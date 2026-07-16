"""
SERVIDOR DE MESAS — módulo gemelo para meseros
------------------------------------------------
Corre un servidor Flask DENTRO de la misma app de la cajera (en un hilo
aparte) para que los meseros, desde el navegador de su celular conectado
al mismo WiFi, puedan abrir mesas y mandar pedidos directamente a la app
principal — sin instalar nada.

Cómo se integra (ver TaqueriaApp en el archivo principal):
    from servidor_mesas import iniciar_servidor, obtener_ip_local

    # dentro de on_start(), después de que self.menu y self.mesas ya existen:
    iniciar_servidor(self)

El servidor NO cobra, NO cancela y NO edita pedidos — solo agrega mesas
nuevas o suma productos a una mesa ya abierta. Cobrar, quitar productos
y cerrar caja se sigue haciendo únicamente desde la app de la cajera,
tal como se pidió.
"""

import os
import socket
import threading
import traceback
import secrets
import copy
from datetime import datetime

from kivy.clock import Clock

try:
    from flask import Flask, jsonify, request, Response
except ImportError:
    Flask = None  # la app principal debe seguir funcionando aunque falte flask

try:
    from zeroconf import ServiceInfo, Zeroconf
except ImportError:
    ServiceInfo = None
    Zeroconf = None  # sin esto, sigue funcionando solo con la IP (como antes)


PUERTO_DEFAULT = 5000

# Nombre "bonito" que se anuncia en la red local via mDNS/Bonjour, para
# que los meseros puedan escribir http://comandero.local:5000 en vez de
# la IP con numeros. Requiere que el navegador del telefono del mesero
# sepa resolver nombres .local -- en Android esto NO esta garantizado al
# 100% (depende de fabricante/version), por eso siempre se sigue
# mostrando tambien la IP y un QR como respaldo infalible.
NOMBRE_MDNS = "comandero.local"

# Sesiones de meseros: token -> nombre del empleado. Vive solo en memoria
# (se resetea si se reinicia la app), es suficiente para uso diario en la
# misma red WiFi local del negocio.
_SESIONES = {}

# Referencia viva del anuncio mDNS, para poder apagarlo limpio en
# detener_servidor() -- igual que ya se hace con el httpd de Flask.
_MDNS = {"zc": None, "info": None}


if __name__ == "__main__":
    print(
        "\n"
        "Este archivo (servidor_mesas.py) NO se corre solo.\n"
        "Es una pieza que usa la app principal por dentro.\n\n"
        "En Pydroid 3, dale 'Run' al archivo:\n"
        "   birria_kivymd_premium-23-2-3.py\n\n"
        "Ese es el que abre la app completa y arranca el servidor\n"
        "de meseros automaticamente al iniciar.\n"
    )


# Candado de multicast: en Android, los paquetes multicast (los que usa
# mDNS para anunciarse en la red) estan bloqueados por default para
# ahorrar bateria. Sin este candado, zeroconf puede arrancar sin tirar
# ningun error, pero nadie en la red ve el anuncio -- por eso Kelvin veia
# "comandero.local" sin responder aun con la libreria ya instalada.
# Requiere el permiso CHANGE_WIFI_MULTICAST_STATE (ver buildozer.spec).
# Fuera de un APK de Android (Pydroid 3, PC) esto simplemente no hace
# nada -- el import de jnius falla y se sigue de largo.
_MULTICAST_LOCK = {"lock": None}


def _adquirir_multicast_lock():
    try:
        from jnius import autoclass, cast
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        Context = autoclass("android.content.Context")
        activity = PythonActivity.mActivity
        wifi_service = activity.getSystemService(Context.WIFI_SERVICE)
        wifi_manager = cast("android.net.wifi.WifiManager", wifi_service)
        lock = wifi_manager.createMulticastLock("comandero_mdns_lock")
        lock.setReferenceCounted(True)
        lock.acquire()
        _MULTICAST_LOCK["lock"] = lock
        print("[servidor_mesas] Multicast lock adquirido (necesario para que mDNS salga a la red)")
    except Exception as e:
        # No es Android (Pydroid/PC), o algo especifico del telefono fallo
        # -- el servidor sigue funcionando normal por IP de cualquier forma.
        print("[servidor_mesas] Multicast lock no disponible:", e)


def _liberar_multicast_lock():
    lock = _MULTICAST_LOCK.get("lock")
    if lock is not None:
        try:
            lock.release()
        except Exception:
            pass
    _MULTICAST_LOCK["lock"] = None


def _iniciar_mdns(puerto, app_kivy=None):
    """Anuncia 'comandero.local' en la red WiFi via mDNS/Bonjour, para que
    los meseros puedan usar http://comandero.local:5000 en vez de la IP.

    Se apoya en la libreria 'zeroconf' (pip install zeroconf, igual que
    se instalo flask). Si no esta instalada, o si algo falla al anunciar
    (puerto, permisos de red, etc.), el servidor sigue funcionando normal
    por IP -- solo no habra nombre bonito disponible.

    Guarda el resultado en app_kivy._mdns_estado = (disponible, motivo)
    para que main.py pueda mostrarlo en el popup en vez de que el error
    se pierda en la consola (que en Pydroid casi nadie revisa)."""
    def _reportar(disponible, motivo):
        if app_kivy is not None:
            app_kivy._mdns_estado = (disponible, motivo)

    if Zeroconf is None:
        _reportar(False, "Falta instalar 'zeroconf' (Pydroid: Pip -> zeroconf).")
        return
    try:
        _adquirir_multicast_lock()
        ip = obtener_ip_local()
        info = ServiceInfo(
            "_http._tcp.local.",
            "Comandero Enoch._http._tcp.local.",
            addresses=[socket.inet_aton(ip)],
            port=puerto,
            server=f"{NOMBRE_MDNS}.",
        )
        zc = Zeroconf()
        zc.register_service(info)
        _MDNS["zc"] = zc
        _MDNS["info"] = info
        print(f"[servidor_mesas] mDNS activo: http://{NOMBRE_MDNS}:{puerto}")
        _reportar(True, None)
    except Exception as e:
        traceback.print_exc()
        _reportar(False, f"No se pudo anunciar mDNS: {e}")


def _detener_mdns():
    zc = _MDNS.get("zc")
    info = _MDNS.get("info")
    if zc is not None:
        try:
            if info is not None:
                zc.unregister_service(info)
            zc.close()
        except Exception:
            pass
    _MDNS["zc"] = None
    _MDNS["info"] = None
    _liberar_multicast_lock()


def obtener_ip_local():
    """IP del celular dentro de la red WiFi actual (no requiere internet,
    solo que haya una ruta de red configurada)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


def _registrar_personas_mesero(app_kivy, mesa, personas):
    """Igual que cuando la cajera abre una mesa libre desde la app: guarda
    cuantas personas llegaron, para que las estadisticas de clientela
    cuadren sin importar quien haya abierto la mesa."""
    try:
        if hasattr(app_kivy, "_registrar_personas_mesa"):
            app_kivy._registrar_personas_mesa(mesa, personas)
    except Exception:
        traceback.print_exc()


# Plazo por default para que la cajera acepte o niegue a un mesero antes
# de que se le niegue el acceso automaticamente (ver _pedir_aprobacion_mesero).
_TIMEOUT_APROBACION_MESERO = 90.0


def _pedir_aprobacion_mesero(app_kivy, nombre, timeout=_TIMEOUT_APROBACION_MESERO):
    """Bloquea esta peticion HTTP -- corre en su propio hilo gracias a
    threaded=True en make_server, asi que NO afecta a otros meseros
    conectados al mismo tiempo -- hasta que la cajera acepte o niegue
    al mesero desde el popup "Usuario: <nombre> / Aceptar / Negar" que
    se abre en la app principal (ver TaqueriaApp._popup_aprobar_mesero
    en main.py), o hasta que pase el plazo sin respuesta.

    Si nadie contesta a tiempo, se niega el acceso por default -- nunca
    se deja pasar solo porque la cajera no vio el aviso."""
    resultado = {"ok": False}
    evento = threading.Event()

    def _mostrar_popup(dt):
        def _responder(aceptado):
            resultado["ok"] = bool(aceptado)
            evento.set()
        try:
            mostrar = getattr(app_kivy, "_popup_aprobar_mesero", None)
            if mostrar is None:
                # Compatibilidad hacia atras: si la app principal es una
                # version vieja sin este popup, se deja pasar directo,
                # tal como funcionaba antes de este cambio.
                resultado["ok"] = True
                evento.set()
                return
            mostrar(nombre, _responder, timeout=timeout)
        except Exception:
            traceback.print_exc()
            resultado["ok"] = True
            evento.set()

    Clock.schedule_once(_mostrar_popup, 0)
    # +2s de colchon sobre el plazo del propio popup, para no cortar la
    # espera un instante antes de que el popup se auto-niegue solo.
    evento.wait(timeout + 2.0)
    return resultado["ok"]


def _en_hilo_kivy(func, timeout=5.0):
    """Ejecuta func() en el hilo PRINCIPAL de Kivy (via Clock.schedule_once)
    y espera aqui mismo, en el hilo de Flask, a que termine -- de forma
    sincrona, usando threading.Event.

    Por que hace falta tambien para LECTURAS como /menu y /mesas: aunque
    Python tiene GIL, iterar una lista (app_kivy.pedidos) mientras OTRO
    hilo le hace append/remove -- justo lo que pasa cuando un mesero manda
    una comanda al mismo tiempo que alguien mas consulta /mesas -- puede
    lanzar 'RuntimeError: list changed size during iteration' de forma
    intermitente. Al leer tambien desde el hilo de Kivy (la unica que
    escribe self.pedidos), esa condicion de carrera desaparece por
    completo, igual que ya pasa con las escrituras."""
    resultado = {}
    evento = threading.Event()

    def _tarea(dt):
        try:
            resultado["valor"] = func()
        except Exception as e:
            resultado["error"] = e
        finally:
            evento.set()

    Clock.schedule_once(_tarea, 0)
    if not evento.wait(timeout):
        raise TimeoutError("La app tardó demasiado en responder")
    if "error" in resultado:
        raise resultado["error"]
    return resultado["valor"]


# ── Servidor Flask ───────────────────────────────────────────────────────────
#
# La lógica de "crear mesa o sumarle productos" YA NO vive aquí: vive en
# app_kivy.procesar_pedido_entrante() (main.py), para que la cajera y los
# meseros usen exactamente el mismo código (mismo esquema de pedido,
# mismo generador de id con uuid4). Este archivo solo se encarga de
# programar esa llamada en el hilo principal de Kivy via Clock -- ver
# la ruta /pedido más abajo.
#
# IMPRESIÓN (ESC/POS + Bluetooth) -- por qué NO vive aquí:
# procesar_pedido_entrante() ya llama internamente a
# app_kivy.imprimir_comanda_cocina(), que arma los bytes ESC/POS (negritas,
# fuente grande para cocina, ancho 58/80mm segun Configuracion) y los manda
# via app_kivy._impresora_bt (ImpresoraBluetoothManager, definido en
# main.py). Este archivo JAMAS abre su propio socket Bluetooth ni construye
# sus propios bytes ESC/POS -- solo reusa las funciones de app_kivy a
# traves de la referencia que ya recibe en _crear_app_flask(app_kivy).
# Razon: solo debe existir UNA conexion Bluetooth activa a la vez; si cada
# hilo de Flask (uno por mesero conectado) abriera su propio socket RFCOMM
# hacia la misma impresora, se pisarian entre si y el hardware rechazaria
# la segunda conexion. Al canalizar todo por Clock.schedule_once hacia el
# hilo principal de Kivy, tambien la impresion queda serializada -- una
# comanda a la vez, en el orden en que llegaron, sin condicion de carrera
# sobre el socket.
#
# Si en el futuro se necesita imprimir algo MAS que la comanda automatica
# (ver /reimprimir mas abajo), la forma correcta es siempre la misma:
# llamar a un metodo publico de app_kivy (imprimir_comanda_cocina,
# imprimir_ticket_cliente, o app_kivy._impresora_bt.abrir_cajon /
# .enviar directamente) -- nunca reimplementar el protocolo ESC/POS ni el
# manejo de socket aqui.

def _crear_app_flask(app_kivy):
    servidor = Flask(__name__)

    def _empleado_del_token(req):
        """Regresa el nombre del empleado dueño del token enviado en el
        header X-Mesero-Token, o None si no hay token valido."""
        token = req.headers.get("X-Mesero-Token", "")
        return _SESIONES.get(token)

    @servidor.route("/")
    def index():
        return Response(PAGINA_HTML, mimetype="text/html")

    @servidor.route("/login", methods=["POST"])
    def login():
        """Valida nombre + contraseña contra los empleados dados de alta
        en Configuracion > Empleados (dentro de la app de la cajera) y
        entrega un token para las siguientes peticiones."""
        datos = request.get_json(force=True, silent=True) or {}
        nombre = (datos.get("nombre") or "").strip()
        password = (datos.get("password") or "").strip()
        if not nombre or not password:
            return jsonify({"ok": False, "error": "Faltan datos"}), 400

        empleados = getattr(app_kivy, "empleados", []) or []
        coincidencia = next(
            (e for e in empleados
             if e.get("nombre", "").strip().lower() == nombre.lower()
             and e.get("password", "") == password),
            None
        )
        if not coincidencia:
            return jsonify({"ok": False, "error": "Nombre o contraseña incorrectos"}), 401

        # La contraseña es correcta, pero antes de entregar el token la
        # cajera tiene que aceptarlo desde un popup en la app principal
        # (ver _pedir_aprobacion_mesero mas arriba). Esto evita que
        # cualquiera que se sepa una contraseña de empleado (activo o ya
        # dado de baja) pueda entrar solo, sin que la cajera se entere.
        if not _pedir_aprobacion_mesero(app_kivy, coincidencia["nombre"]):
            return jsonify({"ok": False, "error": "La cajera no autorizó el acceso"}), 403

        token = secrets.token_hex(16)
        _SESIONES[token] = coincidencia["nombre"]
        return jsonify({"ok": True, "token": token, "nombre": coincidencia["nombre"]})

    @servidor.route("/menu")
    def obtener_menu():
        if not _empleado_del_token(request):
            return jsonify({"error": "No autorizado"}), 401
        try:
            # Se lee dentro del hilo de Kivy (ver _en_hilo_kivy) en vez de
            # tomar app_kivy.menu directo desde este hilo de Flask.
            menu = _en_hilo_kivy(lambda: copy.deepcopy(app_kivy.menu))
        except Exception as e:
            return jsonify({"error": f"No se pudo leer el menú: {e}"}), 500
        return jsonify(menu)

    @servidor.route("/mesas")
    def obtener_mesas():
        if not _empleado_del_token(request):
            return jsonify({"error": "No autorizado"}), 401

        def _leer_mesas():
            # Corre en el hilo principal de Kivy: aqui SI es seguro
            # iterar app_kivy.pedidos y app_kivy.mesas aunque en ese
            # mismo instante llegue otra comanda, porque es el mismo
            # hilo el que procesa ambas cosas, una por una.
            ocupadas = {
                p["mesa"]: p for p in app_kivy.pedidos if p.get("tipo") == "mesa"
            }
            resolver = getattr(app_kivy, "_resolver_mesa_movida", None)
            data = []
            for m in app_kivy.mesas:
                ped = ocupadas.get(m)
                # Si esta mesa quedo libre porque la cajera la movio con
                # CAMBIAR MESA (ver _mover_pedido_a_mesa en main.py), se
                # avisa a donde se fue -- asi el mesero que sigue viendo
                # esta mesa en su pantalla sabe que su pedido se cambio.
                movida_a = None
                if ped is None and resolver is not None:
                    nueva = resolver(m)
                    if nueva != m:
                        movida_a = nueva
                data.append({
                    "nombre": m,
                    "ocupada": ped is not None,
                    "items": copy.deepcopy(ped["items"]) if ped else [],
                    "total": ped["total"] if ped else 0,
                    "empleado": ped.get("empleado") if ped else None,
                    "movida_a": movida_a,
                })
            return data

        try:
            data = _en_hilo_kivy(_leer_mesas)
        except Exception as e:
            return jsonify({"error": f"No se pudo leer las mesas: {e}"}), 500
        return jsonify(data)

    @servidor.route("/pedido", methods=["POST"])
    def recibir_pedido():
        empleado = _empleado_del_token(request)
        if not empleado:
            return jsonify({"ok": False, "error": "No autorizado"}), 401

        datos = request.get_json(force=True, silent=True) or {}
        mesa = datos.get("mesa")
        items = datos.get("items", [])
        if not mesa or not items:
            return jsonify({"ok": False, "error": "Faltan datos"}), 400

        # Si la cajera ya movió esta mesa (CAMBIAR MESA en la app
        # principal) desde que el mesero cargó su pantalla, se resuelve
        # el nombre real ANTES de guardar -- así la comanda cae en el
        # pedido correcto en vez de crear uno fantasma duplicado en la
        # mesa vieja, que ya quedó libre.
        resolver = getattr(app_kivy, "_resolver_mesa_movida", None)
        try:
            mesa_resuelta = _en_hilo_kivy(lambda: resolver(mesa)) if resolver else mesa
        except Exception:
            mesa_resuelta = mesa

        # IMPORTANTE - hilo: esta ruta corre en el hilo de Flask, pero
        # procesar_pedido_entrante toca self.pedidos y refresca la UI de
        # Kivy, que NO es thread-safe. Por eso nunca se llama directo
        # aquí -- se programa con Clock.schedule_once para que la
        # ejecute el hilo principal de Kivy. Si llegan varias comandas
        # casi al mismo tiempo desde distintos meseros (distintos hilos
        # de Flask), Kivy las procesa una por una, en orden de llegada,
        # asi que no hay condicion de carrera sobre self.pedidos.
        Clock.schedule_once(
            lambda dt: app_kivy.procesar_pedido_entrante(mesa_resuelta, items, empleado), 0
        )
        respuesta = {"ok": True}
        if mesa_resuelta != mesa:
            respuesta["mesa_reasignada"] = mesa_resuelta
        return jsonify(respuesta)

    @servidor.route("/reimprimir", methods=["POST"])
    def reimprimir_comanda():
        """Por si la comanda automatica no salio (ej. la impresora estaba
        reconectando justo en ese momento -- ver ImpresoraBluetoothManager
        en main.py). El mesero puede pedir que se vuelva a mandar TODO lo
        que lleva la mesa ahora mismo. NO reimplementa nada de ESC/POS ni
        de Bluetooth aqui: solo llama a app_kivy.imprimir_comanda_cocina(),
        exactamente la misma funcion que usa procesar_pedido_entrante."""
        empleado = _empleado_del_token(request)
        if not empleado:
            return jsonify({"ok": False, "error": "No autorizado"}), 401

        datos = request.get_json(force=True, silent=True) or {}
        mesa = datos.get("mesa")
        if not mesa:
            return jsonify({"ok": False, "error": "Falta la mesa"}), 400

        def _reimprimir():
            resolver = getattr(app_kivy, "_resolver_mesa_movida", None)
            mesa_resuelta = resolver(mesa) if resolver else mesa
            pedido = next(
                (p for p in app_kivy.pedidos
                 if p.get("tipo") == "mesa" and p.get("mesa") == mesa_resuelta),
                None
            )
            if not pedido or not pedido.get("items"):
                return False
            # Misma llamada que usa procesar_pedido_entrante() -- reusa el
            # ImpresoraBluetoothManager de app_kivy, con su reconexion
            # automatica a la MAC guardada si hacia falta.
            app_kivy.imprimir_comanda_cocina(
                mesa_resuelta, None, pedido.get("empleado"),
                copy.deepcopy(pedido["items"])
            )
            return True

        try:
            enviado = _en_hilo_kivy(_reimprimir)
        except Exception as e:
            return jsonify({"ok": False, "error": f"No se pudo reimprimir: {e}"}), 500

        if not enviado:
            return jsonify({"ok": False, "error": "Esa mesa no tiene pedido activo"}), 404
        return jsonify({"ok": True})

    @servidor.route("/personas", methods=["POST"])
    def registrar_personas():
        if not _empleado_del_token(request):
            return jsonify({"ok": False, "error": "No autorizado"}), 401

        datos = request.get_json(force=True, silent=True) or {}
        mesa = datos.get("mesa")
        personas = datos.get("personas")
        if not mesa or not isinstance(personas, int) or personas < 1:
            return jsonify({"ok": False, "error": "Faltan datos"}), 400

        resolver = getattr(app_kivy, "_resolver_mesa_movida", None)
        try:
            mesa_resuelta = _en_hilo_kivy(lambda: resolver(mesa)) if resolver else mesa
        except Exception:
            mesa_resuelta = mesa

        Clock.schedule_once(
            lambda dt: _registrar_personas_mesero(app_kivy, mesa_resuelta, personas), 0
        )
        respuesta = {"ok": True}
        if mesa_resuelta != mesa:
            respuesta["mesa_reasignada"] = mesa_resuelta
        return jsonify(respuesta)

    return servidor


def iniciar_servidor(app_kivy, puerto=PUERTO_DEFAULT, on_error=None):
    """Arranca el servidor en un hilo daemon (no bloquea la app de Kivy).
    Seguro de llamar aunque Flask no este instalado: en ese caso no hace
    nada y la app de la cajera sigue funcionando normal.

    ── Punto crítico de threading ──────────────────────────────────────
    Flask (via werkzeug.serving.make_server + httpd.serve_forever()) se
    ejecuta ENTERO dentro de threading.Thread(daemon=True) mas abajo, en
    un hilo secundario, nunca en el hilo principal de Kivy. Si esto
    corriera en el hilo principal, cada peticion HTTP entrante congelaria
    la interfaz (ANR) hasta que Flask terminara de atenderla. daemon=True
    ademas asegura que este hilo muera solo si la app principal se cierra,
    sin dejar el puerto ocupado ni el proceso colgado en segundo plano.

    Si algo falla (puerto ocupado, dependencia rota, etc.) NUNCA se deja
    escapar la excepcion hacia Kivy -- se captura, se guarda el traceback
    completo y se avisa via `on_error(texto)` para poder mostrarlo en
    pantalla (la persona no tiene por que revisar consolas ni logs)."""
    if Flask is None:
        if on_error:
            on_error("Flask no esta instalado. En Pydroid 3: Menu -> Pip -> "
                      "buscar 'flask' -> Instalar.")
        return None

    def _run():
        try:
            servidor = _crear_app_flask(app_kivy)
            # Se usa make_server en vez de app.run() a proposito: app.run()
            # imprime un banner que en algunos telefonos hace una consulta
            # de DNS/hostname que puede tardar mucho o colgarse. make_server
            # evita ese banner y arranca directo.
            from werkzeug.serving import make_server
            _cp = getattr(app_kivy, "_checkpoint_externo", None)
            if _cp: _cp(f"[servidor_mesas] a punto de bindear puerto {puerto}")
            httpd = make_server("0.0.0.0", puerto, servidor, threaded=True)
            # Se guarda la referencia en la app para poder apagarlo despues
            # de forma limpia (ver detener_servidor() mas abajo) -- sin
            # esto, no habria manera de liberar el puerto sin matar todo
            # el proceso.
            app_kivy._httpd_servidor_mesas = httpd
            if _cp: _cp(f"[servidor_mesas] puerto {puerto} bindeado, entrando a serve_forever")
            print(f"[servidor_mesas] Activo en http://{obtener_ip_local()}:{puerto}")
            _iniciar_mdns(puerto, app_kivy)
            httpd.serve_forever()
            # Si llegamos aqui es porque detener_servidor() llamo a
            # httpd.shutdown() (cierre limpio) -- NO es un error.
            if _cp: _cp(f"[servidor_mesas] serve_forever() termino (apagado limpio)")
        except OSError as e:
            msg = (f"No se pudo abrir el puerto {puerto} (¿ya estaba "
                   f"corriendo de un intento anterior? Cierra Pydroid "
                   f"por completo y vuelve a abrir la app). Detalle: {e}")
            print("[servidor_mesas]", msg)
            _guardar_traceback_archivo(app_kivy, msg)
            if on_error:
                Clock.schedule_once(lambda dt: on_error(msg), 0)
        except Exception as e:
            texto_tb = traceback.format_exc()
            print("[servidor_mesas] Error al iniciar:\n", texto_tb)
            ruta_guardada = _guardar_traceback_archivo(app_kivy, texto_tb)
            if on_error:
                detalle_ruta = (f"\n\nSe guardó el detalle completo en:\n{ruta_guardada}"
                                 if ruta_guardada else
                                 "\n\n(No se pudo guardar el detalle en un archivo)")
                Clock.schedule_once(
                    lambda dt: on_error(f"{e}{detalle_ruta}"),
                    0,
                )

    hilo = threading.Thread(target=_run, daemon=True)
    hilo.start()
    return hilo


def detener_servidor(app_kivy, espera=2.0):
    """Apaga el servidor Flask/werkzeug de forma limpia y libera el puerto.

    Debe llamarse en TRES momentos (ver main.py):
      1) Cierre normal -- App.on_stop().
      2) Salida desde la pantalla principal -- el boton "Salir" del popup
         de confirmacion llama App.stop(), que dispara on_stop() de
         cualquier forma, asi que queda cubierto por el mismo punto 1.
      3) Crash no atrapado -- sys.excepthook (_guardar_error en main.py),
         para que una excepcion en el hilo principal no deje el hilo
         daemon de Flask vivo con el puerto abierto mientras el proceso
         tarde en morir del todo.

    httpd.shutdown() detiene el bucle serve_forever() (normalmente en
    menos de medio segundo, el intervalo interno de sondeo de
    socketserver) y httpd.server_close() cierra el socket de escucha,
    liberando el puerto para el siguiente arranque -- exactamente el
    problema que antes obligaba a "cerrar Pydroid por completo" cuando
    el puerto quedaba ocupado de un intento anterior.

    Se corre en un hilo aparte con timeout, en vez de bloquear el hilo
    que llama (que puede ser el propio hilo principal de Kivy durante
    on_stop, o el hilo que dispara el excepthook), por si algo se cuelga
    y así nunca congela el cierre de la app."""
    httpd = getattr(app_kivy, "_httpd_servidor_mesas", None)
    if httpd is None:
        return  # nunca llego a arrancar, o ya se apago antes

    def _apagar():
        try:
            httpd.shutdown()
        except Exception:
            pass
        try:
            httpd.server_close()
        except Exception:
            pass
        _detener_mdns()

    hilo = threading.Thread(target=_apagar, daemon=True)
    hilo.start()
    hilo.join(timeout=espera)
    app_kivy._httpd_servidor_mesas = None


def _carpeta_de_la_app(app_kivy):
    """Usa la MISMA carpeta que ya usa la app principal para su base de
    datos (la que cambia segun el nombre del negocio en Configuracion),
    en vez de una ruta fija aparte -- asi el error queda junto a todo
    lo demas y es facil de encontrar.

    Desde que app_kivy._db_path() vive dentro de self.user_data_dir (ver
    main.py), esta funcion hereda ese cambio automaticamente sin tocar
    nada aqui. El fallback, por si _db_path() llega a fallar, tampoco
    apunta ya a la raiz del storage (que puede dar PermissionError en
    Android 10+): usa la carpeta del propio script, que es donde ya
    escribe otros archivos de arranque de esta app."""
    try:
        return os.path.dirname(app_kivy._db_path())
    except Exception:
        return os.path.dirname(os.path.abspath(__file__))


def _guardar_traceback_archivo(app_kivy, texto):
    """Guarda el error completo en un archivo de texto DENTRO de la
    carpeta del negocio (la misma que usa la BD de ventas), para poder
    revisarlo despues sin depender de la consola de Pydroid."""
    try:
        carpeta = _carpeta_de_la_app(app_kivy)
        os.makedirs(carpeta, exist_ok=True)
        ruta = os.path.join(carpeta, "error_servidor_mesas.txt")
        with open(ruta, "w", encoding="utf-8") as f:
            f.write("=== Error servidor de mesas ===\n")
            f.write("Fecha: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "\n\n")
            f.write(texto)
        return ruta
    except Exception:
        return None


# ── Página web del mesero (un solo archivo, sin dependencias externas) ──────

PAGINA_HTML = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<title>Mesas — Mesero</title>
<style>
  :root{
    --oscuro:#1c1210; --tarjeta:#2a1c19; --rojo:#b3312c; --dorado:#d9a441;
    --verde:#3ea35a; --texto:#f3e9df; --texto-tenue:#c9b8ab;
  }
  *{box-sizing:border-box; -webkit-tap-highlight-color:transparent;}
  html,body{margin:0; padding:0; height:100%; background:var(--oscuro);
    color:var(--texto); font-family:"Segoe UI",Roboto,Arial,sans-serif;
    overscroll-behavior:none; user-select:none;}
  header{padding:16px 16px 10px; position:sticky; top:0; background:var(--oscuro);
    z-index:20; border-bottom:1px solid #3a2b26;}
  header h1{margin:0; font-size:19px; letter-spacing:.5px; color:var(--dorado);}
  header p{margin:2px 0 0; font-size:12px; color:var(--texto-tenue);}
  .pantalla{padding:14px; padding-bottom:110px;}
  .oculto{display:none !important;}

  /* Grid de mesas */
  .grid-mesas{display:grid; grid-template-columns:repeat(2,1fr); gap:12px;}
  .mesa-card{background:var(--tarjeta); border-radius:14px; padding:16px;
    text-align:center; border:2px solid transparent;}
  .mesa-card.ocupada{border-color:var(--rojo); background:#3a2020;}
  .mesa-card.libre{border-color:#3a2b26;}
  .mesa-card .nombre{font-weight:700; font-size:16px;}
  .mesa-card .estado{font-size:12px; margin-top:4px; color:var(--texto-tenue);}
  .mesa-card.ocupada .estado{color:var(--dorado);}
  .mesa-card .total{font-size:13px; color:var(--dorado); margin-top:6px; font-weight:600;}

  /* Tabs de categoría */
  .tabs{display:flex; gap:8px; overflow-x:auto; padding-bottom:10px; margin-bottom:6px;}
  .tab{flex:0 0 auto; padding:9px 16px; border-radius:20px; font-size:13px;
    background:var(--tarjeta); color:var(--texto-tenue); white-space:nowrap;}
  .tab.activa{background:var(--rojo); color:#fff; font-weight:600;}

  .producto{display:flex; justify-content:space-between; align-items:center;
    background:var(--tarjeta); border-radius:12px; padding:14px 16px; margin-bottom:10px;}
  .producto .nombre{font-size:14.5px;}
  .producto .precio{font-size:12.5px; color:var(--dorado); margin-top:2px;}
  .btn-agregar{background:var(--rojo); color:#fff; border:none; border-radius:10px;
    padding:10px 16px; font-size:13px; font-weight:600;}

  /* Barra inferior de carrito */
  .barra-carrito{position:fixed; left:0; right:0; bottom:0; background:var(--tarjeta);
    border-top:1px solid #3a2b26; padding:12px 16px; display:flex;
    justify-content:space-between; align-items:center; gap:10px;}
  .barra-carrito .info{font-size:13px;}
  .barra-carrito .info b{color:var(--dorado); font-size:15px; display:block;}
  .btn-primario{background:var(--verde); color:#fff; border:none; border-radius:10px;
    padding:13px 22px; font-size:14px; font-weight:700;}
  .btn-primario:disabled{background:#3a2b26; color:#7a6a60;}

  /* Pantalla de carrito/resumen */
  .fila-carrito{display:flex; justify-content:space-between; align-items:center;
    background:var(--tarjeta); border-radius:12px; padding:12px 14px; margin-bottom:8px;}
  .fila-carrito .nota-item{font-size:12px; color:var(--dorado); margin-top:4px;
    font-style:italic;}
  .btn-nota{background:none; border:none; color:var(--texto-tenue);
    font-size:11.5px; text-decoration:underline; padding:6px 0 0; text-align:left;}
  .qty-controles{display:flex; align-items:center; gap:10px;}
  .qty-controles button{width:30px; height:30px; border-radius:8px; border:none;
    background:var(--rojo); color:#fff; font-size:16px; line-height:1;}
  .top-bar{display:flex; align-items:center; gap:10px; margin-bottom:14px;}
  .btn-volver{background:none; border:none; color:var(--dorado); font-size:22px; padding:4px 8px;}
  .top-bar h2{margin:0; font-size:17px;}

  .toast{position:fixed; top:70px; left:50%; transform:translateX(-50%);
    background:var(--verde); color:#fff; padding:10px 18px; border-radius:10px;
    font-size:13px; z-index:50; opacity:0; transition:opacity .25s;}
  .toast.mostrar{opacity:1;}

  .modal-fondo{position:fixed; inset:0; background:rgba(0,0,0,.6); z-index:60;
    display:flex; align-items:flex-end;}
  .modal-caja{background:var(--tarjeta); width:100%; border-radius:16px 16px 0 0;
    padding:20px 18px 26px;}
  .modal-caja input{width:100%; padding:12px; border-radius:10px; border:1px solid #4a3a33;
    background:#1c1210; color:var(--texto); font-size:14px; margin-top:10px;}
  .modal-caja .fila-btns{display:flex; gap:10px; margin-top:16px;}
  .modal-caja .fila-btns button{flex:1; padding:12px; border-radius:10px; border:none; font-weight:600;}

  /* Pantalla de ticket (lo que ya lleva pedido la mesa) */
  .ticket-box{background:#f5ede1; color:#241813; border-radius:6px;
    padding:20px 18px; font-family:"Courier New",monospace;
    box-shadow:0 4px 16px rgba(0,0,0,.35);}
  .ticket-box .titulo-ticket{text-align:center; font-weight:700; font-size:15px;
    letter-spacing:1px; margin-bottom:4px;}
  .ticket-box .sep{border-top:1px dashed #8a7a6a; margin:10px 0;}
  .ticket-box .linea-ticket{display:flex; justify-content:space-between;
    font-size:13px; padding:4px 0; gap:10px;}
  .ticket-box .linea-ticket .cant{color:#5a4a3f; white-space:nowrap;}
  .ticket-box .total-ticket{display:flex; justify-content:space-between;
    font-weight:700; font-size:16px; margin-top:4px;}
  .ticket-vacio{color:var(--texto-tenue); text-align:center; padding:40px 16px;
    font-size:13.5px; line-height:1.5;}
  .btn-agregar-producto{width:100%; margin-top:18px; background:var(--verde);
    color:#fff; border:none; border-radius:12px; padding:15px; font-size:15px;
    font-weight:700;}

  /* Modal: cuantas personas hay en la mesa */
  .contador-personas{display:flex; align-items:center; justify-content:center;
    gap:20px; margin:18px 0 6px;}
  .contador-personas button{width:52px; height:52px; border-radius:12px; border:none;
    font-size:22px; font-weight:700; color:#fff;}
  .contador-personas .btn-menos{background:var(--rojo);}
  .contador-personas .btn-mas{background:var(--dorado);}
  .contador-personas .num-personas{font-size:28px; font-weight:700; min-width:44px;
    text-align:center;}

  /* Pantalla de login (pide clave de empleado) */
  .pantalla-login{display:flex; align-items:center; justify-content:center;
    min-height:100vh; padding:24px;}
  .caja-login{background:var(--tarjeta); border-radius:16px; padding:26px 22px;
    width:100%; max-width:340px;}
  .caja-login h2{margin:0 0 4px; color:var(--dorado); text-align:center;}
  .caja-login p{margin:0 0 18px; font-size:12.5px; color:var(--texto-tenue); text-align:center;}
  .caja-login input{width:100%; padding:13px; border-radius:10px; border:1px solid #4a3a33;
    background:#1c1210; color:var(--texto); font-size:14px; margin-top:10px;}
  .caja-login button{width:100%; margin-top:16px; background:var(--verde); color:#fff;
    border:none; border-radius:10px; padding:13px; font-size:14px; font-weight:700;}
  .caja-login .error-login{color:#e07a6f; font-size:12.5px; text-align:center;
    margin-top:10px; min-height:16px;}
  .btn-salir{background:none; border:none; color:var(--texto-tenue); font-size:12px;
    text-decoration:underline; padding:2px 0;}
</style>
</head>
<body>

<!-- PANTALLA 0: Login del mesero (pide nombre y contraseña) -->
<div id="pantalla-login" class="pantalla-login">
  <div class="caja-login">
    <h2>Mesas</h2>
    <p>Ingresa tu nombre y tu contraseña para tomar pedidos.</p>
    <input type="text" id="login-nombre" placeholder="Tu nombre" autocomplete="off">
    <input type="password" id="login-password" placeholder="Contraseña">
    <button id="btn-login">ENTRAR</button>
    <div class="error-login" id="error-login"></div>
  </div>
</div>

<div id="app-mesero" class="oculto">
<header>
  <h1 id="titulo-header">Mesas</h1>
  <p id="sub-header">Toca una mesa para tomar el pedido</p>
  <p style="margin:6px 0 0; font-size:11.5px;">
    <span id="txt-mesero-actual" style="color:var(--dorado);"></span>
    &nbsp;·&nbsp;
    <button class="btn-salir" onclick="cerrarSesion()">Salir</button>
  </p>
</header>

<!-- PANTALLA 1: Grid de mesas -->
<div id="pantalla-mesas" class="pantalla">
  <div class="grid-mesas" id="grid-mesas"></div>
</div>

<!-- PANTALLA 1.5: Ticket de la mesa (lo que ya lleva pedido) -->
<div id="pantalla-ticket" class="pantalla oculto">
  <div class="top-bar">
    <button class="btn-volver" onclick="volverAMesas()">←</button>
    <h2 id="titulo-mesa-ticket">Mesa</h2>
  </div>
  <div id="ticket-mesa"></div>
  <button class="btn-agregar-producto" onclick="mostrarPantalla('menu')">+ Agregar producto</button>
</div>

<!-- PANTALLA 2: Menú de la mesa seleccionada -->
<div id="pantalla-menu" class="pantalla oculto">
  <div class="top-bar">
    <button class="btn-volver" onclick="mostrarPantalla('ticket')">←</button>
    <h2 id="titulo-mesa">Mesa</h2>
  </div>
  <div class="tabs" id="tabs-categorias"></div>
  <div id="lista-productos"></div>
</div>

<!-- PANTALLA 3: Carrito / confirmar envío -->
<div id="pantalla-carrito" class="pantalla oculto">
  <div class="top-bar">
    <button class="btn-volver" onclick="mostrarPantalla('menu')">←</button>
    <h2>Confirmar pedido</h2>
  </div>
  <p style="margin:0 0 10px; font-size:12px; color:var(--texto-tenue);">
    Esto es lo NUEVO que se va a sumar a lo que ya lleva la mesa.
  </p>
  <div id="lista-carrito"></div>
</div>

<div class="barra-carrito" id="barra-carrito">
  <div class="info">
    <span id="txt-items">0 productos</span>
    <b id="txt-total">$0</b>
  </div>
  <button class="btn-primario" id="btn-accion-carrito" disabled onclick="alPresionarBarra()">Ver pedido</button>
</div>

<div class="toast" id="toast"></div>
</div><!-- /#app-mesero -->

<script>
let MENU = {};
let MESAS = [];
let mesaActual = null;
let carrito = []; // {id, nombre, precio, qty, es_extra, nota}
let pantalla = "mesas"; // mesas | menu | carrito
let catActiva = null;
let TOKEN = localStorage.getItem("mesero_token") || null;
let MESERO_NOMBRE = localStorage.getItem("mesero_nombre") || null;

// Envuelve fetch agregando el token del mesero. Si el servidor responde
// 401 (token invalido o vencido), regresa a la pantalla de login.
async function apiFetch(url, opts){
  opts = opts || {};
  opts.headers = Object.assign({}, opts.headers, {"X-Mesero-Token": TOKEN || ""});
  const r = await fetch(url, opts);
  if (r.status === 401){
    cerrarSesion();
    throw new Error("No autorizado");
  }
  return r;
}

function mostrarErrorLogin(msg){
  document.getElementById("error-login").textContent = msg;
}

async function intentarLogin(){
  const nombre = document.getElementById("login-nombre").value.trim();
  const password = document.getElementById("login-password").value;
  if (!nombre || !password){
    mostrarErrorLogin("Escribe tu nombre y tu contraseña");
    return;
  }
  const btn = document.getElementById("btn-login");
  btn.disabled = true; btn.textContent = "Esperando aprobación de caja...";
  try{
    const r = await fetch("/login", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({nombre, password})
    });
    const data = await r.json();
    if (data.ok){
      TOKEN = data.token;
      MESERO_NOMBRE = data.nombre;
      localStorage.setItem("mesero_token", TOKEN);
      localStorage.setItem("mesero_nombre", MESERO_NOMBRE);
      await entrarComoMesero();
    } else {
      mostrarErrorLogin(data.error || "Nombre o contraseña incorrectos");
    }
  } catch(e){
    mostrarErrorLogin("Sin conexión con la caja");
  }
  btn.disabled = false; btn.textContent = "ENTRAR";
}

function cerrarSesion(){
  TOKEN = null; MESERO_NOMBRE = null;
  localStorage.removeItem("mesero_token");
  localStorage.removeItem("mesero_nombre");
  document.getElementById("app-mesero").classList.add("oculto");
  document.getElementById("pantalla-login").classList.remove("oculto");
  document.getElementById("login-password").value = "";
}

async function entrarComoMesero(){
  document.getElementById("pantalla-login").classList.add("oculto");
  document.getElementById("app-mesero").classList.remove("oculto");
  document.getElementById("txt-mesero-actual").textContent = "Mesero/a: " + MESERO_NOMBRE;
  try{
    await cargarMenu();
    await cargarMesas();
    document.getElementById("barra-carrito").style.display = "none";
  } catch(e){ /* apiFetch ya regreso al login si el token no sirve */ }
}

async function cargarMenu(){
  const r = await apiFetch("/menu");
  MENU = await r.json();
  catActiva = Object.keys(MENU)[0];
}

async function cargarMesas(){
  const r = await apiFetch("/mesas");
  MESAS = await r.json();
  pintarMesas();
}

function pintarMesas(){
  const grid = document.getElementById("grid-mesas");
  grid.innerHTML = "";
  MESAS.forEach(m => {
    const card = document.createElement("div");
    card.className = "mesa-card " + (m.ocupada ? "ocupada" : "libre");
    card.innerHTML = `
      <div class="nombre">${m.nombre}</div>
      <div class="estado">${m.ocupada ? "Ocupada" : "Libre"}</div>
      ${m.ocupada && m.empleado ? `<div class="estado" style="font-size:10.5px;">Atiende: ${m.empleado}</div>` : ""}
      ${m.ocupada ? `<div class="total">$${Math.round(m.total)}</div>` : ""}
      ${m.movida_a ? `<div class="estado" style="font-size:10.5px; color:#7aa8ff;">→ Se movió a ${m.movida_a}</div>` : ""}
    `;
    card.onclick = () => abrirMesa(m.nombre);
    grid.appendChild(card);
  });
}

function avisarSiReasignada(json){
  // Si el servidor redirigio solo la comanda/personas porque la mesa
  // que se tenia seleccionada ya se habia movido con CAMBIAR MESA en
  // la app principal, se avisa aqui para que no quede duda de a donde
  // fue a parar el pedido.
  if (json && json.mesa_reasignada){
    alert(`Esta mesa se movió a ${json.mesa_reasignada}. Tu pedido se guardó ahí.`);
    cargarMesas();
  }
}

function abrirMesa(nombre){
  const info = MESAS.find(m => m.nombre === nombre);
  if (info && info.ocupada){
    entrarAMesa(nombre);
  } else {
    preguntarPersonas(nombre);
  }
}

function preguntarPersonas(nombre){
  let n = 2;
  const fondo = document.createElement("div");
  fondo.className = "modal-fondo";
  fondo.innerHTML = `
    <div class="modal-caja">
      <div style="text-align:center; font-weight:700; color:var(--dorado); font-size:16px;">${nombre}</div>
      <div style="text-align:center; margin-top:6px; font-size:14px;">¿Cuántas personas hay en la mesa?</div>
      <div class="contador-personas">
        <button class="btn-menos" id="btn-menos-personas">−</button>
        <span class="num-personas" id="num-personas">2</span>
        <button class="btn-mas" id="btn-mas-personas">+</button>
      </div>
      <div class="fila-btns">
        <button style="background:#4a3a33; color:#fff;" id="btn-cancelar-personas">Cancelar</button>
        <button style="background:var(--verde); color:#fff;" id="btn-abrir-mesa">ABRIR MESA</button>
      </div>
    </div>`;
  document.body.appendChild(fondo);

  const lblNum = fondo.querySelector("#num-personas");
  fondo.querySelector("#btn-menos-personas").onclick = () => {
    n = Math.max(1, n - 1); lblNum.textContent = n;
  };
  fondo.querySelector("#btn-mas-personas").onclick = () => {
    n = Math.min(60, n + 1); lblNum.textContent = n;
  };
  fondo.querySelector("#btn-cancelar-personas").onclick = () => fondo.remove();
  fondo.querySelector("#btn-abrir-mesa").onclick = async () => {
    fondo.remove();
    try{
      await apiFetch("/personas", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({mesa: nombre, personas: n})
      });
    } catch(e){ /* si falla el registro de personas, igual dejamos tomar el pedido */ }
    entrarAMesa(nombre);
  };
}

function entrarAMesa(nombre){
  mesaActual = nombre;
  carrito = [];
  document.getElementById("titulo-mesa-ticket").textContent = nombre;
  document.getElementById("titulo-mesa").textContent = nombre;
  pintarTabs();
  pintarProductos();
  actualizarBarra();
  const info = MESAS.find(m => m.nombre === nombre);
  if (info && info.ocupada){
    pintarTicketMesa(nombre);
    mostrarPantalla("ticket");
  } else {
    // Mesa recien abierta (aun sin productos): directo a tomar el pedido
    mostrarPantalla("menu");
  }
}

function pintarTicketMesa(nombre){
  const box = document.getElementById("ticket-mesa");
  const info = MESAS.find(m => m.nombre === nombre);
  if (!info || !info.ocupada || !info.items || info.items.length === 0){
    box.innerHTML = `
      <div class="ticket-box">
        <div class="titulo-ticket">MESA ${nombre}</div>
        <div class="ticket-vacio">Aún no hay pedido en esta mesa.<br>
        Toca "Agregar producto" para empezar.</div>
      </div>`;
    return;
  }
  const filas = info.items.map(it => `
    <div class="linea-ticket">
      <span class="cant">${it.qty || 1}×</span>
      <span style="flex:1;">
        ${it.nombre}
        ${it._nota ? `<br><span style="font-size:11px; color:#8a6a4a; font-style:italic;">📝 ${it._nota}</span>` : ""}
      </span>
      <span>$${Math.round((it.precio || 0) * (it.qty || 1))}</span>
    </div>
  `).join("");
  box.innerHTML = `
    <div class="ticket-box">
      <div class="titulo-ticket">MESA ${nombre}</div>
      <div class="sep"></div>
      ${filas}
      <div class="sep"></div>
      <div class="total-ticket"><span>TOTAL</span><span>$${Math.round(info.total)}</span></div>
    </div>
  `;
}

function volverAMesas(){
  cargarMesas();
  mostrarPantalla("mesas");
}

function pintarTabs(){
  const box = document.getElementById("tabs-categorias");
  box.innerHTML = "";
  Object.keys(MENU).forEach(cat => {
    const t = document.createElement("div");
    t.className = "tab" + (cat === catActiva ? " activa" : "");
    t.textContent = cat;
    t.onclick = () => { catActiva = cat; pintarTabs(); pintarProductos(); };
    box.appendChild(t);
  });
}

function pintarProductos(){
  const box = document.getElementById("lista-productos");
  box.innerHTML = "";
  (MENU[catActiva] || []).forEach(prod => {
    const row = document.createElement("div");
    row.className = "producto";
    row.innerHTML = `
      <div>
        <div class="nombre">${prod.nombre}</div>
        <div class="precio">${prod.es_extra ? "Monto libre" : "$" + prod.precio}</div>
      </div>
      <button class="btn-agregar">Agregar</button>
    `;
    row.querySelector("button").onclick = () => {
      if (prod.es_extra) { pedirExtra(prod); return; }
      agregarAlCarrito(prod);
    };
    box.appendChild(row);
  });
}

function pedirExtra(prod){
  const fondo = document.createElement("div");
  fondo.className = "modal-fondo";
  fondo.innerHTML = `
    <div class="modal-caja">
      <div style="font-weight:700; margin-bottom:4px;">${prod.nombre}</div>
      <input type="text" id="extra-desc" placeholder="Descripción">
      <input type="number" id="extra-monto" placeholder="Monto ($)">
      <div class="fila-btns">
        <button style="background:#4a3a33; color:#fff;" onclick="this.closest('.modal-fondo').remove()">Cancelar</button>
        <button style="background:var(--verde); color:#fff;" id="btn-confirmar-extra">Agregar</button>
      </div>
    </div>`;
  document.body.appendChild(fondo);
  fondo.querySelector("#btn-confirmar-extra").onclick = () => {
    const desc = fondo.querySelector("#extra-desc").value.trim() || prod.nombre;
    const monto = parseFloat(fondo.querySelector("#extra-monto").value) || 0;
    if (monto <= 0){ return; }
    agregarAlCarrito({id: prod.id, nombre: desc, precio: monto});
    fondo.remove();
  };
}

function agregarAlCarrito(prod){
  // Solo se fusiona con un renglon existente SIN nota: un renglon que ya
  // tiene un comentario ("sin cebolla") representa un plato especifico y
  // no debe absorber en silencio un plato nuevo sin ese comentario.
  const existente = carrito.find(i => i.id === prod.id && i.nombre === prod.nombre && !i.nota);
  if (existente){ existente.qty += 1; }
  else { carrito.push({id: prod.id, nombre: prod.nombre, precio: prod.precio, qty: 1, nota: ""}); }
  actualizarBarra();
  mostrarToast(prod.nombre + " agregado");
}

function editarNotaCarrito(idx){
  const it = carrito[idx];
  const fondo = document.createElement("div");
  fondo.className = "modal-fondo";
  fondo.innerHTML = `
    <div class="modal-caja">
      <div style="font-weight:700; margin-bottom:4px;">${it.nombre}</div>
      <input type="text" id="input-nota" placeholder="Comentario (ej. sin cebolla, bien dorado)">
      <div class="fila-btns">
        <button style="background:#4a3a33; color:#fff;" onclick="this.closest('.modal-fondo').remove()">Cancelar</button>
        <button style="background:var(--verde); color:#fff;" id="btn-guardar-nota">Guardar</button>
      </div>
    </div>`;
  document.body.appendChild(fondo);
  const inp = fondo.querySelector("#input-nota");
  inp.value = it.nota || "";
  inp.focus();
  const guardar = () => {
    carrito[idx].nota = inp.value.trim();
    fondo.remove();
    pintarCarrito();
  };
  fondo.querySelector("#btn-guardar-nota").onclick = guardar;
  inp.addEventListener("keydown", e => { if (e.key === "Enter") guardar(); });
}

function cambiarQty(idx, delta){
  carrito[idx].qty += delta;
  if (carrito[idx].qty <= 0) carrito.splice(idx, 1);
  actualizarBarra();
  pintarCarrito();
}

function totalCarrito(){
  return carrito.reduce((s,i) => s + i.precio * i.qty, 0);
}
function itemsCarrito(){
  return carrito.reduce((s,i) => s + i.qty, 0);
}

function actualizarBarra(){
  document.getElementById("txt-items").textContent = itemsCarrito() + " productos";
  document.getElementById("txt-total").textContent = "$" + Math.round(totalCarrito());
  const btn = document.getElementById("btn-accion-carrito");
  btn.disabled = carrito.length === 0;
  btn.textContent = pantalla === "carrito" ? "Enviar a caja" : "Ver pedido";
}

function alPresionarBarra(){
  if (carrito.length === 0) return;
  if (pantalla !== "carrito"){ mostrarPantalla("carrito"); return; }
  enviarPedido();
}

function pintarCarrito(){
  const box = document.getElementById("lista-carrito");
  box.innerHTML = "";
  if (carrito.length === 0){
    box.innerHTML = '<p style="color:var(--texto-tenue); text-align:center; margin-top:30px;">Carrito vacío</p>';
    return;
  }
  carrito.forEach((it, idx) => {
    const row = document.createElement("div");
    row.className = "fila-carrito";
    row.innerHTML = `
      <div style="flex:1; padding-right:10px;">
        <div class="nombre">${it.nombre}</div>
        <div class="precio">$${it.precio} c/u</div>
        ${it.nota ? `<div class="nota-item">📝 ${it.nota}</div>` : ""}
        <button class="btn-nota" onclick="editarNotaCarrito(${idx})">
          ${it.nota ? "Editar comentario" : "+ Agregar comentario"}
        </button>
      </div>
      <div class="qty-controles">
        <button onclick="cambiarQty(${idx}, -1)">−</button>
        <span>${it.qty}</span>
        <button onclick="cambiarQty(${idx}, 1)">+</button>
      </div>
    `;
    box.appendChild(row);
  });
}

async function enviarPedido(){
  const btn = document.getElementById("btn-accion-carrito");
  btn.disabled = true; btn.textContent = "Enviando...";
  try{
    const r = await apiFetch("/pedido", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({mesa: mesaActual, items: carrito})
    });
    const data = await r.json();
    if (data.ok){
      mostrarToast("Pedido enviado a caja ✓");
      carrito = [];
      avisarSiReasignada(data);
      await cargarMesas();
      mostrarPantalla("ticket");
    } else {
      mostrarToast("Error: " + (data.error || "no se pudo enviar"));
    }
  } catch(e){
    mostrarToast("Sin conexión con la caja");
  }
  actualizarBarra();
}

function mostrarPantalla(nombre){
  pantalla = nombre;
  ["mesas","ticket","menu","carrito"].forEach(p => {
    document.getElementById("pantalla-" + p).classList.toggle("oculto", p !== nombre);
  });
  document.getElementById("sub-header").textContent =
    nombre === "mesas"  ? "Toca una mesa para tomar el pedido" :
    nombre === "ticket" ? "Mesa " + mesaActual :
    nombre === "menu"   ? "Agregando a mesa " + mesaActual :
    "Revisa antes de enviar";
  document.getElementById("barra-carrito").style.display =
    (nombre === "menu" || nombre === "carrito") ? "flex" : "none";
  if (nombre === "carrito") pintarCarrito();
  if (nombre === "ticket") pintarTicketMesa(mesaActual);
  actualizarBarra();
}

function mostrarToast(msg){
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.classList.add("mostrar");
  setTimeout(() => t.classList.remove("mostrar"), 1600);
}

// Refresca el estado de las mesas cada 5s mientras estás en esa pantalla,
// y si estás dentro de una mesa, refresca tambien lo que ya lleva pedido
// (por si caja cobra, o otro mesero le agrega algo mientras la tienes abierta)
setInterval(async () => {
  if (pantalla === "mesas"){
    cargarMesas();
  } else if (pantalla === "ticket" && mesaActual){
    await cargarMesas();
    pintarTicketMesa(mesaActual);
  }
}, 5000);

document.getElementById("btn-login").onclick = intentarLogin;
document.getElementById("login-password").addEventListener("keydown", (e) => {
  if (e.key === "Enter") intentarLogin();
});

(async function init(){
  if (TOKEN && MESERO_NOMBRE){
    await entrarComoMesero();
  } else {
    document.getElementById("pantalla-login").classList.remove("oculto");
  }
})();
</script>
</body>
</html>
"""

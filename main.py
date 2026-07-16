"""
Comandero Enoch — Sistema POS
Compatible con Kivy 2.3.1 / Pydroid 3
Kivy y mucha marihuna
KelvINK- Sistema Enoch
Usa KivyMD (MDApp, Snackbar, etc.)

Corregido y mejorado con ayuda de Claude (Anthropic)
"""

import sys
import os
import json
import shutil
import traceback
import copy
import calendar
import uuid
import threading
import queue
import socket
import time
from datetime import datetime, timedelta, date

# Pydroid 3 a veces ejecuta el script desde un archivo temporal interno
# (temp_iiec_codefile.py) en vez de desde esta carpeta, por lo que el
# import relativo de servidor_mesas.py falla aunque el archivo SI este
# junto a este -- en ese caso, os.path.dirname(os.path.abspath(__file__))
# apunta a la carpeta temporal de Pydroid, NO a donde esta tu proyecto.
# Para no depender de una sola fuente, se arma una lista de candidatos y
# se agregan TODOS los que existan de verdad a sys.path antes de intentar
# el import:
#   1) La ruta fija de siempre (funciona si tu carpeta se llama asi).
#   2) La carpeta de __file__ (funciona cuando Pydroid SI ejecuta desde
#      el archivo real).
#   3) La carpeta de sys.argv[0] (en muchas versiones de Pydroid, esto
#      apunta al archivo real que abriste, aunque __file__ no lo haga).
#   4) El directorio de trabajo actual (os.getcwd()), por si Pydroid se
#      lanzo posicionado ya dentro de la carpeta del proyecto.
_CARPETAS_PROYECTO = []
for _candidata in (
    "/storage/emulated/0/Download/Taqueria",  # carpeta real confirmada del proyecto
    "/storage/emulated/0/Proyecto comanda",
    os.path.dirname(os.path.abspath(__file__)),
    os.path.dirname(os.path.abspath(sys.argv[0])) if sys.argv and sys.argv[0] else "",
    os.getcwd(),
):
    if _candidata and _candidata not in _CARPETAS_PROYECTO:
        _CARPETAS_PROYECTO.append(_candidata)

for _c in _CARPETAS_PROYECTO:
    if _c and os.path.isdir(_c) and _c not in sys.path:
        sys.path.insert(0, _c)

# database.py (BaseDatos, nuevo_id) DEBE importarse ya con sys.path
# corregido arriba -- si este import se hace ANTES de arreglar sys.path
# (como estaba antes), Pydroid puede no encontrar database.py aunque este
# bien puesto junto a main.py, porque a veces ejecuta desde una copia
# temporal en otra carpeta.
#
# A diferencia de servidor_mesas.py (que SI puede fallar en silencio con
# un fallback a None, porque el servidor de mesas es opcional), la app NO
# puede arrancar sin BaseDatos/nuevo_id -- asi que aqui, si falla, se dejan
# los mismos archivos de diagnostico que usa el resto del arranque y
# LUEGO se relanza la excepcion (raise) para no fingir que la app puede
# seguir sin base de datos. Sin este try/except, un import fallido de
# database.py truena ANTES de que sys.excepthook exista (mas abajo), y el
# error se pierde por completo -- la app "se cierra sola" sin dejar rastro,
# que es justo el sintoma reportado.
try:
    from database import BaseDatos, nuevo_id as _nuevo_id
except Exception:
    import traceback as _tb_db
    _detalle_db = (
        "No se pudo importar database.py -- revisa que el archivo "
        "database.py este en LA MISMA CARPETA que main.py.\n\n"
        + _tb_db.format_exc()
    )
    for _c in _CARPETAS_PROYECTO:
        try:
            os.makedirs(_c, exist_ok=True)
            with open(os.path.join(_c, "error_import_database.txt"),
                      "w", encoding="utf-8") as _f:
                _f.write(_detalle_db)
        except Exception:
            pass
    raise

try:
    from servidor_mesas import iniciar_servidor, obtener_ip_local, detener_servidor, NOMBRE_MDNS
except Exception:
    iniciar_servidor = None
    obtener_ip_local = None
    detener_servidor = None
    NOMBRE_MDNS = "comandero.local"
    try:
        import traceback as _tb_import
        _detalle = _tb_import.format_exc()
        for _c in _CARPETAS_PROYECTO:
            try:
                os.makedirs(_c, exist_ok=True)
                with open(os.path.join(_c, "error_import_servidor_mesas.txt"),
                          "w", encoding="utf-8") as _f:
                    _f.write(_detalle)
            except Exception:
                pass
    except Exception:
        pass

try:
    from kivy.app import App
    from kivymd.app import MDApp
    from kivymd.icon_definitions import md_icons
    from kivymd.uix.snackbar import Snackbar
    # Componentes reales de KivyMD (1.2.0) para el Dashboard/pantalla de
    # inicio: reemplazan los BoxLayout + canvas.before manuales que se
    # usaban antes para simular tarjetas/sombras (ver _construir_tarjeta_
    # mesa y el KV de <PantallaInicio> mas abajo). Se agrupan aqui para
    # no desperdigar imports de kivymd por todo el archivo.
    from kivymd.uix.card import MDCard
    from kivymd.uix.boxlayout import MDBoxLayout
    from kivymd.uix.gridlayout import MDGridLayout
    from kivymd.uix.floatlayout import MDFloatLayout
    from kivymd.uix.button import (
        MDRaisedButton, MDFlatButton, MDIconButton, MDRectangleFlatButton,
    )
    from kivymd.uix.label import MDLabel
    from kivy.lang import Builder
    from kivy.clock import Clock
    from kivy.uix.screenmanager import ScreenManager, Screen, NoTransition
    from kivy.uix.boxlayout import BoxLayout
    from kivy.uix.anchorlayout import AnchorLayout
    from kivy.uix.widget import Widget
    from kivy.uix.scrollview import ScrollView
    from kivy.uix.gridlayout import GridLayout
    from kivy.uix.label import Label
    from kivy.uix.button import Button
    from kivy.uix.textinput import TextInput
    from kivy.uix.popup import Popup as _PopupKivyOriginal
    from kivy.uix.image import Image as KivyImage
    from kivy.metrics import dp
    from kivy.graphics import Color, RoundedRectangle, Rectangle, Line
    from kivy.properties import ListProperty, StringProperty
    from kivy.uix.behaviors import ButtonBehavior

    # ── FIX DE RAIZ: contraste roto en TODOS los popups bajo temas claros ──
    # Diagnostico (por que el texto se veia negro sobre fondo oscuro/gris
    # en los modales, ej. el de "ver pedido de mesa", con el tema 'Clara'):
    #
    # 1) 'background_color' de Popup NO es un relleno solido -- es un
    #    TINTE multiplicativo sobre la imagen de panel con bordes que
    #    Kivy dibuja por defecto ('background', un PNG con sombreado
    #    gris/oscuro ya incorporado en la textura). Por mas claro que
    #    sea self.OSCURO en el tema activo (blanco puro en 'Clara'), esa
    #    imagen jamas se vuelve realmente blanca: solo se aclara un poco
    #    y se queda gris/oscura. Ningun popup de la app apagaba esa
    #    imagen, asi que TODOS heredaban este mismo problema -- por eso
    #    afecta "varios modales y listas", no uno solo.
    # 2) 'title_color' (el texto del titulo, dibujado por el propio
    #    Popup) tiene un default de Kivy fijo en blanco casi puro,
    #    pensado para paneles oscuros. De 39 Popup(...) en el archivo,
    #    solo 1 lo fijaba manualmente -- los otros 38 se quedaban con
    #    ese blanco fijo, invisible en cuanto el fondo es claro.
    #
    # Nada de esto era una variable de color faltante ni un negro
    # hardcodeado en el codigo de la app: era un comportamiento nativo
    # de Popup que ningun tema (ni 'Clara' ni los demas) estaba
    # pisando. La solucion NO es parchear cada Popup(...) uno por uno
    # (39 lugares, fragil y facil de olvidar en el proximo popup nuevo):
    # se sobreescribe aqui, una sola vez, la clase Popup que el resto
    # del archivo ya usa. Cualquier Popup(...) existente sigue
    # funcionando exactamente igual (mismos argumentos); esta subclase
    # solo RELLENA valores que antes faltaban, calculandolos con la
    # misma _texto_contraste() que ya usa el resto de la app -- si un
    # popup en particular YA pasa su propio title_color/separator_color/
    # background, ese valor explicito se respeta tal cual.
    class Popup(_PopupKivyOriginal):
        def __init__(self, **kwargs):
            bg = kwargs.get("background_color", [1, 1, 1, 1])
            texto = _texto_contraste(bg)
            kwargs.setdefault("background", "")           # sin imagen de Kivy: relleno SOLIDO real
            kwargs.setdefault("title_color", texto)        # titulo dinamico, ya no fijo en blanco
            kwargs.setdefault("separator_color", texto[:3] + [0.25])
            super().__init__(**kwargs)

    # ── Parche anti-crash: ripple con radius=None ────────────────────────
    # En la version de KivyMD 2.x que corre en el telefono (el comentario
    # de mas arriba decia "1.2.0", pero claramente ya no lo es -- ver
    # version_kivy_kivymd.txt), los botones legacy (MDRaisedButton,
    # MDFlatButton, MDIconButton, MDRectangleFlatButton) a veces llegan al
    # primer toque con su propiedad "radius" en None en vez de una lista
    # (ej. [0]), y kivymd.uix.behaviors.ripple_behavior.CommonRipple
    # truena con "ValueError: None is not allowed for ..._round_rad" justo
    # al hacer self._round_rad = self.radius. Forzamos aqui que "radius"
    # nunca sea None ANTES de que el ripple intente usarlo, sin tocar cada
    # boton uno por uno en los ~9000 renglones de este archivo.
    try:
        from kivymd.uix.behaviors.ripple_behavior import CommonRipple
        _orig_lay_canvas_instructions = CommonRipple.lay_canvas_instructions

        def _lay_canvas_instructions_seguro(self, *args, **kwargs):
            if hasattr(self, "radius") and self.radius is None:
                self.radius = [0]
            return _orig_lay_canvas_instructions(self, *args, **kwargs)

        CommonRipple.lay_canvas_instructions = _lay_canvas_instructions_seguro
    except Exception:
        pass

    # ── Parche anti-crash: "assert rule not in self.rulectx" ────────────
    # Este es el causante de que las mesas dejen de dibujarse despues de
    # CUALQUIER error a medias construyendo un widget. Builder._apply_rule
    # (kivy/lang/builder.py) guarda una marca en Builder.rulectx mientras
    # arma un widget con su regla KV, y la borra al terminar -- pero esa
    # limpieza NO esta protegida con try/finally en Kivy. Si algo truena a
    # la mitad de construir, por ejemplo, una MDCard (el mismo tipo de bug
    # de "radius=None" de arriba, u otra cosa), esa marca se queda pegada
    # para siempre, y CUALQUIER MDCard (o boton, o lo que sea) que se
    # intente crear despues truena con "AssertionError: rule not in
    # self.rulectx" -- aunque no tenga nada que ver con el error original.
    # Esto es lo que hacia que las tarjetas de mesa dejaran de aparecer:
    # una vez que una se atoro, ninguna mesa nueva se podia volver a
    # construir en toda la corrida de la app.
    #
    # El parche envuelve _apply_rule para que, si algo truena a la mitad,
    # se limpie la marca en vez de dejarla pegada -- asi el siguiente
    # widget de esa clase se puede seguir construyendo con normalidad, en
    # vez de quedar bloqueado el resto de la sesion.
    try:
        from kivy.lang.builder import BuilderBase

        _orig_apply_rule = BuilderBase._apply_rule

        def _apply_rule_seguro(self, widget, rule, rootrule, *args, **kwargs):
            try:
                return _orig_apply_rule(
                    self, widget, rule, rootrule, *args, **kwargs
                )
            except Exception:
                self.rulectx.pop(rule, None)
                self.rulectx.pop(rootrule, None)
                raise

        BuilderBase._apply_rule = _apply_rule_seguro
    except Exception:
        pass

    # ── Parche anti-crash: radius=None en botones legacy (RAIZ) ──────────
    # Los dos parches de arriba tapan SINTOMAS (ripple, rulectx atorado),
    # pero la causa real es esta: en la version de KivyMD 2.x instalada,
    # MDRaisedButton / MDFlatButton / MDIconButton / MDRectangleFlatButton
    # (los botones "viejos", de antes de MD3) en realidad YA NO TIENEN
    # "radius" como una Property de verdad de Kivy -- por eso NO se puede
    # pasar como kwarg al crearlos (eso truena con "Properties ['radius']
    # ... may not be existing property names"). Aun asi, en esta version
    # instalada, algo dentro de KivyMD SI lee "self.radius" / "root.radius"
    # esperando encontrar una lista (el ripple, la sombra del boton...) y
    # se encuentra con None, y truena.
    #
    # La solucion de raiz es definir "radius" como una property de Python
    # normal (no de Kivy) directo en la clase, con su propio valor guardado
    # aparte, para que:
    #   - SIEMPRE se pueda leer y nunca regrese None (regresa [dp(8)] si
    #     nadie lo definio antes), y
    #   - se pueda seguir asignando libremente, tanto desde KV
    #     ("radius: [dp(10)]", como ya hace el boton de "NUEVO PEDIDO")
    #     como desde Python, sin romper nada.
    try:
        def _normalizar_radius(valor):
            # BoxShadow.border_radius exige exactamente 4 valores (uno por
            # esquina). Varios botones en este archivo traen "radius:
            # [dp(N)]" con un solo valor (pensado para RoundedRectangle,
            # que si acepta 1 valor), asi que aqui lo expandimos a 4 para
            # que tambien funcione con la sombra interna del boton.
            if valor is None:
                return [dp(8)] * 4
            try:
                n = len(valor)
            except TypeError:
                return [valor] * 4
            if n == 4:
                return list(valor)
            if n == 1:
                return [valor[0]] * 4
            # Cualquier otra longitud rara: mejor no adivinar, usar default.
            return [dp(8)] * 4

        def _radius_get(self):
            valor = self.__dict__.get("_radius_valor_seguro")
            return _normalizar_radius(valor)

        def _radius_set(self, valor):
            self.__dict__["_radius_valor_seguro"] = valor

        for _cls in (
            MDRaisedButton, MDFlatButton, MDIconButton, MDRectangleFlatButton,
        ):
            _cls.radius = property(_radius_get, _radius_set)
    except Exception:
        pass
except Exception:
    # Si Kivy/KivyMD truena al importarse, esto pasa ANTES de que
    # sys.excepthook este activo (mas abajo), asi que sin este bloque
    # el error se pierde por completo y la app "no abre" sin dejar
    # ningun rastro. Lo guardamos aqui a mano para ver la causa real.
    import traceback as _tb_kivy
    _detalle_kivy = _tb_kivy.format_exc()
    for _c in _CARPETAS_PROYECTO:
        try:
            os.makedirs(_c, exist_ok=True)
            with open(os.path.join(_c, "error_import_kivy.txt"),
                      "w", encoding="utf-8") as _f:
                _f.write(_detalle_kivy)
        except Exception:
            pass
    raise

# Diagnostico de versiones: se escribe SIEMPRE que los imports de arriba
# tuvieron exito, independientemente de si algo truena mas adelante (KV,
# build(), etc.) -- asi, aunque el resto de la app se caiga sin dejar
# rastro, al menos queda registrado con que version de Kivy/KivyMD se
# esta corriendo, que suele ser la causa mas comun de un widget que no
# existe o una propiedad (radius/elevation) que cambio de nombre entre
# versiones.
try:
    import kivy as _kivy_diag
    import kivymd as _kivymd_diag
    _texto_version = (
        f"kivy: {getattr(_kivy_diag, '__version__', '?')}\n"
        f"kivymd: {getattr(_kivymd_diag, '__version__', '?')}\n"
        f"python: {sys.version}\n"
    )
    for _c in _CARPETAS_PROYECTO:
        try:
            os.makedirs(_c, exist_ok=True)
            with open(os.path.join(_c, "version_kivy_kivymd.txt"),
                      "w", encoding="utf-8") as _f:
                _f.write(_texto_version)
        except Exception:
            pass
except Exception:
    pass

# ── Manejador de errores ─────────────────────────────────────────────────────
# Nombre de carpeta configurable en vivo: arranca con el valor por defecto y
# se actualiza desde App cuando el usuario cambia el nombre de la empresa
# en Configuracion (ver App._actualizar_carpeta_errores).
_CARPETA_ERRORES = {"nombre": "Comandero"}

def _carpeta_base_datos():
    """Reemplaza los antiguos "/storage/emulated/0/..." fijos. Android 10+
    (scoped storage) puede lanzar PermissionError al escribir directo en la
    raiz del almacenamiento compartido sin el permiso especial de "Acceso a
    todos los archivos" -- por eso TODO lo que la app guarda (BD, config,
    logo, log de errores, checkpoints) debe vivir dentro del user_data_dir
    de Kivy, que es privado de la app y siempre escribible.

    El problema: esta funcion tambien la usan sys.excepthook, _checkpoint()
    y _leer_puntero_carpeta() mas abajo, que corren AL IMPORTAR EL MODULO,
    antes de que exista ninguna instancia de TaqueriaApp -- ahi no hay
    "self" del que leer self.user_data_dir.

    Por eso:
      - Si la App YA existe (App.get_running_app()), se usa su
        self.user_data_dir de verdad (la via oficial de Kivy).
      - Si TODAVIA no existe (bootstrap muy temprano, antes del primer
        frame), se usa un respaldo que imita la MISMA formula que Kivy usa
        quando kivy.utils.platform no detecta 'android' -- justo el caso
        de Pydroid 3, que corre sin el bootstrap de python-for-android
        (ver _PERMITIR_CODIGO_ANDROID_NATIVO mas abajo): una carpeta
        oculta junto al propio script, en vez de la raiz del storage.

    Asi, exista ya la App o no, todo apunta SIEMPRE a la misma carpeta --
    nunca se reparten los datos en dos lugares distintos segun el momento
    en que se pida la ruta."""
    try:
        from kivy.app import App
        app_activa = App.get_running_app()
        if app_activa is not None:
            return app_activa.user_data_dir  # Kivy ya crea la carpeta si falta
    except Exception:
        pass
    ruta = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".taqueria")
    try:
        os.makedirs(ruta, exist_ok=True)
    except Exception:
        pass
    return ruta

# Puntero de ubicacion FIJA (nunca se mueve): es la unica forma de saber, en
# un arranque en frio, en que carpeta quedo la base de datos la ultima vez
# que se cambio el nombre de la empresa -- sin esto habria un problema de
# "huevo y gallina" (la carpeta la dice la BD, pero la BD esta en la carpeta).
# Vive dentro de _carpeta_base_datos() (antes: ruta fija a la raiz del
# storage) para no necesitar permisos especiales de Android.
_PUNTERO_CARPETA = os.path.join(_carpeta_base_datos(), ".comandero_carpeta.txt")

def _leer_puntero_carpeta():
    try:
        if os.path.exists(_PUNTERO_CARPETA):
            with open(_PUNTERO_CARPETA, "r", encoding="utf-8") as f:
                nombre = f.read().strip()
                if nombre:
                    _CARPETA_ERRORES["nombre"] = nombre
    except Exception:
        pass

def _escribir_puntero_carpeta(nombre):
    try:
        with open(_PUNTERO_CARPETA, "w", encoding="utf-8") as f:
            f.write(nombre)
    except Exception:
        pass

_leer_puntero_carpeta()  # se ejecuta al importar el modulo, antes de _init_db()

def _sanear_nombre_carpeta(nombre):
    """Quita caracteres invalidos para nombres de carpeta en Android/Windows
    y evita nombres vacios."""
    nombre = (nombre or "").strip()
    for ch in '/\\:*?"<>|':
        nombre = nombre.replace(ch, "")
    return nombre or "Comandero"

def _guardar_error(tipo, valor, tb):
    _texto_error = None
    try:
        carpeta = os.path.join(_carpeta_base_datos(), _CARPETA_ERRORES["nombre"])
        os.makedirs(carpeta, exist_ok=True)
        ruta_log = os.path.join(carpeta, "error_birria.txt")
        _texto_error = (
            f"=== Error {_CARPETA_ERRORES['nombre']} ===\n"
            + "Fecha: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "\n\n"
            + "".join(traceback.format_exception(tipo, valor, tb))
        )
        with open(ruta_log, "w", encoding="utf-8") as f:
            f.write(_texto_error)
    except Exception:
        pass

    # Copia adicional en almacenamiento PUBLICO (carpeta "Taquería" en la
    # memoria principal del telefono), para poder abrir error.txt con
    # cualquier explorador de archivos sin permisos especiales de Android
    # -- la copia de arriba (carpeta privada) sigue siendo la fuente
    # confiable si esta escritura publica llega a fallar por permisos.
    try:
        if _texto_error is not None:
            carpeta_publica = "/storage/emulated/0/Taquería"
            os.makedirs(carpeta_publica, exist_ok=True)
            with open(os.path.join(carpeta_publica, "error.txt"),
                      "w", encoding="utf-8") as f:
                f.write(_texto_error)
    except Exception:
        pass

    # Una excepcion no atrapada en el hilo principal puede dejar vivo el
    # hilo daemon de Flask (servidor de mesas) con el puerto abierto hasta
    # que el proceso completo muera -- lo que puede tardar en Android. Se
    # intenta apagarlo de forma limpia tambien aqui, no solo en on_stop().
    try:
        if detener_servidor is not None:
            app_activa = App.get_running_app()
            if app_activa is not None:
                detener_servidor(app_activa, espera=1.0)
    except Exception:
        pass

sys.excepthook = _guardar_error

def _checkpoint(mensaje):
    """Deja constancia en disco de hasta donde llego la ejecucion.
    A diferencia de _guardar_error, esto no espera una excepcion: sirve
    para ubicar cierres 'mudos' (crash nativo, el proceso muere sin que
    Python alcance a lanzar ni capturar nada). Se ACUMULA (append) para
    poder ver la secuencia completa de pasos alcanzados, no solo el
    ultimo -- el orden es lo que nos dice donde se corto la ejecucion."""
    try:
        carpeta = os.path.join(_carpeta_base_datos(), _CARPETA_ERRORES["nombre"])
        os.makedirs(carpeta, exist_ok=True)
        with open(os.path.join(carpeta, "checkpoint.txt"), "a", encoding="utf-8") as f:
            f.write(datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f") + " -- " + mensaje + "\n")
    except Exception:
        pass

_checkpoint("=== NUEVO ARRANQUE ===")

_checkpoint("Modulo main.py importado correctamente (Kivy/KivyMD ya cargaron)")

# Interruptor manual: mientras se prueba en Pydroid 3, este codigo se
# queda APAGADO porque jnius/PythonActivity no existen de verdad fuera
# de un APK compilado -- llamarlos ahi puede tumbar el proceso entero
# sin ningun mensaje de error (crash nativo, no una excepcion de Python).
# Cambiar a True SOLO al probar el APK ya compilado con buildozer.
_PERMITIR_CODIGO_ANDROID_NATIVO = True

# ── Menú por defecto ──────────────────────────────────────────────────────────
MENU_DEFAULT = {
    "Comida": [
        {"id": "c1", "nombre": "Orden Birria (1L)", "precio": 120},
        {"id": "c2", "nombre": "1/2 Birria",        "precio": 65},
        {"id": "c3", "nombre": "Taco Dorado",       "precio": 18},
    ],
    "Bebida": [
        {"id": "b1", "nombre": "Coca-Cola", "precio": 25},
        {"id": "b2", "nombre": "Agua",      "precio": 15},
    ],
    "Postre": [
        {"id": "p1", "nombre": "Flan", "precio": 30},
    ],
    "Otros": [
        {"id": "o1", "nombre": "Cigarro",     "precio": 20},
        {"id": "o2", "nombre": "Costo Extra", "precio": 0, "es_extra": True},
    ],
}

MESAS_DEFAULT = ["Mesa 1", "Mesa 2", "Mesa 3", "Mesa 4", "Mesa 5"]

# ── Info del negocio para tickets (Configuracion > Personalizacion >
# Informacion del negocio y ticket) ──────────────────────────────────────────
# Todos los campos son opcionales (default ""); si un campo tiene
# contenido, aparece automaticamente al final del ticket de venta (ESC/POS,
# imagen para Galeria y Vista Previa). El nombre del negocio NO esta aqui
# a proposito: ya existe como self.nombre_taqueria (Configuracion >
# Personalizacion > Nombre de la taqueria) y ya se imprime como encabezado
# del ticket -- duplicarlo aqui mostraria el nombre dos veces.
# Para agregar un campo nuevo a futuro (logotipo ya existe aparte, redes
# sociales, horario, RFC, metodos de pago, QR para transferencia, datos
# fiscales...) basta con sumar la clave aqui, un campo_texto() en
# abrir_info_negocio_ticket() y una linea en su _guardar() -- no hace
# falta tocar _cargar_info_negocio/_guardar_info_negocio ni el resto de
# la app.
INFO_NEGOCIO_DEFAULT = {
    "direccion": "",
    "banco": "",
    "cuenta": "",                  # CLABE o numero de cuenta
    "titular": "",                 # nombre del titular de la cuenta
    "telefono": "",                # para enviar comprobante de pago
    "mensaje_agradecimiento": "",  # si esta vacio, se usa un default al imprimir
}

# ── Colores (RGBA 0-1) ────────────────────────────────────────────────────────
# Roles fijos, usados en toda la app vía KV (app.NEGRO, app.OSCURO, etc.) y
# via App.get_running_app() en codigo Python fuera de la clase de la app:
#   NEGRO  = fondo principal de la pantalla
#   OSCURO = fondo del header / tarjetas oscuras
#   CREMA  = color de texto principal
#   ROJO   = color primario (botones, acentos) — se llama "ROJO" aunque el tema sea azul
#   DORADO = color secundario / detalles
#   ACCENT = color del boton de accion principal (siempre verde, como en la referencia)
# El nombre de la variable es legado; lo que cambia segun el tema es su VALOR.
# NEGRO/OSCURO/CREMA/ROJO/DORADO/ACCENT NO existen como variables de modulo:
# su UNICA fuente de verdad es TEMAS (mas abajo) y su UNICO estado en tiempo
# de ejecucion son las ListProperty reactivas de TaqueriaApp (ver la clase),
# que _aplicar_paleta() actualiza en un solo lugar al cambiar de tema.
# GRIS es distinto: es una constante fija, independiente del tema activo (no
# vive en TEMAS ni es reactiva) -- se usa para separadores/lineas divisorias
# que deliberadamente no cambian con el tema.
GRIS = [0.4, 0.4, 0.4, 1]

# Superficie oscura fija (no reactiva al tema, a proposito): fondo del
# Snackbar y de los campos de texto (TextInput) de toda la app. Antes este
# mismo valor estaba escrito como literal suelto en mas de 15 lugares
# distintos (Python y KV); ahora tiene una unica definicion.
SUPERFICIE_FIJA_OSCURA = [0.18, 0.18, 0.18, 1]

# Color de aviso (ambar), fijo, no reactivo al tema: mensajes de "QR/mDNS
# no disponible" en el popup de acceso por WiFi.
AVISO_AMBAR = [0.9, 0.6, 0.3, 1]

# Campo de solo lectura estilo "codigo" (fondo blanco, texto negro), fijo
# a proposito para que la URL/mDNS sea legible y facil de seleccionar sin
# importar el tema activo.
CAMPO_CODIGO_BG = [1, 1, 1, 1]
CAMPO_CODIGO_FG = [0, 0, 0, 1]

MESES_ES = ["", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
            "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
DIAS_SEMANA_ES = ["L", "M", "M", "J", "V", "S", "D"]

# ── Temas disponibles (Configuracion > Personalizacion) ──────────────────────
TEMAS = {
    "Oscuro clasico": {
        "NEGRO":  [0.102, 0.102, 0.102, 1],
        "OSCURO": [0.067, 0.067, 0.067, 1],
        "CREMA":  [1.000, 0.973, 0.906, 1],
        "ROJO":   [0.545, 0.102, 0.102, 1],
        "DORADO": [0.831, 0.627, 0.090, 1],
        "ACCENT":  [0.180, 0.600, 0.260, 1],
    },
    "Rojo Fuego": {
        "NEGRO":  [0.941, 0.925, 0.875, 1],
        "OSCURO": [0.545, 0.102, 0.102, 1],
        "CREMA":  [0.130, 0.130, 0.130, 1],
        "ROJO":   [0.720, 0.110, 0.110, 1],
        "DORADO": [0.960, 0.780, 0.320, 1],
        "ACCENT":  [0.160, 0.620, 0.270, 1],
    },
    "Azul Aqua": {
        "NEGRO":  [0.941, 0.925, 0.875, 1],
        "OSCURO": [0.110, 0.420, 0.550, 1],
        "CREMA":  [0.130, 0.130, 0.130, 1],
        "ROJO":   [0.110, 0.420, 0.550, 1],
        "DORADO": [0.960, 0.850, 0.550, 1],
        "ACCENT":  [0.160, 0.620, 0.270, 1],
    },
    "Neutro": {
        "NEGRO":  [0.949, 0.949, 0.941, 1],
        "OSCURO": [0.220, 0.220, 0.220, 1],
        "CREMA":  [0.130, 0.130, 0.130, 1],
        "ROJO":   [0.300, 0.300, 0.300, 1],
        "DORADO": [0.600, 0.470, 0.150, 1],
        "ACCENT":  [0.160, 0.620, 0.270, 1],
    },
    # "Clara": tema claro/minimalista, extraido de una interfaz de
    # referencia (fondo crema calido, tarjetas blancas, texto casi negro,
    # acentos salmon/menta). El mapeo NO sigue el nombre literal de cada
    # color de la referencia -- sigue el ROL real que cada variable ya
    # tiene en ESTE codigo (ver el comentario "Roles fijos" arriba de
    # este diccionario, y como se usan de verdad ROJO/DORADO en el resto
    # del archivo: DORADO pinta el estado "Ocupada" y el boton "Ver
    # Pedido" -- coral en la referencia --, mientras que ROJO es el
    # acento "primario" generico usado en botones de otras pantallas
    # -- Negar/Salir/Copiar, etc. -- que en la referencia le toca el
    # menta):
    #   NEGRO  = fondo PRINCIPAL de pantalla        -> crema calido de fondo
    #   OSCURO = fondo de header / tarjetas          -> blanco (tarjetas de la referencia)
    #   CREMA  = color de TEXTO principal            -> casi negro (texto de la referencia)
    #   ROJO   = acento primario generico (otras pantallas) -> menta/verde agua
    #   DORADO = "Ocupada" / boton "Ver Pedido"       -> salmon/coral
    #   ACCENT = boton "Nuevo Pedido" (siempre verde en esta app) -> verde azulado,
    #            un punto medio entre el teal oscuro de la referencia y el
    #            verde que ya usan los demas temas (ver nota mas abajo).
    "Clara": {
        "NEGRO":  [0.945, 0.925, 0.867, 1],   # fondo crema calido de pantalla
        "OSCURO": [1.000, 1.000, 1.000, 1],   # tarjetas/header blancos
        "CREMA":  [0.067, 0.094, 0.153, 1],   # texto casi negro (#111827)
        "ROJO":   [0.204, 0.827, 0.600, 1],   # menta/verde agua (#34D399) -- acento generico
        "DORADO": [0.973, 0.443, 0.443, 1],   # salmon/coral (#F87171) -- Ocupada / Ver Pedido
        "ACCENT":  [0.184, 0.435, 0.420, 1],  # verde azulado (compromiso, ver nota)
    },
}


# ── Paleta fija de "Configuracion > Menu" (rediseno UI/UX) ────────────────────
# A peticion explicita del rediseno, esta pantalla (categorias, productos,
# mesas, empleados) usa una paleta clara FIJA, independiente del tema que el
# negocio tenga elegido en Personalizacion (TEMAS de arriba): fondo hueso,
# tarjetas blancas y acento verde esmeralda con contraste >= 4.5:1 sobre
# texto blanco. El resto de la app (Inicio, Pedidos, Estadisticas,
# Personalizacion) sigue reaccionando al tema activo sin cambios.
CFG_FONDO        = [0.976, 0.973, 0.965, 1]   # #F9F8F6 -- fondo de pantalla
CFG_TARJETA      = [1.000, 1.000, 1.000, 1]   # blanco -- cards
CFG_TEXTO        = [0.129, 0.129, 0.129, 1]   # texto principal, casi negro
CFG_TEXTO_GRIS   = [0.459, 0.459, 0.459, 1]   # #757575 -- categorias inactivas
CFG_EMERALD      = [0.016, 0.471, 0.341, 1]   # #047857 -- acento (contraste ~5.5:1 en blanco)
CFG_EMERALD_SOFT = [0.016, 0.471, 0.341, 0.15]  # 15% -- fondo de categoria activa
CFG_ALERTA       = [0.827, 0.184, 0.184, 1]   # #D32F2F -- borrar/eliminar
CFG_ALERTA_SOFT  = [0.827, 0.184, 0.184, 0.10]  # 10% -- fondo suave de aviso/borrar
# Dos grises propios de Configuracion, deliberadamente distintos de
# CFG_FONDO y CFG_TEXTO_GRIS (son decisiones visuales distintas, no la
# misma constante repetida): fondo de TextInput y color de hint_text.
CFG_CAMPO_BG     = [0.949, 0.949, 0.941, 1]   # fondo de TextInput (mas gris que CFG_FONDO)
CFG_HINT_GRIS    = [0.600, 0.600, 0.600, 1]   # texto de hint (mas claro que CFG_TEXTO_GRIS)

_ICONOS_CATEGORIA_CFG = {
    "comida": "silverware-fork-knife", "comidas": "silverware-fork-knife",
    "bebida": "cup", "bebidas": "cup",
    "postre": "cupcake", "postres": "cupcake",
    "entrada": "food-croissant", "entradas": "food-croissant",
    "especial": "star-outline", "especiales": "star-outline",
    "otro": "dots-horizontal", "otros": "dots-horizontal",
}

def _icono_categoria_cfg(nombre):
    """Icono decorativo por categoria (Config > Menu). Puramente visual: si
    el nombre no esta en el mapa usa un icono generico -- nunca bloquea ni
    cambia el nombre real de la categoria que ya guarda el negocio."""
    return _ICONOS_CATEGORIA_CFG.get(nombre.strip().lower(), "silverware-variant")


# ── Helpers de UI ─────────────────────────────────────────────────────────────
def _luminancia(rgb):
    """Luminancia relativa aproximada (0=negro, 1=blanco) para elegir texto legible."""
    r, g, b = rgb[0], rgb[1], rgb[2]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b

def _texto_contraste(bg_rgb):
    """Devuelve blanco casi puro o negro casi puro, el que mas contraste haga
    contra bg_rgb. Se recalcula en cada llamada para que funcione con
    cualquier tema, en vez de asumir que CREMA siempre contrasta con ROJO."""
    if _luminancia(bg_rgb) > 0.5:
        return [0.08, 0.08, 0.08, 1]
    return [0.97, 0.97, 0.95, 1]

def _verde_contraste(bg_rgb):
    """Verde semantico de 'mesa libre', pero ajustado al contraste del tema
    activo -- mismo criterio que _texto_contraste (luminancia de bg_rgb).
    Sobre fondo claro (Rojo Fuego/Azul Aqua/Neutro) usa un verde bosque mas
    oscuro y saturado para que se note sobre la tarjeta clara; sobre fondo
    oscuro (Oscuro clasico) usa un verde menta mas brillante, porque un
    verde bosque oscuro se perderia contra un fondo ya oscuro."""
    if _luminancia(bg_rgb) > 0.5:
        return [0.106, 0.470, 0.216, 1]   # verde bosque -- fondo claro
    return [0.376, 0.780, 0.451, 1]       # verde menta -- fondo oscuro

def lbl(text, color=None, font_size="14sp", bold=False, halign="left",
        size_hint_y=None, height=None, markup=False, shorten=False,
        auto_height=False):
    if bold and not markup:
        text = f"[b]{text}[/b]"
        markup = True
    kw = dict(text=text, color=color or App.get_running_app().CREMA,
               font_size=font_size, markup=markup, halign=halign)
    if size_hint_y is not None:
        kw["size_hint_y"] = size_hint_y
    if height is not None:
        kw["height"] = height
    if shorten:
        kw["shorten"] = True
        kw["shorten_from"] = "right"
    w = Label(**kw)
    if halign != "left":
        w.bind(size=lambda inst, v: setattr(inst, "text_size", v))
    else:
        w.bind(size=lambda inst, v: setattr(inst, "text_size", (v[0], None)))
    if auto_height:
        # Si el texto no cabe en una sola linea, la etiqueta crece en alto
        # (con un margen minimo) en vez de quedar encimada con lo siguiente.
        # valign="top" es clave: mientras el alto todavia no se recalcula
        # (o si el recalculo llega un frame tarde), Kivy dibuja el texto
        # que sobra hacia ABAJO en vez de hacia ARRIBA, evitando que se
        # monte sobre el widget de encima (p.ej. un titulo).
        w.valign = "top"
        def _ajustar_alto(inst, ts):
            inst.height = max(height or dp(22), ts[1] + dp(12))
        w.bind(texture_size=_ajustar_alto)
        # Forzamos un primer calculo ya mismo (no solo reactivo a 'size')
        # para que el alto sea correcto desde el primer frame.
        w.texture_update()
        _ajustar_alto(w, w.texture_size)
    return w

def btn_raised(text, bg=None, color=None, size_hint_x=1, width=None,
               size_hint_y=None, height=dp(44), font_size="14sp", on_press=None,
               markup=False):
    bg = bg or App.get_running_app().ROJO
    color = color or _texto_contraste(bg)
    kw = dict(text=text, background_color=[0,0,0,0], color=color,
              font_size=font_size, size_hint_x=size_hint_x, markup=markup,
              size_hint_y=size_hint_y if size_hint_y is not None else None)
    if size_hint_y is None:
        kw["size_hint_y"] = None
        kw["height"] = height
    if width is not None:
        kw["size_hint_x"] = None
        kw["width"] = width
    b = Button(**kw)
    _set_bg(b, bg)
    if on_press:
        b.bind(on_press=on_press)
    return b

def btn_flat(text, color=None, size_hint_x=1, width=None,
             size_hint_y=None, height=dp(44), font_size="14sp", on_press=None,
             markup=False):
    color = color or App.get_running_app().CREMA
    kw = dict(text=text, background_color=[0,0,0,0], color=color,
              font_size=font_size, size_hint_x=size_hint_x, markup=markup)
    if size_hint_y is None:
        kw["size_hint_y"] = None
        kw["height"] = height
    else:
        kw["size_hint_y"] = size_hint_y
    if width is not None:
        kw["size_hint_x"] = None
        kw["width"] = width
    b = Button(**kw)
    if on_press:
        b.bind(on_press=on_press)
    return b

def _set_bg(widget, color, radius=None):
    if radius is None:
        radius = [dp(16)]
    elif not isinstance(radius, (list, tuple)):
        radius = [radius]
    def _draw(w, *_):
        w.canvas.before.clear()
        with w.canvas.before:
            Color(*color)
            RoundedRectangle(pos=w.pos, size=w.size, radius=radius)
    widget.bind(pos=_draw, size=_draw)
    _draw(widget)

class _CeldaDiaCalendario(ButtonBehavior, Label):
    """Celda de día del calendario mensual (Estadísticas > Fecha...).

    Se usa ButtonBehavior + Label (en vez de Button) a propósito: Button
    trae su propio padding/estilo interno que, dentro de un GridLayout de
    filas forzadas, terminaba dibujando el fondo dorado más alto que la
    celda real y montándose sobre la fila siguiente (números "brincando"
    de línea). Al heredar de Label, esta celda mide EXACTAMENTE lo mismo
    que las demás celdas del grid (todas comparten la misma fila/columna
    forzada por el GridLayout), así que el fondo dorado -dibujado con
    pos=self.pos y size=self.size- nunca puede salirse de su casilla.
    """
    def __init__(self, bg=None, **kw):
        super().__init__(**kw)
        self._bg_color = bg
        if bg:
            with self.canvas.before:
                self._color_instr = Color(*bg)
                self._rect_instr = RoundedRectangle(pos=self.pos, size=self.size,
                                                     radius=[dp(8)])
            self.bind(pos=self._actualizar_bg, size=self._actualizar_bg)

    def _actualizar_bg(self, *_):
        self._rect_instr.pos = self.pos
        self._rect_instr.size = self.size


class ButtonBehavior_BoxLayout_cfg(ButtonBehavior, BoxLayout):
    """Fila tocable (ButtonBehavior + BoxLayout) para las categorias de
    Configuracion > Menu. Mismo patron ya probado en este archivo que
    _CeldaDiaCalendario (ButtonBehavior + Label) -- se evita a proposito
    MDIconButton/MDFlatButton aqui: estan importados y parcheados por si
    acaso, pero nunca se usan en el resto del codigo porque en la version
    de KivyMD instalada dieron problemas (ver el comentario grande sobre
    'radius=None en botones legacy' cerca de los imports)."""
    pass


def campo_texto(hint="", password=False, input_filter=None, multiline=False,
                height=dp(44)):
    """Crea un TextInput con el estilo visual de la app.
    Para encadenar campos usa encadenar_campos() despues de crearlos.
    """
    kw = dict(
        hint_text=hint,
        multiline=multiline,
        background_color=SUPERFICIE_FIJA_OSCURA,
        foreground_color=_texto_contraste(SUPERFICIE_FIJA_OSCURA),
        hint_text_color=[0.5, 0.5, 0.5, 1],
        cursor_color=App.get_running_app().DORADO,
        size_hint_y=None,
        height=height,
        padding=[dp(8), dp(10)],
    )
    if password:
        kw["password"] = True
    if input_filter:
        kw["input_filter"] = input_filter
    return TextInput(**kw)


def encadenar_campos(*campos, on_ultimo=None):
    """Encadena N campos: Enter en cada uno mueve el foco al siguiente.
    En el ultimo campo, Enter llama on_ultimo() si se pasa.
    Usa schedule_once para que Android no cierre el teclado entre transiciones.
    """
    lista = list(campos)
    for i, campo in enumerate(lista):
        if i < len(lista) - 1:
            sig = lista[i + 1]
            campo.bind(on_text_validate=lambda inst, s=sig:
                       Clock.schedule_once(lambda dt, _s=s: setattr(_s, "focus", True), 0.05))
        else:
            if on_ultimo:
                campo.bind(on_text_validate=lambda inst: on_ultimo())

# _nuevo_id() ahora vive en database.py (ver import arriba); se deja el
# mismo nombre `_nuevo_id` disponible aqui para no tocar los ~6 lugares
# del archivo que ya lo llaman.

def _cerrar_seguro(popup):
    """Cierra un Popup sin tronar si el usuario ya lo cerró a mano
    (por ejemplo tocando OK justo antes de que dispare el auto-cierre)."""
    try:
        popup.dismiss()
    except Exception:
        pass

def _snack(msg):
    """Snackbar nativo de KivyMD."""
    try:
        Snackbar(
            text=msg,
            snackbar_x="8dp",
            snackbar_y="8dp",
            size_hint_x=0.95,
            duration=2.5,
            bg_color=SUPERFICIE_FIJA_OSCURA,
        ).open()
    except Exception:
        # fallback si Snackbar falla (por ejemplo si la version de KivyMD
        # instalada ya no acepta estos parametros del Snackbar viejo).
        #
        # OJO: aqui antes el Label tenia size_hint por default (1,1) y
        # el popup una altura FIJA de dp(140), sin importar que tan
        # largo fuera el mensaje -- con un texto de 2-3 lineas (como
        # "Escribe un motivo para poder quitar el producto") el texto
        # se cortaba y solo se alcanzaba a ver el ultimo pedazo. Ahora
        # el Label mide su propio texto ya envuelto (mismo mecanismo de
        # auto_height que usa lbl()) y el popup crece con el, para que
        # el mensaje completo siempre se vea entero.
        # NOTA: Popup ya esta disponible como la version corregida
        # (ver el shim definido junto al import original, arriba) --
        # no se re-importa aqui a proposito, para no perder el fix de
        # contraste de fondo/titulo en este popup de respaldo tambien.
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.label import Label
        from kivy.uix.button import Button
        content = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(12),
                            size_hint_y=None)
        content.bind(minimum_height=content.setter("height"))

        _app = App.get_running_app()
        lb = Label(text=msg, color=_texto_contraste(_app.OSCURO), font_size="14sp",
                  halign="center", valign="middle", markup=True,
                  size_hint_y=None)
        lb.bind(width=lambda w, v: setattr(w, "text_size", (v, None)))
        lb.bind(texture_size=lambda w, v: setattr(w, "height", v[1]))
        content.add_widget(lb)

        ok = Button(text="OK", background_color=[0,0,0,0], color=_texto_contraste(_app.ROJO),
                    size_hint_y=None, height=dp(38))
        _set_bg(ok, _app.ROJO)
        content.add_widget(ok)

        popup = Popup(title="", separator_height=0, content=content,
                      size_hint=(0.8, None), background_color=_app.OSCURO)

        def _sync_popup_height(*_):
            popup.height = min(content.height + dp(24), dp(420))
        content.bind(minimum_height=_sync_popup_height)
        _sync_popup_height()

        ok.bind(on_press=lambda *_: popup.dismiss())
        popup.open()
        # Mismo duration=2.5s que se le hubiera dado al Snackbar real, para
        # que este respaldo tambien se cierre solo -- si el Snackbar nativo
        # esta fallando SIEMPRE (posible incompatibilidad de version de
        # KivyMD), que cada aviso de la app exija tocar "OK" a mano seria
        # muy molesto comparado con como se comporta normalmente.
        Clock.schedule_once(lambda dt: _cerrar_seguro(popup), 2.5)

# ── Impresion termica (ESC/POS) ───────────────────────────────────────────────
# Comandos crudos ESC/POS: hablan el 99% de las impresoras termicas baratas
# (58/80mm, Bluetooth o WiFi) sin importar la marca, mientras soporten el
# estandar. _enviar_a_impresora() (metodo de TaqueriaApp, mas abajo) hoy
# corre en "modo prueba" -- no pide ningun permiso de Bluetooth/USB todavia.
_ESC_INIT        = b"\x1b\x40"          # Reinicia la impresora a su estado por defecto
_ESC_BOLD_ON     = b"\x1b\x45\x01"
_ESC_BOLD_OFF    = b"\x1b\x45\x00"
_ESC_GRANDE_ON   = b"\x1d\x21\x11"      # Doble alto + doble ancho (para la cocina)
_ESC_GRANDE_OFF  = b"\x1d\x21\x00"
_ESC_ALIGN_IZQ   = b"\x1b\x61\x00"
_ESC_ALIGN_CEN   = b"\x1b\x61\x01"
_ESC_CORTE       = b"\n\n\n\x1d\x56\x42\x00"   # Avanza papel y corta (corte parcial)
_ESC_ABRIR_CAJON = b"\x1b\x70\x00\x19\xfa"      # ESC p 0 25 250 -- pulso pin 2 (RJ11), el estandar en cajones de dinero conectados a la impresora

# Caracteres por linea segun ancho de papel, con fuente NORMAL (en fuente
# GRANDE de la comanda de cocina caben la mitad).
_ANCHO_CHARS = {"58": 32, "80": 48}

# Ancho en dp del "papel" simulado en la Vista Previa (Configuracion >
# Impresora > Ejemplo). Proporcional al ancho real en mm (dp(4) por mm)
# para que un ticket de 80mm se vea visiblemente mas ancho que uno de
# 58mm, igual que en una impresora fisica -- NO se usa para nada del
# ESC/POS real, solo para el contenedor del Popup.
_ANCHO_PAPEL_DP = {"58": dp(58 * 4), "80": dp(80 * 4)}


def _sin_acentos(texto):
    """La mayoria de impresoras termicas baratas no traen bien la tabla de
    codigos con acentos/ñ (usan CP437/850 y cada marca clona distinto).
    Para evitar simbolos raros en vez de 'ó'/'í'/'ñ', se manda sin acentos."""
    reemplazos = str.maketrans("áéíóúÁÉÍÓÚñÑ", "aeiouAEIOUnN")
    return (texto or "").translate(reemplazos)


def _linea_dos_columnas(izq, der, ancho):
    """'Mesa:1              Hora: 2:35' -- separa izq/der con espacios
    hasta llenar el ancho, o recorta si no cabe (nunca truena)."""
    izq, der = _sin_acentos(izq), _sin_acentos(der)
    espacio = ancho - len(izq) - len(der)
    if espacio < 1:
        return (izq[: max(ancho - len(der) - 1, 0)] + " " + der)[:ancho]
    return izq + (" " * espacio) + der


def _centrar_texto(texto, ancho):
    texto = _sin_acentos(texto)
    if len(texto) >= ancho:
        return texto[:ancho]
    relleno = (ancho - len(texto)) // 2
    return (" " * relleno) + texto


def _separador_texto(ancho, char="-"):
    return char * ancho


# Cache del resultado de _fuente_monoespaciada() -- se busca en disco UNA
# sola vez por sesion (glob recursivo sobre kivy/kivymd instalados), no en
# cada apertura del Popup de Vista Previa.
_FUENTE_MONO = {"intentado": False, "nombre": None}


def _fuente_monoespaciada():
    """Registra una fuente monoespaciada real bajo un nombre propio y la
    regresa lista para usarse como font_name en un Label.

    IMPORTANTE: 'RobotoMono' NO es un font_name valido solo por escribirlo
    -- Kivy solo reconoce nombres de fuente que hayan pasado antes por
    LabelBase.register(); si no, trata el string como nombre de archivo
    literal y truena con OSError('File RobotoMono.ttf not found') apenas
    se crea el primer Label (esto es justo lo que paso en Pydroid).

    Aqui se busca un .ttf monoespaciado real dentro de los paquetes kivymd
    y kivy ya instalados (glob recursivo, sin asumir una ruta fija que
    pueda cambiar entre versiones) y se registra bajo el nombre interno
    'ComanderoMono'. Si no se encuentra ninguno, regresa None -- quien
    llama debe entonces omitir font_name y dejar la fuente default de
    Kivy, para que la Vista Previa jamas truene por esto (el alineado de
    columnas se ve un poco menos perfecto sin fuente monoespaciada, pero
    la app sigue funcionando)."""
    if _FUENTE_MONO["intentado"]:
        return _FUENTE_MONO["nombre"]
    _FUENTE_MONO["intentado"] = True

    import os as _os
    import glob as _glob

    paquetes = []
    try:
        import kivymd
        paquetes.append(_os.path.dirname(kivymd.__file__))
    except Exception:
        pass
    try:
        import kivy
        paquetes.append(_os.path.dirname(kivy.__file__))
    except Exception:
        pass

    encontrado = None
    for base in paquetes:
        for patron in ("**/RobotoMono*.ttf", "**/*Mono*.ttf", "**/DejaVuSansMono*.ttf"):
            try:
                coincidencias = _glob.glob(_os.path.join(base, patron), recursive=True)
            except Exception:
                coincidencias = []
            if coincidencias:
                encontrado = coincidencias[0]
                break
        if encontrado:
            break

    if not encontrado:
        print("[VistaPrevia] No se encontro ninguna fuente monoespaciada instalada; "
              "se usara la fuente default de Kivy.")
        return None

    try:
        from kivy.core.text import LabelBase
        LabelBase.register(name="ComanderoMono", fn_regular=encontrado)
        _FUENTE_MONO["nombre"] = "ComanderoMono"
        print(f"[VistaPrevia] Fuente monoespaciada registrada: {encontrado}")
    except Exception as e:
        print(f"[VistaPrevia] No se pudo registrar la fuente monoespaciada: {e}")
        return None

    return _FUENTE_MONO["nombre"]


# ─────────────────────────────────────────────────────────────────────────────
KV = """
#:import NoTransition kivy.uix.screenmanager.NoTransition
# Boton de la barra de navegacion inferior: icono ARRIBA, texto ABAJO
# (en vez del icono como prefijo en la misma linea que el texto), y
# size_hint_x: 1 para que las 4 pestanas repartan el ancho completo del
# panel por igual entre ellas, en vez de quedar amontonadas a la
# izquierda segun el ancho de su propio contenido.
<TabInferior@ButtonBehavior+BoxLayout>:
    icono: ""
    texto: ""
    color_texto: [1, 1, 1, 1]
    orientation: "vertical"
    size_hint_x: 1
    padding: 0, "4dp"
    canvas.before:
        Color:
            rgba: (app.texto_contraste(app.OSCURO)[:3] + [0.16]) if self.state == "down" else (0, 0, 0, 0)
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(14)]
    Label:
        text: root.icono
        markup: True
        font_size: "18sp"
        color: root.color_texto
        size_hint_y: 0.6
    Label:
        text: root.texto
        font_size: "10sp"
        color: root.color_texto
        size_hint_y: 0.4

<PantallaInicio>:
    name: "inicio"
    MDBoxLayout:
        orientation: "vertical"
        md_bg_color: app.NEGRO

        # Header — logo a la izquierda ocupando todo el alto de la barra,
        # y a la derecha título + botones en dos filas.
        # MDBoxLayout (en vez del BoxLayout + canvas.before de antes) ya
        # trae "md_bg_color" y "radius" de fabrica via BackgroundColor
        # Behavior -- se usa aqui solo para redondear las 2 esquinas
        # inferiores, dando la sensacion de "panel" flotando sobre NEGRO.
        MDBoxLayout:
            orientation: "horizontal"
            size_hint_y: None
            height: "122dp"
            padding: "10dp", "6dp"
            spacing: "10dp"
            md_bg_color: app.OSCURO
            radius: [0, 0, dp(16), dp(16)]

            Image:
                id: img_logo
                source: app.logo_path
                opacity: 1 if app.logo_path else 0
                size_hint_x: None
                width: "110dp" if app.logo_path else 0
                allow_stretch: True
                keep_ratio: True

            MDBoxLayout:
                orientation: "vertical"
                spacing: "4dp"

                # Fila 1: título
                MDLabel:
                    id: lbl_nombre_taqueria
                    text: app.nombre_taqueria
                    markup: True
                    theme_text_color: "Custom"
                    text_color: app.texto_contraste(app.OSCURO)
                    font_size: "26sp"
                    halign: "left"
                    valign: "middle"
                    text_size: self.size
                    shorten: True
                    shorten_from: "right"

                # Fila 2: botones Gastos, Cierre y Servidor de meseros —
                # componentes reales de KivyMD: MDRectangleFlatButton
                # (borde real via line_color) y MDRaisedButton (elevacion
                # real).
                #
                # OJO: los botones "viejos" de KivyMD (MDRectangleFlat
                # Button, MDRaisedButton) NO respetan size_hint_x -- se
                # autoajustan al ancho de su propio texto (es un
                # comportamiento documentado de KivyMD, no un bug de esta
                # app), asi que en pantallas angostas los 3 juntos se
                # salian por el borde derecho.
                #
                # Arreglo: cada boton va DENTRO de un BoxLayout "normal"
                # (sin comportamiento de auto-ancho -- ese SI respeta
                # size_hint_x como cualquier layout de Kivy), con
                # size_hint_x proporcional (40% / 40% / 20%). Ademas, el
                # boton se liga en KV a size/pos de ese contenedor
                # (size: self.parent.size / pos: self.parent.pos), y por
                # si el boton intenta cambiar su propio tamano despues (su
                # auto-ancho interno), on_size/on_pos llaman a
                # app._clamp_a_contenedor() para regresarlo de inmediato al
                # tamano de su contenedor -- asi nunca se puede salir de su
                # tercio de fila, sin importar que tan largo sea su texto.
                MDBoxLayout:
                    orientation: "horizontal"
                    size_hint_y: None
                    height: "44dp"
                    spacing: "10dp"

                    BoxLayout:
                        id: cont_gastos_caja
                        size_hint_x: 0.40
                        Button:
                            # Se cambio de MDRectangleFlatButton a un Button
                            # plano: el boton "viejo" de KivyMD se auto-ajusta
                            # a su TEXTO natural, y cuando _clamp_a_contenedor
                            # lo forzaba a un ancho mas chico (para no salirse
                            # de su tercio de fila), el texto de adentro no se
                            # achicaba ni se recortaba -- simplemente se
                            # dibujaba mas ancho que el boton y "chocaba" con
                            # el borde (se salia visualmente de el). Un Button
                            # normal de Kivy si respeta text_size + shorten de
                            # verdad, asi que el texto queda SIEMPRE adentro
                            # del widget, recortado con "..." si no cabe.
                            text: app.icono("cash") + " GASTOS\\nCAJA"
                            markup: True
                            font_size: "10sp"
                            shorten: True
                            shorten_from: "right"
                            max_lines: 2
                            halign: "center"
                            valign: "middle"
                            background_color: [0, 0, 0, 0]
                            color: app.texto_contraste(app.OSCURO)
                            on_release: app.abrir_gastos_caja()
                            size_hint: None, None
                            size: self.parent.size
                            pos: self.parent.pos
                            text_size: self.width - dp(6), self.height
                            on_size: app._clamp_a_contenedor(self)
                            on_pos: app._clamp_a_contenedor(self)
                            canvas.before:
                                Color:
                                    rgba: app.texto_contraste(app.OSCURO)[:3] + [0.55]
                                Line:
                                    rounded_rectangle: [self.x, self.y, self.width, self.height, dp(10)]
                                    width: 1

                    BoxLayout:
                        id: cont_cierre_caja
                        size_hint_x: 0.40
                        Button:
                            # Mismo motivo que arriba: MDRaisedButton no
                            # reajustaba su texto al achicarse, y "CIERRE DE
                            # CAJA" (mas largo que "GASTOS CAJA") era el que
                            # mas se notaba saliendose del boton.
                            text: app.icono("cash-register") + " CIERRE\\nCAJA"
                            markup: True
                            font_size: "10sp"
                            shorten: True
                            shorten_from: "right"
                            max_lines: 2
                            halign: "center"
                            valign: "middle"
                            background_color: [0, 0, 0, 0]
                            color: app.texto_contraste(app.ACCENT)
                            on_release: app.abrir_cierre_caja()
                            size_hint: None, None
                            size: self.parent.size
                            pos: self.parent.pos
                            text_size: self.width - dp(6), self.height
                            on_size: app._clamp_a_contenedor(self)
                            on_pos: app._clamp_a_contenedor(self)
                            canvas.before:
                                Color:
                                    rgba: app.ACCENT
                                RoundedRectangle:
                                    pos: self.pos
                                    size: self.size
                                    radius: [dp(10)]

                    BoxLayout:
                        id: cont_srv
                        size_hint_x: 0.20
                        MDRaisedButton:
                            text: "SRV"
                            font_size: "12sp"
                            md_bg_color: app.DORADO
                            theme_text_color: "Custom"
                            text_color: app.texto_contraste(app.DORADO)
                            elevation: 1
                            on_release: app.abrir_popup_servidor()
                            size_hint: None, None
                            size: self.parent.size
                            pos: self.parent.pos
                            on_size: app._clamp_a_contenedor(self)
                            on_pos: app._clamp_a_contenedor(self)



        # Cuerpo — una sola columna, ancho completo, con scroll
        ScrollView:
            do_scroll_x: False
            MDBoxLayout:
                orientation: "vertical"
                size_hint_y: None
                height: self.minimum_height
                padding: "14dp"
                spacing: "16dp"

                # Card DOMICILIO + resumen HOY (ancho completo). MDCard
                # real: esquinas redondeadas (radius) + sombra/elevacion
                # de verdad, en vez del RoundedRectangle plano de antes.
                MDCard:
                    orientation: "vertical"
                    size_hint_y: None
                    height: self.minimum_height
                    padding: "14dp", "6dp", "14dp", "10dp"
                    spacing: "6dp"
                    radius: [dp(18)]
                    elevation: 0
                    theme_bg_color: "Custom"
                    md_bg_color: app.OSCURO
                    canvas.after:
                        Color:
                            rgba: app.texto_contraste(app.OSCURO)[:3] + [0.08]
                        Line:
                            rounded_rectangle: [self.x, self.y, self.width, self.height, dp(18)]
                            width: 1

                    MDBoxLayout:
                        orientation: "horizontal"
                        size_hint_y: None
                        height: "26dp"
                        MDLabel:
                            text: "[b]DOMICILIO[/b]"
                            markup: True
                            theme_text_color: "Custom"
                            text_color: app.texto_contraste(app.OSCURO)
                            font_size: "14sp"
                            halign: "left"
                            valign: "middle"
                            text_size: self.size
                            size_hint_x: 0.27
                        MDLabel:
                            id: lbl_fecha_hora
                            text: ""
                            markup: True
                            theme_text_color: "Custom"
                            text_color: app.texto_contraste(app.OSCURO)[:3] + [0.75]
                            font_size: "11sp"
                            halign: "center"
                            valign: "middle"
                            text_size: self.width, None
                            size_hint_x: 0.46
                            shorten: True
                            shorten_from: "right"
                        MDLabel:
                            text: "[b]HOY[/b]"
                            markup: True
                            theme_text_color: "Custom"
                            text_color: app.texto_contraste(app.OSCURO)
                            font_size: "14sp"
                            halign: "right"
                            valign: "middle"
                            text_size: self.size
                            size_hint_x: 0.27

                    # KPI Badges: 3 columnas independientes (numero grande
                    # arriba, descripcion gris abajo), como en la referencia.
                    MDGridLayout:
                        cols: 3
                        size_hint_y: None
                        height: "58dp"
                        spacing: "8dp"

                        MDBoxLayout:
                            orientation: "vertical"
                            MDLabel:
                                id: stat_domicilios_num
                                text: "0"
                                markup: True
                                theme_text_color: "Custom"
                                text_color: app.texto_contraste(app.OSCURO)
                                font_size: "22sp"
                                bold: True
                                halign: "center"
                                valign: "bottom"
                                text_size: self.size
                            MDLabel:
                                text: "Domicilios:"
                                theme_text_color: "Custom"
                                text_color: app.texto_contraste(app.OSCURO)[:3] + [0.55]
                                font_size: "11sp"
                                halign: "center"
                                valign: "top"
                                text_size: self.size

                        MDBoxLayout:
                            orientation: "vertical"
                            MDLabel:
                                id: stat_mesas_num
                                text: "0"
                                markup: True
                                theme_text_color: "Custom"
                                text_color: app.texto_contraste(app.OSCURO)
                                font_size: "22sp"
                                bold: True
                                halign: "center"
                                valign: "bottom"
                                text_size: self.size
                            MDLabel:
                                text: "Mesas del dia:"
                                theme_text_color: "Custom"
                                text_color: app.texto_contraste(app.OSCURO)[:3] + [0.55]
                                font_size: "11sp"
                                halign: "center"
                                valign: "top"
                                text_size: self.size

                        MDBoxLayout:
                            orientation: "vertical"
                            MDLabel:
                                id: stat_activos_num
                                text: "0"
                                markup: True
                                theme_text_color: "Custom"
                                text_color: app.texto_contraste(app.OSCURO)
                                font_size: "22sp"
                                bold: True
                                halign: "center"
                                valign: "bottom"
                                text_size: self.size
                            MDLabel:
                                text: "Pedidos activos:"
                                theme_text_color: "Custom"
                                text_color: app.texto_contraste(app.OSCURO)[:3] + [0.55]
                                font_size: "11sp"
                                halign: "center"
                                valign: "top"
                                text_size: self.size

                    MDRaisedButton:
                        text: "NUEVO PEDIDO"
                        font_size: "13sp"
                        bold: True
                        size_hint_y: None
                        height: "44dp"
                        size_hint_x: 1
                        md_bg_color: app.ROJO
                        theme_text_color: "Custom"
                        text_color: app.texto_contraste(app.ROJO)
                        radius: [dp(10)]
                        elevation: 2
                        on_release: app.iniciar_orden_domicilio()

                # Sección MESAS (ancho completo, grid parejo de 4 columnas)
                MDLabel:
                    text: "[b]MESAS[/b]"
                    markup: True
                    theme_text_color: "Custom"
                    text_color: app.texto_contraste(app.NEGRO)
                    font_size: "14sp"
                    size_hint_y: None
                    height: "26dp"
                    halign: "left"
                    text_size: self.size

                MDGridLayout:
                    id: grid_mesas
                    cols: 4
                    spacing: "10dp"
                    size_hint_y: None
                    height: self.minimum_height

        # Nav inferior — MDBoxLayout con MDFlatButton (ripple real de
        # KivyMD en vez del Button plano de antes).
        MDBoxLayout:
            size_hint_y: None
            height: "60dp"
            md_bg_color: app.OSCURO
            padding: "6dp"
            spacing: "4dp"
            TabInferior:
                icono: app.icono("table-chair")
                texto: "Inicio"
                color_texto: app.DORADO
                on_release: app.go_to("inicio")
            TabInferior:
                icono: app.icono("ticket")
                texto: "Pedidos"
                color_texto: app.texto_contraste(app.OSCURO)
                on_release: app.ir_activos()
            TabInferior:
                icono: app.icono("chart-bar")
                texto: "Estadisticas"
                color_texto: app.texto_contraste(app.OSCURO)
                on_release: app.ir_estadisticas()
            TabInferior:
                icono: app.icono("cog")
                texto: "Config"
                color_texto: app.texto_contraste(app.OSCURO)
                on_release: app.ir_config()


# ══════ ORDEN ════════════════════════════════════════════════════════════════
<PantallaOrden>:
    name: "orden"
    BoxLayout:
        orientation: "vertical"
        canvas.before:
            Color:
                rgba: app.NEGRO
            Rectangle:
                pos: self.pos
                size: self.size

        # Header
        MDBoxLayout:
            size_hint_y: None
            height: "56dp"
            padding: "14dp", "8dp"
            spacing: "8dp"
            md_bg_color: app.OSCURO
            radius: [0, 0, dp(16), dp(16)]
            Label:
                text: app.icono("silverware-fork-knife")
                markup: True
                font_size: "18sp"
                color: app.texto_contraste(app.OSCURO)
                size_hint_x: None
                width: "24dp"
                halign: "center"
                valign: "middle"
                text_size: self.size
            Label:
                id: lbl_titulo_orden
                text: "Nuevo Pedido"
                bold: True
                color: app.texto_contraste(app.OSCURO)
                font_size: "19sp"
                halign: "left"
                valign: "middle"
                text_size: self.size

        # Botón oculto — referenciado por Python, sin espacio visual
        Button:
            id: btn_ver_pedido
            text: ""
            size_hint_y: None
            height: 0
            opacity: 0
            disabled: True
            background_color: [0,0,0,0]
            on_press: app.ver_pedido_actual()

        # Campos domicilio
        BoxLayout:
            id: box_domicilio
            orientation: "vertical"
            size_hint_y: None
            height: 0
            opacity: 0
            canvas.before:
                Color:
                    rgba: app.OSCURO
                Rectangle:
                    pos: self.pos
                    size: self.size
            padding: "10dp"
            spacing: "4dp"
            TextInput:
                id: campo_nombre
                hint_text: "Nombre del cliente *"
                multiline: False
                background_color: app.SUPERFICIE_FIJA_OSCURA
                foreground_color: app.texto_contraste(app.SUPERFICIE_FIJA_OSCURA)
                hint_text_color: [0.5, 0.5, 0.5, 1]
                cursor_color: app.DORADO
                padding: "8dp", "10dp"
                size_hint_y: None
                height: "44dp"
                focus: False
            TextInput:
                id: campo_telefono
                hint_text: "Telefono"
                multiline: False
                background_color: app.SUPERFICIE_FIJA_OSCURA
                foreground_color: app.texto_contraste(app.SUPERFICIE_FIJA_OSCURA)
                hint_text_color: [0.5, 0.5, 0.5, 1]
                cursor_color: app.DORADO
                padding: "8dp", "10dp"
                size_hint_y: None
                height: "44dp"
                focus: False
            TextInput:
                id: campo_direccion
                hint_text: "Direccion"
                multiline: False
                background_color: app.SUPERFICIE_FIJA_OSCURA
                foreground_color: app.texto_contraste(app.SUPERFICIE_FIJA_OSCURA)
                hint_text_color: [0.5, 0.5, 0.5, 1]
                cursor_color: app.DORADO
                padding: "8dp", "10dp"
                size_hint_y: None
                height: "44dp"
                focus: False

        # Cuerpo dividido
        BoxLayout:
            orientation: "horizontal"
            padding: "8dp"
            spacing: "8dp"

            # Izquierdo — menú
            BoxLayout:
                orientation: "vertical"
                spacing: "6dp"
                size_hint_x: 0.58

                # Tabs
                ScrollView:
                    size_hint_y: None
                    height: "48dp"
                    do_scroll_y: False
                    BoxLayout:
                        id: tabs_cats
                        orientation: "horizontal"
                        spacing: "6dp"
                        size_hint_x: None
                        width: self.minimum_width

                # Productos
                ScrollView:
                    size_hint_y: 1
                    BoxLayout:
                        id: lista_prods
                        orientation: "vertical"
                        spacing: "6dp"
                        size_hint_y: None
                        height: self.minimum_height
                        padding: [dp(6), dp(6), dp(6), dp(6)]

            # Derecho — resumen
            BoxLayout:
                orientation: "vertical"
                spacing: "6dp"
                size_hint_x: 0.42

                BoxLayout:
                    size_hint_y: None
                    height: "44dp"
                    canvas.before:
                        Color:
                            rgba: app.ROJO
                        RoundedRectangle:
                            pos: self.pos
                            size: self.size
                            radius: [dp(16)]
                    padding: "12dp", "6dp"
                    spacing: "6dp"
                    Label:
                        text: app.icono("cart-outline")
                        markup: True
                        font_size: "16sp"
                        color: app.texto_contraste(app.ROJO)
                        size_hint_x: None
                        width: "20dp"
                        halign: "center"
                        valign: "middle"
                        text_size: self.size
                    Label:
                        text: "[b]TU PEDIDO[/b]"
                        markup: True
                        font_size: "14sp"
                        color: app.texto_contraste(app.ROJO)
                        halign: "left"
                        valign: "middle"
                        text_size: self.size

                ScrollView:
                    size_hint_y: 1
                    canvas.before:
                        Color:
                            rgba: app.texto_contraste(app.NEGRO)[:3] + [0.05]
                        RoundedRectangle:
                            pos: self.pos
                            size: self.size
                            radius: [dp(16)]
                        Color:
                            rgba: app.texto_contraste(app.NEGRO)[:3] + [0.08]
                        Line:
                            rounded_rectangle: [self.x, self.y, self.width, self.height, dp(16)]
                            width: 1
                    BoxLayout:
                        id: lista_resumen
                        orientation: "vertical"
                        spacing: "8dp"
                        padding: [0, "4dp", 0, "4dp"]
                        size_hint_y: None
                        height: self.minimum_height

                BoxLayout:
                    size_hint_y: None
                    height: "46dp"
                    canvas.before:
                        Color:
                            rgba: app.DORADO
                        RoundedRectangle:
                            pos: self.pos
                            size: self.size
                            radius: [dp(16)]
                    padding: "10dp", "6dp"
                    Label:
                        text: "[b]TOTAL[/b]"
                        markup: True
                        color: app.texto_contraste(app.DORADO)
                        font_size: "18sp"
                        halign: "left"
                        text_size: self.size
                    Label:
                        id: lbl_total
                        text: "$0"
                        bold: True
                        color: app.texto_contraste(app.DORADO)
                        font_size: "24sp"
                        halign: "right"
                        text_size: self.size

                Button:
                    text: "GUARDAR PEDIDO"
                    background_color: [0,0,0,0]
                    color: app.texto_contraste(app.ROJO)
                    size_hint_y: None
                    height: "44dp"
                    font_size: "13sp"
                    on_press: app.guardar_pedido()
                    canvas.before:
                        Color:
                            rgba: app.ROJO
                        RoundedRectangle:
                            pos: self.pos
                            size: self.size
                            radius: [dp(16)]
                    canvas.after:
                        Color:
                            rgba: (app.texto_contraste(app.ROJO)[:3] + [0.16]) if self.state == "down" else (0, 0, 0, 0)
                        RoundedRectangle:
                            pos: self.pos
                            size: self.size
                            radius: [dp(16)]

                Button:
                    text: "ELIMINAR"
                    background_color: [0,0,0,0]
                    color: app.texto_contraste(app.OSCURO)
                    size_hint_y: None
                    height: "44dp"
                    font_size: "13sp"
                    on_press: app.eliminar_orden_mesa()
                    canvas.before:
                        Color:
                            rgba: app.OSCURO
                        RoundedRectangle:
                            pos: self.pos
                            size: self.size
                            radius: [dp(16)]
                    canvas.after:
                        Color:
                            rgba: (app.texto_contraste(app.OSCURO)[:3] + [0.12]) if self.state == "down" else (0, 0, 0, 0)
                        RoundedRectangle:
                            pos: self.pos
                            size: self.size
                            radius: [dp(16)]



# ══════ ACTIVOS ═══════════════════════════════════════════════════════════════
<PantallaActivos>:
    name: "activos"
    BoxLayout:
        orientation: "vertical"
        canvas.before:
            Color:
                rgba: app.NEGRO
            Rectangle:
                pos: self.pos
                size: self.size

        # Header con titulo y botones flotantes de filtro
        BoxLayout:
            size_hint_y: None
            height: "88dp"
            orientation: "vertical"
            canvas.before:
                Color:
                    rgba: app.OSCURO
                Rectangle:
                    pos: self.pos
                    size: self.size

            Label:
                text: "[b]PEDIDOS ACTIVOS[/b]"
                markup: True
                color: app.texto_contraste(app.OSCURO)
                font_size: "17sp"
                size_hint_y: None
                height: "42dp"
                halign: "left"
                text_size: self.size
                padding_x: "12dp"

            BoxLayout:
                orientation: "horizontal"
                size_hint_y: None
                height: "44dp"
                spacing: "10dp"
                padding: "12dp", "0dp"
                Button:
                    text: "TODOS"
                    background_color: [0,0,0,0]
                    color: app.texto_contraste(app.OSCURO)
                    font_size: "12sp"
                    on_press: app.filtrar_pedidos("todos")
                    canvas.before:
                        Color:
                            rgba: app.OSCURO
                        RoundedRectangle:
                            pos: self.pos
                            size: self.size
                            radius: [dp(12)]
                Button:
                    text: "MESAS"
                    background_color: [0,0,0,0]
                    color: app.texto_contraste(app.ROJO)
                    font_size: "12sp"
                    on_press: app.filtrar_pedidos("mesa")
                    canvas.before:
                        Color:
                            rgba: app.ROJO
                        RoundedRectangle:
                            pos: self.pos
                            size: self.size
                            radius: [dp(12)]
                Button:
                    text: "DOMICILIOS"
                    background_color: [0,0,0,0]
                    color: app.texto_contraste(app.ACCENT)
                    font_size: "12sp"
                    on_press: app.filtrar_pedidos("domicilio")
                    canvas.before:
                        Color:
                            rgba: app.ACCENT
                        RoundedRectangle:
                            pos: self.pos
                            size: self.size
                            radius: [dp(12)]


        ScrollView:
            BoxLayout:
                id: lista_activos
                orientation: "vertical"
                spacing: "10dp"
                padding: "10dp"
                size_hint_y: None
                height: self.minimum_height

        BoxLayout:
            size_hint_y: None
            height: "60dp"
            canvas.before:
                Color:
                    rgba: app.OSCURO
                Rectangle:
                    pos: self.pos
                    size: self.size
            padding: "6dp"
            spacing: "4dp"
            TabInferior:
                icono: app.icono("table-chair")
                texto: "Inicio"
                color_texto: app.texto_contraste(app.OSCURO)
                on_release: app.go_to("inicio")
            TabInferior:
                icono: app.icono("ticket")
                texto: "Pedidos"
                color_texto: app.DORADO
                on_release: app.ir_activos()
            TabInferior:
                icono: app.icono("chart-bar")
                texto: "Estadisticas"
                color_texto: app.texto_contraste(app.OSCURO)
                on_release: app.ir_estadisticas()
            TabInferior:
                icono: app.icono("cog")
                texto: "Config"
                color_texto: app.texto_contraste(app.OSCURO)
                on_release: app.ir_config()


# ══════ CONFIG ════════════════════════════════════════════════════════════════
<PantallaConfig>:
    name: "config"
    BoxLayout:
        orientation: "vertical"
        canvas.before:
            Color:
                rgba: app.CFG_FONDO
            Rectangle:
                pos: self.pos
                size: self.size

        # ── Header (altura fija) ──
        BoxLayout:
            size_hint_y: None
            height: "52dp"
            canvas.before:
                Color:
                    rgba: app.CFG_TARJETA
                Rectangle:
                    pos: self.pos
                    size: self.size
                Color:
                    rgba: 0.902, 0.898, 0.886, 1
                Line:
                    points: [self.x, self.y, self.x + self.width, self.y]
                    width: 1
            padding: "8dp"
            spacing: "8dp"
            Button:
                text: "<"
                bold: True
                background_color: [0,0,0,0]
                color: app.CFG_TEXTO
                size_hint_x: None
                width: "40dp"
                font_size: "20sp"
                on_press: app.go_to("inicio")
            Label:
                text: "[b]CONFIGURACION DEL MENU[/b]"
                markup: True
                color: app.CFG_TEXTO
                font_size: "16sp"
                halign: "left"
                text_size: self.size

        # ── Selector de secciones (altura fija) ──
        # Reemplaza al viejo layout de una sola columna donde Categorias,
        # Productos, Mesas, Empleados y Personalizacion iban todos
        # apilados dentro de un ScrollView gigante que terminaba
        # desbordandose sobre el nav inferior. Ahora la pantalla se
        # divide en dos secciones (Menu / Operativa) que se muestran una
        # a la vez, cada una ocupando exactamente el espacio disponible.
        BoxLayout:
            size_hint_y: None
            height: "48dp"
            padding: "12dp", "6dp"
            canvas.before:
                Color:
                    rgba: app.CFG_TARJETA
                Rectangle:
                    pos: self.pos
                    size: self.size
                Color:
                    rgba: 0.902, 0.898, 0.886, 1
                Line:
                    points: [self.x, self.y, self.x + self.width, self.y]
                    width: 1

            BoxLayout:
                orientation: "horizontal"
                padding: "3dp"
                canvas.before:
                    Color:
                        rgba: 0.933, 0.929, 0.918, 1
                    RoundedRectangle:
                        pos: self.pos
                        size: self.size
                        radius: [dp(10)]

                Button:
                    text: "CATALOGO"
                    bold: True
                    font_size: "12sp"
                    background_color: [0,0,0,0]
                    color: app.CFG_TARJETA if app.config_tab == "menu" else (app.CFG_TEXTO_GRIS)
                    on_press: app.set_config_tab("menu")
                    canvas.before:
                        Color:
                            rgba: (app.CFG_EMERALD) if app.config_tab == "menu" else (0,0,0,0)
                        RoundedRectangle:
                            pos: self.pos
                            size: self.size
                            radius: [dp(8)]

                Button:
                    text: "OPERATIVA"
                    bold: True
                    font_size: "12sp"
                    background_color: [0,0,0,0]
                    color: app.CFG_TARJETA if app.config_tab == "operativa" else (app.CFG_TEXTO_GRIS)
                    on_press: app.set_config_tab("operativa")
                    canvas.before:
                        Color:
                            rgba: (app.CFG_EMERALD) if app.config_tab == "operativa" else (0,0,0,0)
                        RoundedRectangle:
                            pos: self.pos
                            size: self.size
                            radius: [dp(8)]

        # ── Contenido (llena TODO el espacio restante, sin scroll de pagina) ──
        ScreenManager:
            id: sm_config
            size_hint_y: 1
            transition: NoTransition()

            Screen:
                name: "menu"
                BoxLayout:
                    orientation: "horizontal"
                    padding: "12dp"
                    spacing: "10dp"

                    # Columna categorías
                    BoxLayout:
                        orientation: "vertical"
                        spacing: "6dp"
                        size_hint_x: 0.38

                        # Card lista (flexible: llena el espacio libre)
                        BoxLayout:
                            orientation: "vertical"
                            padding: "10dp"
                            spacing: "4dp"
                            size_hint_y: 1
                            canvas.before:
                                Color:
                                    rgba: app.CFG_TARJETA
                                RoundedRectangle:
                                    pos: self.pos
                                    size: self.size
                                    radius: [dp(12)]
                                Color:
                                    rgba: 0, 0, 0, 0.06
                                Line:
                                    rounded_rectangle: [self.x, self.y, self.width, self.height, dp(12)]
                                    width: 1

                            Label:
                                text: "CATEGORIAS"
                                bold: True
                                color: app.CFG_TEXTO
                                font_size: "11sp"
                                size_hint_y: None
                                height: "16dp"
                                halign: "left"
                                text_size: self.size

                            ScrollView:
                                do_scroll_x: False
                                size_hint_y: 1
                                BoxLayout:
                                    id: lista_cats_cfg
                                    orientation: "vertical"
                                    spacing: "6dp"
                                    size_hint_y: None
                                    height: self.minimum_height
                                    padding: [0, "4dp"]

                        # Card "agregar categoría" (altura fija, siempre visible)
                        BoxLayout:
                            orientation: "vertical"
                            spacing: "6dp"
                            size_hint_y: None
                            height: "112dp"
                            padding: "10dp"
                            canvas.before:
                                Color:
                                    rgba: app.CFG_TARJETA
                                RoundedRectangle:
                                    pos: self.pos
                                    size: self.size
                                    radius: [dp(12)]
                                Color:
                                    rgba: 0, 0, 0, 0.06
                                Line:
                                    rounded_rectangle: [self.x, self.y, self.width, self.height, dp(12)]
                                    width: 1

                            TextInput:
                                id: campo_nueva_cat
                                hint_text: "Nueva categoria"
                                multiline: False
                                background_color: app.CFG_CAMPO_BG
                                foreground_color: app.CFG_TEXTO
                                hint_text_color: app.CFG_HINT_GRIS
                                cursor_color: app.CFG_EMERALD
                                padding: "8dp", "10dp"
                                size_hint_y: None
                                height: "40dp"
                                on_text_validate: app.agregar_categoria()

                            Button:
                                text: "+  AGREGAR"
                                bold: True
                                font_size: "12sp"
                                background_color: [0,0,0,0]
                                color: app.CFG_TARJETA
                                size_hint_y: None
                                height: "44dp"
                                on_press: app.agregar_categoria()
                                canvas.before:
                                    Color:
                                        rgba: app.CFG_EMERALD
                                    RoundedRectangle:
                                        pos: self.pos
                                        size: self.size
                                        radius: [dp(10)]

                    # Columna productos
                    BoxLayout:
                        orientation: "vertical"
                        spacing: "6dp"
                        size_hint_x: 0.62

                        # Card lista (flexible: llena el espacio libre)
                        BoxLayout:
                            orientation: "vertical"
                            padding: "10dp"
                            spacing: "4dp"
                            size_hint_y: 1
                            canvas.before:
                                Color:
                                    rgba: app.CFG_TARJETA
                                RoundedRectangle:
                                    pos: self.pos
                                    size: self.size
                                    radius: [dp(12)]
                                Color:
                                    rgba: 0, 0, 0, 0.06
                                Line:
                                    rounded_rectangle: [self.x, self.y, self.width, self.height, dp(12)]
                                    width: 1

                            Label:
                                id: lbl_cat_cfg
                                text: "Selecciona una categoria"
                                bold: True
                                color: app.CFG_TEXTO
                                font_size: "13sp"
                                size_hint_y: None
                                height: "22dp"
                                halign: "left"
                                text_size: self.size

                            ScrollView:
                                do_scroll_x: False
                                size_hint_y: 1
                                BoxLayout:
                                    id: lista_prods_cfg
                                    orientation: "vertical"
                                    spacing: "6dp"
                                    size_hint_y: None
                                    height: self.minimum_height
                                    padding: [0, "4dp"]

                        # Card "agregar producto" (altura fija, siempre visible)
                        BoxLayout:
                            orientation: "vertical"
                            spacing: "6dp"
                            size_hint_y: None
                            height: "112dp"
                            padding: "10dp"
                            canvas.before:
                                Color:
                                    rgba: app.CFG_TARJETA
                                RoundedRectangle:
                                    pos: self.pos
                                    size: self.size
                                    radius: [dp(12)]
                                Color:
                                    rgba: 0, 0, 0, 0.06
                                Line:
                                    rounded_rectangle: [self.x, self.y, self.width, self.height, dp(12)]
                                    width: 1

                            BoxLayout:
                                orientation: "horizontal"
                                spacing: "6dp"
                                size_hint_y: None
                                height: "40dp"

                                TextInput:
                                    id: campo_prod_nombre
                                    hint_text: "Nombre del producto"
                                    multiline: False
                                    background_color: app.CFG_CAMPO_BG
                                    foreground_color: app.CFG_TEXTO
                                    hint_text_color: app.CFG_HINT_GRIS
                                    cursor_color: app.CFG_EMERALD
                                    padding: "8dp", "10dp"
                                    size_hint_x: 0.62

                                TextInput:
                                    id: campo_prod_precio
                                    hint_text: "Precio"
                                    multiline: False
                                    input_filter: "float"
                                    background_color: app.CFG_CAMPO_BG
                                    foreground_color: app.CFG_TEXTO
                                    hint_text_color: app.CFG_HINT_GRIS
                                    cursor_color: app.CFG_EMERALD
                                    padding: "8dp", "10dp"
                                    size_hint_x: 0.38
                                    on_text_validate: app.agregar_producto_cfg()

                            Button:
                                text: "+  AGREGAR PRODUCTO"
                                bold: True
                                font_size: "12sp"
                                background_color: [0,0,0,0]
                                color: app.CFG_TARJETA
                                size_hint_y: None
                                height: "44dp"
                                on_press: app.agregar_producto_cfg()
                                canvas.before:
                                    Color:
                                        rgba: app.CFG_EMERALD
                                    RoundedRectangle:
                                        pos: self.pos
                                        size: self.size
                                        radius: [dp(10)]

            Screen:
                name: "operativa"
                BoxLayout:
                    orientation: "vertical"
                    padding: "12dp"
                    spacing: "12dp"

                    # Mesas
                    BoxLayout:
                        orientation: "vertical"
                        size_hint_y: None
                        height: "104dp"
                        padding: "14dp"
                        spacing: "8dp"
                        canvas.before:
                            Color:
                                rgba: app.CFG_TARJETA
                            RoundedRectangle:
                                pos: self.pos
                                size: self.size
                                radius: [dp(12)]
                            Color:
                                rgba: 0, 0, 0, 0.06
                            Line:
                                rounded_rectangle: [self.x, self.y, self.width, self.height, dp(12)]
                                width: 1

                        Label:
                            text: "MESAS"
                            bold: True
                            color: app.CFG_EMERALD
                            font_size: "12sp"
                            size_hint_y: None
                            height: "16dp"
                            halign: "left"
                            text_size: self.size

                        BoxLayout:
                            orientation: "horizontal"
                            size_hint_y: None
                            height: "44dp"
                            spacing: "14dp"

                            Button:
                                text: app.icono("minus")
                                markup: True
                                background_color: [0,0,0,0]
                                color: app.CFG_ALERTA
                                font_size: "18sp"
                                size_hint: None, None
                                size: "38dp", "38dp"
                                on_press: app.confirmar_quitar_mesa()
                                canvas.before:
                                    Color:
                                        rgba: app.CFG_ALERTA_SOFT
                                    RoundedRectangle:
                                        pos: self.pos
                                        size: self.size
                                        radius: [dp(19)]

                            Label:
                                id: lbl_num_mesas
                                text: "Mesas totales: 0"
                                bold: True
                                color: app.CFG_TEXTO
                                font_size: "15sp"
                                halign: "center"
                                valign: "middle"
                                text_size: self.size

                            Button:
                                text: app.icono("plus")
                                markup: True
                                background_color: [0,0,0,0]
                                color: app.CFG_TARJETA
                                font_size: "18sp"
                                size_hint: None, None
                                size: "38dp", "38dp"
                                on_press: app.agregar_mesa()
                                canvas.before:
                                    Color:
                                        rgba: app.CFG_EMERALD
                                    RoundedRectangle:
                                        pos: self.pos
                                        size: self.size
                                        radius: [dp(19)]

                    # Empleados
                    BoxLayout:
                        orientation: "horizontal"
                        size_hint_y: None
                        height: "64dp"
                        padding: "14dp"
                        spacing: "10dp"
                        canvas.before:
                            Color:
                                rgba: app.CFG_TARJETA
                            RoundedRectangle:
                                pos: self.pos
                                size: self.size
                                radius: [dp(12)]
                            Color:
                                rgba: 0, 0, 0, 0.06
                            Line:
                                rounded_rectangle: [self.x, self.y, self.width, self.height, dp(12)]
                                width: 1

                        Label:
                            text: "EMPLEADOS"
                            bold: True
                            color: app.CFG_EMERALD
                            font_size: "12sp"
                            halign: "left"
                            valign: "middle"
                            text_size: self.size

                        Button:
                            text: "GESTIONAR PERSONAL"
                            bold: True
                            background_color: [0,0,0,0]
                            color: app.CFG_TARJETA
                            font_size: "12sp"
                            size_hint_x: None
                            width: "190dp"
                            on_press: app.abrir_empleados()
                            canvas.before:
                                Color:
                                    rgba: app.CFG_EMERALD
                                RoundedRectangle:
                                    pos: self.pos
                                    size: self.size
                                    radius: [dp(10)]

                    # Personalización
                    ButtonBehavior_BoxLayout_cfg:
                        orientation: "horizontal"
                        size_hint_y: None
                        height: "56dp"
                        padding: "14dp"
                        spacing: "10dp"
                        on_release: app.abrir_personalizacion()
                        canvas.before:
                            Color:
                                rgba: app.CFG_TARJETA
                            RoundedRectangle:
                                pos: self.pos
                                size: self.size
                                radius: [dp(12)]
                            Color:
                                rgba: 0, 0, 0, 0.06
                            Line:
                                rounded_rectangle: [self.x, self.y, self.width, self.height, dp(12)]
                                width: 1

                        Label:
                            text: "Personalización de la app"
                            color: app.CFG_TEXTO
                            font_size: "13sp"
                            halign: "left"
                            valign: "middle"
                            text_size: self.size

                        Label:
                            text: app.icono("chevron-right")
                            markup: True
                            color: app.CFG_EMERALD
                            font_size: "16sp"
                            size_hint_x: None
                            width: "24dp"
                            halign: "right"
                            valign: "middle"
                            text_size: self.size

                    Widget:
                        size_hint_y: 1

        # ── Nav inferior fijo ──
        BoxLayout:
            size_hint_y: None
            height: "60dp"
            canvas.before:
                Color:
                    rgba: app.CFG_TARJETA
                Rectangle:
                    pos: self.pos
                    size: self.size
                Color:
                    rgba: 0.902, 0.898, 0.886, 1
                Line:
                    points: [self.x, self.top, self.x + self.width, self.top]
                    width: 1
            padding: "6dp"
            spacing: "4dp"
            TabInferior:
                icono: app.icono("table-chair")
                texto: "Inicio"
                color_texto: app.CFG_TEXTO_GRIS
                on_release: app.go_to("inicio")
            TabInferior:
                icono: app.icono("ticket")
                texto: "Pedidos"
                color_texto: app.CFG_TEXTO_GRIS
                on_release: app.ir_activos()
            TabInferior:
                icono: app.icono("chart-bar")
                texto: "Estadisticas"
                color_texto: app.CFG_TEXTO_GRIS
                on_release: app.ir_estadisticas()
            TabInferior:
                icono: app.icono("cog")
                texto: "Config"
                color_texto: app.DORADO
                on_release: app.ir_config()


# ══════ ESTADISTICAS ══════════════════════════════════════════════════════════
<PantallaEstadisticas>:
    name: "estadisticas"
    BoxLayout:
        orientation: "vertical"
        canvas.before:
            Color:
                rgba: app.NEGRO
            Rectangle:
                pos: self.pos
                size: self.size

        # Header
        BoxLayout:
            size_hint_y: None
            height: "52dp"
            canvas.before:
                Color:
                    rgba: app.OSCURO
                Rectangle:
                    pos: self.pos
                    size: self.size
            padding: "12dp", "8dp"
            Label:
                text: "[b]ESTADISTICAS[/b]"
                markup: True
                color: app.texto_contraste(app.OSCURO)
                font_size: "18sp"
                halign: "left"
                text_size: self.size

        # Botones de periodo
        ScrollView:
            size_hint_y: None
            height: "46dp"
            do_scroll_y: False
            BoxLayout:
                orientation: "horizontal"
                size_hint_x: None
                width: "560dp"
                spacing: "4dp"
                padding: "6dp", "4dp"
                Button:
                    text: "Hoy"
                    background_color: [0,0,0,0]
                    color: app.texto_contraste(app.ROJO)
                    size_hint_x: None
                    width: "68dp"
                    font_size: "12sp"
                    on_press: app._cambiar_periodo_est("hoy", self)
                    canvas.before:
                        Color:
                            rgba: app.ROJO
                        RoundedRectangle:
                            pos: self.pos
                            size: self.size
                            radius: [dp(12)]
                Button:
                    text: "Semana"
                    background_color: [0,0,0,0]
                    color: app.texto_contraste(app.OSCURO)
                    size_hint_x: None
                    width: "70dp"
                    font_size: "12sp"
                    on_press: app._cambiar_periodo_est("semana", self)
                    canvas.before:
                        Color:
                            rgba: app.OSCURO
                        RoundedRectangle:
                            pos: self.pos
                            size: self.size
                            radius: [dp(12)]
                Button:
                    text: "Mes"
                    background_color: [0,0,0,0]
                    color: app.texto_contraste(app.OSCURO)
                    size_hint_x: None
                    width: "55dp"
                    font_size: "12sp"
                    on_press: app._cambiar_periodo_est("mes", self)
                    canvas.before:
                        Color:
                            rgba: app.OSCURO
                        RoundedRectangle:
                            pos: self.pos
                            size: self.size
                            radius: [dp(12)]
                Button:
                    text: "3 Meses"
                    background_color: [0,0,0,0]
                    color: app.texto_contraste(app.OSCURO)
                    size_hint_x: None
                    width: "75dp"
                    font_size: "12sp"
                    on_press: app._cambiar_periodo_est("3meses", self)
                    canvas.before:
                        Color:
                            rgba: app.OSCURO
                        RoundedRectangle:
                            pos: self.pos
                            size: self.size
                            radius: [dp(12)]
                Button:
                    text: "6 Meses"
                    background_color: [0,0,0,0]
                    color: app.texto_contraste(app.OSCURO)
                    size_hint_x: None
                    width: "75dp"
                    font_size: "12sp"
                    on_press: app._cambiar_periodo_est("6meses", self)
                    canvas.before:
                        Color:
                            rgba: app.OSCURO
                        RoundedRectangle:
                            pos: self.pos
                            size: self.size
                            radius: [dp(12)]
                Button:
                    text: "1 Año"
                    background_color: [0,0,0,0]
                    color: app.texto_contraste(app.OSCURO)
                    size_hint_x: None
                    width: "60dp"
                    font_size: "12sp"
                    on_press: app._cambiar_periodo_est("anio", self)
                    canvas.before:
                        Color:
                            rgba: app.OSCURO
                        RoundedRectangle:
                            pos: self.pos
                            size: self.size
                            radius: [dp(12)]
                Button:
                    id: est_lbl_periodo
                    text: "FECHA..."
                    background_color: [0,0,0,0]
                    color: app.texto_contraste(app.ACCENT)
                    size_hint_x: None
                    width: "80dp"
                    font_size: "11sp"
                    on_press: app._abrir_calendario()
                    canvas.before:
                        Color:
                            rgba: app.ACCENT
                        RoundedRectangle:
                            pos: self.pos
                            size: self.size
                            radius: [dp(12)]


        # Cuerpo scrollable con resultados
        ScrollView:
            BoxLayout:
                id: est_cuerpo
                orientation: "vertical"
                spacing: "6dp"
                padding: "12dp", "8dp"
                size_hint_y: None
                height: self.minimum_height

        # Nav inferior
        BoxLayout:
            size_hint_y: None
            height: "60dp"
            canvas.before:
                Color:
                    rgba: app.OSCURO
                Rectangle:
                    pos: self.pos
                    size: self.size
            padding: "6dp"
            spacing: "4dp"
            TabInferior:
                icono: app.icono("table-chair")
                texto: "Inicio"
                color_texto: app.texto_contraste(app.OSCURO)
                on_release: app.go_to("inicio")
            TabInferior:
                icono: app.icono("ticket")
                texto: "Pedidos"
                color_texto: app.texto_contraste(app.OSCURO)
                on_release: app.ir_activos()
            TabInferior:
                icono: app.icono("chart-bar")
                texto: "Estadisticas"
                color_texto: app.DORADO
                on_release: app.ir_estadisticas()
            TabInferior:
                icono: app.icono("cog")
                texto: "Config"
                color_texto: app.texto_contraste(app.OSCURO)
                on_release: app.ir_config()

<PantallaBienvenida>:
    name: "bienvenida"
    BoxLayout:
        orientation: "vertical"
        canvas.before:
            Color:
                rgba: app.NEGRO
            Rectangle:
                pos: self.pos
                size: self.size
        padding: "28dp"
        spacing: "16dp"

        Widget:
            size_hint_y: 0.15

        Label:
            text: "[b]BIENVENIDO[/b]"
            markup: True
            color: app.texto_contraste(app.NEGRO)
            font_size: "22sp"
            size_hint_y: None
            height: "36dp"

        Label:
            text: "Configura tu negocio antes de empezar.\\nEsto solo se pide una vez."
            color: app.texto_contraste(app.NEGRO)
            font_size: "13sp"
            halign: "center"
            text_size: self.width, None
            size_hint_y: None
            height: "50dp"

        Widget:
            size_hint_y: 0.05

        Label:
            text: "Nombre de la empresa"
            color: app.texto_contraste(app.NEGRO)
            font_size: "13sp"
            halign: "left"
            text_size: self.size
            size_hint_y: None
            height: "20dp"

        TextInput:
            id: campo_bienv_nombre
            hint_text: "Ej. Taqueria La Birria"
            multiline: False
            background_color: app.SUPERFICIE_FIJA_OSCURA
            foreground_color: app.texto_contraste(app.SUPERFICIE_FIJA_OSCURA)
            hint_text_color: [0.5, 0.5, 0.5, 1]
            cursor_color: app.DORADO
            padding: "10dp", "12dp"
            size_hint_y: None
            height: "46dp"

        Label:
            text: "Contraseña de administrador"
            color: app.texto_contraste(app.NEGRO)
            font_size: "13sp"
            halign: "left"
            text_size: self.size
            size_hint_y: None
            height: "20dp"

        TextInput:
            id: campo_bienv_pass1
            hint_text: "Minimo 4 caracteres"
            password: True
            multiline: False
            background_color: app.SUPERFICIE_FIJA_OSCURA
            foreground_color: app.texto_contraste(app.SUPERFICIE_FIJA_OSCURA)
            hint_text_color: [0.5, 0.5, 0.5, 1]
            cursor_color: app.DORADO
            padding: "10dp", "12dp"
            size_hint_y: None
            height: "46dp"

        TextInput:
            id: campo_bienv_pass2
            hint_text: "Confirmar contraseña"
            password: True
            multiline: False
            background_color: app.SUPERFICIE_FIJA_OSCURA
            foreground_color: app.texto_contraste(app.SUPERFICIE_FIJA_OSCURA)
            hint_text_color: [0.5, 0.5, 0.5, 1]
            cursor_color: app.DORADO
            padding: "10dp", "12dp"
            size_hint_y: None
            height: "46dp"

        Widget:
            size_hint_y: 0.05

        Button:
            text: "Comenzar"
            size_hint_y: None
            height: "50dp"
            background_color: [0, 0, 0, 0]
            color: app.texto_contraste(app.ROJO)
            on_press: app.finalizar_config_inicial(campo_bienv_nombre.text, campo_bienv_pass1.text, campo_bienv_pass2.text)
            canvas.before:
                Color:
                    rgba: app.ROJO
                RoundedRectangle:
                    pos: self.pos
                    size: self.size
                    radius: [dp(16)]
            canvas.after:
                Color:
                    rgba: (app.texto_contraste(app.ROJO)[:3] + [0.16]) if self.state == "down" else (0, 0, 0, 0)
                RoundedRectangle:
                    pos: self.pos
                    size: self.size
                    radius: [dp(16)]

        Widget:
            size_hint_y: 0.3
"""

# ─── Screens ──────────────────────────────────────────────────────────────────
class PantallaInicio(Screen):
    pass


class PantallaOrden(Screen):
    """El encadenamiento de los campos de domicilio (nombre/telefono/
    direccion) se maneja en TaqueriaApp.iniciar_orden(), porque ese metodo
    ya sabe exactamente cuando el usuario empieza un pedido nuevo y necesita
    el foco. Aqui solo declaramos la bandera de control."""
    _campos_encadenados = False


class PantallaActivos(Screen):
    pass


class PantallaConfig(Screen):
    """El encadenamiento de sus campos (nueva categoria / nuevo producto)
    se hace en TaqueriaApp._abrir_config_real(), que ya se ejecuta una sola
    vez por sesion (bandera _campos_encadenados) justo antes de mostrar
    esta pantalla — momento en el que sus ids ya estan garantizados."""
    _campos_encadenados = False


class PantallaEstadisticas(Screen):
    pass


class PantallaBienvenida(Screen):
    """Solo se muestra una vez: la primera vez que se abre la app, antes
    de que exista un nombre de empresa/contraseña configurados."""
    pass


# ─── App ──────────────────────────────────────────────────────────────────────
# ── Conexión Bluetooth robusta para impresora térmica (Android 12+) ─────────
# Vive en este archivo (main.py) porque es quien ya maneja Kivy/KivyMD y la
# configuracion persistida (self._leer_config / self._guardar_config). El
# resto de la app (servidor_mesas.py, botones de la UI) solo llama a los
# metodos publicos de TaqueriaApp (imprimir_comanda_cocina, etc.) -- nunca
# tocan el socket Bluetooth directamente.
class _EstadoImpresoraBT:
    DESCONECTADA = "desconectada"
    CONECTANDO   = "conectando"
    CONECTADA    = "conectada"
    ERROR        = "error"


class ImpresoraBluetoothManager:
    """
    Maneja la conexión SPP (RFCOMM) con la impresora térmica.
    - iniciar_vigilancia(): al abrir la app, si hay MAC guardada, conecta
      en un daemon thread de fondo sin bloquear el arranque; si falla,
      reintenta en silencio cada 'intervalo_seg' (10s por default). Si NO
      hay MAC guardada, no hace absolutamente nada.
    - enviar()/abrir_cajon(): NO escriben directo -- encolan el trabajo
      en una cola FIFO (self._cola_impresion) que un unico hilo
      trabajador consume en orden de llegada. Esto evita 2 problemas
      cuando llegan varios pedidos casi al mismo tiempo (ej. 3+ meseros
      mandando comanda juntos):
        1) Orden: sin cola, cada enviar() lanzaba su propio hilo y el SO
           no garantizaba que el primer pedido en llegar fuera el primero
           en imprimirse. Con un unico consumidor FIFO, el orden de
           impresion es siempre el orden de llegada.
        2) Buffer fisico: las impresoras termicas SPP baratas no tienen
           control de flujo ni avisan "ocupado". Si el segundo ticket
           llega mientras la primera todavia esta cortando el papel del
           anterior, se pueden perder lineas o cortar a destiempo. Por
           eso el trabajador espera PAUSA_ENTRE_TRABAJOS_SEG entre cada
           trabajo antes de sacar el siguiente de la cola.
    - verificar_conexion(): chequeo barato del socket (isConnected() de
      Android SOLO confirma que connect() tuvo exito alguna vez -- NO
      detecta en tiempo real que la impresora se apago o salio de rango;
      esa deteccion real ocurre recien cuando el write() falla). Se usa
      como filtro rapido, no como prueba de vida definitiva.
    - Todo el trabajo de red corre en threading.Thread; la UI de Kivy
      nunca se bloquea. Los callbacks siempre regresan vía Clock.
    """
    SPP_UUID                    = "00001101-0000-1000-8000-00805F9B34FB"
    MAX_REINTENTOS              = 3
    ESPERA_REINTENTO_SEG        = 2    # backoff simple: 2s, 4s, 6s
    PAUSA_ENTRE_TRABAJOS_SEG    = 1.5  # margen para que la termica termine de imprimir+cortar
    # ^ Ajustar si con rafagas de 3+ pedidos siguen apareciendo tickets con
    #   lineas faltantes o cortes a destiempo -- subir a 2.0-2.5s en
    #   impresoras de 58mm mas lentas.

    def __init__(self, app):
        self.app                        = app  # referencia a TaqueriaApp
        self._socket                    = None
        self._mac_actual                = None
        self._estado                    = _EstadoImpresoraBT.DESCONECTADA
        self._lock                      = threading.RLock()  # evita 2 conexiones a la vez
        # RLock (no Lock normal) porque el trabajador toma el lock para
        # TODO el tramo conexion+escritura, y dentro de ese tramo puede
        # llamar a _conectar_con_reintentos(), que vuelve a pedir el
        # mismo lock -- con un Lock normal eso seria un deadlock (el
        # mismo hilo esperando a si mismo). RLock permite que el MISMO
        # hilo lo reajuste varias veces; otros hilos (por ejemplo la
        # vigilancia de fondo) siguen bloqueados igual que con un Lock
        # normal hasta que se libere.
        self._hilo_vigilancia           = None
        self._detener_vigilancia_flag   = None
        self._cola_impresion            = queue.Queue()
        self._hilo_trabajador           = None

    # ---------- bajo nivel ----------
    def _obtener_adaptador(self):
        from jnius import autoclass
        BluetoothAdapter = autoclass('android.bluetooth.BluetoothAdapter')
        adaptador = BluetoothAdapter.getDefaultAdapter()
        if adaptador is None:
            raise RuntimeError("Este equipo no tiene Bluetooth")
        if not adaptador.isEnabled():
            raise RuntimeError("El Bluetooth esta apagado")
        return adaptador

    def _abrir_socket(self, mac):
        from jnius import autoclass
        UUID = autoclass('java.util.UUID')
        adaptador = self._obtener_adaptador()
        dispositivo = adaptador.getRemoteDevice(mac)
        socket = dispositivo.createRfcommSocketToServiceRecord(UUID.fromString(self.SPP_UUID))
        adaptador.cancelDiscovery()
        try:
            socket.connect()  # bloqueante -- el propio SO le pone timeout (~12s)
        except Exception:
            # Si connect() falla, el objeto Java ya reservo un fd/canal
            # RFCOMM a nivel de SO que jamas llega a asignarse a
            # self._socket -- sin este close() explicito, cada intento
            # fallido (y con MAX_REINTENTOS=3 + vigilancia cada 10s, son
            # muchos con la impresora apagada) deja un socket nativo
            # huerfano sin cerrar.
            try:
                socket.close()
            except Exception:
                pass
            raise
        return socket

    def _cerrar_socket_silencioso(self):
        if self._socket is not None:
            try:
                self._socket.close()
            except Exception:
                pass
        self._socket = None

    # ---------- estado / verificación ----------
    def esta_conectada(self):
        """Chequeo barato del ultimo estado conocido (no toca el socket)."""
        with self._lock:
            return self._estado == _EstadoImpresoraBT.CONECTADA and self._socket is not None

    def verificar_conexion(self):
        """Chequeo RAPIDO pero NO definitivo: isConnected() en Android solo
        confirma que connect() tuvo exito alguna vez, no detecta en tiempo
        real que la impresora se apago o salio de rango -- esa deteccion
        real ocurre cuando el write() falla (ver el trabajador de la cola).
        Se usa como filtro barato antes de intentar escribir.
        Rapido pero bloqueante -- solo desde hilo, nunca desde el hilo de Kivy."""
        with self._lock:
            sock = self._socket
            if sock is None:
                return False
            try:
                vivo = bool(sock.isConnected())
                if not vivo:
                    self._estado = _EstadoImpresoraBT.DESCONECTADA
                    self._socket = None
                return vivo
            except Exception:
                self._estado = _EstadoImpresoraBT.ERROR
                self._socket = None
                return False

    # ---------- conexión directa con reintentos ----------
    def _conectar_con_reintentos(self, mac):
        with self._lock:
            self._estado = _EstadoImpresoraBT.CONECTANDO
            ultimo_error = None
            for intento in range(1, self.MAX_REINTENTOS + 1):
                try:
                    self._socket = self._abrir_socket(mac)
                    self._mac_actual = mac
                    self._estado = _EstadoImpresoraBT.CONECTADA
                    return
                except Exception as e:
                    ultimo_error = e
                    print(f"[ImpresoraBT] intento {intento}/{self.MAX_REINTENTOS} fallo: {e}")
                    self._cerrar_socket_silencioso()
                    if intento < self.MAX_REINTENTOS:
                        time.sleep(self.ESPERA_REINTENTO_SEG * intento)
            self._estado = _EstadoImpresoraBT.ERROR
            raise RuntimeError(f"Impresora no disponible tras {self.MAX_REINTENTOS} intentos: {ultimo_error}")

    def desconectar(self):
        self._cerrar_socket_silencioso()
        self._estado = _EstadoImpresoraBT.DESCONECTADA

    # ---------- vigilancia de fondo (arranque de la app) ----------
    def iniciar_vigilancia(self, intervalo_seg=10):
        """Se llama UNA vez, al abrir la app (build()) o justo despues de
        vincular una impresora nueva.
        - Si NO hay MAC guardada: no hace nada, no lanza hilos ni errores
          -- solo espera a que el usuario configure la impresora.
        - Si SI hay MAC: lanza un daemon thread que intenta conectar en
          segundo plano sin congelar el arranque, y si falla o se pierde
          la señal despues, reintenta cada 'intervalo_seg' en silencio
          (sin snackbars, sin popups) hasta que la impresora responda o
          la app se cierre (el thread es daemon, muere solo con la app)."""
        mac_guardada = self.app._leer_config("impresora_bt_mac", "")
        if not mac_guardada:
            return  # sin impresora configurada -- no hay nada que vigilar
        if self._hilo_vigilancia is not None:
            return  # ya hay una vigilancia corriendo, no duplicar

        self._detener_vigilancia_flag = threading.Event()

        def _bucle():
            while not self._detener_vigilancia_flag.is_set():
                mac_actual = self.app._leer_config("impresora_bt_mac", "")
                if not mac_actual:
                    return  # el usuario desvinculo la impresora -- parar
                try:
                    if self.esta_conectada() and self.verificar_conexion():
                        pass  # sigue viva, nada que hacer este ciclo
                    else:
                        self._conectar_con_reintentos(mac_actual)
                except Exception as e:
                    print("[ImpresoraBT] vigilancia: sigue sin poder conectar:", e)
                self._detener_vigilancia_flag.wait(intervalo_seg)

        self._hilo_vigilancia = threading.Thread(target=_bucle, daemon=True)
        self._hilo_vigilancia.start()

    def detener_vigilancia(self):
        if self._detener_vigilancia_flag is not None:
            self._detener_vigilancia_flag.set()
        self._hilo_vigilancia = None

    # ---------- escaneo de equipos cercanos (fallback, no prioritario) ------
    def escanear_cercanos(self, callback_dispositivo, callback_fin, segundos=8):
        """Descubre equipos Bluetooth NUEVOS (no solo emparejados). Requiere
        permiso BLUETOOTH_SCAN. Se usa solo cuando el usuario pide "Buscar
        impresora nueva" en el selector. No bloquea la UI: usa
        BroadcastReceiver + Clock, la ventana de escaneo se corta sola."""
        from jnius import autoclass
        from android.broadcast import BroadcastReceiver

        BluetoothDevice = autoclass('android.bluetooth.BluetoothDevice')
        adaptador = self._obtener_adaptador()
        encontrados = set()

        def _on_broadcast(context, intent):
            if intent.getAction() == BluetoothDevice.ACTION_FOUND:
                dispositivo = intent.getParcelableExtra(BluetoothDevice.EXTRA_DEVICE)
                mac = dispositivo.getAddress()
                if mac not in encontrados:
                    encontrados.add(mac)
                    nombre = dispositivo.getName() or "Desconocido"
                    Clock.schedule_once(lambda dt: callback_dispositivo(nombre, mac))

        receptor = BroadcastReceiver(_on_broadcast, actions=['android.bluetooth.device.action.FOUND'])
        receptor.start()
        adaptador.startDiscovery()

        def _detener(dt):
            try: adaptador.cancelDiscovery()
            except Exception: pass
            try: receptor.stop()
            except Exception: pass
            callback_fin()

        Clock.schedule_once(_detener, segundos)

    def listar_emparejados(self):
        """[(nombre, mac), ...] -- solo los YA vinculados en Ajustes de
        Android. No requiere BLUETOOTH_SCAN, solo BLUETOOTH_CONNECT."""
        adaptador = self._obtener_adaptador()
        return [(d.getName() or "Desconocido", d.getAddress())
                for d in adaptador.getBondedDevices().toArray()]

    # ---------- API principal ----------
    def _iniciar_trabajador(self):
        """Arranca (una sola vez) el hilo consumidor de la cola de
        impresion. Se llama de forma perezosa desde enviar(), asi no hace
        falta tocar iniciar_vigilancia() ni el arranque de la app.

        Por que una cola con UN solo consumidor y no un hilo por pedido
        (como antes): con 3+ meseros mandando pedidos casi al mismo
        tiempo, lanzar un threading.Thread por cada enviar() no
        garantiza que el primero en llegar sea el primero en imprimirse
        (el SO decide el orden de los hilos), y en cuanto uno soltaba el
        lock el siguiente ya podia escribir aunque la impresora todavia
        estuviera fisicamente cortando el ticket anterior -- las
        impresoras termicas SPP baratas no tienen control de flujo ni
        avisan "ocupado", asi que eso puede perder lineas o cortar a
        destiempo. Con un unico trabajador FIFO + pausa entre trabajos,
        ambos problemas quedan resueltos."""
        if self._hilo_trabajador is not None:
            return

        def _bucle_trabajador():
            while True:
                datos_bytes, callback_ok, callback_error = self._cola_impresion.get()
                try:
                    mac = self.app._leer_config("impresora_bt_mac", "")
                    if not mac:
                        if callback_error:
                            Clock.schedule_once(lambda dt: callback_error("Impresora no configurada"))
                        continue
                    try:
                        # Todo el tramo va bajo el mismo lock que usa
                        # _conectar_con_reintentos: asi, si justo en este
                        # momento la vigilancia de fondo (iniciar_vigilancia)
                        # detecta la conexion caida y quiere reconectar,
                        # tiene que ESPERAR a que esta escritura termine en
                        # vez de cerrar el socket a media impresion (la
                        # causa del ticket perdido silencioso).
                        with self._lock:
                            if not (self.esta_conectada() and self._mac_actual == mac
                                    and self.verificar_conexion()):
                                self._conectar_con_reintentos(mac)  # reconexion forzada

                            salida = self._socket.getOutputStream()
                            salida.write(datos_bytes)
                            salida.flush()
                        if callback_ok:
                            Clock.schedule_once(lambda dt: callback_ok())
                    except Exception as e:
                        self._estado = _EstadoImpresoraBT.ERROR
                        self._cerrar_socket_silencioso()
                        print("[ImpresoraBT] Error al imprimir:", e)
                        if callback_error:
                            Clock.schedule_once(lambda dt: callback_error("Impresora no disponible"))
                finally:
                    # Pausa SIEMPRE, haya salido bien o mal el trabajo --
                    # asi el siguiente ticket de la cola no le pisa el
                    # corte de papel al anterior. Si el trabajo fallo (p.
                    # ej. impresora apagada) la pausa tambien evita que
                    # los reintentos de 3+ pedidos en cola se disparen
                    # todos pegados uno tras otro.
                    time.sleep(self.PAUSA_ENTRE_TRABAJOS_SEG)
                    self._cola_impresion.task_done()

        self._hilo_trabajador = threading.Thread(target=_bucle_trabajador, daemon=True)
        self._hilo_trabajador.start()

    def enviar(self, datos_bytes, callback_ok=None, callback_error=None):
        """Punto de entrada para imprimir/abrir cajon. Ya NO escribe
        directo ni lanza un hilo por llamada: encola el trabajo en
        self._cola_impresion, que el unico hilo trabajador (ver
        _iniciar_trabajador) consume en orden FIFO, uno a la vez, con una
        pausa entre cada uno. Si nunca se configuro una impresora, el
        propio trabajador cancela en silencio -- ese aviso lo da la UI
        que llama a enviar(), no este modulo. Retorna de inmediato --
        jamas congela la interfaz."""
        self._iniciar_trabajador()
        self._cola_impresion.put((datos_bytes, callback_ok, callback_error))

    def abrir_cajon(self, callback_ok=None, callback_error=None):
        """Reusa exactamente la misma logica de cola de enviar()."""
        self.enviar(_ESC_ABRIR_CAJON, callback_ok=callback_ok, callback_error=callback_error)


# ── Conexión WiFi (Red Local) para impresora térmica ─────────────────────────
# Mismo espíritu que ImpresoraBluetoothManager: cola FIFO + un único hilo
# trabajador, para que el orden de impresión respete el orden de llegada y
# nunca se disparen sockets compitiendo entre sí. La diferencia clave es que
# AQUÍ la conexión es volátil (se abre y se cierra por cada ticket) en vez de
# persistente -- ver la docstring de enviar() para el porqué.
class _EstadoImpresoraWifi:
    OCIOSA    = "ociosa"
    ENVIANDO  = "enviando"
    ERROR     = "error"


class ImpresoraWifiManager:
    """
    Envía tickets ESC/POS a una impresora térmica en la red local vía TCP
    crudo al puerto 9100 (protocolo RAW/JetDirect -- el estándar de facto
    en impresoras térmicas WiFi de bajo costo; no requiere handshake ni
    autenticación, solo aceptan bytes crudos y los imprimen).

    - enviar()/abrir_cajon(): encolan el trabajo en self._cola_impresion;
      un único hilo trabajador (_iniciar_trabajador) lo consume en orden
      FIFO, uno a la vez, con pausa entre trabajos -- mismo patrón que
      ImpresoraBluetoothManager, por la misma razón: evitar que un ticket
      le pise el corte de papel al anterior cuando llegan 3+ pedidos casi
      juntos.
    - Conexión VOLÁTIL, no persistente: cada ticket abre su propio socket
      TCP, manda todo el buffer y lo cierra de inmediato. Ver enviar()
      para el razonamiento completo.
    - Todo el trabajo de red corre en threading.Thread; la UI de Kivy
      nunca se bloquea. Los callbacks siempre regresan vía Clock.
    """
    PUERTO                    = 9100
    TIMEOUT_CONEXION_SEG      = 5     # timeout de connect() -- nunca colgar el hilo
    TIMEOUT_ENVIO_SEG         = 8     # timeout del sendall() una vez conectado
    MAX_REINTENTOS            = 3
    ESPERA_REINTENTO_SEG      = 2     # backoff simple: 2s, 4s, 6s
    PAUSA_ENTRE_TRABAJOS_SEG  = 1.5   # margen para que la termica termine de imprimir+cortar

    def __init__(self, app):
        self.app               = app  # referencia a TaqueriaApp
        self._cola_impresion   = queue.Queue()
        self._hilo_trabajador  = None
        self._estado           = _EstadoImpresoraWifi.OCIOSA
        self._lock             = threading.RLock()  # protege self._estado entre hilos

    # ---------- bajo nivel ----------
    def _enviar_una_vez(self, ip, datos_bytes):
        """Abre conexion, manda TODO el buffer, cierra. Nunca deja el
        socket abierto mas tiempo del necesario.

        Por que conexion volatil y no persistente (Keep-Alive): la
        mayoria de impresoras termicas WiFi baratas corren un firmware
        RAW/JetDirect que solo acepta UNA conexion TCP a la vez en el
        puerto 9100. Si esta app mantuviera el socket abierto de forma
        continua, cualquier otro mesero (u otro dispositivo, como una
        segunda instancia de esta misma app) que intente imprimir se
        quedaria bloqueado hasta que el firmware de la impresora expire
        esa conexion por su cuenta -- algo que en varios modelos tarda
        varios minutos. Abriendo/cerrando por ticket, el puerto queda
        libre en cuanto termina cada impresion.

        socket.create_connection ya usa el timeout tanto para connect()
        como valor por defecto del socket resultante; igual se refuerza
        con settimeout() explicito para el sendall(), por si el timeout
        de envio quiere ser distinto al de conexion (aqui son distintos
        a proposito: conectar debe fallar rapido, pero el envio de un
        ticket largo con foto/logo puede tardar un poco mas)."""
        with socket.create_connection((ip, self.PUERTO), timeout=self.TIMEOUT_CONEXION_SEG) as sock:
            sock.settimeout(self.TIMEOUT_ENVIO_SEG)
            sock.sendall(datos_bytes)  # bloquea hasta que TODO el buffer sale del socket
            try:
                sock.shutdown(socket.SHUT_WR)  # avisa "no mando mas datos" antes de cerrar
            except OSError:
                pass  # algunas impresoras ya cerraron su lado -- no es fatal

    def _enviar_con_reintentos(self, ip, datos_bytes):
        """Reintentos acotados con backoff -- igual que
        _conectar_con_reintentos del modulo Bluetooth. Captura errores de
        red ESPECIFICOS (nunca Exception generico) para poder devolver un
        mensaje util segun la causa real."""
        ultimo_error = None
        for intento in range(1, self.MAX_REINTENTOS + 1):
            try:
                self._enviar_una_vez(ip, datos_bytes)
                return
            except socket.timeout:
                ultimo_error = f"La impresora en {ip} no respondio a tiempo"
            except ConnectionRefusedError:
                ultimo_error = f"La impresora en {ip} rechazo la conexion (apagada o puerto ocupado)"
            except (socket.gaierror, OSError) as e:
                # gaierror: IP/host invalido o sin DNS local.
                # OSError generico: red inaccesible (WiFi caido, subred
                # distinta, etc). Se captura junto porque ambos son fallas
                # de RED, a diferencia de un except Exception ciego que
                # tambien se tragaria bugs de logica (KeyError, TypeError...).
                ultimo_error = f"Red inaccesible para {ip}: {e}"
            print(f"[ImpresoraWifi] intento {intento}/{self.MAX_REINTENTOS} fallo: {ultimo_error}")
            if intento < self.MAX_REINTENTOS:
                time.sleep(self.ESPERA_REINTENTO_SEG * intento)
        raise RuntimeError(ultimo_error or "Impresora WiFi no disponible")

    # ---------- cola FIFO (mismo patron que ImpresoraBluetoothManager) -----
    def _iniciar_trabajador(self):
        """Un unico hilo consumidor: garantiza orden FIFO y una pausa
        entre trabajos para no saturar el buffer fisico de la impresora,
        exactamente por la misma razon que en el modulo Bluetooth."""
        if self._hilo_trabajador is not None:
            return

        def _bucle_trabajador():
            while True:
                ip, datos_bytes, callback_ok, callback_error = self._cola_impresion.get()
                try:
                    if not ip:
                        if callback_error:
                            Clock.schedule_once(lambda dt: callback_error("Impresora WiFi sin IP configurada"))
                        continue
                    with self._lock:
                        self._estado = _EstadoImpresoraWifi.ENVIANDO
                    self._enviar_con_reintentos(ip, datos_bytes)
                    with self._lock:
                        self._estado = _EstadoImpresoraWifi.OCIOSA
                    if callback_ok:
                        Clock.schedule_once(lambda dt: callback_ok())
                except Exception as e:
                    with self._lock:
                        self._estado = _EstadoImpresoraWifi.ERROR
                    print("[ImpresoraWifi] Error al imprimir:", e)
                    if callback_error:
                        mensaje = str(e)
                        Clock.schedule_once(lambda dt: callback_error(mensaje))
                finally:
                    time.sleep(self.PAUSA_ENTRE_TRABAJOS_SEG)
                    self._cola_impresion.task_done()

        self._hilo_trabajador = threading.Thread(target=_bucle_trabajador, daemon=True)
        self._hilo_trabajador.start()

    # ---------- API principal ----------
    def enviar(self, ip, datos_bytes, callback_ok=None, callback_error=None):
        """Punto de entrada para imprimir/abrir cajon por WiFi. Encola el
        trabajo; el unico hilo trabajador conecta-envia-cierra en orden
        FIFO, uno a la vez. Retorna de inmediato -- jamas congela la
        interfaz, ni siquiera si el WiFi se cae en pleno intento."""
        self._iniciar_trabajador()
        self._cola_impresion.put((ip, datos_bytes, callback_ok, callback_error))

    def abrir_cajon(self, ip, callback_ok=None, callback_error=None):
        """Reusa exactamente la misma logica de cola de enviar()."""
        self.enviar(ip, _ESC_ABRIR_CAJON, callback_ok=callback_ok, callback_error=callback_error)

    def probar_conexion(self, ip, callback_ok=None, callback_error=None, timeout=3):
        """Prueba RAPIDA de conectividad para el boton 'Probar conexion'
        de Configuracion: solo abre y cierra el socket, sin mandar ningun
        byte -- asi la cajera puede validar la IP en el momento de
        configurarla, sin imprimir un ticket de prueba ni activar el
        cortador de papel por accidente. Corre en un hilo aparte, jamas
        bloquea la UI ni pasa por la cola de impresion (es independiente
        de enviar(), para no hacer esperar un ticket real en cola detras
        de una prueba)."""
        def _trabajo():
            try:
                with socket.create_connection((ip, self.PUERTO), timeout=timeout):
                    pass
                if callback_ok:
                    Clock.schedule_once(lambda dt: callback_ok())
            except socket.timeout:
                if callback_error:
                    mensaje = f"Sin respuesta de {ip} (tiempo agotado)"
                    Clock.schedule_once(lambda dt: callback_error(mensaje))
            except ConnectionRefusedError:
                if callback_error:
                    mensaje = f"{ip} rechazo la conexion (revisa la IP o si esta prendida)"
                    Clock.schedule_once(lambda dt: callback_error(mensaje))
            except (socket.gaierror, OSError) as e:
                if callback_error:
                    mensaje = f"No se pudo conectar a {ip}: {e}"
                    Clock.schedule_once(lambda dt: callback_error(mensaje))
        threading.Thread(target=_trabajo, daemon=True).start()


class TaqueriaApp(MDApp):

    # Propiedades reactivas: al cambiar su valor, todo lo que las usa en el
    # KV (rgba: app.ROJO, etc.) se redibuja solo, sin tocar cada pantalla.
    # TEMAS es la UNICA fuente de sus valores (incluido el default inicial).
    ROJO   = ListProperty(TEMAS["Oscuro clasico"]["ROJO"])
    DORADO = ListProperty(TEMAS["Oscuro clasico"]["DORADO"])
    NEGRO  = ListProperty(TEMAS["Oscuro clasico"]["NEGRO"])
    OSCURO = ListProperty(TEMAS["Oscuro clasico"]["OSCURO"])
    CREMA  = ListProperty(TEMAS["Oscuro clasico"]["CREMA"])
    ACCENT = ListProperty(TEMAS["Oscuro clasico"]["ACCENT"])

    # Constante fija (no reactiva al tema, por diseno): expuesta a la clase
    # para que el KV pueda leerla como app.SUPERFICIE_FIJA_OSCURA, con
    # SUPERFICIE_FIJA_OSCURA (modulo) como unica fuente de su valor.
    SUPERFICIE_FIJA_OSCURA = SUPERFICIE_FIJA_OSCURA

    # Paleta fija de Configuracion (ver comentario junto a su definicion,
    # mas arriba): expuesta a la clase para que el KV de <PantallaConfig>
    # ya no repita estos mismos numeros como literales sueltos.
    CFG_FONDO        = CFG_FONDO
    CFG_TARJETA      = CFG_TARJETA
    CFG_TEXTO        = CFG_TEXTO
    CFG_TEXTO_GRIS   = CFG_TEXTO_GRIS
    CFG_EMERALD      = CFG_EMERALD
    CFG_EMERALD_SOFT = CFG_EMERALD_SOFT
    CFG_ALERTA       = CFG_ALERTA
    CFG_ALERTA_SOFT  = CFG_ALERTA_SOFT
    CFG_CAMPO_BG     = CFG_CAMPO_BG
    CFG_HINT_GRIS    = CFG_HINT_GRIS

    tema_actual = StringProperty("Oscuro clasico")
    logo_path   = StringProperty("")

    # Pestaña activa dentro de Configuracion ("menu" | "operativa").
    # Antes toda la pantalla era un solo ScrollView gigante donde el
    # contenido se desbordaba sobre el nav inferior en pantallas chicas.
    # Ahora se reparte en dos sub-pantallas fijas (sin scroll de pagina)
    # controladas por este selector tipo "segmented control".
    config_tab = StringProperty("menu")

    nombre_taqueria = "[b]TAQUERIA LA BIRRIA[/b]"
    _password       = "1234"

    def texto_contraste(self, bg):
        """Expuesto a KV: color de texto (blanco o negro) mas legible sobre bg."""
        return _texto_contraste(bg)

    def verde_contraste(self, bg):
        """Expuesto a KV: verde de 'mesa libre' ajustado al contraste del
        tema activo (ver _verde_contraste)."""
        return _verde_contraste(bg)

    def icono(self, nombre_md_icon):
        """Expuesto a KV: arma el marcado [font=Icons]...[/font] para un
        icono de Material Design Icons (la fuente 'Icons' ya la registra
        KivyMD solo al importar kivymd.app, no hace falta registrarla a
        mano). Se usa como PREFIJO de texto en botones (ver <PantallaInicio>
        y la barra de navegacion inferior), en vez de emojis Unicode: los
        emojis modernos (fuera del rango BMP, ej. 💵🧾📊🪑🎟️) no tienen
        glifo en la fuente por defecto de Kivy y se ven como el cuadrito
        "tofu" -- los iconos de Material Design SI vienen incluidos con
        KivyMD y se ven bien en cualquier dispositivo. El widget que reciba
        este texto necesita "markup: True" para que el tag [font=...] se
        interprete en vez de mostrarse literal.
        Requiere que el widget al que se le ponga el texto soporte markup
        (Label, Button, y los botones "viejos" de KivyMD lo soportan)."""
        cp = md_icons.get(nombre_md_icon, "")
        if not cp:
            return ""
        return f"[font=Icons]{cp}[/font]"

    def _clamp_a_contenedor(self, widget, *_):
        """Expuesto a KV (on_size/on_pos). Fuerza a 'widget' a ocupar
        EXACTAMENTE el tamano y la posicion de su contenedor padre (un
        BoxLayout normal, no un boton de KivyMD).

        Motivo: los botones "viejos" de KivyMD (MDRectangleFlatButton,
        MDRaisedButton, etc.) no respetan size_hint_x -- se autoajustan al
        ancho de su propio texto/label internamente, por eso antes se
        salian del header en pantallas angostas. Como no podemos hacer que
        "respeten" size_hint_x, en vez de eso los metemos en un
        contenedor normal (que si reparte el ancho como cualquier
        BoxLayout de Kivy) y, cada vez que el boton intenta cambiar su
        propio tamano o posicion por su cuenta, este metodo lo regresa de
        inmediato al tamano/posicion de su contenedor. El resultado: el
        boton nunca puede salirse de la porcion de fila que le toca, sin
        importar que tan largo sea su texto.
        """
        contenedor = widget.parent
        if contenedor is None:
            return
        if list(widget.size) != list(contenedor.size):
            widget.size = contenedor.size
        if list(widget.pos) != list(contenedor.pos):
            widget.pos = contenedor.pos


    def _aplicar_paleta(self, nombre_tema):
        """Aplica los valores de color de un tema (sin refrescar pantallas ni guardar)."""
        t = TEMAS.get(nombre_tema)
        if not t:
            return False
        self.NEGRO  = t["NEGRO"]
        self.OSCURO = t["OSCURO"]
        self.CREMA  = t["CREMA"]
        self.ROJO   = t["ROJO"]
        self.DORADO = t["DORADO"]
        self.ACCENT = t["ACCENT"]
        self.tema_actual = nombre_tema
        return True

    def _actualizar_carpeta_errores(self, nombre):
        """Sanea el nombre, lo aplica de inmediato (para que el proximo
        crash ya caiga ahi), crea la carpeta nueva, migra TODO lo que la
        app crea (base de datos + log de errores) y actualiza el puntero
        fijo para que el proximo arranque en frio sepa donde buscar."""
        nombre_anterior = _CARPETA_ERRORES["nombre"]
        nombre = _sanear_nombre_carpeta(nombre)
        _CARPETA_ERRORES["nombre"] = nombre
        _escribir_puntero_carpeta(nombre)

        try:
            # self.user_data_dir en vez de "/storage/emulated/0/": misma
            # migracion de siempre (BD + log + logo), pero dentro de la
            # carpeta privada de la app, sin requerir permisos especiales.
            base = self.user_data_dir
            ruta_nueva = os.path.join(base, nombre)
            os.makedirs(ruta_nueva, exist_ok=True)

            if nombre != nombre_anterior:
                carpeta_vieja = os.path.join(base, nombre_anterior)
                for archivo in ("error_birria.txt", "ventas_birria.db"):
                    ruta_vieja = os.path.join(carpeta_vieja, archivo)
                    if os.path.exists(ruta_vieja):
                        shutil.move(ruta_vieja, os.path.join(ruta_nueva, archivo))
                # El logo tiene extension variable (logo.png, logo.jpg...),
                # asi que se busca por nombre base en vez de exacto.
                try:
                    for archivo in os.listdir(carpeta_vieja):
                        if archivo.lower().startswith("logo."):
                            ruta_vieja = os.path.join(carpeta_vieja, archivo)
                            ruta_dest  = os.path.join(ruta_nueva, archivo)
                            shutil.move(ruta_vieja, ruta_dest)
                            if self.logo_path == ruta_vieja:
                                self.logo_path = ruta_dest
                                self._guardar_config("logo_path", ruta_dest)
                except Exception:
                    pass
                try:
                    os.rmdir(carpeta_vieja)  # solo borra si quedo vacia; si tiene
                except OSError:              # algo mas adentro, la deja intacta
                    pass
        except Exception:
            pass

        return nombre

    # ── LOGO / IMAGEN DEL NEGOCIO ────────────────────────────────────────────
    _GALERIA_REQUEST_CODE = 9081

    def elegir_logo(self):
        """Abre la Galeria de Android para elegir una imagen de logo (puede
        ser un PNG sin fondo). Si la Galeria nativa no esta disponible en
        este entorno (por ejemplo dentro de Pydroid 3, que no siempre trae
        las clases de python-for-android), usa el selector de archivos de
        plyer, y si tampoco esta disponible, se ofrece escribir la ruta
        a mano."""
        if self._abrir_galeria_nativa():
            return
        try:
            from plyer import filechooser
            filechooser.open_file(
                on_selection=self._logo_seleccionado,
                mime_type="image/*",
                filters=[["Imagenes", "*.png", "*.jpg", "*.jpeg", "*.webp"]],
            )
        except Exception as e:
            print("Error abriendo selector de logo:", e)
            self._pedir_ruta_logo_manual()

    def _abrir_galeria_nativa(self):
        """Intenta abrir la app de Galeria de Android directamente, con
        ACTION_PICK sobre imagenes. Regresa True si logro lanzarla. Esto
        solo funciona cuando la app corre empaquetada como APK (con
        python-for-android); dentro de Pydroid 3 normalmente estas clases
        no existen y se regresa False para usar el siguiente metodo."""
        try:
            from jnius import autoclass
            from android import activity

            if not getattr(self, "_logo_activity_bind_hecho", False):
                activity.bind(on_activity_result=self._on_logo_activity_result)
                self._logo_activity_bind_hecho = True

            Intent    = autoclass("android.content.Intent")
            MediaImg  = autoclass("android.provider.MediaStore$Images$Media")
            PythonActivity = autoclass("org.kivy.android.PythonActivity")

            intent = Intent(Intent.ACTION_PICK, MediaImg.EXTERNAL_CONTENT_URI)
            intent.setType("image/*")
            PythonActivity.mActivity.startActivityForResult(
                intent, self._GALERIA_REQUEST_CODE
            )
            return True
        except Exception as e:
            print("Galeria nativa no disponible, uso selector alterno:", e)
            return False

    def _on_logo_activity_result(self, requestCode, resultCode, intent):
        """Recibe el resultado de la Galeria nativa (ver _abrir_galeria_nativa)."""
        if requestCode != self._GALERIA_REQUEST_CODE:
            return
        try:
            from jnius import autoclass
            Activity = autoclass("android.app.Activity")
            if resultCode != Activity.RESULT_OK or intent is None:
                return
            uri = intent.getData()
            if uri is None:
                return
            Clock.schedule_once(lambda dt: self._guardar_logo_desde_uri(uri), 0)
        except Exception as e:
            print("Error leyendo seleccion de galeria:", e)

    def _guardar_logo_desde_uri(self, uri):
        """Copia la imagen elegida en la Galeria (content://...) a la
        carpeta de datos de la app, leyendola con el ContentResolver de
        Android (funciona aunque el URI no tenga una ruta de archivo
        real, como pasa seguido en Android moderno)."""
        try:
            from jnius import autoclass
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            resolver = PythonActivity.mActivity.getContentResolver()

            mime = ""
            try:
                mime = resolver.getType(uri) or ""
            except Exception:
                pass
            if "jpeg" in mime or "jpg" in mime:
                ext = ".jpg"
            elif "webp" in mime:
                ext = ".webp"
            else:
                ext = ".png"

            carpeta = os.path.dirname(self._db_path())
            destino = os.path.join(carpeta, f"logo{ext}")

            stream_in = resolver.openInputStream(uri)
            datos = bytearray()
            buf = bytearray(8192)
            n = stream_in.read(buf)
            while n != -1:
                datos.extend(buf[:n])
                n = stream_in.read(buf)
            stream_in.close()

            with open(destino, "wb") as f_out:
                f_out.write(datos)

            self.logo_path = destino
            self._guardar_config("logo_path", destino)
            _snack("Logo actualizado")
        except Exception as e:
            print("Error guardando logo desde galeria:", e)
            _snack("No se pudo guardar la imagen de la galeria")

    def _logo_seleccionado(self, seleccion):
        """Callback del filechooser (puede llegar desde otro hilo)."""
        if not seleccion:
            return
        ruta = seleccion[0]
        Clock.schedule_once(lambda dt: self._guardar_logo(ruta), 0)

    def _pedir_ruta_logo_manual(self):
        """Popup de respaldo: escribir a mano la ruta del archivo de
        imagen, por si el selector nativo de archivos no esta disponible
        en este telefono/version de Pydroid."""
        content = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(12))
        content.add_widget(lbl(
            "No se pudo abrir el explorador de archivos.\n"
            "Escribe la ruta completa de la imagen:\n"
            "(ej. /storage/emulated/0/Pictures/logo.png)",
            color=self.texto_contraste(self.OSCURO), font_size="12sp",
            halign="center", size_hint_y=None, height=dp(66),
        ))
        campo = TextInput(hint_text="/storage/emulated/0/...", multiline=False,
                           size_hint_y=None, height=dp(44), font_size="13sp")
        content.add_widget(campo)

        popup_ref = [None]

        def _confirmar(*_):
            ruta = campo.text.strip()
            if popup_ref[0]:
                popup_ref[0].dismiss()
            if ruta:
                self._guardar_logo(ruta)

        b_ok = btn_raised("USAR ESTA IMAGEN", bg=self.ACCENT,
                          size_hint_y=None, height=dp(44))
        b_can = btn_flat("Cancelar", color=self.texto_contraste(self.OSCURO)[:3] + [0.6],
                         size_hint_y=None, height=dp(36))
        b_ok.bind(on_press=_confirmar)
        campo.bind(on_text_validate=_confirmar)

        content.add_widget(b_ok)
        content.add_widget(b_can)

        popup = Popup(title="Imagen del logo", separator_height=0,
                      content=content, size_hint=(0.86, None), height=dp(280),
                      background_color=self.OSCURO)
        popup_ref[0] = popup
        b_can.bind(on_press=lambda *_: popup.dismiss())
        popup.open()

    def _guardar_logo(self, ruta_origen):
        """Copia la imagen elegida a la carpeta de datos de la app (junto
        a la BD) y la deja lista para mostrarse como logo en la pantalla
        principal. Acepta PNG con transparencia."""
        try:
            if not ruta_origen or not os.path.isfile(ruta_origen):
                _snack("No se encontro esa imagen")
                return
            carpeta = os.path.dirname(self._db_path())
            ext = os.path.splitext(ruta_origen)[1].lower()
            if ext not in (".png", ".jpg", ".jpeg", ".webp"):
                ext = ".png"
            destino = os.path.join(carpeta, f"logo{ext}")
            shutil.copy(ruta_origen, destino)
            self.logo_path = destino
            self._guardar_config("logo_path", destino)
            _snack("Logo actualizado")
        except Exception as e:
            print("Error guardando logo:", e)
            _snack("No se pudo guardar la imagen")

    def quitar_logo(self):
        """Quita el logo actual; el titulo vuelve a mostrarse solo (sin
        imagen) en la pantalla principal."""
        self.logo_path = ""
        self._guardar_config("logo_path", "")
        _snack("Logo quitado")

    def finalizar_config_inicial(self, nombre, pass1, pass2):
        """Conectado al boton 'Comenzar' de la pantalla de bienvenida.
        Se ejecuta UNA sola vez en la vida de la app: valida los datos,
        los guarda, mueve la carpeta/BD al nombre elegido, y marca la
        bandera para que esta pantalla no vuelva a aparecer."""
        nombre = nombre.strip()
        if not nombre:
            _snack("Escribe el nombre de tu empresa")
            return
        if len(pass1) < 4:
            _snack("La contraseña debe tener al menos 4 caracteres")
            return
        if pass1 != pass2:
            _snack("Las contraseñas no coinciden")
            return

        self.nombre_taqueria = f"[b]{nombre}[/b]"
        self._guardar_config("nombre_taqueria", nombre)
        self._actualizar_carpeta_errores(nombre)

        self._password = pass1
        self._guardar_config("password", pass1)

        self._guardar_config("config_inicial_completa", "1")
        self._config_inicial_lista = True

        try:
            sc = self.root.get_screen("inicio")
            sc.ids.lbl_nombre_taqueria.text = self.nombre_taqueria
        except Exception:
            pass

        self.screen_history = ["inicio"]
        self.root.current = "inicio"
        _snack(f"Todo listo, bienvenido a {nombre}")

    def aplicar_tema(self, nombre_tema):
        """Cambia toda la paleta de colores de la app en vivo y lo guarda
        para que quede aplicado la proxima vez que se abra la app."""
        if not self._aplicar_paleta(nombre_tema):
            return
        # Las tarjetas de mesa cacheadas (ver refrescar_mesas) tienen los
        # colores del tema anterior "horneados" en su instruccion de
        # Color -- si no se invalida el cache aqui, una mesa que no
        # cambio de ocupada/libre se quedaria con el color viejo tras
        # cambiar de tema.
        self._tarjetas_mesa = {}
        self._refrescar_todas_pantallas()
        self._guardar_config("tema", nombre_tema)
        _snack(f"Tema aplicado: {nombre_tema}")

    def _refrescar_estadisticas_actual(self):
        """Recarga la pantalla de estadisticas con el periodo que ya estaba
        seleccionado, para que solo cambien los colores, no el filtro."""
        try:
            self._cargar_estadisticas(getattr(self, "_periodo_est_actual", "hoy"))
        except Exception:
            pass

    def _refrescar_todas_pantallas(self):
        """Reconstruye las pantallas dinamicas para que tomen el tema nuevo
        sin tener que salir y volver a entrar manualmente."""
        for metodo in ("refrescar_mesas", "_rebuild_tabs",
                       "_rebuild_productos", "refrescar_lista_activos",
                       "_rebuild_prods_cfg", "refrescar_cats_cfg",
                       "_rebuild_mesas_cfg", "_refrescar_estadisticas_actual"):
            fn = getattr(self, metodo, None)
            if callable(fn):
                try:
                    fn()
                except Exception:
                    pass

    def build(self):
        from kivy.core.window import Window
        # "below_target" es consciente de que widget tiene el foco: solo
        # redimensiona la ventana lo necesario para dejarlo visible justo
        # arriba del teclado. "pan" desplaza TODA la ventana por el alto
        # completo del teclado sin importar donde este el campo, lo que en
        # formularios con campos cerca del borde superior (como el de
        # domicilio) los empuja fuera de la pantalla. El salto de foco
        # entre campos encadenados ya no depende de esto: lo resuelve el
        # Clock.schedule_once dentro de encadenar_campos().
        Window.softinput_mode = "below_target"
        Window.bind(on_keyboard=self.on_back_button)
        self.theme_cls.theme_style = "Dark"
        self.theme_cls.primary_palette = "Red"

        self.pedidos             = []
        self.orden_actual        = []
        self.tipo_orden          = None
        self.mesa_sel            = None
        self.cat_cfg             = None
        self.filtro              = "todos"
        # nombre_viejo -> (nombre_nuevo, timestamp) por cada vez que la
        # cajera usa CAMBIAR MESA en un pedido ya guardado (ver
        # _mover_pedido_a_mesa). Sirve para que servidor_mesas.py pueda
        # redirigir sola una comanda que un mesero manda todavia a la
        # mesa vieja (por ejemplo si ya tenia esa pantalla abierta antes
        # del cambio), en vez de crear un pedido fantasma duplicado en
        # esa mesa. Se limpia sola: una entrada solo importa mientras la
        # mesa vieja siga libre (ver _resolver_mesa_movida).
        self._mesas_movidas      = {}
        self._dialog             = None

        # _init_db() debe correr ANTES de cualquier lectura/escritura de
        # configuracion -- incluida self._impresora_bt.iniciar_vigilancia()
        # un poco mas abajo, que lee "impresora_bt_mac" via self._leer_
        # config() -> self.db.leer_config(). Antes de la refactorizacion a
        # database.py esto no importaba (cada _leer_config abria su propia
        # conexion cruda con sqlite3.connect(), sin depender de "self.db").
        # Ahora que _leer_config/_guardar_config delegan en self.db
        # (instancia de BaseDatos), si _init_db() no ha corrido todavia
        # cuando algo intenta leer config, revienta con "AttributeError:
        # 'TaqueriaApp' object has no attribute 'db'" -- justo el crash
        # reportado, que salia ANTES de llegar al menu porque pasaba aqui
        # mismo, al inicio de build().
        self._init_db()

        # Manager de impresora Bluetooth: conecta solo si ya hay una MAC
        # guardada de una vinculacion manual previa; si no hay, no hace
        # nada (ver ImpresoraBluetoothManager.iniciar_vigilancia).
        self._impresora_bt       = ImpresoraBluetoothManager(self)
        self._impresora_bt.iniciar_vigilancia()
        # Manager de impresora WiFi: no necesita "vigilancia" -- al ser
        # conexion volatil (abre/envia/cierra por ticket, ver
        # ImpresoraWifiManager.enviar), no hay nada que mantener vivo en
        # segundo plano; solo se activa cuando enviar() se llama.
        self._impresora_wifi     = ImpresoraWifiManager(self)
        self._pedido_editando_id = None
        self._periodo_est_actual = "hoy"

        # Menu y mesas: se cargan desde la BD (tabla config, claves "menu"
        # y "mesas", guardadas como JSON). Si es la primera vez que corre
        # la app en este dispositivo (o la BD esta vacia/corrupta), se usa
        # el menu/mesas de fabrica y se guarda de una vez para que la
        # siguiente lectura ya encuentre algo valido.
        self.menu   = self._cargar_menu()
        self.mesas  = self._cargar_mesas()
        self.cat_activa = list(self.menu.keys())[0]

        # Info del negocio para tickets (direccion, datos bancarios,
        # mensaje de agradecimiento). Ver INFO_NEGOCIO_DEFAULT arriba y
        # _cargar_info_negocio() abajo -- todos los campos opcionales.
        self.info_negocio = self._cargar_info_negocio()

        # Cargar el tema guardado (si el usuario cambio uno antes de cerrar
        # la app la ultima vez) antes de construir la interfaz, para que
        # abra directamente con esos colores.
        tema_guardado = self._leer_config("tema", "Oscuro clasico")
        self._aplicar_paleta(tema_guardado)

        # Igual que el tema: si el usuario ya puso un nombre de taqueria
        # antes (Configuracion > Personal), la carpeta de errores debe
        # usarlo desde este arranque, y el label de inicio tambien.
        nombre_guardado = self._leer_config("nombre_taqueria", "TAQUERIA LA BIRRIA")
        self.nombre_taqueria = f"[b]{nombre_guardado}[/b]"
        self._actualizar_carpeta_errores(nombre_guardado)

        # La contraseña vivia solo en memoria (se reseteaba a "1234" en
        # cada arranque). Ahora se persiste igual que el resto de la config.
        self._password = self._leer_config("password", "1234")

        # Empleados (mesero/a): lista de {"nombre":..., "password":...}.
        # Se usan para saber quien atiende cada mesa (reflejado en la
        # tarjeta de la mesa y en el ticket) y para pedir clave en la
        # pagina web de meseros (servidor_mesas.py).
        try:
            self.empleados = json.loads(self._leer_config("empleados", "[]"))
        except Exception:
            self.empleados = []
        self._empleado_sel = None

        # Logo del negocio (si el usuario ya eligio uno antes).
        logo_guardado = self._leer_config("logo_path", "")
        if logo_guardado and os.path.isfile(logo_guardado):
            self.logo_path = logo_guardado
        else:
            self.logo_path = ""

        # Pantalla de bienvenida: solo la primera vez que se abre la app
        # (todavia no existe la bandera config_inicial_completa en la BD).
        self._config_inicial_lista = self._leer_config("config_inicial_completa", "0") == "1"
        pantalla_inicial = "inicio" if self._config_inicial_lista else "bienvenida"
        self.screen_history = [pantalla_inicial]

        _checkpoint("build(): a punto de parsear el KV (Builder.load_string)")
        Builder.load_string(KV)
        _checkpoint("build(): KV parseado sin problema (las clases MD ya existen)")
        # NoTransition en vez del SlideTransition por defecto: la
        # animacion de deslizamiento renderiza las DOS pantallas a la vez
        # durante ~0.2s en cada cambio (go_to() se llama muy seguido:
        # entrar a una mesa, volver, abrir config, etc.), lo que se nota
        # como micro-cortes en celulares de gama baja. Sin transicion el
        # cambio es instantaneo y mucho mas fluido -- el costo es solo
        # estetico (se pierde el deslizamiento), no funcional.
        sm = ScreenManager(transition=NoTransition())
        sm.add_widget(PantallaBienvenida(name="bienvenida"))
        _checkpoint("build(): PantallaBienvenida instanciada")
        sm.add_widget(PantallaInicio(name="inicio"))
        _checkpoint("build(): PantallaInicio instanciada (aqui vive el Dashboard nuevo)")
        sm.add_widget(PantallaOrden(name="orden"))
        sm.add_widget(PantallaActivos(name="activos"))
        sm.add_widget(PantallaConfig(name="config"))
        sm.add_widget(PantallaEstadisticas(name="estadisticas"))
        sm.current = pantalla_inicial
        _checkpoint("build(): terminado, entrando al mainloop")

        def _checkpoint_primer_frame(*_):
            _checkpoint("Window: primer frame dibujado (la UI SI se mostro)")
            Window.unbind(on_draw=_checkpoint_primer_frame)
        Window.bind(on_draw=_checkpoint_primer_frame)

        # Reloj en tiempo real (fecha + hora) en la tarjeta DOMICILIO/HOY
        # del dashboard. Se actualiza cada segundo via Clock.schedule_
        # interval -- no depende de refrescar_stats() ni de ningun otro
        # evento porque debe seguir avanzando aunque no entren pedidos.
        Clock.schedule_once(self._actualizar_reloj_dashboard, 0)
        Clock.schedule_interval(self._actualizar_reloj_dashboard, 1)

        return sm

    def on_start(self):
        _checkpoint("on_start: inicio")
        self._solicitar_permisos_inicio()
        _checkpoint("on_start: paso _solicitar_permisos_inicio")
        self._mantener_app_viva()
        _checkpoint("on_start: paso _mantener_app_viva")
        self.refrescar_mesas()
        _checkpoint("on_start: paso refrescar_mesas")
        self.refrescar_stats()
        _checkpoint("on_start: paso refrescar_stats")
        # Si Android mato el proceso completo por falta de RAM mientras
        # estaba en pausa, aqui NO se llama on_resume (la app arranca de
        # cero), por eso restauramos tambien en el arranque normal.
        self._restaurar_estado_temporal()
        _checkpoint("on_start: paso _restaurar_estado_temporal")
        self._iniciar_servidor_mesas()
        _checkpoint("on_start: paso _iniciar_servidor_mesas (fin de on_start)")

    # Interruptor manual: CONFIRMADO -- en Pydroid 3, cualquier intento de
    # abrir un servidor Flask (escuchando en 0.0.0.0 o en la IP especifica
    # del wifi, se probaron ambos) tumba el proceso completo a nivel de
    # sistema, sin lanzar ninguna excepcion de Python atrapable. Es un
    # limite del propio Pydroid 3, no de este codigo. En el APK compilado
    # con buildozer SI funciona (buildozer.spec ya declara INTERNET /
    # ACCESS_NETWORK_STATE / ACCESS_WIFI_STATE). Dejar en False mientras
    # se prueba en Pydroid 3; cambiar a True solo para el APK compilado.
    _SERVIDOR_MESAS_ACTIVO = True

    def _popup_aprobar_mesero(self, nombre, callback, timeout=90.0):
        """Se llama desde servidor_mesas.py (hilo de Flask, vía Clock)
        cada vez que un mesero manda un nombre + contraseña correctos en
        /login. Antes de entregarle el token de acceso, la cajera tiene
        que aceptarlo aquí -- así una contraseña de empleado que ya no
        trabaja ahí (o que alguien más se sabe) no basta por sí sola
        para tomar pedidos.

        'callback' se llama UNA sola vez con True (Aceptar) o False
        (Negar / se acabó el tiempo) -- del otro lado hay un hilo de
        esa petición HTTP esperando esta respuesta con un
        threading.Event, así que aquí SIEMPRE hay que terminar llamando
        a callback, sin excepción, o el mesero se queda colgado hasta
        que el propio servidor expire la espera por su cuenta.

        Si llegan varios meseros casi al mismo tiempo, se encolan y se
        muestran uno por uno (nunca dos popups de aprobación encimados)."""
        if not hasattr(self, "_cola_aprobacion_mesero"):
            self._cola_aprobacion_mesero = []
            self._popup_aprobacion_activo = False

        self._cola_aprobacion_mesero.append((nombre, callback, timeout))
        if not self._popup_aprobacion_activo:
            self._procesar_cola_aprobacion_mesero()

    def _procesar_cola_aprobacion_mesero(self):
        """Saca la siguiente solicitud pendiente de la cola y muestra su
        popup. Se vuelve a llamar sola cuando ese popup se resuelve
        (Aceptar, Negar o timeout), hasta vaciar la cola."""
        if not getattr(self, "_cola_aprobacion_mesero", None):
            self._popup_aprobacion_activo = False
            return
        self._popup_aprobacion_activo = True
        nombre, callback, timeout = self._cola_aprobacion_mesero.pop(0)

        resuelto = {"listo": False}
        popup_ref = [None]

        def _resolver(aceptado):
            # Guardia: Aceptar/Negar y el timeout automático pueden
            # dispararse casi al mismo tiempo -- solo el primero cuenta.
            if resuelto["listo"]:
                return
            resuelto["listo"] = True
            try:
                if popup_ref[0]:
                    popup_ref[0].dismiss()
            except Exception:
                pass
            try:
                callback(aceptado)
            except Exception:
                pass
            Clock.schedule_once(lambda dt: self._procesar_cola_aprobacion_mesero(), 0)

        content = BoxLayout(orientation="vertical", padding=dp(18), spacing=dp(12))
        content.add_widget(lbl(
            "[b]NUEVO MESERO CONECTÁNDOSE[/b]", markup=True, color=self.texto_contraste(self.OSCURO),
            font_size="14sp", halign="center", size_hint_y=None, height=dp(26),
        ))
        content.add_widget(lbl(
            f"Usuario: [b]{nombre}[/b]", markup=True,
            color=self.texto_contraste(self.OSCURO), font_size="17sp",
            halign="center", size_hint_y=None, height=dp(34),
        ))
        content.add_widget(lbl(
            "¿Le das acceso para tomar pedidos?",
            color=self.texto_contraste(self.OSCURO)[:3] + [0.65],
            font_size="12sp", halign="center", size_hint_y=None, height=dp(22),
        ))

        btns = BoxLayout(orientation="horizontal", size_hint_y=None,
                         height=dp(46), spacing=dp(10))
        b_negar = btn_raised("NEGAR", bg=self.ROJO,
                             size_hint_y=None, height=dp(46), font_size="14sp")
        b_aceptar = btn_raised("ACEPTAR", bg=self.ACCENT,
                               size_hint_y=None, height=dp(46), font_size="14sp")
        btns.add_widget(b_negar)
        btns.add_widget(b_aceptar)
        content.add_widget(btns)

        popup = Popup(title="", separator_height=0, content=content,
                      size_hint=(0.86, None), height=dp(240),
                      background_color=self.OSCURO, auto_dismiss=False)
        popup_ref[0] = popup

        b_negar.bind(on_press=lambda *_: _resolver(False))
        b_aceptar.bind(on_press=lambda *_: _resolver(True))
        popup.open()

        # Si la cajera no responde a tiempo, se niega solo -- mismo
        # plazo que el hilo de Flask que está esperando esta respuesta
        # (servidor_mesas._pedir_aprobacion_mesero), para no dejar el
        # popup pegado en pantalla después de que el mesero ya recibió
        # un "no autorizado" por el lado del servidor.
        Clock.schedule_once(lambda dt: _resolver(False), timeout)

    def _iniciar_servidor_mesas(self):
        """Levanta el servidor local para que los meseros tomen pedidos
        desde el navegador de su celular (misma red WiFi). No requiere
        internet ni instalar nada del lado del mesero. Si algo falla,
        se muestra un popup EN PANTALLA con el motivo -- no hace falta
        revisar consola ni logs."""
        if not self._SERVIDOR_MESAS_ACTIVO:
            return
        if iniciar_servidor is None:
            self._popup_error_servidor(
                "No se encontró el archivo servidor_mesas.py junto a la "
                "app, o falló al importarlo."
            )
            return
        try:
            self._checkpoint_externo = _checkpoint  # para que servidor_mesas.py pueda dejar sus propios checkpoints
            iniciar_servidor(self, on_error=self._popup_error_servidor)
            Clock.schedule_once(lambda dt: self._avisar_ip_servidor(), 2.0)
        except Exception as e:
            self._popup_error_servidor(str(e))

    def abrir_popup_servidor(self):
        """Abre el popup con el QR y el enlace del servidor de meseros en
        cualquier momento -- lo dispara el boton 'SRV' de la pantalla de
        inicio. Antes este popup solo aparecia 2 segundos despues de
        arrancar la app; ahora tambien se puede volver a ver cuando
        haga falta (por ejemplo si llega un mesero nuevo a medio turno)."""
        httpd = getattr(self, "_httpd_servidor_mesas", None)
        if httpd is None:
            self._popup_error_servidor(
                "El servidor de meseros no esta corriendo ahorita. "
                "Revisa que este activado y que no haya fallado al iniciar "
                "(cierra y vuelve a abrir la app si acabas de instalar "
                "'flask')."
            )
            return
        self._avisar_ip_servidor()

    def _avisar_ip_servidor(self):
        _checkpoint("_avisar_ip_servidor: inicio (2s despues de iniciar servidor)")
        try:
            ip = obtener_ip_local() if obtener_ip_local else "?"
            url_ip = f"http://{ip}:5000"
            disponible_mdns, motivo_mdns = getattr(
                self, "_mdns_estado", (False, "No se pudo confirmar el estado de mDNS.")
            )
            url_mdns = f"http://{NOMBRE_MDNS}:5000" if disponible_mdns else None
            self._popup_ip_servidor(url_ip, url_mdns, motivo_mdns if not disponible_mdns else None)
            _checkpoint("_avisar_ip_servidor: popup mostrado sin problema")
        except Exception:
            pass

    def _generar_qr_widget(self, url, tamano_dp=170):
        """Genera un QR de 'url' y lo regresa como (widget, None), o
        (None, motivo) si la libreria 'qrcode' no esta instalada o algo
        fallo -- para poder avisar el motivo real en pantalla en vez de
        que el QR simplemente no aparezca sin explicacion.

        En Pydroid 3: Menu -> Pip -> buscar 'qrcode' e instalar; si pide
        Pillow y no la tienes, instala tambien 'pillow' (casi siempre ya
        viene con Kivy). Se hace en memoria (BytesIO), sin tocar disco."""
        try:
            import qrcode
        except ImportError:
            return None, "Falta instalar 'qrcode' (Pydroid: Pip -> qrcode)."
        try:
            import io
            from kivy.core.image import Image as CoreImage

            img = qrcode.make(url, border=2)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            buf.seek(0)
            core_img = CoreImage(buf, ext="png")
            widget = KivyImage(texture=core_img.texture,
                               size_hint=(None, None),
                               size=(dp(tamano_dp), dp(tamano_dp)))
            return widget, None
        except Exception as e:
            print("QR no disponible:", e)
            return None, f"No se pudo generar el QR: {e}"

    def _popup_ip_servidor(self, url_ip, url_mdns=None, motivo_mdns=None):
        """Muestra las direcciones del servidor de meseros en un popup:
        - Codigo QR de la IP: para no escribir nada, solo escanear.
        - Nombre bonito (http://comandero.local:5000): funciona sin
          escribir numeros, pero depende de 'zeroconf' instalado Y de
          que el navegador del telefono del mesero sepa resolver
          nombres .local (no garantizado en todos los Android).
        - IP numerica: respaldo que SIEMPRE funciona.
        Si el QR o el mDNS no estan disponibles, se explica el motivo
        en vez de desaparecer sin avisar nada."""
        try:
            from kivy.core.clipboard import Clipboard

            content = BoxLayout(orientation="vertical", padding=dp(16),
                                spacing=dp(8), size_hint_y=None)
            content.bind(minimum_height=content.setter("height"))

            content.add_widget(lbl(
                "[b]Servidor de meseros listo[/b]", markup=True,
                color=self.texto_contraste(self.OSCURO), font_size="15sp", halign="center",
                size_hint_y=None, height=dp(26),
            ))

            qr_widget, motivo_qr = self._generar_qr_widget(url_ip)
            if qr_widget is not None:
                content.add_widget(lbl(
                    "Escanea con la camara del celular:",
                    color=self.texto_contraste(self.OSCURO), font_size="12sp",
                    halign="center", size_hint_y=None, height=dp(20),
                ))
                fila_qr = AnchorLayout(size_hint_y=None, height=dp(180))
                fila_qr.add_widget(qr_widget)
                content.add_widget(fila_qr)
            elif motivo_qr:
                content.add_widget(lbl(
                    f"QR no disponible: {motivo_qr}",
                    color=AVISO_AMBAR, font_size="11sp",
                    halign="center", size_hint_y=None, height=dp(32),
                    auto_height=True,
                ))

            if url_mdns:
                content.add_widget(lbl(
                    "O escribe en el navegador (misma red WiFi):",
                    color=self.texto_contraste(self.OSCURO), font_size="12sp",
                    halign="center", size_hint_y=None, height=dp(20),
                ))
                campo_mdns = TextInput(
                    text=url_mdns, readonly=True, multiline=False,
                    font_size="15sp", halign="center",
                    size_hint_y=None, height=dp(42),
                    background_color=CAMPO_CODIGO_BG, foreground_color=CAMPO_CODIGO_FG,
                )
                campo_mdns.bind(
                    on_touch_down=lambda inst, touch:
                        inst.select_all() if inst.collide_point(*touch.pos) else None
                )
                content.add_widget(campo_mdns)
                content.add_widget(lbl(
                    "Si esa direccion no abre en su celular, usa esta:",
                    color=self.texto_contraste(self.OSCURO)[:3] + [0.6],
                    font_size="11sp", halign="center",
                    size_hint_y=None, height=dp(18),
                ))
            elif motivo_mdns:
                content.add_widget(lbl(
                    f"Nombre .local no disponible: {motivo_mdns}",
                    color=AVISO_AMBAR, font_size="11sp",
                    halign="center", size_hint_y=None, height=dp(32),
                    auto_height=True,
                ))

            campo_url = TextInput(
                text=url_ip, readonly=True, multiline=False,
                font_size="15sp", halign="center",
                size_hint_y=None, height=dp(42),
                background_color=CAMPO_CODIGO_BG, foreground_color=CAMPO_CODIGO_FG,
            )
            campo_url.bind(
                on_touch_down=lambda inst, touch:
                    inst.select_all() if inst.collide_point(*touch.pos) else None
            )
            content.add_widget(campo_url)

            fila_botones = BoxLayout(orientation="horizontal", spacing=dp(10),
                                     size_hint_y=None, height=dp(44))

            def _copiar(*_a):
                Clipboard.copy(url_mdns or url_ip)
                _snack("Direccion copiada")

            b_copiar = btn_raised("Copiar", bg=self.DORADO,
                                  size_hint_y=None, height=dp(44),
                                  on_press=_copiar)
            b_cerrar = btn_raised("Cerrar", bg=GRIS,
                                  size_hint_y=None, height=dp(44))
            fila_botones.add_widget(b_copiar)
            fila_botones.add_widget(b_cerrar)
            content.add_widget(fila_botones)

            alto_popup = dp(360) if qr_widget is not None else dp(280)
            alto_popup = alto_popup + (dp(80) if (url_mdns or motivo_mdns) else 0)
            alto_popup = alto_popup + (dp(40) if motivo_qr else 0)

            scroll = ScrollView(size_hint=(1, None), height=min(dp(560), alto_popup))
            scroll.add_widget(content)

            popup = Popup(title="", separator_height=0, content=scroll,
                          size_hint=(0.9, None), height=min(dp(600), alto_popup + dp(20)),
                          background_color=self.OSCURO)
            b_cerrar.bind(on_press=lambda *_: popup.dismiss())
            popup.open()
        except Exception as e:
            # Si algo del popup falla, al menos avisa por snackbar como antes
            print("Error mostrando popup de IP:", e)
            _snack(f"Meseros: conectense a {url_ip}")

    def _popup_error_servidor(self, texto):
        """Muestra en pantalla (no en consola) por qué no arrancó el
        servidor de meseros. La app de la cajera sigue funcionando
        normal aunque esto falle."""
        try:
            content = BoxLayout(orientation="vertical", padding=dp(16),
                                spacing=dp(10), size_hint_y=None)
            content.bind(minimum_height=content.setter("height"))
            content.add_widget(lbl(
                "[b]Servidor de meseros no arrancó[/b]", markup=True,
                color=self.texto_contraste(self.OSCURO), font_size="15sp", halign="center",
                size_hint_y=None, height=dp(28), auto_height=True,
            ))
            content.add_widget(lbl(
                str(texto), color=self.texto_contraste(self.OSCURO),
                font_size="12sp", halign="left", size_hint_y=None,
                height=dp(60), auto_height=True,
            ))
            content.add_widget(lbl(
                "La app de caja sigue funcionando normal.",
                color=GRIS, font_size="11sp", halign="center",
                size_hint_y=None, height=dp(24), auto_height=True,
            ))
            b_cerrar = btn_raised("Entendido", bg=self.DORADO,
                                  size_hint_y=None, height=dp(42))
            content.add_widget(b_cerrar)
            popup = Popup(title="", separator_height=0, content=content,
                          size_hint=(0.9, None), background_color=self.OSCURO)

            def _sync_popup_height(*_):
                # El popup SIEMPRE sigue el alto real del contenido -- antes
                # quedaba fijo en dp(280) sin importar que tan largo fuera
                # el texto del error, y todo se encimaba si no cabia ahi.
                popup.height = min(content.height + dp(24), dp(560))
            content.bind(minimum_height=_sync_popup_height)
            _sync_popup_height()

            b_cerrar.bind(on_press=lambda *_: popup.dismiss())
            popup.open()
        except Exception as e:
            print("Error mostrando popup de servidor:", e)

    def _solicitar_permisos_inicio(self):
        """Al iniciar, pide los permisos de almacenamiento que la app
        necesita (guarda la base de datos y el logo en la memoria
        compartida del telefono, fuera de su carpeta privada).

        - Permisos normales (leer/escribir almacenamiento): se piden con
          el dialogo comun de Android.
        - Permiso avanzado "Acceso a todos los archivos" (obligatorio
          desde Android 11 para escribir fuera de la carpeta privada):
          Android ya no deja concederlo con un dialogo, solo desde
          Ajustes -- asi que si falta, se abre esa pantalla de Ajustes
          directamente en vez de mostrar un mensaje pidiendo que el
          usuario la busque el solo.

        En Pydroid 3 (sin las clases de python-for-android) o en
        cualquier entorno que no sea Android, esto no hace nada."""
        if not _PERMITIR_CODIGO_ANDROID_NATIVO:
            return
        try:
            from jnius import autoclass
            Build = autoclass("android.os.Build$VERSION")
            sdk_int = Build.SDK_INT
        except Exception:
            return  # No es un APK de Android: no hay nada que pedir

        # Permisos "normales" de almacenamiento (Android 6 a 10).
        try:
            from android.permissions import request_permissions, Permission
            request_permissions([
                Permission.WRITE_EXTERNAL_STORAGE,
                Permission.READ_EXTERNAL_STORAGE,
            ])
        except Exception as e:
            print("No se pudieron pedir permisos basicos:", e)

        # Permiso avanzado (Android 11+ / API 30+): "Acceso a todos los
        # archivos". Si falta, ir directo a la pantalla de Ajustes donde
        # se concede, en vez de un permiso que Android ya no muestra
        # como dialogo emergente.
        if sdk_int >= 30:
            try:
                Environment = autoclass("android.os.Environment")
                if not Environment.isExternalStorageManager():
                    Intent   = autoclass("android.content.Intent")
                    Settings = autoclass("android.provider.Settings")
                    Uri      = autoclass("android.net.Uri")
                    PythonActivity = autoclass("org.kivy.android.PythonActivity")
                    paquete = PythonActivity.mActivity.getPackageName()
                    intent = Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION)
                    intent.setData(Uri.parse("package:" + paquete))
                    PythonActivity.mActivity.startActivity(intent)
            except Exception as e:
                print("No se pudo abrir Ajustes de permisos avanzados:", e)

    def _mantener_app_viva(self):
        """Reduce (no elimina del todo, eso depende tambien del telefono)
        las probabilidades de que Android mate la app en segundo plano,
        para que el servidor de meseros siga respondiendo aunque la
        pantalla se bloquee o se cambie a otra app:

        1) Wake lock parcial: evita que el procesador se duerma del todo
           con la pantalla apagada/bloqueada (la pantalla SI se apaga,
           solo el CPU se mantiene activo para poder atender al servidor).
        2) Pide quedar fuera de la optimizacion de bateria (Doze), que es
           la razon #1 por la que Android detiene apps en segundo plano.

        En Pydroid 3 o fuera de Android esto no hace nada.
        """
        if not _PERMITIR_CODIGO_ANDROID_NATIVO:
            return
        try:
            from jnius import autoclass
        except Exception:
            return  # No es un APK de Android

        # 1) Wake lock parcial (se mantiene mientras la app viva, se
        # libera solo). Debe ir en un try aparte: si falla, igual
        # intentamos lo de la bateria.
        try:
            from jnius import cast
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            Context = autoclass("android.content.Context")
            PowerManager = autoclass("android.os.PowerManager")
            activity = PythonActivity.mActivity
            power_service = activity.getSystemService(Context.POWER_SERVICE)
            power_manager = cast("android.os.PowerManager", power_service)
            wake_lock = power_manager.newWakeLock(
                PowerManager.PARTIAL_WAKE_LOCK, "ComanderoEnoch::ServidorMesas"
            )
            wake_lock.setReferenceCounted(False)
            wake_lock.acquire()
            self._wake_lock = wake_lock  # guardamos la referencia, si se
            # pierde (recolector de basura) Android puede liberar el lock
        except Exception as e:
            print("No se pudo tomar el wake lock:", e)

        # 2) Excluir de la optimizacion de bateria (Android 6+ / API 23+).
        # Igual que el permiso de "todos los archivos": ya no se puede
        # conceder con un dialogo comun, hay que mandar a Ajustes.
        try:
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            Context = autoclass("android.content.Context")
            activity = PythonActivity.mActivity
            paquete = activity.getPackageName()
            power_service = activity.getSystemService(Context.POWER_SERVICE)
            ya_excluida = power_service.isIgnoringBatteryOptimizations(paquete)
            if not ya_excluida:
                Intent = autoclass("android.content.Intent")
                Settings = autoclass("android.provider.Settings")
                Uri = autoclass("android.net.Uri")
                intent = Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS)
                intent.setData(Uri.parse("package:" + paquete))
                activity.startActivity(intent)
        except Exception as e:
            print("No se pudo pedir exclusion de optimizacion de bateria:", e)

    def go_to(self, screen_name):
        """Navega a una pantalla y la registra en la pila de historial.
        Usar SIEMPRE en vez de asignar self.root.current directamente."""
        if screen_name != self.screen_history[-1]:
            self.screen_history.append(screen_name)
        self.root.current = screen_name

    def on_back_button(self, window, key, *args):
        """Controla el botón fisico/gesto Atrás de Android (keycode 27)."""
        _checkpoint(f"on_back_button: se recibio key={key}")
        if key == 27:
            if len(self.screen_history) > 1:
                self.screen_history.pop()
                self.root.current = self.screen_history[-1]
                return True   # evento consumido: no cierra la app
            self._confirmar_salida()
            return True       # se consume: la app NO cierra sola, decide el popup
        return False

    def _confirmar_salida(self):
        """Popup de 'seguro que quieres salir' -- se muestra al presionar
        Atrás estando ya en la pantalla de inicio."""
        if self._dialog:
            return  # ya hay un popup abierto, no apilar otro encima

        content = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(14),
                            size_hint_y=None)
        content.bind(minimum_height=content.setter("height"))
        content.add_widget(lbl("¿Deseas cerrar la aplicacion?",
                               color=self.texto_contraste(self.OSCURO),
                               font_size="15sp", halign="center",
                               size_hint_y=None, height=dp(50)))

        btns = BoxLayout(orientation="horizontal", size_hint_y=None,
                         height=dp(44), spacing=dp(10))
        b_cancelar = btn_flat("Cancelar", color=self.texto_contraste(self.OSCURO),
                              size_hint_y=None, height=dp(44))
        b_salir    = btn_raised("Salir", bg=self.ROJO,
                                size_hint_y=None, height=dp(44))
        btns.add_widget(b_cancelar)
        btns.add_widget(b_salir)
        content.add_widget(btns)

        popup = Popup(title="", separator_height=0, content=content,
                      size_hint=(0.8, None), height=dp(150),
                      background_color=self.OSCURO, auto_dismiss=False)

        def _cerrar_popup(*_):
            self._dialog = None
            popup.dismiss()

        b_cancelar.bind(on_press=_cerrar_popup)
        b_salir.bind(on_press=lambda *_: App.get_running_app().stop())

        self._dialog = popup
        popup.open()

    def on_stop(self):
        """Se llama al cerrar la app (cierre normal, o al presionar 'Salir'
        en el popup de _confirmar_salida -- ese boton llama App.stop(),
        que dispara on_stop() igual que un cierre normal): aseguramos que
        el tema activo quede guardado para la proxima vez que se abra, y
        apagamos el servidor de mesas de forma limpia para no dejar el
        puerto ocupado en el celular/tablet."""
        _checkpoint("on_stop: Kivy llamo on_stop (cierre 'avisado', no un kill)")
        try:
            self._guardar_config("tema", self.tema_actual)
        except Exception:
            pass
        self._guardar_estado_temporal()  # red de seguridad extra ante un kill
        try:
            if detener_servidor is not None:
                detener_servidor(self)
                _checkpoint("on_stop: servidor de mesas apagado")
        except Exception:
            pass
        try:
            if getattr(self, "_wake_lock", None):
                self._wake_lock.release()
        except Exception:
            pass

    # ── SEGUNDO PLANO (pausa / reanudacion) ─────────────────────────────────────
    def on_pause(self):
        """Se dispara al presionar Home, bloquear pantalla, o cambiar de app.
        Devolver True es obligatorio: le indica a Android que la app debe
        quedar pausada (no destruida) y que puede llamarse on_resume().

        A PROPOSITO NO se llama detener_servidor() aqui: _mantener_app_viva()
        (wake lock + exclusion de Doze) existe precisamente para que los
        meseros sigan pudiendo mandar comandas mientras la pantalla de la
        cajera esta apagada/bloqueada. Apagar el servidor en cada pausa
        rompería esa funcion. Solo se apaga en on_stop(), un cierre real."""
        self._guardar_estado_temporal()
        return True

    def on_resume(self):
        """Se dispara al volver a la app tras un on_pause. Si Android
        mato el proceso por falta de memoria mientras estaba en pausa,
        aqui restauramos lo que se congelo, y la vista queda igual."""
        self._restaurar_estado_temporal()

    def llamar_red_segura(self, func, *args, on_error=None, **kwargs):
        """Envoltura para CUALQUIER llamada de red futura (sync a la nube,
        verificar licencia, etc). Si no hay internet o el servidor no
        responde, nunca truena la app: muestra un snack y sigue local."""
        import socket
        try:
            return func(*args, **kwargs)
        except (socket.timeout, socket.gaierror, ConnectionError, OSError) as e:
            _snack("Sin conexion. Se sigue trabajando en modo local.")
            if callable(on_error):
                on_error(e)
            return None
        except Exception as e:
            _snack("No se pudo completar la accion en linea.")
            if callable(on_error):
                on_error(e)
            return None

    def _guardar_estado_temporal(self):
        """Congela en la tabla config (SQLite) todo lo que se perderia si
        el proceso muere en segundo plano: la orden en curso, los campos
        de domicilio, Y TAMBIEN self.pedidos completo (todas las mesas
        ocupadas y los domicilios activos). Antes solo se respaldaba
        orden_actual; self.pedidos nunca se guardaba, asi que si Android
        mataba el proceso en pausa (pantalla bloqueada / cambio de app)
        se perdian TODAS las mesas abiertas de los clientes al volver.
        Antes esto era un archivo estado_temporal.json; ahora vive en la
        misma base que el resto de la config."""
        try:
            estado = {
                "pantalla":           self.root.current if self.root else "inicio",
                "orden_actual":       self.orden_actual,
                "tipo_orden":         self.tipo_orden,
                "mesa_sel":           self.mesa_sel,
                # self.pedidos = TODAS las mesas ocupadas + domicilios
                # activos. Es la parte critica que antes se perdia.
                "pedidos":            self.pedidos,
                # Si el usuario estaba agregando productos a una mesa YA
                # existente (no una nueva), hay que recordar cual, o al
                # volver "guardar_pedido" la trataria como pedido nuevo
                # y duplicaria la mesa en vez de actualizarla.
                "pedido_editando_id": getattr(self, "_pedido_editando_id", None),
            }
            sc = self.root.get_screen("orden") if self.root else None
            if sc:
                estado["campo_nombre"]    = sc.ids.campo_nombre.text
                estado["campo_telefono"]  = sc.ids.campo_telefono.text
                estado["campo_direccion"] = sc.ids.campo_direccion.text
            self._guardar_config("estado_temporal", json.dumps(estado))
        except Exception as e:
            print("Error guardando estado_temporal:", e)

    def _restaurar_estado_temporal(self):
        """Si hay un estado guardado en config, repone self.pedidos (TODAS
        las mesas ocupadas y domicilios activos), la orden en construccion
        y los campos de texto, exactamente como estaban antes de que la
        app se pausara o el proceso muriera en segundo plano."""
        crudo = self._leer_config("estado_temporal", None)
        if not crudo:
            return
        try:
            estado = json.loads(crudo)

            # self.pedidos es la parte critica: si no se restaura, todas
            # las mesas que el mesero tenia abiertas (y los domicilios en
            # curso) desaparecen como si nunca hubieran existido.
            pedidos_guardados = estado.get("pedidos")
            if isinstance(pedidos_guardados, list):
                self.pedidos = pedidos_guardados

            self.orden_actual        = estado.get("orden_actual", [])
            self.tipo_orden          = estado.get("tipo_orden")
            self.mesa_sel            = estado.get("mesa_sel")
            self._pedido_editando_id = estado.get("pedido_editando_id")

            sc = self.root.get_screen("orden") if self.root else None
            if sc:
                sc.ids.campo_nombre.text    = estado.get("campo_nombre", "")
                sc.ids.campo_telefono.text  = estado.get("campo_telefono", "")
                sc.ids.campo_direccion.text = estado.get("campo_direccion", "")
                if self.orden_actual:
                    self._rebuild_resumen()  # repinta la lista de items en pantalla

            # refrescar_mesas()/refrescar_stats() ya se llamaron en on_start
            # ANTES de esta funcion (con self.pedidos todavia vacio), y
            # on_resume no los llama en absoluto. Hay que repintar de
            # nuevo aqui para que las mesas ocupadas y los totales
            # reflejen el self.pedidos recien restaurado.
            self.refrescar_mesas()
            self.refrescar_stats()
            try:
                self.refrescar_lista_activos()
            except Exception:
                pass  # la pantalla "activos" puede no existir todavia

            self._guardar_config("estado_temporal", "")  # ya se restauro, no reusar
        except Exception as e:
            print("Error restaurando estado_temporal:", e)

    # ── BASE DE DATOS ─────────────────────────────────────────────────────────
    def _db_path(self):
        """La carpeta se resuelve via _CARPETA_ERRORES, que en un arranque
        en frio ya viene inicializada por _leer_puntero_carpeta() (ver
        cabecera del archivo) -- asi la BD se encuentra sin importar que
        el nombre de la empresa se haya cambiado en sesiones anteriores.

        Usa self.user_data_dir (aqui SI hay "self", a diferencia del
        modulo) en vez de una ruta fija a la raiz del storage, para no
        toparse con PermissionError en Android 10+ (scoped storage)."""
        try:
            carpeta = os.path.join(self.user_data_dir, _CARPETA_ERRORES["nombre"])
            os.makedirs(carpeta, exist_ok=True)
        except Exception:
            carpeta = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(carpeta, "ventas_birria.db")

    def _init_db(self):
        self.db = BaseDatos(self._db_path())
        self.db.inicializar()

    def _fecha_instalacion(self):
        """Fecha (date) en que se instaló/corrió la app por primera vez en
        este dispositivo. Si por algún motivo no existe (BD antigua sin
        el registro), se guarda hoy como fallback y se usa esa."""
        valor = self.db.fecha_instalacion()
        if valor:
            try:
                return datetime.strptime(valor, "%Y-%m-%d").date()
            except Exception:
                pass
        hoy = datetime.now().date()
        self.db.guardar_config("fecha_instalacion", hoy.strftime("%Y-%m-%d"))
        return hoy

    def _fechas_con_estadisticas(self):
        """Regresa un set() de date() para cada día que ya tiene al menos
        una venta o una pérdida fantasma registrada en la BD. Sólo esos
        días deben ser accionables en el calendario de Estadísticas >
        Fechas -- se incluye pérdida fantasma para no esconder un día
        donde solo hubo cancelaciones y ninguna venta cobrada."""
        fechas = set()
        for f in self.db.fechas_con_estadisticas():
            try:
                fechas.add(datetime.strptime(f, "%Y-%m-%d").date())
            except Exception:
                pass
        return fechas

    def _guardar_config(self, clave, valor):
        """Guarda un ajuste (ej. tema) en la BD para que persista entre sesiones."""
        self.db.guardar_config(clave, valor)

    def _leer_config(self, clave, default=None):
        """Lee un ajuste guardado en la BD. Si no existe, regresa default."""
        return self.db.leer_config(clave, default)

    def _guardar_empleados(self):
        """Persiste la lista de empleados (nombre + contraseña) en la BD."""
        self._guardar_config("empleados", json.dumps(self.empleados))

    def _cargar_menu(self):
        """Carga self.menu (categorias -> productos -> precios) desde la
        BD (config["menu"], guardado como JSON). Si no hay nada guardado
        todavia (primera vez que corre la app en este dispositivo) o el
        valor guardado esta corrupto/vacio, cae de vuelta a MENU_DEFAULT
        y lo persiste de inmediato para dejar la BD en un estado valido."""
        crudo = self._leer_config("menu", None)
        if crudo:
            try:
                menu = json.loads(crudo)
                if isinstance(menu, dict) and menu:
                    return menu
            except Exception as e:
                print("Error leyendo menu guardado, se usa el de fabrica:", e)
        menu = copy.deepcopy(MENU_DEFAULT)
        self._guardar_config("menu", json.dumps(menu))
        return menu

    def _cargar_mesas(self):
        """Carga self.mesas (lista de nombres) desde la BD (config["mesas"],
        guardado como JSON). Igual que _cargar_menu: si no hay nada
        guardado o esta corrupto, usa MESAS_DEFAULT y lo persiste."""
        crudo = self._leer_config("mesas", None)
        if crudo:
            try:
                mesas = json.loads(crudo)
                if isinstance(mesas, list) and mesas:
                    return mesas
            except Exception as e:
                print("Error leyendo mesas guardadas, se usan las de fabrica:", e)
        mesas = list(MESAS_DEFAULT)
        self._guardar_config("mesas", json.dumps(mesas))
        return mesas

    def _guardar_menu(self):
        """Persiste self.menu completo en la BD. Debe llamarse cada vez
        que se agregue, edite o elimine una categoria/producto/precio
        desde Configuracion, o el cambio se pierde al cerrar la app."""
        self._guardar_config("menu", json.dumps(self.menu))

    def _guardar_mesas(self):
        """Persiste self.mesas en la BD. Debe llamarse cada vez que se
        agregue o quite una mesa desde Configuracion."""
        self._guardar_config("mesas", json.dumps(self.mesas))

    def _cargar_info_negocio(self):
        """Carga self.info_negocio (direccion, datos bancarios y mensaje
        de agradecimiento para el ticket) desde la BD (config
        ["info_negocio"], guardado como JSON). Todos los campos son
        opcionales: si no hay nada guardado (primera vez) o el valor esta
        corrupto, se completa con "" para cada clave de
        INFO_NEGOCIO_DEFAULT -- a diferencia de _cargar_menu/_cargar_mesas,
        aqui NO hay datos de fabrica que mostrar, un ticket sin esta
        informacion es perfectamente valido. Si en el futuro se agrega un
        campo nuevo a INFO_NEGOCIO_DEFAULT, esta funcion ya lo completa
        solo (setdefault via dict(INFO_NEGOCIO_DEFAULT)) sin migracion
        manual."""
        crudo = self._leer_config("info_negocio", None)
        datos = dict(INFO_NEGOCIO_DEFAULT)
        if crudo:
            try:
                guardado = json.loads(crudo)
                if isinstance(guardado, dict):
                    for clave in datos:
                        if clave in guardado:
                            datos[clave] = guardado[clave]
            except Exception as e:
                print("Error leyendo info_negocio guardada, se usan campos vacios:", e)
        return datos

    def _guardar_info_negocio(self):
        """Persiste self.info_negocio completo en la BD. Debe llamarse
        cada vez que se edite algun campo desde Configuracion >
        Personalizacion > Informacion del negocio y ticket, o el cambio
        se pierde al cerrar la app. NO afecta pedidos ya cobrados
        anteriormente: esta info solo se lee al armar un ticket NUEVO."""
        self._guardar_config("info_negocio", json.dumps(self.info_negocio))


    def _registrar_venta_db(self, items, tipo_orden, pedido_id="", mesa_nombre="", forma_pago="efectivo"):
        """Guarda TODOS los items del pedido cobrado en una sola
        transaccion SQLite. Antes, todos los INSERT vivian en un solo
        try/except que solo IMPRIMIA el error si algo fallaba (ej. un
        item sin "precio" por un KeyError): la venta completa se perdia
        sin dejar rastro en la BD, pero el llamador (_cobrar_pedido) no
        se enteraba y quitaba el pedido de "activos" de todos modos —
        el usuario veia "Cobrado" y el dinero desaparecia sin registro.

        Ahora: BEGIN al inicio, un INSERT por item, y si CUALQUIERA falla
        se hace ROLLBACK de TODO el pedido (no se guarda nada a medias).
        Devuelve True solo si la venta completa quedo guardada, False si
        se revirtio por cualquier error. El llamador DEBE revisar este
        valor antes de dar la venta por hecha."""
        prod_cat = {}
        for cat, prods in self.menu.items():
            for p in prods:
                prod_cat[p["id"]] = cat
        return self.db.registrar_venta(
            items, tipo_orden, prod_cat,
            pedido_id=pedido_id, mesa_nombre=mesa_nombre, forma_pago=forma_pago,
        )

    def _registrar_personas_mesa(self, mesa_nombre, personas):
        """Guarda cuantas personas entraron a una mesa al momento de abrirla,
        para poder saber en estadisticas cuanta gente ha entrado al local."""
        self.db.registrar_personas_mesa(mesa_nombre, personas)

    # ── ESTADÍSTICAS ─────────────────────────────────────────────────────────
    def ir_estadisticas(self):
        self.go_to("estadisticas")
        Clock.schedule_once(lambda dt: self._cargar_estadisticas("hoy"), 0.1)

    def _cambiar_periodo_est(self, periodo, btn_origen=None):
        """Cambia el periodo activo y actualiza los botones."""
        self._periodo_est_actual = periodo
        sc = self.root.get_screen("estadisticas")
        # Resetear texto del botón de fecha personalizada
        sc.ids.est_lbl_periodo.text = "Fecha..."
        self._cargar_estadisticas(periodo)

    def _cargar_estadisticas(self, periodo, fecha_custom=None):
        """Consulta la BD según el periodo y reconstruye la pantalla."""
        sc = self.root.get_screen("estadisticas")
        cuerpo = sc.ids.est_cuerpo
        cuerpo.clear_widgets()

        hoy = datetime.now().date()

        if periodo == "hoy":
            desde = hoy
            hasta = hoy
            titulo = "HOY"
        elif periodo == "semana":
            desde = hoy - timedelta(days=6)
            hasta = hoy
            titulo = "ESTA SEMANA"
        elif periodo == "mes":
            desde = hoy.replace(day=1)
            hasta = hoy
            titulo = "ESTE MES"
        elif periodo == "3meses":
            desde = (hoy - timedelta(days=89)).replace(day=1)
            hasta = hoy
            titulo = "ÚLTIMOS 3 MESES"
        elif periodo == "6meses":
            desde = (hoy - timedelta(days=179)).replace(day=1)
            hasta = hoy
            titulo = "ÚLTIMOS 6 MESES"
        elif periodo == "anio":
            desde = hoy.replace(month=1, day=1)
            hasta = hoy
            titulo = "ESTE AÑO"
        elif periodo == "custom" and fecha_custom:
            desde = fecha_custom
            hasta = fecha_custom
            titulo = fecha_custom.strftime("%d/%m/%Y")
        else:
            desde = hoy
            hasta = hoy
            titulo = "HOY"

        ds = desde.strftime("%Y-%m-%d")
        hs = hasta.strftime("%Y-%m-%d")
        r = self.db.obtener_estadisticas(ds, hs)

        tiene_datos     = r["tiene_datos"]
        total_dinero    = r["total_dinero"]
        total_piezas    = r["total_piezas"]
        total_pedidos   = r["total_pedidos"]
        mesas_pedidos   = r["mesas_pedidos"]
        mesas_ganancia  = r["mesas_ganancia"]
        mesa_ticket     = r["mesa_ticket"]
        top_mesas       = r["top_mesas"]
        dom_pedidos     = r["dom_pedidos"]
        dom_ganancia    = r["dom_ganancia"]
        dom_ticket      = r["dom_ticket"]
        top_prods       = r["top_prods"]
        low_prods       = r["low_prods"]
        mesas_abiertas   = r["mesas_abiertas"]
        total_personas   = r["total_personas"]
        promedio_persona = r["promedio_persona"]
        top_horas       = r["top_horas"]
        total_gastos_periodo = r["total_gastos_periodo"]
        top_gastos      = r["top_gastos"]
        total_perdida_fantasma_periodo = r["total_perdida_fantasma_periodo"]
        lista_perdida_fantasma_periodo = r["lista_perdida_fantasma_periodo"]

        # ── Helpers de UI ──
        def card_inicio():
            box = BoxLayout(
                orientation="vertical",
                size_hint_y=None, padding=dp(14), spacing=dp(6),
            )
            with box.canvas.before:
                Color(*self.OSCURO)
                box._bg = RoundedRectangle(pos=box.pos, size=box.size, radius=[dp(16)])
            box.bind(pos=lambda w,v: setattr(w._bg,'pos',v),
                     size=lambda w,v: setattr(w._bg,'size',v))
            return box

        def card_fin(box):
            box.height = box.minimum_height if hasattr(box,'minimum_height') else dp(80)
            box.bind(minimum_height=box.setter('height'))
            cuerpo.add_widget(box)

        def seccion(texto, box=None):
            dest = box or cuerpo
            lw = lbl(f"[b]{texto}[/b]", markup=True, color=_texto_contraste(self.OSCURO),
                     font_size="13sp", size_hint_y=None, height=dp(26))
            dest.add_widget(lw)

        def fila(texto, valor, color_v=None, box=None):
            dest = box or cuerpo
            row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(24))
            row.add_widget(lbl(texto, color=_texto_contraste(self.OSCURO), font_size="12sp",
                               size_hint_y=None, height=dp(24)))
            row.add_widget(lbl(valor, color=color_v or _texto_contraste(self.OSCURO),
                               font_size="12sp", halign="right",
                               size_hint_y=None, height=dp(24)))
            dest.add_widget(row)

        def fila_gasto(texto, valor, color_v=None, box=None):
            """Como fila(), pero pensada para el nombre de un gasto, que
            puede ser un motivo de texto libre largo (p.ej. "Pérdida en
            efectivo: <motivo> (<detalle>)" de un producto/cuenta
            cancelada). Aquí el alto de la fila crece con el contenido
            real en vez de quedar fijo, para que el texto que no cabe
            no se dibuje encima del renglón siguiente."""
            dest = box or cuerpo
            H_G = dp(24)
            row = BoxLayout(orientation="horizontal", size_hint_y=None, height=H_G)
            l_txt = lbl(texto, color=_texto_contraste(self.OSCURO), font_size="12sp",
                       size_hint_y=None, height=H_G, auto_height=True)
            l_txt.size_hint_x = 0.65
            l_val = Label(text=valor, color=color_v or _texto_contraste(self.OSCURO), font_size="12sp",
                         halign="right", valign="middle",
                         size_hint_x=0.35, size_hint_y=1)
            l_val.bind(size=lambda inst,v: setattr(inst,"text_size",v))
            row.add_widget(l_txt)
            row.add_widget(l_val)
            l_txt.bind(height=lambda inst, v: setattr(row, "height", v))
            dest.add_widget(row)

        def sep(h=8):
            from kivy.uix.widget import Widget
            cuerpo.add_widget(Widget(size_hint_y=None, height=dp(h)))

        def linea_divisora():
            from kivy.uix.widget import Widget
            div = Widget(size_hint_y=None, height=dp(1))
            with div.canvas:
                Color(*GRIS)
                div._line = Rectangle(pos=div.pos, size=div.size)
            div.bind(pos=lambda w,v: setattr(w._line,'pos',v),
                     size=lambda w,v: setattr(w._line,'size',v))
            cuerpo.add_widget(div)

        # ── Título periodo ──
        lbl_t = lbl(f"[b]PERIODO: {titulo}[/b]", markup=True,
                    color=self.CREMA, font_size="15sp",
                    halign="center", size_hint_y=None, height=dp(34))
        cuerpo.add_widget(lbl_t)
        sep(6)

        if not tiene_datos:
            cuerpo.add_widget(lbl(
                "Sin registro para este periodo",
                color=_texto_contraste(self.NEGRO)[:3] + [0.6], font_size="14sp", halign="center",
                size_hint_y=None, height=dp(50),
            ))
            return

        # ══ RESUMEN GENERAL ══
        c = card_inicio()
        seccion("RESUMEN GENERAL", c)
        fila("Total recaudado:",  f"${total_dinero:,.0f}",  box=c)
        fila("Pedidos cobrados:", str(total_pedidos),        box=c)
        fila("Piezas vendidas:",  str(int(total_piezas)),    box=c)
        fila("Gastos:",           f"-${total_gastos_periodo:,.0f}", box=c)
        ganancia_neta_periodo = total_dinero - total_gastos_periodo
        color_gan_periodo = _verde_contraste(self.OSCURO) if ganancia_neta_periodo >= 0 else self.texto_contraste(self.OSCURO)
        fila("Ganancia neta:",    f"${ganancia_neta_periodo:,.0f}",
             color_v=color_gan_periodo, box=c)
        card_fin(c)
        sep()

        # ══ MESAS ══
        c = card_inicio()
        seccion("MESAS", c)
        fila("Pedidos de mesa:",  str(mesas_pedidos),                       box=c)
        fila("Total ganado:",     f"${mesas_ganancia:,.0f}",                box=c)
        fila("Ticket promedio:",  f"${mesa_ticket:,.0f}",                   box=c)
        if top_mesas:
            sep_lbl = lbl("  Top mesas:", color=_texto_contraste(self.OSCURO)[:3] + [0.85], font_size="11sp",
                          size_hint_y=None, height=dp(20))
            c.add_widget(sep_lbl)
            def _hexc(rgb):
                return "".join(f"{int(round(x*255)):02x}" for x in rgb[:3])
            for nombre_m, cnt_m, gan_m in top_mesas:
                row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(24))
                row.add_widget(lbl(f"    {nombre_m}", color=_texto_contraste(self.OSCURO), font_size="12sp",
                                   size_hint_y=None, height=dp(24)))
                valor_txt = (f"[color={_hexc(_texto_contraste(self.OSCURO))}]{cnt_m} pedidos  •  [/color]"
                             f"[color={_hexc(_texto_contraste(self.OSCURO))}]${gan_m:,.0f}[/color]")
                row.add_widget(lbl(valor_txt, markup=True, halign="right",
                                   font_size="12sp", size_hint_y=None, height=dp(24)))
                c.add_widget(row)
        card_fin(c)
        sep()

        # ══ GASTOS ══
        c = card_inicio()
        seccion("GASTOS", c)
        fila("Total gastado:", f"-${total_gastos_periodo:,.0f}", box=c)
        for nombre_g, total_g, veces_g in top_gastos:
            etiqueta_g = f"    {nombre_g}"
            valor_g = f"-${total_g:,.0f}"
            if veces_g > 1:
                valor_g += f"  ({int(veces_g)}×)"
            fila_gasto(etiqueta_g, valor_g, box=c)
        if not top_gastos:
            c.add_widget(lbl(
                "  Sin gastos registrados en este periodo",
                color=_texto_contraste(self.OSCURO)[:3] + [0.6], font_size="12sp",
                size_hint_y=None, height=dp(24),
            ))
        card_fin(c)
        sep()

        # ══ PÉRDIDA FANTASMA ══
        # Productos/cuentas cancelados YA GUARDADOS -- tabla independiente
        # de 'gastos' a propósito. NO se suma a "Total gastado" de arriba
        # ni afecta ninguna cifra de ganancia; solo se suma entre sí como
        # contador informativo/de auditoría.
        c = card_inicio()
        seccion("PÉRDIDA FANTASMA (no afecta ganancia ni gastos)", c)
        fila("Total pérdida fantasma:", f"-${total_perdida_fantasma_periodo:,.0f}", box=c)
        for ptipo, pdetalle, pmotivo, pmonto in lista_perdida_fantasma_periodo:
            etiqueta_tipo = "Cuenta" if ptipo == "cuenta" else "Producto"
            texto_pf = f"    {etiqueta_tipo}: {pdetalle} — Motivo: {pmotivo}"
            fila_gasto(texto_pf, f"-${pmonto:,.0f}", box=c)
        if not lista_perdida_fantasma_periodo:
            c.add_widget(lbl(
                "  Sin pérdidas fantasma en este periodo",
                color=_texto_contraste(self.OSCURO)[:3] + [0.6], font_size="12sp",
                size_hint_y=None, height=dp(24),
            ))
        card_fin(c)
        sep()

        # ══ CLIENTELA ══
        c = card_inicio()
        seccion("CLIENTELA (PERSONAS)", c)
        fila("Mesas abiertas:",      str(mesas_abiertas),               box=c)
        fila("Personas atendidas:",  str(int(total_personas)),          box=c)
        fila("Promedio por mesa:",   f"{promedio_persona:.1f}",         box=c)
        card_fin(c)
        sep()

        # ══ DOMICILIOS ══
        c = card_inicio()
        seccion("DOMICILIOS / PARA LLEVAR", c)
        fila("Pedidos domicilio:", str(dom_pedidos),                        box=c)
        fila("Total ganado:",      f"${dom_ganancia:,.0f}",                 box=c)
        fila("Ticket promedio:",   f"${dom_ticket:,.0f}",                   box=c)
        card_fin(c)
        sep()

        # ══ COMPARATIVA ══
        c = card_inicio()
        seccion("COMPARATIVA", c)
        tot = mesas_ganancia + dom_ganancia
        pct_m = (mesas_ganancia / tot * 100) if tot else 0
        pct_d = (dom_ganancia   / tot * 100) if tot else 0
        fila("Mesas aportaron:",      f"{pct_m:.0f}%  (${mesas_ganancia:,.0f})", box=c)
        fila("Domicilios aportaron:", f"{pct_d:.0f}%  (${dom_ganancia:,.0f})",   box=c)
        card_fin(c)
        sep()

        # ══ PRODUCTOS ══
        c = card_inicio()
        seccion("MÁS VENDIDOS", c)
        for nombre_p, cnt_p, gan_p in top_prods:
            fila(f"  {nombre_p}", f"{int(cnt_p)} pzas  •  ${gan_p:,.0f}", box=c)
        card_fin(c)
        sep()

        c = card_inicio()
        seccion("MENOS VENDIDOS", c)
        for nombre_p, cnt_p in low_prods:
            fila(f"  {nombre_p}", f"{int(cnt_p)} pzas", box=c)
        card_fin(c)
        sep()

        # ══ HORAS PICO ══
        c = card_inicio()
        seccion("HORAS PICO", c)
        for hora_i, cnt_h in top_horas:
            rng = f"{hora_i:02d}:00 – {hora_i:02d}:59"
            fila(f"  {rng}", f"{int(cnt_h)} ventas", box=c)
        card_fin(c)
        sep(12)

    def _abrir_calendario(self):
        """Calendario mensual completo desde el mes de instalación de la
        app hasta el mes actual. TODOS los días se ven (no sólo los que
        tienen ventas), pero únicamente los días que ya tienen
        estadísticas registradas (al menos una venta guardada en la BD)
        son accionables: se pintan en dorado y llevan al cierre de ese
        día en modo solo lectura. El resto de los días se muestran en
        gris, sin fondo ni evento, y no son interactivos hasta que se
        registren ventas en ellos."""
        instalacion = self._fecha_instalacion()
        hoy = datetime.now().date()
        fechas_con_datos = self._fechas_con_estadisticas()

        # Mes que se muestra actualmente (arranca en el mes de hoy) y los
        # límites de navegación: no se puede ir antes del mes de
        # instalación ni después del mes actual.
        mes_actual = [hoy.year, hoy.month]
        mes_min = (instalacion.year, instalacion.month)
        mes_max = (hoy.year, hoy.month)

        # ── Medidas fijas y conocidas de antemano (nada se lee de
        # propiedades calculadas por Kivy en tiempo de layout), para que
        # el alto del popup se pueda calcular con exactitud y no dependa
        # de que Kivy ya haya terminado de "asentar" el árbol de
        # widgets: eso fue lo que antes dejaba el popup diminuto con
        # contenido oculto.
        CELDA_H     = dp(44)
        FILA_SPC    = dp(3)
        CAB_H       = dp(40)
        AYUDA_H     = dp(32)
        DOW_H       = dp(22)
        CERRAR_H    = dp(40)
        CONTENT_PAD = dp(14)
        CONTENT_SPC = dp(8)
        FILAS_MAX   = 6  # un mes nunca ocupa más de 6 semanas

        content = BoxLayout(orientation="vertical", padding=CONTENT_PAD,
                            spacing=CONTENT_SPC, size_hint_y=None)
        content.bind(minimum_height=content.setter("height"))

        # ─── Cabecera con navegación de mes ─────────────────────────────
        cab = BoxLayout(orientation="horizontal", size_hint_y=None, height=CAB_H,
                        spacing=dp(6))
        b_prev = btn_flat("<", color=self.texto_contraste(self.OSCURO), size_hint_x=None, width=dp(40), height=CAB_H)
        lbl_mes = lbl("", color=_texto_contraste(self.OSCURO), font_size="15sp",
                      halign="center", size_hint_y=None, height=CAB_H, markup=True)
        b_next = btn_flat(">", color=self.texto_contraste(self.OSCURO), size_hint_x=None, width=dp(40), height=CAB_H)
        cab.add_widget(b_prev)
        cab.add_widget(lbl_mes)
        cab.add_widget(b_next)
        content.add_widget(cab)

        # Texto de ayuda con salto de línea fijo (2 líneas exactas) en
        # vez de auto-ajuste, para que su alto sea 100% predecible.
        content.add_widget(lbl(
            "Los días en dorado ya tienen ventas registradas\n"
            "y son los únicos consultables.",
            color=GRIS, font_size="11sp", halign="center",
            size_hint_y=None, height=AYUDA_H,
        ))

        # ─── Encabezado de días de la semana (Lunes a Domingo) ──────────
        dow = BoxLayout(orientation="horizontal", size_hint_y=None, height=DOW_H,
                        spacing=0)
        for d_nombre in DIAS_SEMANA_ES:
            dow.add_widget(lbl(d_nombre, color=GRIS, font_size="11sp",
                               halign="center", size_hint_y=None, height=DOW_H))
        content.add_widget(dow)

        # ─── Contenedor de la cuadrícula de días (se reconstruye al
        # cambiar de mes). Es un GridLayout de verdad con
        # row_force_default=True: eso OBLIGA a que cada una de las 6
        # filas mida exactamente CELDA_H, sin importar qué tipo de
        # widget se le ponga adentro (Label o celda clicable). Antes,
        # cada semana era su propio BoxLayout horizontal y cada celda
        # traía su propia altura "sugerida"; eso permitía que una celda
        # (sobre todo el botón dorado, con su padding interno) terminara
        # midiendo más que las demás y se recargara sobre la fila de
        # abajo. Con row_force_default eso ya no puede pasar: Kivy fija
        # la altura del widget al valor de la fila, punto.
        grid_wrap = GridLayout(cols=7, rows=FILAS_MAX, spacing=0,
                               size_hint_y=None,
                               height=FILAS_MAX * CELDA_H,
                               row_force_default=True,
                               row_default_height=CELDA_H)
        content.add_widget(grid_wrap)

        # Líneas finas que dividen la cuadrícula en 7x6 celdas iguales
        # (cuadrícula visible), pedidas explícitamente para reforzar que
        # cada número vive siempre en el mismo lugar exacto de su celda.
        # Se recalculan solas cada vez que el grid cambia de tamaño o
        # posición (p.ej. al abrirse el popup).
        def _redibujar_lineas(*_):
            grid_wrap.canvas.after.clear()
            x0, y0 = grid_wrap.pos
            w, h = grid_wrap.size
            col_w = w / 7.0
            with grid_wrap.canvas.after:
                Color(1, 1, 1, 0.10)
                # verticales: 8 líneas (2 bordes + 6 divisiones internas)
                for c in range(8):
                    x = x0 + c * col_w
                    Line(points=[x, y0, x, y0 + h], width=1)
                # horizontales: FILAS_MAX + 1 líneas
                for r in range(FILAS_MAX + 1):
                    y = y0 + r * CELDA_H
                    Line(points=[x0, y, x0 + w, y], width=1)

        grid_wrap.bind(pos=_redibujar_lineas, size=_redibujar_lineas)

        popup_ref = [None]

        def _ir_a_fecha(f):
            if popup_ref[0]:
                popup_ref[0].dismiss()
            # Al elegir un día con estadísticas registradas se muestra el
            # popup de CIERRE DE CAJA de ese día (mismo formato que el
            # cierre del día actual), recalculado en vivo desde las
            # tablas ventas/gastos ya guardadas en SQLite. Se abre en
            # modo solo_lectura=True para que desde Estadísticas sólo se
            # puedan CONSULTAR los datos de cierre, sin poder registrar
            # ni editar el fondo de caja (evita maniobras de la cajera).
            # El botón "CIERRE DE CAJA" original del día actual sigue
            # llamando a abrir_cierre_caja() sin este parámetro, así que
            # conserva la edición exactamente igual que antes.
            self.abrir_cierre_caja(fecha=f, solo_lectura=True)

        def _dibujar_mes(*_):
            grid_wrap.clear_widgets()
            anio, mes = mes_actual
            lbl_mes.text = f"[b]{MESES_ES[mes]} {anio}[/b]"

            b_prev.disabled = (anio, mes) <= mes_min
            b_next.disabled = (anio, mes) >= mes_max
            b_prev.opacity = 0.30 if b_prev.disabled else 1
            b_next.opacity = 0.30 if b_next.disabled else 1

            # calendar.monthrange: 0=lunes ... 6=domingo (coincide con
            # el encabezado L M M J V S D usado arriba).
            primer_dia_semana, n_dias_mes = calendar.monthrange(anio, mes)

            # Lista completa de celdas del mes: None = celda vacía de
            # relleno (antes del día 1 o después del último día). SIEMPRE
            # se completa hasta 7*FILAS_MAX celdas (6 semanas fijas), aun
            # si el mes sólo necesita 5 semanas: así la cuadrícula dibuja
            # siempre el mismo número de filas que el espacio reservado
            # en grid_wrap, sin dejar huecos ni descuadrar el alto del
            # popup entre un mes y otro.
            celdas = [None] * primer_dia_semana
            for dia_n in range(1, n_dias_mes + 1):
                celdas.append(date(anio, mes, dia_n))
            while len(celdas) < 7 * FILAS_MAX:
                celdas.append(None)

            # Se agregan las 7*FILAS_MAX celdas directo al GridLayout (que
            # las va acomodando solo, fila por fila, de izquierda a
            # derecha). row_force_default ya garantiza que TODAS midan
            # exactamente CELDA_H de alto y el GridLayout reparte el
            # ancho en 7 columnas iguales, así que ninguna celda -esté
            # vacía, sea un número suelto o el círculo dorado- puede
            # quedar más grande ni desplazada respecto a las demás.
            for f in celdas:
                if f is None:
                    grid_wrap.add_widget(Label(text=""))
                    continue

                if f in fechas_con_datos:
                    # Día accionable: tiene ventas/estadísticas
                    # registradas -> se puede consultar su cierre.
                    celda = _CeldaDiaCalendario(
                        bg=self.DORADO, text=str(f.day),
                        color=_texto_contraste(self.DORADO), font_size="13sp",
                        halign="center", valign="middle",
                    )
                    celda.bind(size=lambda inst, v: setattr(inst, "text_size", v))
                    celda.bind(on_release=lambda inst, f=f: _ir_a_fecha(f))
                    grid_wrap.add_widget(celda)
                else:
                    # Día sin ventas todavía: sólo se muestra el
                    # número, sin fondo y sin evento -> no interactivo.
                    es_hoy = (f == hoy)
                    txt = f"[u]{f.day}[/u]" if es_hoy else str(f.day)
                    color_num = (GRIS if instalacion <= f <= hoy
                                else [0.30, 0.30, 0.30, 1])
                    lb = Label(text=txt, color=color_num, font_size="13sp",
                              markup=True, halign="center", valign="middle")
                    lb.bind(size=lambda inst, v: setattr(inst, "text_size", v))
                    grid_wrap.add_widget(lb)

            _redibujar_lineas()

        def _cambiar_mes(delta):
            anio, mes = mes_actual
            mes += delta
            if mes < 1:
                mes = 12; anio -= 1
            elif mes > 12:
                mes = 1; anio += 1
            if (anio, mes) < mes_min or (anio, mes) > mes_max:
                return
            mes_actual[0], mes_actual[1] = anio, mes
            _dibujar_mes()

        b_prev.bind(on_press=lambda *_: _cambiar_mes(-1))
        b_next.bind(on_press=lambda *_: _cambiar_mes(1))

        _dibujar_mes()

        btn_cerrar = btn_flat("Cerrar", color=_texto_contraste(self.OSCURO),
                              size_hint_y=None, height=CERRAR_H)
        content.add_widget(btn_cerrar)

        # ── Alto del popup calculado con las medidas fijas de arriba
        # (nada leído de Kivy en caliente): cabecera + ayuda + días de
        # semana + cuadrícula de 6 filas fijas + botón cerrar + espacios
        # + padding + barra de título. Como grid_wrap SIEMPRE dibuja
        # exactamente 6 filas (rellenando con celdas vacías si el mes
        # necesita menos), este cálculo es exacto: nunca sobra ni falta
        # espacio, así que no hace falta scroll.
        n_bloques = 5  # cab, ayuda, dow, grid_wrap, btn_cerrar
        alto_contenido = (
            CAB_H + AYUDA_H + DOW_H + grid_wrap.height + CERRAR_H
            + CONTENT_SPC * (n_bloques - 1) + CONTENT_PAD * 2
        )
        barra_titulo_popup = dp(48)
        alto_popup = barra_titulo_popup + alto_contenido

        popup = Popup(
            title="Estadísticas por fecha",
            content=content,
            size_hint=(0.94, None),
            height=alto_popup,
            background_color=self.OSCURO,
        )
        popup_ref[0] = popup
        btn_cerrar.bind(on_press=lambda *_: popup.dismiss())
        popup.open()

    # ── Navegación ────────────────────────────────────────────────────────────
    def ir_activos(self):
        self.refrescar_lista_activos()
        self.go_to("activos")

    def cancelar_orden(self):
        try:
            from kivy.core.window import Window
            Window.release_all_keyboards()

            sc = self.root.get_screen("orden")
            for fid in ("campo_nombre", "campo_telefono", "campo_direccion"):
                try:
                    sc.ids[fid].text = ""
                    sc.ids[fid].focus = False
                except Exception:
                    pass

            self.orden_actual = []
            self._pedido_editando_id = None
            self.refrescar_mesas()
            self.refrescar_stats()
            self.go_to("inicio")
        except Exception as e:
            print("Error en cancelar_orden:", e)
            _snack("Ocurrio un error al volver")

    def eliminar_orden_mesa(self):
        """Elimina la selección actual, desocupa la mesa y regresa al menú principal."""
        try:
            from kivy.core.window import Window
            Window.release_all_keyboards()

            sc = self.root.get_screen("orden")
            for fid in ("campo_nombre", "campo_telefono", "campo_direccion"):
                try:
                    sc.ids[fid].text = ""
                    sc.ids[fid].focus = False
                except Exception:
                    pass

            # Si hay un pedido en edición, eliminarlo también de la lista
            if self._pedido_editando_id:
                self.pedidos = [p for p in self.pedidos
                                if p["id"] != self._pedido_editando_id]

            self.orden_actual = []
            self._pedido_editando_id = None
            self.mesa_sel = None
            self.refrescar_mesas()
            self.refrescar_stats()
            self.go_to("inicio")
        except Exception as e:
            print("Error en eliminar_orden_mesa:", e)
            _snack("Ocurrio un error al eliminar")

    def ir_config(self):
        """Pide contraseña antes de entrar a Config."""
        f_pass = campo_texto("Contraseña", password=True)
        popup_ref = [None]

        def _verificar(*_):
            if f_pass.text == self._password:
                if popup_ref[0]: popup_ref[0].dismiss()
                self._abrir_config_real()
            else:
                _snack("Contraseña incorrecta")
                f_pass.text = ""

        content = BoxLayout(orientation="vertical", padding=dp(14), spacing=dp(10))
        content.add_widget(lbl("[b]CONFIGURACION[/b]", markup=True,
                               color=self.texto_contraste(self.OSCURO), font_size="16sp",
                               halign="center", size_hint_y=None, height=dp(30)))
        content.add_widget(f_pass)
        btns = BoxLayout(orientation="horizontal", size_hint_y=None,
                         height=dp(44), spacing=dp(8))
        b_can  = btn_flat("Cancelar", color=_texto_contraste(self.OSCURO), size_hint_y=None, height=dp(38))
        b_ok   = btn_raised("Entrar", bg=self.ROJO,
                            size_hint_y=None, height=dp(38))
        btns.add_widget(b_can)
        btns.add_widget(b_ok)
        content.add_widget(btns)

        popup = Popup(title="", separator_height=0, content=content,
                      size_hint=(0.82, None), height=dp(220),
                      background_color=self.OSCURO)
        popup_ref[0] = popup
        b_ok.bind(on_press=_verificar)
        b_can.bind(on_press=lambda *_: popup.dismiss())
        f_pass.bind(on_text_validate=_verificar)
        popup.open()

    def _abrir_config_real(self):
        self.refrescar_cats_cfg()
        self._rebuild_mesas_cfg()
        sc = self.root.get_screen("config")
        if not sc._campos_encadenados:
            encadenar_campos(
                sc.ids.campo_prod_nombre,
                sc.ids.campo_prod_precio,
                on_ultimo=self.agregar_producto_cfg,
            )
            sc._campos_encadenados = True
        self.set_config_tab("menu")
        self.go_to("config")

    def set_config_tab(self, tab):
        """Cambia entre las dos sub-vistas de Configuracion (Menu /
        Operativa). Reemplaza al viejo ScrollView unico: cada sub-vista
        ahora ocupa exactamente el espacio disponible entre el header y
        el nav inferior, sin desbordarse ni requerir scroll de pagina."""
        if tab not in ("menu", "operativa"):
            return
        self.config_tab = tab
        sc = self.root.get_screen("config")
        sc.ids.sm_config.current = tab

    # ── INICIO ────────────────────────────────────────────────────────────────
    def refrescar_mesas(self, *_):
        """Actualiza el grid de mesas de la pantalla de inicio.

        OPTIMIZACION: antes, cada llamada hacia grid.clear_widgets() y
        reconstruia las N tarjetas desde cero -- BoxLayout, instrucciones
        de canvas (Color/RoundedRectangle) y labels nuevos en CADA
        llamada. Este metodo se dispara muy seguido (cada pedido que
        entra, se cobra, se edita o se elimina -- incluidas las comandas
        que llegan cada pocos segundos desde el navegador de los meseros,
        via procesar_pedido_entrante), asi que reconstruir TODO cada vez
        generaba trabajo de layout y basura (garbage collection) de
        sobra, notorio en celulares de gama baja.

        Ahora se guarda cada tarjeta ya construida en self._tarjetas_mesa
        (nombre -> {"card": widget, "estado": (ocupada, empleado)}) y se
        reutiliza tal cual mientras su estado no haya cambiado desde el
        refresco anterior. Solo se reconstruye (via
        _construir_tarjeta_mesa) la tarjeta de una mesa cuando de verdad
        cambio algo en ella (se ocupo, se libero, o cambio el empleado
        que atiende) o cuando es la primera vez que se ve esa mesa. El
        orden de insercion en el grid se mantiene identico al original
        (se limpia y se vuelve a llenar en el orden de self.mesas), asi
        que no hay riesgo de alterar el acomodo visual -- lo unico que
        cambia es que reutilizar una tarjeta sin cambios es mucho mas
        barato que crearla de nuevo."""
        sc   = self.root.get_screen("inicio")
        grid = sc.ids.grid_mesas
        _checkpoint(f"refrescar_mesas: inicio ({len(self.mesas)} mesas a construir/reutilizar)")

        if not hasattr(self, "_tarjetas_mesa"):
            self._tarjetas_mesa = {}  # nombre_mesa -> {"card":.., "estado":..}

        pedidos_mesa = {p["mesa"]: p for p in self.pedidos if p.get("tipo") == "mesa"}
        ocupadas = set(pedidos_mesa.keys())

        # Se descartan del cache las mesas que ya no existen (se borraron
        # en Configuracion), para no acumular memoria con tarjetas huerfanas.
        mesas_actuales = set(self.mesas)
        for nombre_vieja in list(self._tarjetas_mesa.keys()):
            if nombre_vieja not in mesas_actuales:
                self._tarjetas_mesa.pop(nombre_vieja)

        grid.clear_widgets()  # solo desprende los widgets del grid, NO los
                              # destruye -- los que se reutilizan abajo
                              # siguen intactos y se vuelven a colgar tal cual.
        for mesa in self.mesas:
            ocup = mesa in ocupadas
            emp_mesa = pedidos_mesa.get(mesa, {}).get("empleado") if ocup else None
            estado_nuevo = (ocup, emp_mesa)

            info = self._tarjetas_mesa.get(mesa)
            if info is None or info["estado"] != estado_nuevo:
                card = self._construir_tarjeta_mesa(mesa, ocup, emp_mesa)
                self._tarjetas_mesa[mesa] = {"card": card, "estado": estado_nuevo}
            else:
                card = info["card"]  # sin cambios: se reutiliza tal cual

            grid.add_widget(card)

    def _construir_tarjeta_mesa(self, mesa, ocup, emp_mesa):
        """Crea el widget de UNA tarjeta de mesa, ahora como MDCard real
        (elevacion + radius de KivyMD) en vez del BoxLayout + canvas.before
        manual de antes. Extraido de refrescar_mesas() para poder llamarlo
        solo cuando de verdad hace falta (mesa nueva o con estado
        distinto), en vez de para las N mesas en cada refresco -- ver el
        comentario de refrescar_mesas()."""
        # Estilo sobre la foto de referencia (mesa ocupada): tarjeta de
        # color SOLIDO (sin capa translucida ni borde en Oscuro
        # clasico/Rojo Fuego), esquinas bien redondeadas, titulo en
        # blanco/contraste, boton "Ver Pedido" como pildora DORADA con
        # texto oscuro (DORADO como relleno, con su propio texto
        # contrastado, siempre es seguro). El estado "Ocupada"/"Libre"
        # usa el sistema de contraste existente contra el fondo real de
        # la tarjeta (no un color fijo), para garantizar legibilidad en
        # los 5 temas.
        # EXCEPCION visual pedida: en los temas reales "Azul Aqua" y
        # "Neutro", ocupada ademas lleva una capa blanca traslucida
        # encima del OSCURO (ver mas abajo, card._capa) -- los otros 2
        # temas (Oscuro clasico, Rojo Fuego) se quedan con el OSCURO
        # solido.
        bg_tarjeta = self.OSCURO
        txt_tarjeta = self.texto_contraste(self.OSCURO)
        # Fondo efectivo de la tarjeta ocupada: en Azul Aqua/Neutro se le
        # agrega encima una capa blanca translucida (ver canvas.after mas
        # abajo, card._capa) que aclara el color real que ve el usuario --
        # el contraste de "Ocupada" debe calcularse contra ESE fondo
        # resultante, no contra el OSCURO puro de debajo.
        if ocup and self.tema_actual in ("Azul Aqua", "Neutro"):
            bg_efectivo_estado = [bg_tarjeta[0]*0.65 + 0.35,
                                   bg_tarjeta[1]*0.65 + 0.35,
                                   bg_tarjeta[2]*0.65 + 0.35, 1]
        else:
            bg_efectivo_estado = bg_tarjeta
        color_estado = self.texto_contraste(bg_efectivo_estado) if ocup else _verde_contraste(self.OSCURO)
        radio = dp(18)

        # La mesa OCUPADA crece un poco respecto a la LIBRE (pedido
        # explicito): un poco mas de alto para acomodar el estado
        # "Ocupada" + el boton "Ver Pedido" con aire, y un poco mas todavia
        # si ademas hay un empleado asignado (linea extra "Atiende: ...").
        if ocup:
            altura = dp(118) + (dp(16) if emp_mesa else 0)
        else:
            altura = dp(100)
        # MDCard ya trae su propio fondo redondeado + sombra via
        # md_bg_color/radius/elevation -- ya NO se dibuja un RoundedRectangle
        # a mano como antes (card._bg desaparece). Solo se conservan a mano
        # la capa translucida (card._capa) y el borde de "libre" (card._borde),
        # porque MDCard no trae eso de fabrica.
        card = MDCard(
            orientation="vertical",
            size_hint_y=None,
            height=altura,
            padding=dp(12),
            spacing=dp(5),
            radius=[radio],
            # elevation=0: en este entorno (KivyMD 2.x sobre Android/Pydroid)
            # la sombra de MDCard a veces no logra dibujar el blur real y en
            # vez de eso pinta un rectangulo SOLIDO NEGRO detras/debajo de
            # toda la tarjeta. Se desactiva por completo.
            elevation=0,
            # md_bg_color se deja TRANSPARENTE a proposito: en las pruebas,
            # el "theme_bg_color=Custom" + "md_bg_color" de MDCard NO
            # pintaba el color correcto cuando la tarjeta se crea desde
            # Python puro (a diferencia de una MDCard declarada en KV, que
            # si funciona). En vez de seguir peleando con el sistema de
            # theming de KivyMD, se apaga su fondo por completo y se dibuja
            # el fondo A MANO abajo (card._fondo, canvas.before), igual que
            # ya se hace de forma confiable con el borde verde (card._borde)
            # y la capa translucida (card._capa).
            theme_bg_color="Custom",
            md_bg_color=[0, 0, 0, 0],
        )
        with card.canvas.before:
            Color(*bg_tarjeta)
            card._fondo = RoundedRectangle(pos=card.pos, size=card.size, radius=[radio])
        with card.canvas.after:
            card._capa = None
            # Pedido explicito: solo en los temas reales "Azul Aqua" y
            # "Neutro", las mesas ocupadas se cubren con una capa blanca
            # TRASLUCIDA encima del OSCURO del tema (asi se ve la foto de
            # referencia: un azul apagado/grisaceo, no el azul puro). Los
            # otros 2 temas se quedan con el OSCURO solido tal cual, sin capa.
            if ocup and self.tema_actual in ("Azul Aqua", "Neutro"):
                Color(1, 1, 1, 0.35)
                card._capa = RoundedRectangle(pos=card.pos, size=card.size, radius=[radio])
            card._borde = None
            if not ocup:
                Color(*(color_estado[:3] + [1]))
                card._borde = Line(rounded_rectangle=[card.x, card.y, card.width, card.height, radio],
                                    width=dp(1.3))
        def _sync_bg(w, v):
            if w._fondo is not None:
                w._fondo.pos = w.pos
                w._fondo.size = w.size
            if w._capa is not None:
                w._capa.pos = w.pos
                w._capa.size = w.size
            if w._borde is not None:
                w._borde.rounded_rectangle = [w.x, w.y, w.width, w.height, radio]
        card.bind(pos=_sync_bg, size=_sync_bg)

        card.add_widget(lbl(
            f"[b]{mesa}[/b]", markup=True, halign="center", color=txt_tarjeta,
            size_hint_y=None, height=dp(26), font_size="16sp",
        ))
        card.add_widget(lbl(
            "Ocupada" if ocup else "Libre",
            color=color_estado, bold=True,
            font_size="12sp", halign="center",
            size_hint_y=None, height=dp(18),
        ))
        if emp_mesa:
            card.add_widget(lbl(
                f"Atiende: {emp_mesa}",
                color=txt_tarjeta[:3] + [0.55],
                font_size="10sp", halign="center",
                size_hint_y=None, height=dp(16),
            ))

        m = mesa
        if ocup:
            # El boton "Ver Pedido" (MDRaisedButton) se auto-ajusta a su
            # propio texto en vez de respetar size_hint_x (comportamiento
            # documentado de los botones "viejos" de KivyMD) -- por eso
            # antes se salia por la izquierda de la tarjeta, encimandose
            # con la mesa de al lado en el grid. Arreglo: el boton va
            # DENTRO de un BoxLayout normal (contenedor) que ocupa el
            # ancho completo disponible de la tarjeta (size_hint=(1,None)),
            # y se liga (bind) el tamano/posicion del boton al del
            # contenedor -- tanto al crearlo como cada vez que el boton
            # intente cambiar su propio tamano por su cuenta -- para que
            # nunca pueda salirse de los limites de SU tarjeta.
            contenedor_btn = BoxLayout(
                size_hint=(1, None), height=dp(40),
            )
            btn_ver = MDRaisedButton(
                text="Ver Pedido", md_bg_color=self.DORADO,
                theme_text_color="Custom", text_color=self.texto_contraste(self.DORADO),
                size_hint=(None, None), font_size="11sp",
                elevation=1,
            )

            def _fijar_boton_al_contenedor(cont, btn):
                def _ajustar(*_):
                    btn.size = cont.size
                    btn.pos = cont.pos
                cont.bind(size=_ajustar, pos=_ajustar)
                btn.bind(size=_ajustar, pos=_ajustar)
                _ajustar()

            _fijar_boton_al_contenedor(contenedor_btn, btn_ver)
            btn_ver.bind(on_release=lambda inst, m=m: self._ver_pedido_mesa(m))
            contenedor_btn.add_widget(btn_ver)
            card.add_widget(contenedor_btn)
        else:
            # Tocar la card completa pregunta cuantas personas hay
            # antes de abrir el pedido (se guarda en estadisticas)
            card.bind(on_touch_down=lambda w, t, m=m:
                self._preguntar_personas_mesa(m) if w.collide_point(*t.pos) else None)

        return card

    # ── IMPRESION TERMICA (ESC/POS) ──────────────────────────────────────────
    def _impresora_activa(self):
        """True = impresora 'encendida' en Configuracion (se muestran
        todas las pantallas/opciones de impresion, aunque el hardware no
        este conectado). False = 'apagada': se ocultan esas opciones en
        toda la app para no generar clics inutiles, y ademas no se
        intenta mandar nada a imprimir (ni siquiera el .txt de modo
        prueba). Por default queda encendida, para no cambiarle el
        comportamiento a nadie que ya tenia la app configurada."""
        return self._leer_config("impresora_activa", "1") == "1"

    def _set_impresora_activa(self, activa):
        self._guardar_config("impresora_activa", "1" if activa else "0")

    def _leer_config_impresora(self):
        """Regresa (tipo, ancho, ip). tipo: 'bluetooth' o 'wifi'.
        ancho: '58' u '80'. ip: solo aplica si tipo == 'wifi'."""
        tipo  = self._leer_config("impresora_tipo", "bluetooth")
        ancho = self._leer_config("impresora_ancho", "58")
        ip    = self._leer_config("impresora_ip", "")
        return tipo, ancho, ip

    def _guardar_config_impresora(self, tipo=None, ancho=None, ip=None, mac=None):
        if tipo is not None:
            self._guardar_config("impresora_tipo", tipo)
        if ancho is not None:
            self._guardar_config("impresora_ancho", ancho)
        if ip is not None:
            self._guardar_config("impresora_ip", ip)
        if mac is not None:
            self._guardar_config("impresora_bt_mac", mac)

    def _pedir_permisos_bluetooth(self, callback_ok, incluir_scan=False):
        """Pide 'Dispositivos cercanos' (BLUETOOTH_CONNECT / BLUETOOTH_SCAN)
        en Android 12+. En PC (platform != 'android') no hace nada y sigue
        directo.

        OJO -- Pydroid 3 instalado en un celular real TAMBIEN reporta
        platform == 'android' (es Android de verdad), asi que ese chequeo
        NO alcanza para detectarlo. La diferencia real es que Pydroid corre
        sobre SU PROPIA PythonActivity (no la que genera python-for-android
        al compilar con buildozer), y esa PythonActivity no expone la
        interfaz Java PythonActivity$PermissionsCallback que necesita
        request_permissions()/check_permission() -- truenan con
        jnius.jnius.JavaException ('...is not visible from class loader').
        Por eso TODO el bloque de permisos va envuelto en try/except: en
        vez de tronar la app, se degrada a 'seguir sin pedir permiso' y
        deja que las llamadas reales a Bluetooth (listar_emparejados,
        escanear_cercanos, ImpresoraBluetoothManager.enviar), que ya
        tienen su propio try/except, sean las que reporten el error en la
        UI sin cerrar la app. En el APK compilado con buildozer esto NUNCA
        entra al except -- ahi si existe la interfaz y el flujo normal de
        permisos funciona igual que siempre."""
        from kivy.utils import platform
        if platform != "android":
            callback_ok(); return
        try:
            from android.permissions import request_permissions, check_permission, Permission
            permisos = [getattr(Permission, "BLUETOOTH_CONNECT", "android.permission.BLUETOOTH_CONNECT")]
            if incluir_scan:
                permisos.append(getattr(Permission, "BLUETOOTH_SCAN", "android.permission.BLUETOOTH_SCAN"))
            faltan = [p for p in permisos if not check_permission(p)]
        except Exception as e:
            print(f"[Bluetooth] check_permission no disponible en este entorno "
                  f"(probable Pydroid 3): {e}")
            callback_ok(); return
        if not faltan:
            callback_ok(); return
        def _resultado(perms, resultados):
            if all(resultados):
                callback_ok()
            else:
                Clock.schedule_once(lambda dt: _snack("Se requieren permisos de Bluetooth"))
        try:
            request_permissions(faltan, _resultado)
        except Exception as e:
            print(f"[Bluetooth] request_permissions no disponible en este entorno "
                  f"(Pydroid 3 no expone PermissionsCallback): {e}")
            Clock.schedule_once(lambda dt: _snack(
                "Bluetooth real necesita el APK compilado; en Pydroid 3 "
                "no se pueden pedir permisos -- sigue en modo prueba"))
            callback_ok()

    def vincular_impresora_bluetooth(self, mac, nombre=""):
        """Guarda la MAC SOLO cuando el usuario la elige a mano en el
        selector de Configuracion. Nunca se llama automaticamente."""
        self._guardar_config_impresora(tipo="bluetooth", mac=mac)
        _snack(f"Impresora vinculada: {nombre or mac}")
        self._impresora_bt.iniciar_vigilancia()  # arranca a cuidarla de una vez

    def _popup_elegir_impresora_bluetooth(self):
        """Selector visual: primero muestra los equipos YA emparejados en
        Ajustes de Android (no requiere escaneo ni permiso de ubicacion);
        incluye un boton 'Buscar impresoras nuevas' como respaldo, que
        pide BLUETOOTH_SCAN y hace un escaneo real de 8 segundos."""
        content = BoxLayout(orientation="vertical", padding=dp(14), spacing=dp(8),
                            size_hint_y=None)
        content.bind(minimum_height=content.setter("height"))
        content.add_widget(lbl("[b]ELEGIR IMPRESORA BLUETOOTH[/b]", markup=True,
                               color=self.texto_contraste(self.OSCURO), font_size="15sp",
                               halign="center", size_hint_y=None, height=dp(28)))

        lista = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(6))
        lista.bind(minimum_height=lista.setter("height"))

        scroll = ScrollView(size_hint=(1, None), height=dp(280))
        scroll.add_widget(lista)
        content.add_widget(scroll)

        estado_lbl = lbl("", color=_texto_contraste(self.OSCURO)[:3] + [0.6],
                         font_size="12sp", size_hint_y=None, height=dp(20),
                         halign="center")
        content.add_widget(estado_lbl)

        popup = Popup(title="", separator_height=0, content=content,
                      size_hint=(0.88, None), height=dp(440),
                      background_color=self.OSCURO)

        def _fila_dispositivo(nombre, mac):
            b = btn_flat(f"{nombre}\n{mac}", color=_texto_contraste(self.OSCURO),
                        font_size="12sp", size_hint_y=None, height=dp(48))
            _set_bg(b, self.OSCURO, radius=dp(8))
            b.bind(on_press=lambda *_: (popup.dismiss(),
                                        self.vincular_impresora_bluetooth(mac, nombre)))
            return b

        def _cargar_emparejados():
            from kivy.utils import platform
            if platform != "android":
                estado_lbl.text = "Bluetooth solo disponible en el celular"
                return
            def _hacerlo():
                try:
                    dispositivos = self._impresora_bt.listar_emparejados()
                except Exception as e:
                    # OJO: 'e' se borra solo al salir de este bloque except
                    # (limpieza automatica de Python 3). El lambda de abajo
                    # corre despues, via Clock, en otro tick -- si capturara
                    # 'e' directo tronaria con NameError. Por eso se congela
                    # el mensaje en un str ANTES de agendar el callback.
                    mensaje_error = str(e)
                    Clock.schedule_once(lambda dt: setattr(estado_lbl, "text", f"Error: {mensaje_error}"))
                    return
                def _pintar(dt):
                    lista.clear_widgets()
                    if not dispositivos:
                        estado_lbl.text = "Sin equipos emparejados. Vincula tu impresora en Ajustes > Bluetooth primero."
                        return
                    estado_lbl.text = "Toca tu impresora para vincularla"
                    for nombre, mac in dispositivos:
                        lista.add_widget(_fila_dispositivo(nombre, mac))
                Clock.schedule_once(_pintar)
            self._pedir_permisos_bluetooth(lambda: threading.Thread(target=_hacerlo, daemon=True).start())

        def _buscar_nuevas(*_):
            from kivy.utils import platform
            if platform != "android":
                # Modo Simulacion (PC/Pydroid): no hay adaptador Bluetooth
                # real que escanear -- se avisa y se sale, sin tronar.
                estado_lbl.text = "Busqueda de equipos nuevos solo disponible en el celular"
                return

            estado_lbl.text = "Buscando equipos cercanos (8s)..."

            def _al_encontrar(nombre, mac):
                lista.add_widget(_fila_dispositivo(nombre, mac))

            def _al_terminar():
                estado_lbl.text = "Busqueda terminada"

            def _lanzar_escaneo():
                try:
                    self._impresora_bt.escanear_cercanos(_al_encontrar, _al_terminar, segundos=8)
                except Exception as e:
                    # Blindaje final: cualquier fallo de hardware/permiso
                    # a medio conceder se queda en la UI, nunca tumba la app.
                    estado_lbl.text = f"No se pudo escanear: {e}"

            # BLUETOOTH_SCAN es obligatorio en Android 12+ para
            # startDiscovery(); sin pedirlo antes, el SO respondia con
            # SecurityException y la app se cerraba de golpe al tocar
            # este boton.
            self._pedir_permisos_bluetooth(_lanzar_escaneo, incluir_scan=True)

        b_buscar = btn_raised("BUSCAR IMPRESORAS NUEVAS", bg=self.ACCENT,
                              size_hint_y=None, height=dp(42), font_size="12sp")
        b_buscar.bind(on_press=_buscar_nuevas)
        content.add_widget(b_buscar)

        b_cerrar = btn_flat("Cerrar", color=_texto_contraste(self.OSCURO),
                            size_hint_y=None, height=dp(38))
        b_cerrar.bind(on_press=lambda *_: popup.dismiss())
        content.add_widget(b_cerrar)

        popup.open()
        _cargar_emparejados()

    def _lineas_pie_negocio(self, ancho):
        """Arma las lineas de pie de ticket -- direccion, datos para
        transferencia y mensaje de agradecimiento -- a partir de
        self.info_negocio. MISMA fuente que usan el ticket ESC/POS real
        (_construir_ticket_cliente_escpos), el ticket visual para Galeria
        (_construir_ticket_widget, en su propia version con Labels) y la
        Vista Previa (_get_texto_prueba), asi los tres coinciden siempre.

        Todos los campos son opcionales: cada bloque solo aparece si el
        usuario cargo esa informacion en Configuracion > Personalizacion >
        Informacion del negocio y ticket. Si el mensaje de agradecimiento
        quedo vacio, se usa el mismo texto por defecto que tenia el ticket
        antes de que existiera esta seccion, asi ningun ticket viejo (ni
        uno nuevo sin configurar nada) cambia de aspecto.

        'ancho' es el ancho en CARACTERES (igual que _centrar_texto/
        _separador_texto), no en dp -- se usa tal cual para ESC/POS y
        Vista Previa; _construir_ticket_widget dibuja su propia version
        con Label porque ahi el ancho es en dp, no en caracteres."""
        info = self.info_negocio
        lineas = []

        if info.get("direccion"):
            lineas.append(_centrar_texto(_sin_acentos(info["direccion"]), ancho))

        datos_pago = [k for k in ("banco", "cuenta", "titular") if info.get(k)]
        if datos_pago:
            lineas.append(_separador_texto(ancho))
            lineas.append(_centrar_texto("DATOS PARA TRANSFERENCIA", ancho))
            if info.get("banco"):
                lineas.append(_centrar_texto(f"Banco: {_sin_acentos(info['banco'])}", ancho))
            if info.get("cuenta"):
                lineas.append(_centrar_texto(f"Cuenta/CLABE: {info['cuenta']}", ancho))
            if info.get("titular"):
                lineas.append(_centrar_texto(f"Titular: {_sin_acentos(info['titular'])}", ancho))
        if info.get("telefono"):
            lineas.append(_centrar_texto(f"Enviar comprobante al: {info['telefono']}", ancho))

        lineas.append(_separador_texto(ancho))
        mensaje = info.get("mensaje_agradecimiento") or "Gracias por su preferencia"
        lineas.append(_centrar_texto(_sin_acentos(mensaje), ancho))
        return lineas

    def _construir_ticket_cliente_escpos(self, encabezado_lineas, items, total):
        """Version ESC/POS (texto para impresora fisica) del mismo ticket
        que _construir_ticket_widget dibuja como imagen para Galeria."""
        _, ancho_papel, _ = self._leer_config_impresora()
        ancho = _ANCHO_CHARS.get(ancho_papel, 32)

        partes = [_ESC_INIT, _ESC_ALIGN_CEN, _ESC_BOLD_ON]
        nombre_limpio = self.nombre_taqueria.replace("[b]", "").replace("[/b]", "")
        partes.append((_sin_acentos(nombre_limpio) + "\n").encode("ascii", "replace"))
        partes.append(_ESC_BOLD_OFF)
        for linea in encabezado_lineas:
            partes.append((_centrar_texto(linea, ancho) + "\n").encode("ascii", "replace"))

        partes.append(_ESC_ALIGN_IZQ)
        partes.append((_separador_texto(ancho) + "\n").encode("ascii"))

        for it in items:
            qty  = it.get("qty", 1)
            subt = it["precio"] * qty
            izq  = f"{qty}x {it['nombre']}"
            der  = f"${subt:.0f}"
            partes.append((_linea_dos_columnas(izq, der, ancho) + "\n").encode("ascii", "replace"))

        partes.append((_separador_texto(ancho) + "\n").encode("ascii"))
        partes.append(_ESC_BOLD_ON)
        partes.append((_linea_dos_columnas("TOTAL", f"${total:.0f}", ancho) + "\n").encode("ascii", "replace"))
        partes.append(_ESC_BOLD_OFF)
        partes.append(_ESC_ALIGN_CEN)
        for linea in self._lineas_pie_negocio(ancho):
            partes.append((linea + "\n").encode("ascii", "replace"))
        partes.append(_ESC_CORTE)
        return b"".join(partes)

    def _construir_comanda_cocina_escpos(self, mesa, nombre_cliente, mesero, items):
        """Comanda para cocina: encabezado con mesa/hora/cliente/mesero,
        platillos (categoria 'Comida') en letra grande y negrita porque
        son prioridad para el chef, y bebidas/postres/otros abajo en
        negrita normal. mesa=None se interpreta como pedido a domicilio."""
        _, ancho_papel, _ = self._leer_config_impresora()
        ancho = _ANCHO_CHARS.get(ancho_papel, 32)
        ahora = datetime.now().strftime("%H:%M")

        # Mismo truco que _registrar_venta_db usa para saber la categoria
        # de cada producto a partir de su id.
        prod_cat = {}
        for cat, prods in self.menu.items():
            for p in prods:
                prod_cat[p["id"]] = cat

        comida = [it for it in items if prod_cat.get(it.get("id", ""), "Otros") == "Comida"]
        resto  = [it for it in items if prod_cat.get(it.get("id", ""), "Otros") != "Comida"]

        partes = [_ESC_INIT, _ESC_ALIGN_IZQ, _ESC_BOLD_ON]

        txt_mesa = f"Mesa: {mesa}" if mesa else "DOMICILIO"
        partes.append((_linea_dos_columnas(txt_mesa, f"Hora: {ahora}", ancho) + "\n").encode("ascii", "replace"))

        txt_cliente = f"Cliente: {nombre_cliente}" if nombre_cliente else "Cliente: -"
        txt_mesero  = f"Mesero: {mesero}" if mesero else "Mesero: -"
        partes.append((_linea_dos_columnas(txt_cliente, txt_mesero, ancho) + "\n").encode("ascii", "replace"))
        partes.append(_ESC_BOLD_OFF)

        partes.append((_separador_texto(ancho) + "\n").encode("ascii"))

        # ── Comida: prioridad para el chef -- letra grande y negrita ──
        partes.append(_ESC_GRANDE_ON)
        partes.append(_ESC_BOLD_ON)
        if comida:
            for it in comida:
                qty = it.get("qty", 1)
                partes.append((f"x{qty} {_sin_acentos(it['nombre'])}\n").encode("ascii", "replace"))
                nota = (it.get("_nota") or "").strip()
                if nota:
                    # La nota se imprime en letra NORMAL (se apaga
                    # _ESC_GRANDE momentaneamente) para que no compita en
                    # tamano con el nombre del platillo, pero se deja en
                    # negrita y con '>>' para que el chef la note de
                    # inmediato aunque sea mas chica. Se vuelve a prender
                    # GRANDE justo despues para el siguiente platillo.
                    partes.append(_ESC_GRANDE_OFF)
                    partes.append((f"  >> {_sin_acentos(nota)}\n").encode("ascii", "replace"))
                    partes.append(_ESC_GRANDE_ON)
        else:
            partes.append(b"(sin platillos)\n")
        partes.append(_ESC_GRANDE_OFF)
        partes.append(_ESC_BOLD_OFF)

        partes.append(b"\n")

        # ── Bebidas / postres / otros: secundario, negrita normal ──
        partes.append(_ESC_BOLD_ON)
        if resto:
            for it in resto:
                qty = it.get("qty", 1)
                partes.append((f"{qty}x {_sin_acentos(it['nombre'])}\n").encode("ascii", "replace"))
                nota = (it.get("_nota") or "").strip()
                if nota:
                    partes.append((f"  >> {_sin_acentos(nota)}\n").encode("ascii", "replace"))
        partes.append(_ESC_BOLD_OFF)

        partes.append((_separador_texto(ancho) + "\n").encode("ascii"))
        partes.append(_ESC_CORTE)
        return b"".join(partes)

    def _enviar_a_impresora(self, datos_bytes, etiqueta="ticket"):
        """Punto UNICO por donde pasa cualquier impresion (ticket cliente,
        comanda de cocina, apertura de cajon). Bluetooth va por
        ImpresoraBluetoothManager (requiere Android real, pyjnius).
        WiFi va por ImpresoraWifiManager -- a diferencia de Bluetooth, un
        socket TCP normal SI funciona igual en PC/Pydroid que en el APK
        compilado, asi que no hace falta el chequeo de platform=='android'
        aqui: si hay una IP configurada, se intenta de verdad tambien
        durante pruebas en escritorio."""
        tipo, ancho, ip = self._leer_config_impresora()

        if tipo == "bluetooth":
            from kivy.utils import platform
            if platform != "android":
                self._guardar_prueba_txt(datos_bytes, etiqueta, tipo, ancho, ip)
                return

            def _hacerlo():
                self._impresora_bt.enviar(
                    datos_bytes,
                    callback_ok=lambda: _snack("Ticket enviado a la impresora"),
                    callback_error=lambda msg: _snack(msg),
                )
            self._pedir_permisos_bluetooth(_hacerlo)
            return

        if tipo == "wifi":
            if not ip:
                # Sin IP configurada todavia -- ni vale la pena intentar
                # conectar, se degrada directo a modo prueba como antes.
                self._guardar_prueba_txt(datos_bytes, etiqueta, tipo, ancho, ip)
                return
            self._impresora_wifi.enviar(
                ip, datos_bytes,
                callback_ok=lambda: _snack("Ticket enviado a la impresora"),
                callback_error=lambda msg: _snack(msg),
            )
            return

        # Cualquier otro tipo no manejado todavia: modo prueba.
        self._guardar_prueba_txt(datos_bytes, etiqueta, tipo, ancho, ip)

    def _guardar_prueba_txt(self, datos_bytes, etiqueta, tipo, ancho, ip):
        """Respaldo de depuracion (PC/Pydroid, o impresora WiFi todavia sin
        implementar): guarda lo que se hubiera impreso en un .txt."""
        try:
            carpeta = os.path.join(os.path.dirname(self._db_path()), "impresiones_prueba")
            os.makedirs(carpeta, exist_ok=True)
            nombre = f"{etiqueta}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            ruta = os.path.join(carpeta, nombre)
            legible = datos_bytes.decode("ascii", errors="ignore")
            legible = "".join(ch for ch in legible if ch.isprintable() or ch == "\n")
            with open(ruta, "w", encoding="utf-8") as f:
                f.write(f"[MODO PRUEBA] impresora configurada: {tipo} / papel {ancho}mm"
                        + (f" / ip {ip}" if tipo == "wifi" and ip else "") + "\n")
                f.write(legible)
            _snack("Ticket listo (modo prueba, sin impresora conectada)")
        except Exception as e:
            print("Error en _guardar_prueba_txt:", e)
            _snack("No se pudo generar el ticket de prueba")

    def imprimir_ticket_cliente(self, encabezado_lineas, items, total):
        if not items:
            _snack("No hay items para imprimir")
            return
        if not self._impresora_activa():
            # Impresora apagada en Configuracion: no se intenta nada, ni
            # siquiera el .txt de modo prueba.
            return
        datos = self._construir_ticket_cliente_escpos(encabezado_lineas, items, total)
        self._enviar_a_impresora(datos, etiqueta="ticket_cliente")

    def imprimir_comanda_cocina(self, mesa, nombre_cliente, mesero, items):
        if not items:
            return
        if not self._impresora_activa():
            return
        datos = self._construir_comanda_cocina_escpos(mesa, nombre_cliente, mesero, items)
        self._enviar_a_impresora(datos, etiqueta="comanda_cocina")

    # ── VISTA PREVIA DE IMPRESION (solo visual/pruebas) ─────────────────────
    # Reusa a proposito los MISMOS helpers de formato que ya usan
    # _construir_ticket_cliente_escpos / _construir_comanda_cocina_escpos
    # (_ANCHO_CHARS, _linea_dos_columnas, _centrar_texto, _separador_texto):
    # asi el texto que se ve en el Popup es identico, caracter por
    # caracter, al que de verdad sale hacia el ESC/POS -- no una version
    # aparte que se pueda desincronizar del formato real.
    def _get_texto_prueba(self, tipo="ticket"):
        """Texto de ejemplo (NO toca self.pedidos ni la base de datos) para
        la Vista Previa. Lee el ancho de papel configurado EN ESE MOMENTO
        -- cada llamada relee _leer_config_impresora(), asi que si el
        usuario cambio 58<->80mm no hace falta reiniciar nada."""
        _, ancho_papel, _ = self._leer_config_impresora()
        ancho = _ANCHO_CHARS.get(ancho_papel, 32)

        items_prueba = [
            {"nombre": "Taco de birria", "precio": 35, "qty": 3},
            {"nombre": "Consome chico", "precio": 20, "qty": 1},
            {"nombre": "Refresco 600ml", "precio": 25, "qty": 2},
        ]
        total = sum(i["precio"] * i["qty"] for i in items_prueba)

        lineas = []
        nombre_limpio = self.nombre_taqueria.replace("[b]", "").replace("[/b]", "")
        lineas.append(_centrar_texto(nombre_limpio, ancho))
        etiqueta_tipo = "COMANDA DE COCINA" if tipo == "comanda" else "TICKET DE VENTA"
        lineas.append(_centrar_texto(f"Ejemplo -- {etiqueta_tipo}", ancho))
        lineas.append(_centrar_texto(f"Papel {ancho_papel}mm ({ancho} car/linea)", ancho))
        lineas.append(_centrar_texto(datetime.now().strftime("%d/%m/%Y  %H:%M"), ancho))
        lineas.append(_separador_texto(ancho))
        for it in items_prueba:
            izq = f"{it['qty']}x {it['nombre']}"
            der = f"${it['precio'] * it['qty']:.0f}"
            lineas.append(_linea_dos_columnas(izq, der, ancho))
        lineas.append(_separador_texto(ancho))
        lineas.append(_linea_dos_columnas("TOTAL", f"${total:.0f}", ancho))
        lineas.append(_separador_texto(ancho))
        for linea_pie in self._lineas_pie_negocio(ancho):
            lineas.append(linea_pie)
        lineas.append(_separador_texto(ancho))
        lineas.append(_centrar_texto("Vista previa -- no es una venta real", ancho))
        return "\n".join(lineas)

    def _popup_vista_previa_impresion(self, tipo="ticket"):
        """Popup 'Ejemplo' de Configuracion > Impresora. Puramente visual:
        no crea pedidos, no llama a _registrar_venta_db, no toca
        self.pedidos -- solo arma un string de muestra y, si el usuario
        pide 'PROBAR IMPRESORA', lo manda por el mismo camino que un
        ticket real (_enviar_a_impresora), con su propia etiqueta para no
        mezclarse con los .txt de depuracion de ventas reales."""
        from kivy.core.window import Window

        _, ancho_papel, _ = self._leer_config_impresora()
        ancho_dp = _ANCHO_PAPEL_DP.get(ancho_papel, _ANCHO_PAPEL_DP["58"])
        texto = self._get_texto_prueba(tipo)

        contenido = BoxLayout(orientation="vertical", padding=dp(14), spacing=dp(10),
                              size_hint_y=None)
        contenido.bind(minimum_height=contenido.setter("height"))
        contenido.add_widget(lbl(f"[b]VISTA PREVIA -- {ancho_papel}mm[/b]", markup=True,
                                 color=self.texto_contraste(self.OSCURO), font_size="15sp", halign="center",
                                 size_hint_y=None, height=dp(26)))

        # ── "papel" simulado: ancho fijo proporcional al ancho real ──
        # IMPORTANTE: el ancho del Label es FIJO (size_hint_x=None + width +
        # text_size explicitos) desde su creacion. Asi el texture_size (y
        # por lo tanto la altura) se calcula bien desde el primer frame,
        # sin depender de que el layout del padre le reparta un ancho
        # despues -- esa dependencia tardia era la causa real de que el
        # texto se "encimara" (la altura se fijaba antes de saber el
        # ancho real de dibujo).
        papel = BoxLayout(orientation="vertical", size_hint=(None, None),
                          width=ancho_dp, padding=dp(8))
        papel.bind(minimum_height=papel.setter("height"))
        _set_bg(papel, [0.96, 0.96, 0.94, 1], radius=dp(4))  # blanco papel

        # font_name='RobotoMono' a secas truena (OSError) si esa fuente no
        # esta registrada de antemano -- ver _fuente_monoespaciada(). Si no
        # se encuentra ninguna .ttf monoespaciada instalada, se omite
        # font_name por completo y Kivy usa su fuente default: se pierde
        # el alineado perfecto de columnas, pero el Popup nunca truena.
        _kw_fuente = {}
        _fuente = _fuente_monoespaciada()
        if _fuente:
            _kw_fuente["font_name"] = _fuente

        etiqueta_ticket = Label(
            text=texto, font_size="11sp",
            color=[0.08, 0.08, 0.08, 1], halign="left", valign="top",
            markup=False, size_hint_y=None,
            size_hint_x=None, width=ancho_dp - dp(16),
            text_size=(ancho_dp - dp(16), None),
            **_kw_fuente,
        )
        etiqueta_ticket.bind(texture_size=lambda w, ts: setattr(w, "height", ts[1]))
        # Forzamos el calculo YA (no solo de forma reactiva): garantiza que
        # papel.height -- y todo lo que depende de el, abajo -- sea
        # correcto desde antes de abrir el Popup, sin esperar un frame extra.
        etiqueta_ticket.texture_update()
        etiqueta_ticket.height = etiqueta_ticket.texture_size[1]
        papel.add_widget(etiqueta_ticket)
        papel.do_layout()  # fuerza minimum_height/height correctos YA

        # ── Envoltura con scroll: alto dinamico segun el contenido ──
        # - 1 platillo -> papel chico -> el ScrollView (y el Popup) se
        #   achican con el, sin dejar hueco muerto abajo.
        # - 50 platillos -> papel mas alto que el 55% de la pantalla ->
        #   el ScrollView se topa en ese maximo y aparece scroll.
        ALTO_MAX_PAPEL = Window.height * 0.55
        alto_scroll_inicial = min(papel.height, ALTO_MAX_PAPEL)

        scroll_papel = ScrollView(size_hint=(None, None), width=ancho_dp,
                                  height=alto_scroll_inicial, do_scroll_x=False)
        envoltura = AnchorLayout(anchor_x="center", anchor_y="top", size_hint_y=None,
                                 height=alto_scroll_inicial)

        def _sync_alto_scroll(*_):
            alto = min(papel.height, Window.height * 0.55)
            scroll_papel.height = alto
            envoltura.height = alto
        papel.bind(height=_sync_alto_scroll)

        scroll_papel.add_widget(papel)
        envoltura.add_widget(scroll_papel)
        contenido.add_widget(envoltura)

        contenido.add_widget(lbl(
            f"Ancho configurado: {ancho_papel}mm  "
            f"({_ANCHO_CHARS.get(ancho_papel, 32)} caracteres/linea)",
            color=_texto_contraste(self.OSCURO)[:3] + [0.55], font_size="11sp",
            halign="center", size_hint_y=None, height=dp(20),
        ))

        botones = BoxLayout(orientation="horizontal", size_hint_y=None,
                            height=dp(44), spacing=dp(10))
        b_cerrar = btn_flat("Cerrar", color=_texto_contraste(self.OSCURO),
                            size_hint_y=None, height=dp(40))
        b_probar = btn_raised("PROBAR IMPRESORA", bg=self.ACCENT,
                              size_hint_y=None, height=dp(40), font_size="12sp")

        def _probar(*_):
            # Mismo string que se ve en pantalla (WYSIWYG) -- se envuelve
            # con los mismos comandos ESC/POS de init/corte que usa el
            # resto de la app, y pasa por _enviar_a_impresora() tal cual,
            # asi respeta bluetooth/wifi/modo-prueba segun lo configurado.
            # NO llama a _registrar_venta_db ni toca self.pedidos.
            datos = _ESC_INIT + _sin_acentos(texto).encode("ascii", "replace") + b"\n" + _ESC_CORTE
            self._enviar_a_impresora(datos, etiqueta="prueba_impresora")

        b_cerrar.bind(on_press=lambda *_: popup.dismiss())
        b_probar.bind(on_press=_probar)
        botones.add_widget(b_cerrar)
        botones.add_widget(b_probar)
        contenido.add_widget(botones)

        # ── Popup: alto TOTAL dinamico, tope en el 94% de la pantalla ──
        popup = Popup(title="", separator_height=0, content=contenido,
                      size_hint=(0.9, None), background_color=self.OSCURO)

        def _sync_alto_popup(*_):
            popup.height = min(contenido.height + dp(24), Window.height * 0.94)
        contenido.bind(minimum_height=_sync_alto_popup)
        scroll_papel.bind(height=_sync_alto_popup)
        _sync_alto_popup()

        popup.open()

    # ── VISTA PREVIA DE COMANDA DE COCINA (solo visual/pruebas) ─────────────
    # Fuentes por ancho de papel: mesa gigante, encabezados en negrita,
    # items legibles de un vistazo. 80mm usa exactamente los tamaños
    # pedidos (item 18sp); 58mm se reduce un poco para que quepa sin
    # desbordarse en un papel mas angosto.
    _FUENTE_COMANDA_POR_ANCHO = {
        "58": {"mesa": "24sp", "header": "16sp", "item": "15sp"},
        "80": {"mesa": "30sp", "header": "19sp", "item": "18sp"},
    }

    def _datos_prueba_comanda(self):
        """Datos fijos de ejemplo, YA divididos a mano en 'cocina' y
        'bebidas' -- a proposito NO dependen de self.menu ni de la
        categoria real de ningun producto (a diferencia de
        _construir_comanda_cocina_escpos, que si la necesita para un
        pedido real). Asi la demo se ve igual sin importar que tenga
        configurado el menu del negocio, y sirve tanto para pintar la
        Vista Previa en pantalla como para los bytes ESC/POS de 'PROBAR
        IMPRESORA' -- un solo lugar, ambos coinciden siempre."""
        return {
            "mesa": "5",
            "cliente": "Cliente ejemplo",
            "mesero": "Mesero demo",
            "hora": datetime.now().strftime("%H:%M"),
            "cocina": [
                {"nombre": "Taco de birria", "qty": 3},
                {"nombre": "Orden de consome", "qty": 1},
                {"nombre": "Quesotaco", "qty": 2},
            ],
            "bebidas": [
                {"nombre": "Refresco 600ml", "qty": 2},
                {"nombre": "Agua de horchata", "qty": 1},
            ],
        }

    def _construir_comanda_prueba_escpos(self, ancho_papel):
        """ESC/POS de la comanda de EJEMPLO -- mismo lenguaje de impresora
        que _construir_comanda_cocina_escpos() (mesa/negrita/letra grande
        para COCINA), pero con _datos_prueba_comanda() en vez de un pedido
        real, para que 'PROBAR IMPRESORA' sirva incluso sin ningun pedido
        activo. No toca self.pedidos ni la base de datos."""
        datos = self._datos_prueba_comanda()
        ancho = _ANCHO_CHARS.get(ancho_papel, 32)
        ahora = datos["hora"]

        partes = [_ESC_INIT, _ESC_ALIGN_CEN, _ESC_GRANDE_ON, _ESC_BOLD_ON]
        partes.append((f"MESA {datos['mesa']}\n").encode("ascii", "replace"))
        partes.append(_ESC_GRANDE_OFF)
        partes.append(_ESC_BOLD_OFF)
        partes.append(_ESC_ALIGN_IZQ)
        partes.append((_linea_dos_columnas(f"Cliente: {datos['cliente']}", f"Hora: {ahora}", ancho)
                       + "\n").encode("ascii", "replace"))
        partes.append((f"Mesero: {datos['mesero']}\n").encode("ascii", "replace"))
        partes.append((_separador_texto(ancho) + "\n").encode("ascii"))

        partes.append(_ESC_GRANDE_ON)
        partes.append(_ESC_BOLD_ON)
        partes.append(b"COCINA\n")
        for it in datos["cocina"]:
            partes.append((f"x{it['qty']} {_sin_acentos(it['nombre'])}\n").encode("ascii", "replace"))
        partes.append(_ESC_GRANDE_OFF)
        partes.append(_ESC_BOLD_OFF)
        partes.append(b"\n")

        partes.append(_ESC_BOLD_ON)
        partes.append(b"BEBIDAS\n")
        for it in datos["bebidas"]:
            partes.append((f"{it['qty']}x {_sin_acentos(it['nombre'])}\n").encode("ascii", "replace"))
        partes.append(_ESC_BOLD_OFF)

        partes.append((_separador_texto(ancho) + "\n").encode("ascii"))
        partes.append(_ESC_CORTE)
        return b"".join(partes)

    def _popup_vista_previa_comanda(self):
        """Vista previa 'para cocina' -- letra grande, negritas forzadas
        via markup [b][/b] y separacion clara MESA / COCINA / BEBIDAS,
        pensada para que el cocinero identifique el pedido de un vistazo.
        Puramente visual/pruebas: no crea pedidos, no toca self.pedidos
        ni la base de datos.

        A diferencia del ticket de cliente (un solo bloque monoespaciado),
        aqui se arma con varios Label por separado -- necesario para tener
        tamaños de letra distintos (mesa gigante, encabezados, items) en
        el mismo Popup. Ancho fijo = ancho_dp (58/80mm), igual que el
        ticket, con wrap automatico (text_size) para que un nombre de
        producto largo nunca se desborde del 'papel', solo baja de linea."""
        from kivy.core.window import Window

        _, ancho_papel, _ = self._leer_config_impresora()
        ancho_dp = _ANCHO_PAPEL_DP.get(ancho_papel, _ANCHO_PAPEL_DP["58"])
        fuentes = self._FUENTE_COMANDA_POR_ANCHO.get(ancho_papel, self._FUENTE_COMANDA_POR_ANCHO["58"])
        datos = self._datos_prueba_comanda()
        ancho_util = ancho_dp - dp(20)  # ancho_dp menos el padding horizontal del "papel"

        def _linea_comanda(texto_markup, font_size, color, height_min=dp(22)):
            """Crea una linea de la comanda con ANCHO FIJO desde su creacion
            (size_hint_x=None + width + text_size explicitos). Esto es lo
            que evita que el texto se encime: la altura (texture_size[1])
            se calcula ya mismo contra el ancho real de dibujo, no contra
            un ancho que el BoxLayout padre reparte un frame despues."""
            w = Label(
                text=texto_markup, markup=True, font_size=font_size, color=color,
                halign="left", valign="top",
                size_hint_y=None, size_hint_x=None, width=ancho_util,
                text_size=(ancho_util, None),
            )
            def _ajustar_alto(inst, ts):
                inst.height = max(height_min, ts[1] + dp(6))
            w.bind(texture_size=_ajustar_alto)
            # Calculo inmediato: la altura ya es correcta antes de que el
            # Popup se abra, sin esperar un frame extra ni encimarse con
            # el siguiente widget.
            w.texture_update()
            _ajustar_alto(w, w.texture_size)
            return w

        def _fila_producto(nombre, qty):
            # [b] para negritas -- resalta cada platillo de un vistazo.
            texto = f"[b]x{qty}  {_sin_acentos(nombre)}[/b]"
            return _linea_comanda(texto, fuentes["item"], [0.05, 0.05, 0.05, 1])

        contenido = BoxLayout(orientation="vertical", padding=dp(14), spacing=dp(10),
                              size_hint_y=None)
        contenido.bind(minimum_height=contenido.setter("height"))
        contenido.add_widget(lbl(f"[b]VISTA PREVIA -- COMANDA DE COCINA -- {ancho_papel}mm[/b]",
                                 markup=True, color=self.texto_contraste(self.OSCURO), font_size="15sp",
                                 halign="center", size_hint_y=None, height=dp(26)))

        papel = BoxLayout(orientation="vertical", size_hint=(None, None), width=ancho_dp,
                          padding=dp(10), spacing=dp(4))
        papel.bind(minimum_height=papel.setter("height"))
        _set_bg(papel, [1, 1, 1, 1], radius=dp(4))  # fondo blanco -- maximo contraste

        # ── Mesa: lo primero que ve el cocinero -- [b] + [size=] bien grande ──
        papel.add_widget(_linea_comanda(
            f"[b][size=28sp]MESA {_sin_acentos(str(datos['mesa']))}[/size][/b]",
            fuentes["mesa"], [0, 0, 0, 1], height_min=dp(46),
        ))
        # Esta linea de mesa usa halign="left" por defecto en _linea_comanda;
        # la centramos aparte porque es la unica que lo necesita:
        papel.children[0].halign = "center"

        papel.add_widget(_linea_comanda(
            f"{_sin_acentos(datos['cliente'])}   -   {_sin_acentos(datos['mesero'])}",
            "12sp", [0.3, 0.3, 0.3, 1],
        ))
        papel.children[0].halign = "center"

        papel.add_widget(_linea_comanda(
            f"[b]Hora: {datos['hora']}[/b]", "12sp", [0.3, 0.3, 0.3, 1],
        ))
        papel.children[0].halign = "center"

        separador = Widget(size_hint_y=None, height=dp(2))
        def _pintar_separador(w, *_):
            w.canvas.before.clear()
            with w.canvas.before:
                Color(0, 0, 0, 1)
                Rectangle(pos=w.pos, size=w.size)
        separador.bind(pos=_pintar_separador, size=_pintar_separador)
        papel.add_widget(separador)

        # ── Bloque COCINA: rojo/negrita/letra grande -- prioridad del chef ──
        papel.add_widget(_linea_comanda("[b]COCINA[/b]", fuentes["header"], [0.65, 0.05, 0.05, 1]))
        for it in datos["cocina"]:
            papel.add_widget(_fila_producto(it["nombre"], it["qty"]))

        papel.add_widget(Widget(size_hint_y=None, height=dp(10)))

        # ── Bloque BEBIDAS: azul/negrita -- secundario para el chef ──
        papel.add_widget(_linea_comanda("[b]BEBIDAS[/b]", fuentes["header"], [0.05, 0.3, 0.55, 1]))
        for it in datos["bebidas"]:
            papel.add_widget(_fila_producto(it["nombre"], it["qty"]))

        papel.do_layout()  # fuerza minimum_height/height correctos YA

        # ── Envoltura con scroll: alto dinamico segun cantidad de platillos ──
        # - 1 platillo -> papel chico -> ScrollView y Popup se achican con el.
        # - 50 platillos -> papel mas alto que el 55% de pantalla -> se topa
        #   ahi y aparece scroll, sin que ninguna linea se encime.
        alto_scroll_inicial = min(papel.height, Window.height * 0.55)

        scroll_papel = ScrollView(size_hint=(None, None), width=ancho_dp,
                                  height=alto_scroll_inicial, do_scroll_x=False)
        envoltura = AnchorLayout(anchor_x="center", anchor_y="top", size_hint_y=None,
                                 height=alto_scroll_inicial)

        def _sync_alto_scroll(*_):
            alto = min(papel.height, Window.height * 0.55)
            scroll_papel.height = alto
            envoltura.height = alto
        papel.bind(height=_sync_alto_scroll)

        scroll_papel.add_widget(papel)
        envoltura.add_widget(scroll_papel)
        contenido.add_widget(envoltura)

        contenido.add_widget(lbl(
            f"Ancho configurado: {ancho_papel}mm",
            color=_texto_contraste(self.OSCURO)[:3] + [0.55], font_size="11sp",
            halign="center", size_hint_y=None, height=dp(20),
        ))

        botones = BoxLayout(orientation="horizontal", size_hint_y=None,
                            height=dp(44), spacing=dp(10))
        b_cerrar = btn_flat("Cerrar", color=_texto_contraste(self.OSCURO),
                            size_hint_y=None, height=dp(40))
        b_probar = btn_raised("PROBAR IMPRESORA", bg=self.ACCENT,
                              size_hint_y=None, height=dp(40), font_size="12sp")

        def _probar(*_):
            # Reusa el mismo ancho_papel que ya se leyo al abrir el Popup
            # -- consistente con lo que se ve en pantalla. Pasa por
            # _enviar_a_impresora() igual que una comanda real (respeta
            # bluetooth/wifi/modo-prueba), pero con etiqueta propia y sin
            # tocar self.pedidos ni la base de datos.
            datos_bytes = self._construir_comanda_prueba_escpos(ancho_papel)
            self._enviar_a_impresora(datos_bytes, etiqueta="prueba_comanda")

        b_cerrar.bind(on_press=lambda *_: popup.dismiss())
        b_probar.bind(on_press=_probar)
        botones.add_widget(b_cerrar)
        botones.add_widget(b_probar)
        contenido.add_widget(botones)

        # ── Popup: alto TOTAL dinamico, tope en el 94% de la pantalla ──
        popup = Popup(title="", separator_height=0, content=contenido,
                      size_hint=(0.9, None), background_color=self.OSCURO)

        def _sync_alto_popup(*_):
            popup.height = min(contenido.height + dp(24), Window.height * 0.94)
        contenido.bind(minimum_height=_sync_alto_popup)
        scroll_papel.bind(height=_sync_alto_popup)
        _sync_alto_popup()

        popup.open()

    # ── TICKET DE VENTA (imagen para Galeria) ───────────────────────────────
    def _ticket_dir(self):
        """Carpeta publica de Galeria donde se guardan los tickets. Usa el
        mismo nombre dinamico que la carpeta de errores (Configuracion >
        Personal > Nombre de la taqueria), asi ambas quedan sincronizadas.

        A PROPOSITO no se migra a self.user_data_dir: esa carpeta es
        privada de la app (Android no la muestra en la Galeria), y el
        objetivo aqui es justo lo contrario -- que el ticket aparezca en
        la Galeria del celular para que la cajera lo pueda compartir (ver
        _notificar_galeria). Sigue usando Pictures/, que es la ubicacion
        publica pensada para este tipo de contenido; si en algun momento
        Android bloquea tambien esta ruta por scoped storage, la solucion
        correcta seria MediaStore via jnius, no user_data_dir."""
        try:
            carpeta = "/storage/emulated/0/Pictures/" + _CARPETA_ERRORES["nombre"]
            os.makedirs(carpeta, exist_ok=True)
        except Exception:
            carpeta = os.path.dirname(os.path.abspath(__file__))
        return carpeta

    def _notificar_galeria(self, ruta):
        """Avisa al escaner de medios de Android para que el ticket aparezca
        de inmediato en la Galeria. Es un intento silencioso: si falla (por
        ejemplo, fuera de Android) el archivo ya quedo guardado igual."""
        try:
            from jnius import autoclass
            Intent = autoclass("android.content.Intent")
            Uri = autoclass("android.net.Uri")
            File = autoclass("java.io.File")
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            contexto = PythonActivity.mActivity
            intent = Intent(Intent.ACTION_MEDIA_SCANNER_SCAN_FILE)
            intent.setData(Uri.fromFile(File(ruta)))
            contexto.sendBroadcast(intent)
        except Exception:
            pass

    def _construir_ticket_widget(self, encabezado_lineas, items, total):
        """Arma el widget visual del ticket, estilo recibo de papel: fondo
        blanco y texto oscuro fijos (no dependen del tema activo), para que
        se vea igual de profesional sin importar los colores de la app."""
        BLANCO_T = [0.98, 0.98, 0.96, 1]
        NEGRO_T  = [0.12, 0.12, 0.12, 1]
        GRIS_T   = [0.12, 0.12, 0.12, 0.55]
        ancho = dp(300)

        ticket = BoxLayout(
            orientation="vertical", size_hint=(None, None), width=ancho,
            padding=[dp(18), dp(18), dp(18), dp(18)], spacing=dp(3),
        )
        ticket.bind(minimum_height=ticket.setter("height"))
        with ticket.canvas.before:
            Color(*BLANCO_T)
            ticket._bg = Rectangle(pos=ticket.pos, size=ticket.size)
        ticket.bind(pos=lambda w, v: setattr(w._bg, "pos", v),
                    size=lambda w, v: setattr(w._bg, "size", v))

        def fila_centrada(texto, tam="12sp", negrita=False, color=None, h=dp(20)):
            l = Label(
                text=f"[b]{texto}[/b]" if negrita else texto,
                markup=True, color=color or NEGRO_T, font_size=tam,
                halign="center", valign="middle",
                size_hint_y=None, height=h,
            )
            l.bind(width=lambda w, v: setattr(w, "text_size", (v, None)))
            return l

        def separador():
            d = Label(text="- " * 26, color=GRIS_T, font_size="10sp",
                      halign="center", size_hint_y=None, height=dp(12))
            d.bind(width=lambda w, v: setattr(w, "text_size", (v, None)))
            return d

        # Ancho util fijo (ancho del ticket menos el padding izq+der) desde
        # la creacion del Label -- igual que en la Vista Previa de
        # impresion/comanda: asi el texture_size (y por lo tanto el alto)
        # se calcula bien desde el primer frame, sin que el texto se
        # encime si la direccion, el banco o el mensaje personalizado
        # ocupan mas de una linea.
        ancho_util_pie = ancho - dp(36)

        def fila_pie(texto, negrita=False, color=None, tam="11sp"):
            w = Label(
                text=f"[b]{texto}[/b]" if negrita else texto, markup=True,
                color=color or GRIS_T, font_size=tam,
                halign="center", valign="top",
                size_hint_y=None, size_hint_x=None, width=ancho_util_pie,
                text_size=(ancho_util_pie, None),
            )
            w.bind(texture_size=lambda inst, ts: setattr(inst, "height", ts[1]))
            w.texture_update()
            w.height = w.texture_size[1]
            return w

        nombre_limpio = self.nombre_taqueria.replace("[b]", "").replace("[/b]", "")
        ticket.add_widget(fila_centrada(nombre_limpio, tam="16sp", negrita=True, h=dp(26)))
        for linea in encabezado_lineas:
            ticket.add_widget(fila_centrada(linea, tam="11sp", color=GRIS_T))
        ticket.add_widget(separador())

        for it in items:
            qty  = it.get("qty", 1)
            subt = it["precio"] * qty
            fila = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(20))
            l_nom = Label(
                text=f"{qty}x {it['nombre']}", color=NEGRO_T, font_size="12sp",
                halign="left", valign="middle",
                size_hint_x=0.68, size_hint_y=None, height=dp(20), shorten=True,
            )
            l_nom.bind(size=lambda w, v: setattr(w, "text_size", (v[0], None)))
            l_pre = Label(
                text=f"${subt:.0f}", color=NEGRO_T, font_size="12sp",
                halign="right", valign="middle",
                size_hint_x=0.32, size_hint_y=None, height=dp(20),
            )
            l_pre.bind(size=lambda w, v: setattr(w, "text_size", (v[0], None)))
            fila.add_widget(l_nom)
            fila.add_widget(l_pre)
            ticket.add_widget(fila)

        ticket.add_widget(separador())

        fila_total = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(28))
        l_tl = Label(text="[b]TOTAL[/b]", markup=True, color=NEGRO_T, font_size="16sp",
                     halign="left", valign="middle",
                     size_hint_x=0.5, size_hint_y=None, height=dp(28))
        l_tl.bind(size=lambda w, v: setattr(w, "text_size", (v[0], None)))
        l_tv = Label(text=f"[b]${total:.0f}[/b]", markup=True, color=NEGRO_T, font_size="16sp",
                     halign="right", valign="middle",
                     size_hint_x=0.5, size_hint_y=None, height=dp(28))
        l_tv.bind(size=lambda w, v: setattr(w, "text_size", (v[0], None)))
        fila_total.add_widget(l_tl)
        fila_total.add_widget(l_tv)
        ticket.add_widget(fila_total)

        ticket.add_widget(separador())

        info = self.info_negocio
        if info.get("direccion"):
            ticket.add_widget(fila_pie(_sin_acentos(info["direccion"])))

        datos_pago = [k for k in ("banco", "cuenta", "titular") if info.get(k)]
        if datos_pago:
            ticket.add_widget(separador())
            ticket.add_widget(fila_pie("DATOS PARA TRANSFERENCIA", negrita=True, color=NEGRO_T))
            if info.get("banco"):
                ticket.add_widget(fila_pie(f"Banco: {_sin_acentos(info['banco'])}", color=NEGRO_T))
            if info.get("cuenta"):
                ticket.add_widget(fila_pie(f"Cuenta/CLABE: {info['cuenta']}", color=NEGRO_T))
            if info.get("titular"):
                ticket.add_widget(fila_pie(f"Titular: {_sin_acentos(info['titular'])}", color=NEGRO_T))
        if info.get("telefono"):
            ticket.add_widget(fila_pie(f"Enviar comprobante al: {info['telefono']}", color=NEGRO_T))

        ticket.add_widget(separador())
        mensaje = info.get("mensaje_agradecimiento") or "Gracias por su preferencia"
        ticket.add_widget(fila_pie(_sin_acentos(mensaje), tam="11sp"))

        return ticket

    def _abrir_ticket(self, encabezado_lineas, items, total, titulo="TICKET DE VENTA"):
        """Popup con el ticket armado y un boton para guardarlo en Galeria.
        El popup se ajusta al tamano real del ticket (no a un 85% de
        pantalla fijo), para que no quede un hueco muerto arriba cuando
        el ticket es mas chico que la pantalla; si el ticket es mas alto
        de lo que cabe, entonces si se activa el scroll."""
        if not items:
            _snack("No hay items para generar el ticket")
            return

        from kivy.core.window import Window

        ticket = self._construir_ticket_widget(encabezado_lineas, items, total)

        # Alto maximo visible para el area del ticket: no mas del 60% de
        # la pantalla, para dejar siempre lugar a titulo y botones.
        alto_max_scroll = Window.height * 0.6
        alto_scroll = min(ticket.height, alto_max_scroll)

        scroll = ScrollView(size_hint=(1, None), height=alto_scroll,
                            do_scroll_x=False)
        anchor = AnchorLayout(anchor_x="center", anchor_y="top", size_hint_y=None)
        anchor.height = ticket.height
        ticket.bind(height=lambda w, v: setattr(anchor, "height", v))

        def _sync_alto_scroll(*_):
            scroll.height = min(ticket.height, Window.height * 0.6)
        ticket.bind(height=_sync_alto_scroll)

        anchor.add_widget(ticket)
        scroll.add_widget(anchor)

        impresora_activa = self._impresora_activa()

        btns = BoxLayout(orientation="horizontal", size_hint_y=None,
                         height=dp(46), spacing=dp(10))
        b_cerrar  = btn_flat("CERRAR", color=_texto_contraste(self.OSCURO),
                             size_hint_y=None, height=dp(44))
        b_guardar = btn_raised("GALERIA", bg=self.ACCENT,
                               size_hint_y=None, height=dp(44), font_size="12sp")
        btns.add_widget(b_cerrar)
        btns.add_widget(b_guardar)
        # Boton IMPRIMIR: solo aparece si la impresora esta encendida en
        # Configuracion > Personalizacion (si esta apagada no tiene
        # sentido mostrarlo, es un clic que no lleva a nada).
        if impresora_activa:
            b_imprimir = btn_raised("IMPRIMIR", bg=self.DORADO,
                                    size_hint_y=None, height=dp(44), font_size="12sp")
            btns.add_widget(b_imprimir)

        content = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(10),
                            size_hint_y=None)
        content.bind(minimum_height=content.setter("height"))
        content.add_widget(lbl(
            f"[b]{titulo}[/b]", markup=True, color=self.texto_contraste(self.OSCURO), font_size="15sp",
            halign="center", size_hint_y=None, height=dp(26),
        ))
        content.add_widget(scroll)
        content.add_widget(btns)

        popup = Popup(title="", separator_height=0, content=content,
                      size_hint=(0.92, None), background_color=self.OSCURO)

        def _sync_popup_height(*_):
            popup.height = min(content.height + dp(24), Window.height * 0.94)
        content.bind(minimum_height=_sync_popup_height)
        scroll.bind(height=_sync_popup_height)
        _sync_popup_height()

        b_cerrar.bind(on_press=lambda *_: popup.dismiss())
        b_guardar.bind(on_press=lambda *_: self._guardar_ticket_imagen(ticket))
        if impresora_activa:
            b_imprimir.bind(on_press=lambda *_: self.imprimir_ticket_cliente(
                encabezado_lineas, items, total))
        popup.open()

    def _guardar_ticket_imagen(self, ticket_widget):
        """Rasteriza el widget del ticket a PNG y lo guarda en la Galeria."""
        carpeta = self._ticket_dir()
        ahora   = datetime.now()
        nombre  = f"ticket_{ahora.strftime('%Y%m%d_%H%M%S')}.png"
        ruta    = os.path.join(carpeta, nombre)

        def _exportar(dt):
            try:
                ticket_widget.export_to_png(ruta)
                self._notificar_galeria(ruta)
                _snack("Ticket guardado en Galeria")
            except Exception as e:
                print("Error guardando ticket:", e)
                _snack("No se pudo guardar el ticket")

        # Se agenda un frame despues: asegura que el widget ya tenga su
        # tamano/posicion final antes de rasterizarlo (si se exporta en el
        # mismo instante en que se arma, puede salir con tamano 0).
        Clock.schedule_once(_exportar, 0.1)

    def _ver_pedido_mesa(self, mesa):
        pedido = next((p for p in self.pedidos
                       if p.get("tipo") == "mesa" and p.get("mesa") == mesa), None)
        if not pedido:
            _snack(f"No se encontro pedido para {mesa}")
            return

        # Scroll interno para que nunca se encimen aunque haya muchos items
        scroll = ScrollView(size_hint=(1, 1))
        inner = BoxLayout(
            orientation="vertical", spacing=dp(2),
            padding=[dp(4), dp(4), dp(4), dp(4)],
            size_hint_y=None,
        )
        inner.bind(minimum_height=inner.setter("height"))
        scroll.add_widget(inner)

        total = 0
        FH = dp(32)   # altura fija por fila — generosa para evitar encimado
        FH_NOTA = dp(20)  # alto extra de la sub-linea de nota, si existe
        for idx, it in enumerate(pedido["items"]):
            qty  = it.get("qty", 1)
            subt = it["precio"] * qty
            total += subt
            nota = (it.get("_nota") or "").strip()

            fila = BoxLayout(
                orientation="vertical", spacing=dp(1),
                size_hint_y=None, height=(FH + FH_NOTA if nota else FH),
            )

            row = BoxLayout(orientation="horizontal", size_hint_y=None, height=FH)
            l_nom = Label(
                text=f"{qty}x  {it['nombre']}",
                color=_texto_contraste(self.OSCURO), font_size="13sp",
                halign="left", valign="middle",
                size_hint_x=0.55, size_hint_y=None, height=FH,
            )
            l_nom.bind(size=lambda w,v: setattr(w,"text_size",(v[0],None)))
            l_pre = Label(
                text=f"${subt:.0f}",
                color=self.texto_contraste(self.OSCURO), font_size="13sp",
                halign="right", valign="middle",
                size_hint_x=0.28, size_hint_y=None, height=FH,
            )
            l_pre.bind(size=lambda w,v: setattr(w,"text_size",(v[0],None)))
            btn_del = btn_flat(
                "X", color=self.texto_contraste(self.OSCURO),
                size_hint_x=None, width=dp(34),
                size_hint_y=None, height=FH,
            )
            btn_del.bind(on_press=lambda inst, i=idx, m=mesa, n=it["nombre"], q=qty:
                         self._confirmar_eliminar_item_pedido(m, i, n, q))
            row.add_widget(l_nom)
            row.add_widget(l_pre)
            row.add_widget(btn_del)
            fila.add_widget(row)

            if nota:
                l_nota = Label(
                    text=f"     📝 {nota}",
                    color=self.texto_contraste(self.OSCURO)[:3] + [0.85], font_size="11sp",
                    halign="left", valign="middle",
                    size_hint_y=None, height=FH_NOTA,
                    shorten=True,
                )
                l_nota.bind(size=lambda w,v: setattr(w,"text_size",(v[0],None)))
                fila.add_widget(l_nota)

            inner.add_widget(fila)

        # Línea divisora
        from kivy.uix.widget import Widget as _W
        div = _W(size_hint_y=None, height=dp(1))
        with div.canvas:
            Color(*GRIS)
            div._r = Rectangle(pos=div.pos, size=div.size)
        div.bind(pos=lambda w,v: setattr(w._r,'pos',v),
                 size=lambda w,v: setattr(w._r,'size',v))
        inner.add_widget(div)

        # Fila total
        row_t = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(36))
        l_tl = Label(
            text="[b]TOTAL[/b]", markup=True,
            color=self.texto_contraste(self.OSCURO), font_size="14sp",
            halign="left", valign="middle",
            size_hint_x=0.55, size_hint_y=None, height=dp(36),
        )
        l_tl.bind(size=lambda w,v: setattr(w,"text_size",(v[0],None)))
        l_tv = Label(
            text=f"[b]${total:.0f}[/b]", markup=True,
            color=self.texto_contraste(self.OSCURO), font_size="14sp",
            halign="right", valign="middle",
            size_hint_x=0.45, size_hint_y=None, height=dp(36),
        )
        l_tv.bind(size=lambda w,v: setattr(w,"text_size",(v[0],None)))
        row_t.add_widget(l_tl)
        row_t.add_widget(l_tv)
        inner.add_widget(row_t)

        # Botones fuera del scroll (2 filas para que quepan bien en celular)
        btns1 = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(46),
                          spacing=dp(8), padding=[dp(4), dp(4), dp(4), 0])
        b_cerrar = btn_flat("Cerrar", color=_texto_contraste(self.OSCURO), size_hint_y=None, height=dp(40))
        b_ticket = btn_flat("TICKET", color=self.texto_contraste(self.OSCURO), size_hint_y=None, height=dp(40))
        btns1.add_widget(b_cerrar)
        btns1.add_widget(b_ticket)

        btns2 = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(46),
                          spacing=dp(8), padding=[dp(4), 0, dp(4), 0])
        b_mesa = btn_flat("CAMBIAR MESA", color=self.texto_contraste(self.OSCURO),
                          size_hint_y=None, height=dp(40))
        b_unir = btn_flat("UNIR MESA", color=self.texto_contraste(self.OSCURO),
                          size_hint_y=None, height=dp(40))
        b_mas  = btn_raised("Agregar mas", bg=self.ROJO,
                            size_hint_y=None, height=dp(40))
        btns2.add_widget(b_mesa)
        btns2.add_widget(b_unir)
        btns2.add_widget(b_mas)

        # Fila aparte para Cobrar, bien visible, ancho completo
        btn_cobrar = btn_raised(
            f"Cobrar  ${total:.0f}", bg=self.ACCENT, color=_texto_contraste(self.ACCENT),
            size_hint_y=None, height=dp(44),
        )

        wrap = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(6))
        wrap.add_widget(scroll)
        wrap.add_widget(btn_cobrar)
        wrap.add_widget(btns1)
        wrap.add_widget(btns2)

        popup = Popup(
            title=f"{mesa}  —  {pedido['hora']}",
            content=wrap,
            size_hint=(0.88, 0.8),
            background_color=self.OSCURO,
        )
        b_cerrar.bind(on_press=lambda *_: popup.dismiss())
        b_ticket.bind(on_press=lambda *_, p=pedido: self._abrir_ticket(
            [f"Mesa: {p['mesa']}", f"Hora: {p['hora']}"] +
            ([f"Atendió: {p['empleado']}"] if p.get("empleado") else []),
            p["items"], total, titulo="TICKET DE VENTA",
        ))
        b_mesa.bind(on_press=lambda *_, i=pedido["id"]: (popup.dismiss(),
                                                          self._elegir_nueva_mesa(i)))
        b_unir.bind(on_press=lambda *_, i=pedido["id"]: (popup.dismiss(),
                                                          self._elegir_mesa_para_unir(i)))
        b_mas.bind(on_press=lambda *_, m=mesa: (popup.dismiss(),
                                                 self._agregar_a_mesa_existente(m)))
        pid = pedido["id"]
        btn_cobrar.bind(on_press=lambda *_, i=pid: (popup.dismiss(),
                                                      self._dialog_forma_pago(i)))
        popup.open()
        self._dialog = popup
        popup.bind(on_dismiss=lambda *_: setattr(self, "_dialog", None))

    def _elegir_nueva_mesa(self, pid):
        """Popup para mover un pedido YA GUARDADO de una mesa a otra (p.ej.
        si los clientes se cambiaron de la Mesa 1 a la Mesa 3). Solo
        ofrece mesas libres -- nunca se puede "aterrizar" encima de un
        pedido que ya está en otra mesa."""
        pedido = next((p for p in self.pedidos if p["id"] == pid), None)
        if not pedido:
            return
        mesa_actual = pedido.get("mesa")

        ocupadas = {p["mesa"] for p in self.pedidos
                   if p.get("tipo") == "mesa" and p["id"] != pid}
        libres = [m for m in self.mesas if m not in ocupadas and m != mesa_actual]

        content = BoxLayout(orientation="vertical", padding=dp(18), spacing=dp(12))
        content.add_widget(lbl(
            "[b]CAMBIAR MESA[/b]", markup=True, color=self.texto_contraste(self.OSCURO),
            font_size="15sp", halign="center", size_hint_y=None, height=dp(26),
        ))
        content.add_widget(lbl(
            f"Mover pedido de {mesa_actual} a:",
            color=self.texto_contraste(self.OSCURO), font_size="13sp",
            halign="center", size_hint_y=None, height=dp(24),
        ))

        popup_ref = [None]

        if not libres:
            content.add_widget(lbl(
                "No hay otra mesa libre en este momento.",
                color=GRIS, font_size="12sp", halign="center",
                size_hint_y=None, height=dp(40), auto_height=True,
            ))
        else:
            scroll = ScrollView(size_hint=(1, None), height=dp(220))
            grid = GridLayout(cols=3, spacing=dp(8), size_hint_y=None, padding=[0, dp(4)])
            grid.bind(minimum_height=grid.setter("height"))
            for m in libres:
                b = btn_flat(m, color=self.texto_contraste(self.OSCURO),
                            size_hint_y=None, height=dp(44))
                b.bind(on_press=lambda inst, mn=m: (
                    popup_ref[0].dismiss() if popup_ref[0] else None,
                    self._mover_pedido_a_mesa(pid, mn),
                ))
                grid.add_widget(b)
            scroll.add_widget(grid)
            content.add_widget(scroll)

        b_can = btn_flat("Cancelar", color=self.texto_contraste(self.OSCURO),
                         size_hint_y=None, height=dp(40))
        content.add_widget(b_can)

        content.size_hint_y = None
        content.bind(minimum_height=content.setter("height"))

        popup = Popup(title="", separator_height=0, content=content,
                      size_hint=(0.86, None), background_color=self.OSCURO)

        def _sync_popup_height(*_):
            popup.height = min(content.height + dp(24), dp(460))
        content.bind(minimum_height=_sync_popup_height)
        _sync_popup_height()

        popup_ref[0] = popup
        b_can.bind(on_press=lambda *_: popup.dismiss())
        popup.open()
        self._dialog = popup
        popup.bind(on_dismiss=lambda *_: setattr(self, "_dialog", None))

    def _resolver_mesa_movida(self, nombre):
        """Sigue la cadena de _mesas_movidas hasta encontrar dónde terminó
        una mesa que se movió (puede haberse movido más de una vez).
        Regresa el nombre final SOLO si esa mesa vieja sigue libre --
        si alguien ya volvió a ocupar el nombre viejo (otra mesa/pedido
        nuevo con ese nombre), ya no aplica la redirección y se regresa
        tal cual se pidió, para no desviar un pedido nuevo y legítimo."""
        ocupadas_ahora = {p["mesa"] for p in self.pedidos if p.get("tipo") == "mesa"}
        visto = set()
        actual = nombre
        while actual in self._mesas_movidas and actual not in ocupadas_ahora:
            if actual in visto:
                break  # por si acaso hay un ciclo, no debería pasar
            visto.add(actual)
            actual = self._mesas_movidas[actual][0]
        return actual

    def _mover_pedido_a_mesa(self, pid, mesa_nueva):
        """Cambia la mesa de un pedido ya guardado. No toca items, total,
        empleado ni nada más -- solo reasigna la ubicación física. Si
        entre que se abrió el popup y se tocó el botón alguien más ya
        ocupó esa mesa (dos cajeras a la vez, por ejemplo), se cancela
        para no pisar ese otro pedido."""
        pedido = next((p for p in self.pedidos if p["id"] == pid), None)
        if not pedido:
            return
        ya_ocupada = any(p["mesa"] == mesa_nueva for p in self.pedidos
                         if p.get("tipo") == "mesa" and p["id"] != pid)
        if ya_ocupada:
            _snack(f"{mesa_nueva} ya está ocupada, elige otra")
            return

        mesa_vieja = pedido.get("mesa")
        pedido["mesa"] = mesa_nueva
        self._mesas_movidas[mesa_vieja] = (mesa_nueva, datetime.now())
        # Si "mesa_nueva" a su vez era el nombre viejo de un movimiento
        # anterior (una mesa que ya se había movido antes hacia acá), esa
        # entrada ya no tiene sentido -- se quita para no dejar cadenas
        # rotas.
        self._mesas_movidas.pop(mesa_nueva, None)
        self.refrescar_mesas()
        self.refrescar_lista_activos()
        _snack(f"Pedido movido de {mesa_vieja} a {mesa_nueva}")

    def _elegir_mesa_para_unir(self, pid):
        """Popup para UNIR el pedido de esta mesa con el de OTRA mesa ya
        ocupada (p.ej. la Mesa 4 se junta con la Mesa 1). A diferencia de
        _elegir_nueva_mesa (que mueve un pedido a una mesa LIBRE), aqui
        solo se listan mesas OCUPADAS -- es contra ese pedido existente
        contra el que se van a sumar los items."""
        pedido = next((p for p in self.pedidos if p["id"] == pid), None)
        if not pedido:
            return
        mesa_actual = pedido.get("mesa")

        ocupadas = [p["mesa"] for p in self.pedidos
                    if p.get("tipo") == "mesa" and p["id"] != pid]
        if not ocupadas:
            _snack("No hay otra mesa ocupada con la cual unir")
            return

        content = BoxLayout(orientation="vertical", padding=dp(18), spacing=dp(12))
        content.add_widget(lbl(
            "[b]UNIR MESA[/b]", markup=True, color=self.texto_contraste(self.OSCURO),
            font_size="15sp", halign="center", size_hint_y=None, height=dp(26),
        ))
        content.add_widget(lbl(
            f"Juntar {mesa_actual} con:",
            color=self.texto_contraste(self.OSCURO), font_size="13sp",
            halign="center", size_hint_y=None, height=dp(24),
        ))

        popup_ref = [None]

        scroll = ScrollView(size_hint=(1, None), height=dp(220))
        grid = GridLayout(cols=3, spacing=dp(8), size_hint_y=None, padding=[0, dp(4)])
        grid.bind(minimum_height=grid.setter("height"))
        for m in ocupadas:
            b = btn_flat(m, color=self.texto_contraste(self.OSCURO),
                        size_hint_y=None, height=dp(44))
            b.bind(on_press=lambda inst, mn=m: (
                popup_ref[0].dismiss() if popup_ref[0] else None,
                self._confirmar_unir_mesas(pid, mn),
            ))
            grid.add_widget(b)
        scroll.add_widget(grid)
        content.add_widget(scroll)

        b_can = btn_flat("Cancelar", color=self.texto_contraste(self.OSCURO),
                         size_hint_y=None, height=dp(40))
        content.add_widget(b_can)

        content.size_hint_y = None
        content.bind(minimum_height=content.setter("height"))

        popup = Popup(title="", separator_height=0, content=content,
                      size_hint=(0.86, None), background_color=self.OSCURO)

        def _sync_popup_height(*_):
            popup.height = min(content.height + dp(24), dp(460))
        content.bind(minimum_height=_sync_popup_height)
        _sync_popup_height()

        popup_ref[0] = popup
        b_can.bind(on_press=lambda *_: popup.dismiss())
        popup.open()
        self._dialog = popup
        popup.bind(on_dismiss=lambda *_: setattr(self, "_dialog", None))

    def _confirmar_unir_mesas(self, pid_origen, mesa_destino):
        """Confirmacion antes de unir dos mesas: a diferencia de cambiar
        de mesa, esta accion SI combina dos pedidos en uno solo y no se
        puede deshacer con un simple "cambiar mesa" de vuelta, asi que
        se avisa claramente antes de tocar nada."""
        pedido_origen = next((p for p in self.pedidos if p["id"] == pid_origen), None)
        if not pedido_origen:
            return
        mesa_origen = pedido_origen.get("mesa")

        content = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(14),
                            size_hint_y=None)
        content.bind(minimum_height=content.setter("height"))
        content.add_widget(lbl(
            f"¿Unir {mesa_origen} con {mesa_destino}?\n"
            f"Los productos de {mesa_origen} se sumaran a la cuenta de "
            f"{mesa_destino} y {mesa_origen} quedara libre.",
            color=self.texto_contraste(self.OSCURO), font_size="14sp",
            halign="center", size_hint_y=None, height=dp(80), auto_height=True,
        ))

        btns = BoxLayout(orientation="horizontal", size_hint_y=None,
                         height=dp(44), spacing=dp(10))
        b_cancelar = btn_flat("CANCELAR", color=self.texto_contraste(self.OSCURO),
                              size_hint_y=None, height=dp(42))
        b_unir = btn_raised("UNIR", bg=self.ROJO,
                            size_hint_y=None, height=dp(42))
        btns.add_widget(b_cancelar)
        btns.add_widget(b_unir)
        content.add_widget(btns)

        popup = Popup(title="", separator_height=0, content=content,
                      size_hint=(0.86, None), height=dp(220),
                      background_color=self.OSCURO, auto_dismiss=False)

        def _cerrar(*_):
            self._dialog = None
            popup.dismiss()

        def _confirmar(*_):
            self._dialog = None
            popup.dismiss()
            self._unir_mesas(pid_origen, mesa_destino)

        b_cancelar.bind(on_press=_cerrar)
        b_unir.bind(on_press=_confirmar)
        self._dialog = popup
        popup.open()

    def _unir_mesas(self, pid_origen, mesa_destino):
        """Combina el pedido de 'pid_origen' con el pedido ya existente en
        'mesa_destino': suma cantidades de los productos que coincidan
        (mismo id, y ninguno de los dos es un "extra" con _uid propio) y
        agrega el resto como renglones nuevos. El pedido origen
        desaparece (su mesa vuelve a quedar libre) y todo queda bajo el
        pedido de mesa_destino, que conserva su hora/empleado original."""
        pedido_origen  = next((p for p in self.pedidos if p["id"] == pid_origen), None)
        pedido_destino = next((p for p in self.pedidos
                               if p.get("tipo") == "mesa" and p["mesa"] == mesa_destino
                               and p["id"] != pid_origen), None)
        if not pedido_origen or not pedido_destino:
            _snack("No se pudo unir: revisa que ambas mesas sigan ocupadas")
            return

        mesa_origen = pedido_origen.get("mesa")

        for item in pedido_origen["items"]:
            if item.get("_uid"):
                # Los "extras" (Costo Extra ya cobrado con su propia nota)
                # siempre se agregan como renglon nuevo, nunca se suman.
                pedido_destino["items"].append(copy.deepcopy(item))
                continue
            existente = next((it for it in pedido_destino["items"]
                              if it["id"] == item["id"] and not it.get("_uid")), None)
            if existente:
                existente["qty"] = existente.get("qty", 1) + item.get("qty", 1)
            else:
                pedido_destino["items"].append(copy.deepcopy(item))

        pedido_destino["total"] = sum(
            it["precio"] * it.get("qty", 1) for it in pedido_destino["items"]
        )

        self.pedidos = [p for p in self.pedidos if p["id"] != pid_origen]
        # Igual que al mover una mesa: se registra que "mesa_origen" quedo
        # libre por una union, por si algo mas en la app sigue esa cadena.
        self._mesas_movidas[mesa_origen] = (mesa_destino, datetime.now())
        self._mesas_movidas.pop(mesa_destino, None)

        self.refrescar_mesas()
        self.refrescar_lista_activos()
        self.refrescar_stats()
        _snack(f"{mesa_origen} se unio con {mesa_destino}")

    def _confirmar_eliminar_item_pedido(self, mesa, index, nombre_item, qty=1):
        """Pide confirmacion antes de quitar un producto de un pedido de mesa
        ya guardado (por ejemplo, si el cliente cancelo algo o el mesero
        agrego de mas). Si hay mas de 1 unidad, deja elegir entre quitar
        solo una unidad (por si se agregaron de mas) o quitar la linea
        completa."""
        if self._dialog:
            try: self._dialog.dismiss()
            except Exception: pass

        content = BoxLayout(orientation="vertical", padding=dp(18), spacing=dp(14))
        titulo_lbl = lbl(
            "¿Quitar este producto del pedido?",
            color=self.texto_contraste(self.OSCURO), font_size="14sp",
            halign="center", size_hint_y=None, height=dp(28),
            auto_height=True,
        )
        content.add_widget(titulo_lbl)
        content.add_widget(lbl(
            f"[b]{qty}x {nombre_item}[/b]" if qty > 1 else f"[b]{nombre_item}[/b]",
            markup=True, color=self.texto_contraste(self.OSCURO),
            font_size="15sp", halign="center", size_hint_y=None, height=dp(26),
            auto_height=True,
        ))
        content.add_widget(lbl(
            "Se registrará como pérdida fantasma en el cierre de caja "
            "(no afecta la ganancia ni el total en caja). "
            "Escribe el motivo para poder continuar:",
            color=self.texto_contraste(self.OSCURO)[:3] + [0.6],
            font_size="11sp", halign="center", size_hint_y=None, height=dp(40),
            auto_height=True,
        ))
        f_razon = campo_texto("Motivo de la eliminación *", multiline=True, height=dp(64))
        content.add_widget(f_razon)

        popup_ref = [None]
        estado = {"n": 1}

        def _quitar(*_):
            razon = f_razon.text.strip()
            if not razon:
                _snack("Escribe un motivo para poder quitar el producto")
                return
            if popup_ref[0]:
                popup_ref[0].dismiss()
            self._eliminar_item_pedido(mesa, index, cantidad=estado["n"], razon=razon)

        if qty > 1:
            # Hay mas de una unidad: se elige con +/- cuantas quitar, sin
            # poder pasarse de las que realmente hay (tope = qty).
            content.add_widget(lbl(
                f"¿Cuantas de las {qty} quieres quitar?",
                color=self.texto_contraste(self.OSCURO)[:3] + [0.6],
                font_size="12sp", halign="center", size_hint_y=None, height=dp(22),
            ))

            contador = BoxLayout(orientation="horizontal", size_hint_y=None,
                                  height=dp(56), spacing=dp(16))
            btn_menos = btn_raised("−", bg=self.ROJO, size_hint_x=None, width=dp(56),
                                    font_size="22sp")
            lbl_num = lbl(str(estado["n"]), color=self.texto_contraste(self.OSCURO),
                          font_size="26sp", bold=True, halign="center")
            btn_mas = btn_raised("+", bg=self.DORADO, size_hint_x=None, width=dp(56),
                                  font_size="22sp")
            contador.add_widget(btn_menos)
            contador.add_widget(lbl_num)
            contador.add_widget(btn_mas)
            content.add_widget(contador)

            def _cambiar(delta):
                estado["n"] = max(1, min(qty, estado["n"] + delta))
                lbl_num.text = str(estado["n"])
                b_quitar.text = "Quitar todos" if estado["n"] == qty else f"Quitar {estado['n']}"

            btn_menos.bind(on_press=lambda *_: _cambiar(-1))
            btn_mas.bind(on_press=lambda *_: _cambiar(1))

            b_quitar = btn_raised("Quitar 1", bg=self.ROJO,
                                   size_hint_y=None, height=dp(46), font_size="14sp")
            b_quitar.bind(on_press=_quitar)
            content.add_widget(b_quitar)
        else:
            b_si = btn_raised("SI, QUITAR", bg=self.ROJO,
                               size_hint_y=None, height=dp(46), font_size="14sp")
            b_si.bind(on_press=_quitar)
            content.add_widget(b_si)

        b_can = btn_flat("Cancelar", color=self.texto_contraste(self.OSCURO)[:3] + [0.6],
                          size_hint_y=None, height=dp(36))

        content.add_widget(b_can)

        # El contenido define su propia altura (suma de sus hijos) en vez de
        # una altura fija adivinada, para que si el titulo crece a 2 lineas
        # (nombres largos, pantallas angostas) el popup crezca con el en
        # lugar de que el texto se encime con el nombre del producto.
        content.size_hint_y = None
        content.bind(minimum_height=content.setter("height"))

        popup = Popup(
            title="", separator_height=0,
            content=content,
            size_hint=(0.82, None), height=dp(230),
            background_color=self.OSCURO,
        )

        def _sync_popup_height(*_):
            popup.height = content.height + dp(20)
        content.bind(minimum_height=_sync_popup_height)
        _sync_popup_height()

        popup_ref[0] = popup
        b_can.bind(on_press=lambda *_: (popup.dismiss(),
                                         self._ver_pedido_mesa(mesa)))
        popup.open()
        self._dialog = popup
        popup.bind(on_dismiss=lambda *_: setattr(self, "_dialog", None))

    def _eliminar_item_pedido(self, mesa, index, cantidad=None, razon=""):
        """Quita el producto en 'index' del pedido de la mesa dada, recalcula
        el total y refresca todo. Si el pedido se queda sin productos, se
        elimina por completo y la mesa vuelve a quedar libre.

        cantidad=None  -> quita la linea completa (todas las unidades).
        cantidad=N     -> solo resta N unidades de esa linea; si con eso
                           llega a 0, entonces si se quita la linea entera.

        razon: motivo obligatorio (ya validado en _confirmar_eliminar_item_pedido)
        que se registra como pérdida fantasma (tabla independiente,
        NO afecta ganancia neta ni total en caja) por el valor exacto de
        lo que se quitó -- así el conteo en Cierre de Caja/Estadísticas
        siempre cuadra con lo que en realidad se canceló.
        """
        pedido = next((p for p in self.pedidos
                       if p.get("tipo") == "mesa" and p.get("mesa") == mesa), None)
        if not pedido:
            return

        perdida = 0
        nombre_item = ""
        if 0 <= index < len(pedido["items"]):
            item = pedido["items"][index]
            nombre_item = item["nombre"]
            qty_actual = item.get("qty", 1)
            cant_quitada = qty_actual if (cantidad is None or cantidad >= qty_actual) else cantidad
            perdida = item["precio"] * cant_quitada
            if cantidad is None or cantidad >= qty_actual:
                pedido["items"].pop(index)
            else:
                item["qty"] = qty_actual - cantidad

        if perdida > 0:
            self._registrar_perdida_fantasma(
                "producto", f"{nombre_item} — Mesa: {mesa}", razon, perdida
            )

        if not pedido["items"]:
            self.pedidos = [p for p in self.pedidos if p["id"] != pedido["id"]]
            self.refrescar_mesas()
            self.refrescar_stats()
            self.refrescar_lista_activos()
            _snack(f"Pedido de {mesa} eliminado (sin productos)  —  pérdida fantasma: ${perdida:,.0f}")
            return

        pedido["total"] = sum(i["precio"] * i.get("qty", 1) for i in pedido["items"])
        self.refrescar_mesas()
        self.refrescar_stats()
        self.refrescar_lista_activos()
        _snack(f"Producto eliminado  —  pérdida fantasma registrada: ${perdida:,.0f}")
        self._ver_pedido_mesa(mesa)

    def _preguntar_personas_mesa(self, mesa):
        """Al abrir una mesa libre, pregunta cuantas personas la ocupan.
        El numero se ajusta solo con botones +/- (sin teclado) y se guarda
        en la BD (tabla mesa_personas) para las estadisticas de clientela."""
        estado = {"n": 2}

        content = BoxLayout(orientation="vertical", padding=dp(18), spacing=dp(14))
        content.add_widget(lbl(
            f"[b]{mesa}[/b]", markup=True, color=self.texto_contraste(self.OSCURO),
            font_size="16sp", halign="center", size_hint_y=None, height=dp(26),
        ))
        content.add_widget(lbl(
            "¿Cuantas personas hay en la mesa?",
            color=self.texto_contraste(self.OSCURO), font_size="14sp",
            halign="center", size_hint_y=None, height=dp(28),
        ))

        contador = BoxLayout(orientation="horizontal", size_hint_y=None,
                              height=dp(56), spacing=dp(16))
        btn_menos = btn_raised("−", bg=self.ROJO, size_hint_x=None, width=dp(56),
                                font_size="22sp")
        lbl_num = lbl(str(estado["n"]), color=self.texto_contraste(self.OSCURO),
                      font_size="26sp", bold=True, halign="center")
        btn_mas = btn_raised("+", bg=self.DORADO, size_hint_x=None, width=dp(56),
                              font_size="22sp")
        contador.add_widget(btn_menos)
        contador.add_widget(lbl_num)
        contador.add_widget(btn_mas)
        content.add_widget(contador)

        def _cambiar(delta):
            estado["n"] = max(1, min(60, estado["n"] + delta))
            lbl_num.text = str(estado["n"])

        btn_menos.bind(on_press=lambda *_: _cambiar(-1))
        btn_mas.bind(on_press=lambda *_: _cambiar(1))

        popup_ref = [None]

        def _confirmar(*_):
            if popup_ref[0]:
                popup_ref[0].dismiss()
            self._registrar_personas_mesa(mesa, estado["n"])

            def _con_empleado(nombre_emp):
                self._empleado_sel = nombre_emp
                self.iniciar_orden("mesa", mesa)

            self._elegir_empleado(_con_empleado)

        b_abrir = btn_raised("ABRIR MESA", bg=self.ACCENT,
                              size_hint_y=None, height=dp(46), font_size="14sp")
        b_can = btn_flat("Cancelar", color=self.texto_contraste(self.OSCURO)[:3] + [0.6],
                          size_hint_y=None, height=dp(36))
        b_abrir.bind(on_press=_confirmar)

        content.add_widget(b_abrir)
        content.add_widget(b_can)

        popup = Popup(
            title="", separator_height=0,
            content=content,
            size_hint=(0.82, None), height=dp(300),
            background_color=self.OSCURO,
        )
        popup_ref[0] = popup
        b_can.bind(on_press=lambda *_: popup.dismiss())
        popup.open()

    def _agregar_a_mesa_existente(self, mesa):
        if self._dialog:
            try: self._dialog.dismiss()
            except Exception: pass
        self.iniciar_orden("mesa", mesa)

    def _actualizar_reloj_dashboard(self, *_):
        """Refresca el label de fecha/hora en tiempo real de la tarjeta
        DOMICILIO/HOY del dashboard (id: lbl_fecha_hora). Se llama cada
        segundo desde Clock.schedule_interval (ver build()), asi que debe
        ser barato y a prueba de fallos: si la pantalla "inicio" todavia
        no existe (por ejemplo la primerisima llamada via schedule_once,
        antes de que self.root este listo del todo) simplemente no hace
        nada y se corrige solo en el siguiente tick, sin tronar la app."""
        try:
            sc = self.root.get_screen("inicio")
        except Exception:
            return
        ahora = datetime.now()
        # Fecha corta (dia/mes/año a 2 digitos) + hora en formato 12h con
        # AM/PM, en una sola linea -- la columna central de esta fila es
        # angosta (comparte espacio con "DOMICILIO" y "HOY"), asi que el
        # texto se mantiene compacto a proposito para que quepa completo
        # sin recortarse ni partirse en dos lineas.
        texto = ahora.strftime("%d/%m/%y  %I:%M:%S %p")
        sc.ids.lbl_fecha_hora.text = texto

    def refrescar_stats(self, *_):
        sc  = self.root.get_screen("inicio")
        hoy = datetime.now().date().strftime("%Y-%m-%d")

        # Pedidos activos en memoria (tiempo real)
        sc.ids.stat_activos_num.text = str(len(self.pedidos))

        # Domicilios del día: activos en memoria + cobrados en BD
        dom_activos = sum(1 for p in self.pedidos if p["tipo"] == "domicilio")
        dom_cobrados, mesas_cobradas = self.db.conteo_pedidos_cobrados_dia(hoy)

        total_dom   = dom_activos + dom_cobrados
        # Mesas del día: cobradas en BD + las activas ahora (que aún no se cobran)
        mesas_activas = len({p["mesa"] for p in self.pedidos if p["tipo"] == "mesa"})
        total_mesas = mesas_cobradas + mesas_activas

        sc.ids.stat_domicilios_num.text = str(total_dom)
        sc.ids.stat_mesas_num.text      = str(total_mesas)

    # ── ORDEN ─────────────────────────────────────────────────────────────────
    def iniciar_orden_domicilio(self):
        """Los pedidos a domicilio siempre los toma la caja, nunca un
        mesero, así que aquí NUNCA se pregunta quién atiende (eso sólo
        aplica a las mesas). Se abre la orden de una vez, sin empleado
        asignado."""
        self._empleado_sel = None
        self.iniciar_orden("domicilio")

    def iniciar_orden(self, tipo, mesa=None):
        """Prepara la pantalla de Orden para un pedido de mesa o domicilio.

        Para domicilio: encadena los campos nombre -> telefono -> direccion
        una sola vez (bandera _campos_encadenados en la Screen, no se
        vuelve a bindear en pedidos siguientes) y, con un pequeno retraso,
        le da el foco a campo_nombre para que el teclado aparezca listo
        para escribir sin pelear con la animacion de la pantalla.
        """
        self.tipo_orden = tipo
        self.mesa_sel   = mesa
        self.cat_activa = list(self.menu.keys())[0]

        pedido_existente = None
        if tipo == "mesa" and mesa:
            pedido_existente = next(
                (p for p in self.pedidos if p.get("tipo") == "mesa" and p.get("mesa") == mesa),
                None
            )

        if pedido_existente:
            self.orden_actual = copy.deepcopy(pedido_existente["items"])
            self._pedido_editando_id = pedido_existente["id"]
            # Foto de los items tal cual estaban ANTES de esta edicion --
            # sirve para, al guardar, calcular solo lo que se agrego de
            # nuevo y mandarlo a la comanda de cocina (ver
            # _items_agregados_desde_edicion / guardar_pedido).
            self._orden_original_items = copy.deepcopy(pedido_existente["items"])
        else:
            self.orden_actual = []
            self._pedido_editando_id = None
            self._orden_original_items = []

        sc = self.root.get_screen("orden")
        sc.ids.lbl_titulo_orden.text = (
            "Domicilio" if tipo == "domicilio" else mesa
        )
        box = sc.ids.box_domicilio
        if tipo == "domicilio":
            box.height = dp(170); box.opacity = 1
            sc.ids.campo_nombre.text    = ""
            sc.ids.campo_telefono.text  = ""
            sc.ids.campo_direccion.text = ""

            # Encadenar una sola vez (bandera en la propia Screen, que es
            # una instancia unica y persistente durante toda la sesion).
            if not sc._campos_encadenados:
                encadenar_campos(
                    sc.ids.campo_nombre,
                    sc.ids.campo_telefono,
                    sc.ids.campo_direccion,
                )
                sc._campos_encadenados = True

            # Foco seguro al primer campo: se agenda con un pequeno retraso
            # para que la pantalla ya haya terminado de entrar/animarse y
            # Android no cierre el teclado al pelearse con ese cambio.
            Clock.schedule_once(
                lambda dt: setattr(sc.ids.campo_nombre, "focus", True), 0.2
            )
        else:
            box.height = 0; box.opacity = 0

        self._rebuild_tabs()
        self._rebuild_productos()
        self._rebuild_resumen()

        btn = sc.ids.btn_ver_pedido
        if pedido_existente:
            btn.opacity = 1
            btn.disabled = False
        else:
            btn.opacity = 0
            btn.disabled = True

        self.go_to("orden")

    def ver_pedido_actual(self):
        if not self.orden_actual:
            return
        sc = self.root.get_screen("orden")
        lineas = []
        total = 0
        for it in self.orden_actual:
            qty  = it.get("qty", 1)
            subt = it["precio"] * qty
            total += subt
            lineas.append(f"{qty}x {it['nombre']}  —  ${subt:.0f}")
        lineas.append("TOTAL: $" + f"{total:.0f}")
        texto = "\n".join(lineas)

        content = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))
        content.add_widget(lbl(texto, color=_texto_contraste(self.OSCURO), font_size="13sp",
                               halign="left", markup=False))

        btns = BoxLayout(orientation="horizontal", size_hint_y=None,
                         height=dp(40), spacing=dp(8))
        b_ticket = btn_flat("TICKET", color=self.texto_contraste(self.OSCURO), size_hint_y=None, height=dp(38))
        b_cerrar = btn_raised("Cerrar", bg=self.ROJO, size_hint_y=None, height=dp(38))
        btns.add_widget(b_ticket)
        btns.add_widget(b_cerrar)
        content.add_widget(btns)

        popup = Popup(
            title=f"Pedido  {self.mesa_sel or 'Mesa'}",
            content=content,
            size_hint=(0.82, None), height=dp(70 + 20*len(lineas) + 50),
            background_color=self.OSCURO,
        )
        titulo_pedido = "Domicilio" if self.tipo_orden == "domicilio" else (self.mesa_sel or "Mesa")
        eid = getattr(self, "_pedido_editando_id", None)
        emp_actual = self._empleado_sel
        if eid and not emp_actual:
            ped_ed = next((p for p in self.pedidos if p["id"] == eid), None)
            if ped_ed:
                emp_actual = ped_ed.get("empleado")
        encabezado = [f"{titulo_pedido}", datetime.now().strftime("%d/%m/%Y  %H:%M")]
        if self.tipo_orden == "domicilio":
            tel_dom = sc.ids.campo_telefono.text.strip()
            dir_dom = sc.ids.campo_direccion.text.strip()
            if tel_dom:
                encabezado.append(f"Tel: {tel_dom}")
            if dir_dom:
                encabezado.append(f"Dir: {dir_dom}")
        if emp_actual:
            encabezado.append(f"Atendió: {emp_actual}")
        b_ticket.bind(on_press=lambda *_: self._abrir_ticket(
            encabezado, self.orden_actual, total, titulo="TICKET DE VENTA",
        ))
        b_cerrar.bind(on_press=lambda *_: popup.dismiss())
        popup.open()

    def _rebuild_tabs(self):
        sc  = self.root.get_screen("orden")
        box = sc.ids.tabs_cats
        box.clear_widgets()
        for cat in self.menu:
            if cat == self.cat_activa:
                b = btn_raised(cat, bg=self.ROJO,
                               size_hint_x=None, width=dp(110))
                _set_bg(b, self.ROJO, radius=dp(22))
            else:
                b = btn_flat(cat, color=[.6,.6,.6,1],
                             size_hint_x=None, width=dp(110))
                with b.canvas.before:
                    Color(.6, .6, .6, .5)
                    b._borde_cat = Line(rounded_rectangle=[b.x, b.y, b.width, b.height, dp(22)], width=1)
                b.bind(pos=lambda w,v: setattr(w._borde_cat, 'rounded_rectangle',
                                                [w.x, w.y, w.width, w.height, dp(22)]),
                       size=lambda w,v: setattr(w._borde_cat, 'rounded_rectangle',
                                                 [w.x, w.y, w.width, w.height, dp(22)]))
            c = cat
            b.bind(on_press=lambda inst, c=c: self._cambiar_cat(c))
            box.add_widget(b)

    def _cambiar_cat(self, cat):
        self.cat_activa = cat
        self._rebuild_tabs()
        self._rebuild_productos()

    def _rebuild_productos(self):
        sc  = self.root.get_screen("orden")
        box = sc.ids.lista_prods
        box.clear_widgets()

        for prod in self.menu.get(self.cat_activa, []):
            row = BoxLayout(
                orientation="horizontal",
                size_hint_y=None, height=dp(88),
                padding=dp(10), spacing=dp(10),
            )
            with row.canvas.before:
                Color(*self.OSCURO)
                row._bg = RoundedRectangle(pos=row.pos, size=row.size, radius=[dp(16)])
                Color(*(self.texto_contraste(self.OSCURO)[:3] + [0.08]))
                row._borde = Line(rounded_rectangle=[row.x, row.y, row.width, row.height, dp(16)], width=1)
            row.bind(pos=lambda w,v: (setattr(w._bg,'pos',v),
                                       setattr(w._borde,'rounded_rectangle',[w.x, w.y, w.width, w.height, dp(16)])),
                     size=lambda w,v: (setattr(w._bg,'size',v),
                                        setattr(w._borde,'rounded_rectangle',[w.x, w.y, w.width, w.height, dp(16)])))

            icono_prod = Label(
                text=self.icono(_icono_categoria_cfg(self.cat_activa)),
                markup=True, color=self.texto_contraste(self.OSCURO), font_size="20sp",
                size_hint_x=None, width=dp(28), halign="center", valign="middle",
            )
            icono_prod.bind(size=lambda inst, v: setattr(inst, "text_size", v))
            row.add_widget(icono_prod)

            info = BoxLayout(orientation="vertical", spacing=dp(2))
            info.add_widget(lbl(
                f"[b]{prod['nombre']}[/b]", markup=True,
                color=self.texto_contraste(self.OSCURO),
                font_size="13sp", size_hint_y=None, height=dp(44),
            ))
            if not prod.get("es_extra"):
                info.add_widget(lbl(
                    f"[b]${prod['precio']:.0f}[/b]", markup=True, color=self.texto_contraste(self.OSCURO),
                    font_size="12sp", size_hint_y=None, height=dp(20),
                ))
            row.add_widget(info)

            b = btn_raised("Agregar", bg=self.ROJO,
                           size_hint_x=None, width=dp(85))
            _set_bg(b, self.ROJO, radius=dp(22))
            p = prod
            if prod.get("es_extra"):
                b.bind(on_press=lambda inst, p=p: self._dialog_extra(p))
            else:
                b.bind(on_press=lambda inst, p=p: self._agregar_item(p))
            row.add_widget(b)
            box.add_widget(row)


    def _dialog_extra(self, prod):
        self._f_nota  = campo_texto("Descripcion / nota")
        self._f_monto = campo_texto("Monto ($)", input_filter="float")
        encadenar_campos(self._f_nota, self._f_monto)
        content = BoxLayout(orientation="vertical", spacing=dp(8),
                            padding=dp(10))
        content.add_widget(self._f_nota)
        content.add_widget(self._f_monto)
        btns = BoxLayout(orientation="horizontal", size_hint_y=None,
                         height=dp(44), spacing=dp(8))
        b_cancel = btn_flat("Cancelar", color=self.texto_contraste(self.OSCURO),
                            size_hint_y=None, height=dp(38))
        b_add    = btn_raised("Agregar", bg=self.ROJO,
                              size_hint_y=None, height=dp(38))
        btns.add_widget(b_cancel)
        btns.add_widget(b_add)
        content.add_widget(btns)

        popup = Popup(
            title="Costo Extra", content=content,
            size_hint=(0.82, None), height=dp(260),
            background_color=self.OSCURO,
        )
        b_cancel.bind(on_press=lambda *_: popup.dismiss())
        b_add.bind(on_press=lambda *_, p=prod: self._confirmar_extra(p, popup))
        self._f_monto.bind(
            on_text_validate=lambda *_, p=prod: self._confirmar_extra(p, popup)
        )
        self._dialog = popup
        popup.bind(on_dismiss=lambda *_: setattr(self, "_dialog", None))
        popup.open()

    def _confirmar_extra(self, prod, popup):
        nota  = self._f_nota.text.strip() or "Extra"
        try:
            monto = float(self._f_monto.text.strip())
            assert monto > 0
        except Exception:
            return
        item = {**prod, "nombre": nota, "precio": monto, "qty": 1,
                "_uid": _nuevo_id()}
        self.orden_actual.append(item)
        self._rebuild_resumen()
        popup.dismiss()

    def _agregar_item(self, prod):
        """Cada toque de 'Agregar' crea un renglon NUEVO y separado (con su
        propio _uid), en vez de sumarse al renglon de un producto igual
        que ya estaba en la orden. Esto es a proposito: si el cliente 1
        pidio 3 tacos y el cliente 2 pidio 1 taco, cocina debe ver 4
        renglones de "1x Taco" (4 platos separados), NUNCA un solo
        renglon de "4x Taco" que se preste a servirse en un solo plato.
        El +/- de cada fila (ver _cambiar_qty/_rebuild_resumen) sigue
        funcionando igual que antes para ajustar la cantidad de ESE
        renglon en particular -- solo cambio donde se "aterriza" cada
        toque de Agregar, no el control de +/- que ya existia."""
        self.orden_actual.append({**prod, "qty": 1, "_uid": _nuevo_id()})
        self._rebuild_resumen()

    def _dialog_nota_item(self, item):
        """Popup para escribir/editar un comentario corto de UN renglon
        del pedido (ej. 'sin cebolla', 'bien dorado'). Se guarda en
        item['_nota'] y se muestra debajo del nombre en 'TU PEDIDO'."""
        f_nota = campo_texto("Comentario (ej. sin cebolla)")
        f_nota.text = item.get("_nota", "")
        content = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(10))
        content.add_widget(f_nota)
        btns = BoxLayout(orientation="horizontal", size_hint_y=None,
                         height=dp(44), spacing=dp(8))
        b_quitar   = btn_flat("Quitar", color=self.texto_contraste(self.OSCURO),
                              size_hint_y=None, height=dp(38))
        b_guardar  = btn_raised("Guardar", bg=self.ROJO,
                                size_hint_y=None, height=dp(38))
        btns.add_widget(b_quitar)
        btns.add_widget(b_guardar)
        content.add_widget(btns)

        popup = Popup(
            title=f"Nota — {item['nombre']}", content=content,
            size_hint=(0.85, None), height=dp(220),
            background_color=self.OSCURO,
        )

        def _guardar(*_):
            texto = f_nota.text.strip()
            if texto:
                item["_nota"] = texto
            else:
                item.pop("_nota", None)
            self._rebuild_resumen()
            popup.dismiss()

        def _quitar(*_):
            item.pop("_nota", None)
            self._rebuild_resumen()
            popup.dismiss()

        b_guardar.bind(on_press=_guardar)
        f_nota.bind(on_text_validate=_guardar)
        b_quitar.bind(on_press=_quitar)
        self._dialog = popup
        popup.bind(on_dismiss=lambda *_: setattr(self, "_dialog", None))
        popup.open()

    def _cambiar_qty(self, key, delta, por_uid=False):
        for i, item in enumerate(self.orden_actual):
            match = item.get("_uid") == key if por_uid else item["id"] == key
            if match:
                item["qty"] = item.get("qty", 1) + delta
                if item["qty"] <= 0:
                    self.orden_actual.pop(i)
                break
        self._rebuild_resumen()

    def _rebuild_resumen(self):
        sc  = self.root.get_screen("orden")
        box = sc.ids.lista_resumen
        box.clear_widgets()
        total = 0
        txt_color = self.texto_contraste(self.OSCURO)

        from kivy.uix.widget import Widget as _Espaciador

        for item in self.orden_actual:
            qty  = item.get("qty", 1)
            subt = item["precio"] * qty
            total += subt
            nota = (item.get("_nota") or "").strip()

            uid  = item.get("_uid")
            iid  = item["id"]
            es_e = bool(uid)

            alto_row = dp(94) if nota else dp(76)
            row = BoxLayout(
                orientation="vertical",
                size_hint_y=None, height=alto_row,
                spacing=dp(4), padding=[dp(10), dp(6), dp(10), dp(6)],
            )
            with row.canvas.before:
                Color(*self.OSCURO)
                row._bg = RoundedRectangle(pos=row.pos, size=row.size, radius=[dp(16)])
                Color(*(self.texto_contraste(self.OSCURO)[:3] + [0.08]))
                row._borde = Line(rounded_rectangle=[row.x, row.y, row.width, row.height, dp(16)], width=1)
            row.bind(pos=lambda w,v: (setattr(w._bg,'pos',v),
                                       setattr(w._borde,'rounded_rectangle',[w.x, w.y, w.width, w.height, dp(16)])),
                     size=lambda w,v: (setattr(w._bg,'size',v),
                                        setattr(w._borde,'rounded_rectangle',[w.x, w.y, w.width, w.height, dp(16)])))

            # Linea de arriba: cantidad + nombre COMPLETO + precio, sin
            # recortar (antes usaba shorten=True y se veia "1x Ord...").
            _hex_precio = "#%02x%02x%02x" % tuple(
                int(max(0, min(1, c)) * 255) for c in txt_color[:3]
            )
            row.add_widget(lbl(
                f"[b]{qty}x {item['nombre']}[/b]  —  [color={_hex_precio}]${subt:.0f}[/color]",
                markup=True, color=txt_color, font_size="13sp",
                size_hint_y=None, height=dp(24), shorten=False,
            ))

            if nota:
                row.add_widget(lbl(
                    f"[i]📝 {nota}[/i]", markup=True,
                    color=txt_color[:3] + [0.65], font_size="11sp",
                    size_hint_y=None, height=dp(18), shorten=True,
                ))

            # Linea de abajo: nota (junto al menos), menos, mas -- botones
            # mas grandes (dp40) para que sea facil picarles con el dedo.
            fila_botones = BoxLayout(orientation="horizontal", size_hint_y=None,
                                      height=dp(40), spacing=dp(8))

            btn_nota = btn_flat(self.icono("comment-text-outline"), markup=True,
                                 color=txt_color if nota else (txt_color[:3] + [0.6]),
                                 size_hint_x=None, width=dp(40),
                                 size_hint_y=None, height=dp(40))
            btn_m = btn_flat("−", color=txt_color[:3] + [0.6],
                             size_hint_x=None, width=dp(40),
                             size_hint_y=None, height=dp(40))
            btn_p = btn_flat("+", color=self.texto_contraste(self.OSCURO),
                             size_hint_x=None, width=dp(40),
                             size_hint_y=None, height=dp(40))
            for _bqty in (btn_nota, btn_m, btn_p):
                with _bqty.canvas.before:
                    Color(*(self.texto_contraste(self.OSCURO)[:3] + [0.09]))
                    _bqty._circ = RoundedRectangle(pos=_bqty.pos, size=_bqty.size, radius=[dp(20)])
                _bqty.bind(pos=lambda w,v: setattr(w._circ,'pos',v),
                           size=lambda w,v: setattr(w._circ,'size',v))
            btn_nota.bind(on_press=lambda inst, it=item: self._dialog_nota_item(it))
            btn_m.bind(on_press=lambda inst, k=uid if es_e else iid, e=es_e:
                       self._cambiar_qty(k, -1, e))
            btn_p.bind(on_press=lambda inst, k=uid if es_e else iid, e=es_e:
                       self._cambiar_qty(k, +1, e))

            fila_botones.add_widget(btn_nota)
            fila_botones.add_widget(btn_m)
            fila_botones.add_widget(_Espaciador())
            fila_botones.add_widget(btn_p)
            row.add_widget(fila_botones)
            box.add_widget(row)

        sc.ids.lbl_total.text = f"${total:.0f}"


    def _items_agregados_desde_edicion(self):
        """Compara self._orden_original_items (foto de como estaba el
        pedido al abrir la mesa para editar) contra self.orden_actual
        (como quedo despues de que la cajera agrego/quito productos) y
        regresa SOLO la diferencia positiva: productos nuevos o aumentos
        de cantidad en productos que ya estaban. Los "extras" (items con
        _uid) se identifican por su _uid; el resto, por su id de
        producto. Si algo se quito o se bajo de cantidad, no se incluye
        aqui (eso no le interesa a la cocina)."""
        def _clave(item):
            return item.get("_uid") or item["id"]

        originales = {}
        for it in getattr(self, "_orden_original_items", []):
            originales[_clave(it)] = originales.get(_clave(it), 0) + it.get("qty", 1)

        agregados = []
        for it in self.orden_actual:
            qty_actual = it.get("qty", 1)
            qty_previa = originales.get(_clave(it), 0)
            diferencia = qty_actual - qty_previa
            if diferencia > 0:
                agregados.append({**it, "qty": diferencia})
        return agregados

    def procesar_pedido_entrante(self, mesa, items_nuevos, empleado=None):
        """Punto ÚNICO para crear una mesa nueva o sumarle productos a una
        que ya estaba abierta. Es el reemplazo centralizado de la lógica
        que antes estaba duplicada en guardar_pedido() (cajera) y en
        servidor_mesas._agregar_pedido_mesero() (meseros).

        Usa siempre _nuevo_id() (uuid4) para el id del pedido -- NUNCA
        str(id(object())), que se descartó justamente porque con pedidos
        concurrentes (varios meseros mandando comandas casi al mismo
        tiempo) producia ids repetidos y pedidos que se mezclaban o se
        sobreescribian entre si al cobrar o editar.

        IMPORTANTE - hilos: este método toca self.pedidos y refresca la
        UI de Kivy, así que NUNCA debe llamarse directo desde el hilo de
        Flask (servidor_mesas.py). Debe entrar siempre via
        Clock.schedule_once, para correr en el hilo principal de Kivy.
        Desde la propia app (hilo principal) se puede llamar directo,
        como hace guardar_pedido() más abajo.

        Regresa True si se guardó bien, False si hubo un error (nunca
        deja escapar la excepción, para no tumbar el hilo que la llame)."""
        try:
            # El carrito web del mesero (servidor_mesas.py) manda el
            # comentario del platillo bajo la clave 'nota' (JSON plano,
            # sin el guion bajo que usa la UI de la cajera). Se normaliza
            # aqui, en el punto UNICO de entrada, para que TODO lo demas
            # (comanda de cocina, Pedidos Activos, modal de mesa,
            # registrar_venta) solo tenga que conocer una sola clave:
            # '_nota'. Si el item ya trae '_nota' (pedido armado desde la
            # propia app) se respeta tal cual.
            for _it in items_nuevos:
                if not _it.get("_nota") and _it.get("nota"):
                    _it["_nota"] = _it["nota"]

            # Si la cajera movió esta mesa con CAMBIAR MESA (ver
            # _mover_pedido_a_mesa) DESPUÉS de que el mesero cargó su
            # pantalla, la comanda todavía llega con el nombre viejo.
            # Se redirige sola al nombre nuevo -- así nunca se crea un
            # pedido fantasma duplicado en la mesa que ya quedó libre.
            mesa_resuelta = self._resolver_mesa_movida(mesa)
            if mesa_resuelta != mesa:
                print(f"[procesar_pedido_entrante] '{mesa}' se movió a "
                     f"'{mesa_resuelta}', redirigiendo la comanda")
                mesa = mesa_resuelta

            pedido_existente = next(
                (p for p in self.pedidos
                 if p.get("tipo") == "mesa" and p.get("mesa") == mesa),
                None
            )
            if pedido_existente:
                pedido_existente["items"].extend(items_nuevos)
                pedido_existente["total"] = sum(
                    i["precio"] * i.get("qty", 1) for i in pedido_existente["items"]
                )
            else:
                total = sum(i["precio"] * i.get("qty", 1) for i in items_nuevos)
                self.pedidos.append({
                    "id": _nuevo_id(),
                    "tipo": "mesa", "mesa": mesa,
                    "nombre_dom": None,
                    "items": items_nuevos,
                    "total": total,
                    "hora": datetime.now().strftime("%H:%M"),
                    "empleado": empleado,
                })

            self.refrescar_mesas()
            self.refrescar_stats()
            try:
                if self.root and self.root.current == "activos":
                    self.refrescar_lista_activos()
            except Exception:
                pass
            # Comanda de cocina: se manda SIEMPRE que entran items nuevos
            # a una mesa por este punto centralizado (tanto si los mando
            # la cajera desde guardar_pedido() como si los mando un
            # mesero via servidor_mesas.py) -- asi el chef se entera igual
            # sin importar quien tomo la orden.
            try:
                self.imprimir_comanda_cocina(mesa, None, empleado, items_nuevos)
            except Exception:
                pass
            return True
        except Exception:
            texto_tb = traceback.format_exc()
            print(f"[procesar_pedido_entrante] Error agregando pedido de mesa '{mesa}':\n{texto_tb}")
            _cp = getattr(self, "_checkpoint_externo", None)
            if _cp:
                _cp(f"[procesar_pedido_entrante] ERROR mesa={mesa}: {texto_tb.splitlines()[-1]}")
            return False

    def guardar_pedido(self):
        if not self.orden_actual:
            _snack("Agrega al menos un producto"); return
        sc = self.root.get_screen("orden")
        total = sum(i["precio"] * i.get("qty", 1) for i in self.orden_actual)

        if self.tipo_orden == "domicilio":
            nombre   = sc.ids.campo_nombre.text.strip()
            telefono = sc.ids.campo_telefono.text.strip()
            if not nombre:
                _snack("Ingresa el nombre del cliente"); return
            pedido = {
                "id": _nuevo_id(),
                "tipo": "domicilio", "mesa": None,
                "nombre_dom": nombre,
                "telefono": telefono,
                "direccion": sc.ids.campo_direccion.text.strip(),
                "items": copy.deepcopy(self.orden_actual),
                "total": total,
                "hora": datetime.now().strftime("%H:%M"),
                "empleado": self._empleado_sel,
            }
            self.pedidos.append(pedido)
            self.imprimir_comanda_cocina(None, nombre, self._empleado_sel,
                                         copy.deepcopy(self.orden_actual))

        else:
            eid = getattr(self, "_pedido_editando_id", None)
            if eid:
                items_agregados = self._items_agregados_desde_edicion()
                for p in self.pedidos:
                    if p["id"] == eid:
                        p["items"] = copy.deepcopy(self.orden_actual)
                        p["total"] = total
                        break
                # Mesa ya abierta a la que la cajera le agrega productos
                # desde su propia pantalla (sin pasar por
                # procesar_pedido_entrante): se manda comanda de cocina
                # SOLO con lo nuevo, igual que cuando lo manda un mesero.
                if items_agregados:
                    try:
                        self.imprimir_comanda_cocina(
                            self.mesa_sel, None, self._empleado_sel, items_agregados
                        )
                    except Exception:
                        pass
            else:
                # Misma lógica de creación que usa servidor_mesas.py para
                # los meseros -- centralizada aquí para que ambos caminos
                # generen pedidos idénticos en forma e id.
                self.procesar_pedido_entrante(
                    self.mesa_sel, copy.deepcopy(self.orden_actual), self._empleado_sel
                )

        self._pedido_editando_id = None
        self._empleado_sel = None
        self.refrescar_mesas()
        self.refrescar_stats()
        self.ir_activos()

    # ── ACTIVOS ───────────────────────────────────────────────────────────────
    def filtrar_pedidos(self, f):
        self.filtro = f
        self.refrescar_lista_activos()

    def refrescar_lista_activos(self):
        sc  = self.root.get_screen("activos")
        box = sc.ids.lista_activos
        box.clear_widgets()

        lista = [p for p in self.pedidos
                 if self.filtro == "todos" or p["tipo"] == self.filtro]

        if not lista:
            box.add_widget(lbl(
                "No hay pedidos activos", color=[.4,.4,.4,1],
                halign="center", size_hint_y=None, height=dp(60),
            ))
            return

        for p in lista:
            n_items = len(p["items"])
            n_notas = sum(1 for it in p["items"] if (it.get("_nota") or "").strip())
            extra = 0
            if p["tipo"] == "domicilio":
                extra += dp(26)
                if p.get("telefono"):  extra += dp(22)
                if p.get("direccion"): extra += dp(22)
            h = dp(110) + n_items * dp(24) + n_notas * dp(18) + extra

            card = BoxLayout(
                orientation="vertical",
                size_hint_y=None, height=h,
                padding=dp(14), spacing=dp(6),
            )
            with card.canvas.before:
                Color(*self.OSCURO)
                card._bg = RoundedRectangle(pos=card.pos, size=card.size, radius=[dp(16)])
            card.bind(pos=lambda w,v: setattr(w._bg,'pos',v),
                      size=lambda w,v: setattr(w._bg,'size',v))

            txt_color = self.texto_contraste(self.OSCURO)
            titulo = (f"[b]{p['nombre_dom']}[/b]  |  Domicilio"
                      if p["tipo"] == "domicilio" else f"[b]{p['mesa']}[/b]")
            card.add_widget(lbl(
                f"{titulo}  {p['hora']}", markup=True, color=txt_color,
                font_size="14sp", size_hint_y=None, height=dp(26),
            ))

            if p["tipo"] == "domicilio":
                if p.get("telefono"):
                    card.add_widget(lbl(
                        f"Tel: {p['telefono']}", color=txt_color[:3] + [0.65],
                        font_size="12sp", size_hint_y=None, height=dp(20),
                    ))
                if p.get("direccion"):
                    card.add_widget(lbl(
                        f"Dir: {p['direccion']}", color=txt_color[:3] + [0.65],
                        font_size="12sp", size_hint_y=None, height=dp(20),
                    ))

            for it in p["items"]:
                qty = it.get("qty",1)
                card.add_widget(lbl(
                    f"  {qty}x {it['nombre']}  |  ${it['precio']*qty:.0f}",
                    color=txt_color[:3] + [0.8], font_size="13sp",
                    size_hint_y=None, height=dp(22),
                ))
                nota = (it.get("_nota") or "").strip()
                if nota:
                    card.add_widget(lbl(
                        f"     📝 {nota}", color=txt_color[:3] + [0.9],
                        font_size="11sp", shorten=True,
                        size_hint_y=None, height=dp(18),
                    ))

            card.add_widget(lbl(
                f"[b]TOTAL: ${p['total']:.0f}[/b]", markup=True, color=self.texto_contraste(self.OSCURO),
                font_size="15sp", size_hint_y=None, height=dp(30),
            ))

            btns = BoxLayout(
                orientation="horizontal", spacing=dp(8),
                size_hint_y=None, height=dp(40),
            )
            btn_e = btn_flat("ELIMINAR", color=txt_color[:3] + [0.7],
                             size_hint_x=0.34, size_hint_y=None, height=dp(40))
            btn_t = btn_flat("TICKET", color=self.texto_contraste(self.OSCURO),
                             size_hint_x=0.30, size_hint_y=None, height=dp(40))
            btn_c = btn_raised("COBRADO", bg=self.ACCENT,
                               size_hint_x=0.36, size_hint_y=None, height=dp(40))
            pid = p["id"]
            btn_e.bind(on_press=lambda inst, i=pid: self._confirmar_eliminar_pedido(i))
            btn_t.bind(on_press=lambda inst, ped=p: self._abrir_ticket(
                ([f"{ped['nombre_dom']}  |  Domicilio", f"Hora: {ped['hora']}"] +
                 ([f"Tel: {ped['telefono']}"] if ped.get("telefono") else []) +
                 ([f"Dir: {ped['direccion']}"] if ped.get("direccion") else [])
                 if ped["tipo"] == "domicilio" else
                 [f"Mesa: {ped['mesa']}", f"Hora: {ped['hora']}"]) +
                ([f"Atendió: {ped['empleado']}"] if ped.get("empleado") else []),
                ped["items"], ped["total"], titulo="TICKET DE VENTA",
            ))
            btn_c.bind(on_press=lambda inst, i=pid: self._dialog_forma_pago(i))
            btns.add_widget(btn_e)
            btns.add_widget(btn_t)
            btns.add_widget(btn_c)
            card.add_widget(btns)
            box.add_widget(card)


    def _dialog_forma_pago(self, pid):
        """Pregunta si el pago fue en efectivo o transferencia antes de cobrar."""
        pedido = next((p for p in self.pedidos if p["id"] == pid), None)
        if not pedido:
            return
        total = pedido.get("total", 0)

        content = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(12))
        content.add_widget(lbl(
            "[b]FORMA DE PAGO[/b]", markup=True, color=self.texto_contraste(self.OSCURO),
            font_size="16sp", halign="center", size_hint_y=None, height=dp(28),
        ))
        content.add_widget(lbl(
            f"[b]Total a cobrar: ${total:,.0f}[/b]",
            markup=True, color=self.texto_contraste(self.OSCURO), font_size="16sp",
            halign="center", size_hint_y=None, height=dp(36),
        ))
        content.add_widget(lbl(
            "¿Como pago el cliente?",
            color=self.texto_contraste(self.OSCURO), font_size="14sp",
            halign="center", size_hint_y=None, height=dp(28),
        ))

        popup_ref = [None]

        def _pagar(forma):
            if popup_ref[0]:
                popup_ref[0].dismiss()
            if forma == "efectivo":
                # El efectivo NUNCA se cobra directo: primero se pregunta
                # con cuánto pagó el cliente, para poder calcular el
                # cambio exacto (ver _dialog_efectivo_recibido).
                self._dialog_efectivo_recibido(pid, total)
            else:
                self._cobrar_pedido(pid, forma)

        b_ef  = btn_raised("EFECTIVO", bg=self.ACCENT,
                            size_hint_y=None, height=dp(48), font_size="14sp")
        b_tar = btn_raised("TARJETA / TRANSFERENCIA", bg=self.ROJO,
                            size_hint_y=None, height=dp(48), font_size="13sp")
        b_can = btn_flat("Cancelar", color=self.texto_contraste(self.OSCURO)[:3] + [0.6],
                          size_hint_y=None, height=dp(36))

        b_ef.bind(on_press=lambda *_: _pagar("efectivo"))
        b_tar.bind(on_press=lambda *_: _pagar("transferencia"))

        content.add_widget(b_ef)
        content.add_widget(b_tar)
        content.add_widget(b_can)

        popup = Popup(
            title="", separator_height=0,
            content=content,
            size_hint=(0.82, None), height=dp(320),
            background_color=self.OSCURO,
        )
        popup_ref[0] = popup
        b_can.bind(on_press=lambda *_: popup.dismiss())
        popup.open()

    def _dialog_efectivo_recibido(self, pid, total):
        """Antes de cobrar en efectivo, pregunta con cuánto pagó el
        cliente y calcula el cambio exacto (recibido - total) para que
        la cajera no tenga que sacarlo a mano. 'Pago exacto' es un
        atajo para cuando el cliente no pide cambio."""
        content = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(10))
        content.add_widget(lbl(
            "[b]PAGO EN EFECTIVO[/b]", markup=True, color=self.texto_contraste(self.OSCURO),
            font_size="16sp", halign="center", size_hint_y=None, height=dp(28),
        ))
        content.add_widget(lbl(
            f"[b]Total a cobrar: ${total:,.0f}[/b]",
            markup=True, color=self.texto_contraste(self.OSCURO), font_size="16sp",
            halign="center", size_hint_y=None, height=dp(32),
        ))
        content.add_widget(lbl(
            "¿Con cuánto pagó el cliente?",
            color=self.texto_contraste(self.OSCURO), font_size="14sp",
            halign="center", size_hint_y=None, height=dp(26),
        ))

        campo_monto = campo_texto(hint="Monto recibido", input_filter="float")
        content.add_widget(campo_monto)

        lbl_cambio = lbl(
            "", markup=True, color=self.texto_contraste(self.OSCURO), font_size="16sp",
            halign="center", size_hint_y=None, height=dp(30),
        )
        content.add_widget(lbl_cambio)

        lbl_error = lbl(
            "", color=self.texto_contraste(self.OSCURO), font_size="12sp", halign="center",
            size_hint_y=None, height=dp(20),
        )
        content.add_widget(lbl_error)

        def _recalcular(*_):
            txt = (campo_monto.text or "").strip().replace(",", "")
            lbl_error.text = ""
            if not txt:
                lbl_cambio.text = ""
                return
            try:
                recibido = float(txt)
            except ValueError:
                lbl_cambio.text = ""
                return
            cambio = recibido - total
            if cambio < 0:
                lbl_cambio.text = ""
                lbl_error.text = "El monto es menor al total a cobrar"
            else:
                lbl_cambio.text = f"[b]Cambio a entregar: ${cambio:,.0f}[/b]"

        campo_monto.bind(text=_recalcular)

        popup_ref2 = [None]

        def _confirmar(*_):
            txt = (campo_monto.text or "").strip().replace(",", "")
            try:
                recibido = float(txt) if txt else total
            except ValueError:
                lbl_error.text = "Ingresa un monto válido"
                return
            if recibido < total:
                lbl_error.text = "El monto es menor al total a cobrar"
                return
            cambio = recibido - total
            if popup_ref2[0]:
                popup_ref2[0].dismiss()
            self._cobrar_pedido(pid, "efectivo")
            if cambio > 0:
                _snack(f"Cobrado (Efectivo)  •  Cambio: ${cambio:,.0f}")
            else:
                _snack("Cobrado (Efectivo)  •  Pago exacto")

        def _pago_exacto(*_):
            campo_monto.text = f"{total:.0f}"
            _confirmar()

        b_confirmar = btn_raised("COBRAR", bg=self.ACCENT,
                                  size_hint_y=None, height=dp(46), font_size="14sp")
        b_exacto = btn_flat("Pago exacto (sin cambio)",
                             color=self.texto_contraste(self.OSCURO)[:3] + [0.75],
                             size_hint_y=None, height=dp(32), font_size="12sp")
        b_can2 = btn_flat("Cancelar", color=self.texto_contraste(self.OSCURO)[:3] + [0.6],
                          size_hint_y=None, height=dp(36))

        b_confirmar.bind(on_press=_confirmar)
        b_exacto.bind(on_press=_pago_exacto)

        content.add_widget(b_confirmar)
        content.add_widget(b_exacto)
        content.add_widget(b_can2)

        popup2 = Popup(
            title="", separator_height=0,
            content=content,
            size_hint=(0.86, None), height=dp(420),
            background_color=self.OSCURO,
        )
        popup_ref2[0] = popup2
        b_can2.bind(on_press=lambda *_: popup2.dismiss())
        popup2.open()
        Clock.schedule_once(lambda dt: setattr(campo_monto, "focus", True), 0.15)
        campo_monto.bind(on_text_validate=lambda *_: _confirmar())

    def _cobrar_pedido(self, pid, forma_pago="efectivo"):
        pedido = next((p for p in self.pedidos if p["id"] == pid), None)
        if not pedido:
            return

        guardado_ok = self._registrar_venta_db(
            pedido["items"],
            pedido.get("tipo", "mesa"),
            pedido_id=pedido["id"],
            mesa_nombre=pedido.get("mesa") or "",
            forma_pago=forma_pago,
        )

        if not guardado_ok:
            # La venta NO quedo guardada en la BD (se hizo ROLLBACK
            # completo). El pedido se queda en "activos" para poder
            # reintentar el cobro: si lo elimineramos aqui, el dinero
            # cobrado en la mesa desaparecia sin dejar ningun registro.
            self._alerta_cobro_fallido(pedido)
            return

        self.pedidos = [p for p in self.pedidos if p["id"] != pid]
        self.refrescar_mesas(); self.refrescar_stats()
        self.refrescar_lista_activos()
        _snack(f"Cobrado  ({'Efectivo' if forma_pago=='efectivo' else 'Tarjeta/Transf.'})")

        if forma_pago == "efectivo":
            # Silencioso: si no hay impresora configurada o esta apagada,
            # no interrumpe el cobro -- solo no abre el cajon.
            self._impresora_bt.abrir_cajon()

    def _alerta_cobro_fallido(self, pedido):
        """Popup bloqueante (no se puede cerrar tocando fuera) para
        cuando _registrar_venta_db devuelve False. Es deliberadamente
        mas intrusivo que un _snack: un mensaje de 2.5 segundos se puede
        pasar por alto en un negocio con movimiento, y este error
        significa que un cobro real NO quedo registrado en ningun lado."""
        mesa_o_dom = pedido.get("mesa") or pedido.get("nombre_dom") or "el pedido"
        content = BoxLayout(orientation="vertical", padding=dp(14), spacing=dp(10))
        content.add_widget(lbl(
            f"No se pudo guardar el cobro de {mesa_o_dom} en la base de "
            f"datos.\n\nEl pedido NO se elimino de Activos para que "
            f"puedas intentar cobrarlo de nuevo.",
            color=_texto_contraste(self.OSCURO), font_size="14sp",
            halign="center", auto_height=True,
        ))
        b_ok = btn_raised("ENTENDIDO", bg=self.ROJO, size_hint_y=None, height=dp(40))
        content.add_widget(b_ok)
        popup = Popup(
            title="Error al cobrar",
            content=content,
            size_hint=(0.85, None), height=dp(240),
            background_color=self.OSCURO,
            auto_dismiss=False,
        )
        b_ok.bind(on_press=lambda *_: popup.dismiss())
        popup.open()

    def _registrar_perdida_fantasma(self, tipo, detalle, motivo, monto):
        """Registra un producto o una cuenta cancelada YA GUARDADA en su
        PROPIA tabla ('perdidas_fantasma'), separada por completo de
        'gastos'. A propósito NO se mezcla con los gastos de caja
        reales (compras, propinas, etc.): esto es solo un contador
        informativo de lo que se canceló después de guardado, para que
        NO reste de la ganancia neta ni del total en caja de Cierre de
        Caja -- únicamente se suma entre sí y se muestra aparte, como
        'pérdida fantasma' de auditoría. Ver abrir_cierre_caja y
        _cargar_estadisticas para donde se lee y se pinta."""
        self.db.registrar_perdida_fantasma(tipo, detalle, motivo, monto)

    def _confirmar_eliminar_pedido(self, pid):
        """Pide un motivo OBLIGATORIO antes de eliminar una cuenta completa
        ya guardada (mesa o domicilio). Sin motivo no deja continuar --
        así ninguna cuenta puede 'desaparecer' de Activos sin dejar
        rastro. El motivo y el total de la cuenta quedan registrados
        como pérdida fantasma (ver _registrar_perdida_fantasma) -- no
        afecta la ganancia neta ni el total en caja."""
        pedido = next((p for p in self.pedidos if p["id"] == pid), None)
        if not pedido:
            return
        detalle = pedido.get("mesa") or pedido.get("nombre_dom") or "esta cuenta"
        total = pedido.get("total", 0)

        f_razon = campo_texto("Motivo de la eliminación *", multiline=True, height=dp(70))

        content = BoxLayout(orientation="vertical", padding=dp(18), spacing=dp(10))
        content.add_widget(lbl(
            "[b]ELIMINAR CUENTA[/b]", markup=True, color=self.texto_contraste(self.OSCURO),
            font_size="15sp", halign="center", size_hint_y=None, height=dp(26),
        ))
        content.add_widget(lbl(
            f"{detalle}  —  ${total:,.0f}", markup=False,
            color=self.texto_contraste(self.OSCURO), font_size="14sp",
            halign="center", size_hint_y=None, height=dp(24),
        ))
        content.add_widget(lbl(
            "Se registrará como pérdida fantasma en el cierre de caja "
            "(no afecta la ganancia ni el total en caja). "
            "Escribe el motivo para poder continuar:",
            color=self.texto_contraste(self.OSCURO)[:3] + [0.65], font_size="12sp",
            halign="center", size_hint_y=None, height=dp(48), auto_height=True,
        ))
        content.add_widget(f_razon)

        popup_ref = [None]

        def _confirmar(*_):
            razon = f_razon.text.strip()
            if not razon:
                _snack("Escribe un motivo para poder eliminar la cuenta")
                return
            if popup_ref[0]:
                popup_ref[0].dismiss()
            self._eliminar_pedido(pid, razon)

        btns = BoxLayout(orientation="horizontal", size_hint_y=None,
                         height=dp(44), spacing=dp(10))
        b_can = btn_flat("Cancelar", color=self.texto_contraste(self.OSCURO),
                         size_hint_y=None, height=dp(40))
        b_ok  = btn_raised("ELIMINAR", bg=self.ROJO, size_hint_y=None, height=dp(40))
        btns.add_widget(b_can)
        btns.add_widget(b_ok)
        content.add_widget(btns)

        content.size_hint_y = None
        content.bind(minimum_height=content.setter("height"))

        popup = Popup(title="", separator_height=0, content=content,
                      size_hint=(0.86, None), background_color=self.OSCURO)

        def _sync_popup_height(*_):
            popup.height = content.height + dp(24)
        content.bind(minimum_height=_sync_popup_height)
        _sync_popup_height()

        popup_ref[0] = popup
        b_can.bind(on_press=lambda *_: popup.dismiss())
        b_ok.bind(on_press=_confirmar)
        popup.open()

    def _eliminar_pedido(self, pid, razon):
        pedido = next((p for p in self.pedidos if p["id"] == pid), None)
        if not pedido:
            return
        detalle = pedido.get("mesa") or pedido.get("nombre_dom") or "cuenta"
        total = pedido.get("total", 0)
        self._registrar_perdida_fantasma("cuenta", detalle, razon, total)

        self.pedidos = [p for p in self.pedidos if p["id"] != pid]
        self.refrescar_mesas(); self.refrescar_stats()
        self.refrescar_lista_activos()
        _snack(f"Cuenta eliminada  —  pérdida fantasma registrada: ${total:,.0f}")

    # ── GASTOS DE CAJA ────────────────────────────────────────────────────────
    def abrir_gastos_caja(self):
        """Popup para registrar un gasto de caja (nombre + monto)."""
        f_nombre = campo_texto("Nombre del gasto *")
        f_monto  = campo_texto("Cantidad ($)", input_filter="float")
        encadenar_campos(f_nombre, f_monto)

        content = BoxLayout(orientation="vertical", padding=dp(14), spacing=dp(10))
        content.add_widget(lbl(
            "[b]GASTO DE CAJA[/b]", markup=True, color=self.texto_contraste(self.OSCURO),
            font_size="16sp", halign="center", size_hint_y=None, height=dp(30),
        ))
        content.add_widget(f_nombre)
        content.add_widget(f_monto)

        btns = BoxLayout(orientation="horizontal", size_hint_y=None,
                         height=dp(44), spacing=dp(8))
        b_can  = btn_flat("Cancelar", color=_texto_contraste(self.OSCURO), size_hint_y=None, height=dp(38))
        b_save = btn_raised("GUARDAR", bg=self.ROJO,
                            size_hint_y=None, height=dp(38))
        btns.add_widget(b_can)
        btns.add_widget(b_save)
        content.add_widget(btns)

        popup_ref = [None]

        def _guardar(*_):
            nombre = f_nombre.text.strip()
            monto_txt = f_monto.text.strip()
            if not nombre:
                _snack("Ingresa el nombre del gasto"); return
            try:
                monto = float(monto_txt)
                assert monto > 0
            except Exception:
                _snack("Cantidad invalida"); return
            try:
                self.db.registrar_gasto(nombre, monto)
            except Exception as e:
                _snack(f"Error al guardar: {e}"); return
            if popup_ref[0]:
                popup_ref[0].dismiss()
            _snack(f"Gasto '{nombre}' registrado  —  ${monto:,.0f}")

        b_save.bind(on_press=_guardar)
        f_monto.bind(on_text_validate=lambda *_: _guardar())

        popup = Popup(
            title="", separator_height=0,
            content=content,
            size_hint=(0.85, None), height=dp(300),
            background_color=self.OSCURO,
        )
        popup_ref[0] = popup
        b_can.bind(on_press=lambda *_: popup.dismiss())
        popup.open()

    # ── CIERRE DE CAJA ────────────────────────────────────────────────────────
    def _abrir_fondo_popup(self, fecha_str, on_guardado=None):
        """Popup pequeño para capturar cuánto dinero se dejó de fondo
        (base) en la caja al iniciar el día. Se guarda en la tabla
        fondo_caja (una fila por fecha) y se suma al efectivo del
        cierre correspondiente."""
        if self._dialog:
            return

        valor_actual = self.db.obtener_fondo_caja(fecha_str)

        content = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(12),
                            size_hint_y=None)
        content.bind(minimum_height=content.setter("height"))
        content.add_widget(lbl("Fondo de caja",
                               color=self.texto_contraste(self.OSCURO),
                               font_size="15sp", halign="center",
                               size_hint_y=None, height=dp(26)))
        content.add_widget(lbl(
            "¿Con cuánto dinero abriste la caja hoy? Este monto se "
            "suma al efectivo del cierre.",
            color=GRIS, font_size="12sp", halign="center",
            size_hint_y=None, height=dp(48), auto_height=True))

        ti = campo_texto(hint="0", input_filter="float", height=dp(46))
        if valor_actual:
            ti.text = f"{valor_actual:,.0f}"
        content.add_widget(ti)

        btns = BoxLayout(orientation="horizontal", size_hint_y=None,
                         height=dp(44), spacing=dp(10))
        b_cancelar = btn_flat("Cancelar", color=self.texto_contraste(self.OSCURO),
                              size_hint_y=None, height=dp(44))
        b_guardar  = btn_raised("Guardar", bg=self.DORADO,
                                size_hint_y=None, height=dp(44))
        btns.add_widget(b_cancelar)
        btns.add_widget(b_guardar)
        content.add_widget(btns)

        popup = Popup(title="", separator_height=0, content=content,
                      size_hint=(0.85, None), height=dp(260),
                      background_color=self.OSCURO, auto_dismiss=False)

        def _cerrar(*_):
            self._dialog = None
            popup.dismiss()
            if on_guardado:
                on_guardado()

        def _guardar(*_):
            texto = (ti.text or "").replace(",", "").strip()
            try:
                monto = float(texto) if texto else 0
            except ValueError:
                _snack("Monto invalido"); return
            try:
                self.db.guardar_fondo_caja(fecha_str, monto)
            except Exception as e:
                _snack(f"Error al guardar fondo: {e}"); return
            self._dialog = None
            popup.dismiss()
            _snack("Fondo guardado")
            if on_guardado:
                on_guardado()

        b_cancelar.bind(on_press=_cerrar)
        b_guardar.bind(on_press=_guardar)

        self._dialog = popup
        popup.open()

    def abrir_cierre_caja(self, fecha=None, solo_lectura=False):
        """Popup con el resumen financiero de un día.

        `fecha` puede ser un objeto date/datetime o un string 'YYYY-MM-DD'.
        Si no se pasa nada, se usa el día actual. Los datos siempre se
        recalculan en vivo a partir de las tablas `ventas` y `gastos`
        (ya persistidas en SQLite), así que sirve tanto para el cierre
        del día de hoy como para consultar el cierre de cualquier fecha
        pasada desde el calendario de Estadísticas.

        `solo_lectura=True` oculta el botón "REGISTRAR / EDITAR FONDO"
        para que, al consultarse desde Estadísticas, no se pueda
        modificar el fondo de caja de un día ya cerrado (evita
        maniobras de la cajera). El botón normal de CIERRE DE CAJA del
        día actual sigue llamando a esta función sin este parámetro,
        por lo que conserva la edición tal como estaba."""
        if fecha is None:
            fecha_dt = datetime.now().date()
        elif isinstance(fecha, str):
            fecha_dt = datetime.strptime(fecha, "%Y-%m-%d").date()
        elif isinstance(fecha, datetime):
            fecha_dt = fecha.date()
        else:
            fecha_dt = fecha  # ya es un date

        hoy = fecha_dt.strftime("%Y-%m-%d")

        r = self.db.obtener_cierre_caja(hoy)
        if r is None:
            _snack("Error al cargar cierre"); return

        venta_total             = r["venta_total"]
        total_pedidos           = r["total_pedidos"]
        mesas_atendidas         = r["mesas_atendidas"]
        pedidos_mesa            = r["pedidos_mesa"]
        pedidos_dom             = r["pedidos_dom"]
        total_efectivo          = r["total_efectivo"]
        total_tarjeta           = r["total_tarjeta"]
        lista_gastos            = r["lista_gastos"]
        total_gastos            = r["total_gastos"]
        lista_perdidas_fantasma = r["lista_perdidas_fantasma"]
        total_perdida_fantasma  = r["total_perdida_fantasma"]
        clientes_atendidos      = r["clientes_atendidos"]
        fondo_caja              = r["fondo_caja"]
        # Total en caja = fondo inicial + efectivo cobrado - gastos pagados
        # de caja (ver database.py:obtener_cierre_caja para el porqué de
        # cada termino, incluida la exclusión deliberada de la pérdida
        # fantasma de esta cuenta).
        total_en_caja           = r["total_en_caja"]
        ganancia_neta           = r["ganancia_neta"]
        H = dp(30)   # altura estándar por fila

        # El texto neutro de este popup usa el mismo sistema de contraste
        # que el resto de la app: el fondo real es self.OSCURO (pasado
        # abajo como background_color del Popup), y la clase Popup
        # parcheada de este archivo limpia el skin por defecto
        # (background=""), asi que background_color SI es un relleno
        # solido real -- en el tema "Clara", OSCURO es blanco puro, y el
        # texto debe verse oscuro sobre ese blanco, no claro. Los valores
        # con su propio color semantico (verde/rojo/azul/morado/naranja)
        # no cambian.
        TXT_NEUTRO      = self.texto_contraste(self.OSCURO)                # etiquetas y valores neutros
        TXT_SECUNDARIO  = self.texto_contraste(self.OSCURO)[:3] + [0.6]    # "Sin gastos hoy", notas, etc.

        # ─── helpers de layout ─────────────────────────────────────────────
        scroll = ScrollView(size_hint=(1, 1))
        box = BoxLayout(
            orientation="vertical", spacing=dp(4),
            padding=[dp(12), dp(8), dp(12), dp(8)],
            size_hint_y=None,
        )
        box.bind(minimum_height=box.setter("height"))
        scroll.add_widget(box)

        def _add_titulo(texto):
            """Sección con fondo ligeramente distinto."""
            bg = BoxLayout(size_hint_y=None, height=dp(26))
            with bg.canvas.before:
                Color(0.20, 0.20, 0.20, 1)
                bg._r = RoundedRectangle(pos=bg.pos, size=bg.size, radius=[dp(12)])
            bg.bind(pos=lambda w,v: setattr(w._r,'pos',v),
                    size=lambda w,v: setattr(w._r,'size',v))
            lb = Label(
                text=f"[b]{texto}[/b]", markup=True,
                color=self.DORADO, font_size="12sp",
                halign="left", valign="middle",
                size_hint_y=None, height=dp(26),
                padding_x=dp(6),
            )
            lb.bind(size=lambda inst,v: setattr(inst,"text_size",(v[0],None)))
            bg.add_widget(lb)
            box.add_widget(bg)

        def _add_fila(etiqueta, valor, color_v=None):
            """Fila etiqueta | valor — alturas totalmente fijas."""
            row = BoxLayout(
                orientation="horizontal",
                size_hint_y=None, height=H,
            )
            l_etq = Label(
                text=etiqueta, color=TXT_NEUTRO, font_size="13sp",
                halign="left", valign="middle",
                size_hint_x=0.60, size_hint_y=None, height=H,
            )
            l_etq.bind(size=lambda inst,v: setattr(inst,"text_size",(v[0],None)))

            l_val = Label(
                text=valor, color=color_v or TXT_NEUTRO, font_size="13sp",
                halign="right", valign="middle",
                size_hint_x=0.40, size_hint_y=None, height=H,
            )
            l_val.bind(size=lambda inst,v: setattr(inst,"text_size",(v[0],None)))

            row.add_widget(l_etq)
            row.add_widget(l_val)
            box.add_widget(row)

        def _add_fila_grande(etiqueta, valor, color_v):
            row = BoxLayout(
                orientation="horizontal",
                size_hint_y=None, height=dp(38),
            )
            l_etq = Label(
                text=f"[b]{etiqueta}[/b]", markup=True,
                color=TXT_NEUTRO, font_size="14sp",
                halign="left", valign="middle",
                size_hint_x=0.55, size_hint_y=None, height=dp(38),
            )
            l_etq.bind(size=lambda inst,v: setattr(inst,"text_size",(v[0],None)))
            l_val = Label(
                text=f"[b]{valor}[/b]", markup=True,
                color=color_v, font_size="14sp",
                halign="right", valign="middle",
                size_hint_x=0.45, size_hint_y=None, height=dp(38),
            )
            l_val.bind(size=lambda inst,v: setattr(inst,"text_size",(v[0],None)))
            row.add_widget(l_etq)
            row.add_widget(l_val)
            box.add_widget(row)

        def _add_fila_gasto(etiqueta, valor, color_v=None):
            """Como _add_fila, pero para los renglones de GASTOS: el
            motivo es texto libre que la cajera escribe (puede venir
            largo -- sobre todo el de "Pérdida en efectivo: <motivo>
            (<detalle>)" de un producto/cuenta cancelada), así que aquí
            el alto de la fila SÍ crece con el contenido real (usa el
            mismo mecanismo de auto_height que ya usa lbl()) en vez de
            quedar fijo en H, que hacía que el texto que no cabía se
            dibujara encima del renglón de abajo."""
            row = BoxLayout(orientation="horizontal", size_hint_y=None, height=H)
            l_etq = lbl(
                etiqueta, color=TXT_NEUTRO, font_size="13sp",
                halign="left", size_hint_y=None, height=H, auto_height=True,
            )
            l_etq.size_hint_x = 0.62
            l_val = Label(
                text=valor, color=color_v or TXT_NEUTRO, font_size="13sp",
                halign="right", valign="middle",
                size_hint_x=0.38, size_hint_y=1,
            )
            l_val.bind(size=lambda inst,v: setattr(inst,"text_size",v))

            row.add_widget(l_etq)
            row.add_widget(l_val)
            l_etq.bind(height=lambda inst, v: setattr(row, "height", v))
            box.add_widget(row)

        def _add_sep():
            from kivy.uix.widget import Widget as W
            sp = W(size_hint_y=None, height=dp(6))
            box.add_widget(sp)
            div = W(size_hint_y=None, height=dp(1))
            with div.canvas:
                Color(0.35, 0.35, 0.35, 1)
                div._r = Rectangle(pos=div.pos, size=div.size)
            div.bind(pos=lambda w,v: setattr(w._r,'pos',v),
                     size=lambda w,v: setattr(w._r,'size',v))
            box.add_widget(div)
            sp2 = W(size_hint_y=None, height=dp(4))
            box.add_widget(sp2)

        # ─── Encabezado ────────────────────────────────────────────────────
        cab = Label(
            text=f"[b]CIERRE  {fecha_dt.strftime('%d/%m/%Y')}[/b]",
            markup=True, color=TXT_NEUTRO, font_size="15sp",
            halign="center", valign="middle",
            size_hint_y=None, height=dp(34),
        )
        cab.bind(size=lambda inst,v: setattr(inst,"text_size",v))
        box.add_widget(cab)
        _add_sep()

        # ─── Ventas ────────────────────────────────────────────────────────
        _add_titulo("VENTAS DEL DIA")
        _add_fila("Venta total:",          f"${venta_total:,.0f}")
        _add_fila("Total pedidos:",        str(total_pedidos))
        _add_fila("  Pedidos mesa:",       str(pedidos_mesa))
        _add_fila("  Pedidos domicilio:",  str(pedidos_dom))
        _add_fila("Mesas atendidas:",      str(mesas_atendidas))
        _add_fila("Clientes atendidos:",   str(int(clientes_atendidos)))
        _add_sep()

        # ─── Forma de pago ─────────────────────────────────────────────────
        _add_titulo("FORMA DE PAGO")
        _add_fila("Efectivo:",                f"${total_efectivo:,.0f}", _verde_contraste(self.OSCURO))
        _add_fila("Tarjeta/Transferencia:",   f"${total_tarjeta:,.0f}")
        _add_sep()

        # ─── Gastos ────────────────────────────────────────────────────────
        from kivy.uix.widget import Widget as W
        _add_titulo("GASTOS DE CAJA")
        if lista_gastos:
            for gnom, gmonto in lista_gastos:
                _add_fila_gasto(f"  {gnom}:", f"-${gmonto:,.0f}")
        else:
            lb_ng = Label(
                text="Sin gastos hoy", color=TXT_SECUNDARIO, font_size="12sp",
                halign="left", valign="middle",
                size_hint_y=None, height=H,
            )
            lb_ng.bind(size=lambda inst,v: setattr(inst,"text_size",(v[0],None)))
            box.add_widget(lb_ng)
        _add_fila("Total gastos:", f"-${total_gastos:,.0f}")
        _add_sep()

        # ─── Pérdida fantasma ──────────────────────────────────────────────
        # Productos/cuentas cancelados YA GUARDADOS. Se muestra por separado
        # a propósito -- NO se suma a "Total gastos", NO afecta "Total en
        # caja" ni "GANANCIA NETA" de abajo. Solo se suma entre sí, como
        # contador informativo/de auditoría de lo que se canceló.
        _add_titulo("PÉRDIDA FANTASMA (no afecta ganancia ni caja)")
        if lista_perdidas_fantasma:
            for ptipo, pdetalle, pmotivo, pmonto in lista_perdidas_fantasma:
                etiqueta_tipo = "Cuenta" if ptipo == "cuenta" else "Producto"
                texto = f"  {etiqueta_tipo}: {pdetalle} — Motivo: {pmotivo}"
                _add_fila_gasto(texto, f"-${pmonto:,.0f}")
        else:
            lb_npf = Label(
                text="Sin pérdidas fantasma hoy", color=TXT_SECUNDARIO, font_size="12sp",
                halign="left", valign="middle",
                size_hint_y=None, height=H,
            )
            lb_npf.bind(size=lambda inst,v: setattr(inst,"text_size",(v[0],None)))
            box.add_widget(lb_npf)
        _add_fila("Total pérdida fantasma:", f"-${total_perdida_fantasma:,.0f}")
        _add_sep()

        # ─── Fondo de caja ─────────────────────────────────────────────────
        _add_titulo("FONDO DE CAJA")
        _add_fila("Fondo inicial:",           f"${fondo_caja:,.0f}",     TXT_SECUNDARIO)
        _add_fila("Total en caja (efectivo):", f"${total_en_caja:,.0f}")
        box.add_widget(W(size_hint_y=None, height=dp(4)))
        b_fondo = None
        if not solo_lectura:
            # Solo se muestra el botón de editar/registrar fondo cuando el
            # cierre se abre desde su lugar original (botón CIERRE DE CAJA
            # del día actual). Si se abre desde Estadísticas > Fechas, se
            # omite por completo para que quede en modo solo lectura y no
            # se pueda modificar el fondo de un día ya cerrado.
            b_fondo = btn_raised("REGISTRAR / EDITAR FONDO", bg=self.DORADO,
                                 color=_texto_contraste(self.DORADO), font_size="13sp",
                                 size_hint_y=None, height=dp(44))
            box.add_widget(b_fondo)
            box.add_widget(W(size_hint_y=None, height=dp(4)))
        else:
            lb_solo_lectura = Label(
                text="Consulta de solo lectura — el fondo no se puede modificar aquí",
                color=TXT_SECUNDARIO, font_size="11sp", halign="center", valign="middle",
                size_hint_y=None, height=dp(24),
            )
            lb_solo_lectura.bind(size=lambda inst, v: setattr(inst, "text_size", (v[0], None)))
            box.add_widget(lb_solo_lectura)
        _add_sep()

        # ─── Ganancia neta ─────────────────────────────────────────────────
        color_gan = _verde_contraste(self.OSCURO) if ganancia_neta >= 0 else self.texto_contraste(self.OSCURO)
        _add_fila_grande("GANANCIA NETA:", f"${ganancia_neta:,.0f}", color_gan)

        # ─── Botón cerrar ──────────────────────────────────────────────────
        from kivy.uix.widget import Widget as W
        box.add_widget(W(size_hint_y=None, height=dp(10)))
        b_cerrar = btn_raised("Cerrar", bg=self.ROJO,
                              size_hint_y=None, height=dp(44))
        box.add_widget(b_cerrar)
        box.add_widget(W(size_hint_y=None, height=dp(6)))

        popup = Popup(
            title="", separator_height=0,
            content=scroll,
            size_hint=(0.92, 0.88),
            background_color=self.OSCURO,
        )
        b_cerrar.bind(on_press=lambda *_: popup.dismiss())
        if b_fondo is not None:
            b_fondo.bind(on_press=lambda *_: (
                popup.dismiss(),
                self._abrir_fondo_popup(hoy, lambda: self.abrir_cierre_caja(fecha=fecha_dt))
            ))
        popup.open()

    # ── CONFIG ────────────────────────────────────────────────────────────────
    def refrescar_cats_cfg(self):
        """Repinta la lista de categorias (Config > Menu). La categoria
        activa ya NO se marca con un fondo rojo solido (fatiga visual):
        usa el acento verde esmeralda al 15% de opacidad + una barra
        vertical en el borde izquierdo, y las inactivas quedan en gris
        neutro (#757575). Es puramente visual -- self.cat_cfg y el orden
        de self.menu (la fuente de verdad) no cambian."""
        sc  = self.root.get_screen("config")
        box = sc.ids.lista_cats_cfg
        box.clear_widgets()
        for cat in self.menu:
            activo = (cat == self.cat_cfg)
            fila = ButtonBehavior_BoxLayout_cfg(
                orientation="horizontal", size_hint_y=None, height=dp(44),
                padding=(dp(10), 0), spacing=dp(8),
            )
            with fila.canvas.before:
                Color(*(CFG_EMERALD_SOFT if activo else [1, 1, 1, 0]))
                fila._bg = RoundedRectangle(pos=fila.pos, size=fila.size, radius=[dp(10)])
                Color(*(CFG_EMERALD if activo else [0, 0, 0, 0]))
                fila._barra = RoundedRectangle(pos=fila.pos, size=(dp(4), fila.height),
                                               radius=[dp(2)])

            def _redraw(w, *_a):
                w._bg.pos = w.pos
                w._bg.size = w.size
                w._barra.pos = w.pos
                w._barra.size = (dp(4), w.height)
            fila.bind(pos=_redraw, size=_redraw)

            icono_lbl = lbl(self.icono(_icono_categoria_cfg(cat)),
                            color=(CFG_EMERALD if activo else CFG_TEXTO_GRIS),
                            font_size="17sp", markup=True,
                            size_hint_y=None, height=dp(44))
            icono_lbl.size_hint_x = None
            icono_lbl.width = dp(26)
            fila.add_widget(icono_lbl)

            nombre_lbl = Label(
                text=(f"[b]{cat}[/b]" if activo else cat), markup=True,
                color=(CFG_TEXTO if activo else CFG_TEXTO_GRIS),
                font_size="14sp", halign="left", valign="middle",
                shorten=True, shorten_from="right",
                size_hint_y=None, height=dp(44),
            )
            nombre_lbl.bind(size=lambda inst, v: setattr(inst, "text_size", v))
            fila.add_widget(nombre_lbl)

            if activo:
                chevron = lbl(self.icono("chevron-right"), color=CFG_EMERALD,
                              font_size="15sp", markup=True,
                              size_hint_y=None, height=dp(44))
                chevron.size_hint_x = None
                chevron.width = dp(20)
                fila.add_widget(chevron)

            c = cat
            fila.bind(on_release=lambda inst, c=c: self._sel_cat_cfg(c))
            box.add_widget(fila)

    def _sel_cat_cfg(self, cat):
        self.cat_cfg = cat
        self._prod_cfg_abierto = None
        sc = self.root.get_screen("config")
        sc.ids.lbl_cat_cfg.text = cat
        self.refrescar_cats_cfg()
        self._rebuild_prods_cfg()

    def _rebuild_prods_cfg(self):
        """Repinta la lista de productos de la categoria activa (Config >
        Menu). Cada fila: nombre a la izquierda, precio a la derecha, y un
        boton "..." (kebab, patron estandar de Material Design) al extremo
        derecho. Editar/Eliminar YA NO estan siempre visibles -- se
        revelan DENTRO de la misma fila solo al tocar el "...", igual que
        un menu contextual nativo. Solo un producto puede tener sus
        acciones abiertas a la vez (self._prod_cfg_abierto guarda su id);
        tocar el "..." de otro producto, o la "X" de cierre, lo colapsa de
        nuevo. El borrado sigue sin ser inmediato: el icono de basura abre
        _confirmar_eliminar_producto_cfg() y solo despues de confirmar se
        llama a _elim_prod_cfg(), que es la que de verdad persiste el
        cambio -- esa funcion no se toco."""
        sc  = self.root.get_screen("config")
        box = sc.ids.lista_prods_cfg
        box.clear_widgets()
        if not self.cat_cfg:
            return
        if not hasattr(self, "_prod_cfg_abierto"):
            self._prod_cfg_abierto = None  # id del producto con acciones visibles
        for prod in self.menu.get(self.cat_cfg, []):
            pid = prod["id"]
            # "Costo Extra" (y cualquier producto marcado es_extra) es un
            # producto especial de sistema: la app siempre asume que
            # existe en la categoria "Otros" para poder cobrar cargos
            # variables (propina, envio especial, etc). Por eso nunca se
            # muestran sus acciones de editar/eliminar -- protegido=True
            # fuerza abierto=False sin importar el estado guardado en
            # self._prod_cfg_abierto.
            protegido = bool(prod.get("es_extra"))
            abierto = (self._prod_cfg_abierto == pid) and not protegido
            row = BoxLayout(
                orientation="horizontal", size_hint_y=None, height=dp(48),
                padding=(dp(12), dp(6)), spacing=dp(6),
            )
            with row.canvas.before:
                Color(*CFG_FONDO)
                row._bg = RoundedRectangle(pos=row.pos, size=row.size, radius=[dp(10)])
            row.bind(pos=lambda w,v: setattr(w._bg,'pos',v),
                     size=lambda w,v: setattr(w._bg,'size',v))

            nombre_lbl = Label(
                text=f"[b]{prod['nombre']}[/b]", markup=True,
                color=CFG_TEXTO, font_size="12sp",
                halign="left", valign="middle",
                shorten=True, shorten_from="right",
                size_hint_y=None, height=dp(48),
            )
            nombre_lbl.bind(size=lambda inst, v: setattr(inst, "text_size", v))
            row.add_widget(nombre_lbl)

            precio_lbl = lbl(
                f"${prod['precio']:.0f}", color=CFG_EMERALD, font_size="12sp",
                bold=True, halign="right", size_hint_y=None, height=dp(48),
                shorten=True,
            )
            precio_lbl.size_hint_x = None
            precio_lbl.width = dp(56)
            row.add_widget(precio_lbl)

            if abierto:
                # Acciones reveladas DENTRO de la misma fila: editar,
                # eliminar y cerrar (vuelve a dejar solo el "...").
                acciones = BoxLayout(
                    orientation="horizontal", size_hint_x=None, width=dp(96), spacing=dp(2),
                )
                btn_edit = Button(
                    text=self.icono("pencil-outline"), markup=True,
                    background_color=[0,0,0,0], color=CFG_EMERALD, font_size="15sp",
                    size_hint=(None, None), size=(dp(30), dp(30)),
                )
                _set_bg(btn_edit, [CFG_EMERALD[0], CFG_EMERALD[1], CFG_EMERALD[2], 0.10],
                        radius=dp(15))
                btn_del = Button(
                    text=self.icono("delete-outline"), markup=True,
                    background_color=[0,0,0,0], color=CFG_ALERTA, font_size="15sp",
                    size_hint=(None, None), size=(dp(30), dp(30)),
                )
                _set_bg(btn_del, [CFG_ALERTA[0], CFG_ALERTA[1], CFG_ALERTA[2], 0.10],
                        radius=dp(15))
                btn_cerrar = Button(
                    text=self.icono("close"), markup=True,
                    background_color=[0,0,0,0], color=CFG_TEXTO_GRIS, font_size="13sp",
                    size_hint=(None, None), size=(dp(30), dp(30)),
                )
                btn_edit.bind(on_press=lambda inst, p=prod: self._dialog_editar_precio(p))
                btn_del.bind(on_press=lambda inst, p=prod: self._confirmar_eliminar_producto_cfg(p))
                btn_cerrar.bind(on_press=lambda inst, pid=pid: self._toggle_prod_cfg_acciones(pid))
                acciones.add_widget(btn_edit)
                acciones.add_widget(btn_del)
                acciones.add_widget(btn_cerrar)
                row.add_widget(acciones)
            elif protegido:
                # Candado en vez de "...": Costo Extra no se puede tocar
                # desde aqui. Al presionarlo solo se avisa por que, no se
                # abre ningun menu de acciones.
                cont_lock = BoxLayout(orientation="horizontal", size_hint_x=None, width=dp(34))
                btn_lock = Button(
                    text=self.icono("lock-outline"), markup=True,
                    background_color=[0,0,0,0], color=CFG_TEXTO_GRIS, font_size="16sp",
                    size_hint=(None, None), size=(dp(30), dp(30)),
                )
                btn_lock.bind(on_press=lambda *_: _snack(
                    "Costo Extra es un producto del sistema: no se puede editar ni eliminar"
                ))
                cont_lock.add_widget(btn_lock)
                row.add_widget(cont_lock)
            else:
                cont_kebab = BoxLayout(orientation="horizontal", size_hint_x=None, width=dp(34))
                btn_kebab = Button(
                    text=self.icono("dots-vertical"), markup=True,
                    background_color=[0,0,0,0], color=CFG_TEXTO_GRIS, font_size="16sp",
                    size_hint=(None, None), size=(dp(30), dp(30)),
                )
                btn_kebab.bind(on_press=lambda inst, pid=pid: self._toggle_prod_cfg_acciones(pid))
                cont_kebab.add_widget(btn_kebab)
                row.add_widget(cont_kebab)

            box.add_widget(row)

    def _toggle_prod_cfg_acciones(self, pid):
        """Abre/cierra el menu de acciones (editar/eliminar) de UN producto
        dentro de su misma fila. Si ya habia otro abierto, se cierra solo
        (unicamente un producto puede tener sus acciones visibles a la
        vez, para no llenar la lista de iconos)."""
        prod = next((p for p in self.menu.get(self.cat_cfg, []) if p["id"] == pid), None)
        if prod and prod.get("es_extra"):
            return  # nunca se abre para Costo Extra (ver _rebuild_prods_cfg)
        self._prod_cfg_abierto = None if self._prod_cfg_abierto == pid else pid
        self._rebuild_prods_cfg()

    def agregar_categoria(self):
        sc     = self.root.get_screen("config")
        nombre = sc.ids.campo_nueva_cat.text.strip()
        if not nombre: return
        if nombre in self.menu:
            _snack("Esa categoria ya existe"); return
        self.menu[nombre] = []
        self._guardar_menu()
        sc.ids.campo_nueva_cat.text = ""
        self._sel_cat_cfg(nombre)

    def agregar_producto_cfg(self):
        sc = self.root.get_screen("config")
        if not self.cat_cfg:
            _snack("Selecciona una categoria primero"); return
        nombre = sc.ids.campo_prod_nombre.text.strip()
        precio_txt = sc.ids.campo_prod_precio.text.strip()
        if not nombre or not precio_txt:
            _snack("Nombre y precio requeridos"); return
        try:
            precio = float(precio_txt)
        except ValueError:
            _snack("Precio invalido"); return
        self.menu[self.cat_cfg].append({
            "id": f"u_{_nuevo_id()}", "nombre": nombre, "precio": precio
        })
        self._guardar_menu()
        sc.ids.campo_prod_nombre.text = ""
        sc.ids.campo_prod_precio.text = ""
        self._rebuild_prods_cfg()
        _snack(f"'{nombre}' agregado")

    def _dialog_editar_precio(self, prod):
        if prod.get("es_extra"):
            _snack("Costo Extra no se puede editar")
            return
        self._edit_prod = prod
        self._f_nuevo_precio = campo_texto(
            "Nuevo precio", input_filter="float",
        )
        self._f_nuevo_precio.text = str(
            int(prod["precio"]) if prod["precio"] == int(prod["precio"])
            else prod["precio"]
        )
        content = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))
        content.add_widget(self._f_nuevo_precio)
        btns = BoxLayout(orientation="horizontal", size_hint_y=None,
                         height=dp(44), spacing=dp(8))
        b_cancel = btn_flat("Cancelar", color=CFG_TEXTO_GRIS,
                            size_hint_y=None, height=dp(38))
        b_save   = btn_raised("Guardar", bg=CFG_EMERALD,
                              size_hint_y=None, height=dp(38))
        btns.add_widget(b_cancel)
        btns.add_widget(b_save)
        content.add_widget(btns)

        popup = Popup(
            title=f"Editar: {prod['nombre']}",
            title_color=CFG_TEXTO,
            content=content,
            size_hint=(0.82, None), height=dp(180),
            background_color=CFG_TARJETA,
        )
        b_cancel.bind(on_press=lambda *_: popup.dismiss())
        b_save.bind(on_press=lambda *_, pp=popup: self._confirmar_editar_precio(pp))
        self._f_nuevo_precio.bind(
            on_text_validate=lambda *_, pp=popup: self._confirmar_editar_precio(pp)
        )
        self._dialog = popup
        popup.bind(on_dismiss=lambda *_: setattr(self, "_dialog", None))
        popup.open()

    def _confirmar_editar_precio(self, popup):
        try:
            nuevo = float(self._f_nuevo_precio.text.strip())
            assert nuevo >= 0
        except Exception:
            _snack("Precio invalido"); return
        self._edit_prod["precio"] = nuevo
        self._guardar_menu()
        popup.dismiss()
        self._rebuild_prods_cfg()
        _snack(f"Precio actualizado a ${nuevo:.0f}")

    def _confirmar_eliminar_producto_cfg(self, prod):
        """Dialogo de confirmacion antes de borrar un producto (Config >
        Gestion de Productos). Mismo patron de seguridad que ya se usa
        para borrar empleados (abrir_empleados > _confirmar_borrar):
        nunca se borra de inmediato al tocar el icono de basura. Solo si
        se confirma se llama a _elim_prod_cfg(), que sigue siendo la
        unica funcion que en verdad modifica self.menu y persiste."""
        if self._dialog:
            return

        content = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(14),
                            size_hint_y=None)
        content.bind(minimum_height=content.setter("height"))
        content.add_widget(lbl(
            f"¿Eliminar \"{prod['nombre']}\"?",
            color=CFG_TEXTO, font_size="15sp", halign="center",
            size_hint_y=None, height=dp(40), auto_height=True,
        ))

        btns = BoxLayout(orientation="horizontal", size_hint_y=None,
                         height=dp(44), spacing=dp(10))
        b_cancelar = btn_flat("CANCELAR", color=CFG_TEXTO_GRIS,
                              size_hint_y=None, height=dp(42))
        _set_bg(b_cancelar, [0.929, 0.929, 0.918, 1], radius=dp(10))
        b_eliminar = btn_raised("ELIMINAR", bg=CFG_ALERTA, color=[1,1,1,1],
                                size_hint_y=None, height=dp(42))
        btns.add_widget(b_cancelar)
        btns.add_widget(b_eliminar)
        content.add_widget(btns)

        popup = Popup(title="", separator_height=0, content=content,
                      size_hint=(0.82, None), height=dp(180),
                      background_color=CFG_TARJETA, auto_dismiss=False)

        def _cerrar(*_):
            self._dialog = None
            popup.dismiss()

        def _confirmar(*_):
            self._dialog = None
            popup.dismiss()
            self._elim_prod_cfg(prod["id"])
            _snack(f"'{prod['nombre']}' eliminado")

        b_cancelar.bind(on_press=_cerrar)
        b_eliminar.bind(on_press=_confirmar)
        self._dialog = popup
        popup.open()

    def _elim_prod_cfg(self, pid):
        if self.cat_cfg:
            objetivo = next((p for p in self.menu[self.cat_cfg] if p["id"] == pid), None)
            if objetivo and objetivo.get("es_extra"):
                # Ultima linea de defensa: Costo Extra jamas se elimina,
                # sin importar desde donde se haya intentado.
                _snack("Costo Extra no se puede eliminar")
                return
            self.menu[self.cat_cfg] = [
                p for p in self.menu[self.cat_cfg] if p["id"] != pid
            ]
            self._guardar_menu()
            self._rebuild_prods_cfg()

    # ── MESAS CFG ────────────────────────────────────────────────────────────
    def _rebuild_mesas_cfg(self):
        sc = self.root.get_screen("config")
        sc.ids.lbl_num_mesas.text = f"Mesas totales: {len(self.mesas)}"

    def agregar_mesa(self):
        n = len(self.mesas) + 1
        nombre = f"Mesa {n}"
        while nombre in self.mesas:
            n += 1
            nombre = f"Mesa {n}"
        self.mesas.append(nombre)
        self._guardar_mesas()
        self._rebuild_mesas_cfg()
        self.refrescar_mesas()

    def confirmar_quitar_mesa(self):
        """Pide confirmacion antes de eliminar una mesa (mismo patron ya
        usado para borrar productos): antes, el boton '-' en Config >
        Operativa borraba de inmediato sin aviso, a un toque de
        distancia del boton '+'."""
        if not self.mesas or self._dialog:
            return
        ocupadas = {p["mesa"] for p in self.pedidos if p.get("tipo") == "mesa"}
        objetivo = next(
            (m for m in reversed(self.mesas) if m not in ocupadas), None
        )
        if objetivo is None:
            _snack("Todas las mesas tienen pedido activo")
            return

        content = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(14),
                            size_hint_y=None)
        content.bind(minimum_height=content.setter("height"))
        content.add_widget(lbl(
            f"¿Eliminar \"{objetivo}\"?",
            color=CFG_TEXTO, font_size="15sp", halign="center",
            size_hint_y=None, height=dp(40), auto_height=True,
        ))

        btns = BoxLayout(orientation="horizontal", size_hint_y=None,
                         height=dp(44), spacing=dp(10))
        b_cancelar = btn_flat("CANCELAR", color=CFG_TEXTO_GRIS,
                              size_hint_y=None, height=dp(42))
        _set_bg(b_cancelar, [0.929, 0.929, 0.918, 1], radius=dp(10))
        b_eliminar = btn_raised("ELIMINAR", bg=CFG_ALERTA, color=[1,1,1,1],
                                size_hint_y=None, height=dp(42))
        btns.add_widget(b_cancelar)
        btns.add_widget(b_eliminar)
        content.add_widget(btns)

        popup = Popup(title="", separator_height=0, content=content,
                      size_hint=(0.82, None), height=dp(180),
                      background_color=CFG_TARJETA, auto_dismiss=False)

        def _cerrar(*_):
            self._dialog = None
            popup.dismiss()

        def _confirmar(*_):
            self._dialog = None
            popup.dismiss()
            self.quitar_mesa()

        b_cancelar.bind(on_press=_cerrar)
        b_eliminar.bind(on_press=_confirmar)
        self._dialog = popup
        popup.open()

    def quitar_mesa(self):
        if not self.mesas:
            return
        ocupadas = {p["mesa"] for p in self.pedidos if p.get("tipo") == "mesa"}
        for mesa in reversed(self.mesas):
            if mesa not in ocupadas:
                self.mesas.remove(mesa)
                self._guardar_mesas()
                self._rebuild_mesas_cfg()
                self.refrescar_mesas()
                return
        _snack("Todas las mesas tienen pedido activo")


    def _borrar_estadisticas(self, alcance="todas"):
        """Borra registros de ventas, gastos, pérdida fantasma y clientela
        (mesa_personas).

        alcance='hoy'   -> borra solo el día actual (útil para limpiar
                            las pruebas de un cajero/mesero nuevo).
        alcance='todas' -> borra todo el historial, para empezar desde
                            cero.

        No toca config (tema/nombre/contraseña) ni el catálogo de
        categorías/productos/mesas."""
        ok, mensaje = self.db.borrar_estadisticas(alcance)
        _snack(mensaje)
        if ok:
            try:
                self._refrescar_estadisticas_actual()
            except Exception:
                pass

    def _confirmar_borrar_estadisticas(self):
        """Primer paso: preguntar qué se quiere borrar (solo hoy o todo),
        antes de pedir la confirmación final."""
        if self._dialog:
            return

        content = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(12),
                            size_hint_y=None)
        content.bind(minimum_height=content.setter("height"))
        content.add_widget(lbl("¿Qué estadísticas quieres borrar?",
                               color=self.texto_contraste(self.OSCURO),
                               font_size="15sp", halign="center",
                               size_hint_y=None, height=dp(28)))
        content.add_widget(lbl(
            "\"Solo hoy\" limpia las pruebas de un cajero o mesero "
            "nuevo. \"Todas\" borra el historial completo para "
            "empezar desde cero.",
            color=GRIS, font_size="12sp", halign="center",
            size_hint_y=None, height=dp(52), auto_height=True))

        b_hoy = btn_flat("Solo HOY  (pruebas del día)",
                         color=self.texto_contraste(self.OSCURO),
                         size_hint_y=None, height=dp(46))
        _set_bg(b_hoy, self.OSCURO)
        b_todas = btn_raised("TODAS  (empezar desde cero)", bg=self.ROJO,
                             size_hint_y=None, height=dp(46))
        b_cancelar = btn_flat("Cancelar", color=self.texto_contraste(self.OSCURO),
                              size_hint_y=None, height=dp(40))

        content.add_widget(b_hoy)
        content.add_widget(b_todas)
        content.add_widget(b_cancelar)

        popup = Popup(title="", separator_height=0, content=content,
                      size_hint=(0.86, None), height=dp(300),
                      background_color=self.OSCURO, auto_dismiss=False)

        def _cerrar_popup(*_):
            self._dialog = None
            popup.dismiss()

        def _elegir(alcance):
            self._dialog = None
            popup.dismiss()
            self._confirmar_borrar_estadisticas_paso2(alcance)

        b_hoy.bind(on_press=lambda *_: _elegir("hoy"))
        b_todas.bind(on_press=lambda *_: _elegir("todas"))
        b_cancelar.bind(on_press=_cerrar_popup)

        self._dialog = popup
        popup.open()

    def _confirmar_borrar_estadisticas_paso2(self, alcance):
        """Segundo paso: confirmación final ya con el alcance elegido,
        para evitar borrados accidentales."""
        if self._dialog:
            return

        if alcance == "hoy":
            texto = ("Esto borrará las ventas, gastos y registro de "
                     "clientela SOLO del día de hoy.\n\nNo se puede deshacer.")
        else:
            texto = ("Esto borrará TODAS las ventas, gastos y registro "
                     "de clientela de forma permanente.\n\nNo se puede deshacer.")

        content = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(14),
                            size_hint_y=None)
        content.bind(minimum_height=content.setter("height"))
        content.add_widget(lbl(texto, color=self.texto_contraste(self.OSCURO),
                               font_size="14sp", halign="center",
                               size_hint_y=None, height=dp(90), auto_height=True))

        btns = BoxLayout(orientation="horizontal", size_hint_y=None,
                         height=dp(44), spacing=dp(10))
        b_cancelar = btn_flat("Cancelar", color=self.texto_contraste(self.OSCURO),
                              size_hint_y=None, height=dp(44))
        b_borrar   = btn_raised("Borrar", bg=self.ROJO,
                                size_hint_y=None, height=dp(44))
        btns.add_widget(b_cancelar)
        btns.add_widget(b_borrar)
        content.add_widget(btns)

        popup = Popup(title="", separator_height=0, content=content,
                      size_hint=(0.85, None), height=dp(230),
                      background_color=self.OSCURO, auto_dismiss=False)

        def _cerrar_popup(*_):
            self._dialog = None
            popup.dismiss()

        def _confirmar(*_):
            self._dialog = None
            popup.dismiss()
            self._borrar_estadisticas(alcance)

        b_cancelar.bind(on_press=_cerrar_popup)
        b_borrar.bind(on_press=_confirmar)

        self._dialog = popup
        popup.open()

    # ── EMPLEADOS ────────────────────────────────────────────────────────────
    def abrir_empleados(self):
        """Popup para dar de alta, editar o eliminar empleados (mesero/a).
        Cada empleado solo necesita un nombre y una contraseña sencillos;
        esa contraseña es la que se pedira despues en la pagina web de
        meseros (servidor_mesas.py) para identificar quien atiende."""
        popup_ref = [None]

        content = BoxLayout(orientation="vertical", padding=dp(14), spacing=dp(10),
                            size_hint_y=None)
        content.bind(minimum_height=content.setter("height"))
        content.add_widget(lbl("[b]EMPLEADOS[/b]", markup=True,
                               color=self.texto_contraste(self.OSCURO), font_size="16sp",
                               halign="center", size_hint_y=None, height=dp(30)))

        lista_box = BoxLayout(orientation="vertical", spacing=dp(6),
                              size_hint_y=None)
        lista_box.bind(minimum_height=lista_box.setter("height"))

        def _repintar_lista():
            lista_box.clear_widgets()
            if not self.empleados:
                lista_box.add_widget(lbl(
                    "Aun no hay empleados registrados.",
                    color=self.texto_contraste(self.OSCURO)[:3] + [0.5],
                    font_size="12sp", size_hint_y=None, height=dp(24)))
                return
            for emp in self.empleados:
                fila = BoxLayout(orientation="horizontal", size_hint_y=None,
                                 height=dp(42), spacing=dp(6))
                _set_bg(fila, self.OSCURO, radius=dp(10))
                fila.add_widget(lbl(
                    emp["nombre"], color=self.texto_contraste(self.OSCURO),
                    font_size="14sp", halign="left"))
                b_edit = btn_flat("Editar", color=self.texto_contraste(self.OSCURO), font_size="12sp",
                                  size_hint_x=None, width=dp(64),
                                  size_hint_y=None, height=dp(36))
                b_del = btn_flat("Borrar", color=self.texto_contraste(self.OSCURO), font_size="12sp",
                                 size_hint_x=None, width=dp(64),
                                 size_hint_y=None, height=dp(36))
                b_edit.bind(on_press=lambda inst, e=emp: _editar(e))
                b_del.bind(on_press=lambda inst, e=emp: _confirmar_borrar(e))
                fila.add_widget(b_edit)
                fila.add_widget(b_del)
                lista_box.add_widget(fila)

        def _confirmar_borrar(emp):
            content_c = BoxLayout(orientation="vertical", padding=dp(14), spacing=dp(10))
            content_c.add_widget(lbl(
                f"¿Borrar a {emp['nombre']}?",
                color=self.texto_contraste(self.OSCURO), font_size="14sp",
                halign="center", size_hint_y=None, height=dp(40)))
            btns_c = BoxLayout(orientation="horizontal", size_hint_y=None,
                               height=dp(44), spacing=dp(8))
            b_can = btn_flat("Cancelar", color=self.texto_contraste(self.OSCURO),
                             size_hint_y=None, height=dp(40))
            b_ok = btn_raised("Borrar", bg=self.ROJO, size_hint_y=None, height=dp(40))
            btns_c.add_widget(b_can)
            btns_c.add_widget(b_ok)
            content_c.add_widget(btns_c)
            popup_c = Popup(title="", separator_height=0, content=content_c,
                            size_hint=(0.78, None), height=dp(160),
                            background_color=self.OSCURO)

            def _borrar(*_):
                self.empleados = [e for e in self.empleados if e["nombre"] != emp["nombre"]]
                self._guardar_empleados()
                popup_c.dismiss()
                _repintar_lista()
                self.refrescar_mesas()
                _snack("Empleado borrado")

            b_can.bind(on_press=lambda *_: popup_c.dismiss())
            b_ok.bind(on_press=_borrar)
            popup_c.open()

        def _editar(emp):
            f_nom = campo_texto("Nombre")
            f_pass = campo_texto("Contraseña", password=True)
            f_nom.text = emp["nombre"]
            f_pass.text = emp["password"]
            encadenar_campos(f_nom, f_pass)

            content_e = BoxLayout(orientation="vertical", padding=dp(14), spacing=dp(10))
            content_e.add_widget(lbl("[b]EDITAR EMPLEADO[/b]", markup=True,
                                     color=self.texto_contraste(self.OSCURO), font_size="15sp",
                                     halign="center", size_hint_y=None, height=dp(28)))
            content_e.add_widget(f_nom)
            content_e.add_widget(f_pass)
            btns_e = BoxLayout(orientation="horizontal", size_hint_y=None,
                               height=dp(44), spacing=dp(8))
            b_can = btn_flat("Cancelar", color=self.texto_contraste(self.OSCURO),
                             size_hint_y=None, height=dp(40))
            b_ok = btn_raised("Guardar", bg=self.ACCENT, size_hint_y=None, height=dp(40))
            btns_e.add_widget(b_can)
            btns_e.add_widget(b_ok)
            content_e.add_widget(btns_e)
            popup_e = Popup(title="", separator_height=0, content=content_e,
                            size_hint=(0.85, None), height=dp(260),
                            background_color=self.OSCURO)

            def _guardar_edit(*_):
                nuevo_nombre = f_nom.text.strip()
                nueva_pass = f_pass.text.strip()
                if not nuevo_nombre or not nueva_pass:
                    _snack("Nombre y contraseña son obligatorios"); return
                if any(e["nombre"].lower() == nuevo_nombre.lower() and e is not emp
                       for e in self.empleados):
                    _snack("Ya existe un empleado con ese nombre"); return
                emp["nombre"] = nuevo_nombre
                emp["password"] = nueva_pass
                self._guardar_empleados()
                popup_e.dismiss()
                _repintar_lista()
                self.refrescar_mesas()
                _snack("Empleado actualizado")

            b_can.bind(on_press=lambda *_: popup_e.dismiss())
            b_ok.bind(on_press=_guardar_edit)
            f_pass.bind(on_text_validate=_guardar_edit)
            popup_e.open()

        _repintar_lista()
        content.add_widget(lista_box)

        # ── Alta de nuevo empleado ──
        content.add_widget(lbl("Agregar nuevo:", color=self.texto_contraste(self.OSCURO)[:3] + [0.6],
                                font_size="13sp", size_hint_y=None, height=dp(22)))
        f_nombre_n = campo_texto("Nombre")
        f_pass_n = campo_texto("Contraseña", password=True)
        encadenar_campos(f_nombre_n, f_pass_n)
        content.add_widget(f_nombre_n)
        content.add_widget(f_pass_n)

        def _agregar(*_):
            nombre = f_nombre_n.text.strip()
            passw = f_pass_n.text.strip()
            if not nombre or not passw:
                _snack("Nombre y contraseña son obligatorios"); return
            if any(e["nombre"].lower() == nombre.lower() for e in self.empleados):
                _snack("Ya existe un empleado con ese nombre"); return
            self.empleados.append({"nombre": nombre, "password": passw})
            self._guardar_empleados()
            f_nombre_n.text = ""
            f_pass_n.text = ""
            _repintar_lista()
            _snack("Empleado agregado")

        b_agregar = btn_raised("+ AGREGAR EMPLEADO", bg=self.ROJO,
                               size_hint_y=None, height=dp(42), font_size="13sp")
        b_agregar.bind(on_press=_agregar)
        f_pass_n.bind(on_text_validate=_agregar)
        content.add_widget(b_agregar)

        b_cerrar = btn_flat("Cerrar", color=self.texto_contraste(self.OSCURO),
                            size_hint_y=None, height=dp(40))
        b_cerrar.bind(on_press=lambda *_: popup_ref[0].dismiss())
        content.add_widget(b_cerrar)

        scroll = ScrollView(size_hint=(1, None), height=dp(520))
        scroll.add_widget(content)

        popup = Popup(title="", separator_height=0, content=scroll,
                      size_hint=(0.9, None), height=dp(560),
                      background_color=self.OSCURO)
        popup_ref[0] = popup
        popup.open()

    def _elegir_empleado(self, callback):
        """Pregunta que empleado atiende, antes de abrir una mesa o iniciar
        un domicilio. Si no hay empleados registrados, no pregunta nada y
        sigue de largo (callback recibe None)."""
        if not self.empleados:
            callback(None)
            return

        content = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(10),
                            size_hint_y=None)
        content.bind(minimum_height=content.setter("height"))
        content.add_widget(lbl("¿Quien atiende?", color=self.texto_contraste(self.OSCURO),
                               font_size="15sp", halign="center",
                               size_hint_y=None, height=dp(28)))

        popup_ref = [None]

        def _elegir(nombre):
            if popup_ref[0]: popup_ref[0].dismiss()
            callback(nombre)

        for emp in self.empleados:
            b = btn_flat(emp["nombre"], color=self.texto_contraste(self.OSCURO),
                        font_size="14sp", size_hint_y=None, height=dp(42))
            _set_bg(b, self.OSCURO, radius=dp(10))
            b.bind(on_press=lambda inst, n=emp["nombre"]: _elegir(n))
            content.add_widget(b)

        b_sin = btn_flat("Sin asignar", color=self.texto_contraste(self.OSCURO)[:3] + [0.6],
                         font_size="13sp", size_hint_y=None, height=dp(38))
        b_sin.bind(on_press=lambda *_: _elegir(None))
        content.add_widget(b_sin)

        scroll = ScrollView(size_hint=(1, None), height=min(dp(400), dp(60) + len(self.empleados) * dp(48)))
        scroll.add_widget(content)

        popup = Popup(title="", separator_height=0, content=scroll,
                      size_hint=(0.8, None), height=min(dp(440), dp(100) + len(self.empleados) * dp(48)),
                      background_color=self.OSCURO)
        popup_ref[0] = popup
        popup.open()

    def abrir_info_negocio_ticket(self):
        """Popup de Configuracion > Personalizacion > Informacion del
        negocio y ticket: direccion, datos bancarios para transferencia y
        mensaje de agradecimiento personalizado. TODOS los campos son
        opcionales -- ninguno bloquea el guardado si esta vacio -- y si
        tienen contenido se muestran solos al final del ticket de venta
        (ESC/POS, imagen para Galeria y Vista Previa; ver
        _lineas_pie_negocio). Modificar esto NO afecta pedidos ya
        cobrados anteriormente: solo se lee al armar un ticket NUEVO.

        Estructura pensada para crecer sin tocar el resto de la app: cada
        campo es una clave mas en self.info_negocio (dict persistido como
        JSON, ver INFO_NEGOCIO_DEFAULT / _cargar_info_negocio /
        _guardar_info_negocio). Agregar un campo a futuro (logotipo ya
        existe aparte, redes sociales, horario, RFC, metodos de pago, QR
        para transferencia, datos fiscales...) es: sumar la clave en
        INFO_NEGOCIO_DEFAULT, un campo_texto() aqui, y una linea en
        _guardar() de abajo."""
        from kivy.core.window import Window

        info = self.info_negocio

        f_direccion = campo_texto("Direccion del negocio (opcional)")
        f_direccion.text = info.get("direccion", "")

        f_banco = campo_texto("Banco (opcional)")
        f_banco.text = info.get("banco", "")

        f_cuenta = campo_texto("CLABE o numero de cuenta (opcional)")
        f_cuenta.text = info.get("cuenta", "")

        f_titular = campo_texto("Nombre del titular de la cuenta (opcional)")
        f_titular.text = info.get("titular", "")

        f_telefono = campo_texto("Telefono para enviar comprobante de pago (opcional)")
        f_telefono.text = info.get("telefono", "")

        f_mensaje = campo_texto(
            "Mensaje de agradecimiento (opcional, ej. Gracias por su preferencia)",
            multiline=True, height=dp(70),
        )
        f_mensaje.text = info.get("mensaje_agradecimiento", "")

        encadenar_campos(f_direccion, f_banco, f_cuenta, f_titular, f_telefono)

        popup_ref = [None]

        def _guardar(*_):
            # Sin validaciones de "campo obligatorio" a proposito: cada
            # campo se guarda tal cual (incluso vacio) y _lineas_pie_negocio
            # decide, al armar CADA ticket nuevo, cual bloque mostrar.
            self.info_negocio = {
                "direccion": f_direccion.text.strip(),
                "banco": f_banco.text.strip(),
                "cuenta": f_cuenta.text.strip(),
                "titular": f_titular.text.strip(),
                "telefono": f_telefono.text.strip(),
                "mensaje_agradecimiento": f_mensaje.text.strip(),
            }
            self._guardar_info_negocio()
            _snack("Informacion del negocio guardada")
            if popup_ref[0]:
                popup_ref[0].dismiss()

        content = BoxLayout(orientation="vertical", padding=dp(14), spacing=dp(10),
                            size_hint_y=None)
        content.bind(minimum_height=content.setter("height"))
        content.add_widget(lbl("[b]INFORMACIÓN DEL NEGOCIO Y TICKET[/b]", markup=True,
                               color=self.texto_contraste(self.OSCURO), font_size="16sp", halign="center",
                               size_hint_y=None, height=dp(26), auto_height=True))
        def _campo(etiqueta, campo):
            content.add_widget(lbl(etiqueta, color=_texto_contraste(self.OSCURO)[:3] + [0.6],
                                   font_size="13sp", size_hint_y=None, height=dp(20),
                                   auto_height=True))
            content.add_widget(campo)

        _campo("Direccion del negocio:", f_direccion)
        _campo("Banco:", f_banco)
        _campo("CLABE o numero de cuenta:", f_cuenta)
        _campo("Nombre del titular de la cuenta:", f_titular)
        _campo("Telefono para enviar comprobante de pago:", f_telefono)
        _campo("Mensaje de agradecimiento personalizado:", f_mensaje)

        btns = BoxLayout(orientation="horizontal", size_hint_y=None,
                         height=dp(44), spacing=dp(10))
        b_can  = btn_flat("Cancelar", color=_texto_contraste(self.OSCURO), size_hint_y=None, height=dp(40))
        b_save = btn_raised("GUARDAR CAMBIOS", bg=self.ACCENT, size_hint_y=None, height=dp(40))
        btns.add_widget(b_can)
        btns.add_widget(b_save)
        content.add_widget(btns)

        # ── ScrollView + Popup de alto dinamico (mismo patron ya probado
        # en _abrir_ticket / _popup_vista_previa_impresion): chico si el
        # contenido cabe, con scroll si no cabe en la pantalla. ──
        scroll = ScrollView(size_hint=(1, None), do_scroll_x=False)
        scroll.add_widget(content)

        popup = Popup(title="", separator_height=0, content=scroll,
                      size_hint=(0.9, None), background_color=self.OSCURO)

        def _sync_alto(*_):
            alto_scroll = min(content.height, Window.height * 0.7)
            scroll.height = alto_scroll
            popup.height = min(alto_scroll + dp(24), Window.height * 0.92)
        content.bind(minimum_height=_sync_alto)
        _sync_alto()

        popup_ref[0] = popup
        b_can.bind(on_press=lambda *_: popup.dismiss())
        b_save.bind(on_press=_guardar)
        popup.open()

    def abrir_personalizacion(self):
        """Popup para cambiar tema de color, nombre de taqueria y contraseña."""
        f_nombre  = campo_texto("Nombre de la taqueria")
        f_pass1   = campo_texto("Nueva contraseña", password=True)
        f_pass2   = campo_texto("Confirmar contraseña", password=True)
        encadenar_campos(f_nombre, f_pass1, f_pass2)

        # Mostrar nombre actual sin markup
        nombre_actual = self.nombre_taqueria.replace("[b]","").replace("[/b]","")
        f_nombre.text = nombre_actual

        popup_ref = [None]

        def _guardar(*_):
            nuevo_nombre = f_nombre.text.strip()
            p1 = f_pass1.text
            p2 = f_pass2.text

            if not nuevo_nombre:
                _snack("El nombre no puede estar vacio"); return

            if p1 or p2:
                if p1 != p2:
                    _snack("Las contraseñas no coinciden"); return
                if len(p1) < 4:
                    _snack("La contraseña debe tener al menos 4 caracteres"); return
                self._password = p1
                self._guardar_config("password", p1)
                _snack("Contraseña actualizada")

            self.nombre_taqueria = f"[b]{nuevo_nombre}[/b]"
            self._guardar_config("nombre_taqueria", nuevo_nombre)
            self._actualizar_carpeta_errores(nuevo_nombre)
            # Refrescar el label en pantalla inicio
            try:
                sc = self.root.get_screen("inicio")
                sc.ids.lbl_nombre_taqueria.text = self.nombre_taqueria
            except Exception:
                pass

            if popup_ref[0]: popup_ref[0].dismiss()
            if not (p1 or p2):
                _snack("Nombre guardado")

        # ── Selector de tema de color (arriba, siempre visible sin scroll) ──
        def _elegir_tema(nombre_tema):
            self.aplicar_tema(nombre_tema)

        box_temas = BoxLayout(orientation="vertical", size_hint_y=None,
                              height=len(TEMAS) * dp(46) + dp(6), spacing=dp(8))
        for nombre_tema, datos in TEMAS.items():
            fila = BoxLayout(orientation="horizontal", size_hint_y=None,
                             height=dp(42), spacing=dp(8))
            chip = Label(text="", size_hint_x=None, width=dp(28))
            _set_bg(chip, datos["ROJO"], radius=dp(8))
            fila.add_widget(chip)
            activo = (nombre_tema == self.tema_actual)
            texto_b = f"[b]{nombre_tema}[/b]" if activo else nombre_tema
            b_tema = btn_flat(texto_b, color=_texto_contraste(self.OSCURO), font_size="13sp",
                              markup=True, size_hint_y=None, height=dp(42))
            _set_bg(b_tema, self.OSCURO)
            b_tema.bind(on_press=lambda inst, n=nombre_tema: _elegir_tema(n))
            fila.add_widget(b_tema)
            box_temas.add_widget(fila)

        content = BoxLayout(orientation="vertical", padding=dp(14), spacing=dp(10),
                            size_hint_y=None)
        content.bind(minimum_height=content.setter("height"))
        content.add_widget(lbl("[b]PERSONALIZACIÓN[/b]", markup=True,
                               color=self.texto_contraste(self.OSCURO), font_size="16sp",
                               halign="center", size_hint_y=None, height=dp(30)))
        content.add_widget(lbl("Tema de color:", color=_texto_contraste(self.OSCURO)[:3] + [0.6],
                                font_size="13sp", size_hint_y=None, height=dp(22)))
        content.add_widget(box_temas)
        fila_logo = BoxLayout(orientation="horizontal", size_hint_y=None,
                              height=dp(56), spacing=dp(10))
        preview_logo = KivyImage(source=self.logo_path, allow_stretch=True, keep_ratio=True,
                                 size_hint_x=None, width=dp(52),
                                 opacity=(1 if self.logo_path else 0))
        b_logo_elegir = btn_raised("ELEGIR IMAGEN", bg=self.ACCENT,
                                   size_hint_y=None, height=dp(44), font_size="12sp")
        b_logo_quitar = btn_flat("Quitar", color=_texto_contraste(self.OSCURO)[:3] + [0.6],
                                 size_hint_y=None, height=dp(44), font_size="12sp")
        b_logo_elegir.bind(on_press=lambda *_: self.elegir_logo())
        b_logo_quitar.bind(on_press=lambda *_: self.quitar_logo())
        fila_logo.add_widget(preview_logo)
        fila_logo.add_widget(b_logo_elegir)
        fila_logo.add_widget(b_logo_quitar)
        content.add_widget(fila_logo)
        content.add_widget(lbl("Nombre de la taqueria:", color=_texto_contraste(self.OSCURO)[:3] + [0.6],
                                font_size="13sp", size_hint_y=None, height=dp(22), auto_height=True))
        content.add_widget(f_nombre)
        content.add_widget(lbl("Cambiar contraseña (dejar vacio = sin cambio):",
                                color=_texto_contraste(self.OSCURO)[:3] + [0.6], font_size="13sp",
                                size_hint_y=None, height=dp(22), auto_height=True))
        content.add_widget(f_pass1)
        content.add_widget(f_pass2)

        # ── Impresora ──
        tipo_actual, ancho_actual, ip_actual = self._leer_config_impresora()
        impresora_activa = self._impresora_activa()
        content.add_widget(lbl("Impresora de tickets:",
                                color=_texto_contraste(self.OSCURO)[:3] + [0.6],
                                font_size="13sp", size_hint_y=None, height=dp(22),
                                auto_height=True))

        def _refrescar_chip_imp(boton, activo):
            boton.text = f"[b]{boton._texto_btn}[/b]" if activo else boton._texto_btn
            fondo_chip = self.ACCENT if activo else self.OSCURO
            _set_bg(boton, fondo_chip, radius=dp(10))
            boton.color = self.texto_contraste(fondo_chip)

        # Interruptor encendida/apagada: cierra y vuelve a abrir este
        # mismo popup para que se redibuje mostrando u ocultando todo lo
        # demas (tipo de impresora, bluetooth, ancho de papel, ejemplos).
        fila_switch = BoxLayout(orientation="horizontal", size_hint_y=None,
                                height=dp(42), spacing=dp(8))
        texto_switch = "🖨  Impresora: ENCENDIDA" if impresora_activa else "🖨  Impresora: APAGADA"
        b_switch = btn_raised(texto_switch,
                              bg=(self.ACCENT if impresora_activa else [0.4, 0.4, 0.4, 1]),
                              size_hint_y=None, height=dp(42), font_size="13sp")
        b_switch.bind(on_press=lambda *_: (
            self._set_impresora_activa(not impresora_activa),
            popup.dismiss(),
            self.abrir_personalizacion(),
        ))
        fila_switch.add_widget(b_switch)
        content.add_widget(fila_switch)

        if impresora_activa:
            f_ip = campo_texto("IP de la impresora (ej. 192.168.1.50)")
            f_ip.text = ip_actual
            f_ip.opacity = 1 if tipo_actual == "wifi" else 0
            f_ip.disabled = tipo_actual != "wifi"
            f_ip.size_hint_y = None
            f_ip.height = dp(44) if tipo_actual == "wifi" else 0

            def _elegir_tipo_impresora(tipo):
                self._guardar_config_impresora(tipo=tipo)
                f_ip.opacity = 1 if tipo == "wifi" else 0
                f_ip.disabled = tipo != "wifi"
                f_ip.height = dp(44) if tipo == "wifi" else 0
                _refrescar_chip_imp(b_bt, tipo == "bluetooth")
                _refrescar_chip_imp(b_wifi, tipo == "wifi")
                _refrescar_visibilidad_prueba_wifi(tipo)

            fila_tipo = BoxLayout(orientation="horizontal", size_hint_y=None,
                                  height=dp(42), spacing=dp(8))
            b_bt   = btn_flat("Bluetooth", color=_texto_contraste(self.OSCURO), markup=True,
                              font_size="13sp", size_hint_y=None, height=dp(42))
            b_bt._texto_btn = "Bluetooth"
            b_wifi = btn_flat("WiFi", color=_texto_contraste(self.OSCURO), markup=True,
                              font_size="13sp", size_hint_y=None, height=dp(42))
            b_wifi._texto_btn = "WiFi"
            _refrescar_chip_imp(b_bt, tipo_actual == "bluetooth")
            _refrescar_chip_imp(b_wifi, tipo_actual == "wifi")
            b_bt.bind(on_press=lambda *_: _elegir_tipo_impresora("bluetooth"))
            b_wifi.bind(on_press=lambda *_: _elegir_tipo_impresora("wifi"))
            fila_tipo.add_widget(b_bt)
            fila_tipo.add_widget(b_wifi)
            content.add_widget(fila_tipo)
            content.add_widget(f_ip)
            f_ip.bind(on_text_validate=lambda *_: self._guardar_config_impresora(ip=f_ip.text.strip()))

            # ── Probar conexion WiFi (solo visible si tipo == wifi) ──
            lbl_prueba_wifi = lbl("", color=_texto_contraste(self.OSCURO)[:3] + [0.6],
                                  font_size="11sp", halign="left",
                                  size_hint_y=None,
                                  height=dp(18) if tipo_actual == "wifi" else 0)
            lbl_prueba_wifi.opacity = 1 if tipo_actual == "wifi" else 0

            b_probar_wifi = btn_flat("PROBAR CONEXIÓN", color=_texto_contraste(self.OSCURO),
                                     font_size="12sp", size_hint_y=None,
                                     height=dp(38) if tipo_actual == "wifi" else 0)
            b_probar_wifi.opacity = 1 if tipo_actual == "wifi" else 0
            _set_bg(b_probar_wifi, self.OSCURO, radius=dp(8))

            def _probar_wifi(*_):
                ip_probar = f_ip.text.strip()
                if not ip_probar:
                    lbl_prueba_wifi.text = "Escribe una IP primero"
                    lbl_prueba_wifi.color = [0.9, 0.5, 0.3, 1]
                    return
                # Se guarda de una vez -- asi si la prueba sale bien, la
                # IP ya queda lista sin que la cajera tenga que acordarse
                # de tocar "Enter" en el campo aparte.
                self._guardar_config_impresora(ip=ip_probar)
                lbl_prueba_wifi.text = f"Probando conexion con {ip_probar}..."
                lbl_prueba_wifi.color = _texto_contraste(self.OSCURO)[:3] + [0.6]

                def _ok():
                    lbl_prueba_wifi.text = f"✓ Conectado con {ip_probar}"
                    lbl_prueba_wifi.color = [0.3, 0.75, 0.4, 1]

                def _error(mensaje):
                    lbl_prueba_wifi.text = f"✗ {mensaje}"
                    lbl_prueba_wifi.color = [0.85, 0.35, 0.3, 1]

                self._impresora_wifi.probar_conexion(ip_probar, callback_ok=_ok, callback_error=_error)

            b_probar_wifi.bind(on_press=_probar_wifi)
            content.add_widget(b_probar_wifi)
            content.add_widget(lbl_prueba_wifi)

            def _refrescar_visibilidad_prueba_wifi(tipo):
                b_probar_wifi.opacity = 1 if tipo == "wifi" else 0
                b_probar_wifi.height = dp(38) if tipo == "wifi" else 0
                b_probar_wifi.disabled = tipo != "wifi"
                lbl_prueba_wifi.opacity = 1 if tipo == "wifi" else 0
                lbl_prueba_wifi.height = dp(18) if tipo == "wifi" else 0
                lbl_prueba_wifi.text = ""

            # ── Selector de impresora Bluetooth (solo visible si tipo == bluetooth) ──
            mac_actual = self._leer_config("impresora_bt_mac", "")
            lbl_mac = lbl(f"Vinculada: {mac_actual}" if mac_actual else "Sin impresora vinculada",
                         color=_texto_contraste(self.OSCURO)[:3] + [0.55], font_size="11sp",
                         size_hint_y=None, height=dp(20) if tipo_actual == "bluetooth" else 0)
            lbl_mac.opacity = 1 if tipo_actual == "bluetooth" else 0
            b_elegir_bt = btn_raised("ELEGIR IMPRESORA BLUETOOTH", bg=self.ACCENT,
                                     size_hint_y=None,
                                     height=dp(42) if tipo_actual == "bluetooth" else 0,
                                     font_size="12sp")
            b_elegir_bt.opacity = 1 if tipo_actual == "bluetooth" else 0
            b_elegir_bt.bind(on_press=lambda *_: (popup.dismiss(),
                                                  self._popup_elegir_impresora_bluetooth()))
            content.add_widget(lbl_mac)
            content.add_widget(b_elegir_bt)

            # NOTA: b_bt y b_wifi ya quedaron enlazados arriba a
            # "lambda *_: _elegir_tipo_impresora(...)" -- como es una closure
            # que busca el nombre en tiempo de llamada (no lo copia al momento
            # del bind), redefinir la funcion aqui abajo con el mismo nombre
            # es suficiente para que ambos botones usen esta version nueva.
            # NO se vuelve a hacer bind (evita duplicar el callback).
            _elegir_tipo_impresora_original = _elegir_tipo_impresora
            def _elegir_tipo_impresora(tipo):
                _elegir_tipo_impresora_original(tipo)
                lbl_mac.height = dp(20) if tipo == "bluetooth" else 0
                lbl_mac.opacity = 1 if tipo == "bluetooth" else 0
                b_elegir_bt.height = dp(42) if tipo == "bluetooth" else 0
                b_elegir_bt.opacity = 1 if tipo == "bluetooth" else 0

            content.add_widget(lbl("Ancho de papel:",
                                    color=_texto_contraste(self.OSCURO)[:3] + [0.6],
                                    font_size="13sp", size_hint_y=None, height=dp(22),
                                    auto_height=True))

            def _elegir_ancho_impresora(ancho):
                self._guardar_config_impresora(ancho=ancho)
                _refrescar_chip_imp(b_58, ancho == "58")
                _refrescar_chip_imp(b_80, ancho == "80")

            fila_ancho = BoxLayout(orientation="horizontal", size_hint_y=None,
                                   height=dp(42), spacing=dp(8))
            b_58 = btn_flat("58mm", color=_texto_contraste(self.OSCURO), markup=True,
                            font_size="13sp", size_hint_y=None, height=dp(42))
            b_58._texto_btn = "58mm"
            b_80 = btn_flat("80mm", color=_texto_contraste(self.OSCURO), markup=True,
                            font_size="13sp", size_hint_y=None, height=dp(42))
            b_80._texto_btn = "80mm"
            _refrescar_chip_imp(b_58, ancho_actual == "58")
            _refrescar_chip_imp(b_80, ancho_actual == "80")
            b_58.bind(on_press=lambda *_: _elegir_ancho_impresora("58"))
            b_80.bind(on_press=lambda *_: _elegir_ancho_impresora("80"))
            fila_ancho.add_widget(b_58)
            fila_ancho.add_widget(b_80)
            content.add_widget(fila_ancho)

            b_vista_previa = btn_flat("Ejemplo (vista previa)", color=self.texto_contraste(self.OSCURO),
                                      size_hint_y=None, height=dp(36), font_size="12sp")
            # Ya NO se hace popup.dismiss() antes de abrir la vista previa:
            # se abre encima de Personalizacion sin cerrarla, asi al pulsar
            # "Cerrar" en la vista previa el usuario vuelve directo a
            # Personalizacion en vez de tener que volver a abrirla desde
            # Configuracion. _popup_vista_previa_impresion() igual vuelve a
            # leer _leer_config_impresora() cada vez que se llama, asi que
            # sigue agarrando el 58/80mm recien elegido sin depender de que
            # Personalizacion se haya cerrado.
            b_vista_previa.bind(on_press=lambda *_: self._popup_vista_previa_impresion("ticket"))
            content.add_widget(b_vista_previa)

            b_vista_previa_comanda = btn_flat("Ejemplo (comanda cocina)", color=self.texto_contraste(self.OSCURO),
                                              size_hint_y=None, height=dp(36), font_size="12sp")
            b_vista_previa_comanda.bind(on_press=lambda *_: self._popup_vista_previa_comanda())
            content.add_widget(b_vista_previa_comanda)

        b_info_negocio = btn_flat("Información del negocio y ticket  ▸", color=self.texto_contraste(self.OSCURO),
                                  size_hint_y=None, height=dp(40), font_size="12sp")
        # Igual que las vistas previas de arriba: ya no se cierra
        # Personalizacion al abrir esta -- se abre encima, asi al cerrarla
        # el usuario sigue en Personalizacion.
        b_info_negocio.bind(on_press=lambda *_: self.abrir_info_negocio_ticket())
        content.add_widget(b_info_negocio)

        # ── Zona de pruebas: borrar estadísticas ──
        content.add_widget(lbl("Zona de pruebas:",
                                color=_texto_contraste(self.OSCURO)[:3] + [0.6],
                                font_size="13sp", size_hint_y=None, height=dp(22),
                                auto_height=True))
        b_borrar_est = btn_flat("🗑  Borrar estadisticas (ventas, gastos, clientela)",
                                color=self.texto_contraste(self.OSCURO), font_size="12sp",
                                size_hint_y=None, height=dp(40))
        b_borrar_est.bind(on_press=lambda *_: (
            popup.dismiss(), self._confirmar_borrar_estadisticas()
        ))
        content.add_widget(b_borrar_est)

        btns = BoxLayout(orientation="horizontal", size_hint_y=None,
                         height=dp(44), spacing=dp(10))
        b_can  = btn_flat("Cancelar", color=_texto_contraste(self.OSCURO), size_hint_y=None, height=dp(40))
        b_save = btn_raised("GUARDAR", bg=self.ROJO,
                            size_hint_y=None, height=dp(40))
        btns.add_widget(b_can)
        btns.add_widget(b_save)
        content.add_widget(btns)

        scroll = ScrollView(size_hint=(1, None), height=dp(540))
        scroll.add_widget(content)

        popup = Popup(title="", separator_height=0, content=scroll,
                      size_hint=(0.88, None), height=dp(580),
                      background_color=self.OSCURO)
        popup_ref[0] = popup
        b_save.bind(on_press=_guardar)
        b_can.bind(on_press=lambda *_: popup.dismiss())
        f_pass2.bind(on_text_validate=_guardar)
        popup.open()


if __name__ == "__main__":
    TaqueriaApp().run()

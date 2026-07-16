# -*- coding: utf-8 -*-
"""
database.py
============
Capa de acceso a datos de la app. Aisla TODO lo relacionado con SQLite
(conexion, esquema, migraciones, y las queries de negocio) para que
main.py (Kivy/KivyMD) no tenga que saber nada de SQL.

Principios de esta extraccion:
- Nada aqui importa Kivy/KivyMD. Esto se puede probar con pytest plano,
  sin levantar la app grafica.
- La clase BaseDatos NO conoce rutas de Android/scoped storage ni
  `self.user_data_dir`: recibe la ruta final del archivo .db ya resuelta
  por el caller (en main.py, App._db_path() sigue viviendo alla, porque
  es una responsabilidad de la plataforma/app, no de la base de datos).
- Las funciones que en el archivo original dependian de estado de la App
  (ej. self.menu para mapear producto->categoria) ahora reciben ese dato
  como parametro explicito, en vez de leerlo de "self".
- Cada metodo abre y cierra su propia conexion (mismo patron que el
  original) porque asi funcionaba bien con WAL + multiples hilos
  (servidor de mesas, meseros, cajera). No se comparte una conexion
  global entre hilos.
"""

import sqlite3
import uuid
from datetime import datetime


# ─────────────────────────────────────────────────────────────────────────
# Funciones de negocio puras (no tocan la BD)
# ─────────────────────────────────────────────────────────────────────────

def nuevo_id():
    """ID unico para pedidos/items. Antes se usaba str(id(object())), pero
    id() es la direccion de memoria en CPython: en cuanto el objeto
    temporal se descarta (inmediatamente, nadie lo referencia), esa
    direccion queda libre y el recolector de basura se la puede dar a
    otro objeto creado justo despues. Con pedidos concurrentes llegando
    en sucesion rapida desde el servidor de meseros, esto producia IDs
    repetidos: dos pedidos distintos terminaban con el mismo "id" y se
    mezclaban o se sobreescribian entre si al cobrar o editar.
    uuid4 genera 122 bits aleatorios: la probabilidad de choque es
    astronomicamente baja incluso con miles de pedidos concurrentes."""
    return uuid.uuid4().hex


# ─────────────────────────────────────────────────────────────────────────
# Acceso a la base de datos
# ─────────────────────────────────────────────────────────────────────────

class BaseDatos:
    """Encapsula la conexion SQLite y todas las operaciones de negocio
    sobre ella. Uso tipico desde main.py:

        self.db = BaseDatos(self._db_path())
        self.db.inicializar()
        ...
        self.menu = self.db.cargar_menu(MENU_DEFAULT)
    """

    def __init__(self, ruta_bd):
        self.ruta_bd = ruta_bd

    # ── Conexion ────────────────────────────────────────────────────────
    def conectar(self):
        """Abre una conexion a la BD ya configurada para soportar rafagas
        de escrituras concurrentes (varios meseros mandando comandas al
        mismo tiempo que la cajera cobra o consulta estadisticas):

        - journal_mode=WAL: las lecturas ya no bloquean a las escrituras
          ni viceversa (el modo por defecto, DELETE/rollback journal, si
          lo hace). Es justo lo que provoca "database is locked" cuando
          llegan varios pedidos a la vez.
        - timeout=30.0: si en el instante exacto dos hilos intentan
          escribir a la vez (dos POST /pedido simultaneos), SQLite espera
          hasta 30s a que el otro termine en vez de tronar de inmediato
          con OperationalError("database is locked").
        - synchronous=NORMAL: seguro de usar en conjunto con WAL (a
          diferencia de con el journal por defecto) y evita que cada
          commit espere un fsync completo a disco, lo que acelera mucho
          las escrituras seguidas de las comandas de los meseros.

        Todas las llamadas a sqlite3.connect(...) de la app deben pasar
        por aqui en vez de abrir la conexion "pelona"."""
        con = sqlite3.connect(self.ruta_bd, timeout=30.0)
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("PRAGMA synchronous=NORMAL;")
        return con

    def inicializar(self):
        """Crea las tablas (si no existen), aplica migraciones silenciosas
        de columnas nuevas, y guarda la fecha_instalacion una unica vez.
        Debe llamarse una vez al arrancar la app, antes de usar cualquier
        otro metodo de esta clase."""
        try:
            con = self.conectar()
            cur = con.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS ventas (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    fecha       TEXT NOT NULL,
                    hora        TEXT NOT NULL,
                    hora_int    INTEGER NOT NULL,
                    producto    TEXT NOT NULL,
                    categoria   TEXT NOT NULL,
                    cantidad    INTEGER NOT NULL,
                    precio_u    REAL NOT NULL,
                    total       REAL NOT NULL,
                    tipo_orden  TEXT NOT NULL,
                    pedido_id   TEXT NOT NULL DEFAULT '',
                    mesa_nombre TEXT NOT NULL DEFAULT '',
                    forma_pago  TEXT NOT NULL DEFAULT 'efectivo',
                    nota        TEXT NOT NULL DEFAULT ''
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS gastos (
                    id      INTEGER PRIMARY KEY AUTOINCREMENT,
                    fecha   TEXT NOT NULL,
                    hora    TEXT NOT NULL,
                    nombre  TEXT NOT NULL,
                    monto   REAL NOT NULL
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS perdidas_fantasma (
                    id       INTEGER PRIMARY KEY AUTOINCREMENT,
                    fecha    TEXT NOT NULL,
                    hora     TEXT NOT NULL,
                    tipo     TEXT NOT NULL DEFAULT 'producto',
                    detalle  TEXT NOT NULL,
                    motivo   TEXT NOT NULL DEFAULT '',
                    monto    REAL NOT NULL
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS config (
                    clave TEXT PRIMARY KEY,
                    valor TEXT NOT NULL
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS mesa_personas (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    fecha       TEXT NOT NULL,
                    hora        TEXT NOT NULL,
                    mesa_nombre TEXT NOT NULL,
                    personas    INTEGER NOT NULL
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS fondo_caja (
                    fecha TEXT PRIMARY KEY,
                    monto REAL NOT NULL DEFAULT 0
                )
            """)
            # Migraciones silenciosas
            for col, defn in [
                ("pedido_id",   "TEXT NOT NULL DEFAULT ''"),
                ("mesa_nombre", "TEXT NOT NULL DEFAULT ''"),
                ("forma_pago",  "TEXT NOT NULL DEFAULT 'efectivo'"),
                ("nota",        "TEXT NOT NULL DEFAULT ''"),
            ]:
                try:
                    cur.execute(f"ALTER TABLE ventas ADD COLUMN {col} {defn}")
                except Exception:
                    pass
            con.commit()
            con.close()

            # Fecha de instalacion: se guarda UNA sola vez, la primera vez
            # que la app corre en este dispositivo (INSERT OR IGNORE no
            # pisa el valor si ya existia). A partir de esa fecha se
            # muestra el calendario completo en Estadisticas > Fechas.
            try:
                con2 = self.conectar()
                cur2 = con2.cursor()
                cur2.execute(
                    "INSERT OR IGNORE INTO config (clave, valor) VALUES (?, ?)",
                    ("fecha_instalacion", datetime.now().strftime("%Y-%m-%d")),
                )
                con2.commit()
                con2.close()
            except Exception as e:
                print("Error guardando fecha_instalacion:", e)
        except Exception as e:
            print("Error init_db:", e)

    # ── Config (clave/valor genérico) ───────────────────────────────────
    def guardar_config(self, clave, valor):
        """Guarda un ajuste (ej. tema) en la BD para que persista entre sesiones."""
        try:
            con = self.conectar()
            cur = con.cursor()
            cur.execute(
                "INSERT OR REPLACE INTO config (clave, valor) VALUES (?, ?)",
                (clave, valor),
            )
            con.commit()
            con.close()
        except Exception as e:
            print("Error guardando config:", e)

    def leer_config(self, clave, default=None):
        """Lee un ajuste guardado en la BD. Si no existe, regresa default."""
        try:
            con = self.conectar()
            cur = con.cursor()
            cur.execute("SELECT valor FROM config WHERE clave = ?", (clave,))
            fila = cur.fetchone()
            con.close()
            if fila:
                return fila[0]
        except Exception as e:
            print("Error leyendo config:", e)
        return default

    def fecha_instalacion(self):
        """Fecha (str 'YYYY-MM-DD') en que se instalo/corrio la app por
        primera vez en este dispositivo, o None si no existe el registro
        (el caller decide el fallback, ya que "hoy" es una nocion de la
        capa de arriba, no de la BD)."""
        return self.leer_config("fecha_instalacion")

    def fechas_con_estadisticas(self):
        """Regresa una lista de strings 'YYYY-MM-DD', uno por cada dia que
        ya tiene al menos una venta o una perdida fantasma registrada en
        la BD. Solo esos dias deben ser accionables en el calendario de
        Estadisticas > Fechas -- se incluye perdida fantasma para no
        esconder un dia donde solo hubo cancelaciones y ninguna venta
        cobrada. Se regresan como strings (no date()) para no acoplar
        esta capa a como el caller quiera parsear/usar las fechas."""
        fechas = []
        try:
            con = self.conectar()
            cur = con.cursor()
            cur.execute("SELECT DISTINCT fecha FROM ventas")
            filas = cur.fetchall()
            cur.execute("SELECT DISTINCT fecha FROM perdidas_fantasma")
            filas += cur.fetchall()
            con.close()
            fechas = sorted({f for (f,) in filas})
        except Exception as e:
            print("Error _fechas_con_estadisticas:", e)
        return fechas

    # ── Menu / Mesas / Info del negocio (persistidos como JSON en config) ─
    # NOTA: estos metodos reciben y regresan el JSON ya serializado
    # (strings) o None; la deserializacion/objeto default (MENU_DEFAULT,
    # MESAS_DEFAULT, etc.) vive en main.py porque son datos de dominio de
    # la app, no de la base de datos en si.
    def cargar_menu_json(self):
        """Regresa el JSON crudo guardado en config['menu'], o None si no
        hay nada guardado todavia."""
        return self.leer_config("menu", None)

    def guardar_menu_json(self, menu_json):
        """Persiste el JSON de self.menu completo en la BD."""
        self.guardar_config("menu", menu_json)

    def cargar_mesas_json(self):
        """Regresa el JSON crudo guardado en config['mesas'], o None si no
        hay nada guardado todavia."""
        return self.leer_config("mesas", None)

    def guardar_mesas_json(self, mesas_json):
        """Persiste el JSON de self.mesas en la BD."""
        self.guardar_config("mesas", mesas_json)

    def cargar_info_negocio_json(self):
        """Regresa el JSON crudo guardado en config['info_negocio'], o
        None si no hay nada guardado todavia."""
        return self.leer_config("info_negocio", None)

    def guardar_info_negocio_json(self, info_json):
        """Persiste el JSON de self.info_negocio completo en la BD."""
        self.guardar_config("info_negocio", info_json)

    def guardar_empleados_json(self, empleados_json):
        """Persiste la lista de empleados (nombre + contraseña) en la BD."""
        self.guardar_config("empleados", empleados_json)

    # ── Ventas ───────────────────────────────────────────────────────────
    def registrar_venta(self, items, tipo_orden, prod_cat,
                         pedido_id="", mesa_nombre="", forma_pago="efectivo"):
        """Guarda TODOS los items del pedido cobrado en una sola
        transaccion SQLite.

        `prod_cat` es un dict {producto_id: categoria} ya armado por el
        caller a partir de self.menu (esta funcion no conoce el menu de
        la app, solo mapea id->categoria con lo que le pasen).

        Antes, todos los INSERT vivian en un solo try/except que solo
        IMPRIMIA el error si algo fallaba (ej. un item sin "precio" por
        un KeyError): la venta completa se perdia sin dejar rastro en la
        BD, pero el llamador (_cobrar_pedido) no se enteraba y quitaba el
        pedido de "activos" de todos modos -- el usuario veia "Cobrado" y
        el dinero desaparecia sin registro.

        Ahora: BEGIN al inicio, un INSERT por item, y si CUALQUIERA falla
        se hace ROLLBACK de TODO el pedido (no se guarda nada a medias).
        Devuelve True solo si la venta completa quedo guardada, False si
        se revirtio por cualquier error. El llamador DEBE revisar este
        valor antes de dar la venta por hecha."""
        con = None
        try:
            con = self.conectar()
            cur = con.cursor()
            con.execute("BEGIN")

            ahora = datetime.now()
            fecha    = ahora.strftime("%Y-%m-%d")
            hora     = ahora.strftime("%H:%M")
            hora_int = ahora.hour

            for item in items:
                qty    = item.get("qty", 1)
                precio = item["precio"]
                nombre = item["nombre"]
                cat    = prod_cat.get(item.get("id", ""), "Otros")
                # El comentario/nota del renglon ("sin cebolla", "bien
                # dorado", etc.) viaja en el item bajo la clave '_nota'
                # (mismo estandar que usa main.py en toda la app, sin
                # importar si el renglon lo puso la cajera o un mesero
                # desde la web). Se guarda en su propia columna para que
                # el historial/reimpresion conserve el detalle exacto de
                # cada plato, no solo el nombre generico del producto.
                nota = (item.get("_nota") or "").strip()
                cur.execute("""
                    INSERT INTO ventas
                    (fecha, hora, hora_int, producto, categoria, cantidad,
                     precio_u, total, tipo_orden, pedido_id, mesa_nombre, forma_pago, nota)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (fecha, hora, hora_int, nombre, cat, qty, precio,
                      precio * qty, tipo_orden, pedido_id, mesa_nombre, forma_pago, nota))

            con.commit()
            return True
        except Exception as e:
            print("Error registrar_venta_db (se hizo ROLLBACK, nada quedo guardado):", e)
            if con is not None:
                try:
                    con.rollback()
                except Exception:
                    pass
            return False
        finally:
            if con is not None:
                try:
                    con.close()
                except Exception:
                    pass

    def registrar_personas_mesa(self, mesa_nombre, personas):
        """Guarda cuantas personas entraron a una mesa al momento de
        abrirla, para poder saber en estadisticas cuanta gente ha
        entrado al local."""
        try:
            con = self.conectar()
            cur = con.cursor()
            ahora = datetime.now()
            cur.execute("""
                INSERT INTO mesa_personas (fecha, hora, mesa_nombre, personas)
                VALUES (?, ?, ?, ?)
            """, (ahora.strftime("%Y-%m-%d"), ahora.strftime("%H:%M"),
                  mesa_nombre, personas))
            con.commit()
            con.close()
        except Exception as e:
            print("Error registrar_personas_mesa:", e)

    def registrar_perdida_fantasma(self, tipo, detalle, motivo, monto):
        """Registra un producto o una cuenta cancelada YA GUARDADA en su
        PROPIA tabla ('perdidas_fantasma'), separada por completo de
        'gastos'. A proposito NO se mezcla con los gastos de caja reales
        (compras, propinas, etc.): esto es solo un contador informativo
        de lo que se cancelo despues de guardado, para que NO reste de la
        ganancia neta ni del total en caja de Cierre de Caja --
        unicamente se suma entre si y se muestra aparte, como 'perdida
        fantasma' de auditoria."""
        if monto <= 0:
            return
        try:
            con = self.conectar()
            cur = con.cursor()
            ahora = datetime.now()
            cur.execute(
                "INSERT INTO perdidas_fantasma "
                "(fecha, hora, tipo, detalle, motivo, monto) VALUES (?,?,?,?,?,?)",
                (ahora.strftime("%Y-%m-%d"), ahora.strftime("%H:%M"),
                 tipo, detalle, motivo, monto)
            )
            con.commit(); con.close()
        except Exception as e:
            print("Error registrando perdida fantasma:", e)

    def registrar_gasto(self, nombre, monto):
        """Guarda un gasto de caja (nombre + monto). Lanza la excepcion
        hacia el caller (a diferencia del resto de metodos "fire and
        forget") porque abrir_gastos_caja necesita mostrarle al usuario
        el error especifico en el propio popup si algo falla."""
        con = self.conectar()
        cur = con.cursor()
        ahora = datetime.now()
        cur.execute(
            "INSERT INTO gastos (fecha, hora, nombre, monto) VALUES (?,?,?,?)",
            (ahora.strftime("%Y-%m-%d"), ahora.strftime("%H:%M"), nombre, monto)
        )
        con.commit(); con.close()

    # ── Fondo de caja ────────────────────────────────────────────────────
    def obtener_fondo_caja(self, fecha_str):
        """Regresa el monto de fondo de caja guardado para `fecha_str`
        ('YYYY-MM-DD'), o 0 si no hay registro."""
        try:
            con = self.conectar()
            cur = con.cursor()
            cur.execute("SELECT monto FROM fondo_caja WHERE fecha=?", (fecha_str,))
            r = cur.fetchone()
            con.close()
            return r[0] if r else 0
        except Exception:
            return 0

    def guardar_fondo_caja(self, fecha_str, monto):
        """Guarda (o reemplaza) cuanto dinero se dejo de fondo/base en la
        caja para `fecha_str`. Lanza la excepcion hacia el caller para que
        el popup de captura pueda mostrar el error especifico."""
        con = self.conectar()
        cur = con.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO fondo_caja (fecha, monto) VALUES (?, ?)",
            (fecha_str, monto)
        )
        con.commit()
        con.close()

    # ── Conteos rapidos (pantalla de inicio) ────────────────────────────
    def conteo_pedidos_cobrados_dia(self, fecha_str):
        """Regresa (domicilios_cobrados, mesas_cobradas) -- pedidos unicos
        (por pedido_id) ya cobrados y guardados en `ventas` para el dia
        `fecha_str`. Se usa junto con los pedidos activos en memoria para
        pintar los contadores de la pantalla de inicio."""
        dom_cobrados = 0
        mesas_cobradas = 0
        try:
            con = self.conectar()
            cur = con.cursor()
            cur.execute(
                "SELECT COUNT(DISTINCT pedido_id) FROM ventas "
                "WHERE fecha=? AND tipo_orden='domicilio'",
                (fecha_str,)
            )
            dom_cobrados = cur.fetchone()[0] or 0
            cur.execute(
                "SELECT COUNT(DISTINCT pedido_id) FROM ventas "
                "WHERE fecha=? AND tipo_orden='mesa'",
                (fecha_str,)
            )
            mesas_cobradas = cur.fetchone()[0] or 0
            con.close()
        except Exception as e:
            print("Error conteo_pedidos_cobrados_dia:", e)
        return dom_cobrados, mesas_cobradas

    # ── Estadisticas por periodo ─────────────────────────────────────────
    def obtener_estadisticas(self, desde_str, hasta_str):
        """Corre todas las queries de la pantalla de Estadisticas para el
        rango [desde_str, hasta_str] (strings 'YYYY-MM-DD' inclusive) y
        regresa un dict plano con los resultados. main.py solo arma la UI
        a partir de este dict; no le toca ver SQL.

        Si algo falla, regresa el mismo dict pero con todos los valores
        en su "cero" natural y tiene_datos=False, igual que hacia el
        bloque except del codigo original."""
        try:
            con = self.conectar()
            cur = con.cursor()
            ds, hs = desde_str, hasta_str

            cur.execute(
                "SELECT SUM(total), SUM(cantidad) FROM ventas WHERE fecha BETWEEN ? AND ?",
                (ds, hs)
            )
            row = cur.fetchone()
            total_dinero = row[0] or 0
            total_piezas = row[1] or 0

            cur.execute("""
                SELECT COUNT(DISTINCT pedido_id), SUM(total)
                FROM ventas
                WHERE fecha BETWEEN ? AND ? AND tipo_orden = 'mesa'
            """, (ds, hs))
            rm = cur.fetchone()
            mesas_pedidos  = rm[0] or 0
            mesas_ganancia = rm[1] or 0

            cur.execute("""
                SELECT mesa_nombre, COUNT(DISTINCT pedido_id) as cnt, SUM(total) as gan
                FROM ventas
                WHERE fecha BETWEEN ? AND ? AND tipo_orden = 'mesa' AND mesa_nombre != ''
                GROUP BY mesa_nombre ORDER BY cnt DESC LIMIT 5
            """, (ds, hs))
            top_mesas = cur.fetchall()

            cur.execute("""
                SELECT COUNT(DISTINCT pedido_id), SUM(total)
                FROM ventas
                WHERE fecha BETWEEN ? AND ? AND tipo_orden = 'domicilio'
            """, (ds, hs))
            rd = cur.fetchone()
            dom_pedidos  = rd[0] or 0
            dom_ganancia = rd[1] or 0

            mesa_ticket = (mesas_ganancia / mesas_pedidos) if mesas_pedidos else 0
            dom_ticket  = (dom_ganancia  / dom_pedidos)   if dom_pedidos  else 0
            total_pedidos = mesas_pedidos + dom_pedidos

            cur.execute("""
                SELECT producto, SUM(cantidad) as cnt, SUM(total) as gan
                FROM ventas WHERE fecha BETWEEN ? AND ?
                GROUP BY producto ORDER BY cnt DESC LIMIT 5
            """, (ds, hs))
            top_prods = cur.fetchall()

            cur.execute("""
                SELECT producto, SUM(cantidad) as cnt
                FROM ventas WHERE fecha BETWEEN ? AND ?
                GROUP BY producto ORDER BY cnt ASC LIMIT 3
            """, (ds, hs))
            low_prods = cur.fetchall()

            cur.execute("""
                SELECT COUNT(*), SUM(personas)
                FROM mesa_personas
                WHERE fecha BETWEEN ? AND ?
            """, (ds, hs))
            rp = cur.fetchone()
            mesas_abiertas   = rp[0] or 0
            total_personas   = rp[1] or 0
            promedio_persona = (total_personas / mesas_abiertas) if mesas_abiertas else 0

            cur.execute("""
                SELECT hora_int, SUM(cantidad) as cnt
                FROM ventas WHERE fecha BETWEEN ? AND ?
                GROUP BY hora_int ORDER BY cnt DESC LIMIT 5
            """, (ds, hs))
            top_horas = cur.fetchall()

            cur.execute(
                "SELECT SUM(monto) FROM gastos WHERE fecha BETWEEN ? AND ?",
                (ds, hs)
            )
            total_gastos_periodo = cur.fetchone()[0] or 0

            cur.execute("""
                SELECT nombre, SUM(monto) as total, COUNT(*) as veces
                FROM gastos WHERE fecha BETWEEN ? AND ?
                GROUP BY nombre ORDER BY total DESC LIMIT 12
            """, (ds, hs))
            top_gastos = cur.fetchall()

            cur.execute(
                "SELECT SUM(monto) FROM perdidas_fantasma WHERE fecha BETWEEN ? AND ?",
                (ds, hs)
            )
            total_perdida_fantasma_periodo = cur.fetchone()[0] or 0

            cur.execute("""
                SELECT tipo, detalle, motivo, monto
                FROM perdidas_fantasma WHERE fecha BETWEEN ? AND ?
                ORDER BY id DESC LIMIT 20
            """, (ds, hs))
            lista_perdida_fantasma_periodo = cur.fetchall()

            con.close()
            tiene_datos = (total_piezas > 0 or mesas_abiertas > 0
                           or total_gastos_periodo > 0
                           or total_perdida_fantasma_periodo > 0)

            return dict(
                tiene_datos=tiene_datos,
                total_dinero=total_dinero, total_piezas=total_piezas,
                total_pedidos=total_pedidos,
                mesas_pedidos=mesas_pedidos, mesas_ganancia=mesas_ganancia,
                mesa_ticket=mesa_ticket, top_mesas=top_mesas,
                dom_pedidos=dom_pedidos, dom_ganancia=dom_ganancia,
                dom_ticket=dom_ticket,
                top_prods=top_prods, low_prods=low_prods,
                mesas_abiertas=mesas_abiertas, total_personas=total_personas,
                promedio_persona=promedio_persona, top_horas=top_horas,
                total_gastos_periodo=total_gastos_periodo, top_gastos=top_gastos,
                total_perdida_fantasma_periodo=total_perdida_fantasma_periodo,
                lista_perdida_fantasma_periodo=lista_perdida_fantasma_periodo,
            )
        except Exception as e:
            print("Error stats:", e)
            return dict(
                tiene_datos=False,
                total_dinero=0, total_piezas=0, total_pedidos=0,
                mesas_pedidos=0, mesas_ganancia=0, mesa_ticket=0, top_mesas=[],
                dom_pedidos=0, dom_ganancia=0, dom_ticket=0,
                top_prods=[], low_prods=[],
                mesas_abiertas=0, total_personas=0, promedio_persona=0, top_horas=[],
                total_gastos_periodo=0, top_gastos=[],
                total_perdida_fantasma_periodo=0, lista_perdida_fantasma_periodo=[],
            )

    # ── Cierre de caja (un solo dia) ─────────────────────────────────────
    def obtener_cierre_caja(self, fecha_str):
        """Corre todas las queries del popup de Cierre de Caja para el
        dia `fecha_str` ('YYYY-MM-DD') y regresa un dict plano. Los datos
        siempre se recalculan en vivo a partir de las tablas `ventas` y
        `gastos` (ya persistidas en SQLite), asi que sirve tanto para el
        cierre del dia de hoy como para consultar el cierre de cualquier
        fecha pasada desde el calendario de Estadisticas.

        Regresa None si algo fallo (el caller original mostraba un
        _snack con el error y no seguia armando el popup)."""
        try:
            con = self.conectar()
            cur = con.cursor()
            hoy = fecha_str

            cur.execute(
                "SELECT SUM(total), COUNT(DISTINCT pedido_id) FROM ventas WHERE fecha=?",
                (hoy,)
            )
            rv = cur.fetchone()
            venta_total   = rv[0] or 0
            total_pedidos = rv[1] or 0

            cur.execute(
                "SELECT COUNT(DISTINCT mesa_nombre) FROM ventas "
                "WHERE fecha=? AND tipo_orden='mesa' AND mesa_nombre!=''",
                (hoy,)
            )
            mesas_atendidas = cur.fetchone()[0] or 0

            cur.execute(
                "SELECT COUNT(DISTINCT pedido_id) FROM ventas WHERE fecha=? AND tipo_orden='mesa'",
                (hoy,)
            )
            pedidos_mesa = cur.fetchone()[0] or 0

            cur.execute(
                "SELECT COUNT(DISTINCT pedido_id) FROM ventas WHERE fecha=? AND tipo_orden='domicilio'",
                (hoy,)
            )
            pedidos_dom = cur.fetchone()[0] or 0

            cur.execute(
                "SELECT SUM(total) FROM ventas WHERE fecha=? AND forma_pago='efectivo'",
                (hoy,)
            )
            total_efectivo = cur.fetchone()[0] or 0

            cur.execute(
                "SELECT SUM(total) FROM ventas WHERE fecha=? AND forma_pago='transferencia'",
                (hoy,)
            )
            total_tarjeta = cur.fetchone()[0] or 0

            cur.execute(
                "SELECT nombre, monto FROM gastos WHERE fecha=? ORDER BY id",
                (hoy,)
            )
            lista_gastos = cur.fetchall()
            total_gastos = sum(g[1] for g in lista_gastos)

            cur.execute(
                "SELECT tipo, detalle, motivo, monto FROM perdidas_fantasma "
                "WHERE fecha=? ORDER BY id",
                (hoy,)
            )
            lista_perdidas_fantasma = cur.fetchall()
            total_perdida_fantasma = sum(p[3] for p in lista_perdidas_fantasma)

            cur.execute(
                "SELECT SUM(personas) FROM mesa_personas WHERE fecha=?",
                (hoy,)
            )
            clientes_atendidos = cur.fetchone()[0] or 0

            cur.execute(
                "SELECT monto FROM fondo_caja WHERE fecha=?",
                (hoy,)
            )
            rf = cur.fetchone()
            fondo_caja = rf[0] if rf else 0

            con.close()

            # Total en caja = fondo inicial + efectivo cobrado - gastos
            # pagados de caja. Asi el numero coincide exactamente con el
            # dinero fisico real en caja. OJO: 'total_perdida_fantasma'
            # (productos/cuentas cancelados ya guardados) a proposito NO
            # entra en esta cuenta ni en la de ganancia_neta -- viene de
            # su propia tabla (perdidas_fantasma), separada de 'gastos'.
            # Es solo un contador informativo que se suma entre si y se
            # muestra aparte, desconectado del resto de las cifras.
            total_en_caja = fondo_caja + total_efectivo - total_gastos
            ganancia_neta = venta_total - total_gastos

            return dict(
                venta_total=venta_total, total_pedidos=total_pedidos,
                mesas_atendidas=mesas_atendidas,
                pedidos_mesa=pedidos_mesa, pedidos_dom=pedidos_dom,
                total_efectivo=total_efectivo, total_tarjeta=total_tarjeta,
                lista_gastos=lista_gastos, total_gastos=total_gastos,
                lista_perdidas_fantasma=lista_perdidas_fantasma,
                total_perdida_fantasma=total_perdida_fantasma,
                clientes_atendidos=clientes_atendidos,
                fondo_caja=fondo_caja,
                total_en_caja=total_en_caja, ganancia_neta=ganancia_neta,
            )
        except Exception as e:
            print("Error al cargar cierre:", e)
            return None

    # ── Mantenimiento ────────────────────────────────────────────────────
    def borrar_estadisticas(self, alcance="todas"):
        """Borra registros de ventas, gastos, perdida fantasma y clientela
        (mesa_personas).

        alcance='hoy'   -> borra solo el dia actual (util para limpiar
                            las pruebas de un cajero/mesero nuevo).
        alcance='todas' -> borra todo el historial, para empezar desde
                            cero.

        No toca config (tema/nombre/contraseña) ni el catalogo de
        categorias/productos/mesas.

        Regresa (True, mensaje) si salio bien, o (False, mensaje_error)
        si algo fallo -- el caller decide como mostrar cada caso
        (_snack, log, etc.)."""
        try:
            con = self.conectar()
            cur = con.cursor()
            if alcance == "hoy":
                hoy = datetime.now().date().strftime("%Y-%m-%d")
                cur.execute("DELETE FROM ventas WHERE fecha=?", (hoy,))
                cur.execute("DELETE FROM gastos WHERE fecha=?", (hoy,))
                cur.execute("DELETE FROM perdidas_fantasma WHERE fecha=?", (hoy,))
                cur.execute("DELETE FROM mesa_personas WHERE fecha=?", (hoy,))
                mensaje = "Estadisticas de hoy borradas"
            else:
                cur.execute("DELETE FROM ventas")
                cur.execute("DELETE FROM gastos")
                cur.execute("DELETE FROM perdidas_fantasma")
                cur.execute("DELETE FROM mesa_personas")
                mensaje = "Todas las estadisticas fueron borradas"
            con.commit()
            con.close()
            return True, mensaje
        except Exception as e:
            return False, f"Error al borrar: {e}"

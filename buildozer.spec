[app]

# ── Identidad de la app ──────────────────────────────────────────────────────
title = Comandero Enoch
package.name = comanderoenoch
package.domain = com.estudiokelvin

# ── Código fuente ─────────────────────────────────────────────────────────────
source.dir = .
source.include_exts = py,png,jpg,jpeg,kv,atlas,json,ttf,otf
source.exclude_dirs = tests,bin,venv,.buildozer,__pycache__
source.exclude_exts = spec,pyc,pyo

version = 1.0

# ── Requisitos Python (todo lo que main.py / servidor_mesas.py importan) ────
# kivy/kivymd: UI. flask+werkzeug: servidor local de meseros. zeroconf: mDNS
# (comandero.local). qrcode+pillow: QR de conexión. plyer: selector de
# archivos (logo). pyjnius+android: permisos, WifiManager (multicast lock),
# wake lock, exclusión de optimización de batería.
requirements = python3,kivy==2.3.1,kivymd==1.2.0,flask,werkzeug,zeroconf,qrcode,pillow,plyer,pyjnius,android,setuptools

# ── Icono y presentación ─────────────────────────────────────────────────────
icon.filename = %(source.dir)s/icono.png
orientation = portrait
fullscreen = 0

# ── Permisos de Android ──────────────────────────────────────────────────────
# INTERNET / ACCESS_NETWORK_STATE / ACCESS_WIFI_STATE: servidor Flask + que
#   los meseros se conecten por WiFi local.
# CHANGE_WIFI_MULTICAST_STATE: MulticastLock para que el mDNS (zeroconf)
#   siga anunciándose con la pantalla apagada.
# READ/WRITE_EXTERNAL_STORAGE: compatibilidad Android 6-10 (logo, backups).
# MANAGE_EXTERNAL_STORAGE: Android 11+, acceso completo para backups/logo
#   fuera de la carpeta privada (la app ya maneja el flujo a Ajustes).
# WAKE_LOCK: mantener el CPU activo para que el servidor de meseros responda
#   con la pantalla bloqueada.
# REQUEST_IGNORE_BATTERY_OPTIMIZATIONS: salir del modo Doze para que Android
#   no mate el servidor en segundo plano.
# POST_NOTIFICATIONS: requerido en Android 13+ si en algún momento se
#   muestran notificaciones (KivyMD/plyer las usan internamente a veces).
# BLUETOOTH_CONNECT / BLUETOOTH_SCAN: obligatorios en Android 12+ (API 31+)
#   para abrir el socket RFCOMM (ImpresoraBluetoothManager) y para
#   startDiscovery() en escanear_cercanos(). Sin declararlos aqui,
#   request_permissions() en main.py los pide en runtime pero el SO los
#   niega solos porque no existen en el manifest -- la impresora nunca
#   conecta y el escaneo lanza SecurityException.
android.permissions = INTERNET,ACCESS_NETWORK_STATE,ACCESS_WIFI_STATE,CHANGE_WIFI_MULTICAST_STATE,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE,MANAGE_EXTERNAL_STORAGE,WAKE_LOCK,REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,POST_NOTIFICATIONS,BLUETOOTH_CONNECT,BLUETOOTH_SCAN

# ── Arquitectura y niveles de API ────────────────────────────────────────────
android.archs = arm64-v8a
android.api = 34
# minapi 31 = Android 12+, pedido explicitamente (el manejo de permisos
# BLUETOOTH_CONNECT/BLUETOOTH_SCAN de ImpresoraBluetoothManager esta
# escrito para el modelo de permisos de Android 12+; en versiones
# anteriores a la 31 no se pediria BLUETOOTH_CONNECT/SCAN y se necesitaria
# ademas el permiso legacy BLUETOOTH/BLUETOOTH_ADMIN, que hoy no esta).
android.minapi = 31
android.ndk = 25b
android.accept_sdk_license = True

# scoped storage: se maneja "a mano" en el código (user_data_dir + Ajustes
# de Acceso a todos los archivos), así que no forzamos legacy storage.
android.allow_backup = True

# ── Otros ajustes recomendados ───────────────────────────────────────────────
android.presplash_color = #1a1a2e
android.enable_androidx = True
android.gradle_dependencies =
android.add_compile_options =

[buildozer]
log_level = 2
warn_on_root = 0

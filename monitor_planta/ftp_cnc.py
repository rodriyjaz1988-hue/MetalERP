"""Servidor FTP del Monitor para la transferencia FTP del Embedded Ethernet
de los controles Fanuc (0i-D/0i-F): el operario, desde el torno, ve la lista
de programas de la carpeta de su máquina y carga el que necesita.

Cada máquina entra con su propio usuario (el código de la máquina, ej. T1) y la
clave del Monitor, y solo ve su carpeta: monitor_planta\\ftp\\<MÁQUINA>\\.
Solo lectura: desde el torno no se puede borrar ni pisar nada en la PC.

El teclado del Fanuc escribe todo en mayúsculas: usuario y clave se aceptan
sin distinguir mayúsculas de minúsculas. Cada conexión, entrada, lista y
bajada del torno se avisa (al_evento) para ver hasta dónde llegó.
"""
import os, threading, time

_estado = {"activo": False, "ok": None, "error": None, "puerto": None, "usuarios": []}
_servidor = None
_hilo = None
_lock = threading.Lock()
PUERTOS_PASIVOS = range(60000, 60010)
# Conexión, entrada y lista se avisan una vez cada tantos segundos por IP
# (la pantalla del torno puede pedir la lista varias veces seguidas).
AVISO_CADA_SEG = 120
_ultimo_aviso = {}


def estado():
    return dict(_estado)


def detener():
    global _servidor, _hilo
    with _lock:
        srv, _servidor = _servidor, None
    if srv:
        try:
            srv.close_all()
        except Exception:
            pass
    if _hilo:
        _hilo.join(timeout=5)
        _hilo = None
    _estado.update(activo=False)


def arrancar(base, puerto, clave, maquinas, al_evento=None):
    """(Re)arranca el servidor. maquinas = códigos (usuarios). al_evento(tipo, maquina, archivo, ip)."""
    global _servidor, _hilo
    detener()
    _estado.update(puerto=puerto, usuarios=list(maquinas), error=None, ok=None)
    try:
        from pyftpdlib.authorizers import AuthenticationFailed, DummyAuthorizer
        from pyftpdlib.handlers import FTPHandler
        from pyftpdlib.servers import FTPServer
    except ImportError:
        _estado.update(ok=False, error="Falta instalar pyftpdlib (pip install pyftpdlib)")
        return
    if not maquinas:
        _estado.update(ok=False, error="No hay máquinas Fanuc cargadas en Lectores")
        return
    if not clave:
        _estado.update(ok=False, error="Falta la clave del FTP")
        return
    class Autorizador(DummyAuthorizer):
        def validate_authentication(self, username, password, handler):
            u = self.user_table.get(str(username or "").strip().upper())
            if not u or str(u["pwd"]).upper() != str(password or "").strip().upper():
                raise AuthenticationFailed("Usuario o clave incorrectos")

    aut = Autorizador()
    for maq in maquinas:
        carpeta = os.path.join(base, maq)
        os.makedirs(carpeta, exist_ok=True)
        aut.add_user(str(maq).upper(), clave, carpeta, perm="elr")

    def avisar(tipo, maquina, archivo, ip, cada=0):
        if not al_evento:
            return
        if cada:
            k = (tipo, ip, maquina)
            t = time.time()
            if t - _ultimo_aviso.get(k, 0) < cada:
                return
            _ultimo_aviso[k] = t
        try:
            al_evento(tipo, maquina or "", os.path.basename(archivo) if archivo else None, ip)
        except Exception as e:
            print("  [ftp] evento:", e)

    class Manejador(FTPHandler):
        banner = "Nexus MetalERP"
        passive_ports = PUERTOS_PASIVOS
        use_sendfile = False

        def on_connect(self):
            avisar("conexion", "", None, self.remote_ip, AVISO_CADA_SEG)

        def ftp_USER(self, line):
            # El usuario es el código de la máquina (T2): se guarda en mayúsculas.
            return super().ftp_USER(str(line or "").strip().upper())

        def on_login(self, username):
            avisar("login", username, None, self.remote_ip, AVISO_CADA_SEG)

        def on_login_failed(self, username, password):
            avisar("login_fallido", (username or "").upper(), None, self.remote_ip)

        def ftp_LIST(self, path):
            r = super().ftp_LIST(path)
            if r:
                avisar("lista", self.username, None, self.remote_ip, AVISO_CADA_SEG)
            return r

        def ftp_NLST(self, path):
            r = super().ftp_NLST(path)
            if r:
                avisar("lista", self.username, None, self.remote_ip, AVISO_CADA_SEG)
            return r

        def ftp_RETR(self, file):
            # Si el torno pide el programa sin extensión (O9999), se le da O9999.NC.
            if not os.path.isfile(file):
                for ext in (".NC", ".nc", ".TXT", ".txt"):
                    if os.path.isfile(file + ext):
                        file = file + ext
                        break
            return super().ftp_RETR(file)

        def on_file_sent(self, file):
            avisar("bajado", self.username, file, self.remote_ip)

        def on_incomplete_file_sent(self, file):
            avisar("bajado_incompleto", self.username, file, self.remote_ip)

    Manejador.authorizer = aut
    try:
        srv = FTPServer(("0.0.0.0", int(puerto)), Manejador)
    except OSError as e:
        _estado.update(ok=False, error=f"No se pudo abrir el puerto {puerto}: {e}")
        return
    srv.max_cons, srv.max_cons_per_ip = 30, 6
    with _lock:
        _servidor = srv

    def correr():
        try:
            srv.serve_forever(timeout=1, blocking=True, handle_exit=False)
        except Exception as e:
            _estado.update(ok=False, error=f"El FTP se cortó: {e}")
        finally:
            _estado.update(activo=False)

    _hilo = threading.Thread(target=correr, name="ftp", daemon=True)
    _hilo.start()
    _estado.update(activo=True, ok=True)

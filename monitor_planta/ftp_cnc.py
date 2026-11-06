"""Servidor FTP del Monitor para la transferencia FTP del Embedded Ethernet
de los controles Fanuc (0i-D/0i-F): el operario, desde el torno, ve la lista
de programas de la carpeta de su máquina y carga el que necesita.

Cada máquina entra con su propio usuario (el código de la máquina, ej. T1) y la
clave del Monitor, y solo ve su carpeta: monitor_planta\\ftp\\<MÁQUINA>\\.
Solo lectura: desde el torno no se puede borrar ni pisar nada en la PC.
"""
import os, threading

_estado = {"activo": False, "ok": None, "error": None, "puerto": None, "usuarios": []}
_servidor = None
_hilo = None
_lock = threading.Lock()
PUERTOS_PASIVOS = range(60000, 60010)


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
        from pyftpdlib.authorizers import DummyAuthorizer
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
    aut = DummyAuthorizer()
    for maq in maquinas:
        carpeta = os.path.join(base, maq)
        os.makedirs(carpeta, exist_ok=True)
        aut.add_user(maq, clave, carpeta, perm="elr")

    def ev(tipo, h, archivo=None):
        if al_evento:
            try:
                al_evento(tipo, h.username or "", os.path.basename(archivo) if archivo else None, h.remote_ip)
            except Exception as e:
                print("  [ftp] evento:", e)

    class Manejador(FTPHandler):
        banner = "Monitor de planta MetalERP"
        passive_ports = PUERTOS_PASIVOS
        use_sendfile = False

        def on_login(self, username):
            ev("login", self)

        def on_login_failed(self, username, password):
            if al_evento:
                try:
                    al_evento("login_fallido", (username or "").upper(), None, self.remote_ip)
                except Exception:
                    pass

        def on_file_sent(self, file):
            ev("bajado", self, file)

        def on_incomplete_file_sent(self, file):
            ev("bajado_incompleto", self, file)

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

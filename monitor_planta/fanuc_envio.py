"""Envío de programas a un CNC Fanuc (PC -> memoria del control).

Para ESCRIBIR en el control se usa la librería oficial de Fanuc (FOCAS2,
Fwlib), no el protocolo armado a mano de fanuc_focas.py: así el control
recibe exactamente lo que espera. Funciones: cnc_dwnstart3 / cnc_download3 /
cnc_dwnend3 (programa nuevo), cnc_delete (borrar, solo para reemplazar con
confirmación) y cnc_rdprgnum (programa en ejecución / principal).

Dónde busca la librería (fwlibe64.dll en Python de 64 bits, fwlib32.dll en 32):
  1. la carpeta "fwlib_dir" de config.json
  2. monitor_planta\\fwlib\\
  3. el paquete chattertools (pip install chattertools) -> lib\\Fwlib64 o Fwlib32
"""
import ctypes, glob, os, re, struct, sys, time

AQUI = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
ES_64 = struct.calcsize("P") == 8
_dll = None
_dll_ruta = None

EW = {-16: "No hay comunicación con el control (EW_SOCKET)", -15: "Falta una DLL de Fanuc (EW_NODLL)",
      -8: "Conexión inválida (EW_HANDLE)", -2: "El control pidió parar (RESET)",
      -1: "El control está ocupado (otra transferencia o edición en segundo plano)",
      1: "Función no disponible en este control (EW_FUNC)", 2: "Largo inválido (EW_LENGTH)",
      5: "Datos rechazados por el control (EW_DATA)", 6: "El control no tiene la opción necesaria (EW_NOOPT)",
      7: "Memoria protegida contra escritura (llave de programa o parámetro de protección O8000/O9000)",
      8: "No hay lugar en la memoria del control", 9: "Parámetro no habilitado (EW_PARAM)",
      10: "Buffer lleno (EW_BUFFER)", 12: "El control está en modo MDI o editando en segundo plano: cambiá de modo",
      13: "El control rechazó la operación en este estado (EW_REJECT)", 15: "El control tiene una alarma",
      17: "Dato protegido con contraseña (EW_PASSWD)"}
DETALLE_DATA = {1: "hay un carácter que el control no acepta", 2: "bloque con cantidad impar de caracteres (chequeo TV)",
                3: "la memoria ya tiene la cantidad máxima de programas",
                4: "ese número de programa ya existe en el control",
                5: "ese número de programa está seleccionado en el control"}


class ErrorEnvio(Exception):
    pass


def _candidatas(cfg_dir=None):
    sub = "Fwlib64" if ES_64 else "Fwlib32"
    nombre = "fwlibe64.dll" if ES_64 else "fwlib32.dll"
    carpetas = []
    if cfg_dir:
        carpetas.append(cfg_dir)
    carpetas.append(os.path.join(AQUI, "fwlib"))
    try:
        import importlib.util
        spec = importlib.util.find_spec("chattertools")
        if spec and spec.submodule_search_locations:
            for base in spec.submodule_search_locations:
                carpetas.append(os.path.join(base, "lib", sub))
    except Exception:
        pass
    for base in {os.path.dirname(sys.executable), sys.prefix}:
        carpetas += glob.glob(os.path.join(base, "Lib", "site-packages", "chattertools", "lib", sub))
    return [os.path.join(c, nombre) for c in carpetas]


def cargar(cfg_dir=None):
    """Carga la DLL de Fanuc. Devuelve la ruta o lanza ErrorEnvio."""
    global _dll, _dll_ruta
    if _dll is not None:
        return _dll_ruta
    if os.name != "nt":
        raise ErrorEnvio("El envío de programas funciona solo en Windows (librería de Fanuc)")
    probadas = []
    for ruta in _candidatas(cfg_dir):
        if not os.path.exists(ruta):
            probadas.append(ruta)
            continue
        try:
            carpeta = os.path.dirname(ruta)
            os.add_dll_directory(carpeta)
            os.environ["PATH"] = carpeta + os.pathsep + os.environ.get("PATH", "")
            dll = ctypes.WinDLL(ruta)
        except OSError as e:
            raise ErrorEnvio(f"No se pudo cargar {ruta}: {e} (¿la bloquea el antivirus?)")
        us, sh, lg = ctypes.c_ushort, ctypes.c_short, ctypes.c_long
        dll.cnc_allclibhndl3.argtypes = [ctypes.c_char_p, us, lg, ctypes.POINTER(us)]
        dll.cnc_freelibhndl.argtypes = [us]
        dll.cnc_dwnstart3.argtypes = [us, sh]
        dll.cnc_download3.argtypes = [us, ctypes.POINTER(lg), ctypes.c_char_p]
        dll.cnc_dwnend3.argtypes = [us]
        dll.cnc_delete.argtypes = [us, sh]
        dll.cnc_rdprgnum.argtypes = [us, ctypes.c_void_p]
        dll.cnc_getdtailerr.argtypes = [us, ctypes.c_void_p]
        for f in ("cnc_allclibhndl3", "cnc_freelibhndl", "cnc_dwnstart3", "cnc_download3", "cnc_dwnend3",
                  "cnc_delete", "cnc_rdprgnum", "cnc_getdtailerr"):
            getattr(dll, f).restype = sh
        _dll, _dll_ruta = dll, ruta
        return ruta
    raise ErrorEnvio("No está instalada la librería de Fanuc (FOCAS2). Instalala con: "
                     "pip install chattertools   o copiá las DLL de Fwlib en monitor_planta\\fwlib\\")


def disponible(cfg_dir=None):
    try:
        return {"ok": True, "dll": cargar(cfg_dir)}
    except ErrorEnvio as e:
        return {"ok": False, "error": str(e)}


class _Conexion:
    def __init__(self, ip, puerto=8193, timeout=10, cfg_dir=None):
        cargar(cfg_dir)
        self.h = ctypes.c_ushort(0)
        r = _dll.cnc_allclibhndl3(str(ip).encode("ascii"), int(puerto or 8193), timeout, ctypes.byref(self.h))
        if r != 0:
            raise ErrorEnvio(f"No se pudo conectar con {ip}:{puerto}: {EW.get(r, r)}")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        _dll.cnc_freelibhndl(self.h)

    def detalle(self):
        b = (ctypes.c_short * 2)()
        if _dll.cnc_getdtailerr(self.h, b) == 0:
            return b[0]
        return None

    def error(self, r, que):
        txt = EW.get(r, f"código {r}")
        if r == 5:
            d = self.detalle()
            if d in DETALLE_DATA:
                txt = "El control rechazó el programa: " + DETALLE_DATA[d]
        return ErrorEnvio(f"{que}: {txt}")


def numero_en_texto(texto):
    m = re.search(r"^\s*O(\d{1,8})", texto.replace("\r", ""), re.M)
    return int(m.group(1)) if m else None


def preparar(texto, numero):
    """Texto listo para el control: \\nO<numero>...\\n%  (sin %, sin CR, solo ASCII).
    La línea O del archivo se reemplaza por el número elegido (se conserva el comentario)."""
    lineas = [l.rstrip() for l in texto.replace("\r", "").split("\n")]
    while lineas and lineas[0].strip() in ("", "%"):
        lineas.pop(0)
    while lineas and lineas[-1].strip() in ("", "%"):
        lineas.pop()
    if not lineas:
        raise ErrorEnvio("El archivo no tiene código")
    if any(l.strip() == "%" for l in lineas):
        raise ErrorEnvio("El archivo tiene más de un programa (hay un % en el medio). Mandá uno por vez.")
    nom = ("O%04d" % numero) if numero < 10000 else ("O%08d" % numero)
    m = re.match(r"^\s*O\d+\s*(.*)$", lineas[0])
    if m:
        lineas[0] = nom + m.group(1)
    else:
        lineas.insert(0, nom)
    cuerpo = "\n".join(lineas)
    malos = sorted({c for c in cuerpo if ord(c) > 126 or (ord(c) < 32 and c != "\n")})
    if malos:
        raise ErrorEnvio("El programa tiene caracteres que el control no acepta: " + " ".join(repr(c) for c in malos[:10]))
    return "\n" + cuerpo + "\n%"


def programa_activo(ip, puerto=8193, cfg_dir=None):
    """(en ejecución, principal) según el control."""
    with _Conexion(ip, puerto, cfg_dir=cfg_dir) as c:
        b = (ctypes.c_byte * 16)()
        r = _dll.cnc_rdprgnum(c.h, b)
        if r != 0:
            raise c.error(r, "No se pudo leer el programa activo")
        _, _, run, main = struct.unpack("<hhii", bytes(b)[:12])
        return run, main


def borrar(ip, puerto, numero, cfg_dir=None):
    with _Conexion(ip, puerto, cfg_dir=cfg_dir) as c:
        r = _dll.cnc_delete(c.h, int(numero))
        if r != 0:
            raise c.error(r, f"No se pudo borrar O{numero:04d}")


def enviar(ip, puerto, datos, cfg_dir=None, avance=None):
    """Manda un programa ya preparado (ver preparar()). El control rechaza
    un número que ya existe, así que esto nunca pisa nada."""
    raw = datos.encode("ascii")
    with _Conexion(ip, puerto, cfg_dir=cfg_dir) as c:
        r = _dll.cnc_dwnstart3(c.h, 0)
        if r != 0:
            raise c.error(r, "El control no aceptó empezar el envío")
        err = None
        try:
            enviado, fin = 0, time.time() + 120
            while enviado < len(raw):
                parte = raw[enviado:enviado + 1280]
                n = ctypes.c_long(len(parte))
                r = _dll.cnc_download3(c.h, ctypes.byref(n), parte)
                if r == 10:
                    if time.time() > fin:
                        raise ErrorEnvio("El control dejó de recibir datos")
                    time.sleep(0.05)
                    continue
                if r != 0:
                    err = c.error(r, "Error mandando el programa")
                    break
                enviado += max(0, n.value)
                if avance:
                    avance(enviado, len(raw))
        finally:
            r = _dll.cnc_dwnend3(c.h)
        if err:
            raise err
        if r != 0:
            raise c.error(r, "El control no guardó el programa")


def normalizar(texto):
    """Para comparar lo mandado con lo que quedó en el control."""
    t = texto.replace("\r", "")
    lineas = [re.sub(r"\s+", "", l) for l in t.split("\n")]
    return [l for l in lineas if l and l != "%"]

"""Lectura del contador de piezas de un CNC Fanuc por red (FOCAS2, puerto 8193).

Python puro: no necesita la librería de Fanuc (Fwlib32.dll). El protocolo sale
de pyfanuc (github.com/diohpix/pyfanuc, dominio público), reducido a lo que usa
el Monitor: abrir la conexión, leer datos del sistema, leer una variable de
macro (#3901 = piezas hechas) o un parámetro (6711 = piezas hechas), listar y
bajar los programas de la memoria del control (backup), leer las alarmas
activas y cerrar.

Prueba rápida desde la PC:   python fanuc_focas.py 192.168.1.200
"""
import re, socket, sys
from struct import pack, unpack

CABECERA = b"\xa0\xa0\xa0\xa0"
ABRIR, ABRIR_OK = 0x0101, 0x0102
PEDIDO, RESPUESTA = 0x2101, 0x2102
CERRAR, CERRAR_OK = 0x0201, 0x0202
# Subida de programas (control -> PC), como cnc_upstart/cnc_upload de Fwlib
SUBIR, SUBIR_FIN, SUBIR_FIN_OK = 0x1501, 0x1701, 0x1702
SUBIR_DATOS = 0x16   # byte alto de las tramas con texto: 0x1604 en unos controles, 0x1602 en el 0i-D


# Grupos de alarma de Fanuc (cnc_rdalmmsg2): el prefijo que muestra la pantalla ALARM
TIPOS_ALARMA = {0: "SW", 1: "PW", 2: "IO", 3: "PS", 4: "OT", 5: "OH", 6: "SV", 7: "SR", 8: "MC",
                9: "SP", 10: "DS", 11: "IE", 12: "BG", 13: "SN", 15: "EX", 19: "PC"}


class ErrorFanuc(Exception):
    pass


class Fanuc:
    def __init__(self, ip, puerto=8193, timeout=5):
        self.ip, self.puerto, self.timeout = ip, int(puerto or 8193), timeout
        self.sock = None
        self.sysinfo = None

    # ── conexión ──
    def __enter__(self):
        self.abrir()
        return self

    def __exit__(self, *a):
        self.cerrar()

    def abrir(self):
        try:
            self.sock = socket.create_connection((self.ip, self.puerto), timeout=self.timeout)
        except OSError as e:
            raise ErrorFanuc(f"No se pudo conectar con {self.ip}:{self.puerto} ({e}). "
                             "Revisá el cable, la IP del torno y que FOCAS2 tenga el puerto 8193.")
        self.sock.settimeout(self.timeout)
        self._mandar(ABRIR, b"\x00\x02")
        tipo, _ = self._recibir()
        if tipo != ABRIR_OK:
            raise ErrorFanuc("El control no aceptó la conexión FOCAS (respuesta inesperada)")
        try:
            self.sysinfo = self._leer_sysinfo()
        except ErrorFanuc:
            self.sysinfo = {}

    def cerrar(self):
        if not self.sock:
            return
        try:
            self._mandar(CERRAR, b"")
            self._recibir()
        except Exception:
            pass
        try:
            self.sock.close()
        except OSError:
            pass
        self.sock = None

    # ── tramas ──
    def _mandar(self, tipo, datos):
        self.sock.sendall(CABECERA + pack(">HHH", 1, tipo, len(datos)) + datos)

    def _leer_exacto(self, n):
        b = b""
        while len(b) < n:
            parte = self.sock.recv(n - len(b))
            if not parte:
                raise ErrorFanuc("El control cerró la conexión")
            b += parte
        return b

    def _recibir(self):
        cab = self._leer_exacto(10)
        if not cab.startswith(CABECERA):
            raise ErrorFanuc("Respuesta que no es FOCAS (¿es el puerto correcto?)")
        _, tipo, largo = unpack(">HHH", cab[4:10])
        return tipo, (self._leer_exacto(largo) if largo else b"")

    def _pedido(self, c1, c2, c3, v1=0, v2=0, v3=0, v4=0, v5=0):
        cmd = pack(">HHH", c1, c2, c3)
        sub = cmd + pack(">iiiii", v1, v2, v3, v4, v5)
        self._mandar(PEDIDO, pack(">HH", 1, len(sub) + 2) + sub)
        tipo, datos = self._recibir()
        if tipo != RESPUESTA or len(datos) < 4:
            raise ErrorFanuc("Respuesta inesperada del control")
        cant, = unpack(">H", datos[0:2])
        largo, = unpack(">H", datos[2:4])
        bloque = datos[4:2 + largo]
        if not bloque.startswith(cmd):
            raise ErrorFanuc("Respuesta de otro pedido")
        if bloque[6:12] != b"\x00" * 6:
            err, = unpack(">h", bloque[6:8])
            raise ErrorFanuc(f"El control devolvió el error {err}")
        n, = unpack(">H", bloque[12:14])
        return bloque[14:14 + n]

    # ── lecturas ──
    def _leer_sysinfo(self):
        d = self._pedido(1, 1, 0x18)
        if len(d) < 0x12:
            return {}
        addinfo, maxaxis, cnctype, mttype, series, version, axes = unpack(">HH2s2s4s4s2s", d[:0x12])
        dec = lambda b: b.decode("ascii", "replace").strip("\x00 ")
        return {"ejes_max": maxaxis, "cnc": dec(cnctype), "tipo": dec(mttype),
                "serie": dec(series), "version": dec(version), "ejes": dec(axes)}

    def leer_macro(self, numero):
        """Variable de macro (#3901 = piezas hechas). None si está vacía."""
        d = self._pedido(1, 1, 0x15, numero, numero)
        if len(d) < 8:
            return None
        if d[6:8] == b"\xff\xff":
            return None
        valor, = unpack(">i", d[0:4])
        base, exp = d[5], d[7]
        if base in (2, 10) and exp:
            return valor / base ** exp
        return valor

    def leer_parametro(self, numero):
        """Parámetro entero (6711 = piezas hechas)."""
        d = self._pedido(1, 1, 0x0E, numero, numero, 0)
        if len(d) < 12:
            return None
        _, eje, tipo = unpack(">IhH", d[0:8])
        v = d[8:12]
        if tipo == 3:
            return unpack(">i", v)[0]
        if tipo == 2:
            return unpack(">h", v[2:4])[0]
        return v[-1]

    # ── programas (backup) ──
    def listar_programas(self):
        """Programas de la memoria del control: {numero: {"tam": bytes, "comentario": str}}."""
        res, desde = {}, 1
        for _ in range(2000):            # tope de seguridad
            try:
                d = self._pedido(1, 1, 0x06, desde, 0x13, 2)
            except ErrorFanuc:
                if res:            # algunos controles dan error al pasar el último
                    break
                raise
            if not d:
                break
            nuevos = 0
            for t in range(0, len(d) - 71, 72):
                numero, tam, com = unpack(">II64s", d[t:t + 72])
                if numero <= 0 or numero in res:
                    continue
                res[numero] = {"tam": tam,
                               "comentario": com.split(b"\0", 1)[0].decode("ascii", "replace").strip()}
                desde = max(desde, numero + 1)
                nuevos += 1
            if not nuevos:
                break
        return res

    def bajar(self, desde, hasta=None, timeout=20):
        """Texto de los programas O<desde>..O<hasta> tal como los manda el control
        (con los % de inicio y fin). Usa una conexión aparte, como Fwlib."""
        nom = lambda n: ("O%04d" % n) if n < 10000 else ("O%08d" % n)
        q = (nom(desde) + "-" + nom(hasta if hasta is not None else desde)).encode("ascii")
        s = socket.create_connection((self.ip, self.puerto), timeout=self.timeout)
        try:
            s.settimeout(timeout)
            s.sendall(CABECERA + pack(">HHH", 1, ABRIR, 2) + b"\x00\x01")
            tipo, _, buf = self._trama(s, b"")
            if tipo != ABRIR_OK:
                raise ErrorFanuc("El control no aceptó la conexión para bajar programas")
            pedido = bytearray(0x204)
            pedido[0:4] = b"\x00\x00\x00\x01"
            pedido[4:4 + len(q)] = q
            s.sendall(CABECERA + pack(">HHH", 1, SUBIR, len(pedido)) + bytes(pedido))
            tipo, datos, buf = self._trama(s, buf)       # acuse del pedido
            if tipo == SUBIR_FIN:
                s.sendall(CABECERA + pack(">HHH", 1, SUBIR_FIN_OK, 0))
                return ""
            texto = datos if tipo >> 8 == SUBIR_DATOS else b""
            while True:
                tipo, datos, buf = self._trama(s, buf)
                if tipo >> 8 == SUBIR_DATOS:
                    texto += datos
                elif tipo == SUBIR_FIN:
                    s.sendall(CABECERA + pack(">HHH", 1, SUBIR_FIN_OK, 0))
                    break
                if len(texto) > 64 * 1024 * 1024:
                    raise ErrorFanuc("El programa es demasiado grande")
            return texto.decode("latin-1")
        except socket.timeout:
            raise ErrorFanuc(f"El control dejó de mandar datos al bajar {q.decode()}")
        finally:
            try:
                s.sendall(CABECERA + pack(">HHH", 1, CERRAR, 0))
            except OSError:
                pass
            s.close()

    @staticmethod
    def _trama(s, buf):
        """Lee una trama entera de un socket: (tipo, datos, lo que sobró)."""
        while True:
            if len(buf) >= 10:
                if not buf.startswith(CABECERA):
                    raise ErrorFanuc("Respuesta que no es FOCAS al bajar programas")
                _, tipo, largo = unpack(">HHH", buf[4:10])
                if len(buf) >= 10 + largo:
                    return tipo, buf[10:10 + largo], buf[10 + largo:]
            parte = s.recv(65536)
            if not parte:
                raise ErrorFanuc("El control cerró la conexión al bajar programas")
            buf += parte

    # ── alarmas ──
    def leer_alarmas(self, maximo=10):
        """Alarmas activas del control: [{"tipo": "SP", "numero": 9001, "codigo": "SP9001",
        "texto": "MOTOR OVERHEAT", "eje": 0}]. Lista vacía si no hay ninguna.
        Primero pide todas juntas (tipo -1); si el control no lo acepta, lee qué
        grupos tienen alarma (mapa de bits) y pide cada grupo."""
        try:
            return self._alarmas_tipo(-1, maximo)
        except ErrorFanuc:
            mapa = self._pedido(1, 1, 0x1A)
            if len(mapa) < 4:
                raise ErrorFanuc("El control no devolvió las alarmas")
            bits, = unpack(">L", mapa[:4])
            res = []
            for t in range(32):
                if bits & (1 << t):
                    try:
                        res += self._alarmas_tipo(t, maximo)
                    except ErrorFanuc:
                        res.append({"tipo": TIPOS_ALARMA.get(t, "AL"), "numero": None,
                                    "codigo": TIPOS_ALARMA.get(t, "AL"), "texto": "", "eje": 0})
            return res

    def _alarmas_tipo(self, tipo, maximo, largo_texto=32):
        d = self._pedido(1, 1, 0x23, tipo, maximo, 1, largo_texto)
        res, paso = [], 16 + largo_texto
        for pos in range(0, len(d) - 15, paso):
            num, t, eje, n = unpack(">iiii", d[pos:pos + 16])
            txt = d[pos + 16:pos + 16 + max(0, min(n, largo_texto))]
            txt = txt.split(b"\0", 1)[0].decode("latin-1", "replace").strip()
            pref = TIPOS_ALARMA.get(t, "AL")
            res.append({"tipo": pref, "numero": num, "codigo": f"{pref}{num:04d}" if num >= 0 else pref,
                        "texto": txt, "eje": eje})
        return res

    def piezas(self):
        """Contador de piezas: #3901 y, si no se puede, el parámetro 6711."""
        try:
            v = self.leer_macro(3901)
            if v is not None:
                return int(round(v)), "#3901"
        except ErrorFanuc:
            pass
        v = self.leer_parametro(6711)
        if v is None:
            raise ErrorFanuc("El control no devolvió el contador de piezas (#3901 ni parámetro 6711)")
        return int(v), "parámetro 6711"


def leer_piezas(ip, puerto=8193, timeout=5):
    with Fanuc(ip, puerto, timeout) as f:
        n, origen = f.piezas()
        return {"contador": n, "origen": origen, "sysinfo": f.sysinfo}


def separar_programas(texto):
    """Parte el texto de varios programas en {numero: texto}. Cada programa
    empieza en una línea con O<número> solo o seguido de un comentario
    (una línea como O47G99 es parte del programa, no el inicio de otro)."""
    texto = texto.replace("\r", "")
    res, num, lineas = {}, None, []
    for ln in texto.split("\n"):
        m = re.match(r"\s*O(\d+)\s*(\(.*)?$", ln)
        if m:
            if num is not None:
                res[num] = "\n".join(lineas).strip("%\n ") + "\n"
            num, lineas = int(m.group(1)), [ln]
        elif num is not None:
            lineas.append(ln)
    if num is not None:
        res[num] = "\n".join(lineas).strip("%\n ") + "\n"
    return res


def backup_programas(ip, puerto=8193, avance=None):
    """Baja todos los programas de la memoria del control.
    Devuelve (programas {numero: texto}, lista {numero: {tam, comentario}}, errores [str]).
    avance(hechos, total, actual) se llama mientras baja."""
    errores = []
    with Fanuc(ip, puerto, timeout=10) as f:
        sysinfo = f.sysinfo
        try:
            lista = f.listar_programas()
        except ErrorFanuc as e:
            lista, errores = {}, [f"No se pudo leer la lista de programas: {e}"]
        programas = {}
        if lista:
            total = len(lista)
            for i, n in enumerate(sorted(lista)):
                if avance:
                    avance(i, total, n)
                try:
                    txt = f.bajar(n)
                    if not txt.strip("%\r\n "):
                        raise ErrorFanuc("el control no mandó el contenido del programa")
                    # Sin separar_programas: se pidió uno solo y puede tener líneas como O47G99
                    programas[n] = txt.replace("\r", "").strip("%\n ") + "\n"
                except ErrorFanuc as e:
                    errores.append(f"O{n:04d}: {e}")
            if avance:
                avance(total, total, None)
        else:
            # Sin lista: se pide todo junto (O0001 a O9999) y se separa
            if avance:
                avance(0, 0, "todos")
            programas = separar_programas(f.bajar(1, 9999, timeout=60))
            if programas:
                errores = []
    return programas, lista, errores, sysinfo


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python fanuc_focas.py <IP del torno> [puerto]")
        sys.exit(1)
    try:
        with Fanuc(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else 8193) as f:
            print("Conectado. Control:", f.sysinfo)
            try:
                print("Macro #3901 (piezas hechas):", f.leer_macro(3901))
            except ErrorFanuc as e:
                print("Macro #3901:", e)
            try:
                print("Parámetro 6711 (piezas hechas):", f.leer_parametro(6711))
            except ErrorFanuc as e:
                print("Parámetro 6711:", e)
            try:
                al = f.leer_alarmas()
                print("Alarmas activas:", ", ".join(f"{a['codigo']} {a['texto']}" for a in al) or "ninguna")
            except ErrorFanuc as e:
                print("Alarmas:", e)
            try:
                progs = f.listar_programas()
                print(f"Programas en memoria: {len(progs)}", ", ".join("O%04d" % n for n in sorted(progs)[:30]))
            except ErrorFanuc as e:
                print("Lista de programas:", e)
    except ErrorFanuc as e:
        print("ERROR:", e)
        sys.exit(2)
    input("\nApretá Enter para cerrar...") if sys.stdin and sys.stdin.isatty() and sys.platform == "win32" else None

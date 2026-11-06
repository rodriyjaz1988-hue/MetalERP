"""Diagnóstico de bajada de programas de un Fanuc por FOCAS2 (SOLO LECTURA).

Pide UN programa al control en varios formatos de pedido y guarda todo lo que
contesta, para saber qué formato entiende ese control. No escribe nada en la
máquina: solo usa el pedido de subida (control -> PC) y la lista de programas.

Uso:  python diag_bajada.py <IP> [numero_programa] [puerto]
Ej.:  python diag_bajada.py 192.168.10.201 2
Deja el resultado en diag_bajada_<IP>_<fecha>.txt al lado de este archivo.
"""
import os, socket, sys, time
from datetime import datetime
from struct import pack, unpack

CAB = b"\xa0\xa0\xa0\xa0"
AQUI = os.path.dirname(os.path.abspath(__file__))
salida = []


def log(*a):
    t = " ".join(str(x) for x in a)
    print(t)
    salida.append(t)


def trama(s, buf):
    while True:
        if len(buf) >= 10:
            if not buf.startswith(CAB):
                raise RuntimeError("no FOCAS: " + buf[:40].hex())
            v, tipo, largo = unpack(">HHH", buf[4:10])
            if len(buf) >= 10 + largo:
                return v, tipo, buf[10:10 + largo], buf[10 + largo:]
        p = s.recv(65536)
        if not p:
            raise RuntimeError("el control cerró la conexión")
        buf += p


def abrir(ip, puerto, dst):
    s = socket.create_connection((ip, puerto), timeout=8)
    s.settimeout(10)
    s.sendall(CAB + pack(">HHH", 1, 0x0101, 2) + dst)
    v, t, d, buf = trama(s, b"")
    return s, t, d, buf


def cerrar(s):
    try:
        s.sendall(CAB + pack(">HHH", 1, 0x0201, 0))
        s.settimeout(2)
        trama(s, b"")
    except Exception:
        pass
    s.close()


def pedido(s, buf, c3, *v):
    v = list(v) + [0] * (5 - len(v))
    cmd = pack(">HHH", 1, 1, c3)
    sub = cmd + pack(">iiiii", *v)
    s.sendall(CAB + pack(">HHH", 1, 0x2101, len(sub) + 4) + pack(">HH", 1, len(sub) + 2) + sub)
    _, t, d, buf = trama(s, buf)
    return d, buf


def probar_subida(ip, puerto, nombre, cab4, dst, largo_buf=0x204):
    q = nombre.encode("ascii")
    log(f"\n--- Pedido: tipo={cab4.hex()} texto='{nombre}' apertura={dst.hex()} buffer={largo_buf} ---")
    try:
        s, t, d, buf = abrir(ip, puerto, dst)
    except Exception as e:
        log("  no abre:", e)
        return None
    log(f"  apertura -> tipo {t:#06x} datos {d.hex()}")
    texto, tramas = b"", []
    try:
        p = bytearray(largo_buf)
        p[0:4] = cab4
        p[4:4 + len(q)] = q
        s.sendall(CAB + pack(">HHH", 1, 0x1501, len(p)) + bytes(p))
        fin = time.time() + 10
        while time.time() < fin:
            v, t, d, buf = trama(s, buf)
            tramas.append((t, len(d)))
            if len(tramas) <= 6 or t != 0x1604:
                log(f"  trama v{v} tipo {t:#06x} largo {len(d)} datos {d[:120].hex()} | {d[:120]!r}")
            if t == 0x1604:
                texto += d
            if t == 0x1701:
                s.sendall(CAB + pack(">HHH", 1, 0x1702, 0))
                break
    except Exception as e:
        log("  error:", e)
    finally:
        cerrar(s)
    log(f"  total tramas {len(tramas)}, texto {len(texto)} bytes")
    if texto:
        log("  texto (primeros 400):", repr(texto[:400]))
    return texto


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    ip = sys.argv[1]
    num = int(sys.argv[2]) if len(sys.argv) > 2 else None
    puerto = int(sys.argv[3]) if len(sys.argv) > 3 else 8193
    log(f"Diagnóstico bajada FOCAS  {ip}:{puerto}  {datetime.now():%Y-%m-%d %H:%M:%S}")
    s, t, d, buf = abrir(ip, puerto, b"\x00\x02")
    log(f"apertura principal -> {t:#06x}")
    try:
        d, buf = pedido(s, buf, 0x18)
        log("sysinfo:", d.hex(), repr(d))
        try:
            d, buf = pedido(s, buf, 0x1c)
            log("programa en ejecución / principal:", d.hex())
        except Exception as e:
            log("prognum:", e)
        d, buf = pedido(s, buf, 0x06, 1, 0x13, 2)
        log("lista (primer bloque) bruto:", d[:200].hex())
        progs = []
        bloque = d[14:]
        for i in range(0, len(bloque) - 71, 72):
            n, tam, com = unpack(">II64s", bloque[i:i + 72])
            progs.append((n, tam, com.split(b"\0")[0]))
        log("primeros programas:", progs[:5])
        if num is None and progs:
            num = progs[0][0]
    finally:
        cerrar(s)
    if num is None:
        log("No hay programa para probar")
        return
    log(f"\nPrograma a pedir: O{num:04d}")
    variantes = []
    for cab4 in (b"\x00\x00\x00\x01", b"\x00\x00\x00\x00"):
        for nom in (f"O{num:04d}-O{num:04d}", f"O{num:04d}", f"O{num}-O{num}", f"O{num:08d}-O{num:08d}",
                    f"{num:04d}-{num:04d}", f"{num}"):
            variantes.append((nom, cab4))
    resultados = []
    for nom, cab4 in variantes:
        for dst in (b"\x00\x01", b"\x00\x02"):
            txt = probar_subida(ip, puerto, nom, cab4, dst)
            ok = bool(txt and txt.replace(b"%", b"").strip())
            resultados.append((nom, cab4.hex(), dst.hex(), len(txt or b""), ok))
            time.sleep(0.3)
    # pedido viejo (cnc_upstart): número binario en vez de texto
    for cab in (pack(">i", num), pack(">ii", 0, num), pack(">iii", 0, num, num)):
        log(f"\n--- Pedido binario {cab.hex()} ---")
        try:
            s, t, d, buf = abrir(ip, puerto, b"\x00\x01")
            p = bytearray(0x204)
            p[0:len(cab)] = cab
            s.sendall(CAB + pack(">HHH", 1, 0x1501, len(p)) + bytes(p))
            texto = b""
            fin = time.time() + 10
            while time.time() < fin:
                v, t, d, buf = trama(s, buf)
                log(f"  trama tipo {t:#06x} largo {len(d)} {d[:80]!r}")
                if t == 0x1604:
                    texto += d
                if t == 0x1701:
                    s.sendall(CAB + pack(">HHH", 1, 0x1702, 0))
                    break
            cerrar(s)
            resultados.append(("bin " + cab.hex(), "", "0001", len(texto), bool(texto.replace(b"%", b"").strip())))
        except Exception as e:
            log("  error:", e)
    log("\n===== RESUMEN =====")
    for r in resultados:
        log(f"{'OK ' if r[4] else '-- '} texto='{r[0]}' tipo={r[1]} apertura={r[2]} bytes={r[3]}")


if __name__ == "__main__":
    try:
        main()
    finally:
        nom = os.path.join(AQUI, f"diag_bajada_{sys.argv[1] if len(sys.argv) > 1 else 'x'}_{datetime.now():%Y%m%d_%H%M%S}.txt")
        with open(nom, "w", encoding="utf-8") as f:
            f.write("\n".join(salida))
        print("\nResultado guardado en", nom)

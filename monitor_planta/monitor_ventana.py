"""Monitor de planta como programa de Windows con ventana propia.

Arranca el Monitor (el mismo de monitor.py: recibe las piezas del router y
manda los paquetes a MetalERP) y lo muestra en su propia ventana, sin
navegador. Si ya hay un Monitor corriendo en esta PC, solo abre la ventana.
Al cerrar la ventana el Monitor se detiene y deja de recibir piezas, por eso
pide confirmación.
"""
import os, socket, sys, threading, time, urllib.request

import monitor

# Sin consola (.exe con ventana) no hay dónde escribir: lo que el Monitor
# imprime va a monitor.log, al lado del .exe.
if sys.stdout is None or sys.stderr is None:
    _log = open(os.path.join(monitor.AQUI, "monitor.log"), "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stdout or _log
    sys.stderr = sys.stderr or _log


def puerto_ocupado(puerto):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", puerto)) == 0


def esperar_servidor(url, segundos=30):
    fin = time.time() + segundos
    while time.time() < fin:
        try:
            urllib.request.urlopen(url + "/api/estado", timeout=2).read()
            return True
        except Exception:
            time.sleep(0.3)
    return False


def main():
    import webview

    puerto = int(monitor.cfg().get("puerto") or 5100)
    url = f"http://127.0.0.1:{puerto}"
    ya_corria = puerto_ocupado(puerto)
    if not ya_corria:
        threading.Thread(target=monitor.arrancar_servidor, name="servidor", daemon=True).start()
    if not esperar_servidor(url):
        webview.create_window("Nexus", html=(
            "<body style='font-family:Segoe UI,sans-serif;padding:30px'><h2>Nexus no pudo arrancar</h2>"
            f"<p>Revisá que el puerto {puerto} no lo esté usando otro programa. "
            "El detalle está en monitor.log, al lado del programa.</p></body>"))
        webview.start()
        return
    webview.create_window(
        "Nexus" + (" (ya estaba abierto)" if ya_corria else ""),
        url, width=1320, height=860, min_size=(900, 600),
        # Cerrar la ventana apaga el Monitor: las piezas del router dejan de llegar.
        confirm_close=not ya_corria)
    webview.start()


if __name__ == "__main__":
    main()

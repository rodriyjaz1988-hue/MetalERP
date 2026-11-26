"""Agrega a MetalERP (metalerp_v3\\server.py) la ruta POST /api/planta/v1/paradas:
las paradas que el operario carga en el torno (Monitor de planta) quedan como
Trabajo no productivo del operario que tenía la máquina a esa hora.

Uso:  python patch_paradas.py C:\\MetalERP\\metalerp_v3\\server.py
Deja copia server.py.bak_paradas_<fecha>. No cambia la versión del esquema: la
tabla planta_paradas se crea sola la primera vez que llega una parada.
"""
import os, shutil, sys
from datetime import datetime

ANCLA = '@app.route("/api/planta/v1/paquetes/<uuid_p>")'
MARCA = '@app.route("/api/planta/v1/paradas", methods=["POST"])'

BLOQUE = '''@app.route("/api/planta/v1/paradas", methods=["POST"])
@clave_planta_requerida
def monitor_api_paradas():
    """Paradas que el operario cargó en el torno (variable de macro, Monitor de
    planta). Cada una queda como Trabajo no productivo con el motivo, la
    duración y el operario elegido para la máquina en Máquinas en planta a la
    hora en que empezó. Un reenvío de la misma parada (mismo uuid) no duplica."""
    d = request.get_json(silent=True) or {}
    lista = d.get("paradas")
    if not isinstance(lista, list):
        return jsonify({"error": "Falta la lista de paradas"}), 400
    if len(lista) > 2000:
        return jsonify({"error": "Máximo 2000 paradas por envío"}), 413
    db = get_db()
    db.execute("""CREATE TABLE IF NOT EXISTS planta_paradas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        uuid TEXT UNIQUE NOT NULL,
        clave_id INTEGER,
        maquina_id INTEGER,
        codigo INTEGER,
        motivo TEXT,
        inicio TEXT,
        fin TEXT,
        minutos REAL,
        empleado_id INTEGER,
        tnp_id INTEGER,
        recibido TEXT DEFAULT (datetime('now','localtime')))""")
    db.commit()
    maqs = {r["codigo"].upper(): r["id"] for r in db.execute("SELECT id, codigo FROM maquinas").fetchall()}
    resultado, errores = {}, []
    for p in lista:
        if not isinstance(p, dict):
            errores.append({"error": "Formato inválido"}); continue
        u = str(p.get("uuid") or "").strip()[:64]
        if not u:
            errores.append({"error": "Falta uuid"}); continue
        prev = db.execute("""SELECT pp.tnp_id, t.numero FROM planta_paradas pp
            LEFT JOIN trabajo_no_productivo t ON t.id=pp.tnp_id WHERE pp.uuid=?""", (u,)).fetchone()
        if prev:
            resultado[u] = {"tnp": prev["numero"], "repetida": True}; continue
        mid = maqs.get(str(p.get("maquina") or "").strip().upper())
        ini, fin = _monitor_hora(p.get("inicio")), _monitor_hora(p.get("fin"))
        motivo = str(p.get("motivo") or "").strip()[:120]
        try:
            minutos = round(float(p.get("minutos")), 2)
        except (TypeError, ValueError):
            minutos = 0
        if not mid:
            errores.append({"uuid": u, "error": f"Máquina \\"{p.get('maquina')}\\" no existe en MetalERP"}); continue
        if not ini or not motivo:
            errores.append({"uuid": u, "error": "Falta el inicio o el motivo"}); continue
        if minutos <= 0:
            minutos = 0.01
        op = db.execute("""SELECT empleado_id FROM planta_maquina_ops WHERE maquina_id=? AND desde<=?
            AND (hasta IS NULL OR hasta>?) ORDER BY desde DESC, id DESC LIMIT 1""", (mid, ini, ini)).fetchone()
        emp = op["empleado_id"] if op else None
        with transaccion():
            numero = siguiente_numero("trabajo_no_productivo", "TNP-", 5, reservar=True)
            tid = db.execute("""INSERT INTO trabajo_no_productivo (numero, empleado_id, descripcion, tiempo_min, fecha)
                VALUES (?,?,?,?,?)""", (numero, emp, motivo, minutos, ini)).lastrowid
            try:
                cod = int(p.get("codigo")) if p.get("codigo") not in (None, "") else None
            except (TypeError, ValueError):
                cod = None
            db.execute("""INSERT INTO planta_paradas (uuid, clave_id, maquina_id, codigo, motivo, inicio, fin, minutos,
                empleado_id, tnp_id) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (u, g.planta_clave["id"], mid, cod, motivo, ini, fin, minutos, emp, tid))
        resultado[u] = {"tnp": numero, "operario": emp}
    return jsonify({"recibidas": len(lista), "resultado": resultado, "errores": errores})


'''


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    ruta = sys.argv[1]
    with open(ruta, encoding="utf-8", newline="") as f:
        s = f.read()
    if MARCA in s:
        print("Ya estaba aplicado: no se cambió nada.")
        return
    crlf = "\r\n" in s
    if s.count(ANCLA) != 1:
        print("No encontré el lugar donde va (", ANCLA, "): no se cambió nada.")
        sys.exit(2)
    for nec in ("def clave_planta_requerida", "def _monitor_hora", "class transaccion", "def siguiente_numero",
                "CREATE TABLE IF NOT EXISTS planta_maquina_ops", "CREATE TABLE IF NOT EXISTS trabajo_no_productivo"):
        if nec not in s:
            print("Falta", nec, "en server.py: no se cambió nada.")
            sys.exit(3)
    bloque = BLOQUE.replace("\n", "\r\n") if crlf else BLOQUE
    nuevo = s.replace(ANCLA, bloque + ANCLA, 1)
    copia = ruta + ".bak_paradas_" + datetime.now().strftime("%Y%m%d_%H%M")
    shutil.copy2(ruta, copia)
    with open(ruta + ".tmp", "w", encoding="utf-8", newline="") as f:
        f.write(nuevo)
    os.replace(ruta + ".tmp", ruta)
    print("Listo. Copia del anterior:", copia)


if __name__ == "__main__":
    main()

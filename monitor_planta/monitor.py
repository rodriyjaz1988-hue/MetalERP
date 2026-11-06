"""Monitor de planta: app aparte de MetalERP.

Recibe del router una señal por cada pieza que termina una máquina (o el
contador del CNC), guarda cada pieza en su propia base y una vez por hora
manda el paquete a MetalERP por la API. Si MetalERP no responde, el paquete
queda guardado y se reintenta cada 5 minutos, sin duplicar nada.

Arranque: INICIAR_MONITOR.bat (o python monitor.py). Pantalla: http://<pc>:5100
"""
import io, json, os, re, socket, sqlite3, sys, threading, time, uuid, zipfile
import urllib.request, urllib.error
from datetime import datetime, timedelta
from flask import Flask, jsonify, request, send_from_directory, send_file, g

# Como .exe (PyInstaller): los datos (config.json, monitor.db) van al lado del
# .exe y la pantalla viene adentro del .exe.
if getattr(sys, "frozen", False):
    AQUI = os.path.dirname(os.path.abspath(sys.executable))
    PLANTILLAS = os.path.join(getattr(sys, "_MEIPASS", AQUI), "templates")
else:
    AQUI = os.path.dirname(os.path.abspath(__file__))
    PLANTILLAS = os.path.join(AQUI, "templates")
DB_PATH = os.path.join(AQUI, "monitor.db")
BACKUP_DIR = os.path.join(AQUI, "backups")
CONFIG_PATH = os.path.join(AQUI, "config.json")
CONFIG_DEFECTO = {
    "metalerp_url": "http://localhost:5000",
    "api_key": "",
    "intervalo_min": 60,          # cada cuánto se manda el paquete (alineado al reloj)
    "puerto": 5100,
    "parada_seg": 180,            # sin piezas durante este tiempo: la máquina figura parada
    "senal_token": "",            # si se completa, el router tiene que mandarlo (?token=...)
    # Máquinas que la app lee por red ella misma (sin router):
    # [{"maquina": "SL2000", "tipo": "fanuc", "ip": "192.168.1.200", "puerto": 8193, "multiplo": 1, "activo": true}]
    "lectores": [],
}
LECTOR_SEG = 5                    # cada cuánto se lee el contador de cada máquina
TIPOS_LECTOR = {"fanuc": 8193, "haas": 5051}
REINTENTO_MIN = 5
MAX_PIEZAS_PAQUETE = 5000
MAX_SALTO_CONTADOR = 500          # un salto mayor del contador se toma como reinicio

app = Flask(__name__, template_folder=PLANTILLAS)
_lock_cfg = threading.Lock()
_aviso_envio = threading.Event()
_estado = {"metalerp_ok": None, "metalerp_error": None, "metalerp_visto": None,
           "maquinas": [], "ultimo_envio": None, "proximo_envio": None, "enviando": False}
_lock_contador = threading.Lock()


def ahora():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ── Configuración ────────────────────────────────────────────────────────────
def cfg():
    with _lock_cfg:
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                c = json.load(f)
        except (OSError, ValueError):
            c = {}
        return {**CONFIG_DEFECTO, **c}


def guardar_cfg(nuevo):
    with _lock_cfg:
        c = {**CONFIG_DEFECTO}
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                c.update(json.load(f))
        except (OSError, ValueError):
            pass
        c.update(nuevo)
        tmp = CONFIG_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(c, f, ensure_ascii=False, indent=2)
        os.replace(tmp, CONFIG_PATH)
        return c


# ── Base propia ──────────────────────────────────────────────────────────────
ESQUEMA = """
CREATE TABLE IF NOT EXISTS piezas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT UNIQUE NOT NULL,
    maquina TEXT NOT NULL,
    hora TEXT NOT NULL,
    ciclo_seg REAL,
    contador INTEGER,
    origen TEXT,
    paquete TEXT,                 -- NULL: todavía no entró en un paquete
    creado TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS ix_piezas_paquete ON piezas(paquete, id);
CREATE INDEX IF NOT EXISTS ix_piezas_maq ON piezas(maquina, hora);
CREATE TABLE IF NOT EXISTS paquetes (
    uuid TEXT PRIMARY KEY,
    creado TEXT DEFAULT (datetime('now','localtime')),
    desde TEXT, hasta TEXT,
    piezas INTEGER DEFAULT 0,
    estado TEXT DEFAULT 'Por enviar',   -- Por enviar / Enviado / Error
    intentos INTEGER DEFAULT 0,
    proximo_intento TEXT,
    enviado TEXT,
    respuesta TEXT,
    error TEXT
);
CREATE TABLE IF NOT EXISTS contadores (
    maquina TEXT PRIMARY KEY,
    contador INTEGER,
    hora TEXT
);
CREATE TABLE IF NOT EXISTS ultima_pieza (
    maquina TEXT PRIMARY KEY,
    hora TEXT
);
"""


def conectar():
    db = sqlite3.connect(DB_PATH, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode = WAL")
    db.execute("PRAGMA busy_timeout = 30000")
    return db


def get_db():
    if "db" not in g:
        g.db = conectar()
    return g.db


@app.teardown_appcontext
def _cerrar(e=None):
    db = g.pop("db", None)
    if db:
        db.close()


def init_db():
    db = conectar()
    db.executescript(ESQUEMA)
    db.commit()
    db.close()


# ── Señales del router ───────────────────────────────────────────────────────
def registrar_piezas(db, maquina, n, hora_fin, contador=None, origen="senal"):
    """Guarda n piezas de la máquina terminadas hasta hora_fin, repartidas
    entre la pieza anterior y esta. El ciclo es el tiempo entre piezas."""
    maquina = maquina.strip().upper()
    fin = datetime.strptime(hora_fin, "%Y-%m-%d %H:%M:%S")
    r = db.execute("SELECT hora FROM ultima_pieza WHERE maquina=?", (maquina,)).fetchone()
    anterior = datetime.strptime(r["hora"], "%Y-%m-%d %H:%M:%S") if r else None
    paso = (fin - anterior).total_seconds() / n if anterior and fin > anterior else None
    # Un hueco de más de 30 min no es un ciclo (almuerzo, parada): sin ciclo.
    if paso is not None and paso > 1800:
        paso = None
    filas = []
    for i in range(n):
        h = fin - timedelta(seconds=(paso or 0) * (n - 1 - i))
        filas.append((str(uuid.uuid4()), maquina, h.strftime("%Y-%m-%d %H:%M:%S"),
                       round(paso, 1) if paso else None,
                       (contador - (n - 1 - i)) if contador is not None else None, origen))
    db.executemany("INSERT INTO piezas (uuid, maquina, hora, ciclo_seg, contador, origen) VALUES (?,?,?,?,?,?)", filas)
    db.execute("INSERT INTO ultima_pieza (maquina, hora) VALUES (?,?) ON CONFLICT(maquina) DO UPDATE SET hora=excluded.hora",
               (maquina, hora_fin))
    return n


def delta_contador(db, maq, cont, hora):
    """Piezas nuevas según el contador de la máquina (y lo guarda)."""
    prev = db.execute("SELECT contador FROM contadores WHERE maquina=?", (maq,)).fetchone()
    db.execute("""INSERT INTO contadores (maquina, contador, hora) VALUES (?,?,?)
        ON CONFLICT(maquina) DO UPDATE SET contador=excluded.contador, hora=excluded.hora""", (maq, cont, hora))
    if prev is None or prev["contador"] is None:
        return 0           # primera lectura: solo se toma como referencia
    n = cont - prev["contador"]
    if n < 0 or n > MAX_SALTO_CONTADOR:
        return 0           # el contador se reinició o saltó: nueva referencia
    return n


def _hora_senal(v):
    s = str(v or "").strip().replace("T", " ")[:19]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            h = datetime.strptime(s, fmt)
            # Reloj del router muy corrido: se usa la hora de la PC.
            if abs((h - datetime.now()).total_seconds()) < 12 * 3600:
                return h.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    return ahora()


@app.route("/senal", methods=["GET", "POST"])
def senal():
    """Lo llama el router (o el programa puente) por cada pieza:
         GET  /senal?maquina=T16                 -> 1 pieza
         GET  /senal?maquina=T16&contador=18452   -> las piezas desde el último contador
         GET  /senal?maquina=T16&piezas=3         -> 3 piezas
         POST /senal  {"maquina": "T16", "contador": 18452, "hora": "..."}  (o una lista de esos)
    """
    c = cfg()
    datos = request.get_json(silent=True) if request.method == "POST" else None
    if datos is None:
        datos = dict(request.values)
    lista = datos if isinstance(datos, list) else [datos]
    if c.get("senal_token") and (request.values.get("token") or (lista[0] or {}).get("token")) != c["senal_token"]:
        return jsonify({"error": "token inválido"}), 403
    total, res = 0, []
    db = get_db()
    with _lock_contador:
        for d in lista:
            if not isinstance(d, dict):
                continue
            maq = str(d.get("maquina") or "").strip().upper()
            if not maq:
                res.append({"error": "falta maquina"}); continue
            hora = _hora_senal(d.get("hora"))
            n = 1
            cont = d.get("contador")
            if cont not in (None, ""):
                try:
                    cont = int(float(cont))
                except (TypeError, ValueError):
                    res.append({"maquina": maq, "error": "contador inválido"}); continue
                n = delta_contador(db, maq, cont, hora)
            elif d.get("piezas") not in (None, ""):
                try:
                    n = max(0, min(MAX_SALTO_CONTADOR, int(float(d.get("piezas")))))
                except (TypeError, ValueError):
                    n = 0
            else:
                cont = None
            if n:
                registrar_piezas(db, maq, n, hora, cont if isinstance(cont, int) else None,
                                 origen=str(d.get("origen") or "router")[:20])
            total += n
            res.append({"maquina": maq, "piezas": n})
        db.commit()
    return jsonify({"ok": True, "piezas": total, "detalle": res})


# ── Conexión con MetalERP ────────────────────────────────────────────────────
def llamar_metalerp(metodo, ruta, cuerpo=None, timeout=60, url_base=None, sin_clave=False):
    c = cfg()
    if not sin_clave and not c.get("api_key"):
        raise RuntimeError("La app todavía no está conectada con MetalERP (Configuración → Conectar)")
    url = (url_base or c["metalerp_url"]).rstrip("/") + ruta
    data = json.dumps(cuerpo).encode("utf-8") if cuerpo is not None else None
    cab = {"Content-Type": "application/json"}
    if not sin_clave:
        cab["X-Api-Key"] = c["api_key"]
    req = urllib.request.Request(url, data=data, method=metodo, headers=cab)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode("utf-8")).get("error")
        except Exception:
            msg = None
        if e.code == 404 and not msg:
            msg = "MetalERP no tiene la conexión para la app: reinicialo con INICIAR_SERVIDOR.bat para que tome la versión nueva"
        raise RuntimeError(msg or f"MetalERP respondió {e.code}")
    except (urllib.error.URLError, socket.timeout, ConnectionError) as e:
        raise RuntimeError(f"No se pudo conectar con MetalERP en {url.split('/api/')[0]}: ¿está abierto el servidor? ({getattr(e, 'reason', e)})")


def armar_paquetes(db):
    """Las piezas que todavía no están en un paquete pasan a uno nuevo."""
    while True:
        ids = [r["id"] for r in db.execute(
            "SELECT id FROM piezas WHERE paquete IS NULL ORDER BY id LIMIT ?", (MAX_PIEZAS_PAQUETE,)).fetchall()]
        if not ids:
            return
        u = str(uuid.uuid4())
        marcas = ",".join("?" * len(ids))
        db.execute(f"UPDATE piezas SET paquete=? WHERE id IN ({marcas})", [u] + ids)
        r = db.execute("SELECT MIN(hora) d, MAX(hora) h, COUNT(*) n FROM piezas WHERE paquete=?", (u,)).fetchone()
        db.execute("INSERT INTO paquetes (uuid, desde, hasta, piezas) VALUES (?,?,?,?)", (u, r["d"], r["h"], r["n"]))
        db.commit()


def enviar_pendientes(forzar=False):
    """Manda los paquetes por enviar (y los que fallaron, cuando toca)."""
    db = conectar()
    _estado["enviando"] = True
    try:
        armar_paquetes(db)
        filtro = "estado!='Enviado'" if forzar else "estado='Por enviar' OR (estado='Error' AND (proximo_intento IS NULL OR proximo_intento<=?))"
        args = () if forzar else (ahora(),)
        for k in db.execute(f"SELECT * FROM paquetes WHERE {filtro} ORDER BY creado, uuid", args).fetchall():
            piezas = [dict(r) for r in db.execute(
                "SELECT uuid, maquina, hora, ciclo_seg, contador FROM piezas WHERE paquete=? ORDER BY id", (k["uuid"],))]
            try:
                r = llamar_metalerp("POST", "/api/planta/v1/paquetes",
                                    {"uuid": k["uuid"], "desde": k["desde"], "hasta": k["hasta"], "piezas": piezas}, timeout=120)
                db.execute("""UPDATE paquetes SET estado='Enviado', enviado=?, respuesta=?, error=NULL,
                    intentos=intentos+1 WHERE uuid=?""", (ahora(), json.dumps(r, ensure_ascii=False)[:4000], k["uuid"]))
                db.commit()
                _estado.update(metalerp_ok=True, metalerp_error=None, metalerp_visto=ahora(), ultimo_envio=ahora())
            except Exception as e:
                prox = (datetime.now() + timedelta(minutes=REINTENTO_MIN)).strftime("%Y-%m-%d %H:%M:%S")
                db.execute("""UPDATE paquetes SET estado='Error', error=?, intentos=intentos+1, proximo_intento=?
                    WHERE uuid=?""", (str(e)[:500], prox, k["uuid"]))
                db.commit()
                _estado.update(metalerp_ok=False, metalerp_error=str(e))
                break           # si uno falla, los siguientes esperan (van en orden)
    finally:
        _estado["enviando"] = False
        db.close()


def proximo_envio(desde=None):
    """Próximo envío alineado al reloj: con 60 min, a cada hora en punto."""
    m = max(1, int(cfg().get("intervalo_min") or 60))
    d = desde or datetime.now()
    base = d.replace(hour=0, minute=0, second=0, microsecond=0)
    pasados = int((d - base).total_seconds() // 60)
    return base + timedelta(minutes=(pasados // m + 1) * m)


def hilo_envios():
    prox = proximo_envio()
    _estado["proximo_envio"] = prox.strftime("%Y-%m-%d %H:%M:%S")
    while True:
        forzado = _aviso_envio.wait(30)
        _aviso_envio.clear()
        try:
            if forzado or datetime.now() >= prox:
                enviar_pendientes(forzar=forzado)
                if datetime.now() >= prox:
                    prox = proximo_envio()
            else:
                # Reintentos de paquetes que fallaron (cada 5 min), sin esperar la hora.
                db = conectar()
                hay = db.execute("SELECT 1 FROM paquetes WHERE estado='Error' AND proximo_intento<=?", (ahora(),)).fetchone()
                db.close()
                if hay:
                    enviar_pendientes()
            _estado["proximo_envio"] = prox.strftime("%Y-%m-%d %H:%M:%S")
        except Exception as e:
            print(f"  [envíos] {e}")


def hilo_maquinas():
    """Lee de MetalERP las máquinas con su operación y operario, cada 30 s."""
    while True:
        try:
            if cfg().get("api_key"):
                _estado["maquinas"] = llamar_metalerp("GET", "/api/planta/v1/maquinas", timeout=20)
                _estado.update(metalerp_ok=True, metalerp_error=None, metalerp_visto=ahora())
        except Exception as e:
            _estado.update(metalerp_ok=False, metalerp_error=str(e))
        time.sleep(30)


# ── Lectores: la app le pregunta el contador a la máquina por red ─────────────
_lectores_estado = {}   # maquina -> {contador, origen, leido, error, control, piezas}


def leer_haas(ip, puerto, timeout=5):
    """Haas (Setting 143 activado): ?Q402 devuelve el contador M30 #1."""
    import re
    with socket.create_connection((ip, int(puerto or 5051)), timeout=timeout) as s:
        s.settimeout(timeout)
        s.sendall(b"?Q402\r\n")
        txt, fin = "", time.time() + timeout
        while time.time() < fin:
            try:
                parte = s.recv(256)
            except socket.timeout:
                break
            if not parte:
                break
            txt += parte.decode("ascii", "replace")
            m = re.search(r"M30[^,]*,\s*(-?\d+)", txt)
            if m:
                return {"contador": int(m.group(1)), "origen": "Q402", "sysinfo": None}
    raise RuntimeError("La Haas no devolvió el contador: " + (txt.strip() or "sin respuesta"))


def leer_lector(lec, timeout=5):
    tipo = lec.get("tipo")
    if tipo == "fanuc":
        import fanuc_focas
        try:
            return fanuc_focas.leer_piezas(lec["ip"], lec.get("puerto") or 8193, timeout)
        except fanuc_focas.ErrorFanuc as e:
            raise RuntimeError(str(e))
    if tipo == "haas":
        try:
            return leer_haas(lec["ip"], lec.get("puerto") or 5051, timeout)
        except OSError as e:
            raise RuntimeError(f"No se pudo conectar con {lec['ip']} ({e})")
    raise RuntimeError(f"Tipo de lector desconocido: {tipo}")


def _leer_y_registrar(lec):
    maq = str(lec["maquina"]).strip().upper()
    est = _lectores_estado.setdefault(maq, {"piezas": 0})
    try:
        r = leer_lector(lec)
    except Exception as e:
        est.update(error=str(e), intento=ahora())
        return
    hora = ahora()
    est.update(contador=r["contador"], origen=r.get("origen"), leido=hora, error=None, intento=hora,
               control=r.get("sysinfo") or est.get("control"))
    db = conectar()
    try:
        with _lock_contador:
            n = delta_contador(db, maq, int(r["contador"]), hora)
            mult = max(1, int(lec.get("multiplo") or 1))
            if n:
                registrar_piezas(db, maq, n * mult, hora, int(r["contador"]) if mult == 1 else None,
                                 origen=lec.get("tipo"))
                est["piezas"] = est.get("piezas", 0) + n * mult
            db.commit()
    finally:
        db.close()


def hilo_lectores():
    while True:
        for lec in cfg().get("lectores") or []:
            if lec.get("activo", True) and lec.get("ip") and lec.get("maquina"):
                try:
                    _leer_y_registrar(lec)
                except Exception as e:
                    print(f"  [lector {lec.get('maquina')}] {e}")
        time.sleep(LECTOR_SEG)


def _lectores_con_estado():
    res = []
    for lec in cfg().get("lectores") or []:
        res.append({**lec, "estado": _lectores_estado.get(str(lec.get("maquina", "")).upper())})
    return res


# ── Pantalla ─────────────────────────────────────────────────────────────────
_IPS_PROPIAS = set()


def es_local():
    """La configuración se cambia solo desde la PC donde corre la app (por
    localhost o por la IP de la propia PC)."""
    if not _IPS_PROPIAS:
        _IPS_PROPIAS.update({"127.0.0.1", "::1", "localhost", ip_local()})
        try:
            _IPS_PROPIAS.update(socket.gethostbyname_ex(socket.gethostname())[2])
        except OSError:
            pass
    return request.remote_addr in _IPS_PROPIAS


@app.route("/")
def inicio():
    return send_from_directory(PLANTILLAS, "monitor.html")


@app.route("/api/estado")
def api_estado():
    db = get_db()
    c = cfg()
    hoy = datetime.now().strftime("%Y-%m-%d")
    stats = {r["maquina"]: dict(r) for r in db.execute("""SELECT maquina,
            SUM(CASE WHEN substr(hora,1,10)=? THEN 1 ELSE 0 END) hoy,
            SUM(CASE WHEN paquete IS NULL THEN 1 ELSE 0 END) sin_paquete,
            MAX(hora) ultima,
            AVG(CASE WHEN hora>=? THEN ciclo_seg END) ciclo_prom
        FROM piezas WHERE hora>=? OR paquete IS NULL GROUP BY maquina""",
        (hoy, (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"), hoy)).fetchall()}
    sin_enviar = db.execute("""SELECT COUNT(*) FROM piezas p LEFT JOIN paquetes k ON k.uuid=p.paquete
        WHERE p.paquete IS NULL OR k.estado!='Enviado'""").fetchone()[0]
    maquinas = []
    vistos = set()
    for m in _estado["maquinas"] or []:
        s = stats.get(m["codigo"].upper(), {})
        vistos.add(m["codigo"].upper())
        maquinas.append({**m, "local": s})
    for cod, s in stats.items():   # señales de máquinas que MetalERP no conoce
        if cod not in vistos:
            maquinas.append({"codigo": cod, "nombre": "(no está en MetalERP)", "desconocida": True, "local": s})
    return jsonify({
        "hora": ahora(), "config": {k: c[k] for k in ("metalerp_url", "intervalo_min", "parada_seg", "puerto")},
        "tiene_clave": bool(c.get("api_key")), "es_local": es_local(),
        "metalerp_ok": _estado["metalerp_ok"], "metalerp_error": _estado["metalerp_error"],
        "metalerp_visto": _estado["metalerp_visto"], "ultimo_envio": _estado["ultimo_envio"],
        "proximo_envio": _estado["proximo_envio"], "enviando": _estado["enviando"],
        "sin_enviar": sin_enviar, "maquinas": maquinas, "lectores": _lectores_con_estado(),
    })


@app.route("/api/lectores", methods=["GET", "PUT"])
def api_lectores():
    if request.method == "GET":
        return jsonify({"lectores": _lectores_con_estado(), "es_local": es_local()})
    if not es_local():
        return jsonify({"error": "Los lectores solo se cambian desde la PC donde corre la app"}), 403
    d = request.get_json(silent=True) or {}
    lista, vistos = [], set()
    for x in d.get("lectores") or []:
        maq = str(x.get("maquina") or "").strip().upper()
        ip = str(x.get("ip") or "").strip()
        tipo = x.get("tipo") if x.get("tipo") in TIPOS_LECTOR else None
        if not maq and not ip:
            continue
        if not maq or not ip or not tipo:
            return jsonify({"error": "Cada lector necesita máquina, tipo e IP"}), 400
        if maq in vistos:
            return jsonify({"error": f"La máquina {maq} está dos veces"}), 400
        vistos.add(maq)
        try:
            puerto = int(x.get("puerto") or TIPOS_LECTOR[tipo])
            multiplo = max(1, min(100, int(x.get("multiplo") or 1)))
        except (TypeError, ValueError):
            return jsonify({"error": f"Puerto o piezas por ciclo inválidos en {maq}"}), 400
        lista.append({"maquina": maq, "tipo": tipo, "ip": ip, "puerto": puerto,
                      "multiplo": multiplo, "activo": bool(x.get("activo", True))})
    guardar_cfg({"lectores": lista})
    for k in list(_lectores_estado):
        if k not in vistos:
            _lectores_estado.pop(k, None)
    return jsonify({"ok": True, "lectores": _lectores_con_estado()})


@app.route("/api/lectores/probar", methods=["POST"])
def api_lectores_probar():
    """Lee una vez el contador, sin cargar piezas."""
    if not es_local():
        return jsonify({"ok": False, "error": "Probalo desde la PC donde corre la app"}), 403
    d = request.get_json(silent=True) or {}
    if d.get("tipo") not in TIPOS_LECTOR or not str(d.get("ip") or "").strip():
        return jsonify({"ok": False, "error": "Falta el tipo o la IP"})
    try:
        r = leer_lector({"tipo": d["tipo"], "ip": str(d["ip"]).strip(), "puerto": d.get("puerto")})
        return jsonify({"ok": True, **r})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


# ── Backup de programas del CNC ──────────────────────────────────────────────
# Baja todos los programas de la memoria del control a
# backups\<MÁQUINA>\<fecha_hora>\O0001.NC ... (uno por programa) + TODOS.NC + LISTA.txt
_backup_estado = {}     # maquina -> {en_curso, hechos, total, actual, inicio, fin, error, carpeta, programas}
_lock_backup = threading.Lock()


def _nombre_seguro(x):
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(x or ""))[:40] or "MAQ"


def _hacer_backup(lec):
    import fanuc_focas
    maq = str(lec["maquina"]).strip().upper()
    est = _backup_estado[maq]

    def avance(hechos, total, actual):
        est.update(hechos=hechos, total=total, actual=actual)

    try:
        programas, lista, errores, sysinfo = fanuc_focas.backup_programas(
            lec["ip"], lec.get("puerto") or 8193, avance)
        if not programas:
            raise RuntimeError("El control no devolvió ningún programa"
                               + (": " + "; ".join(errores[:3]) if errores else ""))
        sello = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        carpeta = os.path.join(BACKUP_DIR, _nombre_seguro(maq), sello)
        os.makedirs(carpeta, exist_ok=True)
        crlf = lambda t: t.replace("\r", "").replace("\n", "\r\n")
        nom = lambda n: ("O%04d" % n) if n < 10000 else ("O%08d" % n)
        for n, txt in programas.items():
            with open(os.path.join(carpeta, nom(n) + ".NC"), "w", encoding="latin-1", newline="") as f:
                f.write(crlf("%\n" + txt + "%\n"))
        with open(os.path.join(carpeta, "TODOS.NC"), "w", encoding="latin-1", newline="") as f:
            f.write(crlf("%\n" + "".join(programas[n] for n in sorted(programas)) + "%\n"))
        lineas = [f"Backup de programas de {maq} ({lec['ip']})", f"Fecha: {ahora()}"]
        if sysinfo:
            lineas.append("Control: " + " ".join(str(sysinfo.get(k) or "") for k in ("cnc", "tipo", "serie", "version")).strip())
        lineas += [f"Programas: {len(programas)}", "", "Programa   Tamaño   Comentario"]
        for n in sorted(programas):
            info = lista.get(n) or {}
            lineas.append(f"{nom(n):<10} {len(programas[n].encode('latin-1', 'replace')):>7}   {info.get('comentario', '')}")
        if errores:
            lineas += ["", "No se pudieron bajar:"] + errores
        with open(os.path.join(carpeta, "LISTA.txt"), "w", encoding="utf-8-sig", newline="") as f:
            f.write("\r\n".join(lineas) + "\r\n")
        est.update(carpeta=os.path.relpath(carpeta, BACKUP_DIR), programas=len(programas),
                   errores=errores, error=None)
    except Exception as e:
        est.update(error=str(e))
    finally:
        est.update(en_curso=False, fin=ahora(), actual=None)


def _lista_backups(maq):
    base = os.path.join(BACKUP_DIR, _nombre_seguro(maq))
    res = []
    try:
        nombres = sorted(os.listdir(base), reverse=True)
    except OSError:
        return res
    for nombre in nombres[:30]:
        ruta = os.path.join(base, nombre)
        if not os.path.isdir(ruta):
            continue
        archivos = [a for a in os.listdir(ruta) if a.upper().endswith(".NC") and a.upper() != "TODOS.NC"]
        tam = sum(os.path.getsize(os.path.join(ruta, a)) for a in os.listdir(ruta))
        res.append({"carpeta": _nombre_seguro(maq) + "/" + nombre, "fecha": re.sub(r"^(\d{4}-\d\d-\d\d)_(\d\d)(\d\d)(\d\d)$", r"\1 \2:\3:\4", nombre),
                    "programas": len(archivos), "tam": tam})
    return res


def _ruta_backup(rel):
    """Carpeta de un backup, sin salirse de la carpeta backups."""
    ruta = os.path.realpath(os.path.join(BACKUP_DIR, str(rel or "")))
    base = os.path.realpath(BACKUP_DIR)
    if not ruta.startswith(base + os.sep) or not os.path.isdir(ruta):
        return None
    return ruta


@app.route("/api/backup", methods=["GET", "POST"])
def api_backup():
    lectores = [l for l in cfg().get("lectores") or [] if l.get("tipo") == "fanuc" and l.get("ip")]
    if request.method == "GET":
        return jsonify({"es_local": es_local(), "carpeta": BACKUP_DIR, "maquinas": [
            {"maquina": l["maquina"], "ip": l["ip"], "puerto": l.get("puerto"),
             "estado": _backup_estado.get(str(l["maquina"]).upper()),
             "backups": _lista_backups(l["maquina"])} for l in lectores]})
    d = request.get_json(silent=True) or {}
    maq = str(d.get("maquina") or "").strip().upper()
    lec = next((l for l in lectores if str(l["maquina"]).upper() == maq), None)
    if not lec:
        return jsonify({"error": f"La máquina {maq} no tiene lector Fanuc cargado"}), 400
    with _lock_backup:
        if (_backup_estado.get(maq) or {}).get("en_curso"):
            return jsonify({"error": f"Ya se está haciendo el backup de {maq}"}), 409
        _backup_estado[maq] = {"en_curso": True, "hechos": 0, "total": 0, "actual": None,
                               "inicio": ahora(), "fin": None, "error": None}
    threading.Thread(target=_hacer_backup, args=(lec,), name="backup-" + maq, daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/backup/zip")
def api_backup_zip():
    ruta = _ruta_backup(request.args.get("carpeta"))
    if not ruta:
        return jsonify({"error": "No existe ese backup"}), 404
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, "w", zipfile.ZIP_DEFLATED) as z:
        for a in sorted(os.listdir(ruta)):
            z.write(os.path.join(ruta, a), a)
    mem.seek(0)
    nombre = "backup_" + os.path.relpath(ruta, BACKUP_DIR).replace(os.sep, "_") + ".zip"
    return send_file(mem, mimetype="application/zip", as_attachment=True, download_name=nombre)


@app.route("/api/backup/abrir", methods=["POST"])
def api_backup_abrir():
    """Abre la carpeta del backup en el Explorador (solo en la PC de la app)."""
    if not es_local():
        return jsonify({"error": "La carpeta se abre solo en la PC donde corre la app"}), 403
    rel = (request.get_json(silent=True) or {}).get("carpeta")
    ruta = _ruta_backup(rel) if rel else BACKUP_DIR
    if not ruta:
        return jsonify({"error": "No existe ese backup"}), 404
    os.makedirs(ruta, exist_ok=True)
    try:
        os.startfile(ruta)
    except (AttributeError, OSError) as e:
        return jsonify({"error": f"No se pudo abrir la carpeta: {e}", "ruta": ruta}), 500
    return jsonify({"ok": True, "ruta": ruta})


# ── Envío de programas a la máquina (PC -> CNC) ───────────────────────────────
# Escribe en el control con la librería oficial de Fanuc (fanuc_envio.py).
# Resguardos: solo desde la PC de la app; el control rechaza un número que ya
# existe; reemplazar pide confirmación, no toca el programa en ejecución o
# principal, guarda antes una copia del actual y lo restaura si el envío falla;
# después de mandar, se vuelve a leer y se compara. Todo queda en la tabla envios.
_lock_envio = threading.Lock()


def _db_envios(db):
    db.execute("""CREATE TABLE IF NOT EXISTS envios (id INTEGER PRIMARY KEY AUTOINCREMENT,
        hora TEXT, maquina TEXT, programa INTEGER, archivo TEXT, bytes INTEGER, reemplazo INTEGER,
        copia TEXT, resultado TEXT, verificado INTEGER, detalle TEXT, desde TEXT)""")


def _lectores_fanuc():
    return [l for l in cfg().get("lectores") or [] if l.get("tipo") == "fanuc" and l.get("ip")]


@app.route("/api/envio", methods=["GET", "POST"])
def api_envio():
    import fanuc_envio
    db = get_db()
    _db_envios(db)
    if request.method == "GET":
        filas = db.execute("SELECT * FROM envios ORDER BY id DESC LIMIT 50").fetchall()
        return jsonify({"es_local": es_local(), "libreria": fanuc_envio.disponible(cfg().get("fwlib_dir")),
                        "maquinas": [{"maquina": l["maquina"], "ip": l["ip"], "puerto": l.get("puerto")}
                                     for l in _lectores_fanuc()],
                        "historial": [dict(r) for r in filas]})
    if not es_local():
        return jsonify({"error": "Los programas se mandan solo desde la PC donde corre la app"}), 403
    d = request.get_json(silent=True) or {}
    maq = str(d.get("maquina") or "").strip().upper()
    lec = next((l for l in _lectores_fanuc() if str(l["maquina"]).upper() == maq), None)
    if not lec:
        return jsonify({"error": f"La máquina {maq} no tiene lector Fanuc cargado"}), 400
    try:
        numero = int(d.get("numero"))
        if not 1 <= numero <= 99999999:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"error": "Número de programa inválido"}), 400
    archivo = str(d.get("archivo") or "")[:120]
    reemplazar = bool(d.get("reemplazar"))
    ip, puerto, fwdir = lec["ip"], lec.get("puerto") or 8193, cfg().get("fwlib_dir")
    nom = ("O%04d" % numero) if numero < 10000 else ("O%08d" % numero)
    if not _lock_envio.acquire(blocking=False):
        return jsonify({"error": "Ya se está mandando otro programa"}), 409
    reg = {"hora": ahora(), "maquina": maq, "programa": numero, "archivo": archivo, "bytes": 0,
           "reemplazo": 0, "copia": None, "resultado": "Error", "verificado": None, "detalle": None,
           "desde": request.remote_addr}
    try:
        import fanuc_focas
        datos = fanuc_envio.preparar(str(d.get("texto") or ""), numero)
        reg["bytes"] = len(datos)
        fanuc_envio.cargar(fwdir)
        with fanuc_focas.Fanuc(ip, puerto, timeout=10) as f:
            lista = f.listar_programas()
        viejo = None
        if numero in lista:
            if not reemplazar:
                return jsonify({"existe": True, "programa": nom,
                                "comentario": (lista[numero] or {}).get("comentario", "")}), 409
            run, main = fanuc_envio.programa_activo(ip, puerto, fwdir)
            if numero in (run, main):
                raise RuntimeError(f"{nom} es el programa seleccionado o en ejecución en {maq}: "
                                   "no se reemplaza. Seleccioná otro programa en la máquina o mandalo con otro número.")
            with fanuc_focas.Fanuc(ip, puerto, timeout=10) as f:
                viejo = f.bajar(numero)
            if not fanuc_envio.normalizar(viejo):
                raise RuntimeError(f"No se pudo leer el {nom} actual para guardar la copia: no se reemplaza")
            carpeta = os.path.join(BACKUP_DIR, _nombre_seguro(maq), "reemplazados")
            os.makedirs(carpeta, exist_ok=True)
            copia = os.path.join(carpeta, f"{nom}_{datetime.now():%Y-%m-%d_%H%M%S}.NC")
            with open(copia, "w", encoding="latin-1", newline="") as fh:
                fh.write(viejo.replace("\r", "").replace("\n", "\r\n"))
            reg.update(reemplazo=1, copia=os.path.relpath(copia, BACKUP_DIR))
            fanuc_envio.borrar(ip, puerto, numero, fwdir)
        try:
            fanuc_envio.enviar(ip, puerto, datos, fwdir)
        except Exception as e:
            if viejo is not None:
                try:
                    fanuc_envio.enviar(ip, puerto, fanuc_envio.preparar(viejo, numero), fwdir)
                    raise RuntimeError(f"{e}. Se volvió a cargar el {nom} anterior.")
                except fanuc_envio.ErrorEnvio as e2:
                    raise RuntimeError(f"{e}. ATENCIÓN: no se pudo volver a cargar el {nom} anterior ({e2}); "
                                       f"está guardado en backups\\{reg['copia']}")
            raise
        # Verificación: se vuelve a leer lo que quedó en el control
        try:
            with fanuc_focas.Fanuc(ip, puerto, timeout=10) as f:
                quedo = f.bajar(numero)
            reg["verificado"] = 1 if fanuc_envio.normalizar(quedo) == fanuc_envio.normalizar(datos) else 0
        except Exception as e:
            reg["detalle"] = f"Mandado, pero no se pudo verificar: {e}"
        reg["resultado"] = "Enviado"
        if reg["verificado"] == 0:
            reg["detalle"] = "Mandado, pero lo que quedó en el control no es igual al archivo: revisalo en la máquina"
        return jsonify({"ok": True, **reg})
    except Exception as e:
        reg["detalle"] = str(e)
        return jsonify({"ok": False, "error": str(e), **reg}), 400
    finally:
        _lock_envio.release()
        if reg["resultado"] == "Enviado" or reg["detalle"]:
            try:
                db.execute("""INSERT INTO envios (hora,maquina,programa,archivo,bytes,reemplazo,copia,resultado,
                    verificado,detalle,desde) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    tuple(reg[k] for k in ("hora", "maquina", "programa", "archivo", "bytes", "reemplazo", "copia",
                                           "resultado", "verificado", "detalle", "desde")))
                db.commit()
            except Exception as e:
                print("  [envio] no se pudo registrar:", e)


@app.route("/api/paquetes")
def api_paquetes():
    filas = get_db().execute("SELECT * FROM paquetes ORDER BY creado DESC LIMIT 100").fetchall()
    res = []
    for r in filas:
        x = dict(r)
        try:
            x["respuesta"] = json.loads(r["respuesta"]) if r["respuesta"] else None
        except ValueError:
            pass
        res.append(x)
    return jsonify(res)


@app.route("/api/piezas")
def api_piezas():
    w, p = ["1=1"], []
    if request.args.get("maquina"):
        w.append("maquina=?"); p.append(request.args["maquina"].upper())
    filas = get_db().execute(f"""SELECT p.*, k.estado paquete_estado FROM piezas p
        LEFT JOIN paquetes k ON k.uuid=p.paquete WHERE {' AND '.join(w)} ORDER BY p.id DESC LIMIT 300""", p).fetchall()
    return jsonify([dict(r) for r in filas])


@app.route("/api/enviar_ahora", methods=["POST"])
def api_enviar_ahora():
    _aviso_envio.set()
    return jsonify({"ok": True})


@app.route("/api/config", methods=["GET", "PUT"])
def api_config():
    if request.method == "GET":
        c = cfg()
        return jsonify({**{k: v for k, v in c.items() if k != "api_key"},
                        "api_key_fin": (c.get("api_key") or "")[-4:], "es_local": es_local()})
    if not es_local():
        return jsonify({"error": "La configuración solo se cambia desde la PC donde corre la app"}), 403
    d = request.get_json(silent=True) or {}
    nuevo = {}
    if "metalerp_url" in d:
        u = str(d["metalerp_url"]).strip().rstrip("/")
        if not u.startswith(("http://", "https://")):
            return jsonify({"error": "La dirección tiene que empezar con http://"}), 400
        nuevo["metalerp_url"] = u
    if d.get("api_key"):
        nuevo["api_key"] = str(d["api_key"]).strip()
    for k, lo, hi in (("intervalo_min", 1, 1440), ("parada_seg", 30, 7200)):
        if k in d:
            try:
                nuevo[k] = max(lo, min(hi, int(d[k])))
            except (TypeError, ValueError):
                return jsonify({"error": f"{k} inválido"}), 400
    if "senal_token" in d:
        nuevo["senal_token"] = str(d["senal_token"] or "").strip()
    guardar_cfg(nuevo)
    _estado["proximo_envio"] = proximo_envio().strftime("%Y-%m-%d %H:%M:%S")
    return jsonify({"ok": True})


@app.route("/api/vincular", methods=["POST"])
def api_vincular():
    """Conecta la app con MetalERP con un usuario administrador: MetalERP da
    una clave nueva y queda guardada acá. No hace falta copiar nada."""
    if not es_local():
        return jsonify({"ok": False, "error": "Conectá la app desde la PC donde está instalada"}), 403
    d = request.get_json(silent=True) or {}
    url = str(d.get("metalerp_url") or cfg()["metalerp_url"]).strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    try:
        r = llamar_metalerp("POST", "/api/planta/v1/vincular",
                            {"username": d.get("username"), "password": d.get("password"), "nombre": "Monitor de planta"},
                            timeout=15, url_base=url, sin_clave=True)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})
    guardar_cfg({"metalerp_url": url, "api_key": r["clave"]})
    try:
        _estado["maquinas"] = llamar_metalerp("GET", "/api/planta/v1/maquinas", timeout=20)
        _estado.update(metalerp_ok=True, metalerp_error=None, metalerp_visto=ahora())
    except Exception:
        pass
    return jsonify({"ok": True, "app": r.get("nombre")})


@app.route("/api/probar", methods=["POST"])
def api_probar():
    try:
        r = llamar_metalerp("GET", "/api/planta/v1/estado", timeout=10)
        _estado.update(metalerp_ok=True, metalerp_error=None, metalerp_visto=ahora())
        try:
            _estado["maquinas"] = llamar_metalerp("GET", "/api/planta/v1/maquinas", timeout=20)
        except Exception:
            pass
        return jsonify({"ok": True, "app": r.get("app")})
    except Exception as e:
        _estado.update(metalerp_ok=False, metalerp_error=str(e))
        return jsonify({"ok": False, "error": str(e)})


def ip_local():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


def arrancar_servidor():
    """Base, hilos de envío y servidor web (se queda corriendo)."""
    init_db()
    c = cfg()
    if not os.path.exists(CONFIG_PATH):
        guardar_cfg({})
    threading.Thread(target=hilo_envios, name="envios", daemon=True).start()
    threading.Thread(target=hilo_maquinas, name="maquinas", daemon=True).start()
    threading.Thread(target=hilo_lectores, name="lectores", daemon=True).start()
    puerto = int(c.get("puerto") or 5100)
    print("=" * 52 + "\n   Monitor de planta (conectado a MetalERP)\n" + "=" * 52)
    print(f"\n   Pantalla:  http://localhost:{puerto}")
    print(f"   En la red: http://{ip_local()}:{puerto}")
    print(f"   Señal del router: http://{ip_local()}:{puerto}/senal?maquina=T16")
    print(f"   MetalERP:  {c['metalerp_url']}  (paquete cada {c['intervalo_min']} min)\n")
    app.run(host="0.0.0.0", port=puerto, debug=False, threaded=True)


if __name__ == "__main__":
    arrancar_servidor()

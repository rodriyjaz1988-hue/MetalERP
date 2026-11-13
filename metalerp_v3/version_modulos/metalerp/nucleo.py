"""MetalERP v3.0 - Sistema ERP Taller Metalurgico

Núcleo: app Flask, conexión a la base con auditoría, consultas, numeración,
sesión, roles, permisos y filtro de valores monetarios."""
import os, re, socket, sqlite3, hashlib, secrets, math, threading
import json as _json

# --- Parche compatibilidad Windows Server viejo / OpenSSL sin 'usedforsecurity' ---
# reportlab moderno llama hashlib.md5(usedforsecurity=False), pero el build de
# OpenSSL de este Python no soporta ese kwarg. Lo interceptamos y lo descartamos.
_orig_md5 = hashlib.md5
def _md5_compat(*args, **kwargs):
    kwargs.pop('usedforsecurity', None)
    return _orig_md5(*args)
hashlib.md5 = _md5_compat
# --- Fin parche ---

from datetime import datetime, date, timedelta
from functools import wraps
from flask import (Flask, render_template, request, jsonify, session, redirect, g,
                   send_from_directory, has_request_context)

# ── Permisos predeterminados por rol ──────────────────────────────────────────
DEFAULT_PERMISIONES = {
    'operario': {
        'ver_ordenes_trabajo': '1',
        'ver_procesos_productos': '1',
        'ver_control_produccion': '1',
        'ver_novedades_por_ot': '1',
    },
    'logistica': {
        'mod_mrp': '1',
        'mod_inventario': '1',
        'mod_movimientos': '1',
        'mod_lotes': '1',
        'mod_remitir': '1',
        'mod_remitos_emitidos': '1',
        'mod_clientes': '1',
        'mod_oc_clientes': '1',
        'mod_proveedores': '1',
        'ver_monetario': '0',
    }
}

# Carpeta de la instalación (la que tiene server.py, templates/ y database/);
# este archivo vive un nivel más abajo, en metalerp/.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH  = os.path.join(BASE_DIR, "database", "metalerp.db")
app = Flask(__name__, root_path=BASE_DIR, template_folder="templates", static_folder="static")
app.secret_key = secrets.token_hex(32)
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# ── Bitácora de auditoría ─────────────────────────────────────────────────────
# Toda alta/modificación/baja de datos queda registrada en la tabla `auditoria`
# SIN tocar los controladores: se intercepta en la capa de conexión. Por acá
# pasan tanto los helpers query()/execute() como los db.execute(...) sueltos
# que hay repartidos por el archivo, así que no hay forma de escribir en la
# base sin dejar rastro.
#
# Reglas:
#   · El registro nunca puede voltear la operación principal: todo el trabajo
#     de auditoría va envuelto en try/except y, si falla, solo se avisa por
#     consola (SQLite hace rollback a nivel sentencia, no de transacción).
#   · Origen "usuario" cuando hay sesión HTTP; "sistema" para procesos
#     automáticos (arranque, backfills, cálculos) o cuando un bloque se marca
#     explícitamente con auditoria_proceso("nombre").
#   · Nunca se guardan contraseñas ni columnas de marca de tiempo técnica.

AUDITORIA_TABLAS_EXCLUIDAS = {"auditoria", "cotizaciones_dolar", "ia_conversaciones", "ia_mensajes",
                              # HMI de prueba: un registro por pieza; la novedad final sí se audita.
                              "hmi_sesiones", "hmi_eventos",
                              # Tablets de planta: la bandeja es una cola; la novedad que genera sí se audita.
                              "planta_bandeja", "planta_huellas"}
# Nombres exactos que nunca se guardan.
AUDITORIA_COLUMNAS_EXCLUIDAS = {"password", "passwd", "pwd", "clave", "updated_at", "modificado_en"}
# Fragmentos: cualquier columna que los contenga tampoco se guarda.
AUDITORIA_COLUMNAS_FRAGMENTOS = ("password", "contrasena", "contraseña", "updated_at", "token", "secret")
# Tope de filas inspeccionadas por sentencia (un UPDATE masivo no debe hacer
# que la auditoría cueste más que la operación en sí).
AUDITORIA_MAX_FILAS = 500
# Los valores muy largos (ej. imágenes en base64 en `configuracion`) se cortan.
AUDITORIA_MAX_LARGO_VALOR = 2000

_aud_local = threading.local()


def _aud_estado(nombre, default=None):
    return getattr(_aud_local, nombre, default)


def _aud_aviso(e):
    try:
        print(f"[auditoria] No se pudo registrar el cambio: {e}")
    except Exception:
        pass


class auditoria_proceso:
    """Marca un bloque como cambio hecho por el sistema y no por el usuario.

    Sirve tanto de context manager como de decorador:

        with auditoria_proceso("MRP"):
            ...
        @auditoria_proceso("backfill requerimientos")
        def _backfill(): ...

    Es el único punto de extensión pensado para el resto del código: todo lo
    demás se audita solo.
    """

    def __init__(self, nombre):
        self.nombre = nombre

    def __enter__(self):
        self._previo = _aud_estado("proceso")
        _aud_local.proceso = self.nombre
        return self

    def __exit__(self, *exc):
        _aud_local.proceso = self._previo
        return False

    def __call__(self, f):
        @wraps(f)
        def _envuelto(*a, **kw):
            with auditoria_proceso(self.nombre):
                return f(*a, **kw)
        return _envuelto


def _aud_identidad():
    """(origen, usuario_id, actor) de quien está haciendo el cambio."""
    proceso = _aud_estado("proceso")
    if proceso:
        return "sistema", None, proceso
    try:
        if has_request_context():
            if session.get("user_id"):
                nombre = session.get("nombre") or session.get("username") or f"usuario #{session['user_id']}"
                return "usuario", session["user_id"], nombre
            return "sistema", None, "solicitud sin sesión"
    except Exception:
        pass
    return "sistema", None, "proceso interno"


def _aud_ruta():
    try:
        if has_request_context():
            return f"{request.method} {request.path}"
    except Exception:
        pass
    return None


# ── Lectura del SQL ───────────────────────────────────────────────────────────
_AUD_DML = re.compile(r"^\s*(INSERT|REPLACE|UPDATE|DELETE)\b", re.I)
_AUD_TABLA = re.compile(
    r"^\s*(?:INSERT(?:\s+OR\s+[A-Za-z]+)?\s+INTO"
    r"|REPLACE(?:\s+INTO)?"
    r"|UPDATE(?:\s+OR\s+[A-Za-z]+)?"
    r"|DELETE\s+FROM)\s+[\"'`\[]?([A-Za-z_][A-Za-z0-9_]*)", re.I)


def _aud_mascara(sql):
    """Copia del SQL con literales y comentarios pisados por espacios, más la
    profundidad de paréntesis de cada carácter (misma longitud que `sql`).

    Hace falta para encontrar el WHERE *de la sentencia* y no el de una
    subconsulta, y para contar los '?' que corresponden al SET.
    """
    out, prof = [], []
    nivel, estado, cierre, i, n = 0, None, "", 0, len(sql)
    while i < n:
        c = sql[i]
        if estado is None:
            if c in "'\"`[":
                estado, cierre = "lit", ("]" if c == "[" else c)
                out.append(" "); prof.append(nivel)
            elif c == "-" and i + 1 < n and sql[i + 1] == "-":
                estado = "lin"; out.append(" "); prof.append(nivel)
            elif c == "/" and i + 1 < n and sql[i + 1] == "*":
                estado = "blk"; out.append(" "); prof.append(nivel)
            elif c == "(":
                nivel += 1; out.append(c); prof.append(nivel)
            elif c == ")":
                out.append(c); prof.append(nivel); nivel -= 1
            else:
                out.append(c); prof.append(nivel)
        elif estado == "lit":
            out.append(" "); prof.append(nivel)
            if c == cierre:
                if c != "]" and i + 1 < n and sql[i + 1] == c:
                    i += 1; out.append(" "); prof.append(nivel)   # '' = comilla escapada
                else:
                    estado = None
        elif estado == "lin":
            out.append("\n" if c == "\n" else " "); prof.append(nivel)
            if c == "\n":
                estado = None
        else:  # blk
            out.append(" "); prof.append(nivel)
            if c == "/" and i > 0 and sql[i - 1] == "*":
                estado = None
        i += 1
    return "".join(out), prof


def _aud_partes(sql, params):
    """(verbo, tabla, where_sql, params_del_where) o (None, ...) si no aplica."""
    m = _AUD_TABLA.match(sql)
    if not m:
        return None, None, None, None
    verbo = re.match(r"^\s*([A-Za-z]+)", sql).group(1).upper()
    tabla = m.group(1)
    if verbo in ("INSERT", "REPLACE"):
        return verbo, tabla, None, ()
    if isinstance(params, dict):
        return None, None, None, None          # parámetros nombrados: no se usan acá
    seq = tuple(params or ())
    mascara, prof = _aud_mascara(sql)
    pos = -1
    for w in re.finditer(r"\bWHERE\b", mascara, re.I):
        if prof[w.start()] == 0:
            pos = w.start()
    if pos < 0:
        return verbo, tabla, "", ()            # sin WHERE: afecta a toda la tabla
    where_sql = sql[pos:]
    fin = re.search(r"\bRETURNING\b", mascara[pos:], re.I)
    if fin:
        where_sql = where_sql[:fin.start()]
    return verbo, tabla, where_sql, seq[mascara.count("?", 0, pos):]


# ── Metadatos de las tablas (se leen una vez por proceso) ─────────────────────
_aud_meta = {}


def _aud_tabla_meta(conn, tabla):
    meta = _aud_meta.get(tabla)
    if meta is None:
        cols, pks = [], []
        for c in conn._crudo(f'PRAGMA table_info("{tabla}")').fetchall():
            nombre = c[1]
            cols.append(nombre)
            if c[5]:
                pks.append(nombre)
        excluidas = {c for c in cols
                     if c.lower() in AUDITORIA_COLUMNAS_EXCLUIDAS
                     or any(f in c.lower() for f in AUDITORIA_COLUMNAS_FRAGMENTOS)}
        meta = {"cols": cols, "pk": pks[0] if len(pks) == 1 else None, "excluidas": excluidas}
        _aud_meta[tabla] = meta
    return meta


def _aud_valor(v):
    if isinstance(v, (bytes, bytearray)):
        return f"<binario, {len(v)} bytes>"
    if isinstance(v, str) and len(v) > AUDITORIA_MAX_LARGO_VALOR:
        return v[:AUDITORIA_MAX_LARGO_VALOR] + f"… (+{len(v) - AUDITORIA_MAX_LARGO_VALOR} caracteres)"
    return v


def _aud_fila(fila, excluidas):
    return {k: _aud_valor(fila[k]) for k in fila.keys()
            if k != "_aud_rowid" and k not in excluidas}


def _aud_enmascarar(d):
    """Reemplaza los importes por un marcador. La bitácora sigue mostrando QUÉ
    campo cambió, pero no el valor, para quien no puede ver importes."""
    if not d:
        return d
    return {k: ("\u2014 (oculto)" if k in CAMPOS_MONETARIOS else v) for k, v in d.items()}


def _aud_leer(conn, tabla, where_sql, where_params, meta):
    """Filas afectadas, con su rowid, antes de ejecutar la sentencia."""
    try:
        cur = conn._crudo(f'SELECT rowid AS _aud_rowid, * FROM "{tabla}" {where_sql or ""}', where_params)
    except sqlite3.Error:
        cur = conn._crudo(f'SELECT * FROM "{tabla}" {where_sql or ""}', where_params)
    cur.row_factory = sqlite3.Row
    filas = cur.fetchmany(AUDITORIA_MAX_FILAS + 1)
    truncado = len(filas) > AUDITORIA_MAX_FILAS
    out = []
    for f in filas[:AUDITORIA_MAX_FILAS]:
        claves = f.keys()
        out.append({
            "rowid": f["_aud_rowid"] if "_aud_rowid" in claves else None,
            "id": f[meta["pk"]] if meta["pk"] and meta["pk"] in claves else (
                f["_aud_rowid"] if "_aud_rowid" in claves else None),
            "datos": _aud_fila(f, meta["excluidas"]),
        })
    return out, truncado


def _aud_releer(conn, tabla, rowid, meta):
    if rowid is None:
        return None
    try:
        cur = conn._crudo(f'SELECT * FROM "{tabla}" WHERE rowid=?', (rowid,))
        cur.row_factory = sqlite3.Row
        f = cur.fetchone()
    except sqlite3.Error:
        return None
    return _aud_fila(f, meta["excluidas"]) if f else None


def _aud_json(d):
    if d is None:
        return None
    return _json.dumps(d, ensure_ascii=False, default=str)


def _aud_registrar(conn, tabla, accion, registro_id, antes, despues):
    origen, uid, actor = _aud_identidad()
    conn._crudo(
        "INSERT INTO auditoria (fecha,origen,usuario_id,actor,entidad,registro_id,accion,ruta,valores_antes,valores_despues)"
        " VALUES (datetime('now','localtime'),?,?,?,?,?,?,?,?,?)",
        (origen, uid, actor, tabla, None if registro_id is None else str(registro_id),
         accion, _aud_ruta(), _aud_json(antes), _aud_json(despues)))


def _aud_antes(conn, sql, params):
    verbo, tabla, where_sql, where_params = _aud_partes(sql, params)
    if not tabla or tabla.lower() in AUDITORIA_TABLAS_EXCLUIDAS:
        return None
    meta = _aud_tabla_meta(conn, tabla)
    if not meta["cols"]:
        return None                                   # vista o tabla inexistente
    ctx = {"verbo": verbo, "tabla": tabla, "meta": meta, "filas": [], "truncado": False}
    if verbo not in ("INSERT", "REPLACE"):
        if where_sql is None:
            return None
        ctx["filas"], ctx["truncado"] = _aud_leer(conn, tabla, where_sql, where_params, meta)
    return ctx


def _aud_despues(conn, cur, ctx):
    if not ctx:
        return
    tabla, meta, verbo = ctx["tabla"], ctx["meta"], ctx["verbo"]
    if verbo in ("INSERT", "REPLACE"):
        nueva = _aud_releer(conn, tabla, cur.lastrowid, meta)
        if nueva is None:
            return
        if (cur.rowcount or 1) > 1:
            nueva = dict(nueva, _filas_insertadas=cur.rowcount)
        rid = nueva.get(meta["pk"]) if meta["pk"] else cur.lastrowid
        _aud_registrar(conn, tabla, "alta", rid, None, nueva)
        return
    if verbo == "UPDATE":
        for f in ctx["filas"]:
            despues = _aud_releer(conn, tabla, f["rowid"], meta)
            antes = f["datos"]
            if despues is None:
                continue
            # Solo los campos que efectivamente cambiaron.
            dif_a, dif_d = {}, {}
            for k in set(antes) | set(despues):
                if antes.get(k) != despues.get(k):
                    dif_a[k] = antes.get(k)
                    dif_d[k] = despues.get(k)
            if not dif_d:
                continue                               # UPDATE que no cambió nada
            _aud_registrar(conn, tabla, "modificacion", f["id"], dif_a, dif_d)
        return
    for f in ctx["filas"]:                             # DELETE
        _aud_registrar(conn, tabla, "baja", f["id"], f["datos"], None)


class _AuditConnection(sqlite3.Connection):
    """Conexión que deja registrada toda escritura en la tabla `auditoria`."""

    def _crudo(self, sql, params=()):
        """Ejecuta sin auditar (uso interno de la auditoría)."""
        return sqlite3.Connection.execute(self, sql, params)

    def execute(self, sql, parameters=()):
        if _aud_estado("dentro") or not isinstance(sql, str) or not _AUD_DML.match(sql):
            return sqlite3.Connection.execute(self, sql, parameters)
        ctx = None
        _aud_local.dentro = True
        try:
            ctx = _aud_antes(self, sql, parameters)
        except Exception as e:
            _aud_aviso(e)
        finally:
            _aud_local.dentro = False
        cur = sqlite3.Connection.execute(self, sql, parameters)
        _aud_local.dentro = True
        try:
            _aud_despues(self, cur, ctx)
        except Exception as e:
            _aud_aviso(e)
        finally:
            _aud_local.dentro = False
        return cur

    def executemany(self, sql, seq_of_parameters):
        if _aud_estado("dentro") or not isinstance(sql, str) or not _AUD_DML.match(sql):
            return sqlite3.Connection.executemany(self, sql, seq_of_parameters)
        filas = list(seq_of_parameters)
        # Lote chico: se ejecuta fila por fila para que cada una quede
        # auditada con su valor real. Lote grande: se prioriza la velocidad
        # de la operación y se deja un único asiento con el resumen.
        if len(filas) <= 200:
            cur = None
            for p in filas:
                cur = self.execute(sql, p)
            return cur if cur is not None else sqlite3.Connection.execute(self, "SELECT 1")
        cur = sqlite3.Connection.executemany(self, sql, filas)
        _aud_local.dentro = True
        try:
            tabla = (_AUD_TABLA.match(sql) or [None, None])[1]
            if tabla and tabla.lower() not in AUDITORIA_TABLAS_EXCLUIDAS:
                _aud_registrar(self, tabla, "alta", None, None, {"_filas_afectadas": len(filas)})
        except Exception as e:
            _aud_aviso(e)
        finally:
            _aud_local.dentro = False
        return cur


def get_db():
    if "db" not in g:
        # timeout=30 -> si la DB esta bloqueada por otra conexion (varios
        # operarios en simultaneo), espera hasta 30s en vez de fallar al toque
        g.db = sqlite3.connect(DB_PATH, timeout=30, factory=_AuditConnection)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        # WAL permite que lecturas y escrituras convivan sin bloquearse entre si,
        # clave cuando hay varias cuentas conectadas por la misma red local
        g.db.execute("PRAGMA journal_mode = WAL")
        g.db.execute("PRAGMA busy_timeout = 30000")
        g.db.create_function("cant_material", 3, cant_material, deterministic=True)
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop("db", None)
    if db: db.close()

def query(sql, params=(), one=False):
    cur = get_db().execute(sql, params)
    rows = cur.fetchall()
    return (rows[0] if rows else None) if one else rows

def execute(sql, params=()):
    db = get_db()
    cur = db.execute(sql, params)
    # Dentro de un bloque `with transaccion():` se confirma todo junto al final.
    if not g.get("_transaccion"):
        db.commit()
    return cur.lastrowid


class transaccion:
    """Agrupa varias escrituras en una sola transacción: dentro del bloque,
    execute() no confirma cada sentencia; al salir se confirma todo junto y,
    si algo falla, se deshace todo (no quedan OT a medias ni renglones sin
    vincular). Toma el lock de escritura de entrada (BEGIN IMMEDIATE), así
    los números que se sacan adentro con siguiente_numero() no se pueden
    repetir con otra conexión. Un bloque dentro de otro se suma al de afuera."""

    def __enter__(self):
        self._externa = bool(g.get("_transaccion"))
        if not self._externa:
            db = get_db()
            if db.in_transaction:
                db.commit()
            db.execute("BEGIN IMMEDIATE")
            g._transaccion = True
        return self

    def __exit__(self, tipo, exc, tb):
        if self._externa:
            return False
        g._transaccion = False
        db = get_db()
        if tipo is None:
            db.commit()
        else:
            db.rollback()
        return False

def get_config_valor(clave, default=""):
    row = query("SELECT valor FROM configuracion WHERE clave=?", (clave,), one=True)
    return row["valor"] if row and row["valor"] not in (None, "") else default


def siguiente_numero(tabla, prefijo, ancho, reservar=False):
    """Próximo número correlativo de `tabla` con la forma <prefijo><N>, N con
    `ancho` dígitos: siguiente_numero("ordenes", "OT-", 3) -> "OT-169". Las
    series por año llevan el año en el prefijo ("LOTE-2026-").

    Parte del número más alto ya cargado con ese prefijo exacto; los que
    después del prefijo no son solo dígitos (otra serie, o cargados a mano con
    otro formato) no cuentan. Si el resultado ya existe, sigue sumando hasta
    encontrar uno libre.

    reservar=True lo hace atómico: toma el lock de escritura de la base
    (BEGIN IMMEDIATE) antes de leer, así ninguna otra conexión puede sacar el
    mismo número entre esta lectura y el INSERT del que llama, cuyo commit
    libera el lock. Junto con el UNIQUE de la columna `numero`, dos altas
    simultáneas nunca comparten número."""
    if reservar:
        db = get_db()
        if not db.in_transaction:
            db.execute("BEGIN IMMEDIATE")
    filas = query(f"""SELECT numero FROM {tabla} WHERE SUBSTR(numero, 1, ?) = ?
        ORDER BY CAST(SUBSTR(numero, ?) AS INTEGER) DESC, id DESC LIMIT 20""",
        (len(prefijo), prefijo, len(prefijo) + 1))
    n = 1
    for f in filas:
        resto = (f["numero"] or "")[len(prefijo):]
        if resto.isdigit():
            n = int(resto) + 1
            break
    numero = f"{prefijo}{n:0{ancho}d}"
    while query(f"SELECT 1 FROM {tabla} WHERE numero=?", (numero,), one=True):
        n += 1
        numero = f"{prefijo}{n:0{ancho}d}"
    return numero


def next_numero_sc():
    # Próximo número de SC (SC-0001, SC-0002, ...) a salvo de condiciones de
    # carrera: si dos solicitudes se crean casi al mismo tiempo (ej: una
    # manual y otra automática por stock bajo) podían calcular el mismo número
    # -> UNIQUE constraint failed. Con BEGIN IMMEDIATE tomamos el lock de
    # escritura antes de leer, así ninguna otra conexión puede colarse entre
    # el SELECT y el INSERT. Las series SC-PROD-0003 y SC-TERC-0005 (MRP y
    # faltantes de terceros) son independientes y no cuentan acá.
    db = get_db()
    propia = not db.in_transaction   # dentro de transaccion() ya hay lock
    if propia:
        db.execute("BEGIN IMMEDIATE")
    try:
        return siguiente_numero("solicitudes_compra", "SC-", 4)
    except:
        if propia:
            db.rollback()
        raise

def next_numero_oc():
    # Mismo problema que next_numero_sc (dos OC creadas casi al mismo tiempo,
    # o un doble-click): BEGIN IMMEDIATE toma el lock de escritura antes de leer.
    db = get_db()
    propia = not db.in_transaction   # dentro de transaccion() ya hay lock
    if propia:
        db.execute("BEGIN IMMEDIATE")
    try:
        return siguiente_numero("ordenes_compra", "OCP-", 4)
    except:
        if propia:
            db.rollback()
        raise

def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

ROLES_BASE = ("admin", "operario", "vendedor", "almacen", "logistica")

def _rol_row(nombre):
    try:
        return query("SELECT * FROM roles WHERE nombre=?", (nombre,), one=True)
    except Exception:
        return None

def _rol_base(nombre):
    """Rol base (define qué endpoints puede usar) de un rol, sea de sistema o creado
    desde Configuración. Si el rol no existe (dato viejo) se usa el nombre tal cual."""
    r = _rol_row(nombre)
    return r["base_rol"] if r else nombre

def _permisos_rol(nombre):
    """Permisos predeterminados de un rol: los de la tabla roles, o los DEFAULT."""
    import json as _j
    r = _rol_row(nombre)
    if r and r["permisos"]:
        try:
            p = _j.loads(r["permisos"])
            if isinstance(p, dict) and p:
                return {k: str(v) for k, v in p.items()}
        except Exception:
            pass
    return dict(DEFAULT_PERMISIONES.get(_rol_base(nombre), {}))

def _permisos_sesion():
    """Permisos efectivos del usuario de la sesión: los suyos, o si no tiene
    ninguno (y no es admin) los predeterminados de su rol."""
    perms = {r["clave"]: r["valor"] for r in
             query("SELECT clave, valor FROM usuario_permisos WHERE usuario_id=?", (session["user_id"],))}
    if not perms and session.get("rol") != "admin":
        perms = _permisos_rol(session.get("rol_nombre") or session.get("rol", "operario"))
    # "Indicadores de compras" no tuvo casilla propia hasta 2026-10, así que
    # quien tenía Compras desactivado igual lo veía. Lo guardado antes de eso
    # hereda lo de Compras (ídem _permMod en app.html).
    if "mod_indicadores_compras" not in perms and "mod_solicitudes" in perms:
        perms["mod_indicadores_compras"] = perms["mod_solicitudes"]
    return perms


def modulo_requerido(mod):
    """Bloquea el endpoint si el módulo está oculto para el usuario, con el
    mismo criterio que el menú (setupRoles en app.html): admin ve todo,
    logística solo lo habilitado con '1', el resto todo salvo lo puesto en '0'."""
    def decorator(f):
        @wraps(f)
        def wrapped(*a, **kw):
            rol = session.get("rol")
            if rol != "admin":
                v = _permisos_sesion().get("mod_" + mod)
                if (v != "1") if rol == "logistica" else (v == "0"):
                    return jsonify({"error": "Sin permiso"}), 403
            return f(*a, **kw)
        return wrapped
    return decorator


def login_required(roles=None):
    def decorator(f):
        @wraps(f)
        def wrapped(*a, **kw):
            if "user_id" not in session:
                # Las rutas /api/* siempre son llamadas por fetch() esperando
                # JSON (ver api() en app.html). Devolverles un redirect HTML
                # a /login hace que r.json() explote con un error críptico
                # ("Unexpected token '<'") en vez de mostrar algo entendible.
                # Solo se redirige de verdad para rutas que no son de API
                # (navegación directa del browser).
                if request.path.startswith("/api/"):
                    return jsonify({"error": "Sesión expirada, volvé a iniciar sesión."}), 401
                return redirect("/login")
            if roles and session.get("rol") not in roles:
                return jsonify({"error": "Sin permiso"}), 403
            return f(*a, **kw)
        return wrapped
    return decorator

# ── Schema ────────────────────────────────────────────────────────────────────
# ── Permiso "ver valores monetarios" ─────────────────────────────────────────
# Regla única de todo el sistema: el servidor decide, y lo que no sale de acá
# no puede filtrarse en el navegador. Antes esto vivía solo en app.html
# (const VER_MONETARIO) y la API mandaba igual todos los importes: bastaba
# abrir la pestaña Red del navegador para verlos.
#
# Para agregar un campo monetario nuevo alcanza con registrarlo en
# CAMPOS_MONETARIOS: el after_request lo saca de todas las respuestas JSON y
# el before_request lo descarta de los payloads de escritura. Si el campo es
# ambiguo (un "total" que son unidades, un "valor" que es un texto), va en
# NO_MONETARIO con el motivo, y tests/test_monetario_schema.py falla si
# aparece una columna nueva que no esté en ninguna de las dos listas.

CAMPOS_MONETARIOS = frozenset({
    # Precios
    "precio", "precio_unit", "precio_unitario", "precio_venta",
    "precio_acordado", "precio_tercerizado", "oc_precio_reciente",
    # Costos
    "costo", "costo_mat", "costo_mo", "costo_total", "costo_terc",
    "costo_terciarizado", "costo_mat_item", "costo_unitario",
    # Montos / totales de dinero
    "monto", "monto_total", "monto_pedido", "monto_entregado",
    "monto_compras_pend", "total_monto_pedido", "total_monto_entregado",
    "subtotal", "importe", "exceso_monto", "precio_total",
    # Facturación
    "facturacion", "facturacion_mes", "facturacion_historico",
    "facturado", "total_facturado",
    # Configuración con contenido monetario
    "valor_hora_mo",
})

# Columnas/claves que el patrón de nombres marca como sospechosas pero NO son
# importes. Si alguna de estas pasara a representar dinero, hay que moverla
# a CAMPOS_MONETARIOS.
NO_MONETARIO = {
    "iva": "condición frente al IVA del cliente (texto: 'Responsable Inscripto'), no un importe",
    "iva_pct": "alícuota en porcentaje del presupuesto, no un importe",
    "nro_factura": "número de comprobante, no un importe",
    "centro_costo": "código de centro de costo, no un importe",
    "cantidad_activa": "unidades aprobadas de un lote; matchea el patrón por 'iva' dentro de 'activa'",
    "cantidad_activa_actual": "idem cantidad_activa",
    "nueva_activa": "idem cantidad_activa",
    "nueva_activa_total": "idem cantidad_activa",
    "cant_activa": "idem cantidad_activa",
    "pdf_mostrar_costos": "bandera 0/1 de configuración; igual se filtra aparte en /api/config",
    "pdf_mostrar_precios": "bandera 0/1 de configuración; igual se filtra aparte en /api/config",
    "mostrar_costos": "bandera interna del PDF",
    "mostrar_precios": "bandera interna del PDF",
}

# Nombres que NO se resuelven por nombre: cada endpoint decide. Se dejan
# anotados para que nadie los agregue al filtro automático sin pensarlo.
CAMPOS_AMBIGUOS = {
    "total": "puede ser unidades (total_realizado) o plata; se resuelve por endpoint",
    "valor": "configuracion.valor es texto genérico; se filtra por clave en /api/config",
    "cantidad": "unidades",
}


def puede_ver_monetario():
    """True si el usuario de la sesión puede ver importes. Cacheado por request."""
    if has_request_context() and "ver_monetario" in g:
        return g.ver_monetario
    ok = _calcular_ver_monetario()
    if has_request_context():
        g.ver_monetario = ok
    return ok


def _calcular_ver_monetario():
    if "user_id" not in session:
        return False                     # sin sesión, lo más restrictivo
    if _rol_base(session.get("rol_nombre") or session.get("rol", "")) == "logistica":
        return False
    try:
        rows = query("SELECT clave, valor FROM usuario_permisos WHERE usuario_id=?",
                     (session["user_id"],))
        perms = {r["clave"]: r["valor"] for r in rows}
    except Exception:
        perms = {}
    if not perms and session.get("rol") != "admin":
        perms = _permisos_rol(session.get("rol_nombre") or session.get("rol", "operario"))
    return perms.get("ver_monetario") != "0"


def solo_con_monetario(f):
    """Endpoint que no tiene nada que devolver sin el permiso: 403 directo."""
    @wraps(f)
    def _envuelto(*a, **kw):
        if not puede_ver_monetario():
            return jsonify({"error": "Sin permiso"}), 403
        return f(*a, **kw)
    return _envuelto


def _sin_monetario(dato):
    """Saca recursivamente toda clave monetaria de un JSON ya parseado."""
    if isinstance(dato, dict):
        for k in [k for k in dato if k in CAMPOS_MONETARIOS]:
            del dato[k]
        for v in dato.values():
            _sin_monetario(v)
    elif isinstance(dato, list):
        for v in dato:
            _sin_monetario(v)
    return dato


def _mon_o_actual(d, clave, tabla, rid):
    """Valor monetario a grabar en un UPDATE: el del payload si vino, y si no
    (un usuario sin ver_monetario nunca lo manda: lo descarta el before_request
    de abajo) el que ya está guardado, para no pisarlo con 0."""
    if clave in d:
        return d[clave]
    fila = query(f"SELECT {clave} v FROM {tabla} WHERE id=?", (rid,), one=True)
    return (fila["v"] if fila else None) or 0


@app.before_request
def _descartar_monetario_entrante():
    """Un usuario restringido no puede escribir importes: se descartan del
    payload antes de que el endpoint lo lea, así no pisa con 0 ni con null lo
    que ya estaba guardado. Los costos que calcula el server siguen igual."""
    if not request.path.startswith("/api/"):
        return
    if request.method not in ("POST", "PUT", "PATCH"):
        return
    if puede_ver_monetario():
        return
    try:
        cuerpo = request.get_json(silent=True)
    except Exception:
        return
    # get_json cachea: mutar el objeto devuelto alcanza para que el endpoint
    # lo vea ya filtrado, sin tocar cada handler.
    if cuerpo is not None:
        _sin_monetario(cuerpo)


@app.after_request
def _descartar_monetario_saliente(resp):
    """Saca los importes de toda respuesta JSON de /api/ para los restringidos."""
    try:
        if not request.path.startswith("/api/"):
            return resp
        if resp.direct_passthrough or not (resp.content_type or "").startswith("application/json"):
            return resp
        if puede_ver_monetario():
            return resp
        datos = _json.loads(resp.get_data(as_text=True))
        resp.set_data(_json.dumps(_sin_monetario(datos), ensure_ascii=False, default=str))
    except Exception as e:
        print(f"[monetario] No se pudo filtrar la respuesta de {request.path}: {e}")
    return resp

# ── Boot ──────────────────────────────────────────────────────────────────────
def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80)); ip = s.getsockname()[0]; s.close(); return ip
    except: return "127.0.0.1"


# Funciones de otras áreas. Van al final a propósito: así cada módulo ya
# definió todo lo suyo cuando otro lo importa, y no hay problemas de
# importación circular. Se usan recién al atender pedidos.
from .comun import cant_material

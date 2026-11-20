"""Configuración general, moneda y cotización del dólar."""
from .nucleo import (_json, app, auditoria_proceso, date, datetime, DB_PATH, execute,
    get_config_valor, get_db, jsonify, login_required, os, puede_ver_monetario, query,
    request, session, sqlite3, threading)

# ── Configuración del sistema ─────────────────────────────────────────────────
# Claves de `configuracion` cuyo contenido es (o revela) un importe.
CONFIG_CLAVES_MONETARIAS = ("valor_hora_mo", "pdf_mostrar_costos", "pdf_mostrar_precios")


@app.route("/api/config", methods=["GET"])
@login_required()
def get_config():
    rows = query("SELECT clave, valor, descripcion FROM configuracion ORDER BY clave")
    ver = puede_ver_monetario()
    return jsonify({r["clave"]: {"valor": r["valor"] or "", "descripcion": r["descripcion"]}
                    for r in rows
                    if ver or r["clave"] not in CONFIG_CLAVES_MONETARIAS})

@app.route("/api/config", methods=["POST"])
@login_required(roles=["admin"])
def save_config():
    d = request.json or {}
    if not puede_ver_monetario():
        # No puede verlas, tampoco pisarlas.
        d = {k: v for k, v in d.items() if k not in CONFIG_CLAVES_MONETARIAS}
    d.pop("moneda", None)  # solo con /api/moneda/cambiar, que convierte los precios
    if "dolar_casa" in d and d["dolar_casa"] not in DOLAR_CASAS:
        return jsonify({"error": "Tipo de dólar desconocido"}), 400
    for clave, valor in d.items():
        execute("UPDATE configuracion SET valor=? WHERE clave=?", (str(valor), clave))
    return jsonify({"ok": True})

# ── Moneda (pesos / dólares) y cotización del dólar ──────────────────────────
# La cotización se trae sola de DolarAPI (dolarapi.com: oficial, MEP, blue, CCL,
# mayorista, tarjeta) al arrancar y cada DOLAR_INTERVALO_SEG. Si no hay internet
# se sigue con la última guardada; también se puede cargar a mano.
DOLAR_API_URL = "https://dolarapi.com/v1/dolares"
DOLAR_INTERVALO_SEG = 3 * 3600
DOLAR_CASAS = {
    "oficial": "Oficial",
    "bolsa": "MEP (bolsa)",
    "contadoconliqui": "Contado con liqui",
    "blue": "Blue",
    "mayorista": "Mayorista",
    "tarjeta": "Tarjeta",
}
_dolar_estado = {"ultimo_intento": None, "ultimo_ok": None, "error": None}

# Precios vigentes que se convierten al cambiar la moneda: (clave, tabla,
# columna, filtro, descripción). Lo ya emitido (OCs, presupuestos, pedidos,
# OTTs, OTs, recepciones) NO se toca: queda en la moneda en que se hizo.
MONEDA_CONVERSION = (
    ("mo", "configuracion", "valor", "clave='valor_hora_mo'", "Valor de mano de obra por hora"),
    ("mat_precio", "materiales", "precio_unit", "precio_unit<>0", "Precio de compra de materiales"),
    ("mat_costo_mat", "materiales", "costo_mat", "costo_mat<>0", "Costo de materiales guardado en productos"),
    ("mat_costo_mo", "materiales", "costo_mo", "costo_mo<>0", "Costo de mano de obra guardado en productos"),
    ("mat_pventa", "materiales", "precio_venta", "precio_venta<>0", "Precio de venta de productos"),
    ("prov_mat", "proveedor_materiales", "precio_unit", "precio_unit<>0", "Precios de materiales por proveedor"),
    ("prov_serv", "proveedor_servicios", "precio_unit", "precio_unit<>0", "Servicios de terceros por proveedor"),
    ("proc_terc", "proceso_operaciones", "precio_tercerizado", "precio_tercerizado<>0", "Precio tercerizado en los procesos"),
    ("cot_abiertas", "cotizaciones_compra", "precio_unit",
     "precio_unit<>0 AND solicitud_id IN (SELECT id FROM solicitudes_compra WHERE estado IN ('Pendiente','Cotizada'))",
     "Cotizaciones de compra abiertas"),
)


def moneda_sistema():
    try:
        return get_config_valor("moneda", "ARS") or "ARS"
    except Exception:
        return "ARS"


def _dolar_descargar():
    import urllib.request
    req = urllib.request.Request(DOLAR_API_URL, headers={"User-Agent": "MetalERP", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return _json.loads(r.read().decode("utf-8"))


def actualizar_cotizacion_dolar():
    """Trae las cotizaciones del día y las guarda (una por tipo y día; si ya
    había una de la API para hoy, se reemplaza). Devuelve cuántas guardó."""
    _dolar_estado["ultimo_intento"] = datetime.now().isoformat(timespec="seconds")
    try:
        datos = _dolar_descargar()
        if isinstance(datos, dict):
            datos = [datos]
        hoy = date.today().isoformat()
        n = 0
        for d in datos:
            casa = d.get("casa")
            venta = d.get("venta")
            if casa not in DOLAR_CASAS or not isinstance(venta, (int, float)) or venta <= 0:
                continue
            execute("DELETE FROM cotizaciones_dolar WHERE fecha=? AND casa=? AND fuente='api'", (hoy, casa))
            execute("""INSERT INTO cotizaciones_dolar (fecha,casa,compra,venta,fuente,fecha_api)
                VALUES (?,?,?,?, 'api', ?)""", (hoy, casa, d.get("compra"), float(venta), d.get("fechaActualizacion")))
            n += 1
        if not n:
            raise ValueError("la respuesta no trajo cotizaciones")
        _dolar_estado["ultimo_ok"] = _dolar_estado["ultimo_intento"]
        _dolar_estado["error"] = None
        return n
    except Exception as e:
        _dolar_estado["error"] = f"{type(e).__name__}: {e}"[:300]
        raise


def _dolar_bucle():
    while True:
        try:
            with app.app_context(), auditoria_proceso("cotización del dólar"):
                actualizar_cotizacion_dolar()
        except Exception as e:
            try:
                print(f"[dolar] No se pudo actualizar la cotización: {e}")
            except Exception:
                pass
        threading.Event().wait(DOLAR_INTERVALO_SEG)


def iniciar_cotizacion_automatica():
    threading.Thread(target=_dolar_bucle, name="cotizacion-dolar", daemon=True).start()


def cotizacion_vigente(casa=None):
    casa = casa or get_config_valor("dolar_casa", "oficial")
    r = query("""SELECT * FROM cotizaciones_dolar WHERE casa=?
        ORDER BY fecha DESC, id DESC LIMIT 1""", (casa,), one=True)
    return dict(r) if r else None


@app.route("/api/dolar", methods=["GET"])
@login_required()
def get_dolar():
    casa = get_config_valor("dolar_casa", "oficial")
    hoy = date.today().isoformat()
    return jsonify({
        "moneda": moneda_sistema(),
        "casa": casa,
        "casas": DOLAR_CASAS,
        "actual": cotizacion_vigente(casa),
        "hoy_todas": [dict(r) for r in query("""SELECT casa,compra,venta,fuente FROM cotizaciones_dolar c
            WHERE fecha=(SELECT MAX(fecha) FROM cotizaciones_dolar) AND id=(SELECT MAX(id)
            FROM cotizaciones_dolar c2 WHERE c2.casa=c.casa AND c2.fecha=c.fecha)""")],
        "historial": [dict(r) for r in query("""SELECT fecha,compra,venta,fuente FROM cotizaciones_dolar
            WHERE casa=? ORDER BY fecha DESC, id DESC LIMIT 15""", (casa,))],
        "hoy": hoy,
        "estado": _dolar_estado,
        "cambios": [dict(r) for r in query("""SELECT mc.*,u.nombre usuario_nombre FROM moneda_cambios mc
            LEFT JOIN usuarios u ON u.id=mc.usuario_id ORDER BY mc.id DESC LIMIT 10""")],
    })


@app.route("/api/dolar/actualizar", methods=["POST"])
@login_required(roles=["admin"])
def post_dolar_actualizar():
    try:
        with auditoria_proceso("cotización del dólar"):
            n = actualizar_cotizacion_dolar()
    except Exception:
        return jsonify({"error": "No se pudo traer la cotización de internet ("
                        + (_dolar_estado["error"] or "error desconocido")
                        + "). Podés cargarla a mano."}), 502
    return jsonify({"ok": True, "guardadas": n, "actual": cotizacion_vigente()})


@app.route("/api/dolar/manual", methods=["POST"])
@login_required(roles=["admin"])
def post_dolar_manual():
    d = request.json or {}
    casa = d.get("casa") or get_config_valor("dolar_casa", "oficial")
    if casa not in DOLAR_CASAS:
        return jsonify({"error": "Tipo de dólar desconocido"}), 400
    try:
        venta = float(d.get("venta"))
        compra = float(d["compra"]) if d.get("compra") not in (None, "") else None
    except (TypeError, ValueError):
        return jsonify({"error": "Cotización inválida"}), 400
    if venta <= 0:
        return jsonify({"error": "La cotización tiene que ser mayor a cero"}), 400
    execute("""INSERT INTO cotizaciones_dolar (fecha,casa,compra,venta,fuente,usuario_id)
        VALUES (?,?,?,?,'manual',?)""", (date.today().isoformat(), casa, compra, venta, session.get("user_id")))
    return jsonify({"ok": True, "actual": cotizacion_vigente(casa)})


def _moneda_parametros():
    """(origen, destino, cotización, factor) del pedido, o un error."""
    d = request.json if request.method == "POST" else request.args
    d = d or {}
    origen = moneda_sistema()
    destino = d.get("destino")
    if destino not in ("ARS", "USD"):
        return None, "Moneda destino inválida"
    if destino == origen:
        return None, "El sistema ya está en " + ("dólares" if destino == "USD" else "pesos")
    try:
        cot = float(d.get("cotizacion"))
    except (TypeError, ValueError):
        return None, "Cotización inválida"
    if cot <= 0:
        return None, "La cotización tiene que ser mayor a cero"
    factor = 1.0 / cot if destino == "USD" else cot
    return (origen, destino, cot, factor), None


def _redondeo_moneda(v, destino):
    """En dólares se guardan más decimales (6 bajo 1 US$, si no 4) para no
    perder precisión, ni siquiera al volver a pesos; en pesos, centavos."""
    if destino == "ARS":
        return round(v, 2)
    return round(v, 6 if abs(v) < 1 else 4)


def _moneda_filas(clave, tabla, columna, filtro):
    if tabla == "materiales":
        sql = f"SELECT id, codigo||' — '||descripcion nombre, {columna} v FROM materiales WHERE {filtro} ORDER BY codigo"
    elif tabla == "configuracion":
        sql = f"SELECT clave id, descripcion nombre, CAST(valor AS REAL) v FROM configuracion WHERE {filtro}"
    elif tabla == "proveedor_servicios":
        sql = f"""SELECT s.id, COALESCE(p.razon,'')||' — '||s.nombre nombre, s.precio_unit v FROM proveedor_servicios s
            LEFT JOIN proveedores p ON p.id=s.proveedor_id WHERE {filtro.replace('precio_unit','s.precio_unit')}"""
    elif tabla == "proveedor_materiales":
        sql = f"""SELECT pm.id, COALESCE(p.razon,'')||' — '||COALESCE(m.codigo,'') nombre, pm.precio_unit v
            FROM proveedor_materiales pm LEFT JOIN proveedores p ON p.id=pm.proveedor_id
            LEFT JOIN materiales m ON m.id=pm.material_id WHERE {filtro.replace('precio_unit','pm.precio_unit')}"""
    elif tabla == "proceso_operaciones":
        sql = f"""SELECT po.id, COALESCE(m.codigo,'')||' — '||po.nombre nombre, po.precio_tercerizado v
            FROM proceso_operaciones po LEFT JOIN materiales m ON m.id=po.producto_id
            WHERE {filtro.replace('precio_tercerizado','po.precio_tercerizado')}"""
    elif tabla == "cotizaciones_compra":
        sql = f"""SELECT c.id, COALESCE(sc.numero,'')||' — '||COALESCE(p.razon,'') nombre, c.precio_unit v
            FROM cotizaciones_compra c LEFT JOIN solicitudes_compra sc ON sc.id=c.solicitud_id
            LEFT JOIN proveedores p ON p.id=c.proveedor_id
            WHERE {filtro.replace('precio_unit','c.precio_unit').replace('solicitud_id','c.solicitud_id')}"""
    else:
        sql = f"SELECT id, id nombre, {columna} v FROM {tabla} WHERE {filtro}"
    return query(sql)


@app.route("/api/moneda/vista_previa", methods=["GET"])
@login_required(roles=["admin"])
def moneda_vista_previa():
    if not puede_ver_monetario():
        return jsonify({"error": "Necesitás permiso para ver importes"}), 403
    par, err = _moneda_parametros()
    if err:
        return jsonify({"error": err}), 400
    origen, destino, cot, factor = par
    grupos = []
    for clave, tabla, columna, filtro, desc in MONEDA_CONVERSION:
        filas = _moneda_filas(clave, tabla, columna, filtro)
        grupos.append({
            "clave": clave, "descripcion": desc, "cantidad": len(filas),
            "filas": [{"nombre": r["nombre"], "antes": r["v"], "despues": _redondeo_moneda((r["v"] or 0) * factor, destino)}
                      for r in filas],
        })
    return jsonify({"origen": origen, "destino": destino, "cotizacion": cot, "grupos": grupos})


@app.route("/api/moneda/cambiar", methods=["POST"])
@login_required(roles=["admin"])
def moneda_cambiar():
    """Pasa los precios vigentes a la otra moneda con la cotización dada. Antes
    hace una copia completa de la base. Todo o nada."""
    if not puede_ver_monetario():
        return jsonify({"error": "Necesitás permiso para ver importes"}), 403
    par, err = _moneda_parametros()
    if err:
        return jsonify({"error": err}), 400
    origen, destino, cot, factor = par
    db = get_db()
    marca = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = os.path.join(os.path.dirname(DB_PATH), f"metalerp_backup_pre_moneda_{marca}.db")
    n = 2
    while os.path.exists(backup):
        backup = os.path.join(os.path.dirname(DB_PATH), f"metalerp_backup_pre_moneda_{marca}_{n}.db")
        n += 1
    try:
        dst = sqlite3.connect(backup)
        db.backup(dst)
        dst.close()
    except Exception as e:
        return jsonify({"error": f"No se pudo hacer la copia de seguridad, no se cambió nada ({e})"}), 500
    redondeo = ("ROUND({c}*?, 2)" if destino == "ARS"
                else "ROUND({c}*?, CASE WHEN ABS({c}*?)<1 THEN 6 ELSE 4 END)")
    filas = 0
    try:
        db.commit()
        db.execute("BEGIN IMMEDIATE")
        for clave, tabla, columna, filtro, desc in MONEDA_CONVERSION:
            if tabla == "configuracion":
                r = db.execute(f"SELECT valor FROM configuracion WHERE {filtro}").fetchone()
                try:
                    v = float(r["valor"] or 0) if r else 0.0
                except (TypeError, ValueError):
                    v = 0.0
                db.execute(f"UPDATE configuracion SET valor=? WHERE {filtro}", (str(_redondeo_moneda(v * factor, destino)),))
                filas += 1
                continue
            cur = db.execute(f"UPDATE {tabla} SET {columna}={redondeo.format(c=columna)} WHERE {filtro}",
                             (factor,) if destino == "ARS" else (factor, factor))
            filas += cur.rowcount
        db.execute("""UPDATE cotizaciones_compra SET moneda=? WHERE solicitud_id IN
            (SELECT id FROM solicitudes_compra WHERE estado IN ('Pendiente','Cotizada'))""", (destino,))
        db.execute("UPDATE configuracion SET valor=? WHERE clave='moneda'", (destino,))
        db.execute("""INSERT INTO moneda_cambios (origen,destino,cotizacion,casa,filas,backup,usuario_id)
            VALUES (?,?,?,?,?,?,?)""", (origen, destino, cot, get_config_valor("dolar_casa", "oficial"),
                                         filas, os.path.basename(backup), session.get("user_id")))
        db.commit()
    except Exception as e:
        db.rollback()
        return jsonify({"error": f"No se pudo convertir, no se cambió nada ({e})"}), 500
    return jsonify({"ok": True, "moneda": destino, "filas": filas, "backup": os.path.basename(backup)})

"""Categorías de máquina, máquinas, mantenimiento preventivo y tickets."""
from .nucleo import (_mon_o_actual, app, date, datetime, execute, jsonify, login_required,
    query, re, request, session, siguiente_numero, timedelta)

@app.route("/api/categorias_maquina/<int:cid>", methods=["PUT"])
@login_required(roles=["admin"])
def update_cat_maq(cid):
    d = request.json
    execute("UPDATE categorias_maquina SET nombre=?,descripcion=? WHERE id=?",
            (d["nombre"], d.get("descripcion"), cid))
    return jsonify({"ok": True})

@app.route("/api/categorias_maquina/<int:cid>", methods=["DELETE"])
@login_required(roles=["admin"])
def delete_cat_maq(cid):
    used = query("SELECT COUNT(*) c FROM proceso_operaciones WHERE categoria_maquina_id=?", (cid,), one=True)["c"]
    if used:
        return jsonify({"error": f"En uso por {used} operación(es)"}), 400
    execute("DELETE FROM categorias_maquina WHERE id=?", (cid,))
    return jsonify({"ok": True})

@app.route("/api/categorias_maquina", methods=["GET"])
@login_required()
def get_cat_maq(): return jsonify([dict(r) for r in query("SELECT * FROM categorias_maquina ORDER BY nombre")])

@app.route("/api/categorias_maquina", methods=["POST"])
@login_required(roles=["admin"])
def create_cat_maq():
    d = request.json
    if not d.get("nombre"): return jsonify({"error":"Nombre requerido"}), 400
    lid = execute("INSERT INTO categorias_maquina (nombre,descripcion) VALUES (?,?)", (d["nombre"],d.get("descripcion")))
    return jsonify({"ok":True,"id":lid}), 201

# ── Maquinas ──────────────────────────────────────────────────────────────────
def _codigo_sort_key(codigo):
    m = re.match(r"^([A-Za-z]*)(\d+)$", (codigo or "").strip())
    if m:
        return (m.group(1).upper(), int(m.group(2)))
    return ((codigo or "").upper(), 0)

@app.route("/api/maquinas", methods=["GET"])
@login_required()
def get_maquinas():
    rows = query("SELECT m.*,c.nombre categoria_nombre FROM maquinas m LEFT JOIN categorias_maquina c ON c.id=m.categoria_id")
    horas = _horas_maquinas()
    result = []
    for r in rows:
        d = dict(r)
        d["horas_actuales"] = horas.get(r["id"], float(r["horas_uso"] or 0))
        d["reemplazos"] = [dict(x) for x in query("SELECT m2.id,m2.codigo,m2.nombre FROM maquina_reemplazos mr JOIN maquinas m2 ON m2.id=mr.reemplazo_id WHERE mr.maquina_id=?", (r["id"],))]
        result.append(d)
    result.sort(key=lambda d: _codigo_sort_key(d.get("codigo")))
    return jsonify(result)

@app.route("/api/maquinas", methods=["POST"])
@login_required(roles=["admin","operario"])
def create_maquina():
    d = request.json
    if not d.get("codigo") or not d.get("nombre"): return jsonify({"error":"Código y nombre requeridos"}), 400
    if query("SELECT id FROM maquinas WHERE codigo=?", (d["codigo"],), one=True): return jsonify({"error":"Código ya existe"}), 409
    lid = execute("INSERT INTO maquinas (codigo,nombre,categoria_id,marca,modelo,numero_serie,anio,ubicacion,estado,horas_uso,obs) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (d["codigo"],d["nombre"],d.get("categoria_id"),d.get("marca"),d.get("modelo"),d.get("numero_serie"),d.get("anio"),d.get("ubicacion"),d.get("estado","Operativa"),d.get("horas_uso",0),d.get("obs")))
    for rid in (d.get("reemplazos") or []):
        try: execute("INSERT OR IGNORE INTO maquina_reemplazos (maquina_id,reemplazo_id) VALUES (?,?)", (lid, int(rid)))
        except: pass
    return jsonify({"ok":True,"id":lid}), 201

@app.route("/api/maquinas/<int:mid>", methods=["PUT"])
@login_required(roles=["admin","operario"])
def update_maquina(mid):
    d = request.json
    execute("UPDATE maquinas SET nombre=?,categoria_id=?,marca=?,modelo=?,numero_serie=?,anio=?,ubicacion=?,estado=?,horas_uso=?,obs=? WHERE id=?",
        (d["nombre"],d.get("categoria_id"),d.get("marca"),d.get("modelo"),d.get("numero_serie"),d.get("anio"),d.get("ubicacion"),d.get("estado","Operativa"),d.get("horas_uso",0),d.get("obs"),mid))
    execute("DELETE FROM maquina_reemplazos WHERE maquina_id=?", (mid,))
    for rid in (d.get("reemplazos") or []):
        try: execute("INSERT OR IGNORE INTO maquina_reemplazos (maquina_id,reemplazo_id) VALUES (?,?)", (mid, int(rid)))
        except: pass
    return jsonify({"ok":True})

# ── Mantenimiento ─────────────────────────────────────────────────────────────
MANT_DIAS_AVISO = 7        # fecha: "Próximo" si vence dentro de estos días
MANT_HORAS_AVISO_PCT = 0.10  # horas: "Próximo" si falta menos de este % de la frecuencia


def _horas_maquinas():
    """Horas de uso de cada máquina: las cargadas a mano en la máquina (las que
    traía antes de MetalERP) más el tiempo real de las novedades de producción
    hechas en ella (la de la novedad o, si no tiene, la de la operación)."""
    prod = {r["mid"]: r["min"] or 0 for r in query(
        """SELECT COALESCE(n.maquina_id, oo.maquina_id) mid, SUM(n.tiempo_real_min) min
           FROM novedades_produccion n
           LEFT JOIN orden_operaciones oo ON oo.id=n.orden_operacion_id
           WHERE COALESCE(n.maquina_id, oo.maquina_id) IS NOT NULL
           GROUP BY COALESCE(n.maquina_id, oo.maquina_id)""")}
    return {r["id"]: round(float(r["horas_uso"] or 0) + prod.get(r["id"], 0) / 60.0, 1)
            for r in query("SELECT id, horas_uso FROM maquinas")}


def _sumar_frecuencia(fecha_iso, tipo, valor):
    """Fecha + frecuencia (dias/semanas/meses). None si no aplica."""
    try:
        f = date.fromisoformat(str(fecha_iso)[:10])
        v = int(valor)
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    if tipo == "dias":
        return (f + timedelta(days=v)).isoformat()
    if tipo == "semanas":
        return (f + timedelta(weeks=v)).isoformat()
    if tipo == "meses":
        m = f.month - 1 + v
        anio, mes = f.year + m // 12, m % 12 + 1
        dias_mes = [31, 29 if anio % 4 == 0 and (anio % 100 or anio % 400 == 0) else 28,
                    31, 30, 31, 30, 31, 31, 30, 31, 30, 31][mes - 1]
        return date(anio, mes, min(f.day, dias_mes)).isoformat()
    return None


def _mant_estado(p, horas_act):
    """Completa un plan (dict) con las horas actuales de la máquina, las horas
    de la próxima realización y su estado: Vencido, Próximo, Al día,
    Por condición o Sin programar. Si vence por fecha y por horas, manda
    el peor de los dos."""
    p["horas_actuales"] = horas_act
    p["proxima_horas"] = None
    p["faltan_horas"] = None
    p["faltan_dias"] = None
    if p.get("tipo") == "Por condicion":
        p["estado"] = "Por condición"
        return p
    nivel = -1  # -1 sin dato, 0 al día, 1 próximo, 2 vencido
    if p.get("frecuencia_tipo") == "horas" and p.get("frecuencia_valor"):
        frec = float(p["frecuencia_valor"])
        p["proxima_horas"] = round(float(p.get("ultima_horas") or 0) + frec, 1)
        p["faltan_horas"] = round(p["proxima_horas"] - horas_act, 1)
        nivel = max(nivel, 2 if p["faltan_horas"] <= 0 else
                    1 if p["faltan_horas"] <= frec * MANT_HORAS_AVISO_PCT else 0)
    if p.get("proxima_fecha"):
        try:
            dias = (date.fromisoformat(p["proxima_fecha"][:10]) - date.today()).days
            p["faltan_dias"] = dias
            nivel = max(nivel, 2 if dias < 0 else 1 if dias <= MANT_DIAS_AVISO else 0)
        except ValueError:
            pass
    p["estado"] = {2: "Vencido", 1: "Próximo", 0: "Al día"}.get(nivel, "Sin programar")
    return p


def _mant_planes():
    horas = _horas_maquinas()
    rows = query("""SELECT p.*,m.nombre maquina_nombre,m.codigo maquina_codigo,
        (SELECT COUNT(*) FROM mantenimiento_registros r WHERE r.plan_id=p.id) realizaciones
        FROM mantenimiento_plan p JOIN maquinas m ON m.id=p.maquina_id
        ORDER BY p.proxima_fecha,m.nombre""")
    return [_mant_estado(dict(r), horas.get(r["maquina_id"], 0.0)) for r in rows]


def _mant_alertas():
    """Planes vencidos y próximos, los vencidos primero (para el tablero y
    el aviso del menú)."""
    orden = {"Vencido": 0, "Próximo": 1}
    al = [p for p in _mant_planes() if p["estado"] in orden]
    al.sort(key=lambda p: (orden[p["estado"]], p["faltan_dias"] if p["faltan_dias"] is not None else 99999,
                           p["faltan_horas"] if p["faltan_horas"] is not None else 1e9))
    return [{"id": p["id"], "maquina": p["maquina_nombre"], "maquina_codigo": p["maquina_codigo"],
             "tarea": p["tarea"], "tipo": p["tipo"], "estado": p["estado"],
             "proxima_fecha": p["proxima_fecha"], "proxima_horas": p["proxima_horas"],
             "faltan_horas": p["faltan_horas"], "horas_actuales": p["horas_actuales"]} for p in al]


def _mant_datos(d, pid=None):
    """Valores del plan a guardar. Para frecuencia en días/semanas/meses, si
    hay última realización y no se dio la próxima fecha, se calcula. Para
    frecuencia en horas, si no se dieron las horas de la última realización
    se cuentan desde las horas actuales de la máquina (plan nuevo)."""
    ftp = d.get("frecuencia_tipo")
    fvl = d.get("frecuencia_valor") or None
    ult_h = d.get("ultima_horas")
    ult_h = None if ult_h in (None, "") else float(ult_h)
    prox = d.get("proxima_fecha") or None
    if d.get("tipo") != "Por condicion":
        if ftp in ("dias", "semanas", "meses") and not prox and d.get("ultima_fecha"):
            prox = _sumar_frecuencia(d["ultima_fecha"], ftp, fvl)
        if ftp == "horas" and ult_h is None and pid is None:
            ult_h = _horas_maquinas().get(int(d["maquina_id"]), 0.0)
    return (d.get("tipo", "Frecuencia fija"), ftp, fvl, d.get("ultima_fecha") or None,
            prox, d.get("responsable"), d.get("obs"), ult_h)


@app.route("/api/mantenimiento", methods=["GET"])
@login_required()
def get_mantenimiento():
    return jsonify(_mant_planes())

@app.route("/api/mantenimiento/alertas", methods=["GET"])
@login_required()
def get_mantenimiento_alertas():
    al = _mant_alertas()
    return jsonify({"vencidas": sum(1 for a in al if a["estado"] == "Vencido"),
                    "proximas": sum(1 for a in al if a["estado"] == "Próximo"),
                    "items": al[:10]})

@app.route("/api/mantenimiento", methods=["POST"])
@login_required(roles=["admin","operario"])
def create_mantenimiento():
    d = request.json
    if not d.get("maquina_id") or not d.get("tarea"): return jsonify({"error":"Máquina y tarea requeridas"}), 400
    lid = execute("INSERT INTO mantenimiento_plan (maquina_id,tarea,tipo,frecuencia_tipo,frecuencia_valor,ultima_fecha,proxima_fecha,responsable,obs,ultima_horas) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (d["maquina_id"],d["tarea"])+_mant_datos(d))
    return jsonify({"ok":True,"id":lid}), 201

@app.route("/api/mantenimiento/<int:pid>", methods=["PUT"])
@login_required(roles=["admin","operario"])
def update_mantenimiento(pid):
    d = request.json
    if not d.get("tarea"): return jsonify({"error":"La tarea es requerida"}), 400
    datos = _mant_datos(d, pid)
    maq = d.get("maquina_id") or query("SELECT maquina_id FROM mantenimiento_plan WHERE id=?", (pid,), one=True)["maquina_id"]
    execute("UPDATE mantenimiento_plan SET maquina_id=?,tarea=?,tipo=?,frecuencia_tipo=?,frecuencia_valor=?,ultima_fecha=?,proxima_fecha=?,responsable=?,obs=?,ultima_horas=? WHERE id=?",
        (maq,d["tarea"])+datos+(pid,))
    return jsonify({"ok":True})

@app.route("/api/mantenimiento/<int:pid>", methods=["DELETE"])
@login_required(roles=["admin"])
def delete_mantenimiento(pid):
    execute("DELETE FROM mantenimiento_registros WHERE plan_id=?", (pid,))
    execute("DELETE FROM mantenimiento_plan WHERE id=?", (pid,))
    return jsonify({"ok":True})

@app.route("/api/mantenimiento/<int:pid>/realizar", methods=["POST"])
@login_required(roles=["admin","operario"])
def realizar_mantenimiento(pid):
    """Registra que la tarea se hizo: queda en el historial y el plan vuelve
    a contar desde esta fecha y estas horas de máquina."""
    p = query("SELECT * FROM mantenimiento_plan WHERE id=?", (pid,), one=True)
    if not p: return jsonify({"error":"Tarea no encontrada"}), 404
    d = request.json or {}
    fecha = (d.get("fecha") or date.today().isoformat())[:10]
    try:
        date.fromisoformat(fecha)
    except ValueError:
        return jsonify({"error":"Fecha inválida"}), 400
    if fecha > date.today().isoformat():
        return jsonify({"error":"La fecha no puede ser futura"}), 400
    horas = d.get("horas")
    try:
        horas = _horas_maquinas().get(p["maquina_id"], 0.0) if horas in (None, "") else float(horas)
    except (TypeError, ValueError):
        return jsonify({"error":"Horas inválidas"}), 400
    execute("""INSERT INTO mantenimiento_registros (plan_id,maquina_id,fecha,horas,responsable,obs,usuario_id)
        VALUES (?,?,?,?,?,?,?)""",
        (pid, p["maquina_id"], fecha, horas, d.get("responsable") or p["responsable"], d.get("obs"), session.get("user_id")))
    prox = p["proxima_fecha"]
    if p["tipo"] != "Por condicion":
        if p["frecuencia_tipo"] in ("dias", "semanas", "meses"):
            prox = _sumar_frecuencia(fecha, p["frecuencia_tipo"], p["frecuencia_valor"]) or prox
        elif p["frecuencia_tipo"] == "horas":
            prox = None
    execute("UPDATE mantenimiento_plan SET ultima_fecha=?,ultima_horas=?,proxima_fecha=? WHERE id=?",
        (fecha, horas, prox, pid))
    return jsonify({"ok":True,"proxima_fecha":prox})

@app.route("/api/mantenimiento/<int:pid>/registros", methods=["GET"])
@login_required()
def get_mantenimiento_registros(pid):
    return jsonify([dict(r) for r in query("""SELECT r.*,u.nombre usuario_nombre
        FROM mantenimiento_registros r LEFT JOIN usuarios u ON u.id=r.usuario_id
        WHERE r.plan_id=? ORDER BY r.fecha DESC, r.id DESC""", (pid,))])

# ── Tickets ───────────────────────────────────────────────────────────────────
@app.route("/api/tickets", methods=["GET"])
@login_required()
def get_tickets():
    estado = request.args.get("estado")
    sql = "SELECT t.*,m.nombre maquina_nombre,m.codigo maquina_codigo FROM tickets_reparacion t JOIN maquinas m ON m.id=t.maquina_id"
    rows = query(sql+" WHERE t.estado=? ORDER BY t.id DESC",(estado,)) if estado else query(sql+" ORDER BY t.id DESC")
    return jsonify([dict(r) for r in rows])

@app.route("/api/tickets", methods=["POST"])
@login_required(roles=["admin","operario"])
def create_ticket():
    d = request.json
    if not d.get("maquina_id") or not d.get("descripcion"): return jsonify({"error":"Máquina y descripción requeridas"}), 400
    numero = siguiente_numero("tickets_reparacion", "TKT-", 3)
    lid = execute("INSERT INTO tickets_reparacion (numero,maquina_id,tipo,descripcion,prioridad,estado,responsable,horas_paro,creado_por) VALUES (?,?,?,?,?,?,?,?,?)",
        (numero,d["maquina_id"],d.get("tipo","Correctivo"),d["descripcion"],d.get("prioridad","Normal"),"Abierto",d.get("responsable"),0,session["user_id"]))
    execute("UPDATE maquinas SET estado='En mantenimiento' WHERE id=? AND estado='Operativa'", (d["maquina_id"],))
    return jsonify({"ok":True,"id":lid,"numero":numero}), 201

def calc_horas_paro_habiles(fecha_apertura_str, fecha_cierre_dt):
    """Calcula horas de paro entre apertura y cierre, excluyendo sábados y domingos.
    fecha_cierre_dt debe ser un datetime (momento exacto del cierre), no una date."""
    try:
        apertura = datetime.fromisoformat(fecha_apertura_str)
    except Exception:
        return 0.0
    # Si por error llega un date (sin hora), se usa fin de día como fallback,
    # pero el caller siempre debe pasar datetime.now() para reflejar la hora real.
    cierre = datetime.combine(fecha_cierre_dt, datetime.max.time()) if not hasattr(fecha_cierre_dt, 'hour') else fecha_cierre_dt
    if cierre <= apertura:
        return 0.0
    total_segundos = 0.0
    current = apertura
    while current < cierre:
        next_step = min(current.replace(hour=23,minute=59,second=59), cierre)
        # 0=lunes ... 5=sábado, 6=domingo
        if current.weekday() < 5:  # día hábil
            total_segundos += (next_step - current).total_seconds()
        # avanzar al inicio del próximo día
        current = (current.replace(hour=0, minute=0, second=0) + timedelta(days=1))
    return round(total_segundos / 3600, 2)

@app.route("/api/tickets/<int:tid>", methods=["PUT"])
@login_required(roles=["admin","operario"])
def update_ticket(tid):
    d = request.json
    fecha_cierre = None
    horas_paro_calc = None
    horas_ajuste = abs(float(d.get("horas_ajuste") or 0))
    if d.get("estado") == "Cerrado":
        momento_cierre = datetime.now()
        fecha_cierre = momento_cierre.isoformat(sep=' ', timespec='seconds')
        t_apertura = query("SELECT fecha_apertura,horas_paro FROM tickets_reparacion WHERE id=?", (tid,), one=True)
        if t_apertura and t_apertura["fecha_apertura"]:
            horas_paro_calc = calc_horas_paro_habiles(t_apertura["fecha_apertura"], momento_cierre) + horas_ajuste
        else:
            horas_paro_calc = max(0.0, horas_ajuste)
    else:
        fecha_cierre = d.get("fecha_cierre")
        # Mantener horas_paro existente si no se cierra
        t_existing = query("SELECT horas_paro FROM tickets_reparacion WHERE id=?", (tid,), one=True)
        horas_paro_calc = t_existing["horas_paro"] if t_existing else 0.0
    execute("UPDATE tickets_reparacion SET descripcion=?,tipo=?,prioridad=?,estado=?,responsable=?,fecha_cierre=?,horas_paro=?,horas_ajuste=?,costo=?,solucion=? WHERE id=?",
        (d["descripcion"],d.get("tipo","Correctivo"),d.get("prioridad","Normal"),d.get("estado","Abierto"),d.get("responsable"),fecha_cierre,horas_paro_calc,horas_ajuste,_mon_o_actual(d,"costo","tickets_reparacion",tid),d.get("solucion"),tid))
    if d.get("estado") == "Cerrado":
        t = query("SELECT maquina_id FROM tickets_reparacion WHERE id=?", (tid,), one=True)
        if t:
            open_count = query("SELECT COUNT(*) c FROM tickets_reparacion WHERE maquina_id=? AND estado='Abierto' AND id!=?", (t["maquina_id"],tid), one=True)["c"]
            if open_count == 0: execute("UPDATE maquinas SET estado='Operativa' WHERE id=?", (t["maquina_id"],))
    return jsonify({"ok":True})

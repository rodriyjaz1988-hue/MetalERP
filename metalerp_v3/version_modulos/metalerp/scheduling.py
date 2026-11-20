"""Operaciones pendientes por sector y scheduling (Gantt) de producción."""
from .nucleo import app, execute, get_db, jsonify, login_required, query, request

# ── Operaciones pendientes por sector (punto 19) ─────────────────────────────
@app.route("/api/operaciones_pendientes", methods=["GET"])
@login_required()
def get_operaciones_pendientes():
    """Renglones de operaciones Pendientes / En proceso de OTs Pendientes / En proceso.
    Filtro opcional por sector (categoria_maquina_id), maquina, estado y texto."""
    cat = request.args.get("categoria_id")
    estado = request.args.get("estado")
    q = (request.args.get("q") or "").strip()
    sql = """SELECT oo.id, oo.orden_id, oo.orden, oo.nombre operacion, oo.estado,
        oo.qty_requerida, oo.qty_producida, oo.es_tercerizada,
        oo.categoria_maquina_id, cm.nombre sector, oo.maquina_id, m.nombre maquina_nombre,
        o.numero ot_numero, o.prioridad, o.fecha_entrega, o.estado ot_estado,
        p.codigo producto_codigo, p.nombre producto_nombre, c.razon cliente_nombre,
        pr.razon proveedor_nombre
        FROM orden_operaciones oo
        JOIN ordenes o ON o.id=oo.orden_id
        LEFT JOIN categorias_maquina cm ON cm.id=oo.categoria_maquina_id
        LEFT JOIN maquinas m ON m.id=oo.maquina_id
        LEFT JOIN productos p ON p.id=o.producto_id
        LEFT JOIN clientes c ON c.id=o.cliente_id
        LEFT JOIN proveedores pr ON pr.id=oo.proveedor_id
        WHERE o.estado IN ('Pendiente','En proceso')
          AND (oo.estado IN ('Pendiente','En proceso') OR oo.qty_producida<oo.qty_requerida)
          AND oo.estado NOT IN ('Completada','Cancelada')"""
    args = []
    if cat == "terceros":
        sql += " AND oo.es_tercerizada=1"
    elif cat:
        sql += " AND oo.categoria_maquina_id=? AND COALESCE(oo.es_tercerizada,0)=0"
        args.append(cat)
    if estado:
        sql += " AND oo.estado=?"
        args.append(estado)
    if q:
        sql += " AND (o.numero LIKE ? OR oo.nombre LIKE ? OR p.nombre LIKE ? OR p.codigo LIKE ? OR c.razon LIKE ?)"
        args += [f"%{q}%"] * 5
    sql += " ORDER BY COALESCE(o.fecha_entrega,'9999'), o.id, CAST(oo.orden AS INTEGER)"
    rows = query(sql, tuple(args))
    return jsonify([dict(r) for r in rows])


# ── Scheduling de producción ─────────────────────────────────────────────────
# Gantt por máquina. Un "bloque" = una operación de OT, en una máquina, con un
# operario y una jornada de 9 o 12 horas. No modifica la OT ni sus operaciones:
# es solo la planificación; el avance real sigue yendo por Control de producción.
from datetime import datetime as _dt, timedelta as _td

_SCH_JORNADAS = (9, 12)
_SCH_FMT = "%Y-%m-%d %H:%M"


def _sch_parse(v):
    """Acepta 'YYYY-MM-DD HH:MM' o 'YYYY-MM-DDTHH:MM' (con o sin segundos)."""
    v = str(v or "").strip().replace("T", " ")[:16]
    try:
        return _dt.strptime(v, _SCH_FMT)
    except ValueError:
        return None


def _sch_corto(v):
    """'2026-10-14 06:00' -> '14/10 06:00' para los mensajes."""
    return f"{v[8:10]}/{v[5:7]} {v[11:16]}"


# Los bloques de OTs u operaciones cerradas quedan como historial en el Gantt,
# pero ya no ocupan la máquina ni al operario.
_SCH_ACTIVO = " AND o.estado NOT IN ('Completada','Cancelada') AND oo.estado NOT IN ('Completada','Cancelada')"


def _sch_ahora():
    return _dt.now().strftime(_SCH_FMT)


def _sch_qty_futura(oo_id):
    """Cantidad planificada en bloques que todavía no terminaron. Los bloques
    ya pasados no cuentan: lo que se hizo en ellos ya está en qty_producida."""
    r = query("SELECT COALESCE(SUM(cantidad_plan),0) q FROM planificacion WHERE orden_operacion_id=? AND fin>?",
              (oo_id, _sch_ahora()), one=True)
    return float(r["q"] or 0)


def _sch_disponible(oo_id, requerida, falta, excluir_bid=None):
    """Cuánto queda por planificar de una operación: lo que falta producir
    menos lo ya planificado a futuro en otros bloques. None si la operación
    no tiene cantidad requerida (no hay tope que controlar)."""
    if float(requerida or 0) <= 0:
        return None
    r = query("""SELECT COALESCE(SUM(cantidad_plan),0) q FROM planificacion
                 WHERE orden_operacion_id=? AND fin>? AND id<>?""",
              (oo_id, _sch_ahora(), excluir_bid or 0), one=True)
    return round(falta - float(r["q"] or 0), 6)


def _sch_tope_error(v, disponible):
    """Una operación planificada por completo no admite más planificación
    (sí la misma operación de otra OT, que es otra orden_operacion)."""
    if disponible is None:
        return None
    if disponible <= 0.0001:
        return (f"La operación {v['op_desc']} ya está planificada por completo. "
                "Para cambiarla, editá o eliminá sus bloques.")
    if v["qty"] > disponible + 0.0001:
        return (f"La operación {v['op_desc']} solo tiene {disponible:g} u sin planificar "
                f"(pediste {v['qty']:g} u).")
    return None


def _sch_bloque_sql():
    return """SELECT pl.id, pl.orden_operacion_id, pl.maquina_id, pl.empleado_id, pl.inicio, pl.fin,
        pl.jornada_horas, pl.cantidad_plan, pl.obs,
        TRIM(COALESCE(e.apellido,'')||' '||COALESCE(e.nombre,'')) empleado_nombre,
        oo.nombre operacion, oo.orden op_orden, oo.estado op_estado, oo.qty_requerida, oo.qty_producida,
        oo.categoria_maquina_id,
        o.id orden_id, o.numero ot_numero, o.prioridad, o.fecha_entrega, o.estado ot_estado,
        p.codigo producto_codigo, p.nombre producto_nombre, c.razon cliente_nombre
        FROM planificacion pl
        JOIN orden_operaciones oo ON oo.id=pl.orden_operacion_id
        JOIN ordenes o ON o.id=oo.orden_id
        LEFT JOIN empleados e ON e.id=pl.empleado_id
        LEFT JOIN productos p ON p.id=o.producto_id
        LEFT JOIN clientes c ON c.id=o.cliente_id"""


@app.route("/api/scheduling", methods=["GET"])
@login_required()
def sch_get():
    """Datos del Gantt: máquinas (recursos) + bloques que tocan la ventana pedida."""
    desde = request.args.get("desde") or _dt.now().strftime("%Y-%m-%d")
    try:
        dias = max(1, min(60, int(request.args.get("dias") or 7)))
        d0 = _dt.strptime(desde[:10], "%Y-%m-%d")
    except ValueError:
        return jsonify({"error": "Fecha o cantidad de días inválida"}), 400
    d1 = d0 + _td(days=dias)
    maqs = query("""SELECT m.id, m.codigo, m.nombre, m.estado, m.categoria_id,
                    COALESCE(cm.nombre,'Sin sector') grupo
                    FROM maquinas m LEFT JOIN categorias_maquina cm ON cm.id=m.categoria_id
                    ORDER BY COALESCE(cm.nombre,'~'), m.codigo""")
    bl = query(_sch_bloque_sql() + " WHERE pl.inicio < ? AND pl.fin > ? ORDER BY pl.inicio",
               (d1.strftime(_SCH_FMT), d0.strftime(_SCH_FMT)))
    return jsonify({"desde": d0.strftime("%Y-%m-%d"), "dias": dias,
                    "maquinas": [dict(x) for x in maqs], "bloques": [dict(x) for x in bl]})


@app.route("/api/scheduling/pendientes", methods=["GET"])
@login_required()
def sch_pendientes():
    """Operaciones de OTs Pendientes / En proceso (no tercerizadas) con lo ya planificado."""
    rows = query("""SELECT oo.id, oo.orden_id, oo.orden, oo.nombre operacion, oo.estado,
        oo.qty_requerida, oo.qty_producida, oo.categoria_maquina_id, cm.nombre sector,
        oo.maquina_id, COALESCE(oo.tiempo_setup_min,0) setup_min, COALESCE(oo.tiempo_ciclo_seg,0) ciclo_seg,
        o.numero ot_numero, o.prioridad, o.fecha_entrega, o.estado ot_estado,
        p.codigo producto_codigo, p.nombre producto_nombre, c.razon cliente_nombre,
        (SELECT COALESCE(SUM(pl.cantidad_plan),0) FROM planificacion pl WHERE pl.orden_operacion_id=oo.id AND pl.fin>?) qty_planificada,
        (SELECT COUNT(*) FROM planificacion pl WHERE pl.orden_operacion_id=oo.id) bloques
        FROM orden_operaciones oo
        JOIN ordenes o ON o.id=oo.orden_id
        LEFT JOIN categorias_maquina cm ON cm.id=oo.categoria_maquina_id
        LEFT JOIN productos p ON p.id=o.producto_id
        LEFT JOIN clientes c ON c.id=o.cliente_id
        WHERE o.estado IN ('Pendiente','En proceso')
          AND COALESCE(oo.es_tercerizada,0)=0
          AND oo.estado NOT IN ('Completada','Cancelada')
          AND (oo.estado IN ('Pendiente','En proceso') OR oo.qty_producida<oo.qty_requerida)
        ORDER BY COALESCE(o.fecha_entrega,'9999'), o.id, CAST(oo.orden AS INTEGER)""", (_sch_ahora(),))
    return jsonify([dict(r) for r in rows])


def _sch_validar(d, bid=None, emp_actual=None):
    """Valida un bloque. Devuelve (datos, error, avisos). Choques de máquina u
    operario son error (409): una máquina o una persona no pueden estar en dos
    trabajos a la vez."""
    avisos = []
    try:
        oo_id = int(d.get("orden_operacion_id"))
        maq_id = int(d.get("maquina_id"))
    except (TypeError, ValueError):
        return None, ("Falta la operación o la máquina", 400), avisos
    try:
        jor = int(d.get("jornada_horas") or 9)
    except (TypeError, ValueError):
        jor = 0
    if jor not in _SCH_JORNADAS:
        return None, ("La jornada debe ser de 9 o 12 horas", 400), avisos
    ini = _sch_parse(d.get("inicio"))
    if not ini:
        return None, ("Fecha/hora de inicio inválida", 400), avisos
    fin = ini + _td(hours=jor)
    op = query("""SELECT oo.*, o.numero ot_numero, o.fecha_entrega, o.estado ot_estado
                  FROM orden_operaciones oo JOIN ordenes o ON o.id=oo.orden_id WHERE oo.id=?""", (oo_id,), one=True)
    if not op:
        return None, ("Operación no encontrada", 404), avisos
    if op["es_tercerizada"]:
        return None, ("Una operación tercerizada no se programa en una máquina propia", 400), avisos
    if op["estado"] in ("Completada", "Cancelada") or op["ot_estado"] in ("Completada", "Cancelada"):
        return None, ("La operación ya está " + op["estado"].lower() + " y no se puede programar", 400), avisos
    maq = query("SELECT * FROM maquinas WHERE id=?", (maq_id,), one=True)
    if not maq:
        return None, ("Máquina no encontrada", 404), avisos
    emp_id = d.get("empleado_id")
    emp = None
    if emp_id not in (None, "", 0, "0"):
        emp = query("SELECT * FROM empleados WHERE id=?", (int(emp_id),), one=True)
        if not emp:
            return None, ("Operario no encontrado", 404), avisos
        if not emp["activo"]:
            # Un bloque que ya lo tenía asignado se puede seguir editando
            # (p.ej. cambiar la observación) sin perder el operario.
            if emp_actual is None or int(emp_actual) != emp["id"]:
                return None, ("El operario está dado de baja", 400), avisos
            avisos.append("El operario está dado de baja")
    try:
        qty = float(d.get("cantidad_plan") or 0)
    except (TypeError, ValueError):
        return None, ("Cantidad inválida", 400), avisos
    if qty < 0:
        return None, ("La cantidad no puede ser negativa", 400), avisos
    a, b = ini.strftime(_SCH_FMT), fin.strftime(_SCH_FMT)
    ex = bid or 0
    # Choque de máquina
    c = query(_sch_bloque_sql() + " WHERE pl.maquina_id=? AND pl.id<>? AND pl.inicio<? AND pl.fin>?" + _SCH_ACTIVO + " LIMIT 1",
              (maq_id, ex, b, a), one=True)
    if c:
        return None, (f"La máquina {maq['nombre']} ya está ocupada de {_sch_corto(c['inicio'])} a {_sch_corto(c['fin'])} "
                      f"({c['ot_numero']} · {c['operacion']})", 409), avisos
    # Choque de operario
    if emp:
        c = query(_sch_bloque_sql() + " WHERE pl.empleado_id=? AND pl.id<>? AND pl.inicio<? AND pl.fin>?" + _SCH_ACTIVO + " LIMIT 1",
                  (emp["id"], ex, b, a), one=True)
        if c:
            mq = query("SELECT nombre FROM maquinas WHERE id=?", (c["maquina_id"],), one=True)
            return None, (f"{emp['apellido']} {emp['nombre']} ya tiene trabajo de {_sch_corto(c['inicio'])} a {_sch_corto(c['fin'])} "
                          f"en {mq['nombre'] if mq else 'otra máquina'} ({c['ot_numero']})", 409), avisos
        if op["categoria_maquina_id"]:
            hab = query("SELECT 1 FROM empleado_maquinas WHERE empleado_id=? AND categoria_maquina_id=?",
                        (emp["id"], op["categoria_maquina_id"]), one=True)
            if not hab:
                avisos.append("El operario no está habilitado en el sector de esta operación")
    else:
        avisos.append("Sin operario asignado")
    if maq["estado"] != "Operativa":
        avisos.append(f"La máquina está en estado «{maq['estado']}»")
    if op["categoria_maquina_id"] and maq["categoria_id"] and op["categoria_maquina_id"] != maq["categoria_id"]:
        avisos.append("La máquina es de otro sector distinto al de la operación")
    if op["fecha_entrega"] and fin.strftime("%Y-%m-%d") > str(op["fecha_entrega"])[:10]:
        avisos.append(f"Termina después de la fecha de entrega de la OT ({str(op['fecha_entrega'])[:10]})")
    return {"oo": oo_id, "maq": maq_id, "emp": emp["id"] if emp else None, "ini": a, "fin": b,
            "jor": jor, "qty": qty, "obs": (d.get("obs") or "").strip() or None,
            "requerida": float(op["qty_requerida"] or 0),
            "op_desc": f"{op['ot_numero']} · {op['nombre']}",
            "falta": max(0.0, float(op["qty_requerida"] or 0) - float(op["qty_producida"] or 0))}, None, avisos


@app.route("/api/scheduling", methods=["POST"])
@login_required(roles=["admin", "operario"])
def sch_crear():
    d = request.get_json(silent=True) or {}
    # BEGIN IMMEDIATE toma el lock de escritura antes de validar los choques:
    # sin esto, dos altas simultáneas en la misma máquina y horario pasaban
    # las dos la validación y quedaban superpuestas.
    db = get_db()
    if db.in_transaction:
        db.commit()
    db.execute("BEGIN IMMEDIATE")
    try:
        res = _sch_crear(d, db)
        if db.in_transaction:
            db.commit()
        return res
    except:
        db.rollback()
        raise


def _sch_crear(d, db):
    v, err, avisos = _sch_validar(d)
    if err:
        db.rollback()
        return jsonify({"error": err[0]}), err[1]
    tope = _sch_tope_error(v, _sch_disponible(v["oo"], v["requerida"], v["falta"]))
    if tope:
        db.rollback()
        return jsonify({"error": tope}), 400
    # Repetir en los N días siguientes (como el Excel: mismo trabajo, mismo
    # operario, todos los días). Se valida TODO antes de grabar nada.
    try:
        rep = max(0, min(30, int(d.get("repetir") or 0)))
    except (TypeError, ValueError):
        rep = 0
    habiles = bool(d.get("solo_habiles", True))
    # Con cantidad por jornada, las repeticiones se reparten lo que falta
    # producir (descontado lo ya planificado a futuro) en vez de copiar la
    # misma cantidad todos los días: faltaban 40 u, repetir 5 días daba 200 u.
    resta = None
    if rep and v["qty"] > 0:
        resta = v["falta"] - _sch_qty_futura(v["oo"])
        if resta <= 0:
            avisos.append("La operación ya tiene planificado todo lo que falta: no se repitió el bloque")
            rep = 0
            resta = None
        else:
            v["qty"] = min(v["qty"], resta)
            resta -= v["qty"]
    plan = [v]
    cur = _sch_parse(v["ini"])
    while len(plan) < rep + 1 and (resta is None or resta > 0):
        cur = cur + _td(days=1)
        if habiles and cur.weekday() >= 5:
            continue
        dd = dict(d); dd["inicio"] = cur.strftime(_SCH_FMT)
        vv, err, av = _sch_validar(dd)
        if err:
            db.rollback()
            return jsonify({"error": f"Día {cur.strftime('%d/%m')}: {err[0]}"}), err[1]
        for x in av:
            if x not in avisos:
                avisos.append(x)
        if resta is not None:
            vv["qty"] = min(vv["qty"], resta)
            resta -= vv["qty"]
        plan.append(vv)
    if len(plan) < rep + 1:
        avisos.append(f"Con {len(plan)} jornada(s) alcanza para lo que falta producir: no se crearon las otras {rep + 1 - len(plan)}")
    ids = []
    for x in plan:
        ids.append(db.execute("""INSERT INTO planificacion (orden_operacion_id,maquina_id,empleado_id,inicio,fin,jornada_horas,cantidad_plan,obs)
                                 VALUES (?,?,?,?,?,?,?,?)""",
                              (x["oo"], x["maq"], x["emp"], x["ini"], x["fin"], x["jor"], x["qty"], x["obs"])).lastrowid)
    return jsonify({"ok": True, "id": ids[0], "ids": ids, "avisos": avisos}), 201


@app.route("/api/scheduling/<int:bid>", methods=["PUT"])
@login_required(roles=["admin", "operario"])
def sch_editar(bid):
    d = request.get_json(silent=True) or {}
    db = get_db()
    if db.in_transaction:
        db.commit()
    db.execute("BEGIN IMMEDIATE")  # ver sch_crear
    try:
        cur = query("SELECT * FROM planificacion WHERE id=?", (bid,), one=True)
        if not cur:
            db.rollback()
            return jsonify({"error": "Bloque no encontrado"}), 404
        # lo que no se manda queda como estaba (permite mover solo máquina/hora arrastrando)
        base = {"orden_operacion_id": cur["orden_operacion_id"], "maquina_id": cur["maquina_id"],
                "empleado_id": cur["empleado_id"], "inicio": cur["inicio"], "jornada_horas": cur["jornada_horas"],
                "cantidad_plan": cur["cantidad_plan"], "obs": cur["obs"]}
        base.update({k: d[k] for k in base if k in d})
        v, err, avisos = _sch_validar(base, bid, emp_actual=cur["empleado_id"])
        if err:
            db.rollback()
            return jsonify({"error": err[0]}), err[1]
        # Mover el bloque (máquina, hora, operario) siempre se puede; pasarlo a
        # otra operación o subirle la cantidad no puede exceder lo que queda.
        if v["oo"] != cur["orden_operacion_id"] or v["qty"] > float(cur["cantidad_plan"] or 0) + 0.0001:
            tope = _sch_tope_error(v, _sch_disponible(v["oo"], v["requerida"], v["falta"], excluir_bid=bid))
            if tope:
                db.rollback()
                return jsonify({"error": tope}), 400
        db.execute("""UPDATE planificacion SET orden_operacion_id=?,maquina_id=?,empleado_id=?,inicio=?,fin=?,
                      jornada_horas=?,cantidad_plan=?,obs=? WHERE id=?""",
                   (v["oo"], v["maq"], v["emp"], v["ini"], v["fin"], v["jor"], v["qty"], v["obs"], bid))
        db.commit()
    except:
        db.rollback()
        raise
    return jsonify({"ok": True, "avisos": avisos})


@app.route("/api/scheduling/<int:bid>", methods=["DELETE"])
@login_required(roles=["admin", "operario"])
def sch_borrar(bid):
    if not query("SELECT id FROM planificacion WHERE id=?", (bid,), one=True):
        return jsonify({"error": "Bloque no encontrado"}), 404
    execute("DELETE FROM planificacion WHERE id=?", (bid,))
    return jsonify({"ok": True})

"""HMI de prueba (/hmi-test): sesiones, ciclos y novedad resultante."""
from .nucleo import (app, BASE_DIR, datetime, execute, jsonify, login_required, os, query,
    request, session, transaccion)

# ── HMI de máquina — MÓDULO DE PRUEBA ─────────────────────────────────────────
# Estación táctil junto a la máquina (huella + contador de piezas). La huella
# y los pulsos del contador se SIMULAN en el navegador; lo que sí es real es
# el circuito del lado del servidor: la sesión de trabajo, cada ciclo como
# evento con uid único (un reenvío no suma dos veces) y, si el usuario lo
# pide al final, la novedad real por POST /api/novedades con sus reglas.

def _hmi_trabajado(s):
    """Segundos trabajados: lo acumulado más el tramo en curso si no está en pausa."""
    seg = float(s["trabajado_seg"] or 0)
    if s["desde"]:
        try:
            seg += max(0.0, (datetime.now() - datetime.strptime(s["desde"], "%Y-%m-%d %H:%M:%S")).total_seconds())
        except ValueError:
            pass
    return seg


def _hmi_sesion_dict(sid):
    s = query("""SELECT s.*, e.nombre emp_nombre, e.apellido emp_apellido, e.legajo,
            o.numero ot_numero, oo.nombre op_nombre, oo.orden paso,
            oo.qty_requerida, oo.qty_producida, oo.tiempo_ciclo_seg,
            p.codigo pieza_codigo, p.nombre pieza_nombre, m.codigo maquina_codigo,
            n.numero novedad_numero,
            (SELECT MAX(recibido) FROM hmi_eventos WHERE sesion_id=s.id) ultimo_evento
        FROM hmi_sesiones s
        JOIN empleados e ON e.id=s.empleado_id
        JOIN ordenes o ON o.id=s.orden_id
        JOIN orden_operaciones oo ON oo.id=s.orden_operacion_id
        LEFT JOIN productos p ON p.id=o.producto_id
        LEFT JOIN maquinas m ON m.id=s.maquina_id
        LEFT JOIN novedades_produccion n ON n.id=s.novedad_id
        WHERE s.id=?""", (sid,), one=True)
    if not s:
        return None
    d = dict(s)
    d["trabajado_seg"] = round(_hmi_trabajado(s), 1)
    return d


def _hmi_sesion_o_error(sid, estados=None):
    s = query("SELECT * FROM hmi_sesiones WHERE id=?", (sid,), one=True)
    if not s:
        return None, (jsonify({"error": "Sesión no encontrada"}), 404)
    if estados and s["estado"] not in estados:
        return None, (jsonify({"error": f"La sesión está {s['estado']}", "estado": s["estado"]}), 409)
    return s, None


@app.route("/hmi-test")
@login_required(roles=["admin", "operario"])
def hmi_test():
    # Se sirve el archivo tal cual (sin Jinja): toma todo por /api/hmi_test/*.
    with open(os.path.join(BASE_DIR, "templates", "hmi_test.html"), encoding="utf-8") as f:
        return f.read(), 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/api/hmi_test/datos")
@login_required(roles=["admin", "operario"])
def hmi_test_datos():
    """Máquina de la terminal, empleados activos, operaciones propias abiertas
    de OT Pendiente / En proceso (todas si la máquina no tiene ninguna
    asignada, avisando con por_maquina=False) y la sesión abierta, si hay."""
    cod = (request.args.get("maquina") or "T16").strip()
    maq = query("SELECT id, codigo, nombre, marca, modelo FROM maquinas WHERE codigo=?", (cod,), one=True)
    empleados = [dict(r) for r in query("""SELECT id, legajo, nombre, apellido, cargo, turno
        FROM empleados WHERE activo=1 ORDER BY apellido, nombre""")]
    sql = """SELECT oo.id, oo.orden_id, oo.orden paso, oo.nombre, oo.estado,
            oo.qty_requerida, oo.qty_producida, oo.tiempo_ciclo_seg, oo.maquina_id,
            o.numero ot_numero, o.estado ot_estado, o.fecha_entrega,
            p.codigo pieza_codigo, p.nombre pieza_nombre
        FROM orden_operaciones oo
        JOIN ordenes o ON o.id=oo.orden_id
        LEFT JOIN productos p ON p.id=o.producto_id
        WHERE o.estado IN ('Pendiente','En proceso')
          AND COALESCE(oo.es_tercerizada,0)=0
          AND oo.estado!='Completada'"""
    ops = []
    por_maquina = False
    if maq:
        ops = [dict(r) for r in query(sql + " AND oo.maquina_id=? ORDER BY o.numero, CAST(oo.orden AS REAL)", (maq["id"],))]
        por_maquina = bool(ops)
    if not ops:
        ops = [dict(r) for r in query(sql + " ORDER BY o.numero, CAST(oo.orden AS REAL)")]
    activa = None
    if maq:
        r = query("""SELECT id FROM hmi_sesiones WHERE maquina_id=? AND estado!='Finalizada'
            ORDER BY id DESC LIMIT 1""", (maq["id"],), one=True)
        activa = _hmi_sesion_dict(r["id"]) if r else None
    return jsonify({"maquina": dict(maq) if maq else {"codigo": cod, "nombre": "(no encontrada)"},
                    "por_maquina": por_maquina, "empleados": empleados, "operaciones": ops,
                    "sesion_activa": activa,
                    "hora_servidor": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})


@app.route("/api/hmi_test/sesiones", methods=["POST"])
@login_required(roles=["admin", "operario"])
def hmi_test_iniciar():
    d = request.get_json(silent=True) or {}
    maq = query("SELECT id FROM maquinas WHERE codigo=?", ((d.get("maquina") or "").strip(),), one=True)
    if not maq:
        return jsonify({"error": "Máquina no encontrada"}), 400
    emp = query("SELECT id FROM empleados WHERE id=? AND activo=1", (d.get("empleado_id"),), one=True)
    if not emp:
        return jsonify({"error": "Empleado no encontrado o inactivo"}), 400
    op = query("""SELECT oo.id, oo.orden_id, oo.estado, oo.es_tercerizada, o.estado ot_estado
        FROM orden_operaciones oo JOIN ordenes o ON o.id=oo.orden_id WHERE oo.id=?""",
        (d.get("orden_operacion_id"),), one=True)
    if not op:
        return jsonify({"error": "Operación no encontrada"}), 400
    if op["ot_estado"] not in ("Pendiente", "En proceso"):
        return jsonify({"error": f"La OT está {op['ot_estado']}"}), 400
    if op["es_tercerizada"]:
        return jsonify({"error": "La operación es tercerizada: no se trabaja en esta máquina"}), 400
    if op["estado"] == "Completada":
        return jsonify({"error": "La operación ya está Completada"}), 400
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with transaccion():
        abierta = query("""SELECT id FROM hmi_sesiones WHERE maquina_id=? AND estado!='Finalizada'""",
            (maq["id"],), one=True)
        if abierta:
            return jsonify({"error": "Ya hay un trabajo abierto en esta máquina", "sesion_id": abierta["id"]}), 409
        sid = execute("""INSERT INTO hmi_sesiones (maquina_id, empleado_id, orden_id, orden_operacion_id,
                estado, inicio, desde, creado_por) VALUES (?,?,?,?, 'Produciendo', ?, ?, ?)""",
            (maq["id"], emp["id"], op["orden_id"], op["id"], ahora, ahora, session["user_id"]))
    return jsonify(_hmi_sesion_dict(sid)), 201


@app.route("/api/hmi_test/sesiones/<int:sid>")
@login_required(roles=["admin", "operario"])
def hmi_test_sesion(sid):
    s = _hmi_sesion_dict(sid)
    return (jsonify(s), 200) if s else (jsonify({"error": "Sesión no encontrada"}), 404)


@app.route("/api/hmi_test/sesiones/<int:sid>/eventos", methods=["POST"])
@login_required(roles=["admin", "operario"])
def hmi_test_evento(sid):
    """Un ciclo terminado. Idempotente por (sesión, uid): si el mismo evento
    llega dos veces (reintento tras un corte), el segundo no suma."""
    d = request.get_json(silent=True) or {}
    uid = str(d.get("uid") or "").strip()
    if not uid or len(uid) > 80:
        return jsonify({"error": "uid requerido"}), 400
    with transaccion():
        s, err = _hmi_sesion_o_error(sid)
        if err:
            return err
        ya = query("SELECT 1 FROM hmi_eventos WHERE sesion_id=? AND uid=?", (sid, uid), one=True)
        if ya:
            execute("UPDATE hmi_sesiones SET duplicados=duplicados+1 WHERE id=?", (sid,))
            duplicado = True
        elif s["estado"] != "Produciendo":
            return jsonify({"error": f"La sesión está {s['estado']}: el ciclo no se cuenta",
                            "estado": s["estado"]}), 409
        else:
            execute("INSERT INTO hmi_eventos (sesion_id, uid, seq, ts_origen) VALUES (?,?,?,?)",
                (sid, uid, d.get("seq"), d.get("ts")))
            execute("UPDATE hmi_sesiones SET ciclos=ciclos+1 WHERE id=?", (sid,))
            duplicado = False
    r = query("SELECT ciclos, duplicados FROM hmi_sesiones WHERE id=?", (sid,), one=True)
    return jsonify({"ok": True, "duplicado": duplicado, "ciclos": r["ciclos"], "duplicados": r["duplicados"]})


@app.route("/api/hmi_test/sesiones/<int:sid>/pausa", methods=["POST"])
@login_required(roles=["admin", "operario"])
def hmi_test_pausa(sid):
    with transaccion():
        s, err = _hmi_sesion_o_error(sid, ("Produciendo",))
        if err:
            return err
        execute("UPDATE hmi_sesiones SET estado='Pausada', trabajado_seg=?, desde=NULL WHERE id=?",
            (_hmi_trabajado(s), sid))
    return jsonify(_hmi_sesion_dict(sid))


@app.route("/api/hmi_test/sesiones/<int:sid>/reanudar", methods=["POST"])
@login_required(roles=["admin", "operario"])
def hmi_test_reanudar(sid):
    with transaccion():
        s, err = _hmi_sesion_o_error(sid, ("Pausada",))
        if err:
            return err
        execute("UPDATE hmi_sesiones SET estado='Produciendo', desde=? WHERE id=?",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), sid))
    return jsonify(_hmi_sesion_dict(sid))


@app.route("/api/hmi_test/sesiones/<int:sid>/finalizar", methods=["POST"])
@login_required(roles=["admin", "operario"])
def hmi_test_finalizar(sid):
    d = request.get_json(silent=True) or {}
    try:
        nok = int(d.get("nok") or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "NO OK inválido"}), 400
    with transaccion():
        s, err = _hmi_sesion_o_error(sid, ("Produciendo", "Pausada"))
        if err:
            return err
        if nok < 0 or nok > int(s["ciclos"]):
            return jsonify({"error": f"NO OK debe estar entre 0 y {s['ciclos']}"}), 400
        execute("""UPDATE hmi_sesiones SET estado='Finalizada', fin=?, trabajado_seg=?, desde=NULL, nok=?
            WHERE id=?""", (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), _hmi_trabajado(s), nok, sid))
    return jsonify(_hmi_sesion_dict(sid))


@app.route("/api/hmi_test/sesiones/<int:sid>/novedad", methods=["POST"])
@login_required(roles=["admin", "operario"])
def hmi_test_vincular_novedad(sid):
    """Anota en la sesión la novedad real que se creó con POST /api/novedades."""
    d = request.get_json(silent=True) or {}
    s, err = _hmi_sesion_o_error(sid, ("Finalizada",))
    if err:
        return err
    n = query("SELECT id, orden_operacion_id FROM novedades_produccion WHERE id=?", (d.get("novedad_id"),), one=True)
    if not n or n["orden_operacion_id"] != s["orden_operacion_id"]:
        return jsonify({"error": "La novedad no corresponde a esta sesión"}), 400
    execute("UPDATE hmi_sesiones SET novedad_id=? WHERE id=? AND novedad_id IS NULL", (n["id"], sid))
    return jsonify(_hmi_sesion_dict(sid))

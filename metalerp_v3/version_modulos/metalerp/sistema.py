"""Bitácora de auditoría (consulta) y registro de cambios del sistema."""
from .nucleo import (_aud_enmascarar, _json, app, datetime, execute, jsonify,
    login_required, puede_ver_monetario, query, request, session)

# ── Bitácora de auditoría — API (solo lectura, solo admin) ───────────────────
AUDITORIA_ACCIONES = ("alta", "modificacion", "baja")


def _aud_cargar(txt):
    if not txt:
        return {}
    try:
        v = _json.loads(txt)
        return v if isinstance(v, dict) else {}
    except Exception:
        return {}


def _aud_cambios(fila):
    """Comparación campo por campo entre el valor anterior y el nuevo."""
    antes, despues = _aud_cargar(fila["valores_antes"]), _aud_cargar(fila["valores_despues"])
    if not puede_ver_monetario():
        antes, despues = _aud_enmascarar(antes), _aud_enmascarar(despues)
    campos = sorted(set(antes) | set(despues))
    return [{"campo": c, "antes": antes.get(c), "despues": despues.get(c)} for c in campos]


def _aud_filtros():
    """WHERE + parámetros armados con los filtros de la query string."""
    w, p = ["1=1"], []
    desde = (request.args.get("desde") or "").strip()
    hasta = (request.args.get("hasta") or "").strip()
    origen = (request.args.get("origen") or "").strip()
    actor = (request.args.get("usuario") or "").strip()
    entidad = (request.args.get("entidad") or "").strip()
    accion = (request.args.get("accion") or "").strip()
    q = (request.args.get("q") or "").strip()
    if desde:
        w.append("fecha >= ?"); p.append(desde + " 00:00:00")
    if hasta:
        w.append("fecha <= ?"); p.append(hasta + " 23:59:59")
    if origen in ("usuario", "sistema"):
        w.append("origen = ?"); p.append(origen)
    if actor:
        w.append("actor = ?"); p.append(actor)
    if entidad:
        w.append("entidad = ?"); p.append(entidad)
    if accion in AUDITORIA_ACCIONES:
        w.append("accion = ?"); p.append(accion)
    if q:
        if puede_ver_monetario():
            w.append("(entidad LIKE ? OR actor LIKE ? OR IFNULL(registro_id,'') LIKE ?"
                     " OR IFNULL(valores_antes,'') LIKE ? OR IFNULL(valores_despues,'') LIKE ?)")
            p += [f"%{q}%"] * 5
        else:
            # Buscar dentro de los JSON permitiría adivinar importes probando
            # números hasta que un asiento aparezca: para el restringido la
            # búsqueda libre se limita a los metadatos del asiento.
            w.append("(entidad LIKE ? OR actor LIKE ? OR IFNULL(registro_id,'') LIKE ?)")
            p += [f"%{q}%"] * 3
    return " AND ".join(w), p


@app.route("/api/auditoria")
@login_required(roles=["admin"])
def get_auditoria():
    where, params = _aud_filtros()
    try:
        pagina = max(1, int(request.args.get("pagina", 1)))
    except (TypeError, ValueError):
        pagina = 1
    try:
        por_pagina = int(request.args.get("por_pagina", 50))
    except (TypeError, ValueError):
        por_pagina = 50
    por_pagina = min(200, max(10, por_pagina))
    total = query(f"SELECT COUNT(*) c FROM auditoria WHERE {where}", params, one=True)["c"]
    filas = query(
        f"SELECT * FROM auditoria WHERE {where} ORDER BY fecha DESC, id DESC LIMIT ? OFFSET ?",
        (*params, por_pagina, (pagina - 1) * por_pagina))
    rows = []
    for f in filas:
        cambios = _aud_cambios(f)
        rows.append({
            "id": f["id"], "fecha": f["fecha"], "origen": f["origen"],
            "usuario_id": f["usuario_id"], "actor": f["actor"],
            "entidad": f["entidad"], "registro_id": f["registro_id"],
            "accion": f["accion"], "ruta": f["ruta"],
            "campos": [c["campo"] for c in cambios],
        })
    return jsonify({
        "total": total, "pagina": pagina, "por_pagina": por_pagina,
        "paginas": max(1, -(-total // por_pagina)), "rows": rows,
    })


@app.route("/api/auditoria/opciones")
@login_required(roles=["admin"])
def get_auditoria_opciones():
    return jsonify({
        "entidades": [r["entidad"] for r in query("SELECT DISTINCT entidad FROM auditoria ORDER BY entidad")],
        "usuarios": [r["actor"] for r in query("SELECT DISTINCT actor FROM auditoria ORDER BY actor")],
        "acciones": list(AUDITORIA_ACCIONES),
        "origenes": ["usuario", "sistema"],
    })


@app.route("/api/auditoria/<int:aid>")
@login_required(roles=["admin"])
def get_auditoria_detalle(aid):
    f = query("SELECT * FROM auditoria WHERE id=?", (aid,), one=True)
    if not f:
        return jsonify({"error": "Asiento no encontrado"}), 404
    d = dict(f)
    d["cambios"] = _aud_cambios(f)
    d.pop("valores_antes", None)
    d.pop("valores_despues", None)
    return jsonify(d)


# ── Registro de cambios del sistema (solo admin) ─────────────────────────────
# Historial de los cambios de código hechos en MetalERP, cargado a mano.
# Obligatorios: fecha y descripción. Todo lo demás es opcional.
CAMBIOS_CAMPOS_TEXTO = ("descripcion", "tipo", "modulo", "detalle", "motivo",
                        "objetivo", "archivos", "autor", "referencia")


def _cambio_desde_request():
    d = request.get_json(silent=True) or {}
    datos = {}
    for c in CAMBIOS_CAMPOS_TEXTO:
        v = d.get(c)
        v = str(v).strip() if v is not None else ""
        datos[c] = v or None
    fecha = str(d.get("fecha") or "").strip()[:10]
    try:
        datetime.strptime(fecha, "%Y-%m-%d")
    except ValueError:
        return None, "La fecha es obligatoria (formato AAAA-MM-DD)."
    if not datos["descripcion"]:
        return None, "La descripción es obligatoria."
    datos["fecha"] = fecha
    return datos, None


@app.route("/api/registro-cambios")
@login_required(roles=["admin"])
def get_registro_cambios():
    filas = query("""SELECT rc.*, u.nombre AS creado_por_nombre FROM registro_cambios rc
                     LEFT JOIN usuarios u ON u.id=rc.creado_por
                     ORDER BY rc.fecha DESC, rc.id DESC""")
    return jsonify([dict(f) for f in filas])


@app.route("/api/registro-cambios", methods=["POST"])
@login_required(roles=["admin"])
def crear_registro_cambio():
    datos, err = _cambio_desde_request()
    if err:
        return jsonify({"error": err}), 400
    cols = ["fecha", *CAMBIOS_CAMPOS_TEXTO, "creado_por"]
    vals = [datos["fecha"], *[datos[c] for c in CAMBIOS_CAMPOS_TEXTO], session.get("user_id")]
    nid = execute(f"INSERT INTO registro_cambios ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", vals)
    return jsonify({"ok": True, "id": nid})


@app.route("/api/registro-cambios/<int:cid>", methods=["PUT"])
@login_required(roles=["admin"])
def editar_registro_cambio(cid):
    if not query("SELECT 1 FROM registro_cambios WHERE id=?", (cid,), one=True):
        return jsonify({"error": "Cambio no encontrado"}), 404
    datos, err = _cambio_desde_request()
    if err:
        return jsonify({"error": err}), 400
    cols = ["fecha", *CAMBIOS_CAMPOS_TEXTO]
    execute(f"""UPDATE registro_cambios SET {', '.join(c + '=?' for c in cols)},
                actualizado_en=datetime('now','localtime') WHERE id=?""",
            [datos[c] for c in cols] + [cid])
    return jsonify({"ok": True})


@app.route("/api/registro-cambios/<int:cid>", methods=["DELETE"])
@login_required(roles=["admin"])
def borrar_registro_cambio(cid):
    execute("DELETE FROM registro_cambios WHERE id=?", (cid,))
    return jsonify({"ok": True})

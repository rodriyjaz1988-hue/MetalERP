"""Lotes de stock y trazabilidad (remito, lote, OT, OTT, materia prima)."""
from .nucleo import (app, auditoria_proceso, datetime, execute, jsonify, login_required,
    query, request, session, siguiente_numero)

# ── Lotes ─────────────────────────────────────────────────────────────────────
def _gen_lote_numero():
    """Genera número de lote correlativo por año: LOTE-2026-0001"""
    return siguiente_numero("lotes", f"LOTE-{datetime.now().year}-", 4)

@app.route("/api/lotes", methods=["GET"])
@login_required()
def get_lotes():
    material_id = request.args.get("material_id")
    estado = request.args.get("estado")
    proveedor_id = request.args.get("proveedor_id")
    cliente_id = request.args.get("cliente_id")
    sql = """SELECT l.*,m.codigo mat_codigo,m.descripcion mat_descripcion,m.unidad,
        m.categoria,
        MAX(0, l.cantidad_activa - COALESCE(l.cantidad_reservada,0)) AS disponible_libre,
        p.razon proveedor_nombre, u.nombre creado_por_nombre,
        cl.id cliente_id, cl.razon cliente_nombre
        FROM lotes l
        JOIN materiales m ON m.id=l.material_id
        LEFT JOIN proveedores p ON p.id=l.proveedor_id
        LEFT JOIN usuarios u ON u.id=l.creado_por
        LEFT JOIN productos pr2 ON pr2.id=m.producto_id
        LEFT JOIN clientes cl ON cl.id=pr2.cliente_id"""
    conds, params = [], []
    if material_id:
        conds.append("l.material_id=?"); params.append(material_id)
    if estado:
        conds.append("l.estado=?"); params.append(estado)
    elif "estado" not in request.args:
        # Exclude Agotado only when no estado filter is set at all (default view)
        # When cliente sends ?estado= (Todos los estados), show everything including Agotado
        conds.append("l.estado != 'Agotado'")
    if proveedor_id:
        conds.append("l.proveedor_id=?"); params.append(proveedor_id)
    if cliente_id:
        conds.append("cl.id=?"); params.append(cliente_id)
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    sql += " ORDER BY l.id DESC"
    return jsonify([dict(r) for r in query(sql, params)])

@app.route("/api/lotes", methods=["POST"])
@login_required(roles=["admin","almacen"])
def create_lote():
    d = request.json
    if not d.get("material_id") or not d.get("cantidad"):
        return jsonify({"error": "Material y cantidad requeridos"}), 400
    mat = query("SELECT categoria FROM materiales WHERE id=?", (d["material_id"],), one=True)
    if not mat:
        return jsonify({"error": "Material no encontrado"}), 404
    if mat["categoria"] != "Material":
        return jsonify({"error": "Solo se pueden crear lotes para artículos de categoría Material"}), 400
    numero = _gen_lote_numero()
    qty = float(d["cantidad"])
    lid = execute("""INSERT INTO lotes
        (numero,material_id,cantidad_original,cantidad_disponible,proveedor_id,
         referencia_proveedor,certificado,estado,obs,creado_por,stock_computado)
        VALUES (?,?,?,?,?,?,?,?,?,?,1)""",
        (numero, d["material_id"], qty, qty,
         d.get("proveedor_id"), d.get("referencia_proveedor"),
         d.get("certificado"), "Ingresado", d.get("obs"), session["user_id"]))
    # El material está en el depósito: entra a inventario al ingresarlo.
    execute("""UPDATE materiales SET stock=stock+?, actualizado=datetime('now','localtime')
        WHERE id=?""", (qty, d["material_id"]))
    # El stock del material representa SOLO lo Aprobado por Calidad. Un lote
    # recién ingresado queda en estado "Ingresado" con cantidad_activa=0
    # (nada aprobado todavía), así que NO se suma a stock acá. El stock se
    # actualiza recién en update_lote(), cuando Calidad clasifica cantidades
    # como Aprobado/Rechazado/Pendiente. Se deja igual un movimiento
    # informativo para trazabilidad, aclarando que todavía no impacta stock.
    execute("""INSERT INTO movimientos (material_id,lote_id,tipo,cantidad,referencia,usuario_id)
        VALUES (?,?,?,?,?,?)""",
        (d["material_id"], lid, "ingreso", qty,
         f"Ingreso lote {numero} — {d.get('referencia_proveedor','')} (pendiente de clasificación, no computa a stock)",
         session["user_id"]))
    return jsonify({"ok": True, "id": lid, "numero": numero}), 201

@auditoria_proceso("sincronización retorno OTT → operación")
def _sync_ott_retorno_a_operacion(lote_id):
    """Si este lote es el lote de retorno de una operación tercerizada
    INTERMEDIA (OTT con lote_retorno_id=lote_id, es_ultimo_nivel=0), actualiza
    qty_producida de la operación siguiente con lo YA APROBADO del lote de
    forma incremental (aprobás 30 → se puede usar 30; aprobás 10 más → 40),
    aunque el lote todavía tenga piezas pendientes de recibir del proveedor
    o pendientes de clasificar.

    IMPORTANTE: esta función NUNCA marca la operación ni la OTT como
    Completada por sí sola, aunque lo aprobado ya alcance la cantidad
    requerida — eso quedó a propósito como un paso MANUAL: el usuario tiene
    que confirmarlo desde OTT con el botón "Completar" (ver ott_completar).
    Antes esto se auto-completaba apenas se llegaba a la cantidad requerida,
    lo cual traía dos problemas: 1) no daba lugar a que alguien revise/decida
    antes de cerrar (ej. dar la OTT por completada con menos de lo pedido si
    el faltante se da de baja), y 2) al recalcularse qty_producida en cada
    aprobación, una OTT que ya se había dejado abierta a propósito podía
    terminar "completándose sola" en un aprobado posterior sin que nadie lo
    pidiera. Acá solo se actualiza qty_producida (lo ya aprobado, para que
    la operación siguiente pueda ir cargando novedades de forma incremental
    — ver _tope_terc_previa); el pase a Completada queda 100% en manos del
    botón "Completar" de OTT. Es idempotente."""
    ott = query("""SELECT ott.*, oo.id oo_id, oo.estado oo_estado, oo.qty_requerida,
            oo.orden_id oo_orden_id, oo.orden oo_orden
        FROM ordenes_tercerizado ott
        LEFT JOIN orden_operaciones oo ON oo.id=ott.operacion_id
        WHERE ott.lote_retorno_id=? AND ott.es_ultimo_nivel=0""", (lote_id,), one=True)
    if not ott or not ott["oo_id"]:
        return
    lote = query("""SELECT id,numero,material_id,cantidad_activa,cantidad_rechazada,
            cantidad_disponible,cantidad_reservada,estado
        FROM lotes WHERE id=?""", (lote_id,), one=True)
    if not lote:
        return

    # Lo aprobado ACUMULADO de este lote: lo que sigue en el lote más lo que
    # ya se consumió para esta OT. Hay que sumar lo consumido porque el
    # semielaborado lo consume la operación siguiente (ver _materiales_ott_pendientes_por_operacion); si
    # se mirara solo cantidad_activa, una segunda aprobación parcial pisaría
    # qty_producida con el delta nuevo en vez del total.
    consumido = 0.0
    if ott["ot_origen_id"]:
        row = query("""SELECT COALESCE(cantidad_consumida,0) c FROM orden_lotes
            WHERE orden_id=? AND lote_id=?""",
            (ott["ot_origen_id"], lote_id), one=True)
        consumido = float(row["c"] or 0) if row else 0.0
    aprobado = float(lote["cantidad_activa"] or 0) + consumido
    if aprobado <= 0:
        return  # todavía no hay nada aprobado

    # Solo actualiza qty_producida (lo ya aprobado hasta ahora), sin tocar
    # el estado de la operación ni de la OTT — el cierre es manual, ver
    # ott_completar.
    if ott["oo_estado"] != "Completada":
        usa_cajones = _ot_usa_cajones(ott["oo_orden_id"])
        execute("UPDATE orden_operaciones SET qty_producida=? WHERE id=?",
            (aprobado, ott["oo_id"]))
        consumir_herramientas_op(ott["oo_id"])
        _sync_cajones_op_tercerizada(ott["oo_id"], usa_cajones)


def _consumir_pse_sobrante_ot(oid):
    """Al completar la OT, da de baja el semielaborado aprobado que quedó en
    los lotes de retorno de sus OTT intermedias sin que la operación
    siguiente lo consumiera (piezas que no siguieron la ruta). Antes esto se
    hacía al cerrar cada OTT, pero ahí todavía hacía falta para la operación
    siguiente."""
    for ott in query("""SELECT ott.id, ott.numero, ott.lote_retorno_id FROM ordenes_tercerizado ott
            WHERE ott.ot_origen_id=? AND ott.es_ultimo_nivel=0
              AND ott.lote_retorno_id IS NOT NULL""", (oid,)):
        lote = query("""SELECT id,numero,material_id,cantidad_activa FROM lotes WHERE id=?""",
            (ott["lote_retorno_id"],), one=True)
        if not lote:
            continue
        sobrante = float(lote["cantidad_activa"] or 0)
        if sobrante <= 0.0001:
            continue
        execute("""UPDATE lotes SET
                cantidad_activa=MAX(0, cantidad_activa-?),
                cantidad_disponible=MAX(0, cantidad_disponible-?),
                cantidad_reservada=MAX(0, COALESCE(cantidad_reservada,0)-?),
                estado=CASE WHEN cantidad_disponible-? <= 0.0001 THEN 'Agotado' ELSE estado END
            WHERE id=?""", (sobrante, sobrante, sobrante, sobrante, lote["id"]))
        execute("""UPDATE materiales SET stock=MAX(0, stock-?),
                actualizado=datetime('now','localtime') WHERE id=?""",
            (sobrante, lote["material_id"]))
        execute("""UPDATE orden_lotes SET cantidad_consumida=COALESCE(cantidad_consumida,0)+?
            WHERE orden_id=? AND lote_id=?""", (sobrante, oid, lote["id"]))
        execute("""INSERT INTO movimientos (material_id,lote_id,tipo,cantidad,referencia,usuario_id)
            VALUES (?,?,'salida',?,?,?)""",
            (lote["material_id"], lote["id"], sobrante,
             f"Baja del semielaborado sobrante al completar la OT — OTT {ott['numero']} "
             f"— Lote {lote['numero']}", session.get("user_id")))


@app.route("/api/lotes/<int:lid>", methods=["PUT"])
@login_required(roles=["admin","almacen","calidad"])
def update_lote(lid):
    d = request.json
    lote = query("SELECT * FROM lotes WHERE id=?", (lid,), one=True)
    if not lote: return jsonify({"error": "Lote no encontrado"}), 404

    if query("SELECT 1 FROM cajones WHERE lote_id=? AND orden_id IS NOT NULL LIMIT 1", (lid,), one=True):
        if ("cantidad_aprobada" in d or "cantidad_rechazada" in d
                or ("estado" in d and d.get("estado") != lote["estado"])):
            return jsonify({"error": "Este lote tiene cajones: Calidad libera o rechaza cada cajón "
                                     "desde la lista de cajones del lote."}), 400
        execute("UPDATE lotes SET referencia_proveedor=?,certificado=?,obs=? WHERE id=?",
            (d.get("referencia_proveedor", lote["referencia_proveedor"]),
             d.get("certificado", lote["certificado"]), d.get("obs", lote["obs"]), lid))
        return jsonify({"ok": True, "numero_lote": lote["numero"], "estado": lote["estado"]})

    disp = float(lote["cantidad_disponible"])

    # ── Modelo nuevo: se editan los 3 valores de la partición del lote
    # (Aprobado / Rechazado / Pendiente) de forma absoluta, no incremental.
    # Esto evita que aprobar y rechazar por separado sumen más que el total
    # disponible, y permite corregir un dato mal cargado simplemente
    # reabriendo el lote y volviendo a fijar los valores correctos.
    if "cantidad_aprobada" in d or "cantidad_rechazada" in d:
        aprobado = float(d.get("cantidad_aprobada", lote["cantidad_activa"] or 0) or 0)
        rechazado = float(d.get("cantidad_rechazada", lote["cantidad_rechazada"] or 0) or 0)
        if aprobado < 0 or rechazado < 0:
            return jsonify({"error": "Las cantidades no pueden ser negativas"}), 400
        if aprobado + rechazado > disp + 0.001:
            return jsonify({"error": "Aprobado (%.2f) + Rechazado (%.2f) no puede superar el total disponible (%.2f)"
                % (aprobado, rechazado, disp)}), 400
        # Lo aprobado no puede quedar por debajo de lo que ya está reservado
        # para OTs (asignado desde "Lotes asignados" o retorno de OTT): la
        # reserva quedaría apuntando a piezas que ya no están aprobadas.
        # (lo que pase a Rechazado libera reserva en la misma medida, ver abajo)
        reservado_lote = max(0.0, float(lote["cantidad_reservada"] or 0)
                             - max(0.0, rechazado - float(lote["cantidad_rechazada"] or 0)))
        if aprobado < float(lote["cantidad_activa"] or 0) and aprobado + 0.001 < reservado_lote:
            return jsonify({"error": "No se puede bajar el aprobado a %.2f: hay %.2f reservadas para OTs en este lote. "
                "Liberá esa asignación desde Órdenes de trabajo → Lotes asignados antes de corregir."
                % (aprobado, reservado_lote)}), 400

        pendiente = max(0.0, disp - aprobado - rechazado)
        if disp <= 0.0001:
            estado_lote = "Agotado"
        elif pendiente <= 0.001 and aprobado >= rechazado:
            estado_lote = "Aprobado"
        elif pendiente <= 0.001 and rechazado > aprobado:
            estado_lote = "Rechazado"
        else:
            estado_lote = "Ingresado"  # queda algo pendiente de analizar (parcial)

        execute("""UPDATE lotes SET estado=?,cantidad_activa=?,cantidad_rechazada=?,
            referencia_proveedor=?,certificado=?,obs=? WHERE id=?""",
            (estado_lote, aprobado, rechazado,
             d.get("referencia_proveedor", lote["referencia_proveedor"]),
             d.get("certificado", lote["certificado"]),
             d.get("obs", lote["obs"]), lid))
        execute("""INSERT INTO movimientos (material_id,lote_id,tipo,cantidad,referencia,usuario_id)
            VALUES (?,?,?,?,?,?)""",
            (lote["material_id"], lid, "ajuste", disp,
             ("Edición liberación → Aprobado:%.2f Rechazado:%.2f Pendiente:%.2f | Lote %s"
                % (aprobado, rechazado, pendiente, lote["numero"]))
             + (" | Obs: " + d.get("obs") if d.get("obs") else ""),
             session["user_id"]))
        # ── Stock y clasificación de Calidad ──────────────────────────────
        # Lotes del modelo viejo (stock_computado=0): el stock del material
        # representa solo lo Aprobado de esos lotes, así que el ajuste se
        # calcula por la variación de cantidad_aprobada (cantidad_activa)
        # respecto del valor previo. Si aprobado sube, entra a stock; si baja
        # (ej. se corrige una clasificación), sale de stock.
        # Lotes con stock_computado=1 (los actuales): sus piezas ya están en
        # stock desde que entraron al depósito, aprobadas o no; clasificarlas
        # no mueve stock (ver abajo). Lo rechazado sale al devolverse.
        aprobado_anterior = float(lote["cantidad_activa"] or 0)
        delta_aprobado = aprobado - aprobado_anterior
        # Si las piezas ya entraron a inventario al entrar al deposito
        # (stock_computado=1), clasificarlas no mueve nada: estan fisicamente
        # ahi igual, aprobadas o no.
        if bool(lote["stock_computado"] if "stock_computado" in lote.keys() else 0):
            delta_aprobado = 0.0
        if abs(delta_aprobado) > 0.0001:
            execute("""UPDATE materiales SET stock=MAX(0,stock+?),
                actualizado=datetime('now','localtime') WHERE id=?""",
                (delta_aprobado, lote["material_id"]))
            execute("""INSERT INTO movimientos (material_id,lote_id,tipo,cantidad,referencia,usuario_id)
                VALUES (?,?,?,?,?,?)""",
                (lote["material_id"], lid,
                 "entrada" if delta_aprobado > 0 else "salida",
                 abs(delta_aprobado),
                 (f"Aprobación de lote {lote['numero']} — ingreso a inventario"
                  if delta_aprobado > 0 else
                  f"Corrección de aprobación — Lote {lote['numero']} (baja de inventario)"),
                 session["user_id"]))
        auto_generar_sc_bajo_stock(lote["material_id"], f"ajuste de lote {lote['numero']} (aprobado/rechazado)")
        # ── Lo Rechazado nunca podrá usarse, así que si estaba reservado
        # para una OT (ver ott_registrar_retorno / asignar_lote_a_ot) hay
        # que liberar esa reserva en la misma medida en que sube lo
        # rechazado — si no, queda "cantidad_reservada" fantasma que nunca
        # se puede cubrir con material real. Si rechazado bajara (corrección
        # de una clasificación), no se reconstruye la reserva automáticamente.
        rechazado_anterior = float(lote["cantidad_rechazada"] or 0)
        delta_rechazado = rechazado - rechazado_anterior
        if delta_rechazado > 0.0001:
            execute("UPDATE lotes SET cantidad_reservada=MAX(0,COALESCE(cantidad_reservada,0)-?) WHERE id=?",
                (delta_rechazado, lid))
        _sync_ott_retorno_a_operacion(lid)
        _sync_cajones_recepcion(lid)
        return jsonify({"ok": True, "numero_lote": lote["numero"],
            "cantidad_aprobada": aprobado, "cantidad_rechazada": rechazado,
            "cantidad_pendiente": pendiente, "estado": estado_lote})

    # ── Modelo legado: cambio de estado de todo el lote de una sola vez
    # (se mantiene por compatibilidad con otros llamadores internos)
    nuevo_estado = d.get("estado", lote["estado"])
    nueva_activa_total = disp if nuevo_estado == "Aprobado" else 0
    nueva_rechazada_total = disp if nuevo_estado == "Rechazado" else 0
    execute("""UPDATE lotes SET estado=?,cantidad_activa=?,cantidad_rechazada=?,
        referencia_proveedor=?,certificado=?,obs=? WHERE id=?""",
        (nuevo_estado, nueva_activa_total, nueva_rechazada_total,
         d.get("referencia_proveedor", lote["referencia_proveedor"]),
         d.get("certificado", lote["certificado"]),
         d.get("obs", lote["obs"]), lid))
    execute("""INSERT INTO movimientos (material_id,lote_id,tipo,cantidad,referencia,usuario_id)
        VALUES (?,?,?,?,?,?)""",
        (lote["material_id"], lid, "ajuste", disp,
         f"Cambio estado → {nuevo_estado} | Lote {lote['numero']}",
         session["user_id"]))
    # ── Lotes con stock_computado=0: el stock refleja solo lo Aprobado y se
    # ajusta por la variación de cantidad_activa; con stock_computado=1 la
    # clasificación no mueve stock (ver explicación en el modelo nuevo más
    # arriba) ─────────────────────────────────────────────────────────────
    aprobado_anterior = float(lote["cantidad_activa"] or 0)
    delta_aprobado = nueva_activa_total - aprobado_anterior
    # Idem: un lote cuyo stock ya se computo al crearlo no se mueve por Calidad.
    if bool(lote["stock_computado"] if "stock_computado" in lote.keys() else 0):
        delta_aprobado = 0.0
    if abs(delta_aprobado) > 0.0001:
        execute("""UPDATE materiales SET stock=MAX(0,stock+?),
            actualizado=datetime('now','localtime') WHERE id=?""",
            (delta_aprobado, lote["material_id"]))
        execute("""INSERT INTO movimientos (material_id,lote_id,tipo,cantidad,referencia,usuario_id)
            VALUES (?,?,?,?,?,?)""",
            (lote["material_id"], lid,
             "entrada" if delta_aprobado > 0 else "salida",
             abs(delta_aprobado),
             (f"Aprobación de lote {lote['numero']} — ingreso a inventario"
              if delta_aprobado > 0 else
              f"Corrección de aprobación — Lote {lote['numero']} (baja de inventario)"),
             session["user_id"]))
    auto_generar_sc_bajo_stock(lote["material_id"], f"cambio de estado de lote {lote['numero']}")
    # ── Misma liberación de reserva que en el modelo nuevo: si el lote pasa
    # a Rechazado (o ya tenía algo rechazado), esa porción nunca se puede
    # usar, así que no debe seguir contando como reservada para la OT.
    rechazado_anterior = float(lote["cantidad_rechazada"] or 0)
    delta_rechazado = nueva_rechazada_total - rechazado_anterior
    if delta_rechazado > 0.0001:
        execute("UPDATE lotes SET cantidad_reservada=MAX(0,COALESCE(cantidad_reservada,0)-?) WHERE id=?",
            (delta_rechazado, lid))
    _sync_ott_retorno_a_operacion(lid)
    _sync_cajones_recepcion(lid)
    return jsonify({"ok": True, "accion": "estado_actualizado",
        "estado": nuevo_estado, "cant_activa": nueva_activa_total})


@app.route("/api/lotes/<int:lid>/trazabilidad", methods=["GET"])
@login_required()
def trazabilidad_lote(lid):
    """Traza un lote: movimientos, OTs que lo usaron, productos terminados generados."""
    lote = query("""SELECT l.*,m.codigo mat_codigo,m.descripcion mat_descripcion
        FROM lotes l JOIN materiales m ON m.id=l.material_id WHERE l.id=?""",
        (lid,), one=True)
    if not lote: return jsonify({"error": "Lote no encontrado"}), 404

    movimientos = query("""SELECT mv.*,u.nombre usuario_nombre
        FROM movimientos mv LEFT JOIN usuarios u ON u.id=mv.usuario_id
        WHERE mv.lote_id=? ORDER BY mv.id""", (lid,))

    ordenes = query("""SELECT ol.*,o.numero ot_numero,o.estado ot_estado,
        o.fecha_entrega,c.razon cliente_nombre,p.nombre producto_nombre,
        m.descripcion mat_descripcion
        FROM orden_lotes ol
        JOIN ordenes o ON o.id=ol.orden_id
        LEFT JOIN clientes c ON c.id=o.cliente_id
        LEFT JOIN productos p ON p.id=o.producto_id
        JOIN materiales m ON m.id=ol.material_id
        WHERE ol.lote_id=? ORDER BY ol.id""", (lid,))

    return jsonify({
        "lote": dict(lote),
        "movimientos": [dict(r) for r in movimientos],
        "ordenes": [dict(r) for r in ordenes],
        "origen": _traz_origen_lote(lid),
        "destinos": _traz_destinos(lid),
    })


# ── Trazabilidad completa (remito ⇄ OT ⇄ lotes de materia prima) ─────────────
# Un lote de producto terminado o semielaborado se llama como la OT que lo hizo
# y lleva referencia "OT <número>" (con sufijo "-PT" si el número ya estaba
# usado); el que vuelve de un tercero es el lote_retorno_id de su OTT.
TRAZ_PROFUNDIDAD = 5


def _traz_lote_info(lid):
    l = query("""SELECT l.id,l.numero,l.cantidad_original,l.estado,l.fecha_ingreso,
            l.referencia_proveedor,l.certificado,m.codigo mat_codigo,
            m.descripcion mat_descripcion,m.unidad,pv.razon proveedor
        FROM lotes l JOIN materiales m ON m.id=l.material_id
        LEFT JOIN proveedores pv ON pv.id=l.proveedor_id WHERE l.id=?""", (lid,), one=True)
    if not l:
        return None
    d = dict(l)
    rc = query("SELECT numero,remito,fecha FROM recepciones WHERE lote_id=? ORDER BY id LIMIT 1", (lid,), one=True)
    d["recepcion"] = dict(rc) if rc else None
    return d


def _traz_ot_de_lote(lote):
    """OT que produjo el lote (o None si es de compra)."""
    ref = (lote.get("referencia_proveedor") or "").strip()
    if ref.startswith("OT "):
        num = ref[3:].strip()
        for cand in (num, num[:-3] if num.endswith("-PT") else None):
            if cand:
                o = query("SELECT id FROM ordenes WHERE numero=?", (cand,), one=True)
                if o:
                    return o["id"]
    c = query("SELECT orden_id FROM cajones WHERE lote_id=? AND orden_id IS NOT NULL LIMIT 1", (lote["id"],), one=True)
    return c["orden_id"] if c else None


def _traz_lotes_de_ot(ot):
    """Lotes que salieron de una OT (terminado o semielaborado)."""
    ids = [r["id"] for r in query(
        "SELECT id FROM lotes WHERE referencia_proveedor IN (?,?)",
        ("OT " + ot["numero"], "OT " + ot["numero"] + "-PT"))]
    ids += [r["lote_id"] for r in query(
        "SELECT DISTINCT lote_id FROM cajones WHERE orden_id=? AND lote_id IS NOT NULL", (ot["id"],))
        if r["lote_id"] not in ids]
    return ids


def _traz_origen_lote(lid, nivel=0, vistos=None):
    """Hacia atrás: de dónde salió un lote. Si es de una OT, la OT con sus
    operaciones y los lotes que consumió (recursivo); si volvió de un
    tercero, la OTT; si es de compra, proveedor y recepción."""
    vistos = vistos if vistos is not None else set()
    info = _traz_lote_info(lid)
    if not info:
        return None
    if lid in vistos or nivel > TRAZ_PROFUNDIDAD:
        info["repetido"] = True
        return info
    vistos.add(lid)
    ott = query("""SELECT t.id,t.numero,t.estado,t.fecha_envio,t.fecha_retorno_real,
            t.cantidad_enviada,t.cantidad_recibida,t.ot_origen_id,pv.razon proveedor,
            po.nombre operacion
        FROM ordenes_tercerizado t LEFT JOIN proveedores pv ON pv.id=t.proveedor_id
        LEFT JOIN orden_operaciones po ON po.id=t.operacion_id
        WHERE t.lote_retorno_id=? LIMIT 1""", (lid,), one=True)
    info["ott"] = dict(ott) if ott else None
    oid = _traz_ot_de_lote(info) or (ott["ot_origen_id"] if ott else None)
    info["ot"] = _traz_ot(oid, nivel, vistos) if oid else None
    if not info["ot"] and not ott:
        info["origen"] = "compra" if info.get("proveedor") or (info.get("referencia_proveedor") or "").startswith("OC ") else "stock"
    return info


def _traz_ot(oid, nivel, vistos):
    o = query("""SELECT o.id,o.numero,o.estado,o.cantidad,o.fecha_inicio,o.fecha_entrega,
            p.codigo producto_codigo,p.nombre producto_nombre,c.razon cliente
        FROM ordenes o LEFT JOIN productos p ON p.id=o.producto_id
        LEFT JOIN clientes c ON c.id=o.cliente_id WHERE o.id=?""", (oid,), one=True)
    if not o:
        return None
    d = dict(o)
    ops = []
    for op in query("""SELECT oo.id,oo.orden,oo.nombre,oo.es_tercerizada,oo.qty_producida,
            mq.codigo maquina_codigo,mq.nombre maquina_nombre
        FROM orden_operaciones oo LEFT JOIN maquinas mq ON mq.id=oo.maquina_id
        WHERE oo.orden_id=? ORDER BY oo.orden,oo.id""", (oid,)):
        x = dict(op)
        x["novedades"] = [dict(n) for n in query("""SELECT n.numero,n.fecha,n.turno,
                n.cantidad_producida,n.tiempo_real_min,
                TRIM(COALESCE(e.nombre,'')||' '||COALESCE(e.apellido,'')) empleado,
                COALESCE(mq.codigo,mo.codigo) maquina_codigo
            FROM novedades_produccion n LEFT JOIN empleados e ON e.id=n.empleado_id
            LEFT JOIN maquinas mq ON mq.id=n.maquina_id
            LEFT JOIN orden_operaciones oo ON oo.id=n.orden_operacion_id
            LEFT JOIN maquinas mo ON mo.id=oo.maquina_id
            WHERE n.orden_operacion_id=? ORDER BY n.fecha,n.id""", (op["id"],))]
        x["otts"] = [dict(t) for t in query("""SELECT t.numero,t.estado,t.fecha_envio,
                t.fecha_retorno_real,t.cantidad_enviada,t.cantidad_recibida,pv.razon proveedor
            FROM ordenes_tercerizado t LEFT JOIN proveedores pv ON pv.id=t.proveedor_id
            WHERE t.ot_origen_id=? AND t.operacion_id=? ORDER BY t.id""", (oid, op["id"]))]
        ops.append(x)
    d["operaciones"] = ops
    mats = []
    for ol in query("""SELECT ol.lote_id,ol.cantidad_usada,ol.cantidad_consumida
            FROM orden_lotes ol WHERE ol.orden_id=? ORDER BY ol.id""", (oid,)):
        lo = _traz_origen_lote(ol["lote_id"], nivel + 1, vistos)
        if lo:
            lo["cantidad_usada"] = ol["cantidad_usada"]
            lo["cantidad_consumida"] = ol["cantidad_consumida"]
            mats.append(lo)
    d["materiales"] = mats
    return d


def _traz_remitos_de_lote(lid):
    return [dict(r) for r in query("""SELECT r.id,r.numero,r.fecha,r.estado,
            c.razon cliente,ri.cantidad
        FROM remito_items ri JOIN remitos r ON r.id=ri.remito_id
        LEFT JOIN clientes c ON c.id=r.cliente_id
        WHERE ri.lote_id=? AND COALESCE(r.tipo,'entrega_cliente')='entrega_cliente'
        ORDER BY r.fecha,r.id""", (lid,))]


def _traz_destinos(lid, nivel=0, vistos=None):
    """Hacia adelante: a qué clientes llegó un lote, directamente por remito o
    a través de las OTs que lo consumieron (recursivo)."""
    vistos = vistos if vistos is not None else set()
    if lid in vistos or nivel > TRAZ_PROFUNDIDAD:
        return {"remitos": [], "ordenes": []}
    vistos.add(lid)
    res = {"remitos": _traz_remitos_de_lote(lid), "ordenes": []}
    for o in query("""SELECT DISTINCT o.id,o.numero,o.estado,c.razon cliente,
            p.nombre producto_nombre
        FROM orden_lotes ol JOIN ordenes o ON o.id=ol.orden_id
        LEFT JOIN clientes c ON c.id=o.cliente_id
        LEFT JOIN productos p ON p.id=o.producto_id
        WHERE ol.lote_id=? ORDER BY o.id""", (lid,)):
        x = dict(o)
        x["lotes"] = []
        for plid in _traz_lotes_de_ot(o):
            if plid == lid:
                continue
            info = _traz_lote_info(plid)
            if info:
                info.update(_traz_destinos(plid, nivel + 1, vistos))
                x["lotes"].append(info)
        res["ordenes"].append(x)
    return res


@app.route("/api/trazabilidad/remito/<int:rid>", methods=["GET"])
@login_required()
def trazabilidad_remito(rid):
    """Todo lo que formó un remito: por renglón, lote, cajones, OT con sus
    operaciones y novedades, terceros y lotes de materia prima."""
    r = query("""SELECT r.id,r.numero,r.fecha,r.estado,r.tipo,r.obs,c.razon cliente,
            oc.numero pedido_numero
        FROM remitos r LEFT JOIN clientes c ON c.id=r.cliente_id
        LEFT JOIN ordenes_cliente oc ON oc.id=r.orden_cliente_id WHERE r.id=?""", (rid,), one=True)
    if not r:
        return jsonify({"error": "Remito no encontrado"}), 404
    vistos = set()
    items = []
    for it in query("""SELECT ri.id,ri.cantidad,ri.lote_id,m.codigo mat_codigo,
            m.descripcion mat_descripcion,m.unidad
        FROM remito_items ri LEFT JOIN materiales m ON m.id=ri.material_id
        WHERE ri.remito_id=? ORDER BY ri.id""", (rid,)):
        x = dict(it)
        x["cajones"] = [dict(c) for c in query("""SELECT c.numero,ric.cantidad,c.estado,
                c.calidad_fecha,u.nombre calidad_por
            FROM remito_item_cajones ric JOIN cajones c ON c.id=ric.cajon_id
            LEFT JOIN usuarios u ON u.id=c.calidad_por
            WHERE ric.remito_item_id=? ORDER BY c.numero""", (it["id"],))]
        x["lote"] = _traz_origen_lote(it["lote_id"], 0, vistos) if it["lote_id"] else None
        items.append(x)
    return jsonify({"remito": dict(r), "items": items})


# Funciones de otras áreas. Van al final a propósito: así cada módulo ya
# definió todo lo suyo cuando otro lo importa, y no hay problemas de
# importación circular. Se usan recién al atender pedidos.
from .comun import consumir_herramientas_op
from .cajones import (_ot_usa_cajones, _sync_cajones_op_tercerizada,
    _sync_cajones_recepcion)
from .compras import auto_generar_sc_bajo_stock

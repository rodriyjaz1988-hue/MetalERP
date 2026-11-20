"""Remitos a clientes y PT disponible para remitir."""
from .nucleo import (app, execute, jsonify, login_required, modulo_requerido, query,
    request, session, siguiente_numero)

# ── Remitos ───────────────────────────────────────────────────────────────────
@app.route("/api/remitos", methods=["GET"])
@login_required()
def get_remitos():
    cliente_id = request.args.get("cliente_id")
    sql = """SELECT r.*,c.razon cliente_nombre,oc.numero oc_numero,
            ott.numero ott_numero, ocp.numero oc_proveedor_numero,
            COALESCE(c.razon, pott.razon, pocp.razon) destinatario
        FROM remitos r
        LEFT JOIN clientes c ON c.id=r.cliente_id
        LEFT JOIN ordenes_cliente oc ON oc.id=r.orden_cliente_id
        LEFT JOIN ordenes_tercerizado ott ON ott.id=r.ott_id
        LEFT JOIN proveedores pott ON pott.id=ott.proveedor_id
        LEFT JOIN ordenes_compra ocp ON ocp.id=r.oc_id
        LEFT JOIN proveedores pocp ON pocp.id=ocp.proveedor_id"""
    items_sql = """SELECT ri.*,m.descripcion mat_descripcion,
            m.codigo mat_codigo,m.unidad,l.numero lote_numero
            FROM remito_items ri
            JOIN materiales m ON m.id=ri.material_id
            JOIN lotes l ON l.id=ri.lote_id
            WHERE ri.remito_id IN ({})"""

    # Modo paginado (pantalla "Remitos emitidos"): filtra y pagina en la base,
    # así se pueden recorrer todos los remitos sin cargarlos de una vez.
    if request.args.get("pagina") is not None:
        w, p = [], []
        if cliente_id:
            w.append("r.cliente_id=?"); p.append(cliente_id)
        fecha = (request.args.get("fecha") or "").strip()
        if fecha:
            w.append("substr(r.fecha,1,10)=?"); p.append(fecha)
        oc = (request.args.get("oc") or "").strip()
        if oc:
            w.append("IFNULL(oc.numero,'') LIKE ?"); p.append(f"%{oc}%")
        mat = (request.args.get("material") or "").strip()
        if mat:
            w.append("""(EXISTS (SELECT 1 FROM remito_items ri2
                JOIN materiales m2 ON m2.id=ri2.material_id
                WHERE ri2.remito_id=r.id
                AND (IFNULL(m2.codigo,'')||' '||IFNULL(m2.descripcion,'')) LIKE ?)
                OR EXISTS (SELECT 1 FROM ordenes_tercerizado o2
                LEFT JOIN proceso_operaciones po2 ON po2.id=o2.proceso_op_id
                LEFT JOIN productos pr2 ON pr2.id=po2.producto_id
                LEFT JOIN materiales ms2 ON ms2.id=o2.material_se_id
                WHERE o2.id=r.ott_id
                AND (IFNULL(pr2.codigo,'')||' '||IFNULL(pr2.nombre,'')||' '||
                     IFNULL(ms2.codigo,'')||' '||IFNULL(ms2.descripcion,'')) LIKE ?))""")
            p.extend([f"%{mat}%", f"%{mat}%"])
        where = (" WHERE " + " AND ".join(w)) if w else ""
        try:
            por_pagina = int(request.args.get("por_pagina", 25))
        except (TypeError, ValueError):
            por_pagina = 25
        por_pagina = min(200, max(10, por_pagina))
        try:
            pagina = max(1, int(request.args.get("pagina", 1)))
        except (TypeError, ValueError):
            pagina = 1
        total = query("SELECT COUNT(*) c FROM remitos r LEFT JOIN ordenes_cliente oc "
                      "ON oc.id=r.orden_cliente_id" + where, p, one=True)["c"]
        paginas = max(1, -(-total // por_pagina))
        pagina = min(pagina, paginas)
        rows = query(sql + where + " ORDER BY r.id DESC LIMIT ? OFFSET ?",
                     (*p, por_pagina, (pagina - 1) * por_pagina))
        result = [dict(r) for r in rows]
        por_id = {d["id"]: d for d in result}
        for d in result:
            d["items"] = []
        if por_id:
            ids = list(por_id)
            for x in query(items_sql.format(",".join("?" * len(ids))), ids):
                por_id[x["remito_id"]]["items"].append(dict(x))
        _items_remitos_proveedor(result)
        return jsonify({"total": total, "pagina": pagina, "por_pagina": por_pagina,
                        "paginas": paginas, "rows": result})

    # Modo clásico (sin paginar): devuelve la lista completa.
    rows = query(sql+" WHERE r.cliente_id=? ORDER BY r.id DESC",(cliente_id,)) if cliente_id else query(sql+" ORDER BY r.id DESC")
    result = []
    for r in rows:
        d = dict(r)
        d["items"] = [dict(x) for x in query(items_sql.format("?"), (r["id"],))]
        result.append(d)
    _items_remitos_proveedor(result)
    return jsonify(result)

@app.route("/api/remitos/<int:rid>", methods=["GET"])
@login_required()
def get_remito(rid):
    """Detalle completo de un remito para la vista "Ver" de Remitos emitidos."""
    d = _remito_detalle(rid)
    if not d: return jsonify({"error": "Remito no encontrado"}), 404
    return jsonify(d)


def _remito_detalle(rid):
    """Remito con destino (cliente o proveedor), referencias e ítems, o None.
    Lo usan la vista "Ver" y el PDF de "Emitir Remito"."""
    r = query("""SELECT r.*, oc.numero oc_cliente_numero, u.nombre creado_por_nombre,
            ott.numero ott_numero, ott.estado ott_estado, ott.proveedor_id ott_proveedor_id,
            o.numero ot_numero, po.nombre operacion_nombre,
            ocp.numero oc_numero, ocp.proveedor_id ocp_proveedor_id
        FROM remitos r
        LEFT JOIN ordenes_cliente oc ON oc.id=r.orden_cliente_id
        LEFT JOIN usuarios u ON u.id=r.creado_por
        LEFT JOIN ordenes_tercerizado ott ON ott.id=r.ott_id
        LEFT JOIN ordenes o ON o.id=ott.ot_origen_id
        LEFT JOIN proceso_operaciones po ON po.id=ott.proceso_op_id
        LEFT JOIN ordenes_compra ocp ON ocp.id=r.oc_id
        WHERE r.id=?""", (rid,), one=True)
    if not r: return None
    d = dict(r)
    if d.get("cliente_id"):
        c = query("""SELECT razon,cuit,iva,direccion,localidad,contacto,telefono
            FROM clientes WHERE id=?""", (d["cliente_id"],), one=True)
        d["destino"] = dict(c, tipo="cliente") if c else None
    else:
        prov_id = d.get("ott_proveedor_id") or d.get("ocp_proveedor_id")
        p = query("SELECT razon,cuit,contacto,telefono FROM proveedores WHERE id=?",
                  (prov_id,), one=True) if prov_id else None
        d["destino"] = dict(p, tipo="proveedor") if p else None
    d["items"] = [dict(x) for x in query("""SELECT ri.*, m.descripcion mat_descripcion,
            m.codigo mat_codigo, m.unidad, l.numero lote_numero
        FROM remito_items ri
        JOIN materiales m ON m.id=ri.material_id
        JOIN lotes l ON l.id=ri.lote_id
        WHERE ri.remito_id=?""", (rid,))]
    _items_remitos_proveedor([d])
    return d

def _items_remitos_proveedor(remitos):
    """Los remitos hacia proveedores (traslado/devolución de OTT, devolución
    de OC) no generan remito_items, así que su columna Ítems salía vacía.
    Para mostrarlos se arma el ítem a partir de la OTT/OC de origen. Son
    solo de lectura (sin lote_id): no afectan stock ni entregas."""
    for d in remitos:
        if d.get("items"):
            continue
        tipo = d.get("tipo")
        if tipo in ("traslado_ott", "devolucion_ott") and d.get("ott_id"):
            if tipo == "traslado_ott":
                # La pieza que viaja: el producto de la operación; en una
                # OTT manual (sin operación) el material insumo enviado.
                it = query("""SELECT COALESCE(pr.codigo, m.codigo) mat_codigo,
                        COALESCE(pr.nombre, m.descripcion) mat_descripcion,
                        COALESCE(pr.unidad, m.unidad) unidad
                    FROM ordenes_tercerizado ott
                    LEFT JOIN proceso_operaciones po ON po.id=ott.proceso_op_id
                    LEFT JOIN productos pr ON pr.id=po.producto_id
                    LEFT JOIN materiales m ON m.id=ott.material_se_id
                    WHERE ott.id=?""", (d["ott_id"],), one=True)
            else:
                it = query("""SELECT m.codigo mat_codigo, m.descripcion mat_descripcion,
                        m.unidad, l.numero lote_numero
                    FROM ordenes_tercerizado ott
                    JOIN lotes l ON l.id=ott.lote_retorno_id
                    JOIN materiales m ON m.id=l.material_id
                    WHERE ott.id=?""", (d["ott_id"],), one=True)
            if it and (it["mat_codigo"] or it["mat_descripcion"]):
                x = dict(it)
                cant = d.get("ott_cantidad")
                if cant is None and tipo == "traslado_ott":
                    # Remitos viejos sin cantidad guardada: si es el único
                    # traslado de esa OTT, la cantidad es la enviada.
                    _o = query("""SELECT cantidad_enviada,
                            (SELECT COUNT(*) FROM remitos WHERE ott_id=ott.id AND tipo='traslado_ott') n
                        FROM ordenes_tercerizado ott WHERE id=?""", (d["ott_id"],), one=True)
                    if _o and _o["n"] == 1 and float(_o["cantidad_enviada"] or 0) > 0:
                        cant = _o["cantidad_enviada"]
                x.update(remito_id=d["id"], cantidad=cant)
                d["items"] = [x]
        elif tipo == "devolucion_oc" and d.get("oc_id"):
            # Lo devuelto queda acumulado por ítem de OC; la cantidad solo es
            # exacta si la OC tiene un único remito de devolución.
            unico = query("""SELECT COUNT(*) c FROM remitos
                WHERE oc_id=? AND tipo='devolucion_oc'""", (d["oc_id"],), one=True)["c"] == 1
            d["items"] = [dict(remito_id=d["id"], mat_codigo=x["mat_codigo"],
                               mat_descripcion=x["mat_descripcion"], unidad=x["unidad"],
                               cantidad=x["cantidad"] if unico else None)
                for x in query("""SELECT COALESCE(m.codigo, i.descripcion) mat_codigo,
                        COALESCE(m.descripcion, i.descripcion) mat_descripcion, m.unidad,
                        i.cantidad_rechazada_devuelta cantidad
                    FROM ordenes_compra_items i LEFT JOIN materiales m ON m.id=i.material_id
                    WHERE i.oc_id=? AND COALESCE(i.cantidad_rechazada_devuelta,0) > 0""",
                    (d["oc_id"],))]

@app.route("/api/remitos/opciones", methods=["GET"])
@login_required()
def get_remitos_opciones():
    """Sugerencias para los filtros de Remitos emitidos (OC y materiales usados)."""
    ocs = query("""SELECT DISTINCT oc.numero FROM remitos r
        JOIN ordenes_cliente oc ON oc.id=r.orden_cliente_id
        WHERE oc.numero IS NOT NULL ORDER BY oc.numero""")
    mats = query("""SELECT m.codigo, m.descripcion FROM remito_items ri
            JOIN materiales m ON m.id=ri.material_id
        UNION
        SELECT COALESCE(pr.codigo, ms.codigo), COALESCE(pr.nombre, ms.descripcion)
            FROM remitos r JOIN ordenes_tercerizado ott ON ott.id=r.ott_id
            LEFT JOIN proceso_operaciones po ON po.id=ott.proceso_op_id
            LEFT JOIN productos pr ON pr.id=po.producto_id
            LEFT JOIN materiales ms ON ms.id=ott.material_se_id
            WHERE COALESCE(pr.codigo, ms.codigo) IS NOT NULL
        ORDER BY 1""")
    return jsonify({"ocs": [r["numero"] for r in ocs],
                    "materiales": [{"codigo": r["codigo"], "descripcion": r["descripcion"]} for r in mats]})

@app.route("/api/pt_disponible", methods=["GET"])
@login_required()
def get_pt_disponible():
    """Productos terminados con lotes activos disponibles para remitir."""
    cliente_id = request.args.get("cliente_id")
    # La vinculación a la OC de cliente solo cuenta si esa OC está activa
    # (no Cancelada). Si se cancela la OC, el producto ya hecho y aprobado
    # queda "sin OC vinculada" (aunque el vínculo OT->ítem siga existiendo);
    # si la OC se reabre (vuelve a un estado activo), el join vuelve a
    # resolver y la vinculación reaparece sola — todo se calcula en vivo a
    # partir de ordenes_cliente.estado, sin tocar el vínculo real.
    #
    # El join a la OT que originó el lote usa orden_cliente_item_ots (no la
    # columna ot_id, que solo guarda la primera OT vinculada a un ítem) para
    # cubrir también lotes de OTs vinculadas como 2da/3ra OT de un ítem.
    #
    # Un lote deja de listarse acá en cuanto el pendiente del ítem al que
    # está vinculado llega a 0 (ya se remitió todo lo pedido): el resto de
    # producto terminado que haya quedado (porque la OT pedía más de lo que
    # esa OC necesitaba) no debe ofrecerse para remitir contra esa OC. Si esa
    # OT se desvincula y se vincula a otra OC con pendiente, el lote vuelve a
    # aparecer solo.
    rows = query("""SELECT l.*,m.codigo mat_codigo,m.descripcion mat_descripcion,m.unidad,
        p.nombre producto_nombre, p.id producto_id,
        pcli.razon producto_cliente_nombre,
        CASE WHEN oc.id IS NOT NULL THEN oc_items.id END oc_item_id,
        CASE WHEN oc.id IS NOT NULL THEN oc_items.cantidad END oc_cantidad,
        CASE WHEN oc.id IS NOT NULL THEN oc_items.orden_cliente_id END orden_cliente_id,
        oc.numero oc_numero,
        CASE WHEN oc.id IS NOT NULL THEN oc.cliente_id END oc_cliente_id,
        CASE WHEN oc.id IS NOT NULL THEN
            (SELECT COALESCE(SUM(ri.cantidad),0) FROM remito_items ri JOIN remitos rr ON rr.id=ri.remito_id
             WHERE ri.orden_cliente_item_id=oc_items.id AND rr.estado!='Anulado')
        END ya_remitido
        FROM lotes l
        JOIN materiales m ON m.id=l.material_id
        LEFT JOIN productos p ON p.id=m.id
        LEFT JOIN clientes pcli ON pcli.id=p.cliente_id
        LEFT JOIN ordenes ot_gen ON (ot_gen.numero=l.numero
            OR l.numero=ot_gen.numero || '-PT'
            OR l.numero LIKE ot_gen.numero || '-C%')
        LEFT JOIN orden_cliente_item_ots ocio ON ocio.ot_id=ot_gen.id
        LEFT JOIN ordenes_cliente_items oc_items ON oc_items.id=ocio.item_id
            AND oc_items.producto_id=p.id
        LEFT JOIN ordenes_cliente oc ON oc.id=oc_items.orden_cliente_id
            AND oc.estado IN ('Recibida','Confirmada','En proceso')
        WHERE m.categoria='Producto terminado'
        AND l.cantidad_activa>0 AND l.estado != 'Agotado' AND l.estado != 'Bloqueado'
        AND oc.id IS NOT NULL
        AND oc_items.cantidad > (SELECT COALESCE(SUM(ri.cantidad),0) FROM remito_items ri JOIN remitos rr ON rr.id=ri.remito_id
             WHERE ri.orden_cliente_item_id=oc_items.id AND rr.estado!='Anulado')
        """ + ("AND oc.cliente_id=?" if cliente_id else "") + """
        ORDER BY l.id DESC""", (cliente_id,) if cliente_id else ())
    return jsonify([dict(r) for r in rows])

@app.route("/api/remitos", methods=["POST"])
@login_required(roles=["admin","almacen","vendedor","logistica"])
@modulo_requerido("remitir")
def create_remito():
    d = request.json
    if not d.get("cliente_id"): return jsonify({"error": "Cliente requerido"}), 400
    items_in = [it for it in (d.get("items") or []) if it.get("lote_id") and it.get("cantidad")]
    if not items_in:
        return jsonify({"error": "El remito debe tener al menos un ítem"}), 400
    # Validar TODOS los ítems antes de grabar nada: antes un ítem que pedía
    # más de lo aprobado se salteaba en silencio y el remito salía igual,
    # incompleto, sin avisar. Se suma por lote por si el mismo lote viene en
    # más de un renglón.
    pedido_por_lote = {}
    for it in items_in:
        try:
            qty_it = float(it["cantidad"])
        except (TypeError, ValueError):
            return jsonify({"error": "Cantidad inválida en un ítem del remito"}), 400
        if qty_it <= 0:
            return jsonify({"error": "Las cantidades del remito deben ser mayores a 0"}), 400
        pedido_por_lote[it["lote_id"]] = pedido_por_lote.get(it["lote_id"], 0.0) + qty_it
    # El lote tiene que ser del mismo producto que el renglón del pedido al
    # que se imputa (tabla única: el PT y el producto comparten id).
    for it in items_in:
        if it.get("orden_cliente_item_id"):
            oci_chk = query("SELECT producto_id FROM ordenes_cliente_items WHERE id=?", (it["orden_cliente_item_id"],), one=True)
            l_chk = query("SELECT numero,material_id FROM lotes WHERE id=?", (it["lote_id"],), one=True)
            if not oci_chk:
                return jsonify({"error": "Renglón del pedido no encontrado"}), 400
            if l_chk and int(l_chk["material_id"]) != int(oci_chk["producto_id"]):
                return jsonify({"error": f"El lote {l_chk['numero']} es de otro producto que el renglón del pedido"}), 400
    for lid_it, qty_it in pedido_por_lote.items():
        l_it = query("SELECT numero,cantidad_activa FROM lotes WHERE id=?", (lid_it,), one=True)
        if not l_it:
            return jsonify({"error": "Lote no encontrado en un ítem del remito"}), 400
        if qty_it > float(l_it["cantidad_activa"] or 0) + 0.0001:
            return jsonify({"error": f"El lote {l_it['numero']} tiene {float(l_it['cantidad_activa'] or 0):g} aprobado/disponible y se quieren remitir {qty_it:g}"}), 400
    numero = siguiente_numero("remitos", "REM-", 4)
    rid = execute("""INSERT INTO remitos (numero,cliente_id,orden_cliente_id,obs,creado_por)
        VALUES (?,?,?,?,?)""",
        (numero, d.get("cliente_id"), d.get("orden_cliente_id"),
         d.get("obs"), session["user_id"]))
    items_insertados = 0
    for item in items_in:
        qty = float(item["cantidad"])
        lote = query("""SELECT id,material_id,cantidad_disponible,cantidad_activa
            FROM lotes WHERE id=?""", (item["lote_id"],), one=True)
        if not lote: continue
        activa = float(lote["cantidad_activa"] or 0)
        if qty > activa:
            # Can't remit more than what's active/approved
            continue
        ri_id = execute("""INSERT INTO remito_items
            (remito_id,material_id,lote_id,orden_cliente_item_id,cantidad,obs)
            VALUES (?,?,?,?,?,?)""",
            (rid, lote["material_id"], item["lote_id"],
             item.get("orden_cliente_item_id"), qty, item.get("obs")))
        items_insertados += 1
        # Discount from lote (both disponible and activa)
        nueva_disp   = max(0, float(lote["cantidad_disponible"]) - qty)
        nueva_activa = max(0, activa - qty)
        nuevo_estado = "Agotado" if nueva_disp <= 0 else ("Aprobado" if nueva_activa > 0 else "Ingresado")
        execute("""UPDATE lotes SET cantidad_disponible=?,cantidad_activa=?,estado=?
            WHERE id=?""", (nueva_disp, nueva_activa, nuevo_estado, lote["id"]))
        if query("SELECT 1 FROM cajones WHERE lote_id=? LIMIT 1", (lote["id"],), one=True):
            _remitir_de_cajones(ri_id, lote["id"], qty)
            _lote_estado_por_cajones(lote["id"])
        # Discount from PT stock
        execute("UPDATE materiales SET stock=MAX(0,stock-?),actualizado=datetime('now','localtime') WHERE id=?",
            (qty, lote["material_id"]))
        execute("INSERT INTO movimientos (material_id,lote_id,tipo,cantidad,referencia,usuario_id) VALUES (?,?,?,?,?,?)",
            (lote["material_id"], lote["id"], "salida", qty, f"Remito {numero}", session["user_id"]))
        if item.get("orden_cliente_item_id"):
            _sync_requerimiento_desde_pedido(item["orden_cliente_item_id"])
    if items_insertados == 0:
        # Ningún ítem pudo aplicarse (stock insuficiente en todos): abortar remito
        execute("DELETE FROM remitos WHERE id=?", (rid,))
        return jsonify({"error": "No se pudo generar el remito: stock insuficiente en los ítems seleccionados"}), 400

    # ── Cierre automático de la OC: si con este remito se cubrió el 100% de
    # lo pedido (sumando todos los remitos, no solo este), marcar la OC como
    # "Completada". No completar OCs que todavía tengan renglones sin OT
    # (item["ot_id"] NULL), porque eso significa que ni siquiera se terminó
    # de planificar todo el pedido.
    ocids_afectadas = set()
    if d.get("orden_cliente_id"):
        ocids_afectadas.add(d["orden_cliente_id"])
    for item in items_in:
        oci = item.get("orden_cliente_item_id")
        if oci:
            row = query("SELECT orden_cliente_id FROM ordenes_cliente_items WHERE id=?", (oci,), one=True)
            if row: ocids_afectadas.add(row["orden_cliente_id"])
    for ocid_remito in ocids_afectadas:
        oc_items = query("""SELECT id,cantidad,ot_id FROM ordenes_cliente_items
            WHERE orden_cliente_id=?""", (ocid_remito,))
        def _cubierto(it):
            _o, c = _ots_vinculadas_item(it["id"])
            return c >= float(it["cantidad"])
        if oc_items and all(_cubierto(it) for it in oc_items):
            # Cada renglón tiene que estar entregado por completo: el exceso
            # de uno no cubre lo que falta de otro.
            def _entregado(it):
                return float(query("""SELECT COALESCE(SUM(ri.cantidad),0) total
                    FROM remito_items ri JOIN remitos r ON r.id=ri.remito_id
                    WHERE ri.orden_cliente_item_id=? AND r.estado!='Anulado'""",
                    (it["id"],), one=True)["total"])
            if all(_entregado(it) >= float(it["cantidad"]) - 0.001 for it in oc_items):
                execute("UPDATE ordenes_cliente SET estado='Completada' WHERE id=?", (ocid_remito,))
                _forzar_completar_ots_oc(ocid_remito)

    return jsonify({"ok": True, "id": rid, "numero": numero}), 201


# Funciones de otras áreas. Van al final a propósito: así cada módulo ya
# definió todo lo suyo cuando otro lo importa, y no hay problemas de
# importación circular. Se usan recién al atender pedidos.
from .ventas import _forzar_completar_ots_oc, _ots_vinculadas_item
from .requerimientos import _sync_requerimiento_desde_pedido
from .cajones import _lote_estado_por_cajones, _remitir_de_cajones

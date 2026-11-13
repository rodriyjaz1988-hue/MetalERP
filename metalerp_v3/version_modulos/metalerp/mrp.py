"""MRP: consolidación de pedidos y pronósticos, análisis de faltantes y OTs."""
from .nucleo import (app, auditoria_proceso, date, execute, jsonify, login_required, math,
    query, request, siguiente_numero, timedelta, transaccion)

# ── MRP ampliado: consolidar OC-cliente → generar OTs ────────────────────────
@auditoria_proceso("SC automática por material faltante")
def _generar_sc_materiales_faltantes(oid, numero_ot, motivo=""):
    """Revisa los materiales que requiere una OT (por ejemplo una OT auxiliar
    recién creada) y, para cada uno que esté bajo stock mínimo o cuyo stock
    actual no alcance para cubrir lo que esta OT necesita, genera (o
    actualiza) una Solicitud de Compra. La cantidad pedida siempre apunta a
    reponer hasta el "Máximo" configurado en el material (stock_max), no solo
    lo justo para esta OT — igual que el resto del sistema de reposición.
    Si el material no tiene Máximo configurado, se usa como objetivo lo que
    esta OT necesita.
    Devuelve la lista de SC creadas/actualizadas.

    Desactivado por defecto: ver _sc_automaticas_activas()."""
    if not _sc_automaticas_activas():
        return []
    creadas = []
    mats = query("""SELECT om.material_id, om.cantidad_requerida, m.codigo, m.descripcion,
        m.unidad, m.categoria, m.stock, m.stock_min, m.stock_max,
        COALESCE((SELECT SUM(MAX(0, l.cantidad_activa - COALESCE(l.cantidad_reservada,0)))
                   FROM lotes l
                   WHERE l.material_id=om.material_id
                     AND l.cantidad_activa > COALESCE(l.cantidad_reservada,0)), 0) AS disponible_libre,
        (SELECT COUNT(*) FROM lotes l2 WHERE l2.material_id=om.material_id) AS n_lotes
        FROM orden_materiales om JOIN materiales m ON m.id=om.material_id
        WHERE om.orden_id=?""", (oid,))
    for mat in mats:
        if mat["categoria"] not in ("Material", "Insumo", "Herramienta"):
            # "Producto terminado" nunca genera Solicitud de Compra: no se
            # compra en Compras. Si hace falta más de lo que hay en stock, se
            # resuelve fabricándolo (OT auxiliar) — eso lo cubre
            # _gap_analysis_materiales, que vuelve a correr sobre esta OT
            # recién creada (ver _gap_analysis_materiales_multipass).
            continue
        requerido = float(mat["cantidad_requerida"] or 0)
        # Mismo criterio que el gap analysis del MRP: disponible libre por
        # lote (o stock, si el material no usa lotes) más lo que ya viene en
        # OC abiertas, para no volver a pedir lo que está en camino.
        disponible, en_camino = _disponible_material(mat["material_id"])
        stock = disponible + en_camino
        stock_min = float(mat["stock_min"] or 0)
        stock_max = float(mat["stock_max"] or 0)
        # Objetivo de reposición: el Máximo del material. Si no hay Máximo
        # configurado, al menos lo que esta OT necesita.
        objetivo = stock_max if stock_max > 0 else max(stock_min, requerido)
        # Dispara SC si el material está bajo su mínimo, o si — aunque esté
        # por encima del mínimo — el stock disponible no alcanza para cubrir
        # lo que esta OT puntualmente necesita.
        bajo_minimo = stock_min > 0 and stock < stock_min
        insuficiente_para_ot = stock < requerido
        if not bajo_minimo and not insuficiente_para_ot:
            continue
        faltante = round(max(objetivo, requerido) - stock, 3)
        if faltante <= 0:
            continue

        sc_exist = query(f"""SELECT id,cantidad FROM solicitudes_compra
            WHERE material_id=? AND estado IN {SC_ABIERTAS_SQL}
            ORDER BY id DESC LIMIT 1""", (mat["material_id"],), one=True)
        if sc_exist:
            if float(sc_exist["cantidad"] or 0) < faltante:
                execute("""UPDATE solicitudes_compra SET cantidad=?, obs=? WHERE id=?""",
                    (faltante,
                     f"Actualizada automáticamente: material requerido por OT {numero_ot}, faltante {faltante} {mat['unidad']} (objetivo: Máximo {objetivo}).",
                     sc_exist["id"]))
                creadas.append({"numero": None, "material": mat["descripcion"], "cantidad": faltante, "actualizada": True})
            continue

        # Serie SC-PROD-: todo lo que genera el MRP (las manuales son SC-).
        sc_num = siguiente_numero("solicitudes_compra", "SC-PROD-", 4, reservar=True)
        tipo_sc = "Productiva" if mat["categoria"] == "Material" else "Indirecta"
        execute("""INSERT INTO solicitudes_compra
            (numero,tipo,descripcion,material_id,cantidad,unidad,urgencia,estado,obs)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (sc_num, tipo_sc,
             f"Material requerido por {numero_ot} — {mat['descripcion']}",
             mat["material_id"], faltante, mat["unidad"],
             "Alta", "Pendiente",
             f"Generada automáticamente: material requerido por OT {numero_ot}, faltante {faltante} {mat['unidad']} (objetivo: Máximo {objetivo}). {motivo}"))
        creadas.append({"numero": sc_num, "material": mat["descripcion"], "cantidad": faltante})
    return creadas

@app.route("/api/mrp/consolidar", methods=["POST"])
@login_required(roles=["admin","operario"])
@auditoria_proceso("MRP — consolidación de pedidos")
def mrp_consolidar():
    d = request.json or {}
    try:
        oc_ids = sorted({int(x) for x in (d.get("oc_ids") or [])})
    except (TypeError, ValueError):
        return jsonify({"error":"Pedidos inválidos"}), 400
    if not oc_ids: return jsonify({"error":"Seleccioná al menos una OC de cliente"}), 400
    placeholders = ",".join("?" * len(oc_ids))
    ocs = query(f"SELECT id,numero,estado FROM ordenes_cliente WHERE id IN ({placeholders})", oc_ids)
    if len(ocs) != len(oc_ids):
        return jsonify({"error":"Alguno de los pedidos seleccionados ya no existe. Actualizá la pantalla."}), 404
    no_pend = [o["numero"] for o in ocs if o["estado"] not in ("Recibida", "Confirmada")]
    if no_pend:
        return jsonify({"error":"Estos pedidos ya no están pendientes de procesar: " + ", ".join(no_pend)
                        + ". Actualizá la pantalla."}), 400
    items = query(f"""SELECT i.producto_id,SUM(i.cantidad) AS total_qty,
        p.nombre producto_nombre,p.codigo,p.costo_mat,p.costo_mo,p.precio_venta,
        MAX(oc.cliente_id) cliente_id, COUNT(DISTINCT oc.cliente_id) n_clientes,
        p.tiempo_total_hs,
        COALESCE(i.fecha_deseada, MAX(oc.fecha_entrega)) fecha_entrega,
        GROUP_CONCAT(i.id) AS item_ids
        FROM ordenes_cliente_items i
        JOIN ordenes_cliente oc ON oc.id=i.orden_cliente_id
        JOIN productos p ON p.id=i.producto_id
        WHERE oc.id IN ({placeholders}) AND (i.ot_id IS NULL OR i.ot_id=0)
        GROUP BY i.producto_id, i.fecha_deseada""", oc_ids)
    if not items:
        return jsonify({"error":"Los pedidos seleccionados no tienen renglones pendientes: ya tienen todas sus OT generadas."}), 400
    ots_creadas = []
    # Todo o nada: si algo falla a mitad de camino no quedan OT incompletas
    # ni renglones sin vincular, y se puede reintentar sin duplicar.
    try:
        with transaccion():
            for item in items:
                # Si se consolidan pedidos de varios clientes en una misma OT, la OT
                # no es de un cliente puntual (los vínculos ítem→OT siguen indicando
                # a qué pedido corresponde cada parte).
                cliente_ot = item["cliente_id"] if int(item["n_clientes"] or 0) <= 1 else None
                # Sin fecha deseada ni fecha de entrega del pedido, _crear_ot_mrp
                # estima una (hoy + días de trabajo) para que entre en Scheduling.
                oid, numero = _crear_ot_mrp(
                    item["producto_id"], item["total_qty"], cliente_id=cliente_ot,
                    descripcion=f"Fabricación {item['producto_nombre']} — generado por MRP",
                    fecha_entrega=item["fecha_entrega"], precio_venta=item["precio_venta"])
                # Vincular esta OT a los renglones de OC que la originaron
                # (para que "Remitir a cliente" pueda cruzar PT → OC)
                if item["item_ids"]:
                    item_id_list = [int(x) for x in str(item["item_ids"]).split(",") if x]
                    if item_id_list:
                        ph_items = ",".join("?" * len(item_id_list))
                        execute(f"UPDATE ordenes_cliente_items SET ot_id=? WHERE id IN ({ph_items})",
                                [oid] + item_id_list)
                        for iid in item_id_list:
                            execute("INSERT OR IGNORE INTO orden_cliente_item_ots (item_id,ot_id) VALUES (?,?)",
                                    (iid, oid))
                ots_creadas.append({"numero":numero,"producto":item["producto_nombre"],"cantidad":item["total_qty"]})
            # Pasan a "En proceso" solo los pedidos que quedaron con todos sus
            # renglones con OT.
            execute(f"""UPDATE ordenes_cliente SET estado='En proceso' WHERE id IN ({placeholders})
                AND NOT EXISTS (SELECT 1 FROM ordenes_cliente_items i
                    WHERE i.orden_cliente_id=ordenes_cliente.id AND (i.ot_id IS NULL OR i.ot_id=0))""", oc_ids)

            solicitudes_creadas, ots_auxiliares, avisos = _gap_analysis_materiales_multipass()
    except Exception as e:
        print(f"[MRP] Falló la consolidación de pedidos: {e!r}")
        return jsonify({"error": f"No se pudo consolidar y no se generó nada: {e}"}), 500
    return jsonify({"ok":True,"ots":ots_creadas,"ots_auxiliares":ots_auxiliares,
                    "solicitudes_compra":solicitudes_creadas,"avisos":avisos})


def _gap_analysis_materiales_multipass(max_passes=5):
    """Corre _gap_analysis_materiales() repetidas veces: si una pasada genera
    una OT auxiliar nueva (fabricación de un Producto Terminado faltante),
    esa OT auxiliar trae sus propios materiales, que a su vez pueden incluir
    OTRO Producto Terminado faltante (BOM multinivel) — eso recién queda
    visible para el análisis en la pasada siguiente, porque la pasada actual
    ya leyó orden_materiales antes de insertar la nueva OT. Se repite hasta
    que una pasada no genere nada nuevo, con un tope de pasadas para no
    entrar en loop infinito si hay una referencia circular entre productos.
    Devuelve (solicitudes_creadas, ots_auxiliares, avisos) acumuladas de
    todas las pasadas."""
    solicitudes_tot, ots_tot, avisos_tot = [], [], []
    for _ in range(max_passes):
        solicitudes, ots_aux, avisos = _gap_analysis_materiales()
        solicitudes_tot.extend(solicitudes)
        ots_tot.extend(ots_aux)
        avisos_tot.extend(a for a in avisos if a not in avisos_tot)
        # Si esta pasada no creó ninguna OT auxiliar NUEVA (las "actualizada"
        # son sobre una OT que ya existía de una pasada anterior a este
        # llamado), no hay nada más que una pasada nueva pueda destapar.
        if not any(not o.get("actualizada") for o in ots_aux):
            break
    return solicitudes_tot, ots_tot, avisos_tot


def _gap_analysis_materiales():
    """Analiza el stock disponible contra todas las OTs activas (Pendiente/En
    proceso) y genera automáticamente Solicitudes de Compra u OTs auxiliares
    (para Producto Terminado fabricado en planta) para cubrir los faltantes.
    Es agnóstico del origen de las OTs (OC de cliente, pronóstico de venta,
    etc.) — corre sobre el estado actual de orden_materiales. Devuelve
    (solicitudes_creadas, ots_auxiliares, avisos); avisos = textos para el
    usuario sobre faltantes que el sistema no puede resolver solo."""
    # ── Material gap analysis: check stock vs all pending OTs ─────────────────
    solicitudes_creadas = []
    ots_auxiliares = []
    avisos = []
    # Get all active OTs (including just-created) that have unassigned materials
    gap_mats = query("""
        SELECT om.material_id, m.codigo, m.descripcion, m.unidad, m.categoria,
               m.producto_id AS pt_producto_id, m.stock_max,
               SUM(om.cantidad_requerida) AS total_req,
               SUM(COALESCE(om.cantidad_asignada,0)) AS total_asign,
               m.stock AS stock_actual,
               COALESCE((SELECT SUM(MAX(0, l.cantidad_activa - COALESCE(l.cantidad_reservada,0)))
                          FROM lotes l
                          WHERE l.material_id=om.material_id
                            AND l.cantidad_activa > COALESCE(l.cantidad_reservada,0)), 0) AS disponible_libre
        FROM orden_materiales om
        JOIN ordenes o ON o.id=om.orden_id
        JOIN materiales m ON m.id=om.material_id
        WHERE o.estado IN ('Pendiente','En proceso')
        GROUP BY om.material_id""")
    for mat in gap_mats:
        total_req   = float(mat["total_req"] or 0)
        total_asign = float(mat["total_asign"] or 0)
        # Para materiales con trazabilidad por lote (los que tienen lotes
        # cargados), el faltante se calcula contra el "Disponible libre"
        # real (lotes.cantidad_activa - cantidad_reservada), no contra el
        # stock total del material, porque parte de ese stock puede ya
        # estar reservado para otras OTs a nivel de lote. Si el material no
        # maneja lotes (insumos/herramientas sin trazabilidad), se usa el
        # stock general como antes.
        stock, en_camino = _disponible_material(mat["material_id"])
        # Cantidad neta que falta asignar a las OTs activas (lo ya asignado
        # no vuelve a contarse). El faltante real es lo que excede al stock
        # actualmente disponible: si el stock alcanza para cubrir todo lo
        # requerido, no hay faltante; si no alcanza, la SC debe pedir
        # exactamente la diferencia (cubre al máximo con el stock existente,
        # sin sobre-pedir).
        reservado   = max(0, total_req - total_asign)
        faltante    = max(0, reservado - stock)
        if faltante <= 0:
            continue

        # Si el insumo faltante es un Producto Terminado fabricado en planta
        # (tiene proceso propio definido), el faltante NO se resuelve con
        # una SC de compra: se resuelve fabricándolo. Se genera una OT
        # "auxiliar" de ese producto, por la cantidad necesaria para llenar
        # el inventario hasta su "Máximo" (materiales.stock_max) — no solo
        # lo justo para esta OT, para no quedar disparando una OT aux nueva
        # cada vez que se corre el MRP.
        prod_pt = None
        if mat["categoria"] == "Producto terminado" and mat["pt_producto_id"]:
            prod_pt = query("""SELECT p.id,p.nombre,p.codigo FROM productos p
                JOIN proceso_operaciones po ON po.producto_id=p.id
                WHERE p.id=? AND p.activo=1 LIMIT 1""", (mat["pt_producto_id"],), one=True)

        if prod_pt:
            stock_max = float(mat["stock_max"] or 0)
            cantidad_ot = round(max(faltante, stock_max - stock), 3)
            if cantidad_ot <= 0:
                continue

            # No duplicar: si ya hay una OT auxiliar Pendiente/En proceso
            # para este producto (generada por esta misma lógica), se
            # actualiza su cantidad en vez de crear otra.
            ot_exist = query("""SELECT id,numero,cantidad FROM ordenes
                WHERE producto_id=? AND estado IN ('Pendiente','En proceso')
                  AND obs LIKE 'OT auxiliar generada automáticamente por MRP%'
                ORDER BY id DESC LIMIT 1""", (prod_pt["id"],), one=True)
            if ot_exist:
                if float(ot_exist["cantidad"] or 0) < cantidad_ot:
                    # La cantidad de la OT aux cambió: operaciones, materiales
                    # (sin perder lo ya asignado) y costos siguen a la cantidad
                    # nueva, y volvemos a chequear si algún material quedó faltante.
                    _ajustar_cantidad_ot(ot_exist["id"], cantidad_ot)
                    scs_mat = _generar_sc_materiales_faltantes(
                        ot_exist["id"], ot_exist["numero"],
                        motivo=f"Insumo de OT auxiliar {ot_exist['numero']} ({prod_pt['nombre']}).")
                    solicitudes_creadas.extend(scs_mat)
                    ots_auxiliares.append({"numero": ot_exist["numero"], "producto": prod_pt["nombre"],
                                            "cantidad": cantidad_ot, "actualizada": True})
                continue

            oid_aux, numero_aux = _crear_ot_mrp(
                prod_pt["id"], cantidad_ot,
                descripcion=f"{prod_pt['codigo']} — {prod_pt['nombre']} (OT auxiliar por faltante de insumo)",
                prioridad="Alta", fecha_entrega=date.today().isoformat(), precio_venta=0,
                obs=f"OT auxiliar generada automáticamente por MRP. Faltante detectado: {round(faltante,3)} {mat['unidad']}. Se pide hasta el máximo ({stock_max}).")
            ots_auxiliares.append({"numero": numero_aux, "producto": prod_pt["nombre"], "cantidad": cantidad_ot})

            # La OT auxiliar recién creada tiene sus propios materiales
            # (los que hacen falta para fabricar el insumo). Si alguno está
            # bajo stock o no alcanza para cubrir esta OT, se genera la SC
            # correspondiente, pidiendo hasta el Máximo de ese material.
            scs_mat = _generar_sc_materiales_faltantes(
                oid_aux, numero_aux,
                motivo=f"Insumo de OT auxiliar {numero_aux} ({prod_pt['nombre']}).")
            solicitudes_creadas.extend(scs_mat)
            continue

        # Producto terminado sin proceso propio: no se compra en Compras (el
        # alta de SC lo rechaza) ni se puede fabricar sin proceso. Se avisa
        # para que le carguen el proceso o lo resuelvan a mano.
        if mat["categoria"] == "Producto terminado":
            avisos.append(f"Falta {round(faltante, 3)} {mat['unidad'] or ''} de {mat['codigo']} "
                          f"({mat['descripcion']}), un producto terminado sin proceso propio: "
                          "cargale el proceso en Procesos para que el MRP genere su OT.")
            continue

        # Caso normal: material real → falta resolverlo por compra (SC).
        # Si ya hay una SC abierta para este material, no duplicamos: si su
        # cantidad ya cubre el faltante actual la dejamos; si quedó corta
        # (p.ej. porque el faltante creció con esta corrida de MRP), la
        # actualizamos para que cubra el faltante real en vez de dejarla
        # desactualizada.
        # Sexta via automatica de SC (ademas de las cuatro de
        # _sc_automaticas_activas): el MRP inserta la SC aca mismo, sin pasar
        # por _generar_sc_*. Con las SC en manual se saltea el material y se
        # sigue con el resto del gap analysis: las OT auxiliares de arriba
        # NO se tocan, solo deja de pedirse la compra sola.
        if not _sc_automaticas_activas():
            continue
        # Lo que ya está comprado y todavía no llegó (OC abiertas) cubre parte
        # del faltante: sin descontarlo, cada corrida del MRP volvía a pedir
        # el mismo material que ya estaba en camino.
        faltante = round(faltante - en_camino, 3)
        if faltante <= 0:
            continue
        sc_exist = query(f"""SELECT id,cantidad FROM solicitudes_compra
            WHERE material_id=? AND estado IN {SC_ABIERTAS_SQL}
            ORDER BY id DESC LIMIT 1""", (mat["material_id"],), one=True)
        if sc_exist:
            if float(sc_exist["cantidad"] or 0) < faltante:
                execute("""UPDATE solicitudes_compra SET cantidad=?,
                    obs=? WHERE id=?""",
                    (round(faltante, 3),
                     f"Actualizada automáticamente por MRP. Faltante: {round(faltante,3)} {mat['unidad']}",
                     sc_exist["id"]))
                solicitudes_creadas.append({"numero":None,"material":mat["descripcion"],"cantidad":round(faltante,3),"actualizada":True})
        else:
            sc_num = siguiente_numero("solicitudes_compra", "SC-PROD-", 4, reservar=True)
            execute("""INSERT INTO solicitudes_compra
                (numero,tipo,descripcion,material_id,cantidad,unidad,urgencia,estado,obs)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (sc_num, "Productiva",
                 f"Material requerido por MRP — {mat['descripcion']}",
                 mat["material_id"], round(faltante, 3), mat["unidad"],
                 "Alta", "Pendiente",
                 f"Generada automáticamente por MRP. Faltante: {round(faltante,3)} {mat['unidad']}"))
            solicitudes_creadas.append({"numero":sc_num,"material":mat["descripcion"],"cantidad":round(faltante,3)})
    return solicitudes_creadas, ots_auxiliares, avisos


@app.route("/api/mrp/pronostico_meses", methods=["POST"])
@login_required(roles=["admin","operario"])
def mrp_pronostico_meses():
    """Devuelve los meses con renglones pendientes de convertir para los
    pronósticos de venta seleccionados, para que el usuario elija con cuál
    mes consolidar."""
    d = request.json or {}
    pron_ids = d.get("pronostico_ids") or ([d["pronostico_id"]] if d.get("pronostico_id") else [])
    if not pron_ids: return jsonify({"error":"Seleccioná al menos un pronóstico"}), 400
    placeholders = ",".join("?" * len(pron_ids))
    meses = query(f"""SELECT i.mes, COUNT(*) AS items_pendientes, SUM(i.cantidad) AS total_qty
        FROM pronostico_venta_items i
        WHERE i.pronostico_id IN ({placeholders}) AND i.cantidad>0
          AND i.id NOT IN (SELECT item_id FROM pronostico_item_ots)
        GROUP BY i.mes ORDER BY i.mes""", pron_ids)
    return jsonify([dict(r) for r in meses])

@app.route("/api/mrp/consolidar_pronostico", methods=["POST"])
@login_required(roles=["admin","operario"])
@auditoria_proceso("MRP — consolidación de pronóstico")
def mrp_consolidar_pronostico():
    """Genera OTs de fabricación (para stock, sin OC de cliente vinculada) a
    partir de los renglones de un pronóstico de venta. Se debe indicar el mes
    a consolidar ("mes", formato YYYY-MM): se consolidan ese mes y todos los
    meses anteriores que todavía tengan renglones pendientes (ej: si se
    consolida septiembre, también se consolidan agosto, julio, etc. si
    estaban pendientes), ya que se asume que si se llegó a un mes es porque
    los anteriores también deben quedar cubiertos. Se genera una OT distinta
    por cada mes consolidado (nunca se mezclan cantidades de distintos meses
    en una misma OT), y se evita duplicar OTs si el renglón ya fue convertido
    previamente (se registra en pronostico_item_ots)."""
    d = request.json
    pron_ids = d.get("pronostico_ids") or ([d["pronostico_id"]] if d.get("pronostico_id") else [])
    if not pron_ids: return jsonify({"error":"Seleccioná al menos un pronóstico"}), 400
    mes = (d.get("mes") or "").strip()
    if not mes: return jsonify({"error":"Seleccioná el mes a consolidar"}), 400
    placeholders = ",".join("?" * len(pron_ids))
    pronosticos = query(f"SELECT * FROM pronosticos_venta WHERE id IN ({placeholders})", pron_ids)
    if not pronosticos: return jsonify({"error":"Pronóstico no encontrado"}), 404

    # Se agrupa por producto, cliente y mes (mes <= mes elegido) de forma que
    # cada mes pendiente hasta el elegido (inclusive) genere sus propias OTs
    # (nunca se mezclan cantidades de meses distintos en una misma OT).
    items = query(f"""SELECT i.producto_id, pv.cliente_id, i.mes, SUM(i.cantidad) AS total_qty,
        p.nombre producto_nombre, p.codigo, p.precio_venta,
        GROUP_CONCAT(i.id) AS item_ids, GROUP_CONCAT(DISTINCT pv.codigo) AS pron_codigos
        FROM pronostico_venta_items i
        JOIN pronosticos_venta pv ON pv.id=i.pronostico_id
        JOIN productos p ON p.id=i.producto_id
        WHERE i.pronostico_id IN ({placeholders}) AND i.cantidad>0 AND i.mes<=?
          AND i.id NOT IN (SELECT item_id FROM pronostico_item_ots)
        GROUP BY i.producto_id, pv.cliente_id, i.mes
        ORDER BY i.mes""", pron_ids + [mes])
    if not items:
        return jsonify({"error":"No hay renglones pendientes de convertir hasta el mes seleccionado"}), 400

    ots_creadas = []
    # Todo o nada, igual que la consolidación de pedidos.
    try:
        with transaccion():
            for item in items:
                # Entrega: el último día del mes consolidado. Si ese día ya pasó,
                # _crear_ot_mrp estima una fecha (hoy + días de trabajo).
                fin_mes = _fin_de_mes(item["mes"])
                fecha_ot = fin_mes.isoformat() if fin_mes and fin_mes >= date.today() else None
                oid, numero = _crear_ot_mrp(
                    item["producto_id"], item["total_qty"], cliente_id=item["cliente_id"],
                    descripcion=f"Fabricación {item['producto_nombre']} — generado por pronóstico {item['pron_codigos']} ({item['mes']})",
                    fecha_entrega=fecha_ot, precio_venta=item["precio_venta"],
                    obs=f"Generada automáticamente a partir del/los pronóstico(s) de venta {item['pron_codigos']} — mes {item['mes']}.")

                # Vincular los renglones del pronóstico que originaron esta OT, para
                # no volver a convertirlos si se corre el consolidado de nuevo.
                item_id_list = [int(x) for x in str(item["item_ids"]).split(",") if x]
                for iid in item_id_list:
                    execute("INSERT OR IGNORE INTO pronostico_item_ots (item_id,ot_id) VALUES (?,?)", (iid, oid))

                ots_creadas.append({"numero": numero, "producto": item["producto_nombre"], "cantidad": item["total_qty"], "mes": item["mes"]})

            solicitudes_creadas, ots_auxiliares, avisos = _gap_analysis_materiales_multipass()
    except Exception as e:
        print(f"[MRP] Falló la consolidación del pronóstico: {e!r}")
        return jsonify({"error": f"No se pudo consolidar el pronóstico y no se generó nada: {e}"}), 500
    return jsonify({"ok":True,"ots":ots_creadas,"ots_auxiliares":ots_auxiliares,
                    "solicitudes_compra":solicitudes_creadas,"avisos":avisos})


def _qty_operacion(op, qty):
    """Piezas que procesa una operación en una OT de `qty` piezas. Volumen
    agrupado: si la operación agrupa el total en lotes de "valor_recalculado",
    lo requerido de esa operación es ceil(qty / valor_recalculado) en lugar
    del total de la OT. Ej: OT total=100, valor_recalculado=33 → requerido=4.
    `op` es una fila de proceso_operaciones (o una con esas dos columnas)."""
    claves = op.keys()
    vol_agrup = op["volumen_agrupado"] if "volumen_agrupado" in claves else 0
    valor_recalc = op["valor_recalculado"] if "valor_recalculado" in claves else 0
    if vol_agrup and valor_recalc and float(valor_recalc) > 0:
        return math.ceil(float(qty or 0) / float(valor_recalc))
    return qty


def _fin_de_mes(mes):
    """Último día del mes "YYYY-MM" (date), o None si no se puede leer."""
    import calendar
    try:
        anio, m = (int(x) for x in str(mes).split("-")[:2])
        return date(anio, m, calendar.monthrange(anio, m)[1])
    except (TypeError, ValueError):
        return None


def _fecha_estimada_ot(producto_id, cantidad):
    """Fecha de entrega estimada para una OT sin fecha: hoy + los días de
    trabajo necesarios (tiempo total del producto x cantidad, jornadas de 8 h)."""
    p = query("SELECT tiempo_total_hs FROM materiales WHERE id=?", (producto_id,), one=True)
    horas = float((p["tiempo_total_hs"] if p else 0) or 1)
    dias = math.ceil(horas * float(cantidad or 0) / 8)
    return (date.today() + timedelta(days=max(dias, 1))).isoformat()


def _crear_ot_mrp(producto_id, cantidad, cliente_id=None, descripcion=None, prioridad="Normal",
                  fecha_entrega=None, precio_venta=0, obs=None):
    """Crea una OT generada por el sistema (consolidación de pedidos o de
    pronóstico, OT auxiliar del MRP o por faltante de un remito de OTT), con
    todo lo que tiene que llevar: número reservado, operaciones (con volumen
    agrupado), materiales requeridos, OTT de las operaciones tercerizadas y
    fecha de entrega (si no viene, se estima para que entre en Scheduling).
    Devuelve (id, numero)."""
    numero = siguiente_numero("ordenes", "OT-", 3, reservar=True)
    # Tiempo estándar (min) según las operaciones del proceso, y costo de
    # materiales según la receta actual (no los valores fijos del producto,
    # que pueden estar desactualizados).
    ops_proc = query(
        "SELECT * FROM proceso_operaciones WHERE producto_id=? ORDER BY CAST(orden AS INTEGER), orden",
        (producto_id,))
    tiempo_std = tiempo_std_min(ops_proc, cantidad)
    costo_mat = calcular_costo_producto(producto_id, cantidad)
    if not fecha_entrega:
        fecha_entrega = _fecha_estimada_ot(producto_id, cantidad)
    oid = execute("""INSERT INTO ordenes
        (numero,cliente_id,producto_id,descripcion,cantidad,prioridad,estado,fecha_entrega,costo_mat,costo_mo,precio_venta,obs)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (numero, cliente_id, producto_id, descripcion, cantidad, prioridad, "Pendiente", fecha_entrega,
         round(costo_mat, 2), round(tiempo_std, 0), precio_venta, obs))
    populate_ops_internal(oid, producto_id, cantidad)
    populate_mats_internal(oid, producto_id, cantidad)
    # OTT de las operaciones tercerizadas (idempotente). La OTT no dispara
    # compras: su flujo es remitir → recibir.
    _generar_ott_para_ot(oid, numero)
    return oid, numero


def _ajustar_cantidad_ot(oid, nueva, vieja=None, recalcular_costos=True):
    """Cambia la cantidad de una OT y hace que todo lo que depende de ella la
    siga: la cantidad requerida de cada operación (con volumen agrupado; las
    que alguien cambió a mano quedan como están), los materiales requeridos
    (sin tocar lo ya asignado ni reservado) y, si se pide, costo_mat y
    costo_mo. `vieja` es la cantidad anterior, si ya se grabó la nueva."""
    ot = query("SELECT id, producto_id, cantidad FROM ordenes WHERE id=?", (oid,), one=True)
    if not ot:
        return
    if vieja is None:
        vieja = float(ot["cantidad"] or 0)
    execute("UPDATE ordenes SET cantidad=?, actualizado=datetime('now','localtime') WHERE id=?", (nueva, oid))
    ops = query("""SELECT oo.id, oo.qty_requerida, oo.qty_producida,
            po.volumen_agrupado, po.valor_recalculado
        FROM orden_operaciones oo LEFT JOIN proceso_operaciones po ON po.id=oo.proceso_op_id
        WHERE oo.orden_id=?""", (oid,))
    for op in ops:
        if abs(float(op["qty_requerida"] or 0) - float(_qty_operacion(op, vieja) or 0)) > 1e-6:
            continue   # cantidad cargada a mano en la operación: no se pisa
        execute("UPDATE orden_operaciones SET qty_requerida=? WHERE id=?", (_qty_operacion(op, nueva), op["id"]))
        if float(op["qty_producida"] or 0) > 0:
            _sincronizar_estado_paso(op["id"])   # el paso puede cerrarse o reabrirse
    mids = {r["material_id"] for r in query(
        "SELECT material_id FROM orden_materiales WHERE orden_id=?", (oid,))}
    mids |= {r["material_id"] for r in query("""SELECT DISTINCT om.material_id
        FROM orden_operacion_materiales om JOIN orden_operaciones oo ON oo.id=om.orden_operacion_id
        WHERE oo.orden_id=? AND om.material_id IS NOT NULL""", (oid,))}
    for mid in mids:
        _recalcular_material_requerido_ot(oid, mid)
    if recalcular_costos and ot["producto_id"]:
        ops_proc = query("SELECT * FROM proceso_operaciones WHERE producto_id=?", (ot["producto_id"],))
        execute("UPDATE ordenes SET costo_mat=?, costo_mo=? WHERE id=?",
                (round(calcular_costo_producto(ot["producto_id"], nueva), 2),
                 round(tiempo_std_min(ops_proc, nueva), 0), oid))


def _materiales_requeridos_ot(oid, material_id=None):
    """{material_id: (cantidad requerida, unidad)} de una OT, a partir de sus
    propias operaciones y de la copia de materiales de cada una
    (orden_operacion_materiales). Herramientas con vida útil: ceil(piezas /
    vida útil) (cant_material). En un paso con rutas alternativas (mismo
    número de orden) cuenta la ruta que más usa, no la suma de todas: el paso
    lo hace una sola. Si la OT no requiere materia prima, los materiales de
    categoría "Material" quedan afuera."""
    filtro, args = "", [oid]
    if material_id is not None:
        filtro, args = "AND om.material_id=?", [oid, material_id]
    rows = query(f"""SELECT material_id, SUM(paso) AS total, unidad, categoria FROM (
        SELECT om.material_id, m.unidad, m.categoria, oo.orden,
            MAX(cant_material(om.cantidad, oo.qty_requerida, om.vida_util_herramienta)) AS paso
        FROM orden_operaciones oo
        JOIN orden_operacion_materiales om ON om.orden_operacion_id=oo.id
        JOIN materiales m ON m.id=om.material_id
        WHERE oo.orden_id=? AND om.material_id IS NOT NULL {filtro}
        GROUP BY om.material_id, oo.orden)
        GROUP BY material_id""", args)
    ot = query("SELECT requiere_material FROM ordenes WHERE id=?", (oid,), one=True)
    sin_mp = ot is not None and ot["requiere_material"] is not None and int(ot["requiere_material"]) == 0
    return {r["material_id"]: (float(r["total"] or 0), r["unidad"]) for r in rows
            if not (sin_mp and r["categoria"] == "Material")}


def _disponible_material(material_id):
    """(disponible, en_camino) de un material, con el criterio del MRP.
    disponible: si el material maneja lotes, el "Disponible libre" de sus
    lotes (cantidad_activa - cantidad_reservada), porque parte del stock puede
    estar reservado para otras OT; si no, el stock general.
    en_camino: lo pedido en OC de compra abiertas que todavía no llegó."""
    m = query("""SELECT m.stock,
            (SELECT COUNT(*) FROM lotes l WHERE l.material_id=m.id) AS n_lotes,
            COALESCE((SELECT SUM(MAX(0, l.cantidad_activa - COALESCE(l.cantidad_reservada,0)))
                      FROM lotes l WHERE l.material_id=m.id), 0) AS libre
        FROM materiales m WHERE m.id=?""", (material_id,), one=True)
    if not m:
        return 0.0, 0.0
    disponible = float(m["libre"] or 0) if m["n_lotes"] else float(m["stock"] or 0)
    en_camino = float(query(f"""SELECT COALESCE(SUM(MAX(0, i.cantidad - COALESCE(i.cantidad_recibida,0))),0) c
        FROM ordenes_compra_items i JOIN ordenes_compra oc ON oc.id=i.oc_id
        WHERE i.material_id=? AND oc.estado IN {OC_EN_CAMINO_SQL}""", (material_id,), one=True)["c"] or 0)
    return disponible, en_camino


def populate_ops_internal(oid, prod_id, qty):
    ops = query("SELECT * FROM proceso_operaciones WHERE producto_id=? ORDER BY CAST(orden AS INTEGER), orden", (prod_id,))
    for op in ops:
        _oo_nuevo = execute("""INSERT INTO orden_operaciones
            (orden_id,proceso_op_id,orden,nombre,categoria_maquina_id,maquina_id,
             tiempo_setup_min,tiempo_ciclo_seg,estado,qty_requerida,
             es_tercerizada,proveedor_id,precio_tercerizado,tiempo_minimo_dias)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (oid,op["id"],op["orden"],op["nombre"],op["categoria_maquina_id"],op["maquina_id"],
             op["tiempo_setup_min"],op["tiempo_ciclo_seg"],"Pendiente",_qty_operacion(op, qty),
             op["es_tercerizada"] if "es_tercerizada" in op.keys() else 0,
             op["proveedor_id"] if "proveedor_id" in op.keys() else None,
             op["precio_tercerizado"] if "precio_tercerizado" in op.keys() else 0,
             op["tiempo_minimo_dias"] if "tiempo_minimo_dias" in op.keys() else 0))
        _copiar_materiales_a_ot_op(_oo_nuevo, op["id"])

def populate_mats_internal(oid, prod_id, qty):
    # Se calculan con las operaciones que ya creó populate_ops_internal (y su
    # copia de materiales), con el mismo criterio que al editar la OT: ver
    # _materiales_requeridos_ot.
    for mid, (total, unidad) in _materiales_requeridos_ot(oid).items():
        execute("INSERT INTO orden_materiales (orden_id,material_id,cantidad_requerida,cantidad_asignada,unidad) VALUES (?,?,?,0,?)",
            (oid, mid, total, unidad))

# ── MRP ampliado ──────────────────────────────────────────────────────────────
@app.route("/api/mrp")
@login_required()
def mrp():
    criticos = []
    for r in query(f"""SELECT m.id,m.codigo,m.descripcion,m.categoria,m.stock,m.stock_min,m.stock_max,m.stock_min-m.stock AS faltante,m.unidad,p.razon proveedor,
            (SELECT s.numero FROM solicitudes_compra s WHERE s.material_id=m.id AND s.estado IN {SC_ABIERTAS_SQL} ORDER BY s.id DESC LIMIT 1) sc_activa
            FROM materiales m LEFT JOIN proveedores p ON p.id=m.proveedor_id WHERE m.stock<m.stock_min AND m.stock_min>0 ORDER BY (m.stock_min-m.stock) DESC"""):
        c = dict(r)
        # Cantidad a pedir con "+ SC": hasta el Máximo (o el Mínimo si no hay
        # Máximo), con el mismo criterio que el MRP: disponible libre por lote
        # más lo que ya viene en OC abiertas.
        disponible, en_camino = _disponible_material(c["id"])
        smin, smax = float(c["stock_min"] or 0), float(c["stock_max"] or 0)
        objetivo = smax if smax > smin else smin
        c["disponible"] = round(disponible, 3)
        c["en_camino"] = round(en_camino, 3)
        c["cant_sc"] = round(max(0.0, objetivo - disponible - en_camino), 3)
        criticos.append(c)
    return jsonify({
        "criticos": criticos,
        "ordenes_activas": [dict(r) for r in query("SELECT o.numero,o.descripcion,o.estado,o.fecha_entrega,o.cantidad,c.razon cliente,pr.nombre producto FROM ordenes o LEFT JOIN clientes c ON c.id=o.cliente_id LEFT JOIN productos pr ON pr.id=o.producto_id WHERE o.estado IN ('Pendiente','En proceso') ORDER BY o.fecha_entrega")],
        "oc_cliente_pendientes": [dict(r) for r in query("SELECT oc.*,c.razon cliente_nombre FROM ordenes_cliente oc JOIN clientes c ON c.id=oc.cliente_id WHERE oc.estado IN ('Recibida','Confirmada') ORDER BY oc.fecha_entrega")],
        "pronosticos_pendientes": [dict(r) for r in query("""SELECT p.id,p.codigo,p.periodos,p.fecha_emision,c.razon cliente_nombre,
            (SELECT COUNT(*) FROM pronostico_venta_items i WHERE i.pronostico_id=p.id AND i.cantidad>0
               AND i.id NOT IN (SELECT item_id FROM pronostico_item_ots)) items_pendientes
            FROM pronosticos_venta p LEFT JOIN clientes c ON c.id=p.cliente_id
            WHERE p.estado='Alta' AND EXISTS (
                SELECT 1 FROM pronostico_venta_items i WHERE i.pronostico_id=p.id AND i.cantidad>0
                  AND i.id NOT IN (SELECT item_id FROM pronostico_item_ots))
            ORDER BY p.fecha_emision DESC""")],
        # Solo OT abiertas. Cada paso cuenta una vez aunque tenga rutas
        # alternativas (requerido = el mayor de sus rutas, producido = la suma,
        # igual que _sincronizar_estado_paso), y lo pendiente nunca es negativo.
        "carga_por_sector": [dict(r) for r in query("""
            WITH pasos AS (
                SELECT oo.orden_id, oo.orden, MAX(oo.qty_requerida) req,
                       SUM(COALESCE(oo.qty_producida,0)) prod,
                       SUM(CASE WHEN oo.estado='Completada' THEN 1 ELSE 0 END) completas
                FROM orden_operaciones oo JOIN ordenes o ON o.id=oo.orden_id
                WHERE o.estado IN ('Pendiente','En proceso') AND COALESCE(oo.estado,'')!='Cancelada'
                GROUP BY oo.orden_id, oo.orden)
            SELECT cm.nombre sector, COUNT(*) ops_pendientes,
                   SUM(MAX(0, COALESCE(p.req,0) - p.prod)) piezas_pendientes
            FROM pasos p
            JOIN (SELECT DISTINCT orden_id, orden, categoria_maquina_id FROM orden_operaciones) r
              ON r.orden_id=p.orden_id AND r.orden=p.orden
            JOIN categorias_maquina cm ON cm.id=r.categoria_maquina_id
            WHERE p.completas=0
            GROUP BY cm.nombre ORDER BY ops_pendientes DESC""")],
    })


# Funciones de otras áreas. Van al final a propósito: así cada módulo ya
# definió todo lo suyo cuando otro lo importa, y no hay problemas de
# importación circular. Se usan recién al atender pedidos.
from .comun import (_copiar_materiales_a_ot_op, _sc_automaticas_activas,
    _sincronizar_estado_paso, OC_EN_CAMINO_SQL, SC_ABIERTAS_SQL)
from .productos import calcular_costo_producto, tiempo_std_min
from .ordenes import _generar_ott_para_ot, _recalcular_material_requerido_ot

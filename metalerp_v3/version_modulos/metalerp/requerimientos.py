"""Requerimientos productivos y su sincronización con OTT, pedidos y compras."""
from .nucleo import (app, auditoria_proceso, date, datetime, execute, jsonify,
    login_required, query, request)

# ── Requerimientos productivos ─────────────────────────────────────────────────
def _calc_estado_req(f_estimada, f_entrega, estado_actual=None):
    """Replica la fórmula del Excel de origen:
    - Con f_entrega cargada -> ENTREGADO.
    - Sin f_entrega y hoy > f_estimada -> VENCIDO.
    - Sin f_entrega y no vencido -> PROXIMO.
    ANULADO es un estado manual (no lo calcula la fórmula): si el registro
    ya está anulado y no se cargó entrega, se respeta esa marca manual.
    """
    if estado_actual == "ANULADO" and not f_entrega:
        return "ANULADO"
    if f_entrega:
        return "ENTREGADO"
    if f_estimada:
        try:
            fe = datetime.strptime(str(f_estimada)[:10], "%Y-%m-%d").date()
            if date.today() > fe:
                return "VENCIDO"
        except (ValueError, TypeError):
            pass
    return "PROXIMO"

def _calc_cumplimientos_req(f_estimada, f_entrega, cantidad_pedida, cantidad_entregada, cant_no_conforme):
    """Calcula cumple_fecha / cumple_cantidad / cumple_calidad a partir de los
    datos de entrega. Devuelve (cumple_fecha, cumple_cantidad, cumple_calidad),
    cada uno 0/1, o None si todavía no hay entrega registrada (nada que evaluar)."""
    if not f_entrega:
        return None, None, None
    cumple_fecha = None
    if f_estimada:
        try:
            fe = datetime.strptime(str(f_estimada)[:10], "%Y-%m-%d").date()
            fg = datetime.strptime(str(f_entrega)[:10], "%Y-%m-%d").date()
            cumple_fecha = 1 if fg <= fe else 0
        except (ValueError, TypeError):
            cumple_fecha = None
    cant_ent = cantidad_entregada or 0
    cant_ped = cantidad_pedida or 0
    cumple_cantidad = 1 if (cant_ped > 0 and cant_ent >= 0.9 * cant_ped) else 0
    nc = cant_no_conforme or 0
    cumple_calidad = 1 if nc == 0 else 0
    return cumple_fecha, cumple_cantidad, cumple_calidad

def _req_row_out(r):
    d = dict(r)
    d["estado"] = _calc_estado_req(d.get("f_estimada"), d.get("f_entrega"), d.get("estado"))
    if not d.get("cliente_nombre") and d.get("ot_origen_numero"):
        # Requerimientos de compra (materia prima) no tienen cliente propio:
        # se muestra la OT que originó la solicitud de compra en su lugar,
        # en la misma columna donde el resto de los requerimientos muestra
        # el cliente.
        d["cliente_nombre"] = d["ot_origen_numero"]
    return d

def _next_numero_req():
    """Próximo número correlativo para requerimientos_productivos, igual que
    el que sugiere el modal de carga manual del frontend: el mayor numero
    puramente numérico + 1 (arranca en 1 si no hay ninguno todavía)."""
    filas = query("SELECT numero FROM requerimientos_productivos")
    maxn = 0
    for f in filas:
        try: n = int(f["numero"])
        except Exception: continue
        if n > maxn: maxn = n
    return str(maxn + 1)

# ── Sincronización automática OTT -> Requerimiento productivo ────────────────
# Reemplaza la carga manual (y la vieja carga por IA/PDF, ya eliminada): cada
# vez que una orden tercerizada (ordenes_tercerizado / "OTT") cambia — se crea,
# se emite un remito de traslado hacia el proveedor, se recibe (total o
# parcialmente) o se completa — se refleja automáticamente en
# requerimientos_productivos, sin que nadie tenga que tipearlo en el Excel ni
# en la pantalla de carga manual. El vínculo entre ambas tablas es
# requerimientos_productivos.numero = ordenes_tercerizado.numero (ambos son
# únicos), así que el sync es un upsert por ese número.
@auditoria_proceso("sincronización OTT → requerimiento")
def _sync_requerimiento_desde_ott(ott_id):
    """Crea o actualiza el requerimiento_productivo espejo de una OTT.
    Se llama después de cualquier cambio relevante sobre la OTT (alta, emisión
    de remito, recepción parcial/total, devolución de rechazo, completado).
    No debe lanzar excepción hacia arriba: es un efecto secundario de
    sincronización, y un problema acá nunca debe hacer fallar la operación
    real sobre la OTT (que ya quedó grabada)."""
    try:
        ott = query("""
            SELECT ott.*, o.numero ot_numero, o.cliente_id ot_cliente_id,
                   o.descripcion ot_descripcion, o.cantidad ot_cantidad,
                   po.nombre proceso_nombre, po.producto_id proceso_producto_id,
                   pr.codigo prod_codigo, pr.unidad prod_unidad,
                   prov.razon proveedor_razon,
                   rem.numero remito_numero
            FROM ordenes_tercerizado ott
            LEFT JOIN ordenes o ON o.id=ott.ot_origen_id
            LEFT JOIN proceso_operaciones po ON po.id=ott.proceso_op_id
            LEFT JOIN productos pr ON pr.id=po.producto_id
            LEFT JOIN proveedores prov ON prov.id=ott.proveedor_id
            LEFT JOIN remitos rem ON rem.id=ott.remito_traslado_id
            WHERE ott.id=?""", (ott_id,), one=True)
        if not ott:
            return

        # OTT con SC del servicio: entra a Requerimientos productivos recién
        # cuando se hace su orden de compra. Sin OC (todavía, o porque se
        # anuló) el espejo no existe: se borra, salvo que alguien le haya
        # cargado datos a mano, y entonces queda ANULADO.
        oc_ott = None
        if query("SELECT 1 FROM solicitudes_compra WHERE ott_id=? AND ott_remito IS NULL", (ott_id,), one=True):
            oc_ott = query("""SELECT oc.numero, oc.creado FROM ordenes_compra_items i
                JOIN solicitudes_compra s ON s.id=i.solicitud_id
                JOIN ordenes_compra oc ON oc.id=i.oc_id
                WHERE s.ott_id=? AND oc.estado!='Anulada' ORDER BY oc.id LIMIT 1""", (ott_id,), one=True)
            if not oc_ott:
                previo = query("""SELECT id, f_necesidad, nro_icp, ubicacion_remito
                    FROM requerimientos_productivos WHERE numero=?""", (ott["numero"],), one=True)
                if previo:
                    if previo["f_necesidad"] or previo["nro_icp"] or previo["ubicacion_remito"]:
                        execute("UPDATE requerimientos_productivos SET estado='ANULADO' WHERE id=?", (previo["id"],))
                    else:
                        execute("DELETE FROM requerimientos_productivos WHERE id=?", (previo["id"],))
                return

        cantidad_pedida = float(ott["cantidad_enviada"] or 0)
        if cantidad_pedida <= 0:
            # Todavía no se remitió nada: usar lo planificado en la OT como
            # cantidad pedida provisoria (se corrige sola cuando se emita el
            # remito real y cantidad_enviada pase a tener un valor > 0).
            cantidad_pedida = float(ott["ot_cantidad"] or 0) or float(ott["cantidad_plan"] or 0)

        f_entrega = ott["fecha_retorno_real"]
        cantidad_entregada = float(ott["cantidad_recibida"] or 0) if f_entrega else None
        cant_no_conforme = None
        if f_entrega:
            # Rechazado y ya devuelto al proveedor: no llegó conforme.
            cant_no_conforme = float(ott["cantidad_rechazada_devuelta"] or 0)

        # Cantidad Aprobada = lo entregado menos lo no conforme. Solo se
        # puede calcular una vez que hay entrega; antes queda en None (se
        # completa sola apenas haya fecha de entrega, igual que
        # cantidad_entregada/cant_no_conforme).
        cantidad_aprobada = (cantidad_entregada - cant_no_conforme) if f_entrega else None

        estado = _calc_estado_req(ott["fecha_retorno_est"], f_entrega)
        if ott["estado"] == "Cancelado":
            estado = "ANULADO"
        cumple_fecha, cumple_cantidad, cumple_calidad = _calc_cumplimientos_req(
            ott["fecha_retorno_est"], f_entrega, cantidad_pedida, cantidad_entregada, cant_no_conforme)

        existente = query("SELECT id FROM requerimientos_productivos WHERE numero=?", (ott["numero"],), one=True)
        campos = dict(
            cliente_id=ott["ot_cliente_id"],
            codigo=ott["prod_codigo"] or ott["ot_numero"],
            material_proceso=ott["proceso_nombre"],
            provision="Tercerizado",
            cantidad_pedida=cantidad_pedida,
            unidad=ott["prod_unidad"],
            proveedor_id=ott["proveedor_id"],
            nro_oc_remito=oc_ott["numero"] if oc_ott else ott["remito_numero"],
            f_pedido=(oc_ott["creado"] if oc_ott else ott["creado"] or "")[:10] or None,
            f_necesidad=None,
            f_estimada=ott["fecha_retorno_est"],
            f_entrega=f_entrega,
            estado=estado,
            cantidad_entregada=cantidad_entregada,
            remito=ott["remito_numero"],
            nro_factura=None,
            cumple_fecha=cumple_fecha,
            cumple_cantidad=cumple_cantidad,
            cumple_calidad=cumple_calidad,
            cant_no_conforme=cant_no_conforme,
            obs=f"Auto-generado desde {ott['numero']} (OT {ott['ot_numero'] or '—'})",
        )
        if f_entrega:
            # Solo se agrega la clave (y por lo tanto se pisa en el UPDATE de
            # abajo) una vez que hay entrega real, igual que cantidad_entregada
            # y cant_no_conforme. Antes de eso no se incluye, para no pisar un
            # valor que alguien haya cargado a mano.
            campos["cantidad_aprobada"] = cantidad_aprobada
        if existente:
            # No pisar f_necesidad/nro_icp/ubicacion_remito/cantidad_aprobada
            # (antes de la entrega) si alguien los completó a mano sobre este
            # mismo requerimiento.
            sets = ",".join(f"{k}=?" for k in campos)
            execute(f"UPDATE requerimientos_productivos SET {sets} WHERE id=?",
                    (*campos.values(), existente["id"]))
        else:
            cols = ",".join(("numero", *campos.keys()))
            qs = ",".join("?" * (len(campos) + 1))
            execute(f"INSERT INTO requerimientos_productivos ({cols}) VALUES ({qs})",
                    (ott["numero"], *campos.values()))
    except Exception as e:
        # Sync best-effort: se loguea pero nunca interrumpe el flujo de la OTT.
        print(f"[requerimientos_productivos] No se pudo sincronizar OTT {ott_id}: {e}")

# ── Sincronización automática Pedido de cliente -> Requerimiento productivo ──
# Mismo patrón que _sync_requerimiento_desde_ott: cada ítem de pedido de
# cliente (ordenes_cliente_items) tiene su requerimiento_productivo espejo.
# Alta: al crear el ítem del pedido. Entrega: al emitir el remito.
# Vínculo numero = f"OC-CLI-ITEM-{item_id}" (único por ítem, estable en el
# tiempo aunque cambien cantidades/fechas).
@auditoria_proceso("sincronización pedido → requerimiento")
def _sync_requerimiento_desde_pedido(item_id):
    """Crea o actualiza el requerimiento_productivo espejo de un ítem de
    pedido de cliente (ordenes_cliente_items). Se llama después de crear el
    ítem (alta) y después de emitir/anular un remito que lo incluya (entrega).
    No debe lanzar excepción hacia arriba: es un efecto secundario de
    sincronización, y un problema acá nunca debe hacer fallar la operación
    real sobre el pedido/remito (que ya quedó grabada)."""
    try:
        item = query("""
            SELECT oci.*, oc.numero oc_numero, oc.cliente_id oc_cliente_id,
                   oc.fecha oc_fecha, oc.estado oc_estado,
                   pr.codigo prod_codigo, pr.unidad prod_unidad, pr.nombre prod_nombre
            FROM ordenes_cliente_items oci
            JOIN ordenes_cliente oc ON oc.id=oci.orden_cliente_id
            LEFT JOIN productos pr ON pr.id=oci.producto_id
            WHERE oci.id=?""", (item_id,), one=True)
        if not item:
            return

        numero = f"OC-CLI-ITEM-{item_id}"
        cantidad_pedida = float(item["cantidad"] or 0)

        entregado = query("""SELECT COALESCE(SUM(ri.cantidad),0) cant,
                   MAX(r.creado) ultima, MAX(r.numero) remito_numero
            FROM remito_items ri JOIN remitos r ON r.id=ri.remito_id
            WHERE ri.orden_cliente_item_id=? AND r.estado!='Anulado'""",
            (item_id,), one=True)
        cantidad_entregada = float(entregado["cant"] or 0)
        f_entrega = entregado["ultima"][:10] if (cantidad_entregada > 0 and entregado["ultima"]) else None

        estado = _calc_estado_req(item["fecha_deseada"], f_entrega)
        if item["oc_estado"] == "Cancelada":
            estado = "ANULADO"
        cumple_fecha, cumple_cantidad, cumple_calidad = _calc_cumplimientos_req(
            item["fecha_deseada"], f_entrega, cantidad_pedida, cantidad_entregada, None)

        existente = query("SELECT id FROM requerimientos_productivos WHERE numero=?", (numero,), one=True)
        campos = dict(
            cliente_id=item["oc_cliente_id"],
            codigo=item["prod_codigo"] or item["prod_nombre"],
            material_proceso=item["prod_nombre"],
            provision="Venta directa",
            cantidad_pedida=cantidad_pedida,
            unidad=item["prod_unidad"],
            proveedor_id=None,
            nro_oc_remito=item["oc_numero"],
            f_pedido=item["oc_fecha"][:10] if item["oc_fecha"] else None,
            f_necesidad=None,
            f_estimada=item["fecha_deseada"],
            f_entrega=f_entrega,
            estado=estado,
            cantidad_entregada=cantidad_entregada if f_entrega else None,
            remito=entregado["remito_numero"] if f_entrega else None,
            nro_factura=None,
            cumple_fecha=cumple_fecha,
            cumple_cantidad=cumple_cantidad,
            cumple_calidad=cumple_calidad,
            cant_no_conforme=None,
            obs=f"Auto-generado desde pedido {item['oc_numero']} (ítem {item_id})",
        )
        if existente:
            sets = ",".join(f"{k}=?" for k in campos)
            execute(f"UPDATE requerimientos_productivos SET {sets} WHERE id=?",
                    (*campos.values(), existente["id"]))
        else:
            cols = ",".join(("numero", *campos.keys()))
            qs = ",".join("?" * (len(campos) + 1))
            execute(f"INSERT INTO requerimientos_productivos ({cols}) VALUES ({qs})",
                    (numero, *campos.values()))
    except Exception as e:
        # Sync best-effort: se loguea pero nunca interrumpe el flujo del pedido/remito.
        print(f"[requerimientos_productivos] No se pudo sincronizar ítem de pedido {item_id}: {e}")

# ── Sincronización automática Compra (a proveedor) -> Requerimiento productivo
# Mismo patrón que OTT y pedidos de cliente, ahora para lo que se compra a
# proveedores: cada ítem de orden de compra (ordenes_compra_items) tiene su
# requerimiento_productivo espejo. Alta: al emitir la OC (crear el ítem).
# Entrega: al recibir mercadería (recibir_oc), y se vuelve a sincronizar al
# devolver rechazos (oc_devolver_rechazo), cerrar (cerrar_oc), completar
# (completar_oc) y anular (anular_oc) la OC. numero = f"OCP-ITEM-{item_id}",
# único y estable por ítem.
# Solo se sincronizan las compras "productivas": ítems cuyo material tiene
# categoria='Material' (materia prima que entra a producción). Insumos,
# Herramientas y demás categorías no generan requerimiento — no son compras
# productivas — y si el ítem no tiene material_id (descripción libre) tampoco
# se sincroniza, porque no hay forma de saber su categoría.
@auditoria_proceso("sincronización compra → requerimiento")
def _sync_requerimiento_desde_compra(item_id):
    """Crea o actualiza el requerimiento_productivo espejo de un ítem de
    orden de compra (ordenes_compra_items), solo si es una compra productiva
    (material categoria='Material'). Se llama después de emitir la OC (alta)
    y después de registrar una recepción sobre ese ítem (entrega).
    No debe lanzar excepción hacia arriba: es un efecto secundario de
    sincronización, y un problema acá nunca debe hacer fallar la operación
    real sobre la OC (que ya quedó grabada)."""
    try:
        item = query("""
            SELECT oci.*, oc.numero oc_numero, oc.proveedor_id oc_proveedor_id,
                   oc.creado oc_creado, oc.fecha_entrega_est oc_fecha_entrega_est,
                   oc.estado oc_estado,
                   m.codigo mat_codigo, m.descripcion mat_descripcion, m.unidad mat_unidad,
                   m.categoria mat_categoria,
                   sc.ot_origen_id sc_ot_origen_id
            FROM ordenes_compra_items oci
            JOIN ordenes_compra oc ON oc.id=oci.oc_id
            LEFT JOIN materiales m ON m.id=oci.material_id
            LEFT JOIN solicitudes_compra sc ON sc.id=oci.solicitud_id
            WHERE oci.id=?""", (item_id,), one=True)
        if not item:
            return
        if item["mat_categoria"] != "Material":
            # No es una compra productiva (Insumo, Herramienta, sin material_id, etc.)
            return
        if item["solicitud_id"] and query("SELECT ott_id FROM solicitudes_compra WHERE id=? AND ott_id IS NOT NULL",
                                          (item["solicitud_id"],), one=True):
            # Servicio de una OTT: su requerimiento es el espejo de la OTT.
            return

        # El "numero" visible es un correlativo normal (igual que el resto de
        # los requerimientos, ej. 12500), no un identificador técnico: el
        # vínculo estable para el upsert es origen_item_id, no numero (ver
        # migración de origen_item_id más arriba).
        existente_prev = query(
            "SELECT id, numero FROM requerimientos_productivos WHERE origen_item_id=?",
            (item_id,), one=True)
        numero = existente_prev["numero"] if existente_prev else _next_numero_req()
        cantidad_pedida = float(item["cantidad"] or 0)
        cantidad_recibida = float(item["cantidad_recibida"] or 0)
        # cantidad_entregada refleja siempre lo recibido hasta el momento (si
        # una devolución lo deja en 0, queda vacía). La entrega recién se da
        # por hecha (f_entrega) cuando llegó todo lo pedido, o cuando la OC se
        # cerró/completó con algo recibido: el saldo ya no va a llegar.
        # Mientras sea parcial el requerimiento sigue PROXIMO/VENCIDO, sin
        # f_entrega y sin cumplimientos (todavía no hay entrega que evaluar).
        cantidad_entregada = cantidad_recibida if cantidad_recibida > 0.0001 else None
        entrega_completa = cantidad_recibida >= cantidad_pedida - 0.0001
        oc_finalizada = item["oc_estado"] in ("Cerrada", "Completada")
        f_entrega = (item["fecha_recibida"][:10]
                     if (cantidad_entregada and item["fecha_recibida"]
                         and (entrega_completa or oc_finalizada)) else None)

        estado = _calc_estado_req(item["oc_fecha_entrega_est"], f_entrega)
        if item["oc_estado"] in ("Cancelada", "Anulada"):
            estado = "ANULADO"
        elif item["oc_estado"] == "Cerrada" and not cantidad_entregada:
            # Se cerró la OC sin recibir nada de este ítem: no va a llegar.
            estado = "ANULADO"
        cumple_fecha, cumple_cantidad, cumple_calidad = _calc_cumplimientos_req(
            item["oc_fecha_entrega_est"], f_entrega, cantidad_pedida, cantidad_entregada, None)

        campos = dict(
            cliente_id=None,
            codigo=item["mat_codigo"] or item["descripcion"],
            material_proceso=item["mat_descripcion"] or item["descripcion"],
            provision="Compra",
            cantidad_pedida=cantidad_pedida,
            unidad=item["mat_unidad"] or item["unidad"],
            proveedor_id=item["oc_proveedor_id"],
            nro_oc_remito=item["oc_numero"],
            f_pedido=item["oc_creado"][:10] if item["oc_creado"] else None,
            f_necesidad=None,
            f_estimada=item["oc_fecha_entrega_est"],
            f_entrega=f_entrega,
            estado=estado,
            cantidad_entregada=cantidad_entregada,
            remito=None,
            nro_factura=None,
            cumple_fecha=cumple_fecha,
            cumple_cantidad=cumple_cantidad,
            cumple_calidad=cumple_calidad,
            cant_no_conforme=None,
            obs=f"Auto-generado desde compra {item['oc_numero']} (ítem {item_id})",
            origen_item_id=item_id,
            ot_origen_id=item["sc_ot_origen_id"],
        )
        if existente_prev:
            sets = ",".join(f"{k}=?" for k in campos)
            execute(f"UPDATE requerimientos_productivos SET {sets} WHERE id=?",
                    (*campos.values(), existente_prev["id"]))
        else:
            cols = ",".join(("numero", *campos.keys()))
            qs = ",".join("?" * (len(campos) + 1))
            execute(f"INSERT INTO requerimientos_productivos ({cols}) VALUES ({qs})",
                    (numero, *campos.values()))
    except Exception as e:
        # Sync best-effort: se loguea pero nunca interrumpe el flujo de la compra.
        print(f"[requerimientos_productivos] No se pudo sincronizar ítem de compra {item_id}: {e}")

@app.route("/api/requerimientos_productivos", methods=["GET"])
@login_required()
def get_requerimientos_productivos():
    sql = """SELECT rp.*, c.razon cliente_nombre, p.razon proveedor_nombre,
               o.numero ot_origen_numero
        FROM requerimientos_productivos rp
        LEFT JOIN clientes c ON c.id=rp.cliente_id
        LEFT JOIN proveedores p ON p.id=rp.proveedor_id
        LEFT JOIN ordenes o ON o.id=rp.ot_origen_id
        WHERE 1=1"""
    params = []
    cliente_id = request.args.get("cliente_id")
    proveedor_id = request.args.get("proveedor_id")
    if cliente_id:
        sql += " AND rp.cliente_id=?"; params.append(cliente_id)
    if proveedor_id:
        sql += " AND rp.proveedor_id=?"; params.append(proveedor_id)
    sql += " ORDER BY (rp.f_estimada IS NULL), rp.f_estimada, rp.id DESC"
    raw_rows = query(sql, tuple(params))
    calidad_map = _calidad_requerimientos_bulk(raw_rows)
    rows = []
    for r in raw_rows:
        d = _req_row_out(r)
        d["_calidad"] = calidad_map.get(d["id"], {"evaluable": True, "aprobado": d.get("cumple_calidad"),
                                                    "origen": "manual", "lote_estado": None, "lote_pct": None})
        rows.append(d)
    estado = request.args.get("estado")
    if estado:
        rows = [r for r in rows if r["estado"] == estado]
    return jsonify(rows)

@app.route("/api/requerimientos_productivos", methods=["POST"])
@login_required(roles=["admin","almacen","vendedor"])
def create_requerimiento_productivo():
    d = request.json or {}
    if not d.get("numero"): return jsonify({"error":"Número requerido"}), 400
    if not d.get("cantidad_pedida"): return jsonify({"error":"Cantidad pedida requerida"}), 400
    estado = _calc_estado_req(d.get("f_estimada"), d.get("f_entrega"), d.get("estado"))
    cumple_fecha, cumple_cantidad, cumple_calidad = _calc_cumplimientos_req(
        d.get("f_estimada"), d.get("f_entrega"), d.get("cantidad_pedida"),
        d.get("cantidad_entregada"), d.get("cant_no_conforme"))
    rid = execute("""INSERT INTO requerimientos_productivos
        (numero,cliente_id,codigo,material_proceso,provision,cantidad_pedida,unidad,
         proveedor_id,nro_oc_remito,f_pedido,f_necesidad,f_estimada,f_entrega,estado,
         cantidad_entregada,remito,nro_factura,cumple_fecha,cumple_cantidad,cumple_calidad,
         nro_icp,cant_no_conforme,ubicacion_remito,cantidad_aprobada,obs)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (d["numero"], d.get("cliente_id") or None, d.get("codigo"), d.get("material_proceso"),
         d.get("provision"), d["cantidad_pedida"], d.get("unidad"),
         d.get("proveedor_id") or None, d.get("nro_oc_remito"), d.get("f_pedido"),
         d.get("f_necesidad"), d.get("f_estimada"), d.get("f_entrega"), estado,
         d.get("cantidad_entregada"), d.get("remito"), d.get("nro_factura"),
         cumple_fecha, cumple_cantidad, cumple_calidad,
         d.get("nro_icp"), d.get("cant_no_conforme"), d.get("ubicacion_remito"),
         d.get("cantidad_aprobada"), d.get("obs")))
    return jsonify({"ok":True,"id":rid}), 201

@app.route("/api/requerimientos_productivos/<int:rid>", methods=["PUT"])
@login_required(roles=["admin","almacen","vendedor"])
def update_requerimiento_productivo(rid):
    d = request.json or {}
    if not d.get("numero"): return jsonify({"error":"Número requerido"}), 400
    if not d.get("cantidad_pedida"): return jsonify({"error":"Cantidad pedida requerida"}), 400
    estado = _calc_estado_req(d.get("f_estimada"), d.get("f_entrega"), d.get("estado"))
    cumple_fecha, cumple_cantidad, cumple_calidad = _calc_cumplimientos_req(
        d.get("f_estimada"), d.get("f_entrega"), d.get("cantidad_pedida"),
        d.get("cantidad_entregada"), d.get("cant_no_conforme"))
    execute("""UPDATE requerimientos_productivos SET
        numero=?,cliente_id=?,codigo=?,material_proceso=?,provision=?,cantidad_pedida=?,unidad=?,
        proveedor_id=?,nro_oc_remito=?,f_pedido=?,f_necesidad=?,f_estimada=?,f_entrega=?,estado=?,
        cantidad_entregada=?,remito=?,nro_factura=?,cumple_fecha=?,cumple_cantidad=?,cumple_calidad=?,
        nro_icp=?,cant_no_conforme=?,ubicacion_remito=?,cantidad_aprobada=?,obs=? WHERE id=?""",
        (d["numero"], d.get("cliente_id") or None, d.get("codigo"), d.get("material_proceso"),
         d.get("provision"), d["cantidad_pedida"], d.get("unidad"),
         d.get("proveedor_id") or None, d.get("nro_oc_remito"), d.get("f_pedido"),
         d.get("f_necesidad"), d.get("f_estimada"), d.get("f_entrega"), estado,
         d.get("cantidad_entregada"), d.get("remito"), d.get("nro_factura"),
         cumple_fecha, cumple_cantidad, cumple_calidad,
         d.get("nro_icp"), d.get("cant_no_conforme"), d.get("ubicacion_remito"),
         d.get("cantidad_aprobada"), d.get("obs"), rid))
    return jsonify({"ok":True})

@app.route("/api/requerimientos_productivos/<int:rid>/entrega", methods=["PUT"])
@login_required(roles=["admin","almacen","vendedor"])
def registrar_entrega_requerimiento(rid):
    """Registra los datos de recepción de un requerimiento y recalcula
    automáticamente el estado y los 3 indicadores de cumplimiento."""
    r = query("SELECT * FROM requerimientos_productivos WHERE id=?", (rid,), one=True)
    if not r: return jsonify({"error":"Requerimiento no encontrado"}), 404
    d = request.json or {}
    if not d.get("f_entrega"): return jsonify({"error":"Fecha de entrega requerida"}), 400
    cantidad_entregada = d.get("cantidad_entregada")
    cant_no_conforme = d.get("cant_no_conforme")
    # Cantidad Aprobada: si mandaron un valor explícito lo respeta (por si el
    # usuario la corrige a mano), si no la calcula como entregada - no conforme.
    if "cantidad_aprobada" in d:
        cantidad_aprobada = d.get("cantidad_aprobada")
    elif cantidad_entregada is not None:
        cantidad_aprobada = float(cantidad_entregada or 0) - float(cant_no_conforme or 0)
    else:
        cantidad_aprobada = None
    estado = _calc_estado_req(r["f_estimada"], d.get("f_entrega"))
    cumple_fecha, cumple_cantidad, cumple_calidad = _calc_cumplimientos_req(
        r["f_estimada"], d.get("f_entrega"), r["cantidad_pedida"], cantidad_entregada, cant_no_conforme)
    execute("""UPDATE requerimientos_productivos SET
        f_entrega=?,cantidad_entregada=?,remito=?,nro_factura=?,cant_no_conforme=?,
        cantidad_aprobada=?,estado=?,cumple_fecha=?,cumple_cantidad=?,cumple_calidad=? WHERE id=?""",
        (d.get("f_entrega"), cantidad_entregada, d.get("remito"), d.get("nro_factura"),
         cant_no_conforme, cantidad_aprobada, estado, cumple_fecha, cumple_cantidad, cumple_calidad, rid))
    return jsonify({"ok":True})

@app.route("/api/requerimientos_productivos/<int:rid>", methods=["DELETE"])
@login_required(roles=["admin"])
def delete_requerimiento_productivo(rid):
    execute("DELETE FROM requerimientos_productivos WHERE id=?", (rid,))
    return jsonify({"ok":True})


# Funciones de otras áreas. Van al final a propósito: así cada módulo ya
# definió todo lo suyo cuando otro lo importa, y no hay problemas de
# importación circular. Se usan recién al atender pedidos.
from .dashboard import _calidad_requerimientos_bulk

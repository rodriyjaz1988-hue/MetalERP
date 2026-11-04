"""Órdenes de trabajo de terceros (OTT): envío, retorno, rechazos y SC del servicio."""
from .nucleo import (_mon_o_actual, app, auditoria_proceso, date, execute, jsonify,
    login_required, next_numero_sc, query, request, session, siguiente_numero)

# ══════════════════════════════════════════════════════════════════════════════
# OTT — Órdenes de Trabajo de Terceros
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/ott", methods=["GET"])
@login_required()
def get_ott_list():
    estado = request.args.get("estado")
    prov_id = request.args.get("proveedor_id")
    sql = """SELECT ott.*,
        o.numero ot_numero, o.estado ot_estado, p.razon proveedor_nombre,
        po.nombre op_nombre, po.orden op_orden,
        pr.nombre producto_nombre, pr.codigo producto_codigo,
        mse.codigo material_codigo, mse.descripcion material_descripcion,
        (SELECT GROUP_CONCAT(sc.numero, ', ') FROM solicitudes_compra sc WHERE sc.ott_id=ott.id) sc_numeros,
        (SELECT GROUP_CONCAT(oc.numero || CASE WHEN oc.estado IN ('Pendiente aprobacion','Borrador') THEN ' (a aprobar)' ELSE '' END, ', ')
            FROM ordenes_compra_items i JOIN solicitudes_compra sc ON sc.id=i.solicitud_id
            JOIN ordenes_compra oc ON oc.id=i.oc_id
            WHERE sc.ott_id=ott.id AND oc.estado!='Anulada') oc_numeros,
        COALESCE((SELECT l.cantidad_rechazada FROM lotes l WHERE l.id=ott.lote_retorno_id), 0) AS rechazado_pendiente_devolver,
        (SELECT l.estado FROM lotes l WHERE l.id=ott.lote_retorno_id) AS lote_retorno_estado,
        -- Total a mandar al proveedor: mismo criterio que la SC del servicio
        -- (_asegurar_sc_ott): cantidad de la operación, o la planificada de
        -- una OTT manual, o la de la OT.
        COALESCE(NULLIF(oo.qty_requerida,0), NULLIF(ott.cantidad_plan,0), o.cantidad, 0) AS cantidad_total
        FROM ordenes_tercerizado ott
        LEFT JOIN materiales mse ON mse.id=ott.material_se_id
        LEFT JOIN ordenes o ON o.id=ott.ot_origen_id
        LEFT JOIN proveedores p ON p.id=ott.proveedor_id
        LEFT JOIN proceso_operaciones po ON po.id=ott.proceso_op_id
        LEFT JOIN productos pr ON pr.id=po.producto_id
        LEFT JOIN orden_operaciones oo ON oo.id=ott.operacion_id
        WHERE 1=1"""
    params = []
    if estado:
        sql += " AND ott.estado=?"; params.append(estado)
    if prov_id:
        sql += " AND ott.proveedor_id=?"; params.append(prov_id)
    sql += " ORDER BY ott.creado DESC"
    return jsonify([dict(r) for r in query(sql, params)])

@app.route("/api/ott/<int:oid>", methods=["GET"])
@login_required()
def get_ott(oid):
    r = query("""SELECT ott.*,
        o.numero ot_numero, p.razon proveedor_nombre, p.telefono proveedor_tel,
        p.email proveedor_email, po.nombre op_nombre, po.orden op_orden,
        pr.nombre producto_nombre, pr.codigo producto_codigo,
        rem.numero remito_numero, remdev.numero remito_devolucion_numero,
        oo.qty_requerida oo_qty_requerida,
        oo.orden_id oo_orden_id, oo.orden oo_orden,
        mse.codigo material_codigo, mse.descripcion material_descripcion,
        l.cantidad_rechazada lote_cantidad_rechazada
        FROM ordenes_tercerizado ott
        LEFT JOIN materiales mse ON mse.id=ott.material_se_id
        LEFT JOIN ordenes o ON o.id=ott.ot_origen_id
        LEFT JOIN proveedores p ON p.id=ott.proveedor_id
        LEFT JOIN proceso_operaciones po ON po.id=ott.proceso_op_id
        LEFT JOIN productos pr ON pr.id=po.producto_id
        LEFT JOIN remitos rem ON rem.id=ott.remito_traslado_id
        LEFT JOIN remitos remdev ON remdev.id=ott.remito_devolucion_id
        LEFT JOIN orden_operaciones oo ON oo.id=ott.operacion_id
        LEFT JOIN lotes l ON l.id=ott.lote_retorno_id
        WHERE ott.id=?""", (oid,), one=True)
    if not r: return jsonify({"error":"OTT no encontrada"}), 404
    r = dict(r)
    # lotes.cantidad_rechazada ya baja al devolver (ver ott_devolver_rechazo):
    # lo que queda ahí es lo rechazado que sigue en planta. Restarle además
    # lo devuelto lo descontaba dos veces y un segundo rechazo no se podía
    # devolver nunca.
    r["rechazado_pendiente_devolver"] = round(float(r.get("lote_cantidad_rechazada") or 0), 6)
    # Cantidad disponible para remitir. Prioridad:
    # 1) Si hay una operación ANTERIOR dentro de la misma OT (misma
    #    secuencia de proceso), lo disponible es lo que esa operación
    #    anterior ya PRODUJO (orden_operaciones.qty_producida) — sea una
    #    operación propia (cargada por Novedades) o tercerizada (recibida
    #    y aprobada) — menos lo que ya se remitió de esta OTT. Esto es lo
    #    que corresponde en un proceso multi-nivel: el semielaborado recién
    #    salido de un paso previo puede no estar todavía reflejado en
    #    materiales.stock (eso solo pasa automáticamente cuando el paso
    #    previo también fue tercerizado y su lote de retorno ya fue
    #    Aprobado; una operación propia completada por Novedades NUNCA
    #    vuelca su producción a materiales.stock, solo queda registrada en
    #    qty_producida de esa operación — de ahí el bug donde el stock de
    #    la operación anterior "no aparecía" para remitir).
    # 2) Si no hay operación anterior (es el primer paso del proceso), se
    #    usa el stock general del material del producto si existe.
    # 3) Si tampoco hay stock cargado, se usa la cantidad planificada para
    #    la operación en la OT.
    cantidad_enviada = r.get("cantidad_enviada") or 0
    op_anterior = None
    if r.get("oo_orden_id") is not None and r.get("oo_orden") is not None:
        try:
            orden_num_int = float(r["oo_orden"])
        except Exception:
            orden_num_int = None
        if orden_num_int is not None:
            op_anterior = query("""SELECT qty_producida FROM orden_operaciones
                WHERE orden_id=? AND CAST(orden AS REAL) < ?
                ORDER BY CAST(orden AS REAL) DESC LIMIT 1""",
                (r["oo_orden_id"], orden_num_int), one=True)
    if op_anterior is not None:
        producido_anterior = float(op_anterior["qty_producida"] or 0)
        r["cantidad_disponible"] = max(producido_anterior - cantidad_enviada, 0)
        r["cantidad_disponible_origen"] = "produccion_previa"
    else:
        mat_stock = None
        prod_id = query("SELECT producto_id FROM proceso_operaciones WHERE id=?", (r["proceso_op_id"],), one=True)
        prod_id = prod_id["producto_id"] if prod_id else None
        if prod_id:
            # Primero el propio artículo PT (id=producto_id), después semielaborados.
            mat = query("SELECT stock FROM materiales WHERE producto_id=? AND activo=1 ORDER BY (id=producto_id) DESC, id LIMIT 1", (prod_id,), one=True)
            if mat: mat_stock = mat["stock"]
        if mat_stock is not None:
            # Acá NO se resta lo ya enviado: al emitir cada remito las piezas
            # salieron del depósito y materiales.stock ya bajó. Restarlas otra
            # vez las descontaba dos veces y el modal ofrecía 0 cuando todavía
            # quedaban piezas por mandar. Es el mismo criterio que usa
            # ott_emitir_remito para validar (ver rama `elif mat:` de allá).
            r["cantidad_disponible"] = max(mat_stock, 0)
            r["cantidad_disponible_origen"] = "stock"
        elif not r.get("operacion_id") and float(r.get("cantidad_plan") or 0) > 0:
            r["cantidad_disponible"] = max(float(r["cantidad_plan"]) - cantidad_enviada, 0)
            r["cantidad_disponible_origen"] = "cantidad_plan"
        else:
            r["cantidad_disponible"] = max((r.get("oo_qty_requerida") or 0) - cantidad_enviada, 0)
            r["cantidad_disponible_origen"] = "qty_requerida"

    # Tope adicional por insumos tipo 'material' cargados en la operación
    # (ver ott_emitir_remito para la validación real al confirmar el envío;
    # esto es solo para que el modal ya muestre/limite el valor correcto).
    if r.get("operacion_id"):
        # Mismo criterio que ott_emitir_remito: el material que representa la
        # operación comprada al tercero no es un insumo físico y no limita.
        _mat_ret = _material_retorno_operacion(r["operacion_id"])
        limite_insumo = None
        for ins in query("""SELECT om.material_id, om.cantidad, m.stock mat_stock
                FROM orden_operacion_materiales om JOIN materiales m ON m.id=om.material_id
                WHERE om.orden_operacion_id=? AND om.tipo='material'""", (r["operacion_id"],)):
            if _mat_ret and ins["material_id"] == _mat_ret:
                continue
            cant_unit = float(ins["cantidad"] or 0)
            if cant_unit <= 0:
                continue
            max_por_insumo = float(ins["mat_stock"] or 0) / cant_unit
            if limite_insumo is None or max_por_insumo < limite_insumo:
                limite_insumo = max_por_insumo
        if limite_insumo is not None and limite_insumo < r["cantidad_disponible"]:
            r["cantidad_disponible"] = round(limite_insumo, 3)
            r["cantidad_disponible_origen"] = "insumo"
    r["envio_bloqueado"] = _bloqueo_envio_ott(oid) if r.get("estado") not in ("Cancelado", "Completado") else None
    return jsonify(r)

@app.route("/api/ott", methods=["POST"])
@login_required(roles=["admin","operario"])
def create_ott():
    d = request.json
    if not d.get("proveedor_id"):
        return jsonify({"error":"Proveedor requerido"}), 400
    # v147 (punto 10): OTT manual — sin OT/operación de origen. Exige el material
    # como insumo (el mismo que se genera al ingresar el remito) y la cantidad.
    es_manual = not d.get("operacion_id") and not d.get("proceso_op_id")
    material_id = d.get("material_id")
    cantidad_plan = 0
    if es_manual:
        if not material_id:
            return jsonify({"error":"Seleccioná el material como insumo (es el mismo que se generará al ingresar el remito)"}), 400
        mat = query("SELECT id,categoria FROM materiales WHERE id=? AND activo=1", (material_id,), one=True)
        if not mat:
            return jsonify({"error":"Material no encontrado"}), 404
        if mat["categoria"] == "Producto terminado":
            return jsonify({"error":"Un producto terminado no puede usarse como insumo de una OTT manual"}), 400
        try: cantidad_plan = float(d.get("cantidad") or 0)
        except (TypeError, ValueError): cantidad_plan = 0
        if cantidad_plan <= 0:
            return jsonify({"error":"Indicá la cantidad a enviar a terceros"}), 400
    numero = siguiente_numero("ordenes_tercerizado", "OTT-", 4)
    lid = execute("""INSERT INTO ordenes_tercerizado
        (numero,ot_origen_id,operacion_id,proceso_op_id,proveedor_id,
         precio_acordado,estado,es_ultimo_nivel,fecha_retorno_est,obs,creado_por,material_se_id,cantidad_plan)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (numero, d.get("ot_origen_id"), d.get("operacion_id"),
         d.get("proceso_op_id"), d["proveedor_id"],
         d.get("precio_acordado", 0), "Pendiente",
         1 if d.get("es_ultimo_nivel") else 0,
         d.get("fecha_retorno_est"), d.get("obs"), session["user_id"],
         material_id if es_manual else None, cantidad_plan))
    sc_numero = _asegurar_sc_ott(lid)
    _sync_requerimiento_desde_ott(lid)
    return jsonify({"ok": True, "id": lid, "numero": numero, "solicitud_compra": sc_numero}), 201

@app.route("/api/ott/<int:oid>", methods=["PUT"])
@login_required(roles=["admin","operario"])
def update_ott(oid):
    d = request.json
    # v147 (punto 9): el proveedor se puede cambiar solo antes de iniciarse la OTT
    # (antes del primer envío), porque al enviar se genera la solicitud de compra.
    _ott_act = query("SELECT proveedor_id,cantidad_enviada FROM ordenes_tercerizado WHERE id=?", (oid,), one=True)
    if not _ott_act: return jsonify({"error":"OTT no encontrada"}), 404
    if float(_ott_act["cantidad_enviada"] or 0) > 0 and d.get("proveedor_id") != _ott_act["proveedor_id"]:
        return jsonify({"error":"No se puede cambiar el proveedor: la OTT ya inició (tiene envíos)."}), 400
    execute("""UPDATE ordenes_tercerizado SET estado=?,proveedor_id=?,precio_acordado=?,
        fecha_retorno_est=?,fecha_envio=?,obs=? WHERE id=?""",
        (d.get("estado"), d.get("proveedor_id"), _mon_o_actual(d, "precio_acordado", "ordenes_tercerizado", oid),
         d.get("fecha_retorno_est"), d.get("fecha_envio"), d.get("obs"), oid))
    _sync_requerimiento_desde_ott(oid)
    _sync_sc_ott(oid)
    return jsonify({"ok": True})

@auditoria_proceso("SC automática por insumo de OTT")
def _generar_sc_insumo_ott(material_id, faltante, motivo):
    """Genera (o amplía, si ya hay una activa) una Solicitud de Compra por
    el faltante puntual de un material/insumo requerido para remitir una
    OTT — a diferencia de auto_generar_sc_bajo_stock, esto NO depende de
    stock_min/stock_max: es el faltante exacto para cubrir este remito.

    Desactivado por defecto: ver _sc_automaticas_activas()."""
    if not _sc_automaticas_activas():
        return None
    if faltante <= 0 or not material_id:
        return None
    mat = query("SELECT codigo,descripcion,unidad FROM materiales WHERE id=?", (material_id,), one=True)
    if not mat:
        return None
    sc_exist = query("""SELECT id,cantidad FROM solicitudes_compra
        WHERE material_id=? AND estado IN ('Pendiente','Cotizada','En evaluación')
        ORDER BY id DESC LIMIT 1""", (material_id,), one=True)
    if sc_exist:
        nueva_cant = round(float(sc_exist["cantidad"] or 0) + faltante, 3)
        execute("""UPDATE solicitudes_compra SET cantidad=?,
            obs=COALESCE(obs,'') || ? WHERE id=?""",
            (nueva_cant, f" | +{round(faltante,3)} {mat['unidad']} por {motivo}.", sc_exist["id"]))
        return {"numero": None, "material": mat["descripcion"], "cantidad": round(faltante, 3), "actualizada": True}
    numero = next_numero_sc()
    execute("""INSERT INTO solicitudes_compra
        (numero,tipo,material_id,descripcion,cantidad,unidad,urgencia,estado,solicitante_id,obs)
        VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (numero, "Productiva", material_id, mat["descripcion"], round(faltante, 3), mat["unidad"],
         "Urgente", "Pendiente", session.get("user_id"),
         f"Generada automáticamente: faltante de insumo por {motivo}."))
    return {"numero": numero, "material": mat["descripcion"], "cantidad": round(faltante, 3)}


def _generar_ot_aux_insumo_ott(producto_id, faltante, motivo):
    """Genera (o amplía, si ya hay una OT auxiliar en curso para el mismo
    producto) una OT auxiliar para fabricar el faltante de un producto
    usado como insumo de una operación tercerizada, para cubrir un remito
    de OTT. Mismo patrón que las OT auxiliares del MRP (_gap_analysis_materiales),
    pero disparado puntualmente por el faltante de este remito."""
    if faltante <= 0 or not producto_id:
        return None
    prod = query("SELECT id,codigo,nombre FROM productos WHERE id=? AND activo=1", (producto_id,), one=True)
    if not prod:
        return None
    ot_exist = query("""SELECT id,numero,cantidad FROM ordenes
        WHERE producto_id=? AND estado IN ('Pendiente','En proceso')
          AND obs LIKE 'OT auxiliar generada automáticamente por remito de OTT%'
        ORDER BY id DESC LIMIT 1""", (producto_id,), one=True)
    if ot_exist:
        nueva_cant = round(float(ot_exist["cantidad"] or 0) + faltante, 3)
        _ajustar_cantidad_ot(ot_exist["id"], nueva_cant)
        return {"numero": ot_exist["numero"], "producto": prod["nombre"],
                "cantidad": round(faltante, 3), "actualizada": True}
    oid_aux, numero_aux = _crear_ot_mrp(
        producto_id, round(faltante, 3),
        descripcion=f"{prod['codigo']} — {prod['nombre']} (OT auxiliar por faltante de insumo)",
        prioridad="Alta", fecha_entrega=date.today().isoformat(), precio_venta=0,
        obs=f"OT auxiliar generada automáticamente por remito de OTT. Motivo: {motivo}.")
    return {"numero": numero_aux, "producto": prod["nombre"], "cantidad": round(faltante, 3)}


# ── Compra del servicio de cada OTT ───────────────────────────────────────────
# Cada OTT nace con su Solicitud de Compra (el servicio del tercero), con una
# cotización precargada del proveedor y el precio de la OTT. Las piezas no
# pueden salir al proveedor hasta que esa SC tenga su OC emitida y aprobada
# (ver _bloqueo_envio_ott). Las OTT que ya tenían piezas afuera antes de este
# cambio no tienen SC y siguen como estaban.
SC_OTT_INACTIVAS = ("Cancelada", "Rechazada")
OBS_COTIZACION_OTT = "Precargada desde la OTT"


def _sc_activa_ott(ott_id):
    return query("""SELECT * FROM solicitudes_compra WHERE ott_id=? AND ott_remito IS NULL
        AND estado NOT IN ('Cancelada','Rechazada') ORDER BY id DESC LIMIT 1""", (ott_id,), one=True)


def _asegurar_sc_ott(ott_id):
    """Crea la SC del servicio de la OTT si no tiene una activa. Devuelve el
    número de la SC creada, o None si no hacía falta (o la OTT no tiene
    proveedor, o ya está cerrada)."""
    ott = query("""SELECT ott.*, po.nombre op_nombre, o.numero ot_numero, o.cantidad ot_cantidad,
            o.estado ot_estado, oo.qty_requerida
        FROM ordenes_tercerizado ott
        LEFT JOIN proceso_operaciones po ON po.id=ott.proceso_op_id
        LEFT JOIN ordenes o ON o.id=ott.ot_origen_id
        LEFT JOIN orden_operaciones oo ON oo.id=ott.operacion_id
        WHERE ott.id=?""", (ott_id,), one=True)
    if not ott or ott["estado"] in ("Cancelado", "Completado") or not ott["proveedor_id"]:
        return None
    if ott["ot_estado"] in ("Cancelada", "Completada"):
        return None
    if _sc_activa_ott(ott_id):
        return None
    mat_id = _material_retorno_operacion(ott["operacion_id"]) if ott["operacion_id"] else None
    mat_id = mat_id or ott["material_se_id"]
    mat = query("SELECT id,descripcion,unidad,categoria FROM materiales WHERE id=?", (mat_id,), one=True) if mat_id else None
    total = float(ott["qty_requerida"] or 0) or float(ott["cantidad_plan"] or 0) or float(ott["ot_cantidad"] or 0)
    cantidad = total - float(ott["cantidad_enviada"] or 0)
    if cantidad <= 0:
        cantidad = total or 1
    try:
        solicitante = session.get("user_id")
    except RuntimeError:   # arranque, fuera de un pedido web
        solicitante = None
    numero = next_numero_sc()
    desc = (f"Servicio tercerizado {ott['op_nombre'] or 'OTT manual'}"
            + (f" — {mat['descripcion']}" if mat else "")
            + f" (OTT {ott['numero']}" + (f", OT {ott['ot_numero']}" if ott["ot_numero"] else "") + ")")
    sid = execute("""INSERT INTO solicitudes_compra
        (numero,tipo,material_id,descripcion,cantidad,unidad,urgencia,estado,ot_origen_id,
         solicitante_id,obs,ott_id)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (numero, "Productiva" if mat and mat["categoria"] == "Material" else "Indirecta",
         mat["id"] if mat else None, desc, cantidad, mat["unidad"] if mat else "u", "Normal",
         "Pendiente", ott["ot_origen_id"], solicitante or ott["creado_por"],
         f"Generada automáticamente al crear la OTT {ott['numero']}. Las piezas no se "
         "pueden enviar al proveedor hasta que se emita y apruebe la OC.", ott_id))
    precio = float(ott["precio_acordado"] or 0)
    execute("""INSERT INTO cotizaciones_compra
        (solicitud_id,proveedor_id,precio_unit,plazo_entrega_dias,seleccionada,obs)
        VALUES (?,?,?,?,?,?)""",
        (sid, ott["proveedor_id"], precio, 3, 1 if precio > 0 else 0,
         OBS_COTIZACION_OTT + (" — precio acordado" if precio > 0 else " — falta cargar el precio")))
    return numero


def _sync_sc_ott(ott_id):
    """Acompaña a la SC del servicio cuando cambia la OTT: si la OTT se cancela,
    la SC pendiente se cancela; si cambia el proveedor o el precio antes de
    comprar, se corrige la cotización precargada."""
    ott = query("SELECT * FROM ordenes_tercerizado WHERE id=?", (ott_id,), one=True)
    if not ott:
        return
    if ott["estado"] == "Cancelado":
        execute("""UPDATE solicitudes_compra SET estado='Cancelada'
            WHERE ott_id=? AND estado='Pendiente'""", (ott_id,))
        return
    sc = _sc_activa_ott(ott_id)
    if sc and sc["estado"] == "Pendiente" and ott["proveedor_id"]:
        precio = float(ott["precio_acordado"] or 0)
        execute("""UPDATE cotizaciones_compra SET proveedor_id=?, precio_unit=?, seleccionada=?,
                obs=? WHERE solicitud_id=? AND obs LIKE ?""",
            (ott["proveedor_id"], precio, 1 if precio > 0 else 0,
             OBS_COTIZACION_OTT + (" — precio acordado" if precio > 0 else " — falta cargar el precio"),
             sc["id"], OBS_COTIZACION_OTT + "%"))
    elif not sc and ott["estado"] == "Pendiente" and float(ott["cantidad_enviada"] or 0) == 0:
        _asegurar_sc_ott(ott_id)


def _bloqueo_envio_ott(ott_id):
    """None si las piezas de la OTT pueden salir al proveedor; si no, el motivo.
    Hace falta una OC emitida y aprobada para la SC del servicio. Las OTT sin
    ninguna SC (anteriores a este cambio) no se bloquean."""
    if not query("SELECT 1 FROM solicitudes_compra WHERE ott_id=? AND ott_remito IS NULL", (ott_id,), one=True):
        return None
    ocs = query("""SELECT oc.numero, oc.estado FROM ordenes_compra_items i
        JOIN solicitudes_compra s ON s.id=i.solicitud_id
        JOIN ordenes_compra oc ON oc.id=i.oc_id
        WHERE s.ott_id=? AND oc.estado!='Anulada' ORDER BY oc.id DESC""", (ott_id,))
    if any(o["estado"] not in ("Pendiente aprobacion", "Borrador") for o in ocs):
        return None
    if ocs:
        return (f"No se pueden enviar las piezas: la orden de compra {ocs[0]['numero']} del servicio "
                "todavía está pendiente de aprobación.")
    sc = _sc_activa_ott(ott_id)
    if sc:
        return (f"No se pueden enviar las piezas: falta emitir la orden de compra de la solicitud "
                f"{sc['numero']} (Compras).")
    numero = _asegurar_sc_ott(ott_id)
    return ("No se pueden enviar las piezas: la solicitud de compra del servicio estaba cancelada"
            + (f" y se generó una nueva, la {numero}." if numero else ".")
            + " Compras tiene que emitir la orden de compra.")


@auditoria_proceso("SC automática por envío a tercero")
def _generar_sc_por_envio_ott(ott_id, cantidad, num_rem):
    """v147 — punto 9: al emitir un envío de una OTT se genera una Solicitud de
    Compra por la cantidad enviada (servicio tercerizado), con una cotización
    precargada del proveedor de la OTT al precio acordado, SIN seleccionar:
    Compras debe confirmar el precio (seleccionando la cotización) y emitir la
    OC. Devuelve None si la OTT no tiene material de retorno definido (legado).

    Desactivado por defecto: ver _sc_automaticas_activas()."""
    if not _sc_automaticas_activas():
        return None
    if query("SELECT 1 FROM solicitudes_compra WHERE ott_id=? AND ott_remito IS NULL", (ott_id,), one=True):
        return None
    ott = query("""SELECT ott.*, po.nombre op_nombre, o.numero ot_numero
        FROM ordenes_tercerizado ott
        LEFT JOIN proceso_operaciones po ON po.id=ott.proceso_op_id
        LEFT JOIN ordenes o ON o.id=ott.ot_origen_id WHERE ott.id=?""", (ott_id,), one=True)
    if not ott or not ott["proveedor_id"]:
        return None
    mat_id = None
    if ott["operacion_id"]:
        mat_id = _material_retorno_operacion(ott["operacion_id"])
    elif ott["material_se_id"]:
        mat_id = ott["material_se_id"]
    if not mat_id:
        return None
    mat = query("SELECT id,codigo,descripcion,unidad,categoria FROM materiales WHERE id=?", (mat_id,), one=True)
    if not mat:
        return None
    numero = next_numero_sc()
    tipo_sc = "Productiva" if mat["categoria"] == "Material" else "Indirecta"
    desc = (f"Servicio tercerizado {ott['op_nombre'] or 'OTT manual'} — {mat['descripcion']} "
            f"(OTT {ott['numero']}, remito {num_rem})")
    sid = execute("""INSERT INTO solicitudes_compra
        (numero,tipo,material_id,descripcion,cantidad,unidad,urgencia,estado,ot_origen_id,
         solicitante_id,obs,ott_id,ott_remito)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (numero, tipo_sc, mat["id"], desc, cantidad, mat["unidad"], "Normal", "Pendiente",
         ott["ot_origen_id"], session.get("user_id"),
         f"Generada automáticamente por el envío {num_rem} de la OTT {ott['numero']}. "
         "Compras debe confirmar el precio y emitir la OC.",
         ott_id, num_rem))
    execute("""INSERT INTO cotizaciones_compra
        (solicitud_id,proveedor_id,precio_unit,plazo_entrega_dias,seleccionada,obs)
        VALUES (?,?,?,?,0,?)""",
        (sid, ott["proveedor_id"], float(ott["precio_acordado"] or 0), 3,
         "Precio precargado desde la OTT — confirmar antes de emitir la OC"))
    return {"numero": numero, "cantidad": cantidad, "material": mat["descripcion"]}

@app.route("/api/ott/<int:oid>/emitir_remito", methods=["POST"])
@login_required(roles=["admin","operario"])
def ott_emitir_remito(oid):
    """Genera remito de traslado: piezas salen del taller hacia el proveedor.
    Si el material ya existe en stock (ej. semielaborado de un paso anterior),
    se descuenta y se deja registro del movimiento de salida, para que mientras
    la pieza está afuera no figure como stock disponible en el taller.

    Soporta envíos parciales: se puede llamar más de una vez sobre la misma
    OTT (ej. remitir 50 de 100 y más adelante remitir el resto), igual que
    "registrar_retorno" ya soporta recepciones parciales. Cada llamada suma
    a cantidad_enviada y genera un remito nuevo (todos quedan vinculados a
    la OTT vía remitos.ott_id)."""
    ott = query("""SELECT ott.*, po.producto_id
        FROM ordenes_tercerizado ott
        LEFT JOIN proceso_operaciones po ON po.id=ott.proceso_op_id
        WHERE ott.id=?""", (oid,), one=True)
    if not ott: return jsonify({"error":"OTT no encontrada"}), 404
    if ott["estado"] not in ("Pendiente","Remito emitido","En proceso","Recibido"):
        return jsonify({"error":"No se puede emitir remito en el estado actual de la OTT"}), 400
    if not ott["proveedor_id"]:
        return jsonify({"error":"La OTT no tiene proveedor asignado: editala y elegí el proveedor antes de emitir el remito"}), 400
    _bloqueo = _bloqueo_envio_ott(oid)
    if _bloqueo:
        return jsonify({"error": _bloqueo}), 400
    if ott["ot_origen_id"]:
        _ot_est = query("SELECT estado FROM ordenes WHERE id=?", (ott["ot_origen_id"],), one=True)
        if _ot_est and _ot_est["estado"] in ("Cancelada", "Completada"):
            return jsonify({"error": f"No se puede emitir remito: la OT de origen está {_ot_est['estado']}"}), 400

    d = request.json or {}
    cantidad = float(d.get("cantidad") or 0)
    if cantidad <= 0:
        return jsonify({"error":"Ingresá la cantidad de piezas que se envían al proveedor"}), 400

    cantidad_enviada_previa = float(ott["cantidad_enviada"] or 0)

    # Cantidad disponible para remitir. Misma prioridad que usa GET /api/ott/<id>:
    # 1) Si hay una operación ANTERIOR en la misma OT, lo disponible es lo que
    #    esa operación ya PRODUJO (orden_operaciones.qty_producida) — sea propia
    #    (cargada por Novedades) o tercerizada y ya recibida — menos TODO lo ya
    #    enviado para este mismo paso (de esta OTT y de otras OTTs del mismo
    #    paso, si las hubiera). Este "stock auxiliar" interno nunca se refleja
    #    en materiales.stock cuando el paso anterior fue una operación propia,
    #    así que NO hay que exigir stock físico acá.
    # 2) Si no hay operación anterior (primer paso del proceso), se usa el
    #    stock físico del material si existe.
    # 3) Si tampoco hay stock cargado, se usa la cantidad planificada de la
    #    operación en la OT, también neta de todo lo ya enviado para ese paso.
    oo = query("SELECT qty_requerida, orden_id, orden FROM orden_operaciones WHERE id=?",
               (ott["operacion_id"],), one=True) if ott["operacion_id"] else None

    op_anterior = None
    if oo and oo["orden_id"] is not None and oo["orden"] is not None:
        try:
            orden_num_int = float(oo["orden"])
        except Exception:
            orden_num_int = None
        if orden_num_int is not None:
            op_anterior = query("""SELECT id, qty_producida, es_tercerizada FROM orden_operaciones
                WHERE orden_id=? AND CAST(orden AS REAL) < ?
                ORDER BY CAST(orden AS REAL) DESC LIMIT 1""",
                (oo["orden_id"], orden_num_int), one=True)

    # Total ya enviado para este paso, sumando TODAS las OTTs de esa
    # operación (incluida esta misma, con sus envíos previos) — así un
    # segundo envío parcial de esta OTT descuenta correctamente lo que
    # esta OTT ya remitió antes, y no solo lo de otras OTTs.
    total_ya_enviado = 0
    if ott["operacion_id"]:
        total_ya_enviado = query("""SELECT COALESCE(SUM(cantidad_enviada),0) tot
            FROM ordenes_tercerizado WHERE operacion_id=?""",
            (ott["operacion_id"],), one=True)["tot"]

    # Antes acá se buscaba "el material del producto" (materiales.producto_id),
    # pero desde la unificación de artículos eso devuelve el propio Producto
    # Terminado: enviar a terceros el PRIMER paso de la ruta validaba y
    # descontaba stock del PT, cuando lo que sale son piezas en bruto. Lo
    # único físico que se descuenta al enviar es el semielaborado de una
    # tercerizada anterior (abajo) y los insumos de la operación.
    mat = None

    # Si el paso anterior fue tercerizado, lo que se reenvía al segundo
    # proveedor es SU semielaborado, no un material cualquiera del producto.
    # La consulta de arriba no filtra por categoría y suele devolver el
    # material de Producto Terminado, así que el descuento de más abajo no
    # encontraba lotes vinculados y salteaba el consumo en silencio: el
    # semielaborado quedaba en stock aunque las piezas ya estuvieran de nuevo
    # afuera. Se resuelve por el PSE que congeló la OTT anterior.
    if op_anterior is not None and op_anterior["es_tercerizada"]:
        pse_previo = query("""SELECT m.id, m.stock, m.codigo
            FROM ordenes_tercerizado o JOIN materiales m ON m.id=o.material_se_id
            WHERE o.operacion_id=? AND o.material_se_id IS NOT NULL
            ORDER BY o.id DESC LIMIT 1""", (op_anterior["id"],), one=True)
        if pse_previo:
            mat = pse_previo

    # Tope adicional por insumos (materiales, no productos) cargados en la
    # operación como "Material/Producto como insumo": si la operación
    # requiere, por ejemplo, 3 unidades de un material por cada unidad de
    # pieza a tercerizar, y solo hay 300 en stock, no se puede remitir más
    # de 100 piezas aunque el resto de los límites (planificado, producido
    # por la operación anterior, etc.) permitan más — no alcanzaría material
    # para acompañar ese envío. Los insumos tipo 'producto' NO entran acá:
    # su faltante se resuelve generando una OT auxiliar (ver más abajo), no
    # limitando el remito.
    # El insumo que representa la operación comprada al tercero (el material
    # de retorno de la OTT) NO es un insumo físico: existe para poder
    # COMPRARLE la operación al proveedor, y es el que se genera cuando entra
    # su remito. No hay que exigirlo en stock para poder mandar las piezas ni
    # consumirlo: se adquiere con la SC que genera el propio envío.
    mat_retorno_id = _material_retorno_operacion(ott["operacion_id"]) if ott["operacion_id"] else None
    limite_insumo, limite_insumo_cod = None, None
    if ott["operacion_id"]:
        for ins in query("""SELECT om.material_id, om.cantidad, m.stock mat_stock, m.codigo mat_codigo
                FROM orden_operacion_materiales om JOIN materiales m ON m.id=om.material_id
                WHERE om.orden_operacion_id=? AND om.tipo='material'""", (ott["operacion_id"],)):
            if mat_retorno_id and ins["material_id"] == mat_retorno_id:
                continue
            cant_unit = float(ins["cantidad"] or 0)
            if cant_unit <= 0:
                continue
            max_por_insumo = float(ins["mat_stock"] or 0) / cant_unit
            if limite_insumo is None or max_por_insumo < limite_insumo:
                limite_insumo, limite_insumo_cod = max_por_insumo, ins["mat_codigo"]

    if op_anterior is not None:
        disponible = max(float(op_anterior["qty_producida"] or 0) - float(total_ya_enviado or 0), 0)
        if limite_insumo is not None:
            disponible = min(disponible, limite_insumo)
        if cantidad > disponible:
            return jsonify({"error": f"Cantidad excede lo producido en la operación anterior "
                                      f"(disponible: {disponible}, solicitado: {cantidad})"
                                      + (f" — limitado por stock de insumo {limite_insumo_cod}"
                                         if limite_insumo is not None and disponible < float(op_anterior["qty_producida"] or 0) - float(total_ya_enviado or 0)
                                         else "")}), 400
    elif mat:
        disponible = mat["stock"]
        if limite_insumo is not None:
            disponible = min(disponible, limite_insumo)
        if disponible < cantidad:
            return jsonify({"error": f"Stock insuficiente de {mat['codigo'] if disponible==mat['stock'] else limite_insumo_cod} "
                                      f"para enviar a tercerizar (disponible: {disponible}, solicitado: {cantidad})"}), 400
    elif oo and oo["qty_requerida"]:
        # Primer paso del proceso: el límite es la cantidad planificada de la
        # operación en la OT (no hay stock físico todavía para acotarlo),
        # neta de todo lo ya enviado para ese paso.
        disponible = max(float(oo["qty_requerida"]) - float(total_ya_enviado or 0), 0)
        if limite_insumo is not None:
            disponible = min(disponible, limite_insumo)
        if cantidad > disponible:
            return jsonify({"error": f"Cantidad excede lo planificado para la operación "
                                      f"(disponible: {disponible}, solicitado: {cantidad})"
                                      + (f" — limitado por stock de insumo {limite_insumo_cod}"
                                         if limite_insumo is not None and limite_insumo < float(oo["qty_requerida"]) - float(total_ya_enviado or 0)
                                         else "")}), 400
    elif not ott["operacion_id"] and float(ott["cantidad_plan"] or 0) > 0:
        # v147: OTT manual — el techo es la cantidad indicada al crearla.
        disponible = max(float(ott["cantidad_plan"]) - cantidad_enviada_previa, 0)
        if cantidad > disponible + 0.0001:
            return jsonify({"error": f"Cantidad excede lo indicado en la OTT (disponible: {disponible:g}, solicitado: {cantidad:g})"}), 400
        _mat_man = query("SELECT codigo,stock FROM materiales WHERE id=?", (ott["material_se_id"],), one=True)
        if _mat_man and float(_mat_man["stock"] or 0) + 0.0001 < cantidad:
            return jsonify({"error": f"Stock insuficiente del material insumo {_mat_man['codigo']} "
                                      f"(disponible: {float(_mat_man['stock'] or 0):g}, solicitado: {cantidad:g})"}), 400
    elif limite_insumo is not None and cantidad > limite_insumo:
        # No hay operación anterior, ni stock propio del semielaborado, ni
        # cantidad planificada cargada — el único límite que queda es el
        # insumo.
        return jsonify({"error": f"Cantidad excede la disponible según stock de insumo "
                                  f"{limite_insumo_cod} (disponible: {limite_insumo}, solicitado: {cantidad})"}), 400

    # Create remito de traslado
    num_rem = siguiente_numero("remitos", "REM-", 4)

    rid = execute("""INSERT INTO remitos (numero,cliente_id,fecha,estado,obs,creado_por,tipo,ott_id,ott_cantidad)
        VALUES (?,NULL,date('now','localtime'),'Emitido',?,?,?,?,?)""",
        (num_rem, d.get("obs", f"Traslado a proveedor externo (envío parcial: {cantidad})"
                               if cantidad_enviada_previa > 0 else "Traslado a proveedor externo"),
         session["user_id"], "traslado_ott", oid, cantidad))

    # El descuento de materiales.stock/lote solo corresponde cuando esa
    # cantidad efectivamente había entrado a inventario. Hay DOS casos:
    #  1) Primer paso del proceso, stock "físico" común (mat, op_anterior
    #     None): ya se descuenta más abajo.
    #  2) La operación anterior fue TERCERIZADA: su retorno se aprobó vía
    #     Lotes, lo que YA sumó esa cantidad a materiales.stock Y quedó
    #     reservado/vinculado a esta OT en un lote concreto (ver
    #     ott_registrar_retorno/update_lote). Al reenviar ese semielaborado a
    #     un SEGUNDO proveedor, hay que consumir ese mismo lote (igual que
    #     create_novedad) — si no, queda "cantidad_reservada"/stock fantasma
    #     que nunca se gasta aunque la pieza ya salió del taller de nuevo.
    #  Si la operación anterior fue PROPIA (no tercerizada), nunca se cargó
    #  a materiales.stock ni a ningún lote — no hay nada que descontar.
    stock_descontado = False
    if mat and op_anterior is None:
        execute("""INSERT INTO movimientos (material_id,lote_id,tipo,cantidad,referencia,usuario_id)
            VALUES (?,NULL,'salida',?,?,?)""",
            (mat["id"], cantidad, f"Envío a tercerizado OTT {ott['numero']} — {num_rem}",
             session["user_id"]))
        execute("UPDATE materiales SET stock=stock-? WHERE id=?", (cantidad, mat["id"]))
        stock_descontado = True
    elif op_anterior is not None and op_anterior["es_tercerizada"] and mat:
        vinculos = _lotes_vinculados_material(oo["orden_id"], mat["id"])
        if vinculos:
            plan, disponible_total, cubierto = _plan_consumo_adicional(vinculos, cantidad)
            if not cubierto:
                return jsonify({"error": f"Stock disponible insuficiente en lote(s) vinculados de "
                    f"\"{mat['codigo']}\" (disponible {disponible_total}, requerido {cantidad}) para "
                    f"reenviar a este proveedor."}), 400
            for lote_activo, consumo in plan:
                execute("""UPDATE lotes SET
                        cantidad_disponible=MAX(0, cantidad_disponible-?),
                        cantidad_activa=MAX(0, cantidad_activa-?),
                        cantidad_reservada=MAX(0, COALESCE(cantidad_reservada,0)-?),
                        estado=CASE WHEN cantidad_disponible-? <= 0 THEN 'Agotado' ELSE estado END
                    WHERE id=?""", (consumo, consumo, consumo, consumo, lote_activo["id"]))
                execute("""UPDATE materiales SET stock=MAX(0, stock-?), actualizado=datetime('now','localtime')
                    WHERE id=?""", (consumo, mat["id"]))
                execute("""UPDATE orden_lotes SET cantidad_consumida=COALESCE(cantidad_consumida,0)+?
                    WHERE orden_id=? AND lote_id=?""", (consumo, oo["orden_id"], lote_activo["id"]))
                execute("""INSERT INTO movimientos (material_id,lote_id,tipo,cantidad,referencia,usuario_id)
                    VALUES (?,?,'salida',?,?,?)""",
                    (mat["id"], lote_activo["id"], consumo,
                     f"Reenvío a tercerizado OTT {ott['numero']} — {num_rem} (Lote {lote_activo['numero']})",
                     session["user_id"]))
            stock_descontado = True

    # ── Insumos de la operación tercerizada (materiales/productos que se
    # mandan al proveedor junto con la pieza, cargados en "Material/Producto
    # como insumo" del proceso). Se consumen proporcionalmente a la cantidad
    # remitida (om.cantidad * cantidad). Si no alcanza el stock: el faltante
    # de un MATERIAL genera/amplía una Solicitud de Compra puntual; el
    # faltante de un PRODUCTO (semielaborado) genera/amplía una OT auxiliar
    # para fabricarlo. El remito igual se emite — no se bloquea por esto.
    insumos_op = query("""SELECT om.tipo, om.material_id, om.producto_id, om.cantidad,
            m.codigo mat_codigo, m.stock mat_stock
        FROM orden_operacion_materiales om
        JOIN materiales m ON m.id=om.material_id
        WHERE om.orden_operacion_id=?""", (ott["operacion_id"],)) if ott["operacion_id"] else []
    scs_insumo, ots_insumo = [], []
    for ins in insumos_op:
        if mat_retorno_id and ins["material_id"] == mat_retorno_id:
            continue   # es la operación que se le compra al tercero, no un insumo físico
        requerido = round(float(ins["cantidad"] or 0) * cantidad, 4)
        if requerido <= 0:
            continue
        stock_disp = float(ins["mat_stock"] or 0)
        consumir = min(requerido, stock_disp)
        faltante = round(requerido - consumir, 4)
        if consumir > 0:
            execute("""UPDATE materiales SET stock=stock-?, actualizado=datetime('now','localtime')
                WHERE id=?""", (consumir, ins["material_id"]))
            execute("""INSERT INTO movimientos (material_id,lote_id,tipo,cantidad,referencia,usuario_id)
                VALUES (?,NULL,'salida',?,?,?)""",
                (ins["material_id"], consumir,
                 f"Consumo insumo p/ remito OTT {ott['numero']} — {num_rem} ({ins['mat_codigo']})",
                 session["user_id"]))
        if faltante > 0:
            motivo = f"remito {num_rem} de OTT {ott['numero']}"
            if ins["tipo"] == "producto" and ins["producto_id"]:
                r = _generar_ot_aux_insumo_ott(ins["producto_id"], faltante, motivo)
                if r: ots_insumo.append(r)
            else:
                r = _generar_sc_insumo_ott(ins["material_id"], faltante, motivo)
                if r: scs_insumo.append(r)

    # v147 (punto 10): OTT manual — se consume el material insumo enviado.
    if not ott["operacion_id"] and ott["material_se_id"] and float(ott["cantidad_plan"] or 0) > 0:
        execute("""UPDATE materiales SET stock=MAX(0,stock-?), actualizado=datetime('now','localtime') WHERE id=?""",
                (cantidad, ott["material_se_id"]))
        execute("""INSERT INTO movimientos (material_id,lote_id,tipo,cantidad,referencia,usuario_id)
            VALUES (?,NULL,'salida',?,?,?)""",
            (ott["material_se_id"], cantidad, f"Envío a tercerizado OTT {ott['numero']} — {num_rem}", session["user_id"]))

    # Si ya estaba "En proceso" (hubo una recepción parcial previa), se
    # mantiene ese estado — no se retrocede a "Remito emitido". Si estaba
    # "Pendiente" o "Remito emitido", pasa (o queda) en "Remito emitido".
    nuevo_estado = ott["estado"] if ott["estado"] == "En proceso" else "Remito emitido"
    # El retorno estimado se fija al emitir el PRIMER remito: antes de enviar
    # el material no hay desde cuándo contar. Sale del plazo pactado con el
    # proveedor (proveedores.plazo_dias). Sin esto el campo quedaba siempre en
    # NULL para las OTT generadas automáticamente desde una OT, y entonces
    # _calc_cumplimientos_req devolvia cumple_fecha=None: ninguna OTT podia
    # aparecer en el grafico de Cumplimiento de entrega ni marcarse VENCIDA.
    # COALESCE: si alguien ya lo cargo a mano en la OTT, se respeta, y los
    # remitos parciales posteriores no lo recalculan.
    execute("""UPDATE ordenes_tercerizado SET estado=?,
        remito_traslado_id=?, fecha_envio=COALESCE(fecha_envio,date('now','localtime')),
        fecha_retorno_est=COALESCE(fecha_retorno_est,
            date(COALESCE(fecha_envio, date('now','localtime')), '+' ||
                 COALESCE((SELECT plazo_dias FROM proveedores
                           WHERE id=ordenes_tercerizado.proveedor_id), 3) || ' days')),
        cantidad_enviada=? WHERE id=?""",
        (nuevo_estado, rid, cantidad_enviada_previa + cantidad, oid))
    _sync_requerimiento_desde_ott(oid)
    # v147 (punto 9): cada envío genera una solicitud de compra por la cantidad
    # enviada; Compras confirma el precio y emite la OC.
    sc_ott = _generar_sc_por_envio_ott(oid, cantidad, num_rem)
    return jsonify({"ok": True, "remito_numero": num_rem, "remito_id": rid,
                     "solicitud_compra_ott": sc_ott,
                     "cantidad_enviada_total": cantidad_enviada_previa + cantidad,
                     "stock_descontado": stock_descontado,
                     "solicitudes_compra_insumo": scs_insumo,
                     "ots_auxiliares_insumo": ots_insumo})

@app.route("/api/ott/<int:oid>/registrar_retorno", methods=["POST"])
@login_required(roles=["admin","operario","almacen"])
def ott_registrar_retorno(oid):
    """Registra la recepción de piezas devueltas por el proveedor.

    Igual que "Recibir" en OC emitidas: se puede recibir en distintas
    ocasiones (recepciones parciales) mientras el proveedor va entregando.
    Todo lo recibido para una misma OTT va SIEMPRE al mismo lote (se
    amplía cantidad_disponible en vez de crear uno nuevo por cada
    recepción parcial, para no fragmentar la trazabilidad de calidad de
    una misma tanda de piezas tercerizadas). cantidad_original del lote se
    fija en cantidad_enviada de la OTT (no se va acumulando con cada
    recepción) para que un ciclo de rechazo → devolución → reingreso de
    reemplazo no la infle más allá de lo realmente enviado."""
    ott = query("""SELECT ott.*,po.producto_id,po.nombre op_nombre,pr.codigo prod_codigo,pr.nombre prod_nombre,
        pr.unidad prod_unidad,o.numero ot_numero
        FROM ordenes_tercerizado ott
        LEFT JOIN proceso_operaciones po ON po.id=ott.proceso_op_id
        LEFT JOIN productos pr ON pr.id=po.producto_id
        LEFT JOIN ordenes o ON o.id=ott.ot_origen_id
        WHERE ott.id=?""", (oid,), one=True)
    if not ott: return jsonify({"error":"OTT no encontrada"}), 404
    if ott["estado"] not in ("Remito emitido","En proceso"):
        return jsonify({"error":"Estado inválido para registrar retorno"}), 400

    d = request.json
    cantidad = float(d.get("cantidad", 1))
    if cantidad <= 0:
        return jsonify({"error":"Cantidad debe ser mayor a 0"}), 400
    # v147 (punto 9): el remito del proveedor se ingresa desde Recepción
    remito_prov = (d.get("remito") or "").strip()

    cantidad_enviada = float(ott["cantidad_enviada"] or 0)
    cantidad_recibida_previa = float(ott["cantidad_recibida"] or 0)
    if cantidad_enviada > 0:
        pendiente = cantidad_enviada - cantidad_recibida_previa
        if cantidad - pendiente > 0.0001:
            return jsonify({"error": f"La cantidad supera lo pendiente de recibir "
                                      f"(pendiente: {pendiente:g})"}), 400

    cantidad_recibida_total = cantidad_recibida_previa + cantidad
    # Recepción completa (cubre lo enviado, o no había cantidad_enviada
    # cargada) → OTT pasa a Recibido y se cierra la recepción. Si todavía
    # queda pendiente, queda "En proceso" para que el botón "Recibir" siga
    # disponible y se pueda seguir recibiendo contra el mismo lote/OT.
    completa = cantidad_enviada <= 0 or cantidad_recibida_total >= cantidad_enviada - 0.0001
    nuevo_estado = "Recibido" if completa else "En proceso"

    # ── Caso ÚLTIMA operación (PT → cliente) ───────────────────────────────
    # Acá NO se crea/amplía ningún lote a medida que llegan recepciones
    # parciales de la OTT. En su lugar, lo recibido va sumando directo al
    # "Total realizado" de la OT (orden_operaciones.qty_producida de la
    # última operación). El lote de PT se genera una sola vez, cuando la
    # operación llega al 100% y la OT se completa sola (descuento de
    # insumos + generación del lote PT vía _completar_ot_automatico /
    # generar_pt_faltante_si_corresponde) — mismo cierre que completar la
    # OT a mano.
    if ott["es_ultimo_nivel"]:
        execute("""UPDATE ordenes_tercerizado
            SET estado=?, cantidad_recibida=?,
                fecha_retorno_real=CASE WHEN ? THEN date('now','localtime') ELSE fecha_retorno_real END
            WHERE id=?""",
            (nuevo_estado, cantidad_recibida_total, completa, oid))

        ot_recien_completada = False
        if ott["operacion_id"]:
            op_row = query("SELECT id,qty_requerida,qty_producida,orden_id FROM orden_operaciones WHERE id=?",
                (ott["operacion_id"],), one=True)
            if op_row:
                nueva_qty_prod = float(op_row["qty_producida"] or 0) + cantidad
                qty_req = float(op_row["qty_requerida"] or 0)
                op_completa = qty_req > 0 and nueva_qty_prod >= qty_req - 0.0001
                usa_cajones = _ot_usa_cajones(op_row["orden_id"])
                execute("UPDATE orden_operaciones SET qty_producida=?,estado=? WHERE id=?",
                    (nueva_qty_prod, "Completada" if op_completa else "En proceso", op_row["id"]))
                consumir_herramientas_op(op_row["id"])
                _sync_cajones_op_tercerizada(op_row["id"], usa_cajones)
                execute("UPDATE ordenes SET estado='En proceso' WHERE id=? AND estado='Pendiente'",
                    (op_row["orden_id"],))
                if op_completa:
                    execute("UPDATE ordenes_tercerizado SET estado='Completado' WHERE id=?", (oid,))
                    _completar_ot_automatico(op_row["orden_id"])
                    _cajones_vincular_lote(op_row["orden_id"])
                    ot_completada_chk = query("SELECT estado FROM ordenes WHERE id=?", (op_row["orden_id"],), one=True)
                    ot_recien_completada = bool(ot_completada_chk and ot_completada_chk["estado"] == "Completada")

        resultado = {
            "ok": True,
            "es_ultimo_nivel": True,
            "completa": completa,
            "cantidad_recibida": cantidad_recibida_total,
            "cantidad_enviada": cantidad_enviada,
            "ot_completada": ot_recien_completada,
            "mensaje": (
                (f"Recepción cargada al Total realizado de la OT ({cantidad_recibida_total:g})."
                 + (" ¡OT completada, lote de PT generado!" if ot_recien_completada
                    else " Falta completar la cantidad de la operación para cerrar la OT."))
                if completa else
                f"Recepción parcial cargada al Total realizado de la OT "
                f"({cantidad_recibida_total:g} de {cantidad_enviada:g} recibido) — "
                "quedan piezas pendientes de recibir."
            )
        }
        _sync_requerimiento_desde_ott(oid)
        _ott_sync_oc_recibido(oid)
        return jsonify(resultado), 201

    # ── Caso operación INTERMEDIA (semielaborado) ──────────────────────────
    # Acá sí se necesita un lote físico: lo recibido alimenta la operación
    # siguiente del proceso, y esa operación se abastece desde Lotes como
    # cualquier otro insumo.
    #
    # Determine material_id for the lote: usar el material vinculado al
    # producto de la operación (semielaborado). Vínculo por producto_id
    # (FK), NO por codigo: dos productos distintos pueden compartir codigo
    # con un material ajeno por casualidad, y buscar solo por codigo
    # terminaría mezclando stock de cosas distintas.
    # Búsqueda por vínculo real (FK): producto_id + operacion_id (proceso_op_id
    # de la OTT). NO solo por producto_id: un mismo producto puede tener más
    # de una operación intermedia tercerizada, y cada una debe generar/usar
    # su PROPIO material de semielaborado (no compartir stock entre sí).
    # El semielaborado ya viene congelado desde que se creó la OTT: es el que
    # corresponde a la definición con la que las piezas salieron del taller,
    # aunque después se hayan editado los insumos en Procesos.
    mat_id = ott["material_se_id"] if "material_se_id" in ott.keys() else None
    if not mat_id:
        # OTT anterior al versionado: se resuelve contra la definición vigente
        # y se congela para las próximas recepciones parciales de esta misma
        # OTT, así todas caen en el mismo material.
        mat_id = _get_or_create_pse(ott["proceso_op_id"])
        if mat_id:
            execute("UPDATE ordenes_tercerizado SET material_se_id=? WHERE id=?",
                    (mat_id, oid))
    if not mat_id:
        # Sin proceso_op_id no hay de dónde derivar el semielaborado (la
        # operación del proceso fue borrada). Camino legado: material colgado
        # del producto, sin versionar.
        op_nombre = (ott["op_nombre"] or "SE").strip()
        codigo_base = f"{ott['prod_codigo']}-{op_nombre}"
        candidato = codigo_base
        intento = 1
        while query("SELECT id FROM materiales WHERE codigo=?", (candidato,), one=True):
            intento += 1
            candidato = f"{codigo_base}-{intento}"
        mat_id = execute("""INSERT INTO materiales
            (codigo,descripcion,categoria,producto_id,operacion_id,unidad,stock,stock_min,precio_unit,activo)
            VALUES (?,?,?,?,?,?,0,0,0,1)""",
            (candidato,
             f"{ott['prod_nombre']} — {op_nombre}",
             "Semielaborado",
             ott["producto_id"],
             ott["proceso_op_id"],
             ott["prod_unidad"] or "unid"))

    # Si ya existe un lote de retorno para esta OTT (de una recepción
    # parcial anterior), se amplía ese mismo lote en vez de crear uno
    # nuevo — todas las entregas del proveedor para esta OTT terminan en
    # un único lote. Queda "Ingresado" (pendiente de aprobación de
    # Calidad), igual que cualquier otro lote que entra al taller: no se
    # aprueba solo ni suma a stock acá, eso pasa recién en Lotes cuando se
    # clasifica como Aprobado (ver update_lote → _sync_ott_retorno_a_operacion),
    # que es el momento en que la operación tercerizada de la OT se da por
    # completada y la OT puede seguir con las operaciones siguientes.
    lote_existente = None
    if ott["lote_retorno_id"]:
        lote_existente = query("SELECT id,numero FROM lotes WHERE id=?", (ott["lote_retorno_id"],), one=True)

    if lote_existente:
        lote_id = lote_existente["id"]
        num_lote = lote_existente["numero"]
        # Si el lote ya había quedado totalmente clasificado (ej. se aprobó
        # todo lo recibido hasta ahora y quedó estado='Aprobado' o
        # 'Rechazado'), esta nueva entrega trae piezas SIN clasificar
        # todavía — hay que reabrirlo a "Ingresado" para que vuelva a
        # aparecer en la cola de Calidad como pendiente de clasificar. Si
        # ya estaba "Ingresado" (quedaba algo pendiente de antes), no hace
        # falta tocar el estado.
        #
        # cantidad_original NO se va sumando con cada recepción parcial: se
        # fija en cantidad_enviada de la OTT (el tamaño total acordado del
        # envío), igual que en los lotes que genera una OC (cantidad_original
        # = cantidad pedida). Si en cambio se fuera acumulando cantidad +
        # cantidad en cada recepción, un ciclo de rechazo → devolución →
        # reingreso del reemplazo (que vuelve a pasar por este mismo camino,
        # ver ott_devolver_rechazo) infla el original más allá de lo
        # realmente enviado (ej. recibo 90, rechazo y devuelvo esas 90,
        # reingresan 80 de reemplazo → el original terminaba en 90+80=170 en
        # vez de quedarse en los 100 que se enviaron en total). Si la OTT no
        # tiene cantidad_enviada cargada (caso legado), se sigue acumulando
        # como antes por no tener un techo de referencia.
        if cantidad_enviada > 0:
            execute("""UPDATE lotes SET cantidad_original=MAX(cantidad_original,?),
                cantidad_disponible=cantidad_disponible+?,
                estado=CASE WHEN estado IN ('Aprobado','Rechazado','Agotado') THEN 'Ingresado' ELSE estado END
                WHERE id=?""",
                (cantidad_enviada, cantidad, lote_id))
        else:
            execute("""UPDATE lotes SET cantidad_original=cantidad_original+?,
                cantidad_disponible=cantidad_disponible+?,
                estado=CASE WHEN estado IN ('Aprobado','Rechazado','Agotado') THEN 'Ingresado' ELSE estado END
                WHERE id=?""",
                (cantidad, cantidad, lote_id))
    else:
        num_lote = siguiente_numero("lotes", "Lote-OTT-", 3)

        # cantidad_original arranca en cantidad_enviada (el total acordado
        # del envío), no en lo recibido en esta primera entrega — ver
        # comentario arriba en la rama de ampliación. Si no hay
        # cantidad_enviada cargada, se usa lo recibido como antes.
        cantidad_original_inicial = cantidad_enviada if cantidad_enviada > 0 else cantidad
        lote_id = execute("""INSERT INTO lotes
            (numero,material_id,cantidad_original,cantidad_disponible,cantidad_activa,
             proveedor_id,estado,obs,creado_por)
            VALUES (?,?,?,?,0,?,?,?,?)""",
            (num_lote, mat_id, cantidad_original_inicial, cantidad, ott["proveedor_id"], "Ingresado",
             f"Retorno OTT {ott['numero']} — OT {ott['ot_numero'] or '—'} — pendiente de aprobación en Lotes",
             session["user_id"]))

    # Las piezas volvieron del tercero y están en el depósito: entran a
    # inventario ahora, las apruebe Calidad o no.
    execute("""UPDATE materiales SET stock=stock+?, actualizado=datetime('now','localtime')
        WHERE id=?""", (cantidad, mat_id))
    execute("UPDATE lotes SET stock_computado=1 WHERE id=?", (lote_id,))
    execute("""INSERT INTO movimientos (material_id,lote_id,tipo,cantidad,referencia,usuario_id)
        VALUES (?,?,'ingreso',?,?,?)""",
        (mat_id, lote_id, cantidad,
         f"Retorno OTT {ott['numero']} — ingreso a inventario, pendiente de clasificación"
         + (f" · Remito {remito_prov}" if remito_prov else ""),
         session["user_id"]))
    if remito_prov:
        execute("UPDATE lotes SET referencia_proveedor=COALESCE(NULLIF(referencia_proveedor,''),?) WHERE id=?",
                (remito_prov, lote_id))

    # ── Reservar el lote exclusivamente para la OT de origen ──────────────
    # Este material (semielaborado) es el resultado de una operación
    # tercerizada dentro de una OT puntual: no debe quedar disponible como
    # stock libre para cubrir otras OTs (ni para que el análisis de
    # faltantes/MRP lo tome para otra orden). Se reserva de la misma forma
    # que "asignar_lote_a_ot" (cantidad_reservada + orden_lotes), así el
    # lote queda atado exclusivamente a esta OT para la siguiente operación
    # del proceso, y no aparece como "disponible libre" para ninguna otra
    # orden.
    if ott["ot_origen_id"]:
        execute("UPDATE lotes SET cantidad_reservada=COALESCE(cantidad_reservada,0)+? WHERE id=?",
                (cantidad, lote_id))
        # Si el material (semielaborado) no estaba en la foto de
        # orden_materiales tomada al crear la OT, el UPDATE de abajo no
        # afecta ninguna fila y la reserva queda "huérfana": no aparece en
        # "Lotes asignados" y, peor, la novedad que debería consumirla la
        # salta en silencio (ver create_novedad). Se asegura la fila antes
        # de sumarle la cantidad asignada.
        existe_om = query("SELECT 1 FROM orden_materiales WHERE orden_id=? AND material_id=?",
            (ott["ot_origen_id"], mat_id), one=True)
        if not existe_om:
            execute("""INSERT INTO orden_materiales
                (orden_id,material_id,cantidad_requerida,cantidad_asignada,unidad)
                VALUES (?,?,0,0,(SELECT unidad FROM materiales WHERE id=?))""",
                (ott["ot_origen_id"], mat_id, mat_id))
        execute("""UPDATE orden_materiales SET cantidad_asignada=cantidad_asignada+?
            WHERE orden_id=? AND material_id=?""", (cantidad, ott["ot_origen_id"], mat_id))
        execute("""INSERT INTO orden_lotes (orden_id,lote_id,material_id,cantidad_usada,fecha)
            VALUES (?,?,?,?,date('now','localtime'))
            ON CONFLICT(orden_id,lote_id) DO UPDATE SET
                cantidad_usada=cantidad_usada+excluded.cantidad_usada,
                fecha=excluded.fecha""", (ott["ot_origen_id"], lote_id, mat_id, cantidad))
        execute("""INSERT INTO movimientos (material_id,lote_id,tipo,cantidad,referencia,usuario_id)
            VALUES (?,?,'reserva',?,?,?)""",
            (mat_id, lote_id, cantidad,
             f"Reservado exclusivo para {ott['ot_numero'] or '—'} | Retorno OTT {ott['numero']} "
             "(no disponible para otras OTs)", session["user_id"]))

    if completa:
        execute("""UPDATE ordenes_tercerizado
            SET estado=?, lote_retorno_id=?, cantidad_recibida=?,
                fecha_retorno_real=date('now','localtime') WHERE id=?""",
            (nuevo_estado, lote_id, cantidad_recibida_total, oid))
    else:
        execute("""UPDATE ordenes_tercerizado
            SET estado=?, lote_retorno_id=?, cantidad_recibida=? WHERE id=?""",
            (nuevo_estado, lote_id, cantidad_recibida_total, oid))

    resultado = {
        "ok": True,
        "lote_numero": num_lote,
        "lote_id": lote_id,
        "mat_id": mat_id,
        "es_ultimo_nivel": False,
        "completa": completa,
        "cantidad_recibida": cantidad_recibida_total,
        "cantidad_enviada": cantidad_enviada,
        "ot_completada": False,
        "mensaje": (
            (f"Lote {num_lote} " + ("actualizado" if lote_existente else "creado") +
             " — queda pendiente de aprobación en Lotes.")
            if completa else
            f"Recepción parcial cargada al lote {num_lote} "
            f"({cantidad_recibida_total:g} de {cantidad_enviada:g} recibido) — "
            "quedan piezas pendientes de recibir."
        )
    }
    _sync_requerimiento_desde_ott(oid)
    _ott_sync_oc_recibido(oid)
    return jsonify(resultado), 201

@app.route("/api/ott/<int:oid>/devolver_rechazo", methods=["POST"])
@login_required(roles=["admin","operario","almacen"])
def ott_devolver_rechazo(oid):
    """Devuelve al proveedor las piezas que Calidad rechazó del lote de
    retorno de esta OTT (paso intermedio — solo aplica a OTTs con
    lote_retorno_id, ver update_lote/_sync_ott_retorno_a_operacion).

    La cantidad a devolver es SIEMPRE la que ya está clasificada como
    Rechazada en el lote y que todavía no se devolvió antes (lote.cantidad_rechazada
    menos lo ya acumulado en ordenes_tercerizado.cantidad_rechazada_devuelta) —
    no se tipea a mano, para que coincida exactamente con lo que Calidad
    clasificó. Si el lote se clasifica de a partes (ej. se rechaza más
    después de una devolución previa), este endpoint se puede volver a
    llamar y solo devuelve el excedente nuevo.

    Efectos:
    1) Se descuenta del lote lo devuelto: cantidad_rechazada y
       cantidad_disponible bajan en esa medida (las piezas ya no están
       físicamente en el taller, dejan de contar en la partición del lote).
       cantidad_activa (aprobado) no se toca.
    2) cantidad_recibida de la OTT baja en la misma medida — así el
       proveedor queda "debiendo" esa cantidad otra vez: pendiente de
       recibir (cantidad_enviada - cantidad_recibida) vuelve a ser mayor a
       0 y el botón "Recibir" reaparece para cargar el reemplazo, que entra
       al MISMO lote (ott.lote_retorno_id no se toca).
    3) cantidad_rechazada_devuelta acumula lo devuelto, para trazabilidad y
       para no devolver dos veces lo mismo.
    4) Se emite un remito de devolución (tipo 'devolucion_ott') vinculado a
       la OTT, igual que el remito de traslado que se emite al enviar.
    """
    ott = query("""SELECT ott.* FROM ordenes_tercerizado ott WHERE ott.id=?""", (oid,), one=True)
    if not ott: return jsonify({"error":"OTT no encontrada"}), 404
    if not ott["lote_retorno_id"]:
        return jsonify({"error":"Esta OTT todavía no recibió ningún lote — no hay nada para devolver"}), 400
    if ott["es_ultimo_nivel"]:
        return jsonify({"error":"Las OTT de último nivel (PT → cliente) no generan lote clasificable "
            "por Calidad, no aplica devolución de rechazo acá"}), 400

    lote = query("SELECT * FROM lotes WHERE id=?", (ott["lote_retorno_id"],), one=True)
    if not lote: return jsonify({"error":"Lote de retorno no encontrado"}), 404

    ya_devuelto = float(ott["cantidad_rechazada_devuelta"] or 0)
    # Lo rechazado que sigue en planta: cantidad_rechazada del lote ya baja
    # en cada devolución (paso 1), no hay que restarle además ya_devuelto.
    cantidad = round(float(lote["cantidad_rechazada"] or 0), 6)
    if cantidad <= 0.0001:
        return jsonify({"error":"No hay piezas rechazadas pendientes de devolver para esta OTT"}), 400

    d = request.json or {}

    # 1) Descontar del lote lo devuelto (sale físicamente del taller)
    execute("""UPDATE lotes SET
            cantidad_disponible=MAX(0, cantidad_disponible-?),
            cantidad_rechazada=MAX(0, cantidad_rechazada-?)
        WHERE id=?""", (cantidad, cantidad, lote["id"]))
    # Las piezas entraron a inventario al recibirse el retorno
    # (stock_computado=1): al volver al proveedor, salen. Igual que en
    # oc_devolver_rechazo.
    if _lote_stock_computado(lote["id"]):
        execute("""UPDATE materiales SET stock=MAX(0, stock-?),
            actualizado=datetime('now','localtime') WHERE id=?""",
            (cantidad, lote["material_id"]))
    # La reserva del lote ya se liberó al clasificarlas como Rechazadas (ver
    # update_lote); acá se baja también lo asignado a la OT, porque el
    # reemplazo, al reingresar, lo vuelve a sumar (ver ott_registrar_retorno).
    if ott["ot_origen_id"]:
        execute("""UPDATE orden_lotes SET cantidad_usada=MAX(0, cantidad_usada-?)
            WHERE orden_id=? AND lote_id=?""", (cantidad, ott["ot_origen_id"], lote["id"]))
        execute("""UPDATE orden_materiales SET cantidad_asignada=MAX(0, cantidad_asignada-?)
            WHERE orden_id=? AND material_id=?""", (cantidad, ott["ot_origen_id"], lote["material_id"]))
    execute("""INSERT INTO movimientos (material_id,lote_id,tipo,cantidad,referencia,usuario_id)
        VALUES (?,?,'salida',?,?,?)""",
        (lote["material_id"], lote["id"], cantidad,
         f"Devolución a proveedor de piezas rechazadas — OTT {ott['numero']} (Lote {lote['numero']})",
         session["user_id"]))

    # 2) La OTT queda "debiendo" esa cantidad de nuevo del lado del proveedor
    cantidad_recibida_previa = float(ott["cantidad_recibida"] or 0)
    cantidad_recibida_nueva = max(0.0, cantidad_recibida_previa - cantidad)
    cantidad_enviada = float(ott["cantidad_enviada"] or 0)
    nuevo_estado = ott["estado"]
    if ott["estado"] != "Completado":
        nuevo_estado = "En proceso" if cantidad_recibida_nueva > 0 else (
            "Remito emitido" if cantidad_enviada > 0 else ott["estado"])

    # 3) Remito de devolución al proveedor
    num_rem = siguiente_numero("remitos", "REM-", 4)
    rid = execute("""INSERT INTO remitos (numero,cliente_id,fecha,estado,obs,creado_por,tipo,ott_id,ott_cantidad)
        VALUES (?,NULL,date('now','localtime'),'Emitido',?,?,?,?,?)""",
        (num_rem, d.get("obs", f"Devolución a proveedor — piezas rechazadas OTT {ott['numero']} "
                               f"(Lote {lote['numero']})"),
         session["user_id"], "devolucion_ott", oid, cantidad))

    execute("""UPDATE ordenes_tercerizado SET
            estado=?, cantidad_recibida=?, cantidad_rechazada_devuelta=?,
            remito_devolucion_id=?
        WHERE id=?""",
        (nuevo_estado, cantidad_recibida_nueva, ya_devuelto + cantidad, rid, oid))

    _ott_sync_oc_recibido(oid)
    _sync_requerimiento_desde_ott(oid)
    return jsonify({"ok": True, "cantidad_devuelta": cantidad, "remito_numero": num_rem,
        "remito_id": rid, "cantidad_recibida": cantidad_recibida_nueva,
        "cantidad_rechazada_devuelta": ya_devuelto + cantidad, "estado": nuevo_estado})

@app.route("/api/ott/<int:oid>/completar", methods=["POST"])
@login_required(roles=["admin","operario"])
def ott_completar(oid):
    """Confirmación MANUAL de cierre de la OTT (botón "Completar"). Aprobar o
    rechazar piezas del lote de retorno (ver update_lote/
    _sync_ott_retorno_a_operacion) solo va actualizando qty_producida de la
    operación de forma incremental — nunca marca nada como Completada por sí
    solo. Acá, y solo acá, es donde el usuario decide dar la OTT por
    cerrada, y recién en ese momento se marca Completada tanto la OTT como
    la operación de la OT asociada (con lo aprobado hasta este momento como
    qty_producida final)."""
    ott = query("""SELECT ott.*, oo.id oo_id, oo.estado oo_estado
        FROM ordenes_tercerizado ott
        LEFT JOIN orden_operaciones oo ON oo.id=ott.operacion_id
        WHERE ott.id=?""", (oid,), one=True)
    if not ott: return jsonify({"error": "OTT no encontrada"}), 404
    if ott["estado"] == "Completado":
        return jsonify({"ok": True})  # ya estaba completada, idempotente

    # Lo aprobado ACUMULADO del lote de retorno: lo que sigue en el lote más
    # lo que ya se consumió para esta OT (novedades de la operación siguiente
    # o reenvío a otro tercero). Mirar solo cantidad_activa pisaba
    # qty_producida con lo que quedaba en el lote y se perdían piezas (mismo
    # criterio que _sync_ott_retorno_a_operacion).
    aprobado = None
    if ott["lote_retorno_id"]:
        lote = query("SELECT cantidad_activa FROM lotes WHERE id=?", (ott["lote_retorno_id"],), one=True)
        if lote:
            aprobado = float(lote["cantidad_activa"] or 0)
            if ott["ot_origen_id"]:
                row = query("""SELECT COALESCE(cantidad_consumida,0) c FROM orden_lotes
                    WHERE orden_id=? AND lote_id=?""",
                    (ott["ot_origen_id"], ott["lote_retorno_id"]), one=True)
                aprobado += float(row["c"] or 0) if row else 0.0

    execute("UPDATE ordenes_tercerizado SET estado='Completado' WHERE id=?", (oid,))
    if ott["oo_id"] and ott["oo_estado"] != "Completada":
        if aprobado is not None:
            execute("UPDATE orden_operaciones SET estado='Completada',qty_producida=? WHERE id=?",
                (aprobado, ott["oo_id"]))
            consumir_herramientas_op(ott["oo_id"])
        else:
            execute("UPDATE orden_operaciones SET estado='Completada' WHERE id=?", (ott["oo_id"],))
    # El semielaborado NO se consume acá: lo consume la operación siguiente al
    # declarar sus novedades (ver _materiales_ott_pendientes_por_operacion) o
    # el reenvío a otro tercero. Consumirlo al cerrar la OTT dejaba a la
    # operación siguiente sin material y la OT trabada. Lo que sobre se da de
    # baja al completar la OT (ver _consumir_pse_sobrante_ot).
    _sync_requerimiento_desde_ott(oid)
    return jsonify({"ok": True})


# Funciones de otras áreas. Van al final a propósito: así cada módulo ya
# definió todo lo suyo cuando otro lo importa, y no hay problemas de
# importación circular. Se usan recién al atender pedidos.
from .comun import (_get_or_create_pse, _lotes_vinculados_material,
    _material_retorno_operacion, _plan_consumo_adicional, _sc_automaticas_activas,
    consumir_herramientas_op)
from .requerimientos import _sync_requerimiento_desde_ott
from .ordenes import _completar_ot_automatico
from .cajones import (_cajones_vincular_lote, _lote_stock_computado, _ot_usa_cajones,
    _sync_cajones_op_tercerizada)
from .mrp import _ajustar_cantidad_ot, _crear_ot_mrp
from .compras import _ott_sync_oc_recibido

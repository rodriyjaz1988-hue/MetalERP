"""Órdenes de trabajo (OT): alta, edición, operaciones, materiales y lotes asignados."""
from .nucleo import (_mon_o_actual, app, auditoria_proceso, execute, jsonify,
    login_required, query, request, session, siguiente_numero)

# ── Ordenes ───────────────────────────────────────────────────────────────────
@app.route("/api/ordenes", methods=["GET"])
@login_required()
def get_ordenes():
    estado = request.args.get("estado")
    sql = """SELECT o.*,c.razon cliente_nombre,p.nombre producto_nombre,p.codigo producto_codigo,
        (SELECT SUM(oo2.qty_producida) FROM orden_operaciones oo2
         WHERE oo2.orden_id=o.id AND oo2.orden=(
            SELECT oo.orden FROM orden_operaciones oo
            WHERE oo.orden_id=o.id ORDER BY CAST(oo.orden AS INTEGER) DESC, oo.orden DESC LIMIT 1
         )) total_realizado,
        (SELECT oci.orden_cliente_id FROM orden_cliente_item_ots ocio
         JOIN ordenes_cliente_items oci ON oci.id=ocio.item_id WHERE ocio.ot_id=o.id LIMIT 1) oc_id,
        (SELECT oc.numero FROM orden_cliente_item_ots ocio
         JOIN ordenes_cliente_items oci ON oci.id=ocio.item_id JOIN ordenes_cliente oc ON oc.id=oci.orden_cliente_id
         WHERE ocio.ot_id=o.id LIMIT 1) oc_numero,
        (SELECT COUNT(*) FROM orden_operaciones oo3 WHERE oo3.orden_id=o.id) ops_count,
        (SELECT COUNT(*) FROM orden_operaciones oo4 WHERE oo4.orden_id=o.id
         AND (oo4.estado!='Completada' OR oo4.qty_producida<oo4.qty_requerida)) ops_pendientes,
        (SELECT COALESCE(SUM(ot.precio_acordado * COALESCE(oo_ot.qty_requerida,1)),0)
         FROM ordenes_tercerizado ot LEFT JOIN orden_operaciones oo_ot ON oo_ot.id=ot.operacion_id
         WHERE ot.ot_origen_id=o.id AND ot.estado!='Cancelado') costo_terciarizado
        FROM ordenes o LEFT JOIN clientes c ON c.id=o.cliente_id LEFT JOIN productos p ON p.id=o.producto_id"""
    rows = query(sql+" WHERE o.estado=? ORDER BY o.id DESC",(estado,)) if estado else query(sql+" ORDER BY o.id DESC")
    result = []
    for r in rows:
        d = dict(r)
        d["lista_para_completar"] = bool(
            d.get("estado") not in ("Completada", "Cancelada")
            and (d.get("ops_count") or 0) > 0
            and (d.get("ops_pendientes") or 0) == 0
        )
        d["costo_total"] = float(d.get("costo_mat") or 0) + float(d.get("costo_terciarizado") or 0)
        result.append(d)
    return jsonify(result)

@app.route("/api/ordenes", methods=["POST"])
@login_required(roles=["admin","operario","vendedor"])
def create_orden():
    d = request.json
    if not d.get("producto_id"): return jsonify({"error":"Producto requerido"}), 400
    prod = query("SELECT codigo,nombre FROM productos WHERE id=?", (d["producto_id"],), one=True)
    if not prod: return jsonify({"error":"Producto no encontrado"}), 404
    descripcion = d.get("descripcion") or f"{prod['codigo']} — {prod['nombre']}"
    numero = siguiente_numero("ordenes", "OT-", 3)
    # El estado de una OT nueva siempre arranca en "Pendiente" — no se acepta
    # un estado inicial distinto desde el body, aunque el cliente lo mande
    # (el campo se sacó del formulario de creación en el frontend, pero se
    # blinda también acá por si se llama directo a la API).
    lid = execute("INSERT INTO ordenes (numero,cliente_id,producto_id,descripcion,detalle,cantidad,prioridad,estado,fecha_inicio,fecha_entrega,costo_mat,costo_mo,precio_venta,obs) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (numero,d.get("cliente_id"),d["producto_id"],descripcion,d.get("detalle"),d.get("cantidad",1),d.get("prioridad","Normal"),"Pendiente",d.get("fecha_inicio"),d.get("fecha_entrega"),d.get("costo_mat",0),d.get("costo_mo",0),0,d.get("obs")))
    if "requiere_material" in d and str(d.get("requiere_material")) in ("0","False","false"):
        execute("UPDATE ordenes SET requiere_material=0 WHERE id=?", (lid,))
    return jsonify({"ok":True,"id":lid,"numero":numero}), 201

def _generar_ott_para_ot(ot_id, ot_numero):
    """Genera la OTT (Orden de Trabajo de Terceros) correspondiente a cada
    operación tercerizada de la OT, si todavía no tiene una. Es idempotente:
    si la operación ya tiene una OTT vinculada (por operacion_id), no crea
    otra — así se puede llamar desde cualquier camino de creación/regeneración
    de operaciones de la OT (creación manual, explosión multinivel, MRP)
    sin duplicar.

    Esta OTT es la que sostiene la pausa de la OT: mientras no tenga un lote
    de retorno Aprobado, la operación tercerizada (y todo lo que va después
    en la ruta) queda bloqueada — ver create_novedad() y update_lote()."""
    ops = query("""SELECT oo.* FROM orden_operaciones oo
        WHERE oo.orden_id=? AND oo.es_tercerizada=1""", (ot_id,))
    max_orden = query("""SELECT MAX(CAST(orden AS INTEGER)) mx
        FROM orden_operaciones WHERE orden_id=?""", (ot_id,), one=True)["mx"]
    for op in ops:
        ya_existe = query("SELECT id FROM ordenes_tercerizado WHERE operacion_id=?", (op["id"],), one=True)
        if ya_existe:
            continue
        num_ott = siguiente_numero("ordenes_tercerizado", "OTT-", 4)
        try:
            es_ult = 1 if (max_orden is not None and int(op["orden"]) == int(max_orden)) else 0
        except Exception:
            es_ult = 0
        # El semielaborado que va a volver se congela acá, igual que el
        # proveedor y el precio: si más adelante alguien edita los insumos en
        # Procesos, esta OT sigue con el PSE que tenía y la definición nueva
        # arranca recién en las OT siguientes. Solo aplica a operaciones
        # INTERMEDIAS: la última no genera semielaborado sino el PT de la OT.
        mat_se_id = None
        # v147: si la operación define su material insumo, ése es el que se
        # genera al ingresar el remito; si no, se usa el semielaborado (legado).
        mat_ret_id = _material_retorno_operacion(op["id"])
        if mat_ret_id:
            mat_se_id = mat_ret_id
        elif not es_ult:
            try:
                mat_se_id = _get_or_create_pse(op["proceso_op_id"])
            except Exception as e:
                print(f"[WARN] No se pudo resolver el semielaborado de la "
                      f"operación {op['id']} al crear {num_ott}: {e}")
        nueva_ott = execute("""INSERT INTO ordenes_tercerizado
            (numero,ot_origen_id,operacion_id,proceso_op_id,proveedor_id,
             precio_acordado,estado,es_ultimo_nivel,material_se_id,creado_por)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (num_ott, ot_id, op["id"], op["proceso_op_id"],
             op["proveedor_id"] if "proveedor_id" in op.keys() else None,
             op["precio_tercerizado"] if "precio_tercerizado" in op.keys() else 0,
             "Pendiente", es_ult, mat_se_id, session.get("user_id")))
        _asegurar_sc_ott(nueva_ott)


@app.route("/api/ordenes/<int:oid>", methods=["GET"])
@login_required()
def get_orden(oid):
    r = query("""SELECT o.*,c.razon cliente_nombre,p.nombre producto_nombre,p.codigo producto_codigo
        FROM ordenes o
        LEFT JOIN clientes c ON c.id=o.cliente_id
        LEFT JOIN productos p ON p.id=o.producto_id
        WHERE o.id=?""", (oid,), one=True)
    if not r: return jsonify({"error":"OT no encontrada"}), 404
    return jsonify(dict(r))

def _completar_ot_automatico(oid):
    """Completa automáticamente una OT cuando su última operación (tercerizada)
    recibe la totalidad de lo remitido — mismo cierre que completar la OT a
    mano desde Órdenes de Trabajo (descuento de insumos sin lote + generación
    del lote de PT), pero disparado desde registrar_retorno de la OTT en vez
    de pasar por el formulario de edición de la OT. Es idempotente: si la OT
    ya está Completada, no hace nada."""
    orden_actual = query("SELECT * FROM ordenes WHERE id=?", (oid,), one=True)
    if not orden_actual or orden_actual["estado"] == "Completada":
        return
    numero_ot = orden_actual["numero"]
    ya_descontado = int(orden_actual["stock_descontado"] or 0) == 1
    try:
        if not ya_descontado:
            execute("UPDATE ordenes SET stock_descontado=1 WHERE id=?", (oid,))
            insumos = query("""
                SELECT om.material_id, m.codigo, m.descripcion,
                       SUM(cant_material(om.cantidad, oo.qty_producida, om.vida_util_herramienta)) consumo
                FROM orden_operaciones oo
                JOIN orden_operacion_materiales om ON om.orden_operacion_id=oo.id
                JOIN materiales m ON m.id=om.material_id
                WHERE oo.orden_id=? AND m.categoria='Insumo'   -- las herramientas se descuentan por novedad (consumir_herramientas_op)
                GROUP BY om.material_id
            """, (oid,))
            for ins in insumos:
                consumo = float(ins["consumo"] or 0)
                if consumo <= 0:
                    continue
                execute("""UPDATE materiales SET stock=MAX(0, stock-?),
                    actualizado=datetime('now','localtime') WHERE id=?""",
                    (consumo, ins["material_id"]))
                auto_generar_sc_bajo_stock(ins["material_id"], f"consumo insumos OT {numero_ot}")
                execute("""INSERT INTO movimientos
                    (material_id, lote_id, tipo, cantidad, referencia, usuario_id)
                    VALUES (?, NULL, 'salida', ?, ?, ?)""",
                    (ins["material_id"], consumo,
                     f"Consumo OT {numero_ot} — Insumo {ins['codigo']} (sin lote)",
                     session["user_id"]))
        consumir_herramientas_ot(oid)
        generar_pt_faltante_si_corresponde(oid)
        _consumir_pse_sobrante_ot(oid)
        execute("UPDATE lotes SET estado='Ingresado' WHERE estado='Abierto' AND numero LIKE ?",
            (numero_ot + "-C%",))
    except Exception as e:
        print(f"[OTT] No se pudo autocompletar OT {numero_ot} desde retorno OTT: {e}")
        return
    execute("UPDATE ordenes SET estado='Completada' WHERE id=?", (oid,))


@auditoria_proceso("generación automática de PT")
def generar_pt_faltante_si_corresponde(oid):
    """Red de seguridad: si la OT se marca 'Completada' pero el flujo de
    Novedades no generó (o generó parcialmente) el stock de Producto
    Terminado correspondiente, completa la diferencia acá.

    Es idempotente: calcula cuánto PT ya se generó (lote cuyo número
    coincide con el número de la OT) y solo agrega lo que falte hasta
    llegar a la cantidad solicitada en la OT. Si las Novedades ya
    generaron todo, no hace nada.
    """
    orden = query("SELECT * FROM ordenes WHERE id=?", (oid,), one=True)
    if not orden or not orden["producto_id"]:
        return
    prod = query("SELECT * FROM productos WHERE id=?", (orden["producto_id"],), one=True)
    if not prod:
        return

    # ── Cantidad real a generar como PT: es lo que EFECTIVAMENTE hizo la
    # ÚLTIMA operación de la ruta, sin techo. Si la OT se completa ANTES de
    # llegar al 100% (ej. se cancela/cierra con menos piezas de las
    # pedidas), el PT que corresponde generar es esa cantidad menor. Si en
    # cambio la última operación PRODUJO DE MÁS respecto de lo pedido (ej.
    # se pidieron 100 y la operación anterior había llegado a 108, entonces
    # esta última puede llegar hasta 108), el lote de PT también refleja
    # esas 108 — no se recorta al pedido original. Cada operación puede
    # cargar cualquier cantidad de piezas terminadas, sin tope respecto de
    # lo que haya producido la operación anterior.
    # Si el último paso tiene rutas alternativas (2+ operaciones con el
    # mismo número de "orden" — p.ej. dos máquinas/procesos posibles para el
    # mismo paso) y se trabajó en más de una, lo producido de ese paso es la
    # SUMA de lo que hizo cada alternativa, no solo una de ellas.
    ultimo_orden = query("""SELECT orden FROM orden_operaciones
        WHERE orden_id=? ORDER BY CAST(orden AS INTEGER) DESC, orden DESC LIMIT 1""", (oid,), one=True)
    target_qty = 0.0
    if ultimo_orden:
        target_qty = float(query("""SELECT COALESCE(SUM(qty_producida),0) s FROM orden_operaciones
            WHERE orden_id=? AND orden=?""", (oid, ultimo_orden["orden"]), one=True)["s"] or 0)
    if target_qty <= 0:
        return

    # Todo lo producido (incluso por encima de lo pedido en la OT) se vuelca
    # íntegramente al lote de PT de esta OT — ya no existe el desvío a
    # "Producto sin lote" para el excedente.
    lote_target = target_qty

    mat_pt = get_or_create_pt_material(prod)
    ot_lote_num = orden["numero"]

    lotes_usados = query("""SELECT l.numero FROM orden_lotes ol
        JOIN lotes l ON l.id=ol.lote_id WHERE ol.orden_id=?""", (oid,))
    lotes_ref = ", ".join(l["numero"] for l in lotes_usados) if lotes_usados else "—"

    # Un único lote de PT por OT (pendiente de Calidad). Si la OT trabaja con
    # cajones, sus cajones apuntan a este lote y Calidad clasifica por cajón.
    lote_pt_row = query("""SELECT id, numero, cantidad_original, cantidad_disponible,
        COALESCE(cantidad_activa,0) cantidad_activa,
        COALESCE(cantidad_rechazada,0) cantidad_rechazada
        FROM lotes WHERE numero=? AND material_id=?""",
        (ot_lote_num, mat_pt["id"]), one=True)
    ya_generado = float(lote_pt_row["cantidad_original"]) if lote_pt_row else 0.0
    faltante = lote_target - ya_generado
    if faltante < -0.0001 and lote_pt_row:
        # Se corrigio una novedad HACIA ABAJO: el lote tiene mas piezas de
        # las que la planta termino declarando. Se devuelve la diferencia
        # en vez de dejar el lote inflado.
        _reducir_lotes_pt(mat_pt["id"], [lote_pt_row], -faltante, ot_lote_num)
        return
    if faltante <= 0:
        return  # Las Novedades ya cubrieron toda la cantidad (del lote de esta OT)

    # lotes.numero es UNIQUE a nivel global (no por material). Si no hay
    # lote de PT para esta OT pero el número ya está tomado por un lote
    # de OTRO material, se le agrega un sufijo para no chocar.
    if not lote_pt_row:
        choque = query("SELECT id FROM lotes WHERE numero=?", (ot_lote_num,), one=True)
        if choque:
            ot_lote_num = f"{ot_lote_num}-PT"

    if lote_pt_row:
        execute("""UPDATE lotes SET
            cantidad_disponible=cantidad_disponible+?,
            cantidad_original=cantidad_original+?,
            estado='Ingresado', stock_computado=1
            WHERE id=?""",
            (faltante, faltante, lote_pt_row["id"]))
        lote_pt_id = lote_pt_row["id"]
    else:
        lote_pt_id = execute("""INSERT INTO lotes
            (numero,material_id,cantidad_original,cantidad_disponible,
             cantidad_activa,referencia_proveedor,estado,obs,creado_por,stock_computado)
            VALUES (?,?,?,?,?,?,?,?,?,1)""",
            (ot_lote_num, mat_pt["id"], faltante, faltante, 0,
             f"OT {ot_lote_num}", "Ingresado",
             f"Lotes MP: {lotes_ref}", session.get("user_id")))

    # Las piezas entraron al depósito: entran a inventario ahora, sin
    # esperar a Calidad. Clasificarlas después no vuelve a moverlas.
    execute("""UPDATE materiales SET stock=stock+?,
        actualizado=datetime('now','localtime') WHERE id=?""",
        (faltante, mat_pt["id"]))
    execute(
        "INSERT INTO movimientos (material_id,lote_id,tipo,cantidad,referencia,usuario_id) VALUES (?,?,?,?,?,?)",
        (mat_pt["id"], lote_pt_id, "ingreso", faltante,
         f"Generación automática al completar OT {ot_lote_num} — ingreso a inventario, pendiente de clasificación de Calidad | Lotes MP: {lotes_ref}",
         session.get("user_id")))
    return


@app.route("/api/ordenes/<int:oid>", methods=["PUT"])
@login_required(roles=["admin","operario","vendedor"])
def update_orden(oid):
    d = request.json
    if not d.get("producto_id"): return jsonify({"error":"Producto requerido"}), 400
    prod = query("SELECT codigo,nombre FROM productos WHERE id=?", (d["producto_id"],), one=True)
    if not prod: return jsonify({"error":"Producto no encontrado"}), 404
    descripcion = d.get("descripcion") or f"{prod['codigo']} — {prod['nombre']}"

    # Obtener estado actual antes de actualizar
    orden_actual = query("SELECT estado, stock_descontado, numero, producto_id, cantidad FROM ordenes WHERE id=?", (oid,), one=True)
    nuevo_estado = d.get("estado", "Pendiente")

    # ── No permitir completar la OT si quedan operaciones sin completar ───────
    # El descuento de stock (lotes + insumos) se dispara cuando la OT pasa a
    # "Completada", así que primero hay que garantizar que TODAS sus
    # operaciones ya estén en estado "Completada".
    ya_estaba_completada_chk = orden_actual and orden_actual["estado"] == "Completada"
    if nuevo_estado == "Completada" and not ya_estaba_completada_chk:
        # Si un paso tiene rutas alternativas (mismo número de "orden"),
        # alcanza con que UNA de ellas esté Completada para dar el paso por
        # hecho — las demás alternativas no usadas quedan en Pendiente.
        pendientes = query("""SELECT COUNT(*) c FROM (
            SELECT orden FROM orden_operaciones WHERE orden_id=?
            GROUP BY orden HAVING SUM(CASE WHEN estado='Completada' THEN 1 ELSE 0 END)=0)""",
            (oid,), one=True)["c"]
        if pendientes > 0:
            return jsonify({"error": f"No se puede completar la OT: quedan {pendientes} operación(es) sin completar"}), 400

    # ── Cambio de producto en una OT existente ────────────────────────────────
    # Las operaciones (orden_operaciones), los materiales requeridos
    # (orden_materiales) y los lotes ya vinculados (orden_lotes) se generan a
    # partir del producto de la OT. Si el producto cambia, todo eso queda
    # "huérfano": las operaciones siguen siendo las del producto viejo, y por
    # eso al declarar una novedad seguía ofreciendo vincular un lote de la
    # operación/producto anterior. Para evitarlo, si cambia el producto y la
    # OT no tiene nada de trabajo real ya declarado, se regeneran las
    # operaciones y materiales para el producto nuevo. Si ya hay novedades,
    # lotes vinculados o producción declarada, se bloquea el cambio de
    # producto para no perder ni corromper ese historial.
    producto_anterior = orden_actual["producto_id"] if orden_actual else None
    cambia_producto = producto_anterior is not None and int(producto_anterior) != int(d["producto_id"])
    if cambia_producto:
        novedades_previas = query("""SELECT COUNT(*) c FROM novedades_produccion n
            JOIN orden_operaciones oo ON oo.id=n.orden_operacion_id
            WHERE oo.orden_id=?""", (oid,), one=True)["c"]
        lotes_vinculados = query("SELECT COUNT(*) c FROM orden_lotes WHERE orden_id=?", (oid,), one=True)["c"]
        produccion_declarada = query("""SELECT COUNT(*) c FROM orden_operaciones
            WHERE orden_id=? AND qty_producida>0""", (oid,), one=True)["c"]
        if novedades_previas > 0 or lotes_vinculados > 0 or produccion_declarada > 0:
            return jsonify({"error": "No se puede cambiar el producto de la OT: ya tiene novedades, lotes vinculados o producción declarada. Cancelá o revertí esa actividad antes de cambiar el producto."}), 400
        n_pl = _n_bloques_planificados(oid)
        if n_pl:
            return jsonify({"error": f"No se puede cambiar el producto de la OT: tiene {n_pl} bloque/s en el Scheduling de producción. Quitalos de la planificación antes de cambiar el producto."}), 400

    # ── Completar la OT: no confirmar el estado hasta que todo salga bien ─────
    # Antes, el UPDATE de abajo grababa estado='Completada' de entrada, y el
    # descuento de stock / generación del lote de PT se hacían DESPUÉS, cada
    # uno con su propio commit. Si algo fallaba a mitad de camino (una
    # excepción en el descuento o en la generación del PT), la OT quedaba
    # guardada como "Completada" en la base aunque el stock nunca se hubiera
    # descontado ni el lote de PT se hubiera generado — y como ya figuraba
    # "Completada", un reintento (incluso revirtiendo a "En proceso" y volviendo
    # a completar) volvía a chocar con el mismo error, dejando la OT trabada.
    # Para evitarlo: si la OT recién está pasando a "Completada", el UPDATE
    # principal graba el estado ANTERIOR (no toca nada más), y solo al final,
    # una vez que el descuento de stock y la generación del PT terminaron sin
    # errores, se confirma el cambio a "Completada" en un último UPDATE.
    completando_ahora = nuevo_estado == "Completada" and not ya_estaba_completada_chk
    estado_a_grabar = (orden_actual["estado"] if orden_actual else "Pendiente") if completando_ahora else nuevo_estado

    execute("UPDATE ordenes SET cliente_id=?,producto_id=?,descripcion=?,detalle=?,cantidad=?,prioridad=?,estado=?,fecha_inicio=?,fecha_entrega=?,costo_mat=?,costo_mo=?,precio_venta=0,obs=?,actualizado=datetime('now','localtime') WHERE id=?",
        (d.get("cliente_id"),d["producto_id"],descripcion,d.get("detalle"),d.get("cantidad",1),d.get("prioridad","Normal"),estado_a_grabar,d.get("fecha_inicio"),d.get("fecha_entrega"),_mon_o_actual(d,"costo_mat","ordenes",oid),_mon_o_actual(d,"costo_mo","ordenes",oid),d.get("obs"),oid))

    # Punto 4 (v147): flag "requiere materia prima" de la OT. Solo se toca si el
    # body lo trae (el cambio rápido de estado no lo manda).
    if "requiere_material" in d:
        nuevo_rm = 1 if str(d.get("requiere_material")) in ("1","True","true") else 0
        actual_rm = query("SELECT requiere_material FROM ordenes WHERE id=?", (oid,), one=True)
        actual_rm = 1 if (actual_rm is None or actual_rm["requiere_material"] is None) else int(actual_rm["requiere_material"])
        if nuevo_rm != actual_rm:
            lotes_v = query("SELECT COUNT(*) c FROM orden_lotes WHERE orden_id=?", (oid,), one=True)["c"]
            if lotes_v > 0:
                return jsonify({"error": "No se puede cambiar 'Requiere materia prima': la OT ya tiene lotes vinculados."}), 400
            execute("UPDATE ordenes SET requiere_material=? WHERE id=?", (nuevo_rm, oid))
            if not cambia_producto:
                _populate_orden_materiales(oid)

    # Al cambiar el producto (sin actividad previa), regenerar operaciones y
    # materiales requeridos para que reflejen la ruta del producto nuevo.
    if cambia_producto:
        _populate_orden_operaciones(oid)
        _populate_orden_materiales(oid)
    # Al cambiar solo la cantidad de una OT abierta, las operaciones y los
    # materiales requeridos siguen a la cantidad nueva (lo ya asignado se
    # conserva). Los costos quedan como los cargó el usuario en el formulario.
    elif orden_actual and orden_actual["estado"] not in ("Completada", "Cancelada") \
            and nuevo_estado not in ("Completada", "Cancelada"):
        try:
            cant_nueva = float(d.get("cantidad", 1) or 0)
        except (TypeError, ValueError):
            cant_nueva = 0
        cant_vieja = float(orden_actual["cantidad"] or 0)
        if cant_nueva > 0 and abs(cant_nueva - cant_vieja) > 1e-9:
            _ajustar_cantidad_ot(oid, cant_nueva, vieja=cant_vieja, recalcular_costos=False)

    # ── Descontar stock de materiales al completar la OT ──────────────────────
    # Solo importa si ya se descontó o no (stock_descontado). NO alcanza con
    # mirar si el estado anterior ya era "Completada": si la OT quedó cargada
    # como Completada de entrada (ej. datos migrados/de prueba) sin pasar
    # nunca por este descuento, stock_descontado sigue en 0 y hay que
    # generarlo igual la próxima vez que se guarde la OT.
    ya_descontado = orden_actual and int(orden_actual["stock_descontado"] or 0) == 1

    # Todo lo que sigue (descuento de stock + generación del lote de PT) se
    # ejecuta dentro de un try/except: si algo falla acá, la OT NO debe quedar
    # confirmada como "Completada" (ver estado_a_grabar más arriba), para que
    # el usuario reciba el error real y pueda reintentar sin quedar trabado.
    try:
        if nuevo_estado == "Completada" and not ya_descontado:
            numero_ot = orden_actual["numero"] if orden_actual else str(oid)

            # NOTA: los materiales/PT que llevan lote YA se descuentan del
            # stock y del lote en el momento en que se declara cada novedad
            # (ver create_novedad), no acá. Antes este bloque volvía a
            # descontar cantidad_disponible/cantidad_activa/stock a partir
            # de orden_lotes.cantidad_usada al completar la OT, lo que
            # duplicaba el descuento (una vez por novedad + una vez acá).
            # Se deja el flag stock_descontado en 1 igual, para no romper
            # la idempotencia de este bloque ni la lógica de PT de abajo.
            execute("UPDATE ordenes SET stock_descontado=1 WHERE id=?", (oid,))

            # ── Insumos (sin lote): descuento directo del stock general ──────────
            # A diferencia de los materiales con lote, los insumos no se validan
            # ni descuentan al declarar la novedad (ver create_novedad). Acá se
            # calcula el consumo total a partir de lo realmente producido en cada
            # operación de la OT (qty_producida) por la cantidad unitaria definida
            # en operacion_materiales, y se descuenta de una sola vez al completar.
            insumos = query("""
                SELECT om.material_id, m.codigo, m.descripcion,
                       SUM(cant_material(om.cantidad, oo.qty_producida, om.vida_util_herramienta)) consumo
                FROM orden_operaciones oo
                JOIN orden_operacion_materiales om ON om.orden_operacion_id=oo.id
                JOIN materiales m ON m.id=om.material_id
                WHERE oo.orden_id=? AND m.categoria='Insumo'   -- las herramientas se descuentan por novedad (consumir_herramientas_op)
                GROUP BY om.material_id
            """, (oid,))
            for ins in insumos:
                consumo = float(ins["consumo"] or 0)
                if consumo <= 0:
                    continue
                execute("""UPDATE materiales
                    SET stock=MAX(0, stock-?), actualizado=datetime('now','localtime')
                    WHERE id=?""", (consumo, ins["material_id"]))
                auto_generar_sc_bajo_stock(ins["material_id"], f"consumo insumos OT {numero_ot}")
                execute("""INSERT INTO movimientos
                    (material_id, lote_id, tipo, cantidad, referencia, usuario_id)
                    VALUES (?, NULL, 'salida', ?, ?, ?)""",
                    (ins["material_id"], consumo,
                     f"Consumo OT {numero_ot} — Insumo {ins['codigo']} (sin lote)",
                     session["user_id"]))

        # ── Red de seguridad: asegurar que el PT quede generado ──────────────────
        # Se ejecuta SIEMPRE que la OT quede en estado "Completada", incluso si
        # stock_descontado ya estaba en 1 (ej: la OT ya se había completado antes
        # y se vuelve a guardar). La función es idempotente: calcula cuánto PT ya
        # existe en el lote OT-N y solo agrega lo que falte hasta la cantidad
        # total de la OT, así que no duplica nada.
        if nuevo_estado == "Completada":
            consumir_herramientas_ot(oid)
            generar_pt_faltante_si_corresponde(oid)
            if completando_ahora:
                _consumir_pse_sobrante_ot(oid)
            # Si quedó un cajón "Abierto" (parcialmente lleno) para esta OT,
            # se cierra igual: al completarse la OT no van a llegar más
            # piezas para terminar de llenarlo, así que pasa a "Ingresado"
            # (pendiente de Calidad) con lo que tenga hasta ahora.
            numero_ot_cierre = orden_actual["numero"] if orden_actual else str(oid)
            execute("UPDATE lotes SET estado='Ingresado' WHERE estado='Abierto' AND numero LIKE ?",
                (numero_ot_cierre + "-C%",))
    except Exception as e:
        # Algo falló al descontar stock o generar el lote de PT: NO confirmar
        # la OT como "Completada" (ya quedó grabada con su estado anterior más
        # arriba), para que el usuario vea el error real y pueda reintentar
        # sin que la OT quede en un limbo "Completada" sin stock ni lote.
        return jsonify({"error": f"No se pudo completar la OT: {e}"}), 500

    # Recién acá, con el descuento de stock y la generación del PT ya
    # confirmados sin errores, se graba el cambio de estado a "Completada".
    if completando_ahora:
        execute("UPDATE ordenes SET estado='Completada' WHERE id=?", (oid,))

    # Si se revierte de Completada a otro estado, restaurar el stock
    if orden_actual and orden_actual["estado"] == "Completada" and nuevo_estado != "Completada" and ya_descontado:
        numero_ot = orden_actual["numero"] if orden_actual else str(oid)

        # NOTA IMPORTANTE: los materiales/PT que llevan LOTE ya NO se
        # reversan acá. Desde que el descuento de esos materiales pasó a
        # hacerse al instante en cada novedad (ver create_novedad, descuento
        # inmediato), completar la OT NUNCA vuelve a descontar ese stock —
        # por lo tanto reabrir la OT (revertir de "Completada") tampoco debe
        # devolverlo. Antes este bloque SÍ lo devolvía (cantidad_disponible,
        # cantidad_activa y, peor, cantidad_reservada) basándose en
        # orden_lotes.cantidad_usada, como si el completar hubiera vuelto a
        # descontarlo — lo cual generaba stock/reserva fantasma cada vez que
        # se reabría y volvía a completar una OT (bug reportado: reservado
        # que crecía sin corresponder a ningún consumo real). El único lugar
        # que debe tocar cantidad_reservada/cantidad_disponible/activa de un
        # lote por consumo de OT es create_novedad, en el momento en que se
        # declara cada novedad real.
        execute("UPDATE ordenes SET stock_descontado=0 WHERE id=?", (oid,))

        # ── Reversión de insumos (sin lote) ───────────────────────────────────
        insumos_rev = query("""
            SELECT om.material_id, m.codigo,
                   SUM(cant_material(om.cantidad, oo.qty_producida, om.vida_util_herramienta)) consumo
            FROM orden_operaciones oo
            JOIN orden_operacion_materiales om ON om.orden_operacion_id=oo.id
            JOIN materiales m ON m.id=om.material_id
            WHERE oo.orden_id=? AND m.categoria='Insumo'   -- las herramientas se descuentan por novedad (consumir_herramientas_op)
            GROUP BY om.material_id
        """, (oid,))
        for ins in insumos_rev:
            consumo = float(ins["consumo"] or 0)
            if consumo <= 0:
                continue
            execute("""UPDATE materiales
                SET stock=stock+?, actualizado=datetime('now','localtime')
                WHERE id=?""", (consumo, ins["material_id"]))
            execute("""INSERT INTO movimientos
                (material_id, lote_id, tipo, cantidad, referencia, usuario_id)
                VALUES (?, NULL, 'entrada', ?, ?, ?)""",
                (ins["material_id"], consumo,
                 f"Reversión OT {numero_ot} — Insumo {ins['codigo']} (estado cambiado a {nuevo_estado})",
                 session["user_id"]))

    # ── Cancelar la OT: desvincular lotes de materiales ya asignados ──────────
    # Al cancelar, cualquier lote vinculado a esta OT (por "Asignar lote" o
    # automáticamente al declarar una novedad) debe desvincularse, INCLUSO si
    # ya se consumió parte del material desde ese lote. Se libera la reserva
    # pendiente que pudiera quedar sobre el lote (cantidad_reservada) para
    # que vuelva a estar disponible para otras OTs; el material que ya se
    # descontó como consumo real (stock/cantidad_activa) NO se devuelve acá
    # — desvincular no es lo mismo que reponer stock ya gastado.
    ya_estaba_cancelada = orden_actual and orden_actual["estado"] == "Cancelada"
    if nuevo_estado == "Cancelada" and not ya_estaba_cancelada:
        vinculos = query("SELECT * FROM orden_lotes WHERE orden_id=?", (oid,))
        for v in vinculos:
            execute("UPDATE lotes SET cantidad_reservada=MAX(0, COALESCE(cantidad_reservada,0)-?) WHERE id=?",
                (float(v["cantidad_usada"] or 0), v["lote_id"]))
        execute("DELETE FROM orden_lotes WHERE orden_id=?", (oid,))
        execute("UPDATE orden_materiales SET cantidad_asignada=0 WHERE orden_id=?", (oid,))
        # Los cajones que todavía no terminaron ninguna pieza quedan En espera
        # para pasarlos a otra OT abierta del mismo producto (o darlos de baja).
        for c in query("SELECT * FROM cajones WHERE orden_id=? AND estado='En proceso'", (oid,)):
            if _cajon_terminadas(c) <= 0.0001:
                execute("UPDATE cajones SET estado='En espera' WHERE id=?", (c["id"],))
        # Las OTT que todavía no salieron al proveedor (sin envíos) se
        # cancelan junto con la OT; las que ya tienen piezas afuera quedan
        # como están para poder recibirlas de vuelta.
        execute("""UPDATE ordenes_tercerizado SET estado='Cancelado'
            WHERE ot_origen_id=? AND estado='Pendiente' AND COALESCE(cantidad_enviada,0)=0""", (oid,))
        execute("""UPDATE solicitudes_compra SET estado='Cancelada' WHERE estado='Pendiente'
            AND ott_id IN (SELECT id FROM ordenes_tercerizado WHERE ot_origen_id=? AND estado='Cancelado')""", (oid,))
    elif ya_estaba_cancelada and nuevo_estado != "Cancelada":
        # Se reactiva la OT: sus OTT canceladas sin envíos vuelven a Pendiente.
        execute("""UPDATE ordenes_tercerizado SET estado='Pendiente'
            WHERE ot_origen_id=? AND estado='Cancelado' AND COALESCE(cantidad_enviada,0)=0""", (oid,))
        for _t in query("SELECT id FROM ordenes_tercerizado WHERE ot_origen_id=? AND estado='Pendiente'", (oid,)):
            _sync_sc_ott(_t["id"])
        # y sus cajones en espera (los que no se pasaron a otra OT) vuelven.
        for c in query("SELECT id FROM cajones WHERE orden_id=? AND estado='En espera'", (oid,)):
            execute("UPDATE cajones SET estado='En proceso' WHERE id=?", (c["id"],))
            _cajon_recalcular(c["id"])

    return jsonify({"ok":True})


# ── Operaciones de OT (desglose en renglones) ─────────────────────────────────
@app.route("/api/ordenes/<int:oid>/operaciones", methods=["GET"])
@login_required()
def get_orden_operaciones(oid):
    rows = query("""SELECT oo.*,cm.nombre cat_maquina_nombre,m.nombre maquina_nombre,
        p.razon proveedor_nombre, ott.id ott_id
        FROM orden_operaciones oo
        LEFT JOIN categorias_maquina cm ON cm.id=oo.categoria_maquina_id
        LEFT JOIN maquinas m ON m.id=oo.maquina_id
        LEFT JOIN proveedores p ON p.id=oo.proveedor_id
        LEFT JOIN ordenes_tercerizado ott ON ott.operacion_id=oo.id
        WHERE oo.orden_id=? ORDER BY CAST(oo.orden AS INTEGER), oo.orden""", (oid,))
    out = [dict(r) for r in rows]
    # Una operación queda bloqueada para revertir su estado (una vez
    # Completada) si depende de una tercerización previa en la misma OT
    # (ver _tiene_terc_previa) — el resto se puede revertir libremente.
    for r in out:
        try:
            orden_num = int(r["orden"])
        except Exception:
            orden_num = None
        r["depende_terc_previa"] = orden_num is not None and any(
            o.get("es_tercerizada") for o in out
            if o is not r and _orden_int(o.get("orden")) is not None and _orden_int(o.get("orden")) < orden_num
        )
    return jsonify(out)

def _orden_int(v):
    try:
        return int(v)
    except Exception:
        return None

def _motivo_no_repoblar(oid):
    """Por qué NO se puede regenerar las operaciones de esta OT, o None.

    Regenerar borra y rehace orden_operaciones. Eso es inofensivo mientras la
    OT no arrancó, pero deja de serlo en cuanto hay trabajo declarado o
    piezas en la calle:

      · Novedades declaradas: novedades_produccion referencia la operación
        con ON DELETE NO ACTION, así que el DELETE fallaba con un
        "FOREIGN KEY constraint failed" y el endpoint devolvía un 500 sin
        explicación. Además, borrar la operación perdería la producción.
      · OTT ya en movimiento: la tercerizada referencia la operación con
        ON DELETE SET NULL, así que el DELETE pasaba pero dejaba la OTT
        huérfana, apuntando a nada, con piezas ya remitidas al proveedor.
    """
    n_nov = query("""SELECT COUNT(*) c FROM novedades_produccion nov
        JOIN orden_operaciones oo ON oo.id=nov.orden_operacion_id
        WHERE oo.orden_id=?""", (oid,), one=True)["c"]
    if n_nov:
        return ("La OT ya tiene producción declarada (%d novedad/es): no se pueden "
                "regenerar sus operaciones sin perder ese trabajo." % n_nov)
    en_curso = query("""SELECT numero, estado FROM ordenes_tercerizado
        WHERE ot_origen_id=? AND (COALESCE(cantidad_enviada,0) > 0
              OR estado NOT IN ('Pendiente','Anulada'))
        LIMIT 1""", (oid,), one=True)
    if en_curso:
        return ("La OT tiene una orden de tercerizado en curso (%s, %s): no se pueden "
                "regenerar sus operaciones." % (en_curso["numero"], en_curso["estado"]))
    # La planificación cuelga de orden_operaciones con ON DELETE CASCADE:
    # regenerar borraría en silencio todos los bloques del Scheduling.
    n_pl = _n_bloques_planificados(oid)
    if n_pl:
        return ("La OT tiene %d bloque/s en el Scheduling de producción: quitalos de la "
                "planificación antes de regenerar sus operaciones." % n_pl)
    return None


def _n_bloques_planificados(oid, opid=None):
    sql = """SELECT COUNT(*) c FROM planificacion pl
        JOIN orden_operaciones oo ON oo.id=pl.orden_operacion_id WHERE oo.orden_id=?"""
    args = [oid]
    if opid is not None:
        sql += " AND oo.id=?"
        args.append(opid)
    return query(sql, tuple(args), one=True)["c"]


def _populate_orden_operaciones(oid):
    """Borra y regenera orden_operaciones a partir del producto actual de la OT.
    Función interna reutilizada por el endpoint POST y por update_orden cuando
    se cambia el producto de una OT existente.

    Devuelve la cantidad de operaciones creadas, None si la OT no tiene
    producto, o el string con el motivo si no se puede regenerar."""
    orden = query("SELECT producto_id FROM ordenes WHERE id=?", (oid,), one=True)
    if not orden or not orden["producto_id"]: return None
    motivo = _motivo_no_repoblar(oid)
    if motivo:
        return motivo
    # Las OTT que todavía no se movieron se borran junto con las operaciones:
    # si no, quedarían apuntando a nada (ON DELETE SET NULL) y después
    # _generar_ott_para_ot crearía otras, duplicándolas.
    # Sus SC del servicio: las pendientes se borran con la OTT; las que ya
    # avanzaron (OC emitida) quedan, desvinculadas, para que Compras las vea.
    _ott_borrar = "SELECT id FROM ordenes_tercerizado WHERE ot_origen_id=? AND COALESCE(cantidad_enviada,0)=0 AND estado IN ('Pendiente','Anulada')"
    execute(f"DELETE FROM solicitudes_compra WHERE estado IN ('Pendiente','Cancelada') AND ott_id IN ({_ott_borrar})", (oid,))
    execute(f"""UPDATE solicitudes_compra SET ott_id=NULL,
        obs=COALESCE(obs||char(10),'')||'La OTT de esta solicitud se eliminó al regenerar las operaciones de la OT.'
        WHERE ott_id IN ({_ott_borrar})""", (oid,))
    execute("""DELETE FROM ordenes_tercerizado WHERE ot_origen_id=?
        AND COALESCE(cantidad_enviada,0)=0 AND estado IN ('Pendiente','Anulada')""", (oid,))
    execute("DELETE FROM orden_operaciones WHERE orden_id=?", (oid,))
    ops = query("""SELECT po.*,cm.nombre cat_maq FROM proceso_operaciones po
        LEFT JOIN categorias_maquina cm ON cm.id=po.categoria_maquina_id
        WHERE po.producto_id=? ORDER BY CAST(po.orden AS INTEGER), po.orden""", (orden["producto_id"],))
    qty = query("SELECT cantidad FROM ordenes WHERE id=?", (oid,), one=True)["cantidad"]
    for op in ops:
        qty_op = _qty_operacion(op, qty)
        _oo_nuevo = execute("""INSERT INTO orden_operaciones
            (orden_id,proceso_op_id,orden,nombre,categoria_maquina_id,maquina_id,
             tiempo_setup_min,tiempo_ciclo_seg,estado,qty_requerida,
             es_tercerizada,proveedor_id,precio_tercerizado,tiempo_minimo_dias)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (oid,op["id"],op["orden"],op["nombre"],op["categoria_maquina_id"],op["maquina_id"],
             op["tiempo_setup_min"],op["tiempo_ciclo_seg"],"Pendiente",qty_op,
             op["es_tercerizada"] if "es_tercerizada" in op.keys() else 0,
             op["proveedor_id"] if "proveedor_id" in op.keys() else None,
             op["precio_tercerizado"] if "precio_tercerizado" in op.keys() else 0,
             op["tiempo_minimo_dias"] if "tiempo_minimo_dias" in op.keys() else 0))
        _copiar_materiales_a_ot_op(_oo_nuevo, op["id"])
    # Auto-generate OTT para ops tercerizadas (ya no se genera SC acá: la
    # compra/gestión del servicio tercerizado se maneja desde la OTT).
    ot_row = query("SELECT numero FROM ordenes WHERE id=?", (oid,), one=True)
    if ot_row:
        _generar_ott_para_ot(oid, ot_row["numero"])

    return len(ops)


def _populate_orden_materiales(oid):
    """Borra y regenera orden_materiales a partir del producto actual de la OT."""
    orden = query("SELECT producto_id,cantidad,requiere_material FROM ordenes WHERE id=?", (oid,), one=True)
    if not orden or not orden["producto_id"]: return None
    execute("DELETE FROM orden_materiales WHERE orden_id=?", (oid,))
    # Herramientas con vida útil: ceil(piezas que procesa esa operación /
    # vida útil); el resto, cantidad por pieza x cantidad de la OT (como antes).
    mats = query("""SELECT om.material_id,
        SUM(CASE WHEN COALESCE(om.vida_util_herramienta,0)>0
            THEN cant_material(om.cantidad, oo.qty_requerida, om.vida_util_herramienta)
            ELSE om.cantidad*? END) AS total, m.unidad
        FROM orden_operaciones oo
        JOIN orden_operacion_materiales om ON om.orden_operacion_id=oo.id
        JOIN materiales m ON m.id=om.material_id
        WHERE oo.orden_id=? AND om.material_id IS NOT NULL GROUP BY om.material_id""",
        (orden["cantidad"], oid))
    if not mats:
        mats = query("""SELECT om.material_id,
            SUM(cant_material(om.cantidad, ?, om.vida_util_herramienta)) AS total, m.unidad
            FROM proceso_operaciones po
            JOIN operacion_materiales om ON om.operacion_id=po.id
            JOIN materiales m ON m.id=om.material_id
            WHERE po.producto_id=? GROUP BY om.material_id""",
            (orden["cantidad"], orden["producto_id"]))
    # Si la OT no requiere materia prima, se omiten los materiales de categoría
    # "Material" (los insumos/herramientas se siguen descontando igual).
    if orden["requiere_material"] is not None and int(orden["requiere_material"]) == 0:
        mats = [m for m in mats if (query("SELECT categoria FROM materiales WHERE id=?", (m["material_id"],), one=True) or {"categoria":None})["categoria"] != "Material"]
    for mat in mats:
        execute("INSERT INTO orden_materiales (orden_id,material_id,cantidad_requerida,cantidad_asignada,unidad) VALUES (?,?,?,0,?)",
            (oid, mat["material_id"], mat["total"], mat["unidad"]))
    return len(mats)


@app.route("/api/ordenes/<int:oid>/operaciones/populate", methods=["POST"])
@login_required()
def populate_orden_operaciones(oid):
    n = _populate_orden_operaciones(oid)
    if n is None: return jsonify({"error":"La OT no tiene producto asignado"}), 400
    if isinstance(n, str): return jsonify({"error": n}), 409
    return jsonify({"ok":True,"ops_created":n})

def _tiene_terc_previa(orden_id, orden_num):
    """True si existe alguna operación tercerizada ANTERIOR (orden menor) en
    la misma OT, sin importar su estado. Se usa para restringir la reversión
    de estado 'Completada': solo las operaciones que consumen o dependen de
    una tercerización previa quedan bloqueadas una vez completadas; el resto
    de las operaciones se puede revertir libremente."""
    try:
        orden_num_int = float(orden_num)
    except Exception:
        return False
    row = query("""SELECT 1 FROM orden_operaciones
        WHERE orden_id=? AND es_tercerizada=1
          AND CAST(orden AS REAL) < ?
        LIMIT 1""", (orden_id, orden_num_int), one=True)
    return row is not None


# ── CRUD completo para operaciones de OT ─────────────────────────────────────
def _recalcular_material_requerido_ot(oid, material_id):
    """Recalcula orden_materiales.cantidad_requerida de UN material de la OT en
    función de la qty_requerida de cada operación de la OT que lo usa
    (orden_operacion_materiales: copia propia de la OT, v148). Si el material
    ya no lo usa ninguna operación y no tiene nada asignado, se quita de la OT;
    si lo usa y no estaba, se agrega. No toca lo ya asignado/reservado."""
    calc = _materiales_requeridos_ot(oid, material_id).get(material_id)
    total = float(calc[0] or 0) if calc else 0
    row = {"unidad": calc[1]} if calc else None
    existing = query("SELECT id,cantidad_asignada FROM orden_materiales WHERE orden_id=? AND material_id=?", (oid, material_id), one=True)
    if existing:
        if total <= 0:
            usado = query("SELECT COUNT(*) c FROM orden_lotes WHERE orden_id=? AND material_id=?", (oid, material_id), one=True)["c"]
            if float(existing["cantidad_asignada"] or 0) <= 0 and not usado:
                execute("DELETE FROM orden_materiales WHERE id=?", (existing["id"],))
                return
        execute("UPDATE orden_materiales SET cantidad_requerida=? WHERE id=?", (total, existing["id"]))
    elif total > 0:
        unidad = (row["unidad"] if row else None)
        execute("INSERT INTO orden_materiales (orden_id,material_id,cantidad_requerida,cantidad_asignada,unidad) VALUES (?,?,?,0,?)",
                (oid, material_id, total, unidad))


@app.route("/api/ordenes/<int:oid>/operaciones/<int:opid>", methods=["PUT"])
@login_required(roles=["admin","operario"])
def update_ot_operacion(oid, opid):
    d = request.json or {}
    # Build dynamic UPDATE based on which fields were provided
    allowed = {
        "orden", "nombre", "categoria_maquina_id", "maquina_id",
        "tiempo_setup_min", "tiempo_ciclo_seg", "qty_requerida", "estado",
    }
    fields = {k: v for k, v in d.items() if k in allowed}
    if not fields:
        return jsonify({"ok": True, "noop": True})
    if fields.get("estado"):
        oo = query("SELECT orden, estado, es_tercerizada FROM orden_operaciones WHERE id=? AND orden_id=?", (opid, oid), one=True)
        if not oo: return jsonify({"error":"Operación no encontrada"}), 404
        if oo["estado"] == "Completada" and fields["estado"] != "Completada" and _tiene_terc_previa(oid, oo["orden"]):
            return jsonify({"error": "Esta operación depende de una tercerización previa y ya está "
                "Completada: no se puede revertir a un estado anterior."}), 400
        if fields["estado"] in ("En proceso","Completada"):
            if oo["es_tercerizada"]:
                return jsonify({"error": "Esta operación es tercerizada: se completa sola cuando vuelve "
                    "el lote del proveedor (OTT) y queda Aprobado en Lotes, no se marca a mano."}), 400
            bloqueo = _bloqueo_terc_previo(oid, oo["orden"])
            if bloqueo:
                return jsonify({"error": f"OT pausada: la operación tercerizada \"{bloqueo['nombre']}\" "
                    f"(orden {bloqueo['orden']}) todavía no fue recibida/aprobada."}), 400
            # Si esta operación es la que debe consumir el semielaborado
            # devuelto por una OTT anterior, no se puede completar a mano
            # desde este select: hay que declarar la Novedad de producción
            # con la cantidad, que es lo único que descuenta/libera el lote
            # de la OTT (ver _materiales_ott_pendientes_por_operacion). Si
            # se permitiera acá, el lote queda "pegado" con cantidad
            # aprobada y reservada para siempre (bug reportado).
            pendientes_ott = _materiales_ott_pendientes_por_operacion(oid, opid)
            if pendientes_ott:
                return jsonify({"error": "Esta operación consume el semielaborado devuelto por una "
                    "tercerización anterior: no se puede completar cambiando el estado a mano. "
                    "Cargá una Novedad de producción con la cantidad para que el lote de la OTT "
                    "se descuente correctamente."}), 400
    # Si se está por cambiar qty_requerida, necesitamos el proceso_op_id ANTES
    # del UPDATE para saber qué materiales de esta operación recalcular después.
    proceso_op_id = opid if "qty_requerida" in fields else None
    set_clause = ", ".join(f"{k}=?" for k in fields.keys())
    params = list(fields.values()) + [opid, oid]
    execute(f"UPDATE orden_operaciones SET {set_clause} WHERE id=? AND orden_id=?", params)
    # ── La cantidad que se le pide al lote/stock por cada material que usa
    # esta operación cambia en función de la nueva qty_requerida ingresada.
    if "qty_requerida" in fields and proceso_op_id:
        mat_ids = query("SELECT DISTINCT material_id FROM orden_operacion_materiales WHERE orden_operacion_id=?", (opid,))
        for mr in mat_ids:
            _recalcular_material_requerido_ot(oid, mr["material_id"])
    # Si se puso esta operación "En proceso" o "Completada" a mano, la OT
    # también pasa de "Pendiente" a "En proceso" (ya se empezó a producir).
    if fields.get("estado") in ("En proceso", "Completada"):
        execute("UPDATE ordenes SET estado='En proceso' WHERE id=? AND estado='Pendiente'", (oid,))
    return jsonify({"ok": True})

# ── Materiales por operación de la OT (v148, punto 4): la OT es independiente del proceso ──
@app.route("/api/orden_operaciones/<int:ooid>/materiales", methods=["GET"])
@login_required()
def get_ot_op_materiales(ooid):
    rows = query("""SELECT om.id,om.material_id,om.cantidad,om.unidad,om.tipo,om.vida_util_herramienta,m.codigo,m.descripcion,m.categoria,m.stock
        FROM orden_operacion_materiales om LEFT JOIN materiales m ON m.id=om.material_id
        WHERE om.orden_operacion_id=? ORDER BY om.id""", (ooid,))
    return jsonify([dict(r) for r in rows])

@app.route("/api/orden_operaciones/<int:ooid>/materiales", methods=["PUT"])
@login_required(roles=["admin","operario"])
def set_ot_op_materiales(ooid):
    """Reemplaza la lista de materiales/insumos de UNA operación de la OT.
    Lista vacía = la operación no consume material. No toca el proceso del producto."""
    oo = query("SELECT * FROM orden_operaciones WHERE id=?", (ooid,), one=True)
    if not oo: return jsonify({"error": "Operación no encontrada"}), 404
    lista = (request.json or {}).get("materiales")
    if not isinstance(lista, list): return jsonify({"error": "materiales (lista) requerido"}), 400
    limpia = []
    for m in lista:
        try:
            mid = int(m.get("material_id")); cant = float(m.get("cantidad") or 0)
        except (TypeError, ValueError):
            return jsonify({"error": "Material o cantidad inválidos"}), 400
        if cant <= 0: return jsonify({"error": "La cantidad de cada material debe ser mayor a 0"}), 400
        mat = query("SELECT id,unidad FROM materiales WHERE id=?", (mid,), one=True)
        if not mat: return jsonify({"error": f"Material {mid} no existe"}), 404
        limpia.append((mid, cant, m.get("unidad") or mat["unidad"], m.get("tipo") or "material",
                       _vida_util_valida(mid, m.get("vida_util_herramienta"))))
    if oo["es_tercerizada"] and not any(t == "material" for _, _, _, t, _ in limpia):
        return jsonify({"error": "Una operación tercerizada necesita un insumo (el material que vuelve del tercero)."}), 400
    previos = [r["material_id"] for r in query("SELECT DISTINCT material_id FROM orden_operacion_materiales WHERE orden_operacion_id=?", (ooid,)) if r["material_id"]]
    execute("DELETE FROM orden_operacion_materiales WHERE orden_operacion_id=?", (ooid,))
    for mid, cant, un, tipo, vida in limpia:
        execute("INSERT INTO orden_operacion_materiales (orden_operacion_id,material_id,cantidad,unidad,tipo,vida_util_herramienta) VALUES (?,?,?,?,?,?)", (ooid, mid, cant, un, tipo, vida))
    for mid in set(previos) | {x[0] for x in limpia}:
        _recalcular_material_requerido_ot(oo["orden_id"], mid)
    # OTT de esta operación que todavía no inició: actualizar el material de retorno
    if oo["es_tercerizada"]:
        ret = _material_retorno_operacion(ooid)
        if ret:
            execute("""UPDATE ordenes_tercerizado SET material_se_id=? WHERE operacion_id=? AND estado='Pendiente' AND COALESCE(cantidad_enviada,0)=0""", (ret, ooid))
    return jsonify({"ok": True})

@app.route("/api/ordenes/<int:oid>/operaciones/<int:opid>", methods=["DELETE"])
@login_required(roles=["admin","operario"])
def delete_ot_operacion(oid, opid):
    n_pl = _n_bloques_planificados(oid, opid)
    if n_pl:
        return jsonify({"error": f"La operación tiene {n_pl} bloque/s en el Scheduling de producción: quitalos de la planificación antes de borrarla."}), 409
    mat_ids_prev = query("SELECT DISTINCT material_id FROM orden_operacion_materiales WHERE orden_operacion_id=?", (opid,))
    execute("DELETE FROM orden_operacion_materiales WHERE orden_operacion_id=?", (opid,))
    execute("DELETE FROM orden_operaciones WHERE id=? AND orden_id=?", (opid, oid))
    # Al borrar la operación, lo pedido de sus materiales también baja (ya no
    # hay ninguna operación pendiente que lo necesite, salvo que otra
    # operación de la misma OT use el mismo material).
    for mr in mat_ids_prev:
        _recalcular_material_requerido_ot(oid, mr["material_id"])
    return jsonify({"ok": True})

@app.route("/api/ordenes/<int:oid>/operaciones", methods=["POST"])
@login_required(roles=["admin","operario"])
def add_ot_operacion(oid):
    d = request.json
    if not d.get("nombre"): return jsonify({"error":"Nombre requerido"}), 400
    new_id = execute("""INSERT INTO orden_operaciones
        (orden_id,orden,nombre,categoria_maquina_id,maquina_id,
         tiempo_setup_min,tiempo_ciclo_seg,estado,qty_requerida,obs)
        VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (oid, d.get("orden",1), d["nombre"],
         d.get("categoria_maquina_id") or None,
         d.get("maquina_id") or None,
         d.get("tiempo_setup_min",0), d.get("tiempo_ciclo_seg",0),
         d.get("estado","Pendiente"), d.get("qty_requerida",0),
         d.get("obs")))
    for m in (d.get("materiales") or []):
        try:
            if float(m.get("cantidad") or 0) > 0 and m.get("material_id"):
                execute("INSERT INTO orden_operacion_materiales (orden_operacion_id,material_id,cantidad,unidad,tipo,vida_util_herramienta) VALUES (?,?,?,?,?,?)",
                        (new_id, int(m["material_id"]), float(m["cantidad"]), m.get("unidad"), m.get("tipo") or "material",
                         _vida_util_valida(int(m["material_id"]), m.get("vida_util_herramienta"))))
                _recalcular_material_requerido_ot(oid, int(m["material_id"]))
        except (TypeError, ValueError):
            pass
    return jsonify({"ok": True, "id": new_id}), 201

# ── Materiales de OT ──────────────────────────────────────────────────────────
@app.route("/api/ordenes/<int:oid>/materiales", methods=["GET"])
@login_required()
def get_orden_materiales(oid):
    rows = query("""SELECT om.*,m.descripcion,m.codigo,m.unidad,m.stock,m.categoria
        FROM orden_materiales om JOIN materiales m ON m.id=om.material_id
        WHERE om.orden_id=? ORDER BY m.codigo""", (oid,))
    # Lotes ya vinculados a esta OT (asignados manualmente y/o consumidos por
    # novedades), para que el frontend pueda mostrar QUÉ lote(s) se eligieron
    # para cada material en la tabla de "Lotes asignados".
    lotes_rows = query("""SELECT ol.material_id, ol.lote_id, l.numero, ol.cantidad_usada, ol.cantidad_consumida
        FROM orden_lotes ol JOIN lotes l ON l.id=ol.lote_id
        WHERE ol.orden_id=?""", (oid,))
    lotes_por_mat = {}
    for lr in lotes_rows:
        lotes_por_mat.setdefault(lr["material_id"], []).append(
            {"lote_id": lr["lote_id"], "numero": lr["numero"], "cantidad_usada": lr["cantidad_usada"],
             "cantidad_consumida": lr["cantidad_consumida"] or 0})
    # A qué operación(es) del proceso está destinado cada material (un mismo
    # material puede estar requerido por más de un paso de la ruta, así que
    # se lista cada uno con su número de orden).
    ops_por_mat = {}
    if True:
        ops_rows = query("""SELECT om2.material_id, oo.orden op_orden, oo.nombre op_nombre
            FROM orden_operacion_materiales om2
            JOIN orden_operaciones oo ON oo.id=om2.orden_operacion_id
            WHERE oo.orden_id=? ORDER BY CAST(oo.orden AS INTEGER)""", (oid,))
        for orow in ops_rows:
            ops_por_mat.setdefault(orow["material_id"], []).append(
                f"{orow['op_orden']}. {orow['op_nombre']}")
    out = []
    for r in rows:
        rd = dict(r)
        rd["lotes_asignados"] = lotes_por_mat.get(r["material_id"], [])
        rd["operaciones"] = ops_por_mat.get(r["material_id"], [])
        out.append(rd)
    return jsonify(out)

@app.route("/api/ordenes/<int:oid>/materiales/populate", methods=["POST"])
@login_required()
def populate_orden_materiales(oid):
    n = _populate_orden_materiales(oid)
    if n is None: return jsonify({"error":"OT sin producto"}), 400
    # Si algún material requerido es un Producto Terminado (no se puede
    # comprar en Compras) y no hay stock suficiente para cubrir esta OT, se
    # genera automáticamente una OT auxiliar por el faltante — misma lógica
    # que ya se usaba al consolidar pedidos de cliente/pronóstico, ahora
    # también al crear/editar una OT manualmente desde Órdenes de trabajo.
    solicitudes_creadas, ots_auxiliares, avisos = _gap_analysis_materiales_multipass()
    return jsonify({"ok":True,"mats":n,"ots_auxiliares":ots_auxiliares,"solicitudes_compra":solicitudes_creadas,"avisos":avisos})

# ── Materiales/PT requeridos por una operación de OT + lotes disponibles ──────
@app.route("/api/orden_operaciones/<int:ooid>/materiales_requeridos")
@login_required()
def get_materiales_requeridos_op(ooid):
    """Para el modal de novedad: qué materiales/PT exige la operación y qué
    lotes están disponibles para vincular a cada uno (stock activo > 0)."""
    oo = query("SELECT * FROM orden_operaciones WHERE id=?", (ooid,), one=True)
    if not oo:
        return jsonify({"error": "Operación no encontrada"}), 404
    mats = query("""SELECT om.material_id, om.cantidad cantidad_unitaria, om.unidad, om.tipo,
        m.codigo, m.descripcion, m.categoria
        FROM orden_operacion_materiales om
        JOIN materiales m ON m.id=om.material_id
        WHERE om.orden_operacion_id=?
          AND EXISTS (
            SELECT 1 FROM orden_materiales omt
            WHERE omt.orden_id=? AND omt.material_id=om.material_id
          )""", (oo["id"], oo["orden_id"]))
    out = []
    for mat in mats:
        es_insumo = mat["categoria"] in ("Insumo", "Herramienta")
        # Los insumos no llevan trazabilidad por lote: se descuentan directo
        # del stock general al completar la OT, sin pedirle al operario que
        # elija un lote acá.
        lotes = [] if es_insumo else query("""SELECT l.id, l.numero,
            MAX(0, l.cantidad_activa - COALESCE(l.cantidad_reservada,0)) AS disponible_libre,
            l.referencia_proveedor, l.fecha_ingreso
            FROM lotes l
            WHERE l.material_id=? AND l.cantidad_activa > COALESCE(l.cantidad_reservada,0)
            ORDER BY l.fecha_ingreso""", (mat["material_id"],))
        # Si esta OT ya tiene un lote vinculado para este material (reservado
        # en una novedad anterior), informarlo para bloquear el selector.
        lote_vinculado = None if es_insumo else query("""
            SELECT l.id, l.numero, ol.cantidad_usada
            FROM orden_lotes ol JOIN lotes l ON l.id=ol.lote_id
            WHERE ol.orden_id=? AND ol.material_id=?""",
            (oo["orden_id"], mat["material_id"]), one=True)
        out.append({
            "material_id": mat["material_id"], "codigo": mat["codigo"],
            "descripcion": mat["descripcion"], "cantidad_unitaria": mat["cantidad_unitaria"],
            "unidad": mat["unidad"], "tipo": mat["tipo"] if "tipo" in mat.keys() else "material",
            "categoria": mat["categoria"], "requiere_lote": not es_insumo,
            "lotes": [dict(l) for l in lotes],
            "lote_vinculado": dict(lote_vinculado) if lote_vinculado else None
        })
    return jsonify(out)

# ── Lotes disponibles para un material (aprobados) ────────────────────────────
@app.route("/api/materiales/<int:mid>/lotes_aprobados")
@login_required()
def get_lotes_aprobados(mid):
    # disponible_libre = solo cantidad_activa (aprobada y no rechazada)
    # Se excluyen lotes sin stock aprobado
    rows = query("""SELECT l.id, l.numero, l.cantidad_disponible,
        l.cantidad_activa,
        MAX(0, l.cantidad_activa - COALESCE(l.cantidad_reservada,0)) AS disponible_libre,
        l.certificado, l.referencia_proveedor, l.fecha_ingreso
        FROM lotes l
        WHERE l.material_id=?
          AND l.cantidad_activa > COALESCE(l.cantidad_reservada,0)
        ORDER BY l.fecha_ingreso""", (mid,))
    return jsonify([dict(r) for r in rows])

# ── Asignar lote específico a OT ──────────────────────────────────────────────
@app.route("/api/ordenes/<int:oid>/materiales/<int:mid>/asignar_lote", methods=["POST"])
@login_required(roles=["admin","almacen","operario"])
def asignar_lote_a_ot(oid, mid):
    d = request.json
    lote_id = d.get("lote_id")
    qty     = float(d.get("cantidad", 0))
    if not lote_id or qty <= 0:
        return jsonify({"error": "lote_id y cantidad requeridos"}), 400

    lote = query("""SELECT l.* FROM lotes l
        WHERE l.id=? AND l.material_id=?""",
        (lote_id, mid), one=True)
    if not lote:
        return jsonify({"error": "Lote no encontrado para este material"}), 404

    orden = query("SELECT estado FROM ordenes WHERE id=?", (oid,), one=True)
    if orden and orden["estado"] == "Completada":
        return jsonify({"error": "La OT ya está completada: no se pueden modificar los lotes asignados"}), 400

    # Disponible libre = aprobado - ya reservado para otras OTs
    reservado_actual = float(lote["cantidad_reservada"] or 0)
    disponible_libre = max(0, float(lote["cantidad_activa"] or 0) - reservado_actual)
    if disponible_libre < qty:
        return jsonify({"error": f"Stock insuficiente: disponible libre {disponible_libre} requerido {qty}"}), 400

    # Solo reservar (no descontar del stock real).
    # El descuento efectivo ocurre al completar la OT.
    execute("UPDATE lotes SET cantidad_reservada=COALESCE(cantidad_reservada,0)+? WHERE id=?",
            (qty, lote_id))

    # Update orden_materiales assigned
    execute("""UPDATE orden_materiales SET cantidad_asignada=cantidad_asignada+?
        WHERE orden_id=? AND material_id=?""", (qty, oid, mid))

    # Record in orden_lotes (sin movimiento de stock todavía)
    # Si ya existía una reserva previa de este lote para esta OT, se SUMA
    # (no se pisa), porque cantidad_reservada en el lote ya se acumula así.
    execute("""INSERT INTO orden_lotes (orden_id,lote_id,material_id,cantidad_usada,fecha)
        VALUES (?,?,?,?,date('now','localtime'))
        ON CONFLICT(orden_id,lote_id) DO UPDATE SET
            cantidad_usada=cantidad_usada+excluded.cantidad_usada,
            fecha=excluded.fecha""", (oid, lote_id, mid, qty))

    num = query("SELECT numero FROM ordenes WHERE id=?", (oid,), one=True)["numero"]
    # Movimiento de reserva (tipo 'reserva') para trazabilidad, sin impacto en stock
    execute("""INSERT INTO movimientos (material_id,lote_id,tipo,cantidad,referencia,usuario_id)
        VALUES (?,?,'reserva',?,?,?)""",
        (mid, lote_id, qty, f"Reservado para {num} | Lote {lote['numero']}", session["user_id"]))

    return jsonify({"ok": True, "lote": lote["numero"], "asignado": qty})

@app.route("/api/ordenes/<int:oid>/materiales/<int:mid>/lotes/<int:lote_id>", methods=["PUT"])
@login_required(roles=["admin","almacen","operario"])
def modificar_cantidad_lote_asignado(oid, mid, lote_id):
    """Modifica la cantidad ya asignada/reservada de un lote puntual para
    esta OT (columna 'Lotes asignados'), sin tener que quitar y volver a
    asignar. Ajusta la reserva del lote y lo asignado del material por la
    diferencia; no toca stock real (eso ocurre al completar la OT).

    Si parte de ese lote ya fue CONSUMIDA (una novedad ya descontó stock
    real usando ese lote), no se puede bajar la cantidad por debajo de lo
    consumido: eso ya se gastó y queda como historial. En ese caso la
    cantidad se recorta a lo consumido en vez de rechazar la operación."""
    d = request.json or {}
    nueva_qty = float(d.get("cantidad", -1))
    if nueva_qty < 0:
        return jsonify({"error": "Cantidad inválida"}), 400

    row = query("""SELECT * FROM orden_lotes WHERE orden_id=? AND lote_id=? AND material_id=?""",
                (oid, lote_id, mid), one=True)
    if not row:
        return jsonify({"error": "Este lote no está asignado a esta OT"}), 404

    orden = query("SELECT estado FROM ordenes WHERE id=?", (oid,), one=True)
    if orden and orden["estado"] == "Completada":
        return jsonify({"error": "La OT ya está completada: no se pueden modificar los lotes asignados"}), 400

    lote = query("SELECT * FROM lotes WHERE id=?", (lote_id,), one=True)
    if not lote:
        return jsonify({"error": "Lote no encontrado"}), 404

    vieja_qty = float(row["cantidad_usada"] or 0)
    consumida = float(row["cantidad_consumida"] or 0) if "cantidad_consumida" in row.keys() else 0
    recortado = False
    if nueva_qty < consumida:
        nueva_qty = consumida  # no se puede liberar lo ya consumido, queda como está
        recortado = True
    delta = round(nueva_qty - vieja_qty, 6)

    if delta > 0:
        reservado_actual = float(lote["cantidad_reservada"] or 0)
        disponible_libre = max(0, float(lote["cantidad_activa"] or 0) - reservado_actual)
        if disponible_libre < delta:
            return jsonify({"error": f"Stock insuficiente en el lote: disponible libre {disponible_libre}, necesitás {delta} más"}), 400

    execute("UPDATE lotes SET cantidad_reservada=MAX(0,COALESCE(cantidad_reservada,0)+?) WHERE id=?",
            (delta, lote_id))
    execute("""UPDATE orden_materiales SET cantidad_asignada=MAX(0,cantidad_asignada+?)
        WHERE orden_id=? AND material_id=?""", (delta, oid, mid))

    if nueva_qty <= 0:
        # nueva_qty solo puede ser 0 acá si consumida también es 0 (si no, ya se recortó arriba)
        execute("DELETE FROM orden_lotes WHERE orden_id=? AND lote_id=? AND material_id=?", (oid, lote_id, mid))
    else:
        execute("UPDATE orden_lotes SET cantidad_usada=? WHERE orden_id=? AND lote_id=? AND material_id=?",
                (nueva_qty, oid, lote_id, mid))

    num = query("SELECT numero FROM ordenes WHERE id=?", (oid,), one=True)["numero"]
    execute("""INSERT INTO movimientos (material_id,lote_id,tipo,cantidad,referencia,usuario_id)
        VALUES (?,?,'reserva',?,?,?)""",
        (mid, lote_id, delta, f"Modificación asignación {num} | Lote {lote['numero']} ({vieja_qty} → {nueva_qty})", session["user_id"]))

    return jsonify({"ok": True, "lote": lote["numero"], "cantidad_anterior": vieja_qty,
                    "cantidad_nueva": nueva_qty, "cantidad_consumida": consumida, "recortado": recortado})

# ── Verificar cobertura de materiales de una OT ───────────────────────────────
@app.route("/api/ordenes/<int:oid>/materiales/alerta")
@login_required()
def alerta_materiales_ot(oid):
    mats = query("""SELECT om.material_id, om.cantidad_requerida, om.cantidad_asignada,
        m.descripcion, m.codigo, m.categoria,
        (SELECT COUNT(*) FROM lotes l WHERE l.material_id=om.material_id AND l.estado='Aprobado'
         AND l.cantidad_activa > COALESCE(l.cantidad_reservada,0)) lotes_ok
        FROM orden_materiales om JOIN materiales m ON m.id=om.material_id
        WHERE om.orden_id=?""", (oid,))
    alertas = []
    for m in mats:
        # Los insumos/herramientas no requieren asignación de lote; se descuentan al completar la OT
        if m["categoria"] in ("Insumo", "Herramienta"):
            continue
        faltante = float(m["cantidad_requerida"] or 0) - float(m["cantidad_asignada"] or 0)
        if faltante > 0:
            alertas.append({
                "material": m["codigo"] + " — " + m["descripcion"],
                "faltante": faltante,
                "hay_lotes_aprobados": bool(m["lotes_ok"]),
            })
    return jsonify({"alertas": alertas, "ok": len(alertas) == 0})


# Funciones de otras áreas. Van al final a propósito: así cada módulo ya
# definió todo lo suyo cuando otro lo importa, y no hay problemas de
# importación circular. Se usan recién al atender pedidos.
from .comun import (_copiar_materiales_a_ot_op, _get_or_create_pse,
    _material_retorno_operacion, _materiales_ott_pendientes_por_operacion,
    _vida_util_valida, consumir_herramientas_ot, get_or_create_pt_material)
from .cajones import _cajon_recalcular, _cajon_terminadas, _reducir_lotes_pt
from .ott import _asegurar_sc_ott, _sync_sc_ott
from .mrp import (_ajustar_cantidad_ot, _gap_analysis_materiales_multipass,
    _materiales_requeridos_ot, _qty_operacion)
from .novedades import _bloqueo_terc_previo
from .lotes import _consumir_pse_sobrante_ot
from .compras import auto_generar_sc_bajo_stock

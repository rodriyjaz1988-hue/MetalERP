"""Novedades de producción, trabajo no productivo y rendimiento por operario."""
from .nucleo import (app, datetime, execute, jsonify, login_required, query, request,
    session, siguiente_numero)

# ── Novedades de producción ───────────────────────────────────────────────────
@app.route("/api/novedades/corregir_rendimiento", methods=["GET"])
@login_required(roles=["admin"])
def preview_corregir_novedades():
    """Previsualiza qué novedades cambiarían su rendimiento/desvío al
    recalcularlos usando el tiempo de ciclo que tiene la operación en SU
    propia OT (orden_operaciones.tiempo_ciclo_seg) como estándar, ya que
    ese es el valor vigente para esa orden puntual (puede haber sido
    ajustado y diferir del proceso/plantilla). Solo si la OT no tiene un
    valor propio cargado (0/NULL) se recurre al de la plantilla
    (proceso_operaciones.tiempo_ciclo_seg) como respaldo. No modifica nada."""
    rows = query("""
        SELECT n.id, n.numero, n.cantidad_producida, n.tiempo_real_min, n.tiempo_perdido,
               n.rendimiento_pct, n.desvio,
               COALESCE(NULLIF(oo.tiempo_ciclo_seg, 0), po.tiempo_ciclo_seg, 60) AS std_ciclo
        FROM novedades_produccion n
        JOIN orden_operaciones oo ON oo.id = n.orden_operacion_id
        LEFT JOIN proceso_operaciones po ON po.id = oo.proceso_op_id
        WHERE n.tiempo_real_min > 0
        ORDER BY n.id
    """)

    afectadas = []
    for r in rows:
        # std_ciclo esta en segundos; tiempo_real_min en minutos.
        std_ciclo = (r["std_ciclo"] or 60) / 60.0
        t_real = r["tiempo_real_min"]
        qty = r["cantidad_producida"]
        t_productivo = max(t_real, 0.1)
        rendimiento_nuevo = round((qty / t_productivo) / (1 / std_ciclo) * 100, 1)
        rendimiento_nuevo = min(rendimiento_nuevo, 999)
        desvio_nuevo = 1 if rendimiento_nuevo < 80 else 0

        if abs((r["rendimiento_pct"] or 0) - rendimiento_nuevo) < 0.05 and r["desvio"] == desvio_nuevo:
            continue

        afectadas.append({
            "id": r["id"], "numero": r["numero"],
            "tiempo_real_min": t_real, "tiempo_perdido": r["tiempo_perdido"],
            "rendimiento_actual": r["rendimiento_pct"], "desvio_actual": r["desvio"],
            "rendimiento_nuevo": rendimiento_nuevo, "desvio_nuevo": desvio_nuevo
        })

    return jsonify({"afectadas": afectadas, "total": len(afectadas)})

@app.route("/api/novedades/corregir_rendimiento", methods=["POST"])
@login_required(roles=["admin"])
def aplicar_corregir_novedades():
    """Aplica la corrección de rendimiento/desvío calculada por
    preview_corregir_novedades sobre todas las novedades afectadas."""
    rows = query("""
        SELECT n.id, n.cantidad_producida, n.tiempo_real_min,
               n.rendimiento_pct, n.desvio,
               COALESCE(NULLIF(oo.tiempo_ciclo_seg, 0), po.tiempo_ciclo_seg, 60) AS std_ciclo
        FROM novedades_produccion n
        JOIN orden_operaciones oo ON oo.id = n.orden_operacion_id
        LEFT JOIN proceso_operaciones po ON po.id = oo.proceso_op_id
        WHERE n.tiempo_real_min > 0
        ORDER BY n.id
    """)

    updates = []
    for r in rows:
        # std_ciclo esta en segundos; tiempo_real_min en minutos.
        std_ciclo = (r["std_ciclo"] or 60) / 60.0
        t_real = r["tiempo_real_min"]
        qty = r["cantidad_producida"]
        t_productivo = max(t_real, 0.1)
        rendimiento_nuevo = round((qty / t_productivo) / (1 / std_ciclo) * 100, 1)
        rendimiento_nuevo = min(rendimiento_nuevo, 999)
        desvio_nuevo = 1 if rendimiento_nuevo < 80 else 0

        if abs((r["rendimiento_pct"] or 0) - rendimiento_nuevo) < 0.05 and r["desvio"] == desvio_nuevo:
            continue
        updates.append((rendimiento_nuevo, desvio_nuevo, r["id"]))

    for rendimiento_nuevo, desvio_nuevo, nid in updates:
        execute("UPDATE novedades_produccion SET rendimiento_pct=?, desvio=? WHERE id=?",
            (rendimiento_nuevo, desvio_nuevo, nid))

    return jsonify({"ok": True, "corregidas": len(updates)})

@app.route("/api/novedades", methods=["GET"])
@login_required()
def get_novedades():
    oid = request.args.get("orden_id")
    operacion_id = request.args.get("operacion_id")
    empleado_id = request.args.get("empleado_id")
    producto_id = request.args.get("producto_id")
    cliente_id = request.args.get("cliente_id")
    maquina_id = request.args.get("maquina_id")
    fecha_desde = request.args.get("fecha_desde")
    fecha_hasta = request.args.get("fecha_hasta")
    ocultar_completadas = request.args.get("ocultar_completadas")
    sql = """SELECT n.*,e.nombre||' '||e.apellido empleado_nombre,
        m.codigo||' — '||m.nombre maquina_nombre,
        oo.nombre operacion_nombre, oo.orden op_orden,
        o.numero ot_numero, o.producto_id, o.cliente_id, o.estado ot_estado,
        p.nombre producto_nombre, p.codigo producto_codigo,
        c.razon cliente_nombre,
        (SELECT GROUP_CONCAT(cj.numero || ' (' || printf('%g', nc.cantidad) || ')', ', ')
            FROM novedad_cajones nc JOIN cajones cj ON cj.id=nc.cajon_id
            WHERE nc.novedad_id=n.id) cajones_txt
        FROM novedades_produccion n
        LEFT JOIN empleados e ON e.id=n.empleado_id
        LEFT JOIN maquinas m ON m.id=n.maquina_id
        JOIN orden_operaciones oo ON oo.id=n.orden_operacion_id
        JOIN ordenes o ON o.id=n.orden_id
        LEFT JOIN productos p ON p.id=o.producto_id
        LEFT JOIN clientes c ON c.id=o.cliente_id"""
    where = []
    params = []
    if oid: where.append("n.orden_id=?"); params.append(oid)
    if operacion_id: where.append("n.orden_operacion_id=?"); params.append(operacion_id)
    if empleado_id: where.append("n.empleado_id=?"); params.append(empleado_id)
    if producto_id: where.append("o.producto_id=?"); params.append(producto_id)
    if cliente_id: where.append("o.cliente_id=?"); params.append(cliente_id)
    if maquina_id: where.append("n.maquina_id=?"); params.append(maquina_id)
    if fecha_desde: where.append("n.fecha>=?"); params.append(fecha_desde)
    if fecha_hasta: where.append("n.fecha<=?"); params.append(fecha_hasta)
    if ocultar_completadas in ("1","true"): where.append("o.estado NOT IN ('Completada','Cancelada')")
    sql += (" WHERE "+" AND ".join(where)) if where else ""
    sql += " ORDER BY n.id DESC"
    if not where: sql += " LIMIT 200"
    rows = query(sql, tuple(params)) if params else query(sql)
    return jsonify([dict(r) for r in rows])

def _bloqueo_terc_previo(orden_id, orden_num):
    """Si hay una operación tercerizada ANTERIOR (orden menor) en la misma OT
    que todavía no está Completada, la OT queda pausada: no se puede avanzar
    con operaciones posteriores hasta que el proveedor devuelva el lote y
    quede Aprobado (ver ott_registrar_retorno / update_lote).
    Devuelve la fila bloqueante o None si no hay bloqueo."""
    try:
        orden_num_int = float(orden_num)
    except Exception:
        return None
    return query("""SELECT nombre, orden FROM orden_operaciones
        WHERE orden_id=? AND es_tercerizada=1 AND estado!='Completada'
          AND CAST(orden AS REAL) < ?
        ORDER BY CAST(orden AS REAL) LIMIT 1""",
        (orden_id, orden_num_int), one=True)

def _tope_terc_previa(orden_id, orden_num):
    """Devuelve la operación tercerizada ANTERIOR (orden menor) más cercana
    en la misma OT junto con lo que ya aprobó/produjo hasta el momento
    (qty_producida) — o None si no hay ninguna. Esto se usa para permitir
    cargar novedades en la operación siguiente de forma incremental,
    topeadas a lo que la tercerizada ya entregó/aprobó hasta ahora (ver
    _sync_ott_retorno_a_operacion: si de 100 llegaron y se aprobaron 50, acá
    se puede cargar hasta 50, no hay que esperar a que vuelva/apruebe todo).

    IMPORTANTE: a diferencia de _bloqueo_terc_previo (que deja de bloquear
    en cuanto la tercerizada llega a 'Completada'), este tope NO filtra por
    estado. Tiene que seguir aplicando incluso después de que la tercerizada
    quede Completada, porque sigue siendo el límite físico real de lo que
    volvió aprobado del proveedor: si ya se cargaron 50 acá (mientras la
    tercerizada estaba en 50/100) y después se aprueban en OTRO lote las 50
    rechazadas restantes (tercerizada ahora en 100/100, Completada), lo
    disponible para seguir cargando esta operación es 100 (total aprobado)
    MENOS lo ya cargado (50) = 50, no 100 de nuevo. Si acá se dejara de
    aplicar el tope al completarse la tercerizada, se perdía esa resta y se
    podía volver a cargar hasta el total (100) ignorando lo ya declarado —
    ese era el bug: quedaba limitado únicamente por el estado de la
    operación tercerizada en vez de por la cantidad real ya aprobada."""
    try:
        orden_num_int = float(orden_num)
    except Exception:
        return None
    return query("""SELECT id, nombre, orden, qty_producida FROM orden_operaciones
        WHERE orden_id=? AND es_tercerizada=1
          AND CAST(orden AS REAL) < ?
        ORDER BY CAST(orden AS REAL) DESC LIMIT 1""",
        (orden_id, orden_num_int), one=True)

@app.route("/api/novedades", methods=["POST"])
@login_required(roles=["admin","operario"])
def create_novedad():
    d = request.json
    if not d.get("orden_id") or not d.get("orden_operacion_id"):
        return jsonify({"error":"orden_id y orden_operacion_id requeridos"}), 400
    qty = float(d.get("cantidad_producida",0) or 0)
    piezas_no_ok = float(d.get("piezas_observadas",0) or 0)
    t_real = float(d.get("tiempo_real_min",0))
    if qty<=0 and piezas_no_ok<=0: return jsonify({"error":"Cargue cantidad OK o piezas NO OK"}), 400
    if t_real<=0: return jsonify({"error":"El tiempo debe ser mayor a 0"}), 400
    # La vinculación de lote a un material de la OT se hace exclusivamente
    # desde Órdenes de trabajo → "Lotes asignados" (botón "Asignar lote").
    # Acá, al declarar una novedad, solo se CONSUME el lote que ya haya sido
    # vinculado por ese camino — no se acepta elegir/crear un vínculo nuevo
    # desde este endpoint.

    op = query("""SELECT oo.*,po.tiempo_ciclo_seg std_ciclo,po.producto_id
        FROM orden_operaciones oo
        LEFT JOIN proceso_operaciones po ON po.id=oo.proceso_op_id
        WHERE oo.id=?""", (d["orden_operacion_id"],), one=True)
    if not op: return jsonify({"error":"Operación no encontrada"}), 404
    if int(op["orden_id"]) != int(d["orden_id"]):
        return jsonify({"error":"La operación no pertenece a esa OT"}), 400
    _ot_nov = query("SELECT estado FROM ordenes WHERE id=?", (d["orden_id"],), one=True)
    if _ot_nov and _ot_nov["estado"] == "Cancelada":
        return jsonify({"error":"La OT está cancelada: no se pueden cargar novedades"}), 400

    # ── Operación tercerizada: no se carga por Novedades. Se completa sola
    # cuando vuelve el lote del proveedor (OTT → Lotes → Aprobado). ────────
    if op["es_tercerizada"]:
        return jsonify({"error": "Esta operación es tercerizada: no se carga por Novedades. "
            "Se completa automáticamente cuando vuelve el lote del proveedor (OTT) y queda Aprobado en Lotes."}), 400

    # ── OT pausada por una operación tercerizada ANTERIOR sin completar:
    # NO se bloquea todo — se topea lo que se puede cargar en esta operación
    # a lo que la tercerizada ya entregó/aprobó hasta el momento (uso
    # incremental). Ej: de 100 llegaron y se aprobaron 50 → se puede cargar
    # esta operación hasta 50 en total, sin esperar a que vuelva/apruebe el
    # resto. ─────────────────────────────────────────────────────────────
    qty_req_op = float(op["qty_requerida"] or 0)
    qty_prod_op = float(op["qty_producida"] or 0)
    tope_terc = _tope_terc_previa(d["orden_id"], op["orden"])
    if tope_terc:
        disponible_terc = float(tope_terc["qty_producida"] or 0)
        if disponible_terc <= 0.0001:
            return jsonify({"error": f"OT pausada: la operación tercerizada \"{tope_terc['nombre']}\" "
                f"(orden {tope_terc['orden']}) todavía no tiene nada recibido/aprobado. No se pueden "
                f"cargar novedades de esta operación hasta que vuelva y se apruebe al menos una parte "
                f"del lote del proveedor."}), 400
        if qty_prod_op + qty > disponible_terc + 0.0001:
            return jsonify({"error": f"Cantidad excede lo disponible de la operación tercerizada "
                f"\"{tope_terc['nombre']}\" (orden {tope_terc['orden']}): aprobado hasta ahora "
                f"{disponible_terc:g}, ya cargado en esta operación {qty_prod_op:g}, "
                f"disponible para esta novedad {max(0, disponible_terc - qty_prod_op):g}."}), 400

    # ── Si la operación está marcada como "Completada", no se pueden cargar
    # más novedades. Si el usuario la volvió a poner "En proceso" manualmente
    # (por ejemplo desde Control de Producción) después de haber llegado al
    # 100%, se le permite seguir cargando novedades: el bloqueo es por
    # ESTADO, no por haber alcanzado la cantidad requerida. Solo se vuelve a
    # bloquear cuando el usuario la marca Completada de nuevo (manual o
    # automáticamente al llegar al 100%). ───────────────────────────────────
    if op["estado"] == "Completada":
        return jsonify({"error": "No se puede cargar más novedades: la operación ya está marcada como Completada (%s/%s piezas). Volvé a ponerla en proceso para seguir cargando." % (qty_prod_op, qty_req_op)}), 400

    # El ciclo estandar se carga en segundos y el tiempo real se declara en
    # minutos, asi que se pasa a minutos para calcular el rendimiento.
    std_ciclo = (op["tiempo_ciclo_seg"] or op["std_ciclo"] or 60) / 60.0
    t_perdido = float(d.get("tiempo_perdido") or 0)
    # tiempo_real = tiempo EFECTIVAMENTE trabajado (ya neto).
    # tiempo_perdido = tiempo aparte que no se trabajó (no está incluido en tiempo_real).
    # Por lo tanto el rendimiento se calcula sobre tiempo_real solo, sin restar nada.
    t_productivo = max(t_real, 0.1)
    rendimiento = round((qty / t_productivo) / (1 / std_ciclo) * 100, 1)
    rendimiento = min(rendimiento, 999)
    desvio = 1 if rendimiento < 80 else 0

    # ── VALIDACIONES DE STOCK/LOTES: se hacen TODAS antes de insertar nada,
    # así si algo falla no queda la novedad guardada a medias (ver bug donde
    # el INSERT ocurría antes de estas validaciones y la novedad quedaba
    # creada aunque el sistema mostrara un error de stock insuficiente). ──
    mats_op = []
    insumos_op = []
    lotes_info = {}
    if True:
        mats_op_all = query("""SELECT om.*, m.descripcion descripcion, m.categoria categoria
            FROM orden_operacion_materiales om JOIN materiales m ON m.id=om.material_id
            WHERE om.orden_operacion_id=?""", (op["id"],))
        mats_op = [m for m in mats_op_all if m["categoria"] not in ("Insumo", "Herramienta")]
        insumos_op = [m for m in mats_op_all if m["categoria"] in ("Insumo", "Herramienta")]
    # ── Material semielaborado de una OTT anterior (no está en el BOM del
    # producto porque se generó dinámicamente al recibir el retorno del
    # proveedor) — ver _materiales_ott_pendientes_por_operacion. Se chequea
    # siempre, incluso si esta operación no tiene proceso_op_id (agregada a
    # mano), porque este material no depende de la plantilla de proceso.
    for extra in _materiales_ott_pendientes_por_operacion(d["orden_id"], d["orden_operacion_id"]):
        if not any(m["material_id"] == extra["material_id"] for m in mats_op):
            mats_op.append(extra)

    # Validar stock disponible para insumos (se descuentan recién al
    # completar la OT, pero acá se valida que alcance considerando lo
    # ya comprometido por otras operaciones/novedades de la misma OT
    # más lo que agrega esta novedad, para no permitir cargar una
    # novedad que termine consumiendo más de lo que hay en stock).
    # Las herramientas, en cambio, se descuentan con cada novedad
    # (consumir_herramientas_op): para ellas cuenta solo lo que falta descontar.
    if insumos_op:
        errores_ins = []
        for ins in insumos_op:
            # Consumo de toda la OT contando esta novedad (herramientas con
            # vida útil: ceil por operación, ver cant_material).
            total_necesario = float(query("""SELECT COALESCE(SUM(CASE WHEN m.categoria='Herramienta'
                    -- herramientas: solo lo que falta descontar (el resto ya salió del stock)
                    THEN MAX(0, cant_material(om.cantidad, oo.qty_producida + CASE WHEN oo.id=? THEN ? ELSE 0 END,
                                              om.vida_util_herramienta) - COALESCE(om.herr_consumido,0))
                    ELSE cant_material(om.cantidad, oo.qty_producida + CASE WHEN oo.id=? THEN ? ELSE 0 END,
                                       om.vida_util_herramienta) END),0) c
                FROM orden_operaciones oo
                JOIN orden_operacion_materiales om ON om.orden_operacion_id=oo.id
                JOIN materiales m ON m.id=om.material_id
                WHERE oo.orden_id=? AND om.material_id=?""",
                (op["id"], qty, op["id"], qty, d["orden_id"], ins["material_id"]), one=True)["c"] or 0)
            mat_stock = query("SELECT stock FROM materiales WHERE id=?", (ins["material_id"],), one=True)
            stock_disp = float(mat_stock["stock"] or 0) if mat_stock else 0
            if total_necesario > stock_disp:
                faltante = round(total_necesario - stock_disp, 3)
                errores_ins.append(f"Stock insuficiente de insumo \"{ins['descripcion']}\" (stock {stock_disp}, requerido {round(total_necesario,3)}, faltan {faltante})")
        if errores_ins:
            return jsonify({"error": "No se puede confirmar la novedad: " + " | ".join(errores_ins)}), 400

    if mats_op:
        errores = []
        for mat in mats_op:
            consumo = mat["cantidad"] * qty
            # Si el material fue añadido al proceso DESPUÉS de creada la
            # OT, no está en la foto de orden_materiales (tomada al
            # crear la OT) y por lo tanto tampoco aparece en "Lotes
            # asignados" para poder vincularle un lote ahí — pedirlo acá
            # dejaría al usuario sin forma de resolverlo. Se lo salta,
            # EXCEPTO si ya tiene un lote vinculado igual (ej. retorno de
            # una OTT, que reserva el lote vía orden_lotes aunque la
            # fila de orden_materiales no exista o el UPDATE de
            # cantidad_asignada no haya afectado ninguna fila): en ese
            # caso hay un vínculo real esperando a consumirse y no debe
            # perderse en silencio.
            en_ot = query("SELECT 1 FROM orden_materiales WHERE orden_id=? AND material_id=?",
                (d["orden_id"], mat["material_id"]), one=True)
            tiene_vinculo_previo = query("""SELECT 1 FROM orden_lotes
                WHERE orden_id=? AND material_id=?""",
                (d["orden_id"], mat["material_id"]), one=True)
            if not en_ot and not tiene_vinculo_previo:
                continue
            # Si este material ya tiene uno o más lotes vinculados a la
            # OT (de una novedad anterior o de una/varias asignaciones
            # manuales desde "Lotes asignados"), se consume de ESOS
            # lotes — pueden ser VARIOS: si el primero no alcanza para
            # cubrir todo el consumo, se completa con los siguientes
            # lotes vinculados (ej. un lote de 90 + uno de 10, o varios
            # lotes chicos), en orden de ingreso (FIFO).
            vinculos = _lotes_vinculados_material(d["orden_id"], mat["material_id"])
            if not vinculos:
                errores.append(f"Falta vincular un lote para \"{mat['descripcion'] if 'descripcion' in mat.keys() else mat['material_id']}\" — hacelo desde Órdenes de trabajo → Lotes asignados antes de declarar la novedad")
                continue
            # Disponible: los lotes vinculados a esta OT son reservas
            # propias de ella (ver _plan_consumo_adicional) — no se les
            # resta cantidad_reservada, esa resta solo aplica al elegir
            # un lote nuevo desde "Lotes asignados".
            plan, disponible_total, cubierto = _plan_consumo_adicional(vinculos, consumo)
            if not cubierto:
                detalle = ", ".join(f"{l['numero']} (libre {max(0, float(l['cantidad_activa'] or 0))})" for l in vinculos)
                errores.append(f"Stock disponible insuficiente en lote(s) vinculados [{detalle}] (disponible total {disponible_total}, requerido {consumo})")
                continue
            lotes_info[mat["material_id"]] = plan
        if errores:
            return jsonify({"error": "No se puede confirmar la novedad: " + " | ".join(errores)}), 400

    # ── Cajones: en el primer paso las piezas OK llenan cajones solas; en los
    # siguientes se indica en qué cajón(es) se trabajó, con tope por cajón
    # (ver _plan_cajones_paso). Las piezas NO OK no se imputan a cajones. ──
    usa_cajones = qty > 0 and _ot_usa_cajones(d["orden_id"])
    plan_cajones = None
    if usa_cajones:
        pasos_ot = _pasos_ot(d["orden_id"])
        paso_op = query("SELECT CAST(orden AS INTEGER) p FROM orden_operaciones WHERE id=?",
            (op["id"],), one=True)["p"]
        if paso_op != pasos_ot[0]:
            plan_cajones, err = _plan_cajones_paso(d["orden_id"], paso_op, qty, d.get("cajones"))
            if err:
                return jsonify({"error": "No se puede confirmar la novedad: " + err}), 400

    # ── Todas las validaciones pasaron: recién ahora se inserta la novedad ──
    numero = siguiente_numero("novedades_produccion", "NOV-", 5)

    fecha_nov = d.get("fecha") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lid = execute("""INSERT INTO novedades_produccion
        (numero,orden_id,orden_operacion_id,empleado_id,maquina_id,cantidad_producida,tiempo_real_min,
         piezas_observadas,tiempo_perdido,turno,fecha,rendimiento_pct,desvio,obs,creado_por)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (numero,d["orden_id"],d["orden_operacion_id"],d.get("empleado_id"),d.get("maquina_id"),qty,t_real,
         d.get("piezas_observadas") or 0, d.get("tiempo_perdido") or 0,
         d.get("turno"),fecha_nov,rendimiento,desvio,d.get("obs"),session["user_id"]))

    execute("UPDATE orden_operaciones SET qty_producida=qty_producida+? WHERE id=?",
        (qty, d["orden_operacion_id"]))
    consumir_herramientas_op(d["orden_operacion_id"])
    if usa_cajones:
        if plan_cajones is None:
            _guardar_novedad_cajones(lid, d["orden_id"], [], extra=qty)
        else:
            _guardar_novedad_cajones(lid, d["orden_id"], plan_cajones)

    # En cuanto se declara la primera novedad de producción, la OT pasa de
    # "Pendiente" a "En proceso" (si ya estaba en otro estado —En proceso,
    # Completada, etc.— no se toca).
    execute("UPDATE ordenes SET estado='En proceso' WHERE id=? AND estado='Pendiente'",
        (d["orden_id"],))

    # ── Si con esta novedad la operación llegó (o superó) el 100% de lo
    # requerido, se marca automáticamente como "Completada". No se toca el
    # estado si la operación ya estaba marcada como Completada de antes
    # (evita pisar, por ejemplo, un estado "Completada" manual con datos
    # distintos) ni si todavía no llegó al 100%. TAMPOCO se auto-completa si
    # la operación YA estaba en o por encima del 100% ANTES de esta novedad
    # (esto pasa cuando el usuario la reabrió manualmente a "En proceso"
    # después de haberla completado antes): en ese caso se le deja seguir
    # cargando novedades libremente y la operación solo vuelve a
    # "Completada" cuando el usuario la marca así manualmente. ─────────────
    ya_estaba_al_100 = qty_req_op > 0 and qty_prod_op >= qty_req_op - 0.0001
    if op["estado"] != "Completada" and not ya_estaba_al_100:
        _sincronizar_estado_paso(d["orden_operacion_id"])

    # Consumir materias primas/PT vinculadas a un lote: DESCUENTO REAL E
    # INMEDIATO en cuanto se declara la novedad (la novedad ya representa
    # producción efectivamente realizada, así que el material se da por
    # gastado en el momento, sin esperar a que la OT se marque como
    # "Completada"). La vinculación de lote sigue siendo OBLIGATORIA por
    # cada material/PT requerido por la operación, EXCEPTO los de categoría
    # "Insumo": esos no llevan trazabilidad por lote y se descuentan directo
    # del stock general al completar la OT (ver update_orden).
    # La validación de stock ya se hizo arriba (lotes_info).
    if mats_op:
        for mat in mats_op:
            plan = lotes_info.get(mat["material_id"])
            if plan is None:
                # Mismo criterio que en la validación de arriba: material
                # agregado al proceso después de creada la OT, sin lote para
                # vincular todavía — no se descuenta, no rompe la novedad.
                continue
            for lote_activo, consumo in plan:
                # Descuento real: cantidad_disponible, cantidad_activa del lote
                # y stock general del material. También se libera cualquier
                # reserva previa sobre ese mismo lote (p.ej. si se había
                # asignado manualmente desde "Lotes asignados" antes de esta
                # novedad), para no dejar cantidad_reservada desalineada.
                execute("""UPDATE lotes SET
                        cantidad_disponible=MAX(0, cantidad_disponible-?),
                        cantidad_activa=MAX(0, cantidad_activa-?),
                        cantidad_reservada=MAX(0, COALESCE(cantidad_reservada,0)-?),
                        estado=CASE WHEN cantidad_disponible-? <= 0 THEN 'Agotado' ELSE estado END
                    WHERE id=?""", (consumo, consumo, consumo, consumo, lote_activo["id"]))
                execute("""UPDATE materiales SET stock=MAX(0, stock-?), actualizado=datetime('now','localtime')
                    WHERE id=?""", (consumo, mat["material_id"]))
                auto_generar_sc_bajo_stock(mat["material_id"], f"consumo Novedad {numero}")
                # NOTA: NO se vuelve a sumar a orden_materiales.cantidad_asignada
                # acá. Ese campo ya quedó incrementado en el momento en que el
                # lote se vinculó a esta OT (botón "Asignar lote", o el retorno
                # de una OTT), que es justo el requisito para poder entrar a
                # este bloque (_lotes_vinculados_material exige que ya haya un
                # vínculo). Esta novedad solo CONVIERTE esa reserva en consumo
                # real (por eso se descuenta cantidad_reservada arriba); sumarlo
                # de nuevo acá duplicaba el total y hacía que "Lotes asignados"
                # mostrara más cantidad asignada que la que realmente se asignó
                # (ej. reservar 100 y cargar una novedad de 50 mostraba 150).
                # Marcar en orden_lotes cuánto de lo YA ASIGNADO a este lote
                # se consumió realmente. cantidad_usada es el TOTAL
                # comprometido (asignado) para este lote+OT — ya quedó
                # cargado al vincular el lote (Asignar lote / retorno OTT) y
                # NO se vuelve a tocar acá. cantidad_consumida es el
                # subconjunto de ese total que ya se gastó de verdad; es la
                # que avanza con cada novedad (siempre existe la fila porque
                # _lotes_vinculados_material ya exigió el vínculo arriba).
                execute("""UPDATE orden_lotes SET
                        cantidad_consumida=COALESCE(cantidad_consumida,0)+?
                    WHERE orden_id=? AND lote_id=?""",
                    (consumo, d["orden_id"], lote_activo["id"]))
                execute("INSERT INTO movimientos (material_id,lote_id,tipo,cantidad,referencia,usuario_id) VALUES (?,?,?,?,?,?)",
                    (mat["material_id"], lote_activo["id"], "salida", consumo,
                     f"Consumo real por Novedad {numero} — Lote {lote_activo['numero']} (descuento inmediato)",
                     session["user_id"]))



    # ── Generación inmediata de PT por cajón ────────────────────────────────
    # Si esta novedad es de la ÚLTIMA operación de la ruta, ya representa
    # piezas terminadas: el circuito real es que el operario las deja en
    # bolsa y después las lleva con un cajón a Calidad. Por eso acá se
    # genera/actualiza de inmediato el lote de PT correspondiente al cajón
    # en curso (ver generar_pt_faltante_si_corresponde), en vez de esperar a
    # que toda la OT se marque "Completada" y mezclar todo en un solo lote.
    # Si el producto no tiene capacidad_cajon configurada, esta misma llamada
    # mantiene el comportamiento anterior (un solo lote por OT).
    # Se envuelve en try/except para no perder la novedad ya guardada si algo
    # falla acá: update_orden() vuelve a llamar a esta función como red de
    # seguridad al completar la OT, así que no queda nada sin generar.
    try:
        max_orden = query("""SELECT MAX(CAST(orden AS INTEGER)) mx
            FROM orden_operaciones WHERE orden_id=?""", (d["orden_id"],), one=True)["mx"]
        if max_orden is not None and int(op["orden"]) == int(max_orden):
            generar_pt_faltante_si_corresponde(d["orden_id"])
    except Exception as e:
        print(f"[WARN] No se pudo generar PT/cajón al declarar novedad {numero} (OT {d['orden_id']}): {e}")
    if usa_cajones:
        _cajones_vincular_lote(d["orden_id"])
    cajones_nov = [r["numero"] for r in query("""SELECT cj.numero FROM novedad_cajones nc
        JOIN cajones cj ON cj.id=nc.cajon_id WHERE nc.novedad_id=? ORDER BY cj.id""", (lid,))]

    return jsonify({"ok":True,"id":lid,"numero":numero,"rendimiento_pct":rendimiento,"desvio":desvio,
                    "cajones":cajones_nov}), 201






@app.route("/api/novedades/<int:nid>", methods=["GET"])
@login_required()
def get_novedad(nid):
    row = query("""SELECT n.*,e.nombre||' '||e.apellido empleado_nombre,
        m.codigo||' — '||m.nombre maquina_nombre,
        oo.nombre operacion_nombre, oo.orden op_orden,
        oo.proceso_op_id, oo.orden_id,
        o.numero ot_numero, o.producto_id
        FROM novedades_produccion n
        LEFT JOIN empleados e ON e.id=n.empleado_id
        LEFT JOIN maquinas m ON m.id=n.maquina_id
        JOIN orden_operaciones oo ON oo.id=n.orden_operacion_id
        JOIN ordenes o ON o.id=n.orden_id
        WHERE n.id=?""", (nid,), one=True)
    if not row: return jsonify({"error":"Novedad no encontrada"}), 404
    out = dict(row)
    out["cajones"] = [dict(r) for r in query("""SELECT nc.cajon_id, nc.cantidad, cj.numero
        FROM novedad_cajones nc JOIN cajones cj ON cj.id=nc.cajon_id
        WHERE nc.novedad_id=? ORDER BY cj.id""", (nid,))]
    return jsonify(out)

@app.route("/api/novedades/<int:nid>", methods=["PUT"])
@login_required(roles=["admin","operario"])
def update_novedad(nid):
    """Edita una novedad y ajusta stocks/consumos por diferencia."""
    d = request.json
    nov = query("""SELECT n.*,oo.proceso_op_id,oo.orden,oo.orden_id,o.producto_id
        FROM novedades_produccion n
        JOIN orden_operaciones oo ON oo.id=n.orden_operacion_id
        JOIN ordenes o ON o.id=n.orden_id
        WHERE n.id=?""", (nid,), one=True)
    if not nov: return jsonify({"error":"Novedad no encontrada"}), 404

    qty_old = float(nov["cantidad_producida"])
    _qty_raw = d.get("cantidad_producida", None)
    qty_new = qty_old if _qty_raw in (None,"") else float(_qty_raw)
    t_old   = float(nov["tiempo_real_min"])
    t_new   = float(d.get("tiempo_real_min", t_old))
    diff    = qty_new - qty_old  # positive = more produced, negative = less

    # --- Cajones: se valida antes de tocar nada (tope por cajón, pasos
    # siguientes y lo ya clasificado por Calidad) ---
    plan_cajones, extra_cajones = None, 0.0
    if _ot_tiene_cajones(nov["orden_id"]) and (diff != 0 or d.get("cajones")):
        plan_cajones, extra_cajones, err = _replan_novedad_cajones(
            nid, nov["orden_id"], nov["orden_operacion_id"], qty_new, d.get("cajones"))
        if err:
            return jsonify({"error": "No se puede editar la novedad: " + err}), 400

    # --- Validar stock de insumos si se está aumentando la cantidad ---
    if diff > 0:
        insumos_op = query("""SELECT om.*, m.descripcion descripcion
            FROM orden_operacion_materiales om JOIN materiales m ON m.id=om.material_id
            WHERE om.orden_operacion_id=? AND m.categoria IN ('Insumo','Herramienta')""", (nov["orden_operacion_id"],))
        if insumos_op:
            errores_ins = []
            for ins in insumos_op:
                total_necesario = float(query("""SELECT COALESCE(SUM(CASE WHEN m.categoria='Herramienta'
                        THEN MAX(0, cant_material(om.cantidad, oo.qty_producida + CASE WHEN oo.id=? THEN ? ELSE 0 END,
                                                  om.vida_util_herramienta) - COALESCE(om.herr_consumido,0))
                        ELSE cant_material(om.cantidad, oo.qty_producida + CASE WHEN oo.id=? THEN ? ELSE 0 END,
                                           om.vida_util_herramienta) END),0) c
                    FROM orden_operaciones oo
                    JOIN orden_operacion_materiales om ON om.orden_operacion_id=oo.id
                    JOIN materiales m ON m.id=om.material_id
                    WHERE oo.orden_id=? AND om.material_id=?""",
                    (nov["orden_operacion_id"], diff, nov["orden_operacion_id"], diff, nov["orden_id"], ins["material_id"]), one=True)["c"] or 0)
                mat_stock = query("SELECT stock FROM materiales WHERE id=?", (ins["material_id"],), one=True)
                stock_disp = float(mat_stock["stock"] or 0) if mat_stock else 0
                if total_necesario > stock_disp:
                    faltante = round(total_necesario - stock_disp, 3)
                    errores_ins.append(f"Stock insuficiente de insumo \"{ins['descripcion']}\" (stock {stock_disp}, requerido {round(total_necesario,3)}, faltan {faltante})")
            if errores_ins:
                return jsonify({"error": "No se puede confirmar el ajuste: " + " | ".join(errores_ins)}), 400


    # --- Ajustar el CONSUMO REAL de materias primas (diferencia) ---
    # Desde que el material se descuenta al declarar la novedad (ver
    # create_novedad), editar la cantidad producida debe ajustar el stock y
    # el lote ya consumidos por la diferencia, usando el lote que ya estaba
    # vinculado a este material en la OT.
    if diff != 0:
        mats_op = []
        if True:
            mats_op = query("""SELECT om.*, m.categoria categoria
                FROM orden_operacion_materiales om JOIN materiales m ON m.id=om.material_id
                WHERE om.orden_operacion_id=?""", (nov["orden_operacion_id"],))
            mats_op = [dict(m) for m in mats_op]
        for extra in _materiales_ott_pendientes_por_operacion(nov["orden_id"], nov["orden_operacion_id"]):
            if not any(m["material_id"] == extra["material_id"] for m in mats_op):
                mats_op.append(extra)
        for mat in mats_op:
            if mat["categoria"] in ("Insumo", "Herramienta"):
                continue  # los insumos/herramientas se calculan/descuentan recién al completar la OT
            consumo_diff = mat["cantidad"] * diff  # + = se consume más, - = se devuelve stock
            vinculos = _lotes_vinculados_material(nov["orden_id"], mat["material_id"])
            if not vinculos:
                continue  # no había lote vinculado para este material en esta OT
            if consumo_diff < 0:
                # Se devuelve stock: repartir entre los lotes vinculados
                # (LIFO), igual que al eliminar una novedad, en vez de
                # volcarlo entero a un único lote.
                plan = _plan_devolucion(vinculos, -consumo_diff)
                movs = [(lote_v["id"], lote_v["numero"], devolver) for lote_v, devolver in plan]
                devuelto_total = sum(d for _, _, d in movs)
                faltante = round(-consumo_diff - devuelto_total, 6)
                if faltante > 0.0001:
                    lote_v = vinculos[-1]
                    movs.append((lote_v["id"], lote_v["numero"], faltante))
                for lote_id, lote_num, cant in movs:
                    if cant <= 0: continue
                    execute("""UPDATE lotes SET
                            cantidad_disponible=cantidad_disponible+?,
                            cantidad_activa=cantidad_activa+?,
                            estado=CASE WHEN estado='Agotado' AND cantidad_disponible+?>0 THEN 'Aprobado' ELSE estado END
                        WHERE id=?""", (cant, cant, cant, lote_id))
                    execute("""UPDATE materiales SET stock=stock+?, actualizado=datetime('now','localtime')
                        WHERE id=?""", (cant, mat["material_id"]))
                    # cantidad_usada (total ASIGNADO al lote para esta OT) y
                    # orden_materiales.cantidad_asignada NO se tocan acá: ese
                    # total lo define "Asignar lote", no las novedades. Bajar
                    # la cantidad producida solo revierte lo CONSUMIDO.
                    execute("""UPDATE orden_lotes SET cantidad_consumida=MAX(0,COALESCE(cantidad_consumida,0)-?)
                        WHERE orden_id=? AND lote_id=?""",
                            (cant, nov["orden_id"], lote_id))
                    execute("INSERT INTO movimientos (material_id,lote_id,tipo,cantidad,referencia,usuario_id) VALUES (?,?,?,?,?,?)",
                            (mat["material_id"], lote_id, "entrada", cant,
                             f"Ajuste consumo {nov['numero']} — Lote {lote_num}", session["user_id"]))
            else:
                # Se consume más: seguir tomando del lote vinculado más
                # reciente (mismo criterio FIFO que create_novedad ya usa
                # para el consumo inicial, vía _plan_consumo_adicional).
                plan, _, cubierto = _plan_consumo_adicional(vinculos, consumo_diff)
                for lote_v, tomar in plan:
                    execute("""UPDATE lotes SET
                            cantidad_disponible=MAX(0, cantidad_disponible-?),
                            cantidad_activa=MAX(0, cantidad_activa-?),
                            cantidad_reservada=MAX(0, COALESCE(cantidad_reservada,0)-?),
                            estado=CASE WHEN cantidad_disponible-? <= 0 THEN 'Agotado' ELSE estado END
                        WHERE id=?""", (tomar, tomar, tomar, tomar, lote_v["id"]))
                    execute("""UPDATE materiales SET stock=MAX(0, stock-?), actualizado=datetime('now','localtime')
                        WHERE id=?""", (tomar, mat["material_id"]))
                    # cantidad_usada / cantidad_asignada NO suben acá: ya
                    # estaban comprometidas desde que se asignó el lote.
                    # Subir la cantidad producida solo convierte más de esa
                    # reserva ya comprometida en consumo real.
                    execute("""UPDATE orden_lotes SET cantidad_consumida=COALESCE(cantidad_consumida,0)+?
                        WHERE orden_id=? AND lote_id=?""",
                            (tomar, nov["orden_id"], lote_v["id"]))
                    execute("INSERT INTO movimientos (material_id,lote_id,tipo,cantidad,referencia,usuario_id) VALUES (?,?,?,?,?,?)",
                            (mat["material_id"], lote_v["id"], "salida", tomar,
                             f"Ajuste consumo {nov['numero']} — Lote {lote_v['numero']}", session["user_id"]))

    # --- Ajustar qty_producida en orden_operacion ---
    execute("UPDATE orden_operaciones SET qty_producida=MAX(0,qty_producida+?) WHERE id=?",
            (diff, nov["orden_operacion_id"]))
    consumir_herramientas_op(nov["orden_operacion_id"])
    if plan_cajones is not None:
        _guardar_novedad_cajones(nid, nov["orden_id"], plan_cajones, extra_cajones)

    # --- Sincronizar estado con el 100%: si al editar la novedad la
    # operación pasa a tener 100% o más, se marca "Completada"; si al
    # editarla (achicando la cantidad) queda por debajo del 100% y estaba
    # marcada como Completada, se vuelve a "En proceso" para no dejarla
    # marcada como terminada sin estarlo. No se toca si el estado fue
    # cambiado manualmente a algo distinto de estos dos. ────────────────────
    oo_now = query("SELECT qty_requerida,qty_producida,estado FROM orden_operaciones WHERE id=?",
        (nov["orden_operacion_id"],), one=True)
    if oo_now:
        _sincronizar_estado_paso(nov["orden_operacion_id"])

    # --- Resincronizar el PT si es la ultima operacion ---
    # El PT producido vive en un LOTE pendiente de Calidad; materiales.stock
    # representa solo lo aprobado (ver liberar_lote). Antes aca se sumaba el
    # diff directo a materiales.stock: eso metia piezas en stock salteando
    # Calidad y, como el lote seguia sin actualizarse, la proxima novedad lo
    # completaba igual y esas piezas terminaban contadas DOS veces al aprobar.
    # Ahora se usa el mismo camino que el alta: recalcular el lote contra lo
    # realmente producido en el ultimo paso, sin tocar el stock.
    max_ord = query("SELECT MAX(CAST(orden AS INTEGER)) mo FROM orden_operaciones WHERE orden_id=?",
                    (nov["orden_id"],), one=True)["mo"]
    if nov["orden"] == max_ord and diff != 0 and nov["producto_id"]:
        try:
            generar_pt_faltante_si_corresponde(nov["orden_id"])
        except Exception as e:
            print(f"[WARN] No se pudo resincronizar el PT de la OT {nov['orden_id']} "
                  f"al editar la novedad {nov['numero']}: {e}")

    if plan_cajones is not None:
        _cajones_vincular_lote(nov["orden_id"])

    # --- Recalcular rendimiento ---
    op_std = query("SELECT tiempo_ciclo_seg FROM orden_operaciones WHERE id=?",
                   (nov["orden_operacion_id"],), one=True)
    # ciclo en minutos (la columna esta en segundos) para comparar contra
    # tiempo_real_min.
    ciclo = (float(op_std["tiempo_ciclo_seg"] or 60) if op_std else 60) / 60.0
    t_perd_new = float(d.get("tiempo_perdido", nov["tiempo_perdido"] if "tiempo_perdido" in nov.keys() else 0) or 0)
    # tiempo_real ya es tiempo neto trabajado; tiempo_perdido es aparte, no se resta.
    t_prod_new = max(t_new, 0.1) if t_new > 0 else 0.1
    rendimiento = round((qty_new / t_prod_new) / (1 / ciclo) * 100, 1) if t_new > 0 else 0
    rendimiento = min(rendimiento, 999)
    desvio = 1 if rendimiento < 80 else 0

    execute("""UPDATE novedades_produccion SET
            cantidad_producida=?, tiempo_real_min=?, empleado_id=?, maquina_id=?,
            piezas_observadas=?, tiempo_perdido=?,
            turno=?, obs=?, rendimiento_pct=?, desvio=?, fecha=?
            WHERE id=?""",
            (qty_new, t_new, d.get("empleado_id", nov["empleado_id"]), d.get("maquina_id", nov["maquina_id"]),
            d.get("piezas_observadas", nov["piezas_observadas"] if "piezas_observadas" in nov.keys() else 0) or 0,
            d.get("tiempo_perdido", nov["tiempo_perdido"] if "tiempo_perdido" in nov.keys() else 0) or 0,
            d.get("turno", nov["turno"]), d.get("obs", nov["obs"]),
            rendimiento, desvio, d.get("fecha", nov["fecha"]), nid))

    return jsonify({"ok": True, "diff": diff, "rendimiento_pct": rendimiento,
                    "desvio": desvio, "ajuste_pt": diff != 0})

@app.route("/api/novedades/<int:nid>", methods=["DELETE"])
@login_required(roles=["admin","operario"])
def delete_novedad(nid):
    """Elimina una novedad y revierte todos sus efectos en stock.
    Antes de borrarla, guarda un registro en novedades_eliminadas con el
    detalle de todo lo que se revirtió (lotes de materia prima, stock de
    producto terminado y remitos que ya hubieran usado ese stock), para
    que quede trazabilidad de qué se eliminó y qué efectos tuvo."""
    import json
    nov = query("""SELECT n.*,oo.proceso_op_id,oo.orden,oo.orden_id,oo.nombre operacion_nombre,
        o.producto_id,o.numero ot_numero,
        p.nombre producto_nombre,
        e.nombre||' '||e.apellido empleado_nombre,
        m.codigo||' — '||m.nombre maquina_nombre,
        u.nombre creado_por_nombre
        FROM novedades_produccion n
        JOIN orden_operaciones oo ON oo.id=n.orden_operacion_id
        JOIN ordenes o ON o.id=n.orden_id
        LEFT JOIN productos p ON p.id=o.producto_id
        LEFT JOIN empleados e ON e.id=n.empleado_id
        LEFT JOIN maquinas m ON m.id=n.maquina_id
        LEFT JOIN usuarios u ON u.id=n.creado_por
        WHERE n.id=?""", (nid,), one=True)
    if not nov: return jsonify({"error":"Novedad no encontrada"}), 404

    qty = float(nov["cantidad_producida"])
    detalle = {"lotes_mp": [], "pt": None, "remitos": []}
    lote_ids_afectados = set()
    pt_lote_ids = set()  # lotes de PT de esta OT — si tienen remitos, se eliminan (no solo se informan)

    # --- Cajones: no se puede sacar piezas que ya avanzaron a pasos
    # siguientes ni que Calidad ya clasificó ---
    filas_cajones = [dict(r) for r in query("""SELECT nc.cajon_id, nc.cantidad, cj.numero
        FROM novedad_cajones nc JOIN cajones cj ON cj.id=nc.cajon_id
        WHERE nc.novedad_id=? ORDER BY cj.id""", (nid,))]
    if filas_cajones:
        _, _, err = _replan_novedad_cajones(nid, nov["orden_id"], nov["orden_operacion_id"], 0.0)
        if err:
            return jsonify({"error": "No se puede eliminar la novedad: " + err}), 400
        detalle["cajones"] = filas_cajones

    # --- Devolver el CONSUMO REAL de materias primas al stock/lote ---
    # Desde que el material se descuenta al declarar la novedad (ver
    # create_novedad), eliminarla debe devolver ese stock ya consumido.
    if True:
        mats_op = query("""SELECT om.*, m.categoria categoria, m.descripcion descripcion
            FROM orden_operacion_materiales om JOIN materiales m ON m.id=om.material_id
            WHERE om.orden_operacion_id=?""", (nov["orden_operacion_id"],))
        mats_op = [dict(m) for m in mats_op]
    else:
        mats_op = []
    for extra in _materiales_ott_pendientes_por_operacion(nov["orden_id"], nov["orden_operacion_id"]):
        if not any(m["material_id"] == extra["material_id"] for m in mats_op):
            mats_op.append(extra)
    if True:
        for mat in mats_op:
            if mat["categoria"] in ("Insumo", "Herramienta"):
                continue
            consumo = mat["cantidad"] * qty
            # Puede haber consumido de VARIOS lotes (FIFO, ver create_novedad).
            # Repartir la devolución entre todos los lotes vinculados a este
            # material en esta OT (LIFO, sin superar cantidad_usada por
            # lote) en vez de volcarla entera a un único lote.
            vinculos = _lotes_vinculados_material(nov["orden_id"], mat["material_id"])
            if not vinculos:
                continue
            plan = _plan_devolucion(vinculos, consumo)
            if not plan:
                continue
            for lote_v, devolver in plan:
                # Devuelve stock real Y reconstituye la reserva para esta OT
                # (cantidad_reservada), porque el material seguía comprometido
                # con esta OT (orden_materiales.cantidad_asignada no cambia:
                # esa reserva nunca se "gastó" a nivel de total asignado, solo
                # pasaba de reservado a consumido — ahora vuelve a reservado).
                execute("""UPDATE lotes SET
                        cantidad_disponible=cantidad_disponible+?,
                        cantidad_activa=cantidad_activa+?,
                        cantidad_reservada=COALESCE(cantidad_reservada,0)+?,
                        estado=CASE WHEN estado='Agotado' AND cantidad_disponible+?>0 THEN 'Aprobado' ELSE estado END
                    WHERE id=?""", (devolver, devolver, devolver, devolver, lote_v["id"]))
                execute("""UPDATE materiales SET stock=stock+?, actualizado=datetime('now','localtime')
                    WHERE id=?""", (devolver, mat["material_id"]))
                execute("""UPDATE orden_lotes SET cantidad_consumida=MAX(0,COALESCE(cantidad_consumida,0)-?)
                    WHERE orden_id=? AND lote_id=?""",
                        (devolver, nov["orden_id"], lote_v["id"]))
                execute("INSERT INTO movimientos (material_id,lote_id,tipo,cantidad,referencia,usuario_id) VALUES (?,?,?,?,?,?)",
                        (mat["material_id"], lote_v["id"], "entrada", devolver,
                         f"Reversa {nov['numero']} — devuelve consumo Lote {lote_v['numero']}", session["user_id"]))
                lote_after = query("SELECT numero,estado,cantidad_disponible,cantidad_activa FROM lotes WHERE id=?",
                    (lote_v["id"],), one=True)
                lote_ids_afectados.add(lote_v["id"])
                detalle["lotes_mp"].append({
                    "lote_id": lote_v["id"], "lote_numero": lote_after["numero"],
                    "material": mat["descripcion"], "cantidad_devuelta": round(devolver, 3),
                    "estado_lote": lote_after["estado"],
                    "cantidad_disponible_actual": lote_after["cantidad_disponible"],
                    "cantidad_activa_actual": lote_after["cantidad_activa"]})
            devuelto_total = sum(d for _, d in plan)
            faltante = round(consumo - devuelto_total, 6)
            if faltante > 0.0001:
                # No se pudo repartir todo (cantidad_usada acumulada menor al
                # consumo de esta novedad, p.ej. por consumos de otras
                # novedades ya revertidos). Se devuelve el resto al lote más
                # reciente para no perder stock, mismo criterio que antes.
                lote_v = vinculos[-1]
                execute("""UPDATE lotes SET
                        cantidad_disponible=cantidad_disponible+?,
                        cantidad_activa=cantidad_activa+?,
                        cantidad_reservada=COALESCE(cantidad_reservada,0)+?,
                        estado=CASE WHEN estado='Agotado' AND cantidad_disponible+?>0 THEN 'Aprobado' ELSE estado END
                    WHERE id=?""", (faltante, faltante, faltante, faltante, lote_v["id"]))
                execute("""UPDATE materiales SET stock=stock+?, actualizado=datetime('now','localtime')
                    WHERE id=?""", (faltante, mat["material_id"]))
                execute("INSERT INTO movimientos (material_id,lote_id,tipo,cantidad,referencia,usuario_id) VALUES (?,?,?,?,?,?)",
                        (mat["material_id"], lote_v["id"], "entrada", faltante,
                         f"Reversa {nov['numero']} — resto devuelto a Lote {lote_v['numero']}", session["user_id"]))
                lote_after = query("SELECT numero,estado,cantidad_disponible,cantidad_activa FROM lotes WHERE id=?",
                    (lote_v["id"],), one=True)
                lote_ids_afectados.add(lote_v["id"])
                detalle["lotes_mp"].append({
                    "lote_id": lote_v["id"], "lote_numero": lote_after["numero"],
                    "material": mat["descripcion"], "cantidad_devuelta": round(faltante, 3),
                    "estado_lote": lote_after["estado"],
                    "cantidad_disponible_actual": lote_after["cantidad_disponible"],
                    "cantidad_activa_actual": lote_after["cantidad_activa"],
                    "nota": "resto (cantidad_usada acumulada insuficiente)"})

    # --- Revertir qty_producida en orden_operacion ---
    execute("UPDATE orden_operaciones SET qty_producida=MAX(0,qty_producida-?) WHERE id=?",
            (qty, nov["orden_operacion_id"]))
    consumir_herramientas_op(nov["orden_operacion_id"])

    # --- Si al eliminar la novedad la operación queda por debajo del 100%
    # y estaba marcada como Completada (automáticamente por haber llegado al
    # 100%), se revierte a "En proceso". ────────────────────────────────────
    oo_now = query("SELECT qty_requerida,qty_producida,estado FROM orden_operaciones WHERE id=?",
        (nov["orden_operacion_id"],), one=True)
    if oo_now and oo_now["estado"] == "Completada":
        qty_req_now = float(oo_now["qty_requerida"] or 0)
        qty_prod_now = float(oo_now["qty_producida"] or 0)
        if qty_req_now > 0 and qty_prod_now < qty_req_now - 0.0001:
            execute("UPDATE orden_operaciones SET estado='En proceso' WHERE id=?",
                (nov["orden_operacion_id"],))

    # --- Revertir stock PT si era ultima operacion ---
    max_ord = query("SELECT MAX(CAST(orden AS INTEGER)) mo FROM orden_operaciones WHERE orden_id=?",
                    (nov["orden_id"],), one=True)["mo"]
    if nov["orden"] == max_ord and nov["producto_id"]:
        prod = query("SELECT * FROM productos WHERE id=?", (nov["producto_id"],), one=True)
        if prod:
            # Tabla única: el stock del PT está en la misma fila del producto.
            mat_pt = query("SELECT id FROM materiales WHERE id=?", (prod["id"],), one=True)
            if mat_pt:
                execute("UPDATE materiales SET stock=MAX(0,stock-?),actualizado=datetime('now','localtime') WHERE id=?",
                        (qty, mat_pt["id"]))
                execute("INSERT INTO movimientos (material_id,tipo,cantidad,referencia,usuario_id) VALUES (?,?,?,?,?)",
                        (mat_pt["id"], "salida", qty,
                         f"Reversa PT {nov['numero']}", session["user_id"]))
                # Snapshot de los lotes de PT de esta OT (lote único o
                # "cajones" OT-C1, OT-C2...) para que el registro de
                # eliminación muestre en qué estado quedan — incluyendo si
                # ya fueron aprobados por Calidad (stock aprobado).
                lotes_ot = query("""SELECT id,numero,estado,cantidad_original,cantidad_disponible,cantidad_activa
                    FROM lotes WHERE material_id=? AND (numero=? OR numero LIKE ?)
                    ORDER BY numero""", (mat_pt["id"], nov["ot_numero"], nov["ot_numero"]+"-C%"))
                for l in lotes_ot:
                    # Un lote con cajones remite solo de cajones liberados, y
                    # esta novedad no puede tocar piezas liberadas (ver
                    # arriba): sus remitos no se tocan.
                    if query("SELECT 1 FROM cajones WHERE lote_id=? LIMIT 1", (l["id"],), one=True):
                        continue
                    lote_ids_afectados.add(l["id"])
                    pt_lote_ids.add(l["id"])
                detalle["pt"] = {
                    "material": prod["nombre"],
                    "cantidad_revertida_stock": qty,
                    "lotes_ot": [dict(l) for l in lotes_ot]}

    # --- Remitos que ya hayan entregado el PT de esta OT: al eliminar la
    # novedad se elimina también el ítem del remito (el material fabricado a
    # partir de esa novedad ya no existe). Si el remito queda sin ítems, se
    # anula (no se borra, para conservar el número/historial). ────────────────
    if pt_lote_ids:
        placeholders_pt = ",".join("?" * len(pt_lote_ids))
        remito_items_pt = query(f"""SELECT ri.id ri_id, ri.remito_id, ri.cantidad,
                ri.orden_cliente_item_id oci_id,
                r.numero remito_numero, r.estado,
                c.razon cliente_nombre, l.numero lote_numero, m.descripcion material
            FROM remito_items ri
            JOIN remitos r ON r.id=ri.remito_id
            JOIN lotes l ON l.id=ri.lote_id
            JOIN materiales m ON m.id=ri.material_id
            LEFT JOIN clientes c ON c.id=r.cliente_id
            WHERE ri.lote_id IN ({placeholders_pt}) AND r.estado!='Anulado'""", tuple(pt_lote_ids))
        remitos_afectados_ids = set()
        oci_afectados_ids = set()
        for ri in remito_items_pt:
            detalle["remitos"].append({
                "remito_numero": ri["remito_numero"], "fecha": None, "estado": ri["estado"],
                "cliente_nombre": ri["cliente_nombre"], "cantidad": ri["cantidad"],
                "lote_numero": ri["lote_numero"], "material": ri["material"],
                "accion": "Ítem eliminado del remito al eliminar la novedad"})
            if ri["oci_id"]:
                oci_afectados_ids.add(ri["oci_id"])
            execute("DELETE FROM remito_items WHERE id=?", (ri["ri_id"],))
            remitos_afectados_ids.add(ri["remito_id"])
        for rem_id in remitos_afectados_ids:
            quedan = query("SELECT COUNT(*) c FROM remito_items WHERE remito_id=?", (rem_id,), one=True)["c"]
            if quedan == 0:
                execute("UPDATE remitos SET estado='Anulado' WHERE id=?", (rem_id,))
        for oci_id in oci_afectados_ids:
            _sync_requerimiento_desde_pedido(oci_id)

    # --- Remitos que ya hayan usado stock de lotes de MATERIA PRIMA devueltos
    # (caso infrecuente: si se remitió materia prima como tal). Estos NO se
    # eliminan automáticamente, solo quedan informados en el registro. Los
    # remitos de PRODUCTO TERMINADO ya se eliminaron arriba. ─────────────────
    lote_ids_mp = lote_ids_afectados - pt_lote_ids
    if lote_ids_mp:
        placeholders = ",".join("?" * len(lote_ids_mp))
        remitos_rows = query(f"""SELECT r.numero remito_numero, r.fecha, r.estado,
                c.razon cliente_nombre, ri.cantidad, l.numero lote_numero, m.descripcion material
            FROM remito_items ri
            JOIN remitos r ON r.id=ri.remito_id
            JOIN lotes l ON l.id=ri.lote_id
            JOIN materiales m ON m.id=ri.material_id
            LEFT JOIN clientes c ON c.id=r.cliente_id
            WHERE ri.lote_id IN ({placeholders})
            ORDER BY r.fecha DESC""", tuple(lote_ids_mp))
        detalle["remitos"].extend(dict(r) for r in remitos_rows)

    # --- Guardar registro de auditoría antes de borrar la novedad ---
    quien_elimina = query("SELECT nombre FROM usuarios WHERE id=?", (session["user_id"],), one=True)
    execute("""INSERT INTO novedades_eliminadas
        (novedad_numero,orden_id,orden_numero,orden_operacion_id,operacion_nombre,
         producto_id,producto_nombre,empleado_id,empleado_nombre,maquina_id,maquina_nombre,
         cantidad_producida,piezas_observadas,tiempo_real_min,tiempo_perdido,turno,
         fecha_novedad,rendimiento_pct,obs,novedad_creado_por,novedad_creado_por_nombre,
         detalle_json,eliminado_por,eliminado_por_nombre)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (nov["numero"], nov["orden_id"], nov["ot_numero"], nov["orden_operacion_id"], nov["operacion_nombre"],
         nov["producto_id"], nov["producto_nombre"], nov["empleado_id"], nov["empleado_nombre"],
         nov["maquina_id"], nov["maquina_nombre"],
         nov["cantidad_producida"], nov["piezas_observadas"] if "piezas_observadas" in nov.keys() else 0,
         nov["tiempo_real_min"], nov["tiempo_perdido"] if "tiempo_perdido" in nov.keys() else 0, nov["turno"],
         nov["fecha"], nov["rendimiento_pct"], nov["obs"], nov["creado_por"], nov["creado_por_nombre"],
         json.dumps(detalle, ensure_ascii=False), session["user_id"],
         quien_elimina["nombre"] if quien_elimina else None))

    if filas_cajones:
        _guardar_novedad_cajones(nid, nov["orden_id"], [])
    execute("DELETE FROM novedades_produccion WHERE id=?", (nid,))
    return jsonify({"ok": True})


# ── Registro de novedades eliminadas (auditoría) ────────────────────────────
@app.route("/api/novedades-eliminadas", methods=["GET"])
@login_required(roles=["admin","operario"])
def get_novedades_eliminadas():
    import json
    q = (request.args.get("q") or "").strip().lower()
    desde = request.args.get("desde")
    hasta = request.args.get("hasta")
    sql = "SELECT * FROM novedades_eliminadas WHERE 1=1"
    params = []
    if desde: sql += " AND date(eliminado)>=?"; params.append(desde)
    if hasta: sql += " AND date(eliminado)<=?"; params.append(hasta)
    sql += " ORDER BY id DESC LIMIT 500"
    rows = query(sql, tuple(params)) if params else query(sql)
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["detalle"] = json.loads(d.pop("detalle_json") or "{}")
        except Exception:
            d["detalle"] = {}
            d.pop("detalle_json", None)
        out.append(d)
    if q:
        out = [d for d in out if q in (d.get("novedad_numero") or "").lower()
               or q in (d.get("orden_numero") or "").lower()
               or q in (d.get("operacion_nombre") or "").lower()
               or q in (d.get("empleado_nombre") or "").lower()
               or q in (d.get("producto_nombre") or "").lower()]
    return jsonify(out)


@app.route("/api/novedades-eliminadas/<int:eid>/restaurar", methods=["POST"])
@login_required(roles=["admin","operario"])
def restaurar_novedad_eliminada(eid):
    """Deshace una eliminación de novedad: vuelve a crear la novedad con sus
    datos originales y rehace, en sentido inverso, todo lo que
    delete_novedad() había revertido (según el detalle_json guardado):
    re-consume la materia prima de los mismos lotes, repone el stock de
    producto terminado y recrea los ítems de remito que se habían borrado
    (reabriendo el remito si había quedado anulado por eso). Si algo de lo
    referenciado (lote, remito, material) ya no existe o cambió de forma
    incompatible, se avisa mediante "warnings" en la respuesta pero no se
    interrumpe el resto de la restauración."""
    import json
    reg = query("SELECT * FROM novedades_eliminadas WHERE id=?", (eid,), one=True)
    if not reg: return jsonify({"error":"Registro no encontrado"}), 404
    if reg["restaurado"]:
        return jsonify({"error":"Esta novedad ya fue restaurada el "+reg["restaurado"]}), 400

    ya_existe = query("SELECT id FROM novedades_produccion WHERE numero=?", (reg["novedad_numero"],), one=True)
    if ya_existe:
        return jsonify({"error":"Ya existe una novedad con el número "+reg["novedad_numero"]+", no se puede restaurar"}), 400

    oo = query("SELECT * FROM orden_operaciones WHERE id=?", (reg["orden_operacion_id"],), one=True)
    if not oo:
        return jsonify({"error":"La operación de esa orden ya no existe, no se puede restaurar"}), 400
    orden = query("SELECT * FROM ordenes WHERE id=?", (reg["orden_id"],), one=True)
    if not orden:
        return jsonify({"error":"La orden de trabajo ya no existe, no se puede restaurar"}), 400

    try:
        detalle = json.loads(reg["detalle_json"] or "{}")
    except Exception:
        detalle = {}

    warnings = []
    qty = float(reg["cantidad_producida"] or 0)

    # --- Volver a crear la novedad con sus datos originales ---
    nid_rest = execute("""INSERT INTO novedades_produccion
        (numero,orden_id,orden_operacion_id,empleado_id,maquina_id,cantidad_producida,tiempo_real_min,
         piezas_observadas,tiempo_perdido,turno,fecha,rendimiento_pct,desvio,obs,creado_por)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (reg["novedad_numero"], reg["orden_id"], reg["orden_operacion_id"], reg["empleado_id"], reg["maquina_id"],
         qty, reg["tiempo_real_min"], reg["piezas_observadas"] or 0, reg["tiempo_perdido"] or 0, reg["turno"],
         reg["fecha_novedad"], reg["rendimiento_pct"], 1 if (reg["rendimiento_pct"] or 0) < 80 else 0,
         reg["obs"], reg["novedad_creado_por"]))

    # --- Rehacer qty_producida y estado de la operación / OT (mismo criterio que create_novedad) ---
    qty_req_op = float(oo["qty_requerida"] or 0)
    qty_prod_antes = float(oo["qty_producida"] or 0)
    execute("UPDATE orden_operaciones SET qty_producida=qty_producida+? WHERE id=?", (qty, reg["orden_operacion_id"]))
    consumir_herramientas_op(reg["orden_operacion_id"])

    # --- Volver a imputar a cajones, con las mismas reglas que una novedad nueva ---
    if qty > 0 and _ot_tiene_cajones(reg["orden_id"]):
        pasos_ot = _pasos_ot(reg["orden_id"])
        paso_op = query("SELECT CAST(orden AS INTEGER) p FROM orden_operaciones WHERE id=?",
            (reg["orden_operacion_id"],), one=True)["p"]
        if paso_op == pasos_ot[0]:
            _guardar_novedad_cajones(nid_rest, reg["orden_id"], [], extra=qty)
        else:
            plan_c, err = _plan_cajones_paso(reg["orden_id"], paso_op, qty, detalle.get("cajones"),
                sin_novedad=nid_rest)
            if err:
                plan_c, _ = _plan_cajones_paso(reg["orden_id"], paso_op, qty, sin_novedad=nid_rest, parcial=True)
                warnings.append("No se pudieron usar los mismos cajones que tenía (" + err
                                + "): se imputó en orden a los cajones con piezas disponibles")
            _guardar_novedad_cajones(nid_rest, reg["orden_id"], plan_c)
        _cajones_vincular_lote(reg["orden_id"])
    execute("UPDATE ordenes SET estado='En proceso' WHERE id=? AND estado='Pendiente'", (reg["orden_id"],))
    ya_estaba_al_100 = qty_req_op > 0 and qty_prod_antes >= qty_req_op - 0.0001
    if oo["estado"] != "Completada" and not ya_estaba_al_100:
        _sincronizar_estado_paso(reg["orden_operacion_id"])

    # --- Re-consumir la materia prima de los mismos lotes que se habían devuelto ---
    for l in detalle.get("lotes_mp") or []:
        lote_id = l.get("lote_id")
        consumo = float(l.get("cantidad_devuelta") or 0)
        if not lote_id or consumo <= 0: continue
        lote = query("SELECT * FROM lotes WHERE id=?", (lote_id,), one=True)
        if not lote:
            warnings.append("El lote "+str(l.get("lote_numero") or lote_id)+" ya no existe: no se pudo re-consumir "+str(consumo))
            continue
        execute("""UPDATE lotes SET
                cantidad_disponible=MAX(0,cantidad_disponible-?),
                cantidad_activa=MAX(0,cantidad_activa-?),
                cantidad_reservada=MAX(0,COALESCE(cantidad_reservada,0)-?),
                estado=CASE WHEN cantidad_disponible-?<=0 THEN 'Agotado' ELSE estado END
            WHERE id=?""", (consumo, consumo, consumo, consumo, lote_id))
        execute("""UPDATE materiales SET stock=MAX(0,stock-?), actualizado=datetime('now','localtime')
            WHERE id=?""", (consumo, lote["material_id"]))
        # cantidad_usada / cantidad_asignada NO se tocan: la reserva de este
        # lote para esta OT ya estaba comprometida antes de la novedad
        # original (se había restaurado cantidad_reservada al eliminarla).
        # Re-consumir solo vuelve a convertir esa reserva en consumo real.
        existing_ol = query("SELECT id FROM orden_lotes WHERE orden_id=? AND lote_id=?", (reg["orden_id"], lote_id), one=True)
        if existing_ol:
            execute("""UPDATE orden_lotes SET cantidad_consumida=COALESCE(cantidad_consumida,0)+?
                WHERE orden_id=? AND lote_id=?""", (consumo, reg["orden_id"], lote_id))
        else:
            # No debería pasar en circunstancias normales (el vínculo se
            # crea al asignar el lote), pero por las dudas se preserva como
            # red de seguridad si el vínculo ya no existiera.
            execute("""INSERT INTO orden_lotes (orden_id,lote_id,material_id,cantidad_usada,cantidad_consumida)
                VALUES (?,?,?,?,?)""", (reg["orden_id"], lote_id, lote["material_id"], consumo, consumo))
            execute("""UPDATE orden_materiales SET cantidad_asignada=cantidad_asignada+?
                WHERE orden_id=? AND material_id=?""", (consumo, reg["orden_id"], lote["material_id"]))
        execute("INSERT INTO movimientos (material_id,lote_id,tipo,cantidad,referencia,usuario_id) VALUES (?,?,?,?,?,?)",
            (lote["material_id"], lote_id, "salida", consumo,
             f"Restauración {reg['novedad_numero']} — re-consume Lote {lote['numero']}", session["user_id"]))

    # --- Reponer el stock de producto terminado revertido ---
    pt = detalle.get("pt")
    if pt:
        prod = query("SELECT * FROM productos WHERE id=?", (reg["producto_id"],), one=True) if reg["producto_id"] else None
        # Tabla única: el stock del PT está en la misma fila del producto.
        mat_pt = query("SELECT id FROM materiales WHERE id=?", (prod["id"],), one=True) if prod else None
        if mat_pt:
            qty_pt = float(pt.get("cantidad_revertida_stock") or 0)
            execute("UPDATE materiales SET stock=stock+?, actualizado=datetime('now','localtime') WHERE id=?",
                    (qty_pt, mat_pt["id"]))
            execute("INSERT INTO movimientos (material_id,tipo,cantidad,referencia,usuario_id) VALUES (?,?,?,?,?)",
                    (mat_pt["id"], "entrada", qty_pt, f"Restauración PT {reg['novedad_numero']}", session["user_id"]))
        else:
            warnings.append("No se encontró el material de producto terminado: no se pudo reponer el stock de PT")

    # --- Recrear ítems de remito que se habían eliminado, y reabrir el remito si quedó anulado ---
    for r in detalle.get("remitos") or []:
        if not r.get("accion"): continue  # remitos de MP: solo informativos, no se tocaron al eliminar
        remito = query("SELECT * FROM remitos WHERE numero=?", (r.get("remito_numero"),), one=True)
        lote_r = query("SELECT * FROM lotes WHERE numero=?", (r.get("lote_numero"),), one=True)
        if not remito or not lote_r:
            warnings.append("No se pudo recrear el ítem del remito "+str(r.get("remito_numero") or "—")+" (remito o lote ya no existen)")
            continue
        execute("""INSERT INTO remito_items (remito_id,material_id,lote_id,cantidad,obs)
            VALUES (?,?,?,?,?)""",
            (remito["id"], lote_r["material_id"], lote_r["id"], r.get("cantidad") or 0,
             "Restaurado automáticamente al restaurar novedad "+reg["novedad_numero"]))
        if remito["estado"] == "Anulado":
            nuevo_estado = r.get("estado") or "Emitido"
            execute("UPDATE remitos SET estado=? WHERE id=?", (nuevo_estado, remito["id"]))

    # --- Marcar el registro de auditoría como restaurado (se conserva el historial) ---
    quien = query("SELECT nombre FROM usuarios WHERE id=?", (session["user_id"],), one=True)
    execute("""UPDATE novedades_eliminadas SET restaurado=datetime('now','localtime'),
            restaurado_por=?, restaurado_por_nombre=? WHERE id=?""",
        (session["user_id"], quien["nombre"] if quien else None, eid))

    return jsonify({"ok": True, "numero": reg["novedad_numero"], "warnings": warnings})


# ── Trabajo no productivo ──────────────────────────────────────────────────────
@app.route("/api/trabajo-no-productivo", methods=["GET"])
@login_required()
def get_trabajo_no_productivo():
    emp_id = request.args.get("emp_id")
    desde = request.args.get("desde")
    hasta = request.args.get("hasta")
    sql = """SELECT t.*, e.nombre||' '||e.apellido empleado_nombre
        FROM trabajo_no_productivo t
        LEFT JOIN empleados e ON e.id=t.empleado_id
        WHERE 1=1"""
    params = []
    if emp_id:
        sql += " AND t.empleado_id=?"
        params.append(emp_id)
    if desde:
        sql += " AND date(t.fecha)>=?"
        params.append(desde)
    if hasta:
        sql += " AND date(t.fecha)<=?"
        params.append(hasta)
    sql += " ORDER BY t.fecha DESC, t.id DESC"
    if not emp_id:
        sql += " LIMIT 200"
    rows = query(sql, tuple(params))
    return jsonify([dict(r) for r in rows])

@app.route("/api/trabajo-no-productivo", methods=["POST"])
@login_required(roles=["admin","operario"])
def create_trabajo_no_productivo():
    d = request.json
    desc = (d.get("descripcion") or "").strip()
    tmin = float(d.get("tiempo_min") or 0)
    fecha = (d.get("fecha") or "").strip()
    if not desc: return jsonify({"error":"Descripción requerida"}), 400
    if tmin <= 0: return jsonify({"error":"El tiempo debe ser mayor a 0"}), 400

    numero = siguiente_numero("trabajo_no_productivo", "TNP-", 5)

    if fecha:
        lid = execute("""INSERT INTO trabajo_no_productivo
            (numero,empleado_id,descripcion,tiempo_min,fecha,creado_por)
            VALUES (?,?,?,?,?,?)""",
            (numero, d.get("empleado_id") or None, desc, tmin, fecha, session["user_id"]))
    else:
        lid = execute("""INSERT INTO trabajo_no_productivo
            (numero,empleado_id,descripcion,tiempo_min,creado_por)
            VALUES (?,?,?,?,?)""",
            (numero, d.get("empleado_id") or None, desc, tmin, session["user_id"]))
    return jsonify({"ok":True,"id":lid,"numero":numero}), 201

@app.route("/api/trabajo-no-productivo/<int:tid>", methods=["PUT"])
@login_required(roles=["admin","operario"])
def update_trabajo_no_productivo(tid):
    row = query("SELECT id FROM trabajo_no_productivo WHERE id=?", (tid,), one=True)
    if not row: return jsonify({"error":"Registro no encontrado"}), 404
    d = request.json
    desc = (d.get("descripcion") or "").strip()
    tmin = float(d.get("tiempo_min") or 0)
    fecha = (d.get("fecha") or "").strip()
    if not desc: return jsonify({"error":"Descripción requerida"}), 400
    if tmin <= 0: return jsonify({"error":"El tiempo debe ser mayor a 0"}), 400
    if fecha:
        execute("""UPDATE trabajo_no_productivo SET descripcion=?,tiempo_min=?,empleado_id=?,fecha=? WHERE id=?""",
            (desc, tmin, d.get("empleado_id") or None, fecha, tid))
    else:
        execute("""UPDATE trabajo_no_productivo SET descripcion=?,tiempo_min=?,empleado_id=? WHERE id=?""",
            (desc, tmin, d.get("empleado_id") or None, tid))
    return jsonify({"ok": True})

@app.route("/api/trabajo-no-productivo/<int:tid>", methods=["DELETE"])
@login_required(roles=["admin","operario"])
def delete_trabajo_no_productivo(tid):
    row = query("SELECT id FROM trabajo_no_productivo WHERE id=?", (tid,), one=True)
    if not row: return jsonify({"error":"Registro no encontrado"}), 404
    execute("DELETE FROM trabajo_no_productivo WHERE id=?", (tid,))
    return jsonify({"ok": True})



@app.route("/api/rendimiento_operario", methods=["GET"])
@login_required()
def get_rendimiento_operario():
    """Rendimiento ponderado por operario, agrupado por año/mes/día."""
    rows = query("""SELECT
        e.id emp_id, e.nombre||' '||e.apellido empleado_nombre,
        strftime('%Y', n.fecha) anio,
        strftime('%Y-%m', n.fecha) mes,
        strftime('%Y-%m-%d', n.fecha) dia,
        COUNT(*) novedades,
        AVG(n.rendimiento_pct) rend_promedio,
        SUM(n.cantidad_producida) total_producido,
        SUM(n.tiempo_real_min) total_min_real
        FROM novedades_produccion n
        JOIN empleados e ON e.id=n.empleado_id
        WHERE n.empleado_id IS NOT NULL
        GROUP BY e.id, strftime('%Y-%m-%d', n.fecha)
        ORDER BY e.apellido, e.nombre, n.fecha DESC""")
    # Group by empleado → año → mes → dia
    result = {}
    for r in rows:
        eid = r["emp_id"]
        if eid not in result:
            result[eid] = {"emp_id": eid, "nombre": r["empleado_nombre"],
                           "años": {}}
        años = result[eid]["años"]
        a = r["anio"]
        if a not in años:
            años[a] = {"año": a, "meses": {}, "total_novedades": 0,
                       "rend_sum": 0.0, "rend_count": 0}
        m = r["mes"]
        if m not in años[a]["meses"]:
            años[a]["meses"][m] = {"mes": m, "dias": [], "total_novedades": 0,
                                   "rend_sum": 0.0, "rend_count": 0}
        años[a]["meses"][m]["dias"].append({
            "dia": r["dia"],
            "novedades": r["novedades"],
            "rend_promedio": round(float(r["rend_promedio"] or 0), 1),
            "total_producido": r["total_producido"],
            "total_min_real": r["total_min_real"],
        })
        años[a]["meses"][m]["total_novedades"] += r["novedades"]
        años[a]["meses"][m]["rend_sum"] += float(r["rend_promedio"] or 0)
        años[a]["meses"][m]["rend_count"] += 1
        años[a]["total_novedades"] += r["novedades"]
        años[a]["rend_sum"] += float(r["rend_promedio"] or 0)
        años[a]["rend_count"] += 1
    # Flatten for JSON
    out = []
    for eid, emp in result.items():
        emp_row = {"emp_id": eid, "nombre": emp["nombre"], "años": []}
        for a, año_data in sorted(emp["años"].items(), reverse=True):
            rc = año_data["rend_count"]
            año_row = {
                "año": a,
                "rend_promedio": round(año_data["rend_sum"]/rc, 1) if rc else 0,
                "total_novedades": año_data["total_novedades"],
                "meses": []
            }
            for m, mes_data in sorted(año_data["meses"].items(), reverse=True):
                mc = mes_data["rend_count"]
                año_row["meses"].append({
                    "mes": m,
                    "rend_promedio": round(mes_data["rend_sum"]/mc, 1) if mc else 0,
                    "total_novedades": mes_data["total_novedades"],
                    "dias": mes_data["dias"]
                })
            emp_row["años"].append(año_row)
        out.append(emp_row)
    return jsonify(out)


@app.route("/api/rendimiento_operario_dias", methods=["GET"])
@login_required()
def get_rendimiento_operario_dias():
    """Rendimiento diario de un operario filtrado por rango de fechas."""
    emp_id = request.args.get("emp_id")
    desde = request.args.get("desde")
    hasta = request.args.get("hasta")
    if not emp_id:
        return jsonify({"error": "emp_id requerido"}), 400
    sql = """SELECT
        strftime('%Y-%m-%d', n.fecha) dia,
        COUNT(*) novedades,
        AVG(n.rendimiento_pct) rend_promedio,
        SUM(n.cantidad_producida) total_producido_bruto,
        SUM(COALESCE(n.piezas_observadas,0)) total_no_ok,
        SUM(n.tiempo_real_min) total_min_real,
        SUM(COALESCE(n.tiempo_perdido,0)) total_tiempo_perdido
        FROM novedades_produccion n
        WHERE n.empleado_id=?"""
    params = [emp_id]
    if desde:
        sql += " AND date(n.fecha)>=?"
        params.append(desde)
    if hasta:
        sql += " AND date(n.fecha)<=?"
        params.append(hasta)
    sql += " GROUP BY strftime('%Y-%m-%d', n.fecha) ORDER BY dia DESC"
    rows = query(sql, tuple(params))
    out = [{
        "dia": r["dia"],
        "novedades": r["novedades"],
        "rend_promedio": round(float(r["rend_promedio"] or 0), 1),
        "total_producido": r["total_producido_bruto"] or 0,
        "total_no_ok": r["total_no_ok"] or 0,
        "total_min_real": r["total_min_real"],
        "total_tiempo_perdido": r["total_tiempo_perdido"],
    } for r in rows]
    return jsonify(out)


# Funciones de otras áreas. Van al final a propósito: así cada módulo ya
# definió todo lo suyo cuando otro lo importa, y no hay problemas de
# importación circular. Se usan recién al atender pedidos.
from .comun import (_lotes_vinculados_material, _materiales_ott_pendientes_por_operacion,
    _plan_consumo_adicional, _plan_devolucion, _sincronizar_estado_paso,
    consumir_herramientas_op)
from .requerimientos import _sync_requerimiento_desde_pedido
from .ordenes import generar_pt_faltante_si_corresponde
from .cajones import (_cajones_vincular_lote, _guardar_novedad_cajones, _ot_tiene_cajones,
    _ot_usa_cajones, _pasos_ot, _plan_cajones_paso, _replan_novedad_cajones)
from .compras import auto_generar_sc_bajo_stock

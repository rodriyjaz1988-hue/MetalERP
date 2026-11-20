"""Productos, categorías de producto, operaciones del proceso, herramientas,
tiempos y costos, versiones y archivos de producto."""
from .nucleo import (_mon_o_actual, app, BASE_DIR, execute, get_config_valor, get_db,
    jsonify, login_required, query, request, session)

def _snapshot_producto(prod_id):
    """Genera un snapshot JSON del producto y sus operaciones/materiales actuales."""
    import json
    db = get_db()
    prod = db.execute("SELECT * FROM productos WHERE id=?", (prod_id,)).fetchone()
    if not prod:
        return None
    ops = db.execute(
        "SELECT * FROM proceso_operaciones WHERE producto_id=? ORDER BY CAST(orden AS INTEGER), orden", (prod_id,)
    ).fetchall()
    ops_list = []
    for op in ops:
        op_d = dict(op)
        if op_d.get("categoria_maquina_id"):
            cm = db.execute("SELECT nombre FROM categorias_maquina WHERE id=?", (op_d["categoria_maquina_id"],)).fetchone()
            op_d["cat_maq_nombre"] = cm["nombre"] if cm else None
        mats = db.execute(
            """SELECT om.*,m.codigo mat_codigo,m.descripcion mat_descripcion,m.unidad mat_unidad
               FROM operacion_materiales om
               LEFT JOIN materiales m ON m.id=om.material_id
               WHERE om.operacion_id=?""", (op["id"],)
        ).fetchall()
        op_d["materiales"] = [dict(m) for m in mats]
        ops_list.append(op_d)
    snap = {"producto": dict(prod), "operaciones": ops_list}
    return json.dumps(snap, ensure_ascii=False)

def guardar_version_producto(prod_id, motivo=None, creado_por=None):
    """Guarda una versión/snapshot del proceso actual antes de modificarlo."""
    snap = _snapshot_producto(prod_id)
    if not snap:
        return
    # Obtener número de versión correlativo
    last = query(
        "SELECT COALESCE(MAX(version_num),0) n FROM producto_versiones WHERE producto_id=?",
        (prod_id,), one=True
    )
    next_num = (last["n"] if last else 0) + 1
    execute(
        "INSERT INTO producto_versiones (producto_id,version_num,motivo,snapshot,creado_por) VALUES (?,?,?,?,?)",
        (prod_id, next_num, motivo, snap, creado_por)
    )

# ── Categorias ────────────────────────────────────────────────────────────────
@app.route("/api/categorias_producto", methods=["GET"])
@login_required()
def get_cat_prod(): return jsonify([dict(r) for r in query("SELECT * FROM categorias_producto ORDER BY nombre")])

@app.route("/api/categorias_producto", methods=["POST"])
@login_required(roles=["admin"])
def create_cat_prod():
    d = request.json
    if not d.get("nombre"): return jsonify({"error":"Nombre requerido"}), 400
    lid = execute("INSERT INTO categorias_producto (nombre,descripcion) VALUES (?,?)", (d["nombre"],d.get("descripcion")))
    return jsonify({"ok":True,"id":lid}), 201

@app.route("/api/categorias_producto/<int:cid>", methods=["PUT"])
@login_required(roles=["admin"])
def update_cat_prod(cid):
    d = request.json
    execute("UPDATE categorias_producto SET nombre=?,descripcion=? WHERE id=?",
            (d["nombre"], d.get("descripcion"), cid))
    return jsonify({"ok": True})

@app.route("/api/categorias_producto/<int:cid>", methods=["DELETE"])
@login_required(roles=["admin"])
def delete_cat_prod(cid):
    # Check if in use
    used = query("SELECT COUNT(*) c FROM productos WHERE categoria_id=?", (cid,), one=True)["c"]
    if used:
        return jsonify({"error": f"En uso por {used} producto(s)"}), 400
    execute("DELETE FROM categorias_producto WHERE id=?", (cid,))
    return jsonify({"ok": True})

# ── Productos / Procesos ──────────────────────────────────────────────────────
@app.route("/api/productos", methods=["GET"])
@login_required()
def get_productos():
    cliente_id = request.args.get("cliente_id")
    # `productos` es una vista sobre la tabla única de artículos (materiales):
    # acá se listan los que se fabrican, es decir los de tipo "Producto
    # terminado" y cualquier otro artículo que ya tenga un proceso cargado
    # (por si se le cambió el tipo después de definirle el proceso).
    filtro_fabricables = """(p.tipo_articulo='Producto terminado'
        OR EXISTS (SELECT 1 FROM proceso_operaciones po WHERE po.producto_id=p.id))"""
    if cliente_id:
        rows = query(f"""SELECT p.*,c.nombre categoria_nombre,cl.razon cliente_nombre FROM productos p
            LEFT JOIN categorias_producto c ON c.id=p.categoria_id
            LEFT JOIN clientes cl ON cl.id=p.cliente_id
            WHERE p.cliente_id=? AND p.activo=1 AND {filtro_fabricables} ORDER BY p.codigo""", (cliente_id,))
    else:
        rows = query(f"""SELECT p.*,c.nombre categoria_nombre,cl.razon cliente_nombre FROM productos p
            LEFT JOIN categorias_producto c ON c.id=p.categoria_id
            LEFT JOIN clientes cl ON cl.id=p.cliente_id
            WHERE p.activo=1 AND {filtro_fabricables} ORDER BY p.codigo""")
    result = []
    try:
        valor_hora_mo = float(get_config_valor("valor_hora_mo", "0") or 0)
    except (TypeError, ValueError):
        valor_hora_mo = 0
    for r in rows:
        d = dict(r)
        # Calculate costo_mat dynamically from current material prices
        d["costo_mat"] = round(calcular_costo_producto(d["id"], 1.0), 2)
        # El ciclo se carga por operación en SEGUNDOS, pero el total acumulado
        # del producto se expone en MINUTOS: es la escala en la que se lee en
        # la tabla de Procesos/Productos (35 min, no 2100 seg).
        _ciclo_total_seg = calcular_tiempo_ciclo_total_seg(d["id"])
        d["tiempo_ciclo_total_min"] = round(_ciclo_total_seg / 60.0, 2)
        d["rendimiento_ponderado"] = calcular_rendimiento_ponderado_producto(d["id"])
        d["costo_terc"] = round(calcular_costo_terciarizado_producto(d["id"]), 2)
        # Costo de mano de obra: el tiempo de ciclo total está en SEGUNDOS y el
        # valor hora se configura por hora, así que se divide por 3600.
        d["costo_mo"] = round(_ciclo_total_seg / 3600.0 * valor_hora_mo, 2)
        d["costo_total"] = round((d["costo_mat"] or 0) + (d["costo_mo"] or 0) + (d["costo_terc"] or 0), 2)
        if cliente_id:
            # v147 (punto 5): precio del ítem en la OC de cliente más reciente
            oc_r = query("""SELECT oci.precio_unit, oc.numero, oc.fecha
                FROM ordenes_cliente_items oci JOIN ordenes_cliente oc ON oc.id=oci.orden_cliente_id
                WHERE oci.producto_id=? AND oc.cliente_id=?
                ORDER BY oc.fecha DESC, oc.id DESC LIMIT 1""", (d["id"], cliente_id), one=True)
            d["oc_precio_reciente"] = oc_r["precio_unit"] if oc_r else None
            d["oc_numero_reciente"] = oc_r["numero"] if oc_r else None
            d["oc_fecha_reciente"] = oc_r["fecha"] if oc_r else None
        result.append(d)
    return jsonify(result)

def calcular_costo_terciarizado_producto(producto_id):
    """Costo terciarizado de un producto: suma del precio por unidad
    (precio_tercerizado) de todas sus operaciones marcadas como
    tercerizadas (es_tercerizada=1) en la plantilla de proceso del
    producto. Es el costo, por unidad de producto, de mandar a hacer
    afuera esas operaciones (no incluye materiales de las operaciones
    propias, eso ya lo cubre costo_mat)."""
    row = query("""
        SELECT COALESCE(SUM(precio_tercerizado),0) total
        FROM proceso_operaciones
        WHERE producto_id=? AND es_tercerizada=1
    """, (producto_id,), one=True)
    return float(row["total"] or 0)

def calcular_rendimiento_ponderado_producto(producto_id):
    """Rendimiento ponderado por tiempo real, sobre todas las Novedades
    históricas (de todas las OTs) del producto:
        Σ(tiempo_real_i * rend_i) / Σ(tiempo_real_i)
    El rendimiento de cada novedad se recalcula en vivo a partir de sus
    datos crudos (cantidad, tiempo real, ciclo estándar) con la misma
    fórmula que usa la creación de novedades, en lugar de confiar en el
    campo rendimiento_pct ya guardado — así no se ve afectado por
    novedades cuyo rendimiento_pct haya quedado en 0 (default) por no
    haber sido recalculado."""
    rows = query("""
        SELECT n.cantidad_producida qty, n.tiempo_real_min t_real,
               COALESCE(n.tiempo_perdido,0) t_perd,
               COALESCE(NULLIF(po.tiempo_ciclo_seg,0), NULLIF(oo.tiempo_ciclo_seg,0), 60) ciclo
        FROM novedades_produccion n
        JOIN orden_operaciones oo ON oo.id = n.orden_operacion_id
        JOIN ordenes o ON o.id = oo.orden_id
        LEFT JOIN proceso_operaciones po ON po.id = oo.proceso_op_id
        WHERE o.producto_id = ? AND n.tiempo_real_min > 0
    """, (producto_id,))
    if not rows:
        return None
    num = 0.0
    den = 0.0
    for r in rows:
        # ciclo viene en segundos; tiempo_real_min en minutos.
        ciclo = float(r["ciclo"] or 60) / 60.0
        qty = float(r["qty"] or 0)
        t_real = float(r["t_real"] or 0)
        t_perd = float(r["t_perd"] or 0)
        if qty <= 0 or ciclo <= 0 or t_real <= 0:
            continue
        # Misma fórmula que usa el recálculo real de novedades (init_db) y
        # la creación de novedades: el tiempo productivo descuenta el
        # tiempo perdido declarado, no el tiempo real bruto. Antes esta
        # función no restaba tiempo_perdido, lo que subestimaba el
        # rendimiento (y en varios casos lo dejaba en ~0%).
        t_productivo = max(t_real - t_perd, 0.1)
        rend = round((qty / t_productivo) / (1 / ciclo) * 100, 1)
        rend = min(rend, 999)
        num += t_real * rend
        den += t_real
    if den <= 0:
        return None
    return round(num / den, 2)

@app.route("/api/productos/<int:pid>", methods=["GET"])
@login_required()
def get_producto(pid):
    prod = query("SELECT p.*,COALESCE(p.peso_kg,0) peso_kg,c.nombre categoria_nombre FROM productos p LEFT JOIN categorias_producto c ON c.id=p.categoria_id WHERE p.id=?", (pid,), one=True)
    if not prod: return jsonify({"error":"No encontrado"}), 404
    d = dict(prod)
    d["tiempo_ciclo_total_min"] = round(calcular_tiempo_ciclo_total_seg(pid) / 60.0, 2)
    ops = query("SELECT op.*,cm.nombre cat_maq_nombre,m.nombre maquina_nombre FROM proceso_operaciones op LEFT JOIN categorias_maquina cm ON cm.id=op.categoria_maquina_id LEFT JOIN maquinas m ON m.id=op.maquina_id WHERE op.producto_id=? ORDER BY CAST(op.orden AS INTEGER), op.orden", (pid,))
    d["operaciones"] = []
    for op in ops:
        od = dict(op)
        mats_raw = query("""SELECT om.*,
            m.codigo mat_codigo, m.descripcion mat_descripcion, m.unidad mat_unidad,
            p.codigo prod_codigo, p.nombre prod_nombre, p.unidad prod_unidad
            FROM operacion_materiales om
            LEFT JOIN materiales m ON m.id=om.material_id
            LEFT JOIN productos p ON p.id=om.producto_id
            WHERE om.operacion_id=?""", (op["id"],))
        od["materiales"] = []
        od["productos_insumo"] = []
        for x in mats_raw:
            mx = dict(x)
            if mx.get("tipo") == "producto":
                mx["codigo"] = mx.get("prod_codigo",""); mx["descripcion"] = mx.get("prod_nombre",""); mx["unidad"] = mx.get("prod_unidad","")
                od["productos_insumo"].append(mx)
            else:
                mx["codigo"] = mx.get("mat_codigo",""); mx["descripcion"] = mx.get("mat_descripcion",""); mx["unidad"] = mx.get("mat_unidad","")
                od["materiales"].append(mx)
        d["operaciones"].append(od)
    return jsonify(d)

def _codigo_en_uso(codigo, excluir_id=None):
    """Busca el código en la tabla ÚNICA de artículos (productos terminados,
    materiales, insumos, herramientas y semielaborados comparten el mismo
    espacio de códigos). Devuelve la fila que lo usa o None."""
    if excluir_id:
        return query("SELECT id,codigo,categoria FROM materiales WHERE codigo=? AND id!=?",
                     (codigo, excluir_id), one=True)
    return query("SELECT id,codigo,categoria FROM materiales WHERE codigo=?", (codigo,), one=True)

def _msg_codigo_en_uso(row):
    return f"El código '{row['codigo']}' ya está en uso por otro artículo ({row['categoria'] or 'Material'})"

def _piezas_por_cajon(valor):
    """"Piezas por cajón" (capacidad_cajon) es obligatorio: entero >= 1.
    Devuelve (valor, error)."""
    try:
        v = float(valor)
    except (TypeError, ValueError):
        return None, "Piezas por cajón es obligatorio (número entero mayor a 0)"
    if v < 1 or v != int(v):
        return None, "Piezas por cajón tiene que ser un número entero mayor a 0"
    return int(v), None

@app.route("/api/productos", methods=["POST"])
@login_required(roles=["admin","operario"])
def create_producto():
    d = request.json
    if not d.get("codigo") or not d.get("nombre"): return jsonify({"error":"Código y nombre requeridos"}), 400
    cap_cajon, err = _piezas_por_cajon(d.get("capacidad_cajon"))
    if err: return jsonify({"error": err}), 400
    dup = _codigo_en_uso(d["codigo"])
    if dup: return jsonify({"error": _msg_codigo_en_uso(dup)}), 409
    # El producto es un artículo más de la tabla única (materiales), de tipo
    # "Producto terminado": la misma fila lleva su proceso, stock y lotes.
    # (El trigger trg_materiales_pt_alta completa producto_id = id.)
    cb = (d.get("codigo_barras") or "").strip() or None
    lid = execute("""INSERT INTO materiales
        (codigo,descripcion,descripcion_larga,categoria,categoria_producto_id,unidad,
         tiempo_total_hs,costo_mat,costo_mo,precio_venta,peso_kg,cliente_id,obs,
         capacidad_cajon,codigo_barras,stock,stock_min,activo)
        VALUES (?,?,?,'Producto terminado',?,?,?,?,?,?,?,?,?,?,?,0,0,1)""",
        (d["codigo"],d["nombre"],d.get("descripcion"),d.get("categoria_id") or None,d.get("unidad","unid"),
         d.get("tiempo_total_hs",0),d.get("costo_mat",0),d.get("costo_mo",0),d.get("precio_venta",0),
         d.get("peso_kg",0),d.get("cliente_id") or None,d.get("obs"),cap_cajon,cb))
    return jsonify({"ok":True,"id":lid}), 201


@app.route("/api/productos/<int:pid>/copiar", methods=["POST"])
@login_required(roles=["admin","operario"])
def copiar_producto(pid):
    """Copia un producto con sus operaciones y materiales, usando un nuevo código."""
    d = request.json
    nuevo_codigo = (d.get("codigo") or "").strip()
    nuevo_nombre = (d.get("nombre") or "").strip()
    if not nuevo_codigo:
        return jsonify({"error": "Código requerido"}), 400
    dup = _codigo_en_uso(nuevo_codigo)
    if dup:
        return jsonify({"error": _msg_codigo_en_uso(dup)}), 409

    # Fetch original
    orig = query("SELECT * FROM productos WHERE id=?", (pid,), one=True)
    if not orig:
        return jsonify({"error": "Producto original no encontrado"}), 404

    orig_ops = query(
        "SELECT * FROM proceso_operaciones WHERE producto_id=? ORDER BY CAST(orden AS INTEGER), orden", (pid,))

    # Create new product
    nuevo_nombre_final = nuevo_nombre or (orig["nombre"] + " (copia)")
    # Nuevo artículo "Producto terminado" en la tabla única (sin stock: el
    # stock y los lotes no se copian, son del artículo original).
    new_pid = execute(
        """INSERT INTO materiales
           (codigo,descripcion,descripcion_larga,categoria,categoria_producto_id,unidad,
            tiempo_total_hs,costo_mat,costo_mo,precio_venta,activo,obs,capacidad_cajon,stock,stock_min)
           VALUES (?,?,?,'Producto terminado',?,?,?,?,?,?,?,?,?,0,0)""",
        (nuevo_codigo, nuevo_nombre_final, orig["descripcion"],
         orig["categoria_id"], orig["unidad"], orig["tiempo_total_hs"],
         orig["costo_mat"], orig["costo_mo"], orig["precio_venta"],
         1, orig["obs"], orig["capacidad_cajon"]))

    # Copy operations and their materials
    ops_copiadas = 0
    for op in orig_ops:
        new_opid = execute(
            """INSERT INTO proceso_operaciones
               (producto_id,orden,nombre,descripcion,categoria_maquina_id,maquina_id,
                tiempo_setup_min,tiempo_ciclo_seg,es_tercerizada,proveedor_id,
                precio_tercerizado,tiempo_minimo_dias,volumen_agrupado,valor_recalculado,obs)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (new_pid, op["orden"], op["nombre"], op["descripcion"],
             op["categoria_maquina_id"], op["maquina_id"],
             op["tiempo_setup_min"], op["tiempo_ciclo_seg"],
             op["es_tercerizada"] if "es_tercerizada" in op.keys() else 0,
             op["proveedor_id"] if "proveedor_id" in op.keys() else None,
             op["precio_tercerizado"] if "precio_tercerizado" in op.keys() else 0,
             op["tiempo_minimo_dias"] if "tiempo_minimo_dias" in op.keys() else 0,
             op["volumen_agrupado"] if "volumen_agrupado" in op.keys() else 0,
             op["valor_recalculado"] if "valor_recalculado" in op.keys() else 0,
             op["obs"] if "obs" in op.keys() else None))

        # Copy materials for this operation
        mats = query(
            "SELECT * FROM operacion_materiales WHERE operacion_id=?", (op["id"],))
        for m in mats:
            execute(
                "INSERT INTO operacion_materiales (operacion_id,material_id,producto_id,cantidad,unidad,tipo,vida_util_herramienta) VALUES (?,?,?,?,?,?,?)",
                (new_opid, m["material_id"] if "material_id" in m.keys() else None,
                 m["producto_id"] if "producto_id" in m.keys() else None,
                 m["cantidad"], m["unidad"],
                 m["tipo"] if "tipo" in m.keys() else "material",
                 m["vida_util_herramienta"]))
        ops_copiadas += 1

    return jsonify({
        "ok": True, "id": new_pid,
        "codigo": nuevo_codigo, "nombre": nuevo_nombre_final,
        "ops_copiadas": ops_copiadas
    }), 201

@app.route("/api/productos/<int:pid>", methods=["PUT"])
@login_required(roles=["admin","operario"])
def update_producto(pid):
    d = request.json
    # If only precio_venta is sent (partial update from OC), do a targeted UPDATE
    if "capacidad_cajon" in d or "nombre" in d:
        cap_cajon, err = _piezas_por_cajon(d.get("capacidad_cajon"))
        if err: return jsonify({"error": err}), 400
        d["capacidad_cajon"] = cap_cajon
    if "nombre" not in d:
        fields, vals = [], []
        for col in ["precio_venta","peso_kg","cliente_id","activo","obs","capacidad_cajon","codigo_barras"]:
            if col in d:
                fields.append(f"{col}=?")
                vals.append(d[col])
        if fields:
            execute(f"UPDATE materiales SET {', '.join(fields)},actualizado=datetime('now','localtime') WHERE id=?", vals + [pid])
        return jsonify({"ok": True})
    # Validar código si se está modificando (único en TODA la tabla de artículos)
    if d.get("codigo"):
        dup = _codigo_en_uso(d["codigo"], excluir_id=pid)
        if dup:
            return jsonify({"error": _msg_codigo_en_uso(dup)}), 409
    prod_actual = query("SELECT codigo,descripcion nombre,costo_mat,costo_mo,precio_venta FROM materiales WHERE id=?", (pid,), one=True)
    if not prod_actual:
        return jsonify({"error": "Producto no encontrado"}), 404
    nuevo_codigo = d.get("codigo") or prod_actual["codigo"]
    # v147: si el usuario no tiene permiso monetario el frontend no manda costos
    # ni precio: se conservan los valores actuales en vez de pisarlos con 0.
    # Tabla única: nombre -> descripcion, descripcion -> descripcion_larga,
    # categoria_id -> categoria_producto_id. No hay "espejo" que sincronizar:
    # el inventario, los lotes y las OT leen esta misma fila.
    execute("""UPDATE materiales SET codigo=?,descripcion=?,descripcion_larga=?,categoria_producto_id=?,unidad=?,
        tiempo_total_hs=?,costo_mat=?,costo_mo=?,precio_venta=?,peso_kg=?,cliente_id=?,obs=?,activo=?,
        capacidad_cajon=?,actualizado=datetime('now','localtime') WHERE id=?""",
        (nuevo_codigo,d["nombre"],d.get("descripcion"),d.get("categoria_id") or None,d.get("unidad","unid"),d.get("tiempo_total_hs",0),
         d.get("costo_mat",prod_actual["costo_mat"]),d.get("costo_mo",prod_actual["costo_mo"]),d.get("precio_venta",prod_actual["precio_venta"]),
         d.get("peso_kg",0),d.get("cliente_id") or None,d.get("obs"),1 if d.get("activo",True) else 0,d["capacidad_cajon"],pid))
    if "codigo_barras" in d:
        cb = (d.get("codigo_barras") or "").strip() or None
        execute("UPDATE materiales SET codigo_barras=? WHERE id=?", (cb, pid))
    return jsonify({"ok":True})

@app.route("/api/operaciones", methods=["POST"])
@login_required(roles=["admin","operario"])
def create_operacion():
    d = request.json
    if not d.get("producto_id") or not d.get("nombre"): return jsonify({"error":"Producto y nombre requeridos"}), 400
    prod_id_op = d.get("producto_id")
    # Un producto no puede usarse como insumo de sí mismo
    for mat in (d.get("materiales") or []):
        if mat.get("tipo") == "producto" and mat.get("producto_id") and int(mat["producto_id"]) == int(prod_id_op):
            return jsonify({"error":"Un producto no puede usarse como insumo de sí mismo"}), 400
    # Guardar versión antes de modificar
    usuario_actual = session.get("username", "sistema")
    guardar_version_producto(prod_id_op, motivo="Operación agregada: "+d.get("nombre",""), creado_por=usuario_actual)
    es_terc = 1 if d.get("es_tercerizada") else 0
    # Una operación no puede ser tercerizada y normal a la vez, y solo se
    # persiste como tercerizada si efectivamente se cargó info (proveedor
    # o precio) — si tildaron el check pero no cargaron nada, se guarda
    # como operación normal.
    if es_terc and not (d.get("proveedor_id") or (d.get("precio_tercerizado") or 0)):
        es_terc = 0
    # v147 (punto 9): una operación tercerizada exige un material como insumo
    # (es el mismo material que se genera al ingresar el remito del proveedor).
    if es_terc and not _tiene_insumo_material(d.get("materiales")):
        return jsonify({"error": "Una operación tercerizada requiere cargar obligatoriamente un material como insumo "
                                 "(es el mismo que se generará al ingresar el remito del proveedor)."}), 400
    vol_agrup = 1 if d.get("volumen_agrupado") else 0
    lid = execute("""INSERT INTO proceso_operaciones
        (producto_id,orden,nombre,descripcion,categoria_maquina_id,maquina_id,
         tiempo_setup_min,tiempo_ciclo_seg,es_tercerizada,proveedor_id,
         precio_tercerizado,tiempo_minimo_dias,obs,volumen_agrupado,valor_recalculado)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (d["producto_id"],d.get("orden",1),d["nombre"],d.get("descripcion"),
         d.get("categoria_maquina_id") if not es_terc else None,
         d.get("maquina_id") if not es_terc else None,
         d.get("tiempo_setup_min",0) if not es_terc else 0,
         d.get("tiempo_ciclo_seg",0) if not es_terc else 0,
         es_terc,
         d.get("proveedor_id") if es_terc else None,
         d.get("precio_tercerizado",0) if es_terc else 0,
         d.get("tiempo_minimo_dias",0),
         d.get("obs"),
         vol_agrup,
         d.get("valor_recalculado",0) if vol_agrup else 0))
    for mat in (d.get("materiales") or []):
        if mat.get("cantidad") and (mat.get("material_id") or mat.get("producto_id")):
            tipo_m = mat.get("tipo","material")
            mat_id = mat.get("material_id") or None
            # Un producto usado como insumo (tipo='producto') se resuelve al
            # material de stock 'Producto terminado' correspondiente (mismo
            # mapeo que usa el resto del sistema, vía get_or_create_pt_material),
            # así queda vinculado por material_id como cualquier otro material
            # y hereda automáticamente la trazabilidad por lote (selección de
            # lote en Órdenes de trabajo → Lotes asignados, descuento por
            # lote, etc.) en vez de tratarse como insumo sin lote.
            if tipo_m == "producto" and mat.get("producto_id"):
                prod_ins = query("SELECT id,codigo,nombre,unidad FROM productos WHERE id=?", (mat["producto_id"],), one=True)
                if prod_ins:
                    mat_pt = get_or_create_pt_material(prod_ins)
                    mat_id = mat_pt["id"]
            execute("INSERT INTO operacion_materiales (operacion_id,material_id,producto_id,cantidad,unidad,tipo,vida_util_herramienta) VALUES (?,?,?,?,?,?,?)",
                (lid, mat_id, mat.get("producto_id") or None,
                 mat["cantidad"], mat.get("unidad",""), tipo_m,
                 _vida_util_valida(mat_id, mat.get("vida_util_herramienta"))))
    _recalcular_tiempo_total_producto(d["producto_id"])
    return jsonify({"ok":True,"id":lid}), 201

@app.route("/api/operaciones/<int:oid>", methods=["PUT"])
@login_required(roles=["admin","operario"])
def update_operacion(oid):
    d = request.json
    row = query("SELECT producto_id FROM proceso_operaciones WHERE id=?", (oid,), one=True)
    if not row: return jsonify({"error":"Operación no encontrada"}), 404
    prod_id = row["producto_id"]
    # Un producto no puede usarse como insumo de sí mismo
    for mat in (d.get("materiales") or []):
        if mat.get("tipo") == "producto" and mat.get("producto_id") and int(mat["producto_id"]) == int(prod_id):
            return jsonify({"error":"Un producto no puede usarse como insumo de sí mismo"}), 400
    # Guardar versión antes de modificar
    guardar_version_producto(prod_id, motivo="Operación editada: "+d.get("nombre","op #"+str(oid)), creado_por=session.get("username","sistema"))
    nuevo_orden = d.get("orden", 1)
    es_terc = 1 if d.get("es_tercerizada") else 0
    # Sin ver_monetario el precio no viene en el payload: se usa el guardado.
    precio_terc = _mon_o_actual(d, "precio_tercerizado", "proceso_operaciones", oid)
    # Idem create_operacion: mutuamente excluyente y solo persiste como
    # tercerizada si se cargó proveedor o precio.
    if es_terc and not (d.get("proveedor_id") or (precio_terc or 0)):
        es_terc = 0
    if es_terc:
        if "materiales" in d:
            _mats_chk = d.get("materiales")
        else:
            _mats_chk = [dict(x) for x in query("SELECT material_id,cantidad,tipo FROM operacion_materiales WHERE operacion_id=?", (oid,))]
        if not _tiene_insumo_material(_mats_chk):
            return jsonify({"error": "Una operación tercerizada requiere cargar obligatoriamente un material como insumo "
                                     "(es el mismo que se generará al ingresar el remito del proveedor)."}), 400
    vol_agrup = 1 if d.get("volumen_agrupado") else 0
    execute("""UPDATE proceso_operaciones SET orden=?,nombre=?,descripcion=?,
        categoria_maquina_id=?,maquina_id=?,tiempo_setup_min=?,tiempo_ciclo_seg=?,
        es_tercerizada=?,proveedor_id=?,precio_tercerizado=?,tiempo_minimo_dias=?,obs=?,
        volumen_agrupado=?,valor_recalculado=?
        WHERE id=?""",
        (nuevo_orden, d["nombre"], d.get("descripcion"), d.get("categoria_maquina_id"),
         d.get("maquina_id"), d.get("tiempo_setup_min",0), d.get("tiempo_ciclo_seg",0),
         es_terc, d.get("proveedor_id") if es_terc else None,
         precio_terc if es_terc else 0,
         d.get("tiempo_minimo_dias",0), d.get("obs"),
         vol_agrup, d.get("valor_recalculado",0) if vol_agrup else 0, oid))
    # Update materials if provided
    if "materiales" in d:
        execute("DELETE FROM operacion_materiales WHERE operacion_id=?", (oid,))
        for mat in (d["materiales"] or []):
            if mat.get("cantidad") and (mat.get("material_id") or mat.get("producto_id")):
                tipo_m = mat.get("tipo","material")
                mat_id = mat.get("material_id") or None
                # Ver comentario equivalente en create_operacion: resolver
                # producto -> material 'Producto terminado' para que herede
                # trazabilidad por lote.
                if tipo_m == "producto" and mat.get("producto_id"):
                    prod_ins = query("SELECT id,codigo,nombre,unidad FROM productos WHERE id=?", (mat["producto_id"],), one=True)
                    if prod_ins:
                        mat_pt = get_or_create_pt_material(prod_ins)
                        mat_id = mat_pt["id"]
                execute("INSERT INTO operacion_materiales (operacion_id,material_id,producto_id,cantidad,unidad,tipo,vida_util_herramienta) VALUES (?,?,?,?,?,?,?)",
                    (oid, mat_id, mat.get("producto_id") or None,
                     mat["cantidad"], mat.get("unidad",""), tipo_m,
                     _vida_util_valida(mat_id, mat.get("vida_util_herramienta"))))
    # Recalculate total time
    _recalcular_tiempo_total_producto(prod_id)
    return jsonify({"ok":True})

@app.route("/api/operaciones/<int:oid>", methods=["DELETE"])
@login_required(roles=["admin","operario"])
def delete_operacion(oid):
    op = query("SELECT producto_id,nombre FROM proceso_operaciones WHERE id=?", (oid,), one=True)
    if op:
        guardar_version_producto(op["producto_id"], motivo="Operación eliminada: "+(op["nombre"] or ""), creado_por=session.get("username","sistema"))
    # Desvincular referencias que no tienen ON DELETE CASCADE/SET NULL en el esquema,
    # para no romper el borrado por FOREIGN KEY constraint failed.
    execute("UPDATE orden_operaciones SET proceso_op_id=NULL WHERE proceso_op_id=?", (oid,))
    execute("UPDATE ordenes_tercerizado SET proceso_op_id=NULL WHERE proceso_op_id=?", (oid,))
    execute("DELETE FROM proceso_operaciones WHERE id=?", (oid,))
    if op:
        _recalcular_tiempo_total_producto(op["producto_id"])
    return jsonify({"ok":True})

# ── Herramientas ──────────────────────────────────────────────────────────────
@app.route("/api/operaciones/<int:opid>/herramientas", methods=["GET"])
@login_required()
def get_herramientas(opid):
    rows = query("""SELECT * FROM herramientas_operacion
        WHERE operacion_id=? ORDER BY CAST(orden AS INTEGER), orden""", (opid,))
    return jsonify([dict(r) for r in rows])

@app.route("/api/operaciones/<int:opid>/herramientas", methods=["POST"])
@login_required(roles=["admin","operario"])
def add_herramienta(opid):
    d = request.json
    if not d.get("nombre"):
        return jsonify({"error": "Nombre requerido"}), 400
    lid = execute("""INSERT INTO herramientas_operacion
        (operacion_id, orden, nombre, descripcion, duracion_min, unidad, cantidad)
        VALUES (?,?,?,?,?,?,?)""",
        (opid, d.get("orden", 1), d["nombre"], d.get("descripcion"),
         d.get("duracion_min", 0), d.get("unidad", "unid"), d.get("cantidad", 1)))
    return jsonify({"ok": True, "id": lid}), 201

@app.route("/api/operaciones/<int:opid>/herramientas/<int:hid>", methods=["PUT"])
@login_required(roles=["admin","operario"])
def update_herramienta(opid, hid):
    d = request.json
    execute("""UPDATE herramientas_operacion SET orden=?,nombre=?,descripcion=?,
        duracion_min=?,unidad=?,cantidad=? WHERE id=? AND operacion_id=?""",
        (d.get("orden",1), d.get("nombre",""), d.get("descripcion"),
         d.get("duracion_min",0), d.get("unidad","unid"), d.get("cantidad",1),
         hid, opid))
    return jsonify({"ok": True})

@app.route("/api/operaciones/<int:opid>/herramientas/<int:hid>", methods=["DELETE"])
@login_required(roles=["admin","operario"])
def delete_herramienta(opid, hid):
    execute("DELETE FROM herramientas_operacion WHERE id=? AND operacion_id=?", (hid, opid))
    return jsonify({"ok": True})

# Herramientas del inventario de una operación: son las filas de
# operacion_materiales cuyo material es de categoría Herramienta, las mismas
# que se editan en "Editar" operación, así la vida útil (piezas por
# herramienta) alimenta requerimientos y consumos.
def _herr_inv_fila(opid, rid):
    return query("""SELECT om.id FROM operacion_materiales om
        JOIN materiales m ON m.id=om.material_id
        WHERE om.id=? AND om.operacion_id=? AND m.categoria='Herramienta'""", (rid, opid), one=True)

def _herr_inv_datos(d):
    try:
        cant = float(d.get("cantidad") or 1)
    except (TypeError, ValueError):
        cant = 0
    if cant <= 0:
        return None, None, "La cantidad tiene que ser mayor a 0"
    vida = d.get("vida_util_herramienta")
    if vida not in (None, ""):
        try:
            vida = int(float(vida))
        except (TypeError, ValueError):
            vida = 0
        if vida <= 0:
            return None, None, "Piezas por herramienta tiene que ser un entero mayor a 0"
    else:
        vida = None
    return cant, vida, None

@app.route("/api/operaciones/<int:opid>/herramientas_inv", methods=["GET"])
@login_required()
def get_herramientas_inv(opid):
    rows = query("""SELECT om.id, om.material_id, om.cantidad, om.unidad, om.vida_util_herramienta,
        m.codigo, m.descripcion
        FROM operacion_materiales om JOIN materiales m ON m.id=om.material_id
        WHERE om.operacion_id=? AND m.categoria='Herramienta' ORDER BY om.id""", (opid,))
    return jsonify([dict(r) for r in rows])

@app.route("/api/operaciones/<int:opid>/herramientas_inv", methods=["POST"])
@login_required(roles=["admin","operario"])
def add_herramienta_inv(opid):
    d = request.json or {}
    op = query("SELECT producto_id,nombre FROM proceso_operaciones WHERE id=?", (opid,), one=True)
    if not op: return jsonify({"error":"Operación no encontrada"}), 404
    mat = query("SELECT id,codigo,unidad,categoria FROM materiales WHERE id=?", (d.get("material_id"),), one=True)
    if not mat or mat["categoria"] != "Herramienta":
        return jsonify({"error":"Seleccioná una herramienta del inventario"}), 400
    cant, vida, err = _herr_inv_datos(d)
    if err: return jsonify({"error": err}), 400
    guardar_version_producto(op["producto_id"], motivo="Herramienta agregada en "+(op["nombre"] or "")+": "+mat["codigo"],
                             creado_por=session.get("username","sistema"))
    previa = query("SELECT id FROM operacion_materiales WHERE operacion_id=? AND material_id=?", (opid, mat["id"]), one=True)
    if previa:
        execute("UPDATE operacion_materiales SET cantidad=?, vida_util_herramienta=? WHERE id=?", (cant, vida, previa["id"]))
        return jsonify({"ok": True, "id": previa["id"]})
    rid = execute("""INSERT INTO operacion_materiales (operacion_id,material_id,cantidad,unidad,tipo,vida_util_herramienta)
        VALUES (?,?,?,?,'material',?)""", (opid, mat["id"], cant, mat["unidad"] or "unid", vida))
    return jsonify({"ok": True, "id": rid}), 201

@app.route("/api/operaciones/<int:opid>/herramientas_inv/<int:rid>", methods=["PUT"])
@login_required(roles=["admin","operario"])
def update_herramienta_inv(opid, rid):
    if not _herr_inv_fila(opid, rid): return jsonify({"error":"Herramienta no encontrada"}), 404
    cant, vida, err = _herr_inv_datos(request.json or {})
    if err: return jsonify({"error": err}), 400
    op = query("SELECT producto_id,nombre FROM proceso_operaciones WHERE id=?", (opid,), one=True)
    guardar_version_producto(op["producto_id"], motivo="Herramienta editada en "+(op["nombre"] or ""),
                             creado_por=session.get("username","sistema"))
    execute("UPDATE operacion_materiales SET cantidad=?, vida_util_herramienta=? WHERE id=?", (cant, vida, rid))
    return jsonify({"ok": True})

@app.route("/api/operaciones/<int:opid>/herramientas_inv/<int:rid>", methods=["DELETE"])
@login_required(roles=["admin","operario"])
def delete_herramienta_inv(opid, rid):
    if not _herr_inv_fila(opid, rid): return jsonify({"error":"Herramienta no encontrada"}), 404
    op = query("SELECT producto_id,nombre FROM proceso_operaciones WHERE id=?", (opid,), one=True)
    guardar_version_producto(op["producto_id"], motivo="Herramienta quitada en "+(op["nombre"] or ""),
                             creado_por=session.get("username","sistema"))
    execute("DELETE FROM operacion_materiales WHERE id=?", (rid,))
    return jsonify({"ok": True})




def _recalcular_tiempo_total_producto(prod_id):
    """Recalcula tiempo_total_hs de un producto sumando el tiempo de cada paso
    (orden). Si un paso tiene rutas alternativas (mismo número de orden, p.ej.
    2 procesos posibles para el mismo paso), se toma la más rápida como
    estimación — la ruta realmente usada se elige en Control de producción."""
    tot = query("""SELECT COALESCE(SUM(t),0) total FROM (
        SELECT MIN(tiempo_setup_min + tiempo_ciclo_seg/60.0) t
        FROM proceso_operaciones WHERE producto_id=? GROUP BY orden)""",
        (prod_id,), one=True)["total"]
    execute("UPDATE materiales SET tiempo_total_hs=? WHERE id=?", (round(tot/60,2), prod_id))

def tiempo_std_min(ops, qty):
    """Tiempo estándar en MINUTOS de una lista de operaciones para 'qty' piezas.
    Ojo con las unidades: tiempo_setup_min está en minutos (es una preparación
    de máquina, se hace una vez) y tiempo_ciclo_seg en segundos (es por pieza),
    así que el ciclo se pasa a minutos antes de sumar.
    Si un paso tiene rutas alternativas (mismo número de orden) se toma la más
    rápida, igual que calcular_tiempo_ciclo_total_seg y tiempo_total_hs."""
    por_paso = {}
    for op in ops:
        t = (op["tiempo_setup_min"] or 0) + (op["tiempo_ciclo_seg"] or 0) / 60.0 * qty
        k = op["orden"]
        por_paso[k] = t if k not in por_paso else min(por_paso[k], t)
    return sum(por_paso.values())

def calcular_tiempo_ciclo_total_seg(prod_id, qty=1.0, _camino=()):
    """Suma tiempo_ciclo_seg de todas las operaciones (sin setup), recursivo.
    Devuelve SEGUNDOS. Si un material es un PT con proceso, suma también su
    tiempo de fabricación. `_camino` son los productos de la rama actual: un
    PT que aparece en dos ramas se cuenta en las dos, y solo se corta un
    ciclo real (un producto que se contiene a sí mismo)."""
    if prod_id in _camino:
        return 0.0
    _camino = _camino + (prod_id,)

    # Tiempo de ciclo propio (si un paso tiene rutas alternativas con el
    # mismo número de orden, se toma la más rápida como estimación)
    ops = query("""SELECT COALESCE(SUM(t),0) s FROM (
        SELECT MIN(tiempo_ciclo_seg) t FROM proceso_operaciones
        WHERE producto_id=? GROUP BY orden)""",
        (prod_id,), one=True)
    total = float(ops["s"] or 0) * qty

    # Tiempo de sub-productos (materiales que son PT). En un paso con rutas
    # alternativas cuenta la ruta que más usa, no la suma de todas.
    mats = query("""SELECT material_id, SUM(paso) AS total_cant, categoria, codigo FROM (
        SELECT om.material_id, m.categoria, m.codigo, po.orden, MAX(om.cantidad)*? AS paso
        FROM proceso_operaciones po
        JOIN operacion_materiales om ON om.operacion_id=po.id
        JOIN materiales m ON m.id=om.material_id
        WHERE po.producto_id=?
        GROUP BY om.material_id, po.orden)
        GROUP BY material_id""", (qty, prod_id))

    for m in mats:
        if m["categoria"] == "Producto terminado":
            # Tabla única: el material PT ES el producto (mismo id).
            sub = query("SELECT id FROM materiales WHERE id=? AND activo=1",
                        (m["material_id"],), one=True)
            if sub:
                total += calcular_tiempo_ciclo_total_seg(
                    sub["id"], float(m["total_cant"] or 0), _camino)
    return total

def calcular_costo_producto(prod_id, qty=1.0, _camino=()):
    """Calcula costo_mat de un producto recursivamente.
    Si un material es un Producto terminado con proceso definido,
    su costo = costo de fabricarlo (materiales de sus operaciones).
    Una herramienta con vida útil se cuesta por el desgaste: precio x piezas
    / vida útil (una herramienta que dura 500 piezas suma 1/500 de su precio
    por pieza). En un paso con rutas alternativas cuenta la ruta que más
    material usa, no la suma de todas. `_camino` son los productos de la rama
    actual: un PT que aparece en dos ramas se cuesta en las dos, y solo se
    corta un ciclo real (un producto que se contiene a sí mismo)."""
    if prod_id in _camino:   # evitar ciclos
        return 0.0
    _camino = _camino + (prod_id,)

    mats = query("""SELECT material_id, SUM(paso) AS total_cant, precio_unit, categoria, codigo FROM (
        SELECT om.material_id, m.precio_unit, m.categoria, m.codigo, po.orden,
            MAX(CASE WHEN COALESCE(om.vida_util_herramienta,0)>0
                     THEN ?*1.0/om.vida_util_herramienta
                     ELSE om.cantidad*? END) AS paso
        FROM proceso_operaciones po
        JOIN operacion_materiales om ON om.operacion_id=po.id
        JOIN materiales m ON m.id=om.material_id
        WHERE po.producto_id=?
        GROUP BY om.material_id, po.orden)
        GROUP BY material_id""", (qty, qty, prod_id))

    costo_total = 0.0
    for m in mats:
        cant = float(m["total_cant"] or 0)
        if m["categoria"] == "Producto terminado":
            # Buscar si este PT tiene un producto-proceso definido
            # Tabla única: el material PT ES el producto (mismo id).
            sub_prod = query(
                "SELECT id FROM materiales WHERE id=? AND activo=1",
                (m["material_id"],), one=True)
            if sub_prod:
                costo_total += calcular_costo_producto(sub_prod["id"], cant, _camino)
                continue
        costo_total += float(m["precio_unit"] or 0) * cant
    return costo_total


# ── Gestión de archivos de producto ──────────────────────────────────────────
import os as _os, mimetypes as _mimetypes
from werkzeug.utils import secure_filename as _secure

FILES_BASE = _os.path.join(BASE_DIR, "documentos")

def _prod_dir(pid):
    """Returns the directory path for a product's files, creating it if needed."""
    prod = query("SELECT codigo FROM materiales WHERE id=?", (pid,), one=True)
    if not prod:
        return None, None
    safe_code = "".join(c if c.isalnum() or c in "-_." else "_" for c in prod["codigo"])
    path = _os.path.join(FILES_BASE, f"{safe_code}__{pid}")
    if not _os.path.isdir(path) and _os.path.isdir(FILES_BASE):
        # Si el código del artículo cambió (ahora se puede editar desde
        # Procesos o desde Inventario), la carpeta vieja sigue llamándose
        # <código viejo>__<id>: se la renombra para no "perder" los archivos.
        previas = [x for x in _os.listdir(FILES_BASE)
                   if x.endswith(f"__{pid}") and _os.path.isdir(_os.path.join(FILES_BASE, x))]
        if previas:
            try:
                _os.rename(_os.path.join(FILES_BASE, previas[0]), path)
            except OSError:
                return _os.path.join(FILES_BASE, previas[0]), prod["codigo"]
    _os.makedirs(path, exist_ok=True)
    return path, prod["codigo"]

# ── Versiones de producto ─────────────────────────────────────────────────────
@app.route("/api/productos/<int:pid>/versiones", methods=["GET"])
@login_required()
def list_versiones(pid):
    rows = query(
        """SELECT id,version_num,motivo,creado_por,creado
           FROM producto_versiones WHERE producto_id=?
           ORDER BY version_num DESC""", (pid,)
    )
    return jsonify([dict(r) for r in rows])

@app.route("/api/productos/<int:pid>/versiones/<int:vid>", methods=["GET"])
@login_required()
def get_version(pid, vid):
    import json
    row = query(
        "SELECT * FROM producto_versiones WHERE id=? AND producto_id=?",
        (vid, pid), one=True
    )
    if not row: return jsonify({"error":"Versión no encontrada"}), 404
    d = dict(row)
    d["snapshot"] = json.loads(d["snapshot"])
    prod_snap = d["snapshot"]["producto"]
    cat_id = prod_snap.get("categoria_id")
    if cat_id:
        cat = query("SELECT nombre FROM categorias_producto WHERE id=?", (cat_id,), one=True)
        prod_snap["categoria_nombre"] = cat["nombre"] if cat else None
    cli_id = prod_snap.get("cliente_id")
    if cli_id:
        cli = query("SELECT razon FROM clientes WHERE id=?", (cli_id,), one=True)
        prod_snap["cliente_nombre"] = cli["razon"] if cli else None
    # Completar datos de las operaciones que puedan faltar en snapshots viejos
    # (nombre de máquina específica y nombre de proveedor en tercerizadas)
    for op in d["snapshot"].get("operaciones", []):
        if not op.get("cat_maq_nombre") and op.get("categoria_maquina_id"):
            cm = query("SELECT nombre FROM categorias_maquina WHERE id=?", (op["categoria_maquina_id"],), one=True)
            op["cat_maq_nombre"] = cm["nombre"] if cm else None
        if not op.get("maquina_nombre") and op.get("maquina_id"):
            mq = query("SELECT nombre FROM maquinas WHERE id=?", (op["maquina_id"],), one=True)
            op["maquina_nombre"] = mq["nombre"] if mq else None
        if not op.get("proveedor_nombre") and op.get("proveedor_id"):
            pv = query("SELECT razon FROM proveedores WHERE id=?", (op["proveedor_id"],), one=True)
            op["proveedor_nombre"] = pv["razon"] if pv else None
    return jsonify(d)

@app.route("/api/productos/<int:pid>/versiones/<int:vid>", methods=["DELETE"])
@login_required(roles=["admin"])
def delete_version(pid, vid):
    execute("DELETE FROM producto_versiones WHERE id=? AND producto_id=?", (vid, pid))
    return jsonify({"ok": True})

def _sub_path(base, sub):
    """Resuelve una subcarpeta relativa dentro de la carpeta del artículo, sin permitir salir de ella."""
    sub = (sub or "").replace("\\", "/").strip("/")
    parts = [_secure(x) for x in sub.split("/") if x and x not in (".", "..")]
    full = _os.path.realpath(_os.path.join(base, *parts)) if parts else _os.path.realpath(base)
    root = _os.path.realpath(base)
    if full != root and not full.startswith(root + _os.sep):
        return None, ""
    return full, "/".join(parts)

@app.route("/api/productos/<int:pid>/archivos", methods=["GET"])
@login_required()
def list_archivos(pid):
    """Lista archivos y carpetas del artículo. ?sub=carpeta/subcarpeta navega la estructura."""
    path, codigo = _prod_dir(pid)
    if not path:
        return jsonify({"error": "Producto no encontrado"}), 404
    full, sub = _sub_path(path, request.args.get("sub"))
    if not full or not _os.path.isdir(full):
        return jsonify({"error": "Carpeta no encontrada"}), 404
    files, folders = [], []
    for fname in sorted(_os.listdir(full), key=str.lower):
        fpath = _os.path.join(full, fname)
        if _os.path.isdir(fpath):
            folders.append({"nombre": fname, "items": len(_os.listdir(fpath))})
        elif _os.path.isfile(fpath):
            stat = _os.stat(fpath)
            mime, _ = _mimetypes.guess_type(fname)
            files.append({
                "nombre": fname,
                "ruta":   (sub + "/" if sub else "") + fname,
                "size":   stat.st_size,
                "mime":   mime or "application/octet-stream",
                "is_img": (mime or "").startswith("image/"),
                "is_pdf": mime == "application/pdf",
            })
    return jsonify({"archivos": files, "carpetas": folders, "sub": sub, "carpeta": path})

@app.route("/api/productos/<int:pid>/carpetas", methods=["POST"])
@login_required(roles=["admin", "operario"])
def create_carpeta_archivos(pid):
    path, _ = _prod_dir(pid)
    if not path:
        return jsonify({"error": "Producto no encontrado"}), 404
    d = request.json or {}
    nombre = _secure((d.get("nombre") or "").strip())
    if not nombre:
        return jsonify({"error": "Nombre de carpeta requerido"}), 400
    base, _s = _sub_path(path, d.get("sub"))
    if not base:
        return jsonify({"error": "Ruta inválida"}), 400
    dest = _os.path.join(base, nombre)
    if _os.path.exists(dest):
        return jsonify({"error": "Ya existe una carpeta o archivo con ese nombre"}), 409
    _os.makedirs(dest)
    return jsonify({"ok": True, "nombre": nombre}), 201

@app.route("/api/productos/<int:pid>/carpetas", methods=["DELETE"])
@login_required(roles=["admin"])
def delete_carpeta_archivos(pid):
    path, _ = _prod_dir(pid)
    if not path:
        return jsonify({"error": "Producto no encontrado"}), 404
    full, sub = _sub_path(path, request.args.get("sub"))
    if not full or not sub or not _os.path.isdir(full):
        return jsonify({"error": "Carpeta no encontrada"}), 404
    if _os.listdir(full):
        return jsonify({"error": "La carpeta no está vacía. Eliminá primero su contenido."}), 400
    _os.rmdir(full)
    return jsonify({"ok": True})

@app.route("/api/productos/<int:pid>/archivos", methods=["POST"])
@login_required(roles=["admin", "operario"])
def upload_archivo(pid):
    from flask import request as _req
    path, _ = _prod_dir(pid)
    if not path:
        return jsonify({"error": "Producto no encontrado"}), 404
    if "file" not in _req.files:
        return jsonify({"error": "Sin archivo"}), 400
    f = _req.files["file"]
    if not f.filename:
        return jsonify({"error": "Nombre vacío"}), 400
    full, _s = _sub_path(path, _req.form.get("sub") or _req.args.get("sub"))
    if not full:
        return jsonify({"error": "Ruta inválida"}), 400
    _os.makedirs(full, exist_ok=True)
    safe = _secure(f.filename)
    dest = _os.path.join(full, safe)
    f.save(dest)
    return jsonify({"ok": True, "nombre": safe}), 201

@app.route("/api/productos/<int:pid>/archivos/<path:nombre>", methods=["GET"])
@login_required()
def download_archivo(pid, nombre):
    from flask import send_from_directory
    path, _ = _prod_dir(pid)
    if not path:
        return jsonify({"error": "Producto no encontrado"}), 404
    return send_from_directory(path, nombre)

@app.route("/api/productos/<int:pid>/archivos/<path:nombre>", methods=["DELETE"])
@login_required(roles=["admin"])
def delete_archivo(pid, nombre):
    path, _ = _prod_dir(pid)
    if not path:
        return jsonify({"error": "Producto no encontrado"}), 404
    fpath = _os.path.realpath(_os.path.join(path, nombre))
    if not fpath.startswith(_os.path.realpath(path) + _os.sep) or not _os.path.isfile(fpath):
        return jsonify({"error": "Archivo no encontrado"}), 404
    _os.remove(fpath)
    return jsonify({"ok": True})


# Funciones de otras áreas. Van al final a propósito: así cada módulo ya
# definió todo lo suyo cuando otro lo importa, y no hay problemas de
# importación circular. Se usan recién al atender pedidos.
from .comun import _tiene_insumo_material, _vida_util_valida, get_or_create_pt_material

"""Materiales (inventario) y movimientos de stock."""
from .nucleo import app, execute, jsonify, login_required, query, request, session

# ── Inventario ────────────────────────────────────────────────────────────────
@app.route("/api/materiales", methods=["GET"])
@login_required()
def get_materiales():
    categoria = request.args.get("categoria")
    # El stock mostrado en inventario es la suma del APROBADO de los lotes
    # ingresados para ese material. "Aprobado" = lotes.cantidad_activa, que
    # es la cantidad aprobada vigente de cada lote (puede ser parcial, sin
    # que el lote como un todo tenga estado='Aprobado'). NO se debe filtrar
    # por lotes.estado: eso deja afuera lotes parcialmente aprobados.
    sql = """SELECT m.*,
                    p.razon proveedor_nombre, cp.nombre cat_prod_nombre,
                    cli.razon cliente_nombre,
                    COALESCE((SELECT SUM(l.cantidad_activa) FROM lotes l
                              WHERE l.material_id=m.id), 0) AS stock_lotes
             FROM materiales m
             LEFT JOIN clientes cli ON cli.id=m.cliente_id
             LEFT JOIN proveedores p ON p.id=m.proveedor_id
             LEFT JOIN categorias_producto cp ON cp.id=m.categoria_producto_id"""
    if categoria:
        rows = query(sql+" WHERE m.categoria=? ORDER BY m.codigo", (categoria,))
    else:
        rows = query(sql+" ORDER BY m.codigo")
    out = []
    for r in rows:
        d = dict(r)
        # Para materiales con categoria 'Material', 'Producto terminado' o
        # 'Semielaborado' (los tres manejan lotes — este último son los
        # materiales auto-generados por retorno de OTT intermedia, ver
        # ott_registrar_retorno), se reemplaza el stock por el stock
        # aprobado de lotes. Insumos sin lote conservan el stock original.
        if d.get("categoria") in ("Material", "Producto terminado", "Semielaborado"):
            d["stock"] = d.pop("stock_lotes")
        else:
            d.pop("stock_lotes", None)
        out.append(d)
    return jsonify(out)

@app.route("/api/materiales/productos_terminados", methods=["GET"])
@login_required()
def get_productos_terminados_stock():
    rows = query("""SELECT m.*,pr.nombre producto_nombre,c.razon cliente_nombre,cp.nombre cat_prod_nombre,
            COALESCE(m.cliente_id, pr.cliente_id) cliente_id_efectivo
        FROM materiales m
        LEFT JOIN productos pr ON pr.id=m.id
        LEFT JOIN categorias_producto cp ON cp.id=m.categoria_producto_id
        LEFT JOIN clientes c ON c.id=COALESCE(m.cliente_id, pr.cliente_id)
        WHERE m.categoria='Producto terminado'
        ORDER BY c.razon,m.codigo""")
    return jsonify([dict(r) for r in rows])

@app.route("/api/materiales", methods=["POST"])
@login_required(roles=["admin","almacen","logistica"])
def create_material():
    d = request.json
    if not d.get("codigo") or not d.get("descripcion"): return jsonify({"error":"Código y descripción requeridos"}), 400
    dup = _codigo_en_uso(d["codigo"])
    if dup: return jsonify({"error": _msg_codigo_en_uso(dup)}), 409
    stock_inicial = float(d.get("stock", 0) or 0)
    lid = execute("INSERT INTO materiales (codigo,descripcion,categoria,categoria_producto_id,unidad,stock,stock_min,stock_max,precio_unit,proveedor_id,obs) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (d["codigo"],d["descripcion"],d.get("categoria","Material"),d.get("categoria_producto_id"),d.get("unidad","kg"),stock_inicial,d.get("stock_min",0),d.get("stock_max",0),d.get("precio_unit",0),d.get("proveedor_id"),d.get("obs")))
    if stock_inicial > 0 and d.get("categoria","Material") == "Material":
        # Auto-create lote for initial stock
        lote_num = _gen_lote_numero()
        lote_id = execute("""INSERT INTO lotes
            (numero,material_id,cantidad_original,cantidad_disponible,
             proveedor_id,referencia_proveedor,estado,obs,creado_por,stock_computado)
            VALUES (?,?,?,?,?,?,?,?,?,1)""",
            (lote_num, lid, stock_inicial, stock_inicial,
             d.get("proveedor_id"), "Stock inicial al dar de alta",
             "Ingresado", "Creado automáticamente al dar de alta el material",
             session["user_id"]))
        execute("INSERT INTO movimientos (material_id,lote_id,tipo,cantidad,referencia,usuario_id) VALUES (?,?,?,?,?,?)",
            (lid, lote_id, "entrada", stock_inicial, f"Stock inicial — {lote_num}", session["user_id"]))
    elif stock_inicial > 0:
        execute("INSERT INTO movimientos (material_id,tipo,cantidad,referencia,usuario_id) VALUES (?,?,?,?,?)",
            (lid, "entrada", stock_inicial, "Stock inicial al dar de alta", session["user_id"]))
    _aplicar_cliente_barras_material(lid, d, es_alta=True)
    return jsonify({"ok":True,"id":lid}), 201

def _aplicar_cliente_barras_material(mid, d, es_alta=False):
    """Cliente y código de barras/QR/DataMatrix (punto 17) del artículo.

    Desde la unificación de productos y materiales el TIPO (categoria) es
    explícito: lo elige el usuario y NO se deduce del cliente. Antes, asignar
    un cliente forzaba 'Producto terminado' y quitarlo volvía a 'Material'."""
    if "codigo_barras" in d:
        execute("UPDATE materiales SET codigo_barras=? WHERE id=?", ((d.get("codigo_barras") or "").strip() or None, mid))
    if "cliente_id" in d:
        execute("UPDATE materiales SET cliente_id=? WHERE id=?", (d.get("cliente_id") or None, mid))

@app.route("/api/materiales/<int:mid>", methods=["PUT"])
@login_required(roles=["admin","almacen","logistica"])
def update_material(mid):
    d = request.json
    rol_sesion = session.get("rol")
    actual = query("SELECT codigo,producto_id,categoria FROM materiales WHERE id=?", (mid,), one=True)
    if not actual:
        return jsonify({"error": "Material no encontrado"}), 404
    nuevo_codigo = actual["codigo"]
    if "codigo" in d and d.get("codigo") and d["codigo"] != actual["codigo"]:
        # Tabla única: el código de un producto terminado se puede editar desde
        # acá o desde Procesos (es la misma fila). Solo los semielaborados
        # (producto_id apunta a OTRO artículo) tienen código generado por el
        # sistema a partir del de su producto.
        if actual["producto_id"] and actual["producto_id"] != mid:
            return jsonify({"error": "Este código lo genera el sistema a partir del producto al que pertenece (semielaborado)."}), 400
        dup = _codigo_en_uso(d["codigo"], excluir_id=mid)
        if dup:
            return jsonify({"error": _msg_codigo_en_uso(dup)}), 409
        nuevo_codigo = d["codigo"]
    if "precio_unit" in d and rol_sesion == "admin":
        execute("UPDATE materiales SET codigo=?,descripcion=?,categoria=?,categoria_producto_id=?,unidad=?,stock_min=?,stock_max=?,precio_unit=?,proveedor_id=?,obs=?,actualizado=datetime('now','localtime') WHERE id=?",
            (nuevo_codigo,d["descripcion"],d.get("categoria") or actual["categoria"],d.get("categoria_producto_id"),d.get("unidad"),d.get("stock_min",0),d.get("stock_max",0),d["precio_unit"],d.get("proveedor_id"),d.get("obs"),mid))
    else:
        execute("UPDATE materiales SET codigo=?,descripcion=?,categoria=?,categoria_producto_id=?,unidad=?,stock_min=?,stock_max=?,proveedor_id=?,obs=?,actualizado=datetime('now','localtime') WHERE id=?",
            (nuevo_codigo,d["descripcion"],d.get("categoria") or actual["categoria"],d.get("categoria_producto_id"),d.get("unidad"),d.get("stock_min",0),d.get("stock_max",0),d.get("proveedor_id"),d.get("obs"),mid))
    _aplicar_cliente_barras_material(mid, d)
    # Propagar la nueva descripción a las copias guardadas en compras
    # (solicitudes_compra y ordenes_compra_items no hacen JOIN en vivo con materiales,
    #  guardan una copia propia del texto al momento de crearse)
    if d.get("descripcion"):
        execute("UPDATE solicitudes_compra SET descripcion=? WHERE material_id=?", (d["descripcion"], mid))
        execute("UPDATE ordenes_compra_items SET descripcion=? WHERE material_id=?", (d["descripcion"], mid))
    return jsonify({"ok":True})

# Clasificación de movimientos por origen (v148). Orden = prioridad al etiquetar.
_MOV_ORIGENES = {
    "ott":        ("Retorno de terceros (OTT)", ["Retorno OTT %", "Recepción OTT %"], []),
    "directa":    ("Recepción sin OC", ["Recepción REC-%"], []),
    "oc":         ("Recepción según OC", ["Recep. %", "Recepción de OC %"], []),
    "devolucion": ("Devolución / reenvío", ["Devolución a proveedor%", "Reenvío a tercerizado%"], []),
    "remitos":    ("Remito a cliente", ["Remito %"], []),
    "consumos":   ("Consumo de producción", ["Consumo%", "Ajuste consumo%", "Reversión OT%", "Reversa%", "Restauración%", "Ajuste PT%", "Corrección de aprobaci%"], ["reserva"]),
    "lotes":      ("Alta / aprobación de lote", ["OC % emitida%", "Generación automática%", "Ingreso lote%", "Aprobación de lote%", "Stock inicial%", "Migración inicial%", "Edición liberación%"], []),
    "ajustes":    ("Ajuste manual", ["Ajuste%", "Edición libre%"], []),
}
def _mov_origen_cond(key):
    _l, likes, tipos = _MOV_ORIGENES[key]
    cond = [f"mv.referencia LIKE ?" for _ in likes] + [f"mv.tipo=?" for _ in tipos]
    return "(" + " OR ".join(cond) + ")", list(likes) + list(tipos)
def _mov_origen_label(ref, tipo):
    import re as _re
    ref = ref or ""
    for k, (lbl, likes, tipos) in _MOV_ORIGENES.items():
        for lk in likes:
            rx = "^" + ".*".join(_re.escape(x) for x in lk.split("%")) + "$"
            if _re.match(rx, ref, _re.S):
                return lbl
        if tipo in tipos:
            return lbl
    return "Otros"

@app.route("/api/movimientos", methods=["GET"])
@login_required()
def get_movimientos():
    material_id = request.args.get("material_id")
    tipo = request.args.get("tipo")
    sql = """SELECT mv.*,m.codigo mat_codigo,m.descripcion mat_descripcion,m.unidad mat_unidad,
        u.nombre usuario_nombre, l.numero lote_numero
        FROM movimientos mv
        LEFT JOIN materiales m ON m.id=mv.material_id
        LEFT JOIN usuarios u ON u.id=mv.usuario_id
        LEFT JOIN lotes l ON l.id=mv.lote_id"""
    conditions = []
    params = []
    if material_id:
        conditions.append("mv.material_id=?")
        params.append(material_id)
    if tipo:
        conditions.append("mv.tipo=?")
        params.append(tipo)
    # v148 (punto 7): origen del movimiento = clasificación por tipo/referencia
    origen = request.args.get("origen")
    if origen == "recepciones":
        parts = []
        for k in ("directa", "oc", "ott"):
            c_, p_ = _mov_origen_cond(k); parts.append(c_); params += p_
        conditions.append("(" + " OR ".join(parts) + ")")
    elif origen in _MOV_ORIGENES:
        c_, p_ = _mov_origen_cond(origen)
        conditions.append(c_); params += p_
    desde = request.args.get("desde"); hasta = request.args.get("hasta")
    if desde:
        conditions.append("date(mv.fecha)>=date(?)"); params.append(desde)
    if hasta:
        conditions.append("date(mv.fecha)<=date(?)"); params.append(hasta)
    q = (request.args.get("q") or "").strip()
    if q:
        conditions.append("(mv.referencia LIKE ? OR l.numero LIKE ?)"); params += [f"%{q}%", f"%{q}%"]
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    try: limite = min(int(request.args.get("limit", 500)), 5000)
    except (TypeError, ValueError): limite = 500
    sql += f" ORDER BY mv.id DESC LIMIT {limite}"
    rows = query(sql, params)
    out = []
    for r in rows:
        d_ = dict(r); d_["origen"] = _mov_origen_label(d_.get("referencia"), d_.get("tipo")); out.append(d_)
    return jsonify(out)


# Funciones de otras áreas. Van al final a propósito: así cada módulo ya
# definió todo lo suyo cuando otro lo importa, y no hay problemas de
# importación circular. Se usan recién al atender pedidos.
from .productos import _codigo_en_uso, _msg_codigo_en_uso
from .lotes import _gen_lote_numero

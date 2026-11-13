"""Proveedores, solicitudes de compra, cotizaciones, órdenes de compra y recepciones."""
from .nucleo import (app, datetime, execute, jsonify, login_required, next_numero_oc,
    next_numero_sc, query, request, session, siguiente_numero, solo_con_monetario)

# ── Proveedores ───────────────────────────────────────────────────────────────
@app.route("/api/proveedores", methods=["GET"])
@login_required()
def get_proveedores():
    rows = query("SELECT * FROM proveedores ORDER BY razon")
    result = []
    for r in rows:
        d = dict(r)
        d["mat_vinculados"] = [dict(x) for x in query(
            "SELECT m.id,m.codigo,m.descripcion,m.unidad,pm.precio_unit,pm.plazo_dias,pm.es_principal FROM proveedor_materiales pm JOIN materiales m ON m.id=pm.material_id WHERE pm.proveedor_id=? ORDER BY pm.es_principal DESC,m.codigo",
            (r["id"],))]
        result.append(d)
    return jsonify(result)

@app.route("/api/proveedores", methods=["POST"])
@login_required(roles=["admin","almacen","vendedor"])
def create_proveedor():
    d = request.json
    if not d.get("razon"): return jsonify({"error":"Razón social requerida"}), 400
    lid = execute("INSERT INTO proveedores (razon,cuit,contacto,telefono,email,materiales,plazo_dias,calificacion,estado,obs,categoria_compra) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (d["razon"],d.get("cuit"),d.get("contacto"),d.get("telefono"),d.get("email"),d.get("materiales"),d.get("plazo_dias",3),d.get("calificacion",5),d.get("estado","Activo"),d.get("obs"),d.get("categoria_compra") or None))
    return jsonify({"ok":True,"id":lid}), 201

@app.route("/api/proveedores/<int:pid>", methods=["PUT"])
@login_required(roles=["admin","almacen"])
def update_proveedor(pid):
    d = request.json
    if not d.get("razon"): return jsonify({"error":"Razón social requerida"}), 400
    execute("UPDATE proveedores SET razon=?,cuit=?,contacto=?,telefono=?,email=?,materiales=?,plazo_dias=?,calificacion=?,estado=?,obs=?,categoria_compra=? WHERE id=?",
        (d["razon"],d.get("cuit"),d.get("contacto"),d.get("telefono"),d.get("email"),d.get("materiales"),d.get("plazo_dias",3),d.get("calificacion",5),d.get("estado","Activo"),d.get("obs"),d.get("categoria_compra") or None,pid))
    return jsonify({"ok":True})

@app.route("/api/proveedores/<int:pid>/materiales", methods=["GET"])
@login_required()
def get_proveedor_materiales(pid):
    rows = query("""SELECT m.id,m.codigo,m.descripcion,m.unidad,
        pm.precio_unit,pm.plazo_dias,pm.es_principal
        FROM proveedor_materiales pm
        JOIN materiales m ON m.id=pm.material_id
        WHERE pm.proveedor_id=? ORDER BY pm.es_principal DESC,m.codigo""", (pid,))
    return jsonify([dict(r) for r in rows])

@app.route("/api/proveedores/<int:pid>/materiales", methods=["POST"])
@login_required(roles=["admin","almacen"])
def link_mat(pid):
    d = request.json
    if not d.get("material_id"): return jsonify({"error":"Material requerido"}), 400
    execute("INSERT OR REPLACE INTO proveedor_materiales (proveedor_id,material_id,precio_unit,plazo_dias,es_principal) VALUES (?,?,?,?,?)",
        (pid, d["material_id"], d.get("precio_unit",0), d.get("plazo_dias",3), 1 if d.get("es_principal") else 0))
    return jsonify({"ok":True})

# ── Solicitudes de compra ─────────────────────────────────────────────────────
def auto_generar_sc_bajo_stock(material_id, motivo=""):
    """Si el material quedó por debajo de su stock mínimo, genera automáticamente
    una Solicitud de Compra (si no hay ya una en curso para ese material) por la
    diferencia entre stock actual y stock máximo (o el mínimo si no hay máximo
    configurado).

    Mientras haya una SC todavía ajustable (Pendiente o Cotizada, es decir
    que todavía no se emitió su OC) para el material, NO se genera una
    nueva: se sigue trabajando con la misma, actualizando la cantidad
    solicitada si el stock siguió bajando.

    Si la SC ya tiene su OC emitida, su cantidad quedó fijada en esa orden
    de compra y ya no se puede tocar. Mientras esa OC todavía no se recibió
    (total o parcialmente) por una cantidad que cubra el faltante, NO se
    genera una SC nueva: el gasto ya está cubierto por la OC en camino. Solo
    si, aun contando esa OC pendiente de recibir, el faltante neto sigue
    siendo positivo (por ejemplo porque el consumo posterior fue mayor a lo
    pedido), se genera una SC adicional por ese remanente.

    Tampoco se genera (ni se actualiza) una SC por la parte del faltante que
    ya está cubierta por stock que YA ingresó a planta pero todavía está
    pendiente de aprobación de Calidad y que todavía NO está sumado a
    materiales.stock (lotes 'Ingresado' del modelo viejo, stock_computado=0:
    su stock lo suma Calidad al aprobar). Los lotes con stock_computado=1 ya
    entraron a materiales.stock al recibirse, aprobados o no, así que no se
    vuelven a contar. Solo si, aun contando ese pendiente, el faltante neto
    sigue siendo positivo, se genera la SC por ese remanente.

    Cuando el stock del material vuelve a completarse hasta el objetivo
    (stock máximo, o el mínimo si no hay máximo configurado) —típicamente al
    recibirse/aprobarse la mercadería de la OC emitida— se da por resuelta
    cualquier SC que siguiera abierta para ese material (se marca 'Cerrada').
    Recién ahí, la próxima vez que el stock vuelva a caer por debajo del
    mínimo, se generará una SC nueva.

    No hace nada si el material no es comprable (Producto terminado) o no
    tiene mínimo configurado.

    Desactivado por defecto: ver _sc_automaticas_activas()."""
    if not _sc_automaticas_activas():
        return
    if not material_id:
        return
    mat = query("SELECT id,codigo,descripcion,stock,stock_min,stock_max,unidad,categoria FROM materiales WHERE id=?",
                (material_id,), one=True)
    # "Producto terminado" NUNCA es comprable en Compras: si un material de
    # esta categoría queda bajo stock, el faltante se resuelve fabricándolo
    # (OT auxiliar vía _gap_analysis_materiales), no
    # con una Solicitud de Compra. Este chequeo antes decía excluir "Producto
    # terminado" en el comentario de arriba pero lo dejaba pasar en el código
    # (bug) — quedaba visible como faltante comprable en Compras.
    if not mat or mat["categoria"] not in ("Material", "Insumo", "Herramienta"):
        return
    stock_min = float(mat["stock_min"] or 0)
    stock_max = float(mat["stock_max"] or 0)
    stock = float(mat["stock"] or 0)
    objetivo = stock_max if stock_max > stock_min else stock_min

    # El stock se completó de nuevo hasta el objetivo: cerramos cualquier SC
    # que siguiera en curso para este material, para dejar de "trabajar" con
    # ella y habilitar que se genere una SC nueva la próxima vez que el
    # stock vuelva a quedar bajo.
    if objetivo > 0 and stock >= objetivo:
        execute("""UPDATE solicitudes_compra SET estado='Cerrada'
            WHERE material_id=? AND estado IN ('Pendiente','Cotizada','OC Emitida')""",
            (material_id,))
        return

    if stock_min <= 0 or stock >= stock_min:
        return

    faltante = round(objetivo - stock, 3)

    # Cuánto de ese faltante ya está cubierto por OC emitidas para este
    # material que todavía no se recibieron por completo (lo que está "en
    # camino" o ya recibido pero pendiente de aprobación de Calidad). Si esa
    # cobertura ya alcanza para tapar el faltante, no corresponde generar
    # (ni actualizar) una SC nueva: el gasto ya está cubierto.
    # (por ítem, MAX(0, ...): un ítem recibido de más no resta lo que falta
    # de otro)
    pendiente_entrega = query("""SELECT COALESCE(SUM(MAX(0, i.cantidad - i.cantidad_recibida)),0) pend
        FROM ordenes_compra_items i
        JOIN solicitudes_compra s ON s.id = i.solicitud_id
        WHERE s.material_id=? AND s.estado='OC Emitida'""", (material_id,), one=True)["pend"] or 0

    # Stock que YA está en planta pero todavía sin decisión de Calidad y que
    # NO figura en materiales.stock: solo los lotes 'Ingresado' del modelo
    # viejo (stock_computado=0), que suman a stock recién al aprobarse. Los
    # lotes con stock_computado=1 ya están dentro de `stock` (ver
    # recibir_oc / create_recepcion); sumarlos acá los contaba dos veces y
    # podía frenar una SC necesaria.
    pendiente_aprobacion = query("""SELECT COALESCE(SUM(cantidad_disponible),0) pend
        FROM lotes WHERE material_id=? AND estado='Ingresado'
          AND COALESCE(stock_computado,0)=0""",
        (material_id,), one=True)["pend"] or 0

    faltante_neto = round(faltante - float(pendiente_entrega) - float(pendiente_aprobacion), 3)
    if faltante_neto <= 0:
        return
    faltante = faltante_neto

    # ¿Ya hay una SC todavía ajustable (Pendiente/Cotizada) para este
    # material? Seguimos trabajando con ella en lugar de generar otra.
    # Una SC con OC ya emitida NO bloquea la generación de una nueva: su
    # cantidad quedó fijada en esa orden de compra y, si el stock sigue (o
    # vuelve a quedar) por debajo del mínimo, corresponde generar una SC
    # adicional en vez de esperar a que llegue la mercadería de la anterior.
    activa = query("""SELECT id,estado,cantidad FROM solicitudes_compra
        WHERE material_id=? AND estado IN ('Pendiente','Cotizada')
        ORDER BY id DESC LIMIT 1""", (material_id,), one=True)
    if activa:
        # Todavía está Pendiente/Cotizada: la actualizamos para reflejar el
        # nuevo faltante en vez de crear otra.
        if faltante > float(activa["cantidad"] or 0):
            execute("UPDATE solicitudes_compra SET cantidad=? WHERE id=?", (faltante, activa["id"]))
        return

    numero = next_numero_sc()
    urgencia = "Urgente" if stock <= 0 else "Normal"
    obs = f"Generada automáticamente: stock ({stock}) por debajo del mínimo ({stock_min}). Reposición hasta stock máximo ({objetivo})."
    if motivo: obs += f" Origen: {motivo}."
    tipo_sc = "Productiva" if mat["categoria"] == "Material" else "Indirecta"
    execute("""INSERT INTO solicitudes_compra
        (numero,tipo,material_id,descripcion,cantidad,unidad,urgencia,estado,solicitante_id,obs)
        VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (numero, tipo_sc, material_id, mat["descripcion"], faltante,
         mat["unidad"], urgencia, "Pendiente", session.get("user_id"), obs))

@app.route("/api/solicitudes_compra/pendientes_count", methods=["GET"])
@login_required()
def get_sc_pendientes_count():
    # Cantidad de SC en estado 'Pendiente' -> usado por el badge del sidebar
    # en el módulo de Compras. Liviano a propósito (COUNT en vez de traer
    # todas las filas) porque se consulta con polling desde el frontend.
    row = query("SELECT COUNT(*) c FROM solicitudes_compra WHERE estado='Pendiente'", one=True)
    return jsonify({"count": row["c"]})

@app.route("/api/solicitudes_compra", methods=["GET"])
@login_required()
def get_solicitudes():
    tipo = request.args.get("tipo")
    sql = """SELECT s.*,m.codigo mat_codigo,m.descripcion mat_nombre,m.unidad mat_unidad,
        u.nombre solicitante_nombre, o.numero ot_numero,
        (SELECT oc.id FROM ordenes_compra_items oci JOIN ordenes_compra oc ON oc.id=oci.oc_id
            WHERE oci.solicitud_id=s.id ORDER BY oci.id DESC LIMIT 1) oc_id,
        (SELECT oc.numero FROM ordenes_compra_items oci JOIN ordenes_compra oc ON oc.id=oci.oc_id
            WHERE oci.solicitud_id=s.id ORDER BY oci.id DESC LIMIT 1) oc_numero
        FROM solicitudes_compra s
        LEFT JOIN materiales m ON m.id=s.material_id
        LEFT JOIN usuarios u ON u.id=s.solicitante_id
        LEFT JOIN ordenes o ON o.id=s.ot_origen_id"""
    rows = query(sql+" WHERE s.tipo=? ORDER BY s.id DESC",(tipo,)) if tipo else query(sql+" ORDER BY s.id DESC")
    return jsonify([dict(r) for r in rows])

@app.route("/api/solicitudes_compra", methods=["POST"])
@login_required(roles=["admin","almacen","operario","vendedor"])
def create_solicitud():
    d = request.json
    if not d.get("descripcion") or not d.get("cantidad"):
        return jsonify({"error":"Descripción y cantidad requeridas"}), 400
    tipo = d.get("tipo", "Productiva")
    if d.get("material_id"):
        mat = query("SELECT categoria FROM materiales WHERE id=?", (d["material_id"],), one=True)
        if not mat or mat["categoria"] not in ("Material", "Insumo", "Herramienta"):
            return jsonify({"error":"Solo se pueden solicitar materiales, insumos o herramientas — un producto terminado no se compra, se fabrica (generá o esperá la OT correspondiente)"}), 400
        if tipo == "Productiva" and mat["categoria"] != "Material":
            return jsonify({"error":"Una SC productiva solo puede cargar materiales, no insumos ni herramientas"}), 400
        if tipo == "Indirecta" and mat["categoria"] not in ("Insumo", "Herramienta"):
            return jsonify({"error":"Una SC indirecta solo puede cargar insumos o herramientas"}), 400
    elif tipo == "Productiva":
        return jsonify({"error":"Una SC productiva debe cargar un material"}), 400
    if d.get("material_id"):
        activa = query(f"""SELECT numero FROM solicitudes_compra
            WHERE material_id=? AND estado IN {SC_ABIERTAS_SQL}
            ORDER BY id DESC LIMIT 1""", (d["material_id"],), one=True)
        if activa:
            return jsonify({"error":f"Ya existe una solicitud de compra activa ({activa['numero']}) para este material"}), 400
    numero = next_numero_sc()
    lid = execute("""INSERT INTO solicitudes_compra
        (numero,tipo,material_id,descripcion,cantidad,unidad,urgencia,estado,ot_origen_id,centro_costo,solicitante_id,obs)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (numero,d.get("tipo","Productiva"),d.get("material_id"),d["descripcion"],d["cantidad"],
         d.get("unidad"),d.get("urgencia","Normal"),"Pendiente",d.get("ot_origen_id"),
         d.get("centro_costo"),session["user_id"],d.get("obs")))
    return jsonify({"ok":True,"id":lid,"numero":numero}), 201

@app.route("/api/solicitudes_compra/<int:sid>", methods=["PUT"])
@login_required(roles=["admin","almacen","vendedor"])
def update_solicitud(sid):
    d = request.json
    actual = query("SELECT * FROM solicitudes_compra WHERE id=?", (sid,), one=True)
    if not actual: return jsonify({"error":"No encontrada"}), 404
    if actual["estado"] == "OC Emitida":
        return jsonify({"error":"No se puede editar: ya tiene una OC emitida"}), 400
    campos = ["tipo","material_id","descripcion","cantidad","unidad","urgencia","estado","ot_origen_id","centro_costo","obs"]
    valores = {c: d[c] if c in d else actual[c] for c in campos}
    # "OC Emitida" lo pone create_oc al emitir la OC; a mano dejaba la SC
    # cerrada sin ninguna OC detrás.
    if valores["estado"] == "OC Emitida":
        return jsonify({"error":"El estado \"OC Emitida\" se asigna solo al emitir la orden de compra"}), 400
    # Las validaciones de tipo/material solo tienen sentido cuando alguno de
    # esos dos campos realmente cambia en este PUT. Si el request solo toca
    # otra cosa (p.ej. cancelar una SC cambiando su estado), no hay que
    # revalidar datos que ya estaban guardados así (incluye SC de servicio
    # generadas automáticamente para operaciones tercerizadas, que son
    # "Productiva" sin material_id).
    if "tipo" in d or "material_id" in d:
        if valores.get("material_id"):
            mat = query("SELECT categoria FROM materiales WHERE id=?", (valores["material_id"],), one=True)
            if not mat or mat["categoria"] not in ("Material", "Insumo", "Herramienta"):
                return jsonify({"error":"Solo se pueden solicitar materiales, insumos o herramientas — un producto terminado no se compra, se fabrica"}), 400
            if valores["tipo"] == "Productiva" and mat["categoria"] != "Material":
                return jsonify({"error":"Una SC productiva solo puede cargar materiales, no insumos ni herramientas"}), 400
            if valores["tipo"] == "Indirecta" and mat["categoria"] not in ("Insumo", "Herramienta"):
                return jsonify({"error":"Una SC indirecta solo puede cargar insumos o herramientas"}), 400
        elif valores["tipo"] == "Productiva" and not (actual["material_id"] is None and (actual["unidad"] or "") == "servicio"):
            return jsonify({"error":"Una SC productiva debe cargar un material"}), 400
    execute("""UPDATE solicitudes_compra SET tipo=?,material_id=?,descripcion=?,cantidad=?,unidad=?,
        urgencia=?,estado=?,ot_origen_id=?,centro_costo=?,obs=? WHERE id=?""",
        (valores["tipo"],valores["material_id"],valores["descripcion"],valores["cantidad"],valores["unidad"],
         valores["urgencia"],valores["estado"],valores["ot_origen_id"],valores["centro_costo"],valores["obs"],sid))
    return jsonify({"ok":True})

# ── Cotizaciones de compra ────────────────────────────────────────────────────
@app.route("/api/cotizaciones_compra", methods=["GET"])
@login_required()
@solo_con_monetario
def get_cotizaciones():
    sid = request.args.get("solicitud_id")
    sql = """SELECT c.*,p.razon proveedor_nombre,s.descripcion solicitud_desc,s.cantidad sol_cantidad,s.unidad sol_unidad,s.tipo solicitud_tipo,s.estado solicitud_estado
        FROM cotizaciones_compra c
        JOIN proveedores p ON p.id=c.proveedor_id
        JOIN solicitudes_compra s ON s.id=c.solicitud_id"""
    rows = query(sql+" WHERE c.solicitud_id=? ORDER BY c.precio_unit",(sid,)) if sid else query(sql+" ORDER BY c.id DESC")
    return jsonify([dict(r) for r in rows])

@app.route("/api/cotizaciones_compra", methods=["POST"])
@login_required(roles=["admin","almacen","vendedor"])
@solo_con_monetario
def create_cotizacion():
    d = request.json
    if not d.get("solicitud_id") or not d.get("proveedor_id") or not d.get("precio_unit"):
        return jsonify({"error":"Solicitud, proveedor y precio requeridos"}), 400
    sol = query("SELECT estado FROM solicitudes_compra WHERE id=?", (d["solicitud_id"],), one=True)
    if not sol:
        return jsonify({"error":"Solicitud de compra no encontrada"}), 404
    if sol["estado"] in ESTADOS_SC_CERRADOS:
        return jsonify({"error":"No se puede cotizar: la solicitud de compra ya completó su circuito"}), 400
    lid = execute("""INSERT INTO cotizaciones_compra
        (solicitud_id,proveedor_id,precio_unit,plazo_entrega_dias,condicion_pago,seleccionada,obs)
        VALUES (?,?,?,?,?,?,?)""",
        (d["solicitud_id"],d["proveedor_id"],d["precio_unit"],d.get("plazo_entrega_dias",3),
         d.get("condicion_pago"),0,d.get("obs")))
    return jsonify({"ok":True,"id":lid}), 201

ESTADOS_SC_CERRADOS = ("OC Emitida", "Cerrada", "Cancelada", "Rechazada")

@app.route("/api/cotizaciones_compra/<int:cid>", methods=["PUT"])
@login_required(roles=["admin","almacen","vendedor"])
@solo_con_monetario
def update_cotizacion(cid):
    cot = query("SELECT * FROM cotizaciones_compra WHERE id=?", (cid,), one=True)
    if not cot: return jsonify({"error":"Cotización no encontrada"}), 404
    sol = query("SELECT estado FROM solicitudes_compra WHERE id=?", (cot["solicitud_id"],), one=True)
    if sol and sol["estado"] in ESTADOS_SC_CERRADOS:
        return jsonify({"error":"No se puede editar: la solicitud de compra ya completó su circuito"}), 400
    d = request.json
    if not d.get("proveedor_id") or not d.get("precio_unit"):
        return jsonify({"error":"Proveedor y precio requeridos"}), 400
    execute("""UPDATE cotizaciones_compra SET proveedor_id=?,precio_unit=?,plazo_entrega_dias=?,
        condicion_pago=?,obs=? WHERE id=?""",
        (d["proveedor_id"],d["precio_unit"],d.get("plazo_entrega_dias",3),
         d.get("condicion_pago"),d.get("obs"),cid))
    return jsonify({"ok":True})

@app.route("/api/cotizaciones_compra/<int:cid>/seleccionar", methods=["POST"])
@login_required(roles=["admin","almacen","vendedor"])
@solo_con_monetario
def seleccionar_cotizacion(cid):
    cot = query("SELECT * FROM cotizaciones_compra WHERE id=?", (cid,), one=True)
    if not cot: return jsonify({"error":"Cotización no encontrada"}), 404
    sol = query("SELECT estado FROM solicitudes_compra WHERE id=?", (cot["solicitud_id"],), one=True)
    if sol and sol["estado"] in ESTADOS_SC_CERRADOS:
        return jsonify({"error":"No se puede seleccionar: la solicitud de compra ya completó su circuito"}), 400
    execute("UPDATE cotizaciones_compra SET seleccionada=0 WHERE solicitud_id=?", (cot["solicitud_id"],))
    execute("UPDATE cotizaciones_compra SET seleccionada=1 WHERE id=?", (cid,))
    execute("UPDATE solicitudes_compra SET estado='Cotizada' WHERE id=?", (cot["solicitud_id"],))
    return jsonify({"ok":True})

@app.route("/api/cotizaciones_compra/<int:cid>/deseleccionar", methods=["POST"])
@login_required(roles=["admin","almacen","vendedor"])
@solo_con_monetario
def deseleccionar_cotizacion(cid):
    cot = query("SELECT * FROM cotizaciones_compra WHERE id=?", (cid,), one=True)
    if not cot: return jsonify({"error":"Cotización no encontrada"}), 404
    sol = query("SELECT estado FROM solicitudes_compra WHERE id=?", (cot["solicitud_id"],), one=True)
    if sol and sol["estado"] in ESTADOS_SC_CERRADOS:
        return jsonify({"error":"No se puede deseleccionar: la solicitud de compra ya completó su circuito"}), 400
    execute("UPDATE cotizaciones_compra SET seleccionada=0 WHERE id=?", (cid,))
    # Si ya se emitió una OC para esta solicitud, no tocamos su estado (ya avanzó
    # más allá de "Cotizada"); si no, la volvemos a "Pendiente" para permitir
    # elegir otra cotización.
    sol = query("SELECT estado FROM solicitudes_compra WHERE id=?", (cot["solicitud_id"],), one=True)
    if sol and sol["estado"] == "Cotizada":
        execute("UPDATE solicitudes_compra SET estado='Pendiente' WHERE id=?", (cot["solicitud_id"],))
    return jsonify({"ok":True})

# ── Órdenes de compra a proveedores ──────────────────────────────────────────
LIMITE_APROBACION = 50000

@app.route("/api/ordenes_compra", methods=["GET"])
@login_required()
def get_ocs():
    sql = """SELECT oc.*,p.razon proveedor_nombre,u.nombre creado_por_nombre,ua.nombre aprobado_por_nombre
        FROM ordenes_compra oc
        JOIN proveedores p ON p.id=oc.proveedor_id
        LEFT JOIN usuarios u ON u.id=oc.creado_por
        LEFT JOIN usuarios ua ON ua.id=oc.aprobado_por"""
    rows = query(sql+" ORDER BY oc.id DESC")
    result = []
    for r in rows:
        d = dict(r)
        d["items"] = [dict(x) for x in query("""SELECT i.*,m.descripcion mat_desc,m.codigo mat_codigo,
            s.numero sc_numero,s.tipo sc_tipo,s.ott_id sc_ott_id,tt.numero ott_numero,
            c.condicion_pago cot_condicion_pago,c.plazo_entrega_dias cot_plazo_entrega_dias,
            l.cantidad_rechazada lote_cantidad_rechazada
            FROM ordenes_compra_items i LEFT JOIN materiales m ON m.id=i.material_id
            LEFT JOIN solicitudes_compra s ON s.id=i.solicitud_id
            LEFT JOIN ordenes_tercerizado tt ON tt.id=s.ott_id
            LEFT JOIN cotizaciones_compra c ON c.solicitud_id=i.solicitud_id AND c.seleccionada=1
            LEFT JOIN lotes l ON l.id=i.lote_id
            WHERE i.oc_id=?""", (r["id"],))]
        # Total de piezas rechazadas (clasificadas por Calidad en los lotes de
        # esta OC) que todavía no se devolvieron al proveedor — ver
        # oc_devolver_rechazo. Se usa para mostrar el botón "Devolver piezas".
        d["rechazado_pendiente_devolver"] = round(sum(
            max(0.0, float(i.get("lote_cantidad_rechazada") or 0))
            for i in d["items"]), 6)
        result.append(d)
    return jsonify(result)

@app.route("/api/ordenes_compra/proveedor/<int:pid>", methods=["GET"])
@login_required()
def get_ocs_by_proveedor(pid):
    """Obtiene el historial de órdenes de compra de un proveedor específico"""
    sql = """SELECT oc.*,p.razon proveedor_nombre,u.nombre creado_por_nombre,ua.nombre aprobado_por_nombre
        FROM ordenes_compra oc
        JOIN proveedores p ON p.id=oc.proveedor_id
        LEFT JOIN usuarios u ON u.id=oc.creado_por
        LEFT JOIN usuarios ua ON ua.id=oc.aprobado_por
        WHERE oc.proveedor_id=?"""
    rows = query(sql, (pid,), )
    result = []
    for r in rows:
        d = dict(r)
        d["items"] = [dict(x) for x in query("""SELECT i.*,m.descripcion mat_desc,m.codigo mat_codigo,
            s.numero sc_numero,s.tipo sc_tipo,s.ott_id sc_ott_id,tt.numero ott_numero,
            c.condicion_pago cot_condicion_pago,c.plazo_entrega_dias cot_plazo_entrega_dias
            FROM ordenes_compra_items i LEFT JOIN materiales m ON m.id=i.material_id
            LEFT JOIN solicitudes_compra s ON s.id=i.solicitud_id
            LEFT JOIN ordenes_tercerizado tt ON tt.id=s.ott_id
            LEFT JOIN cotizaciones_compra c ON c.solicitud_id=i.solicitud_id AND c.seleccionada=1
            WHERE i.oc_id=?""", (r["id"],))]
        result.append(d)
    return jsonify(result)

@app.route("/api/ordenes_compra", methods=["POST"])
@login_required(roles=["admin","almacen","vendedor"])
@solo_con_monetario
def create_oc():
    d = request.json
    if not d.get("proveedor_id") or not d.get("items"): return jsonify({"error":"Proveedor e ítems requeridos"}), 400
    # ── Una OC puede juntar varias SC (1 a N) en una sola orden, siempre que
    # todas tengan cotización seleccionada con el MISMO proveedor que la OC
    # (una OC va a un solo proveedor). También se revalida que la SC siga
    # disponible para comprar (evita doble-compra si dos personas abrieron el
    # modal al mismo tiempo). La generación de lotes sigue siendo por ítem
    # (ver el loop de abajo), así que aunque se agrupen varias SC en una
    # misma OC, cada una termina con su propio lote independiente. ──────────
    for item in d["items"]:
        if item.get("material_id"):
            mat = query("SELECT categoria FROM materiales WHERE id=?", (item["material_id"],), one=True)
            if mat and mat["categoria"] == "Producto terminado":
                return jsonify({"error": f"No se puede comprar \"{item.get('descripcion','')}\": es un producto terminado, no se compra, se fabrica (generá la OT correspondiente)."}), 400
        if item.get("solicitud_id"):
            sol = query("SELECT estado FROM solicitudes_compra WHERE id=?", (item["solicitud_id"],), one=True)
            if not sol:
                return jsonify({"error": "Solicitud de compra no encontrada"}), 404
            if sol["estado"] in ("OC Emitida","Cerrada","Cancelada","Rechazada"):
                return jsonify({"error": f"No se puede emitir la OC: la solicitud de compra ya no está disponible (estado: {sol['estado']})"}), 400
            cot = query("""SELECT id,proveedor_id FROM cotizaciones_compra
                WHERE solicitud_id=? AND seleccionada=1""", (item["solicitud_id"],), one=True)
            if not cot:
                return jsonify({"error":"No se puede emitir la OC: la solicitud de compra no tiene una cotización seleccionada"}), 400
            if int(cot["proveedor_id"]) != int(d["proveedor_id"]):
                return jsonify({"error":"No se puede emitir la OC: todas las solicitudes deben tener su cotización seleccionada con el mismo proveedor de la OC"}), 400
    numero = next_numero_oc()
    total = sum(float(i.get("precio_unit",0))*float(i.get("cantidad",0)) for i in d["items"])
    estado = "Aprobada" if total <= LIMITE_APROBACION else "Pendiente aprobacion"
    # v147 (punto 9): una OC generada por una OTT obtiene autorización automática
    # si el precio de TODOS sus ítems coincide con la lista de precios del
    # proveedor; si no coincide, queda pendiente de aprobación (aunque no
    # supere el límite).
    items_ott = [i for i in d["items"] if i.get("solicitud_id") and
                 query("SELECT ott_id FROM solicitudes_compra WHERE id=?", (i["solicitud_id"],), one=True)["ott_id"]]
    if items_ott:
        todos_ok = True
        for i in items_ott:
            lp = query("SELECT precio_unit FROM proveedor_materiales WHERE proveedor_id=? AND material_id=?",
                       (d["proveedor_id"], i.get("material_id")), one=True)
            if not lp or abs(float(lp["precio_unit"] or 0) - float(i.get("precio_unit", 0))) > 0.005:
                todos_ok = False; break
        # La aprobación automática por lista de precios vale solo si TODOS los
        # ítems son de OTT. Antes bastaba un ítem de OTT para que la OC
        # entera salteara el límite, con cualquier otro ítem de cualquier
        # importe. Si hay ítems comunes rige el límite, y un precio de OTT que
        # no coincide con la lista la deja pendiente igual.
        if len(items_ott) == len(d["items"]):
            estado = "Aprobada" if todos_ok else "Pendiente aprobacion"
        elif not todos_ok:
            estado = "Pendiente aprobacion"
    lid = execute("""INSERT INTO ordenes_compra
        (numero,proveedor_id,estado,monto_total,fecha_entrega_est,obs,creado_por)
        VALUES (?,?,?,?,?,?,?)""",
        (numero,d["proveedor_id"],estado,total,d.get("fecha_entrega_est"),d.get("obs"),session["user_id"]))
    lotes_creados = []
    for item in d["items"]:
        oci_id = execute("""INSERT INTO ordenes_compra_items
            (oc_id,solicitud_id,material_id,descripcion,cantidad,precio_unit,unidad)
            VALUES (?,?,?,?,?,?,?)""",
            (lid,item.get("solicitud_id"),item.get("material_id"),item["descripcion"],
             item["cantidad"],item["precio_unit"],item.get("unidad")))
        _sync_requerimiento_desde_compra(oci_id)
        if item.get("solicitud_id"):
            execute("UPDATE solicitudes_compra SET estado='OC Emitida' WHERE id=?", (item["solicitud_id"],))
            sc = query("SELECT material_id FROM solicitudes_compra WHERE id=?", (item["solicitud_id"],), one=True)
            if sc and sc["material_id"]:
                auto_generar_sc_bajo_stock(sc["material_id"], f"OC {numero} emitida para SC")
        # ── Al EMITIR la OC se crea de una el Lote de ese ítem (en 0), en
        # estado "Ingresado", ya vinculado al ítem. El lote NO arranca con la
        # cantidad pedida: solo va a reflejar lo que efectivamente vaya
        # llegando (ver recibir_oc), para no dar por planificable algo que
        # todavía no entró físicamente a planta.
        _es_ott_item = bool(item.get("solicitud_id") and
            query("SELECT ott_id FROM solicitudes_compra WHERE id=?", (item["solicitud_id"],), one=True)["ott_id"])
        if item.get("material_id") and not _es_ott_item:
            # (los ítems de OTT no crean lote acá: el lote lo genera la recepción del remito en Terceros)
            mat_cat = query("SELECT categoria FROM materiales WHERE id=?", (item["material_id"],), one=True)
            if mat_cat and mat_cat["categoria"] in ("Material", "Producto terminado"):
                numero_lote = _gen_lote_numero()
                lote_id = execute("""INSERT INTO lotes
                    (numero,material_id,cantidad_original,cantidad_disponible,cantidad_activa,
                     proveedor_id,referencia_proveedor,estado,creado_por)
                    VALUES (?,?,?,?,?,?,?,?,?)""",
                    (numero_lote, item["material_id"], 0, 0, 0,
                     d["proveedor_id"], f"OC {numero}", "Ingresado", session["user_id"]))
                lotes_creados.append(numero_lote)
                execute("UPDATE ordenes_compra_items SET lote_id=? WHERE oc_id=? AND material_id=? AND lote_id IS NULL",
                    (lote_id, lid, item["material_id"]))
    for _i in items_ott:
        _o = query("SELECT ott_id FROM solicitudes_compra WHERE id=?", (_i["solicitud_id"],), one=True)
        if _o and _o["ott_id"]:
            _ott_sync_oc_recibido(_o["ott_id"])
            _sync_requerimiento_desde_ott(_o["ott_id"])
    return jsonify({"ok":True,"id":lid,"numero":numero,"estado":estado,"total":total,"lotes":lotes_creados}), 201

def _estado_recepcion_oc(items):
    """'Recibida' si TODOS los renglones llegaron completos, 'Recibida parcial'
    si llegó algo, None si nada. Se mira renglón por renglón: antes se
    comparaban totales y 20 recibidos de un renglón de 10 dejaban la OC como
    'Recibida' con otro renglón de 10 sin recibir."""
    items = list(items)
    if not items:
        return None
    if all(float(i["cantidad_recibida"] or 0) >= float(i["cantidad"] or 0) - 0.0001 for i in items):
        return "Recibida"
    if any(float(i["cantidad_recibida"] or 0) > 0.0001 for i in items):
        return "Recibida parcial"
    return None


def _ott_sync_oc_recibido(ott_id):
    """v147: reparte lo recibido de una OTT (ordenes_tercerizado.cantidad_recibida)
    entre los ítems de OC vinculados a ella (vía solicitudes_compra.ott_id) y
    recalcula el estado de esas OC. Idempotente."""
    ott = query("SELECT cantidad_recibida FROM ordenes_tercerizado WHERE id=?", (ott_id,), one=True)
    if not ott: return
    restante = float(ott["cantidad_recibida"] or 0)
    items = query("""SELECT i.id,i.cantidad,i.oc_id,oc.estado FROM ordenes_compra_items i
        JOIN solicitudes_compra s ON s.id=i.solicitud_id
        JOIN ordenes_compra oc ON oc.id=i.oc_id
        WHERE s.ott_id=? AND oc.estado!='Anulada' ORDER BY i.id""", (ott_id,))
    ocs = set()
    for it in items:
        asignar = max(0.0, min(float(it["cantidad"] or 0), restante))
        execute("UPDATE ordenes_compra_items SET cantidad_recibida=? WHERE id=?", (asignar, it["id"]))
        restante -= asignar
        ocs.add(it["oc_id"])
    for ocid in ocs:
        oc = query("SELECT estado FROM ordenes_compra WHERE id=?", (ocid,), one=True)
        if not oc or oc["estado"] in ("Pendiente aprobacion", "Completada", "Anulada", "Cerrada"):
            continue
        estado_rec = _estado_recepcion_oc(query(
            "SELECT cantidad,cantidad_recibida FROM ordenes_compra_items WHERE oc_id=?", (ocid,)))
        if estado_rec:
            execute("UPDATE ordenes_compra SET estado=? WHERE id=?", (estado_rec, ocid))

def _gen_recepcion_numero():
    """Genera número de recepción correlativo por año: REC-2026-0001"""
    return siguiente_numero("recepciones", f"REC-{datetime.now().year}-", 4)

@app.route("/api/recepciones", methods=["GET"])
@login_required()
def get_recepciones():
    """Todo lo que ENTRA por Recepción directa, OC (Compras) y OTT
    (retorno de terceros) — las salidas de stock no se listan acá."""
    result = []

    directas = query("""SELECT r.*, m.codigo AS mat_codigo, m.descripcion AS mat_descripcion,
        m.unidad AS mat_unidad, m.categoria AS mat_categoria,
        p.razon AS proveedor_nombre, l.numero AS lote_numero, l.estado AS lote_estado,
        u.username AS usuario
        FROM recepciones r
        JOIN materiales m ON m.id=r.material_id
        LEFT JOIN proveedores p ON p.id=r.proveedor_id
        LEFT JOIN lotes l ON l.id=r.lote_id
        LEFT JOIN usuarios u ON u.id=r.creado_por
        ORDER BY r.id DESC""")
    for r in directas:
        d = dict(r)
        d["origen"] = "Directa"
        result.append(d)

    # ── OC (Compras): movimientos generados al Recibir una Orden de Compra
    # (ver recibir_oc). No hay tabla propia para esto — se identifica por el
    # prefijo fijo de referencia que usa ese endpoint. ──────────────────────
    oc_movs = query("""SELECT mv.id,mv.fecha,mv.cantidad,mv.referencia,mv.lote_id,
        m.codigo AS mat_codigo, m.descripcion AS mat_descripcion, m.unidad AS mat_unidad,
        m.categoria AS mat_categoria, l.numero AS lote_numero, l.estado AS lote_estado,
        u.username AS usuario
        FROM movimientos mv
        JOIN materiales m ON m.id=mv.material_id
        LEFT JOIN lotes l ON l.id=mv.lote_id
        LEFT JOIN usuarios u ON u.id=mv.usuario_id
        WHERE mv.tipo IN ('recepcion','entrada') AND mv.referencia LIKE 'Recep. %'
        ORDER BY mv.id DESC""")
    for mv in oc_movs:
        d = dict(mv)
        oc_numero = d["referencia"][len("Recep. "):].split(" · ")[0].strip()
        d["remito"] = d["referencia"].split(" · Remito ", 1)[1].strip() if " · Remito " in d["referencia"] else None
        oc = query("""SELECT oc.numero,pv.razon AS proveedor_nombre
            FROM ordenes_compra oc LEFT JOIN proveedores pv ON pv.id=oc.proveedor_id
            WHERE oc.numero=?""", (oc_numero,), one=True)
        d["numero"] = oc_numero
        d["proveedor_nombre"] = oc["proveedor_nombre"] if oc else None
        d["precio_unit"] = None
        d["origen"] = "OC"
        result.append(d)

    # ── OTT (Terceros): retornos de operaciones intermedias con lote (ver
    # ott_registrar_retorno). El retorno del ÚLTIMO nivel (PT → cliente) no
    # genera lote/movimiento — se ve reflejado directo en la OT, no acá. ────
    ott_movs = query("""SELECT mv.id,mv.fecha,mv.cantidad,mv.referencia,mv.lote_id,
        m.codigo AS mat_codigo, m.descripcion AS mat_descripcion, m.unidad AS mat_unidad,
        m.categoria AS mat_categoria, l.numero AS lote_numero, l.estado AS lote_estado,
        u.username AS usuario
        FROM movimientos mv
        JOIN materiales m ON m.id=mv.material_id
        LEFT JOIN lotes l ON l.id=mv.lote_id
        LEFT JOIN usuarios u ON u.id=mv.usuario_id
        WHERE mv.tipo='ingreso' AND mv.referencia LIKE 'Retorno OTT %'
        ORDER BY mv.id DESC""")
    for mv in ott_movs:
        d = dict(mv)
        ott_numero = d["referencia"][len("Retorno OTT "):].split(" (")[0].strip()
        d["remito"] = d["referencia"].split(" · Remito ", 1)[1].strip() if " · Remito " in d["referencia"] else None
        ott = query("""SELECT ott.numero,pv.razon AS proveedor_nombre
            FROM ordenes_tercerizado ott LEFT JOIN proveedores pv ON pv.id=ott.proveedor_id
            WHERE ott.numero=?""", (ott_numero,), one=True)
        d["numero"] = ott_numero
        d["proveedor_nombre"] = ott["proveedor_nombre"] if ott else None
        d["precio_unit"] = None
        d["origen"] = "OTT"
        result.append(d)

    result.sort(key=lambda x: x.get("fecha") or "", reverse=True)
    return jsonify(result)

@app.route("/api/recepciones", methods=["POST"])
@login_required(roles=["admin","almacen"])
def create_recepcion():
    """Registra el ingreso físico de material/insumo a planta, independiente
    de cualquier Orden de Compra. Reutiliza la misma lógica de lotes/stock
    que antes solo se disparaba al recibir una OC (ver recibir_oc):
    Material/Producto terminado generan (o hacen crecer) un lote pendiente
    de aprobación de Calidad; el resto de categorías suma directo a stock."""
    d = request.json
    if not d.get("material_id"): return jsonify({"error":"Material requerido"}), 400
    try:
        qty = float(d.get("cantidad", 0))
    except (TypeError, ValueError):
        return jsonify({"error":"Cantidad inválida"}), 400
    if qty <= 0: return jsonify({"error":"La cantidad debe ser mayor a 0"}), 400
    mat = query("SELECT * FROM materiales WHERE id=?", (d["material_id"],), one=True)
    if not mat: return jsonify({"error":"Material no encontrado"}), 404
    # ── Si hay una OC abierta (no anulada/cerrada/completada) con saldo
    # pendiente de este material (y de este proveedor, si se indicó), lo
    # normal es recibirla desde "Recibir OC": una recepción directa no
    # descuenta el saldo de la OC y el material termina contado dos veces
    # (una acá y otra cuando se reciba la OC). Se avisa con 409 y se pide
    # confirmación explícita (confirmar_sin_oc) para seguir sin OC. Los ítems
    # de OTT no cuentan: se reciben desde Terceros. ─────────────────────────
    if not d.get("confirmar_sin_oc"):
        _filtro_prov = " AND oc.proveedor_id=?" if d.get("proveedor_id") else ""
        _params = (mat["id"], d["proveedor_id"]) if d.get("proveedor_id") else (mat["id"],)
        ocs_abiertas = [dict(r) for r in query(f"""SELECT oc.id, oc.numero, oc.estado,
                pv.razon AS proveedor_nombre,
                SUM(MAX(0, i.cantidad - COALESCE(i.cantidad_recibida,0))) AS saldo
            FROM ordenes_compra_items i
            JOIN ordenes_compra oc ON oc.id=i.oc_id
            LEFT JOIN proveedores pv ON pv.id=oc.proveedor_id
            LEFT JOIN solicitudes_compra s ON s.id=i.solicitud_id
            WHERE i.material_id=? AND oc.estado NOT IN ('Anulada','Cerrada','Completada')
              AND i.cantidad - COALESCE(i.cantidad_recibida,0) > 0.0001
              AND s.ott_id IS NULL{_filtro_prov}
            GROUP BY oc.id ORDER BY oc.id""", _params)]
        if ocs_abiertas:
            detalle = ", ".join(f"{o['numero']} ({o['proveedor_nombre'] or 'sin proveedor'}, "
                                f"saldo {round(o['saldo'], 3):g}, {o['estado']})" for o in ocs_abiertas)
            return jsonify({"error": f"¿Registrar igual como recepción sin OC?\n"
                                     f"Hay OC abiertas con saldo pendiente de {mat['codigo']}: {detalle}. "
                                     f"Si esta mercadería corresponde a una de ellas, cancelá y usá "
                                     f"\"Recibir OC\" en Compras para que se descuente del saldo.",
                            "requiere_confirmacion": True,
                            "ocs_abiertas": ocs_abiertas}), 409
    precio_unit = d.get("precio_unit")
    try: precio_unit = float(precio_unit) if precio_unit not in (None,"") else None
    except (TypeError, ValueError): precio_unit = None
    numero = _gen_recepcion_numero()
    lote_id = None
    if mat["categoria"] in ("Material", "Producto terminado"):
        numero_lote = _gen_lote_numero()
        lote_id = execute("""INSERT INTO lotes
            (numero,material_id,cantidad_original,cantidad_disponible,cantidad_activa,
             proveedor_id,referencia_proveedor,estado,obs,creado_por,stock_computado)
            VALUES (?,?,?,?,?,?,?,?,?,?,1)""",
            (numero_lote, mat["id"], qty, qty, 0,
             d.get("proveedor_id"), d.get("remito"), "Ingresado", d.get("obs"), session["user_id"]))
        # La mercadería entró al depósito: entra a inventario, la apruebe
        # Calidad o no.
        execute("""UPDATE materiales SET stock=stock+?, actualizado=datetime('now','localtime')
            WHERE id=?""", (qty, mat["id"]))
        execute("""INSERT INTO movimientos (material_id,lote_id,tipo,cantidad,referencia,usuario_id)
            VALUES (?,?,?,?,?,?)""",
            (mat["id"], lote_id, "recepcion", qty, f"Recepción {numero}", session["user_id"]))
    else:
        execute("UPDATE materiales SET stock=stock+?,actualizado=datetime('now','localtime') WHERE id=?", (qty, mat["id"]))
        execute("""INSERT INTO movimientos (material_id,lote_id,tipo,cantidad,referencia,usuario_id)
            VALUES (?,?,?,?,?,?)""",
            (mat["id"], None, "entrada", qty, f"Recepción {numero}", session["user_id"]))
    rid = execute("""INSERT INTO recepciones
        (numero,material_id,cantidad,proveedor_id,remito,precio_unit,lote_id,obs,creado_por)
        VALUES (?,?,?,?,?,?,?,?,?)""",
        (numero, mat["id"], qty, d.get("proveedor_id"), d.get("remito"), precio_unit,
         lote_id, d.get("obs"), session["user_id"]))
    if precio_unit is not None and precio_unit > 0 and d.get("proveedor_id"):
        execute("""INSERT OR REPLACE INTO proveedor_materiales (proveedor_id,material_id,precio_unit,plazo_dias,es_principal)
            VALUES (?,?,?,COALESCE((SELECT plazo_dias FROM proveedor_materiales WHERE proveedor_id=? AND material_id=?),3),
            COALESCE((SELECT es_principal FROM proveedor_materiales WHERE proveedor_id=? AND material_id=?),0))""",
            (d["proveedor_id"], mat["id"], precio_unit, d["proveedor_id"], mat["id"], d["proveedor_id"], mat["id"]))
    lote_num = query("SELECT numero FROM lotes WHERE id=?", (lote_id,), one=True) if lote_id else None
    return jsonify({"ok":True,"id":rid,"numero":numero,"lote":lote_id,
                    "lote_numero":lote_num["numero"] if lote_num else None,
                    "capacidad_cajon":mat["capacidad_cajon"] if "capacidad_cajon" in mat.keys() else None}), 201

@app.route("/api/ordenes_compra/<int:ocid>/aprobar", methods=["POST"])
@login_required(roles=["admin","vendedor"])
def aprobar_oc(ocid):
    oc = query("SELECT estado FROM ordenes_compra WHERE id=?", (ocid,), one=True)
    if not oc: return jsonify({"error":"OC no encontrada"}), 404
    if oc["estado"] not in ("Borrador", "Pendiente aprobacion"):
        return jsonify({"error": f"No se puede aprobar una OC en estado \"{oc['estado']}\""}), 400
    execute("UPDATE ordenes_compra SET estado='Aprobada',aprobado_por=?,fecha_aprobacion=datetime('now','localtime') WHERE id=?",
        (session["user_id"], ocid))
    return jsonify({"ok":True})

@app.route("/api/ordenes_compra/<int:ocid>/recibir", methods=["POST"])
@login_required(roles=["admin","almacen","vendedor"])
def recibir_oc(ocid):
    d = request.json or {}
    recepciones = d.get("items", [])
    # ── Validaciones ANTES de grabar nada ─────────────────────────────────
    # Solo se recibe una OC aprobada (o ya en recepción / cerrada por saldo
    # que finalmente llega). Antes se podía recibir una OC pendiente de
    # aprobación (salteando la aprobación), una anulada o una completada, y
    # cantidades negativas.
    oc_chk = query("SELECT estado FROM ordenes_compra WHERE id=?", (ocid,), one=True)
    if not oc_chk: return jsonify({"error":"OC no encontrada"}), 404
    if oc_chk["estado"] not in ("Aprobada", "Enviada", "Recibida parcial", "Recibida", "Cerrada"):
        return jsonify({"error": f"No se puede recibir una OC en estado \"{oc_chk['estado']}\""
                                  + (" — primero tiene que aprobarse" if oc_chk["estado"] in ("Borrador", "Pendiente aprobacion") else "")}), 400
    for recv in recepciones:
        item = query("SELECT * FROM ordenes_compra_items WHERE id=? AND oc_id=?", (recv.get("item_id"), ocid), one=True)
        if not item:
            return jsonify({"error":"Ítem de OC no encontrado en esta OC"}), 400
        try:
            qty_chk = float(recv.get("cantidad", 0))
        except (TypeError, ValueError):
            return jsonify({"error":"Cantidad inválida"}), 400
        if qty_chk <= 0:
            return jsonify({"error":"La cantidad recibida debe ser mayor a 0"}), 400
        if item["solicitud_id"]:
            _sc_ott = query("SELECT ott_id FROM solicitudes_compra WHERE id=?", (item["solicitud_id"],), one=True)
            if _sc_ott and _sc_ott["ott_id"]:
                return jsonify({"error": "Los ítems de una OC generada por una OTT se reciben desde Recepción → Pendientes de retorno — Terceros (OTT), cargando el remito."}), 400
    for recv in recepciones:
        item = query("SELECT * FROM ordenes_compra_items WHERE id=?", (recv["item_id"],), one=True)
        qty = float(recv.get("cantidad",0))
        # ── Se puede recibir una cantidad distinta a la pedida (de más o de
        # menos). Si además viene un precio_unit distinto al cargado en la
        # OC, lo actualizamos: es común que el proveedor ajuste el precio
        # cuando la cantidad finalmente entregada no coincide con la
        # pedida. El monto_total de la OC se recalcula abajo en base a estos
        # valores actualizados. ─────────────────────────────────────────────
        nuevo_precio = recv.get("precio_unit")
        if nuevo_precio is not None:
            try: nuevo_precio = float(nuevo_precio)
            except (TypeError, ValueError): nuevo_precio = None
        if nuevo_precio is not None and abs(nuevo_precio - float(item["precio_unit"])) > 0.0001:
            execute("UPDATE ordenes_compra_items SET precio_unit=? WHERE id=?", (nuevo_precio, recv["item_id"]))
        # fecha_recibida alimenta la fecha de entrega del requerimiento
        # productivo (ver _sync_requerimiento_desde_compra); antes no se
        # grababa nunca y todas las compras figuraban sin entregar.
        execute("""UPDATE ordenes_compra_items SET cantidad_recibida=cantidad_recibida+?,
            fecha_recibida=datetime('now','localtime') WHERE id=?""", (qty, recv["item_id"]))
        if item["material_id"]:
            mat_cat = query("SELECT categoria FROM materiales WHERE id=?", (item["material_id"],), one=True)
            oc = query("SELECT numero, proveedor_id FROM ordenes_compra WHERE id=?", (ocid,), one=True)
            if mat_cat and mat_cat["categoria"] in ("Material", "Producto terminado") and not item["lote_id"]:
                # ── Ítem sin lote (OC vieja, o ítem que al emitirse no creó
                # lote): se crea acá, igual que en create_oc (en 0,
                # 'Ingresado'), se vincula al ítem y sigue el flujo normal.
                # Sin esto la mercadería se recibía sin lote y sin sumar a
                # stock. ──────────────────────────────────────────────────
                numero_lote = _gen_lote_numero()
                lote_id = execute("""INSERT INTO lotes
                    (numero,material_id,cantidad_original,cantidad_disponible,cantidad_activa,
                     proveedor_id,referencia_proveedor,estado,creado_por)
                    VALUES (?,?,?,?,?,?,?,?,?)""",
                    (numero_lote, item["material_id"], 0, 0, 0,
                     oc["proveedor_id"], f"OC {oc['numero']}", "Ingresado", session["user_id"]))
                execute("UPDATE ordenes_compra_items SET lote_id=? WHERE id=?", (lote_id, item["id"]))
                item = dict(item)
                item["lote_id"] = lote_id
            if mat_cat and mat_cat["categoria"] in ("Material", "Producto terminado"):
                # ── El Lote de este ítem se creó al EMITIR la OC (ver
                # create_oc), en 0. Acá va creciendo con lo que efectivamente
                # se recibe en cada entrega — sea igual, menor o mayor a lo
                # pedido — para que siempre refleje la mercadería real que
                # entró a planta, pendiente de aprobación de Calidad. Si más
                # adelante llega el saldo faltante, el lote vuelve a crecer
                # con esa entrega tardía. ──────────────────────────────────
                # Primero se separa la porción de esta recepción que en
                # realidad es el REINGRESO de un reemplazo por piezas
                # rechazadas y devueltas al proveedor (ver
                # oc_devolver_rechazo): esa porción no crea crecimiento nuevo
                # del lote, vuelve al mismo lote como cantidad_disponible
                # directamente (ver bloque siguiente). El resto de la
                # recepción sí hace crecer el lote.
                devuelto = float(item["cantidad_rechazada_devuelta"] or 0)
                reingresado_previo = float(item["cantidad_rechazada_reingresada"] or 0)
                pendiente_reingreso = max(0.0, devuelto - reingresado_previo)
                a_reingresar = min(qty, pendiente_reingreso)
                crecimiento = qty - a_reingresar
                if crecimiento > 0.0001 and item["lote_id"]:
                    execute("""UPDATE lotes SET cantidad_original=cantidad_original+?,
                        cantidad_disponible=cantidad_disponible+?, stock_computado=1
                        WHERE id=?""",
                        (crecimiento, crecimiento, item["lote_id"]))
                    execute("""UPDATE materiales SET stock=stock+?,
                        actualizado=datetime('now','localtime') WHERE id=?""",
                        (crecimiento, item["material_id"]))
                    # (el movimiento de esta recepción se registra una sola
                    # vez más abajo, ya con el lote — antes se grababan dos)
                # ── Reingreso de piezas devueltas por rechazo: si este ítem
                # tuvo alguna devolución a proveedor (ver oc_devolver_rechazo),
                # lo que ahora llega como reemplazo NO forma un lote nuevo:
                # vuelve al MISMO lote de origen, sumándose a cantidad_disponible
                # como "Ingresado" (pendiente de que Calidad lo vuelva a
                # clasificar), igual que si fuera la primera recepción. Se
                # reingresa como máximo lo que efectivamente se devolvió y aún
                # no fue repuesto (cantidad_rechazada_devuelta menos lo ya
                # reingresado en entregas anteriores del reemplazo). ──────────
                # Si el lote ya computa a stock (stock_computado=1), las piezas
                # de reemplazo entran a inventario ahora, igual que cualquier
                # recepción: la devolución las descontó y Calidad no vuelve a
                # sumarlas al aprobarlas. Los lotes viejos (stock_computado=0)
                # siguen como antes: el stock lo mueve Calidad al aprobar.
                if a_reingresar > 0.0001 and item["lote_id"]:
                    _reing_computa = _lote_stock_computado(item["lote_id"])
                    execute("""UPDATE lotes SET cantidad_disponible=cantidad_disponible+?,
                        estado=CASE WHEN estado IN ('Aprobado','Rechazado') THEN 'Ingresado' ELSE estado END
                        WHERE id=?""", (a_reingresar, item["lote_id"]))
                    if _reing_computa:
                        execute("""UPDATE materiales SET stock=stock+?,
                            actualizado=datetime('now','localtime') WHERE id=?""",
                            (a_reingresar, item["material_id"]))
                    execute("""UPDATE ordenes_compra_items SET
                        cantidad_rechazada_reingresada=? WHERE id=?""",
                        (reingresado_previo + a_reingresar, item["id"]))
                    execute("""INSERT INTO movimientos (material_id,lote_id,tipo,cantidad,referencia,usuario_id)
                        VALUES (?,?,?,?,?,?)""",
                        (item["material_id"], item["lote_id"], "ingreso", a_reingresar,
                         f"OC {oc['numero']} — reingreso al mismo lote de reemplazo por piezas rechazadas "
                         + ("(pendiente de aprobación de Calidad, suma a stock)" if _reing_computa
                            else "(pendiente de aprobación de Calidad, no computa a stock)"),
                         session["user_id"]))
            else:
                # Otras categorías (Insumo, Herramienta) no pasan por control
                # de Calidad ni manejan lote: se suman directo, por la
                # cantidad efectivamente recibida (pueda ser más o menos que
                # lo pedido).
                execute("UPDATE materiales SET stock=stock+?,actualizado=datetime('now','localtime') WHERE id=?", (qty, item["material_id"]))
            _es_lote = bool(mat_cat and mat_cat["categoria"] in ("Material","Producto terminado"))
            _qty_mov = (qty - a_reingresar) if _es_lote else qty
            if _qty_mov > 0.0001:
              execute("INSERT INTO movimientos (material_id,lote_id,tipo,cantidad,referencia,usuario_id) VALUES (?,?,?,?,?,?)",
                (item["material_id"], item["lote_id"] if _es_lote else None,
                 "recepcion" if _es_lote else "entrada",
                 _qty_mov, f"Recep. {oc['numero']}" + (f" · Remito {d.get('remito')}" if d.get("remito") else ""), session["user_id"]))
    items = query("SELECT cantidad,cantidad_recibida,precio_unit FROM ordenes_compra_items WHERE oc_id=?", (ocid,))
    # ── Monto total de la OC: por cada ítem, si ya se recibió algo se cobra
    # lo efectivamente recibido a su precio (posiblemente ajustado); lo que
    # todavía está pendiente de recibir se sigue proyectando a cantidad
    # pedida x precio, para que el total refleje lo real sin perder de vista
    # lo que falta entregar. ─────────────────────────────────────────────────
    nuevo_monto = sum(
        (i["cantidad_recibida"] if i["cantidad_recibida"] > 0 else i["cantidad"]) * i["precio_unit"]
        + (max(0.0, i["cantidad"] - i["cantidad_recibida"]) * i["precio_unit"] if i["cantidad_recibida"] > 0 and i["cantidad_recibida"] < i["cantidad"] else 0.0)
        for i in items
    )
    execute("UPDATE ordenes_compra SET monto_total=? WHERE id=?", (nuevo_monto, ocid))
    estado_rec = _estado_recepcion_oc(items)
    if estado_rec: execute("UPDATE ordenes_compra SET estado=? WHERE id=?", (estado_rec, ocid))
    # Los requerimientos espejo se sincronizan recién acá, con el estado de la
    # OC ya recalculado, y los de TODOS sus ítems: una entrega tardía saca a la
    # OC de 'Cerrada' y los ítems que habían quedado ANULADO por el cierre
    # vuelven a estar pendientes.
    for i in query("SELECT id FROM ordenes_compra_items WHERE oc_id=?", (ocid,)):
        _sync_requerimiento_desde_compra(i["id"])
    # Lotes que entraron en esta recepción, para cargar sus bultos y etiquetas.
    lotes_rec = []
    for recv in recepciones:
        try: q = float(recv.get("cantidad") or 0)
        except (TypeError, ValueError): q = 0
        it = query("""SELECT i.lote_id, l.numero, m.codigo, m.descripcion, m.unidad,
                m.capacidad_cajon, m.codigo_barras
            FROM ordenes_compra_items i JOIN lotes l ON l.id=i.lote_id
            JOIN materiales m ON m.id=i.material_id
            WHERE i.id=? AND i.oc_id=? AND m.categoria IN ('Material','Producto terminado')""",
            (recv.get("item_id"), ocid), one=True)
        if it and q > 0:
            lotes_rec.append({"lote_id": it["lote_id"], "lote_numero": it["numero"], "cantidad": q,
                              "codigo": it["codigo"], "descripcion": it["descripcion"],
                              "unidad": it["unidad"], "capacidad_cajon": it["capacidad_cajon"],
                              "codigo_barras": it["codigo_barras"]})
    oc_num = query("SELECT numero FROM ordenes_compra WHERE id=?", (ocid,), one=True)
    return jsonify({"ok":True,"monto_total":nuevo_monto,"oc_numero":oc_num["numero"] if oc_num else None,
                    "lotes":lotes_rec})

@app.route("/api/ordenes_compra/<int:ocid>/devolver_rechazo", methods=["POST"])
@login_required(roles=["admin","operario","almacen"])
def oc_devolver_rechazo(ocid):
    """Misma lógica que ott_devolver_rechazo (ver ese endpoint) pero aplicada
    a Compras: cada ítem de la OC generó su propio Lote al emitirse la OC
    (ver create_oc, ordenes_compra_items.lote_id), y ese lote es el que
    Calidad clasifica al recibir la mercadería. Acá se recorren TODOS los
    ítems de la OC y se devuelve, de cada uno, lo que esté clasificado como
    Rechazado en su lote y todavía no se haya devuelto antes.

    Efectos por ítem con rechazo pendiente:
    1) Se descuenta del lote lo devuelto (cantidad_disponible y
       cantidad_rechazada bajan); cantidad_activa (aprobado) no se toca.
    2) cantidad_recibida del ítem baja en la misma medida — el proveedor
       vuelve a deber esa cantidad (reemplazo), que al recibirse ingresa al
       MISMO lote (no se crea uno nuevo).
    3) cantidad_rechazada_devuelta del ítem acumula lo devuelto, para no
       devolver dos veces lo mismo si el lote se clasifica de a partes.

    Se emite UN solo remito de devolución (tipo 'devolucion_oc') para toda
    la OC, agrupando lo devuelto de todos sus ítems.
    """
    oc = query("SELECT * FROM ordenes_compra WHERE id=?", (ocid,), one=True)
    if not oc: return jsonify({"error":"OC no encontrada"}), 404

    items = query("""SELECT i.*, l.cantidad_rechazada lote_cantidad_rechazada,
        m.descripcion mat_desc, m.codigo mat_codigo
        FROM ordenes_compra_items i
        LEFT JOIN lotes l ON l.id=i.lote_id
        LEFT JOIN materiales m ON m.id=i.material_id
        WHERE i.oc_id=?""", (ocid,))

    total_devuelto = 0.0
    detalle = []
    items_devueltos = []
    for item in items:
        if not item["lote_id"]:
            continue
        ya_devuelto = float(item["cantidad_rechazada_devuelta"] or 0)
        # Lo rechazado que sigue en planta: cantidad_rechazada del lote ya
        # baja en cada devolución (paso 1); restarle además ya_devuelto lo
        # descontaba dos veces y un segundo rechazo no se podía devolver.
        cantidad = round(float(item["lote_cantidad_rechazada"] or 0), 6)
        if cantidad <= 0.0001:
            continue

        # 1) Descontar del lote lo devuelto (sale físicamente del depósito)
        execute("""UPDATE lotes SET
                cantidad_disponible=MAX(0, cantidad_disponible-?),
                cantidad_rechazada=MAX(0, cantidad_rechazada-?)
            WHERE id=?""", (cantidad, cantidad, item["lote_id"]))
        # Las piezas rechazadas seguían contando en inventario mientras
        # estaban en el depósito. Al volver al proveedor, salen. (Solo para
        # lotes cuyo stock se computó al recibirlos; los anteriores a este
        # modelo nunca habían entrado.)
        if _lote_stock_computado(item["lote_id"]):
            execute("""UPDATE materiales SET stock=MAX(0, stock-?),
                actualizado=datetime('now','localtime') WHERE id=?""",
                (cantidad, item["material_id"]))
        execute("""INSERT INTO movimientos (material_id,lote_id,tipo,cantidad,referencia,usuario_id)
            VALUES (?,?,'salida',?,?,?)""",
            (item["material_id"], item["lote_id"], cantidad,
             f"Devolución a proveedor de piezas rechazadas — OC {oc['numero']} "
             f"({item['mat_codigo'] or item['descripcion']})",
             session["user_id"]))

        # 2) El ítem queda "debiendo" esa cantidad de nuevo del lado del proveedor
        cantidad_recibida_nueva = max(0.0, float(item["cantidad_recibida"] or 0) - cantidad)
        cantidad_rechazada_devuelta_nueva = ya_devuelto + cantidad
        execute("""UPDATE ordenes_compra_items SET
                cantidad_recibida=?, cantidad_rechazada_devuelta=?
            WHERE id=?""", (cantidad_recibida_nueva, cantidad_rechazada_devuelta_nueva, item["id"]))

        total_devuelto += cantidad
        items_devueltos.append(item["id"])
        detalle.append(f"{cantidad:g} x {item['mat_codigo'] or ''} {item['mat_desc'] or item['descripcion']}".strip())

    if total_devuelto <= 0.0001:
        return jsonify({"error":"No hay piezas rechazadas pendientes de devolver para esta OC"}), 400

    d = request.json or {}

    # 3) Remito de devolución al proveedor (uno solo para toda la OC)
    num_rem = siguiente_numero("remitos", "REM-", 4)
    obs_default = f"Devolución a proveedor — piezas rechazadas OC {oc['numero']}: " + "; ".join(detalle)
    rid = execute("""INSERT INTO remitos (numero,cliente_id,fecha,estado,obs,creado_por,tipo,oc_id)
        VALUES (?,NULL,date('now','localtime'),'Emitido',?,?,?,?)""",
        (num_rem, d.get("obs", obs_default), session["user_id"], "devolucion_oc", ocid))

    # 4) Recalcular estado de la OC (si lo recibido bajó, puede volver a
    # "Recibida parcial" para reflejar que hace falta el reemplazo)
    items_post = query("SELECT cantidad,cantidad_recibida FROM ordenes_compra_items WHERE oc_id=?", (ocid,))
    nuevo_estado = oc["estado"]
    if oc["estado"] not in ("Borrador","Pendiente aprobacion"):
        nuevo_estado = _estado_recepcion_oc(items_post) or "Aprobada"

    execute("UPDATE ordenes_compra SET estado=?, remito_devolucion_id=? WHERE id=?",
        (nuevo_estado, rid, ocid))

    # 5) Requerimiento espejo de cada ítem devuelto: lo recibido bajó, así que
    # deja de estar entregado (y si quedó en 0, sin cantidad entregada). Se
    # sincroniza después del paso 4 para que vea el estado nuevo de la OC.
    for item_id in items_devueltos:
        _sync_requerimiento_desde_compra(item_id)

    return jsonify({"ok": True, "cantidad_devuelta": round(total_devuelto, 6), "remito_numero": num_rem,
        "remito_id": rid, "estado": nuevo_estado})

@app.route("/api/ordenes_compra/<int:ocid>/cerrar", methods=["POST"])
@login_required(roles=["admin","almacen","vendedor"])
def cerrar_oc(ocid):
    """Cierre manual de una OC cuando el saldo pendiente (lo que se pidió
    menos lo efectivamente recibido) NO va a llegar más — el proveedor no
    entrega el resto y no tiene sentido seguir esperándolo. Congela la OC en
    'Cerrada' para que deje de listarse como pendiente de recepción (ver
    filtros de MRP/SC), pero NO toca lo ya recibido ni los lotes: el lote
    generado por esta OC queda tal cual con lo que efectivamente ingresó.

    Si más adelante el proveedor manda ese saldo igual (entrega tardía), la
    OC se puede volver a recibir con normalidad: recibir_oc() recalcula el
    estado en base a cantidad_recibida vs cantidad pedida al final de cada
    recepción, así que una nueva recepción saca a la OC de 'Cerrada' sola
    (vuelve a 'Recibida parcial' o 'Recibida' según corresponda) y el lote
    vuelve a crecer con lo que llegue.
    """
    oc = query("SELECT * FROM ordenes_compra WHERE id=?", (ocid,), one=True)
    if not oc: return jsonify({"error":"OC no encontrada"}), 404
    if oc["estado"] not in ("Aprobada","Enviada","Recibida parcial"):
        return jsonify({"error": f"No se puede cerrar una OC en estado \"{oc['estado']}\""}), 400
    execute("UPDATE ordenes_compra SET estado='Cerrada' WHERE id=?", (ocid,))
    # Requerimientos espejo: lo recibido en parte queda entregado (el saldo ya
    # no llega) y lo que no se recibió nada pasa a ANULADO.
    for i in query("SELECT id FROM ordenes_compra_items WHERE oc_id=?", (ocid,)):
        _sync_requerimiento_desde_compra(i["id"])
    return jsonify({"ok":True,"estado":"Cerrada"})

def _oc_tipo(ocid):
    """'Directa' si algún ítem viene de una SC productiva (o material 'Material'),
    'Indirecta' si todos son insumos/herramientas."""
    rows = query("""SELECT s.tipo sc_tipo, m.categoria cat FROM ordenes_compra_items i
        LEFT JOIN solicitudes_compra s ON s.id=i.solicitud_id
        LEFT JOIN materiales m ON m.id=i.material_id WHERE i.oc_id=?""", (ocid,))
    for r in rows:
        if r["sc_tipo"] == "Productiva" or (not r["sc_tipo"] and r["cat"] in ("Material", "Producto terminado", "Semielaborado")):
            return "Directa"
    return "Indirecta"

@app.route("/api/ordenes_compra/<int:ocid>/remitos", methods=["GET"])
@login_required()
def oc_remitos_recibidos(ocid):
    """Remitos del proveedor ya cargados al recibir esta OC (para vincular al completarla)."""
    oc = query("SELECT numero,remito_numero FROM ordenes_compra WHERE id=?", (ocid,), one=True)
    if not oc: return jsonify({"error":"OC no encontrada"}), 404
    remitos = []
    for r in query("SELECT referencia FROM movimientos WHERE referencia LIKE ?", (f"Recep. {oc['numero']}%",)):
        if " · Remito " in (r["referencia"] or ""):
            v = r["referencia"].split(" · Remito ", 1)[1].strip()
            if v and v not in remitos: remitos.append(v)
    # remitos de terceros (OTT) vinculados a los ítems de esta OC
    for t in query("""SELECT DISTINCT tt.numero FROM ordenes_compra_items i
        JOIN solicitudes_compra s ON s.id=i.solicitud_id JOIN ordenes_tercerizado tt ON tt.id=s.ott_id
        WHERE i.oc_id=?""", (ocid,)):
        for r in query("SELECT referencia FROM movimientos WHERE referencia LIKE ?", (f"Retorno OTT {t['numero']}%",)):
            if " · Remito " in (r["referencia"] or ""):
                v = r["referencia"].split(" · Remito ", 1)[1].strip()
                if v and v not in remitos: remitos.append(v)
    return jsonify({"tipo": _oc_tipo(ocid), "remitos": remitos, "remito_numero": oc["remito_numero"]})

@app.route("/api/ordenes_compra/<int:ocid>/anular", methods=["POST"])
@login_required(roles=["admin","almacen","vendedor"])
def anular_oc(ocid):
    """v147 (punto 8): anula una OC (directa o indirecta) que todavía no recibió
    mercadería. Libera las SC (vuelven a 'Cotizada' para poder re-emitir) y
    elimina los lotes vacíos creados al emitir."""
    d = request.json or {}
    oc = query("SELECT * FROM ordenes_compra WHERE id=?", (ocid,), one=True)
    if not oc: return jsonify({"error":"OC no encontrada"}), 404
    if oc["estado"] in ("Anulada","Completada","Recibida","Cerrada"):
        return jsonify({"error": f"No se puede anular una OC en estado \"{oc['estado']}\""}), 400
    items = query("SELECT * FROM ordenes_compra_items WHERE oc_id=?", (ocid,))
    if any(float(i["cantidad_recibida"] or 0) > 0.0001 for i in items):
        return jsonify({"error":"La OC ya tiene mercadería recibida: no se puede anular. Usá 'Completar' o 'Cerrar OC'."}), 400
    for i in items:
        if i["lote_id"]:
            l = query("SELECT cantidad_original FROM lotes WHERE id=?", (i["lote_id"],), one=True)
            mv = query("SELECT COUNT(*) c FROM movimientos WHERE lote_id=?", (i["lote_id"],), one=True)["c"]
            if l and float(l["cantidad_original"] or 0) == 0 and mv == 0:
                execute("UPDATE ordenes_compra_items SET lote_id=NULL WHERE id=?", (i["id"],))
                execute("DELETE FROM lotes WHERE id=?", (i["lote_id"],))
        if i["solicitud_id"]:
            execute("UPDATE solicitudes_compra SET estado='Cotizada' WHERE id=? AND estado='OC Emitida'", (i["solicitud_id"],))
    execute("""UPDATE ordenes_compra SET estado='Anulada',motivo_anulacion=?,fecha_anulada=datetime('now','localtime') WHERE id=?""",
        ((d.get("motivo") or "").strip() or None, ocid))
    # El requerimiento espejo pasa a ANULADO (antes seguía como pendiente).
    for i in items:
        _sync_requerimiento_desde_compra(i["id"])
    # Servicio de una OTT: sin OC, la OTT sale de Requerimientos productivos.
    for _t in query("""SELECT DISTINCT s.ott_id FROM ordenes_compra_items i
            JOIN solicitudes_compra s ON s.id=i.solicitud_id
            WHERE i.oc_id=? AND s.ott_id IS NOT NULL""", (ocid,)):
        _sync_requerimiento_desde_ott(_t["ott_id"])
    return jsonify({"ok":True,"estado":"Anulada"})

@app.route("/api/ordenes_compra/<int:ocid>/completar", methods=["POST"])
@login_required(roles=["admin","almacen","vendedor"])
def completar_oc(ocid):
    """v147 (punto 8): completa una OC. En una OC DIRECTA es obligatorio
    vincular el remito correspondiente; en una indirecta es opcional."""
    d = request.json or {}
    oc = query("SELECT * FROM ordenes_compra WHERE id=?", (ocid,), one=True)
    if not oc: return jsonify({"error":"OC no encontrada"}), 404
    if oc["estado"] not in ("Aprobada","Enviada","Recibida parcial","Recibida","Cerrada"):
        return jsonify({"error": f"No se puede completar una OC en estado \"{oc['estado']}\""}), 400
    tipo = _oc_tipo(ocid)
    remito = (d.get("remito") or "").strip()
    if tipo == "Directa" and not remito:
        return jsonify({"error":"Una OC directa requiere vincular el remito correspondiente para completarse."}), 400
    execute("""UPDATE ordenes_compra SET estado='Completada',remito_numero=?,fecha_completada=datetime('now','localtime') WHERE id=?""",
        (remito or None, ocid))
    # Requerimientos espejo: con la OC completada, lo recibido en parte queda
    # entregado (ver _sync_requerimiento_desde_compra).
    for i in query("SELECT id FROM ordenes_compra_items WHERE oc_id=?", (ocid,)):
        _sync_requerimiento_desde_compra(i["id"])
    return jsonify({"ok":True,"estado":"Completada","tipo":tipo})


# Funciones de otras áreas. Van al final a propósito: así cada módulo ya
# definió todo lo suyo cuando otro lo importa, y no hay problemas de
# importación circular. Se usan recién al atender pedidos.
from .comun import _sc_automaticas_activas, SC_ABIERTAS_SQL
from .requerimientos import (_sync_requerimiento_desde_compra,
    _sync_requerimiento_desde_ott)
from .cajones import _lote_stock_computado
from .lotes import _gen_lote_numero

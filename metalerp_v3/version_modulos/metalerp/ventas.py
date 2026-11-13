"""Clientes, presupuestos, pedidos de cotización, pronósticos de venta y
pedidos de clientes (OC de clientes) con su avance."""
from .nucleo import (_json, _mon_o_actual, app, date, datetime, execute, get_db, jsonify,
    login_required, math, puede_ver_monetario, query, request, session, siguiente_numero)

# ── Clientes ──────────────────────────────────────────────────────────────────
@app.route("/api/clientes", methods=["GET"])
@login_required()
def get_clientes(): return jsonify([dict(r) for r in query("SELECT * FROM clientes ORDER BY razon")])

@app.route("/api/clientes", methods=["POST"])
@login_required(roles=["admin","vendedor"])
def create_cliente():
    d = request.json
    if not d.get("razon") or not d.get("cuit") or not d.get("contacto"): return jsonify({"error":"Razón, CUIT y contacto requeridos"}), 400
    if query("SELECT id FROM clientes WHERE cuit=?", (d["cuit"],), one=True): return jsonify({"error":"CUIT ya registrado"}), 409
    lid = execute("INSERT INTO clientes (razon,cuit,iva,rubro,localidad,direccion,contacto,cargo,telefono,email,categoria,plazo_pago,trabajos,obs) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (d["razon"],d["cuit"],d.get("iva"),d.get("rubro"),d.get("localidad"),d.get("direccion"),d["contacto"],d.get("cargo"),d.get("telefono"),d.get("email"),d.get("categoria","Regular"),d.get("plazo_pago"),d.get("trabajos"),d.get("obs")))
    return jsonify({"ok":True,"id":lid}), 201

@app.route("/api/clientes/<int:cid>", methods=["PUT"])
@login_required(roles=["admin","vendedor"])
def update_cliente(cid):
    d = request.json
    execute("UPDATE clientes SET razon=?,cuit=?,iva=?,rubro=?,localidad=?,direccion=?,contacto=?,cargo=?,telefono=?,email=?,categoria=?,plazo_pago=?,trabajos=?,obs=? WHERE id=?",
        (d["razon"],d["cuit"],d.get("iva"),d.get("rubro"),d.get("localidad"),d.get("direccion"),d["contacto"],d.get("cargo"),d.get("telefono"),d.get("email"),d.get("categoria","Regular"),d.get("plazo_pago"),d.get("trabajos"),d.get("obs"),cid))
    return jsonify({"ok":True})

# ── Presupuestos ──────────────────────────────────────────────────────────────
@app.route("/api/presupuestos", methods=["GET"])
@login_required()
def get_presupuestos():
    return jsonify([dict(r) for r in query("SELECT p.*,c.razon cliente_nombre FROM presupuestos p LEFT JOIN clientes c ON c.id=p.cliente_id ORDER BY p.id DESC")])

@app.route("/api/presupuestos", methods=["POST"])
@login_required(roles=["admin","vendedor"])
def create_presupuesto():
    d = request.json
    if not d.get("cliente_id"): return jsonify({"error":"Cliente requerido"}), 400
    d["descripcion"] = d.get("descripcion") or f"Presupuesto para cliente {d['cliente_id']}"
    numero = siguiente_numero("presupuestos", "PRES-", 3)
    sub = float(d.get("subtotal", 0))
    iva = float(d.get("iva_pct", 21))
    total = float(d.get("total")) if d.get("total") else sub * (1 + iva/100)
    if not sub and total: sub = total / (1 + iva/100)
    lid = execute("INSERT INTO presupuestos (numero,cliente_id,descripcion,items,subtotal,iva_pct,total,validez_dias,estado,obs) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (numero,d.get("cliente_id"),d["descripcion"],d.get("items"),sub,iva,total,d.get("validez_dias",30),d.get("estado","Borrador"),d.get("obs")))
    return jsonify({"ok":True,"id":lid,"numero":numero,"total":total}), 201

PRESUPUESTO_ESTADOS = ("Borrador", "Enviado", "Aprobado", "Rechazado", "Facturado")

@app.route("/api/presupuestos/<int:pid>", methods=["PUT"])
@login_required(roles=["admin","vendedor"])
def update_presupuesto(pid):
    """Edita un presupuesto o solo su estado. 'Facturado' lo cierra: desde ahí
    no se edita ni cambia de estado. Lo que no viene en el payload conserva su
    valor (un usuario sin ver_monetario no manda subtotal)."""
    actual = query("SELECT * FROM presupuestos WHERE id=?", (pid,), one=True)
    if not actual: return jsonify({"error":"Presupuesto no encontrado"}), 404
    if actual["estado"] == "Facturado":
        return jsonify({"error":f"El presupuesto {actual['numero']} está facturado (cerrado): no se puede modificar"}), 400
    d = request.json or {}
    v = dict(actual)
    for k in ("descripcion","cliente_id","subtotal","iva_pct","validez_dias","estado","obs"):
        if k in d: v[k] = d[k]
    if v["estado"] not in PRESUPUESTO_ESTADOS:
        return jsonify({"error":"Estado inválido"}), 400
    if not (v.get("descripcion") or "").strip():
        return jsonify({"error":"Descripción requerida"}), 400
    try:
        sub = float(v.get("subtotal") or 0)
        iva = float(v.get("iva_pct") if v.get("iva_pct") not in ("", None) else 21)
        validez = int(float(v.get("validez_dias") or 30))
    except (TypeError, ValueError):
        return jsonify({"error":"Valores numéricos inválidos"}), 400
    total = sub * (1 + iva/100) if ("subtotal" in d or "iva_pct" in d) else actual["total"]
    execute("UPDATE presupuestos SET descripcion=?,cliente_id=?,subtotal=?,iva_pct=?,total=?,validez_dias=?,estado=?,obs=? WHERE id=?",
        (v["descripcion"], v.get("cliente_id") or None, sub, iva, total, validez, v["estado"], v.get("obs"), pid))
    return jsonify({"ok":True})

# ── Pedidos de cotización (pestaña de Presupuestos) ──────────────────────────
# Negociación cliente <-> taller. El cliente no usa el sistema: sus respuestas
# las registra un admin o vendedor.
#   Pendiente -> Cotizada (cotizar: el taller manda precio) | Rechazada (rechaza el taller)
#               | Aprobada (solo si viene de una contraoferta: el taller la acepta)
#   Cotizada  -> Aprobada | Rechazada (rechaza el cliente) | Pendiente (contraoferta, ronda+1)
#   Aprobada y Rechazada son finales: solo un admin puede reabrir (-> Pendiente).
# El precio solo cambia al cotizar o en una contraoferta, así todo queda en
# pedidos_cotizacion_historial (cantidad y precio vigentes después de cada paso).
PCOT_ESTADOS = ("Pendiente", "Cotizada", "Aprobada", "Rechazada")
PCOT_FINALES = ("Aprobada", "Rechazada")
PCOT_DESCRIPCION_MAX = 1000
PCOT_NOTA_MAX = 300


def _validar_pedido_cotizacion(d, actual=None):
    """Devuelve (valores, None) o (None, mensaje de error). En una edición,
    lo que no viene en el payload conserva el valor actual. El precio no se
    toca acá: se carga al cotizar o en una contraoferta."""
    v = dict(actual) if actual else {}
    for k in ("fecha", "cliente_id", "producto_id", "cantidad", "descripcion"):
        if k in d:
            v[k] = d[k]
    if not v.get("cliente_id") or not query("SELECT 1 FROM clientes WHERE id=?", (v["cliente_id"],), one=True):
        return None, "Cliente requerido"
    if not v.get("producto_id"):
        return None, "Producto requerido"
    prod = query("SELECT categoria FROM materiales WHERE id=?", (v["producto_id"],), one=True)
    if not prod or prod["categoria"] != "Producto terminado":
        return None, ("Solo se pueden cotizar productos terminados — materiales, insumos, "
                      "herramientas y semielaborados no se cotizan a clientes")
    try:
        v["cantidad"] = float(v.get("cantidad") or 0)
    except (TypeError, ValueError):
        v["cantidad"] = 0
    if v["cantidad"] <= 0:
        return None, "La cantidad de piezas debe ser mayor a 0"
    desc = v.get("descripcion")
    desc = "" if desc is None else str(desc).strip()
    if len(desc) > PCOT_DESCRIPCION_MAX:
        return None, f"La descripción no puede superar los {PCOT_DESCRIPCION_MAX} caracteres (tiene {len(desc)})"
    v["descripcion"] = desc or None
    v["fecha"] = (v.get("fecha") or date.today().isoformat())[:10]
    return v, None


def _pcot_historial(db, pid, evento, nota=None):
    """Asienta un paso con la ronda, cantidad y precio que quedaron vigentes.
    Va en la misma transacción que el cambio (el que llama hace el commit)."""
    db.execute("""INSERT INTO pedidos_cotizacion_historial
            (pedido_id, ronda, evento, cantidad, precio_total, nota, usuario_id)
        SELECT id, ronda, ?, cantidad, precio_total, ?, ? FROM pedidos_cotizacion WHERE id=?""",
        (evento, nota, session.get("user_id"), pid))


def _pcot_nota(d, clave="nota"):
    """Texto libre opcional (nota o motivo): con strip, recortado a PCOT_NOTA_MAX."""
    return str(d.get(clave) or "").strip()[:PCOT_NOTA_MAX] or None


def _pcot_mando_precio():
    """¿El pedido trajo precio_total? Mira el cuerpo crudo: a un usuario sin
    ver_monetario el before_request ya se lo sacó del JSON parseado, y hay que
    avisarle en vez de ignorarlo en silencio."""
    try:
        crudo = _json.loads(request.get_data(as_text=True) or "{}")
    except (ValueError, TypeError):
        return False
    return isinstance(crudo, dict) and crudo.get("precio_total") not in (None, "")


def _pcot_numero(valor, nombre):
    """(float, None) o (None, error) para precio_total/cantidad del payload."""
    try:
        n = float(valor)
    except (TypeError, ValueError):
        return None, f"{nombre} inválido"
    if math.isnan(n) or math.isinf(n):
        return None, f"{nombre} inválido"
    return n, None


@app.route("/api/pedidos_cotizacion", methods=["GET"])
@login_required()
def get_pedidos_cotizacion():
    return jsonify([dict(r) for r in query("""SELECT pc.*, c.razon cliente_nombre,
            m.codigo producto_codigo, m.descripcion producto_nombre, m.unidad producto_unidad,
            u.nombre estado_por_nombre,
            (SELECT h.evento FROM pedidos_cotizacion_historial h WHERE h.pedido_id=pc.id
             ORDER BY h.id DESC LIMIT 1) ultimo_evento
        FROM pedidos_cotizacion pc
        LEFT JOIN clientes c ON c.id=pc.cliente_id
        LEFT JOIN materiales m ON m.id=pc.producto_id
        LEFT JOIN usuarios u ON u.id=pc.estado_por
        ORDER BY pc.id DESC""")])


@app.route("/api/pedidos_cotizacion/<int:pid>/historial", methods=["GET"])
@login_required()
def get_pedido_cotizacion_historial(pid):
    if not query("SELECT 1 FROM pedidos_cotizacion WHERE id=?", (pid,), one=True):
        return jsonify({"error": "Pedido de cotización no encontrado"}), 404
    filas = []
    for r in query("""SELECT h.*, u.nombre usuario_nombre, pc.moneda
            FROM pedidos_cotizacion_historial h
            JOIN pedidos_cotizacion pc ON pc.id=h.pedido_id
            LEFT JOIN usuarios u ON u.id=h.usuario_id
            WHERE h.pedido_id=? ORDER BY h.id""", (pid,)):
        d = dict(r)
        d["precio_unitario"] = (d["precio_total"] / d["cantidad"]
                                if d["precio_total"] is not None and d["cantidad"] else None)
        filas.append(d)
    return jsonify(filas)


@app.route("/api/pedidos_cotizacion", methods=["POST"])
@login_required(roles=["admin","vendedor"])
def create_pedido_cotizacion():
    v, err = _validar_pedido_cotizacion(request.json or {})
    if err: return jsonify({"error": err}), 400
    db = get_db()
    try:
        numero = siguiente_numero("pedidos_cotizacion", "PCOT-", 4, reservar=True)
        lid = db.execute("""INSERT INTO pedidos_cotizacion
            (numero,fecha,cliente_id,producto_id,cantidad,descripcion,estado,ronda,creado_por)
            VALUES (?,?,?,?,?,?,'Pendiente',1,?)""",
            (numero, v["fecha"], v["cliente_id"], v["producto_id"], v["cantidad"],
             v["descripcion"], session.get("user_id"))).lastrowid
        _pcot_historial(db, lid, "Solicitud")
        db.commit()
    except Exception:
        db.rollback()
        raise
    return jsonify({"ok": True, "id": lid, "numero": numero}), 201


@app.route("/api/pedidos_cotizacion/<int:pid>", methods=["PUT"])
@login_required(roles=["admin","vendedor"])
def update_pedido_cotizacion(pid):
    actual = query("SELECT * FROM pedidos_cotizacion WHERE id=?", (pid,), one=True)
    if not actual: return jsonify({"error": "Pedido de cotización no encontrado"}), 404
    if actual["estado"] != "Pendiente":
        return jsonify({"error": f"El pedido {actual['numero']} está {actual['estado']}: solo se puede editar "
                                 "mientras está Pendiente."}), 409
    v, err = _validar_pedido_cotizacion(request.json or {}, actual)
    if err: return jsonify({"error": err}), 400
    db = get_db()
    cur = db.execute("""UPDATE pedidos_cotizacion SET fecha=?,cliente_id=?,producto_id=?,
        cantidad=?,descripcion=? WHERE id=? AND estado='Pendiente'""",
        (v["fecha"], v["cliente_id"], v["producto_id"], v["cantidad"], v["descripcion"], pid))
    db.commit()
    if not cur.rowcount:
        return jsonify({"error": "El pedido cambió de estado mientras lo editabas: actualizá la lista."}), 409
    return jsonify({"ok": True})


@app.route("/api/pedidos_cotizacion/<int:pid>/estado", methods=["POST"])
@login_required(roles=["admin","vendedor"])
def estado_pedido_cotizacion(pid):
    """Un paso de la negociación: {accion, precio_total?, cantidad?, motivo?, nota?}.
    accion = cotizar | rechazar | aprobar | contraoferta | reabrir."""
    d = request.json or {}
    accion = str(d.get("accion") or "").strip().lower()
    if accion not in ("cotizar", "rechazar", "aprobar", "contraoferta", "reabrir"):
        return jsonify({"error": "Acción inválida: tiene que ser cotizar, rechazar, aprobar, "
                                 "contraoferta o reabrir."}), 400
    actual = query("SELECT * FROM pedidos_cotizacion WHERE id=?", (pid,), one=True)
    if not actual: return jsonify({"error": "Pedido de cotización no encontrado"}), 404
    estado, numero = actual["estado"], actual["numero"]

    # Permisos propios de la acción.
    if accion == "reabrir" and session.get("rol") != "admin":
        return jsonify({"error": "Solo un administrador puede reabrir un pedido de cotización."}), 403
    if accion == "cotizar" and not puede_ver_monetario():
        return jsonify({"error": "No tenés permiso para ver importes, así que no podés cotizar. "
                                 "Pedile a alguien con ese permiso que cargue el precio."}), 403
    if accion == "contraoferta" and not puede_ver_monetario() and _pcot_mando_precio():
        return jsonify({"error": "No tenés permiso para ver importes: la contraoferta solo puede cambiar "
                                 "la cantidad. Para un precio nuevo pedile a alguien con ese permiso."}), 403

    # Transiciones válidas (estado de origen -> acción).
    desde = {"cotizar": ("Pendiente",), "rechazar": ("Pendiente", "Cotizada"),
             "aprobar": ("Cotizada", "Pendiente"), "contraoferta": ("Cotizada",), "reabrir": PCOT_FINALES}[accion]
    # Pendiente se aprueba solo cuando lo último fue una contraoferta del
    # cliente: el taller la acepta tal cual, sin volver a cotizar.
    acepta_contraoferta = False
    if accion == "aprobar" and estado == "Pendiente":
        ultimo = query("""SELECT evento FROM pedidos_cotizacion_historial WHERE pedido_id=?
            ORDER BY id DESC LIMIT 1""", (pid,), one=True)
        if not ultimo or ultimo["evento"] != "Contraoferta":
            return jsonify({"error": f"El pedido {numero} está Pendiente: para aprobarlo tiene que estar "
                                     "Cotizada, o tener una contraoferta del cliente por aceptar."}), 409
        if actual["precio_total"] is None:
            return jsonify({"error": "La contraoferta no tiene precio total: cotizá el pedido antes de aprobarlo."}), 400
        acepta_contraoferta = True
    if estado not in desde:
        verbo = {"cotizar": "cotizar", "rechazar": "rechazar", "aprobar": "aprobar",
                 "contraoferta": "registrar una contraoferta", "reabrir": "reabrir"}[accion]
        if estado in PCOT_FINALES:
            msg = (f"El pedido {numero} está {estado} (estado final): no se puede {verbo}. "
                   "Solo un administrador puede reabrirlo.")
        elif accion == "reabrir":
            msg = f"El pedido {numero} está {estado}: solo se reabren pedidos Aprobados o Rechazados."
        else:
            msg = (f"El pedido {numero} está {estado}: para {verbo} tiene que estar "
                   f"{' o '.join(desde)}.")
        return jsonify({"error": msg}), 409

    sets, params = [], []
    nota = _pcot_nota(d)
    if accion == "cotizar":
        if d.get("precio_total") in (None, ""):
            return jsonify({"error": "Para cotizar cargá el precio total."}), 400
        precio, err = _pcot_numero(d.get("precio_total"), "Precio total")
        if err: return jsonify({"error": err}), 400
        if precio < 0:
            return jsonify({"error": "El precio total no puede ser negativo."}), 400
        nuevo, evento = "Cotizada", "Cotización"
        sets += ["precio_total=?", "estado_motivo=NULL"]; params += [precio]
    elif accion == "rechazar":
        motivo = _pcot_nota(d, "motivo") or nota
        quien = "el taller" if estado == "Pendiente" else "el cliente"
        nuevo, evento = "Rechazada", "Rechazo"
        nota = f"Rechazado por {quien}" + (f": {motivo}" if motivo else "")
        sets += ["estado_motivo=?"]; params += [motivo]
    elif accion == "aprobar":
        nuevo, evento = "Aprobada", "Aprobación"
        base = "Contraoferta del cliente aceptada por el taller" if acepta_contraoferta else "Aprobado por el cliente"
        nota = base + (f": {nota}" if nota else "")
        sets += ["estado_motivo=NULL"]
    elif accion == "contraoferta":
        vino_precio = d.get("precio_total") not in (None, "")
        vino_cant = d.get("cantidad") not in (None, "")
        if not vino_precio and not vino_cant:
            return jsonify({"error": "La contraoferta necesita un precio total y/o una cantidad nuevos."}), 400
        precio, cant = actual["precio_total"], actual["cantidad"]
        if vino_precio:
            precio, err = _pcot_numero(d.get("precio_total"), "Precio total")
            if err: return jsonify({"error": err}), 400
            if precio < 0:
                return jsonify({"error": "El precio total no puede ser negativo."}), 400
        if vino_cant:
            cant, err = _pcot_numero(d.get("cantidad"), "Cantidad")
            if err: return jsonify({"error": err}), 400
            if cant <= 0:
                return jsonify({"error": "La cantidad de piezas debe ser mayor a 0."}), 400
        mismo_precio = (precio is None and actual["precio_total"] is None) or (
            precio is not None and actual["precio_total"] is not None
            and abs(precio - actual["precio_total"]) < 0.005)
        if mismo_precio and abs(cant - actual["cantidad"]) < 1e-9:
            return jsonify({"error": "La contraoferta tiene que cambiar el precio total o la cantidad vigentes."}), 400
        nuevo, evento = "Pendiente", "Contraoferta"
        sets += ["precio_total=?", "cantidad=?", "ronda=ronda+1", "estado_motivo=NULL"]
        params += [precio, cant]
    else:  # reabrir
        nuevo, evento = "Pendiente", "Reapertura"
        nota = f"Reabierto (estaba {estado})" + (f": {nota}" if nota else "")
        sets += ["estado_motivo=NULL"]

    db = get_db()
    try:
        cur = db.execute(
            f"""UPDATE pedidos_cotizacion SET estado=?, estado_por=?,
                estado_fecha=datetime('now','localtime'){''.join(', ' + s for s in sets)}
            WHERE id=? AND estado=?""",
            [nuevo, session.get("user_id")] + params + [pid, estado])
        if not cur.rowcount:
            db.rollback()
            return jsonify({"error": "El pedido cambió de estado mientras tanto: actualizá la lista."}), 409
        _pcot_historial(db, pid, evento, nota)
        db.commit()
    except Exception:
        db.rollback()
        raise
    fila = query("SELECT estado, ronda FROM pedidos_cotizacion WHERE id=?", (pid,), one=True)
    return jsonify({"ok": True, "estado": fila["estado"], "ronda": fila["ronda"]})


@app.route("/api/pedidos_cotizacion/<int:pid>", methods=["DELETE"])
@login_required(roles=["admin","vendedor"])
def delete_pedido_cotizacion(pid):
    if not query("SELECT 1 FROM pedidos_cotizacion WHERE id=?", (pid,), one=True):
        return jsonify({"error": "Pedido de cotización no encontrado"}), 404
    db = get_db()
    try:
        # El historial cae por ON DELETE CASCADE; se borra explícito igual por
        # si la conexión tuviera las claves foráneas apagadas.
        db.execute("DELETE FROM pedidos_cotizacion_historial WHERE pedido_id=?", (pid,))
        db.execute("DELETE FROM pedidos_cotizacion WHERE id=?", (pid,))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return jsonify({"ok": True})

# ── Pronósticos de venta ───────────────────────────────────────────────────────
@app.route("/api/pronosticos_venta", methods=["GET"])
@login_required()
def get_pronosticos_venta():
    return jsonify([dict(r) for r in query("""
        SELECT p.*, cl.razon cliente_nombre
        FROM pronosticos_venta p
        LEFT JOIN clientes cl ON cl.id=p.cliente_id
        ORDER BY p.id DESC""")])

@app.route("/api/pronosticos_venta", methods=["POST"])
@login_required()
def create_pronostico_venta():
    d = request.json or {}
    codigo = (d.get("codigo") or "").strip()
    fecha_emision = d.get("fecha_emision")
    periodos = d.get("periodos")
    cliente_id = d.get("cliente_id") or None
    if not codigo: return jsonify({"error":"Código requerido"}), 400
    if not fecha_emision: return jsonify({"error":"Fecha de emisión requerida"}), 400
    try: periodos = int(periodos)
    except (TypeError, ValueError): return jsonify({"error":"Periodos inválido"}), 400
    if periodos <= 0: return jsonify({"error":"Periodos inválido"}), 400
    if cliente_id:
        try: cliente_id = int(cliente_id)
        except (TypeError, ValueError): return jsonify({"error":"Cliente inválido"}), 400
        if not query("SELECT id FROM clientes WHERE id=?", (cliente_id,), one=True):
            return jsonify({"error":"Cliente no encontrado"}), 400
    if query("SELECT id FROM pronosticos_venta WHERE codigo=?", (codigo,), one=True):
        return jsonify({"error":"Ya existe un pronóstico con ese código"}), 409
    estado = d.get("estado") or "Alta"
    if estado not in ("Alta","Baja"): estado = "Alta"

    pid = execute("INSERT INTO pronosticos_venta (codigo,estado,fecha_emision,periodos,cliente_id) VALUES (?,?,?,?,?)",
        (codigo, estado, fecha_emision, periodos, cliente_id))

    # Generar los meses del periodo a partir de fecha_emision, y crear una
    # fila (cantidad 0) por cada producto activo x mes, para que la tabla
    # se pueda editar directamente. Si se eligió un cliente, el pronóstico
    # solo toma los productos de ese cliente.
    try:
        base = datetime.strptime(fecha_emision[:10], "%Y-%m-%d")
    except ValueError:
        base = datetime.now()
    meses = []
    y, m = base.year, base.month
    for i in range(periodos):
        mm = ((m - 1 + i) % 12) + 1
        yy = y + ((m - 1 + i) // 12)
        meses.append(f"{yy:04d}-{mm:02d}")

    if cliente_id:
        productos = query("SELECT id FROM productos WHERE activo=1 AND tipo_articulo='Producto terminado' AND cliente_id=?", (cliente_id,))
    else:
        productos = query("SELECT id FROM productos WHERE activo=1 AND tipo_articulo='Producto terminado'")
    rows = [(pid, p["id"], mes, 0) for p in productos for mes in meses]
    if rows:
        db = get_db()
        db.executemany("INSERT OR IGNORE INTO pronostico_venta_items (pronostico_id,producto_id,mes,cantidad) VALUES (?,?,?,?)", rows)
        db.commit()

    return jsonify({"ok":True,"id":pid}), 201

@app.route("/api/pronosticos_venta/<int:pid>", methods=["PUT"])
@login_required()
def update_pronostico_venta(pid):
    d = request.json or {}
    p = query("SELECT * FROM pronosticos_venta WHERE id=?", (pid,), one=True)
    if not p: return jsonify({"error":"No encontrado"}), 404
    estado = d.get("estado", p["estado"])
    if estado not in ("Alta","Baja"): return jsonify({"error":"Estado inválido"}), 400
    execute("UPDATE pronosticos_venta SET estado=? WHERE id=?", (estado, pid))
    return jsonify({"ok":True})

@app.route("/api/pronosticos_venta/<int:pid>", methods=["DELETE"])
@login_required()
def delete_pronostico_venta(pid):
    execute("DELETE FROM pronosticos_venta WHERE id=?", (pid,))
    return jsonify({"ok":True})

@app.route("/api/pronosticos_venta/<int:pid>/tabla", methods=["GET"])
@login_required()
def get_pronostico_venta_tabla(pid):
    p = query("""SELECT p.*, cl.razon cliente_nombre
        FROM pronosticos_venta p
        LEFT JOIN clientes cl ON cl.id=p.cliente_id
        WHERE p.id=?""", (pid,), one=True)
    if not p: return jsonify({"error":"No encontrado"}), 404
    meses = [r["mes"] for r in query(
        "SELECT DISTINCT mes FROM pronostico_venta_items WHERE pronostico_id=? ORDER BY mes", (pid,))]
    filas = query("""
        SELECT pr.id producto_id, pr.codigo, pr.nombre, pr.unidad, pr.precio_venta, i.mes, i.cantidad,
               cl.razon cliente
        FROM pronostico_venta_items i
        JOIN productos pr ON pr.id=i.producto_id
        LEFT JOIN clientes cl ON cl.id=pr.cliente_id
        WHERE i.pronostico_id=?
        ORDER BY pr.codigo, i.mes""", (pid,))
    productos = {}
    for f in filas:
        pr = productos.setdefault(f["producto_id"], {
            "producto_id": f["producto_id"], "codigo": f["codigo"],
            "nombre": f["nombre"], "unidad": f["unidad"],
            "cliente": f["cliente"], "precio_venta": f["precio_venta"], "cantidades": {}})
        pr["cantidades"][f["mes"]] = f["cantidad"]
    return jsonify({"pronostico": dict(p), "meses": meses, "productos": list(productos.values())})

@app.route("/api/pronosticos_venta/<int:pid>/items", methods=["PUT"])
@login_required()
def update_pronostico_venta_items(pid):
    d = request.json or {}
    items = d.get("items") or []
    for it in items:
        execute("""UPDATE pronostico_venta_items SET cantidad=?
                   WHERE pronostico_id=? AND producto_id=? AND mes=?""",
            (float(it.get("cantidad") or 0), pid, it["producto_id"], it["mes"]))
    return jsonify({"ok":True})

# ── Avance de entrega de OC ───────────────────────────────────────────────────
@app.route("/api/ordenes_cliente/<int:ocid>/avance")
@login_required()
def get_oc_avance(ocid):
    items = query("""SELECT i.*,p.nombre prod_nombre,p.codigo prod_codigo,p.unidad
        FROM ordenes_cliente_items i
        JOIN productos p ON p.id=i.producto_id
        WHERE i.orden_cliente_id=? ORDER BY i.id""", (ocid,))
    result = []
    for item in items:
        # Sum quantities delivered via remitos
        entregado = query("""SELECT COALESCE(SUM(ri.cantidad),0) total
            FROM remito_items ri
            JOIN remitos r ON r.id=ri.remito_id
            WHERE ri.orden_cliente_item_id=? AND r.estado!='Anulado'""",
            (item["id"],), one=True)["total"]
        # Get linked remitos
        remitos = [dict(r) for r in query("""SELECT r.numero, r.fecha, r.estado, ri.cantidad
            FROM remito_items ri
            JOIN remitos r ON r.id=ri.remito_id
            WHERE ri.orden_cliente_item_id=? AND r.estado!='Anulado'
            ORDER BY r.fecha""", (item["id"],))]
        cantidad_pedida = float(item["cantidad"] or 0)
        entregado = float(entregado)
        precio = float(item["precio_unit"] or 0)
        # pct_entrega uncapped puede pasar de 100% cuando se remitió por
        # encima de lo pedido; se guarda aparte para no romper las barras de
        # progreso (que sí se recortan visualmente al 100%).
        pct = round(entregado / cantidad_pedida * 100) if cantidad_pedida else 0
        exceso = max(0.0, entregado - cantidad_pedida)
        d = dict(item)
        d["entregado"] = entregado
        d["pct_entrega"] = min(100, pct)
        d["pct_entrega_real"] = pct
        d["exceso"] = exceso
        # El monto a facturar se calcula sobre lo REALMENTE entregado, no
        # sobre lo pedido: si se remitió de más, ese excedente también se
        # cobra y el importe final de la OC queda por encima del presupuesto
        # original (cantidad_pedida * precio_unit).
        d["monto_pedido"] = cantidad_pedida * precio
        d["monto_entregado"] = entregado * precio
        d["remitos"] = remitos
        result.append(d)
    # Overall OC progress
    total_req = sum(float(i["cantidad"]) for i in items)
    total_ent = sum(r["entregado"] for r in result)
    total_monto_pedido = sum(r["monto_pedido"] for r in result)
    total_monto_entregado = sum(r["monto_entregado"] for r in result)
    pct_total = _pct_por_renglon([(r["cantidad"], r["entregado"]) for r in result])
    return jsonify({"items": result, "pct_total": pct_total,
                    "total_requerido": total_req, "total_entregado": total_ent,
                    "total_monto_pedido": total_monto_pedido,
                    "total_monto_entregado": total_monto_entregado})

# ── Ordenes de cliente (comercial) ────────────────────────────────────────────
@app.route("/api/ordenes_cliente", methods=["GET"])
@login_required()
def get_ordenes_cliente():
    cid = request.args.get("cliente_id")
    est = request.args.get("estado")
    sql = "SELECT oc.*,c.razon cliente_nombre FROM ordenes_cliente oc JOIN clientes c ON c.id=oc.cliente_id"
    conds = []
    params = []
    if cid:
        conds.append("oc.cliente_id=?")
        params.append(cid)
    if est:
        conds.append("oc.estado=?")
        params.append(est)
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    sql += " ORDER BY oc.id DESC"
    rows = query(sql, tuple(params)) if params else query(sql)
    result = []
    for r in rows:
        d = dict(r)
        try:
            d["items"] = [dict(x) for x in query("""SELECT i.*,p.nombre producto_nombre,p.codigo producto_codigo,
                o.numero ot_numero
                FROM ordenes_cliente_items i
                JOIN productos p ON p.id=i.producto_id
                LEFT JOIN ordenes o ON o.id=i.ot_id
                WHERE i.orden_cliente_id=?""", (r["id"],))]
        except Exception:
            # Fallback for old DBs missing ot_id column (migration will fix on restart)
            d["items"] = [dict(x) for x in query("""SELECT i.*,p.nombre producto_nombre,p.codigo producto_codigo,
                NULL as ot_id, NULL as ot_numero
                FROM ordenes_cliente_items i
                JOIN productos p ON p.id=i.producto_id
                WHERE i.orden_cliente_id=?""", (r["id"],))]
        for it in d["items"]:
            ots_item, cubierto = _ots_vinculadas_item(it["id"])
            it["ots"] = ots_item
            it["cantidad_cubierta"] = cubierto
        # Avance real de entrega: lo remitido sobre lo pedido (no "OT generada").
        total_ent = float(query("""SELECT COALESCE(SUM(ri.cantidad),0) total
            FROM remito_items ri
            JOIN remitos rem ON rem.id=ri.remito_id
            JOIN ordenes_cliente_items oci ON oci.id=ri.orden_cliente_item_id
            WHERE oci.orden_cliente_id=? AND rem.estado!='Anulado'""",
            (r["id"],), one=True)["total"])
        d["entregado"] = total_ent
        # Monto pedido (según lo cotizado) vs. monto a facturar (según lo
        # realmente remitido, ítem por ítem). Si se remitió por encima de lo
        # pedido en algún renglón, monto_entregado queda por encima de
        # monto_pedido — ese excedente es el que afecta el precio final.
        monto_pedido = 0.0
        monto_entregado = 0.0
        for i in d["items"]:
            precio_i = float(i.get("precio_unit") or 0)
            cant_pedida_i = float(i.get("cantidad") or 0)
            ent_i = float(query("""SELECT COALESCE(SUM(ri.cantidad),0) total
                FROM remito_items ri JOIN remitos rem ON rem.id=ri.remito_id
                WHERE ri.orden_cliente_item_id=? AND rem.estado!='Anulado'""",
                (i["id"],), one=True)["total"])
            i["cantidad_entregada"] = ent_i
            i["cantidad_restante"] = max(0, cant_pedida_i - ent_i)
            monto_pedido += cant_pedida_i * precio_i
            monto_entregado += ent_i * precio_i
        d["monto_pedido"] = monto_pedido
        d["monto_entregado"] = monto_entregado
        d["pct_entrega"] = _pct_por_renglon([(i["cantidad"], i["cantidad_entregada"]) for i in d["items"]])
        result.append(d)
    return jsonify(result)

def _sync_precio_venta_producto(producto_id, precio_unit):
    """Si el precio unitario cargado en un ítem de pedido de cliente difiere
    del precio_venta actual del producto, actualiza el producto para que el
    precio de venta quede sincronizado (se refleja en Productos y en las
    pantallas que lo consultan, como Clientes).
    Se hace acá (server-side) y no como una segunda llamada desde el
    frontend porque /api/productos requiere rol admin/operario, mientras que
    guardar un pedido de cliente lo puede hacer un vendedor: con la llamada
    separada, un vendedor actualizaba el precio del pedido pero el precio
    del producto quedaba sin cambios (403 silencioso)."""
    try:
        precio_unit = float(precio_unit or 0)
    except (TypeError, ValueError):
        return
    if precio_unit <= 0:
        return
    prod = query("SELECT precio_venta FROM materiales WHERE id=?", (producto_id,), one=True)
    if prod and round(float(prod["precio_venta"] or 0), 2) != round(precio_unit, 2):
        execute("UPDATE materiales SET precio_venta=? WHERE id=?", (precio_unit, producto_id))

@app.route("/api/ordenes_cliente", methods=["POST"])
@login_required(roles=["admin","vendedor"])
def create_orden_cliente():
    d = request.json
    if not d.get("cliente_id"):
        return jsonify({"error":"Cliente requerido"}), 400
    # Número automático OC-<año>-#### (la serie que ya se venía usando a
    # mano); los números viejos con otro formato no cuentan para la serie.
    # Se reserva con el lock de escritura: el INSERT de abajo lo confirma.
    numero = siguiente_numero("ordenes_cliente", f"OC-{date.today().year}-", 4, reservar=True)
    # "fecha" = fecha de emisión que se carga en el formulario; antes se
    # ignoraba y quedaba siempre la fecha de alta.
    lid = execute("INSERT INTO ordenes_cliente (numero,cliente_id,fecha,fecha_entrega,estado,obs) VALUES (?,?,COALESCE(?,datetime('now','localtime')),?,?,?)",
        (numero, d["cliente_id"], d.get("fecha") or None, d.get("fecha_entrega"), d.get("estado","Recibida"), d.get("obs")))
    for item in (d.get("items") or []):
        if item.get("producto_id") and item.get("cantidad"):
            if "precio_unit" in item:
                precio = item["precio_unit"] or 0
            else:
                # Sin ver_monetario el precio no viaja: se usa el de venta del producto.
                pv = query("SELECT precio_venta FROM materiales WHERE id=?", (item["producto_id"],), one=True)
                precio = (pv["precio_venta"] if pv else 0) or 0
            item_id = execute("""INSERT INTO ordenes_cliente_items
                (orden_cliente_id,producto_id,cantidad,precio_unit,fecha_deseada,obs)
                VALUES (?,?,?,?,?,?)""",
                (lid, item["producto_id"], item["cantidad"],
                 precio, item.get("fecha_deseada"), item.get("obs")))
            _sync_requerimiento_desde_pedido(item_id)
            _sync_precio_venta_producto(item["producto_id"], item.get("precio_unit"))
    return jsonify({"ok":True,"id":lid,"numero":numero}), 201


def _ots_vinculadas_item(item_id):
    """Todas las OTs vinculadas a un ítem de OC de cliente (puede haber más
    de una, repartiendo la cantidad pedida entre varias OTs del mismo
    material/producto), más la suma de sus cantidades."""
    rows = query("""SELECT o.id ot_id, o.numero ot_numero, o.cantidad ot_cantidad, o.estado ot_estado
        FROM orden_cliente_item_ots ocio JOIN ordenes o ON o.id=ocio.ot_id
        WHERE ocio.item_id=? ORDER BY ocio.id""", (item_id,))
    ots = [dict(r) for r in rows]
    cubierto = sum(float(r["ot_cantidad"] or 0) for r in ots)
    return ots, cubierto

def _forzar_completar_ots_oc(ocid):
    """Al pasar una OC de cliente a "Completada" (a mano o por el cierre
    automático del remito), completa también todas sus OTs vinculadas aunque
    no hayan terminado todas sus operaciones.

    Cada OT se cierra con el mismo cierre que _completar_ot_automatico
    (insumos sin lote, lote de PT por lo que realmente hizo la última
    operación, baja del semielaborado sobrante de OTT, cajones abiertos a
    "Ingresado"). Además, como la OT no va a seguir produciendo:
      - se libera la reserva de lotes asignados que no se llegó a consumir;
      - las OTT pendientes sin envíos se cancelan (las que tienen piezas en
        el proveedor quedan abiertas para poder recibirlas);
      - se borran del Scheduling los bloques futuros de operaciones sin
        terminar (los pasados quedan como historial).
    Las operaciones quedan con el avance real que tenían.

    Devuelve (completadas, fallidas): listas de números de OT."""
    ots = query("""SELECT o.id, o.numero FROM ordenes o
        WHERE o.id IN (
            SELECT ocio.ot_id FROM orden_cliente_item_ots ocio
              JOIN ordenes_cliente_items i ON i.id=ocio.item_id
             WHERE i.orden_cliente_id=?
            UNION
            SELECT i.ot_id FROM ordenes_cliente_items i
             WHERE i.orden_cliente_id=? AND i.ot_id IS NOT NULL)
          AND o.estado NOT IN ('Completada','Cancelada')
        ORDER BY o.id""", (ocid, ocid))
    if not ots:
        return [], []
    oc = query("SELECT numero FROM ordenes_cliente WHERE id=?", (ocid,), one=True)
    oc_num = oc["numero"] if oc else str(ocid)
    completadas, fallidas = [], []
    for ot in ots:
        oid = ot["id"]
        _completar_ot_automatico(oid)
        fin = query("SELECT estado FROM ordenes WHERE id=?", (oid,), one=True)
        if not fin or fin["estado"] != "Completada":
            fallidas.append(ot["numero"])
            continue
        # Reserva de lotes asignados y no consumidos: vuelve a quedar libre.
        for v in query("""SELECT id, lote_id, material_id, cantidad_usada,
                COALESCE(cantidad_consumida,0) consumida
                FROM orden_lotes WHERE orden_id=?""", (oid,)):
            pendiente = float(v["cantidad_usada"] or 0) - float(v["consumida"] or 0)
            if pendiente <= 0.0001:
                continue
            execute("UPDATE lotes SET cantidad_reservada=MAX(0, COALESCE(cantidad_reservada,0)-?) WHERE id=?",
                (pendiente, v["lote_id"]))
            execute("""UPDATE orden_materiales SET cantidad_asignada=MAX(0, COALESCE(cantidad_asignada,0)-?)
                WHERE orden_id=? AND material_id=?""", (pendiente, oid, v["material_id"]))
            if float(v["consumida"] or 0) <= 0.0001:
                execute("DELETE FROM orden_lotes WHERE id=?", (v["id"],))
            else:
                execute("UPDATE orden_lotes SET cantidad_usada=? WHERE id=?", (v["consumida"], v["id"]))
        execute("""UPDATE ordenes_tercerizado SET estado='Cancelado'
            WHERE ot_origen_id=? AND estado='Pendiente' AND COALESCE(cantidad_enviada,0)=0""", (oid,))
        execute("""UPDATE solicitudes_compra SET estado='Cancelada' WHERE estado='Pendiente'
            AND ott_id IN (SELECT id FROM ordenes_tercerizado WHERE ot_origen_id=? AND estado='Cancelado')""", (oid,))
        execute("""DELETE FROM planificacion WHERE inicio > strftime('%Y-%m-%d %H:%M','now','localtime')
            AND orden_operacion_id IN (SELECT id FROM orden_operaciones
                WHERE orden_id=? AND estado NOT IN ('Completada','Cancelada'))""", (oid,))
        nota = f"Completada al completar la OC {oc_num}."
        execute("""UPDATE ordenes SET obs=CASE WHEN COALESCE(TRIM(obs),'')='' THEN ?
                ELSE obs || char(10) || ? END,
            actualizado=datetime('now','localtime') WHERE id=?""", (nota, nota, oid))
        completadas.append(ot["numero"])
    return completadas, fallidas

def _pct_entrega_oc(ocid):
    """Avance real de entrega de una OC (lo remitido sobre lo pedido),
    misma lógica que en el listado de OCs. Se usa para bloquear
    vincular/desvincular OTs una vez que la OC llegó al 100%."""
    filas = query("""SELECT oci.cantidad,
            (SELECT COALESCE(SUM(ri.cantidad),0) FROM remito_items ri
               JOIN remitos rem ON rem.id=ri.remito_id
              WHERE ri.orden_cliente_item_id=oci.id AND rem.estado!='Anulado') entregado
        FROM ordenes_cliente_items oci WHERE oci.orden_cliente_id=?""", (ocid,))
    return _pct_por_renglon([(r["cantidad"], r["entregado"]) for r in filas])

def _pct_por_renglon(pares):
    """% de avance de un pedido u OC a partir de (pedido, entregado) de cada
    renglón. Lo entregado de más en un renglón NO cuenta para otro: antes se
    sumaba todo junto y 15 remitidos en un renglón de 10 tapaban los 5 que
    faltaban en otro, dando 100% con un renglón sin entregar."""
    total_req = sum(float(p or 0) for p, _e in pares)
    cubierto = sum(min(float(e or 0), float(p or 0)) for p, e in pares)
    return min(100, round(cubierto / total_req * 100)) if total_req else 0

@app.route("/api/ordenes/vinculables", methods=["GET"])
@login_required(roles=["admin","vendedor","operario"])
def get_ordenes_vinculables():
    """OTs existentes (cualquier estado salvo canceladas) que todavía no
    están vinculadas a ningún ítem de OC de cliente, filtrables por pieza
    (producto). Se pueden vincular varias a un mismo ítem: el límite lo pone
    la suma de sus cantidades contra lo pedido por el ítem, no la cantidad
    individual de cada OT."""
    producto_id = request.args.get("producto_id")
    pieza = request.args.get("pieza")
    sql = """SELECT o.*, pr.codigo prod_codigo, pr.nombre prod_nombre
        FROM ordenes o
        LEFT JOIN productos pr ON pr.id=o.producto_id
        WHERE o.id NOT IN (SELECT ot_id FROM orden_cliente_item_ots)
        AND o.estado NOT IN ('Cancelada')"""
    params = []
    if producto_id:
        sql += " AND o.producto_id=?"
        params.append(producto_id)
    elif pieza:
        sql += " AND (pr.codigo LIKE ? OR pr.nombre LIKE ? OR o.descripcion LIKE ?)"
        params += [f"%{pieza}%", f"%{pieza}%", f"%{pieza}%"]
    sql += " ORDER BY o.id DESC"
    rows = query(sql, tuple(params))
    return jsonify([dict(r) for r in rows])

@app.route("/api/ordenes_cliente_items/<int:item_id>/vincular_ot", methods=["POST"])
@login_required(roles=["admin","vendedor","operario"])
def vincular_ot_item(item_id):
    """Vincula manualmente una OT ya existente (no generada por explosión) a
    un ítem de OC de cliente. Se pueden vincular varias OTs del mismo
    material/producto a un mismo ítem, repartiendo la cantidad pedida entre
    ellas, pero la opción se bloquea apenas la suma de lo vinculado iguala o
    supera la cantidad que pide el ítem de la OC."""
    d = request.json or {}
    ot_id = d.get("ot_id")
    if not ot_id: return jsonify({"error":"OT requerida"}), 400
    item = query("SELECT * FROM ordenes_cliente_items WHERE id=?", (item_id,), one=True)
    if not item: return jsonify({"error":"Ítem de OC no encontrado"}), 404
    if _pct_entrega_oc(item["orden_cliente_id"]) >= 100:
        return jsonify({"error":"La OC ya está 100% entregada: no se pueden vincular más OTs"}), 409
    ot = query("SELECT * FROM ordenes WHERE id=?", (ot_id,), one=True)
    if not ot: return jsonify({"error":"OT no encontrada"}), 404
    if ot["producto_id"] and item["producto_id"] and ot["producto_id"] != item["producto_id"]:
        return jsonify({"error":"La OT es de otro material/producto distinto al del ítem"}), 400
    ya_vinculada = query("SELECT id FROM orden_cliente_item_ots WHERE ot_id=?", (ot_id,), one=True)
    if ya_vinculada: return jsonify({"error":"Esa OT ya está vinculada a otro ítem"}), 409
    _ots, cubierto = _ots_vinculadas_item(item_id)
    if cubierto >= float(item["cantidad"]):
        return jsonify({"error":"Ya se cubrió la cantidad pedida por este ítem: no se pueden vincular más OTs"}), 409
    execute("INSERT INTO orden_cliente_item_ots (item_id,ot_id) VALUES (?,?)", (item_id, ot_id))
    if not item["ot_id"]:
        execute("UPDATE ordenes_cliente_items SET ot_id=? WHERE id=?", (ot_id, item_id))
    # Solo avanza un pedido que todavía no arrancó: no reabre uno cancelado
    # ni completado.
    execute("UPDATE ordenes_cliente SET estado='En proceso' WHERE id=? AND estado IN ('Recibida','Confirmada')",
            (item["orden_cliente_id"],))
    return jsonify({"ok": True})

@app.route("/api/ordenes_cliente_items/<int:item_id>/desvincular_ot/<int:ot_id>", methods=["DELETE"])
@login_required(roles=["admin","vendedor","operario"])
def desvincular_ot_item(item_id, ot_id):
    """Quita el vínculo entre una OT y un ítem de OC de cliente."""
    item = query("SELECT * FROM ordenes_cliente_items WHERE id=?", (item_id,), one=True)
    if not item: return jsonify({"error":"Ítem de OC no encontrado"}), 404
    if _pct_entrega_oc(item["orden_cliente_id"]) >= 100:
        return jsonify({"error":"La OC ya está 100% entregada: no se pueden desvincular OTs"}), 409
    execute("DELETE FROM orden_cliente_item_ots WHERE item_id=? AND ot_id=?", (item_id, ot_id))
    if item["ot_id"] == ot_id:
        otra = query("SELECT ot_id FROM orden_cliente_item_ots WHERE item_id=? ORDER BY id LIMIT 1", (item_id,), one=True)
        execute("UPDATE ordenes_cliente_items SET ot_id=? WHERE id=?", (otra["ot_id"] if otra else None, item_id))
    return jsonify({"ok": True})

@app.route("/api/ordenes_cliente/<int:ocid>", methods=["PUT"])
@login_required(roles=["admin","vendedor"])
def update_orden_cliente(ocid):
    d = request.json or {}
    actual = query("SELECT * FROM ordenes_cliente WHERE id=?", (ocid,), one=True)
    if not actual: return jsonify({"error":"OC no encontrada"}), 404
    # Solo se pisan los campos que vienen en el body: el formulario no manda
    # fecha_entrega y antes la ponía en NULL en cada edición.
    # El número es automático: no se cambia al editar.
    nuevo_numero = actual["numero"]
    # Ítems: los renglones sin OT que ya existen se ACTUALIZAN por id (el
    # formulario manda el id de cada renglón). Antes se borraban todos y se
    # volvían a crear, y eso:
    #   - fallaba (FOREIGN KEY) si algún renglón ya tenía remitos, dejando la
    #     cabecera grabada a medias;
    #   - ponía el precio en 0 cuando lo editaba un usuario sin ver_monetario
    #     (el precio no viaja: lo descarta el before_request).
    # Todo se valida antes de grabar nada.
    alta, cambios, bajas = [], [], []
    if "items" in d:
        existentes = {r["id"]: r for r in query(
            "SELECT * FROM ordenes_cliente_items WHERE orden_cliente_id=? AND (ot_id IS NULL OR ot_id=0)", (ocid,))}
        vistos = set()
        for item in (d["items"] or []):
            if not (item.get("producto_id") and item.get("cantidad")):
                continue
            iid = item.get("id")
            try: iid = int(iid) if iid not in (None, "") else None
            except (TypeError, ValueError): iid = None
            if iid in existentes:
                vistos.add(iid)
                if (int(item["producto_id"]) != int(existentes[iid]["producto_id"])
                        and query("SELECT 1 FROM remito_items WHERE orden_cliente_item_id=? LIMIT 1", (iid,), one=True)):
                    return jsonify({"error": "No se puede cambiar el producto de un renglón que ya tiene remitos"}), 400
                cambios.append((iid, item))
            else:
                alta.append(item)
        for iid in existentes:
            if iid in vistos:
                continue
            if query("SELECT 1 FROM remito_items WHERE orden_cliente_item_id=? LIMIT 1", (iid,), one=True):
                pr = query("SELECT codigo FROM productos WHERE id=?", (existentes[iid]["producto_id"],), one=True)
                return jsonify({"error": f"No se puede quitar el renglón de {pr['codigo'] if pr else 'producto'}: ya tiene remitos emitidos"}), 400
            bajas.append(iid)
    execute("UPDATE ordenes_cliente SET numero=?,estado=?,fecha=?,fecha_entrega=?,obs=? WHERE id=?",
        (nuevo_numero,
         d["estado"] if "estado" in d else actual["estado"],
         (d.get("fecha") or actual["fecha"]) if "fecha" in d else actual["fecha"],
         d["fecha_entrega"] if "fecha_entrega" in d else actual["fecha_entrega"],
         d["obs"] if "obs" in d else actual["obs"], ocid))
    for iid in bajas:
        execute("DELETE FROM requerimientos_productivos WHERE numero=?", (f"OC-CLI-ITEM-{iid}",))
        execute("DELETE FROM ordenes_cliente_items WHERE id=?", (iid,))
    for iid, item in cambios:
        execute("""UPDATE ordenes_cliente_items SET producto_id=?,cantidad=?,fecha_deseada=?,obs=?,
            precio_unit=? WHERE id=?""",
            (item["producto_id"], item["cantidad"], item.get("fecha_deseada"), item.get("obs"),
             _mon_o_actual(item, "precio_unit", "ordenes_cliente_items", iid), iid))
        _sync_requerimiento_desde_pedido(iid)
        if "precio_unit" in item:
            _sync_precio_venta_producto(item["producto_id"], item["precio_unit"])
    for item in alta:
        if "precio_unit" in item:
            precio = item["precio_unit"] or 0
        else:
            # Sin ver_monetario el precio no viaja: se usa el de venta del producto.
            pv = query("SELECT precio_venta FROM materiales WHERE id=?", (item["producto_id"],), one=True)
            precio = (pv["precio_venta"] if pv else 0) or 0
        item_id = execute("""INSERT INTO ordenes_cliente_items
            (orden_cliente_id,producto_id,cantidad,precio_unit,fecha_deseada,obs)
            VALUES (?,?,?,?,?,?)""",
            (ocid, item["producto_id"], item["cantidad"], precio, item.get("fecha_deseada"), item.get("obs")))
        _sync_requerimiento_desde_pedido(item_id)
        if "precio_unit" in item:
            _sync_precio_venta_producto(item["producto_id"], item["precio_unit"])
    # Completar la OC completa también sus OTs, aunque no estén terminadas.
    if d.get("estado") == "Completada" and actual["estado"] != "Completada":
        completadas, fallidas = _forzar_completar_ots_oc(ocid)
        return jsonify({"ok":True, "ots_completadas":completadas, "ots_fallidas":fallidas})
    return jsonify({"ok":True})


# Funciones de otras áreas. Van al final a propósito: así cada módulo ya
# definió todo lo suyo cuando otro lo importa, y no hay problemas de
# importación circular. Se usan recién al atender pedidos.
from .requerimientos import _sync_requerimiento_desde_pedido
from .ordenes import _completar_ot_automatico

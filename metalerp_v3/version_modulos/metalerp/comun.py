"""Funciones de negocio compartidas por varias áreas (stock de materiales,
herramientas, PT/PSE de operaciones, planes de consumo y devolución)."""
from .nucleo import execute, get_config_valor, math, query, session

# Una Solicitud de Compra en estos estados todavía está abierta (puede
# terminar en una OC): mientras haya una así no se genera otra para el mismo
# material. La usan el MRP, la tabla de críticos y el alta de SC.
SC_ABIERTAS_SQL = "('Pendiente','Cotizada','En evaluación')"
# OC de compra cuya mercadería todavía puede llegar.
OC_EN_CAMINO_SQL = "('Borrador','Pendiente aprobacion','Aprobada','Enviada','Recibida parcial')"


def _sc_automaticas_activas():
    """¿El sistema puede crear Solicitudes de Compra por su cuenta?

    Por defecto NO: las SC se cargan a mano desde Compras. Hay cuatro puntos
    que históricamente las generaban solos — stock por debajo del mínimo,
    faltante de insumo al remitir una OTT, envío a un tercero, y materiales
    faltantes de una OT auxiliar — y todos preguntan acá antes de crear nada.

    Para volver a habilitarlas: configuracion.sc_automaticas = '1'.
    """
    try:
        return get_config_valor("sc_automaticas", "0") == "1"
    except Exception:
        # Ante la duda (sin contexto de base, por ejemplo) no se crea nada.
        return False


def cant_material(cantidad_unit, piezas, vida_util):
    """Cantidad de un material de una operación para procesar `piezas` piezas.

    Herramienta con vida útil (piezas que hace cada una): ceil(piezas / vida
    útil), p.ej. 100 piezas con vida útil 4 -> 25 herramientas, 101 -> 26.
    Sin vida útil (vacía o 0): cantidad por pieza x piezas, como siempre.
    También está registrada como función SQL (ver get_db):
    cant_material(om.cantidad, oo.qty_requerida, om.vida_util_herramienta)."""
    try:
        piezas = float(piezas or 0)
        vida = float(vida_util or 0)
    except (TypeError, ValueError):
        return 0.0
    if vida > 0:
        return float(math.ceil(piezas / vida - 1e-9)) if piezas > 0 else 0.0
    return float(cantidad_unit or 0) * piezas


def _vida_util_valida(material_id, valor):
    """Vida útil a guardar para un material de una operación: entero > 0 solo
    si el material es de categoría Herramienta; en cualquier otro caso None."""
    try:
        vida = int(float(valor))
    except (TypeError, ValueError):
        return None
    if vida <= 0 or not material_id:
        return None
    mat = query("SELECT categoria FROM materiales WHERE id=?", (material_id,), one=True)
    return vida if mat and mat["categoria"] == "Herramienta" else None


def consumir_herramientas_op(oo_id):
    """Lleva el stock de las herramientas de una operación de OT a lo que ya se
    produjo en ella: consumo = cant_material(cantidad, qty_producida, vida útil)
    y se descuenta solo la diferencia con lo ya descontado (herr_consumido).
    Se llama después de cada cambio de qty_producida (novedad nueva, editada,
    borrada o restaurada; retornos de OTT). Si lo producido baja (se corrige o
    borra una novedad) las herramientas de más vuelven al stock."""
    filas = query("""SELECT om.id, om.material_id, om.cantidad, om.vida_util_herramienta,
            COALESCE(om.herr_consumido,0) consumido, oo.qty_producida, o.numero ot_numero, m.codigo
        FROM orden_operacion_materiales om
        JOIN orden_operaciones oo ON oo.id=om.orden_operacion_id
        JOIN ordenes o ON o.id=oo.orden_id
        JOIN materiales m ON m.id=om.material_id
        WHERE om.orden_operacion_id=? AND m.categoria='Herramienta'""", (oo_id,))
    for f in filas:
        objetivo = cant_material(f["cantidad"], f["qty_producida"], f["vida_util_herramienta"])
        delta = round(objetivo - float(f["consumido"] or 0), 6)
        if abs(delta) < 1e-9:
            continue
        if delta > 0:
            execute("""UPDATE materiales SET stock=MAX(0, stock-?),
                actualizado=datetime('now','localtime') WHERE id=?""", (delta, f["material_id"]))
            ref = f"Consumo OT {f['ot_numero']} — Herramienta {f['codigo']}"
        else:
            execute("""UPDATE materiales SET stock=stock+?,
                actualizado=datetime('now','localtime') WHERE id=?""", (-delta, f["material_id"]))
            ref = f"Devolución OT {f['ot_numero']} — Herramienta {f['codigo']} (se corrigió lo producido)"
        execute("""INSERT INTO movimientos (material_id, lote_id, tipo, cantidad, referencia, usuario_id)
            VALUES (?, NULL, ?, ?, ?, ?)""",
            (f["material_id"], "salida" if delta > 0 else "entrada", abs(delta), ref, session.get("user_id")))
        execute("UPDATE orden_operacion_materiales SET herr_consumido=? WHERE id=?", (objetivo, f["id"]))
        if delta > 0:
            auto_generar_sc_bajo_stock(f["material_id"], f"consumo herramientas OT {f['ot_numero']}")


def consumir_herramientas_ot(oid):
    """consumir_herramientas_op para todas las operaciones de una OT (al
    completarla, por si quedó algo de antes de este cambio)."""
    for r in query("SELECT id FROM orden_operaciones WHERE orden_id=?", (oid,)):
        consumir_herramientas_op(r["id"])

def get_or_create_pt_material(prod):
    """Devuelve el artículo de stock de un producto terminado.

    Desde la unificación de productos y materiales (ver
    migracion_unificacion.py) el producto ES el artículo de stock: la misma
    fila de `materiales` tiene el proceso, el stock y los lotes, y conserva
    el id que tenía en la vieja tabla `productos`. Ya no existe un "gemelo"
    que crear ni sincronizar, así que esta función solo devuelve esa fila.

    Se conserva el nombre (y la firma) porque la usan muchos puntos del
    código: generación de PT al completar una OT, novedades, insumos de tipo
    producto, diagnósticos, etc. Requiere que `prod` tenga "id".
    """
    prod_keys = prod.keys() if hasattr(prod, "keys") else prod
    if "id" not in prod_keys or prod["id"] is None:
        raise ValueError("get_or_create_pt_material requiere prod['id'] (producto_id)")
    art = query("SELECT id,stock FROM materiales WHERE id=?", (prod["id"],), one=True)
    if art:
        return art
    raise ValueError(f"El artículo id={prod['id']} no existe")

def _firma_insumos_operacion(proceso_op_id):
    """Firma de lo que se le manda al proveedor en una operación tercerizada.

    Es la identidad del semielaborado que vuelve: mismos insumos = misma
    pieza. Si en Procesos se le agrega o se le cambia un material a la
    operación, lo que devuelve el proveedor ya no es lo mismo y necesita su
    propio código (ver _get_or_create_pse).

    El PROVEEDOR no entra en la firma a propósito: queda trazado por lote
    (lotes.proveedor_id) y por OTT (ordenes_tercerizado.proveedor_id), que se
    congelan al momento del envío y no se ven afectados por editar el proceso
    más tarde.
    """
    rows = query("""SELECT material_id, producto_id, cantidad
        FROM operacion_materiales WHERE operacion_id=?
        ORDER BY COALESCE(material_id,0), COALESCE(producto_id,0)""",
        (proceso_op_id,))
    partes = ["%s:%s:%g" % (r["material_id"] or 0, r["producto_id"] or 0,
                            float(r["cantidad"] or 0)) for r in rows]
    return "|".join(partes) if partes else "(sin insumos)"


def _get_or_create_pse(proceso_op_id):
    """Devuelve (creando si hace falta) el id del material 'Semielaborado' de
    una operación tercerizada intermedia, en su versión VIGENTE.

    Un semielaborado queda definido por la operación MAS sus insumos. Mientras
    la firma no cambie se reusa el mismo material; apenas cambia se crea una
    versión nueva con su propio código (-v2, -v3, ...) en vez de mezclar dos
    piezas distintas bajo el mismo stock y la misma trazabilidad.

    Las OT en curso no se ven afectadas: la OTT congela su semielaborado en
    material_se_id al crearse, igual que ya congela proveedor y precio.

    Devuelve None si la operación no existe o perdió el vínculo con su
    producto (proceso_op_id NULL porque se borró la operación del proceso).
    """
    if not proceso_op_id:
        return None
    op = query("""SELECT po.id, po.nombre, po.producto_id,
            pr.codigo prod_codigo, pr.nombre prod_nombre, pr.unidad prod_unidad
        FROM proceso_operaciones po JOIN productos pr ON pr.id=po.producto_id
        WHERE po.id=?""", (proceso_op_id,), one=True)
    if not op:
        return None

    firma = _firma_insumos_operacion(proceso_op_id)
    vigente = query("""SELECT id FROM materiales
        WHERE producto_id=? AND operacion_id=? AND categoria='Semielaborado'
          AND COALESCE(pse_firma,'')=? AND activo=1
        ORDER BY id DESC LIMIT 1""",
        (op["producto_id"], proceso_op_id, firma), one=True)
    if vigente:
        return vigente["id"]

    # Firma nueva: hace falta otra versión. El código base queda para la
    # primera; de ahí en más se numeran -v2, -v3...
    op_nombre = (op["nombre"] or "SE").strip()
    base = "%s-%s" % (op["prod_codigo"], op_nombre)
    previas = query("""SELECT COUNT(*) c FROM materiales
        WHERE producto_id=? AND operacion_id=? AND categoria='Semielaborado'""",
        (op["producto_id"], proceso_op_id), one=True)["c"]
    n = int(previas or 0) + 1
    candidato = base if n == 1 else "%s-v%d" % (base, n)
    while query("SELECT id FROM materiales WHERE codigo=?", (candidato,), one=True):
        n += 1
        candidato = "%s-v%d" % (base, n)

    return execute("""INSERT INTO materiales
        (codigo,descripcion,categoria,producto_id,operacion_id,pse_firma,
         unidad,stock,stock_min,precio_unit,activo)
        VALUES (?,?,?,?,?,?,?,0,0,0,1)""",
        (candidato, "%s — %s" % (op["prod_nombre"], op_nombre),
         "Semielaborado", op["producto_id"], proceso_op_id, firma,
         op["prod_unidad"] or "unid"))


def _material_retorno_operacion(orden_operacion_id):
    """v147 (punto 9): en una operación tercerizada el primer insumo de tipo
    'material' es el material que se genera al ingresar el remito del proveedor.
    v148: se lee de la copia propia de la OT (orden_operacion_materiales)."""
    if not orden_operacion_id:
        return None
    r = query("""SELECT om.material_id FROM orden_operacion_materiales om
        WHERE om.orden_operacion_id=? AND om.tipo='material' AND om.material_id IS NOT NULL
        ORDER BY om.id LIMIT 1""", (orden_operacion_id,), one=True)
    return r["material_id"] if r else None


def _sincronizar_estado_paso(orden_operacion_id):
    """Cierra (o reabre) un paso mirando su TOTAL, no cada ruta por separado.

    Un paso puede tener rutas alternativas: varias orden_operaciones con el
    mismo `orden` (p.ej. dos máquinas que hacen lo mismo). Si el trabajo se
    reparte entre dos, ninguna llega sola a lo requerido y el paso no se
    cerraba nunca, aunque entre las dos estuviera completo — y la OT quedaba
    trabada. Lo requerido del paso es el mayor de sus rutas (cualquiera
    podría hacerlo entero) y lo producido es la suma de todas. Es el mismo
    criterio que ya usaba generar_pt_faltante_si_corresponde para el PT.
    """
    op = query("SELECT orden_id, orden FROM orden_operaciones WHERE id=?",
               (orden_operacion_id,), one=True)
    if not op:
        return
    rutas = query("""SELECT id, qty_requerida, qty_producida, estado
        FROM orden_operaciones WHERE orden_id=? AND orden=?""",
        (op["orden_id"], op["orden"]))
    requerido = max([float(r["qty_requerida"] or 0) for r in rutas] or [0.0])
    if requerido <= 0:
        return
    producido = sum(float(r["qty_producida"] or 0) for r in rutas)
    completo = producido >= requerido - 0.0001
    for r in rutas:
        # Una ruta que nunca se usó no se marca como hecha: el paso se cierra
        # con las que efectivamente trabajaron.
        if float(r["qty_producida"] or 0) <= 0 and r["id"] != orden_operacion_id:
            continue
        if completo and r["estado"] != "Completada":
            execute("UPDATE orden_operaciones SET estado='Completada' WHERE id=?", (r["id"],))
        elif not completo and r["estado"] == "Completada":
            execute("UPDATE orden_operaciones SET estado='En proceso' WHERE id=?", (r["id"],))


def _copiar_materiales_a_ot_op(oo_id, proceso_op_id):
    """v148 (punto 4): al generarse la OT se COPIA el proceso. Desde ahí la OT es
    independiente: sus materiales se editan en la OT y no se validan contra el proceso."""
    if not oo_id or not proceso_op_id:
        return
    execute("DELETE FROM orden_operacion_materiales WHERE orden_operacion_id=?", (oo_id,))
    for r in query("SELECT material_id,producto_id,cantidad,unidad,tipo,vida_util_herramienta FROM operacion_materiales WHERE operacion_id=?", (proceso_op_id,)):
        execute("""INSERT INTO orden_operacion_materiales (orden_operacion_id,material_id,producto_id,cantidad,unidad,tipo,vida_util_herramienta)
                   VALUES (?,?,?,?,?,?,?)""", (oo_id, r["material_id"], r["producto_id"], r["cantidad"], r["unidad"], r["tipo"] or "material", r["vida_util_herramienta"]))


def _tiene_insumo_material(materiales):
    return any((m.get("tipo", "material") == "material" and m.get("material_id") and m.get("cantidad"))
               for m in (materiales or []))


def _lotes_vinculados_material(orden_id, material_id):
    """Todos los lotes vinculados a este material en esta OT (vía
    orden_lotes), en orden FIFO por fecha de ingreso del lote. Puede haber
    MÁS DE UNO: la OT puede cubrir la cantidad requerida combinando varios
    lotes (ej. uno de 90 + uno de 10, o varios lotes chicos) en vez de
    exigir que un solo lote alcance para todo el consumo."""
    return query("""SELECT l.id, l.numero, l.cantidad_activa, l.fecha_ingreso,
            ol.cantidad_usada, COALESCE(ol.cantidad_consumida,0) cantidad_consumida
        FROM orden_lotes ol JOIN lotes l ON l.id=ol.lote_id
        WHERE ol.orden_id=? AND ol.material_id=?
        ORDER BY l.fecha_ingreso, l.id""", (orden_id, material_id))

def _plan_consumo_adicional(vinculos, requerido):
    """Distribuye `requerido` entre los lotes vinculados (orden FIFO por
    fecha de ingreso). Se usa cantidad_activa como disponible sin restar
    cantidad_reservada porque estos lotes ya están vinculados/reservados
    para ESTA MISMA OT (esa resta solo aplica al elegir un lote nuevo desde
    "Lotes asignados", no acá). Devuelve (plan, disponible_total, cubierto)
    donde plan es una lista de tuplas (lote, cantidad_a_tomar_de_ese_lote)."""
    plan = []
    restante = requerido
    disponible_total = 0
    for lote in vinculos:
        disp = max(0, float(lote["cantidad_activa"] or 0))
        disponible_total += disp
        if restante <= 0.0000001:
            continue
        tomar = min(disp, restante)
        if tomar > 0:
            plan.append((lote, round(tomar, 6)))
            restante -= tomar
    return plan, disponible_total, restante <= 0.0001

def _materiales_ott_pendientes_por_operacion(orden_id, oo_id):
    """Devuelve el material semielaborado generado por el retorno de una
    operación tercerizada ANTERIOR (por orden) dentro de la misma OT, cuyo
    consumo debe imputarse a ESTA operación puntual — la primera operación
    posterior a la tercerizada en la ruta. Este material se crea de forma
    dinámica al recibir el retorno de la OTT (ver registrar_retorno) y por
    lo tanto NUNCA está declarado en operacion_materiales (la plantilla de
    proceso del producto), así que sin este chequeo create_novedad/editar/
    eliminar novedad lo ignoran por completo y el lote de la OTT nunca se
    gasta aunque esté reservado y vinculado (orden_lotes) a la OT — bug
    reportado. Se asume consumo 1:1 (1 unidad de semielaborado por cada
    unidad producida en esta operación), que es el criterio con el que se
    genera la cantidad recibida de la OTT."""
    op = query("SELECT orden_id,orden FROM orden_operaciones WHERE id=?", (oo_id,), one=True)
    if not op or op["orden_id"] != orden_id:
        return []
    try:
        orden_num = float(op["orden"])
    except (TypeError, ValueError):
        return []
    # Tercerizada previa MÁS CERCANA (mayor "orden" que sea < la de esta
    # operación), que sea intermedia (es_ultimo_nivel=0, ya que la de último
    # nivel no genera semielaborado sino que cierra la OT directamente) y
    # cuyo lote de retorno ya exista.
    terc_prev = query("""SELECT ott.lote_retorno_id, l.material_id
        FROM orden_operaciones oo
        JOIN ordenes_tercerizado ott ON ott.operacion_id=oo.id
        LEFT JOIN lotes l ON l.id=ott.lote_retorno_id
        WHERE oo.orden_id=? AND oo.es_tercerizada=1 AND ott.es_ultimo_nivel=0
          AND CAST(oo.orden AS REAL) < ?
        ORDER BY CAST(oo.orden AS REAL) DESC LIMIT 1""", (orden_id, orden_num), one=True)
    if not terc_prev or not terc_prev["material_id"]:
        return []
    mat = query("SELECT id,descripcion,unidad,categoria FROM materiales WHERE id=?",
        (terc_prev["material_id"],), one=True)
    if not mat:
        return []
    return [{"material_id": mat["id"], "cantidad": 1, "categoria": mat["categoria"] or "Semielaborado",
        "descripcion": mat["descripcion"], "unidad": mat["unidad"]}]

def _plan_devolucion(vinculos, a_devolver):
    """Distribuye una devolución de stock (por edición o eliminación de una
    novedad) entre los lotes vinculados, en orden inverso (LIFO: el lote
    agregado más recientemente primero), sin devolver a un lote más de lo
    que efectivamente se le registró como consumido (cantidad_consumida),
    para no inflar su stock por encima de lo real.
    NOTA: cantidad_consumida es un acumulado por lote+material+OT a través
    de TODAS las novedades de esa OT (el schema no trackea qué lote sirvió
    a cada novedad puntual), así que esta distribución es una aproximación
    razonable y no un reverso exacto por novedad individual."""
    plan = []
    restante = a_devolver
    for lote in reversed(vinculos):
        consumida = float(lote["cantidad_consumida"] or 0)
        if restante <= 0.0000001:
            continue
        tomar = min(consumida, restante)
        if tomar > 0:
            plan.append((lote, round(tomar, 6)))
            restante -= tomar
    return plan


# Funciones de otras áreas. Van al final a propósito: así cada módulo ya
# definió todo lo suyo cuando otro lo importa, y no hay problemas de
# importación circular. Se usan recién al atender pedidos.
from .compras import auto_generar_sc_bajo_stock

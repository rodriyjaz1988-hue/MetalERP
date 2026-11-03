"""Cajones de producción y su relación con lotes, novedades y remitos."""
from .nucleo import (app, datetime, execute, has_request_context, jsonify, login_required,
    math, query, request, session, siguiente_numero)

def _lote_stock_computado(lote_id):
    """True si las piezas de este lote ya se sumaron a materiales.stock al
    crearlo. Los lotes viejos (anteriores a este cambio) devuelven False y
    siguen con el modelo anterior: su stock lo mueve Calidad."""
    r = query("SELECT stock_computado FROM lotes WHERE id=?", (lote_id,), one=True)
    return bool(r and r["stock_computado"])


def _reducir_lotes_pt(mat_pt_id, lotes, sobrante, ot_lote_num):
    """Descuenta `sobrante` piezas de los lotes de PT de una OT, empezando por
    el mas nuevo (los lotes vienen ordenados por el llamador).

    Solo se toca lo que Calidad TODAVIA NO clasifico
    (cantidad_original - cantidad_activa - cantidad_rechazada): lo aprobado ya
    entro a `materiales.stock` y puede estar consumido por otra OT, asi que
    descontarlo desde aca dejaria un descuadre peor que el que se intenta
    corregir. Si no alcanza con lo sin clasificar, se descuenta lo que se
    pueda y se avisa por consola en vez de romper la edicion.

    Devuelve lo que NO se pudo descontar.
    """
    for lote in lotes:
        if sobrante <= 0.0001:
            break
        sin_clasificar = (float(lote["cantidad_original"] or 0)
                          - float(lote["cantidad_activa"] or 0)
                          - float(lote["cantidad_rechazada"] or 0))
        quitar = min(sobrante,
                     max(0.0, sin_clasificar),
                     float(lote["cantidad_disponible"] or 0))
        if quitar <= 0.0001:
            continue
        execute("""UPDATE lotes SET
            cantidad_original=MAX(0, cantidad_original-?),
            cantidad_disponible=MAX(0, cantidad_disponible-?),
            estado=CASE WHEN cantidad_original-? <= 0.0001 AND estado<>'Abierto'
                        THEN 'Agotado' ELSE estado END
            WHERE id=?""", (quitar, quitar, quitar, lote["id"]))
        # Si al crearse el lote ya se habia computado el stock (las piezas
        # entraron al deposito), sacarlas del lote tiene que sacarlas tambien
        # del inventario.
        if _lote_stock_computado(lote["id"]):
            execute("""UPDATE materiales SET stock=MAX(0, stock-?),
                actualizado=datetime('now','localtime') WHERE id=?""",
                (quitar, mat_pt_id))
        execute("""INSERT INTO movimientos (material_id,lote_id,tipo,cantidad,referencia,usuario_id)
            VALUES (?,?,?,?,?,?)""",
            (mat_pt_id, lote["id"], "ajuste", quitar,
             f"Correccion de produccion OT {ot_lote_num} - se descuentan {quitar:g} piezas "
             f"del lote {lote['numero']} (no habian pasado por Calidad)",
             session.get("user_id")))
        sobrante -= quitar
    if sobrante > 0.0001:
        print(f"[WARN] OT {ot_lote_num}: quedaron {sobrante:g} piezas de PT sin poder "
              f"descontar del lote - ya estaban clasificadas por Calidad.")
    return sobrante


# ── Cajones ───────────────────────────────────────────────────────────────────
# Un cajón agrupa piezas físicas de una OT desde la 1ª operación hasta que
# Calidad las libera. Lo que hizo cada paso en cada cajón sale de
# novedad_cajones (operaciones internas) y ott_cajones (tercerizadas). El paso
# es el número de "orden" de la operación (las rutas alternativas comparten
# paso), así un cajón transferido desde otra OT del mismo producto sigue desde
# el paso donde quedó. Estados: En proceso, En espera (su OT se canceló y
# espera pasar a otra), Liberado / Rechazado (Calidad clasificó todo lo que
# terminó la última operación) y Baja.

def _pasos_ot(oid):
    return [r["p"] for r in query("""SELECT DISTINCT CAST(orden AS INTEGER) p
        FROM orden_operaciones WHERE orden_id=? ORDER BY 1""", (oid,))]


def _ot_tiene_cajones(oid):
    return bool(query("SELECT 1 FROM cajones WHERE orden_id=? LIMIT 1", (oid,), one=True))


def _ot_usa_cajones(oid):
    """La OT trabaja con cajones si ya tiene alguno, o si su producto tiene
    "piezas por cajón" y su primer paso todavía no produjo nada. Las OTs que
    ya habían empezado siguen sin cajones, como antes."""
    if _ot_tiene_cajones(oid):
        return True
    o = query("""SELECT p.capacidad_cajon FROM ordenes o JOIN productos p ON p.id=o.producto_id
        WHERE o.id=?""", (oid,), one=True)
    if not o or not o["capacidad_cajon"] or int(o["capacidad_cajon"]) <= 0:
        return False
    pasos = _pasos_ot(oid)
    if not pasos:
        return False
    hecho = query("""SELECT COALESCE(SUM(qty_producida),0) s FROM orden_operaciones
        WHERE orden_id=? AND CAST(orden AS INTEGER)=?""", (oid, pasos[0]), one=True)["s"]
    return float(hecho or 0) <= 0.0001


def _cajon_por_paso(cajon_id, sin_novedad=None, sin_op=None):
    """{paso: piezas} que registró cada paso en el cajón (sin contar la
    novedad `sin_novedad` ni la operación tercerizada `sin_op`)."""
    out = {}
    for r in query("""SELECT CAST(oo.orden AS INTEGER) p, SUM(nc.cantidad) c
            FROM novedad_cajones nc
            JOIN novedades_produccion n ON n.id=nc.novedad_id
            JOIN orden_operaciones oo ON oo.id=n.orden_operacion_id
            WHERE nc.cajon_id=? AND nc.novedad_id<>? GROUP BY 1""", (cajon_id, sin_novedad or 0)):
        out[r["p"]] = out.get(r["p"], 0.0) + float(r["c"] or 0)
    for r in query("""SELECT CAST(oo.orden AS INTEGER) p, SUM(oc.cantidad) c
            FROM ott_cajones oc JOIN orden_operaciones oo ON oo.id=oc.orden_operacion_id
            WHERE oc.cajon_id=? AND oc.orden_operacion_id<>? GROUP BY 1""", (cajon_id, sin_op or 0)):
        out[r["p"]] = out.get(r["p"], 0.0) + float(r["c"] or 0)
    return out


def _cajon_pasos(cajon, por_paso):
    return sorted(set(_pasos_ot(cajon["orden_id"])) | set(por_paso))


def _cajon_terminadas(cajon, por_paso=None):
    """Piezas del cajón que ya hizo la última operación de su OT. Un bulto de
    una recepción de compra (sin OT) ya llega terminado: son todas sus piezas."""
    if not cajon["orden_id"]:
        return float(cajon["cantidad"] or 0)
    pasos = _pasos_ot(cajon["orden_id"])
    if not pasos:
        return 0.0
    if por_paso is None:
        por_paso = _cajon_por_paso(cajon["id"])
    return por_paso.get(pasos[-1], 0.0)


def _cajon_disponible(cajon, paso, por_paso):
    """Piezas del cajón que el paso anterior ya hizo y este paso todavía no."""
    previos = [p for p in _cajon_pasos(cajon, por_paso) if p < paso]
    if not previos:
        return 0.0
    return max(0.0, por_paso.get(previos[-1], 0.0) - por_paso.get(paso, 0.0))


def _cajon_error(cajon, por_paso):
    """Valida un cajón con las cantidades por paso que quedarían: ningún paso
    puede tener más piezas que el anterior, y la última operación no puede
    quedar por debajo de lo que Calidad ya clasificó."""
    if cajon["estado"] == "Baja":
        return f"El cajón {cajon['numero']} está dado de baja"
    pasos = _cajon_pasos(cajon, por_paso)
    for a, b in zip(pasos, pasos[1:]):
        if por_paso.get(b, 0.0) > por_paso.get(a, 0.0) + 0.0001:
            return (f"El cajón {cajon['numero']} quedaría con {por_paso.get(b, 0.0):g} piezas en el paso {b} "
                    f"y solo {por_paso.get(a, 0.0):g} en el paso {a}")
    clasif = float(cajon["cantidad_liberada"] or 0) + float(cajon["cantidad_rechazada"] or 0)
    if clasif > 0 and _cajon_terminadas(cajon, por_paso) < clasif - 0.0001:
        return (f"El cajón {cajon['numero']} ya tiene {clasif:g} piezas clasificadas por Calidad: "
                f"no puede quedar con menos piezas terminadas")
    return None


def _cajon_nuevo(oid, capacidad):
    o = query("""SELECT o.producto_id, m.codigo FROM ordenes o
        JOIN materiales m ON m.id=o.producto_id WHERE o.id=?""", (oid,), one=True)
    numero = siguiente_numero("cajones", f"cajon-{o['codigo']}-", 3, reservar=True)
    return execute("""INSERT INTO cajones (numero,orden_id,orden_origen_id,producto_id,capacidad)
        VALUES (?,?,?,?,?)""", (numero, oid, oid, o["producto_id"], capacidad))


def _llenar_cajones(oid, qty):
    """Primer paso: las piezas OK llenan el cajón abierto de la OT y abren los
    que hagan falta (250 con 100 por cajón -> 100, 100, 50). Devuelve
    [(cajon_id, cantidad)]."""
    prod = query("""SELECT p.capacidad_cajon FROM ordenes o JOIN productos p ON p.id=o.producto_id
        WHERE o.id=?""", (oid,), one=True)
    plan = []
    restante = float(qty)
    while restante > 0.0001:
        caj = query("""SELECT * FROM cajones WHERE orden_id=? AND orden_origen_id=orden_id
            AND estado='En proceso' AND cantidad < capacidad - 0.0001
            AND cantidad_liberada + cantidad_rechazada = 0
            ORDER BY id LIMIT 1""", (oid,), one=True)
        if not caj:
            cap = int(prod["capacidad_cajon"] or 0) if prod else 0
            if cap <= 0:
                # Se borró "piezas por cajón" con la OT en curso: sigue con
                # la capacidad de sus cajones.
                ult = query("SELECT capacidad FROM cajones WHERE orden_id=? ORDER BY id DESC LIMIT 1",
                    (oid,), one=True)
                cap = int(ult["capacidad"]) if ult else 0
            if cap <= 0:
                break
            caj = query("SELECT * FROM cajones WHERE id=?", (_cajon_nuevo(oid, cap),), one=True)
        poner = min(restante, float(caj["capacidad"]) - float(caj["cantidad"]))
        execute("UPDATE cajones SET cantidad=cantidad+? WHERE id=?", (poner, caj["id"]))
        plan.append((caj["id"], poner))
        restante -= poner
    return plan


def _plan_cajones_paso(oid, paso, qty, pedido=None, sin_novedad=None, sin_op=None, parcial=False):
    """Paso que no es el primero: valida en qué cajones se trabajó (`pedido`
    = [{cajon_id, cantidad}]) o, si no vino, los toma en orden (FIFO). Cada
    cajón admite como máximo lo que el paso anterior hizo en él menos lo que
    este paso ya cargó. Devuelve (plan, error)."""
    cajones = query("""SELECT * FROM cajones WHERE orden_id=? AND estado NOT IN ('Baja','En espera')
        ORDER BY id""", (oid,))
    disp = {c["id"]: _cajon_disponible(c, paso, _cajon_por_paso(c["id"], sin_novedad, sin_op))
            for c in cajones}
    por_id = {c["id"]: c for c in cajones}
    if pedido:
        plan, vistos = [], set()
        for it in pedido:
            try:
                cid = int(it.get("cajon_id"))
                cant = float(it.get("cantidad") or 0)
            except (TypeError, ValueError, AttributeError):
                return None, "Cajón o cantidad inválidos"
            if cant <= 0:
                continue
            if cid not in por_id:
                return None, "Uno de los cajones indicados no es de esta OT o no está disponible"
            if cid in vistos:
                return None, f"El cajón {por_id[cid]['numero']} está repetido"
            vistos.add(cid)
            if cant > disp[cid] + 0.0001:
                return None, (f"El cajón {por_id[cid]['numero']} tiene {disp[cid]:g} piezas disponibles "
                              f"para esta operación y se cargan {cant:g}")
            plan.append((cid, cant))
        total = sum(c for _, c in plan)
        if abs(total - qty) > 0.0001:
            return None, f"La suma por cajón ({total:g}) tiene que ser igual a las piezas OK ({qty:g})"
        return plan, None
    plan, restante = [], float(qty)
    for c in cajones:
        tomar = min(restante, disp[c["id"]])
        if tomar > 0.0001:
            plan.append((c["id"], tomar))
            restante -= tomar
    if restante > 0.0001 and not parcial:
        return None, (f"Los cajones de la OT tienen {qty - restante:g} piezas disponibles para esta "
                      f"operación y se cargan {qty:g}")
    return plan, None


def _quitar_lifo(filas, quitar):
    """Saca `quitar` piezas de [(cajon_id, cantidad)] empezando por el último."""
    filas = [list(f) for f in filas]
    for f in reversed(filas):
        if quitar <= 0.0001:
            break
        t = min(f[1], quitar)
        f[1] -= t
        quitar -= t
    return [(c, q) for c, q in filas if q > 0.0001]


def _replan_novedad_cajones(nov_id, oid, oo_id, qty_new, pedido=None):
    """Plan de cajones para una novedad que se edita (o se borra: qty_new=0).
    Devuelve (plan, extra_primer_paso, error): `plan` son las filas que le
    quedan a la novedad y `extra_primer_paso` las piezas a sumar llenando
    cajones (solo en el primer paso). Valida cada cajón afectado antes de
    tocar nada."""
    paso = query("SELECT CAST(orden AS INTEGER) p FROM orden_operaciones WHERE id=?", (oo_id,), one=True)["p"]
    pasos = _pasos_ot(oid)
    primero = bool(pasos) and paso == pasos[0]
    actuales = [(r["cajon_id"], float(r["cantidad"])) for r in query(
        "SELECT cajon_id, cantidad FROM novedad_cajones WHERE novedad_id=? ORDER BY cajon_id", (nov_id,))]
    total = sum(q for _, q in actuales)
    extra = 0.0
    if pedido and not primero and qty_new > 0:
        plan, err = _plan_cajones_paso(oid, paso, qty_new, pedido, sin_novedad=nov_id)
        if err:
            return None, 0.0, err
    elif qty_new < total - 0.0001:
        plan = _quitar_lifo(actuales, total - qty_new)
    elif qty_new > total + 0.0001:
        plan = actuales
        if primero:
            extra = qty_new - total
        else:
            mas, err = _plan_cajones_paso(oid, paso, qty_new - total)
            if err:
                return None, 0.0, err
            d = dict(plan)
            for cid, q in mas:
                d[cid] = d.get(cid, 0.0) + q
            plan = sorted(d.items())
    else:
        plan = actuales
    nuevo = dict(plan)
    for cid in set(nuevo) | {c for c, _ in actuales}:
        cajon = query("SELECT * FROM cajones WHERE id=?", (cid,), one=True)
        por_paso = _cajon_por_paso(cid, sin_novedad=nov_id)
        if nuevo.get(cid, 0.0) > 0:
            por_paso[paso] = por_paso.get(paso, 0.0) + nuevo[cid]
        if dict(actuales).get(cid, 0.0) == nuevo.get(cid, 0.0) and cajon["estado"] != "Baja":
            continue
        err = _cajon_error(cajon, por_paso)
        if err:
            return None, 0.0, err
    return plan, extra, None


def _cajon_recalcular(cid):
    """Recalcula las piezas de entrada y el estado de un cajón."""
    c = query("SELECT * FROM cajones WHERE id=?", (cid,), one=True)
    if not c or not c["orden_id"]:   # los bultos de recepción siguen al lote
        return
    por_paso = _cajon_por_paso(cid)
    cantidad = por_paso[min(por_paso)] if por_paso else 0.0
    estado = c["estado"]
    if estado not in ("Baja", "En espera"):
        term = _cajon_terminadas(c, por_paso)
        clasif = float(c["cantidad_liberada"] or 0) + float(c["cantidad_rechazada"] or 0)
        if cantidad <= 0.0001:
            estado = "Baja"
        elif term > 0.0001 and clasif >= term - 0.0001:
            estado = "Liberado" if float(c["cantidad_liberada"] or 0) > 0 else "Rechazado"
        else:
            estado = "En proceso"
    execute("UPDATE cajones SET cantidad=?, estado=? WHERE id=?", (cantidad, estado, cid))


def _guardar_novedad_cajones(nov_id, oid, plan, extra=0.0):
    """Deja a la novedad con las filas `plan` (+ `extra` piezas llenando
    cajones del primer paso) y recalcula los cajones tocados."""
    tocados = {r["cajon_id"] for r in query("SELECT cajon_id FROM novedad_cajones WHERE novedad_id=?", (nov_id,))}
    execute("DELETE FROM novedad_cajones WHERE novedad_id=?", (nov_id,))
    filas = dict()
    for cid, q in plan:
        filas[cid] = filas.get(cid, 0.0) + q
    if extra > 0.0001:
        # _llenar_cajones ya suma a cajones.cantidad; el recálculo de abajo
        # lo vuelve a derivar de las filas, así que no queda doble.
        for cid, q in _llenar_cajones(oid, extra):
            filas[cid] = filas.get(cid, 0.0) + q
    for cid, q in filas.items():
        if q > 0.0001:
            execute("INSERT INTO novedad_cajones (novedad_id,cajon_id,cantidad) VALUES (?,?,?)", (nov_id, cid, q))
    for cid in tocados | set(filas):
        _cajon_recalcular(cid)


def _lote_pt_ot(oid):
    """Lote de PT de la OT (ver generar_pt_faltante_si_corresponde)."""
    o = query("SELECT numero, producto_id FROM ordenes WHERE id=?", (oid,), one=True)
    if not o or not o["producto_id"]:
        return None
    r = query("""SELECT id FROM lotes WHERE material_id=? AND numero IN (?,?)
        ORDER BY numero=? DESC LIMIT 1""",
        (o["producto_id"], o["numero"], o["numero"] + "-PT", o["numero"]), one=True)
    return r["id"] if r else None


def _cajones_vincular_lote(oid):
    lote_id = _lote_pt_ot(oid)
    if lote_id:
        execute("UPDATE cajones SET lote_id=? WHERE orden_id=? AND lote_id IS NULL", (lote_id, oid))


def _sync_cajones_op_tercerizada(oo_id, usa):
    """Una operación tercerizada no carga novedades: lo que registra como hecho
    (qty_producida) se imputa a cajones. En el primer paso crea/llena
    cajones; en los demás los toma en orden (FIFO) hasta lo disponible. Si
    bajó, se descuenta de los últimos cajones mientras los pasos siguientes
    lo permitan."""
    if not usa:
        return
    oo = query("""SELECT id, orden_id, CAST(orden AS INTEGER) p, qty_producida
        FROM orden_operaciones WHERE id=?""", (oo_id,), one=True)
    if not oo:
        return
    oid = oo["orden_id"]
    pasos = _pasos_ot(oid)
    actuales = [(r["cajon_id"], float(r["cantidad"])) for r in query(
        "SELECT cajon_id, cantidad FROM ott_cajones WHERE orden_operacion_id=? ORDER BY cajon_id", (oo_id,))]
    delta = float(oo["qty_producida"] or 0) - sum(q for _, q in actuales)
    filas = dict(actuales)
    if delta > 0.0001:
        if pasos and oo["p"] == pasos[0]:
            nuevos = _llenar_cajones(oid, delta)
        else:
            nuevos, _ = _plan_cajones_paso(oid, oo["p"], delta, parcial=True)
        for cid, q in nuevos:
            filas[cid] = filas.get(cid, 0.0) + q
    elif delta < -0.0001:
        quitar = -delta
        for cid, q in reversed(actuales):
            if quitar <= 0.0001:
                break
            cajon = query("SELECT * FROM cajones WHERE id=?", (cid,), one=True)
            t = min(q, quitar)
            por_paso = _cajon_por_paso(cid, sin_op=oo_id)
            por_paso[oo["p"]] = por_paso.get(oo["p"], 0.0) + q - t
            if _cajon_error(cajon, por_paso):
                continue
            filas[cid] = q - t
            quitar -= t
        if quitar > 0.0001:
            print(f"[WARN] Operación {oo_id}: {quitar:g} piezas tercerizadas menos que no se "
                  f"pudieron sacar de sus cajones (ya avanzaron en pasos siguientes).")
    else:
        return
    execute("DELETE FROM ott_cajones WHERE orden_operacion_id=?", (oo_id,))
    for cid, q in filas.items():
        if q > 0.0001:
            execute("INSERT INTO ott_cajones (orden_operacion_id,cajon_id,cantidad) VALUES (?,?,?)",
                (oo_id, cid, q))
    for cid in filas:
        _cajon_recalcular(cid)


def _lote_estado_por_cajones(lote_id):
    """Estado del lote derivado de lo que Calidad clasificó en sus cajones."""
    l = query("SELECT * FROM lotes WHERE id=?", (lote_id,), one=True)
    if not l:
        return
    disp = float(l["cantidad_disponible"] or 0)
    act = float(l["cantidad_activa"] or 0)
    rech = float(l["cantidad_rechazada"] or 0)
    if disp <= 0.0001:
        estado = "Agotado"
    elif disp - act - rech > 0.001:
        estado = "Ingresado"
    else:
        estado = "Aprobado" if act > 0.0001 else "Rechazado"
    execute("UPDATE lotes SET estado=? WHERE id=?", (estado, lote_id))


def _sync_cajones_recepcion(lote_id):
    """Los bultos de una recepción (cajones sin OT) reflejan lo que Calidad
    decidió para el lote: lo aprobado se reparte del primer bulto al último y
    lo rechazado sigue en los bultos siguientes. Lo ya remitido de un bulto
    queda siempre como liberado."""
    cajs = query("""SELECT * FROM cajones WHERE lote_id=? AND orden_id IS NULL
        AND estado<>'Baja' ORDER BY id""", (lote_id,))
    l = query("SELECT * FROM lotes WHERE id=?", (lote_id,), one=True)
    if not cajs or not l:
        return
    disp = float(l["cantidad_disponible"] or 0)
    act = float(l["cantidad_activa"] or 0)
    rech_rest = float(l["cantidad_rechazada"] or 0)
    pend = max(0.0, disp - act - rech_rest)
    lib_rest = max(0.0, float(l["cantidad_original"] or 0) - rech_rest - pend)
    for c in cajs:
        cant = float(c["cantidad"] or 0)
        lib = max(min(cant, lib_rest), float(c["cantidad_remitida"] or 0))
        lib_rest = max(0.0, lib_rest - lib)
        rech = min(max(0.0, cant - lib), rech_rest)
        rech_rest -= rech
        if lib + rech >= cant - 0.0001:
            estado = "Liberado" if lib > 0.0001 else "Rechazado"
        else:
            estado = "Ingresado"
        if (abs(lib - float(c["cantidad_liberada"] or 0)) > 0.0001
                or abs(rech - float(c["cantidad_rechazada"] or 0)) > 0.0001 or estado != c["estado"]):
            execute("""UPDATE cajones SET cantidad_liberada=?, cantidad_rechazada=?, estado=?,
                calidad_por=?, calidad_fecha=datetime('now','localtime') WHERE id=?""",
                (lib, rech, estado, session.get("user_id") if has_request_context() else None, c["id"]))


def _lote_es_de_produccion(lote):
    """Lote de una OT (producto terminado o retorno de un tercero): sus cajones
    se arman al declarar la producción, no a mano."""
    num = lote["numero"] or ""
    if num.startswith("Lote-OTT") or query("SELECT 1 FROM ordenes WHERE numero=? OR ?=numero||'-PT'",
                                           (num, num), one=True):
        return True
    return bool(query("SELECT 1 FROM cajones WHERE lote_id=? AND orden_id IS NOT NULL LIMIT 1",
                      (lote["id"],), one=True))


@app.route("/api/lotes/<int:lid>/bultos", methods=["POST"])
@login_required(roles=["admin","almacen","vendedor","calidad"])
def guardar_bultos_lote(lid):
    """Guarda los bultos de una recepción de compra como cajones del lote
    (uno por bulto, con su cantidad). Si el lote ya tenía bultos y todavía no
    salió nada de ellos, se reemplazan."""
    d = request.json or {}
    try:
        cants = [float(x) for x in (d.get("cantidades") or [])]
    except (TypeError, ValueError):
        return jsonify({"error": "Cantidades inválidas"}), 400
    cants = [round(c, 4) for c in cants if c > 0.0001]
    if not cants:
        return jsonify({"error": "Indicá al menos un bulto con cantidad"}), 400
    if len(cants) > 500:
        return jsonify({"error": "Son demasiados bultos (máximo 500)"}), 400
    lote = query("""SELECT l.*, m.codigo mat_codigo FROM lotes l
        JOIN materiales m ON m.id=l.material_id WHERE l.id=?""", (lid,), one=True)
    if not lote:
        return jsonify({"error": "Lote no encontrado"}), 404
    if _lote_es_de_produccion(lote):
        return jsonify({"error": "Este lote es de producción: sus cajones se arman solos al declarar "
                                 "las novedades de la OT."}), 400
    total = float(lote["cantidad_original"] or 0)
    viejos = query("SELECT * FROM cajones WHERE lote_id=? AND orden_id IS NULL AND estado<>'Baja'", (lid,))
    # "agregar": una entrega parcial suma bultos a los que ya tenía el lote;
    # si no, los bultos nuevos reemplazan a los anteriores.
    agregar = bool(d.get("agregar"))
    ya = sum(float(c["cantidad"] or 0) for c in viejos) if agregar else 0.0
    if ya + sum(cants) > total + 0.0001:
        return jsonify({"error": f"Los bultos suman {ya + sum(cants):g} y el lote tiene {total:g}"}), 400
    if not agregar:
        if any(float(c["cantidad_remitida"] or 0) > 0.0001 for c in viejos):
            return jsonify({"error": "De estos bultos ya se remitieron piezas: no se pueden rearmar"}), 400
        for c in viejos:
            execute("DELETE FROM cajones WHERE id=?", (c["id"],))
    cap = int(math.ceil(max(cants)))
    numeros = []
    for q in cants:
        numero = siguiente_numero("cajones", f"cajon-{lote['mat_codigo']}-", 3, reservar=True)
        execute("""INSERT INTO cajones (numero,orden_id,orden_origen_id,producto_id,lote_id,
            capacidad,cantidad,estado,obs) VALUES (?,NULL,NULL,?,?,?,?,'Ingresado',?)""",
            (numero, lote["material_id"], lid, cap, q,
             "Bulto de recepción — " + (lote["referencia_proveedor"] or lote["numero"])))
        numeros.append(numero)
    _sync_cajones_recepcion(lid)
    return jsonify({"ok": True, "cajones": numeros, "sin_bulto": round(total - ya - sum(cants), 4)})


def _remitir_de_cajones(remito_item_id, lote_id, qty):
    """Un remito de un lote con cajones sale de sus cajones liberados, del más
    viejo al más nuevo, y queda anotado de qué cajón salió cada pieza."""
    restante = float(qty)
    for c in query("""SELECT id, cantidad_liberada - cantidad_remitida libre FROM cajones
            WHERE lote_id=? AND cantidad_liberada - cantidad_remitida > 0.0001 ORDER BY id""", (lote_id,)):
        if restante <= 0.0001:
            break
        tomar = min(restante, float(c["libre"]))
        execute("INSERT INTO remito_item_cajones (remito_item_id,cajon_id,cantidad) VALUES (?,?,?)",
            (remito_item_id, c["id"], tomar))
        execute("UPDATE cajones SET cantidad_remitida=cantidad_remitida+? WHERE id=?", (tomar, c["id"]))
        restante -= tomar

# ── Cajones: consulta, calidad, transferencia y baja ─────────────────────────
_CAJON_SQL = """SELECT cj.*, o.numero ot_numero, o.estado ot_estado, oor.numero ot_origen_numero,
        m.codigo producto_codigo, m.descripcion producto_nombre, l.numero lote_numero
    FROM cajones cj
    LEFT JOIN ordenes o ON o.id=cj.orden_id
    LEFT JOIN ordenes oor ON oor.id=cj.orden_origen_id
    JOIN materiales m ON m.id=cj.producto_id
    LEFT JOIN lotes l ON l.id=cj.lote_id"""


def _cajon_dict(c, paso=None):
    d = dict(c)
    por_paso = _cajon_por_paso(c["id"])
    d["terminadas"] = _cajon_terminadas(c, por_paso)
    d["por_paso"] = {str(k): v for k, v in sorted(por_paso.items())}
    if paso is not None:
        d["disponible"] = _cajon_disponible(c, paso, por_paso)
    return d


@app.route("/api/ordenes/<int:oid>/cajones", methods=["GET"])
@login_required()
def get_cajones_ot(oid):
    """Cajones de la OT. Con orden_operacion_id dice si es el primer paso
    (ahí los cajones se llenan solos) o cuánto tiene disponible cada cajón
    para esa operación."""
    oo_id = request.args.get("orden_operacion_id", type=int)
    pasos = _pasos_ot(oid)
    paso, primero = None, False
    if oo_id:
        r = query("SELECT CAST(orden AS INTEGER) p FROM orden_operaciones WHERE id=? AND orden_id=?",
            (oo_id, oid), one=True)
        if r:
            paso = r["p"]
            primero = bool(pasos) and paso == pasos[0]
    rows = query(_CAJON_SQL + " WHERE cj.orden_id=? AND cj.estado<>'Baja' ORDER BY cj.id", (oid,))
    cajones = [_cajon_dict(c, None if primero else paso) for c in rows]
    abierto = next((c for c in cajones if c["estado"] == "En proceso"
                    and c["orden_origen_id"] == c["orden_id"]
                    and c["cantidad"] < c["capacidad"] - 0.0001
                    and c["cantidad_liberada"] + c["cantidad_rechazada"] == 0), None)
    prod = query("""SELECT p.capacidad_cajon FROM ordenes o JOIN productos p ON p.id=o.producto_id
        WHERE o.id=?""", (oid,), one=True)
    return jsonify({"usa_cajones": _ot_usa_cajones(oid), "primer_paso": primero, "paso": paso,
                    "capacidad": prod["capacidad_cajon"] if prod else None,
                    "abierto": abierto, "cajones": cajones})


@app.route("/api/cajones", methods=["GET"])
@login_required()
def get_cajones():
    where, params = [], []
    buscar = (request.args.get("buscar") or "").strip()
    if buscar:
        where.append("""(cj.numero LIKE ? OR o.numero LIKE ? OR m.codigo LIKE ?
            OR m.descripcion LIKE ? OR l.numero LIKE ?)""")
        params += [f"%{buscar}%"] * 5
    for arg, col in (("lote_id", "cj.lote_id"), ("orden_id", "cj.orden_id"), ("estado", "cj.estado")):
        if request.args.get(arg):
            where.append(f"{col}=?")
            params.append(request.args.get(arg))
    sql = _CAJON_SQL + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY cj.id DESC LIMIT 500"
    return jsonify([_cajon_dict(c) for c in query(sql, tuple(params))])


@app.route("/api/cajones/<int:cid>", methods=["GET"])
@login_required()
def get_cajon(cid):
    """Trazabilidad del cajón: OT, lote, producto, piezas por paso, novedades
    (operación, operario, máquina, fecha), lotes de material consumidos en
    esas novedades, decisión de Calidad y remitos con su cliente."""
    c = query(_CAJON_SQL + " WHERE cj.id=?", (cid,), one=True)
    if not c:
        return jsonify({"error": "Cajón no encontrado"}), 404
    d = _cajon_dict(c)
    d["novedades"] = [dict(r) for r in query("""SELECT n.id, n.numero, n.fecha, nc.cantidad,
            oo.nombre operacion, oo.orden paso, o.numero ot_numero,
            e.nombre||' '||e.apellido empleado_nombre, mq.codigo||' — '||mq.nombre maquina_nombre
        FROM novedad_cajones nc
        JOIN novedades_produccion n ON n.id=nc.novedad_id
        JOIN orden_operaciones oo ON oo.id=n.orden_operacion_id
        JOIN ordenes o ON o.id=n.orden_id
        LEFT JOIN empleados e ON e.id=n.empleado_id
        LEFT JOIN maquinas mq ON mq.id=n.maquina_id
        WHERE nc.cajon_id=? ORDER BY CAST(oo.orden AS INTEGER), n.fecha, n.id""", (cid,))]
    d["tercerizadas"] = [dict(r) for r in query("""SELECT oc.cantidad, oo.nombre operacion, oo.orden paso,
            o.numero ot_numero,
            (SELECT GROUP_CONCAT(t.numero, ', ') FROM ordenes_tercerizado t WHERE t.operacion_id=oo.id) ott_numero
        FROM ott_cajones oc
        JOIN orden_operaciones oo ON oo.id=oc.orden_operacion_id
        JOIN ordenes o ON o.id=oo.orden_id
        WHERE oc.cajon_id=? ORDER BY CAST(oo.orden AS INTEGER)""", (cid,))]
    # Una novedad que abarcó varios cajones muestra sus lotes de material en
    # todos ellos: el consumo no se puede repartir por cajón.
    d["materiales"] = [dict(r) for r in query("""SELECT n.numero novedad_numero, l.numero lote_numero,
            m.codigo material_codigo, m.descripcion material,
            SUM(CASE WHEN mv.tipo='salida' THEN mv.cantidad ELSE -mv.cantidad END) cantidad
        FROM novedad_cajones nc
        JOIN novedades_produccion n ON n.id=nc.novedad_id
        JOIN movimientos mv ON (mv.referencia LIKE 'Consumo real por Novedad ' || n.numero || ' %'
                             OR mv.referencia LIKE 'Ajuste consumo ' || n.numero || ' %')
        JOIN lotes l ON l.id=mv.lote_id
        JOIN materiales m ON m.id=mv.material_id
        WHERE nc.cajon_id=?
        GROUP BY n.id, l.id ORDER BY n.id, l.id""", (cid,))]
    u = query("SELECT nombre FROM usuarios WHERE id=?", (c["calidad_por"],), one=True) if c["calidad_por"] else None
    d["calidad_por_nombre"] = u["nombre"] if u else None
    d["remitos"] = [dict(r) for r in query("""SELECT r.id, r.numero, r.fecha, r.estado,
            cl.razon cliente_nombre, ric.cantidad
        FROM remito_item_cajones ric
        JOIN remito_items ri ON ri.id=ric.remito_item_id
        JOIN remitos r ON r.id=ri.remito_id
        LEFT JOIN clientes cl ON cl.id=r.cliente_id
        WHERE ric.cajon_id=? ORDER BY r.id""", (cid,))]
    return jsonify(d)


@app.route("/api/cajones/<int:cid>/calidad", methods=["POST"])
@login_required(roles=["admin","almacen","calidad"])
def calidad_cajon(cid):
    """Calidad libera y/o rechaza piezas terminadas del cajón (valores
    absolutos: se puede liberar una parte y dejar el resto pendiente, o
    corregir/deshacer mientras no se haya remitido). Lo liberado pasa a
    disponible del lote (cantidad_activa) y lo rechazado a su columna
    Rechazado; el estado del lote se deriva de sus cajones."""
    d = request.json or {}
    c = query("SELECT * FROM cajones WHERE id=?", (cid,), one=True)
    if not c:
        return jsonify({"error": "Cajón no encontrado"}), 404
    if c["estado"] in ("Baja", "En espera"):
        return jsonify({"error": f"El cajón está {c['estado'].lower()}"}), 400
    if not c["orden_id"]:
        return jsonify({"error": "Este cajón es un bulto de una recepción: Calidad libera o rechaza "
                                 "el lote completo (Lotes → Gestionar) y los bultos se actualizan solos."}), 400
    term = _cajon_terminadas(c)
    lote_id = c["lote_id"] or _lote_pt_ot(c["orden_id"])
    if term <= 0.0001 or not lote_id:
        return jsonify({"error": "El cajón todavía no tiene piezas terminadas por la última operación"}), 400
    try:
        lib = float(d.get("cantidad_liberada", c["cantidad_liberada"]) or 0)
        rech = float(d.get("cantidad_rechazada", c["cantidad_rechazada"]) or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "Cantidades inválidas"}), 400
    if lib < 0 or rech < 0:
        return jsonify({"error": "Las cantidades no pueden ser negativas"}), 400
    if lib + rech > term + 0.0001:
        return jsonify({"error": f"Liberado ({lib:g}) + rechazado ({rech:g}) no puede superar las "
                                 f"{term:g} piezas terminadas del cajón"}), 400
    if lib < float(c["cantidad_remitida"] or 0) - 0.0001:
        return jsonify({"error": f"Del cajón ya se remitieron {float(c['cantidad_remitida']):g} piezas: "
                                 f"no se puede liberar menos"}), 400
    lote = query("SELECT * FROM lotes WHERE id=?", (lote_id,), one=True)
    d_lib = lib - float(c["cantidad_liberada"] or 0)
    d_rech = rech - float(c["cantidad_rechazada"] or 0)
    if d_lib < 0 and float(lote["cantidad_activa"] or 0) + d_lib < -0.0001:
        return jsonify({"error": "El lote ya no tiene esas piezas liberadas disponibles "
                                 "(salieron por otro movimiento)"}), 400
    execute("""UPDATE lotes SET cantidad_activa=MAX(0, COALESCE(cantidad_activa,0)+?),
        cantidad_rechazada=MAX(0, COALESCE(cantidad_rechazada,0)+?) WHERE id=?""", (d_lib, d_rech, lote_id))
    execute("""UPDATE cajones SET cantidad_liberada=?, cantidad_rechazada=?, calidad_por=?,
        calidad_fecha=datetime('now','localtime'), calidad_obs=?, lote_id=? WHERE id=?""",
        (lib, rech, session["user_id"], d.get("obs", c["calidad_obs"]), lote_id, cid))
    _cajon_recalcular(cid)
    _lote_estado_por_cajones(lote_id)
    execute("""INSERT INTO movimientos (material_id,lote_id,tipo,cantidad,referencia,usuario_id)
        VALUES (?,?,?,?,?,?)""",
        (c["producto_id"], lote_id, "ajuste", term,
         f"Calidad cajón {c['numero']} → Liberado:{lib:g} Rechazado:{rech:g} "
         f"Pendiente:{term - lib - rech:g} | Lote {lote['numero']}"
         + (" | Obs: " + d["obs"] if d.get("obs") else ""), session["user_id"]))
    c = query("SELECT estado FROM cajones WHERE id=?", (cid,), one=True)
    return jsonify({"ok": True, "estado": c["estado"], "cantidad_liberada": lib,
                    "cantidad_rechazada": rech, "pendiente": term - lib - rech})


@app.route("/api/cajones/<int:cid>/destinos", methods=["GET"])
@login_required()
def get_cajon_destinos(cid):
    """OTs abiertas del mismo producto a las que se puede pasar el cajón."""
    c = query("SELECT * FROM cajones WHERE id=?", (cid,), one=True)
    if not c:
        return jsonify({"error": "Cajón no encontrado"}), 404
    return jsonify([dict(r) for r in query("""SELECT id, numero, estado, cantidad FROM ordenes
        WHERE producto_id=? AND id<>? AND estado NOT IN ('Cancelada','Completada')
        ORDER BY id DESC""", (c["producto_id"], c["orden_id"]))])


@app.route("/api/cajones/<int:cid>/transferir", methods=["POST"])
@login_required(roles=["admin","operario"])
def transferir_cajon(cid):
    """Un cajón en espera (su OT se canceló) pasa a otra OT abierta del mismo
    producto, que sigue desde la operación donde quedó: el tope de cada paso
    sale de lo que el cajón ya hizo en la OT anterior."""
    d = request.json or {}
    c = query("SELECT * FROM cajones WHERE id=?", (cid,), one=True)
    if not c:
        return jsonify({"error": "Cajón no encontrado"}), 404
    if c["estado"] != "En espera":
        return jsonify({"error": "Solo se pueden pasar a otra OT los cajones en espera (de una OT cancelada)"}), 400
    try:
        destino = int(d.get("orden_id"))
    except (TypeError, ValueError):
        return jsonify({"error": "Elegí la OT destino"}), 400
    o = query("SELECT id, numero, producto_id, estado FROM ordenes WHERE id=?", (destino,), one=True)
    if not o or o["id"] == c["orden_id"]:
        return jsonify({"error": "OT destino inválida"}), 400
    if o["producto_id"] != c["producto_id"]:
        return jsonify({"error": "La OT destino tiene que ser del mismo producto"}), 400
    if o["estado"] in ("Cancelada", "Completada"):
        return jsonify({"error": "La OT destino tiene que estar abierta"}), 400
    por_paso = _cajon_por_paso(cid)
    if por_paso and not [p for p in _pasos_ot(destino) if p > max(por_paso)]:
        return jsonify({"error": f"La OT {o['numero']} no tiene operaciones después del paso "
                                 f"{max(por_paso)}, donde quedó el cajón"}), 400
    origen = query("SELECT numero FROM ordenes WHERE id=?", (c["orden_id"],), one=True)
    quien = query("SELECT nombre FROM usuarios WHERE id=?", (session["user_id"],), one=True)
    nota = (f"{datetime.now().strftime('%Y-%m-%d %H:%M')} pasado de {origen['numero']} a {o['numero']}"
            f" por {quien['nombre'] if quien else '—'}")
    execute("""UPDATE cajones SET orden_id=?, lote_id=NULL, estado='En proceso',
        obs=CASE WHEN COALESCE(obs,'')='' THEN ? ELSE obs || char(10) || ? END WHERE id=?""",
        (destino, nota, nota, cid))
    _cajon_recalcular(cid)
    return jsonify({"ok": True})


@app.route("/api/cajones/<int:cid>/baja", methods=["POST"])
@login_required(roles=["admin"])
def baja_cajon(cid):
    """Da de baja un cajón en espera (sus piezas no siguen). El número no se
    reutiliza."""
    d = request.json or {}
    c = query("SELECT * FROM cajones WHERE id=?", (cid,), one=True)
    if not c:
        return jsonify({"error": "Cajón no encontrado"}), 404
    if c["estado"] != "En espera":
        return jsonify({"error": "Solo se pueden dar de baja los cajones en espera (de una OT cancelada)"}), 400
    quien = query("SELECT nombre FROM usuarios WHERE id=?", (session["user_id"],), one=True)
    nota = (f"{datetime.now().strftime('%Y-%m-%d %H:%M')} baja por {quien['nombre'] if quien else '—'}"
            + (f": {d['obs']}" if d.get("obs") else ""))
    execute("""UPDATE cajones SET estado='Baja',
        obs=CASE WHEN COALESCE(obs,'')='' THEN ? ELSE obs || char(10) || ? END WHERE id=?""", (nota, nota, cid))
    return jsonify({"ok": True})

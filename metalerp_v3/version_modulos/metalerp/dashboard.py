"""Tableros: operativo, económico, requerimientos e indicadores de compras."""
from .nucleo import (app, date, datetime, jsonify, login_required, modulo_requerido, query,
    request, solo_con_monetario, timedelta)

# ── Dashboard operativo — rendimiento semanal ─────────────────────────────────
@app.route("/api/dashboard/rendimiento_semanal")
@login_required()
def dashboard_rendimiento_semanal():
    semanas = [dict(r) for r in query("""
        SELECT strftime('%Y-%W', fecha) semana,
               MIN(fecha) fecha_inicio,
               ROUND(AVG(rendimiento_pct),1) avg_rend,
               COUNT(*) novedades,
               ROUND(SUM(cantidad_producida),1) total_prod
        FROM novedades_produccion
        WHERE fecha >= date('now','-26 weeks')
        GROUP BY strftime('%Y-%W', fecha)
        ORDER BY semana""")]
    # Current week label
    import datetime
    hoy = datetime.date.today()
    semana_actual = hoy.strftime('%Y-%W')
    return jsonify({"semanas": semanas, "semana_actual": semana_actual})

# ── Dashboard económico — facturación por cliente por mes ─────────────────────
@app.route("/api/dashboard/facturacion_por_cliente")
@login_required()
@solo_con_monetario
def dashboard_facturacion_por_cliente():
    import datetime
    hoy = datetime.date.today()
    anio = hoy.year
    # Facturación pasada (presupuestos facturados)
    facturado = [dict(r) for r in query("""
        SELECT strftime('%Y-%m', p.creado) mes,
               c.razon cliente,
               ROUND(SUM(p.total),2) total
        FROM presupuestos p
        JOIN clientes c ON c.id=p.cliente_id
        WHERE p.estado='Facturado'
          AND strftime('%Y', p.creado)=?
        GROUP BY mes, c.id
        ORDER BY mes, c.razon""", (str(anio),))]
    # Pedidos futuros (OC confirmadas/en proceso con items sin facturar)
    pedidos = [dict(r) for r in query("""
        SELECT strftime('%Y-%m', COALESCE(i.fecha_deseada, oc.fecha_entrega, oc.creado)) mes,
               c.razon cliente,
               ROUND(SUM(i.cantidad * i.precio_unit),2) total
        FROM ordenes_cliente_items i
        JOIN ordenes_cliente oc ON oc.id=i.orden_cliente_id
        JOIN clientes c ON c.id=oc.cliente_id
        WHERE oc.estado IN ('Recibida','Confirmada','En proceso')
          AND strftime('%Y', COALESCE(i.fecha_deseada, oc.fecha_entrega, oc.creado))=?
        GROUP BY mes, c.id
        ORDER BY mes, c.razon""", (str(anio),))]
    # Ratio empleados
    emps = [dict(r) for r in query("""
        SELECT COALESCE(tipo,'Sin tipo') tipo, COUNT(*) cantidad
        FROM empleados WHERE activo=1 GROUP BY tipo ORDER BY cantidad DESC""")]
    return jsonify({
        "anio": anio,
        "mes_actual": hoy.strftime('%Y-%m'),
        "facturado": facturado,
        "pedidos": pedidos,
        "empleados": emps,
    })

# ── Dashboard operativo (producción, calidad, inventario) ─────────────────────
@app.route("/api/dashboard/operativo")
@login_required()
def dashboard_operativo():
    return jsonify({
        # Métricas superiores
        "ot_activas":       query("SELECT COUNT(*) c FROM ordenes WHERE estado IN ('Pendiente','En proceso')", one=True)["c"],
        "ot_completadas_mes": query("SELECT COUNT(*) c FROM ordenes WHERE estado='Completada' AND strftime('%Y-%m',actualizado)=strftime('%Y-%m','now')", one=True)["c"],
        "stock_critico":    query("SELECT COUNT(*) c FROM materiales WHERE stock<=stock_min AND stock_min>0", one=True)["c"],
        "lotes_pendientes": query("SELECT COUNT(*) c FROM lotes WHERE estado='Ingresado'", one=True)["c"],
        "maquinas_fuera":   query("SELECT COUNT(*) c FROM maquinas WHERE estado!='Operativa'", one=True)["c"],
        "tickets_abiertos": query("SELECT COUNT(*) c FROM tickets_reparacion WHERE estado='Abierto'", one=True)["c"],
        # OTs por estado
        "ots_por_estado": [dict(r) for r in query(
            "SELECT estado, COUNT(*) cantidad FROM ordenes GROUP BY estado ORDER BY cantidad DESC")],
        # Eficiencia productiva últimos 30 días
        "eficiencia_ops": dict(query(
            "SELECT AVG(rendimiento_pct) avg_rend, COUNT(*) total_novedades "
            "FROM novedades_produccion WHERE fecha>=date('now','-30 days')", one=True) or {}),
        # Alertas stock
        "alertas_mat": [dict(r) for r in query(
            "SELECT codigo,descripcion,stock,stock_min,unidad FROM materiales "
            "WHERE stock<=stock_min AND stock_min>0 ORDER BY (stock_min-stock) DESC LIMIT 8")],
        # Lotes pendientes liberación
        "lotes_ingresados": [dict(r) for r in query(
            """SELECT l.numero,m.descripcion mat_desc,l.cantidad_disponible,m.unidad,l.fecha_ingreso
               FROM lotes l JOIN materiales m ON m.id=l.material_id
               WHERE l.estado='Ingresado' ORDER BY l.fecha_ingreso LIMIT 6""")],
        # Mantenimiento próximo
        "mantto_proximo": _mant_alertas()[:5],
        # Tickets abiertos
        "alertas_tkt": [dict(r) for r in query(
            "SELECT m.nombre maquina,t.descripcion,t.prioridad FROM tickets_reparacion t "
            "JOIN maquinas m ON m.id=t.maquina_id WHERE t.estado='Abierto' LIMIT 5")],
        # OTs con vencimiento cercano
        "ots_urgentes": [dict(r) for r in query(
            "SELECT o.numero,COALESCE(pr.nombre,o.descripcion) producto,c.razon cliente,"
            "o.estado,o.fecha_entrega FROM ordenes o "
            "LEFT JOIN clientes c ON c.id=o.cliente_id "
            "LEFT JOIN productos pr ON pr.id=o.producto_id "
            "WHERE o.estado IN ('Pendiente','En proceso') AND o.fecha_entrega IS NOT NULL "
            "AND o.fecha_entrega<=date('now','+5 days') ORDER BY o.fecha_entrega LIMIT 5")],
        # OTs recientes
        "ots_recientes": [dict(r) for r in query(
            "SELECT o.numero,COALESCE(pr.nombre,o.descripcion) producto,c.razon cliente,"
            "o.estado,o.fecha_entrega FROM ordenes o "
            "LEFT JOIN clientes c ON c.id=o.cliente_id "
            "LEFT JOIN productos pr ON pr.id=o.producto_id "
            "ORDER BY o.id DESC LIMIT 6")],
    })

# ── Clasificación de material_proceso en categorías amplias (para gráficos) ───
# El campo material_proceso guarda la especificación puntual de cada renglón
# (ej. "SAE 1010 LC...", "6063 T5", "ANILLADO DE CAÑOS"), no una categoría.
# Para agrupar como en el Excel original (TRATAMIENTO SUPERFICIAL / MATERIA
# PRIMA / PROCESO) se usa la categoría del PROVEEDOR (proveedores.categoria_compra,
# igual que en la hoja "DATOS INDICADORES DE COMPRAS" del Excel real, donde la
# agrupación es por proveedor y no por texto libre). Si el proveedor no tiene
# categoria_compra cargada, se cae a un heurístico por palabras clave sobre el
# texto de material_proceso como respaldo.
_KW_TRAT_SUP = (
    "tratamiento superficial", "tratamiento termico", "tratamiento térmico",
    "anodizado", "niquelado", "cataforesis", "pintura", "pintado", "pint.",
    "pint ", "cincado", "cinc ", "zincado", "fosfat", "cromad", "cromo",
    "pavonado", "plateado", "dorado", "pulido quimico", "pulido químico",
    "galvaniz", "templado", "temple", "revenido", "arenado", "decapado",
    "desplacado", "granallado",
)
_KW_MATERIA_PRIMA = (
    "sae ", "sae1", "sae4", "sae 1", "sae 4", "aisi", "chapa", "barra",
    "alambre", "tubo", "laton", "latón", "bronce", "6063", "6061", "nylon",
    "acero", "hierro", "aluminio", "inox",
)

def _clasificar_material_proceso_texto(valor):
    """Heurístico de respaldo por palabras clave, usado sólo cuando el
    proveedor del requerimiento no tiene categoria_compra cargada."""
    if not valor:
        return "SIN CATEGORÍA"
    v = valor.strip().lower()
    if v.startswith("sae") or v.startswith("aisi"):
        return "MATERIA PRIMA"
    if any(kw in v for kw in _KW_TRAT_SUP):
        return "TRATAMIENTO SUPERFICIAL"
    if any(kw in v for kw in _KW_MATERIA_PRIMA):
        return "MATERIA PRIMA"
    return "PROCESO"

def _clasificar_requerimiento(material_proceso, categoria_compra_proveedor):
    """Categoría amplia de un requerimiento para los gráficos del dashboard.
    Prioridad: categoria_compra del proveedor (fuente confiable, como en el
    Excel original) > heurístico por texto de material_proceso (respaldo)."""
    if categoria_compra_proveedor:
        return categoria_compra_proveedor
    return _clasificar_material_proceso_texto(material_proceso)


# ── Calidad de un requerimiento productivo, en base al LOTE real de stock ────
# (no al campo manual cumple_calidad/cant_no_conforme). Fuente única de verdad
# usada por dashboard_requerimientos, dashboard_indicadores_compras y el
# listado de Requerimientos productivos, para que los 3 módulos coincidan.
#
# Vínculo con el lote (ya existía en el sistema, sin columnas nuevas):
#   - Requerimiento de COMPRA (materia prima): rp.origen_item_id
#     -> ordenes_compra_items.id -> ordenes_compra_items.lote_id -> lotes.id
#   - Requerimiento TERCERIZADO (proceso/tratamiento): rp.numero
#     -> ordenes_tercerizado.numero -> ordenes_tercerizado.lote_retorno_id -> lotes.id
#
# Regla:
#   - Lote con decisión de Calidad (estado Aprobado/Rechazado/Agotado):
#     % aprobado = 1 - lotes.cantidad_rechazada / lotes.cantidad_original
#     aprobado=1 si % >= 0.95, si no incidente (aprobado=0). evaluable=True.
#     Se mide por lo rechazado y NO por cantidad_activa: esa columna tambien
#     se descuenta cuando el lote se consume (remito, novedad), con lo cual
#     un lote sin un solo rechazo contaba como incidente apenas se usaba.
#   - Lote todavía 'Ingresado' (sin decisión de Calidad): NO evaluable —
#     queda "pendiente de calidad", no cuenta ni como aprobado ni incidente.
#   - Sin lote vinculado (históricos del Excel, cargas manuales sin OC/OTT
#     de por medio): fallback al criterio manual (cant_no_conforme==0), y
#     SÍ entra al cálculo (evaluable=True) — a diferencia del caso anterior.
def _calidad_requerimientos_bulk(rows):
    """rows: iterable de dicts/Row con al menos id, numero, origen_item_id,
    cumple_calidad. Devuelve {rp_id: {evaluable, aprobado, origen, lote_estado, lote_pct}}."""
    rows = list(rows)
    if not rows:
        return {}
    origen_ids = sorted({r["origen_item_id"] for r in rows if r["origen_item_id"]})
    numeros = sorted({r["numero"] for r in rows if r["numero"]})

    lote_by_origen = {}
    if origen_ids:
        ph = ",".join("?" * len(origen_ids))
        for oci in query(f"SELECT id, lote_id FROM ordenes_compra_items WHERE id IN ({ph})", tuple(origen_ids)):
            if oci["lote_id"]:
                lote_by_origen[oci["id"]] = oci["lote_id"]

    lote_by_numero = {}
    if numeros:
        ph = ",".join("?" * len(numeros))
        for ott in query(f"SELECT numero, lote_retorno_id FROM ordenes_tercerizado WHERE numero IN ({ph})", tuple(numeros)):
            if ott["lote_retorno_id"]:
                lote_by_numero[ott["numero"]] = ott["lote_retorno_id"]

    lote_ids = sorted(set(lote_by_origen.values()) | set(lote_by_numero.values()))
    lotes_info = {}
    if lote_ids:
        ph = ",".join("?" * len(lote_ids))
        for l in query(f"SELECT id, estado, cantidad_activa, cantidad_original, "
                       f"cantidad_rechazada FROM lotes WHERE id IN ({ph})", tuple(lote_ids)):
            lotes_info[l["id"]] = l

    out = {}
    for r in rows:
        lote_id = lote_by_origen.get(r["origen_item_id"]) or lote_by_numero.get(r["numero"])
        lote = lotes_info.get(lote_id) if lote_id else None
        if lote:
            if lote["estado"] in ("Aprobado", "Rechazado", "Agotado"):
                orig = float(lote["cantidad_original"] or 0)
                # Se mide por lo RECHAZADO, no por lo que queda en stock:
                # cantidad_activa tambien baja al consumir el lote (remitos,
                # novedades), asi que usarla hacia que un lote impecable ya
                # usado contara como incidente de calidad. cantidad_rechazada
                # solo la mueve Calidad.
                rech = float(lote["cantidad_rechazada"] or 0)
                pct = max(0.0, 1.0 - (rech / orig)) if orig > 0 else 0.0
                out[r["id"]] = {"evaluable": True, "aprobado": 1 if pct >= 0.95 else 0,
                                 "origen": "lote", "lote_estado": lote["estado"], "lote_pct": round(pct, 4)}
            else:  # 'Ingresado' — todavía sin decisión de Calidad
                out[r["id"]] = {"evaluable": False, "aprobado": None,
                                 "origen": "lote", "lote_estado": lote["estado"], "lote_pct": None}
        else:
            cc = r["cumple_calidad"]
            out[r["id"]] = {"evaluable": True, "aprobado": cc if cc is not None else None,
                             "origen": "manual", "lote_estado": None, "lote_pct": None}
    return out


# ── Dashboard de requerimientos productivos ───────────────────────────────────
@app.route("/api/dashboard/requerimientos")
@login_required()
def dashboard_requerimientos():
    rows = query("""SELECT rp.*, c.razon cliente_nombre, p.razon proveedor_nombre, p.categoria_compra
        FROM requerimientos_productivos rp
        LEFT JOIN clientes c ON c.id=rp.cliente_id
        LEFT JOIN proveedores p ON p.id=rp.proveedor_id""")
    hoy = date.today()
    calidad_map = _calidad_requerimientos_bulk(rows)
    rows_dict = [dict(r) for r in rows]
    for d in rows_dict:
        d["_calidad"] = calidad_map.get(d["id"], {"evaluable": True, "aprobado": d.get("cumple_calidad"),
                                                    "origen": "manual", "lote_estado": None, "lote_pct": None})

    activos, vencidos, proximos, entregados_mes, anulados = [], [], [], 0, 0
    cumple_fecha_ok = cumple_fecha_tot = 0
    cumple_cant_ok = cumple_cant_tot = 0
    cumple_calidad_ok = cumple_calidad_tot = 0
    pendientes_calidad = 0
    por_proveedor = {}

    for d in rows_dict:
        estado = _calc_estado_req(d.get("f_estimada"), d.get("f_entrega"), d.get("estado"))
        d["estado"] = estado

        if estado == "ANULADO":
            anulados += 1
            continue
        if estado == "ENTREGADO":
            if d.get("f_entrega") and str(d["f_entrega"])[:7] == hoy.strftime("%Y-%m"):
                entregados_mes += 1
        else:
            activos.append(d)
            proveedor = d.get("proveedor_nombre") or "Sin proveedor"
            por_proveedor[proveedor] = por_proveedor.get(proveedor, 0) + 1
            if estado == "VENCIDO":
                try:
                    fe = datetime.strptime(str(d["f_estimada"])[:10], "%Y-%m-%d").date()
                    d["dias_vencido"] = (hoy - fe).days
                except (ValueError, TypeError):
                    d["dias_vencido"] = 0
                vencidos.append(d)
            elif estado == "PROXIMO" and d.get("f_estimada"):
                try:
                    fe = datetime.strptime(str(d["f_estimada"])[:10], "%Y-%m-%d").date()
                    if fe <= hoy + timedelta(days=7):
                        proximos.append(d)
                except (ValueError, TypeError):
                    pass

        if d.get("cumple_fecha") is not None:
            cumple_fecha_tot += 1
            cumple_fecha_ok += d["cumple_fecha"]
        if d.get("cumple_cantidad") is not None:
            cumple_cant_tot += 1
            cumple_cant_ok += d["cumple_cantidad"]
        if d.get("f_entrega"):
            if d["_calidad"]["evaluable"] and d["_calidad"]["aprobado"] is not None:
                cumple_calidad_tot += 1
                cumple_calidad_ok += d["_calidad"]["aprobado"]
            elif not d["_calidad"]["evaluable"]:
                pendientes_calidad += 1

    vencidos.sort(key=lambda x: x["dias_vencido"], reverse=True)
    proximos.sort(key=lambda x: x.get("f_estimada") or "")

    def pct(ok, tot):
        return round(100 * ok / tot) if tot else None

    # ── Series mensuales para gráficos (últimos 12 meses con datos, por categoría) ──
    MESES_LBL = ["ENE","FEB","MAR","ABR","MAY","JUN","JUL","AGO","SEP","OCT","NOV","DIC"]
    entregados = [d for d in rows_dict if d["f_entrega"]]
    for d in entregados:
        d["_categoria"] = _clasificar_requerimiento(d.get("material_proceso"), d.get("categoria_compra"))
    meses_con_datos = sorted({str(d["f_entrega"])[:7] for d in entregados})[-12:]

    # Orden fijo (igual que el Excel original) y sólo categorías con datos
    ORDEN_CAT = ["TRATAMIENTO SUPERFICIAL", "MATERIA PRIMA", "PROCESO", "SIN CATEGORÍA"]
    categorias = [c for c in ORDEN_CAT if any(d["_categoria"] == c for d in entregados)]

    def serie_mensual(campo):
        # {categoria: [pct_mes1, pct_mes2, ...]}, más "PROMEDIO MENSUAL"
        series = {}
        for cat in categorias:
            valores = []
            for ym in meses_con_datos:
                grupo = [d for d in entregados
                         if d["_categoria"] == cat
                         and str(d["f_entrega"])[:7] == ym and d.get(campo) is not None]
                valores.append(pct(sum(g[campo] for g in grupo), len(grupo)) if grupo else None)
            series[cat] = valores
        promedio = []
        for i in range(len(meses_con_datos)):
            vals = [series[cat][i] for cat in categorias if series[cat][i] is not None]
            promedio.append(round(sum(vals) / len(vals)) if vals else None)
        series["PROMEDIO MENSUAL"] = promedio
        return series

    def serie_mensual_calidad():
        # Igual que serie_mensual, pero basada en _calidad (lote real / fallback
        # manual) en vez del campo cumple_calidad crudo, y excluyendo los
        # requerimientos con lote todavía pendiente de clasificar en Calidad.
        series = {}
        for cat in categorias:
            valores = []
            for ym in meses_con_datos:
                grupo = [d for d in entregados
                         if d["_categoria"] == cat and str(d["f_entrega"])[:7] == ym
                         and d["_calidad"]["evaluable"] and d["_calidad"]["aprobado"] is not None]
                valores.append(pct(sum(g["_calidad"]["aprobado"] for g in grupo), len(grupo)) if grupo else None)
            series[cat] = valores
        promedio = []
        for i in range(len(meses_con_datos)):
            vals = [series[cat][i] for cat in categorias if series[cat][i] is not None]
            promedio.append(round(sum(vals) / len(vals)) if vals else None)
        series["PROMEDIO MENSUAL"] = promedio
        return series

    meses_lbl_out = [MESES_LBL[int(ym.split("-")[1]) - 1] for ym in meses_con_datos]

    # ── Performance por proveedor: % cumplimiento fecha / cantidad / calidad,
    # sobre los requerimientos entregados (f_entrega no nula). Reusa d["_calidad"]
    # ya calculado arriba con _calidad_requerimientos_bulk (misma fuente que
    # dashboard_indicadores_compras) para que ambos módulos coincidan. ──
    def performance_por_proveedor():
        por_prov = {}
        for d in entregados:
            prov = d.get("proveedor_nombre") or "Sin proveedor"
            por_prov.setdefault(prov, []).append(d)

        out = []
        for prov, items in por_prov.items():
            fecha_vals = [d["cumple_fecha"] for d in items if d.get("cumple_fecha") is not None]
            cant_vals = [d["cumple_cantidad"] for d in items if d.get("cumple_cantidad") is not None]
            calidad_vals = [d["_calidad"]["aprobado"] for d in items
                             if d["_calidad"]["evaluable"] and d["_calidad"]["aprobado"] is not None]
            out.append({
                "proveedor": prov,
                "entregados": len(items),
                "cumple_fecha_pct": pct(sum(fecha_vals), len(fecha_vals)),
                "cumple_cantidad_pct": pct(sum(cant_vals), len(cant_vals)),
                "cumple_calidad_pct": pct(sum(calidad_vals), len(calidad_vals)),
            })
        # Sólo proveedores con al menos un dato evaluable en alguno de los 3 ejes,
        # ordenados por volumen de entregas (los más relevantes primero).
        out = [o for o in out if o["cumple_fecha_pct"] is not None
               or o["cumple_cantidad_pct"] is not None or o["cumple_calidad_pct"] is not None]
        out.sort(key=lambda o: o["entregados"], reverse=True)
        return out[:10]

    # ── Cantidad pedida vs entregada, top 10 por cantidad pedida entre los activos ──
    barras = sorted(
        [{"numero": d["numero"], "codigo": d.get("codigo"),
          "cantidad_pedida": d.get("cantidad_pedida") or 0,
          "cantidad_entregada": d.get("cantidad_entregada") or 0}
         for d in rows_dict if (d.get("cantidad_pedida") or 0) > 0],
        key=lambda x: x["cantidad_pedida"], reverse=True)[:10]

    return jsonify({
        "activos":         len(activos),
        "vencidos":        len(vencidos),
        "proximos_7d":     len(proximos),
        "entregados_mes":  entregados_mes,
        "cumple_fecha_pct":   pct(cumple_fecha_ok, cumple_fecha_tot),
        "cumple_cantidad_pct": pct(cumple_cant_ok, cumple_cant_tot),
        "cumple_calidad_pct":  pct(cumple_calidad_ok, cumple_calidad_tot),
        "pendientes_calidad":  pendientes_calidad,
        "top_vencidos": [
            {"numero": d["numero"], "cliente": d.get("cliente_nombre"),
             "codigo": d.get("codigo"), "proveedor": d.get("proveedor_nombre"),
             "f_estimada": d.get("f_estimada"), "dias_vencido": d["dias_vencido"]}
            for d in vencidos[:8]],
        "top_proximos": [
            {"numero": d["numero"], "cliente": d.get("cliente_nombre"),
             "codigo": d.get("codigo"), "proveedor": d.get("proveedor_nombre"),
             "f_estimada": d.get("f_estimada")}
            for d in proximos[:8]],
        "por_proveedor": sorted(
            [{"proveedor": k, "cantidad": v} for k, v in por_proveedor.items()],
            key=lambda x: x["cantidad"], reverse=True)[:8],
        "graficos": {
            "meses": meses_lbl_out,
            "objetivo_pct": 90,
            "indice_calidad": serie_mensual_calidad(),
            "cumplimiento_entrega": serie_mensual("cumple_fecha"),
            "cantidad_pedida_vs_entregada": barras,
            "performance_por_proveedor": performance_por_proveedor(),
        },
    })

# ── Indicadores de compras por proveedor (réplica hoja "DATOS INDICADORES DE
# COMPRAS" del Excel) ──────────────────────────────────────────────────────
# Por cada proveedor, mes a mes: Lotes Entregados, Entregados a tiempo,
# Aprobados, Incidentes de Calidad, y los 3 índices:
#   CE  (Cumplimiento de Entrega) = entregados_a_tiempo / entregados
#   IC  (Índice de Calidad)       = aprobados/entregados - incidentes_rate*0.1
#   IPP (Índice Performance Prov) = promedio(CE, IC)
# Nota: el Excel original resta también "Observados/Rechazados/Desviados"
# cargados a mano; acá no existen esos campos en la base, así que quedan
# absorbidos en "aprobados" (cumple_calidad) — el resultado es equivalente
# cuando esos campos manuales están en 0, que es el caso normal.
@app.route("/api/dashboard/indicadores_compras")
@login_required()
@modulo_requerido("indicadores_compras")
def dashboard_indicadores_compras():
    anio = request.args.get("anio", str(date.today().year))
    rows = query("""SELECT rp.*, p.razon proveedor_nombre, p.categoria_compra
        FROM requerimientos_productivos rp
        JOIN proveedores p ON p.id=rp.proveedor_id
        WHERE rp.f_entrega IS NOT NULL AND substr(rp.f_entrega,1,4)=?""", (anio,))
    rows = [dict(r) for r in rows]
    for d in rows:
        d["_categoria"] = _clasificar_requerimiento(d.get("material_proceso"), d.get("categoria_compra"))
    # Calidad real basada en el lote (con fallback manual para los sin vínculo),
    # misma fuente única que usa dashboard_requerimientos — ver _calidad_requerimientos_bulk.
    calidad_map = _calidad_requerimientos_bulk(rows)
    for d in rows:
        d["_calidad"] = calidad_map.get(d["id"], {"evaluable": True, "aprobado": d.get("cumple_calidad"),
                                                    "origen": "manual", "lote_estado": None, "lote_pct": None})

    MESES_LBL = ["Ene","Feb","Mar","Abr","May","Jun","Jul","Ago","Sep","Oct","Nov","Dic"]
    ORDEN_CAT = ["TRATAMIENTO SUPERFICIAL", "MATERIA PRIMA", "PROCESO", "SIN CATEGORÍA"]

    def calc_indicadores(items):
        meses = []
        tot_entregados = tot_a_tiempo = tot_aprobados = tot_evaluados = tot_pendientes = 0
        for m in range(1, 13):
            ym = f"{anio}-{m:02d}"
            grupo = [d for d in items if str(d["f_entrega"])[:7] == ym]
            entregados = len(grupo)
            a_tiempo = sum(1 for d in grupo if d.get("cumple_fecha") == 1)
            # "Aprobados"/"Incidentes" sólo salen de los evaluables (lote con decisión
            # de Calidad, o sin lote vinculado con fallback manual). Los que tienen
            # lote todavía 'Ingresado' quedan afuera y se cuentan como "pendientes".
            evaluados = [d for d in grupo if d["_calidad"]["evaluable"] and d["_calidad"]["aprobado"] is not None]
            aprobados = sum(d["_calidad"]["aprobado"] for d in evaluados)
            n_eval = len(evaluados)
            incidentes = n_eval - aprobados
            pendientes = entregados - n_eval
            ce = round(a_tiempo / entregados, 4) if entregados else None
            ic = round((aprobados / n_eval) - (incidentes / n_eval * 0.1), 4) if n_eval else None
            ipp = round((ce + ic) / 2, 4) if (ce is not None and ic is not None) else None
            tot_entregados += entregados; tot_a_tiempo += a_tiempo; tot_aprobados += aprobados
            tot_evaluados += n_eval; tot_pendientes += pendientes
            meses.append({
                "mes": MESES_LBL[m - 1], "entregados": entregados, "a_tiempo": a_tiempo,
                "aprobados": aprobados, "incidentes": incidentes, "pendientes": pendientes,
                "ce": ce, "ic": ic, "ipp": ipp,
            })
        tot_incidentes = tot_evaluados - tot_aprobados
        ce_t = round(tot_a_tiempo / tot_entregados, 4) if tot_entregados else None
        ic_t = round((tot_aprobados / tot_evaluados) - (tot_incidentes / tot_evaluados * 0.1), 4) if tot_evaluados else None
        ipp_t = round((ce_t + ic_t) / 2, 4) if (ce_t is not None and ic_t is not None) else None
        return meses, {
            "entregados": tot_entregados, "a_tiempo": tot_a_tiempo, "aprobados": tot_aprobados,
            "incidentes": tot_incidentes, "pendientes": tot_pendientes, "ce": ce_t, "ic": ic_t, "ipp": ipp_t,
        }

    categorias_out = []
    categorias_presentes = [c for c in ORDEN_CAT if any(d["_categoria"] == c for d in rows)]
    for cat in categorias_presentes:
        items_cat = [d for d in rows if d["_categoria"] == cat]
        proveedores_cat = sorted({d["proveedor_nombre"] for d in items_cat})
        proveedores_out = []
        for prov in proveedores_cat:
            items_prov = [d for d in items_cat if d["proveedor_nombre"] == prov]
            meses, total = calc_indicadores(items_prov)
            proveedores_out.append({"proveedor": prov, "meses": meses, "total": total})
        proveedores_out.sort(key=lambda p: p["total"]["entregados"], reverse=True)
        categorias_out.append({"categoria": cat, "proveedores": proveedores_out})

    return jsonify({"anio": anio, "meses_lbl": MESES_LBL, "categorias": categorias_out})

# ── Dashboard económico / financiero ──────────────────────────────────────────
@app.route("/api/dashboard/economico")
@login_required()
@solo_con_monetario
def dashboard_economico():
    return jsonify({
        # Métricas superiores
        "presupuestos_mes":  query("SELECT COUNT(*) c FROM presupuestos WHERE strftime('%Y-%m',creado)=strftime('%Y-%m','now')", one=True)["c"],
        "facturacion_mes":   query("SELECT COALESCE(SUM(total),0) s FROM presupuestos WHERE estado='Facturado' AND strftime('%Y-%m',creado)=strftime('%Y-%m','now')", one=True)["s"],
        "pedidos_activos":   query("SELECT COUNT(*) c FROM ordenes_cliente WHERE estado IN ('Recibida','Confirmada','En proceso')", one=True)["c"],
        "valor_pedidos":     query("SELECT COALESCE(SUM(i.cantidad*i.precio_unit),0) s FROM ordenes_cliente_items i JOIN ordenes_cliente oc ON oc.id=i.orden_cliente_id WHERE oc.estado IN ('Recibida','Confirmada','En proceso')", one=True)["s"],
        "ocs_compra_pend":   query("SELECT COUNT(*) c FROM ordenes_compra WHERE estado IN ('Pendiente aprobacion','Aprobada','Enviada')", one=True)["c"],
        "monto_compras_pend":query("SELECT COALESCE(SUM(monto_total),0) s FROM ordenes_compra WHERE estado IN ('Pendiente aprobacion','Aprobada','Enviada')", one=True)["s"],
        # Facturación últimos 6 meses
        "facturacion_historico": [dict(r) for r in query(
            "SELECT strftime('%Y-%m',creado) mes, COALESCE(SUM(total),0) total, COUNT(*) cantidad "
            "FROM presupuestos WHERE estado='Facturado' AND creado>=date('now','-6 months') "
            "GROUP BY mes ORDER BY mes")],
        # Presupuestos por estado
        "presupuestos_estado": [dict(r) for r in query(
            "SELECT estado, COUNT(*) cantidad, COALESCE(SUM(total),0) total "
            "FROM presupuestos GROUP BY estado ORDER BY total DESC")],
        # Pedidos de clientes pendientes
        "pedidos_cliente": [dict(r) for r in query(
            """SELECT oc.numero,c.razon cliente,oc.estado,oc.creado,
               COALESCE(SUM(i.cantidad*i.precio_unit),0) valor
               FROM ordenes_cliente oc
               JOIN clientes c ON c.id=oc.cliente_id
               LEFT JOIN ordenes_cliente_items i ON i.orden_cliente_id=oc.id
               WHERE oc.estado IN ('Recibida','Confirmada','En proceso')
               GROUP BY oc.id ORDER BY oc.creado DESC LIMIT 8""")],
        # OCs de compra pendientes
        "compras_pendientes": [dict(r) for r in query(
            "SELECT oc.numero,p.razon proveedor,oc.estado,oc.monto_total,oc.fecha_entrega_est "
            "FROM ordenes_compra oc JOIN proveedores p ON p.id=oc.proveedor_id "
            "WHERE oc.estado IN ('Pendiente aprobacion','Aprobada','Enviada') "
            "ORDER BY oc.creado DESC LIMIT 6")],
        # Costo de OTs activas (valor en producción)
        "valor_produccion":  query(
            "SELECT COALESCE(SUM(costo_mat+costo_mo),0) s FROM ordenes "
            "WHERE estado IN ('Pendiente','En proceso')", one=True)["s"],
        # Top clientes por facturación
        "top_clientes": [dict(r) for r in query(
            """SELECT c.razon,COUNT(*) pedidos,COALESCE(SUM(i.cantidad*i.precio_unit),0) valor
               FROM ordenes_cliente oc JOIN clientes c ON c.id=oc.cliente_id
               LEFT JOIN ordenes_cliente_items i ON i.orden_cliente_id=oc.id
               GROUP BY c.id ORDER BY valor DESC LIMIT 5""")],
    })


# Funciones de otras áreas. Van al final a propósito: así cada módulo ya
# definió todo lo suyo cuando otro lo importa, y no hay problemas de
# importación circular. Se usan recién al atender pedidos.
from .maquinas import _mant_alertas
from .requerimientos import _calc_estado_req

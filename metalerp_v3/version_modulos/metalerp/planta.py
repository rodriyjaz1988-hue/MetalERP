"""Tablets de planta, bandeja de registros, procesador, tablero en vivo y
lectores de huella."""
from .nucleo import (_json, _rol_base, app, BASE_DIR, datetime, execute, g, get_db,
    get_local_ip, hash_pw, jsonify, login_required, os, query, re, request, secrets,
    session, siguiente_numero, threading, timedelta, wraps)

# ══ Tablets de planta (etapa 1: producción) ═══════════════════════════════════
# Una tablet por máquina, en modo kiosco, entra sin usuario: se identifica con
# un token propio (Sistema → Tablets de planta). Lo que carga el operario va a
# la bandeja (planta_bandeja) y un procesador ÚNICO lo convierte en novedad con
# la misma lógica de siempre (POST /api/novedades), de a un registro por vez.
#
#   tablet --POST /api/tablet/registros--> planta_bandeja (solo INSERT, uuid único)
#   procesador (un hilo) --> /api/novedades --> Procesado (con la NOV) o Error
#
# Un reenvío del mismo registro (corte de Wi-Fi antes del OK) no duplica: el
# uuid lo genera la tablet y la bandeja lo tiene UNIQUE. Los errores de
# validación (OT cancelada, sin lote, etc.) quedan en "Error" para que un
# administrador corrija y reprocese; no se reintentan solos.

PLANTA_TIPOS = {"produccion", "parada"}
# Motivos de parada que elige el operario al poner Pausa en la tablet. Son los
# mismos códigos de Trabajo no productivo (CODIGOS_PARADA_MAQUINA en app.html):
# se usa la lista del sector de la máquina si la categoría se llama igual, y si
# no la de CNC. Cada pausa queda como un TNP del operario.
PLANTA_MOTIVOS_PARADA = {
    "CNC": ["MANTENIMIENTO", "PUESTA EN MARCHA", "ALMUERZO - CENA", "LIMPIEZA DEL SECTOR", "LIMPIEZA INTERIOR",
        "CAMBIAR INSERTO", "GIRAR INSERTO", "CORREGIR MEDIDA", "CAMBIAR BARRA", "AGREGAR SOLUBLE", "CAMBIO DE OPERADOR",
        "FALTA DE OPERADOR", "PROBLEMAS CON ALIMENTADOR", "CAMBIO DE PREPARACION", "CORTE Y DESPUNTE DE BARRAS", "BAÑO",
        "ROTURA DE HTAS", "CAMBIO DE INSERTO EN OTRA MAQUINA", "EXPLICACION / REUNION", "FALTA DE PREPARACION",
        "MOVER PIEZAS", "FALTA DE MATERIAL", "ESPERAR AL ENCARGADO / PEDIR INSERTO", "REPASAR PIEZAS", "DESCARGAR MATERIAL"],
    "CORTADORAS": ["MANTENIMIENTO", "PUESTA EN MARCHA", "ALMUERZO - CENA", "LIMPIEZA DEL SECTOR", "LIMPIEZA DE CORTADORA",
        "FALTA DE PREPARACION", "MOVER PIEZAS", "CORREGIR MEDIDA", "CAMBIAR BARRAS", "FALTA DE MATERIAL", "CAMBIO DE OPERADOR",
        "FALTA DE OPERADOR", "PROBLEMAS CON PISTONES", "CAMBIO DE PREPARACION", "ESPERAR AL ENCARGADO", "BAÑO",
        "REPASAR PIEZAS", "DESCARGAR MATERIAL", "EXPLICACION / REUNION", "CONTAR PIEZAS", "PEDIR ELEMENTOS DE SEGURIDAD",
        "ENTREGAR PZ A CONTROL", "CAMBIO DE SIERRA", "EMITIR DOCUMENTACION", "ARMADO DE PLANILLAS"],
    "CORTADORA LASER": ["PRODUCCION", "MANTENIMIENTO", "PUESTA EN MARCHA", "ALMUERZO - CENA", "CREAR PROGRAMA",
        "MODIFICAR PROGRAMA", "CAMBIO DE TUBO DE GAS", "CAMBIO DE PREPARACION", "CAMBIO DE MATERIAL", "CORRECCION DE MEDIDAS",
        "ESPERAR AL ENCARGADO", "BAÑO", "PEDIR ELEMENTOS DE SEGURIDAD", "ALARMA DE MAQUINA", "EXPLICACION / REUNION",
        "LEVANTAR PIEZAS DE BATEA", "CORTAR SOBRANTES", "ESPERAR REPOSICION DE MATERIA PRIMA (CLARK)",
        "LIMPIEZA DE LENTE Y BOQUILLA", "CORTE DE PRUEBA"],
    "BALANCINES": ["MANTENIMIENTO", "PUESTA EN MARCHA", "ALMUERZO - CENA", "LIMPIEZA DEL SECTOR", "LIMPIEZA DE MATRIZ",
        "FALTA DE PREPARACION", "MOVER PIEZAS", "CORREGIR MEDIDA", "CAMBIAR ROLLO", "FALTA DE MATERIAL", "CAMBIO DE OPERADOR",
        "FALTA DE OPERADOR", "PROBLEMAS CON ALIMENTADOR", "CAMBIO DE PREPARACION", "ESPERAR AL ENCARGADO", "BAÑO",
        "REPASAR PIEZAS", "DESCARGAR MATERIAL", "EXPLICACION / REUNION", "CONTAR PIEZAS", "PEDIR ELEMENTOS DE SEGURIDAD",
        "ENTREGAR PZ A CONTROL", "PESAR DESPERDICIO / RECORTES (COBRE, LATON)", "EMITIR DOCUMENTACION", "ARMADO DE PLANILLAS"],
}


def _planta_motivos_parada(maquina_id):
    c = query("""SELECT cm.nombre FROM maquinas m JOIN categorias_maquina cm ON cm.id=m.categoria_id
        WHERE m.id=?""", (maquina_id,), one=True)
    nombre = str(c["nombre"] or "").strip().upper() if c else ""
    return PLANTA_MOTIVOS_PARADA.get(nombre) or PLANTA_MOTIVOS_PARADA["CNC"]
# Si la novedad no se puede cargar se reintenta sola sin límite: a los 1, 3 y 5
# minutos y después cada 5 minutos, hasta que entre (por ejemplo cuando vuelve
# y se aprueba el lote de una OTT) o el supervisor la corrija o descarte. Solo
# queda en Error si la operación o el operario ya no existen. La falta de
# lote no cuenta: el registro espera hasta que producción asigne el lote a la
# OT y entonces se carga solo (y consume el material en ese momento).
PLANTA_REINTENTOS_MIN = (1, 3, 5)
PLANTA_ERRORES_LOTE = ("Falta vincular un lote", "Stock disponible insuficiente en lote")
_planta_visto = {}                    # tablet_id -> última vez que consultó (en memoria)
_planta_aviso = threading.Event()     # despierta al procesador cuando entra algo
_planta_hilo = None


def _planta_tablet_actual():
    tok = (request.headers.get("X-Tablet-Token") or "").strip()
    if not tok:
        return None
    return query("""SELECT t.*, m.codigo maquina_codigo, m.nombre maquina_nombre
        FROM planta_tablets t LEFT JOIN maquinas m ON m.id=t.maquina_id
        WHERE t.token=? AND t.activa=1""", (tok,), one=True)


def tablet_requerida(f):
    @wraps(f)
    def wrapped(*a, **kw):
        t = _planta_tablet_actual()
        if not t:
            return jsonify({"error": "Tablet no habilitada. Pedile al administrador el enlace de esta máquina.",
                            "sin_token": True}), 401
        g.tablet = t
        _planta_visto[t["id"]] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return f(*a, **kw)
    return wrapped


@app.route("/tablet")
def tablet_pagina():
    # Sin login: la página no trae datos, todo pasa por /api/tablet/* con el token.
    with open(os.path.join(BASE_DIR, "templates", "tablet.html"), encoding="utf-8") as f:
        return f.read(), 200, {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store"}


def _planta_registro_dict(r):
    try:
        datos = _json.loads(r["datos"] or "{}")
    except ValueError:
        datos = {}
    return {"id": r["id"], "uuid": r["uuid"], "tipo": r["tipo"], "estado": r["estado"],
            "error": r["error"], "hora_operario": r["hora_operario"], "recibido": r["recibido"],
            "procesado": r["procesado"], "novedad_id": r["novedad_id"],
            "novedad_numero": r["novedad_numero"] if "novedad_numero" in r.keys() else None,
            "espera": r["espera"] if "espera" in r.keys() else None,
            "intentos": r["intentos"], "reintentar_desde": r["reintentar_desde"] if "reintentar_desde" in r.keys() else None,
            "datos": datos}


def _planta_operaciones_abiertas(maquina_id=None, sin_maquina=False):
    """Operaciones propias abiertas de OT Pendiente / En proceso (de una
    máquina, las que no tienen máquina, o todas), las de entrega más próxima
    primero."""
    sql = """SELECT oo.id, oo.orden_id, oo.orden paso, oo.nombre, oo.estado,
            oo.qty_requerida, oo.qty_producida, oo.tiempo_ciclo_seg,
            o.numero ot_numero, o.estado ot_estado, o.fecha_entrega,
            p.codigo pieza_codigo, p.nombre pieza_nombre
        FROM orden_operaciones oo
        JOIN ordenes o ON o.id=oo.orden_id
        LEFT JOIN productos p ON p.id=o.producto_id
        WHERE o.estado IN ('Pendiente','En proceso')
          AND COALESCE(oo.es_tercerizada,0)=0
          AND oo.estado!='Completada'"""
    params = ()
    if maquina_id is not None:
        sql += " AND oo.maquina_id=?"
        params = (maquina_id,)
    elif sin_maquina:
        sql += " AND oo.maquina_id IS NULL"
    sql += " ORDER BY o.fecha_entrega IS NULL, o.fecha_entrega, o.numero, CAST(oo.orden AS REAL)"
    return [dict(r) for r in query(sql, params)]


@app.route("/api/tablet/estado")
@tablet_requerida
def tablet_estado():
    """Todo lo que la pantalla necesita: máquina, operarios, operaciones
    abiertas (las de la máquina; todas si no tiene ninguna asignada) y el
    estado de los últimos registros que mandó esta tablet."""
    t = g.tablet
    empleados = [dict(r) for r in query("""SELECT id, legajo, nombre, apellido, turno
        FROM empleados WHERE activo=1 ORDER BY apellido, nombre""")]
    ops = _planta_operaciones_abiertas(t["maquina_id"])
    por_maquina = bool(ops)
    if not ops:
        ops = _planta_operaciones_abiertas()
    else:
        # Además de las de su máquina, las que todavía no tienen máquina
        # asignada (la tablet las muestra aparte, debajo).
        ops += [dict(o, sin_maquina=True) for o in _planta_operaciones_abiertas(sin_maquina=True)]
    regs = [_planta_registro_dict(r) for r in query("""SELECT b.*, n.numero novedad_numero
        FROM planta_bandeja b LEFT JOIN novedades_produccion n ON n.id=b.novedad_id
        WHERE b.tablet_id=? ORDER BY b.id DESC LIMIT 20""", (t["id"],))]
    return jsonify({"tablet": {"id": t["id"], "nombre": t["nombre"]},
                    "maquina": {"id": t["maquina_id"], "codigo": t["maquina_codigo"], "nombre": t["maquina_nombre"]},
                    "por_maquina": por_maquina, "empleados": empleados, "operaciones": ops,
                    "motivos_parada": _planta_motivos_parada(t["maquina_id"]),
                    "registros": regs, "hora_servidor": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})


# ── Tablero de planta (en vivo) ──────────────────────────────────────────────
# Cada tablet manda cada pocos segundos lo que está mostrando: operario,
# operación, produciendo o en pausa y por qué. Queda solo en memoria: si el
# servidor se reinicia, las tablets lo vuelven a mandar en la vuelta siguiente.
# El tablero (/tablero-planta) lo junta con lo declarado hoy en la bandeja.
_planta_vivo = {}                     # tablet_id -> estado que mandó + hora en que llegó
PLANTA_VIVO_CAMPOS = ("pantalla", "empleado_id", "empleado", "orden_operacion_id", "pausado", "motivo",
                      "pausa_seg", "trabajado_seg", "ok", "nok", "en_cola")
PLANTA_VIVO_VENCE_SEG = 30           # sin noticias de la tablet en ese tiempo = desconectada


@app.route("/api/tablet/vivo", methods=["POST"])
@tablet_requerida
def tablet_vivo():
    d = request.get_json(silent=True) or {}
    _planta_vivo[g.tablet["id"]] = dict({k: d.get(k) for k in PLANTA_VIVO_CAMPOS}, visto=datetime.now())
    return jsonify({"ok": True})


@app.route("/tablero-planta")
@login_required(roles=["admin"])
def tablero_planta_pagina():
    with open(os.path.join(BASE_DIR, "templates", "tablero_planta.html"), encoding="utf-8") as f:
        return f.read(), 200, {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store"}


def _num(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


@app.route("/api/planta/tablero")
@login_required(roles=["admin"])
def planta_tablero():
    ahora = datetime.now()
    hoy = ahora.strftime("%Y-%m-%d")
    tot = {"ok": 0.0, "nok": 0.0, "min": 0.0, "paradas": 0, "paradas_min": 0.0}
    por_tablet, motivos = {}, {}
    for r in query("""SELECT tablet_id, tipo, datos FROM planta_bandeja
            WHERE estado!='Descartado' AND SUBSTR(COALESCE(hora_operario, recibido), 1, 10)=?""", (hoy,)):
        try:
            d = _json.loads(r["datos"] or "{}")
        except ValueError:
            continue
        h = por_tablet.setdefault(r["tablet_id"], {"ok": 0.0, "nok": 0.0, "min": 0.0, "paradas": 0, "paradas_min": 0.0})
        if r["tipo"] == "parada":
            m = _num(d.get("minutos"))
            for x in (h, tot):
                x["paradas"] += 1
                x["paradas_min"] += m
            mot = str(d.get("motivo") or "Sin motivo")
            motivos[mot] = motivos.get(mot, 0.0) + m
        else:
            for x in (h, tot):
                x["ok"] += _num(d.get("cantidad_ok"))
                x["nok"] += _num(d.get("cantidad_nok"))
                x["min"] += _num(d.get("tiempo_min"))
    tablets, resumen = [], {}
    for t in query("""SELECT t.id, t.nombre, m.codigo maquina_codigo, m.nombre maquina_nombre
            FROM planta_tablets t LEFT JOIN maquinas m ON m.id=t.maquina_id
            WHERE t.activa=1 ORDER BY m.codigo, t.nombre"""):
        v = _planta_vivo.get(t["id"])
        edad = (ahora - v["visto"]).total_seconds() if v else None
        op = None
        if v is None or edad > PLANTA_VIVO_VENCE_SEG:
            estado = "Desconectada"
        elif v.get("pantalla") == "produciendo" and v.get("orden_operacion_id"):
            estado = "En pausa" if v.get("pausado") else "Produciendo"
        elif v.get("empleado_id"):
            estado = "Eligiendo trabajo"
        else:
            estado = "Sin operario"
        if estado in ("Produciendo", "En pausa"):
            o = query("""SELECT oo.orden paso, oo.nombre, oo.qty_requerida, oo.qty_producida, oo.tiempo_ciclo_seg,
                    o.numero ot, p.codigo pieza_codigo, p.nombre pieza_nombre
                FROM orden_operaciones oo JOIN ordenes o ON o.id=oo.orden_id
                LEFT JOIN productos p ON p.id=o.producto_id WHERE oo.id=?""", (v["orden_operacion_id"],), one=True)
            if o:
                op = dict(o, paso=f"{_num(o['paso']):g}",
                          pieza=" · ".join(x for x in (o["pieza_codigo"], o["pieza_nombre"]) if x))
        vivo = None
        if v and estado != "Desconectada":
            vivo = {k: v.get(k) for k in PLANTA_VIVO_CAMPOS}
            # Los segundos se cuentan desde que llegó el aviso, no con el reloj de la tablet.
            for k in ("pausa_seg", "trabajado_seg"):
                if vivo.get(k) is not None:
                    vivo[k] = _num(vivo[k]) + (edad if (k == "pausa_seg") == bool(v.get("pausado")) else 0)
        resumen[estado] = resumen.get(estado, 0) + 1
        tablets.append({"id": t["id"], "nombre": t["nombre"], "maquina_codigo": t["maquina_codigo"],
                        "maquina_nombre": t["maquina_nombre"], "estado": estado, "vivo": vivo, "operacion": op,
                        "ultima_conexion": _planta_visto.get(t["id"]), "hoy": por_tablet.get(t["id"], {})})
    return jsonify({"tablets": tablets, "resumen": resumen, "hoy": tot,
                    "motivos": [{"motivo": k, "min": round(m, 1)} for k, m in sorted(motivos.items(), key=lambda x: -x[1])[:8]],
                    "hora_servidor": ahora.strftime("%Y-%m-%d %H:%M:%S")})


@app.route("/api/tablet/registros", methods=["POST"])
@tablet_requerida
def tablet_registrar():
    """Solo anota en la bandeja y responde: la tablet no espera a que se
    procese. Un uuid repetido devuelve OK con duplicado=True."""
    d = request.get_json(silent=True) or {}
    uid = str(d.get("uuid") or "").strip()
    if not re.fullmatch(r"[0-9a-fA-F-]{16,64}", uid):
        return jsonify({"error": "Registro sin identificador válido"}), 400
    tipo = d.get("tipo") or "produccion"
    if tipo not in PLANTA_TIPOS:
        return jsonify({"error": f"Tipo de registro desconocido: {tipo}"}), 400
    datos = d.get("datos")
    if not isinstance(datos, dict):
        return jsonify({"error": "Registro sin datos"}), 400
    hora = str(d.get("hora") or "")[:19] or None
    db = get_db()
    cur = db.execute("""INSERT OR IGNORE INTO planta_bandeja (uuid, tablet_id, tipo, datos, hora_operario)
        VALUES (?,?,?,?,?)""", (uid, g.tablet["id"], tipo, _json.dumps(datos, ensure_ascii=False), hora))
    db.commit()
    _planta_aviso.set()
    return jsonify({"ok": True, "duplicado": cur.rowcount == 0})


# ── Procesador único ─────────────────────────────────────────────────────────

def _planta_fecha(hora_operario, recibido):
    """La hora real de carga en la tablet, salvo que el reloj de la tablet
    esté muy corrido (más de 12 h contra la hora en que llegó)."""
    try:
        h = datetime.strptime(hora_operario, "%Y-%m-%d %H:%M:%S")
        r = datetime.strptime(recibido, "%Y-%m-%d %H:%M:%S")
        if abs((h - r).total_seconds()) <= 12 * 3600:
            return hora_operario
    except (TypeError, ValueError):
        pass
    return recibido


def _planta_marca(rid):
    return f"[tablet #{rid}]"


def _planta_procesar(rid):
    """Convierte un registro de la bandeja en novedad. Devuelve True si quedó
    resuelto (Procesado o Error) y False si hay que reintentar más tarde."""
    with app.app_context():
        db = get_db()
        r = db.execute("""SELECT b.*, t.nombre tablet_nombre, t.maquina_id, t.creado_por tablet_usuario
            FROM planta_bandeja b JOIN planta_tablets t ON t.id=b.tablet_id WHERE b.id=?""", (rid,)).fetchone()
        if not r or r["estado"] not in ("Pendiente", "Procesando"):
            return True
        try:
            d = _json.loads(r["datos"] or "{}")
        except ValueError:
            d = {}

        def error(msg):
            db.execute("""UPDATE planta_bandeja SET estado='Error', error=?, intentos=intentos+1,
                procesado=datetime('now','localtime') WHERE id=?""", (msg[:500], rid))
            db.commit()
            return True

        if r["tipo"] == "parada":
            return _planta_procesar_parada(db, r, d, error)

        op = db.execute("SELECT id, orden_id FROM orden_operaciones WHERE id=?",
                        (d.get("orden_operacion_id"),)).fetchone()
        if not op:
            return error("La operación ya no existe")
        emp = db.execute("SELECT id, turno, nombre, apellido FROM empleados WHERE id=?",
                         (d.get("empleado_id"),)).fetchone()
        if not emp:
            return error("El operario ya no existe")
        usr = db.execute("SELECT id, username, nombre FROM usuarios WHERE id=?", (r["tablet_usuario"],)).fetchone() \
            or db.execute("SELECT id, username, nombre FROM usuarios WHERE rol='admin' ORDER BY id LIMIT 1").fetchone()
        obs = (d.get("obs") or "").strip()
        payload = {
            "orden_id": op["orden_id"], "orden_operacion_id": op["id"],
            "empleado_id": emp["id"], "maquina_id": r["maquina_id"], "turno": emp["turno"],
            "cantidad_producida": d.get("cantidad_ok") or 0,
            "piezas_observadas": d.get("cantidad_nok") or 0,
            "tiempo_real_min": d.get("tiempo_min") or 0,
            "tiempo_perdido": d.get("tiempo_perdido_min") or 0,
            "fecha": _planta_fecha(r["hora_operario"], r["recibido"]),
            "obs": f"{r['tablet_nombre']} {_planta_marca(rid)}" + (" · ingresó con huella" if d.get("huella_id") else "")
                   + (f" · sin huella, autorizó {_planta_admin_nombre(d.get('admin_id'))}" if d.get("admin_id") else "")
                   + (f" · {obs}" if obs else ""),
        }
        db.execute("UPDATE planta_bandeja SET estado='Procesando' WHERE id=?", (rid,))
        db.commit()
        intentos = r["intentos"] or 0

    try:
        with app.test_request_context("/api/novedades", method="POST", json=payload):
            session.update({"user_id": usr["id"], "username": usr["username"], "nombre": usr["nombre"],
                            "rol": "operario", "rol_nombre": "Tablet de planta"})
            resp = app.full_dispatch_request()
            cuerpo = resp.get_json(silent=True) or {}
            codigo = resp.status_code
    except Exception as e:  # base bloqueada, etc.: se reintenta
        cuerpo, codigo = {"error": f"Error interno: {e}"}, 500

    with app.app_context():
        db = get_db()
        if codigo < 300 and cuerpo.get("id"):
            db.execute("""UPDATE planta_bandeja SET estado='Procesado', novedad_id=?, error=NULL,
                intentos=intentos+1, procesado=datetime('now','localtime') WHERE id=?""", (cuerpo["id"], rid))
            db.commit()
            return True
        msg = str(cuerpo.get("error") or f"HTTP {codigo}")[:500]
        if codigo < 500 and any(t in msg for t in PLANTA_ERRORES_LOTE):
            db.execute("""UPDATE planta_bandeja SET estado='Pendiente', espera='lote', espera_ref=?, error=?,
                reintentar_desde=NULL WHERE id=?""", (_planta_firma_lotes(db, payload["orden_id"]), msg, rid))
            db.commit()
            return True
        intentos += 1
        minutos = PLANTA_REINTENTOS_MIN[min(intentos, len(PLANTA_REINTENTOS_MIN)) - 1]
        prox = (datetime.now() + timedelta(minutes=minutos)).strftime("%Y-%m-%d %H:%M:%S")
        db.execute("""UPDATE planta_bandeja SET estado='Pendiente', error=?, intentos=?, reintentar_desde=?
            WHERE id=?""", (msg, intentos, prox, rid))
        db.commit()
        return True


def _planta_procesar_parada(db, r, d, error):
    """Una pausa con motivo de la tablet queda como Trabajo no productivo del
    operario. El TNP y el Procesado del registro van en la misma transacción,
    así un corte en el medio no lo carga dos veces."""
    motivo = str(d.get("motivo") or "").strip()[:80]
    try:
        minutos = round(float(d.get("minutos") or 0), 1)
    except (TypeError, ValueError):
        minutos = 0
    if not motivo or minutos <= 0:
        return error("Parada sin motivo o sin tiempo")
    if not db.execute("SELECT 1 FROM empleados WHERE id=?", (d.get("empleado_id"),)).fetchone():
        return error("El operario ya no existe")
    maq = db.execute("SELECT nombre FROM maquinas WHERE id=?", (r["maquina_id"],)).fetchone()
    op = db.execute("""SELECT oo.orden, oo.nombre, o.numero FROM orden_operaciones oo
        JOIN ordenes o ON o.id=oo.orden_id WHERE oo.id=?""", (d.get("orden_operacion_id"),)).fetchone()
    partes = [motivo, maq["nombre"] if maq else r["tablet_nombre"]]
    if op:
        partes.append(f"{op['numero']} paso {float(op['orden'] or 0):g} {op['nombre']}")
    desc = " · ".join(p for p in partes if p) + " · tablet"
    usr = r["tablet_usuario"] or (db.execute("SELECT id FROM usuarios WHERE rol='admin' ORDER BY id LIMIT 1").fetchone() or [None])[0]
    numero = siguiente_numero("trabajo_no_productivo", "TNP-", 5, reservar=True)
    tid = db.execute("""INSERT INTO trabajo_no_productivo (numero, empleado_id, descripcion, tiempo_min, fecha, creado_por)
        VALUES (?,?,?,?,?,?)""", (numero, d.get("empleado_id"), desc, minutos,
        _planta_fecha(d.get("desde"), r["recibido"]), usr)).lastrowid
    d = dict(d, tnp_id=tid, tnp_numero=numero)
    db.execute("""UPDATE planta_bandeja SET estado='Procesado', datos=?, error=NULL, intentos=intentos+1,
        procesado=datetime('now','localtime') WHERE id=?""", (_json.dumps(d, ensure_ascii=False), r["id"]))
    db.commit()
    return True


def _planta_firma_lotes(db, orden_id):
    """Resumen de los lotes asignados a la OT: si cambia, se asignó algo."""
    f = db.execute("""SELECT COUNT(*) n, COALESCE(MAX(id),0) m, COALESCE(SUM(cantidad_usada),0) s
        FROM orden_lotes WHERE orden_id=?""", (orden_id,)).fetchone()
    return f"{f['n']}|{f['m']}|{f['s']}"


def _planta_revisar_esperas():
    """Los que esperan lote vuelven a la cola cuando a su OT le asignaron lote."""
    with app.app_context():
        db = get_db()
        cambio = False
        for r in db.execute("SELECT id, datos, espera_ref FROM planta_bandeja WHERE estado='Pendiente' AND espera='lote'").fetchall():
            try:
                oid = _json.loads(r["datos"] or "{}").get("orden_operacion_id")
            except ValueError:
                continue
            op = db.execute("SELECT orden_id FROM orden_operaciones WHERE id=?", (oid,)).fetchone()
            if not op or _planta_firma_lotes(db, op["orden_id"]) != r["espera_ref"]:
                db.execute("""UPDATE planta_bandeja SET espera=NULL, espera_ref=NULL, intentos=0,
                    reintentar_desde=NULL WHERE id=?""", (r["id"],))
                cambio = True
        if cambio:
            db.commit()


def _planta_recuperar():
    """Al arrancar: un registro que quedó 'Procesando' (se cortó la luz en el
    medio) se da por Procesado si su novedad llegó a crearse; si no, vuelve a
    Pendiente. Así nunca se carga dos veces."""
    with app.app_context():
        db = get_db()
        for r in db.execute("SELECT id FROM planta_bandeja WHERE estado='Procesando'").fetchall():
            n = db.execute("SELECT id FROM novedades_produccion WHERE obs LIKE ? ORDER BY id DESC LIMIT 1",
                           (f"%{_planta_marca(r['id'])}%",)).fetchone()
            if n:
                db.execute("""UPDATE planta_bandeja SET estado='Procesado', novedad_id=?,
                    procesado=datetime('now','localtime') WHERE id=?""", (n["id"], r["id"]))
            else:
                db.execute("UPDATE planta_bandeja SET estado='Pendiente' WHERE id=?", (r["id"],))
        # Los que quedaron en Error por el viejo tope de 3 reintentos vuelven a
        # intentarse (los de operación u operario borrado siguen en Error).
        db.execute("""UPDATE planta_bandeja SET estado='Pendiente', reintentar_desde=NULL, procesado=NULL
            WHERE estado='Error' AND intentos>3 AND error NOT IN ('La operación ya no existe', 'El operario ya no existe')""")
        db.commit()


def _planta_bucle():
    _planta_recuperar()
    espera = 2
    revision = datetime.min
    while True:
        _planta_aviso.wait(espera)
        _planta_aviso.clear()
        try:
            if (datetime.now() - revision).total_seconds() > 10:
                revision = datetime.now()
                _planta_revisar_esperas()
            with app.app_context():
                ids = [r["id"] for r in get_db().execute(
                    """SELECT id FROM planta_bandeja WHERE estado='Pendiente' AND espera IS NULL
                       AND (reintentar_desde IS NULL OR reintentar_desde<=?) ORDER BY id LIMIT 200""",
                    (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),)).fetchall()]
            espera = 2
            for rid in ids:
                if not _planta_procesar(rid):
                    espera = 10     # problema transitorio: dar un respiro antes de reintentar
                    break
        except Exception as e:
            print(f"  [tablets] error en el procesador: {e}")
            espera = 10


def iniciar_procesador_planta():
    global _planta_hilo
    if _planta_hilo and _planta_hilo.is_alive():
        return
    _planta_hilo = threading.Thread(target=_planta_bucle, name="procesador-planta", daemon=True)
    _planta_hilo.start()


# ── Administración (Sistema → Tablets de planta) ──────────────────────────────

def _planta_enlace(token):
    host = request.host
    if host.split(":")[0] in ("localhost", "127.0.0.1"):
        puerto = host.split(":")[1] if ":" in host else "80"
        host = f"{get_local_ip()}:{puerto}"
    return f"http://{host}/tablet?t={token}"


@app.route("/api/planta/tablets")
@login_required(roles=["admin"])
def planta_tablets():
    filas = query("""SELECT t.*, m.codigo maquina_codigo, m.nombre maquina_nombre,
            (SELECT COUNT(*) FROM planta_bandeja b WHERE b.tablet_id=t.id AND b.estado IN ('Pendiente','Procesando')) pendientes,
            (SELECT COUNT(*) FROM planta_bandeja b WHERE b.tablet_id=t.id AND b.estado='Error') errores,
            (SELECT MAX(recibido) FROM planta_bandeja b WHERE b.tablet_id=t.id) ultimo_registro,
            (SELECT MAX(recibido) FROM planta_huellas h WHERE h.tablet_id=t.id) ultima_huella
        FROM planta_tablets t LEFT JOIN maquinas m ON m.id=t.maquina_id ORDER BY t.activa DESC, t.nombre""")
    res = []
    for r in filas:
        x = dict(r)
        x["ultimo_contacto"] = _planta_visto.get(r["id"])
        x["lector_visto"] = (_planta_lectores.get(r["lector_sn"]) or {}).get("visto") if r["lector_sn"] else None
        x["enlace"] = _planta_enlace(r["token"])
        res.append(x)
    return jsonify(res)


@app.route("/api/planta/tablets", methods=["POST"])
@login_required(roles=["admin"])
def planta_tablet_crear():
    d = request.get_json(silent=True) or {}
    nombre = (d.get("nombre") or "").strip()
    maq = query("SELECT id, codigo FROM maquinas WHERE id=?", (d.get("maquina_id"),), one=True)
    if not maq:
        return jsonify({"error": "Elegí la máquina"}), 400
    nombre = nombre or f"Tablet {maq['codigo']}"
    tid = execute("""INSERT INTO planta_tablets (nombre, maquina_id, token, creado_por)
        VALUES (?,?,?,?)""", (nombre, maq["id"], secrets.token_urlsafe(18), session["user_id"]))
    return jsonify({"ok": True, "id": tid}), 201


@app.route("/api/planta/tablets/<int:tid>", methods=["PUT"])
@login_required(roles=["admin"])
def planta_tablet_editar(tid):
    d = request.get_json(silent=True) or {}
    t = query("SELECT * FROM planta_tablets WHERE id=?", (tid,), one=True)
    if not t:
        return jsonify({"error": "Tablet no encontrada"}), 404
    maq = query("SELECT id FROM maquinas WHERE id=?", (d.get("maquina_id", t["maquina_id"]),), one=True)
    if not maq:
        return jsonify({"error": "Elegí la máquina"}), 400
    nombre = (d.get("nombre") if d.get("nombre") is not None else t["nombre"]).strip() or t["nombre"]
    activa = 1 if d.get("activa", t["activa"]) else 0
    execute("UPDATE planta_tablets SET nombre=?, maquina_id=?, activa=? WHERE id=?", (nombre, maq["id"], activa, tid))
    return jsonify({"ok": True})


@app.route("/api/planta/tablets/<int:tid>/token", methods=["POST"])
@login_required(roles=["admin"])
def planta_tablet_token(tid):
    """Enlace nuevo (tablet perdida o robada): el anterior deja de servir."""
    if not query("SELECT 1 FROM planta_tablets WHERE id=?", (tid,), one=True):
        return jsonify({"error": "Tablet no encontrada"}), 404
    execute("UPDATE planta_tablets SET token=? WHERE id=?", (secrets.token_urlsafe(18), tid))
    return jsonify({"ok": True})


@app.route("/api/planta/bandeja")
@login_required(roles=["admin"])
def planta_bandeja_lista():
    cond, params = [], []
    if request.args.get("estado") == "Esperando lote":
        cond.append("b.estado='Pendiente' AND b.espera='lote'")
    elif request.args.get("estado"):
        cond.append("b.estado=?"); params.append(request.args["estado"])
    if request.args.get("tablet_id"):
        cond.append("b.tablet_id=?"); params.append(request.args["tablet_id"])
    filas = query(f"""SELECT b.*, n.numero novedad_numero, t.nombre tablet_nombre, m.codigo maquina_codigo,
            u.nombre resuelto_por_nombre
        FROM planta_bandeja b JOIN planta_tablets t ON t.id=b.tablet_id
        LEFT JOIN maquinas m ON m.id=t.maquina_id
        LEFT JOIN novedades_produccion n ON n.id=b.novedad_id
        LEFT JOIN usuarios u ON u.id=b.resuelto_por
        {'WHERE ' + ' AND '.join(cond) if cond else ''}
        ORDER BY b.id DESC LIMIT 500""", params)
    emp = {r["id"]: f"{r['apellido'] or ''} {r['nombre'] or ''}".strip()
           for r in query("SELECT id, nombre, apellido FROM empleados")}
    ops = {}
    res = []
    for r in filas:
        x = _planta_registro_dict(r)
        x.update({"tablet_nombre": r["tablet_nombre"], "maquina_codigo": r["maquina_codigo"],
                  "intentos": r["intentos"], "resuelto_por_nombre": r["resuelto_por_nombre"]})
        oid = x["datos"].get("orden_operacion_id")
        if oid not in ops:
            o = query("""SELECT oo.orden paso, oo.nombre, o.numero ot FROM orden_operaciones oo
                JOIN ordenes o ON o.id=oo.orden_id WHERE oo.id=?""", (oid,), one=True)
            ops[oid] = f"{o['ot']} · {o['paso']} {o['nombre']}" if o else "(operación borrada)"
        x["operacion"] = ops[oid]
        x["empleado"] = emp.get(x["datos"].get("empleado_id"), "(sin operario)")
        res.append(x)
    totales = {r["estado"]: r["n"] for r in query("SELECT estado, COUNT(*) n FROM planta_bandeja GROUP BY estado")}
    totales["Esperando lote"] = query("SELECT COUNT(*) n FROM planta_bandeja WHERE estado='Pendiente' AND espera='lote'", one=True)["n"]
    return jsonify({"registros": res, "totales": totales})


@app.route("/api/planta/operaciones")
@login_required(roles=["admin"])
def planta_operaciones():
    return jsonify(_planta_operaciones_abiertas())


@app.route("/api/planta/bandeja/<int:rid>/reprocesar", methods=["POST"])
@login_required(roles=["admin"])
def planta_bandeja_reprocesar(rid):
    """Vuelve a Pendiente un registro con Error, opcionalmente corrigiendo
    cantidades, tiempo, operación u operario."""
    r = query("SELECT * FROM planta_bandeja WHERE id=?", (rid,), one=True)
    if not r:
        return jsonify({"error": "Registro no encontrado"}), 404
    if r["estado"] != "Error" and not (r["estado"] == "Pendiente" and (r["espera"] or r["intentos"])):
        return jsonify({"error": f"Solo se reprocesan registros con error, reintentando o esperando lote (este está {r['estado']})"}), 400
    datos = _json.loads(r["datos"] or "{}")
    cambios = (request.get_json(silent=True) or {}).get("datos") or {}
    for k in ("cantidad_ok", "cantidad_nok", "tiempo_min", "tiempo_perdido_min"):
        if k in cambios:
            try:
                datos[k] = max(0.0, float(cambios[k] or 0))
            except (TypeError, ValueError):
                return jsonify({"error": f"Valor inválido en {k}"}), 400
    for k in ("orden_operacion_id", "empleado_id"):
        if cambios.get(k):
            datos[k] = int(cambios[k])
    execute("""UPDATE planta_bandeja SET estado='Pendiente', datos=?, error=NULL, intentos=0, espera=NULL,
        espera_ref=NULL, reintentar_desde=NULL, resuelto_por=? WHERE id=?""",
        (_json.dumps(datos, ensure_ascii=False), session["user_id"], rid))
    _planta_aviso.set()
    return jsonify({"ok": True})


@app.route("/api/planta/bandeja/<int:rid>/descartar", methods=["POST"])
@login_required(roles=["admin"])
def planta_bandeja_descartar(rid):
    r = query("SELECT estado, espera, intentos FROM planta_bandeja WHERE id=?", (rid,), one=True)
    if not r:
        return jsonify({"error": "Registro no encontrado"}), 404
    if r["estado"] != "Error" and not (r["estado"] == "Pendiente" and (r["espera"] or r["intentos"])):
        return jsonify({"error": "Solo se descartan registros con error"}), 400
    execute("UPDATE planta_bandeja SET estado='Descartado', resuelto_por=?, procesado=datetime('now','localtime') WHERE id=?",
            (session["user_id"], rid))
    return jsonify({"ok": True})


# ══ Tablets de planta: entrada con huella ═════════════════════════════════════
# El operario no elige su nombre: apoya el dedo en el lector de huella de la
# máquina. El lector reconoce la huella (las plantillas viven en el lector, no
# en MetalERP) y manda al servidor el legajo; el servidor lo anota en
# planta_huellas para la tablet que tiene asignado ese lector, y la tablet, que
# pregunta cada segundo y medio, entra sola con ese operario.
#
#   Lector ZKTeco con "push" (ADMS): se configura en el lector la IP del
#   servidor y el puerto 5000; habla con /iclock/* (protocolo del fabricante).
#   Cualquier otro lector o puente: POST /api/planta/huella {sn, legajo, hora}.
#
# El lector se asigna a la tablet por su número de serie (Sistema → Tablets de
# planta). Una marca vieja (el lector, al conectarse, sube todo su historial)
# no inicia sesión: solo cuentan las de los últimos minutos.

PLANTA_HUELLA_VENTANA_MIN = 10        # marcas más viejas que esto (hora del lector) se ignoran
PLANTA_HUELLA_VIGENCIA_SEG = 60       # la tablet toma una marca solo si llegó hace menos de esto
_planta_lectores = {}                 # sn -> {"visto", "ip"} (en memoria; para la pantalla de admin)


def _planta_norm_legajo(v):
    v = re.sub(r"\s+", "", str(v or ""))
    return v.lstrip("0") or ("0" if v else "")


def _planta_empleado_por_legajo(legajo):
    buscado = _planta_norm_legajo(legajo)
    if not buscado:
        return None
    for e in query("SELECT id, legajo, nombre, apellido FROM empleados WHERE activo=1 AND legajo IS NOT NULL"):
        if _planta_norm_legajo(e["legajo"]) == buscado:
            return e
    return None


def _planta_lector_visto(sn):
    _planta_lectores[sn] = {"visto": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "ip": request.remote_addr}


def _planta_anotar_huella(sn, legajo, hora=None, origen="api", tablet=None):
    """Anota una marca. Devuelve (ok, motivo). Con tablet (simulada) no mira el lector."""
    ahora = datetime.now()
    if hora:
        try:
            h = datetime.strptime(str(hora).strip()[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return False, "hora inválida"
        if abs((ahora - h).total_seconds()) > PLANTA_HUELLA_VENTANA_MIN * 60:
            return False, "marca vieja"
        hora = h.strftime("%Y-%m-%d %H:%M:%S")
    else:
        hora = ahora.strftime("%Y-%m-%d %H:%M:%S")
    if tablet is None:
        tablet = query("SELECT id FROM planta_tablets WHERE lector_sn=? AND activa=1", (sn,), one=True)
        if not tablet:
            return False, "lector sin tablet asignada"
    emp = _planta_empleado_por_legajo(legajo)
    execute("""INSERT INTO planta_huellas (tablet_id, lector_sn, legajo, empleado_id, hora, origen)
        VALUES (?,?,?,?,?,?)""", (tablet["id"], sn, str(legajo or "").strip(), emp["id"] if emp else None, hora, origen))
    return True, "ok"


# ── Lector ZKTeco por push (ADMS / iclock) ───────────────────────────────────

def _zk_texto(t):
    return t, 200, {"Content-Type": "text/plain; charset=utf-8"}


@app.route("/iclock/cdata", methods=["GET", "POST"])
def zk_cdata():
    sn = (request.args.get("SN") or "").strip()
    if not sn:
        return _zk_texto("ERROR")
    _planta_lector_visto(sn)
    if request.method == "GET":
        # Saludo inicial: Realtime=1 hace que mande cada marca en el momento.
        return _zk_texto("\n".join([
            f"GET OPTION FROM: {sn}", "ATTLOGStamp=None", "OPERLOGStamp=9999", "ATTPHOTOStamp=None",
            "ErrorDelay=30", "Delay=2", "TransTimes=00:00;14:05", "TransInterval=1",
            "TransFlag=TransData AttLog", "TimeZone=-3", "Realtime=1", "Encrypt=None"]) + "\n")
    cuerpo = request.get_data(as_text=True) or ""
    filas = [f for f in cuerpo.replace("\r", "").split("\n") if f.strip()]
    if (request.args.get("table") or "").upper() == "ATTLOG":
        # PIN \t AAAA-MM-DD HH:MM:SS \t estado \t verificación ...
        for f in filas:
            partes = f.split("\t")
            if len(partes) >= 2:
                _planta_anotar_huella(sn, partes[0], partes[1], "zkteco")
    return _zk_texto(f"OK: {len(filas)}")


@app.route("/iclock/getrequest", methods=["GET"])
def zk_getrequest():
    sn = (request.args.get("SN") or "").strip()
    if sn:
        _planta_lector_visto(sn)
    return _zk_texto("OK")


@app.route("/iclock/devicecmd", methods=["POST"])
def zk_devicecmd():
    return _zk_texto("OK")


@app.route("/api/planta/huella", methods=["POST"])
def planta_huella_generica():
    """Para lectores de otra marca o un programa puente: {sn, legajo, hora?}.
    Solo se acepta si el número de serie está asignado a una tablet activa."""
    d = request.get_json(silent=True) or {}
    sn = str(d.get("sn") or "").strip()
    legajo = str(d.get("legajo") or "").strip()
    if not sn or not legajo:
        return jsonify({"error": "Faltan sn y legajo"}), 400
    _planta_lector_visto(sn)
    ok, motivo = _planta_anotar_huella(sn, legajo, d.get("hora"), "api")
    if not ok:
        return jsonify({"error": motivo}), 409
    return jsonify({"ok": True})


# ── Tablet ───────────────────────────────────────────────────────────────────

def _planta_huella_dict(r):
    nombre = " ".join(x for x in [r["apellido"], r["nombre"]] if x) if r["empleado_id"] else None
    return {"id": r["id"], "empleado_id": r["empleado_id"], "legajo": r["legajo"], "nombre": nombre,
            "hora": r["hora"], "recibido": r["recibido"]}


@app.route("/api/tablet/huella")
@tablet_requerida
def tablet_huella():
    """La última marca de esta tablet posterior a `desde`, si llegó hace menos de
    un minuto. `ultima_id` le sirve a la tablet para no tomar una marca vieja
    cuando recién arranca."""
    t = g.tablet
    desde = request.args.get("desde", type=int) or 0
    limite = (datetime.now() - timedelta(seconds=PLANTA_HUELLA_VIGENCIA_SEG)).strftime("%Y-%m-%d %H:%M:%S")
    r = query("""SELECT h.*, e.nombre, e.apellido FROM planta_huellas h
        LEFT JOIN empleados e ON e.id=h.empleado_id
        WHERE h.tablet_id=? AND h.id>? AND h.recibido>=? ORDER BY h.id DESC LIMIT 1""", (t["id"], desde, limite), one=True)
    ult = query("SELECT MAX(id) m FROM planta_huellas WHERE tablet_id=?", (t["id"],), one=True)
    return jsonify({"huella": _planta_huella_dict(r) if r else None, "ultima_id": (ult["m"] if ult else None) or 0,
                    "lector": bool(t["lector_sn"]),
                    "lector_visto": (_planta_lectores.get(t["lector_sn"]) or {}).get("visto") if t["lector_sn"] else None})


# ── Administración ───────────────────────────────────────────────────────────

@app.route("/api/planta/lectores")
@login_required(roles=["admin"])
def planta_lectores():
    """Lectores que se comunicaron desde que arrancó el servidor (asignados o no)."""
    asignados = {r["lector_sn"]: r["nombre"] for r in query(
        "SELECT lector_sn, nombre FROM planta_tablets WHERE lector_sn IS NOT NULL")}
    return jsonify([{"sn": sn, "visto": v["visto"], "ip": v["ip"], "tablet": asignados.get(sn)}
                    for sn, v in sorted(_planta_lectores.items(), key=lambda x: x[1]["visto"], reverse=True)])


@app.route("/api/planta/tablets/<int:tid>/lector", methods=["PUT"])
@login_required(roles=["admin"])
def planta_tablet_lector(tid):
    d = request.get_json(silent=True) or {}
    if not query("SELECT 1 FROM planta_tablets WHERE id=?", (tid,), one=True):
        return jsonify({"error": "Tablet no encontrada"}), 404
    sn = str(d.get("lector_sn") or "").strip() or None
    if sn:
        otra = query("SELECT nombre FROM planta_tablets WHERE lector_sn=? AND id!=?", (sn, tid), one=True)
        if otra:
            return jsonify({"error": f"Ese lector ya está asignado a {otra['nombre']}"}), 409
    execute("UPDATE planta_tablets SET lector_sn=? WHERE id=?", (sn, tid))
    return jsonify({"ok": True})


@app.route("/api/planta/tablets/<int:tid>/huella", methods=["POST"])
@login_required(roles=["admin"])
def planta_tablet_huella_simulada(tid):
    """Probar sin lector: hace de cuenta que ese operario apoyó el dedo."""
    d = request.get_json(silent=True) or {}
    t = query("SELECT id, lector_sn FROM planta_tablets WHERE id=?", (tid,), one=True)
    e = query("SELECT legajo FROM empleados WHERE id=? AND activo=1", (d.get("empleado_id"),), one=True)
    if not t or not e:
        return jsonify({"error": "Elegí la tablet y el operario"}), 400
    if not str(e["legajo"] or "").strip():
        return jsonify({"error": "Ese operario no tiene legajo cargado: sin legajo el lector no lo puede identificar"}), 400
    _planta_anotar_huella(t["lector_sn"], e["legajo"], None, "simulada", tablet=t)
    return jsonify({"ok": True})



# ── Tablets de planta: ingreso de administrador sin huella ────────────────────
# Si el lector falla o el operario no puede marcar, un administrador de
# MetalERP pone su usuario y contraseña en la tablet y elige al operario de la
# lista. La novedad queda con "sin huella, autorizó <administrador>".
_planta_admin_fallos = {}             # tablet_id -> [cantidad, hasta]


def _planta_admin_nombre(uid):
    u = query("SELECT nombre, username FROM usuarios WHERE id=?", (uid,), one=True)
    return (u["nombre"] or u["username"]) if u else f"usuario #{uid}"


@app.route("/api/tablet/admin", methods=["POST"])
@tablet_requerida
def tablet_admin():
    t = g.tablet
    n, hasta = _planta_admin_fallos.get(t["id"], [0, None])
    if hasta and datetime.now() < hasta:
        return jsonify({"error": "Demasiados intentos. Esperá un minuto."}), 429
    d = request.get_json(silent=True) or {}
    u = query("SELECT * FROM usuarios WHERE username=? AND activo=1", (str(d.get("username") or "").strip(),), one=True)
    if not u or u["password"] != hash_pw(d.get("password") or ""):
        n += 1
        _planta_admin_fallos[t["id"]] = [0, datetime.now() + timedelta(minutes=1)] if n >= 5 else [n, None]
        return jsonify({"error": "Usuario o contraseña incorrectos"}), 401
    if _rol_base(u["rol"]) != "admin":
        return jsonify({"error": "Solo un administrador puede entrar sin huella"}), 403
    _planta_admin_fallos.pop(t["id"], None)
    return jsonify({"ok": True, "admin": {"id": u["id"], "nombre": u["nombre"] or u["username"]}})

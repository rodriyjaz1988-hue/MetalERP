# -*- coding: utf-8 -*-
"""
Unificación de las tablas `productos` y `materiales` en UNA sola tabla de
artículos (`materiales`).

Por qué
-------
Hasta ahora cada producto terminado existía dos veces: la ficha de proceso en
`productos` y un "gemelo" de stock en `materiales` (mismo código, vinculado por
materiales.producto_id). Eso generaba dos listas de códigos que había que
mantener sincronizadas a mano (código, nombre, cliente, código de barras...).

Después de esta migración:
  * `materiales` es la ÚNICA tabla de artículos. La columna `categoria` es el
    tipo explícito: Material / Insumo / Herramienta / Producto terminado /
    Semielaborado (no se deduce del cliente).
  * Cada producto terminado es UNA fila de `materiales`, con su stock, sus
    lotes y su proceso. Conserva el MISMO id que tenía en `productos` (de eso
    dependen las carpetas de documentos, las versiones de proceso y las OT).
  * Las columnas propias del producto (tiempo_total_hs, costo_mat, costo_mo,
    precio_venta, peso_kg, capacidad_cajon, descripcion_larga, creado) pasan a
    `materiales`.
  * Para un producto terminado, materiales.producto_id = su propio id (lo
    mantiene un trigger). Para un semielaborado, producto_id = el producto al
    que pertenece. Para materia prima / insumo / herramienta queda NULL.
  * `productos` pasa a ser una VISTA de solo lectura sobre `materiales` con los
    nombres de columna de antes (nombre, categoria_id, ...). Sirve para que las
    consultas de lectura existentes sigan funcionando. Cualquier escritura debe
    ir a `materiales`.
  * Todas las tablas que apuntaban a productos(id) pasan a apuntar a
    materiales(id). Los materiales que cambian de id (gemelos que se funden con
    su producto, o materiales cuyo id chocaba con el de un producto) se
    renumeran en TODAS las tablas que los referencian.

Seguridad
---------
  * Antes de tocar nada se hace un backup completo de la base (API de backup
    de SQLite, consistente aunque haya WAL).
  * Toda la migración corre en UNA transacción. Antes de confirmar se verifica:
    conteo de filas de cada tabla, stock total, cada referencia remapeada fila
    por fila, novedades (cantidad y tiempos), foreign_key_check e
    integrity_check. Si algo no cierra se hace ROLLBACK y la base queda
    exactamente como estaba.
  * Se escribe un informe (database/unificacion_informe_<fecha>.txt).

Uso manual
----------
  python migracion_unificacion.py --simular [ruta.db]
        Corre la migración completa sobre una COPIA temporal y muestra el
        informe. No modifica la base original.
  python migracion_unificacion.py [ruta.db]
        Hace backup y migra.

El server la llama sola al arrancar (init_db) si detecta que la base todavía
tiene la tabla `productos`.
"""
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime

MARCA_CONFIG = "unificacion_articulos_v1"

PT = "Producto terminado"

# Sufijo para renombrar un artículo que no es producto cuyo código coincide
# con el código de un producto (el producto conserva el suyo).
_SUFIJO_POR_CATEGORIA = {
    "Material": "-MP",
    "Insumo": "-INS",
    "Herramienta": "-HER",
    "Semielaborado": "-SE",
}

DDL_MATERIALES = """CREATE TABLE "{nombre}" (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo TEXT UNIQUE NOT NULL,
    descripcion TEXT NOT NULL,
    categoria TEXT DEFAULT 'Material',
    categoria_producto_id INTEGER REFERENCES categorias_producto(id),
    unidad TEXT DEFAULT 'kg',
    stock REAL DEFAULT 0,
    stock_min REAL DEFAULT 0,
    stock_max REAL DEFAULT 0,
    precio_unit REAL DEFAULT 0,
    proveedor_id INTEGER REFERENCES proveedores(id),
    obs TEXT,
    actualizado TEXT DEFAULT (datetime('now','localtime')),
    activo INTEGER DEFAULT 1,
    producto_id INTEGER REFERENCES materiales(id),
    pse_firma TEXT,
    operacion_id INTEGER REFERENCES proceso_operaciones(id),
    tipo TEXT CHECK(tipo IN ('MP','PSE','PSET')),
    cliente_id INTEGER REFERENCES clientes(id),
    codigo_barras TEXT,
    descripcion_larga TEXT,
    tiempo_total_hs REAL DEFAULT 0,
    costo_mat REAL DEFAULT 0,
    costo_mo REAL DEFAULT 0,
    precio_venta REAL DEFAULT 0,
    peso_kg REAL DEFAULT 0,
    capacidad_cajon INTEGER,
    creado TEXT DEFAULT (datetime('now','localtime')))"""

COLUMNAS_MATERIALES = [
    "id", "codigo", "descripcion", "categoria", "categoria_producto_id", "unidad",
    "stock", "stock_min", "stock_max", "precio_unit", "proveedor_id", "obs",
    "actualizado", "activo", "producto_id", "pse_firma", "operacion_id", "tipo",
    "cliente_id", "codigo_barras", "descripcion_larga", "tiempo_total_hs",
    "costo_mat", "costo_mo", "precio_venta", "peso_kg", "capacidad_cajon", "creado",
]

DDL_VISTA_PRODUCTOS = """CREATE VIEW productos AS
SELECT id,
       codigo,
       descripcion            AS nombre,
       descripcion_larga      AS descripcion,
       categoria_producto_id  AS categoria_id,
       unidad,
       tiempo_total_hs,
       costo_mat,
       costo_mo,
       precio_venta,
       activo,
       obs,
       creado,
       peso_kg,
       cliente_id,
       capacidad_cajon,
       CASE WHEN categoria='Producto terminado' THEN 'PT' END AS tipo,
       codigo_barras,
       categoria              AS tipo_articulo
FROM materiales"""

# Un producto terminado se referencia a sí mismo en producto_id: así todo el
# código que busca "el material de stock del producto X" (producto_id=X AND
# categoria='Producto terminado') encuentra la misma fila, sin importar por
# qué camino se dio de alta el artículo (Procesos, Inventario, carga masiva).
DDL_TRIGGERS = [
    """CREATE TRIGGER IF NOT EXISTS trg_materiales_pt_alta
    AFTER INSERT ON materiales
    WHEN NEW.categoria='Producto terminado' AND (NEW.producto_id IS NULL OR NEW.producto_id<>NEW.id)
    BEGIN
        UPDATE materiales SET producto_id=NEW.id WHERE id=NEW.id;
    END""",
    """CREATE TRIGGER IF NOT EXISTS trg_materiales_pt_cambio
    AFTER UPDATE OF categoria, producto_id ON materiales
    WHEN NEW.categoria='Producto terminado' AND (NEW.producto_id IS NULL OR NEW.producto_id<>NEW.id)
    BEGIN
        UPDATE materiales SET producto_id=NEW.id WHERE id=NEW.id;
    END""",
    """CREATE TRIGGER IF NOT EXISTS trg_materiales_pt_baja
    AFTER UPDATE OF categoria ON materiales
    WHEN OLD.categoria='Producto terminado' AND NEW.categoria<>'Producto terminado'
         AND NEW.producto_id=NEW.id
    BEGIN
        UPDATE materiales SET producto_id=NULL WHERE id=NEW.id;
    END""",
]

INDICES_EXTRA = [
    "CREATE INDEX IF NOT EXISTS idx_materiales_categoria ON materiales(categoria)",
]


# ─────────────────────────────────────────────────────────────────────────────
# Utilidades
# ─────────────────────────────────────────────────────────────────────────────
def _tipo_objeto(db, nombre):
    r = db.execute("SELECT type FROM sqlite_master WHERE name=?", (nombre,)).fetchone()
    return r[0] if r else None


def necesita_migrar(db_path):
    """True si la base todavía tiene la tabla `productos` (esquema viejo)."""
    if not os.path.exists(db_path):
        return False
    db = sqlite3.connect(db_path)
    try:
        return _tipo_objeto(db, "productos") == "table"
    finally:
        db.close()


def _cols(db, tabla):
    return [r[1] for r in db.execute(f'PRAGMA table_info("{tabla}")').fetchall()]


def _tablas(db):
    return [r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]


def _fks_hacia(db, destino):
    """[(tabla, columna)] de todas las FK que apuntan a `destino`."""
    out = []
    for t in _tablas(db):
        for fk in db.execute(f'PRAGMA foreign_key_list("{t}")').fetchall():
            if fk[2] == destino:
                out.append((t, fk[3]))
    return out


def _txt(v):
    return (v or "").strip() if isinstance(v, str) else ("" if v is None else str(v))


def _norm_codigo(c):
    return re.sub(r"\s+", "", (c or "")).lower()


def _primero(*vals):
    for v in vals:
        if v not in (None, ""):
            return v
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Análisis (no modifica nada)
# ─────────────────────────────────────────────────────────────────────────────
def analizar(db):
    db.row_factory = sqlite3.Row
    prods = {r["id"]: dict(r) for r in db.execute("SELECT * FROM productos ORDER BY id")}
    mats = {r["id"]: dict(r) for r in db.execute("SELECT * FROM materiales ORDER BY id")}

    avisos = []      # cosas para revisar, no bloquean
    bloqueos = []    # impiden migrar sin una decisión manual
    acciones = []    # decisiones automáticas que se tomaron

    # 1) Gemelos de stock: material 'Producto terminado' vinculado por FK.
    gemelo_de_prod = {}   # prod_id -> mat_id
    prod_de_gemelo = {}   # mat_id  -> prod_id
    for m in mats.values():
        pid = m.get("producto_id")
        if m.get("categoria") == PT and pid in prods and m.get("operacion_id") is None:
            if pid in gemelo_de_prod:
                bloqueos.append(
                    f"El producto id={pid} ({prods[pid]['codigo']}) tiene más de un material "
                    f"'Producto terminado' vinculado (ids {gemelo_de_prod[pid]} y {m['id']}). "
                    f"Hay que decidir a mano cuál conservar.")
                continue
            gemelo_de_prod[pid] = m["id"]
            prod_de_gemelo[m["id"]] = pid

    # 1b) Respaldo: material PT sin producto_id cuyo código coincide con un
    #     producto que no tiene gemelo por FK.
    prod_por_codigo = {p["codigo"]: pid for pid, p in prods.items()}
    for m in mats.values():
        if m["id"] in prod_de_gemelo:
            continue
        if m.get("categoria") == PT and not m.get("producto_id"):
            pid = prod_por_codigo.get(m["codigo"])
            if pid and pid not in gemelo_de_prod:
                gemelo_de_prod[pid] = m["id"]
                prod_de_gemelo[m["id"]] = pid
                acciones.append(
                    f"Material id={m['id']} '{m['codigo']}' (PT sin vínculo) se une al producto "
                    f"id={pid} por coincidencia exacta de código.")

    # 2) Diferencias entre producto y su gemelo (se conserva lo del producto).
    for pid, mid in gemelo_de_prod.items():
        p, m = prods[pid], mats[mid]
        if _txt(p.get("codigo")) != _txt(m.get("codigo")):
            acciones.append(
                f"Producto id={pid}: el gemelo de stock tenía el código '{m['codigo']}'; "
                f"queda el código del producto '{p['codigo']}'.")
        if _txt(p.get("nombre")) != _txt(m.get("descripcion")):
            avisos.append(
                f"Producto '{p['codigo']}': nombre '{p.get('nombre')}' ≠ descripción del gemelo "
                f"'{m.get('descripcion')}'. Queda el nombre del producto.")
        if _txt(p.get("unidad")).lower() != _txt(m.get("unidad")).lower():
            avisos.append(
                f"Producto '{p['codigo']}': unidad '{p.get('unidad')}' ≠ unidad del stock "
                f"'{m.get('unidad')}'. Queda la del producto; revisar que el stock esté en esa unidad.")
        if p.get("cliente_id") and m.get("cliente_id") and p["cliente_id"] != m["cliente_id"]:
            avisos.append(
                f"Producto '{p['codigo']}': cliente {p['cliente_id']} ≠ cliente del gemelo "
                f"{m['cliente_id']}. Queda el del producto.")

    # 3) Materiales PT "sueltos" (sin producto): pasan a ser artículos PT propios.
    for m in mats.values():
        if m["id"] in prod_de_gemelo:
            continue
        if m.get("categoria") == PT:
            if m.get("producto_id") and m["producto_id"] not in prods:
                avisos.append(
                    f"Material PT id={m['id']} '{m['codigo']}' apuntaba al producto id="
                    f"{m['producto_id']}, que no existe. Queda como producto terminado propio.")
            else:
                acciones.append(
                    f"Material PT id={m['id']} '{m['codigo']}' no tenía ficha de producto: "
                    f"queda como producto terminado (sin proceso).")
        elif m.get("producto_id") and m["producto_id"] not in prods:
            avisos.append(
                f"Material id={m['id']} '{m['codigo']}' ({m.get('categoria')}) apuntaba al producto "
                f"id={m['producto_id']}, que no existe: se le quita el vínculo.")

    # 4) Asignación de ids. Productos conservan su id; gemelos toman el id de
    #    su producto; el resto de los materiales conserva el suyo salvo que
    #    choque con un id de producto.
    usados = set(prods.keys())
    mapa = {}
    for mid, pid in prod_de_gemelo.items():
        mapa[mid] = pid
    resto = [mid for mid in sorted(mats) if mid not in prod_de_gemelo]
    for mid in resto:
        if mid not in usados:
            mapa[mid] = mid
            usados.add(mid)
    seq = dict(db.execute("SELECT name, seq FROM sqlite_sequence").fetchall()) if _tipo_objeto(db, "sqlite_sequence") else {}
    siguiente = max([0, *usados, *mats.keys(), seq.get("productos", 0) or 0, seq.get("materiales", 0) or 0]) + 1
    for mid in resto:
        if mid not in mapa:
            mapa[mid] = siguiente
            acciones.append(
                f"Material id={mid} '{mats[mid]['codigo']}' cambia a id={siguiente} "
                f"(su id coincidía con el de un producto).")
            usados.add(siguiente)
            siguiente += 1

    # 5) Códigos finales: el producto conserva el suyo. Un material que no es
    #    gemelo y comparte código con un producto se renombra.
    codigos_finales = {}   # nuevo_id -> codigo
    for pid, p in prods.items():
        codigos_finales[pid] = p["codigo"]
    ocupados = set(codigos_finales.values())
    renombres = {}         # mat_id viejo -> (codigo viejo, codigo nuevo)
    for mid in resto:
        m = mats[mid]
        cod = m["codigo"]
        if cod in ocupados:
            suf = _SUFIJO_POR_CATEGORIA.get(m.get("categoria") or "", "-ART")
            n, cand = 1, f"{cod}{suf}"
            while cand in ocupados or any(cand == mm["codigo"] for mm in mats.values()):
                n += 1
                cand = f"{cod}{suf}{n}"
            renombres[mid] = (cod, cand)
            cod = cand
            acciones.append(
                f"CHOQUE DE CÓDIGO: el material id={mid} '{m['codigo']}' ({m.get('categoria')}, "
                f"{m.get('descripcion')}) tenía el mismo código que el producto "
                f"'{m['codigo']}'. El producto conserva el código; el material pasa a '{cand}'.")
        codigos_finales[mapa[mid]] = cod
        ocupados.add(cod)

    # 6) Avisos informativos.
    sin_cliente = [p for p in prods.values() if not p.get("cliente_id")]
    for p in sin_cliente:
        avisos.append(f"Producto '{p['codigo']}' ({p.get('nombre')}) no tiene cliente asignado. "
                      f"Queda como 'Producto terminado' (el tipo es explícito).")
    por_norm = {}
    for nid, cod in codigos_finales.items():
        por_norm.setdefault(_norm_codigo(cod), []).append(cod)
    for k, lst in por_norm.items():
        if len(lst) > 1:
            avisos.append("Códigos casi iguales (solo difieren en mayúsculas/espacios), "
                          "posibles duplicados: " + " | ".join(repr(c) for c in sorted(lst)))
    if _tipo_objeto(db, "lotes") == "table":
        for m in mats.values():
            if m.get("categoria") in ("Material", PT, "Semielaborado"):
                s_l = db.execute("SELECT COALESCE(SUM(cantidad_activa),0) FROM lotes WHERE material_id=?",
                                 (m["id"],)).fetchone()[0]
                if abs(float(m.get("stock") or 0) - float(s_l or 0)) > 0.001:
                    avisos.append(
                        f"Stock sin lote aprobado (dato previo, no se modifica): '{m['codigo']}' "
                        f"stock={m.get('stock')} vs aprobado en lotes={s_l}.")

    return {
        "prods": prods, "mats": mats,
        "gemelo_de_prod": gemelo_de_prod, "prod_de_gemelo": prod_de_gemelo,
        "mapa": mapa, "codigos_finales": codigos_finales, "renombres": renombres,
        "avisos": avisos, "acciones": acciones, "bloqueos": bloqueos,
        "seq_final": max([siguiente - 1, seq.get("productos", 0) or 0, seq.get("materiales", 0) or 0]),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Construcción de filas unificadas
# ─────────────────────────────────────────────────────────────────────────────
def _obs_combinadas(*vals):
    partes = []
    for v in vals:
        v = _txt(v)
        if v and v not in partes:
            partes.append(v)
    if partes:
        return "\n".join(partes)
    return vals[0] if vals else None   # conserva '' tal cual estaba


def _filas_unificadas(plan):
    prods, mats = plan["prods"], plan["mats"]
    mapa, codigos = plan["mapa"], plan["codigos_finales"]
    filas = []
    for pid, p in prods.items():
        m = mats.get(plan["gemelo_de_prod"].get(pid)) or {}
        filas.append({
            "id": pid,
            "codigo": codigos[pid],
            "descripcion": _primero(p.get("nombre"), m.get("descripcion"), p.get("codigo")),
            "categoria": PT,
            "categoria_producto_id": _primero(p.get("categoria_id"), m.get("categoria_producto_id")),
            "unidad": _primero(p.get("unidad"), m.get("unidad"), "unid"),
            "stock": m.get("stock") or 0,
            "stock_min": m.get("stock_min") or 0,
            "stock_max": m.get("stock_max") or 0,
            "precio_unit": m.get("precio_unit") or 0,
            "proveedor_id": m.get("proveedor_id"),
            "obs": _obs_combinadas(p.get("obs"), m.get("obs")),
            "actualizado": _primero(m.get("actualizado"), p.get("creado")),
            "activo": 1 if p.get("activo") in (None, 1, "1") else 0,
            "producto_id": pid,
            "pse_firma": None,
            "operacion_id": None,
            "tipo": m.get("tipo"),
            "cliente_id": _primero(p.get("cliente_id"), m.get("cliente_id")),
            "codigo_barras": _primero(p.get("codigo_barras"), m.get("codigo_barras")),
            "descripcion_larga": p.get("descripcion"),
            "tiempo_total_hs": p.get("tiempo_total_hs") or 0,
            "costo_mat": p.get("costo_mat") or 0,
            "costo_mo": p.get("costo_mo") or 0,
            "precio_venta": p.get("precio_venta") or 0,
            "peso_kg": p.get("peso_kg") or 0,
            "capacidad_cajon": p.get("capacidad_cajon"),
            "creado": _primero(p.get("creado"), m.get("actualizado")),
        })
    for mid, m in mats.items():
        if mid in plan["prod_de_gemelo"]:
            continue
        nid = mapa[mid]
        cat = m.get("categoria") or "Material"
        prod_ref = m.get("producto_id") if m.get("producto_id") in prods else None
        if cat == PT:
            prod_ref = nid   # PT propio: se referencia a sí mismo
        filas.append({
            "id": nid,
            "codigo": codigos[nid],
            "descripcion": _primero(m.get("descripcion"), m.get("codigo")),
            "categoria": cat,
            "categoria_producto_id": m.get("categoria_producto_id"),
            "unidad": m.get("unidad"),
            "stock": m.get("stock") or 0,
            "stock_min": m.get("stock_min") or 0,
            "stock_max": m.get("stock_max") or 0,
            "precio_unit": m.get("precio_unit") or 0,
            "proveedor_id": m.get("proveedor_id"),
            "obs": m.get("obs"),
            "actualizado": m.get("actualizado"),
            "activo": 1 if m.get("activo") in (None, 1, "1") else 0,
            "producto_id": prod_ref,
            "pse_firma": m.get("pse_firma"),
            "operacion_id": m.get("operacion_id"),
            "tipo": m.get("tipo"),
            "cliente_id": m.get("cliente_id"),
            "codigo_barras": m.get("codigo_barras"),
            "descripcion_larga": None,
            "tiempo_total_hs": 0, "costo_mat": 0, "costo_mo": 0, "precio_venta": 0,
            "peso_kg": 0, "capacidad_cajon": None,
            "creado": m.get("actualizado"),
        })
    return filas


# ─────────────────────────────────────────────────────────────────────────────
# Foto "antes" para verificar
# ─────────────────────────────────────────────────────────────────────────────
def _foto(db):
    f = {"conteos": {}, "refs_mat": {}, "refs_prod": {}}
    for t in _tablas(db):
        f["conteos"][t] = db.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
    for t, c in _fks_hacia(db, "materiales"):
        if t == "materiales":
            continue
        f["refs_mat"][(t, c)] = dict(db.execute(
            f'SELECT rowid, "{c}" FROM "{t}" WHERE "{c}" IS NOT NULL').fetchall())
    for t, c in _fks_hacia(db, "productos"):
        f["refs_prod"][(t, c)] = dict(db.execute(
            f'SELECT rowid, "{c}" FROM "{t}" WHERE "{c}" IS NOT NULL').fetchall())
    f["stock_total"] = db.execute("SELECT ROUND(COALESCE(SUM(stock),0),6) FROM materiales").fetchone()[0]
    if "novedades_produccion" in f["conteos"]:
        f["novedades"] = db.execute("""SELECT COUNT(*), ROUND(COALESCE(SUM(cantidad_producida),0),6),
            ROUND(COALESCE(SUM(tiempo_real_min),0),6) FROM novedades_produccion""").fetchone()
    f["ot_producto_codigo"] = dict(db.execute(
        "SELECT o.id, p.codigo FROM ordenes o LEFT JOIN productos p ON p.id=o.producto_id").fetchall())
    f["fk_violaciones"] = set(tuple(r) for r in db.execute("PRAGMA foreign_key_check").fetchall())
    return f


# ─────────────────────────────────────────────────────────────────────────────
# Migración
# ─────────────────────────────────────────────────────────────────────────────
def _reconstruir_con_fk_a_materiales(db, tabla):
    """Recrea `tabla` cambiando REFERENCES productos(...) por materiales(...)."""
    sql = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (tabla,)).fetchone()[0]
    nuevo = re.sub(r'REFERENCES\s+["`\[]?productos["`\]]?\s*\(', "REFERENCES materiales(", sql, flags=re.I)
    tmp = f"{tabla}__unif"
    nuevo = re.sub(r'^\s*CREATE\s+TABLE\s+(IF\s+NOT\s+EXISTS\s+)?("[^"]+"|`[^`]+`|\[[^\]]+\]|\S+)',
                   f'CREATE TABLE "{tmp}"', nuevo, count=1, flags=re.I)
    indices = [r[0] for r in db.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name=? AND sql IS NOT NULL", (tabla,))]
    triggers = [r[0] for r in db.execute(
        "SELECT sql FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (tabla,))]
    cols = ",".join(f'"{c}"' for c in _cols(db, tabla))
    # Conservar el contador AUTOINCREMENT: si se borraron filas al final, el
    # INSERT de la copia lo bajaría y se reusarían ids de registros borrados.
    seq_viejo = db.execute("SELECT seq FROM sqlite_sequence WHERE name=?", (tabla,)).fetchone()
    db.execute(f'DROP TABLE IF EXISTS "{tmp}"')
    db.execute(nuevo)
    db.execute(f'INSERT INTO "{tmp}" ({cols}) SELECT {cols} FROM "{tabla}"')
    db.execute(f'DROP TABLE "{tabla}"')
    db.execute(f'ALTER TABLE "{tmp}" RENAME TO "{tabla}"')
    for s in indices + triggers:
        db.execute(s)
    if seq_viejo is not None:
        actual = db.execute("SELECT seq FROM sqlite_sequence WHERE name=?", (tabla,)).fetchone()
        if actual is None:
            db.execute("INSERT INTO sqlite_sequence (name, seq) VALUES (?,?)", (tabla, seq_viejo[0]))
        elif (actual[0] or 0) < (seq_viejo[0] or 0):
            db.execute("UPDATE sqlite_sequence SET seq=? WHERE name=?", (seq_viejo[0], tabla))


def _remapear_snapshots(db, mapa):
    if _tipo_objeto(db, "producto_versiones") != "table":
        return 0
    cambiados = 0
    for vid, snap in db.execute("SELECT id, snapshot FROM producto_versiones").fetchall():
        try:
            d = json.loads(snap)
        except Exception:
            continue
        tocado = False
        for op in d.get("operaciones") or []:
            for m in op.get("materiales") or []:
                mid = m.get("material_id")
                if mid in mapa and mapa[mid] != mid:
                    m["material_id"] = mapa[mid]
                    tocado = True
        if tocado:
            db.execute("UPDATE producto_versiones SET snapshot=? WHERE id=?",
                       (json.dumps(d, ensure_ascii=False), vid))
            cambiados += 1
    return cambiados


def _verificar(db, antes, plan):
    errores = []
    mapa = plan["mapa"]
    despues_conteos = {t: db.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in _tablas(db)}
    for t, n in antes["conteos"].items():
        if t in ("materiales", "productos", "sqlite_sequence"):
            continue
        if despues_conteos.get(t) != n:
            errores.append(f"Tabla {t}: {n} filas antes, {despues_conteos.get(t)} después")
    esperado = len(plan["prods"]) + len(plan["mats"]) - len(plan["prod_de_gemelo"])
    if despues_conteos.get("materiales") != esperado:
        errores.append(f"materiales: se esperaban {esperado} artículos y hay {despues_conteos.get('materiales')}")
    st = db.execute("SELECT ROUND(COALESCE(SUM(stock),0),6) FROM materiales").fetchone()[0]
    if abs((st or 0) - (antes["stock_total"] or 0)) > 0.0001:
        errores.append(f"Stock total: {antes['stock_total']} antes, {st} después")
    for (t, c), filas in antes["refs_mat"].items():
        ahora = dict(db.execute(f'SELECT rowid, "{c}" FROM "{t}" WHERE "{c}" IS NOT NULL').fetchall())
        for rid, viejo in filas.items():
            if ahora.get(rid) != mapa.get(viejo, viejo):
                errores.append(f"{t}.{c} fila {rid}: esperaba {mapa.get(viejo, viejo)}, hay {ahora.get(rid)}")
                break
        if len(ahora) != len(filas):
            errores.append(f"{t}.{c}: {len(filas)} referencias antes, {len(ahora)} después")
    for (t, c), filas in antes["refs_prod"].items():
        if t == "materiales":
            continue
        ahora = dict(db.execute(f'SELECT rowid, "{c}" FROM "{t}" WHERE "{c}" IS NOT NULL').fetchall())
        if ahora != filas:
            errores.append(f"{t}.{c}: cambiaron referencias a productos (no debería)")
    if "novedades" in antes:
        nov = db.execute("""SELECT COUNT(*), ROUND(COALESCE(SUM(cantidad_producida),0),6),
            ROUND(COALESCE(SUM(tiempo_real_min),0),6) FROM novedades_produccion""").fetchone()
        if tuple(nov) != tuple(antes["novedades"]):
            errores.append(f"Novedades: {tuple(antes['novedades'])} antes, {tuple(nov)} después")
    ot_ahora = dict(db.execute(
        "SELECT o.id, m.codigo FROM ordenes o LEFT JOIN materiales m ON m.id=o.producto_id").fetchall())
    if ot_ahora != antes["ot_producto_codigo"]:
        dif = [k for k in antes["ot_producto_codigo"] if ot_ahora.get(k) != antes["ot_producto_codigo"][k]]
        errores.append(f"OTs con producto distinto después de migrar: {dif[:10]}")
    viol = set(tuple(r) for r in db.execute("PRAGMA foreign_key_check").fetchall())
    nuevas = [v for v in viol if v[0] not in ("materiales",) and v not in antes["fk_violaciones"]]
    viol_mat = [v for v in viol if v[0] == "materiales"]
    if nuevas or viol_mat:
        errores.append(f"foreign_key_check: {sorted(nuevas + viol_mat)[:10]}")
    pt_mal = db.execute("""SELECT COUNT(*) FROM materiales
        WHERE categoria='Producto terminado' AND (producto_id IS NULL OR producto_id<>id)""").fetchone()[0]
    if pt_mal:
        errores.append(f"{pt_mal} productos terminados sin auto-referencia en producto_id")
    integ = db.execute("PRAGMA integrity_check").fetchone()[0]
    if integ != "ok":
        errores.append(f"integrity_check: {integ}")
    return errores, despues_conteos


def _backup(db_path, destino_dir=None):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    destino_dir = destino_dir or os.path.dirname(os.path.abspath(db_path))
    destino = os.path.join(destino_dir, f"metalerp_backup_pre_unificacion_{ts}.db")
    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(destino)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return destino


def migrar(db_path, hacer_backup=True, log=print, informe_dir=None):
    """Migra la base. Devuelve dict con ok, informe (texto), ruta_informe,
    ruta_backup. Si algo falla hace ROLLBACK y devuelve ok=False."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    informe_dir = informe_dir or os.path.dirname(os.path.abspath(db_path))
    ruta_informe = os.path.join(informe_dir, f"unificacion_informe_{ts}.txt")
    lineas = [f"Unificación productos + materiales — {datetime.now():%Y-%m-%d %H:%M:%S}",
              f"Base: {os.path.abspath(db_path)}", ""]

    if not necesita_migrar(db_path):
        return {"ok": True, "ya_migrada": True, "informe": "La base ya está unificada.",
                "ruta_informe": None, "ruta_backup": None}

    ruta_backup = None
    if hacer_backup:
        # Instalación nueva (tablas vacías): no hay nada que respaldar.
        _c = sqlite3.connect(db_path)
        try:
            vacia = (_c.execute("SELECT COUNT(*) FROM productos").fetchone()[0] == 0 and
                     _c.execute("SELECT COUNT(*) FROM materiales").fetchone()[0] == 0)
        finally:
            _c.close()
        hacer_backup = not vacia
    if hacer_backup:
        ruta_backup = _backup(db_path)
        lineas.append(f"Backup completo previo: {ruta_backup}")
        log(f"[unificación] Backup: {ruta_backup}")

    db = sqlite3.connect(db_path, isolation_level=None, timeout=60)
    db.row_factory = sqlite3.Row
    ok = False
    try:
        db.execute("PRAGMA foreign_keys = OFF")
        db.execute("BEGIN IMMEDIATE")
        plan = analizar(db)
        antes = _foto(db)

        lineas += ["", "=== RESUMEN ===",
                   f"Productos (ficha de proceso): {len(plan['prods'])}",
                   f"Materiales (inventario):      {len(plan['mats'])}",
                   f"  de los cuales gemelos de stock de un producto: {len(plan['prod_de_gemelo'])}",
                   f"Artículos en la tabla unificada: "
                   f"{len(plan['prods']) + len(plan['mats']) - len(plan['prod_de_gemelo'])}",
                   f"Materiales que cambian de id: "
                   f"{sum(1 for k, v in plan['mapa'].items() if k != v)} "
                   f"(gemelos que toman el id de su producto + choques de id)",
                   f"Códigos renombrados por choque: {len(plan['renombres'])}"]
        if plan["bloqueos"]:
            lineas += ["", "=== BLOQUEOS (no se migró) ==="] + [" - " + b for b in plan["bloqueos"]]
            raise RuntimeError("Hay conflictos que requieren una decisión manual: " + " / ".join(plan["bloqueos"]))

        mapa = plan["mapa"]
        # 1) Remapear referencias a materiales que cambian de id.
        db.execute("DROP TABLE IF EXISTS temp._mapa_mat")
        db.execute("CREATE TEMP TABLE _mapa_mat (viejo INTEGER PRIMARY KEY, nuevo INTEGER NOT NULL)")
        db.executemany("INSERT INTO temp._mapa_mat VALUES (?,?)",
                       [(k, v) for k, v in mapa.items() if k != v])
        for t, c in _fks_hacia(db, "materiales"):
            if t == "materiales":
                continue
            db.execute(f'''UPDATE "{t}" SET "{c}"=(SELECT nuevo FROM temp._mapa_mat WHERE viejo="{t}"."{c}")
                WHERE "{c}" IN (SELECT viejo FROM temp._mapa_mat)''')
        # Insumos "producto" sin material: el material ahora es el mismo producto.
        for t in ("operacion_materiales", "orden_operacion_materiales"):
            if _tipo_objeto(db, t) == "table" and "producto_id" in _cols(db, t):
                db.execute(f'''UPDATE "{t}" SET material_id=producto_id
                    WHERE material_id IS NULL AND producto_id IS NOT NULL''')
        n_snap = _remapear_snapshots(db, mapa)

        # 2) Tabla unificada.
        filas = _filas_unificadas(plan)
        db.execute('DROP TABLE IF EXISTS "materiales__unif"')
        db.execute(DDL_MATERIALES.format(nombre="materiales__unif"))
        ph = ",".join("?" * len(COLUMNAS_MATERIALES))
        db.executemany(
            f'INSERT INTO "materiales__unif" ({",".join(COLUMNAS_MATERIALES)}) VALUES ({ph})',
            [[f[c] for c in COLUMNAS_MATERIALES] for f in filas])
        indices_mat = [r[0] for r in db.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name='materiales' AND sql IS NOT NULL")]
        db.execute("DROP TABLE materiales")
        db.execute('ALTER TABLE "materiales__unif" RENAME TO materiales')
        for s in indices_mat:
            db.execute(s)
        for s in INDICES_EXTRA:
            db.execute(s)

        # 3) Tablas que apuntaban a productos(id) -> materiales(id).
        hijas = [t for t, _c in _fks_hacia(db, "productos")]
        db.execute("DROP TABLE productos")
        for t in sorted(set(hijas)):
            if t == "materiales":
                continue
            _reconstruir_con_fk_a_materiales(db, t)

        # 4) Vista de compatibilidad + triggers + secuencias.
        db.execute("DROP VIEW IF EXISTS productos")
        db.execute(DDL_VISTA_PRODUCTOS)
        for s in DDL_TRIGGERS:
            db.execute(s)
        db.execute("DELETE FROM sqlite_sequence WHERE name IN ('productos','materiales')")
        db.execute("INSERT INTO sqlite_sequence (name, seq) VALUES ('materiales', ?)",
                   (max(plan["seq_final"], db.execute("SELECT COALESCE(MAX(id),0) FROM materiales").fetchone()[0]),))

        # 5) Verificación antes de confirmar.
        errores, despues = _verificar(db, antes, plan)
        lineas += ["", "=== VERIFICACIÓN ==="]
        for t in sorted(antes["conteos"]):
            if t in ("sqlite_sequence",):
                continue
            a, d = antes["conteos"][t], despues.get(t, "(vista)" if t == "productos" else "—")
            marca = "" if (a == d or t in ("materiales", "productos")) else "   <-- DIFERENTE"
            lineas.append(f"  {t:34s} antes={a:<6} después={d}{marca}")
        lineas.append(f"  Stock total antes={antes['stock_total']} después="
                      f"{db.execute('SELECT ROUND(COALESCE(SUM(stock),0),6) FROM materiales').fetchone()[0]}")
        if "novedades" in antes:
            lineas.append(f"  Novedades (cantidad, Σ producido, Σ minutos): {tuple(antes['novedades'])}")
        lineas.append(f"  Versiones de proceso con material remapeado: {n_snap}")
        if errores:
            lineas += ["", "ERRORES DE VERIFICACIÓN — se hizo ROLLBACK, la base no se modificó:"] + \
                      [" - " + e for e in errores]
            raise RuntimeError("La verificación falló: " + "; ".join(errores[:5]))
        lineas.append("  Todas las verificaciones OK.")

        if _tipo_objeto(db, "configuracion") == "table":
            db.execute("INSERT OR REPLACE INTO configuracion (clave,valor,descripcion) VALUES (?,?,?)",
                       (MARCA_CONFIG, datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "Productos y materiales unificados en la tabla materiales"))
        db.execute("COMMIT")
        ok = True
        lineas += ["", "=== DECISIONES AUTOMÁTICAS ==="] + ([" - " + a for a in plan["acciones"]] or [" (ninguna)"])
        lineas += ["", "=== PARA REVISAR (no bloquean) ==="] + ([" - " + a for a in plan["avisos"]] or [" (nada)"])
        lineas += ["", "=== MAPA DE IDS DE MATERIALES (viejo -> nuevo) ==="]
        lineas += [f"  {k} -> {v}  ({plan['mats'][k]['codigo']})" for k, v in sorted(plan["mapa"].items()) if k != v]
        lineas += ["", "Migración confirmada (COMMIT)."]
    except Exception as e:
        try:
            db.execute("ROLLBACK")
        except Exception:
            pass
        lineas += ["", f"*** MIGRACIÓN CANCELADA: {e}", "La base quedó sin cambios."]
        log(f"[unificación] ERROR: {e}")
    finally:
        try:
            db.execute("PRAGMA foreign_keys = ON")
        except Exception:
            pass
        db.close()

    texto = "\n".join(lineas)
    try:
        with open(ruta_informe, "w", encoding="utf-8") as fh:
            fh.write(texto)
    except Exception:
        ruta_informe = None
    return {"ok": ok, "ya_migrada": False, "informe": texto,
            "ruta_informe": ruta_informe, "ruta_backup": ruta_backup}


def simular(db_path, log=print):
    """Corre la migración completa sobre una copia temporal. No toca el original."""
    tmpdir = tempfile.mkdtemp(prefix="metalerp_sim_")
    copia = os.path.join(tmpdir, "simulacion.db")
    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(copia)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    res = migrar(copia, hacer_backup=False, log=log, informe_dir=tmpdir)
    res["ruta_copia"] = copia
    return res


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    ruta = args[0] if args else os.path.join(os.path.dirname(os.path.abspath(__file__)), "database", "metalerp.db")
    if "--simular" in sys.argv:
        r = simular(ruta)
        print(r["informe"])
        print(f"\n(Simulación sobre copia: {r.get('ruta_copia')}. La base original no se tocó.)")
    else:
        r = migrar(ruta)
        print(r["informe"])
    sys.exit(0 if r["ok"] else 1)

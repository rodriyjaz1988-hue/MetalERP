#!/usr/bin/env python3
"""MetalERP v3.0 - Sistema ERP Taller Metalurgico"""
import os, re, socket, sqlite3, hashlib, secrets, math
from datetime import datetime, date, timedelta
from functools import wraps
from flask import Flask, render_template, request, jsonify, session, redirect, g, send_from_directory

# ── Permisos predeterminados por rol ──────────────────────────────────────────
DEFAULT_PERMISIONES = {
    'operario': {
        'ver_ordenes_trabajo': '1',
        'ver_procesos_productos': '1',
        'ver_control_produccion': '1',
        'ver_novedades_por_ot': '1',
    },
    'logistica': {
        'mod_inventario': '1',
        'mod_lotes': '1',
        'mod_oc_clientes': '1',
    }
}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, "database", "metalerp.db")
app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = secrets.token_hex(32)
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

def get_db():
    if "db" not in g:
        # timeout=30 -> si la DB esta bloqueada por otra conexion (varios
        # operarios en simultaneo), espera hasta 30s en vez de fallar al toque
        g.db = sqlite3.connect(DB_PATH, timeout=30)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        # WAL permite que lecturas y escrituras convivan sin bloquearse entre si,
        # clave cuando hay varias cuentas conectadas por la misma red local
        g.db.execute("PRAGMA journal_mode = WAL")
        g.db.execute("PRAGMA busy_timeout = 30000")
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop("db", None)
    if db: db.close()

def query(sql, params=(), one=False):
    cur = get_db().execute(sql, params)
    rows = cur.fetchall()
    return (rows[0] if rows else None) if one else rows

def execute(sql, params=()):
    db = get_db()
    cur = db.execute(sql, params)
    db.commit()
    return cur.lastrowid

def get_or_create_pt_material(prod):
    """Devuelve (creando si hace falta) el material de categoría 'Producto
    terminado' correspondiente a un producto.

    Es la ÚNICA fuente de verdad para este mapeo producto -> material de
    stock. Todo el código que necesite ese material (generación de PT al
    completar una OT, novedades de producción, alta/copia de producto,
    diagnósticos, etc.) debe llamar a esta función en vez de repetir la
    consulta/insert a mano — así evitamos que cada punto del código diverja
    y se generen inconsistencias.

    IMPORTANTE: productos.codigo y materiales.codigo son namespaces UNIQUE
    independientes entre sí. Pueden coincidir por casualidad (ej. un
    material de materia prima con el mismo código que un producto sin
    ninguna relación real entre ambos).

    El vínculo real y definitivo es materiales.producto_id (FK), NO el
    código. Requiere que `prod` tenga "id". Si dos productos comparten
    código y ambos terminan necesitando un material PT, cada uno obtiene
    su propio material (identificado por producto_id) aunque el código
    visible se tenga que desambiguar con un sufijo — así nunca se
    mezcla el stock de un producto con el de otro material/producto
    que casualmente comparte código.
    """
    prod_keys = prod.keys() if hasattr(prod, "keys") else prod
    if "id" not in prod_keys or prod["id"] is None:
        raise ValueError("get_or_create_pt_material requiere prod['id'] (producto_id)")

    # 1) Búsqueda por vínculo real (FK), no por string de código. Se filtra
    # también por categoria porque un mismo producto puede tener ADEMÁS un
    # material "Producto sin lote" (excedente de producción, ver
    # get_or_create_sinlote_material) con el mismo producto_id.
    mat_pt = query("SELECT id,stock FROM materiales WHERE producto_id=? AND categoria='Producto terminado'", (prod["id"],), one=True)
    if mat_pt:
        return mat_pt

    # 2) No existe vínculo todavía. Buscamos un código libre para crear el
    #    material, evitando pisar cualquier material ya existente (sea cual
    #    sea su categoría o a qué producto -si alguno- esté vinculado).
    codigo_base = prod["codigo"]
    candidato = codigo_base
    intento = 1
    while query("SELECT id FROM materiales WHERE codigo=?", (candidato,), one=True):
        intento += 1
        candidato = f"{codigo_base}-PT{intento}"

    new_mid = execute(
        "INSERT INTO materiales (codigo,descripcion,categoria,producto_id,unidad,stock,stock_min) VALUES (?,?,?,?,?,0,0)",
        (candidato, prod["nombre"], "Producto terminado", prod["id"], prod["unidad"]))
    return {"id": new_mid, "stock": 0}

def get_or_create_sinlote_material(prod):
    """Devuelve (creando si hace falta) el material de categoría 'Producto sin
    lote' correspondiente a un producto: piezas que sobraron de producir de
    más en una OT (por encima de lo pedido) y que quedan como stock directo,
    SIN pasar por lote ni por clasificación de Calidad — igual que Insumo/
    Herramienta. Convive con el material 'Producto terminado' del mismo
    producto (mismo producto_id, categoria distinta).
    """
    prod_keys = prod.keys() if hasattr(prod, "keys") else prod
    if "id" not in prod_keys or prod["id"] is None:
        raise ValueError("get_or_create_sinlote_material requiere prod['id'] (producto_id)")

    mat = query("SELECT id,stock FROM materiales WHERE producto_id=? AND categoria='Producto sin lote'",
        (prod["id"],), one=True)
    if mat:
        return mat

    codigo_base = f"{prod['codigo']}-SL"
    candidato = codigo_base
    intento = 1
    while query("SELECT id FROM materiales WHERE codigo=?", (candidato,), one=True):
        intento += 1
        candidato = f"{codigo_base}{intento}"

    new_mid = execute(
        "INSERT INTO materiales (codigo,descripcion,categoria,producto_id,unidad,stock,stock_min) VALUES (?,?,?,?,?,0,0)",
        (candidato, f"{prod['nombre']} (sin lote)", "Producto sin lote", prod["id"], prod["unidad"]))
    return {"id": new_mid, "stock": 0}

def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def login_required(roles=None):
    def decorator(f):
        @wraps(f)
        def wrapped(*a, **kw):
            if "user_id" not in session:
                # Las rutas /api/* siempre son llamadas por fetch() esperando
                # JSON (ver api() en app.html). Devolverles un redirect HTML
                # a /login hace que r.json() explote con un error críptico
                # ("Unexpected token '<'") en vez de mostrar algo entendible.
                # Solo se redirige de verdad para rutas que no son de API
                # (navegación directa del browser).
                if request.path.startswith("/api/"):
                    return jsonify({"error": "Sesión expirada, volvé a iniciar sesión."}), 401
                return redirect("/login")
            if roles and session.get("rol") not in roles:
                return jsonify({"error": "Sin permiso"}), 403
            return f(*a, **kw)
        return wrapped
    return decorator

# ── Schema ────────────────────────────────────────────────────────────────────
SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL, password TEXT NOT NULL,
    nombre TEXT NOT NULL,
    rol TEXT NOT NULL CHECK(rol IN ('admin','operario','vendedor','almacen','logistica')),
    activo INTEGER DEFAULT 1,
    creado TEXT DEFAULT (datetime('now','localtime')));

CREATE TABLE IF NOT EXISTS categorias_maquina (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT UNIQUE NOT NULL, descripcion TEXT,
    creado TEXT DEFAULT (datetime('now','localtime')));

CREATE TABLE IF NOT EXISTS maquinas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo TEXT UNIQUE NOT NULL, nombre TEXT NOT NULL,
    categoria_id INTEGER REFERENCES categorias_maquina(id),
    marca TEXT, modelo TEXT, numero_serie TEXT, anio INTEGER,
    ubicacion TEXT, estado TEXT DEFAULT 'Operativa',
    horas_uso REAL DEFAULT 0, obs TEXT,
    creado TEXT DEFAULT (datetime('now','localtime')));

CREATE TABLE IF NOT EXISTS maquina_reemplazos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    maquina_id INTEGER NOT NULL REFERENCES maquinas(id) ON DELETE CASCADE,
    reemplazo_id INTEGER NOT NULL REFERENCES maquinas(id) ON DELETE CASCADE,
    UNIQUE(maquina_id, reemplazo_id));

CREATE TABLE IF NOT EXISTS mantenimiento_plan (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    maquina_id INTEGER NOT NULL REFERENCES maquinas(id) ON DELETE CASCADE,
    tarea TEXT NOT NULL, tipo TEXT DEFAULT 'Frecuencia fija',
    frecuencia_tipo TEXT, frecuencia_valor INTEGER,
    ultima_fecha TEXT, proxima_fecha TEXT,
    responsable TEXT, obs TEXT,
    creado TEXT DEFAULT (datetime('now','localtime')));

CREATE TABLE IF NOT EXISTS tickets_reparacion (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    numero TEXT UNIQUE NOT NULL,
    maquina_id INTEGER NOT NULL REFERENCES maquinas(id),
    tipo TEXT DEFAULT 'Correctivo', descripcion TEXT NOT NULL,
    prioridad TEXT DEFAULT 'Normal', estado TEXT DEFAULT 'Abierto',
    responsable TEXT,
    fecha_apertura TEXT DEFAULT (datetime('now','localtime')),
    fecha_cierre TEXT, horas_paro REAL DEFAULT 0,
    horas_ajuste REAL DEFAULT 0,
    costo REAL DEFAULT 0, solucion TEXT,
    creado_por INTEGER REFERENCES usuarios(id),
    creado TEXT DEFAULT (datetime('now','localtime')));

CREATE TABLE IF NOT EXISTS categorias_producto (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT UNIQUE NOT NULL, descripcion TEXT,
    creado TEXT DEFAULT (datetime('now','localtime')));

CREATE TABLE IF NOT EXISTS proveedores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    razon TEXT NOT NULL, cuit TEXT, contacto TEXT,
    telefono TEXT, email TEXT, materiales TEXT,
    plazo_dias INTEGER DEFAULT 3, calificacion INTEGER DEFAULT 5,
    estado TEXT DEFAULT 'Activo', obs TEXT,
    creado TEXT DEFAULT (datetime('now','localtime')));

CREATE TABLE IF NOT EXISTS materiales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo TEXT UNIQUE NOT NULL, descripcion TEXT NOT NULL,
    categoria TEXT DEFAULT 'Material',
    categoria_producto_id INTEGER REFERENCES categorias_producto(id),
    producto_id INTEGER REFERENCES productos(id),
    unidad TEXT DEFAULT 'kg', stock REAL DEFAULT 0,
    stock_min REAL DEFAULT 0, stock_max REAL DEFAULT 0,
    precio_unit REAL DEFAULT 0,
    proveedor_id INTEGER REFERENCES proveedores(id),
    obs TEXT,
    actualizado TEXT DEFAULT (datetime('now','localtime')));

CREATE TABLE IF NOT EXISTS proveedor_materiales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proveedor_id INTEGER NOT NULL REFERENCES proveedores(id) ON DELETE CASCADE,
    material_id INTEGER NOT NULL REFERENCES materiales(id) ON DELETE CASCADE,
    precio_unit REAL DEFAULT 0, plazo_dias INTEGER DEFAULT 3,
    es_principal INTEGER DEFAULT 0,
    UNIQUE(proveedor_id, material_id));

CREATE TABLE IF NOT EXISTS clientes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    razon TEXT NOT NULL, cuit TEXT UNIQUE, iva TEXT,
    rubro TEXT, localidad TEXT, direccion TEXT,
    contacto TEXT, cargo TEXT, telefono TEXT, email TEXT,
    categoria TEXT DEFAULT 'Regular', plazo_pago TEXT,
    trabajos TEXT, obs TEXT,
    creado TEXT DEFAULT (datetime('now','localtime')));

CREATE TABLE IF NOT EXISTS productos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo TEXT UNIQUE NOT NULL, nombre TEXT NOT NULL,
    descripcion TEXT,
    categoria_id INTEGER REFERENCES categorias_producto(id),
    unidad TEXT DEFAULT 'unid',
    tiempo_total_hs REAL DEFAULT 0,
    costo_mat REAL DEFAULT 0, costo_mo REAL DEFAULT 0,
    precio_venta REAL DEFAULT 0,
    activo INTEGER DEFAULT 1, obs TEXT,
    creado TEXT DEFAULT (datetime('now','localtime')));

CREATE TABLE IF NOT EXISTS proceso_operaciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    producto_id INTEGER NOT NULL REFERENCES productos(id) ON DELETE CASCADE,
    orden INTEGER DEFAULT 1, nombre TEXT NOT NULL,
    descripcion TEXT,
    categoria_maquina_id INTEGER REFERENCES categorias_maquina(id),
    maquina_id INTEGER REFERENCES maquinas(id),
    tiempo_setup_min INTEGER DEFAULT 0,
    tiempo_ciclo_min INTEGER DEFAULT 0,
    es_tercerizada INTEGER DEFAULT 0,
    proveedor_id INTEGER REFERENCES proveedores(id),
    precio_tercerizado REAL DEFAULT 0,
    tiempo_minimo_dias INTEGER DEFAULT 0,
    volumen_agrupado INTEGER DEFAULT 0,
    valor_recalculado REAL DEFAULT 0,
    obs TEXT);

CREATE TABLE IF NOT EXISTS operacion_materiales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    operacion_id INTEGER NOT NULL REFERENCES proceso_operaciones(id) ON DELETE CASCADE,
    material_id INTEGER NOT NULL REFERENCES materiales(id),
    cantidad REAL NOT NULL, unidad TEXT);

CREATE TABLE IF NOT EXISTS ordenes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    numero TEXT UNIQUE NOT NULL,
    cliente_id INTEGER REFERENCES clientes(id),
    producto_id INTEGER REFERENCES productos(id),
    descripcion TEXT NOT NULL, detalle TEXT,
    cantidad REAL DEFAULT 1, operario TEXT, maquina TEXT,
    prioridad TEXT DEFAULT 'Normal', estado TEXT DEFAULT 'Pendiente',
    fecha_inicio TEXT, fecha_entrega TEXT,
    costo_mat REAL DEFAULT 0, costo_mo REAL DEFAULT 0,
    precio_venta REAL DEFAULT 0, obs TEXT,
    creado TEXT DEFAULT (datetime('now','localtime')),
    actualizado TEXT DEFAULT (datetime('now','localtime')));

CREATE TABLE IF NOT EXISTS presupuestos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    numero TEXT UNIQUE NOT NULL,
    cliente_id INTEGER REFERENCES clientes(id),
    descripcion TEXT NOT NULL, items TEXT,
    subtotal REAL DEFAULT 0, iva_pct REAL DEFAULT 21,
    total REAL DEFAULT 0, validez_dias INTEGER DEFAULT 30,
    estado TEXT DEFAULT 'Borrador', obs TEXT,
    creado TEXT DEFAULT (datetime('now','localtime')));

CREATE TABLE IF NOT EXISTS lotes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    numero TEXT UNIQUE NOT NULL,
    material_id INTEGER NOT NULL REFERENCES materiales(id),
    cantidad_original REAL NOT NULL,
    cantidad_disponible REAL NOT NULL,
    cantidad_activa REAL DEFAULT 0,
    cantidad_rechazada REAL DEFAULT 0,
    proveedor_id INTEGER REFERENCES proveedores(id),
    fecha_ingreso TEXT DEFAULT (datetime('now','localtime')),
    referencia_proveedor TEXT,
    certificado TEXT,
    estado TEXT DEFAULT 'Ingresado' CHECK(estado IN ('Ingresado','Aprobado','Agotado','Rechazado')),
    obs TEXT,
    creado_por INTEGER REFERENCES usuarios(id),
    creado TEXT DEFAULT (datetime('now','localtime')));

CREATE TABLE IF NOT EXISTS remitos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    numero TEXT UNIQUE NOT NULL,
    cliente_id INTEGER REFERENCES clientes(id),
    orden_cliente_id INTEGER REFERENCES ordenes_cliente(id),
    fecha TEXT DEFAULT (datetime('now','localtime')),
    estado TEXT DEFAULT 'Emitido',
    obs TEXT,
    creado_por INTEGER REFERENCES usuarios(id),
    creado TEXT DEFAULT (datetime('now','localtime')));

CREATE TABLE IF NOT EXISTS remito_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    remito_id INTEGER NOT NULL REFERENCES remitos(id) ON DELETE CASCADE,
    material_id INTEGER NOT NULL REFERENCES materiales(id),
    lote_id INTEGER NOT NULL REFERENCES lotes(id),
    orden_cliente_item_id INTEGER REFERENCES ordenes_cliente_items(id),
    cantidad REAL NOT NULL,
    obs TEXT);

CREATE TABLE IF NOT EXISTS orden_lotes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    orden_id INTEGER NOT NULL REFERENCES ordenes(id) ON DELETE CASCADE,
    lote_id INTEGER NOT NULL REFERENCES lotes(id),
    material_id INTEGER NOT NULL REFERENCES materiales(id),
    cantidad_usada REAL NOT NULL,
    fecha TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(orden_id, lote_id));

CREATE TABLE IF NOT EXISTS movimientos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    material_id INTEGER REFERENCES materiales(id),
    lote_id INTEGER REFERENCES lotes(id),
    tipo TEXT NOT NULL, cantidad REAL NOT NULL,
    referencia TEXT, usuario_id INTEGER REFERENCES usuarios(id),
    fecha TEXT DEFAULT (datetime('now','localtime')));

CREATE TABLE IF NOT EXISTS producto_clientes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    producto_id INTEGER NOT NULL REFERENCES productos(id) ON DELETE CASCADE,
    cliente_id INTEGER NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
    UNIQUE(producto_id, cliente_id));

CREATE TABLE IF NOT EXISTS orden_operaciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    orden_id INTEGER NOT NULL REFERENCES ordenes(id) ON DELETE CASCADE,
    proceso_op_id INTEGER REFERENCES proceso_operaciones(id),
    orden INTEGER DEFAULT 1,
    nombre TEXT NOT NULL,
    categoria_maquina_id INTEGER REFERENCES categorias_maquina(id),
    maquina_id INTEGER REFERENCES maquinas(id),
    tiempo_setup_min INTEGER DEFAULT 0,
    tiempo_ciclo_min INTEGER DEFAULT 0,
    estado TEXT DEFAULT 'Pendiente',
    qty_requerida REAL DEFAULT 0,
    qty_producida REAL DEFAULT 0,
    es_tercerizada INTEGER DEFAULT 0,
    proveedor_id INTEGER REFERENCES proveedores(id),
    precio_tercerizado REAL DEFAULT 0,
    tiempo_minimo_dias INTEGER DEFAULT 0);

CREATE TABLE IF NOT EXISTS orden_materiales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    orden_id INTEGER NOT NULL REFERENCES ordenes(id) ON DELETE CASCADE,
    material_id INTEGER NOT NULL REFERENCES materiales(id),
    cantidad_requerida REAL DEFAULT 0,
    cantidad_asignada REAL DEFAULT 0,
    unidad TEXT);

CREATE TABLE IF NOT EXISTS empleados (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    legajo TEXT UNIQUE NOT NULL,
    nombre TEXT NOT NULL,
    apellido TEXT NOT NULL,
    cargo TEXT,
    tipo TEXT DEFAULT 'Indirecto' CHECK(tipo IN ('Directo','Indirecto')),
    turno TEXT,
    activo INTEGER DEFAULT 1,
    obs TEXT,
    creado TEXT DEFAULT (datetime('now','localtime')));

CREATE TABLE IF NOT EXISTS empleado_maquinas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    empleado_id INTEGER NOT NULL REFERENCES empleados(id) ON DELETE CASCADE,
    categoria_maquina_id INTEGER NOT NULL REFERENCES categorias_maquina(id) ON DELETE CASCADE,
    UNIQUE(empleado_id, categoria_maquina_id));

CREATE TABLE IF NOT EXISTS ordenes_cliente (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    numero TEXT UNIQUE NOT NULL,
    cliente_id INTEGER NOT NULL REFERENCES clientes(id),
    fecha TEXT DEFAULT (datetime('now','localtime')),
    fecha_entrega TEXT,
    estado TEXT DEFAULT 'Recibida',
    obs TEXT,
    creado TEXT DEFAULT (datetime('now','localtime')));

CREATE TABLE IF NOT EXISTS ordenes_cliente_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    orden_cliente_id INTEGER NOT NULL REFERENCES ordenes_cliente(id) ON DELETE CASCADE,
    producto_id INTEGER NOT NULL REFERENCES productos(id),
    cantidad REAL NOT NULL,
    precio_unit REAL DEFAULT 0,
    fecha_deseada TEXT,
    ot_id INTEGER REFERENCES ordenes(id),
    obs TEXT);

CREATE TABLE IF NOT EXISTS novedades_produccion (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    numero TEXT UNIQUE NOT NULL,
    orden_id INTEGER NOT NULL REFERENCES ordenes(id),
    orden_operacion_id INTEGER NOT NULL REFERENCES orden_operaciones(id),
    empleado_id INTEGER REFERENCES empleados(id),
    maquina_id INTEGER REFERENCES maquinas(id),
    cantidad_producida REAL NOT NULL,
    tiempo_real_min REAL NOT NULL,
    turno TEXT,
    fecha TEXT DEFAULT (datetime('now','localtime')),
    rendimiento_pct REAL DEFAULT 0,
    desvio INTEGER DEFAULT 0,
    obs TEXT,
    creado_por INTEGER REFERENCES usuarios(id));

CREATE TABLE IF NOT EXISTS trabajo_no_productivo (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    numero TEXT UNIQUE NOT NULL,
    empleado_id INTEGER REFERENCES empleados(id),
    descripcion TEXT NOT NULL,
    tiempo_min REAL NOT NULL,
    fecha TEXT DEFAULT (datetime('now','localtime')),
    creado_por INTEGER REFERENCES usuarios(id),
    creado TEXT DEFAULT (datetime('now','localtime')));

CREATE TABLE IF NOT EXISTS solicitudes_compra (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    numero TEXT UNIQUE NOT NULL,
    tipo TEXT DEFAULT 'Productiva' CHECK(tipo IN ('Productiva','Indirecta')),
    material_id INTEGER REFERENCES materiales(id),
    descripcion TEXT NOT NULL,
    cantidad REAL NOT NULL,
    unidad TEXT,
    urgencia TEXT DEFAULT 'Normal',
    estado TEXT DEFAULT 'Pendiente',
    ot_origen_id INTEGER REFERENCES ordenes(id),
    centro_costo TEXT,
    solicitante_id INTEGER REFERENCES usuarios(id),
    obs TEXT,
    creado TEXT DEFAULT (datetime('now','localtime')));

CREATE TABLE IF NOT EXISTS cotizaciones_compra (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    solicitud_id INTEGER NOT NULL REFERENCES solicitudes_compra(id) ON DELETE CASCADE,
    proveedor_id INTEGER NOT NULL REFERENCES proveedores(id),
    precio_unit REAL NOT NULL,
    plazo_entrega_dias INTEGER DEFAULT 3,
    condicion_pago TEXT,
    seleccionada INTEGER DEFAULT 0,
    obs TEXT,
    creado TEXT DEFAULT (datetime('now','localtime')));

CREATE TABLE IF NOT EXISTS ordenes_compra (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    numero TEXT UNIQUE NOT NULL,
    proveedor_id INTEGER NOT NULL REFERENCES proveedores(id),
    estado TEXT DEFAULT 'Borrador',
    monto_total REAL DEFAULT 0,
    limite_aprobacion REAL DEFAULT 50000,
    aprobado_por INTEGER REFERENCES usuarios(id),
    fecha_aprobacion TEXT,
    fecha_entrega_est TEXT,
    obs TEXT,
    creado_por INTEGER REFERENCES usuarios(id),
    creado TEXT DEFAULT (datetime('now','localtime')));

CREATE TABLE IF NOT EXISTS ordenes_compra_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    oc_id INTEGER NOT NULL REFERENCES ordenes_compra(id) ON DELETE CASCADE,
    solicitud_id INTEGER REFERENCES solicitudes_compra(id),
    material_id INTEGER REFERENCES materiales(id),
    descripcion TEXT NOT NULL,
    cantidad REAL NOT NULL,
    cantidad_recibida REAL DEFAULT 0,
    precio_unit REAL NOT NULL,
    unidad TEXT);
"""

# ── Seed data ─────────────────────────────────────────────────────────────────
def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.executescript(SCHEMA)
    def cnt(t): return db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]

    if cnt("usuarios") == 0:
        db.execute("INSERT INTO usuarios (username,password,nombre,rol) VALUES (?,?,?,?)",
            ("admin", hash_pw("admin123"), "Administrador", "admin"))

    # categorias_maquina: sin seed (configurar desde app)


    # ── Migrations: add columns for existing DBs ─────────────────────────────
    def _cols(table):
        return [r[1] for r in db.execute(f"PRAGMA table_info({table})").fetchall()]

    # ordenes_cliente_items: fecha_deseada, ot_id
    oci = _cols("ordenes_cliente_items")
    if "fecha_deseada" not in oci:
        db.execute("ALTER TABLE ordenes_cliente_items ADD COLUMN fecha_deseada TEXT")
    if "ot_id" not in oci:
        db.execute("ALTER TABLE ordenes_cliente_items ADD COLUMN ot_id INTEGER REFERENCES ordenes(id)")

    # Reparación: vincular OTs generadas por MRP (antes del fix) a los renglones
    # de OC que quedaron con ot_id NULL, siempre que el cruce producto+cliente
    # sea inequívoco (una sola OT candidata, no usada ya por otro renglón).
    try:
        huerfanos = db.execute("""
            SELECT i.id item_id, i.producto_id, oc.cliente_id
            FROM ordenes_cliente_items i
            JOIN ordenes_cliente oc ON oc.id=i.orden_cliente_id
            WHERE (i.ot_id IS NULL OR i.ot_id=0) AND oc.estado != 'Pendiente'
        """).fetchall()
        for h in huerfanos:
            candidatas = db.execute("""
                SELECT o.id FROM ordenes o
                WHERE o.producto_id=? AND o.cliente_id=?
                AND o.id NOT IN (SELECT ot_id FROM ordenes_cliente_items WHERE ot_id IS NOT NULL)
            """, (h["producto_id"], h["cliente_id"])).fetchall()
            if len(candidatas) == 1:
                db.execute("UPDATE ordenes_cliente_items SET ot_id=? WHERE id=?",
                           (candidatas[0]["id"], h["item_id"]))
    except Exception:
        pass

    # materiales: producto_id (vínculo explícito material PT -> producto,
    # en vez de depender solo de que coincida el string de código)
    try:
        mc = _cols("materiales")
        if "producto_id" not in mc:
            db.execute("ALTER TABLE materiales ADD COLUMN producto_id INTEGER REFERENCES productos(id)")
        # Backfill SOLO para materiales que:
        #  a) tienen categoria='Producto terminado'
        #  b) su codigo matchea el codigo de UN SOLO producto
        #  c) la descripcion del material coincide con el nombre del producto
        #     (evita heredar el vínculo en casos de colisión como Acero/Soporte,
        #      donde el codigo coincide mas la descripcion NO corresponde)
        db.execute("""
            UPDATE materiales SET producto_id = (
                SELECT p.id FROM productos p
                WHERE p.codigo = materiales.codigo
                  AND p.nombre = materiales.descripcion
            )
            WHERE categoria='Producto terminado' AND producto_id IS NULL
              AND (SELECT COUNT(*) FROM productos p2 WHERE p2.codigo = materiales.codigo) = 1
        """)
        db.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_materiales_producto_id
            ON materiales(producto_id) WHERE producto_id IS NOT NULL
        """)
    except Exception: pass

    # El índice único de arriba (producto_id) permitía UN SOLO material por
    # producto. Para soportar el material "Producto sin lote" (excedente de
    # producción que no pasa por lotes/Calidad, va directo a stock) conviviendo
    # con el material "Producto terminado" del mismo producto, el índice pasa
    # a ser único por (producto_id, categoria).
    try:
        db.execute("DROP INDEX IF EXISTS idx_materiales_producto_id")
        db.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_materiales_producto_categoria
            ON materiales(producto_id, categoria) WHERE producto_id IS NOT NULL
        """)
    except Exception: pass

    # ordenes: sinlote_generado — cuánto de lo producido de más en esta OT
    # (por encima de la cantidad pedida) ya se acreditó al stock "Producto
    # sin lote" del producto. Permite que generar_pt_faltante_si_corresponde
    # sea idempotente igual que con el lote de PT.
    try:
        oc = _cols("ordenes")
        if "sinlote_generado" not in oc:
            db.execute("ALTER TABLE ordenes ADD COLUMN sinlote_generado REAL DEFAULT 0")
    except Exception: pass

    # lotes: cantidad_activa
    try:
        lc = _cols("lotes")
        if "cantidad_activa" not in lc:
            db.execute("ALTER TABLE lotes ADD COLUMN cantidad_activa REAL DEFAULT 0")
            db.execute("UPDATE lotes SET cantidad_activa=cantidad_disponible WHERE estado='Aprobado'")
    except Exception: pass

    # lotes: cantidad_reservada — stock apartado para OTs en curso, aún no consumido
    # Se descuenta de lo visible como "disponible libre" pero no del stock real hasta
    # que la OT se complete.
    try:
        lc = _cols("lotes")
        if "cantidad_reservada" not in lc:
            db.execute("ALTER TABLE lotes ADD COLUMN cantidad_reservada REAL DEFAULT 0")
    except Exception: pass

    # lotes: cantidad_rechazada (antes se calculaba sumando movimientos historicos,
    # lo cual podia superponerse con cantidad_activa y dar totales inconsistentes,
    # ej. 800 aprobado + 200 rechazado sobre un total de 800. Ahora es una columna
    # real que junto a cantidad_activa siempre respeta: activa+rechazada<=disponible)
    try:
        lc = _cols("lotes")
        if "cantidad_rechazada" not in lc:
            db.execute("ALTER TABLE lotes ADD COLUMN cantidad_rechazada REAL DEFAULT 0")
            for lr in db.execute("SELECT id,cantidad_disponible,cantidad_activa,estado FROM lotes").fetchall():
                disp = float(lr["cantidad_disponible"] or 0)
                act = float(lr["cantidad_activa"] or 0)
                hist = db.execute("""SELECT COALESCE(SUM(cantidad),0) FROM movimientos
                    WHERE lote_id=? AND tipo='ajuste' AND referencia LIKE '%Rechazado%'""",
                    (lr["id"],)).fetchone()[0]
                cupo = max(0.0, disp - act)  # espacio aun no aprobado, lo unico que puede estar "rechazado"
                rech = min(float(hist or 0), cupo)
                if lr["estado"] == "Rechazado" and rech <= 0:
                    rech = disp  # lote totalmente rechazado sin movimientos historicos detectables
                db.execute("UPDATE lotes SET cantidad_rechazada=? WHERE id=?", (rech, lr["id"]))
    except Exception: pass

    # movimientos: lote_id
    try:
        mc = _cols("movimientos")
        if "lote_id" not in mc:
            db.execute("ALTER TABLE movimientos ADD COLUMN lote_id INTEGER REFERENCES lotes(id)")
    except Exception: pass

    # lotes: agregar estado 'Abierto' al CHECK constraint. Un lote de PT
    # "cajón" queda en 'Abierto' mientras todavía no llegó a la capacidad
    # del producto (sigue recibiendo piezas de próximas novedades); al
    # llenarse pasa a 'Ingresado' (igual que antes: pendiente de Calidad).
    try:
        lot_ddl = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='lotes'").fetchone()
        if lot_ddl and 'Abierto' not in lot_ddl[0]:
            db.execute("""CREATE TABLE lotes_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                numero TEXT UNIQUE NOT NULL,
                material_id INTEGER NOT NULL REFERENCES materiales(id),
                cantidad_original REAL NOT NULL,
                cantidad_disponible REAL NOT NULL,
                cantidad_activa REAL DEFAULT 0,
                cantidad_rechazada REAL DEFAULT 0,
                cantidad_reservada REAL DEFAULT 0,
                proveedor_id INTEGER REFERENCES proveedores(id),
                fecha_ingreso TEXT DEFAULT (datetime('now','localtime')),
                referencia_proveedor TEXT,
                certificado TEXT,
                estado TEXT DEFAULT 'Ingresado' CHECK(estado IN ('Ingresado','Abierto','Aprobado','Agotado','Rechazado')),
                obs TEXT,
                creado_por INTEGER REFERENCES usuarios(id),
                creado TEXT DEFAULT (datetime('now','localtime')))""")
            cols_comunes = ",".join(_cols("lotes"))
            db.execute(f"INSERT INTO lotes_new ({cols_comunes}) SELECT {cols_comunes} FROM lotes")
            db.execute("DROP TABLE lotes")
            db.execute("ALTER TABLE lotes_new RENAME TO lotes")
    except Exception as e:
        print(f"[WARN] Migración lotes (estado Abierto) falló: {e}")

    # orden_operaciones: tercerizada fields
    ooc = _cols("orden_operaciones")
    for col, typedef in [("es_tercerizada","INTEGER DEFAULT 0"),("proveedor_id","INTEGER"),
                          ("precio_tercerizado","REAL DEFAULT 0"),("tiempo_minimo_dias","INTEGER DEFAULT 0")]:
        if col not in ooc:
            db.execute(f"ALTER TABLE orden_operaciones ADD COLUMN {col} {typedef}")

    # proceso_operaciones: tercerizada fields
    poc = _cols("proceso_operaciones")
    for col, typedef in [("es_tercerizada","INTEGER DEFAULT 0"),("proveedor_id","INTEGER"),
                          ("precio_tercerizado","REAL DEFAULT 0"),("tiempo_minimo_dias","INTEGER DEFAULT 0")]:
        if col not in poc:
            db.execute(f"ALTER TABLE proceso_operaciones ADD COLUMN {col} {typedef}")

    # proceso_operaciones: volumen agrupado — cuando está activo, la cantidad
    # requerida de esta operación no es igual al total a realizar de la OT,
    # sino el resultado de agrupar ese total en lotes de tamaño
    # "valor_recalculado" (redondeado hacia arriba). Ej: OT total=100,
    # valor_recalculado=33 → requerido=3 (ceil(100/33)).
    poc = _cols("proceso_operaciones")
    for col, typedef in [("volumen_agrupado","INTEGER DEFAULT 0"),("valor_recalculado","REAL DEFAULT 0")]:
        if col not in poc:
            db.execute(f"ALTER TABLE proceso_operaciones ADD COLUMN {col} {typedef}")

    # solicitudes_compra: ot_origen_id
    try:
        sc = _cols("solicitudes_compra")
        if "ot_origen_id" not in sc:
            db.execute("ALTER TABLE solicitudes_compra ADD COLUMN ot_origen_id INTEGER REFERENCES ordenes(id)")
    except Exception: pass

    # novedades_produccion: maquina_id
    try:
        npc = _cols("novedades_produccion")
        if "maquina_id" not in npc:
            db.execute("ALTER TABLE novedades_produccion ADD COLUMN maquina_id INTEGER REFERENCES maquinas(id)")
    except Exception: pass
    try:
        npc = _cols("novedades_produccion")
        if "piezas_observadas" not in npc:
            db.execute("ALTER TABLE novedades_produccion ADD COLUMN piezas_observadas REAL DEFAULT 0")
    except Exception: pass
    try:
        npc = _cols("novedades_produccion")
        if "tiempo_perdido" not in npc:
            db.execute("ALTER TABLE novedades_produccion ADD COLUMN tiempo_perdido REAL DEFAULT 0")
    except Exception: pass
    try:
        db.execute("ALTER TABLE productos ADD COLUMN peso_kg REAL DEFAULT 0")
    except Exception: pass

    # productos: capacidad_cajon — cantidad fija de piezas que entran en un
    # cajón de este producto. Cuando se declara una novedad de la ÚLTIMA
    # operación de la ruta, el PT generado se va acumulando en un lote de
    # "cajón" (numero = OT-N-C1, OT-N-C2, ...) hasta llegar a esta cantidad;
    # al llenarse, ese cajón queda listo para pasar a Calidad y se abre el
    # siguiente. Si es NULL o 0, se mantiene el comportamiento anterior (un
    # único lote de PT por OT, sin dividir en cajones).
    try:
        pc = _cols("productos")
        if "capacidad_cajon" not in pc:
            db.execute("ALTER TABLE productos ADD COLUMN capacidad_cajon INTEGER")
    except Exception: pass

    # ordenes: stock_descontado — flag para no descontar materiales dos veces al completar
    try:
        oc = _cols("ordenes")
        if "stock_descontado" not in oc:
            db.execute("ALTER TABLE ordenes ADD COLUMN stock_descontado INTEGER DEFAULT 0")
    except Exception: pass

    # ── Órdenes de Trabajo de Terceros (OTT) ────────────────────────────────
    db.execute("""CREATE TABLE IF NOT EXISTS ordenes_tercerizado (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        numero TEXT UNIQUE NOT NULL,
        ot_origen_id INTEGER REFERENCES ordenes(id) ON DELETE SET NULL,
        operacion_id INTEGER REFERENCES orden_operaciones(id) ON DELETE SET NULL,
        proceso_op_id INTEGER REFERENCES proceso_operaciones(id),
        proveedor_id INTEGER REFERENCES proveedores(id),
        precio_acordado REAL DEFAULT 0,
        estado TEXT DEFAULT 'Pendiente'
            CHECK(estado IN ('Pendiente','Remito emitido','En proceso','Recibido','Completado','Cancelado')),
        es_ultimo_nivel INTEGER DEFAULT 0,
        remito_traslado_id INTEGER REFERENCES remitos(id),
        lote_retorno_id INTEGER REFERENCES lotes(id),
        fecha_envio TEXT,
        fecha_retorno_est TEXT,
        fecha_retorno_real TEXT,
        obs TEXT,
        creado TEXT DEFAULT (datetime('now','localtime')),
        creado_por INTEGER REFERENCES usuarios(id)
    )""")

    # ── Tabla configuración del sistema (ensure remitos has tipo column) ─────
    try:
        db.execute("ALTER TABLE remitos ADD COLUMN tipo TEXT DEFAULT 'entrega_cliente'")
    except Exception: pass
    try:
        db.execute("ALTER TABLE remitos ADD COLUMN ott_id INTEGER REFERENCES ordenes_tercerizado(id)")
    except Exception: pass

    # ── Herramientas por operación ───────────────────────────────────────────
    db.execute("""CREATE TABLE IF NOT EXISTS herramientas_operacion (
        id INTEGER PRIMARY KEY,
        operacion_id INTEGER NOT NULL REFERENCES proceso_operaciones(id) ON DELETE CASCADE,
        orden INTEGER DEFAULT 1,
        nombre TEXT NOT NULL,
        descripcion TEXT,
        duracion_min REAL DEFAULT 0,
        unidad TEXT DEFAULT 'unid',
        cantidad REAL DEFAULT 1
    )""")

    # ── Permisos por usuario ──────────────────────────────────────────────────
    db.execute("""CREATE TABLE IF NOT EXISTS usuario_permisos (
        id INTEGER PRIMARY KEY,
        usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
        clave TEXT NOT NULL,
        valor TEXT,
        UNIQUE(usuario_id, clave)
    )""")

    try:
        db.execute("ALTER TABLE productos ADD COLUMN cliente_id INTEGER REFERENCES clientes(id)")
    except Exception: pass
    try:
        db.execute("ALTER TABLE operacion_materiales ADD COLUMN tipo TEXT DEFAULT 'material'")
    except Exception: pass
    try:
        db.execute("ALTER TABLE operacion_materiales ADD COLUMN producto_id INTEGER REFERENCES productos(id)")
    except Exception: pass
    try:
        db.execute("ALTER TABLE proceso_operaciones ADD COLUMN es_tercerizada INTEGER DEFAULT 0")
    except Exception: pass
    try:
        db.execute("ALTER TABLE proceso_operaciones ADD COLUMN proveedor_id INTEGER REFERENCES proveedores(id)")
    except Exception: pass
    try:
        db.execute("ALTER TABLE proceso_operaciones ADD COLUMN precio_tercerizado REAL DEFAULT 0")
    except Exception: pass
    try:
        db.execute("ALTER TABLE tickets_reparacion ADD COLUMN horas_ajuste REAL DEFAULT 0")
    except Exception: pass

    # ── Migrate empleados: make apellido nullable ────────────────────────────────
    try:
        emp_cols_info = db.execute("PRAGMA table_info(empleados)").fetchall()
        for col in emp_cols_info:
            if col[1] == 'apellido' and col[3] == 1:  # notnull flag
                SCHEMA_EMP_NEW = (
                    "CREATE TABLE IF NOT EXISTS empleados_new ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                    "legajo TEXT UNIQUE NOT NULL, nombre TEXT NOT NULL, apellido TEXT,"
                    "cargo TEXT, tipo TEXT DEFAULT 'Indirecto',"
                    "turno TEXT, activo INTEGER DEFAULT 1, obs TEXT,"
                    "creado TEXT DEFAULT (datetime('now','localtime')))"
                )
                db.execute(SCHEMA_EMP_NEW)
                db.execute("INSERT OR IGNORE INTO empleados_new SELECT id,legajo,nombre,apellido,cargo,tipo,turno,activo,obs,creado FROM empleados")
                db.execute("DROP TABLE empleados")
                db.execute("ALTER TABLE empleados_new RENAME TO empleados")
                break
    except Exception: pass

    # ── Migrate lotes: rename old Activo→Aprobado, Bloqueado→Rechazado ─────────
    try:
        db.execute("UPDATE lotes SET estado='Aprobado' WHERE estado='Activo'")
        db.execute("UPDATE lotes SET estado='Rechazado' WHERE estado='Bloqueado'")
    except Exception: pass

    # ── Tabla configuración del sistema ───────────────────────────────────────
    db.execute("""CREATE TABLE IF NOT EXISTS configuracion (
        clave TEXT PRIMARY KEY,
        valor TEXT,
        descripcion TEXT
    )""")
    _cfg_defaults = [
        ('empresa_nombre',      'Mecanizados Ituzaingo',    'Nombre del taller / empresa'),
        ('empresa_subtitulo',   'Taller de Mecanizados', 'Subtítulo o rubro'),
        ('empresa_direccion',   '',                   'Dirección'),
        ('empresa_telefono',    '',                   'Teléfono / WhatsApp'),
        ('empresa_email',       '',                   'Email'),
        ('pdf_color_hex',       '2C5F8A',             'Color principal PDF (hex sin #)'),
        ('pdf_mostrar_costos',  '0',                  'Mostrar costos en PDF (0/1)'),
        ('pdf_mostrar_precios', '0',                  'Mostrar precio de venta en PDF (0/1)'),
        ('pdf_nota_pie',        '',                   'Nota al pie del PDF de OT'),
    ]
    for _k, _v, _d in _cfg_defaults:
        db.execute("INSERT OR IGNORE INTO configuracion (clave,valor,descripcion) VALUES (?,?,?)",
                   (_k, _v, _d))


    # ── Migrate usuarios: add logistica to rol CHECK constraint ──────────────
    # ── Migrate usuarios: add logistica to rol CHECK constraint ──────────────
    try:
        usr_ddl = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='usuarios'").fetchone()
        if usr_ddl and 'logistica' not in usr_ddl[0]:
            db.execute("""CREATE TABLE IF NOT EXISTS usuarios_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL, password TEXT NOT NULL,
                nombre TEXT NOT NULL,
                rol TEXT NOT NULL CHECK(rol IN ('admin','operario','vendedor','almacen','logistica')),
                activo INTEGER DEFAULT 1,
                creado TEXT DEFAULT (datetime('now','localtime')))""")
            db.execute("INSERT OR IGNORE INTO usuarios_new SELECT id,username,password,nombre,rol,activo,creado FROM usuarios")
            db.execute("DROP TABLE usuarios")
            db.execute("ALTER TABLE usuarios_new RENAME TO usuarios")
    except Exception as e:
        print(f"[WARN] Migración usuarios falló: {e}")

    # ── Versiones de proceso de productos ───────────────────────────────────
    db.execute("""CREATE TABLE IF NOT EXISTS producto_versiones (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        producto_id INTEGER NOT NULL REFERENCES productos(id) ON DELETE CASCADE,
        version_num INTEGER NOT NULL DEFAULT 1,
        motivo TEXT,
        snapshot TEXT NOT NULL,
        creado_por TEXT,
        creado TEXT DEFAULT (datetime('now','localtime')))""")
    # Recalcular rendimiento de novedades existentes descontando tiempo_perdido
    try:
        novedades = db.execute(
            "SELECT n.id, n.cantidad_producida, n.tiempo_real_min, "
            "COALESCE(n.tiempo_perdido,0) tiempo_perdido, "
            "COALESCE(po.tiempo_ciclo_min, oo.tiempo_ciclo_min, 1) ciclo "
            "FROM novedades_produccion n "
            "JOIN orden_operaciones oo ON oo.id=n.orden_operacion_id "
            "LEFT JOIN proceso_operaciones po ON po.id=oo.proceso_op_id"
        ).fetchall()
        for nov in novedades:
            ciclo  = float(nov["ciclo"] or 1)
            qty    = float(nov["cantidad_producida"] or 0)
            t_real = float(nov["tiempo_real_min"] or 0)
            t_perd = float(nov["tiempo_perdido"] or 0)
            t_prod = max(t_real - t_perd, 0.1)
            if qty > 0 and t_prod > 0:
                rend = round((qty / t_prod) / (1 / ciclo) * 100, 1)
                desv = 1 if rend < 80 else 0
                db.execute(
                    "UPDATE novedades_produccion SET rendimiento_pct=?, desvio=? WHERE id=?",
                    (rend, desv, nov["id"])
                )
    except Exception as e:
        print(f"[init_db] Advertencia al recalcular rendimiento: {e}")

    db.commit()
    db.close()

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

# ── Auth ──────────────────────────────────────────────────────────────────────
@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        d = request.get_json(silent=True) or request.form
        user = query("SELECT * FROM usuarios WHERE username=? AND activo=1", (d.get("username",""),), one=True)
        if user and user["password"] == hash_pw(d.get("password","")):
            session.update({"user_id":user["id"],"username":user["username"],"nombre":user["nombre"],"rol":user["rol"]})
            if request.is_json: return jsonify({"ok":True,"rol":user["rol"],"nombre":user["nombre"]})
            return redirect("/")
        if request.is_json: return jsonify({"ok":False,"error":"Usuario o contraseña incorrectos"}), 401
    return render_template("login.html")

@app.route("/logout")
def logout(): session.clear(); return redirect("/login")

@app.route("/api/me")
def me():
    if "user_id" not in session: return jsonify({"auth":False}), 401
    
    # Load user permissions
    perms = {}
    try:
        rows = query("SELECT clave,valor FROM usuario_permisos WHERE usuario_id=?", (session["user_id"],))
        perms = {r["clave"]: r["valor"] for r in rows}
    except Exception:
        pass
    
    # Si no hay permisos explícitos y no es admin, usar permisos predeterminados del rol
    if not perms and session.get("rol") != "admin":
        rol = session.get("rol", "operario")
        if rol in DEFAULT_PERMISIONES:
            perms = DEFAULT_PERMISIONES[rol].copy()
    
    return jsonify({"auth":True,"nombre":session["nombre"],"rol":session["rol"],"perms":perms})
# ── Serve React SPA ──────────────────────────────────────────────────────────
import os as _os

@app.route("/app")
@app.route("/app/<path:path>")
def react_app(path=""):
    return send_from_directory("static/dist", "index.html")

@app.route("/")
@login_required()
def index():
    uid = session["user_id"]
    perm_rows = query("SELECT clave, valor FROM usuario_permisos WHERE usuario_id=?", (uid,))
    perms = {r["clave"]: r["valor"] for r in perm_rows}
    
    # Si no hay permisos explícitos y no es admin, usar permisos predeterminados del rol
    if not perms and session.get("rol") != "admin":
        rol = session.get("rol", "operario")
        if rol in DEFAULT_PERMISIONES:
            perms = DEFAULT_PERMISIONES[rol].copy()
    
    return render_template("app.html",
                          nombre=session["nombre"],
                          rol=session["rol"],
                          perms=perms)



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
        "mantto_proximo": [dict(r) for r in query(
            "SELECT m.nombre maquina,p.tarea,p.proxima_fecha,p.tipo FROM mantenimiento_plan p "
            "JOIN maquinas m ON m.id=p.maquina_id "
            "WHERE p.proxima_fecha<=date('now','+7 days') ORDER BY p.proxima_fecha LIMIT 5")],
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

# ── Dashboard económico / financiero ──────────────────────────────────────────
@app.route("/api/dashboard/economico")
@login_required()
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

# ── Dashboard (legacy) ───────────────────────────────────────────────────────
@app.route("/api/dashboard")
@login_required()
def dashboard():
    return jsonify({
        "ot_activas":      query("SELECT COUNT(*) c FROM ordenes WHERE estado IN ('Pendiente','En proceso')", one=True)["c"],
        "stock_critico":   query("SELECT COUNT(*) c FROM materiales WHERE stock<=stock_min AND stock_min>0", one=True)["c"],
        "maquinas_fuera":  query("SELECT COUNT(*) c FROM maquinas WHERE estado!='Operativa'", one=True)["c"],
        "tickets_abiertos":query("SELECT COUNT(*) c FROM tickets_reparacion WHERE estado='Abierto'", one=True)["c"],
        "facturacion":     query("SELECT COALESCE(SUM(total),0) s FROM presupuestos WHERE estado='Facturado' AND strftime('%Y-%m',creado)=strftime('%Y-%m','now')", one=True)["s"],
        "alertas_mat":     [dict(r) for r in query("SELECT codigo,descripcion,stock,stock_min,unidad FROM materiales WHERE stock<=stock_min AND stock_min>0 LIMIT 5")],
        "alertas_ot":      [dict(r) for r in query("SELECT numero,descripcion,fecha_entrega FROM ordenes WHERE estado IN ('Pendiente','En proceso') AND fecha_entrega<=date('now','+3 days') ORDER BY fecha_entrega LIMIT 4")],
        "alertas_tkt":     [dict(r) for r in query("SELECT m.nombre maquina,t.numero,t.descripcion,t.prioridad FROM tickets_reparacion t JOIN maquinas m ON m.id=t.maquina_id WHERE t.estado='Abierto' LIMIT 4")],
        "mantto_proximo":  [dict(r) for r in query("SELECT m.nombre maquina,p.tarea,p.proxima_fecha,p.tipo FROM mantenimiento_plan p JOIN maquinas m ON m.id=p.maquina_id WHERE p.proxima_fecha IS NOT NULL AND p.proxima_fecha<=date('now','+7 days') ORDER BY p.proxima_fecha LIMIT 5")],
        "ots_recientes":   [dict(r) for r in query("SELECT o.numero,c.razon cliente,pr.nombre producto,o.descripcion,o.estado,o.fecha_entrega FROM ordenes o LEFT JOIN clientes c ON c.id=o.cliente_id LEFT JOIN productos pr ON pr.id=o.producto_id ORDER BY o.id DESC LIMIT 6")],
    })

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

@app.route("/api/categorias_maquina/<int:cid>", methods=["PUT"])
@login_required(roles=["admin"])
def update_cat_maq(cid):
    d = request.json
    execute("UPDATE categorias_maquina SET nombre=?,descripcion=? WHERE id=?",
            (d["nombre"], d.get("descripcion"), cid))
    return jsonify({"ok": True})

@app.route("/api/categorias_maquina/<int:cid>", methods=["DELETE"])
@login_required(roles=["admin"])
def delete_cat_maq(cid):
    used = query("SELECT COUNT(*) c FROM proceso_operaciones WHERE categoria_maquina_id=?", (cid,), one=True)["c"]
    if used:
        return jsonify({"error": f"En uso por {used} operación(es)"}), 400
    execute("DELETE FROM categorias_maquina WHERE id=?", (cid,))
    return jsonify({"ok": True})

@app.route("/api/categorias_maquina", methods=["GET"])
@login_required()
def get_cat_maq(): return jsonify([dict(r) for r in query("SELECT * FROM categorias_maquina ORDER BY nombre")])

@app.route("/api/categorias_maquina", methods=["POST"])
@login_required(roles=["admin"])
def create_cat_maq():
    d = request.json
    if not d.get("nombre"): return jsonify({"error":"Nombre requerido"}), 400
    lid = execute("INSERT INTO categorias_maquina (nombre,descripcion) VALUES (?,?)", (d["nombre"],d.get("descripcion")))
    return jsonify({"ok":True,"id":lid}), 201

# ── Maquinas ──────────────────────────────────────────────────────────────────
def _codigo_sort_key(codigo):
    m = re.match(r"^([A-Za-z]*)(\d+)$", (codigo or "").strip())
    if m:
        return (m.group(1).upper(), int(m.group(2)))
    return ((codigo or "").upper(), 0)

@app.route("/api/maquinas", methods=["GET"])
@login_required()
def get_maquinas():
    rows = query("SELECT m.*,c.nombre categoria_nombre FROM maquinas m LEFT JOIN categorias_maquina c ON c.id=m.categoria_id")
    result = []
    for r in rows:
        d = dict(r)
        d["reemplazos"] = [dict(x) for x in query("SELECT m2.id,m2.codigo,m2.nombre FROM maquina_reemplazos mr JOIN maquinas m2 ON m2.id=mr.reemplazo_id WHERE mr.maquina_id=?", (r["id"],))]
        result.append(d)
    result.sort(key=lambda d: _codigo_sort_key(d.get("codigo")))
    return jsonify(result)

@app.route("/api/maquinas", methods=["POST"])
@login_required(roles=["admin","operario"])
def create_maquina():
    d = request.json
    if not d.get("codigo") or not d.get("nombre"): return jsonify({"error":"Código y nombre requeridos"}), 400
    if query("SELECT id FROM maquinas WHERE codigo=?", (d["codigo"],), one=True): return jsonify({"error":"Código ya existe"}), 409
    lid = execute("INSERT INTO maquinas (codigo,nombre,categoria_id,marca,modelo,numero_serie,anio,ubicacion,estado,horas_uso,obs) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (d["codigo"],d["nombre"],d.get("categoria_id"),d.get("marca"),d.get("modelo"),d.get("numero_serie"),d.get("anio"),d.get("ubicacion"),d.get("estado","Operativa"),d.get("horas_uso",0),d.get("obs")))
    for rid in (d.get("reemplazos") or []):
        try: execute("INSERT OR IGNORE INTO maquina_reemplazos (maquina_id,reemplazo_id) VALUES (?,?)", (lid, int(rid)))
        except: pass
    return jsonify({"ok":True,"id":lid}), 201

@app.route("/api/maquinas/<int:mid>", methods=["PUT"])
@login_required(roles=["admin","operario"])
def update_maquina(mid):
    d = request.json
    execute("UPDATE maquinas SET nombre=?,categoria_id=?,marca=?,modelo=?,numero_serie=?,anio=?,ubicacion=?,estado=?,horas_uso=?,obs=? WHERE id=?",
        (d["nombre"],d.get("categoria_id"),d.get("marca"),d.get("modelo"),d.get("numero_serie"),d.get("anio"),d.get("ubicacion"),d.get("estado","Operativa"),d.get("horas_uso",0),d.get("obs"),mid))
    execute("DELETE FROM maquina_reemplazos WHERE maquina_id=?", (mid,))
    for rid in (d.get("reemplazos") or []):
        try: execute("INSERT OR IGNORE INTO maquina_reemplazos (maquina_id,reemplazo_id) VALUES (?,?)", (mid, int(rid)))
        except: pass
    return jsonify({"ok":True})

# ── Mantenimiento ─────────────────────────────────────────────────────────────
@app.route("/api/mantenimiento", methods=["GET"])
@login_required()
def get_mantenimiento():
    return jsonify([dict(r) for r in query(
        "SELECT p.*,m.nombre maquina_nombre,m.codigo maquina_codigo FROM mantenimiento_plan p JOIN maquinas m ON m.id=p.maquina_id ORDER BY p.proxima_fecha,m.nombre")])

@app.route("/api/mantenimiento", methods=["POST"])
@login_required(roles=["admin","operario"])
def create_mantenimiento():
    d = request.json
    if not d.get("maquina_id") or not d.get("tarea"): return jsonify({"error":"Máquina y tarea requeridas"}), 400
    lid = execute("INSERT INTO mantenimiento_plan (maquina_id,tarea,tipo,frecuencia_tipo,frecuencia_valor,ultima_fecha,proxima_fecha,responsable,obs) VALUES (?,?,?,?,?,?,?,?,?)",
        (d["maquina_id"],d["tarea"],d.get("tipo","Frecuencia fija"),d.get("frecuencia_tipo"),d.get("frecuencia_valor"),d.get("ultima_fecha"),d.get("proxima_fecha"),d.get("responsable"),d.get("obs")))
    return jsonify({"ok":True,"id":lid}), 201

@app.route("/api/mantenimiento/<int:pid>", methods=["PUT"])
@login_required(roles=["admin","operario"])
def update_mantenimiento(pid):
    d = request.json
    execute("UPDATE mantenimiento_plan SET tarea=?,tipo=?,frecuencia_tipo=?,frecuencia_valor=?,ultima_fecha=?,proxima_fecha=?,responsable=?,obs=? WHERE id=?",
        (d["tarea"],d.get("tipo"),d.get("frecuencia_tipo"),d.get("frecuencia_valor"),d.get("ultima_fecha"),d.get("proxima_fecha"),d.get("responsable"),d.get("obs"),pid))
    return jsonify({"ok":True})

@app.route("/api/mantenimiento/<int:pid>", methods=["DELETE"])
@login_required(roles=["admin"])
def delete_mantenimiento(pid):
    execute("DELETE FROM mantenimiento_plan WHERE id=?", (pid,))
    return jsonify({"ok":True})

# ── Tickets ───────────────────────────────────────────────────────────────────
@app.route("/api/tickets", methods=["GET"])
@login_required()
def get_tickets():
    estado = request.args.get("estado")
    sql = "SELECT t.*,m.nombre maquina_nombre,m.codigo maquina_codigo FROM tickets_reparacion t JOIN maquinas m ON m.id=t.maquina_id"
    rows = query(sql+" WHERE t.estado=? ORDER BY t.id DESC",(estado,)) if estado else query(sql+" ORDER BY t.id DESC")
    return jsonify([dict(r) for r in rows])

@app.route("/api/tickets", methods=["POST"])
@login_required(roles=["admin","operario"])
def create_ticket():
    d = request.json
    if not d.get("maquina_id") or not d.get("descripcion"): return jsonify({"error":"Máquina y descripción requeridas"}), 400
    last = query("SELECT numero FROM tickets_reparacion ORDER BY id DESC LIMIT 1", one=True)
    try: n = int(last["numero"].split("-")[1])+1 if last else 1
    except: n = 1
    numero = f"TKT-{n:03d}"
    lid = execute("INSERT INTO tickets_reparacion (numero,maquina_id,tipo,descripcion,prioridad,estado,responsable,horas_paro,creado_por) VALUES (?,?,?,?,?,?,?,?,?)",
        (numero,d["maquina_id"],d.get("tipo","Correctivo"),d["descripcion"],d.get("prioridad","Normal"),"Abierto",d.get("responsable"),0,session["user_id"]))
    execute("UPDATE maquinas SET estado='En mantenimiento' WHERE id=? AND estado='Operativa'", (d["maquina_id"],))
    return jsonify({"ok":True,"id":lid,"numero":numero}), 201

def calc_horas_paro_habiles(fecha_apertura_str, fecha_cierre_dt):
    """Calcula horas de paro entre apertura y cierre, excluyendo sábados y domingos.
    fecha_cierre_dt debe ser un datetime (momento exacto del cierre), no una date."""
    try:
        apertura = datetime.fromisoformat(fecha_apertura_str)
    except Exception:
        return 0.0
    # Si por error llega un date (sin hora), se usa fin de día como fallback,
    # pero el caller siempre debe pasar datetime.now() para reflejar la hora real.
    cierre = datetime.combine(fecha_cierre_dt, datetime.max.time()) if not hasattr(fecha_cierre_dt, 'hour') else fecha_cierre_dt
    if cierre <= apertura:
        return 0.0
    total_segundos = 0.0
    current = apertura
    while current < cierre:
        next_step = min(current.replace(hour=23,minute=59,second=59), cierre)
        # 0=lunes ... 5=sábado, 6=domingo
        if current.weekday() < 5:  # día hábil
            total_segundos += (next_step - current).total_seconds()
        # avanzar al inicio del próximo día
        current = (current.replace(hour=0, minute=0, second=0) + timedelta(days=1))
    return round(total_segundos / 3600, 2)

@app.route("/api/tickets/<int:tid>", methods=["PUT"])
@login_required(roles=["admin","operario"])
def update_ticket(tid):
    d = request.json
    fecha_cierre = None
    horas_paro_calc = None
    horas_ajuste = abs(float(d.get("horas_ajuste") or 0))
    if d.get("estado") == "Cerrado":
        momento_cierre = datetime.now()
        fecha_cierre = momento_cierre.isoformat(sep=' ', timespec='seconds')
        t_apertura = query("SELECT fecha_apertura,horas_paro FROM tickets_reparacion WHERE id=?", (tid,), one=True)
        if t_apertura and t_apertura["fecha_apertura"]:
            horas_paro_calc = calc_horas_paro_habiles(t_apertura["fecha_apertura"], momento_cierre) + horas_ajuste
        else:
            horas_paro_calc = max(0.0, horas_ajuste)
    else:
        fecha_cierre = d.get("fecha_cierre")
        # Mantener horas_paro existente si no se cierra
        t_existing = query("SELECT horas_paro FROM tickets_reparacion WHERE id=?", (tid,), one=True)
        horas_paro_calc = t_existing["horas_paro"] if t_existing else 0.0
    execute("UPDATE tickets_reparacion SET descripcion=?,tipo=?,prioridad=?,estado=?,responsable=?,fecha_cierre=?,horas_paro=?,horas_ajuste=?,costo=?,solucion=? WHERE id=?",
        (d["descripcion"],d.get("tipo","Correctivo"),d.get("prioridad","Normal"),d.get("estado","Abierto"),d.get("responsable"),fecha_cierre,horas_paro_calc,horas_ajuste,d.get("costo",0),d.get("solucion"),tid))
    if d.get("estado") == "Cerrado":
        t = query("SELECT maquina_id FROM tickets_reparacion WHERE id=?", (tid,), one=True)
        if t:
            open_count = query("SELECT COUNT(*) c FROM tickets_reparacion WHERE maquina_id=? AND estado='Abierto' AND id!=?", (t["maquina_id"],tid), one=True)["c"]
            if open_count == 0: execute("UPDATE maquinas SET estado='Operativa' WHERE id=?", (t["maquina_id"],))
    return jsonify({"ok":True})

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
                    COALESCE((SELECT SUM(l.cantidad_activa) FROM lotes l
                              WHERE l.material_id=m.id), 0) AS stock_lotes
             FROM materiales m
             LEFT JOIN proveedores p ON p.id=m.proveedor_id
             LEFT JOIN categorias_producto cp ON cp.id=m.categoria_producto_id"""
    if categoria:
        rows = query(sql+" WHERE m.categoria=? ORDER BY m.codigo", (categoria,))
    else:
        rows = query(sql+" ORDER BY m.codigo")
    out = []
    for r in rows:
        d = dict(r)
        # Para materiales con categoria 'Material' o 'Producto terminado'
        # (ambos manejan lotes), se reemplaza el stock por el stock aprobado
        # de lotes. Insumos sin lote conservan el stock original.
        if d.get("categoria") in ("Material", "Producto terminado"):
            d["stock"] = d.pop("stock_lotes")
        else:
            d.pop("stock_lotes", None)
        out.append(d)
    return jsonify(out)

@app.route("/api/materiales/productos_terminados", methods=["GET"])
@login_required()
def get_productos_terminados_stock():
    rows = query("""SELECT m.*,pr.nombre producto_nombre,c.razon cliente_nombre,cp.nombre cat_prod_nombre
        FROM materiales m
        LEFT JOIN productos pr ON pr.codigo=m.codigo
        LEFT JOIN categorias_producto cp ON cp.id=m.categoria_producto_id
        LEFT JOIN producto_clientes pc ON pc.producto_id=pr.id
        LEFT JOIN clientes c ON c.id=pc.cliente_id
        WHERE m.categoria='Producto terminado'
        ORDER BY c.razon,m.codigo""")
    return jsonify([dict(r) for r in rows])

@app.route("/api/materiales", methods=["POST"])
@login_required(roles=["admin","almacen"])
def create_material():
    d = request.json
    if not d.get("codigo") or not d.get("descripcion"): return jsonify({"error":"Código y descripción requeridos"}), 400
    if query("SELECT id FROM materiales WHERE codigo=?", (d["codigo"],), one=True): return jsonify({"error":"Código ya existe"}), 409
    stock_inicial = float(d.get("stock", 0) or 0)
    lid = execute("INSERT INTO materiales (codigo,descripcion,categoria,categoria_producto_id,unidad,stock,stock_min,stock_max,precio_unit,proveedor_id,obs) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (d["codigo"],d["descripcion"],d.get("categoria","Material"),d.get("categoria_producto_id"),d.get("unidad","kg"),stock_inicial,d.get("stock_min",0),d.get("stock_max",0),d.get("precio_unit",0),d.get("proveedor_id"),d.get("obs")))
    if stock_inicial > 0 and d.get("categoria","Material") == "Material":
        # Auto-create lote for initial stock
        from datetime import datetime
        year = datetime.now().year
        last_l = query("SELECT numero FROM lotes WHERE numero LIKE ? ORDER BY id DESC LIMIT 1",
            (f"LOTE-{year}-%",), one=True)
        try: ln = int(last_l["numero"].split("-")[2]) + 1 if last_l else 1
        except: ln = 1
        lote_num = f"LOTE-{year}-{ln:04d}"
        lote_id = execute("""INSERT INTO lotes
            (numero,material_id,cantidad_original,cantidad_disponible,
             proveedor_id,referencia_proveedor,estado,obs,creado_por)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (lote_num, lid, stock_inicial, stock_inicial,
             d.get("proveedor_id"), "Stock inicial al dar de alta",
             "Ingresado", "Creado automáticamente al dar de alta el material",
             session["user_id"]))
        execute("INSERT INTO movimientos (material_id,lote_id,tipo,cantidad,referencia,usuario_id) VALUES (?,?,?,?,?,?)",
            (lid, lote_id, "entrada", stock_inicial, f"Stock inicial — {lote_num}", session["user_id"]))
    elif stock_inicial > 0:
        execute("INSERT INTO movimientos (material_id,tipo,cantidad,referencia,usuario_id) VALUES (?,?,?,?,?)",
            (lid, "entrada", stock_inicial, "Stock inicial al dar de alta", session["user_id"]))
    return jsonify({"ok":True,"id":lid}), 201

@app.route("/api/materiales/<int:mid>", methods=["PUT"])
@login_required(roles=["admin","almacen","logistica"])
def update_material(mid):
    d = request.json
    rol_sesion = session.get("rol")
    if "precio_unit" in d and rol_sesion == "admin":
        execute("UPDATE materiales SET descripcion=?,categoria=?,categoria_producto_id=?,unidad=?,stock_min=?,stock_max=?,precio_unit=?,proveedor_id=?,obs=?,actualizado=datetime('now','localtime') WHERE id=?",
            (d["descripcion"],d.get("categoria"),d.get("categoria_producto_id"),d.get("unidad"),d.get("stock_min",0),d.get("stock_max",0),d["precio_unit"],d.get("proveedor_id"),d.get("obs"),mid))
    else:
        execute("UPDATE materiales SET descripcion=?,categoria=?,categoria_producto_id=?,unidad=?,stock_min=?,stock_max=?,proveedor_id=?,obs=?,actualizado=datetime('now','localtime') WHERE id=?",
            (d["descripcion"],d.get("categoria"),d.get("categoria_producto_id"),d.get("unidad"),d.get("stock_min",0),d.get("stock_max",0),d.get("proveedor_id"),d.get("obs"),mid))
    # Propagar la nueva descripción a las copias guardadas en compras
    # (solicitudes_compra y ordenes_compra_items no hacen JOIN en vivo con materiales,
    #  guardan una copia propia del texto al momento de crearse)
    if d.get("descripcion"):
        execute("UPDATE solicitudes_compra SET descripcion=? WHERE material_id=?", (d["descripcion"], mid))
        execute("UPDATE ordenes_compra_items SET descripcion=? WHERE material_id=?", (d["descripcion"], mid))
    return jsonify({"ok":True})

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
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY mv.id DESC LIMIT 500"
    rows = query(sql, params)
    return jsonify([dict(r) for r in rows])

@app.route("/api/materiales/<int:mid>/movimiento", methods=["POST"])
@login_required(roles=["admin","almacen"])
def movimiento(mid):
    d = request.json
    tipo = d.get("tipo")
    qty  = float(d.get("cantidad", 0))
    if tipo == "salida":
        mat = query("SELECT stock FROM materiales WHERE id=?", (mid,), one=True)
        if not mat or mat["stock"] < qty: return jsonify({"error":"Stock insuficiente"}), 400
        execute("UPDATE materiales SET stock=stock-?,actualizado=datetime('now','localtime') WHERE id=?", (qty, mid))
        auto_generar_sc_bajo_stock(mid, "movimiento de salida manual")
    elif tipo == "entrada":
        execute("UPDATE materiales SET stock=stock+?,actualizado=datetime('now','localtime') WHERE id=?", (qty, mid))
    else:
        execute("UPDATE materiales SET stock=?,actualizado=datetime('now','localtime') WHERE id=?", (qty, mid))
    execute("INSERT INTO movimientos (material_id,tipo,cantidad,referencia,usuario_id) VALUES (?,?,?,?,?)",
        (mid, tipo, qty, d.get("referencia"), session["user_id"]))
    return jsonify({"ok":True})

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
@login_required(roles=["admin","almacen"])
def create_proveedor():
    d = request.json
    if not d.get("razon"): return jsonify({"error":"Razón social requerida"}), 400
    lid = execute("INSERT INTO proveedores (razon,cuit,contacto,telefono,email,materiales,plazo_dias,calificacion,estado,obs) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (d["razon"],d.get("cuit"),d.get("contacto"),d.get("telefono"),d.get("email"),d.get("materiales"),d.get("plazo_dias",3),d.get("calificacion",5),d.get("estado","Activo"),d.get("obs")))
    return jsonify({"ok":True,"id":lid}), 201

@app.route("/api/proveedores/<int:pid>", methods=["PUT"])
@login_required(roles=["admin","almacen"])
def update_proveedor(pid):
    d = request.json
    execute("UPDATE proveedores SET razon=?,cuit=?,contacto=?,telefono=?,email=?,materiales=?,plazo_dias=?,calificacion=?,estado=?,obs=? WHERE id=?",
        (d["razon"],d.get("cuit"),d.get("contacto"),d.get("telefono"),d.get("email"),d.get("materiales"),d.get("plazo_dias",3),d.get("calificacion",5),d.get("estado","Activo"),d.get("obs"),pid))
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

@app.route("/api/proveedores/<int:pid>/materiales/<int:mid>", methods=["DELETE"])
@login_required(roles=["admin","almacen"])
def unlink_mat(pid, mid):
    execute("DELETE FROM proveedor_materiales WHERE proveedor_id=? AND material_id=?", (pid, mid))
    return jsonify({"ok":True})

# ── Productos / Procesos ──────────────────────────────────────────────────────
@app.route("/api/productos", methods=["GET"])
@login_required()
def get_productos():
    cliente_id = request.args.get("cliente_id")
    if cliente_id:
        rows = query("""SELECT p.*,c.nombre categoria_nombre,cl.razon cliente_nombre FROM productos p
            LEFT JOIN categorias_producto c ON c.id=p.categoria_id
            LEFT JOIN clientes cl ON cl.id=p.cliente_id
            WHERE p.cliente_id=? AND p.activo=1 ORDER BY p.codigo""", (cliente_id,))
    else:
        rows = query("""SELECT p.*,c.nombre categoria_nombre,cl.razon cliente_nombre FROM productos p
            LEFT JOIN categorias_producto c ON c.id=p.categoria_id
            LEFT JOIN clientes cl ON cl.id=p.cliente_id
            WHERE p.activo=1 ORDER BY p.codigo""")
    result = []
    for r in rows:
        d = dict(r)
        # Calculate costo_mat dynamically from current material prices
        d["costo_mat"] = round(calcular_costo_producto(d["id"], 1.0), 2)
        d["tiempo_ciclo_total_min"] = round(calcular_tiempo_ciclo_total(d["id"]), 2)
        result.append(d)
    return jsonify(result)

@app.route("/api/productos/<int:pid>", methods=["GET"])
@login_required()
def get_producto(pid):
    prod = query("SELECT p.*,COALESCE(p.peso_kg,0) peso_kg,c.nombre categoria_nombre FROM productos p LEFT JOIN categorias_producto c ON c.id=p.categoria_id WHERE p.id=?", (pid,), one=True)
    if not prod: return jsonify({"error":"No encontrado"}), 404
    d = dict(prod)
    d["tiempo_ciclo_total_min"] = round(calcular_tiempo_ciclo_total(pid), 2)
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

@app.route("/api/productos", methods=["POST"])
@login_required(roles=["admin","operario"])
def create_producto():
    d = request.json
    if not d.get("codigo") or not d.get("nombre"): return jsonify({"error":"Código y nombre requeridos"}), 400
    if query("SELECT id FROM productos WHERE codigo=?", (d["codigo"],), one=True): return jsonify({"error":"Código ya existe"}), 409
    lid = execute("INSERT INTO productos (codigo,nombre,descripcion,categoria_id,unidad,tiempo_total_hs,costo_mat,costo_mo,precio_venta,peso_kg,cliente_id,obs,capacidad_cajon) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (d["codigo"],d["nombre"],d.get("descripcion"),d.get("categoria_id"),d.get("unidad","unid"),d.get("tiempo_total_hs",0),d.get("costo_mat",0),d.get("costo_mo",0),d.get("precio_venta",0),d.get("peso_kg",0),d.get("cliente_id") or None,d.get("obs"),d.get("capacidad_cajon") or None))
    # Auto-create matching material entry for stock tracking of finished product
    get_or_create_pt_material({"id": lid, "codigo": d["codigo"], "nombre": d["nombre"], "unidad": d.get("unidad","unid")})
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
    if query("SELECT id FROM productos WHERE codigo=?", (nuevo_codigo,), one=True):
        return jsonify({"error": f"El código '{nuevo_codigo}' ya existe"}), 409

    # Fetch original
    orig = query("SELECT * FROM productos WHERE id=?", (pid,), one=True)
    if not orig:
        return jsonify({"error": "Producto original no encontrado"}), 404

    orig_ops = query(
        "SELECT * FROM proceso_operaciones WHERE producto_id=? ORDER BY CAST(orden AS INTEGER), orden", (pid,))

    # Create new product
    nuevo_nombre_final = nuevo_nombre or (orig["nombre"] + " (copia)")
    new_pid = execute(
        """INSERT INTO productos
           (codigo,nombre,descripcion,categoria_id,unidad,tiempo_total_hs,
            costo_mat,costo_mo,precio_venta,activo,obs)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (nuevo_codigo, nuevo_nombre_final, orig["descripcion"],
         orig["categoria_id"], orig["unidad"], orig["tiempo_total_hs"],
         orig["costo_mat"], orig["costo_mo"], orig["precio_venta"],
         1, orig["obs"]))

    # Auto-create matching material for PT stock tracking
    get_or_create_pt_material({"id": new_pid, "codigo": nuevo_codigo, "nombre": nuevo_nombre_final, "unidad": orig["unidad"]})

    # Copy operations and their materials
    ops_copiadas = 0
    for op in orig_ops:
        new_opid = execute(
            """INSERT INTO proceso_operaciones
               (producto_id,orden,nombre,descripcion,categoria_maquina_id,maquina_id,
                tiempo_setup_min,tiempo_ciclo_min,es_tercerizada,proveedor_id,
                precio_tercerizado,tiempo_minimo_dias,volumen_agrupado,valor_recalculado,obs)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (new_pid, op["orden"], op["nombre"], op["descripcion"],
             op["categoria_maquina_id"], op["maquina_id"],
             op["tiempo_setup_min"], op["tiempo_ciclo_min"],
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
                "INSERT INTO operacion_materiales (operacion_id,material_id,cantidad,unidad) VALUES (?,?,?,?)",
                (new_opid, m["material_id"], m["cantidad"], m["unidad"]))
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
    if "nombre" not in d:
        fields, vals = [], []
        for col in ["precio_venta","peso_kg","cliente_id","activo","obs","capacidad_cajon"]:
            if col in d:
                fields.append(f"{col}=?")
                vals.append(d[col])
        if fields:
            execute(f"UPDATE productos SET {', '.join(fields)} WHERE id=?", vals + [pid])
        return jsonify({"ok": True})
    # Validar código si se está modificando (debe seguir siendo único)
    if d.get("codigo"):
        dup = query("SELECT id FROM productos WHERE codigo=? AND id!=?", (d["codigo"], pid), one=True)
        if dup:
            return jsonify({"error": f"El código '{d['codigo']}' ya está en uso por otro producto"}), 409
    prod_actual = query("SELECT codigo FROM productos WHERE id=?", (pid,), one=True)
    if not prod_actual:
        return jsonify({"error": "Producto no encontrado"}), 404
    nuevo_codigo = d.get("codigo") or prod_actual["codigo"]
    execute("UPDATE productos SET codigo=?,nombre=?,descripcion=?,categoria_id=?,unidad=?,tiempo_total_hs=?,costo_mat=?,costo_mo=?,precio_venta=?,peso_kg=?,cliente_id=?,obs=?,activo=?,capacidad_cajon=? WHERE id=?",
        (nuevo_codigo,d["nombre"],d.get("descripcion"),d.get("categoria_id"),d.get("unidad","unid"),d.get("tiempo_total_hs",0),d.get("costo_mat",0),d.get("costo_mo",0),d.get("precio_venta",0),d.get("peso_kg",0),d.get("cliente_id") or None,d.get("obs"),1 if d.get("activo",True) else 0,d.get("capacidad_cajon") or None,pid))
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
    vol_agrup = 1 if d.get("volumen_agrupado") else 0
    lid = execute("""INSERT INTO proceso_operaciones
        (producto_id,orden,nombre,descripcion,categoria_maquina_id,maquina_id,
         tiempo_setup_min,tiempo_ciclo_min,es_tercerizada,proveedor_id,
         precio_tercerizado,tiempo_minimo_dias,obs,volumen_agrupado,valor_recalculado)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (d["producto_id"],d.get("orden",1),d["nombre"],d.get("descripcion"),
         d.get("categoria_maquina_id") if not es_terc else None,
         d.get("maquina_id") if not es_terc else None,
         d.get("tiempo_setup_min",0) if not es_terc else 0,
         d.get("tiempo_ciclo_min",0) if not es_terc else 0,
         es_terc,
         d.get("proveedor_id") if es_terc else None,
         d.get("precio_tercerizado",0) if es_terc else 0,
         d.get("tiempo_minimo_dias",0),
         d.get("obs"),
         vol_agrup,
         d.get("valor_recalculado",0) if vol_agrup else 0))
    for mat in (d.get("materiales") or []):
        if mat.get("material_id") and mat.get("cantidad"):
            execute("INSERT INTO operacion_materiales (operacion_id,material_id,cantidad,unidad) VALUES (?,?,?,?)", (lid,mat["material_id"],mat["cantidad"],mat.get("unidad","")))
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
    vol_agrup = 1 if d.get("volumen_agrupado") else 0
    execute("""UPDATE proceso_operaciones SET orden=?,nombre=?,descripcion=?,
        categoria_maquina_id=?,maquina_id=?,tiempo_setup_min=?,tiempo_ciclo_min=?,
        es_tercerizada=?,proveedor_id=?,precio_tercerizado=?,tiempo_minimo_dias=?,obs=?,
        volumen_agrupado=?,valor_recalculado=?
        WHERE id=?""",
        (nuevo_orden, d["nombre"], d.get("descripcion"), d.get("categoria_maquina_id"),
         d.get("maquina_id"), d.get("tiempo_setup_min",0), d.get("tiempo_ciclo_min",0),
         es_terc, d.get("proveedor_id") if es_terc else None,
         d.get("precio_tercerizado",0) if es_terc else 0,
         d.get("tiempo_minimo_dias",0), d.get("obs"),
         vol_agrup, d.get("valor_recalculado",0) if vol_agrup else 0, oid))
    # Update materials if provided
    if "materiales" in d:
        execute("DELETE FROM operacion_materiales WHERE operacion_id=?", (oid,))
        for mat in (d["materiales"] or []):
            if mat.get("material_id") and mat.get("cantidad"):
                tipo_m = mat.get("tipo","material")
                execute("INSERT INTO operacion_materiales (operacion_id,material_id,producto_id,cantidad,unidad,tipo) VALUES (?,?,?,?,?,?)",
                    (oid, mat.get("material_id") or None, mat.get("producto_id") or None,
                     mat["cantidad"], mat.get("unidad",""), tipo_m))
    # Recalculate total time
    _recalcular_tiempo_total_producto(prod_id)
    return jsonify({"ok":True})

@app.route("/api/operaciones/<int:oid>", methods=["DELETE"])
@login_required(roles=["admin","operario"])
def delete_operacion(oid):
    op = query("SELECT producto_id,nombre FROM proceso_operaciones WHERE id=?", (oid,), one=True)
    if op:
        guardar_version_producto(op["producto_id"], motivo="Operación eliminada: "+(op["nombre"] or ""), creado_por=session.get("username","sistema"))
    execute("DELETE FROM proceso_operaciones WHERE id=?", (oid,))
    if op:
        _recalcular_tiempo_total_producto(op["producto_id"])
    return jsonify({"ok":True})

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

# ── Ordenes ───────────────────────────────────────────────────────────────────
@app.route("/api/ordenes", methods=["GET"])
@login_required()
def get_ordenes():
    estado = request.args.get("estado")
    sql = """SELECT o.*,c.razon cliente_nombre,p.nombre producto_nombre,p.codigo producto_codigo,
        (SELECT oo.qty_producida FROM orden_operaciones oo
         WHERE oo.orden_id=o.id ORDER BY CAST(oo.orden AS INTEGER) DESC, oo.orden DESC LIMIT 1) total_realizado,
        (SELECT oci.orden_cliente_id FROM ordenes_cliente_items oci WHERE oci.ot_id=o.id LIMIT 1) oc_id,
        (SELECT oc.numero FROM ordenes_cliente_items oci JOIN ordenes_cliente oc ON oc.id=oci.orden_cliente_id
         WHERE oci.ot_id=o.id LIMIT 1) oc_numero
        FROM ordenes o LEFT JOIN clientes c ON c.id=o.cliente_id LEFT JOIN productos p ON p.id=o.producto_id"""
    rows = query(sql+" WHERE o.estado=? ORDER BY o.id DESC",(estado,)) if estado else query(sql+" ORDER BY o.id DESC")
    return jsonify([dict(r) for r in rows])

@app.route("/api/ordenes", methods=["POST"])
@login_required(roles=["admin","operario","vendedor"])
def create_orden():
    d = request.json
    if not d.get("producto_id"): return jsonify({"error":"Producto requerido"}), 400
    prod = query("SELECT codigo,nombre FROM productos WHERE id=?", (d["producto_id"],), one=True)
    if not prod: return jsonify({"error":"Producto no encontrado"}), 404
    descripcion = d.get("descripcion") or f"{prod['codigo']} — {prod['nombre']}"
    last = query("SELECT numero FROM ordenes ORDER BY id DESC LIMIT 1", one=True)
    try: n = int(last["numero"].split("-")[1])+1 if last else 1
    except: n = 1
    numero = f"OT-{n:03d}"
    lid = execute("INSERT INTO ordenes (numero,cliente_id,producto_id,descripcion,detalle,cantidad,prioridad,estado,fecha_inicio,fecha_entrega,costo_mat,costo_mo,precio_venta,obs) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (numero,d.get("cliente_id"),d["producto_id"],descripcion,d.get("detalle"),d.get("cantidad",1),d.get("prioridad","Normal"),d.get("estado","Pendiente"),d.get("fecha_inicio"),d.get("fecha_entrega"),d.get("costo_mat",0),d.get("costo_mo",0),0,d.get("obs")))
    return jsonify({"ok":True,"id":lid,"numero":numero}), 201

def _generar_sc_tercerizado(ot_id, ot_numero):
    """Genera solicitudes de compra para operaciones tercerizadas de una OT."""
    ops = query("""SELECT oo.*,p.razon proveedor_nombre
        FROM orden_operaciones oo
        LEFT JOIN proveedores p ON p.id=oo.proveedor_id
        WHERE oo.orden_id=? AND oo.es_tercerizada=1""", (ot_id,))
    for op in ops:
        last = query("SELECT numero FROM solicitudes_compra ORDER BY id DESC LIMIT 1", one=True)
        try: n = int(last["numero"].split("-")[1])+1 if last else 1
        except: n = 1
        numero_sc = f"SC-{n:04d}"
        ot_row = query("SELECT cantidad FROM ordenes WHERE id=?", (ot_id,), one=True)
        qty = float(ot_row["cantidad"] or 1) if ot_row else 1
        desc = f"Operación tercerizada: {op['nombre']} — {op['proveedor_nombre'] or 'Proveedor no asignado'}"
        execute("""INSERT INTO solicitudes_compra
            (numero,tipo,descripcion,cantidad,unidad,urgencia,estado,
             ot_origen_id,obs)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (numero_sc, "Productiva", desc, qty, "servicio",
             "Normal", "Pendiente", ot_id,
             f"Generada automáticamente al crear {ot_numero}"))

@app.route("/api/ordenes/<int:oid>", methods=["GET"])
@login_required()
def get_orden(oid):
    r = query("""SELECT o.*,c.razon cliente_nombre,p.nombre producto_nombre,p.codigo producto_codigo
        FROM ordenes o
        LEFT JOIN clientes c ON c.id=o.cliente_id
        LEFT JOIN productos p ON p.id=o.producto_id
        WHERE o.id=?""", (oid,), one=True)
    if not r: return jsonify({"error":"OT no encontrada"}), 404
    return jsonify(dict(r))

def generar_pt_faltante_si_corresponde(oid):
    """Red de seguridad: si la OT se marca 'Completada' pero el flujo de
    Novedades no generó (o generó parcialmente) el stock de Producto
    Terminado correspondiente, completa la diferencia acá.

    Es idempotente: calcula cuánto PT ya se generó (lote cuyo número
    coincide con el número de la OT) y solo agrega lo que falte hasta
    llegar a la cantidad solicitada en la OT. Si las Novedades ya
    generaron todo, no hace nada.
    """
    orden = query("SELECT * FROM ordenes WHERE id=?", (oid,), one=True)
    if not orden or not orden["producto_id"]:
        return
    prod = query("SELECT * FROM productos WHERE id=?", (orden["producto_id"],), one=True)
    if not prod:
        return

    # ── Cantidad real a generar como PT: es lo que EFECTIVAMENTE hizo la
    # ÚLTIMA operación de la ruta, sin techo. Si la OT se completa ANTES de
    # llegar al 100% (ej. se cancela/cierra con menos piezas de las
    # pedidas), el PT que corresponde generar es esa cantidad menor. Si en
    # cambio la última operación PRODUJO DE MÁS respecto de lo pedido (ej.
    # se pidieron 100 y la operación anterior había llegado a 108, entonces
    # esta última puede llegar hasta 108), el lote de PT también refleja
    # esas 108 — no se recorta al pedido original. Cada operación puede
    # cargar cualquier cantidad de piezas terminadas, sin tope respecto de
    # lo que haya producido la operación anterior.
    ultima_op = query("""SELECT qty_producida FROM orden_operaciones
        WHERE orden_id=? ORDER BY CAST(orden AS INTEGER) DESC, orden DESC LIMIT 1""", (oid,), one=True)
    target_qty = float(ultima_op["qty_producida"] or 0) if ultima_op else 0.0
    if target_qty <= 0:
        return

    # ── Excedente sobre lo pedido: va a "Producto sin lote", no al lote de la OT ──
    # Si se produjo más de lo que la OT pedía (orden["cantidad"]), esa diferencia
    # no se suma al lote de PT de esta OT (que queda pendiente de Calidad como
    # siempre) sino que se acredita directo al stock de "Producto sin lote" del
    # producto, disponible para prellenar la próxima OT del mismo producto.
    cantidad_pedida = float(orden["cantidad"] or 0)
    if cantidad_pedida > 0:
        lote_target = min(target_qty, cantidad_pedida)
        sinlote_target = max(0.0, target_qty - cantidad_pedida)
    else:
        lote_target = target_qty
        sinlote_target = 0.0

    ya_sinlote = float(orden["sinlote_generado"] or 0)
    falta_sinlote = sinlote_target - ya_sinlote
    if falta_sinlote > 0:
        mat_sinlote = get_or_create_sinlote_material(prod)
        execute("""UPDATE materiales SET stock=stock+?, actualizado=datetime('now','localtime')
            WHERE id=?""", (falta_sinlote, mat_sinlote["id"]))
        execute("UPDATE ordenes SET sinlote_generado=COALESCE(sinlote_generado,0)+? WHERE id=?",
            (falta_sinlote, oid))
        execute("""INSERT INTO movimientos (material_id,lote_id,tipo,cantidad,referencia,usuario_id)
            VALUES (?,NULL,'ingreso',?,?,?)""",
            (mat_sinlote["id"], falta_sinlote,
             f"Excedente OT {orden['numero']} — producido por encima de lo pedido ({cantidad_pedida:g}), sin lote",
             session.get("user_id")))

    mat_pt = get_or_create_pt_material(prod)
    ot_lote_num = orden["numero"]

    lotes_usados = query("""SELECT l.numero FROM orden_lotes ol
        JOIN lotes l ON l.id=ol.lote_id WHERE ol.orden_id=?""", (oid,))
    lotes_ref = ", ".join(l["numero"] for l in lotes_usados) if lotes_usados else "—"

    capacidad_cajon = 0
    try:
        capacidad_cajon = int(prod["capacidad_cajon"]) if prod["capacidad_cajon"] else 0
    except Exception:
        capacidad_cajon = 0

    # ── Sin capacidad de cajón configurada: comportamiento legado, un único
    # lote de PT por OT (todo junto, pendiente de Calidad). ────────────────
    if capacidad_cajon <= 0:
        lote_pt_row = query("SELECT id, cantidad_original FROM lotes WHERE numero=? AND material_id=?",
            (ot_lote_num, mat_pt["id"]), one=True)
        ya_generado = float(lote_pt_row["cantidad_original"]) if lote_pt_row else 0.0
        faltante = lote_target - ya_generado
        if faltante <= 0:
            return  # Las Novedades ya cubrieron toda la cantidad (del lote de esta OT)

        # lotes.numero es UNIQUE a nivel global (no por material). Si no hay
        # lote de PT para esta OT pero el número ya está tomado por un lote
        # de OTRO material, se le agrega un sufijo para no chocar.
        if not lote_pt_row:
            choque = query("SELECT id FROM lotes WHERE numero=?", (ot_lote_num,), one=True)
            if choque:
                ot_lote_num = f"{ot_lote_num}-PT"

        if lote_pt_row:
            execute("""UPDATE lotes SET
                cantidad_disponible=cantidad_disponible+?,
                cantidad_original=cantidad_original+?,
                estado='Ingresado'
                WHERE id=?""",
                (faltante, faltante, lote_pt_row["id"]))
            lote_pt_id = lote_pt_row["id"]
        else:
            lote_pt_id = execute("""INSERT INTO lotes
                (numero,material_id,cantidad_original,cantidad_disponible,
                 cantidad_activa,referencia_proveedor,estado,obs,creado_por)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (ot_lote_num, mat_pt["id"], faltante, faltante, 0,
                 f"OT {ot_lote_num}", "Ingresado",
                 f"Lotes MP: {lotes_ref}", session.get("user_id")))

        execute(
            "INSERT INTO movimientos (material_id,lote_id,tipo,cantidad,referencia,usuario_id) VALUES (?,?,?,?,?,?)",
            (mat_pt["id"], lote_pt_id, "ingreso", faltante,
             f"Generación automática al completar OT {ot_lote_num} — pendiente de clasificación de Calidad (no computa a stock) | Lotes MP: {lotes_ref}",
             session.get("user_id")))
        return

    # ── Con capacidad de cajón configurada: el PT se reparte en lotes tipo
    # "cajón" (numero = OT-C1, OT-C2, ...), cada uno con tope = capacidad
    # del producto. El cajón que todavía no se llenó queda en estado
    # 'Abierto' (sigue sumando piezas de próximas novedades); al llegar a la
    # capacidad pasa a 'Ingresado' (listo para que Calidad lo clasifique,
    # igual que el resto de los lotes). Esto reemplaza el lote único por OT:
    # así cada cajón físico que el operario lleva a Calidad es su propio
    # lote, y Calidad puede aprobar/rechazar cajón por cajón en vez de la
    # OT completa de una sola vez. ──────────────────────────────────────────
    prefijo_cajon = f"{ot_lote_num}-C"
    ya_generado = query("""SELECT COALESCE(SUM(cantidad_original),0) s FROM lotes
        WHERE material_id=? AND numero LIKE ?""",
        (mat_pt["id"], prefijo_cajon + "%"), one=True)["s"] or 0.0

    restante = lote_target - float(ya_generado)
    if restante <= 0.0001:
        return  # Las Novedades ya cubrieron toda la cantidad (en los cajones de esta OT)

    while restante > 0.0001:
        cajon = query("""SELECT * FROM lotes WHERE material_id=? AND numero LIKE ?
            AND estado='Abierto' ORDER BY id DESC LIMIT 1""",
            (mat_pt["id"], prefijo_cajon + "%"), one=True)
        if cajon:
            espacio = max(0.0, capacidad_cajon - float(cajon["cantidad_original"]))
            aporte = min(espacio, restante)
            if aporte <= 0:
                # Cajón "Abierto" ya está lleno por alguna inconsistencia
                # previa: se cierra igual para no quedar en loop infinito.
                execute("UPDATE lotes SET estado='Ingresado' WHERE id=?", (cajon["id"],))
                continue
            nuevo_total = float(cajon["cantidad_original"]) + aporte
            se_llena = nuevo_total >= capacidad_cajon - 0.0001
            execute("""UPDATE lotes SET
                cantidad_original=cantidad_original+?,
                cantidad_disponible=cantidad_disponible+?,
                estado=?
                WHERE id=?""",
                (aporte, aporte, ("Ingresado" if se_llena else "Abierto"), cajon["id"]))
            execute(
                "INSERT INTO movimientos (material_id,lote_id,tipo,cantidad,referencia,usuario_id) VALUES (?,?,?,?,?,?)",
                (mat_pt["id"], cajon["id"], "ingreso", aporte,
                 f"Producción OT {ot_lote_num}, cajón {cajon['numero']}"
                 + (" — cajón completo, pendiente de clasificación de Calidad" if se_llena else " — cajón en curso")
                 + f" (no computa a stock) | Lotes MP: {lotes_ref}",
                 session.get("user_id")))
            restante -= aporte
        else:
            n_existentes = query("SELECT COUNT(*) c FROM lotes WHERE material_id=? AND numero LIKE ?",
                (mat_pt["id"], prefijo_cajon + "%"), one=True)["c"]
            numero_cajon = f"{prefijo_cajon}{n_existentes+1}"
            aporte = min(capacidad_cajon, restante)
            se_llena = aporte >= capacidad_cajon - 0.0001
            cid = execute("""INSERT INTO lotes
                (numero,material_id,cantidad_original,cantidad_disponible,
                 cantidad_activa,referencia_proveedor,estado,obs,creado_por)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (numero_cajon, mat_pt["id"], aporte, aporte, 0,
                 f"OT {ot_lote_num}", ("Ingresado" if se_llena else "Abierto"),
                 f"Lotes MP: {lotes_ref}", session.get("user_id")))
            execute(
                "INSERT INTO movimientos (material_id,lote_id,tipo,cantidad,referencia,usuario_id) VALUES (?,?,?,?,?,?)",
                (mat_pt["id"], cid, "ingreso", aporte,
                 f"Producción OT {ot_lote_num}, cajón {numero_cajon}"
                 + (" — cajón completo, pendiente de clasificación de Calidad" if se_llena else " — cajón en curso")
                 + f" (no computa a stock) | Lotes MP: {lotes_ref}",
                 session.get("user_id")))
            restante -= aporte


@app.route("/api/ordenes/<int:oid>", methods=["PUT"])
@login_required(roles=["admin","operario","vendedor"])
def update_orden(oid):
    d = request.json
    if not d.get("producto_id"): return jsonify({"error":"Producto requerido"}), 400
    prod = query("SELECT codigo,nombre FROM productos WHERE id=?", (d["producto_id"],), one=True)
    if not prod: return jsonify({"error":"Producto no encontrado"}), 404
    descripcion = d.get("descripcion") or f"{prod['codigo']} — {prod['nombre']}"

    # Obtener estado actual antes de actualizar
    orden_actual = query("SELECT estado, stock_descontado, numero, producto_id FROM ordenes WHERE id=?", (oid,), one=True)
    nuevo_estado = d.get("estado", "Pendiente")

    # ── No permitir completar la OT si quedan operaciones sin completar ───────
    # El descuento de stock (lotes + insumos) se dispara cuando la OT pasa a
    # "Completada", así que primero hay que garantizar que TODAS sus
    # operaciones ya estén en estado "Completada".
    ya_estaba_completada_chk = orden_actual and orden_actual["estado"] == "Completada"
    if nuevo_estado == "Completada" and not ya_estaba_completada_chk:
        # Si un paso tiene rutas alternativas (mismo número de "orden"),
        # alcanza con que UNA de ellas esté Completada para dar el paso por
        # hecho — las demás alternativas no usadas quedan en Pendiente.
        pendientes = query("""SELECT COUNT(*) c FROM (
            SELECT orden FROM orden_operaciones WHERE orden_id=?
            GROUP BY orden HAVING SUM(CASE WHEN estado='Completada' THEN 1 ELSE 0 END)=0)""",
            (oid,), one=True)["c"]
        if pendientes > 0:
            return jsonify({"error": f"No se puede completar la OT: quedan {pendientes} operación(es) sin completar"}), 400

    # ── Cambio de producto en una OT existente ────────────────────────────────
    # Las operaciones (orden_operaciones), los materiales requeridos
    # (orden_materiales) y los lotes ya vinculados (orden_lotes) se generan a
    # partir del producto de la OT. Si el producto cambia, todo eso queda
    # "huérfano": las operaciones siguen siendo las del producto viejo, y por
    # eso al declarar una novedad seguía ofreciendo vincular un lote de la
    # operación/producto anterior. Para evitarlo, si cambia el producto y la
    # OT no tiene nada de trabajo real ya declarado, se regeneran las
    # operaciones y materiales para el producto nuevo. Si ya hay novedades,
    # lotes vinculados o producción declarada, se bloquea el cambio de
    # producto para no perder ni corromper ese historial.
    producto_anterior = orden_actual["producto_id"] if orden_actual else None
    cambia_producto = producto_anterior is not None and int(producto_anterior) != int(d["producto_id"])
    if cambia_producto:
        novedades_previas = query("""SELECT COUNT(*) c FROM novedades_produccion n
            JOIN orden_operaciones oo ON oo.id=n.orden_operacion_id
            WHERE oo.orden_id=?""", (oid,), one=True)["c"]
        lotes_vinculados = query("SELECT COUNT(*) c FROM orden_lotes WHERE orden_id=?", (oid,), one=True)["c"]
        produccion_declarada = query("""SELECT COUNT(*) c FROM orden_operaciones
            WHERE orden_id=? AND qty_producida>0""", (oid,), one=True)["c"]
        if novedades_previas > 0 or lotes_vinculados > 0 or produccion_declarada > 0:
            return jsonify({"error": "No se puede cambiar el producto de la OT: ya tiene novedades, lotes vinculados o producción declarada. Cancelá o revertí esa actividad antes de cambiar el producto."}), 400

    # ── Completar la OT: no confirmar el estado hasta que todo salga bien ─────
    # Antes, el UPDATE de abajo grababa estado='Completada' de entrada, y el
    # descuento de stock / generación del lote de PT se hacían DESPUÉS, cada
    # uno con su propio commit. Si algo fallaba a mitad de camino (una
    # excepción en el descuento o en la generación del PT), la OT quedaba
    # guardada como "Completada" en la base aunque el stock nunca se hubiera
    # descontado ni el lote de PT se hubiera generado — y como ya figuraba
    # "Completada", un reintento (incluso revirtiendo a "En proceso" y volviendo
    # a completar) volvía a chocar con el mismo error, dejando la OT trabada.
    # Para evitarlo: si la OT recién está pasando a "Completada", el UPDATE
    # principal graba el estado ANTERIOR (no toca nada más), y solo al final,
    # una vez que el descuento de stock y la generación del PT terminaron sin
    # errores, se confirma el cambio a "Completada" en un último UPDATE.
    completando_ahora = nuevo_estado == "Completada" and not ya_estaba_completada_chk
    estado_a_grabar = (orden_actual["estado"] if orden_actual else "Pendiente") if completando_ahora else nuevo_estado

    execute("UPDATE ordenes SET cliente_id=?,producto_id=?,descripcion=?,detalle=?,cantidad=?,prioridad=?,estado=?,fecha_inicio=?,fecha_entrega=?,costo_mat=?,costo_mo=?,precio_venta=0,obs=?,actualizado=datetime('now','localtime') WHERE id=?",
        (d.get("cliente_id"),d["producto_id"],descripcion,d.get("detalle"),d.get("cantidad",1),d.get("prioridad","Normal"),estado_a_grabar,d.get("fecha_inicio"),d.get("fecha_entrega"),d.get("costo_mat",0),d.get("costo_mo",0),d.get("obs"),oid))

    # Al cambiar el producto (sin actividad previa), regenerar operaciones y
    # materiales requeridos para que reflejen la ruta del producto nuevo.
    if cambia_producto:
        _populate_orden_operaciones(oid)
        _populate_orden_materiales(oid)

    # ── Descontar stock de materiales al completar la OT ──────────────────────
    # Solo importa si ya se descontó o no (stock_descontado). NO alcanza con
    # mirar si el estado anterior ya era "Completada": si la OT quedó cargada
    # como Completada de entrada (ej. datos migrados/de prueba) sin pasar
    # nunca por este descuento, stock_descontado sigue en 0 y hay que
    # generarlo igual la próxima vez que se guarde la OT.
    ya_estaba_completada = orden_actual and orden_actual["estado"] == "Completada"
    ya_descontado = orden_actual and int(orden_actual["stock_descontado"] or 0) == 1

    # Todo lo que sigue (descuento de stock + generación del lote de PT) se
    # ejecuta dentro de un try/except: si algo falla acá, la OT NO debe quedar
    # confirmada como "Completada" (ver estado_a_grabar más arriba), para que
    # el usuario reciba el error real y pueda reintentar sin quedar trabado.
    try:
        if nuevo_estado == "Completada" and not ya_descontado:
            numero_ot = orden_actual["numero"] if orden_actual else str(oid)

            # NOTA: los materiales/PT que llevan lote YA se descuentan del
            # stock y del lote en el momento en que se declara cada novedad
            # (ver create_novedad), no acá. Antes este bloque volvía a
            # descontar cantidad_disponible/cantidad_activa/stock a partir
            # de orden_lotes.cantidad_usada al completar la OT, lo que
            # duplicaba el descuento (una vez por novedad + una vez acá).
            # Se deja el flag stock_descontado en 1 igual, para no romper
            # la idempotencia de este bloque ni la lógica de PT de abajo.
            execute("UPDATE ordenes SET stock_descontado=1 WHERE id=?", (oid,))

            # ── Insumos (sin lote): descuento directo del stock general ──────────
            # A diferencia de los materiales con lote, los insumos no se validan
            # ni descuentan al declarar la novedad (ver create_novedad). Acá se
            # calcula el consumo total a partir de lo realmente producido en cada
            # operación de la OT (qty_producida) por la cantidad unitaria definida
            # en operacion_materiales, y se descuenta de una sola vez al completar.
            insumos = query("""
                SELECT om.material_id, m.codigo, m.descripcion,
                       SUM(om.cantidad * oo.qty_producida) consumo
                FROM orden_operaciones oo
                JOIN operacion_materiales om ON om.operacion_id=oo.proceso_op_id
                JOIN materiales m ON m.id=om.material_id
                WHERE oo.orden_id=? AND m.categoria IN ('Insumo','Herramienta')
                GROUP BY om.material_id
            """, (oid,))
            for ins in insumos:
                consumo = float(ins["consumo"] or 0)
                if consumo <= 0:
                    continue
                execute("""UPDATE materiales
                    SET stock=MAX(0, stock-?), actualizado=datetime('now','localtime')
                    WHERE id=?""", (consumo, ins["material_id"]))
                auto_generar_sc_bajo_stock(ins["material_id"], f"consumo insumos OT {numero_ot}")
                execute("""INSERT INTO movimientos
                    (material_id, lote_id, tipo, cantidad, referencia, usuario_id)
                    VALUES (?, NULL, 'salida', ?, ?, ?)""",
                    (ins["material_id"], consumo,
                     f"Consumo OT {numero_ot} — Insumo {ins['codigo']} (sin lote)",
                     session["user_id"]))

        # ── Red de seguridad: asegurar que el PT quede generado ──────────────────
        # Se ejecuta SIEMPRE que la OT quede en estado "Completada", incluso si
        # stock_descontado ya estaba en 1 (ej: la OT ya se había completado antes
        # y se vuelve a guardar). La función es idempotente: calcula cuánto PT ya
        # existe en el lote OT-N y solo agrega lo que falte hasta la cantidad
        # total de la OT, así que no duplica nada.
        if nuevo_estado == "Completada":
            generar_pt_faltante_si_corresponde(oid)
            # Si quedó un cajón "Abierto" (parcialmente lleno) para esta OT,
            # se cierra igual: al completarse la OT no van a llegar más
            # piezas para terminar de llenarlo, así que pasa a "Ingresado"
            # (pendiente de Calidad) con lo que tenga hasta ahora.
            numero_ot_cierre = orden_actual["numero"] if orden_actual else str(oid)
            execute("UPDATE lotes SET estado='Ingresado' WHERE estado='Abierto' AND numero LIKE ?",
                (numero_ot_cierre + "-C%",))
    except Exception as e:
        # Algo falló al descontar stock o generar el lote de PT: NO confirmar
        # la OT como "Completada" (ya quedó grabada con su estado anterior más
        # arriba), para que el usuario vea el error real y pueda reintentar
        # sin que la OT quede en un limbo "Completada" sin stock ni lote.
        return jsonify({"error": f"No se pudo completar la OT: {e}"}), 500

    # Recién acá, con el descuento de stock y la generación del PT ya
    # confirmados sin errores, se graba el cambio de estado a "Completada".
    if completando_ahora:
        execute("UPDATE ordenes SET estado='Completada' WHERE id=?", (oid,))

    # Si se revierte de Completada a otro estado, restaurar el stock
    if orden_actual and orden_actual["estado"] == "Completada" and nuevo_estado != "Completada" and ya_descontado:
        numero_ot = orden_actual["numero"] if orden_actual else str(oid)

        # NOTA IMPORTANTE: los materiales/PT que llevan LOTE ya NO se
        # reversan acá. Desde que el descuento de esos materiales pasó a
        # hacerse al instante en cada novedad (ver create_novedad, descuento
        # inmediato), completar la OT NUNCA vuelve a descontar ese stock —
        # por lo tanto reabrir la OT (revertir de "Completada") tampoco debe
        # devolverlo. Antes este bloque SÍ lo devolvía (cantidad_disponible,
        # cantidad_activa y, peor, cantidad_reservada) basándose en
        # orden_lotes.cantidad_usada, como si el completar hubiera vuelto a
        # descontarlo — lo cual generaba stock/reserva fantasma cada vez que
        # se reabría y volvía a completar una OT (bug reportado: reservado
        # que crecía sin corresponder a ningún consumo real). El único lugar
        # que debe tocar cantidad_reservada/cantidad_disponible/activa de un
        # lote por consumo de OT es create_novedad, en el momento en que se
        # declara cada novedad real.
        execute("UPDATE ordenes SET stock_descontado=0 WHERE id=?", (oid,))

        # ── Reversión de insumos (sin lote) ───────────────────────────────────
        insumos_rev = query("""
            SELECT om.material_id, m.codigo,
                   SUM(om.cantidad * oo.qty_producida) consumo
            FROM orden_operaciones oo
            JOIN operacion_materiales om ON om.operacion_id=oo.proceso_op_id
            JOIN materiales m ON m.id=om.material_id
            WHERE oo.orden_id=? AND m.categoria IN ('Insumo','Herramienta')
            GROUP BY om.material_id
        """, (oid,))
        for ins in insumos_rev:
            consumo = float(ins["consumo"] or 0)
            if consumo <= 0:
                continue
            execute("""UPDATE materiales
                SET stock=stock+?, actualizado=datetime('now','localtime')
                WHERE id=?""", (consumo, ins["material_id"]))
            execute("""INSERT INTO movimientos
                (material_id, lote_id, tipo, cantidad, referencia, usuario_id)
                VALUES (?, NULL, 'entrada', ?, ?, ?)""",
                (ins["material_id"], consumo,
                 f"Reversión OT {numero_ot} — Insumo {ins['codigo']} (estado cambiado a {nuevo_estado})",
                 session["user_id"]))

        # ── Reversión del excedente "Producto sin lote" ───────────────────────
        sinlote_prev = float(orden_actual["sinlote_generado"] or 0) if orden_actual and "sinlote_generado" in orden_actual.keys() else 0.0
        if sinlote_prev > 0 and orden_actual["producto_id"]:
            prod_rev = query("SELECT * FROM productos WHERE id=?", (orden_actual["producto_id"],), one=True)
            if prod_rev:
                mat_sinlote_rev = get_or_create_sinlote_material(prod_rev)
                execute("""UPDATE materiales SET stock=MAX(0, stock-?), actualizado=datetime('now','localtime')
                    WHERE id=?""", (sinlote_prev, mat_sinlote_rev["id"]))
                execute("""INSERT INTO movimientos (material_id,lote_id,tipo,cantidad,referencia,usuario_id)
                    VALUES (?,NULL,'salida',?,?,?)""",
                    (mat_sinlote_rev["id"], sinlote_prev,
                     f"Reversión OT {numero_ot} — excedente sin lote (estado cambiado a {nuevo_estado})",
                     session["user_id"]))
        execute("UPDATE ordenes SET sinlote_generado=0 WHERE id=?", (oid,))

    # ── Cancelar la OT: desvincular lotes de materiales ya asignados ──────────
    # Al cancelar, cualquier lote vinculado a esta OT (por "Asignar lote" o
    # automáticamente al declarar una novedad) debe desvincularse, INCLUSO si
    # ya se consumió parte del material desde ese lote. Se libera la reserva
    # pendiente que pudiera quedar sobre el lote (cantidad_reservada) para
    # que vuelva a estar disponible para otras OTs; el material que ya se
    # descontó como consumo real (stock/cantidad_activa) NO se devuelve acá
    # — desvincular no es lo mismo que reponer stock ya gastado.
    ya_estaba_cancelada = orden_actual and orden_actual["estado"] == "Cancelada"
    if nuevo_estado == "Cancelada" and not ya_estaba_cancelada:
        vinculos = query("SELECT * FROM orden_lotes WHERE orden_id=?", (oid,))
        for v in vinculos:
            execute("UPDATE lotes SET cantidad_reservada=MAX(0, COALESCE(cantidad_reservada,0)-?) WHERE id=?",
                (float(v["cantidad_usada"] or 0), v["lote_id"]))
        execute("DELETE FROM orden_lotes WHERE orden_id=?", (oid,))
        execute("UPDATE orden_materiales SET cantidad_asignada=0 WHERE orden_id=?", (oid,))

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
    last = query("SELECT numero FROM presupuestos ORDER BY id DESC LIMIT 1", one=True)
    try: n = int(last["numero"].split("-")[1])+1 if last else 1
    except: n = 1
    numero = f"PRES-{n:03d}"
    sub = float(d.get("subtotal", 0))
    iva = float(d.get("iva_pct", 21))
    total = float(d.get("total")) if d.get("total") else sub * (1 + iva/100)
    if not sub and total: sub = total / (1 + iva/100)
    lid = execute("INSERT INTO presupuestos (numero,cliente_id,descripcion,items,subtotal,iva_pct,total,validez_dias,estado,obs) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (numero,d.get("cliente_id"),d["descripcion"],d.get("items"),sub,iva,total,d.get("validez_dias",30),d.get("estado","Borrador"),d.get("obs")))
    return jsonify({"ok":True,"id":lid,"numero":numero,"total":total}), 201

# ── Usuarios ──────────────────────────────────────────────────────────────────
@app.route("/api/usuarios", methods=["GET"])
@login_required(roles=["admin"])
def get_usuarios():
    return jsonify([dict(r) for r in query("SELECT id,username,nombre,rol,activo,creado FROM usuarios ORDER BY nombre")])

@app.route("/api/usuarios", methods=["POST"])
@login_required(roles=["admin"])
def create_usuario():
    d = request.json
    if not d.get("username") or not d.get("password"): 
        return jsonify({"error":"Username y contraseña requeridos"}), 400
    if query("SELECT id FROM usuarios WHERE username=?", (d["username"],), one=True): 
        return jsonify({"error":"Usuario ya existe"}), 409
    
    rol = d.get("rol", "operario")
    
    # Crear el usuario
    execute("INSERT INTO usuarios (username,password,nombre,rol) VALUES (?,?,?,?)",
            (d["username"], hash_pw(d["password"]), d.get("nombre", d["username"]), rol))
    
    # Obtener el ID del usuario recién creado
    usuario_id = query("SELECT id FROM usuarios WHERE username=?", (d["username"],), one=True)["id"]
    
    # Asignar permisos predeterminados según el rol
    # Admin no necesita permisos explícitos (tiene acceso total)
    if rol in DEFAULT_PERMISIONES:
        for clave, valor in DEFAULT_PERMISIONES[rol].items():
            execute("""INSERT OR IGNORE INTO usuario_permisos (usuario_id, clave, valor) 
                      VALUES (?, ?, ?)""",
                    (usuario_id, clave, valor))
    
    return jsonify({"ok": True}), 201

@app.route("/api/usuarios/<int:uid>", methods=["DELETE"])
@login_required(roles=["admin"])
def delete_usuario(uid):
    if uid == session["user_id"]: return jsonify({"error":"No podés eliminar tu propio usuario"}), 400
    execute("UPDATE usuarios SET activo=0 WHERE id=?", (uid,))
    return jsonify({"ok":True})


# ── Producto-Clientes (vinculación) ───────────────────────────────────────────
@app.route("/api/productos/<int:pid>/clientes", methods=["GET"])
@login_required()
def get_producto_clientes(pid):
    rows = query("SELECT c.* FROM producto_clientes pc JOIN clientes c ON c.id=pc.cliente_id WHERE pc.producto_id=?", (pid,))
    return jsonify([dict(r) for r in rows])

@app.route("/api/productos/<int:pid>/clientes", methods=["POST"])
@login_required(roles=["admin","vendedor"])
def link_producto_cliente(pid):
    d = request.json
    cid = d.get("cliente_id")
    if not cid: return jsonify({"error":"cliente_id requerido"}), 400
    execute("INSERT OR IGNORE INTO producto_clientes (producto_id,cliente_id) VALUES (?,?)", (pid, cid))
    return jsonify({"ok":True}), 201

@app.route("/api/productos/<int:pid>/clientes/<int:cid>", methods=["DELETE"])
@login_required(roles=["admin","vendedor"])
def unlink_producto_cliente(pid, cid):
    execute("DELETE FROM producto_clientes WHERE producto_id=? AND cliente_id=?", (pid, cid))
    return jsonify({"ok":True})

@app.route("/api/productos_by_cliente/<int:cid>", methods=["GET"])
@login_required()
def get_productos_by_cliente(cid):
    rows = query("SELECT p.*,COALESCE(p.peso_kg,0) peso_kg,c.nombre categoria_nombre FROM productos p LEFT JOIN categorias_producto c ON c.id=p.categoria_id WHERE p.id IN (SELECT producto_id FROM producto_clientes WHERE cliente_id=?) AND p.activo=1 ORDER BY p.codigo", (cid,))
    return jsonify([dict(r) for r in rows])

# ── Operaciones de OT (desglose en renglones) ─────────────────────────────────
@app.route("/api/ordenes/<int:oid>/operaciones", methods=["GET"])
@login_required()
def get_orden_operaciones(oid):
    rows = query("""SELECT oo.*,cm.nombre cat_maquina_nombre,m.nombre maquina_nombre,
        p.razon proveedor_nombre
        FROM orden_operaciones oo
        LEFT JOIN categorias_maquina cm ON cm.id=oo.categoria_maquina_id
        LEFT JOIN maquinas m ON m.id=oo.maquina_id
        LEFT JOIN proveedores p ON p.id=oo.proveedor_id
        WHERE oo.orden_id=? ORDER BY CAST(oo.orden AS INTEGER), oo.orden""", (oid,))
    return jsonify([dict(r) for r in rows])

def _populate_orden_operaciones(oid):
    """Borra y regenera orden_operaciones a partir del producto actual de la OT.
    Función interna reutilizada por el endpoint POST y por update_orden cuando
    se cambia el producto de una OT existente."""
    orden = query("SELECT producto_id FROM ordenes WHERE id=?", (oid,), one=True)
    if not orden or not orden["producto_id"]: return None
    execute("DELETE FROM orden_operaciones WHERE orden_id=?", (oid,))
    ops = query("""SELECT po.*,cm.nombre cat_maq FROM proceso_operaciones po
        LEFT JOIN categorias_maquina cm ON cm.id=po.categoria_maquina_id
        WHERE po.producto_id=? ORDER BY CAST(po.orden AS INTEGER), po.orden""", (orden["producto_id"],))
    qty = query("SELECT cantidad FROM ordenes WHERE id=?", (oid,), one=True)["cantidad"]
    for op in ops:
        # Volumen agrupado: si la operación agrupa el total a realizar en
        # lotes de tamaño "valor_recalculado", la cantidad requerida de esta
        # operación puntual pasa a ser ceil(total_ot / valor_recalculado) en
        # lugar del total de la OT. Ej: OT total=100, valor_recalculado=33 →
        # requerido=3.
        vol_agrup = op["volumen_agrupado"] if "volumen_agrupado" in op.keys() else 0
        valor_recalc = op["valor_recalculado"] if "valor_recalculado" in op.keys() else 0
        if vol_agrup and valor_recalc and valor_recalc > 0:
            qty_op = math.ceil(qty / valor_recalc)
        else:
            qty_op = qty
        execute("""INSERT INTO orden_operaciones
            (orden_id,proceso_op_id,orden,nombre,categoria_maquina_id,maquina_id,
             tiempo_setup_min,tiempo_ciclo_min,estado,qty_requerida,
             es_tercerizada,proveedor_id,precio_tercerizado,tiempo_minimo_dias)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (oid,op["id"],op["orden"],op["nombre"],op["categoria_maquina_id"],op["maquina_id"],
             op["tiempo_setup_min"],op["tiempo_ciclo_min"],"Pendiente",qty_op,
             op["es_tercerizada"] if "es_tercerizada" in op.keys() else 0,
             op["proveedor_id"] if "proveedor_id" in op.keys() else None,
             op["precio_tercerizado"] if "precio_tercerizado" in op.keys() else 0,
             op["tiempo_minimo_dias"] if "tiempo_minimo_dias" in op.keys() else 0))
    # Auto-generate solicitudes_compra for tercerizada ops
    ot_row = query("SELECT numero FROM ordenes WHERE id=?", (oid,), one=True)
    if ot_row:
        _generar_sc_tercerizado(oid, ot_row["numero"])

    _aplicar_stock_sinlote_a_ot(oid)

    return len(ops)


def _aplicar_stock_sinlote_a_ot(oid):
    """Si el producto de la OT tiene stock en 'Producto sin lote' (piezas que
    sobraron de producir de más en una OT anterior, ver
    generar_pt_faltante_si_corresponde), lo consume para dar la OT nueva por
    ya-hecha hasta esa cantidad.

    El sobrante en generar_pt_faltante_si_corresponde siempre se genera en la
    ÚLTIMA operación de la ruta (la que cierra la OT). Por eso acá el
    qty_producida se carga únicamente en la última operación de la OT nueva
    (ej. op20) y NO en las anteriores (ej. op10 queda en 0): esas operaciones
    previas no se hicieron realmente, solo la última tenía el excedente.
    Ese stock se descuenta del material sin lote.
    """
    orden = query("SELECT id,numero,producto_id,cantidad FROM ordenes WHERE id=?", (oid,), one=True)
    if not orden or not orden["producto_id"]:
        return
    prod = query("SELECT * FROM productos WHERE id=?", (orden["producto_id"],), one=True)
    if not prod:
        return

    mat_sinlote = get_or_create_sinlote_material(prod)
    disponible = float(query("SELECT stock FROM materiales WHERE id=?", (mat_sinlote["id"],), one=True)["stock"] or 0)
    if disponible <= 0:
        return

    qty_pedida = float(orden["cantidad"] or 0)
    aplicar = min(disponible, qty_pedida) if qty_pedida > 0 else disponible
    if aplicar <= 0:
        return

    ultima_op = query("""SELECT id,qty_requerida FROM orden_operaciones
        WHERE orden_id=? ORDER BY CAST(orden AS INTEGER) DESC, orden DESC LIMIT 1""", (oid,), one=True)
    if not ultima_op:
        return

    qty_req_op = float(ultima_op["qty_requerida"] or 0)
    qty_op = min(aplicar, qty_req_op) if qty_req_op > 0 else aplicar
    nuevo_estado_op = "Completada" if qty_req_op > 0 and qty_op >= qty_req_op else "En proceso"
    execute("UPDATE orden_operaciones SET qty_producida=?, estado=? WHERE id=?",
        (qty_op, nuevo_estado_op, ultima_op["id"]))
    # aplicar puede exceder lo que la última operación admite (qty_req_op);
    # lo efectivamente consumido del sinlote es qty_op, no "aplicar" original.
    aplicar = qty_op

    execute("UPDATE materiales SET stock=MAX(0, stock-?), actualizado=datetime('now','localtime') WHERE id=?",
        (aplicar, mat_sinlote["id"]))
    execute("""INSERT INTO movimientos (material_id,lote_id,tipo,cantidad,referencia,usuario_id)
        VALUES (?,NULL,'salida',?,?,?)""",
        (mat_sinlote["id"], aplicar,
         f"Aplicado a OT {orden['numero']} — piezas ya hechas (sobrante de producción anterior)",
         session.get("user_id")))

    # Si la OT quedó completa de entrada (el sobrante alcanzaba/superaba lo
    # pedido), no se auto-completa la OT acá: eso requiere pasar por el
    # flujo normal de "Completar OT" (PUT estado=Completada), que además
    # genera el lote de PT correspondiente.


def _populate_orden_materiales(oid):
    """Borra y regenera orden_materiales a partir del producto actual de la OT."""
    orden = query("SELECT producto_id,cantidad FROM ordenes WHERE id=?", (oid,), one=True)
    if not orden or not orden["producto_id"]: return None
    execute("DELETE FROM orden_materiales WHERE orden_id=?", (oid,))
    mats = query("""SELECT om.material_id,SUM(om.cantidad)*? AS total,m.unidad
        FROM proceso_operaciones po
        JOIN operacion_materiales om ON om.operacion_id=po.id
        JOIN materiales m ON m.id=om.material_id
        WHERE po.producto_id=? GROUP BY om.material_id""",
        (orden["cantidad"], orden["producto_id"]))
    for mat in mats:
        execute("INSERT INTO orden_materiales (orden_id,material_id,cantidad_requerida,cantidad_asignada,unidad) VALUES (?,?,?,0,?)",
            (oid, mat["material_id"], mat["total"], mat["unidad"]))
    return len(mats)


@app.route("/api/ordenes/<int:oid>/operaciones/populate", methods=["POST"])
@login_required()
def populate_orden_operaciones(oid):
    n = _populate_orden_operaciones(oid)
    if n is None: return jsonify({"error":"La OT no tiene producto asignado"}), 400
    return jsonify({"ok":True,"ops_created":n})

@app.route("/api/orden_operaciones/<int:ooid>", methods=["PUT"])
@login_required(roles=["admin","operario"])
def update_orden_operacion(ooid):
    d = request.json
    nuevo_estado = d.get("estado","Pendiente")
    if nuevo_estado != "Pendiente":
        oo = query("SELECT orden_id, orden, estado FROM orden_operaciones WHERE id=?", (ooid,), one=True)
        if not oo: return jsonify({"error":"Operación no encontrada"}), 404
    execute("UPDATE orden_operaciones SET estado=?,qty_producida=? WHERE id=?",
        (nuevo_estado, d.get("qty_producida",0), ooid))
    return jsonify({"ok":True})

# ── CRUD completo para operaciones de OT ─────────────────────────────────────
@app.route("/api/ordenes/<int:oid>/operaciones/<int:opid>", methods=["PUT"])
@login_required(roles=["admin","operario"])
def update_ot_operacion(oid, opid):
    d = request.json or {}
    # Build dynamic UPDATE based on which fields were provided
    allowed = {
        "orden", "nombre", "categoria_maquina_id", "maquina_id",
        "tiempo_setup_min", "tiempo_ciclo_min", "qty_requerida", "estado",
    }
    fields = {k: v for k, v in d.items() if k in allowed}
    if not fields:
        return jsonify({"ok": True, "noop": True})
    if fields.get("estado") and fields["estado"] != "Pendiente":
        oo = query("SELECT orden, estado FROM orden_operaciones WHERE id=? AND orden_id=?", (opid, oid), one=True)
    set_clause = ", ".join(f"{k}=?" for k in fields.keys())
    params = list(fields.values()) + [opid, oid]
    execute(f"UPDATE orden_operaciones SET {set_clause} WHERE id=? AND orden_id=?", params)
    # Si se puso esta operación "En proceso" o "Completada" a mano, la OT
    # también pasa de "Pendiente" a "En proceso" (ya se empezó a producir).
    if fields.get("estado") in ("En proceso", "Completada"):
        execute("UPDATE ordenes SET estado='En proceso' WHERE id=? AND estado='Pendiente'", (oid,))
    return jsonify({"ok": True})

@app.route("/api/ordenes/<int:oid>/operaciones/<int:opid>", methods=["DELETE"])
@login_required(roles=["admin","operario"])
def delete_ot_operacion(oid, opid):
    execute("DELETE FROM orden_operaciones WHERE id=? AND orden_id=?", (opid, oid))
    return jsonify({"ok": True})

@app.route("/api/ordenes/<int:oid>/operaciones", methods=["POST"])
@login_required(roles=["admin","operario"])
def add_ot_operacion(oid):
    d = request.json
    if not d.get("nombre"): return jsonify({"error":"Nombre requerido"}), 400
    new_id = execute("""INSERT INTO orden_operaciones
        (orden_id,orden,nombre,categoria_maquina_id,maquina_id,
         tiempo_setup_min,tiempo_ciclo_min,estado,qty_requerida,obs)
        VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (oid, d.get("orden",1), d["nombre"],
         d.get("categoria_maquina_id") or None,
         d.get("maquina_id") or None,
         d.get("tiempo_setup_min",0), d.get("tiempo_ciclo_min",0),
         d.get("estado","Pendiente"), d.get("qty_requerida",0),
         d.get("obs")))
    return jsonify({"ok": True, "id": new_id}), 201

# ── Materiales de OT ──────────────────────────────────────────────────────────
@app.route("/api/ordenes/<int:oid>/materiales", methods=["GET"])
@login_required()
def get_orden_materiales(oid):
    rows = query("""SELECT om.*,m.descripcion,m.codigo,m.unidad,m.stock,m.categoria
        FROM orden_materiales om JOIN materiales m ON m.id=om.material_id
        WHERE om.orden_id=? ORDER BY m.codigo""", (oid,))
    # Lotes ya vinculados a esta OT (asignados manualmente y/o consumidos por
    # novedades), para que el frontend pueda mostrar QUÉ lote(s) se eligieron
    # para cada material en la tabla de "Lotes asignados".
    lotes_rows = query("""SELECT ol.material_id, ol.lote_id, l.numero, ol.cantidad_usada
        FROM orden_lotes ol JOIN lotes l ON l.id=ol.lote_id
        WHERE ol.orden_id=?""", (oid,))
    lotes_por_mat = {}
    for lr in lotes_rows:
        lotes_por_mat.setdefault(lr["material_id"], []).append(
            {"lote_id": lr["lote_id"], "numero": lr["numero"], "cantidad_usada": lr["cantidad_usada"]})
    # A qué operación(es) del proceso está destinado cada material (un mismo
    # material puede estar requerido por más de un paso de la ruta, así que
    # se lista cada uno con su número de orden).
    ops_por_mat = {}
    orden_row = query("SELECT producto_id FROM ordenes WHERE id=?", (oid,), one=True)
    if orden_row and orden_row["producto_id"]:
        ops_rows = query("""SELECT om2.material_id, po.orden op_orden, po.nombre op_nombre
            FROM operacion_materiales om2
            JOIN proceso_operaciones po ON po.id=om2.operacion_id
            WHERE po.producto_id=?""", (orden_row["producto_id"],))
        for orow in ops_rows:
            ops_por_mat.setdefault(orow["material_id"], []).append(
                f"{orow['op_orden']}. {orow['op_nombre']}")
    out = []
    for r in rows:
        rd = dict(r)
        rd["lotes_asignados"] = lotes_por_mat.get(r["material_id"], [])
        rd["operaciones"] = ops_por_mat.get(r["material_id"], [])
        out.append(rd)
    return jsonify(out)

@app.route("/api/ordenes/<int:oid>/materiales/populate", methods=["POST"])
@login_required()
def populate_orden_materiales(oid):
    n = _populate_orden_materiales(oid)
    if n is None: return jsonify({"error":"OT sin producto"}), 400
    return jsonify({"ok":True,"mats":n})

@app.route("/api/ordenes/<int:oid>/materiales/<int:mid>/asignar", methods=["POST"])
@login_required(roles=["admin","almacen"])
def asignar_material_ot(oid, mid):
    d = request.json
    qty = float(d.get("cantidad",0))
    mat = query("SELECT id FROM materiales WHERE id=?", (mid,), one=True)
    if not mat: return jsonify({"error":"Material no encontrado"}), 404
    # Solo registra la cantidad asignada a la OT.
    # El descuento real del stock ocurre cuando la OT pasa a "Completada" (ver update_orden).
    execute("UPDATE orden_materiales SET cantidad_asignada=cantidad_asignada+? WHERE orden_id=? AND material_id=?", (qty,oid,mid))
    return jsonify({"ok":True})



# ══════════════════════════════════════════════════════════════════════════════
# OTT — Órdenes de Trabajo de Terceros
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/ott", methods=["GET"])
@login_required()
def get_ott_list():
    estado = request.args.get("estado")
    prov_id = request.args.get("proveedor_id")
    sql = """SELECT ott.*,
        o.numero ot_numero, p.razon proveedor_nombre,
        po.nombre op_nombre, po.orden op_orden,
        pr.nombre producto_nombre, pr.codigo producto_codigo
        FROM ordenes_tercerizado ott
        LEFT JOIN ordenes o ON o.id=ott.ot_origen_id
        LEFT JOIN proveedores p ON p.id=ott.proveedor_id
        LEFT JOIN proceso_operaciones po ON po.id=ott.proceso_op_id
        LEFT JOIN productos pr ON pr.id=po.producto_id
        WHERE 1=1"""
    params = []
    if estado:
        sql += " AND ott.estado=?"; params.append(estado)
    if prov_id:
        sql += " AND ott.proveedor_id=?"; params.append(prov_id)
    sql += " ORDER BY ott.creado DESC"
    return jsonify([dict(r) for r in query(sql, params)])

@app.route("/api/ott/<int:oid>", methods=["GET"])
@login_required()
def get_ott(oid):
    r = query("""SELECT ott.*,
        o.numero ot_numero, p.razon proveedor_nombre, p.telefono proveedor_tel,
        p.email proveedor_email, po.nombre op_nombre, po.orden op_orden,
        pr.nombre producto_nombre, pr.codigo producto_codigo,
        rem.numero remito_numero
        FROM ordenes_tercerizado ott
        LEFT JOIN ordenes o ON o.id=ott.ot_origen_id
        LEFT JOIN proveedores p ON p.id=ott.proveedor_id
        LEFT JOIN proceso_operaciones po ON po.id=ott.proceso_op_id
        LEFT JOIN productos pr ON pr.id=po.producto_id
        LEFT JOIN remitos rem ON rem.id=ott.remito_traslado_id
        WHERE ott.id=?""", (oid,), one=True)
    if not r: return jsonify({"error":"OTT no encontrada"}), 404
    return jsonify(dict(r))

@app.route("/api/ott", methods=["POST"])
@login_required(roles=["admin","operario"])
def create_ott():
    d = request.json
    if not d.get("proveedor_id"):
        return jsonify({"error":"Proveedor requerido"}), 400
    last = query("SELECT numero FROM ordenes_tercerizado ORDER BY id DESC LIMIT 1", one=True)
    try: n = int(last["numero"].split("-")[1])+1 if last else 1
    except: n = 1
    numero = f"OTT-{n:04d}"
    lid = execute("""INSERT INTO ordenes_tercerizado
        (numero,ot_origen_id,operacion_id,proceso_op_id,proveedor_id,
         precio_acordado,estado,es_ultimo_nivel,fecha_retorno_est,obs,creado_por)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (numero, d.get("ot_origen_id"), d.get("operacion_id"),
         d.get("proceso_op_id"), d["proveedor_id"],
         d.get("precio_acordado", 0), "Pendiente",
         1 if d.get("es_ultimo_nivel") else 0,
         d.get("fecha_retorno_est"), d.get("obs"), session["user_id"]))
    return jsonify({"ok": True, "id": lid, "numero": numero}), 201

@app.route("/api/ott/<int:oid>", methods=["PUT"])
@login_required(roles=["admin","operario"])
def update_ott(oid):
    d = request.json
    execute("""UPDATE ordenes_tercerizado SET estado=?,proveedor_id=?,precio_acordado=?,
        fecha_retorno_est=?,fecha_envio=?,obs=? WHERE id=?""",
        (d.get("estado"), d.get("proveedor_id"), d.get("precio_acordado",0),
         d.get("fecha_retorno_est"), d.get("fecha_envio"), d.get("obs"), oid))
    return jsonify({"ok": True})

@app.route("/api/ott/<int:oid>/emitir_remito", methods=["POST"])
@login_required(roles=["admin","operario"])
def ott_emitir_remito(oid):
    """Genera remito de traslado: piezas salen del taller hacia el proveedor."""
    ott = query("SELECT * FROM ordenes_tercerizado WHERE id=?", (oid,), one=True)
    if not ott: return jsonify({"error":"OTT no encontrada"}), 404
    if ott["estado"] not in ("Pendiente",):
        return jsonify({"error":"Solo se puede emitir remito desde estado Pendiente"}), 400

    # Create remito de traslado
    last_rem = query("SELECT numero FROM remitos ORDER BY id DESC LIMIT 1", one=True)
    try: nr = int(last_rem["numero"].split("-")[1])+1 if last_rem else 1
    except: nr = 1
    num_rem = f"REM-{nr:04d}"

    d = request.json or {}
    rid = execute("""INSERT INTO remitos (numero,cliente_id,fecha,estado,obs,creado_por,tipo,ott_id)
        VALUES (?,NULL,date('now','localtime'),'Emitido',?,?,?,?)""",
        (num_rem, d.get("obs","Traslado a proveedor externo"),
         session["user_id"], "traslado_ott", oid))

    execute("""UPDATE ordenes_tercerizado SET estado='Remito emitido',
        remito_traslado_id=?, fecha_envio=date('now','localtime') WHERE id=?""",
        (rid, oid))
    return jsonify({"ok": True, "remito_numero": num_rem, "remito_id": rid})

@app.route("/api/ott/<int:oid>/registrar_retorno", methods=["POST"])
@login_required(roles=["admin","operario","almacen"])
def ott_registrar_retorno(oid):
    """Registra el retorno de piezas: crea lote y según es_ultimo_nivel decide destino."""
    ott = query("""SELECT ott.*,po.producto_id,pr.codigo prod_codigo,pr.nombre prod_nombre,
        pr.unidad prod_unidad,o.numero ot_numero
        FROM ordenes_tercerizado ott
        LEFT JOIN proceso_operaciones po ON po.id=ott.proceso_op_id
        LEFT JOIN productos pr ON pr.id=po.producto_id
        LEFT JOIN ordenes o ON o.id=ott.ot_origen_id
        WHERE ott.id=?""", (oid,), one=True)
    if not ott: return jsonify({"error":"OTT no encontrada"}), 404
    if ott["estado"] not in ("Remito emitido","En proceso"):
        return jsonify({"error":"Estado inválido para registrar retorno"}), 400

    d = request.json
    cantidad = float(d.get("cantidad", 1))
    if cantidad <= 0:
        return jsonify({"error":"Cantidad debe ser mayor a 0"}), 400

    # Determine material_id for the lote:
    # if ultimo nivel → categoría PT (producto terminado)
    # if intermedio → semielaborado → use the material linked to the op's product
    # Vínculo por producto_id (FK), NO por codigo: dos productos distintos
    # pueden compartir codigo con un material ajeno por casualidad, y
    # buscar solo por codigo terminaría mezclando stock de cosas distintas.
    mat = query("SELECT id FROM materiales WHERE producto_id=? AND activo=1",
                (ott["producto_id"],), one=True)
    if not mat:
        # Auto-create a material entry for this PT/semielaborado, con un
        # codigo distinguible si el codigo del producto ya está tomado.
        codigo_base = ott["prod_codigo"]
        candidato = codigo_base
        intento = 1
        while query("SELECT id FROM materiales WHERE codigo=?", (candidato,), one=True):
            intento += 1
            candidato = f"{codigo_base}-PT{intento}"
        mat_id = execute("""INSERT INTO materiales
            (codigo,descripcion,categoria,producto_id,unidad,stock,stock_min,precio_unit,activo)
            VALUES (?,?,?,?,?,0,0,0,1)""",
            (candidato,
             ott["prod_nombre"],
             "Producto terminado" if ott["es_ultimo_nivel"] else "Semielaborado",
             ott["producto_id"],
             ott["prod_unidad"] or "unid"))
    else:
        mat_id = mat["id"]

    # Create lote
    last_l = query("SELECT numero FROM lotes ORDER BY id DESC LIMIT 1", one=True)
    try: nl = int(last_l["numero"].split("-")[2])+1 if last_l else 1
    except: nl = 1
    num_lote = f"LOTE-{ott['prod_codigo']}-{nl:04d}"

    lote_id = execute("""INSERT INTO lotes
        (numero,material_id,cantidad_original,cantidad_disponible,cantidad_activa,
         estado,obs,creado_por)
        VALUES (?,?,?,?,?,?,?,?)""",
        (num_lote, mat_id, cantidad, cantidad, cantidad, "Aprobado",
         f"Retorno OTT {ott['numero']} — OT {ott['ot_numero'] or '—'}",
         session["user_id"]))

    execute("""INSERT INTO movimientos (material_id,lote_id,tipo,cantidad,referencia,usuario_id)
        VALUES (?,?,'entrada',?,?,?)""",
        (mat_id, lote_id, cantidad, f"Retorno OTT {ott['numero']}", session["user_id"]))

    execute("""UPDATE ordenes_tercerizado
        SET estado='Recibido', lote_retorno_id=?,
            fecha_retorno_real=date('now','localtime') WHERE id=?""",
        (lote_id, oid))

    # Update material stock
    execute("UPDATE materiales SET stock=stock+? WHERE id=?", (cantidad, mat_id))

    resultado = {
        "ok": True,
        "lote_numero": num_lote,
        "lote_id": lote_id,
        "mat_id": mat_id,
        "es_ultimo_nivel": bool(ott["es_ultimo_nivel"]),
        "mensaje": (
            "Lote creado y disponible para Remitir a cliente"
            if ott["es_ultimo_nivel"]
            else "Lote creado como semielaborado — asignable a OT"
        )
    }
    return jsonify(resultado), 201

@app.route("/api/ott/<int:oid>/completar", methods=["POST"])
@login_required(roles=["admin","operario"])
def ott_completar(oid):
    execute("UPDATE ordenes_tercerizado SET estado='Completado' WHERE id=?", (oid,))
    return jsonify({"ok": True})

# ── Materiales/PT requeridos por una operación de OT + lotes disponibles ──────
@app.route("/api/orden_operaciones/<int:ooid>/materiales_requeridos")
@login_required()
def get_materiales_requeridos_op(ooid):
    """Para el modal de novedad: qué materiales/PT exige la operación y qué
    lotes están disponibles para vincular a cada uno (stock activo > 0)."""
    oo = query("SELECT * FROM orden_operaciones WHERE id=?", (ooid,), one=True)
    if not oo:
        return jsonify({"error": "Operación no encontrada"}), 404
    if not oo["proceso_op_id"]:
        return jsonify([])
    mats = query("""SELECT om.material_id, om.cantidad cantidad_unitaria, om.unidad, om.tipo,
        m.codigo, m.descripcion, m.categoria
        FROM operacion_materiales om
        JOIN materiales m ON m.id=om.material_id
        WHERE om.operacion_id=?""", (oo["proceso_op_id"],))
    out = []
    for mat in mats:
        es_insumo = mat["categoria"] in ("Insumo", "Herramienta")
        # Los insumos no llevan trazabilidad por lote: se descuentan directo
        # del stock general al completar la OT, sin pedirle al operario que
        # elija un lote acá.
        lotes = [] if es_insumo else query("""SELECT l.id, l.numero,
            MAX(0, l.cantidad_activa - COALESCE(l.cantidad_reservada,0)) AS disponible_libre,
            l.referencia_proveedor, l.fecha_ingreso
            FROM lotes l
            WHERE l.material_id=? AND l.cantidad_activa > COALESCE(l.cantidad_reservada,0)
            ORDER BY l.fecha_ingreso""", (mat["material_id"],))
        # Si esta OT ya tiene un lote vinculado para este material (reservado
        # en una novedad anterior), informarlo para bloquear el selector.
        lote_vinculado = None if es_insumo else query("""
            SELECT l.id, l.numero, ol.cantidad_usada
            FROM orden_lotes ol JOIN lotes l ON l.id=ol.lote_id
            WHERE ol.orden_id=? AND ol.material_id=?""",
            (oo["orden_id"], mat["material_id"]), one=True)
        out.append({
            "material_id": mat["material_id"], "codigo": mat["codigo"],
            "descripcion": mat["descripcion"], "cantidad_unitaria": mat["cantidad_unitaria"],
            "unidad": mat["unidad"], "tipo": mat["tipo"] if "tipo" in mat.keys() else "material",
            "categoria": mat["categoria"], "requiere_lote": not es_insumo,
            "lotes": [dict(l) for l in lotes],
            "lote_vinculado": dict(lote_vinculado) if lote_vinculado else None
        })
    return jsonify(out)

# ── Lotes disponibles para un material (aprobados) ────────────────────────────
@app.route("/api/materiales/<int:mid>/lotes_aprobados")
@login_required()
def get_lotes_aprobados(mid):
    # disponible_libre = solo cantidad_activa (aprobada y no rechazada)
    # Se excluyen lotes sin stock aprobado
    rows = query("""SELECT l.id, l.numero, l.cantidad_disponible,
        l.cantidad_activa,
        MAX(0, l.cantidad_activa - COALESCE(l.cantidad_reservada,0)) AS disponible_libre,
        l.certificado, l.referencia_proveedor, l.fecha_ingreso
        FROM lotes l
        WHERE l.material_id=?
          AND l.cantidad_activa > COALESCE(l.cantidad_reservada,0)
        ORDER BY l.fecha_ingreso""", (mid,))
    return jsonify([dict(r) for r in rows])

# ── Asignar lote específico a OT ──────────────────────────────────────────────
@app.route("/api/ordenes/<int:oid>/materiales/<int:mid>/asignar_lote", methods=["POST"])
@login_required(roles=["admin","almacen","operario"])
def asignar_lote_a_ot(oid, mid):
    d = request.json
    lote_id = d.get("lote_id")
    qty     = float(d.get("cantidad", 0))
    if not lote_id or qty <= 0:
        return jsonify({"error": "lote_id y cantidad requeridos"}), 400

    lote = query("""SELECT l.* FROM lotes l
        WHERE l.id=? AND l.material_id=?""",
        (lote_id, mid), one=True)
    if not lote:
        return jsonify({"error": "Lote no encontrado para este material"}), 404

    # Disponible libre = aprobado - ya reservado para otras OTs
    reservado_actual = float(lote["cantidad_reservada"] or 0)
    disponible_libre = max(0, float(lote["cantidad_activa"] or 0) - reservado_actual)
    if disponible_libre < qty:
        return jsonify({"error": f"Stock insuficiente: disponible libre {disponible_libre} requerido {qty}"}), 400

    # Solo reservar (no descontar del stock real).
    # El descuento efectivo ocurre al completar la OT.
    execute("UPDATE lotes SET cantidad_reservada=COALESCE(cantidad_reservada,0)+? WHERE id=?",
            (qty, lote_id))

    # Update orden_materiales assigned
    execute("""UPDATE orden_materiales SET cantidad_asignada=cantidad_asignada+?
        WHERE orden_id=? AND material_id=?""", (qty, oid, mid))

    # Record in orden_lotes (sin movimiento de stock todavía)
    # Si ya existía una reserva previa de este lote para esta OT, se SUMA
    # (no se pisa), porque cantidad_reservada en el lote ya se acumula así.
    execute("""INSERT INTO orden_lotes (orden_id,lote_id,material_id,cantidad_usada,fecha)
        VALUES (?,?,?,?,date('now','localtime'))
        ON CONFLICT(orden_id,lote_id) DO UPDATE SET
            cantidad_usada=cantidad_usada+excluded.cantidad_usada,
            fecha=excluded.fecha""", (oid, lote_id, mid, qty))

    num = query("SELECT numero FROM ordenes WHERE id=?", (oid,), one=True)["numero"]
    # Movimiento de reserva (tipo 'reserva') para trazabilidad, sin impacto en stock
    execute("""INSERT INTO movimientos (material_id,lote_id,tipo,cantidad,referencia,usuario_id)
        VALUES (?,?,'reserva',?,?,?)""",
        (mid, lote_id, qty, f"Reservado para {num} | Lote {lote['numero']}", session["user_id"]))

    return jsonify({"ok": True, "lote": lote["numero"], "asignado": qty})

# ── Verificar cobertura de materiales de una OT ───────────────────────────────
@app.route("/api/ordenes/<int:oid>/materiales/alerta")
@login_required()
def alerta_materiales_ot(oid):
    mats = query("""SELECT om.material_id, om.cantidad_requerida, om.cantidad_asignada,
        m.descripcion, m.codigo, m.categoria,
        (SELECT COUNT(*) FROM lotes l WHERE l.material_id=om.material_id AND l.estado='Aprobado'
         AND l.cantidad_activa > COALESCE(l.cantidad_reservada,0)) lotes_ok
        FROM orden_materiales om JOIN materiales m ON m.id=om.material_id
        WHERE om.orden_id=?""", (oid,))
    alertas = []
    for m in mats:
        # Los insumos/herramientas no requieren asignación de lote; se descuentan al completar la OT
        if m["categoria"] in ("Insumo", "Herramienta"):
            continue
        faltante = float(m["cantidad_requerida"] or 0) - float(m["cantidad_asignada"] or 0)
        if faltante > 0:
            alertas.append({
                "material": m["codigo"] + " — " + m["descripcion"],
                "faltante": faltante,
                "hay_lotes_aprobados": bool(m["lotes_ok"]),
            })
    return jsonify({"alertas": alertas, "ok": len(alertas) == 0})

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
        pct = min(100, round(float(entregado) / float(item["cantidad"]) * 100)) if item["cantidad"] else 0
        d = dict(item)
        d["entregado"] = float(entregado)
        d["pct_entrega"] = pct
        d["remitos"] = remitos
        result.append(d)
    # Overall OC progress
    total_req = sum(float(i["cantidad"]) for i in items)
    total_ent = sum(r["entregado"] for r in result)
    pct_total = min(100, round(total_ent / total_req * 100)) if total_req else 0
    return jsonify({"items": result, "pct_total": pct_total,
                    "total_requerido": total_req, "total_entregado": total_ent})

# ── Permisos de usuario ───────────────────────────────────────────────────────
@app.route("/api/usuarios/<int:uid>/permisos", methods=["GET"])
@login_required(roles=["admin"])
def get_permisos(uid):
    rows = query("SELECT * FROM usuario_permisos WHERE usuario_id=?", (uid,))
    perms = {r["clave"]: r["valor"] for r in rows}
    return jsonify(perms)

@app.route("/api/usuarios/<int:uid>/permisos", methods=["POST"])
@login_required(roles=["admin"])
def save_permisos(uid):
    d = request.json or {}
    for clave, valor in d.items():
        execute("""INSERT INTO usuario_permisos (usuario_id,clave,valor)
            VALUES (?,?,?) ON CONFLICT(usuario_id,clave) DO UPDATE SET valor=excluded.valor""",
            (uid, clave, str(valor)))
    return jsonify({"ok": True})

# ── Empleados / RRHH ──────────────────────────────────────────────────────────
@app.route("/api/empleados", methods=["GET"])
@login_required()
def get_empleados():
    rows = query("SELECT * FROM empleados ORDER BY apellido,nombre")
    result = []
    for r in rows:
        d = dict(r)
        d["maquinas"] = [dict(x) for x in query(
            "SELECT cm.id,cm.nombre FROM empleado_maquinas em JOIN categorias_maquina cm ON cm.id=em.categoria_maquina_id WHERE em.empleado_id=?",
            (r["id"],))]
        result.append(d)
    return jsonify(result)

@app.route("/api/empleados", methods=["POST"])
@login_required(roles=["admin"])
def create_empleado():
    d = request.json
    if not d.get("legajo") or not d.get("nombre"):
        return jsonify({"error":"Legajo y nombre requeridos"}), 400
    if query("SELECT id FROM empleados WHERE legajo=?", (d["legajo"],), one=True):
        return jsonify({"error":"Legajo ya existe"}), 409
    lid = execute("INSERT INTO empleados (legajo,nombre,apellido,cargo,tipo,turno,obs) VALUES (?,?,?,?,?,?,?)",
        (d["legajo"],d["nombre"],d.get("apellido"),d.get("cargo"),d.get("tipo","Indirecto"),d.get("turno"),d.get("obs")))
    for cmid in (d.get("maquinas") or []):
        try: execute("INSERT OR IGNORE INTO empleado_maquinas (empleado_id,categoria_maquina_id) VALUES (?,?)", (lid, cmid))
        except: pass
    return jsonify({"ok":True,"id":lid}), 201

@app.route("/api/empleados/<int:eid>", methods=["PUT"])
@login_required(roles=["admin"])
def update_empleado(eid):
    d = request.json
    if d.get("legajo"):
        dup = query("SELECT id FROM empleados WHERE legajo=? AND id!=?", (d["legajo"], eid), one=True)
        if dup:
            return jsonify({"error":"Legajo ya existe"}), 409
    execute("UPDATE empleados SET legajo=?,nombre=?,apellido=?,cargo=?,tipo=?,turno=?,activo=?,obs=? WHERE id=?",
        (d.get("legajo"),d["nombre"],d["apellido"],d.get("cargo"),d.get("tipo","Indirecto"),d.get("turno"),
         1 if d.get("activo",True) else 0,d.get("obs"),eid))
    execute("DELETE FROM empleado_maquinas WHERE empleado_id=?", (eid,))
    for cmid in (d.get("maquinas") or []):
        try: execute("INSERT OR IGNORE INTO empleado_maquinas (empleado_id,categoria_maquina_id) VALUES (?,?)", (eid, cmid))
        except: pass
    return jsonify({"ok":True})

# ── Ordenes de cliente (comercial) ────────────────────────────────────────────
@app.route("/api/ordenes_cliente", methods=["GET"])
@login_required()
def get_ordenes_cliente():
    cid = request.args.get("cliente_id")
    sql = "SELECT oc.*,c.razon cliente_nombre FROM ordenes_cliente oc JOIN clientes c ON c.id=oc.cliente_id"
    rows = query(sql+" WHERE oc.cliente_id=? ORDER BY oc.id DESC",(cid,)) if cid else query(sql+" ORDER BY oc.id DESC")
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
        # Avance real de entrega: lo remitido sobre lo pedido (no "OT generada").
        total_req = sum(float(i["cantidad"]) for i in d["items"])
        total_ent = float(query("""SELECT COALESCE(SUM(ri.cantidad),0) total
            FROM remito_items ri
            JOIN remitos rem ON rem.id=ri.remito_id
            JOIN ordenes_cliente_items oci ON oci.id=ri.orden_cliente_item_id
            WHERE oci.orden_cliente_id=? AND rem.estado!='Anulado'""",
            (r["id"],), one=True)["total"])
        d["entregado"] = total_ent
        d["pct_entrega"] = min(100, round(total_ent/total_req*100)) if total_req else 0
        result.append(d)
    return jsonify(result)

@app.route("/api/ordenes_cliente", methods=["POST"])
@login_required(roles=["admin","vendedor"])
def create_orden_cliente():
    d = request.json
    if not d.get("cliente_id") or not d.get("items"):
        return jsonify({"error":"Cliente e ítems requeridos"}), 400
    # Generar número automático solo a partir de los que ya tienen el
    # formato OC-CLI-####, ignorando números manuales con otro formato
    # (p.ej. "oc-2026", "OC-2026-0005") que rompían el cálculo por-1 y
    # podían generar un número ya usado (UNIQUE constraint failed).
    ultimos = query("SELECT numero FROM ordenes_cliente WHERE numero LIKE 'OC-CLI-%' ORDER BY id DESC")
    n = 1
    for r in ultimos:
        try:
            n = int(r["numero"].split("-")[-1]) + 1
            break
        except (ValueError, IndexError):
            continue
    numero = d.get("numero_oc") or f"OC-CLI-{n:04d}"
    # Check duplicate numero (también cubre el autogenerado: si por algún
    # motivo ya existe, se sigue incrementando hasta encontrar uno libre)
    if not d.get("numero_oc"):
        while query("SELECT id FROM ordenes_cliente WHERE numero=?", (numero,), one=True):
            n += 1
            numero = f"OC-CLI-{n:04d}"
    elif query("SELECT id FROM ordenes_cliente WHERE numero=?", (numero,), one=True):
        return jsonify({"error": f"El número {numero} ya existe"}), 409
    lid = execute("INSERT INTO ordenes_cliente (numero,cliente_id,fecha_entrega,estado,obs) VALUES (?,?,?,?,?)",
        (numero, d["cliente_id"], d.get("fecha_entrega"), d.get("estado","Recibida"), d.get("obs")))
    for item in d["items"]:
        if item.get("producto_id") and item.get("cantidad"):
            execute("""INSERT INTO ordenes_cliente_items
                (orden_cliente_id,producto_id,cantidad,precio_unit,fecha_deseada,obs)
                VALUES (?,?,?,?,?,?)""",
                (lid, item["producto_id"], item["cantidad"],
                 item.get("precio_unit",0), item.get("fecha_deseada"), item.get("obs")))
    return jsonify({"ok":True,"id":lid,"numero":numero}), 201




def _recalcular_tiempo_total_producto(prod_id):
    """Recalcula tiempo_total_hs de un producto sumando el tiempo de cada paso
    (orden). Si un paso tiene rutas alternativas (mismo número de orden, p.ej.
    2 procesos posibles para el mismo paso), se toma la más rápida como
    estimación — la ruta realmente usada se elige en Control de producción."""
    tot = query("""SELECT COALESCE(SUM(t),0) total FROM (
        SELECT MIN(tiempo_setup_min+tiempo_ciclo_min) t
        FROM proceso_operaciones WHERE producto_id=? GROUP BY orden)""",
        (prod_id,), one=True)["total"]
    execute("UPDATE productos SET tiempo_total_hs=? WHERE id=?", (round(tot/60,2), prod_id))

def calcular_tiempo_ciclo_total(prod_id, qty=1.0, _visitados=None):
    """Suma tiempo_ciclo_min de todas las operaciones (sin setup), recursivo.
    Si un material es un PT con proceso, suma también su tiempo de fabricación."""
    if _visitados is None:
        _visitados = set()
    if prod_id in _visitados:
        return 0.0
    _visitados.add(prod_id)

    # Tiempo de ciclo propio (si un paso tiene rutas alternativas con el
    # mismo número de orden, se toma la más rápida como estimación)
    ops = query("""SELECT COALESCE(SUM(t),0) s FROM (
        SELECT MIN(tiempo_ciclo_min) t FROM proceso_operaciones
        WHERE producto_id=? GROUP BY orden)""",
        (prod_id,), one=True)
    total = float(ops["s"] or 0) * qty

    # Tiempo de sub-productos (materiales que son PT)
    mats = query("""SELECT om.material_id, SUM(om.cantidad)*? AS total_cant,
        m.categoria, m.codigo
        FROM proceso_operaciones po
        JOIN operacion_materiales om ON om.operacion_id=po.id
        JOIN materiales m ON m.id=om.material_id
        WHERE po.producto_id=?
        GROUP BY om.material_id""", (qty, prod_id))

    for m in mats:
        if m["categoria"] == "Producto terminado":
            sub = query("SELECT id FROM productos WHERE codigo=? AND activo=1",
                        (m["codigo"],), one=True)
            if sub:
                total += calcular_tiempo_ciclo_total(
                    sub["id"], float(m["total_cant"] or 0), _visitados)
    return total

def calcular_costo_producto(prod_id, qty=1.0, _visitados=None):
    """Calcula costo_mat de un producto recursivamente.
    Si un material es un Producto terminado con proceso definido,
    su costo = costo de fabricarlo (materiales de sus operaciones)."""
    if _visitados is None:
        _visitados = set()
    if prod_id in _visitados:   # evitar ciclos
        return 0.0
    _visitados.add(prod_id)

    mats = query("""SELECT om.material_id, SUM(om.cantidad)*? AS total_cant,
        m.precio_unit, m.categoria, m.codigo
        FROM proceso_operaciones po
        JOIN operacion_materiales om ON om.operacion_id=po.id
        JOIN materiales m ON m.id=om.material_id
        WHERE po.producto_id=?
        GROUP BY om.material_id""", (qty, prod_id))

    costo_total = 0.0
    for m in mats:
        cant = float(m["total_cant"] or 0)
        if m["categoria"] == "Producto terminado":
            # Buscar si este PT tiene un producto-proceso definido
            sub_prod = query(
                "SELECT id FROM productos WHERE codigo=? AND activo=1",
                (m["codigo"],), one=True)
            if sub_prod:
                costo_total += calcular_costo_producto(sub_prod["id"], cant, _visitados)
                continue
        costo_total += float(m["precio_unit"] or 0) * cant
    return costo_total


def explotar_multinivel(prod_id, qty, cliente_id, fecha_entrega_padre, oc_numero,
                        nivel=0, _ots=None, _visitados=None):
    """Genera OT para prod_id y, recursivamente, OTs hijas para cada sub-producto
    que sea Producto terminado con proceso propio.
    Retorna (ot_id_padre, lista_de_ots_creadas)."""
    from datetime import datetime, timedelta
    import math
    if _ots is None: _ots = []
    if _visitados is None: _visitados = set()
    if prod_id in _visitados:
        return None, _ots
    _visitados.add(prod_id)

    prod = query("SELECT * FROM productos WHERE id=?", (prod_id,), one=True)
    if not prod:
        return None, _ots

    # Costo y tiempo
    costo_mat = calcular_costo_producto(prod_id, qty)
    ops_proc = query("SELECT * FROM proceso_operaciones WHERE producto_id=? ORDER BY CAST(orden AS INTEGER), orden",
                     (prod_id,))
    tiempo_std_min = sum(
        (op["tiempo_setup_min"] or 0) + (op["tiempo_ciclo_min"] or 0) * qty
        for op in ops_proc
    )
    dias_necesarios = max(1, math.ceil(tiempo_std_min / 480))
    if nivel == 0:
        fecha_ot = fecha_entrega_padre
    else:
        # Sub-OT necesita terminar antes que la padre
        try:
            fecha_padre_dt = datetime.strptime(fecha_entrega_padre, "%Y-%m-%d")
            fecha_ot = (fecha_padre_dt - timedelta(days=dias_necesarios + 1)).strftime("%Y-%m-%d")
        except Exception:
            fecha_ot = fecha_entrega_padre

    # Número OT
    last_ot = query("SELECT numero FROM ordenes ORDER BY id DESC LIMIT 1", one=True)
    try: n = int(last_ot["numero"].split("-")[1]) + 1 if last_ot else 1
    except: n = 1
    numero_ot = f"OT-{n:03d}"

    prefijo = "  " * nivel
    obs = f"{prefijo}Generada desde OC {oc_numero}" + (f" | Sub-producto niv.{nivel}" if nivel > 0 else "")

    ot_id = execute("""INSERT INTO ordenes
        (numero,cliente_id,producto_id,descripcion,cantidad,prioridad,estado,
         fecha_entrega,costo_mat,costo_mo,precio_venta,obs)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (numero_ot, cliente_id, prod_id,
         f"{prod['codigo']} — {prod['nombre']}",
         qty, "Normal", "Pendiente",
         fecha_ot, round(costo_mat, 2), round(tiempo_std_min, 0),
         float(prod["precio_venta"] or 0), obs))

    # Operaciones
    for op in ops_proc:
        execute("""INSERT INTO orden_operaciones
            (orden_id,proceso_op_id,orden,nombre,categoria_maquina_id,maquina_id,
             tiempo_setup_min,tiempo_ciclo_min,estado,qty_requerida,
             es_tercerizada,proveedor_id,precio_tercerizado,tiempo_minimo_dias)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (ot_id, op["id"], op["orden"], op["nombre"],
             op["categoria_maquina_id"], op["maquina_id"],
             op["tiempo_setup_min"], op["tiempo_ciclo_min"],
             "Pendiente", qty,
             op["es_tercerizada"] if "es_tercerizada" in op.keys() else 0,
             op["proveedor_id"] if "proveedor_id" in op.keys() else None,
             op["precio_tercerizado"] if "precio_tercerizado" in op.keys() else 0,
             op["tiempo_minimo_dias"] if "tiempo_minimo_dias" in op.keys() else 0))

    # Materiales — separar simples de sub-productos
    mats = query("""SELECT om.material_id, SUM(om.cantidad)*? AS total_cant,
        m.unidad, m.precio_unit, m.categoria, m.codigo
        FROM proceso_operaciones po
        JOIN operacion_materiales om ON om.operacion_id=po.id
        JOIN materiales m ON m.id=om.material_id
        WHERE po.producto_id=?
        GROUP BY om.material_id""", (qty, prod_id))

    for mat in mats:
        cant = float(mat["total_cant"] or 0)
        # Registrar el material en la OT (siempre, independientemente de si es sub-prod)
        execute("""INSERT INTO orden_materiales
            (orden_id,material_id,cantidad_requerida,cantidad_asignada,unidad)
            VALUES (?,?,?,0,?)""",
            (ot_id, mat["material_id"], cant, mat["unidad"]))

        # Si es PT con proceso propio → generar OT hija recursivamente
        if mat["categoria"] == "Producto terminado":
            sub_prod = query(
                """SELECT p.id FROM productos p
                   JOIN proceso_operaciones po ON po.producto_id=p.id
                   WHERE p.codigo=? AND p.activo=1
                   LIMIT 1""",
                (mat["codigo"],), one=True)
            if sub_prod:
                sub_ot_id, _ots = explotar_multinivel(
                    sub_prod["id"], cant, cliente_id, fecha_ot,
                    oc_numero, nivel + 1, _ots, _visitados)

    _generar_sc_tercerizado(ot_id, numero_ot)

    _ots.append({
        "item": prod["nombre"],
        "cantidad": qty,
        "ot_numero": numero_ot,
        "ot_id": ot_id,
        "fecha_entrega": fecha_ot,
        "nivel": nivel,
        "costo_mat": round(costo_mat, 2),
    })
    return ot_id, _ots

@app.route("/api/ordenes_cliente/<int:ocid>/explotar", methods=["POST"])
@login_required(roles=["admin","vendedor","operario"])
def explotar_orden_cliente(ocid):
    """Genera OTs para cada ítem de la OC con explosión multinivel:
    si un material es un Producto terminado con proceso propio, genera OTs hijas."""
    from datetime import datetime, timedelta
    import math

    oc = query("SELECT * FROM ordenes_cliente WHERE id=?", (ocid,), one=True)
    if not oc: return jsonify({"error":"OC no encontrada"}), 404
    if oc["estado"] == "En proceso":
        return jsonify({"error":"Esta OC ya fue explotada"}), 409

    items = query("""SELECT i.*,p.nombre prod_nombre,p.codigo prod_codigo,
        p.tiempo_total_hs,p.costo_mat,p.precio_venta
        FROM ordenes_cliente_items i
        JOIN productos p ON p.id=i.producto_id
        WHERE i.orden_cliente_id=?""", (ocid,))

    if not items: return jsonify({"error":"La OC no tiene ítems"}), 400

    hoy = datetime.now()
    ots_todas = []

    for item in items:
        if item["ot_id"]:
            continue

        # Fecha entrega del nivel 0
        tiempo_hs = float(item["tiempo_total_hs"] or 1)
        dias_necesarios = math.ceil(tiempo_hs * float(item["cantidad"]) / 8)
        fecha_entrega = item["fecha_deseada"] or             (hoy + timedelta(days=max(dias_necesarios, 1))).strftime("%Y-%m-%d")

        # Explosión multinivel recursiva
        ot_id, ots_item = explotar_multinivel(
            item["producto_id"], float(item["cantidad"]),
            oc["cliente_id"], fecha_entrega, oc["numero"])

        if ot_id:
            execute("UPDATE ordenes_cliente_items SET ot_id=? WHERE id=?",
                    (ot_id, item["id"]))

        ots_todas.extend(ots_item)

    execute("UPDATE ordenes_cliente SET estado='En proceso' WHERE id=?", (ocid,))
    return jsonify({"ok": True, "ots": ots_todas})

@app.route("/api/ordenes_cliente/<int:ocid>", methods=["PUT"])
@login_required(roles=["admin","vendedor"])
def update_orden_cliente(ocid):
    d = request.json
    execute("UPDATE ordenes_cliente SET estado=?,fecha_entrega=?,obs=? WHERE id=?",
        (d.get("estado"), d.get("fecha_entrega"), d.get("obs"), ocid))
    # Update items if provided (only items without OTs assigned)
    if "items" in d:
        execute("DELETE FROM ordenes_cliente_items WHERE orden_cliente_id=? AND (ot_id IS NULL OR ot_id=0)", (ocid,))
        for item in (d["items"] or []):
            if item.get("producto_id") and item.get("cantidad"):
                execute("""INSERT INTO ordenes_cliente_items
                    (orden_cliente_id,producto_id,cantidad,precio_unit,fecha_deseada,obs)
                    VALUES (?,?,?,?,?,?)""",
                    (ocid, item["producto_id"], item["cantidad"],
                     item.get("precio_unit",0), item.get("fecha_deseada"), item.get("obs")))
    return jsonify({"ok":True})

# ── MRP ampliado: consolidar OC-cliente → generar OTs ────────────────────────
@app.route("/api/mrp/consolidar", methods=["POST"])
@login_required(roles=["admin","operario"])
def mrp_consolidar():
    d = request.json
    oc_ids = d.get("oc_ids", [])
    if not oc_ids: return jsonify({"error":"Seleccioná al menos una OC de cliente"}), 400
    placeholders = ",".join("?" * len(oc_ids))
    items = query(f"""SELECT i.producto_id,SUM(i.cantidad) AS total_qty,
        p.nombre producto_nombre,p.codigo,p.costo_mat,p.costo_mo,p.precio_venta,
        MAX(oc.cliente_id) cliente_id,
        COALESCE(i.fecha_deseada, MAX(oc.fecha_entrega)) fecha_entrega,
        GROUP_CONCAT(i.id) AS item_ids
        FROM ordenes_cliente_items i
        JOIN ordenes_cliente oc ON oc.id=i.orden_cliente_id
        JOIN productos p ON p.id=i.producto_id
        WHERE oc.id IN ({placeholders}) AND (i.ot_id IS NULL OR i.ot_id=0)
        GROUP BY i.producto_id, i.fecha_deseada""", oc_ids)
    ots_creadas = []
    for item in items:
        last = query("SELECT numero FROM ordenes ORDER BY id DESC LIMIT 1", one=True)
        try: n = int(last["numero"].split("-")[1])+1 if last else 1
        except: n = 1
        numero = f"OT-{n:03d}"

        # Calcular tiempo estándar (min) en base a las operaciones del proceso,
        # igual que en explotar_multinivel, en vez de copiar costo_mo del producto.
        ops_proc_item = query(
            "SELECT * FROM proceso_operaciones WHERE producto_id=? ORDER BY CAST(orden AS INTEGER), orden",
            (item["producto_id"],))
        tiempo_std_min = sum(
            (op["tiempo_setup_min"] or 0) + (op["tiempo_ciclo_min"] or 0) * item["total_qty"]
            for op in ops_proc_item
        )

        # Costo de materiales: se calcula dinámicamente en base a la receta
        # actual del producto (igual que en explotar_multinivel / calcular_costo_producto),
        # en vez de usar productos.costo_mat, que es un valor estático que puede
        # estar desactualizado o en 0 si nunca se recalculó a mano.
        costo_mat_item = calcular_costo_producto(item["producto_id"], item["total_qty"])

        oid = execute("""INSERT INTO ordenes
            (numero,cliente_id,producto_id,descripcion,cantidad,prioridad,estado,fecha_entrega,costo_mat,costo_mo,precio_venta)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (numero,item["cliente_id"],item["producto_id"],
             f"Fabricación {item['producto_nombre']} — generado por MRP",
             item["total_qty"],"Normal","Pendiente",item["fecha_entrega"],
             round(costo_mat_item, 2),round(tiempo_std_min, 0),item["precio_venta"]))
        populate_ops_internal(oid, item["producto_id"], item["total_qty"])
        populate_mats_internal(oid, item["producto_id"], item["total_qty"])
        # Vincular esta OT a los renglones de OC que la originaron
        # (para que "Remitir a cliente" pueda cruzar PT → OC)
        if item["item_ids"]:
            item_id_list = [int(x) for x in str(item["item_ids"]).split(",") if x]
            if item_id_list:
                ph_items = ",".join("?" * len(item_id_list))
                execute(f"UPDATE ordenes_cliente_items SET ot_id=? WHERE id IN ({ph_items})",
                        [oid] + item_id_list)
        # ── Generate OTTs for tercerized operations ───────────────────────
        terc_ops = query("""SELECT po.*, oo.id oo_id,
            (SELECT MAX(CAST(orden AS INTEGER)) FROM proceso_operaciones WHERE producto_id=po.producto_id) max_orden
            FROM proceso_operaciones po
            JOIN orden_operaciones oo ON oo.proceso_op_id=po.id AND oo.orden_id=?
            WHERE po.producto_id=? AND po.es_tercerizada=1""",
            (oid, item["producto_id"]))
        for top in terc_ops:
            last_ott = query("SELECT numero FROM ordenes_tercerizado ORDER BY id DESC LIMIT 1", one=True)
            try: no = int(last_ott["numero"].split("-")[1])+1 if last_ott else 1
            except: no = 1
            num_ott = f"OTT-{no:04d}"
            es_ult = 1 if top["orden"] == top["max_orden"] else 0
            ott_id = execute("""INSERT INTO ordenes_tercerizado
                (numero,ot_origen_id,operacion_id,proceso_op_id,proveedor_id,
                 precio_acordado,estado,es_ultimo_nivel,creado_por)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (num_ott, oid, top["oo_id"], top["id"],
                 top["proveedor_id"] if "proveedor_id" in top.keys() else None,
                 top["precio_tercerizado"] if "precio_tercerizado" in top.keys() else 0,
                 "Pendiente", es_ult, session["user_id"]))
            # Generate SC for the tercerized service
            if top.get("proveedor_id"):
                last_sc = query("SELECT numero FROM solicitudes_compra ORDER BY id DESC LIMIT 1", one=True)
                try: ns = int(last_sc["numero"].split("-")[2])+1 if last_sc else 1
                except: ns = 1
                sc_num = f"SC-TERC-{ns:04d}"
                execute("""INSERT INTO solicitudes_compra
                    (numero,tipo,descripcion,cantidad,unidad,urgencia,estado,obs)
                    VALUES (?,?,?,?,?,?,?,?)""",
                    (sc_num, "Servicio",
                     f"Servicio tercerizado: {top['nombre']} — OTT {num_ott}",
                     item["total_qty"], "unid", "Alta", "Pendiente",
                     f"Generada por MRP. OT: {numero}"))
                solicitudes_creadas.append({"numero": sc_num, "material": top["nombre"], "cantidad": item["total_qty"]})
        ots_creadas.append({"numero":numero,"producto":item["producto_nombre"],"cantidad":item["total_qty"]})
    execute(f"UPDATE ordenes_cliente SET estado='En proceso' WHERE id IN ({placeholders})", oc_ids)

    # ── Material gap analysis: check stock vs all pending OTs ─────────────────
    solicitudes_creadas = []
    # Get all active OTs (including just-created) that have unassigned materials
    gap_mats = query("""
        SELECT om.material_id, m.codigo, m.descripcion, m.unidad,
               SUM(om.cantidad_requerida) AS total_req,
               SUM(COALESCE(om.cantidad_asignada,0)) AS total_asign,
               m.stock AS stock_actual
        FROM orden_materiales om
        JOIN ordenes o ON o.id=om.orden_id
        JOIN materiales m ON m.id=om.material_id
        WHERE o.estado IN ('Pendiente','En proceso')
        GROUP BY om.material_id""")
    for mat in gap_mats:
        total_req   = float(mat["total_req"] or 0)
        total_asign = float(mat["total_asign"] or 0)
        stock       = float(mat["stock_actual"] or 0)
        # Cantidad neta que falta asignar a las OTs activas (lo ya asignado
        # no vuelve a contarse). El faltante real es lo que excede al stock
        # actualmente disponible: si el stock alcanza para cubrir todo lo
        # requerido, no hay faltante; si no alcanza, la SC debe pedir
        # exactamente la diferencia (cubre al máximo con el stock existente,
        # sin sobre-pedir).
        reservado   = max(0, total_req - total_asign)
        faltante    = max(0, reservado - stock)
        if faltante > 0:
            # Si ya hay una SC abierta para este material, no duplicamos: si su
            # cantidad ya cubre el faltante actual la dejamos; si quedó corta
            # (p.ej. porque el faltante creció con esta corrida de MRP), la
            # actualizamos para que cubra el faltante real en vez de dejarla
            # desactualizada.
            sc_exist = query("""SELECT id,cantidad FROM solicitudes_compra
                WHERE material_id=? AND estado IN ('Pendiente','En evaluación')
                ORDER BY id DESC LIMIT 1""", (mat["material_id"],), one=True)
            if sc_exist:
                if float(sc_exist["cantidad"] or 0) < faltante:
                    execute("""UPDATE solicitudes_compra SET cantidad=?,
                        obs=? WHERE id=?""",
                        (round(faltante, 3),
                         f"Actualizada automáticamente por MRP. Faltante: {round(faltante,3)} {mat['unidad']}",
                         sc_exist["id"]))
                    solicitudes_creadas.append({"numero":None,"material":mat["descripcion"],"cantidad":round(faltante,3),"actualizada":True})
            else:
                last_sc = query("SELECT numero FROM solicitudes_compra ORDER BY id DESC LIMIT 1", one=True)
                try: sc_n = int(last_sc["numero"].split("-")[2])+1 if last_sc else 1
                except: sc_n = 1
                sc_num = f"SC-PROD-{sc_n:04d}"
                execute("""INSERT INTO solicitudes_compra
                    (numero,tipo,descripcion,material_id,cantidad,unidad,urgencia,estado,obs)
                    VALUES (?,?,?,?,?,?,?,?,?)""",
                    (sc_num, "Productiva",
                     f"Material requerido por MRP — {mat['descripcion']}",
                     mat["material_id"], round(faltante, 3), mat["unidad"],
                     "Alta", "Pendiente",
                     f"Generada automáticamente por MRP. Faltante: {round(faltante,3)} {mat['unidad']}"))
                solicitudes_creadas.append({"numero":sc_num,"material":mat["descripcion"],"cantidad":round(faltante,3)})
    return jsonify({"ok":True,"ots":ots_creadas,"solicitudes_compra":solicitudes_creadas})

def populate_ops_internal(oid, prod_id, qty):
    ops = query("SELECT * FROM proceso_operaciones WHERE producto_id=? ORDER BY CAST(orden AS INTEGER), orden", (prod_id,))
    for op in ops:
        execute("""INSERT INTO orden_operaciones
            (orden_id,proceso_op_id,orden,nombre,categoria_maquina_id,maquina_id,
             tiempo_setup_min,tiempo_ciclo_min,estado,qty_requerida,
             es_tercerizada,proveedor_id,precio_tercerizado,tiempo_minimo_dias)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (oid,op["id"],op["orden"],op["nombre"],op["categoria_maquina_id"],op["maquina_id"],
             op["tiempo_setup_min"],op["tiempo_ciclo_min"],"Pendiente",qty,
             op["es_tercerizada"] if "es_tercerizada" in op.keys() else 0,
             op["proveedor_id"] if "proveedor_id" in op.keys() else None,
             op["precio_tercerizado"] if "precio_tercerizado" in op.keys() else 0,
             op["tiempo_minimo_dias"] if "tiempo_minimo_dias" in op.keys() else 0))

def populate_mats_internal(oid, prod_id, qty):
    mats = query("""SELECT om.material_id,SUM(om.cantidad)*? AS total,m.unidad
        FROM proceso_operaciones po JOIN operacion_materiales om ON om.operacion_id=po.id
        JOIN materiales m ON m.id=om.material_id
        WHERE po.producto_id=? GROUP BY om.material_id""", (qty, prod_id))
    for mat in mats:
        execute("INSERT INTO orden_materiales (orden_id,material_id,cantidad_requerida,cantidad_asignada,unidad) VALUES (?,?,?,0,?)",
            (oid, mat["material_id"], mat["total"], mat["unidad"]))

# ── Novedades de producción ───────────────────────────────────────────────────
@app.route("/api/novedades/corregir_rendimiento", methods=["GET"])
@login_required(roles=["admin"])
def preview_corregir_novedades():
    """Previsualiza qué novedades cambiarían su rendimiento/desvío al
    recalcularlos usando el tiempo de ciclo que tiene la operación en SU
    propia OT (orden_operaciones.tiempo_ciclo_min) como estándar, ya que
    ese es el valor vigente para esa orden puntual (puede haber sido
    ajustado y diferir del proceso/plantilla). Solo si la OT no tiene un
    valor propio cargado (0/NULL) se recurre al de la plantilla
    (proceso_operaciones.tiempo_ciclo_min) como respaldo. No modifica nada."""
    rows = query("""
        SELECT n.id, n.numero, n.cantidad_producida, n.tiempo_real_min, n.tiempo_perdido,
               n.rendimiento_pct, n.desvio,
               COALESCE(NULLIF(oo.tiempo_ciclo_min, 0), po.tiempo_ciclo_min, 1) AS std_ciclo
        FROM novedades_produccion n
        JOIN orden_operaciones oo ON oo.id = n.orden_operacion_id
        LEFT JOIN proceso_operaciones po ON po.id = oo.proceso_op_id
        WHERE n.tiempo_real_min > 0
        ORDER BY n.id
    """)

    afectadas = []
    for r in rows:
        std_ciclo = r["std_ciclo"] or 1
        t_real = r["tiempo_real_min"]
        qty = r["cantidad_producida"]
        t_productivo = max(t_real, 0.1)
        rendimiento_nuevo = round((qty / t_productivo) / (1 / std_ciclo) * 100, 1)
        rendimiento_nuevo = min(rendimiento_nuevo, 999.9)
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
               COALESCE(NULLIF(oo.tiempo_ciclo_min, 0), po.tiempo_ciclo_min, 1) AS std_ciclo
        FROM novedades_produccion n
        JOIN orden_operaciones oo ON oo.id = n.orden_operacion_id
        LEFT JOIN proceso_operaciones po ON po.id = oo.proceso_op_id
        WHERE n.tiempo_real_min > 0
        ORDER BY n.id
    """)

    updates = []
    for r in rows:
        std_ciclo = r["std_ciclo"] or 1
        t_real = r["tiempo_real_min"]
        qty = r["cantidad_producida"]
        t_productivo = max(t_real, 0.1)
        rendimiento_nuevo = round((qty / t_productivo) / (1 / std_ciclo) * 100, 1)
        rendimiento_nuevo = min(rendimiento_nuevo, 999.9)
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
        c.razon cliente_nombre
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

    op = query("""SELECT oo.*,po.tiempo_ciclo_min std_ciclo,po.producto_id
        FROM orden_operaciones oo
        LEFT JOIN proceso_operaciones po ON po.id=oo.proceso_op_id
        WHERE oo.id=?""", (d["orden_operacion_id"],), one=True)
    if not op: return jsonify({"error":"Operación no encontrada"}), 404

    # ── Si la operación está marcada como "Completada", no se pueden cargar
    # más novedades. Si el usuario la volvió a poner "En proceso" manualmente
    # (por ejemplo desde Control de Producción) después de haber llegado al
    # 100%, se le permite seguir cargando novedades: el bloqueo es por
    # ESTADO, no por haber alcanzado la cantidad requerida. Solo se vuelve a
    # bloquear cuando el usuario la marca Completada de nuevo (manual o
    # automáticamente al llegar al 100%). ───────────────────────────────────
    qty_req_op = float(op["qty_requerida"] or 0)
    qty_prod_op = float(op["qty_producida"] or 0)
    if op["estado"] == "Completada":
        return jsonify({"error": "No se puede cargar más novedades: la operación ya está marcada como Completada (%s/%s piezas). Volvé a ponerla en proceso para seguir cargando." % (qty_prod_op, qty_req_op)}), 400

    std_ciclo = op["tiempo_ciclo_min"] or op["std_ciclo"] or 1
    t_perdido = float(d.get("tiempo_perdido") or 0)
    # tiempo_real = tiempo EFECTIVAMENTE trabajado (ya neto).
    # tiempo_perdido = tiempo aparte que no se trabajó (no está incluido en tiempo_real).
    # Por lo tanto el rendimiento se calcula sobre tiempo_real solo, sin restar nada.
    t_productivo = max(t_real, 0.1)
    rendimiento = round((qty / t_productivo) / (1 / std_ciclo) * 100, 1)
    rendimiento = min(rendimiento, 999.9)
    desvio = 1 if rendimiento < 80 else 0

    # ── VALIDACIONES DE STOCK/LOTES: se hacen TODAS antes de insertar nada,
    # así si algo falla no queda la novedad guardada a medias (ver bug donde
    # el INSERT ocurría antes de estas validaciones y la novedad quedaba
    # creada aunque el sistema mostrara un error de stock insuficiente). ──
    mats_op = []
    insumos_op = []
    lotes_info = {}
    if op["proceso_op_id"]:
        mats_op_all = query("""SELECT om.*, m.descripcion descripcion, m.categoria categoria
            FROM operacion_materiales om JOIN materiales m ON m.id=om.material_id
            WHERE om.operacion_id=?""", (op["proceso_op_id"],))
        mats_op = [m for m in mats_op_all if m["categoria"] not in ("Insumo", "Herramienta")]
        insumos_op = [m for m in mats_op_all if m["categoria"] in ("Insumo", "Herramienta")]

        # Validar stock disponible para insumos (se descuentan recién al
        # completar la OT, pero acá se valida que alcance considerando lo
        # ya comprometido por otras operaciones/novedades de la misma OT
        # más lo que agrega esta novedad, para no permitir cargar una
        # novedad que termine consumiendo más de lo que hay en stock).
        if insumos_op:
            errores_ins = []
            for ins in insumos_op:
                consumo_incremental = ins["cantidad"] * qty
                comprometido = query("""SELECT COALESCE(SUM(om.cantidad * oo.qty_producida),0) c
                    FROM orden_operaciones oo
                    JOIN operacion_materiales om ON om.operacion_id=oo.proceso_op_id
                    WHERE oo.orden_id=? AND om.material_id=?""",
                    (d["orden_id"], ins["material_id"]), one=True)["c"] or 0
                mat_stock = query("SELECT stock FROM materiales WHERE id=?", (ins["material_id"],), one=True)
                stock_disp = float(mat_stock["stock"] or 0) if mat_stock else 0
                total_necesario = float(comprometido) + consumo_incremental
                if total_necesario > stock_disp:
                    faltante = round(total_necesario - stock_disp, 3)
                    errores_ins.append(f"Stock insuficiente de insumo \"{ins['descripcion']}\" (stock {stock_disp}, requerido {round(total_necesario,3)}, faltan {faltante})")
            if errores_ins:
                return jsonify({"error": "No se puede confirmar la novedad: " + " | ".join(errores_ins)}), 400

        if mats_op:
            errores = []
            for mat in mats_op:
                consumo = mat["cantidad"] * qty
                # Si este material ya tiene un lote vinculado a la OT (de una
                # novedad anterior o de una asignación manual desde "Lotes
                # asignados"), se sigue consumiendo de ESE MISMO lote (el
                # selector en el modal queda bloqueado en esa opción). El
                # consumo de ESTA novedad se descuenta igual, aunque el lote
                # ya estuviera vinculado antes.
                vinculo = query("""SELECT l.* FROM orden_lotes ol
                    JOIN lotes l ON l.id=ol.lote_id
                    WHERE ol.orden_id=? AND ol.material_id=?""",
                    (d["orden_id"], mat["material_id"]), one=True)
                if vinculo:
                    lote = vinculo
                else:
                    errores.append(f"Falta vincular un lote para \"{mat['descripcion'] if 'descripcion' in mat.keys() else mat['material_id']}\" — hacelo desde Órdenes de trabajo → Lotes asignados antes de declarar la novedad")
                    continue
                # Disponible: si el lote YA estaba vinculado a esta misma OT
                # (reservado de antemano para ella, ej. desde "Lotes
                # asignados" o de una novedad anterior), esa reserva es DE
                # ESTA OT y no debe restarse — sería bloquearse a sí misma.
                # Solo se descuenta cantidad_reservada cuando el lote se
                # elige recién ahora (fresco), para no pisar la reserva de
                # OTRAS órdenes que puedan estar usando el mismo lote.
                if vinculo:
                    disponible_libre = max(0, float(lote["cantidad_activa"] or 0))
                else:
                    disponible_libre = max(0, float(lote["cantidad_activa"] or 0) - float(lote["cantidad_reservada"] or 0))
                if disponible_libre < consumo:
                    errores.append(f"Stock disponible insuficiente en lote {lote['numero']} (libre {disponible_libre}, requerido {consumo})")
                    continue
                lotes_info[mat["material_id"]] = (lote, consumo)
            if errores:
                return jsonify({"error": "No se puede confirmar la novedad: " + " | ".join(errores)}), 400

    # ── Todas las validaciones pasaron: recién ahora se inserta la novedad ──
    last = query("SELECT numero FROM novedades_produccion ORDER BY id DESC LIMIT 1", one=True)
    try: n = int(last["numero"].split("-")[1])+1 if last else 1
    except: n = 1
    numero = f"NOV-{n:05d}"

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
    if (qty_req_op > 0 and (qty_prod_op + qty) >= qty_req_op - 0.0001
            and op["estado"] != "Completada" and not ya_estaba_al_100):
        execute("UPDATE orden_operaciones SET estado='Completada' WHERE id=?",
            (d["orden_operacion_id"],))

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
            lote_activo, consumo = lotes_info[mat["material_id"]]
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
            # Reflejar el consumo en orden_materiales.cantidad_asignada para
            # que la pestaña "Lotes asignados" de la OT (Órdenes de trabajo
            # -> Detalle -> Lotes asignados) muestre de inmediato que este
            # material ya fue consumido, aunque haya sido desde una novedad
            # y no desde el botón manual "Asignar lote".
            execute("""UPDATE orden_materiales SET cantidad_asignada=cantidad_asignada+?
                WHERE orden_id=? AND material_id=?""",
                (consumo, d["orden_id"], mat["material_id"]))
            # Acumular en orden_lotes la cantidad ya consumida de este lote
            # (queda como historial/trazabilidad; el descuento de stock ya
            # se aplicó arriba, no queda pendiente para la OT completada).
            existing = query("SELECT id FROM orden_lotes WHERE orden_id=? AND lote_id=?",
                (d["orden_id"], lote_activo["id"]), one=True)
            if not existing:
                execute("""INSERT INTO orden_lotes (orden_id,lote_id,material_id,cantidad_usada)
                    VALUES (?,?,?,?)""",
                    (d["orden_id"], lote_activo["id"], mat["material_id"], consumo))
            else:
                execute("UPDATE orden_lotes SET cantidad_usada=cantidad_usada+? WHERE orden_id=? AND lote_id=?",
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

    return jsonify({"ok":True,"id":lid,"numero":numero,"rendimiento_pct":rendimiento,"desvio":desvio}), 201






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
    return jsonify(dict(row))

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

    # --- Validar stock de insumos si se está aumentando la cantidad ---
    if nov["proceso_op_id"] and diff > 0:
        insumos_op = query("""SELECT om.*, m.descripcion descripcion
            FROM operacion_materiales om JOIN materiales m ON m.id=om.material_id
            WHERE om.operacion_id=? AND m.categoria IN ('Insumo','Herramienta')""", (nov["proceso_op_id"],))
        if insumos_op:
            errores_ins = []
            for ins in insumos_op:
                consumo_incremental = ins["cantidad"] * diff
                comprometido = query("""SELECT COALESCE(SUM(om.cantidad * oo.qty_producida),0) c
                    FROM orden_operaciones oo
                    JOIN operacion_materiales om ON om.operacion_id=oo.proceso_op_id
                    WHERE oo.orden_id=? AND om.material_id=?""",
                    (nov["orden_id"], ins["material_id"]), one=True)["c"] or 0
                mat_stock = query("SELECT stock FROM materiales WHERE id=?", (ins["material_id"],), one=True)
                stock_disp = float(mat_stock["stock"] or 0) if mat_stock else 0
                total_necesario = float(comprometido) + consumo_incremental
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
    if nov["proceso_op_id"] and diff != 0:
        mats_op = query("""SELECT om.*, m.categoria categoria
            FROM operacion_materiales om JOIN materiales m ON m.id=om.material_id
            WHERE om.operacion_id=?""", (nov["proceso_op_id"],))
        for mat in mats_op:
            if mat["categoria"] in ("Insumo", "Herramienta"):
                continue  # los insumos/herramientas se calculan/descuentan recién al completar la OT
            consumo_diff = mat["cantidad"] * diff  # + = se consume más, - = se devuelve stock
            lote_ref = query("""SELECT ol.lote_id, l.numero FROM orden_lotes ol
                JOIN lotes l ON l.id=ol.lote_id
                WHERE ol.orden_id=? AND ol.material_id=? LIMIT 1""",
                (nov["orden_id"], mat["material_id"]), one=True)
            if not lote_ref:
                continue  # no había lote vinculado para este material en esta OT
            # Si aumenta la cantidad producida (consumo_diff > 0): descontar
            # más stock/lote. Si disminuye (consumo_diff < 0): devolver stock
            # al lote y al stock general.
            execute("""UPDATE lotes SET
                    cantidad_disponible=MAX(0, cantidad_disponible-?),
                    cantidad_activa=MAX(0, cantidad_activa-?),
                    estado=CASE WHEN cantidad_disponible-? <= 0 THEN 'Agotado' ELSE estado END
                WHERE id=?""", (consumo_diff, consumo_diff, consumo_diff, lote_ref["lote_id"]))
            execute("""UPDATE materiales SET stock=MAX(0, stock-?), actualizado=datetime('now','localtime')
                WHERE id=?""", (consumo_diff, mat["material_id"]))
            execute("UPDATE orden_lotes SET cantidad_usada=MAX(0,cantidad_usada+?) WHERE orden_id=? AND lote_id=?",
                    (consumo_diff, nov["orden_id"], lote_ref["lote_id"]))
            # Mantener orden_materiales.cantidad_asignada en línea con el
            # consumo ajustado, para que "Lotes asignados" en el detalle de
            # la OT refleje el cambio hecho al editar la novedad.
            execute("""UPDATE orden_materiales SET cantidad_asignada=MAX(0,cantidad_asignada+?)
                WHERE orden_id=? AND material_id=?""",
                (consumo_diff, nov["orden_id"], mat["material_id"]))
            tipo_mov = "salida" if consumo_diff > 0 else "entrada"
            execute("INSERT INTO movimientos (material_id,lote_id,tipo,cantidad,referencia,usuario_id) VALUES (?,?,?,?,?,?)",
                    (mat["material_id"], lote_ref["lote_id"], tipo_mov, abs(consumo_diff),
                     f"Ajuste consumo {nov['numero']} — Lote {lote_ref['numero']}", session["user_id"]))

    # --- Ajustar qty_producida en orden_operacion ---
    execute("UPDATE orden_operaciones SET qty_producida=MAX(0,qty_producida+?) WHERE id=?",
            (diff, nov["orden_operacion_id"]))

    # --- Sincronizar estado con el 100%: si al editar la novedad la
    # operación pasa a tener 100% o más, se marca "Completada"; si al
    # editarla (achicando la cantidad) queda por debajo del 100% y estaba
    # marcada como Completada, se vuelve a "En proceso" para no dejarla
    # marcada como terminada sin estarlo. No se toca si el estado fue
    # cambiado manualmente a algo distinto de estos dos. ────────────────────
    oo_now = query("SELECT qty_requerida,qty_producida,estado FROM orden_operaciones WHERE id=?",
        (nov["orden_operacion_id"],), one=True)
    if oo_now:
        qty_req_now = float(oo_now["qty_requerida"] or 0)
        qty_prod_now = float(oo_now["qty_producida"] or 0)
        if qty_req_now > 0:
            if qty_prod_now >= qty_req_now - 0.0001 and oo_now["estado"] != "Completada":
                execute("UPDATE orden_operaciones SET estado='Completada' WHERE id=?",
                    (nov["orden_operacion_id"],))
            elif qty_prod_now < qty_req_now - 0.0001 and oo_now["estado"] == "Completada":
                execute("UPDATE orden_operaciones SET estado='En proceso' WHERE id=?",
                    (nov["orden_operacion_id"],))

    # --- Ajustar stock PT si es ultima operacion ---
    max_ord = query("SELECT MAX(CAST(orden AS INTEGER)) mo FROM orden_operaciones WHERE orden_id=?",
                    (nov["orden_id"],), one=True)["mo"]
    if nov["orden"] == max_ord and diff != 0 and nov["producto_id"]:
        prod = query("SELECT * FROM productos WHERE id=?", (nov["producto_id"],), one=True)
        if prod:
            mat_pt = get_or_create_pt_material(prod)
            tipo_pt = "entrada" if diff > 0 else "salida"
            execute("UPDATE materiales SET stock=MAX(0,stock+?),actualizado=datetime('now','localtime') WHERE id=?",
                    (diff, mat_pt["id"]))
            execute("INSERT INTO movimientos (material_id,tipo,cantidad,referencia,usuario_id) VALUES (?,?,?,?,?)",
                    (mat_pt["id"], tipo_pt, abs(diff),
                     f"Ajuste PT {nov['numero']}", session["user_id"]))

    # --- Recalcular rendimiento ---
    std = float(nov["tiempo_ciclo_min"] if hasattr(nov,"tiempo_ciclo_min") else 1) or 1
    op_std = query("SELECT tiempo_ciclo_min FROM proceso_operaciones WHERE id=?",
                   (nov["proceso_op_id"],), one=True) if nov["proceso_op_id"] else None
    ciclo = float(op_std["tiempo_ciclo_min"] or 1) if op_std else 1
    t_perd_new = float(d.get("tiempo_perdido", nov["tiempo_perdido"] if "tiempo_perdido" in nov.keys() else 0) or 0)
    # tiempo_real ya es tiempo neto trabajado; tiempo_perdido es aparte, no se resta.
    t_prod_new = max(t_new, 0.1) if t_new > 0 else 0.1
    rendimiento = round((qty_new / t_prod_new) / (1 / ciclo) * 100, 1) if t_new > 0 else 0
    rendimiento = min(rendimiento, 999.9)
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
                    "desvio": desvio, "ajuste_stock": diff != 0})

@app.route("/api/novedades/<int:nid>", methods=["DELETE"])
@login_required(roles=["admin","operario"])
def delete_novedad(nid):
    """Elimina una novedad y revierte todos sus efectos en stock."""
    nov = query("""SELECT n.*,oo.proceso_op_id,oo.orden,oo.orden_id,o.producto_id
        FROM novedades_produccion n
        JOIN orden_operaciones oo ON oo.id=n.orden_operacion_id
        JOIN ordenes o ON o.id=n.orden_id
        WHERE n.id=?""", (nid,), one=True)
    if not nov: return jsonify({"error":"Novedad no encontrada"}), 404

    qty = float(nov["cantidad_producida"])

    # --- Devolver el CONSUMO REAL de materias primas al stock/lote ---
    # Desde que el material se descuenta al declarar la novedad (ver
    # create_novedad), eliminarla debe devolver ese stock ya consumido.
    if nov["proceso_op_id"]:
        mats_op = query("""SELECT om.*, m.categoria categoria
            FROM operacion_materiales om JOIN materiales m ON m.id=om.material_id
            WHERE om.operacion_id=?""", (nov["proceso_op_id"],))
        for mat in mats_op:
            if mat["categoria"] in ("Insumo", "Herramienta"):
                continue
            consumo = mat["cantidad"] * qty
            lote_ref = query("""SELECT ol.lote_id, l.numero FROM orden_lotes ol
                JOIN lotes l ON l.id=ol.lote_id
                WHERE ol.orden_id=? AND ol.material_id=? LIMIT 1""",
                (nov["orden_id"], mat["material_id"]), one=True)
            if not lote_ref:
                continue
            execute("""UPDATE lotes SET
                    cantidad_disponible=cantidad_disponible+?,
                    cantidad_activa=cantidad_activa+?,
                    estado=CASE WHEN estado='Agotado' AND cantidad_disponible+?>0 THEN 'Aprobado' ELSE estado END
                WHERE id=?""", (consumo, consumo, consumo, lote_ref["lote_id"]))
            execute("""UPDATE materiales SET stock=stock+?, actualizado=datetime('now','localtime')
                WHERE id=?""", (consumo, mat["material_id"]))
            execute("UPDATE orden_lotes SET cantidad_usada=MAX(0,cantidad_usada-?) WHERE orden_id=? AND lote_id=?",
                    (consumo, nov["orden_id"], lote_ref["lote_id"]))
            # Liberar también lo reflejado en orden_materiales.cantidad_asignada
            # para que "Lotes asignados" no siga mostrando el material como
            # consumido una vez eliminada la novedad que lo descontó.
            execute("""UPDATE orden_materiales SET cantidad_asignada=MAX(0,cantidad_asignada-?)
                WHERE orden_id=? AND material_id=?""",
                (consumo, nov["orden_id"], mat["material_id"]))
            execute("INSERT INTO movimientos (material_id,lote_id,tipo,cantidad,referencia,usuario_id) VALUES (?,?,?,?,?,?)",
                    (mat["material_id"], lote_ref["lote_id"], "entrada", consumo,
                     f"Reversa {nov['numero']} — devuelve consumo Lote {lote_ref['numero']}", session["user_id"]))

    # --- Revertir qty_producida en orden_operacion ---
    execute("UPDATE orden_operaciones SET qty_producida=MAX(0,qty_producida-?) WHERE id=?",
            (qty, nov["orden_operacion_id"]))

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
            mat_pt = query("SELECT id FROM materiales WHERE codigo=? AND categoria='Producto terminado'",
                           (prod["codigo"],), one=True)
            if mat_pt:
                execute("UPDATE materiales SET stock=MAX(0,stock-?),actualizado=datetime('now','localtime') WHERE id=?",
                        (qty, mat_pt["id"]))
                execute("INSERT INTO movimientos (material_id,tipo,cantidad,referencia,usuario_id) VALUES (?,?,?,?,?)",
                        (mat_pt["id"], "salida", qty,
                         f"Reversa PT {nov['numero']}", session["user_id"]))

    execute("DELETE FROM novedades_produccion WHERE id=?", (nid,))
    return jsonify({"ok": True})


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

    last = query("SELECT numero FROM trabajo_no_productivo ORDER BY id DESC LIMIT 1", one=True)
    try: n = int(last["numero"].split("-")[1])+1 if last else 1
    except: n = 1
    numero = f"TNP-{n:05d}"

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


# ── Lotes ─────────────────────────────────────────────────────────────────────
def _gen_lote_numero():
    """Genera número de lote correlativo por año: LOTE-2026-0001"""
    from datetime import datetime
    year = datetime.now().year
    last = query(
        "SELECT numero FROM lotes WHERE numero LIKE ? ORDER BY id DESC LIMIT 1",
        (f"LOTE-{year}-%",), one=True)
    if last:
        try: n = int(last["numero"].split("-")[2]) + 1
        except: n = 1
    else:
        n = 1
    return f"LOTE-{year}-{n:04d}"

@app.route("/api/lotes", methods=["GET"])
@login_required()
def get_lotes():
    material_id = request.args.get("material_id")
    estado = request.args.get("estado")
    proveedor_id = request.args.get("proveedor_id")
    cliente_id = request.args.get("cliente_id")
    sql = """SELECT l.*,m.codigo mat_codigo,m.descripcion mat_descripcion,m.unidad,
        m.categoria,
        MAX(0, l.cantidad_activa - COALESCE(l.cantidad_reservada,0)) AS disponible_libre,
        p.razon proveedor_nombre, u.nombre creado_por_nombre,
        cl.id cliente_id, cl.razon cliente_nombre
        FROM lotes l
        JOIN materiales m ON m.id=l.material_id
        LEFT JOIN proveedores p ON p.id=l.proveedor_id
        LEFT JOIN usuarios u ON u.id=l.creado_por
        LEFT JOIN productos pr2 ON pr2.id=m.producto_id
        LEFT JOIN clientes cl ON cl.id=pr2.cliente_id"""
    conds, params = [], []
    if material_id:
        conds.append("l.material_id=?"); params.append(material_id)
    if estado:
        conds.append("l.estado=?"); params.append(estado)
    elif "estado" not in request.args:
        # Exclude Agotado only when no estado filter is set at all (default view)
        # When cliente sends ?estado= (Todos los estados), show everything including Agotado
        conds.append("l.estado != 'Agotado'")
    if proveedor_id:
        conds.append("l.proveedor_id=?"); params.append(proveedor_id)
    if cliente_id:
        conds.append("cl.id=?"); params.append(cliente_id)
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    sql += " ORDER BY l.id DESC"
    return jsonify([dict(r) for r in query(sql, params)])

@app.route("/api/lotes", methods=["POST"])
@login_required(roles=["admin","almacen"])
def create_lote():
    d = request.json
    if not d.get("material_id") or not d.get("cantidad"):
        return jsonify({"error": "Material y cantidad requeridos"}), 400
    mat = query("SELECT categoria FROM materiales WHERE id=?", (d["material_id"],), one=True)
    if not mat:
        return jsonify({"error": "Material no encontrado"}), 404
    if mat["categoria"] != "Material":
        return jsonify({"error": "Solo se pueden crear lotes para artículos de categoría Material"}), 400
    numero = _gen_lote_numero()
    qty = float(d["cantidad"])
    lid = execute("""INSERT INTO lotes
        (numero,material_id,cantidad_original,cantidad_disponible,proveedor_id,
         referencia_proveedor,certificado,estado,obs,creado_por)
        VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (numero, d["material_id"], qty, qty,
         d.get("proveedor_id"), d.get("referencia_proveedor"),
         d.get("certificado"), "Ingresado", d.get("obs"), session["user_id"]))
    # El stock del material representa SOLO lo Aprobado por Calidad. Un lote
    # recién ingresado queda en estado "Ingresado" con cantidad_activa=0
    # (nada aprobado todavía), así que NO se suma a stock acá. El stock se
    # actualiza recién en update_lote(), cuando Calidad clasifica cantidades
    # como Aprobado/Rechazado/Pendiente. Se deja igual un movimiento
    # informativo para trazabilidad, aclarando que todavía no impacta stock.
    execute("""INSERT INTO movimientos (material_id,lote_id,tipo,cantidad,referencia,usuario_id)
        VALUES (?,?,?,?,?,?)""",
        (d["material_id"], lid, "ingreso", qty,
         f"Ingreso lote {numero} — {d.get('referencia_proveedor','')} (pendiente de clasificación, no computa a stock)",
         session["user_id"]))
    return jsonify({"ok": True, "id": lid, "numero": numero}), 201

@app.route("/api/lotes/<int:lid>", methods=["PUT"])
@login_required(roles=["admin","almacen","calidad"])
def update_lote(lid):
    d = request.json
    lote = query("SELECT * FROM lotes WHERE id=?", (lid,), one=True)
    if not lote: return jsonify({"error": "Lote no encontrado"}), 404

    disp = float(lote["cantidad_disponible"])

    # ── Modelo nuevo: se editan los 3 valores de la partición del lote
    # (Aprobado / Rechazado / Pendiente) de forma absoluta, no incremental.
    # Esto evita que aprobar y rechazar por separado sumen más que el total
    # disponible, y permite corregir un dato mal cargado simplemente
    # reabriendo el lote y volviendo a fijar los valores correctos.
    if "cantidad_aprobada" in d or "cantidad_rechazada" in d:
        aprobado = float(d.get("cantidad_aprobada", lote["cantidad_activa"] or 0) or 0)
        rechazado = float(d.get("cantidad_rechazada", lote["cantidad_rechazada"] or 0) or 0)
        if aprobado < 0 or rechazado < 0:
            return jsonify({"error": "Las cantidades no pueden ser negativas"}), 400
        if aprobado + rechazado > disp + 0.001:
            return jsonify({"error": "Aprobado (%.2f) + Rechazado (%.2f) no puede superar el total disponible (%.2f)"
                % (aprobado, rechazado, disp)}), 400

        pendiente = max(0.0, disp - aprobado - rechazado)
        if pendiente <= 0.001 and aprobado >= rechazado:
            estado_lote = "Aprobado"
        elif pendiente <= 0.001 and rechazado > aprobado:
            estado_lote = "Rechazado"
        else:
            estado_lote = "Ingresado"  # queda algo pendiente de analizar (parcial)

        execute("""UPDATE lotes SET estado=?,cantidad_activa=?,cantidad_rechazada=?,
            referencia_proveedor=?,certificado=?,obs=? WHERE id=?""",
            (estado_lote, aprobado, rechazado,
             d.get("referencia_proveedor", lote["referencia_proveedor"]),
             d.get("certificado", lote["certificado"]),
             d.get("obs", lote["obs"]), lid))
        execute("""INSERT INTO movimientos (material_id,lote_id,tipo,cantidad,referencia,usuario_id)
            VALUES (?,?,?,?,?,?)""",
            (lote["material_id"], lid, "ajuste", disp,
             ("Edición liberación → Aprobado:%.2f Rechazado:%.2f Pendiente:%.2f | Lote %s"
                % (aprobado, rechazado, pendiente, lote["numero"]))
             + (" | Obs: " + d.get("obs") if d.get("obs") else ""),
             session["user_id"]))
        # ── El stock del material representa SOLO lo Aprobado ──────────────
        # Lo Pendiente y lo Rechazado NO cuentan como stock disponible. Por
        # eso el ajuste de stock se calcula en base a la variación de
        # cantidad_aprobada (cantidad_activa) respecto del valor previo, sin
        # importar cómo se haya movido lo Rechazado/Pendiente. Si aprobado
        # sube, entra a stock; si baja (ej. se corrige una clasificación),
        # sale de stock.
        aprobado_anterior = float(lote["cantidad_activa"] or 0)
        delta_aprobado = aprobado - aprobado_anterior
        if abs(delta_aprobado) > 0.0001:
            execute("""UPDATE materiales SET stock=MAX(0,stock+?),
                actualizado=datetime('now','localtime') WHERE id=?""",
                (delta_aprobado, lote["material_id"]))
            execute("""INSERT INTO movimientos (material_id,lote_id,tipo,cantidad,referencia,usuario_id)
                VALUES (?,?,?,?,?,?)""",
                (lote["material_id"], lid,
                 "entrada" if delta_aprobado > 0 else "salida",
                 abs(delta_aprobado),
                 (f"Aprobación de lote {lote['numero']} — ingreso a inventario"
                  if delta_aprobado > 0 else
                  f"Corrección de aprobación — Lote {lote['numero']} (baja de inventario)"),
                 session["user_id"]))
        auto_generar_sc_bajo_stock(lote["material_id"], f"ajuste de lote {lote['numero']} (aprobado/rechazado)")
        return jsonify({"ok": True, "numero_lote": lote["numero"],
            "cantidad_aprobada": aprobado, "cantidad_rechazada": rechazado,
            "cantidad_pendiente": pendiente, "estado": estado_lote})

    # ── Modelo legado: cambio de estado de todo el lote de una sola vez
    # (se mantiene por compatibilidad con otros llamadores internos)
    nuevo_estado = d.get("estado", lote["estado"])
    nueva_activa_total = disp if nuevo_estado == "Aprobado" else 0
    nueva_rechazada_total = disp if nuevo_estado == "Rechazado" else 0
    execute("""UPDATE lotes SET estado=?,cantidad_activa=?,cantidad_rechazada=?,
        referencia_proveedor=?,certificado=?,obs=? WHERE id=?""",
        (nuevo_estado, nueva_activa_total, nueva_rechazada_total,
         d.get("referencia_proveedor", lote["referencia_proveedor"]),
         d.get("certificado", lote["certificado"]),
         d.get("obs", lote["obs"]), lid))
    execute("""INSERT INTO movimientos (material_id,lote_id,tipo,cantidad,referencia,usuario_id)
        VALUES (?,?,?,?,?,?)""",
        (lote["material_id"], lid, "ajuste", disp,
         f"Cambio estado → {nuevo_estado} | Lote {lote['numero']}",
         session["user_id"]))
    # ── El stock del material representa SOLO lo Aprobado (ver explicación
    # detallada en el modelo nuevo más arriba) — el ajuste se calcula según
    # la variación de cantidad_activa (aprobado), no de rechazado ─────────
    aprobado_anterior = float(lote["cantidad_activa"] or 0)
    delta_aprobado = nueva_activa_total - aprobado_anterior
    if abs(delta_aprobado) > 0.0001:
        execute("""UPDATE materiales SET stock=MAX(0,stock+?),
            actualizado=datetime('now','localtime') WHERE id=?""",
            (delta_aprobado, lote["material_id"]))
        execute("""INSERT INTO movimientos (material_id,lote_id,tipo,cantidad,referencia,usuario_id)
            VALUES (?,?,?,?,?,?)""",
            (lote["material_id"], lid,
             "entrada" if delta_aprobado > 0 else "salida",
             abs(delta_aprobado),
             (f"Aprobación de lote {lote['numero']} — ingreso a inventario"
              if delta_aprobado > 0 else
              f"Corrección de aprobación — Lote {lote['numero']} (baja de inventario)"),
             session["user_id"]))
    auto_generar_sc_bajo_stock(lote["material_id"], f"cambio de estado de lote {lote['numero']}")
    return jsonify({"ok": True, "accion": "estado_actualizado",
        "estado": nuevo_estado, "cant_activa": nueva_activa_total})

@app.route("/api/lotes/<int:lid>/trazabilidad", methods=["GET"])
@login_required()
def trazabilidad_lote(lid):
    """Traza un lote: movimientos, OTs que lo usaron, productos terminados generados."""
    lote = query("""SELECT l.*,m.codigo mat_codigo,m.descripcion mat_descripcion
        FROM lotes l JOIN materiales m ON m.id=l.material_id WHERE l.id=?""",
        (lid,), one=True)
    if not lote: return jsonify({"error": "Lote no encontrado"}), 404

    movimientos = query("""SELECT mv.*,u.nombre usuario_nombre
        FROM movimientos mv LEFT JOIN usuarios u ON u.id=mv.usuario_id
        WHERE mv.lote_id=? ORDER BY mv.id""", (lid,))

    ordenes = query("""SELECT ol.*,o.numero ot_numero,o.estado ot_estado,
        o.fecha_entrega,c.razon cliente_nombre,p.nombre producto_nombre,
        m.descripcion mat_descripcion
        FROM orden_lotes ol
        JOIN ordenes o ON o.id=ol.orden_id
        LEFT JOIN clientes c ON c.id=o.cliente_id
        LEFT JOIN productos p ON p.id=o.producto_id
        JOIN materiales m ON m.id=ol.material_id
        WHERE ol.lote_id=? ORDER BY ol.id""", (lid,))

    return jsonify({
        "lote": dict(lote),
        "movimientos": [dict(r) for r in movimientos],
        "ordenes": [dict(r) for r in ordenes],
    })

@app.route("/api/materiales/<int:mid>/lotes", methods=["GET"])
@login_required()
def get_lotes_by_material(mid):
    rows = query("""SELECT l.*,p.razon proveedor_nombre
        FROM lotes l LEFT JOIN proveedores p ON p.id=l.proveedor_id
        WHERE l.material_id=? ORDER BY l.id DESC""", (mid,))
    return jsonify([dict(r) for r in rows])

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
    pendiente de aprobación de Calidad (lotes en estado 'Ingresado'). Si ese
    stock, al aprobarse, alcanza para llegar al mínimo, no hay necesidad
    real de comprar nada — solo falta que Calidad decida. Solo si, aun
    contando ese stock pendiente de aprobación, el faltante neto sigue
    siendo positivo, se genera la SC por ese remanente.

    Cuando el stock del material vuelve a completarse hasta el objetivo
    (stock máximo, o el mínimo si no hay máximo configurado) —típicamente al
    recibirse/aprobarse la mercadería de la OC emitida— se da por resuelta
    cualquier SC que siguiera abierta para ese material (se marca 'Cerrada').
    Recién ahí, la próxima vez que el stock vuelva a caer por debajo del
    mínimo, se generará una SC nueva.

    No hace nada si el material no es comprable (Producto terminado) o no
    tiene mínimo configurado."""
    if not material_id:
        return
    mat = query("SELECT id,codigo,descripcion,stock,stock_min,stock_max,unidad,categoria FROM materiales WHERE id=?",
                (material_id,), one=True)
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
    pendiente_entrega = query("""SELECT COALESCE(SUM(i.cantidad - i.cantidad_recibida),0) pend
        FROM ordenes_compra_items i
        JOIN solicitudes_compra s ON s.id = i.solicitud_id
        WHERE s.material_id=? AND s.estado='OC Emitida'""", (material_id,), one=True)["pend"] or 0

    # Stock que YA está en planta pero todavía sin decisión de Calidad
    # (lotes en estado 'Ingresado'): si ese stock se termina aprobando,
    # alcanza para tapar el faltante sin necesidad de comprar nada. Mientras
    # ese pendiente de aprobación cubra (total o parcialmente) el faltante,
    # no corresponde generar ni actualizar una SC por esa parte: no hay
    # ninguna necesidad real de compra todavía, solo falta que Calidad
    # decida sobre lo que ya se recibió.
    pendiente_aprobacion = query("""SELECT COALESCE(SUM(cantidad_disponible),0) pend
        FROM lotes WHERE material_id=? AND estado='Ingresado'""",
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

    last = query("SELECT numero FROM solicitudes_compra ORDER BY id DESC LIMIT 1", one=True)
    try: n = int(last["numero"].split("-")[1])+1 if last else 1
    except: n = 1
    numero = f"SC-{n:04d}"
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
    sql = """SELECT s.*,m.descripcion mat_nombre,m.unidad mat_unidad,
        u.nombre solicitante_nombre, o.numero ot_numero
        FROM solicitudes_compra s
        LEFT JOIN materiales m ON m.id=s.material_id
        LEFT JOIN usuarios u ON u.id=s.solicitante_id
        LEFT JOIN ordenes o ON o.id=s.ot_origen_id"""
    rows = query(sql+" WHERE s.tipo=? ORDER BY s.id DESC",(tipo,)) if tipo else query(sql+" ORDER BY s.id DESC")
    return jsonify([dict(r) for r in rows])

@app.route("/api/solicitudes_compra", methods=["POST"])
@login_required(roles=["admin","almacen","operario"])
def create_solicitud():
    d = request.json
    if not d.get("descripcion") or not d.get("cantidad"):
        return jsonify({"error":"Descripción y cantidad requeridas"}), 400
    tipo = d.get("tipo", "Productiva")
    if d.get("material_id"):
        mat = query("SELECT categoria FROM materiales WHERE id=?", (d["material_id"],), one=True)
        if not mat or mat["categoria"] not in ("Material", "Insumo", "Herramienta", "Producto terminado"):
            return jsonify({"error":"Solo se pueden solicitar materiales, insumos, herramientas o productos terminados"}), 400
        if tipo == "Productiva" and mat["categoria"] not in ("Material", "Producto terminado"):
            return jsonify({"error":"Una SC productiva solo puede cargar materiales o productos terminados, no insumos ni herramientas"}), 400
        if tipo == "Indirecta" and mat["categoria"] not in ("Insumo", "Herramienta"):
            return jsonify({"error":"Una SC indirecta solo puede cargar insumos o herramientas"}), 400
    elif tipo == "Indirecta":
        return jsonify({"error":"Las SC indirectas deben cargar un insumo o herramienta"}), 400
    if d.get("material_id"):
        activa = query("""SELECT numero FROM solicitudes_compra
            WHERE material_id=? AND estado IN ('Pendiente','Cotizada')
            ORDER BY id DESC LIMIT 1""", (d["material_id"],), one=True)
        if activa:
            return jsonify({"error":f"Ya existe una solicitud de compra activa ({activa['numero']}) para este material"}), 400
    last = query("SELECT numero FROM solicitudes_compra ORDER BY id DESC LIMIT 1", one=True)
    try: n = int(last["numero"].split("-")[1])+1 if last else 1
    except: n = 1
    numero = f"SC-{n:04d}"
    lid = execute("""INSERT INTO solicitudes_compra
        (numero,tipo,material_id,descripcion,cantidad,unidad,urgencia,estado,ot_origen_id,centro_costo,solicitante_id,obs)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (numero,d.get("tipo","Productiva"),d.get("material_id"),d["descripcion"],d["cantidad"],
         d.get("unidad"),d.get("urgencia","Normal"),"Pendiente",d.get("ot_origen_id"),
         d.get("centro_costo"),session["user_id"],d.get("obs")))
    return jsonify({"ok":True,"id":lid,"numero":numero}), 201

@app.route("/api/solicitudes_compra/<int:sid>", methods=["PUT"])
@login_required(roles=["admin","almacen"])
def update_solicitud(sid):
    d = request.json
    actual = query("SELECT * FROM solicitudes_compra WHERE id=?", (sid,), one=True)
    if not actual: return jsonify({"error":"No encontrada"}), 404
    if actual["estado"] == "OC Emitida":
        return jsonify({"error":"No se puede editar: ya tiene una OC emitida"}), 400
    campos = ["tipo","material_id","descripcion","cantidad","unidad","urgencia","estado","ot_origen_id","centro_costo","obs"]
    valores = {c: d[c] if c in d else actual[c] for c in campos}
    if valores.get("material_id"):
        mat = query("SELECT categoria FROM materiales WHERE id=?", (valores["material_id"],), one=True)
        if not mat or mat["categoria"] not in ("Material", "Insumo", "Herramienta", "Producto terminado"):
            return jsonify({"error":"Solo se pueden solicitar materiales, insumos, herramientas o productos terminados"}), 400
        if valores["tipo"] == "Productiva" and mat["categoria"] not in ("Material", "Producto terminado"):
            return jsonify({"error":"Una SC productiva solo puede cargar materiales o productos terminados, no insumos ni herramientas"}), 400
        if valores["tipo"] == "Indirecta" and mat["categoria"] not in ("Insumo", "Herramienta"):
            return jsonify({"error":"Una SC indirecta solo puede cargar insumos o herramientas"}), 400
    elif valores["tipo"] == "Indirecta":
        return jsonify({"error":"Las SC indirectas deben cargar un insumo o herramienta"}), 400
    execute("""UPDATE solicitudes_compra SET tipo=?,material_id=?,descripcion=?,cantidad=?,unidad=?,
        urgencia=?,estado=?,ot_origen_id=?,centro_costo=?,obs=? WHERE id=?""",
        (valores["tipo"],valores["material_id"],valores["descripcion"],valores["cantidad"],valores["unidad"],
         valores["urgencia"],valores["estado"],valores["ot_origen_id"],valores["centro_costo"],valores["obs"],sid))
    return jsonify({"ok":True})

# ── Cotizaciones de compra ────────────────────────────────────────────────────
@app.route("/api/cotizaciones_compra", methods=["GET"])
@login_required()
def get_cotizaciones():
    sid = request.args.get("solicitud_id")
    sql = """SELECT c.*,p.razon proveedor_nombre,s.descripcion solicitud_desc,s.cantidad sol_cantidad,s.unidad sol_unidad,s.tipo solicitud_tipo,s.estado solicitud_estado
        FROM cotizaciones_compra c
        JOIN proveedores p ON p.id=c.proveedor_id
        JOIN solicitudes_compra s ON s.id=c.solicitud_id"""
    rows = query(sql+" WHERE c.solicitud_id=? ORDER BY c.precio_unit",(sid,)) if sid else query(sql+" ORDER BY c.id DESC")
    return jsonify([dict(r) for r in rows])

@app.route("/api/cotizaciones_compra", methods=["POST"])
@login_required(roles=["admin","almacen"])
def create_cotizacion():
    d = request.json
    if not d.get("solicitud_id") or not d.get("proveedor_id") or not d.get("precio_unit"):
        return jsonify({"error":"Solicitud, proveedor y precio requeridos"}), 400
    lid = execute("""INSERT INTO cotizaciones_compra
        (solicitud_id,proveedor_id,precio_unit,plazo_entrega_dias,condicion_pago,seleccionada,obs)
        VALUES (?,?,?,?,?,?,?)""",
        (d["solicitud_id"],d["proveedor_id"],d["precio_unit"],d.get("plazo_entrega_dias",3),
         d.get("condicion_pago"),0,d.get("obs")))
    return jsonify({"ok":True,"id":lid}), 201

@app.route("/api/cotizaciones_compra/<int:cid>/seleccionar", methods=["POST"])
@login_required(roles=["admin","almacen"])
def seleccionar_cotizacion(cid):
    cot = query("SELECT * FROM cotizaciones_compra WHERE id=?", (cid,), one=True)
    if not cot: return jsonify({"error":"Cotización no encontrada"}), 404
    execute("UPDATE cotizaciones_compra SET seleccionada=0 WHERE solicitud_id=?", (cot["solicitud_id"],))
    execute("UPDATE cotizaciones_compra SET seleccionada=1 WHERE id=?", (cid,))
    execute("UPDATE solicitudes_compra SET estado='Cotizada' WHERE id=?", (cot["solicitud_id"],))
    return jsonify({"ok":True})

@app.route("/api/cotizaciones_compra/<int:cid>/deseleccionar", methods=["POST"])
@login_required(roles=["admin","almacen"])
def deseleccionar_cotizacion(cid):
    cot = query("SELECT * FROM cotizaciones_compra WHERE id=?", (cid,), one=True)
    if not cot: return jsonify({"error":"Cotización no encontrada"}), 404
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
            s.numero sc_numero,s.tipo sc_tipo
            FROM ordenes_compra_items i LEFT JOIN materiales m ON m.id=i.material_id
            LEFT JOIN solicitudes_compra s ON s.id=i.solicitud_id
            WHERE i.oc_id=?""", (r["id"],))]
        result.append(d)
    return jsonify(result)

@app.route("/api/ordenes_compra", methods=["POST"])
@login_required(roles=["admin","almacen"])
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
    last = query("SELECT numero FROM ordenes_compra ORDER BY id DESC LIMIT 1", one=True)
    try: n = int(last["numero"].split("-")[1])+1 if last else 1
    except: n = 1
    numero = f"OCP-{n:04d}"
    total = sum(float(i.get("precio_unit",0))*float(i.get("cantidad",0)) for i in d["items"])
    estado = "Aprobada" if total <= LIMITE_APROBACION else "Pendiente aprobacion"
    lid = execute("""INSERT INTO ordenes_compra
        (numero,proveedor_id,estado,monto_total,fecha_entrega_est,obs,creado_por)
        VALUES (?,?,?,?,?,?,?)""",
        (numero,d["proveedor_id"],estado,total,d.get("fecha_entrega_est"),d.get("obs"),session["user_id"]))
    lotes_creados = []
    for item in d["items"]:
        execute("""INSERT INTO ordenes_compra_items
            (oc_id,solicitud_id,material_id,descripcion,cantidad,precio_unit,unidad)
            VALUES (?,?,?,?,?,?,?)""",
            (lid,item.get("solicitud_id"),item.get("material_id"),item["descripcion"],
             item["cantidad"],item["precio_unit"],item.get("unidad")))
        if item.get("solicitud_id"):
            execute("UPDATE solicitudes_compra SET estado='OC Emitida' WHERE id=?", (item["solicitud_id"],))
            sc = query("SELECT material_id FROM solicitudes_compra WHERE id=?", (item["solicitud_id"],), one=True)
            if sc and sc["material_id"]:
                auto_generar_sc_bajo_stock(sc["material_id"], f"OC {numero} emitida para SC")
        # ── Al EMITIR la OC se crea de una todo el Lote de ese ítem, en estado
        # "Ingresado" (pendiente de aprobación de Calidad). El stock de
        # materiales NO se toca acá: se suma recién cuando Calidad aprueba el
        # lote vía update_lote(). Así el lote entrante queda visible/planificable
        # desde el momento en que se emite la orden, sin esperar la recepción
        # física de la mercadería.
        if item.get("material_id"):
            mat_cat = query("SELECT categoria FROM materiales WHERE id=?", (item["material_id"],), one=True)
            if mat_cat and mat_cat["categoria"] in ("Material", "Producto terminado"):
                qty = float(item["cantidad"])
                numero_lote = _gen_lote_numero()
                lote_id = execute("""INSERT INTO lotes
                    (numero,material_id,cantidad_original,cantidad_disponible,cantidad_activa,
                     proveedor_id,referencia_proveedor,estado,creado_por)
                    VALUES (?,?,?,?,?,?,?,?,?)""",
                    (numero_lote, item["material_id"], qty, qty, 0,
                     d["proveedor_id"], f"OC {numero}", "Ingresado", session["user_id"]))
                execute("""INSERT INTO movimientos (material_id,lote_id,tipo,cantidad,referencia,usuario_id)
                    VALUES (?,?,?,?,?,?)""",
                    (item["material_id"], lote_id, "ingreso", qty,
                     f"OC {numero} emitida — Lote {numero_lote} (pendiente de aprobación de Calidad, no computa a stock)",
                     session["user_id"]))
                lotes_creados.append(numero_lote)
    return jsonify({"ok":True,"id":lid,"numero":numero,"estado":estado,"total":total,"lotes":lotes_creados}), 201

@app.route("/api/ordenes_compra/<int:ocid>/aprobar", methods=["POST"])
@login_required(roles=["admin"])
def aprobar_oc(ocid):
    execute("UPDATE ordenes_compra SET estado='Aprobada',aprobado_por=?,fecha_aprobacion=datetime('now','localtime') WHERE id=?",
        (session["user_id"], ocid))
    return jsonify({"ok":True})

@app.route("/api/ordenes_compra/<int:ocid>/recibir", methods=["POST"])
@login_required(roles=["admin","almacen"])
def recibir_oc(ocid):
    d = request.json
    recepciones = d.get("items", [])
    for recv in recepciones:
        item = query("SELECT * FROM ordenes_compra_items WHERE id=?", (recv["item_id"],), one=True)
        if not item: continue
        qty = float(recv.get("cantidad",0))
        execute("UPDATE ordenes_compra_items SET cantidad_recibida=cantidad_recibida+? WHERE id=?", (qty, recv["item_id"]))
        if item["material_id"]:
            mat_cat = query("SELECT categoria FROM materiales WHERE id=?", (item["material_id"],), one=True)
            oc = query("SELECT numero FROM ordenes_compra WHERE id=?", (ocid,), one=True)
            if mat_cat and mat_cat["categoria"] in ("Material", "Producto terminado"):
                # Categorías "Material" y "Producto terminado": el Lote ya fue
                # creado al EMITIR la OC (ver create_oc), con todo su stock en
                # "Ingresado" pendiente de aprobación de Calidad. Acá solo
                # registramos la recepción física para trazabilidad
                # (cantidad_recibida), sin crear un lote nuevo ni tocar
                # materiales.stock (eso ocurre recién cuando Calidad aprueba
                # el lote vía update_lote).
                pass
            else:
                # Otras categorías (Insumo, Herramienta) no pasan por control
                # de Calidad ni manejan lote: se suman directo.
                execute("UPDATE materiales SET stock=stock+?,actualizado=datetime('now','localtime') WHERE id=?", (qty, item["material_id"]))
            execute("INSERT INTO movimientos (material_id,lote_id,tipo,cantidad,referencia,usuario_id) VALUES (?,?,?,?,?,?)",
                (item["material_id"], None,
                 "entrada" if not (mat_cat and mat_cat["categoria"] in ("Material","Producto terminado")) else "recepcion",
                 qty, f"Recep. {oc['numero']}", session["user_id"]))
    items = query("SELECT cantidad,cantidad_recibida FROM ordenes_compra_items WHERE oc_id=?", (ocid,))
    total_ord = sum(i["cantidad"] for i in items)
    total_rec = sum(i["cantidad_recibida"] for i in items)
    if total_rec >= total_ord: execute("UPDATE ordenes_compra SET estado='Recibida' WHERE id=?", (ocid,))
    elif total_rec > 0: execute("UPDATE ordenes_compra SET estado='Recibida parcial' WHERE id=?", (ocid,))
    return jsonify({"ok":True})

@app.route("/api/ordenes_compra/<int:ocid>", methods=["PUT"])
@login_required(roles=["admin","almacen"])
def update_oc(ocid):
    d = request.json
    execute("UPDATE ordenes_compra SET estado=?,fecha_entrega_est=?,obs=? WHERE id=?",
        (d.get("estado"),d.get("fecha_entrega_est"),d.get("obs"),ocid))
    return jsonify({"ok":True})

# ── MRP ampliado ──────────────────────────────────────────────────────────────
@app.route("/api/mrp")
@login_required()
def mrp():
    return jsonify({
        "criticos": [dict(r) for r in query("""SELECT m.id,m.codigo,m.descripcion,m.stock,m.stock_min,m.stock_max,m.stock_min-m.stock AS faltante,m.unidad,p.razon proveedor,
            (SELECT s.numero FROM solicitudes_compra s WHERE s.material_id=m.id AND s.estado IN ('Pendiente','Cotizada') ORDER BY s.id DESC LIMIT 1) sc_activa
            FROM materiales m LEFT JOIN proveedores p ON p.id=m.proveedor_id WHERE m.stock<m.stock_min AND m.stock_min>0 ORDER BY (m.stock_min-m.stock) DESC""")],
        "ordenes_activas": [dict(r) for r in query("SELECT o.numero,o.descripcion,o.estado,o.fecha_entrega,o.cantidad,c.razon cliente,pr.nombre producto FROM ordenes o LEFT JOIN clientes c ON c.id=o.cliente_id LEFT JOIN productos pr ON pr.id=o.producto_id WHERE o.estado IN ('Pendiente','En proceso') ORDER BY o.fecha_entrega")],
        "oc_cliente_pendientes": [dict(r) for r in query("SELECT oc.*,c.razon cliente_nombre FROM ordenes_cliente oc JOIN clientes c ON c.id=oc.cliente_id WHERE oc.estado IN ('Recibida','Confirmada') ORDER BY oc.fecha_entrega")],
        "carga_por_sector": [dict(r) for r in query("""SELECT cm.nombre sector,COUNT(oo.id) ops_pendientes,
            SUM(oo.qty_requerida - oo.qty_producida) piezas_pendientes
            FROM orden_operaciones oo
            JOIN categorias_maquina cm ON cm.id=oo.categoria_maquina_id
            WHERE oo.estado != 'Completada'
            GROUP BY cm.nombre ORDER BY ops_pendientes DESC""")],
    })



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
    from collections import defaultdict
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


# ── Remitos ───────────────────────────────────────────────────────────────────
@app.route("/api/remitos", methods=["GET"])
@login_required()
def get_remitos():
    cliente_id = request.args.get("cliente_id")
    sql = """SELECT r.*,c.razon cliente_nombre,oc.numero oc_numero
        FROM remitos r
        LEFT JOIN clientes c ON c.id=r.cliente_id
        LEFT JOIN ordenes_cliente oc ON oc.id=r.orden_cliente_id"""
    rows = query(sql+" WHERE r.cliente_id=? ORDER BY r.id DESC",(cliente_id,)) if cliente_id else query(sql+" ORDER BY r.id DESC LIMIT 200")
    result = []
    for r in rows:
        d = dict(r)
        d["items"] = [dict(x) for x in query("""SELECT ri.*,m.descripcion mat_descripcion,
            m.codigo mat_codigo,m.unidad,l.numero lote_numero
            FROM remito_items ri
            JOIN materiales m ON m.id=ri.material_id
            JOIN lotes l ON l.id=ri.lote_id
            WHERE ri.remito_id=?""", (r["id"],))]
        result.append(d)
    return jsonify(result)

@app.route("/api/pt_disponible", methods=["GET"])
@login_required()
def get_pt_disponible():
    """Productos terminados con lotes activos disponibles para remitir."""
    cliente_id = request.args.get("cliente_id")
    # La vinculación a la OC de cliente solo cuenta si esa OC está activa
    # (no Cancelada). Si se cancela la OC, el producto ya hecho y aprobado
    # queda "sin OC vinculada" (aunque el ítem oc_items.ot_id siga apuntando
    # a la OT); si la OC se reabre (vuelve a un estado activo), el join
    # vuelve a resolver y la vinculación reaparece sola — todo se calcula en
    # vivo a partir de ordenes_cliente.estado, sin tocar el vínculo real.
    rows = query("""SELECT l.*,m.codigo mat_codigo,m.descripcion mat_descripcion,m.unidad,
        p.nombre producto_nombre, p.id producto_id,
        CASE WHEN oc.id IS NOT NULL THEN oc_items.id END oc_item_id,
        CASE WHEN oc.id IS NOT NULL THEN oc_items.cantidad END oc_cantidad,
        CASE WHEN oc.id IS NOT NULL THEN oc_items.orden_cliente_id END orden_cliente_id,
        oc.numero oc_numero,
        CASE WHEN oc.id IS NOT NULL THEN oc.cliente_id END oc_cliente_id,
        CASE WHEN oc.id IS NOT NULL THEN
            (SELECT COALESCE(SUM(ri.cantidad),0) FROM remito_items ri WHERE ri.orden_cliente_item_id=oc_items.id)
        END ya_remitido
        FROM lotes l
        JOIN materiales m ON m.id=l.material_id
        LEFT JOIN productos p ON p.codigo=m.codigo
        LEFT JOIN ordenes ot_gen ON ot_gen.numero=l.numero
        LEFT JOIN ordenes_cliente_items oc_items ON oc_items.producto_id=p.id
            AND oc_items.ot_id=ot_gen.id
        LEFT JOIN ordenes_cliente oc ON oc.id=oc_items.orden_cliente_id
            AND oc.estado IN ('Recibida','Confirmada','En proceso')
        WHERE m.categoria='Producto terminado'
        AND l.cantidad_activa>0 AND l.estado != 'Agotado' AND l.estado != 'Bloqueado'
        AND oc.id IS NOT NULL
        """ + ("AND oc.cliente_id=?" if cliente_id else "") + """
        ORDER BY l.id DESC""", (cliente_id,) if cliente_id else ())
    return jsonify([dict(r) for r in rows])

@app.route("/api/remitos", methods=["POST"])
@login_required(roles=["admin","almacen","vendedor"])
def create_remito():
    d = request.json
    if not d.get("cliente_id"): return jsonify({"error": "Cliente requerido"}), 400
    items_in = [it for it in (d.get("items") or []) if it.get("lote_id") and it.get("cantidad")]
    if not items_in:
        return jsonify({"error": "El remito debe tener al menos un ítem"}), 400
    last = query("SELECT numero FROM remitos ORDER BY id DESC LIMIT 1", one=True)
    try: n = int(last["numero"].split("-")[1])+1 if last else 1
    except: n = 1
    numero = f"REM-{n:04d}"
    rid = execute("""INSERT INTO remitos (numero,cliente_id,orden_cliente_id,obs,creado_por)
        VALUES (?,?,?,?,?)""",
        (numero, d.get("cliente_id"), d.get("orden_cliente_id"),
         d.get("obs"), session["user_id"]))
    items_insertados = 0
    for item in items_in:
        qty = float(item["cantidad"])
        lote = query("""SELECT id,material_id,cantidad_disponible,cantidad_activa
            FROM lotes WHERE id=?""", (item["lote_id"],), one=True)
        if not lote: continue
        activa = float(lote["cantidad_activa"] or 0)
        if qty > activa:
            # Can't remit more than what's active/approved
            continue
        execute("""INSERT INTO remito_items
            (remito_id,material_id,lote_id,orden_cliente_item_id,cantidad,obs)
            VALUES (?,?,?,?,?,?)""",
            (rid, lote["material_id"], item["lote_id"],
             item.get("orden_cliente_item_id"), qty, item.get("obs")))
        items_insertados += 1
        # Discount from lote (both disponible and activa)
        nueva_disp   = max(0, float(lote["cantidad_disponible"]) - qty)
        nueva_activa = max(0, activa - qty)
        nuevo_estado = "Agotado" if nueva_disp <= 0 else ("Aprobado" if nueva_activa > 0 else "Ingresado")
        execute("""UPDATE lotes SET cantidad_disponible=?,cantidad_activa=?,estado=?
            WHERE id=?""", (nueva_disp, nueva_activa, nuevo_estado, lote["id"]))
        # Discount from PT stock
        execute("UPDATE materiales SET stock=MAX(0,stock-?),actualizado=datetime('now','localtime') WHERE id=?",
            (qty, lote["material_id"]))
        execute("INSERT INTO movimientos (material_id,lote_id,tipo,cantidad,referencia,usuario_id) VALUES (?,?,?,?,?,?)",
            (lote["material_id"], lote["id"], "salida", qty, f"Remito {numero}", session["user_id"]))
    if items_insertados == 0:
        # Ningún ítem pudo aplicarse (stock insuficiente en todos): abortar remito
        execute("DELETE FROM remitos WHERE id=?", (rid,))
        return jsonify({"error": "No se pudo generar el remito: stock insuficiente en los ítems seleccionados"}), 400

    # ── Cierre automático de la OC: si con este remito se cubrió el 100% de
    # lo pedido (sumando todos los remitos, no solo este), marcar la OC como
    # "Completada". No completar OCs que todavía tengan renglones sin OT
    # (item["ot_id"] NULL), porque eso significa que ni siquiera se terminó
    # de planificar todo el pedido.
    ocids_afectadas = set()
    if d.get("orden_cliente_id"):
        ocids_afectadas.add(d["orden_cliente_id"])
    for item in items_in:
        oci = item.get("orden_cliente_item_id")
        if oci:
            row = query("SELECT orden_cliente_id FROM ordenes_cliente_items WHERE id=?", (oci,), one=True)
            if row: ocids_afectadas.add(row["orden_cliente_id"])
    for ocid_remito in ocids_afectadas:
        oc_items = query("""SELECT id,cantidad,ot_id FROM ordenes_cliente_items
            WHERE orden_cliente_id=?""", (ocid_remito,))
        if oc_items and all(it["ot_id"] for it in oc_items):
            total_req = sum(float(it["cantidad"]) for it in oc_items)
            total_ent = 0.0
            for it in oc_items:
                ent = query("""SELECT COALESCE(SUM(ri.cantidad),0) total
                    FROM remito_items ri JOIN remitos r ON r.id=ri.remito_id
                    WHERE ri.orden_cliente_item_id=? AND r.estado!='Anulado'""",
                    (it["id"],), one=True)["total"]
                total_ent += float(ent)
            if total_req > 0 and total_ent >= total_req - 0.001:
                execute("UPDATE ordenes_cliente SET estado='Completada' WHERE id=?", (ocid_remito,))

    return jsonify({"ok": True, "id": rid, "numero": numero}), 201





# ── Configuración del sistema ─────────────────────────────────────────────────
@app.route("/api/config", methods=["GET"])
@login_required()
def get_config():
    rows = query("SELECT clave, valor, descripcion FROM configuracion ORDER BY clave")
    return jsonify({r["clave"]: {"valor": r["valor"] or "", "descripcion": r["descripcion"]} for r in rows})

@app.route("/api/config", methods=["POST"])
@login_required(roles=["admin"])
def save_config():
    d = request.json or {}
    for clave, valor in d.items():
        execute("UPDATE configuracion SET valor=? WHERE clave=?", (str(valor), clave))
    return jsonify({"ok": True})

# ── Emisión de OT (PDF con ReportLab) ────────────────────────────────────────
@app.route("/api/ordenes/<int:oid>/pdf")
@login_required()
def emitir_ot_pdf(oid):
    try:
        return _build_ot_pdf(oid)
    except Exception:
        import traceback
        tb = traceback.format_exc()
        return (
            '<html><body style="font-family:monospace;padding:20px">'
            '<h2 style="color:red">Error al generar PDF</h2>'
            '<pre style="background:#f5f5f5;padding:16px;border-radius:4px;font-size:12px">'
            + tb.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
            + '</pre></body></html>'
        ), 500


def _build_ot_pdf(oid):
    import io
    from datetime import datetime
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
        HRFlowable, KeepTogether
    )
    from flask import send_file

    # ── Datos ────────────────────────────────────────────────────────────────
    ot = query("""SELECT o.*,c.razon cliente_nombre,
        p.nombre producto_nombre, p.codigo producto_codigo
        FROM ordenes o
        LEFT JOIN clientes c ON c.id=o.cliente_id
        LEFT JOIN productos p ON p.id=o.producto_id
        WHERE o.id=?""", (oid,), one=True)
    if not ot:
        from flask import jsonify
        return jsonify({"error": "OT no encontrada"}), 404

    ops = query("""SELECT oo.*,
        cm.nombre cat_maquina_nombre, m.nombre maquina_nombre,
        p.razon proveedor_nombre
        FROM orden_operaciones oo
        LEFT JOIN categorias_maquina cm ON cm.id=oo.categoria_maquina_id
        LEFT JOIN maquinas m ON m.id=oo.maquina_id
        LEFT JOIN proveedores p ON p.id=oo.proveedor_id
        WHERE oo.orden_id=? ORDER BY CAST(oo.orden AS INTEGER), oo.orden""", (oid,))

    mats = query("""SELECT om.*,
        m.descripcion, m.codigo, m.unidad,
        COALESCE(m.stock,0) AS stock
        FROM orden_materiales om
        JOIN materiales m ON m.id=om.material_id
        WHERE om.orden_id=? ORDER BY m.codigo""", (oid,))

    # ── Config ───────────────────────────────────────────────────────────────
    cfg_rows = query("SELECT clave, valor FROM configuracion")
    cfg = {r["clave"]: (r["valor"] or "") for r in cfg_rows}

    def hex_to_color(h, fallback="2C5F8A"):
        h = (h or fallback).strip().lstrip("#")
        if len(h) != 6:
            h = fallback
        try:
            return colors.HexColor("#" + h)
        except Exception:
            return colors.HexColor("#" + fallback)

    PRIMARY   = hex_to_color(cfg.get("pdf_color_hex"), "2C5F8A")
    PRIMARY_L = colors.HexColor("#ECF3FA")   # light variant for alternating rows
    GRAY_L    = colors.HexColor("#F5F5F5")
    GRAY_D    = colors.HexColor("#CCCCCC")
    WHITE     = colors.white
    BLACK     = colors.HexColor("#1A1A1A")
    MUTED     = colors.HexColor("#666666")

    mostrar_costos  = cfg.get("pdf_mostrar_costos",  "0") == "1"
    mostrar_precios = cfg.get("pdf_mostrar_precios", "0") == "1"

    empresa_nombre    = cfg.get("empresa_nombre",    "MetalERP Taller")
    empresa_subtitulo = cfg.get("empresa_subtitulo", "")
    empresa_dir       = cfg.get("empresa_direccion", "")
    empresa_tel       = cfg.get("empresa_telefono",  "")
    empresa_email     = cfg.get("empresa_email",     "")
    nota_pie          = cfg.get("pdf_nota_pie",      "")

    # ── Estilos ──────────────────────────────────────────────────────────────
    def sty(size=9, bold=False, color=None, align=TA_LEFT, leading=None, space_after=0):
        return ParagraphStyle(
            name=f"s{size}{'b' if bold else ''}",
            fontSize=size,
            fontName="Helvetica-Bold" if bold else "Helvetica",
            textColor=color or BLACK,
            alignment=align,
            leading=leading or size * 1.35,
            spaceAfter=space_after,
        )

    def P(text, **kw):
        return Paragraph(str(text or "—"), sty(**kw))

    def fmt_date(d):
        if not d: return "—"
        try: return datetime.strptime(d[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
        except: return str(d)

    def fmt_money(n):
        try: return f"$ {float(n or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        except: return "$ 0,00"

    # ── Documento ────────────────────────────────────────────────────────────
    W, H = A4
    M = 15 * mm
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=M, rightMargin=M,
        topMargin=M, bottomMargin=M,
        title=f"OT {ot['numero']}",
    )
    CW = W - 2 * M
    story = []

    # ── 1. Encabezado ─────────────────────────────────────────────────────────
    estado_color = {
        "Pendiente":  colors.HexColor("#E65100"),
        "En proceso": PRIMARY,
        "Completada": colors.HexColor("#1B5E20"),
        "Cancelada":  colors.HexColor("#A32D2D"),
    }.get(ot["estado"], BLACK)

    # Tabla encabezado: empresa (izq) | número OT (der)
    empresa_lines = [empresa_nombre]
    if empresa_subtitulo: empresa_lines.append(empresa_subtitulo)
    contact_parts = [p for p in [empresa_dir, empresa_tel, empresa_email] if p]
    empresa_txt = "<br/>".join(
        [f'<font size="12"><b>{empresa_lines[0]}</b></font>'] +
        ([f'<font size="9" color="#555555">{empresa_lines[1]}</font>'] if len(empresa_lines) > 1 else []) +
        ([f'<font size="8" color="#888888">{" · ".join(contact_parts)}</font>'] if contact_parts else [])
    )

    hdr = Table([[
        Paragraph(empresa_txt, sty(size=10)),
        Table([[
            P("ORDEN DE TRABAJO", size=8, bold=True, color=MUTED, align=TA_RIGHT),
            P(ot["numero"], size=20, bold=True, color=PRIMARY, align=TA_RIGHT),
        ]], colWidths=[30*mm, 40*mm],
           style=TableStyle([("VALIGN",(0,0),(-1,-1),"BOTTOM"),("BOTTOMPADDING",(0,0),(-1,-1),0)])),
    ]], colWidths=[CW - 72*mm, 72*mm])
    hdr.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("LINEBELOW", (0,0), (-1,0), 2, PRIMARY),
        ("BOTTOMPADDING", (0,0), (-1,0), 6),
        ("TOPPADDING", (0,0), (-1,0), 2),
    ]))
    story.append(hdr)
    story.append(Spacer(1, 4*mm))

    # ── 2. Ficha OT ───────────────────────────────────────────────────────────
    estado_badge = (
        f'<font color="{estado_color.hexval()}"><b>{ot["estado"].upper()}</b></font>'
    )
    prio_map = {"Alta": "🔴", "Media": "🟡", "Baja": "🟢", "Urgente": "🔴🔴"}

    info_data = [
        [P("Producto / descripción", size=8, bold=True, color=MUTED),
         P(ot["producto_nombre"] or ot["descripcion"] or "—", size=9),
         P("Estado", size=8, bold=True, color=MUTED),
         Paragraph(estado_badge, sty(size=10, bold=True))],

        [P("Cliente", size=8, bold=True, color=MUTED),
         P(ot["cliente_nombre"] or "—", size=9),
         P("Prioridad", size=8, bold=True, color=MUTED),
         P(ot["prioridad"] or "—", size=9)],

        [P("Cantidad", size=8, bold=True, color=MUTED),
         P(str(ot["cantidad"]), size=9),
         P("Fecha inicio", size=8, bold=True, color=MUTED),
         P(fmt_date(ot["fecha_inicio"]), size=9)],

        [P("Costo material" if mostrar_costos else "Fecha entrega",
           size=8, bold=True, color=MUTED),
         P(fmt_money(ot["costo_mat"]) if mostrar_costos else fmt_date(ot["fecha_entrega"]), size=9),
         P("Fecha entrega" if mostrar_costos else "Precio venta",
           size=8, bold=True, color=MUTED),
         P(fmt_date(ot["fecha_entrega"]) if mostrar_costos else
           (fmt_money(ot["precio_venta"]) if mostrar_precios else "—"), size=9)],
    ]

    c1, c2, c3, c4 = 32*mm, CW/2-32*mm, 28*mm, CW/2-28*mm
    info_tbl = Table(info_data, colWidths=[c1, c2, c3, c4])
    info_tbl.setStyle(TableStyle([
        ("GRID",            (0,0), (-1,-1), 0.4, GRAY_D),
        ("BACKGROUND",      (0,0), (0,-1), PRIMARY_L),
        ("BACKGROUND",      (2,0), (2,-1), PRIMARY_L),
        ("ROWBACKGROUNDS",  (0,0), (-1,-1), [WHITE, GRAY_L]),
        ("VALIGN",          (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING",      (0,0), (-1,-1), 4),
        ("BOTTOMPADDING",   (0,0), (-1,-1), 4),
        ("LEFTPADDING",     (0,0), (-1,-1), 5),
    ]))
    story.append(info_tbl)

    if ot["obs"]:
        story.append(Spacer(1, 2*mm))
        obs_tbl = Table([[
            P("Observaciones:", size=8, bold=True, color=MUTED),
            P(ot["obs"], size=8, color=MUTED),
        ]], colWidths=[32*mm, CW-32*mm])
        obs_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,-1), colors.HexColor("#FFFDE7")),
            ("GRID", (0,0), (-1,-1), 0.3, GRAY_D),
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            ("TOPPADDING", (0,0), (-1,-1), 4),
            ("BOTTOMPADDING", (0,0), (-1,-1), 4),
            ("LEFTPADDING", (0,0), (-1,-1), 5),
        ]))
        story.append(obs_tbl)

    story.append(Spacer(1, 6*mm))

    # ── 3. Operaciones ────────────────────────────────────────────────────────
    story.append(KeepTogether([
        Table([[P("OPERACIONES", size=10, bold=True, color=WHITE)]],
              colWidths=[CW],
              style=TableStyle([
                  ("BACKGROUND", (0,0), (-1,-1), PRIMARY),
                  ("TOPPADDING", (0,0), (-1,-1), 5),
                  ("BOTTOMPADDING", (0,0), (-1,-1), 5),
                  ("LEFTPADDING", (0,0), (-1,-1), 6),
              ])),
    ]))

    if ops:
        op_head = [
            P("Ord.", size=8, bold=True, color=WHITE, align=TA_CENTER),
            P("Operación", size=8, bold=True, color=WHITE),
            P("Sector / Máquina", size=8, bold=True, color=WHITE),
            P("Setup (min)", size=8, bold=True, color=WHITE, align=TA_CENTER),
            P("Ciclo (min)", size=8, bold=True, color=WHITE, align=TA_CENTER),
            P("Cant. req.", size=8, bold=True, color=WHITE, align=TA_CENTER),
            P("Estado", size=8, bold=True, color=WHITE, align=TA_CENTER),
            P("Firma / V°B°", size=8, bold=True, color=WHITE, align=TA_CENTER),
        ]
        op_rows = [op_head]
        for op in ops:
            est_c = {
                "Pendiente":  colors.HexColor("#E65100"),
                "En proceso": PRIMARY,
                "Completada": colors.HexColor("#1B5E20"),
            }.get(op["estado"], MUTED)

            tercerizado = op["es_tercerizada"] if "es_tercerizada" in op.keys() else 0
            if tercerizado:
                sector = f'<font color="#A32D2D"><b>TERC.</b></font> {op["proveedor_nombre"] or "—"}'
            else:
                sector = op["cat_maquina_nombre"] or "—"
                if op["maquina_nombre"]:
                    sector += f'<br/><font size="7" color="#888888">{op["maquina_nombre"]}</font>'

            op_rows.append([
                P(op["orden"], size=8, align=TA_CENTER),
                Paragraph(op["nombre"], sty(size=8)),
                Paragraph(sector, sty(size=8)),
                P(op["tiempo_setup_min"] or 0, size=8, align=TA_CENTER),
                P(op["tiempo_ciclo_min"] or 0, size=8, align=TA_CENTER),
                P(op["qty_requerida"] or 0, size=8, align=TA_CENTER),
                Paragraph(f'<font color="{est_c.hexval()}"><b>{op["estado"]}</b></font>',
                          sty(size=7, align=TA_CENTER)),
                P("", size=8),   # firma
            ])

        op_tbl = Table(op_rows,
            colWidths=[10*mm, 48*mm, 42*mm, 16*mm, 16*mm, 16*mm, 22*mm, 10*mm])
        op_tbl.setStyle(TableStyle([
            ("BACKGROUND",     (0,0), (-1,0), PRIMARY),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [WHITE, PRIMARY_L]),
            ("GRID",           (0,0), (-1,-1), 0.4, GRAY_D),
            ("VALIGN",         (0,0), (-1,-1), "MIDDLE"),
            ("TOPPADDING",     (0,0), (-1,-1), 4),
            ("BOTTOMPADDING",  (0,0), (-1,-1), 4),
            ("LEFTPADDING",    (0,0), (-1,-1), 4),
            # Firma box: thicker border
            ("BOX",            (7,1), (7,-1), 0.8, GRAY_D),
        ]))
        story.append(op_tbl)
    else:
        story.append(Table([[P("Sin operaciones registradas.", size=8, color=MUTED)]],
            colWidths=[CW], style=TableStyle([
                ("BACKGROUND", (0,0), (-1,-1), GRAY_L),
                ("TOPPADDING", (0,0), (-1,-1), 6),
                ("BOTTOMPADDING", (0,0), (-1,-1), 6),
                ("LEFTPADDING", (0,0), (-1,-1), 6),
            ])))

    story.append(Spacer(1, 6*mm))

    # ── 4. Materiales ─────────────────────────────────────────────────────────
    story.append(KeepTogether([
        Table([[P("MATERIALES / INSUMOS", size=10, bold=True, color=WHITE)]],
              colWidths=[CW],
              style=TableStyle([
                  ("BACKGROUND", (0,0), (-1,-1), PRIMARY),
                  ("TOPPADDING", (0,0), (-1,-1), 5),
                  ("BOTTOMPADDING", (0,0), (-1,-1), 5),
                  ("LEFTPADDING", (0,0), (-1,-1), 6),
              ])),
    ]))

    if mats:
        mat_head = [
            P("Código", size=8, bold=True, color=WHITE),
            P("Descripción", size=8, bold=True, color=WHITE),
            P("Cant. requerida", size=8, bold=True, color=WHITE, align=TA_CENTER),
            P("Cant. asignada", size=8, bold=True, color=WHITE, align=TA_CENTER),
            P("Unidad", size=8, bold=True, color=WHITE, align=TA_CENTER),
            P("Stock disp.", size=8, bold=True, color=WHITE, align=TA_CENTER),
        ]
        mat_rows = [mat_head]
        for m in mats:
            ok = float(m["cantidad_asignada"] or 0) >= float(m["cantidad_requerida"] or 0)
            asn_color = colors.HexColor("#1B5E20") if ok else colors.HexColor("#E65100")
            mat_rows.append([
                P(m["codigo"], size=8),
                Paragraph(m["descripcion"], sty(size=8)),
                P(m["cantidad_requerida"], size=8, align=TA_CENTER),
                Paragraph(
                    f'<font color="{asn_color.hexval()}"><b>{m["cantidad_asignada"]}</b></font>',
                    sty(size=8, align=TA_CENTER)),
                P(m["unidad"], size=8, align=TA_CENTER),
                P(m["stock"], size=8, align=TA_CENTER),
            ])

        mat_tbl = Table(mat_rows,
            colWidths=[25*mm, 70*mm, 26*mm, 26*mm, 18*mm, 15*mm])
        mat_tbl.setStyle(TableStyle([
            ("BACKGROUND",     (0,0), (-1,0), PRIMARY),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [WHITE, PRIMARY_L]),
            ("GRID",           (0,0), (-1,-1), 0.4, GRAY_D),
            ("VALIGN",         (0,0), (-1,-1), "MIDDLE"),
            ("TOPPADDING",     (0,0), (-1,-1), 4),
            ("BOTTOMPADDING",  (0,0), (-1,-1), 4),
            ("LEFTPADDING",    (0,0), (-1,-1), 4),
        ]))
        story.append(mat_tbl)
    else:
        story.append(Table([[P("Sin materiales registrados.", size=8, color=MUTED)]],
            colWidths=[CW], style=TableStyle([
                ("BACKGROUND", (0,0), (-1,-1), GRAY_L),
                ("TOPPADDING", (0,0), (-1,-1), 6),
                ("BOTTOMPADDING", (0,0), (-1,-1), 6),
                ("LEFTPADDING", (0,0), (-1,-1), 6),
            ])))

    story.append(Spacer(1, 8*mm))

    # ── 5. Firmas ─────────────────────────────────────────────────────────────
    firma_head = [
        P("Emitido por", size=7, color=MUTED, align=TA_CENTER),
        P("Supervisor de producción", size=7, color=MUTED, align=TA_CENTER),
        P("Control de calidad", size=7, color=MUTED, align=TA_CENTER),
    ]
    firma_sign = [P("", size=7), P("", size=7), P("", size=7)]
    firma_label = [
        P("Firma y aclaración", size=6, color=GRAY_D, align=TA_CENTER),
        P("Firma y aclaración", size=6, color=GRAY_D, align=TA_CENTER),
        P("Firma y aclaración", size=6, color=GRAY_D, align=TA_CENTER),
    ]
    fw = CW / 3
    firma_tbl = Table(
        [firma_head, firma_sign, firma_label],
        colWidths=[fw, fw, fw],
        rowHeights=[8*mm, 18*mm, 6*mm],
    )
    firma_tbl.setStyle(TableStyle([
        ("BOX",        (0,0), (-1,-1), 0.5, GRAY_D),
        ("INNERGRID",  (0,0), (-1,-1), 0.4, GRAY_D),
        ("BACKGROUND", (0,0), (-1,0),  PRIMARY_L),
        ("BACKGROUND", (0,2), (-1,2),  GRAY_L),
        ("LINEBELOW",  (0,1), (-1,1),  0.8, BLACK),
        ("VALIGN",     (0,0), (-1,-1), "BOTTOM"),
        ("ALIGN",      (0,0), (-1,-1), "CENTER"),
        ("TOPPADDING", (0,0), (-1,-1), 3),
        ("BOTTOMPADDING",(0,0),(-1,-1),3),
    ]))
    story.append(KeepTogether([firma_tbl]))

    # ── 6. Nota al pie + footer ───────────────────────────────────────────────
    if nota_pie:
        story.append(Spacer(1, 3*mm))
        story.append(HRFlowable(width="100%", thickness=0.5, color=GRAY_D))
        story.append(Paragraph(nota_pie, sty(size=7.5, color=MUTED, space_after=0)))

    story.append(Spacer(1, 3*mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=GRAY_D))
    ahora = datetime.now().strftime("%d/%m/%Y %H:%M")
    story.append(Paragraph(
        f'MetalERP v3 · {ot["numero"]} · Generado el {ahora}',
        sty(size=7, color=GRAY_D, align=TA_CENTER)))

    # ── Build ─────────────────────────────────────────────────────────────────
    doc.build(story)
    buf.seek(0)
    return send_file(buf, mimetype="application/pdf",
                     as_attachment=False,
                     download_name=f'{ot["numero"]}.pdf')


# ── Gestión de archivos de producto ──────────────────────────────────────────
import os as _os, mimetypes as _mimetypes
from werkzeug.utils import secure_filename as _secure

FILES_BASE = _os.path.join(_os.path.dirname(__file__), "documentos")

def _prod_dir(pid):
    """Returns the directory path for a product's files, creating it if needed."""
    prod = query("SELECT codigo FROM productos WHERE id=?", (pid,), one=True)
    if not prod:
        return None, None
    safe_code = "".join(c if c.isalnum() or c in "-_." else "_" for c in prod["codigo"])
    path = _os.path.join(FILES_BASE, f"{safe_code}__{pid}")
    _os.makedirs(path, exist_ok=True)
    return path, prod["codigo"]

# ── Versiones de producto ─────────────────────────────────────────────────────
@app.route("/api/productos/<int:pid>/versiones", methods=["GET"])
@login_required()
def list_versiones(pid):
    import json
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

@app.route("/api/productos/<int:pid>/archivos", methods=["GET"])
@login_required()
def list_archivos(pid):
    path, codigo = _prod_dir(pid)
    if not path:
        return jsonify({"error": "Producto no encontrado"}), 404
    files = []
    for fname in sorted(_os.listdir(path)):
        fpath = _os.path.join(path, fname)
        if _os.path.isfile(fpath):
            stat = _os.stat(fpath)
            mime, _ = _mimetypes.guess_type(fname)
            files.append({
                "nombre": fname,
                "size":   stat.st_size,
                "mime":   mime or "application/octet-stream",
                "is_img": (mime or "").startswith("image/"),
                "is_pdf": mime == "application/pdf",
            })
    return jsonify({"archivos": files, "carpeta": path})

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
    safe = _secure(f.filename)
    dest = _os.path.join(path, safe)
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
    fpath = _os.path.join(path, nombre)
    if not _os.path.isfile(fpath):
        return jsonify({"error": "Archivo no encontrado"}), 404
    _os.remove(fpath)
    return jsonify({"ok": True})

# ── Cargas masivas ────────────────────────────────────────────────────────────
@app.route("/api/bulk/schema", methods=["GET"])
@login_required(roles=["admin"])
def get_bulk_schema():
    """Returns all tables with their columns (excluding system tables and PKs)."""
    import sqlite3 as _sq
    db2 = _sq.connect(DB_PATH)
    tables = db2.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT IN "
        "('sqlite_sequence') ORDER BY name").fetchall()
    result = {}
    for (tname,) in tables:
        cols = db2.execute(f"PRAGMA table_info({tname})").fetchall()
        # cid, name, type, notnull, default, pk
        result[tname] = [
            {"name": r[1], "type": r[2], "notnull": bool(r[3]),
             "default": r[4], "pk": bool(r[5])}
            for r in cols
        ]
    db2.close()
    return jsonify(result)

@app.route("/api/bulk/import", methods=["POST"])
@login_required(roles=["admin"])
def bulk_import():
    """Imports rows from JSON payload: {table: str, rows: list[dict], mode: 'insert'|'upsert'}"""
    d = request.json
    table  = d.get("table", "")
    rows   = d.get("rows", [])
    mode   = d.get("mode", "insert")   # insert = always insert, upsert = INSERT OR REPLACE

    if not table or not rows:
        return jsonify({"error": "table y rows requeridos"}), 400

    # Whitelist: only real tables
    import sqlite3 as _sq
    db2 = _sq.connect(DB_PATH)
    valid = {r[0] for r in db2.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    db2.close()

    if table not in valid:
        return jsonify({"error": f"Tabla '{table}' no existe"}), 400
    if table in ("usuarios", "sqlite_sequence"):
        return jsonify({"error": "Tabla protegida"}), 403

    # Get column names (skip 'id' for plain inserts unless provided)
    pragma = query(f"PRAGMA table_info({table})")
    col_meta = {r["name"]: r for r in pragma}

    inserted = 0
    errors = []
    cmd = "INSERT OR REPLACE" if mode == "upsert" else "INSERT OR IGNORE"

    # Get FK info for this table to nullify invalid references
    import sqlite3 as _sq3
    _db_fk = _sq3.connect(DB_PATH)
    fk_info = _db_fk.execute(f"PRAGMA foreign_key_list({table})").fetchall()
    # fk_info: (id, seq, table, from, to, on_update, on_delete, match)
    fk_cols = {row[3]: (row[2], row[4]) for row in fk_info}  # {col: (ref_table, ref_col)}
    _db_fk.close()

    for i, row in enumerate(rows):
        # Only keep columns that exist in the table
        valid_row = {k: v for k, v in row.items() if k in col_meta}
        # Remove 'id' for plain inserts (let autoincrement handle it)
        if mode == "insert" and "id" in valid_row:
            del valid_row["id"]
        if not valid_row:
            errors.append(f"Fila {i+1}: sin columnas válidas")
            continue
        # Nullify FK columns with empty/zero/nonexistent values
        for col, (ref_table, ref_col) in fk_cols.items():
            if col in valid_row:
                val = valid_row[col]
                # If blank, None, or 0 — set to NULL (avoids FK error)
                if val is None or val == "" or val == 0:
                    valid_row[col] = None
                else:
                    # Check if referenced value exists
                    try:
                        exists = query(f"SELECT 1 FROM {ref_table} WHERE {ref_col}=?",
                                       (val,), one=True)
                        if not exists:
                            valid_row[col] = None  # silently nullify invalid FK
                    except Exception:
                        valid_row[col] = None
        cols_str = ", ".join(valid_row.keys())
        placeholders = ", ".join("?" * len(valid_row))
        try:
            execute(f"{cmd} INTO {table} ({cols_str}) VALUES ({placeholders})",
                    list(valid_row.values()))
            inserted += 1
        except Exception as e:
            errors.append(f"Fila {i+1}: {str(e)[:80]}")

    return jsonify({"ok": True, "inserted": inserted,
                    "errors": errors, "total": len(rows)})

# ── Debug / diagnóstico ───────────────────────────────────────────────────────
@app.route("/api/debug/pt_materiales")
@login_required(roles=["admin"])
def debug_pt_materiales():
    """Diagnóstico: muestra estado de materiales PT y ejecuta migración si faltan."""
    db = get_db()
    prods = query("SELECT id,codigo,nombre,unidad FROM productos")
    result = []
    for p in prods:
        existia = query("SELECT id FROM materiales WHERE producto_id=?", (p["id"],), one=True)
        mat = get_or_create_pt_material(p)
        result.append({"producto": p["codigo"], "accion": "ok" if existia else "creado",
                        "mat_id": mat["id"], "stock": mat.get("stock", 0)})
    return jsonify({"ok": True, "productos": result})


@app.route("/diagnostico")
@login_required(roles=["admin"])
def diagnostico_page():
    """Diagnóstico completo server-side — corre el test y devuelve HTML con resultados."""
    lines = []

    def ok(msg):  lines.append(f'<div class="ok">✓ {msg}</div>')
    def err(msg): lines.append(f'<div class="err">✗ {msg}</div>')
    def info(msg):lines.append(f'<div class="info">→ {msg}</div>')
    def sep(msg): lines.append(f'<div class="sep">{msg}</div>')

    sep("1. Productos y sus materiales PT")
    prods = query("SELECT id,codigo,nombre,unidad FROM productos")
    for p in prods:
        existia = query("SELECT id FROM materiales WHERE producto_id=?", (p["id"],), one=True)
        mat = get_or_create_pt_material(p)
        if existia:
            ok(f"Producto {p['codigo']} — mat_id={mat['id']} stock={mat.get('stock',0)}")
        else:
            ok(f"Producto {p['codigo']} — material PT creado ahora, mat_id={mat['id']}")

    sep("2. OTs activas y sus operaciones")
    ots = query("SELECT o.*,p.nombre prod_nombre,p.codigo prod_codigo FROM ordenes o LEFT JOIN productos p ON p.id=o.producto_id WHERE o.estado IN ('Pendiente','En proceso') ORDER BY o.id DESC")
    for ot in ots:
        ops = query("SELECT * FROM orden_operaciones WHERE orden_id=? ORDER BY CAST(orden AS INTEGER), orden", (ot["id"],))
        proc_ops = query("SELECT * FROM proceso_operaciones WHERE producto_id=? ORDER BY CAST(orden AS INTEGER), orden", (ot["producto_id"],)) if ot["producto_id"] else []
        info(f"OT {ot['numero']} (id={ot['id']}) — producto: {ot['prod_nombre'] or 'SIN PRODUCTO'} — ops OT: {len(ops)} — ops proceso: {len(proc_ops)}")
        if not ot["producto_id"]:
            err(f"  OT {ot['numero']} no tiene producto asignado — no puede generar PT")
        elif len(proc_ops) == 0:
            err(f"  Producto {ot['prod_codigo']} no tiene operaciones en el proceso — definir en Procesos/Productos")
        elif len(ops) == 0:
            info(f"  OT {ot['numero']} no tiene ops cargadas — se pueden poblar desde el proceso")
        else:
            max_ord = max(op["orden"] for op in ops)
            ok(f"  {len(ops)} operaciones cargadas. Última: orden={max_ord}")
            for op in ops:
                info(f"    op id={op['id']} orden={op['orden']} nombre={op['nombre']} qty_req={op['qty_requerida']} qty_prod={op['qty_producida']}")

    test_ot_id = int(request.args.get('ot', 1))
    sep(f"3. Test directo en OT id={test_ot_id} (cambiá ?ot=N en la URL para otra OT)")
    ot6 = query("SELECT o.*,p.codigo prod_codigo FROM ordenes o LEFT JOIN productos p ON p.id=o.producto_id WHERE o.id=?", (test_ot_id,), one=True)
    if not ot6:
        err(f"OT id={test_ot_id} no encontrada en esta base de datos")
    elif not ot6["producto_id"]:
        err(f"OT-{test_ot_id} no tiene producto asignado")
    else:
        info(f"OT-6: producto_id={ot6['producto_id']} codigo={ot6['prod_codigo']} cantidad={ot6['cantidad']}")
        proc_ops = query("SELECT * FROM proceso_operaciones WHERE producto_id=? ORDER BY CAST(orden AS INTEGER), orden", (ot6["producto_id"],))
        info(f"Operaciones en proceso del producto: {len(proc_ops)}")
        for op in proc_ops:
            info(f"  op id={op['id']} orden={op['orden']} nombre={op['nombre']}")

        execute("DELETE FROM orden_operaciones WHERE orden_id=?", (test_ot_id,))
        for op in proc_ops:
            execute("""INSERT INTO orden_operaciones
                (orden_id,proceso_op_id,orden,nombre,categoria_maquina_id,maquina_id,
                 tiempo_setup_min,tiempo_ciclo_min,estado,qty_requerida)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (test_ot_id, op["id"], op["orden"], op["nombre"], op["categoria_maquina_id"],
                 op["maquina_id"], op["tiempo_setup_min"], op["tiempo_ciclo_min"],
                 "Pendiente", ot6["cantidad"]))
        ok(f"Pobladas {len(proc_ops)} operaciones en OT-6")

        ops6 = query("SELECT * FROM orden_operaciones WHERE orden_id=? ORDER BY CAST(orden AS INTEGER), orden", (test_ot_id,))
        if ops6:
            last = max(ops6, key=lambda o: o["orden"])
            info(f"Última operación: id={last['id']} orden={last['orden']} nombre={last['nombre']} qty_req={last['qty_requerida']}")

            # Simulate declaring novedad on last op
            sep("4. Simulando novedad en última operación de OT-6")
            qty = float(last["qty_requerida"] or 1)
            std = float(last["tiempo_ciclo_min"] or 1)
            rendimiento = round((qty / qty) * 100, 1)

            last_n = query("SELECT numero FROM novedades_produccion ORDER BY id DESC LIMIT 1", one=True)
            try: n = int(last_n["numero"].split("-")[1])+1 if last_n else 1
            except: n = 1
            numero = f"NOV-TEST-{n:05d}"

            nov_id = execute("""INSERT INTO novedades_produccion
                (numero,orden_id,orden_operacion_id,cantidad_producida,tiempo_real_min,
                 rendimiento_pct,desvio,creado_por)
                VALUES (?,?,?,?,?,?,?,?)""",
                (numero, test_ot_id, last["id"], qty, qty*std, rendimiento, 0, 1))
            execute("UPDATE orden_operaciones SET qty_producida=qty_producida+? WHERE id=?", (qty, last["id"]))
            ok(f"Novedad {numero} insertada (id={nov_id}) qty={qty}")

            # Check PT generation
            max_orden = query("SELECT MAX(CAST(orden AS INTEGER)) mo FROM orden_operaciones WHERE orden_id=?", (test_ot_id,), one=True)["mo"]
            es_ultima = (last["orden"] == max_orden)
            info(f"Es última operación: {es_ultima} (orden={last['orden']} max={max_orden})")

            op_actual = query("SELECT qty_requerida,qty_producida FROM orden_operaciones WHERE id=?", (last["id"],), one=True)
            qty_req = float(op_actual["qty_requerida"] or 0)
            qty_prod = float(op_actual["qty_producida"] or 0)
            info(f"qty_req={qty_req} qty_prod={qty_prod} genera_PT={es_ultima and qty_prod>=qty_req and qty_req>0}")

            if es_ultima and qty_prod >= qty_req and qty_req > 0:
                prod = query("SELECT * FROM productos WHERE id=?", (ot6["producto_id"],), one=True)
                existia_mat = query("SELECT id FROM materiales WHERE codigo=? AND categoria='Producto terminado'", (prod["codigo"],), one=True)
                mat_pt = get_or_create_pt_material(prod)
                if not existia_mat:
                    info(f"Material PT creado on-the-fly id={mat_pt['id']}")
                stock_antes = mat_pt.get("stock", 0)
                execute(
                    "UPDATE materiales SET stock=stock+?,actualizado=datetime('now','localtime') WHERE id=?",
                    (qty, mat_pt["id"]))
                # Create/update PT lote with OT number
                lotes_ot = query("""SELECT l.numero FROM orden_lotes ol
                    JOIN lotes l ON l.id=ol.lote_id
                    WHERE ol.orden_id=?""", (d["orden_id"],))
                lotes_ref = ", ".join(l["numero"] for l in lotes_ot) if lotes_ot else "—"
                ot_row = query("SELECT numero FROM ordenes WHERE id=?", (d["orden_id"],), one=True)
                ot_lote_num = ot_row["numero"] if ot_row else numero
                lote_pt_row = query("SELECT id FROM lotes WHERE numero=? AND material_id=?",
                    (ot_lote_num, mat_pt["id"]), one=True)
                if lote_pt_row:
                    execute("""UPDATE lotes SET
                        cantidad_disponible=cantidad_disponible+?,
                        cantidad_activa=cantidad_activa+?,
                        cantidad_original=cantidad_original+?,
                        estado='Aprobado'
                        WHERE id=?""",
                        (qty, qty, qty, lote_pt_row["id"]))
                    lote_pt_id = lote_pt_row["id"]
                else:
                    lote_pt_id = execute("""INSERT INTO lotes
                        (numero,material_id,cantidad_original,cantidad_disponible,
                         cantidad_activa,referencia_proveedor,estado,obs,creado_por)
                        VALUES (?,?,?,?,?,?,?,?,?)""",
                        (ot_lote_num, mat_pt["id"], qty, qty, qty,
                         f"Generado desde OT {ot_lote_num}",
                         "Aprobado", f"Lotes MP usados: {lotes_ref}", session["user_id"]))
                execute(
                    "INSERT INTO movimientos (material_id,lote_id,tipo,cantidad,referencia,usuario_id) VALUES (?,?,?,?,?,?)",
                    (mat_pt["id"], lote_pt_id, "entrada", qty,
                     f"Prod. terminada {numero} | Lotes MP: {lotes_ref}",
                     session["user_id"]))
                stock_despues = query("SELECT stock FROM materiales WHERE id=?", (mat_pt["id"],), one=True)["stock"]
                ok(f"Stock PT actualizado: {stock_antes} → {stock_despues} (material id={mat_pt['id']})")
            else:
                err(f"Condición no cumplida para generar PT")

    sep(f"5. Novedades registradas para OT-{test_ot_id}")
    novs = query("""SELECT n.*,oo.nombre op_nombre,oo.orden op_orden
        FROM novedades_produccion n
        JOIN orden_operaciones oo ON oo.id=n.orden_operacion_id
        WHERE n.orden_id=? ORDER BY n.id DESC LIMIT 10""", (test_ot_id,))
    if novs:
        for n in novs:
            info(f"  {n['numero']} op={n['op_nombre']}(ord={n['op_orden']}) qty={n['cantidad_producida']} rend={n['rendimiento_pct']}%")
    else:
        info(f"Sin novedades para OT-{test_ot_id}")

    html_body = "\n".join(lines)
    return f"""<!DOCTYPE html><html><head><title>Diagnóstico MetalERP</title>
<style>
body{{font-family:monospace;padding:24px;background:#111;color:#ccc;line-height:1.6}}
.ok{{color:#86efac}}.err{{color:#fca5a5;font-weight:bold}}.info{{color:#93c5fd}}
.sep{{color:#fde68a;font-weight:bold;margin-top:14px;border-bottom:1px solid #333;padding-bottom:4px}}
</style></head><body>
<h2 style="color:#7dd3fc">Diagnóstico MetalERP — {request.args.get('run','')}</h2>
<a href="/diagnostico?run=1" style="background:#3b82f6;color:#fff;padding:8px 16px;border-radius:5px;text-decoration:none;font-size:13px">▶ Ejecutar diagnóstico</a>
&nbsp;
<a href="/" style="background:#555;color:#fff;padding:8px 16px;border-radius:5px;text-decoration:none;font-size:13px">← Volver al sistema</a>
<hr style="border-color:#333;margin:16px 0">
{html_body if request.args.get('run') else '<div class="info">Presioná "Ejecutar diagnóstico" para correr el test.</div>'}
</body></html>"""

# ── Boot ──────────────────────────────────────────────────────────────────────
def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80)); ip = s.getsockname()[0]; s.close(); return ip
    except: return "127.0.0.1"


@app.route("/api/rendimiento_operarios", methods=["GET"])
@login_required()
def rendimiento_operarios():
    rows = query("""
        SELECT e.id empleado_id, (e.nombre || ' ' || COALESCE(e.apellido,'')) empleado_nombre,
               e.tipo,
               COUNT(n.id) total_novedades,
               COALESCE(ROUND(AVG(n.rendimiento_pct),1),0) avg_rend,
               COALESCE(SUM(n.cantidad_producida),0) total_producido,
               COALESCE(ROUND(SUM(n.tiempo_real_min)/60.0,1),0) total_horas
        FROM empleados e
        LEFT JOIN novedades_produccion n ON n.empleado_id=e.id AND n.cantidad_producida>0 AND n.tiempo_real_min>0
        WHERE e.activo=1
        GROUP BY e.id
        HAVING total_novedades > 0
        ORDER BY avg_rend DESC""")
    return jsonify([dict(r) for r in rows])

if __name__ == "__main__":
    print("="*52+"\n   MetalERP v3.0 - Taller Metalurgico\n"+"="*52)
    init_db()
    ip = get_local_ip()
    
    # 1. Definimos el puerto en una variable única
    PUERTO = 5001
    
    # 2. Usamos la variable en las URLs dinámicamente
    print(f"\n   Local:   http://localhost:{PUERTO}")
    print(f"  Red:     http://{ip}:{PUERTO}")
    print(f"\n   Usuario: admin  |  Contraseña: admin123\n")
    
    # 3. Le pasamos la variable a Flask
    # threaded=True: atiende varias conexiones en paralelo. Sin esto, con
    # varios operarios conectados por la misma wifi, una request lenta
    # (ej. declarar la ultima operacion, que descuenta MP y genera PT)
    # bloqueaba a todas las demas hasta terminar.
    app.run(host="0.0.0.0", port=PUERTO, debug=False, threaded=True)


# fix_obs_proc.py  NOMBRE DEL ARCHIVO DE CORRECCION
#import sqlite3

#c = sqlite3.connect('database/metalerp.db')

# Ver columnas actuales de la tabla que realmente usa el endpoint de edición
#cols = [row[1] for row in c.execute("PRAGMA table_info(proceso_operaciones)").fetchall()]
#print("Columnas actuales de proceso_operaciones:", cols)

#if 'obs' not in cols:
    #c.execute("ALTER TABLE proceso_operaciones ADD COLUMN obs TEXT")
    #c.commit()
    #print("OK: columna 'obs' agregada a proceso_operaciones")
#else:
    #print("OK: columna 'obs' ya existe en proceso_operaciones, no se necesita cambio")

#c.close()

#-------------------------------------------------------------------------------------------------#

#fix_pbs.py   NOMBRE DEL SEGUNDO ARCHIVO DE CORRECCION 
#import sqlite3

#c = sqlite3.connect('database/metalerp.db')

# Ver columnas actuales
#cols = [row[1] for row in c.execute("PRAGMA table_info(orden_operaciones)").fetchall()]
#print("Columnas actuales:", cols)

#if 'obs' not in cols:
    #c.execute("ALTER TABLE orden_operaciones ADD COLUMN obs TEXT")
    #c.commit()
    #print("OK: columna 'obs' agregada a orden_operaciones")
#else:
    #print("OK: columna 'obs' ya existe, no se necesita cambio")

#c.close()

#--------------------------------------------------------------------------------------------------#

#Este archivo se ejecuta nada mas para agregar logistica dentro de los roles de usuario. 
#fix_db.py
#import sqlite3

#c = sqlite3.connect('database/metalerp.db')

#c.execute("DROP TABLE IF EXISTS usuarios_new")

#c.execute("""CREATE TABLE usuarios_new (
    #id INTEGER PRIMARY KEY AUTOINCREMENT,
    #username TEXT UNIQUE NOT NULL,
    #password TEXT NOT NULL,
    #nombre TEXT NOT NULL,
    #rol TEXT NOT NULL CHECK(rol IN ('admin','operario','vendedor','almacen','logistica')),
    #activo INTEGER DEFAULT 1,
    #creado TEXT DEFAULT (datetime('now','localtime')))""")

#c.execute("INSERT INTO usuarios_new SELECT id,username,password,nombre,rol,activo,creado FROM usuarios")
#c.execute("DROP TABLE usuarios")
#c.execute("ALTER TABLE usuarios_new RENAME TO usuarios")
#c.commit()

#r = c.execute("SELECT sql FROM sqlite_master WHERE name='usuarios'").fetchone()
#print("RESULTADO:")
#print(r[0])
#c.close()
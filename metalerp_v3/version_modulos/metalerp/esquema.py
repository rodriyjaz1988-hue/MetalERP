"""Esquema de la base: SCHEMA, migraciones por versión, init_db, reparaciones
y rellenos de datos que corren al arrancar."""
from .nucleo import (_json, app, datetime, DB_PATH, DEFAULT_PERMISIONES, execute, hash_pw,
    os, query, re, sqlite3)

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    nombre TEXT NOT NULL,
    rol TEXT NOT NULL,
    activo INTEGER DEFAULT 1,
    creado TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS categorias_maquina (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT UNIQUE NOT NULL,
    descripcion TEXT,
    creado TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS maquinas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo TEXT UNIQUE NOT NULL,
    nombre TEXT NOT NULL,
    categoria_id INTEGER REFERENCES categorias_maquina(id),
    marca TEXT,
    modelo TEXT,
    numero_serie TEXT,
    anio INTEGER,
    ubicacion TEXT,
    estado TEXT DEFAULT 'Operativa',
    horas_uso REAL DEFAULT 0,
    obs TEXT,
    creado TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS maquina_reemplazos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    maquina_id INTEGER NOT NULL REFERENCES maquinas(id) ON DELETE CASCADE,
    reemplazo_id INTEGER NOT NULL REFERENCES maquinas(id) ON DELETE CASCADE,
    UNIQUE(maquina_id, reemplazo_id)
);

CREATE TABLE IF NOT EXISTS mantenimiento_plan (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    maquina_id INTEGER NOT NULL REFERENCES maquinas(id) ON DELETE CASCADE,
    tarea TEXT NOT NULL,
    tipo TEXT DEFAULT 'Frecuencia fija',
    frecuencia_tipo TEXT,
    frecuencia_valor INTEGER,
    ultima_fecha TEXT,
    proxima_fecha TEXT,
    responsable TEXT,
    obs TEXT,
    creado TEXT DEFAULT (datetime('now','localtime')),
    ultima_horas REAL
);

CREATE TABLE IF NOT EXISTS mantenimiento_registros (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id INTEGER NOT NULL REFERENCES mantenimiento_plan(id) ON DELETE CASCADE,
    maquina_id INTEGER REFERENCES maquinas(id) ON DELETE CASCADE,
    fecha TEXT NOT NULL,
    horas REAL,
    responsable TEXT,
    obs TEXT,
    usuario_id INTEGER REFERENCES usuarios(id),
    creado TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_mant_reg_plan ON mantenimiento_registros(plan_id);

-- Cotización del dólar: una fila por día y tipo (casa) traída de la API, más
-- las cargadas a mano. Vale la última.
CREATE TABLE IF NOT EXISTS cotizaciones_dolar (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT NOT NULL,
    casa TEXT NOT NULL,
    compra REAL,
    venta REAL NOT NULL,
    fuente TEXT DEFAULT 'api',
    fecha_api TEXT,
    usuario_id INTEGER REFERENCES usuarios(id),
    creado TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_cotiz_dolar ON cotizaciones_dolar(casa, fecha);

-- Cambios de la moneda del sistema (pesos <-> dólares) con la cotización usada.
CREATE TABLE IF NOT EXISTS moneda_cambios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT DEFAULT (datetime('now','localtime')),
    origen TEXT NOT NULL,
    destino TEXT NOT NULL,
    cotizacion REAL NOT NULL,
    casa TEXT,
    filas INTEGER,
    backup TEXT,
    usuario_id INTEGER REFERENCES usuarios(id)
);

CREATE TABLE IF NOT EXISTS tickets_reparacion (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    numero TEXT UNIQUE NOT NULL,
    maquina_id INTEGER NOT NULL REFERENCES maquinas(id),
    tipo TEXT DEFAULT 'Correctivo',
    descripcion TEXT NOT NULL,
    prioridad TEXT DEFAULT 'Normal',
    estado TEXT DEFAULT 'Abierto',
    responsable TEXT,
    fecha_apertura TEXT DEFAULT (datetime('now','localtime')),
    fecha_cierre TEXT,
    horas_paro REAL DEFAULT 0,
    costo REAL DEFAULT 0,
    solucion TEXT,
    creado_por INTEGER REFERENCES usuarios(id),
    creado TEXT DEFAULT (datetime('now','localtime')),
    horas_ajuste REAL DEFAULT 0,
    moneda TEXT
);

CREATE TABLE IF NOT EXISTS categorias_producto (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT UNIQUE NOT NULL,
    descripcion TEXT,
    creado TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS proveedores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    razon TEXT NOT NULL,
    cuit TEXT,
    contacto TEXT,
    telefono TEXT,
    email TEXT,
    materiales TEXT,
    plazo_dias INTEGER DEFAULT 3,
    calificacion INTEGER DEFAULT 5,
    estado TEXT DEFAULT 'Activo',
    obs TEXT,
    creado TEXT DEFAULT (datetime('now','localtime')),
    categoria_compra TEXT
);

CREATE TABLE IF NOT EXISTS materiales (
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
    creado TEXT DEFAULT (datetime('now','localtime'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_materiales_producto_categoria_sinop ON materiales(producto_id, categoria) WHERE producto_id IS NOT NULL AND operacion_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_materiales_prod_cat_op_firma ON materiales(producto_id, categoria, operacion_id, COALESCE(pse_firma,'')) WHERE producto_id IS NOT NULL AND operacion_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_materiales_categoria ON materiales(categoria);
CREATE VIEW IF NOT EXISTS productos AS
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
FROM materiales;
CREATE TRIGGER IF NOT EXISTS trg_materiales_pt_alta
    AFTER INSERT ON materiales
    WHEN NEW.categoria='Producto terminado' AND (NEW.producto_id IS NULL OR NEW.producto_id<>NEW.id)
    BEGIN
        UPDATE materiales SET producto_id=NEW.id WHERE id=NEW.id;
    END;
CREATE TRIGGER IF NOT EXISTS trg_materiales_pt_cambio
    AFTER UPDATE OF categoria, producto_id ON materiales
    WHEN NEW.categoria='Producto terminado' AND (NEW.producto_id IS NULL OR NEW.producto_id<>NEW.id)
    BEGIN
        UPDATE materiales SET producto_id=NEW.id WHERE id=NEW.id;
    END;
CREATE TRIGGER IF NOT EXISTS trg_materiales_pt_baja
    AFTER UPDATE OF categoria ON materiales
    WHEN OLD.categoria='Producto terminado' AND NEW.categoria<>'Producto terminado'
         AND NEW.producto_id=NEW.id
    BEGIN
        UPDATE materiales SET producto_id=NULL WHERE id=NEW.id;
    END;

CREATE TABLE IF NOT EXISTS proveedor_materiales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proveedor_id INTEGER NOT NULL REFERENCES proveedores(id) ON DELETE CASCADE,
    material_id INTEGER NOT NULL REFERENCES materiales(id) ON DELETE CASCADE,
    precio_unit REAL DEFAULT 0,
    plazo_dias INTEGER DEFAULT 3,
    es_principal INTEGER DEFAULT 0,
    UNIQUE(proveedor_id, material_id)
);

CREATE TABLE IF NOT EXISTS clientes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    razon TEXT NOT NULL,
    cuit TEXT UNIQUE,
    iva TEXT,
    rubro TEXT,
    localidad TEXT,
    direccion TEXT,
    contacto TEXT,
    cargo TEXT,
    telefono TEXT,
    email TEXT,
    categoria TEXT DEFAULT 'Regular',
    plazo_pago TEXT,
    trabajos TEXT,
    obs TEXT,
    creado TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS proceso_operaciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    producto_id INTEGER NOT NULL REFERENCES materiales(id) ON DELETE CASCADE,
    orden INTEGER DEFAULT 1,
    nombre TEXT NOT NULL,
    descripcion TEXT,
    categoria_maquina_id INTEGER REFERENCES categorias_maquina(id),
    maquina_id INTEGER REFERENCES maquinas(id),
    tiempo_setup_min INTEGER DEFAULT 0,
    tiempo_ciclo_seg REAL DEFAULT 0,
    es_tercerizada INTEGER DEFAULT 0,
    proveedor_id INTEGER REFERENCES proveedores(id),
    precio_tercerizado REAL DEFAULT 0,
    tiempo_minimo_dias INTEGER DEFAULT 0,
    obs TEXT,
    volumen_agrupado INTEGER DEFAULT 0,
    valor_recalculado REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS operacion_materiales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    operacion_id INTEGER NOT NULL REFERENCES proceso_operaciones(id) ON DELETE CASCADE,
    material_id INTEGER REFERENCES materiales(id),
    producto_id INTEGER REFERENCES materiales(id),
    cantidad REAL NOT NULL,
    unidad TEXT,
    tipo TEXT DEFAULT 'material',
    vida_util_herramienta INTEGER
);

CREATE TABLE IF NOT EXISTS ordenes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    numero TEXT UNIQUE NOT NULL,
    cliente_id INTEGER REFERENCES clientes(id),
    producto_id INTEGER REFERENCES materiales(id),
    descripcion TEXT NOT NULL,
    detalle TEXT,
    cantidad REAL DEFAULT 1,
    operario TEXT,
    maquina TEXT,
    prioridad TEXT DEFAULT 'Normal',
    estado TEXT DEFAULT 'Pendiente',
    fecha_inicio TEXT,
    fecha_entrega TEXT,
    costo_mat REAL DEFAULT 0,
    costo_mo REAL DEFAULT 0,
    precio_venta REAL DEFAULT 0,
    obs TEXT,
    creado TEXT DEFAULT (datetime('now','localtime')),
    actualizado TEXT DEFAULT (datetime('now','localtime')),
    stock_descontado INTEGER DEFAULT 0,
    requiere_material INTEGER DEFAULT 1,
    moneda TEXT
);

-- Pedidos de cotización que llegan de clientes (pestaña dentro de
-- Presupuestos). Un pedido = un producto terminado, una cantidad y el precio
-- total por esa cantidad; el unitario se deriva en pantalla.
-- Negociación cliente <-> taller: Pendiente (le toca al taller) -> Cotizada
-- (el taller mandó precio) -> Aprobada / Rechazada (finales) o contraoferta
-- del cliente, que vuelve a Pendiente con ronda+1. precio_total y cantidad son
-- los vigentes de la ronda; cada paso queda en pedidos_cotizacion_historial.
CREATE TABLE IF NOT EXISTS pedidos_cotizacion (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    numero TEXT UNIQUE NOT NULL,
    fecha TEXT NOT NULL DEFAULT (date('now','localtime')),
    cliente_id INTEGER NOT NULL REFERENCES clientes(id),
    producto_id INTEGER NOT NULL REFERENCES materiales(id),
    cantidad REAL NOT NULL CHECK(cantidad > 0),
    precio_total REAL,
    creado_por INTEGER REFERENCES usuarios(id),
    creado TEXT DEFAULT (datetime('now','localtime')),
    moneda TEXT,
    estado TEXT NOT NULL DEFAULT 'Pendiente' CHECK(estado IN ('Pendiente','Cotizada','Aprobada','Rechazada')),
    estado_motivo TEXT,
    estado_por INTEGER REFERENCES usuarios(id),
    estado_fecha TEXT,
    descripcion TEXT,
    ronda INTEGER NOT NULL DEFAULT 1
);

-- Cada paso de la negociación de un pedido de cotización: cantidad y precio
-- total vigentes después del evento.
CREATE TABLE IF NOT EXISTS pedidos_cotizacion_historial (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pedido_id INTEGER NOT NULL REFERENCES pedidos_cotizacion(id) ON DELETE CASCADE,
    ronda INTEGER NOT NULL,
    evento TEXT NOT NULL CHECK(evento IN ('Solicitud','Cotización','Contraoferta','Aprobación','Rechazo','Reapertura')),
    cantidad REAL,
    precio_total REAL,
    nota TEXT,
    usuario_id INTEGER REFERENCES usuarios(id),
    fecha TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS ix_pcot_historial_pedido ON pedidos_cotizacion_historial(pedido_id);

-- Cajones: piezas físicas de una OT agrupadas desde la 1ª operación hasta que
-- Calidad las libera (numero = cajon-<código de la pieza>-NNN, nunca se
-- reutiliza: un cajón no se borra, pasa a Baja). Lo que hizo cada paso en
-- cada cajón queda en novedad_cajones (operaciones internas) y ott_cajones
-- (tercerizadas); lo que salió por remito, en remito_item_cajones.
CREATE TABLE IF NOT EXISTS cajones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    numero TEXT UNIQUE NOT NULL,
    orden_id INTEGER REFERENCES ordenes(id),   -- NULL: bulto de una recepción de compra
    orden_origen_id INTEGER REFERENCES ordenes(id),
    producto_id INTEGER NOT NULL REFERENCES materiales(id),
    lote_id INTEGER REFERENCES lotes(id),
    capacidad INTEGER NOT NULL,
    cantidad REAL NOT NULL DEFAULT 0,
    cantidad_liberada REAL NOT NULL DEFAULT 0,
    cantidad_rechazada REAL NOT NULL DEFAULT 0,
    cantidad_remitida REAL NOT NULL DEFAULT 0,
    estado TEXT NOT NULL DEFAULT 'En proceso',
    calidad_por INTEGER REFERENCES usuarios(id),
    calidad_fecha TEXT,
    calidad_obs TEXT,
    obs TEXT,
    creado TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_cajones_orden ON cajones(orden_id);
CREATE INDEX IF NOT EXISTS idx_cajones_lote ON cajones(lote_id);

CREATE TABLE IF NOT EXISTS novedad_cajones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    novedad_id INTEGER NOT NULL REFERENCES novedades_produccion(id) ON DELETE CASCADE,
    cajon_id INTEGER NOT NULL REFERENCES cajones(id),
    cantidad REAL NOT NULL CHECK(cantidad > 0),
    UNIQUE(novedad_id, cajon_id)
);
CREATE INDEX IF NOT EXISTS idx_novedad_cajones_cajon ON novedad_cajones(cajon_id);

CREATE TABLE IF NOT EXISTS ott_cajones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    orden_operacion_id INTEGER NOT NULL REFERENCES orden_operaciones(id) ON DELETE CASCADE,
    cajon_id INTEGER NOT NULL REFERENCES cajones(id),
    cantidad REAL NOT NULL CHECK(cantidad > 0),
    UNIQUE(orden_operacion_id, cajon_id)
);
CREATE INDEX IF NOT EXISTS idx_ott_cajones_cajon ON ott_cajones(cajon_id);

CREATE TABLE IF NOT EXISTS remito_item_cajones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    remito_item_id INTEGER NOT NULL REFERENCES remito_items(id) ON DELETE CASCADE,
    cajon_id INTEGER NOT NULL REFERENCES cajones(id),
    cantidad REAL NOT NULL CHECK(cantidad > 0)
);
CREATE INDEX IF NOT EXISTS idx_remito_item_cajones_cajon ON remito_item_cajones(cajon_id);

CREATE TABLE IF NOT EXISTS presupuestos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    numero TEXT UNIQUE NOT NULL,
    cliente_id INTEGER REFERENCES clientes(id),
    descripcion TEXT NOT NULL,
    items TEXT,
    subtotal REAL DEFAULT 0,
    iva_pct REAL DEFAULT 21,
    total REAL DEFAULT 0,
    validez_dias INTEGER DEFAULT 30,
    estado TEXT DEFAULT 'Borrador',
    obs TEXT,
    creado TEXT DEFAULT (datetime('now','localtime')),
    moneda TEXT
);

CREATE TABLE IF NOT EXISTS lotes (
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
    creado TEXT DEFAULT (datetime('now','localtime')),
    stock_computado INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS remitos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    numero TEXT UNIQUE NOT NULL,
    cliente_id INTEGER REFERENCES clientes(id),
    orden_cliente_id INTEGER REFERENCES ordenes_cliente(id),
    fecha TEXT DEFAULT (datetime('now','localtime')),
    estado TEXT DEFAULT 'Emitido',
    obs TEXT,
    creado_por INTEGER REFERENCES usuarios(id),
    creado TEXT DEFAULT (datetime('now','localtime')),
    tipo TEXT DEFAULT 'entrega_cliente',
    ott_id INTEGER REFERENCES ordenes_tercerizado(id),
    oc_id INTEGER REFERENCES ordenes_compra(id),
    ott_cantidad REAL
);

CREATE TABLE IF NOT EXISTS remito_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    remito_id INTEGER NOT NULL REFERENCES remitos(id) ON DELETE CASCADE,
    material_id INTEGER NOT NULL REFERENCES materiales(id),
    lote_id INTEGER NOT NULL REFERENCES lotes(id),
    orden_cliente_item_id INTEGER REFERENCES ordenes_cliente_items(id),
    cantidad REAL NOT NULL,
    obs TEXT
);

CREATE TABLE IF NOT EXISTS orden_lotes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    orden_id INTEGER NOT NULL REFERENCES ordenes(id) ON DELETE CASCADE,
    lote_id INTEGER NOT NULL REFERENCES lotes(id),
    material_id INTEGER NOT NULL REFERENCES materiales(id),
    cantidad_usada REAL NOT NULL,
    fecha TEXT DEFAULT (datetime('now','localtime')),
    cantidad_consumida REAL DEFAULT 0,
    UNIQUE(orden_id, lote_id)
);

CREATE TABLE IF NOT EXISTS movimientos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    material_id INTEGER REFERENCES materiales(id),
    lote_id INTEGER REFERENCES lotes(id),
    tipo TEXT NOT NULL,
    cantidad REAL NOT NULL,
    referencia TEXT,
    usuario_id INTEGER REFERENCES usuarios(id),
    fecha TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS recepciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    numero TEXT UNIQUE NOT NULL,
    material_id INTEGER NOT NULL REFERENCES materiales(id),
    cantidad REAL NOT NULL,
    proveedor_id INTEGER REFERENCES proveedores(id),
    remito TEXT,
    precio_unit REAL,
    lote_id INTEGER REFERENCES lotes(id),
    obs TEXT,
    creado_por INTEGER REFERENCES usuarios(id),
    fecha TEXT DEFAULT (datetime('now','localtime')),
    moneda TEXT
);

CREATE TABLE IF NOT EXISTS producto_clientes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    producto_id INTEGER NOT NULL REFERENCES materiales(id) ON DELETE CASCADE,
    cliente_id INTEGER NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
    UNIQUE(producto_id, cliente_id)
);

CREATE TABLE IF NOT EXISTS orden_operaciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    orden_id INTEGER NOT NULL REFERENCES ordenes(id) ON DELETE CASCADE,
    proceso_op_id INTEGER REFERENCES proceso_operaciones(id),
    orden INTEGER DEFAULT 1,
    nombre TEXT NOT NULL,
    categoria_maquina_id INTEGER REFERENCES categorias_maquina(id),
    maquina_id INTEGER REFERENCES maquinas(id),
    tiempo_setup_min INTEGER DEFAULT 0,
    tiempo_ciclo_seg REAL DEFAULT 0,
    estado TEXT DEFAULT 'Pendiente',
    qty_requerida REAL DEFAULT 0,
    qty_producida REAL DEFAULT 0,
    es_tercerizada INTEGER DEFAULT 0,
    proveedor_id INTEGER REFERENCES proveedores(id),
    precio_tercerizado REAL DEFAULT 0,
    tiempo_minimo_dias INTEGER DEFAULT 0
);

-- Scheduling de producción: cada renglón es un bloque de trabajo (una jornada
-- de 9 o 12 h) de una operación de OT en una máquina, con su operario.
CREATE TABLE IF NOT EXISTS planificacion (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    orden_operacion_id INTEGER NOT NULL REFERENCES orden_operaciones(id) ON DELETE CASCADE,
    maquina_id INTEGER NOT NULL REFERENCES maquinas(id),
    empleado_id INTEGER REFERENCES empleados(id) ON DELETE SET NULL,
    inicio TEXT NOT NULL,
    fin TEXT NOT NULL,
    jornada_horas INTEGER DEFAULT 9,
    cantidad_plan REAL DEFAULT 0,
    obs TEXT,
    creado TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_planif_maq ON planificacion(maquina_id, inicio);
CREATE INDEX IF NOT EXISTS idx_planif_emp ON planificacion(empleado_id, inicio);
CREATE INDEX IF NOT EXISTS idx_planif_op ON planificacion(orden_operacion_id);

CREATE TABLE IF NOT EXISTS orden_materiales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    orden_id INTEGER NOT NULL REFERENCES ordenes(id) ON DELETE CASCADE,
    material_id INTEGER NOT NULL REFERENCES materiales(id),
    cantidad_requerida REAL DEFAULT 0,
    cantidad_asignada REAL DEFAULT 0,
    unidad TEXT
);

CREATE TABLE IF NOT EXISTS empleados (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    legajo TEXT UNIQUE NOT NULL,
    nombre TEXT NOT NULL,
    apellido TEXT,
    cargo TEXT,
    tipo TEXT DEFAULT 'Indirecto',
    turno TEXT,
    activo INTEGER DEFAULT 1,
    obs TEXT,
    creado TEXT DEFAULT (datetime('now','localtime')),
    fecha_alta TEXT,
    fecha_baja TEXT
);

CREATE TABLE IF NOT EXISTS empleado_maquinas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    empleado_id INTEGER NOT NULL REFERENCES empleados(id) ON DELETE CASCADE,
    categoria_maquina_id INTEGER NOT NULL REFERENCES categorias_maquina(id) ON DELETE CASCADE,
    UNIQUE(empleado_id, categoria_maquina_id)
);

CREATE TABLE IF NOT EXISTS ordenes_cliente (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    numero TEXT UNIQUE NOT NULL,
    cliente_id INTEGER NOT NULL REFERENCES clientes(id),
    fecha TEXT DEFAULT (datetime('now','localtime')),
    fecha_entrega TEXT,
    estado TEXT DEFAULT 'Recibida',
    obs TEXT,
    creado TEXT DEFAULT (datetime('now','localtime')),
    moneda TEXT
);

CREATE TABLE IF NOT EXISTS ordenes_cliente_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    orden_cliente_id INTEGER NOT NULL REFERENCES ordenes_cliente(id) ON DELETE CASCADE,
    producto_id INTEGER NOT NULL REFERENCES materiales(id),
    cantidad REAL NOT NULL,
    precio_unit REAL DEFAULT 0,
    fecha_deseada TEXT,
    ot_id INTEGER REFERENCES ordenes(id),
    obs TEXT
);

CREATE TABLE IF NOT EXISTS orden_cliente_item_ots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL REFERENCES ordenes_cliente_items(id) ON DELETE CASCADE,
    ot_id INTEGER NOT NULL REFERENCES ordenes(id),
    creado TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(item_id, ot_id)
);

CREATE TABLE IF NOT EXISTS novedades_produccion (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    numero TEXT UNIQUE NOT NULL,
    orden_id INTEGER NOT NULL REFERENCES ordenes(id),
    orden_operacion_id INTEGER NOT NULL REFERENCES orden_operaciones(id),
    empleado_id INTEGER REFERENCES empleados(id),
    cantidad_producida REAL NOT NULL,
    tiempo_real_min REAL NOT NULL,
    turno TEXT,
    fecha TEXT DEFAULT (datetime('now','localtime')),
    rendimiento_pct REAL DEFAULT 0,
    desvio INTEGER DEFAULT 0,
    obs TEXT,
    creado_por INTEGER REFERENCES usuarios(id),
    maquina_id INTEGER REFERENCES maquinas(id),
    piezas_observadas REAL DEFAULT 0,
    tiempo_perdido REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS novedades_eliminadas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    novedad_numero TEXT NOT NULL,
    orden_id INTEGER,
    orden_numero TEXT,
    orden_operacion_id INTEGER,
    operacion_nombre TEXT,
    producto_id INTEGER,
    producto_nombre TEXT,
    empleado_id INTEGER,
    empleado_nombre TEXT,
    maquina_id INTEGER,
    maquina_nombre TEXT,
    cantidad_producida REAL,
    piezas_observadas REAL,
    tiempo_real_min REAL,
    tiempo_perdido REAL,
    turno TEXT,
    fecha_novedad TEXT,
    rendimiento_pct REAL,
    obs TEXT,
    novedad_creado_por INTEGER,
    novedad_creado_por_nombre TEXT,
    detalle_json TEXT,
    eliminado_por INTEGER REFERENCES usuarios(id),
    eliminado_por_nombre TEXT,
    eliminado TEXT DEFAULT (datetime('now','localtime')),
    restaurado TEXT,
    restaurado_por INTEGER REFERENCES usuarios(id),
    restaurado_por_nombre TEXT
);

CREATE TABLE IF NOT EXISTS trabajo_no_productivo (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    numero TEXT UNIQUE NOT NULL,
    empleado_id INTEGER REFERENCES empleados(id),
    descripcion TEXT NOT NULL,
    tiempo_min REAL NOT NULL,
    fecha TEXT DEFAULT (datetime('now','localtime')),
    creado_por INTEGER REFERENCES usuarios(id),
    creado TEXT DEFAULT (datetime('now','localtime'))
);

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
    creado TEXT DEFAULT (datetime('now','localtime')),
    ott_id INTEGER REFERENCES ordenes_tercerizado(id),
    ott_remito TEXT
);

CREATE TABLE IF NOT EXISTS cotizaciones_compra (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    solicitud_id INTEGER NOT NULL REFERENCES solicitudes_compra(id) ON DELETE CASCADE,
    proveedor_id INTEGER NOT NULL REFERENCES proveedores(id),
    precio_unit REAL NOT NULL,
    plazo_entrega_dias INTEGER DEFAULT 3,
    condicion_pago TEXT,
    seleccionada INTEGER DEFAULT 0,
    obs TEXT,
    creado TEXT DEFAULT (datetime('now','localtime')),
    moneda TEXT
);

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
    creado TEXT DEFAULT (datetime('now','localtime')),
    remito_devolucion_id INTEGER REFERENCES remitos(id),
    remito_numero TEXT,
    fecha_completada TEXT,
    motivo_anulacion TEXT,
    fecha_anulada TEXT,
    moneda TEXT
);

CREATE TABLE IF NOT EXISTS ordenes_compra_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    oc_id INTEGER NOT NULL REFERENCES ordenes_compra(id) ON DELETE CASCADE,
    solicitud_id INTEGER REFERENCES solicitudes_compra(id),
    material_id INTEGER REFERENCES materiales(id),
    descripcion TEXT NOT NULL,
    cantidad REAL NOT NULL,
    cantidad_recibida REAL DEFAULT 0,
    precio_unit REAL NOT NULL,
    unidad TEXT,
    lote_id INTEGER REFERENCES lotes(id),
    cantidad_rechazada_devuelta REAL DEFAULT 0,
    cantidad_rechazada_reingresada REAL DEFAULT 0,
    fecha_recibida TEXT
);

CREATE TABLE IF NOT EXISTS pronosticos_venta (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo TEXT UNIQUE NOT NULL,
    estado TEXT NOT NULL DEFAULT 'Alta',
    fecha_emision TEXT NOT NULL,
    periodos INTEGER NOT NULL DEFAULT 3,
    creado TEXT DEFAULT (datetime('now','localtime')),
    cliente_id INTEGER REFERENCES clientes(id)
);

CREATE TABLE IF NOT EXISTS pronostico_venta_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pronostico_id INTEGER NOT NULL REFERENCES pronosticos_venta(id) ON DELETE CASCADE,
    producto_id INTEGER NOT NULL REFERENCES materiales(id),
    mes TEXT NOT NULL,
    cantidad REAL NOT NULL DEFAULT 0,
    UNIQUE(pronostico_id, producto_id, mes)
);

CREATE TABLE IF NOT EXISTS pronostico_item_ots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL REFERENCES pronostico_venta_items(id) ON DELETE CASCADE,
    ot_id INTEGER NOT NULL REFERENCES ordenes(id),
    UNIQUE(item_id, ot_id)
);

CREATE TABLE IF NOT EXISTS requerimientos_productivos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    numero TEXT NOT NULL,
    cliente_id INTEGER REFERENCES clientes(id),
    codigo TEXT,
    material_proceso TEXT,
    provision TEXT,
    cantidad_pedida REAL NOT NULL DEFAULT 0,
    unidad TEXT,
    proveedor_id INTEGER REFERENCES proveedores(id),
    nro_oc_remito TEXT,
    f_pedido TEXT,
    f_necesidad TEXT,
    f_estimada TEXT,
    f_entrega TEXT,
    estado TEXT DEFAULT 'PROXIMO',
    cantidad_entregada REAL,
    remito TEXT,
    nro_factura TEXT,
    cumple_fecha INTEGER,
    cumple_cantidad INTEGER,
    cumple_calidad INTEGER,
    nro_icp TEXT,
    cant_no_conforme REAL,
    ubicacion_remito TEXT,
    obs TEXT,
    creado TEXT DEFAULT (datetime('now','localtime')),
    origen_item_id INTEGER,
    ot_origen_id INTEGER REFERENCES ordenes(id),
    cantidad_aprobada REAL
);

-- Bitacora de auditoria: una fila por alta / modificacion / baja de datos.
-- La escribe la capa de conexion (ver _AuditConnection), no los controladores.
CREATE TABLE IF NOT EXISTS auditoria (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT NOT NULL,
    origen TEXT NOT NULL,                -- 'usuario' | 'sistema'
    usuario_id INTEGER,                  -- NULL cuando origen='sistema'
    actor TEXT NOT NULL,                 -- nombre del usuario o del proceso
    entidad TEXT NOT NULL,               -- tabla afectada
    registro_id TEXT,                    -- clave primaria del registro afectado
    accion TEXT NOT NULL,                -- 'alta' | 'modificacion' | 'baja'
    ruta TEXT,                           -- endpoint que origino el cambio
    valores_antes TEXT,                  -- JSON (solo los campos que cambiaron)
    valores_despues TEXT                 -- JSON (solo los campos que cambiaron)
);
CREATE INDEX IF NOT EXISTS ix_auditoria_fecha ON auditoria(fecha);
CREATE INDEX IF NOT EXISTS ix_auditoria_entidad ON auditoria(entidad, registro_id);
CREATE INDEX IF NOT EXISTS ix_auditoria_actor ON auditoria(actor);

CREATE TABLE IF NOT EXISTS ordenes_tercerizado (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    numero TEXT UNIQUE NOT NULL,
    ot_origen_id INTEGER REFERENCES ordenes(id) ON DELETE SET NULL,
    operacion_id INTEGER REFERENCES orden_operaciones(id) ON DELETE SET NULL,
    proceso_op_id INTEGER REFERENCES proceso_operaciones(id),
    proveedor_id INTEGER REFERENCES proveedores(id),
    precio_acordado REAL DEFAULT 0,
    estado TEXT DEFAULT 'Pendiente' CHECK(estado IN ('Pendiente','Remito emitido','En proceso','Recibido','Completado','Cancelado')),
    es_ultimo_nivel INTEGER DEFAULT 0,
    remito_traslado_id INTEGER REFERENCES remitos(id),
    lote_retorno_id INTEGER REFERENCES lotes(id),
    fecha_envio TEXT,
    fecha_retorno_est TEXT,
    fecha_retorno_real TEXT,
    obs TEXT,
    creado TEXT DEFAULT (datetime('now','localtime')),
    creado_por INTEGER REFERENCES usuarios(id),
    cantidad_enviada REAL DEFAULT 0,
    cantidad_recibida REAL DEFAULT 0,
    cantidad_rechazada_devuelta REAL DEFAULT 0,
    remito_devolucion_id INTEGER REFERENCES remitos(id),
    material_se_id INTEGER REFERENCES materiales(id),
    cantidad_plan REAL DEFAULT 0,
    moneda TEXT
);

CREATE TABLE IF NOT EXISTS herramientas_operacion (
    id INTEGER PRIMARY KEY,
    operacion_id INTEGER NOT NULL REFERENCES proceso_operaciones(id) ON DELETE CASCADE,
    orden INTEGER DEFAULT 1,
    nombre TEXT NOT NULL,
    descripcion TEXT,
    duracion_min REAL DEFAULT 0,
    unidad TEXT DEFAULT 'unid',
    cantidad REAL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS usuario_permisos (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    clave TEXT NOT NULL,
    valor TEXT,
    UNIQUE(usuario_id, clave)
);

CREATE TABLE IF NOT EXISTS configuracion (
    clave TEXT PRIMARY KEY,
    valor TEXT,
    descripcion TEXT
);

CREATE TABLE IF NOT EXISTS roles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT UNIQUE NOT NULL,
    descripcion TEXT,
    base_rol TEXT NOT NULL,
    permisos TEXT DEFAULT '{}',
    es_sistema INTEGER DEFAULT 0,
    creado TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS orden_operacion_materiales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    orden_operacion_id INTEGER NOT NULL REFERENCES orden_operaciones(id) ON DELETE CASCADE,
    material_id INTEGER REFERENCES materiales(id),
    producto_id INTEGER REFERENCES materiales(id),
    cantidad REAL DEFAULT 0,
    unidad TEXT,
    tipo TEXT DEFAULT 'material',
    vida_util_herramienta INTEGER,
    herr_consumido REAL DEFAULT 0   -- herramientas ya descontadas del stock por esta operación
);
CREATE INDEX IF NOT EXISTS idx_ooom_oo ON orden_operacion_materiales(orden_operacion_id);

CREATE TABLE IF NOT EXISTS producto_versiones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    producto_id INTEGER NOT NULL REFERENCES materiales(id) ON DELETE CASCADE,
    version_num INTEGER NOT NULL DEFAULT 1,
    motivo TEXT,
    snapshot TEXT NOT NULL,
    creado_por TEXT,
    creado TEXT DEFAULT (datetime('now','localtime'))
);

-- Asistente IA (solo admin): conversaciones, mensajes y registro de consultas.
-- ia_conversaciones e ia_mensajes no se auditan (AUDITORIA_TABLAS_EXCLUIDAS);
-- cada fila de ia_consultas sí queda en la Bitácora.
CREATE TABLE IF NOT EXISTS ia_conversaciones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    titulo TEXT,
    creado TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS ix_ia_conversaciones_usuario ON ia_conversaciones(usuario_id);

CREATE TABLE IF NOT EXISTS ia_mensajes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversacion_id INTEGER NOT NULL REFERENCES ia_conversaciones(id) ON DELETE CASCADE,
    rol TEXT NOT NULL CHECK(rol IN ('user','assistant')),
    contenido TEXT NOT NULL,
    herramientas TEXT,
    creado TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS ix_ia_mensajes_conversacion ON ia_mensajes(conversacion_id);

CREATE TABLE IF NOT EXISTS ia_consultas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT DEFAULT (datetime('now','localtime')),
    usuario_id INTEGER REFERENCES usuarios(id),
    conversacion_id INTEGER,
    pregunta TEXT NOT NULL,
    herramientas TEXT,
    modelo TEXT,
    tokens_entrada INTEGER DEFAULT 0,
    tokens_salida INTEGER DEFAULT 0,
    usd_estimado REAL DEFAULT 0,
    duracion_ms INTEGER,
    error TEXT
);
CREATE INDEX IF NOT EXISTS ix_ia_consultas_fecha ON ia_consultas(fecha);

-- Cada documento nuevo nace en la moneda del sistema.
CREATE TRIGGER IF NOT EXISTS trg_moneda_ordenes AFTER INSERT ON ordenes
WHEN NEW.moneda IS NULL BEGIN
    UPDATE ordenes SET moneda=COALESCE((SELECT valor FROM configuracion WHERE clave='moneda'),'ARS') WHERE id=NEW.id;
END;
CREATE TRIGGER IF NOT EXISTS trg_moneda_pedidos_cotizacion AFTER INSERT ON pedidos_cotizacion
WHEN NEW.moneda IS NULL BEGIN
    UPDATE pedidos_cotizacion SET moneda=COALESCE((SELECT valor FROM configuracion WHERE clave='moneda'),'ARS') WHERE id=NEW.id;
END;
CREATE TRIGGER IF NOT EXISTS trg_moneda_presupuestos AFTER INSERT ON presupuestos
WHEN NEW.moneda IS NULL BEGIN
    UPDATE presupuestos SET moneda=COALESCE((SELECT valor FROM configuracion WHERE clave='moneda'),'ARS') WHERE id=NEW.id;
END;
CREATE TRIGGER IF NOT EXISTS trg_moneda_ordenes_cliente AFTER INSERT ON ordenes_cliente
WHEN NEW.moneda IS NULL BEGIN
    UPDATE ordenes_cliente SET moneda=COALESCE((SELECT valor FROM configuracion WHERE clave='moneda'),'ARS') WHERE id=NEW.id;
END;
CREATE TRIGGER IF NOT EXISTS trg_moneda_ordenes_compra AFTER INSERT ON ordenes_compra
WHEN NEW.moneda IS NULL BEGIN
    UPDATE ordenes_compra SET moneda=COALESCE((SELECT valor FROM configuracion WHERE clave='moneda'),'ARS') WHERE id=NEW.id;
END;
CREATE TRIGGER IF NOT EXISTS trg_moneda_ordenes_tercerizado AFTER INSERT ON ordenes_tercerizado
WHEN NEW.moneda IS NULL BEGIN
    UPDATE ordenes_tercerizado SET moneda=COALESCE((SELECT valor FROM configuracion WHERE clave='moneda'),'ARS') WHERE id=NEW.id;
END;
CREATE TRIGGER IF NOT EXISTS trg_moneda_cotizaciones_compra AFTER INSERT ON cotizaciones_compra
WHEN NEW.moneda IS NULL BEGIN
    UPDATE cotizaciones_compra SET moneda=COALESCE((SELECT valor FROM configuracion WHERE clave='moneda'),'ARS') WHERE id=NEW.id;
END;
CREATE TRIGGER IF NOT EXISTS trg_moneda_recepciones AFTER INSERT ON recepciones
WHEN NEW.moneda IS NULL BEGIN
    UPDATE recepciones SET moneda=COALESCE((SELECT valor FROM configuracion WHERE clave='moneda'),'ARS') WHERE id=NEW.id;
END;
CREATE TRIGGER IF NOT EXISTS trg_moneda_tickets_reparacion AFTER INSERT ON tickets_reparacion
WHEN NEW.moneda IS NULL BEGIN
    UPDATE tickets_reparacion SET moneda=COALESCE((SELECT valor FROM configuracion WHERE clave='moneda'),'ARS') WHERE id=NEW.id;
END;
-- HMI de máquina (MÓDULO DE PRUEBA): una sesión = un operario trabajando una
-- operación de OT en una máquina; los ciclos llegan como eventos con un uid
-- único por sesión, así un reenvío no suma dos veces.
CREATE TABLE IF NOT EXISTS hmi_sesiones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    maquina_id INTEGER REFERENCES maquinas(id),
    empleado_id INTEGER NOT NULL REFERENCES empleados(id),
    orden_id INTEGER NOT NULL REFERENCES ordenes(id),
    orden_operacion_id INTEGER NOT NULL REFERENCES orden_operaciones(id),
    estado TEXT NOT NULL DEFAULT 'Produciendo' CHECK(estado IN ('Produciendo','Pausada','Finalizada')),
    inicio TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    fin TEXT,
    trabajado_seg REAL NOT NULL DEFAULT 0,
    desde TEXT,
    ciclos INTEGER NOT NULL DEFAULT 0,
    duplicados INTEGER NOT NULL DEFAULT 0,
    nok INTEGER NOT NULL DEFAULT 0,
    novedad_id INTEGER REFERENCES novedades_produccion(id),
    creado_por INTEGER REFERENCES usuarios(id)
);
CREATE INDEX IF NOT EXISTS ix_hmi_sesiones_maquina ON hmi_sesiones(maquina_id, estado);
CREATE TABLE IF NOT EXISTS hmi_eventos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sesion_id INTEGER NOT NULL REFERENCES hmi_sesiones(id) ON DELETE CASCADE,
    uid TEXT NOT NULL,
    seq INTEGER,
    ts_origen TEXT,
    recibido TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(sesion_id, uid)
);
-- Registro de cambios del sistema: una fila por cambio de código hecho en
-- MetalERP (qué, cuándo, por qué y para qué). Solo fecha y descripción son
-- obligatorias; lo carga a mano un administrador desde Sistema.
CREATE TABLE IF NOT EXISTS registro_cambios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha TEXT NOT NULL,                 -- día del cambio (YYYY-MM-DD)
    descripcion TEXT NOT NULL,           -- resumen en una línea
    tipo TEXT,                           -- Nuevo / Mejora / Corrección / ...
    modulo TEXT,                         -- parte del sistema afectada
    detalle TEXT,                        -- qué se hizo
    motivo TEXT,                         -- por qué se hizo
    objetivo TEXT,                       -- para qué sirve
    archivos TEXT,                       -- archivos tocados, backups
    autor TEXT,                          -- quién lo hizo
    referencia TEXT,                     -- PR, versión, hilo, etc.
    creado_por INTEGER REFERENCES usuarios(id),
    creado_en TEXT DEFAULT (datetime('now','localtime')),
    actualizado_en TEXT
);
CREATE INDEX IF NOT EXISTS ix_registro_cambios_fecha ON registro_cambios(fecha);
-- Tablets de planta: una por máquina, entra sin usuario con su token.
CREATE TABLE IF NOT EXISTS planta_tablets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    maquina_id INTEGER NOT NULL REFERENCES maquinas(id),
    token TEXT UNIQUE NOT NULL,
    activa INTEGER NOT NULL DEFAULT 1,
    lector_sn TEXT,                      -- n° de serie del lector de huella de la máquina
    creado_por INTEGER REFERENCES usuarios(id),
    creado_en TEXT DEFAULT (datetime('now','localtime'))
);
-- Bandeja de entrada de las tablets: el endpoint solo inserta (uuid generado
-- en la tablet, único: un reenvío no duplica) y un procesador único lo pasa
-- a novedad de a un registro.
CREATE TABLE IF NOT EXISTS planta_bandeja (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT UNIQUE NOT NULL,
    tablet_id INTEGER NOT NULL REFERENCES planta_tablets(id),
    tipo TEXT NOT NULL DEFAULT 'produccion',
    datos TEXT NOT NULL,                 -- JSON tal cual lo cargó el operario
    hora_operario TEXT,                  -- hora real de carga en la tablet
    recibido TEXT DEFAULT (datetime('now','localtime')),
    estado TEXT NOT NULL DEFAULT 'Pendiente'
        CHECK(estado IN ('Pendiente','Procesando','Procesado','Error','Descartado')),
    intentos INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    procesado TEXT,
    novedad_id INTEGER REFERENCES novedades_produccion(id),
    resuelto_por INTEGER REFERENCES usuarios(id),
    espera TEXT,                         -- 'lote': la OT todavía no tiene lote; se carga sola al asignarlo
    espera_ref TEXT,                     -- cómo estaban los lotes de la OT cuando falló
    reintentar_desde TEXT                -- próximo reintento automático
);
CREATE INDEX IF NOT EXISTS ix_planta_bandeja_estado ON planta_bandeja(estado, id);
CREATE INDEX IF NOT EXISTS ix_planta_bandeja_tablet ON planta_bandeja(tablet_id, id);
-- Marcas de huella de los lectores de las máquinas: la tablet de esa máquina
-- entra con el operario (el lector manda el legajo, no la huella).
CREATE TABLE IF NOT EXISTS planta_huellas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tablet_id INTEGER NOT NULL REFERENCES planta_tablets(id),
    lector_sn TEXT,
    legajo TEXT,
    empleado_id INTEGER REFERENCES empleados(id),   -- NULL: legajo que no está en MetalERP
    hora TEXT,                                       -- hora de la marca según el lector
    recibido TEXT DEFAULT (datetime('now','localtime')),
    origen TEXT                                      -- zkteco / api / simulada
);
CREATE INDEX IF NOT EXISTS ix_planta_huellas_tablet ON planta_huellas(tablet_id, id);
"""

def _backfill_remitos_ott_cantidad(db):
    """Completa remitos.ott_cantidad en remitos de OTT emitidos antes de que
    existiera la columna. Fuentes, en orden: la SC generada por ese envío,
    los movimientos de salida que citan el remito, el "envío parcial: X" de
    la observación, y por último (si en la OTT queda un solo remito sin
    cantidad) lo enviado/devuelto de la OTT menos lo ya identificado."""
    import re
    pend = db.execute("""SELECT r.id, r.numero, r.tipo, r.obs, r.ott_id, ott.numero ott_numero
        FROM remitos r JOIN ordenes_tercerizado ott ON ott.id=r.ott_id
        WHERE r.tipo IN ('traslado_ott','devolucion_ott') AND r.ott_cantidad IS NULL""").fetchall()
    cols_rem = {c[1] for c in db.execute("PRAGMA table_info(remitos)")}
    for r in pend:
        cant = None
        if "cantidad_ott" in cols_rem:
            # Columna de una versión anterior, sin uso hoy pero con datos.
            v = db.execute("SELECT cantidad_ott FROM remitos WHERE id=?", (r["id"],)).fetchone()[0]
            if v: cant = v
        if cant is None and r["tipo"] == "traslado_ott":
            # La auditoría guarda cantidad_enviada antes/después de cada envío.
            try:
                import json as _json
                for a in db.execute("""SELECT valores_antes, valores_despues FROM auditoria
                        WHERE entidad='ordenes_tercerizado' AND registro_id=?
                        AND ruta LIKE '%/emitir_remito'""", (str(r["ott_id"]),)):
                    antes = _json.loads(a["valores_antes"] or "{}")
                    desp = _json.loads(a["valores_despues"] or "{}")
                    if desp.get("remito_traslado_id") == r["id"]:
                        delta = float(desp.get("cantidad_enviada") or 0) - float(antes.get("cantidad_enviada") or 0)
                        if delta > 0: cant = delta
                        break
            except Exception:
                pass
        if cant is None and r["tipo"] == "traslado_ott":
            sc = db.execute("""SELECT SUM(cantidad) FROM solicitudes_compra
                WHERE ott_id=? AND ott_remito=?""", (r["ott_id"], r["numero"])).fetchone()[0]
            if sc: cant = sc
            if cant is None:
                mov = db.execute("""SELECT SUM(cantidad) FROM movimientos WHERE tipo='salida'
                    AND (referencia=? OR referencia LIKE ?)""",
                    (f"Envío a tercerizado OTT {r['ott_numero']} — {r['numero']}",
                     f"Reenvío a tercerizado OTT {r['ott_numero']} — {r['numero']} (%")).fetchone()[0]
                if mov: cant = mov
            if cant is None:
                m = re.search(r"envío parcial:\s*([\d.]+)", r["obs"] or "")
                if m: cant = float(m.group(1))
        if cant is not None:
            db.execute("UPDATE remitos SET ott_cantidad=? WHERE id=?", (cant, r["id"]))
    # Un único remito sin cantidad en la OTT: se deduce del total de la OTT.
    for tipo, col in (("traslado_ott", "cantidad_enviada"), ("devolucion_ott", "cantidad_rechazada_devuelta")):
        for o in db.execute(f"""SELECT r.ott_id, ott.{col} total,
                SUM(r.ott_cantidad IS NULL) sin_cant, COALESCE(SUM(r.ott_cantidad),0) conocida
            FROM remitos r JOIN ordenes_tercerizado ott ON ott.id=r.ott_id
            WHERE r.tipo=? GROUP BY r.ott_id""", (tipo,)).fetchall():
            resto = float(o["total"] or 0) - float(o["conocida"] or 0)
            if o["sin_cant"] == 1 and resto > 0.0001:
                db.execute("""UPDATE remitos SET ott_cantidad=?
                    WHERE ott_id=? AND tipo=? AND ott_cantidad IS NULL""", (resto, o["ott_id"], tipo))
    db.commit()

# ── Versión del esquema ───────────────────────────────────────────────────────
# SCHEMA (arriba) describe la base completa tal como la usa este código: una
# instalación nueva se crea directamente así, sin migraciones. La versión de
# cada base queda guardada en PRAGMA user_version.
#
# Para cambiar el esquema más adelante:
#   1. Agregar la tabla o columna en SCHEMA (para las instalaciones nuevas).
#   2. Agregar en MIGRACIONES una función con el número siguiente que haga el
#      mismo cambio sobre una base existente (por ejemplo un ALTER TABLE).
#   3. Subir ESQUEMA_VERSION a ese número.
# Cada migración corre una sola vez por base.
ESQUEMA_VERSION = 16


def _agregar_columna(db, tabla, columna, tipo):
    """ALTER TABLE ADD COLUMN solo si la columna no existe (idempotente)."""
    if columna not in {r[1] for r in db.execute(f"PRAGMA table_info({tabla})")}:
        db.execute(f"ALTER TABLE {tabla} ADD COLUMN {columna} {tipo}")


def _crear_tabla_de_schema(db, tabla):
    """Crea `tabla` (con sus índices) tal como está escrita en SCHEMA, solo si
    todavía no existe (idempotente). Evita repetir el CREATE TABLE."""
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (tabla,)).fetchone():
        return
    ref = sqlite3.connect(":memory:")
    ref.executescript(SCHEMA)
    for (sql,) in ref.execute("""SELECT sql FROM sqlite_master
            WHERE tbl_name=? AND sql IS NOT NULL ORDER BY type='index'""", (tabla,)).fetchall():
        db.execute(sql)
    ref.close()


def _migracion_2(db):
    # Vida útil de herramienta (piezas que hace cada una), en la plantilla
    # del proceso y en la copia propia de cada OT.
    _agregar_columna(db, "operacion_materiales", "vida_util_herramienta", "INTEGER")
    _agregar_columna(db, "orden_operacion_materiales", "vida_util_herramienta", "INTEGER")


def _migracion_4(db):
    # Cajones y su trazabilidad por paso, calidad y remito.
    for tabla in ("cajones", "novedad_cajones", "ott_cajones", "remito_item_cajones"):
        _crear_tabla_de_schema(db, tabla)


def _migracion_5(db):
    # Bultos de una recepción de compra como cajones del lote: cajones.orden_id
    # pasa a admitir NULL. SQLite no cambia un NOT NULL con ALTER, así que se
    # rehace la tabla (procedimiento oficial: tabla nueva, copiar, borrar,
    # renombrar) con las claves foráneas apagadas para no tocar las tablas que
    # apuntan a cajones.
    cols = db.execute("PRAGMA table_info(cajones)").fetchall()
    if not cols or not any(c[1] == "orden_id" and c[3] for c in cols):
        return
    ref = sqlite3.connect(":memory:")
    ref.executescript(SCHEMA)
    sql = ref.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='cajones'").fetchone()[0]
    ref.close()
    sql_nueva = re.sub(r'^CREATE TABLE (IF NOT EXISTS )?"?cajones"?', "CREATE TABLE cajones_nueva", sql, count=1)
    nombres = ",".join(c[1] for c in cols)
    db.commit()
    db.execute("PRAGMA foreign_keys = OFF")
    try:
        db.execute("BEGIN")
        db.execute(sql_nueva)
        db.execute(f"INSERT INTO cajones_nueva ({nombres}) SELECT {nombres} FROM cajones")
        db.execute("DROP TABLE cajones")
        db.execute("ALTER TABLE cajones_nueva RENAME TO cajones")
        db.execute("CREATE INDEX IF NOT EXISTS idx_cajones_orden ON cajones(orden_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_cajones_lote ON cajones(lote_id)")
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.execute("PRAGMA foreign_keys = ON")


def _migracion_6(db):
    # Mantenimiento preventivo por horas de máquina: horas en la última
    # realización del plan e historial de realizaciones.
    _agregar_columna(db, "mantenimiento_plan", "ultima_horas", "REAL")
    _crear_tabla_de_schema(db, "mantenimiento_registros")


DOCUMENTOS_CON_MONEDA = ('ordenes', 'pedidos_cotizacion', 'presupuestos', 'ordenes_cliente', 'ordenes_compra', 'ordenes_tercerizado', 'cotizaciones_compra', 'recepciones', 'tickets_reparacion')


def _migracion_7(db):
    # Moneda pesos/dólares: cotizaciones del dólar, historial de cambios y la
    # moneda de cada documento (lo que ya existía se hizo en pesos).
    _crear_tabla_de_schema(db, "cotizaciones_dolar")
    _crear_tabla_de_schema(db, "moneda_cambios")
    for tabla in DOCUMENTOS_CON_MONEDA:
        _agregar_columna(db, tabla, "moneda", "TEXT")
        db.execute(f"UPDATE {tabla} SET moneda='ARS' WHERE moneda IS NULL")
    db.execute("UPDATE configuracion SET descripcion='Valor de mano de obra por hora' WHERE clave='valor_hora_mo'")


def _migracion_8(db):
    # Asistente IA: conversaciones, mensajes y registro de consultas.
    for tabla in ("ia_conversaciones", "ia_mensajes", "ia_consultas"):
        _crear_tabla_de_schema(db, tabla)


def _migracion_9(db):
    # Pedidos de cotización: se aprueban o rechazan (los que ya había quedan
    # Pendiente).
    _agregar_columna(db, "pedidos_cotizacion", "estado",
                     "TEXT NOT NULL DEFAULT 'Pendiente' CHECK(estado IN ('Pendiente','Aprobado','Rechazado'))")
    _agregar_columna(db, "pedidos_cotizacion", "estado_motivo", "TEXT")
    _agregar_columna(db, "pedidos_cotizacion", "estado_por", "INTEGER REFERENCES usuarios(id)")
    _agregar_columna(db, "pedidos_cotizacion", "estado_fecha", "TEXT")


def _migracion_10(db):
    # Pedidos de cotización como negociación cliente <-> taller: estados
    # Pendiente/Cotizada/Aprobada/Rechazada, descripción, ronda e historial.
    # El CHECK de estado no se cambia con ALTER: se rehace la tabla (tabla
    # nueva, copiar, borrar, renombrar) como en la migración 5.
    cols = [c[1] for c in db.execute("PRAGMA table_info(pedidos_cotizacion)").fetchall()]
    if not cols:
        _crear_tabla_de_schema(db, "pedidos_cotizacion")
        _crear_tabla_de_schema(db, "pedidos_cotizacion_historial")
        return
    ref = sqlite3.connect(":memory:")
    ref.executescript(SCHEMA)
    sql = ref.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='pedidos_cotizacion'").fetchone()[0]
    nuevas = [c[1] for c in ref.execute("PRAGMA table_info(pedidos_cotizacion)").fetchall()]
    ref.close()
    sql_nueva = re.sub(r'^CREATE TABLE (IF NOT EXISTS )?"?pedidos_cotizacion"?', "CREATE TABLE pedidos_cotizacion_nueva", sql, count=1)
    comunes = [c for c in cols if c in nuevas]
    origen = ["""CASE estado WHEN 'Aprobado' THEN 'Aprobada' WHEN 'Rechazado' THEN 'Rechazada'
                 WHEN 'Aprobada' THEN 'Aprobada' WHEN 'Rechazada' THEN 'Rechazada'
                 WHEN 'Cotizada' THEN 'Cotizada' ELSE 'Pendiente' END""" if c == "estado"
              else "COALESCE(ronda, 1)" if c == "ronda" else c for c in comunes]
    db.commit()
    db.execute("PRAGMA foreign_keys = OFF")
    try:
        db.execute("BEGIN")
        db.execute(sql_nueva)
        db.execute(f"INSERT INTO pedidos_cotizacion_nueva ({','.join(comunes)}) "
                   f"SELECT {','.join(origen)} FROM pedidos_cotizacion")
        db.execute("DROP TABLE pedidos_cotizacion")
        db.execute("ALTER TABLE pedidos_cotizacion_nueva RENAME TO pedidos_cotizacion")
        db.execute("""CREATE TRIGGER IF NOT EXISTS trg_moneda_pedidos_cotizacion AFTER INSERT ON pedidos_cotizacion
            WHEN NEW.moneda IS NULL BEGIN
                UPDATE pedidos_cotizacion SET moneda=COALESCE((SELECT valor FROM configuracion WHERE clave='moneda'),'ARS') WHERE id=NEW.id;
            END""")
        db.execute("""CREATE TABLE IF NOT EXISTS pedidos_cotizacion_historial (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pedido_id INTEGER NOT NULL REFERENCES pedidos_cotizacion(id) ON DELETE CASCADE,
            ronda INTEGER NOT NULL,
            evento TEXT NOT NULL CHECK(evento IN ('Solicitud','Cotización','Contraoferta','Aprobación','Rechazo','Reapertura')),
            cantidad REAL,
            precio_total REAL,
            nota TEXT,
            usuario_id INTEGER REFERENCES usuarios(id),
            fecha TEXT DEFAULT (datetime('now','localtime'))
        )""")
        db.execute("CREATE INDEX IF NOT EXISTS ix_pcot_historial_pedido ON pedidos_cotizacion_historial(pedido_id)")
        # Historial de lo que ya existía: la solicitud y, si ya estaba
        # decidido, la aprobación o el rechazo.
        db.execute("""INSERT INTO pedidos_cotizacion_historial
                (pedido_id, ronda, evento, cantidad, precio_total, nota, usuario_id, fecha)
            SELECT id, ronda, 'Solicitud', cantidad, precio_total, NULL, creado_por,
                   COALESCE(creado, fecha)
            FROM pedidos_cotizacion pc
            WHERE NOT EXISTS (SELECT 1 FROM pedidos_cotizacion_historial h WHERE h.pedido_id=pc.id)""")
        db.execute("""INSERT INTO pedidos_cotizacion_historial
                (pedido_id, ronda, evento, cantidad, precio_total, nota, usuario_id, fecha)
            SELECT id, ronda, CASE estado WHEN 'Aprobada' THEN 'Aprobación' ELSE 'Rechazo' END,
                   cantidad, precio_total, estado_motivo, estado_por, COALESCE(estado_fecha, creado, fecha)
            FROM pedidos_cotizacion pc
            WHERE estado IN ('Aprobada','Rechazada')
              AND NOT EXISTS (SELECT 1 FROM pedidos_cotizacion_historial h
                              WHERE h.pedido_id=pc.id AND h.evento IN ('Aprobación','Rechazo'))""")
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.execute("PRAGMA foreign_keys = ON")


def _migracion_11(db):
    # Herramientas: se descuentan a medida que se declara la operación que las
    # usa (herr_consumido lleva lo ya descontado). Las OT que ya descontaron
    # sus herramientas al completarse (stock_descontado=1) quedan con eso
    # registrado, para no volver a descontarlas ni devolverlas.
    _agregar_columna(db, "orden_operacion_materiales", "herr_consumido", "REAL DEFAULT 0")
    db.create_function("cant_material", 3, cant_material, deterministic=True)
    db.execute("""UPDATE orden_operacion_materiales SET herr_consumido=(
            SELECT cant_material(orden_operacion_materiales.cantidad, oo.qty_producida,
                                 orden_operacion_materiales.vida_util_herramienta)
            FROM orden_operaciones oo WHERE oo.id=orden_operacion_materiales.orden_operacion_id)
        WHERE material_id IN (SELECT id FROM materiales WHERE categoria='Herramienta')
          AND orden_operacion_id IN (SELECT oo.id FROM orden_operaciones oo
              JOIN ordenes o ON o.id=oo.orden_id WHERE COALESCE(o.stock_descontado,0)=1)""")


def _migracion_15(db):
    """Tablets de planta con huella: lector asignado a la tablet + marcas."""
    cols = {r[1] for r in db.execute("PRAGMA table_info(planta_tablets)")}
    if "lector_sn" not in cols:
        db.execute("ALTER TABLE planta_tablets ADD COLUMN lector_sn TEXT")
    _crear_tabla_de_schema(db, "planta_huellas")


def _migracion_16(db):
    """Bandeja de tablets: reintentos espaciados y espera de lote."""
    cols = {r[1] for r in db.execute("PRAGMA table_info(planta_bandeja)")}
    for col in ("espera", "espera_ref", "reintentar_desde"):
        if col not in cols:
            db.execute(f"ALTER TABLE planta_bandeja ADD COLUMN {col} TEXT")


MIGRACIONES = {
    2: _migracion_2,
    3: lambda db: _crear_tabla_de_schema(db, "pedidos_cotizacion"),
    4: _migracion_4,
    5: _migracion_5,
    6: _migracion_6,
    7: _migracion_7,
    8: _migracion_8,
    9: _migracion_9,
    10: _migracion_10,
    11: _migracion_11,
    12: lambda db: (_crear_tabla_de_schema(db, "hmi_sesiones"),
                    _crear_tabla_de_schema(db, "hmi_eventos")),
    13: lambda db: _crear_tabla_de_schema(db, "registro_cambios"),
    14: lambda db: (_crear_tabla_de_schema(db, "planta_tablets"),
                    _crear_tabla_de_schema(db, "planta_bandeja")),
    15: _migracion_15,
    16: _migracion_16,
}


def _completar_columnas(db):
    """Agrega las columnas que el SCHEMA tiene y la base no (ALTER TABLE ADD
    COLUMN), para las tablas que ya existen. Red de seguridad para columnas
    que se sumaron al SCHEMA sin su migración. SQLite no deja agregar con
    ALTER un NOT NULL sin valor por defecto ni un defecto calculado: en esos
    casos la columna se agrega sin esa restricción."""
    ref = sqlite3.connect(":memory:")
    ref.executescript(SCHEMA)
    tablas = [r[0] for r in ref.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    for tabla in tablas:
        fila = db.execute("SELECT type FROM sqlite_master WHERE name=?", (tabla,)).fetchone()
        if not fila or fila[0] != "table":
            continue
        cols = {r[1] for r in db.execute(f"PRAGMA table_info({tabla})")}
        for _cid, nombre, tipo, notnull, defecto, _pk in ref.execute(f"PRAGMA table_info({tabla})").fetchall():
            if nombre in cols:
                continue
            definicion = tipo or ""
            calculado = defecto is not None and (defecto.startswith("(") or "CURRENT_" in defecto.upper())
            if defecto is not None and not calculado:
                definicion += f" DEFAULT {defecto}"
                if notnull:
                    definicion += " NOT NULL"
            db.execute(f"ALTER TABLE {tabla} ADD COLUMN {nombre} {definicion}")
    ref.close()


def _faltantes_de_schema(db):
    """Tablas, vistas y columnas del SCHEMA actual que no están en la base."""
    ref = sqlite3.connect(":memory:")
    ref.executescript(SCHEMA)
    faltan = []
    for nombre, tipo in ref.execute("""SELECT name, type FROM sqlite_master
            WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%'""").fetchall():
        fila = db.execute("SELECT type FROM sqlite_master WHERE name=?", (nombre,)).fetchone()
        if not fila or fila[0] != tipo:
            faltan.append(f"{tipo} {nombre}")
        elif tipo == "table":
            cols = {r[1] for r in db.execute(f"PRAGMA table_info({nombre})")}
            faltan += [f"{nombre}.{r[1]}" for r in ref.execute(f"PRAGMA table_info({nombre})")
                       if r[1] not in cols]
    ref.close()
    return faltan


def _actualizar_esquema(db, desde):
    """Corre las migraciones posteriores a `desde`, agrega las columnas que
    falten y crea lo que falte del SCHEMA."""
    for v in range(desde + 1, ESQUEMA_VERSION + 1):
        MIGRACIONES[v](db)
        db.execute(f"PRAGMA user_version = {v}")
        db.commit()
    _completar_columnas(db)
    db.commit()
    # Crea lo que falte (todo es IF NOT EXISTS: no toca lo que ya existe).
    db.executescript(SCHEMA)
    db.execute(f"PRAGMA user_version = {max(desde, ESQUEMA_VERSION)}")
    db.commit()


def _verificar_base_sin_version(db):
    """Base con datos pero sin versión (user_version=0): viene de antes de que
    existiera el versionado (por ejemplo, la base que estaba en GitHub). Se la
    actualiza primero sobre una copia en memoria: si así queda completa, se
    guarda un respaldo del archivo y init_db la actualiza de verdad, como
    versión 1. Si ni así queda completa, se corta el arranque sin tocarla."""
    copia = sqlite3.connect(":memory:")
    db.backup(copia)
    try:
        _actualizar_esquema(copia, 1)
        faltan = _faltantes_de_schema(copia)
    except Exception as e:
        faltan = [f"(error al actualizarla: {e})"]
    copia.close()
    if faltan:
        db.close()
        raise SystemExit(
            "La base de datos es de una versión anterior de MetalERP y no se "
            "pudo actualizar sola. Le falta: "
            + ", ".join(faltan[:10]) + (" ..." if len(faltan) > 10 else "") + ".\n"
            "La base no se tocó.")
    respaldo = os.path.join(os.path.dirname(DB_PATH),
        "metalerp_backup_pre_actualizacion_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".db")
    destino = sqlite3.connect(respaldo)
    db.backup(destino)
    destino.close()
    print(f"[base] Base de una versión anterior: se actualiza. Respaldo en {respaldo}")


# ── Arranque de la base ───────────────────────────────────────────────────────
def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row

    nueva = not db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='usuarios'").fetchone()
    if nueva:
        db.executescript(SCHEMA)
        db.execute(f"PRAGMA user_version = {ESQUEMA_VERSION}")
    else:
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            _verificar_base_sin_version(db)
            version = 1
        _actualizar_esquema(db, version)

    # ── Datos iniciales ──────────────────────────────────────────────────────
    if db.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] == 0:
        db.execute("INSERT INTO usuarios (username,password,nombre,rol) VALUES (?,?,?,?)",
            ("admin", hash_pw("admin123"), "Administrador", "admin"))

    # Configuración por defecto (INSERT OR IGNORE: no pisa lo ya cargado).
    _cfg_defaults = [
        ('empresa_nombre',      'Mecanizado Ituzaingo',    'Nombre del taller / empresa'),
        ('empresa_subtitulo',   'Taller de Mecanizados', 'Subtítulo o rubro'),
        ('empresa_direccion',   '',                   'Dirección'),
        ('empresa_telefono',    '',                   'Teléfono / WhatsApp'),
        ('empresa_email',       '',                   'Email'),
        ('pdf_color_hex',       '2C5F8A',             'Color principal PDF (hex sin #)'),
        ('pdf_mostrar_costos',  '0',                  'Mostrar costos en PDF (0/1)'),
        ('pdf_mostrar_precios', '0',                  'Mostrar precio de venta en PDF (0/1)'),
        ('pdf_nota_pie',        '',                   'Nota al pie del PDF de OT'),
        ('valor_hora_mo',       '0',                  'Valor de mano de obra por hora'),
        ('sc_automaticas',      '0',                  'Generar Solicitudes de Compra automáticamente (0/1)'),
        ('moneda',              'ARS',                'Moneda del sistema (ARS / USD)'),
        ('dolar_casa',          'oficial',            'Tipo de dólar para la cotización'),
    ]
    for _k, _v, _d in _cfg_defaults:
        db.execute("INSERT OR IGNORE INTO configuracion (clave,valor,descripcion) VALUES (?,?,?)",
                   (_k, _v, _d))

    # Roles del sistema (los demás se administran desde Configuración).
    for _rn, _desc in (("admin","Administrador — acceso total"),
                       ("operario","Producción — órdenes de trabajo, procesos, novedades"),
                       ("vendedor","Comercial — clientes, presupuestos, pedidos, compras"),
                       ("almacen","Almacén — inventario, lotes, recepción"),
                       ("logistica","Logística — remitos y stock, sin valores monetarios")):
        db.execute("INSERT OR IGNORE INTO roles (nombre,descripcion,base_rol,permisos,es_sistema) VALUES (?,?,?,?,1)",
                   (_rn, _desc, _rn, _json.dumps(DEFAULT_PERMISIONES.get(_rn, {}))))

    _reparar_datos_al_arrancar(db)
    db.close()


def _reparar_datos_al_arrancar(db):
    """Correcciones de datos que corren en cada arranque. No cambian el
    esquema: completan o corrigen filas que quedaron mal por errores ya
    arreglados. Todas son idempotentes (si no hay nada que corregir, no
    hacen nada)."""

    # Vínculos OC-item -> OT: volcar los que estén en la columna vieja
    # ot_id (de a uno por ítem) a la tabla orden_cliente_item_ots, que ahora
    # permite vincular varias OTs por ítem (repartiendo la cantidad pedida
    # entre varias OTs del mismo material/producto).
    for row in db.execute("""SELECT id,ot_id FROM ordenes_cliente_items
            WHERE ot_id IS NOT NULL AND ot_id NOT IN
            (SELECT ot_id FROM orden_cliente_item_ots WHERE item_id=ordenes_cliente_items.id)""").fetchall():
        try:
            db.execute("INSERT OR IGNORE INTO orden_cliente_item_ots (item_id,ot_id) VALUES (?,?)",
                       (row["id"], row["ot_id"]))
        except Exception:
            pass

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
                AND o.id NOT IN (SELECT ot_id FROM orden_cliente_item_ots)
            """, (h["producto_id"], h["cliente_id"])).fetchall()
            if len(candidatas) == 1:
                db.execute("UPDATE ordenes_cliente_items SET ot_id=? WHERE id=?",
                           (candidatas[0]["id"], h["item_id"]))
                db.execute("INSERT OR IGNORE INTO orden_cliente_item_ots (item_id,ot_id) VALUES (?,?)",
                           (h["item_id"], candidatas[0]["id"]))
    except Exception:
        pass

    try:
        _backfill_remitos_ott_cantidad(db)
    except Exception as e:
        print("[remitos] no se pudo completar ott_cantidad de remitos viejos:", e)
    try:
        # Backfill: los requerimientos de compra ya creados con el esquema
        # viejo tienen numero="OCP-ITEM-{item_id}" y origen_item_id NULL. Se
        # completa origen_item_id a partir de ese numero para que el sync los
        # siga encontrando (y no duplique) aunque más adelante se les asigne
        # un numero correlativo nuevo.
        db.execute("""UPDATE requerimientos_productivos
            SET origen_item_id = CAST(SUBSTR(numero, 10) AS INTEGER)
            WHERE numero LIKE 'OCP-ITEM-%' AND origen_item_id IS NULL""")
    except Exception: pass
    try:
        # Backfill: antes, cantidad_original de un lote generado por retorno
        # de OTT (ver ott_registrar_retorno) se iba SUMANDO en cada recepción
        # parcial, sin bajar nunca al devolver piezas rechazadas — un ciclo
        # de rechazo → devolución → reingreso del reemplazo terminaba
        # inflando el original más allá de lo realmente enviado (ver fix en
        # ott_registrar_retorno). Se corrige una sola vez: para todo lote de
        # retorno de OTT cuyo original quedó por encima de lo enviado, se
        # baja a cantidad_enviada.
        db.execute("""UPDATE lotes SET cantidad_original=(
                SELECT ott.cantidad_enviada FROM ordenes_tercerizado ott WHERE ott.lote_retorno_id=lotes.id
            )
            WHERE id IN (
                SELECT ott.lote_retorno_id FROM ordenes_tercerizado ott
                WHERE ott.lote_retorno_id IS NOT NULL AND COALESCE(ott.cantidad_enviada,0) > 0
                  AND (SELECT l2.cantidad_original FROM lotes l2 WHERE l2.id=ott.lote_retorno_id) > ott.cantidad_enviada
            )""")
    except Exception: pass

    # Backfill: filas viejas de "producto como insumo" (tipo='producto') que
    # quedaron con material_id NULL — de antes de que estas filas se
    # resolvieran al material 'Producto terminado' del producto al guardar
    # la operación (ver create_operacion/update_operacion). Sin material_id
    # estas filas quedaban afuera de toda la trazabilidad por lote (no
    # aparecían en "Lotes asignados", en el modal de novedad, ni se
    # descontaban del stock/lote al completar la OT). Se completan acá para
    # que las operaciones ya guardadas también queden con selección de lote.
    try:
        huerfanas = db.execute(
            "SELECT id, producto_id FROM operacion_materiales WHERE tipo='producto' AND material_id IS NULL AND producto_id IS NOT NULL"
        ).fetchall()
        for hr in huerfanas:
            prod_h = db.execute("SELECT id,codigo,nombre,unidad FROM productos WHERE id=?", (hr["producto_id"],)).fetchone()
            if not prod_h:
                continue
            # Réplica in-line de get_or_create_pt_material (acá no hay contexto
            # de Flask/g todavía para usar query()/execute()/esa función).
            mat_h = db.execute(
                "SELECT id FROM materiales WHERE producto_id=? AND categoria='Producto terminado'",
                (prod_h["id"],)).fetchone()
            if mat_h:
                mat_h_id = mat_h["id"]
            else:
                codigo_base = prod_h["codigo"]
                candidato = codigo_base
                intento = 1
                while db.execute("SELECT id FROM materiales WHERE codigo=?", (candidato,)).fetchone():
                    intento += 1
                    candidato = f"{codigo_base}-PT{intento}"
                cur_h = db.execute(
                    "INSERT INTO materiales (codigo,descripcion,categoria,producto_id,unidad,stock,stock_min) VALUES (?,?,?,?,?,0,0)",
                    (candidato, prod_h["nombre"], "Producto terminado", prod_h["id"], prod_h["unidad"]))
                mat_h_id = cur_h.lastrowid
            db.execute("UPDATE operacion_materiales SET material_id=? WHERE id=?", (mat_h_id, hr["id"]))
        if huerfanas:
            db.commit()
    except Exception as e:
        print(f"[init_db] Advertencia: no se pudo hacer backfill de operacion_materiales.material_id para tipo='producto': {e}")

    # Recalcular rendimiento de novedades existentes con la MISMA fórmula que
    # el alta/edición de novedades y el botón "Corregir" de Novedades por OT:
    # ciclo de la operación en su OT (si no tiene, el de la plantilla) y
    # tiempo_real sin restar tiempo_perdido (tiempo_real ya es neto). Antes
    # usaba la plantilla primero y restaba tiempo_perdido, así que cada
    # reinicio pisaba valores correctos y "Corregir" siempre encontraba
    # novedades para corregir.
    try:
        novedades = db.execute(
            "SELECT n.id, n.cantidad_producida, n.tiempo_real_min, "
            "COALESCE(NULLIF(oo.tiempo_ciclo_seg,0), po.tiempo_ciclo_seg, 60) ciclo "
            "FROM novedades_produccion n "
            "JOIN orden_operaciones oo ON oo.id=n.orden_operacion_id "
            "LEFT JOIN proceso_operaciones po ON po.id=oo.proceso_op_id"
        ).fetchall()
        for nov in novedades:
            # El ciclo estandar se carga en SEGUNDOS; tiempo_real_min esta en
            # minutos, asi que se pasa a minutos antes de comparar.
            ciclo  = float(nov["ciclo"] or 60) / 60.0
            qty    = float(nov["cantidad_producida"] or 0)
            t_real = float(nov["tiempo_real_min"] or 0)
            t_prod = max(t_real, 0.1)
            if t_real > 0:
                rend = round((qty / t_prod) / (1 / ciclo) * 100, 1)
                rend = min(rend, 999)
                desv = 1 if rend < 80 else 0
                db.execute(
                    "UPDATE novedades_produccion SET rendimiento_pct=?, desvio=? WHERE id=?",
                    (rend, desv, nov["id"])
                )
    except Exception as e:
        print(f"[init_db] Advertencia al recalcular rendimiento: {e}")

    # Red de seguridad: topear cualquier rendimiento que haya quedado por
    # encima de 999 (incluidas novedades que no entraron en el recálculo
    # anterior, p.ej. por operación eliminada).
    try:
        db.execute("UPDATE novedades_produccion SET rendimiento_pct=999 WHERE rendimiento_pct>999")
    except Exception as e:
        print(f"[init_db] Advertencia al topear rendimiento: {e}")

    db.commit()  # liberar la transacción abierta por las correcciones de arriba:
                 # las de abajo usan get_db()/query(), que abren una conexión
                 # sqlite3 aparte; si 'db' sigue con una transacción sin
                 # confirmar, esa segunda conexión choca con "database is locked".

    # Reparación: OTTs intermedias cuyo lote de retorno ya está Aprobado
    # pero la orden_operacion tercerizada quedó sin marcarse Completada
    # (bug: faltaba la sincronización — ver _sync_ott_retorno_a_operacion).
    # Esto dejaba la OT pausada para siempre en operaciones posteriores.
    try:
        with app.app_context():
            pendientes = query("""SELECT lote_retorno_id FROM ordenes_tercerizado
                WHERE es_ultimo_nivel=0 AND lote_retorno_id IS NOT NULL""")
            for p in pendientes:
                _sync_ott_retorno_a_operacion(p["lote_retorno_id"])
    except Exception as e:
        print(f"[init_db] Advertencia reparando OTTs con lote aprobado: {e}")

    # Reparación: materiales de retorno de OTT intermedia (semielaborados)
    # que quedaron con categoria distinta a 'Semielaborado' porque
    # ott_registrar_retorno reutilizaba cualquier material existente con
    # el mismo producto_id sin filtrar por categoria (bug corregido). Un
    # material así puede tener MEZCLADOS lotes propios (p.ej. Producto
    # terminado real) con lotes de retorno de OTT. NO se puede arreglar
    # recategorizando el material entero (eso arrastra también el stock
    # ajeno) — hay que separar lote por lote: los vinculados a una OTT
    # (ordenes_tercerizado.lote_retorno_id) van a un material nuevo
    # 'Semielaborado' con código (código del producto)-SE; el resto se
    # queda donde estaba.
    try:
        with app.app_context():
            afectados = query("""
                SELECT DISTINCT m.id mat_id, m.codigo mat_codigo, pr.codigo prod_codigo,
                       pr.id producto_id, m.unidad, m.precio_unit
                FROM ordenes_tercerizado ott
                JOIN lotes l ON l.id=ott.lote_retorno_id
                JOIN materiales m ON m.id=l.material_id
                JOIN productos pr ON pr.id=m.producto_id
                WHERE ott.es_ultimo_nivel=0 AND m.categoria != 'Semielaborado'
            """)
            for m in afectados:
                lotes_ott_ids = {r["lote_retorno_id"] for r in query(
                    """SELECT lote_retorno_id FROM ordenes_tercerizado
                       WHERE lote_retorno_id IS NOT NULL
                         AND EXISTS (SELECT 1 FROM lotes l2 WHERE l2.id=ordenes_tercerizado.lote_retorno_id
                                     AND l2.material_id=?)""", (m["mat_id"],))}
                if not lotes_ott_ids:
                    continue
                nuevo_codigo = f"{m['prod_codigo']}-SE"
                candidato = nuevo_codigo
                intento = 1
                while query("SELECT id FROM materiales WHERE codigo=?", (candidato,), one=True):
                    intento += 1
                    candidato = f"{nuevo_codigo}{intento}"
                se_mat_id = execute("""INSERT INTO materiales
                    (codigo,descripcion,categoria,producto_id,unidad,stock,stock_min,precio_unit,activo)
                    SELECT ?, descripcion, 'Semielaborado', producto_id, unidad, 0, 0, precio_unit, 1
                    FROM materiales WHERE id=?""", (candidato, m["mat_id"]))
                lotes_a_mover = query(
                    f"SELECT id,cantidad_activa FROM lotes WHERE id IN "
                    f"({','.join('?'*len(lotes_ott_ids))})", tuple(lotes_ott_ids))
                total_mover = sum(float(l["cantidad_activa"] or 0) for l in lotes_a_mover)
                execute(f"UPDATE lotes SET material_id=? WHERE id IN "
                        f"({','.join('?'*len(lotes_ott_ids))})",
                        (se_mat_id, *lotes_ott_ids))
                execute("UPDATE materiales SET stock=stock-? WHERE id=?", (total_mover, m["mat_id"]))
                execute("UPDATE materiales SET stock=stock+? WHERE id=?", (total_mover, se_mat_id))
                print(f"[init_db] Separados {len(lotes_ott_ids)} lote(s) de retorno OTT "
                      f"({total_mover:g} unid.) del material id={m['mat_id']} ({m['mat_codigo']}) "
                      f"hacia material nuevo id={se_mat_id} ({candidato})")
    except Exception as e:
        print(f"[init_db] Advertencia reparando materiales semielaborados: {e}")

    # Backfill del versionado de semielaborados. Los que ya existen se quedan
    # con la firma que tienen HOY sus insumos: son la versión vigente, y así
    # _get_or_create_pse los reusa en vez de crear un -v2 de entrada para
    # todos. Las OTT que ya tienen lote de retorno se congelan al material de
    # ese lote, que es el que efectivamente están usando.
    try:
        with app.app_context():
            for m in query("""SELECT id, operacion_id FROM materiales
                    WHERE categoria='Semielaborado' AND operacion_id IS NOT NULL
                      AND pse_firma IS NULL"""):
                execute("UPDATE materiales SET pse_firma=? WHERE id=?",
                        (_firma_insumos_operacion(m["operacion_id"]), m["id"]))
            huerfanas = query("""SELECT ott.id, l.material_id
                FROM ordenes_tercerizado ott JOIN lotes l ON l.id=ott.lote_retorno_id
                WHERE ott.material_se_id IS NULL AND ott.es_ultimo_nivel=0""")
            for o in huerfanas:
                execute("UPDATE ordenes_tercerizado SET material_se_id=? WHERE id=?",
                        (o["material_id"], o["id"]))
            if huerfanas:
                print(f"[init_db] Semielaborado congelado en {len(huerfanas)} OTT(s) ya en curso")
    except Exception as e:
        print(f"[init_db] Advertencia en el backfill de semielaborados: {e}")

    # Reparación de la reparación anterior: una versión previa de esta
    # migración recategorizaba el material entero in-place a
    # 'Semielaborado' en vez de separar lotes, arrastrando también el
    # stock de lotes ajenos (p.ej. Producto terminado real) que
    # compartían el material. Acá se detectan esos materiales (codigo
    # terminado en "-SE", categoria 'Semielaborado') que todavía tengan
    # lotes NO vinculados a ninguna OTT, y se los separa hacia el
    # material original (o uno nuevo si no existe más).
    try:
        with app.app_context():
            se_materiales = query("""SELECT id, codigo, producto_id, unidad, precio_unit
                FROM materiales WHERE categoria='Semielaborado' AND codigo LIKE '%-SE'""")
            for m in se_materiales:
                lotes_ott_ids = {r["lote_retorno_id"] for r in query(
                    "SELECT lote_retorno_id FROM ordenes_tercerizado WHERE lote_retorno_id IS NOT NULL")}
                lotes_del_material = query(
                    "SELECT id,cantidad_activa FROM lotes WHERE material_id=?", (m["id"],))
                ajenos = [l for l in lotes_del_material if l["id"] not in lotes_ott_ids]
                if not ajenos:
                    continue
                codigo_original = m["codigo"][:-3]  # quita el sufijo "-SE"
                otro = query("SELECT id FROM materiales WHERE codigo=?", (codigo_original,), one=True)
                if otro:
                    destino_id = otro["id"]
                else:
                    destino_id = execute("""INSERT INTO materiales
                        (codigo,descripcion,categoria,producto_id,unidad,stock,stock_min,precio_unit,activo)
                        SELECT ?, descripcion, 'Producto terminado', producto_id, unidad, 0, stock_min, precio_unit, 1
                        FROM materiales WHERE id=?""", (codigo_original, m["id"]))
                total_mover = sum(float(l["cantidad_activa"] or 0) for l in ajenos)
                ph = ",".join("?"*len(ajenos))
                execute(f"UPDATE lotes SET material_id=? WHERE id IN ({ph})",
                        (destino_id, *[l["id"] for l in ajenos]))
                execute("UPDATE materiales SET stock=stock-? WHERE id=?", (total_mover, m["id"]))
                execute("UPDATE materiales SET stock=stock+? WHERE id=?", (total_mover, destino_id))
                print(f"[init_db] Separados {len(ajenos)} lote(s) ajenos ({total_mover:g} unid.) "
                      f"del material Semielaborado id={m['id']} hacia material id={destino_id} "
                      f"(codigo {codigo_original})")
    except Exception as e:
        print(f"[init_db] Advertencia separando lotes mezclados en semielaborados: {e}")


def _backfill_sc_ott():
    """Corre en cada arranque: toda OTT Pendiente sin envíos y sin SC del
    servicio recibe la suya (OTT cargadas antes de este cambio). Idempotente."""
    faltan = query("""SELECT ott.id FROM ordenes_tercerizado ott
        WHERE ott.estado='Pendiente' AND COALESCE(ott.cantidad_enviada,0)=0 AND ott.proveedor_id IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM solicitudes_compra s WHERE s.ott_id=ott.id AND s.ott_remito IS NULL
                          AND s.estado NOT IN ('Cancelada','Rechazada'))""")
    creadas = []
    for r in faltan:
        n = _asegurar_sc_ott(r["id"])
        if n:
            creadas.append(n)
            _sync_requerimiento_desde_ott(r["id"])
    if creadas:
        print(f"[OTT] Se generaron {len(creadas)} solicitudes de compra de servicio: {', '.join(creadas)}")


def _backfill_requerimientos_desde_ott():
    """Corre en cada arranque: sincroniza cualquier OTT que todavía no tenga
    su requerimiento_productivo espejo (OTT cargadas antes de este cambio,
    o casos donde el sync en caliente falló). Es idempotente y rápido —
    solo toca las OTT que faltan, no vuelve a tocar las que ya están."""
    faltantes = query("""SELECT ott.id FROM ordenes_tercerizado ott
        WHERE NOT EXISTS (SELECT 1 FROM requerimientos_productivos rp WHERE rp.numero=ott.numero)""")
    if faltantes:
        print(f"[requerimientos_productivos] Backfill: sincronizando {len(faltantes)} OTT existentes...")
        for row in faltantes:
            _sync_requerimiento_desde_ott(row["id"])
        print("[requerimientos_productivos] Backfill completo.")

def _backfill_requerimientos_desde_compras():
    """Corre en cada arranque: sincroniza cualquier ítem de OC productivo
    (material categoria='Material') que todavía no tenga su
    requerimiento_productivo espejo (OC cargadas antes de este cambio, o
    casos donde el sync en caliente falló). Idempotente — solo toca lo que
    falta. _sync_requerimiento_desde_compra ya filtra internamente por
    categoría, así que acá alcanza con pasarle todos los ítems sin espejo."""
    # Hasta 2026-10 recibir_oc no grababa fecha_recibida: se completa con la
    # fecha de la última recepción registrada de ese ítem, y las OC anuladas
    # pasan su requerimiento a ANULADO. Idempotente.
    a_corregir = query("""SELECT oci.id,
            (SELECT MAX(mv.fecha) FROM movimientos mv
              WHERE mv.material_id=oci.material_id
                AND (mv.referencia='Recep. '||oc.numero OR mv.referencia LIKE 'Recep. '||oc.numero||' · %')) f_mov,
            COALESCE(oc.fecha_completada, oc.creado) f_oc
        FROM ordenes_compra_items oci JOIN ordenes_compra oc ON oc.id=oci.oc_id
        WHERE COALESCE(oci.cantidad_recibida,0)>0 AND oci.fecha_recibida IS NULL""")
    for row in a_corregir:
        execute("UPDATE ordenes_compra_items SET fecha_recibida=? WHERE id=?", (row["f_mov"] or row["f_oc"], row["id"]))
        _sync_requerimiento_desde_compra(row["id"])
    for row in query("""SELECT oci.id FROM ordenes_compra_items oci
            JOIN ordenes_compra oc ON oc.id=oci.oc_id
            JOIN requerimientos_productivos rp ON rp.origen_item_id=oci.id
            WHERE oc.estado='Anulada' AND rp.estado!='ANULADO'"""):
        _sync_requerimiento_desde_compra(row["id"])
    # 2026-10: re-sincroniza todos los requerimientos de compra con las reglas
    # de entrega parcial (f_entrega solo con la entrega completa o la OC
    # cerrada/completada; Cerrada sin recibir = ANULADO). Idempotente: el sync
    # recalcula todo desde la OC y un UPDATE sin cambios no deja rastro.
    for row in query("""SELECT oci.id FROM ordenes_compra_items oci
            JOIN requerimientos_productivos rp ON rp.origen_item_id=oci.id"""):
        _sync_requerimiento_desde_compra(row["id"])
    # (el vínculo es origen_item_id: los requerimientos nuevos ya no llevan
    # numero 'OCP-ITEM-<id>' y antes se tomaban como faltantes en cada arranque)
    faltantes = query("""SELECT oci.id FROM ordenes_compra_items oci
        LEFT JOIN materiales m ON m.id=oci.material_id
        WHERE m.categoria='Material'
          AND NOT EXISTS (SELECT 1 FROM requerimientos_productivos rp WHERE rp.origen_item_id=oci.id)""")
    if faltantes:
        print(f"[requerimientos_productivos] Backfill: sincronizando {len(faltantes)} ítems de OC existentes...")
        for row in faltantes:
            _sync_requerimiento_desde_compra(row["id"])
        print("[requerimientos_productivos] Backfill completo (compras).")

def _backfill_requerimientos_desde_pedidos():
    """Corre en cada arranque: sincroniza cualquier ítem de pedido de cliente
    (ordenes_cliente_items) que todavía no tenga su requerimiento_productivo
    espejo (pedidos cargados antes de este cambio, o casos donde el sync en
    caliente falló). Idempotente — solo toca lo que falta."""
    faltantes = query("""SELECT oci.id FROM ordenes_cliente_items oci
        WHERE NOT EXISTS (SELECT 1 FROM requerimientos_productivos rp WHERE rp.numero='OC-CLI-ITEM-'||oci.id)""")
    if faltantes:
        print(f"[requerimientos_productivos] Backfill: sincronizando {len(faltantes)} ítems de pedido existentes...")
        for row in faltantes:
            _sync_requerimiento_desde_pedido(row["id"])
        print("[requerimientos_productivos] Backfill completo (pedidos de cliente).")


# Funciones de otras áreas. Van al final a propósito: así cada módulo ya
# definió todo lo suyo cuando otro lo importa, y no hay problemas de
# importación circular. Se usan recién al atender pedidos.
from .comun import _firma_insumos_operacion, cant_material
from .requerimientos import (_sync_requerimiento_desde_compra,
    _sync_requerimiento_desde_ott, _sync_requerimiento_desde_pedido)
from .ott import _asegurar_sc_ott
from .lotes import _sync_ott_retorno_a_operacion

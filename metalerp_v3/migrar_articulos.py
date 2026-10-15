#!/usr/bin/env python3
"""
migrar_articulos.py — Unifica `productos` y `materiales` en UNA sola tabla
`articulos` (MetalERP v3) y elimina las tablas viejas.

Diferencias con el esquema anterior:

  * UNA sola variable de categoria: `articulos.tipo`, con valores
        MP    Materia prima / material de compra
        PT    Producto terminado (se vende)
        PSE   Semielaborado propio (lo hace la planta)
        PSET  Semielaborado tercerizado (lo hace un proveedor)
        PCI   Producto como insumo: no se vende, pero se fabrica con su
              propia OT y se consume como insumo de otro articulo.
    Desaparecen `categoria` (texto libre: 'Material'/'Producto terminado'/
    'Semielaborado'/'Insumo') y la vieja `tipo` ('producto'/'material').

  * El PT deja de vivir en DOS filas. Antes cada producto tenia su fila
    maestra en `productos` MAS una fila espejo en `materiales`
    (categoria='Producto terminado') que era la que llevaba el stock y los
    lotes. Ahora es UNA fila: la maestra absorbe stock/stock_min/stock_max/
    precio_unit/proveedor_id del espejo, y todas las FKs que apuntaban al
    espejo se remapean a esa unica fila.

  * `productos` y `materiales` se ELIMINAN del destino, y las clausulas
    REFERENCES de las tablas dependientes pasan a apuntar a `articulos`.

Uso:
    py migrar_articulos.py database/metalerp.db database/metalerp_articulos.db

No modifica el archivo de origen.
"""
import os
import re
import shutil
import sqlite3
import sys

# Productos que en vez de PT deben quedar como PCI (producto como insumo:
# no se vende, pero se fabrica con OT propia). Se listan por `productos.id`
# del origen. El script informa los candidatos al final de cada corrida.
RECLASIFICAR_PCI = set()

# El origen trae 556 pares duplicados: una fila en `productos` y otra en
# `materiales` con EL MISMO codigo y el mismo nombre, sin `producto_id` que
# las vincule (quedaron asi de una importacion masiva que cargo el catalogo
# en las dos tablas). Son el mismo articulo fisico. Con esto en True se
# fusionan igual que los espejos de PT: una sola fila, que se queda con el
# stock/lotes/movimientos de la fila de materiales.
FUSIONAR_DUPLICADOS_POR_CODIGO = True

# Categoria que reciben esos pares fusionados.
TIPO_DUPLICADOS = "PT"

# Tablas cuya FK apuntaba a materiales.id y ahora apunta a articulos.id
TABLAS_FK_MATERIAL = [
    ("proveedor_materiales", "material_id"),
    ("remito_items", "material_id"),
    ("orden_lotes", "material_id"),
    ("movimientos", "material_id"),
    ("orden_materiales", "material_id"),
    ("solicitudes_compra", "material_id"),
    ("ordenes_compra_items", "material_id"),
    ("ordenes_tercerizado", "material_se_id"),
    ("lotes", "material_id"),
    ("pronostico_abastecimiento_items", "material_id"),
    ("recepciones", "material_id"),
    ("operacion_materiales", "material_id"),
]

# Tablas cuya FK apuntaba a productos.id y ahora apunta a articulos.id
TABLAS_FK_PRODUCTO = [
    ("operacion_materiales", "producto_id"),
    ("proceso_operaciones", "producto_id"),
    ("ordenes", "producto_id"),
    ("producto_clientes", "producto_id"),
    ("ordenes_cliente_items", "producto_id"),
    ("producto_versiones", "producto_id"),
    ("novedades_eliminadas", "producto_id"),
    ("pronostico_venta_items", "producto_id"),
]

DDL_ARTICULOS = """
    CREATE TABLE articulos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        -- UNICA variable de categoria del articulo (ver docstring del modulo)
        tipo TEXT NOT NULL CHECK(tipo IN ('MP','PT','PSE','PSET','PCI')),

        codigo TEXT NOT NULL,
        nombre TEXT,                  -- nombre visible (ex productos.nombre / materiales.descripcion)
        descripcion TEXT,             -- detalle largo (ex productos.descripcion)
        categoria_producto_id INTEGER REFERENCES categorias_producto(id),
        unidad TEXT,

        -- Ficha de fabricacion (PT y PCI; los semielaborados la heredan del padre)
        tiempo_total_hs REAL DEFAULT 0,
        costo_mat REAL DEFAULT 0,
        costo_mo REAL DEFAULT 0,
        precio_venta REAL DEFAULT 0,
        peso_kg REAL DEFAULT 0,
        cliente_id INTEGER,
        capacidad_cajon INTEGER,

        -- Stock e inventario
        stock REAL DEFAULT 0,
        stock_min REAL DEFAULT 0,
        stock_max REAL DEFAULT 0,
        precio_unit REAL DEFAULT 0,
        proveedor_id INTEGER,

        -- Semielaborados: de que articulo derivan y por que operacion
        articulo_padre_id INTEGER REFERENCES articulos(id),
        operacion_id INTEGER REFERENCES proceso_operaciones(id),
        pse_firma TEXT,

        activo INTEGER DEFAULT 1,
        obs TEXT,
        creado TEXT DEFAULT (datetime('now','localtime')),
        actualizado TEXT DEFAULT (datetime('now','localtime')),

        legacy_producto_id INTEGER,   -- id original en productos, si vino de ahi
        legacy_material_id INTEGER,   -- id original en materiales, si vino de ahi

        -- El PCI no se vende: la regla queda en la base, no en el codigo
        CHECK (tipo <> 'PCI' OR COALESCE(precio_venta,0) = 0)
    )
"""

DDL_INDICES = [
    "CREATE INDEX idx_articulos_codigo ON articulos(codigo)",
    "CREATE INDEX idx_articulos_tipo ON articulos(tipo)",
    "CREATE INDEX idx_articulos_padre ON articulos(articulo_padre_id)",
    "CREATE UNIQUE INDEX idx_articulos_legacy_prod ON articulos(legacy_producto_id) WHERE legacy_producto_id IS NOT NULL",
    "CREATE UNIQUE INDEX idx_articulos_legacy_mat ON articulos(legacy_material_id) WHERE legacy_material_id IS NOT NULL",
    # Traduccion de idx_materiales_producto_categoria_sinop: un solo
    # semielaborado por (padre, tipo) cuando no cuelga de una operacion.
    """CREATE UNIQUE INDEX idx_articulos_padre_tipo_sinop
           ON articulos(articulo_padre_id, tipo)
           WHERE articulo_padre_id IS NOT NULL AND operacion_id IS NULL""",
    # Traduccion de idx_materiales_prod_cat_op_firma: el semielaborado se
    # identifica por padre + tipo + operacion + firma de insumos.
    """CREATE UNIQUE INDEX idx_articulos_padre_tipo_op_firma
           ON articulos(articulo_padre_id, tipo, operacion_id, COALESCE(pse_firma,''))
           WHERE articulo_padre_id IS NOT NULL AND operacion_id IS NOT NULL""",
]


def _tipo_de_material(m):
    """Categoria nueva para una fila de `materiales` que NO es espejo de PT.

    'Semielaborado' se reparte en PSE/PSET respetando materiales.tipo, que ya
    traia esa distincion (la calcula _clasificar_tipo_material en server.py
    segun proceso_operaciones.es_tercerizada). Todo lo demas ('Material',
    'Insumo', 'Herramienta', 'Producto sin lote', NULL) es material de
    compra: MP.
    """
    if m["categoria"] == "Semielaborado":
        return "PSET" if m["tipo"] == "PSET" else "PSE"
    return "MP"


def migrar(origen, destino):
    if not os.path.exists(origen):
        sys.exit("No existe el origen: %s" % origen)
    for sufijo in ("", "-wal", "-shm"):
        if os.path.exists(destino + sufijo):
            os.remove(destino + sufijo)
    shutil.copy(origen, destino)

    conn = sqlite3.connect(destino)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_keys=OFF")

    cur.execute(DDL_ARTICULOS)
    for ddl in DDL_INDICES:
        cur.execute(ddl)

    productos = cur.execute("SELECT * FROM productos").fetchall()
    materiales = cur.execute("SELECT * FROM materiales").fetchall()

    # Filas de `materiales` que se fusionan con un producto, indexadas por
    # productos.id. Dos casos:
    #   a) el espejo de PT (vinculo explicito via materiales.producto_id)
    #   b) el duplicado por codigo de la importacion masiva, si esta activado
    espejos = {}
    for m in materiales:
        if m["categoria"] == "Producto terminado" and m["producto_id"] is not None:
            espejos[m["producto_id"]] = m

    duplicados_por_codigo = 0
    pares_codigo = set()
    if FUSIONAR_DUPLICADOS_POR_CODIGO:
        por_codigo = {p["codigo"]: p["id"] for p in productos}
        for m in materiales:
            pid = por_codigo.get(m["codigo"])
            if (pid is not None and m["producto_id"] is None
                    and m["categoria"] not in ("Producto terminado", "Semielaborado")
                    and pid not in espejos):
                espejos[pid] = m
                pares_codigo.add(pid)
                duplicados_por_codigo += 1

    # --- 1) productos (+ su espejo fusionado) -> PT / PCI -------------------
    map_producto = {}   # legacy productos.id  -> articulos.id
    map_material = {}   # legacy materiales.id -> articulos.id
    codigos_espejo_distintos = []
    for p in productos:
        e = espejos.get(p["id"])
        if p["id"] in RECLASIFICAR_PCI:
            tipo = "PCI"
        elif p["id"] in pares_codigo:
            tipo = TIPO_DUPLICADOS
        else:
            tipo = "PT"
        precio_venta = 0 if tipo == "PCI" else p["precio_venta"]
        cur.execute("""
            INSERT INTO articulos
                (tipo, codigo, nombre, descripcion, categoria_producto_id, unidad,
                 tiempo_total_hs, costo_mat, costo_mo, precio_venta, peso_kg,
                 cliente_id, capacidad_cajon,
                 stock, stock_min, stock_max, precio_unit, proveedor_id,
                 activo, obs, creado, actualizado,
                 legacy_producto_id, legacy_material_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (tipo, p["codigo"], p["nombre"], p["descripcion"],
              p["categoria_id"], p["unidad"],
              p["tiempo_total_hs"], p["costo_mat"], p["costo_mo"],
              precio_venta, p["peso_kg"], p["cliente_id"], p["capacidad_cajon"],
              e["stock"] if e else 0, e["stock_min"] if e else 0,
              e["stock_max"] if e else 0, e["precio_unit"] if e else 0,
              e["proveedor_id"] if e else None,
              p["activo"], p["obs"], p["creado"],
              e["actualizado"] if e else None,
              p["id"], e["id"] if e else None))
        aid = cur.lastrowid
        map_producto[p["id"]] = aid
        if e:
            # El espejo NO genera fila propia: todo lo que le apuntaba pasa a
            # apuntar al PT.
            map_material[e["id"]] = aid
            if e["codigo"] != p["codigo"]:
                codigos_espejo_distintos.append((p["codigo"], e["codigo"]))

    # --- 2) materiales restantes -> MP / PSE / PSET -------------------------
    huerfanos_espejo = []
    for m in materiales:
        if m["id"] in map_material:
            continue
        if m["categoria"] == "Producto terminado":
            # Espejo sin producto: quedo colgado en el modelo viejo.
            huerfanos_espejo.append((m["id"], m["codigo"], m["descripcion"]))
        cur.execute("""
            INSERT INTO articulos
                (tipo, codigo, nombre, categoria_producto_id, unidad,
                 stock, stock_min, stock_max, precio_unit, proveedor_id,
                 operacion_id, pse_firma, activo, obs, actualizado,
                 legacy_material_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (_tipo_de_material(m), m["codigo"], m["descripcion"],
              m["categoria_producto_id"], m["unidad"], m["stock"],
              m["stock_min"], m["stock_max"], m["precio_unit"],
              m["proveedor_id"], m["operacion_id"], m["pse_firma"],
              m["activo"], m["obs"], m["actualizado"], m["id"]))
        map_material[m["id"]] = cur.lastrowid

    # --- 3) materiales.producto_id -> articulos.articulo_padre_id ----------
    for m in materiales:
        if m["producto_id"] is None or m["id"] not in map_material:
            continue
        padre = map_producto.get(m["producto_id"])
        if padre is not None and map_material[m["id"]] != padre:
            cur.execute("UPDATE articulos SET articulo_padre_id=? WHERE id=?",
                        (padre, map_material[m["id"]]))

    # --- 4) Remapear FKs en las tablas dependientes -------------------------
    # Dos pasadas (primero a -nuevo_id, despues a +nuevo_id) porque el rango
    # de ids viejos y el de ids nuevos se superponen: pasar por negativo evita
    # que dos filas choquen en un UNIQUE de forma intermedia, sin importar el
    # orden en que se actualicen.
    def _remapear(tabla, col, mapa):
        filas = cur.execute(
            "SELECT id, %s FROM %s WHERE %s IS NOT NULL" % (col, tabla, col)).fetchall()
        pendientes = []
        for fila in filas:
            nuevo_id = mapa.get(fila[col])
            if nuevo_id is not None:
                cur.execute("UPDATE %s SET %s=? WHERE id=?" % (tabla, col),
                            (-nuevo_id, fila["id"]))
                pendientes.append((nuevo_id, fila["id"]))
        for nuevo_id, row_id in pendientes:
            cur.execute("UPDATE %s SET %s=? WHERE id=?" % (tabla, col),
                        (nuevo_id, row_id))

    for tabla, col in TABLAS_FK_MATERIAL:
        _remapear(tabla, col, map_material)
    for tabla, col in TABLAS_FK_PRODUCTO:
        _remapear(tabla, col, map_producto)

    # --- 5) Chau tablas viejas ---------------------------------------------
    cur.execute("DROP TABLE materiales")
    cur.execute("DROP TABLE productos")
    conn.commit()

    # --- 6) Reapuntar las clausulas REFERENCES a articulos ------------------
    # SQLite no permite ALTER de una FK; se edita el DDL en sqlite_master y se
    # sube schema_version para que las conexiones lo relean. No cambia ni un
    # byte de los datos, solo el texto del esquema.
    patron = re.compile(r"REFERENCES\s+(materiales|productos)\s*\(", re.I)
    cambios = [(n, patron.sub("REFERENCES articulos(", s))
               for n, s in cur.execute(
                   "SELECT name, sql FROM sqlite_master "
                   "WHERE type='table' AND sql IS NOT NULL")
               if patron.search(s)]
    version = cur.execute("PRAGMA schema_version").fetchone()[0]
    conn.isolation_level = None
    cur.execute("PRAGMA writable_schema=ON")
    for nombre, sql_nuevo in cambios:
        cur.execute("UPDATE sqlite_master SET sql=? WHERE type='table' AND name=?",
                    (sql_nuevo, nombre))
    cur.execute("PRAGMA schema_version=%d" % (version + 1))
    cur.execute("PRAGMA writable_schema=OFF")
    conn.close()

    # --- 7) Verificacion sobre una conexion limpia --------------------------
    conn = sqlite3.connect(destino)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    print("articulos: %d  (%d productos + %d materiales - %d fusionados:"
          " %d espejos de PT + %d duplicados por codigo)"
          % (cur.execute("SELECT COUNT(*) FROM articulos").fetchone()[0],
             len(productos), len(materiales), len(espejos),
             len(espejos) - duplicados_por_codigo, duplicados_por_codigo))
    print("REFERENCES reapuntadas a articulos en %d tablas" % len(cambios))
    print("\nPor tipo:")
    for r in cur.execute("SELECT tipo, COUNT(*) n FROM articulos GROUP BY tipo ORDER BY n DESC"):
        print("  %-5s %d" % (r["tipo"], r["n"]))

    print("\nIntegridad:")
    huerfanos = 0
    for tabla, col in TABLAS_FK_MATERIAL + TABLAS_FK_PRODUCTO:
        n = cur.execute("""SELECT COUNT(*) FROM %s t
            LEFT JOIN articulos a ON a.id = t.%s
            WHERE t.%s IS NOT NULL AND a.id IS NULL""" % (tabla, col, col)).fetchone()[0]
        if n:
            print("  FALLA: %d filas huerfanas en %s.%s" % (n, tabla, col))
        huerfanos += n
    print("  filas huerfanas: %d" % huerfanos)
    fk = cur.execute("PRAGMA foreign_key_check").fetchall()
    print("  foreign_key_check: %d violaciones%s"
          % (len(fk), (" -> %s" % [tuple(f) for f in fk[:5]]) if fk else ""))
    print("  integrity_check: %s" % cur.execute("PRAGMA integrity_check").fetchone()[0])
    sobran = cur.execute("""SELECT COUNT(*) FROM sqlite_master
        WHERE name IN ('productos','materiales')""").fetchone()[0]
    print("  tablas viejas restantes: %d" % sobran)

    print("\nAvisos:")
    avisos = 0
    for cod_prod, cod_esp in codigos_espejo_distintos:
        print("  PT '%s': el espejo tenia codigo '%s', queda el del producto"
              % (cod_prod, cod_esp))
        avisos += 1
    for mid, cod, desc in huerfanos_espejo:
        print("  material %d '%s' (%s) era 'Producto terminado' sin producto -> MP"
              % (mid, cod, desc))
        avisos += 1
    dups = cur.execute("""SELECT codigo, COUNT(*) n, GROUP_CONCAT(tipo) tipos
        FROM articulos GROUP BY codigo HAVING n > 1 ORDER BY codigo""").fetchall()
    for d in dups[:10]:
        print("  codigo duplicado '%s' x%d (%s)" % (d["codigo"], d["n"], d["tipos"]))
    if dups:
        print("  ... %d codigos duplicados en total" % len(dups))
        avisos += 1
    for c in cur.execute("""SELECT a.id, a.codigo, a.nombre FROM articulos a
            WHERE a.tipo='PT' AND COALESCE(a.precio_venta,0)=0
              AND EXISTS (SELECT 1 FROM operacion_materiales om WHERE om.producto_id=a.id)
            ORDER BY a.id"""):
        print("  candidato a PCI: articulo %d '%s' (%s) -- sin precio y se consume como insumo"
              % (c["id"], c["codigo"], c["nombre"]))
        avisos += 1
    if not avisos:
        print("  (ninguno)")

    conn.close()
    return huerfanos == 0 and not fk


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Uso: py migrar_articulos.py <origen.db> <destino.db>")
        sys.exit(1)
    sys.exit(0 if migrar(sys.argv[1], sys.argv[2]) else 2)

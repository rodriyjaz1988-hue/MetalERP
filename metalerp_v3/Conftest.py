"""
Fixtures compartidas de los tests del permiso "ver valores monetarios".

Cómo obtiene la base de prueba (NUNCA toca database/metalerp.db):
  1. Si existe la variable METALERP_TEST_DB, copia ese archivo a un tmp.
  2. Si no, crea una base nueva con server.init_db() sobre un tmp.
  3. Si init_db() se niega (p.ej. falta migracion_unificacion.py), copia
     database/metalerp.db a un tmp.
  4. Si nada funciona, los tests se saltean con un mensaje claro.

Sobre esa copia se siembran filas con valores centinela únicos en TODA columna
monetaria, así cualquier filtración queda a la vista.
"""
import os
import re
import shutil
import sqlite3
import sys

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

# Valores centinela: poco probables de aparecer por casualidad.
CENTINELA_REAL = 7777.77      # columnas REAL / NUMERIC / FLOAT
CENTINELA_ENTERO = 913579     # columnas INTEGER
# Representaciones de texto que se buscan en JSON/PDF/Excel (solo dígitos).
CENTINELAS_DIGITOS = ("777777", "913579")

PASS = "Test#12345"
USUARIOS = {
    # username: (rol, permisos explícitos)
    "t_admin": ("admin", {}),                                     # con permiso
    "t_vendedor_ok": ("vendedor", {}),                            # con permiso (sin ver_monetario='0')
    "t_restringido": ("vendedor", {"ver_monetario": "0"}),        # restringido por permiso
    "t_logistica": ("logistica", {}),                             # restringido por rol
}

# Tablas que no se siembran con filas genéricas.
TABLAS_NO_SEMBRAR = {"usuarios", "usuario_permisos", "roles", "sqlite_sequence",
                     "auditoria", "auditoria_cambios"}

_TIPOS_ENTEROS = ("INT",)


def _es_monetaria(nombre):
    import server
    return nombre in server.CAMPOS_MONETARIOS


def _valor_centinela(tipo):
    return CENTINELA_ENTERO if "INT" in (tipo or "").upper() else CENTINELA_REAL


def _crear_base(tmp_path_factory):
    import server
    destino = str(tmp_path_factory.mktemp("db") / "test.db")
    fuente = os.environ.get("METALERP_TEST_DB")
    if fuente:
        shutil.copy(fuente, destino)
        return destino
    server.DB_PATH = destino
    try:
        server.init_db()
        return destino
    except SystemExit as e:
        real = os.path.join(RAIZ, "database", "metalerp.db")
        if os.path.exists(real):
            if os.path.exists(destino):
                os.remove(destino)
            shutil.copy(real, destino)
            return destino
        pytest.skip(f"No se pudo preparar la base de prueba: {e}")


def _sembrar_todo(db):
    """Inserta 1 fila por tabla (padres primero) con centinelas en las columnas
    monetarias. Devuelve la lista de tablas que no se pudieron sembrar."""
    db.execute("PRAGMA foreign_keys=OFF")
    tablas = [r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    tablas = [t for t in tablas if t not in TABLAS_NO_SEMBRAR]

    info = {t: db.execute(f"PRAGMA table_info({t})").fetchall() for t in tablas}
    fks = {t: {r[3]: r[2] for r in db.execute(f"PRAGMA foreign_key_list({t})")} for t in tablas}

    # Orden topológico simple por dependencias de FK.
    orden, pendientes = [], set(tablas)
    while pendientes:
        listo = [t for t in sorted(pendientes)
                 if all(p == t or p not in pendientes for p in fks[t].values())]
        if not listo:               # ciclo: se rompe por cualquier lado
            listo = [sorted(pendientes)[0]]
        for t in listo:
            orden.append(t)
            pendientes.discard(t)

    # Vistas de compatibilidad (p.ej. productos -> materiales): el padre real es la tabla base.
    alias = {"productos": "materiales"}
    ids, fallidas, n = {}, [], 0
    for t in orden + orden:          # 2 vueltas: un padre que falló la 1ª puede entrar en la 2ª
        if t in ids:
            continue
        cols, vals = [], []
        for cid, nombre, tipo, notnull, dflt, pk in info[t]:
            if pk and "INT" in (tipo or "").upper():
                continue
            n += 1
            if nombre in fks[t]:
                padre = fks[t][nombre]
                padre = padre if padre in ids else alias.get(padre, padre)
                if padre in ids:
                    cols.append(nombre); vals.append(ids[padre])
                continue
            if _es_monetaria(nombre):
                cols.append(nombre); vals.append(_valor_centinela(tipo)); continue
            if dflt is not None or not notnull:
                continue
            up = (tipo or "").upper()
            if re.search(r"fecha|creado|desde|hasta", nombre):
                vals.append("2026-10-13")
            elif any(x in up for x in ("INT", "REAL", "NUM", "FLOA", "DOUB")):
                vals.append(1)
            else:
                vals.append(f"S{n}-{nombre}"[:40])
            cols.append(nombre)
        fallidas = [f for f in fallidas if f[0] != t]
        try:
            if cols:
                cur = db.execute(
                    f"INSERT INTO {t} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", vals)
            else:
                cur = db.execute(f"INSERT INTO {t} DEFAULT VALUES")
            ids[t] = cur.lastrowid
        except sqlite3.Error as e:
            fallidas.append((t, str(e)))
    db.commit()
    db.execute("PRAGMA foreign_keys=ON")
    return fallidas


def _sembrar_config(db):
    """Claves de configuracion con contenido monetario (se filtran por clave)."""
    import server
    try:
        db.execute("INSERT OR REPLACE INTO configuracion (clave, valor) VALUES (?,?)",
                   ("valor_hora_mo", str(CENTINELA_REAL)))
    except sqlite3.Error:
        pass


def _crear_usuarios(db):
    import server
    for username, (rol, perms) in USUARIOS.items():
        db.execute("INSERT OR REPLACE INTO usuarios (username,password,nombre,rol,activo) "
                   "VALUES (?,?,?,?,1)", (username, server.hash_pw(PASS), username, rol))
        uid = db.execute("SELECT id FROM usuarios WHERE username=?", (username,)).fetchone()[0]
        db.execute("DELETE FROM usuario_permisos WHERE usuario_id=?", (uid,))
        for k, v in perms.items():
            db.execute("INSERT INTO usuario_permisos (usuario_id,clave,valor) VALUES (?,?,?)",
                       (uid, k, v))
    db.commit()


@pytest.fixture(scope="session")
def db_path(tmp_path_factory):
    import server
    path = _crear_base(tmp_path_factory)
    server.DB_PATH = path
    db = sqlite3.connect(path)
    _crear_usuarios(db)
    fallidas = _sembrar_todo(db)
    _sembrar_config(db)
    db.commit()
    db.close()
    server.SEMBRADO_FALLIDO = fallidas
    return path


@pytest.fixture(scope="session")
def server_mod(db_path):
    import server
    server.DB_PATH = db_path
    server.app.config["TESTING"] = True
    server.app.config["PROPAGATE_EXCEPTIONS"] = False   # un 500 se informa, no aborta el recorrido
    return server


@pytest.fixture(scope="session")
def flask_app(server_mod):
    return server_mod.app


def login_client(app, username):
    c = app.test_client()
    r = c.post("/login", json={"username": username, "password": PASS})
    assert r.status_code == 200 and r.get_json().get("ok"), f"login falló para {username}: {r.data[:200]}"
    return c


@pytest.fixture()
def cli_admin(flask_app):
    return login_client(flask_app, "t_admin")


@pytest.fixture()
def cli_ok(flask_app):
    return login_client(flask_app, "t_vendedor_ok")


@pytest.fixture()
def cli_restringido(flask_app):
    return login_client(flask_app, "t_restringido")


@pytest.fixture()
def cli_logistica(flask_app):
    return login_client(flask_app, "t_logistica")


def foto_bd(path):
    """Volcado completo (todas las tablas menos auditoría/sesión) para comparar antes/después."""
    db = sqlite3.connect(path)
    out = {}
    for (t,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' "
                           "AND name NOT LIKE 'sqlite_%' ORDER BY name"):
        if t in ("auditoria", "auditoria_cambios"):
            continue
        out[t] = db.execute(f"SELECT * FROM {t} ORDER BY 1").fetchall()
    db.close()
    return out
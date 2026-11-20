"""Usuarios, roles, permisos y empleados (RRHH)."""
from .nucleo import (_permisos_rol, _rol_row, app, execute, hash_pw, jsonify,
    login_required, query, request, ROLES_BASE, session)

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
    if not _rol_row(rol):
        return jsonify({"error": f"El rol \"{rol}\" no existe. Crealo antes en Configuración → Roles."}), 400
    
    # Crear el usuario
    execute("INSERT INTO usuarios (username,password,nombre,rol) VALUES (?,?,?,?)",
            (d["username"], hash_pw(d["password"]), d.get("nombre", d["username"]), rol))
    
    # Obtener el ID del usuario recién creado
    usuario_id = query("SELECT id FROM usuarios WHERE username=?", (d["username"],), one=True)["id"]
    
    # Asignar permisos predeterminados según el rol
    # Admin no necesita permisos explícitos (tiene acceso total)
    if rol != "admin":
        for clave, valor in _permisos_rol(rol).items():
            execute("""INSERT OR IGNORE INTO usuario_permisos (usuario_id, clave, valor) 
                      VALUES (?, ?, ?)""",
                    (usuario_id, clave, valor))
    
    return jsonify({"ok": True}), 201

@app.route("/api/usuarios/<int:uid>", methods=["PUT"])
@login_required(roles=["admin"])
def update_usuario(uid):
    d = request.json
    if not query("SELECT id FROM usuarios WHERE id=?", (uid,), one=True):
        return jsonify({"error":"Usuario no encontrado"}), 404
    dup = query("SELECT id FROM usuarios WHERE username=? AND id<>?", (d.get("username",""), uid), one=True)
    if dup:
        return jsonify({"error":"Usuario ya existe"}), 409

    nombre = d.get("nombre") or d.get("username","")
    rol = d.get("rol", "operario")
    if not _rol_row(rol):
        return jsonify({"error": f"El rol \"{rol}\" no existe. Crealo antes en Configuración → Roles."}), 400
    activo = 1 if d.get("activo", 1) else 0
    _rol_previo = query("SELECT rol FROM usuarios WHERE id=?", (uid,), one=True)["rol"]

    if d.get("password"):
        execute("UPDATE usuarios SET username=?,nombre=?,rol=?,activo=?,password=? WHERE id=?",
                (d["username"], nombre, rol, activo, hash_pw(d["password"]), uid))
    else:
        execute("UPDATE usuarios SET username=?,nombre=?,rol=?,activo=? WHERE id=?",
                (d["username"], nombre, rol, activo, uid))

    # Si cambió el rol, el usuario recibe los permisos predeterminados del rol nuevo.
    if rol != _rol_previo and rol != "admin":
        execute("DELETE FROM usuario_permisos WHERE usuario_id=?", (uid,))
        for clave, valor in _permisos_rol(rol).items():
            execute("INSERT OR IGNORE INTO usuario_permisos (usuario_id,clave,valor) VALUES (?,?,?)", (uid, clave, valor))

    return jsonify({"ok": True})

# ── Roles editables (v147, punto 12) ─────────────────────────────────────────
@app.route("/api/roles", methods=["GET"])
@login_required()
def get_roles():
    import json as _j
    out = []
    for r in query("SELECT * FROM roles ORDER BY es_sistema DESC, nombre"):
        d = dict(r)
        try: d["permisos"] = _j.loads(d.get("permisos") or "{}")
        except Exception: d["permisos"] = {}
        d["usuarios"] = query("SELECT COUNT(*) c FROM usuarios WHERE rol=? AND activo=1", (d["nombre"],), one=True)["c"]
        out.append(d)
    return jsonify(out)

@app.route("/api/roles", methods=["POST"])
@login_required(roles=["admin"])
def create_rol():
    import json as _j
    d = request.json or {}
    nombre = (d.get("nombre") or "").strip().lower().replace(" ", "_")
    if not nombre: return jsonify({"error":"Nombre requerido"}), 400
    if d.get("base_rol") not in ROLES_BASE: return jsonify({"error":"Rol base inválido"}), 400
    if _rol_row(nombre): return jsonify({"error":"Ya existe un rol con ese nombre"}), 409
    permisos = {k: str(v) for k, v in (d.get("permisos") or {}).items()}
    rid = execute("INSERT INTO roles (nombre,descripcion,base_rol,permisos,es_sistema) VALUES (?,?,?,?,0)",
                  (nombre, d.get("descripcion"), d["base_rol"], _j.dumps(permisos)))
    return jsonify({"ok":True,"id":rid,"nombre":nombre}), 201

@app.route("/api/roles/<int:rid>", methods=["PUT"])
@login_required(roles=["admin"])
def update_rol(rid):
    import json as _j
    d = request.json or {}
    r = query("SELECT * FROM roles WHERE id=?", (rid,), one=True)
    if not r: return jsonify({"error":"Rol no encontrado"}), 404
    permisos = {k: str(v) for k, v in (d.get("permisos") or {}).items()} if "permisos" in d else None
    if r["es_sistema"]:
        # los roles de sistema conservan nombre y rol base; solo se editan descripción y permisos
        execute("UPDATE roles SET descripcion=?, permisos=COALESCE(?,permisos) WHERE id=?",
                (d.get("descripcion", r["descripcion"]), _j.dumps(permisos) if permisos is not None else None, rid))
        return jsonify({"ok":True})
    nuevo = (d.get("nombre") or r["nombre"]).strip().lower().replace(" ", "_")
    base = d.get("base_rol", r["base_rol"])
    if base not in ROLES_BASE: return jsonify({"error":"Rol base inválido"}), 400
    if nuevo != r["nombre"] and _rol_row(nuevo): return jsonify({"error":"Ya existe un rol con ese nombre"}), 409
    execute("UPDATE roles SET nombre=?,descripcion=?,base_rol=?,permisos=COALESCE(?,permisos) WHERE id=?",
            (nuevo, d.get("descripcion", r["descripcion"]), base, _j.dumps(permisos) if permisos is not None else None, rid))
    if nuevo != r["nombre"]:
        execute("UPDATE usuarios SET rol=? WHERE rol=?", (nuevo, r["nombre"]))
    return jsonify({"ok":True})

@app.route("/api/roles/<int:rid>/aplicar_permisos", methods=["POST"])
@login_required(roles=["admin"])
def aplicar_permisos_rol(rid):
    """Copia los permisos del rol a todos sus usuarios (reemplaza los individuales)."""
    r = query("SELECT * FROM roles WHERE id=?", (rid,), one=True)
    if not r: return jsonify({"error":"Rol no encontrado"}), 404
    if r["nombre"] == "admin": return jsonify({"ok":True,"usuarios":0})
    n = 0
    for u in query("SELECT id FROM usuarios WHERE rol=?", (r["nombre"],)):
        execute("DELETE FROM usuario_permisos WHERE usuario_id=?", (u["id"],))
        for clave, valor in _permisos_rol(r["nombre"]).items():
            execute("INSERT OR IGNORE INTO usuario_permisos (usuario_id,clave,valor) VALUES (?,?,?)", (u["id"], clave, valor))
        n += 1
    return jsonify({"ok":True,"usuarios":n})

@app.route("/api/roles/<int:rid>", methods=["DELETE"])
@login_required(roles=["admin"])
def delete_rol(rid):
    r = query("SELECT * FROM roles WHERE id=?", (rid,), one=True)
    if not r: return jsonify({"error":"Rol no encontrado"}), 404
    if r["es_sistema"]: return jsonify({"error":"Los roles de sistema no se pueden eliminar"}), 400
    en_uso = query("SELECT COUNT(*) c FROM usuarios WHERE rol=?", (r["nombre"],), one=True)["c"]
    if en_uso: return jsonify({"error":f"El rol está asignado a {en_uso} usuario(s). Reasignalos antes de eliminarlo."}), 400
    execute("DELETE FROM roles WHERE id=?", (rid,))
    return jsonify({"ok":True})

@app.route("/api/usuarios/<int:uid>", methods=["DELETE"])
@login_required(roles=["admin"])
def delete_usuario(uid):
    if uid == session["user_id"]: return jsonify({"error":"No podés eliminar tu propio usuario"}), 400
    execute("UPDATE usuarios SET activo=0 WHERE id=?", (uid,))
    return jsonify({"ok":True})

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
    lid = execute("INSERT INTO empleados (legajo,nombre,apellido,cargo,tipo,turno,obs,fecha_alta,fecha_baja) VALUES (?,?,?,?,?,?,?,?,?)",
        (d["legajo"],d["nombre"],d.get("apellido"),d.get("cargo"),d.get("tipo","Indirecto"),d.get("turno"),d.get("obs"),d.get("fecha_alta"),d.get("fecha_baja")))
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
    execute("UPDATE empleados SET legajo=?,nombre=?,apellido=?,cargo=?,tipo=?,turno=?,activo=?,obs=?,fecha_alta=?,fecha_baja=? WHERE id=?",
        (d.get("legajo"),d["nombre"],d["apellido"],d.get("cargo"),d.get("tipo","Indirecto"),d.get("turno"),
         1 if d.get("activo",True) else 0,d.get("obs"),d.get("fecha_alta"),d.get("fecha_baja"),eid))
    execute("DELETE FROM empleado_maquinas WHERE empleado_id=?", (eid,))
    for cmid in (d.get("maquinas") or []):
        try: execute("INSERT OR IGNORE INTO empleado_maquinas (empleado_id,categoria_maquina_id) VALUES (?,?)", (eid, cmid))
        except: pass
    return jsonify({"ok":True})

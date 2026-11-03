"""Login, logout, página principal, versión y manual de usuario."""
from .nucleo import (_permisos_sesion, _rol_base, app, hash_pw, jsonify, login_required,
    os, puede_ver_monetario, query, redirect, render_template, request,
    send_from_directory, session)

# ── Auth ──────────────────────────────────────────────────────────────────────
@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        d = request.get_json(silent=True) or request.form
        user = query("SELECT * FROM usuarios WHERE username=? AND activo=1", (d.get("username",""),), one=True)
        if user and user["password"] == hash_pw(d.get("password","")):
            session.update({"user_id":user["id"],"username":user["username"],"nombre":user["nombre"],
                            "rol":_rol_base(user["rol"]),"rol_nombre":user["rol"]})
            if request.is_json: return jsonify({"ok":True,"rol":_rol_base(user["rol"]),"rol_nombre":user["rol"],"nombre":user["nombre"]})
            return redirect("/")
        if request.is_json: return jsonify({"ok":False,"error":"Usuario o contraseña incorrectos"}), 401
    return render_template("login.html")

@app.route("/logout")
def logout(): session.clear(); return redirect("/login")

@app.route("/")
@login_required()
def index():
    perms = _permisos_sesion()
    ver_mon = puede_ver_monetario()
    # La plantilla recibe el permiso ya resuelto por el servidor; sacarlo de
    # perms evita que quede una segunda fuente de verdad en el navegador.
    perms = {k: v for k, v in perms.items() if k != "ver_monetario"}
    return render_template("app.html",
                          nombre=session["nombre"],
                          rol=session["rol"],
                          rol_nombre=session.get("rol_nombre") or session["rol"],
                          perms=perms,
                          ver_monetario=ver_mon,
                          ia=puede_usar_ia(),
                          moneda=moneda_sistema())

APP_VERSION = "150"

@app.route("/api/version")
@login_required()
def api_version():
    return jsonify({"version": APP_VERSION})

# ── Manual de usuario (punto 16): vive en la carpeta templates ───────────────
@app.route("/manual")
@login_required()
def manual_usuario():
    return send_from_directory(os.path.join(app.root_path, "templates"), "manual_usuario.html")

@app.route("/manual/<fmt>")
@login_required()
def manual_descarga(fmt):
    if fmt not in ("pdf", "docx"):
        return jsonify({"error": "Formato no válido"}), 404
    return send_from_directory(os.path.join(app.root_path, "templates"), "Manual_MetalERP." + fmt, as_attachment=True)


# Funciones de otras áreas. Van al final a propósito: así cada módulo ya
# definió todo lo suyo cuando otro lo importa, y no hay problemas de
# importación circular. Se usan recién al atender pedidos.
from .configuracion import moneda_sistema
from .ia import puede_usar_ia

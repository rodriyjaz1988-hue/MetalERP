#!/usr/bin/env python3
"""
E2E opcional: con un usuario SIN permiso "ver_monetario", recorre todos los
módulos del menú y verifica que ningún importe llegue al navegador.

Qué comprueba, módulo por módulo:
  1. Centinelas: ningún valor centinela (en cualquiera de sus formatos) aparece
     en el HTML de la página (código fuente, scripts incluidos), en el DOM
     renderizado ni en el cuerpo de las respuestas /api/ que recibió el navegador.
  2. `$` + dígito (y ARS/USD/U$S + dígito) en el DOM renderizado, sin contar
     <script>/<style>.
  3. Encabezados (<th>) y etiquetas (<label>/<legend>) con términos monetarios.
     Otros textos sueltos con esos términos se informan como AVISO (con
     E2E_STRICT_TEXT=1 también fallan).
  4. Inputs/selects/textarea monetarios que sigan en el DOM, aunque estén
     ocultos (display:none sigue exponiendo el valor), y atributos data-precio,
     data-costo, etc.
  5. Claves de CAMPOS_MONETARIOS (leídas de server.py, sin importarlo) en el
     JSON de las respuestas /api/.
  6. Módulos monetarios de punta a punta (dash_economico) ausentes del menú.

Control opcional (recomendado): con E2E_CONTROL_USER/E2E_CONTROL_PASS (un
usuario CON permiso) se verifica que los centinelas SÍ se vean en algún lado.
Si el control no los ve, el test está ciego (centinelas mal sembrados o
detector roto) y falla en lugar de dar un verde falso.

Requisitos: pip install playwright && playwright install chromium
Prerrequisitos: servidor levantado, usuario restringido existente y centinelas
sembrados en la base contra la que corre el servidor.

Uso:
  E2E_USER=restringido E2E_PASS=xxx E2E_SENTINELS=7777777.77,8888888.88 \
  [E2E_CONTROL_USER=admin E2E_CONTROL_PASS=yyy] \
  python tests/e2e_sin_monetario.py [--base-url http://127.0.0.1:5000] [--headed]

En Windows (PowerShell):
  $env:E2E_SENTINELS="7777777.77,8888888.88"
  python tests\\e2e_sin_monetario.py --user restringido --password xxx --control-user admin --control-password yyy
  (o pasar todo por flags, sin variables de entorno: ver --help)

Variables (todas tienen su flag equivalente, ver --help):
  E2E_BASE_URL, E2E_USER, E2E_PASS, E2E_SENTINELS (coma-separados),
  E2E_CONTROL_USER, E2E_CONTROL_PASS, E2E_STRICT_TEXT, E2E_SETTLE_MS, E2E_SERVER_PY
Código de salida: 0 todo bien, 1 hay hallazgos, 2 error de configuración/entorno.
"""
import argparse
import ast
import json
import os
import re
import sys
from pathlib import Path

# En Windows la consola suele ser cp1252 y los "─", "—" o "ñ" de los mensajes
# hacen caer el script con UnicodeEncodeError. Se fuerza UTF-8 (sin romper si
# la salida está redirigida a un archivo o a un pipe).
for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    from playwright.sync_api import sync_playwright, Error as PWError
except ImportError:  # pragma: no cover
    print("Falta playwright: pip install playwright && playwright install chromium")
    sys.exit(2)


class ErrorEntorno(Exception):
    """Problema de configuración/entorno (servidor caído, login, navegador): código de salida 2."""


def buscar_server_py(explicito=None):
    """Ubica server.py: --server-py/E2E_SERVER_PY, la carpeta padre de tests/, la carpeta
    del script o el directorio actual. Así funciona aunque el script no esté en tests/."""
    candidatos = []
    if explicito:
        candidatos.append(Path(explicito))
    aqui = Path(__file__).resolve().parent
    candidatos += [aqui.parent / "server.py", aqui / "server.py", Path.cwd() / "server.py",
                   Path.cwd().parent / "server.py"]
    for c in candidatos:
        if c.is_file():
            return c
    return candidatos[0] if explicito else aqui.parent / "server.py"


SERVER_PY = buscar_server_py()

# ── Zonas donde lo monetario es legítimo: ahí vive el checkbox del PERMISO ────
# (misma lista que _zonaExentaMonetario en app.html; si cambia allá, cambiar acá)
ZONAS_EXENTAS = "#p-auditoria,#mo-auditoria,#p-usuarios,#mo-permisos,#mo-rol"

# ── Módulos que, sin el permiso, no deben existir en el menú ni en el DOM ─────
MODULOS_PROHIBIDOS = ["dash_economico"]

# ── Inputs que matchean por nombre pero NO contienen ni piden un importe ─────
# Cada entrada necesita su motivo. Si alguna pasara a guardar dinero, sacarla.
IDS_PERMITIDOS = {
    "cfg-costos": "checkbox 0/1 'Mostrar costos en el PDF' (bandera, ver NO_MONETARIO en server.py)",
    "cfg-precios": "checkbox 0/1 'Mostrar precio de venta en el PDF' (bandera, ver NO_MONETARIO)",
    "ott-precio-id": "hidden con el id de la OTT que se está cotizando, no un importe",
    "ott-precio-prov": "select de proveedor dentro del modal de precio OTT, no un importe",
}

# ── Detectores (a propósito independientes de los regex del front: si el front
#    se equivoca en su regex, este test no debe equivocarse igual) ─────────────
RE_DOLAR_DIGITO = re.compile(r"(?:U\$S|US\$|\$)\s?\d", re.I)
RE_MONEDA_DIGITO = re.compile(r"\b(?:ARS|USD)\s?\d", re.I)
RE_TERMINO = re.compile(
    r"precio|costo|monto|importe|subtotal|facturaci|facturad|valor\s*(?:hora|mano)"
    r"|total\s+con\s+iva|iva\s*\(%\)|\(\$\)|\$\s*$|tarifa",
    re.I,
)
# Falsos positivos conocidos (códigos/condiciones que no son importes).
RE_PERMITIDO = re.compile(
    r"centro\s+de\s+costo|centro_costo|condici[oó]n|recalcul|nro\.?\s*factura|n[°º]\s*factura"
    r"|mostrar\s+(?:costos?|precios?)\b",
    re.I,
)
RE_NOMBRE_CAMPO = re.compile(r"precio|costo|monto|importe|subtotal|valor_hora|facturaci|facturad", re.I)
RE_NOMBRE_CAMPO_PERMITIDO = re.compile(r"centro_costo|nro_factura|ver_monetario", re.I)
RE_ATRIBUTO_DATA = re.compile(r"^data-(precio|costo|monto|importe|subtotal|total-?mon)", re.I)


# ── Utilidades ────────────────────────────────────────────────────────────────
def campos_monetarios_desde_server(ruta=None):
    """Lee CAMPOS_MONETARIOS de server.py con ast (no importa la app)."""
    ruta = Path(ruta) if ruta else SERVER_PY
    try:
        arbol = ast.parse(ruta.read_text(encoding="utf-8-sig"))
    except Exception as e:
        print(f"[aviso] No se pudo leer {ruta}: {e}. Se saltea el chequeo 5 (claves monetarias en la API); "
              f"pasá --server-py con la ruta correcta.")
        return set()
    for nodo in arbol.body:
        if isinstance(nodo, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "CAMPOS_MONETARIOS" for t in nodo.targets
        ):
            try:
                valor = nodo.value
                if isinstance(valor, ast.Call):  # frozenset({...})
                    valor = valor.args[0]
                return set(ast.literal_eval(valor))
            except Exception as e:
                print(f"[aviso] CAMPOS_MONETARIOS no es un literal: {e}")
    print("[aviso] No se encontró CAMPOS_MONETARIOS en server.py")
    return set()


def variantes_centinela(s):
    """Formatos en que un centinela puede aparecer: crudo, es-AR, en-US, sin separadores."""
    s = s.strip()
    out = {s}
    if not re.fullmatch(r"\d+(?:\.\d+)?", s):
        return {v for v in out if len(v) >= 5}
    n = float(s)
    ent, _, dec = f"{n:.2f}".partition(".")
    es_ent = f"{int(ent):,}".replace(",", ".")
    en_ent = f"{int(ent):,}"
    out |= {ent, es_ent, en_ent, f"{ent}.{dec}", f"{es_ent},{dec}", f"{en_ent}.{dec}"}
    if dec == "00":
        out |= {f"{ent}.0"}
    return {v for v in out if len(v) >= 5}  # evita falsos positivos con números cortos


def recortar(texto, i, ancho=45):
    a, b = max(0, i - ancho), min(len(texto), i + ancho)
    return texto[a:b].replace("\n", " ").strip()


def buscar_todos(texto, patron):
    return [(m.start(), m.group(0)) for m in patron.finditer(texto)]


# JS que corre en la página: devuelve un DOM "limpio" y listas para analizar.
JS_SNAPSHOT = """
(zonas) => {
  const exento = el => !!(el.closest && el.closest(zonas));
  const clon = document.documentElement.cloneNode(true);
  clon.querySelectorAll('script,style,noscript,template').forEach(n => n.remove());
  clon.querySelectorAll(zonas).forEach(n => n.remove());

  const cabeceras = [...document.querySelectorAll('th,label,legend')]
    .filter(el => !exento(el))
    .map(el => ({tag: el.tagName.toLowerCase(), id: el.id || '', texto: el.textContent.replace(/\\s+/g,' ').trim()}))
    .filter(x => x.texto);

  const hojas = [...document.body.querySelectorAll('*')]
    .filter(el => !exento(el) && !['SCRIPT','STYLE','TH','LABEL','LEGEND','OPTION'].includes(el.tagName)
                  && el.children.length === 0)
    .map(el => ({tag: el.tagName.toLowerCase(), id: el.id || '', texto: el.textContent.replace(/\\s+/g,' ').trim()}))
    .filter(x => x.texto && x.texto.length <= 80);

  const campos = [...document.querySelectorAll('input,select,textarea')]
    .filter(el => !exento(el))
    .map(el => ({
      tag: el.tagName.toLowerCase(), type: el.type || '', id: el.id || '', name: el.name || '',
      placeholder: el.getAttribute('placeholder') || '', aria: el.getAttribute('aria-label') || '',
      visible: !!(el.offsetParent !== null), tieneValor: !!(el.value && String(el.value).trim() !== '')
    }));

  const atributos = [];
  document.querySelectorAll('*').forEach(el => {
    if (exento(el)) return;
    for (const a of el.attributes) {
      if (/^data-/i.test(a.name)) atributos.push({tag: el.tagName.toLowerCase(), id: el.id || '', nombre: a.name, valor: a.value});
    }
  });

  return {
    html: clon.outerHTML,
    cabeceras, hojas, campos, atributos,
  };
}
"""


class Hallazgos:
    """Agrupa por (categoría, detalle): el DOM estático (modales, formularios) está en
    todos los módulos a la vez, y repetir el mismo hallazgo 28 veces tapa lo importante."""

    def __init__(self):
        self.fallos = {}   # (cat, detalle) -> [módulos]
        self.avisos = {}
        self.total_modulos = 0

    def _add(self, d, modulo, cat, detalle):
        mods = d.setdefault((cat, detalle), [])
        if modulo not in mods:
            mods.append(modulo)

    def fallo(self, modulo, cat, detalle):
        self._add(self.fallos, modulo, cat, detalle)

    def aviso(self, modulo, cat, detalle):
        self._add(self.avisos, modulo, cat, detalle)


def claves_json(obj, prohibidas, ruta=""):
    """Recorre un JSON y devuelve las rutas de claves monetarias presentes."""
    hall = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in prohibidas:
                hall.append(f"{ruta}.{k}" if ruta else k)
            hall += claves_json(v, prohibidas, f"{ruta}.{k}" if ruta else k)
    elif isinstance(obj, list):
        for v in obj[:200]:  # alcanza con una muestra grande; evita listas gigantes
            hall += claves_json(v, prohibidas, f"{ruta}[]")
    return hall


def login(playwright, base_url, usuario, clave, headed):
    try:
        browser = playwright.chromium.launch(headless=not headed)
    except PWError as e:
        raise ErrorEntorno("No se pudo abrir Chromium (" + str(e).splitlines()[0] + "). "
                           "Ejecutá: playwright install chromium")
    ctx = browser.new_context(ignore_https_errors=True, viewport={"width": 1500, "height": 950})
    try:
        r = ctx.request.post(f"{base_url}/login", data=json.dumps({"username": usuario, "password": clave}),
                             headers={"Content-Type": "application/json"})
    except PWError as e:
        browser.close()
        raise ErrorEntorno(f"No se pudo conectar a {base_url} ({str(e).splitlines()[0]}). "
                           f"¿Está levantado el servidor? Usá --base-url si no corre en ese puerto.")
    if r.status != 200:
        browser.close()
        raise ErrorEntorno(f"Login de '{usuario}' falló (HTTP {r.status}). ¿Usuario/clave/servidor correctos?")
    return browser, ctx


def recorrer(playwright, base_url, usuario, clave, centinelas, prohibidas, headed, settle_ms, estricto_texto,
             etiqueta):
    """Recorre todos los módulos visibles. Devuelve (Hallazgos, dict centinelas_vistos)."""
    H = Hallazgos()
    vistos = {}  # centinela -> módulos donde apareció (sirve para el control)
    browser, ctx = login(playwright, base_url, usuario, clave, headed)
    page = ctx.new_page()

    respuestas = []  # (url, cuerpo_texto, status)

    def on_response(resp):
        try:
            if "/api/" in resp.url and "application/json" in (resp.headers.get("content-type") or ""):
                respuestas.append((resp.url, resp.text(), resp.status))
        except Exception:
            pass  # redirecciones/respuestas sin cuerpo

    page.on("response", on_response)
    errores_js = []
    page.on("pageerror", lambda e: errores_js.append(str(e)))

    try:
        page.goto(f"{base_url}/", wait_until="load", timeout=30000)
        try:  # si la app hace polling la red nunca queda en reposo: no es un error
            page.wait_for_load_state("networkidle", timeout=10000)
        except PWError:
            pass
        page.wait_for_selector(".ni[data-p]", state="attached", timeout=15000)
    except PWError as e:
        browser.close()
        raise ErrorEntorno(f"La página principal no cargó el menú (.ni[data-p]) para '{usuario}': "
                           f"{str(e).splitlines()[0]}. ¿La sesión expiró o el servidor devolvió un error?")

    # 6) módulos que no deben existir
    if etiqueta == "restringido":
        for p in MODULOS_PROHIBIDOS:
            if page.query_selector(f'.ni[data-p="{p}"]') or page.query_selector(f"#p-{p}"):
                H.fallo(p, "módulo prohibido", f"'{p}' sigue en el menú o en el DOM para un usuario restringido")

    modulos = page.evaluate(
        """() => [...document.querySelectorAll('.ni[data-p]')]
              .filter(n => n.offsetParent !== null && n.style.display !== 'none')
              .map(n => n.dataset.p)"""
    )
    if not modulos:
        browser.close()
        raise ErrorEntorno("No se encontró ningún módulo visible en el menú.")
    H.total_modulos = len(modulos)
    print(f"[{etiqueta}] {len(modulos)} módulos visibles: {', '.join(modulos)}")

    for mod in modulos:
        desde = len(respuestas)
        try:
            page.click(f'.ni[data-p="{mod}"]', timeout=5000)
        except PWError:
            # grupo colapsado u overlay: se dispara el mismo handler por JS
            page.evaluate("(p)=>document.querySelector('.ni[data-p=\"'+p+'\"]').click()", mod)
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except PWError:
            H.aviso(mod, "carga", "la red no quedó en reposo en 15 s; se analiza igual")
        # El front limpia con un MutationObserver (setTimeout 0): se deja asentar.
        page.wait_for_timeout(settle_ms)

        fuente = page.content()                      # HTML completo, scripts incluidos
        snap = page.evaluate(JS_SNAPSHOT, ZONAS_EXENTAS)
        dom, nuevas = snap["html"], respuestas[desde:]

        # 1) centinelas ------------------------------------------------------
        for c, variantes in centinelas.items():
            for v in variantes:
                where = []
                if v in fuente:
                    where.append("HTML fuente")
                if v in dom:
                    where.append("DOM")
                if any(v in cuerpo for _, cuerpo, _ in nuevas):
                    where.append("respuesta /api/")
                if where:
                    vistos.setdefault(c, set()).add(mod)
                    H.fallo(mod, "centinela", f"{c} (como '{v}') visible en: {', '.join(where)}")
                    break

        # 2) $ + dígito ------------------------------------------------------
        for patron in (RE_DOLAR_DIGITO, RE_MONEDA_DIGITO):
            for i, m in buscar_todos(dom, patron)[:5]:
                H.fallo(mod, "$ + dígito", f"'{m}' → …{recortar(dom, i)}…")

        # 3) encabezados / etiquetas / textos ---------------------------------
        for x in snap["cabeceras"]:
            if RE_TERMINO.search(x["texto"]) and not RE_PERMITIDO.search(x["texto"]):
                H.fallo(mod, "encabezado/etiqueta", f"<{x['tag']}{'#'+x['id'] if x['id'] else ''}> '{x['texto'][:70]}'")
        for x in snap["hojas"]:
            if RE_TERMINO.search(x["texto"]) and not RE_PERMITIDO.search(x["texto"]):
                es_etiqueta = x["texto"].rstrip().endswith(":")
                (H.fallo if (estricto_texto or es_etiqueta) else H.aviso)(
                    mod, "etiqueta suelta" if es_etiqueta else "texto con término monetario",
                    f"<{x['tag']}{'#'+x['id'] if x['id'] else ''}> '{x['texto'][:70]}'")

        # 4) inputs monetarios (visibles u ocultos) y atributos data-* -----------
        for c in snap["campos"]:
            ident = " ".join([c["id"], c["name"], c["placeholder"], c["aria"]])
            if c["id"] in IDS_PERMITIDOS:
                continue
            if RE_NOMBRE_CAMPO.search(ident) and not RE_NOMBRE_CAMPO_PERMITIDO.search(ident):
                estado = "visible" if c["visible"] else "OCULTO (sigue en el DOM)"
                con_valor = " con valor" if c["tieneValor"] else ""
                H.fallo(mod, "input monetario",
                        f"<{c['tag']} id='{c['id']}' name='{c['name']}'> {estado}{con_valor}")
        for a in snap["atributos"]:
            if RE_ATRIBUTO_DATA.match(a["nombre"]):
                H.fallo(mod, "atributo data-* monetario",
                        f"<{a['tag']}{'#'+a['id'] if a['id'] else ''} {a['nombre']}='{a['valor'][:30]}'>")

        # 5) claves monetarias en el JSON recibido ----------------------------
        if prohibidas:
            for url, cuerpo, status in nuevas:
                try:
                    datos = json.loads(cuerpo)
                except ValueError:
                    continue
                rutas = sorted(set(claves_json(datos, prohibidas)))
                if rutas:
                    H.fallo(mod, "clave monetaria en API",
                            f"{url.replace(base_url, '')} → {', '.join(rutas[:6])}")

    for e in errores_js:
        H.aviso("(global)", "error JS", e[:160])
    browser.close()
    return H, vistos


def _donde(mods, total):
    if total and len(mods) >= total:
        return f"en todos los módulos ({total})"
    corto = ", ".join(mods[:4]) + (f" y {len(mods) - 4} más" if len(mods) > 4 else "")
    return f"en: {corto}"


def imprimir(H, titulo):
    print(f"\n── {titulo} " + "─" * max(0, 60 - len(titulo)))
    for (cat, det), mods in H.fallos.items():
        print(f"  FALLO  {cat}: {det}\n         {_donde(mods, H.total_modulos)}")
    for (cat, det), mods in H.avisos.items():
        print(f"  aviso  {cat}: {det}  ({_donde(mods, H.total_modulos)})")
    if not H.fallos:
        print("  sin fallos")


def main():
    ap = argparse.ArgumentParser(description="E2E: usuario restringido no debe ver importes")
    ap.add_argument("--base-url", default=os.environ.get("E2E_BASE_URL", "http://127.0.0.1:5000"))
    ap.add_argument("--user", default=os.environ.get("E2E_USER"))
    ap.add_argument("--password", default=os.environ.get("E2E_PASS"))
    ap.add_argument("--sentinels", default=os.environ.get("E2E_SENTINELS", ""),
                    help="valores centinela sembrados en la base, separados por coma (ej. 7777777.77,8888888.88)")
    ap.add_argument("--control-user", default=os.environ.get("E2E_CONTROL_USER"))
    ap.add_argument("--control-password", default=os.environ.get("E2E_CONTROL_PASS"))
    ap.add_argument("--strict-text", action="store_true", default=os.environ.get("E2E_STRICT_TEXT") == "1",
                    help="los textos sueltos con términos monetarios también fallan (por defecto: aviso)")
    ap.add_argument("--settle-ms", type=int, default=int(os.environ.get("E2E_SETTLE_MS", "600")))
    ap.add_argument("--server-py", default=os.environ.get("E2E_SERVER_PY"),
                    help="ruta a server.py (por defecto se busca junto al proyecto)")
    ap.add_argument("--headed", action="store_true")
    a = ap.parse_args()

    if not (a.user and a.password):
        print("[error] Falta usuario restringido: E2E_USER/E2E_PASS (o --user/--password).")
        return 2

    base = a.base_url.rstrip("/")
    centinelas = {c.strip(): variantes_centinela(c) for c in a.sentinels.split(",") if c.strip()}
    if not centinelas:
        print("[AVISO] Sin centinelas (E2E_SENTINELS): se saltea el chequeo 1 y NO hay garantía de que un\n"
              "        importe real sea detectado por valor. Solo corren los chequeos estructurales.")
    prohibidas = campos_monetarios_desde_server(buscar_server_py(a.server_py))
    print(f"CAMPOS_MONETARIOS leídos de server.py: {len(prohibidas)}")

    try:
        return _ejecutar(a, base, centinelas, prohibidas)
    except ErrorEntorno as e:
        print(f"[error] {e}")
        return 2


def _ejecutar(a, base, centinelas, prohibidas):
    with sync_playwright() as pw:
        H, _ = recorrer(pw, base, a.user, a.password, centinelas, prohibidas, a.headed,
                        a.settle_ms, a.strict_text, "restringido")
        imprimir(H, f"Usuario restringido ({a.user})")

        control_ok = True
        if a.control_user and a.control_password and centinelas:
            Hc, vistos = recorrer(pw, base, a.control_user, a.control_password, centinelas, set(), a.headed,
                                  a.settle_ms, False, "control")
            ciegos = [c for c in centinelas if c not in vistos]
            print(f"\n── Control ({a.control_user}) " + "─" * 40)
            for c in centinelas:
                if c in vistos:
                    print(f"  ok     {c} visible en: {', '.join(sorted(vistos[c]))}")
            for c in ciegos:
                print(f"  FALLO  {c} NO se ve ni con el usuario con permiso: centinela mal sembrado "
                      f"o detector ciego; el verde del restringido no vale para este valor")
            control_ok = not ciegos
        elif centinelas:
            print("\n[aviso] Sin usuario de control (E2E_CONTROL_USER/PASS): no se valida que los centinelas "
                  "sean visibles para quien sí tiene permiso.")

    ok = not H.fallos and control_ok
    print("\nRESULTADO:", "OK" if ok else "FALLÓ")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
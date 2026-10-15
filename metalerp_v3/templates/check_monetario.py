#!/usr/bin/env python3
"""
check_monetario.py — lint del permiso "ver valores monetarios".

Falla (exit 1) si app.html renderiza algo monetario sin pasar por las
herramientas que lo eliminan para el usuario restringido:

  Regla A  Un campo de CAMPOS_MONETARIOS (el set de server.py) leído como
           propiedad (r.precio_unit, r['costo_mat']) fuera de fmtM / fmtMD /
           monOnly / thM / tdM / un bloque o ternario bajo VER_MONETARIO.

  Regla B  Las palabras Precio / Costo / Monto / Importe / Subtotal en un
           texto que se renderiza (HTML estático o string/template de JS)
           fuera de monOnly / thM / tdM / VER_MONETARIO / data-monetario.

Uso:
    python scripts/check_monetario.py                 # busca templates/app.html
    python scripts/check_monetario.py --html RUTA --server RUTA
    python scripts/check_monetario.py --selftest      # prueba el propio lint

Sólo usa la librería estándar. No importa server.py (lee CAMPOS_MONETARIOS con
ast), así que no toca la base ni arranca nada.

LÍMITES (es un lint, no un intérprete de JS):
  · El "guardado" se decide por estructura léxica: paréntesis de una guarda,
    llave de un `if(VER_MONETARIO){`, ternario/&& dentro del mismo paréntesis o
    template, o cualquier línea que contenga VER_MONETARIO sin negar.
  · Un `if(!VER_MONETARIO) return;` al principio de una función NO se entiende:
    ahí hay que anotar la línea con `monetario-ok: motivo` o agregarla a la
    ALLOWLIST de abajo.
  · Las claves de objeto ({precio: x}) no se consideran lectura: lo que el
    cliente manda lo descarta el servidor (before_request).
"""
import argparse
import ast
import bisect
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

# ── Qué cuenta como "pasar por" el filtro ────────────────────────────────────
GUARDAS = {"monOnly", "thM", "tdM", "fmtM", "fmtMD"}
ATRIBUTO_HTML = "data-monetario"
MARCA_LINEA = "monetario-ok"          # comentario en la línea: `/* monetario-ok: motivo */`

# Zonas donde se HABLA de los campos monetarios en vez de mostrar importes.
# Espejo de _zonaExentaMonetario() en app.html: si cambia allá, cambia acá.
ZONAS_EXENTAS = {"p-auditoria", "mo-auditoria", "p-usuarios", "mo-permisos", "mo-rol"}

# Palabras de la regla B. En texto plano sólo cuentan con mayúscula inicial o en
# MAYÚSCULAS ("Precio", "COSTO"); en un fragmento HTML (el string contiene '<')
# cuentan en cualquier caso. "Centro de costo" no es un importe.
_STEMS = "Precio|Costo|Monto|Importe|Subtotal"
RE_PALABRA = re.compile(
    r"(?<!centro de )(?<!Centro de )\b(?:%s|%s)(?:s|es|S|ES)?\b" % (_STEMS, _STEMS.upper())
)
RE_PALABRA_HTML = re.compile(
    r"(?<!centro de )\b(?:%s)(?:s|es)?\b" % _STEMS, re.I
)

# ── ALLOWLIST ────────────────────────────────────────────────────────────────
# Cada entrada: (regex que se busca en el TEXTO de la línea, motivo).
# El motivo es obligatorio: si no se puede explicar en una línea, probablemente
# no debería estar acá. Las entradas que ya no matchean nada se avisan al final
# (con --estricto-allowlist hacen fallar el lint, para que no se pudra).
ALLOWLIST = [
    # (r"patrón", "por qué esto no es un importe visible para el restringido"),
]


# ── Lectura de CAMPOS_MONETARIOS ─────────────────────────────────────────────
def cargar_campos(ruta_server):
    arbol = ast.parse(Path(ruta_server).read_text(encoding="utf-8"))
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "CAMPOS_MONETARIOS" for t in nodo.targets
        ):
            consts = [
                n.value for n in ast.walk(nodo.value)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)
            ]
            if consts:
                return frozenset(consts)
    raise SystemExit("No encontré CAMPOS_MONETARIOS en %s" % ruta_server)


# ── Preprocesado de la plantilla Jinja (conserva largo y saltos de línea) ────
def neutralizar_jinja(t):
    def expr(m):
        s = m.group(0)
        return "0" + re.sub(r"[^\n]", " ", s[1:])          # {{ x|tojson }} -> 0
    t = re.sub(r"\{\{.*?\}\}", expr, t, flags=re.S)
    t = re.sub(r"\{%.*?%\}|\{#.*?#\}", lambda m: re.sub(r"[^\n]", " ", m.group(0)), t, flags=re.S)
    return t


# ── Escáner de JavaScript ────────────────────────────────────────────────────
_PREV_INICIA_REGEX = set("(,=:[!&|?{;+-*%<>~^") | {"", "return", "typeof", "case", "in", "of", "else", "do"}
_KW = {"return", "typeof", "case", "in", "of", "else", "do"}


def escanear_js(src, base, campos, emit):
    """Recorre `src` (JS) y llama emit(offset_absoluto, tipo, dato, guardado).
       tipo = 'campo' (dato = nombre) | 'texto' (dato = contenido de string/template)."""
    n = len(src)
    i = 0
    pila = []              # {"k": "(" | "{" | "[" | "tpl", "g": bool, "ver": bool, "if": bool}
    prev = ""
    ult = ""               # último identificador (válido si prev == "ident")
    pend_llave = False
    en_tpl = False

    def guardado():
        return any(f["g"] for f in pila)

    def cerrar(k):
        for idx in range(len(pila) - 1, -1, -1):
            if pila[idx]["k"] == k:
                f = pila[idx]
                del pila[idx:]
                return f
        return None

    while i < n:
        if en_tpl:
            j = i
            while j < n:
                c = src[j]
                if c == "\\":
                    j += 2
                    continue
                if c == "`" or (c == "$" and j + 1 < n and src[j + 1] == "{"):
                    break
                j += 1
            if j > i:
                emit(base + i, "texto", src[i:j], guardado())
            if j >= n:
                return
            if src[j] == "`":
                en_tpl = False
                i = j + 1
                prev, ult = "str", ""
            else:
                pila.append({"k": "tpl", "g": False, "ver": False, "if": False})
                en_tpl = False
                i = j + 2
                prev, ult = "{", ""
            continue

        c = src[i]
        if c in " \t\r\n":
            i += 1
            continue
        if src.startswith("//", i):
            j = src.find("\n", i)
            i = n if j < 0 else j
            continue
        if src.startswith("/*", i):
            j = src.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        if c != "{":
            pend_llave = False

        if c in "'\"":
            j = i + 1
            while j < n and src[j] != c and src[j] != "\n":
                j += 2 if src[j] == "\\" else 1
            contenido = src[i + 1:j]
            if prev == "[" and contenido in campos and src[j + 1:j + 2] == "]":
                emit(base + i, "campo", contenido, guardado())
            emit(base + i + 1, "texto", contenido, guardado())
            i = j + 1
            prev, ult = "str", ""
            continue
        if c == "`":
            en_tpl = True
            i += 1
            continue
        if c == "/":
            if prev in _PREV_INICIA_REGEX:
                j = i + 1
                en_clase = False
                while j < n:
                    ch = src[j]
                    if ch == "\\":
                        j += 2
                        continue
                    if ch == "[":
                        en_clase = True
                    elif ch == "]":
                        en_clase = False
                    elif ch == "/" and not en_clase:
                        break
                    elif ch == "\n":
                        break
                    j += 1
                j += 1
                while j < n and src[j].isalpha():
                    j += 1
                i = j
                prev, ult = "str", ""
            else:
                i += 1
                prev = "/"
            continue
        if c.isalpha() or c in "_$":
            m = re.compile(r"[\w$]+").match(src, i)
            nombre = m.group(0)
            if nombre == "VER_MONETARIO" and prev != "!":
                if pila:
                    pila[-1]["g"] = True
                    pila[-1]["ver"] = True
            elif prev == "." and nombre in campos:
                emit(base + i, "campo", nombre, guardado())
            i = m.end()
            prev = nombre if nombre in _KW else "ident"
            ult = nombre
            continue
        if c.isdigit():
            m = re.compile(r"[\w.]+").match(src, i)
            i = m.end()
            prev, ult = "num", ""
            continue
        if c == "(":
            pila.append({"k": "(", "g": prev == "ident" and ult in GUARDAS, "ver": False,
                         "if": prev == "ident" and ult == "if"})
            i += 1
            prev, ult = "(", ""
            continue
        if c == ")":
            f = cerrar("(")
            pend_llave = bool(f and f["if"] and f["ver"])
            i += 1
            prev, ult = ")", ""
            continue
        if c == "{":
            pila.append({"k": "{", "g": pend_llave, "ver": False, "if": False})
            pend_llave = False
            i += 1
            prev, ult = "{", ""
            continue
        if c == "}":
            if pila and pila[-1]["k"] == "tpl":
                pila.pop()
                en_tpl = True
                i += 1
                continue
            cerrar("{")
            i += 1
            prev, ult = "}", ""
            continue
        if c == "[":
            pila.append({"k": "[", "g": False, "ver": False, "if": False})
            i += 1
            prev, ult = "[", ""
            continue
        if c == "]":
            cerrar("[")
            i += 1
            prev, ult = "]", ""
            continue
        if src.startswith("...", i):
            i += 3
            prev, ult = "spread", ""
            continue
        i += 1
        prev, ult = c, ""


# ── Escáner de HTML estático ─────────────────────────────────────────────────
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
         "param", "source", "track", "wbr"}
_ATTRS_TEXTO = ("title", "placeholder", "aria-label", "alt", "label", "value")


class _EscanerHTML(HTMLParser):
    def __init__(self, inicios_linea, on_js, on_texto):
        super().__init__(convert_charrefs=True)
        self.inicios = inicios_linea
        self.on_js = on_js
        self.on_texto = on_texto
        self.pila = []                 # (tag, ok)
        self.en_script = False
        self.en_style = False

    def _offset(self):
        linea, col = self.getpos()
        return self.inicios[linea - 1] + col

    def _ok(self):
        return self.pila[-1][1] if self.pila else False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        ok = self._ok() or ATRIBUTO_HTML in a or (a.get("id") in ZONAS_EXENTAS)
        if not ok:
            for k in _ATTRS_TEXTO:
                if a.get(k):
                    self.on_texto(self._offset(), a[k])
        if tag == "script":
            self.en_script = True
        elif tag == "style":
            self.en_style = True
        if tag not in _VOID:
            self.pila.append((tag, ok))

    def handle_startendtag(self, tag, attrs):
        n = len(self.pila)
        self.handle_starttag(tag, attrs)
        del self.pila[n:]

    def handle_endtag(self, tag):
        if tag == "script":
            self.en_script = False
        elif tag == "style":
            self.en_style = False
        for idx in range(len(self.pila) - 1, -1, -1):
            if self.pila[idx][0] == tag:
                del self.pila[idx:]
                return

    def handle_data(self, data):
        if self.en_style:
            return
        if self.en_script:
            self.on_js(self._offset(), data)
        elif not self._ok() and data.strip():
            self.on_texto(self._offset(), data)


# ── Análisis ─────────────────────────────────────────────────────────────────
def analizar(texto_original, campos):
    """Devuelve lista de (línea, regla, mensaje)."""
    texto = neutralizar_jinja(texto_original)
    inicios = [0]
    for m in re.finditer(r"\n", texto):
        inicios.append(m.end())
    lineas = texto_original.split("\n")
    hallazgos = []

    def linea_de(off):
        return bisect.bisect_right(inicios, off)

    def linea_guardada(nro):
        t = lineas[nro - 1]
        return bool(re.search(r"(?<!!)\bVER_MONETARIO\b", t)) or MARCA_LINEA in t

    def agregar(off, regla, msg):
        hallazgos.append((linea_de(off), regla, msg))

    def palabras(off, contenido, es_html):
        rx = RE_PALABRA_HTML if (es_html or "<" in contenido) else RE_PALABRA
        for m in rx.finditer(contenido):
            agregar(off + m.start(), "B",
                    "texto monetario «%s» fuera de monOnly/thM/tdM/data-monetario" % m.group(0))

    def on_texto_estatico(off, contenido):
        for m in RE_PALABRA.finditer(contenido):
            agregar(off + m.start(), "B",
                    "«%s» en HTML estático sin data-monetario" % m.group(0))

    def emit(off, tipo, dato, guardado):
        if guardado:
            return
        if tipo == "campo":
            agregar(off, "A", "campo monetario «%s» leído fuera de fmtM/fmtMD/monOnly/thM/tdM/VER_MONETARIO" % dato)
        else:
            palabras(off, dato, False)

    def on_js(off, src):
        escanear_js(src, off, campos, emit)

    esc = _EscanerHTML(inicios, on_js, on_texto_estatico)
    esc.feed(texto)
    esc.close()

    # La guarda por línea (VER_MONETARIO / monetario-ok) se aplica al final:
    # cubre lo que el análisis estructural no alcanza (ver LÍMITES).
    unicos = set()
    salida = []
    for lin, regla, msg in sorted(hallazgos):
        if linea_guardada(lin):
            continue
        if (lin, msg) in unicos:
            continue
        unicos.add((lin, msg))
        salida.append((lin, regla, msg))
    return salida


def aplicar_allowlist(hallazgos, lineas):
    usadas = [0] * len(ALLOWLIST)
    reglas = [(re.compile(p), m) for p, m in ALLOWLIST]
    quedan, permitidos = [], []
    for lin, regla, msg in hallazgos:
        t = lineas[lin - 1]
        for idx, (rx, motivo) in enumerate(reglas):
            if rx.search(t):
                usadas[idx] += 1
                permitidos.append((lin, regla, msg, motivo))
                break
        else:
            quedan.append((lin, regla, msg))
    sin_uso = [ALLOWLIST[i][0] for i, u in enumerate(usadas) if u == 0]
    return quedan, permitidos, sin_uso


# ── Autoprueba ───────────────────────────────────────────────────────────────
def _selftest():
    campos = frozenset({"precio_unit", "costo_mat"})
    def n(html):
        return [(r, m.split("«")[1].split("»")[0] if "«" in m else m) for _, r, m in analizar(html, campos)]
    casos = [
        # (html, cantidad de hallazgos esperados)
        ("<script>h+=fmtM(r.precio_unit);</script>", 0),
        ("<script>h+=r.precio_unit;</script>", 1),
        ("<script>h+=(r.costo_mat||0).toFixed(2);</script>", 1),
        ("<script>h+=monOnly('<td>Precio</td>'+fmtM(r.precio_unit));</script>", 0),
        ("<script>h+='<th>Precio</th>';</script>", 1),
        ("<script>h+=thM('Precio');</script>", 0),
        ("<script>x=VER_MONETARIO?'<b>Costo</b>':'';</script>", 0),
        ("<script>if(VER_MONETARIO){\n h+='<th>Costo</th>';\n}\nh+='<th>Costo</th>';</script>", 1),
        ("<script>if(!VER_MONETARIO){\n h+='<th>Costo</th>';\n}</script>", 1),
        ("<script>x=`<td>${fmtM(r.costo_mat)}</td>`;</script>", 0),
        ("<script>x=`<td>${r.costo_mat}</td>`;</script>", 1),
        ("<script>x=r['precio_unit'];</script>", 1),
        ("<script>x=/\\d+/.test(s); y=a/b; z=thM('Costo');</script>", 0),
        ("<script>x={precio_unit:1};</script>", 0),
        ("<script>$('prod-costo').value=1; alert('el costo no puede ser negativo');</script>", 0),
        ("<script>h+='Centro de costo';</script>", 0),
        ("<script>h+='<td>Precio</td>'; // otra cosa\nx=1; // monetario-ok: está en otra línea\n</script>", 1),
        ("<script>h+='<td>Precio</td>'; /* monetario-ok: prueba */</script>", 0),
        ("<th>Precio</th>", 1),
        ("<th data-monetario>Precio</th>", 0),
        ("<div data-monetario><p>Monto</p></div>", 0),
        ("<div id='p-usuarios'><label>Precio</label></div>", 0),
        ("<input placeholder='Precio unitario'>", 1),
        ("<script>const P={{ perms|tojson }}; h+=thM('Precio');</script>", 0),
    ]
    mal = 0
    for html, esperado in casos:
        got = len(n(html))
        if got != esperado:
            mal += 1
            print("FALLA selftest: esperaba %d, obtuve %d en: %s" % (esperado, got, html))
    print("selftest: %d casos, %d fallas" % (len(casos), mal))
    return 1 if mal else 0


# ── CLI ──────────────────────────────────────────────────────────────────────
def _primero(candidatos):
    for c in candidatos:
        if c.exists():
            return c
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--html", help="ruta de app.html (default: templates/app.html o app.html)")
    ap.add_argument("--server", help="ruta de server.py (default: server.py)")
    ap.add_argument("--mostrar-permitidos", action="store_true")
    ap.add_argument("--estricto-allowlist", action="store_true",
                    help="falla si hay entradas de la ALLOWLIST que ya no matchean nada")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)

    if a.selftest:
        return _selftest()

    ruta_html = Path(a.html) if a.html else _primero([RAIZ / "templates" / "app.html", RAIZ / "app.html"])
    ruta_srv = Path(a.server) if a.server else _primero([RAIZ / "server.py"])
    if not ruta_html or not ruta_html.exists():
        print("No encuentro app.html (usá --html)", file=sys.stderr)
        return 2
    if not ruta_srv or not ruta_srv.exists():
        print("No encuentro server.py (usá --server)", file=sys.stderr)
        return 2

    campos = cargar_campos(ruta_srv)
    texto = ruta_html.read_text(encoding="utf-8")
    lineas = texto.split("\n")
    hallazgos = analizar(texto, campos)
    quedan, permitidos, sin_uso = aplicar_allowlist(hallazgos, lineas)

    for lin, regla, msg in quedan:
        print("%s:%d: [%s] %s" % (ruta_html.name, lin, regla, msg))
        print("    " + lineas[lin - 1].strip()[:160])
    if a.mostrar_permitidos:
        for lin, regla, msg, motivo in permitidos:
            print("permitido %s:%d [%s] %s  (%s)" % (ruta_html.name, lin, regla, msg, motivo))
    for p in sin_uso:
        print("aviso: la entrada de ALLOWLIST %r ya no matchea nada; se puede borrar" % p)

    print("\n%d campos monetarios vigilados · %d hallazgos · %d permitidos"
          % (len(campos), len(quedan), len(permitidos)))
    if quedan:
        print("Cada hallazgo se arregla con monOnly/thM/tdM/fmtM/data-monetario, "
              "o (si de verdad no es un importe) con `monetario-ok: motivo` en la línea / ALLOWLIST.")
        return 1
    if sin_uso and a.estricto_allowlist:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
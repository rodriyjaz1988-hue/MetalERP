"""Ayudas para programas CNC Fanuc (texto): número O, formato y comparación."""
import re


class ErrorPrograma(Exception):
    pass


def nombre_o(numero):
    return ("O%04d" % numero) if numero < 10000 else ("O%08d" % numero)


def numero_en_texto(texto):
    m = re.search(r"^\s*%?\s*O(\d{1,8})", texto.replace("\r", ""), re.M)
    return int(m.group(1)) if m else None


def comentario(texto):
    for ln in texto.replace("\r", "").split("\n"):
        if re.match(r"^\s*O\d+", ln):
            m = re.search(r"\(([^)]*)\)", ln)
            return m.group(1).strip() if m else ""
    return ""


def preparar(texto, numero):
    """Archivo listo para el control: %, O<numero> (se conserva el comentario
    de la línea O), el código, y % al final. Saltos de línea CR LF, solo ASCII."""
    lineas = [l.rstrip() for l in texto.replace("\r", "").split("\n")]
    while lineas and lineas[0].strip() in ("", "%"):
        lineas.pop(0)
    while lineas and lineas[-1].strip() in ("", "%"):
        lineas.pop()
    if not lineas:
        raise ErrorPrograma("El archivo no tiene código")
    if any(l.strip() == "%" for l in lineas):
        raise ErrorPrograma("El archivo tiene más de un programa (hay un % en el medio). Mandá uno por vez.")
    m = re.match(r"^\s*O\d+\s*(.*)$", lineas[0])
    if m:
        lineas[0] = nombre_o(numero) + m.group(1)
    else:
        lineas.insert(0, nombre_o(numero))
    cuerpo = "\n".join(lineas)
    malos = sorted({c for c in cuerpo if ord(c) > 126 or (ord(c) < 32 and c not in "\n\t")})
    if malos:
        raise ErrorPrograma("El programa tiene caracteres que el control no acepta: "
                            + " ".join(repr(c) for c in malos[:10]))
    return ("%\n" + cuerpo + "\n%\n").replace("\n", "\r\n")


def normalizar(texto):
    """Líneas sin espacios ni %, para comparar lo del archivo con lo del control."""
    lineas = [re.sub(r"\s+", "", l) for l in texto.replace("\r", "").split("\n")]
    return [l for l in lineas if l and l != "%"]

"""
Recalcula rendimiento_pct (y desvio) de novedades_produccion ya cargadas,
usando el tiempo_ciclo_min ACTUAL de proceso_operaciones.

Caso que soluciona: se cargó una novedad cuando la operación todavía no
tenía tiempo_ciclo_min definido (el sistema usó el fallback de 1 min/pieza),
y después se cargó el ciclo real -> la novedad quedó con un rendimiento_pct
inflado/incorrecto (ej. 186.7% en vez del valor real).

Misma fórmula que usa el servidor en create_novedad / update_novedad:
    t_productivo = max(tiempo_real_min - tiempo_perdido, 0.1)
    rendimiento  = round((cantidad_producida / t_productivo) / (1 / std_ciclo) * 100, 1)
    desvio       = 1 if rendimiento < 80 else 0

Uso:
    python recalcular_rendimiento.py            -> dry-run, solo muestra qué cambiaría
    python recalcular_rendimiento.py --aplicar   -> aplica los cambios en la base
    python recalcular_rendimiento.py --ot OT-019 -> limita a una OT puntual (opcional, combinable con --aplicar)
"""
import sqlite3
import os
import sys
import shutil
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "database", "metalerp.db")


def main():
    aplicar = "--aplicar" in sys.argv
    ot_filtro = None
    if "--ot" in sys.argv:
        idx = sys.argv.index("--ot")
        if idx + 1 < len(sys.argv):
            ot_filtro = sys.argv[idx + 1]

    if not os.path.exists(DB_PATH):
        print(f"ERROR: no se encontró la base en {DB_PATH}")
        sys.exit(1)

    if aplicar:
        backup_path = DB_PATH + f".bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        shutil.copy2(DB_PATH, backup_path)
        print(f"Backup creado en: {backup_path}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    sql = """
        SELECT n.id, n.numero, n.cantidad_producida, n.tiempo_real_min,
               n.tiempo_perdido, n.rendimiento_pct, n.desvio,
               oo.orden_id, oo.nombre op_nombre,
               po.tiempo_ciclo_min std_ciclo,
               o.numero ot_numero
        FROM novedades_produccion n
        JOIN orden_operaciones oo ON oo.id = n.orden_operacion_id
        LEFT JOIN proceso_operaciones po ON po.id = oo.proceso_op_id
        JOIN ordenes o ON o.id = oo.orden_id
    """
    params = []
    if ot_filtro:
        sql += " WHERE o.numero = ?"
        params.append(ot_filtro)
    sql += " ORDER BY n.id"

    rows = cur.execute(sql, params).fetchall()

    if not rows:
        print("No se encontraron novedades para procesar.")
        return

    cambios = []
    sin_ciclo = []

    for r in rows:
        std_ciclo = r["std_ciclo"] or 0
        if not std_ciclo:
            # Operación sigue sin ciclo estándar definido: no se puede
            # recalcular correctamente, se deja como está (usaría el mismo
            # fallback de 1 min/pieza que ya tiene guardado).
            sin_ciclo.append(r)
            continue

        qty = float(r["cantidad_producida"] or 0)
        t_real = float(r["tiempo_real_min"] or 0)
        t_perdido = float(r["tiempo_perdido"] or 0)
        t_productivo = max(t_real - t_perdido, 0.1)

        nuevo_rend = round((qty / t_productivo) / (1 / std_ciclo) * 100, 1)
        nuevo_desvio = 1 if nuevo_rend < 80 else 0

        rend_actual = float(r["rendimiento_pct"] or 0)

        if abs(nuevo_rend - rend_actual) > 0.05 or nuevo_desvio != r["desvio"]:
            cambios.append((r, nuevo_rend, nuevo_desvio, std_ciclo))

    print(f"Novedades analizadas: {len(rows)}")
    print(f"Sin tiempo de ciclo definido (no se tocan): {len(sin_ciclo)}")
    print(f"Novedades a corregir: {len(cambios)}")
    print("-" * 90)

    for r, nuevo_rend, nuevo_desvio, std_ciclo in cambios:
        print(f"{r['numero']:<14} OT {r['ot_numero']:<10} {r['op_nombre']:<20} "
              f"ciclo={std_ciclo}min  {r['rendimiento_pct']}% -> {nuevo_rend}%  "
              f"(desvio {r['desvio']} -> {nuevo_desvio})")

    if sin_ciclo:
        print("-" * 90)
        print("Sin ciclo estándar definido todavía (revisar manualmente si corresponde):")
        for r in sin_ciclo:
            print(f"  {r['numero']:<14} OT {r['ot_numero']:<10} {r['op_nombre']}")

    if not aplicar:
        print("-" * 90)
        print("DRY-RUN: no se modificó nada. Corré con --aplicar para guardar los cambios.")
        return

    for r, nuevo_rend, nuevo_desvio, std_ciclo in cambios:
        cur.execute(
            "UPDATE novedades_produccion SET rendimiento_pct=?, desvio=? WHERE id=?",
            (nuevo_rend, nuevo_desvio, r["id"]),
        )

    conn.commit()
    conn.close()
    print("-" * 90)
    print(f"Listo. {len(cambios)} novedades actualizadas.")


if __name__ == "__main__":
    main()
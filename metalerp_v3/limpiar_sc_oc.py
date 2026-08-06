"""
Limpia los DATOS de Solicitudes de Compra (SC) y Órdenes de Compra (OC)
del módulo de Compras, sin borrar las tablas (la estructura queda intacta).

Uso:
    python limpiar_sc_oc.py
    python limpiar_sc_oc.py --db /ruta/a/metalerp.db
    python limpiar_sc_oc.py --sin-backup     (no recomendado)
"""
import argparse
import os
import shutil
import sqlite3
import sys
from datetime import datetime

# Ruta por defecto, igual a la que usa server.py (BASE_DIR/database/metalerp.db)
DEFAULT_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "database", "metalerp.db")

# Orden de borrado: primero las tablas "hijas" (tienen FK hacia las otras),
# después las "padres", para no romper las relaciones.
TABLAS_A_LIMPIAR = [
    "ordenes_compra_items",   # items de cada OC (FK -> ordenes_compra, solicitudes_compra)
    "cotizaciones_compra",    # cotizaciones recibidas por SC (FK -> solicitudes_compra)
    "ordenes_compra",         # órdenes de compra (OC)
    "solicitudes_compra",     # solicitudes de compra (SC)
]


def limpiar(db_path: str, hacer_backup: bool = True) -> None:
    if not os.path.isfile(db_path):
        print(f"No se encontró la base de datos en: {db_path}")
        sys.exit(1)

    if hacer_backup:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = f"{db_path}.backup_{stamp}"
        shutil.copy2(db_path, backup_path)
        print(f"Backup creado en: {backup_path}")

    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys = OFF")
    cur = con.cursor()

    try:
        for tabla in TABLAS_A_LIMPIAR:
            cur.execute(f"SELECT COUNT(*) FROM {tabla}")
            cantidad = cur.fetchone()[0]
            cur.execute(f"DELETE FROM {tabla}")
            print(f"  - {tabla}: {cantidad} filas borradas")
        con.commit()
        con.execute("PRAGMA foreign_keys = ON")
        con.execute("VACUUM")
        print("Listo. Datos de SC y OC eliminados (tablas intactas).")
    except sqlite3.Error as e:
        con.rollback()
        print(f"Error al limpiar la base: {e}")
        sys.exit(1)
    finally:
        con.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Limpia datos de SC y OC (módulo Compras)")
    parser.add_argument("--db", default=DEFAULT_DB, help="Ruta al archivo .db (default: database/metalerp.db)")
    parser.add_argument("--sin-backup", action="store_true", help="No crear backup antes de borrar (no recomendado)")
    args = parser.parse_args()

    print(f"Base de datos: {args.db}")
    respuesta = input("Esto borrará TODAS las Solicitudes de Compra y Órdenes de Compra. ¿Continuar? (s/N): ")
    if respuesta.strip().lower() != "s":
        print("Cancelado.")
        sys.exit(0)

    limpiar(args.db, hacer_backup=not args.sin_backup)
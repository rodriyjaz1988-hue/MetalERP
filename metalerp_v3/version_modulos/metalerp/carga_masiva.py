"""Carga masiva de datos desde planillas."""
from .nucleo import app, DB_PATH, execute, jsonify, login_required, query, request

# ── Cargas masivas ────────────────────────────────────────────────────────────
@app.route("/api/bulk/schema", methods=["GET"])
@login_required(roles=["admin"])
def get_bulk_schema():
    """Returns all tables with their columns (excluding system tables and PKs)."""
    import sqlite3 as _sq
    db2 = _sq.connect(DB_PATH)
    tables = db2.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT IN "
        "('sqlite_sequence') ORDER BY name").fetchall()
    result = {}
    for (tname,) in tables:
        cols = db2.execute(f"PRAGMA table_info({tname})").fetchall()
        # cid, name, type, notnull, default, pk
        result[tname] = [
            {"name": r[1], "type": r[2], "notnull": bool(r[3]),
             "default": r[4], "pk": bool(r[5])}
            for r in cols
        ]
    db2.close()
    return jsonify(result)

@app.route("/api/bulk/import", methods=["POST"])
@login_required(roles=["admin"])
def bulk_import():
    """Imports rows from JSON payload: {table: str, rows: list[dict], mode: 'insert'|'upsert'}"""
    d = request.json
    table  = d.get("table", "")
    rows   = d.get("rows", [])
    mode   = d.get("mode", "insert")   # insert = always insert, upsert = INSERT OR REPLACE

    if not table or not rows:
        return jsonify({"error": "table y rows requeridos"}), 400

    # Whitelist: only real tables
    import sqlite3 as _sq
    db2 = _sq.connect(DB_PATH)
    valid = {r[0] for r in db2.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    db2.close()

    if table not in valid:
        return jsonify({"error": f"Tabla '{table}' no existe"}), 400
    if table in ("usuarios", "sqlite_sequence"):
        return jsonify({"error": "Tabla protegida"}), 403

    # Get column names (skip 'id' for plain inserts unless provided)
    pragma = query(f"PRAGMA table_info({table})")
    col_meta = {r["name"]: r for r in pragma}

    inserted = 0
    errors = []
    # True upsert (update-in-place, keeps the existing id and doesn't cascade-delete
    # related rows like proceso_operaciones) when the table has a UNIQUE key we can
    # conflict on. Falls back to INSERT OR REPLACE only if no unique key is found.
    unique_col = None
    if mode == "upsert":
        idx_list = query(f"PRAGMA index_list({table})")
        for ix in idx_list:
            if ix["unique"]:
                ix_cols = query(f"PRAGMA index_info({ix['name']})")
                if len(ix_cols) == 1 and ix_cols[0]["name"] != "id":
                    unique_col = ix_cols[0]["name"]
                    break

    # Get FK info for this table to nullify invalid references
    import sqlite3 as _sq3
    _db_fk = _sq3.connect(DB_PATH)
    fk_info = _db_fk.execute(f"PRAGMA foreign_key_list({table})").fetchall()
    # fk_info: (id, seq, table, from, to, on_update, on_delete, match)
    fk_cols = {row[3]: (row[2], row[4]) for row in fk_info}  # {col: (ref_table, ref_col)}
    _db_fk.close()

    for i, row in enumerate(rows):
        # Only keep columns that exist in the table
        valid_row = {k: v for k, v in row.items() if k in col_meta}
        # Remove 'id' for plain inserts (let autoincrement handle it)
        if mode == "insert" and "id" in valid_row:
            del valid_row["id"]
        if not valid_row:
            errors.append(f"Fila {i+1}: sin columnas válidas")
            continue
        # Nullify FK columns with empty/zero/nonexistent values
        for col, (ref_table, ref_col) in fk_cols.items():
            if col in valid_row:
                val = valid_row[col]
                # If blank, None, or 0 — set to NULL (avoids FK error)
                if val is None or val == "" or val == 0:
                    valid_row[col] = None
                else:
                    # Special case: cliente_id/proveedor_id given as a razon (name) instead of
                    # an id. Resolve by name (case-insensitive), auto-creating the record if needed.
                    if ref_table in ("clientes", "proveedores") and ref_col == "id" and not (
                        isinstance(val, (int, float)) or (isinstance(val, str) and val.strip().isdigit())
                    ):
                        nombre = str(val).strip()
                        found = query(f"SELECT id FROM {ref_table} WHERE lower(razon)=lower(?)",
                                      (nombre,), one=True)
                        if not found:
                            try:
                                new_id = execute(f"INSERT INTO {ref_table} (razon) VALUES (?)", (nombre,))
                                valid_row[col] = new_id
                            except Exception:
                                valid_row[col] = None
                        else:
                            valid_row[col] = found["id"]
                        continue
                    # Check if referenced value exists
                    try:
                        exists = query(f"SELECT 1 FROM {ref_table} WHERE {ref_col}=?",
                                       (val,), one=True)
                        if not exists:
                            valid_row[col] = None  # silently nullify invalid FK
                    except Exception:
                        valid_row[col] = None
        cols_str = ", ".join(valid_row.keys())
        placeholders = ", ".join("?" * len(valid_row))
        try:
            if mode == "upsert" and unique_col and unique_col in valid_row:
                update_cols = [c for c in valid_row.keys() if c not in ("id", unique_col)]
                if update_cols:
                    set_str = ", ".join(f"{c}=excluded.{c}" for c in update_cols)
                    sql = (f"INSERT INTO {table} ({cols_str}) VALUES ({placeholders}) "
                           f"ON CONFLICT({unique_col}) DO UPDATE SET {set_str}")
                else:
                    sql = f"INSERT OR IGNORE INTO {table} ({cols_str}) VALUES ({placeholders})"
                execute(sql, list(valid_row.values()))
            else:
                cmd = "INSERT OR REPLACE" if mode == "upsert" else "INSERT OR IGNORE"
                execute(f"{cmd} INTO {table} ({cols_str}) VALUES ({placeholders})",
                        list(valid_row.values()))
            inserted += 1
        except Exception as e:
            errors.append(f"Fila {i+1}: {str(e)[:80]}")

    return jsonify({"ok": True, "inserted": inserted,
                    "errors": errors, "total": len(rows)})

#!/usr/bin/env python3
"""MetalERP v3.0 - Sistema ERP Taller Metalurgico

Arranque del servidor. El código está repartido por área en la carpeta metalerp/
(ver metalerp/LEEME.md)."""
import metalerp

from metalerp.nucleo import app, auditoria_proceso, get_local_ip
from metalerp.esquema import (_backfill_requerimientos_desde_compras,
    _backfill_requerimientos_desde_ott, _backfill_requerimientos_desde_pedidos,
    _backfill_sc_ott, init_db)
from metalerp.configuracion import iniciar_cotizacion_automatica
from metalerp.planta import iniciar_procesador_planta

# Compatibilidad: los scripts de prueba usan server.<nombre> (server.app,
# server.init_db, server.DB_PATH, funciones internas...). Se copian acá todos
# los nombres del paquete para que sigan funcionando igual que antes.
for _modulo in metalerp.MODULOS:
    globals().update({k: v for k, v in vars(_modulo).items() if not k.startswith("__")})


if __name__ == "__main__":
    print("="*52+"\n   MetalERP v3.0 - Taller Metalurgico\n"+"="*52)
    init_db()
    with app.app_context(), auditoria_proceso("backfill de requerimientos"):
        _backfill_sc_ott()
        _backfill_requerimientos_desde_ott()
        _backfill_requerimientos_desde_compras()
        _backfill_requerimientos_desde_pedidos()
    iniciar_cotizacion_automatica()
    iniciar_procesador_planta()
    ip = get_local_ip()
    
    # 1. Definimos el puerto en una variable única
    PUERTO = 5000
    
    # 2. Usamos la variable en las URLs dinámicamente
    print(f"\n   Local:   http://localhost:{PUERTO}")
    print(f"  Red:     http://{ip}:{PUERTO}")
    print(f"\n   Usuario: admin  |  Contraseña: admin123\n")
    
    # 3. Le pasamos la variable a Flask
    # threaded=True: atiende varias conexiones en paralelo. Sin esto, con
    # varios operarios conectados por la misma wifi, una request lenta
    # (ej. declarar la ultima operacion, que descuenta MP y genera PT)
    # bloqueaba a todas las demas hasta terminar.
    app.run(host="0.0.0.0", port=PUERTO, debug=False, threaded=True)

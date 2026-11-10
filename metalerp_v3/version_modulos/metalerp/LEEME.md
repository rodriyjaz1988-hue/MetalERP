# Código de MetalERP

Desde el 29/10/2026 el servidor está repartido por área. Antes era un solo
`server.py` de 18.300 líneas y un `templates/app.html` de 17.300. El sistema
funciona y se ve exactamente igual: solo cambió dónde está cada cosa.

Se arranca igual que siempre: `INICIAR_SERVIDOR.bat` (o `python server.py`).

## Servidor (Python)

`server.py` quedó chico: solo arranca. Todo lo demás está en la carpeta
`metalerp/`, un archivo por área:

| Archivo | Qué tiene | Rutas |
|---|---|---|
| `nucleo.py` | Núcleo: app Flask, conexión a la base con auditoría, consultas, numeración, sesión, roles, permisos y filtro de valores monetarios. | 0 |
| `esquema.py` | Esquema de la base: SCHEMA, migraciones por versión, init_db, reparaciones y rellenos de datos que corren al arrancar. | 0 |
| `comun.py` | Funciones de negocio compartidas por varias áreas (stock de materiales, herramientas, PT/PSE de operaciones, planes de consumo y devolución). | 0 |
| `paginas.py` | Login, logout, página principal, versión y manual de usuario. | 6 |
| `dashboard.py` | Tableros: operativo, económico, requerimientos e indicadores de compras. | 6 |
| `usuarios.py` | Usuarios, roles, permisos y empleados (RRHH). | 14 |
| `maquinas.py` | Categorías de máquina, máquinas, mantenimiento preventivo y tickets. | 17 |
| `materiales.py` | Materiales (inventario) y movimientos de stock. | 5 |
| `productos.py` | Productos, categorías de producto, operaciones del proceso, herramientas, tiempos y costos, versiones y archivos de producto. | 29 |
| `ventas.py` | Clientes, presupuestos, pedidos de cotización, pronósticos de venta y pedidos de clientes (OC de clientes) con su avance. | 25 |
| `requerimientos.py` | Requerimientos productivos y su sincronización con OTT, pedidos y compras. | 5 |
| `scheduling.py` | Operaciones pendientes por sector y scheduling (Gantt) de producción. | 6 |
| `ordenes.py` | Órdenes de trabajo (OT): alta, edición, operaciones, materiales y lotes asignados. | 18 |
| `cajones.py` | Cajones de producción y su relación con lotes, novedades y remitos. | 8 |
| `ott.py` | Órdenes de trabajo de terceros (OTT): envío, retorno, rechazos y SC del servicio. | 8 |
| `mrp.py` | MRP: consolidación de pedidos y pronósticos, análisis de faltantes y OTs. | 4 |
| `novedades.py` | Novedades de producción, trabajo no productivo y rendimiento por operario. | 15 |
| `lotes.py` | Lotes de stock y trazabilidad (remito, lote, OT, OTT, materia prima). | 5 |
| `compras.py` | Proveedores, solicitudes de compra, cotizaciones, órdenes de compra y recepciones. | 26 |
| `remitos.py` | Remitos a clientes y PT disponible para remitir. | 5 |
| `configuracion.py` | Configuración general, moneda y cotización del dólar. | 7 |
| `pdfs.py` | PDFs: base común y documentos de OT, OP, remito y OC. | 4 |
| `carga_masiva.py` | Carga masiva de datos desde planillas. | 2 |
| `sistema.py` | Bitácora de auditoría (consulta) y registro de cambios del sistema. | 7 |
| `ia.py` | Asistente de IA (Mártin): herramientas de solo lectura, chat e historial, voz. | 6 |
| `hmi.py` | HMI de prueba (/hmi-test): sesiones, ciclos y novedad resultante. | 9 |
| `planta.py` | Tablets de planta, bandeja de registros, procesador, tablero en vivo y lectores de huella. | 23 |

### Reglas para agregar o cambiar código

- Una ruta nueva va en el archivo de su área, con el mismo `@app.route` y
  `@login_required` de siempre. `app` sale de `nucleo.py`.
- Lo que usan todas las áreas (base, sesión, permisos, numeración) va en
  `nucleo.py`. Ese archivo no importa nada de las otras áreas al principio.
- Si una función usa algo de otro archivo, se agrega en las líneas
  `from .otro_archivo import ...`. Las de `nucleo` van arriba de todo; las de
  otras áreas van **al final del archivo**. Es a propósito: así no hay
  problemas de importación circular (compras usa cosas de OTT y OTT de compras).
- Un cambio de la base sigue las reglas de siempre en `esquema.py`: agregar al
  `SCHEMA`, sumar `MIGRACIONES[n]` y subir `ESQUEMA_VERSION`.
- Los scripts de prueba que usan `server.algo` siguen funcionando: `server.py`
  copia todos los nombres del paquete.
- Los archivos tienen fin de línea de Windows (CRLF). Hay que mantenerlo.

## Pantalla principal (templates/app.html)

`templates/app.html` quedó como un índice que arma la página con
`{% include %}`. Las partes están en `templates/app/`:

- `estilos.css`: todos los estilos.
- `menu.html`: el menú lateral.
- `paginas/<pantalla>.html`: una por pantalla. El nombre es el mismo que el
  `data-p` del menú (por ejemplo `paginas/ordenes.html` es `#p-ordenes`).
- `modales/*.html`: las ventanas emergentes, agrupadas por área.
- `js/*.js`: el código de la pantalla, por área. Todos se arman **dentro del
  mismo `<script>`**, en el orden de `app.html`. Ese orden importa: no hay que
  cambiarlo.

Las variables que manda el servidor (`ROL`, `PERMS`, `VER_MONETARIO`,
`IA_PERMITIDA`, `MONEDA`) siguen escritas en `app.html` mismo.

Ojo: las partes también pasan por Jinja. No escribir `{#`, `{%` ni `{{` en el
código JavaScript. En un `.js`, `{{ variable }}` sale sin escapar: usar siempre
`{{ variable|tojson }}`.

## Copiar a otra PC

Ahora hay que copiar `server.py` **y** las carpetas `metalerp/` y
`templates/` completas. Si solo se copia `server.py`, el servidor no arranca.
`ACTUALIZAR.bat` copia todo eso.

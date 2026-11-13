// ── Ayudas de guía (2026-10-19) ──────────────────────────────────────────
// 1) Botones grises de la barra de acciones: al pasar el mouse por el
//    encabezado, cada botón deshabilitado suma a su título el motivo
//    (data-motivo si la pantalla lo define; si no hay fila elegida, que hay
//    que elegir una). Los botones con data-sin-guia arman su propio título.
// 2) Campos de los formularios: título explicativo al pasar el mouse.
(function(){
  function guiaBarra(card){
    const lbl=card.querySelector('.vh-badge[id$="-sel-label"]');
    const sinSel=!!lbl&&lbl.textContent.trim()==='–';
    card.querySelectorAll('.vh-acciones button').forEach(function(b){
      if(b.hasAttribute('data-sin-guia')) return;
      if(b.title!==b.dataset.tg) b.dataset.t0=b.title||'';
      if(b.disabled){
        const m=b.dataset.motivo||(sinSel?'Primero seleccioná una fila de la tabla':(lbl?'No disponible para la fila seleccionada':''));
        if(!m) return;
        const t=b.dataset.t0?b.dataset.t0+'\n→ '+m:m;
        b.title=t; b.dataset.tg=t;
      }else if(b.dataset.tg&&b.title===b.dataset.tg){
        b.title=b.dataset.t0; b.dataset.tg='';
      }
    });
  }
  document.addEventListener('mouseover',function(e){
    const card=e.target&&e.target.closest&&e.target.closest('.vhead-card');
    if(card) guiaBarra(card);
  },true);

  const AYUDAS={
    'mat-min':'Por debajo de este valor el artículo aparece en Alertas de stock y como faltante en Planificación MRP',
    'emat-min':'Por debajo de este valor el artículo aparece en Alertas de stock y como faltante en Planificación MRP',
    'emat-max':'Hasta dónde reponer: si es mayor que el mínimo, el MRP sugiere comprar hasta este valor',
    'op-set':'Minutos para preparar la máquina antes de empezar a producir',
    'ope-set':'Minutos para preparar la máquina antes de empezar a producir',
    'otop-set':'Minutos para preparar la máquina antes de empezar a producir',
    'op-cic':'Segundos que lleva hacer una pieza en esta operación',
    'ope-cic':'Segundos que lleva hacer una pieza en esta operación',
    'otop-cic':'Segundos que lleva hacer una pieza en esta operación',
    'op-tdays':'Días que tarda el tercero en devolver las piezas',
    'lm-pla':'Días que tarda el proveedor en entregar desde que se le pide',
    'cot-pla':'Días que tarda el proveedor en entregar desde que se le pide',
    'pres-val':'Días que el presupuesto mantiene el precio desde su fecha',
    'nov-qty':'Piezas buenas terminadas en esta novedad',
    'nov-obs-qty':'Piezas con defecto o para revisar: no se cuentan como producidas OK',
    'nov-tmin':'Horas que realmente llevó el trabajo (ej.: 1,5 = una hora y media)',
    'reqent-noconforme':'Lo que no pasa el control: se descuenta de la cantidad aprobada',
    'prov-cal':'1 = muy malo · 5 = excelente',
    'maq-rep':'Otras máquinas que pueden hacer el mismo trabajo que esta',
    'et-xbulto':'Piezas que entran en cada bulto: con el total se calcula la cantidad de bultos',
    'mant-ftp':'Unidad con la que se mide cada cuánto se repite la tarea',
    'mant-fvl':'Cada cuántas horas, días o semanas (según Frecuencia) se repite la tarea',
    'ottn-ret':'Fecha en que se espera que el tercero devuelva las piezas'
  };
  function aplicarAyudas(){
    Object.keys(AYUDAS).forEach(function(id){
      const el=document.getElementById(id); if(!el) return;
      if(!el.title) el.title=AYUDAS[id];
      const fg=el.closest('.fg'); const lb=fg&&fg.querySelector('label');
      if(lb&&!lb.title){ lb.title=AYUDAS[id]; lb.style.cursor='help'; }
    });
  }
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',aplicarAyudas); else aplicarAyudas();
})();

// ── Dashboard Requerimientos productivos ──────────────────────────────────────
function irAReqFiltrado(estado){
  document.querySelectorAll('.ni').forEach(n=>n.classList.remove('active'));
  document.querySelectorAll('.page').forEach(p=>p.classList.remove('active'));
  const nav=document.querySelector('[data-p=requerimientos_productivos]');if(nav)nav.classList.add('active');
  const pg=$('p-requerimientos_productivos');if(pg)pg.classList.add('active');
  document.querySelectorAll('#req-tabs .tab').forEach(x=>x.classList.remove('active'));
  const tab=document.querySelector('#req-tabs .tab[data-e="'+estado+'"]');if(tab)tab.classList.add('active');
  reqF=estado;loadReq();
}

async function loadDashRequerimientos(){
  const d=await api('/api/dashboard/requerimientos');
  const pctStr=function(v){return v==null?'—':v+'%';};
  $('dreq-metrics').innerHTML=
    '<div class="metric"><div class="ml">Vencidos</div><div class="mv"'+(d.vencidos>0?' style="color:#A32D2D"':'')+'>'+d.vencidos+'</div></div>'
   +'<div class="metric"><div class="ml">Próximos (7 días)</div><div class="mv"'+(d.proximos_7d>0?' style="color:#854F0B"':'')+'>'+d.proximos_7d+'</div></div>'
   +'<div class="metric"><div class="ml">Activos totales</div><div class="mv">'+d.activos+'</div></div>'
   +'<div class="metric"><div class="ml">Entregados este mes</div><div class="mv" style="color:var(--color-text-success)">'+fN(d.entregados_mes)+'</div></div>'
   +'<div class="metric"><div class="ml">Cumple fecha</div><div class="mv">'+pctStr(d.cumple_fecha_pct)+'</div></div>'
   +'<div class="metric"><div class="ml">Cumple cantidad</div><div class="mv">'+pctStr(d.cumple_cantidad_pct)+'</div></div>'
   +'<div class="metric"><div class="ml">Cumple calidad</div><div class="mv">'+pctStr(d.cumple_calidad_pct)+'</div></div>'
   +'<div class="metric"><div class="ml">Pend. clasificación calidad</div><div class="mv"'+(d.pendientes_calidad>0?' style="color:#854F0B"':'')+'>'+fN(d.pendientes_calidad||0)+'</div></div>';

  if(!d.top_vencidos.length){$('dreq-vencidos').innerHTML='<div class="al al-g">Sin requerimientos vencidos ✓</div>';}
  else{
    let h='<table><tr><th>Número</th><th>Cliente</th><th>Proveedor</th><th>F. Estimada</th><th>Días vencido</th></tr>';
    d.top_vencidos.forEach(function(r){
      h+='<tr><td><b>'+r.numero+'</b></td><td>'+(r.cliente||'—')+'</td><td>'+(r.proveedor||'—')+'</td>'
       +'<td style="color:#A32D2D;font-weight:600">'+fmtD(r.f_estimada)+'</td><td>'+r.dias_vencido+'</td></tr>';
    });
    $('dreq-vencidos').innerHTML=h+'</table>';
  }

  if(!d.top_proximos.length){$('dreq-proximos').innerHTML='<div class="al al-g">Sin vencimientos en los próximos 7 días</div>';}
  else{
    let h='<table><tr><th>Número</th><th>Cliente</th><th>Proveedor</th><th>F. Estimada</th></tr>';
    d.top_proximos.forEach(function(r){
      h+='<tr><td><b>'+r.numero+'</b></td><td>'+(r.cliente||'—')+'</td><td>'+(r.proveedor||'—')+'</td><td>'+fmtD(r.f_estimada)+'</td></tr>';
    });
    $('dreq-proximos').innerHTML=h+'</table>';
  }

  if(!d.por_proveedor.length){$('dreq-proveedor').innerHTML='<div class="em">Sin requerimientos pendientes.</div>';}
  else{
    let h='<table><tr><th>Proveedor</th><th>Pendientes</th></tr>';
    d.por_proveedor.forEach(function(r){h+='<tr><td>'+r.proveedor+'</td><td><b>'+fN(r.cantidad)+'</b></td></tr>';});
    $('dreq-proveedor').innerHTML=h+'</table>';
  }

  const g=d.graficos||{};
  renderReqLineChart('dreq-chart-calidad', g.meses||[], g.indice_calidad||{}, g.objetivo_pct);
  renderReqLineChart('dreq-chart-entrega', g.meses||[], g.cumplimiento_entrega||{}, g.objetivo_pct);
  renderReqBarChart('dreq-chart-barras', g.cantidad_pedida_vs_entregada||[]);
  renderReqProveedorPerfChart('dreq-chart-performance-prov', g.performance_por_proveedor||[]);
}

// Paleta fija por categoría — misma lógica de agrupación que el Excel original
// (TRATAMIENTO SUPERFICIAL / MATERIA PRIMA / PROCESO), consistente entre ambos gráficos de línea
const REQ_CHART_CAT_COLORS = {
  'TRATAMIENTO SUPERFICIAL': '#2C5F8A',
  'MATERIA PRIMA':           '#A32D2D',
  'PROCESO':                 '#1B5E20',
  'SIN CATEGORÍA':           '#854F0B',
};
const REQ_CHART_COLORS = ['#2C5F8A','#A32D2D','#1B5E20','#854F0B','#6A3D9A','#0E7C86'];
const REQ_CHART_PROM_COLOR = '#E08A00';
const REQ_CHART_OBJ_COLOR = '#888';

function reqChartColor(cat, ci){
  return REQ_CHART_CAT_COLORS[cat] || REQ_CHART_COLORS[ci % REQ_CHART_COLORS.length];
}

function renderReqLineChart(containerId, meses, series, objetivoPct){
  const el=$(containerId);
  if(!el) return;
  // Orden fijo, mostrando sólo las series presentes
  const ORDEN = ['TRATAMIENTO SUPERFICIAL','MATERIA PRIMA','PROCESO','SIN CATEGORÍA','PROMEDIO MENSUAL'];
  const cats = ORDEN.filter(function(c){return Object.prototype.hasOwnProperty.call(series||{}, c);});
  if(!meses.length || !cats.length){el.innerHTML='<div class="em">Sin datos suficientes para graficar.</div>';return;}

  let h='<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px">';
  cats.forEach(function(cat,ci){
    const isProm = cat==='PROMEDIO MENSUAL';
    const color = isProm ? REQ_CHART_PROM_COLOR : reqChartColor(cat, ci);
    h+='<div>'
      +'<div style="font-size:11.5px;font-weight:700;margin-bottom:4px;color:'+color+'">'+cat+'</div>'
      +renderReqLineChartSingle(meses, series[cat]||[], objetivoPct, color, isProm)
      +'</div>';
  });
  h+='</div>';
  el.innerHTML = h;
}

function renderReqLineChartSingle(meses, vals, objetivoPct, color, isProm){
  const W=340, H=170, padL=32, padR=10, padT=12, padB=22;
  const plotW=W-padL-padR, plotH=H-padT-padB;
  const n=meses.length;
  const xStep = n>1 ? plotW/(n-1) : 0;
  const x=function(i){return padL + i*xStep;};
  const y=function(pct){return padT + plotH - (Math.max(0,Math.min(100,pct))/100)*plotH;};

  let svg='<svg viewBox="0 0 '+W+' '+H+'" style="width:100%;height:auto;font-family:inherit;background:var(--color-bg-secondary);border-radius:6px" xmlns="http://www.w3.org/2000/svg">';

  // Grilla horizontal (0/50/100%)
  [0,50,100].forEach(function(p){
    const yy=y(p);
    svg+='<line x1="'+padL+'" y1="'+yy+'" x2="'+(W-padR)+'" y2="'+yy+'" stroke="var(--color-border-tertiary)" stroke-width="1"/>';
    svg+='<text x="'+(padL-5)+'" y="'+(yy+3)+'" font-size="8.5" text-anchor="end" fill="var(--color-text-secondary)">'+p+'%</text>';
  });

  // Eje X: etiquetas de mes (todas si hay pocas, alternadas si hay muchas)
  const skip = n>8 ? 2 : 1;
  meses.forEach(function(m,i){
    if(i%skip!==0 && i!==n-1) return;
    svg+='<text x="'+x(i)+'" y="'+(H-6)+'" font-size="8" text-anchor="middle" fill="var(--color-text-secondary)">'+m+'</text>';
  });

  // Línea objetivo
  if(objetivoPct!=null){
    const oy=y(objetivoPct);
    svg+='<line x1="'+padL+'" y1="'+oy+'" x2="'+(W-padR)+'" y2="'+oy+'" stroke="'+REQ_CHART_OBJ_COLOR+'" stroke-width="1.25" stroke-dasharray="4,3"/>';
  }

  // Serie
  let path='', started=false;
  vals.forEach(function(v,i){
    if(v==null){started=false;return;}
    const cmd=started?'L':'M';
    path+=cmd+x(i)+' '+y(v)+' ';
    started=true;
  });
  if(path) svg+='<path d="'+path.trim()+'" fill="none" stroke="'+color+'" stroke-width="'+(isProm?2.75:2.25)+'" '+(isProm?'stroke-dasharray="6,2.5"':'')+' stroke-linecap="round"/>';
  vals.forEach(function(v,i){
    if(v==null) return;
    svg+='<circle cx="'+x(i)+'" cy="'+y(v)+'" r="3" fill="'+color+'"><title>'+meses[i]+': '+v+'%</title></circle>';
    svg+='<text x="'+x(i)+'" y="'+(y(v)-7)+'" font-size="8" text-anchor="middle" fill="'+color+'" font-weight="600">'+v+'</text>';
  });

  svg+='</svg>';
  return svg;
}

// Barras agrupadas por proveedor: % cumplimiento fecha / cantidad / calidad.
// Misma paleta que renderReqLineChart (colores fijos por eje, no por categoría),
// y mismo criterio visual de svg-en-fondo-var(--color-bg-secondary) que los otros gráficos.
const REQ_PERF_EJES = [
  {key:'cumple_fecha_pct',    label:'Fecha',    color:'#2C5F8A'},
  {key:'cumple_cantidad_pct', label:'Cantidad', color:'#1B5E20'},
  {key:'cumple_calidad_pct',  label:'Calidad',  color:'#854F0B'},
];

function renderReqProveedorPerfChart(containerId, data){
  const el=$(containerId);
  if(!el) return;
  if(!data.length){el.innerHTML='<div class="em">Sin requerimientos entregados con datos de cumplimiento.</div>';return;}

  const n = data.length;
  const groupW = 150, barW = 26, barGap = 6, H = 210, padT = 14, padB = 46, padL = 34, padR = 10;
  const plotH = H - padT - padB;
  const W = padL + padR + n*groupW;
  const y = function(pct){return padT + plotH - (Math.max(0,Math.min(100,pct))/100)*plotH;};

  let svg='<svg viewBox="0 0 '+W+' '+H+'" style="width:100%;height:auto;min-width:'+Math.max(W,340)+'px;font-family:inherit;background:var(--color-bg-secondary);border-radius:6px" xmlns="http://www.w3.org/2000/svg">';

  // Grilla horizontal (0/50/100%)
  [0,50,100].forEach(function(p){
    const yy=y(p);
    svg+='<line x1="'+padL+'" y1="'+yy+'" x2="'+(W-padR)+'" y2="'+yy+'" stroke="var(--color-border-tertiary)" stroke-width="1"/>';
    svg+='<text x="'+(padL-5)+'" y="'+(yy+3)+'" font-size="8.5" text-anchor="end" fill="var(--color-text-secondary)">'+p+'%</text>';
  });

  data.forEach(function(prov, gi){
    const gx = padL + gi*groupW + (groupW - (REQ_PERF_EJES.length*barW + (REQ_PERF_EJES.length-1)*barGap))/2;
    REQ_PERF_EJES.forEach(function(eje, ei){
      const v = prov[eje.key];
      const bx = gx + ei*(barW+barGap);
      if(v==null){
        svg+='<text x="'+(bx+barW/2)+'" y="'+(y(0)-4)+'" font-size="8" text-anchor="middle" fill="var(--color-text-secondary)">s/d</text>';
        return;
      }
      const by = y(v);
      svg+='<rect x="'+bx+'" y="'+by+'" width="'+barW+'" height="'+(y(0)-by)+'" rx="2" fill="'+eje.color+'"><title>'+prov.proveedor+' — '+eje.label+': '+v+'%</title></rect>';
      svg+='<text x="'+(bx+barW/2)+'" y="'+(by-4)+'" font-size="8" text-anchor="middle" fill="'+eje.color+'" font-weight="600">'+v+'</text>';
    });
    // Etiqueta de proveedor (multi-línea simple si es largo)
    const cx = padL + gi*groupW + groupW/2;
    const nombre = prov.proveedor.length>18 ? prov.proveedor.slice(0,17)+'…' : prov.proveedor;
    svg+='<text x="'+cx+'" y="'+(H-padB+14)+'" font-size="9" text-anchor="middle" fill="var(--color-text-primary)" font-weight="600">'+nombre+'</text>';
    svg+='<text x="'+cx+'" y="'+(H-padB+26)+'" font-size="8" text-anchor="middle" fill="var(--color-text-secondary)">'+fN(prov.entregados)+' entreg.</text>';
  });

  svg+='</svg>';

  let leg='<div style="display:flex;flex-wrap:wrap;gap:14px;margin-top:8px;font-size:11.5px">';
  REQ_PERF_EJES.forEach(function(eje){
    leg+='<div style="display:flex;align-items:center;gap:5px"><span style="width:11px;height:11px;border-radius:2px;background:'+eje.color+';display:inline-block"></span><b>'+eje.label+'</b></div>';
  });
  leg+='</div>';

  el.innerHTML = svg + leg;
}

function renderReqBarChart(containerId, data){
  const el=$(containerId);
  if(!el) return;
  if(!data.length){el.innerHTML='<div class="em">Sin requerimientos con cantidad pedida registrada.</div>';return;}
  const maxVal = Math.max.apply(null, data.map(function(d){return Math.max(d.cantidad_pedida, d.cantidad_entregada||0);}), 1);
  const fmtN=function(v){return (Math.round(v*100)/100).toLocaleString('es-AR');};
  let h='<div style="display:flex;flex-wrap:wrap;gap:14px;margin-bottom:10px;font-size:11.5px">'
    +'<div style="display:flex;align-items:center;gap:5px"><span style="width:11px;height:11px;border-radius:2px;background:#2C5F8A;display:inline-block"></span><b>Pedida</b></div>'
    +'<div style="display:flex;align-items:center;gap:5px"><span style="width:11px;height:11px;border-radius:2px;background:#1B5E20;display:inline-block"></span><b>Entregada</b></div>'
    +'</div>';
  h+='<div style="display:flex;flex-direction:column;gap:12px">';
  data.forEach(function(r){
    const pctPed = Math.round((r.cantidad_pedida/maxVal)*100);
    const pctEnt = Math.round(((r.cantidad_entregada||0)/maxVal)*100);
    const cumplioCant = (r.cantidad_entregada||0) >= r.cantidad_pedida;
    h+='<div>';
    h+='<div style="font-size:11.5px;font-weight:600;margin-bottom:4px">'+r.numero+(r.codigo?' — '+r.codigo:'')
      +(cumplioCant?' <span style="color:var(--color-text-success);font-weight:400">✓ completo</span>':' <span style="color:#A32D2D;font-weight:400">faltante</span>')+'</div>';
    h+='<div style="display:flex;align-items:center;gap:6px;margin-bottom:3px">';
    h+='<div style="width:66px;font-size:10.5px;color:var(--color-text-secondary)">Pedida</div>';
    h+='<div style="flex:1;background:var(--color-border-tertiary);border-radius:3px;height:12px"><div style="background:#2C5F8A;height:12px;border-radius:3px;width:'+pctPed+'%;min-width:2px"></div></div>';
    h+='<div style="width:70px;font-size:10.5px;text-align:right;font-weight:600">'+fmtN(r.cantidad_pedida)+'</div></div>';
    h+='<div style="display:flex;align-items:center;gap:6px">';
    h+='<div style="width:66px;font-size:10.5px;color:var(--color-text-secondary)">Entregada</div>';
    h+='<div style="flex:1;background:var(--color-border-tertiary);border-radius:3px;height:12px"><div style="background:'+(cumplioCant?'#1B5E20':'#B08900')+';height:12px;border-radius:3px;width:'+pctEnt+'%;min-width:2px"></div></div>';
    h+='<div style="width:70px;font-size:10.5px;text-align:right;font-weight:600">'+fmtN(r.cantidad_entregada||0)+'</div></div>';
    h+='</div>';
  });
  h+='</div>';
  el.innerHTML=h;
}

// ── Requerimientos productivos ─────────────────────────────────────────────────
let _reqRows=[], reqF='', _reqSel=null;
document.querySelectorAll('#req-tabs .tab').forEach(t=>t.addEventListener('click',()=>{
  document.querySelectorAll('#req-tabs .tab').forEach(x=>x.classList.remove('active'));
  t.classList.add('active');reqF=t.dataset.e;loadReq();
}));

async function loadReq(){
  $('req-list').innerHTML='<div class="ld">Cargando...</div>';
  const url='/api/requerimientos_productivos'+(reqF?'?estado='+encodeURIComponent(reqF):'');
  _reqRows=await api(url);
  if(!Array.isArray(_reqRows)){_reqRows=[];_reqSel=null;actualizarToolbarReq();$('req-list').innerHTML='<div class="em">Error al cargar.</div>';return;}
  renderReq();
}

// La auto-carga por PDF/foto (autoCargarReq) fue reemplazada: los requerimientos
// productivos ahora se generan y actualizan solos desde las OTT (ver backend
// _sync_requerimiento_desde_ott). Se mantiene la carga manual (openReqModal)
// solo como excepción para casos que no pasan por una OTT.

function renderReq(){
  const q=($('req-buscar')?$('req-buscar').value:'').toLowerCase().trim();
  const filtradas=q?_reqRows.filter(function(r){
    return ((r.numero||'')+' '+(r.codigo||'')+' '+(r.cliente_nombre||'')+' '+(r.proveedor_nombre||'')+' '+(r.material_proceso||'')).toLowerCase().includes(q);
  }):_reqRows;
  if(_reqSel && !filtradas.some(function(r){return r.id===_reqSel;})) _reqSel=null;
  actualizarToolbarReq();
  if(!filtradas.length){$('req-list').innerHTML='<div class="em">'+(q?'No hay requerimientos que coincidan con la búsqueda.':'No hay requerimientos.')+'</div>';return;}
  let h='<table><tr><th style="width:24px"></th><th>Número</th><th>Cliente</th><th>Código</th><th>Material / Proceso</th><th>Proveedor</th>'
    +'<th>Cant. pedida</th><th>F. Estimada</th><th>F. Entrega</th><th>Estado</th><th>Calidad</th></tr>';
  filtradas.forEach(r=>{
    const c=r._calidad;
    let calidadBadge='—';
    if(c && r.f_entrega){
      const loteTitle=c.lote_pct!=null?' title="'+Math.round(c.lote_pct*100)+'% aprobado del lote"':'';
      if(!c.evaluable){
        calidadBadge='<span class="b ba" title="Lote de stock todavía sin decisión de Calidad">Pend. clasificación</span>';
      } else if(c.origen==='manual'){
        calidadBadge='<span class="b bk" title="Sin lote de stock vinculado — calidad cargada a mano (cant. no conforme)">Calidad manual</span>'
          +(c.aprobado===0?' <span class="b br">Incidente</span>':'');
      } else if(c.aprobado===0){
        calidadBadge='<span class="b br"'+loteTitle+'>Incidente</span>';
      } else {
        calidadBadge='<span class="b bg"'+loteTitle+'>Aprobado</span>';
      }
    }
    const sel=_reqSel===r.id;
    h+='<tr class="'+(sel?'ot-sel':'')+'" style="cursor:pointer" onclick="selReq('+r.id+')" ondblclick="openReqModal('+r.id+')">'
      +'<td><input type="radio" name="req-sel" '+(sel?'checked':'')+' onclick="event.stopPropagation();selReq('+r.id+')"></td>'
      +'<td><b>'+r.numero+'</b></td><td>'+(r.cliente_nombre||'—')+'</td><td>'+(r.codigo||'—')+'</td>'
      +'<td>'+(r.material_proceso||'—')+(r.provision?' <span style="color:var(--color-text-secondary)">— '+r.provision+'</span>':'')+'</td>'
      +'<td>'+(r.proveedor_nombre||'—')+'</td>'
      +'<td>'+fN(r.cantidad_pedida)+' '+(r.unidad||'')+(r.cantidad_entregada!=null?' <span style="color:var(--color-text-secondary)">(ent. '+r.cantidad_entregada+(r.cantidad_aprobada!=null?' / apr. '+r.cantidad_aprobada:'')+')</span>':'')+'</td>'
      +'<td>'+fmtD(r.f_estimada)+'</td><td>'+fmtD(r.f_entrega)+'</td><td>'+sb(r.estado)+'</td>'
      +'<td>'+calidadBadge+'</td></tr>';
  });
  $('req-list').innerHTML=h+'</table>';
}

function selReq(id){ _reqSel=id; renderReq(); }
function actualizarToolbarReq(){
  const r=_reqSel?_reqRows.find(function(x){return x.id===_reqSel;}):null;
  $('req-sel-label').textContent=r?r.numero:'–';
  $('req-b-edit').disabled=!r;
  $('req-b-entrega').disabled=!r||r.estado==='ENTREGADO'||r.estado==='ANULADO';
  $('req-b-elim').style.display=ROL==='admin'?'':'none';
  $('req-b-elim').disabled=!r;
}
function reqSelAccion(a){
  const r=_reqSel?_reqRows.find(function(x){return x.id===_reqSel;}):null;
  if(!r){toast('Seleccioná un requerimiento de la lista','w');return;}
  if(a==='edit') openReqModal(r.id);
  else if(a==='entrega') openEntregaReq(r.id);
  else if(a==='elim') deleteReq(r.id);
}

async function openReqModal(id){
  $('req-id').value='';$('req-numero').value='';$('req-codigo').value='';
  cliBuscadorClear('req-cli');$('req-mat-proc').value='';$('req-provision').value='';
  $('req-cant-pedida').value='';$('req-unidad').value='';$('req-oc-remito').value='';
  $('req-icp').value='';$('req-f-pedido').value='';$('req-f-necesidad').value='';
  $('req-f-estimada').value='';$('req-estado').value='';$('req-ubicacion').value='';$('req-obs').value='';
  if(!_prov.length)_prov=await api('/api/proveedores');
  await selLoad('req-proveedor',_prov,null,'— Sin proveedor —');
  if(id){
    const r=_reqRows.find(x=>x.id===id);
    if(!r){toast('Requerimiento no encontrado','e');return;}
    $('mo-req-title').innerHTML='Requerimiento '+r.numero+' <span class="mx" onclick="closeMo(\'mo-req\')">×</span>';
    $('req-id').value=r.id;$('req-numero').value=r.numero;$('req-codigo').value=r.codigo||'';
    cliBuscadorSet('req-cli',r.cliente_id);
    $('req-proveedor').value=r.proveedor_id||'';
    $('req-mat-proc').value=r.material_proceso||'';$('req-provision').value=r.provision||'';
    $('req-cant-pedida').value=r.cantidad_pedida;$('req-unidad').value=r.unidad||'';
    $('req-oc-remito').value=r.nro_oc_remito||'';$('req-icp').value=r.nro_icp||'';
    $('req-f-pedido').value=(r.f_pedido||'').slice(0,10);
    $('req-f-necesidad').value=(r.f_necesidad||'').slice(0,10);
    $('req-f-estimada').value=(r.f_estimada||'').slice(0,10);
    $('req-estado').value=r.estado==='ANULADO'?'ANULADO':'';
    $('req-ubicacion').value=r.ubicacion_remito||'';$('req-obs').value=r.obs||'';
  } else {
    toast('Los requerimientos se generan automáticamente; no se pueden crear a mano','w');
    return;
  }
  openMo('mo-req');
}

async function saveReq(){
  const numero=$('req-numero').value.trim();
  const cantidad=parseFloat($('req-cant-pedida').value);
  if(!numero){toast('El número es obligatorio','w');return;}
  if(!cantidad){toast('La cantidad pedida es obligatoria','w');return;}
  const id=$('req-id').value;
  const d={
    numero, cliente_id:$('req-cli').value||null, codigo:$('req-codigo').value.trim(),
    material_proceso:$('req-mat-proc').value.trim(), provision:$('req-provision').value.trim(),
    cantidad_pedida:cantidad, unidad:$('req-unidad').value.trim(),
    proveedor_id:$('req-proveedor').value||null, nro_oc_remito:$('req-oc-remito').value.trim(),
    f_pedido:$('req-f-pedido').value||null, f_necesidad:$('req-f-necesidad').value||null,
    f_estimada:$('req-f-estimada').value||null, estado:$('req-estado').value||null,
    nro_icp:$('req-icp').value.trim(), ubicacion_remito:$('req-ubicacion').value.trim(),
    obs:$('req-obs').value.trim()
  };
  const res=id?await api('/api/requerimientos_productivos/'+id,{method:'PUT',body:JSON.stringify(d)})
    :await api('/api/requerimientos_productivos',{method:'POST',body:JSON.stringify(d)});
  if(res.ok){toast('Requerimiento guardado');closeMo('mo-req');loadReq();}
  else toast(res.error||'Error','e');
}

function openEntregaReq(id){
  const r=_reqRows.find(x=>x.id===id);
  if(!r){toast('Requerimiento no encontrado','e');return;}
  $('reqent-id').value=r.id;
  $('reqent-info').textContent=r.numero+' — '+(r.material_proceso||r.codigo||'')+' · Cant. pedida: '+fN(r.cantidad_pedida)+' '+(r.unidad||'');
  $('reqent-cantidad').value=r.cantidad_entregada!=null?r.cantidad_entregada:r.cantidad_pedida;
  $('reqent-fecha').value='';$('reqent-remito').value=r.remito||'';
  $('reqent-factura').value=r.nro_factura||'';$('reqent-noconforme').value='';
  $('reqent-aprobada').value=r.cantidad_aprobada!=null?r.cantidad_aprobada:'';
  openMo('mo-req-entrega');
}

// Recalcula "Cantidad aprobada" = entregada - no conforme a medida que se
// tipean esos dos campos. Queda igual editable a mano si el usuario la toca
// después (no se vuelve a pisar salvo que cambien entregada/no conforme).
function reqEntCalcAprobada(){
  const ent=$('reqent-cantidad').value?parseFloat($('reqent-cantidad').value):null;
  const noConf=$('reqent-noconforme').value?parseFloat($('reqent-noconforme').value):0;
  $('reqent-aprobada').value=ent!=null?(ent-noConf):'';
}

async function saveEntregaReq(){
  const id=$('reqent-id').value;
  const fecha=$('reqent-fecha').value;
  if(!fecha){toast('La fecha de entrega es obligatoria','w');return;}
  const d={
    f_entrega:fecha,
    cantidad_entregada:$('reqent-cantidad').value?parseFloat($('reqent-cantidad').value):null,
    remito:$('reqent-remito').value.trim(), nro_factura:$('reqent-factura').value.trim(),
    cant_no_conforme:$('reqent-noconforme').value?parseFloat($('reqent-noconforme').value):null,
    cantidad_aprobada:$('reqent-aprobada').value?parseFloat($('reqent-aprobada').value):null
  };
  const res=await api('/api/requerimientos_productivos/'+id+'/entrega',{method:'PUT',body:JSON.stringify(d)});
  if(res.ok){toast('Entrega registrada');closeMo('mo-req-entrega');loadReq();}
  else toast(res.error||'Error','e');
}

async function deleteReq(id){
  if(!await confirmar('¿Eliminar este requerimiento? Esta acción no se puede deshacer.'))return;
  const res=await apiBorrar('/api/requerimientos_productivos/'+id,'Requerimiento eliminado');
  if(res.ok){toast('Requerimiento eliminado');loadReq();}
  else toast(res.error||'Error','e');
}


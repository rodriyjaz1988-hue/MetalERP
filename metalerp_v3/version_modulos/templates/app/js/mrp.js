// ── MRP (versión completa v3) ─────────────────────────────────────────────────
let _mrpCrit=new Map();
async function loadMRP(){
  const d=await api('/api/mrp');
  _mrpCrit=new Map(d.criticos.map(function(r){return [r.id,r];}));
  if(!d.criticos.length){$('mrp-mat').innerHTML='<div class="em">Sin materiales críticos.</div>';}
  else{
    let h='<table><tr><th>Código</th><th>Descripción</th><th>Stock</th><th>Mínimo</th><th>Faltante</th><th>Faltante (máx.)</th><th></th><th>Unidad</th><th>Proveedor</th><th>Estado</th></tr>';
    d.criticos.forEach(r=>{
      const faltanteMax=(r.stock_max&&r.stock_max>0)?Math.max(0,Math.round((r.stock_max-r.stock)*100)/100):null;
      // La cantidad a pedir (cant_sc) la calcula el servidor con el criterio
      // del MRP: disponible libre por lote más lo que ya viene en OC abiertas.
      const btnHtml=(ROL==='operario')?'—':(r.sc_activa
        ? `<button class="btn btn-s" disabled title="Ya existe ${schEsc(r.sc_activa)} abierta para este material">✓ ${schEsc(r.sc_activa)}</button>`
        : r.categoria==='Producto terminado'
        ? `<span title="Un producto terminado no se compra: se fabrica con una OT">Fabricar</span>`
        : !(r.cant_sc>0)
        ? `<button class="btn btn-s" disabled title="Lo que viene en órdenes de compra abiertas (${fN(r.en_camino)} ${schEsc(r.unidad)}) ya cubre el faltante">En camino</button>`
        : `<button class="btn btn-s" id="mrp-sc-${r.id}" title="Pide ${fN(r.cant_sc)} ${schEsc(r.unidad)}: hasta el máximo, descontando el disponible libre y lo que viene en OC" onclick="mrpAgregarSC(${r.id})">+ SC</button>`);
      h+=`<tr><td>${schEsc(r.codigo)}</td><td>${schEsc(r.descripcion)}</td><td>${fN(r.stock)}</td><td>${fN(r.stock_min)}</td><td><b>${fN(r.faltante)}</b></td><td>${faltanteMax!=null?fN(faltanteMax):'—'}</td><td>${btnHtml}</td><td>${r.unidad}</td><td>${r.proveedor||'—'}</td><td>${r.stock<=0?'<span class="b br">Sin stock</span>':'<span class="b ba">Bajo mínimo</span>'}</td></tr>`;
    });
    $('mrp-mat').innerHTML=h+'</table>';
  }
  if(!d.ordenes_activas.length){$('mrp-ot').innerHTML='<div class="em">No hay órdenes activas. Acá aparecen las OT pendientes o en proceso.</div>';}
  else{
    let h='<table><tr><th>N° OT</th><th>Cliente</th><th>Producto</th><th>Cant.</th><th>Estado</th><th>Entrega</th></tr>';
    d.ordenes_activas.forEach(r=>{h+=`<tr><td><b>${r.numero}</b></td><td>${r.cliente||'—'}</td><td>${r.producto||r.descripcion}</td><td>${fN(r.cantidad)}</td><td>${sb(r.estado)}</td><td>${fmtD(r.fecha_entrega)}</td></tr>`;});
    $('mrp-ot').innerHTML=h+'</table>';
  }
  // Carga por sector
  if(d.carga_por_sector&&d.carga_por_sector.length){
    let h2='<table><tr><th>Sector</th><th>Ops. pendientes</th><th>Piezas pendientes</th></tr>';
    d.carga_por_sector.forEach(r=>{h2+=`<tr><td><b>${r.sector}</b></td><td>${fN(r.ops_pendientes)}</td><td>${Math.round(r.piezas_pendientes||0)}</td></tr>`;});
    $('mrp-carga-sector').innerHTML=h2+'</table>';
  } else {
    $('mrp-carga-sector').innerHTML='<div class="em">Sin carga de trabajo pendiente por sector.</div>';
  }
  // OC cliente pendientes
  if(d.oc_cliente_pendientes&&d.oc_cliente_pendientes.length){
    let h3='<table><tr><th><input type="checkbox" id="oc-all" onchange="toggleAllOC(this)"></th><th>N°</th><th>Cliente</th><th>Entrega</th><th>Estado</th></tr>';
    d.oc_cliente_pendientes.forEach(r=>{h3+=`<tr><td><input type="checkbox" class="oc-chk" value="${r.id}"></td><td><b>${r.numero}</b></td><td>${r.cliente_nombre}</td><td>${fmtD(r.fecha_entrega)}</td><td>${sb(r.estado)}</td></tr>`;});
    $('mrp-oc-pend').innerHTML=h3+'</table>';
  } else {
    $('mrp-oc-pend').innerHTML='<div class="em">Sin pedidos de clientes pendientes de procesar.</div>';
  }
  // Pronósticos de venta pendientes de consolidar
  if(d.pronosticos_pendientes&&d.pronosticos_pendientes.length){
    let h4='<table><tr><th><input type="checkbox" id="pron-all" onchange="toggleAllPron(this)"></th><th>Código</th><th>Cliente</th><th>Emisión</th><th>Períodos</th><th>Renglones pend.</th></tr>';
    d.pronosticos_pendientes.forEach(r=>{h4+=`<tr><td><input type="checkbox" class="pron-chk" value="${r.id}"></td><td><b>${r.codigo}</b></td><td>${r.cliente_nombre||'—'}</td><td>${fmtD(r.fecha_emision)}</td><td>${r.periodos}</td><td>${fN(r.items_pendientes)}</td></tr>`;});
    $('mrp-pron-pend').innerHTML=h4+'</table>';
  } else {
    $('mrp-pron-pend').innerHTML='<div class="em">Sin pronósticos de venta pendientes de consolidar.</div>';
  }
}

function toggleAllOC(cb){document.querySelectorAll('.oc-chk').forEach(c=>c.checked=cb.checked);}
function toggleAllPron(cb){document.querySelectorAll('.pron-chk').forEach(c=>c.checked=cb.checked);}

async function consolidarTodo(){
  const ocIds=[...document.querySelectorAll('.oc-chk:checked')].map(c=>parseInt(c.value));
  const pronIds=[...document.querySelectorAll('.pron-chk:checked')].map(c=>parseInt(c.value));
  if(!ocIds.length&&!pronIds.length){toast('Seleccioná al menos un pedido o pronóstico','w');return;}
  if(pronIds.length){
    // El flujo de pronóstico pide el mes; ese modal ya detecta y consolida los OC tildados también
    await consolidarPronostico();
  } else {
    await consolidarOCs();
  }
}

// Texto con lo que generó una consolidación (OT auxiliares, SC y avisos).
function _mrpExtras(res){
  let m='';
  const aux=(res.ots_auxiliares||[]).filter(function(o){return !o.actualizada;});
  if(aux.length) m+=' · '+aux.length+' OT auxiliar'+(aux.length!==1?'es':'')+' por faltante de insumo';
  if(res.solicitudes_compra&&res.solicitudes_compra.length) m+=' · '+res.solicitudes_compra.length+' SC de compra generada'+(res.solicitudes_compra.length!==1?'s':'');
  if(res.avisos&&res.avisos.length) m+=' · Atención: '+res.avisos.join(' ');
  return m;
}

async function consolidarOCs(){
  const ids=[...document.querySelectorAll('.oc-chk:checked')].map(c=>parseInt(c.value));
  if(!ids.length){toast('Seleccioná al menos un pedido','w');return;}
  if(!await confirmar(`¿Consolidar ${ids.length} pedido(s) y generar OTs automáticamente?`))return;
  const res=await api('/api/mrp/consolidar',{method:'POST',body:JSON.stringify({oc_ids:ids})});
  if(res.ok){
    const nums=res.ots.map(o=>o.numero+' ('+o.producto+' x'+fN(o.cantidad)+')').join(', ');
    toast('OTs generadas: '+nums+_mrpExtras(res),res.avisos&&res.avisos.length?'w':undefined);
  } else toast(res.error||'Error','e');
  loadMRP();
}




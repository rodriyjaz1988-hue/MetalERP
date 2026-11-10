// ── Pronóstico de ventas ─────────────────────────────────────────────────────
let _pvActualId = null;
let _pvRows=[];

let _pvF='';     // pestaña activa: '', 'Alta', 'Baja'
let _pvSel=null; // id del pronóstico seleccionado
document.querySelectorAll('#pv-tabs .tab').forEach(t=>t.addEventListener('click',()=>{
  document.querySelectorAll('#pv-tabs .tab').forEach(x=>x.classList.remove('active'));
  t.classList.add('active');_pvF=t.dataset.e;renderPV();
}));

function clearFiltrosPV(){
  if($('pv-buscar'))$('pv-buscar').value='';
  _pvF='';
  document.querySelectorAll('#pv-tabs .tab').forEach(x=>x.classList.toggle('active',x.dataset.e===''));
  renderPV();
}

async function loadPronosticoVentas(){
  const rows = await api('/api/pronosticos_venta');
  _pvRows = rows;
  renderPV();
}

function renderPV(){
  const rows=_pvRows||[];
  if(!rows.length){
    $('pv-lista').innerHTML='<div class="em">No hay pronósticos generados. Usá «Nuevo pronóstico» para crear el primero.</div>';
    _pvActualId = null;
    actualizarToolbarPV();
    return;
  }
  if(_pvSel!==null && !rows.some(r=>r.id===_pvSel)) _pvSel=null;
  const q=($('pv-buscar')?$('pv-buscar').value:'').trim().toLowerCase();
  let list=rows;
  if(_pvF) list=list.filter(r=>r.estado===_pvF);
  if(q) list=list.filter(r=>(r.codigo||'').toLowerCase().includes(q)||(r.cliente_nombre||'Todos').toLowerCase().includes(q));
  if(!list.length){
    $('pv-lista').innerHTML='<div class="em">Sin resultados para los filtros seleccionados.</div>';
    _pvActualId = null;
    actualizarToolbarPV();
    return;
  }
  const abiertoPrevio = _pvActualId;
  let h='<table><tr><th style="width:24px"></th><th>Código</th><th>Estado</th><th>Cliente</th><th>Fecha emisión</th><th>Periodos</th></tr>';
  list.forEach(r=>{
    const abierto = r.id===abiertoPrevio;
    const sel = r.id===_pvSel;
    h+=`<tr id="pv-row-${r.id}" class="${sel?'ot-sel':''}" style="cursor:pointer" onclick="selPV(${r.id})">`
     +`<td style="white-space:nowrap"><input type="radio" name="pv-sel" ${sel?'checked':''} onclick="event.stopPropagation();selPV(${r.id})"> <button class="btn btn-s" onclick="event.stopPropagation();selPV(${r.id});togglePvDetalle(${r.id})" id="pv-toggle-${r.id}" title="Ver tabla">${abierto?'▲':'▼'}</button></td>`
     +`<td><b>${r.codigo}</b></td><td>${r.estado==='Alta'?'<span class="b bg">Alta</span>':'<span class="b bk">Baja</span>'}</td>`
     +`<td>${r.cliente_nombre||'Todos'}</td>`
     +`<td>${fmtD(r.fecha_emision)}</td><td>${r.periodos} meses</td></tr>`
     +`<tr id="pv-detalle-row-${r.id}" style="display:${abierto?'table-row':'none'}"><td colspan="6" style="background:var(--color-background-secondary)"><div id="pv-detalle-${r.id}"></div></td></tr>`;
  });
  $('pv-lista').innerHTML=h+'</table>';
  if(abiertoPrevio && list.some(r=>r.id===abiertoPrevio)) verPronosticoVentas(abiertoPrevio);
  else _pvActualId=null;
  actualizarToolbarPV();
}

// Selecciona un pronóstico sin volver a pintar la tabla (así no se cierra
// el detalle que esté desplegado).
function selPV(id){
  _pvSel=id;
  document.querySelectorAll('#pv-lista tr.ot-sel').forEach(tr=>tr.classList.remove('ot-sel'));
  const tr=$('pv-row-'+id);
  if(tr){
    tr.classList.add('ot-sel');
    const rd=tr.querySelector('input[type=radio]'); if(rd) rd.checked=true;
  }
  actualizarToolbarPV();
}
function actualizarToolbarPV(){
  const r=_pvSel!==null?(_pvRows||[]).find(x=>x.id===_pvSel):null;
  const lbl=$('pv-sel-label'); if(lbl) lbl.textContent=r?r.codigo:'–';
  ['ver','estado','elim'].forEach(k=>{const b=$('pv-b-'+k);if(b)b.disabled=!r;});
  const t=$('pv-b-estado-txt'); if(t) t.textContent=(r&&r.estado!=='Alta')?'Dar de alta':'Dar de baja';
}
function pvSelAccion(a){
  const r=_pvSel!==null?(_pvRows||[]).find(x=>x.id===_pvSel):null;
  if(!r){toast('Seleccioná un pronóstico de la lista','w');return;}
  if(a==='ver') togglePvDetalle(r.id);
  else if(a==='estado') togglePronosticoVentasEstado(r.id,r.estado);
  else if(a==='elim') eliminarPronosticoVenta(r.id,r.codigo);
}

async function togglePvDetalle(id){
  const yaAbierto = _pvActualId===id;
  if(_pvActualId!==null && _pvActualId!==id){
    const filaAnt = $('pv-detalle-row-'+_pvActualId);
    if(filaAnt) filaAnt.style.display='none';
    const btnAnt = $('pv-toggle-'+_pvActualId);
    if(btnAnt) btnAnt.textContent='▼';
  }
  const fila = $('pv-detalle-row-'+id);
  const btn = $('pv-toggle-'+id);
  if(yaAbierto){
    fila.style.display='none';
    if(btn) btn.textContent='▼';
    _pvActualId=null;
    return;
  }
  fila.style.display='table-row';
  if(btn) btn.textContent='▲';
  _pvActualId=id;
  await verPronosticoVentas(id);
}

async function openPronosticoVenta(){
  $('pv-codigo').value='';
  $('pv-estado').value='Alta';
  $('pv-fecha').value=new Date().toISOString().slice(0,10);
  $('pv-periodos').value='3';
  if(!_cli.length)_cli=await api('/api/clientes');
  $('pv-cliente').value='';
  $('pv-cliente-search').value='';
  openMo('mo-pronostico-venta');
}

function filtrarPVClientes(){
  const q=($('pv-cliente-search').value||'').toLowerCase().trim();
  const cont=$('pv-cliente-results');
  const listaConTodos=[{id:'',razon:'Todos los clientes'}].concat(
    q?_cli.filter(function(c){return (c.razon||'').toLowerCase().includes(q);}):_cli);
  _novotResultsRender(cont,listaConTodos,function(c){return c.razon;},function(c){
    $('pv-cliente').value=c.id;
    $('pv-cliente-search').value=c.id?c.razon:'';
    cont.style.display='none';cont.innerHTML='';
  });
}

async function generarPronosticoVentas(){
  const body={
    codigo:$('pv-codigo').value.trim(),
    estado:$('pv-estado').value,
    cliente_id:$('pv-cliente').value||null,
    fecha_emision:$('pv-fecha').value,
    periodos:$('pv-periodos').value
  };
  if(!body.codigo){toast('Código requerido','w');return;}
  if(!body.fecha_emision){toast('Fecha de emisión requerida','w');return;}
  const res=await api('/api/pronosticos_venta',{method:'POST',body:JSON.stringify(body)});
  if(res.ok){
    toast('Pronóstico creado');
    closeMo('mo-pronostico-venta');
    $('pv-codigo').value='';$('pv-fecha').value='';
    _pvActualId=res.id;
    await loadPronosticoVentas();
  } else toast(res.error||'Error','e');
}

async function togglePronosticoVentasEstado(id,estadoActual){
  const nuevo = estadoActual==='Alta' ? 'Baja' : 'Alta';
  const res=await api('/api/pronosticos_venta/'+id,{method:'PUT',body:JSON.stringify({estado:nuevo})});
  if(res.ok){toast('Estado actualizado');loadPronosticoVentas();}
  else toast(res.error||'Error','e');
}

async function eliminarPronosticoVenta(id,codigo){
  if(!await confirmar('¿Eliminar el pronóstico "'+codigo+'"? Esta acción no se puede deshacer.')) return;
  const res=await apiBorrar('/api/pronosticos_venta/'+id,'Pronóstico eliminado');
  if(res.ok){
    toast('Pronóstico eliminado');
    if(_pvActualId===id){_pvActualId=null;}
    loadPronosticoVentas();
  } else toast(res.error||'Error','e');
}

function _pvMesLabel(mes){
  // mes viene como 'YYYY-MM' -> mostrar 'MM/AA'
  const [y,m]=mes.split('-');
  return m+'/'+y.slice(2);
}

function _pvRecalcFila(inp){
  const tr = inp.closest('tr');
  if(!tr) return;
  const precio = parseFloat(tr.dataset.precio)||0;
  const inputs = tr.querySelectorAll('input[data-pid]');
  let total=0;
  inputs.forEach(i=>{ total += (parseFloat(i.value)||0)*precio; });
  const td = tr.querySelector('.pv-total-fila');
  if(td) td.textContent = fmtM(total);
}

async function verPronosticoVentas(id){
  const data = await api('/api/pronosticos_venta/'+id+'/tabla');
  const cont = $('pv-detalle-'+id);
  if(!cont) return;
  if(data.error){toast(data.error,'e');return;}
  const titulo = 'Pronóstico '+data.pronostico.codigo+' — '+data.pronostico.periodos+' meses'+(data.pronostico.cliente_nombre?' — '+data.pronostico.cliente_nombre:'');
  if(!data.productos.length){
    cont.innerHTML=`<div style="padding:12px"><div class="ct" style="margin-bottom:8px">${titulo}</div><div class="em">No hay productos activos para pronosticar.</div></div>`;
    return;
  }
  const esTodosClientes = !data.pronostico.cliente_nombre;
  const placeholderBuscar = esTodosClientes ? 'Buscar por código, producto o cliente...' : 'Buscar por código o producto...';
  let h=`<div style="padding:12px">`
    +`<div class="ch" style="margin-bottom:8px"><span class="ct">${titulo}</span>`
    +`<button class="btn btn-p" onclick="guardarPronosticoVentasTabla(${id})">Guardar cambios</button></div>`
    +`<div style="margin-bottom:10px"><input type="text" id="pv-buscar-${id}" placeholder="${placeholderBuscar}"`
    +` style="width:100%;max-width:320px;font-size:13px;padding:7px 10px;border:1px solid var(--color-border-tertiary);border-radius:6px;background:var(--color-background-primary);color:var(--color-text-primary)"`
    +` oninput="filtrarPronosticoVentasTabla(${id})"></div>`
    +`<div style="overflow-x:auto"><table id="pv-tabla-${id}"><tr><th>Código PZ</th><th>Cliente</th>`;
  data.meses.forEach(m=>{h+=`<th>${_pvMesLabel(m)}</th>`;});
  h+='<th>Valor total estimado</th></tr>';
  data.productos.forEach(p=>{
    h+=`<tr ${VER_MONETARIO?`data-precio="${p.precio_venta||0}"`:''}><td><b>${p.codigo}</b><div style="font-size:11px;color:var(--color-text-secondary)">${p.nombre}</div></td>`
      +`<td>${p.cliente||'—'}</td>`;
    let totalRow=0;
    data.meses.forEach(m=>{
      const cant = p.cantidades[m] ?? 0;
      totalRow += cant*(p.precio_venta||0);
      h+=`<td><input type="number" min="0" step="1" data-pid="${p.producto_id}" data-mes="${m}" value="${cant}" style="width:90px;height:30px;padding:4px 6px;border:1px solid #ddd;border-radius:6px;font-size:12px" oninput="_pvRecalcFila(this)"></td>`;
    });
    h+=`<td class="pv-total-fila" style="font-weight:600;white-space:nowrap">${fmtM(totalRow)}</td>`;
    h+='</tr>';
  });
  h+='</table></div></div>';
  cont.innerHTML=h;
}

function filtrarPronosticoVentasTabla(id){
  const q = ($('pv-buscar-'+id).value||'').toLowerCase().trim();
  const tabla = $('pv-tabla-'+id);
  if(!tabla) return;
  const filas = tabla.querySelectorAll('tr');
  filas.forEach((tr,i)=>{
    if(i===0) return; // header
    const codigoProd = (tr.cells[0] ? tr.cells[0].textContent.toLowerCase() : '');
    const cliente = (tr.cells[1] ? tr.cells[1].textContent.toLowerCase() : '');
    tr.style.display = (codigoProd.includes(q) || cliente.includes(q)) ? '' : 'none';
  });
}

async function guardarPronosticoVentasTabla(id){
  const inputs = document.querySelectorAll('#pv-tabla-'+id+' input[data-pid]');
  const items = Array.from(inputs).map(inp=>({
    producto_id: parseInt(inp.dataset.pid),
    mes: inp.dataset.mes,
    cantidad: parseFloat(inp.value)||0
  }));
  const res = await api('/api/pronosticos_venta/'+id+'/items',{method:'PUT',body:JSON.stringify({items})});
  if(res.ok) toast('Pronóstico guardado');
  else toast(res.error||'Error','e');
}

let _pronMesIds=[];

function fmtMesLabel(mes){
  const meses=['Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic'];
  const p=(mes||'').split('-');
  if(p.length!==2) return mes;
  const idx=parseInt(p[1],10)-1;
  return (meses[idx]||p[1])+' '+p[0];
}

async function consolidarPronostico(){
  const ids=[...document.querySelectorAll('.pron-chk:checked')].map(c=>parseInt(c.value));
  if(!ids.length){toast('Seleccioná al menos un pronóstico','w');return;}
  const meses=await api('/api/mrp/pronostico_meses',{method:'POST',body:JSON.stringify({pronostico_ids:ids})});
  if(!Array.isArray(meses)){toast((meses&&meses.error)||'Error','e');return;}
  if(!meses.length){toast('No hay renglones pendientes de convertir en los pronósticos seleccionados','w');return;}
  _pronMesIds=ids;
  const sel=$('pron-mes-select');
  sel.innerHTML=meses.map(m=>`<option value="${m.mes}">${fmtMesLabel(m.mes)} — ${fN(m.items_pendientes)} renglón(es), ${Math.round(m.total_qty||0)} u.</option>`).join('');
  const ocIds=[...document.querySelectorAll('.oc-chk:checked')].map(c=>parseInt(c.value));
  if(ocIds.length){
    $('pron-oc-count').textContent=ocIds.length;
    $('pron-oc-warn').style.display='block';
    $('pron-oc-incluir').checked=true;
  } else {
    $('pron-oc-warn').style.display='none';
  }
  openMo('mo-pron-mes');
}

async function confirmarConsolidarPronostico(){
  const mes=$('pron-mes-select').value;
  if(!mes){toast('Seleccioná el mes a consolidar','w');return;}
  const incluirOC=$('pron-oc-warn').style.display!=='none' && $('pron-oc-incluir').checked;
  const ocIds=incluirOC?[...document.querySelectorAll('.oc-chk:checked')].map(c=>parseInt(c.value)):[];
  const msgConfirm=ocIds.length
    ? `¿Consolidar hasta el mes ${fmtMesLabel(mes)} (incluye meses anteriores pendientes) junto con ${ocIds.length} pedido(s) de cliente, y generar OTs automáticamente?`
    : `¿Consolidar hasta el mes ${fmtMesLabel(mes)} (incluye meses anteriores pendientes) y generar OTs automáticamente?`;
  if(!await confirmar(msgConfirm))return;
  let msgs=[], aviso=false;
  if(ocIds.length){
    const resOc=await api('/api/mrp/consolidar',{method:'POST',body:JSON.stringify({oc_ids:ocIds})});
    if(!resOc.ok){
      // Si fallan los pedidos no se sigue con el pronóstico: el usuario
      // eligió consolidar las dos cosas juntas.
      toast('Error al consolidar pedidos, no se consolidó el pronóstico: '+(resOc.error||'Error'),'e');
      loadMRP();
      return;
    }
    const numsOc=resOc.ots.map(o=>o.numero+' ('+o.producto+' x'+fN(o.cantidad)+')').join(', ');
    msgs.push('OTs de pedidos: '+numsOc+_mrpExtras(resOc));
    aviso=aviso||!!(resOc.avisos&&resOc.avisos.length);
  }
  const res=await api('/api/mrp/consolidar_pronostico',{method:'POST',body:JSON.stringify({pronostico_ids:_pronMesIds,mes})});
  if(res.ok){
    closeMo('mo-pron-mes');
    const mesesInc=[...new Set(res.ots.map(o=>o.mes))].sort();
    const nums=res.ots.map(o=>o.numero+' ('+o.producto+' x'+fN(o.cantidad)+', '+fmtMesLabel(o.mes)+')').join(', ');
    msgs.push('OTs de pronóstico — meses '+mesesInc.map(fmtMesLabel).join(', ')+': '+nums+_mrpExtras(res));
    aviso=aviso||!!(res.avisos&&res.avisos.length);
    toast(msgs.join(' — '),aviso?'w':undefined);
  } else if(msgs.length){
    // Los pedidos sí se consolidaron: se muestra lo que se generó y el error.
    closeMo('mo-pron-mes');
    toast(msgs.join(' — ')+' — Error en el pronóstico, no se generó nada de él: '+(res.error||'Error'),'e');
  } else toast(res.error||'Error','e');
  loadMRP();
}


async function loadCli(){
  _cli=await api('/api/clientes');
  _cliProdCache={};
  renderCli();
}

// Selección de cliente + barra de herramientas (mismo patrón que Proveedores /
// OT): radio por fila, clic selecciona, doble clic edita (o abre los productos
// si el rol no puede editar).
let _cliSel=null, _cliF='';
function _cliPuedeEditar(){ return ['admin','operario'].includes(ROL); }
function renderCli(){
  const el=$('cli-list');
  if(!el) return;
  if(!_cli.length){el.innerHTML='<div class="em">No hay clientes. Usá «Nuevo cliente» para cargar el primero.</div>';_cliSel=null;actualizarToolbarCli();return;}
  const q=($('cli-search')?$('cli-search').value:'').trim().toLowerCase();
  let list=_cli;
  if(_cliF) list=list.filter(function(r){return (r.categoria||'')===_cliF;});
  if(q) list=list.filter(function(r){
    return (r.razon||'').toLowerCase().includes(q)
      ||(r.cuit||'').toLowerCase().includes(q)
      ||(r.contacto||'').toLowerCase().includes(q)
      ||(r.email||'').toLowerCase().includes(q);
  });
  if(_cliSel && !_cli.some(function(c){return c.id===_cliSel;})) _cliSel=null;
  if(!list.length){
    el.innerHTML='<div class="em">'+(q?'No se encontraron clientes para "'+q+'".':'No hay clientes para el filtro seleccionado.')+'</div>';
    actualizarToolbarCli();return;
  }
  const cm={Premium:'bb',Institucional:'bp',Regular:'bk',Nuevo:'bg'};
  const canEditCli=_cliPuedeEditar();
  const tbl=document.createElement('table');
  tbl.innerHTML='<tr><th style="width:24px"></th><th>Razón social</th><th>CUIT</th><th>Contacto</th><th>Teléfono</th><th>Email</th><th>Categoría</th><th>Plazo pago</th></tr>';
  const tbody=document.createElement('tbody');
  list.forEach(r=>{
    const tr=document.createElement('tr');
    tr.id='clirow-'+r.id;
    tr.style.cursor='pointer';
    tr.title=canEditCli?'Doble clic: editar el cliente':'Doble clic: ver los productos del cliente';
    if(_cliSel===r.id) tr.className='ot-sel';
    tr.innerHTML='<td style="white-space:nowrap"><input type="radio" name="cli-sel" '+(_cliSel===r.id?'checked':'')+'> <button class="btn btn-s" style="padding:2px 5px;font-size:11px" title="Ver productos del cliente">▶</button></td>'
      +'<td><b>'+r.razon+'</b></td>'
      +'<td>'+(r.cuit||'—')+'</td>'
      +'<td>'+(r.contacto||'—')+'<br><span style="font-size:11px;color:var(--color-text-secondary)">'+(r.cargo||'')+'</span></td>'
      +'<td>'+(r.telefono||'—')+'</td>'
      +'<td>'+(r.email||'—')+'</td>'
      +'<td><span class="b '+(cm[r.categoria]||'bk')+'">'+r.categoria+'</span></td>'
      +'<td>'+(r.plazo_pago||'—')+'</td>';
    tr.onclick=function(){ selCli(r.id); };
    tr.ondblclick=function(){ selCli(r.id); cliSelAccion(canEditCli?'edit':'prod'); };
    tr.querySelector('input[type=radio]').onclick=function(e){ e.stopPropagation(); selCli(r.id); };
    const bExp=tr.querySelector('td:first-child button');
    bExp.onclick=function(e){ e.stopPropagation(); selCli(r.id); toggleProductosCliente(r.id); };
    bExp.ondblclick=function(e){ e.stopPropagation(); };
    tbody.appendChild(tr);
    // Hidden detail row
    const trDet=document.createElement('tr');
    trDet.id='cliprod-'+r.id; trDet.style.display='none';
    const tdDet=document.createElement('td'); tdDet.colSpan=8; tdDet.style.padding='0';
    const div=document.createElement('div');
    div.id='cliprod-body-'+r.id;
    div.style.cssText='padding:8px 12px 10px 32px;background:var(--color-background-secondary);font-size:11px';
    div.innerHTML='<div class="ld">Cargando...</div>';
    tdDet.appendChild(div); trDet.appendChild(tdDet); tbody.appendChild(trDet);
  });
  tbl.appendChild(tbody);
  el.innerHTML=''; el.appendChild(tbl);
  actualizarToolbarCli();
}
function selCli(id){
  _cliSel=id;
  document.querySelectorAll('#cli-list tr.ot-sel').forEach(function(tr){tr.classList.remove('ot-sel');});
  const tr=document.getElementById('clirow-'+id);
  if(tr){
    tr.classList.add('ot-sel');
    const rd=tr.querySelector('input[type=radio]'); if(rd) rd.checked=true;
  }
  actualizarToolbarCli();
}
function actualizarToolbarCli(){
  const r=_cliSel?_cli.find(function(c){return c.id===_cliSel;}):null;
  const lbl=$('cli-sel-label');
  if(lbl){
    const t=r?(r.razon||'#'+r.id):'–';
    lbl.textContent=t.length>28?t.slice(0,27)+'…':t;
    lbl.title=r?t:'Cliente seleccionado';
  }
  const be=$('cli-b-edit');
  if(be){ be.style.display=_cliPuedeEditar()?'':'none'; be.disabled=!r; }
  const bp=$('cli-b-prod'); if(bp) bp.disabled=!r;
}
function cliSelAccion(a){
  const r=_cliSel?_cli.find(function(c){return c.id===_cliSel;}):null;
  if(!r){toast('Seleccioná un cliente de la lista','w');return;}
  if(a==='edit') editCli(r);
  else if(a==='prod') toggleProductosCliente(r.id);
}
function nuevoCli(){
  ['cli-id','cli-raz','cli-cui','cli-rub','cli-loc','cli-dir','cli-con','cli-car','cli-tel','cli-ema','cli-pla','cli-obs'].forEach(function(k){if($(k))$(k).value='';});
  if($('cli-iva')) $('cli-iva').value='';
  if($('cli-cat')) $('cli-cat').value='Regular';
  openMo('mo-cli');
}
function clearFiltrosCli(){
  if($('cli-search'))$('cli-search').value='';
  _cliF='';
  document.querySelectorAll('#cli-tabs .tab').forEach(x=>x.classList.toggle('active',x.dataset.c===''));
  renderCli();
}
document.querySelectorAll('#cli-tabs .tab').forEach(t=>t.addEventListener('click',()=>{
  document.querySelectorAll('#cli-tabs .tab').forEach(x=>x.classList.remove('active'));
  t.classList.add('active');
  _cliF=t.dataset.c||'';
  renderCli();
}));

let _cliProdCache={};

async function toggleProductosCliente(cid){
  const row=document.getElementById('cliprod-'+cid);
  const btn=document.querySelector('#clirow-'+cid+' td:first-child button');
  if(!row) return;
  const vis=row.style.display==='none'||row.style.display==='';
  row.style.display=vis?'table-row':'none';
  if(btn) btn.textContent=vis?'▼':'▶';
  if(!vis) return;
  const body=document.getElementById('cliprod-body-'+cid);
  if(body.dataset.loaded==='1') return; // ya cargado, no reconsultar
  try{
    const prods=await api('/api/productos?cliente_id='+cid);
    _cliProdCache[cid]=prods||[];
    if(!prods||!prods.length){
      body.innerHTML='<div class="em">Este cliente no tiene productos asociados.</div>';
      body.dataset.loaded='1';
      return;
    }
    body.innerHTML='<input type="text" id="cliprod-search-'+cid+'" placeholder="🔍 Buscar por código, nombre o categoría..." oninput="renderProductosCliente('+cid+')" style="margin-bottom:8px;padding:6px 10px;font-size:11px;border:1.5px solid #c7c7c0;border-radius:6px;outline:none;background:#fff;width:100%;max-width:320px">'
      +'<div id="cliprod-table-'+cid+'"></div>';
    renderProductosCliente(cid);
    body.dataset.loaded='1';
  }catch(e){
    body.innerHTML='<div class="al al-e"><strong>Error</strong> al cargar los productos del cliente</div>';
    console.error(e);
  }
}

function renderProductosCliente(cid){
  const cont=document.getElementById('cliprod-table-'+cid);
  if(!cont) return;
  const all=_cliProdCache[cid]||[];
  const searchEl=document.getElementById('cliprod-search-'+cid);
  const q=(searchEl?searchEl.value:'').trim().toLowerCase();
  const prods=q?all.filter(function(p){
    return (p.codigo||'').toLowerCase().includes(q)
      ||(p.nombre||'').toLowerCase().includes(q)
      ||(p.categoria_nombre||'').toLowerCase().includes(q);
  }):all;
  if(!prods.length){
    cont.innerHTML='<div class="em">No se encontraron productos para "'+q+'".</div>';
    return;
  }
  let h='<table style="font-size:11px"><tr><th>Código</th><th>Nombre</th><th>Categoría</th><th>Precio de venta</th><th>Precio OC más reciente</th><th>Estado</th></tr>';
  prods.forEach(function(p){
    const ocTxt=(p.oc_precio_reciente!=null)
      ?'<b>'+fmtMD(p.oc_precio_reciente)+'</b> <span style="color:var(--color-text-secondary)">'+(VER_MONETARIO?('('+(p.oc_numero_reciente||'')+(p.oc_fecha_reciente?' · '+fmtD(p.oc_fecha_reciente):'')+')'):'')+'</span>'
      :'<span style="color:var(--color-text-secondary)">Sin OC</span>';
    h+='<tr>'
      +'<td><b>'+p.codigo+'</b></td>'
      +'<td>'+p.nombre+'</td>'
      +'<td>'+(p.categoria_nombre||'—')+'</td>'
      +'<td><b>'+fmtM(p.precio_venta||0)+'</b></td>'
      +'<td>'+ocTxt+'</td>'
      +'<td>'+(p.activo?'<span class="b bg">Activo</span>':'<span class="b bk">Inactivo</span>')+'</td>'
      +'</tr>';
  });
  cont.innerHTML=h+'</table>';
}

async function saveCli(){
  const id=$('cli-id').value;
  const body={razon:$('cli-raz').value,cuit:$('cli-cui').value,iva:$('cli-iva').value,
    rubro:$('cli-rub').value,localidad:$('cli-loc').value,direccion:$('cli-dir').value,
    contacto:$('cli-con').value,cargo:$('cli-car').value,telefono:$('cli-tel').value,
    email:$('cli-ema').value,categoria:$('cli-cat').value,plazo_pago:$('cli-pla').value,obs:$('cli-obs').value};
  if(!body.razon||!body.cuit||!body.contacto){toast('Razón, CUIT y contacto requeridos','w');return;}
  const res=await api(id?'/api/clientes/'+id:'/api/clientes',{method:id?'PUT':'POST',body:JSON.stringify(body)});
  if(res.ok){toast(id?'Cliente actualizado':'Cliente registrado');closeMo('mo-cli');$('cli-id').value='';_cli=[];loadCli();}
  else toast(res.error||'Error','e');
}


// ── Novedades por OT ──────────────────────────────────────────────────────────
async function openNovEdit(novId){
  const nov = await api('/api/novedades/'+novId).catch(function(){return null;});
  if(!nov){ toast('Novedad no encontrada','e'); return; }
  const oid = nov.orden_id;
  $('nov-oid').value = oid;
  // Acá sí se puede elegir entre todas las operaciones de la OT, así que
  // el select vuelve a mostrarse (puede haber quedado oculto si el modal
  // se abrió antes desde Control de producción)
  const wrap=$('nov-op-wrap');
  if(wrap) wrap.style.display='';
  const titleEl=$('nov-op-title');
  if(titleEl) titleEl.textContent='';
  // Cargar operaciones en el select (solo las normales: una operación
  // tercerizada no declara Novedad de producción propia, se completa sola
  // cuando vuelve el lote del proveedor — ver update_ot_operacion en el
  // backend, que ya la bloquea a mano por el mismo motivo).
  const ops = (await api('/api/ordenes/'+oid+'/operaciones')).filter(function(op){return !op.es_tercerizada;});
  const sel = $('nov-op');
  sel.innerHTML = '';
  ops.forEach(function(op){
    const opt=document.createElement('option');
    opt.value=op.id;
    opt.textContent=op.orden+'. '+op.nombre+' (ciclo: '+op.tiempo_ciclo_seg+' seg)';
    sel.appendChild(opt);
  });
  sel.value = nov.operacion_id||nov.orden_operacion_id||'';
  sel.onchange=function(){
    const opSel=ops.find(function(o){return o.id==sel.value;});
    checkNovCiclo(opSel);
    loadNovCajones(oid, sel.value, sel.value==nov.orden_operacion_id?nov.cajones:null);
    // Si se cambia de operación, se precarga la máquina específica de ese
    // proceso (el usuario puede pisarla a mano si corresponde otra).
    setNovMaquina((opSel&&opSel.maquina_id)?opSel.maquina_id:'');
  };
  checkNovCiclo(ops.find(function(o){return o.id==sel.value;}));
  // La edición no re-gestiona lotes (solo ajusta stock agregado/quitado);
  // ocultamos el selector de lotes para no confundir.
  $('nov-lotes-wrap').style.display='none';
  $('nov-lotes-list').innerHTML='';
  _novMatsReq=[];
  // Cargar empleados siempre
  if(!_emp.length) _emp = await api('/api/empleados');
  // Cargar máquinas siempre
  if(!_maq.length) _maq = await api('/api/maquinas');
  setNovMaquina(nov.maquina_id||'');
  // Setear valores de la novedad
  $('nov-qty').value = nov.cantidad_producida||1;
  if($('nov-tmin')) $('nov-tmin').value = nov.tiempo_real_min?(Math.round((nov.tiempo_real_min/60)*100)/100):'';
  if($('nov-tur')) $('nov-tur').value = nov.turno||'';
  if($('nov-fecha')) $('nov-fecha').value = (nov.fecha||'').slice(0,10);
  if($('nov-obs')) $('nov-obs').value = nov.obs||'';
  setNovEmpleado(nov.empleado_id||'');
  await loadNovCajones(oid, nov.orden_operacion_id, nov.cajones);
  // Marcar como edicion
  $('nov-oid').dataset.editId = novId;
  $('nov-del-btn').style.display='';
  openMo('mo-nov');
}

async function deleteNovFromModal(){
  const editId = $('nov-oid').dataset&&$('nov-oid').dataset.editId;
  if(!editId){ toast('No hay una novedad para eliminar','e'); return; }
  if(!await confirmar('¿Eliminar esta novedad? Se revertirán sus efectos en stock (materiales consumidos y producto terminado generado). Esta acción no se puede deshacer.')) return;
  try{
    await api('/api/novedades/'+editId,{method:'DELETE'});
    toast('Novedad eliminada','g');
    delete $('nov-oid').dataset.editId;
    closeMo('mo-nov');
    // Refrescar listados relevantes si están cargados/visibles
    if(typeof loadNovOT==='function') loadNovOT();
    if(typeof loadCtrlProd==='function') loadCtrlProd();
  }catch(e){
    toast(e.message||'Error al eliminar la novedad','e');
  }
}

async function loadNovOTList(){
  // Cache raw data used by the searchable filters (OT, empleado, producto, máquina)
  if(!_novOTOrdenes.length) _novOTOrdenes=await api('/api/ordenes');
  if(!_emp.length)_emp=await api('/api/empleados');
  if(!_prod.length)_prod=await api('/api/productos');
  if(!_maq.length)_maq=await api('/api/maquinas');
  if(!_cli.length)_cli=await api('/api/clientes');
  loadNovOT();
}
let _novOTOrdenes=[];
let _novCorrPreview=[];

function clearNovOTFiltros(){
  $('novot-ot-fil').value='';$('novot-ot-search').value='';
  _setNovOTOperacionesSel(null);
  $('novot-emp-fil').value='';$('novot-emp-search').value='';
  $('novot-prod-fil').value='';$('novot-prod-search').value='';
  cliBuscadorClear('novot-cli-fil');
  $('novot-maq-fil').value='';$('novot-maq-search').value='';
  $('novot-fdesde-fil').value='';
  $('novot-fhasta-fil').value='';
  $('novot-oculta-comp').checked=true;
  loadNovOT();
}
function updateNovOTFiltrosBadge(){
  // Ya no hay botón "Filtros" con badge (los filtros quedaron siempre
  // visibles arriba de la tabla) — se mantiene la función vacía por si
  // queda alguna referencia, para no romper nada.
}

// ── Buscador genérico de Cliente (reemplaza <select> por autocompletar) ───
// baseId es el id del input hidden que guarda el cliente_id elegido (el
// mismo id que antes tenía el <select>, para no romper el resto del código
// que lee/escribe $('baseId').value). El input de texto visible es
// baseId+'-search' y el desplegable de resultados baseId+'-results'.
async function filtrarClienteBuscador(baseId, todosLabel, onChangeFnName){
  if(!_cli.length)_cli=await api('/api/clientes');
  const q=($(baseId+'-search').value||'').toLowerCase().trim();
  const cont=$(baseId+'-results');
  const lista=q?_cli.filter(function(c){return (c.razon||'').toLowerCase().includes(q);})
    :_cli.slice().sort(function(a,b){return (a.razon||'').localeCompare(b.razon||'');});
  const listaFinal=todosLabel?[{id:'',razon:todosLabel},...lista]:lista;
  _novotResultsRender(cont,listaFinal,function(c){return c.razon;},function(c){
    $(baseId).value=c.id;
    $(baseId+'-search').value=c.id?c.razon:'';
    cont.style.display='none';cont.innerHTML='';
    if(onChangeFnName && window[onChangeFnName]) window[onChangeFnName]();
  });
}
// Fija el valor del buscador de cliente a partir de un cliente_id (para
// precargar el campo al editar un registro existente).
function cliBuscadorSet(baseId, cid){
  const c=_cli.find(function(x){return x.id==cid||x.id==parseInt(cid);});
  $(baseId).value=cid||'';
  $(baseId+'-search').value=c?c.razon:'';
}
function cliBuscadorClear(baseId){
  $(baseId).value='';
  $(baseId+'-search').value='';
}

// ── Buscadores del panel de Filtros de Novedades por OT ───────────────────
function _novotResultsRender(cont, lista, formatFn, onPick){
  if(!lista.length){
    cont.innerHTML='<div style="padding:8px 10px;font-size:12px;color:#999">Sin resultados</div>';
    cont.style.display='block';
    return;
  }
  cont.innerHTML='';
  lista.slice(0,30).forEach(function(item){
    const div=document.createElement('div');
    div.textContent=formatFn(item);
    div.style.cssText='padding:7px 10px;font-size:13px;cursor:pointer';
    div.onmouseenter=function(){this.style.background='#f4f4f2';};
    div.onmouseleave=function(){this.style.background='';};
    div.onmousedown=function(ev){ ev.preventDefault(); onPick(item); };
    cont.appendChild(div);
  });
  cont.style.display='block';
}

// Puebla el select de Operación según la OT elegida en el filtro de Novedades por OT.
// Si no hay OT seleccionada, el select queda deshabilitado y vacío (la operación
// solo puede filtrarse una vez elegida la OT).
async function _setNovOTOperacionesSel(oid){
  const sel=$('novot-op-fil');
  sel.value='';
  if(!oid){
    sel.innerHTML='<option value="">Elegí primero una OT</option>';
    sel.disabled=true;
    return;
  }
  sel.disabled=true;
  sel.innerHTML='<option value="">Cargando...</option>';
  const ops=await api('/api/ordenes/'+oid+'/operaciones').catch(function(){return [];});
  sel.innerHTML='<option value="">Todas las operaciones</option>';
  (ops||[]).forEach(function(o){
    const opt=document.createElement('option');
    opt.value=o.id;
    opt.textContent=(o.orden!=null?o.orden+' — ':'')+(o.nombre||o.operacion_nombre||'');
    sel.appendChild(opt);
  });
  sel.disabled=false;
}

function filtrarNovOTOts(){
  const q=($('novot-ot-search').value||'').toLowerCase().trim();
  $('novot-ot-fil').value='';
  const cont=$('novot-ot-results');
  if(!q){cont.style.display='none';cont.innerHTML='';_setNovOTOperacionesSel(null);loadNovOT();return;}
  const lista=_novOTOrdenes.filter(function(r){
    return (r.numero||'').toLowerCase().includes(q);
  });
  _novotResultsRender(cont,lista,function(r){return r.numero+' — '+(r.producto_codigo||r.producto_nombre||r.descripcion||'');},function(r){
    $('novot-ot-fil').value=r.id;
    $('novot-ot-search').value=r.numero+' — '+(r.producto_codigo||r.producto_nombre||r.descripcion||'');
    cont.style.display='none';cont.innerHTML='';
    _setNovOTOperacionesSel(r.id);
    loadNovOT();
  });
}

function filtrarNovOTEmpleados(){
  const q=($('novot-emp-search').value||'').toLowerCase().trim();
  $('novot-emp-fil').value='';
  const cont=$('novot-emp-results');
  if(!q){cont.style.display='none';cont.innerHTML='';loadNovOT();return;}
  const lista=_emp.filter(function(e){
    const full1=(e.nombre+' '+e.apellido).toLowerCase();
    const full2=(e.apellido+' '+e.nombre).toLowerCase();
    return full1.includes(q)||full2.includes(q);
  });
  _novotResultsRender(cont,lista,function(e){return e.apellido+', '+e.nombre;},function(e){
    $('novot-emp-fil').value=e.id;
    $('novot-emp-search').value=e.apellido+', '+e.nombre;
    cont.style.display='none';cont.innerHTML='';
    loadNovOT();
  });
}

function filtrarOTProductos(){
  const q=($('ot-prod-search').value||'').toLowerCase().trim();
  const cont=$('ot-prod-results');
  if(!q){cont.style.display='none';cont.innerHTML='';return;}
  const lista=_prod.filter(function(p){
    const full=((p.codigo||'')+' '+(p.nombre||'')).toLowerCase();
    return full.includes(q);
  });
  _novotResultsRender(cont,lista,function(p){return p.codigo+' — '+p.nombre;},function(p){
    $('ot-prod').value=p.id;
    $('ot-prod-search').value=p.codigo+' — '+p.nombre;
    cont.style.display='none';cont.innerHTML='';
    onOTProdChange();
  });
}

function filtrarNovOTProductos(){
  const q=($('novot-prod-search').value||'').toLowerCase().trim();
  $('novot-prod-fil').value='';
  const cont=$('novot-prod-results');
  if(!q){cont.style.display='none';cont.innerHTML='';loadNovOT();return;}
  const lista=_prod.filter(function(p){
    const full=((p.codigo||'')+' '+(p.nombre||'')).toLowerCase();
    return full.includes(q);
  });
  _novotResultsRender(cont,lista,function(p){return p.codigo+' — '+p.nombre;},function(p){
    $('novot-prod-fil').value=p.id;
    $('novot-prod-search').value=p.codigo+' — '+p.nombre;
    cont.style.display='none';cont.innerHTML='';
    loadNovOT();
  });
}

function filtrarNovOTMaquinas(){
  const q=($('novot-maq-search').value||'').toLowerCase().trim();
  $('novot-maq-fil').value='';
  const cont=$('novot-maq-results');
  if(!q){cont.style.display='none';cont.innerHTML='';loadNovOT();return;}
  const lista=_maq.filter(function(m){
    const full=((m.codigo||'')+' '+(m.nombre||'')).toLowerCase();
    return full.includes(q);
  });
  _novotResultsRender(cont,lista,function(m){return m.codigo+' — '+m.nombre;},function(m){
    $('novot-maq-fil').value=m.id;
    $('novot-maq-search').value=m.codigo+' — '+m.nombre;
    cont.style.display='none';cont.innerHTML='';
    loadNovOT();
  });
}

// ── Orden de la tabla de novedades por OT ─────────────────────────────────
let _novOTSortCol='numero', _novOTSortDir='desc';
function novOTSortKey(n,col){
  switch(col){
    case 'numero': return n.numero;
    case 'ot_numero': return (n.ot_numero||'').toLowerCase();
    case 'producto_nombre': return (n.producto_codigo||n.producto_nombre||'').toLowerCase();
    case 'cliente_nombre': return (n.cliente_nombre||'').toLowerCase();
    case 'operacion_nombre': return (n.op_orden!=null?String(n.op_orden).padStart(6,'0'):'')+(n.operacion_nombre||'').toLowerCase();
    case 'empleado_nombre': return (n.empleado_nombre||'').toLowerCase();
    case 'maquina_nombre': return (n.maquina_nombre||'').toLowerCase();
    case 'cantidad_producida': return parseFloat(n.cantidad_producida||0);
    case 'piezas_observadas': return parseFloat(n.piezas_observadas||0);
    case 'cajones_txt': return (n.cajones_txt||'').toLowerCase();
    case 'tiempo_real_min': return parseFloat(n.tiempo_real_min||0);
    case 'rendimiento_pct': return parseFloat(n.rendimiento_pct||0);
    case 'desvio': return n.desvio?1:0;
    case 'fecha': return n.fecha||'';
    default: return '';
  }
}
function sortNovOT(col){
  if(_novOTSortCol===col){
    _novOTSortDir=_novOTSortDir==='asc'?'desc':'asc';
  } else {
    _novOTSortCol=col;_novOTSortDir='asc';
  }
  loadNovOT();
}

async function loadNovOT(){
  updateNovOTFiltrosBadge();
  const oid=$('novot-ot-fil').value;
  // El filtro de Operación solo tiene sentido si ya se eligió una OT (el select
  // se puebla y habilita recién ahí); si por algún motivo hay un valor cargado
  // sin OT seleccionada, se ignora.
  const opId=oid?$('novot-op-fil').value:'';
  const empId=$('novot-emp-fil').value;
  const prodId=$('novot-prod-fil').value;
  const cliId=$('novot-cli-fil').value;
  const maqId=$('novot-maq-fil').value;
  const fdesde=$('novot-fdesde-fil').value;
  const fhasta=$('novot-fhasta-fil').value;
  const ocultarComp=$('novot-oculta-comp').checked;

  const p=[];
  if(oid) p.push('orden_id='+oid);
  if(opId) p.push('operacion_id='+opId);
  if(empId) p.push('empleado_id='+empId);
  if(prodId) p.push('producto_id='+prodId);
  if(cliId) p.push('cliente_id='+cliId);
  if(maqId) p.push('maquina_id='+maqId);
  if(fdesde) p.push('fecha_desde='+fdesde);
  if(fhasta) p.push('fecha_hasta='+fhasta);
  if(ocultarComp) p.push('ocultar_completadas=1');

  const rows=await api('/api/novedades'+(p.length?'?'+p.join('&'):''));

  if(oid){
    const ot=await api('/api/ordenes/'+oid).then(function(d){return d;}).catch(function(){return null;});
    if(ot&&ot.id){
      $('novot-info').innerHTML='<b>'+ot.numero+'</b> — '+(ot.producto_nombre||'—')+' | Cliente: '+(ot.cliente_nombre||'—')+' | Cantidad: '+fN(ot.cantidad)+' | Estado: '+sb(ot.estado);
    }
  } else {
    $('novot-info').innerHTML='';
  }

  _novOTData=rows;
  renderNovOTTable();
}

// ── Selección de novedad + barra de herramientas de Novedades por OT ──────
let _novOTData=[];
let _novOTSel=null;
function selNovOT(id){ _novOTSel=id; renderNovOTTable(); }
function actualizarToolbarNovOT(){
  const r=_novOTSel?_novOTData.find(function(x){return x.id===_novOTSel;}):null;
  const puede=['admin','operario'].includes(ROL);
  const lbl=$('novot-sel-label'); if(lbl) lbl.textContent=r?r.numero:'–';
  const be=$('novot-b-edit');
  if(be){ be.style.display=puede?'':'none'; be.disabled=!r||!puede; }
}
function novOTSelAccion(a){
  const r=_novOTSel?_novOTData.find(function(x){return x.id===_novOTSel;}):null;
  if(!r){toast('Seleccioná una novedad de la lista','w');return;}
  if(a==='edit') openNovEdit(r.id);
}

function renderNovOTTable(){
  const rows=_novOTData.slice();
  // Si la novedad seleccionada ya no está en la lista (filtros / recarga), se deselecciona.
  if(_novOTSel && !rows.some(function(r){return r.id===_novOTSel;})) _novOTSel=null;
  if(!rows.length){
    actualizarToolbarNovOT();
    $('novot-list').innerHTML='<div class="em">Sin novedades para los filtros seleccionados.</div>';
    return;
  }
  // Ordenar filas según columna/dirección seleccionada
  rows.sort(function(a,b){
    const ka=novOTSortKey(a,_novOTSortCol), kb=novOTSortKey(b,_novOTSortCol);
    let cmp;
    if(typeof ka==='number'&&typeof kb==='number') cmp=ka-kb;
    else cmp=String(ka).localeCompare(String(kb),'es',{numeric:true});
    return _novOTSortDir==='asc'?cmp:-cmp;
  });
  function th(label,col){
    const arrow=_novOTSortCol===col?(_novOTSortDir==='asc'?' ▲':' ▼'):'';
    return '<th style="cursor:pointer;user-select:none" onclick="sortNovOT(\''+col+'\')" title="Ordenar">'+label+arrow+'</th>';
  }
  let h='<table><tr><th style="width:24px"></th>'
    +th('N°','numero')+th('OT','ot_numero')+th('Producto','producto_nombre')+th('Cliente','cliente_nombre')
    +th('Operación','operacion_nombre')+th('Empleado','empleado_nombre')+th('Máquina','maquina_nombre')
    +th('Cant. (OK)','cantidad_producida')+th('No OK','piezas_observadas')+th('Cajón(es)','cajones_txt')+th('Tiempo real','tiempo_real_min')
    +th('Rendimiento','rendimiento_pct')+th('Desvío','desvio')+th('Fecha','fecha')
    +'</tr>';
  rows.forEach(function(n){
    const rc=n.rendimiento_pct>=95?'bg':n.rendimiento_pct>=80?'ba':'br';
    const nok=parseFloat(n.piezas_observadas||0);
    h+='<tr class="'+(_novOTSel===n.id?'ot-sel':'')+'" style="cursor:pointer" onclick="selNovOT('+n.id+')">'
      +'<td><input type="radio" name="novot-sel"'+(_novOTSel===n.id?' checked':'')+' onclick="event.stopPropagation();selNovOT('+n.id+')"></td>'
      +'<td><b>'+n.numero+'</b></td>'
      +'<td><a href="#" onclick="event.stopPropagation();goToNovOT('+n.orden_id+');return false;" style="color:var(--color-text-info);text-decoration:none;font-weight:600">'+(n.ot_numero||'—')+'</a></td>'
      +'<td>'+(n.producto_codigo||n.producto_nombre||'—')+'</td>'
      +'<td>'+(n.cliente_nombre||'—')+'</td>'
      +'<td>'+(n.op_orden!=null?n.op_orden+'- ':'')+n.operacion_nombre+'</td>'
      +'<td>'+(n.empleado_nombre||'—')+'</td>'
      +'<td>'+(n.maquina_nombre||'—')+'</td>'
      +'<td>'+fN(n.cantidad_producida)+'</td>'
      +'<td>'+(nok>0?'<span class="b br">'+nok+'</span>':'<span style="color:var(--color-text-secondary)">0</span>')+'</td>'
      +'<td style="font-size:11px">'+(n.cajones_txt?schEsc(n.cajones_txt):'—')+'</td>'
      +'<td>'+(Math.round((parseFloat(n.tiempo_real_min||0)/60)*100)/100)+'h</td>'
      +'<td><span class="b '+rc+'">'+n.rendimiento_pct+'%</span></td>'
      +'<td>'+(n.desvio?'<span class="b br">Desvío</span>':'<span class="b bg">OK</span>')+'</td>'
      +'<td>'+fmtD(n.fecha)+'</td>'
      +'</tr>';
  });
  // Summary row
  const totalProd=rows.reduce(function(s,n){return s+parseFloat(n.cantidad_producida||0);},0);
  const totalNOK=rows.reduce(function(s,n){return s+parseFloat(n.piezas_observadas||0);},0);
  const totalTmin=rows.reduce(function(s,n){return s+parseFloat(n.tiempo_real_min||0);},0);
  const avgRend=rows.length?Math.round(rows.reduce(function(s,n){return s+parseFloat(n.rendimiento_pct||0);},0)/rows.length):0;
  const rendCol=avgRend>=95?'bg':avgRend>=80?'ba':'br';
  h+='<tr style="font-weight:600;background:var(--color-background-secondary)">'
    +'<td colspan="8">Totales</td>'
    +'<td>'+totalProd+'</td><td>'+(totalNOK>0?'<span class="b br">'+totalNOK+'</span>':'<span style="color:var(--color-text-secondary)">0</span>')+'</td><td></td><td>'+totalTmin+'min</td>'
    +'<td><span class="b '+rendCol+'">'+avgRend+'% prom.</span></td>'
    +'<td colspan="2">'+rows.length+' novedades</td>'
    +'</tr>';
  $('novot-list').innerHTML=h+'</table>';
  actualizarToolbarNovOT();
}

// ── Corrección masiva de rendimiento de novedades ──────────────────────────
async function abrirCorregirNovedades(){
  openMo('mo-novot-corr');
  $('novot-corr-confirm-btn').style.display='none';
  $('novot-corr-body').innerHTML='<div class="ld">Analizando...</div>';
  let res;
  try{
    res = await api('/api/novedades/corregir_rendimiento');
  }catch(e){
    $('novot-corr-body').innerHTML='<div class="em">Error al analizar las novedades.</div>';
    return;
  }
  _novCorrPreview = res.afectadas||[];
  if(!_novCorrPreview.length){
    $('novot-corr-body').innerHTML='<div class="em">No hay novedades para corregir. Todos los rendimientos ya están calculados correctamente.</div>';
    return;
  }
  let h='<div style="margin-bottom:10px">Se van a corregir <b>'+_novCorrPreview.length+'</b> novedad(es):</div>';
  h+='<div style="max-height:320px;overflow-y:auto"><table class="tbl"><thead><tr>'
    +'<th>Novedad</th><th>Rendimiento actual</th><th>Rendimiento nuevo</th><th>Desvío</th></tr></thead><tbody>';
  _novCorrPreview.forEach(function(n){
    h+='<tr><td>'+n.numero+'</td>'
      +'<td>'+n.rendimiento_actual+'%</td>'
      +'<td><b>'+n.rendimiento_nuevo+'%</b></td>'
      +'<td>'+(n.desvio_actual!==n.desvio_nuevo?(n.desvio_nuevo?'→ Desvío':'→ OK'):(n.desvio_nuevo?'Desvío':'OK'))+'</td>'
      +'</tr>';
  });
  h+='</tbody></table></div>';
  $('novot-corr-body').innerHTML=h;
  $('novot-corr-confirm-btn').style.display='';
}

async function confirmarCorregirNovedades(){
  if(!_novCorrPreview||!_novCorrPreview.length) return;
  if(!await confirmar('¿Confirmás la corrección de '+_novCorrPreview.length+' novedad(es)? Esta acción no se puede deshacer.')) return;
  try{
    const res = await api('/api/novedades/corregir_rendimiento', {method:'POST'});
    toast(res.corregidas+' novedad(es) corregida(s) correctamente.','s');
    closeMo('mo-novot-corr');
    loadNovOTList();
  }catch(e){
    toast('Error al aplicar la corrección','e');
  }
}

function goToNovOT(otId){
  // Navigate to novedades_ot page and filter by this OT
  document.querySelectorAll('.ni').forEach(function(n){n.classList.remove('active');});
  document.querySelectorAll('.page').forEach(function(p){p.classList.remove('active');});
  const nav=document.querySelector('[data-p="novedades_ot"]');
  if(nav) nav.classList.add('active');
  const page=$('p-novedades_ot');
  if(page) page.classList.add('active');
  function applyFiltro(){
    const ot=_novOTOrdenes.find(function(r){return String(r.id)===String(otId);});
    $('novot-ot-fil').value=otId;
    $('novot-ot-search').value=ot?(ot.numero+' — '+(ot.producto_codigo||ot.producto_nombre||ot.descripcion||'')):'';
    _setNovOTOperacionesSel(otId);
    loadNovOT();
  }
  if(!_novOTOrdenes.length){
    loadNovOTList().then(applyFiltro);
  } else {
    applyFiltro();
  }
}


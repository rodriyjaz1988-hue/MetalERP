// ── Ordenes ───────────────────────────────────────────────────────────────────
let otF='';
document.querySelectorAll('#ot-tabs .tab').forEach(t=>t.addEventListener('click',()=>{
  document.querySelectorAll('#ot-tabs .tab').forEach(x=>x.classList.remove('active'));
  t.classList.add('active');otF=t.dataset.e;loadOT();
}));

let _otSortCol=null;
let _otSortAsc=true;
let _otRawRows=[];

function sortOT(col){
  if(_otSortCol===col){ _otSortAsc=!_otSortAsc; }
  else { _otSortCol=col; _otSortAsc=true; }
  renderOT();
}

// Vuelve a pintar la lista aplicando los filtros (código de pieza, cliente,
// OC vinculada, total a realizar) sin volver a pedir los datos al servidor.
function filtrarOT(){
  renderOT();
}

// Limpia los filtros de la lista de OTs. Si skipRender es true, no vuelve a
// pintar (usado cuando el llamador va a hacer loadOT()/renderOT() después).
function clearFiltrosOT(skipRender){
  if($('ot-fil-codigo'))$('ot-fil-codigo').value='';
  if($('ot-fil-cliente'))cliBuscadorClear('ot-fil-cliente');
  if($('ot-fil-oc'))$('ot-fil-oc').value='';
  if($('ot-fil-total-desde'))$('ot-fil-total-desde').value='';
  if($('ot-fil-total-hasta'))$('ot-fil-total-hasta').value='';
  if(!skipRender) renderOT();
}

async function loadOT(){
  _otRawRows=await api('/api/ordenes'+(otF?'?estado='+encodeURIComponent(otF):''));
  if(!_cli.length)_cli=await api('/api/clientes');
  renderOT();
}

function renderOT(){
  const qCodigo=($('ot-fil-codigo')?$('ot-fil-codigo').value:'').toLowerCase().trim();
  const cliId=$('ot-fil-cliente')?$('ot-fil-cliente').value:'';
  const qOC=($('ot-fil-oc')?$('ot-fil-oc').value:'').toLowerCase().trim();
  const totalDesdeRaw=$('ot-fil-total-desde')?$('ot-fil-total-desde').value:'';
  const totalHastaRaw=$('ot-fil-total-hasta')?$('ot-fil-total-hasta').value:'';
  const totalDesde=totalDesdeRaw!==''?parseFloat(totalDesdeRaw):NaN;
  const totalHasta=totalHastaRaw!==''?parseFloat(totalHastaRaw):NaN;

  let rows=_otRawRows;
  if(qCodigo) rows=rows.filter(function(r){return (r.producto_codigo||'').toLowerCase().includes(qCodigo);});
  if(cliId) rows=rows.filter(function(r){return String(r.cliente_id||'')===String(cliId);});
  if(qOC) rows=rows.filter(function(r){return (r.oc_numero||'').toLowerCase().includes(qOC);});
  if(!isNaN(totalDesde)) rows=rows.filter(function(r){return parseFloat(r.cantidad)>=totalDesde;});
  if(!isNaN(totalHasta)) rows=rows.filter(function(r){return parseFloat(r.cantidad)<=totalHasta;});

  if(!rows.length){
    $('ot-list').innerHTML='<div class="em">'+(_otRawRows.length?'Sin resultados para los filtros seleccionados.':'No hay órdenes. Creá la primera con «Nueva OT».')+'</div>';
    return;
  }
  if(_otSortCol){
    const numCols=['cantidad','total_realizado','costo_total','costo_mo'];
    const dateCols=['fecha_entrega'];
    rows.sort(function(a,b){
      let va=a[_otSortCol], vb=b[_otSortCol];
      if(va===null||va===undefined) va='';
      if(vb===null||vb===undefined) vb='';
      if(numCols.includes(_otSortCol)){
        va=parseFloat(va)||0; vb=parseFloat(vb)||0;
        return _otSortAsc ? va-vb : vb-va;
      }
      if(dateCols.includes(_otSortCol)){
        va=va?new Date(va).getTime():0; vb=vb?new Date(vb).getTime():0;
        return _otSortAsc ? va-vb : vb-va;
      }
      va=String(va).toLowerCase(); vb=String(vb).toLowerCase();
      return _otSortAsc ? va.localeCompare(vb) : vb.localeCompare(va);
    });
  }
  const thStyle='cursor:pointer;user-select:none;white-space:nowrap;';
  const cols=[
    {key:'numero',label:'N° OT'},{key:'producto_codigo',label:'Código pieza'},{key:'producto_nombre',label:'Producto'},
    {key:'cliente_nombre',label:'Cliente'},{key:'cantidad',label:'Total a realizar'},
    {key:'total_realizado',label:'Total realizado'},
    {key:'costo_total',label:'Costo total'},{key:'costo_mo',label:'T.std (min)'},
    {key:'estado',label:'Estado'},{key:'fecha_entrega',label:'Entrega'},{key:'oc_numero',label:'OC vinculada'}
  ];
  let h='<table><tr><th style="width:24px"></th>';
  cols.forEach(function(c){
    const arrow=_otSortCol===c.key ? (_otSortAsc?' ▲':' ▼') : ' ⇅';
    const arrowColor=_otSortCol===c.key ? '' : ';opacity:0.35';
    h+='<th style="'+thStyle+'" onclick="sortOT(\''+c.key+'\')">'
      +c.label+'<span style="font-size:10px'+arrowColor+'">'+arrow+'</span></th>';
  });
  h+='</tr>';
  const estadoColoresOT={'Pendiente':{bg:'#FAEEDA',fg:'#633806'},'En proceso':{bg:'#E6F1FB',fg:'#0C447C'},'Completada':{bg:'#EAF3DE',fg:'#27500A'},'Cancelada':{bg:'#F1F1F1',fg:'#555'}};
  rows.forEach(r=>{
    const estadoCol=['admin','operario','vendedor'].includes(ROL)
      ?'<select onchange="cambiarEstadoOT('+r.id+',this)" style="font-family:inherit;font-size:11px;font-weight:500;padding:3px 9px;border-radius:7px;border:1px solid transparent;background:'+(estadoColoresOT[r.estado]?estadoColoresOT[r.estado].bg:'#fff')+';color:'+(estadoColoresOT[r.estado]?estadoColoresOT[r.estado].fg:'#1a1a1a')+';cursor:pointer">'
        +['Pendiente','En proceso','Completada','Cancelada'].map(function(e){return '<option value="'+e+'" style="background:#fff"'+(r.estado===e?' selected':'')+'>'+e+'</option>';}).join('')
        +'</select>'
      :sb(r.estado);
    const _otAbierta=!['Completada','Cancelada'].includes(r.estado);
    h+=`<tr id="ot-row-${r.id}" class="${_otSel===r.id?'ot-sel':''}${venceFila(r.fecha_entrega,_otAbierta)}" style="cursor:pointer" title="Doble clic: ver el avance de las operaciones" onclick="selOT(${r.id})"><td><input type="radio" name="ot-sel" ${_otSel===r.id?'checked':''} onclick="event.stopPropagation();selOT(${r.id})"></td><td>${r.lista_para_completar?`<span title="Todas las operaciones al 100% — lista para marcar como Completada" style="display:inline-flex;align-items:center;justify-content:center;width:16px;height:16px;border-radius:50%;background:#2E9E44;color:#fff;font-size:11px;font-weight:700;margin-right:6px;vertical-align:middle">!</span>`:''}<b>${r.numero}</b></td><td>${r.producto_codigo||'—'}</td><td>${r.producto_nombre||r.descripcion}</td><td>${r.cliente_nombre||'—'}</td>
    <td>${fN(r.cantidad)}</td><td${(r.cantidad>0&&(r.total_realizado||0)>=r.cantidad)?' style="color:#2e7d32;font-weight:600" title="Ya se realizó toda la cantidad pedida"':''}>${r.total_realizado||0}</td><td title="${VER_MONETARIO?('Materiales: '+fmtM(r.costo_mat||0)+(r.costo_terciarizado?' + Terciarizado: '+fmtM(r.costo_terciarizado):'')):''}">${fmtM(r.costo_total!==undefined?r.costo_total:r.costo_mat)}</td><td>${r.costo_mo||0}</td>
    <td onclick="event.stopPropagation()">${estadoCol}</td><td${venceCelda(r.fecha_entrega,_otAbierta)}>${fmtD(r.fecha_entrega)}</td>
    <td>${r.oc_numero?`<span style="cursor:pointer;color:var(--color-accent);text-decoration:underline dotted" onclick="verAvanceOC(${r.oc_id},'${r.oc_numero}')" title="Ver avance de entrega">${r.oc_numero}</span>`:'—'}</td>`;
    h+='</tr>';
    if(_otAvanceAbierto===r.id) h+='<tr id="ot-avance-row"><td colspan="'+(cols.length+1)+'" style="background:#fafaf8;padding:8px 14px"><div id="ot-avance-box"><div class="ld">Cargando operaciones...</div></div></td></tr>';
  });
  $('ot-list').innerHTML=h+'</table>';
  _ot_cache=new Map(rows.map(r=>[r.id,r]));
  if(_otSel && !_ot_cache.has(_otSel)){ _otSel=null; _otAvanceAbierto=null; }
  actualizarToolbarOT();
  if(_otAvanceAbierto) cargarAvanceOT(_otAvanceAbierto);
}

// ── Selección de OT + barra de herramientas (fix v147) ──────────────────────
let _otSel=null;
let _otAvanceAbierto=null;
// Un clic selecciona la OT; el doble clic sobre la misma fila despliega u
// oculta el avance de sus operaciones. No usamos el evento 'dblclick' porque
// renderOT() rehace la tabla en el primer clic y el navegador ya no lo dispara
// sobre la fila (la fila original dejó de existir): lo detectamos por tiempo.
const OT_DBLCLICK_MS=400;
let _otUltClick={id:null,t:0};
function selOT(id){
  const ahora=Date.now();
  const esDoble=(_otUltClick.id===id && ahora-_otUltClick.t<OT_DBLCLICK_MS);
  _otUltClick=esDoble?{id:null,t:0}:{id:id,t:ahora};
  _otSel=id;
  if(esDoble){
    // El doble clic deja texto seleccionado en la fila: lo limpiamos.
    try{window.getSelection().removeAllRanges();}catch(e){}
    _otAvanceAbierto=(_otAvanceAbierto===id)?null:id;
  }else if(_otAvanceAbierto && _otAvanceAbierto!==id){
    _otAvanceAbierto=null;
  }
  renderOT();
}
function actualizarToolbarOT(){
  const r=_otSel&&_ot_cache?_ot_cache.get(_otSel):null;
  const puede=['admin','operario','vendedor'].includes(ROL);
  $('ot-sel-label').textContent=r?r.numero:'–';
  $('ot-b-ops').disabled=!r||!puede;
  $('ot-b-edit').disabled=!r||!puede;
  $('ot-b-emitir').disabled=!r||!puede;
  ['ot-b-ops','ot-b-edit','ot-b-emitir'].forEach(function(id){ $(id).dataset.motivo=(r&&!puede)?'Tu usuario no tiene permiso para esta acción':''; });
}
function otSelAccion(a){
  const r=_otSel&&_ot_cache?_ot_cache.get(_otSel):null;
  if(!r){toast('Seleccioná una OT de la lista','w');return;}
  if(a==='edit') editOT(r);
  else if(a==='ops') openOTDetail(r.id,r.numero);
  else if(a==='emitir') emitirOT(r.id);
}
async function cargarAvanceOT(oid){
  const box=$('ot-avance-box'); if(!box) return;
  const ops=await api('/api/ordenes/'+oid+'/operaciones');
  if(!ops.length){box.innerHTML='<div class="em">La OT no tiene operaciones generadas.</div>';return;}
  let h='<table style="margin:0"><tr><th>Ord.</th><th>Operación</th><th>Sector</th><th>Requerido</th><th>Producido</th><th>Avance</th><th>Estado</th></tr>';
  ops.forEach(function(op){
    const pct=op.qty_requerida>0?Math.min(100,Math.round(op.qty_producida/op.qty_requerida*100)):0;
    const col=pct>=100?'#2E9E44':pct>=50?'#E0A100':'#C0392B';
    const sector=op.es_tercerizada?('<span class="b br" style="font-size:10px">TERC</span> '+(op.proveedor_nombre||'—')):(op.cat_maquina_nombre||'—');
    h+='<tr><td>'+op.orden+'</td><td>'+op.nombre+'</td><td>'+sector+'</td><td>'+fN(op.qty_requerida)+'</td><td>'+fN(op.qty_producida)+'</td>'
      +'<td style="min-width:130px"><div style="background:#e6e6e0;border-radius:6px;height:10px;overflow:hidden;display:inline-block;width:90px;vertical-align:middle"><div style="height:10px;width:'+pct+'%;background:'+col+'"></div></div> <b style="font-size:11px">'+pct+'%</b></td>'
      +'<td>'+sb(op.estado)+'</td></tr>';
  });
  box.innerHTML=h+'</table>';
}

async function cambiarEstadoOT(id,sel){
  const nuevoEstado=sel.value;
  const colores={'Pendiente':{bg:'#FAEEDA',fg:'#633806'},'En proceso':{bg:'#E6F1FB',fg:'#0C447C'},'Completada':{bg:'#EAF3DE',fg:'#27500A'},'Cancelada':{bg:'#F1F1F1',fg:'#555'}};
  sel.style.background=colores[nuevoEstado]?colores[nuevoEstado].bg:'#fff';
  sel.style.color=colores[nuevoEstado]?colores[nuevoEstado].fg:'#1a1a1a';
  const r=_ot_cache.get(id);
  if(!r){toast('Error: OT no encontrada','e');loadOT();return;}
  const body={
    descripcion:r.descripcion,
    cliente_id:r.cliente_id||null,
    producto_id:r.producto_id,
    detalle:r.detalle,
    cantidad:r.cantidad,
    prioridad:r.prioridad,
    estado:nuevoEstado,
    fecha_inicio:r.fecha_inicio,
    fecha_entrega:r.fecha_entrega,
    costo_mat:r.costo_mat,
    costo_mo:r.costo_mo,
    precio_venta:0,
    obs:r.obs
  };
  const res=await api('/api/ordenes/'+r.id,{method:'PUT',body:JSON.stringify(body)});
  if(res.ok){toast('Estado actualizado');loadOT();}
  else{toast(res.error||'Error','e');loadOT();}
}

async function emitirOT(oid){
  toast('Generando PDF...', 'g');
  // Populate ops/mats if empty before generating
  const ops = await api('/api/ordenes/'+oid+'/operaciones');
  if(!ops.length){
    await api('/api/ordenes/'+oid+'/operaciones/populate',{method:'POST',body:JSON.stringify({})});
  }
  const mats = await api('/api/ordenes/'+oid+'/materiales');
  if(!mats.length){
    await api('/api/ordenes/'+oid+'/materiales/populate',{method:'POST',body:JSON.stringify({})});
  }
  // Open PDF from server in new tab
  window.open('/api/ordenes/'+oid+'/pdf', '_blank');
}

async function emitirOP(oid, opid){
  toast('Generando PDF...', 'g');
  window.open('/api/ordenes/'+oid+'/operaciones/'+opid+'/pdf', '_blank');
}


// ── Asignar lote a OT ────────────────────────────────────────────────────────
let _alLoteSelected = null;
let _alReturnCtx = null; // cuando se abre desde "Modificar lotes", guarda {oid,mid} para volver ahí

async function abrirAsignLote(oid, mid, faltante, desc){
  _alReturnCtx = null;
  $('al-faltante-wrap').style.display = '';
  $('al-oid').value = oid;
  $('al-mid').value = mid;
  // desc may be null when called from table — fetch from mats list
  if(!desc||desc==='null'){
    const mlist = await api('/api/ordenes/'+oid+'/materiales');
    const m = mlist.find(function(x){return x.material_id===parseInt(mid)||x.material_id===mid;});
    desc = m ? m.codigo+' — '+m.descripcion : 'Material '+mid;
  }
  $('al-desc').textContent = desc;
  $('al-faltante').textContent = faltante;
  $('al-qty').value = faltante;
  $('al-lotes-list').innerHTML = '<div class="ld">Cargando...</div>';
  _alLoteSelected = null;
  openMo('mo-asign-lote');

  const lotes = await api('/api/materiales/'+mid+'/lotes_aprobados');
  if(!lotes.length){
    $('al-lotes-list').innerHTML = '<div class="al al-e">No hay lotes aprobados con stock libre para este material.</div>';
    return;
  }
  let h = '<table><tr><th>Lote</th><th>Disponible libre</th><th>Certificado</th><th>Ingreso</th><th></th></tr>';
  lotes.forEach(function(l){
    h += '<tr id="al-row-'+l.id+'">'
      + '<td><b>'+l.numero+'</b></td>'
      + '<td><b>'+fN(l.disponible_libre)+'</b></td>'
      + '<td>'+(l.certificado||'—')+'</td>'
      + '<td>'+fmtD(l.fecha_ingreso)+'</td>'
      + '<td><button class="btn btn-s" onclick="seleccionarLote('+l.id+','+l.disponible_libre+')" id="al-btn-'+l.id+'">Seleccionar</button></td>'
      + '</tr>';
  });
  $('al-lotes-list').innerHTML = h + '</table>';
}

// Igual que abrirAsignLote, pero se usa desde "Modificar lotes asignados" para
// agregar un lote nuevo: no hay "faltante" (se pide la cantidad libremente) y,
// al confirmar, se vuelve al modal de Modificar en lugar de al detalle de la OT.
async function abrirAsignLoteParaModificar(oid, mid, desc){
  _alReturnCtx = {oid:oid, mid:mid};
  $('al-oid').value = oid;
  $('al-mid').value = mid;
  $('al-desc').textContent = desc;
  $('al-faltante-wrap').style.display = 'none';
  $('al-faltante').textContent = '';
  $('al-qty').value = '';
  $('al-lotes-list').innerHTML = '<div class="ld">Cargando...</div>';
  _alLoteSelected = null;
  openMo('mo-asign-lote');

  const mlist = await api('/api/ordenes/'+oid+'/materiales');
  const m = mlist.find(function(x){return x.material_id===parseInt(mid);});
  const yaAsignados = new Set(((m && m.lotes_asignados) || []).map(function(l){return l.lote_id;}));
  const disponibles = await api('/api/materiales/'+mid+'/lotes_aprobados');
  const lotes = disponibles.filter(function(l){return !yaAsignados.has(l.id);});
  if(!lotes.length){
    $('al-lotes-list').innerHTML = '<div class="al al-e">No hay otros lotes aprobados con stock libre para este material.</div>';
    return;
  }
  let h = '<table><tr><th>Lote</th><th>Disponible libre</th><th>Certificado</th><th>Ingreso</th><th></th></tr>';
  lotes.forEach(function(l){
    h += '<tr id="al-row-'+l.id+'">'
      + '<td><b>'+l.numero+'</b></td>'
      + '<td><b>'+fN(l.disponible_libre)+'</b></td>'
      + '<td>'+(l.certificado||'—')+'</td>'
      + '<td>'+fmtD(l.fecha_ingreso)+'</td>'
      + '<td><button class="btn btn-s" onclick="seleccionarLote('+l.id+','+l.disponible_libre+')" id="al-btn-'+l.id+'">Seleccionar</button></td>'
      + '</tr>';
  });
  $('al-lotes-list').innerHTML = h + '</table>';
}

function seleccionarLote(loteId, libre){
  // Si el lote clickeado ya estaba seleccionado, se deselecciona (toggle).
  if(_alLoteSelected === loteId){
    _alLoteSelected = null;
    document.querySelectorAll('#al-lotes-list tr[id^="al-row-"]').forEach(function(r){
      r.style.background = '';
      r.style.color = '';
      r.style.outline = '';
      r.style.outlineOffset = '';
    });
    document.querySelectorAll('#al-lotes-list button[id^="al-btn-"]').forEach(function(b){
      b.textContent = 'Seleccionar';
    });
    $('al-qty').value = $('al-faltante').textContent;
    $('al-qty').removeAttribute('max');
    return;
  }
  _alLoteSelected = loteId;
  document.querySelectorAll('#al-lotes-list tr[id^="al-row-"]').forEach(function(r){
    if(r.id === 'al-row-'+loteId){
      r.style.background = '#dceeff';
      r.style.color = '#1a1a1a';
      r.style.outline = '2px solid #378ADD';
      r.style.outlineOffset = '-2px';
    } else {
      r.style.background = '';
      r.style.color = '';
      r.style.outline = '';
      r.style.outlineOffset = '';
    }
  });
  document.querySelectorAll('#al-lotes-list button[id^="al-btn-"]').forEach(function(b){
    b.textContent = (b.id === 'al-btn-'+loteId) ? 'Quitar selección' : 'Seleccionar';
  });
  const faltanteNum = parseFloat($('al-faltante').textContent);
  const qty = Math.min(isNaN(faltanteNum)?libre:faltanteNum, libre);
  $('al-qty').value = qty;
  $('al-qty').max = libre;
}

async function confirmarAsignLote(){
  if(!_alLoteSelected){ toast('Seleccioná un lote','w'); return; }
  const oid = parseInt($('al-oid').value);
  const mid = parseInt($('al-mid').value);
  const qty = parseFloat($('al-qty').value);
  if(!qty||qty<=0){ toast('Ingresá una cantidad','w'); return; }
  const res = await api('/api/ordenes/'+oid+'/materiales/'+mid+'/asignar_lote',
    {method:'POST', body:JSON.stringify({lote_id:_alLoteSelected, cantidad:qty})});
  if(res.ok){
    toast('Lote asignado: '+fN(qty)+' u. de lote '+res.lote);
    closeMo('mo-asign-lote');
    if(_alReturnCtx){
      const ctx = _alReturnCtx; _alReturnCtx = null;
      await refrescarModLotes(ctx.oid, ctx.mid);
    } else {
      openOTDetail(oid);
    }
  } else toast(res.error||'Error','e');
}

// ── Modificar cantidad de lotes ya asignados a un material de la OT ───────
async function abrirModificarLotes(oid, mid, desc){
  $('ml-oid').value = oid;
  $('ml-mid').value = mid;
  $('ml-desc').textContent = 'Lotes asignados — ' + desc;
  $('ml-list').innerHTML = '<div class="ld">Cargando...</div>';
  $('ml-add-list').innerHTML = '<div class="ld">Cargando lotes disponibles...</div>';
  openMo('mo-mod-lotes');

  const mlist = await api('/api/ordenes/'+oid+'/materiales');
  const m = mlist.find(function(x){return x.material_id===parseInt(mid);});
  const lotes = (m && m.lotes_asignados) || [];
  if(!lotes.length){
    $('ml-list').innerHTML = '<div class="em">Sin lotes asignados.</div>';
  } else {
    let h = '';
    lotes.forEach(function(l){
      const consumida = l.cantidad_consumida || 0;
      h += '<div class="opc" id="ml-row-'+l.lote_id+'">'
        + '<div class="oph"><span class="opn">Lote '+l.numero+'</span></div>'
        + (consumida>0
          ? '<div class="opm" style="color:#854F0B">Ya se consumieron '+consumida+' de este lote en producción — no se pueden liberar.</div>'
          : '')
        + '<div style="display:flex;gap:8px;align-items:center;margin-top:6px">'
        + '<input type="number" min="'+consumida+'" step="0.01" value="'+l.cantidad_usada+'" id="ml-qty-'+l.lote_id+'" style="width:120px;height:32px;padding:5px 8px;font-size:13px;border:1px solid #ddd;border-radius:7px">'
        + '<button class="btn btn-s btn-p" onclick="guardarCantidadLote('+l.lote_id+')">Guardar</button>'
        + '<button class="btn btn-s btn-d" onclick="eliminarLoteAsignado('+l.lote_id+')">'+(consumida>0?'Quitar lo no consumido':'Eliminar')+'</button>'
        + '</div></div>';
    });
    $('ml-list').innerHTML = h;
  }

  // Lotes disponibles para agregar (excluye los ya asignados a este material en esta OT)
  const yaAsignados = new Set(lotes.map(function(l){return l.lote_id;}));
  const disponibles = await api('/api/materiales/'+mid+'/lotes_aprobados');
  const paraAgregar = disponibles.filter(function(l){return !yaAsignados.has(l.id);});
  if(!paraAgregar.length){
    $('ml-add-list').innerHTML = '<div class="em">No hay otros lotes aprobados con stock libre para este material.</div>';
    return;
  }
  $('ml-add-list').innerHTML = '<button class="btn btn-p" onclick="abrirAsignLoteParaModificar('+oid+','+mid+',\''+desc.replace(/'/g,"\\'")+'\')">+ Agregar lote</button>';
}

async function guardarCantidadLote(loteId){
  const oid = parseInt($('ml-oid').value);
  const mid = parseInt($('ml-mid').value);
  const qty = parseFloat($('ml-qty-'+loteId).value);
  if(isNaN(qty)||qty<0){ toast('Ingresá una cantidad válida','w'); return; }
  const res = await api('/api/ordenes/'+oid+'/materiales/'+mid+'/lotes/'+loteId,
    {method:'PUT', body:JSON.stringify({cantidad:qty})});
  if(res.ok){
    toast(res.recortado
      ? 'Solo se pudo bajar hasta '+fN(res.cantidad_nueva)+' (lo demás ya está consumido)'
      : 'Cantidad actualizada: '+fN(res.cantidad_anterior)+' → '+fN(res.cantidad_nueva), res.recortado?'w':'g');
    await refrescarModLotes(oid, mid);
  } else toast(res.error||'Error','e');
}

async function eliminarLoteAsignado(loteId){
  if(!await confirmar('¿Quitar este lote de la OT? Se liberará lo que todavía no se haya consumido; si ya se usó parte en producción, esa parte queda registrada.')) return;
  const oid = parseInt($('ml-oid').value);
  const mid = parseInt($('ml-mid').value);
  const res = await api('/api/ordenes/'+oid+'/materiales/'+mid+'/lotes/'+loteId,
    {method:'PUT', body:JSON.stringify({cantidad:0})});
  if(res.ok){
    toast(res.recortado
      ? 'Lote '+res.lote+': se liberó lo no consumido, quedan '+fN(res.cantidad_nueva)+' ya usados en producción'
      : 'Lote '+res.lote+' quitado de la OT', res.recortado?'w':'g');
    await refrescarModLotes(oid, mid);
  } else toast(res.error||'Error','e');
}

async function refrescarModLotes(oid, mid){
  const desc=$('ml-desc').textContent.replace(/^Lotes asignados — /,'');
  const num=$('ot-detail-title').childNodes[0].textContent.replace('Detalle OT ','').trim();
  await openOTDetail(oid,num);
  abrirModificarLotes(oid, mid, desc);
}

// ── Plan de herramientas por operación ────────────────────────────────────────
let _herrOpId = null;

function openHerramientasById(btn){
  const opId = parseInt(btn.getAttribute('data-herr'));
  const opNombre = decodeURIComponent(btn.getAttribute('data-herr-nom'));
  openHerramientas(opId, opNombre);
}

async function openHerramientas(opId, opNombre){
  _herrOpId = opId;
  document.getElementById('herr-op-nombre').textContent = opNombre;
  document.getElementById('herr-list').innerHTML = '<div class="ld">Cargando...</div>';
  openMo('mo-herramientas');
  await loadHerramientas();
}

// Herramienta: se carga "piezas por herramienta" o "cant. por pieza", nunca
// las dos. Con piezas por herramienta, la cantidad muestra "—" (se guarda 1,
// que el cálculo no usa); sin ella, piezas muestra "—" y la cantidad es obligatoria.
function herrExclusivo(vidaEl,cantEl){
  if(!vidaEl||!cantEl) return;
  vidaEl.placeholder='—';
  const aplicar=function(){
    if(vidaEl.value){
      if(!cantEl.disabled&&cantEl.value) cantEl.dataset.prev=cantEl.value;
      cantEl.value=''; cantEl.placeholder='—'; cantEl.disabled=true;
      cantEl.title='No se usa: la herramienta se calcula por piezas por herramienta';
    } else {
      if(cantEl.disabled) cantEl.value=cantEl.dataset.prev||'1';
      cantEl.placeholder='Cant.'; cantEl.disabled=false; cantEl.title='';
    }
  };
  vidaEl.addEventListener('input',aplicar);
  aplicar();
}
// Cantidad a guardar: con piezas por herramienta va 1 (no se usa en el cálculo).
function herrCantidad(vidaEl,cantEl){
  if(vidaEl&&vidaEl.value) return 1;
  return cantEl?cantEl.value:1;
}

async function loadHerramientas(){
  const canEdit = ['admin','operario'].includes(ROL);
  // Herramientas del inventario de la operación (con piezas por herramienta),
  // las de texto libre cargadas antes y el inventario, en paralelo
  const [asignadas, previas, inventario] = await Promise.all([
    api('/api/operaciones/'+_herrOpId+'/herramientas_inv'),
    api('/api/operaciones/'+_herrOpId+'/herramientas'),
    api('/api/materiales?categoria=Herramienta')
  ]);

  let hList = '';
  if(!asignadas.length && !previas.length){
    hList = '<div class="em">Sin herramientas asignadas.</div>';
  } else {
    hList = '<table><tr><th>Herramienta</th><th title="Cuántas piezas hace una herramienta antes de reemplazarla">Piezas por herramienta</th><th title="Se usa solo si no hay piezas por herramienta">Cant. por pieza</th>'+(canEdit?'<th></th>':'')+'</tr>';
    asignadas.forEach(function(r){
      hList += '<tr>'
        + '<td><b>'+r.codigo+'</b> — '+(r.descripcion||'')+'</td>'
        + (canEdit
            ? '<td><input type="number" min="1" step="1" id="herr-vida-'+r.id+'" value="'+(r.vida_util_herramienta||'')+'" placeholder="—" style="width:90px"></td>'
              + '<td><input type="number" min="0.01" step="0.01" id="herr-cant-'+r.id+'" value="'+r.cantidad+'" style="width:70px"> '+(r.unidad||'')+'</td>'
              + '<td style="white-space:nowrap"><button class="btn btn-s" onclick="updateHerramientaInv('+r.id+')">Guardar</button> <button class="btn btn-s btn-d" onclick="deleteHerramientaInv('+r.id+')">✕</button></td>'
            : '<td>'+(r.vida_util_herramienta||'—')+'</td><td>'+(r.vida_util_herramienta?'—':fN(r.cantidad)+' '+(r.unidad||''))+'</td>')
        + '</tr>';
    });
    previas.forEach(function(r){
      hList += '<tr>'
        + '<td><b>'+r.nombre+'</b>'+(r.descripcion?' — '+r.descripcion:'')+'</td>'
        + '<td>—</td><td>'+fN(r.cantidad)+' '+r.unidad+'</td>'
        + (canEdit?'<td><button class="btn btn-s btn-d" onclick="deleteHerramienta('+r.id+')">✕</button></td>':'')
        + '</tr>';
    });
    hList += '</table>';
  }
  document.getElementById('herr-list').innerHTML = hList;
  if(canEdit) asignadas.forEach(function(r){ herrExclusivo($('herr-vida-'+r.id),$('herr-cant-'+r.id)); });
  herrExclusivo($('herr-vida'),$('herr-cant'));

  // Selector de inventario (solo si puede editar)
  const sel = document.getElementById('herr-inv-sel');
  if(sel && canEdit){
    sel.innerHTML = '<option value="">— Seleccionar herramienta del inventario —</option>'
      + inventario.map(function(m){
          return '<option value="'+m.id+'">'+m.codigo+' — '+m.descripcion+'</option>';
        }).join('');
    if(!inventario.length) sel.innerHTML='<option value="">No hay herramientas en Inventario (categoría Herramienta)</option>';
    document.getElementById('herr-inv-wrap').style.display = canEdit ? 'block' : 'none';
  }
}

async function _herrRefrescar(msg){
  await loadHerramientas();
  if(curProdId) verProc(curProdId, curProdNom);
  toast(msg);
}

async function saveHerramienta(){
  const sel = document.getElementById('herr-inv-sel');
  if(!sel || !sel.value){ toast('Seleccioná una herramienta del inventario','w'); return; }
  if(!$('herr-vida').value && !(parseFloat($('herr-cant').value)>0)){ toast('Cargá piezas por herramienta o la cantidad por pieza','w'); return; }
  const body = {
    material_id: parseInt(sel.value),
    cantidad: parseFloat(herrCantidad($('herr-vida'),$('herr-cant'))),
    vida_util_herramienta: document.getElementById('herr-vida').value||null,
  };
  const res = await api('/api/operaciones/'+_herrOpId+'/herramientas_inv',
    {method:'POST', body:JSON.stringify(body)});
  if(res.ok){
    sel.value='';
    document.getElementById('herr-vida').value='';
    document.getElementById('herr-cant').value='1';
    $('herr-cant').disabled=false; $('herr-cant').placeholder='Cant.';
    await _herrRefrescar('Herramienta agregada');
  } else toast(res.error||'Error','e');
}

async function updateHerramientaInv(rid){
  const vEl=$('herr-vida-'+rid), cEl=$('herr-cant-'+rid);
  if(!vEl.value && !(parseFloat(cEl.value)>0)){ toast('Cargá piezas por herramienta o la cantidad por pieza','w'); return; }
  const body = {
    cantidad: parseFloat(herrCantidad(vEl,cEl)),
    vida_util_herramienta: vEl.value||null,
  };
  const res = await api('/api/operaciones/'+_herrOpId+'/herramientas_inv/'+rid,
    {method:'PUT', body:JSON.stringify(body)});
  if(res.ok) await _herrRefrescar('Herramienta guardada');
  else toast(res.error||'Error','e');
}

async function deleteHerramientaInv(rid){
  if(!await confirmar('¿Quitar herramienta de la operación?')) return;
  const res = await apiBorrar('/api/operaciones/'+_herrOpId+'/herramientas_inv/'+rid,'Herramienta quitada');
  if(res.ok) await _herrRefrescar('Quitada');
  else toast(res.error||'Error','e');
}

async function deleteHerramienta(hid){
  if(!await confirmar('¿Eliminar herramienta?')) return;
  const res = await apiBorrar('/api/operaciones/'+_herrOpId+'/herramientas/'+hid,'Herramienta eliminada');
  if(res.ok){ await loadHerramientas(); toast('Eliminada'); }
  else toast(res.error||'Error','e');
}

// ── Avance de OC + remitos ────────────────────────────────────────────────────
async function verAvanceOC(ocId, ocNumero){
  const data = await api('/api/ordenes_cliente/'+ocId+'/avance');
  const modal = document.getElementById('mo-avance-oc');
  document.getElementById('avance-oc-titulo').textContent = 'Avance OC '+ocNumero;
  const pct = data.pct_total||0;
  const pctColor = pct>=100?'#1B5E20':pct>=50?'#E65100':'#A32D2D';
  const montoPedido=data.total_monto_pedido||0, montoEntregado=data.total_monto_entregado||0;
  const excesoTotal=Math.max(0,montoEntregado-montoPedido);
  let h = '<div style="margin-bottom:10px;font-size:13px">'
    + '<b>Avance general:</b> '
    + '<span style="color:'+pctColor+';font-size:16px;font-weight:700">'+pct+'%</span>'
    + ' &nbsp; Entregado: '+fN(data.total_entregado)+' / '+fN(data.total_requerido)
    + '</div>';
  h += '<div style="background:var(--color-border-tertiary);border-radius:4px;height:10px;margin-bottom:10px">'
    + '<div style="background:'+pctColor+';height:10px;border-radius:4px;width:'+Math.min(pct,100)+'%;transition:width .4s"></div></div>';
  // Sin permiso no va ni la franja de montos ni el aviso de excedente: el
  // aviso y su color naranja se derivan de comparar dos importes, así que
  // también son un rastro.
  h += monOnly('<div style="display:flex;justify-content:space-between;font-size:12px;background:var(--color-background-secondary);border-radius:6px;padding:8px 10px;margin-bottom:14px">'
    + '<span>Monto pedido: <b>'+fmtM(montoPedido)+'</b></span>'
    + '<span>Monto a facturar: <b style="color:'+(excesoTotal>0?'#E65100':'inherit')+'">'+fmtM(montoEntregado)+'</b></span>'
    + '</div>'
    + (excesoTotal>0?('<div class="al al-w" style="margin-bottom:10px;font-size:12px">Se remitió por encima de lo pedido: el excedente ('+fmtM(excesoTotal)+') también se factura, el importe final queda por arriba del presupuesto original.</div>'):''));

  (data.items||[]).forEach(function(item){
    const ipct=item.pct_entrega||0;
    const ic=ipct>=100?'#1B5E20':ipct>0?'#E65100':'#A32D2D';
    const tieneExceso=(item.exceso||0)>0;
    h += '<div style="border:1px solid var(--color-border-tertiary);border-radius:6px;padding:8px 10px;margin-bottom:8px">';
    h += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">';
    h += '<span style="font-weight:600">'+item.prod_codigo+' — '+item.prod_nombre+'</span>';
    h += '<span style="color:'+ic+';font-weight:700">'+(item.pct_entrega_real||ipct)+'%</span></div>';
    h += '<div style="background:var(--color-border-tertiary);border-radius:3px;height:6px;margin-bottom:6px">'
      +'<div style="background:'+ic+';height:6px;border-radius:3px;width:'+Math.min(ipct,100)+'%"></div></div>';
    h += '<div style="font-size:11px;color:var(--color-text-secondary)">'
      +'Pedido: '+fN(item.cantidad)+' '+item.unidad
      +' &nbsp;|&nbsp; Entregado: '+item.entregado
      +(tieneExceso?' &nbsp;|&nbsp; <span style="color:#E65100;font-weight:600">Exceso: '+item.exceso+'</span>':'')
      +(item.fecha_deseada?' &nbsp;|&nbsp; F. deseada: '+fmtD(item.fecha_deseada):'')
      +'</div>';
    h += '<div style="font-size:11px;color:var(--color-text-secondary);margin-top:2px">'
      +'Monto pedido: '+fmtM(item.monto_pedido)
      +' &nbsp;|&nbsp; Monto a facturar: <b style="color:'+(tieneExceso?'#E65100':'inherit')+'">'+fmtM(item.monto_entregado)+'</b>'
      +'</div>';
    if(item.remitos&&item.remitos.length){
      h += '<div style="margin-top:6px;font-size:11px">';
      h += '<b style="color:var(--color-text-secondary)">Remitos vinculados:</b> ';
      h += item.remitos.map(function(r){
        return r.numero+' ('+fmtD(r.fecha)+') — '+fN(r.cantidad)+' u.';
      }).join(', ');
      h += '</div>';
    }
    h += '</div>';
  });
  document.getElementById('avance-oc-body').innerHTML = h;
  openMo('mo-avance-oc');
}


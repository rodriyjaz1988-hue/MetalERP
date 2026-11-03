// ── Pedidos de clientes (mismo patrón visual que Órdenes de trabajo) ─────────
let _occF='';
let _occRawRows=[];
let _occSortCol=null, _occSortAsc=true;
let _occSel=null, _occExpandido=null;
let _occUltClick={id:null,t:0};
document.querySelectorAll('#occ-tabs .tab').forEach(t=>t.addEventListener('click',()=>{
  document.querySelectorAll('#occ-tabs .tab').forEach(x=>x.classList.remove('active'));
  t.classList.add('active');_occF=t.dataset.e;loadOCClientes();
}));

function sortOCC(col){
  if(_occSortCol===col){ _occSortAsc=!_occSortAsc; }
  else { _occSortCol=col; _occSortAsc=true; }
  renderOCC();
}
function filtrarOCC(){ renderOCC(); }
function clearFiltrosOCC(skipRender){
  if($('occ-fil-numero'))$('occ-fil-numero').value='';
  if($('occ-fil-codigo'))$('occ-fil-codigo').value='';
  if($('oc-cli-fil'))cliBuscadorClear('oc-cli-fil');
  if(!skipRender) renderOCC();
}

async function loadOCClientes(){
  try {
    if(!_cli.length)_cli=await api('/api/clientes');
    const url='/api/ordenes_cliente'+(_occF?'?estado='+encodeURIComponent(_occF):'');
    let rows;
    try {
      rows=await api(url);
    } catch(e) {
      $('occ-list').innerHTML='<div class="em" style="color:red">Error de red: '+e.message+'</div>';
      return;
    }
    if(!Array.isArray(rows)){
      $('occ-list').innerHTML='<div class="em" style="color:red">Error del servidor: '+(rows.error||JSON.stringify(rows))+'</div>';
      return;
    }
    rows.forEach(function(r){
      r._total=(r.items||[]).reduce(function(s,i){return s+(parseFloat(i.cantidad)||0);},0);
    });
    _occRawRows=rows;
    _occ_cache=new Map(rows.map(function(r){return[r.id,r];}));
    renderOCC();
  } catch(e) {
    console.error('[OCC]', e);
    $('occ-list').innerHTML='<div class="em" style="color:red;font-size:11px">Error: '+e.message+'<br>'+e.stack.split("\n").slice(0,3).join("<br>")+'</div>';
  }
}

function renderOCC(){
  const cliId=$('oc-cli-fil')?$('oc-cli-fil').value:'';
  const qNum=($('occ-fil-numero')?$('occ-fil-numero').value:'').toLowerCase().trim();
  const qCod=($('occ-fil-codigo')?$('occ-fil-codigo').value:'').toLowerCase().trim();

  let rows=_occRawRows.slice();
  if(cliId) rows=rows.filter(function(r){return String(r.cliente_id||'')===String(cliId);});
  if(qNum) rows=rows.filter(function(r){return (r.numero||'').toLowerCase().includes(qNum);});
  if(qCod) rows=rows.filter(function(r){return (r.items||[]).some(function(i){return (i.producto_codigo||'').toLowerCase().includes(qCod);});});

  if(!rows.length){
    $('occ-list').innerHTML='<div class="em">'+(_occRawRows.length?'Sin resultados para los filtros seleccionados.':'No hay pedidos de clientes registrados. Usá «Nueva OC» para cargar el primero.')+'</div>';
    _occSel=null;_occExpandido=null;actualizarToolbarOCC();
    return;
  }
  if(_occSortCol){
    const numCols=['_total','pct_entrega'];
    const dateCols=['creado','fecha_entrega'];
    rows.sort(function(a,b){
      let va=a[_occSortCol], vb=b[_occSortCol];
      if(va===null||va===undefined) va='';
      if(vb===null||vb===undefined) vb='';
      if(numCols.includes(_occSortCol)){
        va=parseFloat(va)||0; vb=parseFloat(vb)||0;
        return _occSortAsc ? va-vb : vb-va;
      }
      if(dateCols.includes(_occSortCol)){
        va=va?new Date(va).getTime():0; vb=vb?new Date(vb).getTime():0;
        return _occSortAsc ? va-vb : vb-va;
      }
      va=String(va).toLowerCase(); vb=String(vb).toLowerCase();
      return _occSortAsc ? va.localeCompare(vb) : vb.localeCompare(va);
    });
  }
  const thStyle='cursor:pointer;user-select:none;white-space:nowrap;';
  const cols=[
    {key:'numero',label:'N° OC'},{key:'cliente_nombre',label:'Cliente'},{key:'_total',label:'Artículos'},
    {key:'creado',label:'Fecha'},{key:'fecha_entrega',label:'F. entrega'},{key:'estado',label:'Estado'},{key:'pct_entrega',label:'Avance'}
  ];
  let h='<table><tr><th style="width:24px"></th>';
  cols.forEach(function(c){
    const arrow=_occSortCol===c.key ? (_occSortAsc?' ▲':' ▼') : ' ⇅';
    const arrowColor=_occSortCol===c.key ? '' : ';opacity:0.35';
    h+='<th style="'+thStyle+'" onclick="sortOCC(\''+c.key+'\')">'
      +c.label+'<span style="font-size:10px'+arrowColor+'">'+arrow+'</span></th>';
  });
  h+='</tr>';
  rows.forEach(function(r){
    // Avance real de entrega: lo remitido sobre lo pedido (viene del backend
    // ya calculado sobre remito_items, no sobre si hay OT generada o no).
    const avancePct=(typeof r.pct_entrega==='number')?r.pct_entrega:0;
    const avanceColor=avancePct===100?'bg':avancePct>0?'ba':'br';
    const detalle=r.items.map(function(i){return i.producto_codigo+' ('+i.producto_nombre+') ×'+fN(i.cantidad)+' '+(i.unidad||'unid');}).join('\n');
    const sel=_occSel===r.id;
    const occAbierta=!['Completada','Cancelada'].includes(r.estado)&&avancePct<100;
    const occVence=(r.items||[]).filter(function(i){return i.fecha_deseada&&(+i.cantidad_entregada||0)<(+i.cantidad||0);})
      .map(function(i){return String(i.fecha_deseada).slice(0,10);}).sort()[0]||r.fecha_entrega;
    h+='<tr id="occ-row-'+r.id+'" class="'+(sel?'ot-sel':'')+venceFila(occVence,occAbierta)+'" style="cursor:pointer" title="Doble clic: ver el detalle de renglones" onclick="selOCC('+r.id+')">'
      +'<td><input type="radio" name="occ-sel" '+(sel?'checked':'')+' onclick="event.stopPropagation();selOCC('+r.id+')"></td>'
      +'<td><b>'+r.numero+'</b></td>'
      +'<td>'+r.cliente_nombre+'</td>'
      +'<td title="'+detalle.replace(/"/g,'&quot;')+'">Total pedido: <b>'+r._total+'</b> ('+r.items.length+' artículo'+(r.items.length!==1?'s':'')+')</td>'
      +'<td>'+fmtD(r.creado)+'</td>'
      +'<td'+venceCelda(occVence,occAbierta)+'>'+(r.fecha_entrega?fmtD(r.fecha_entrega):'—')+'</td>'
      +'<td>'+sb(r.estado)+'</td>'
      +'<td><span class="b '+avanceColor+'">'+avancePct+'%</span></td>'
      +'</tr>';
    if(_occExpandido===r.id){
      h+='<tr id="occ-det-'+r.id+'"><td colspan="'+(cols.length+1)+'" style="background:#fafaf8;padding:8px 14px">'+occDetalleHTML(r,avancePct)+'</td></tr>';
    }
  });
  $('occ-list').innerHTML=h+'</table>';
  if(_occSel && !_occ_cache.has(_occSel)){ _occSel=null; _occExpandido=null; }
  actualizarToolbarOCC();
}

// Detalle de renglones del pedido (se despliega con doble clic sobre la fila).
function occDetalleHTML(r,avancePct){
  let h='<table style="width:100%"><tr>'
    +'<th style="font-size:11px">Código</th><th style="font-size:11px">Producto</th>'
    +'<th style="font-size:11px">Cant.</th><th style="font-size:11px">Precio unit.</th>'
    +'<th style="font-size:11px">Precio total</th>'
    +'<th style="font-size:11px">F. deseada</th><th style="font-size:11px">OT</th>'
    +'<th style="font-size:11px">Avance</th>'
    +'</tr>';
  let precioTotalPedido=0;
  r.items.forEach(function(i){
    const ots=i.ots||[];
    const cubierto=i.cantidad_cubierta||0;
    const itAvPct=i.cantidad>0?Math.min(100,Math.round(cubierto/i.cantidad*100)):0;
    const completo=cubierto>=i.cantidad;
    const ocEntregada=avancePct>=100;
    let otCell;
    if(ROL==='logistica'){
      otCell=ots.length?ots.map(function(o){return o.ot_numero;}).join(', '):'Sin vincular';
    }else{
      otCell=ots.map(function(o){
        return '<span style="display:inline-flex;align-items:center;gap:2px">'
          +'<button class="btn btn-s" onclick="goToOT('+o.ot_id+')" style="color:var(--color-text-info)" title="Ir a la OT '+o.ot_numero+'">'+o.ot_numero+'</button>'
          +(ocEntregada?'':'<button class="btn btn-s btn-d" onclick="desvincularOTItem('+i.id+','+o.ot_id+')" title="Desvincular esta OT del pedido">Desvincular</button>')
          +'</span>';
      }).join(' ');
      if(!ocEntregada){
        otCell+=(ots.length?' ':'')+'<button class="btn btn-s" onclick="openVincularOT('+i.id+','+i.producto_id+','+JSON.stringify(i.producto_codigo+' - '+i.producto_nombre).replace(/"/g,'&quot;')+','+i.cantidad+','+cubierto+')" title="Vincular otra OT ya existente para cubrir lo que falta">'+(ots.length?'+ Vincular otra OT':'Vincular OT')+'</button>';
      }
    }
    h+='<tr style="font-size:11px">'
      +'<td>'+i.producto_codigo+'</td>'
      +'<td>'+i.producto_nombre+'</td>'
      +'<td>'+fN(i.cantidad)+' '+(i.unidad||'unid')+'</td>'
      +'<td>'+fmtM(i.precio_unit,r.moneda)+'</td>'
      +'<td><b>'+fmtM((parseFloat(i.precio_unit)||0)*(parseFloat(i.cantidad)||0))+'</b></td>'
      +'<td>'+(i.fecha_deseada?fmtD(i.fecha_deseada):'—')+'</td>'
      +'<td>'+otCell+'</td>'
      +'<td><span class="b '+(completo?'bg':(cubierto>0?'ba':'br'))+'">'+(completo?'Explotada':(cubierto>0?'Parcial ('+itAvPct+'%)':'Pendiente'))+'</span></td>'
      +'</tr>';
    precioTotalPedido+=(parseFloat(i.precio_unit)||0)*(parseFloat(i.cantidad)||0);
  });
  h+='<tr style="font-size:11px;border-top:1px solid var(--color-border-tertiary)">'
    +'<td colspan="4" style="text-align:right"><b>Precio total</b></td>'
    +'<td><b>'+fmtM(precioTotalPedido,r.moneda)+'</b></td>'
    +'<td colspan="3"></td>'
    +'</tr>';
  return h+'</table>';
}

// Un clic selecciona el pedido; doble clic despliega/oculta sus renglones
// (misma detección por tiempo que en OT, porque renderOCC() rehace la tabla).
function selOCC(id){
  const ahora=Date.now();
  const esDoble=(_occUltClick.id===id && ahora-_occUltClick.t<OT_DBLCLICK_MS);
  _occUltClick=esDoble?{id:null,t:0}:{id:id,t:ahora};
  _occSel=id;
  if(esDoble){
    try{window.getSelection().removeAllRanges();}catch(e){}
    _occExpandido=(_occExpandido===id)?null:id;
  }else if(_occExpandido && _occExpandido!==id){
    _occExpandido=null;
  }
  renderOCC();
}
function actualizarToolbarOCC(){
  const r=_occSel&&_occ_cache?_occ_cache.get(_occSel):null;
  const puedeEditar=['admin','vendedor'].includes(ROL);
  $('occ-sel-label').textContent=r?r.numero:'–';
  $('occ-b-avance').disabled=!r;
  const be=$('occ-b-edit');
  be.style.display=puedeEditar?'':'none';
  be.disabled=!r||!puedeEditar;
}
function occSelAccion(a){
  const r=_occSel&&_occ_cache?_occ_cache.get(_occSel):null;
  if(!r){toast('Seleccioná un pedido de la lista','w');return;}
  if(a==='avance') verAvanceOC(r.id,r.numero);
  else if(a==='edit') editOCC(r.id);
}

function openVincularOT(itemId,productoId,productoLabel,cantidad,cubierto){
  cubierto=cubierto||0;
  const restante=Math.max(0,(cantidad||0)-cubierto);
  $('vot-item-id').value=itemId;
  $('vot-producto-id').value=productoId||'';
  $('vot-item-info').innerHTML='Pieza requerida: <b>'+(productoLabel||'—')+'</b> — pedido: <b>'+cantidad+'</b>'
    +(cubierto>0?' — ya cubierto: <b>'+fN(cubierto)+'</b> — falta: <b>'+fN(restante)+'</b>':'')
    +'<br><span style="font-size:11px;color:var(--color-text-secondary)">Solo se muestran OTs del mismo material/producto. La opción se bloqueará apenas se cubra el total pedido.</span>';
  $('vot-results').innerHTML='<div class="em">Buscando OTs disponibles...</div>';
  openMo('mo-vincular-ot');
  buscarOTsVincular();
}

async function buscarOTsVincular(){
  const productoId=$('vot-producto-id').value;
  const params=[];
  if(productoId) params.push('producto_id='+encodeURIComponent(productoId));
  $('vot-results').innerHTML='<div class="ld">Buscando...</div>';
  let rows;
  try{ rows=await api('/api/ordenes/vinculables'+(params.length?('?'+params.join('&')):'')); }
  catch(e){ $('vot-results').innerHTML='<div class="em" style="color:red">Error: '+e.message+'</div>'; return; }
  if(!rows.length){$('vot-results').innerHTML='<div class="em">No se encontraron OTs disponibles para vincular.</div>';return;}
  let h='<table><tr><th>OT</th><th>Pieza</th><th>Cantidad</th><th>Estado</th><th>F. entrega</th><th></th></tr>';
  rows.forEach(function(r){
    h+='<tr>'
      +'<td><b>'+r.numero+'</b></td>'
      +'<td>'+(r.prod_codigo||'')+' '+(r.prod_nombre||r.descripcion||'')+'</td>'
      +'<td>'+fN(r.cantidad)+'</td>'
      +'<td>'+sb(r.estado)+'</td>'
      +'<td>'+(r.fecha_entrega?fmtD(r.fecha_entrega):'—')+'</td>'
      +'<td><button class="btn btn-s btn-p" onclick="vincularOT('+r.id+')">Vincular</button></td>'
      +'</tr>';
  });
  $('vot-results').innerHTML=h+'</table>';
}

async function desvincularOTItem(itemId,otId){
  if(!await confirmar('¿Desvincular esta OT del pedido? Esta acción no se puede deshacer.'))return;
  const res=await api('/api/ordenes_cliente_items/'+itemId+'/desvincular_ot/'+otId,{method:'DELETE'});
  if(!res.ok){toast(res.error||'Error','e');return;}
  toast('OT desvinculada del pedido');
  loadOCClientes();
}

async function vincularOT(otId){
  const itemId=$('vot-item-id').value;
  const res=await api('/api/ordenes_cliente_items/'+itemId+'/vincular_ot',{method:'POST',body:JSON.stringify({ot_id:otId})});
  if(!res.ok){toast(res.error||'Error','e');return;}
  toast('OT vinculada al pedido');
  closeMo('mo-vincular-ot');
  loadOCClientes();
}

async function openOCC(){
  $('occ-id').value='';
  $('occ-title').textContent='Nueva OC de cliente';
  $('occ-num').value='';
  $('occ-est').value='Recibida';
  $('occ-obs').value='';
  $('occ-fec').value=new Date().toISOString().slice(0,10);
  _occProd=[];_occItems={};_occItemsBloqueados=[];
  if(!_cli.length)_cli=await api('/api/clientes');
  $('occ-cli').value='';
  $('occ-cli-search').value='';
  $('occ-prod-grid').innerHTML='<div style="font-size:12px;color:var(--color-text-secondary)">Seleccioná un cliente para ver sus productos.</div>';
  openMo('mo-occ');
}

async function editOCC(id){
  const r=_occ_cache.get(id)||_occ_cache.get(parseInt(id));
  if(!r)return;
  $('occ-id').value=r.id;
  $('occ-title').textContent='Editar OC '+r.numero;
  $('occ-num').value=r.numero;
  $('occ-est').value=r.estado;
  $('occ-obs').value=r.obs||'';
  $('occ-fec').value=(r.fecha||'').slice(0,10);
  _occProd=[];_occItems={};_occItemsBloqueados=[];
  if(!_cli.length)_cli=await api('/api/clientes');
  const cliSel=_cli.find(function(c){return String(c.id)===String(r.cliente_id);});
  $('occ-cli').value=r.cliente_id||'';
  $('occ-cli-search').value=cliSel?cliSel.razon:'';
  await loadOCCProductos(r.items);
  openMo('mo-occ');
}

function filtrarOCCClientes(){
  const q=($('occ-cli-search').value||'').toLowerCase().trim();
  const cont=$('occ-cli-results');
  const lista=q?_cli.filter(function(c){return (c.razon||'').toLowerCase().includes(q);}):_cli;
  _novotResultsRender(cont,lista,function(c){return c.razon;},function(c){
    $('occ-cli').value=c.id;
    $('occ-cli-search').value=c.razon;
    cont.style.display='none';cont.innerHTML='';
    loadOCCProductos();
  });
}


// _occItems: { prodId: [{qty, precio, fecha, obs}, ...] }
async function loadOCCProductos(existingItems){
  const cid=$('occ-cli').value;
  const grid=$('occ-prod-grid');
  if(!cid){
    grid.innerHTML='<div style="font-size:12px;color:var(--color-text-secondary)">Seleccioná un cliente para ver sus productos.</div>';
    return;
  }
  grid.innerHTML='<div class="ld">Cargando productos...</div>';
  _occProd=await api('/api/productos?cliente_id='+cid);
  if(!_occProd.length && !(existingItems&&existingItems.length)){
    grid.innerHTML='<div class="em">Este cliente no tiene productos asignados. Asigná productos desde Procesos/Productos.</div>';
    return;
  }
  // Build _occItems from existingItems if provided
  _occItems={};
  _occItemsBloqueados=[];
  if(existingItems){
    existingItems.forEach(function(it){
      // Los ítems que ya tienen una OT generada no se reeditan ni se reenvían:
      // si se incluyeran en la grilla, al guardar se duplicarían (el backend
      // no borra ítems con ot_id, pero sí los vuelve a insertar).
      if(it.ot_id){
        _occItemsBloqueados.push(it);
        return;
      }
      if(!_occItems[it.producto_id]) _occItems[it.producto_id]=[];
      _occItems[it.producto_id].push({id:it.id,qty:it.cantidad,precio:it.precio_unit,fecha:it.fecha_deseada||'',obs:it.obs||''});
      // Producto que ya no está asignado al cliente: igual se muestra, si no
      // el renglón quedaba fuera de la grilla y se borraba al guardar.
      if(!_occProd.some(function(p){return String(p.id)===String(it.producto_id);}))
        _occProd.push({id:it.producto_id,codigo:it.producto_codigo||it.producto_id,nombre:it.producto_nombre||''});
    });
  }
  renderOCCGrid();
}

function renderOCCGrid(){
  const grid=$('occ-prod-grid');
  const st='font-size:12px;padding:6px 8px;border:1px solid #ddd;border-radius:6px;background:#fff;color:#1a1a1a;font-family:inherit;transition:border .15s';
  const q=($('occ-prod-search')?$('occ-prod-search').value:'').toLowerCase().trim();
  const prodList=q?_occProd.filter(function(p){
    return ((p.codigo||'')+' '+(p.nombre||'')).toLowerCase().includes(q);
  }):_occProd;

  let h='<div style="position:relative;margin-bottom:8px">';
  h+='<input type="text" id="occ-prod-search" placeholder="🔍 Buscar producto por código o nombre..." autocomplete="off" ';
  h+='value="'+(q?q.replace(/"/g,'&quot;'):'')+'" oninput="renderOCCGridPreserve()" ';
  h+='style="width:100%;font-size:12px;padding:7px 10px;border:1px solid #ddd;border-radius:7px">';
  h+='</div>';

  h+='<table class="occ-grid-table" style="width:100%;border-collapse:collapse;font-size:12px">';
  h+='<thead><tr style="background:#f7f7f4">';
  h+='<th style="padding:6px 8px;text-align:left;font-size:11px;font-weight:600;color:#888;text-transform:uppercase;letter-spacing:.04em">Producto</th>';
  h+='<th style="padding:6px 4px;width:80px;text-align:left;font-size:11px;font-weight:600;color:#888;text-transform:uppercase;letter-spacing:.04em">Cantidad</th>';
  h+=thM('Precio unit. $','style="padding:6px 4px;width:100px;text-align:left;font-size:11px;font-weight:600;color:#888;text-transform:uppercase;letter-spacing:.04em"');
  h+='<th style="padding:6px 4px;width:130px;text-align:left;font-size:11px;font-weight:600;color:#888;text-transform:uppercase;letter-spacing:.04em">Fecha entrega</th>';
  h+='<th style="padding:6px 4px;width:140px;text-align:left;font-size:11px;font-weight:600;color:#888;text-transform:uppercase;letter-spacing:.04em">Observaciones</th>';
  h+='<th style="width:70px;padding:6px 4px"></th>';
  h+='</tr></thead><tbody>';

  if(!prodList.length){
    h+='<tr><td colspan="6" style="padding:14px 8px;text-align:center;color:#999">Sin productos que coincidan con "'+q+'"</td></tr>';
  }

  prodList.forEach(function(p){
    const rows=(_occItems[p.id]&&_occItems[p.id].length)?_occItems[p.id]:[{qty:0,precio:p.precio_venta||'',fecha:'',obs:''}];
    rows.forEach(function(row,ri){
      const isFirst=ri===0;
      const rowId='occr_'+p.id+'_'+ri;
      h+='<tr id="'+rowId+'" data-prod="'+p.id+'" data-ri="'+ri+'"'+(row.id?' data-item-id="'+row.id+'"':'')+' style="border-bottom:1px solid #f0f0ec">';
      if(isFirst){
        h+='<td rowspan="'+rows.length+'" style="padding:8px;vertical-align:top;border-right:1px solid #e8e8e3;background:#fafaf8">';
        h+='<div style="font-weight:600;color:#1a1a1a">'+p.codigo+'</div>';
        h+='<div style="font-size:11px;color:#888;margin-top:1px">'+p.nombre+'</div>';
        h+='</td>';
      }
      h+='<td style="padding:5px 4px"><input data-f="qty" type="number" value="'+row.qty+'" min="0" step="1" style="'+st+';width:100%;max-width:74px" placeholder="0"></td>';
      h+=tdM('<input data-f="precio" type="number" value="'+row.precio+'" min="0" step="0.01" style="'+st+';width:100%;max-width:94px" placeholder="0.00">','style="padding:5px 4px"');
      h+='<td style="padding:5px 4px"><input data-f="fecha" type="date" value="'+row.fecha+'" style="'+st+';width:100%;max-width:128px"></td>';
      h+='<td style="padding:5px 4px"><input data-f="obs" type="text" value="'+row.obs+'" style="'+st+';width:100%;max-width:136px" placeholder="Obs..."></td>';
      h+='<td style="padding:5px 4px;white-space:nowrap">';
      if(isFirst) h+='<button class="btn btn-s btn-p" onclick="addOCCDate('+p.id+')">+ Fecha</button> ';
      h+='<button class="btn btn-s btn-d" onclick="removeOCCDate('+p.id+','+ri+')">✕</button>';
      h+='</td></tr>';
    });
  });
  h+='</tbody></table>';
  if(_occItemsBloqueados&&_occItemsBloqueados.length){
    h+='<div style="margin-top:8px;font-size:11px;color:var(--color-text-secondary)">';
    h+='Ítems ya con OT generada (no editables):</div>';
    h+='<table style="width:100%;border-collapse:collapse;font-size:12px;opacity:.7">';
    _occItemsBloqueados.forEach(function(it){
      h+='<tr><td style="padding:3px 8px">'+(it.producto_codigo||it.producto_id)+'</td>'
        +'<td style="padding:3px 8px">'+fN(it.cantidad)+'</td>'
        +'<td style="padding:3px 8px">'+(it.fecha_deseada||'—')+'</td>'
        +'<td style="padding:3px 8px">OT '+(it.ot_numero||it.ot_id)+'</td></tr>';
    });
    h+='</table>';
  }
  grid.innerHTML=h;
}

function addOCCDate(prodId){
  // Save current state first (merge, don't overwrite filtered-out products)
  const onScreen=readOCCGrid();
  Object.keys(onScreen).forEach(function(id){ _occItems[id]=onScreen[id]; });
  if(!_occItems[prodId]) _occItems[prodId]=[];
  _occItems[prodId].push({qty:0,precio:'',fecha:'',obs:''});
  renderOCCGrid();
  // Focus the new row's qty
  setTimeout(function(){
    const rows=document.querySelectorAll('[data-prod="'+prodId+'"]');
    const last=rows[rows.length-1];
    if(last) last.querySelector('[data-f="qty"]').focus();
  },50);
}

function removeOCCDate(prodId,ri){
  const onScreen=readOCCGrid();
  Object.keys(onScreen).forEach(function(id){ _occItems[id]=onScreen[id]; });
  if(_occItems[prodId]) _occItems[prodId].splice(ri,1);
  renderOCCGrid();
}

function readOCCGrid(){
  const result={};
  _occProd.forEach(function(p){
    const rows=document.querySelectorAll('[data-prod="'+p.id+'"]');
    if(!rows.length) return; // not currently rendered (filtered out) — keep previous state
    result[p.id]=[];
    rows.forEach(function(row){
      // Sin permiso monetario la columna de precio no existe (se borra del DOM).
      const pr=row.querySelector('[data-f="precio"]');
      result[p.id].push({
        id:row.dataset.itemId?parseInt(row.dataset.itemId):null,
        qty:row.querySelector('[data-f="qty"]').value,
        precio:pr?pr.value:'',
        fecha:row.querySelector('[data-f="fecha"]').value,
        obs:row.querySelector('[data-f="obs"]').value,
      });
    });
  });
  return result;
}

function renderOCCGridPreserve(){
  // Merge current on-screen values into _occItems (only for rows visible right now),
  // so filtering the search box doesn't discard quantities typed for other products.
  const cur=readOCCGrid();
  Object.keys(cur).forEach(function(id){ _occItems[id]=cur[id]; });
  const searchVal=$('occ-prod-search')?$('occ-prod-search').value:'';
  renderOCCGrid();
  const newInput=$('occ-prod-search');
  if(newInput){
    newInput.value=searchVal;
    newInput.focus();
    newInput.setSelectionRange(searchVal.length,searchVal.length);
  }
}

async function saveOCC(){
  const eid=$('occ-id').value;
  if(!$('occ-cli').value){toast('Seleccioná un cliente','w');return;}

  // Merge current on-screen values (only products currently rendered, since the
  // product search box may be filtering some rows out) into _occItems, then use
  // that merged state so filtered-out products aren't lost on save.
  const onScreen=readOCCGrid();
  Object.keys(onScreen).forEach(function(id){ _occItems[id]=onScreen[id]; });
  const grid=_occItems;
  const items=[];

  _occProd.forEach(function(p){
    const rows=grid[p.id]||[];
    rows.forEach(function(row){
      const qty=Math.max(0,Math.round(parseFloat(row.qty)||0));
      if(!qty) return;  // skip rows with qty=0
      const it={
        id:row.id||null,
        producto_id:p.id,
        cantidad:qty,
        fecha_deseada:row.fecha||null,
        obs:row.obs||null,
        unidad:'unid',
      };
      // Sin permiso monetario el precio no se manda: el servidor conserva el
      // guardado (o usa el de venta del producto en un renglón nuevo).
      if(VER_MONETARIO) it.precio_unit=parseFloat(row.precio)||0;
      items.push(it);
      // El precio de venta del producto se sincroniza en el propio backend
      // (ver _sync_precio_venta_producto en /api/ordenes_cliente) cuando el
      // precio unitario cargado acá difiere del precio_venta actual. Antes
      // se hacía con una segunda llamada desde acá a /api/productos, pero
      // esa ruta exige rol admin/operario y un vendedor no lo tiene: el
      // pedido se guardaba bien pero el precio del producto no cambiaba.
    });
  });

  // Si se está cancelando el pedido, no hace falta cargar cantidades nuevas
  // (por ejemplo cuando todos los renglones ya están cubiertos por una OT y
  // quedaron en 0, como en "Ítems ya con OT generada")
  // Se permite guardar una OC sin ítems: queda registrada sin ninguna OT
  // vinculada, y las OTs se pueden vincular manualmente después (botón
  // "Vincular OT") o generar con "Explotar".

  const body={
    cliente_id:parseInt($('occ-cli').value),
    fecha:$('occ-fec').value,
    estado:$('occ-est').value,
    obs:$('occ-obs').value,
    items:items,
  };

  let res;
  if(eid){
    const prev=_occ_cache.get(eid)||_occ_cache.get(parseInt(eid));
    if(body.estado==='Completada' && (!prev || prev.estado!=='Completada')
       && !await confirmar('Al completar la OC se completan también todas sus OTs vinculadas, aunque no estén terminadas.\n\nSe genera el PT solo por lo producido, se libera la reserva de lotes no consumida, se cancelan las OTT pendientes sin envíos y se quitan del Scheduling los bloques futuros.\n\n¿Continuar?')) return;
    res=await api('/api/ordenes_cliente/'+eid,{method:'PUT',body:JSON.stringify(body)});
  } else {
    res=await api('/api/ordenes_cliente',{method:'POST',body:JSON.stringify(body)});
  }
  if(!res.ok){toast(res.error||'Error','e');return;}

  toast(eid?'OC actualizada':'OC '+res.numero+' registrada');
  if(res.ots_completadas&&res.ots_completadas.length) toast('OTs completadas: '+res.ots_completadas.join(', '));
  if(res.ots_fallidas&&res.ots_fallidas.length) toast('No se pudieron completar: '+res.ots_fallidas.join(', '),'e');
  closeMo('mo-occ');
  _prod=[];  // refresh product cache (prices may have changed)
  loadOCClientes();
}


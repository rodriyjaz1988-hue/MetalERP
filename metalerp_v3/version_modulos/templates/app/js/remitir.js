// ── Remitir a cliente ─────────────────────────────────────────────────────────
let _remItems=[];

async function loadPTDisponible(){
  if(!_cli.length)_cli=await api('/api/clientes');
  const cliId=$('rem-cli-fil')?$('rem-cli-fil').value:'';
  const rows=await api('/api/pt_disponible'+(cliId?('?cliente_id='+encodeURIComponent(cliId)):''));
  if(!rows.length){$('rem-pt-list').innerHTML='<div class="em">Sin stock de productos terminados disponibles.</div>';return;}
  let h='<table><tr><th>Producto / Lote</th><th>Cliente</th><th>Disponible</th><th>OC vinculada</th><th></th></tr>';
  rows.forEach(function(r){
    const falta=r.oc_cantidad?(r.oc_cantidad-r.ya_remitido):null;
    h+='<tr>'
      +'<td><b>'+(r.mat_codigo?r.mat_codigo+' — ':'')+(r.mat_descripcion||'—')+'</b><br><span style="font-size:11px;color:var(--color-text-secondary)">'+r.numero+'</span></td>'
      +'<td style="font-size:11px">'+(r.producto_cliente_nombre||'—')+'</td>'
      +'<td><b>'+fN(r.cantidad_activa)+'</b> '+r.unidad+'<br><span style="font-size:10px;color:var(--color-text-secondary)">'+fN(r.cantidad_disponible)+' total</span></td>'
      +'<td>'+(falta!==null?'<span style="cursor:pointer;color:var(--color-accent);text-decoration:underline dotted" onclick="verAvanceOC('+r.orden_cliente_id+',\''+(r.oc_numero||'')+'\')" title="Ver avance de entrega">Pendiente: '+Math.max(0,falta).toFixed(2)+'</span>':'—')+'</td>'
      +'<td><button class="btn btn-s" onclick="addRemItem('+r.id+','+r.material_id+','+JSON.stringify(r.mat_descripcion).replace(/"/g,'&quot;')+','+r.cantidad_activa+',' +(r.oc_item_id||'null')+','+(r.orden_cliente_id||'null')+','+(r.oc_cliente_id||'null')+')">+ Agregar</button></td>'
      +'</tr>';
  });
  $('rem-pt-list').innerHTML=h+'</table>';
}

async function loadRemitirPage(){
  if(!_cli.length)_cli=await api('/api/clientes');
  cliBuscadorClear('rem-cli');
  loadPTDisponible();
  loadRemitidos();
}

async function loadRemitosEmitidosPage(){
  if(!_cli.length)_cli=await api('/api/clientes');
  cliBuscadorClear('rem-fil-cli');
  loadRemitidos();
}

async function loadOCsPendientes(){
  const cid=$('rem-cli').value;
  const sel=$('rem-oc');sel.innerHTML='<option value="">— Sin OC —</option>';
  if(!cid){ renderOCItems(null); return; }
  const ocs=await api('/api/ordenes_cliente?cliente_id='+cid);
  ocs.filter(function(o){return o.estado==='En proceso'||o.estado==='Confirmada'||o.estado==='Recibida';}).forEach(function(o){
    const opt=document.createElement('option');opt.value=o.id;opt.textContent=o.numero+(o.fecha_entrega?' — '+fmtD(o.fecha_entrega):'');opt.dataset.oc=JSON.stringify(o);sel.appendChild(opt);
  });
  await renderOCItems(null);
}

async function onRemOCChange(){
  const sel=$('rem-oc');
  const ocId=sel.value;
  if(!ocId){ renderOCItems(null); return; }
  const ocs=await api('/api/ordenes_cliente?cliente_id='+$('rem-cli').value);
  const oc=ocs.find(function(o){return String(o.id)===String(ocId);});
  renderOCItems(oc);
}

function renderOCItems(oc){
  let cont=document.getElementById('rem-oc-items');
  if(!cont){
    // Insert below the OC select
    const ocSel=$('rem-oc').parentElement;
    cont=document.createElement('div');cont.id='rem-oc-items';
    ocSel.insertAdjacentElement('afterend',cont);
  }
  if(!oc||!oc.items||!oc.items.length){cont.innerHTML='';return;}
  // Group items by fecha_deseada
  const byDate={};
  oc.items.forEach(function(i){
    const d=i.fecha_deseada||'Sin fecha';
    if(!byDate[d]) byDate[d]=[];
    byDate[d].push(i);
  });
  let h='<div style="margin:8px 0;padding:8px;background:var(--color-background-secondary);border-radius:6px;font-size:12px">';
  h+='<div style="font-weight:600;margin-bottom:6px;color:var(--color-text-secondary)">Renglones de la OC — seleccioná fecha de entrega a la que imputar:</div>';
  Object.keys(byDate).sort().forEach(function(d){
    h+='<div style="margin-bottom:4px;padding:6px;border:1px solid var(--color-border-tertiary);border-radius:4px">';
    h+='<label style="display:flex;align-items:center;gap:6px;cursor:pointer;font-weight:600">';
    h+='<input type="radio" name="rem-oc-date" value="'+d+'" style="width:14px;height:14px"> ';
    h+=(d==='Sin fecha'?'Sin fecha especificada':'Entrega: '+fmtD(d));
    h+='</label>';
    byDate[d].forEach(function(i){
      const restante=(i.cantidad_restante!==undefined)?i.cantidad_restante:i.cantidad;
      h+='<div style="margin-left:22px;font-size:11px;color:var(--color-text-secondary);margin-top:2px">';
      h+=i.producto_codigo+' - '+i.producto_nombre+' - '+fN(i.cantidad)+' '+i.unidad+' - '+fN(restante)+' '+i.unidad+' restante';
      h+='</div>';
    });
    h+='</div>';
  });
  h+='</div>';
  cont.innerHTML=h;
  // Auto-select the only date if there's just one
  const radios=cont.querySelectorAll('input[name="rem-oc-date"]');
  if(radios.length===1) radios[0].checked=true;
}

async function addRemItem(loteId,matId,desc,disp,ocItemId,ocId,ocCliId){
  // Si el lote está vinculado a una OC de cliente, completar Cliente y OC de Cliente
  if(ocId&&ocCliId){
    const cliSel=$('rem-cli');
    if(!cliSel.value){
      cliBuscadorSet('rem-cli',ocCliId);
      await loadOCsPendientes();
      const ocSel=$('rem-oc');
      ocSel.value=ocId;
      await onRemOCChange();
    }else if(String(cliSel.value)===String(ocCliId)){
      const ocSel=$('rem-oc');
      if(!ocSel.value){
        ocSel.value=ocId;
        await onRemOCChange();
      }
    }else{
      toast('Este lote pertenece a una OC de otro cliente','w');
    }
  }
  // If lote already in table, increase qty (capped at disp)
  const existing=$('rem-items').querySelector('input[data-lote="'+loteId+'"]');
  if(existing){
    const cur=parseFloat(existing.value)||0;
    const max=parseFloat(existing.dataset.disp)||disp;
    const nv=Math.min(cur+1,max);
    existing.value=nv;
    toast(nv>=max?'Máximo disponible: '+max+' u.':'Cantidad actualizada: '+nv, nv>=max?'w':'g');
    return;
  }
  const st='font-size:12px;padding:3px 6px;border:1px solid var(--color-border-tertiary);border-radius:5px;background:var(--color-background-primary);color:var(--color-text-primary);width:100%';
  const tr=document.createElement('tr');
  tr.innerHTML='<td>'+desc+'<br><span style="font-size:11px;color:var(--color-text-secondary)">Lote '+loteId+'</span></td>'
    +'<td>'+fN(disp)+'</td>'
    +'<td><input type="number" value="1" min="1" max="'+disp+'" step="1" style="'+st+'"'
      +' data-lote="'+loteId+'" data-mat="'+matId+'" data-oci="'+(ocItemId||'')+'" data-disp="'+disp+'"'
      +' onchange="capRemQty(this)"></td>'
    +'<td><button class="btn btn-s btn-d" onclick="this.parentElement.parentElement.remove()">×</button></td>';
  $('rem-items').appendChild(tr);
}

function capRemQty(inp){
  const max=parseFloat(inp.dataset.disp)||0;
  let v=Math.round(parseFloat(inp.value)||0);
  if(v>max) v=Math.floor(max);
  if(v<=0) v=1;
  inp.value=v;
}

async function saveRemito(){
  const cid=$('rem-cli').value;
  const ocid=$('rem-oc').value||null;
  if(!cid){toast('Seleccioná un cliente','w');return;}
  const rows=[...$('rem-items').querySelectorAll('tr')];
  if(!rows.length){toast('Agregá al menos un ítem','w');return;}
  const items=rows.map(function(tr){
    const inp=tr.querySelector('input[type=number]');
    return{lote_id:parseInt(inp.dataset.lote),material_id:parseInt(inp.dataset.mat),
      cantidad:parseFloat(inp.value),orden_cliente_item_id:inp.dataset.oci||null};
  }).filter(function(i){return i.lote_id&&i.cantidad>0;});
  const res=await api('/api/remitos',{method:'POST',body:JSON.stringify({
    cliente_id:parseInt(cid),orden_cliente_id:ocid?parseInt(ocid):null,
    obs:$('rem-obs').value,items:items
  })});
  if(res.ok){
    toast('Remito '+res.numero+' generado');
    $('rem-items').innerHTML='';$('rem-obs').value='';_remItems=[];
    loadPTDisponible();loadRemitidos(1);
  } else toast(res.error||'Error','e');
}

let _remPag=1, _remPaginas=1, _remReq=0, _remTimer=null;
let _remOpc={ocs:[],materiales:[]};

async function loadRemitidos(pag){
  if(!_cli.length)_cli=await api('/api/clientes');
  const q=new URLSearchParams();
  q.set('pagina', pag||_remPag||1);
  q.set('por_pagina', parseInt(($('rem-pp')||{}).value||25,10));
  const cli=$('rem-fil-cli')?$('rem-fil-cli').value:'';
  const mat=$('rem-fil-mat')?$('rem-fil-mat').value.trim().replace(/\s*—\s*/g,' '):'';
  const fecha=$('rem-fil-fecha')?$('rem-fil-fecha').value:'';
  const oc=$('rem-fil-oc')?$('rem-fil-oc').value.trim():'';
  if(cli)q.set('cliente_id',cli);
  if(mat)q.set('material',mat);
  if(fecha)q.set('fecha',fecha);
  if(oc)q.set('oc',oc);
  const req=++_remReq; // si el usuario sigue escribiendo, se descartan respuestas viejas
  $('rem-hist').innerHTML='<div class="ld">Cargando...</div>';
  const data=await api('/api/remitos?'+q.toString());
  if(req!==_remReq)return;
  if(!data||data.error||!data.rows){
    $('rem-hist').innerHTML='<div class="em">'+((data&&data.error)||'No se pudieron leer los remitos.')+'</div>';
    return;
  }
  _remPag=data.pagina; _remPaginas=data.paginas;
  _remData=data;
  renderRemitidos(data);
  api('/api/remitos/opciones').then(function(o){if(o&&o.ocs)_remOpc=o;});
}
function remPagina(d){
  const n=_remPag+d;
  if(n<1||n>_remPaginas)return;
  loadRemitidos(n);
}

function clearRemFiltros(){
  cliBuscadorClear('rem-fil-cli');
  $('rem-fil-mat').value='';
  $('rem-fil-fecha').value='';
  $('rem-fil-oc').value='';
  $('rem-fil-mat-sug').style.display='none';
  $('rem-fil-oc-sug').style.display='none';
  applyRemFiltros();
}

function onRemFilMatInput(){
  applyRemFiltros();
  const q=$('rem-fil-mat').value.trim().toLowerCase();
  const box=$('rem-fil-mat-sug');
  if(!q){box.style.display='none';return;}
  const seen={};
  const opts=[];
  (_remOpc.materiales||[]).forEach(function(i){
    const label=(i.codigo||'')+' — '+(i.descripcion||'');
    const key=label.toLowerCase();
    if(key.indexOf(q)!==-1&&!seen[key]){seen[key]=1;opts.push(label);}
  });
  if(!opts.length){box.style.display='none';return;}
  box.innerHTML=opts.slice(0,10).map(function(o){
    return '<div style="padding:5px 8px;font-size:12px;cursor:pointer" onmousedown="selectRemFilMat(\''+o.replace(/'/g,"\\'")+'\')">'+o+'</div>';
  }).join('');
  box.style.display='block';
}
function selectRemFilMat(v){
  $('rem-fil-mat').value=v;
  $('rem-fil-mat-sug').style.display='none';
  applyRemFiltros();
}

function onRemFilOcInput(){
  applyRemFiltros();
  const q=$('rem-fil-oc').value.trim().toLowerCase();
  const box=$('rem-fil-oc-sug');
  if(!q){box.style.display='none';return;}
  const seen={};
  const opts=[];
  (_remOpc.ocs||[]).forEach(function(n){
    const key=String(n).toLowerCase();
    if(key.indexOf(q)!==-1&&!seen[key]){seen[key]=1;opts.push(n);}
  });
  if(!opts.length){box.style.display='none';return;}
  box.innerHTML=opts.slice(0,10).map(function(o){
    return '<div style="padding:5px 8px;font-size:12px;cursor:pointer" onmousedown="selectRemFilOc(\''+o.replace(/'/g,"\\'")+'\')">'+o+'</div>';
  }).join('');
  box.style.display='block';
}
function selectRemFilOc(v){
  $('rem-fil-oc').value=v;
  $('rem-fil-oc-sug').style.display='none';
  applyRemFiltros();
}

function applyRemFiltros(){
  clearTimeout(_remTimer);
  _remTimer=setTimeout(function(){loadRemitidos(1);},250);
}

const REM_TIPOS={entrega_cliente:'Entrega a cliente',traslado_ott:'Envío a tercerizado',
  devolucion_ott:'Devolución OTT',devolucion_oc:'Devolución OC'};
function remTipoLbl(t){return REM_TIPOS[t||'entrega_cliente']||t;}
let _remSel=null, _remData=null;
function renderRemitidos(data){
  const rows=data.rows||[];
  window._remRows=new Map(rows.map(function(r){return [r.id,r];}));
  if(_remSel && !window._remRows.has(_remSel)) _remSel=null;
  if(!rows.length){
    $('rem-hist').innerHTML='<div class="em">Sin remitos emitidos.</div>';
  } else {
    let h='<table><tr><th style="width:24px"></th><th>Remito</th><th>Tipo</th><th>Destinatario</th><th>OC / OTT</th><th>Fecha</th><th>Ítems</th></tr>';
    rows.forEach(function(r){
      const its=r.items.map(function(i){return (i.mat_codigo||i.mat_descripcion||'')+(i.cantidad!=null?' x'+i.cantidad:'');}).join(', ');
      const ref=[r.oc_numero,r.ott_numero,r.oc_proveedor_numero].filter(Boolean).join(' · ')||'—';
      const sel=_remSel===r.id;
      h+='<tr class="'+(sel?'ot-sel':'')+'" style="cursor:pointer" onclick="selRem('+r.id+')" ondblclick="verRemito('+r.id+')">'
        +'<td><input type="radio" name="rem-sel" '+(sel?'checked':'')+' onclick="event.stopPropagation();selRem('+r.id+')"></td>'
        +'<td><b>'+r.numero+'</b>'+(r.estado==='Anulado'?' <span class="b br">Anulado</span>':'')+'</td>'
        +'<td><span class="b bt">'+remTipoLbl(r.tipo)+'</span></td>'
        +'<td>'+(r.destinatario||'—')+'</td>'
        +'<td>'+ref+'</td><td>'+fmtD(r.fecha)+'</td>'
        +'<td style="font-size:11px">'+its+'</td></tr>';
    });
    $('rem-hist').innerHTML=h+'</table>';
  }
  actualizarToolbarRem();
  const desde=data.total?((data.pagina-1)*data.por_pagina+1):0;
  const hasta=Math.min(data.pagina*data.por_pagina, data.total);
  $('rem-rango').textContent=data.total
    ? ('Mostrando '+desde.toLocaleString('es-AR')+'–'+hasta.toLocaleString('es-AR')
       +' de '+data.total.toLocaleString('es-AR')+' remitos')
    : 'Sin remitos';
  $('rem-pag-lbl').textContent='Página '+data.pagina+' de '+data.paginas;
  $('rem-prev').disabled=data.pagina<=1;
  $('rem-next').disabled=data.pagina>=data.paginas;
}

function selRem(id){ _remSel=id; if(_remData) renderRemitidos(_remData); }
function actualizarToolbarRem(){
  const r=_remSel&&window._remRows?window._remRows.get(_remSel):null;
  $('rem-sel-label').textContent=r?r.numero:'–';
  $('rem-b-ver').disabled=!r;
  $('rem-b-traz').disabled=!r;
  $('rem-b-pdf').disabled=!r;
}
function remSelAccion(a){
  const r=_remSel&&window._remRows?window._remRows.get(_remSel):null;
  if(!r){toast('Seleccioná un remito de la lista','w');return;}
  if(a==='ver') verRemito(r.id);
  else if(a==='traz') verTrazRemito(r.id);
  else if(a==='pdf') window.open('/api/remitos/'+r.id+'/pdf','_blank');
}
let _remDetId=null;
async function verRemito(id){
  _remDetId=id;
  $('rem-det-title').textContent='Remito';
  $('rem-det').innerHTML='<div class="ld">Cargando...</div>';
  openMo('mo-rem-det');
  const d=await api('/api/remitos/'+id);
  if(!d||d.error){$('rem-det').innerHTML='<div class="em">'+((d&&d.error)||'No se pudo leer el remito.')+'</div>';return;}
  const e=function(v){return (v==null||v==='')?'—':String(v).replace(/&/g,'&amp;').replace(/</g,'&lt;');};
  $('rem-det-title').textContent='Remito '+d.numero;
  const campo=function(l,v){return '<div><div style="font-size:11px;color:var(--color-text-secondary)">'+l+'</div><div style="font-size:13px;font-weight:500">'+v+'</div></div>';};
  let h='<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:12px 18px;margin-bottom:14px">';
  h+=campo('Tipo','<span class="b bt">'+remTipoLbl(d.tipo)+'</span>');
  h+=campo('Estado',d.estado==='Anulado'?'<span class="b br">Anulado</span>':'<span class="b bg">'+e(d.estado)+'</span>');
  h+=campo('Fecha',fmtD(d.fecha));
  h+=campo('Emitido por',e(d.creado_por_nombre));
  h+='</div>';
  const dst=d.destino||{};
  h+='<div style="font-size:12px;font-weight:600;margin:4px 0 6px">Remitido a</div>';
  h+='<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:12px 18px;margin-bottom:14px;padding:10px;border:1px solid var(--color-border-tertiary);border-radius:8px">';
  h+=campo(d.cliente_id?'Cliente':'Proveedor','<b>'+e(dst.razon)+'</b>');
  h+=campo('CUIT',e(dst.cuit));
  if(dst.direccion||dst.localidad) h+=campo('Dirección',e([dst.direccion,dst.localidad].filter(Boolean).join(', ')));
  h+=campo('Contacto',e([dst.contacto,dst.telefono].filter(Boolean).join(' · ')));
  h+='</div>';
  const ref=[];
  if(d.oc_cliente_numero) ref.push(campo('OC del cliente','<b>'+e(d.oc_cliente_numero)+'</b>'));
  if(d.ott_numero) ref.push(campo('OTT','<b>'+e(d.ott_numero)+'</b>'+(d.ott_estado?' <span style="font-size:11px;color:var(--color-text-secondary)">('+e(d.ott_estado)+')</span>':'')));
  if(d.ot_numero) ref.push(campo('OT de origen',e(d.ot_numero)));
  if(d.operacion_nombre) ref.push(campo('Operación tercerizada',e(d.operacion_nombre)));
  if(d.oc_numero) ref.push(campo('OC a proveedor','<b>'+e(d.oc_numero)+'</b>'));
  if(ref.length){
    h+='<div style="font-size:12px;font-weight:600;margin:4px 0 6px">Origen</div>';
    h+='<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:12px 18px;margin-bottom:14px">'+ref.join('')+'</div>';
  }
  h+='<div style="font-size:12px;font-weight:600;margin:4px 0 6px">Ítems</div>';
  if(!(d.items||[]).length) h+='<div class="em">Sin ítems registrados.</div>';
  else{
    h+='<table><tr><th>Código de pieza</th><th>Artículo</th><th>Cantidad</th><th>Unidad</th><th>Lote</th></tr>';
    d.items.forEach(function(i){
      h+='<tr><td><b>'+e(i.mat_codigo)+'</b></td><td>'+e(i.mat_descripcion)+'</td><td>'+(i.cantidad!=null?i.cantidad:'—')
        +'</td><td>'+e(i.unidad)+'</td><td>'+e(i.lote_numero)+'</td></tr>';
    });
    h+='</table>';
  }
  if(d.obs) h+='<div style="margin-top:12px;font-size:12px"><span style="color:var(--color-text-secondary)">Observaciones:</span> '+e(d.obs)+'</div>';
  $('rem-det').innerHTML=h;
}


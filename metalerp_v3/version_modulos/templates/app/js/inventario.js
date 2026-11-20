// ── Inventario ────────────────────────────────────────────────────────────────
let invC='';
let _invRawRows=[];
let _invRawIsPT=false;
let _invSortDir=''; // '', 'asc', 'desc'
document.querySelectorAll('#inv-tabs .tab').forEach(t=>t.addEventListener('click',()=>{
  document.querySelectorAll('#inv-tabs .tab').forEach(x=>x.classList.remove('active'));
  t.classList.add('active');invC=t.dataset.c;loadInv();
}));

function toggleInvSort(){
  _invSortDir = _invSortDir==='' ? 'desc' : (_invSortDir==='desc' ? 'asc' : '');
  const btn=$('inv-sort-btn');
  if(btn){
    btn.textContent = _invSortDir==='desc' ? 'Stock ▼ Mayor a menor' : (_invSortDir==='asc' ? 'Stock ▲ Menor a mayor' : 'Stock ⇅');
    btn.classList.toggle('btn-p', _invSortDir!=='');
  }
  renderInvFiltered();
}

async function loadInv(){
  // Productos terminados tab — same layout as other tabs, with all buttons
  if(invC==='PT'){
    const rows=await api('/api/materiales/productos_terminados');
    _mat_cache_pt=new Map(rows.map(function(r){return[r.id,r];}));
    _invRawRows=rows;_invRawIsPT=true;
    renderInvFiltered();
    return;
  }
  // Standard inventory view
  let rows=await api('/api/materiales'+(invC?'?categoria='+invC:''));_mat=rows;
  if(!invC)_mat_cache=new Map(rows.map(r=>[r.id,r]));
  else rows.forEach(function(r){_mat_cache.set(r.id,r);});
  _invRawRows=rows;_invRawIsPT=false;
  renderInvFiltered();
}

function filtrarInv(){renderInvFiltered();}

function renderInvFiltered(){
  const q=($('inv-search')?$('inv-search').value:'').trim().toLowerCase();
  let rows=_invRawRows||[];
  if(q){
    rows=rows.filter(function(r){
      const cod=(r.codigo||'').toLowerCase();
      const desc=(r.descripcion||r.producto_nombre||'').toLowerCase();
      return cod.includes(q)||desc.includes(q);
    });
  }
  if(_invSortDir){
    rows=rows.slice().sort(function(a,b){
      const sa=Number(a.stock)||0, sb=Number(b.stock)||0;
      return _invSortDir==='asc' ? sa-sb : sb-sa;
    });
  }
  window._invRows=new Map(rows.map(function(r){return [r.id,r];}));
  if(_invSel && !window._invRows.has(_invSel)) _invSel=null;
  if(_invRawIsPT){
    if(!rows.length){$('inv-list').innerHTML='<div class="em">'+(q?'No hay ítems que coincidan con la búsqueda.':'Sin stock de productos terminados. Declarar novedades de producción para generar stock.')+'</div>';actualizarToolbarInv();return;}
    let h='<table><tr><th style="width:24px"></th><th>Código</th><th>Producto</th><th>Cliente</th><th>Stock</th><th>Mín.</th><th>Máximo</th><th>Precio unit.</th><th>Estado</th></tr>';
    rows.forEach(function(r){
      const _cod='<a href="#" onclick="event.stopPropagation();goToMatMov('+r.id+');return false;" style="color:var(--color-text-info);text-decoration:none;font-weight:500">'+r.codigo+'</a>';
      const _cli=r.cliente_nombre?('<span class="b ba">'+r.cliente_nombre+'</span>'):'<span class="b bk">Sin cliente</span>';
      h+='<tr class="'+(_invSel===r.id?'ot-sel':'')+'" style="cursor:pointer" onclick="selInv('+r.id+')">'
        +'<td><input type="radio" name="inv-sel"'+(_invSel===r.id?' checked':'')+' onclick="event.stopPropagation();selInv('+r.id+')"></td>'
        +'<td>'+_cod+'</td>'
        +'<td>'+(r.producto_nombre||r.descripcion)+'</td>'
        +'<td>'+_cli+'</td>'
        +'<td><b>'+fN(r.stock)+'</b> '+r.unidad+'</td>'
        +'<td>'+fN(r.stock_min)+'</td>'
        +'<td>'+(r.stock_max||'—')+'</td>'
        +'<td>'+fmtM(r.precio_unit)+'</td>'
        +'<td>'+stBadge(r.stock,r.stock_min)+'</td>'
        +'</tr>';
    });
    $('inv-list').innerHTML=h+'</table>';
    actualizarToolbarInv();
    return;
  }
  if(!rows.length){$('inv-list').innerHTML='<div class="em">'+(q?'No hay ítems que coincidan con la búsqueda.':'No hay ítems. Usá «Agregar» para cargar el primero.')+'</div>';actualizarToolbarInv();return;}
  let h='<table><tr><th style="width:24px"></th><th>Código</th><th>Descripción</th><th>Tipo</th><th>Cat. producto</th><th>Stock</th><th>Nivel</th><th>Mín.</th><th>Máximo</th><th>Precio unit.</th><th>Proveedor</th><th>Estado</th></tr>';
  rows.forEach(r=>{
    const _cod='<a href="#" onclick="event.stopPropagation();goToMatMov('+r.id+');return false;" style="color:var(--color-text-info);text-decoration:none;font-weight:500">'+r.codigo+'</a>';
    const _cp=r.cat_prod_nombre?'<span class="b bt">'+r.cat_prod_nombre+'</span>':'—';
    h+='<tr class="'+(_invSel===r.id?'ot-sel':'')+'" style="cursor:pointer" onclick="selInv('+r.id+')">'
      +'<td><input type="radio" name="inv-sel"'+(_invSel===r.id?' checked':'')+' onclick="event.stopPropagation();selInv('+r.id+')"></td>'
      +'<td>'+_cod+'</td>'
      +'<td>'+r.descripcion+'</td>'
      +'<td><span class="b bk">'+r.categoria+'</span></td>'
      +'<td>'+_cp+'</td>'
      +'<td>'+fN(r.stock)+' '+r.unidad+'</td>'
      +'<td>'+stBar(r.stock,r.stock_min,r.stock_max)+'</td>'
      +'<td>'+fN(r.stock_min)+'</td>'
      +'<td>'+(r.stock_max||'—')+'</td>'
      +'<td>'+fmtM(r.precio_unit)+'</td>'
      +'<td>'+(r.proveedor_nombre||'—')+'</td>'
      +'<td>'+stBadge(r.stock,r.stock_min)+'</td>'
      +'</tr>';
  });
  $('inv-list').innerHTML=h+'</table>';
  actualizarToolbarInv();
}

// ── Selección de artículo + barra de herramientas de Inventario ───────────
let _invSel=null;
function selInv(id){ _invSel=id; renderInvFiltered(); }
function actualizarToolbarInv(){
  const r=_invSel&&window._invRows?window._invRows.get(_invSel):null;
  const lbl=$('inv-sel-label'); if(lbl) lbl.textContent=r?r.codigo:'–';
  const bt=$('inv-b-edit'); if(bt) bt.disabled=!r;
}
function invSelAccion(a){
  const r=_invSel&&window._invRows?window._invRows.get(_invSel):null;
  if(!r){toast('Seleccioná un artículo de la lista','w');return;}
  if(a==='edit') openEditMat(r.id);
}

async function _cargarClientesMat(px, cid){
  if(!_cli.length)_cli=await api('/api/clientes');
  await selLoad(px+'-cli',[{id:'',razon:'— Sin cliente —'},..._cli],cid||null);
}
async function openMat(){
  await _cargarClientesMat('mat',null);
  $('mat-bar').value=''; $('mat-tip').disabled=false; $('mat-tip').value='Material';
  if(!_catP.length)_catP=await api('/api/categorias_producto');
  if(!_prov.length)_prov=await api('/api/proveedores');
  await selLoad('mat-cp',[{id:'',nombre:'— Sin categoría —'},..._catP],null);
  await selLoad('mat-prv',[{id:'',razon:'— Sin proveedor —'},..._prov],null);
  openMo('mo-mat');
}

async function saveMat(){
  const body={codigo:$('mat-cod').value,descripcion:$('mat-des').value,categoria:$('mat-tip').value,
    cliente_id:$('mat-cli').value?parseInt($('mat-cli').value):null,codigo_barras:$('mat-bar').value.trim(),
    categoria_producto_id:$('mat-cp').value||null,unidad:$('mat-uni').value,
    stock:$('mat-stk').value||0,stock_min:$('mat-min').value||0,
    precio_unit:$('mat-pre').value||0,proveedor_id:$('mat-prv').value||null,obs:$('mat-obs').value};
  if(!body.codigo||!body.descripcion){toast('Código y descripción requeridos','w');return;}
  const res=await api('/api/materiales',{method:'POST',body:JSON.stringify(body)});
  if(res.ok){toast('Artículo agregado');closeMo('mo-mat');_mat=[];_prod=[];loadInv();}
  else toast(res.error||'Error','e');
}

// ── Recepción de material/insumo ────────────────────────────────────────────────
// Módulo central de recepción: acá se aprueban TODOS los ingresos a planta
// — directos, de Compras (OC) y de Terceros (OTT). Los botones "Recibir" y
// "Registrar retorno" ya no están en Órdenes de compra ni en OTT: la acción
// vive acá.
async function loadRecepciones(){
  loadRecOCPend();
  loadRecOTTPend();
}

function irAMovimientosRecepciones(){
  document.querySelectorAll('.ni').forEach(function(n){n.classList.remove('active');});
  document.querySelectorAll('.page').forEach(function(p){p.classList.remove('active');});
  const navEl=document.querySelector('[data-p="movimientos"]');
  if(navEl)navEl.classList.add('active');
  $('p-movimientos').classList.add('active');
  $('mov-origen-fil').value='recepciones';
  loadMovimientos();
}

function openRecSegunOC(){
  const ids=[..._recOcCache.keys()];
  if(!ids.length){toast('No hay OC pendientes de recibir','w');return;}
  $('recpick-oc').innerHTML=ids.map(function(id){const r=_recOcCache.get(id);return '<option value="'+id+'">'+r.numero+' — '+r.proveedor_nombre+'</option>';}).join('');
  openMo('mo-rec-pick-oc');
}
function continuarRecSegunOC(){
  const id=parseInt($('recpick-oc').value);
  closeMo('mo-rec-pick-oc');
  if(id) openRecOC(id);
}

// ── Pendientes de OC (Compras) — reemplaza el botón "Recibir" que antes
// estaba en Órdenes de compra. Reutiliza el mismo endpoint de recepción
// (/api/ordenes_compra/:id/recibir), solo que ahora se dispara desde acá.
let _recOcCache=new Map();
async function loadRecOCPend(){
  const ocs=await api('/api/ordenes_compra');
  const pend=(ocs||[]).filter(function(r){
    return ['Aprobada','Enviada','Recibida parcial','Cerrada'].includes(r.estado)
      && (r.items||[]).some(function(i){return !i.sc_ott_id && (i.cantidad-i.cantidad_recibida)>0.0001;});
  });
  _recOcCache=new Map(pend.map(function(r){return [r.id,r];}));
  // OC de servicio (OTT): no se reciben acá, vuelven con el retorno de la OTT.
  // Se listan igual con un aviso para que la OC aprobada no "desaparezca".
  const serv=[];
  (ocs||[]).forEach(function(r){
    if(!['Aprobada','Enviada','Recibida parcial','Cerrada'].includes(r.estado))return;
    (r.items||[]).forEach(function(i){
      if(i.sc_ott_id && (i.cantidad-i.cantidad_recibida)>0.0001) serv.push({oc:r,i:i});
    });
  });
  let hs='';
  if(serv.length){
    hs='<div style="margin-top:14px;font-weight:600">OC de servicio tercerizado</div>'
      +'<div style="font-size:12px;color:var(--color-text-secondary);margin:2px 0 6px">No se reciben acá: primero emití el remito de envío de la OTT desde Remitir; cuando vuelvan las piezas, registrá el retorno en "OTT pendientes de retorno".</div>'
      +'<table><tr><th>N°</th><th>Proveedor</th><th>Estado</th><th>OTT</th><th>Cantidad</th><th></th></tr>';
    serv.forEach(function(x){
      hs+='<tr><td><b>'+x.oc.numero+'</b></td><td>'+x.oc.proveedor_nombre+'</td><td>'+sb(x.oc.estado)+'</td>'
        +'<td><b>'+(x.i.ott_numero||'—')+'</b></td><td>'+fN(x.i.cantidad-x.i.cantidad_recibida)+'</td>'
        +'<td><span class="b ba" style="font-size:10px">Se recibe con el retorno de la OTT</span></td></tr>';
    });
    hs+='</table>';
  }
  if(!pend.length){$('rec-oc-pend-list').innerHTML='<div class="em">No hay OC pendientes de recibir. Acá aparecen las OC aprobadas que todavía esperan mercadería.</div>'+hs;return;}
  let h='<table><tr><th>N°</th><th>Proveedor</th><th>Estado</th><th>Pendiente</th><th></th></tr>';
  pend.forEach(function(r){
    const pendCant=(r.items||[]).reduce(function(a,i){return a+(i.sc_ott_id?0:Math.max(0,i.cantidad-i.cantidad_recibida));},0);
    h+='<tr><td><b>'+r.numero+'</b></td><td>'+r.proveedor_nombre+'</td><td>'+sb(r.estado)+'</td>'
      +'<td><b>'+fN(pendCant)+'</b></td>'
      +'<td><button class="btn btn-s btn-p" onclick="openRecOC('+r.id+')">Recibir</button></td></tr>';
  });
  $('rec-oc-pend-list').innerHTML=h+'</table>'+hs;
}

function openRecOC(id){
  const r=_recOcCache.get(id);
  if(!r){toast('OC no encontrada','e');return;}
  $('recoc-ocid').value=id;
  $('recoc-remito').value='';
  $('recoc-prv').textContent='Proveedor: '+r.proveedor_nombre;
  let h='<table><tr><th>Descripción</th><th>Pedido</th><th>Recibido</th><th>A recibir ahora</th></tr>';
  (r.items||[]).forEach(function(i){
    const pend=Math.max(0,i.cantidad-i.cantidad_recibida);
    if(pend<=0.0001 || i.sc_ott_id) return;
    h+='<tr><td>'+i.descripcion+'</td><td>'+fN(i.cantidad)+'</td><td>'+fN(i.cantidad_recibida)+'</td>'
      +'<td><input type="number" data-iid="'+i.id+'" value="'+pend+'" min="0" max="'+pend+'" step="0.01" style="width:80px;font-size:12px;padding:3px 6px;border:1px solid var(--color-border-tertiary);border-radius:5px;background:var(--color-background-primary);color:var(--color-text-primary)"></td></tr>';
  });
  $('recoc-items').innerHTML=h+'</table>';
  openMo('mo-oc-recibir');
}

async function saveRecOC(){
  const ocid=$('recoc-ocid').value;
  const items=[...$('recoc-items').querySelectorAll('input[data-iid]')].map(function(inp){
    return {item_id:parseInt(inp.dataset.iid),cantidad:parseFloat(inp.value)||0};
  }).filter(function(i){return i.cantidad>0;});
  if(!items.length){toast('Ingresá al menos una cantidad a recibir','w');return;}
  const res=await api('/api/ordenes_compra/'+ocid+'/recibir',{method:'POST',body:JSON.stringify({items,remito:($('recoc-remito').value||'').trim()||null})});
  if(res.ok){
    res._remito=$('recoc-remito').value||'';
    toast('Recepción registrada — stock actualizado');
    closeMo('mo-oc-recibir');
    loadRecOCPend();loadRecepciones();
    const _rem=(res._remito||'').trim(), _ref=(res.oc_numero||('OC '+ocid))+(_rem?' · Remito '+_rem:'');
    if(res.lotes&&res.lotes.length){
      abrirEtiquetasCola(res.lotes.map(function(l){return {origen:'Recepción OC',referencia:_ref,cantidad:l.cantidad,
        unidad:l.unidad||'',descripcion:(l.codigo?l.codigo+' — ':'')+(l.descripcion||''),codigo_barras:l.codigo_barras||'',
        lote:l.lote_numero,lote_id:l.lote_id,capacidad_cajon:l.capacidad_cajon,agregar:true};}));
    } else abrirEtiquetas({origen:'Recepción OC',referencia:_ref,cantidad:items.reduce(function(a,i){return a+i.cantidad;},0)});
  } else toast(res.error||'Error','e');
}

// ── Pendientes de OTT (Terceros) — reemplaza el botón "Registrar retorno"
// que antes estaba en OTT. El modal y las funciones abrirRetornoOTT /
// confirmarRetornoOTT siguen siendo las mismas (ver más abajo, sección OTT),
// solo que ahora se disparan desde acá.
async function loadRecOTTPend(){
  const rows=await api('/api/ott');
  const pend=(rows||[]).filter(function(r){return r.estado==='Remito emitido'||r.estado==='En proceso';});
  if(!pend.length){$('rec-ott-pend-list').innerHTML='<div class="em">No hay OTT pendientes de retorno. Acá aparecen las OTT enviadas a terceros que todavía no volvieron.</div>';return;}
  let h='<table><tr><th>N°</th><th>OT origen</th><th>Producto</th><th>Proveedor</th><th>Nivel</th><th>En espera</th><th></th></tr>';
  pend.forEach(function(r){
    const enEspera=Math.max((r.cantidad_enviada||0)-(r.cantidad_recibida||0),0);
    h+='<tr><td><b>'+r.numero+'</b></td><td>'+(r.ot_numero||'—')+'</td><td style="font-size:11px">'+(r.producto_codigo||'—')+'</td>'
      +'<td>'+(r.proveedor_nombre||'—')+'</td>'
      +'<td>'+(r.es_ultimo_nivel?'<span class="b bg" style="font-size:10px">PT</span>':'<span class="b ba" style="font-size:10px">Semi</span>')+'</td>'
      +'<td>'+(enEspera>0?'<b>'+fN(enEspera)+'</b>':'<span style="color:var(--color-text-secondary)">—</span>')+'</td>'
      +'<td><button class="btn btn-s btn-p" onclick="abrirRetornoOTT('+r.id+','+r.es_ultimo_nivel+')">Registrar retorno</button></td></tr>';
  });
  $('rec-ott-pend-list').innerHTML=h+'</table>';
}

async function openRecepcion(){
  if(!_mat.length)_mat=await api('/api/materiales');
  if(!_prov.length)_prov=await api('/api/proveedores');
  const selMat=$('rec-mat');
  selMat.innerHTML='<option value="">— Seleccionar material/insumo —</option>'+_mat.map(function(m){
    return '<option value="'+m.id+'">'+m.codigo+' — '+m.descripcion+' ('+(m.categoria||'')+')</option>';
  }).join('');
  const selProv=$('rec-prov');
  selProv.innerHTML='<option value="">— Ninguno —</option>'+_prov.map(function(p){
    return '<option value="'+p.id+'">'+p.razon+'</option>';
  }).join('');
  $('rec-qty').value='';$('rec-remito').value='';$('rec-precio').value='';$('rec-obs').value='';
  openMo('mo-recepcion');
}

async function saveRecepcion(){
  const material_id=$('rec-mat').value;
  const cantidad=parseFloat($('rec-qty').value);
  if(!material_id){toast('Seleccioná un material o insumo','w');return;}
  if(!cantidad||cantidad<=0){toast('Ingresá una cantidad válida','w');return;}
  const body={
    material_id:parseInt(material_id),
    cantidad,
    proveedor_id:$('rec-prov').value?parseInt($('rec-prov').value):null,
    remito:$('rec-remito').value||null,
    precio_unit:$('rec-precio').value?parseFloat($('rec-precio').value):null,
    obs:$('rec-obs').value||null,
  };
  let res=await api('/api/recepciones',{method:'POST',body:JSON.stringify(body)});
  // Hay OC abiertas con saldo de este material: el server pide confirmar
  // antes de registrarlo como recepción sin OC (lo normal es "Recibir OC").
  if(res.requiere_confirmacion){
    if(!await confirmar(res.error)) return;
    body.confirmar_sin_oc=true;
    res=await api('/api/recepciones',{method:'POST',body:JSON.stringify(body)});
  }
  if(res.ok){
    toast('Recepción '+res.numero+' registrada'+(res.lote?' — lote '+(res.lote_numero||res.lote)+' pendiente de aprobación de Calidad':' — stock actualizado'));
    const _mo=_mat.find(function(m){return String(m.id)===String(material_id);})||{};
    closeMo('mo-recepcion');_mat=[];_mat_cache=new Map();loadRecepciones();
    abrirEtiquetas({origen:'Recepción',referencia:res.numero+(body.remito?' · Remito '+body.remito:''),cantidad:cantidad,unidad:_mo.unidad||'',descripcion:(_mo.codigo?_mo.codigo+' — ':'')+(_mo.descripcion||''),codigo_barras:_mo.codigo_barras||'',
      lote:res.lote_numero||'',lote_id:res.lote||null,capacidad_cajon:res.capacidad_cajon});
  } else toast(res.error||'Error','e');
}


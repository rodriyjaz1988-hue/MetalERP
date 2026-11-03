// ── Compras ───────────────────────────────────────────────────────────────────
let compView='solicitudes',scTipo='',cotTipo='',_scRows=[],_scCots=[];

// Cada sub-vista de Compras tiene su propia fila de filtros y su propio
// botón de alta: los tres viven en el encabezado y se muestran según la
// pestaña activa. Qué botón puede ver cada rol lo define setupRoles(), que
// deja marcado `data-permitido`; acá solo se elige el de la vista actual.
const COMPRAS_VISTAS = ['solicitudes','cotizaciones','ocs'];
const COMPRAS_BOTON = {solicitudes:'b-sc', cotizaciones:'b-cot', ocs:'b-oc'};

function mostrarVistaCompras(v){
  COMPRAS_VISTAS.forEach(function(x){
    const cv=$('cv-'+x); if(cv) cv.style.display = (x===v?'block':'none');
    const cf=$('cf-'+x); if(cf) cf.style.display = (x===v?'':'none');
    const bt=$(COMPRAS_BOTON[x]);
    if(bt) bt.style.display = (x===v && bt.dataset.permitido==='1') ? '' : 'none';
  });
  actualizarToolbarCompras();
}

// Selección de fila en las tres vistas de Compras (mismo patrón que OT /
// Remitos): un radio por fila, clic en la fila selecciona y los botones del
// encabezado se habilitan según el estado de la fila elegida.
let _scSel=null, _cotSel=null, _ocSel=null, _cotRows=new Map();
function _cmpBtn(id,visible,habilitado,motivo){
  const b=$(id); if(!b) return;
  b.style.display=visible?'':'none';
  b.disabled=!habilitado;
  b.dataset.motivo=motivo||'';
}
function actualizarToolbarCompras(){
  const v=compView, lbl=$('cmp-sel-label');
  // Solicitudes
  const sc=_scSel?(_scRows||[]).find(function(x){return x.id===_scSel;}):null;
  const scCerrada=sc?['OC Emitida','Cerrada','Cancelada','Rechazada'].indexOf(sc.estado)!==-1:true;
  const scMot=sc?'La solicitud está '+sc.estado:'';
  _cmpBtn('sc-b-edit', v==='solicitudes', sc&&sc.estado!=='OC Emitida'&&sc.estado!=='Cancelada', scMot);
  _cmpBtn('sc-b-cot', v==='solicitudes', sc&&!scCerrada, scMot);
  _cmpBtn('sc-b-cancel', v==='solicitudes', sc&&!scCerrada, scMot);
  _cmpBtn('sc-b-reabrir', v==='solicitudes', sc&&sc.estado==='Cancelada', sc?'Solo para solicitudes canceladas':'');
  // Cotizaciones
  const c=_cotSel?_cotRows.get(_cotSel):null;
  const cAbierta=c&&['OC Emitida','Cerrada','Cancelada','Rechazada'].indexOf(c.solicitud_estado)===-1;
  const cotMot=c&&!cAbierta?'La solicitud de esta cotización está '+(c.solicitud_estado||'cerrada'):'';
  _cmpBtn('cot-b-sel', v==='cotizaciones', cAbierta&&!c.seleccionada, cotMot||(c?'Ya es la cotización elegida':''));
  _cmpBtn('cot-b-desel', v==='cotizaciones', cAbierta&&!!c.seleccionada, cotMot||(c?'Esta cotización no está elegida':''));
  _cmpBtn('cot-b-edit', v==='cotizaciones', cAbierta, cotMot);
  // OC emitidas (los botones que el rol no puede usar no se muestran)
  const oc=_ocSel&&typeof _oc_cache!=='undefined'&&_oc_cache?_oc_cache.get(_ocSel):null;
  const e=oc?oc.estado:'';
  const rolGestion=['admin','almacen','vendedor'].includes(ROL);
  const ocMot=oc?'No disponible para una OC en estado '+e:'';
  _cmpBtn('oc-b-aprobar', v==='ocs'&&['admin','vendedor'].includes(ROL), e==='Pendiente aprobacion', oc?'Solo para OC pendientes de aprobación':'');
  _cmpBtn('oc-b-emitir', v==='ocs', !!oc);
  _cmpBtn('oc-b-completar', v==='ocs'&&rolGestion, ['Aprobada','Enviada','Recibida parcial','Recibida','Cerrada'].includes(e), ocMot);
  _cmpBtn('oc-b-cerrar', v==='ocs', ['Aprobada','Enviada','Recibida parcial'].includes(e), oc?'Solo para OC aprobadas, enviadas o con recepción parcial':'');
  _cmpBtn('oc-b-dev', v==='ocs', !!oc&&(oc.rechazado_pendiente_devolver||0)>0.0001, oc?'La OC no tiene piezas rechazadas pendientes de devolver':'');
  _cmpBtn('oc-b-anular', v==='ocs'&&rolGestion, ['Pendiente aprobacion','Aprobada','Enviada','Recibida parcial'].includes(e), oc?'Solo se anula una OC que no recibió mercadería (estado actual: '+e+')':'');
  if(lbl) lbl.textContent = v==='solicitudes'?(sc?sc.numero:'–')
    : v==='cotizaciones'?(c?(c.proveedor_nombre||'Cotización'):'–')
    : (oc?oc.numero:'–');
}
function selSC(id){ _scSel=id; renderSC(); }
function selCotFila(id){
  _cotSel=id;
  document.querySelectorAll('#cot-list tr[data-cot]').forEach(function(tr){
    const s=Number(tr.dataset.cot)===id;
    tr.classList.toggle('ot-sel',s);
    const rb=tr.querySelector('input[name=cot-sel]'); if(rb) rb.checked=s;
  });
  actualizarToolbarCompras();
}
function selOC(id){
  _ocSel=id;
  document.querySelectorAll('#oc-list tr[data-oc]').forEach(function(tr){
    const s=Number(tr.dataset.oc)===id;
    tr.classList.toggle('ot-sel',s);
    const rb=tr.querySelector('input[name=oc-sel]'); if(rb) rb.checked=s;
  });
  actualizarToolbarCompras();
}
function scSelAccion(a){
  const r=_scSel?(_scRows||[]).find(function(x){return x.id===_scSel;}):null;
  if(!r){toast('Seleccioná una solicitud de la lista','w');return;}
  if(a==='edit') editSC(r.id);
  else if(a==='cot') openCotModalForSC(r.id, r.descripcion||'');
  else if(a==='cancel') cancelSC(r.id, r.numero, r.obs||'');
  else if(a==='reabrir') reabrirSC(r.id, r.numero);
}
function cotSelAccion(a){
  const c=_cotSel?_cotRows.get(_cotSel):null;
  if(!c){toast('Seleccioná una cotización de la lista','w');return;}
  if(a==='sel') selCot(c.id);
  else if(a==='desel') deselCot(c.id);
  else if(a==='edit') editCot(c);
}
function ocSelAccion(a){
  const r=_ocSel&&_oc_cache?_oc_cache.get(_ocSel):null;
  if(!r){toast('Seleccioná una OC de la lista','w');return;}
  if(a==='aprobar') aprobarOC(r.id);
  else if(a==='emitir') emitirOC(r.id);
  else if(a==='completar') completarOC(r.id);
  else if(a==='cerrar') cerrarOC(r.id);
  else if(a==='dev') devolverRechazoOC(r.id);
  else if(a==='anular') anularOC(r.id);
}

document.querySelectorAll('#comp-tabs .tab').forEach(t=>t.addEventListener('click',()=>{
  document.querySelectorAll('#comp-tabs .tab').forEach(x=>x.classList.remove('active'));
  t.classList.add('active');compView=t.dataset.cv;
  mostrarVistaCompras(compView);
  if(compView==='solicitudes')loadSC();
  else if(compView==='cotizaciones')loadCot();
  else loadOCs();
}));

document.querySelectorAll('#sc-tabs .tab').forEach(t=>t.addEventListener('click',()=>{
  document.querySelectorAll('#sc-tabs .tab').forEach(x=>x.classList.remove('active'));
  t.classList.add('active');scTipo=t.dataset.st;loadSC();
}));

document.querySelectorAll('#cot-tabs .tab').forEach(t=>t.addEventListener('click',()=>{
  document.querySelectorAll('#cot-tabs .tab').forEach(x=>x.classList.remove('active'));
  t.classList.add('active');cotTipo=t.dataset.ct;loadCot();
}));

let ocTipoFiltro='';
document.querySelectorAll('#oc-tabs .tab').forEach(t=>t.addEventListener('click',()=>{
  document.querySelectorAll('#oc-tabs .tab').forEach(x=>x.classList.remove('active'));
  t.classList.add('active');ocTipoFiltro=t.dataset.oct;loadOCs();
}));

// Limpia los filtros de la lista de OC emitidas (tipo, producto, proveedor).
function clearFiltrosOC(){
  ocTipoFiltro='';
  document.querySelectorAll('#oc-tabs .tab').forEach(x=>x.classList.remove('active'));
  const tTodas=document.querySelector('#oc-tabs .tab[data-oct=""]');
  if(tTodas) tTodas.classList.add('active');
  if($('oc-fil-prod'))$('oc-fil-prod').value='';
  if($('oc-fil-prov'))$('oc-fil-prov').value='';
  loadOCs();
}

async function cancelSC(id,numero,obs){
  if(!await confirmar('¿Estás seguro que quieres cancelar la '+numero+'?'))return;
  const res=await api('/api/solicitudes_compra/'+id,{method:'PUT',body:JSON.stringify({estado:'Cancelada',obs:obs||''})});
  if(res&&res.ok){toast('Solicitud cancelada');loadSC();updateSCBadge();}
  else toast((res&&res.error)||'Error al cancelar','e');
}

async function reabrirSC(id,numero){
  if(!await confirmar('¿Estás seguro que quieres reabrir la '+numero+'?'))return;
  const res=await api('/api/solicitudes_compra/'+id,{method:'PUT',body:JSON.stringify({estado:'Pendiente'})});
  if(res&&res.ok){toast('Solicitud reabierta');loadSC();updateSCBadge();}
  else toast((res&&res.error)||'Error al reabrir','e');
}

function loadComprasView(){ loadSC(); }

async function loadSC(){
  try {
  let rows=await api('/api/solicitudes_compra'+(scTipo?'?tipo='+scTipo:''));
  if($('sc-ocultar-canc')&&$('sc-ocultar-canc').checked){
    rows=rows.filter(r=>r.estado!=='Cancelada'&&r.estado!=='OC Emitida'&&r.estado!=='Cerrada'&&r.estado!=='Rechazada');
  }
  _scRows=rows;
  // Fetch cotizaciones grouped by solicitud
  // Sin permiso monetario el servidor niega las cotizaciones (tienen precios):
  // la lista de solicitudes se muestra igual, sin el mejor precio.
  _scCots = await api('/api/cotizaciones_compra');
  if(!Array.isArray(_scCots)) _scCots=[];
  renderSC();
  } catch(e) {
    console.error('[SC]', e);
    $('sc-list').innerHTML='<div class="em" style="color:red;font-size:11px">Error SC: '+e.message+'</div>';
  }
}

function renderSC(){
  try {
  let rows=_scRows||[];
  const q=($('sc-buscar')&&$('sc-buscar').value||'').trim().toLowerCase();
  if(q){
    rows=rows.filter(function(r){
      return (r.numero||'').toLowerCase().indexOf(q)>-1
        || (r.mat_codigo||'').toLowerCase().indexOf(q)>-1
        || (r.mat_nombre||'').toLowerCase().indexOf(q)>-1
        || (r.descripcion||'').toLowerCase().indexOf(q)>-1;
    });
  }
  if(_scSel && !rows.some(function(r){return r.id===_scSel;})) _scSel=null;
  actualizarToolbarCompras();
  if(!rows.length){$('sc-list').innerHTML='<div class="em">No hay solicitudes. Usá «Nueva solicitud» o generalas desde Planificación MRP.</div>';return;}
  const cots = _scCots||[];
  const cotBySC = {};
  cots.forEach(function(c){
    if(!cotBySC[c.solicitud_id]) cotBySC[c.solicitud_id]=[];
    cotBySC[c.solicitud_id].push(c);
  });
  let h='<table><tr><th style="width:24px"></th><th></th><th>N°</th><th>Tipo</th><th>Descripción / Material</th><th>Cantidad</th><th>OT</th><th>Urgencia</th><th>Estado</th><th>Mejor precio</th><th>OC vinculada</th></tr>';
  rows.forEach(function(r){
    const rcots = cotBySC[r.id]||[];
    const minCot = rcots.length ? rcots.reduce(function(a,b){return a.precio_unit<b.precio_unit?a:b;}) : null;
    const hasExp = rcots.length>0;
    const sel=_scSel===r.id;
    const editable=r.estado!=='OC Emitida'&&r.estado!=='Cancelada';
    h+='<tr id="scrow-'+r.id+'" class="'+(sel?'ot-sel':'')+'" style="cursor:pointer" onclick="selSC('+r.id+')"'+(editable?' ondblclick="editSC('+r.id+')"':'')+'>';
    h+='<td><input type="radio" name="sc-sel" '+(sel?'checked':'')+' onclick="event.stopPropagation();selSC('+r.id+')"></td>';
    h+='<td><button class="btn btn-s" style="padding:2px 5px;font-size:11px" ';
    h+='onclick="event.stopPropagation();toggleSCCots('+r.id+')">'+(!hasExp?'—':'▶')+'</button></td>';
    h+='<td><b>'+r.numero+'</b></td>';
    h+='<td><span class="b '+( r.tipo==='Productiva'?'bb':'bp')+'">'+r.tipo+'</span></td>';
    h+='<td>'+r.descripcion+(r.mat_nombre?'<br><span style="font-size:10px;color:var(--color-text-secondary)">'+(r.mat_codigo?'['+r.mat_codigo+'] ':'')+r.mat_nombre+'</span>':'')+(r.centro_costo?' <span class="b bp" style="font-size:12px;font-weight:600" title="Centro de costo">'+r.centro_costo+'</span>':'')+(r.obs&&r.obs.indexOf('Generada automáticamente')===0?' <span class="b bk" style="font-size:9px" title="'+r.obs.replace(/"/g,"&quot;")+'">⚙ Auto</span>':'')+'</td>';
    h+='<td>'+fN(r.cantidad)+' '+(r.mat_unidad||r.unidad||'')+'</td>';
    h+='<td>'+(r.ot_numero||'—')+'</td>';
    h+='<td><span class="b '+(r.urgencia==='Crítica'?'br':r.urgencia==='Alta'?'ba':'bk')+'">'+r.urgencia+'</span></td>';
    h+='<td>'+(r.estado==='OC Emitida'?'<span class="b bg">Emitida</span>':sb(r.estado))+'</td>';
    h+='<td>'+(minCot?'<span class="b bg">'+fmtMD(minCot.precio_unit)+'</span> '+minCot.proveedor_nombre:'—')+'</td>';
    h+='<td>'+(r.oc_numero?'<span class="b bt" style="cursor:pointer" onclick="event.stopPropagation();goToOC('+r.oc_id+')" title="Ver OC de compras">'+r.oc_numero+'</span>':'—')+'</td>';
    const ESTADOS_SC_CERRADOS=['OC Emitida','Cerrada','Cancelada','Rechazada'];
    const circuitoCerrado = ESTADOS_SC_CERRADOS.indexOf(r.estado)!==-1;
    h+='</tr>';
    // Hidden expandable cotizaciones rows
    h+='<tr id="sccots-'+r.id+'" style="display:none"><td colspan="11" style="padding:0">';
    h+='<div style="padding:6px 12px 8px 32px;background:var(--color-background-secondary)">';
    if(!rcots.length){
      h+='<div class="em" style="font-size:11px">Sin cotizaciones. Usá + Cot. para agregar.</div>';
    } else {
      const minP=Math.min(...rcots.map(function(c){return c.precio_unit;}));
      h+='<table style="font-size:11px"><tr><th>Proveedor</th><th>Precio unit.</th><th>Plazo</th><th>Condición</th><th>Total</th><th></th></tr>';
      rcots.forEach(function(c){
        const best=c.precio_unit===minP;
        h+='<tr style="'+(best?'background:#EAF3DE':'')+'">';
        h+='<td>'+c.proveedor_nombre+'</td>';
        h+='<td>'+(best?'<b>':'')+ fmtM(c.precio_unit)+(best?'</b> <span class="b bg" style="font-size:9px">✓ Mejor</span>':'') +'</td>';
        h+='<td>'+(c.plazo_entrega_dias||'—')+'d</td>';
        h+='<td>'+(c.condicion_pago||'—')+'</td>';
        h+='<td>'+fmtM(c.precio_unit*r.cantidad)+'</td>';
        h+='<td>'+(c.seleccionada?'<span class="b bg">✓ Seleccionada</span>':(circuitoCerrado?'<span style="color:var(--color-text-secondary)">—</span>':'<button class="btn btn-s btn-p" style="font-size:10px" onclick="selCot('+c.id+')">Seleccionar</button>'))+'</td>';
        h+='</tr>';
      });
      h+='</table>';
    }
    h+='</div></td></tr>';
  });
  $('sc-list').innerHTML=h+'</table>';
  } catch(e) {
    console.error('[SC render]', e);
    $('sc-list').innerHTML='<div class="em" style="color:red;font-size:11px">Error SC: '+e.message+'</div>';
  }
}

async function saveSC(){
  const id=$('sc-id').value;
  const tipo=$('sc-tipo').value;
  const body={tipo:tipo,descripcion:$('sc-des').value,cantidad:$('sc-qty').value,
    material_id:$('sc-mat').value||null,ot_origen_id:$('sc-ot').value||null,
    unidad:$('sc-uni').value,urgencia:$('sc-urg').value,
    centro_costo:$('sc-cc').value,obs:$('sc-obs').value};
  if(tipo==='Productiva'&&!body.material_id){toast('Seleccioná un material','w');return;}
  if(!body.descripcion||!body.cantidad){toast('Descripción y cantidad requeridas','w');return;}
  const res=await api(id?'/api/solicitudes_compra/'+id:'/api/solicitudes_compra',{method:id?'PUT':'POST',body:JSON.stringify(body)});
  if(res.ok){toast(id?'Solicitud actualizada':'Solicitud '+res.numero+' creada');closeMo('mo-sc');loadSC();updateSCBadge();}
  else toast(res.error||'Error','e');
}

let _scMatTipo='Productiva';
function fillSCMatSelect(tipo, selectedId){
  // Ya no llena un <select>: solo guarda el tipo actual (para filtrar por
  // categoría en filtrarSCMat) y precarga el buscador si viene un material
  // seleccionado (caso edición).
  _scMatTipo=tipo;
  $('sc-mat').value=selectedId||'';
  if(selectedId){
    const mat=_mat.find(function(m){return String(m.id)===String(selectedId);});
    $('sc-mat-search').value=mat?(mat.codigo+' — '+mat.descripcion):'';
  }else{
    $('sc-mat-search').value='';
  }
}

function filtrarSCMat(){
  const q=($('sc-mat-search').value||'').toLowerCase().trim();
  const cont=$('sc-mat-results');
  const cats = _scMatTipo==='Indirecta' ? ['Insumo','Herramienta'] : ['Material'];
  const base=_mat.filter(function(m){return cats.indexOf(m.categoria)!==-1;});
  const lista = q ? base.filter(function(m){
    const full=((m.codigo||'')+' '+(m.descripcion||'')).toLowerCase();
    return full.includes(q);
  }) : base;
  _novotResultsRender(cont,lista,function(m){return m.codigo+' — '+m.descripcion+(m.stock!==undefined?' (stock:'+fN(m.stock)+')':'');},function(m){
    $('sc-mat').value=m.id;
    $('sc-mat-search').value=m.codigo+' — '+m.descripcion;
    cont.style.display='none';cont.innerHTML='';
    onSCMatChange();
  });
}

function onSCTipoChange(){
  const tipo=$('sc-tipo').value;
  const isInd = tipo==='Indirecta';
  const lbl=document.getElementById('sc-mat-label');
  if(lbl) lbl.innerHTML = isInd ? 'Insumo/Herramienta' : 'Material <span class="req">*</span>';
  $('sc-mat-search').placeholder = isInd ? 'Buscar insumo/herramienta, o dejar vacío para ítem libre...' : 'Buscar por código o descripción...';
  fillSCMatSelect(tipo, $('sc-mat').value);
  onSCMatChange();
}

function onSCMatChange(){
  const mid = $('sc-mat').value;
  const tipo = $('sc-tipo').value;
  const desInput = $('sc-des');
  if(!mid){
    if(tipo==='Indirecta'){
      // Ítem libre: la descripción se escribe a mano
      desInput.readOnly=false;
      desInput.placeholder='Ej: Resma papel A4, guantes, repuesto varios...';
    }else{
      desInput.readOnly=true;
      desInput.value='';
      desInput.placeholder='Ej: Acero SAE 1045 barra 40mm';
    }
    $('sc-uni').value='';
    return;
  }
  const mat = _mat.find(function(m){ return String(m.id)===String(mid); });
  if(!mat) return;
  desInput.readOnly=true;
  desInput.value = mat.descripcion;
  $('sc-uni').value = mat.unidad||'';
}

async function openSCModal(){
  $('sc-id').value='';
  $('sc-modal-title').childNodes[0].textContent='Solicitud de compra ';
  if(!_mat.length)_mat=await api('/api/materiales');
  const rows=await api('/api/ordenes?estado=En proceso');
  const so=$('sc-ot');so.innerHTML='<option value="">— Sin OT —</option>';
  rows.forEach(function(r){const o=document.createElement('option');o.value=r.id;o.textContent=r.numero+' — '+(r.producto_nombre||r.descripcion);so.appendChild(o);});
  $('sc-tipo').value='Productiva';
  $('sc-des').value='';$('sc-qty').value='';$('sc-uni').value='';$('sc-cc').value='';$('sc-obs').value='';
  $('sc-urg').value='Normal';$('sc-ot').value='';
  onSCTipoChange();
  openMo('mo-sc');
  setTimeout(function(){ $('sc-mat-search').focus(); }, 80);
}

async function editSC(id){
  const r=_scRows.find(function(x){return x.id===id;});
  if(!r){toast('No se encontró la solicitud','e');return;}
  if(r.estado==='OC Emitida'){toast('No se puede editar: ya tiene una OC emitida','w');return;}
  if(r.estado==='Cancelada'){toast('No se puede editar: la solicitud está cancelada','w');return;}
  if(!_mat.length)_mat=await api('/api/materiales');
  const rows=await api('/api/ordenes?estado=En proceso');
  const so=$('sc-ot');so.innerHTML='<option value="">— Sin OT —</option>';
  rows.forEach(function(o2){const o=document.createElement('option');o.value=o2.id;o.textContent=o2.numero+' — '+(o2.producto_nombre||o2.descripcion);so.appendChild(o);});
  $('sc-id').value=r.id;
  $('sc-modal-title').childNodes[0].textContent='Editar solicitud '+r.numero+' ';
  $('sc-tipo').value=r.tipo||'Productiva';
  $('sc-ot').value=r.ot_origen_id||'';
  $('sc-qty').value=r.cantidad||'';
  $('sc-uni').value=r.unidad||'';
  $('sc-urg').value=r.urgencia||'Normal';
  $('sc-cc').value=r.centro_costo||'';
  $('sc-obs').value=r.obs||'';
  onSCTipoChange();
  fillSCMatSelect($('sc-tipo').value, r.material_id||'');
  onSCMatChange();
  if(!r.material_id){ $('sc-des').value=r.descripcion||''; $('sc-uni').value=r.unidad||''; }
  openMo('mo-sc');
}

async function loadCot(){
  let rows=await api('/api/cotizaciones_compra');
  if(!Array.isArray(rows)) rows=[];
  if(cotTipo) rows=rows.filter(r=>r.solicitud_tipo===cotTipo);
  if($('cot-ocultar-canc')&&$('cot-ocultar-canc').checked){
    rows=rows.filter(r=>r.solicitud_estado!=='Cancelada'&&r.solicitud_estado!=='OC Emitida'&&r.solicitud_estado!=='Cerrada'&&r.solicitud_estado!=='Rechazada');
  }
  _cotRows=new Map(rows.map(function(r){return [r.id,r];}));
  if(_cotSel && !_cotRows.has(_cotSel)) _cotSel=null;
  actualizarToolbarCompras();
  if(!rows.length){$('cot-list').innerHTML='<div class="em">No hay cotizaciones cargadas. Seleccioná una solicitud y usá «Cotización», o «Nueva cotización».</div>';return;}
  let grouped={};
  rows.forEach(r=>{if(!grouped[r.solicitud_id])grouped[r.solicitud_id]={desc:r.solicitud_desc,qty:r.sol_cantidad,uni:r.sol_unidad,estado:r.solicitud_estado,items:[]};grouped[r.solicitud_id].items.push(r);});
  const ESTADOS_CERRADOS=['OC Emitida','Cerrada','Cancelada','Rechazada'];
  let h='';
  Object.entries(grouped).forEach(([sid,g])=>{
    const minPrecio=Math.min(...g.items.map(i=>i.precio_unit));
    const circuitoCerrado = ESTADOS_CERRADOS.indexOf(g.estado)!==-1;
    h+=`<div style="margin-bottom:20px;padding:12px;border:1px solid var(--color-border,#e5e5e0);border-radius:8px;background:var(--color-background,#fff)"><div style="font-size:12px;font-weight:600;color:var(--color-text-secondary);margin-bottom:8px;padding-bottom:6px;border-bottom:1px solid var(--color-border,#e5e5e0)">${g.desc} — ${fN(g.qty)} ${g.uni||''}${circuitoCerrado?' <span class="b bk" style="font-size:9px" title="La solicitud ya cerró su circuito de compra: no se puede modificar la cotización seleccionada">🔒 Circuito cerrado</span>':''}</div>`;
    h+='<div class="nowrap-tbl"><table><tr><th style="width:24px"></th><th>Proveedor</th><th>Precio unit.</th><th>Plazo</th><th>Condición</th><th>Total</th><th>Elegida</th></tr>';
    g.items.forEach(c=>{
      const esMenor=c.precio_unit===minPrecio;
      const sel=_cotSel===c.id;
      const elegida = c.seleccionada
        ? `<span class="b bg">✓ Elegida</span>`
        : `<span style="color:var(--color-text-secondary)">—</span>`;
      h+=`<tr data-cot="${c.id}" class="${esMenor?'cot-row-menor':''}${sel?' ot-sel':''}" style="cursor:pointer" onclick="selCotFila(${c.id})"${circuitoCerrado?'':` ondblclick="selCotFila(${c.id});cotSelAccion('edit')"`}>
        <td><input type="radio" name="cot-sel" ${sel?'checked':''} onclick="event.stopPropagation();selCotFila(${c.id})"></td>
        <td>${c.proveedor_nombre}</td><td>${fmtMD(c.precio_unit)} ${esMenor?'<span class="b bg">Menor</span>':''}</td>
        <td>${c.plazo_entrega_dias}d</td><td>${c.condicion_pago||'—'}</td>
        <td>${fmtM(c.precio_unit*g.qty)}</td>
        <td>${elegida}</td></tr>`;
    });
    h+='</table></div></div>';   // cierra la tabla y el cuadro de la solicitud
  });
  $('cot-list').innerHTML=h;
}

function toggleSCCots(scId){
  const cotsRow=document.getElementById('sccots-'+scId);
  const btn=document.querySelector('#scrow-'+scId+' button');
  if(!cotsRow) return;
  const vis = cotsRow.style.display==='none'||cotsRow.style.display==='';
  cotsRow.style.display = vis ? 'table-row' : 'none';
  if(btn) btn.textContent = vis ? '▼' : '▶';
}

async function openCotModalForSC(scId, scDesc){
  _cotEditId=null;$('mo-cot').querySelector('.mh').firstChild.textContent='Nueva cotización ';
  // Populate the solicitud selector with just this SC pre-selected
  const ss=$('cot-sol');
  ss.innerHTML='<option value="'+scId+'">'+scDesc+'</option>';
  // Populate proveedores
  if(!_prov.length)_prov=await api('/api/proveedores');
  provCotSet(null);
  $('cot-pre').value='';$('cot-pla').value='3';$('cot-cond').value='';$('cot-obs').value='';
  openMo('mo-cot');
  setTimeout(function(){$('cot-prv-search').focus();},80);
}

async function selCot(id){
  const res=await api('/api/cotizaciones_compra/'+id+'/seleccionar',{method:'POST',body:JSON.stringify({})});
  if(res.ok){toast('Cotización seleccionada');loadCot();}
  else toast(res.error||'Error','e');
}

async function deselCot(id){
  const res=await api('/api/cotizaciones_compra/'+id+'/deseleccionar',{method:'POST',body:JSON.stringify({})});
  if(res.ok){toast('Cotización deseleccionada');loadCot();}
  else toast(res.error||'Error','e');
}

let _cotEditId=null;

async function editCot(c){
  _cotEditId=c.id;
  $('mo-cot').querySelector('.mh').firstChild.textContent='Editar cotización ';
  const ss=$('cot-sol');
  ss.innerHTML='<option value="'+c.solicitud_id+'">'+(c.solicitud_desc||'')+'</option>';
  if(!_prov.length)_prov=await api('/api/proveedores');
  provCotSet(c.proveedor_id);
  $('cot-pre').value=c.precio_unit;
  $('cot-pla').value=c.plazo_entrega_dias||3;
  $('cot-cond').value=c.condicion_pago||'';
  $('cot-obs').value=c.obs||'';
  openMo('mo-cot');
}

// ── Buscador de proveedor (modal de cotización) ──
function _provNombre(p){return p.nombre||p.razon||p.codigo||'';}
function provCotSet(pid){
  const p=pid?_prov.find(function(x){return x.id==pid;}):null;
  $('cot-prv').value=p?p.id:'';
  $('cot-prv-search').value=p?_provNombre(p):'';
  const c=$('cot-prv-results');if(c){c.style.display='none';c.innerHTML='';}
}
async function filtrarProvCot(){
  if(!_prov.length)_prov=await api('/api/proveedores');
  const q=($('cot-prv-search').value||'').toLowerCase().trim();
  const cont=$('cot-prv-results');
  const base=_prov.slice().sort(function(a,b){return _provNombre(a).localeCompare(_provNombre(b));});
  const lista=q?base.filter(function(p){
    return (_provNombre(p)+' '+(p.cuit||'')+' '+(p.contacto||'')).toLowerCase().includes(q);
  }):base;
  _novotResultsRender(cont,lista,_provNombre,function(p){
    $('cot-prv').value=p.id;
    $('cot-prv-search').value=_provNombre(p);
    cont.style.display='none';cont.innerHTML='';
  });
}

async function saveCot(){
  const body={solicitud_id:$('cot-sol').value,proveedor_id:$('cot-prv').value,
    precio_unit:$('cot-pre').value,plazo_entrega_dias:$('cot-pla').value||3,
    condicion_pago:$('cot-cond').value,obs:$('cot-obs').value};
  if(!body.proveedor_id&&$('cot-prv-search').value.trim()){toast('Elegí un proveedor de la lista de resultados','w');return;}
  if(!body.solicitud_id||!body.proveedor_id||!body.precio_unit){toast('Solicitud, proveedor y precio requeridos','w');return;}
  const editing=_cotEditId;
  const res=editing
    ? await api('/api/cotizaciones_compra/'+editing,{method:'PUT',body:JSON.stringify(body)})
    : await api('/api/cotizaciones_compra',{method:'POST',body:JSON.stringify(body)});
  if(res.ok){toast(editing?'Cotización actualizada':'Cotización guardada');_cotEditId=null;$('mo-cot').querySelector('.mh').firstChild.textContent='Nueva cotización ';closeMo('mo-cot');loadSC();loadCot();}
  else toast(res.error||'Error','e');
}

async function openCotModal(){
  _cotEditId=null;$('mo-cot').querySelector('.mh').firstChild.textContent='Nueva cotización ';
  const sc=await api('/api/solicitudes_compra');
  const ss=$('cot-sol');ss.innerHTML='<option value="">— Seleccionar solicitud —</option>';
  sc.forEach(s=>{const o=document.createElement('option');o.value=s.id;o.textContent=s.numero+' — '+s.descripcion;ss.appendChild(o);});
  if(!_prov.length)_prov=await api('/api/proveedores');
  provCotSet(null);
  openMo('mo-cot');
}

function goToOC(ocId){
  if(!ocId)return;
  document.querySelectorAll('#comp-tabs .tab').forEach(x=>x.classList.remove('active'));
  mostrarVistaCompras('ocs');
  const tOc=[...document.querySelectorAll('#comp-tabs .tab')].find(x=>x.dataset.cv==='ocs');
  if(tOc)tOc.classList.add('active');
  compView='ocs';
  ['solicitudes','cotizaciones','ocs'].forEach(v=>$('cv-'+v).style.display=v===compView?'block':'none');
  // Resetear filtros de la grilla de OC para asegurar que la OC buscada sea visible
  ocTipoFiltro='';
  document.querySelectorAll('#oc-tabs .tab').forEach(x=>x.classList.remove('active'));
  const tTodas=document.querySelector('#oc-tabs .tab[data-oct=""]');
  if(tTodas)tTodas.classList.add('active');
  if($('oc-fil-prov'))$('oc-fil-prov').value='';
  if($('oc-fil-prod'))$('oc-fil-prod').value='';
  loadOCs().then(function(){
    const row=$('oc-row-'+ocId);
    if(row){
      selOC(ocId);
      row.scrollIntoView({behavior:'smooth',block:'center'});
      toggleOCDetail(ocId);
      row.style.transition='background .3s';
      row.style.background='#EAF3DE';
      setTimeout(function(){row.style.background='';},1500);
    }
  });
}

async function loadOCs(){
  const all=await api('/api/ordenes_compra');
  _oc_cache=new Map(all.map(r=>[r.id,r]));

  // Poblar filtro de proveedores (una sola vez)
  const provSel=$('oc-fil-prov');
  if(provSel&&provSel.options.length<=1){
    const provs=[...new Map(all.map(r=>[r.proveedor_id,r.proveedor_nombre])).entries()]
      .sort((a,b)=>(a[1]||'').localeCompare(b[1]||''));
    provs.forEach(function(p){const o=document.createElement('option');o.value=p[0];o.textContent=p[1];provSel.appendChild(o);});
  }

  const provFiltro=provSel?provSel.value:'';
  const prodQ=($('oc-fil-prod')?$('oc-fil-prod').value:'').toLowerCase().trim();
  const rows=all.filter(r=>{
    if(provFiltro&&String(r.proveedor_id)!==String(provFiltro)) return false;
    const items=r.items||[];
    if(ocTipoFiltro&&!items.some(i=>i.sc_tipo===ocTipoFiltro)) return false;
    if(prodQ&&!items.some(i=>((i.mat_codigo||'')+' '+(i.mat_desc||'')+' '+(i.descripcion||'')).toLowerCase().includes(prodQ))) return false;
    return true;
  });

  if(_ocSel && !rows.some(r=>r.id===_ocSel)) _ocSel=null;
  actualizarToolbarCompras();
  if(!rows.length){$('oc-list').innerHTML='<div class="em">No hay OC emitidas para los filtros seleccionados.</div>';return;}
  let h='<div style="overflow-x:auto"><table><tr><th style="width:24px"></th><th></th><th>N°</th><th>Fecha emisión</th><th>Proveedor</th><th>Producto</th><th>SC vinculada</th><th>Total</th><th>Entrega est.</th><th>Estado</th><th>Aprobada por</th></tr>';
  rows.forEach(r=>{
    const scNums=[...new Set((r.items||[]).map(i=>i.sc_numero).filter(Boolean))];
    const scCell=scNums.length?scNums.map(n=>`<span class="b bt">${n}</span>`).join(' '):'—';
    const prods=[...new Set((r.items||[]).map(i=>(i.mat_codigo?i.mat_codigo+' — ':'')+(i.mat_desc||i.descripcion||'')).filter(Boolean))];
    const prodCell=prods.length?(prods.length>1?prods.map(p=>`<div>${p}</div>`).join(''):prods[0]):'—';
    const sel=_ocSel===r.id;
    const ocAbierta=!['Recibida','Completada','Anulada','Cancelada','Rechazada'].includes(r.estado);
    h+=`<tr id="oc-row-${r.id}" data-oc="${r.id}" class="${sel?'ot-sel':''}${venceFila(r.fecha_entrega_est,ocAbierta)}" style="cursor:pointer" onclick="selOC(${r.id})"${(r.items||[]).length?` ondblclick="toggleOCDetail(${r.id})"`:''}>
    <td><input type="radio" name="oc-sel" ${sel?'checked':''} onclick="event.stopPropagation();selOC(${r.id})"></td>
    <td>${(r.items||[]).length?`<button class="btn btn-s" style="padding:2px 8px" onclick="event.stopPropagation();toggleOCDetail(${r.id})">▶</button>`:''}</td>
    <td><b>${r.numero}</b></td><td>${fmtD(r.creado)}</td><td>${r.proveedor_nombre}</td><td>${prodCell}</td><td>${scCell}</td>
    <td><b>${fmtM(r.monto_total,r.moneda)}</b></td><td${venceCelda(r.fecha_entrega_est,ocAbierta)}>${fmtD(r.fecha_entrega_est)}</td>
    <td>${sb(r.estado)}</td><td>${r.aprobado_por_nombre||'—'}</td></tr>
    <tr id="oc-det-${r.id}" style="display:none"><td colspan="11" style="background:var(--color-background-secondary);padding:10px 14px">
    ${ocDetailTable(r.items||[],r.moneda)}
    </td></tr>`;
  });
  $('oc-list').innerHTML=h+'</table></div>';
}

function emitirOC(id){
  const r=_oc_cache.get(parseInt(id));
  if(!r){toast('OC no encontrada','e');return;}
  toast('Generando PDF...', 'g');
  // Genera el PDF en el servidor (ReportLab), con la misma estética que la OT
  window.open('/api/ordenes_compra/'+id+'/pdf', '_blank');
}

// Misma lógica de devolución de lotes que en OTT (ver abrirDevolucionOTT):
// devuelve al proveedor lo que Calidad haya clasificado como Rechazado en
// los lotes generados por esta OC y que todavía no se devolvió.
async function devolverRechazoOC(ocId){
  const r=_oc_cache.get(parseInt(ocId));
  if(!r){toast('OC no encontrada','e');return;}
  const cant=r.rechazado_pendiente_devolver||0;
  if(cant<=0.0001){toast('No hay piezas rechazadas pendientes de devolver','w');return;}
  if(!await confirmar('Se van a devolver '+fN(cant)+' pieza(s) rechazada(s) al proveedor '+(r.proveedor_nombre||'')+'.\n\nSe generará un remito de devolución y esa cantidad vuelve a quedar pendiente de recibir (reemplazo) en el mismo lote.\n\n¿Confirmar devolución?')) return;
  const res=await api('/api/ordenes_compra/'+ocId+'/devolver_rechazo',{method:'POST',body:JSON.stringify({})});
  if(res.ok){
    toast('Remito '+res.remito_numero+' emitido — '+fN(res.cantidad_devuelta)+' pieza(s) devuelta(s) al proveedor');
    loadOCs();
  } else toast(res.error||'Error','e');
}

// Cierre manual de la OC: se usa cuando quedó una recepción parcial (o
// nada recibido aún) y el saldo pendiente NO va a llegar más — el
// proveedor no va a entregar el resto. No toca lo ya recibido ni el lote;
// solo saca a la OC de la lista de "pendientes de recibir". Si más
// adelante el proveedor manda ese saldo igual, alcanza con volver a
// "Recibir": la OC se reabre sola y el lote vuelve a crecer.
async function cerrarOC(ocId){
  const r=_oc_cache.get(parseInt(ocId));
  if(!r){toast('OC no encontrada','e');return;}
  const items=r.items||[];
  const pendiente=items.reduce((a,i)=>a+Math.max(0,(i.cantidad||0)-(i.cantidad_recibida||0)),0);
  const msg=pendiente>0.0001?
    'Vas a cerrar la OC '+r.numero+' con '+fN(pendiente)+' unidad(es) todavía pendientes de recibir.\n\nEsto asume que el proveedor NO va a entregar el resto. Lo ya recibido no se modifica.\n\nSi más adelante llega igual, podés volver a "Recibir" y la OC se reabre sola.\n\n¿Confirmar cierre?':
    '¿Cerrar la OC '+r.numero+'?';
  if(!await confirmar(msg)) return;
  const res=await api('/api/ordenes_compra/'+ocId+'/cerrar',{method:'POST',body:JSON.stringify({})});
  if(res.ok){toast('OC '+r.numero+' cerrada');loadOCs();}
  else toast(res.error||'Error','e');
}

async function anularOC(ocId){
  const r=_oc_cache.get(parseInt(ocId));
  if(!r){toast('OC no encontrada','e');return;}
  const motivo=await pedirTexto('¿Anular la OC '+r.numero+' ('+(r.proveedor_nombre||'')+')?\nLas solicitudes de compra vuelven a quedar disponibles.\n\nMotivo de la anulación (opcional):');
  if(motivo===null) return;
  const res=await api('/api/ordenes_compra/'+ocId+'/anular',{method:'POST',body:JSON.stringify({motivo:motivo})});
  if(res.ok){toast('OC '+r.numero+' anulada');loadOCs();}
  else toast(res.error||'Error','e');
}

let _compOCId=null;
async function completarOC(ocId){
  const r=_oc_cache.get(parseInt(ocId));
  if(!r){toast('OC no encontrada','e');return;}
  const info=await api('/api/ordenes_compra/'+ocId+'/remitos');
  _compOCId=ocId;
  $('compoc-titulo').textContent='Completar OC '+r.numero+' — '+(r.proveedor_nombre||'');
  const directa=info&&info.tipo==='Directa';
  $('compoc-tipo').innerHTML=directa
    ?'<b>OC directa:</b> es obligatorio vincular el remito del proveedor correspondiente.'
    :'<b>OC indirecta:</b> el remito es opcional.';
  const sel=$('compoc-remito-sel');
  sel.innerHTML='<option value="">— Elegir remito ya recibido —</option>'+((info&&info.remitos)||[]).map(function(x){return '<option>'+x+'</option>';}).join('');
  $('compoc-remito').value=(info&&info.remito_numero)||((info&&info.remitos&&info.remitos.length)?info.remitos[info.remitos.length-1]:'');
  $('compoc-remito-req').style.display=directa?'':'none';
  const pend=(r.items||[]).reduce(function(a,i){return a+Math.max(0,(i.cantidad||0)-(i.cantidad_recibida||0));},0);
  $('compoc-pend').textContent=pend>0.0001?('Atención: quedan '+fN(pend)+' unidad(es) sin recibir; se dan por no entregadas.'):'';
  openMo('mo-comp-oc');
}
async function confirmarCompletarOC(){
  const res=await api('/api/ordenes_compra/'+_compOCId+'/completar',{method:'POST',body:JSON.stringify({remito:$('compoc-remito').value.trim()})});
  if(res.ok){toast('OC completada');closeMo('mo-comp-oc');loadOCs();}
  else toast(res.error||'Error','e');
}

function ocDetailTable(items,mon){
  if(!items.length) return '<div class="em">Sin ítems.</div>';
  let h='<table style="width:100%"><tr><th>N° SC</th><th>Tipo</th><th>Desc./Material</th><th>Cantidad</th><th>Prec. unitario</th><th>Precio total</th></tr>';
  items.forEach(function(i){
    const total=(i.precio_unit||0)*(i.cantidad||0);
    h+='<tr>'
      +'<td>'+(i.sc_numero||'—')+'</td>'
      +'<td>'+(i.sc_tipo||'—')+'</td>'
      +'<td>'+((i.mat_codigo?i.mat_codigo+' — ':'')+(i.mat_desc||i.descripcion||''))+'</td>'
      +'<td>'+fN(i.cantidad)+' '+(i.unidad||'')+'</td>'
      +'<td>'+fmtMD(i.precio_unit,mon)+'</td>'
      +'<td><b>'+fmtM(total,mon)+'</b></td>'
      +'</tr>';
  });
  return h+'</table>';
}

function toggleOCDetail(id){
  const row=document.getElementById('oc-det-'+id);
  const btn=document.getElementById('oc-row-'+id).querySelector('button');
  if(!row) return;
  const vis=row.style.display==='none'||row.style.display==='';
  row.style.display=vis?'table-row':'none';
  if(btn) btn.textContent=vis?'▼':'▶';
}

async function openOCModal(){
  $('oc-ent').value='';$('oc-obs').value='';
  $('oc-total').textContent='$0';$('oc-total').style.color='inherit';
  $('oc-prov-info').textContent='—';
  _ocScSel = new Map(); // solicitud_id -> {solicitud, cotizacion}
  const scs=await api('/api/solicitudes_compra');
  let cots=await api('/api/cotizaciones_compra');
  if(!Array.isArray(cots)) cots=[];
  const seleccionadaPorSC={};
  cots.forEach(function(c){ if(c.seleccionada) seleccionadaPorSC[c.solicitud_id]=c; });
  _ocScPend=scs.filter(function(s){return s.estado!=='OC Emitida'&&s.estado!=='Rechazada'&&s.estado!=='Cerrada'&&s.estado!=='Cancelada';});
  _ocScCotMap=seleccionadaPorSC;
  renderOCScList();
  openMo('mo-oc');
}

let _ocScSel=new Map(), _ocScPend=[], _ocScCotMap={};

function renderOCScList(){
  if(!_ocScPend.length){
    $('oc-sc-list').innerHTML='<div class="em" style="padding:12px">No hay solicitudes de compra pendientes de OC.</div>';
    return;
  }
  // Proveedor ya fijado por la primera SC elegida (si hay alguna elegida) —
  // las demás SC solo se pueden tildar si su cotización es del mismo proveedor.
  const primerSel=[..._ocScSel.values()][0];
  const provFijado=primerSel?primerSel.cotizacion.proveedor_id:null;
  let h='<table style="width:100%"><tr><th style="width:26px"></th><th>N° SC</th><th>Tipo</th><th>Descripción</th><th>Cant.</th><th>Proveedor (cotización)</th><th>Prec. unit.</th><th>Total</th></tr>';
  _ocScPend.forEach(function(s){
    const cot=_ocScCotMap[s.id];
    const checked=_ocScSel.has(s.id);
    const sinCot=!cot;
    const otroProveedor=cot&&provFijado&&cot.proveedor_id!==provFijado;
    const disabled=sinCot||otroProveedor;
    const total=cot?(cot.precio_unit*s.cantidad):0;
    h+='<tr style="'+(disabled&&!checked?'opacity:.45':'')+'">'
      +'<td><input type="checkbox" '+(checked?'checked':'')+(disabled&&!checked?' disabled':'')+' onchange="toggleOCSC('+s.id+',this.checked)"></td>'
      +'<td><b>'+s.numero+'</b></td>'
      +'<td>'+(s.tipo||'—')+'</td>'
      +'<td>'+s.descripcion+'</td>'
      +'<td>'+fN(s.cantidad)+' '+(s.mat_unidad||s.unidad||'')+'</td>'
      +'<td>'+(cot?cot.proveedor_nombre:'<span style="color:#A32D2D">sin cotización seleccionada</span>')+'</td>'
      +'<td>'+(cot?fmtMD(cot.precio_unit):'—')+'</td>'
      +'<td>'+(cot?fmtM(total):'—')+'</td>'
      +'</tr>';
  });
  $('oc-sc-list').innerHTML=h+'</table>';
  updateOCTotal();
}

function toggleOCSC(sid,checked){
  const sol=_ocScPend.find(function(s){return s.id===sid;});
  const cot=_ocScCotMap[sid];
  if(!sol||!cot) return;
  if(checked) _ocScSel.set(sid,{solicitud:sol,cotizacion:cot});
  else _ocScSel.delete(sid);
  renderOCScList();
}

function updateOCTotal(){
  let total=0;
  _ocScSel.forEach(function(v){ total+=v.cotizacion.precio_unit*v.solicitud.cantidad; });
  $('oc-total').textContent=fmtM(total);
  $('oc-total').style.color=total>50000?'#A32D2D':'inherit';
  const primerSel=[..._ocScSel.values()][0];
  $('oc-prov-info').textContent=primerSel?primerSel.cotizacion.proveedor_nombre:'—';
}

async function saveOC(){
  if(!_ocScSel.size){toast('Elegí al menos una solicitud de compra con cotización seleccionada','w');return;}
  const vals=[..._ocScSel.values()];
  const proveedor_id=vals[0].cotizacion.proveedor_id;
  const items=vals.map(function(v){
    return {material_id:v.solicitud.material_id||null,descripcion:v.solicitud.descripcion,
      cantidad:v.solicitud.cantidad,precio_unit:v.cotizacion.precio_unit,
      unidad:v.solicitud.mat_unidad||v.solicitud.unidad,solicitud_id:v.solicitud.id};
  });
  const body={proveedor_id,fecha_entrega_est:$('oc-ent').value,obs:$('oc-obs').value,items};
  const res=await api('/api/ordenes_compra',{method:'POST',body:JSON.stringify(body)});
  if(res.ok){
    let msg=res.estado==='Pendiente aprobacion'?
      `OC ${res.numero} creada — requiere aprobación (monto ${fmtM(res.total)})`:
      `OC ${res.numero} aprobada automáticamente`;
    if(res.lotes&&res.lotes.length) msg+=` — ${res.lotes.length} lote(s) generado(s) (${res.lotes.join(', ')}), pendiente de aprobación de Calidad`;
    toast(msg,res.estado==='Pendiente aprobacion'?'w':'g');
    closeMo('mo-oc');loadOCs();updateSCBadge();
    if(typeof loadSC==='function') loadSC();
    if(typeof loadCot==='function') loadCot();
  } else toast(res.error||'Error','e');
}


function mrpAgregarSC(matId){
  const r=_mrpCrit.get(matId); if(!r) return;
  agregarSCDesdeMRP(r.id,r.codigo,r.descripcion||'',r.cant_sc,r.unidad,r.categoria==='Material'?'Productiva':'Indirecta');
}
async function agregarSCDesdeMRP(matId,codigo,desc,cant,unidad,tipo){
  if(!cant||cant<=0){toast('No hay faltante para generar SC','w');return;}
  if(!await confirmar('¿Generar Solicitud de Compra por '+fN(cant)+' '+unidad+' de "'+codigo+' — '+desc+'"?')) return;
  const btn=$('mrp-sc-'+matId);
  if(btn){btn.disabled=true;btn.textContent='...';}
  try{
    const body={material_id:matId,tipo:tipo||'Productiva',descripcion:codigo+' — '+desc,cantidad:cant,unidad:unidad,urgencia:'Alta'};
    const r=await api('/api/solicitudes_compra',{method:'POST',body:JSON.stringify(body)});
    if(r&&r.ok){toast('SC '+r.numero+' generada por '+fN(cant)+' '+unidad,'g');}
    loadMRP();
  }catch(e){
    toast(e.message||'Error al generar la SC','r');
    if(btn){btn.disabled=false;btn.textContent='+ SC';}
  }
}


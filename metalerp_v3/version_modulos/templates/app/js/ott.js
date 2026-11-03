// ── OTT — Órdenes de Trabajo de Terceros ─────────────────────────────────────
// "Ocultar cerradas": esconde OTTs cuya OT de origen ya esté
// Completada/Cancelada, o cuya propia OTT esté Completada — son OTTs que ya
// cumplieron su ciclo y no requieren más acción, solo generan ruido en la
// lista. Se recuerda la preferencia entre sesiones (localStorage).
function _ottOcultarCerradas(){
  const v=localStorage.getItem('ott_ocultar_cerradas');
  return v===null?true:v==='1'; // default: ocultas
}
function _renderOttOcultarBtn(){
  const btn=$('ott-ocultar-btn'); if(!btn) return;
  const activo=_ottOcultarCerradas();
  btn.textContent=activo?'👁 Mostrar cerradas':'🚫 Ocultar cerradas';
  btn.classList.toggle('btn-p',!activo);
}
function toggleOcultarOTTCerradas(){
  localStorage.setItem('ott_ocultar_cerradas', _ottOcultarCerradas()?'0':'1');
  loadOTT();
}
// ── Selección de OTT + barra de herramientas (mismo patrón que Procesos/Productos) ──
let _ottSel=null;
let _ottRows=[];
let _ottQ='';
function _ottCerrada(r){
  const otCerrada=r.ot_estado==='Completada'||r.ot_estado==='Cancelada';
  const ottCerrada=r.estado==='Completado'||r.estado==='Cancelado';
  return otCerrada||ottCerrada;
}
function selOTT(id){ _ottSel=id; renderOTT(); }
function actualizarToolbarOTT(){
  const r=_ottSel&&window._ottMap?window._ottMap.get(_ottSel):null;
  const cerrada=r?_ottCerrada(r):true;
  $('ott-sel-label').textContent=r?r.numero:'–';
  $('ott-b-ver').disabled=!r;
  $('ott-b-edit').disabled=!r||cerrada;
  $('ott-b-remito').disabled=!r||cerrada||!(r.estado==='Pendiente'||r.estado==='Remito emitido'||r.estado==='En proceso'||r.estado==='Recibido');
  $('ott-b-dev').disabled=!r||cerrada||!((r.rechazado_pendiente_devolver||0)>0.0001);
  $('ott-b-comp').disabled=!r||cerrada||!(r.estado==='Recibido'&&r.lote_retorno_estado==='Aprobado');
}
function ottSelAccion(a){
  const r=_ottSel&&window._ottMap?window._ottMap.get(_ottSel):null;
  if(!r){toast('Seleccioná una OTT de la lista','w');return;}
  if(a==='ver') openOTTDetalle(r.id);
  else if(a==='edit') abrirPrecioOTT(r.id);
  else if(a==='remito') abrirEnvioOTT(r.id);
  else if(a==='dev') abrirDevolucionOTT(r.id);
  else if(a==='comp') completarOTT(r.id);
}
async function loadOTT(){
  _renderOttOcultarBtn();
  const est=$('ott-est-fil')?$('ott-est-fil').value:'';
  let rows=await api('/api/ott'+(est?'?estado='+est:''));
  const el=$('ott-list'); if(!el) return;
  if(!rows||rows.error){
    _ottRows=[];window._ottMap=new Map();_ottSel=null;
    el.innerHTML='<div class="em">Error cargando OTTs.</div>';
    actualizarToolbarOTT();
    return;
  }
  if(_ottOcultarCerradas()){
    rows=rows.filter(function(r){
      const otCerrada=r.ot_estado==='Completada'||r.ot_estado==='Cancelada';
      const ottCompletada=r.estado==='Completado';
      return !(otCerrada||ottCompletada);
    });
  }
  const q=($('ott-buscar')?$('ott-buscar').value:'').trim().toLowerCase();
  if(q){
    rows=rows.filter(function(r){
      return [r.producto_codigo,r.ot_numero,r.op_nombre,r.proveedor_nombre]
        .some(function(v){return v&&String(v).toLowerCase().includes(q);});
    });
  }
  _ottRows=rows;_ottQ=q;
  renderOTT();
}
function renderOTT(){
  const el=$('ott-list'); if(!el) return;
  const rows=_ottRows, q=_ottQ;
  window._ottMap=new Map(rows.map(function(r){return [r.id,r];}));
  if(_ottSel && !window._ottMap.has(_ottSel)) _ottSel=null;
  if(!rows.length){
    el.innerHTML='<div class="em">'+(q?'Sin resultados para "'+q+'".':'Sin órdenes de terceros'+(_ottOcultarCerradas()?' activas (hay cerradas ocultas — tocá "Mostrar cerradas" para verlas)':'')+'.')+'</div>';
    actualizarToolbarOTT();
    return;
  }
  const estCol={Pendiente:'ba','Remito emitido':'bb','En proceso':'bb',Recibido:'bg',Completado:'bg',Cancelado:'bk'};
  let h='<table><tr><th style="width:24px"></th><th>N°</th><th>OT origen</th><th>Operación</th><th>Producto</th><th>Material (insumo/retorno)</th><th>Proveedor</th><th>Precio</th><th>Nivel</th><th>Estado</th><th>A enviar</th><th>SC</th></tr>';
  rows.forEach(function(r){
    const aEnviar=(r.estado==='Cancelado'||r.estado==='Completado')?0:Math.max((r.cantidad_total||0)-(r.cantidad_enviada||0),0);
    const sel=_ottSel===r.id;
    h+='<tr class="'+(sel?'ot-sel':'')+'" style="cursor:pointer" onclick="selOTT('+r.id+')">'
      +'<td><input type="radio" name="ott-sel" '+(sel?'checked':'')+' onclick="event.stopPropagation();selOTT('+r.id+')"></td>'
      +'<td><b>'+r.numero+'</b></td>'
      +'<td>'+(r.ot_numero||'—')+'</td>'
      +'<td>'+(r.op_orden!=null?'<b>'+r.op_orden+'</b>. ':'')+(r.op_nombre||'—')+'</td>'
      +'<td style="font-size:11px">'+(r.producto_codigo||'—')+'</td>'
      +'<td style="font-size:11px">'+(r.material_codigo?('<b>'+r.material_codigo+'</b> '+(r.material_descripcion||'')):'—')+'</td>'
      +'<td>'+(r.proveedor_nombre||'<span style="color:#D85A30">Sin proveedor</span>')+'</td>'
      +'<td>'+fmtM(r.precio_acordado||0,r.moneda)+'</td>'
      +'<td>'+(!r.operacion_id&&!r.proceso_op_id?'<span class="b bk" style="font-size:10px">Manual</span>':(r.es_ultimo_nivel?'<span class="b bg" style="font-size:10px">PT</span>':'<span class="b ba" style="font-size:10px">Semi</span>'))+'</td>'
      +'<td><span class="b '+(estCol[r.estado]||'bk')+'">'+r.estado+'</span></td>'
      +'<td>'+(aEnviar>0?'<b>'+fN(aEnviar)+'</b>'+((r.cantidad_enviada||0)>0?' <span style="font-size:10px;color:var(--color-text-secondary)">de '+fN(r.cantidad_total)+'</span>':''):'<span style="color:var(--color-text-secondary)">—</span>')+'</td>'
      +'<td style="font-size:11px">'+(r.sc_numeros||'—')+(r.sc_numeros?'<br>'+(r.oc_numeros?'<span style="color:#1D9E75">'+r.oc_numeros+'</span>':'<span style="color:#D85A30">Sin OC</span>'):'')+'</td>'
      +'</tr>';
  });
  el.innerHTML=h+'</table>';
  actualizarToolbarOTT();
}

async function abrirNuevaOTT(){
  if(!_prov.length)_prov=await api('/api/proveedores');
  const mats=await api('/api/materiales');
  const ok=(mats||[]).filter(function(m){return m.categoria!=='Producto terminado'&&m.activo!==0;});
  $('ottn-mat').innerHTML='<option value="">— Seleccionar material —</option>'+ok.map(function(m){return '<option value="'+m.id+'">'+m.codigo+' — '+m.descripcion+' ('+(m.categoria||'')+')</option>';}).join('');
  $('ottn-prov').innerHTML='<option value="">— Seleccionar proveedor —</option>'+_prov.map(function(p){return '<option value="'+p.id+'">'+p.razon+'</option>';}).join('');
  $('ottn-qty').value='';$('ottn-precio').value='';$('ottn-ret').value='';$('ottn-obs').value='';
  if($('ottn-precio-wrap')) $('ottn-precio-wrap').style.display=VER_MONETARIO?'':'none';
  openMo('mo-ott-nueva');
}
async function guardarNuevaOTT(){
  const body={
    material_id:$('ottn-mat').value?parseInt($('ottn-mat').value):null,
    cantidad:parseFloat($('ottn-qty').value)||0,
    proveedor_id:$('ottn-prov').value?parseInt($('ottn-prov').value):null,
    precio_acordado:VER_MONETARIO?(parseFloat($('ottn-precio').value)||0):0,
    fecha_retorno_est:$('ottn-ret').value||null,
    obs:$('ottn-obs').value
  };
  if(!body.material_id){toast('Seleccioná el material como insumo','w');return;}
  if(!body.proveedor_id){toast('Seleccioná el proveedor','w');return;}
  if(body.cantidad<=0){toast('Indicá la cantidad a enviar','w');return;}
  const res=await api('/api/ott',{method:'POST',body:JSON.stringify(body)});
  if(res.ok){toast('OTT '+res.numero+' creada');closeMo('mo-ott-nueva');loadOTT();}
  else toast(res.error||'Error','e');
}

async function openOTTDetalle(ottId){
  const r=await api('/api/ott/'+ottId);
  $('ott-modal-titulo').textContent=r.numero;
  $('ott-modal-id').value=ottId;
  let h='<div class="fg2" style="font-size:12px">';
  h+='<div class="fg"><b>OT origen:</b> '+(r.ot_numero||'—')+'</div>';
  h+='<div class="fg"><b>Producto:</b> '+(r.producto_codigo||'—')+' — '+(r.producto_nombre||'—')+'</div>';
  h+='<div class="fg"><b>Operación:</b> '+(r.op_orden||'')+(r.op_nombre?' — '+r.op_nombre:'—')+'</div>';
  h+='<div class="fg"><b>Proveedor:</b> '+(r.proveedor_nombre||'Sin asignar')+'</div>';
  if(r.material_codigo) h+='<div class="fg"><b>Material (insumo / retorno):</b> '+r.material_codigo+' — '+(r.material_descripcion||'')+'</div>';
  if(!r.operacion_id&&!r.proceso_op_id) h+='<div class="fg"><b>Tipo:</b> OTT manual — cantidad indicada: '+fN(r.cantidad_plan||0)+'</div>';
  h+=monOnly('<div class="fg"><b>Precio acordado:</b> '+fmtM(r.precio_acordado||0,r.moneda)+'</div>');
  h+='<div class="fg"><b>Nivel:</b> '+(r.es_ultimo_nivel?'Último nivel (PT → cliente)':'Paso intermedio (semielaborado → OT)')+'</div>';
  h+='<div class="fg"><b>Estado:</b> '+r.estado+'</div>';
  if(r.remito_numero) h+='<div class="fg"><b>Remito traslado:</b> '+r.remito_numero+'</div>';
  if(r.fecha_envio) h+='<div class="fg"><b>Fecha envío:</b> '+fmtD(r.fecha_envio)+'</div>';
  if(r.fecha_retorno_est) h+='<div class="fg"><b>Retorno estimado:</b> '+fmtD(r.fecha_retorno_est)+'</div>';
  if(r.fecha_retorno_real) h+='<div class="fg"><b>Retorno real:</b> '+fmtD(r.fecha_retorno_real)+'</div>';
  if(r.remito_devolucion_numero) h+='<div class="fg"><b>Remito devolución:</b> '+r.remito_devolucion_numero+'</div>';
  h+='</div>';
  if(r.obs) h+='<div style="font-size:11px;color:var(--color-text-secondary);margin-top:8px">Obs: '+r.obs+'</div>';
  const pendDev=r.rechazado_pendiente_devolver||0;
  if(pendDev>0.0001) h+='<div style="font-size:12px;margin-top:8px;color:#D85A30"><b>Rechazado pendiente de devolver al proveedor:</b> '+pendDev+'</div>';
  $('ott-modal-body').innerHTML=h;
  $('ott-modal-actions').innerHTML='<button class="btn" onclick="closeMo(&quot;mo-ott&quot;)">Cerrar</button>'
    +(pendDev>0.0001?'<button class="btn btn-s" style="background:#D85A30;color:#fff" onclick="closeMo(&quot;mo-ott&quot;);abrirDevolucionOTT('+ottId+')">Devolver piezas</button>':'');
  openMo('mo-ott');
}

async function abrirEnvioOTT(ottId){
  $('ott-env-id').value=ottId;
  $('ott-env-qty').value='';
  $('ott-env-obs').value='';
  $('ott-env-disp').textContent='Cargando cantidad disponible...';
  $('ott-env-qty').removeAttribute('max');
  openMo('mo-ott-envio');
  const r=await api('/api/ott/'+ottId);
  if(r&&r.envio_bloqueado){
    closeMo('mo-ott-envio');
    toast(r.envio_bloqueado,'w');
    return;
  }
  if(r&&!r.error){
    const disp=r.cantidad_disponible||0;
    const origenTxt={stock:' (stock actual)',produccion_previa:' (producido en la operación anterior)',qty_requerida:' (cantidad planificada de la operación)',insumo:' (limitado por stock de insumo requerido)'};
    $('ott-env-disp').textContent='Disponible para remitir: '+disp+(origenTxt[r.cantidad_disponible_origen]||'');
    $('ott-env-qty').max=disp;
    $('ott-env-qty').placeholder=disp;
  } else {
    $('ott-env-disp').textContent='';
  }
  setTimeout(function(){$('ott-env-qty').focus();},80);
}

async function confirmarEnvioOTT(){
  const ottId=$('ott-env-id').value;
  const qty=parseFloat($('ott-env-qty').value);
  if(!qty||qty<=0){toast('Ingresá la cantidad de piezas enviadas','w');return;}
  const max=parseFloat($('ott-env-qty').getAttribute('max'));
  if(!isNaN(max)&&qty>max){toast('La cantidad supera lo disponible para remitir ('+max+')','w');return;}
  const res=await api('/api/ott/'+ottId+'/emitir_remito',{method:'POST',body:JSON.stringify({
    cantidad:qty, obs:$('ott-env-obs').value
  })});
  if(res.ok){
    toast('Remito '+res.remito_numero+' emitido — piezas en tránsito'+(res.stock_descontado?' (stock descontado)':''));
    if(res.solicitud_compra_ott){
      toast('Se generó la solicitud de compra '+res.solicitud_compra_ott.numero+' por '+res.solicitud_compra_ott.cantidad
            +(VER_MONETARIO?' — Compras debe confirmar el precio y emitir la OC':' — Compras debe continuar el trámite'),'w');
    }
    if(typeof abrirEtiquetas==='function'){
      abrirEtiquetas({origen:'OTT',referencia:res.remito_numero,cantidad:qty});
    }
    (res.solicitudes_compra_insumo||[]).forEach(function(s){
      toast((s.actualizada?'SC ampliada':'SC '+s.numero+' generada')+' por faltante de '+s.material+' ('+fN(s.cantidad)+')','w');
    });
    (res.ots_auxiliares_insumo||[]).forEach(function(o){
      toast((o.actualizada?'OT '+o.numero+' ampliada':'OT auxiliar '+o.numero+' generada')+' por faltante de '+o.producto+' ('+fN(o.cantidad)+')','w');
    });
    closeMo('mo-ott-envio');
    loadOTT();
  } else toast(res.error||'Error','e');
}

function abrirRetornoOTT(ottId, esUltimo){
  $('ott-ret-id').value=ottId;
  $('ott-ret-qty').value='';
  $('ott-ret-remito').value='';
  $('ott-ret-obs').value='';
  $('ott-ret-info').innerHTML=esUltimo
    ?'<b>Último nivel:</b> el lote quedará disponible para Remitir a cliente. El "Total realizado" de la OT se va actualizando con cada recepción, y al recibir todo la OT se marca Completada automáticamente.'
    :'<b>Paso intermedio:</b> el lote quedará como semielaborado asignable a una OT.';
  openMo('mo-ott-retorno');
  setTimeout(function(){$('ott-ret-qty').focus();},80);
}

async function confirmarRetornoOTT(){
  const ottId=$('ott-ret-id').value;
  const qty=parseFloat($('ott-ret-qty').value);
  if(!qty||qty<=0){toast('Ingresá la cantidad recibida','w');return;}
  const res=await api('/api/ott/'+ottId+'/registrar_retorno',{method:'POST',body:JSON.stringify({
    cantidad:qty, obs:$('ott-ret-obs').value, remito:($('ott-ret-remito').value||'').trim()
  })});
  if(res.ok){
    toast(res.mensaje+(res.lote_numero?' — Lote '+res.lote_numero:''));
    closeMo('mo-ott-retorno');
    loadOTT();
    if(typeof loadRecOTTPend==='function') loadRecOTTPend();
    if(typeof loadRecepciones==='function') loadRecepciones();
    if(typeof abrirEtiquetas==='function'){
      abrirEtiquetas({origen:'Recepción OTT',referencia:(res.lote_numero||'OTT '+ottId),cantidad:qty,lote:res.lote_numero||''});
    }
  } else toast(res.error||'Error','e');
}

async function abrirDevolucionOTT(ottId){
  const r=await api('/api/ott/'+ottId);
  if(!r||r.error){toast(r&&r.error||'Error','e');return;}
  const cant=r.rechazado_pendiente_devolver||0;
  if(cant<=0.0001){toast('No hay piezas rechazadas pendientes de devolver','w');return;}
  if(!await confirmar('Se van a devolver '+fN(cant)+' pieza(s) rechazada(s) al proveedor '+(r.proveedor_nombre||'')+'.\n\nSe generará un remito de devolución y esa cantidad vuelve a quedar pendiente de recibir (reemplazo) en el mismo lote.\n\n¿Confirmar devolución?')) return;
  const res=await api('/api/ott/'+ottId+'/devolver_rechazo',{method:'POST',body:JSON.stringify({})});
  if(res.ok){
    toast('Remito '+res.remito_numero+' emitido — '+fN(res.cantidad_devuelta)+' pieza(s) devuelta(s) al proveedor');
    loadOTT();
  } else toast(res.error||'Error','e');
}

async function completarOTT(ottId){
  if(!await confirmar('¿Confirmar que la OTT fue completada? Esta acción no se puede deshacer.'))return;
  const res=await api('/api/ott/'+ottId+'/completar',{method:'POST',body:JSON.stringify({})});
  if(res.ok){toast('OTT completada');loadOTT();}
  else toast(res.error||'Error','e');
}

async function abrirPrecioOTT(ottId){
  const r=await api('/api/ott/'+ottId);
  if(!r||r.error){toast('No se pudo cargar la OTT','e');return;}
  $('ott-precio-id').value=ottId;
  $('ott-precio-val').value=r.precio_acordado||'';
  if(!_prov.length)_prov=await api('/api/proveedores');
  await selLoad('ott-precio-prov',[{id:'',nombre:'— Sin proveedor —'},..._prov.map(function(p){return{id:p.id,nombre:p.razon};})],r.proveedor_id||null,'— Sin proveedor —');
  const iniciada=(r.cantidad_enviada||0)>0;
  $('ott-precio-prov').disabled=iniciada;
  $('ott-precio-prov').title=iniciada?'La OTT ya inició (tiene envíos): el proveedor no se puede cambiar':'';
  $('ott-precio-wrap').style.display=VER_MONETARIO?'':'none';
  openMo('mo-ott-precio');
  setTimeout(function(){$('ott-precio-val').focus();$('ott-precio-val').select();},80);
}

async function confirmarPrecioOTT(){
  const ottId=$('ott-precio-id').value;
  let nuevoPrecio=parseFloat($('ott-precio-val').value);
  if(!VER_MONETARIO){ const _r0=await api('/api/ott/'+ottId); nuevoPrecio=_r0&&!_r0.error?(_r0.precio_acordado||0):0; }
  if(isNaN(nuevoPrecio)||nuevoPrecio<0){toast('Ingresá un precio válido','e');return;}
  const provSel=$('ott-precio-prov').value;
  const r=await api('/api/ott/'+ottId);
  if(!r||r.error){toast('No se pudo cargar la OTT','e');return;}
  const res=await api('/api/ott/'+ottId,{method:'PUT',body:JSON.stringify({
    estado:r.estado, proveedor_id:provSel?parseInt(provSel):null, precio_acordado:nuevoPrecio,
    fecha_retorno_est:r.fecha_retorno_est, fecha_envio:r.fecha_envio, obs:r.obs
  })});
  if(res.ok){toast('OTT actualizada');closeMo('mo-ott-precio');loadOTT();}
  else toast(res.error||'Error al actualizar','e');
}


// ── Buscador de productos insumo ──────────────────────────────────────────────
let _pbPrefix = 'op';
let _pbProdActualId = null;

async function abrirBuscadorProducto(prefix){
  _pbPrefix = prefix;
  // ID del producto "padre" cuyo proceso se está editando (op-pid o ope-pid).
  // Se excluye de los resultados para que un producto no pueda usarse como
  // insumo de sí mismo.
  const pidField = $(prefix+'-pid');
  _pbProdActualId = pidField && pidField.value ? parseInt(pidField.value) : null;
  $('pb-prefix').value = prefix;
  $('pb-query').value = '';
  $('pb-resultados').innerHTML = '<div class="ld">Cargando productos...</div>';
  openMo('mo-prod-buscar');
  setTimeout(function(){ $('pb-query').focus(); }, 80);
  // Load all products once
  if(!_prod.length) _prod = await api('/api/productos');
  filtrarProductosBuscador();
}

function filtrarProductosBuscador(){
  const q = ($('pb-query').value||'').toLowerCase().trim();
  const base = _pbProdActualId
    ? _prod.filter(function(p){ return p.id !== _pbProdActualId; })
    : _prod;
  const lista = q
    ? base.filter(function(p){
        return p.codigo.toLowerCase().includes(q) || p.nombre.toLowerCase().includes(q);
      })
    : base.slice(0, 40);  // show first 40 when no query

  if(!lista.length){
    $('pb-resultados').innerHTML = '<div class="em" style="padding:12px">Sin resultados para "'+q+'".</div>';
    return;
  }
  const el = $('pb-resultados');
  el.innerHTML = '';
  lista.forEach(function(p){
    const row = document.createElement('div');
    row.style.cssText = 'display:flex;align-items:center;justify-content:space-between;padding:8px 12px;border-bottom:1px solid var(--color-border-tertiary);cursor:pointer';
    row.onmouseenter = function(){ this.style.background='var(--color-background-secondary)'; };
    row.onmouseleave = function(){ this.style.background=''; };
    const info = document.createElement('div');
    info.innerHTML = '<span style="font-weight:600;font-size:12px">'+p.codigo+'</span>'
      +' <span style="font-size:12px;color:var(--color-text-secondary)">'+p.nombre+'</span>'
      +(p.cliente_nombre?'<br><span style="font-size:10px;color:var(--color-text-secondary)">'+p.cliente_nombre+'</span>':'');
    const addBtn = document.createElement('button');
    addBtn.className = 'btn btn-s btn-p';
    addBtn.style.cssText = 'font-size:11px;padding:3px 8px;flex-shrink:0';
    addBtn.textContent = '+ Agregar';
    addBtn.onclick = (function(prod){ return function(e){
      e.stopPropagation();
      agregarProductoInsumo(_pbPrefix, prod);
      closeMo('mo-prod-buscar');
    }; })(p);
    row.appendChild(info);
    row.appendChild(addBtn);
    el.appendChild(row);
  });
  if(base.length > 40 && !q){
    const hint = document.createElement('div');
    hint.style.cssText = 'padding:8px 12px;font-size:11px;color:var(--color-text-secondary)';
    hint.textContent = 'Mostrando 40 de '+base.length+'. Escribí para filtrar.';
    el.appendChild(hint);
  }
}

function agregarProductoInsumo(prefix, prod, cantidadInicial){
  const containerId = prefix+'-prods-insumo';
  const el = document.getElementById(containerId);
  if(!el) return;

  // Check if already added
  if(el.querySelector('[data-prod-id="'+prod.id+'"]')){
    toast('Ese producto ya está en la lista','w');
    return;
  }

  const row = document.createElement('div');
  row.className = 'mr';
  row.setAttribute('data-tipo','producto');
  row.setAttribute('data-prod-id', prod.id);
  row.style.cssText = 'display:flex;align-items:center;gap:6px;margin-bottom:4px;background:var(--color-background-secondary);padding:5px 8px;border-radius:6px;border:1px solid var(--color-border-tertiary)';

  const nameSpan = document.createElement('span');
  nameSpan.style.cssText = 'flex:1;font-size:12px;font-weight:600';
  nameSpan.textContent = prod.codigo + ' — ' + prod.nombre;

  const qtyInput = document.createElement('input');
  qtyInput.type = 'number'; qtyInput.min = '0.01'; qtyInput.step = '0.01';
  qtyInput.value = (cantidadInicial!=null && cantidadInicial!=='') ? cantidadInicial : '1';
  qtyInput.placeholder = 'Cant.';
  qtyInput.style.cssText = 'width:65px;font-size:12px;padding:3px 6px;border:1px solid var(--color-border-tertiary);border-radius:5px;background:var(--color-background-primary);color:var(--color-text-primary)';

  const uniInput = document.createElement('input');
  uniInput.placeholder = 'unid';
  uniInput.value = prod.unidad || 'unid';
  uniInput.readOnly = true;
  uniInput.title = 'La unidad viene definida por el producto y no se puede modificar';
  uniInput.style.cssText = 'width:50px;font-size:12px;padding:3px 6px;border:1px solid var(--color-border-tertiary);border-radius:5px;background:var(--color-background-secondary);color:var(--color-text-secondary);cursor:not-allowed';

  const delBtn = document.createElement('button');
  delBtn.className = 'btn btn-s btn-d';
  delBtn.textContent = '×';
  delBtn.onclick = function(){ row.remove(); };

  row.appendChild(nameSpan);
  row.appendChild(qtyInput);
  row.appendChild(uniInput);
  row.appendChild(delBtn);
  el.appendChild(row);
}

function leerProductosInsumo(prefix){
  const containerId = prefix+'-prods-insumo';
  const el = document.getElementById(containerId);
  if(!el) return [];
  return Array.from(el.querySelectorAll('.mr[data-tipo="producto"]')).map(function(row){
    const inputs = row.querySelectorAll('input');
    return {
      tipo: 'producto',
      producto_id: parseInt(row.getAttribute('data-prod-id')),
      cantidad: parseFloat(inputs[0].value)||1,
      unidad: inputs[1].value||'unid',
    };
  }).filter(function(x){ return x.producto_id && x.cantidad; });
}

async function selLoad(selId,data,selVal,empty='— Sin —'){const s=$(selId);s.innerHTML=`<option value="">${empty}</option>`;data.forEach(r=>{const o=document.createElement('option');o.value=r.id;o.textContent=r.nombre||r.razon||r.codigo;if(r.id==selVal)o.selected=true;s.appendChild(o);});}

async function openOT(){
  $('ot-id').value='';
  if(!_cli.length)_cli=await api('/api/clientes');
  if(!_prod.length)_prod=await api('/api/productos');
  $('ot-prod').value='';$('ot-prod-search').value='';
  await selLoad('ot-cli',[{id:'',nombre:'— Sin cliente —'},..._cli],null);
  $('ot-cm').value='—'; $('ot-tst').value='—';
  $('ot-est').value='Pendiente';
  // Al crear una OT, el estado siempre arranca en "Pendiente" — no se
  // permite elegirlo, así que el campo se oculta del formulario.
  $('ot-est-wrap').style.display='none';
  const _hoy=new Date().toISOString().slice(0,10);
  $('ot-ini').value=_hoy; $('ot-ent').value=_hoy;
  openMo('mo-ot');
}

async function onOTProdChange(){
  await calcOTCostos();
}

async function calcOTCostos(){
  const pid=$('ot-prod').value;
  const qty=parseFloat($('ot-cant').value)||1;
  if(!pid){$('ot-cm').value='';$('ot-tst').value='';return;}
  // Ensure inventory cache is loaded
  if(_mat_cache.size===0){
    const allMats=await api('/api/materiales');
    _mat_cache=new Map(allMats.map(function(r){return[r.id,r];}));
  }
  const prod=await api('/api/productos/'+pid);
  if(!prod) return;
  // Costo: precio_unit (inventario) x cantidad_proceso x cantidad_OT
  let costoMat=0;
  if(prod.operaciones&&prod.operaciones.length){
    sortOpsNumeric(prod.operaciones).forEach(function(op){
      if(op.materiales&&op.materiales.length){
        op.materiales.forEach(function(m){
          const matData=_mat_cache.get(parseInt(m.material_id));
          const precio=matData?matData.precio_unit:0;
          costoMat+=precio * m.cantidad * qty;
        });
      }
    });
  }
  if(costoMat===0&&prod.costo_mat) costoMat=prod.costo_mat*qty;
  // Tiempo std en MINUTOS: setup por op (ya en minutos) + ciclo x cantidad
  // (el ciclo se carga en segundos, por eso se divide por 60).
  let tiempoStd=0;
  if(prod.operaciones&&prod.operaciones.length){
    sortOpsNumeric(prod.operaciones).forEach(function(op){
      tiempoStd+=(op.tiempo_setup_min||0)+((op.tiempo_ciclo_seg||0)/60*qty);
    });
  } else {
    tiempoStd=Math.round((prod.tiempo_total_hs||0)*60*qty);
  }
  // Store raw number for saveOT to use
  $('ot-cm').dataset.raw=costoMat;
  $('ot-cm').value=fmtM(costoMat);
  $('ot-tst').value=Math.round(tiempoStd);
}

async function editOT(r){
  $('ot-id').value=r.id;$('ot-cant').value=r.cantidad;
  $('ot-est').value=r.estado;
  // Al editar una OT existente sí se puede ver/cambiar el estado.
  $('ot-est-wrap').style.display='';
  $('ot-ini').value=r.fecha_inicio||'';$('ot-ent').value=r.fecha_entrega||'';
  $('ot-obs').value=r.obs||'';
  $('ot-cm').value=fmtM(r.costo_mat||0,r.moneda);
  $('ot-tst').value=r.costo_mo||0;
  if(!_cli.length)_cli=await api('/api/clientes');
  if(!_prod.length)_prod=await api('/api/productos');
  $('ot-prod').value=r.producto_id||'';
  const _otp=_prod.find(function(p){return p.id==r.producto_id;});
  $('ot-prod-search').value=_otp?(_otp.codigo+' — '+_otp.nombre):'';
  await selLoad('ot-cli',[{id:'',nombre:'— Sin cliente —'},..._cli],r.cliente_id);
  // Si la OT ya está vinculada a un ítem de una OC de cliente, la fecha de
  // entrega quedó comprometida con el cliente al vincularla: no se debe
  // poder modificar desde acá.
  const entInput=$('ot-ent');
  if(r.oc_id){
    entInput.disabled=true;
    entInput.title='Esta OT está vinculada a la OC '+(r.oc_numero||r.oc_id)+': la fecha de entrega no se puede modificar.';
    $('ot-ent-label').innerHTML='Fecha entrega <span style="font-size:10px;color:var(--color-text-secondary)">(vinculada a OC '+(r.oc_numero||r.oc_id)+', no editable)</span>';
  }else{
    entInput.disabled=false;
    entInput.title='';
    $('ot-ent-label').textContent='Fecha entrega';
  }
  openMo('mo-ot');
}

async function saveOT(){
  const id=$('ot-id').value;
  const pid=$('ot-prod').value;
  if(!pid){toast('Seleccioná un producto','w');return;}
  // Parse costo_mat from display string or raw number
  const cmRaw=$('ot-cm').value.replace(/[$.\s]/g,'').replace(/\./g,'').replace(',','.');
  const costo_mat=parseFloat(cmRaw)||0;
  const tst=parseFloat($('ot-tst').value)||0;
  const prod=_prod.find(function(p){return p.id==pid||p.id==parseInt(pid);});
  const desc=prod?(prod.codigo+' — '+prod.nombre):'OT';
  const body={
    descripcion:desc,
    cliente_id:$('ot-cli').value||null,
    producto_id:parseInt(pid),
    cantidad:parseFloat($('ot-cant').value)||1,
    fecha_inicio:$('ot-ini').value,
    fecha_entrega:$('ot-ent').value,
    costo_mat:costo_mat,
    costo_mo:tst,
    precio_venta:0,
    obs:$('ot-obs').value
  };
  // El estado solo se manda al editar una OT existente — al crear, el
  // backend siempre la genera en "Pendiente" y el campo ni se muestra.
  if(id) body.estado=$('ot-est').value;
  const res=await api(id?'/api/ordenes/'+id:'/api/ordenes',{method:id?'PUT':'POST',body:JSON.stringify(body)});
  if(res.ok){
    toast(id?'OT actualizada':'OT '+res.numero+' creada');
    closeMo('mo-ot');$('ot-id').value='';
    // Auto-populate operaciones and materiales for new OT
    if(!id&&res.id){
      await api('/api/ordenes/'+res.id+'/operaciones/populate',{method:'POST',body:JSON.stringify({})});
      const popMat=await api('/api/ordenes/'+res.id+'/materiales/populate',{method:'POST',body:JSON.stringify({})});
      // Si algún insumo es un Producto Terminado sin stock suficiente (no se
      // puede comprar en Compras), el backend ya generó la OT auxiliar de
      // fabricación por el faltante — avisamos para que no pase inadvertido.
      const otsAux=(popMat&&popMat.ots_auxiliares)||[];
      const otsNuevas=otsAux.filter(function(o){return !o.actualizada;});
      if(otsNuevas.length){
        toast('Insumo(s) sin stock suficiente: se generó OT auxiliar de fabricación — '
          +otsNuevas.map(function(o){return o.numero+' ('+o.producto+' x'+fN(o.cantidad)+')';}).join(', '), 'w');
      }
    }
    _prod=[];loadOT();
  }
  else toast(res.error||'Error','e');
}


// ── Procesos / Productos ───────────────────────────────────────────────────────
// loadProd() pide los datos al servidor; renderProd() solo redibuja desde lo ya
// cargado. Seleccionar una fila o escribir en el buscador usan renderProd(),
// así la respuesta es inmediata y no se repite la consulta de /api/productos.
async function loadProd(){
  if(!_cli.length)_cli=await api('/api/clientes');
  const cid=$('prod-cli-fil')?$('prod-cli-fil').value:'';
  const rowsAll=await api('/api/productos'+(cid?'?cliente_id='+cid:''));_prod=rowsAll;
  window._prodAll=rowsAll;
  renderProd();
}
function renderProd(){
  const rowsAll=window._prodAll||[];
  const q=($('prod-search')?$('prod-search').value:'').trim().toLowerCase();
  const rows=q?rowsAll.filter(function(r){
    return (r.codigo||'').toLowerCase().includes(q)||(r.nombre||'').toLowerCase().includes(q);
  }):rowsAll;
  if(!rowsAll.length){$('prod-list').innerHTML='<div class="em">No hay productos terminados. Usá «Nuevo producto» para crear el primero.</div>';return;}
  if(!rows.length){$('prod-list').innerHTML='<div class="em">No se encontraron productos para "'+q+'".</div>';return;}
  let h='<table><tr><th style="width:24px"></th><th>Código</th><th>Nombre</th><th>Cliente</th><th>Categoría</th><th>Precio venta</th><th>Costo total</th><th>Costo MO</th><th>Costo mat.</th><th>Costo terc.</th><th>Ciclo total</th><th>Peso (kg)</th><th>Rend. ponderado</th><th>Estado</th></tr>';
  window._prodRows=new Map(rows.map(function(r){return [r.id,r];}));
  if(_prodSel && !window._prodRows.has(_prodSel)) _prodSel=null;
  rows.forEach(r=>{
    const rend=r.rendimiento_ponderado;
    let rendCls='bk';
    if(rend!=null){
      if(rend<80) rendCls='br';
      else if(rend<100) rendCls='ba';
      else rendCls='bg';
    }
    h+=`<tr class="${_prodSel===r.id?'ot-sel':''}" style="cursor:pointer" onclick="selProd(${r.id})">
    <td><input type="radio" name="prod-sel" ${_prodSel===r.id?'checked':''} onclick="event.stopPropagation();selProd(${r.id})"></td>
    <td><b>${r.codigo}</b></td>
    <td>${r.nombre}</td>
    <td style="font-size:11px">${r.cliente_nombre||'—'}</td>
    <td><span class="b bt">${r.categoria_nombre||'—'}</span></td>
    <td><b>${fmtM(r.precio_venta)}</b></td>
    <td><b>${fmtM(r.costo_total)}</b></td>
    <td>${fmtM(r.costo_mo)}</td>
    <td>${fmtM(r.costo_mat)}</td>
    <td>${(r.costo_terc||0)>0?fmtM(r.costo_terc):'—'}</td>
    <td>${r.tiempo_ciclo_total_min!=null?r.tiempo_ciclo_total_min+'<span style="font-size:10px;color:var(--color-text-secondary)"> min</span>':"—"}</td>
    <td>${(r.peso_kg||0)>0?(r.peso_kg+' kg'):"—"}</td>
    <td><span class="b ${rendCls}">${rend!=null?rend+'%':'—'}</span></td>
    <td>${r.activo?'<span class="b bg">Activo</span>':'<span class="b bk">Inactivo</span>'}</td>
    </tr>`;
  });
  $('prod-list').innerHTML=h+'</table>';
  actualizarToolbarProd();
}

// ── Selección de artículo + barra de herramientas (fix v147) ────────────────
let _prodSel=null;
function selProd(id){ _prodSel=id; renderProd(); }
function actualizarToolbarProd(){
  const r=_prodSel&&window._prodRows?window._prodRows.get(_prodSel):null;
  $('prod-sel-label').textContent=r?r.codigo:'–';
  $('prod-b-ver').disabled=!r;
  $('prod-b-edit').disabled=!r;
  $('prod-b-copy').disabled=!r||ROL==='operario';
}
function prodSelAccion(a){
  const r=_prodSel&&window._prodRows?window._prodRows.get(_prodSel):null;
  if(!r){toast('Seleccioná un artículo de la lista','w');return;}
  if(a==='ver') verProc(r.id);
  else if(a==='edit') editProd(r);
  else if(a==='copy') openCopyProd(r.id);
}

function clearProcDetail(){
  closeMo('mo-proc-view');
  document.getElementById('proc-detail').innerHTML='';
  const vc=document.getElementById('prod-versiones-card');
  if(vc) vc.style.display='none';
}

async function verProc(pid,nom){
  curProdId=pid;
  // Look up name from already-loaded cache to avoid HTML escaping issues
  if(!nom){
    const cached=_prod.find(function(p){return p.id===pid||p.id===parseInt(pid);});
    nom=cached?cached.nombre:'Producto '+pid;
  }
  curProdNom=nom;
  const prod=await api('/api/productos/'+pid);
  const canEdit=['admin','operario'].includes(ROL);
  // Product info bar
  const pesoStr  = (prod.peso_kg&&prod.peso_kg>0)?(prod.peso_kg+' kg'):'—';
  const cicloStr = prod.tiempo_ciclo_total_min!=null?(prod.tiempo_ciclo_total_min+' min'):'—';

  let html='<div class="card" style="border-left:3px solid #378ADD">';
  html+='<div class="ch"><span class="ct">Proceso: '+nom+'</span><span style="font-size:11px;font-weight:400;color:var(--color-text-secondary);display:flex;gap:16px">'
    +(cicloStr!=='—'?'<span>⏱ '+cicloStr+' ciclo</span>':'')
    +(pesoStr!=='—'?'<span>⚖ '+pesoStr+'</span>':'')
    +'</span>';
  html+='<div style="display:flex;gap:6px">';
  if(canEdit) html+='<button class="btn btn-s btn-p" onclick="openOp('+pid+')">+ Operar</button>';
  html+='<button class="btn btn-s" onclick="clearProcDetail()">Cerrar</button>';
  html+='</div></div>';
  if(!prod||!prod.operaciones||!prod.operaciones.length){
    html+='<div class="em">Sin operaciones definidas. Usá el botón "+ Operar" para agregar la primera.</div>';
  } else {
    sortOpsNumeric(prod.operaciones).forEach(function(op){
      const matsArr=op.materiales&&op.materiales.length
        ?op.materiales.map(function(m){return '<span class="tag tag-g">'+m.descripcion+': '+(m.vida_util_herramienta>0?'1 c/ '+m.vida_util_herramienta+' pz (vida útil)':m.cantidad+' '+m.unidad)+'</span>';})
        :[];
      const prodsInsumoArr=op.productos_insumo&&op.productos_insumo.length
        ?op.productos_insumo.map(function(pi){return '<span class="tag tag-g" title="Producto usado como insumo"> '+pi.descripcion+': '+fN(pi.cantidad)+' '+pi.unidad+'</span>';})
        :[];
      html+='<div class="opc"><div class="oph"><div>';
      const tercBadge=op.es_tercerizada?'<span class="b br" style="font-size:10px;margin-left:6px">TERCERIZADO</span>':'';
      const volBadge=op.volumen_agrupado?'<span class="b" style="font-size:10px;margin-left:6px">VOL. AGRUPADO ×'+op.valor_recalculado+'</span>':'';
      html+='<div class="opn">'+op.orden+'. '+op.nombre+tercBadge+volBadge+'</div>';
      if(op.es_tercerizada){
        html+='<div class="opm">Proveedor: '+(op.proveedor_nombre||'—')+' · Precio: '+fmtM(op.precio_tercerizado||0)+' · Plazo mínimo: '+(op.tiempo_minimo_dias||'—')+' días</div>';
      } else {
        html+='<div class="opm">'+(op.cat_maq_nombre||'Cualquier máquina')+(op.maquina_nombre?' · '+op.maquina_nombre:'')+'</div>';
      }
      html+='</div><div style="text-align:right;font-size:11px;color:var(--color-text-secondary)">';
      html+='Setup: '+op.tiempo_setup_min+' min &nbsp; Ciclo: '+(op.tiempo_ciclo_seg||0)+' seg';
      if(canEdit){
        html+='<br><span style="display:flex;gap:4px;justify-content:flex-end;margin-top:4px">';
        html+='<button class="btn btn-s" onclick="openOpEditById('+op.id+','+pid+')">Editar</button>';
        html+='<button class="btn btn-s" data-herr="'+op.id+'" data-herr-nom="'+encodeURIComponent(op.nombre)+'" onclick="openHerramientasById(this)">🔧 Herramientas</button>';
        html+='<button class="btn btn-s btn-d" onclick="delOp('+op.id+')">Eliminar</button>';
        html+='</span>';
      }
      html+='</div></div>';
      if(op.descripcion) html+='<div style="font-size:12px;color:var(--color-text-secondary);margin-bottom:5px">'+op.descripcion+'</div>';
      if(matsArr.length) html+='<div style="margin-top:4px">'+matsArr.join('')+'</div>';
      if(prodsInsumoArr.length) html+='<div style="margin-top:4px">'+prodsInsumoArr.join('')+'</div>';
      html+='</div>';
    });
  }
  html+='</div>';

  // ── Info chips (in header, not separate card) ──────────────────────────────
  // (shown inline in the card subtitle below the process header)

  // ── Archivos del producto ──────────────────────────────────────────────────
  html+='<div class="card" style="margin-top:8px" id="prod-files-card-'+pid+'">';
  html+='<div class="ch"><span class="ct">Archivos y documentación</span>';
  if(canEdit) html+='<label class="btn btn-s btn-p" style="cursor:pointer">+ Subir archivo<input type="file" multiple style="display:none" onchange="uploadArchivosProd('+pid+',this)"></label> <button class="btn btn-s" onclick="nuevaCarpetaProd('+pid+')">+ Carpeta</button>';
  html+='</div>';
  html+='<div id="prod-files-list-'+pid+'" style="min-height:32px"><div class="ld">Cargando archivos...</div></div>';
  html+='</div>';

  // ── Versiones anteriores del producto ────────────────────────────────────
  html+='<div class="card" style="margin-top:8px">';
  html+='<div class="ch"><span class="ct">Versiones anteriores</span></div>';
  html+='<div id="versiones-list"><div class="ld">Cargando...</div></div>';
  html+='</div>';

  document.getElementById('proc-detail').innerHTML=html;
  loadArchivosProd(pid);
  cargarVersiones(pid);
  $('proc-view-title').textContent='Proceso: '+nom;
  openMo('mo-proc-view');
}


async function openOp(pid){
  $('op-pid').value=pid;opN=0;$('op-mats').innerHTML='';
  $('op-ord').value='';$('op-nom').value='';$('op-desc').value='';
  $('op-set').value=0;$('op-cic').value=0;$('op-obs').value='';
  if($('op-terc')) $('op-terc').checked=false;
  if($('op-prec')) $('op-prec').value='';
  if($('op-tdays')) $('op-tdays').value=1;
  toggleTercOp('op');
  if(!_catM.length)_catM=await api('/api/categorias_maquina');
  if(!_maq.length)_maq=await api('/api/maquinas');
  if(!_prov.length)_prov=await api('/api/proveedores');
  // Always refresh materials to pick up newly created items
  _mat=await api('/api/materiales?categoria=Material');
  _mat_cache=new Map(_mat.map(function(r){return[r.id,r];}));
  await selLoad('op-catm',[{id:'',nombre:'— Cualquiera —'},..._catM],null,'— Cualquiera —');
  await selLoad('op-maq',[{id:'',nombre:'— Cualquiera del tipo —'},..._maq.map(m=>({...m,nombre:m.codigo+' — '+m.nombre}))],null,'— Cualquiera del tipo —');
  setProvOp('op',null);
  openMo('mo-op');
}

async function saveOp(){
  const pid=$('op-pid').value;
  const mats=[...$('op-mats').querySelectorAll('.mr')].map(function(row){
    const hidId=row.querySelector('.mat-id-field');
    const numInputs=row.querySelectorAll('input[type="number"],input:not([type])');
    const mid=hidId?hidId.value:null;
    const vida=row.querySelector('.mat-vida-field');
    const qty=herrCantidad(vida,numInputs[0]);
    const uni=numInputs[1]?numInputs[1].value:'unid';
    return{tipo:'material',material_id:mid,cantidad:qty,unidad:uni,vida_util_herramienta:vida&&vida.value?parseInt(vida.value):null};
  }).filter(function(m){return m.material_id&&m.cantidad;}).concat(leerProductosInsumo('op'));
  // "Terciarizado" solo se guarda como tal si, además de tildar el check,
  // se cargó alguna información en sus campos (proveedor o precio). Si se
  // tilda el check pero no se completa nada, no queda como tercerizada.
  const tercChecked=!!($('op-terc') && $('op-terc').checked);
  const provId=$('op-prv')?($('op-prv').value||null):null;
  const precio=parseFloat($('op-prec')?$('op-prec').value:0)||0;
  // Sin permiso monetario el precio no se ve ni se manda: no alcanza para
  // decidir. El servidor resuelve con el precio que ya tiene guardado.
  const esTerc=tercChecked && (!!provId || precio>0 || !VER_MONETARIO);
  const body={producto_id:pid,orden:$('op-ord').value,nombre:$('op-nom').value,
    descripcion:$('op-desc').value,
    categoria_maquina_id:esTerc?null:($('op-catm').value||null),
    maquina_id:esTerc?null:($('op-maq').value||null),
    tiempo_setup_min:esTerc?0:(parseFloat($('op-set').value)||0),
    tiempo_ciclo_seg:esTerc?0:(parseFloat($('op-cic').value)||0),
    obs:esTerc?'':$('op-obs').value,materiales:mats,
    es_tercerizada:esTerc?1:0,
    proveedor_id:esTerc?provId:null,
    precio_tercerizado:esTerc?precio:0,
    tiempo_minimo_dias:esTerc?(parseInt($('op-tdays').value)||1):0};
  if(!body.nombre){toast('Nombre requerido','w');return;}
  if(tercChecked && !esTerc){toast(VER_MONETARIO
      ? 'Tildaste "Tercerizada" pero no cargaste proveedor ni precio — se guardó como operación normal'
      : 'Tildaste "Tercerizada" pero no cargaste proveedor — se guardó como operación normal','w');}
  const res=await api('/api/operaciones',{method:'POST',body:JSON.stringify(body)});
  if(res.ok){toast('Operación agregada');closeMo('mo-op');verProc(pid,curProdNom);}
  else toast(res.error||'Error','e');
}

async function delOp(oid){
  if(!await confirmar('¿Eliminar esta operación?'))return;
  const res=await apiBorrar('/api/operaciones/'+oid,'Operación eliminada');
  if(res.ok){toast('Operación eliminada');verProc(curProdId,curProdNom);}
  else toast(res.error||'Error','e');
}

async function openProd(){
  $('prod-id').value='';
  $('prod-bar').value='';
  $('prod-cajon').value='';
  if(!_catP.length)_catP=await api('/api/categorias_producto');
  await selLoad('prod-cat',[{id:'',nombre:'— Sin categoría —'},..._catP],null);
  if(!_cli.length)_cli=await api('/api/clientes');
  await selLoad('prod-cli-id',[{id:'',razon:'— Sin cliente —'},..._cli.map(function(c){return{id:c.id,nombre:c.razon};})],null);
  openMo('mo-prod');
}

async function openCopyProd(pid){
  const cached = _prod.find(function(p){return p.id===pid||p.id===parseInt(pid);});
  $('cprod-orig').textContent = cached ? cached.codigo+' — '+cached.nombre : 'Producto '+pid;
  $('cprod-pid').value = pid;
  $('cprod-cod').value = '';
  $('cprod-nom').value = '';
  openMo('mo-copy-prod');
  // Focus the code input after modal opens
  setTimeout(function(){ $('cprod-cod').focus(); }, 80);
}

async function saveCopyProd(){
  const pid = $('cprod-pid').value;
  const codigo = $('cprod-cod').value.trim();
  const nombre = $('cprod-nom').value.trim();
  if(!codigo){toast('Ingresá el nuevo código','w');$('cprod-cod').focus();return;}
  const res = await api('/api/productos/'+pid+'/copiar',
    {method:'POST', body:JSON.stringify({codigo, nombre})});
  if(res.ok){
    toast('Producto '+res.codigo+' creado con '+res.ops_copiadas+' operaciones copiadas');
    closeMo('mo-copy-prod');
    _prod = [];
    loadProd();
  } else {
    toast(res.error||'Error al copiar','e');
    $('cprod-cod').focus();
  }
}

async function editProd(r){
  $('prod-id').value=r.id;$('prod-cod').value=r.codigo;$('prod-nom').value=r.nombre;
  $('prod-desc').value=r.descripcion||'';$('prod-uni').value=r.unidad;
  $('prod-ths').value=r.tiempo_total_hs;$('prod-cm').value=r.costo_mat;
  $('prod-cmo').value=r.costo_mo;$('prod-pv').value=r.precio_venta;
  $('prod-peso').value=r.peso_kg||0;
  $('prod-cajon').value=r.capacidad_cajon||'';
  $('prod-bar').value=r.codigo_barras||'';
  if($('prod-cli-id')) selLoad('prod-cli-id',[{id:'',nombre:'— Sin cliente —'},...(_cli.length?_cli:await api('/api/clientes')).map(function(c){return{id:c.id,nombre:c.razon};})],r.cliente_id||null);
  $('prod-obs').value=r.obs||'';
  if(!_catP.length)_catP=await api('/api/categorias_producto');
  await selLoad('prod-cat',[{id:'',nombre:'— Sin categoría —'},..._catP],r.categoria_id);
  openMo('mo-prod');
}

async function saveProd(){
  const id=$('prod-id').value;
  const body={codigo:$('prod-cod').value,nombre:$('prod-nom').value,descripcion:$('prod-desc').value,
    categoria_id:$('prod-cat').value||null,unidad:$('prod-uni').value,
    tiempo_total_hs:$('prod-ths').value||0,
    peso_kg:parseFloat($('prod-peso').value)||0,
    cliente_id:$('prod-cli-id').value?parseInt($('prod-cli-id').value):null,
    codigo_barras:$('prod-bar').value.trim(),
    obs:$('prod-obs').value,activo:true};
  // Solo roles con permiso monetario pueden enviar costos y precio
  if(ROL!=='operario' && VER_MONETARIO){
    body.costo_mat=$('prod-cm').value||0;
    body.costo_mo=$('prod-cmo').value||0;
    body.precio_venta=$('prod-pv').value||0;
  }
  if(!body.codigo||!body.nombre){toast('Código y nombre requeridos','w');return;}
  const cajon=Number($('prod-cajon').value);
  if(!Number.isInteger(cajon)||cajon<1){toast('Piezas por cajón es obligatorio (número entero mayor a 0)','w');$('prod-cajon').focus();return;}
  body.capacidad_cajon=cajon;
  const res=await api(id?'/api/productos/'+id:'/api/productos',{method:id?'PUT':'POST',body:JSON.stringify(body)});
  if(res.ok){toast(id?'Producto actualizado':'Producto creado');closeMo('mo-prod');$('prod-id').value='';_prod=[];loadProd();}
  else toast(res.error||'Error','e');
}

// loadMRP defined below (v3 full version)

// ── Versiones de producto ─────────────────────────────────────────────────────
let _curVersionProdId = null;

// Cargar versiones del producto
async function cargarVersiones(productId) {
  const container = document.getElementById('versiones-list');
  container.innerHTML = '<div class="text-center text-muted py-4"><i class="bi bi-hourglass-split"></i> Cargando...</div>';

  try {
    const res = await fetch(`/api/productos/${productId}/versiones`);
    const versiones = await res.json();

    if (versiones.length === 0) {
      container.innerHTML = '<div class="text-center text-muted py-4">No hay versiones guardadas</div>';
      return;
    }

    let html = `
      <table class="table table-sm">
        <thead>
          <tr>
            <th>Versión</th>
            <th>Cambio realizado</th>
            <th>Usuario</th>
            <th>Fecha</th>
            <th>Acciones</th>
          </tr>
        </thead>
        <tbody>
    `;

    versiones.forEach(v => {
      html += `
        <tr>
          <td><strong>v${v.version_num}</strong></td>
          <td>${v.motivo || '—'}</td>
          <td>${v.creado_por || '—'}</td>
          <td>${new Date(v.creado).toLocaleString('es-AR')}</td>
          <td>
            <button class="btn btn-sm btn-primary" onclick="verVersion(${productId}, ${v.id})">
              Ver producto
            </button>
            <button class="btn btn-sm btn-outline-danger" onclick="eliminarVersion(${productId}, ${v.id})">
              Eliminar
            </button>
          </td>
        </tr>
      `;
    });

    html += '</tbody></table>';
    container.innerHTML = html;
  } catch (err) {
    container.innerHTML = '<div class="alert alert-danger">Error al cargar versiones</div>';
  }
}

// Ver versión del producto con sus operaciones
let _curVersionSnapshot = null;

async function verVersion(productId, versionId) {
  try {
    const res = await fetch(`/api/productos/${productId}/versiones/${versionId}`);
    const version = await res.json();

    const snapshot = version.snapshot;
    _curVersionSnapshot = snapshot; // se usa luego al abrir "Ver proceso completo"
    const prod = snapshot.producto;
    const operaciones = snapshot.operaciones || [];

    // Info del producto (todos los campos, no solo algunos)
    document.getElementById('ver-prod-codigo').textContent = prod.codigo || '—';
    document.getElementById('ver-prod-nombre').textContent = prod.nombre || '—';
    document.getElementById('ver-prod-categoria').textContent = prod.categoria_nombre || '—';
    document.getElementById('ver-prod-cliente').textContent = prod.cliente_nombre || '—';
    document.getElementById('ver-prod-unidad').textContent = prod.unidad || '—';
    document.getElementById('ver-prod-peso').textContent = (prod.peso_kg && prod.peso_kg > 0) ? (prod.peso_kg + ' kg') : '—';
    document.getElementById('ver-prod-tiempo').textContent = `${prod.tiempo_total_hs || 0} hs`;
    document.getElementById('ver-prod-estado').textContent = prod.activo ? 'Activo' : 'Inactivo';
    document.getElementById('ver-prod-costo').textContent = fmtMD(prod.costo_mat);
    document.getElementById('ver-prod-costomo').textContent = fmtMD(prod.costo_mo);
    document.getElementById('ver-prod-precio').textContent = fmtMD(prod.precio_venta);
    // Ocultar valores monetarios para el rol operario
    const ocultarMonetario = (ROL === 'operario' || !VER_MONETARIO) ? 'none' : '';
    document.getElementById('ver-prod-costo-wrap').style.display = ocultarMonetario;
    document.getElementById('ver-prod-costomo-wrap').style.display = ocultarMonetario;
    document.getElementById('ver-prod-precio-wrap').style.display = ocultarMonetario;
    document.getElementById('ver-prod-desc').textContent = prod.descripcion || '—';
    document.getElementById('ver-prod-obs').textContent = prod.obs || '—';

    // Resumen de operaciones (el detalle completo se ve con el botón)
    document.getElementById('ver-ops-resumen').textContent =
      operaciones.length
        ? `${operaciones.length} operación${operaciones.length === 1 ? '' : 'es'} definida${operaciones.length === 1 ? '' : 's'} en esta versión`
        : 'Sin operaciones definidas en esta versión';

    // Mostrar modal
    openMo('mo-version');
  } catch (err) {
    toast('Error al cargar la versión','e');
  }
}

// Ver el proceso completo (todas las operaciones con toda su info) de la versión actualmente abierta
function verVersionProcesoCompleto() {
  if (!_curVersionSnapshot) return;
  const operaciones = _curVersionSnapshot.operaciones || [];
  const cont = document.getElementById('ver-proc-detail');

  if (!operaciones.length) {
    cont.innerHTML = '<div class="em">Sin operaciones definidas en esta versión.</div>';
    openMo('mo-version-proc');
    return;
  }

  let html = '';
  sortOpsNumeric(operaciones).forEach(op => {
    const matsArr = (op.materiales && op.materiales.length)
      ? op.materiales.map(m => `<span class="tag tag-g">${m.mat_descripcion || m.mat_codigo || '—'}: ${fN(m.cantidad)} ${m.unidad || m.mat_unidad || ''}</span>`)
      : [];
    const tercBadge = op.es_tercerizada ? '<span class="b br" style="font-size:10px;margin-left:6px">TERCERIZADO</span>' : '';

    html += '<div class="opc"><div class="oph"><div>';
    html += `<div class="opn">${op.orden}. ${op.nombre || ''}${tercBadge}</div>`;
    if (op.es_tercerizada) {
      html += `<div class="opm">Proveedor: ${op.proveedor_nombre || '—'} · Precio: ${fmtMD(op.precio_tercerizado)} · Plazo mínimo: ${op.tiempo_minimo_dias || '—'} días</div>`;
    } else {
      html += `<div class="opm">${op.cat_maq_nombre || 'Cualquier máquina'}${op.maquina_nombre ? ' · ' + op.maquina_nombre : ''}</div>`;
    }
    html += '</div><div style="text-align:right;font-size:11px;color:var(--color-text-secondary)">';
    html += `Setup: ${op.tiempo_setup_min || 0} min &nbsp; Ciclo: ${op.tiempo_ciclo_seg || 0} seg`;
    html += '</div></div>';
    html += `<div style="font-size:12px;color:var(--color-text-secondary);margin-bottom:5px"><strong>Descripción:</strong> ${op.descripcion || '—'}</div>`;
    html += `<div style="font-size:12px;color:var(--color-text-secondary);margin-bottom:5px"><strong>Observaciones:</strong> ${op.obs || '—'}</div>`;
    if (matsArr.length) {
      html += '<div style="margin-top:4px">' + matsArr.join('') + '</div>';
    } else {
      html += '<div style="font-size:12px;color:var(--color-text-secondary)"><strong>Materiales:</strong> sin materiales asignados</div>';
    }
    html += '</div>';
  });

  cont.innerHTML = html;
  openMo('mo-version-proc');
}

// Eliminar versión
async function eliminarVersion(productId, versionId) {
  if (!await confirmar('¿Eliminar esta versión?')) return;

  try {
    const res = await apiBorrar(`/api/productos/${productId}/versiones/${versionId}`, 'Versión eliminada');

    if (res.ok) {
      cargarVersiones(productId);
    } else {
      toast('Error al eliminar la versión','e');
    }
  } catch (err) {
    toast('Error al eliminar la versión','e');
  }
}

// ── Archivos de producto ─────────────────────────────────────────────────────
function _fmtSize(bytes){
  if(bytes<1024) return bytes+' B';
  if(bytes<1024*1024) return (bytes/1024).toFixed(1)+' KB';
  return (bytes/(1024*1024)).toFixed(1)+' MB';
}

const _archSub={};
function _encPath(p){return (p||'').split('/').filter(Boolean).map(encodeURIComponent).join('/');}
function irCarpetaProd(pid,sub){_archSub[pid]=sub||'';loadArchivosProd(pid);}
async function loadArchivosProd(pid){
  const el=document.getElementById('prod-files-list-'+pid);
  if(!el) return;
  const sub=_archSub[pid]||'';
  const data=await api('/api/productos/'+pid+'/archivos'+(sub?'?sub='+encodeURIComponent(sub):''));
  if(data.error){ if(sub){_archSub[pid]='';return loadArchivosProd(pid);} el.innerHTML='<div class="em">'+data.error+'</div>';return; }
  const files=data.archivos||[], folders=data.carpetas||[];
  const canDel=['admin'].includes(ROL);
  el.innerHTML='';
  // Ruta (breadcrumb)
  const bc=document.createElement('div'); bc.style.cssText='font-size:12px;margin-bottom:6px';
  const partes=sub?sub.split('/'):[];
  let h='<a href="#" onclick="irCarpetaProd('+pid+',\'\');return false">📁 Raíz</a>', acc='';
  partes.forEach(function(x){acc+=(acc?'/':'')+x; h+=' / <a href="#" onclick="irCarpetaProd('+pid+','+JSON.stringify(acc).replace(/"/g,'&quot;')+');return false">'+x+'</a>';});
  bc.innerHTML=h;
  if(sub && canDel && !files.length && !folders.length){
    bc.innerHTML+=' <button class="btn btn-s btn-d" style="margin-left:8px" onclick="eliminarCarpetaProd('+pid+')">Eliminar esta carpeta</button>';
  }
  el.appendChild(bc);
  if(!files.length && !folders.length){
    const em=document.createElement('div'); em.className='em'; em.style.padding='8px 0';
    em.textContent='Carpeta vacía. Subí planos, imágenes o documentos, o creá subcarpetas.'; el.appendChild(em); return;
  }
  const grid=document.createElement('div');
  grid.style.cssText='display:flex;flex-wrap:wrap;gap:8px;padding:4px 0';
  folders.forEach(function(fo){
    const card=document.createElement('div');
    card.style.cssText='border:1px solid var(--color-border-tertiary);border-radius:8px;padding:8px 10px;min-width:130px;max-width:180px;font-size:11px;cursor:pointer;background:var(--color-background-secondary)';
    card.innerHTML='<div style="font-size:28px;text-align:center;margin-bottom:4px">📁</div><div style="font-weight:600;word-break:break-all;text-align:center">'+fo.nombre+'</div><div style="color:var(--color-text-secondary);text-align:center;margin-top:2px">'+fo.items+' elemento(s)</div>';
    card.onclick=function(){ irCarpetaProd(pid,(sub?sub+'/':'')+fo.nombre); };
    grid.appendChild(card);
  });
  files.forEach(function(f){
    const ruta=f.ruta||f.nombre;
    const url='/api/productos/'+pid+'/archivos/'+_encPath(ruta);
    const card=document.createElement('div');
    card.style.cssText='border:1px solid var(--color-border-tertiary);border-radius:8px;padding:8px 10px;min-width:130px;max-width:180px;font-size:11px';
    if(f.is_img){
      const a=document.createElement('a'); a.href=url; a.target='_blank';
      const img=document.createElement('img'); img.src=url;
      img.style.cssText='width:100%;height:80px;object-fit:cover;border-radius:4px;margin-bottom:4px;display:block';
      a.appendChild(img); card.appendChild(a);
    } else {
      const ico=document.createElement('div');
      ico.style.cssText='font-size:28px;text-align:center;margin-bottom:4px';
      ico.textContent=f.is_pdf?'📄':'📎'; card.appendChild(ico);
    }
    const nm=document.createElement('div'); nm.style.cssText='font-weight:600;word-break:break-all;line-height:1.3'; nm.textContent=f.nombre; card.appendChild(nm);
    const sz=document.createElement('div'); sz.style.cssText='color:var(--color-text-secondary);margin-top:2px'; sz.textContent=_fmtSize(f.size); card.appendChild(sz);
    const btns=document.createElement('div'); btns.style.cssText='display:flex;gap:4px;margin-top:6px';
    const aVer=document.createElement('a'); aVer.href=url; aVer.target='_blank'; aVer.className='btn btn-s'; aVer.textContent='Ver'; aVer.style.flex='1'; aVer.style.textAlign='center'; btns.appendChild(aVer);
    const aDl=document.createElement('a'); aDl.href=url; aDl.download=f.nombre; aDl.className='btn btn-s'; aDl.textContent='↓'; aDl.style.flex='1'; aDl.style.textAlign='center'; btns.appendChild(aDl);
    if(canDel){
      const bDel=document.createElement('button'); bDel.className='btn btn-s btn-d'; bDel.textContent='✕';
      bDel.onclick=function(){ deleteArchivoProd(pid, ruta); };
      btns.appendChild(bDel);
    }
    card.appendChild(btns);
    grid.appendChild(card);
  });
  el.appendChild(grid);
}

async function nuevaCarpetaProd(pid){
  const nombre=await pedirTexto('Nombre de la nueva carpeta'+((_archSub[pid]||'')?' (dentro de '+_archSub[pid]+')':'')+':');
  if(!nombre||!nombre.trim()) return;
  const res=await api('/api/productos/'+pid+'/carpetas',{method:'POST',body:JSON.stringify({nombre:nombre.trim(),sub:_archSub[pid]||''})});
  if(res.ok){ toast('Carpeta creada'); loadArchivosProd(pid); } else toast(res.error||'Error','e');
}
async function eliminarCarpetaProd(pid){
  const sub=_archSub[pid]||''; if(!sub) return;
  if(!await confirmar('¿Eliminar la carpeta "'+sub+'"?')) return;
  const res=await apiBorrar('/api/productos/'+pid+'/carpetas?sub='+encodeURIComponent(sub),'Carpeta eliminada');
  if(res.ok){ toast('Carpeta eliminada'); _archSub[pid]=sub.split('/').slice(0,-1).join('/'); loadArchivosProd(pid); }
  else toast(res.error||'Error','e');
}

async function uploadArchivosProd(pid, input){
  const files=Array.from(input.files);
  if(!files.length) return;
  let ok=0,err=0;
  for(const file of files){
    const fd=new FormData();
    fd.append('file',file);
    fd.append('sub',_archSub[pid]||'');
    try{
      const r=await fetch('/api/productos/'+pid+'/archivos',{method:'POST',body:fd});
      const d=await r.json();
      if(d.ok) ok++; else err++;
    }catch(e){err++;}
  }
  input.value='';
  toast(ok+' archivo'+(ok!==1?'s':'')+' subido'+(ok!==1?'s':'')+(err?' ('+err+' errores)':''));
  loadArchivosProd(pid);
}

async function deleteArchivoProd(pid, ruta){
  if(!await confirmar('¿Eliminar "'+ruta+'"?')) return;
  const res=await apiBorrar('/api/productos/'+pid+'/archivos/'+_encPath(ruta),'Archivo eliminado');
  if(res.ok){ toast('Archivo eliminado'); loadArchivosProd(pid); }
  else toast(res.error||'Error','e');
}


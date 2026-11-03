// ── Edit material ─────────────────────────────────────────────────────────────
async function openEditMat(id){
  // Se busca primero en las filas que se están mostrando en Inventario (son
  // las del botón "Editar" que se tocó). _mat_cache NO es confiable acá: se
  // vacía al guardar estando en una pestaña filtrada y otros módulos (p.ej.
  // Procesos, al abrir una operación) la pisan con solo una categoría. Si
  // igual no aparece, se trae la lista completa del server.
  const _id=parseInt(id);
  let r=(_invRawRows||[]).find(function(x){return x.id===_id;})
     ||_mat_cache.get(_id)||_mat_cache_pt.get(_id);
  if(!r){
    const allM=await api('/api/materiales');
    if(Array.isArray(allM)){
      allM.forEach(function(x){_mat_cache.set(x.id,x);});
      r=allM.find(function(x){return x.id===_id;});
    }
  }
  if(!r){toast('Artículo no encontrado','e');return;}
  $('emat-id').value=r.id;
  $('emat-cod').value=r.codigo;
  // Tabla única: un producto terminado tiene producto_id = su propio id y su
  // código se edita libremente. Solo los semielaborados (producto_id apunta a
  // OTRO artículo) tienen código generado por el sistema.
  const esEspejoProducto=!!r.producto_id && r.producto_id!==r.id;
  $('emat-cod').readOnly=esEspejoProducto;
  $('emat-cod').style.background=esEspejoProducto?'var(--color-background-secondary)':'';
  $('emat-cod-hint').style.display=esEspejoProducto?'':'none';
  $('emat-des').value=r.descripcion;
  $('emat-tip').value=r.categoria||'Material';
  $('emat-tip').dataset.espejo=esEspejoProducto?'1':'0';
  await _cargarClientesMat('emat',r.cliente_id);
  $('emat-tip').disabled=esEspejoProducto;
  $('emat-bar').value=r.codigo_barras||'';
  $('emat-uni').value=r.unidad||'kg';
  $('emat-min').value=r.stock_min||0;
  $('emat-max').value=r.stock_max||0;
  $('emat-pre').value=r.precio_unit||0;
  $('emat-obs').value=r.obs||'';
  if(!_catP.length)_catP=await api('/api/categorias_producto');
  const sc=$('emat-cp');sc.innerHTML='<option value="">— Sin categoría —</option>';
  _catP.forEach(function(c){const o=document.createElement('option');o.value=c.id;o.textContent=c.nombre;if(c.id==r.categoria_producto_id)o.selected=true;sc.appendChild(o);});
  if(!_prov.length)_prov=await api('/api/proveedores');
  const sp=$('emat-prv');sp.innerHTML='<option value="">— Sin proveedor —</option>';
  _prov.forEach(function(p){const o=document.createElement('option');o.value=p.id;o.textContent=p.razon;if(p.id==r.proveedor_id)o.selected=true;sp.appendChild(o);});
  openMo('mo-edit-mat');
}

async function saveEditMat(){
  const id=$('emat-id').value;
  const puedeEditarPrecio=(ROL==='admin' && VER_MONETARIO);
  const body={
    codigo:$('emat-cod').value.trim(),
    descripcion:$('emat-des').value,
    categoria:$('emat-tip').value,
    cliente_id:$('emat-cli').value?parseInt($('emat-cli').value):null,
    codigo_barras:$('emat-bar').value.trim(),
    categoria_producto_id:$('emat-cp').value||null,
    unidad:$('emat-uni').value,
    stock_min:parseFloat($('emat-min').value)||0,
    stock_max:parseFloat($('emat-max').value)||0,
    proveedor_id:$('emat-prv').value||null,
    obs:$('emat-obs').value
  };
  if(puedeEditarPrecio) body.precio_unit=parseFloat($('emat-pre').value)||0;
  if(!body.descripcion){toast('Descripción requerida','w');return;}
  const res=await api('/api/materiales/'+id,{method:'PUT',body:JSON.stringify(body)});
  if(res.ok){toast('Artículo actualizado');closeMo('mo-edit-mat');_mat=[];_mat_cache=new Map();_prod=[];loadInv();}
  else toast(res.error||'Error','e');
}

// ── Módulo Movimientos (página completa) ──────────────────────────────────────
document.querySelectorAll('#mov-tabs .tab').forEach(t=>t.addEventListener('click',()=>{
  document.querySelectorAll('#mov-tabs .tab').forEach(x=>x.classList.remove('active'));
  t.classList.add('active');$('mov-tipo-fil').value=t.dataset.e;loadMovimientos();
}));
async function loadMovimientos(){
  const mid=$('mov-mat-fil').value;
  const tipo=$('mov-tipo-fil').value;
  let url='/api/movimientos';
  const params=[];
  if(mid) params.push('material_id='+mid);
  if(tipo) params.push('tipo='+tipo);
  if($('mov-origen-fil').value) params.push('origen='+$('mov-origen-fil').value);
  if($('mov-desde-fil').value) params.push('desde='+$('mov-desde-fil').value);
  if($('mov-hasta-fil').value) params.push('hasta='+$('mov-hasta-fil').value);
  if($('mov-q-fil').value.trim()) params.push('q='+encodeURIComponent($('mov-q-fil').value.trim()));
  if(params.length) url+='?'+params.join('&');

  $('mov-list').innerHTML='<div class="ld">Cargando...</div>';
  if(_mat_cache.size===0){
    const allM=await api('/api/materiales');
    _mat_cache=new Map(allM.map(function(r){return[r.id,r];}));
  }
  const rows=await api(url);
  $('mov-count-label').textContent=rows.length;
  if(!rows.length){$('mov-list').innerHTML='<div class="em">No hay movimientos para los filtros seleccionados.</div>';return;}

  let h='<table><tr><th>Fecha</th><th>Artículo</th><th>Tipo</th><th>Cantidad</th><th>Lote</th><th>Origen</th><th>Referencia</th><th>Usuario</th></tr>';
  rows.forEach(function(r){
    const mat=_mat_cache.get(parseInt(r.material_id));
    const mid2=parseInt(r.material_id);
    const matLabel=mat?('<a href="#" onclick="goToMatMov('+mid2+');return false;" style="color:var(--color-text-info);text-decoration:none">'+mat.codigo+'</a>'):'—';
    const tipCol=r.tipo==='entrada'?'bg':r.tipo==='salida'?'br':'ba';
    h+='<tr><td>'+fmtD(r.fecha)+'</td>'
      +'<td>'+matLabel+'</td>'
      +'<td><span class="b '+tipCol+'">'+r.tipo+'</span></td>'
      +'<td><b>'+fN(r.cantidad)+'</b></td>'
      +'<td>'+(r.lote_numero?'<span class="b ba">'+r.lote_numero+'</span>':'—')+'</td>'
      +'<td>'+(r.origen||'—')+'</td>'
      +'<td>'+(r.referencia||'—')+'</td>'
      +'<td>'+(r.usuario_nombre||'—')+'</td></tr>';
  });
  $('mov-list').innerHTML=h+'</table>';
}
function clearMovFiltros(){
  $('mov-mat-fil').value='';$('mov-mat-fil-txt').value='';$('mov-tipo-fil').value='';
  $('mov-origen-fil').value='';$('mov-desde-fil').value='';$('mov-hasta-fil').value='';$('mov-q-fil').value='';
  document.querySelectorAll('#mov-tabs .tab').forEach(x=>x.classList.toggle('active',x.dataset.e===''));
  loadMovimientos();
}

function goToMatMov(matId){
  // Navigate to movimientos page and filter by this material
  document.querySelectorAll('.ni').forEach(function(n){n.classList.remove('active');});
  document.querySelectorAll('.page').forEach(function(p){p.classList.remove('active');});
  const navEl=document.querySelector('[data-p="movimientos"]');
  if(navEl)navEl.classList.add('active');
  $('p-movimientos').classList.add('active');
  // Set filter and load
  const mat=_mat_cache.get(parseInt(matId));
  $('mov-mat-fil').value=matId;
  $('mov-mat-fil-txt').value=mat?(mat.codigo+' — '+mat.descripcion):'';
  loadMovimientos();
}

function filtrarMovMatFil(){
  const q=($('mov-mat-fil-txt').value||'').toLowerCase().trim();
  const drop=$('mov-mat-fil-drop');
  if(!q){
    drop.style.display='none';
    if($('mov-mat-fil').value){ $('mov-mat-fil').value=''; loadMovimientos(); }
    return;
  }
  if(!_mat.length){
    drop.innerHTML='<div style="padding:8px 12px;font-size:12px;color:var(--color-text-secondary)">Cargando...</div>';
    drop.style.display='block';
    api('/api/materiales').then(function(rows){ _mat=rows; filtrarMovMatFil(); });
    return;
  }
  const lista=_mat.filter(function(m){
    return (m.codigo&&m.codigo.toLowerCase().includes(q)) || (m.descripcion&&m.descripcion.toLowerCase().includes(q));
  }).slice(0,40);
  if(!lista.length){
    drop.innerHTML='<div style="padding:8px 12px;font-size:12px;color:var(--color-text-secondary)">Sin resultados.</div>';
    drop.style.display='block';
    return;
  }
  drop.innerHTML='';
  lista.forEach(function(m){
    const row=document.createElement('div');
    row.style.cssText='padding:7px 12px;font-size:12px;cursor:pointer;border-bottom:1px solid var(--color-border-tertiary)';
    row.onmouseenter=function(){this.style.background='var(--color-background-secondary)';};
    row.onmouseleave=function(){this.style.background='';};
    row.innerHTML='<span style="font-weight:600">'+m.codigo+'</span> <span style="color:var(--color-text-secondary)">— '+m.descripcion+'</span>';
    row.onmousedown=function(e){ e.preventDefault(); seleccionarMovMatFil(m.id, m.codigo+' — '+m.descripcion); };
    drop.appendChild(row);
  });
  drop.style.display='block';
}
function seleccionarMovMatFil(id, texto){
  $('mov-mat-fil').value=id;
  $('mov-mat-fil-txt').value=texto;
  $('mov-mat-fil-drop').style.display='none';
  loadMovimientos();
}

// Inventory codes are clickable via goToMatMov inline in the table row



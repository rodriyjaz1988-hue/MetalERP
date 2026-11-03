// ── Edit operacion ────────────────────────────────────────────────────────────
async function openOpEditById(opId, pid){
  // Fetch all ops for this product and find the one we need
  const prod=await api('/api/productos/'+pid);
  if(!prod||!prod.operaciones){toast('Error cargando operación','e');return;}
  const op=prod.operaciones.find(function(o){return o.id===opId;});
  if(!op){toast('Operación no encontrada','e');return;}
  openOpEdit(op,pid);
}

async function openOpEdit(op, pid){
  $('ope-id').value=op.id;
  $('ope-pid').value=pid;
  $('ope-ord').value=op.orden;
  $('ope-nom').value=op.nombre;
  $('ope-desc').value=op.descripcion||'';
  $('ope-set').value=op.tiempo_setup_min||0;
  $('ope-cic').value=op.tiempo_ciclo_seg||0;
  const isTerc=!!(op.es_tercerizada);
  $('ope-terc').checked=isTerc;
  const tercFields=document.getElementById('ope-campos-terc');
  if(tercFields) tercFields.style.display=isTerc?'block':'none';
  // Siempre cargar la lista de proveedores en el select, no solo cuando la
  // operación ya es tercerizada, para que esté disponible si el usuario
  // tilda "Tercerizada" recién en esta edición.
  if(!_prov.length)_prov=await api('/api/proveedores');
  setProvOp('ope',op.proveedor_id||null);
  if($('ope-precio')) $('ope-precio').value=op.precio_tercerizado||0;
  if($('ope-tdays')) $('ope-tdays').value=op.tiempo_minimo_dias||1;
  $('ope-obs').value=op.obs||'';
  const volAgrup=!!(op.volumen_agrupado);
  toggleVolAgrupOp('ope', volAgrup);
  if(volAgrup) $('ope-vol-agrup-valor').value=op.valor_recalculado||'';
  const esTerc=!!(op.es_tercerizada||0);
  $('ope-terc').checked=esTerc;
  toggleTercOp('ope');
  if(!_catM.length)_catM=await api('/api/categorias_maquina');
  if(!_maq.length)_maq=await api('/api/maquinas');
  if(_mat_cache.size===0){const allM=await api('/api/materiales');_mat_cache=new Map(allM.map(function(r){return[r.id,r];}));}
  await selLoad('ope-catm',[{id:'',nombre:'— Cualquiera —'},..._catM],op.categoria_maquina_id);
  await selLoad('ope-maq',[{id:'',nombre:'— Cualquiera —'},..._maq.map(function(m){return{...m,nombre:m.codigo+' — '+m.nombre};})],op.maquina_id);
  // Load proveedores for tercerizada
  await loadTercProv('ope');
  setProvOp('ope',op.proveedor_id||null);
  $('ope-precio').value=op.precio_tercerizado||0;
  $('ope-tdays').value=op.tiempo_minimo_dias||1;
  // Load existing materials
  $('ope-mats').innerHTML='';
  const opePI=document.getElementById('ope-prods-insumo');
  if(opePI) opePI.innerHTML='';
  if(op.materiales&&op.materiales.length){
    op.materiales.forEach(function(m){addOpeMat(m.material_id,m.cantidad,m.unidad,m.vida_util_herramienta);});
  }
  if(op.productos_insumo&&op.productos_insumo.length){
    if(!_prod.length) _prod=await api('/api/productos');
    op.productos_insumo.forEach(function(pi){
      agregarProductoInsumo('ope',{id:pi.producto_id,codigo:pi.codigo,nombre:pi.descripcion,unidad:pi.unidad},pi.cantidad);
    });
  }
  openMo('mo-op-edit');
}

let _opeN=0;
function addOpeMat(matId,qty,uni,vida){
  // Called when loading existing op materiales for edit
  const mat = matId ? (_mat_cache.get(parseInt(matId)) || _mat.find(function(m){return m.id==matId;})) : null;
  const desc = mat ? mat.codigo+' — '+mat.descripcion : (matId ? 'Material #'+matId : '');
  const unid = uni || (mat ? mat.unidad : 'unid');
  _agregarMaterialRow('ope-mats', matId, desc, unid, qty, vida);
}

// ── Material search (shared between op and ope modals) ───────────────────────
let _mbPrefix = 'op';

async function abrirBuscadorMaterial(prefix){
  _mbPrefix = prefix;
  $('mb-query').value = '';
  $('mb-resultados').innerHTML = '<div class="ld">Cargando materiales e insumos...</div>';
  openMo('mo-mat-buscar');
  setTimeout(function(){ $('mb-query').focus(); }, 80);
  
  // Buscar materiales, insumos y herramientas en paralelo
  const [materiales, insumos, herramientas] = await Promise.all([
    api('/api/materiales?categoria=Material'),
    api('/api/materiales?categoria=Insumo'),
    api('/api/materiales?categoria=Herramienta')
  ]);
  
  _mat = [...materiales, ...insumos, ...herramientas];
  _mat_cache = new Map(_mat.map(function(m){ return [m.id, m]; }));
  filtrarMaterialesBuscador();
}

function filtrarMaterialesBuscador(){
  const q = ($('mb-query').value||'').toLowerCase().trim();
  const lista = q
    ? _mat.filter(function(m){
        return m.codigo.toLowerCase().includes(q) || m.descripcion.toLowerCase().includes(q);
      })
    : _mat.slice(0, 40);

  if(!lista.length){
    $('mb-resultados').innerHTML = '<div class="em" style="padding:12px">Sin resultados.</div>';
    return;
  }
  const el = $('mb-resultados');
  el.innerHTML = '';
  lista.forEach(function(m){
    const row = document.createElement('div');
    row.style.cssText = 'display:flex;align-items:center;justify-content:space-between;padding:8px 12px;border-bottom:1px solid var(--color-border-tertiary);cursor:pointer';
    row.onmouseenter = function(){ this.style.background='var(--color-background-secondary)'; };
    row.onmouseleave = function(){ this.style.background=''; };
    const info = document.createElement('div');
    info.innerHTML = '<span style="font-weight:600;font-size:12px">'+m.codigo+'</span>'
      +' <span style="font-size:12px;color:var(--color-text-secondary)">'+m.descripcion+'</span>'
      +'<br><span style="font-size:10px;color:var(--color-text-secondary)">'+m.categoria
      +' · Stock: '+fN(m.stock)+' '+m.unidad+'</span>';
    const addBtn = document.createElement('button');
    addBtn.className = 'btn btn-s btn-p';
    addBtn.style.cssText = 'font-size:11px;padding:3px 8px;flex-shrink:0';
    addBtn.textContent = '+ Agregar';
    addBtn.onclick = (function(mat){ return function(e){
      e.stopPropagation();
      _agregarMaterialRow(_mbPrefix+'-mats', mat.id, mat.codigo+' — '+mat.descripcion, mat.unidad, 1);
      closeMo('mo-mat-buscar');
    }; })(m);
    row.appendChild(info);
    row.appendChild(addBtn);
    el.appendChild(row);
  });
  if(_mat.length > 40 && !q){
    const hint = document.createElement('div');
    hint.style.cssText = 'padding:8px 12px;font-size:11px;color:var(--color-text-secondary)';
    hint.textContent = 'Mostrando 40 de '+_mat.length+'. Escribí para filtrar.';
    el.appendChild(hint);
  }
}

function _agregarMaterialRow(containerId, matId, desc, unid, qty, vida){
  const el = document.getElementById(containerId);
  if(!el) return;
  // Check if already added
  if(matId && el.querySelector('[data-mat-id="'+matId+'"]')){
    toast('Ese material ya está en la lista','w'); return;
  }
  const st = 'font-size:12px;padding:3px 6px;border:1px solid var(--color-border-tertiary);border-radius:5px;background:var(--color-background-primary);color:var(--color-text-primary)';
  const row = document.createElement('div');
  row.className = 'mr';
  if(matId) row.setAttribute('data-mat-id', matId);
  row.style.cssText = 'display:flex;align-items:center;gap:6px;margin-bottom:4px;background:var(--color-background-secondary);padding:5px 8px;border-radius:6px;border:1px solid var(--color-border-tertiary)';

  // Hidden material_id input (read by saveOp/saveOpEdit)
  const hidId = document.createElement('input');
  hidId.type='hidden'; hidId.value=matId||''; hidId.className='mat-id-field';
  const nameSpan = document.createElement('span');
  nameSpan.style.cssText = 'flex:1;font-size:12px;font-weight:600';
  nameSpan.textContent = desc || '—';
  const qtyInput = document.createElement('input');
  qtyInput.type='number'; qtyInput.min='0.01'; qtyInput.step='0.01';
  qtyInput.value = qty||1; qtyInput.placeholder='Cant.';
  qtyInput.style = st+';width:65px';
  const uniInput = document.createElement('input');
  uniInput.placeholder='unid'; uniInput.value=unid||'';
  uniInput.style = st+';width:50px';
  const delBtn = document.createElement('button');
  delBtn.className='btn btn-s btn-d'; delBtn.textContent='×';
  delBtn.onclick = function(){ row.remove(); };
  // Vida útil: solo para materiales de categoría Herramienta. Con un valor,
  // las herramientas necesarias son ceil(piezas / vida útil).
  const matRef = matId ? (_mat_cache.get(parseInt(matId)) || _mat.find(function(m){return m.id==matId;})) : null;
  let vidaInput = null;
  if(matRef && matRef.categoria==='Herramienta'){
    vidaInput = document.createElement('input');
    vidaInput.type='number'; vidaInput.min='1'; vidaInput.step='1';
    vidaInput.className='mat-vida-field';
    vidaInput.value = vida||''; vidaInput.placeholder='Vida útil';
    vidaInput.title='Vida útil herramienta: piezas que hace cada herramienta. Herramientas necesarias = piezas ÷ vida útil, redondeado hacia arriba. Vacío = cantidad por pieza.';
    vidaInput.style = st+';width:80px';
  }

  row.appendChild(hidId);
  row.appendChild(nameSpan);
  row.appendChild(qtyInput);
  row.appendChild(uniInput);
  if(vidaInput){
    const lbl = document.createElement('span');
    lbl.style.cssText = 'font-size:11px;color:var(--color-text-secondary)';
    lbl.textContent = 'Vida útil (pz)';
    row.appendChild(lbl);
    row.appendChild(vidaInput);
    herrExclusivo(vidaInput,qtyInput);
  }
  row.appendChild(delBtn);
  el.appendChild(row);
}

async function saveOpEdit(){
  const id=$('ope-id').value;
  const pid=parseInt($('ope-pid').value);
  const tercChecked=$('ope-terc').checked;
  const provId=$('ope-prv').value||null;
  const precio=parseFloat($('ope-precio').value)||0;
  // "Terciarizado" solo se guarda como tal si, además de tildar el check,
  // se cargó alguna información en sus campos (proveedor o precio).
  // Sin permiso monetario el precio no se ve ni se manda: no alcanza para
  // decidir. El servidor resuelve con el precio que ya tiene guardado.
  const esTerc=tercChecked && (!!provId || precio>0 || !VER_MONETARIO);
  const materiales=[...$('ope-mats').querySelectorAll('.mr')].map(function(row){
    const hidId=row.querySelector('.mat-id-field');
    const numInputs=row.querySelectorAll('input[type="number"]');
    const mid=hidId?hidId.value:null;
    const vida=row.querySelector('.mat-vida-field');
    const qty=herrCantidad(vida,numInputs[0]);
    const uni=row.querySelector('input:not([type="number"]):not([type="hidden"])')?row.querySelector('input:not([type="number"]):not([type="hidden"])').value:'unid';
    return{tipo:'material',material_id:mid,cantidad:qty,unidad:uni,vida_util_herramienta:vida&&vida.value?parseInt(vida.value):null};
  }).filter(function(m){return m.material_id&&m.cantidad;}).concat(leerProductosInsumo('ope'));
  const volAgrupBtn=document.getElementById('ope-vol-agrup-btn');
  const volAgrup=!!(volAgrupBtn&&volAgrupBtn.classList.contains('btn-p'));
  const valorRecalc=parseFloat($('ope-vol-agrup-valor').value)||0;
  if(volAgrup&&!valorRecalc){toast('Ingresá el Valor Recalculado','w');return;}
  const body={
    nombre:$('ope-nom').value,
    orden:$('ope-ord').value,
    descripcion:$('ope-desc').value,
    obs:$('ope-obs').value,
    materiales:materiales,
    volumen_agrupado:volAgrup?1:0,
    valor_recalculado:volAgrup?valorRecalc:0,
    es_tercerizada:esTerc?1:0,
    categoria_maquina_id:esTerc?null:($('ope-catm').value||null),
    maquina_id:esTerc?null:($('ope-maq').value||null),
    tiempo_setup_min:esTerc?0:(parseFloat($('ope-set').value)||0),
    tiempo_ciclo_seg:esTerc?0:(parseFloat($('ope-cic').value)||0),
    proveedor_id:esTerc?provId:null,
    precio_tercerizado:esTerc?precio:0,
    tiempo_minimo_dias:esTerc?(parseInt($('ope-tdays').value)||1):0
  };
  if(!body.nombre){toast('Nombre requerido','w');return;}
  if(tercChecked && !esTerc){toast(VER_MONETARIO
      ? 'Tildaste "Tercerizada" pero no cargaste proveedor ni precio — se guardó como operación normal'
      : 'Tildaste "Tercerizada" pero no cargaste proveedor — se guardó como operación normal','w');}
  const res=await api('/api/operaciones/'+id,{method:'PUT',body:JSON.stringify(body)});
  if(res.ok){toast('Operación actualizada');closeMo('mo-op-edit');verProc(pid,curProdNom);}
  else toast(res.error||'Error al guardar','e');
}

// ── OT detail: operations and materials ───────────────────────────────────────
function switchOTTab(dt){
  document.querySelectorAll('#ot-det-tabs .tab').forEach(function(x){
    x.classList.toggle('active', x.dataset.dt===dt);
  });
  $('ot-det-ops').style.display  = dt==='ops'  ? 'block' : 'none';
  $('ot-det-mats').style.display = dt==='mats' ? 'block' : 'none';
}
document.querySelectorAll('#ot-det-tabs .tab').forEach(function(t){
  t.addEventListener('click', function(){ switchOTTab(t.dataset.dt); });
});

async function openOTDetail(oid,num){
  if(!num){const c=_ot_cache&&_ot_cache.get&&_ot_cache.get(oid);num=c?c.numero:'OT-'+oid;}
  $('ot-detail-title').childNodes[0].textContent='Detalle OT '+num+' ';
  $('ot-det-ops').innerHTML='<div class="ld">Cargando...</div>';
  $('ot-det-mats').innerHTML='<div class="ld">Cargando...</div>';
  switchOTTab('ops');
  openMo('mo-ot-detail');

  const canEdit=['admin','operario'].includes(ROL);
  const otData=await api('/api/ordenes/'+oid);
  const otCompletada=otData&&otData.estado==='Completada';
  const canAssignLote=ROL==='admin'&&!otCompletada;

  // Load operations — auto-populate if empty
  let ops=await api('/api/ordenes/'+oid+'/operaciones');
  if(!ops.length){
    const popRes=await api('/api/ordenes/'+oid+'/operaciones/populate',{method:'POST',body:JSON.stringify({})});
    if(popRes.ok&&popRes.ops_created>0) ops=await api('/api/ordenes/'+oid+'/operaciones');
  }
  if(!ops.length){
    $('ot-det-ops').innerHTML='<div class="em">Sin operaciones. Asegurate de que el producto tenga un proceso definido.</div>';
  } else {
    // La columna mezcla setup (minutos) con el precio pactado del tercero:
    // para el restringido se omite entera, encabezado y celdas a la vez.
    let h='<table><tr><th>Ord.</th><th>Operación</th><th>Sector</th>'+thM('Setup / Precio')+'<th>Ciclo</th><th>Req.</th><th>Producido</th><th>Estado</th><th></th></tr>';
    ops.forEach(function(op){
      const pct=op.qty_requerida>0?Math.round(op.qty_producida/op.qty_requerida*100):0;
      const pctCol=pct>=100?'bg':pct>=50?'ba':'br';
      if(op.es_tercerizada){
        // Operación tercerizada: no tiene sentido mostrar setup/ciclo de
        // máquina propia (no se fabrica acá) ni "OK" como si fuera control
        // de calidad interno — acá lo que importa es el precio pactado con
        // el proveedor y cuánto volvió recibido de lo enviado.
        const sector='<span class="b br" style="font-size:10px">TERC</span> '+(op.proveedor_nombre||'—');
        h+='<tr>'
          +'<td>'+op.orden+'</td>'
          +'<td>'+op.nombre+'</td>'
          +'<td>'+sector+'</td>'
          // Con la columna Setup/Precio omitida queda sola la de Ciclo, que
          // para una tercerizada no aplica.
          +(VER_MONETARIO
             ? ('<td colspan="2">'+(op.precio_tercerizado?fmtMD(op.precio_tercerizado):'—')+'</td>')
             : '<td>—</td>')
          +'<td>'+fN(op.qty_requerida)+'</td>'
          +'<td>'+fN(op.qty_producida)+' <span style="font-size:10px;color:var(--color-text-secondary)">(recibido)</span></td>'
          +'<td>'+sb(op.estado)+' <span style="font-size:10px;color:var(--color-text-secondary)">'+pct+'%</span></td>'
          +'<td style="white-space:nowrap">'
            +(op.ott_id?'<button class="btn btn-s" onclick="abrirPrecioOTT('+op.ott_id+')">Editar</button>':'')
          +'</td>'
          +'</tr>';
        return;
      }
      const sector=op.cat_maquina_nombre||'—';
      h+='<tr>'
        +'<td>'+op.orden+'</td>'
        +'<td>'+op.nombre+'</td>'
        +'<td>'+sector+'</td>'
        +tdM(op.tiempo_setup_min+' min')
        +'<td>'+(op.tiempo_ciclo_seg||0)+' seg</td>'
        +'<td>'+fN(op.qty_requerida)+'</td>'
        +'<td>'+fN(op.qty_producida)+'</td>'
        +'<td>'+sb(op.estado)+' <span style="font-size:10px;color:var(--color-text-secondary)">'+pct+'%</span></td>'
        +'<td style="white-space:nowrap">'
          +'<button class="btn btn-s" onclick="emitirOP('+oid+','+op.id+')" title="Imprimir OP">&#128438; Emitir OP</button>'
          +(canEdit?' <button class="btn btn-s" onclick="openEditOTOp('+op.id+','+oid+')">Editar</button>':'')
        +'</td>'
        +'</tr>';
    });
    $('ot-det-ops').innerHTML=h+'</table>';
    if(canEdit){
      $('ot-det-ops').innerHTML+='<div class="ma" style="margin-top:8px">'
        +'<button class="btn btn-s btn-p" onclick="openAddOTOp('+oid+')">+ Agregar operación</button></div>';
    }
  }

  // Load materials — populate AFTER ops (populate needs producto_id from ops)
  let mats=await api('/api/ordenes/'+oid+'/materiales');
  if(!mats.length){
    const popRes=await api('/api/ordenes/'+oid+'/materiales/populate',{method:'POST',body:JSON.stringify({})});
    if(popRes.ok&&popRes.mats>0) mats=await api('/api/ordenes/'+oid+'/materiales');
    const otsNuevas=((popRes&&popRes.ots_auxiliares)||[]).filter(function(o){return !o.actualizada;});
    if(otsNuevas.length){
      toast('Insumo(s) sin stock suficiente: se generó OT auxiliar de fabricación — '
        +otsNuevas.map(function(o){return o.numero+' ('+o.producto+' x'+fN(o.cantidad)+')';}).join(', '), 'w');
    }
  }
  // Check alert for uncovered materials
  const alerta = await api('/api/ordenes/'+oid+'/materiales/alerta');
  if(!mats.length){
    $('ot-det-mats').innerHTML='<div class="em">Sin materias primas asignadas.</div>';
  } else {
    let h='';
    if(alerta&&!alerta.ok){
      h+='<div class="al al-w" style="margin-bottom:8px">⚠ Hay materiales sin cobertura completa de lote aprobado.</div>';
    }
    const matsConLote = mats.filter(function(m){ return m.categoria!=='Insumo'&&m.categoria!=='Herramienta'; });
    h+='<table>';
    if(matsConLote.length){
      h+='<tr><th>Código</th><th>Descripción</th><th>Operación</th><th>Req.</th><th>Asignado</th><th>Unidad</th><th>Lote(s)</th><th>Cobertura</th><th></th></tr>';
    }
    mats.forEach(function(m){
      // Los insumos/herramientas se descuentan automáticamente al completar la OT, no requieren asignación de lote
      if(m.categoria==='Insumo'||m.categoria==='Herramienta') return;
      const cob=m.cantidad_requerida>0?Math.min(100,Math.round(m.cantidad_asignada/m.cantidad_requerida*100)):0;
      const cobCol=cob>=100?'bg':cob>=50?'ba':'br';
      const faltante=Math.max(0,m.cantidad_requerida-m.cantidad_asignada);
      const lotesTxt=(m.lotes_asignados&&m.lotes_asignados.length)
        ?m.lotes_asignados.map(function(l){return '<b>'+l.numero+'</b> ('+fN(l.cantidad_usada)+')';}).join(', ')
        :'<span style="color:#999">— sin lote —</span>';
      const opsTxt=(m.operaciones&&m.operaciones.length)
        ?m.operaciones.join('<br>')
        :'<span style="color:#999">—</span>';
      h+='<tr>'
        +'<td>'+m.codigo+'</td>'
        +'<td>'+m.descripcion+'</td>'
        +'<td style="font-size:12px">'+opsTxt+'</td>'
        +'<td>'+fN(m.cantidad_requerida)+'</td>'
        +'<td>'+fN(m.cantidad_asignada)+'</td>'
        +'<td>'+m.unidad+'</td>'
        +'<td>'+lotesTxt+'</td>'
        +'<td><span class="b '+cobCol+'">'+cob+'%</span></td>'
        +'<td><div style="display:flex;gap:6px;flex-wrap:nowrap;white-space:nowrap;align-items:center">'
        +(canAssignLote&&faltante>0
          ?'<button class="btn btn-s btn-p" onclick="abrirAsignLote('+oid+','+m.material_id+','+faltante+',null)">Asignar lote</button>'
          :'')
        +(canAssignLote&&m.lotes_asignados&&m.lotes_asignados.length
          ?'<button class="btn btn-s" onclick="abrirModificarLotes('+oid+','+m.material_id+',\''+(m.codigo+' — '+m.descripcion).replace(/'/g,"\\'")+'\')">Modificar</button>'
          :'')
        +(otCompletada&&m.lotes_asignados&&m.lotes_asignados.length
          ?'<span class="b bg" title="OT completada — lotes cerrados">✓</span>'
          :'')
        +'</div></td></tr>';
    });
    if(!matsConLote.length){
      h+='<tr><td colspan="9" style="text-align:center;color:#888;font-size:13px;padding:12px">Sin materiales con lote — los insumos se descuentan automáticamente al completar la OT.</td></tr>';
    }
    $('ot-det-mats').innerHTML=h+'</table>';
  }
}


// ── Editar / agregar operaciones de una OT ───────────────────────────────────
let _editOTOid = null;

// ── Materiales por operación de la OT (editable, independiente del proceso) ──
let _otopMats=[];
async function _otopEnsureMats(){ if(!_mat.length) _mat=await api('/api/materiales'); }
function otopRender(){
  const el=$('otop-mats'); if(!el) return;
  if(!_otopMats.length){ el.innerHTML='<div class="em" style="padding:4px 0">Esta operación no consume material.</div>'; return; }
  const opts=function(sel){return '<option value="">— Material —</option>'+_mat.map(function(m){return '<option value="'+m.id+'"'+(String(m.id)===String(sel)?' selected':'')+'>'+m.codigo+' — '+m.descripcion+' ('+(m.categoria||'')+')</option>';}).join('');};
  const esHerr=function(id){const m=_mat.find(function(x){return String(x.id)===String(id);});return !!(m&&m.categoria==='Herramienta');};
  el.innerHTML=_otopMats.map(function(r,i){
    return '<div style="display:flex;gap:6px;margin-bottom:4px;align-items:center">'
      +'<select style="flex:1;min-width:0" onchange="_otopMats['+i+'].material_id=this.value;otopRender()">'+opts(r.material_id)+'</select>'
      +'<input type="number" min="0" step="any" value="'+(r.cantidad||'')+'" placeholder="cant." style="width:80px" oninput="_otopMats['+i+'].cantidad=this.value">'
      +(esHerr(r.material_id)?'<input type="number" min="1" step="1" value="'+(r.vida_util_herramienta||'')+'" placeholder="Vida útil" title="Vida útil herramienta (piezas por herramienta). Vacío = cantidad por pieza." style="width:80px" oninput="_otopMats['+i+'].vida_util_herramienta=this.value">':'')
      +'<select style="width:90px" onchange="_otopMats['+i+'].tipo=this.value"><option value="material"'+(r.tipo!=='producto'?' selected':'')+'>Material</option><option value="producto"'+(r.tipo==='producto'?' selected':'')+'>Producto</option></select>'
      +'<button class="btn btn-s btn-d" type="button" onclick="_otopMats.splice('+i+',1);otopRender()">✕</button></div>';
  }).join('');
}
async function otopAddMat(){ await _otopEnsureMats(); _otopMats.push({material_id:'',cantidad:'',tipo:'material'}); otopRender(); }
async function otopLoadMats(opId){
  await _otopEnsureMats();
  if(opId){ const r=await api('/api/orden_operaciones/'+opId+'/materiales'); _otopMats=Array.isArray(r)?r.map(function(x){return {material_id:x.material_id,cantidad:x.cantidad,tipo:x.tipo||'material',unidad:x.unidad,vida_util_herramienta:x.vida_util_herramienta};}):[]; }
  else _otopMats=[];
  otopRender();
}
function otopMatsPayload(){
  return _otopMats.filter(function(r){return r.material_id&&parseFloat(r.cantidad)>0;}).map(function(r){return {material_id:parseInt(r.material_id),cantidad:parseFloat(r.cantidad),tipo:r.tipo||'material',unidad:r.unidad||null,vida_util_herramienta:parseInt(r.vida_util_herramienta)||null};});
}

async function openEditOTOp(opId, oid){
  _editOTOid = oid;
  const ops = await api('/api/ordenes/'+oid+'/operaciones');
  const op = ops.find(function(o){return o.id===opId;});
  if(!op){toast('Operación no encontrada','e');return;}

  $('otop-id').value = op.id;
  $('otop-oid').value = oid;
  $('otop-ord').value = op.orden;
  $('otop-nom').value = op.nombre;
  $('otop-set').value = op.tiempo_setup_min||0;
  $('otop-cic').value = op.tiempo_ciclo_seg||0;
  $('otop-req').value = op.qty_requerida||0;
  $('otop-est').value = op.estado||'Pendiente';
  $('otop-obs').value = op.obs||'';

  if(!_catM.length)_catM=await api('/api/categorias_maquina');
  if(!_maq.length)_maq=await api('/api/maquinas');
  await selLoad('otop-catm',[{id:'',nombre:'— Cualquier sector —'},..._catM],op.categoria_maquina_id);
  await selLoad('otop-maq',[{id:'',nombre:'— Cualquier máquina —'},..._maq.map(function(m){return{...m,nombre:m.codigo+' — '+m.nombre};})],op.maquina_id);

  $('otop-title').textContent='Editar operación';
  await otopLoadMats(opId);
  openMo('mo-otop');
}

async function openAddOTOp(oid){
  _editOTOid = oid;
  $('otop-id').value = '';
  $('otop-oid').value = oid;
  $('otop-ord').value = '';
  $('otop-nom').value = '';
  $('otop-set').value = 0;
  $('otop-cic').value = 0;
  $('otop-req').value = '';
  $('otop-est').value = 'Pendiente';
  $('otop-obs').value = '';

  if(!_catM.length)_catM=await api('/api/categorias_maquina');
  if(!_maq.length)_maq=await api('/api/maquinas');
  await selLoad('otop-catm',[{id:'',nombre:'— Cualquier sector —'},..._catM],null);
  await selLoad('otop-maq',[{id:'',nombre:'— Cualquier máquina —'},..._maq.map(function(m){return{...m,nombre:m.codigo+' — '+m.nombre};})],null);

  $('otop-title').textContent='Agregar operación';
  await otopLoadMats(null);
  openMo('mo-otop');
}

async function saveOTOp(){
  const id = $('otop-id').value;
  const oid = parseInt($('otop-oid').value);
  const body = {
    orden: $('otop-ord').value || '1',
    nombre: $('otop-nom').value,
    tiempo_setup_min: (parseFloat($('otop-set').value)||0),
    tiempo_ciclo_seg: (parseFloat($('otop-cic').value)||0),
    qty_requerida: parseFloat($('otop-req').value)||0,
    estado: $('otop-est').value,
    categoria_maquina_id: $('otop-catm').value||null,
    maquina_id: $('otop-maq').value||null,
    obs: $('otop-obs').value,
  };
  if(!body.nombre){toast('Nombre requerido','w');return;}

  let res;
  if(id){
    res = await api('/api/ordenes/'+oid+'/operaciones/'+id, {method:'PUT',body:JSON.stringify(body)});
    if(res.ok){
      const rm = await api('/api/orden_operaciones/'+id+'/materiales',{method:'PUT',body:JSON.stringify({materiales:otopMatsPayload()})});
      if(!rm.ok){ toast(rm.error||'No se pudieron guardar los materiales','e'); return; }
    }
  } else {
    body.materiales = otopMatsPayload();
    res = await api('/api/ordenes/'+oid+'/operaciones', {method:'POST',body:JSON.stringify(body)});
  }
  if(res.ok){
    toast(id?'Operación actualizada':'Operación agregada');
    closeMo('mo-otop');
    openOTDetail(oid);
  } else toast(res.error||'Error','e');
}

async function deleteOTOp(opId, oid){
  if(!await confirmar('¿Eliminar esta operación de la OT?'))return;
  const res = await apiBorrar('/api/ordenes/'+oid+'/operaciones/'+opId,'Operación quitada de la OT');
  if(res.ok){toast('Operación eliminada');closeMo('mo-otop');openOTDetail(oid);}
  else toast(res.error||'Error','e');
}



// ── Proveedores ───────────────────────────────────────────────────────────────
async function toggleProvMats(provId, cachedProv){
  const row=document.getElementById('provmats-'+provId);
  const btn=document.querySelector('#provrow-'+provId+' td:first-child button');
  if(!row) return;
  const vis=row.style.display==='none'||row.style.display==='';
  row.style.display=vis?'table-row':'none';
  if(btn) btn.textContent=vis?'▼':'▶';
  if(!vis) return;
  const body=document.getElementById('provmats-body-'+provId);
  const mats=await api('/api/proveedores/'+provId+'/materiales');
  if(!mats||!mats.length){
    body.innerHTML='<div class="em">Sin artículos en lista de precios. Usá "+ Mat." para agregar.</div>';
    return;
  }
  let h='<table style="font-size:11px"><tr><th>Código</th><th>Descripción</th><th>Precio unit.</th><th>Plazo</th><th>Principal</th></tr>';
  mats.forEach(function(m){
    h+='<tr>'
      +'<td>'+m.codigo+'</td>'
      +'<td>'+m.descripcion+'</td>'
      +'<td><b>'+fmtM(m.precio_unit)+'</b></td>'
      +'<td>'+(m.plazo_dias||'—')+'d</td>'
      +'<td>'+(m.es_principal?'<span class="b bg">✓</span>':'')+'</td>'
      +'</tr>';
  });
  body.innerHTML=h+'</table>';
  // Show active OTTs for this provider
  const otts=await api('/api/ott?proveedor_id='+provId);
  const activas=otts.filter(function(o){return o.estado!=='Completado'&&o.estado!=='Cancelado';});
  if(activas.length){
    let ho='<div style="margin-top:10px;font-weight:600;font-size:11px;color:var(--color-text-secondary);margin-bottom:4px">OTTs activas</div>';
    ho+='<table style="font-size:11px"><tr><th>N°</th><th>Producto</th><th>Estado</th><th>Precio</th></tr>';
    activas.forEach(function(o){
      ho+='<tr><td><b>'+o.numero+'</b></td><td>'+(o.producto_codigo||'—')+'</td>'
        +'<td>'+o.estado+'</td><td>'+fmtM(o.precio_acordado||0,o.moneda)+'</td></tr>';
    });
    body.innerHTML+=ho+'</table>';
  }
}

let _provF='';      // pestaña activa: '', 'Activo', 'Inactivo'
let _provSel=null;  // id del proveedor seleccionado
document.querySelectorAll('#prov-tabs .tab').forEach(t=>t.addEventListener('click',()=>{
  document.querySelectorAll('#prov-tabs .tab').forEach(x=>x.classList.remove('active'));
  t.classList.add('active');_provF=t.dataset.e;loadProv();
}));

function clearFiltrosProv(){
  if($('prov-search'))$('prov-search').value='';
  _provF='';
  document.querySelectorAll('#prov-tabs .tab').forEach(x=>x.classList.toggle('active',x.dataset.e===''));
  loadProv();
}

// Selecciona un proveedor sin volver a pintar la tabla (así no se pliegan
// las filas de materiales que estén desplegadas).
function selProv(id){
  _provSel=id;
  document.querySelectorAll('#prov-list tr.ot-sel').forEach(function(tr){tr.classList.remove('ot-sel');});
  const tr=document.getElementById('provrow-'+id);
  if(tr){
    tr.classList.add('ot-sel');
    const rd=tr.querySelector('input[type=radio]'); if(rd) rd.checked=true;
  }
  actualizarToolbarProv();
}
function actualizarToolbarProv(){
  const r=_provSel?_prov.find(function(p){return String(p.id)===String(_provSel);}):null;
  const lbl=$('prov-sel-label');
  if(lbl){
    const t=r?(r.razon||'#'+r.id):'–';
    lbl.textContent=t.length>28?t.slice(0,27)+'…':t;
    lbl.title=r?t:'Proveedor seleccionado';
  }
  ['edit','mat','hist'].forEach(function(k){const b=$('prov-b-'+k);if(b)b.disabled=!r;});
}
function provSelAccion(a){
  const r=_provSel?_prov.find(function(p){return String(p.id)===String(_provSel);}):null;
  if(!r){toast('Seleccioná un proveedor de la lista','w');return;}
  if(a==='edit') editProv(r);
  else if(a==='mat') openLM(r.id);
  else if(a==='hist') openHistorialCompra(r.id, r.razon);
}

async function loadProv(){
  if(!_prov.length)_prov=await api('/api/proveedores');
  const el=$('prov-list');
  if(!_prov.length){el.innerHTML='<div class="em">No hay proveedores. Usá «Agregar» para cargar el primero.</div>';actualizarToolbarProv();return;}
  const q=($('prov-search')?$('prov-search').value:'').trim().toLowerCase();
  let list=_prov;
  if(_provF) list=list.filter(function(r){return (r.estado||'Activo')===_provF;});
  if(q) list=list.filter(function(r){
    return (r.razon||'').toLowerCase().includes(q)
      ||(r.contacto||'').toLowerCase().includes(q)
      ||(r.telefono||'').toLowerCase().includes(q);
  });
  if(_provSel && !_prov.some(function(p){return String(p.id)===String(_provSel);})) _provSel=null;
  if(!list.length){
    el.innerHTML='<div class="em">'+(q?'No se encontraron proveedores para "'+q+'".':'No hay proveedores para el filtro seleccionado.')+'</div>';
    actualizarToolbarProv();return;
  }
  const tbl=document.createElement('table');
  tbl.innerHTML='<tr><th style="width:24px"></th><th>Razón social</th><th>Contacto</th><th>Teléfono</th><th>Plazo</th><th>Calificación</th><th>Estado</th><th>Lista de precios</th></tr>';
  const tbody=document.createElement('tbody');
  list.forEach(function(r){
    const tr=document.createElement('tr');
    tr.id='provrow-'+r.id;
    tr.style.cursor='pointer';
    if(String(_provSel)===String(r.id)) tr.className='ot-sel';
    const hasMats=r.mat_vinculados&&r.mat_vinculados.length;
    tr.innerHTML='<td style="white-space:nowrap"><input type="radio" name="prov-sel" '+(String(_provSel)===String(r.id)?'checked':'')+'> <button class="btn btn-s" style="padding:2px 5px;font-size:11px" title="Ver lista de precios">▶</button></td>'
      +'<td><b>'+r.razon+'</b></td>'
      +'<td>'+(r.contacto||'—')+'</td>'
      +'<td>'+(r.telefono||'—')+'</td>'
      +'<td>'+(r.plazo_dias||0)+'d</td>'
      +'<td style="color:#EF9F27;font-size:13px">'+stars(r.calificacion)+'</td>'
      +'<td>'+sb(r.estado)+'</td>'
      +'<td style="font-size:11px;color:var(--color-text-secondary)">'+(hasMats?r.mat_vinculados.length+' artículo'+(r.mat_vinculados.length!==1?'s':''):'Sin artículos')+'</td>';
    tr.onclick=function(){ selProv(r.id); };
    tr.querySelector('input[type=radio]').onclick=function(e){ e.stopPropagation(); selProv(r.id); };
    // Expand button
    const bExp=tr.querySelector('td:first-child button');
    bExp.onclick=function(e){ e.stopPropagation(); selProv(r.id); toggleProvMats(r.id, r); };
    tbody.appendChild(tr);
    // Hidden detail row
    const trDet=document.createElement('tr');
    trDet.id='provmats-'+r.id; trDet.style.display='none';
    const tdDet=document.createElement('td'); tdDet.colSpan=8; tdDet.style.padding='0';
    const div=document.createElement('div');
    div.id='provmats-body-'+r.id;
    div.style.cssText='padding:8px 12px 10px 32px;background:var(--color-background-secondary);font-size:11px';
    div.innerHTML='<div class="ld">Cargando...</div>';
    tdDet.appendChild(div); trDet.appendChild(tdDet); tbody.appendChild(trDet);
  });
  tbl.appendChild(tbody);
  el.innerHTML=''; el.appendChild(tbl);
  actualizarToolbarProv();
}

async function openLM(pid){
  $('lm-pid').value=pid;
  $('lm-mat').value='';
  $('lm-mat-search').value='';
  $('lm-pre').value='';
  $('lm-pla').value='3';
  $('lm-pri').value='1';
  // Always refresh materials from API
  _mat=await api('/api/materiales');
  if(!_mat.length){
    toast('No hay materiales en inventario. Cargá materiales primero.','w');
  }
  openMo('mo-prov-mat');
  setTimeout(function(){$('lm-mat-search').focus();},80);
}

function filtrarLMMat(){
  const q=($('lm-mat-search').value||'').toLowerCase().trim();
  const cont=$('lm-mat-results');
  const lista = q ? _mat.filter(function(m){
    const full=((m.codigo||'')+' '+(m.descripcion||'')).toLowerCase();
    return full.includes(q);
  }) : _mat;
  _novotResultsRender(cont,lista,function(m){return m.codigo+' — '+m.descripcion+(m.unidad?' ('+m.unidad+')':'');},function(m){
    $('lm-mat').value=m.id;
    $('lm-mat-search').value=m.codigo+' — '+m.descripcion;
    cont.style.display='none';cont.innerHTML='';
  });
}

async function saveLM(){
  const pid=$('lm-pid').value;
  const body={material_id:$('lm-mat').value,precio_unit:$('lm-pre').value||0,plazo_dias:$('lm-pla').value||3,es_principal:$('lm-pri').value==='1'};
  if(!body.material_id){toast('Seleccioná un material','w');return;}
  const res=await api('/api/proveedores/'+pid+'/materiales',{method:'POST',body:JSON.stringify(body)});
  if(res.ok){toast('Material vinculado');closeMo('mo-prov-mat');_prov=[];loadProv();}
  else toast(res.error||'Error','e');
}

async function openHistorialCompra(pid, razonSocial){
  $('hist-prov-titulo').textContent='Historial de compra — '+razonSocial;
  const body=$('hist-compra-body');
  body.innerHTML='<div class="ld">Cargando...</div>';
  openMo('mo-historial-compra');
  
  try {
    const ocs=await api('/api/ordenes_compra/proveedor/'+pid);
    if(!ocs || ocs.length===0){
      body.innerHTML='<div class="em">No hay órdenes de compra para este proveedor.</div>';
      return;
    }
    
    let html='<div style="padding:4px 0">';
    ocs.forEach(function(oc){
      const fechaEmision=new Date(oc.fecha_emision).toLocaleDateString('es-AR');
      const total=oc.total||0;
      const estado=oc.estado||'—';
      
      html+='<div class="opc">';
      html+='<div class="oph"><div>';
      html+='<div class="opn">OC #'+oc.numero+' — <span style="color:var(--color-text-secondary);font-weight:400">'+fechaEmision+'</span></div>';
      html+='<div class="opm" style="margin-top:4px">'+monOnly('<strong style="color:var(--color-text-primary)">Total: '+fmtM(total)+'</strong> • ')+'Estado: '+sb(estado)+'</div>';
      html+='</div></div>';
      
      if(oc.items && oc.items.length>0){
        html+='<div style="margin-top:8px;padding-top:8px;border-top:1px solid var(--color-border-tertiary);font-size:11px">';
        html+='<div style="color:var(--color-text-secondary);font-weight:500;margin-bottom:4px">Materiales:</div>';
        oc.items.forEach(function(item){
          const qtotal=item.cantidad||0;
          const precio=item.precio_unitario||0;
          const monto=qtotal*precio;
          html+='<div style="display:flex;justify-content:space-between;padding:3px 0;color:var(--color-text-secondary)">';
          html+='<span>'+item.mat_codigo+' — '+item.mat_desc+'</span>';
          html+='<span>'+qtotal+' × '+fmtM(precio)+' = '+fmtM(monto)+'</span>';
          html+='</div>';
        });
        html+='</div>';
      }
      
      html+='</div>';
    });
    html+='</div>';
    body.innerHTML=html;
  } catch(e){
    body.innerHTML='<div class="al al-e"><strong>Error</strong> al cargar el historial de compra</div>';
    console.error(e);
  }
}

function nuevoProv(){
  $('prov-id').value='';
  $('prov-mh-title').textContent='Proveedor';
  $('prov-raz').value=''; $('prov-cui').value=''; $('prov-mat').value='';
  $('prov-con').value=''; $('prov-tel').value=''; $('prov-ema').value='';
  $('prov-pla').value='3'; $('prov-cal').value='5'; $('prov-est').value='Activo';
  $('prov-catc').value=''; $('prov-obs').value='';
  openMo('mo-prov');
}

function editProv(r){
  $('prov-id').value=r.id;
  $('prov-mh-title').textContent='Editar proveedor';
  $('prov-raz').value=r.razon||''; $('prov-cui').value=r.cuit||''; $('prov-mat').value=r.materiales||'';
  $('prov-con').value=r.contacto||''; $('prov-tel').value=r.telefono||''; $('prov-ema').value=r.email||'';
  $('prov-pla').value=r.plazo_dias||3; $('prov-cal').value=r.calificacion||5; $('prov-est').value=r.estado||'Activo';
  $('prov-catc').value=r.categoria_compra||''; $('prov-obs').value=r.obs||'';
  openMo('mo-prov');
}

async function saveProv(){
  const id=$('prov-id').value;
  const body={razon:$('prov-raz').value,cuit:$('prov-cui').value,contacto:$('prov-con').value,
    telefono:$('prov-tel').value,email:$('prov-ema').value,materiales:$('prov-mat').value,
    plazo_dias:$('prov-pla').value||3,calificacion:$('prov-cal').value||5,estado:$('prov-est').value,
    categoria_compra:$('prov-catc').value,obs:$('prov-obs').value};
  if(!body.razon){toast('Razón social requerida','w');return;}
  const res=id?await api('/api/proveedores/'+id,{method:'PUT',body:JSON.stringify(body)})
             :await api('/api/proveedores',{method:'POST',body:JSON.stringify(body)});
  if(res.ok){toast(id?'Proveedor actualizado':'Proveedor agregado');closeMo('mo-prov');_prov=[];loadProv();}
  else toast(res.error||'Error','e');
}


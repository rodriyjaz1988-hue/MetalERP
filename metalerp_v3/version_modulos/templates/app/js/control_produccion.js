// ── Control de producción ─────────────────────────────────────────────────────
let _ctrlOps=[],_ctrlOid=null,_ctrlOtData=null,_ctrlPollId=null,_ctrlActivas=[];
// Ruta elegida por OT cuando un paso tiene procesos alternativos (mismo
// número de orden): { [ordenId]: { [numeroDeOrden]: opIdElegido } }
let _ctrlAltSel={};

function onCtrlAltChange(oid,ordenKey,sel){
  if(!_ctrlAltSel[oid]) _ctrlAltSel[oid]={};
  _ctrlAltSel[oid][ordenKey]=sel.value;
  loadCtrlOps(oid);
}

function startCtrlPoll(){
  stopCtrlPoll();
  _ctrlPollId=setInterval(function(){
    const page=$('p-ctrl_prod');
    if(!page||!page.classList.contains('active')||!_ctrlOid) return;
    // No interrumpir si el usuario está interactuando con un select/input de la tabla
    const ae=document.activeElement;
    const ops=$('ctrl-ops');
    if(ae&&ops&&ops.contains(ae)) return;
    loadCtrlOps(_ctrlOid);
  },5000);
}
function stopCtrlPoll(){
  if(_ctrlPollId){clearInterval(_ctrlPollId);_ctrlPollId=null;}
}

function _ctrlSelectOT(oid){
  document.querySelectorAll('#ctrl-ot-list .ctrl-ot-row').forEach(function(d){
    d.classList.toggle('selected', d.getAttribute('data-ot')===String(oid));
  });
}

function _ctrlRenderHeader(){
  const d=_ctrlOtData;
  const header=$('ctrl-ot-header');
  if(!d){
    header.innerHTML='<span style="color:#888">Seleccioná una OT →</span>';
    actualizarToolbarCtrl();
    return;
  }
  // Use DOM nodes to avoid any CSS variable issues
  header.innerHTML='';
  // Badge with OT number
  const badge=document.createElement('span');
  badge.textContent=d.numero;
  badge.style.cssText='display:inline-block;font-size:15px;font-weight:700;background:#2C5F8A;color:#fff;border-radius:6px;padding:3px 12px;margin-right:10px;vertical-align:middle';
  header.appendChild(badge);
  // Description
  const desc=document.createElement('span');
  desc.textContent=(d.producto_codigo?(d.producto_codigo+' -- '+(d.producto_nombre||'—')):(d.producto_nombre||d.descripcion||'—'));
  desc.style.cssText='font-size:13px;font-weight:600;color:#333;vertical-align:middle;margin-right:8px';
  header.appendChild(desc);
  // Quantity
  const qty=document.createElement('span');
  qty.textContent='× '+d.cantidad;
  qty.style.cssText='font-size:11px;color:#888;vertical-align:middle;margin-right:8px';
  header.appendChild(qty);
  // Estado badge
  const estDiv=document.createElement('span');
  estDiv.innerHTML=sb(d.estado);
  header.appendChild(estDiv);
}

// ── Botón "Actualizar" de Control de producción ────────────────────────────
// Recarga la lista de OTs activas y, si hay una OT seleccionada, también sus
// operaciones — útil para ver reflejado de inmediato el efecto de una
// novedad recién declarada (qty_producida, % de avance, estado, etc.).
async function refreshCtrlProd(){
  await loadCtrlProd();
  if(_ctrlOid) await loadCtrlOps(_ctrlOid);
}

async function loadCtrlProd(){
  const rows=await api('/api/ordenes');
  _ctrlActivas=rows.filter(function(r){return r.estado==='En proceso'||r.estado==='Pendiente';});
  _renderCtrlOtList();
}

// Filtra la lista de OTs activas por producto (código o nombre) a partir del
// buscador ubicado junto al título "OTs activas".
function filtrarCtrlOts(){
  _renderCtrlOtList();
}

function _renderCtrlOtList(){
  const q=($('ctrl-ot-search')?$('ctrl-ot-search').value:'').toLowerCase().trim();
  let activas=_ctrlEstF?_ctrlActivas.filter(function(r){return r.estado===_ctrlEstF;}):_ctrlActivas;
  if(q) activas=activas.filter(function(r){
    const full=((r.numero||'')+' '+(r.producto_codigo||'')+' '+(r.producto_nombre||'')+' '+(r.descripcion||'')).toLowerCase();
    return full.includes(q);
  });
  const filtrando=!!(q||_ctrlEstF);
  const list=$('ctrl-ot-list');
  if(!activas.length){
    list.innerHTML='<div class="em" style="padding:12px">'+(q?'Sin resultados para "'+q+'".':'Sin OTs activas.')+'</div>';
    // La OT que estaba seleccionada (si había) ya no está activa: limpiar
    // la selección y el panel de la derecha para que no quede mostrando
    // datos viejos (p.ej. una OT ya completada).
    if(_ctrlOid && !filtrando){
      _ctrlOid=null;_ctrlOtData=null;_ctrlOps=[];_ctrlOpSel=null;
      _ctrlRenderHeader();
      $('ctrl-ops').innerHTML='<div class="em">Seleccioná una OT.</div>';
    }
    actualizarToolbarCtrl();
    return;
  }
  list.innerHTML='';
  activas.forEach(function(r){
    const div=document.createElement('div');
    div.className='ctrl-ot-row';
    div.setAttribute('data-ot', r.id);
    div.style.cssText='padding:10px 14px;cursor:pointer;border-bottom:1px solid var(--color-border-tertiary);border-left:4px solid transparent;font-size:12px;box-sizing:border-box';
    div.innerHTML=
      '<div class="ctrl-ot-num" style="font-weight:600;color:var(--color-text-primary)">'+r.numero+'</div>'
      +'<div class="ctrl-ot-sub" style="color:var(--color-text-secondary);margin-top:2px">'+(r.producto_codigo?(r.producto_codigo+' -- '+(r.producto_nombre||'—')):(r.producto_nombre||r.descripcion||'—'))+'</div>'
      +'<div style="margin-top:3px">'+sb(r.estado)+' <span class="ctrl-ot-sub" style="color:var(--color-text-secondary);font-size:11px">× '+fN(r.cantidad)+'</span></div>';
    div.onclick=function(){
      if(String(_ctrlOid)!==String(r.id)) _ctrlOpSel=null;
      _ctrlOid=r.id;
      _ctrlOtData=r;
      _ctrlSelectOT(r.id);
      _ctrlRenderHeader();
      loadCtrlOps(r.id);
    };
    list.appendChild(div);
  });
  // After re-render: restore selection and refresh _ctrlOtData from fresh API data
  if(_ctrlOid){
    var fresh=activas.find(function(r){return r.id===_ctrlOid||r.id===parseInt(_ctrlOid);});
    if(fresh){
      _ctrlOtData=fresh;   // update with latest data (estado, etc.)
      _ctrlSelectOT(_ctrlOid);
      _ctrlRenderHeader();
    } else if(!filtrando){
      // La OT seleccionada ya no está activa (se completó/canceló): limpiar selección y tabla
      _ctrlOid=null;_ctrlOtData=null;_ctrlOps=[];_ctrlOpSel=null;
      _ctrlRenderHeader();
      $('ctrl-ops').innerHTML='<div class="em">Seleccioná una OT.</div>';
    }
  }
  actualizarToolbarCtrl();
  startCtrlPoll();
}

async function loadCtrlOps(oid){
  if(oid!=null&&oid!==undefined) _ctrlOid=oid;
  oid=_ctrlOid;
  if(!oid){$('ctrl-ops').innerHTML='<div class="em">Seleccioná una OT.</div>';_ctrlOpSel=null;actualizarToolbarCtrl();return;}
  // Header is rendered by _ctrlRenderHeader, not here — just keep it alive
  _ctrlRenderHeader();
  _ctrlOps=await api('/api/ordenes/'+oid+'/operaciones');
  if(!_ctrlOps.length){
    const popRes=await api('/api/ordenes/'+oid+'/operaciones/populate',{method:'POST',body:JSON.stringify({})});
    if(popRes.error){
      $('ctrl-ops').innerHTML='<div class="em">'+popRes.error+'</div>';return;
    }
    if(popRes.ops_created>0) _ctrlOps=await api('/api/ordenes/'+oid+'/operaciones');
  }
  if(!_ctrlOps.length){
    $('ctrl-ops').innerHTML='<div class="em">Esta OT no tiene operaciones. Definí el proceso en Procesos/Productos.</div>';return;
  }
  // Agrupar por número de "orden": si un paso tiene rutas alternativas
  // (2+ operaciones con el mismo orden — p.ej. dos máquinas/procesos
  // posibles para el mismo paso), se muestran como un solo renglón con un
  // select para elegir qué ruta se va a usar. El tiempo de ciclo (y por lo
  // tanto el rendimiento calculado al declarar la novedad) depende de cuál
  // se elija.
  // Las operaciones tercerizadas no se gestionan desde Control de producción
  // (se siguen desde Órdenes de Trabajo de Terceros / OTT), así que se
  // excluyen de esta vista.
  const gruposOrden={};
  _ctrlOps.filter(function(op){return !op.es_tercerizada;}).forEach(function(op){
    const k=String(op.orden);
    if(!gruposOrden[k]) gruposOrden[k]=[];
    gruposOrden[k].push(op);
  });
  if(!Object.keys(gruposOrden).length){
    $('ctrl-ops').innerHTML='<div class="em">Esta OT solo tiene operaciones tercerizadas (ver Órdenes de Trabajo de Terceros).</div>';return;
  }
  if(!_ctrlAltSel[oid]) _ctrlAltSel[oid]={};
  const altSel=_ctrlAltSel[oid];
  Object.keys(gruposOrden).forEach(function(k){
    const grupo=gruposOrden[k];
    if(altSel[k]&&grupo.some(function(o){return String(o.id)===String(altSel[k]);})) return;
    // Por defecto: si alguna alternativa ya tiene trabajo declarado
    // (estado distinto de Pendiente o producción cargada), esa es la
    // elegida; si no, la primera de la lista.
    const enUso=grupo.find(function(o){return o.estado!=='Pendiente'||o.qty_producida>0;});
    altSel[k]=(enUso||grupo[0]).id;
  });
  _ctrlOpRows=new Map();
  let h='<table><tr><th style="width:24px"></th><th>Ord.</th><th>Operación</th><th>Sector / Proveedor</th><th>Req.</th><th>Producido (OK)</th><th>%</th><th>Estado</th></tr>';
  Object.keys(gruposOrden).sort(function(a,b){return parseInt(a)-parseInt(b);}).forEach(function(k){
    const grupo=gruposOrden[k];
    const esAlternativa=grupo.length>1;
    const op=grupo.find(function(o){return String(o.id)===String(altSel[k]);})||grupo[0];
    // Si se trabajó en más de una alternativa del mismo paso (mismo "orden"),
    // el producido de ese paso es la suma de lo producido en cada una, no
    // solo lo de la alternativa seleccionada en el select.
    const alternativasConProduccion=grupo.filter(function(o){return (o.qty_producida||0)>0;});
    const producidoTotal=alternativasConProduccion.length>1
      ? alternativasConProduccion.reduce(function(s,o){return s+(o.qty_producida||0);},0)
      : op.qty_producida;
    const pct=op.qty_requerida>0?Math.round(producidoTotal/op.qty_requerida*100):0;
    const pctCol=pct>=100?'bg':pct>=50?'ba':'br';
    const sector=op.es_tercerizada
      ?('<span class="b br" style="font-size:10px">TERC</span> '+(op.proveedor_nombre||'—'))
      :(op.cat_maquina_nombre||'—');
    _ctrlOpRows.set(op.id,op);
    const selOp=_ctrlOpSel===op.id;
    const estadoColores={'Pendiente':{bg:'#FAEEDA',fg:'#633806'},'En proceso':{bg:'#E6F1FB',fg:'#0C447C'},'Completada':{bg:'#EAF3DE',fg:'#27500A'}};
    const estadoCol=(['admin','operario'].includes(ROL)&&!(op.estado==='Completada'&&op.depende_terc_previa))
      ?'<select data-estado-actual="'+op.estado+'" onchange="cambiarEstadoOp('+op.id+','+oid+',this)" style="font-family:inherit;font-size:11px;font-weight:500;padding:3px 9px;border-radius:7px;border:1px solid transparent;background:'+(estadoColores[op.estado]?estadoColores[op.estado].bg:'#fff')+';color:'+(estadoColores[op.estado]?estadoColores[op.estado].fg:'#1a1a1a')+';cursor:pointer">'
        +['Pendiente','En proceso','Completada'].map(function(e){return '<option value="'+e+'" style="background:#fff"'+(op.estado===e?' selected':'')+'>'+e+'</option>';}).join('')
        +'</select>'
      :sb(op.estado);
    const nombreCol=esAlternativa
      ?('<select onchange="onCtrlAltChange(\''+oid+'\',\''+k+'\',this)" style="font-family:inherit;font-size:12px;padding:3px 6px;border-radius:5px;border:1px solid var(--color-border-tertiary)">'
        +grupo.map(function(o){return '<option value="'+o.id+'"'+(String(o.id)===String(op.id)?' selected':'')+'>'+o.nombre+' (ciclo: '+o.tiempo_ciclo_seg+' seg)</option>';}).join('')
        +'</select>')
      :op.nombre;
    const warnTerc=op.depende_terc_previa
      ?'<span title="Esta operación sigue a una operación tercerizada: una vez marcada Completada no se puede deshacer" style="display:inline-flex;align-items:center;justify-content:center;width:16px;height:16px;margin-left:6px;border-radius:50%;background:#F5C518;color:#4a3800;font-size:11px;font-weight:800;line-height:1;vertical-align:middle;cursor:help">!</span>'
      :'';

    h+='<tr data-ctrlop="'+op.id+'" class="'+(selOp?'ot-sel':'')+'" style="cursor:pointer" title="Doble clic: declarar novedad" onclick="selCtrlOp('+op.id+')" ondblclick="if(event.target.tagName!==\'SELECT\'){selCtrlOp('+op.id+');ctrlSelAccion(\'nov\');}">'
      +'<td><input type="radio" name="ctrl-op-sel" '+(selOp?'checked':'')+' onclick="event.stopPropagation();selCtrlOp('+op.id+')"></td>'
      +'<td>'+op.orden+'</td>'
      +'<td>'+nombreCol+warnTerc+'</td>'
      +'<td>'+sector+'</td>'
      +'<td>'+fN(op.qty_requerida)+'</td>'
      +'<td>'+producidoTotal+(alternativasConProduccion.length>1?' <span style="font-size:10px;color:var(--color-text-secondary)">('+alternativasConProduccion.map(function(o){return o.nombre+': '+o.qty_producida;}).join(' + ')+')</span>':'')+'</td>'
      +'<td><span class="b '+pctCol+'">'+pct+'%</span></td>'
      +'<td>'+estadoCol+'</td>'
      +'</tr>';
  });
  if(_ctrlOpSel && !_ctrlOpRows.has(_ctrlOpSel)) _ctrlOpSel=null;
  $('ctrl-ops').innerHTML=h+'</table>';
  actualizarToolbarCtrl();
}

// Selección de operación + barra de herramientas (mismo patrón que OT /
// Procesos): clic en la fila selecciona, doble clic declara la novedad.
let _ctrlOpSel=null, _ctrlOpRows=new Map(), _ctrlEstF='';
function selCtrlOp(id){
  _ctrlOpSel=id;
  document.querySelectorAll('#ctrl-ops tr[data-ctrlop]').forEach(function(tr){
    const s=Number(tr.dataset.ctrlop)===id;
    tr.classList.toggle('ot-sel',s);
    const rb=tr.querySelector('input[name=ctrl-op-sel]'); if(rb) rb.checked=s;
  });
  actualizarToolbarCtrl();
}
function actualizarToolbarCtrl(){
  const op=_ctrlOpSel?_ctrlOpRows.get(_ctrlOpSel):null;
  const lbl=$('ctrl-sel-label');
  if(lbl){
    const t=_ctrlOtData?(_ctrlOtData.numero+(op?' · '+op.nombre:'')):'–';
    lbl.textContent=t.length>34?t.slice(0,33)+'…':t;
    lbl.title=_ctrlOtData?t:'OT / operación seleccionada';
  }
  const b=$('ctrl-b-nov');
  if(b){
    b.style.display=['admin','operario'].includes(ROL)?'':'none';
    b.disabled=!(op&&op.estado!=='Completada');
    b.title=op&&op.estado==='Completada'?'La operación seleccionada ya está completada':'Declarar una novedad en la operación seleccionada';
  }
}
function ctrlSelAccion(a){
  const op=_ctrlOpSel?_ctrlOpRows.get(_ctrlOpSel):null;
  if(!op){toast('Seleccioná una operación de la lista','w');return;}
  if(a==='nov'){
    if(!['admin','operario'].includes(ROL)) return;
    if(op.estado==='Completada'){toast('La operación ya está completada','w');return;}
    openNovOp(op.id,_ctrlOid);
  }
}
function clearFiltrosCtrl(){
  if($('ctrl-ot-search'))$('ctrl-ot-search').value='';
  _ctrlEstF='';
  document.querySelectorAll('#ctrl-tabs .tab').forEach(x=>x.classList.toggle('active',x.dataset.e===''));
  _renderCtrlOtList();
}
document.querySelectorAll('#ctrl-tabs .tab').forEach(t=>t.addEventListener('click',()=>{
  document.querySelectorAll('#ctrl-tabs .tab').forEach(x=>x.classList.remove('active'));
  t.classList.add('active');
  _ctrlEstF=t.dataset.e||'';
  _renderCtrlOtList();
}));

async function cambiarEstadoOp(opid,oid,sel){
  const nuevoEstado=sel.value;
  const estadoAnterior=sel.dataset.estadoActual||nuevoEstado;
  const colores={'Pendiente':{bg:'#FAEEDA',fg:'#633806'},'En proceso':{bg:'#E6F1FB',fg:'#0C447C'},'Completada':{bg:'#EAF3DE',fg:'#27500A'}};
  const res=await api('/api/ordenes/'+oid+'/operaciones/'+opid,{method:'PUT',body:JSON.stringify({estado:nuevoEstado})});
  if(res.ok){
    sel.style.background=colores[nuevoEstado]?colores[nuevoEstado].bg:'#fff';
    sel.style.color=colores[nuevoEstado]?colores[nuevoEstado].fg:'#1a1a1a';
    sel.dataset.estadoActual=nuevoEstado;
    toast('Estado actualizado');loadCtrlOps(oid);
  } else {
    sel.value=estadoAnterior; // revertir visualmente, el backend rechazó el cambio
    toast(res.error||'Error','e');
  }
}

// ── Lotes obligatorios por material/PT requerido en la operación ─────────────
// Los insumos (categoria='Insumo') no llevan trazabilidad por lote: se
// descuentan directo del stock general al completar la OT (ver backend),
// así que acá no se les pide elegir lote, solo se informan.
let _novMatsReq=[];
async function loadNovLotes(opId){
  const wrap=$('nov-lotes-wrap'), list=$('nov-lotes-list');
  if(!opId){wrap.style.display='none';list.innerHTML='';_novMatsReq=[];return;}
  _novMatsReq=await api('/api/orden_operaciones/'+opId+'/materiales_requeridos');
  if(!Array.isArray(_novMatsReq)||!_novMatsReq.length){wrap.style.display='none';list.innerHTML='';_novMatsReq=[];return;}
  wrap.style.display='';
  // La vinculación de lote se hace desde Órdenes de trabajo → "Lotes
  // asignados" (botón "Asignar lote"). Acá solo se informa el estado: si el
  // material ya tiene lote vinculado se muestra cuál; si no, se avisa que
  // hay que ir a asignarlo antes de poder declarar la novedad.
  list.innerHTML=_novMatsReq.map(function(m){
    if(m.requiere_lote===false){
      // Insumo: no se elige lote, solo se informa que se descontará al completar la OT
      return '<div style="display:flex;align-items:center;gap:8px">'
        +'<span style="min-width:160px;font-size:12px">'+m.codigo+' — '+m.descripcion+'</span>'
        +'<span style="flex:1;font-size:12px;color:var(--color-text-tertiary)">'+(m.categoria==='Herramienta'?'Herramienta':'Insumo')+' — se descuenta del stock general al completar la OT (sin lote)</span>'
        +'</div>';
    }
    if(m.lote_vinculado){
      return '<div style="display:flex;align-items:center;gap:8px">'
        +'<span style="min-width:160px;font-size:12px">'+m.codigo+' — '+m.descripcion+'</span>'
        +'<span class="b bg" style="font-size:11px">Lote '+m.lote_vinculado.numero+' vinculado</span>'
        +'</div>';
    }
    return '<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">'
      +'<span style="min-width:160px;font-size:12px">'+m.codigo+' — '+m.descripcion+'</span>'
      +'<span class="b br" style="font-size:11px">Sin lote vinculado</span>'
      +'<span style="font-size:11px;color:var(--color-text-secondary)">Asignalo desde Órdenes de trabajo → Lotes asignados</span>'
      +'</div>';
  }).join('');
}
function getNovLotesSeleccionados(){
  // Ya no se elige lote acá: solo se valida que cada material que lo
  // requiera tenga un lote vinculado de antemano (asignado desde Órdenes
  // de trabajo). No se envía ningún lote nuevo al backend.
  const faltantes=[];
  (_novMatsReq||[]).forEach(function(m){
    if(m.requiere_lote!==false && !m.lote_vinculado){
      faltantes.push(m.codigo+' — '+m.descripcion);
    }
  });
  return {lotes:{}, faltantes};
}

// ── Buscador de empleado en modal de novedad (compartido por las 3 vías de apertura) ──
function nombreEmpleadoNov(id){
  const e=_emp.find(function(x){return String(x.id)===String(id);});
  return e ? (e.apellido+', '+e.nombre) : '';
}
function setNovEmpleado(id){
  $('nov-emp').value = id||'';
  $('nov-emp-search').value = id ? nombreEmpleadoNov(id) : '';
  const cont=$('nov-emp-results');
  if(cont){cont.style.display='none';cont.innerHTML='';}
}
function filtrarNovEmpleados(){
  const q=($('nov-emp-search').value||'').toLowerCase().trim();
  $('nov-emp').value=''; // hasta que se reseleccione, no hay empleado confirmado
  const cont=$('nov-emp-results');
  if(!q){cont.style.display='none';cont.innerHTML='';return;}
  const lista=_emp.filter(function(e){
    if(e.tipo!=='Directo'||!e.activo)return false;
    const full1=(e.nombre+' '+e.apellido).toLowerCase();
    const full2=(e.apellido+' '+e.nombre).toLowerCase();
    return full1.includes(q)||full2.includes(q);
  });
  if(!lista.length){
    cont.innerHTML='<div style="padding:8px 10px;font-size:12px;color:#999">Sin resultados</div>';
    cont.style.display='block';
    return;
  }
  cont.innerHTML='';
  lista.slice(0,30).forEach(function(e){
    const item=document.createElement('div');
    item.textContent=e.apellido+', '+e.nombre;
    item.style.cssText='padding:7px 10px;font-size:13px;cursor:pointer';
    item.onmouseenter=function(){this.style.background='#f4f4f2';};
    item.onmouseleave=function(){this.style.background='';};
    item.onmousedown=function(ev){
      ev.preventDefault();
      $('nov-emp').value=e.id;
      $('nov-emp-search').value=e.apellido+', '+e.nombre;
      cont.style.display='none';
      cont.innerHTML='';
    };
    cont.appendChild(item);
  });
  cont.style.display='block';
}

// ── Buscador de máquina en modal de novedad (compartido por las 3 vías de apertura) ──
function nombreMaquinaNov(id){
  const m=_maq.find(function(x){return String(x.id)===String(id);});
  return m ? (m.codigo+' — '+m.nombre) : '';
}
function setNovMaquina(id){
  $('nov-maq').value = id||'';
  $('nov-maq-search').value = id ? nombreMaquinaNov(id) : '';
  const cont=$('nov-maq-results');
  if(cont){cont.style.display='none';cont.innerHTML='';}
}
function filtrarNovMaquinas(){
  const q=($('nov-maq-search').value||'').toLowerCase().trim();
  $('nov-maq').value=''; // hasta que se reseleccione, no hay máquina confirmada
  const cont=$('nov-maq-results');
  if(!q){cont.style.display='none';cont.innerHTML='';return;}
  const lista=_maq.filter(function(m){
    const full=((m.codigo||'')+' '+(m.nombre||'')).toLowerCase();
    return full.includes(q);
  });
  if(!lista.length){
    cont.innerHTML='<div style="padding:8px 10px;font-size:12px;color:#999">Sin resultados</div>';
    cont.style.display='block';
    return;
  }
  cont.innerHTML='';
  lista.slice(0,30).forEach(function(m){
    const item=document.createElement('div');
    item.textContent=m.codigo+' — '+m.nombre;
    item.style.cssText='padding:7px 10px;font-size:13px;cursor:pointer';
    item.onmouseenter=function(){this.style.background='#f4f4f2';};
    item.onmouseleave=function(){this.style.background='';};
    item.onmousedown=function(ev){
      ev.preventDefault();
      $('nov-maq').value=m.id;
      $('nov-maq-search').value=m.codigo+' — '+m.nombre;
      cont.style.display='none';
      cont.innerHTML='';
    };
    cont.appendChild(item);
  });
  cont.style.display='block';
}

function checkNovCiclo(op){
  const warn=$('nov-cic-warn');
  if(!warn) return;
  const sinCiclo = op && (!op.tiempo_ciclo_seg || op.tiempo_ciclo_seg<=0);
  warn.style.display = sinCiclo ? 'block' : 'none';
}

// ── Cajones en el modal de novedad ──────────────────────────────────────────
// En el primer paso de la OT las piezas OK llenan el cajón abierto solas; en
// los siguientes se indica cuánto se hizo en cada cajón (hasta lo que el paso
// anterior dejó en él).
let _novCaj=null, _novCajTocado=false;
async function loadNovCajones(oid, opId, propiasLista){
  const wrap=$('nov-caj-wrap'), body=$('nov-caj-body');
  _novCaj=null; _novCajTocado=!!(propiasLista&&propiasLista.length);
  if(!wrap) return;
  wrap.style.display='none'; body.innerHTML='';
  if(!oid||!opId) return;
  const r=await api('/api/ordenes/'+oid+'/cajones?orden_operacion_id='+opId);
  if(!r||r.error||!r.usa_cajones) return;
  _novCaj=r; wrap.style.display='';
  const nota='font-size:12px;color:var(--color-text-secondary)';
  if(r.primer_paso){
    const ab=r.abierto;
    body.innerHTML='<div style="'+nota+'">'+(ab
      ? 'Las piezas OK van al cajón <b>'+schEsc(ab.numero)+'</b> ('+fN(ab.cantidad)+' de '+ab.capacidad+'); si no entran se abre otro.'
      : 'Las piezas OK abren un cajón nuevo de '+(r.capacidad||'—')+' piezas.')+'</div>';
    return;
  }
  const propias={};
  (propiasLista||[]).forEach(function(c){propias[c.cajon_id]=c.cantidad;});
  const lista=r.cajones.filter(function(c){return (c.disponible||0)>0||propias[c.id];});
  if(!lista.length){
    body.innerHTML='<div style="'+nota+'">Ningún cajón tiene piezas disponibles para esta operación (el paso anterior todavía no cargó nada).</div>';
    return;
  }
  body.innerHTML='<table><tr><th>Cajón</th><th>Disponible</th><th>Cantidad</th></tr>'+lista.map(function(c){
    const disp=(c.disponible||0)+(propias[c.id]||0);
    return '<tr><td><b>'+schEsc(c.numero)+'</b></td><td>'+fN(disp)+'</td><td><input type="number" class="nov-caj-q" data-id="'+c.id+'" data-disp="'+disp
      +'" min="0" max="'+disp+'" step="1" value="'+(propias[c.id]||'')+'" oninput="_novCajTocado=true;novCajSuma()" style="width:90px"></td></tr>';
  }).join('')+'</table><div id="nov-caj-suma" style="'+nota+';margin-top:4px">La suma tiene que ser igual a la cantidad OK.</div>';
  autoNovCajones();
}
// Mientras no se toque a mano, reparte la cantidad OK en orden entre los cajones.
function autoNovCajones(){
  if(!_novCaj||_novCaj.primer_paso||_novCajTocado) return;
  let resto=parseFloat($('nov-qty').value)||0;
  document.querySelectorAll('#nov-caj-body .nov-caj-q').forEach(function(i){
    const t=Math.min(resto, parseFloat(i.dataset.disp)||0);
    i.value=t>0?t:''; resto-=t;
  });
  novCajSuma();
}
// Muestra cuánto se repartió entre cajones contra la cantidad OK
function novCajSuma(){
  const el=$('nov-caj-suma'); if(!el) return;
  let suma=0;
  document.querySelectorAll('#nov-caj-body .nov-caj-q').forEach(function(i){suma+=parseFloat(i.value)||0;});
  const ok=parseFloat($('nov-qty').value)||0;
  const bien=Math.abs(suma-ok)<0.001;
  el.innerHTML='Repartido en cajones: <b style="color:'+(bien?'#2e7d32':'#c62828')+'">'+suma+' de '+ok+'</b>'
    +(bien?'':' — la suma tiene que ser igual a la cantidad OK');
}
function getNovCajones(){
  if(!_novCaj||!_novCaj.usa_cajones||_novCaj.primer_paso) return null;
  const out=[];
  document.querySelectorAll('#nov-caj-body .nov-caj-q').forEach(function(i){
    const v=parseFloat(i.value);
    if(v>0) out.push({cajon_id:parseInt(i.dataset.id),cantidad:v});
  });
  return out;
}

async function openNovOp(opId, ordId){
  // Pre-fill novedad modal with op/ot data
  $('nov-oid').value=ordId;
  const op=_ctrlOps.find(function(o){return o.id==opId;});
  const s=$('nov-op');
  s.innerHTML='';
  if(op){
    const o=document.createElement('option');o.value=op.id;
    o.textContent=op.orden+'. '+op.nombre+' (ciclo: '+op.tiempo_ciclo_seg+' seg)';
    s.appendChild(o);
  }
  // La operación ya viene determinada por la tarjeta seleccionada en Control
  // de producción: ocultamos el select (no hace falta elegir) y mostramos el
  // nombre como subtítulo del modal en su lugar.
  const wrap=$('nov-op-wrap');
  if(wrap) wrap.style.display='none';
  const titleEl=$('nov-op-title');
  if(titleEl) titleEl.textContent = op ? (' — '+op.nombre) : '';
  checkNovCiclo(op);
  if(!_emp.length)_emp=await api('/api/empleados');
  setNovEmpleado('');
  if(!_maq.length)_maq=await api('/api/maquinas');
  setNovMaquina((op&&op.maquina_id)?op.maquina_id:'');
  $('nov-fecha').value=new Date().toISOString().slice(0,10);
  $('nov-qty').value='';$('nov-tmin').value='';$('nov-obs-qty').value='';$('nov-tperd').value='';
  delete $('nov-oid').dataset.editId;
  $('nov-del-btn').style.display='none';
  await loadNovLotes(opId);
  await loadNovCajones(ordId, opId);
  openMo('mo-nov');
}

async function saveNov(){
  const tminH=parseFloat($('nov-tmin').value);
  const tperdH=parseFloat($('nov-tperd').value);
  const qtyOK=$('nov-qty').value;
  const pzNoOK=$('nov-obs-qty').value;
  const body={orden_id:$('nov-oid').value,orden_operacion_id:$('nov-op').value,
    empleado_id:$('nov-emp').value||null,maquina_id:$('nov-maq').value||null,cantidad_producida:qtyOK||0,
    piezas_observadas:pzNoOK||null,
    tiempo_real_min:Number.isFinite(tminH)?Math.round(tminH*60):'',tiempo_perdido:Number.isFinite(tperdH)?Math.round(tperdH*60):null,
    turno:$('nov-tur').value,
    fecha:$('nov-fecha').value,obs:$('nov-obs').value};
  // Cantidad OK es obligatoria salvo que se haya cargado Piezas NO OK (rechazo puro)
  const sinQtyOK=!qtyOK||parseFloat(qtyOK)<=0;
  const sinPzNoOK=!pzNoOK||parseFloat(pzNoOK)<=0;
  if(!body.orden_operacion_id||!body.tiempo_real_min){toast('Operación y tiempo requeridos','w');return;}
  if(sinQtyOK&&sinPzNoOK){toast('Cargue Cantidad producida (OK) o Piezas NO OK','w');return;}
  const cajNov=getNovCajones();
  if(cajNov&&!sinQtyOK){
    const suma=cajNov.reduce(function(s,c){return s+c.cantidad;},0);
    if(Math.abs(suma-parseFloat(qtyOK))>0.0001){toast('La suma por cajón ('+suma+') tiene que ser igual a la cantidad OK ('+parseFloat(qtyOK)+')','w');return;}
    body.cajones=cajNov;
  }
  if(_novMatsReq.length){
    const {lotes, faltantes}=getNovLotesSeleccionados();
    if(faltantes.length){toast('Asigná el lote desde Órdenes de trabajo antes de declarar la novedad — falta para: '+faltantes.join(', '),'w');return;}
    body.lotes=lotes;
  }
  // Deshabilitar botón para evitar doble envío
  const btnConfirmar=document.querySelector('#mo-nov .btn-p');
  if(btnConfirmar){btnConfirmar.disabled=true;btnConfirmar.textContent='Guardando...';}
  const editId = $('nov-oid').dataset&&$('nov-oid').dataset.editId;
  // Foto del estado actual ANTES de enviar, para poder confirmar despues si
  // la novedad se guardo igual aunque la conexion se haya cortado en el medio
  // (pasa sobre todo en la ultima operacion de la OT, que tarda mas porque
  // ademas descuenta materia prima y genera stock de producto terminado)
  let preCount=null;
  if(!editId){
    try{
      const previas=await api('/api/novedades?orden_id='+body.orden_id);
      preCount=Array.isArray(previas)?previas.length:null;
    }catch(_e){ /* si esto falla no es grave, seguimos sin la foto */ }
  }
  let res;
  try{
    if(editId){
      res=await api('/api/novedades/'+editId,{method:'PUT',body:JSON.stringify(body)});
      delete $('nov-oid').dataset.editId;
    } else {
      res=await api('/api/novedades',{method:'POST',body:JSON.stringify(body)});
    }
  }catch(e){
    // Antes de avisar "Error de conexión", chequeamos si la novedad se
    // guardó igual del lado del servidor (típico cuando la última
    // operación tarda más de la cuenta por el descuento de stock/PT)
    let yaGuardada=false;
    if(!editId && preCount!==null){
      try{
        const actuales=await api('/api/novedades?orden_id='+body.orden_id);
        if(Array.isArray(actuales)&&actuales.length>preCount) yaGuardada=true;
      }catch(_e2){ /* si ni esto responde, ahí sí es error de conexión real */ }
    }
    if(btnConfirmar){btnConfirmar.disabled=false;btnConfirmar.textContent='Confirmar novedad';}
    if(yaGuardada){
      toast('La novedad se guardó, pero la confirmación tardó más de lo normal','w');
      closeMo('mo-nov');
      loadCtrlProd();
    } else {
      toast('Error de conexión','e');
    }
    return;
  }
  // Restaurar botón antes de cerrar para que quede listo la próxima vez
  if(btnConfirmar){btnConfirmar.disabled=false;btnConfirmar.textContent='Confirmar novedad';}
  if(res&&res.ok){
    closeMo('mo-nov');
    clearNovModal(); // Limpiar el modal después de guardar exitosamente
    let msg=`Novedad ${res.numero} — Rendimiento: ${res.rendimiento_pct}%`;
    if(res.desvio)msg+=' ⚠ DESVÍO detectado';
    toast(msg,res.desvio?'w':'g');
    // Refrescar la(s) vista(s) que puedan estar mostrando esta novedad.
    // Antes solo se refrescaba Control de Producción: si el usuario venía
    // de "Novedades por OT" (ej. editando una novedad ahí) o de Rendimiento,
    // esas tablas quedaban desactualizadas hasta recargar toda la página.
    const activePage = document.querySelector('.page.active');
    const activeId = activePage ? activePage.id : '';
    loadCtrlProd();
    if(activeId==='p-novedades_ot' && typeof loadNovOT==='function') loadNovOT();
    if(activeId==='p-rendimiento' && typeof loadRendimiento==='function') loadRendimiento();
    // La novedad puede haber descontado cantidad_activa/cantidad_reservada
    // de un lote (consumo real de materia prima / semielaborado tercerizado).
    // Si el usuario tiene abierta la pantalla de Lotes, refrescarla también,
    // si no queda mostrando "Aprobado"/"Reservado" desactualizado hasta
    // recargar la página entera.
    if(activeId==='p-lotes' && typeof loadLotes==='function') loadLotes();
  } else {
    toast((res&&res.error)||'Error al guardar','e');
  }
}


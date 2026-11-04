// ── Trabajo no productivo ───────────────────────────────────────────────────
const CODIGOS_PARADA_MAQUINA={
  'CNC':['MANTENIMIENTO','PUESTA EN MARCHA','ALMUERZO - CENA','LIMPIEZA DEL SECTOR','LIMPIEZA INTERIOR',
    'CAMBIAR INSERTO','GIRAR INSERTO','CORREGIR MEDIDA','CAMBIAR BARRA','AGREGAR SOLUBLE','CAMBIO DE OPERADOR',
    'FALTA DE OPERADOR','PROBLEMAS CON ALIMENTADOR','CAMBIO DE PREPARACION','CORTE Y DESPUNTE DE BARRAS','BAÑO',
    'ROTURA DE HTAS','CAMBIO DE INSERTO EN OTRA MAQUINA','EXPLICACION / REUNION','FALTA DE PREPARACION',
    'MOVER PIEZAS','FALTA DE MATERIAL','ESPERAR AL ENCARGADO / PEDIR INSERTO','REPASAR PIEZAS','DESCARGAR MATERIAL'],
  'CORTADORAS':['MANTENIMIENTO','PUESTA EN MARCHA','ALMUERZO - CENA','LIMPIEZA DEL SECTOR','LIMPIEZA DE CORTADORA',
    'FALTA DE PREPARACION','MOVER PIEZAS','CORREGIR MEDIDA','CAMBIAR BARRAS','FALTA DE MATERIAL','CAMBIO DE OPERADOR',
    'FALTA DE OPERADOR','PROBLEMAS CON PISTONES','CAMBIO DE PREPARACION','ESPERAR AL ENCARGADO','BAÑO',
    'REPASAR PIEZAS','DESCARGAR MATERIAL','EXPLICACION / REUNION','CONTAR PIEZAS','PEDIR ELEMENTOS DE SEGURIDAD',
    'ENTREGAR PZ A CONTROL','CAMBIO DE SIERRA','EMITIR DOCUMENTACION','ARMADO DE PLANILLAS'],
  'CORTADORA LASER':['PRODUCCION','MANTENIMIENTO','PUESTA EN MARCHA','ALMUERZO - CENA','CREAR PROGRAMA',
    'MODIFICAR PROGRAMA','CAMBIO DE TUBO DE GAS','CAMBIO DE PREPARACION','CAMBIO DE MATERIAL','CORRECCION DE MEDIDAS',
    'ESPERAR AL ENCARGADO','BAÑO','PEDIR ELEMENTOS DE SEGURIDAD','ALARMA DE MAQUINA','EXPLICACION / REUNION',
    'LEVANTAR PIEZAS DE BATEA','CORTAR SOBRANTES','ESPERAR REPOSICION DE MATERIA PRIMA (CLARK)',
    'LIMPIEZA DE LENTE Y BOQUILLA','CORTE DE PRUEBA'],
  'BALANCINES':['MANTENIMIENTO','PUESTA EN MARCHA','ALMUERZO - CENA','LIMPIEZA DEL SECTOR','LIMPIEZA DE MATRIZ',
    'FALTA DE PREPARACION','MOVER PIEZAS','CORREGIR MEDIDA','CAMBIAR ROLLO','FALTA DE MATERIAL','CAMBIO DE OPERADOR',
    'FALTA DE OPERADOR','PROBLEMAS CON ALIMENTADOR','CAMBIO DE PREPARACION','ESPERAR AL ENCARGADO','BAÑO',
    'REPASAR PIEZAS','DESCARGAR MATERIAL','EXPLICACION / REUNION','CONTAR PIEZAS','PEDIR ELEMENTOS DE SEGURIDAD',
    'ENTREGAR PZ A CONTROL','PESAR DESPERDICIO / RECORTES (COBRE, LATON)','EMITIR DOCUMENTACION','ARMADO DE PLANILLAS']
};
function onTNPMaquinaChange(){
  resolveTNPCodigo();
}
// Arma el selector de máquina/sector: los sectores con códigos de parada
// predefinidos más las categorías de máquina / sector cargadas en Configuración.
// Se vuelve a leer en cada apertura para que aparezcan los sectores nuevos.
async function cargarTNPMaquinas(){
  const sel=$('tnp-maquina');
  let cats=[];
  try{ cats=await api('/api/categorias_maquina'); _catM=cats; }catch(e){ cats=_catM||[]; }
  const nombres=Object.keys(CODIGOS_PARADA_MAQUINA);
  const vistos=new Set(nombres.map(function(n){return n.toUpperCase();}));
  (cats||[]).forEach(function(c){
    const n=String(c.nombre||'').trim();
    if(n && !vistos.has(n.toUpperCase())){ vistos.add(n.toUpperCase()); nombres.push(n); }
  });
  sel.innerHTML='<option value="">-- Selecciona Maquina --</option>'
    +nombres.map(function(n){return '<option value="'+schEsc(n)+'">'+schEsc(n)+'</option>';}).join('');
}
// Si el usuario escribe un número en el campo Descripción/Código, lo resuelve
// a la descripción del código de parada correspondiente al tipo de máquina
// seleccionado (el código 20 significa algo distinto según la máquina).
function resolveTNPCodigo(){
  const maq=$('tnp-maquina').value;
  const val=$('tnp-desc').value.trim();
  if(!maq || !val || !/^\d+$/.test(val)) return;
  const arr=CODIGOS_PARADA_MAQUINA[maq];
  const idx=parseInt(val,10)-1;
  if(arr && arr[idx]!==undefined){
    $('tnp-desc').value=arr[idx];
  }
}
let _tnpEditFromList=false;
async function openTNP(id){
  _tnpEditFromList = !!id && $('mo-tnp-list').classList.contains('open');
  if(_tnpEditFromList){ closeMo('mo-tnp-list'); }
  $('tnp-id').value='';
  $('tnp-desc').value='';$('tnp-tmin').value='';
  $('tnp-fecha').value=new Date().toISOString().slice(0,10);
  $('tnp-emp').value='';$('tnp-emp-search').value='';
  $('tnp-emp-results').innerHTML='';$('tnp-emp-results').style.display='none';
  await cargarTNPMaquinas();
  $('tnp-maquina').value='';
  onTNPMaquinaChange();
  if(!_emp.length)_emp=await api('/api/empleados');
  if(id){
    const row=(_tnpListData||[]).find(function(t){return String(t.id)===String(id);})
      || await api('/api/trabajo-no-productivo/'+id).catch(function(){return null;});
    if(!row){toast('Registro no encontrado','e');return;}
    $('tnp-title').textContent='Editar trabajo no productivo';
    $('tnp-id').value=row.id;
    $('tnp-desc').value=row.descripcion||'';
    $('tnp-tmin').value=row.tiempo_min?(parseFloat(row.tiempo_min)/60):'';
    if(row.fecha) $('tnp-fecha').value=row.fecha.slice(0,10);
    if(row.empleado_id){
      $('tnp-emp').value=row.empleado_id;
      $('tnp-emp-search').value=row.empleado_nombre||nombreEmpleadoNov(row.empleado_id);
    }
    // Intenta reconstruir la selección de máquina a partir de la descripción guardada
    if(row.descripcion){
      for(const maq in CODIGOS_PARADA_MAQUINA){
        if(CODIGOS_PARADA_MAQUINA[maq].indexOf(row.descripcion)!==-1){
          $('tnp-maquina').value=maq;
          break;
        }
      }
    }
  } else {
    $('tnp-title').textContent='Trabajo no productivo';
  }
  openMo('mo-tnp');
}
function closeTNP(){
  closeMo('mo-tnp');
  if(_tnpEditFromList){ openTNPList(); }
}

function filtrarTNPEmpleados(){
  const q=($('tnp-emp-search').value||'').toLowerCase().trim();
  $('tnp-emp').value=''; // hasta que se reseleccione, no hay empleado confirmado
  const cont=$('tnp-emp-results');
  if(!q){cont.style.display='none';cont.innerHTML='';return;}
  const lista=_emp.filter(function(e){
    if(!e.activo)return false;
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
      $('tnp-emp').value=e.id;
      $('tnp-emp-search').value=e.apellido+', '+e.nombre;
      cont.style.display='none';
      cont.innerHTML='';
    };
    cont.appendChild(item);
  });
  cont.style.display='block';
}

async function saveTNP(){
  resolveTNPCodigo();
  const tH=parseFloat($('tnp-tmin').value);
  const editId=$('tnp-id').value;
  const fecha=$('tnp-fecha').value;
  const body={descripcion:$('tnp-desc').value.trim(),tiempo_min:Number.isFinite(tH)?Math.round(tH*60):'',empleado_id:$('tnp-emp').value||null,fecha:fecha||null};
  if(!body.descripcion||!body.tiempo_min){toast('Descripción y tiempo requeridos','w');return;}
  if(!fecha){toast('La fecha es requerida','w');return;}
  const btn=document.querySelector('#mo-tnp .btn-p');
  if(btn){btn.disabled=true;btn.textContent='Guardando...';}
  let res;
  try{
    res = editId
      ? await api('/api/trabajo-no-productivo/'+editId,{method:'PUT',body:JSON.stringify(body)})
      : await api('/api/trabajo-no-productivo',{method:'POST',body:JSON.stringify(body)});
  }catch(e){
    if(btn){btn.disabled=false;btn.textContent='Confirmar';}
    toast('Error de conexión','e');
    return;
  }
  if(btn){btn.disabled=false;btn.textContent='Confirmar';}
  closeMo('mo-tnp');
  if(res&&res.ok){
    toast(editId?'Trabajo no productivo actualizado':'Trabajo no productivo registrado: '+(res.numero||''),'g');
    if(_tnpEditFromList){ openTNPList(); }
  } else {
    toast((res&&res.error)||'Error al guardar','e');
  }
}

async function deleteTNPRow(id){
  if(!await confirmar('¿Eliminar este registro de trabajo no productivo?')) return;
  const res=await apiBorrar('/api/trabajo-no-productivo/'+id,'Registro eliminado').catch(function(){return null;});
  if(res&&res.ok){ toast('Registro eliminado','g'); loadTNPList(); }
  else { toast((res&&res.error)||'Error al eliminar','e'); }
}

// ── Listado de Trabajo no productivo ───────────────────────────────────────
let _tnpListData=[];
async function openTNPList(){
  if(!_emp.length)_emp=await api('/api/empleados');
  openMo('mo-tnp-list');
  loadTNPList();
}
function clearTNPListFiltros(){
  $('tnpl-emp-fil').value='';$('tnpl-emp-search').value='';
  $('tnpl-fdesde-fil').value='';
  $('tnpl-fhasta-fil').value='';
  loadTNPList();
}
function filtrarTNPListEmpleados(){
  const q=($('tnpl-emp-search').value||'').toLowerCase().trim();
  $('tnpl-emp-fil').value='';
  const cont=$('tnpl-emp-results');
  if(!q){cont.style.display='none';cont.innerHTML='';loadTNPList();return;}
  const lista=_emp.filter(function(e){
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
      $('tnpl-emp-fil').value=e.id;
      $('tnpl-emp-search').value=e.apellido+', '+e.nombre;
      cont.style.display='none';cont.innerHTML='';
      loadTNPList();
    };
    cont.appendChild(item);
  });
  cont.style.display='block';
}

async function loadTNPList(){
  const empId=$('tnpl-emp-fil').value;
  const fdesde=$('tnpl-fdesde-fil').value;
  const fhasta=$('tnpl-fhasta-fil').value;
  const p=[];
  if(empId) p.push('emp_id='+empId);
  if(fdesde) p.push('desde='+fdesde);
  if(fhasta) p.push('hasta='+fhasta);
  const rows=await api('/api/trabajo-no-productivo'+(p.length?'?'+p.join('&'):''));
  _tnpListData=rows;
  if(!rows.length){$('tnpl-list').innerHTML='<div class="em">Sin registros de trabajo no productivo para los filtros seleccionados.</div>';return;}
  let h='<table><tr><th>N°</th><th>Descripción</th><th>Empleado</th><th>Tiempo</th><th>Fecha</th>'
    +(['admin','operario'].includes(ROL)?'<th></th>':'')+'</tr>';
  rows.forEach(function(t){
    const horas=(parseFloat(t.tiempo_min||0)/60).toFixed(2).replace(/\.?0+$/,'');
    h+='<tr>'
      +'<td><b>'+t.numero+'</b></td>'
      +'<td>'+(t.descripcion||'')+'</td>'
      +'<td>'+(t.empleado_nombre||'—')+'</td>'
      +'<td>'+horas+'h</td>'
      +'<td>'+fmtD(t.fecha)+'</td>'
      +(['admin','operario'].includes(ROL)?'<td style="white-space:nowrap"><button class="btn btn-s" onclick="openTNP('+t.id+')">Editar</button> <button class="btn btn-s" onclick="deleteTNPRow('+t.id+')">Eliminar</button></td>':'')
      +'</tr>';
  });
  $('tnpl-list').innerHTML=h+'</table>';
}

// ── Novedades eliminadas (auditoría) ───────────────────────────────────────
async function openNovEliminadasList(){
  openMo('mo-nov-elim');
  loadNovEliminadas();
}
function clearNovEliminadasFiltros(){
  $('novelim-q-fil').value='';
  $('novelim-fdesde-fil').value='';
  $('novelim-fhasta-fil').value='';
  loadNovEliminadas();
}
async function loadNovEliminadas(){
  const q=$('novelim-q-fil').value.trim();
  const fdesde=$('novelim-fdesde-fil').value;
  const fhasta=$('novelim-fhasta-fil').value;
  const p=[];
  if(q) p.push('q='+encodeURIComponent(q));
  if(fdesde) p.push('desde='+fdesde);
  if(fhasta) p.push('hasta='+fhasta);
  const rows=await api('/api/novedades-eliminadas'+(p.length?'?'+p.join('&'):''));
  if(!rows.length){$('novelim-list').innerHTML='<div class="em">Sin novedades eliminadas para los filtros seleccionados.</div>';return;}
  _novElimData={};
  let h='<table><tr><th>N°</th><th>OT</th><th>Operación</th><th>Producto</th><th>Empleado</th>'
    +'<th>Cant.</th><th>Rend.</th><th>Fecha novedad</th><th>Eliminado por</th><th>Eliminado el</th><th></th></tr>';
  rows.forEach(function(n){
    _novElimData[n.id]=n;
    h+='<tr>'
      +'<td><b>'+(n.novedad_numero||'—')+'</b></td>'
      +'<td>'+(n.orden_numero||'—')+'</td>'
      +'<td>'+(n.operacion_nombre||'—')+'</td>'
      +'<td>'+(n.producto_nombre||'—')+'</td>'
      +'<td>'+(n.empleado_nombre||'—')+'</td>'
      +'<td>'+(n.cantidad_producida!=null?n.cantidad_producida:'—')+'</td>'
      +'<td>'+(n.rendimiento_pct!=null?Math.round(n.rendimiento_pct)+'%':'—')+'</td>'
      +'<td>'+fmtDH(n.fecha_novedad)+'</td>'
      +'<td>'+(n.eliminado_por_nombre||'—')+'</td>'
      +'<td>'+fmtDH(n.eliminado)+'</td>'
      +'<td style="white-space:nowrap">'
        +'<button class="btn btn-s" onclick="verDetalleNovElim('+n.id+')">Detalles</button> '
        +(n.restaurado
          ? '<span class="b bg" title="Restaurada por '+(n.restaurado_por_nombre||'—')+' el '+fmtDH(n.restaurado)+'">Restaurada</span>'
          : '<button class="btn btn-s" style="color:#166534" onclick="restaurarNovElim('+n.id+')">Restaurar</button>')
      +'</td>'
      +'</tr>';
  });
  $('novelim-list').innerHTML=h+'</table>';
}

// ── Restaurar una novedad eliminada (rehace todo lo que se había revertido) ─
async function restaurarNovElim(id){
  const n=_novElimData[id];
  if(!n){toast('No se encontró el registro','e');return;}
  if(!await confirmar('¿Restaurar la novedad '+(n.novedad_numero||'')+'?\nSe volverá a crear la novedad y se rehará todo lo que se había revertido: consumo de materia prima, stock de producto terminado e ítems de remito.')) return;
  const res=await api('/api/novedades-eliminadas/'+id+'/restaurar',{method:'POST'});
  if(res.ok){
    toast('Novedad '+res.numero+' restaurada','g');
    if(res.warnings && res.warnings.length){
      toast(res.warnings.join(' | '),'w');
    }
    loadNovEliminadas();
  } else {
    toast(res.error||'Error al restaurar','e');
  }
}

// ── Detalle de consecuencias de una novedad eliminada ──────────────────────
var _novElimData={};
function verDetalleNovElim(id){
  const n=_novElimData[id];
  if(!n){toast('No se encontró el registro','e');return;}
  const det=n.detalle||{};
  let h='';

  h+='<div style="font-size:12px;color:var(--color-text-secondary);margin-bottom:12px">'
    +'Novedad <b>'+(n.novedad_numero||'—')+'</b> de la OT <b>'+(n.orden_numero||'—')+'</b>'
    +' — '+(n.cantidad_producida!=null?n.cantidad_producida:'—')+' unidades declaradas'
    +', eliminada por '+(n.eliminado_por_nombre||'—')+' el '+fmtDH(n.eliminado)+'.</div>';

  // Materia prima devuelta a lotes
  h+='<div style="font-size:11px;font-weight:600;color:#888;margin-bottom:6px;text-transform:uppercase;letter-spacing:.04em">Materia prima devuelta</div>';
  if(det.lotes_mp && det.lotes_mp.length){
    det.lotes_mp.forEach(function(l){
      h+='<div class="opc">'
        +'<div class="oph"><span class="opn">'+(l.material||'—')+'</span>'
        +'<span class="b bg">+'+fN(l.cantidad_devuelta)+'</span></div>'
        +'<div class="opm">Lote '+(l.lote_numero||'—')+' — estado '+(l.estado_lote||'—')
        +' — disponible actual: '+(l.cantidad_disponible_actual!=null?l.cantidad_disponible_actual:'—')+'</div>'
        +(l.nota?'<div class="opm" style="color:#854F0B">'+l.nota+'</div>':'')
        +'</div>';
    });
  } else {
    h+='<div class="em" style="padding:10px">No consumió materia prima de lotes.</div>';
  }

  // Producto terminado revertido
  h+='<div style="font-size:11px;font-weight:600;color:#888;margin:12px 0 6px;text-transform:uppercase;letter-spacing:.04em">Producto terminado revertido</div>';
  if(det.pt){
    h+='<div class="opc">'
      +'<div class="oph"><span class="opn">'+(det.pt.material||'—')+'</span>'
      +'<span class="b br">-'+fN(det.pt.cantidad_revertida_stock)+'</span></div>';
    if(det.pt.lotes_ot && det.pt.lotes_ot.length){
      h+='<div class="opm">Lote(s) de esta OT:</div>';
      det.pt.lotes_ot.forEach(function(l){
        h+='<div class="opm">• '+(l.numero||'—')+' — '+(l.estado||'—')
          +' — disponible: '+(l.cantidad_disponible!=null?l.cantidad_disponible:'—')
          +' / activa: '+(l.cantidad_activa!=null?l.cantidad_activa:'—')+'</div>';
      });
    }
    h+='</div>';
  } else {
    h+='<div class="em" style="padding:10px">Esta novedad no era la última operación de la OT, no generó/revirtió stock de producto terminado.</div>';
  }

  // Remitos afectados
  h+='<div style="font-size:11px;font-weight:600;color:#888;margin:12px 0 6px;text-transform:uppercase;letter-spacing:.04em">Remitos que ya usaban ese stock</div>';
  if(det.remitos && det.remitos.length){
    h+='<div class="al al-w" style="margin-bottom:8px">Atención: ya se había remitido stock proveniente de los lotes afectados por esta novedad antes de eliminarla.</div>';
    det.remitos.forEach(function(r){
      h+='<div class="opc">'
        +'<div class="oph"><span class="opn">Remito '+(r.remito_numero||'—')+'</span>'
        +'<span class="b bb">'+(r.cantidad!=null?r.cantidad:'—')+'</span></div>'
        +'<div class="opm">Cliente: '+(r.cliente_nombre||'—')+' — Lote '+(r.lote_numero||'—')
        +' ('+(r.material||'—')+') — '+fmtDH(r.fecha)+' — '+(r.estado||'—')+'</div>'
        +'</div>';
    });
  } else {
    h+='<div class="em" style="padding:10px">No se había remitido stock de los lotes afectados.</div>';
  }

  $('novelim-det-body').innerHTML=h;
  openMo('mo-nov-elim-det');
}


let _occProd=[], _occN=0, _occItemsBloqueados=[];


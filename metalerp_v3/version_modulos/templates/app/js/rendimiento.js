// ── Rendimiento por operario ──────────────────────────────────────────────────
async function loadRendimiento(){
  const rows=await api('/api/rendimiento_operario');
  const cont=$('rend-list');
  if(!rows.length){cont.innerHTML='<div class="em">Sin datos. Declarar novedades con empleado asignado.</div>';return;}
  // Rango por defecto: últimos 30 días
  const hoy=new Date();
  const hace30=new Date(hoy.getTime()-29*24*60*60*1000);
  const fmt=function(d){return d.toISOString().slice(0,10);};
  const defDesde=fmt(hace30), defHasta=fmt(hoy);
  // Inicializar los selectores globales si aún no tienen valor
  const gDesde=$('rend-global-desde'), gHasta=$('rend-global-hasta');
  if(gDesde && !gDesde.value) gDesde.value=defDesde;
  if(gHasta && !gHasta.value) gHasta.value=defHasta;
  let html='';
  rows.forEach(function(emp,ei){
    const eId='re'+ei;
    html+='<div class="rend-card" data-emp-id="'+emp.emp_id+'" style="border:1.5px solid var(--color-primary,#2C5F8A);border-radius:8px;margin-bottom:10px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.08)">';
    html+='<div class="rend-hdr" data-target="'+eId+'" title="Clic: ver u ocultar el detalle diario" onmouseover="this.style.background=\'var(--color-border-tertiary)\'" onmouseout="this.style.background=\'var(--color-background-secondary)\'" style="display:flex;align-items:center;justify-content:space-between;cursor:pointer;padding:10px 14px;background:var(--color-background-secondary);gap:10px;transition:background .15s">'
      +'<input type="radio" name="rend-sel" style="flex-shrink:0;margin:0">'
      +'<span style="font-weight:600;font-size:14px;flex-shrink:0">'+emp.nombre+'</span>'
      +'<div id="'+eId+'-sum" style="display:flex;gap:12px;align-items:center;flex-wrap:wrap;flex:1;justify-content:flex-end;margin-right:10px"><span style="font-size:11px;color:var(--color-text-secondary)">Cargando...</span></div>'
      +'<span id="'+eId+'-i" class="rend-tog" title="Ver u ocultar el detalle" style="font-size:14px;flex-shrink:0;color:var(--color-primary,#2C5F8A);font-weight:700;padding:0 4px">▶</span>'
      +'</div>';
    html+='<div id="'+eId+'" style="display:none;padding:10px 14px 12px">';
    html+='<div id="'+eId+'-tbl"><div class="ld" style="font-size:12px">Cargando...</div></div>';
    html+='</div></div>';
  });
  cont.innerHTML=html;
  cont._rendOrigOrder=Array.from(cont.querySelectorAll('.rend-card'));
  rendRankingDir=null;
  // Buscador de operarios
  const buscador=$('rend-buscar');
  if(buscador){
    buscador.value='';
    buscador.oninput=function(){
      const q=buscador.value.trim().toLowerCase();
      cont.querySelectorAll('.rend-card').forEach(function(card){
        const nombre=(card.querySelector('.rend-hdr span').textContent||'').toLowerCase();
        card.style.display=nombre.includes(q)?'':'none';
      });
    };
  }
  // Clic en el encabezado del operario (o en ▶): lo selecciona y abre / cierra
  // el detalle diario.
  if(_rendSel && !rows.some(function(e){return String(e.emp_id)===String(_rendSel);})) _rendSel=null;
  cont.querySelectorAll('.rend-hdr').forEach(function(hdr){
    const card=hdr.closest('.rend-card');
    hdr.addEventListener('click',function(){ selRend(card.dataset.empId); toggleRend(hdr.dataset.target); });
  });
  selRend(_rendSel);
  // Asociar cada card con su función de refresco (usa fechas globales)
  const initProms=[];
  cont.querySelectorAll('.rend-card').forEach(function(card){
    const empId=card.dataset.empId;
    const eId=card.querySelector('.rend-hdr').dataset.target;
    // Carga el resumen en el header (siempre, sin abrir el panel)
    card._refreshSum=function(){
      const desde=($('rend-global-desde')||{}).value||defDesde;
      const hasta=($('rend-global-hasta')||{}).value||defHasta;
      return loadRendimientoOperarioRango(empId,desde,hasta,eId+'-tbl',eId+'-sum');
    };
    // Carga la tabla completa (solo al abrir el panel)
    card._refreshRend=card._refreshSum;
    // Cargar resumen del header inmediatamente para todos los operarios
    initProms.push(card._refreshSum());
    card._rendLoaded=true; // marcar como cargado para que toggleRend no re-dispare
  });
  // Cuando terminen de cargar todos los resúmenes, reaplicar el ranking si está activo
  Promise.all(initProms).then(function(){ applyRendRanking(); });
}

let _rendSel=null;
function selRend(empId){
  _rendSel=empId||null;
  document.querySelectorAll('#rend-list .rend-card').forEach(function(card){
    const s=_rendSel!==null&&card.dataset.empId===String(_rendSel);
    card.classList.toggle('rend-sel',s);
    const rb=card.querySelector('input[name=rend-sel]'); if(rb) rb.checked=s;
  });
  actualizarToolbarRend();
}
function _rendSelCard(){
  if(_rendSel===null) return null;
  return Array.from(document.querySelectorAll('#rend-list .rend-card')).find(function(c){return c.dataset.empId===String(_rendSel);})||null;
}
function actualizarToolbarRend(){
  const card=_rendSelCard();
  const lbl=$('rend-sel-label');
  if(lbl){
    const t=card?(card.querySelector('.rend-hdr span').textContent||''):'–';
    lbl.textContent=t.length>28?t.slice(0,27)+'…':t;
    lbl.title=card?t:'Operario seleccionado';
  }
}

function rendAplicarFechasGlobales(){
  const cont=$('rend-list');
  if(!cont) return;
  const proms=[];
  cont.querySelectorAll('.rend-card').forEach(function(card){
    if(card._refreshRend){
      card._rendLoaded=false;
      proms.push(card._refreshRend());
    }
  });
  Promise.all(proms).then(function(){ applyRendRanking(); });
}

// ── Ranking de operarios por rendimiento (según fechas seleccionadas) ─────────
let rendRankingDir=null; // null = orden original, 'desc' = mayor a menor, 'asc' = menor a mayor
function toggleRendRanking(){
  rendRankingDir = rendRankingDir===null ? 'desc' : (rendRankingDir==='desc' ? 'asc' : null);
  applyRendRanking();
}
function applyRendRanking(){
  const cont=$('rend-list');
  const btn=$('rend-ranking-btn');
  if(!cont) return;
  if(!rendRankingDir){
    // Restaurar el orden original de las cards
    if(cont._rendOrigOrder){
      cont._rendOrigOrder.forEach(function(c){cont.appendChild(c);});
    }
    if(btn){btn.textContent='Ranking';btn.classList.remove('btn-p');}
    return;
  }
  const cards=Array.from(cont.querySelectorAll('.rend-card'));
  cards.sort(function(a,b){
    const ra=parseFloat(a.dataset.rend);
    const rb=parseFloat(b.dataset.rend);
    const va=isNaN(ra)?-1:ra, vb=isNaN(rb)?-1:rb;
    return rendRankingDir==='desc' ? (vb-va) : (va-vb);
  });
  cards.forEach(function(c){cont.appendChild(c);});
  if(btn){
    btn.textContent = rendRankingDir==='desc' ? 'Ranking ▼ Mayor a menor' : 'Ranking ▲ Menor a mayor';
    btn.classList.add('btn-p');
  }
}

function toggleRend(id){
  const el=$(id),ic=$(id+'-i');
  if(!el) return;
  const open=el.style.display==='block';
  el.style.display=open?'none':'block';
  if(ic) ic.textContent=open?'▶':'▼';
  actualizarToolbarRend();
  // Cargar la tabla recién al abrir, la primera vez
  if(!open){
    const card=el.closest('.rend-card');
    if(card && card._refreshRend && !card._rendLoaded){
      card._rendLoaded=true;
      card._refreshRend();
    }
  }
}

function toggleTnpBlock(id){
  const el=$(id),ic=$(id+'-i');
  if(!el) return;
  const open=el.style.display==='block';
  el.style.display=open?'none':'block';
  if(ic) ic.textContent=open?'▶':'▼';
}

async function loadRendimientoOperarioRango(empId,desde,hasta,targetId,sumId){
  const cont=$(targetId);
  const sumCont=sumId?$(sumId):null;
  if(!cont) return;
  cont.innerHTML='<div class="ld" style="font-size:12px">Cargando...</div>';
  let url='/api/rendimiento_operario_dias?emp_id='+empId;
  if(desde) url+='&desde='+desde;
  if(hasta) url+='&hasta='+hasta;
  let tnpUrl='/api/trabajo-no-productivo?emp_id='+empId;
  if(desde) tnpUrl+='&desde='+desde;
  if(hasta) tnpUrl+='&hasta='+hasta;
  const [dias,tnp]=await Promise.all([api(url),api(tnpUrl)]);
  if(!dias.length){
    cont.innerHTML='<div class="em" style="font-size:12px">Sin datos en el período seleccionado.</div>';
    if(sumCont) sumCont.innerHTML='<span style="font-size:11px;color:var(--color-text-secondary)">Sin datos</span>';
    const cardVacio=sumCont?sumCont.closest('.rend-card'):null;
    if(cardVacio) delete cardVacio.dataset.rend;
    return;
  }
  // Promedio del período (ponderado por tiempo real trabajado de cada día)
  let sumMin=0,sumRendPond=0,sumProducido=0,sumNovedades=0,sumNoOk=0;
  dias.forEach(function(dia){
    const min=parseFloat(dia.total_min_real)||0;
    sumMin+=min;
    sumRendPond+=(parseFloat(dia.rend_promedio)||0)*min;
    sumProducido+=parseFloat(dia.total_producido)||0;
    sumNovedades+=parseFloat(dia.novedades)||0;
    sumNoOk+=parseFloat(dia.total_no_ok)||0;
  });
  const rendProm=sumMin>0?Math.round((sumRendPond/sumMin)*10)/10:0;
  const rcProm=rendProm>=95?'bg':rendProm>=80?'ba':'br';
  // Guardar el rendimiento del período en la card, para poder ordenar por Ranking
  const cardRend=sumCont?sumCont.closest('.rend-card'):null;
  if(cardRend) cardRend.dataset.rend=rendProm;
  // Actualizar el resumen en el header del operario
  if(sumCont){
    sumCont.innerHTML=
      '<span class="b '+rcProm+'" style="font-size:12px">'+rendProm+'%</span>'
      +'<span style="font-size:12px;color:var(--color-text-secondary)">Producido: <b style="color:var(--color-text-primary)">'+sumProducido+'</b></span>'
      +'<span style="font-size:12px;color:var(--color-text-secondary)">No OK: <b style="color:var(--color-text-primary)">'+sumNoOk+'</b></span>'
      +'<span style="font-size:12px;color:var(--color-text-secondary)">Novedades: <b style="color:var(--color-text-primary)">'+sumNovedades+'</b></span>'
      +'<span style="font-size:12px;color:var(--color-text-secondary)">Días: <b style="color:var(--color-text-primary)">'+dias.length+'</b></span>';
  }
  let html='<table style="width:100%"><tr>'
    +'<th style="text-align:left;font-size:11px;padding:3px 6px">Fecha</th>'
    +'<th style="text-align:left;font-size:11px;padding:3px 6px">Producido</th>'
    +'<th style="text-align:left;font-size:11px;padding:3px 6px">No OK</th>'
    +'<th style="text-align:left;font-size:11px;padding:3px 6px">T.real</th>'
    +'<th style="text-align:left;font-size:11px;padding:3px 6px">Rendimiento</th>'
    +'<th style="text-align:left;font-size:11px;padding:3px 6px">Novedades</th></tr>';
  let diasNoProd=0, novedadesNoProd=0;
  dias.forEach(function(dia){
    const rc=dia.rend_promedio>=95?'bg':dia.rend_promedio>=80?'ba':'br';
    if(rc==='br'){
      diasNoProd++;
      novedadesNoProd+=parseFloat(dia.novedades)||0;
    }
    html+='<tr style="font-size:12px">'
      +'<td style="padding:3px 6px">'+dia.dia+'</td>'
      +'<td style="padding:3px 6px">'+fN(dia.total_producido)+'</td>'
      +'<td style="padding:3px 6px">'+(dia.total_no_ok||0)+'</td>'
      +'<td style="padding:3px 6px">'+dia.total_min_real+'min</td>'
      +'<td style="padding:3px 6px"><span class="b '+rc+'">'+dia.rend_promedio+'%</span></td>'
      +'<td style="padding:3px 6px">'+dia.novedades+'</td></tr>';
  });
  html+='</table>';
  // Fila combinada: el menú desplegable de "Trabajo no productivo cargado" a la
  // izquierda (compacto) y, a la misma altura, "Novedades no productivas" a la derecha.
  const tnpId=targetId+'-tnp';
  html+='<div style="margin-top:8px;display:flex;gap:16px;align-items:stretch;flex-wrap:wrap">';
  // Bloque: trabajo no productivo cargado (limpieza, etc.) en el período,
  // como menú desplegable dentro del menú desplegable del operario, a la izquierda.
  if(tnp && tnp.length){
    const sumTnpMin=tnp.reduce(function(s,t){return s+(parseFloat(t.tiempo_min)||0);},0);
    html+='<div style="border:1.5px solid var(--color-primary,#2C5F8A);border-radius:6px;overflow:hidden;flex-shrink:0;box-shadow:0 1px 3px rgba(0,0,0,0.08)">'
      +'<div style="width:100%">'
      +'<div onclick="toggleTnpBlock(\''+tnpId+'\')" onmouseover="this.style.background=\'var(--color-border-tertiary)\'" onmouseout="this.style.background=\'var(--color-background-secondary)\'" style="cursor:pointer;padding:6px 10px;background:var(--color-background-secondary);font-size:12px;font-weight:600;display:flex;justify-content:flex-end;align-items:center;gap:10px;text-align:right;height:100%;transition:background .15s">'
      +'<span>Trabajo no productivo cargado</span>'
      +'<span style="color:var(--color-text-secondary);font-weight:400">Total: '+tnp.length+' · '+sumTnpMin+'min</span>'
      +'<span id="'+tnpId+'-i" style="flex-shrink:0;color:var(--color-primary,#2C5F8A);font-weight:700">▶</span>'
      +'</div>'
      +'<div id="'+tnpId+'" style="display:none">'
      +'<table style="width:100%"><tr>'
      +'<th style="text-align:left;font-size:11px;padding:3px 6px">Fecha</th>'
      +'<th style="text-align:left;font-size:11px;padding:3px 6px">Descripción</th>'
      +'<th style="text-align:left;font-size:11px;padding:3px 6px">Tiempo</th>'
      +'<th style="text-align:left;font-size:11px;padding:3px 6px">Nº</th></tr>';
    tnp.forEach(function(t){
      html+='<tr style="font-size:12px">'
        +'<td style="padding:3px 6px">'+(t.fecha||'').slice(0,10)+'</td>'
        +'<td style="padding:3px 6px">'+(t.descripcion||'')+'</td>'
        +'<td style="padding:3px 6px">'+(t.tiempo_min||0)+'min</td>'
        +'<td style="padding:3px 6px">'+(t.numero||'')+'</td></tr>';
    });
    html+='</table></div></div></div>';
  } else {
    html+='<div style="font-size:12px;color:var(--color-text-secondary);display:flex;align-items:center">Sin trabajo no productivo cargado en el período seleccionado.</div>';
  }
  // "Novedades no productivas" a la derecha.
  html+='<div style="flex:1;padding:8px 10px;border-radius:6px;background:var(--color-background-secondary);display:flex;gap:16px;align-items:center;justify-content:flex-end;flex-wrap:wrap">'
    +'<span style="font-size:12px;color:var(--color-text-secondary)">Novedades no productivas (rendimiento &lt;80%): <b style="color:var(--color-text-primary)">'+novedadesNoProd+'</b></span>'
    +'</div>';
  html+='</div>';
  cont.innerHTML=html;
}



async function openLiberacion(loteId){
  const cajs=await api('/api/cajones?lote_id='+loteId);
  if(Array.isArray(cajs)&&cajs.some(function(c){return c.orden_id;})){
    const l=(_lotesData||[]).find(function(x){return x.id==loteId;});
    filtrarCajLote(loteId, l?l.numero:('Lote '+loteId));
    toast('Este lote se libera por cajón','w');
    return;
  }
  const rows=await api('/api/lotes');
  const lote=rows.find(function(l){return l.id==loteId;});
  if(!lote) return;
  $('lm-id').value=lote.id;
  $('lm-total').value=lote.cantidad_disponible;
  $('lm-title').childNodes[0].textContent='Gestionar lote '+lote.numero+' ';
  $('lm-info').innerHTML='<b>'+lote.numero+'</b> — '+lote.mat_descripcion
    +' | Disponible: <b>'+fN(lote.cantidad_disponible)+'</b> '+lote.unidad
    +' | Estado actual: <b>'+lote.estado+'</b>'
    +(lote.referencia_proveedor?' | Ref: '+lote.referencia_proveedor:'')
    +(lote.certificado?' | Cert: '+lote.certificado:'');
  $('lm-aprobado').value=(lote.cantidad_activa||0);
  $('lm-rechazado').value=(lote.cantidad_rechazada||0);
  $('lm-aprobado').max=lote.cantidad_disponible;
  $('lm-rechazado').max=lote.cantidad_disponible;
  $('lm-unidad-1').textContent=$('lm-unidad-2').textContent=$('lm-unidad-3').textContent=lote.unidad||'';
  $('lm-total-lbl').textContent=lote.cantidad_disponible+' '+(lote.unidad||'');
  $('lm-obs').value='';
  $('lm-err').style.display='none';
  lmRecalc();
  openMo('mo-lm');
  setTimeout(function(){ $('lm-aprobado').focus(); }, 80);
}

// Recalcula "Pendiente" = Total - Aprobado - Rechazado, y valida que no se exceda el total.
// changed: 'aprobado' | 'rechazado' | undefined — el campo que el usuario tocó, para recortar ese mismo si excede.
function lmRecalc(changed){
  const total=parseFloat($('lm-total').value)||0;
  let aprobado=parseFloat($('lm-aprobado').value)||0;
  let rechazado=parseFloat($('lm-rechazado').value)||0;
  if(aprobado<0) aprobado=0;
  if(rechazado<0) rechazado=0;
  if(aprobado+rechazado>total+0.001){
    // Recortamos el campo que se acaba de editar para que la suma no supere el total
    if(changed==='aprobado'){ aprobado=Math.max(0,total-rechazado); $('lm-aprobado').value=aprobado; }
    else { rechazado=Math.max(0,total-aprobado); $('lm-rechazado').value=rechazado; }
  }
  const pendiente=Math.max(0,total-aprobado-rechazado);
  $('lm-pendiente').value=pendiente.toFixed(2);
  $('lm-err').style.display='none';
}

function lmQuick(accion){
  const total=parseFloat($('lm-total').value)||0;
  if(accion==='aprobar_todo'){ $('lm-aprobado').value=total; $('lm-rechazado').value=0; }
  else if(accion==='rechazar_todo'){ $('lm-aprobado').value=0; $('lm-rechazado').value=total; }
  else if(accion==='reset'){ $('lm-aprobado').value=0; $('lm-rechazado').value=0; }
  lmRecalc();
}

async function saveLiberacion(){
  const id=$('lm-id').value;
  const total=parseFloat($('lm-total').value)||0;
  const aprobado=parseFloat($('lm-aprobado').value)||0;
  const rechazado=parseFloat($('lm-rechazado').value)||0;
  if(aprobado<0||rechazado<0){ toast('Las cantidades no pueden ser negativas','w'); return; }
  if(aprobado+rechazado>total+0.001){
    $('lm-err').textContent='Aprobado + Rechazado ('+fN(aprobado+rechazado)+') no puede superar el total disponible ('+fN(total)+')';
    $('lm-err').style.display='block';
    return;
  }
  const body={
    cantidad_aprobada: aprobado,
    cantidad_rechazada: rechazado,
    obs:$('lm-obs').value,
  };
  const res=await api('/api/lotes/'+id,{method:'PUT',body:JSON.stringify(body)});
  if(res.ok){
    toast('Lote '+res.numero_lote+' → Aprobado: '+fN(res.cantidad_aprobada)+' | Rechazado: '+fN(res.cantidad_rechazada)+' | Pendiente: '+fN(res.cantidad_pendiente)+' | Estado: '+res.estado);
    closeMo('mo-lm');
    loadLotes();
  } else toast(res.error||'Error','e');
}


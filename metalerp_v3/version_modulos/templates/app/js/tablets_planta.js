// ── Tablets de planta (solo admin) ───────────────────────────────────────────
// Alta de tablets por máquina (cada una con su enlace/token) y la bandeja de lo
// que mandan los operarios. El procesador del servidor convierte cada registro
// en novedad; acá se ven los que fallaron y se corrigen o descartan.
let _tabVista='tablets', _tablets=[], _bandeja=[];

document.querySelectorAll('#tab-tabs .tab').forEach(function(t){t.addEventListener('click',function(){
  document.querySelectorAll('#tab-tabs .tab').forEach(function(x){x.classList.remove('active');});
  t.classList.add('active'); _tabVista=t.dataset.t; loadTabletsPlanta();
});});

async function loadTabletsPlanta(){
  $('tab-fil-bandeja').style.display=_tabVista==='bandeja'?'':'none';
  $('tab-b-nueva').style.display=_tabVista==='tablets'?'':'none';
  const data=await api('/api/planta/tablets');
  _tablets=Array.isArray(data)?data:[];
  const sel=$('tab-fil-tablet'), act=sel.value;
  sel.innerHTML='<option value="">Todas las tablets</option>'+_tablets.map(function(t){return '<option value="'+t.id+'">'+audEsc(t.nombre)+'</option>';}).join('');
  sel.value=act;
  if(_tabVista==='bandeja') return loadBandejaPlanta();
  if(!Array.isArray(data)){ $('tab-list').innerHTML='<div class="em">'+audEsc((data&&data.error)||'No se pudo leer.')+'</div>'; return; }
  const pend=_tablets.reduce(function(a,t){return a+t.pendientes;},0), err=_tablets.reduce(function(a,t){return a+t.errores;},0);
  $('tab-resumen').textContent=err?err+' con error':(pend?pend+' pendientes':'Al día');
  if(!_tablets.length){
    $('tab-list').innerHTML='<div class="em">Todavía no hay tablets. Usá "Nueva tablet", elegí la máquina y abrí el enlace que te da en la tablet.</div>';
    return;
  }
  const ahora=Date.now();
  let h='<table><tr><th>Tablet</th><th>Máquina</th><th>Estado</th><th>Última conexión</th><th>Lector de huella</th><th>Último registro</th><th>Pendientes</th><th>Con error</th><th></th></tr>';
  _tablets.forEach(function(t){
    let con='<span style="color:var(--color-text-tertiary)">Sin datos desde el último reinicio</span>';
    if(t.ultimo_contacto){
      const seg=(ahora-new Date(t.ultimo_contacto.replace(' ','T')).getTime())/1000;
      con=seg<30?'<span class="b bg">En línea</span>':audEsc(fmtDH(t.ultimo_contacto));
    }
    h+='<tr>'
      +'<td><b>'+audEsc(t.nombre)+'</b></td>'
      +'<td>'+audEsc((t.maquina_codigo||'')+' · '+(t.maquina_nombre||''))+'</td>'
      +'<td>'+(t.activa?'<span class="b bg">Activa</span>':'<span class="b bk">Desactivada</span>')+'</td>'
      +'<td>'+con+'</td>'
      +'<td>'+tabLectorCelda(t,ahora)+'</td>'
      +'<td>'+audEsc(t.ultimo_registro?fmtDH(t.ultimo_registro):'—')+'</td>'
      +'<td>'+(t.pendientes||'—')+'</td>'
      +'<td>'+(t.errores?'<a href="#" onclick="tabVerErrores('+t.id+');return false"><span class="b br">'+t.errores+'</span></a>':'—')+'</td>'
      +'<td style="white-space:nowrap;text-align:right">'
        +'<button class="btn" onclick="tabVerEnlace('+t.id+')">Enlace</button> '
        +'<button class="btn" onclick="tabAbrir('+t.id+')">Editar</button> '
        +'<button class="btn" onclick="tabLector('+t.id+')">Lector</button> '
        +'<button class="btn" title="Hacer de cuenta que un operario apoyó el dedo" onclick="tabProbarHuella('+t.id+')">Probar huella</button> '
        +'<button class="btn" title="Genera un enlace nuevo: el anterior deja de servir (tablet perdida o robada)" onclick="tabNuevoToken('+t.id+')">Nuevo enlace</button>'
      +'</td></tr>';
  });
  $('tab-list').innerHTML=h+'</table>';
}

function tabLectorCelda(t,ahora){
  if(!t.lector_sn) return '<span style="color:var(--color-text-tertiary)">Sin lector</span>';
  let est='<span style="font-size:11px;color:var(--color-text-tertiary)">sin noticias desde el último reinicio</span>';
  if(t.lector_visto){
    const seg=(ahora-new Date(t.lector_visto.replace(' ','T')).getTime())/1000;
    est=seg<60?'<span class="b bg">Conectado</span>':'<span style="font-size:11px">visto '+audEsc(fmtDH(t.lector_visto))+'</span>';
  }
  return audEsc(t.lector_sn)+' '+est+(t.ultima_huella?'<div style="font-size:11px;color:var(--color-text-secondary)">Última huella: '+audEsc(fmtDH(t.ultima_huella))+'</div>':'');
}

async function tabLector(id){
  const t=_tablets.find(function(x){return x.id===id;}); if(!t) return;
  $('tlec-id').value=id; $('tlec-sn').value=t.lector_sn||'';
  $('tlec-title').textContent='Lector de huella de '+t.nombre;
  const host=(t.enlace||'').replace(/^https?:\/\//,'').split('/')[0];
  $('tlec-ip').textContent=host.split(':')[0]; $('tlec-puerto').textContent=host.split(':')[1]||'80';
  $('tlec-vistos').innerHTML='';
  openMo('mo-tablet-lector');
  const ls=await api('/api/planta/lectores');
  if(!Array.isArray(ls)||!ls.length){ $('tlec-vistos').innerHTML='<div style="font-size:12px;color:var(--color-text-tertiary)">Todavía no se comunicó ningún lector desde que arrancó el servidor.</div>'; return; }
  $('tlec-vistos').innerHTML='<div style="font-size:12px;font-weight:600;margin-bottom:4px">Lectores que se comunicaron</div>'
    +ls.map(function(l){
      return '<div style="display:flex;align-items:center;gap:8px;font-size:12.5px;padding:3px 0"><b>'+audEsc(l.sn)+'</b>'
        +'<span style="color:var(--color-text-secondary)">'+audEsc(l.ip||'')+' · '+audEsc(fmtDH(l.visto))+(l.tablet?' · asignado a '+audEsc(l.tablet):'')+'</span>'
        +'<button class="btn" style="margin-left:auto" onclick="$(\'tlec-sn\').value=\''+audEsc(l.sn).replace(/\\/g,'')+'\'">Usar este</button></div>';
    }).join('');
}

async function tabGuardarLector(){
  const id=$('tlec-id').value, btn=$('tlec-guardar'); btn.disabled=true;
  try{
    const res=await api('/api/planta/tablets/'+id+'/lector',{method:'PUT',body:JSON.stringify({lector_sn:$('tlec-sn').value.trim()})});
    if(!res||res.error){ toast((res&&res.error)||'No se pudo guardar','e'); return; }
    closeMo('mo-tablet-lector'); toast('Lector guardado'); loadTabletsPlanta();
  }finally{ btn.disabled=false; }
}

async function tabProbarHuella(id){
  const t=_tablets.find(function(x){return x.id===id;}); if(!t) return;
  $('thue-id').value=id; $('thue-title').textContent='Probar huella en '+t.nombre;
  $('thue-emp').innerHTML='<option value="">Cargando...</option>';
  openMo('mo-tablet-huella');
  const emps=await api('/api/empleados');
  $('thue-emp').innerHTML=(Array.isArray(emps)?emps:[]).filter(function(e){return e.activo;}).map(function(e){
    return '<option value="'+e.id+'">'+audEsc(((e.apellido||'')+' '+(e.nombre||'')).trim()+' · leg. '+(e.legajo||'—'))+'</option>';}).join('');
}

async function tabSimularHuella(){
  const btn=$('thue-ok'); btn.disabled=true;
  try{
    const res=await api('/api/planta/tablets/'+$('thue-id').value+'/huella',{method:'POST',body:JSON.stringify({empleado_id:$('thue-emp').value})});
    if(!res||res.error){ toast((res&&res.error)||'No se pudo','e'); return; }
    toast('Huella enviada: mirá la tablet');
  }finally{ btn.disabled=false; }
}

function tabVerErrores(id){
  document.querySelectorAll('#tab-tabs .tab').forEach(function(x){x.classList.toggle('active',x.dataset.t==='bandeja');});
  _tabVista='bandeja'; $('tab-fil-estado').value='Error'; $('tab-fil-tablet').value=String(id);
  loadTabletsPlanta();
}

const BDJ_EST={Pendiente:'ba',Procesando:'ba',Procesado:'bg',Error:'br',Descartado:'bk'};
async function loadBandejaPlanta(){
  $('tab-fil-bandeja').style.display='';
  const q=[];
  if($('tab-fil-estado').value) q.push('estado='+encodeURIComponent($('tab-fil-estado').value));
  if($('tab-fil-tablet').value) q.push('tablet_id='+encodeURIComponent($('tab-fil-tablet').value));
  const data=await api('/api/planta/bandeja'+(q.length?'?'+q.join('&'):''));
  if(!data||!Array.isArray(data.registros)){ $('tab-list').innerHTML='<div class="em">'+audEsc((data&&data.error)||'No se pudo leer la bandeja.')+'</div>'; return; }
  _bandeja=data.registros;
  const tot=data.totales||{};
  const espLote=tot['Esperando lote']||0;
  $('tab-resumen').textContent=(tot.Error?tot.Error+' con error · ':'')+(espLote?espLote+' esperando lote · ':'')+((tot.Pendiente||0)+(tot.Procesando||0)-espLote)+' pendientes · '+(tot.Procesado||0)+' procesados';
  if(!_bandeja.length){ $('tab-list').innerHTML='<div class="em">No hay registros con ese filtro.</div>'; return; }
  let h='<table><tr><th>Cargado</th><th>Tablet</th><th>Operario</th><th>OT · operación</th><th style="text-align:right">OK</th><th style="text-align:right">NO OK</th><th style="text-align:right">Min</th><th>Estado</th><th>Resultado</th><th></th></tr>';
  _bandeja.forEach(function(r){
    const d=r.datos||{};
    let res='—';
    if(r.estado==='Procesado') res=audEsc(r.novedad_numero||d.tnp_numero||'');
    else if(r.error) res='<span style="color:#791F1F;font-size:12px">'+audEsc(r.error)+'</span>';
    let est=r.estado, estCls=BDJ_EST[r.estado]||'bk';
    if(r.estado==='Pendiente'&&r.espera==='lote'){ est='Esperando lote'; res='<span style="font-size:12px">Se carga sola cuando se asigne lote a la OT (Órdenes de trabajo → Lotes asignados).</span>'; }
    else if(r.estado==='Pendiente'&&r.intentos>0){ est='Reintento '+r.intentos; }
    if(r.tipo==='parada') res='<b>Parada:</b> '+audEsc(d.motivo||'')+(r.estado==='Procesado'?' · '+audEsc(d.tnp_numero||''):(r.error?' · <span style="color:#791F1F">'+audEsc(r.error)+'</span>':''));
    if(r.estado==='Descartado'&&r.resuelto_por_nombre) res+=' <span style="font-size:11px;color:var(--color-text-secondary)">('+audEsc(r.resuelto_por_nombre)+')</span>';
    h+='<tr>'
      +'<td style="white-space:nowrap">'+audEsc(fmtDH(r.hora_operario||r.recibido))+'</td>'
      +'<td>'+audEsc(r.tablet_nombre)+'</td>'
      +'<td>'+audEsc(r.empleado)+'</td>'
      +'<td>'+audEsc(r.operacion)+'</td>'
      +'<td style="text-align:right">'+fN(d.cantidad_ok||0)+'</td>'
      +'<td style="text-align:right">'+fN(d.cantidad_nok||0)+'</td>'
      +'<td style="text-align:right">'+fN(d.tiempo_min||d.minutos||0)+'</td>'
      +'<td><span class="b '+estCls+'">'+audEsc(est)+'</span></td>'
      +'<td style="max-width:340px">'+res+'</td>'
      +'<td style="white-space:nowrap">'+(r.estado==='Error'||(r.estado==='Pendiente'&&(r.espera||r.intentos>0))?'<button class="btn" onclick="bdjAbrir('+r.id+')">Corregir</button>':'')+'</td>'
      +'</tr>';
  });
  $('tab-list').innerHTML=h+'</table>';
}

async function tabAbrir(id){
  const t=id?_tablets.find(function(x){return x.id===id;}):null;
  const maqs=await api('/api/maquinas');
  $('tab-maq').innerHTML='<option value="">Elegí la máquina</option>'+(Array.isArray(maqs)?maqs:[]).map(function(m){
    return '<option value="'+m.id+'">'+audEsc((m.codigo||'')+' · '+(m.nombre||''))+'</option>';}).join('');
  $('tab-id').value=t?t.id:'';
  $('tab-maq').value=t?String(t.maquina_id):'';
  $('tab-nombre').value=t?t.nombre:'';
  $('tab-activa').checked=t?!!t.activa:true;
  $('tab-activa-wrap').style.display=t?'':'none';
  $('tab-title').textContent=t?'Editar '+t.nombre:'Nueva tablet';
  openMo('mo-tablet');
}

async function tabGuardar(){
  const id=$('tab-id').value;
  const body={maquina_id:$('tab-maq').value, nombre:$('tab-nombre').value.trim(), activa:$('tab-activa').checked};
  if(!body.maquina_id){ toast('Elegí la máquina','e'); return; }
  const btn=$('tab-guardar'); btn.disabled=true;
  try{
    const res=await api(id?'/api/planta/tablets/'+id:'/api/planta/tablets',{method:id?'PUT':'POST',body:JSON.stringify(body)});
    if(!res||res.error){ toast((res&&res.error)||'No se pudo guardar','e'); return; }
    closeMo('mo-tablet');
    await loadTabletsPlanta();
    if(!id&&res.id){ toast('Tablet creada'); tabVerEnlace(res.id); } else toast('Tablet actualizada');
  }finally{ btn.disabled=false; }
}

function tabVerEnlace(id){
  const t=_tablets.find(function(x){return x.id===id;}); if(!t) return;
  $('tab-enl-title').textContent='Enlace de '+t.nombre;
  $('tab-enl').value=t.enlace;
  openMo('mo-tablet-enlace');
  setTimeout(function(){ $('tab-enl').select(); },50);
}

function tabCopiarEnlace(){
  const i=$('tab-enl'); i.select();
  const listo=function(){ toast('Enlace copiado'); };
  if(navigator.clipboard&&window.isSecureContext){ navigator.clipboard.writeText(i.value).then(listo,function(){ document.execCommand('copy'); listo(); }); }
  else{ document.execCommand('copy'); listo(); }
}

async function tabNuevoToken(id){
  const t=_tablets.find(function(x){return x.id===id;}); if(!t) return;
  if(!await confirmar('¿Generar un enlace nuevo para '+t.nombre+'? La tablet que usa el enlace actual deja de poder cargar hasta que abras el nuevo en ella.')) return;
  const res=await api('/api/planta/tablets/'+id+'/token',{method:'POST'});
  if(!res||res.error){ toast((res&&res.error)||'No se pudo','e'); return; }
  await loadTabletsPlanta();
  tabVerEnlace(id);
}

async function bdjAbrir(id){
  const r=_bandeja.find(function(x){return x.id===id;}); if(!r) return;
  const d=r.datos||{};
  $('bdj-id').value=id;
  $('bdj-error').textContent=r.error||'';
  $('bdj-ok').value=d.cantidad_ok||0; $('bdj-nok').value=d.cantidad_nok||0;
  $('bdj-min').value=d.tiempo_min||0; $('bdj-pausa').value=d.tiempo_perdido_min||0;
  // La operación y el operario actuales primero; después las operaciones
  // abiertas (el mismo listado que ve la tablet) y los empleados activos.
  $('bdj-op').innerHTML='<option value="'+(d.orden_operacion_id||'')+'">'+audEsc(r.operacion)+' (actual)</option>';
  $('bdj-emp').innerHTML='<option value="'+(d.empleado_id||'')+'">'+audEsc(r.empleado)+' (actual)</option>';
  openMo('mo-bandeja');
  const [ops, emps]=await Promise.all([api('/api/planta/operaciones'), api('/api/empleados')]);
  if(Array.isArray(emps)){
    $('bdj-emp').innerHTML+=emps.filter(function(e){return e.activo&&e.id!==d.empleado_id;}).map(function(e){
      return '<option value="'+e.id+'">'+audEsc(((e.apellido||'')+' '+(e.nombre||'')).trim())+'</option>';}).join('');
  }
  if(Array.isArray(ops)){
    $('bdj-op').innerHTML+=ops.filter(function(o){return o.id!==d.orden_operacion_id;}).map(function(o){
      return '<option value="'+o.id+'">'+audEsc(o.ot_numero+' · '+o.paso+' '+o.nombre)+'</option>';}).join('');
  }
}

async function bdjReprocesar(){
  const id=$('bdj-id').value;
  const datos={cantidad_ok:$('bdj-ok').value, cantidad_nok:$('bdj-nok').value, tiempo_min:$('bdj-min').value,
               tiempo_perdido_min:$('bdj-pausa').value, orden_operacion_id:$('bdj-op').value, empleado_id:$('bdj-emp').value};
  const btn=$('bdj-guardar'); btn.disabled=true;
  try{
    const res=await api('/api/planta/bandeja/'+id+'/reprocesar',{method:'POST',body:JSON.stringify({datos:datos})});
    if(!res||res.error){ toast((res&&res.error)||'No se pudo','e'); return; }
    closeMo('mo-bandeja'); toast('Vuelve a procesarse');
    setTimeout(loadBandejaPlanta,1500);
  }finally{ btn.disabled=false; }
}

async function bdjDescartar(){
  const id=$('bdj-id').value;
  if(!await confirmar('¿Descartar este registro? No se va a cargar ninguna novedad con él.')) return;
  const res=await api('/api/planta/bandeja/'+id+'/descartar',{method:'POST'});
  if(!res||res.error){ toast((res&&res.error)||'No se pudo','e'); return; }
  closeMo('mo-bandeja'); toast('Registro descartado'); loadBandejaPlanta();
}


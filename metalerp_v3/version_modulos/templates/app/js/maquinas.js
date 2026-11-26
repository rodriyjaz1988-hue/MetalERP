// ── Maquinas ──────────────────────────────────────────────────────────────────
let maqV='listado';
// Selección por vista (igual que en Órdenes de trabajo: un clic selecciona la
// fila y el chip + el botón Editar del encabezado trabajan sobre ella).
let _maqSel={listado:null,mantenimiento:null,tickets:null};
let _maqRaw=[],_mantRaw=[],_tktRaw=[];
let _maqCache=new Map(),_mantCache=new Map(),_tktCache=new Map();
document.querySelectorAll('#maq-tabs .tab').forEach(t=>t.addEventListener('click',()=>{
  document.querySelectorAll('#maq-tabs .tab').forEach(x=>x.classList.remove('active'));
  t.classList.add('active');maqV=t.dataset.v;
  ['listado','mantenimiento','tickets'].forEach(v=>{
    $('mv-'+v).style.display=v===maqV?'block':'none';
    $('maq-fil-'+v).style.display=v===maqV?'':'none';
    $('maq-new-'+v).style.display=v===maqV?'contents':'none';
  });
  actualizarToolbarMaq();
  loadMaqView();
}));

function _maqCacheActual(){return maqV==='listado'?_maqCache:(maqV==='mantenimiento'?_mantCache:_tktCache);}
function selMaqRow(v,id){
  _maqSel[v]=id;
  if(v==='listado')renderMaq();else if(v==='mantenimiento')renderMant();else renderTkt();
}
function actualizarToolbarMaq(){
  const id=_maqSel[maqV];
  const r=id!=null?_maqCacheActual().get(id):null;
  const lbl=$('maq-sel-label');
  if(lbl)lbl.textContent=r?(maqV==='listado'?r.codigo:(maqV==='mantenimiento'?r.maquina_codigo:r.numero)):'–';
  const bt=$('maq-b-edit');if(bt)bt.disabled=!r;
  ['mant-b-hist','mant-b-real'].forEach(i=>{const b=$(i);if(b)b.disabled=!(r&&maqV==='mantenimiento');});
}
function maqSelAccion(a){
  const id=_maqSel[maqV];
  const r=id!=null?_maqCacheActual().get(id):null;
  if(!r){toast('Seleccioná '+(maqV==='listado'?'una máquina':(maqV==='mantenimiento'?'una tarea':'un ticket'))+' de la lista','w');return;}
  if(a==='edit'){
    if(maqV==='listado')editMaq(r);
    else if(maqV==='mantenimiento')editMant(r);
    else editTkt(r);
  }
}

function loadMaqView(){
  if(maqV==='listado')loadMaq();
  else if(maqV==='mantenimiento')loadMant();
  else loadTkt();
}

function sortMaqCodigo(list){
  return list.slice().sort((a,b)=>{
    const ca=(a.codigo||''), cb=(b.codigo||'');
    const ma=ca.match(/^([A-Za-z]*)(\d+)$/), mb=cb.match(/^([A-Za-z]*)(\d+)$/);
    if(ma&&mb){
      const pa=ma[1].toUpperCase(), pb=mb[1].toUpperCase();
      if(pa!==pb)return pa.localeCompare(pb);
      return parseInt(ma[2],10)-parseInt(mb[2],10);
    }
    return ca.localeCompare(cb,undefined,{numeric:true,sensitivity:'base'});
  });
}

async function loadMaq(){
  try{
    _maq=await api('/api/maquinas');
  }catch(e){
    $('maq-list').innerHTML='<div class="em">Error al cargar máquinas. Revisá la consola / el servidor.</div>';
    console.error(e);
    return;
  }
  _maq=sortMaqCodigo(_maq);
  _maqRaw=_maq;
  renderMaq();
}

function renderMaq(){
  const q=($('maq-search')?$('maq-search').value:'').toLowerCase().trim();
  let rows=_maqRaw;
  if(q)rows=rows.filter(r=>[r.codigo,r.nombre,r.marca,r.modelo,r.categoria_nombre,r.ubicacion].join(' ').toLowerCase().includes(q));
  _maqCache=new Map(rows.map(r=>[r.id,r]));
  if(_maqSel.listado!=null&&!_maqCache.has(_maqSel.listado))_maqSel.listado=null;
  if(!rows.length){
    $('maq-list').innerHTML='<div class="em">'+(_maqRaw.length?'Sin resultados para la búsqueda.':'No hay máquinas registradas. Usá «Nueva máquina» para cargar la primera.')+'</div>';
    actualizarToolbarMaq();return;
  }
  let h='<table><tr><th style="width:24px"></th><th>Código</th><th>Nombre</th><th>Categoría</th><th>Marca/Modelo</th><th>Ubicación</th><th>Horas</th><th>Reemplazos</th><th>Estado</th></tr>';
  rows.forEach(r=>{
    const sel=_maqSel.listado===r.id;
    const rep=r.reemplazos&&r.reemplazos.length?r.reemplazos.map(x=>`<span class="tag">${x.codigo}</span>`).join(''):'—';
    h+=`<tr class="${sel?'ot-sel':''}" style="cursor:pointer" onclick="selMaqRow('listado',${r.id})"><td><input type="radio" name="maq-sel" ${sel?'checked':''} onclick="event.stopPropagation();selMaqRow('listado',${r.id})"></td>
    <td><b>${r.codigo}</b></td><td>${dot(r.estado)}${r.nombre}</td>
    <td><span class="b bp">${r.categoria_nombre||'—'}</span></td>
    <td>${[r.marca,r.modelo].filter(Boolean).join(' ')||'—'}</td>
    <td>${r.ubicacion||'—'}</td><td title="Horas cargadas en la máquina más las de producción declaradas en ella">${fN(r.horas_actuales!=null?r.horas_actuales:(r.horas_uso||0),1)} hs</td><td>${rep}</td>
    <td>${sb(r.estado)}</td></tr>`;
  });
  $('maq-list').innerHTML=h+'</table>';
  actualizarToolbarMaq();
}

async function openMaq(){
  $('maq-id').value='';
  if(!_catM.length)_catM=await api('/api/categorias_maquina');
  if(!_maq.length)_maq=await api('/api/maquinas');
  await selLoad('maq-cat',[{id:'',nombre:'— Sin categoría —'},..._catM],null);
  const sr=$('maq-rep');sr.innerHTML='';
  _maq.forEach(m=>{const o=document.createElement('option');o.value=m.id;o.textContent=m.codigo+' — '+m.nombre;sr.appendChild(o);});
  $('maq-anio').value=new Date().getFullYear();
  openMo('mo-maq');
}

async function editMaq(r){
  $('maq-id').value=r.id;$('maq-cod').value=r.codigo;$('maq-nom').value=r.nombre;
  $('maq-mar').value=r.marca||'';$('maq-mod').value=r.modelo||'';
  $('maq-ser').value=r.numero_serie||'';$('maq-anio').value=r.anio||'';
  $('maq-ubi').value=r.ubicacion||'';$('maq-est').value=r.estado;
  $('maq-hs').value=r.horas_uso||0;$('maq-obs').value=r.obs||'';
  if(!_catM.length)_catM=await api('/api/categorias_maquina');
  if(!_maq.length)_maq=await api('/api/maquinas');
  await selLoad('maq-cat',[{id:'',nombre:'— Sin categoría —'},..._catM],r.categoria_id);
  const sr=$('maq-rep');sr.innerHTML='';
  const rids=(r.reemplazos||[]).map(x=>x.id);
  _maq.filter(m=>m.id!=r.id).forEach(m=>{
    const o=document.createElement('option');o.value=m.id;o.textContent=m.codigo+' — '+m.nombre;
    if(rids.includes(m.id))o.selected=true;sr.appendChild(o);
  });
  openMo('mo-maq');
}

async function saveMaq(){
  const id=$('maq-id').value;
  const reemplazos=[...$('maq-rep').selectedOptions].map(o=>parseInt(o.value));
  const body={codigo:$('maq-cod').value,nombre:$('maq-nom').value,categoria_id:$('maq-cat').value||null,
    marca:$('maq-mar').value,modelo:$('maq-mod').value,numero_serie:$('maq-ser').value,
    anio:$('maq-anio').value||null,ubicacion:$('maq-ubi').value,estado:$('maq-est').value,
    horas_uso:$('maq-hs').value||0,obs:$('maq-obs').value,reemplazos};
  if(!body.codigo||!body.nombre){toast('Código y nombre requeridos','w');return;}
  const res=await api(id?'/api/maquinas/'+id:'/api/maquinas',{method:id?'PUT':'POST',body:JSON.stringify(body)});
  if(res.ok){toast(id?'Máquina actualizada':'Máquina registrada');closeMo('mo-maq');$('maq-id').value='';_maq=[];loadMaq();}
  else toast(res.error||'Error','e');
}

// ── Mantenimiento ─────────────────────────────────────────────────────────────
async function loadMant(){
  _mantRaw=await api('/api/mantenimiento');
  renderMant();
  updateMantBadge();
}

const MANT_EST={'Vencido':['br','fila-vencida'],'Próximo':['ba','fila-por-vencer'],'Al día':['bg',''],'Por condición':['bp',''],'Sin programar':['bk','']};
function mantProximaTxt(r){
  const p=[];
  if(r.proxima_horas!=null)p.push(`a las ${fN(r.proxima_horas,1)} hs <span class="${r.faltan_horas<=0?'fecha-vencida':(r.estado==='Próximo'?'fecha-por-vencer':'')}">(${r.faltan_horas<=0?'pasada por '+fN(-r.faltan_horas,1):'faltan '+fN(r.faltan_horas,1)} hs)</span>`);
  if(r.proxima_fecha)p.push(`<span class="${r.faltan_dias<0?'fecha-vencida':(r.faltan_dias!=null&&r.faltan_dias<=7?'fecha-por-vencer':'')}">${fmtD(r.proxima_fecha)}</span>`);
  return p.join('<br>')||'—';
}
function renderMant(){
  const q=($('mant-search')?$('mant-search').value:'').toLowerCase().trim();
  let rows=_mantRaw;
  if(q)rows=rows.filter(r=>[r.maquina_codigo,r.maquina_nombre,r.tarea,r.responsable].join(' ').toLowerCase().includes(q));
  // Primero lo vencido, después lo próximo, después el resto.
  const ord={'Vencido':0,'Próximo':1};
  rows=rows.slice().sort((a,b)=>(ord[a.estado]??2)-(ord[b.estado]??2));
  _mantCache=new Map(rows.map(r=>[r.id,r]));
  if(_maqSel.mantenimiento!=null&&!_mantCache.has(_maqSel.mantenimiento))_maqSel.mantenimiento=null;
  if(!rows.length){
    $('mant-list').innerHTML='<div class="em">'+(_mantRaw.length?'Sin resultados para la búsqueda.':'No hay tareas de mantenimiento. Usá «Nueva tarea» para programar la primera.')+'</div>';
    actualizarToolbarMaq();return;
  }
  let h='<table><tr><th style="width:24px"></th><th>Máquina</th><th>Tarea</th><th>Frecuencia</th><th>Horas máquina</th><th>Última</th><th>Próxima</th><th>Responsable</th><th>Estado</th></tr>';
  rows.forEach(r=>{
    const sel=_maqSel.mantenimiento===r.id;
    const [bc,fc]=MANT_EST[r.estado]||['bk',''];
    const frec=r.tipo==='Por condicion'?'Por inspección':`Cada ${r.frecuencia_valor||'?'} ${r.frecuencia_tipo==='horas'?'hs de uso':(r.frecuencia_valor==1?({dias:'día',semanas:'semana',meses:'mes'}[r.frecuencia_tipo]||''):(r.frecuencia_tipo==='dias'?'días':(r.frecuencia_tipo||'')))}`;
    const ult=r.ultima_fecha||r.ultima_horas!=null?[r.ultima_fecha?fmtD(r.ultima_fecha):'',r.ultima_horas!=null&&r.frecuencia_tipo==='horas'?fN(r.ultima_horas,1)+' hs':''].filter(Boolean).join('<br>'):'—';
    h+=`<tr class="${sel?'ot-sel':''}${fc?' '+fc:''}" style="cursor:pointer" onclick="selMaqRow('mantenimiento',${r.id})" ondblclick="openMantReal(${r.id})"><td><input type="radio" name="mant-sel" ${sel?'checked':''} onclick="event.stopPropagation();selMaqRow('mantenimiento',${r.id})"></td>
    <td><b>${r.maquina_codigo}</b> ${r.maquina_nombre}</td><td>${r.tarea}${r.realizaciones?` <span class="tz-sub" title="Veces registradas">· ${r.realizaciones}×</span>`:''}</td>
    <td>${frec}</td><td>${fN(r.horas_actuales,1)} hs</td><td>${ult}</td><td>${mantProximaTxt(r)}</td>
    <td>${r.responsable||'—'}</td><td><span class="b ${bc}">${r.estado}</span></td></tr>`;
  });
  $('mant-list').innerHTML=h+'</table>';
  actualizarToolbarMaq();
}

function toggleFrec(v){
  $('mant-fg').style.display=v==='Por condicion'?'none':'grid';
  $('mant-ulh-fg').style.display=$('mant-ftp').value==='horas'?'':'none';
}
function _mantHsAct(){
  const m=_maq.find(x=>x.id==$('mant-maq').value);
  $('mant-hs-act').textContent=m?'La máquina tiene hoy '+fN(m.horas_actuales!=null?m.horas_actuales:(m.horas_uso||0),1)+' hs de uso.':'';
}

async function openMant(){
  $('mant-id').value='';
  ['mant-tar','mant-res','mant-ult','mant-prx','mant-fvl','mant-obs','mant-ulh'].forEach(i=>$(i).value='');
  $('mant-tip').value='Frecuencia fija';$('mant-ftp').value='horas';
  _maq=await api('/api/maquinas');
  await selLoad('mant-maq',_maq.map(m=>({...m,nombre:m.codigo+' — '+m.nombre})),null,'— Seleccionar máquina —');
  $('mant-maq').onchange=_mantHsAct;_mantHsAct();
  toggleFrec('Frecuencia fija');
  openMo('mo-mant');
}

async function editMant(r){
  $('mant-id').value=r.id;$('mant-tar').value=r.tarea;$('mant-tip').value=r.tipo;
  $('mant-res').value=r.responsable||'';$('mant-ult').value=r.ultima_fecha||'';
  $('mant-prx').value=r.proxima_fecha||'';$('mant-ftp').value=r.frecuencia_tipo||'horas';
  $('mant-fvl').value=r.frecuencia_valor||'';$('mant-obs').value=r.obs||'';
  $('mant-ulh').value=r.ultima_horas!=null?r.ultima_horas:'';
  _maq=await api('/api/maquinas');
  await selLoad('mant-maq',_maq.map(m=>({...m,nombre:m.codigo+' — '+m.nombre})),r.maquina_id,'— Seleccionar máquina —');
  $('mant-maq').onchange=_mantHsAct;_mantHsAct();
  toggleFrec(r.tipo);
  openMo('mo-mant');
}

async function saveMant(){
  const id=$('mant-id').value;
  const body={maquina_id:$('mant-maq').value,tarea:$('mant-tar').value,tipo:$('mant-tip').value,
    frecuencia_tipo:$('mant-ftp').value,frecuencia_valor:$('mant-fvl').value||null,
    ultima_fecha:$('mant-ult').value,proxima_fecha:$('mant-prx').value,
    ultima_horas:$('mant-ftp').value==='horas'?$('mant-ulh').value:'',
    responsable:$('mant-res').value,obs:$('mant-obs').value};
  if(!body.maquina_id||!body.tarea){toast('Máquina y tarea requeridas','w');return;}
  if(body.tipo!=='Por condicion'&&!body.frecuencia_valor){toast('Indicá cada cuánto se hace la tarea','w');return;}
  const res=await api(id?'/api/mantenimiento/'+id:'/api/mantenimiento',{method:id?'PUT':'POST',body:JSON.stringify(body)});
  if(res.ok){toast(id?'Tarea actualizada':'Tarea creada');closeMo('mo-mant');$('mant-id').value='';loadMant();}
  else toast(res.error||'Error','e');
}

function mantSelAccion(a){
  const id=_maqSel.mantenimiento;
  if(id==null||!_mantCache.has(id)){toast('Seleccioná una tarea de la lista','w');return;}
  if(a==='real')openMantReal(id);else openMantHist(id);
}
function openMantReal(id){
  const r=_mantCache.get(id);if(!r)return;
  if($('mant-b-real').style.display==='none'){openMantHist(id);return;}
  $('mreal-id').value=id;
  $('mreal-info').innerHTML='<b>'+r.maquina_codigo+'</b> '+r.maquina_nombre+' · '+r.tarea
    +'<br>La máquina tiene hoy <b>'+fN(r.horas_actuales,1)+' hs</b> de uso.';
  $('mreal-fec').value=new Date().toLocaleDateString('sv');
  $('mreal-fec').max=$('mreal-fec').value;
  $('mreal-hs').value=r.horas_actuales;
  $('mreal-res').value=r.responsable||'';$('mreal-obs').value='';
  openMo('mo-mant-real');
}
async function saveMantReal(){
  const id=$('mreal-id').value;
  if(!$('mreal-fec').value){toast('Indicá la fecha','w');return;}
  const res=await api('/api/mantenimiento/'+id+'/realizar',{method:'POST',body:JSON.stringify({
    fecha:$('mreal-fec').value,horas:$('mreal-hs').value,responsable:$('mreal-res').value,obs:$('mreal-obs').value})});
  if(res.ok){toast('Realización registrada'+(res.proxima_fecha?' · próxima: '+fmtD(res.proxima_fecha):''));closeMo('mo-mant-real');loadMant();}
  else toast(res.error||'Error','e');
}
async function openMantHist(id){
  const r=_mantCache.get(id);if(!r)return;
  $('mhist-title').textContent='Historial · '+r.maquina_codigo+' · '+r.tarea;
  $('mhist-body').innerHTML='<div class="ld">Cargando...</div>';
  openMo('mo-mant-hist');
  const regs=await api('/api/mantenimiento/'+id+'/registros');
  if(!regs.length){$('mhist-body').innerHTML='<div class="em">Todavía no se registró ninguna realización de esta tarea.</div>';return;}
  let h='<table><tr><th>Fecha</th><th>Horas máquina</th><th>Responsable</th><th>Observaciones</th><th>Registró</th></tr>';
  regs.forEach(g=>{h+='<tr><td>'+fmtD(g.fecha)+'</td><td>'+(g.horas!=null?fN(g.horas,1)+' hs':'—')+'</td><td>'+_tz(g.responsable||'—')+'</td><td style="white-space:normal">'+_tz(g.obs||'—')+'</td><td>'+_tz(g.usuario_nombre||'—')+'</td></tr>';});
  $('mhist-body').innerHTML=h+'</table>';
}

// Aviso en el menú Máquinas: tareas de mantenimiento vencidas (rojo) o próximas (ámbar)
async function updateMantBadge(){
  try{
    const r=await api('/api/mantenimiento/alertas');
    const b=$('mant-badge');if(!b||!r||r.error)return;
    const n=(r.vencidas||0)+(r.proximas||0);
    if(n>0){
      b.textContent=n>99?'99+':n;b.style.display='flex';
      b.classList.toggle('ni-badge-a',!r.vencidas);
      b.title='Mantenimiento: '+(r.vencidas?r.vencidas+' vencida'+(r.vencidas>1?'s':''):'')+(r.vencidas&&r.proximas?', ':'')+(r.proximas?r.proximas+' próxima'+(r.proximas>1?'s':''):'');
    }else b.style.display='none';
  }catch(e){}
}
updateMantBadge();
setInterval(updateMantBadge,300000);

// ── Tickets ───────────────────────────────────────────────────────────────────
let tktF='';
document.querySelectorAll('#tkt-tabs .tab').forEach(t=>t.addEventListener('click',()=>{
  document.querySelectorAll('#tkt-tabs .tab').forEach(x=>x.classList.remove('active'));
  t.classList.add('active');tktF=t.dataset.e;loadTkt();
}));

async function loadTkt(){
  _tktRaw=await api('/api/tickets'+(tktF?'?estado='+encodeURIComponent(tktF):''));
  renderTkt();
}

function renderTkt(){
  const q=($('tkt-maq-search')?$('tkt-maq-search').value:'').toLowerCase().trim();
  const rows=q?_tktRaw.filter(function(r){
    return ((r.maquina_nombre||'')+' '+(r.maquina_codigo||'')).toLowerCase().includes(q);
  }):_tktRaw;
  _tktCache=new Map(rows.map(r=>[r.id,r]));
  if(_maqSel.tickets!=null&&!_tktCache.has(_maqSel.tickets))_maqSel.tickets=null;
  if(!rows.length){
    $('tkt-list').innerHTML='<div class="em">No hay tickets. Usá «Nuevo ticket» para reportar una falla de máquina.</div>';
    actualizarToolbarMaq();return;
  }
  let h='<table><tr><th style="width:24px"></th><th>Ticket</th><th>Máquina</th><th>Tipo</th><th>Descripción</th><th>Prioridad</th><th>Estado</th><th>Responsable</th><th>Tiempo de paro</th><th>Apertura</th><th>Cierre</th></tr>';
  rows.forEach(r=>{
    const sel=_maqSel.tickets===r.id;
    const timerHtml = r.estado==='Cerrado'
      ? `<span style="color:var(--tx2,#6b7280)">${r.horas_paro} hs</span>`
      : `<span class="tkt-live-timer" data-apertura="${r.fecha_apertura}" data-ajuste="${r.horas_ajuste||0}" style="font-family:monospace;font-weight:600;color:var(--primary,#2563eb)">calculando…</span>`;
    const desc=String(r.descripcion||'').replace(/"/g,'&quot;');
    h+=`<tr class="${sel?'ot-sel':''}" style="cursor:pointer" onclick="selMaqRow('tickets',${r.id})"><td><input type="radio" name="tkt-sel" ${sel?'checked':''} onclick="event.stopPropagation();selMaqRow('tickets',${r.id})"></td>
    <td><b>${r.numero}</b></td><td>${r.maquina_codigo} ${r.maquina_nombre}</td>
    <td><span class="b bk">${r.tipo}</span></td><td style="max-width:300px;overflow:hidden;text-overflow:ellipsis" title="${desc}">${r.descripcion}</td>
    <td>${pb(r.prioridad)}</td><td>${sb(r.estado)}</td>
    <td>${r.responsable||'—'}</td><td>${timerHtml}</td><td>${fmtDH(r.fecha_apertura)}</td><td>${fmtDH(r.fecha_cierre)}</td></tr>`;
  });
  $('tkt-list').innerHTML=h+'</table>';
  actualizarToolbarMaq();
  initLiveTimers();
}

// ── Contador de tiempo hábil ──────────────────────────────────────────────────
let _timerIntervalId=null;

function calcHorasHabiles(fechaAperturaStr){
  const apertura=new Date(fechaAperturaStr.replace(' ','T'));
  const ahora=new Date();
  if(isNaN(apertura)||ahora<=apertura)return 0;
  let totalMs=0;
  let cur=new Date(apertura);
  while(cur<ahora){
    const endOfDay=new Date(cur);
    endOfDay.setHours(23,59,59,999);
    const segmEnd=endOfDay<ahora?endOfDay:ahora;
    const dow=cur.getDay(); // 0=dom,6=sáb
    if(dow!==0&&dow!==6) totalMs+=(segmEnd-cur);
    cur=new Date(cur.setHours(0,0,0,0));
    cur.setDate(cur.getDate()+1);
  }
  return totalMs/3600000;
}

function parseDecimalComa(v){
  // Acepta tanto coma como punto como separador decimal (ej: "4,5" o "4.5")
  if(v===null||v===undefined||v==='')return NaN;
  return parseFloat(String(v).trim().replace(',','.'));
}

function fmtHorasHabiles(h){
  h=Math.max(0,h);
  if(h<1)return Math.round(h*60)+' min';
  const dias=Math.floor(h/24);
  const hrs=Math.floor(h%24);
  const min=Math.round((h%1)*60);
  if(dias>0)return `${dias}d ${hrs}h ${min}m`;
  return `${hrs}h ${min}m`;
}

function initLiveTimers(){
  if(_timerIntervalId)clearInterval(_timerIntervalId);
  function tick(){
    document.querySelectorAll('.tkt-live-timer').forEach(el=>{
      const ap=el.dataset.apertura;
      if(!ap)return;
      const ajuste=Math.abs(parseFloat(el.dataset.ajuste)||0);
      el.textContent=fmtHorasHabiles(calcHorasHabiles(ap)+ajuste);
    });
    // Modal timer
    const mv=$('tkt-timer-val');
    const ml=$('tkt-timer-label');
    if(mv&&ml&&mv.dataset.apertura){
      const est=$('tkt-est')?.value;
      if(est&&est!=='Cerrado'){
        const ajuste=Math.abs(parseDecimalComa($('tkt-ajuste')?.value)||0);
        mv.textContent=fmtHorasHabiles(calcHorasHabiles(mv.dataset.apertura)+ajuste);
        ml.textContent='hábiles transcurridos'+(ajuste!==0?' (ajustado)':'');
      }
    }
  }
  tick();
  _timerIntervalId=setInterval(tick,30000);
}

// ── Buscador de empleado en campo Responsable de tickets ───────────────────
function filtrarTktResponsables(){
  const q=($('tkt-res').value||'').toLowerCase().trim();
  const cont=$('tkt-res-results');
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
      $('tkt-res').value=e.apellido+', '+e.nombre;
      cont.style.display='none';
      cont.innerHTML='';
    };
    cont.appendChild(item);
  });
  cont.style.display='block';
}

async function openTkt(){
  $('tkt-id').value='';
  const mv=$('tkt-timer-val');const ml=$('tkt-timer-label');
  if(mv){mv.textContent='El contador arrancará al guardar';mv.dataset.apertura='';mv.dataset.ajuste='0';if(ml)ml.textContent='';}
  if($('tkt-ajuste'))$('tkt-ajuste').value='';
  if($('tkt-ajuste-box'))$('tkt-ajuste-box').style.display='none';
  if(!_maq.length)_maq=await api('/api/maquinas');
  await selLoad('tkt-maq',_maq.map(m=>({...m,nombre:m.codigo+' — '+m.nombre+' ('+m.estado+')'})),null,'— Seleccionar máquina —');
  if(!_emp.length)_emp=await api('/api/empleados');
  openMo('mo-tkt');
}

async function editTkt(r){
  $('tkt-id').value=r.id;$('tkt-des').value=r.descripcion;$('tkt-tip').value=r.tipo;
  $('tkt-pri').value=r.prioridad;$('tkt-est').value=r.estado;
  $('tkt-res').value=r.responsable||'';
  $('tkt-cos').value=r.costo||0;$('tkt-sol').value=r.solucion||'';
  $('tkt-ajuste').value=Math.abs(r.horas_ajuste||0)||'';
  if($('tkt-ajuste-box'))$('tkt-ajuste-box').style.display='';
  // Mostrar contador de tiempo de paro
  const mv=$('tkt-timer-val');const ml=$('tkt-timer-label');
  if(mv){
    if(r.estado==='Cerrado'){
      mv.dataset.apertura='';mv.dataset.ajuste='0';
      mv.textContent=r.horas_paro+' hs';
      if(ml)ml.textContent='(ticket cerrado)';
    } else {
      mv.dataset.apertura=r.fecha_apertura||'';
      mv.dataset.ajuste=Math.abs(r.horas_ajuste||0);
      const ajuste=Math.abs(parseFloat(r.horas_ajuste||0));
      mv.textContent=fmtHorasHabiles(calcHorasHabiles(r.fecha_apertura)+ajuste);
      if(ml)ml.textContent='hábiles transcurridos'+(ajuste!==0?' (ajustado)':'');
    }
  }
  if(!_maq.length)_maq=await api('/api/maquinas');
  await selLoad('tkt-maq',_maq.map(m=>({...m,nombre:m.codigo+' — '+m.nombre})),r.maquina_id,'— Seleccionar máquina —');
  if(!_emp.length)_emp=await api('/api/empleados');
  // Actualizar contador cuando cambia el ajuste
  $('tkt-ajuste').oninput=function(){
    this.value=this.value.replace(/[^0-9.,]/g,'');
    const mv=$('tkt-timer-val');const ml=$('tkt-timer-label');
    if(!mv||!mv.dataset.apertura)return;
    const ajuste=Math.abs(parseDecimalComa(this.value)||0);
    mv.dataset.ajuste=ajuste;
    mv.textContent=fmtHorasHabiles(calcHorasHabiles(mv.dataset.apertura)+ajuste);
    if(ml)ml.textContent='hábiles transcurridos'+(ajuste!==0?' (ajustado)':'');
  };
  openMo('mo-tkt');
}

async function saveTkt(){
  const id=$('tkt-id').value;
  const body={maquina_id:$('tkt-maq').value,descripcion:$('tkt-des').value,tipo:$('tkt-tip').value,
    prioridad:$('tkt-pri').value,estado:$('tkt-est').value,responsable:$('tkt-res').value,
    costo:$('tkt-cos').value||0,solucion:$('tkt-sol').value,
    horas_ajuste:Math.abs(parseDecimalComa($('tkt-ajuste').value)||0)};
  if(!body.maquina_id||!body.descripcion){toast('Máquina y descripción requeridas','w');return;}
  const res=await api(id?'/api/tickets/'+id:'/api/tickets',{method:id?'PUT':'POST',body:JSON.stringify(body)});
  if(res.ok){toast(id?'Ticket actualizado':'Ticket '+res.numero+' creado');closeMo('mo-tkt');$('tkt-id').value='';_maq=[];loadTkt();}
  else toast(res.error||'Error','e');
}


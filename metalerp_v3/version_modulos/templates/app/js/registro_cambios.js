// ── Registro de cambios del sistema (solo admin) ─────────────────────────────
// Historial de los cambios de código cargado a mano. Obligatorios: fecha y
// descripción. Se trae todo de una vez y se filtra acá (son pocas filas).
const CAM_NOMBRE={{ nombre|tojson }};
let _cambios=[];

function _camTexto(r){
  return [r.descripcion,r.tipo,r.modulo,r.detalle,r.motivo,r.objetivo,r.archivos,r.autor,r.referencia]
    .filter(Boolean).join(' ').toLowerCase();
}

function _camLlenarSelect(id, valores, etiquetaTodos){
  const sel=$(id); if(!sel) return;
  const actual=sel.value;
  sel.innerHTML='<option value="">'+etiquetaTodos+'</option>'
    +valores.map(function(v){return '<option value="'+audEsc(v)+'">'+audEsc(v)+'</option>';}).join('');
  sel.value=valores.indexOf(actual)>=0?actual:'';
}

async function loadRegistroCambios(){
  $('cam-list').innerHTML='<div class="ld">Cargando...</div>';
  const data=await api('/api/registro-cambios');
  if(!Array.isArray(data)){
    $('cam-list').innerHTML='<div class="em">'+audEsc((data&&data.error)||'No se pudo leer el registro.')+'</div>';
    return;
  }
  _cambios=data;
  const unicos=function(c){
    return Array.from(new Set(_cambios.map(function(r){return (r[c]||'').trim();}).filter(Boolean)))
      .sort(function(a,b){return a.localeCompare(b,'es');});
  };
  _camLlenarSelect('cam-tipo-fil', unicos('tipo'), 'Todos los tipos');
  _camLlenarSelect('cam-modulo-fil', unicos('modulo'), 'Todos los módulos');
  $('cam-modulos').innerHTML=unicos('modulo').map(function(v){return '<option value="'+audEsc(v)+'">';}).join('');
  renderCambios();
}

function clearFiltrosCambios(){
  ['cam-desde','cam-hasta','cam-q','cam-tipo-fil','cam-modulo-fil'].forEach(function(i){const e=$(i);if(e)e.value='';});
  renderCambios();
}

function renderCambios(){
  const desde=$('cam-desde').value, hasta=$('cam-hasta').value;
  const tipo=$('cam-tipo-fil').value, modulo=$('cam-modulo-fil').value;
  const palabras=($('cam-q').value||'').toLowerCase().split(/\s+/).filter(Boolean);
  const filas=_cambios.filter(function(r){
    if(desde&&r.fecha<desde) return false;
    if(hasta&&r.fecha>hasta) return false;
    if(tipo&&(r.tipo||'').trim()!==tipo) return false;
    if(modulo&&(r.modulo||'').trim()!==modulo) return false;
    if(palabras.length){ const t=_camTexto(r); if(!palabras.every(function(p){return t.indexOf(p)>=0;})) return false; }
    return true;
  });
  $('cam-total').textContent=filas.length.toLocaleString('es-AR');
  if(!_cambios.length){
    $('cam-list').innerHTML='<div class="em">Todavía no hay cambios registrados. Usá "+ Nuevo cambio" para cargar el primero.</div>';
    return;
  }
  if(!filas.length){
    $('cam-list').innerHTML='<div class="em">No hay cambios que coincidan con el filtro.</div>';
    return;
  }
  const vacio='<span style="color:var(--color-text-tertiary)">—</span>';
  const corto=function(v,n){ v=v||''; return v.length>n?audEsc(v.slice(0,n))+'…':audEsc(v); };
  let h='<table><tr><th>Fecha</th><th>Tipo</th><th>Módulo</th><th>Descripción</th><th>Para qué</th><th>Quién</th></tr>';
  filas.forEach(function(r){
    h+='<tr style="cursor:pointer" title="Ver / editar el cambio" onclick="editarCambio('+r.id+')">'
      +'<td style="white-space:nowrap">'+audEsc(fmtD(r.fecha))+'</td>'
      +'<td>'+(r.tipo?'<span class="b bt">'+audEsc(r.tipo)+'</span>':vacio)+'</td>'
      +'<td>'+(r.modulo?audEsc(r.modulo):vacio)+'</td>'
      +'<td><b>'+audEsc(r.descripcion)+'</b>'
        +(r.detalle?'<div style="font-size:11px;color:var(--color-text-secondary);margin-top:2px">'+corto(r.detalle,140)+'</div>':'')+'</td>'
      +'<td style="font-size:12px">'+(r.objetivo?corto(r.objetivo,90):vacio)+'</td>'
      +'<td>'+(r.autor?audEsc(r.autor):vacio)+'</td>'
      +'</tr>';
  });
  $('cam-list').innerHTML=h+'</table>';
}

const CAM_CAMPOS={fecha:'cam-fecha',descripcion:'cam-desc',tipo:'cam-tipo',modulo:'cam-modulo',
  detalle:'cam-detalle',motivo:'cam-motivo',objetivo:'cam-objetivo',archivos:'cam-archivos',
  autor:'cam-autor',referencia:'cam-ref'};

function _camAbrir(r){
  $('cam-id').value=r?r.id:'';
  Object.keys(CAM_CAMPOS).forEach(function(c){ $(CAM_CAMPOS[c]).value=(r&&r[c])||''; });
  if(!r){
    const d=new Date();
    $('cam-fecha').value=d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0');
    $('cam-autor').value=CAM_NOMBRE||'';
  }
  $('cam-title').textContent=r?'Cambio del '+fmtD(r.fecha):'Nuevo cambio';
  $('cam-borrar').style.display=r?'':'none';
  $('cam-meta').textContent=r
    ? 'Cargado el '+fmtDH(r.creado_en)+(r.creado_por_nombre?' por '+r.creado_por_nombre:'')
      +(r.actualizado_en?' · última edición '+fmtDH(r.actualizado_en):'')
    : 'Solo la fecha y la descripción son obligatorias.';
  openMo('mo-cambio');
  setTimeout(function(){ $('cam-desc').focus(); },50);
}

function nuevoCambio(){ _camAbrir(null); }
function editarCambio(id){
  const r=_cambios.find(function(x){return x.id===id;});
  if(r) _camAbrir(r);
}

async function guardarCambio(){
  const body={};
  Object.keys(CAM_CAMPOS).forEach(function(c){ body[c]=$(CAM_CAMPOS[c]).value.trim(); });
  if(!body.fecha){ toast('Falta la fecha','e'); $('cam-fecha').focus(); return; }
  if(!body.descripcion){ toast('Falta la descripción','e'); $('cam-desc').focus(); return; }
  const id=$('cam-id').value;
  const btn=$('cam-guardar'); btn.disabled=true;
  try{
    const res=await api(id?'/api/registro-cambios/'+id:'/api/registro-cambios',
      {method:id?'PUT':'POST',body:JSON.stringify(body)});
    if(!res||res.error){ toast((res&&res.error)||'No se pudo guardar','e'); return; }
    closeMo('mo-cambio');
    toast(id?'Cambio actualizado':'Cambio registrado');
    loadRegistroCambios();
  }catch(e){
    toast('No se pudo guardar (error de conexión)','e');
  }finally{ btn.disabled=false; }
}

async function borrarCambio(){
  const id=$('cam-id').value; if(!id) return;
  if(!await confirmar('¿Eliminar este cambio del registro?')) return;
  closeMo('mo-cambio');
  _ultimoClicFila=null;
  const res=await apiBorrar('/api/registro-cambios/'+id,'Cambio eliminado');
  if(!res||res.error){ toast((res&&res.error)||'No se pudo eliminar','e'); }
  loadRegistroCambios();
}


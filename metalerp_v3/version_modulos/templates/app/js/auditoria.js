// ── Bitácora de auditoría (solo lectura, solo admin) ─────────────────────────
// La vista no escribe nada: solo consulta /api/auditoria. El servidor arma los
// asientos desde la capa de conexión, acá únicamente se filtran y se muestran.
let _audPag=1, _audPaginas=1, _audAccion='', _audTimerBuscar=null, _audOpcionesListas=false;

// La bitácora muestra datos cargados por los usuarios: hay que escaparlos
// antes de meterlos en el HTML.
function audEsc(v){
  if(v===null||v===undefined) return '';
  return String(v).replace(/[&<>"']/g, function(c){
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
  });
}

const AUD_ACCION_BADGE={alta:'bg', modificacion:'ba', baja:'br'};
const AUD_ACCION_LABEL={alta:'Alta', modificacion:'Modificación', baja:'Baja'};

document.querySelectorAll('#aud-tabs .tab').forEach(t=>t.addEventListener('click',()=>{
  document.querySelectorAll('#aud-tabs .tab').forEach(x=>x.classList.remove('active'));
  t.classList.add('active'); _audAccion=t.dataset.ac; loadAuditoria(1);
}));

function audBuscarDebounce(){
  clearTimeout(_audTimerBuscar);
  _audTimerBuscar=setTimeout(function(){loadAuditoria(1);},350);
}

function clearFiltrosAud(){
  ['aud-desde','aud-hasta','aud-q'].forEach(function(i){const e=$(i);if(e)e.value='';});
  ['aud-origen','aud-usuario','aud-entidad'].forEach(function(i){const e=$(i);if(e)e.value='';});
  document.querySelectorAll('#aud-tabs .tab').forEach(function(x){x.classList.remove('active');});
  const todas=document.querySelector('#aud-tabs .tab[data-ac=""]');
  if(todas) todas.classList.add('active');
  _audAccion='';
  loadAuditoria(1);
}

function audPagina(d){
  const n=_audPag+d;
  if(n<1||n>_audPaginas) return;
  loadAuditoria(n);
}

async function audCargarOpciones(){
  if(_audOpcionesListas) return;
  const o=await api('/api/auditoria/opciones');
  if(!o||o.error) return;
  const llenar=function(id, valores, etiquetaTodos){
    const sel=$(id); if(!sel) return;
    const actual=sel.value;
    sel.innerHTML='<option value="">'+etiquetaTodos+'</option>'
      +valores.map(function(v){return '<option value="'+audEsc(v)+'">'+audEsc(v)+'</option>';}).join('');
    sel.value=actual;
  };
  llenar('aud-usuario', o.usuarios||[], 'Todos los autores');
  llenar('aud-entidad', o.entidades||[], 'Todas las entidades');
  _audOpcionesListas=true;
}

async function loadAuditoria(pag){
  await audCargarOpciones();
  const pp=parseInt(($('aud-pp')||{}).value||50,10);
  const q=new URLSearchParams();
  q.set('pagina', pag||_audPag||1);
  q.set('por_pagina', pp);
  if(_audAccion) q.set('accion', _audAccion);
  [['desde','aud-desde'],['hasta','aud-hasta'],['origen','aud-origen'],
   ['usuario','aud-usuario'],['entidad','aud-entidad'],['q','aud-q']].forEach(function(par){
    const e=$(par[1]); if(e&&e.value) q.set(par[0], e.value);
  });
  $('aud-list').innerHTML='<div class="ld">Cargando...</div>';
  const data=await api('/api/auditoria?'+q.toString());
  if(!data||data.error){
    $('aud-list').innerHTML='<div class="em">'+audEsc((data&&data.error)||'No se pudo leer la bitácora.')+'</div>';
    return;
  }
  _audPag=data.pagina; _audPaginas=data.paginas;
  $('aud-total').textContent=data.total.toLocaleString('es-AR');

  if(!data.rows.length){
    $('aud-list').innerHTML='<div class="em">No hay movimientos que coincidan con el filtro.</div>';
  }else{
    let h='<table><tr><th>Fecha y hora</th><th>Origen</th><th>Autor</th><th>Entidad</th>'
      +'<th>Registro</th><th>Acción</th><th>Campos</th></tr>';
    data.rows.forEach(function(r){
      const campos=(r.campos||[]);
      const resumen=campos.length
        ? audEsc(campos.slice(0,4).join(', '))+(campos.length>4?' <span style="color:var(--color-text-secondary)">+'+(campos.length-4)+'</span>':'')
        : '<span style="color:var(--color-text-tertiary)">—</span>';
      h+='<tr style="cursor:pointer" title="Ver el detalle del cambio" onclick="verAuditoria('+r.id+')">'
        +'<td>'+audEsc(fmtDH(r.fecha))+'</td>'
        +'<td><span class="b '+(r.origen==='usuario'?'bb':'bk')+'">'+(r.origen==='usuario'?'Usuario':'Sistema')+'</span></td>'
        +'<td>'+audEsc(r.actor)+'</td>'
        +'<td><span class="b bt">'+audEsc(r.entidad)+'</span></td>'
        +'<td>'+(r.registro_id?('<b>'+audEsc(r.registro_id)+'</b>'):'<span style="color:var(--color-text-tertiary)">—</span>')+'</td>'
        +'<td><span class="b '+(AUD_ACCION_BADGE[r.accion]||'bk')+'">'+audEsc(AUD_ACCION_LABEL[r.accion]||r.accion)+'</span></td>'
        +'<td style="font-size:11px">'+resumen+'</td>'
        +'</tr>';
    });
    $('aud-list').innerHTML=h+'</table>';
  }

  const desde=data.total?((data.pagina-1)*data.por_pagina+1):0;
  const hasta=Math.min(data.pagina*data.por_pagina, data.total);
  $('aud-rango').textContent=data.total
    ? ('Mostrando '+desde.toLocaleString('es-AR')+'–'+hasta.toLocaleString('es-AR')
       +' de '+data.total.toLocaleString('es-AR')+' movimientos')
    : 'Sin movimientos';
  $('aud-pag-lbl').textContent='Página '+data.pagina+' de '+data.paginas;
  $('aud-prev').disabled=data.pagina<=1;
  $('aud-next').disabled=data.pagina>=data.paginas;
}

function audValor(v){
  if(v===null||v===undefined||v==='') return '<span style="color:var(--color-text-tertiary);font-style:italic">(vacío)</span>';
  return audEsc(v);
}

async function verAuditoria(id){
  $('aud-detalle').innerHTML='<div class="ld">Cargando...</div>';
  openMo('mo-auditoria');
  const d=await api('/api/auditoria/'+id);
  if(!d||d.error){
    $('aud-detalle').innerHTML='<div class="em">'+audEsc((d&&d.error)||'No se pudo leer el asiento.')+'</div>';
    return;
  }
  const dato=function(l,v){
    return '<div><div style="font-size:11px;color:var(--color-text-secondary)">'+l+'</div>'
      +'<div style="font-size:13px;font-weight:500">'+v+'</div></div>';
  };
  let h='<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;'
    +'background:var(--color-background-secondary);border-radius:8px;padding:11px 13px;margin-bottom:14px">'
    +dato('Fecha y hora', audEsc(fmtDH(d.fecha)))
    +dato('Origen', '<span class="b '+(d.origen==='usuario'?'bb':'bk')+'">'+(d.origen==='usuario'?'Usuario':'Sistema')+'</span>')
    +dato('Autor', audEsc(d.actor))
    +dato('Acción', '<span class="b '+(AUD_ACCION_BADGE[d.accion]||'bk')+'">'+audEsc(AUD_ACCION_LABEL[d.accion]||d.accion)+'</span>')
    +dato('Entidad', audEsc(d.entidad))
    +dato('Registro', d.registro_id?audEsc(d.registro_id):'—')
    +(d.ruta?dato('Origen técnico', audEsc(d.ruta)):'')
    +'</div>';

  const cambios=d.cambios||[];
  if(!cambios.length){
    h+='<div class="em">El asiento no registra valores de campos.</div>';
  }else{
    const esAlta=d.accion==='alta', esBaja=d.accion==='baja';
    h+='<table><tr><th>Campo</th><th>Valor anterior</th><th>Valor nuevo</th></tr>';
    cambios.forEach(function(c){
      h+='<tr>'
        +'<td style="font-weight:500">'+audEsc(c.campo)+'</td>'
        +'<td style="color:'+(esAlta?'var(--color-text-tertiary)':'#A32D2D')+'">'+(esAlta?'—':audValor(c.antes))+'</td>'
        +'<td style="color:'+(esBaja?'var(--color-text-tertiary)':'#3B6D11')+'">'+(esBaja?'—':audValor(c.despues))+'</td>'
        +'</tr>';
    });
    h+='</table>';
  }
  $('aud-detalle').innerHTML=h;
}


// ── Lotes ─────────────────────────────────────────────────────────────────────
let _lotesData=[];

// ── Cajones (pestaña de Lotes) ──────────────────────────────────────────────
let _lotesTab='lotes', _caj=[], _cajSel=null;
// Cada sección tiene sus pestañas debajo del encabezado (como Presupuestos).
document.querySelectorAll('.lote-tabs .tab').forEach(function(t){
  t.addEventListener('click',function(){lotesTab(t.dataset.t);});
});
function lotesTab(t){
  _lotesTab=t;
  document.querySelectorAll('.lote-tabs .tab').forEach(function(x){x.classList.toggle('active',x.dataset.t===t);});
  $('lote-sec-lotes').style.display=t==='lotes'?'':'none';
  $('lote-sec-cajones').style.display=t==='cajones'?'':'none';
  if(t==='cajones') loadCajones();
}
function cajBadge(e){
  const m={'En proceso':'bb','En espera':'ba',Liberado:'bg',Rechazado:'br',Baja:'bk'};
  return '<span class="b '+(m[e]||'bk')+'">'+schEsc(e)+'</span>';
}
function filtrarCajLote(loteId, numero){
  $('caj-lote-fil').value=loteId;
  const chip=$('caj-lote-chip'); chip.textContent='Lote '+numero+' ×'; chip.style.display='';
  lotesTab('cajones');
}
function clearCajLote(){
  $('caj-lote-fil').value=''; $('caj-lote-chip').style.display='none';
  loadCajones();
}
function clearCajFiltros(){
  $('caj-buscar').value='';
  clearCajLote();
}
async function loadCajones(){
  const p=[];
  const b=($('caj-buscar').value||'').trim(); if(b) p.push('buscar='+encodeURIComponent(b));
  const l=$('caj-lote-fil').value; if(l) p.push('lote_id='+l);
  const rows=await api('/api/cajones'+(p.length?'?'+p.join('&'):''));
  _caj=Array.isArray(rows)?rows:[];
  renderCajones();
}
function _cajPend(c){ return Math.max(0,(c.terminadas||0)-(c.cantidad_liberada||0)-(c.cantidad_rechazada||0)); }
function renderCajones(){
  if(_cajSel && !_caj.some(function(c){return c.id===_cajSel;})) _cajSel=null;
  if(!_caj.length){
    const sinFiltro=!($('caj-buscar').value||'').trim()&&!$('caj-lote-fil').value;
    $('caj-list').innerHTML='<div class="em">'+(sinFiltro
      ?'Todavía no hay cajones. Se crean solos al cargar la novedad de la primera operación de una OT, o al guardar los bultos de una recepción.'
      :'No hay cajones para los filtros elegidos.')+'</div>';
    actualizarToolbarCaj(); return;
  }
  let h='<table><tr><th style="width:24px"></th><th>Cajón</th><th>OT</th><th>Producto</th><th>Lote</th>'
    +'<th>Piezas</th><th>Terminadas</th><th style="color:#2e7d32">Liberadas</th><th style="color:#c62828">Rechazadas</th>'
    +'<th>Pendiente Calidad</th><th>Remitidas</th><th>Creado</th></tr>';
  _caj.forEach(function(c){
    h+='<tr class="'+(_cajSel===c.id?'ot-sel':'')+'" style="cursor:pointer" title="Estado: '+schEsc(c.estado)+' · doble clic para ver el detalle" onclick="selCaj('+c.id+')" ondblclick="openCajon('+c.id+')">'
      +'<td><input type="radio" name="caj-sel"'+(_cajSel===c.id?' checked':'')+' onclick="event.stopPropagation();selCaj('+c.id+')"></td>'
      +'<td><b>'+schEsc(c.numero)+'</b></td>'
      +'<td>'+(c.orden_id?schEsc(c.ot_numero||'—'):'<span style="color:var(--color-text-secondary)" title="Bulto de una recepción de compra">Recepción</span>')+(c.ot_origen_numero&&c.ot_origen_numero!==c.ot_numero?' <span style="font-size:11px;color:var(--color-text-secondary)">(de '+schEsc(c.ot_origen_numero)+')</span>':'')+'</td>'
      +'<td>'+schEsc(c.producto_codigo||'')+'</td><td>'+schEsc(c.lote_numero||'—')+'</td>'
      +'<td>'+fN(c.cantidad)+' / '+c.capacidad+'</td><td>'+fN(c.terminadas||0)+'</td>'
      +'<td style="color:#2e7d32;font-weight:600">'+fN(c.cantidad_liberada||0)+'</td>'
      +'<td style="color:#c62828;font-weight:600">'+fN(c.cantidad_rechazada||0)+'</td>'
      +'<td'+(_cajPend(c)>0?' style="color:#E65100;font-weight:600" title="Piezas terminadas esperando decisión de Calidad"':'')+'>'+_cajPend(c)+'</td><td>'+fN(c.cantidad_remitida||0)+'</td><td>'+fmtD(c.creado)+'</td></tr>';
  });
  $('caj-list').innerHTML=h+'</table>';
  actualizarToolbarCaj();
}
function selCaj(id){ _cajSel=id; renderCajones(); }
function actualizarToolbarCaj(){
  const c=_cajSel?_caj.find(function(x){return x.id===_cajSel;}):null;
  $('caj-sel-label').textContent=c?c.numero:'–';
  $('caj-b-ver').disabled=!c;
  $('caj-b-ver').title=c?'Trazabilidad del cajón seleccionado':'Seleccioná un cajón de la lista';
  const bc=$('caj-b-cal'); bc.style.display=(ROL==='admin'||ROL==='almacen')?'':'none';
  bc.disabled=!c||['En espera','Baja'].includes(c.estado)||!(c.terminadas>0);
  // El título dice por qué un botón está deshabilitado
  bc.title=!c?'Seleccioná un cajón de la lista'
    :!c.orden_id?'Bulto de una recepción: se libera o rechaza el lote completo y los bultos se actualizan solos'
    :c.estado==='En espera'?'El cajón está en espera (su OT se canceló): pasalo a otra OT primero'
    :c.estado==='Baja'?'El cajón está dado de baja'
    :!(c.terminadas>0)?'Todavía no hay piezas terminadas por la última operación'
    :'Liberar o rechazar piezas del cajón';
  const enEspera=c&&c.estado==='En espera';
  const motivoEspera=!c?'Seleccioná un cajón de la lista':'Solo para cajones en espera (de una OT cancelada)';
  const bt=$('caj-b-transf'); bt.style.display=(ROL==='admin'||ROL==='operario')?'':'none';
  bt.disabled=!enEspera;
  bt.title=enEspera?'Pasar el cajón en espera a otra OT del mismo producto':motivoEspera;
  const bb=$('caj-b-baja'); bb.style.display=ROL==='admin'?'':'none';
  bb.disabled=!enEspera;
  bb.title=enEspera?'Dar de baja el cajón en espera':motivoEspera;
}
function cajSelAccion(a){
  const c=_cajSel?_caj.find(function(x){return x.id===_cajSel;}):null;
  if(!c){toast('Seleccioná un cajón de la lista','w');return;}
  if(a==='ver') openCajon(c.id);
  else if(a==='calidad'){ if(c.orden_id) openCajCal(c); else openLiberacion(c.lote_id); }
  else if(a==='transferir') openCajTransf(c);
  else if(a==='baja') bajaCajon(c);
}
async function openCajon(id){
  $('cajon-body').innerHTML='<div class="ld">Cargando...</div>';
  openMo('mo-cajon');
  const c=await api('/api/cajones/'+id);
  if(!c||c.error){$('cajon-body').innerHTML='<div class="em">'+schEsc((c&&c.error)||'Error')+'</div>';return;}
  $('cajon-title').textContent='Cajón '+c.numero;
  const e=function(v){return schEsc(v==null||v===''?'—':v);};
  const tabla=function(cab, filas){
    if(!filas.length) return '<div class="em" style="padding:8px 0">Sin datos.</div>';
    return '<table><tr>'+cab.map(function(x){return '<th>'+x+'</th>';}).join('')+'</tr>'
      +filas.map(function(f){return '<tr>'+f.map(function(x){return '<td>'+x+'</td>';}).join('')+'</tr>';}).join('')+'</table>';
  };
  // Cada bloque va en su propia tarjeta con título y borde, para separar la información
  const sec=function(t, cuerpo){
    return '<div style="border:1px solid var(--color-border-tertiary);border-radius:8px;margin-top:12px;overflow:hidden">'
      +'<div style="font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.04em;color:var(--color-text-secondary);background:var(--color-background-secondary);padding:7px 12px;border-bottom:1px solid var(--color-border-tertiary)">'+t+'</div>'
      +'<div style="padding:6px 12px 8px">'+cuerpo+'</div></div>';
  };
  const dato=function(lbl, val, color){
    return '<div style="padding:8px 12px;border-right:1px solid var(--color-border-tertiary);border-bottom:1px solid var(--color-border-tertiary)">'
      +'<div style="font-size:10px;text-transform:uppercase;letter-spacing:.04em;color:var(--color-text-secondary)">'+lbl+'</div>'
      +'<div style="font-size:13px;font-weight:600;margin-top:2px'+(color?';color:'+color:'')+'">'+val+'</div></div>';
  };
  const grilla=function(items){
    return '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));border-top:1px solid var(--color-border-tertiary);border-left:1px solid var(--color-border-tertiary);border-radius:6px;overflow:hidden;margin:4px 0">'+items.join('')+'</div>';
  };
  let h='<div style="display:flex;align-items:center;gap:8px;margin-bottom:2px"><b style="font-size:15px">'+e(c.numero)+'</b> '+cajBadge(c.estado)+'</div>';
  h+=sec('Datos del cajón', grilla([
    dato('OT', e(c.ot_numero)+(c.ot_origen_numero&&c.ot_origen_numero!==c.ot_numero?' <span style="font-weight:400;font-size:11px">(empezó en '+e(c.ot_origen_numero)+')</span>':'')),
    dato('Lote', e(c.lote_numero)),
    dato('Producto', e(c.producto_codigo)+' — '+e(c.producto_nombre))
  ]));
  h+=sec('Piezas', grilla([
    dato('En el cajón', c.cantidad+' <span style="font-weight:400;font-size:11px">de '+c.capacidad+'</span>'),
    dato('Terminadas', c.terminadas||0),
    dato('Liberadas', c.cantidad_liberada||0, '#2e7d32'),
    dato('Rechazadas', c.cantidad_rechazada||0, '#c62828'),
    dato('Remitidas', c.cantidad_remitida||0)
  ]));
  h+=sec('Piezas por paso', tabla(['Paso','Piezas'], Object.keys(c.por_paso||{}).map(function(k){return [e(k), c.por_paso[k]];})));
  h+=sec('Novedades', tabla(['Novedad','Fecha','OT','Operación','Operario','Máquina','Piezas en este cajón'],
    c.novedades.map(function(n){return [e(n.numero), fmtD(n.fecha), e(n.ot_numero), e(n.paso)+'. '+e(n.operacion), e(n.empleado_nombre), e(n.maquina_nombre), n.cantidad];})));
  if(c.tercerizadas.length) h+=sec('Operaciones tercerizadas', tabla(['OT','Operación','OTT','Piezas'],
    c.tercerizadas.map(function(t){return [e(t.ot_numero), e(t.paso)+'. '+e(t.operacion), e(t.ott_numero), t.cantidad];})));
  h+=sec('Lotes de material consumidos', tabla(['Novedad','Lote','Material','Cantidad'],
    c.materiales.map(function(m){return [e(m.novedad_numero), e(m.lote_numero), e(m.material_codigo)+' — '+e(m.material), m.cantidad];})));
  h+=sec('Calidad', c.calidad_fecha
    ? '<div style="font-size:12px;padding:4px 0">'+e(c.calidad_por_nombre)+' — '+fmtD(c.calidad_fecha)+(c.calidad_obs?' — '+e(c.calidad_obs):'')+'</div>'
    : '<div class="em" style="padding:8px 0">Todavía sin decisión de Calidad.</div>');
  h+=sec('Remitos', tabla(['Remito','Fecha','Cliente','Estado','Piezas'],
    c.remitos.map(function(r){return [e(r.numero), fmtD(r.fecha), e(r.cliente_nombre), e(r.estado), r.cantidad];})));
  if(c.obs) h+=sec('Historial', '<div style="font-size:12px;white-space:pre-line;padding:4px 0">'+e(c.obs)+'</div>');
  $('cajon-body').innerHTML=h;
}
function openCajCal(c){
  $('cajcal-id').value=c.id; $('cajcal-term').value=c.terminadas||0;
  $('cajcal-title').textContent='Calidad — '+c.numero;
  $('cajcal-info').innerHTML='<b>'+schEsc(c.numero)+'</b> — '+schEsc(c.producto_nombre||'')
    +' | Terminadas: <b>'+fN(c.terminadas||0)+'</b> de '+fN(c.cantidad)+' pz'
    +' | Estado actual: <b>'+schEsc(c.estado)+'</b>'
    +(c.cantidad_remitida?' | Ya remitidas: <b>'+fN(c.cantidad_remitida)+'</b>':'');
  $('cajcal-lib').value=c.cantidad_liberada||0; $('cajcal-rech').value=c.cantidad_rechazada||0;
  $('cajcal-obs').value=c.calidad_obs||'';
  $('cajcal-total-lbl').textContent=(c.terminadas||0)+' pz';
  cajCalRecalc(); openMo('mo-cajon-cal');
}
function cajCalRecalc(changed){
  const t=parseFloat($('cajcal-term').value)||0;
  let l=Math.max(0,parseFloat($('cajcal-lib').value)||0), r=Math.max(0,parseFloat($('cajcal-rech').value)||0);
  // Igual que en Gestionar lote: se recorta el campo editado para no superar el total
  if(l+r>t+0.001){
    if(changed==='aprobado'){ l=Math.max(0,t-r); $('cajcal-lib').value=l; }
    else { r=Math.max(0,t-l); $('cajcal-rech').value=r; }
  }
  $('cajcal-pend').value=Math.max(0,t-l-r);
}
function cajCalQuick(a){
  const t=parseFloat($('cajcal-term').value)||0;
  if(a==='aprobar_todo'){ $('cajcal-lib').value=t; $('cajcal-rech').value=0; }
  else if(a==='rechazar_todo'){ $('cajcal-lib').value=0; $('cajcal-rech').value=t; }
  else { $('cajcal-lib').value=0; $('cajcal-rech').value=0; }
  cajCalRecalc();
}
async function saveCajCal(){
  const id=$('cajcal-id').value;
  const res=await api('/api/cajones/'+id+'/calidad',{method:'POST',body:JSON.stringify({
    cantidad_liberada:parseFloat($('cajcal-lib').value)||0, cantidad_rechazada:parseFloat($('cajcal-rech').value)||0,
    obs:$('cajcal-obs').value})});
  if(res&&res.ok){toast('Cajón '+res.estado.toLowerCase()+(res.pendiente>0?' — quedan '+fN(res.pendiente)+' pendientes':''));closeMo('mo-cajon-cal');loadCajones();}
  else toast((res&&res.error)||'Error','e');
}
async function openCajTransf(c){
  $('cajtr-id').value=c.id; $('cajtr-title').textContent='Pasar '+c.numero+' a otra OT';
  const ots=await api('/api/cajones/'+c.id+'/destinos');
  const s=$('cajtr-ot'); s.innerHTML='';
  (Array.isArray(ots)?ots:[]).forEach(function(o){
    const op=document.createElement('option'); op.value=o.id; op.textContent=o.numero+' — '+o.estado+' ('+fN(o.cantidad)+' pz)'; s.appendChild(op);
  });
  if(!s.options.length){toast('No hay otra OT abierta de este producto','w');return;}
  openMo('mo-cajon-transf');
}
async function saveCajTransf(){
  const res=await api('/api/cajones/'+$('cajtr-id').value+'/transferir',{method:'POST',body:JSON.stringify({orden_id:parseInt($('cajtr-ot').value)})});
  if(res&&res.ok){toast('Cajón pasado de OT');closeMo('mo-cajon-transf');loadCajones();}
  else toast((res&&res.error)||'Error','e');
}
async function bajaCajon(c){
  const obs=await pedirTexto('¿Dar de baja el cajón '+c.numero+'? Sus piezas no siguen. Motivo (opcional):','');
  if(obs===null) return;
  const res=await api('/api/cajones/'+c.id+'/baja',{method:'POST',body:JSON.stringify({obs:obs})});
  if(res&&res.ok){toast('Cajón dado de baja');loadCajones();}
  else toast((res&&res.error)||'Error','e');
}
let _lotesSortCol=null;
let _lotesSortAsc=true;

async function loadLotes(){
  if(_lotesTab==='cajones') loadCajones();
  // Ensure materials are loaded for the material search filter
  if(!_mat.length)_mat=await api('/api/materiales');
  if(!_cli.length)_cli=await api('/api/clientes');
  // Populate proveedor filter
  if($('lote-prov-fil').options.length<=1){
    if(!_prov.length)_prov=await api('/api/proveedores');
    _prov.forEach(function(p){
      const o=document.createElement('option');o.value=p.id;o.textContent=p.razon;
      $('lote-prov-fil').appendChild(o);
    });
  }
  updateLotesFiltrosBadge();
  const mid=$('lote-mat-fil').value;
  const cid=$('lote-cli-fil').value;
  const pid=$('lote-prov-fil').value;
  let url='/api/lotes?estado=';
  const p=[];
  if(mid) p.push('material_id='+mid);
  if(cid) p.push('cliente_id='+cid);
  if(pid) p.push('proveedor_id='+pid);
  if(p.length) url+='&'+p.join('&');

  const rows=await api(url);
  if(!rows.length){
    _lotesData=[];
    _lotesSortCol=null;
    renderLotesTable();
    return;
  }

  // Enrich rows with computed field for sorting
  _lotesData = rows.map(function(r){
    r._ingresado = Math.max(0, (r.cantidad_disponible||0)-(r.cantidad_activa||0)-(r.cantidad_rechazada||0));
    return r;
  });
  _lotesSortCol = null;
  renderLotesTable();
}

function filtrarLoteMatFil(){
  const q=($('lote-mat-fil-txt').value||'').toLowerCase().trim();
  const drop=$('lote-mat-fil-drop');
  if(!q){
    drop.style.display='none';
    if($('lote-mat-fil').value){ $('lote-mat-fil').value=''; loadLotes(); }
    return;
  }
  if(!_mat.length){
    drop.innerHTML='<div style="padding:8px 12px;font-size:12px;color:var(--color-text-secondary)">Cargando...</div>';
    drop.style.display='block';
    api('/api/materiales').then(function(rows){ _mat=rows; filtrarLoteMatFil(); });
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
    row.onmousedown=function(e){ e.preventDefault(); seleccionarLoteMatFil(m.id, m.codigo+' — '+m.descripcion); };
    drop.appendChild(row);
  });
  drop.style.display='block';
}
function seleccionarLoteMatFil(id, texto){
  $('lote-mat-fil').value=id;
  $('lote-mat-fil-txt').value=texto;
  $('lote-mat-fil-drop').style.display='none';
  loadLotes();
}
function clearLotesFiltros(){
  $('lote-mat-fil').value='';
  $('lote-mat-fil-txt').value='';
  $('lote-mat-fil-drop').style.display='none';
  cliBuscadorClear('lote-cli-fil');
  $('lote-prov-fil').value='';
  $('lote-reservado-fil').checked=false;
  $('lote-oculta-agot').checked=true;
  loadLotes();
}
function updateLotesFiltrosBadge(){
  // Ya no hay botón "Filtros" con badge (los filtros quedaron siempre
  // visibles arriba de la tabla) — se mantiene la función vacía por si
  // queda alguna referencia, para no romper nada.
}

function sortLotes(col){
  if(_lotesSortCol===col){ _lotesSortAsc=!_lotesSortAsc; }
  else { _lotesSortCol=col; _lotesSortAsc=true; }
  renderLotesTable();
}

function renderLotesTable(){
  const cols = [
    {key:'numero',             label:'N° Lote',         style:''},
    {key:'mat_desc',           label:'Material',        style:''},
    {key:'cantidad_original',  label:'Original',        style:''},
    {key:'_ingresado',         label:'Ingresado',       style:'color:#888'}, 
    {key:'cantidad_activa',    label:'Aprobado',        style:'color:#2e7d32'},
    {key:'disponible_libre',   label:'Disponible libre',style:'color:#2e7d32'},
    {key:'cantidad_reservada', label:'Reservado',       style:'color:#a36b00'},
    {key:'cantidad_rechazada', label:'✕ Rechazado',     style:'color:#c62828'},
    {key:'proveedor_nombre',   label:'Proveedor',       style:''},
    {key:'ref_cert',           label:'Ref./Cert.',      style:''},
    {key:'fecha_ingreso',      label:'Ingreso',         style:''},
  ];

  // Sort
  let data = _lotesData.slice();
  // Ocultar agotados: sin nada en ingresado, aprobado ni rechazado
  // (si solo tiene reservado, también se considera agotado).
  if($('lote-oculta-agot') && $('lote-oculta-agot').checked){
    data = data.filter(function(r){
      const ingresado=parseFloat(r._ingresado)||0;
      const aprobado=parseFloat(r.cantidad_activa)||0;
      const rechazado=parseFloat(r.cantidad_rechazada)||0;
      return ingresado>0 || aprobado>0 || rechazado>0;
    });
  }
  if($('lote-reservado-fil') && $('lote-reservado-fil').checked){
    data = data.filter(function(r){
      const aprobado=parseFloat(r.cantidad_activa)||0;
      const reservado=parseFloat(r.cantidad_reservada)||0;
      if(aprobado<=0) return false;
      return (reservado/aprobado) > 0.5;
    });
  }
  updateLotesFiltrosBadge();
  if(_lotesSortCol){
    data.sort(function(a,b){
      let va = a[_lotesSortCol], vb = b[_lotesSortCol];
      if(va===null||va===undefined) va='';
      if(vb===null||vb===undefined) vb='';
      // Numeric sort for quantity/date columns
      const numCols=['cantidad_original','cantidad_disponible','_ingresado','cantidad_activa','cantidad_reservada','disponible_libre','cantidad_rechazada'];
      if(numCols.includes(_lotesSortCol)){
        va=parseFloat(va)||0; vb=parseFloat(vb)||0;
        return _lotesSortAsc ? va-vb : vb-va;
      }
      va=String(va).toLowerCase(); vb=String(vb).toLowerCase();
      return _lotesSortAsc ? va.localeCompare(vb) : vb.localeCompare(va);
    });
  }

  // Si el lote seleccionado ya no está visible (filtros / recarga), se deselecciona.
  if(_loteSel && !data.some(function(r){return r.id===_loteSel;})) _loteSel=null;
  if(!data.length){
    actualizarToolbarLotes();
    $('lote-list').innerHTML='<div class="em">No hay lotes para mostrar'+($('lote-oculta-agot')&&$('lote-oculta-agot').checked?' (todos están agotados — desmarcá "Ocultar agotados" para verlos)':'')+'.</div>';
    return;
  }

  // Header
  const thStyle='cursor:pointer;user-select:none;white-space:nowrap;';
  let h='<table><tr><th style="width:24px"></th>';
  cols.forEach(function(c){
    const arrow = _lotesSortCol===c.key ? (_lotesSortAsc?' ▲':' ▼') : ' ⇅';
    const arrowColor = _lotesSortCol===c.key ? '' : ';opacity:0.35';
    h+='<th style="'+thStyle+(c.style?c.style+';':'')+'" onclick="sortLotes(\''+c.key+'\')">'
      +c.label+'<span style="font-size:10px'+arrowColor+'">'+arrow+'</span></th>';
  });
  h+='</tr>';

  // Rows
  data.forEach(function(r){
    h+='<tr class="'+(_loteSel===r.id?'ot-sel':'')+'" style="cursor:pointer" onclick="selLote('+r.id+')">'
      +'<td><input type="radio" name="lote-sel"'+(_loteSel===r.id?' checked':'')+' onclick="event.stopPropagation();selLote('+r.id+')"></td>'
      +'<td><b>'+r.numero+'</b></td>'
      +'<td>'+(r.mat_codigo||'')+' — '+(r.mat_descripcion||'')+'</td>'
      +'<td>'+fN(r.cantidad_original||0)+' '+r.unidad+'</td>'
      +'<td style="color:#888">'+fN(r._ingresado)+' '+r.unidad+'</td>'
      +'<td style="color:#2e7d32;font-weight:600">'+fN(r.cantidad_activa||0)+' '+r.unidad+'</td>'
      +'<td style="color:#2e7d32;font-weight:600"><b>'+(r.disponible_libre!=null?r.disponible_libre:r.cantidad_activa||0)+'</b> '+r.unidad+'</td>'
      +'<td style="color:#a36b00;font-weight:600">'+fN(r.cantidad_reservada||0)+' '+r.unidad+'</td>'
      +'<td style="color:#c62828;font-weight:600">'+fN(r.cantidad_rechazada||0)+' '+r.unidad+'</td>'
      +'<td>'+(r.proveedor_nombre||'—')+'</td>'
      +'<td style="font-size:11px">'+(r.referencia_proveedor||'—')+(r.certificado?' | '+r.certificado:'')+'</td>'
      +'<td>'+fmtD(r.fecha_ingreso)+'</td>'
      +'</tr>';
  });
  $('lote-list').innerHTML=h+'</table>';
  actualizarToolbarLotes();
}

// ── Selección de lote + barra de herramientas de Lotes ────────────────────
let _loteSel=null;
function selLote(id){ _loteSel=id; renderLotesTable(); }
function actualizarToolbarLotes(){
  const r=_loteSel?(_lotesData||[]).find(function(x){return x.id===_loteSel;}):null;
  const lbl=$('lote-sel-label'); if(lbl) lbl.textContent=r?r.numero:'–';
  const bt=$('lote-b-trazar'); if(bt) bt.disabled=!r;
  const be=$('lote-b-etiq'); if(be) be.disabled=!r;
  const bg=$('lote-b-gestionar');
  if(bg){ bg.style.display=(ROL==='logistica')?'none':''; bg.disabled=!r; }
}
function loteSelAccion(a){
  const r=_loteSel?(_lotesData||[]).find(function(x){return x.id===_loteSel;}):null;
  if(!r){toast('Seleccioná un lote de la lista','w');return;}
  if(a==='trazar') openTrazabilidadById(r.id);
  else if(a==='etiquetas') etiquetasLote(r.id);
  else if(a==='gestionar') openLiberacion(r.id);
}

function etiquetasLote(id){
  const r=(_lotesData||[]).find(function(x){return x.id===id;}); if(!r) return;
  const prod=/^(OT-|Lote-OTT)/.test(r.numero||'');
  abrirEtiquetas({origen:'Lote',referencia:r.referencia_proveedor||'',lote:r.numero,cantidad:r.cantidad_original||r.cantidad_disponible||0,unidad:r.unidad||'',descripcion:(r.mat_codigo||'')+' — '+(r.mat_descripcion||''),
    lote_id:prod?null:r.id});
}
function openTrazabilidadById(id){
  // Look up lote numero from the table row - find it via API
  openTrazabilidad(id, 'LOTE-'+id);
}

async function openTrazabilidad(loteId, loteNum){
  $('lote-traz-title').childNodes[0].textContent='Trazabilidad: '+loteNum+' ';
  $('lote-traz-info').textContent='Cargando...';
  $('lote-traz-movs').innerHTML='<div class="ld">Cargando...</div>';
  $('lote-traz-ots').innerHTML='';
  $('lote-traz-origen').innerHTML='';
  $('lote-traz-destinos').innerHTML='';
  openMo('mo-lote-traz');

  const data=await api('/api/lotes/'+loteId+'/trazabilidad');
  if(data.error){$('lote-traz-info').textContent='Error: '+data.error;return;}

  const l=data.lote;
  $('lote-traz-info').innerHTML=
    '<b>'+l.numero+'</b> — '+l.mat_descripcion+
    ' | Ingresado: '+fmtD(l.fecha_ingreso)+
    ' | Cantidad original: <b>'+fN(l.cantidad_original)+'</b> '+l.unidad+
    ' | Disponible: <b>'+fN(l.cantidad_disponible)+'</b>'+
    ' | Estado: '+l.estado+
    (l.referencia_proveedor?' | Ref: '+l.referencia_proveedor:'')+
    (l.certificado?' | Cert: '+l.certificado:'');

  // Movimientos
  if(!data.movimientos.length){
    $('lote-traz-movs').innerHTML='<div class="em">Sin movimientos.</div>';
  } else {
    let h='<table><tr><th>Fecha</th><th>Tipo</th><th>Cantidad</th><th>Referencia</th><th>Usuario</th></tr>';
    data.movimientos.forEach(function(m){
      const c=m.tipo==='entrada'?'bg':'br';
      h+='<tr><td>'+fmtD(m.fecha)+'</td><td><span class="b '+c+'">'+m.tipo+'</span></td>'
        +'<td><b>'+fN(m.cantidad)+'</b></td><td>'+m.referencia+'</td><td>'+(m.usuario_nombre||'—')+'</td></tr>';
    });
    $('lote-traz-movs').innerHTML=h+'</table>';
  }

  // OTs
  if(!data.ordenes.length){
    $('lote-traz-ots').innerHTML='<div class="em">Este lote no fue usado en ninguna OT todavía.</div>';
  } else {
    let h='<table><tr><th>OT</th><th>Producto</th><th>Cliente</th><th>Material</th><th>Cant. usada</th><th>Estado OT</th><th>Entrega</th></tr>';
    data.ordenes.forEach(function(o){
      h+='<tr><td><b>'+o.ot_numero+'</b></td><td>'+(o.producto_nombre||'—')+'</td>'
        +'<td>'+(o.cliente_nombre||'—')+'</td><td>'+o.mat_descripcion+'</td>'
        +'<td>'+fN(o.cantidad_usada)+'</td><td>'+sb(o.ot_estado)+'</td>'
        +'<td>'+fmtD(o.fecha_entrega)+'</td></tr>';
    });
    $('lote-traz-ots').innerHTML=h+'</table>';
  }

  // Origen (hacia atrás) y destino (hacia los clientes)
  const org=data.origen;
  $('lote-traz-origen').innerHTML=org&&(org.ot||org.ott)?trazOrigenHTML(org,0)
    :'<div class="em">Lote de '+(org&&org.origen==='compra'?'compra':'stock')+': no salió de ninguna OT.'
      +(org?' '+trazCompraTxt(org):'')+'</div>';
  $('lote-traz-destinos').innerHTML=trazDestinosHTML(data.destinos,0)
    ||'<div class="em">Este lote todavía no llegó a ningún cliente (ni directo por remito ni a través de una OT).</div>';
}

// ── Trazabilidad completa (remito ⇄ OT ⇄ lotes) ──────────────────────────────
function _tz(t){return String(t==null?'':t).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
function trazCompraTxt(l){
  const p=[];
  if(l.proveedor)p.push('Proveedor: <b>'+_tz(l.proveedor)+'</b>');
  if(l.referencia_proveedor)p.push('Ref: '+_tz(l.referencia_proveedor));
  if(l.certificado)p.push('Certificado: '+_tz(l.certificado));
  if(l.recepcion)p.push('Recepción '+_tz(l.recepcion.numero)+(l.recepcion.remito?' (remito prov. '+_tz(l.recepcion.remito)+')':''));
  if(l.fecha_ingreso)p.push('Ingreso: '+fmtD(l.fecha_ingreso));
  return p.join(' · ');
}
function _trazRango(a){a=a.filter(Boolean).sort();if(!a.length)return '—';const x=fmtD(a[0]),y=fmtD(a[a.length-1]);return x===y?x:x+' al '+y;}
function _trazUnicos(a){return [...new Set(a.filter(Boolean))].join(', ')||'—';}
function trazOtHTML(o,nivel){
  let h='<div class="tz-ot"><div class="tz-tit">'+sb(o.estado)+' <b>'+_tz(o.numero)+'</b> · '+_tz(o.producto_codigo||'')+' '+_tz(o.producto_nombre||'')
    +' · '+fN(o.cantidad)+' u.'+(o.cliente?' · '+_tz(o.cliente):'')
    +' <span class="tz-sub">'+(o.fecha_inicio?'Inicio '+fmtD(o.fecha_inicio):'')+(o.fecha_entrega?' · Entrega '+fmtD(o.fecha_entrega):'')+'</span></div>';
  if(o.operaciones&&o.operaciones.length){
    h+='<table class="tz-tbl"><tr><th>#</th><th>Operación</th><th>Fechas</th><th>Operarios</th><th>Máquinas</th><th>Producido</th></tr>';
    o.operaciones.forEach(op=>{
      const nv=op.novedades||[];
      let prod=nv.reduce((t,n)=>t+(+n.cantidad_producida||0),0);
      let fechas=nv.map(n=>n.fecha),emps=nv.map(n=>n.empleado),maqs=nv.map(n=>n.maquina_codigo);
      if(!maqs.filter(Boolean).length&&op.maquina_codigo)maqs=[op.maquina_codigo];
      let detalle='';
      if(op.otts&&op.otts.length){
        detalle=op.otts.map(t=>'<span class="b bp">'+_tz(t.numero)+'</span> '+_tz(t.proveedor||'')
          +(t.fecha_envio?' · envío '+fmtD(t.fecha_envio):'')+(t.fecha_retorno_real?' · volvió '+fmtD(t.fecha_retorno_real):'')).join('<br>');
        fechas=fechas.concat(op.otts.map(t=>t.fecha_envio),op.otts.map(t=>t.fecha_retorno_real));
        if(!nv.length)prod=op.otts.reduce((t,x)=>t+(+x.cantidad_recibida||0),0);
      }
      h+='<tr><td>'+(op.orden||'')+'</td><td>'+_tz(op.nombre)+(op.es_tercerizada?' <span class="b bp">Tercerizada</span>':'')+(detalle?'<div class="tz-sub">'+detalle+'</div>':'')+'</td>'
        +'<td>'+_trazRango(fechas)+'</td><td>'+_tz(_trazUnicos(emps))+'</td><td>'+_tz(_trazUnicos(maqs))+'</td>'
        +'<td>'+(nv.length||(op.otts&&op.otts.length)?fN(prod):'—')+'</td></tr>';
    });
    h+='</table>';
  }
  if(o.materiales&&o.materiales.length){
    h+='<div class="tz-lbl">Materiales usados</div>';
    o.materiales.forEach(m=>{h+=trazLoteHTML(m,nivel+1);});
  } else h+='<div class="tz-sub" style="margin:4px 0 2px">Sin lotes de materia prima asignados.</div>';
  return h+'</div>';
}
function trazOrigenHTML(l,nivel){
  let h='';
  if(l.ott)h+='<div class="tz-sub" style="margin-bottom:6px">Volvió del tercero <b>'+_tz(l.ott.proveedor||'—')+'</b> con la OTT <b>'+_tz(l.ott.numero)+'</b>'
    +(l.ott.operacion?' ('+_tz(l.ott.operacion)+')':'')+(l.ott.fecha_envio?' · enviado '+fmtD(l.ott.fecha_envio):'')
    +(l.ott.fecha_retorno_real?' · volvió '+fmtD(l.ott.fecha_retorno_real):'')+'</div>';
  if(l.ot)h+=trazOtHTML(l.ot,nivel);
  return h;
}
function trazLoteHTML(l,nivel){
  const cab='<span class="b bb">Lote '+_tz(l.numero)+'</span> '+_tz(l.mat_codigo||'')+' — '+_tz(l.mat_descripcion||'')
    +(l.cantidad_usada!=null?' · usado: <b>'+fN(l.cantidad_usada)+'</b> '+_tz(l.unidad||''):'');
  if(l.repetido)return '<div class="tz-lote">'+cab+' <span class="tz-sub">(ya mostrado más arriba)</span></div>';
  if(!l.ot&&!l.ott)return '<div class="tz-lote">'+cab+'<div class="tz-sub">'+(l.origen==='compra'?'Compra':'Stock')+(trazCompraTxt(l)?' · '+trazCompraTxt(l):'')+'</div></div>';
  return '<details class="tz-lote"'+(nivel<2?' open':'')+'><summary>'+cab+' <span class="tz-sub">· hecho en '+_tz(l.ot?l.ot.numero:l.ott.numero)+'</span></summary>'+trazOrigenHTML(l,nivel)+'</details>';
}
function trazDestinosHTML(d,nivel){
  if(!d)return '';
  let h='';
  if(d.remitos&&d.remitos.length){
    h+='<table class="tz-tbl"><tr><th>Remito</th><th>Fecha</th><th>Cliente</th><th>Cantidad</th><th>Estado</th></tr>';
    d.remitos.forEach(r=>{h+='<tr><td><b>'+_tz(r.numero)+'</b></td><td>'+fmtD(r.fecha)+'</td><td>'+_tz(r.cliente||'—')+'</td><td>'+fN(r.cantidad)+'</td><td>'+sb(r.estado)+'</td></tr>';});
    h+='</table>';
  }
  (d.ordenes||[]).forEach(o=>{
    let sub='';
    (o.lotes||[]).forEach(l=>{
      const x=trazDestinosHTML(l,nivel+1);
      sub+='<div class="tz-lote"><span class="b bb">Lote '+_tz(l.numero)+'</span> '+_tz(l.mat_descripcion||'')+' · '+fN(l.cantidad_original)+' '+_tz(l.unidad||'')
        +(x||'<div class="tz-sub">Todavía sin remitir.</div>')+'</div>';
    });
    h+='<div class="tz-ot"><div class="tz-tit">Usado en '+sb(o.estado)+' <b>'+_tz(o.numero)+'</b> · '+_tz(o.producto_nombre||'')+(o.cliente?' · '+_tz(o.cliente):'')+'</div>'
      +(sub||'<div class="tz-sub">La OT todavía no produjo lotes.</div>')+'</div>';
  });
  return h;
}
async function verTrazRemito(id){
  $('rem-traz-title').textContent='Trazabilidad';
  $('rem-traz').innerHTML='<div class="ld">Cargando...</div>';
  openMo('mo-rem-traz');
  const d=await api('/api/trazabilidad/remito/'+id);
  if(!d||d.error){$('rem-traz').innerHTML='<div class="em">'+_tz((d&&d.error)||'No se pudo leer la trazabilidad.')+'</div>';return;}
  const r=d.remito;
  $('rem-traz-title').textContent='Trazabilidad del remito '+r.numero;
  let h='<div class="tz-cab"><b>'+_tz(r.numero)+'</b> · '+fmtD(r.fecha)+' · '+_tz(r.cliente||'—')+(r.pedido_numero?' · Pedido '+_tz(r.pedido_numero):'')+' · '+sb(r.estado)+'</div>';
  if(!d.items.length)h+='<div class="em">El remito no tiene renglones.</div>';
  d.items.forEach(it=>{
    h+='<div class="tz-item"><div class="tz-tit"><b>'+_tz(it.mat_codigo||'')+'</b> '+_tz(it.mat_descripcion||'')+' · <b>'+fN(it.cantidad)+'</b> '+_tz(it.unidad||'')+'</div>';
    if(it.cajones.length)h+='<div class="tz-sub" style="margin-bottom:6px">Cajones: '+it.cajones.map(c=>'<span class="tag" title="'+_tz((c.estado||'')+(c.calidad_por?' · Calidad: '+c.calidad_por+' '+fmtD(c.calidad_fecha):''))+'">'+_tz(c.numero)+' ('+fN(c.cantidad)+')</span>').join(' ')+'</div>';
    if(!it.lote)h+='<div class="tz-sub">Sin lote registrado: no se puede seguir hacia atrás.</div>';
    else{
      const l=it.lote;
      h+='<div class="tz-sub" style="margin-bottom:6px">Lote <b>'+_tz(l.numero)+'</b>'+(l.ot||l.ott?'':' · '+(l.origen==='compra'?'Compra':'Stock')+(trazCompraTxt(l)?' · '+trazCompraTxt(l):''))+'</div>';
      h+=trazOrigenHTML(l,0);
    }
    h+='</div>';
  });
  $('rem-traz').innerHTML=h;
}

// Tab switcher for trazabilidad modal
document.querySelectorAll('#lote-traz-tabs .tab').forEach(function(t){
  t.addEventListener('click',function(){
    document.querySelectorAll('#lote-traz-tabs .tab').forEach(function(x){x.classList.remove('active');});
    t.classList.add('active');
    $('lote-traz-movs').style.display=t.dataset.lt==='movs'?'block':'none';
    $('lote-traz-ots').style.display=t.dataset.lt==='ots'?'block':'none';
    $('lote-traz-origen').style.display=t.dataset.lt==='origen'?'block':'none';
    $('lote-traz-destinos').style.display=t.dataset.lt==='destinos'?'block':'none';
  });
});

// Lote column shown in movimientos table via lote_numero field



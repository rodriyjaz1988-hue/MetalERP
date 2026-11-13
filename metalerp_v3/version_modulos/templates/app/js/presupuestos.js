// ── Presupuestos ──────────────────────────────────────────────────────────────
function calcT(){const s=parseFloat($('pres-sub').value)||0;const i=parseFloat($('pres-iva').value)||0;$('pres-tot').value=fmtM(s*(1+i/100));}

async function openPres(r){
  if(!_cli.length)_cli=await api('/api/clientes');
  $('pres-id').value=r?r.id:'';
  $('pres-title').textContent=r?'Editar presupuesto '+r.numero:'Nuevo presupuesto';
  $('pres-des').value=r?(r.descripcion||''):'';
  if(r&&r.cliente_id) cliBuscadorSet('pres-cli',r.cliente_id); else cliBuscadorClear('pres-cli');
  $('pres-est').value=r?r.estado:'Borrador';
  $('pres-sub').value=r&&r.subtotal!=null?r.subtotal:'';
  $('pres-iva').value=r&&r.iva_pct!=null?r.iva_pct:21;
  $('pres-val').value=r&&r.validez_dias!=null?r.validez_dias:30;
  $('pres-obs').value=r?(r.obs||''):'';
  calcT();openMo('mo-pres');
}

async function editCli(r){
  $('cli-id').value=r.id;
  $('cli-raz').value=r.razon||'';
  $('cli-cui').value=r.cuit||'';
  $('cli-iva').value=r.iva||'Responsable Inscripto';
  $('cli-rub').value=r.rubro||'';
  $('cli-loc').value=r.localidad||'';
  $('cli-dir').value=r.direccion||'';
  $('cli-con').value=r.contacto||'';
  $('cli-car').value=r.cargo||'';
  $('cli-tel').value=r.telefono||'';
  $('cli-ema').value=r.email||'';
  $('cli-cat').value=r.categoria||'Regular';
  $('cli-pla').value=r.plazo_pago||'';
  $('cli-obs').value=r.obs||'';
  openMo('mo-cli');
}

// ── Pedidos de cotización (pestaña de Presupuestos) ─────────────────────────
let _presTab='pres';
document.querySelectorAll('#pres-tabs .tab').forEach(t=>t.addEventListener('click',()=>{
  document.querySelectorAll('#pres-tabs .tab').forEach(x=>x.classList.remove('active'));
  t.classList.add('active');_presTab=t.dataset.t;
  $('p-presupuestos').dataset.pt=_presTab;
  $('pres-sec-pres').style.display=_presTab==='pres'?'':'none';
  $('pres-sec-pcot').style.display=_presTab==='pcot'?'':'none';
  if(_presTab==='pcot') loadPcot();
}));

let _pcot=[];
let _pcotSel=null;
let _pcotSortCol=null;
let _pcotSortAsc=true;

async function loadPcot(){
  const rows=await api('/api/pedidos_cotizacion');
  _pcot=Array.isArray(rows)?rows:[];
  renderPcot();
}
function clearFiltrosPcot(){ if($('pcot-buscar'))$('pcot-buscar').value=''; if($('pcot-fil-estado'))$('pcot-fil-estado').value=''; renderPcot(); }
// Negociación cliente <-> taller: Pendiente (le toca al taller) -> Cotizada
// (enviada al cliente) -> Aprobada / Rechazada (finales) o contraoferta, que
// vuelve a Pendiente en la ronda siguiente. Solo un admin reabre un final.
const PCOT_FINALES=['Aprobada','Rechazada'];
const PCOT_PUEDE=['admin','vendedor'];
// Estado del pedido: badge con la ronda, quién y cuándo lo movió (y el motivo del rechazo).
function pcotEstadoBadge(r){
  const e=r.estado||'Pendiente', cls={Pendiente:'ba',Cotizada:'bb',Aprobada:'bg',Rechazada:'br'}[e]||'bk';
  const ronda=+r.ronda||1;
  let tip=e+(ronda>1?' · ronda '+ronda:'');
  if(r.estado_fecha) tip+=(r.estado_por_nombre?' · '+r.estado_por_nombre:'')+' el '+fmtDH(r.estado_fecha);
  if(r.estado_motivo) tip+=' · Motivo: '+r.estado_motivo;
  return '<span class="b '+cls+'" title="'+schEsc(tip)+'">'+e+(ronda>1?' · R'+ronda:'')+'</span>'+(r.estado_motivo?' <span title="'+schEsc(r.estado_motivo)+'" style="cursor:help">💬</span>':'');
}
function sortPcot(col){
  if(_pcotSortCol===col){ _pcotSortAsc=!_pcotSortAsc; }
  else { _pcotSortCol=col; _pcotSortAsc=true; }
  renderPcot();
}
function _pcotUnit(r){ return (VER_MONETARIO&&r.precio_total!=null&&r.cantidad>0)?r.precio_total/r.cantidad:null; }
function renderPcot(){
  if(_pcotSel!==null&&!_pcot.some(x=>x.id===_pcotSel)) _pcotSel=null;
  if(!_pcot.length){$('pcot-list').innerHTML='<div class="em">No hay pedidos de cotización.'+(PCOT_PUEDE.includes(ROL)?' Usá "Nuevo pedido" para cargar el primero.':'')+'</div>';actualizarToolbarPcot();return;}
  const q=($('pcot-buscar')?$('pcot-buscar').value:'').trim().toLowerCase();
  let lista=_pcot;
  if(q) lista=lista.filter(r=>(r.numero||'').toLowerCase().includes(q)||(r.cliente_nombre||'').toLowerCase().includes(q)
    ||(r.producto_codigo||'').toLowerCase().includes(q)||(r.producto_nombre||'').toLowerCase().includes(q)
    ||(r.descripcion||'').toLowerCase().includes(q));
  const fe=$('pcot-fil-estado')?$('pcot-fil-estado').value:'';
  if(fe) lista=lista.filter(r=>(r.estado||'Pendiente')===fe);
  if(!lista.length){$('pcot-list').innerHTML='<div class="em">Sin resultados para los filtros seleccionados.</div>';actualizarToolbarPcot();return;}
  lista=lista.slice();
  if(_pcotSortCol){
    const numCols=['cantidad','precio_total','precio_unitario'];
    lista.sort(function(a,b){
      if(numCols.includes(_pcotSortCol)){
        const va=_pcotSortCol==='precio_unitario'?_pcotUnit(a):a[_pcotSortCol];
        const vb=_pcotSortCol==='precio_unitario'?_pcotUnit(b):b[_pcotSortCol];
        return _pcotSortAsc?(va||0)-(vb||0):(vb||0)-(va||0);
      }
      const va=String(a[_pcotSortCol]||'').toLowerCase(), vb=String(b[_pcotSortCol]||'').toLowerCase();
      return _pcotSortAsc?va.localeCompare(vb,'es',{numeric:true}):vb.localeCompare(va,'es',{numeric:true});
    });
  }
  const th=function(key,label){
    const arrow=_pcotSortCol===key?(_pcotSortAsc?' ▲':' ▼'):' ⇅';
    const arrowColor=_pcotSortCol===key?'':';opacity:0.35';
    const attrs='style="cursor:pointer;user-select:none;white-space:nowrap" onclick="sortPcot(\''+key+'\')"';
    const txt=label+'<span style="font-size:10px'+arrowColor+'">'+arrow+'</span>';
    return '<th '+attrs+'>'+txt+'</th>';
  };
  let h='<table><tr><th style="width:24px"></th>'+th('numero','N°')+th('fecha','Fecha')+th('cliente_nombre','Cliente')
    +th('producto_codigo','Código')+th('producto_nombre','Producto')+th('descripcion','Descripción')+th('cantidad','Cantidad')
    +monOnly(th('precio_total','Precio total')+th('precio_unitario','Precio unitario'))+th('estado','Estado')+'</tr>';
  lista.forEach(function(r){
    const sel=_pcotSel===r.id;
    h+='<tr id="pcot-row-'+r.id+'" class="'+(sel?'ot-sel':'')+'" style="cursor:pointer" onclick="selPcot('+r.id+')" ondblclick="selPcot('+r.id+');pcotSelAccion((this.dataset.est||\'Pendiente\')===\'Pendiente\'?\'edit\':\'hist\')" data-est="'+schEsc(r.estado||'Pendiente')+'">'
      +'<td><input type="radio" name="pcot-sel" '+(sel?'checked':'')+' onclick="event.stopPropagation();selPcot('+r.id+')"></td>'
      +'<td><b>'+r.numero+'</b></td><td>'+fmtD(r.fecha)+'</td><td>'+(r.cliente_nombre||'—')+'</td>'
      +'<td><b>'+(r.producto_codigo||'—')+'</b></td><td>'+(r.producto_nombre||'—')+'</td>'
      +(r.descripcion
        ?'<td title="'+schEsc(r.descripcion)+'" style="max-width:240px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'+schEsc(r.descripcion)+'</td>'
        :'<td style="color:var(--color-text-secondary)">—</td>')
      +'<td>'+(+r.cantidad).toLocaleString('es-AR')+' '+(r.producto_unidad||'')+'</td>'
      +tdM(r.precio_total!=null?fmtMD(r.precio_total,r.moneda):'—')
      +tdM(_pcotUnit(r)!=null?fmtMD(_pcotUnit(r),r.moneda):'—')
      +'<td style="white-space:nowrap">'+pcotEstadoBadge(r)+'</td>'
      +'</tr>';
  });
  $('pcot-list').innerHTML=h+'</table>'
    +'<div style="font-size:11px;color:var(--color-text-secondary);margin-top:4px">'+lista.length+' pedido'+(lista.length!==1?'s':'')+(lista.length!==_pcot.length?' (de '+_pcot.length+' total)':'')+'</div>';
  actualizarToolbarPcot();
}
function selPcot(id){
  _pcotSel=id;
  document.querySelectorAll('#pcot-list tr.ot-sel').forEach(tr=>tr.classList.remove('ot-sel'));
  const tr=$('pcot-row-'+id);
  if(tr){ tr.classList.add('ot-sel'); const rd=tr.querySelector('input[type=radio]'); if(rd) rd.checked=true; }
  actualizarToolbarPcot();
}
// Botones según el estado del pedido seleccionado. Sin selección quedan a la
// vista (deshabilitados) Editar, Historial y Eliminar.
function actualizarToolbarPcot(){
  const r=_pcotSel!==null?_pcot.find(x=>x.id===_pcotSel):null;
  const lbl=$('pcot-sel-label'); if(lbl) lbl.textContent=r?r.numero+((+r.ronda||1)>1?' · R'+r.ronda:''):'–';
  const e=r?(r.estado||'Pendiente'):null, puede=PCOT_PUEDE.includes(ROL);
  let ver=['hist'];
  if(puede){
    if(!r) ver=['edit','hist','elim'];
    else if(e==='Pendiente') ver=(r.ultimo_evento==='Contraoferta'?['edit','aprob','cot','rech']:['edit','cot','rech']).concat(['hist','elim']);
    else if(e==='Cotizada') ver=['aprob','contra','rech','hist','elim'];
    else ver=(ROL==='admin'?['reab']:[]).concat(['hist','elim']);
  }
  ['edit','cot','aprob','contra','rech','reab','hist','elim'].forEach(function(k){
    const b=$('pcot-b-'+k); if(!b) return;
    b.style.display=ver.includes(k)?'':'none';
    b.disabled=!r;
  });
  const ba=$('pcot-b-aprob');
  if(ba) ba.title=e==='Pendiente'?'Aceptar la contraoferta del cliente tal como vino':'El cliente aprobó la cotización';
  const bc=$('pcot-b-cot');
  if(bc&&!VER_MONETARIO){ bc.disabled=true; bc.title='No tenés permiso para ver importes: no podés cotizar'; }
}
async function _pcotEstado(r,body,ok){
  const res=await api('/api/pedidos_cotizacion/'+r.id+'/estado',{method:'POST',body:JSON.stringify(body)});
  if(res&&res.ok){ toast('Pedido '+r.numero+': '+ok); loadPcot(); return true; }
  toast((res&&res.error)||'Error','e'); if(res&&/cambió de estado/.test(res.error||'')) loadPcot();
  return false;
}
async function pcotSelAccion(a){
  const r=_pcotSel!==null?_pcot.find(x=>x.id===_pcotSel):null;
  if(!r){toast('Seleccioná un pedido de la lista','w');return;}
  if(a==='hist'){ openPcotHist(r); return; }
  if(!PCOT_PUEDE.includes(ROL)) return;
  const e=r.estado||'Pendiente';
  const resumen=(r.cliente_nombre||'')+' · '+(r.producto_codigo||'')+' × '+(+r.cantidad).toLocaleString('es-AR');
  if(a==='edit'){
    if(e!=='Pendiente'){toast('El pedido está '+e+': solo se edita mientras está Pendiente','w');return;}
    openPcot(r);
  }
  else if(a==='cot'||a==='contra'){
    if(a==='cot'&&!VER_MONETARIO){toast('No tenés permiso para ver importes: no podés cotizar','w');return;}
    openPcotNeg(r,a==='cot'?'cotizar':'contraoferta');
  }
  else if(a==='aprob'){
    const contra=e==='Pendiente';
    if(!await confirmar((contra?'¿Aceptar la contraoferta del cliente y aprobar el pedido '+r.numero+'?'
                               :'¿El cliente aprobó la cotización del pedido '+r.numero+'?')+'\n'+resumen
      +(VER_MONETARIO&&r.precio_total!=null?'\nPrecio total: '+fmtMD(r.precio_total,r.moneda):''))) return;
    await _pcotEstado(r,{accion:'aprobar'},contra?'contraoferta aceptada, aprobado':'aprobado');
  }
  else if(a==='rech'){
    const quien=e==='Pendiente'?'el taller':'el cliente';
    const m=await pedirTexto('¿Rechazar el pedido '+r.numero+'? Lo rechaza '+quien+'.\n'+resumen+'\nMotivo (opcional)','');
    if(m===null) return;
    await _pcotEstado(r,{accion:'rechazar',motivo:m},'rechazado por '+quien);
  }
  else if(a==='reab'){
    if(ROL!=='admin') return;
    const m=await pedirTexto('¿Reabrir el pedido '+r.numero+'? Ahora está '+e+' y vuelve a Pendiente.\nNota (opcional)','');
    if(m===null) return;
    await _pcotEstado(r,{accion:'reabrir',nota:m},'reabierto');
  }
  else if(a==='elim'){
    if(!await confirmar('¿Eliminar el pedido de cotización '+r.numero+'?\nSe borra también su historial.')) return;
    const res=await apiBorrar('/api/pedidos_cotizacion/'+r.id,'Pedido de cotización '+r.numero+' eliminado');
    if(res.ok){toast('Pedido '+r.numero+' eliminado');_pcotSel=null;loadPcot();}
    else toast(res.error||'Error','e');
  }
}
let _pcotProds=[];
async function _pcotEnsureProds(){
  if(!_pcotProds.length){
    const rows=await api('/api/productos');
    // Solo productos terminados se cotizan (el servidor rechaza el resto).
    _pcotProds=(Array.isArray(rows)?rows:[]).filter(function(p){return p.tipo_articulo==='Producto terminado';});
  }
}
async function filtrarPcotProducto(){
  await _pcotEnsureProds();
  const q=($('pcot-prod-search').value||'').toLowerCase().trim();
  const cont=$('pcot-prod-results');
  const lista=q?_pcotProds.filter(function(p){return (p.codigo||'').toLowerCase().includes(q)||(p.nombre||'').toLowerCase().includes(q);}):_pcotProds;
  _novotResultsRender(cont,lista,function(p){return p.codigo+' — '+(p.nombre||'');},function(p){
    $('pcot-prod').value=p.id;
    $('pcot-prod-search').value=p.codigo+' — '+(p.nombre||'');
    cont.style.display='none';cont.innerHTML='';
  });
}
function pcotCalcUnit(){
  if(!VER_MONETARIO||!$('pcot-unit')) return;
  const r=_pcot.find(x=>String(x.id)===String($('pcot-id').value));
  const t=r&&r.precio_total!=null?+r.precio_total:NaN, c=parseFloat($('pcot-cant').value);
  $('pcot-unit').value=(!isNaN(t)&&c>0)?fmtMD(t/c,r.moneda):'';
}
function pcotDescCnt(){
  const n=($('pcot-desc').value||'').length, el=$('pcot-desc-cnt');
  if(el) el.textContent=n?'('+n+'/1000)':'';
}
async function openPcot(r){
  if(!_cli.length)_cli=await api('/api/clientes');
  await _pcotEnsureProds();
  $('pcot-id').value=r?r.id:'';
  $('pcot-title').textContent=r?'Editar pedido de cotización '+r.numero+((+r.ronda||1)>1?' · ronda '+r.ronda:''):'Nuevo pedido de cotización';
  $('pcot-fecha').value=r?(r.fecha||'').slice(0,10):new Date().toISOString().slice(0,10);
  if(r) cliBuscadorSet('pcot-cli',r.cliente_id); else cliBuscadorClear('pcot-cli');
  $('pcot-prod').value=r?r.producto_id:'';
  $('pcot-prod-search').value=r?((r.producto_codigo||'')+' — '+(r.producto_nombre||'')):'';
  $('pcot-cant').value=r?r.cantidad:'';
  $('pcot-desc').value=r&&r.descripcion?r.descripcion:'';
  pcotDescCnt();
  // El precio no se edita acá: se carga con Cotizar o en una contraoferta.
  const conPrecio=VER_MONETARIO&&r&&r.precio_total!=null;
  ['pcot-precio-fg','pcot-unit-fg'].forEach(function(id){const el=$(id);if(el)el.style.display=conPrecio?'':'none';});
  if(conPrecio&&$('pcot-precio')) $('pcot-precio').value=fmtMD(r.precio_total,r.moneda);
  pcotCalcUnit();
  openMo('mo-pcot');
}
async function savePcot(){
  const id=$('pcot-id').value;
  const desc=($('pcot-desc').value||'').trim();
  const body={fecha:$('pcot-fecha').value,cliente_id:$('pcot-cli').value||null,
    producto_id:$('pcot-prod').value||null,cantidad:parseFloat($('pcot-cant').value)||0,descripcion:desc};
  if(!body.fecha){toast('Fecha requerida','w');return;}
  if(!body.cliente_id){toast('Elegí un cliente de la lista','w');return;}
  if(!body.producto_id){toast('Elegí un producto terminado de la lista','w');return;}
  if(!(body.cantidad>0)){toast('La cantidad de piezas debe ser mayor a 0','w');return;}
  if(desc.length>1000){toast('La descripción no puede superar los 1000 caracteres','w');return;}
  const res=await api('/api/pedidos_cotizacion'+(id?'/'+id:''),{method:id?'PUT':'POST',body:JSON.stringify(body)});
  if(res.ok){toast(id?'Pedido actualizado':'Pedido '+res.numero+' creado');closeMo('mo-pcot');if(!id)_pcotSel=res.id;loadPcot();}
  else toast(res.error||'Error','e');
}
// Cotizar (el taller carga el precio total) o contraoferta del cliente
// (precio y/o cantidad nuevos: el pedido vuelve a Pendiente en la ronda siguiente).
function openPcotNeg(r,accion){
  const contra=accion==='contraoferta';
  $('pcot-neg-id').value=r.id; $('pcot-neg-accion').value=accion;
  $('pcot-neg-title').textContent=(contra?'Contraoferta del cliente · ':'Cotizar · ')+r.numero;
  $('pcot-neg-info').textContent=(r.cliente_nombre||'')+' · '+(r.producto_codigo||'')+' '+(r.producto_nombre||'')
    +' · ronda '+(+r.ronda||1)+(contra?' → '+((+r.ronda||1)+1):'')
    +(contra&&VER_MONETARIO&&r.precio_total!=null?' · Vigente: '+(+r.cantidad).toLocaleString('es-AR')+' pzs por '+fmtMD(r.precio_total,r.moneda):'');
  $('pcot-neg-cant-fg').style.display=contra?'':'none';
  $('pcot-neg-cant').value=r.cantidad;
  if($('pcot-neg-precio')) $('pcot-neg-precio').value=contra&&r.precio_total!=null?r.precio_total:'';
  if($('pcot-neg-precio-req')) $('pcot-neg-precio-req').style.display=contra?'none':'';
  $('pcot-neg-nota').value='';
  $('pcot-neg-ok').textContent=contra?'Registrar contraoferta':'Cotizar';
  pcotNegCalc();
  openMo('mo-pcot-neg');
  setTimeout(function(){const el=contra?$('pcot-neg-cant'):$('pcot-neg-precio');if(el)el.focus();},50);
}
function pcotNegCalc(){
  if(!VER_MONETARIO||!$('pcot-neg-unit')) return;
  const r=_pcot.find(x=>String(x.id)===String($('pcot-neg-id').value));
  const t=parseFloat($('pcot-neg-precio').value);
  const c=$('pcot-neg-accion').value==='contraoferta'?parseFloat($('pcot-neg-cant').value):(r?+r.cantidad:NaN);
  $('pcot-neg-unit').value=(!isNaN(t)&&c>0)?fmtMD(t/c,r&&r.moneda):'';
}
async function savePcotNeg(){
  const r=_pcot.find(x=>String(x.id)===String($('pcot-neg-id').value));
  if(!r){closeMo('mo-pcot-neg');return;}
  const accion=$('pcot-neg-accion').value, contra=accion==='contraoferta';
  const body={accion:accion,nota:$('pcot-neg-nota').value};
  const pv=$('pcot-neg-precio')?$('pcot-neg-precio').value:'';
  if(!contra){
    if(pv===''){toast('Cargá el precio total para cotizar','w');return;}
    if(!(parseFloat(pv)>=0)){toast('El precio total no puede ser negativo','w');return;}
    body.precio_total=parseFloat(pv);
  } else {
    const c=parseFloat($('pcot-neg-cant').value);
    if(!(c>0)){toast('La cantidad de piezas debe ser mayor a 0','w');return;}
    const p=pv===''?null:parseFloat(pv);
    if(p!==null&&!(p>=0)){toast('El precio total no puede ser negativo','w');return;}
    const cambiaCant=Math.abs(c-(+r.cantidad))>1e-9;
    const cambiaPrecio=VER_MONETARIO&&p!==null&&(r.precio_total==null||Math.abs(p-(+r.precio_total))>=0.005);
    if(!cambiaCant&&!cambiaPrecio){toast('La contraoferta tiene que cambiar el precio total o la cantidad','w');return;}
    if(cambiaCant) body.cantidad=c;
    if(cambiaPrecio) body.precio_total=p;
  }
  if(await _pcotEstado(r,body,contra?'contraoferta registrada (ronda '+((+r.ronda||1)+1)+')':'cotizado')) closeMo('mo-pcot-neg');
}
async function openPcotHist(r){
  $('pcot-hist-title').textContent='Historial · '+r.numero;
  $('pcot-hist-info').textContent=(r.cliente_nombre||'')+' · '+(r.producto_codigo||'')+' '+(r.producto_nombre||'')+' · '+(r.estado||'Pendiente')+' · ronda '+(+r.ronda||1);
  $('pcot-hist-body').innerHTML='<div class="ld">Cargando...</div>';
  openMo('mo-pcot-hist');
  const rows=await api('/api/pedidos_cotizacion/'+r.id+'/historial');
  if(!Array.isArray(rows)){$('pcot-hist-body').innerHTML='<div class="em">'+schEsc((rows&&rows.error)||'No se pudo cargar el historial')+'</div>';return;}
  if(!rows.length){$('pcot-hist-body').innerHTML='<div class="em">Sin movimientos registrados.</div>';return;}
  const cls={'Solicitud':'bk','Cotización':'bb','Contraoferta':'ba','Aprobación':'bg','Rechazo':'br','Reapertura':'bp'};
  let h='<table><tr><th>Ronda</th><th>Evento</th><th>Cantidad</th>'+monOnly('<th>Precio total</th><th>Precio unitario</th>')+'<th>Nota</th><th>Usuario</th><th>Fecha</th></tr>';
  rows.forEach(function(x){
    const unit=(x.precio_total!=null&&x.cantidad>0)?x.precio_total/x.cantidad:null;
    h+='<tr><td>R'+x.ronda+'</td><td><span class="b '+(cls[x.evento]||'bk')+'">'+schEsc(x.evento)+'</span></td>'
      +'<td>'+(x.cantidad!=null?(+x.cantidad).toLocaleString('es-AR'):'—')+'</td>'
      +tdM(x.precio_total!=null?fmtMD(x.precio_total,x.moneda):'—')
      +tdM(unit!=null?fmtMD(unit,x.moneda):'—')
      +'<td style="white-space:normal;max-width:280px">'+(x.nota?schEsc(x.nota):'—')+'</td>'
      +'<td>'+schEsc(x.usuario_nombre||'—')+'</td><td>'+fmtDH(x.fecha)+'</td></tr>';
  });
  $('pcot-hist-body').innerHTML=h+'</table>';
}

let _pres=[];
let _presSel=null;
const PRES_ESTADOS=['Borrador','Enviado','Aprobado','Rechazado','Facturado'];
// Colores del selector de estado, igual que el de Órdenes de trabajo.
const PRES_COLORES={'Borrador':{bg:'#F1F1F1',fg:'#555'},'Enviado':{bg:'#E6F1FB',fg:'#0C447C'},'Aprobado':{bg:'#EAF3DE',fg:'#27500A'},'Rechazado':{bg:'#FCEBEB',fg:'#791F1F'},'Facturado':{bg:'#FAEEDA',fg:'#633806'}};
function _presColorSel(sel){
  const c=PRES_COLORES[sel.value]||{bg:'#fff',fg:'#1a1a1a'};
  sel.style.background=c.bg; sel.style.color=c.fg;
}
async function loadPres(){
  if(_presTab==='pcot') loadPcot();
  const rows=await api('/api/presupuestos');
  _pres=Array.isArray(rows)?rows:[];
  if(_presSel!==null&&!_pres.some(x=>x.id===_presSel)) _presSel=null;
  renderPres();
}
function clearFiltrosPres(){
  ['pres-fil-cli','pres-fil-cli-search','pres-fil-est','pres-fil-tmin','pres-fil-tmax','pres-fil-desde','pres-fil-hasta'].forEach(function(id){if($(id))$(id).value='';});
  renderPres();
}
function _presFiltrados(){
  const v=function(id){return $(id)?$(id).value:'';};
  const cli=v('pres-fil-cli-search')?v('pres-fil-cli'):'';
  const tmin=v('pres-fil-tmin')===''?null:parseFloat(v('pres-fil-tmin'));
  const tmax=v('pres-fil-tmax')===''?null:parseFloat(v('pres-fil-tmax'));
  const desde=v('pres-fil-desde'), hasta=v('pres-fil-hasta'), est=v('pres-fil-est');
  return _pres.filter(function(r){
    if(cli&&String(r.cliente_id)!==String(cli)) return false;
    if(est&&r.estado!==est) return false;
    if(tmin!==null&&!((+r.total||0)>=tmin)) return false;
    if(tmax!==null&&!((+r.total||0)<=tmax)) return false;
    const f=(r.creado||'').slice(0,10);
    if(desde&&f<desde) return false;
    if(hasta&&f>hasta) return false;
    return true;
  });
}
function renderPres(){
  if(!_pres.length){$('pres-list').innerHTML='<div class="em">No hay presupuestos.'+(['admin','vendedor'].includes(ROL)?' Usá "Nuevo presupuesto" para crear el primero.':'')+'</div>';actualizarToolbarPres();return;}
  const lista=_presFiltrados();
  if(!lista.length){$('pres-list').innerHTML='<div class="em">Sin resultados para los filtros seleccionados.</div>';actualizarToolbarPres();return;}
  const puede=['admin','vendedor'].includes(ROL);
  let h='<table><tr><th style="width:24px"></th><th>N°</th><th>Cliente</th><th>Descripción</th><th>Total</th><th>Validez</th><th>Fecha</th><th>Estado</th></tr>';
  lista.forEach(r=>{
    const sel=_presSel===r.id;
    // Facturado = presupuesto cerrado: ya no cambia de estado ni se edita.
    const est=(puede&&r.estado!=='Facturado')
      ?'<select class="pres-est-sel" onclick="event.stopPropagation()" onchange="presCambiarEstado('+r.id+',this)" style="font-family:inherit;font-size:11px;font-weight:500;padding:3px 9px;border-radius:7px;border:1px solid transparent;background:'+((PRES_COLORES[r.estado]||{}).bg||'#fff')+';color:'+((PRES_COLORES[r.estado]||{}).fg||'#1a1a1a')+';cursor:pointer">'
        +PRES_ESTADOS.concat(PRES_ESTADOS.includes(r.estado)?[]:[r.estado]).map(e=>'<option style="background:#fff;color:#1a1a1a"'+(e===r.estado?' selected':'')+'>'+e+'</option>').join('')+'</select>'
      :sb(r.estado)+(r.estado==='Facturado'?' <span title="Presupuesto cerrado" style="font-size:11px">🔒</span>':'');
    h+='<tr id="pres-row-'+r.id+'" class="'+(sel?'ot-sel':'')+'" style="cursor:pointer" onclick="selPres('+r.id+')" ondblclick="selPres('+r.id+');presSelAccion(\'edit\')">'
      +'<td><input type="radio" name="pres-sel" '+(sel?'checked':'')+' onclick="event.stopPropagation();selPres('+r.id+')"></td>'
      +'<td><b>'+r.numero+'</b></td><td>'+(r.cliente_nombre||'—')+'</td><td>'+(r.descripcion||'')+'</td><td><b>'+fmtM(r.total,r.moneda)+'</b></td>'
      +'<td>'+r.validez_dias+'d</td><td>'+fmtD(r.creado)+'</td><td>'+est+'</td></tr>';
  });
  $('pres-list').innerHTML=h+'</table>'
    +'<div style="font-size:11px;color:var(--color-text-secondary);margin-top:4px">'+lista.length+' presupuesto'+(lista.length!==1?'s':'')+(lista.length!==_pres.length?' (de '+_pres.length+' total)':'')+'</div>';
  actualizarToolbarPres();
}
function selPres(id){
  _presSel=id;
  document.querySelectorAll('#pres-list tr.ot-sel').forEach(tr=>tr.classList.remove('ot-sel'));
  const tr=$('pres-row-'+id);
  if(tr){ tr.classList.add('ot-sel'); const rd=tr.querySelector('input[type=radio]'); if(rd) rd.checked=true; }
  actualizarToolbarPres();
}
function actualizarToolbarPres(){
  const r=_presSel!==null?_pres.find(x=>x.id===_presSel):null;
  const lbl=$('pres-sel-label'); if(lbl) lbl.textContent=r?r.numero:'–';
  const b=$('pres-b-edit');
  if(b){
    b.disabled=!r||r.estado==='Facturado';
    b.title=!r?'Editar el presupuesto seleccionado':(r.estado==='Facturado'?'El presupuesto está facturado (cerrado): no se puede editar':'Editar el presupuesto '+r.numero);
  }
}
function presSelAccion(a){
  const r=_presSel!==null?_pres.find(x=>x.id===_presSel):null;
  if(!r){toast('Seleccioná un presupuesto de la lista','w');return;}
  if(!['admin','vendedor'].includes(ROL)) return;
  if(a==='edit'){
    if(r.estado==='Facturado'){toast('El presupuesto '+r.numero+' está facturado (cerrado): no se puede editar','w');return;}
    openPres(r);
  }
}
function _presConfirmaFacturar(numero){
  return confirmar('¿Marcar '+(numero?'el presupuesto '+numero:'el presupuesto')+' como Facturado?\n\nEl presupuesto queda cerrado: ya no se podrá editar ni cambiar de estado.');
}
async function presCambiarEstado(id,sel){
  const r=_pres.find(x=>x.id===id); if(!r) return;
  const nuevo=sel.value;
  if(nuevo===r.estado) return;
  _presColorSel(sel);
  if(nuevo==='Facturado'&&!await _presConfirmaFacturar(r.numero)){sel.value=r.estado;_presColorSel(sel);return;}
  const res=await api('/api/presupuestos/'+id,{method:'PUT',body:JSON.stringify({estado:nuevo})});
  if(res.ok){toast(nuevo==='Facturado'?'Presupuesto '+r.numero+' facturado y cerrado':'Presupuesto '+r.numero+': '+nuevo);loadPres();}
  else{toast(res.error||'Error','e');sel.value=r.estado;_presColorSel(sel);}
}

async function savePres(){
  const id=$('pres-id').value;
  const body={descripcion:$('pres-des').value,cliente_id:$('pres-cli').value||null,
    estado:$('pres-est').value,subtotal:$('pres-sub').value||0,
    iva_pct:$('pres-iva').value||21,validez_dias:$('pres-val').value||30,obs:$('pres-obs').value};
  if(!body.descripcion){toast('Descripción requerida','w');return;}
  const ant=id?_pres.find(x=>String(x.id)===String(id)):null;
  if(body.estado==='Facturado'&&(!ant||ant.estado!=='Facturado')&&!await _presConfirmaFacturar(ant&&ant.numero)) return;
  const res=await api('/api/presupuestos'+(id?'/'+id:''),{method:id?'PUT':'POST',body:JSON.stringify(body)});
  if(res.ok){toast(id?'Presupuesto actualizado':'Presupuesto '+res.numero+' creado');closeMo('mo-pres');if(!id)_presSel=res.id;loadPres();}
  else toast(res.error||'Error','e');
}


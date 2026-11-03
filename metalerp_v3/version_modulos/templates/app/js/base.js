let _cli=[],_prod=[],_mat=[],_maq=[],_catM=[],_catP=[],_prov=[];
let opN=0,curProdId=null,curProdNom='';

// Sin el permiso monetario, los campos de importes se BORRAN del DOM (ver
// _borrarMonetarioDOM). Las funciones que abren y guardan formularios (PT, OT,
// tickets, operaciones, config...) siguen haciendo $('prod-pv').value=... y,
// con el nodo borrado, tiraban TypeError y el formulario no abría ni guardaba.
// Por eso $ devuelve, para esos ids, un nodo suelto que nunca entra al
// documento: se puede leer y escribir sin error y lo que se manda al
// servidor de todos modos se descarta en before_request.
const _MON_BORRADOS=new Map();
function _registrarMonBorrado(nodo){
  if(!nodo||!nodo.querySelectorAll) return;
  [nodo].concat(Array.from(nodo.querySelectorAll('[id]'))).forEach(function(el){
    if(!el.id||_MON_BORRADOS.has(el.id)) return;
    const s=el.cloneNode(false);
    if('value' in s) s.value='';
    _MON_BORRADOS.set(el.id,s);
  });
}
const $=id=>document.getElementById(id)||_MON_BORRADOS.get(id)||null;
// ── Valores monetarios ─────────────────────────────────────────────────────
// Regla: para quien no tiene el permiso, lo monetario NO SE GENERA. Nada de
// display:none ni de placeholders tipo "$ —": un recuadro vacío donde debería
// ir un precio sigue siendo información. El servidor ya no manda los importes
// (ver puede_ver_monetario en server.py); esto evita además que queden
// etiquetas, columnas o celdas sueltas.
//
// Cómo usarlos al escribir una función nueva:
//   monOnly('<b>Total: '+fmtM(x)+'</b>')   -> '' si no puede ver importes
//   '<tr>'+thM('Precio')+'</tr>'           -> el <th> o nada
//   '<tr>'+tdM(fmtM(p))+'</tr>'            -> el <td> o nada
// thM y tdM se omiten a la vez, así la columna desaparece entera y la tabla
// nunca se desalinea. Para HTML estático, poner data-monetario en el nodo.
// fmtM(n, moneda): la moneda del documento si se pasa, si no la del sistema.
// En dólares siempre con centavos (y hasta 4 decimales en importes menores a 1).
const simMon=m=>(m||MONEDA)==='USD'?'US$ ':'$';
const _fmtUSD=n=>{const v=Number(n)||0;return 'US$ '+v.toLocaleString('es-AR',{minimumFractionDigits:2,maximumFractionDigits:Math.abs(v)<1&&v!==0?4:2});};
const fmtM=(n,m)=>!VER_MONETARIO?'':((m||MONEDA)==='USD'?_fmtUSD(n):'$'+Math.round(n||0).toLocaleString('es-AR'));
const fmtMD=(n,m)=>!VER_MONETARIO?'':((m||MONEDA)==='USD'?_fmtUSD(n):'$'+(n||0).toLocaleString('es-AR',{minimumFractionDigits:2,maximumFractionDigits:2}));
const monOnly=html=>VER_MONETARIO?html:'';
const thM=(txt,attrs)=>VER_MONETARIO?('<th'+(attrs?' '+attrs:'')+'>'+txt+'</th>'):'';
const tdM=(txt,attrs)=>VER_MONETARIO?('<td'+(attrs?' '+attrs:'')+'>'+(txt==null?'':txt)+'</td>'):'';
// Cantidades con formato argentino: 1.234,5 (hasta 2 decimales, sin ceros de más).
const fN=(n,dec=2)=>{if(n===null||n===undefined||n==='')return'—';const v=Number(n);return isFinite(v)?v.toLocaleString('es-AR',{maximumFractionDigits:dec}):n;};
// Vencimiento de una fecha de entrega: 'vencida' (ya pasó), 'por-vencer' (hoy o
// en los próximos DIAS_POR_VENCER días) o ''. Solo cuenta si lo pendiente sigue abierto.
const DIAS_POR_VENCER=3;
function _isoLocal(d){return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0');}
function venceEstado(fecha,abierta){
  if(!abierta||!fecha) return '';
  const f=String(fecha).slice(0,10), hoy=new Date();
  if(f<_isoLocal(hoy)) return 'vencida';
  const lim=new Date(hoy); lim.setDate(lim.getDate()+DIAS_POR_VENCER);
  return f<=_isoLocal(lim)?'por-vencer':'';
}
// Clase para el <tr> y atributos (clase + aviso) para la celda de la fecha.
function venceFila(fecha,abierta){const e=venceEstado(fecha,abierta);return e?' fila-'+e:'';}
function venceCelda(fecha,abierta){
  const e=venceEstado(fecha,abierta); if(!e) return '';
  const dias=Math.round((new Date(String(fecha).slice(0,10)+'T00:00:00')-new Date(_isoLocal(new Date())+'T00:00:00'))/86400000);
  const txt=e==='vencida'?('Atrasada '+(-dias)+' día'+(dias===-1?'':'s')):(dias===0?'Vence hoy':'Vence en '+dias+' día'+(dias===1?'':'s'));
  return ' class="fecha-'+e+'" title="'+txt+'"';
}

// Confirmación con el estilo de la página. Devuelve una promesa: usar
// "if(!await confirmar('¿…?')) return;". La primera línea es la pregunta y el
// resto el detalle. Las acciones que borran o no se pueden deshacer van en rojo.
let _cfmAbierto=null;
function confirmar(msg){ return _dialogo(msg,null); }
// Borrado con "Deshacer": la fila desaparece enseguida, pero el DELETE recién
// se manda al servidor después de BORRAR_DEMORA_MS. Si en ese tiempo se toca
// "Deshacer", no se borra nada y la fila vuelve. Uso: en lugar de
// api(url,{method:'DELETE'}) llamar apiBorrar(url,'Categoría eliminada'); la
// promesa devuelve la respuesta del servidor, y si se deshace no se resuelve
// nunca (así el resto de la función, toast y recarga, no corre).
const BORRAR_DEMORA_MS=6000;
let _ultimoClicFila=null;
const _borradosPendientes=new Set();
document.addEventListener('click',function(e){
  if(e.target.closest&&!e.target.closest('.cfm-ov,.undo-t')) _ultimoClicFila=e.target.closest('tr');
},true);
function apiBorrar(url,texto){
  return new Promise(function(resolve){
    const fila=_ultimoClicFila; _ultimoClicFila=null;
    const dispPrev=fila?fila.style.display:'';
    if(fila) fila.style.display='none';
    let wrap=document.getElementById('undo-wrap');
    if(!wrap){ wrap=document.createElement('div'); wrap.id='undo-wrap'; document.body.appendChild(wrap); }
    const t=document.createElement('div');
    t.className='undo-t';
    t.innerHTML='<span></span><button type="button">Deshacer</button><i style="animation-duration:'+BORRAR_DEMORA_MS+'ms"></i>';
    t.querySelector('span').textContent=(texto||'Eliminado')+'.';
    wrap.appendChild(t);
    const pend={url:url,enviar:null};
    function enviar(){
      clearTimeout(tid); _borradosPendientes.delete(pend); t.remove();
      api(url,{method:'DELETE'}).then(function(res){
        if(!(res&&res.ok)&&fila&&fila.isConnected) fila.style.display=dispPrev;
        resolve(res);
      }).catch(function(){
        if(fila&&fila.isConnected) fila.style.display=dispPrev;
        resolve({ok:false,error:'No se pudo eliminar (error de conexión)'});
      });
    }
    pend.enviar=enviar;
    const tid=setTimeout(enviar,BORRAR_DEMORA_MS);
    _borradosPendientes.add(pend);
    t.querySelector('button').addEventListener('click',function(){
      clearTimeout(tid); _borradosPendientes.delete(pend); t.remove();
      if(fila) fila.style.display=dispPrev;
      toast('No se eliminó nada');
    });
  });
}
// Si se cierra o recarga la página con borrados en espera, se mandan ya.
window.addEventListener('pagehide',function(){
  _borradosPendientes.forEach(function(p){
    try{ fetch(p.url,{method:'DELETE',keepalive:true,headers:{'Content-Type':'application/json'}}); }catch(e){}
  });
  _borradosPendientes.clear();
});

// Pregunta con un campo de texto (reemplaza al prompt() del navegador).
// Devuelve el texto escrito, o null si se cancela.
function pedirTexto(msg,valor){ return _dialogo(msg,valor==null?'':String(valor)); }
function _dialogo(msg,texto){
  const conTexto=texto!==null;
  return new Promise(function(resolve){
    if(_cfmAbierto){ resolve(conTexto?null:false); return; }
    msg=String(msg||'');
    // Corta después del primer salto de línea o, si no hay, después de la primera pregunta.
    let corte=msg.indexOf('\n');
    if(corte<0){const q=msg.indexOf('? ');if(q>=0)corte=q+1;}
    const pregunta=corte<0?msg:msg.slice(0,corte), detalle=corte<0?'':msg.slice(corte).trim();
    const peligro=/eliminar|quitar|borrar|cancelar|desvincular|anular|no se puede deshacer/i.test(msg);
    const borra=(pregunta.match(/^\s*¿?\s*(eliminar|quitar|borrar)/i)||[])[1];
    const ov=document.createElement('div');
    ov.className='ov open cfm-ov';
    ov.innerHTML='<div class="mo cfm-mo'+(peligro?' cfm-peligro':'')+'" role="alertdialog" aria-modal="true">'
      +'<div class="cfm-tit"><span class="cfm-ic">'+(peligro?'!':'?')+'</span><span class="cfm-preg"></span></div>'
      +(detalle?'<div class="cfm-det"></div>':'')
      +(conTexto?'<div class="fg cfm-txt"><input type="text" autocomplete="off"></div>':'')
      +'<div class="ma"><button class="btn" data-r="0">Cancelar</button><button class="btn btn-p" data-r="1">'+(borra?'Sí, '+borra.toLowerCase():'Aceptar')+'</button></div></div>';
    ov.querySelector('.cfm-preg').textContent=pregunta;
    if(detalle) ov.querySelector('.cfm-det').textContent=detalle;
    const inp=conTexto?ov.querySelector('.cfm-txt input'):null;
    if(inp) inp.value=texto;
    const previo=document.activeElement;
    function cerrar(r){
      document.removeEventListener('keydown',tecla,true);
      const val=inp?inp.value:null;
      ov.remove(); _cfmAbierto=null;
      if(previo&&previo.focus) try{previo.focus();}catch(e){}
      resolve(conTexto?(r?val:null):r);
    }
    function tecla(e){
      if(e.key==='Escape'){e.preventDefault();e.stopPropagation();cerrar(false);}
      else if(e.key==='Enter'){e.preventDefault();e.stopPropagation();cerrar(document.activeElement===ov.querySelector('[data-r="0"]')?false:true);}
    }
    ov.addEventListener('click',function(e){
      if(e.target===ov){cerrar(false);return;}
      const b=e.target.closest('[data-r]'); if(b) cerrar(b.dataset.r==='1');
    });
    document.addEventListener('keydown',tecla,true);
    document.body.appendChild(ov); _cfmAbierto=ov;
    // En lo que borra, el foco arranca en Cancelar para que un Enter apurado no borre.
    if(inp){ inp.focus(); inp.select(); }
    else ov.querySelector(peligro?'[data-r="0"]':'[data-r="1"]').focus();
  });
}
const fmtD=s=>s?s.slice(0,10).split('-').reverse().join('/'):'—';
const fmtDH=s=>{if(!s)return'—';const f=s.slice(0,10).split('-').reverse().join('/');const h=s.slice(11,16);return h?f+' '+h:f;};
const stars=n=>'★'.repeat(n)+'☆'.repeat(5-n);
function fmtC(el){let v=el.value.replace(/\D/g,'');if(v.length>2)v=v.slice(0,2)+'-'+v.slice(2);if(v.length>11)v=v.slice(0,11)+'-'+v.slice(11);el.value=v.slice(0,13);}

async function api(url,o={}){
  const ctrl=new AbortController();
  // 35s: un poco mas que el busy_timeout de 30s del server, para no cortar
  // antes de que el server tenga chance de responder en horarios de mucho uso
  const tid=setTimeout(()=>ctrl.abort(new DOMException('El servidor tardó más de 35 segundos en responder ('+url.split('?')[0]+').','AbortError')),35000);
  try{
    const r=await fetch(url,{headers:{'Content-Type':'application/json'},signal:ctrl.signal,...o});
    clearTimeout(tid);
    // Si el server respondio HTML en vez de JSON (por ejemplo, un redirect a
    // /login porque la sesion expiro, o una pagina de error 500), r.json()
    // tira "Unexpected token '<'" — un error críptico que no dice nada util
    // al usuario. Lo detectamos por Content-Type y, si la sesion expiro,
    // mandamos a re-loguearse en vez de dejar que la tabla rompa.
    const ctype=(r.headers.get('content-type')||'');
    if(!ctype.includes('application/json')){
      if(r.redirected&&r.url.includes('/login')){
        toast('Tu sesión expiró. Volvé a iniciar sesión.','w');
        setTimeout(()=>{ location.href='/login'; },1200);
        return {error:'Sesión expirada'};
      }
      toast('El servidor devolvió una respuesta inesperada (código '+r.status+'). Probá de nuevo en un momento.','e');
      return {error:'Respuesta inesperada del servidor (HTTP '+r.status+')'};
    }
    const body=await r.json();
    if(r.status===401&&/[Ss]esi[oó]n/.test(body.error||'')){
      toast(body.error,'w');
      setTimeout(()=>{ location.href='/login'; },1200);
    }
    return body;
  }catch(e){
    clearTimeout(tid);
    // Distinguimos timeout (la operacion puede haber terminado igual en el
    // server) de un error de red real (server caido / sin wifi)
    e._isTimeout = e.name==='AbortError';
    throw e;
  }
}

function _ordenNum(o){
  const m = String(o==null?'':o).match(/-?\d+(\.\d+)?/);
  return m ? parseFloat(m[0]) : Infinity;
}
function sortOpsNumeric(arr){
  // Ordena por el número que aparece al inicio del campo "orden" (aunque
  // tenga texto, ej. "10-20. Torneado-Torneado" -> 10). A igualdad de
  // número, respeta el orden en que se cargaron (id ascendente).
  return (arr||[]).slice().sort(function(a,b){
    const na=_ordenNum(a.orden), nb=_ordenNum(b.orden);
    if(na!==nb) return na-nb;
    return (a.id||0)-(b.id||0);
  });
}
function toast(msg,t='g'){
  const d=document.createElement('div');
  const colors={g:['#EAF3DE','#27500A','#C0DD97'],e:['#FCEBEB','#791F1F','#F7C1C1'],w:['#FAEEDA','#633806','#FAC775']};
  const [bg,color,border]=colors[t]||colors.g;
  d.style.cssText=`position:fixed;bottom:20px;right:20px;z-index:9999;padding:9px 15px;border-radius:8px;font-size:13px;box-shadow:0 4px 12px rgba(0,0,0,.14);max-width:320px;background:${bg};color:${color};border:1px solid ${border}`;
  d.textContent=msg;document.body.appendChild(d);setTimeout(()=>d.remove(),3500);
}

function sb(s){const m={Pendiente:'ba','En proceso':'bb',Completada:'bg',Cancelada:'bk',Borrador:'bk',Enviado:'ba',Aprobado:'bg',Rechazado:'br',Facturado:'bb',Activo:'bg',Ingresado:'ba',Agotado:'bk',Operativa:'bg','En mantenimiento':'ba','Fuera de servicio':'br',Abierto:'br',Cerrado:'bk','Sin respuesta':'ba','OC Emitida':'bg',Cotizada:'bb',Rechazada:'br',Cerrada:'bk',Recibida:'bg','Recibida parcial':'ba',PROXIMO:'ba',VENCIDO:'br',ENTREGADO:'bg',ANULADO:'bk'};return `<span class="b ${m[s]||'bk'}">${s}</span>`;}
function pb(p){const m={Alta:'br',Crítica:'br',Media:'ba',Normal:'bg'};return `<span class="b ${m[p]||'bk'}">${p}</span>`;}
function stBar(s,mn,mx){const top=mx>0?mx:(mn*3||100);const pct=Math.min(100,Math.round(s/top*100));const c=s<=mn*.1?'#E24B4A':s<=mn?'#EF9F27':'#639922';return `<div class="sb-w"><div class="sb" style="width:${pct}%;background:${c}"></div></div>`;}
function stBadge(s,mn){if(mn<=0)return '<span class="b bk">Sin mínimo</span>';if(s<=mn*.1)return '<span class="b br">Crítico</span>';if(s<=mn)return '<span class="b ba">Bajo</span>';return '<span class="b bg">Normal</span>';}
function dot(e){const m={Operativa:'dot-g','En mantenimiento':'dot-a','Fuera de servicio':'dot-r'};return `<span class="dot ${m[e]||'dot-r'}"></span>`;}

// Badge "nube" de SC pendientes en el sidebar (módulo Compras)
async function updateSCBadge(){
  try{
    const r=await api('/api/solicitudes_compra/pendientes_count');
    const b=$('sc-badge');
    if(!b)return;
    if(r&&r.count>0){b.textContent=r.count>99?'99+':r.count;b.style.display='flex';}
    else{b.style.display='none';}
  }catch(e){ /* silencioso: no molestar al usuario si falla el polling */ }
}
updateSCBadge();
setInterval(updateSCBadge,60000); // refresco automático cada 60s

async function loadIndicadoresCompras(){
  const anioSel=$('ic-anio');
  if(anioSel && !anioSel.options.length){
    const cur=new Date().getFullYear();
    for(let y=cur;y>=cur-4;y--){const o=document.createElement('option');o.value=y;o.textContent=y;anioSel.appendChild(o);}
    anioSel.value=cur;
  }
  const anio=anioSel?anioSel.value:new Date().getFullYear();
  const body=$('ic-body');
  body.innerHTML='<div class="ld">Cargando...</div>';
  const d=await api('/api/dashboard/indicadores_compras?anio='+anio);
  if(!d.categorias||!d.categorias.length){body.innerHTML='<div class="em">Sin datos para el año seleccionado.</div>';return;}
  const pct=v=>v==null?'—':Math.round(v*100)+'%';
  let h='';
  d.categorias.forEach(cat=>{
    h+='<div class="card" style="margin-bottom:16px"><div class="ch"><span class="ct">'+cat.categoria+'</span></div>';
    h+='<div class="nowrap-tbl"><table><tr><th>Proveedor</th><th>Entregados</th><th>A tiempo</th><th>Aprobados</th><th>Incidentes</th><th>Pend. calidad</th><th>CE</th><th>IC</th><th>IPP</th></tr>';
    cat.proveedores.forEach(p=>{
      const t=p.total;
      h+='<tr><td><b>'+p.proveedor+'</b></td><td>'+fN(t.entregados)+'</td><td>'+t.a_tiempo+'</td><td>'+fN(t.aprobados)+'</td><td>'+t.incidentes+'</td>'
        +'<td>'+(t.pendientes?'<span style="color:var(--color-text-secondary)">'+fN(t.pendientes)+'</span>':'0')+'</td>'
        +'<td>'+pct(t.ce)+'</td><td>'+pct(t.ic)+'</td><td>'+pct(t.ipp)+'</td></tr>';
    });
    h+='</table></div></div>';
  });
  body.innerHTML=h;
}


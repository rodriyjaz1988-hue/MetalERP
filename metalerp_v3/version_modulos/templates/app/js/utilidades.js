// ── Enlace al manual de usuario en cada módulo (punto 16) ────────────────────
function abrirManual(p){ window.open('/manual#ch-'+p,'_blank'); }
(function(){
  document.querySelectorAll('.page[id^="p-"]').forEach(function(pg){
    var pt=pg.querySelector('.pt'); if(!pt || pt.querySelector('.man-link')) return;
    var k=pg.id.slice(2);
    var a=document.createElement('a'); a.className='man-link'; a.href='/manual#ch-'+k; a.target='_blank'; a.textContent='📖 Manual'; a.title='Abrir el capítulo del manual de este módulo';
    pt.appendChild(a);
  });
})();

// ── Embalado y etiquetado (punto 18) ─────────────────────────────────────────
// Code 128-B a SVG, sin librerías externas (funciona sin internet).
const _C128=['212222','222122','222221','121223','121322','131222','122213','122312','132212','221213','221312','231212','112232','122132','122231','113222','123122','123221','223211','221132','221231','213212','223112','312131','311222','321122','321221','312212','322112','322211','212123','212321','232121','111323','131123','131321','112313','132113','132311','211313','231113','231311','112133','112331','132131','113123','113321','133121','313121','211331','231131','213113','213311','213131','311123','311321','331121','312113','312311','332111','314111','221411','431111','111224','111422','121124','121421','141122','141221','112214','112412','122114','122411','142112','142211','241211','221114','413111','241112','134111','111242','121142','121241','114212','124112','124211','411212','421112','421211','212141','214121','412121','111143','111341','131141','114113','114311','411113','411311','113141','114131','311141','411131','211412','211214','211232','2331112'];
function code128SVG(txt,h){
  txt=String(txt||'').replace(/[^\x20-\x7E]/g,'?');
  const codes=[104]; let sum=104;
  for(let i=0;i<txt.length;i++){const c=txt.charCodeAt(i)-32; codes.push(c); sum+=c*(i+1);}
  codes.push(sum%103); codes.push(106);
  let x=10,bars='';
  codes.forEach(function(c){
    const pat=_C128[c];
    for(let i=0;i<pat.length;i++){const w=parseInt(pat[i]); if(i%2===0) bars+='<rect x="'+x+'" y="0" width="'+w+'" height="'+h+'"/>'; x+=w;}
  });
  const W=x+10;
  return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 '+W+' '+h+'" width="100%" height="'+h+'" preserveAspectRatio="none" fill="#000">'+bars+'</svg>';
}
let _etCtx={}, _etCola=[];
function abrirEtiquetasCola(lista){
  _etCola=(lista||[]).slice(1);
  if(lista&&lista.length) abrirEtiquetas(lista[0]);
}
function etCerrar(){
  closeMo('mo-etiquetas');
  if(_etCola.length){ const sig=_etCola.shift(); setTimeout(function(){abrirEtiquetas(sig);},150); }
}
function _etCantidades(){
  const tot=parseFloat($('et-total').value)||0;
  const nb=Math.max(1,parseInt($('et-bultos').value)||1);
  const xb=parseFloat($('et-xbulto').value)||tot;
  const out=[];
  for(let i=1;i<=nb;i++) out.push(i<nb?xb:Math.round((tot-xb*(nb-1))*1000)/1000);
  return out.filter(function(q){return q>0;});
}
// Guarda los bultos como cajones del lote. cerrar=true: cierra el modal al terminar.
async function etGuardarBultos(cerrar){
  if(!_etCtx.lote_id) return true;
  const cants=_etCantidades();
  if(!cants.length){toast('Ingresá la cantidad total','w');return false;}
  const res=await api('/api/lotes/'+_etCtx.lote_id+'/bultos',{method:'POST',
    body:JSON.stringify({cantidades:cants,agregar:!!_etCtx.agregar})});
  if(!res||!res.ok){toast((res&&res.error)||'No se pudieron guardar los cajones','e');return false;}
  toast(res.cajones.length+' cajón(es) guardados en el lote '+(_etCtx.lote||'')
    +(res.sin_bulto>0.0001?' — quedan '+fN(res.sin_bulto)+' sin bulto':''));
  _etCtx.agregar=true; _etCtx.guardado=true;
  if(typeof _lotesTab!=='undefined'&&_lotesTab==='cajones') loadCajones();
  if(cerrar) etCerrar();
  return true;
}
function abrirEtiquetas(o){
  o=o||{}; _etCtx=o;
  $('et-ctx').textContent='Origen: '+(o.origen||'—')+(o.referencia?' · '+o.referencia:'');
  $('et-total').value=o.cantidad||'';
  $('et-unidad').value=o.unidad||'';
  $('et-bultos').value=1;
  $('et-xbulto').value=o.cantidad||'';
  $('et-desc').value=o.descripcion||'';
  $('et-code').value=o.codigo_barras||'';
  $('et-ref').value=o.referencia||'';
  $('et-lote').value=o.lote||'';
  etRecalc('total');
  // "Piezas por cajón" del artículo: arma los bultos solo
  if(o.capacidad_cajon>0 && o.cantidad>0){ $('et-xbulto').value=o.capacidad_cajon; etRecalc('xbulto'); }
  const conLote=!!o.lote_id;
  $('et-caj-wrap').style.display=conLote?'flex':'none';
  $('et-b-guardar').style.display=conLote?'':'none';
  $('et-caj').checked=conLote;
  $('et-caj-lote').textContent=o.lote||'';
  openMo('mo-etiquetas');
}
function etRecalc(src){
  const tot=parseFloat($('et-total').value)||0;
  let nb=Math.max(1,parseInt($('et-bultos').value)||1);
  let xb=parseFloat($('et-xbulto').value)||0;
  if(src==='xbulto' && xb>0 && tot>0){ nb=Math.ceil(tot/xb-1e-9); $('et-bultos').value=nb; }
  else if(src==='bultos' || src==='total'){ xb=tot>0?Math.ceil(tot/nb*1000)/1000:0; $('et-xbulto').value=xb||''; }
  const ult=tot>0&&xb>0?Math.round((tot-xb*(nb-1))*1000)/1000:0;
  $('et-prev').textContent=tot>0?('Se generarán '+nb+' etiqueta(s)'+(nb>1&&ult>0&&ult!==xb?' — el último bulto lleva '+ult:'')+'.'):'';
}
function imprimirEtiquetas(){
  // Los bultos se guardan como cajones del lote (si corresponde) además de imprimirse.
  if(_etCtx.lote_id && $('et-caj').checked && !_etCtx.guardado) etGuardarBultos(false);
  const tot=parseFloat($('et-total').value)||0;
  const nb=Math.max(1,parseInt($('et-bultos').value)||1);
  const xb=parseFloat($('et-xbulto').value)||tot;
  if(!(tot>0)){toast('Ingresá la cantidad total','w');return;}
  const un=$('et-unidad').value, desc=$('et-desc').value, ref=$('et-ref').value, lote=$('et-lote').value;
  const base=($('et-code').value||lote||ref||'S-REF').trim();
  const hoy=new Date().toLocaleDateString('es-AR');
  const esc=function(t){return String(t==null?'':t).replace(/[&<>]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;'}[c];});};
  let pages='';
  for(let i=1;i<=nb;i++){
    const q=(i<nb)?xb:Math.round((tot-xb*(nb-1))*1000)/1000;
    const cod=base+'-'+i+'/'+nb;
    pages+='<div class="et"><div class="h">Mecanizado Ituzaingo<span>'+esc(_etCtx.origen||'')+'</span></div>'
      +'<div class="d">'+esc(desc||'—')+'</div>'
      +'<div class="r"><b>Cant.:</b> '+q+' '+esc(un)+'<span class="bn">Bulto '+i+' / '+nb+'</span></div>'
      +'<div class="r"><b>Ref.:</b> '+esc(ref||'—')+'</div>'
      +'<div class="r"><b>Lote:</b> '+esc(lote||'—')+'<span class="bn" style="font-weight:400">'+hoy+'</span></div>'
      +'<div class="bc">'+code128SVG(cod,46)+'</div><div class="ct">'+esc(cod)+'</div></div>';
  }
  const w=window.open('','_blank');
  if(!w){toast('El navegador bloqueó la ventana de impresión. Permití ventanas emergentes.','w');return;}
  w.document.write('<!doctype html><html><head><meta charset="utf-8"><title>Etiquetas</title><style>'
    +'@page{size:100mm 60mm;margin:0}body{margin:0;font-family:Arial,sans-serif}'
    +'.et{width:100mm;height:60mm;box-sizing:border-box;padding:3mm 4mm;page-break-after:always;overflow:hidden}'
    +'.h{font-weight:bold;font-size:11pt;border-bottom:.4mm solid #000;padding-bottom:1mm;display:flex;justify-content:space-between}.h span{font-size:8pt;font-weight:normal}'
    +'.d{font-size:11pt;font-weight:bold;margin:1.5mm 0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}'
    +'.r{font-size:9pt;margin:.6mm 0;white-space:nowrap;display:flex;justify-content:space-between}.bn{font-weight:bold;font-size:11pt}'
    +'.bc{margin-top:1.5mm;height:12mm}.bc svg{height:12mm}.ct{text-align:center;font-size:8pt;letter-spacing:.3mm}'
    +'</style></head><body>'+pages+'<script>window.onload=function(){setTimeout(function(){window.print();},250);};<\/script></body></html>');
  w.document.close();
}

// ── Control de versión cliente/servidor ──────────────────────────────────────
const APP_VER='150';
(async function(){
  try{
    const r=await fetch('/api/version'); let v=null;
    if(r.ok){ v=(await r.json()).version; }
    if(v!==APP_VER){
      const b=document.createElement('div');
      b.style.cssText='position:fixed;top:0;left:0;right:0;z-index:99999;background:#FCEBEB;color:#791F1F;border-bottom:1px solid #F7C1C1;padding:8px 14px;font-size:13px;text-align:center';
      b.innerHTML='⚠ El servidor no está actualizado (esta pantalla es la v'+APP_VER+' y el servidor '+(v?'es la v'+v:'no tiene versión')+'). Cerrá el servidor y volvé a iniciarlo con <b>python server.py</b> (si usás MetalERP.exe, hay que regenerarlo con el server.py nuevo). Mientras tanto fallarán funciones nuevas con error 404. <a href="#" onclick="this.parentNode.remove();return false" style="margin-left:10px">cerrar</a>';
      document.body.appendChild(b);
    }
  }catch(e){}
})();

// ── Red de seguridad del permiso "ver valores monetarios" (punto 11) ─────────
// Toda columna de tabla o campo de formulario cuyo título sea monetario se
// oculta automáticamente para quien no tiene el permiso, aunque se agregue en
// el futuro. (Complementa a fmtM/fmtMD, que enmascaran los importes.)
function _esTituloMonetario(t){ t=(t||'').trim(); if(!t) return false; if(/^(precio|prec\.|costo|monto|importe|subtotal|facturad|valor|total$)/i.test(t)||/\(\$\)|\$$|precio|costo (mat|mo|terc|total|repar)|total con iva|valor mano|iva \(%\)/i.test(t)) return !/centro de costo|condici[oó]n|recalcul/i.test(t); return false; }
// Zonas donde el barrido por heurística NO debe entrar: hablan DE los campos
// monetarios en vez de mostrar importes, y borrarlas rompería la pantalla.
//   · Auditoría: lista nombres de campos que cambiaron (el valor ya viene
//     enmascarado desde el servidor).
//   · Usuarios/Roles: ahí vive el checkbox "Puede ver valores monetarios",
//     que ES el permiso, no un valor.
function _zonaExentaMonetario(el){
  return !!(el && el.closest && el.closest('#p-auditoria,#mo-auditoria,#p-usuarios,#mo-permisos,#mo-rol'));
}

// Último recurso. Lo que se escribe con monOnly/thM/tdM ya no llega acá; esto
// cubre el HTML viejo que todavía no se migró. BORRA los nodos: ocultarlos
// dejaba el dato en el DOM, al alcance del inspector y del "ver código".
function _borrarMonetarioDOM(root){
  if(VER_MONETARIO) return;
  (root||document).querySelectorAll('table').forEach(function(tb){
    if(_zonaExentaMonetario(tb)) return;
    const rows=Array.from(tb.rows); if(!rows.length) return;
    const hr=rows.find(function(r){return r.querySelector('th');}); if(!hr) return;
    const ths=Array.from(hr.cells); const idx=[];
    ths.forEach(function(th,i){ if(_esTituloMonetario(th.textContent) && !th.dataset.monOk) idx.push(i); });
    if(!idx.length) return;
    rows.forEach(function(r){
      if(r.cells.length!==ths.length) return;
      // De atrás hacia adelante: borrar corre los índices de los siguientes.
      idx.slice().reverse().forEach(function(i){ r.cells[i].remove(); });
    });
  });
  (root||document).querySelectorAll('.fg').forEach(function(fg){
    if(_zonaExentaMonetario(fg)) return;
    const lb=fg.querySelector('label'); if(!lb) return;
    const t=lb.textContent.replace(/\s+/g,' ').trim();
    if(/\(\$\)|^precio|^costo (mat|mo|terc|rep)|^subtotal|^total con|^valor mano|^iva \(%\)|^precio acordado|^costo materiales/i.test(t) && !/centro de costo|condici[oó]n/i.test(t)){ _registrarMonBorrado(fg); fg.remove(); }
  });
  // HTML estático marcado a mano por quien lo escribió.
  (root||document).querySelectorAll('[data-monetario]').forEach(function(el){
    if(!_zonaExentaMonetario(el)){ _registrarMonBorrado(el); el.remove(); }
  });
}
if(!VER_MONETARIO){
  // Con setTimeout y no requestAnimationFrame: rAF no se ejecuta mientras la
  // pestaña está en segundo plano, así que el primer lote de mutaciones
  // dejaba _monT tomado para siempre y el barrido no volvía a correr nunca.
  // Resultado: si los datos cargaban con la pestaña oculta, al volver a ella
  // las columnas monetarias quedaban a la vista.
  let _monT=null;
  const _mo=new MutationObserver(function(){
    if(_monT) return;
    _monT=setTimeout(function(){ _monT=null; _borrarMonetarioDOM(document); }, 0);
  });
  _mo.observe(document.body,{childList:true,subtree:true});
  document.addEventListener('DOMContentLoaded',function(){_borrarMonetarioDOM(document);});
  _borrarMonetarioDOM(document);
}


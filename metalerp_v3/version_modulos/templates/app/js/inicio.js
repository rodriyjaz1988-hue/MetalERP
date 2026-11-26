// ── Init ──────────────────────────────────────────────────────────────────────
// ── Global error catcher ─────────────────────────────────────────────────────
window.onerror = function(msg, src, line, col, err) {
  console.error('[MetalERP] JS Error:', msg, 'at', src+':'+line+':'+col, err);
  // Show visible error in page
  var dbg = document.getElementById('_dbg');
  if (!dbg) {
    dbg = document.createElement('div');
    dbg.id = '_dbg';
    dbg.style.cssText = 'position:fixed;bottom:0;left:0;right:0;background:#fee;color:#900;font-size:11px;padding:4px 8px;z-index:99999;border-top:2px solid #f00;max-height:80px;overflow-y:auto';
    document.body.appendChild(dbg);
  }
  dbg.innerHTML += '<div>ERROR: ' + msg + ' (L' + line + ')</div>';
  return false;
};
window.onunhandledrejection = function(e) {
  console.error('[MetalERP] Unhandled rejection:', e.reason);
  var dbg = document.getElementById('_dbg');
  if (!dbg) {
    dbg = document.createElement('div');
    dbg.id = '_dbg';
    dbg.style.cssText = 'position:fixed;bottom:0;left:0;right:0;background:#fee;color:#900;font-size:11px;padding:4px 8px;z-index:99999;border-top:2px solid #f00;max-height:80px;overflow-y:auto';
    document.body.appendChild(dbg);
  }
  dbg.innerHTML += '<div>PROMISE ERROR: ' + String(e.reason) + '</div>';
};

setupRoles();

// Un ítem del menú está permitido si ni él ni su contenedor fueron ocultados por
// permisos (no cuenta el plegado de secciones).
function _niPermitido(ni){
  for(let el=ni; el && !el.classList.contains('sidebar'); el=el.parentElement){
    if(el.style.display==='none') return false;
  }
  return true;
}

// Menú lateral plegable: clic en el nombre de la sección la abre o la cierra.
const _menuSec=[];
(function iniciarMenuPlegable(){
  let plegadas=[];
  try{ plegadas=JSON.parse(localStorage.getItem('menu_plegado')||'[]'); }catch(e){}
  document.querySelectorAll('.sidebar .sl').forEach(function(sl){
    const nombre=sl.textContent.trim(), items=[];
    for(let el=sl.nextElementSibling; el && !el.classList.contains('sl') && !el.classList.contains('sf'); el=el.nextElementSibling) items.push(el);
    sl.classList.add('sl-pleg');
    sl.insertAdjacentHTML('beforeend','<span class="sl-aviso" title="Hay avisos en esta sección"></span><span class="sl-chev">▼</span>');
    const sec={sl:sl,nombre:nombre,items:items};
    _menuSec.push(sec);
    if(plegadas.includes(nombre)) _plegarSeccion(sec,true,false);
    sl.addEventListener('click',function(){ _plegarSeccion(sec,!sl.classList.contains('plegada'),true); });
  });
  // Punto rojo en la sección plegada si adentro hay un contador visible (ej. Compras).
  const actualizarAvisos=function(){
    _menuSec.forEach(function(sec){
      const hay=sec.items.some(function(el){
        return [].some.call(el.querySelectorAll('.ni-badge'),function(b){return b.style.display!=='none' && b.textContent.trim()!=='0';});
      });
      sec.sl.classList.toggle('con-aviso',hay);
    });
  };
  new MutationObserver(actualizarAvisos).observe(document.querySelector('.sidebar'),{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:['style']});
  actualizarAvisos();
})();
function _plegarSeccion(sec,plegar,guardar){
  sec.sl.classList.toggle('plegada',plegar);
  sec.items.forEach(function(el){ el.classList.toggle('ni-plegado',plegar); });
  if(!guardar) return;
  try{
    localStorage.setItem('menu_plegado',JSON.stringify(_menuSec.filter(function(x){return x.sl.classList.contains('plegada');}).map(function(x){return x.nombre;})));
  }catch(e){}
}

// La pantalla actual queda en la dirección (…/#ordenes): al recargar (F5) se vuelve
// a ella, Atrás/Adelante del navegador recorren las pantallas visitadas y la
// pestaña muestra su nombre.
let _pantallaActual=null, _pantallaSinHistorial=null;
function irAPantalla(p){
  const ni=document.querySelector('.ni[data-p="'+p+'"]');
  if(!ni || !_niPermitido(ni)) return false;
  ni.click();
  return true;
}
(function iniciarPantallaEnDireccion(){
  function alActivar(p){
    if(p===_pantallaActual) return;
    const primera=_pantallaActual===null;
    _pantallaActual=p;
    const sp=document.querySelector('.ni[data-p="'+p+'"] span');
    document.title=(sp?sp.textContent.trim()+' · ':'')+'MetalERP';
    // Si la pantalla está en una sección plegada del menú, abrirla.
    _menuSec.forEach(function(sec){
      if(sec.sl.classList.contains('plegada') && sec.items.some(function(el){return el.matches('.ni[data-p="'+p+'"]')||el.querySelector('.ni[data-p="'+p+'"]');}))
        _plegarSeccion(sec,false,true);
    });
    if(_pantallaSinHistorial===p){ _pantallaSinHistorial=null; return; }
    if(location.hash.slice(1)===p) return;
    if(primera) history.replaceState(null,'','#'+p);
    else history.pushState(null,'','#'+p);
  }
  const obs=new MutationObserver(function(ms){
    ms.forEach(function(m){ if(m.target.classList.contains('active')) alActivar(m.target.id.slice(2)); });
  });
  document.querySelectorAll('.page').forEach(function(pg){ obs.observe(pg,{attributes:true,attributeFilter:['class']}); });
  window.addEventListener('popstate',function(){
    const p=location.hash.slice(1);
    if(!p || p===_pantallaActual) return;
    _pantallaSinHistorial=p;
    if(!irAPantalla(p)){ _pantallaSinHistorial=null; history.replaceState(null,'','#'+_pantallaActual); }
  });
})();

// Atajos de teclado (fuera de campos de texto):
//   /  va al primer buscador de la pantalla   N  botón "Nuevo/Agregar/+" de la pantalla
//   Esc cierra la ventana abierta             ?  muestra esta ayuda
function _visible(el){ return !!(el && el.getClientRects().length && getComputedStyle(el).visibility!=='hidden'); }
function _ventanaAbierta(){
  const abiertas=[].filter.call(document.querySelectorAll('.ov.open'),_visible);
  return abiertas.length?abiertas[abiertas.length-1]:null;
}
document.addEventListener('keydown',function(e){
  if(e.defaultPrevented||e.ctrlKey||e.metaKey||e.altKey||_cfmAbierto) return;
  const pop=document.getElementById('ss-pop'); if(pop&&_visible(pop)) return;
  const t=e.target, escribiendo=t&&(t.isContentEditable||/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName));
  if(e.key==='Escape'){
    const ov=_ventanaAbierta(); if(!ov) { if(escribiendo&&t.blur) t.blur(); return; }
    e.preventDefault();
    if(ov.id) closeMo(ov.id); else ov.classList.remove('open');
    return;
  }
  if(escribiendo||_ventanaAbierta()) return;
  const pg=document.querySelector('.page.active'); if(!pg) return;
  if(e.key==='/'){
    const campos=[].filter.call(pg.querySelectorAll('input[type=text],input[type=search],input:not([type])'),function(i){
      return _visible(i)&&!i.disabled&&!i.readOnly&&(i.classList.contains('sel-fil')||/buscar|🔍/i.test(i.placeholder||''));
    });
    if(campos.length){ e.preventDefault(); campos[0].focus(); campos[0].select&&campos[0].select(); }
  } else if(e.key==='n'||e.key==='N'){
    const btns=[].filter.call(pg.querySelectorAll('button'),function(b){
      return _visible(b)&&!b.disabled&&/^\s*(\+|nuev[oa]\b|agregar\b)/i.test(b.textContent.replace(/\s+/g,' ').trim());
    });
    // Preferir el del encabezado de la pantalla.
    const b=btns.find(function(x){return x.closest('.vhead');})||btns[0];
    if(b){ e.preventDefault(); b.click(); }
  } else if(e.key==='?'){
    e.preventDefault();
    toast('Atajos: / buscar · N nuevo · Esc cerrar ventana','b');
  }
});

// Al entrar: la pantalla de la dirección (si el usuario tiene permiso) o el
// primer módulo visible del menú según el rol.
(function navigateToFirstVisibleModule() {
  const pedida=location.hash.slice(1);
  if(pedida && irAPantalla(pedida)) return;
  const allNi = document.querySelectorAll('.ni[data-p]');
  let firstVisible = null;
  for (const ni of allNi) {
    if (_niPermitido(ni)) {
      firstVisible = ni;
      break;
    }
  }
  if (!firstVisible) { loadDashOperativo(); return; }

  const p = firstVisible.dataset.p;

  // Marcar el nav item como activo
  document.querySelectorAll('.ni').forEach(n => n.classList.remove('active'));
  document.querySelectorAll('.page').forEach(pg => pg.classList.remove('active'));
  firstVisible.classList.add('active');
  const page = document.getElementById('p-' + p);
  if (page) page.classList.add('active');

  // Cargar el módulo
  load(p);
})();

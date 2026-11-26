// ── OC Clientes helpers ───────────────────────────────────────────────────────
async function goToOT(otId){
  document.querySelectorAll('.ni').forEach(function(n){n.classList.remove('active');});
  document.querySelectorAll('.page').forEach(function(p){p.classList.remove('active');});
  const nav=document.querySelector('[data-p="ordenes"]');
  if(nav) nav.classList.add('active');
  const page=$('p-ordenes');
  if(page) page.classList.add('active');

  // Aseguramos que la OT sea visible: si había un filtro de estado activo
  // (En proceso / Pendiente / Completada) que la esconda, lo sacamos y
  // volvemos a "Todas" antes de buscarla en la lista.
  const tabTodas=document.querySelector('#ot-tabs .tab[data-e=""]');
  if(tabTodas && !tabTodas.classList.contains('active')){
    document.querySelectorAll('#ot-tabs .tab').forEach(function(t){t.classList.remove('active');});
    tabTodas.classList.add('active');
    otF='';
  }
  // También limpiamos los filtros de código/cliente/OC/total, por si estaban
  // ocultando la OT a la que estamos navegando.
  clearFiltrosOT(true);
  await loadOT();

  // Remarcar la fila de la OT vinculada
  const row=$('ot-row-'+otId);
  if(row){
    row.scrollIntoView({behavior:'smooth',block:'center'});
    row.classList.remove('ot-row-flash');
    void row.offsetWidth; // reinicia la animación si ya se había disparado antes
    row.classList.add('ot-row-flash');
    setTimeout(function(){row.classList.remove('ot-row-flash');},2500);
  }
}

// ── Global id caches (populated when each module loads) ──────────────────────
let _ot_cache=new Map(),_mat_cache=new Map(),_mat_cache_pt=new Map(),
    _usr_cache=new Map(),_occ_cache=new Map(),_oc_cache=new Map();

function delUsrById(id){
  const r=_usr_cache.get(parseInt(id));
  delUsr(id,r?r.username:'usuario');
}
async function aprobarOC(id){
  const r=_oc_cache.get(parseInt(id));
  if(!await confirmar('¿Aprobar OC '+(r?r.numero:'#'+id)+'?'))return;
  const res=await api('/api/ordenes_compra/'+id+'/aprobar',{method:'POST',body:JSON.stringify({})});
  if(res.ok){toast('OC aprobada');loadOCs();}
  else toast(res.error||'Error','e');
}



// ── Operaciones tercerizadas ──────────────────────────────────────────────────
function toggleTercOp(prefix){
  const cb=document.getElementById(prefix+'-terc');
  if(!cb) return;
  const checked=cb.checked;
  const propios=document.getElementById(prefix+'-campos-propios');
  const terc=document.getElementById(prefix+'-campos-terc');
  const mats=document.getElementById(prefix+'-mats-section');
  if(propios) propios.style.display=checked?'none':'grid';
  if(terc)    terc.style.display=checked?'grid':'none';
  // La sección de materiales/productos como insumo se muestra siempre,
  // tercerizada o no: una operación tercerizada también puede necesitar
  // especificar qué material o producto semielaborado se le manda al
  // proveedor como insumo para que haga el trabajo.
  if(mats)    mats.style.display='block';

  // Si es tercerizada, el formulario debe mostrar solo: N° de orden, Nombre,
  // Descripción, Precio acordado, Proveedor y Plazo de entrega. El resto de
  // los campos "propios" (máquina, tiempos, observaciones, volumen agrupado)
  // se ocultan por completo.
  ['catm','maq','set','cic','obs'].forEach(function(suf){
    const el=document.getElementById(prefix+'-'+suf);
    if(!el) return;
    const wrap=el.closest('.fg')||el;
    wrap.style.display=checked?'none':'';
  });
  const volWrap=document.getElementById(prefix+'-vol-agrup-wrap');
  if(volWrap) volWrap.style.display=checked?'none':'';
}

// ── Volumen agrupado (recalculo de cantidad requerida por operación) ──────────
function toggleVolAgrupOp(prefix, force){
  const btn=document.getElementById(prefix+'-vol-agrup-btn');
  const campo=document.getElementById(prefix+'-vol-agrup-campo');
  if(!btn||!campo) return;
  const activo = force!==undefined ? force : !btn.classList.contains('btn-p');
  btn.classList.toggle('btn-p', activo);
  campo.style.display = activo?'block':'none';
  if(!activo){
    const v=document.getElementById(prefix+'-vol-agrup-valor');
    if(v) v.value='';
  }
}

// El proveedor de una operacion tercerizada se elige con un buscador
// (input de texto + lista filtrada), no con un select: la lista de
// proveedores es larga y buscar por razon social es mas rapido que scrollear.
// El id elegido queda en el input hidden '<prefix>-prv', asi que el resto del
// codigo lo sigue leyendo igual que antes.
async function loadTercProv(prefix){
  if(!document.getElementById(prefix+'-prv')) return;  // no existe en este modal
  if(!_prov.length)_prov=await api('/api/proveedores');
}

// Deja el buscador mostrando el proveedor 'id' (o vacio si es null).
function setProvOp(prefix,id){
  const hid=document.getElementById(prefix+'-prv');
  const txt=document.getElementById(prefix+'-prv-search');
  if(!hid||!txt) return;
  const p=id?_prov.find(function(r){return r.id==id;}):null;
  hid.value=p?p.id:'';
  txt.value=p?p.razon:'';
  const cont=document.getElementById(prefix+'-prv-results');
  if(cont){cont.style.display='none';cont.innerHTML='';}
}

function filtrarProvOp(prefix){
  const txt=document.getElementById(prefix+'-prv-search');
  const cont=document.getElementById(prefix+'-prv-results');
  if(!txt||!cont) return;
  const q=(txt.value||'').toLowerCase().trim();
  // Si el usuario borro el texto, se borra tambien el proveedor elegido.
  if(!q) document.getElementById(prefix+'-prv').value='';
  const lista=q?_prov.filter(function(r){
    return (r.razon||'').toLowerCase().includes(q)
      ||(r.contacto||'').toLowerCase().includes(q);
  }):_prov;
  _novotResultsRender(cont,lista,function(r){return r.razon;},function(r){
    document.getElementById(prefix+'-prv').value=r.id;
    txt.value=r.razon;
    cont.style.display='none';cont.innerHTML='';
  });
}



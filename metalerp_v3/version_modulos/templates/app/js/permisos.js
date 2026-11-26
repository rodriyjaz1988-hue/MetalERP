// ── Permisos de usuario ────────────────────────────────────────────────────────
const MODULOS_SISTEMA = [
  {k:'dash_operativo',    l:'Dashboard Producción'},
  {k:'dash_economico',    l:'Dashboard Económico'},
  {k:'ordenes',           l:'Órdenes de trabajo'},
  {k:'procesos',          l:'Procesos / Productos'},
  {k:'ctrl_prod',         l:'Control de producción'},
  {k:'ops_sector',        l:'Operaciones por sector'},
  {k:'scheduling',        l:'Scheduling de producción'},
  {k:'novedades_ot',      l:'Novedades por OT'},
  {k:'mrp',               l:'Planificación MRP'},
  {k:'requerimientos_productivos', l:'Requerimientos productivos'},
  {k:'dash_requerimientos', l:'Dashboard Requerimientos'},
  {k:'maquinas',          l:'Máquinas'},
  {k:'rrhh',              l:'Recursos humanos'},
  {k:'rendimiento',       l:'Rendimiento operarios'},
  {k:'inventario',        l:'Inventario'},
  {k:'movimientos',       l:'Movimientos'},
  {k:'lotes',             l:'Lotes'},
  {k:'remitir',           l:'Remitir a cliente'},
  {k:'remitos_emitidos',  l:'Remitos emitidos'},
  {k:'presupuestos',      l:'Presupuestos'},
  {k:'clientes',          l:'Clientes'},
  {k:'oc_clientes',       l:'Pedidos de clientes'},
  {k:'pronostico_ventas', l:'Pronóstico de ventas'},
  {k:'solicitudes',       l:'Compras'},
  {k:'indicadores_compras', l:'Indicadores de compras'},
  {k:'recepciones',       l:'Recepción de material/insumo'},
  {k:'proveedores',       l:'Proveedores'},
  {k:'ott',               l:'OTT — Terceros'},
  {k:'configuracion',     l:'Configuración'},
  {k:'carga_masiva',      l:'Carga masiva'},
];
// Valor del permiso de un módulo. "Indicadores de compras" no tuvo casilla
// propia hasta 2026-10: los usuarios y roles guardados antes no traen la
// clave, y heredan lo que tengan en Compras (mismo criterio que el servidor,
// ver _permisos_sesion en server.py).
function _permMod(perms,k){
  const v=perms['mod_'+k];
  if(v===undefined && k==='indicadores_compras') return perms['mod_solicitudes'];
  return v;
}

async function openPermisos(uid, username){
  document.getElementById('perm-uid').value = uid;
  document.getElementById('perm-username').textContent = username;
  document.getElementById('perm-modulos').innerHTML = '<div class="ld">Cargando...</div>';
  openMo('mo-permisos');
  const perms = await api('/api/usuarios/'+uid+'/permisos');
  let h = '<div style="display:grid;grid-template-columns:1fr 1fr;gap:4px">';
  MODULOS_SISTEMA.forEach(function(m){
    const checked = _permMod(perms,m.k) !== '0';
    h += '<label style="display:flex;align-items:center;gap:6px;font-size:12px;cursor:pointer;padding:3px 0">'
      + '<input type="checkbox" data-perm="mod_'+m.k+'" '+(checked?'checked':'')+'>'
      + m.l + '</label>';
  });
  h += '</div>';
  h += '<div style="margin-top:12px;padding-top:10px;border-top:1px solid var(--color-border-tertiary)">';
  h += '<label style="display:flex;align-items:center;gap:8px;font-size:12px;cursor:pointer">';
  const verMon = perms['ver_monetario'] !== '0';
  h += '<input type="checkbox" id="perm-ver-mon" '+(verMon?'checked':'')+' style="width:15px;height:15px">';
  h += 'Puede ver valores monetarios (precios, costos, facturación)</label>';
  // El asistente no viene habilitado: lo da un admin (los admin siempre lo tienen).
  h += '<label style="display:flex;align-items:center;gap:8px;font-size:12px;cursor:pointer;margin-top:6px">';
  h += '<input type="checkbox" id="perm-ia" '+(perms['ia']==='1'?'checked':'')+' style="width:15px;height:15px">';
  h += 'Puede usar el asistente IA (Mártin) <span style="color:var(--color-text-secondary)">· solo ve los módulos de arriba y, sin importes, no los ve</span></label></div>';
  document.getElementById('perm-modulos').innerHTML = h;
}

async function savePermisos(){
  const uid = document.getElementById('perm-uid').value;
  const checks = document.querySelectorAll('#perm-modulos input[data-perm]');
  const payload = {};
  checks.forEach(function(c){ payload[c.dataset.perm] = c.checked ? '1' : '0'; });
  payload['ver_monetario'] = document.getElementById('perm-ver-mon').checked ? '1' : '0';
  payload['ia'] = document.getElementById('perm-ia').checked ? '1' : '0';
  const res = await api('/api/usuarios/'+uid+'/permisos',{method:'POST',body:JSON.stringify(payload)});
  if(res.ok){ toast('Permisos guardados'); closeMo('mo-permisos'); loadUsr(); }
  else toast(res.error||'Error','e');
}




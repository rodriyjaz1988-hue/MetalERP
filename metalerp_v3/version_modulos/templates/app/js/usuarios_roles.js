// ── Usuarios ──────────────────────────────────────────────────────────────────
async function loadUsr() {
  const rows = await api('/api/usuarios');
  if (!rows.length) {
    $('usr-list').innerHTML = '<div class="em">No hay usuarios.</div>';
    return;
  }
  let h = '<table><tr><th>Username</th><th>Nombre</th><th>Rol</th><th>Estado</th><th>Creado</th><th></th></tr>';
  rows.forEach(r => {
    // Aquí está el mapeo correcto que incluye logística
    const rc = {
      admin: 'ra',
      operario: 'ro',
      vendedor: 'rv',
      almacen: 'rm',
      logistica: 'rl' 
    };
    
    h += `<tr>
      <td><b>${r.username}</b></td>
      <td>${r.nombre}</td>
      <td><span class="rb ${rc[r.rol] || 'ro'}">${r.rol}</span></td>
      <td>${r.activo ? '<span class="b bg">Activo</span>' : '<span class="b bk">Inactivo</span>'}</td>
      <td>${fmtD(r.creado)}</td>
      <td style="display:flex;gap:4px">
        <button class="btn btn-s" onclick="editUsrById(${r.id})">Editar</button>
        <button class="btn btn-s" onclick="openPermisos(${r.id},'${r.username}')">Permisos</button>
        <button class="btn btn-s btn-d" onclick="delUsrById(${r.id})">Desactivar</button>
      </td>
    </tr>`;
  });
  $('usr-list').innerHTML = h + '</table>';
  const _urows = await api('/api/usuarios');
  _usr_cache = new Map(_urows.map(r => [r.id, r]));
}

// ── Roles editables (Configuración) ─────────────────────────────────────────
let _roles=[];
async function _cargarRolesSelect(sel, valor){
  const rs=await api('/api/roles');
  if(Array.isArray(rs)) _roles=rs;
  const s=$('usr-rol');
  s.innerHTML=_roles.map(function(r){return '<option value="'+r.nombre+'">'+r.nombre+(r.es_sistema?'':' (personalizado)')+'</option>';}).join('');
  if(valor) s.value=valor;
}
async function loadRoles(){
  const rs=await api('/api/roles');
  if(!Array.isArray(rs)){ $('cfg-roles').innerHTML='<div class="em">No se pudieron cargar los roles.</div>'; return; }
  _roles=rs;
  let h='<table><tr><th>Rol</th><th>Rol base</th><th>Descripción</th><th>Usuarios</th><th>Módulos ocultos</th><th>Valores monetarios</th><th>Asistente IA</th><th></th></tr>';
  rs.forEach(function(r){
    const ocultos=MODULOS_SISTEMA.filter(function(m){return _permMod(r.permisos||{},m.k)==='0';}).length;
    const mon=(r.permisos||{})['ver_monetario']==='0'?'<span class="b br">No</span>':'<span class="b bg">Sí</span>';
    const ia=(r.base_rol==='admin'||(r.permisos||{})['ia']==='1')?'<span class="b bg">Sí</span>':'<span class="b bk">No</span>';
    h+='<tr><td><b>'+r.nombre+'</b>'+(r.es_sistema?' <span class="b bk" style="font-size:10px">sistema</span>':'')+'</td>'
      +'<td>'+r.base_rol+'</td><td style="font-size:12px">'+(r.descripcion||'—')+'</td><td>'+r.usuarios+'</td><td>'+ocultos+'</td><td>'+mon+'</td><td>'+ia+'</td>'
      +'<td style="display:flex;gap:4px"><button class="btn btn-s" onclick="openRol('+r.id+')">Editar</button>'
      +(r.es_sistema?'':'<button class="btn btn-s btn-d" onclick="delRol('+r.id+')">Eliminar</button>')+'</td></tr>';
  });
  $('cfg-roles').innerHTML=h+'</table>';
}
function openRol(id){
  const r=id?_roles.find(function(x){return x.id===id;}):null;
  $('rol-id').value=r?r.id:'';
  $('rol-sistema').value=r&&r.es_sistema?'1':'';
  $('rol-title').textContent=r?('Editar rol: '+r.nombre):'Nuevo rol';
  $('rol-nombre').value=r?r.nombre:'';
  $('rol-desc').value=r?(r.descripcion||''):'';
  $('rol-base').value=r?r.base_rol:'operario';
  const bloqueado=!!(r&&r.es_sistema);
  $('rol-nombre').disabled=bloqueado; $('rol-base').disabled=bloqueado;
  const perms=r?(r.permisos||{}):{};
  let h='<div style="display:grid;grid-template-columns:1fr 1fr;gap:4px">';
  MODULOS_SISTEMA.forEach(function(m){
    const checked=_permMod(perms,m.k)!=='0';
    h+='<label style="display:flex;align-items:center;gap:6px;font-size:12px;cursor:pointer;padding:3px 0"><input type="checkbox" data-rperm="mod_'+m.k+'" '+(checked?'checked':'')+'>'+m.l+'</label>';
  });
  $('rol-modulos').innerHTML=h+'</div>';
  $('rol-ver-mon').checked=perms['ver_monetario']!=='0';
  $('rol-ia').checked=perms['ia']==='1';
  $('rol-aplicar').checked=false;
  $('rol-aplicar-wrap').style.display=r?'':'none';
  openMo('mo-rol');
}
async function saveRol(){
  const id=$('rol-id').value;
  const permisos={};
  document.querySelectorAll('#rol-modulos input[data-rperm]').forEach(function(c){permisos[c.dataset.rperm]=c.checked?'1':'0';});
  permisos['ver_monetario']=$('rol-ver-mon').checked?'1':'0';
  permisos['ia']=$('rol-ia').checked?'1':'0';
  const body={nombre:$('rol-nombre').value.trim(),base_rol:$('rol-base').value,descripcion:$('rol-desc').value,permisos:permisos};
  if(!id&&!body.nombre){toast('Ingresá el nombre del rol','w');return;}
  const res=await api(id?'/api/roles/'+id:'/api/roles',{method:id?'PUT':'POST',body:JSON.stringify(body)});
  if(res.ok){
    if(id&&$('rol-aplicar').checked){
      const ap=await api('/api/roles/'+id+'/aplicar_permisos',{method:'POST',body:JSON.stringify({})});
      if(ap.ok) toast('Permisos aplicados a '+ap.usuarios+' usuario(s)');
    }
    toast(id?'Rol actualizado':'Rol creado');closeMo('mo-rol');loadRoles();
  } else toast(res.error||'Error','e');
}
async function delRol(id){
  const r=_roles.find(function(x){return x.id===id;});
  if(!await confirmar('¿Eliminar el rol "'+(r?r.nombre:id)+'"?')) return;
  const res=await apiBorrar('/api/roles/'+id,'Rol eliminado');
  if(res.ok){toast('Rol eliminado');loadRoles();} else toast(res.error||'Error','e');
}

async function openNewUsr(){
  await _cargarRolesSelect();
  $('usr-id').value='';
  $('usr-usr').value='';$('usr-pw').value='';$('usr-nom').value='';$('usr-rol').value='operario';
  $('usr-pw-req').style.display='inline';
  $('usr-activo-wrap').style.display='none';
  $('mo-usr-title').innerHTML='Nuevo usuario <span class="mx" onclick="closeMo(\'mo-usr\')">×</span>';
  $('usr-save-btn').textContent='Crear usuario';
  openMo('mo-usr');
}

async function editUsrById(id){
  const r=_usr_cache.get(parseInt(id));
  if(!r){toast('Usuario no encontrado','e');return;}
  await _cargarRolesSelect();
  $('usr-id').value=r.id;
  $('usr-usr').value=r.username;
  $('usr-pw').value='';
  $('usr-nom').value=r.nombre||'';
  $('usr-rol').value=r.rol;
  $('usr-activo').value=r.activo?'1':'0';
  $('usr-pw-req').style.display='none';
  $('usr-activo-wrap').style.display='';
  $('mo-usr-title').innerHTML='Editar usuario <span class="mx" onclick="closeMo(\'mo-usr\')">×</span>';
  $('usr-save-btn').textContent='Guardar cambios';
  openMo('mo-usr');
}

async function saveUsr(){
  const id=$('usr-id').value;
  const body={username:$('usr-usr').value,password:$('usr-pw').value,nombre:$('usr-nom').value,rol:$('usr-rol').value};
  if(!body.username||(!id&&!body.password)){toast('Username y contraseña requeridos','w');return;}
  if(id){
    body.activo=$('usr-activo').value;
    const res=await api('/api/usuarios/'+id,{method:'PUT',body:JSON.stringify(body)});
    if(res.ok){toast('Usuario actualizado');closeMo('mo-usr');_usr_cache=new Map();loadUsr();}
    else toast(res.error||'Error','e');
  } else {
    const res=await api('/api/usuarios',{method:'POST',body:JSON.stringify(body)});
    if(res.ok){toast('Usuario creado');closeMo('mo-usr');loadUsr();}
    else toast(res.error||'Error','e');
  }
}

async function delUsr(id,u){
  if(!await confirmar(`¿Eliminar usuario "${u}"?`))return;
  const res=await apiBorrar('/api/usuarios/'+id,'Usuario eliminado');
  if(res.ok){toast('Usuario eliminado');loadUsr();}
  else toast(res.error||'Error','e');
}


// ── Categorías (gestión desde Configuración) ─────────────────────────────────
async function loadCatMaq(){
  const rows = await api('/api/categorias_maquina');
  const el = $('cfg-cat-maq'); if(!el) return;
  if(!rows.length){ el.innerHTML='<div class="em">Sin categorías. Agregá la primera.</div>'; return; }
  let h='<table><tr><th>Nombre</th><th>Descripción</th><th></th></tr>';
  const tbody_maq = document.createElement('tbody');
  rows.forEach(function(r){
    const tr = document.createElement('tr');
    tr.innerHTML = '<td><b>'+r.nombre+'</b></td>'
      +'<td style="font-size:11px;color:var(--color-text-secondary)">'+(r.descripcion||'—')+'</td>'
      +'<td style="display:flex;gap:4px"></td>';
    const tdBtn = tr.querySelector('td:last-child');
    const btnE = document.createElement('button'); btnE.className='btn btn-s'; btnE.textContent='Editar';
    btnE.onclick = function(){ editCatMaq(r.id, r.nombre, r.descripcion||''); };
    const btnD = document.createElement('button'); btnD.className='btn btn-s btn-d'; btnD.textContent='✕';
    btnD.onclick = function(){ deleteCatMaq(r.id); };
    tdBtn.appendChild(btnE); tdBtn.appendChild(btnD);
    tbody_maq.appendChild(tr);
  });
  const tbl_maq = document.createElement('table');
  tbl_maq.innerHTML = '<tr><th>Nombre</th><th>Descripción</th><th></th></tr>';
  tbl_maq.appendChild(tbody_maq);
  el.innerHTML = ''; el.appendChild(tbl_maq);
}

async function loadCatProd(){
  const rows = await api('/api/categorias_producto');
  const el = $('cfg-cat-prod'); if(!el) return;
  if(!rows.length){ el.innerHTML='<div class="em">Sin categorías. Agregá la primera.</div>'; return; }
  const tbody_prod = document.createElement('tbody');
  rows.forEach(function(r){
    const tr = document.createElement('tr');
    tr.innerHTML = '<td><b>'+r.nombre+'</b></td>'
      +'<td style="font-size:11px;color:var(--color-text-secondary)">'+(r.descripcion||'—')+'</td>'
      +'<td style="display:flex;gap:4px"></td>';
    const tdBtn = tr.querySelector('td:last-child');
    const btnE = document.createElement('button'); btnE.className='btn btn-s'; btnE.textContent='Editar';
    btnE.onclick = function(){ editCatProd(r.id, r.nombre, r.descripcion||''); };
    const btnD = document.createElement('button'); btnD.className='btn btn-s btn-d'; btnD.textContent='✕';
    btnD.onclick = function(){ deleteCatProd(r.id); };
    tdBtn.appendChild(btnE); tdBtn.appendChild(btnD);
    tbody_prod.appendChild(tr);
  });
  const tbl_prod = document.createElement('table');
  tbl_prod.innerHTML = '<tr><th>Nombre</th><th>Descripción</th><th></th></tr>';
  tbl_prod.appendChild(tbody_prod);
  el.innerHTML = ''; el.appendChild(tbl_prod);
}

function openNewCatMaq(){
  $('cat-maq-id').value=''; $('cat-maq-nom').value=''; $('cat-maq-desc').value='';
  $('cat-maq-title').textContent='Nueva categoría de máquina';
  openMo('mo-cat-maq'); setTimeout(function(){$('cat-maq-nom').focus();},80);
}
function editCatMaq(id,nom,desc){
  $('cat-maq-id').value=id; $('cat-maq-nom').value=nom; $('cat-maq-desc').value=desc;
  $('cat-maq-title').textContent='Editar categoría de máquina';
  openMo('mo-cat-maq'); setTimeout(function(){$('cat-maq-nom').focus();},80);
}
async function saveCatMaq(){
  const id=$('cat-maq-id').value;
  const nom=$('cat-maq-nom').value.trim();
  if(!nom){toast('Nombre requerido','w');return;}
  const body={nombre:nom,descripcion:$('cat-maq-desc').value};
  const res=id
    ? await api('/api/categorias_maquina/'+id,{method:'PUT',body:JSON.stringify(body)})
    : await api('/api/categorias_maquina',{method:'POST',body:JSON.stringify(body)});
  if(res.ok){toast('Categoría guardada');closeMo('mo-cat-maq');_catM=[];loadCatMaq();}
  else toast(res.error||'Error','e');
}
async function deleteCatMaq(id){
  if(!await confirmar('¿Eliminar esta categoría?')) return;
  const res=await apiBorrar('/api/categorias_maquina/'+id,'Categoría eliminada');
  if(res.ok){toast('Categoría eliminada');_catM=[];loadCatMaq();}
  else toast(res.error||'Error','e');
}

function openNewCatProd(){
  $('cat-prod-id').value=''; $('cat-prod-nom').value=''; $('cat-prod-desc').value='';
  $('cat-prod-title').textContent='Nueva categoría de producto';
  openMo('mo-cat-prod'); setTimeout(function(){$('cat-prod-nom').focus();},80);
}
function editCatProd(id,nom,desc){
  $('cat-prod-id').value=id; $('cat-prod-nom').value=nom; $('cat-prod-desc').value=desc;
  $('cat-prod-title').textContent='Editar categoría de producto';
  openMo('mo-cat-prod'); setTimeout(function(){$('cat-prod-nom').focus();},80);
}
async function saveCatProd(){
  const id=$('cat-prod-id').value;
  const nom=$('cat-prod-nom').value.trim();
  if(!nom){toast('Nombre requerido','w');return;}
  const body={nombre:nom,descripcion:$('cat-prod-desc').value};
  const res=id
    ? await api('/api/categorias_producto/'+id,{method:'PUT',body:JSON.stringify(body)})
    : await api('/api/categorias_producto',{method:'POST',body:JSON.stringify(body)});
  if(res.ok){toast('Categoría guardada');closeMo('mo-cat-prod');_catP=[];loadCatProd();}
  else toast(res.error||'Error','e');
}
async function deleteCatProd(id){
  if(!await confirmar('¿Eliminar esta categoría?')) return;
  const res=await apiBorrar('/api/categorias_producto/'+id,'Categoría eliminada');
  if(res.ok){toast('Categoría eliminada');_catP=[];loadCatProd();}
  else toast(res.error||'Error','e');
}


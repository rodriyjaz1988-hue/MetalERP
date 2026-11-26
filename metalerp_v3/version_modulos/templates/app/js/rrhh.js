// ── Init ──────────────────────────────────────────────────────────────────────

// ── RRHH ─────────────────────────────────────────────────────────────────────
let _emp=[];

let _empF='';        // pestaña activa: '', 'Directo', 'Indirecto', 'Inactivo'
let _empSel=null;    // id del empleado seleccionado
let _empSortCol=null;
let _empSortAsc=true;
document.querySelectorAll('#emp-tabs .tab').forEach(t=>t.addEventListener('click',()=>{
  document.querySelectorAll('#emp-tabs .tab').forEach(x=>x.classList.remove('active'));
  t.classList.add('active');_empF=t.dataset.e;filtrarEmpleados();
}));

async function loadRRHH(){
  _emp=await api('/api/empleados');
  if(!_emp||_emp.error){$('emp-list').innerHTML='<div class="em">Error cargando empleados: '+(_emp&&_emp.error||'Error desconocido')+'</div>';_emp=[];return;}
  filtrarEmpleados();
}

function _empActivo(r){return r.activo!==0&&r.activo!==null;}

function filtrarEmpleados(){
  const q=($('emp-buscar')&&$('emp-buscar').value||'').trim().toLowerCase();
  let lista=_emp;
  if(_empF==='Inactivo') lista=lista.filter(function(r){return !_empActivo(r);});
  else if(_empF) lista=lista.filter(function(r){return r.tipo===_empF;});
  if(q) lista=lista.filter(function(r){
    const nombreCompleto=((r.nombre||'')+' '+(r.apellido||'')).toLowerCase();
    return nombreCompleto.indexOf(q)!==-1;
  });
  renderEmpleados(lista,q);
}

function clearFiltrosEmp(){
  if($('emp-buscar'))$('emp-buscar').value='';
  _empF='';
  document.querySelectorAll('#emp-tabs .tab').forEach(x=>x.classList.toggle('active',x.dataset.e===''));
  filtrarEmpleados();
}

function sortEmp(col){
  if(_empSortCol===col){ _empSortAsc=!_empSortAsc; }
  else { _empSortCol=col; _empSortAsc=true; }
  filtrarEmpleados();
}

function selEmp(id){
  _empSel=id;
  filtrarEmpleados();
}

function actualizarToolbarEmp(lista){
  const r=_empSel?(lista||_emp).find(function(e){return String(e.id)===String(_empSel);}):null;
  const lbl=$('emp-sel-label');
  if(lbl) lbl.textContent=r?(r.legajo||'#'+r.id):'–';
  const be=$('emp-b-edit'); if(be) be.disabled=!r;
}

function empSelAccion(a){
  const r=_empSel?_emp.find(function(e){return String(e.id)===String(_empSel);}):null;
  if(!r){toast('Seleccioná un empleado de la lista','w');return;}
  if(a==='edit') editEmp(r);
}

function renderEmpleados(lista,q){
  if(!_emp.length){$('emp-list').innerHTML='<div class="em">No hay empleados registrados. Usá «Nuevo empleado» para cargar el primero.</div>';actualizarToolbarEmp();return;}
  if(!lista.length){$('emp-list').innerHTML='<div class="em">No se encontraron empleados'+(q?' para "'+q+'"':'')+'.</div>';actualizarToolbarEmp(lista);return;}
  lista=lista.slice();
  if(_empSortCol){
    lista.sort(function(a,b){
      let va,vb;
      if(_empSortCol==='activo'){ va=_empActivo(a)?1:0; vb=_empActivo(b)?1:0; return _empSortAsc?va-vb:vb-va; }
      va=String(a[_empSortCol]||'').toLowerCase(); vb=String(b[_empSortCol]||'').toLowerCase();
      return _empSortAsc?va.localeCompare(vb,'es',{numeric:true}):vb.localeCompare(va,'es',{numeric:true});
    });
  }
  const cols=[
    {key:'legajo',label:'Legajo'},{key:'apellido',label:'Apellido y nombre'},{key:'tipo',label:'Tipo'},
    {key:'cargo',label:'Cargo'},{key:'turno',label:'Turno'},{key:null,label:'Grupos de máquinas'},{key:'activo',label:'Estado'}
  ];
  let h='<table><tr><th style="width:24px"></th>';
  cols.forEach(function(c){
    if(!c.key){h+='<th style="white-space:nowrap">'+c.label+'</th>';return;}
    const arrow=_empSortCol===c.key?(_empSortAsc?' ▲':' ▼'):' ⇅';
    const arrowColor=_empSortCol===c.key?'':';opacity:0.35';
    h+='<th style="cursor:pointer;user-select:none;white-space:nowrap;" onclick="sortEmp(\''+c.key+'\')">'
      +c.label+'<span style="font-size:10px'+arrowColor+'">'+arrow+'</span></th>';
  });
  h+='</tr>';
  lista.forEach(function(r){
    try{
      const sel=String(_empSel)===String(r.id);
      const mqs=r.maquinas&&r.maquinas.length?r.maquinas.map(function(m){return'<span class="tag">'+m.nombre+'</span>';}).join(''):'—';
      const nombre=[r.apellido,r.nombre].filter(Boolean).join(', ')||'—';
      const tipoCol=r.tipo==='Directo'?'bb':r.tipo==='Indirecto'?'bk':'ba';
      h+='<tr id="emp-row-'+r.id+'" class="'+(sel?'ot-sel':'')+'" style="cursor:pointer" onclick="selEmp('+r.id+')" ondblclick="_empSel='+r.id+';editEmpById('+r.id+')">'
        +'<td><input type="radio" name="emp-sel" '+(sel?'checked':'')+' onclick="event.stopPropagation();selEmp('+r.id+')"></td>'
        +'<td><b>'+(r.legajo||'—')+'</b></td>'
        +'<td>'+nombre+'</td>'
        +'<td><span class="b '+tipoCol+'">'+(r.tipo||'—')+'</span></td>'
        +'<td>'+(r.cargo||'—')+'</td>'
        +'<td>'+(r.turno||'—')+'</td>'
        +'<td>'+mqs+'</td>'
        +'<td>'+(_empActivo(r)?'<span class="b bg">Activo</span>':'<span class="b bk">Inactivo</span>')+'</td>'
        +'</tr>';
    }catch(e){
      h+='<tr><td colspan="8" style="color:red;font-size:11px">Error en empleado id='+r.id+': '+e.message+'</td></tr>';
    }
  });
  const filtrado=lista.length!==_emp.length;
  $('emp-list').innerHTML=h+'</table>'
    +'<div style="font-size:11px;color:var(--color-text-secondary);margin-top:4px">'+lista.length+' empleado'+(lista.length!==1?'s':'')+' mostrado'+(lista.length!==1?'s':'')+(filtrado?' (de '+_emp.length+' total)':'')+'</div>';
  actualizarToolbarEmp(lista);
}

async function openEmpModal(){
  $('emp-id').value='';
  $('emp-alta').value=new Date().toISOString().slice(0,10);$('emp-baja').value='';
  if(!_catM.length)_catM=await api('/api/categorias_maquina');
  const s=$('emp-maq');s.innerHTML='';
  _catM.forEach(c=>{const o=document.createElement('option');o.value=c.id;o.textContent=c.nombre;s.appendChild(o);});
  openMo('mo-emp');
}

function editEmpById(id){
  const emp = _emp.find(function(e){ return String(e.id)===String(id); });
  if(emp) editEmp(emp);
  else toast('Empleado no encontrado','e');
}

async function editEmp(r){
  $('emp-id').value=r.id;$('emp-leg').value=r.legajo;$('emp-nom').value=r.nombre;
  $('emp-ape').value=r.apellido;$('emp-car').value=r.cargo||'';$('emp-tipo').value=r.tipo;
  $('emp-tur').value=r.turno||'';$('emp-obs').value=r.obs||'';
  $('emp-alta').value=r.fecha_alta||'';$('emp-baja').value=r.fecha_baja||'';
  if(!_catM.length)_catM=await api('/api/categorias_maquina');
  const s=$('emp-maq');s.innerHTML='';
  const sel=(r.maquinas||[]).map(m=>m.id);
  _catM.forEach(c=>{const o=document.createElement('option');o.value=c.id;o.textContent=c.nombre;if(sel.includes(c.id))o.selected=true;s.appendChild(o);});
  openMo('mo-emp');
}

async function saveEmp(){
  const id=$('emp-id').value;
  const maquinas=[...$('emp-maq').selectedOptions].map(o=>parseInt(o.value));
  const body={legajo:$('emp-leg').value,nombre:$('emp-nom').value,apellido:$('emp-ape').value,
    cargo:$('emp-car').value,tipo:$('emp-tipo').value,turno:$('emp-tur').value,
    obs:$('emp-obs').value,activo:true,maquinas,
    fecha_alta:$('emp-alta').value||null,fecha_baja:$('emp-baja').value||null};
  if(!body.legajo||!body.nombre||!body.apellido){toast('Legajo, nombre y apellido requeridos','w');return;}
  const res=await api(id?'/api/empleados/'+id:'/api/empleados',{method:id?'PUT':'POST',body:JSON.stringify(body)});
  if(res.ok){toast(id?'Empleado actualizado':'Empleado registrado');closeMo('mo-emp');$('emp-id').value='';_emp=[];loadRRHH();}
  else toast(res.error||'Error','e');
}


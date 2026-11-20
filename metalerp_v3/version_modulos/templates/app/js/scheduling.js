// ── Operaciones pendientes por sector ────────────────────────────────────────
async function loadOpsSector(){
  const selS=$('os-sector');
  if(selS && selS.options.length<=1){
    try{
      const cats=await api('/api/categorias_maquina');
      selS.innerHTML='<option value="">Todos los sectores</option>'+cats.map(c=>'<option value="'+c.id+'">'+c.nombre+'</option>').join('')+'<option value="terceros">Tercerizadas</option>';
    }catch(e){}
  }
  const qs=new URLSearchParams();
  if($('os-sector').value) qs.set('categoria_id',$('os-sector').value);
  if($('os-estado').value) qs.set('estado',$('os-estado').value);
  if($('os-q').value.trim()) qs.set('q',$('os-q').value.trim());
  const rows=await api('/api/operaciones_pendientes?'+qs.toString());
  if(!Array.isArray(rows)){ $('os-tbl').innerHTML='<tr><td class="em">'+((rows&&rows.error)||'No se pudo cargar (error 404: el servidor no tiene este módulo; reinicialo con el server.py nuevo).')+'</td></tr>'; return; }
  const bySec={};
  rows.forEach(r=>{const k=r.es_tercerizada?'Tercerizadas':(r.sector||'Sin sector');bySec[k]=(bySec[k]||0)+1;});
  $('os-resumen').innerHTML=Object.keys(bySec).map(k=>'<span class="b bb">'+k+': '+bySec[k]+'</span>').join('')||'';
  let h='<tr><th>OT</th><th>Producto</th><th>Cliente</th><th>Op.</th><th>Operación</th><th>Sector</th><th>Máquina</th><th>Estado</th><th>Avance</th><th>Prioridad</th><th>Entrega</th></tr>';
  if(!rows.length) h+='<tr><td colspan="11" class="em">Sin operaciones pendientes</td></tr>';
  rows.forEach(r=>{
    const pend=Math.max(0,(r.qty_requerida||0)-(r.qty_producida||0));
    h+='<tr><td><b>'+r.ot_numero+'</b></td><td>'+(r.producto_codigo?r.producto_codigo+' — ':'')+(r.producto_nombre||'—')+'</td><td>'+(r.cliente_nombre||'—')+'</td>'
      +'<td>'+r.orden+'</td><td>'+r.operacion+(r.es_tercerizada?' <span class="b bp">Tercero'+(r.proveedor_nombre?': '+r.proveedor_nombre:'')+'</span>':'')+'</td>'
      +'<td>'+(r.es_tercerizada?'Tercerizada':(r.sector||'—'))+'</td><td>'+(r.maquina_nombre||'—')+'</td><td>'+sb(r.estado)+'</td>'
      +'<td>'+fN(r.qty_producida||0)+' / '+fN(r.qty_requerida||0)+' <span style="font-size:10px;color:var(--color-text-secondary)">(faltan '+fN(pend)+')</span></td>'
      +'<td>'+pb(r.prioridad||'Normal')+'</td><td>'+fmtD(r.fecha_entrega)+'</td></tr>';
  });
  $('os-tbl').innerHTML=h;
}

// ── Scheduling de producción ─────────────────────────────────────────────────
// Gantt por máquina. Cada barra = una jornada (9 o 12 h) de una operación de OT,
// en una máquina, con su operario. Las fechas se manejan como texto local
// 'AAAA-MM-DD HH:MM' (sin zona horaria) para que coincidan con el servidor.
const SCH={desde:null,dias:7,pxh:6,maqs:[],bl:[],pend:[],emps:[],cats:[],col:{},sel:null,mv:null,tickH:6};
const SCH_ZOOM={sem:{dias:7,pxh:8,tick:6},d14:{dias:14,pxh:4,tick:12},d3:{dias:3,pxh:14,tick:3},d1:{dias:1,pxh:36,tick:1}};
const SCH_LAB=200;
const SCH_PAL=['#DCEBFA','#E3F2D6','#FBEBCB','#F0E1F7','#D8F0EA','#FADDDA','#E7E7F7','#F3EDD0'];
const SCH_DIAS=['Dom','Lun','Mar','Mié','Jue','Vie','Sáb'];
function schEsc(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}
function schP2(n){return (n<10?'0':'')+n;}
function schMin(s){var m=/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/.exec(s||'');if(!m)return NaN;return Date.UTC(+m[1],+m[2]-1,+m[3],+m[4],+m[5])/60000;}
function schStr(min){var d=new Date(min*60000);return d.getUTCFullYear()+'-'+schP2(d.getUTCMonth()+1)+'-'+schP2(d.getUTCDate())+' '+schP2(d.getUTCHours())+':'+schP2(d.getUTCMinutes());}
function schHoy(){var d=new Date();return d.getFullYear()+'-'+schP2(d.getMonth()+1)+'-'+schP2(d.getDate());}
function schAhora(){var d=new Date();return Date.UTC(d.getFullYear(),d.getMonth(),d.getDate(),d.getHours(),d.getMinutes())/60000;}
function schLunes(f){var m=schMin(f+' 00:00');var dow=new Date(m*60000).getUTCDay();return schStr(m-((dow+6)%7)*1440).slice(0,10);}
function schDM(s){return s?String(s).slice(8,10)+'/'+String(s).slice(5,7):'';}
function schPuedeEditar(){return ROL==='admin'||ROL==='operario';}
function schCorto(n){n=String(n||'').trim();if(!n)return '';var p=n.split(/\s+/);return p[0]+(p[1]?' '+p[1].charAt(0)+'.':'');}

async function loadScheduling(){
  if(!SCH.desde){SCH.desde=schLunes(schHoy());$('sch-fecha').value=SCH.desde;}
  if(!SCH.cats.length){
    try{
      var cats=await api('/api/categorias_maquina');
      if(Array.isArray(cats)){
        SCH.cats=cats;
        var opt=cats.map(function(c){return '<option value="'+c.id+'">'+schEsc(c.nombre)+'</option>';}).join('');
        $('sch-sector').innerHTML='<option value="">Todos los sectores</option>'+opt;
        $('sch-psec').innerHTML='<option value="">Todos los sectores</option>'+opt;
      }
    }catch(e){}
  }
  if(!SCH.emps.length){
    // Se guardan todos: los dados de baja solo se ofrecen en el bloque que ya los tiene
    try{var e=await api('/api/empleados');if(Array.isArray(e))SCH.emps=e;}catch(x){}
  }
  await schRefrescar(true);
}
async function schRefrescar(irAhora){
  var z=SCH_ZOOM[$('sch-zoom').value]||SCH_ZOOM.sem;
  SCH.dias=z.dias;SCH.pxh=z.pxh;SCH.tickH=z.tick;
  var res=await Promise.all([api('/api/scheduling?desde='+SCH.desde+'&dias='+SCH.dias),api('/api/scheduling/pendientes')]);
  var g=res[0],p=res[1];
  if(!g||g.error||!Array.isArray(g.maquinas)){
    $('sch-gantt').innerHTML='<div class="em">'+schEsc((g&&g.error)||'No se pudo cargar. Si el error es 404, el servidor está corriendo una versión vieja: reinicialo con el server.py nuevo.')+'</div>';
    return;
  }
  SCH.maqs=g.maquinas;SCH.bl=g.bloques||[];SCH.pend=Array.isArray(p)?p:[];
  schRender();schRenderPend();
  if(irAhora){
    var t0=schMin(SCH.desde+' 00:00'),n=schAhora();
    var sc=$('sch-scroll');
    sc.scrollLeft=(n>=t0&&n<t0+SCH.dias*1440)?Math.max(0,(n-t0)/60*SCH.pxh-120):0;
  }
}
function schIr(f){if(!f)return;SCH.desde=f;schRefrescar(true);}
function schMover(dir){
  var t=schMin(SCH.desde+' 00:00')+dir*SCH.dias*1440;
  SCH.desde=schStr(t).slice(0,10);$('sch-fecha').value=SCH.desde;schRefrescar(true);
}
function schHoyBtn(){
  var z=SCH_ZOOM[$('sch-zoom').value]||SCH_ZOOM.sem;
  SCH.desde=(z.dias>=7)?schLunes(schHoy()):schHoy();$('sch-fecha').value=SCH.desde;schRefrescar(true);
}

function schRender(){
  var pxh=SCH.pxh,dias=SCH.dias,dayW=24*pxh,W=dias*dayW;
  var t0=schMin(SCH.desde+' 00:00'),t1=t0+dias*1440;
  var sec=$('sch-sector').value,solo=$('sch-solo').checked,q=($('sch-q').value||'').trim().toLowerCase();
  var by={};SCH.bl.forEach(function(b){(by[b.maquina_id]=by[b.maquina_id]||[]).push(b);});
  var hoy=schHoy();
  // encabezado
  var hc='';
  for(var i=0;i<dias;i++){
    var dm=t0+i*1440,ds=schStr(dm).slice(0,10),dow=new Date(dm*60000).getUTCDay();
    hc+='<div class="dy'+((dow===0||dow===6)?' wk':'')+(ds===hoy?' hoy':'')+'" style="left:'+(i*dayW)+'px;width:'+dayW+'px">'+SCH_DIAS[dow]+' '+schDM(ds)+'</div>';
    for(var h=0;h<24;h+=SCH.tickH){hc+='<div class="tk" style="left:'+(i*dayW+h*pxh)+'px;width:'+(SCH.tickH*pxh)+'px">'+schP2(h)+'</div>';}
  }
  var h='<div class="sch-hd" style="width:'+(SCH_LAB+W)+'px"><div class="sch-lab sch-corner">Grupo / máquina</div><div class="sch-hcols" style="width:'+W+'px;height:41px">'+hc+'</div></div>';
  // grupos
  var grupos=[],gm={};
  SCH.maqs.forEach(function(m){
    if(sec&&String(m.categoria_id)!==String(sec))return;
    var mb=by[m.id]||[];
    if(solo&&!mb.length)return;
    if(!gm[m.grupo]){gm[m.grupo]=[];grupos.push(m.grupo);}
    gm[m.grupo].push(m);
  });
  var nbl=0,hrs=0;
  grupos.forEach(function(g){
    var col=SCH.col[g];
    h+='<div class="sch-grp" data-g="'+schEsc(g)+'" style="width:'+(SCH_LAB+W)+'px"><div class="sch-lab">'+(col?'▸ ':'▾ ')+schEsc(g)+' <span>('+gm[g].length+')</span></div></div>';
    if(col)return;
    gm[g].forEach(function(m){
      var mb=by[m.id]||[],hm=0,bars='';
      mb.forEach(function(b){
        var a=schMin(b.inicio),e=schMin(b.fin);
        var ca=Math.max(a,t0),ce=Math.min(e,t1);
        if(ce<=ca)return;
        hm+=(ce-ca)/60;nbl++;
        var left=(ca-t0)/60*pxh,w=Math.max(3,(ce-ca)/60*pxh);
        // OT u operación cerrada: queda como historial pero ya no ocupa la máquina
        var cerr=['Completada','Cancelada'].indexOf(b.ot_estado)>=0||['Completada','Cancelada'].indexOf(b.op_estado)>=0;
        var late=!cerr&&b.fecha_entrega&&String(b.fin).slice(0,10)>String(b.fecha_entrega).slice(0,10);
        var txt=(b.ot_numero+' '+(b.producto_nombre||'')+' '+b.operacion+' '+(b.cliente_nombre||'')+' '+(b.empleado_nombre||'')).toLowerCase();
        var cls='sch-bar'+(b.op_estado==='En proceso'?' proc':'')+(b.empleado_id?'':' sinop')+(late?' late':'')+(cerr?' cerr':'')+(a<t0?' clipL':'')+(e>t1?' clipR':'')+((q&&txt.indexOf(q)<0)?' dim':'');
        var tip=b.ot_numero+' · Op '+b.op_orden+' '+b.operacion+'\n'+(b.producto_codigo?b.producto_codigo+' — ':'')+(b.producto_nombre||'')+(b.cliente_nombre?'\nCliente: '+b.cliente_nombre:'')
          +'\nOperario: '+(b.empleado_nombre||'sin asignar')+'\nJornada: '+b.jornada_horas+' h  ('+b.inicio.slice(5,16).replace('-','/')+' → '+b.fin.slice(5,16).replace('-','/')+')\nCantidad plan: '+(b.cantidad_plan||0)
          +(b.fecha_entrega?'\nEntrega OT: '+schDM(b.fecha_entrega):'')+(late?'\n⚠ Termina después de la entrega':'')
          +(cerr?'\n'+(['Completada','Cancelada'].indexOf(b.ot_estado)>=0?'OT '+b.ot_estado.toLowerCase():'Operación '+b.op_estado.toLowerCase())+': ya no ocupa la máquina':'');
        var l2=(b.empleado_nombre?schCorto(b.empleado_nombre):'sin operario')+' · '+b.jornada_horas+'h'+(b.cantidad_plan?' · '+fN(b.cantidad_plan)+' u':'');
        bars+='<div class="'+cls+'" data-b="'+b.id+'" title="'+schEsc(tip)+'" style="left:'+left+'px;width:'+w+'px;background:'+SCH_PAL[(b.orden_id||0)%SCH_PAL.length]+'">'
          +(w>46?'<span class="t">'+(late?'⚠ ':'')+schEsc(b.ot_numero)+' · '+schEsc(b.operacion)+'</span>'+(w>70?'<span class="o">'+schEsc(l2)+'</span>':''):'')+'</div>';
      });
      hrs+=hm;
      h+='<div class="sch-row" data-m="'+m.id+'" data-cat="'+(m.categoria_id||'')+'" style="width:'+(SCH_LAB+W)+'px"><div class="sch-lab" title="'+schEsc(m.codigo+' — '+m.nombre+' ('+m.estado+')')+'"><b>'+schEsc(m.codigo)+'</b> <span style="overflow:hidden;text-overflow:ellipsis">'+schEsc(m.nombre!==m.codigo?m.nombre:'')+'</span>'
        +(m.estado!=='Operativa'?'<span class="st">'+schEsc(m.estado)+'</span>':'')+(hm?'<span class="hs">'+(Math.round(hm*10)/10)+' h</span>':'')+'</div><div class="sch-line" style="width:'+W+'px">'+bars+'</div></div>';
    });
  });
  if(!grupos.length)h+='<div class="em">No hay máquinas para mostrar. '+(solo?'Probá destildar "Solo máquinas con carga".':'Cargalas en el módulo Máquinas.')+'</div>';
  // superposición: fines de semana, líneas de día/horas y ahora
  var ov='';
  for(var j=0;j<dias;j++){var dw=new Date((t0+j*1440)*60000).getUTCDay();if(dw===0||dw===6)ov+='<div class="wk" style="left:'+(j*dayW)+'px;width:'+dayW+'px"></div>';}
  var grid='repeating-linear-gradient(to right,#cfd2d8 0,#cfd2d8 1px,transparent 1px,transparent '+dayW+'px),repeating-linear-gradient(to right,#eceef0 0,#eceef0 1px,transparent 1px,transparent '+(SCH.tickH*pxh)+'px)';
  var n=schAhora();
  if(n>=t0&&n<t1)ov+='<div class="now" style="left:'+((n-t0)/60*pxh)+'px" title="Ahora"></div>';
  h+='<div class="sch-ov" style="width:'+W+'px;background-image:'+grid+'">'+ov+'</div>';
  var gt=$('sch-gantt');
  gt.style.width=(SCH_LAB+W)+'px';
  gt.innerHTML=h;
  // resumen
  var pendSin=SCH.pend.filter(function(p){return schSinPlan(p)>0;}).length;
  $('sch-resumen').innerHTML='<span class="b bb">'+nbl+' bloques en la vista</span><span class="b bg">'+(Math.round(hrs*10)/10)+' h planificadas</span><span class="b ba">'+pendSin+' operaciones sin planificar</span>';
}

// ── Panel de operaciones sin planificar ──────────────────────────────────────
function schSinPlan(p){return Math.max(0,(p.qty_requerida||0)-(p.qty_producida||0)-(p.qty_planificada||0));}
// Planificada por completo: tiene cantidad requerida y no queda nada sin planificar.
// No admite más bloques (la misma operación de otra OT es otra tarjeta).
function schCompleta(p){return (p.qty_requerida||0)>0&&schSinPlan(p)<=0;}
function schRenderPend(){
  var sec=$('sch-psec').value,q=($('sch-pq').value||'').trim().toLowerCase(),all=$('sch-pall').checked;
  var rows=SCH.pend.filter(function(p){
    if(sec&&String(p.categoria_maquina_id)!==String(sec))return false;
    if(!all&&schSinPlan(p)<=0&&p.bloques>0)return false;
    if(q&&(p.ot_numero+' '+p.operacion+' '+(p.producto_nombre||'')+' '+(p.producto_codigo||'')+' '+(p.cliente_nombre||'')).toLowerCase().indexOf(q)<0)return false;
    return true;
  });
  $('sch-pcount').textContent=rows.length;
  var edit0=schPuedeEditar(),h='';
  rows.forEach(function(p){
    var falta=Math.max(0,(p.qty_requerida||0)-(p.qty_producida||0)),sin=schSinPlan(p);
    var edit=edit0&&!schCompleta(p);
    var late=p.fecha_entrega&&String(p.fecha_entrega).slice(0,10)<schHoy();
    h+='<div class="sch-card'+(p.estado==='En proceso'?' proc':'')+(sin<=0?' full':'')+(SCH.sel===p.id?' sel':'')+'" data-oo="'+p.id+'"'+(edit?' draggable="true"':'')+'>'
      +'<div><b>'+schEsc(p.ot_numero)+'</b> · Op '+schEsc(p.orden)+' <b>'+schEsc(p.operacion)+'</b></div>'
      +'<div class="l2">'+schEsc((p.producto_codigo?p.producto_codigo+' — ':'')+(p.producto_nombre||'—'))+(p.cliente_nombre?' · '+schEsc(p.cliente_nombre):'')+'</div>'
      +'<div class="l3">'+schEsc(p.sector||'Sin sector')+' · faltan <b>'+fN(falta)+'</b> · '+(sin<=0?'<span style="color:#3B6D11">✓ planificada</span>':'sin planificar <b>'+sin+'</b>')+'</div>'
      +'<div class="l4"><span'+(late?' class="late"':'')+'>Entrega '+(p.fecha_entrega?schDM(p.fecha_entrega):'—')+'</span>'+(edit?'<button class="btn" data-act="asig">Asignar</button>':'')+'</div></div>';
  });
  $('sch-plist').innerHTML=h||'<div class="em">Sin operaciones para planificar</div>';
}

// ── Eventos del Gantt y del panel (delegados) ────────────────────────────────
function schMarcarSector(oo){
  document.querySelectorAll('#sch-gantt .sch-row').forEach(function(r){
    r.classList.toggle('sch-match',!!oo&&String(r.dataset.cat)===String(oo.categoria_maquina_id));
  });
}
function schFinDrag(){
  $('sch-scroll').classList.remove('sch-dragging');
  document.querySelectorAll('#sch-gantt .sch-row').forEach(function(r){r.classList.remove('sch-match','sch-hot');});
}
function schSnap(min){return Math.round(min/30)*30;}
function schMinDesdeX(line,clientX){
  var x=clientX-line.getBoundingClientRect().left;
  return schMin(SCH.desde+' 00:00')+schSnap(x/SCH.pxh*60);
}
(function schInit(){
  var pl=$('sch-plist'),gt=$('sch-gantt'),sc=$('sch-scroll');
  pl.addEventListener('dragstart',function(e){
    var c=e.target.closest('.sch-card');if(!c)return;
    var oo=SCH.pend.find(function(p){return p.id==c.dataset.oo;});
    e.dataTransfer.setData('text/plain','oo:'+c.dataset.oo);e.dataTransfer.effectAllowed='copy';
    SCH.sel=oo?oo.id:null;sc.classList.add('sch-dragging');schMarcarSector(oo);
  });
  pl.addEventListener('dragend',schFinDrag);
  pl.addEventListener('click',function(e){
    var c=e.target.closest('.sch-card');if(!c)return;
    var oo=SCH.pend.find(function(p){return p.id==c.dataset.oo;});if(!oo)return;
    if(e.target.closest('[data-act="asig"]')){schAbrirNuevo(oo);return;}
    SCH.sel=(SCH.sel===oo.id)?null:oo.id;
    document.querySelectorAll('#sch-plist .sch-card').forEach(function(x){x.classList.toggle('sel',x.dataset.oo==SCH.sel);});
    schMarcarSector(SCH.sel?oo:null);
  });
  gt.addEventListener('dragover',function(e){
    var row=e.target.closest('.sch-row');if(!row)return;
    e.preventDefault();e.dataTransfer.dropEffect='copy';
    gt.querySelectorAll('.sch-hot').forEach(function(r){if(r!==row)r.classList.remove('sch-hot');});
    row.classList.add('sch-hot');
  });
  gt.addEventListener('drop',function(e){
    var row=e.target.closest('.sch-row');if(!row)return;
    e.preventDefault();
    var d=e.dataTransfer.getData('text/plain')||'';schFinDrag();
    if(d.indexOf('oo:')!==0)return;
    var oo=SCH.pend.find(function(p){return p.id==d.slice(3);});if(!oo)return;
    var line=row.querySelector('.sch-line');
    schAbrirNuevo(oo,row.dataset.m,schStr(schMinDesdeX(line,e.clientX)));
  });
  gt.addEventListener('click',function(e){
    var g=e.target.closest('.sch-grp');
    if(g){var k=g.dataset.g;SCH.col[k]=!SCH.col[k];schRender();return;}
  });
  // mover barras con el mouse
  gt.addEventListener('mousedown',function(e){
    var bar=e.target.closest('.sch-bar');if(!bar||e.button!==0)return;
    var b=SCH.bl.find(function(x){return x.id==bar.dataset.b;});if(!b)return;
    SCH.mv={bar:bar,b:b,x0:e.clientX,y0:e.clientY,moved:false};
    e.preventDefault();
  });
  document.addEventListener('mousemove',function(e){
    var m=SCH.mv;if(!m)return;
    var dx=e.clientX-m.x0,dy=e.clientY-m.y0;
    if(!m.moved&&Math.abs(dx)+Math.abs(dy)<5)return;
    if(!schPuedeEditar())return;
    m.moved=true;m.bar.classList.add('mv');m.bar.style.transform='translate('+dx+'px,'+dy+'px)';
    var el=document.elementFromPoint(e.clientX,e.clientY);
    var row=el&&el.closest?el.closest('.sch-row'):null;
    gt.querySelectorAll('.sch-hot').forEach(function(r){r.classList.remove('sch-hot');});
    if(row)row.classList.add('sch-hot');
  });
  document.addEventListener('mouseup',async function(e){
    var m=SCH.mv;if(!m)return;SCH.mv=null;
    gt.querySelectorAll('.sch-hot').forEach(function(r){r.classList.remove('sch-hot');});
    m.bar.classList.remove('mv');m.bar.style.transform='';
    if(!m.moved){schAbrirEditar(m.b);return;}
    var el=document.elementFromPoint(e.clientX,e.clientY);
    var row=el&&el.closest?el.closest('.sch-row'):null;
    var dxMin=schSnap((e.clientX-m.x0)/SCH.pxh*60);
    var nuevoIni=schStr(schMin(m.b.inicio)+dxMin);
    var maq=row?row.dataset.m:String(m.b.maquina_id);
    if(String(maq)===String(m.b.maquina_id)&&nuevoIni===m.b.inicio)return;
    var r=await api('/api/scheduling/'+m.b.id,{method:'PUT',body:JSON.stringify({maquina_id:+maq,inicio:nuevoIni})});
    if(r&&r.error){toast(r.error,'e');return;}
    if(r&&r.avisos&&r.avisos.length)toast(r.avisos.join(' · '),'w');
    schRefrescar();
  });
})();

// ── Modal de asignación ──────────────────────────────────────────────────────
// ── Buscadores de máquina y operario (misma estética que los de Novedad) ─────
function schTxtMaq(m){
  return m.codigo+(m.nombre&&m.nombre!==m.codigo?' — '+m.nombre:'');
}
function schTxtEmp(e){
  return (e.apellido||'')+', '+(e.nombre||'');
}
function schOcultarRes(id){
  var c=$(id);if(c){c.style.display='none';c.innerHTML='';}
}
function schSetMaq(id){
  var m=SCH.maqs.find(function(x){return String(x.id)===String(id);});
  $('sch-maq').value=m?m.id:'';
  $('sch-maq-search').value=m?schTxtMaq(m):'';
  schOcultarRes('sch-maq-results');
}
function schSetEmp(id,catId){
  var e=SCH.emps.find(function(x){return String(x.id)===String(id);});
  $('sch-emp').value=e?e.id:'';
  $('sch-emp-search').value=e?schTxtEmp(e)+(e.activo?'':' — dado de baja'):'';
  $('mo-sch')._cat=catId;
  // Se recuerda el operario original: si está dado de baja se conserva igual
  // (guardar sin tocarlo no debe quitárselo al bloque).
  $('mo-sch')._empOrig=e?String(e.id):'';
  schOcultarRes('sch-emp-results');
}
function schItemRes(cont,texto,extra,onPick){
  var item=document.createElement('div');
  item.style.cssText='padding:7px 10px;font-size:13px;cursor:pointer;display:flex;justify-content:space-between;gap:8px';
  var t=document.createElement('span');t.textContent=texto;item.appendChild(t);
  if(extra){
    var x=document.createElement('span');x.textContent=extra;
    x.style.cssText='font-size:11px;color:#999;white-space:nowrap';item.appendChild(x);
  }
  item.onmouseenter=function(){this.style.background='#f4f4f2';};
  item.onmouseleave=function(){this.style.background='';};
  item.onmousedown=function(ev){ev.preventDefault();onPick();cont.style.display='none';cont.innerHTML='';};
  cont.appendChild(item);
}
function schFiltrarMaq(escribiendo){
  var q=($('sch-maq-search').value||'').toLowerCase().trim();
  if(escribiendo)$('sch-maq').value=''; // hasta que se reseleccione, no hay máquina confirmada
  var cont=$('sch-maq-results');
  if(!escribiendo)q=''; // al enfocar se muestra la lista completa
  var lista=SCH.maqs.filter(function(m){
    return !q||((m.codigo||'')+' '+(m.nombre||'')+' '+(m.grupo||'')).toLowerCase().includes(q);
  });
  if(!lista.length){
    cont.innerHTML='<div style="padding:8px 10px;font-size:12px;color:#999">Sin resultados</div>';
    cont.style.display='block';return;
  }
  cont.innerHTML='';
  lista.slice(0,60).forEach(function(m){
    var extra=(m.estado&&m.estado!=='Operativa')?m.estado:(m.grupo||'');
    schItemRes(cont,schTxtMaq(m),extra,function(){schSetMaq(m.id);schModalCalc();});
  });
  cont.style.display='block';
}
function schFiltrarEmp(escribiendo){
  var q=($('sch-emp-search').value||'').toLowerCase().trim();
  if(escribiendo)$('sch-emp').value=''; // vacío = sin operario
  var cont=$('sch-emp-results');
  if(!escribiendo)q='';
  var mo=$('mo-sch'),catId=mo._cat,orig=mo._empOrig;
  var hab=[],otros=[];
  SCH.emps.forEach(function(e){
    // los dados de baja solo aparecen si son el operario que ya tenía el bloque
    if(!e.activo&&String(e.id)!==String(orig))return;
    var full1=((e.nombre||'')+' '+(e.apellido||'')).toLowerCase();
    var full2=((e.apellido||'')+' '+(e.nombre||'')).toLowerCase();
    if(q&&!full1.includes(q)&&!full2.includes(q))return;
    var ok=(e.maquinas||[]).some(function(c){return String(c.id)===String(catId);});
    (ok?hab:otros).push(e);
  });
  var lista=hab.map(function(e){return {e:e,hab:true};}).concat(otros.map(function(e){return {e:e,hab:false};}));
  if(!lista.length){
    cont.innerHTML='<div style="padding:8px 10px;font-size:12px;color:#999">Sin resultados</div>';
    cont.style.display='block';return;
  }
  cont.innerHTML='';
  lista.slice(0,60).forEach(function(x){
    var e=x.e;
    var extra=!e.activo?'dado de baja':(x.hab?'Habilitado en este sector':(e.cargo||''));
    schItemRes(cont,schTxtEmp(e),extra,function(){
      $('sch-emp').value=e.id;
      $('sch-emp-search').value=schTxtEmp(e)+(e.activo?'':' — dado de baja');
    });
  });
  cont.style.display='block';
}
function schInfoOp(p){
  var falta=Math.max(0,(p.qty_requerida||0)-(p.qty_producida||0));
  return '<b>'+schEsc(p.ot_numero)+'</b> · Op '+schEsc(p.orden)+' <b>'+schEsc(p.operacion)+'</b> '+(p.estado?sb(p.estado):'')+'<br>'
    +schEsc((p.producto_codigo?p.producto_codigo+' — ':'')+(p.producto_nombre||'—'))+(p.cliente_nombre?' · '+schEsc(p.cliente_nombre):'')+'<br>'
    +'<span style="color:#555">Sector: '+schEsc(p.sector||'—')+' · faltan '+fN(falta)+' u · planificadas a futuro '+fN(p.qty_planificada||0)+' u'
    +(p.fecha_entrega?' · entrega '+schDM(p.fecha_entrega):'')+'</span>';
}
function schAbrirNuevo(p,maqId,inicio){
  if(!schPuedeEditar()){toast('Tu rol no puede modificar la planificación','w');return;}
  if(schCompleta(p)){toast('La operación ya está planificada por completo. Para cambiarla, editá o eliminá sus bloques.','w');return;}
  $('sch-title').textContent='Asignar operación';
  $('sch-id').value='';$('sch-oo').value=p.id;
  $('sch-opinfo').innerHTML=schInfoOp(p);
  if(!maqId){
    var cand=SCH.maqs.filter(function(m){return p.maquina_id?m.id===p.maquina_id:String(m.categoria_id)===String(p.categoria_maquina_id);});
    maqId=(cand[0]||SCH.maqs[0]||{}).id;
  }
  schSetMaq(maqId);
  schSetEmp('',p.categoria_maquina_id);
  $('sch-jor').value='9';
  var ini=inicio||(SCH.desde+' 06:00');
  var hoyIn=schHoy()>=SCH.desde&&schMin(schHoy()+' 00:00')<schMin(SCH.desde+' 00:00')+SCH.dias*1440;
  if(!inicio&&hoyIn)ini=schHoy()+' 06:00';
  $('sch-f').value=ini.slice(0,10);$('sch-h').value=ini.slice(11,16);
  $('sch-qty').value='';$('sch-qty').dataset.man='';
  $('sch-rep').value='0';$('sch-hab').value='1';$('sch-repbox').style.display='flex';
  $('sch-obs').value='';$('sch-del').style.display='none';
  $('sch-err').style.display='none';
  $('mo-sch')._p=p;
  schModalCalc();openMo('mo-sch');
}
function schAbrirEditar(b){
  var p=SCH.pend.find(function(x){return x.id===b.orden_operacion_id;})||{
    id:b.orden_operacion_id,ot_numero:b.ot_numero,orden:b.op_orden,operacion:b.operacion,estado:b.op_estado,producto_nombre:b.producto_nombre,
    producto_codigo:b.producto_codigo,cliente_nombre:b.cliente_nombre,qty_requerida:b.qty_requerida,qty_producida:b.qty_producida,
    categoria_maquina_id:b.categoria_maquina_id,fecha_entrega:b.fecha_entrega,setup_min:0,ciclo_seg:0,qty_planificada:0};
  var edit=schPuedeEditar();
  $('sch-title').textContent=edit?'Editar bloque':'Detalle del bloque';
  $('sch-id').value=b.id;$('sch-oo').value=b.orden_operacion_id;
  $('sch-opinfo').innerHTML=schInfoOp(p);
  schSetMaq(b.maquina_id);
  schSetEmp(b.empleado_id||'',b.categoria_maquina_id);
  $('sch-jor').value=String(b.jornada_horas);
  $('sch-f').value=b.inicio.slice(0,10);$('sch-h').value=b.inicio.slice(11,16);
  $('sch-qty').value=b.cantidad_plan||'';$('sch-qty').dataset.man='1';
  $('sch-repbox').style.display='none';$('sch-rep').value='0';
  $('sch-obs').value=b.obs||'';
  $('sch-del').style.display=edit?'':'none';$('sch-save').style.display=edit?'':'none';
  $('sch-err').style.display='none';
  $('mo-sch')._p=p;
  schModalCalc();openMo('mo-sch');
}
function schHora(hhmm){$('sch-h').value=hhmm;schModalCalc();}
function schModalCalc(){
  var p=$('mo-sch')._p||{},jor=+$('sch-jor').value;
  var f=$('sch-f').value,hh=$('sch-h').value;
  var h='';
  if(f&&hh){
    var a=schMin(f+' '+hh),b=a+jor*60;
    h='Termina el <b>'+schDM(schStr(b))+' a las '+schStr(b).slice(11,16)+'</b> ('+jor+' h de jornada). ';
  }
  var cap=null;
  if(p.ciclo_seg>0){
    var nuevo=!$('sch-id').value&&!(p.bloques>0);
    var seg=jor*3600-(nuevo?(p.setup_min||0)*60:0);
    cap=Math.max(0,Math.floor(seg/p.ciclo_seg));
    h+='Capacidad estimada: <b>≈ '+cap+' piezas</b> (ciclo '+p.ciclo_seg+' s'+(nuevo&&p.setup_min?', setup '+p.setup_min+' min':'')+').';
  }else h+='<span style="color:#888">La operación no tiene tiempo de ciclo cargado: ingresá la cantidad a mano.</span>';
  $('sch-calc').innerHTML=h;
  var q=$('sch-qty');
  if(!q.dataset.man&&cap!=null){
    var sin=Math.max(0,(p.qty_requerida||0)-(p.qty_producida||0)-(p.qty_planificada||0));
    q.value=sin>0?Math.min(cap,sin):cap;
  }
}
async function schGuardar(){
  var id=$('sch-id').value,err=$('sch-err');err.style.display='none';
  var f=$('sch-f').value,hh=$('sch-h').value;
  if(!f||!hh){err.textContent='Indicá fecha y hora de inicio';err.style.display='block';return;}
  if(!$('sch-maq').value){err.textContent=$('sch-maq-search').value.trim()?'Elegí la máquina de la lista de resultados':'Seleccioná una máquina';err.style.display='block';return;}
  if(!$('sch-emp').value&&$('sch-emp-search').value.trim()){err.textContent='Elegí el operario de la lista de resultados (o dejá el campo vacío para no asignar)';err.style.display='block';return;}
  var body={orden_operacion_id:+$('sch-oo').value,maquina_id:+$('sch-maq').value,empleado_id:$('sch-emp').value||null,
    inicio:f+' '+hh,jornada_horas:+$('sch-jor').value,cantidad_plan:+$('sch-qty').value||0,obs:$('sch-obs').value};
  if(!id){body.repetir=+$('sch-rep').value||0;body.solo_habiles=$('sch-hab').value==='1';}
  var btn=$('sch-save');btn.disabled=true;
  try{
    var r=await api(id?'/api/scheduling/'+id:'/api/scheduling',{method:id?'PUT':'POST',body:JSON.stringify(body)});
    if(!r||r.error){err.textContent=(r&&r.error)||'No se pudo guardar';err.style.display='block';return;}
    closeMo('mo-sch');
    var n=(r.ids||[]).length;
    if(r.avisos&&r.avisos.length)toast((n>1?n+' bloques creados. ':'Guardado. ')+r.avisos.join(' · '),'w');
    else toast(n>1?n+' bloques creados':'Planificación guardada');
    schRefrescar();
  }finally{btn.disabled=false;}
}
async function schBorrar(){
  var id=$('sch-id').value;if(!id)return;
  if(!await confirmar('¿Eliminar este bloque de la planificación?'))return;
  var r=await apiBorrar('/api/scheduling/'+id,'Bloque quitado de la planificación');
  if(r&&r.error){toast(r.error,'e');return;}
  closeMo('mo-sch');toast('Bloque eliminado');schRefrescar();
}


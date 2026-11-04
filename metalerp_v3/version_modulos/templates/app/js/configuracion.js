// ── Configuración ────────────────────────────────────────────────────────────
async function loadConfig(){
  const data = await api('/api/config');
  if(!data || data.error){ toast('Error cargando configuración','e'); return; }
  loadRoles();
  if($('cfg-mo-wrap')) $('cfg-mo-wrap').style.display = VER_MONETARIO ? '' : 'none';

  $('cfg-nombre').value    = data.empresa_nombre?.valor    || '';
  $('cfg-subtitulo').value = data.empresa_subtitulo?.valor || '';
  $('cfg-dir').value       = data.empresa_direccion?.valor || '';
  $('cfg-tel').value       = data.empresa_telefono?.valor  || '';
  $('cfg-email').value     = data.empresa_email?.valor     || '';

  var hex = (data.pdf_color_hex?.valor || '2C5F8A').replace('#','');
  $('cfg-color-hex').value    = hex.toUpperCase();
  $('cfg-color-picker').value = '#' + hex;

  // El servidor ya no manda estas claves al restringido (ver
  // CONFIG_CLAVES_MONETARIAS): sus controles se eliminan de la pantalla.
  if(!VER_MONETARIO){
    ['cfg-costos','cfg-precios','cfg-valor-hora-mo-actual'].forEach(function(id){
      var el=$(id); if(!el) return;
      (el.closest('label')||el.closest('.fg')||el).remove();
    });
  }
  if($('cfg-costos'))  $('cfg-costos').checked  = data.pdf_mostrar_costos?.valor  === '1';
  if($('cfg-precios')) $('cfg-precios').checked = data.pdf_mostrar_precios?.valor === '1';
  $('cfg-nota-pie').value  = data.pdf_nota_pie?.valor || '';
  if($('cfg-valor-hora-mo')) $('cfg-valor-hora-mo').value = data.valor_hora_mo?.valor || '';
  if($('cfg-valor-hora-mo-actual'))
    $('cfg-valor-hora-mo-actual').textContent = fmtM(parseFloat(data.valor_hora_mo?.valor||0));
  if($('cfg-moneda')) $('cfg-moneda').value = data.moneda?.valor || 'ARS';
  loadDolar();

  $('cfg-msg').textContent = 'Configuración cargada ✓';
  setTimeout(function(){ $('cfg-msg').textContent = ''; }, 2000);
  loadCatMaq();
  loadCatProd();
}

async function saveConfig(){
  var hex = $('cfg-color-hex').value.replace('#','').trim() || '2C5F8A';
  var payload = {
    empresa_nombre:      $('cfg-nombre').value,
    empresa_subtitulo:   $('cfg-subtitulo').value,
    empresa_direccion:   $('cfg-dir').value,
    empresa_telefono:    $('cfg-tel').value,
    empresa_email:       $('cfg-email').value,
    pdf_color_hex:       hex.toUpperCase(),
    ...(VER_MONETARIO ? {
      pdf_mostrar_costos:  $('cfg-costos').checked  ? '1' : '0',
      pdf_mostrar_precios: $('cfg-precios').checked ? '1' : '0',
    } : {}),
    pdf_nota_pie:        $('cfg-nota-pie').value,
    valor_hora_mo:       $('cfg-valor-hora-mo').value || '0',
  };
  const res = await api('/api/config', {method:'POST', body:JSON.stringify(payload)});
  if(res.ok){
    toast('Configuración guardada');
    $('cfg-msg').textContent = 'Los próximos PDFs usarán esta configuración.';
    setTimeout(function(){ $('cfg-msg').textContent = ''; }, 3000);
  } else {
    toast(res.error || 'Error al guardar','e');
  }
}

async function saveValorHoraMO(){
  var valor = $('cfg-valor-hora-mo').value || '0';
  const res = await api('/api/config', {method:'POST', body:JSON.stringify({valor_hora_mo: valor})});
  if(res.ok){
    toast('Mano de obra guardada');
    $('cfg-valor-hora-mo-actual').textContent = fmtM(parseFloat(valor));
    $('cfg-mo-msg').textContent = 'Guardado ✓';
    setTimeout(function(){ $('cfg-mo-msg').textContent = ''; }, 3000);
  } else {
    toast(res.error || 'Error al guardar','e');
    $('cfg-mo-msg').textContent = 'Error al guardar';
  }
}

// ── Moneda y cotización del dólar ────────────────────────────────────────────
let _dolar=null;
async function loadDolar(){
  const box=$('cfg-dolar-info'); if(!box) return;
  const d=await api('/api/dolar');
  if(!d||d.error){box.innerHTML='<div class="em">No se pudo leer la cotización.</div>';return;}
  _dolar=d;
  const sel=$('cfg-dolar-casa');
  sel.innerHTML=Object.entries(d.casas).map(([k,v])=>'<option value="'+k+'"'+(k===d.casa?' selected':'')+'>'+v+'</option>').join('');
  const a=d.actual, fmtC=v=>v==null?'—':'$'+Number(v).toLocaleString('es-AR',{minimumFractionDigits:2,maximumFractionDigits:2});
  let h='';
  if(a){
    const vieja=a.fecha!==d.hoy;
    h+='<div style="font-size:15px;margin-bottom:4px">1 US$ = <b>'+fmtC(a.venta)+'</b> <span class="tz-sub">venta'+(a.compra!=null?' · compra '+fmtC(a.compra):'')+'</span></div>'
      +'<div class="tz-sub">'+(a.fuente==='manual'?'Cargada a mano':'Traída de DolarAPI')+' el '+fmtD(a.fecha)+(a.creado?' a las '+a.creado.slice(11,16):'')
      +(vieja?' · <span class="fecha-por-vencer">no es de hoy</span>':'')+'</div>';
  } else h+='<div class="em" style="padding:6px 0">Todavía no hay cotización de este tipo. Tocá «Actualizar ahora» o cargala a mano.</div>';
  if(d.estado&&d.estado.error)
    h+='<div class="al al-w" style="margin-top:8px">No se pudo traer la cotización de internet'+(d.estado.ultimo_intento?' ('+d.estado.ultimo_intento.slice(11,16)+')':'')+'. Se usa la última guardada.</div>';
  h+='<div class="tz-sub" style="margin-top:6px">Se actualiza sola al arrancar el servidor y cada 3 horas.</div>';
  if(d.cambios&&d.cambios.length){
    h+='<div class="tz-lbl">Cambios de moneda</div>'+d.cambios.map(c=>'<div class="tz-sub">'+fmtD(c.fecha)+' · '+(c.origen==='ARS'?'Pesos':'Dólares')+' → '+(c.destino==='ARS'?'Pesos':'Dólares')
      +' a '+fmtC(c.cotizacion)+' · '+(c.filas||0)+' precios · '+(c.usuario_nombre||'—')+'</div>').join('');
  }
  box.innerHTML=h;
}
async function cambiarDolarCasa(v){
  const r=await api('/api/config',{method:'POST',body:JSON.stringify({dolar_casa:v})});
  if(r.ok){toast('Tipo de dólar: '+(_dolar?_dolar.casas[v]:v));loadDolar();}else toast(r.error||'Error','e');
}
async function actualizarDolarAhora(){
  const r=await api('/api/dolar/actualizar',{method:'POST'});
  if(r.ok)toast('Cotización actualizada');else toast(r.error||'Error','e');
  loadDolar();
}
async function cargarDolarManual(){
  const v=await pedirTexto('Cotización de venta del dólar '+(_dolar?_dolar.casas[_dolar.casa]:'')+' (pesos por 1 US$). Vale hasta la próxima actualización automática.', _dolar&&_dolar.actual?String(_dolar.actual.venta):'');
  if(v==null)return;
  const t=String(v).trim(), n=parseFloat(t.includes(',')?t.replace(/\./g,'').replace(',','.'):t);
  if(!(n>0)){toast('Cotización inválida','w');return;}
  const r=await api('/api/dolar/manual',{method:'POST',body:JSON.stringify({venta:n})});
  if(r.ok){toast('Cotización guardada');loadDolar();}else toast(r.error||'Error','e');
}
function cambioMonedaSel(sel){
  const destino=sel.value;
  sel.value=MONEDA;  // no cambia hasta confirmar la conversión
  if(destino===MONEDA)return;
  $('mon-destino').value=destino;
  $('mon-title').textContent=destino==='USD'?'Pasar los precios a dólares':'Pasar los precios a pesos';
  $('mon-aviso').innerHTML='<div>'+(destino==='USD'
    ?'Los precios vigentes se van a <b>dividir</b> por la cotización'
    :'Los precios vigentes se van a <b>multiplicar</b> por la cotización')
    +'. Lo ya emitido (OCs, presupuestos, pedidos, OTTs y OTs) queda en la moneda en que se hizo. Antes de convertir se hace una copia completa de la base.</div>';
  const a=_dolar&&_dolar.actual;
  $('mon-cot').value=a?a.venta:'';
  $('mon-cot-info').textContent=a?('Dólar '+_dolar.casas[_dolar.casa]+' del '+fmtD(a.fecha)+'. Podés cambiarla.'):'No hay cotización guardada: cargala.';
  $('mon-preview').innerHTML='';
  $('mon-confirmar').disabled=true;
  $('mon-cot').oninput=function(){$('mon-confirmar').disabled=true;$('mon-preview').innerHTML='';};
  openMo('mo-moneda');
  if(a)vistaPreviaMoneda();
}
function cancelarCambioMoneda(){closeMo('mo-moneda');if($('cfg-moneda'))$('cfg-moneda').value=MONEDA;}
async function vistaPreviaMoneda(){
  const destino=$('mon-destino').value, cot=parseFloat($('mon-cot').value);
  if(!(cot>0)){toast('Indicá la cotización','w');return;}
  $('mon-preview').innerHTML='<div class="ld">Calculando...</div>';
  const d=await api('/api/moneda/vista_previa?destino='+destino+'&cotizacion='+cot);
  if(!d||d.error){$('mon-preview').innerHTML='<div class="em">'+_tz((d&&d.error)||'Error')+'</div>';return;}
  const fa=v=>fmtMD(v,d.origen), fd=v=>fmtMD(v,d.destino);
  let total=0,h='';
  d.grupos.forEach(g=>{
    total+=g.cantidad;
    if(!g.cantidad){h+='<div class="tz-sub" style="margin:4px 0">'+_tz(g.descripcion)+': nada para convertir.</div>';return;}
    h+='<details class="tz-lote"'+(g.cantidad<=5?' open':'')+'><summary><b>'+_tz(g.descripcion)+'</b> · '+g.cantidad+'</summary>'
      +'<table class="tz-tbl"><tr><th>Ítem</th><th>Ahora</th><th>Queda</th></tr>'
      +g.filas.slice(0,200).map(r=>'<tr><td>'+_tz(r.nombre)+'</td><td>'+fa(r.antes)+'</td><td><b>'+fd(r.despues)+'</b></td></tr>').join('')
      +(g.filas.length>200?'<tr><td colspan="3" class="tz-sub">… y '+(g.filas.length-200)+' más</td></tr>':'')+'</table></details>';
  });
  $('mon-preview').innerHTML='<div style="font-size:12.5px;margin-bottom:6px">Se van a convertir <b>'+total+'</b> precios con 1 US$ = $'+cot.toLocaleString('es-AR')+'.</div>'+h;
  $('mon-confirmar').disabled=!total;
}
async function confirmarCambioMoneda(){
  const destino=$('mon-destino').value, cot=parseFloat($('mon-cot').value);
  if(!await confirmar('¿Convertir los precios a '+(destino==='USD'?'dólares':'pesos')+' con 1 US$ = $'+cot.toLocaleString('es-AR')+'? Se hace una copia de la base antes; para volver atrás hay que convertir de nuevo.'))return;
  const r=await api('/api/moneda/cambiar',{method:'POST',body:JSON.stringify({destino:destino,cotizacion:cot})});
  if(r.ok){toast('Listo: '+r.filas+' precios convertidos. Recargando…');closeMo('mo-moneda');setTimeout(()=>location.reload(),1200);}
  else toast(r.error||'Error','e');
}
// Etiquetas fijas "($)" en los formularios: muestran la moneda del sistema.
if(MONEDA==='USD')document.querySelectorAll('label').forEach(l=>l.childNodes.forEach(n=>{if(n.nodeType===3&&n.nodeValue.includes('($)'))n.nodeValue=n.nodeValue.replace('($)','(US$)');}));

// ── Carga masiva ─────────────────────────────────────────────────────────────
let _bulkWb = null;
let _bulkSchema = null;

async function loadCargaMasiva(){
  if(_bulkSchema) return renderBulkSchema();
  const schema = await api('/api/bulk/schema');
  _bulkSchema = schema;
  renderBulkSchema();
}

function renderBulkSchema(){
  const tables = Object.keys(_bulkSchema).sort();
  const container = $('bulk-schema-list');
  container.innerHTML = '<div id="bulk-tbl-grid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:8px"></div>';
  const grid = document.getElementById('bulk-tbl-grid');
  tables.forEach(function(t){
    const cols = _bulkSchema[t];
    const nonPk = cols.filter(function(c){return !c.pk;});
    const div = document.createElement('div');
    div.style.cssText = 'border:1px solid var(--color-border-tertiary);border-radius:8px;padding:10px 12px;font-size:11px;background:var(--color-background-primary)';
    div.innerHTML = '';
    // Header row
    const hdr = document.createElement('div');
    hdr.style.cssText = 'display:flex;align-items:center;justify-content:space-between;margin-bottom:4px';
    const nameSpan = document.createElement('span');
    nameSpan.style.cssText = 'font-weight:700;font-size:12px';
    nameSpan.textContent = t;
    const dlBtn = document.createElement('button');
    dlBtn.className = 'btn btn-s btn-p';
    dlBtn.style.cssText = 'font-size:10px;padding:2px 7px';
    dlBtn.title = 'Descargar plantilla Excel';
    dlBtn.textContent = '↓ Plantilla';
    dlBtn.onclick = (function(tn){ return function(e){ e.stopPropagation(); descargarPlantilla(tn); }; })(t);
    hdr.appendChild(nameSpan);
    hdr.appendChild(dlBtn);
    div.appendChild(hdr);
    // Count subtitle
    const sub = document.createElement('div');
    sub.style.cssText = 'color:var(--color-text-secondary);margin-bottom:6px;font-size:11px';
    sub.textContent = nonPk.length + ' columnas importables';
    div.appendChild(sub);
    // Collapsible cols panel
    const colPanel = document.createElement('div');
    colPanel.className = 'bulk-cols';
    colPanel.style.display = 'none';
    div.appendChild(colPanel);
    // Toggle button
    const togBtn = document.createElement('button');
    togBtn.style.cssText = 'font-size:10px;color:var(--color-text-secondary);background:none;border:none;cursor:pointer;padding:0;margin-top:2px';
    togBtn.textContent = 'Ver columnas ▾';
    togBtn.onclick = (function(d, tn){ return function(e){ e.stopPropagation(); expandBulkTable(d, tn); }; })(div, t);
    div.appendChild(togBtn);
    grid.appendChild(div);
  });
}


function expandBulkTable(el, tname){
  const colDiv = el.querySelector('.bulk-cols');
  const btn = el.querySelector('button:last-child');
  if(colDiv.style.display === 'block'){
    colDiv.style.display = 'none';
    if(btn) btn.textContent = 'Ver columnas ▾';
    return;
  }
  const cols = _bulkSchema[tname];
  colDiv.innerHTML = '<div style="border-top:1px solid var(--color-border-tertiary);margin:6px 0 4px"></div>'
    + cols.map(function(c){
      const badge = c.pk
        ? '<span style="font-size:9px;background:#e8f0fe;color:#1a56db;border-radius:3px;padding:0 4px;margin-left:4px">PK</span>'
        : c.notnull
          ? '<span style="font-size:9px;color:#D85A30;margin-left:2px">*</span>'
          : '';
      return '<div style="padding:2px 0;display:flex;justify-content:space-between;align-items:center">'
        +'<span>'+c.name+badge+'</span>'
        +'<span style="color:var(--color-text-secondary);font-size:10px">'+c.type+'</span>'
        +'</div>';
    }).join('');
  colDiv.style.display = 'block';
  if(btn) btn.textContent = 'Ocultar ▴';
}

function descargarPlantilla(tname){
  if(!_bulkSchema || !_bulkSchema[tname]){ toast('Esquema no cargado','w'); return; }
  const cols = _bulkSchema[tname];
  // Columns to include: skip auto-increment PK, keep all others
  // Mismo criterio que CAMPOS_MONETARIOS del servidor: quien no puede ver
  // importes tampoco se lleva las columnas en la plantilla (ni puede cargarlas).
  const RE_MON = /precio|costo|monto|importe|subtotal|valor_hora|factur/i;
  const importCols = cols.filter(function(c){
    if(c.pk) return false;
    if(!VER_MONETARIO && RE_MON.test(c.name) && !/centro_costo|nro_factura/i.test(c.name)) return false;
    return true;
  });
  if(!importCols.length){ toast('Sin columnas importables','w'); return; }

  // Build worksheet: row 1 = column names, row 2 = types as hint, row 3+ = empty data rows
  const header = importCols.map(function(c){ return c.name; });
  const hints  = importCols.map(function(c){
    let h = c.type;
    if(c.notnull) h += ' (requerido)';
    return h;
  });

  // 5 empty example rows
  const emptyRows = [[],[],[],[],[]];

  const wsData = [header, hints].concat(emptyRows);
  const ws = XLSX.utils.aoa_to_sheet(wsData);

  // Style header row bold width (best-effort via col width)
  ws['!cols'] = header.map(function(h){
    return { wch: Math.max(h.length + 4, 14) };
  });

  // Freeze first row
  ws['!freeze'] = { xSplit: 0, ySplit: 1 };

  // Create workbook with sheet named exactly as the table
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, tname);

  // Download
  XLSX.writeFile(wb, 'plantilla_'+tname+'.xlsx');
  toast('Plantilla '+tname+'.xlsx descargada');
}

// _bulkWbs: array of {nombre, wb} for multiple files
var _bulkWbs = [];

function onBulkFile(input){
  const files = Array.from(input.files);
  if(!files.length){ _bulkWb=null; _bulkWbs=[]; $('bulk-sheets').innerHTML=''; $('bulk-run-btn').disabled=true; return; }
  _bulkWbs = [];
  let loaded = 0;
  const schema = _bulkSchema || {};
  let allSheets = [];

  files.forEach(function(file){
    const reader = new FileReader();
    reader.onload = function(e){
      try {
        const wb = XLSX.read(e.target.result, {type:'array'});
        _bulkWbs.push({nombre:file.name, wb:wb});
        wb.SheetNames.forEach(function(s){ allSheets.push({sheet:s,file:file.name,wb:wb}); });
      } catch(err) {
        allSheets.push({sheet:'ERROR:'+file.name, file:file.name, wb:null, error:err.message});
      }
      loaded++;
      if(loaded === files.length){
        // All files loaded — render summary
        let h = '<div style="font-size:12px;font-weight:600;margin-bottom:6px">'+files.length+' archivo'+(files.length!==1?'s':'')+' — hojas detectadas:</div>';
        allSheets.forEach(function(item){
          if(item.error){
            h += '<div style="font-size:11px;color:red;padding:2px 0">✕ '+item.file+': '+item.error+'</div>';
            return;
          }
          const valid = item.sheet in schema;
          h += '<div style="font-size:11px;padding:2px 0;display:flex;align-items:center;gap:6px">'
            +'<span class="b '+(valid?'bg':'br')+'" style="font-size:10px">'+(valid?'OK':'?')+'</span>'
            +'<span><b>'+item.sheet+'</b>'+(files.length>1?' <span style="color:var(--color-text-secondary);font-size:10px">('+item.file+')</span>':'')+'</span>'
            +(valid?'':' <span style="color:var(--color-text-secondary);font-size:10px">(tabla no encontrada)</span>')
            +'</div>';
        });
        const validCount = allSheets.filter(function(i){ return i.wb && (i.sheet in schema); }).length;
        h += '<div style="font-size:11px;color:var(--color-text-secondary);margin-top:6px">'+validCount+' hoja'+(validCount!==1?'s':'')+' válida'+(validCount!==1?'s':'')+' en total</div>';
        $('bulk-sheets').innerHTML = h;
        $('bulk-run-btn').disabled = validCount === 0;
        // Keep _bulkWb pointing to first file for backward compat
        _bulkWb = _bulkWbs.length ? _bulkWbs[0].wb : null;
      }
    };
    reader.readAsArrayBuffer(file);
  });
}

async function runBulkImport(){
  if(!_bulkWbs.length && !_bulkWb){toast('Seleccioná un archivo primero','w');return;}
  const wbList = _bulkWbs.length ? _bulkWbs.map(function(x){return x.wb;}) : [_bulkWb];
  const mode = $('bulk-mode').value;
  const schema = _bulkSchema || {};
  const log = $('bulk-log');
  log.innerHTML = '';
  $('bulk-run-btn').disabled = true;

  let totalInserted = 0, totalErrors = 0;

  for(const {wb: _curWb, sheet} of wbList.flatMap(function(wb){ return wb.SheetNames.map(function(s){return {wb:wb,sheet:s};}); })){
    if(!(sheet in schema)){
      log.innerHTML += '<div style="color:var(--color-text-secondary)">⊘ '+sheet+': tabla no encontrada, omitida</div>';
      continue;
    }
    const ws = _curWb.Sheets[sheet];
    const rows = XLSX.utils.sheet_to_json(ws, {defval: null});
    if(!rows.length){
      log.innerHTML += '<div style="color:var(--color-text-secondary)">— '+sheet+': hoja vacía</div>';
      continue;
    }
    log.innerHTML += '<div style="color:var(--color-text-secondary)">↑ '+sheet+': enviando '+rows.length+' filas...</div>';

    const res = await api('/api/bulk/import', {
      method:'POST',
      body: JSON.stringify({table: sheet, rows: rows, mode: mode})
    });

    if(res.ok){
      totalInserted += res.inserted;
      const errPart = res.errors && res.errors.length
        ? ' · <span style="color:#D85A30">'+res.errors.length+' errores</span>' : '';
      log.innerHTML += '<div style="color:var(--color-status-success)">✓ '+sheet
        +': '+res.inserted+'/'+res.total+' filas importadas'+errPart+'</div>';
      if(res.errors && res.errors.length){
        res.errors.slice(0,5).forEach(function(e){
          log.innerHTML += '<div style="font-size:10px;color:#D85A30;padding-left:12px">'+e+'</div>';
        });
        if(res.errors.length > 5)
          log.innerHTML += '<div style="font-size:10px;color:var(--color-text-secondary);padding-left:12px">...y '+(res.errors.length-5)+' más</div>';
        totalErrors += res.errors.length;
      }
    } else {
      log.innerHTML += '<div style="color:red">✗ '+sheet+': '+(res.error||'Error desconocido')+'</div>';
    }
  }

  log.innerHTML += '<div style="font-weight:600;margin-top:8px;font-size:12px">'
    +'Total: '+totalInserted+' filas importadas'
    +(totalErrors?' · '+totalErrors+' errores':'')
    +'</div>';
  $('bulk-run-btn').disabled = false;
  toast(totalInserted+' filas importadas'+(totalErrors?' ('+totalErrors+' errores)':''), totalErrors?'w':'g');
}


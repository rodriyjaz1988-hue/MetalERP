// ── Dashboard Operativo ──────────────────────────────────────────────────────
async function loadDashOperativo(){
  const [d, rend] = await Promise.all([
    api('/api/dashboard/operativo'),
    api('/api/dashboard/rendimiento_semanal'),
  ]);
  // ── Rendimiento semanal ───────────────────────────────────────────────────
  (function renderRendSemanal(){
    const el=$('dop-rend-semanal');
    if(!el) return;
    const semanas = rend.semanas || [];
    const semActual = rend.semana_actual || '';
    if(!semanas.length){
      el.innerHTML='<div class="em">Sin novedades registradas en las últimas 26 semanas.</div>';
      return;
    }
    const maxRend = Math.max(...semanas.map(function(s){return s.avg_rend||0;}), 100);
    let h = '<div style="overflow-x:auto"><table style="min-width:600px;border-collapse:collapse;width:100%">';
    h += '<tr><th style="font-size:10px;padding:4px;text-align:left;color:var(--color-text-secondary)">Semana</th>';
    h += '<th style="font-size:10px;padding:4px;text-align:left;color:var(--color-text-secondary)">Rendimiento promedio</th>';
    h += '<th style="font-size:10px;padding:4px;color:var(--color-text-secondary)">Novedades</th>';
    h += '<th style="font-size:10px;padding:4px;color:var(--color-text-secondary)">Producido</th></tr>';
    semanas.forEach(function(s){
      const pct = Math.min(s.avg_rend||0, 100);
      const barColor = pct>=90?'#1B5E20':pct>=70?'#2C5F8A':pct>=50?'#E65100':'#A32D2D';
      const isActual = s.semana === semActual;
      const bg = isActual ? 'background:var(--color-background-secondary)' : '';
      h += '<tr style="'+bg+'">';
      h += '<td style="padding:5px 8px;font-size:11px;white-space:nowrap;'+(isActual?'font-weight:700;color:var(--color-primary)':'')+'">';
      h += fmtD(s.fecha_inicio)+(isActual?' ◀ actual':'')+'</td>';
      h += '<td style="padding:5px 8px;min-width:200px">';
      h += '<div style="display:flex;align-items:center;gap:8px">';
      h += '<div style="flex:1;background:var(--color-border-tertiary);border-radius:3px;height:10px">';
      h += '<div style="background:'+barColor+';height:10px;border-radius:3px;width:'+pct+'%;transition:width .3s"></div></div>';
      h += '<span style="font-size:11px;font-weight:600;color:'+barColor+';min-width:36px">'+pct+'%</span></div></td>';
      h += '<td style="padding:5px 8px;font-size:11px;text-align:center">'+(s.novedades||0)+'</td>';
      h += '<td style="padding:5px 8px;font-size:11px;text-align:center">'+(s.total_prod||0)+'</td>';
      h += '</tr>';
    });
    h += '</table></div>';
    el.innerHTML = h;
  })();

  // Métricas
  const efic=d.eficiencia_ops;
  const rendVal=efic&&efic.avg_rend?Math.round(efic.avg_rend)+'%':'—';
  $('dop-metrics').innerHTML=
    '<div class="metric"><div class="ml">OTs activas</div><div class="mv">'+d.ot_activas+'</div></div>'
   +'<div class="metric"><div class="ml">Completadas este mes</div><div class="mv" style="color:var(--color-text-success)">'+d.ot_completadas_mes+'</div></div>'
   +'<div class="metric"><div class="ml">Stock crítico</div><div class="mv"'+(d.stock_critico>0?' style="color:#A32D2D"':'')+'>'+fN(d.stock_critico)+'</div>'
   +(d.stock_critico>0?'<div class="md e">materiales bajo mínimo</div>':'<div class="md">Sin alertas</div>')+'</div>'
   +'<div class="metric"><div class="ml">Lotes sin liberar</div><div class="mv"'+(d.lotes_pendientes>0?' style="color:#854F0B"':'')+'>'+fN(d.lotes_pendientes)+'</div></div>'
   +'<div class="metric"><div class="ml">Máquinas fuera</div><div class="mv"'+(d.maquinas_fuera>0?' style="color:#854F0B"':'')+'>'+d.maquinas_fuera+'</div></div>'
   +'<div class="metric"><div class="ml">Rendimiento promedio</div><div class="mv">'+rendVal+'</div>'
   +(rend&&rend.total_novedades?'<div class="md">'+rend.total_novedades+' novedades (30d)</div>':'')+'</div>';

  // OTs por estado
  if(!d.ots_por_estado.length){$('dop-estados').innerHTML='<div class="em">Sin órdenes.</div>';}
  else{
    let h='<table><tr><th>Estado</th><th>Cantidad</th></tr>';
    d.ots_por_estado.forEach(function(r){h+='<tr><td>'+sb(r.estado)+'</td><td><b>'+fN(r.cantidad)+'</b></td></tr>';});
    $('dop-estados').innerHTML=h+'</table>';
  }

  // Lotes pendientes
  if(!d.lotes_ingresados.length){$('dop-lotes').innerHTML='<div class="em">Sin lotes pendientes. ✓</div>';}
  else{
    let h='<table><tr><th>Lote</th><th>Material</th><th>Cant.</th><th>Ingreso</th></tr>';
    d.lotes_ingresados.forEach(function(r){
      h+='<tr><td><b>'+r.numero+'</b></td><td>'+r.mat_desc+'</td><td>'+fN(r.cantidad_disponible)+' '+r.unidad+'</td><td>'+fmtD(r.fecha_ingreso)+'</td></tr>';
    });
    $('dop-lotes').innerHTML=h+'</table>';
  }

  // Mantenimiento
  if(!d.mantto_proximo.length){$('dop-mant').innerHTML='<div class="al al-g">Sin tareas vencidas ni próximas</div>';}
  else{
    let html='';
    d.mantto_proximo.forEach(function(a){
      const det=[];
      if(a.proxima_fecha)det.push(fmtD(a.proxima_fecha));
      if(a.faltan_horas!=null)det.push(a.faltan_horas<=0?'pasada por '+fN(-a.faltan_horas,1)+' hs':'faltan '+fN(a.faltan_horas,1)+' hs');
      html+='<div class="al '+(a.estado==='Vencido'?'al-e':'al-w')+'">'+(a.estado==='Vencido'?'<b>Vencida</b> · ':'')+a.maquina+': '+a.tarea+(det.length?' — '+det.join(' · '):'')+'</div>';
    });
    $('dop-mant').innerHTML=html;
  }

  // OTs urgentes
  if(!d.ots_urgentes.length){$('dop-urgentes').innerHTML='<div class="al al-g">Sin OTs con vencimiento próximo</div>';}
  else{
    let h='<table><tr><th>OT</th><th>Producto</th><th>Cliente</th><th>Entrega</th></tr>';
    d.ots_urgentes.forEach(function(r){
      h+='<tr><td><b>'+r.numero+'</b></td><td>'+r.producto+'</td><td>'+(r.cliente||'—')+'</td>'
       +'<td style="color:#A32D2D;font-weight:600">'+fmtD(r.fecha_entrega)+'</td></tr>';
    });
    $('dop-urgentes').innerHTML=h+'</table>';
  }

  // Stock crítico
  if(!d.alertas_mat.length){$('dop-stock').innerHTML='<div class="al al-g">Sin materiales críticos</div>';}
  else{
    let html='';
    d.alertas_mat.forEach(function(a){
      html+='<div class="al al-e"><b>'+a.codigo+'</b> '+a.descripcion+' — '+fN(a.stock)+'/'+fN(a.stock_min)+' '+a.unidad+'</div>';
    });
    $('dop-stock').innerHTML=html;
  }

  // Tickets
  if(!d.alertas_tkt.length){$('dop-tkt').innerHTML='<div class="al al-g">Sin tickets abiertos</div>';}
  else{
    let html='';
    d.alertas_tkt.forEach(function(a){html+='<div class="al al-w"><b>'+a.maquina+'</b>: '+a.descripcion+' '+pb(a.prioridad)+'</div>';});
    $('dop-tkt').innerHTML=html;
  }
}

// ── Dashboard Económico ───────────────────────────────────────────────────────
async function loadDashEconomico(){
  const [d, cliData] = await Promise.all([
    api('/api/dashboard/economico'),
    api('/api/dashboard/facturacion_por_cliente'),
  ]);
  // ── Gráfico facturación por cliente por mes ───────────────────────────────
  (function renderCliChart(){
    if($('dec-chart-anio')) $('dec-chart-anio').textContent = cliData.anio;
    const el=$('dec-chart-cli'); if(!el) return;
    const meses = [];
    for(let m=1;m<=12;m++) meses.push(cliData.anio+'-'+(m<10?'0':'')+m);
    const mesActual = cliData.mes_actual;
    // Merge facturado + pedidos por mes+cliente
    const byKey = {};
    (cliData.facturado||[]).forEach(function(r){
      const k=r.mes+'|'+r.cliente; byKey[k]={mes:r.mes,cli:r.cliente,fact:r.total,ped:0};
    });
    (cliData.pedidos||[]).forEach(function(r){
      const k=r.mes+'|'+r.cliente;
      if(byKey[k]) byKey[k].ped=r.total;
      else byKey[k]={mes:r.mes,cli:r.cliente,fact:0,ped:r.total};
    });
    // Get unique clients (top 8 by total)
    const cliTotals={};
    Object.values(byKey).forEach(function(v){cliTotals[v.cli]=(cliTotals[v.cli]||0)+v.fact+v.ped;});
    const clientes=Object.keys(cliTotals).sort(function(a,b){return cliTotals[b]-cliTotals[a];}).slice(0,8);
    if(!clientes.length){el.innerHTML='<div class="em">Sin datos de facturación en '+cliData.anio+'.</div>';return;}
    const COLORS=['#2C5F8A','#A32D2D','#1B5E20','#E65100','#6A1B9A','#00695C','#F57F17','#4527A0'];
    // Build stacked bar chart SVG-style with HTML divs
    const maxMes = Math.max(...meses.map(function(m){
      let s=0; clientes.forEach(function(c){const v=byKey[m+'|'+c]; if(v) s+=v.fact+v.ped;}); return s;
    }), 1);
    let h='<div style="font-size:10px;display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px">';
    clientes.forEach(function(c,i){
      h+='<span style="display:flex;align-items:center;gap:4px">'
        +'<span style="width:12px;height:12px;border-radius:2px;background:'+COLORS[i%COLORS.length]+';display:inline-block"></span>'+c+'</span>';
    });
    h+='</div>';
    h+='<div style="display:flex;gap:4px;align-items:flex-end;height:140px;overflow-x:auto;padding-bottom:24px;position:relative">';
    meses.forEach(function(m){
      const isPast = m < mesActual;
      const isCurrent = m === mesActual;
      let top=0;
      clientes.forEach(function(c){const v=byKey[m+'|'+c]; if(v) top+=v.fact+v.ped;});
      const pct = top/maxMes;
      h+='<div style="flex:1;min-width:28px;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;position:relative">';
      if(top>0){
        let acc=0;
        clientes.forEach(function(c,ci){
          const v=byKey[m+'|'+c];
          const val=v?(v.fact+v.ped):0;
          if(!val) return;
          const h2=Math.round((val/maxMes)*120);
          const opacity=isPast?1:0.5;  // future = lighter
          const border=isPast?'':'2px dashed '+COLORS[ci%COLORS.length];
          const bg=isPast?COLORS[ci%COLORS.length]:'transparent';
          const textColor=isPast?'#fff':COLORS[ci%COLORS.length];
          h+='<div title="'+(VER_MONETARIO?(c+': '+fmtM(val)):c)+'" style="width:100%;height:'+h2+'px;background:'+bg+';border:'+border+';'
            +'opacity:'+opacity+';box-sizing:border-box;position:relative"></div>';
        });
      }
      const lbl=m.slice(5);
      const lblStyle='font-size:9px;position:absolute;bottom:-20px;white-space:nowrap;'
        +(isCurrent?'font-weight:700;color:var(--color-primary)':'color:var(--color-text-secondary)');
      h+='<span style="'+lblStyle+'">'+lbl+(isCurrent?' ◀':'')+'</span>';
      if(isCurrent) h+='<div style="position:absolute;top:0;bottom:20px;left:50%;width:1px;background:var(--color-primary);opacity:0.4"></div>';
      h+='</div>';
    });
    h+='</div>';
    el.innerHTML=h;
  })();
  // ── Ratio empleados ───────────────────────────────────────────────────────
  (function renderEmps(){
    const el=$('dec-emps'); if(!el) return;
    const emps=cliData.empleados||[];
    if(!emps.length){el.innerHTML='<div class="em">Sin empleados registrados.</div>';return;}
    const total=emps.reduce(function(s,e){return s+e.cantidad;},0);
    let h='<table><tr><th>Tipo</th><th>Cantidad</th><th>%</th></tr>';
    emps.forEach(function(e){
      const pct=Math.round(e.cantidad/total*100);
      h+='<tr><td>'+e.tipo+'</td><td><b>'+fN(e.cantidad)+'</b></td>'
        +'<td><div style="display:flex;align-items:center;gap:6px">'
        +'<div style="flex:1;background:var(--color-border-tertiary);border-radius:3px;height:8px">'
        +'<div style="background:var(--color-primary);height:8px;border-radius:3px;width:'+pct+'%"></div></div>'
        +'<span style="font-size:11px">'+pct+'%</span></div></td></tr>';
    });
    el.innerHTML=h+'</table>';
  })();

  // Métricas
  $('dec-metrics').innerHTML=
    '<div class="metric"><div class="ml">Facturación del mes</div><div class="mv">'+fmtM(d.facturacion_mes)+'</div></div>'
   +'<div class="metric"><div class="ml">Presupuestos este mes</div><div class="mv">'+d.presupuestos_mes+'</div></div>'
   +'<div class="metric"><div class="ml">Pedidos activos</div><div class="mv">'+d.pedidos_activos+'</div>'
   +'<div class="md">'+fmtM(d.valor_pedidos)+' en cartera</div></div>'
   +'<div class="metric"><div class="ml">Valor en producción</div><div class="mv">'+fmtM(d.valor_produccion)+'</div></div>'
   +'<div class="metric"><div class="ml">OC compras pendientes</div><div class="mv"'+(d.ocs_compra_pend>0?' style="color:#854F0B"':'')+'>'+d.ocs_compra_pend+'</div>'
   +'<div class="md">'+fmtM(d.monto_compras_pend)+'</div></div>';

  // Pedidos clientes
  if(!d.pedidos_cliente.length){$('dec-pedidos').innerHTML='<div class="em">Sin pedidos activos.</div>';}
  else{
    let h='<table><tr><th>N°</th><th>Cliente</th><th>Estado</th><th>Valor</th></tr>';
    d.pedidos_cliente.forEach(function(r){
      h+='<tr><td><b>'+r.numero+'</b></td><td>'+r.cliente+'</td><td>'+sb(r.estado)+'</td><td>'+fmtM(r.valor)+'</td></tr>';
    });
    $('dec-pedidos').innerHTML=h+'</table>';
  }

  // Presupuestos por estado
  if(!d.presupuestos_estado.length){$('dec-pres-estado').innerHTML='<div class="em">Sin presupuestos.</div>';}
  else{
    let h='<table><tr><th>Estado</th><th>Cantidad</th><th>Total</th></tr>';
    d.presupuestos_estado.forEach(function(r){
      h+='<tr><td>'+sb(r.estado)+'</td><td>'+fN(r.cantidad)+'</td><td>'+fmtM(r.total)+'</td></tr>';
    });
    $('dec-pres-estado').innerHTML=h+'</table>';
  }

  // Top clientes
  if(!d.top_clientes.length){$('dec-clientes').innerHTML='<div class="em">Sin datos.</div>';}
  else{
    let h='<table><tr><th>Cliente</th><th>Pedidos</th><th>Valor total</th></tr>';
    d.top_clientes.forEach(function(r){
      h+='<tr><td>'+r.razon+'</td><td>'+r.pedidos+'</td><td><b>'+fmtM(r.valor)+'</b></td></tr>';
    });
    $('dec-clientes').innerHTML=h+'</table>';
  }

  // Compras pendientes
  if(!d.compras_pendientes.length){$('dec-compras').innerHTML='<div class="al al-g">Sin OC pendientes</div>';}
  else{
    let h='<table><tr><th>N°</th><th>Proveedor</th><th>Estado</th><th>Monto</th><th>Entrega est.</th></tr>';
    d.compras_pendientes.forEach(function(r){
      h+='<tr><td><b>'+r.numero+'</b></td><td>'+r.proveedor+'</td><td>'+sb(r.estado)+'</td>'
       +'<td>'+fmtM(r.monto_total,r.moneda)+'</td><td>'+fmtD(r.fecha_entrega_est)+'</td></tr>';
    });
    $('dec-compras').innerHTML=h+'</table>';
  }

  // Facturación histórica
  if(!d.facturacion_historico.length){$('dec-historico').innerHTML='<div class="em">Sin datos de facturación.</div>';}
  else{
    const max=Math.max(...d.facturacion_historico.map(function(r){return r.total;}),1);
    let h='<table><tr><th>Mes</th><th>Facturado</th><th></th></tr>';
    d.facturacion_historico.forEach(function(r){
      const pct=Math.round(r.total/max*100);
      h+='<tr><td>'+r.mes+'</td><td>'+fmtM(r.total)+'</td>'
       +'<td style="width:120px"><div style="background:var(--color-border-tertiary);border-radius:3px;height:8px">'
       +'<div style="background:var(--color-text-info);height:8px;border-radius:3px;width:'+pct+'%"></div></div></td></tr>';
    });
    $('dec-historico').innerHTML=h+'</table>';
  }
}



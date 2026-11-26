/* Nexus - pestaña "Programas CNC": editor + simulación (usa cnc_sim.js). */
'use strict';
(function () {
const CNC = window.CNC;
const LH = 20;                       // alto de línea del editor (px)
const COLORES = ['#1F77B4', '#2CA02C', '#D62728', '#9467BD', '#E377C2', '#17BECF', '#8C564B', '#BCBD22'];
const q = id => document.getElementById(id);
const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
async function api(u, o) { try { const r = await fetch(u, Object.assign({ headers: { 'Content-Type': 'application/json' } }, o || {})); return await r.json(); } catch (e) { return { error: 'La app no responde' }; } }
function guardarLS(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { } }
function leerLS(k) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : null; } catch (e) { return null; } }
const nomO = n => n == null ? '' : (n < 10000 ? 'O' + String(n).padStart(4, '0') : 'O' + String(n).padStart(8, '0'));

const S = {
  montado: false, maq: '', lista: null, origen: null,   // origen: {tipo, nombre, numero, fecha}
  original: '', texto: '', res: null, simFull: null, simAnim: null, barra: null, over: {},
  t: 0, jugando: false, vel: 10, ultimoFrame: 0, lineaCur: -1, vista: null, avisosLinea: {}, colorHerr: {}
};

function css() {
  return `
#v-cnc .cnc-bar{display:flex;gap:8px;flex-wrap:wrap;align-items:end;margin:14px 0 10px}
#v-cnc .cnc-bar label{font-size:12.5px;color:var(--muted)}
#v-cnc .cnc-estado{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:0 0 10px;min-height:34px}
#v-cnc .cnc-estado b{font-family:var(--f-display);font-size:17px}
#v-cnc .cnc-main{display:grid;grid-template-columns:minmax(330px,5fr) 7fr;gap:12px;align-items:start}
@media (max-width:1050px){#v-cnc .cnc-main{grid-template-columns:1fr}}
#v-cnc .cnc-card{background:var(--panel);border:1px solid var(--line);border-radius:12px;box-shadow:var(--shadow,none);min-width:0;overflow:hidden}
#v-cnc .cnc-card h3{margin:0;padding:10px 14px;border-bottom:1px solid var(--line);font:700 14px var(--f-body);display:flex;gap:8px;align-items:center}
#v-cnc .cnc-card h3 .help{font-weight:400;margin-left:auto}
#v-cnc .cnc-ed{position:relative;height:min(64vh,640px);display:flex;font:13px/${LH}px var(--f-mono)}
#v-cnc .cnc-gut{width:52px;flex:none;overflow:hidden;background:var(--sunk);border-right:1px solid var(--line);color:var(--muted);text-align:right;user-select:none;position:relative}
#v-cnc .cnc-gut-in{position:absolute;left:0;right:0;top:0;padding:8px 0}
#v-cnc .cnc-gut div{height:${LH}px;padding-right:8px;cursor:pointer;position:relative}
#v-cnc .cnc-gut div.w::before,#v-cnc .cnc-gut div.b::before,#v-cnc .cnc-gut div.i::before{content:"";position:absolute;left:5px;top:6px;width:8px;height:8px;border-radius:50%}
#v-cnc .cnc-gut div.b::before{background:var(--bad)} #v-cnc .cnc-gut div.w::before{background:var(--warn)} #v-cnc .cnc-gut div.i::before{background:var(--idle)}
#v-cnc .cnc-gut div.cur{color:var(--fg);font-weight:700}
#v-cnc .cnc-area{position:relative;flex:1;min-width:0;overflow:hidden}
#v-cnc .cnc-hl,#v-cnc .cnc-ta{position:absolute;inset:0;margin:0;padding:8px 10px;font:inherit;white-space:pre;tab-size:4;border:0;box-sizing:border-box}
#v-cnc .cnc-hl{pointer-events:none;overflow:hidden;color:var(--fg)}
#v-cnc .cnc-hl-in{position:absolute;left:0;top:0;padding:8px 10px;min-width:100%;box-sizing:border-box}
#v-cnc .cnc-hl-in div{height:${LH}px;margin:0 -10px;padding:0 10px}
#v-cnc .cnc-hl-in div.cur{background:var(--accent-bg,rgba(31,95,139,.12));box-shadow:inset 3px 0 0 var(--accent)}
#v-cnc .cnc-hl-in div.cambio{background:rgba(214,160,0,.13)}
#v-cnc .cnc-hl-in div.cur.cambio{background:var(--accent-bg,rgba(31,95,139,.12))}
#v-cnc .cnc-ta{background:transparent;color:transparent;caret-color:var(--fg);resize:none;outline:none;overflow:auto}
#v-cnc .cnc-ta::selection{background:rgba(31,95,139,.28);color:transparent}
#v-cnc .k-c{color:#5E8C61;font-style:italic} #v-cnc .k-n{color:var(--muted)} #v-cnc .k-g{color:#1F5F8B;font-weight:700} #v-cnc .k-m{color:#A0459B;font-weight:700}
#v-cnc .k-t{color:#0E7C6B;font-weight:700;background:rgba(14,124,107,.10);border-radius:3px} #v-cnc .k-f{color:#9A5B00} #v-cnc .k-o{color:var(--accent);font-weight:700} #v-cnc .k-sk{color:var(--bad);font-weight:700}
@media (prefers-color-scheme: dark){#v-cnc .k-g{color:#7DB8E8} #v-cnc .k-m{color:#E29BDD} #v-cnc .k-t{color:#5FD3BF} #v-cnc .k-f{color:#F0B35A} #v-cnc .k-c{color:#8FBF8F}}
#v-cnc .cnc-cv-wrap{position:relative;height:min(52vh,520px);background:var(--sunk);touch-action:none}
#v-cnc canvas{display:block;width:100%;height:100%;cursor:grab}
#v-cnc canvas.arr{cursor:grabbing}
#v-cnc .cnc-lect{position:absolute;left:10px;top:8px;font:12px/1.5 var(--f-mono);background:color-mix(in srgb,var(--panel) 88%,transparent);border:1px solid var(--line);border-radius:8px;padding:6px 9px;pointer-events:none;color:var(--fg)}
#v-cnc .cnc-zoom{position:absolute;right:8px;top:8px;display:flex;gap:4px}
#v-cnc .cnc-zoom .btn{padding:4px 9px}
#v-cnc .cnc-ctrl{display:flex;gap:6px;align-items:center;flex-wrap:wrap;padding:10px 12px;border-top:1px solid var(--line)}
#v-cnc .cnc-ctrl input[type=range]{flex:1;min-width:140px;accent-color:var(--accent)}
#v-cnc .cnc-ctrl .t{font:12.5px var(--f-mono);color:var(--muted);min-width:96px;text-align:right}
#v-cnc .cnc-ctrl .vel{display:inline-flex;border:1px solid var(--line);border-radius:8px;overflow:hidden}
#v-cnc .cnc-ctrl .vel button{border:0;background:var(--panel);color:var(--muted);font:600 12px var(--f-body);padding:6px 8px;cursor:pointer}
#v-cnc .cnc-ctrl .vel button.on{background:var(--accent);color:#fff}
#v-cnc .cnc-bajo{display:grid;grid-template-columns:minmax(250px,1fr) minmax(300px,1.4fr) minmax(300px,1.6fr);gap:12px;margin-top:12px;align-items:start}
@media (max-width:1050px){#v-cnc .cnc-bajo{grid-template-columns:1fr}}
#v-cnc .cnc-pad{padding:10px 14px}
#v-cnc .cnc-barra{display:grid;grid-template-columns:1fr 1fr;gap:8px 10px}
#v-cnc .cnc-barra label{font-size:12px;color:var(--muted)} #v-cnc .cnc-barra input{width:100%}
#v-cnc table.cnc-t{width:100%;border-collapse:collapse;font-size:13px}
#v-cnc table.cnc-t td,#v-cnc table.cnc-t th{padding:5px 6px;border-bottom:1px solid var(--line);text-align:left;vertical-align:middle}
#v-cnc table.cnc-t th{font-size:11.5px;color:var(--muted);font-weight:600;text-transform:uppercase;letter-spacing:.03em}
#v-cnc table.cnc-t select,#v-cnc table.cnc-t input{padding:4px 6px;font-size:12.5px}
#v-cnc .cnc-dot{display:inline-block;width:11px;height:11px;border-radius:3px;vertical-align:-1px;margin-right:6px}
#v-cnc .cnc-av{list-style:none;margin:0;padding:0;max-height:300px;overflow:auto}
#v-cnc .cnc-av li{display:flex;gap:8px;padding:6px 14px;border-bottom:1px solid var(--line);cursor:pointer;font-size:13px;align-items:baseline}
#v-cnc .cnc-av li:hover{background:var(--hover,rgba(0,0,0,.03))}
#v-cnc .cnc-av .ln{font:12px var(--f-mono);color:var(--muted);min-width:4.5ch;text-align:right}
#v-cnc .cnc-av .nv{flex:none;width:9px;height:9px;border-radius:50%;margin-top:4px}
#v-cnc .cnc-tiempo{display:flex;gap:14px;flex-wrap:wrap;padding:10px 14px;border-top:1px solid var(--line)}
#v-cnc .cnc-tiempo div{display:flex;flex-direction:column} #v-cnc .cnc-tiempo b{font:700 18px var(--f-display)} #v-cnc .cnc-tiempo span{font-size:11.5px;color:var(--muted)}
#v-cnc .cnc-vacio{padding:40px 20px;text-align:center;color:var(--muted)}
#v-cnc .pill{display:inline-block;font-size:11.5px;font-weight:600;border-radius:999px;padding:2px 9px;background:var(--sunk);color:var(--muted)}
#v-cnc .pill.warn{background:var(--warn-bg);color:var(--warn)} #v-cnc .pill.ok{background:var(--ok-bg);color:var(--ok)}
`;
}

function html() {
  return `
<div class="help" style="max-width:90ch;margin:14px 0 0">Abrí un programa (del último backup, leído ahora del torno o un archivo de la PC), cambialo en el editor y mirá en la simulación lo que le hace a la pieza. Nada se manda al torno desde acá: guardás una versión o la dejás en la carpeta del torno y la cargás desde <b>Enviar programa</b>.</div>
<div class="cnc-bar">
  <label>Máquina<br><select id="cnc-maq"></select></label>
  <label>Programa del último backup<br><select id="cnc-prog" style="min-width:250px"></select></label>
  <button class="btn" id="cnc-abrir-bk">Abrir</button>
  <span style="width:1px;align-self:stretch;background:var(--line);margin:0 4px"></span>
  <label>Leer ahora del torno<br><input id="cnc-num" type="number" min="1" max="99999999" placeholder="N° O" style="width:96px"></label>
  <button class="btn" id="cnc-leer">Leer</button>
  <span style="width:1px;align-self:stretch;background:var(--line);margin:0 4px"></span>
  <label>Versión guardada<br><select id="cnc-ver" style="min-width:200px"></select></label>
  <label class="btn" style="display:inline-flex;align-items:center;gap:6px;color:var(--fg)">Archivo de la PC<input type="file" id="cnc-arch" accept=".nc,.NC,.txt,.tap,*" hidden></label>
</div>
<div class="cnc-estado" id="cnc-estado"></div>
<div id="cnc-msg" class="aviso" hidden></div>
<div class="cnc-main">
  <div class="cnc-card">
    <h3>Programa <span class="help" id="cnc-ed-info"></span></h3>
    <div class="cnc-ed"><div class="cnc-gut"><div class="cnc-gut-in" id="cnc-gut"></div></div>
      <div class="cnc-area"><pre class="cnc-hl"><div class="cnc-hl-in" id="cnc-hl"></div></pre><textarea class="cnc-ta" id="cnc-ta" spellcheck="false" wrap="off" autocapitalize="characters" autocomplete="off"></textarea></div></div>
  </div>
  <div class="cnc-card">
    <h3>Simulación <span class="help">Arrastrá para mover, rueda para zoom, clic en el recorrido para ir a la línea</span></h3>
    <div class="cnc-cv-wrap" id="cnc-cvw"><canvas id="cnc-cv"></canvas><div class="cnc-lect" id="cnc-lect"></div>
      <div class="cnc-zoom"><button class="btn" id="cnc-z-mas" title="Acercar">+</button><button class="btn" id="cnc-z-menos" title="Alejar">−</button><button class="btn" id="cnc-z-aj" title="Ver la pieza entera">Ajustar</button><button class="btn" id="cnc-z-todo" title="Ver todo el recorrido">Todo</button></div></div>
    <div class="cnc-ctrl">
      <button class="btn" id="cnc-ini" title="Al principio">⏮</button>
      <button class="btn p" id="cnc-play" style="min-width:92px">▶ Simular</button>
      <button class="btn" id="cnc-paso" title="Hasta el final de la próxima línea con movimiento">Línea ⏭</button>
      <button class="btn" id="cnc-fin" title="Al final: pieza terminada">⏭</button>
      <span class="vel" id="cnc-vel"></span>
      <input type="range" id="cnc-rango" min="0" max="1000" value="1000">
      <span class="t" id="cnc-t">0:00 / 0:00</span>
    </div>
  </div>
</div>
<div class="cnc-bajo">
  <div class="cnc-card"><h3>Barra / pieza en bruto</h3>
    <div class="cnc-pad"><div class="cnc-barra">
      <label>Ø exterior<br><input type="number" step="0.1" id="cnc-b-d"></label>
      <label>Ø interior (si es tubo)<br><input type="number" step="0.1" id="cnc-b-din"></label>
      <label>Largo<br><input type="number" step="0.1" id="cnc-b-largo"></label>
      <label>Cara en Z<br><input type="number" step="0.1" id="cnc-b-cara"></label>
      <label>Fuera del plato<br><input type="number" step="0.1" id="cnc-b-sal"></label>
      <label style="display:flex;align-items:end"><button class="btn" id="cnc-b-sug" style="width:100%">Proponer según el programa</button></label>
    </div>
    <div class="help" style="margin-top:8px">El aviso de "rápido que corta material" depende de esta barra: si la pieza viene de otra operación, cargá sus medidas reales.</div>
    <label class="help" style="display:flex;gap:6px;align-items:center;margin-top:8px"><input type="checkbox" id="cnc-barra-sk"> Saltear bloques con / (Block Skip encendido)</label>
    <label class="help" style="display:flex;gap:6px;align-items:center;margin-top:4px"><input type="checkbox" id="cnc-girar" checked> Dar vuelta la pieza cuando el programa para con "GIRAR PIEZA"</label></div>
  </div>
  <div class="cnc-card"><h3>Herramientas <span class="help">Si el tipo está mal, cambialo</span></h3>
    <div style="overflow-x:auto"><table class="cnc-t"><thead><tr><th>T</th><th>Comentario</th><th>Tipo</th><th>Medida</th></tr></thead><tbody id="cnc-herr"></tbody></table></div>
    <div class="cnc-tiempo" id="cnc-tiempo"></div>
  </div>
  <div class="cnc-card"><h3>Avisos <span class="help" id="cnc-av-n"></span></h3><ul class="cnc-av" id="cnc-av"></ul></div>
</div>`;
}

/* ───── Montaje ───── */
function montar(sec) {
  if (S.montado) return;
  S.montado = true;
  const st = document.createElement('style'); st.textContent = css(); document.head.appendChild(st);
  sec.innerHTML = html();
  q('cnc-vel').innerHTML = [1, 5, 10, 30, 100].map(v => '<button data-v="' + v + '"' + (v === S.vel ? ' class="on"' : '') + '>x' + v + '</button>').join('');
  q('cnc-vel').onclick = e => { const v = +e.target.dataset.v; if (!v) return; S.vel = v; [...q('cnc-vel').children].forEach(b => b.classList.toggle('on', +b.dataset.v === v)); };
  const ta = q('cnc-ta');
  ta.addEventListener('input', () => { S.texto = ta.value; pintarEditor(); programarSim(); });
  ta.addEventListener('scroll', sincScroll);
  ['click', 'keyup'].forEach(ev => ta.addEventListener(ev, e => { if (ev === 'keyup' && !/Arrow|Page|Home|End/.test(e.key)) return; irALinea(lineaCursor(), false); }));
  ta.addEventListener('keydown', e => {
    if (e.key === 'Tab') { e.preventDefault(); document.execCommand('insertText', false, '  '); }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') { e.preventDefault(); guardarVersion(); }
  });
  q('cnc-gut').addEventListener('click', e => { const d = e.target.closest('div[data-l]'); if (d) { const l = +d.dataset.l; seleccionarLinea(l); irALinea(l, false); } });
  q('cnc-maq').onchange = () => { S.maq = q('cnc-maq').value; cargarLista(); };
  q('cnc-abrir-bk').onclick = abrirBackup;
  q('cnc-prog').ondblclick = abrirBackup;
  q('cnc-leer').onclick = leerTorno;
  q('cnc-num').onkeydown = e => { if (e.key === 'Enter') leerTorno(); };
  q('cnc-ver').onchange = abrirVersion;
  q('cnc-arch').onchange = abrirArchivo;
  q('cnc-play').onclick = () => { if (!S.res) return; if (S.jugando) parar(); else { if (S.t >= S.res.total - 1e-6) S.t = 0; jugar(); } };
  q('cnc-ini').onclick = () => { parar(); S.t = 0; dibujar(); };
  q('cnc-fin').onclick = () => { parar(); if (S.res) S.t = S.res.total; dibujar(); };
  q('cnc-paso').onclick = pasoLinea;
  q('cnc-rango').oninput = e => { if (!S.res) return; parar(); S.t = S.res.total * e.target.value / 1000; dibujar(); };
  ['d', 'din', 'largo', 'cara', 'sal'].forEach(k => q('cnc-b-' + k).addEventListener('change', leerBarra));
  q('cnc-b-sug').onclick = () => { if (!S.res) return; S.barra = CNC.barraSugerida(S.res); guardarBarra(); ponerBarra(); resimular(true); };
  q('cnc-barra-sk').onchange = () => simular(true);
  q('cnc-girar').onchange = () => simular(true);
  q('cnc-z-mas').onclick = () => zoom(1.4); q('cnc-z-menos').onclick = () => zoom(1 / 1.4);
  q('cnc-z-aj').onclick = () => { ajustar(false); dibujar(); }; q('cnc-z-todo').onclick = () => { ajustar(true); dibujar(); };
  eventosCanvas();
  new ResizeObserver(() => dibujar()).observe(q('cnc-cvw'));
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && S.jugando) parar(); });
  window.addEventListener('beforeunload', e => { if (cambiado()) { e.preventDefault(); e.returnValue = ''; } });
  estado(); pintarEditor(); dibujar();
}

/* ───── Máquinas, programas, versiones ───── */
async function cargarMaquinas() {
  const r = await api('/api/backup');
  const maqs = (r.maquinas || []).map(m => m.maquina);
  const sel = q('cnc-maq');
  const ant = S.maq || leerLS('nexus.cnc.maq') || maqs[0] || '';
  sel.innerHTML = maqs.length ? maqs.map(m => '<option' + (m === ant ? ' selected' : '') + '>' + esc(m) + '</option>').join('') : '<option value="">(sin máquinas Fanuc)</option>';
  S.maq = sel.value; cargarLista();
}
async function cargarLista() {
  guardarLS('nexus.cnc.maq', S.maq);
  q('cnc-prog').innerHTML = '<option>Cargando...</option>'; q('cnc-ver').innerHTML = '';
  if (!S.maq) { q('cnc-prog').innerHTML = '<option value="">—</option>'; return; }
  const r = await api('/api/cnc/programas?maquina=' + encodeURIComponent(S.maq));
  S.lista = r;
  if (r.error) { q('cnc-prog').innerHTML = '<option value="">' + esc(r.error) + '</option>'; return; }
  q('cnc-prog').innerHTML = (r.programas || []).length
    ? (r.programas || []).map(p => '<option value="' + p.numero + '">' + esc(p.nombre + (p.comentario ? '  ' + p.comentario : '')) + '</option>').join('')
    : '<option value="">' + (r.backup ? 'El backup no tiene programas' : 'Sin backup: hacé uno en la pestaña Backup') + '</option>';
  if (S.origen && S.origen.numero) q('cnc-prog').value = String(S.origen.numero);
  const vs = r.versiones || [];
  q('cnc-ver').innerHTML = '<option value="">' + (vs.length ? 'Elegí (' + vs.length + ')' : 'Ninguna todavía') + '</option>'
    + vs.map(v => '<option value="' + esc(v.archivo) + '">' + esc(v.nombre + ' · ' + v.fecha + (v.nota ? ' · ' + v.nota : '')) + '</option>').join('');
}
function cambiado() { return S.texto !== S.original && S.texto.trim() !== ''; }
function puedeReemplazar() { return !cambiado() || confirm('Hay cambios sin guardar en el editor. ¿Abrir otro programa igual y perderlos?'); }
function cargarTexto(txt, origen) {
  txt = String(txt || '').replace(/\r/g, '');
  txt = txt.replace(/^\s*%\s*\n/, '').replace(/\n\s*%\s*\n*$/, '\n');
  S.original = txt; S.texto = txt; S.origen = origen; S.over = leerLS('nexus.cnc.herr.' + clave()) || {};
  q('cnc-ta').value = txt; q('cnc-ta').scrollTop = 0; q('cnc-ta').scrollLeft = 0;
  S.barra = leerLS('nexus.cnc.barra.' + clave());
  S.vista = null; S.lineaCur = -1;
  simular(false);
  if (!S.barra) { S.barra = CNC.barraSugerida(S.res); }
  ponerBarra(); resimular(true);
  S.t = S.res ? S.res.total : 0;
  pintarEditor(); estado(); dibujar(); msg(null);
  if (origen && origen.numero) q('cnc-num').value = origen.numero;
}
function clave() { const n = numeroEnTexto(S.texto) || (S.origen && S.origen.numero) || 'x'; return (S.maq || '-') + '.' + n; }
function numeroEnTexto(t) { const m = String(t || '').match(/^\s*%?\s*O(\d{1,8})/m); return m ? parseInt(m[1], 10) : null; }
async function abrirBackup() {
  const n = parseInt(q('cnc-prog').value, 10);
  if (!n) return;
  if (!puedeReemplazar()) return;
  const r = await api('/api/cnc/abrir?maquina=' + encodeURIComponent(S.maq) + '&numero=' + n);
  if (r.error) return msg(false, r.error);
  cargarTexto(r.texto, { tipo: 'backup', nombre: r.nombre, numero: n, fecha: r.fecha });
}
async function leerTorno() {
  const n = parseInt(q('cnc-num').value, 10);
  if (!S.maq) return msg(false, 'Elegí la máquina');
  if (!n) return msg(false, 'Poné el número de programa (O) que querés leer del torno');
  if (!puedeReemplazar()) return;
  msg('info', 'Leyendo ' + nomO(n) + ' de ' + S.maq + '...');
  const r = await api('/api/backup/programa?ver=1&maquina=' + encodeURIComponent(S.maq) + '&numero=' + n);
  if (r.error) return msg(false, r.error);
  cargarTexto(r.texto, { tipo: 'torno', nombre: r.nombre, numero: n, fecha: 'leído ahora' });
}
async function abrirVersion() {
  const a = q('cnc-ver').value; if (!a) return;
  if (!puedeReemplazar()) { q('cnc-ver').value = ''; return; }
  const r = await api('/api/cnc/abrir?maquina=' + encodeURIComponent(S.maq) + '&version=' + encodeURIComponent(a));
  q('cnc-ver').value = '';
  if (r.error) return msg(false, r.error);
  cargarTexto(r.texto, { tipo: 'version', nombre: r.nombre, numero: r.numero, fecha: r.fecha, archivo: a });
}
function abrirArchivo(e) {
  const f = e.target.files[0]; if (!f) return;
  if (!puedeReemplazar()) { e.target.value = ''; return; }
  const rd = new FileReader();
  rd.onload = () => { const t = rd.result; cargarTexto(t, { tipo: 'archivo', nombre: f.name, numero: numeroEnTexto(t), fecha: 'archivo de la PC' }); e.target.value = ''; };
  rd.readAsText(f, 'latin1');
}
async function guardarVersion() {
  if (!S.texto.trim()) return msg(false, 'No hay programa para guardar');
  if (!S.maq) return msg(false, 'Elegí la máquina');
  const n = numeroEnTexto(S.texto) || (S.origen && S.origen.numero);
  if (!n) return msg(false, 'El programa no tiene número O en la primera línea');
  const nota = prompt('Nota para esta versión (opcional), por ejemplo qué cambiaste:', '');
  if (nota === null) return;
  const r = await api('/api/cnc/guardar', { method: 'POST', body: JSON.stringify({ maquina: S.maq, numero: n, texto: S.texto, nota: nota }) });
  if (r.error) return msg(false, r.error);
  S.original = S.texto; S.origen = Object.assign({}, S.origen || {}, { tipo: 'version', nombre: r.nombre, numero: n, fecha: r.fecha, archivo: r.archivo });
  msg(true, 'Guardado como ' + r.archivo + ' (carpeta programas\\editados\\' + S.maq + '). El torno no se tocó.');
  estado(); pintarEditor(); cargarLista();
}
function descargar() {
  if (!S.texto.trim()) return;
  const n = numeroEnTexto(S.texto) || (S.origen && S.origen.numero) || 1;
  const datos = ('%\n' + S.texto.replace(/\s+$/, '') + '\n%\n').replace(/\n/g, '\r\n');
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([datos], { type: 'application/octet-stream' }));
  a.download = (S.maq ? S.maq + '_' : '') + nomO(n) + '.NC'; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}
async function dejarEnCarpeta(reemplazar) {
  if (!S.maq) return msg(false, 'Elegí la máquina');
  const n = numeroEnTexto(S.texto) || (S.origen && S.origen.numero);
  if (!n) return msg(false, 'El programa no tiene número O en la primera línea');
  const malos = (S.simFull && S.simFull.choques.length) || 0, rojos = S.res ? S.res.avisos.filter(a => a.nivel === 'bad').length : 0;
  if (!reemplazar && (malos || rojos) && !confirm('La simulación tiene ' + (malos + rojos) + ' aviso(s) en rojo. ¿Dejar el programa en la carpeta del torno igual?')) return;
  const r = await api('/api/envio', { method: 'POST', body: JSON.stringify({ maquina: S.maq, numero: n, texto: S.texto, archivo: 'Editor CNC', reemplazar: !!reemplazar }) });
  if (r.existe) { if (confirm(r.programa + '.NC ya está en la carpeta de ' + S.maq + '. ¿Reemplazarlo?')) return dejarEnCarpeta(true); return; }
  if (r.error) return msg(false, r.error);
  msg(true, r.archivo + ' quedó en la carpeta de ' + S.maq + '. Para cargarlo en el torno andá a Enviar programa (Mandar al torno o FTP).');
}
function verCambios() {
  const a = S.original.replace(/\s+$/, '').split('\n'), b = S.texto.replace(/\s+$/, '').split('\n');
  const d = CNC.diferencias(a.map(x => x.trimEnd()), b.map(x => x.trimEnd()));
  if (!d) return msg(false, 'El programa es muy largo para comparar');
  const st = { '-': 'background:rgba(200,40,40,.14)', '+': 'background:rgba(30,150,70,.16)', '=': '' };
  const out = []; let igual = [];
  const vaciar = () => { if (igual.length > 6) { out.push(...igual.slice(0, 3)); out.push({ t: '...', l: '(' + (igual.length - 6) + ' líneas iguales)' }); out.push(...igual.slice(-3)); } else out.push(...igual); igual = []; };
  d.forEach(x => { if (x.t === '=') igual.push(x); else { vaciar(); out.push(x); } }); vaciar();
  const n2 = v => '<span style="color:var(--muted);display:inline-block;min-width:4.5ch;text-align:right">' + (v || '') + '</span>';
  const cuerpo = '<div class="help" style="margin-bottom:8px"><span style="background:rgba(200,40,40,.14);padding:1px 6px;border-radius:3px">− rojo</span> estaba en el original · <span style="background:rgba(30,150,70,.16);padding:1px 6px;border-radius:3px">+ verde</span> está ahora en el editor</div>'
    + '<pre style="margin:0;font:12.5px/1.45 var(--f-mono);white-space:pre">' + out.map(x => x.t === '...' ? '<div style="color:var(--muted);font-style:italic">          ' + esc(x.l) + '</div>' : '<div style="' + st[x.t] + '">' + n2(x.a) + ' ' + n2(x.b) + '  ' + (x.t === '=' ? ' ' : x.t) + ' ' + esc(x.l) + '</div>').join('') + '</pre>';
  if (typeof window.bkModal === 'function') window.bkModal('Cambios en ' + esc(S.origen ? S.origen.nombre : 'el programa'), cuerpo);
}
function volverOriginal() {
  if (!cambiado() || !confirm('¿Descartar los cambios y volver al programa como se abrió?')) return;
  q('cnc-ta').value = S.original; S.texto = S.original; simular(true); pintarEditor(); estado();
}
function msg(ok, t) {
  const e = q('cnc-msg'); if (!e) return;
  if (ok === null) { e.hidden = true; return; }
  e.hidden = false; e.className = 'aviso ' + (ok === 'info' ? 'warn' : ok ? 'ok' : 'bad'); e.textContent = t;
}
function lineasCambiadas() {
  if (!S.original && !S.texto) return 0;
  const a = S.original.split('\n'), b = S.texto.split('\n');
  if (a.length * b.length > 4e6) return a.length === b.length ? b.filter((l, i) => l.trimEnd() !== a[i].trimEnd()).length : -1;
  const d = CNC.diferencias(a.map(x => x.trimEnd()), b.map(x => x.trimEnd()));
  return d ? Math.max(d.filter(x => x.t === '+').length, d.filter(x => x.t === '-').length) : -1;
}
function marcarCambios() {
  // líneas del editor que no están en el original (para pintarlas)
  S.cambios = {};
  if (!cambiado()) return;
  const a = S.original.split('\n').map(x => x.trimEnd()), b = S.texto.split('\n').map(x => x.trimEnd());
  if (a.length * b.length > 4e6) return;
  const d = CNC.diferencias(a, b); if (!d) return;
  d.forEach(x => { if (x.t === '+') S.cambios[x.b - 1] = 1; });
}
function estado() {
  const e = q('cnc-estado'); if (!e) return;
  if (!S.origen && !S.texto) { e.innerHTML = '<span class="help">Elegí un programa para empezar.</span>'; return; }
  const n = numeroEnTexto(S.texto) || (S.origen && S.origen.numero);
  const com = (S.texto.match(/^\s*O\d+\s*\(([^)]*)\)/m) || [])[1] || '';
  const nc = cambiado() ? lineasCambiadas() : 0;
  const de = S.origen ? ({ backup: 'Backup ' + (S.origen.fecha || ''), torno: 'Leído del torno ahora', version: 'Versión ' + (S.origen.fecha || ''), archivo: S.origen.nombre }[S.origen.tipo] || '') : '';
  e.innerHTML = '<b>' + esc(nomO(n) || 'Programa') + '</b>' + (com ? '<span>' + esc(com) + '</span>' : '')
    + (S.maq ? '<span class="pill">' + esc(S.maq) + '</span>' : '') + (de ? '<span class="pill">' + esc(de) + '</span>' : '')
    + (nc ? '<span class="pill warn">' + (nc > 0 ? nc + ' línea' + (nc === 1 ? '' : 's') + ' cambiada' + (nc === 1 ? '' : 's') : 'con cambios') + '</span> <button class="btn" id="cnc-vc">Ver cambios</button><button class="btn" id="cnc-vo">Volver al original</button>' : (S.origen ? '<span class="pill ok">Sin cambios</span>' : ''))
    + '<span style="margin-left:auto;display:flex;gap:6px;flex-wrap:wrap"><button class="btn p" id="cnc-g" title="Ctrl+S">Guardar versión</button><button class="btn" id="cnc-d">Descargar .NC</button><button class="btn" id="cnc-c" title="Lo deja en la carpeta FTP del torno, no lo carga">Dejar en la carpeta del torno</button></span>';
  q('cnc-g').onclick = guardarVersion; q('cnc-d').onclick = descargar; q('cnc-c').onclick = () => dejarEnCarpeta(false);
  if (q('cnc-vc')) { q('cnc-vc').onclick = verCambios; q('cnc-vo').onclick = volverOriginal; }
}

/* ───── Editor ───── */
function pintarLinea(l) {
  let out = '', i = 0;
  const m = l.match(/^(\s*)\//);
  if (m) { out += esc(m[1]) + '<span class="k-sk">/</span>'; i = m[0].length; }
  const resto = l.slice(i);
  return out + resto.replace(/(\([^)]*\)?)|([A-Za-z])([+-]?[\d.]*)|([^A-Za-z(]+)/g, (t, c, L, n, otro) => {
    if (c) return '<span class="k-c">' + esc(c) + '</span>';
    if (otro !== undefined) return esc(otro);
    const u = L.toUpperCase(), cls = { G: 'k-g', M: 'k-m', T: 'k-t', N: 'k-n', F: 'k-f', S: 'k-f', O: 'k-o' }[u];
    return cls ? '<span class="' + cls + '">' + esc(L + n) + '</span>' : esc(L + n);
  });
}
function pintarEditor() {
  if (!q('cnc-hl')) return;
  marcarCambios();
  const ls = S.texto.split('\n');
  const av = S.avisosLinea || {};
  q('cnc-hl').innerHTML = ls.map((l, i) => '<div class="' + (i === S.lineaCur ? 'cur ' : '') + (S.cambios && S.cambios[i] ? 'cambio' : '') + '">' + (pintarLinea(l) || ' ') + '</div>').join('');
  q('cnc-gut').innerHTML = ls.map((l, i) => '<div data-l="' + i + '" class="' + (av[i] || '') + (i === S.lineaCur ? ' cur' : '') + '"' + (av[i] ? ' title="Ver aviso"' : '') + '>' + (i + 1) + '</div>').join('');
  q('cnc-ed-info').textContent = ls.length + ' líneas';
  sincScroll();
}
function marcarLineaCur(l) {
  if (l === S.lineaCur) return;
  const hl = q('cnc-hl'), gu = q('cnc-gut');
  [hl.children[S.lineaCur], gu.children[S.lineaCur]].forEach(e => e && e.classList.remove('cur'));
  S.lineaCur = l;
  [hl.children[l], gu.children[l]].forEach(e => e && e.classList.add('cur'));
}
function sincScroll() {
  const ta = q('cnc-ta');
  q('cnc-hl').style.transform = 'translate(' + (-ta.scrollLeft) + 'px,' + (-ta.scrollTop) + 'px)';
  q('cnc-gut').style.transform = 'translateY(' + (-ta.scrollTop) + 'px)';
}
function lineaCursor() { const ta = q('cnc-ta'); return ta.value.slice(0, ta.selectionStart).split('\n').length - 1; }
function seleccionarLinea(l) {
  const ta = q('cnc-ta'), ls = ta.value.split('\n');
  let p = 0; for (let k = 0; k < l && k < ls.length; k++) p += ls[k].length + 1;
  ta.focus({ preventScroll: true }); ta.setSelectionRange(p, p + (ls[l] || '').length);
  verLinea(l, true);
}
function verLinea(l, centrar) {
  const ta = q('cnc-ta'), y = l * LH, h = ta.clientHeight;
  if (centrar || y < ta.scrollTop + LH || y > ta.scrollTop + h - 2 * LH) ta.scrollTop = Math.max(0, y - h / 2);
  sincScroll();
}

/* ───── Simulación ───── */
let timerSim = null;
function programarSim() { clearTimeout(timerSim); timerSim = setTimeout(() => { simular(true); estado(); }, 350); }
function simular(mantenerT) {
  const t0 = S.res ? S.t / (S.res.total || 1) : 1;
  const enFin = !S.res || S.t >= S.res.total - 1e-6;
  S.res = CNC.interpretar(S.texto, { saltarBarra: q('cnc-barra-sk') && q('cnc-barra-sk').checked, girar: !(q('cnc-girar') && !q('cnc-girar').checked) });
  resimular(false);
  if (mantenerT && !enFin) S.t = Math.min(S.res.total, t0 * S.res.total); else S.t = S.res.total;
  dibujar();
}
function resimular(redibujar) {
  if (!S.res) return;
  if (!S.barra) S.barra = CNC.barraSugerida(S.res);
  S.simFull = new CNC.Sim(S.res, S.barra, S.over);
  S.simFull.hasta(1e12);
  S.simAnim = new CNC.Sim(S.res, S.barra, S.over);
  S.simAnim.herr = S.simFull.herr;
  // colores por herramienta
  S.colorHerr = {}; Object.keys(S.res.herramientas).sort((a, b) => a - b).forEach((k, i) => S.colorHerr[k] = COLORES[i % COLORES.length]);
  // avisos por línea
  S.avisosLinea = {};
  const todos = avisosTodos();
  todos.forEach(a => { const c = a.nivel === 'bad' ? 'b' : a.nivel === 'warn' ? 'w' : 'i'; const ya = S.avisosLinea[a.linea]; if (!ya || (c === 'b') || (c === 'w' && ya === 'i')) S.avisosLinea[a.linea] = c; });
  pintarHerr(); pintarAvisos(todos); pintarTiempo();
  if (!S.vista) ajustar(false);
  if (redibujar) { pintarEditor(); dibujar(); }
}
function avisosTodos() {
  const a = (S.res ? S.res.avisos : []).slice();
  (S.simFull ? S.simFull.choques : []).forEach(c => a.push({ linea: c.linea, nivel: 'bad', msg: c.msg, x: c.x, z: c.z }));
  const ord = { bad: 0, warn: 1, info: 2 };
  return a.sort((x, y) => ord[x.nivel] - ord[y.nivel] || x.linea - y.linea);
}
function pintarAvisos(todos) {
  const ul = q('cnc-av'); if (!ul) return;
  const nb = todos.filter(a => a.nivel === 'bad').length, nw = todos.filter(a => a.nivel === 'warn').length;
  q('cnc-av-n').textContent = todos.length ? (nb ? nb + ' en rojo · ' : '') + (nw ? nw + ' para revisar · ' : '') + todos.length + ' en total' : '';
  if (!S.texto.trim()) { ul.innerHTML = ''; return; }
  ul.innerHTML = todos.length ? todos.slice(0, 300).map(a => '<li data-l="' + a.linea + '"><span class="nv" style="background:var(--' + (a.nivel === 'bad' ? 'bad' : a.nivel === 'warn' ? 'warn' : 'idle') + ')"></span><span class="ln">' + (a.linea + 1) + '</span><span>' + esc(a.msg) + '</span></li>').join('')
    : '<li style="cursor:default"><span class="nv" style="background:var(--ok)"></span><span>Sin avisos: el recorrido no muestra problemas con esta barra.</span></li>';
  ul.onclick = e => { const li = e.target.closest('li[data-l]'); if (!li) return; const l = +li.dataset.l; seleccionarLinea(l); irALinea(l, false); };
}
function pintarHerr() {
  const tb = q('cnc-herr'); if (!tb) return;
  const H = S.res.herramientas, ks = Object.keys(H).sort((a, b) => a - b);
  if (!ks.length) { tb.innerHTML = '<tr><td colspan="4" class="help">El programa no llama herramientas (T).</td></tr>'; return; }
  tb.innerHTML = ks.map(k => {
    const h = S.simFull.herr[k] || { tipo: 'ext' }, o = S.over[k] || {};
    const conMed = h.tipo === 'broca' || h.tipo === 'ran' || h.tipo === 'rani';
    return '<tr><td><span class="cnc-dot" style="background:' + S.colorHerr[k] + '"></span><b>T' + String(k).padStart(2, '0') + '</b></td><td>' + esc(H[k].nombre || '—') + '</td>'
      + '<td><select data-k="' + k + '" class="cnc-tipo" title="' + (o.tipo ? 'Elegido a mano' : h.origen === 'comentario' ? 'Decidido por el comentario de la herramienta' : 'Decidido por la posición: dónde empieza a cortar') + '">' + Object.keys(CNC.TIPOS).map(t => '<option value="' + t + '"' + (t === h.tipo ? ' selected' : '') + '>' + CNC.TIPOS[t] + '</option>').join('') + '</select>'
      + '</td>'
      + '<td>' + (conMed ? '<input type="number" step="0.1" min="0.1" data-k="' + k + '" class="cnc-med" value="' + (h.med || '') + '" style="width:72px" title="' + (h.tipo === 'broca' ? 'Diámetro de la broca' : 'Ancho de la cuchilla') + '"> mm' : '<span class="help">—</span>') + '</td></tr>';
  }).join('');
  tb.querySelectorAll('.cnc-tipo').forEach(s => s.onchange = () => { const k = s.dataset.k, h = S.simFull.herr[k] || {}; S.over[k] = { tipo: s.value, med: s.value === 'broca' ? (h.tipo === 'broca' && h.med ? h.med : 6) : (s.value === 'ran' || s.value === 'rani') ? (h.med && (h.tipo === 'ran' || h.tipo === 'rani') ? h.med : 3) : null }; guardarLS('nexus.cnc.herr.' + clave(), S.over); resimular(true); });
  tb.querySelectorAll('.cnc-med').forEach(s => s.onchange = () => { const k = s.dataset.k, h = S.simFull.herr[k] || {}; S.over[k] = { tipo: h.tipo, med: parseFloat(s.value) || null }; guardarLS('nexus.cnc.herr.' + clave(), S.over); resimular(true); });
}
function pintarTiempo() {
  const e = q('cnc-tiempo'); if (!e) return;
  let corte = 0, rap = 0, otros = 0;
  S.res.movs.forEach(m => { if (m.t === 'r') rap += m.seg; else corte += m.seg; });
  S.res.eventos.forEach(v => otros += v.seg);
  e.innerHTML = '<div><b>' + CNC.fmtSeg(S.res.total) + '</b><span>Ciclo estimado</span></div><div><b>' + CNC.fmtSeg(corte) + '</b><span>Cortando</span></div><div><b>' + CNC.fmtSeg(rap) + '</b><span>Rápidos</span></div><div><b>' + CNC.fmtSeg(otros) + '</b><span>Cambios y esperas</span></div>'
    + '<div style="flex-basis:100%" class="help">Aproximado: rápidos a 15 m/min, 1,5 s por cambio de herramienta, sin aceleraciones.</div>';
}
function ponerBarra() {
  const b = S.barra || {};
  q('cnc-b-d').value = b.d; q('cnc-b-din').value = b.din || 0; q('cnc-b-largo').value = b.largo; q('cnc-b-cara').value = b.cara || 0; q('cnc-b-sal').value = b.saliente;
}
function leerBarra() {
  const v = k => parseFloat(q('cnc-b-' + k).value);
  const b = { d: v('d') || 50, din: Math.max(0, v('din') || 0), largo: v('largo') || 50, cara: v('cara') || 0, saliente: v('sal') || v('largo') || 50 };
  if (b.din >= b.d) b.din = 0;
  S.barra = b; guardarBarra(); resimular(true);
}
function guardarBarra() { guardarLS('nexus.cnc.barra.' + clave(), S.barra); }

/* ───── Reproducción ───── */
function jugar() { S.jugando = true; q('cnc-play').textContent = '⏸ Pausa'; S.ultimoFrame = performance.now(); requestAnimationFrame(cuadro); }
function parar() { S.jugando = false; if (q('cnc-play')) q('cnc-play').textContent = '▶ Simular'; }
function cuadro(ahora) {
  if (!S.jugando) return;
  const dt = Math.min(0.1, (ahora - S.ultimoFrame) / 1000); S.ultimoFrame = ahora;
  S.t += dt * S.vel;
  if (S.t >= S.res.total) { S.t = S.res.total; parar(); }
  dibujar(true);
  if (S.jugando) requestAnimationFrame(cuadro);
}
function finDeLinea(l) {
  let fin = null;
  S.res.movs.forEach(m => { if (m.linea === l) fin = m.ini + m.seg; });
  if (fin == null) S.res.eventos.forEach(v => { if (v.linea === l) fin = v.ini + v.seg; });
  return fin;
}
function irALinea(l, centrar) {
  if (!S.res) return;
  const f = finDeLinea(l);
  marcarLineaCur(l);
  if (f == null) return;
  parar(); S.t = f; dibujar(false, true);
}
function pasoLinea() {
  if (!S.res || !S.res.movs.length) return;
  parar();
  const M = S.res.movs; let k = M.findIndex(m => m.ini + m.seg > S.t + 1e-6);
  if (k < 0) { S.t = 0; k = 0; }
  const l = M[k].linea; let fin = M[k].ini + M[k].seg;
  for (let j = k; j < M.length && M[j].linea === l; j++) fin = M[j].ini + M[j].seg;
  S.t = fin; dibujar(true);
}
function movActual() {
  const M = S.res ? S.res.movs : []; if (!M.length) return null;
  let lo = 0, hi = M.length - 1;
  if (S.t <= M[0].ini) return { m: M[0], f: 0, k: 0 };
  while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (M[mid].ini < S.t - 1e-9) lo = mid; else hi = mid - 1; }
  const m = M[lo]; return { m: m, f: m.seg > 0 ? Math.min(1, Math.max(0, (S.t - m.ini) / m.seg)) : 1, k: lo };
}

/* ───── Dibujo ───── */
function ajustar(todo) {
  const cv = q('cnc-cv'); if (!cv || !S.barra) return;
  const W = cv.clientWidth || 600, H = cv.clientHeight || 400, b = S.barra;
  let z0 = b.cara - Math.max(b.largo, b.saliente) - 30, z1 = b.cara + 12, r1 = b.d / 2 + 16;
  if (todo && S.res) S.res.movs.forEach(m => { z0 = Math.min(z0, m.z0, m.z1); z1 = Math.max(z1, m.z0, m.z1); r1 = Math.max(r1, Math.abs(m.x0) / 2, Math.abs(m.x1) / 2); });
  const esc_ = Math.min((W - 40) / (z1 - z0), (H - 40) / (2 * r1));
  S.vista = { s: esc_, cz: (z0 + z1) / 2, cr: 0 };
}
function zoom(f, px, py) {
  const cv = q('cnc-cv'); if (!S.vista) return;
  const W = cv.clientWidth, H = cv.clientHeight;
  if (px == null) { px = W / 2; py = H / 2; }
  const wz = S.vista.cz + (px - W / 2) / S.vista.s, wr = S.vista.cr - (py - H / 2) / S.vista.s;
  S.vista.s = Math.max(0.05, Math.min(400, S.vista.s * f));
  S.vista.cz = wz - (px - W / 2) / S.vista.s; S.vista.cr = wr + (py - H / 2) / S.vista.s;
  dibujar();
}
function eventosCanvas() {
  const cv = q('cnc-cv'); let arr = null;
  cv.addEventListener('wheel', e => { e.preventDefault(); const r = cv.getBoundingClientRect(); zoom(e.deltaY < 0 ? 1.18 : 1 / 1.18, e.clientX - r.left, e.clientY - r.top); }, { passive: false });
  cv.addEventListener('pointerdown', e => { arr = { x: e.clientX, y: e.clientY, cz: S.vista && S.vista.cz, cr: S.vista && S.vista.cr, mov: false }; cv.setPointerCapture(e.pointerId); });
  cv.addEventListener('pointermove', e => {
    if (!arr || !S.vista) return;
    const dx = e.clientX - arr.x, dy = e.clientY - arr.y;
    if (Math.abs(dx) + Math.abs(dy) > 4) { arr.mov = true; cv.classList.add('arr'); }
    if (arr.mov) { S.vista.cz = arr.cz - dx / S.vista.s; S.vista.cr = arr.cr + dy / S.vista.s; dibujar(); }
  });
  cv.addEventListener('pointerup', e => {
    cv.classList.remove('arr');
    if (arr && !arr.mov) { const r = cv.getBoundingClientRect(); clicCanvas(e.clientX - r.left, e.clientY - r.top); }
    arr = null;
  });
}
function clicCanvas(px, py) {
  if (!S.res || !S.vista) return;
  const cv = q('cnc-cv'), W = cv.clientWidth, H = cv.clientHeight, v = S.vista;
  const sx = z => W / 2 + (z - v.cz) * v.s, sy = r => H / 2 - (r - v.cr) * v.s;
  let mejor = null, dmin = 9;
  S.res.movs.forEach(m => {
    const ax = sx(m.z0), ay = sy(m.x0 / 2), bx = sx(m.z1), by = sy(m.x1 / 2);
    const dx = bx - ax, dy = by - ay, L2 = dx * dx + dy * dy;
    const t = L2 ? Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / L2)) : 0;
    const d = Math.hypot(px - (ax + dx * t), py - (ay + dy * t));
    if (d < dmin) { dmin = d; mejor = m; }
  });
  if (mejor) { seleccionarLinea(mejor.linea); irALinea(mejor.linea, true); }
}
function colores() {
  const cs = getComputedStyle(document.documentElement), g = n => cs.getPropertyValue(n).trim();
  const oscuro = matchMedia('(prefers-color-scheme: dark)').matches;
  return { fondo: g('--sunk') || '#E3E8ED', linea: g('--line') || '#CDD5DD', fg: g('--fg') || '#17222C', muted: g('--muted') || '#5A6875', bad: g('--bad') || '#B23A2E', accent: g('--accent') || '#1F5F8B',
    metal: oscuro ? '#7D8B97' : '#A9B4BE', metal2: oscuro ? '#5B6874' : '#7F8C98', metalBorde: oscuro ? '#C9D3DC' : '#46525D', fantasma: oscuro ? 'rgba(201,211,220,.10)' : 'rgba(70,82,93,.10)',
    plato: oscuro ? '#38444F' : '#5C6873', rapido: oscuro ? '#F0B35A' : '#C77700', rosca: '#9467BD', oscuro: oscuro };
}
function dibujar(seguir, sinScroll) {
  const cv = q('cnc-cv'); if (!cv) return;
  const W = cv.clientWidth, H = cv.clientHeight; if (!W || !H) return;
  const dpr = window.devicePixelRatio || 1;
  if (cv.width !== Math.round(W * dpr) || cv.height !== Math.round(H * dpr)) { cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); }
  const c = cv.getContext('2d'); c.setTransform(dpr, 0, 0, dpr, 0, 0);
  const C = colores();
  c.fillStyle = C.fondo; c.fillRect(0, 0, W, H);
  const rng = q('cnc-rango'), tt = q('cnc-t');
  if (!S.res || !S.barra || !S.texto.trim()) {
    c.fillStyle = C.muted; c.font = '14px ' + getComputedStyle(document.body).fontFamily; c.textAlign = 'center';
    c.fillText('Abrí un programa para ver la simulación', W / 2, H / 2);
    if (tt) tt.textContent = '0:00 / 0:00'; q('cnc-lect').hidden = true; return;
  }
  if (!S.vista) ajustar(false);
  const v = S.vista, b = S.barra;
  const sx = z => W / 2 + (z - v.cz) * v.s, sy = r => H / 2 - (r - v.cr) * v.s;
  // cuadrícula
  const pasoG = [1, 2, 5, 10, 20, 50, 100, 200].find(p => p * v.s >= 40) || 500;
  c.strokeStyle = C.linea; c.lineWidth = 1; c.globalAlpha = 0.5; c.beginPath();
  const zA = v.cz - W / 2 / v.s, zB = v.cz + W / 2 / v.s, rA = v.cr - H / 2 / v.s, rB = v.cr + H / 2 / v.s;
  for (let z = Math.ceil(zA / pasoG) * pasoG; z <= zB; z += pasoG) { c.moveTo(Math.round(sx(z)) + .5, 0); c.lineTo(Math.round(sx(z)) + .5, H); }
  for (let r = Math.ceil(rA / pasoG) * pasoG; r <= rB; r += pasoG) { c.moveTo(0, Math.round(sy(r)) + .5); c.lineTo(W, Math.round(sy(r)) + .5); }
  c.stroke(); c.globalAlpha = 1;
  // material
  S.simAnim.hasta(S.t);
  const M = S.simAnim.mat;
  c.fillStyle = C.fantasma; c.fillRect(sx(M.z0), sy(b.d / 2), (M.z1 - M.z0) * v.s, (b.d / 2 - (b.din || 0) / 2) * v.s);
  c.fillRect(sx(M.z0), sy(-(b.din || 0) / 2), (M.z1 - M.z0) * v.s, (b.d / 2 - (b.din || 0) / 2) * v.s);
  c.setLineDash([4, 4]); c.strokeStyle = C.muted; c.lineWidth = 1;
  c.strokeRect(sx(M.z0), sy(b.d / 2), (M.z1 - M.z0) * v.s, b.d * v.s); c.setLineDash([]);
  const grad = c.createLinearGradient(0, sy(b.d / 2), 0, sy(-b.d / 2));
  grad.addColorStop(0, C.metal2); grad.addColorStop(0.25, C.metal); grad.addColorStop(0.5, C.metal2); grad.addColorStop(0.75, C.metal); grad.addColorStop(1, C.metal2);
  const paso = Math.max(1, Math.floor(0.6 / (M.dz * v.s)));   // columnas por píxel
  [1, -1].forEach(lado => {
    let ini = -1;
    const cerrar = (a, z) => {
      c.beginPath();
      for (let k = a; k < z; k += paso) c.lineTo(sx(M.z0 + k * M.dz), sy(lado * M.fuera[k]));
      c.lineTo(sx(M.z0 + z * M.dz), sy(lado * M.fuera[z - 1]));
      c.lineTo(sx(M.z0 + z * M.dz), sy(lado * M.dentro[z - 1]));
      for (let k = z - 1; k >= a; k -= paso) c.lineTo(sx(M.z0 + k * M.dz), sy(lado * M.dentro[k]));
      c.lineTo(sx(M.z0 + a * M.dz), sy(lado * M.dentro[a]));
      c.closePath(); c.fillStyle = grad; c.fill(); c.strokeStyle = C.metalBorde; c.lineWidth = 1.2; c.stroke();
    };
    for (let k = 0; k <= M.n; k++) {
      const lleno = k < M.n && M.fuera[k] > M.dentro[k] + 1e-4;
      if (lleno && ini < 0) ini = k;
      if (!lleno && ini >= 0) { cerrar(ini, k); ini = -1; }
    }
  });
  // roscas alcanzadas
  S.res.roscas.forEach(r => {
    const m0 = S.res.movs.find(m => m.linea === r.linea && m.t === 'h'); if (!m0 || m0.ini > S.t) return;
    const vueltas = (S.res.giros || []).filter(g => g.ini > m0.ini && g.ini <= S.t).length;
    const esp = z => vueltas % 2 ? 2 * b.cara - b.largo - z : z;
    const p = Math.abs(r.paso) || 1, z0 = Math.min(esp(r.z0), esp(r.z1)), z1 = Math.max(esp(r.z0), esp(r.z1));
    const hondo = Math.abs(r.x - (r.xc || r.x)) / 2 || p * 0.6;
    c.fillStyle = C.fondo;
    [1, -1].forEach(lado => {
      c.beginPath();
      for (let z = z1; z > z0 + 1e-6; z -= p) {
        const za = Math.max(z0, z - p), zm = (z + za) / 2;
        if (zm < M.z0 || zm > M.z1) continue;
        const e = M.en(zm); if (e.fu <= e.de) continue;
        const rsup = r.ext ? e.fu : e.de, rinf = r.ext ? Math.max(e.de, r.x / 2) : Math.min(e.fu, r.x / 2);
        if (r.ext && rinf >= rsup) continue;
        c.moveTo(sx(z), sy(lado * rsup)); c.lineTo(sx(zm), sy(lado * (r.ext ? Math.max(rinf, rsup - hondo) : Math.min(rinf, rsup + hondo)))); c.lineTo(sx(za), sy(lado * rsup)); c.closePath();
      }
      c.fill(); c.strokeStyle = C.metalBorde; c.lineWidth = 0.8; c.stroke();
    });
  });
  // plato y mordazas
  const zJ = b.cara - b.saliente, rJ = b.d / 2;
  c.fillStyle = C.plato;
  [1, -1].forEach(lado => {
    const y0 = sy(lado * (rJ + 14)), y1 = sy(lado * rJ);
    c.fillRect(sx(zJ - 22), Math.min(y0, y1), 22 * v.s, Math.abs(y1 - y0));
  });
  c.globalAlpha = 0.85; c.fillRect(sx(zJ - 60), sy(rJ + 40), 38 * v.s, (2 * rJ + 80) * v.s); c.globalAlpha = 1;
  // eje
  c.strokeStyle = C.muted; c.setLineDash([14, 4, 3, 4]); c.lineWidth = 1; c.beginPath(); c.moveTo(0, sy(0)); c.lineTo(W, sy(0)); c.stroke(); c.setLineDash([]);
  // recorrido: futuro tenue, hecho en color
  const act = movActual(), Ms = S.res.movs;
  c.lineWidth = 1; c.strokeStyle = C.muted; c.globalAlpha = 0.28; c.beginPath();
  for (let k = act ? act.k : 0; k < Ms.length; k++) { const m = Ms[k]; c.moveTo(sx(m.z0), sy(m.x0 / 2)); c.lineTo(sx(m.z1), sy(m.x1 / 2)); }
  c.stroke(); c.globalAlpha = 1;
  const trazar = (filtro, color, ancho, dash) => {
    c.beginPath(); c.strokeStyle = color; c.lineWidth = ancho; c.setLineDash(dash || []);
    let px = null, py = null;
    const lim = act ? act.k : -1;
    for (let k = 0; k <= lim; k++) {
      const m = Ms[k]; if (!filtro(m)) { px = null; continue; }
      const f = k === lim ? act.f : 1;
      const ax = sx(m.z0), ay = sy(m.x0 / 2), bx = sx(m.z0 + (m.z1 - m.z0) * f), by = sy((m.x0 + (m.x1 - m.x0) * f) / 2);
      if (px !== ax || py !== ay) c.moveTo(ax, ay);
      c.lineTo(bx, by); px = bx; py = by;
    }
    c.stroke(); c.setLineDash([]);
  };
  trazar(m => m.t === 'r', C.rapido, 1, [5, 4]);
  Object.keys(S.colorHerr).forEach(k => trazar(m => m.t === 'f' && String(m.herr) === k, S.colorHerr[k], 1.6));
  trazar(m => m.t === 'f' && !S.colorHerr[m.herr], C.accent, 1.6);
  trazar(m => m.t === 'h', C.rosca, 1.8);
  // choques ya ocurridos
  (S.simFull.choques || []).forEach(ch => {
    const m = Ms.find(x => x.linea === ch.linea); if (!m || m.ini > S.t) return;
    const X = sx(ch.z), Y = sy(ch.x / 2);
    c.strokeStyle = C.bad; c.lineWidth = 2.2; c.beginPath(); c.arc(X, Y, 8, 0, 7); c.moveTo(X - 4, Y - 4); c.lineTo(X + 4, Y + 4); c.moveTo(X + 4, Y - 4); c.lineTo(X - 4, Y + 4); c.stroke();
  });
  // herramienta
  let lect = '';
  if (act) {
    const m = act.m, f = act.f, x = m.x0 + (m.x1 - m.x0) * f, z = m.z0 + (m.z1 - m.z0) * f;
    const h = S.simFull.herr[m.herr] || { tipo: 'ext' }, X = sx(z), Y = sy(x / 2), col = S.colorHerr[m.herr] || C.accent;
    dibujarHerr(c, h, X, Y, v.s, col, x < 0);
    const cambio = S.res.movs[0] && S.t < S.res.movs[0].ini;
    lect = '<b>X</b> ' + x.toFixed(3) + '  <b>Z</b> ' + z.toFixed(3) + '<br>T' + String(m.herr).padStart(2, '0') + ' · ' + (m.t === 'r' ? 'Rápido' : m.t === 'h' ? 'Roscando' : 'Cortando') + ' · línea ' + (m.linea + 1);
    if (!cambio) marcarLineaCur(m.linea);
    if (seguir && !sinScroll && S.jugando) verLinea(m.linea, false);
  }
  const ld = q('cnc-lect'); ld.hidden = !lect; ld.innerHTML = lect + '<br><span style="color:var(--muted)">cuadro ' + pasoG + ' mm</span>';
  if (rng) rng.value = Math.round(1000 * S.t / (S.res.total || 1));
  if (tt) tt.textContent = CNC.fmtSeg(S.t) + ' / ' + CNC.fmtSeg(S.res.total);
}
function dibujarHerr(c, h, X, Y, s, col, neg) {
  const k = Math.max(0.6, Math.min(2.2, s / 6)), dir = neg ? 1 : -1;  // dir: hacia dónde queda el cuerpo (arriba en la pantalla = -Y)
  c.save(); c.translate(X, Y);
  c.fillStyle = col; c.strokeStyle = '#111'; c.lineWidth = 1; c.globalAlpha = 0.9;
  c.beginPath();
  if (h.tipo === 'broca') {
    const r = (h.med || 6) / 2 * s;
    c.moveTo(0, 0); c.lineTo(Math.max(6, r * 0.6), -r); c.lineTo(Math.max(6, r * 0.6) + 60 * k, -r); c.lineTo(Math.max(6, r * 0.6) + 60 * k, r); c.lineTo(Math.max(6, r * 0.6), r); c.closePath();
  } else if (h.tipo === 'ran' || h.tipo === 'rani') {
    const w = Math.max(3, (h.med || 3) * s), up = h.tipo === 'ran' ? dir : -dir;
    c.rect(0, 0, w, up * 34 * k);
  } else if (h.tipo === 'nada') {
    c.arc(0, 0, 6 * k, 0, 7);
  } else {
    const up = h.tipo === 'int' ? -dir : dir;
    c.moveTo(0, 0); c.lineTo(16 * k, up * 4 * k); c.lineTo(18 * k, up * 14 * k); c.lineTo(5 * k, up * 16 * k); c.closePath();
    c.fill(); c.stroke(); c.beginPath();
    c.globalAlpha = 0.35; c.rect(6 * k, up * 12 * k, 18 * k, up * 40 * k);
  }
  c.fill(); c.globalAlpha = 1; c.stroke();
  c.fillStyle = '#fff'; c.beginPath(); c.arc(0, 0, 2.2, 0, 7); c.fill(); c.strokeStyle = col; c.stroke();
  c.restore();
}

window.CNCUI = {
  abrir: function (sec) { montar(sec); if (!q('cnc-maq').options.length) cargarMaquinas(); setTimeout(dibujar, 0); },
  _S: S
};
})();

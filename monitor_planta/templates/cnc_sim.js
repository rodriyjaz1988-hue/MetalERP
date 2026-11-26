/* Nexus - Editor y simulación de programas CNC de torno (Fanuc, sistema A).
   Parte 1: intérprete (sin pantalla, se puede probar con node).
   Parte 2: material (barra en columnas) y herramientas.
   Parte 3: pantalla (editor + dibujo), solo en el navegador. */
'use strict';
(function (raiz) {
const CNC = {};

/* ───────────── 1. Lectura de bloques ───────────── */
function leerBloque(raw, i) {
  const b = { i: i, raw: raw, w: {}, g: [], m: [], com: '', skip: false, macro: false, err: null, sinPunto: [], vacio: false };
  let s = String(raw || '').replace(/\(([^)]*)\)?/g, function (m, c) { b.com += (b.com ? ' ' : '') + String(c || '').trim(); return ' '; });
  s = s.replace(/\s+/g, '').toUpperCase();
  if (s.charAt(0) === '/') { b.skip = true; s = s.slice(1); }
  if (!s || s === '%') { b.vacio = true; return b; }
  if (/[#\[\]]|IF|GOTO|WHILE|END\d/.test(s)) { b.macro = true; return b; }
  const re = /([A-Z])([+-]?(?:\d+\.?\d*|\.\d+))?/y;
  let pos = 0;
  while (pos < s.length) {
    re.lastIndex = pos;
    const m = re.exec(s);
    if (!m) { b.err = 'No se entiende "' + s.slice(pos, pos + 12) + '"'; break; }
    pos = re.lastIndex;
    const L = m[1], txt = m[2];
    if (txt === undefined) { b.err = 'Letra ' + L + ' sin número'; continue; }
    const v = parseFloat(txt);
    if (L === 'G') b.g.push(Math.round(v * 10) / 10);
    else if (L === 'M') b.m.push(Math.round(v));
    else {
      if (b.w[L] !== undefined && !b.err) b.err = 'La letra ' + L + ' está dos veces';
      b.w[L] = v;
      if (txt.indexOf('.') < 0 && 'XZUWRIKF'.indexOf(L) >= 0 && v !== 0) b.sinPunto.push(L + txt);
    }
  }
  return b;
}
CNC.leerBloque = leerBloque;

/* ───────────── 2. Intérprete ───────────── */
const OPC_DEF = { homeX: 250, homeZ: 100, rapido: 15000, rpmMax: 4000, saltarBarra: false, cambioSeg: 1.5 };

function interpretar(texto, opc) {
  opc = Object.assign({}, OPC_DEF, opc || {});
  const lineas = String(texto || '').replace(/\r/g, '').split('\n');
  const B = lineas.map(leerBloque);
  const avisos = [], vistos = {};
  function aviso(i, nivel, msg) {
    const k = i + '|' + msg; if (vistos[k]) return; vistos[k] = 1;
    avisos.push({ linea: i, nivel: nivel, msg: msg });
  }
  const movs = [];          // {t:'r'|'f'|'h', x0,z0,x1,z1 (X en diámetro), linea, herr, f, seg}
  const eventos = [];       // pausas, cambios de herramienta: {linea, seg, tipo}
  const herramientas = {};  // num -> {num, nombre, lineas:[]}
  const roscas = [], giros = [];
  const st = { x: opc.homeX, z: opc.homeZ, mov: 0, F: 0, feedRev: true, css: false, S: 0, smax: 0,
               husillo: false, retRosca: false, herr: 0, ciclo: null, vivo: false, comp: false, fin: false };
  let tiempo = 0;
  const g71 = {}, g72 = {}, g73 = {}, g74 = {}, g75 = {}, g76 = {};

  function rpm(d) {
    let lim = st.smax || opc.rpmMax;
    if (!st.css) return Math.min(st.S || 0, opc.rpmMax);
    if (!d || d < 0.5) return lim;
    return Math.min(lim, st.S * 1000 / (Math.PI * Math.abs(d)));
  }
  function agregar(t, x1, z1, i, F) {
    const x0 = st.x, z0 = st.z;
    if (Math.abs(x1 - x0) < 1e-6 && Math.abs(z1 - z0) < 1e-6) return;
    const dr = (x1 - x0) / 2, dz = z1 - z0, largo = Math.hypot(dr, dz);
    let seg;
    if (t === 'r') seg = Math.max(Math.abs(dr), Math.abs(dz)) / opc.rapido * 60;
    else {
      const f = F == null ? st.F : F;
      const n = rpm((x0 + x1) / 2);
      let vel = (t === 'h' || st.feedRev) ? f * n : f;
      if (!(vel > 0)) { vel = 100; if (!f) aviso(i, 'warn', 'Avance sin F: no se sabe a qué velocidad corta'); }
      seg = largo / vel * 60;
    }
    movs.push({ t: t, x0: x0, z0: z0, x1: x1, z1: z1, linea: i, herr: st.herr, seg: seg, ini: tiempo, hus: st.husillo, ret: st.retRosca });
    tiempo += seg; st.x = x1; st.z = z1;
  }
  function arco(x1, z1, w, i, cw, F, t) {
    // plano (z, r) con r = X/2; G2 horario mirando con Z a la derecha y X arriba
    const z0 = st.z, r0 = st.x / 2, r1 = x1 / 2;
    let cz, cr;
    if (w.R !== undefined) {
      const R = w.R, dz = z1 - z0, dr = r1 - r0, d = Math.hypot(dz, dr);
      if (d < 1e-9) { aviso(i, 'warn', 'Arco con R y mismo punto de inicio y fin'); return; }
      let h2 = R * R - d * d / 4;
      if (h2 < -1e-3) aviso(i, 'bad', 'El radio R es chico para llegar a ese punto (R ' + R + ', distancia ' + d.toFixed(3) + ')');
      const h = Math.sqrt(Math.max(0, h2));
      let s = (cw ? 1 : -1) * (R < 0 ? -1 : 1);
      cz = (z0 + z1) / 2 + s * h * dr / d; cr = (r0 + r1) / 2 - s * h * dz / d;
    } else {
      cz = z0 + (w.K || 0); cr = r0 + (w.I || 0);
      const e = Math.abs(Math.hypot(z1 - cz, r1 - cr) - Math.hypot(z0 - cz, r0 - cr));
      if (e > 0.02) aviso(i, 'bad', 'Arco I/K: el punto final no queda a la misma distancia del centro (' + e.toFixed(3) + ' mm)');
    }
    const rad = Math.hypot(z0 - cz, r0 - cr);
    let a0 = Math.atan2(r0 - cr, z0 - cz), a1 = Math.atan2(r1 - cr, z1 - cz), sw = a1 - a0;
    if (cw) { if (sw >= -1e-9) sw -= 2 * Math.PI; } else { if (sw <= 1e-9) sw += 2 * Math.PI; }
    const n = Math.max(2, Math.ceil(Math.abs(sw) * rad / 0.25), Math.ceil(Math.abs(sw) / 0.06));
    for (let k = 1; k <= n; k++) {
      const a = a0 + sw * k / n;
      const zz = k === n ? z1 : cz + rad * Math.cos(a), rr = k === n ? r1 : cr + rad * Math.sin(a);
      agregar(t || 'f', rr * 2, zz, i, F);
    }
  }
  function destino(b, inc) {
    const w = b.w;
    let x = w.X !== undefined ? (inc ? st.x + w.X : w.X) : st.x + (w.U || 0);
    let z = w.Z !== undefined ? (inc ? st.z + w.Z : w.Z) : st.z + (w.W || 0);
    if (w.A !== undefined && b.g.indexOf(76) < 0) {
      const a = w.A * Math.PI / 180, cx = Math.cos(a), sx = Math.sin(a);
      const hayX = w.X !== undefined || w.U !== undefined, hayZ = w.Z !== undefined || w.W !== undefined;
      if (hayX && !hayZ && Math.abs(sx) > 1e-6) z = st.z + ((x - st.x) / 2) * cx / sx;
      else if (hayZ && !hayX && Math.abs(cx) > 1e-6) x = st.x + 2 * (z - st.z) * sx / cx;
    }
    return { x: x, z: z, hay: w.X !== undefined || w.Z !== undefined || w.U !== undefined || w.W !== undefined };
  }
  function buscarN(n, desde) {
    for (let k = desde; k < B.length; k++) if (B[k].w.N === n) return k;
    for (let k = 0; k < desde; k++) if (B[k].w.N === n) return k;
    return -1;
  }
  // Contorno de un ciclo (bloques P..Q): puntos desde el punto de inicio
  function contorno(i, ns, nf) {
    const a = buscarN(ns, i + 1), b = a < 0 ? -1 : buscarN(nf, a);
    if (a < 0 || b < 0) { aviso(i, 'bad', 'No encuentro los bloques N' + ns + ' a N' + nf + ' del ciclo'); return null; }
    const pts = [{ x: st.x, z: st.z, t: 'r', linea: i }];
    let x = st.x, z = st.z, mov = st.mov === 0 ? 0 : 1, F = null;
    for (let k = a; k <= b; k++) {
      const bl = B[k];
      if (bl.vacio || bl.macro) continue;
      bl.g.forEach(function (g) { if (g === 0 || g === 1 || g === 2 || g === 3) mov = g; });
      const w = bl.w;
      if (w.F !== undefined) F = w.F;
      const nx = w.X !== undefined ? w.X : x + (w.U || 0), nz = w.Z !== undefined ? w.Z : z + (w.W || 0);
      if (nx === x && nz === z) continue;
      if (mov === 2 || mov === 3) {
        // discretizar el arco con un estado temporal
        const sx = st.x, sz = st.z, nAntes = movs.length, tAntes = tiempo;
        st.x = x; st.z = z;
        const husAntes = st.husillo; st.husillo = true;
        arco(nx, nz, w, k, mov === 2, F, 'f');
        st.husillo = husAntes;
        const nuevos = movs.splice(nAntes);
        tiempo = tAntes; st.x = sx; st.z = sz;
        nuevos.forEach(function (m) { pts.push({ x: m.x1, z: m.z1, t: 'f', linea: k, F: F }); });
      } else pts.push({ x: nx, z: nz, t: mov === 0 ? 'r' : 'f', linea: k, F: F });
      x = nx; z = nz;
    }
    return { pts: pts, fin: b };
  }
  function recorrer(pts, dx, dz, i, F, desde) {
    for (let k = desde || 1; k < pts.length; k++) {
      const p = pts[k];
      agregar(p.t === 'r' ? 'r' : 'f', p.x + dx, p.z + dz, p.linea != null ? p.linea : i, p.F != null ? p.F : F);
    }
  }
  // Intersección de una recta (Z = cte o X = cte) con el contorno
  function cortes(pts, eje, val) {
    const res = [];
    for (let k = 1; k < pts.length; k++) {
      const a = pts[k - 1], b = pts[k];
      const va = eje === 'x' ? a.x : a.z, vb = eje === 'x' ? b.x : b.z;
      if ((va - val) * (vb - val) <= 0 && va !== vb) {
        const t = (val - va) / (vb - va);
        res.push(eje === 'x' ? a.z + (b.z - a.z) * t : a.x + (b.x - a.x) * t);
      }
    }
    return res;
  }
  function cicloG71(i, b) {
    const w = b.w;
    if (w.P === undefined) { g71.d = w.U !== undefined ? w.U : (w.D !== undefined ? w.D / 1000 : 1); g71.e = w.R !== undefined ? w.R : 0.5; return null; }
    if (w.D !== undefined) g71.d = w.D / 1000;
    const d = g71.d || 1, e = g71.e == null ? 0.5 : g71.e, du = w.U || 0, dw = w.W || 0;
    if (w.F !== undefined) st.F = w.F;
    const sx = st.x, sz = st.z, c = contorno(i, w.P, w.Q);
    if (!c) return null;
    const pts = c.pts.map(function (p, k) { return k === 0 ? p : Object.assign({}, p, { x: p.x + du, z: p.z + dw }); });
    const prof = pts.slice(1);
    if (prof.length < 2) { aviso(i, 'warn', 'Contorno del G71 vacío'); return c.fin; }
    const ext = sx >= prof[0].x;
    const xs = prof.map(function (p) { return p.x; });
    const meta = ext ? Math.min.apply(null, xs) : Math.max.apply(null, xs);
    const zFin = Math.min.apply(null, prof.map(function (p) { return p.z; }));
    let nivel = sx, guard = 0;
    while (guard++ < 2000) {
      nivel += ext ? -2 * d : 2 * d;
      if (ext ? nivel <= meta + 1e-6 : nivel >= meta - 1e-6) break;
      const zs = cortes(prof, 'z', nivel).filter(function (z) { return z <= sz + 1e-6; });
      let zc = zs.length ? Math.max.apply(null, zs) : zFin;
      agregar('r', nivel, sz, i);
      agregar('f', nivel, zc, i);
      agregar('f', nivel + (ext ? 2 * e : -2 * e), zc + e, i);
      agregar('r', st.x, sz, i);
    }
    agregar('r', prof[0].x, sz, i);
    recorrer(pts, 0, 0, i, st.F, 1);
    agregar('r', st.x, sz, i); agregar('r', sx, sz, i);
    return c.fin;
  }
  function cicloG72(i, b) {
    const w = b.w;
    if (w.P === undefined) { g72.d = w.W !== undefined ? w.W : (w.D !== undefined ? w.D / 1000 : 1); g72.e = w.R !== undefined ? w.R : 0.5; return null; }
    const d = g72.d || 1, e = g72.e == null ? 0.5 : g72.e, du = w.U || 0, dw = w.W || 0;
    if (w.F !== undefined) st.F = w.F;
    const sx = st.x, sz = st.z, c = contorno(i, w.P, w.Q);
    if (!c) return null;
    const pts = c.pts.map(function (p, k) { return k === 0 ? p : Object.assign({}, p, { x: p.x + du, z: p.z + dw }); });
    const prof = pts.slice(1);
    if (prof.length < 2) { aviso(i, 'warn', 'Contorno del G72 vacío'); return c.fin; }
    const ext = sx >= Math.max.apply(null, prof.map(function (p) { return p.x; })) - 1e-6;
    const zs_ = prof.map(function (p) { return p.z; });
    const meta = Math.min.apply(null, zs_);
    const xsP = prof.map(function (p) { return p.x; });
    const xFin = ext ? Math.min.apply(null, xsP) : Math.max.apply(null, xsP);
    let nivel = sz, guard = 0;
    while (guard++ < 2000) {
      nivel -= d;
      if (nivel <= meta + 1e-6) break;
      const xs = cortes(prof, 'x', nivel).filter(function (x) { return ext ? x <= sx + 1e-6 : x >= sx - 1e-6; });
      const xc = xs.length ? (ext ? Math.max.apply(null, xs) : Math.min.apply(null, xs)) : xFin;
      agregar('r', sx, nivel, i);
      agregar('f', xc, nivel, i);
      agregar('f', xc + (ext ? 2 * e : -2 * e), nivel + e, i);
      agregar('r', sx, st.z, i);
    }
    agregar('r', sx, prof[0].z);
    recorrer(pts, 0, 0, i, st.F, 1);
    agregar('r', sx, st.z, i); agregar('r', sx, sz, i);
    return c.fin;
  }
  function cicloG73(i, b) {
    const w = b.w;
    if (w.P === undefined) { g73.i = w.U || 0; g73.k = w.W || 0; g73.d = Math.max(1, Math.round(w.R || 1)); return null; }
    if (w.F !== undefined) st.F = w.F;
    const sx = st.x, sz = st.z, c = contorno(i, w.P, w.Q);
    if (!c) return null;
    const n = g73.d || 1, du = w.U || 0, dw = w.W || 0;
    for (let j = 1; j <= n; j++) {
      const f = n === 1 ? 0 : (n - j) / (n - 1);
      const ox = 2 * (g73.i || 0) * f + du, oz = (g73.k || 0) * f + dw;
      agregar('r', c.pts[1].x + ox, c.pts[1].z + oz, i);
      recorrer(c.pts, ox, oz, i, st.F, 2);
      agregar('r', sx, sz, i);
    }
    return c.fin;
  }
  function cicloG70(i, b) {
    const w = b.w, sx = st.x, sz = st.z, c = contorno(i, w.P, w.Q);
    if (!c) return;
    recorrer(c.pts, 0, 0, i, st.F, 1);
    agregar('r', st.x, sz, i); agregar('r', sx, sz, i);
  }
  function micras(v) { return v == null ? null : (Math.abs(v) >= 1 && Number.isInteger(v) ? v / 1000 : v); }
  function cicloG74(i, b) {
    const w = b.w;
    if (w.Q === undefined && w.Z === undefined && w.W === undefined) { g74.e = w.R || 0.5; return; }
    const sx = st.x, sz = st.z, t = destino(b), e = g74.e || 0.5;
    const dk = micras(w.Q) || Math.abs(t.z - sz), di = micras(w.P) || 0;
    const xs = [];
    if (Math.abs(t.x - sx) < 1e-6 || !di) xs.push(t.x);
    else { const paso = 2 * di * Math.sign(t.x - sx); for (let x = sx; Math.sign(t.x - x) === Math.sign(paso) || Math.abs(t.x - x) < 1e-6; x += paso) { xs.push(Math.abs(t.x - x) < Math.abs(paso) ? t.x : x); if (Math.abs(t.x - x) < 1e-6) break; } }
    xs.forEach(function (x) {
      agregar('r', x, sz, i);
      let z = sz;
      while (z > t.z + 1e-6) { const nz = Math.max(t.z, z - dk); agregar('f', x, nz, i); if (nz > t.z + 1e-6) { agregar('r', x, nz + e, i); agregar('r', x, nz, i); } z = nz; }
      agregar('r', x, sz, i);
    });
    agregar('r', sx, sz, i);
  }
  function cicloG75(i, b) {
    const w = b.w;
    if (w.P === undefined && w.X === undefined && w.U === undefined) { g75.e = w.R || 0.5; return; }
    const sx = st.x, sz = st.z, t = destino(b), e = g75.e || 0.5;
    const di = micras(w.P) || Math.abs(t.x - sx) / 2, dk = micras(w.Q) || 0;
    const zz = [];
    if (Math.abs(t.z - sz) < 1e-6 || !dk) zz.push(t.z);
    else { const paso = dk * Math.sign(t.z - sz); let z = sz; for (let n = 0; n < 500; n++) { zz.push(z); if (Math.abs(t.z - z) < 1e-6) break; z = Math.abs(t.z - z) < Math.abs(paso) ? t.z : z + paso; } }
    const dir = Math.sign(t.x - sx) || -1;
    zz.forEach(function (z) {
      agregar('r', sx, z, i);
      let x = sx;
      while ((t.x - x) * dir > 1e-6) { let nx = x + dir * 2 * di; if ((t.x - nx) * dir < 0) nx = t.x; agregar('f', nx, z, i); if ((t.x - nx) * dir > 1e-6) { agregar('r', nx - dir * 2 * e, z, i); agregar('r', nx, z, i); } x = nx; }
      agregar('r', sx, z, i);
    });
    agregar('r', sx, sz, i);
  }
  function cicloG76(i, b) {
    const w = b.w;
    if (w.X === undefined && w.U === undefined && w.Z === undefined && w.W === undefined) {
      if (w.P !== undefined) { const p = Math.round(w.P); g76.m = Math.floor(p / 10000) || 1; }
      g76.qmin = micras(w.Q) || 0.05; g76.r = w.R || 0; return;
    }
    const sx = st.x, sz = st.z, t = destino(b), F = w.F !== undefined ? w.F : st.F;
    const k = micras(w.P) || 1, q = micras(w.Q) || k / 4, ti = w.R || 0;
    const ext = sx > t.x;
    const fin = g76.r || 0, prof = [];
    let n = 1, ultimo = 0;
    while (n < 300) {
      let dd = q * Math.sqrt(n);
      if (dd - ultimo < (g76.qmin || 0)) dd = ultimo + (g76.qmin || 0);
      if (dd >= k - fin) break;
      prof.push(dd); ultimo = dd; n++;
    }
    prof.push(k - fin);
    for (let j = 0; j < (g76.m || 1); j++) prof.push(k);
    prof.forEach(function (dd) {
      const xc = t.x + (ext ? 2 : -2) * (k - dd);
      agregar('r', xc + 2 * ti, sz, i);
      agregar('h', xc, t.z, i, F);
      st.retRosca = true; agregar('r', sx, t.z, i); agregar('r', sx, sz, i); st.retRosca = false;
    });
    roscas.push({ z0: sz, z1: t.z, x: t.x, xc: t.x + (ext ? 2 * k : -2 * k), paso: F, ext: ext, linea: i });
  }
  function cicloCaja(tipo, i, b) {
    const w = b.w, sx = st.x, sz = st.z, t = destino(b), R = w.R || 0;
    if (w.F !== undefined) st.F = w.F;
    if (tipo === 90) {
      agregar('r', t.x + 2 * R, sz, i); agregar('f', t.x, t.z, i); agregar('f', sx, t.z, i); agregar('r', sx, sz, i);
    } else if (tipo === 94) {
      agregar('r', sx, t.z + R, i); agregar('f', t.x, t.z, i); agregar('f', t.x, sz, i); agregar('r', sx, sz, i);
    } else {
      const F = w.F !== undefined ? w.F : st.F;
      agregar('r', t.x + 2 * R, sz, i); agregar('h', t.x, t.z, i, F); st.retRosca = true; agregar('r', sx, t.z, i); agregar('r', sx, sz, i); st.retRosca = false;
      const ult = roscas[roscas.length - 1];
      if (ult && ult.linea <= i && ult.z0 === sz && ult.z1 === t.z && ult.tipo === 92) { ult.x = sx > t.x ? Math.min(ult.x, t.x) : Math.max(ult.x, t.x); }
      else roscas.push({ z0: sz, z1: t.z, x: t.x, xc: t.x, paso: F, ext: sx > t.x, linea: i, tipo: 92 });
    }
  }

  let pc = 0, pasos = 0;
  while (pc < B.length && pasos++ < 200000) {
    const i = pc, b = B[pc]; pc++;
    if (b.vacio) continue;
    if (b.skip && opc.saltarBarra) continue;
    if (b.macro) { aviso(i, 'info', 'Línea con variables o macro: no se simula'); continue; }
    if (b.err) aviso(i, 'warn', b.err);
    if (b.sinPunto.length) aviso(i, 'warn', 'Número sin punto decimal (' + b.sinPunto.join(' ') + '): según el parámetro del control puede leerse en milésimas. Se toma en mm.');
    const w = b.w;
    if (w.O !== undefined && i > 0 && movs.length) { aviso(i, 'info', 'Empieza otro programa (O' + w.O + '): se deja de simular acá'); break; }
    if (w.T !== undefined) {
      const tt = Math.round(w.T), num = tt >= 100 ? Math.floor(tt / 100) : tt;
      if (num > 0) {
        st.herr = num;
        if (!herramientas[num]) herramientas[num] = { num: num, nombre: '', lineas: [] };
        const h = herramientas[num]; h.lineas.push(i);
        if (!h.nombre) {
          let nom = b.com;
          for (let k = i - 1; k >= Math.max(0, i - 3) && !nom; k--) { const p = B[k]; if (p.com && !p.g.length && !p.m.length && p.w.X === undefined && p.w.Z === undefined) nom = p.com; }
          h.nombre = nom || '';
        }
        eventos.push({ linea: i, seg: opc.cambioSeg, tipo: 'T', ini: tiempo }); tiempo += opc.cambioSeg;
      }
    }
    if (w.F !== undefined) st.F = w.F;
    let inc = false, conMov = true, vivo = st.vivo;
    for (let gi = 0; gi < b.g.length; gi++) {
      const g = b.g[gi];
      if (g === 0 || g === 1 || g === 2 || g === 3 || g === 32) { st.mov = g; st.ciclo = null; }
      else if (g === 4) { const sg = w.X !== undefined ? w.X : w.U !== undefined ? w.U : (w.P || 0) / 1000; eventos.push({ linea: i, seg: sg, tipo: 'G4', ini: tiempo }); tiempo += sg; conMov = false; }
      else if (g === 28 || g === 30) {
        const t = destino(b);
        if (t.hay) { agregar('r', t.x, t.z, i); agregar('r', w.X !== undefined || w.U !== undefined ? opc.homeX : st.x, w.Z !== undefined || w.W !== undefined ? opc.homeZ : st.z, i); }
        conMov = false;
      }
      else if (g === 50) { if (w.S !== undefined) st.smax = w.S; if (w.X !== undefined || w.Z !== undefined) aviso(i, 'warn', 'G50 con X/Z cambia el origen de coordenadas: no se simula'); conMov = false; }
      else if (g === 70) { cicloG70(i, b); conMov = false; }
      else if (g === 71) { const f = cicloG71(i, b); if (f != null) pc = f + 1; conMov = false; }
      else if (g === 72) { const f = cicloG72(i, b); if (f != null) pc = f + 1; conMov = false; }
      else if (g === 73) { const f = cicloG73(i, b); if (f != null) pc = f + 1; conMov = false; }
      else if (g === 74) { cicloG74(i, b); conMov = false; }
      else if (g === 75) { cicloG75(i, b); conMov = false; }
      else if (g === 76) { cicloG76(i, b); conMov = false; }
      else if (g === 90 || g === 92 || g === 94) {
        if (w.X !== undefined || w.Z !== undefined || w.U !== undefined || w.W !== undefined) st.ciclo = g;
        else if (g === 92 && w.S !== undefined) { st.smax = w.S; conMov = false; }
      }
      else if (g === 91) { inc = true; aviso(i, 'info', 'G91 (incremental): se toman X/Z como incrementales en este bloque'); }
      else if (g === 96) st.css = true;
      else if (g === 97) st.css = false;
      else if (g === 98) st.feedRev = false;
      else if (g === 99) st.feedRev = true;
      else if (g === 41 || g === 42) aviso(i, 'info', 'Compensación de radio (G' + g + '): se dibuja la punta, sin compensar');
      else if (g >= 83 && g <= 89) { st.vivo = true; vivo = true; aviso(i, 'info', 'Ciclo de herramienta motorizada (G' + g + '): no se simula'); }
      else if (g === 80) { st.vivo = false; vivo = false; }
      else if ([18, 20, 21, 40, 54, 55, 56, 57, 58, 59, 68, 69, 25, 26, 22, 23, 10, 11, 65, 66, 67, 112, 113].indexOf(g) >= 0) {
        if (g === 65 || g === 66) { aviso(i, 'info', 'Llamada a macro (G' + g + '): no se simula'); conMov = false; }
        if (g === 112) aviso(i, 'warn', 'Interpolación polar (G112): no se simula');
        if (g === 20) aviso(i, 'bad', 'G20 = pulgadas: el simulador trabaja en mm');
      }
      else aviso(i, 'info', 'G' + g + ' no se simula');
    }
    if (w.S !== undefined && b.g.indexOf(50) < 0 && !(b.g.indexOf(92) >= 0 && !st.ciclo)) st.S = w.S;
    for (let mi = 0; mi < b.m.length; mi++) {
      const m = b.m[mi];
      if (m === 3 || m === 4) st.husillo = true;
      else if (m === 5) st.husillo = false;
      else if (m === 0 || m === 1) {
        eventos.push({ linea: i, seg: 0, tipo: 'M' + m, ini: tiempo });
        let txt = b.com;
        for (let k = i + 1; k < Math.min(B.length, i + 3); k++) { const nb = B[k]; if (nb.vacio && !nb.com) continue; if (nb.com && !nb.g.length && !nb.m.length && !Object.keys(nb.w).length) txt += ' ' + nb.com; break; }
        if (/GIRAR|DAR VUELTA|VOLTEAR|DAR LA VUELTA/i.test(txt)) {
          if (opc.girar !== false) { giros.push({ linea: i, ini: tiempo }); aviso(i, 'info', 'Acá se da vuelta la pieza (' + txt.trim() + '): la cara queda del otro lado'); }
          else aviso(i, 'info', 'El programa pide dar vuelta la pieza: está apagado en la simulación');
        }
      }
      else if (m === 98) { aviso(i, 'warn', 'Subprograma (M98 P' + (w.P || '') + '): no se simula, se saltea'); conMov = false; }
      else if (m === 30 || m === 2) st.fin = true;
      else if (m === 99) st.fin = true;
    }
    if (conMov && !vivo) {
      const t = destino(b, inc);
      if (t.hay) {
        if (st.ciclo) cicloCaja(st.ciclo, i, b);
        else if (st.mov === 0) agregar('r', t.x, t.z, i);
        else if (st.mov === 1) agregar('f', t.x, t.z, i);
        else if (st.mov === 32) {
          const F = w.F !== undefined ? w.F : st.F, x0 = st.x, z0 = st.z;
          agregar('h', t.x, t.z, i, F);
          if (Math.abs(t.z - z0) > 1 && Math.abs(t.x - x0) < Math.abs(t.z - z0)) {
            const prev = roscas.find(function (r) { return r.tipo === 32 && Math.abs(r.z0 - z0) < 0.01 && Math.abs(r.z1 - t.z) < 0.01; });
            if (prev) { prev.x = prev.ext ? Math.min(prev.x, t.x) : Math.max(prev.x, t.x); }
            else roscas.push({ z0: z0, z1: t.z, x: t.x, xc: t.x, paso: F, ext: true, linea: i, tipo: 32 });
          }
        }
        else if (st.mov === 2 || st.mov === 3) arco(t.x, t.z, w, i, st.mov === 2, null, 'f');
      }
    }
    if (st.fin) break;
  }
  return { bloques: B, movs: movs, eventos: eventos, herramientas: herramientas, roscas: roscas, giros: giros, avisos: avisos,
           total: tiempo, opc: opc, lineas: lineas.length };
}
CNC.interpretar = interpretar;

/* ───────────── 3. Material y herramientas ───────────── */
const TIPOS = { ext: 'Exterior', int: 'Interior', ran: 'Ranurado / tronzado', rani: 'Ranurado interior', broca: 'Broca', nada: 'No corta (tirador, tope)' };
CNC.TIPOS = TIPOS;

function tipoPorNombre(nom) {
  const s = String(nom || '').toUpperCase();
  const num = function () { const m = s.match(/(?:Ø|D|DIAM\.?|DIA\.?)\s*(\d+(?:[.,]\d+)?)|(\d+(?:[.,]\d+)?)\s*(?:MM)?/); return m ? parseFloat((m[1] || m[2]).replace(',', '.')) : null; };
  if (/TIRADOR|PULLER|ALIMENT|TOPE|CONTRA ?PUNTA/.test(s)) return { tipo: 'nada' };
  if (/BROCA|MECHA|DRILL|PUNTO|CENTRAD|MACHO|TAP/.test(s)) return { tipo: 'broca', med: num() };
  if (/RANUR|TRONZ|CORTE|GROOV|PART|CUCHILLA|LAMA/.test(s)) return { tipo: /INT/.test(s) ? 'rani' : 'ran', med: num() };
  if (/INT|BARRA|ALES|BOR|AGUJ/.test(s)) return { tipo: 'int' };
  if (/EXT/.test(s)) return { tipo: 'ext' };
  return null;
}

function Material(barra) {
  this.b = barra;
  const L = Math.max(1, barra.largo);
  this.z0 = barra.cara - L; this.z1 = barra.cara;
  this.dz = Math.max(0.02, L / 2400);
  this.n = Math.ceil(L / this.dz);
  this.fuera = new Float32Array(this.n).fill(barra.d / 2);
  this.dentro = new Float32Array(this.n).fill(Math.max(0, (barra.din || 0) / 2));
}
Material.prototype.col = function (z) { return Math.floor((z - this.z0) / this.dz); };
// Saca material con la punta en (r, z). Devuelve cuánto sacó (mm, el máximo en una columna).
Material.prototype.cortar = function (r, z, h) {
  const n = this.n, dz = this.dz, fu = this.fuera, de = this.dentro;
  let saco = 0;
  if (h.tipo === 'broca') {
    if (Math.abs(r) > 0.3) return this.cortar(r, z, { tipo: 'int' });
    const rad = (h.med || 6) / 2;
    let c = Math.max(0, this.col(z)); if (c >= n) return 0;
    for (; c < n; c++) { const s = Math.min(rad, fu[c]) - de[c]; if (s > 0) { saco = Math.max(saco, s); de[c] = rad; } }
    return saco;
  }
  if (h.tipo === 'nada') return 0;
  if (h.tipo === 'ran' || h.tipo === 'rani') {
    const a = this.col(z), b2 = this.col(z + (h.med || 3)), ex = h.tipo === 'ran';
    for (let c = Math.max(0, a); c <= Math.min(n - 1, b2); c++) {
      if (ex) { const s = fu[c] - Math.max(r, de[c]); if (s > 0) { saco = Math.max(saco, s); fu[c] = r; } }
      else { const s = Math.min(r, fu[c]) - de[c]; if (s > 0) { saco = Math.max(saco, s); de[c] = r; } }
    }
    return saco;
  }
  const ext = h.tipo !== 'int', a = this.col(z), b = this.col(z + 4);
  for (let c = Math.max(0, a); c <= Math.min(n - 1, b); c++) {
    const zc = this.z0 + (c + 0.5) * dz, k = Math.max(0, zc - z) * 0.5;
    if (ext) { const lim = r + k; if (lim < fu[c]) { const s = fu[c] - Math.max(lim, de[c]); if (s > 0) saco = Math.max(saco, s); fu[c] = lim; } }
    else { const lim = r - k; if (lim > de[c]) { const s = Math.min(lim, fu[c]) - de[c]; if (s > 0) saco = Math.max(saco, s); de[c] = lim; } }
  }
  return saco;
};
// Dar vuelta la pieza: la punta que estaba en el plato pasa a ser la cara
Material.prototype.girar = function () { this.fuera.reverse(); this.dentro.reverse(); };
// Para decidir si una herramienta es exterior o interior: material en esa Z
Material.prototype.en = function (z) {
  let c = this.col(z); if (c >= this.n) c = this.n - 1; if (c < 0) c = 0;
  return { fu: this.fuera[c], de: this.dentro[c] };
};

// Simula todo (o hasta el tiempo t): aplica los movimientos al material.
function Sim(res, barra, herrOver) {
  this.res = res; this.barra = barra; this.over = herrOver || {};
  this.herr = {}; this.choques = [];
  this.reiniciar();
}
Sim.prototype.reiniciar = function () { this.mat = new Material(this.barra); this.k = 0; this.frac = 0; this.vistos = {}; this.g = 0; };
Sim.prototype.girosHasta = function (t) { const G = this.res.giros || []; while (this.g < G.length && G[this.g].ini <= t + 1e-9) { this.mat.girar(); this.g++; } };
Sim.prototype.herrDe = function (num, m) {
  if (this.herr[num]) return this.herr[num];
  const info = this.res.herramientas[num] || { nombre: '' };
  const o = this.over[num];
  let h;
  if (o && o.tipo) h = { tipo: o.tipo, med: o.med, origen: 'usuario' };
  else {
    const p = tipoPorNombre(info.nombre);
    if (p) h = { tipo: p.tipo, med: p.med || (p.tipo === 'broca' ? 6 : (p.tipo === 'ran' || p.tipo === 'rani') ? 3 : null), origen: 'comentario' };
    else if (m) {
      const neg = m.x0 < -1 && m.x1 < 0.5, r = (neg ? -m.x0 : m.x0) / 2, e = this.mat.en(m.z0);
      if (Math.abs(m.x0) < 0.05 && Math.abs(m.x1) < 0.05) h = { tipo: 'broca', med: 6, origen: 'posición' };
      else if (r >= e.fu - 0.01 || r >= this.barra.d / 2 - 0.01) h = { tipo: 'ext', origen: 'posición' };
      else if (r <= e.de + 0.01) h = { tipo: 'int', origen: 'posición' };
      else h = { tipo: (r - e.de < e.fu - r) ? 'int' : 'ext', origen: 'posición' };
      if (neg) h.neg = true;
    } else return null;
  }
  this.herr[num] = h; return h;
};
Sim.prototype.aplicar = function (m, f0, f1) {
  if (m.t === 'h') return;   // la rosca se dibuja aparte
  const h = this.herrDe(m.herr, m.t !== 'r' ? m : null) || { tipo: 'ext' };
  if (m.t !== 'r' && !h.lado) { h.lado = 1; if (m.x0 < -1 && m.x1 < 0.5) h.neg = true; }
  const dx = (m.x1 - m.x0) / 2, dz = m.z1 - m.z0, L = Math.hypot(dx, dz) * (f1 - f0);
  const paso = Math.max(0.01, this.mat.dz * 0.7), n = Math.max(1, Math.ceil(L / paso));
  let max = 0, donde = null;
  for (let j = 0; j <= n; j++) {
    const f = f0 + (f1 - f0) * j / n;
    const r0 = m.x0 / 2 + dx * f, r = h.neg ? -r0 : r0, z = m.z0 + dz * f;
    const s = this.mat.cortar(r, z, h);
    if (s > max) { max = s; donde = { x: r0 * 2, z: z }; }
  }
  if (m.t === 'r' && !m.ret && max > 0.05 && !this.vistos['r' + m.linea]) {
    this.vistos['r' + m.linea] = 1;
    this.choques.push({ linea: m.linea, x: donde.x, z: donde.z, mm: max, msg: 'Rápido (G0) que corta ' + max.toFixed(2) + ' mm de material' });
  }
  if (m.t === 'f' && !m.hus && max > 0.02 && !this.vistos['h' + m.linea]) {
    this.vistos['h' + m.linea] = 1;
    this.choques.push({ linea: m.linea, x: donde.x, z: donde.z, mm: max, msg: 'Corta con el husillo parado (falta M3 o M4)' });
  }
};
Sim.prototype.hasta = function (t) {
  const M = this.res.movs;
  const hecho = this.k < M.length ? M[this.k].ini + M[this.k].seg * this.frac : (M.length ? M[M.length - 1].ini + M[M.length - 1].seg : 0);
  if (t < hecho - 1e-9) this.reiniciar();
  while (this.k < M.length) {
    const m = M[this.k];
    if (this.frac === 0) this.girosHasta(m.ini);
    if (t >= m.ini + m.seg) { this.aplicar(m, this.frac, 1); this.k++; this.frac = 0; }
    else { const f = m.seg > 0 ? Math.max(0, (t - m.ini) / m.seg) : 1; if (f > this.frac) { this.aplicar(m, this.frac, f); this.frac = f; } break; }
  }
  if (this.k >= M.length) this.girosHasta(t);
};
CNC.Material = Material; CNC.Sim = Sim; CNC.tipoPorNombre = tipoPorNombre;

// Barra propuesta según el programa
CNC.barraSugerida = function (res) {
  let xmax = 0, zmin = 0, zmaxF = -1e9, xminInt = 1e9;
  const nada = {};
  Object.keys(res.herramientas).forEach(function (k) { const p = tipoPorNombre(res.herramientas[k].nombre); if (p && p.tipo === 'nada') nada[k] = 1; });
  res.movs.forEach(function (m) {
    if (m.t !== 'f' || nada[m.herr]) return;
    xmax = Math.max(xmax, m.x0, m.x1); zmin = Math.min(zmin, m.z0, m.z1); zmaxF = Math.max(zmaxF, m.z1);
  });
  if (!xmax) xmax = 50;
  let d = xmax + 2;
  res.movs.forEach(function (m) { if (m.t === 'r' && !nada[m.herr] && m.z1 < -0.5 && m.x1 >= xmax - 0.01 && m.x1 < d) d = m.x1; });
  d = Math.round(d * 10) / 10;
  // si el programa dice el diámetro de la barra en un comentario (DIAM 38, Ø38, BARRA 38)
  for (let k = 0; k < Math.min(12, res.bloques.length); k++) {
    const mm = String(res.bloques[k].com || '').toUpperCase().match(/(?:DIAM\.?|DIÁM\.?|Ø|BARRA|MATERIAL)\s*(\d+(?:[.,]\d+)?)/);
    if (mm) { const v = parseFloat(mm[1].replace(',', '.')); if (v > 2 && v < 1000) { d = v; break; } }
  }
  const L = Math.ceil(-zmin + 3);
  return { d: d, din: 0, cara: 0, largo: Math.max(10, L), saliente: Math.max(10, L + 5) };
};

/* ───────────── utilidades ───────────── */
CNC.fmtSeg = function (s) {
  s = Math.max(0, Math.round(s));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60;
  return (h ? h + ':' + String(m).padStart(2, '0') : m) + ':' + String(x).padStart(2, '0');
};
// diferencias línea por línea (LCS), para "ver cambios"
CNC.diferencias = function (a, b) {
  const n = a.length, m = b.length;
  if (n * m > 9e6) return null;
  const L = []; for (let i = 0; i <= n; i++) L.push(new Uint16Array(m + 1));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) L[i][j] = a[i] === b[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
  const out = []; let i = 0, j = 0;
  while (i < n && j < m) { if (a[i] === b[j]) { out.push({ t: '=', l: a[i], a: i + 1, b: j + 1 }); i++; j++; } else if (L[i + 1][j] >= L[i][j + 1]) { out.push({ t: '-', l: a[i], a: i + 1 }); i++; } else { out.push({ t: '+', l: b[j], b: j + 1 }); j++; } }
  while (i < n) { out.push({ t: '-', l: a[i], a: i + 1 }); i++; }
  while (j < m) { out.push({ t: '+', l: b[j], b: j + 1 }); j++; }
  return out;
};

if (typeof module !== 'undefined' && module.exports) module.exports = CNC;
raiz.CNC = CNC;
})(typeof window !== 'undefined' ? window : globalThis);

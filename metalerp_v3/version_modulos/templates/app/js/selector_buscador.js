// ── Selector con buscador (automático para <select> con más de 10 opciones) ──
// No reemplaza el <select>: el select original queda en su lugar (mismo id,
// mismo .value, mismos onchange). Al abrirlo con el mouse o el teclado, si
// tiene más de 10 opciones, en vez del desplegable nativo se muestra un
// panel con un campo de búsqueda. Elegir una opción asigna select.value y
// dispara 'change' como si se hubiera elegido en el desplegable nativo.
// Los <select multiple> con más de 10 opciones reciben un filtro de texto arriba.
(function(){
  const SS_MIN=10;
  let pop=null, inp=null, list=null, cur=null, items=[], hi=-1;
  const norm=s=>(s||'').toString().toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g,'');
  const aplica=s=>s&&s.tagName==='SELECT'&&!s.multiple&&!(s.size>1)&&!s.disabled&&s.options.length>SS_MIN&&!s.hasAttribute('data-no-buscador');

  function crear(){
    pop=document.createElement('div');
    pop.id='ss-pop';
    pop.style.cssText='position:fixed;z-index:100000;background:var(--color-background-primary,#fff);border:1px solid #cfd3d8;border-radius:8px;box-shadow:0 8px 24px rgba(0,0,0,.16);display:none;flex-direction:column;overflow:hidden;font-family:inherit';
    inp=document.createElement('input');
    inp.type='text';inp.placeholder='Buscar...';inp.autocomplete='off';
    inp.style.cssText='box-sizing:border-box;margin:6px;padding:6px 9px;font-size:13px;border:1px solid #ddd;border-radius:6px;outline:none;font-family:inherit;color:var(--color-text-primary,#1a1a1a);background:var(--color-background-primary,#fff)';
    list=document.createElement('div');
    list.style.cssText='overflow-y:auto;max-height:280px;padding-bottom:4px';
    pop.appendChild(inp);pop.appendChild(list);
    document.body.appendChild(pop);
    inp.addEventListener('input',function(){filtrar();});
    inp.addEventListener('keydown',function(e){
      if(e.key==='ArrowDown'){e.preventDefault();mover(1);}
      else if(e.key==='ArrowUp'){e.preventDefault();mover(-1);}
      else if(e.key==='PageDown'){e.preventDefault();mover(8);}
      else if(e.key==='PageUp'){e.preventDefault();mover(-8);}
      else if(e.key==='Enter'){e.preventDefault();if(hi>=0&&items[hi])elegir(items[hi].idx);}
      else if(e.key==='Escape'){e.preventDefault();e.stopPropagation();cerrar(true);}
      else if(e.key==='Tab'){cerrar(false);}
    });
    // Clic afuera: cerrar
    document.addEventListener('mousedown',function(e){
      if(pop.style.display!=='none'&&!pop.contains(e.target)&&e.target!==cur)cerrar(false);
    },true);
    window.addEventListener('resize',function(){if(cur)posicionar();});
    document.addEventListener('scroll',function(e){
      if(cur&&!pop.contains(e.target))posicionar();
    },true);
  }

  function posicionar(){
    if(!document.body.contains(cur)||!cur.offsetParent){cerrar(false);return;}
    const r=cur.getBoundingClientRect();
    const w=Math.max(r.width,260);
    let left=Math.min(r.left,window.innerWidth-w-8);if(left<8)left=8;
    pop.style.width=w+'px';pop.style.left=left+'px';
    const abajo=window.innerHeight-r.bottom, arriba=r.top;
    const h=Math.min(330,pop.offsetHeight||330);
    if(abajo<h+8&&arriba>abajo){pop.style.top='';pop.style.bottom=(window.innerHeight-r.top+2)+'px';list.style.maxHeight=Math.max(120,Math.min(280,arriba-60))+'px';}
    else{pop.style.bottom='';pop.style.top=(r.bottom+2)+'px';list.style.maxHeight=Math.max(120,Math.min(280,abajo-60))+'px';}
  }

  function filtrar(){
    const words=norm(inp.value).trim().split(/\s+/).filter(Boolean);
    items=[];
    const opts=cur.options;
    for(let i=0;i<opts.length;i++){
      const o=opts[i];
      if(o.hidden||o.style.display==='none')continue;
      const t=o.text;
      if(words.length){const n=norm(t);if(!words.every(w=>n.includes(w)))continue;}
      items.push({idx:i,text:t,dis:o.disabled});
    }
    render();
  }

  function render(){
    list.innerHTML='';
    const MAX=300;
    if(!items.length){
      list.innerHTML='<div style="padding:8px 10px;font-size:12px;color:#999">Sin resultados</div>';hi=-1;return;
    }
    const sel=cur.selectedIndex;
    hi=items.findIndex(it=>it.idx===sel&&!it.dis);
    if(hi<0||inp.value.trim())hi=items.findIndex(it=>!it.dis);
    const frag=document.createDocumentFragment();
    items.slice(0,MAX).forEach(function(it,k){
      const d=document.createElement('div');
      d.textContent=it.text||' ';
      d.dataset.k=k;
      d.style.cssText='padding:6px 10px;font-size:13px;line-height:1.3;cursor:'+(it.dis?'default':'pointer')+';color:'+(it.dis?'#aaa':'var(--color-text-primary,#1a1a1a)')+(it.idx===sel?';font-weight:600':'');
      if(!it.dis){
        d.onmouseenter=function(){marcar(k,false);};
        d.onmousedown=function(e){e.preventDefault();elegir(it.idx);};
      }
      frag.appendChild(d);
    });
    if(items.length>MAX){
      const m=document.createElement('div');
      m.style.cssText='padding:6px 10px;font-size:11px;color:#999';
      m.textContent='Mostrando '+MAX+' de '+items.length+'. Escribí más para afinar la búsqueda.';
      frag.appendChild(m);
    }
    list.appendChild(frag);
    marcar(hi,true);
  }

  function marcar(k,scroll){
    const prev=list.querySelector('[data-hi]');
    if(prev){prev.removeAttribute('data-hi');prev.style.background='';}
    hi=k;
    const el=list.querySelector('[data-k="'+k+'"]');
    if(el){el.setAttribute('data-hi','1');el.style.background='#e8f1fb';if(scroll)el.scrollIntoView({block:'nearest'});}
  }

  function mover(d){
    const lim=Math.min(items.length,300)-1;
    if(lim<0)return;
    const dir=d>0?1:-1;
    let k=hi<0?(d>0?-1:lim+1):hi;
    k=Math.max(0,Math.min(lim,k+d));
    while(k>=0&&k<=lim&&items[k].dis)k+=dir;
    if(k>=0&&k<=lim)marcar(k,true);
  }

  function elegir(idx){
    const s=cur;
    const cambio=s.selectedIndex!==idx;
    s.selectedIndex=idx;
    cerrar(true);
    if(cambio){
      s.dispatchEvent(new Event('input',{bubbles:true}));
      s.dispatchEvent(new Event('change',{bubbles:true}));
    }
  }

  function abrir(s,texto){
    if(!pop)crear();
    cur=s;
    inp.value=texto||'';
    pop.style.display='flex';
    filtrar();
    posicionar();
    inp.focus();
    if(texto){const n=inp.value.length;inp.setSelectionRange(n,n);}
  }

  function cerrar(foco){
    if(!pop)return;
    pop.style.display='none';
    const s=cur;cur=null;list.innerHTML='';items=[];
    if(foco&&s&&document.body.contains(s)){try{s.focus({preventScroll:true});}catch(_){}}
  }

  // Mouse: reemplaza el desplegable nativo
  document.addEventListener('mousedown',function(e){
    const s=e.target&&e.target.closest?e.target.closest('select'):null;
    if(!aplica(s)||e.button!==0)return;
    e.preventDefault();
    if(cur===s){cerrar(true);return;}
    abrir(s,'');
  },true);
  // Teclado sobre el select enfocado: abrir con flechas/Enter/espacio o al tipear
  document.addEventListener('keydown',function(e){
    const s=e.target;
    if(!aplica(s)||e.ctrlKey||e.metaKey)return;
    if(e.key==='Enter'||e.key===' '||e.key==='F4'||(e.altKey&&(e.key==='ArrowDown'||e.key==='ArrowUp'))){
      e.preventDefault();abrir(s,'');
    }else if(e.key.length===1&&!e.altKey){
      e.preventDefault();abrir(s,e.key);
    }
  },true);

  // <select multiple> grandes: filtro de texto arriba (se agrega al enfocarlo)
  function filtroMultiple(s){
    if(!s||s.tagName!=='SELECT'||!(s.multiple||s.size>1))return;
    if(s._ssFiltro){if(s._ssFiltro.value&&s.options.length&&!s._ssAplicado){s._ssAplicado=1;s._ssFiltro.dispatchEvent(new Event('input'));setTimeout(function(){s._ssAplicado=0;},300);}return;}
    if(s.options.length<=SS_MIN)return;
    const f=document.createElement('input');
    f.type='text';f.placeholder='Filtrar...';f.autocomplete='off';
    f.style.cssText='box-sizing:border-box;width:100%;height:28px;margin-bottom:4px;padding:4px 8px;font-size:12px;border:1px solid #ddd;border-radius:6px;font-family:inherit';
    f.addEventListener('input',function(){
      const words=norm(f.value).trim().split(/\s+/).filter(Boolean);
      Array.from(s.options).forEach(function(o){
        const n=norm(o.text);
        o.style.display=(!words.length||words.every(w=>n.includes(w))||o.selected)?'':'none';
      });
    });
    s.parentNode.insertBefore(f,s);
    s._ssFiltro=f;
  }
  document.addEventListener('focusin',function(e){filtroMultiple(e.target);},true);
  document.addEventListener('mouseover',function(e){
    const t=e.target;
    const s=t&&t.tagName==='OPTION'?t.parentNode:t;
    if(s&&s.tagName==='SELECT')filtroMultiple(s);
  },true);
})();

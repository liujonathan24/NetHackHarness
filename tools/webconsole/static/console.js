/* NetHack web console — shared client JS.
 *
 * Used across pages:
 *   colorize(rows,colors)        map render (map + traces)
 *   post(url,body)               JSON POST helper (all pages)
 *   buildGifs(boxId)             GIF gallery (landing)
 *   KEYMAP                       NetHack key translation (map)
 *   knob/play machinery          row/build/onChange/syncControl/apply/doReset/toggleRec (map)
 *
 * Each page template calls only what it needs.
 */

/* ---------- palette + colorizer ---------- */
const PALETTE=['#1a1a1a','#c44','#4b4','#b83','#46c','#b5b','#5bb','#bbb',
               '#666','#f66','#6f6','#fd5','#6af','#f6f','#6ff','#fff'];
const CHARCOL={'@':'#fd5','>':'#6ff','<':'#6ff','$':'#fd5','#':'#777','.':'#556',
               '|':'#bbb','-':'#bbb','+':'#4b4'};
// Escape HTML metacharacters before injecting a glyph into innerHTML. `&` must
// come first (NetHack draws major demons as '&'); '<'/'>' guard against the map
// stairs glyphs being parsed as tags.
function esc(ch){return ch==='&'?'&amp;':(ch==='<'?'&lt;':(ch==='>'?'&gt;':ch));}
function colorize(rows,colors){
  let h='';
  for(let y=0;y<rows.length;y++){for(let x=0;x<rows[y].length;x++){
    let ch=rows[y][x]; if(ch===' '){h+=' ';continue;}
    let c=colors?colors[y][x]:-1; let col=(c>=0&&c<16)?PALETTE[c]:(CHARCOL[ch]||(/[a-zA-Z]/.test(ch)?'#d6d':'#aaa'));
    h+='<span style="color:'+col+'">'+esc(ch)+'</span>';
  } h+='\n';} return h;
}

/* ---------- API helper ---------- */
/* Always resolves to an object; on transport/HTTP/parse failure returns
   {error:"..."} so callers can surface it instead of throwing. */
async function post(u,b){
  try{
    const r=await fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});
    const d=await r.json().catch(()=>({error:'bad response ('+r.status+')'}));
    if(!r.ok&&!d.error) d.error='request failed ('+r.status+')';
    return d;
  }catch(e){ return {error:'network error: '+(e&&e.message||e)}; }
}

/* ---------- GIF gallery (landing) ---------- */
async function buildGifs(boxId){
  const box=document.getElementById(boxId); if(!box) return;
  let list;
  try{ list=await(await fetch('/gifs')).json(); }
  catch(e){ box.innerHTML='<div class="obs-hint">could not load demos.</div>'; return; }
  if(!list.length){box.innerHTML='<div class="obs-hint">no GIFs found in videos/.</div>'; return;}
  box.innerHTML='';
  const grid=document.createElement('div'); grid.className='gif-grid';
  list.forEach(n=>{const w=document.createElement('div'); w.className='gif-cell';
    w.innerHTML='<div class="glabel">'+n+'</div><img src="/gif/'+n+'" loading="lazy" alt="Animated demo showing the effect of the '+n+' setting">'; grid.appendChild(w);});
  box.appendChild(grid);
}

/* ---------- knob + play machinery (map page) ---------- */
const KEYMAP={'ArrowUp':'k','ArrowDown':'j','ArrowLeft':'h','ArrowRight':'l','Enter':'\r','Escape':'\x1b'};
let curTune={}, META={};

function setDirty(v){const r=document.getElementById('reset'); if(r)r.classList.toggle('dirty',v);
  // Non-color cue (WCAG 1.4.1): the orange tint isn't the only signal that a
  // reset knob changed — surface a text marker too.
  const f=document.getElementById('dirtyflag'); if(f)f.hidden=!v;}
function syncControl(name,val){const m=META[name]; if(!m)return;
  if(m.kind==='bool'){const c=document.getElementById('k_'+name); if(c)c.checked=val>=0.5;}
  else {const r=document.getElementById('k_'+name), n=document.getElementById('n_'+name);
        if(r)r.value=val; if(n)n.value=(+val).toFixed(m.kind==='int'?0:2);}}
function apply(d){
  if(!d||d.error||!d.map){const m=document.getElementById('message');
    if(m)m.textContent=(d&&d.error)?('⚠ '+d.error):'⚠ no response from engine'; return;}
  document.getElementById('screen').innerHTML=colorize(d.map,d.colors);
  document.getElementById('message').textContent=d.message||' ';
  let s=d.status||{};  // defensive: render even if status is somehow absent
  document.getElementById('status').textContent='HP '+s.hp+'/'+s.max_hp+'   AC '+s.ac+'   Dlvl '+s.dlvl+'   $'+s.gold+'   XP-lvl '+s.xp_lvl+(d.done?'   [GAME OVER]':'');
  for(const k in d.tune) syncControl(k,d.tune[k]);
  setDirty(false);
  document.getElementById('recstat').textContent=d.recording?('● recording '+d.recording):'';
  syncRec(!!d.recording);
}
/* Single source of truth for the record button's visual + a11y + label state,
   shared by apply() (server-driven) and toggleRec() (click-driven). */
function syncRec(on){const rb=document.getElementById('recbtn'); if(!rb)return;
  rb.classList.toggle('on',on); rb.setAttribute('aria-pressed',on);
  const l=document.getElementById('reclabel'); if(l)l.textContent=on?'Stop recording':'Record trace';}
async function onChange(name,val){curTune[name]=val;
  if(META[name].reset) setDirty(true);
  else {const d=await post('/live',{name:name,value:val}); apply(d);}}
async function doReset(){
  // Parse the seed without an `||42` fallback — that would turn a valid seed of
  // 0 into 42 (0 is falsy). Only blank/non-numeric input falls back to 42.
  const raw=document.getElementById('seed').value.trim();
  const seed=(raw!==''&&Number.isFinite(+raw))?Math.trunc(+raw):42;
  const d=await post('/reset',{seed:seed,tune:curTune}); apply(d); document.getElementById('screen').focus();}
async function toggleRec(){
  const rb=document.getElementById('recbtn');
  const on=rb.classList.contains('on');
  const r=await post(on?'/record_stop':'/record_start',{});
  if(r&&r.error){const ms=document.getElementById('recstat'); if(ms)ms.textContent='⚠ '+r.error; return;}
  syncRec(!on);
  document.getElementById('recstat').textContent=on?('saved '+(r.name||'')+' ('+(r.turns||0)+' turns)'):('● recording '+r.name);
}
/* ---------- state-modify panel (map page) ---------- */
function modErr(msg){const e=document.getElementById('modstat'); if(e)e.textContent=msg||'';
  const m=document.getElementById('message'); if(m&&msg)m.textContent=msg;}
async function doModify(changes){
  const d=await post('/modify',{changes:changes});
  if(d&&d.error){modErr('modify error: '+d.error); return;}
  modErr(''); apply(d);
}
async function goLevel(){const v=Number(document.getElementById('m_goto').value);
  if(!Number.isFinite(v)){modErr('enter a level'); return;} await doModify({goto_depth:v});}
async function plusLevel(){await doModify({level_up:1});}
async function setField(name){const el=document.getElementById('m_'+name); const v=Number(el.value);
  if(el.value===''||!Number.isFinite(v)){modErr('enter a value for '+name); return;}
  await doModify({[name]:v});}

function row(m){const div=document.createElement('div'); div.className='knob';
  const rst=m.reset?' <span class="rst">&#8635;reset</span>':'';
  if(m.kind==='bool'){
    div.innerHTML='<span class="name">'+m.name+rst+'</span><label class="sw"><input type="checkbox" id="k_'+m.name+'" aria-label="'+m.name+'" '+(m.default>=0.5?'checked':'')+'><span></span></label>';
    div.querySelector('input').addEventListener('change',e=>onChange(m.name,e.target.checked?1:0));
  } else {const dec=m.kind==='int'?0:2;
    div.innerHTML='<span class="name">'+m.name+rst+'</span><input type="range" id="k_'+m.name+'" aria-label="'+m.name+'" min="'+m.lo+'" max="'+m.hi+'" step="'+m.step+'" value="'+m.default+'"><input type="number" class="num" id="n_'+m.name+'" aria-label="'+m.name+' value" min="'+m.lo+'" max="'+m.hi+'" step="'+m.step+'" value="'+(+m.default).toFixed(dec)+'">';
    const r=div.querySelector('input[type=range]'),n=div.querySelector('input.num');
    r.addEventListener('input',e=>{n.value=(+e.target.value).toFixed(dec); onChange(m.name,+e.target.value);});
    n.addEventListener('change',e=>{let v=Math.max(m.lo,Math.min(m.hi,+e.target.value)); n.value=v.toFixed(dec); r.value=v; onChange(m.name,v);});}
  if(m.note){const nt=document.createElement('span'); nt.className='note'; nt.textContent=m.note; div.appendChild(nt);} return div;}
async function build(){const cat=await(await fetch('/catalog')).json();
  cat.knobs.forEach(m=>{META[m.name]=m; curTune[m.name]=m.default;});
  const box=document.getElementById('groups');
  cat.groups.forEach(g=>{const h=document.createElement('h2'); h.textContent=g; box.appendChild(h);
    cat.knobs.filter(m=>m.group===g).forEach(m=>box.appendChild(row(m)));});}

/* Map page wires the keyboard handler + boots build(). On load it asks /current:
 * if a resume just happened (d.live) it renders that state instead of resetting,
 * so navigating from the Tracer's "Resume from this floor" keeps the resumed game.
 * Otherwise it does the normal fresh /reset. */
function initMap(){
  document.getElementById('screen').addEventListener('keydown',async e=>{
    let ch=KEYMAP[e.key]; if(!ch&&e.key.length===1)ch=e.key; if(!ch)return; e.preventDefault();
    apply(await post('/step',{keys:ch}));});
  // Enter to apply, matching type-then-Enter expectations: in the seed box it
  // regenerates; in a modify-panel number field it triggers that row's button.
  const seed=document.getElementById('seed');
  if(seed)seed.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();doReset();}});
  document.querySelectorAll('#modify .mnum').forEach(inp=>inp.addEventListener('keydown',e=>{
    if(e.key==='Enter'){e.preventDefault();const b=inp.parentNode.querySelector('button');if(b)b.click();}}));
  (async()=>{
    await build();
    let d=null; try{ d=await(await fetch('/current')).json(); }catch(e){ d=null; }
    if(d&&d.live){
      if(d.seed!==undefined){const sb=document.getElementById('seed'); if(sb)sb.value=d.seed;}
      apply(d); document.getElementById('screen').focus();
    }
    else { await doReset(); }
  })();
}

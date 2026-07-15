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
// NetHack color 0 is CLR_BLACK; true black (#1a1a1a) is ~1.1:1 on the near-black
// screen bg (#0c0d12) — invisible. Remap it to a visible dark gray (~3.7:1), the
// standard terminal "black -> bright black" behavior, so a black-colored glyph
// (deeper levels, some monsters) is never invisible. (In normal play color 0
// only lands on empty space, which colorize skips, so this is defensive.)
const PALETTE=['#6b6b78','#c44','#4b4','#b83','#46c','#b5b','#5bb','#bbb',
               '#666','#f66','#6f6','#fd5','#6af','#f6f','#6ff','#fff'];
const CHARCOL={'@':'#fd5','>':'#6ff','<':'#6ff','$':'#fd5','#':'#777','.':'#556',
               '|':'#bbb','-':'#bbb','+':'#4b4'};
// Escape HTML metacharacters before injecting a glyph into innerHTML. `&` must
// come first (NetHack draws major demons as '&'); '<'/'>' guard against the map
// stairs glyphs being parsed as tags.
function esc(ch){return ch==='&'?'&amp;':(ch==='<'?'&lt;':(ch==='>'?'&gt;':ch));}
// String-level HTML escape for injecting recorded text (e.g. Tracer LLM panes,
// which may come from shared eval traces) into innerHTML. `&` first.
function escHtml(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function colorize(rows,colors){
  let h='';
  if(!Array.isArray(rows)) return h;
  for(let y=0;y<rows.length;y++){
    // A row must be indexable (string/array). A foreign trace's raw_grid could
    // carry a null/number row; skip it rather than throw on null.length and
    // blank the whole render.
    const row=rows[y]; if(typeof row!=='string'&&!Array.isArray(row)){h+='\n';continue;}
    const crow=Array.isArray(colors)?colors[y]:null;
    for(let x=0;x<row.length;x++){
    let ch=row[x]; if(ch===' '){h+=' ';continue;}
    let c=crow?crow[x]:-1; let col=(c>=0&&c<16)?PALETTE[c]:(CHARCOL[ch]||(/[a-zA-Z]/.test(ch)?'#d6d':'#aaa'));
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
    // Build via DOM: set the label as a text node and the src/alt as properties.
    // escHtml escapes &<> but NOT quotes, so interpolating the name into a
    // double-quoted alt="" attribute would let a filename containing a " break
    // out and inject markup. Property assignment can't be escaped out of.
    const lbl=document.createElement('div'); lbl.className='glabel'; lbl.textContent=n;
    const img=document.createElement('img');
    img.src='/gif/'+encodeURIComponent(n); img.loading='lazy';
    img.alt='Animated demo showing the effect of the '+n+' setting';
    w.appendChild(lbl); w.appendChild(img); grid.appendChild(w);});
  box.appendChild(grid);
}

/* The demo gallery auto-plays looping animated GIFs. WCAG 2.2.2 (Pause, Stop,
 * Hide, Level A) requires a way to stop animation that starts automatically and
 * lasts >5s; this toggle hides/shows the gallery (the "hide" mechanism, and a
 * hidden GIF doesn't animate). Reduced-motion users (WCAG 2.3.3) start with it
 * hidden so no animation plays until they opt in. Gallery content is built into
 * #demos either way; only the container's visibility is toggled. */
function initGifToggle(){
  const btn=document.getElementById('gif-toggle'), demos=document.getElementById('demos');
  if(!btn||!demos) return;
  const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  function set(shown){
    demos.hidden=!shown;
    btn.setAttribute('aria-expanded', shown?'true':'false');
    btn.textContent = shown ? 'Hide animated demos' : 'Show animated demos';
  }
  set(!reduce);
  btn.addEventListener('click',()=>set(demos.hidden));
}

/* ---------- knob + play machinery (map page) ---------- */
const KEYMAP={'ArrowUp':'k','ArrowDown':'j','ArrowLeft':'h','ArrowRight':'l','Enter':'\r','Escape':'\x1b'};
let curTune={}, META={};
let curMode='standard';  // 'standard' | 'curriculum' (map page env mode)

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
    if(m)m.textContent=(d&&d.error)?('⚠ '+d.error):'⚠ no response from engine';
    // Clear the initial 'connecting…' placeholder on a failed first load so it
    // doesn't linger misleadingly; a real status line from prior play is kept.
    const st=document.getElementById('status'); if(st&&st.textContent==='connecting…')st.textContent='—';
    return;}
  document.getElementById('screen').innerHTML=colorize(d.map,d.colors);
  document.getElementById('message').textContent=d.message||' ';
  let s=d.status||{};  // defensive: render even if status is somehow absent
  document.getElementById('status').textContent='HP '+s.hp+'/'+s.max_hp+'   AC '+s.ac+'   Dlvl '+s.dlvl+'   $'+s.gold+'   XP-lvl '+s.xp_lvl+(d.done?'   [GAME OVER]':'');
  // Sync live knobs from the engine's reported tune. Skip RESET knobs: the engine
  // only reflects them after a regenerate, so syncing here would revert a pending
  // change back to the old floor's value. They stay user-controlled (curTune) and
  // keep their 'changes pending' state until Reset. (Dirty is cleared in doReset,
  // not here, so a step between changing a reset knob and Reset keeps the marker.)
  for(const k in d.tune){ if(META[k]&&META[k].reset) continue; curTune[k]=d.tune[k]; syncControl(k,d.tune[k]); }
  const rs=document.getElementById('recstat');
  // aria-hide the decorative ● so the live region announces 'recording <name>'
  // rather than 'black circle recording …' (consistent with the record button).
  if(d.recording) rs.innerHTML='<span aria-hidden="true">●</span> recording '+escHtml(d.recording);
  else rs.textContent='';
  syncRec(!!d.recording);
  syncUndo(d.undos);
  syncMark(d.marked);
  if(d.mode){ curMode=d.mode; syncModeUI(); }
  const cf=document.getElementById('currfloor');
  if(cf){
    if(d.curriculum_floor!==undefined){
      const n=d.curriculum_floor||0;
      cf.textContent = n>=1 ? ('Curriculum floor '+n+'/6 — '+(d.curriculum_floor_name||'')) : 'Off the tour path';
    } else cf.textContent='Floor: —';
  }
}
/* Reflect curMode in the selector + show/hide the curriculum panel. */
function syncModeUI(){
  const sel=document.getElementById('modesel'); if(sel&&sel.value!==curMode) sel.value=curMode;
  const panel=document.getElementById('currpanel'); if(panel) panel.hidden = (curMode!=='curriculum');
}
/* Switching mode rebuilds the env class, so it does a fresh reset in that mode. */
function onModeChange(){
  const sel=document.getElementById('modesel'); if(!sel) return;
  curMode=sel.value; syncModeUI(); doReset();
}
/* Curriculum mode: jump the hero onto floor n (1..6) and settle, then render so
   you can watch it climb back with real < stairs. */
function gotoCurr(n){
  return engineCall(()=>post('/curriculum/goto',{floor:n}).then(d=>{
    const cs=document.getElementById('currstat');
    if(d&&d.error){ if(cs)cs.textContent='⚠ '+d.error; return; }
    if(cs)cs.textContent='placed on floor '+n;
    apply(d); const scr=document.getElementById('screen'); if(scr)scr.focus();
  }));
}
/* Single source of truth for the record button's visual + a11y + label state,
   shared by apply() (server-driven) and toggleRec() (click-driven). */
function syncRec(on){const rb=document.getElementById('recbtn'); if(!rb)return;
  rb.classList.toggle('on',on); rb.setAttribute('aria-pressed',on);
  const l=document.getElementById('reclabel'); if(l)l.textContent=on?'Stop recording':'Record trace';}
/* Enable/disable the Undo button + show how many steps are undoable. */
function syncUndo(n){const b=document.getElementById('undobtn'); if(!b)return;
  n=n|0; b.disabled = n<=0;
  const c=document.getElementById('undocount'); if(c)c.textContent = n>0?('('+n+')'):'';}
/* Undo one step: restore the snapshot taken before the last step (Backspace). */
function doUndo(){
  return engineCall(()=>post('/undo',{n:1}).then(d=>{
    const us=document.getElementById('undostat');
    if(d&&d.error){ if(us)us.textContent=d.error; return; }
    apply(d);
    if(us)us.textContent='undid a step'+((d.undos>0)?(', '+d.undos+' left'):'');
  }));
}
/* Single source of truth for the Restore button's enabled state: it lights up
   only once a checkpoint exists (server reports d.marked). The Checkpoint button
   is always enabled — you can re-pin at any time, overwriting the prior mark. */
function syncMark(marked){const r=document.getElementById('restorebtn'); if(!r)return;
  r.disabled = !marked;}
/* Pin the current engine state as a checkpoint (live Monte-Carlo demo): play
   forward, Restore to snap back, repeat — branching from one fixed position. */
function doMark(){
  return engineCall(()=>post('/mark',{}).then(d=>{
    const ms=document.getElementById('markstat');
    if(d&&d.error){ if(ms)ms.textContent=d.error; return; }
    syncMark(true);
    if(ms)ms.textContent='checkpoint pinned';
  }));
}
/* Restore to the pinned checkpoint. Stays pinned, so you can restore repeatedly. */
function doRestore(){
  return engineCall(()=>post('/restore_mark',{}).then(d=>{
    const ms=document.getElementById('markstat');
    if(d&&d.error){ if(ms)ms.textContent=d.error; return; }
    apply(d);
    if(ms)ms.textContent='restored to checkpoint';
  }));
}
/* Serialize every engine-mutating request through one ordered queue. The server
   shares a single EngineEnv and the C engine is not reentrant, so two in-flight
   /step (e.g. from key-repeat or fast typing), or a /live arriving during a
   /step, could corrupt engine state or render frames out of order. Each call
   waits for the previous to settle, preserving input order; failures don't stall
   the queue (post() never rejects and apply() is error-safe, but guard anyway). */
let _engineQueue=Promise.resolve();
function engineCall(fn){
  const run=_engineQueue.then(fn,fn);
  _engineQueue=run.catch(()=>{});
  return run;
}
/* Debounce the /live posts per knob: dragging a slider fires `input` per pixel
   and each /live does an engine step + full redraw, so without this a single
   drag floods the queue with dozens of requests. The number readout still
   updates instantly (in the input handler); only the network call is coalesced
   to the trailing value, then serialized through engineCall. */
const _liveTimers={};
function postLive(name,val){
  clearTimeout(_liveTimers[name]);
  _liveTimers[name]=setTimeout(()=>{ engineCall(()=>post('/live',{name:name,value:val}).then(apply)); }, 90);
}
async function onChange(name,val){curTune[name]=val;
  if(META[name].reset) setDirty(true);
  else postLive(name,val);}
function doReset(){
  // Parse the seed without an `||42` fallback — that would turn a valid seed of
  // 0 into 42 (0 is falsy). Only blank/non-numeric input falls back to 42.
  const raw=document.getElementById('seed').value.trim();
  const seed=(raw!==''&&Number.isFinite(+raw))?Math.trunc(+raw):42;
  return engineCall(()=>post('/reset',{seed:seed,tune:curTune,mode:curMode}).then(d=>{
    apply(d); setDirty(false);  // the floor was regenerated with curTune -> nothing pending
    document.getElementById('screen').focus();}));}
function toggleRec(){
  const rb=document.getElementById('recbtn');
  const on=rb.classList.contains('on');
  // Serialized with steps so a record_start/stop captures a settled frame, not
  // one mid-step on the shared env.
  return engineCall(()=>post(on?'/record_stop':'/record_start',{}).then(r=>{
    if(r&&r.error){const ms=document.getElementById('recstat'); if(ms)ms.textContent='⚠ '+r.error; return;}
    syncRec(!on);
    const rs=document.getElementById('recstat');
    if(on){const n=r.turns||0; rs.textContent='saved '+(r.name||'')+' ('+n+' turn'+(n===1?'':'s')+')';}
    else rs.innerHTML='<span aria-hidden="true">●</span> recording '+escHtml(r.name);
  }));
}
/* ---------- state-modify panel (map page) ---------- */
function modErr(msg){const e=document.getElementById('modstat'); if(e)e.textContent=msg||'';
  const m=document.getElementById('message'); if(m&&msg)m.textContent=msg;}
function doModify(changes){
  return engineCall(()=>post('/modify',{changes:changes}).then(d=>{
    if(d&&d.error){modErr('modify error: '+d.error); return;}
    modErr(''); apply(d);
  }));
}
async function goLevel(){const v=Number(document.getElementById('m_goto').value);
  if(!Number.isFinite(v)){modErr('enter a level'); return;} await doModify({goto_depth:v});}
async function plusLevel(){await doModify({level_up:1});}
async function setField(name){const el=document.getElementById('m_'+name); const v=Number(el.value);
  if(el.value===''||!Number.isFinite(v)){modErr('enter a value for '+name); return;}
  await doModify({[name]:v});}

function row(m){const div=document.createElement('div'); div.className='knob';
  const rst=m.reset?' <span class="rst"><span aria-hidden="true">&#8635;</span>reset</span>':'';
  if(m.kind==='bool'){
    div.innerHTML='<span class="name">'+m.name+rst+'</span><label class="sw"><input type="checkbox" id="k_'+m.name+'" aria-label="'+m.name+'" '+(m.default>=0.5?'checked':'')+'><span></span></label>';
    div.querySelector('input').addEventListener('change',e=>onChange(m.name,e.target.checked?1:0));
  } else {const dec=m.kind==='int'?0:2;
    div.innerHTML='<span class="name">'+m.name+rst+'</span><input type="range" id="k_'+m.name+'" aria-label="'+m.name+'" min="'+m.lo+'" max="'+m.hi+'" step="'+m.step+'" value="'+m.default+'"><input type="number" class="num" id="n_'+m.name+'" aria-label="'+m.name+' value" min="'+m.lo+'" max="'+m.hi+'" step="'+m.step+'" value="'+(+m.default).toFixed(dec)+'">';
    const r=div.querySelector('input[type=range]'),n=div.querySelector('input.num');
    r.addEventListener('input',e=>{n.value=(+e.target.value).toFixed(dec); onChange(m.name,+e.target.value);});
    n.addEventListener('change',e=>{let x=+e.target.value; if(!Number.isFinite(x))x=+r.value;  // non-numeric -> keep last valid, no NaN
      let v=Math.max(m.lo,Math.min(m.hi,x)); n.value=v.toFixed(dec); r.value=v; onChange(m.name,v);});}
  if(m.note){const nt=document.createElement('span'); nt.className='note'; nt.textContent=m.note; div.appendChild(nt);} return div;}
async function build(){
  // Tolerate a failed/odd /catalog like the other list loaders: show a notice
  // instead of throwing, which would reject initMap's IIFE and skip the initial
  // reset — leaving the map blank with no message.
  let cat;
  try{ cat=await(await fetch('/catalog')).json(); }
  catch(e){ cat=null; }
  const box=document.getElementById('groups');
  if(!cat||!Array.isArray(cat.knobs)){
    if(box) box.innerHTML='<div class="obs-hint">could not load controls.</div>';
    return;
  }
  cat.knobs.forEach(m=>{META[m.name]=m; curTune[m.name]=m.default;});
  (cat.groups||[]).forEach(g=>{const h=document.createElement('h2'); h.textContent=g; box.appendChild(h);
    cat.knobs.filter(m=>m.group===g).forEach(m=>box.appendChild(row(m)));});}

/* Map page wires the keyboard handler + boots build(). On load it asks /current:
 * if a resume just happened (d.live) it renders that state instead of resetting,
 * so navigating from the Tracer's "Resume from this floor" keeps the resumed game.
 * Otherwise it does the normal fresh /reset. */
function initMap(){
  // Don't send /step until the initial reset/resume has started a game. The
  // server now rejects pre-start steps (so they can't crash it), but bailing
  // here avoids a flash of "call /reset first" and wasted requests if the user
  // types on the screen while the page is still loading.
  let _ready=false;
  document.getElementById('screen').addEventListener('keydown',e=>{
    // Let browser/OS shortcuts through (Ctrl/Cmd+C copy, Ctrl/Cmd+R reload,
    // paste, devtools, ...). The single-char path would otherwise swallow the
    // bare letter and preventDefault the shortcut — and it never produced a real
    // NetHack control code anyway.
    if(e.ctrlKey||e.metaKey||e.altKey) return;
    // Backspace = undo the last step (also prevents the browser's "back" nav).
    if(e.key==='Backspace'){ e.preventDefault(); if(_ready) doUndo(); return; }
    let ch=KEYMAP[e.key]; if(!ch&&e.key.length===1)ch=e.key; if(!ch)return; e.preventDefault();
    if(!_ready) return;  // game not started yet — ignore the keystroke
    engineCall(()=>post('/step',{keys:ch}).then(apply));});
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
      // A resume is a fresh state load: adopt the resumed engine's tune for ALL
      // knobs (incl. reset knobs, which apply() deliberately skips mid-play) so
      // the sliders and a later Reset reflect the resumed game, not build()'s
      // defaults.
      if(d.tune) for(const k in d.tune){ curTune[k]=d.tune[k]; syncControl(k,d.tune[k]); }
      apply(d); document.getElementById('screen').focus();
    }
    else { await doReset(); }
    _ready=true;  // a game is started (via resume or reset) — keystrokes now play
  })();
}

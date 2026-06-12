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
function esc(ch){return ch==='<'?'&lt;':(ch==='>'?'&gt;':ch);}
function colorize(rows,colors){
  let h='';
  for(let y=0;y<rows.length;y++){for(let x=0;x<rows[y].length;x++){
    let ch=rows[y][x]; if(ch===' '){h+=' ';continue;}
    let c=colors?colors[y][x]:-1; let col=(c>=0&&c<16)?PALETTE[c]:(CHARCOL[ch]||(/[a-zA-Z]/.test(ch)?'#d6d':'#aaa'));
    h+='<span style="color:'+col+'">'+esc(ch)+'</span>';
  } h+='\n';} return h;
}

/* ---------- API helper ---------- */
async function post(u,b){const r=await fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});return r.json();}

/* ---------- GIF gallery (landing) ---------- */
async function buildGifs(boxId){
  const list=await(await fetch('/gifs')).json();
  const box=document.getElementById(boxId); if(!box) return;
  if(!list.length){box.innerHTML='<div style="color:#5d5f6e">no GIFs found in videos/.</div>'; return;}
  box.innerHTML='';
  const grid=document.createElement('div'); grid.className='gif-grid';
  list.forEach(n=>{const w=document.createElement('div'); w.className='gif-cell';
    w.innerHTML='<div class="glabel">'+n+'</div><img src="/gif/'+n+'">'; grid.appendChild(w);});
  box.appendChild(grid);
}

/* ---------- knob + play machinery (map page) ---------- */
const KEYMAP={'ArrowUp':'k','ArrowDown':'j','ArrowLeft':'h','ArrowRight':'l','Enter':'\r','Escape':'\x1b'};
let curTune={}, META={};

function setDirty(v){const r=document.getElementById('reset'); if(r)r.classList.toggle('dirty',v);}
function syncControl(name,val){const m=META[name]; if(!m)return;
  if(m.kind==='bool'){const c=document.getElementById('k_'+name); if(c)c.checked=val>=0.5;}
  else {const r=document.getElementById('k_'+name), n=document.getElementById('n_'+name);
        if(r)r.value=val; if(n)n.value=(+val).toFixed(m.kind==='int'?0:2);}}
function apply(d){
  document.getElementById('screen').innerHTML=colorize(d.map,d.colors);
  document.getElementById('message').textContent=d.message||' ';
  let s=d.status;
  document.getElementById('status').textContent='HP '+s.hp+'/'+s.max_hp+'   AC '+s.ac+'   Dlvl '+s.dlvl+'   $'+s.gold+'   XP-lvl '+s.xp_lvl+(d.done?'   [GAME OVER]':'');
  for(const k in d.tune) syncControl(k,d.tune[k]);
  setDirty(false);
  document.getElementById('recstat').textContent=d.recording?('● recording '+d.recording):'';
  document.getElementById('recbtn').classList.toggle('on',!!d.recording);
}
async function onChange(name,val){curTune[name]=val;
  if(META[name].reset) setDirty(true);
  else {const d=await post('/live',{name:name,value:val}); apply(d);}}
async function doReset(){const seed=+document.getElementById('seed').value||42;
  const d=await post('/reset',{seed:seed,tune:curTune}); apply(d); document.getElementById('screen').focus();}
async function toggleRec(){
  const on=document.getElementById('recbtn').classList.contains('on');
  const r=await post(on?'/record_stop':'/record_start',{});
  document.getElementById('recbtn').classList.toggle('on',!on);
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
    div.innerHTML='<span class="name">'+m.name+rst+'</span><label class="sw"><input type="checkbox" id="k_'+m.name+'" '+(m.default>=0.5?'checked':'')+'><span></span></label>';
    div.querySelector('input').addEventListener('change',e=>onChange(m.name,e.target.checked?1:0));
  } else {const dec=m.kind==='int'?0:2;
    div.innerHTML='<span class="name">'+m.name+rst+'</span><input type="range" id="k_'+m.name+'" min="'+m.lo+'" max="'+m.hi+'" step="'+m.step+'" value="'+m.default+'"><input type="number" class="num" id="n_'+m.name+'" min="'+m.lo+'" max="'+m.hi+'" step="'+m.step+'" value="'+(+m.default).toFixed(dec)+'">';
    const r=div.querySelector('input[type=range]'),n=div.querySelector('input.num');
    r.addEventListener('input',e=>{n.value=(+e.target.value).toFixed(dec); onChange(m.name,+e.target.value);});
    n.addEventListener('change',e=>{let v=Math.max(m.lo,Math.min(m.hi,+e.target.value)); n.value=v.toFixed(dec); r.value=v; onChange(m.name,v);});}
  if(m.note){const nt=document.createElement('span'); nt.className='note'; nt.textContent=m.note; div.appendChild(nt);} return div;}
async function build(){const cat=await(await fetch('/catalog')).json();
  cat.knobs.forEach(m=>{META[m.name]=m; curTune[m.name]=m.default;});
  const box=document.getElementById('groups');
  cat.groups.forEach(g=>{const h=document.createElement('h3'); h.textContent=g; box.appendChild(h);
    cat.knobs.filter(m=>m.group===g).forEach(m=>box.appendChild(row(m)));});}

/* Map page wires the keyboard handler + boots build()+doReset(). */
function initMap(){
  document.getElementById('screen').addEventListener('keydown',async e=>{
    let ch=KEYMAP[e.key]; if(!ch&&e.key.length===1)ch=e.key; if(!ch)return; e.preventDefault();
    apply(await post('/step',{keys:ch}));});
  (async()=>{await build(); await doReset();})();
}

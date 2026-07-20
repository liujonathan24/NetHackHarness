/* Replays — the local console's Tracer, running on static JSON.
 *
 * The Flask console's Tracer talks to /traces and /trace?path=; there is no
 * server here, so `tools/export_trials.py` writes the same information ahead of
 * time to trials/index.json + trials/<id>.json and this file reads those.
 *
 * Two agent architectures are in the corpus and record different things, so a
 * turn is one of two kinds (normalized by the exporter):
 *   grid   — a tty map, the code the agent generated, the text the LLM was shown
 *   skill  — one skill-library iteration: objective, composed macro, feedback
 * colorize() and escHtml() come from console.js, used unchanged.
 */
(function () {
  'use strict';

  var INDEX = [];          // trials/index.json
  var TRIAL = null;        // the loaded trial {meta, turns}
  var CUR = 0;             // scrub position
  var FILTER = { agent: 'all', outcome: 'all' };
  var _req = 0;            // guards against a stale trial response landing late

  // Sequential ramp on --stairs (#9fe8ff): depth is a magnitude, so one hue
  // stepped dim -> bright. Never a hue per bar.
  var DEPTH_RAMP = ['#3f6f80', '#4b8496', '#5799ac', '#63aec3', '#70c3d9', '#87d9ef', '#9fe8ff'];

  function $(id) { return document.getElementById(id); }
  function depthColor(d, maxD) {
    if (maxD <= 1) return DEPTH_RAMP[DEPTH_RAMP.length - 1];
    var i = Math.round((d - 1) / (maxD - 1) * (DEPTH_RAMP.length - 1));
    return DEPTH_RAMP[Math.max(0, Math.min(DEPTH_RAMP.length - 1, i))];
  }

  // ---- filtering + the trial list ----

  function filtered() {
    return INDEX.filter(function (m) {
      return (FILTER.agent === 'all' || m.agent === FILTER.agent)
          && (FILTER.outcome === 'all' || m.outcome === FILTER.outcome);
    });
  }

  function chip(m) {
    // Outcome is never colour-alone: the glyph and the depth text carry it too.
    var ok = m.outcome === 'OK';
    return '<span class="chip ' + (ok ? 'ok' : 'no') + '">'
         + '<span aria-hidden="true">' + (ok ? '✓' : '·') + '</span> D' + m.max_dlvl
         + '</span>';
  }

  function renderList() {
    var box = $('t-items'), rows = filtered();
    box.innerHTML = '';
    if (!rows.length) {
      box.innerHTML = '<div class="obs-hint">no trials match this filter.</div>';
      return;
    }
    rows.forEach(function (m) {
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'f';
      b.innerHTML = '<span class="fname">' + escHtml(m.agent) + ' &middot; seed ' + m.seed + '</span>'
                  + '<span class="fmeta">' + chip(m) + ' <span class="fturns">'
                  + m.turns + ' turn' + (m.turns === 1 ? '' : 's') + '</span></span>';
      b.setAttribute('aria-label', m.agent + ', seed ' + m.seed + ', '
        + (m.outcome === 'OK' ? 'reached depth ' : 'stuck on depth ') + m.max_dlvl
        + ', ' + m.turns + ' turns');
      if (TRIAL && TRIAL.meta.id === m.id) b.setAttribute('aria-current', 'true');
      b.onclick = function () { loadTrial(m.id); };
      box.appendChild(b);
    });
  }

  // ---- the summary strip ----

  function renderSummary() {
    var rows = filtered(), box = $('summary');
    if (!rows.length) { box.innerHTML = ''; return; }

    // One stat tile per agent present: the share that got off dungeon level 1.
    var agents = {};
    rows.forEach(function (m) {
      var a = agents[m.agent] || (agents[m.agent] = { n: 0, ok: 0 });
      a.n++; if (m.outcome === 'OK') a.ok++;
    });
    var tiles = Object.keys(agents).sort().map(function (name) {
      var a = agents[name];
      return '<div class="tile"><div class="tval">' + a.ok + '<span class="tof">/' + a.n + '</span></div>'
           + '<div class="tlab">' + escHtml(name) + ' reached D2+</div></div>';
    }).join('');

    // Runs by max depth reached: one measure, one axis, single hue, every bar
    // directly labelled (so no tooltip is load-bearing).
    var hist = {}, maxD = 1;
    rows.forEach(function (m) { hist[m.max_dlvl] = (hist[m.max_dlvl] || 0) + 1; maxD = Math.max(maxD, m.max_dlvl); });
    var peak = Math.max.apply(null, Object.keys(hist).map(function (k) { return hist[k]; }));
    var bars = '';
    for (var d = 1; d <= maxD; d++) {
      var n = hist[d] || 0;
      bars += '<div class="brow"><span class="blab">D' + d + '</span>'
            + '<span class="btrack"><span class="bfill" style="width:' + (n / peak * 100) + '%;'
            + 'background:' + depthColor(d, maxD) + '"></span></span>'
            + '<span class="bval">' + n + '</span></div>';
    }

    box.innerHTML = '<div class="tiles">' + tiles + '</div>'
      + '<div class="chart"><div class="ctitle2">runs by max depth reached'
      + ' <span class="cn">n=' + rows.length + '</span></div>' + bars + '</div>';
  }

  // ---- one trial ----

  function loadTrial(id) {
    var mine = ++_req;
    $('t-status').textContent = 'loading ' + id + '…';
    fetch('trials/' + encodeURIComponent(id) + '.json')
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) {
        if (mine !== _req) return;          // superseded by a later click
        TRIAL = d; CUR = 0;
        var sc = $('scrub');
        sc.max = Math.max(0, d.turns.length - 1); sc.value = 0; sc.disabled = !d.turns.length;
        renderList();                        // repaint aria-current
        if (!d.turns.length) {
          $('t-status').textContent = 'this trial has no turns';
          ['t-head', 't-turninfo', 't-map', 't-llm'].forEach(function (i) { $(i).innerHTML = ''; });
          return;
        }
        showTurn(0);
      })
      .catch(function () {
        if (mine !== _req) return;
        $('t-status').textContent = '⚠ could not load ' + id;
      });
  }

  function headerFor(m, t) {
    // "Play this seed" hands the live engine the trial's seed and the depth the
    // agent was on at this turn (play.html reads ?seed / ?dlvl).
    var href = 'play.html?seed=' + encodeURIComponent(m.seed)
             + '&dlvl=' + encodeURIComponent(t.dlvl || 1);
    return '<div class="thead">'
      + '<span class="tname">' + escHtml(m.agent) + ' &middot; seed ' + m.seed + '</span>'
      + chip(m)
      + '<a class="mbtn playbtn" href="' + href + '"><span aria-hidden="true">&#9658;</span> '
      + 'Play this seed</a></div>';
  }

  function renderGrid(t) {
    $('t-map').hidden = false;
    $('t-map').innerHTML = colorize(t.rows || [], null);
    var llm = '';
    (t.code || []).forEach(function (c) {
      llm += '<div class="lbl">agent code <span class="sub">step ' + escHtml(c.step)
           + ' &middot; origin: ' + escHtml(c.origin || '?') + '</span></div>'
           + '<pre>' + escHtml(c.code || '') + '</pre>';
    });
    if (t.user) {
      llm += '<details class="llmdet"><summary>LLM input (the exact text the model saw)</summary>'
           + '<pre>' + escHtml(t.user) + '</pre></details>';
    }
    $('t-llm').innerHTML = llm;
  }

  function renderSkill(t) {
    // Voyager runs record a skill-library iteration, not a frame — there is no
    // map to show, so say so rather than leaving a stale grid on screen.
    $('t-map').hidden = true;
    $('t-map').innerHTML = '';
    var ok = t.success;
    var macro = (t.macro || []).map(function (s) {
      var args = s.args && Object.keys(s.args).length
        ? '(' + Object.keys(s.args).map(function (k) { return k + '=' + s.args[k]; }).join(', ') + ')'
        : '()';
      return '<li><code>' + escHtml(s.skill) + escHtml(args) + '</code></li>';
    }).join('');
    var fb = (t.feedback || []).map(function (f) {
      return '<li>' + escHtml(f) + '</li>';
    }).join('');
    $('t-llm').innerHTML =
        '<div class="nomap">This agent builds a <b>skill library</b> rather than acting'
      + ' frame by frame, so its trace records each proposed skill — not the map.'
      + ' The <code>rlm</code> trials on the left are the ones with a dungeon to scrub.</div>'
      + '<div class="lbl">objective <span class="sub">skill: ' + escHtml(t.skill || '—')
      + '</span></div><pre>' + escHtml(t.objective || '') + '</pre>'
      + '<div class="lbl">composed macro</div><ul class="mlist">' + macro + '</ul>'
      + '<div class="lbl">feedback</div><ul class="mlist">' + fb + '</ul>'
      + '<div class="skres ' + (ok ? 'ok' : 'no') + '"><span aria-hidden="true">'
      + (ok ? '✓' : '×') + '</span> '
      + (ok ? 'succeeded' : 'did not satisfy the success predicate')
      + (t.stored ? ' &middot; stored in the skill library' : '')
      + '</div>';
  }

  function showTurn(i) {
    if (!TRIAL || !TRIAL.turns.length) return;
    CUR = Math.max(0, Math.min(TRIAL.turns.length - 1, i));
    var t = TRIAL.turns[CUR], m = TRIAL.meta, n = TRIAL.turns.length;

    $('scrub').value = CUR;
    $('scrub').setAttribute('aria-valuetext', 'turn ' + t.turn + ', ' + (CUR + 1) + ' of ' + n);
    $('t-head').innerHTML = headerFor(m, t);
    $('t-status').textContent = t.kind === 'grid'
      ? 'dlvl ' + (t.dlvl == null ? '?' : t.dlvl)
        + (t.pos && t.pos.length === 2 ? '   pos (' + t.pos[0] + ',' + t.pos[1] + ')' : '')
        + (t.actions == null ? '' : '   ' + t.actions + ' actions applied')
      : 'dlvl ' + (t.dlvl == null ? '?' : t.dlvl)
        + (t.library == null ? '' : '   skill library: ' + t.library);
    $('t-turninfo').textContent = (t.kind === 'grid' ? 'turn ' : 'iteration ') + t.turn
      + '  (' + (CUR + 1) + '/' + n + ')';
    if (t.kind === 'grid') renderGrid(t); else renderSkill(t);
  }

  // ---- wiring ----

  $('scrub').addEventListener('input', function (e) { showTurn(+e.target.value); });
  document.addEventListener('keydown', function (e) {
    if (!TRIAL) return;
    if (e.target && /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName) && e.target.id !== 'scrub') return;
    if (e.key === 'ArrowLeft') { e.preventDefault(); showTurn(CUR - 1); }
    else if (e.key === 'ArrowRight') { e.preventDefault(); showTurn(CUR + 1); }
  });
  Array.prototype.forEach.call(document.querySelectorAll('.fbtn'), function (b) {
    b.addEventListener('click', function () {
      var key = b.dataset.filter;
      FILTER[key] = b.dataset.value;
      Array.prototype.forEach.call(document.querySelectorAll('.fbtn[data-filter="' + key + '"]'),
        function (o) { o.setAttribute('aria-pressed', String(o === b)); });
      renderList(); renderSummary();
    });
  });

  fetch('trials/index.json')
    .then(function (r) { return r.json(); })
    .then(function (ix) {
      // Deepest first, then by agent/seed — the interesting runs are at the top.
      INDEX = ix.sort(function (a, b) {
        return (b.max_dlvl - a.max_dlvl) || a.agent.localeCompare(b.agent) || (a.seed - b.seed);
      });
      renderList(); renderSummary();
      // Open on the deepest run that actually has a map, so the first thing a
      // visitor sees is a dungeon rather than a skill log.
      var first = INDEX.filter(function (m) { return m.kind === 'grid'; })[0] || INDEX[0];
      if (first) loadTrial(first.id);
    })
    .catch(function () {
      $('t-items').innerHTML = '<div class="obs-hint">could not load the trial index.</div>';
    });
})();

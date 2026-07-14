'use strict';
const $ = s => document.querySelector(s);

// ── analysis worker RPC ─────────────────────────────────────────────────────
const worker = new Worker('js/worker.js', { type: 'module' });
let rpcId = 0;
const pending = new Map();
worker.onmessage = (ev) => {
  const { id, result } = ev.data;
  const cb = pending.get(id);
  if (cb) { pending.delete(id); cb(result); }
};
worker.onerror = (err) => {
  $('#progress').hidden = true;
  showError('Analysis engine failed to load: ' + (err.message || 'worker error'));
};
function rpc(msg, transfer = []) {
  return new Promise((resolve) => {
    const id = ++rpcId;
    pending.set(id, resolve);
    worker.postMessage({ ...msg, id }, transfer);
  });
}

// ── navigation ──────────────────────────────────────────────────────────────
$('#nav-analyze').onclick = () => switchView('analyze');
$('#nav-history').onclick = () => { switchView('history'); loadHistory(); };
function switchView(v) {
  $('#view-analyze').hidden = v !== 'analyze';
  $('#view-history').hidden = v !== 'history';
  $('#nav-analyze').classList.toggle('active', v === 'analyze');
  $('#nav-history').classList.toggle('active', v === 'history');
}

// ── upload ──────────────────────────────────────────────────────────────────
const dz = $('#dropzone');
dz.addEventListener('dragover', e => { e.preventDefault(); dz.classList.add('hover'); });
dz.addEventListener('dragleave', () => dz.classList.remove('hover'));
dz.addEventListener('drop', e => {
  e.preventDefault(); dz.classList.remove('hover');
  if (e.dataTransfer.files.length) upload(e.dataTransfer.files[0]);
});
$('#browse-btn').onclick = () => $('#file-input').click();
$('#file-input').onchange = e => { if (e.target.files.length) upload(e.target.files[0]); };

async function upload(file) {
  $('#error').hidden = true; $('#results').hidden = true;
  $('#dropzone').hidden = true; $('#progress').hidden = false;
  $('#progress-text').textContent = `Crunching ${file.name} (${(file.size / 1048576).toFixed(0)} MB)…`;
  try {
    const buffer = await file.arrayBuffer();
    const data = await rpc({ cmd: 'analyze', fileName: file.name, buffer }, [buffer]);
    $('#progress').hidden = true;
    if (data.error) return showError(data.error);
    render(data);
  } catch (err) {
    $('#progress').hidden = true;
    showError('Could not run the analysis: ' + err.message);
  }
}
function showError(msg) {
  $('#dropzone').hidden = false;
  const el = $('#error'); el.hidden = false; el.textContent = msg;
}

// ── render ──────────────────────────────────────────────────────────────────
function render(data) {
  $('#dropzone').hidden = false;
  const R = $('#results'); R.hidden = false; R.innerHTML = '';
  const m = data.meta;

  R.appendChild(el(`<div class="meta-bar">
    <div><span>Car</span><b>${esc(m.car)}</b></div>
    <div><span>Track</span><b>${esc(m.track)}</b></div>
    <div><span>Driver</span><b>${esc(m.driver || '—')}</b></div>
    <div><span>Setup</span><b>${esc(m.setup_name || 'from telemetry')}</b></div>
    ${data.n_corners ? `<div><span>Corners detected</span><b>${data.n_corners}</b></div>` : ''}
  </div>`));

  const tabs = el('<div class="stint-tabs"></div>');
  const body = el('<div></div>');
  R.appendChild(tabs); R.appendChild(body);

  data.stints.forEach((s, i) => {
    const b = el(`<button>Stint ${s.stint_num} (${s.analysis.n_laps_total} laps)</button>`);
    b.onclick = () => {
      tabs.querySelectorAll('button').forEach(x => x.classList.remove('active'));
      b.classList.add('active');
      renderStint(body, s);
    };
    tabs.appendChild(b);
    if (i === 0) { b.classList.add('active'); renderStint(body, s); }
  });
}

function renderStint(root, s) {
  const a = s.analysis;
  root.innerHTML = '';

  if (s.graded && s.graded.length) {
    const lines = s.graded.map(g =>
      `<b class="${g.win ? 'win' : 'loss'}">${g.win ? '✔' : '✘'}</b> ${esc(g.knob.replace(/_/g, ' '))} for “${esc(g.symptom)}” — pace ${fmtDelta(g.pace_delta)} s/lap, symptom ${g.severity_delta < 0 ? 'improved' : 'unchanged/worse'}`
    ).join('<br>');
    root.appendChild(el(`<div class="graded-banner"><b>Learning update:</b> this stint graded your previous changes on this car/track.<br>${lines}</div>`));
  }

  const degCls = a.deg_per_lap > 0.08 ? 'bad' : a.deg_per_lap > 0.03 ? 'warn' : 'good';
  const conCls = a.consistency > 0.8 ? 'bad' : a.consistency > 0.4 ? 'warn' : 'good';
  root.appendChild(el(`<div class="tiles">
    <div class="tile"><div class="v">${fmtLap(a.best_lap)}</div><div class="l">Best lap</div></div>
    <div class="tile"><div class="v">${fmtLap(a.median_lap)}</div><div class="l">Median lap</div></div>
    <div class="tile"><div class="v ${conCls}">±${a.consistency.toFixed(2)}s</div><div class="l">Consistency (σ)</div></div>
    <div class="tile"><div class="v ${degCls}">${fmtDelta(a.deg_per_lap)}s</div><div class="l">Pace trend / lap</div></div>
    <div class="tile"><div class="v">${a.fuel_used.toFixed(1)}</div><div class="l">Fuel used</div></div>
    <div class="tile"><div class="v">${a.n_laps_used}/${a.n_laps_total}</div><div class="l">Clean laps used</div></div>
  </div>`));

  const plat = a.platform || {};
  if (plat.roll_couple_front != null || plat.brakes || plat.tires) {
    let rows = '';
    if (plat.roll_couple_front != null)
      rows += `<div><span>Front roll share</span><b>${(100 * plat.roll_couple_front).toFixed(0)}%</b></div>`;
    if (plat.brakes)
      rows += `<div><span>Measured brake bias (front)</span><b>${plat.brakes.front_share_pct.toFixed(1)}%${plat.brakes.dial != null ? ' (dial ' + plat.brakes.dial.toFixed(1) + ')' : ''}</b></div>`;
    let tireRows = '';
    for (const w of ['LF', 'RF', 'LR', 'RR']) {
      const t = (plat.tires || {})[w];
      if (!t) continue;
      tireRows += `<tr><td>${w}</td><td>${t.inner.toFixed(0)} / ${t.middle.toFixed(0)} / ${t.outer.toFixed(0)}</td>
        <td>${t.camber_delta >= 0 ? '+' : ''}${t.camber_delta.toFixed(0)}°C</td>
        <td>${t.middle_vs_edges >= 0 ? '+' : ''}${t.middle_vs_edges.toFixed(0)}°C</td>
        <td>${t.hot_pressure_psi ? t.hot_pressure_psi.toFixed(1) + ' psi' : '—'}</td>
        <td>${t.pressure_build_psi != null ? (t.pressure_build_psi >= 0 ? '+' : '') + t.pressure_build_psi.toFixed(1) : '—'}</td></tr>`;
    }
    const table = tireRows ? `<table class="tire-table"><thead><tr><th></th><th>in/mid/out °C</th>
      <th>camber Δ</th><th>mid−edges</th><th>hot press</th><th>build</th></tr></thead><tbody>${tireRows}</tbody></table>` : '';
    root.appendChild(el(`<div class="chart-panel"><h3>Measured platform (from per-wheel telemetry)</h3>
      <div class="meta-bar" style="border:0;padding:6px 0;margin:0">${rows}</div>${table}</div>`));
  }

  const cp = el('<div class="chart-panel"><h3>Lap times across the stint</h3><canvas height="170"></canvas></div>');
  root.appendChild(cp);
  drawLapChart(cp.querySelector('canvas'), a.lap_nums, a.lap_times);

  const cp2 = el('<div class="chart-panel"><h3>Corner balance map (– = pushes, + = loose)</h3><canvas height="190"></canvas></div>');
  root.appendChild(cp2);
  drawBalanceChart(cp2.querySelector('canvas'), a.corners);

  if (s.top_changes && s.top_changes.length) {
    const box = el(`<div class="top-changes"><h3>Most recommended changes</h3>
      <p class="tc-sub">Ranked across all findings this stint — consensus picks first.</p></div>`);
    s.top_changes.forEach((t, i) => {
      const arrow = t.direction > 0 ? '<span class="dir-up">▲</span>' : '<span class="dir-down">▼</span>';
      const L = t.learned || { conf: 0.5, tries: 0, wins: 0 };
      const badges = [];
      if (t.n_findings > 1) badges.push(`<span class="tc-badge consensus">backed by ${t.n_findings} findings</span>`);
      if (t.recurrence) badges.push(`<span class="tc-badge">recommended in ${t.recurrence.hits}/${t.recurrence.stints} recent stints with this car</span>`);
      if (L.tries > 0) badges.push(`<span class="tc-badge ${L.conf >= 0.5 ? 'good' : 'bad'}">worked ${L.wins}/${L.tries}× on this car</span>`);
      box.appendChild(el(`<div class="tc-row">
        <span class="tc-rank">${i + 1}</span>
        <div class="tc-body">
          <div class="tc-change">${arrow} ${esc(t.knob.replace(/_/g, ' '))} — ${esc(t.size)}</div>
          <div class="tc-why">for: ${t.symptoms.map(esc).join(' · ')}</div>
          <div class="tc-badges">${badges.join(' ')}</div>
        </div></div>`));
    });
    root.appendChild(box);
  }

  if (!s.findings.length) {
    root.appendChild(el(`<div class="no-findings"><h3>No significant setup complaints found</h3>
      <p>This stint looks balanced and consistent. Chase pace with driving-line work, or bring a longer run for degradation analysis.</p></div>`));
    return;
  }

  s.findings.forEach(f => {
    const sev = f.severity >= 3 ? 'sev-high' : f.severity < 2 ? 'sev-low' : '';
    const card = el(`<div class="finding ${sev}">
      <h3>${esc(f.symptom)}</h3>
      <div class="evidence">${esc(f.evidence)}</div>
    </div>`);
    f.proposals.forEach(p => {
      const arrow = p.direction > 0 ? '<span class="dir-up">▲ increase</span>' : '<span class="dir-down">▼ decrease</span>';
      const L = p.learned || { conf: 0.5, tries: 0, wins: 0 };
      let confCls = '', confTxt = 'untested on this car';
      if (L.tries > 0) {
        confCls = L.conf >= 0.5 ? 'tested-good' : 'tested-bad';
        confTxt = `worked ${L.wins}/${L.tries}× on this car`;
      }
      const cur = Object.entries(p.current).map(([k, v]) => `${esc(k)} = ${esc(v)}`).join(' · ');
      card.appendChild(el(`<div class="proposal">
        <div class="head"><span class="change">${esc(p.knob.replace(/_/g, ' '))} — ${arrow} ${esc(p.size)}</span>
        <span class="conf ${confCls}">${confTxt}</span></div>
        <div class="current">now: ${cur}</div>
        <div class="why">${esc(p.why)}</div>
        <div class="tradeoff">Trade-off: ${esc(p.tradeoff)}</div>
        ${p.expect ? `<div class="expect">Expected: ${esc(p.expect)}</div>` : ''}
        ${p.verify ? `<div class="verify">Verify next stint: ${esc(p.verify)}</div>` : ''}
      </div>`));
    });
    root.appendChild(card);
  });
}

// ── charts (hand-rolled, no deps) ───────────────────────────────────────────
function setupCanvas(c) {
  const dpr = window.devicePixelRatio || 1;
  const w = c.clientWidth || c.parentElement.clientWidth - 36;
  const h = +c.getAttribute('height');
  c.width = w * dpr; c.height = h * dpr;
  c.style.height = h + 'px';
  const ctx = c.getContext('2d');
  ctx.scale(dpr, dpr);
  return [ctx, w, h];
}

function drawLapChart(c, nums, times) {
  const [ctx, W, H] = setupCanvas(c);
  const pad = { l: 52, r: 12, t: 10, b: 24 };
  const min = Math.min(...times), max = Math.max(...times);
  const span = Math.max(max - min, 0.4);
  const x = i => pad.l + (W - pad.l - pad.r) * (times.length === 1 ? 0.5 : i / (times.length - 1));
  const y = t => pad.t + (H - pad.t - pad.b) * (1 - (t - min) / span);

  ctx.strokeStyle = '#2d333b'; ctx.fillStyle = '#8b949e'; ctx.font = '11px Segoe UI';
  for (let g = 0; g <= 3; g++) {
    const t = min + span * g / 3, yy = y(t);
    ctx.beginPath(); ctx.moveTo(pad.l, yy); ctx.lineTo(W - pad.r, yy); ctx.stroke();
    ctx.fillText(fmtLap(t), 4, yy + 4);
  }
  const n = times.length, sx = times.reduce((s, _, i) => s + i, 0), sy = times.reduce((s, t) => s + t, 0);
  const sxy = times.reduce((s, t, i) => s + i * t, 0), sxx = times.reduce((s, _, i) => s + i * i, 0);
  const slope = (n * sxy - sx * sy) / (n * sxx - sx * sx || 1), icpt = (sy - slope * sx) / n;
  ctx.strokeStyle = '#d2992288'; ctx.setLineDash([5, 5]); ctx.beginPath();
  ctx.moveTo(x(0), y(icpt)); ctx.lineTo(x(n - 1), y(icpt + slope * (n - 1))); ctx.stroke(); ctx.setLineDash([]);

  ctx.strokeStyle = '#58a6ff'; ctx.lineWidth = 2; ctx.beginPath();
  times.forEach((t, i) => i ? ctx.lineTo(x(i), y(t)) : ctx.moveTo(x(i), y(t)));
  ctx.stroke();
  ctx.fillStyle = '#f0b429';
  times.forEach((t, i) => { ctx.beginPath(); ctx.arc(x(i), y(t), 3.2, 0, 7); ctx.fill(); });
  ctx.fillStyle = '#8b949e';
  times.forEach((_, i) => { if (i % Math.ceil(n / 14) === 0) ctx.fillText('L' + nums[i], x(i) - 8, H - 6); });
}

function drawBalanceChart(c, corners) {
  const [ctx, W, H] = setupCanvas(c);
  const pad = { l: 52, r: 12, t: 12, b: 26 };
  const n = corners.length;
  const bw = Math.min(44, (W - pad.l - pad.r) / n * 0.62);
  const mid = pad.t + (H - pad.t - pad.b) / 2;
  const scaleMax = Math.max(1.6, ...corners.map(k => Math.abs(balanceScore(k))));
  const y = v => mid - (v / scaleMax) * (H - pad.t - pad.b) / 2;

  ctx.strokeStyle = '#2d333b'; ctx.beginPath(); ctx.moveTo(pad.l, mid); ctx.lineTo(W - pad.r, mid); ctx.stroke();
  ctx.fillStyle = '#8b949e'; ctx.font = '11px Segoe UI';
  ctx.fillText('loose', 8, pad.t + 10); ctx.fillText('pushes', 8, H - pad.b - 2);

  corners.forEach((k, i) => {
    const v = balanceScore(k);
    const xx = pad.l + (W - pad.l - pad.r) * (i + 0.5) / n - bw / 2;
    ctx.fillStyle = v > 0 ? '#f85149cc' : '#58a6ffcc';
    const hh = Math.abs(y(v) - mid);
    ctx.fillRect(xx, v > 0 ? y(v) : mid, bw, Math.max(hh, 1));
    ctx.fillStyle = '#8b949e';
    ctx.fillText('T' + k.corner, xx + bw / 2 - 8, H - 8);
  });
}
function balanceScore(k) { return 10 * k.oversteer_frac - Math.max(k.understeer_z, 0); }

// ── history ─────────────────────────────────────────────────────────────────
async function loadHistory() {
  const data = await rpc({ cmd: 'history' });
  const L = $('#history-list'); L.innerHTML = '';
  if (!data.stints.length) { L.innerHTML = '<p style="color:#8b949e">Nothing analyzed yet.</p>'; return; }
  data.stints.forEach(s => {
    const row = el(`<div class="hist-row">
      <span class="when">${new Date(s.created * 1000).toLocaleString()}</span>
      <span class="car">${esc(s.car)}</span><span class="track">${esc(s.track)}</span>
      <span class="track">stint ${s.stint_num} · ${esc(s.driver || '')}</span></div>`);
    row.onclick = async () => {
      const d = await rpc({ cmd: 'stint', stintId: s.id });
      if (d.error) return;
      switchView('analyze'); render(d);
    };
    L.appendChild(row);
  });
}

// ── utils ───────────────────────────────────────────────────────────────────
function el(html) { const d = document.createElement('div'); d.innerHTML = html.trim(); return d.firstChild; }
function esc(s) { const d = document.createElement('span'); d.textContent = String(s); return d.innerHTML; }
function fmtLap(t) { const m = Math.floor(t / 60); return m ? `${m}:${(t - m * 60).toFixed(3).padStart(6, '0')}` : t.toFixed(3); }
function fmtDelta(v) { return (v >= 0 ? '+' : '') + v.toFixed(3); }

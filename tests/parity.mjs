// Parity test: JS pipeline vs the Python engine's verified numbers on the
// same real .ibt. Run: node tests/parity.mjs <path-to.ibt>
import { readFileSync } from 'node:fs';
import { parseIbt } from '../docs/js/ibt.js';
import { parseSessionInfo } from '../docs/js/session.js';
import { segmentLaps, segmentStints } from '../docs/js/stints.js';
import { detectCorners, analyzeStint } from '../docs/js/analysis.js';
import { diagnose, summarize } from '../docs/js/engine.js';

const path = process.argv[2];
const b = readFileSync(path);
const ab = b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength);

const t0 = Date.now();
const ibt = parseIbt(ab);
const meta = parseSessionInfo(ibt.sessionInfo);
console.log(`${meta.car} @ ${meta.track} — ${meta.driver} (${Object.keys(meta.setup).length} setup params)`);

const laps = segmentLaps(ibt);
const stints = segmentStints(laps);
const corners = detectCorners(ibt, laps);
console.log(`laps=${laps.length} stints=${stints.length} corners=${corners.length}`);

for (const st of stints) {
  const a = analyzeStint(ibt, st, corners);
  if (!a) { console.log(`stint ${st.stint_num}: too few clean laps`); continue; }
  const p = a.platform;
  console.log(`--- stint ${st.stint_num}: ${a.n_laps_used}/${a.n_laps_total} laps, ` +
    `best ${a.best_lap.toFixed(3)}, median ${a.median_lap.toFixed(3)}, ` +
    `trend ${a.deg_per_lap >= 0 ? '+' : ''}${a.deg_per_lap.toFixed(3)} s/lap, fuel ${a.fuel_used.toFixed(1)}`);
  if (p.roll_couple_front != null) console.log(`  roll front share: ${(100 * p.roll_couple_front).toFixed(0)}%`);
  if (p.brakes) console.log(`  brakes: front share ${p.brakes.front_share_pct.toFixed(1)}% (dial ${p.brakes.dial})`);
  for (const [w, t] of Object.entries(p.tires || {})) {
    console.log(`  ${w}: in-out ${t.camber_delta >= 0 ? '+' : ''}${t.camber_delta.toFixed(0)}C, ` +
      `mid-edges ${t.middle_vs_edges >= 0 ? '+' : ''}${t.middle_vs_edges.toFixed(0)}C, ` +
      `hot ${t.hot_pressure_psi.toFixed(1)} psi (build ${t.pressure_build_psi >= 0 ? '+' : ''}${t.pressure_build_psi.toFixed(1)})`);
  }
  const findings = diagnose(a, meta.setup);
  for (const f of findings) {
    console.log(`  [${f.severity.toFixed(1)}] ${f.symptom} -> ${f.proposals.map((x) => x.knob).join(', ')}`);
    console.log(`       ${f.evidence.slice(0, 140)}`);
  }
  const top = summarize(findings);
  console.log('  top:', top.map((t) => `${t.knob}${t.direction > 0 ? '+' : '-'}`).join(', '));

  // parity assertions vs Python results on the Imola Merc file
  if (meta.car.includes('Mercedes')) {
    const ok = (name, cond) => { if (!cond) throw new Error(`PARITY FAIL: ${name}`); };
    ok('car', meta.car === 'Mercedes-AMG GT3 2020');
    ok('params=78', Object.keys(meta.setup).length === 78);
    ok('corners=17', corners.length === 17);
    ok('laps used 12', a.n_laps_used === 12);
    ok('best ~103.912', Math.abs(a.best_lap - 103.912) < 0.01);
    ok('median ~105.184', Math.abs(a.median_lap - 105.184) < 0.01);
    ok('trend ~-0.064', Math.abs(a.deg_per_lap - -0.064) < 0.01);
    ok('roll ~47%', Math.abs(p.roll_couple_front - 0.4667) < 0.02);
    ok('brakes ~52.0', Math.abs(p.brakes.front_share_pct - 52.0) < 0.3);
    ok('exit traction found', findings.some((f) => f.symptom === 'Poor corner-exit traction'));
    ok('knife-edge found', findings.some((f) => f.symptom.startsWith('Knife-edge')));
    console.log('\nPARITY OK vs Python engine');
  }
}
console.log(`elapsed: ${((Date.now() - t0) / 1000).toFixed(1)}s`);

// Rule-based recommendation engine — port of core/engine.py (v2 deep telemetry).

const KNOBS = {
  brake_bias: /brake.*bias|bias.*brake/i,
  rear_wing: /rear.*wing|wing.*angle|rearwing/i,
  front_wing: /front.*wing|front.*splitter|splitter/i,
  front_arb: /front.*(arb|anti.?roll)|(arb|anti.?roll).*front/i,
  rear_arb: /rear.*(arb|anti.?roll)|(arb|anti.?roll).*rear/i,
  lf_pressure: /(left|l)f.*(cold|starting).*pressure|(cold|starting).*pressure.*lf/i,
  rf_pressure: /(right|r)f.*(cold|starting).*pressure|(cold|starting).*pressure.*rf/i,
  lr_pressure: /(left|l)r.*(cold|starting).*pressure|(cold|starting).*pressure.*lr/i,
  rr_pressure: /(right|r)r.*(cold|starting).*pressure|(cold|starting).*pressure.*rr/i,
  front_spring: /(lf|rf|front).*spring/i,
  rear_spring: /(lr|rr|rear).*spring/i,
  front_camber: /(lf|rf|front).*camber/i,
  rear_camber: /(lr|rr|rear).*camber/i,
  front_ride_height: /(front|lf|rf).*ride.*height/i,
  rear_ride_height: /(rear|lr|rr).*ride.*height/i,
  front_bump: /(lf|rf|front).*(bump|compression)/i,
  rear_bump: /(lr|rr|rear).*(bump|compression)/i,
  front_rebound: /(lf|rf|front).*rebound/i,
  rear_rebound: /(lr|rr|rear).*rebound/i,
  diff_preload: /preload/i,
  diff_coast: /coast.*ramp|coast.*lock/i,
  diff_power: /(power|drive).*ramp|(power|drive).*lock|friction.*faces/i,
  traction_control: /traction.*control|\btc\b/i,
  abs_setting: /\babs\b|anti.?lock/i,
  brake_pressure: /brake.*pressure(?!.*bias)|master.*cyl/i,
  front_toe: /(front|lf|rf).*toe|toe.*in/i,
  rear_toe: /(lr|rr|rear).*toe/i,
  cross_weight: /cross.*weight|wedge/i,
};

export function matchKnobs(setup) {
  const found = {};
  for (const [knob, rx] of Object.entries(KNOBS)) {
    const keys = Object.keys(setup).filter((k) => rx.test(k.replace(/\./g, ' ')));
    if (keys.length) found[knob] = keys;
  }
  return found;
}

const worst = (corners, key, n = 3) =>
  corners.filter((c) => key in c).sort((a, b) => b[key] - a[key]).slice(0, n);
const byClass = (corners, cls) => corners.filter((c) => c.speed_class === cls);
const fmt = (v, d = 1) => v.toFixed(d);

export function diagnose(stintA, setup) {
  const knobs = matchKnobs(setup);
  const corners = stintA.corners;
  const platform = stintA.platform || {};
  const tires = platform.tires || {};
  const brakes = platform.brakes;
  const rollF = platform.roll_couple_front;
  const bottom = platform.bottoming;
  const findings = [];

  const prop = (knob, direction, size, why, tradeoff, expect = '', verify = '') => {
    if (!(knob in knobs)) return null;
    const current = {};
    for (const k of knobs[knob]) current[k] = setup[k];
    return { knob, keys: knobs[knob], direction, size, why, tradeoff, expect, verify, current };
  };
  const add = (symptom, severity, evidence, proposals) => {
    const ps = proposals.filter(Boolean);
    if (ps.length) findings.push({ symptom, severity, evidence, proposals: ps });
  };

  const rollNote = rollF != null ? ` Measured platform: the front carries ${fmt(100 * rollF, 0)}% of total roll.` : '';

  // 1a) Aero understeer (high-speed corners)
  const usHi = byClass(corners, 'high').filter((c) => c.understeer_z > 0.8);
  if (usHi.length) {
    const w = worst(usHi, 'understeer_z');
    const ev = 'Front washes out specifically in the fast corners (' +
      w.map((c) => `corner ${c.corner} @ ${fmt(c.min_speed_kph, 0)} km/h`).join(', ') +
      ') while slower corners are fine — that is an AERO balance problem, not mechanical.';
    add('Aero understeer (high-speed corners)', 2.5 + Math.max(...usHi.map((c) => c.understeer_z)), ev, [
      prop('front_wing', +1, 'one step',
        'More front aero moves the aero balance forward exactly where this shows up.',
        'Can make the rear nervous in the same corners — change one step at a time.',
        'Less steering needed at high-speed apexes; front-tire temps rise slightly.',
        'Next stint: understeer z-score in high-speed corners should drop toward 0.'),
      prop('rear_wing', -1, 'one step',
        'Trimming rear wing shifts balance forward and buys straight-line speed too.',
        'Less rear stability everywhere, especially under braking from high speed.',
        'Better rotation at speed + higher trap speed.',
        'Watch entry stability into the fastest braking zone.'),
      prop('front_ride_height', -1, '1–2 mm lower',
        'Lower front ride height increases front downforce (rake effect).',
        'Bottoming risk — check for floor strikes after.',
        'More front grip at speed with no drag penalty.',
        'Bottoming events per lap must stay near zero.'),
    ]);
  }

  // 1b) Mechanical understeer (slow/medium)
  const usLo = corners.filter((c) => c.speed_class !== 'high' && c.understeer_z > 1.0 && c.understeer_drift < 0.10);
  if (usLo.length >= Math.max(1, corners.length >> 2)) {
    const w = worst(usLo, 'understeer_z');
    const ev = 'Mechanical understeer in slow/medium corners (' +
      w.map((c) => `corner ${c.corner} (${fmt(c.min_speed_kph, 0)} km/h, z=${c.understeer_z >= 0 ? '+' : ''}${fmt(c.understeer_z)})`).join(', ') +
      ') where aero barely matters.' + rollNote;
    add('Mechanical understeer (slow/medium corners)', 2 + Math.max(...usLo.map((c) => c.understeer_z)), ev, [
      prop('front_arb', -1, 'one step softer',
        'Softer front bar lets the outside front take more load mid-corner.' +
        (rollF && rollF > 0.54 ? ` The front already carries ${fmt(100 * rollF, 0)}% of roll — this directly rebalances it.` : ''),
        'Slightly lazier turn-in response.',
        'More front grip from apex out in the slow stuff.',
        'Understeer z at the listed corners; front roll share should drop a few points.'),
      prop('rear_arb', +1, 'one step stiffer',
        'Stiffer rear bar rotates the car by trimming rear lateral grip.',
        'Less rear security on bumpy exits and kerbs.',
        'Sharper rotation; watch for new exit wheelspin.',
        'Wheelspin fraction on exits must not grow.'),
      prop('diff_preload', -1, 'one step less',
        'Less preload frees the car into and through slow corners.',
        'Can add on-throttle snappiness in low gear.',
        'Easier rotation at low speed.',
        'Exit counter-steer fraction in slow corners.'),
      prop('lf_pressure', -1, '0.3–0.7 psi (both fronts)',
        'Lower cold front pressures grow the front contact patch.',
        'Slower warm-up on out-laps.',
        'Front grip up slightly everywhere.',
        'Front middle-vs-edge temp delta should move toward 0.'),
    ]);
  }

  // 2) Degradation-driven balance drift
  const driftingLoose = corners.filter((c) => c.oversteer_drift > 0.05);
  if (driftingLoose.length >= Math.max(1, corners.length >> 2) && stintA.deg_per_lap > 0.03) {
    let rearHot = '';
    for (const w of ['LR', 'RR']) {
      const t = tires[w];
      if (t && (t.pressure_build_psi || 0) > 1.5) {
        rearHot += ` ${w} hot pressure built +${fmt(t.pressure_build_psi)} psi over the stint.`;
      }
    }
    const ev = `Pace fell ${fmt(stintA.deg_per_lap, 3)} s/lap despite the car getting lighter, and ` +
      `counter-steer grew late-stint at ${driftingLoose.length} corners — the rear is giving up faster than the front.${rearHot}`;
    add('Rear degradation — car goes loose over the stint', 2 + 20 * stintA.deg_per_lap, ev, [
      prop('rr_pressure', -1, '0.3–0.5 psi (both rears)',
        'Lower cold rear pressure caps late-stint overheating of the rear carcass.',
        'Marginally lazier response on laps 1–2.',
        'Rear pressure build shrinks; balance drift flattens.',
        'Rear pressure_build should come in under ~1.5 psi next stint.'),
      prop('rear_camber', +1, 'toward less negative by ~0.2°',
        'Less rear camber spreads temperature across the tread and slows wear.',
        'Small loss of peak rear grip on fresh tires.',
        'Rear inner-edge temps drop; deg slope improves.',
        'Rear camber_delta (inner−outer) should shrink.'),
      prop('rear_wing', +1, 'one step',
        'More rear load supports the rear as tires fade — the classic endurance trade.',
        'Straight-line cost; expect a few km/h of trap speed.',
        'Late-stint oversteer drift shrinks.',
        'oversteer_drift at the listed corners.'),
      prop('diff_coast', -1, 'one step less coast lock',
        'Less coast-side locking eases the rear on entry as grip fades.',
        'Slightly more mid-corner rotation to manage.',
        'Entry feels calmer on worn tires.',
        'Late-stint entry counter-steer events.'),
    ]);
  }

  // 3) Chronic oversteer
  const looseNow = corners.filter((c) => c.oversteer_frac > 0.12 && c.oversteer_drift <= 0.05);
  if (looseNow.length >= Math.max(1, corners.length >> 2)) {
    const w = worst(looseNow, 'oversteer_frac');
    const ev = 'Counter-steer on fresh tires at ' +
      w.map((c) => `corner ${c.corner} (${fmt(100 * c.oversteer_frac, 0)}%)`).join(', ') +
      ' — the platform is loose, not worn out.' + rollNote;
    add('Chronic oversteer', 2 + 10 * Math.max(...looseNow.map((c) => c.oversteer_frac)), ev, [
      prop('rear_arb', -1, 'one step softer',
        'Softer rear bar adds rear compliance and lateral grip.' +
        (rollF && rollF < 0.46 ? ` Front roll share is only ${fmt(100 * rollF, 0)}% — the rear is doing too much of the work.` : ''),
        'A touch more roll, slower transients.',
        'Counter-steer fraction drops at the listed corners.',
        'oversteer_frac; also confirm no new understeer in slow corners.'),
      prop('rear_wing', +1, 'one step',
        'More rear downforce plants the rear in the quick stuff.',
        'Straight-line speed cost.',
        'Biggest effect in medium/high-speed corners.',
        'oversteer_frac split by speed class.'),
      prop('rear_spring', -1, 'one step softer',
        'Softer rear springs improve mechanical rear grip, especially on kerbs.',
        'Rear ride height drops under load — check for bottoming.',
        'Calmer rear on bumps and kerbs.',
        'Bottoming events must stay near zero.'),
      prop('front_arb', +1, 'one step stiffer',
        'Balancing move: take a little front grip instead of adding rear.',
        'Adds understeer in slow corners.',
        'Overall balance shifts toward stable.',
        'Watch understeer z in slow corners.'),
    ]);
  }

  // 4) Exit traction — measured wheelspin when available
  const spinCorners = corners.filter((c) => (c.wheelspin_frac || 0) > 0.08);
  const proxyCorners = corners.filter((c) => (c.exit_counter || 0) > 0.10);
  const badExit = spinCorners.length ? spinCorners : proxyCorners;
  if (badExit.length >= Math.max(1, Math.floor(corners.length / 5))) {
    let ev, sev;
    if (spinCorners.length) {
      const w = worst(spinCorners, 'wheelspin_frac');
      ev = 'MEASURED rear wheelspin on exit at ' +
        w.map((c) => `corner ${c.corner} (${fmt(100 * c.wheelspin_frac, 0)}% of throttle-on samples)`).join(', ') +
        ' — rear wheel speed exceeds car speed by 6%+.';
      sev = 2 + 12 * Math.max(...spinCorners.map((c) => c.wheelspin_frac));
    } else {
      const w = worst(proxyCorners, 'exit_counter');
      ev = 'Throttle-on counter-steer at ' +
        w.map((c) => `corner ${c.corner} (${fmt(100 * c.exit_counter, 0)}%)`).join(', ') +
        ' — the rear breaks traction as power goes down.';
      sev = 1.5 + 10 * Math.max(...proxyCorners.map((c) => c.exit_counter));
    }
    add('Poor corner-exit traction', sev, ev, [
      prop('diff_power', -1, 'one step less power-side lock',
        'Less drive lock lets the inside rear slip instead of lighting up both rears.',
        'Can cost drive on long full-throttle exits.',
        'Wheelspin fraction halves at the listed corners.',
        'wheelspin_frac next stint.'),
      prop('rear_spring', -1, 'one step softer',
        'More rear compliance = more traction under power.',
        'Watch rear ride height under fuel load.',
        'Better drive off slow corners especially.',
        'wheelspin_frac in low-speed corners.'),
      prop('traction_control', +1, 'one step (if class rules allow)',
        'A click more TC trims the worst of the wheelspin cheaply.',
        'Masks the mechanical problem; try the diff first.',
        'Immediate reduction in spin events.',
        'Lap time should NOT get slower on exits (over-cut TC does).'),
      prop('rr_pressure', -1, '0.3 psi (both rears)',
        'Bigger rear contact patch on corner exit.',
        'Slower warm-up.',
        'Small but free traction gain.',
        'Rear middle-vs-edge temp delta.'),
    ]);
  }

  // 5) Braking
  const lockF = corners.filter((c) => (c.front_lock_frac || 0) > 0.10);
  const lockR = corners.filter((c) => (c.rear_lock_frac || 0) > 0.08);
  const absHeavy = corners.filter((c) => (c.abs_frac || 0) > 0.35);
  if (lockF.length || (absHeavy.length && !lockR.length)) {
    let biasNote = '';
    if (brakes) {
      biasNote = ` Measured front line-pressure share: ${fmt(brakes.front_share_pct)}%`;
      if (brakes.dial != null) biasNote += ` (bias dial ${fmt(brakes.dial)}).`;
    }
    const pool = lockF.length ? lockF : absHeavy;
    const w = worst(pool, lockF.length ? 'front_lock_frac' : 'abs_frac');
    const ev = 'Front axle saturates under braking at ' +
      w.map((c) => `corner ${c.corner}`).join(', ') +
      (lockF.length ? ' — front wheels dip below 82% of car speed'
        : ' — ABS intervenes on over a third of braking samples') + '.' + biasNote;
    const sevBase = lockF.length
      ? Math.max(...lockF.map((c) => c.front_lock_frac || 0))
      : Math.max(...absHeavy.map((c) => (c.abs_frac || 0) * 0.5));
    add('Front lockups / ABS-limited braking', 2.2 + 5 * sevBase, ev, [
      prop('brake_bias', -1, '0.5% rearward',
        "Moving bias rearward uses more of the rear axle's braking capacity.",
        'Too far = entry instability; move in 0.5% steps.',
        'Front lock fraction drops; braking distances shorten.',
        'front_lock_frac and entry oversteer_frac together.'),
      prop('brake_pressure', -1, 'a few % less master pressure',
        'If you are ABS-limited everywhere, total pressure is past the grip ceiling.',
        'Longer pedal travel feel.',
        'ABS engagement fraction drops without losing decel.',
        'abs_frac next stint.'),
      prop('front_camber', -1, '~0.2° more negative',
        'More front camber adds braking-zone grip on the loaded edge into corners.',
        'Slightly less straight-line braking contact.',
        'Later braking into the worst corners.',
        'front_lock_frac in the listed corners.'),
    ]);
  }
  if (lockR.length) {
    const w = worst(lockR, 'rear_lock_frac');
    const ev = 'REAR wheels lock under braking at ' +
      w.map((c) => `corner ${c.corner} (${fmt(100 * c.rear_lock_frac, 0)}%)`).join(', ') +
      ' — that is instability waiting to happen.' +
      (brakes ? ` Measured front line-pressure share ${fmt(brakes.front_share_pct)}%.` : '');
    add('Rear lockups under braking', 2.5 + 8 * Math.max(...lockR.map((c) => c.rear_lock_frac)), ev, [
      prop('brake_bias', +1, '0.5% forward',
        'Forward bias stops the rears locking before the fronts.',
        'Slightly longer stopping distance if fronts saturate instead.',
        'Rear lock events disappear; entry feels planted.',
        'rear_lock_frac must go to ~0.'),
      prop('diff_coast', +1, 'one step more coast lock',
        'More coast lock stabilizes the rear axle off-throttle.',
        'More entry understeer in slow corners.',
        'Calmer entries even before touching bias.',
        'Entry counter-steer events.'),
    ]);
  }

  // 6) Tire temps: camber + pressure per axle
  for (const [axle, ws, camKnob, pressKnob] of [
    ['front', ['LF', 'RF'], 'front_camber', 'lf_pressure'],
    ['rear', ['LR', 'RR'], 'rear_camber', 'lr_pressure'],
  ]) {
    const recs = ws.filter((w) => tires[w]).map((w) => tires[w]);
    if (recs.length < 2) continue;
    const cam = (recs[0].camber_delta + recs[1].camber_delta) / 2;
    const mve = (recs[0].middle_vs_edges + recs[1].middle_vs_edges) / 2;
    const Axle = axle[0].toUpperCase() + axle.slice(1);
    if (cam > 18) {
      add(`Excess ${axle} camber (inner edges running hot)`, 1.6 + cam / 15,
        `${Axle} inner edges run ${fmt(cam, 0)}°C hotter than outer while loaded ` +
        '(healthy is ~8–15°C). The tread is not working evenly — pace and wear both suffer.', [
        prop(camKnob, +1, '~0.2–0.4° less negative',
          'Flattening camber puts the whole tread to work and cools the inner edge.',
          'A little less peak mid-corner grip.',
          `${axle} inner−outer delta moves toward 12°C.`,
          'camber_delta next stint.')]);
    } else if (cam > 0 && cam < 4) {
      add(`Not enough ${axle} camber (tread too flat)`, 1.4,
        `${Axle} inner and outer edges within ${fmt(cam, 0)}°C while loaded — the tire ` +
        'is not leaning into its camber; mid-corner grip is being left on the table.', [
        prop(camKnob, -1, '~0.2–0.3° more negative',
          'More camber loads the tread properly when the car rolls onto it.',
          'Slightly more inner-edge wear over very long runs.',
          `${axle} camber_delta rises toward ~10°C; apex speeds up.`,
          'camber_delta + min corner speeds.')]);
    }
    if (mve > 5) {
      add(`${Axle} tires overinflated (center overheating)`, 1.5 + mve / 5,
        `${Axle} tread centers run ${fmt(mve, 0)}°C hotter than the edges — the tire is ` +
        'crowning on its center. Contact patch is smaller than it should be.', [
        prop(pressKnob, -1, '0.5–1.0 psi (both sides)',
          'Lower cold pressure flattens the crown and restores full contact.',
          'Slower warm-up; re-check hot pressures after.',
          'middle_vs_edges falls toward 0–3°C.',
          'middle_vs_edges next stint.')]);
    } else if (mve < -5) {
      add(`${Axle} tires underinflated (edges overheating)`, 1.5 - mve / 5,
        `${Axle} tread centers run ${fmt(-mve, 0)}°C cooler than the edges — the tire is ` +
        'folding onto its shoulders. Carcass is working too hard and will overheat late-stint.', [
        prop(pressKnob, +1, '0.5–1.0 psi (both sides)',
          'More pressure supports the carcass and evens the tread.',
          'Slightly smaller contact patch when cold.',
          'middle_vs_edges rises toward 0.',
          'middle_vs_edges + late-stint deg slope.')]);
    }
  }

  // 7) Bottoming
  if (bottom && bottom.events_per_lap > 1.5) {
    add('Floor/splitter bottoming', 1.8 + bottom.events_per_lap / 3,
      `The front floor crushes to ~${fmt(bottom.min_front_rh_mm, 0)} mm ` +
      `${fmt(bottom.events_per_lap)}× per lap at speed — each strike stalls the floor ` +
      'and momentarily kills front downforce (felt as random high-speed understeer).', [
      prop('front_ride_height', +1, '1–2 mm',
        'Raising the front stops the strikes with minimal aero cost.',
        'Slightly less peak front downforce.',
        'Strikes go to ~0; high-speed balance becomes predictable.',
        'events_per_lap next stint.'),
      prop('front_bump', +1, 'one step stiffer',
        'Stiffer bump damping controls the crush without raising the static height.',
        'Harsher over kerbs.',
        'Same ride height, fewer strikes.',
        'events_per_lap + kerb behaviour.'),
      prop('front_spring', +1, 'one step stiffer',
        'Stiffer front springs hold the platform up under aero load.',
        'Less mechanical front grip in slow corners.',
        'Strikes stop; watch slow-corner understeer.',
        'events_per_lap + understeer z in low-speed corners.')]);
  }

  // 8) Knife-edge / inconsistency
  const nervous = corners.filter((c) => c.min_speed_var > 3.0 && c.nervousness > 4.0);
  if (nervous.length >= Math.max(1, corners.length >> 2)) {
    const w = worst(nervous, 'min_speed_var');
    const ev = 'Apex speed varies lap-to-lap by ' +
      w.map((c) => `±${fmt(c.min_speed_var)} km/h at corner ${c.corner}`).join(', ') +
      ' with busy steering — the window is too narrow to hit consistently over a stint.';
    add('Knife-edge balance (inconsistency)', 1 + Math.max(...nervous.map((c) => c.min_speed_var)) / 3, ev, [
      prop('front_arb', -1, 'one step softer',
        'A softer platform widens the operating window at a small ultimate-pace cost.',
        'Peak one-lap pace may drop slightly.',
        "min_speed_var shrinks; median lap improves even if best lap doesn't.",
        'Consistency (σ) and min_speed_var at the listed corners.'),
      prop('rear_wing', +1, 'one step',
        'Stability from aero is the cheapest consistency you can buy for a stint.',
        'Straight-line cost.',
        'Nervousness (steering reversals) drops.',
        'nervousness metric next stint.'),
      prop('front_rebound', -1, 'one step softer',
        'Softer front rebound keeps the front planted over mid-corner bumps.',
        'Slightly floatier turn-in.',
        'Less lap-to-lap variation at bumpy corners.',
        'min_speed_var at the same corners.')]);
  }

  // 9) Entry instability (proxy fallback)
  if (!lockR.length) {
    const entryLoose = corners.filter((c) => c.oversteer_frac > 0.10 && (c.understeer_z || 0) < 0);
    if (entryLoose.length >= Math.max(1, Math.floor(corners.length / 3))) {
      add('Instability on corner entry', 1.8,
        `${entryLoose.length} corners rotate beyond driver input during braking/entry.`, [
        prop('brake_bias', +1, '0.5% forward',
          'Forward bias calms rear rotation under braking.',
          'Longer braking zones if you lock fronts instead.',
          'Entry counter-steer drops.',
          'oversteer_frac at entry-heavy corners + front_lock_frac.'),
        prop('diff_coast', +1, 'one step more coast lock',
          'More coast lock stabilizes the rear axle off-throttle.',
          'More entry understeer in slow corners.',
          'Car tows straighter into corners.',
          'Entry counter-steer events.'),
        prop('rear_toe', +1, 'a little more toe-in',
          'Rear toe-in adds straight-line and entry stability.',
          'Scrubs speed and heats rear tires.',
          'Calmer entries; watch rear temps.',
          'Rear tire temps + entry stability.')]);
    }
  }

  findings.sort((a, b) => b.severity - a.severity);
  return findings;
}

export function summarize(findings, recurrence = null) {
  const agg = new Map();
  for (const f of findings) {
    for (const p of f.proposals) {
      const key = `${p.knob}|${p.direction}`;
      if (!agg.has(key)) {
        agg.set(key, {
          knob: p.knob, direction: p.direction, size: p.size,
          symptoms: [], score: 0, current: p.current, learned: p.learned || null,
        });
      }
      const a = agg.get(key);
      a.symptoms.push(f.symptom);
      const conf = (p.learned || {}).conf ?? 0.5;
      a.score += f.severity * (0.5 + conf);
      if (p.learned && ((a.learned || {}).tries || 0) < p.learned.tries) a.learned = p.learned;
    }
  }
  const out = [];
  for (const a of agg.values()) {
    const rec = recurrence ? recurrence[`${a.knob}|${a.direction}`] : null;
    if (rec) {
      a.recurrence = rec;
      a.score *= 1 + Math.min(rec.hits / Math.max(rec.stints, 1), 1) * 0.5;
    }
    a.n_findings = a.symptoms.length;
    if (a.n_findings > 1) a.score *= 1 + 0.25 * (a.n_findings - 1);
    out.push(a);
  }
  out.sort((x, y) => y.score - x.score);
  return out.slice(0, 5);
}

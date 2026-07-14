// Corner-level and stint-level analysis — port of core/analysis.py.
// All balance metrics are self-normalizing (each lap vs the driver's own
// median through each corner), so any car works without geometry constants.

import { median, mean, std, min as amin, max as amax, percentile, slope } from './mathutil.js';
import { representativeLaps } from './stints.js';
import * as wheels from './wheels.js';

const G = 9.81;

export function detectCorners(ibt, laps) {
  const lat = ibt.ch('LatAccel');
  const pct = ibt.ch('LapDistPct');
  if (!lat || !pct || !laps.length) return [];
  const tick = ibt.tickRate;

  const reps = representativeLaps(laps);
  const ref = (reps.length ? reps : laps).reduce((a, b) => (a.lap_time < b.lap_time ? a : b));
  const s = ref.start, e = ref.end;
  const n = e - s;

  // ~0.25 s box smooth
  const k = Math.max(3, Math.round(tick * 0.25));
  const latS = new Float64Array(n);
  let acc = 0;
  const half = Math.floor(k / 2);
  for (let i = 0; i < n; i++) {
    acc += lat[s + i];
    if (i >= k) acc -= lat[s + i - k];
    if (i >= k - 1) latS[i - half] = acc / k;
  }
  for (let i = 0; i < half; i++) { latS[i] = latS[half]; latS[n - 1 - i] = latS[n - 1 - half]; }

  const absLat = Array.from(latS, Math.abs);
  const thresh = Math.max(0.35 * G, 0.30 * percentile(absLat, 98));

  const corners = [];
  let i = 0;
  while (i < n) {
    if (Math.abs(latS[i]) <= thresh) { i++; continue; }
    let j = i;
    while (j < n && Math.abs(latS[j]) > thresh) j++;
    if (j - i >= tick * 0.7) {
      let apex = i, best = 0;
      for (let m = i; m < j; m++) {
        if (Math.abs(latS[m]) > best) { best = Math.abs(latS[m]); apex = m; }
      }
      corners.push({
        pct_in: pct[s + i], pct_apex: pct[s + apex],
        pct_out: pct[s + Math.min(j, n - 1)],
        direction: latS[apex] > 0 ? 'left' : 'right',
      });
    }
    i = j;
  }
  corners.forEach((c, idx) => { c.id = idx + 1; });
  return corners;
}

function cornerMetrics(ibt, lap, corner) {
  const pct = ibt.ch('LapDistPct');
  const lat = ibt.ch('LatAccel');
  const steer = ibt.ch('SteeringWheelAngle');
  const yaw = ibt.ch('YawRate');
  const spd = ibt.ch('Speed');
  const thr = ibt.ch('Throttle');
  const brk = ibt.ch('Brake');
  if (!pct || !lat || !steer || !spd) return null;
  const tick = ibt.tickRate;
  const lo = corner.pct_in, ap = corner.pct_apex, hi = corner.pct_out;

  const latAll = [], steerAll = [], spdAll = [], yawAll = [];
  const thrExit = [], latExit = [], stExit = [], brkIn = [];
  for (let i = lap.start; i < lap.end; i++) {
    const p = pct[i];
    if (p < lo || p > hi) continue;
    latAll.push(lat[i]); steerAll.push(steer[i]); spdAll.push(spd[i]);
    if (yaw) yawAll.push(yaw[i]);
    if (p >= ap) {
      if (thr) { thrExit.push(thr[i]); latExit.push(lat[i]); stExit.push(steer[i]); }
    } else if (brk) {
      brkIn.push(brk[i]);
    }
  }
  if (latAll.length < 5) return null;

  const m = {};
  m.min_speed = amin(spdAll);
  m.peak_lat_g = amax(latAll.map(Math.abs)) / G;

  const absSteer = mean(steerAll.map(Math.abs));
  if (yaw) {
    m.steer_per_yaw = absSteer / (mean(yawAll.map(Math.abs)) + 1e-6);
  } else {
    const denom = mean(latAll.map((v, idx) => Math.abs(v) / Math.max(spdAll[idx], 5))) + 1e-6;
    m.steer_per_yaw = absSteer / denom;
  }

  let loaded = 0, opposing = 0;
  for (let i = 0; i < latAll.length; i++) {
    if (Math.abs(latAll[i]) > 0.3 * G) {
      loaded++;
      if (Math.sign(steerAll[i]) !== Math.sign(latAll[i]) && Math.abs(steerAll[i]) > 0.03) opposing++;
    }
  }
  m.counter_steer_frac = loaded ? opposing / loaded : 0;

  if (steerAll.length > 3) {
    let reversals = 0;
    let prevSign = Math.sign(steerAll[1] - steerAll[0]);
    for (let i = 2; i < steerAll.length; i++) {
      const sgn = Math.sign(steerAll[i] - steerAll[i - 1]);
      if (sgn !== 0 && prevSign !== 0 && sgn !== prevSign) reversals++;
      if (sgn !== 0) prevSign = sgn;
    }
    m.steer_reversals = reversals / (steerAll.length / tick);
  } else {
    m.steer_reversals = 0;
  }

  if (thr && thrExit.length > 5) {
    m.exit_throttle_avg = mean(thrExit);
    let le = 0, opp = 0;
    for (let i = 0; i < latExit.length; i++) {
      if (Math.abs(latExit[i]) > 0.25 * G) {
        le++;
        if (Math.sign(stExit[i]) !== Math.sign(latExit[i])) opp++;
      }
    }
    m.exit_counter_frac = le ? opp / le : 0;
  }
  if (brk && brkIn.length > 5) m.entry_brake_avg = mean(brkIn);
  return m;
}

export function analyzeStint(ibt, stint, corners) {
  const laps = representativeLaps(stint.laps);
  if (laps.length < 3 || !corners.length) return null;

  const lapTimes = laps.map((l) => l.lap_time);
  const degPerLap = slope(lapTimes);
  const pct = ibt.ch('LapDistPct');

  const perCorner = [];
  for (const c of corners) {
    const rows = laps.map((l) => cornerMetrics(ibt, l, c)).filter(Boolean);
    if (rows.length < 3) continue;
    const half = Math.max(1, rows.length >> 1);
    const col = (key) => rows.map((r) => r[key] ?? 0);

    const slipRows = laps.map((l) => wheels.slipMetrics(ibt, l, pct, c)).filter(Boolean);
    const wheelStats = {};
    if (slipRows.length) {
      for (const key of ['front_lock_frac', 'rear_lock_frac', 'abs_frac', 'wheelspin_frac']) {
        const vals = slipRows.filter((r) => key in r).map((r) => r[key]);
        if (vals.length) wheelStats[key] = median(vals);
      }
    }

    const spy = col('steer_per_yaw');
    const csf = col('counter_steer_frac');
    const ms = col('min_speed');
    const minKph = median(ms) * 3.6;

    perCorner.push({
      ...wheelStats,
      corner: c.id, pct_apex: c.pct_apex, direction: c.direction,
      speed_class: minKph > 170 ? 'high' : minKph < 110 ? 'low' : 'medium',
      min_speed_kph: minKph,
      min_speed_var: std(ms) * 3.6,
      understeer: median(spy),
      understeer_drift: (median(spy.slice(half)) - median(spy.slice(0, half))) / (median(spy.slice(0, half)) + 1e-6),
      oversteer_frac: median(csf),
      oversteer_drift: median(csf.slice(half)) - median(csf.slice(0, half)),
      nervousness: median(col('steer_reversals')),
      exit_counter: rows[0].exit_counter_frac !== undefined ? median(col('exit_counter_frac')) : 0,
    });
  }
  if (!perCorner.length) return null;

  const und = perCorner.map((c) => c.understeer);
  const mu = mean(und), sd = std(und) + 1e-6;
  for (const c of perCorner) c.understeer_z = (c.understeer - mu) / sd;

  const platform = {
    roll_couple_front: wheels.rollCouple(ibt, laps),
    bottoming: wheels.bottoming(ibt, laps),
    tires: wheels.tireThermals(ibt, laps),
    brakes: wheels.brakeBiasEvidence(ibt, laps),
  };

  return {
    platform,
    n_laps_used: laps.length,
    n_laps_total: stint.n_laps,
    best_lap: amin(lapTimes),
    median_lap: median(lapTimes),
    consistency: std(lapTimes),
    deg_per_lap: degPerLap,
    fuel_used: stint.fuel_used,
    lap_times: lapTimes,
    lap_nums: laps.map((l) => l.lap_num),
    corners: perCorner,
  };
}

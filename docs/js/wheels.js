// Per-wheel telemetry analysis — port of core/wheels.py. Channel-guarded.

import { median, min as amin, percentile } from './mathutil.js';

const G = 9.81;
const KPA_TO_PSI = 0.145038;

export function hasWheelSpeeds(ibt) {
  return ['LF', 'RF', 'LR', 'RR'].every((w) => ibt.ch(`${w}speed`));
}

export function slipMetrics(ibt, lap, pct, corner) {
  const spd = ibt.ch('Speed');
  const brk = ibt.ch('Brake');
  const thr = ibt.ch('Throttle');
  if (!spd || !hasWheelSpeeds(ibt)) return null;
  const { start: s, end: e } = lap;
  const lo = corner.pct_in, ap = corner.pct_apex, hi = corner.pct_out;

  const out = {};
  if (brk) {
    const fL = ibt.ch('LFspeed'), fR = ibt.ch('RFspeed');
    const rL = ibt.ch('LRspeed'), rR = ibt.ch('RRspeed');
    let nb = 0, fLock = 0, rLock = 0, absOn = 0;
    const absCh = ibt.ch('BrakeABSactive');
    for (let i = s; i < e; i++) {
      if (pct[i] < lo || pct[i] > ap) continue;
      if (brk[i] <= 0.25 || spd[i] <= 8) continue;
      nb++;
      if (Math.min(fL[i], fR[i]) < 0.82 * spd[i]) fLock++;
      if (Math.min(rL[i], rR[i]) < 0.82 * spd[i]) rLock++;
      if (absCh && absCh[i] > 0.5) absOn++;
    }
    if (nb > 3) {
      out.front_lock_frac = fLock / nb;
      out.rear_lock_frac = rLock / nb;
      if (absCh) out.abs_frac = absOn / nb;
    }
  }
  if (thr) {
    const rL = ibt.ch('LRspeed'), rR = ibt.ch('RRspeed');
    let nd = 0, spin = 0;
    for (let i = s; i < e; i++) {
      if (pct[i] < ap || pct[i] > hi) continue;
      if (thr[i] <= 0.4 || spd[i] <= 8) continue;
      nd++;
      if (Math.max(rL[i], rR[i]) > 1.06 * spd[i]) spin++;
    }
    if (nd > 3) out.wheelspin_frac = spin / nd;
  }
  return Object.keys(out).length ? out : null;
}

export function rollCouple(ibt, laps) {
  const defl = {};
  for (const w of ['LF', 'RF', 'LR', 'RR']) {
    defl[w] = ibt.ch(`${w}shockDefl`);
    if (!defl[w]) return null;
  }
  const lat = ibt.ch('LatAccel');
  if (!lat) return null;
  const tick = ibt.tickRate;
  const fronts = [], rears = [];
  for (const lap of laps) {
    const f = [], r = [];
    for (let i = lap.start; i < lap.end; i++) {
      if (Math.abs(lat[i]) <= 0.6 * G) continue;
      f.push(Math.abs(defl.LF[i] - defl.RF[i]));
      r.push(Math.abs(defl.LR[i] - defl.RR[i]));
    }
    if (f.length < tick) continue;
    fronts.push(median(f));
    rears.push(median(r));
  }
  if (!fronts.length) return null;
  const fm = median(fronts), rm = median(rears);
  return fm / (fm + rm + 1e-9);
}

export function bottoming(ibt, laps) {
  const rhLF = ibt.ch('LFrideHeight'), rhRF = ibt.ch('RFrideHeight');
  const spd = ibt.ch('Speed');
  if (!rhLF || !rhRF || !spd) return null;
  const tick = ibt.tickRate;
  const STRIKE_M = 0.012;
  let events = 0, totalS = 0;
  const mins = [];
  for (const lap of laps) {
    let valid = 0, lapMin = Infinity, prevNear = false;
    for (let i = lap.start; i < lap.end; i++) {
      const front = Math.min(rhLF[i], rhRF[i]);
      const ok = front > 0 && front < 0.30 && spd[i] > 30;
      if (!ok) { prevNear = false; continue; }
      valid++;
      if (front < lapMin) lapMin = front;
      const near = front < STRIKE_M;
      if (near && !prevNear) events++;
      prevNear = near;
    }
    if (valid < tick) continue;
    totalS += valid / tick;
    mins.push(lapMin);
  }
  if (totalS === 0) return null;
  return { events_per_lap: events / Math.max(laps.length, 1), min_front_rh_mm: amin(mins) * 1000 };
}

export function tireThermals(ibt, laps) {
  const lat = ibt.ch('LatAccel');
  if (!lat) return null;
  const tick = ibt.tickRate;
  const out = {};
  for (const [w, innerIs] of [['LF', 'R'], ['LR', 'R'], ['RF', 'L'], ['RR', 'L']]) {
    const tl = ibt.ch(`${w}tempL`), tm = ibt.ch(`${w}tempM`), tr = ibt.ch(`${w}tempR`);
    if (!tl || !tm || !tr) continue;
    const wantPositive = w.startsWith('R');   // +LatAccel = left turn -> loads RIGHT tires
    const sl = [], sm = [], sr = [];
    for (const lap of laps) {
      const ll = [], mm = [], rr = [];
      for (let i = lap.start; i < lap.end; i++) {
        const loaded = wantPositive ? lat[i] > 0.7 * G : lat[i] < -0.7 * G;
        if (!loaded || tm[i] <= 45) continue;
        ll.push(tl[i]); mm.push(tm[i]); rr.push(tr[i]);
      }
      if (ll.length < tick * 0.5) continue;
      sl.push(median(ll)); sm.push(median(mm)); sr.push(median(rr));
    }
    if (sl.length < 3) continue;
    const L = median(sl), M = median(sm), R = median(sr);
    const [inner, outer] = innerIs === 'R' ? [R, L] : [L, R];
    const rec = {
      inner, middle: M, outer,
      camber_delta: inner - outer,
      middle_vs_edges: M - (inner + outer) / 2,
    };
    const press = ibt.ch(`${w}pressure`);
    if (press) {
      const first = laps[0], last = laps[laps.length - 1];
      const pStart = median(press.subarray(first.start, first.end));
      const pEnd = median(press.subarray(last.start, last.end));
      rec.pressure_build_psi = (pEnd - pStart) * KPA_TO_PSI;
      rec.hot_pressure_psi = pEnd * KPA_TO_PSI;
    }
    out[w] = rec;
  }
  return Object.keys(out).length ? out : null;
}

export function brakeBiasEvidence(ibt, laps) {
  const lf = ibt.ch('LFbrakeLinePress'), rf = ibt.ch('RFbrakeLinePress');
  const lr = ibt.ch('LRbrakeLinePress'), rr = ibt.ch('RRbrakeLinePress');
  const brk = ibt.ch('Brake');
  if (!lf || !rf || !lr || !rr || !brk) return null;
  const s = laps[0].start, e = laps[laps.length - 1].end;
  const shares = [];
  for (let i = s; i < e; i++) {
    if (brk[i] <= 0.5) continue;
    const f = (lf[i] + rf[i]) / 2;
    const r = (lr[i] + rr[i]) / 2;
    shares.push(f / (f + r + 1e-9));
  }
  if (shares.length < 30) return null;
  const dc = ibt.ch('dcBrakeBias');
  return {
    front_share_pct: median(shares) * 100,
    dial: dc ? median(dc.subarray(s, e)) : null,
  };
}

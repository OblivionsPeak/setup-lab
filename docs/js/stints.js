// Lap/stint segmentation — port of core/stints.py.

const ON_TRACK = 3;

export function segmentLaps(ibt) {
  const lap = ibt.ch('Lap');
  const tick = ibt.tickRate;
  if (!lap || lap.length < tick * 30) return [];
  const n = lap.length;
  const fuel = ibt.ch('FuelLevel');
  const onPit = ibt.ch('OnPitRoad');
  const surface = ibt.ch('PlayerTrackSurface');
  const lapTimeCh = ibt.ch('LapLastLapTime');

  const boundaries = [];
  for (let i = 1; i < n; i++) if (lap[i] > lap[i - 1]) boundaries.push(i);
  const starts = [0, ...boundaries];
  const ends = [...boundaries, n];

  const laps = [];
  for (let k = 0; k < starts.length; k++) {
    const s = starts[k], e = ends[k];
    if (e - s < tick * 20) continue;               // < 20 s — fragment / tow
    const dur = (e - s) / tick;
    let lt = 0, timed = false;
    if (lapTimeCh && e < n) {
      const stop = Math.min(n, e + tick * 5);
      for (let i = e; i < stop; i++) {
        if (lapTimeCh[i] > 5) { lt = lapTimeCh[i]; timed = true; break; }
      }
    }
    if (!timed) {
      if (e >= n - 2) continue;                    // file ends inside this lap
      lt = dur;
    }
    let pitted = false;
    if (onPit) for (let i = s; i < e; i++) if (onPit[i] > 0.5) { pitted = true; break; }
    let off = 0;
    if (surface) {
      let cnt = 0;
      for (let i = s; i < e; i++) if (surface[i] !== ON_TRACK) cnt++;
      off = cnt / (e - s);
    }
    laps.push({
      lap_num: lap[s] + 1, start: s, end: e, lap_time: lt,
      fuel_start: fuel ? fuel[s] : 0, fuel_end: fuel ? fuel[e - 1] : 0,
      pitted, offtrack_frac: off,
    });
  }
  return laps;
}

export function segmentStints(laps, minLaps = 3) {
  const stints = [];
  let current = [];
  let prevFuelEnd = null;
  for (const lap of laps) {
    const refueled = prevFuelEnd !== null && lap.fuel_start > prevFuelEnd + 1.0;
    if (lap.pitted || refueled) {
      if (current.length >= minLaps) stints.push(current);
      current = [];
    } else {
      current.push(lap);
    }
    prevFuelEnd = lap.fuel_end;
  }
  if (current.length >= minLaps) stints.push(current);

  return stints.map((group, i) => ({
    stint_num: i + 1, laps: group, n_laps: group.length,
    fuel_used: group[0].fuel_start - group[group.length - 1].fuel_end,
  }));
}

export function representativeLaps(stintLaps, maxOfftrack = 0.02) {
  const clean = stintLaps.filter((l) => l.offtrack_frac <= maxOfftrack);
  if (clean.length < 3) return clean;
  const times = clean.map((l) => l.lap_time).sort((a, b) => a - b);
  const med = times[Math.floor(times.length / 2)];
  const keep = clean.filter((l) => l.lap_time < med * 1.03);
  return keep.length >= 3 ? keep : clean;
}

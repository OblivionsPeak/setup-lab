"""Segment telemetry into laps and fuel stints, filter to representative laps."""
import numpy as np

# irsdk_TrkLoc: 3 = on track
ON_TRACK = 3


def _ch(channels, *names):
    for n in names:
        if n in channels:
            return np.asarray(channels[n], dtype=float)
    return None


def segment_laps(channels, tick_rate):
    """Returns list of lap dicts with tick ranges, lap time, fuel, pit/offtrack flags."""
    lap_ch = _ch(channels, 'Lap')
    if lap_ch is None or len(lap_ch) < tick_rate * 30:
        return []
    n = len(lap_ch)
    fuel = _ch(channels, 'FuelLevel')
    on_pit = _ch(channels, 'OnPitRoad')
    surface = _ch(channels, 'PlayerTrackSurface')
    lap_time_ch = _ch(channels, 'LapLastLapTime')

    laps = []
    boundaries = np.flatnonzero(np.diff(lap_ch) > 0) + 1
    starts = np.concatenate(([0], boundaries))
    ends = np.concatenate((boundaries, [n]))

    for s, e in zip(starts, ends):
        if e - s < tick_rate * 20:          # < 20 s — out-lap fragment / tow
            continue
        dur = (e - s) / tick_rate
        # authoritative lap time appears in LapLastLapTime just after the boundary
        lt, timed = 0.0, False
        if lap_time_ch is not None and e < n:
            probe = lap_time_ch[e: min(n, e + tick_rate * 5)]
            good = probe[probe > 5]
            if len(good):
                lt, timed = float(good[0]), True
        if not timed:
            if e >= n - 2:      # file ends at/inside this lap — no trustworthy time
                continue
            lt = dur
        pitted = bool(on_pit is not None and np.any(on_pit[s:e] > 0.5))
        off = 0.0
        if surface is not None:
            off = float(np.mean(surface[s:e] != ON_TRACK))
        laps.append({
            'lap_num': int(lap_ch[s]) + 1,
            'start': int(s), 'end': int(e),
            'lap_time': lt,
            'fuel_start': float(fuel[s]) if fuel is not None else 0.0,
            'fuel_end': float(fuel[e - 1]) if fuel is not None else 0.0,
            'pitted': pitted,
            'offtrack_frac': off,
        })
    return laps


def segment_stints(laps, min_laps=3):
    """Group consecutive non-pit laps into stints. A pit lap (or fuel jump) ends a stint."""
    stints, current = [], []
    prev_fuel_end = None
    for lap in laps:
        refueled = prev_fuel_end is not None and lap['fuel_start'] > prev_fuel_end + 1.0
        if lap['pitted'] or refueled:
            if len(current) >= min_laps:
                stints.append(current)
            current = []
        else:
            current.append(lap)
        prev_fuel_end = lap['fuel_end']
    if len(current) >= min_laps:
        stints.append(current)

    out = []
    for i, group in enumerate(stints):
        out.append({
            'stint_num': i + 1,
            'laps': group,
            'n_laps': len(group),
            'fuel_used': group[0]['fuel_start'] - group[-1]['fuel_end'],
        })
    return out


def representative_laps(stint_laps, max_offtrack=0.02):
    """Clean racing laps only: drop offtracks and statistical outliers (spins, traffic)."""
    clean = [l for l in stint_laps if l['offtrack_frac'] <= max_offtrack]
    if len(clean) < 3:
        return clean
    times = np.array([l['lap_time'] for l in clean])
    med = np.median(times)
    keep = [l for l, t in zip(clean, times) if t < med * 1.03]
    return keep if len(keep) >= 3 else clean

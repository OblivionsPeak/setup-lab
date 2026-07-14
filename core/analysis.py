"""Corner-level and stint-level analysis.

All balance metrics are self-normalizing: each lap's per-corner behaviour is
compared against the driver's own median across the stint, so the analysis
works on any car without car-specific geometry constants.
"""
import numpy as np
from .stints import representative_laps
from . import wheels

G = 9.81


def _ch(channels, *names):
    for n in names:
        if n in channels:
            return np.asarray(channels[n], dtype=float)
    return None


# ── Corner detection ─────────────────────────────────────────────────────────

def detect_corners(channels, laps, tick_rate):
    """Find corners from lateral G vs LapDistPct using the fastest clean lap as reference.

    Returns list of {id, pct_in, pct_apex, pct_out, direction}.
    """
    lat = _ch(channels, 'LatAccel')
    pct = _ch(channels, 'LapDistPct')
    if lat is None or pct is None or not laps:
        return []

    ref = min(representative_laps(laps) or laps, key=lambda l: l['lap_time'])
    s, e = ref['start'], ref['end']
    lat_l, pct_l = lat[s:e], pct[s:e]

    # smooth ~0.25 s
    k = max(3, int(tick_rate * 0.25))
    kern = np.ones(k) / k
    lat_s = np.convolve(lat_l, kern, mode='same')

    thresh = max(0.35 * G, 0.30 * np.percentile(np.abs(lat_s), 98))
    in_corner = np.abs(lat_s) > thresh

    corners, i, n = [], 0, len(in_corner)
    while i < n:
        if not in_corner[i]:
            i += 1
            continue
        j = i
        while j < n and in_corner[j]:
            j += 1
        if (j - i) >= tick_rate * 0.7:                      # ≥ 0.7 s of sustained load
            seg = lat_s[i:j]
            apex = i + int(np.argmax(np.abs(seg)))
            corners.append({
                'pct_in': float(pct_l[i]),
                'pct_apex': float(pct_l[apex]),
                'pct_out': float(pct_l[min(j, n - 1)]),
                'direction': 'left' if seg[np.argmax(np.abs(seg))] > 0 else 'right',
            })
        i = j

    # merge corners whose gaps are tiny (chicane halves stay separate, kinks merge)
    for idx, c in enumerate(corners):
        c['id'] = idx + 1
    return corners


# ── Per-lap, per-corner metrics ──────────────────────────────────────────────

def _lap_slice(channels_name_arr, lap, pct, lo, hi):
    s, e = lap['start'], lap['end']
    p = pct[s:e]
    mask = (p >= lo) & (p <= hi)
    return channels_name_arr[s:e][mask] if np.any(mask) else np.array([])


def corner_metrics(channels, lap, corner, tick_rate):
    """Metrics for one lap through one corner. Phases: entry (in→apex), exit (apex→out)."""
    pct = _ch(channels, 'LapDistPct')
    lat = _ch(channels, 'LatAccel')
    steer = _ch(channels, 'SteeringWheelAngle')
    yaw = _ch(channels, 'YawRate')
    spd = _ch(channels, 'Speed')
    thr = _ch(channels, 'Throttle')
    brk = _ch(channels, 'Brake')
    if any(x is None for x in (pct, lat, steer, spd)):
        return None

    lo, ap, hi = corner['pct_in'], corner['pct_apex'], corner['pct_out']
    m = {}

    def seg(arr, a, b):
        return _lap_slice(arr, lap, pct, a, b)

    lat_all = seg(lat, lo, hi)
    steer_all = seg(steer, lo, hi)
    spd_all = seg(spd, lo, hi)
    if len(lat_all) < 5:
        return None

    m['min_speed'] = float(np.min(spd_all))
    m['peak_lat_g'] = float(np.max(np.abs(lat_all))) / G

    # Understeer proxy: steering effort per unit of yaw response.
    # High steer with low speed-normalized yaw = front not answering.
    if yaw is not None:
        yaw_all = seg(yaw, lo, hi)
        denom = np.mean(np.abs(yaw_all)) + 1e-6
        m['steer_per_yaw'] = float(np.mean(np.abs(steer_all)) / denom)
    else:
        denom = np.mean(np.abs(lat_all) / np.maximum(spd_all, 5.0)) + 1e-6
        m['steer_per_yaw'] = float(np.mean(np.abs(steer_all)) / denom)

    # Oversteer proxy: counter-steer fraction — steering opposing lateral G while loaded.
    loaded = np.abs(lat_all) > 0.3 * G
    if np.any(loaded):
        opposing = np.sign(steer_all[loaded]) != np.sign(lat_all[loaded])
        m['counter_steer_frac'] = float(np.mean(opposing & (np.abs(steer_all[loaded]) > 0.03)))
    else:
        m['counter_steer_frac'] = 0.0

    # Steering busyness: reversal rate while cornering (nervous rear / knife-edge)
    if len(steer_all) > 3:
        d = np.diff(np.sign(np.diff(steer_all)))
        m['steer_reversals'] = float(np.count_nonzero(d) / (len(steer_all) / tick_rate))
    else:
        m['steer_reversals'] = 0.0

    # Exit traction: throttle applied vs lateral grip still demanded
    if thr is not None:
        thr_exit = seg(thr, ap, hi)
        lat_exit = seg(lat, ap, hi)
        st_exit = seg(steer, ap, hi)
        if len(thr_exit) > 5:
            m['exit_throttle_avg'] = float(np.mean(thr_exit))
            loaded_e = np.abs(lat_exit) > 0.25 * G
            if np.any(loaded_e) and st_exit is not None and len(st_exit) == len(lat_exit):
                opp = np.sign(st_exit[loaded_e]) != np.sign(lat_exit[loaded_e])
                m['exit_counter_frac'] = float(np.mean(opp))
            else:
                m['exit_counter_frac'] = 0.0

    # Entry stability under braking
    if brk is not None:
        brk_in = seg(brk, lo, ap)
        if len(brk_in) > 5:
            m['entry_brake_avg'] = float(np.mean(brk_in))

    return m


# ── Stint-level rollup ───────────────────────────────────────────────────────

def analyze_stint(channels, stint, corners, tick_rate):
    """Full stint analysis → degradation, balance drift, per-corner symptom table."""
    laps = representative_laps(stint['laps'])
    if len(laps) < 3 or not corners:
        return None

    lap_times = np.array([l['lap_time'] for l in laps])
    lap_idx = np.arange(len(laps))

    # Pace trend per lap. Within one stint, fuel load and lap index are collinear,
    # so tire deg can't be separated from fuel burn-off here — report the combined
    # trend honestly. Fuel burn makes the car FASTER each lap, so any positive
    # slope means degradation is already beating the fuel effect (a strong signal).
    slope = float(np.polyfit(lap_idx, lap_times, 1)[0])
    deg_per_lap = slope

    pct_ch = _ch(channels, 'LapDistPct')
    per_corner = []
    half = max(3, len(laps) // 2)
    for c in corners:
        rows = [corner_metrics(channels, l, c, tick_rate) for l in laps]
        rows = [r for r in rows if r]
        if len(rows) < 3:
            continue
        slip_rows = [wheels.slip_metrics(channels, l, pct_ch, c) for l in laps]
        slip_rows = [r for r in slip_rows if r]

        def col(key):
            return np.array([r.get(key, 0.0) for r in rows])

        spy = col('steer_per_yaw')
        csf = col('counter_steer_frac')
        rev = col('steer_reversals')
        ms = col('min_speed')

        min_kph = float(np.median(ms) * 3.6)
        wheel_stats = {}
        if slip_rows:
            for key in ('front_lock_frac', 'rear_lock_frac', 'abs_frac', 'wheelspin_frac'):
                vals = [r[key] for r in slip_rows if key in r]
                if vals:
                    wheel_stats[key] = float(np.median(vals))
        per_corner.append({
            **wheel_stats,
            'corner': c['id'],
            'pct_apex': c['pct_apex'],
            'direction': c['direction'],
            'speed_class': 'high' if min_kph > 170 else 'low' if min_kph < 110 else 'medium',
            'min_speed_kph': min_kph,
            'min_speed_var': float(np.std(ms) * 3.6),
            'understeer': float(np.median(spy)),
            'understeer_drift': float(np.median(spy[half:]) - np.median(spy[:half])) / (np.median(spy[:half]) + 1e-6),
            'oversteer_frac': float(np.median(csf)),
            'oversteer_drift': float(np.median(csf[half:]) - np.median(csf[:half])),
            'nervousness': float(np.median(rev)),
            'exit_counter': float(np.median(col('exit_counter_frac'))) if rows[0].get('exit_counter_frac') is not None else 0.0,
        })

    if not per_corner:
        return None

    # Normalize understeer across corners into z-scores so "worst corners" pop out.
    und = np.array([c['understeer'] for c in per_corner])
    mu, sd = np.mean(und), np.std(und) + 1e-6
    for c in per_corner:
        c['understeer_z'] = float((c['understeer'] - mu) / sd)

    # Whole-stint wheel-level measurements (each None if channels absent)
    platform = {
        'roll_couple_front': wheels.roll_couple(channels, laps, corners, pct_ch, tick_rate),
        'bottoming': wheels.bottoming(channels, laps, tick_rate),
        'tires': wheels.tire_thermals(channels, laps, tick_rate),
        'brakes': wheels.brake_bias_evidence(channels, laps),
    }

    return {
        'platform': platform,
        'n_laps_used': len(laps),
        'n_laps_total': stint['n_laps'],
        'best_lap': float(np.min(lap_times)),
        'median_lap': float(np.median(lap_times)),
        'consistency': float(np.std(lap_times)),
        'deg_per_lap': deg_per_lap,
        'fuel_used': stint['fuel_used'],
        'lap_times': [float(t) for t in lap_times],
        'lap_nums': [l['lap_num'] for l in laps],
        'corners': per_corner,
    }

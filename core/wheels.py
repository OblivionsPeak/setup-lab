"""Per-wheel telemetry analysis: slip, ABS, shocks, ride height, tire temps, pressures.

Everything here is channel-guarded — cars/files missing a channel simply skip
that metric, and the engine only fires rules whose evidence exists.
"""
import numpy as np

G = 9.81
KPA_TO_PSI = 0.145038


def _ch(channels, name):
    return np.asarray(channels[name], dtype=float) if name in channels else None


def has_wheel_speeds(channels):
    return all(f'{w}speed' in channels for w in ('LF', 'RF', 'LR', 'RR'))


def slip_metrics(channels, lap, pct, corner):
    """Lockup (braking) and wheelspin (exit) fractions for one lap through one corner."""
    spd = _ch(channels, 'Speed')
    brk = _ch(channels, 'Brake')
    thr = _ch(channels, 'Throttle')
    if spd is None or not has_wheel_speeds(channels):
        return None
    s, e = lap['start'], lap['end']
    p = pct[s:e]
    lo, ap, hi = corner['pct_in'], corner['pct_apex'], corner['pct_out']

    out = {}
    entry = (p >= lo) & (p <= ap)
    exit_ = (p >= ap) & (p <= hi)
    car = spd[s:e]

    if brk is not None and np.any(entry):
        braking = entry & (brk[s:e] > 0.25) & (car > 8)
        if np.count_nonzero(braking) > 3:
            fronts = np.minimum(_ch(channels, 'LFspeed')[s:e], _ch(channels, 'RFspeed')[s:e])
            rears = np.minimum(_ch(channels, 'LRspeed')[s:e], _ch(channels, 'RRspeed')[s:e])
            out['front_lock_frac'] = float(np.mean(fronts[braking] < 0.82 * car[braking]))
            out['rear_lock_frac'] = float(np.mean(rears[braking] < 0.82 * car[braking]))
            abs_ch = _ch(channels, 'BrakeABSactive')
            if abs_ch is not None:
                out['abs_frac'] = float(np.mean(abs_ch[s:e][braking] > 0.5))

    if thr is not None and np.any(exit_):
        driving = exit_ & (thr[s:e] > 0.4) & (car > 8)
        if np.count_nonzero(driving) > 3:
            rears_max = np.maximum(_ch(channels, 'LRspeed')[s:e], _ch(channels, 'RRspeed')[s:e])
            out['wheelspin_frac'] = float(np.mean(rears_max[driving] > 1.06 * car[driving]))
    return out or None


def roll_couple(channels, laps, corners, pct, tick_rate):
    """Measured front share of total roll (from shock deflections) while cornering.

    ~50% = balanced platform; higher = front carries more roll (understeer bias).
    """
    defl = {w: _ch(channels, f'{w}shockDefl') for w in ('LF', 'RF', 'LR', 'RR')}
    lat = _ch(channels, 'LatAccel')
    if any(v is None for v in defl.values()) or lat is None:
        return None
    fronts, rears = [], []
    for lap in laps:
        s, e = lap['start'], lap['end']
        loaded = np.abs(lat[s:e]) > 0.6 * G
        if np.count_nonzero(loaded) < tick_rate:
            continue
        f = np.abs(defl['LF'][s:e][loaded] - defl['RF'][s:e][loaded])
        r = np.abs(defl['LR'][s:e][loaded] - defl['RR'][s:e][loaded])
        fronts.append(np.median(f))
        rears.append(np.median(r))
    if not fronts:
        return None
    fm, rm = np.median(fronts), np.median(rears)
    return float(fm / (fm + rm + 1e-9))


def bottoming(channels, laps, tick_rate):
    """Front ride-height crush events at speed (splitter/floor strikes)."""
    rh_lf, rh_rf = _ch(channels, 'LFrideHeight'), _ch(channels, 'RFrideHeight')
    spd = _ch(channels, 'Speed')
    if rh_lf is None or rh_rf is None or spd is None:
        return None
    STRIKE_M = 0.012          # < 12 mm of front clearance at speed = floor contact zone
    events, total_s, mins = 0, 0.0, []
    for lap in laps:
        s, e = lap['start'], lap['end']
        front = np.minimum(rh_lf[s:e], rh_rf[s:e])
        valid = (front > 0) & (front < 0.30) & (spd[s:e] > 30)   # ride heights reset weirdly off-track
        if np.count_nonzero(valid) < tick_rate:
            continue
        near = valid & (front < STRIKE_M)
        events += int(np.count_nonzero(np.diff(near.astype(int)) == 1))
        total_s += np.count_nonzero(valid) / tick_rate
        mins.append(np.min(front[valid]))
    if total_s == 0:
        return None
    return {'events_per_lap': events / max(len(laps), 1),
            'min_front_rh_mm': float(np.min(mins) * 1000)}


def tire_thermals(channels, laps, tick_rate):
    """Surface-temp spreads (camber/pressure evidence) + hot-pressure build per tire.

    Temps are taken while each tire is the loaded (outside) tire in a corner.
    Convention: inner edge is toward the car centerline — for a LEFT tire the
    inner edge is the R sensor; for a RIGHT tire it's the L sensor.
    """
    lat = _ch(channels, 'LatAccel')
    if lat is None:
        return None
    out = {}
    for w, inner_is in (('LF', 'R'), ('LR', 'R'), ('RF', 'L'), ('RR', 'L')):
        tl, tm, tr = (_ch(channels, f'{w}temp{s}') for s in ('L', 'M', 'R'))
        if tl is None or tm is None or tr is None:
            continue
        # iRacing LatAccel: positive = left turn -> load on RIGHT tires
        want_positive = w.startswith('R')
        samp_l, samp_m, samp_r = [], [], []
        for lap in laps:
            s, e = lap['start'], lap['end']
            loaded = (lat[s:e] > 0.7 * G) if want_positive else (lat[s:e] < -0.7 * G)
            hot = tm[s:e] > 45          # ignore cold out-lap samples
            m = loaded & hot
            if np.count_nonzero(m) < tick_rate * 0.5:
                continue
            samp_l.append(np.median(tl[s:e][m]))
            samp_m.append(np.median(tm[s:e][m]))
            samp_r.append(np.median(tr[s:e][m]))
        if len(samp_l) < 3:
            continue
        L, M, R = float(np.median(samp_l)), float(np.median(samp_m)), float(np.median(samp_r))
        inner, outer = (R, L) if inner_is == 'R' else (L, R)
        rec = {'inner': inner, 'middle': M, 'outer': outer,
               'camber_delta': inner - outer,                 # +hot inner = typical; too high = excess camber
               'middle_vs_edges': M - (inner + outer) / 2}    # + = overinflated, - = underinflated
        press = _ch(channels, f'{w}pressure')
        if press is not None:
            p_start = np.median(press[laps[0]['start']:laps[0]['end']])
            p_end = np.median(press[laps[-1]['start']:laps[-1]['end']])
            rec['pressure_build_psi'] = float((p_end - p_start) * KPA_TO_PSI)
            rec['hot_pressure_psi'] = float(p_end * KPA_TO_PSI)
        out[w] = rec
    return out or None


def brake_bias_evidence(channels, laps):
    """Measured front brake-pressure share + the in-car bias dial value."""
    lf, rf = _ch(channels, 'LFbrakeLinePress'), _ch(channels, 'RFbrakeLinePress')
    lr, rr = _ch(channels, 'LRbrakeLinePress'), _ch(channels, 'RRbrakeLinePress')
    brk = _ch(channels, 'Brake')
    if any(x is None for x in (lf, rf, lr, rr, brk)):
        return None
    s, e = laps[0]['start'], laps[-1]['end']
    hard = brk[s:e] > 0.5
    if np.count_nonzero(hard) < 30:
        return None
    f = (lf[s:e][hard] + rf[s:e][hard]) / 2
    r = (lr[s:e][hard] + rr[s:e][hard]) / 2
    share = float(np.median(f / (f + r + 1e-9)))
    dc = _ch(channels, 'dcBrakeBias')
    return {'front_share_pct': share * 100,
            'dial': float(np.median(dc[s:e])) if dc is not None else None}

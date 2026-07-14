"""Rule-based recommendation engine.

Symptoms are extracted from stint analysis; each rule proposes adjustments only
for parameters that actually exist in this car's CarSetup block, so the engine
adapts to any car automatically. Learned confidence (from graded outcomes in
the store) reorders and reweights candidate adjustments over time.
"""
import re

# Fuzzy parameter matchers: canonical knob -> regex over flattened setup keys.
KNOBS = {
    'brake_bias':        r'brake.*bias|bias.*brake',
    'rear_wing':         r'rear.*wing|wing.*angle|rearwing',
    'front_wing':        r'front.*wing|front.*splitter|splitter',
    'front_arb':         r'front.*(arb|anti.?roll)|(arb|anti.?roll).*front',
    'rear_arb':          r'rear.*(arb|anti.?roll)|(arb|anti.?roll).*rear',
    'lf_pressure':       r'(left|l)f.*(cold|starting).*pressure|(cold|starting).*pressure.*lf',
    'rf_pressure':       r'(right|r)f.*(cold|starting).*pressure|(cold|starting).*pressure.*rf',
    'lr_pressure':       r'(left|l)r.*(cold|starting).*pressure|(cold|starting).*pressure.*lr',
    'rr_pressure':       r'(right|r)r.*(cold|starting).*pressure|(cold|starting).*pressure.*rr',
    'front_spring':      r'(lf|rf|front).*spring',
    'rear_spring':       r'(lr|rr|rear).*spring',
    'front_camber':      r'(lf|rf|front).*camber',
    'rear_camber':       r'(lr|rr|rear).*camber',
    'front_ride_height': r'(front|lf|rf).*ride.*height',
    'rear_ride_height':  r'(rear|lr|rr).*ride.*height',
    'diff_preload':      r'preload',
    'diff_coast':        r'coast.*ramp|coast.*lock',
    'diff_power':        r'(power|drive).*ramp|(power|drive).*lock|friction.*faces',
    'traction_control':  r'traction.*control|\btc\b',
    'front_toe':         r'(front|lf|rf).*toe|toe.*in',
    'rear_toe':          r'(lr|rr|rear).*toe',
    'cross_weight':      r'cross.*weight|wedge',
}


def match_knobs(setup: dict) -> dict:
    """{canonical_knob: [actual setup keys]} for knobs present on this car."""
    found = {}
    for knob, pat in KNOBS.items():
        rx = re.compile(pat, re.I)
        keys = [k for k in setup if rx.search(k.replace('.', ' '))]
        if keys:
            found[knob] = keys
    return found


# Each rule: symptom test over stint analysis -> proposals.
# Proposal: (knob, direction, size, rationale, tradeoff). direction: +1 raise / -1 lower.

def _worst(corners, key, hi=True, z_floor=None):
    pool = corners
    if z_floor is not None:
        pool = [c for c in corners if c.get('understeer_z', 0) >= z_floor] or corners
    return sorted(pool, key=lambda c: c[key], reverse=hi)[:3]


def diagnose(stint_a: dict, setup: dict) -> list:
    """Returns list of finding dicts: {symptom, severity, evidence, proposals:[...]}."""
    knobs = match_knobs(setup)
    corners = stint_a['corners']
    findings = []

    def prop(knob, direction, size, why, tradeoff):
        if knob not in knobs:
            return None
        return {'knob': knob, 'keys': knobs[knob], 'direction': direction,
                'size': size, 'why': why, 'tradeoff': tradeoff,
                'current': {k: setup[k] for k in knobs[knob]}}

    def add(symptom, severity, evidence, proposals):
        ps = [p for p in proposals if p]
        if ps:
            findings.append({'symptom': symptom, 'severity': float(severity),
                             'evidence': evidence, 'proposals': ps})

    # 1) Chronic understeer — corners with high understeer z-score from lap one.
    chronic = [c for c in corners if c['understeer_z'] > 1.0 and c['understeer_drift'] < 0.10]
    if len(chronic) >= max(1, len(corners) // 4):
        worst = _worst(chronic, 'understeer_z')
        ev = ('Front grip is short of the rear all stint, not just on worn tires. Worst at ' +
              ', '.join(f"corner {c['corner']} ({c['direction']}, apex {c['min_speed_kph']:.0f} km/h, "
                        f"understeer z={c['understeer_z']:+.1f})" for c in worst) + '.')
        add('Chronic mid-corner understeer', 2 + max(c['understeer_z'] for c in worst), ev, [
            prop('front_arb', -1, 'one step softer',
                 'Softer front anti-roll bar lets the outside front take more load mid-corner.',
                 'Slightly lazier initial turn-in response.'),
            prop('rear_arb', +1, 'one step stiffer',
                 'Stiffer rear bar rotates the car by taking rear lateral grip down a notch.',
                 'Less rear security on bumpy exits.'),
            prop('front_wing', +1, 'one step',
                 'More front aero directly adds front grip at speed.',
                 'Rear may become nervous in the fastest corners; pair with rear wing if so.'),
            prop('lf_pressure', -1, '0.3–0.7 psi (both fronts)',
                 'Lower cold front pressures grow the front contact patch.',
                 'Slower warm-up on out-laps; watch mid-stint pressures.'),
        ])

    # 2) Degradation-driven balance drift → rear wears faster (loose late stint).
    drifting_loose = [c for c in corners if c['oversteer_drift'] > 0.05]
    if len(drifting_loose) >= max(1, len(corners) // 4) and stint_a['deg_per_lap'] > 0.03:
        ev = (f'Pace fell {stint_a["deg_per_lap"]:.3f} s/lap despite the car getting lighter, and counter-steer '
              f'events grew in the second half of the stint at {len(drifting_loose)} corners — '
              'the rear tires are giving up faster than the fronts.')
        add('Rear degradation — car goes loose over the stint', 2 + 20 * stint_a['deg_per_lap'], ev, [
            prop('rr_pressure', -1, '0.3–0.5 psi (both rears)',
                 'Lower cold rear pressure reduces late-stint overheating of the rear carcass.',
                 'Marginally lazier response on lap 1–2.'),
            prop('rear_camber', +1, 'toward less negative by ~0.2°',
                 'Less rear camber spreads temperature across the tread and slows wear.',
                 'Small loss of peak rear lateral grip when tires are fresh.'),
            prop('rear_wing', +1, 'one step',
                 'More rear load supports the rear as the tires fade — the classic endurance trade.',
                 'Straight-line cost; expect a few km/h of trap speed.'),
            prop('diff_coast', -1, 'one step less coast lock',
                 'Less coast-side locking eases the rear on entry as grip fades.',
                 'Slightly more mid-corner rotation to manage.'),
        ])

    # 3) Chronic oversteer / nervous rear from the start.
    loose_now = [c for c in corners if c['oversteer_frac'] > 0.12 and c['oversteer_drift'] <= 0.05]
    if len(loose_now) >= max(1, len(corners) // 4):
        worst = _worst(loose_now, 'oversteer_frac')
        ev = ('Counter-steer corrections on fresh tires at ' +
              ', '.join(f"corner {c['corner']} ({100*c['oversteer_frac']:.0f}% of loaded samples)"
                        for c in worst) + ' — the platform is loose, not worn out.')
        add('Chronic oversteer', 2 + 10 * max(c['oversteer_frac'] for c in worst), ev, [
            prop('rear_arb', -1, 'one step softer',
                 'Softer rear bar adds rear lateral compliance and grip.',
                 'A touch more roll and slower transient response.'),
            prop('rear_wing', +1, 'one step',
                 'More rear downforce plants the rear in the quick stuff.',
                 'Straight-line speed cost.'),
            prop('front_arb', +1, 'one step stiffer',
                 'Balancing move: take a little front grip instead of adding rear.',
                 'Adds understeer in slow corners.'),
            prop('rear_spring', -1, 'one step softer',
                 'Softer rear springs improve mechanical rear grip, especially on kerbs/bumps.',
                 'Ride-height/floor contact — check rear ride height after.'),
        ])

    # 4) Corner-exit traction trouble.
    bad_exit = [c for c in corners if c.get('exit_counter', 0) > 0.10]
    if len(bad_exit) >= max(1, len(corners) // 5):
        worst = _worst(bad_exit, 'exit_counter')
        ev = ('Throttle-on counter-steer at ' +
              ', '.join(f"corner {c['corner']} ({100*c['exit_counter']:.0f}%)" for c in worst) +
              ' — the rear breaks traction as power goes down.')
        add('Poor corner-exit traction', 1.5 + 10 * max(c['exit_counter'] for c in worst), ev, [
            prop('diff_power', -1, 'one step less power-side lock',
                 'Less drive lock lets the inside rear slip instead of pushing the car sideways.',
                 'Can cost drive on long full-throttle exits.'),
            prop('traction_control', +1, 'one step (if class rules allow)',
                 'A click more TC trims wheelspin at the cost of almost nothing on exits this bad.',
                 'Over-reliance masks the mechanical problem.'),
            prop('rear_spring', -1, 'one step softer',
                 'More rear compliance = more traction under power.',
                 'Watch rear ride height under fuel load.'),
            prop('rr_pressure', -1, '0.3 psi (both rears)',
                 'Bigger rear contact patch on corner exit.',
                 'Slower warm-up.'),
        ])

    # 5) Knife-edge / inconsistent corners (setup too peaky).
    nervous = [c for c in corners if c['min_speed_var'] > 3.0 and c['nervousness'] > 4.0]
    if len(nervous) >= max(1, len(corners) // 4):
        worst = _worst(nervous, 'min_speed_var')
        ev = ('Apex speed varies lap-to-lap by ' +
              ', '.join(f"±{c['min_speed_var']:.1f} km/h at corner {c['corner']}" for c in worst) +
              ' with busy steering — the window is too narrow to hit consistently over a stint.')
        add('Knife-edge balance (inconsistency)', 1 + max(c['min_speed_var'] for c in worst) / 3, ev, [
            prop('front_arb', -1, 'one step softer',
                 'A softer platform widens the operating window at a small ultimate-pace cost.',
                 'Peak one-lap pace may drop slightly.'),
            prop('rear_wing', +1, 'one step',
                 'Stability from aero is the cheapest consistency you can buy for a stint.',
                 'Straight-line cost.'),
        ])

    # 6) Entry instability under braking.
    entry_loose = [c for c in corners if c['oversteer_frac'] > 0.10 and c.get('understeer_z', 0) < 0]
    if len(entry_loose) >= max(1, len(corners) // 3):
        add('Instability on corner entry', 1.8,
            f'{len(entry_loose)} corners show rotation beyond driver input during the braking/entry phase.', [
            prop('brake_bias', +1, '0.5% forward',
                 'Forward bias calms rear rotation under braking.',
                 'Longer braking zones if you lock fronts.'),
            prop('diff_coast', +1, 'one step more coast lock',
                 'More coast lock stabilizes the rear axle off-throttle.',
                 'More entry understeer in slow corners.'),
            prop('rear_toe', +1, 'a little more toe-in',
                 'Rear toe-in adds straight-line and entry stability.',
                 'Scrubs a little speed and heats rear tires.'),
        ])

    findings.sort(key=lambda f: -f['severity'])
    return findings

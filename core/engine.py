"""Rule-based recommendation engine (v2 — deep telemetry).

Symptoms come from stint analysis; each rule proposes adjustments only for
parameters that exist in this car's CarSetup block, so the engine adapts to
any car automatically. Where per-wheel channels exist (shocks, wheel speeds,
brake line pressures, live tire surface temps/pressures) rules cite measured
evidence instead of proxies. Speed-class splits separate aero problems from
mechanical ones. Learned confidence (graded outcomes) reorders proposals.
"""
import re

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
    'front_bump':        r'(lf|rf|front).*(bump|compression)',
    'rear_bump':         r'(lr|rr|rear).*(bump|compression)',
    'front_rebound':     r'(lf|rf|front).*rebound',
    'rear_rebound':      r'(lr|rr|rear).*rebound',
    'diff_preload':      r'preload',
    'diff_coast':        r'coast.*ramp|coast.*lock',
    'diff_power':        r'(power|drive).*ramp|(power|drive).*lock|friction.*faces',
    'traction_control':  r'traction.*control|\btc\b',
    'abs_setting':       r'\babs\b|anti.?lock',
    'brake_pressure':    r'brake.*pressure(?!.*bias)|master.*cyl',
    'front_toe':         r'(front|lf|rf).*toe|toe.*in',
    'rear_toe':          r'(lr|rr|rear).*toe',
    'cross_weight':      r'cross.*weight|wedge',
}


def match_knobs(setup: dict) -> dict:
    found = {}
    for knob, pat in KNOBS.items():
        rx = re.compile(pat, re.I)
        keys = [k for k in setup if rx.search(k.replace('.', ' '))]
        if keys:
            found[knob] = keys
    return found


def _worst(corners, key, n=3):
    return sorted([c for c in corners if key in c], key=lambda c: c[key], reverse=True)[:n]


def _by_class(corners, cls):
    return [c for c in corners if c.get('speed_class') == cls]


def diagnose(stint_a: dict, setup: dict) -> list:
    knobs = match_knobs(setup)
    corners = stint_a['corners']
    platform = stint_a.get('platform') or {}
    tires = platform.get('tires') or {}
    brakes = platform.get('brakes')
    roll_f = platform.get('roll_couple_front')
    bottom = platform.get('bottoming')
    findings = []

    def prop(knob, direction, size, why, tradeoff, expect='', verify=''):
        if knob not in knobs:
            return None
        return {'knob': knob, 'keys': knobs[knob], 'direction': direction,
                'size': size, 'why': why, 'tradeoff': tradeoff,
                'expect': expect, 'verify': verify,
                'current': {k: setup[k] for k in knobs[knob]}}

    def add(symptom, severity, evidence, proposals):
        ps = [p for p in proposals if p]
        if ps:
            findings.append({'symptom': symptom, 'severity': float(severity),
                             'evidence': evidence, 'proposals': ps})

    roll_note = ''
    if roll_f is not None:
        roll_note = f' Measured platform: the front carries {100*roll_f:.0f}% of total roll.'

    # ── 1a) Understeer in HIGH-speed corners → aero balance ─────────────────
    us_hi = [c for c in _by_class(corners, 'high') if c['understeer_z'] > 0.8]
    if us_hi:
        w = _worst(us_hi, 'understeer_z')
        ev = ('Front washes out specifically in the fast corners (' +
              ', '.join(f"corner {c['corner']} @ {c['min_speed_kph']:.0f} km/h" for c in w) +
              ') while slower corners are fine — that is an AERO balance problem, not mechanical.')
        add('Aero understeer (high-speed corners)', 2.5 + max(c['understeer_z'] for c in us_hi), ev, [
            prop('front_wing', +1, 'one step',
                 'More front aero moves the aero balance forward exactly where this shows up.',
                 'Can make the rear nervous in the same corners — change one step at a time.',
                 expect='Less steering needed at high-speed apexes; front-tire temps rise slightly.',
                 verify='Next stint: understeer z-score in high-speed corners should drop toward 0.'),
            prop('rear_wing', -1, 'one step',
                 'Trimming rear wing shifts balance forward and buys straight-line speed too.',
                 'Less rear stability everywhere, especially under braking from high speed.',
                 expect='Better rotation at speed + higher trap speed.',
                 verify='Watch entry stability into the fastest braking zone.'),
            prop('front_ride_height', -1, '1–2 mm lower',
                 'Lower front ride height increases front downforce (rake effect).',
                 'Bottoming risk — check for floor strikes after.',
                 expect='More front grip at speed with no drag penalty.',
                 verify='Bottoming events per lap must stay near zero.'),
        ])

    # ── 1b) Understeer in LOW/MEDIUM corners → mechanical ────────────────────
    us_lo = [c for c in corners if c.get('speed_class') != 'high'
             and c['understeer_z'] > 1.0 and c['understeer_drift'] < 0.10]
    if len(us_lo) >= max(1, len(corners) // 4):
        w = _worst(us_lo, 'understeer_z')
        ev = ('Mechanical understeer in slow/medium corners (' +
              ', '.join(f"corner {c['corner']} ({c['min_speed_kph']:.0f} km/h, z={c['understeer_z']:+.1f})"
                        for c in w) + ') where aero barely matters.' + roll_note)
        add('Mechanical understeer (slow/medium corners)', 2 + max(c['understeer_z'] for c in us_lo), ev, [
            prop('front_arb', -1, 'one step softer',
                 'Softer front bar lets the outside front take more load mid-corner.'
                 + (f' The front already carries {100*roll_f:.0f}% of roll — this directly rebalances it.'
                    if roll_f and roll_f > 0.54 else ''),
                 'Slightly lazier turn-in response.',
                 expect='More front grip from apex out in the slow stuff.',
                 verify='Understeer z at the listed corners; front roll share should drop a few points.'),
            prop('rear_arb', +1, 'one step stiffer',
                 'Stiffer rear bar rotates the car by trimming rear lateral grip.',
                 'Less rear security on bumpy exits and kerbs.',
                 expect='Sharper rotation; watch for new exit wheelspin.',
                 verify='Wheelspin fraction on exits must not grow.'),
            prop('diff_preload', -1, 'one step less',
                 'Less preload frees the car into and through slow corners.',
                 'Can add on-throttle snappiness in low gear.',
                 expect='Easier rotation at low speed.',
                 verify='Exit counter-steer fraction in slow corners.'),
            prop('lf_pressure', -1, '0.3–0.7 psi (both fronts)',
                 'Lower cold front pressures grow the front contact patch.',
                 'Slower warm-up on out-laps.',
                 expect='Front grip up slightly everywhere.',
                 verify='Front middle-vs-edge temp delta should move toward 0.'),
        ])

    # ── 2) Degradation-driven balance drift ─────────────────────────────────
    drifting_loose = [c for c in corners if c['oversteer_drift'] > 0.05]
    if len(drifting_loose) >= max(1, len(corners) // 4) and stint_a['deg_per_lap'] > 0.03:
        rear_hot = ''
        for w_ in ('LR', 'RR'):
            t = tires.get(w_)
            if t and t.get('pressure_build_psi', 0) > 1.5:
                rear_hot += f" {w_} hot pressure built +{t['pressure_build_psi']:.1f} psi over the stint."
        ev = (f'Pace fell {stint_a["deg_per_lap"]:.3f} s/lap despite the car getting lighter, and '
              f'counter-steer grew late-stint at {len(drifting_loose)} corners — the rear is giving up '
              f'faster than the front.{rear_hot}')
        add('Rear degradation — car goes loose over the stint', 2 + 20 * stint_a['deg_per_lap'], ev, [
            prop('rr_pressure', -1, '0.3–0.5 psi (both rears)',
                 'Lower cold rear pressure caps late-stint overheating of the rear carcass.',
                 'Marginally lazier response on laps 1–2.',
                 expect='Rear pressure build shrinks; balance drift flattens.',
                 verify='Rear pressure_build should come in under ~1.5 psi next stint.'),
            prop('rear_camber', +1, 'toward less negative by ~0.2°',
                 'Less rear camber spreads temperature across the tread and slows wear.',
                 'Small loss of peak rear grip on fresh tires.',
                 expect='Rear inner-edge temps drop; deg slope improves.',
                 verify='Rear camber_delta (inner−outer) should shrink.'),
            prop('rear_wing', +1, 'one step',
                 'More rear load supports the rear as tires fade — the classic endurance trade.',
                 'Straight-line cost; expect a few km/h of trap speed.',
                 expect='Late-stint oversteer drift shrinks.',
                 verify='oversteer_drift at the listed corners.'),
            prop('diff_coast', -1, 'one step less coast lock',
                 'Less coast-side locking eases the rear on entry as grip fades.',
                 'Slightly more mid-corner rotation to manage.',
                 expect='Entry feels calmer on worn tires.',
                 verify='Late-stint entry counter-steer events.'),
        ])

    # ── 3) Chronic oversteer ─────────────────────────────────────────────────
    loose_now = [c for c in corners if c['oversteer_frac'] > 0.12 and c['oversteer_drift'] <= 0.05]
    if len(loose_now) >= max(1, len(corners) // 4):
        w = _worst(loose_now, 'oversteer_frac')
        ev = ('Counter-steer on fresh tires at ' +
              ', '.join(f"corner {c['corner']} ({100*c['oversteer_frac']:.0f}%)" for c in w) +
              ' — the platform is loose, not worn out.' + roll_note)
        add('Chronic oversteer', 2 + 10 * max(c['oversteer_frac'] for c in loose_now), ev, [
            prop('rear_arb', -1, 'one step softer',
                 'Softer rear bar adds rear compliance and lateral grip.'
                 + (f' Front roll share is only {100*roll_f:.0f}% — the rear is doing too much of the work.'
                    if roll_f and roll_f < 0.46 else ''),
                 'A touch more roll, slower transients.',
                 expect='Counter-steer fraction drops at the listed corners.',
                 verify='oversteer_frac; also confirm no new understeer in slow corners.'),
            prop('rear_wing', +1, 'one step',
                 'More rear downforce plants the rear in the quick stuff.',
                 'Straight-line speed cost.',
                 expect='Biggest effect in medium/high-speed corners.',
                 verify='oversteer_frac split by speed class.'),
            prop('rear_spring', -1, 'one step softer',
                 'Softer rear springs improve mechanical rear grip, especially on kerbs.',
                 'Rear ride height drops under load — check for bottoming.',
                 expect='Calmer rear on bumps and kerbs.',
                 verify='Bottoming events must stay near zero.'),
            prop('front_arb', +1, 'one step stiffer',
                 'Balancing move: take a little front grip instead of adding rear.',
                 'Adds understeer in slow corners.',
                 expect='Overall balance shifts toward stable.',
                 verify='Watch understeer z in slow corners.'),
        ])

    # ── 4) Exit traction — now with measured wheelspin when available ────────
    spin_corners = [c for c in corners if c.get('wheelspin_frac', 0) > 0.08]
    proxy_corners = [c for c in corners if c.get('exit_counter', 0) > 0.10]
    bad_exit = spin_corners or proxy_corners
    if len(bad_exit) >= max(1, len(corners) // 5):
        if spin_corners:
            w = _worst(spin_corners, 'wheelspin_frac')
            ev = ('MEASURED rear wheelspin on exit at ' +
                  ', '.join(f"corner {c['corner']} ({100*c['wheelspin_frac']:.0f}% of throttle-on samples)"
                            for c in w) + ' — rear wheel speed exceeds car speed by 6%+.')
            sev = 2 + 12 * max(c['wheelspin_frac'] for c in spin_corners)
        else:
            w = _worst(proxy_corners, 'exit_counter')
            ev = ('Throttle-on counter-steer at ' +
                  ', '.join(f"corner {c['corner']} ({100*c['exit_counter']:.0f}%)" for c in w) +
                  ' — the rear breaks traction as power goes down.')
            sev = 1.5 + 10 * max(c['exit_counter'] for c in proxy_corners)
        add('Poor corner-exit traction', sev, ev, [
            prop('diff_power', -1, 'one step less power-side lock',
                 'Less drive lock lets the inside rear slip instead of lighting up both rears.',
                 'Can cost drive on long full-throttle exits.',
                 expect='Wheelspin fraction halves at the listed corners.',
                 verify='wheelspin_frac next stint.'),
            prop('rear_spring', -1, 'one step softer',
                 'More rear compliance = more traction under power.',
                 'Watch rear ride height under fuel load.',
                 expect='Better drive off slow corners especially.',
                 verify='wheelspin_frac in low-speed corners.'),
            prop('traction_control', +1, 'one step (if class rules allow)',
                 'A click more TC trims the worst of the wheelspin cheaply.',
                 'Masks the mechanical problem; try the diff first.',
                 expect='Immediate reduction in spin events.',
                 verify='Lap time should NOT get slower on exits (over-cut TC does).'),
            prop('rr_pressure', -1, '0.3 psi (both rears)',
                 'Bigger rear contact patch on corner exit.',
                 'Slower warm-up.',
                 expect='Small but free traction gain.',
                 verify='Rear middle-vs-edge temp delta.'),
        ])

    # ── 5) Braking: lockups / ABS — measured bias evidence ──────────────────
    lock_f = [c for c in corners if c.get('front_lock_frac', 0) > 0.10]
    lock_r = [c for c in corners if c.get('rear_lock_frac', 0) > 0.08]
    abs_heavy = [c for c in corners if c.get('abs_frac', 0) > 0.35]
    if lock_f or (abs_heavy and not lock_r):
        bias_note = ''
        if brakes:
            bias_note = f" Measured front line-pressure share: {brakes['front_share_pct']:.1f}%"
            if brakes.get('dial') is not None:
                bias_note += f" (bias dial {brakes['dial']:.1f})."
        w = _worst(lock_f or abs_heavy, 'front_lock_frac' if lock_f else 'abs_frac')
        ev = ('Front axle saturates under braking at ' +
              ', '.join(f"corner {c['corner']}" for c in w) +
              (f" — front wheels dip below 82% of car speed"
               if lock_f else ' — ABS intervenes on over a third of braking samples') +
              '.' + bias_note)
        add('Front lockups / ABS-limited braking', 2.2 + 5 * max(
            [c.get('front_lock_frac', 0) for c in lock_f] or [c.get('abs_frac', 0) * 0.5 for c in abs_heavy]), ev, [
            prop('brake_bias', -1, '0.5% rearward',
                 'Moving bias rearward uses more of the rear axle\'s braking capacity.',
                 'Too far = entry instability; move in 0.5% steps.',
                 expect='Front lock fraction drops; braking distances shorten.',
                 verify='front_lock_frac and entry oversteer_frac together.'),
            prop('brake_pressure', -1, 'a few % less master pressure',
                 'If you are ABS-limited everywhere, total pressure is past the grip ceiling.',
                 'Longer pedal travel feel.',
                 expect='ABS engagement fraction drops without losing decel.',
                 verify='abs_frac next stint.'),
            prop('front_camber', -1, '~0.2° more negative',
                 'More front camber adds braking-zone grip on the loaded edge into corners.',
                 'Slightly less straight-line braking contact.',
                 expect='Later braking into the worst corners.',
                 verify='front_lock_frac in the listed corners.'),
        ])
    if lock_r:
        w = _worst(lock_r, 'rear_lock_frac')
        ev = ('REAR wheels lock under braking at ' +
              ', '.join(f"corner {c['corner']} ({100*c['rear_lock_frac']:.0f}%)" for c in w) +
              ' — that is instability waiting to happen.' +
              (f" Measured front line-pressure share {brakes['front_share_pct']:.1f}%." if brakes else ''))
        add('Rear lockups under braking', 2.5 + 8 * max(c['rear_lock_frac'] for c in lock_r), ev, [
            prop('brake_bias', +1, '0.5% forward',
                 'Forward bias stops the rears locking before the fronts.',
                 'Slightly longer stopping distance if fronts saturate instead.',
                 expect='Rear lock events disappear; entry feels planted.',
                 verify='rear_lock_frac must go to ~0.'),
            prop('diff_coast', +1, 'one step more coast lock',
                 'More coast lock stabilizes the rear axle off-throttle.',
                 'More entry understeer in slow corners.',
                 expect='Calmer entries even before touching bias.',
                 verify='Entry counter-steer events.'),
        ])

    # ── 6) Tire temps: camber + pressure evidence per axle ──────────────────
    for axle, ws, cam_knob, press_knobs in (
            ('front', ('LF', 'RF'), 'front_camber', ('lf_pressure', 'rf_pressure')),
            ('rear', ('LR', 'RR'), 'rear_camber', ('lr_pressure', 'rr_pressure'))):
        recs = [tires[w] for w in ws if w in tires]
        if len(recs) < 2:
            continue
        cam = sum(r['camber_delta'] for r in recs) / 2
        mve = sum(r['middle_vs_edges'] for r in recs) / 2
        if cam > 18:
            add(f'Excess {axle} camber (inner edges running hot)', 1.6 + cam / 15,
                f'{axle.capitalize()} inner edges run {cam:.0f}°C hotter than outer while loaded '
                f'(healthy is ~8–15°C). The tread is not working evenly — pace and wear both suffer.', [
                prop(cam_knob, +1, '~0.2–0.4° less negative',
                     'Flattening camber puts the whole tread to work and cools the inner edge.',
                     'A little less peak mid-corner grip.',
                     expect=f'{axle} inner−outer delta moves toward 12°C.',
                     verify='camber_delta next stint.')])
        elif 0 < cam < 4:
            add(f'Not enough {axle} camber (tread too flat)', 1.4,
                f'{axle.capitalize()} inner and outer edges within {cam:.0f}°C while loaded — the tire '
                'is not leaning into its camber; mid-corner grip is being left on the table.', [
                prop(cam_knob, -1, '~0.2–0.3° more negative',
                     'More camber loads the tread properly when the car rolls onto it.',
                     'Slightly more inner-edge wear over very long runs.',
                     expect=f'{axle} camber_delta rises toward ~10°C; apex speeds up.',
                     verify='camber_delta + min corner speeds.')])
        if mve > 5:
            add(f'{axle.capitalize()} tires overinflated (center overheating)', 1.5 + mve / 5,
                f'{axle.capitalize()} tread centers run {mve:.0f}°C hotter than the edges — the tire is '
                'crowning on its center. Contact patch is smaller than it should be.', [
                prop(press_knobs[0], -1, '0.5–1.0 psi (both sides)',
                     'Lower cold pressure flattens the crown and restores full contact.',
                     'Slower warm-up; re-check hot pressures after.',
                     expect='middle_vs_edges falls toward 0–3°C.',
                     verify='middle_vs_edges next stint.')])
        elif mve < -5:
            add(f'{axle.capitalize()} tires underinflated (edges overheating)', 1.5 - mve / 5,
                f'{axle.capitalize()} tread centers run {-mve:.0f}°C cooler than the edges — the tire is '
                'folding onto its shoulders. Carcass is working too hard and will overheat late-stint.', [
                prop(press_knobs[0], +1, '0.5–1.0 psi (both sides)',
                     'More pressure supports the carcass and evens the tread.',
                     'Slightly smaller contact patch when cold.',
                     expect='middle_vs_edges rises toward 0.',
                     verify='middle_vs_edges + late-stint deg slope.')])

    # ── 7) Bottoming ─────────────────────────────────────────────────────────
    if bottom and bottom['events_per_lap'] > 1.5:
        add('Floor/splitter bottoming', 1.8 + bottom['events_per_lap'] / 3,
            f"The front floor crushes to ~{bottom['min_front_rh_mm']:.0f} mm "
            f"{bottom['events_per_lap']:.1f}× per lap at speed — each strike stalls the floor "
            'and momentarily kills front downforce (felt as random high-speed understeer).', [
            prop('front_ride_height', +1, '1–2 mm',
                 'Raising the front stops the strikes with minimal aero cost.',
                 'Slightly less peak front downforce.',
                 expect='Strikes go to ~0; high-speed balance becomes predictable.',
                 verify='events_per_lap next stint.'),
            prop('front_bump', +1, 'one step stiffer',
                 'Stiffer bump damping controls the crush without raising the static height.',
                 'Harsher over kerbs.',
                 expect='Same ride height, fewer strikes.',
                 verify='events_per_lap + kerb behaviour.'),
            prop('front_spring', +1, 'one step stiffer',
                 'Stiffer front springs hold the platform up under aero load.',
                 'Less mechanical front grip in slow corners.',
                 expect='Strikes stop; watch slow-corner understeer.',
                 verify='events_per_lap + understeer z in low-speed corners.')])

    # ── 8) Knife-edge / inconsistency ────────────────────────────────────────
    nervous = [c for c in corners if c['min_speed_var'] > 3.0 and c['nervousness'] > 4.0]
    if len(nervous) >= max(1, len(corners) // 4):
        w = _worst(nervous, 'min_speed_var')
        ev = ('Apex speed varies lap-to-lap by ' +
              ', '.join(f"±{c['min_speed_var']:.1f} km/h at corner {c['corner']}" for c in w) +
              ' with busy steering — the window is too narrow to hit consistently over a stint.')
        add('Knife-edge balance (inconsistency)', 1 + max(c['min_speed_var'] for c in nervous) / 3, ev, [
            prop('front_arb', -1, 'one step softer',
                 'A softer platform widens the operating window at a small ultimate-pace cost.',
                 'Peak one-lap pace may drop slightly.',
                 expect='min_speed_var shrinks; median lap improves even if best lap doesn\'t.',
                 verify='Consistency (σ) and min_speed_var at the listed corners.'),
            prop('rear_wing', +1, 'one step',
                 'Stability from aero is the cheapest consistency you can buy for a stint.',
                 'Straight-line cost.',
                 expect='Nervousness (steering reversals) drops.',
                 verify='nervousness metric next stint.'),
            prop('front_rebound', -1, 'one step softer',
                 'Softer front rebound keeps the front planted over mid-corner bumps.',
                 'Slightly floatier turn-in.',
                 expect='Less lap-to-lap variation at bumpy corners.',
                 verify='min_speed_var at the same corners.')])

    # ── 9) Entry instability (proxy fallback — only without measured locks) ──
    if not lock_r:
        entry_loose = [c for c in corners if c['oversteer_frac'] > 0.10 and c.get('understeer_z', 0) < 0]
        if len(entry_loose) >= max(1, len(corners) // 3):
            add('Instability on corner entry', 1.8,
                f'{len(entry_loose)} corners rotate beyond driver input during braking/entry.', [
                prop('brake_bias', +1, '0.5% forward',
                     'Forward bias calms rear rotation under braking.',
                     'Longer braking zones if you lock fronts instead.',
                     expect='Entry counter-steer drops.',
                     verify='oversteer_frac at entry-heavy corners + front_lock_frac.'),
                prop('diff_coast', +1, 'one step more coast lock',
                     'More coast lock stabilizes the rear axle off-throttle.',
                     'More entry understeer in slow corners.',
                     expect='Car tows straighter into corners.',
                     verify='Entry counter-steer events.'),
                prop('rear_toe', +1, 'a little more toe-in',
                     'Rear toe-in adds straight-line and entry stability.',
                     'Scrubs speed and heats rear tires.',
                     expect='Calmer entries; watch rear temps.',
                     verify='Rear tire temps + entry stability.')])

    findings.sort(key=lambda f: -f['severity'])
    return findings


def summarize(findings: list, recurrence: dict | None = None) -> list:
    """Rank knob+direction pairs across all findings — the 'change these first' list.

    Score = sum of proposing findings' severity, boosted by learned confidence
    and by recurrence across recent stints (same car). A knob proposed by two
    independent symptoms outranks one proposed by a single louder symptom.
    """
    agg = {}
    for f in findings:
        for p in f['proposals']:
            key = (p['knob'], p['direction'])
            a = agg.setdefault(key, {
                'knob': p['knob'], 'direction': p['direction'], 'size': p['size'],
                'symptoms': [], 'score': 0.0, 'current': p['current'],
                'learned': p.get('learned'),
            })
            a['symptoms'].append(f['symptom'])
            conf = (p.get('learned') or {}).get('conf', 0.5)
            a['score'] += f['severity'] * (0.5 + conf)
            if p.get('learned') and (a['learned'] or {}).get('tries', 0) < p['learned']['tries']:
                a['learned'] = p['learned']
    out = []
    for a in agg.values():
        rec = (recurrence or {}).get((a['knob'], a['direction']))
        if rec:
            a['recurrence'] = rec                      # {'hits': n, 'stints': m}
            a['score'] *= 1.0 + min(rec['hits'] / max(rec['stints'], 1), 1.0) * 0.5
        a['n_findings'] = len(a['symptoms'])
        if a['n_findings'] > 1:
            a['score'] *= 1.0 + 0.25 * (a['n_findings'] - 1)
        out.append(a)
    out.sort(key=lambda a: -a['score'])
    return out[:5]

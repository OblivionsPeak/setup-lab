"""End-to-end pipeline test on synthetic telemetry — no iRacing needed.

Stint 1: baseline setup, injected chronic understeer (corner 2) + late-stint
         rear deg. Expect those findings.
Stint 2: setup follows the rear-pressure recommendation and deg is reduced.
         Expect the learning loop to grade the change as a win.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.make_synth_ibt import build
from core.ibt import parse_ibt_bytes
from core.session import parse_session_info
from core.stints import segment_laps, segment_stints
from core.analysis import detect_corners, analyze_stint
from core.engine import diagnose
from core import store


def run_file(blob, name, con):
    channels, session_info, tick_rate, _ = parse_ibt_bytes(blob)
    meta = parse_session_info(session_info)
    assert meta['car'] == 'Synthetic GT3', meta['car']
    assert meta['setup'], 'CarSetup should be extracted from session YAML'
    laps = segment_laps(channels, tick_rate)
    assert len(laps) >= 12, f'expected 12+ laps, got {len(laps)}'
    stints = segment_stints(laps)
    assert len(stints) == 1, f'expected 1 stint, got {len(stints)}'
    corners = detect_corners(channels, laps, tick_rate)
    assert len(corners) == 4, f'expected 4 corners, got {len(corners)}'
    analysis = analyze_stint(channels, stints[0], corners, tick_rate)
    assert analysis, 'analysis returned None'
    findings = diagnose(analysis, meta['setup'])
    sid = store.save_stint(con, name, meta, 1, meta['setup'], analysis, findings)
    graded = store.grade_against_prior(con, sid)
    return meta, analysis, findings, graded


def main():
    # isolated DB
    tmp = tempfile.mkdtemp()
    os.environ['LOCALAPPDATA'] = tmp
    con = store.connect()

    print('--- stint 1: baseline (problems injected) ---')
    blob1 = build(n_laps=14, deg_s_per_lap=0.09, rr_press='24.0')
    meta, analysis, findings, _ = run_file(blob1, 'stint1.ibt', con)
    print(f'car={meta["car"]}  setup params={len(meta["setup"])}  '
          f'laps used={analysis["n_laps_used"]}  trend={analysis["deg_per_lap"]:+.3f}s/lap')
    symptoms = [f['symptom'] for f in findings]
    for f in findings:
        print(f'  [{f["severity"]:.1f}] {f["symptom"]} -> ' +
              ', '.join(p['knob'] for p in f['proposals']))
        print(f'        {f["evidence"][:140]}')

    assert any('understeer' in s.lower() for s in symptoms), 'chronic understeer not detected'
    assert any('degradation' in s.lower() or 'loose' in s.lower() for s in symptoms), \
        'rear degradation not detected'
    corner2 = next(c for c in analysis['corners'] if c['corner'] == 2)
    assert corner2['understeer_z'] > 1.0, f'corner 2 z={corner2["understeer_z"]:.2f}, expected >1'

    print('\n--- stint 2: followed rear-pressure advice, deg reduced ---')
    blob2 = build(n_laps=14, deg_s_per_lap=0.02, rr_press='23.5')
    meta2, analysis2, findings2, graded = run_file(blob2, 'stint2.ibt', con)
    print(f'trend={analysis2["deg_per_lap"]:+.3f}s/lap  graded={len(graded)} recommendation(s)')
    for g in graded:
        print(f'  {"WIN " if g["win"] else "LOSS"} {g["knob"]} for "{g["symptom"]}" '
              f'(pace {g["pace_delta"]:+.3f}s, severity {g["severity_delta"]:+.2f})')
    assert graded, 'learning loop produced no grades despite a followed recommendation'
    assert any(g['win'] for g in graded), 'expected at least one graded win'

    conf = store.learned_confidence(con, meta2['car'])
    assert conf, 'no learned confidence rows'
    print('\nlearned confidence:', {f'{k[1]}': round(v['conf'], 2) for k, v in conf.items()})

    from core.engine import summarize
    findings2 = store.apply_learning(findings2, conf)
    recurrence = store.knob_recurrence(con, meta2['car'])
    top = summarize(findings2, recurrence)
    assert top, 'summarize returned no top changes'
    assert any(t.get('recurrence') for t in top), 'expected recurrence badge from prior stint'
    print('top changes:', [(t['knob'], t['n_findings'], t.get('recurrence')) for t in top[:3]])

    print('\nALL PIPELINE TESTS PASSED')


if __name__ == '__main__':
    main()

"""Run the full analysis pipeline on a real .ibt and print a findings summary."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.ibt import parse_ibt
from core.session import parse_session_info
from core.stints import segment_laps, segment_stints
from core.analysis import detect_corners, analyze_stint
from core.engine import diagnose

ch, si, tr, rc = parse_ibt(sys.argv[1])
meta = parse_session_info(si)
print(f"{meta['car']} @ {meta['track']} — {meta['driver']} ({len(meta['setup'])} setup params)")

laps = segment_laps(ch, tr)
stints = segment_stints(laps)
corners = detect_corners(ch, laps, tr)
print(f'laps={len(laps)} stints={len(stints)} corners={len(corners)}')

for st in stints:
    a = analyze_stint(ch, st, corners, tr)
    if not a:
        print(f"stint {st['stint_num']}: too few clean laps to analyze")
        continue
    p = a.get('platform') or {}
    if p.get('roll_couple_front') is not None:
        print(f"  platform: front roll share {100*p['roll_couple_front']:.0f}%")
    if p.get('brakes'):
        print(f"  brakes: measured front share {p['brakes']['front_share_pct']:.1f}% "
              f"(dial {p['brakes']['dial']})")
    for w, t in (p.get('tires') or {}).items():
        print(f"  {w}: inner-outer {t['camber_delta']:+.0f}C, mid-vs-edges {t['middle_vs_edges']:+.0f}C, "
              f"hot {t.get('hot_pressure_psi', 0):.1f} psi (build {t.get('pressure_build_psi', 0):+.1f})")
    fs = diagnose(a, meta['setup'])
    print(f"--- stint {st['stint_num']}: {a['n_laps_used']}/{a['n_laps_total']} laps, "
          f"best {a['best_lap']:.3f}, median {a['median_lap']:.3f}, "
          f"trend {a['deg_per_lap']:+.3f} s/lap, fuel {a['fuel_used']:.1f}")
    for f in fs:
        print(f"  [{f['severity']:.1f}] {f['symptom']} -> " +
              ', '.join(p['knob'] for p in f['proposals']))
        print('       ' + f['evidence'][:150])

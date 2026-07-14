"""Check which 'garage-suspect' channels actually update while driving."""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.ibt import parse_ibt

ch, si, tr, rc = parse_ibt(sys.argv[1])
suspects = ['LFtempM', 'LFtempCM', 'LFwearM', 'LFpressure', 'RRtempCM', 'RRwearM', 'RRpressure',
            'LFshockDefl', 'LFrideHeight', 'LFspeed', 'LFbrakeLinePress', 'BrakeABSactive',
            'dcBrakeBias', 'dcTractionControl', 'TrackTemp', 'Roll', 'VertAccel']
n = rc
mid = slice(n // 4, 3 * n // 4)   # middle of the run — definitely out driving
for name in suspects:
    if name not in ch:
        print(f'{name:20s} MISSING')
        continue
    arr = np.asarray(ch[name], dtype=float)[mid]
    changes = int(np.count_nonzero(np.diff(arr)))
    print(f'{name:20s} min={np.nanmin(arr):10.4f} max={np.nanmax(arr):10.4f} changes={changes}')

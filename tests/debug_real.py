"""Debug session-YAML parsing against a real .ibt (not committed to CI)."""
import sys
import os
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.ibt import parse_ibt
from core.session import _safe_yaml, parse_session_info

path = sys.argv[1]
ch, si, tr, rc = parse_ibt(path)
out = os.path.join(os.environ['TEMP'], 'real_session.yaml')
with open(out, 'w', encoding='utf-8') as f:
    f.write(si)
print(f'session YAML: {len(si)} chars -> {out}')

try:
    doc = yaml.safe_load(si)
    print('plain safe_load OK, type:', type(doc).__name__)
except Exception as e:
    print('plain safe_load FAILED:', type(e).__name__, str(e)[:400])

try:
    doc = _safe_yaml(si)
    if isinstance(doc, dict):
        print('_safe_yaml OK, keys:', list(doc.keys()))
    else:
        print('_safe_yaml returned', type(doc).__name__)
except Exception as e:
    print('_safe_yaml FAILED:', type(e).__name__, str(e)[:400])

meta = parse_session_info(si)
print('parse_session_info ->', {k: (v if k != 'setup' else f'{len(v)} params') for k, v in meta.items()})

"""SQLite store: sessions, stints, recommendations, and learned per-car confidence.

Learning loop: when a new stint arrives for a (car, track) we already have a
stint for, and the setup changed in the direction a prior recommendation
proposed, the recommendation is graded on measured outcome (fuel-corrected
pace + symptom severity). Grades roll into per-(car, symptom, knob) confidence
that reorders future proposals — the app literally learns each car as people
drive it.
"""
import json
import os
import sqlite3
import time

from .session import numeric_value

SCHEMA = """
CREATE TABLE IF NOT EXISTS stints (
    id INTEGER PRIMARY KEY,
    created REAL,
    file_name TEXT,
    driver TEXT,
    car TEXT,
    track TEXT,
    stint_num INTEGER,
    setup_json TEXT,
    analysis_json TEXT,
    findings_json TEXT
);
CREATE TABLE IF NOT EXISTS grades (
    id INTEGER PRIMARY KEY,
    created REAL,
    car TEXT,
    track TEXT,
    symptom TEXT,
    knob TEXT,
    direction INTEGER,
    followed INTEGER,
    pace_delta REAL,
    severity_delta REAL,
    win INTEGER,
    before_stint INTEGER,
    after_stint INTEGER
);
CREATE INDEX IF NOT EXISTS idx_stints_car_track ON stints(car, track);
CREATE INDEX IF NOT EXISTS idx_grades_car ON grades(car, symptom, knob);
"""


def db_path():
    base = os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')), 'SetupLab')
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, 'setuplab.db')


def connect():
    con = sqlite3.connect(db_path())
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def save_stint(con, file_name, meta, stint_num, setup, analysis, findings):
    cur = con.execute(
        'INSERT INTO stints (created, file_name, driver, car, track, stint_num, setup_json, analysis_json, findings_json) '
        'VALUES (?,?,?,?,?,?,?,?,?)',
        (time.time(), file_name, meta['driver'], meta['car'], meta['track'], stint_num,
         json.dumps(setup), json.dumps(analysis), json.dumps(findings)))
    con.commit()
    return cur.lastrowid


def prior_stint(con, car, track, before_id):
    row = con.execute(
        'SELECT * FROM stints WHERE car=? AND track=? AND id<? ORDER BY id DESC LIMIT 1',
        (car, track, before_id)).fetchone()
    return row


def _severity_map(findings):
    return {f['symptom']: f['severity'] for f in findings}


def grade_against_prior(con, new_id):
    """Grade the prior stint's recommendations using this stint's measured outcome."""
    new = con.execute('SELECT * FROM stints WHERE id=?', (new_id,)).fetchone()
    if not new:
        return []
    prev = prior_stint(con, new['car'], new['track'], new_id)
    if not prev:
        return []

    old_setup = json.loads(prev['setup_json'])
    new_setup = json.loads(new['setup_json'])
    old_a, new_a = json.loads(prev['analysis_json']), json.loads(new['analysis_json'])
    old_f, new_f = json.loads(prev['findings_json']), json.loads(new['findings_json'])
    old_sev, new_sev = _severity_map(old_f), _severity_map(new_f)

    pace_delta = new_a['median_lap'] - old_a['median_lap']   # negative = faster
    graded = []
    for f in old_f:
        for p in f['proposals']:
            followed = 0
            for key in p['keys']:
                ov, nv = numeric_value(old_setup.get(key, '')), numeric_value(new_setup.get(key, ''))
                if ov is None or nv is None or nv == ov:
                    continue
                if (nv - ov) * p['direction'] > 0:
                    followed = 1
            if not followed:
                continue
            sev_delta = new_sev.get(f['symptom'], 0.0) - f['severity']
            win = 1 if (pace_delta < -0.02 or sev_delta < -0.3) else 0
            con.execute(
                'INSERT INTO grades (created, car, track, symptom, knob, direction, followed, '
                'pace_delta, severity_delta, win, before_stint, after_stint) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                (time.time(), new['car'], new['track'], f['symptom'], p['knob'], p['direction'],
                 1, pace_delta, sev_delta, win, prev['id'], new_id))
            graded.append({'symptom': f['symptom'], 'knob': p['knob'],
                           'pace_delta': pace_delta, 'severity_delta': sev_delta, 'win': bool(win)})
    con.commit()
    return graded


def learned_confidence(con, car):
    """{(symptom, knob): {'wins': n, 'tries': n, 'conf': laplace-smoothed}} for a car."""
    rows = con.execute(
        'SELECT symptom, knob, SUM(win) w, COUNT(*) n FROM grades WHERE car=? GROUP BY symptom, knob',
        (car,)).fetchall()
    return {(r['symptom'], r['knob']): {'wins': r['w'], 'tries': r['n'],
                                        'conf': (r['w'] + 1) / (r['n'] + 2)}
            for r in rows}


def apply_learning(findings, conf):
    """Annotate + reorder proposals by learned confidence (untested knobs keep 0.5 prior)."""
    for f in findings:
        for p in f['proposals']:
            c = conf.get((f['symptom'], p['knob']))
            p['learned'] = {'conf': c['conf'], 'tries': c['tries'], 'wins': c['wins']} if c \
                else {'conf': 0.5, 'tries': 0, 'wins': 0}
        f['proposals'].sort(key=lambda p: -p['learned']['conf'])
    return findings


def recent_stints(con, limit=50):
    return [dict(r) for r in con.execute(
        'SELECT id, created, file_name, driver, car, track, stint_num FROM stints '
        'ORDER BY id DESC LIMIT ?', (limit,)).fetchall()]


def get_stint(con, sid):
    r = con.execute('SELECT * FROM stints WHERE id=?', (sid,)).fetchone()
    return dict(r) if r else None

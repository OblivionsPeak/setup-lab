"""Setup Lab — stint-based iRacing setup engineer.

Drop an .ibt telemetry file; get stint-level analysis and detailed,
evidence-cited setup recommendations. Local only, no accounts, no network.
"""
import os
import socket
import sys
import threading
import webbrowser

from flask import Flask, jsonify, render_template, request

from core.ibt import parse_ibt_bytes
from core.session import parse_session_info
from core.stints import segment_laps, segment_stints
from core.analysis import detect_corners, analyze_stint
from core.engine import diagnose
from core import store

PORT = 4790


def resource_path(rel):
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


app = Flask(__name__,
            template_folder=resource_path('templates'),
            static_folder=resource_path('static'))
app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024 * 1024  # 1 GB — long stints are big


@app.get('/')
def index():
    return render_template('index.html')


@app.post('/api/analyze')
def analyze():
    f = request.files.get('ibt')
    if not f or not f.filename.lower().endswith('.ibt'):
        return jsonify({'error': 'Please upload an iRacing .ibt telemetry file.'}), 400

    try:
        channels, session_info, tick_rate, _ = parse_ibt_bytes(f.read())
    except Exception as e:
        return jsonify({'error': f'Could not parse this .ibt file: {e}'}), 400

    meta = parse_session_info(session_info)
    laps = segment_laps(channels, tick_rate)
    if not laps:
        return jsonify({'error': 'No complete laps found in this file.'}), 400
    stints = segment_stints(laps)
    if not stints:
        return jsonify({'error': 'No stint of 3+ consecutive clean laps found. '
                                 'Drive a longer run and try again.'}), 400
    corners = detect_corners(channels, laps, tick_rate)
    if not corners:
        return jsonify({'error': 'Could not detect corners (is this an oval warm-up or tow lap?).'}), 400

    con = store.connect()
    results = []
    for st in stints:
        analysis = analyze_stint(channels, st, corners, tick_rate)
        if not analysis:
            continue
        findings = diagnose(analysis, meta['setup'])
        sid = store.save_stint(con, f.filename, meta, st['stint_num'],
                               meta['setup'], analysis, findings)
        graded = store.grade_against_prior(con, sid)
        conf = store.learned_confidence(con, meta['car'])
        findings = store.apply_learning(findings, conf)
        results.append({'stint_id': sid, 'stint_num': st['stint_num'],
                        'analysis': analysis, 'findings': findings, 'graded': graded})
    con.close()

    if not results:
        return jsonify({'error': 'Stints found but none had 3+ representative laps to analyze.'}), 400

    return jsonify({'meta': {k: meta[k] for k in ('car', 'track', 'driver', 'setup_name', 'session_type')},
                    'setup': meta['setup'],
                    'n_corners': len(corners),
                    'stints': results})


@app.get('/api/history')
def history():
    con = store.connect()
    rows = store.recent_stints(con)
    con.close()
    return jsonify({'stints': rows})


@app.get('/api/stint/<int:sid>')
def stint_detail(sid):
    import json as _json
    con = store.connect()
    row = store.get_stint(con, sid)
    if not row:
        con.close()
        return jsonify({'error': 'not found'}), 404
    conf = store.learned_confidence(con, row['car'])
    findings = store.apply_learning(_json.loads(row['findings_json']), conf)
    con.close()
    return jsonify({'meta': {'car': row['car'], 'track': row['track'],
                             'driver': row['driver'], 'setup_name': '', 'session_type': ''},
                    'setup': _json.loads(row['setup_json']),
                    'stints': [{'stint_id': row['id'], 'stint_num': row['stint_num'],
                                'analysis': _json.loads(row['analysis_json']),
                                'findings': findings, 'graded': []}]})


def open_browser():
    webbrowser.open(f'http://localhost:{PORT}')


def already_running():
    # Werkzeug binds with SO_REUSEADDR, so on Windows a second instance would
    # double-bind the port and silently lose traffic to the first — detect and bail.
    s = socket.socket()
    s.settimeout(0.5)
    try:
        s.connect(('127.0.0.1', PORT))
        return True
    except OSError:
        return False
    finally:
        s.close()


if __name__ == '__main__':
    if already_running():
        open_browser()          # an instance is already up — just show it
        sys.exit(0)
    threading.Timer(1.0, open_browser).start()
    app.run(host='127.0.0.1', port=PORT, debug=False)

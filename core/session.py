"""Extract car, track, driver, and the full CarSetup block from .ibt session YAML."""
import re
import yaml


def _safe_yaml(text):
    # iRacing session YAML can contain unquoted values with ':' or non-ASCII;
    # sanitize the known offenders before parsing.
    cleaned = []
    for line in text.splitlines():
        if re.match(r'\s*(DriverSetupName|UserName|TeamName|AbbrevName|Initials|TrackName|TrackDisplayName|TrackDisplayShortName|TrackCity|TrackCountry|SessionName|SessionType|SessionSubType|WeekendOptions)\s*:', line):
            key, _, val = line.partition(':')
            val = val.strip().replace('"', "'")
            line = f'{key}: "{val}"'
        cleaned.append(line)
    return yaml.safe_load('\n'.join(cleaned))


def parse_session_info(session_info: str) -> dict:
    """Returns {car, car_id, track, track_id, driver, session_type, setup: {flat param dict}, setup_name}."""
    try:
        doc = _safe_yaml(session_info)
    except yaml.YAMLError:
        doc = None
    if not isinstance(doc, dict):
        return {'car': 'unknown', 'track': 'unknown', 'driver': '', 'setup': {}, 'setup_name': '', 'session_type': ''}

    weekend = doc.get('WeekendInfo') or {}
    track = str(weekend.get('TrackDisplayName') or weekend.get('TrackName') or 'unknown')
    track_id = weekend.get('TrackID', 0)

    car, car_id, driver = 'unknown', 0, ''
    di = doc.get('DriverInfo') or {}
    idx = di.get('DriverCarIdx', 0)
    for d in di.get('Drivers') or []:
        if d.get('CarIdx') == idx:
            car = str(d.get('CarScreenName') or d.get('CarPath') or 'unknown')
            car_id = d.get('CarID', 0)
            driver = str(d.get('UserName') or '')
            break

    setup_name = str(di.get('DriverSetupName') or '')
    setup = flatten_setup(doc.get('CarSetup') or {})

    session_type = ''
    sessions = (doc.get('SessionInfo') or {}).get('Sessions') or []
    if sessions:
        session_type = str(sessions[-1].get('SessionType') or '')

    return {'car': car, 'car_id': car_id, 'track': track, 'track_id': track_id,
            'driver': driver, 'setup': setup, 'setup_name': setup_name,
            'session_type': session_type}


def flatten_setup(car_setup: dict) -> dict:
    """CarSetup YAML tree -> flat {'Tab.Section.Param': 'value string'} dict."""
    flat = {}

    def walk(node, path):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == 'UpdateCount':
                    continue
                walk(v, path + [str(k)])
        else:
            flat['.'.join(path)] = str(node)

    walk(car_setup, [])
    return flat


_NUM_RE = re.compile(r'-?\d+(?:\.\d+)?')


def numeric_value(raw: str):
    """First numeric token of a setup value string ('55.0%', '-2.8 deg', '6 clicks')."""
    m = _NUM_RE.search(str(raw))
    return float(m.group()) if m else None

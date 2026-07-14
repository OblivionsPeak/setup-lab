// Session-YAML metadata + CarSetup extraction — port of core/session.py.

import * as yamlMod from './vendor/js-yaml.min.js';

// UMD resolves differently by host: browsers get globalThis.jsyaml from the
// side-effect; Node's CJS detection routes it through module.exports instead.
const yaml = globalThis.jsyaml || yamlMod.default || yamlMod;

const QUOTE_KEYS = /^(\s*)(DriverSetupName|UserName|TeamName|AbbrevName|Initials|TrackName|TrackDisplayName|TrackDisplayShortName|TrackCity|TrackCountry|SessionName|SessionType|SessionSubType)(\s*):(.+)$/;

function safeYaml(text) {
  try {
    const doc = yaml.load(text);
    if (doc && typeof doc === 'object') return doc;
  } catch { /* fall through to sanitizer */ }
  const cleaned = text.split('\n').map((line) => {
    const m = line.match(QUOTE_KEYS);
    if (m && m[4].trim()) {
      return `${m[1]}${m[2]}: "${m[4].trim().replace(/"/g, "'")}"`;
    }
    return line;
  }).join('\n');
  return yaml.load(cleaned);
}

export function flattenSetup(carSetup) {
  const flat = {};
  (function walk(node, path) {
    if (node && typeof node === 'object' && !Array.isArray(node)) {
      for (const [k, v] of Object.entries(node)) {
        if (k === 'UpdateCount') continue;
        walk(v, path ? `${path}.${k}` : k);
      }
    } else {
      flat[path] = String(node);
    }
  })(carSetup || {}, '');
  return flat;
}

export function numericValue(raw) {
  const m = String(raw).match(/-?\d+(?:\.\d+)?/);
  return m ? parseFloat(m[0]) : null;
}

export function parseSessionInfo(sessionInfo) {
  let doc = null;
  try { doc = safeYaml(sessionInfo); } catch { /* ignore */ }
  if (!doc || typeof doc !== 'object') {
    return { car: 'unknown', track: 'unknown', driver: '', setup: {}, setup_name: '', session_type: '' };
  }
  const weekend = doc.WeekendInfo || {};
  const track = String(weekend.TrackDisplayName || weekend.TrackName || 'unknown');

  let car = 'unknown', driver = '';
  const di = doc.DriverInfo || {};
  const idx = di.DriverCarIdx ?? 0;
  for (const d of di.Drivers || []) {
    if (d.CarIdx === idx) {
      car = String(d.CarScreenName || d.CarPath || 'unknown');
      driver = String(d.UserName || '');
      break;
    }
  }
  let sessionType = '';
  const sessions = (doc.SessionInfo || {}).Sessions || [];
  if (sessions.length) sessionType = String(sessions[sessions.length - 1].SessionType || '');

  return {
    car, track, driver,
    setup: flattenSetup(doc.CarSetup || {}),
    setup_name: String(di.DriverSetupName || ''),
    session_type: sessionType,
  };
}

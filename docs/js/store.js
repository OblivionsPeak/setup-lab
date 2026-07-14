// Learning store — IndexedDB port of core/store.py. Same grading logic:
// when a new stint's setup moved in a direction a prior recommendation
// proposed, grade it on measured outcome; grades roll into per-(car,
// symptom, knob) confidence that reorders future proposals.

import { numericValue } from './session.js';

const DB_NAME = 'setuplab';
const DB_VER = 1;

function openDb() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VER);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains('stints')) {
        const st = db.createObjectStore('stints', { keyPath: 'id', autoIncrement: true });
        st.createIndex('car', 'car');
        st.createIndex('car_track', ['car', 'track']);
      }
      if (!db.objectStoreNames.contains('grades')) {
        const gr = db.createObjectStore('grades', { keyPath: 'id', autoIncrement: true });
        gr.createIndex('car', 'car');
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

function tx(db, store, mode, fn) {
  return new Promise((resolve, reject) => {
    const t = db.transaction(store, mode);
    const result = fn(t.objectStore(store));
    t.oncomplete = () => resolve(result.__value !== undefined ? result.__value : result);
    t.onerror = () => reject(t.error);
  });
}

function reqAsync(req) {
  return new Promise((resolve, reject) => {
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

export async function saveStint(fileName, meta, stintNum, setup, analysis, findings) {
  const db = await openDb();
  const rec = {
    created: Date.now() / 1000, file_name: fileName,
    driver: meta.driver, car: meta.car, track: meta.track,
    stint_num: stintNum, setup, analysis, findings,
  };
  const t = db.transaction('stints', 'readwrite');
  const id = await reqAsync(t.objectStore('stints').add(rec));
  db.close();
  return id;
}

async function allStints() {
  const db = await openDb();
  const rows = await reqAsync(db.transaction('stints').objectStore('stints').getAll());
  db.close();
  return rows;
}

export async function gradeAgainstPrior(newId) {
  const rows = await allStints();
  const cur = rows.find((r) => r.id === newId);
  if (!cur) return [];
  const prev = rows
    .filter((r) => r.car === cur.car && r.track === cur.track && r.id < newId)
    .sort((a, b) => b.id - a.id)[0];
  if (!prev) return [];

  const newSev = {};
  for (const f of cur.findings) newSev[f.symptom] = f.severity;
  const paceDelta = cur.analysis.median_lap - prev.analysis.median_lap;

  const graded = [];
  const db = await openDb();
  const t = db.transaction('grades', 'readwrite');
  const gs = t.objectStore('grades');
  for (const f of prev.findings) {
    for (const p of f.proposals) {
      let followed = false;
      for (const key of p.keys) {
        const ov = numericValue(prev.setup[key] ?? '');
        const nv = numericValue(cur.setup[key] ?? '');
        if (ov == null || nv == null || nv === ov) continue;
        if ((nv - ov) * p.direction > 0) followed = true;
      }
      if (!followed) continue;
      const sevDelta = (newSev[f.symptom] ?? 0) - f.severity;
      const win = paceDelta < -0.02 || sevDelta < -0.3;
      gs.add({
        created: Date.now() / 1000, car: cur.car, track: cur.track,
        symptom: f.symptom, knob: p.knob, direction: p.direction,
        pace_delta: paceDelta, severity_delta: sevDelta, win: win ? 1 : 0,
        before_stint: prev.id, after_stint: newId,
      });
      graded.push({ symptom: f.symptom, knob: p.knob, pace_delta: paceDelta, severity_delta: sevDelta, win });
    }
  }
  await new Promise((res, rej) => { t.oncomplete = res; t.onerror = () => rej(t.error); });
  db.close();
  return graded;
}

export async function learnedConfidence(car) {
  const db = await openDb();
  const rows = await reqAsync(db.transaction('grades').objectStore('grades').index('car').getAll(car));
  db.close();
  const agg = {};
  for (const r of rows) {
    const key = `${r.symptom}|${r.knob}`;
    const a = agg[key] || (agg[key] = { wins: 0, tries: 0 });
    a.wins += r.win;
    a.tries += 1;
  }
  for (const a of Object.values(agg)) a.conf = (a.wins + 1) / (a.tries + 2);
  return agg;
}

export function applyLearning(findings, conf) {
  for (const f of findings) {
    for (const p of f.proposals) {
      const c = conf[`${f.symptom}|${p.knob}`];
      p.learned = c ? { conf: c.conf, tries: c.tries, wins: c.wins } : { conf: 0.5, tries: 0, wins: 0 };
    }
    f.proposals.sort((a, b) => b.learned.conf - a.learned.conf);
  }
  return findings;
}

export async function knobRecurrence(car, excludeId = null, window = 8) {
  const rows = (await allStints())
    .filter((r) => r.car === car && r.id !== excludeId)
    .sort((a, b) => b.id - a.id)
    .slice(0, window);
  const counts = {};
  for (const r of rows) {
    const seen = new Set();
    for (const f of r.findings) for (const p of f.proposals) seen.add(`${p.knob}|${p.direction}`);
    for (const key of seen) counts[key] = (counts[key] || 0) + 1;
  }
  const out = {};
  for (const [k, v] of Object.entries(counts)) out[k] = { hits: v, stints: rows.length };
  return out;
}

export async function recentStints(limit = 50) {
  return (await allStints())
    .sort((a, b) => b.id - a.id)
    .slice(0, limit)
    .map((r) => ({ id: r.id, created: r.created, file_name: r.file_name, driver: r.driver, car: r.car, track: r.track, stint_num: r.stint_num }));
}

export async function getStint(id) {
  const db = await openDb();
  const row = await reqAsync(db.transaction('stints').objectStore('stints').get(id));
  db.close();
  return row || null;
}

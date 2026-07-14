// Analysis worker — the whole pipeline runs off the main thread. Messages
// mirror the old Flask API shapes exactly, so the UI code is unchanged.

import { parseIbt } from './ibt.js';
import { parseSessionInfo } from './session.js';
import { segmentLaps, segmentStints } from './stints.js';
import { detectCorners, analyzeStint } from './analysis.js';
import { diagnose, summarize } from './engine.js';
import * as store from './store.js';

function cleanJson(o) {
  if (Array.isArray(o)) return o.map(cleanJson);
  if (o && typeof o === 'object') {
    const out = {};
    for (const [k, v] of Object.entries(o)) out[k] = cleanJson(v);
    return out;
  }
  if (typeof o === 'number' && !Number.isFinite(o)) return null;
  return o;
}

async function analyze(fileName, buf) {
  let ibt;
  try {
    ibt = parseIbt(buf);
  } catch (err) {
    return { error: `Could not parse this .ibt file: ${err.message}` };
  }
  const meta = parseSessionInfo(ibt.sessionInfo);
  const laps = segmentLaps(ibt);
  if (!laps.length) return { error: 'No complete laps found in this file.' };
  const stints = segmentStints(laps);
  if (!stints.length) {
    return { error: 'No stint of 3+ consecutive clean laps found. Drive a longer run and try again.' };
  }
  const corners = detectCorners(ibt, laps);
  if (!corners.length) return { error: 'Could not detect corners (is this an oval warm-up or tow lap?).' };

  const results = [];
  for (const st of stints) {
    const analysis = analyzeStint(ibt, st, corners);
    if (!analysis) continue;
    let findings = diagnose(analysis, meta.setup);
    const sid = await store.saveStint(fileName, meta, st.stint_num, meta.setup, analysis, findings);
    const graded = await store.gradeAgainstPrior(sid);
    const conf = await store.learnedConfidence(meta.car);
    findings = store.applyLearning(findings, conf);
    const recurrence = await store.knobRecurrence(meta.car, sid);
    const top = summarize(findings, recurrence);
    results.push({ stint_id: sid, stint_num: st.stint_num, analysis, findings, top_changes: top, graded });
  }
  if (!results.length) {
    return { error: 'Stints found but none had 3+ representative laps to analyze.' };
  }
  return {
    meta: {
      car: meta.car, track: meta.track, driver: meta.driver,
      setup_name: meta.setup_name, session_type: meta.session_type,
    },
    setup: meta.setup,
    n_corners: corners.length,
    stints: results,
  };
}

self.onmessage = async (ev) => {
  const { cmd, id } = ev.data;
  try {
    let result;
    if (cmd === 'analyze') {
      result = await analyze(ev.data.fileName, ev.data.buffer);
    } else if (cmd === 'history') {
      result = { stints: await store.recentStints() };
    } else if (cmd === 'stint') {
      const row = await store.getStint(ev.data.stintId);
      if (!row) {
        result = { error: 'not found' };
      } else {
        const conf = await store.learnedConfidence(row.car);
        const findings = store.applyLearning(row.findings, conf);
        const recurrence = await store.knobRecurrence(row.car, row.id);
        result = {
          meta: { car: row.car, track: row.track, driver: row.driver, setup_name: '', session_type: '' },
          setup: row.setup,
          stints: [{
            stint_id: row.id, stint_num: row.stint_num, analysis: row.analysis,
            findings, top_changes: summarize(findings, recurrence), graded: [],
          }],
        };
      }
    } else {
      result = { error: `unknown command ${cmd}` };
    }
    self.postMessage({ id, result: cleanJson(result) });
  } catch (err) {
    self.postMessage({ id, result: { error: `Analysis failed: ${err.message}` } });
  }
};

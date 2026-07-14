// iRacing .ibt parser — browser port of core/ibt.py.
// Parses the header eagerly but extracts channels lazily (a session file has
// ~286 channels; the pipeline touches ~45, and a 100 MB file makes eager
// extraction of everything needlessly slow).

const HEADER_SIZE = 112;
const VAR_HEADER_SIZE = 144;

const TYPE_SIZE = { 0: 1, 1: 1, 2: 4, 3: 4, 4: 4, 5: 8 };

export function parseIbt(buf) {
  const dv = new DataView(buf);
  if (buf.byteLength < HEADER_SIZE + 32) throw new Error('File is too small to be a valid .ibt file.');

  const tickRate = dv.getInt32(8, true);
  const sessionInfoLen = dv.getInt32(16, true);
  const sessionInfoOffset = dv.getInt32(20, true);
  const numVars = dv.getInt32(24, true);
  const varHeaderOffset = dv.getInt32(28, true);
  const bufLen = dv.getInt32(36, true);
  let dataBufOffset = dv.getInt32(52, true);   // varBuf[0].bufOffset at byte 48+4

  // disk sub-header at 112: time_t(8) + double(8) + double(8) + int + int
  let recordCount = dv.getInt32(HEADER_SIZE + 28, true);

  const yamlBytes = new Uint8Array(buf, sessionInfoOffset, sessionInfoLen);
  let end = yamlBytes.length;
  while (end > 0 && yamlBytes[end - 1] === 0) end--;
  const sessionInfo = new TextDecoder('utf-8').decode(yamlBytes.subarray(0, end));

  const nameDecoder = new TextDecoder('utf-8');
  const vars = {};
  for (let i = 0; i < numVars; i++) {
    const base = varHeaderOffset + i * VAR_HEADER_SIZE;
    const type = dv.getInt32(base, true);
    const offset = dv.getInt32(base + 4, true);
    const count = dv.getInt32(base + 8, true);
    const nb = new Uint8Array(buf, base + 16, 32);
    let n = 0;
    while (n < 32 && nb[n] !== 0) n++;
    const name = nameDecoder.decode(nb.subarray(0, n));
    vars[name] = { type, offset, count };
  }

  const minDataStart = varHeaderOffset + numVars * VAR_HEADER_SIZE;
  if (dataBufOffset < minDataStart) dataBufOffset = minDataStart;
  const available = buf.byteLength - dataBufOffset;
  recordCount = Math.min(recordCount, Math.floor(available / bufLen));

  const cache = new Map();
  // lazy channel accessor: returns Float64Array (or null if channel absent)
  function ch(name) {
    if (cache.has(name)) return cache.get(name);
    const v = vars[name];
    if (!v || TYPE_SIZE[v.type] === undefined || v.count !== 1) {
      cache.set(name, null);
      return null;
    }
    const out = new Float64Array(recordCount);
    const { type, offset } = v;
    for (let r = 0; r < recordCount; r++) {
      const p = dataBufOffset + r * bufLen + offset;
      out[r] = type === 4 ? dv.getFloat32(p, true)
        : type === 5 ? dv.getFloat64(p, true)
        : type === 2 || type === 3 ? dv.getInt32(p, true)
        : dv.getUint8(p);            // bool / char
    }
    cache.set(name, out);
    return out;
  }

  return { ch, has: (name) => !!vars[name], sessionInfo, tickRate, recordCount };
}

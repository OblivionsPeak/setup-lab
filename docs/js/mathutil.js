// Small numeric helpers standing in for numpy.

export function median(arr) {
  if (!arr.length) return NaN;
  const a = Array.from(arr).sort((x, y) => x - y);
  const m = a.length >> 1;
  return a.length % 2 ? a[m] : (a[m - 1] + a[m]) / 2;
}

export function mean(arr) {
  if (!arr.length) return NaN;
  let s = 0;
  for (const v of arr) s += v;
  return s / arr.length;
}

export function std(arr) {
  if (!arr.length) return NaN;
  const mu = mean(arr);
  let s = 0;
  for (const v of arr) s += (v - mu) * (v - mu);
  return Math.sqrt(s / arr.length);
}

export function min(arr) { let m = Infinity; for (const v of arr) if (v < m) m = v; return m; }
export function max(arr) { let m = -Infinity; for (const v of arr) if (v > m) m = v; return m; }

export function percentile(arr, p) {
  // numpy-style linear interpolation
  const a = Array.from(arr).sort((x, y) => x - y);
  if (!a.length) return NaN;
  const idx = (p / 100) * (a.length - 1);
  const lo = Math.floor(idx), hi = Math.ceil(idx);
  return a[lo] + (a[hi] - a[lo]) * (idx - lo);
}

// least-squares slope of y over 0..n-1 (np.polyfit(x, y, 1)[0])
export function slope(y) {
  const n = y.length;
  if (n < 2) return 0;
  const sx = (n - 1) * n / 2;
  const sxx = (n - 1) * n * (2 * n - 1) / 6;
  let sy = 0, sxy = 0;
  for (let i = 0; i < n; i++) { sy += y[i]; sxy += i * y[i]; }
  return (n * sxy - sx * sy) / (n * sxx - sx * sx);
}

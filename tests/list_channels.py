"""List all channels in a real .ibt with units."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.ibt import parse_ibt
import struct

path = sys.argv[1]
with open(path, 'rb') as f:
    raw = f.read(4 * 1024 * 1024)
(ver, status, tick_rate, siu, sil, sio, num_vars, vho, nb, bl, p0, p1) = struct.unpack_from('<12i', raw, 0)
names = []
for i in range(num_vars):
    base = vho + i * 144
    name = raw[base + 16: base + 48].rstrip(b'\x00').decode('utf-8', 'replace')
    unit = raw[base + 112: base + 144].rstrip(b'\x00').decode('utf-8', 'replace')
    names.append(f'{name} [{unit}]')
print(f'{num_vars} channels @ {tick_rate} Hz')
for n in sorted(names):
    print(' ', n)

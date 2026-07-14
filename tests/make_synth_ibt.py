"""Build a byte-valid synthetic .ibt file for pipeline testing.

Simulates a stint on a 4-corner track with injected setup problems:
  - chronic understeer at corner 2 (steer/yaw ratio 1.7x other corners)
  - late-stint oversteer at corners 3 & 4 (counter-steer grows) + rising lap times
"""
import struct
import numpy as np

TICK = 60
LAP_SECONDS = 80
G = 9.81

CORNERS = [  # (pct_center, half_width_pct, direction)
    (0.15, 0.030, +1), (0.40, 0.035, -1), (0.62, 0.030, +1), (0.85, 0.035, -1),
]

SESSION_YAML = """---
WeekendInfo:
 TrackName: synthetic speedway
 TrackID: 999
 TrackDisplayName: Synthetic International
DriverInfo:
 DriverCarIdx: 0
 DriverSetupName: baseline_v1.sto
 Drivers:
 - CarIdx: 0
   UserName: Test Driver
   CarScreenName: Synthetic GT3
   CarID: 501
SessionInfo:
 Sessions:
 - SessionNum: 0
   SessionType: Practice
CarSetup:
 UpdateCount: 3
 TiresAero:
  LeftFront:
   ColdPressure: 24.5 psi
  RightFront:
   ColdPressure: 24.5 psi
  LeftRear:
   ColdPressure: 24.0 psi
  RightRear:
   ColdPressure: {rr_press} psi
  AeroSettings:
   RearWingSetting: {wing} degrees
 Chassis:
  Front:
   ArbSetting: {farb}
   BrakePressureBias: 54.5%
   ToeIn: -1.0 mm
  Rear:
   ArbSetting: 4
   SpringRate: 180 N/mm
   ToeIn: +1.5 mm
 Drivetrain:
  Differential:
   Preload: 60 Nm
   CoastRampAngle: 45 deg
   DriveRampAngle: 30 deg
...
"""

VARS = [  # (name, type_id) 2=int32 4=float32 1=bool
    ('Lap', 2), ('LapDistPct', 4), ('LapLastLapTime', 4), ('Speed', 4),
    ('Throttle', 4), ('Brake', 4), ('SteeringWheelAngle', 4), ('FuelLevel', 4),
    ('LatAccel', 4), ('YawRate', 4), ('OnPitRoad', 1), ('PlayerTrackSurface', 2),
]
TYPE_SIZE = {1: 1, 2: 4, 4: 4}
TYPE_FMT = {1: '?', 2: 'i', 4: 'f'}


def lap_signals(lap_i, n_laps, lap_time):
    n = LAP_SECONDS * TICK
    t = np.linspace(0, 1, n, endpoint=False)
    pct = t.copy()
    speed = np.full(n, 52.0)
    lat = np.zeros(n)
    steer = np.zeros(n)
    thr = np.ones(n)
    brk = np.zeros(n)
    late = lap_i >= n_laps // 2

    for ci, (c, w, dirn) in enumerate(CORNERS):
        d = (pct - c) / w
        mask = np.abs(d) < 1
        bell = np.where(mask, np.cos(d * np.pi / 2) ** 2, 0.0)
        lat += dirn * 11.0 * bell
        speed -= 26.0 * bell
        entry = mask & (d < -0.3)
        brk[entry] = np.maximum(brk[entry], 0.8 * bell[entry])
        thr[mask] = np.minimum(thr[mask], 1 - 0.9 * bell[mask])

        yaw_implied = dirn * 11.0 * bell / np.maximum(speed, 5)
        gain = 1.7 if ci == 1 else 1.0            # corner 2: chronic understeer
        steer += 2.2 * gain * yaw_implied

        # late-stint oversteer at corners 3/4: counter-steer on exit
        if late and ci >= 2:
            exit_mask = mask & (d > 0.15)
            flip = exit_mask & (np.arange(n) % 4 < 2)   # ~50% of exit samples
            steer[flip] = -0.35 * dirn * np.abs(steer[flip] / (np.abs(steer[flip]) + 1e-9)) \
                          * (0.12 + 0.05 * bell[flip])

    yaw = lat / np.maximum(speed, 5)
    noise = np.random.default_rng(lap_i).normal
    return {
        'LapDistPct': pct.astype(np.float32),
        'Speed': (speed + noise(0, 0.3, n)).astype(np.float32),
        'Throttle': thr.astype(np.float32),
        'Brake': brk.astype(np.float32),
        'SteeringWheelAngle': (steer + noise(0, 0.004, n)).astype(np.float32),
        'LatAccel': (lat + noise(0, 0.15, n)).astype(np.float32),
        'YawRate': (yaw + noise(0, 0.004, n)).astype(np.float32),
    }


def build(n_laps=14, deg_s_per_lap=0.09, rr_press='24.0', wing='6', farb='5', path=None):
    yaml_blob = SESSION_YAML.format(rr_press=rr_press, wing=wing, farb=farb).encode()
    rows_per_lap = LAP_SECONDS * TICK
    total = rows_per_lap * n_laps

    offsets, off = {}, 0
    for name, tid in VARS:
        offsets[name] = off
        off += TYPE_SIZE[tid]
    buf_len = off

    data = bytearray(total * buf_len)
    lap_times = [91.0 + deg_s_per_lap * i for i in range(n_laps)]
    fuel0 = 40.0

    for li in range(n_laps):
        sig = lap_signals(li, n_laps, lap_times[li])
        base_row = li * rows_per_lap
        fuel_start = fuel0 - 2.4 * li
        for r in range(rows_per_lap):
            row_off = (base_row + r) * buf_len
            vals = {
                'Lap': li + 1,
                'LapDistPct': float(sig['LapDistPct'][r]),
                'LapLastLapTime': float(lap_times[li - 1]) if li > 0 else 0.0,
                'Speed': float(sig['Speed'][r]),
                'Throttle': float(sig['Throttle'][r]),
                'Brake': float(sig['Brake'][r]),
                'SteeringWheelAngle': float(sig['SteeringWheelAngle'][r]),
                'FuelLevel': fuel_start - 2.4 * (r / rows_per_lap),
                'LatAccel': float(sig['LatAccel'][r]),
                'YawRate': float(sig['YawRate'][r]),
                'OnPitRoad': False,
                'PlayerTrackSurface': 3,
            }
            for name, tid in VARS:
                struct.pack_into('<' + TYPE_FMT[tid], data, row_off + offsets[name], vals[name])

    n_vars = len(VARS)
    session_offset = 112 + 32
    var_hdr_offset = session_offset + len(yaml_blob)
    data_offset = var_hdr_offset + n_vars * 144

    hdr = struct.pack('<12i', 2, 0, TICK, 1, len(yaml_blob), session_offset,
                      n_vars, var_hdr_offset, 1, buf_len, 0, 0)
    # varBuf[0] at byte 48 within the 112-byte header
    hdr = hdr[:48] + struct.pack('<4i', total, data_offset, 0, 0) + hdr[64:]
    hdr = hdr.ljust(112, b'\x00')
    sub = struct.pack('<qddii', 0, 0.0, float(total / TICK), n_laps, total)

    var_hdrs = b''
    for name, tid in VARS:
        vh = bytearray(144)
        struct.pack_into('<3i', vh, 0, tid, offsets[name], 1)
        vh[16:16 + len(name)] = name.encode()
        var_hdrs += bytes(vh)

    blob = hdr + sub + yaml_blob + var_hdrs + bytes(data)
    if path:
        with open(path, 'wb') as f:
            f.write(blob)
    return blob


if __name__ == '__main__':
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else 'synth.ibt'
    b = build(path=out)
    print(f'wrote {out} ({len(b)/1048576:.1f} MB)')

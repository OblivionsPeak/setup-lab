# Setup Lab

**Stint-based setup engineering for iRacing** — built for the Operation Motorsport eMotorsport community.

Drive a stint, drop the telemetry file in, and get detailed, evidence-cited setup
recommendations — not "add a click of brake bias," but *what the data shows, which
knob to turn, how far, and what it will cost you*. The longer you and your teammates
use it on a car, the smarter it gets about that car.

## How to use it

**Web app (recommended): https://oblivionspeak.github.io/setup-lab/** — no
install, always up to date, runs 100% in your browser (nothing is uploaded).

1. Enable disk telemetry in iRacing (it's on by default; `alt+L` toggles).
2. Drive a stint — **3 or more consecutive clean laps**. Longer is better:
   a full fuel stint gives degradation analysis a real signal.
3. Open the web app (or launch `SetupLab.exe` — same tool, local install).
4. Drop in the `.ibt` file from `Documents\iRacing\telemetry\`.

The web app keeps history + per-car learning in your browser's local storage;
the EXE keeps them in `%LOCALAPPDATA%\SetupLab`. The analysis is identical —
`tests/parity.mjs` asserts the JS engine matches the Python engine exactly.

That's it. **No .sto file needed** — your full car setup is embedded in the
telemetry file and Setup Lab reads it from there, so the analysis always matches
the setup you actually drove.

## What you get

- **Stint summary** — best/median lap, consistency, pace trend per lap, fuel used.
- **Lap chart** with trend line across the stint.
- **Corner balance map** — every detected corner scored pushes ↔ loose.
- **Findings** — chronic understeer/oversteer, degradation-driven balance drift,
  exit traction trouble, entry instability, knife-edge inconsistency. Each finding
  cites its evidence (which corners, how much, when in the stint) and proposes
  changes **only for knobs your car actually has**, with direction, size,
  rationale, and the trade-off you're accepting.

## How it learns your car

Every analyzed stint is stored locally. When you bring a later stint on the same
car and track and the setup changed in a direction Setup Lab recommended, the
result is graded automatically: did pace improve, did the symptom shrink?
Graded outcomes reorder future recommendations — proposals that have worked on
this car float up, tagged `worked 3/4× on this car`; ones that haven't sink.
Fresh cars start from sound vehicle-dynamics first principles and improve with
every stint anyone feeds in.

All analysis is self-normalizing (each lap is compared to the driver's own
median through each corner), so any car iRacing runs works day one — road or oval.

## Privacy

100% local. No accounts, no uploads, no network calls. The database lives at
`%LOCALAPPDATA%\SetupLab\setuplab.db`.

## Running from source

```bat
pip install flask numpy pyyaml
python app.py
```

## Building the EXE

```bat
build.bat
```

## Tests

```bat
python tests\test_pipeline.py
```

Generates byte-valid synthetic `.ibt` telemetry with known injected setup
problems and asserts the full pipeline detects them, then verifies the
learning loop grades a followed recommendation as a win.

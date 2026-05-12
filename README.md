# pipesense

Field data acquisition, anomaly detection, and alarm logging for pipeline monitoring — built around real operational experience with OPC-UA, PI Historian, and multi-channel sensor networks.

---

## What it does

pipesense polls live instrument data, compares it against a stable baseline, and flags anything that looks wrong — either a sudden spike or a slow creep in the wrong direction. Alarms get written to a rotating JSON Lines log. All raw readings go into a compressed HDF5 archive for post-run analysis. (TO BE ADDED)

Everything — sites, channels, thresholds, detection parameters — is driven by YAML config. Swapping in a new site means editing a file, not touching code.

---

## Project layout (This is what version 1.0 would look like)

```
pipesense/
├── config/
│   ├── site_default.yaml        # reference site config (Oil Sands Terminal)
│   ├── loader.py                # loads + validates config at startup
│   └── schema.py                # dataclasses: PipesenseConfig, SiteConfig, ChannelConfig, …
├── sources/
│   ├── base.py                  # DataSource ABC + TagReading + SourceStatus
│   ├── opcua.py                 # live OPC-UA polling (asyncua)
│   ├── pi_historian.py          # OSIsoft PI Historian read
│   └── sim_*.py                 # channel simulators (flow, pressure, temp, level, vibration)
├── detection/
│   ├── base.py                  # Detector ABC + AlarmEvent + AlarmSeverity
│   ├── spike.py                 # SpikeDetector — rolling window (based on z-score)
│   ├── drift.py                 # DriftDetector — two-sided
│   └── engine.py                # DetectionEngine — per-channel fan-out
├── storage/
│   ├── archive.py               # ArchiveWriter — HDF5 with gzip compression
│   └── alarm_log.py             # AlarmLog — JSON Lines with rotation
└── cli.py                       # entry point: validate, info, status, run
```
I'm using Cursor to fill out the comments, clean up the code and add print statements (commented) for debugging


## Quickstart

Dependencies and project metadata are defined in `pyproject.toml`. To get set up:

```bash
# Create a virtual environment (Python 3.10+ required)
uv venv .venv

# Activate it
source .venv/bin/activate            # Linux / macOS
source .venv/Scripts/activate        # Windows

# Navigate to the pipesense directory and Install all dependencies from pyproject.toml
uv sync

# Confirm the install worked
uv run pipesense --help
```

---

## CLI usage

**Validate your site config** before doing anything else — catches threshold ordering errors and missing required fields:

```bash
uv run pipesense validate --config config/site_default.yaml
uv run pipesense info --config config/site_default.yaml    # human-readable summary
```

**Check source connectivity** — confirms OPC-UA or PI Historian is reachable and all configured tags are responding (TO BE ADDED):

```bash
uv run pipesense status --config config/site_default.yaml
```

**Start a monitoring run** — polls all channels, runs detection, and writes to archive and alarm log. Ctrl-C or SIGTERM shuts down cleanly (TO BE ADDED):

```bash
uv run pipesense run --config config/site_default.yaml
uv run pipesense run --config config/site_default.yaml --duration 3600   # stop after 1 hr
```

---

## Site config

Everything lives in YAML. Here's a minimal example:

```yaml
site:
  id: "LACT-001"
  name: "Oil Sands Terminal"
  description: "Main LACT terminal"
  location: "Alberta, Canada"
  opc_ua_endpoint: "opc.tcp://localhost:4840"

channels:
  id: "FT-101"
  name: "Inlet Flow Rate"
  opc_node: "ns=2;s=LACT001.FT101.PV"
  pi_tag: "OIL_SANDS.FT101.PV"
  unit: "m3/h"
  type: "flow"
  poll_interval_s: 5
  thresholds:
    low_low: 0.0
    low: 50.0
    high: 450.0
    high_high: 500.0

detection:
  spike:
    enabled: true
    z_threshold: 3.5         
    min_samples: 10           
  drift:
    enabled: true
    cusum_threshold: 5.0        
    cusum_slack: 0.5            
    window_s: 300             
```

Thresholds are validated at load time — `low_low < low < high < high_high` is enforced, and the loader will reject configs that violate this ordering.
Configurations without the required parameters will also be rejected.

---

## Detection

TBA

---

## Storage

TBA

---

## Running tests

```bash
pytest                              # full suite
pytest --cov=pipesense              # with coverage
pytest tests/test_integration.py    # end-to-end only
```

CI runs the matrix on Python 3.10+, planning to cover atleast 80%. 

---

## Key dependencies (will be updated as the project is developed)

| Package | Purpose |
|---|---|
| `asyncua` | OPC-UA client (live data) |
| `h5py >= 3.10` | HDF5 archiving |
| `pyyaml` | Config loading |
| `click` | CLI |
| `numpy` | Rolling stats, Cumulative Sum |
| `pytest` | Test suite |

---

## Design notes

TBA

# Touchline Demo

A portable synthetic football valuation UI/API. All players, clubs, values and
dates are fictional. This repository has fresh history containing only the
reviewed release tree. The original research repository remains private.

## What works

Search/filter 12 fictional players, inspect synthetic value histories and peer
comparisons, switch estimate modes, and submit validated scenarios. The backend
is Python/FastAPI; the UI is vanilla HTML/CSS/JavaScript. Research modules use
pandas, NumPy and scikit-learn. Node is optional, only for `npm run dev`.

**This build is not a real-player valuation predictor.** It uses original,
deterministic fictional data and a visible illustrative rule:
`100000 + minutes * 100 + goals * 200000 + assists * 100000`.
The previous-value mode retains the fictional earlier value. Display bands are
illustrative and uncalibrated. There are no demo accuracy scores or live data.

Earlier private research selected a previous-valuation baseline over learned
updates; a small PitchAPI pilot did not establish a better production model.
Its records, derived predictions and learned artifacts are not distributed in
this proposed public tree. No replacement-model improvement is claimed.

## Fresh clone

Supported/tested interpreter: **CPython 3.12** (tested with 3.12.4). Create the
environment inside the clone; no pre-existing personal folders are assumed.

Windows PowerShell:

```powershell
git clone https://github.com/Ankit70842/touchline-public.git
cd touchline-public
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --only-binary=:all: --timeout 120 -r requirements-lock.txt
.\.venv\Scripts\python.exe -m uvicorn touchline.api:app --host 127.0.0.1 --port 8000
```

macOS/Linux:

```sh
git clone https://github.com/Ankit70842/touchline-public.git
cd touchline-public
python3.12 -m venv .venv
.venv/bin/python -m pip install --only-binary=:all: --timeout 120 -r requirements-lock.txt
.venv/bin/python -m uvicorn touchline.api:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000;
API schemas are at `/docs`. No data download, API key, account or serialized model
is needed to run the demo. `requirements-lock.txt` pins the tested environment;
`requirements.txt` records compatibility bounds. Only Python 3.12 was tested.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The suite uses synthetic fixtures for dates, price lags, chronological splits,
missingness, identity ambiguity, own goals and request-budget behavior, plus
local API scenarios. It never needs real provider responses. A browser smoke
function is in `tests/browser_checks.js`; use an already installed Playwright CLI
with `tests/playwright.config.json`. Browser tools are optional development tools,
not production dependencies. No silent `npx` installation is required.

See [verification](VERIFICATION.md) for checks actually run and their limits.

## Data and security boundaries

- The public app never discovers or deserializes local `.joblib`/pickle files.
- All fictional values/dates are labeled as synthetic; real historical/live feeds
  are not connected. Private pilot data was league-only, not all competitions.
- Provider exports and learned models remain ignored local research assets.
  Do not redistribute them without independently established permission.
- Optional research code may use separately authorized local CSV/JSON fixtures;
  it is not an automatic source downloader or an endorsement of provider rights.
- Localhost serving is the supported deployment. Do not expose research collection
  commands, local credentials or caches through a public server.

## Licensing and release status

Original code, documentation and synthetic generator: [MIT](LICENSE), copyright
Ankit Chaurasia. Third-party dependencies and historical data are **not** relicensed
under MIT. Read [data notices](DATA_NOTICES.md) and
[third-party notices](THIRD_PARTY_NOTICES.md).

This repository was created with fresh history from the sanitized release tree;
no original Git objects were copied. The original research repository remains
private because its history retains provider material and personal paths. See
[publication review](docs/RELEASE_READINESS.md). No improved predictor is claimed.

# Contributing

This is a personal tool that's public so others can use/adapt it. PRs and
issues are welcome, especially fixes for the external data sources below,
which are the most likely things to break over time.

## Setup

```
git clone https://github.com/pwyller-creator/retirement-tripwires.git
cd retirement-tripwires
copy config.ini.example config.ini
```
Fill in a free FRED key in `config.ini` (fred.stlouisfed.org/docs/api/api_key.html),
then run `run.bat` — it creates a `.venv` and installs `requirements.txt`
automatically on first run.

## Before opening a PR

- Run the two checks CI runs, locally:
  ```
  .venv\Scripts\python.exe -m py_compile *.py
  .venv\Scripts\python.exe -c "import config, state, report, notify, pillar1_concentration, pillar2_capex, pillar3_macro, pillar4_regulatory"
  ```
- If you touched a pillar module, actually run `main.py` and read the output —
  several bugs in this codebase have been silent-failure types (an API
  returning empty/renamed fields, a wrong dict key) that don't throw and
  don't show up in a compile check. See `README.md`'s "Known limitations"
  section for the specific spots that have already bitten this project once.
- Keep dependencies minimal. This is meant to stay a small local script, not
  grow a framework — think twice before adding a new package to
  `requirements.txt`.

## Where things tend to break

- **FTC/DOJ RSS URLs** (`pillar4_regulatory.py` `FEEDS` dict) — government
  endpoints move without redirects. If a run reports `WARN: unreachable/empty
  feed(s)`, that's your signal.
- **SEC EDGAR full-text search** (`pillar2_capex.py`) — occasionally returns
  transient 500s; already tolerated as a non-fatal WARN, but a persistent
  failure likely means the API shape changed.
- **yfinance** (`pillar1_concentration.py`) — `fast_info` uses camelCase
  keys (`marketCap`) accessible only via attribute, not `.get()`. This exact
  mistake silently zeroed out Pillar 1 once already; if you're touching that
  file, watch for the same trap.
- **FOMC meeting dates** (`FOMC_2026_DATES` in `pillar3_macro.py`) — hardcoded
  per year, needs a manual update every January from
  federalreserve.gov/monetarypolicy/fomccalendars.htm.

## Scope

Pillar 2's capex-guidance scan only matches keywords in SEC filings, not
earnings-call transcripts (no free transcript API exists) — it's meant to
surface candidates for a human to read, not to auto-judge guidance changes.
Don't try to make it "smarter" without a real transcript source behind it;
that would just be false confidence.

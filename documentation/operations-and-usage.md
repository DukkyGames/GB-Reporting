# GB-Reporting — launch, update, and usage

This guide covers **local development**, **production (Linux + systemd + Gunicorn)**, **updates**, and **day-to-day use** of the web UI.

---

## Prerequisites

- **Python 3.10+** (3.11 or 3.12 recommended; match what you use in production).
- **WineDirect webservice** username and password with API access to orders, products, and inventory (same credentials the app uses today).
- Optional: **Tock** reservation exports as CSV for the Tours report.

---

## Configuration (environment variables)

Copy `.env.example` to `.env` and fill in real values. Never commit `.env`.

### WineDirect (`WINE_*`)

| Variable | Description |
|----------|-------------|
| `WINE_USERNAME` | Webservice username |
| `WINE_PASSWORD` | Webservice password |
| `WINE_REGION` | `us` (default) or AU equivalent per WineDirect |
| `WINE_VERSION` | API version, e.g. `v3` |
| `WINE_INVENTORY_FILTER` | Passed to inventory calls (see `.env.example`) |
| `WINE_FETCH_ORDER_DETAIL` | `1` to fetch line items per order (heavy; can hit rate limits). Default behavior in code is off unless set. |
| `WINE_ORDER_DETAIL_MAX` | Cap on detail fetches when enabled |
| `WINE_RATE_LIMIT_WAIT` | `1` to wait when rate-limited instead of failing quickly |

### Application

| Variable | Description |
|----------|-------------|
| `FLASK_SECRET_KEY` | Secret for sessions; **must** be strong in production |
| `ADMIN_USER` / `ADMIN_PASSWORD` | Initial admin login (created if missing) |
| `CACHE_DAYS` | How many days of orders the **scheduled full refresh** pulls (default `400`) |
| `CACHE_HOUR` / `CACHE_MINUTE` | Time-of-day for the nightly job; APScheduler’s default cron uses the **host’s local timezone**. The refresh window’s end date is computed in **UTC** in code—see `app.py` if you need exact semantics. |
| `LATEST_DAYS` | Window for the **every-5-minutes** incremental order refresh (default `7`) |
| `FLASK_ENV` | e.g. `production` |

### Gunicorn (production only)

| Variable | Description |
|----------|-------------|
| `GUNICORN_BIND` | Default `0.0.0.0:8000` |
| `GUNICORN_WORKERS` | Default `2` |

---

## Launch — local development

From the repository root:

```bash
python -m venv .venv
```

**Windows (PowerShell):**

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
# Edit .env with your credentials
python app.py
```

**Linux/macOS:**

```bash
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env
python app.py
```

The dev server listens on **`http://0.0.0.0:8000`** (all interfaces). Open **`http://127.0.0.1:8000`**, sign in with `ADMIN_USER` / `ADMIN_PASSWORD`.

**First run:** The app creates `data/app.db` and the admin user. WineDirect sync runs on the scheduler; the first full refresh can take a long time depending on `CACHE_DAYS` and order-detail settings.

---

## Launch — production (Gunicorn + systemd)

The repo includes **`gb-reporting.service.example`**, which assumes:

- App deployed at `/opt/gb-reporting/GB-Reporting`
- Virtualenv at `.venv` under that path
- Environment in `.env` loaded via `EnvironmentFile=`

Steps (adjust paths and user as needed):

1. Clone the repo to the server path.
2. Create `.env` with production secrets.
3. `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
4. Copy the example unit to systemd, e.g. `/etc/systemd/system/gb-reporting.service`, fix `User`, `Group`, `WorkingDirectory`, `EnvironmentFile`, and `ExecStart`.
5. `sudo systemctl daemon-reload && sudo systemctl enable gb-reporting && sudo systemctl start gb-reporting`

Gunicorn uses **`gunicorn.conf.py`**, which starts **`_bootstrap()`** in the master process so **scheduled refreshes** run (they do not start automatically if you only import the app without this hook).

Check logs:

```bash
sudo journalctl -u gb-reporting -f
```

---

## Update — production server (`update_app.sh`)

For a typical Linux deployment matching the script’s paths:

1. Ensure the service name in the script matches your unit (`gb-reporting`).
2. Run from a user that may use `sudo` for `systemctl`:

```bash
chmod +x update_app.sh
./update_app.sh
```

The script:

- Removes `__pycache__` trees (avoids git pull conflicts)
- Runs `git pull`
- Recreates `.venv` if missing
- `pip install -r requirements.txt`
- Restarts the systemd service and shows status

**Windows:** There is no equivalent script; pull changes, activate the venv, `pip install -r requirements.txt`, and restart your process (or Windows service if you use one).

---

## Update — dependency or code changes (any environment)

1. Pull latest code.
2. Activate the virtualenv.
3. `pip install -r requirements.txt`
4. Restart the app (Flask dev: stop and `python app.py` again; production: `systemctl restart gb-reporting`).

SQLite schema evolves via **`CREATE TABLE IF NOT EXISTS`** and column migrations inside `cache.py`; for unusual upgrades, back up `data/app.db` before deploying.

---

## Usage — web application

After login, navigation is via the main menu (dashboard, orders, inventory, products report, tours, settings).

### Dashboard (`/`)

- **Date range**: presets (this month, last 12 months, YTD, etc.) or custom start/end.
- **Units**: toggle **cases** vs **bottles** (cases use 12 bottles per case for display).
- Combines **WineDirect product sales** with **Tock tour collected** revenue in some KPIs when tour data exists.
- **Exports**: Excel / PDF for the current view (toolbar links).

### Orders (`/orders`)

- Search, filters (type, status, ship state, pickup vs ship, totals), date presets.
- Pagination (100 per page).
- Order detail shows line items and raw JSON when present.

### Inventory (`/inventory`)

- SKU search, hide zero, minimums per pool (barn / warehouse / library), pool checkboxes.
- Units: bottles or cases (12 per case).

### Products report (`/products-report`)

- Sales by product over the selected range; case/bottle toggle.

### Tours (`/tours`)

- Built from **`tock_transactions`** in SQLite.
- **Upload**: Tock export CSV; optional “replace existing” wipes prior imported rows.
- Experience multi-select filters; exports when data exists.

### Settings (`/settings`)

- **Cache status**: last run, errors, counts, rate-limit headers when available.
- Triggers such as full order refresh, products-only, inventory-only, or “latest” window map to POST routes under `/refresh/*` (also reachable from the UI where implemented).

### Automated refresh behavior

- **Cron job** (default daily at `CACHE_HOUR`:`CACHE_MINUTE`): orders (last `CACHE_DAYS`), products, inventory.
- **Every 5 minutes**: incremental orders for `LATEST_DAYS`, plus products and inventory.

If refreshes overlap, some paths skip when `refresh_in_progress` is already set.

---

## Troubleshooting

| Symptom | Things to check |
|---------|------------------|
| Login fails | `ADMIN_USER` / `ADMIN_PASSWORD`; DB at `data/app.db`; delete DB only if you intend to reset (recreates admin). |
| Empty dashboard | WineDirect credentials; sync still running; `CACHE_DAYS` too narrow; errors in Settings / `journalctl`. |
| Stuck / rate limit | Set `WINE_RATE_LIMIT_WAIT=1`; disable or cap order detail (`WINE_FETCH_ORDER_DETAIL`, `WINE_ORDER_DETAIL_MAX`). |
| Scheduler not running | Under Gunicorn, confirm **`gunicorn.conf.py`** is used (`when_ready` calls `_bootstrap`). |
| Tours empty | Import Tock CSV; confirm date range includes bookings. |

---

## Security notes

- Restrict network access (VPN or firewall) if the app is on the public internet.
- Use strong `FLASK_SECRET_KEY` and admin password in production.
- The app stores WineDirect data locally; protect backups of `data/app.db`.

---

## Related files

- `.env.example` — variable list with comments
- `gb-reporting.service.example` — systemd template
- `update_app.sh` — server update automation
- `documentation/context.md` — architecture summary

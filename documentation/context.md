# GB-Reporting — codebase context

## Purpose

**GB-Reporting** is an internal Flask web application for **Grimm's Bluff** winery reporting. It pulls commerce data from **WineDirect** (SOAP via `zeep`), stores it in a local **SQLite** database (`data/app.db`), and serves dashboards, order lists, inventory, product performance, and tour (Tock) analytics. Users sign in with credentials stored in the same database.

Reporting dates use **America/Los_Angeles** for “today” and display logic where relevant.

## Repository entry points

- **`README.md`** — Short quick start and links to documentation.
- **`documentation/operations-and-usage.md`** — Operators and users: launch, update, usage.
- **`documentation/context.md`** — This file (architecture and data flow).

## Main components

| Path | Role |
|------|------|
| `app.py` | Flask app: routes, auth (`Flask-Login`), scheduled cache refresh (`APScheduler`), Tock CSV import, exports. |
| `cache.py` | SQLite schema, admin user bootstrap, WineDirect sync (`refresh_orders_cache`, `refresh_products_cache`, `refresh_inventory_cache`), Tock upserts, rate-limit helpers. |
| `winedirect.py` | `WineDirectClient`: SOAP clients for orders, products, inventory; pagination and optional per-order detail fetching. |
| `reports.py` | Pandas/matplotlib report builders for dashboard and product reports. |
| `exporters.py` | Excel (`openpyxl`) and PDF (`reportlab`) exports. |
| `templates/` | Jinja2 HTML UI. |
| `static/` | CSS and assets. |
| `gunicorn.conf.py` | Production WSGI: binds workers, calls `app._bootstrap()` in `when_ready` so the scheduler runs under Gunicorn. |
| `gb-reporting.service.example` | systemd unit template for Linux servers. |
| `update_app.sh` | Server deploy helper: git pull, venv, `pip install`, `systemctl restart`. |

## Data flow

1. **WineDirect** credentials come from environment variables (`WINE_*`).
2. On startup (`python app.py`) or Gunicorn master `when_ready`, `_bootstrap()` runs `init_db`, ensures admin user, and starts the scheduler:
   - **Nightly** full-ish refresh: orders for the last `CACHE_DAYS` days, then products and inventory (`CACHE_HOUR`, `CACHE_MINUTE`).
   - **Every 5 minutes**: incremental order refresh for the last `LATEST_DAYS` (default 7), plus products and inventory.
3. **Tock** data is not pulled from an API; it is **uploaded** as CSV on the Tours page and stored in `tock_transactions`.

## Out of scope / legacy

- **`Reporting.py`**: Standalone script with a hardcoded CSV path; not wired into the Flask app. Treat as experimental or historical unless repurposed.

## UI typography

- Web UI and Plotly charts use **Arial** only (`static/styles.css`, `static/charts.js`).
- Matplotlib report images use Arial via `reports.py` rcParams.
- PDF exports register system Arial for ReportLab (`exporters.py`).

## Configuration

- **`GB_REPORTING_DB_PATH`** — Optional SQLite path (default `data/app.db`). Production systemd example uses `/var/lib/gb-reporting/app.db` with `StateDirectory=gb-reporting`.

## Last updated

- 2026-05-21: `GB_REPORTING_DB_PATH` and clearer SQLite startup errors for production permissions.
- 2026-05-21: Typography standardized on Arial across CSS, charts, and PDF export.
- 2026-05-21: Initial context and operations documentation added.

# GB-Reporting

Internal Flask app for winery reporting: **WineDirect** orders, products, and inventory (cached in SQLite), plus **Tock** tour data via CSV import.

## Documentation

- **[Launch, update, and usage](documentation/operations-and-usage.md)** — environment setup, dev server, production (Gunicorn/systemd), deploy script, and UI walkthrough.
- **[Codebase context](documentation/context.md)** — architecture, modules, and data flow.

## Quick start (development)

```bash
python -m venv .venv
# Windows: .\.venv\Scripts\Activate.ps1
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # Windows: copy .env.example .env
# Edit .env with WINE_* and FLASK_SECRET_KEY / admin credentials
python app.py
```

Open `http://127.0.0.1:8000` and sign in.

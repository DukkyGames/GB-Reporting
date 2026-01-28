from __future__ import annotations

import logging
logging.basicConfig(level=logging.INFO)
logging.getLogger("zeep").setLevel(logging.DEBUG)
logging.getLogger("zeep.transports").setLevel(logging.DEBUG)


import os
from zoneinfo import ZoneInfo
import json
from datetime import datetime, timedelta, date, timezone
import csv
from io import TextIOWrapper
from threading import Thread
import traceback

from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, render_template, request, redirect, url_for, flash, send_file, jsonify
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

from cache import (
    init_db,
    get_db,
    ensure_admin_user,
    refresh_orders_cache,
    refresh_products_cache,
    refresh_inventory_cache,
    clear_orders_cache,
    clear_products_cache,
    clear_tock_transactions,
    upsert_tock_transactions,
    rate_limit_check,
    set_cache_status,
    get_cache_status,
)
from reports import build_report, build_products_report
import pandas as pd
from exporters import (
    export_excel,
    export_pdf,
    export_orders_excel,
    export_orders_pdf,
    export_inventory_excel,
    export_inventory_pdf,
    export_products_excel,
    export_products_pdf,
    export_tours_excel,
    export_tours_pdf,
)

load_dotenv()

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_ROOT, "data", "app.db")

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "change-this")

login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.init_app(app)


class User:
    def __init__(self, user_id: int, username: str, password_hash: str):
        self.id = user_id
        self.username = username
        self.password_hash = password_hash

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    @property
    def is_authenticated(self) -> bool:
        return True

    @property
    def is_active(self) -> bool:
        return True

    @property
    def is_anonymous(self) -> bool:
        return False

    def get_id(self) -> str:
        return str(self.id)


@login_manager.user_loader
def load_user(user_id: str):
    db = get_db(DB_PATH)
    row = db.execute("SELECT id, username, password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
    db.close()
    if not row:
        return None
    return User(row[0], row[1], row[2])


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _default_dates() -> tuple[date, date]:
    today = _report_today()
    start = date(_add_months(today, -11).year, _add_months(today, -11).month, 1)
    return start, today


PACIFIC_TZ = ZoneInfo("America/Los_Angeles")


def _report_today() -> date:
    return datetime.now(PACIFIC_TZ).date()


def _add_months(value: date, months: int) -> date:
    year = value.year + (value.month - 1 + months) // 12
    month = (value.month - 1 + months) % 12 + 1
    day = min(value.day, 28)
    return date(year, month, day)


def _month_bounds(value: date) -> tuple[date, date]:
    first = date(value.year, value.month, 1)
    next_month = _add_months(first, 1)
    last = next_month - timedelta(days=1)
    return first, last


def _format_timestamp(value: str | None) -> str:
    if not value:
        return "—"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.year == 1970:
            return "—"
        return parsed.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        return value


def _build_cache_status() -> dict:
    status = get_cache_status(DB_PATH)
    in_progress = status.get("refresh_in_progress") == "1"
    last_error = status.get("refresh_error") or ""
    finished_at = _format_timestamp(status.get("refresh_finished_at"))
    if in_progress:
        result = "Running"
    elif last_error:
        result = "Failed"
    elif finished_at != "—":
        result = "Success"
    else:
        result = "—"
    return {
        "in_progress": in_progress,
        "started_at": _format_timestamp(status.get("refresh_started_at")),
        "finished_at": finished_at,
        "last_error": last_error,
        "result": result,
        "orders_count": status.get("orders_count") or "0",
        "items_count": status.get("items_count") or "0",
        "products_count": status.get("products_count") or "0",
        "inventory_count": status.get("inventory_count") or "0",
        "latest_order_date": status.get("latest_order_date") or "—",
        "rate_limit_limit": status.get("rate_limit_limit") or "—",
        "rate_limit_remaining": status.get("rate_limit_remaining") or "—",
        "rate_limit_reset_at": _format_timestamp(status.get("rate_limit_reset_at")),
        "refresh_page": status.get("refresh_page") or "0",
        "refresh_fetched": status.get("refresh_fetched") or "0",
        "refresh_total": status.get("refresh_total") or "0",
    }


def _apply_range_key(range_key: str, start_date: date | None, end_date: date | None) -> tuple[date | None, date | None]:
    today = _report_today()
    if range_key == "this_month":
        return date(today.year, today.month, 1), today
    if range_key == "last_month":
        first_this_month = date(today.year, today.month, 1)
        prev_month_last = first_this_month - timedelta(days=1)
        return date(prev_month_last.year, prev_month_last.month, 1), prev_month_last
    if range_key == "last_year":
        return date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)
    if range_key == "last_3_months":
        return date(_add_months(today, -2).year, _add_months(today, -2).month, 1), today
    if range_key == "last_12_months":
        return date(_add_months(today, -11).year, _add_months(today, -11).month, 1), today
    if range_key == "ytd":
        return date(today.year, 1, 1), today
    return start_date, end_date


def _parse_float(value: str | None) -> float:
    if value is None:
        return 0.0
    cleaned = str(value).replace("$", "").replace(",", "").strip()
    if cleaned == "":
        return 0.0
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _parse_int(value: str | None) -> int:
    if value is None:
        return 0
    cleaned = str(value).replace(",", "").strip()
    if cleaned == "":
        return 0
    try:
        return int(float(cleaned))
    except ValueError:
        return 0


def _tours_report(start_date: date, end_date: date) -> dict:
    db = get_db(DB_PATH)
    df = pd.read_sql_query(
        """
        SELECT *
        FROM tock_transactions
        WHERE booking_date IS NOT NULL AND booking_date != ''
        """,
        db,
    )
    db.close()

    if df.empty:
        return {"empty": True}

    df["booking_date"] = pd.to_datetime(df["booking_date"], errors="coerce")
    df["transaction_date"] = pd.to_datetime(df["transaction_date"], errors="coerce")
    df = df.dropna(subset=["booking_date"])
    df = df[(df["booking_date"].dt.date >= start_date) & (df["booking_date"].dt.date <= end_date)]
    if df.empty:
        return {"empty": True}

    df = df[df["action"].isin(["BOOKED", "RESCHEDULED"])]
    if df.empty:
        return {"empty": True}

    df = df.sort_values("transaction_date")
    df_latest = df.drop_duplicates(subset=["confirmation_code"], keep="last")

    total_bookings = len(df_latest)
    total_guests = int(df_latest["party_size"].fillna(0).sum())
    gross_sales = float(df_latest["total_price"].fillna(0).sum())
    collected = float(df_latest["payment_collected"].fillna(0).sum())
    comps = float(df_latest["comp"].fillna(0).sum())
    discounts = float(df_latest["discount"].fillna(0).sum())
    avg_party = total_guests / total_bookings if total_bookings else 0
    avg_rev_per_guest = gross_sales / total_guests if total_guests else 0

    kpis = [
        ("Bookings", f"{total_bookings:,}"),
        ("Guests", f"{total_guests:,}"),
        ("Gross Sales", f"${gross_sales:,.2f}"),
        ("Collected", f"${collected:,.2f}"),
        ("Comps", f"${comps:,.2f}"),
        ("Discounts", f"${discounts:,.2f}"),
        ("Avg Party Size", f"{avg_party:,.1f}"),
        ("Avg Revenue / Guest", f"${avg_rev_per_guest:,.2f}"),
    ]

    monthly = (
        df_latest.groupby(pd.Grouper(key="booking_date", freq="M"))
        .agg(
            bookings=("confirmation_code", "count"),
            guests=("party_size", "sum"),
            sales=("total_price", "sum"),
            collected=("payment_collected", "sum"),
        )
        .reset_index()
    )
    monthly["label"] = monthly["booking_date"].dt.strftime("%b %Y")

    exp_counts = (
        df_latest.groupby("experience")
        .agg(bookings=("confirmation_code", "count"), sales=("total_price", "sum"))
        .reset_index()
        .sort_values("bookings", ascending=False)
        .head(10)
    )

    charts = {
        "monthly": {
            "labels": monthly["label"].tolist(),
            "bookings": monthly["bookings"].fillna(0).astype(int).tolist(),
            "guests": monthly["guests"].fillna(0).astype(int).tolist(),
            "sales": monthly["sales"].fillna(0).astype(float).tolist(),
            "collected": monthly["collected"].fillna(0).astype(float).tolist(),
        },
        "experiences": {
            "labels": exp_counts["experience"].fillna("Unknown").tolist(),
            "bookings": exp_counts["bookings"].fillna(0).astype(int).tolist(),
            "sales": exp_counts["sales"].fillna(0).astype(float).tolist(),
        },
    }

    rows = df_latest.sort_values("booking_date", ascending=False).head(200)
    table = []
    for _, row in rows.iterrows():
        table.append(
            {
                "booking_date": row.get("booking_date").strftime("%Y-%m-%d") if not pd.isna(row.get("booking_date")) else "",
                "experience": row.get("experience") or "",
                "party_size": int(row.get("party_size") or 0),
                "total_price": float(row.get("total_price") or 0),
                "payment_collected": float(row.get("payment_collected") or 0),
                "confirmation_code": row.get("confirmation_code") or "",
            }
        )

    return {
        "empty": False,
        "kpis": kpis,
        "charts": charts,
        "table": table,
    }


def _build_inventory_view(
    *,
    unit: str,
    query: str,
    hide_zero: bool,
    min_total: float,
    min_barn: float,
    min_warehouse: float,
    min_library: float,
    only_barn: bool,
    only_warehouse: bool,
    only_library: bool,
) -> list[dict]:
    db = get_db(DB_PATH)
    rows = db.execute(
        """
        SELECT sku, inventory_pool, current_inventory
        FROM inventory
        ORDER BY sku, inventory_pool
        """
    ).fetchall()
    product_rows = db.execute(
        "SELECT sku, name FROM products"
    ).fetchall()
    db.close()
    product_map = {row["sku"]: row["name"] for row in product_rows if row["sku"]}
    inventory_rows: dict[str, dict[str, float]] = {}
    for row in rows:
        sku = row["sku"] or ""
        pool = (row["inventory_pool"] or "").strip().lower()
        qty = float(row["current_inventory"] or 0)
        if sku not in inventory_rows:
            inventory_rows[sku] = {
                "barn": 0.0,
                "warehouse": 0.0,
                "library": 0.0,
                "total": 0.0,
                "name": product_map.get(sku, ""),
            }
        if "barn" in pool:
            inventory_rows[sku]["barn"] += qty
        elif "warehouse" in pool:
            inventory_rows[sku]["warehouse"] += qty
        elif "library" in pool:
            inventory_rows[sku]["library"] += qty
        else:
            # Unclassified pools roll into total only.
            pass
        inventory_rows[sku]["total"] += qty

    inventory = [
        {"sku": sku, **values}
        for sku, values in sorted(inventory_rows.items(), key=lambda item: item[0])
    ]
    per_case = 12
    unit_divisor = per_case if unit == "case" else 1

    filtered = []
    any_only = only_barn or only_warehouse or only_library
    for row in inventory:
        total = row.get("total", 0) / unit_divisor
        barn = row.get("barn", 0) / unit_divisor
        warehouse = row.get("warehouse", 0) / unit_divisor
        library = row.get("library", 0) / unit_divisor

        if query and query not in row.get("sku", "").lower():
            continue
        if hide_zero and total <= 0:
            continue
        if total < min_total:
            continue
        if barn < min_barn:
            continue
        if warehouse < min_warehouse:
            continue
        if library < min_library:
            continue
        if any_only:
            matches_pool = False
            if only_barn and barn > 0:
                matches_pool = True
            if only_warehouse and warehouse > 0:
                matches_pool = True
            if only_library and library > 0:
                matches_pool = True
            if not matches_pool:
                continue
        display_row = dict(row)
        display_row["total"] = total
        display_row["barn"] = barn
        display_row["warehouse"] = warehouse
        display_row["library"] = library
        filtered.append(display_row)
    return filtered


@app.context_processor
def inject_export_urls():
    exportable = {"dashboard", "orders", "inventory", "products_report", "tours"}
    endpoint = request.endpoint
    if endpoint not in exportable:
        return {"export_excel_url": None, "export_pdf_url": None}
    args = request.args.to_dict(flat=True)
    return {
        "export_excel_url": url_for("export_current_excel", export_endpoint=endpoint, **args),
        "export_pdf_url": url_for("export_current_pdf", export_endpoint=endpoint, **args),
    }


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        db = get_db(DB_PATH)
        row = db.execute("SELECT id, username, password_hash FROM users WHERE username = ?", (username,)).fetchone()
        db.close()
        if row and check_password_hash(row[2], password):
            login_user(User(row[0], row[1], row[2]))
            return redirect(url_for("dashboard"))
        flash("Invalid username or password", "error")
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


@app.route("/", methods=["GET"])
@login_required
def dashboard():
    range_key = request.args.get("range", "last_12_months")
    unit = request.args.get("unit", "case")
    start_default, end_default = _default_dates()
    start_date = _parse_date(request.args.get("start")) or start_default
    end_date = _parse_date(request.args.get("end")) or end_default

    today = _report_today()
    if range_key == "this_month":
        start_date = date(today.year, today.month, 1)
        end_date = today
    elif range_key == "last_month":
        first_this_month = date(today.year, today.month, 1)
        prev_month_last = first_this_month - timedelta(days=1)
        start_date = date(prev_month_last.year, prev_month_last.month, 1)
        end_date = prev_month_last
    elif range_key == "last_year":
        start_date = date(today.year - 1, 1, 1)
        end_date = date(today.year - 1, 12, 31)
    elif range_key == "last_year":
        start_date = date(today.year - 1, 1, 1)
        end_date = date(today.year - 1, 12, 31)
    elif range_key == "last_3_months":
        start_date = date(_add_months(today, -2).year, _add_months(today, -2).month, 1)
        end_date = today
    elif range_key == "last_12_months":
        start_date = date(_add_months(today, -11).year, _add_months(today, -11).month, 1)
        end_date = today
    elif range_key == "ytd":
        start_date = date(today.year, 1, 1)
        end_date = today
    elif range_key == "custom":
        start_date = _parse_date(request.args.get("start")) or start_default
        end_date = _parse_date(request.args.get("end")) or end_default
    if start_date > end_date:
        start_date, end_date = end_date, start_date

    report = build_report(DB_PATH, start_date, end_date)
    tours_report = _tours_report(start_date, end_date)
    unit_label = "Cases" if unit == "case" else "Bottles"
    unit_factor = 12 if unit == "case" else 1
    if not report.get("empty"):
        updated_kpis = []
        for label, value in report.get("kpis", []):
            if label == "Bottles Sold":
                if unit == "case":
                    try:
                        raw_units = float(str(value).replace(",", ""))
                        value = f"{raw_units / unit_factor:,.1f}"
                    except ValueError:
                        pass
                    label = "Cases Sold"
            elif label == "Avg Bottle Price" and unit == "case":
                try:
                    raw_price = float(str(value).replace("$", "").replace(",", ""))
                    value = f"${raw_price * unit_factor:,.2f}"
                    label = "Avg Case Price"
                except ValueError:
                    label = "Avg Case Price"
            elif label == "Avg Bottles / Customer" and unit == "case":
                try:
                    raw_avg = float(str(value).replace(",", ""))
                    value = f"{raw_avg / unit_factor:,.1f}"
                    label = "Avg Cases / Customer"
                except ValueError:
                    label = "Avg Cases / Customer"
            updated_kpis.append((label, value))
        report["kpis"] = updated_kpis

        if "monthly" in report.get("charts", {}):
            units = report["charts"]["monthly"].get("units", [])
            if unit == "case":
                report["charts"]["monthly"]["units"] = [u / unit_factor for u in units]
    return render_template(
        "dashboard.html",
        report=report,
        tours_report=tours_report,
        range_key=range_key,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        unit=unit,
        unit_label=unit_label,
    )


@app.route("/settings", methods=["GET"])
@login_required
def settings():
    cache_status = _build_cache_status()
    return render_template("settings.html", cache_status=cache_status)


@app.route("/cache", methods=["GET"])
@login_required
def cache_view():
    return redirect(url_for("settings"))


@app.route("/products-report", methods=["GET"])
@login_required
def products_report():
    range_key = request.args.get("range", "last_12_months")
    unit = request.args.get("unit", "case")
    start_default, end_default = _default_dates()
    start_date = _parse_date(request.args.get("start")) or start_default
    end_date = _parse_date(request.args.get("end")) or end_default

    today = _report_today()
    if range_key == "this_month":
        start_date = date(today.year, today.month, 1)
        end_date = today
    elif range_key == "last_month":
        first_this_month = date(today.year, today.month, 1)
        prev_month_last = first_this_month - timedelta(days=1)
        start_date = date(prev_month_last.year, prev_month_last.month, 1)
        end_date = prev_month_last
    elif range_key == "last_3_months":
        start_date = date(_add_months(today, -2).year, _add_months(today, -2).month, 1)
        end_date = today
    elif range_key == "last_12_months":
        start_date = date(_add_months(today, -11).year, _add_months(today, -11).month, 1)
        end_date = today
    elif range_key == "ytd":
        start_date = date(today.year, 1, 1)
        end_date = today
    elif range_key == "custom":
        start_date = _parse_date(request.args.get("start")) or start_default
        end_date = _parse_date(request.args.get("end")) or end_default
    if start_date > end_date:
        start_date, end_date = end_date, start_date

    report = build_products_report(DB_PATH, start_date, end_date, unit=unit)
    return render_template(
        "products_report.html",
        report=report,
        range_key=range_key,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        unit=unit,
    )


@app.route("/inventory", methods=["GET"])
@login_required
def inventory():
    query = request.args.get("q", "").strip().lower()
    hide_zero = request.args.get("hide_zero", "0") == "1"
    min_total = float(request.args.get("min_total", "0") or 0)
    min_barn = float(request.args.get("min_barn", "0") or 0)
    min_warehouse = float(request.args.get("min_warehouse", "0") or 0)
    min_library = float(request.args.get("min_library", "0") or 0)
    only_barn = request.args.get("only_barn", "0") == "1"
    only_warehouse = request.args.get("only_warehouse", "0") == "1"
    only_library = request.args.get("only_library", "0") == "1"
    unit = request.args.get("unit", "bottle")
    filtered = _build_inventory_view(
        unit=unit,
        query=query,
        hide_zero=hide_zero,
        min_total=min_total,
        min_barn=min_barn,
        min_warehouse=min_warehouse,
        min_library=min_library,
        only_barn=only_barn,
        only_warehouse=only_warehouse,
        only_library=only_library,
    )

    return render_template(
        "inventory.html",
        inventory=filtered,
        hide_zero=hide_zero,
        query=query,
        min_total=min_total,
        min_barn=min_barn,
        min_warehouse=min_warehouse,
        min_library=min_library,
        only_barn=only_barn,
        only_warehouse=only_warehouse,
        only_library=only_library,
        show_barn=not (only_warehouse or only_library),
        show_warehouse=not (only_barn or only_library),
        show_library=not (only_barn or only_warehouse),
        unit=unit,
    )


@app.route("/tours", methods=["GET"])
@login_required
def tours():
    range_key = request.args.get("range", "last_12_months")
    start_default, end_default = _default_dates()
    start_date = _parse_date(request.args.get("start")) or start_default
    end_date = _parse_date(request.args.get("end")) or end_default
    start_date, end_date = _apply_range_key(range_key, start_date, end_date)
    if start_date and end_date and start_date > end_date:
        start_date, end_date = end_date, start_date

    report = _tours_report(start_date, end_date)
    return render_template(
        "tours.html",
        report=report,
        range_key=range_key,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
    )


@app.route("/tours/upload", methods=["POST"])
@login_required
def tours_upload():
    file = request.files.get("tock_csv")
    if not file or not file.filename:
        flash("Please select a Tock CSV file to upload.", "error")
        return redirect(url_for("tours"))

    replace_existing = request.form.get("replace_existing") == "1"
    if replace_existing:
        clear_tock_transactions(DB_PATH)

    rows = []
    wrapper = TextIOWrapper(file.stream, encoding="utf-8-sig")
    reader = csv.DictReader(wrapper)
    for row in reader:
        rows.append(
            {
                "transaction_id": row.get("Transaction ID"),
                "first_transaction_id": row.get("First Transaction ID"),
                "confirmation_code": row.get("Confirmation Code"),
                "action": row.get("Action"),
                "transaction_date": row.get("Transaction Date"),
                "booking_date": row.get("Booking Date"),
                "realized_date": row.get("Realized Date"),
                "experience": row.get("Experience"),
                "party_size": _parse_int(row.get("Party Size")),
                "price_per_person": _parse_float(row.get("Price Per Person")),
                "sub_total": _parse_float(row.get("Sub total")),
                "tax": _parse_float(row.get("Tax")),
                "service_charge": _parse_float(row.get("Service Charge")),
                "gratuity_charge": _parse_float(row.get("Gratuity Charge")),
                "fees": _parse_float(row.get("Fees")),
                "charges": _parse_float(row.get("Charges")),
                "comp": _parse_float(row.get("Comp")),
                "discount": _parse_float(row.get("Discount")),
                "total_price": _parse_float(row.get("Total Price")),
                "gift_card_value": _parse_float(row.get("Gift Card Value")),
                "payment_collected": _parse_float(row.get("Payment Collected")),
                "payment_refunded": _parse_float(row.get("Payment Refunded")),
                "net_payout_amount": _parse_float(row.get("Net Payout Amount")),
                "booking_method": row.get("Booking Method"),
                "payment_type": row.get("Payment Type"),
                "email": row.get("Email"),
                "first_name": row.get("First Name"),
                "last_name": row.get("Last Name"),
                "raw_json": json.dumps(row, default=str),
            }
        )

    inserted = upsert_tock_transactions(DB_PATH, rows)
    flash(f"Imported {inserted} Tock transactions.", "info")
    return redirect(url_for("tours"))


@app.route("/orders", methods=["GET"])
@login_required
def orders():
    query = request.args.get("q", "").strip()
    range_key = request.args.get("range", "custom")
    start_date = _parse_date(request.args.get("start"))
    end_date = _parse_date(request.args.get("end"))
    page = max(int(request.args.get("page", "1") or 1), 1)
    per_page = 100
    order_type = request.args.get("order_type", "").strip()
    order_status = request.args.get("order_status", "").strip()
    ship_state = request.args.get("ship_state", "").strip()
    pickup = request.args.get("pickup", "").strip()
    min_total = request.args.get("min_total", "").strip()
    max_total = request.args.get("max_total", "").strip()

    start_date, end_date = _apply_range_key(range_key, start_date, end_date)
    if range_key not in {"this_month", "last_month", "last_year", "last_3_months", "last_12_months", "ytd", "custom"}:
        range_key = "custom"

    if start_date and end_date and start_date > end_date:
        start_date, end_date = end_date, start_date

    filters = []
    params = []
    if start_date and end_date:
        filters.append("date(completed_date) BETWEEN ? AND ?")
        params.extend([start_date.isoformat(), end_date.isoformat()])
    elif start_date:
        filters.append("date(completed_date) >= ?")
        params.append(start_date.isoformat())
    elif end_date:
        filters.append("date(completed_date) <= ?")
        params.append(end_date.isoformat())

    if order_type:
        filters.append("order_type = ?")
        params.append(order_type)
    if order_status:
        filters.append("order_status = ?")
        params.append(order_status)
    if ship_state:
        filters.append("ship_state = ?")
        params.append(ship_state)
    if pickup in ("pickup", "ship"):
        filters.append("pickup = ?")
        params.append(1 if pickup == "pickup" else 0)
    if min_total:
        filters.append("order_total >= ?")
        params.append(min_total)
    if max_total:
        filters.append("order_total <= ?")
        params.append(max_total)

    db = get_db(DB_PATH)
    order_types = [row[0] for row in db.execute(
        "SELECT DISTINCT order_type FROM orders WHERE order_type IS NOT NULL AND order_type != '' ORDER BY order_type"
    ).fetchall()]
    if query:
        like = f"%{query}%"
        filters.append("(order_id LIKE ? OR order_number LIKE ? OR customer_id LIKE ?)")
        params.extend([like, like, like])
    else:
        pass
    where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
    count_row = db.execute(
        f"SELECT COUNT(*) FROM orders {where_clause}",
        params,
    ).fetchone()
    total_rows = int(count_row[0] if count_row else 0)
    total_pages = max((total_rows + per_page - 1) // per_page, 1)
    page = min(page, total_pages)
    offset = (page - 1) * per_page
    rows = db.execute(
        f"""
        SELECT order_id, order_number, completed_date,
               bill_first_name, bill_last_name, order_type, order_status, ship_state, order_total, pickup
        FROM orders
        {where_clause}
        ORDER BY CAST(order_number AS INTEGER) DESC, order_number DESC
        LIMIT ? OFFSET ?
        """,
        params + [per_page, offset],
    ).fetchall()
    db.close()
    orders_rows = []
    for row in rows:
        completed_raw = str(row["completed_date"] or "")
        if len(completed_raw) == 10:
            completed_local = completed_raw
        else:
            try:
                completed_dt = datetime.fromisoformat(completed_raw.replace("Z", "+00:00"))
                completed_local = completed_dt.astimezone(PACIFIC_TZ).strftime("%Y-%m-%d")
            except ValueError:
                completed_local = completed_raw
        orders_rows.append({**dict(row), "completed_date": completed_local})
    base_params = {k: v for k, v in request.args.items() if k != "page"}
    prev_url = None
    next_url = None
    if page > 1:
        prev_url = url_for("orders", **{**base_params, "page": page - 1})
    if page < total_pages:
        next_url = url_for("orders", **{**base_params, "page": page + 1})

    return render_template(
        "orders.html",
        orders=orders_rows,
        order_types=order_types,
        query=query,
        range_key=range_key,
        page=page,
        total_pages=total_pages,
        total_rows=total_rows,
        per_page=per_page,
        prev_url=prev_url,
        next_url=next_url,
        start_date=start_date.isoformat() if start_date else "",
        end_date=end_date.isoformat() if end_date else "",
        order_type=order_type,
        order_status=order_status,
        ship_state=ship_state,
        pickup=pickup,
        min_total=min_total,
        max_total=max_total,
    )


@app.route("/orders/<order_id>", methods=["GET"])
@login_required
def order_detail(order_id: str):
    db = get_db(DB_PATH)
    order = db.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
    items = db.execute(
        "SELECT * FROM order_items WHERE order_id = ? ORDER BY id",
        (order_id,),
    ).fetchall()
    db.close()
    if not order:
        flash("Order not found.", "error")
        return redirect(url_for("orders"))
    raw = order["raw_json"]
    raw_pretty = ""
    if raw:
        try:
            raw_pretty = json.dumps(json.loads(raw), indent=2)
        except (json.JSONDecodeError, TypeError):
            raw_pretty = raw
    return render_template(
        "order_detail.html",
        order=order,
        items=items,
        raw_pretty=raw_pretty,
    )


@app.route("/export/excel")
@login_required
def export_excel_route():
    start_date = _parse_date(request.args.get("start"))
    end_date = _parse_date(request.args.get("end"))
    if not start_date or not end_date:
        start_date, end_date = _default_dates()

    buffer = export_excel(DB_PATH, start_date, end_date)
    filename = f"grimms_bluff_report_{start_date.isoformat()}_{end_date.isoformat()}.xlsx"
    return send_file(buffer, as_attachment=True, download_name=filename, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.route("/export/pdf")
@login_required
def export_pdf_route():
    start_date = _parse_date(request.args.get("start"))
    end_date = _parse_date(request.args.get("end"))
    if not start_date or not end_date:
        start_date, end_date = _default_dates()

    buffer = export_pdf(DB_PATH, start_date, end_date)
    filename = f"grimms_bluff_report_{start_date.isoformat()}_{end_date.isoformat()}.pdf"
    return send_file(buffer, as_attachment=True, download_name=filename, mimetype="application/pdf")


@app.route("/export/current/excel/<export_endpoint>")
@login_required
def export_current_excel(export_endpoint: str):
    if export_endpoint == "dashboard":
        range_key = request.args.get("range", "last_12_months")
        start_date = _parse_date(request.args.get("start"))
        end_date = _parse_date(request.args.get("end"))
        start_date, end_date = _apply_range_key(range_key, start_date, end_date)
        if not start_date or not end_date:
            start_date, end_date = _default_dates()
        buffer = export_excel(DB_PATH, start_date, end_date)
        filename = f"grimms_bluff_report_{start_date.isoformat()}_{end_date.isoformat()}.xlsx"
        return send_file(
            buffer,
            as_attachment=True,
            download_name=filename,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    if export_endpoint == "products_report":
        range_key = request.args.get("range", "last_12_months")
        unit = request.args.get("unit", "case")
        start_date = _parse_date(request.args.get("start"))
        end_date = _parse_date(request.args.get("end"))
        start_date, end_date = _apply_range_key(range_key, start_date, end_date)
        if not start_date or not end_date:
            start_date, end_date = _default_dates()
        report = build_products_report(DB_PATH, start_date, end_date, unit=unit)
        buffer = export_products_excel(report, start_date, end_date)
        filename = f"grimms_bluff_products_{start_date.isoformat()}_{end_date.isoformat()}.xlsx"
        return send_file(
            buffer,
            as_attachment=True,
            download_name=filename,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    if export_endpoint == "inventory":
        query = request.args.get("q", "").strip().lower()
        hide_zero = request.args.get("hide_zero", "0") == "1"
        min_total = float(request.args.get("min_total", "0") or 0)
        min_barn = float(request.args.get("min_barn", "0") or 0)
        min_warehouse = float(request.args.get("min_warehouse", "0") or 0)
        min_library = float(request.args.get("min_library", "0") or 0)
        only_barn = request.args.get("only_barn", "0") == "1"
        only_warehouse = request.args.get("only_warehouse", "0") == "1"
        only_library = request.args.get("only_library", "0") == "1"
        unit = request.args.get("unit", "bottle")
        rows = _build_inventory_view(
            unit=unit,
            query=query,
            hide_zero=hide_zero,
            min_total=min_total,
            min_barn=min_barn,
            min_warehouse=min_warehouse,
            min_library=min_library,
            only_barn=only_barn,
            only_warehouse=only_warehouse,
            only_library=only_library,
        )
        buffer = export_inventory_excel(rows, unit=unit)
        filename = f"grimms_bluff_inventory_{_report_today().isoformat()}.xlsx"
        return send_file(
            buffer,
            as_attachment=True,
            download_name=filename,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    if export_endpoint == "orders":
        query = request.args.get("q", "").strip()
        range_key = request.args.get("range", "custom")
        start_date = _parse_date(request.args.get("start"))
        end_date = _parse_date(request.args.get("end"))
        page = max(int(request.args.get("page", "1") or 1), 1)
        per_page = 100
        order_type = request.args.get("order_type", "").strip()
        order_status = request.args.get("order_status", "").strip()
        ship_state = request.args.get("ship_state", "").strip()
        pickup = request.args.get("pickup", "").strip()
        min_total = request.args.get("min_total", "").strip()
        max_total = request.args.get("max_total", "").strip()

        start_date, end_date = _apply_range_key(range_key, start_date, end_date)
        if start_date and end_date and start_date > end_date:
            start_date, end_date = end_date, start_date

        filters = []
        params = []
        if start_date and end_date:
            filters.append("date(completed_date) BETWEEN ? AND ?")
            params.extend([start_date.isoformat(), end_date.isoformat()])
        elif start_date:
            filters.append("date(completed_date) >= ?")
            params.append(start_date.isoformat())
        elif end_date:
            filters.append("date(completed_date) <= ?")
            params.append(end_date.isoformat())

        if order_type:
            filters.append("order_type = ?")
            params.append(order_type)
        if order_status:
            filters.append("order_status = ?")
            params.append(order_status)
        if ship_state:
            filters.append("ship_state = ?")
            params.append(ship_state)
        if pickup in ("pickup", "ship"):
            filters.append("pickup = ?")
            params.append(1 if pickup == "pickup" else 0)
        if min_total:
            filters.append("order_total >= ?")
            params.append(min_total)
        if max_total:
            filters.append("order_total <= ?")
            params.append(max_total)
        if query:
            like = f"%{query}%"
            filters.append("(order_id LIKE ? OR order_number LIKE ? OR customer_id LIKE ?)")
            params.extend([like, like, like])

        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
        offset = (page - 1) * per_page
        db = get_db(DB_PATH)
        rows = db.execute(
            f"""
            SELECT order_id, order_number, completed_date,
                   bill_first_name, bill_last_name, order_type, order_status, ship_state, order_total, pickup
            FROM orders
            {where_clause}
            ORDER BY CAST(order_number AS INTEGER) DESC, order_number DESC
            LIMIT ? OFFSET ?
            """,
            params + [per_page, offset],
        ).fetchall()
        db.close()

        export_rows = []
        for row in rows:
            completed_raw = str(row["completed_date"] or "")
            if len(completed_raw) == 10:
                completed_local = completed_raw
            else:
                try:
                    completed_dt = datetime.fromisoformat(completed_raw.replace("Z", "+00:00"))
                    completed_local = completed_dt.astimezone(PACIFIC_TZ).strftime("%Y-%m-%d")
                except ValueError:
                    completed_local = completed_raw
            export_rows.append(
                {
                    "order_number": row["order_number"],
                    "completed_date": completed_local,
                    "customer": f"{row['bill_first_name']} {row['bill_last_name']}".strip(),
                    "order_type": row["order_type"],
                    "order_status": row["order_status"],
                    "ship_state": row["ship_state"],
                    "order_total": row["order_total"],
                    "pickup": "Yes" if row["pickup"] else "No",
                }
            )

        buffer = export_orders_excel(export_rows)
        filename = f"grimms_bluff_orders_page_{page}.xlsx"
        return send_file(
            buffer,
            as_attachment=True,
            download_name=filename,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    if export_endpoint == "tours":
        range_key = request.args.get("range", "last_12_months")
        start_default, end_default = _default_dates()
        start_date = _parse_date(request.args.get("start")) or start_default
        end_date = _parse_date(request.args.get("end")) or end_default
        start_date, end_date = _apply_range_key(range_key, start_date, end_date)
        if start_date and end_date and start_date > end_date:
            start_date, end_date = end_date, start_date
        report = _tours_report(start_date, end_date)
        if report.get("empty"):
            return ("No tour data for this range.", 400)
        buffer = export_tours_excel(report, start_date, end_date)
        filename = f"grimms_bluff_tours_{start_date.isoformat()}_{end_date.isoformat()}.xlsx"
        return send_file(
            buffer,
            as_attachment=True,
            download_name=filename,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    return ("Unsupported export", 400)


@app.route("/export/current/pdf/<export_endpoint>")
@login_required
def export_current_pdf(export_endpoint: str):
    if export_endpoint == "dashboard":
        range_key = request.args.get("range", "last_12_months")
        start_date = _parse_date(request.args.get("start"))
        end_date = _parse_date(request.args.get("end"))
        start_date, end_date = _apply_range_key(range_key, start_date, end_date)
        if not start_date or not end_date:
            start_date, end_date = _default_dates()
        buffer = export_pdf(DB_PATH, start_date, end_date)
        filename = f"grimms_bluff_report_{start_date.isoformat()}_{end_date.isoformat()}.pdf"
        return send_file(buffer, as_attachment=True, download_name=filename, mimetype="application/pdf")

    if export_endpoint == "products_report":
        range_key = request.args.get("range", "last_12_months")
        unit = request.args.get("unit", "case")
        start_date = _parse_date(request.args.get("start"))
        end_date = _parse_date(request.args.get("end"))
        start_date, end_date = _apply_range_key(range_key, start_date, end_date)
        if not start_date or not end_date:
            start_date, end_date = _default_dates()
        report = build_products_report(DB_PATH, start_date, end_date, unit=unit)
        buffer = export_products_pdf(report, start_date, end_date)
        filename = f"grimms_bluff_products_{start_date.isoformat()}_{end_date.isoformat()}.pdf"
        return send_file(buffer, as_attachment=True, download_name=filename, mimetype="application/pdf")

    if export_endpoint == "inventory":
        query = request.args.get("q", "").strip().lower()
        hide_zero = request.args.get("hide_zero", "0") == "1"
        min_total = float(request.args.get("min_total", "0") or 0)
        min_barn = float(request.args.get("min_barn", "0") or 0)
        min_warehouse = float(request.args.get("min_warehouse", "0") or 0)
        min_library = float(request.args.get("min_library", "0") or 0)
        only_barn = request.args.get("only_barn", "0") == "1"
        only_warehouse = request.args.get("only_warehouse", "0") == "1"
        only_library = request.args.get("only_library", "0") == "1"
        unit = request.args.get("unit", "bottle")
        rows = _build_inventory_view(
            unit=unit,
            query=query,
            hide_zero=hide_zero,
            min_total=min_total,
            min_barn=min_barn,
            min_warehouse=min_warehouse,
            min_library=min_library,
            only_barn=only_barn,
            only_warehouse=only_warehouse,
            only_library=only_library,
        )
        buffer = export_inventory_pdf(rows, unit=unit)
        filename = f"grimms_bluff_inventory_{_report_today().isoformat()}.pdf"
        return send_file(buffer, as_attachment=True, download_name=filename, mimetype="application/pdf")

    if export_endpoint == "orders":
        query = request.args.get("q", "").strip()
        range_key = request.args.get("range", "custom")
        start_date = _parse_date(request.args.get("start"))
        end_date = _parse_date(request.args.get("end"))
        page = max(int(request.args.get("page", "1") or 1), 1)
        per_page = 100
        order_type = request.args.get("order_type", "").strip()
        order_status = request.args.get("order_status", "").strip()
        ship_state = request.args.get("ship_state", "").strip()
        pickup = request.args.get("pickup", "").strip()
        min_total = request.args.get("min_total", "").strip()
        max_total = request.args.get("max_total", "").strip()

        start_date, end_date = _apply_range_key(range_key, start_date, end_date)
        if start_date and end_date and start_date > end_date:
            start_date, end_date = end_date, start_date

        filters = []
        params = []
        if start_date and end_date:
            filters.append("date(completed_date) BETWEEN ? AND ?")
            params.extend([start_date.isoformat(), end_date.isoformat()])
        elif start_date:
            filters.append("date(completed_date) >= ?")
            params.append(start_date.isoformat())
        elif end_date:
            filters.append("date(completed_date) <= ?")
            params.append(end_date.isoformat())

        if order_type:
            filters.append("order_type = ?")
            params.append(order_type)
        if order_status:
            filters.append("order_status = ?")
            params.append(order_status)
        if ship_state:
            filters.append("ship_state = ?")
            params.append(ship_state)
        if pickup in ("pickup", "ship"):
            filters.append("pickup = ?")
            params.append(1 if pickup == "pickup" else 0)
        if min_total:
            filters.append("order_total >= ?")
            params.append(min_total)
        if max_total:
            filters.append("order_total <= ?")
            params.append(max_total)
        if query:
            like = f"%{query}%"
            filters.append("(order_id LIKE ? OR order_number LIKE ? OR customer_id LIKE ?)")
            params.extend([like, like, like])

        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
        offset = (page - 1) * per_page
        db = get_db(DB_PATH)
        rows = db.execute(
            f"""
            SELECT order_id, order_number, completed_date,
                   bill_first_name, bill_last_name, order_type, order_status, ship_state, order_total, pickup
            FROM orders
            {where_clause}
            ORDER BY CAST(order_number AS INTEGER) DESC, order_number DESC
            LIMIT ? OFFSET ?
            """,
            params + [per_page, offset],
        ).fetchall()
        db.close()

        export_rows = []
        for row in rows:
            completed_raw = str(row["completed_date"] or "")
            if len(completed_raw) == 10:
                completed_local = completed_raw
            else:
                try:
                    completed_dt = datetime.fromisoformat(completed_raw.replace("Z", "+00:00"))
                    completed_local = completed_dt.astimezone(PACIFIC_TZ).strftime("%Y-%m-%d")
                except ValueError:
                    completed_local = completed_raw
            export_rows.append(
                {
                    "order_number": row["order_number"],
                    "completed_date": completed_local,
                    "customer": f"{row['bill_first_name']} {row['bill_last_name']}".strip(),
                    "order_type": row["order_type"],
                    "order_status": row["order_status"],
                    "ship_state": row["ship_state"],
                    "order_total": row["order_total"],
                    "pickup": "Yes" if row["pickup"] else "No",
                }
            )

        subtitle_parts = [f"Page {page}"]
        if start_date and end_date:
            subtitle_parts.append(f"{start_date.isoformat()} to {end_date.isoformat()}")
        subtitle = " • ".join(subtitle_parts)
        buffer = export_orders_pdf(export_rows, subtitle=subtitle)
        filename = f"grimms_bluff_orders_page_{page}.pdf"
        return send_file(buffer, as_attachment=True, download_name=filename, mimetype="application/pdf")

    if export_endpoint == "tours":
        range_key = request.args.get("range", "last_12_months")
        start_default, end_default = _default_dates()
        start_date = _parse_date(request.args.get("start")) or start_default
        end_date = _parse_date(request.args.get("end")) or end_default
        start_date, end_date = _apply_range_key(range_key, start_date, end_date)
        if start_date and end_date and start_date > end_date:
            start_date, end_date = end_date, start_date
        report = _tours_report(start_date, end_date)
        if report.get("empty"):
            return ("No tour data for this range.", 400)
        buffer = export_tours_pdf(report, start_date, end_date)
        filename = f"grimms_bluff_tours_{start_date.isoformat()}_{end_date.isoformat()}.pdf"
        return send_file(buffer, as_attachment=True, download_name=filename, mimetype="application/pdf")

    return ("Unsupported export", 400)


@app.route("/refresh/orders", methods=["POST"])
@login_required
def refresh_orders():
    start_date = None
    end_date = None
    if not start_date or not end_date:
        cache_days = int(os.environ.get("CACHE_DAYS", "400"))
        cache_days = max(cache_days, 1)
        end_date = datetime.now(timezone.utc).date()
        start_date = end_date - timedelta(days=cache_days - 1)

    def _run():
        set_cache_status(
            DB_PATH,
            refresh_in_progress="1",
            refresh_started_at=datetime.now(timezone.utc).isoformat(),
            refresh_error="",
        )
        try:
            clear_orders_cache(DB_PATH)
            refresh_orders_cache(DB_PATH, start_date, end_date)
            db = get_db(DB_PATH)
            orders_count = db.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
            items_count = db.execute("SELECT COUNT(*) FROM order_items").fetchone()[0]
            products_count = db.execute("SELECT COUNT(*) FROM products").fetchone()[0]
            inventory_count = db.execute("SELECT COUNT(*) FROM inventory").fetchone()[0]
            latest_order = db.execute("SELECT MAX(date(completed_date)) FROM orders").fetchone()[0]
            db.close()
            set_cache_status(
                DB_PATH,
                refresh_finished_at=datetime.now(timezone.utc).isoformat(),
                refresh_in_progress="0",
                orders_count=str(orders_count),
                items_count=str(items_count),
                products_count=str(products_count),
                inventory_count=str(inventory_count),
                latest_order_date=latest_order or "",
            )
        except Exception as exc:
            set_cache_status(
                DB_PATH,
                refresh_finished_at=datetime.now(timezone.utc).isoformat(),
                refresh_in_progress="0",
                refresh_error=f"{exc}\n{traceback.format_exc()}",
            )

    Thread(target=_run, daemon=True).start()
    flash("Cache refresh started. It may take a few minutes.", "info")
    return redirect(url_for("dashboard"))


@app.route("/refresh/products", methods=["POST"])
@login_required
def refresh_products():
    def _run():
        set_cache_status(
            DB_PATH,
            refresh_in_progress="1",
            refresh_started_at=datetime.now(timezone.utc).isoformat(),
            refresh_error="",
        )
        try:
            clear_products_cache(DB_PATH)
            refresh_products_cache(DB_PATH)
            db = get_db(DB_PATH)
            products_count = db.execute("SELECT COUNT(*) FROM products").fetchone()[0]
            inventory_count = db.execute("SELECT COUNT(*) FROM inventory").fetchone()[0]
            db.close()
            set_cache_status(
                DB_PATH,
                refresh_finished_at=datetime.now(timezone.utc).isoformat(),
                refresh_in_progress="0",
                products_count=str(products_count),
                inventory_count=str(inventory_count),
            )
        except Exception as exc:
            set_cache_status(
                DB_PATH,
                refresh_finished_at=datetime.now(timezone.utc).isoformat(),
                refresh_in_progress="0",
                refresh_error=f"{exc}\n{traceback.format_exc()}",
            )

    Thread(target=_run, daemon=True).start()
    flash("Products refresh started.", "info")
    return redirect(url_for("dashboard"))


@app.route("/refresh/inventory", methods=["POST"])
@login_required
def refresh_inventory():
    def _run():
        set_cache_status(
            DB_PATH,
            refresh_in_progress="1",
            refresh_started_at=datetime.now(timezone.utc).isoformat(),
            refresh_error="",
        )
        try:
            refresh_inventory_cache(DB_PATH)
            db = get_db(DB_PATH)
            inventory_count = db.execute("SELECT COUNT(*) FROM inventory").fetchone()[0]
            db.close()
            set_cache_status(
                DB_PATH,
                refresh_finished_at=datetime.now(timezone.utc).isoformat(),
                refresh_in_progress="0",
                inventory_count=str(inventory_count),
            )
        except Exception as exc:
            set_cache_status(
                DB_PATH,
                refresh_finished_at=datetime.now(timezone.utc).isoformat(),
                refresh_in_progress="0",
                refresh_error=f"{exc}\n{traceback.format_exc()}",
            )

    Thread(target=_run, daemon=True).start()
    flash("Inventory refresh started.", "info")
    return redirect(url_for("dashboard"))


@app.route("/refresh/latest", methods=["POST"])
@login_required
def refresh_latest():
    def _run():
        if get_cache_status(DB_PATH).get("refresh_in_progress") == "1":
            return
        set_cache_status(
            DB_PATH,
            refresh_in_progress="1",
            refresh_started_at=datetime.now(timezone.utc).isoformat(),
            refresh_error="",
        )
        try:
            latest_days = int(os.environ.get("LATEST_DAYS", "7"))
            latest_days = max(latest_days, 1)
            end_date = datetime.now(timezone.utc).date()
            start_date = end_date - timedelta(days=latest_days - 1)
            refresh_orders_cache(DB_PATH, start_date, end_date)
            db = get_db(DB_PATH)
            orders_count = db.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
            items_count = db.execute("SELECT COUNT(*) FROM order_items").fetchone()[0]
            products_count = db.execute("SELECT COUNT(*) FROM products").fetchone()[0]
            inventory_count = db.execute("SELECT COUNT(*) FROM inventory").fetchone()[0]
            latest_order = db.execute("SELECT MAX(date(completed_date)) FROM orders").fetchone()[0]
            db.close()
            set_cache_status(
                DB_PATH,
                refresh_finished_at=datetime.now(timezone.utc).isoformat(),
                refresh_in_progress="0",
                orders_count=str(orders_count),
                items_count=str(items_count),
                products_count=str(products_count),
                inventory_count=str(inventory_count),
                latest_order_date=latest_order or "",
            )
        except Exception as exc:
            set_cache_status(
                DB_PATH,
                refresh_finished_at=datetime.now(timezone.utc).isoformat(),
                refresh_in_progress="0",
                refresh_error=f"{exc}\n{traceback.format_exc()}",
            )

    Thread(target=_run, daemon=True).start()
    flash("Latest data refresh started.", "info")
    return redirect(url_for("dashboard"))


@app.route("/cache-status", methods=["GET"])
@login_required
def cache_status():
    return jsonify(_build_cache_status())


@app.route("/rate-check", methods=["POST"])
@login_required
def rate_check():
    try:
        rate_limit_check(DB_PATH)
        flash("Rate limit checked.", "info")
    except Exception as exc:
        flash(f"Rate limit check failed: {exc}", "error")
    return redirect(url_for("dashboard"))


def _schedule_cache_refresh():
    cache_days = int(os.environ.get("CACHE_DAYS", "400"))
    cache_days = max(cache_days, 1)
    hour = int(os.environ.get("CACHE_HOUR", "2"))
    minute = int(os.environ.get("CACHE_MINUTE", "15"))

    def _run():
        end_date = datetime.now(timezone.utc).date()
        start_date = end_date - timedelta(days=cache_days - 1)
        set_cache_status(
            DB_PATH,
            refresh_in_progress="1",
            refresh_started_at=datetime.now(timezone.utc).isoformat(),
            refresh_error="",
        )
        try:
            refresh_orders_cache(DB_PATH, start_date, end_date)
            refresh_products_cache(DB_PATH)
            refresh_inventory_cache(DB_PATH)
            db = get_db(DB_PATH)
            orders_count = db.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
            items_count = db.execute("SELECT COUNT(*) FROM order_items").fetchone()[0]
            products_count = db.execute("SELECT COUNT(*) FROM products").fetchone()[0]
            inventory_count = db.execute("SELECT COUNT(*) FROM inventory").fetchone()[0]
            latest_order = db.execute("SELECT MAX(date(completed_date)) FROM orders").fetchone()[0]
            db.close()
            set_cache_status(
                DB_PATH,
                refresh_finished_at=datetime.now(timezone.utc).isoformat(),
                refresh_in_progress="0",
                orders_count=str(orders_count),
                items_count=str(items_count),
                products_count=str(products_count),
                inventory_count=str(inventory_count),
                latest_order_date=latest_order or "",
            )
        except Exception as exc:
            set_cache_status(
                DB_PATH,
                refresh_finished_at=datetime.now(timezone.utc).isoformat(),
                refresh_in_progress="0",
                refresh_error=f"{exc}\n{traceback.format_exc()}",
            )

    def _run_latest():
        if get_cache_status(DB_PATH).get("refresh_in_progress") == "1":
            return
        set_cache_status(
            DB_PATH,
            refresh_in_progress="1",
            refresh_started_at=datetime.now(timezone.utc).isoformat(),
            refresh_error="",
        )
        try:
            latest_days = int(os.environ.get("LATEST_DAYS", "7"))
            latest_days = max(latest_days, 1)
            end_date = datetime.now(timezone.utc).date()
            start_date = end_date - timedelta(days=latest_days - 1)
            refresh_orders_cache(DB_PATH, start_date, end_date)
            refresh_products_cache(DB_PATH)
            refresh_inventory_cache(DB_PATH)
            db = get_db(DB_PATH)
            orders_count = db.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
            items_count = db.execute("SELECT COUNT(*) FROM order_items").fetchone()[0]
            products_count = db.execute("SELECT COUNT(*) FROM products").fetchone()[0]
            inventory_count = db.execute("SELECT COUNT(*) FROM inventory").fetchone()[0]
            latest_order = db.execute("SELECT MAX(date(completed_date)) FROM orders").fetchone()[0]
            db.close()
            set_cache_status(
                DB_PATH,
                refresh_finished_at=datetime.now(timezone.utc).isoformat(),
                refresh_in_progress="0",
                orders_count=str(orders_count),
                items_count=str(items_count),
                products_count=str(products_count),
                inventory_count=str(inventory_count),
                latest_order_date=latest_order or "",
            )
        except Exception as exc:
            set_cache_status(
                DB_PATH,
                refresh_finished_at=datetime.now(timezone.utc).isoformat(),
                refresh_in_progress="0",
                refresh_error=f"{exc}\n{traceback.format_exc()}",
            )

    scheduler = BackgroundScheduler()
    scheduler.add_job(_run, "cron", hour=hour, minute=minute)
    scheduler.add_job(_run_latest, "interval", minutes=5)
    scheduler.start()


def _bootstrap():
    init_db(DB_PATH)
    ensure_admin_user(DB_PATH)
    _schedule_cache_refresh()


if __name__ == "__main__":
    _bootstrap()
    app.run(host="0.0.0.0", port=8000, debug=True)

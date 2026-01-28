from __future__ import annotations

import logging
logging.basicConfig(level=logging.INFO)
logging.getLogger("zeep").setLevel(logging.DEBUG)
logging.getLogger("zeep.transports").setLevel(logging.DEBUG)


import os
from zoneinfo import ZoneInfo
import json
from datetime import datetime, timedelta, date, timezone
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
    rate_limit_check,
    set_cache_status,
    get_cache_status,
)
from reports import build_report, build_products_report
from exporters import export_excel, export_pdf

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

    report = build_report(DB_PATH, start_date, end_date)
    return render_template(
        "dashboard.html",
        report=report,
        range_key=range_key,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
    )


@app.route("/cache", methods=["GET"])
@login_required
def cache_view():
    cache_status = _build_cache_status()
    return render_template("cache.html", cache_status=cache_status)


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


@app.route("/orders", methods=["GET"])
@login_required
def orders():
    query = request.args.get("q", "").strip()
    start_date = _parse_date(request.args.get("start"))
    end_date = _parse_date(request.args.get("end"))
    order_type = request.args.get("order_type", "").strip()
    order_status = request.args.get("order_status", "").strip()
    ship_state = request.args.get("ship_state", "").strip()
    pickup = request.args.get("pickup", "").strip()
    min_total = request.args.get("min_total", "").strip()
    max_total = request.args.get("max_total", "").strip()

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
    rows = db.execute(
        f"""
        SELECT order_id, order_number, completed_date,
               bill_first_name, bill_last_name, order_type, order_status, ship_state, order_total, pickup
        FROM orders
        {where_clause}
        ORDER BY CAST(order_number AS INTEGER) DESC, order_number DESC
        LIMIT 500
        """,
        params,
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
    return render_template(
        "orders.html",
        orders=orders_rows,
        order_types=order_types,
        query=query,
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

    scheduler = BackgroundScheduler()
    scheduler.add_job(_run, "cron", hour=hour, minute=minute)
    scheduler.start()


def _bootstrap():
    init_db(DB_PATH)
    ensure_admin_user(DB_PATH)
    _schedule_cache_refresh()


if __name__ == "__main__":
    _bootstrap()
    app.run(host="0.0.0.0", port=8000, debug=True)

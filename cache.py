from __future__ import annotations

import json
import os
import sqlite3
from datetime import date, datetime, timezone
from typing import Iterable

from werkzeug.security import generate_password_hash

from winedirect import WineDirectClient


def get_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    db = get_db(path)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS orders (
            order_id TEXT PRIMARY KEY,
            order_number TEXT,
            completed_date TEXT,
            submitted_date TEXT,
            date_modified TEXT,
            shipped_date TEXT,
            order_type TEXT,
            order_status TEXT,
            ship_state TEXT,
            customer_id TEXT,
            bill_first_name TEXT,
            bill_last_name TEXT,
            ship_first_name TEXT,
            ship_last_name TEXT,
            bill_address TEXT,
            bill_address2 TEXT,
            bill_city TEXT,
            bill_state TEXT,
            bill_zip TEXT,
            bill_country TEXT,
            bill_email TEXT,
            bill_phone TEXT,
            ship_address TEXT,
            ship_address2 TEXT,
            ship_city TEXT,
            ship_state_code TEXT,
            ship_zip TEXT,
            ship_country TEXT,
            ship_email TEXT,
            ship_phone TEXT,
            gift_message TEXT,
            order_notes TEXT,
            payment_status TEXT,
            shipping_status TEXT,
            shipping_type TEXT,
            tracking_number TEXT,
            website_id TEXT,
            is_external_order INTEGER,
            is_pending_pickup INTEGER,
            is_arms_order INTEGER,
            pickup INTEGER,
            order_number_long TEXT,
            pickup_date TEXT,
            pickup_location_code TEXT,
            payment_terms TEXT,
            price_level TEXT,
            sales_associate TEXT,
            sales_attribute TEXT,
            transaction_type TEXT,
            source_code TEXT,
            wholesale_number TEXT,
            requested_delivery_date TEXT,
            requested_ship_date TEXT,
            sent_to_fulfillment_date TEXT,
            future_ship_date TEXT,
            marketplace TEXT,
            order_total REAL,
            taxes REAL,
            shipping_paid REAL,
            shipping REAL,
            sub_total REAL,
            tip REAL,
            total REAL,
            total_after_tip REAL,
            net_sales REAL,
            units REAL,
            raw_json TEXT
        );

        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT,
            sku TEXT,
            product_name TEXT,
            quantity REAL,
            net_sales REAL,
            product_id TEXT,
            product_skuid TEXT,
            price REAL,
            original_price REAL,
            department TEXT,
            department_code TEXT,
            inventory_pool TEXT,
            is_non_taxable INTEGER,
            is_subsku INTEGER,
            sales_tax REAL,
            shipping_sku TEXT,
            shipping_service TEXT,
            sub_department TEXT,
            sub_department_code TEXT,
            subtitle TEXT,
            title TEXT,
            item_type TEXT,
            unit_description TEXT,
            weight REAL,
            cost_of_good REAL,
            custom_tax1 REAL,
            custom_tax2 REAL,
            custom_tax3 REAL,
            parent_sku TEXT,
            parent_skuid TEXT,
            shipped_date TEXT,
            tracking_number TEXT,
            raw_json TEXT
        );

        CREATE TABLE IF NOT EXISTS products (
            product_id TEXT PRIMARY KEY,
            sku TEXT,
            name TEXT,
            last_updated TEXT,
            raw_json TEXT
        );

        CREATE TABLE IF NOT EXISTS inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sku TEXT,
            inventory_pool TEXT,
            inventory_pool_id TEXT,
            website_id TEXT,
            current_inventory REAL,
            raw_json TEXT
        );

        CREATE TABLE IF NOT EXISTS cache_status (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        """
    )
    db.commit()
    _ensure_order_columns(db)
    _ensure_order_item_columns(db)
    _ensure_inventory_columns(db)
    db.close()


def _ensure_order_columns(db: sqlite3.Connection) -> None:
    cursor = db.execute("PRAGMA table_info(orders)")
    existing = {row[1] for row in cursor.fetchall()}
    columns = {
        "submitted_date": "TEXT",
        "date_modified": "TEXT",
        "shipped_date": "TEXT",
        "bill_address": "TEXT",
        "bill_address2": "TEXT",
        "bill_city": "TEXT",
        "bill_state": "TEXT",
        "bill_zip": "TEXT",
        "bill_country": "TEXT",
        "bill_email": "TEXT",
        "bill_phone": "TEXT",
        "ship_address": "TEXT",
        "ship_address2": "TEXT",
        "ship_city": "TEXT",
        "ship_state_code": "TEXT",
        "ship_zip": "TEXT",
        "ship_country": "TEXT",
        "ship_email": "TEXT",
        "ship_phone": "TEXT",
        "bill_first_name": "TEXT",
        "bill_last_name": "TEXT",
        "ship_first_name": "TEXT",
        "ship_last_name": "TEXT",
        "order_status": "TEXT",
        "gift_message": "TEXT",
        "order_notes": "TEXT",
        "payment_status": "TEXT",
        "shipping_status": "TEXT",
        "shipping_type": "TEXT",
        "tracking_number": "TEXT",
        "website_id": "TEXT",
        "is_external_order": "INTEGER",
        "is_pending_pickup": "INTEGER",
        "is_arms_order": "INTEGER",
        "order_number_long": "TEXT",
        "pickup_date": "TEXT",
        "pickup_location_code": "TEXT",
        "payment_terms": "TEXT",
        "price_level": "TEXT",
        "sales_associate": "TEXT",
        "sales_attribute": "TEXT",
        "transaction_type": "TEXT",
        "source_code": "TEXT",
        "wholesale_number": "TEXT",
        "requested_delivery_date": "TEXT",
        "requested_ship_date": "TEXT",
        "sent_to_fulfillment_date": "TEXT",
        "future_ship_date": "TEXT",
        "marketplace": "TEXT",
        "shipping": "REAL",
        "sub_total": "REAL",
        "tip": "REAL",
        "total": "REAL",
        "total_after_tip": "REAL",
        "raw_json": "TEXT",
    }
    for name, col_type in columns.items():
        if name not in existing:
            db.execute(f"ALTER TABLE orders ADD COLUMN {name} {col_type}")
    db.commit()


def _ensure_order_item_columns(db: sqlite3.Connection) -> None:
    cursor = db.execute("PRAGMA table_info(order_items)")
    existing = {row[1] for row in cursor.fetchall()}
    columns = {
        "product_id": "TEXT",
        "product_skuid": "TEXT",
        "price": "REAL",
        "original_price": "REAL",
        "department": "TEXT",
        "department_code": "TEXT",
        "inventory_pool": "TEXT",
        "is_non_taxable": "INTEGER",
        "is_subsku": "INTEGER",
        "sales_tax": "REAL",
        "shipping_sku": "TEXT",
        "shipping_service": "TEXT",
        "sub_department": "TEXT",
        "sub_department_code": "TEXT",
        "subtitle": "TEXT",
        "title": "TEXT",
        "item_type": "TEXT",
        "unit_description": "TEXT",
        "weight": "REAL",
        "cost_of_good": "REAL",
        "custom_tax1": "REAL",
        "custom_tax2": "REAL",
        "custom_tax3": "REAL",
        "parent_sku": "TEXT",
        "parent_skuid": "TEXT",
        "shipped_date": "TEXT",
        "tracking_number": "TEXT",
        "raw_json": "TEXT",
    }
    for name, col_type in columns.items():
        if name not in existing:
            db.execute(f"ALTER TABLE order_items ADD COLUMN {name} {col_type}")
    db.commit()


def _ensure_inventory_columns(db: sqlite3.Connection) -> None:
    cursor = db.execute("PRAGMA table_info(inventory)")
    existing = {row[1] for row in cursor.fetchall()}
    columns = {
        "sku": "TEXT",
        "inventory_pool": "TEXT",
        "inventory_pool_id": "TEXT",
        "website_id": "TEXT",
        "current_inventory": "REAL",
        "raw_json": "TEXT",
    }
    for name, col_type in columns.items():
        if name not in existing:
            db.execute(f"ALTER TABLE inventory ADD COLUMN {name} {col_type}")
    db.commit()


def set_cache_status(path: str, **values: str) -> None:
    if not values:
        return
    # Use a short timeout to reduce "database is locked" during long refresh writes.
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    for key, value in values.items():
        db.execute(
            "INSERT OR REPLACE INTO cache_status (key, value) VALUES (?, ?)",
            (key, value),
        )
    db.commit()
    db.close()


def get_cache_status(path: str) -> dict[str, str]:
    db = get_db(path)
    rows = db.execute("SELECT key, value FROM cache_status").fetchall()
    db.close()
    return {row[0]: row[1] for row in rows}


def _update_rate_limit_status(path: str, rate_limit: dict[str, str]) -> None:
    if not rate_limit:
        return
    updates = {
        "rate_limit_limit": rate_limit.get("limit", "") or "",
        "rate_limit_remaining": rate_limit.get("remaining", "") or "",
        "rate_limit_reset": rate_limit.get("reset", "") or "",
        "rate_limit_reset_at": "",
    }
    reset_epoch = rate_limit.get("reset")
    if reset_epoch:
        try:
            reset_value = int(reset_epoch)
            # Handle ms epoch values by converting to seconds.
            if reset_value > 2_000_000_000_000:
                reset_value = reset_value // 1000
            if reset_value > 0:
                reset_at = datetime.fromtimestamp(reset_value, tz=timezone.utc).isoformat()
                updates["rate_limit_reset_at"] = reset_at
            else:
                updates["rate_limit_reset_at"] = ""
        except (ValueError, OSError):
            pass
    set_cache_status(path, **{k: v for k, v in updates.items() if v is not None})


def ensure_admin_user(path: str) -> None:
    username = os.environ.get("ADMIN_USER")
    password = os.environ.get("ADMIN_PASSWORD")
    if not username or not password:
        return

    db = get_db(path)
    existing = db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
    if not existing:
        db.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username, generate_password_hash(password)),
        )
        db.commit()
    db.close()


def refresh_orders_cache(path: str, start_date: date, end_date: date) -> None:
    client = WineDirectClient.from_env()
    def _progress(page: int, fetched: int, total: int) -> None:
        set_cache_status(
            path,
            refresh_page=str(page),
            refresh_fetched=str(fetched),
            refresh_total=str(total),
        )

    set_cache_status(path, refresh_page="0", refresh_fetched="0", refresh_total="0")
    orders = client.fetch_orders(start_date, end_date, progress_cb=_progress)
    _update_rate_limit_status(path, client.rate_limit)

    db = sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute(
        "DELETE FROM order_items WHERE order_id IN (SELECT order_id FROM orders WHERE date(completed_date) BETWEEN ? AND ?)",
        (start_date.isoformat(), end_date.isoformat()),
    )
    db.execute(
        "DELETE FROM orders WHERE date(completed_date) BETWEEN ? AND ?",
        (start_date.isoformat(), end_date.isoformat()),
    )

    for order in orders:
        order_row = (
            order.get("order_id"),
            order.get("order_number"),
            order.get("completed_date"),
            order.get("submitted_date"),
            order.get("date_modified"),
            order.get("shipped_date"),
            order.get("order_type"),
            order.get("order_status"),
            order.get("ship_state"),
            order.get("customer_id"),
            order.get("bill_first_name"),
            order.get("bill_last_name"),
            order.get("ship_first_name"),
            order.get("ship_last_name"),
            order.get("bill_address"),
            order.get("bill_address2"),
            order.get("bill_city"),
            order.get("bill_state"),
            order.get("bill_zip"),
            order.get("bill_country"),
            order.get("bill_email"),
            order.get("bill_phone"),
            order.get("ship_address"),
            order.get("ship_address2"),
            order.get("ship_city"),
            order.get("ship_state_code"),
            order.get("ship_zip"),
            order.get("ship_country"),
            order.get("ship_email"),
            order.get("ship_phone"),
            order.get("gift_message"),
            order.get("order_notes"),
            order.get("payment_status"),
            order.get("shipping_status"),
            order.get("shipping_type"),
            order.get("tracking_number"),
            order.get("website_id"),
            1 if order.get("is_external_order") else 0,
            1 if order.get("is_pending_pickup") else 0,
            1 if order.get("is_arms_order") else 0,
            1 if order.get("pickup") else 0,
            order.get("order_number_long"),
            order.get("pickup_date"),
            order.get("pickup_location_code"),
            order.get("payment_terms"),
            order.get("price_level"),
            order.get("sales_associate"),
            order.get("sales_attribute"),
            order.get("transaction_type"),
            order.get("source_code"),
            order.get("wholesale_number"),
            order.get("requested_delivery_date"),
            order.get("requested_ship_date"),
            order.get("sent_to_fulfillment_date"),
            order.get("future_ship_date"),
            order.get("marketplace"),
            order.get("order_total"),
            order.get("taxes"),
            order.get("shipping_paid"),
            order.get("shipping"),
            order.get("sub_total"),
            order.get("tip"),
            order.get("total"),
            order.get("total_after_tip"),
            order.get("net_sales"),
            order.get("units"),
            json.dumps(order.get("raw_json", {}), default=str),
        )
        db.execute(
            """
            INSERT OR REPLACE INTO orders (
                order_id, order_number, completed_date, submitted_date, date_modified, shipped_date,
                order_type, order_status, ship_state, customer_id, bill_first_name, bill_last_name, ship_first_name,
                ship_last_name, bill_address, bill_address2, bill_city, bill_state, bill_zip, bill_country,
                bill_email, bill_phone, ship_address, ship_address2, ship_city, ship_state_code, ship_zip,
                ship_country, ship_email, ship_phone, gift_message, order_notes, payment_status, shipping_status,
                shipping_type, tracking_number, website_id, is_external_order, is_pending_pickup, is_arms_order,
                pickup, order_number_long, pickup_date, pickup_location_code, payment_terms, price_level,
                sales_associate, sales_attribute, transaction_type, source_code, wholesale_number,
                requested_delivery_date, requested_ship_date, sent_to_fulfillment_date, future_ship_date,
                marketplace, order_total, taxes, shipping_paid, shipping, sub_total, tip, total, total_after_tip,
                net_sales, units, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            order_row,
        )
        for item in order.get("items", []):
            db.execute(
                """
                INSERT INTO order_items (
                    order_id, sku, product_name, quantity, net_sales, product_id, product_skuid, price,
                    original_price, department, department_code, inventory_pool, is_non_taxable, is_subsku,
                    sales_tax, shipping_sku, shipping_service, sub_department, sub_department_code, subtitle,
                    title, item_type, unit_description, weight, cost_of_good, custom_tax1, custom_tax2,
                    custom_tax3, parent_sku, parent_skuid, shipped_date, tracking_number, raw_json
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    order.get("order_id"),
                    item.get("sku"),
                    item.get("name"),
                    item.get("quantity"),
                    item.get("net_sales"),
                    item.get("product_id"),
                    item.get("product_skuid"),
                    item.get("price"),
                    item.get("original_price"),
                    item.get("department"),
                    item.get("department_code"),
                    item.get("inventory_pool"),
                    1 if item.get("is_non_taxable") else 0,
                    1 if item.get("is_subsku") else 0,
                    item.get("sales_tax"),
                    item.get("shipping_sku"),
                    item.get("shipping_service"),
                    item.get("sub_department"),
                    item.get("sub_department_code"),
                    item.get("subtitle"),
                    item.get("title"),
                    item.get("item_type"),
                    item.get("unit_description"),
                    item.get("weight"),
                    item.get("cost_of_good"),
                    item.get("custom_tax1"),
                    item.get("custom_tax2"),
                    item.get("custom_tax3"),
                    item.get("parent_sku"),
                    item.get("parent_skuid"),
                    item.get("shipped_date"),
                    item.get("tracking_number"),
                    json.dumps(item.get("raw_json", {}), default=str),
                ),
            )

    db.commit()
    db.close()


def clear_orders_cache(path: str) -> None:
    db = sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("DELETE FROM order_items")
    db.execute("DELETE FROM orders")
    db.commit()
    db.close()


def clear_products_cache(path: str) -> None:
    db = sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("DELETE FROM products")
    db.commit()
    db.close()


def refresh_products_cache(path: str) -> None:
    client = WineDirectClient.from_env()
    products = client.fetch_products()
    _update_rate_limit_status(path, client.rate_limit)

    db = get_db(path)
    for product in products:
        db.execute(
            """
            INSERT OR REPLACE INTO products (product_id, sku, name, last_updated, raw_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                product.get("product_id"),
                product.get("sku"),
                product.get("name"),
                product.get("last_updated"),
                json.dumps(product, default=str),
            ),
        )
    db.commit()
    db.close()


def refresh_inventory_cache(path: str) -> None:
    client = WineDirectClient.from_env()
    inventory = client.fetch_inventory()
    _update_rate_limit_status(path, client.rate_limit)

    db = get_db(path)
    db.execute("DELETE FROM inventory")
    for row in inventory:
        db.execute(
            """
            INSERT INTO inventory (sku, inventory_pool, inventory_pool_id, website_id, current_inventory, raw_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                row.get("sku"),
                row.get("inventory_pool"),
                row.get("inventory_pool_id"),
                row.get("website_id"),
                row.get("current_inventory"),
                json.dumps(row.get("raw_json", {}), default=str),
            ),
        )
    db.commit()
    db.close()


def rate_limit_check(path: str) -> None:
    client = WineDirectClient.from_env()
    client.rate_limit_check()
    _update_rate_limit_status(path, client.rate_limit)

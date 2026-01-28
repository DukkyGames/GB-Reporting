from __future__ import annotations

from datetime import date
from io import BytesIO
import base64

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from cache import get_db


def _money0(value: float) -> str:
    return f"${value:,.0f}"


def _money2(value: float) -> str:
    return f"${value:,.2f}"


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _fig_to_base64(fig) -> str:
    buffer = BytesIO()
    fig.savefig(buffer, format="png", dpi=160, bbox_inches="tight")
    plt.close(fig)
    buffer.seek(0)
    return base64.b64encode(buffer.read()).decode("utf-8")


def _load_data(db_path: str, start_date: date, end_date: date) -> tuple[pd.DataFrame, pd.DataFrame]:
    db = get_db(db_path)
    orders = pd.read_sql_query(
        "SELECT * FROM orders",
        db,
    )
    items = pd.read_sql_query(
        "SELECT * FROM order_items",
        db,
    )
    db.close()
    orders["completed_date"] = pd.to_datetime(orders["completed_date"], errors="coerce")
    orders["completed_local"] = orders["completed_date"].dt.date
    mask = (orders["completed_local"] >= start_date) & (orders["completed_local"] <= end_date)
    orders = orders[mask]
    items = items[items["order_id"].isin(orders["order_id"])]
    return orders, items


def _build_report_core(db_path: str, start_date: date, end_date: date) -> dict:
    orders, items = _load_data(db_path, start_date, end_date)
    if orders.empty:
        return {
            "kpis": [],
            "monthly": [],
            "table": [],
            "empty": True,
        }

    orders["completed_date"] = pd.to_datetime(orders["completed_date"], errors="coerce")
    orders["month"] = orders["completed_date"].dt.to_period("M").dt.to_timestamp()

    for col in ("units", "sub_total", "order_total", "taxes"):
        orders[col] = pd.to_numeric(orders[col], errors="coerce").fillna(0)

    total_orders = len(orders)
    total_units = orders["units"].sum()
    net_sales = orders["sub_total"].sum()
    order_total = orders["order_total"].sum()
    taxes = orders["taxes"].sum()
    aov = net_sales / total_orders if total_orders else 0
    avg_bottle_price = net_sales / total_units if total_units else 0

    unique_customers = orders["customer_id"].nunique()
    repeat_customers = orders.groupby("customer_id")["order_id"].nunique().gt(1).sum() if unique_customers else 0
    repeat_rate = repeat_customers / unique_customers if unique_customers else 0
    avg_bottles_per_customer = total_units / unique_customers if unique_customers else 0

    pickup_count = (orders["pickup"] == 1).sum()
    shipping_count = (orders["pickup"] == 0).sum()

    monthly = orders.groupby("month").agg(
        net_sales=("sub_total", "sum"),
        orders=("order_id", "count"),
        units=("units", "sum"),
    ).reset_index()

    peak_row = monthly.loc[monthly["net_sales"].idxmax()] if not monthly.empty else None
    low_row = monthly.loc[monthly["net_sales"].idxmin()] if not monthly.empty else None

    channel = orders.groupby("order_type").agg(net_sales=("sub_total", "sum")).reset_index()
    channel = channel[channel["net_sales"] > 0].sort_values("net_sales", ascending=False)

    top_rev = items.groupby(["sku", "product_name"]).agg(net_sales=("net_sales", "sum")).reset_index()
    top_rev = top_rev.sort_values("net_sales", ascending=False).head(10)

    top_units = items.groupby(["sku", "product_name"]).agg(units=("quantity", "sum")).reset_index()
    top_units = top_units.sort_values("units", ascending=False).head(10)

    states = orders[orders["pickup"] == 0].groupby("ship_state").agg(net_sales=("sub_total", "sum")).reset_index()
    states = states.sort_values("net_sales", ascending=False).head(10)

    kpis = [
        ("Net Sales", _money0(net_sales)),
        ("Total Collected", _money0(order_total)),
        ("Orders", f"{total_orders:,}"),
        ("Bottles Sold", f"{int(total_units):,}"),
        ("Avg Order Value", _money0(aov)),
        ("Avg Bottle Price", _money2(avg_bottle_price)),
        ("Unique Customers", f"{unique_customers:,}"),
        ("Repeat Rate", _pct(repeat_rate)),
        ("Avg Bottles / Customer", f"{avg_bottles_per_customer:,.1f}"),
        ("Shipped Orders", f"{shipping_count:,}"),
        ("Pickup Orders", f"{pickup_count:,}"),
        ("Taxes Collected", _money0(taxes)),
    ]

    if peak_row is not None:
        kpis.append(("Peak Month", f"{peak_row['month'].strftime('%b %Y')} ({_money0(peak_row['net_sales'])})"))
    if low_row is not None:
        kpis.append(("Lowest Month", f"{low_row['month'].strftime('%b %Y')} ({_money0(low_row['net_sales'])})"))

    table = [
        {
            "month": row["month"].strftime("%b %Y"),
            "net_sales": _money0(row["net_sales"]),
            "orders": f"{int(row['orders']):,}",
            "units": f"{int(row['units']):,}",
        }
        for _, row in monthly.iterrows()
    ]

    return {
        "kpis": kpis,
        "monthly": monthly,
        "table": table,
        "channel": channel,
        "top_rev": top_rev,
        "top_units": top_units,
        "states": states,
        "repeat_customers": repeat_customers,
        "unique_customers": unique_customers,
        "empty": False,
    }


def build_report(db_path: str, start_date: date, end_date: date) -> dict:
    core = _build_report_core(db_path, start_date, end_date)
    if core["empty"]:
        return {
            "kpis": [],
            "charts": {},
            "monthly": [],
            "table": [],
            "empty": True,
        }

    monthly = core["monthly"]
    channel = core["channel"]
    top_rev = core["top_rev"]
    top_units = core["top_units"]
    states = core["states"]
    repeat_customers = core["repeat_customers"]
    unique_customers = core["unique_customers"]

    def _native_list(values, cast=float):
        return [cast(v) for v in values]

    chart_data = {
        "monthly": {
            "labels": [d.strftime("%b %Y") for d in monthly["month"]],
            "net_sales": _native_list(monthly["net_sales"], float),
            "orders": _native_list(monthly["orders"], int),
            "units": _native_list(monthly["units"], float),
        },
        "sales_by_channel": {
            "labels": channel["order_type"].fillna("Unknown").tolist(),
            "values": _native_list(channel["net_sales"], float),
        },
        "top_products_revenue": {
            "labels": ["  " + sku for sku in top_rev["sku"].fillna("Unknown").tolist()],
            "values": _native_list(top_rev["net_sales"], float),
        },
        "top_products_units": {
            "labels": top_units["sku"].fillna("Unknown").tolist(),
            "values": _native_list(top_units["units"], float),
        },
        "top_states": {
            "labels": states["ship_state"].fillna("Unknown").tolist(),
            "values": _native_list(states["net_sales"], float),
        },
        "customer_mix": {
            "labels": ["Repeat", "New"],
            "values": [int(repeat_customers), int(max(unique_customers - repeat_customers, 0))],
        },
    }

    return {
        "kpis": core["kpis"],
        "charts": chart_data,
        "monthly": monthly,
        "table": core["table"],
        "empty": False,
    }


def build_report_timeseries(db_path: str, start_date: date, end_date: date, granularity: str = "month") -> dict:
    orders, _ = _load_data(db_path, start_date, end_date)
    if orders.empty:
        return {"labels": [], "net_sales": [], "orders": [], "units": []}

    orders["completed_date"] = pd.to_datetime(orders["completed_date"], errors="coerce")
    orders["completed_local"] = orders["completed_date"].dt.date
    for col in ("units", "sub_total"):
        orders[col] = pd.to_numeric(orders[col], errors="coerce").fillna(0)

    if granularity == "day":
        grouped = orders.groupby("completed_local").agg(
            net_sales=("sub_total", "sum"),
            orders=("order_id", "count"),
            units=("units", "sum"),
        ).reset_index()
        grouped = grouped.sort_values("completed_local")
        labels = [d.strftime("%b %d, %Y") for d in pd.to_datetime(grouped["completed_local"]).dt.date]
    else:
        orders["month"] = orders["completed_date"].dt.to_period("M").dt.to_timestamp()
        grouped = orders.groupby("month").agg(
            net_sales=("sub_total", "sum"),
            orders=("order_id", "count"),
            units=("units", "sum"),
        ).reset_index()
        grouped = grouped.sort_values("month")
        labels = [d.strftime("%b %Y") for d in grouped["month"]]

    return {
        "labels": labels,
        "net_sales": grouped["net_sales"].astype(float).tolist(),
        "orders": grouped["orders"].astype(int).tolist(),
        "units": grouped["units"].astype(float).tolist(),
    }


def build_report_pdf(db_path: str, start_date: date, end_date: date) -> dict:
    core = _build_report_core(db_path, start_date, end_date)
    if core["empty"]:
        return {
            "kpis": [],
            "charts": {},
            "table": [],
            "empty": True,
        }

    chart_images = {
        "monthly_net_sales": _chart_monthly_net_sales(core["monthly"]),
        "orders_units": _chart_orders_units(core["monthly"]),
        "sales_by_channel": _chart_sales_by_channel(core["channel"]),
        "top_products_revenue": _chart_top_products(core["top_rev"], "net_sales", "Top Products by Revenue"),
        "top_products_units": _chart_top_products(core["top_units"], "units", "Top Products by Units"),
        "top_states": _chart_top_states(core["states"]),
        "customer_mix": _chart_customer_mix(core["unique_customers"], core["repeat_customers"]),
    }

    return {
        "kpis": core["kpis"],
        "charts": chart_images,
        "table": core["table"],
        "empty": False,
    }


def build_products_report(db_path: str, start_date: date, end_date: date, unit: str = "case") -> dict:
    db = get_db(db_path)
    orders = pd.read_sql_query(
        "SELECT order_id, order_type, sub_total, completed_date FROM orders",
        db,
    )
    items = pd.read_sql_query(
        """
        SELECT order_id, sku, product_name, title, quantity, net_sales, price
        FROM order_items
        """,
        db,
    )
    inventory = pd.read_sql_query(
        "SELECT sku, current_inventory, inventory_pool FROM inventory",
        db,
    )
    db.close()

    if orders.empty or items.empty:
        return {"empty": True, "skus": [], "top_skus": [], "inventory": []}

    orders["completed_date"] = pd.to_datetime(orders["completed_date"], errors="coerce")
    orders["completed_local"] = orders["completed_date"].dt.date
    orders = orders[(orders["completed_local"] >= start_date) & (orders["completed_local"] <= end_date)]
    if "payment_status" not in orders.columns:
        orders["payment_status"] = ""
    orders = orders.rename(columns={"sub_total": "order_net_sales"})
    items = items[items["order_id"].isin(orders["order_id"])]
    merged = items.merge(orders, on="order_id", how="left")
    merged["sku"] = merged["sku"].fillna("")
    merged["product_name"] = merged["product_name"].fillna("")
    merged["title"] = merged["title"].fillna("")
    merged["product_name"] = merged.apply(
        lambda row: row["product_name"] if row["product_name"] else row["title"], axis=1
    )
    merged["quantity"] = pd.to_numeric(merged["quantity"], errors="coerce").fillna(0)
    merged["cases_sold"] = merged["quantity"] / 12
    merged["net_sales"] = pd.to_numeric(merged["net_sales"], errors="coerce").fillna(0)
    merged["price"] = pd.to_numeric(merged["price"], errors="coerce").fillna(0)
    merged["order_net_sales"] = pd.to_numeric(merged.get("order_net_sales", 0), errors="coerce").fillna(0)

    # Allocate order-level net sales across items by price share, fallback to quantity share.
    merged["line_value"] = merged["price"] * merged["quantity"]
    value_by_order = merged.groupby("order_id")["line_value"].transform("sum")
    qty_by_order = merged.groupby("order_id")["quantity"].transform("sum")
    merged["calc_sales"] = 0.0
    has_value = value_by_order > 0
    merged.loc[has_value, "calc_sales"] = (
        merged.loc[has_value, "order_net_sales"] * (merged.loc[has_value, "line_value"] / value_by_order[has_value])
    )
    has_qty = (~has_value) & (qty_by_order > 0)
    merged.loc[has_qty, "calc_sales"] = (
        merged.loc[has_qty, "order_net_sales"] * (merged.loc[has_qty, "quantity"] / qty_by_order[has_qty])
    )

    grouped = (
        merged.groupby(["sku", "product_name", "order_type"], dropna=False)
        .agg(cases_sold=("cases_sold", "sum"), net_sales=("calc_sales", "sum"))
        .reset_index()
    )
    grouped["avg_sale"] = grouped.apply(
        lambda row: row["net_sales"] / (row["cases_sold"] * 12) if row["cases_sold"] else 0, axis=1
    )
    qty_factor = 1 if unit == "case" else 12
    grouped["display_qty"] = grouped["cases_sold"] * qty_factor

    sku_totals = (
        grouped.groupby(["sku", "product_name"])
        .agg(cases_sold=("cases_sold", "sum"), net_sales=("net_sales", "sum"))
        .reset_index()
    )
    sku_totals["avg_sale"] = sku_totals.apply(
        lambda row: row["net_sales"] / (row["cases_sold"] * 12) if row["cases_sold"] else 0, axis=1
    )
    sku_totals["display_qty"] = sku_totals["cases_sold"] * qty_factor

    skus = []
    for _, row in sku_totals.sort_values("cases_sold", ascending=False).iterrows():
        sku = row["sku"] or "Unknown SKU"
        name = row["product_name"] or sku
        rows = grouped[(grouped["sku"] == row["sku"]) & (grouped["product_name"] == row["product_name"])]
        rows = rows.sort_values("cases_sold", ascending=False)
        max_avg = rows["avg_sale"].max() if not rows.empty else 0
        tol = 1e-6
        detail_rows = [
            {
                "order_type": r["order_type"] or "Unknown",
                "sku": r["sku"],
                "name": r["product_name"] or r["sku"],
                "cases_sold": float(r["display_qty"]),
                "net_sales": float(r["net_sales"]),
                "avg_sale": float(r["avg_sale"]),
                "is_top_avg": abs(float(r["avg_sale"]) - float(max_avg)) <= tol if max_avg else False,
            }
            for _, r in rows.iterrows()
        ]
        skus.append(
            {
                "sku": sku,
                "name": name,
                "total_cases": float(row["display_qty"]),
                "total_sales": float(row["net_sales"]),
                "avg_sale": float(row["avg_sale"]),
                "rows": detail_rows,
            }
        )

    top_skus = sku_totals.sort_values("cases_sold", ascending=False).head(15).to_dict("records")
    for row in top_skus:
        row["display_qty"] = row["cases_sold"] * qty_factor
    inventory_summary = []
    if not inventory.empty:
        inv = inventory.copy()
        inv["current_inventory"] = pd.to_numeric(inv["current_inventory"], errors="coerce").fillna(0)
        inv = inv[~inv["inventory_pool"].fillna("").str.contains("library", case=False)]
        inventory_summary = (
            inv.groupby("sku")
            .agg(total_inventory=("current_inventory", "sum"))
            .reset_index()
            .assign(total_inventory=lambda df: df["total_inventory"] / (12 if unit == "case" else 1))
            .sort_values("total_inventory", ascending=False)
            .head(30)
            .to_dict("records")
        )

    label_summary = []
    if not inventory.empty:
        inv = inventory.copy()
        inv["current_inventory"] = pd.to_numeric(inv["current_inventory"], errors="coerce").fillna(0)
        inv = inv[~inv["inventory_pool"].fillna("").str.contains("library", case=False)]
        inv["base_sku"] = inv["sku"].astype(str).str.replace(r"^\d{2}\.", "", regex=True)
        label_summary = (
            inv.groupby("base_sku")
            .agg(total_inventory=("current_inventory", "sum"))
            .reset_index()
            .assign(total_inventory=lambda df: df["total_inventory"] / (12 if unit == "case" else 1))
            .sort_values("total_inventory", ascending=False)
            .head(30)
            .to_dict("records")
        )

    return {
        "empty": False,
        "unit": unit,
        "unit_label": "Cases" if unit == "case" else "Bottles",
        "skus": skus,
        "top_skus": top_skus,
        "inventory": inventory_summary,
        "inventory_labels": label_summary,
    }


def _chart_monthly_net_sales(monthly: pd.DataFrame) -> str:
    fig, ax = plt.subplots(figsize=(6, 3))
    ax.plot(monthly["month"], monthly["net_sales"], marker="o", color="#0f8da0")
    ax.fill_between(monthly["month"], monthly["net_sales"], color="#7dd3d6", alpha=0.3)
    ax.set_title("Monthly Net Sales")
    ax.tick_params(axis="x", labelrotation=0, labelsize=6)
    ax.spines[["top", "right"]].set_visible(False)
    return _fig_to_base64(fig)


def _chart_orders_units(monthly: pd.DataFrame) -> str:
    fig, ax = plt.subplots(figsize=(6, 3))
    ax.bar(monthly["month"], monthly["orders"], color="#7dd3d6", label="Orders")
    ax.plot(monthly["month"], monthly["units"], marker="o", color="#f7b44a", label="Bottles")
    ax.set_title("Orders & Units")
    ax.tick_params(axis="x", labelrotation=0, labelsize=6)
    ax.legend(loc="upper left", frameon=True)
    ax.spines[["top", "right"]].set_visible(False)
    return _fig_to_base64(fig)


def _chart_sales_by_channel(channel: pd.DataFrame) -> str:
    fig, ax = plt.subplots(figsize=(6, 3))
    ax.bar(channel["order_type"], channel["net_sales"], color="#0f8da0")
    ax.set_title("Sales by Channel")
    ax.tick_params(axis="x", labelrotation=25)
    ax.spines[["top", "right"]].set_visible(False)
    return _fig_to_base64(fig)


def _chart_top_products(df: pd.DataFrame, value_col: str, title: str) -> str:
    fig, ax = plt.subplots(figsize=(6, 7))
    labels = df["sku"].fillna("")
    ax.barh(labels, df[value_col], color="#5c8ef2")
    ax.set_title(title)
    ax.invert_yaxis()
    ax.spines[["top", "right"]].set_visible(False)
    return _fig_to_base64(fig)


def _chart_top_states(df: pd.DataFrame) -> str:
    fig, ax = plt.subplots(figsize=(6, 3))
    ax.bar(df["ship_state"], df["net_sales"], color="#0b6c7c")
    ax.set_title("Top States (Shipped Orders)")
    ax.spines[["top", "right"]].set_visible(False)
    return _fig_to_base64(fig)


def _chart_customer_mix(unique_customers: int, repeat_customers: int) -> str:
    new_customers = max(unique_customers - repeat_customers, 0)
    fig, ax = plt.subplots(figsize=(4, 3.5))
    ax.pie(
        [repeat_customers, new_customers],
        labels=["Repeat", "New"],
        colors=["#0f8da0", "#dbe5e8"],
        autopct="%1.0f%%",
        startangle=90,
    )
    ax.set_title("Customer Mix")
    return _fig_to_base64(fig)

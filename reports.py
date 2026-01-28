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
        "SELECT * FROM orders WHERE date(completed_date) BETWEEN ? AND ?",
        db,
        params=(start_date.isoformat(), end_date.isoformat()),
    )
    items = pd.read_sql_query(
        "SELECT * FROM order_items WHERE order_id IN (SELECT order_id FROM orders WHERE date(completed_date) BETWEEN ? AND ?) ",
        db,
        params=(start_date.isoformat(), end_date.isoformat()),
    )
    db.close()
    return orders, items


def build_report(db_path: str, start_date: date, end_date: date) -> dict:
    orders, items = _load_data(db_path, start_date, end_date)
    if orders.empty:
        return {
            "kpis": [],
            "charts": {},
            "monthly": [],
            "table": [],
            "empty": True,
        }

    orders["completed_date"] = pd.to_datetime(orders["completed_date"], errors="coerce")
    orders["month"] = orders["completed_date"].dt.to_period("M").dt.to_timestamp()

    total_orders = len(orders)
    total_units = orders["units"].sum()
    net_sales = orders["net_sales"].sum()
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
        net_sales=("net_sales", "sum"),
        orders=("order_id", "count"),
        units=("units", "sum"),
    ).reset_index()

    peak_row = monthly.loc[monthly["net_sales"].idxmax()] if not monthly.empty else None
    low_row = monthly.loc[monthly["net_sales"].idxmin()] if not monthly.empty else None

    channel = orders.groupby("order_type").agg(net_sales=("net_sales", "sum")).reset_index()
    channel = channel[channel["net_sales"] > 0].sort_values("net_sales", ascending=False)

    top_rev = items.groupby(["sku", "product_name"]).agg(net_sales=("net_sales", "sum")).reset_index()
    top_rev = top_rev.sort_values("net_sales", ascending=False).head(10)

    top_units = items.groupby(["sku", "product_name"]).agg(units=("quantity", "sum")).reset_index()
    top_units = top_units.sort_values("units", ascending=False).head(10)

    states = orders[orders["pickup"] == 0].groupby("ship_state").agg(net_sales=("net_sales", "sum")).reset_index()
    states = states.sort_values("net_sales", ascending=False).head(10)

    kpis = [
        ("Net Sales", _money0(net_sales)),
        ("Total Collected", _money0(order_total)),
        ("Orders", f"{total_orders:,}"),
        ("Units Sold", f"{int(total_units):,}"),
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

    charts = {
        "monthly_net_sales": _chart_monthly_net_sales(monthly),
        "orders_units": _chart_orders_units(monthly),
        "sales_by_channel": _chart_sales_by_channel(channel),
        "top_products_revenue": _chart_top_products(top_rev, "net_sales", "Top Products by Revenue"),
        "top_products_units": _chart_top_products(top_units, "units", "Top Products by Units"),
        "top_states": _chart_top_states(states),
        "customer_mix": _chart_customer_mix(unique_customers, repeat_customers),
    }

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
        "charts": charts,
        "monthly": monthly,
        "table": table,
        "empty": False,
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
    ax.plot(monthly["month"], monthly["units"], marker="o", color="#f7b44a", label="Units")
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
    fig, ax = plt.subplots(figsize=(6, 3.2))
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

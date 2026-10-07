"""
Dynamic Pricing module.

Demand + availability + sales trends -> intelligent pricing
suggestions.

Implementation: for each menu item a demand index is computed from its
share of recent order volume, a trend slope is fitted with
LinearRegression over the daily quantity series, and stock availability
is read from the inventory table.  These three signals are combined into
a bounded price multiplier (-15% .. +20%).
"""

from datetime import datetime, timedelta

import numpy as np
from sklearn.linear_model import LinearRegression

MAX_INCREASE = 0.20
MAX_DISCOUNT = 0.15
RECENT_WINDOW_DAYS = 30


def _trend_slope(quantities_by_day: dict) -> float:
    """Normalised slope of daily demand: >0 rising, <0 falling."""
    if len(quantities_by_day) < 3:
        return 0.0

    days = sorted(quantities_by_day)
    y = np.array([quantities_by_day[d] for d in days], dtype=float)
    X = np.arange(len(y)).reshape(-1, 1)

    model = LinearRegression().fit(X, y)

    mean = y.mean() or 1.0
    return float(model.coef_[0]) / mean


def suggest_prices(menu_items, orders, inventory=None) -> dict:
    """Return a price suggestion for every available menu item."""
    available = [m for m in menu_items if m.available]

    if not available:
        return {"suggestions": [], "message": "No available menu items."}

    cutoff = datetime.utcnow() - timedelta(days=RECENT_WINDOW_DAYS)

    recent = [
        o for o in orders
        if (o.created_at or datetime.utcnow()) >= cutoff
    ]

    total_quantity = sum(o.quantity or 0 for o in recent) or 1

    # quantity per item, and per item per day
    per_item = {}
    per_item_day = {}

    for order in recent:
        name = order.menu_item
        quantity = order.quantity or 0

        per_item[name] = per_item.get(name, 0) + quantity

        day = (order.created_at or datetime.utcnow()).date()
        per_item_day.setdefault(name, {})
        per_item_day[name][day] = (
            per_item_day[name].get(day, 0) + quantity
        )

    # low stock lookup by (loose) item name
    low_stock = set()
    if inventory:
        for stock in inventory:
            if (stock.quantity or 0) <= (stock.minimum_stock or 0):
                low_stock.add((stock.item_name or "").lower())

    average_share = 1 / len(available)
    suggestions = []

    for item in available:
        base_price = float(item.price or 0)
        sold = per_item.get(item.name, 0)
        share = sold / total_quantity

        # 1. demand signal
        demand_index = share / average_share if average_share else 0.0

        if demand_index >= 1.5:
            demand_adjust, demand_note = 0.10, "high demand"
        elif demand_index <= 0.5:
            demand_adjust, demand_note = -0.08, "low demand"
        else:
            demand_adjust, demand_note = 0.0, "average demand"

        # 2. trend signal
        slope = _trend_slope(per_item_day.get(item.name, {}))

        if slope > 0.05:
            trend_adjust, trend_note = 0.06, "rising trend"
        elif slope < -0.05:
            trend_adjust, trend_note = -0.05, "falling trend"
        else:
            trend_adjust, trend_note = 0.0, "flat trend"

        # 3. availability signal (scarce ingredient -> protect margin)
        if item.name.lower() in low_stock:
            stock_adjust, stock_note = 0.05, "ingredient stock low"
        else:
            stock_adjust, stock_note = 0.0, "stock normal"

        multiplier = 1 + demand_adjust + trend_adjust + stock_adjust
        multiplier = min(
            max(multiplier, 1 - MAX_DISCOUNT),
            1 + MAX_INCREASE,
        )

        suggested = round(base_price * multiplier, 2)
        change_pct = round((multiplier - 1) * 100, 2)

        if change_pct > 0:
            action = "Increase price"
        elif change_pct < 0:
            action = "Offer discount"
        else:
            action = "Keep current price"

        suggestions.append({
            "menu_item": item.name,
            "category": item.category,
            "current_price": base_price,
            "suggested_price": suggested,
            "change_percentage": change_pct,
            "action": action,
            "units_sold_recently": int(sold),
            "demand_index": round(demand_index, 2),
            "reason": f"{demand_note}, {trend_note}, {stock_note}",
        })

    suggestions.sort(
        key=lambda s: s["change_percentage"], reverse=True
    )

    return {
        "window_days": RECENT_WINDOW_DAYS,
        "orders_analyzed": len(recent),
        "max_increase_percentage": MAX_INCREASE * 100,
        "max_discount_percentage": MAX_DISCOUNT * 100,
        "suggestions": suggestions,
    }

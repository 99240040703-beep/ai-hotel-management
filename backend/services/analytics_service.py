"""
Real business analytics, aggregated in SQL.

Every number this module returns is measured from MySQL. Nothing is
estimated, defaulted or filled in, so an empty table produces an empty
result rather than a plausible-looking zero.

--------------------------------------------------------------------------
WHERE REVENUE COMES FROM
--------------------------------------------------------------------------
Two tables hold money and they are not interchangeable:

  * `order_headers` is one row per checkout. Its `total_amount` is
    written by the server from menu.price plus tax and charges, so it is
    the authoritative figure for any order placed through checkout.

  * `orders` is one row per dish. Historical rows predate order headers
    and carry `order_id IS NULL`; they were never re-priced by a
    checkout, so their `total_price` is the only figure available.

Both are summed, and they cannot overlap: a line row that belongs to a
header is excluded from the legacy sum because its money is already in
the header's total. `revenue_breakdown` reports the two separately so a
reader can always see which part of a total came from where.

--------------------------------------------------------------------------
LIFECYCLE AND PAYMENT ARE SEPARATE
--------------------------------------------------------------------------
`status` and `payment_status` are independent columns and this module
never derives one from the other. A served order that has not been paid
for is a normal state in this restaurant - guests pay after they leave -
so "served and unpaid" is counted, never corrected.
"""

from datetime import date, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from models import (
    Customer,
    Inventory,
    Menu,
    Order,
    OrderHeader,
    Reservation,
    User,
    Waste,
)


# =========================================================
# RANGES
# =========================================================

# The lifecycle this project stores in OrderHeader.status.
LIFECYCLE_STATUSES = [
    "Placed",
    "Confirmed",
    "Preparing",
    "Ready",
    "Served",
]

# Statuses that mean the order is still in progress.
ACTIVE_LIFECYCLE_STATUSES = ["Placed", "Confirmed", "Preparing", "Ready"]

# Menu item categories are free text, so the wastage breakdown groups on
# whatever the inventory and waste tables actually contain rather than a
# fixed list.

MAX_RANGE_DAYS = 366


def resolve_range(range_key: str | None, start: date | None = None,
                  end: date | None = None) -> tuple[date, date, str]:
    """
    Turn a range keyword into concrete inclusive dates.

    Accepts today, yesterday, last_7_days, last_30_days, this_week,
    this_month, all_time, or an explicit start/end pair.

    Returns (start_date, end_date, label). The label is echoed back so a
    response can state exactly which window it describes instead of
    leaving the caller to guess.
    """
    today = date.today()

    key = (range_key or "last_7_days").strip().lower()

    if key == "today":
        return today, today, "today"

    if key == "yesterday":
        day = today - timedelta(days=1)
        return day, day, "yesterday"

    if key == "last_7_days":
        return today - timedelta(days=6), today, "last_7_days"

    if key == "last_30_days":
        return today - timedelta(days=29), today, "last_30_days"

    if key == "this_week":
        # Monday-based, matching how a restaurant week is read.
        return today - timedelta(days=today.weekday()), today, "this_week"

    if key == "this_month":
        return today.replace(day=1), today, "this_month"

    if key == "all_time":
        return date(1970, 1, 1), today, "all_time"

    # An explicit window wins if it is supplied and usable.
    if start and end:
        if end < start:
            start, end = end, start

        span = (end - start).days + 1

        if span > MAX_RANGE_DAYS:
            start = end - timedelta(days=MAX_RANGE_DAYS - 1)

        return start, end, "custom"

    return today - timedelta(days=6), today, "last_7_days"


def _daterange(column, start: date, end: date):
    """
    An inclusive date filter that works on a DATETIME column.

    `func.date(column)` is used rather than a bare comparison so the
    whole of the final day is included. Comparing `placed_at >= end`
    would silently drop every order placed during the end day.
    """
    return func.date(column).between(start.isoformat(), end.isoformat())


def _days_between(start: date, end: date) -> list:
    """Every calendar date in the window, so gaps render as real zeros."""
    span = (end - start).days

    return [start + timedelta(days=offset) for offset in range(span + 1)]


# =========================================================
# MONEY
# =========================================================

def revenue_for_window(db: Session, start: date, end: date) -> dict:
    """
    Revenue, order count and portions for one window.

    Split into checkout (order_headers) and legacy (unlinked order rows)
    so the caller can see the composition, and summed for the headline.
    """
    header_row = (
        db.query(
            func.count(OrderHeader.id),
            func.coalesce(func.sum(OrderHeader.total_amount), 0.0),
        )
        .filter(_daterange(OrderHeader.placed_at, start, end))
        .first()
    )

    legacy_row = (
        db.query(
            func.count(Order.id),
            func.coalesce(func.sum(Order.total_price), 0.0),
            func.coalesce(func.sum(Order.quantity), 0),
        )
        .filter(
            _daterange(Order.created_at, start, end),
            Order.order_id.is_(None),
        )
        .first()
    )

    checkout_orders = int(header_row[0] or 0)
    checkout_revenue = float(header_row[1] or 0)

    legacy_orders = int(legacy_row[0] or 0)
    legacy_revenue = float(legacy_row[1] or 0)

    total_orders = checkout_orders + legacy_orders

    return {
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "revenue": round(checkout_revenue + legacy_revenue, 2),
        "orders": total_orders,
        "portions": int(legacy_row[2] or 0),
        "average_order_value": (
            round((checkout_revenue + legacy_revenue) / total_orders, 2)
            if total_orders
            else 0.0
        ),
        "revenue_breakdown": {
            "checkout_revenue": round(checkout_revenue, 2),
            "checkout_orders": checkout_orders,
            "legacy_revenue": round(legacy_revenue, 2),
            "legacy_orders": legacy_orders,
        },
    }


def revenue_trend(db: Session, range_key: str = "last_7_days",
                  start: date | None = None,
                  end: date | None = None) -> dict:
    """
    A real daily revenue and order series for the chart board.

    One grouped query per source, then the days are laid out in Python so
    a day with no orders appears as 0 rather than vanishing from the
    chart and quietly compressing the x-axis.
    """
    start, end, label = resolve_range(range_key, start, end)

    header_rows = (
        db.query(
            func.date(OrderHeader.placed_at).label("day"),
            func.count(OrderHeader.id),
            func.coalesce(func.sum(OrderHeader.total_amount), 0.0),
        )
        .filter(_daterange(OrderHeader.placed_at, start, end))
        .group_by(func.date(OrderHeader.placed_at))
        .all()
    )

    legacy_rows = (
        db.query(
            func.date(Order.created_at).label("day"),
            func.count(Order.id),
            func.coalesce(func.sum(Order.total_price), 0.0),
            func.coalesce(func.sum(Order.quantity), 0),
        )
        .filter(
            _daterange(Order.created_at, start, end),
            Order.order_id.is_(None),
        )
        .group_by(func.date(Order.created_at))
        .all()
    )

    by_day = {}

    for day, count, amount in header_rows:
        key = str(day)
        entry = by_day.setdefault(key, {"revenue": 0.0, "orders": 0, "portions": 0})
        entry["revenue"] += float(amount or 0)
        entry["orders"] += int(count or 0)

    for day, count, amount, portions in legacy_rows:
        key = str(day)
        entry = by_day.setdefault(key, {"revenue": 0.0, "orders": 0, "portions": 0})
        entry["revenue"] += float(amount or 0)
        entry["orders"] += int(count or 0)
        entry["portions"] += int(portions or 0)

    series = []

    for day in _days_between(start, end):
        entry = by_day.get(day.isoformat(), {"revenue": 0.0, "orders": 0, "portions": 0})

        series.append(
            {
                "date": day.isoformat(),
                "revenue": round(entry["revenue"], 2),
                "orders": entry["orders"],
                "portions": entry["portions"],
            }
        )

    total = sum(point["revenue"] for point in series)
    total_orders = sum(point["orders"] for point in series)

    best = max(series, key=lambda point: point["revenue"]) if series else None

    return {
        "range": label,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "days": len(series),
        "data": series,
        "total_revenue": round(total, 2),
        "total_orders": total_orders,
        "average_order_value": (
            round(total / total_orders, 2) if total_orders else 0.0
        ),
        "best_day": (
            {"date": best["date"], "revenue": best["revenue"]}
            if best and best["revenue"] > 0
            else None
        ),
        "has_data": any(point["orders"] for point in series),
    }


# =========================================================
# SALES
# =========================================================

def sales_summary(db: Session, range_key: str = "today",
                  start: date | None = None,
                  end: date | None = None) -> dict:
    """Portions, order lines and average line value for a window."""
    start, end, label = resolve_range(range_key, start, end)

    money = revenue_for_window(db, start, end)

    linked = (
        db.query(
            func.coalesce(func.sum(Order.quantity), 0),
            func.count(Order.id),
        )
        .filter(
            _daterange(Order.created_at, start, end),
            Order.order_id.isnot(None),
        )
        .first()
    )

    line_count = int(linked[1] or 0)

    portions = money["portions"] + int(linked[0] or 0)

    return {
        "range": label,
        "start_date": money["start_date"],
        "end_date": money["end_date"],
        "revenue": money["revenue"],
        "orders": money["orders"],
        "portions_sold": portions,
        "order_lines": line_count,
        "average_order_value": money["average_order_value"],
        "average_portion_price": (
            round(money["revenue"] / portions, 2) if portions else 0.0
        ),
        "has_data": bool(money["orders"] or portions),
    }


def top_dishes(db: Session, limit: int = 5, range_key: str = "all_time",
               start: date | None = None,
               end: date | None = None) -> dict:
    """
    Best selling dishes by quantity, with their real revenue.

    Category and current menu price are joined from `menu` by name. The
    join is a LEFT JOIN in effect: a dish that has since been renamed or
    removed still reports the sales it actually had, with category None
    rather than being dropped from the leaderboard.
    """
    limit = max(1, min(int(limit or 5), 25))

    start, end, label = resolve_range(range_key, start, end)

    rows = (
        db.query(
            Order.menu_item,
            func.coalesce(func.sum(Order.quantity), 0),
            func.coalesce(func.sum(Order.total_price), 0.0),
            func.count(Order.id),
        )
        .filter(_daterange(Order.created_at, start, end))
        .group_by(Order.menu_item)
        .order_by(
            func.coalesce(func.sum(Order.quantity), 0).desc(),
            func.coalesce(func.sum(Order.total_price), 0.0).desc(),
        )
        .limit(limit)
        .all()
    )

    names = [row[0] for row in rows]

    menu_by_name = {}

    if names:
        for item in db.query(Menu).filter(Menu.name.in_(names)).all():
            menu_by_name[item.name] = item

    dishes = []

    for name, quantity, revenue, times in rows:
        item = menu_by_name.get(name)

        dishes.append(
            {
                "dish": name,
                "menu_id": item.id if item else None,
                "category": item.category if item else None,
                "quantity_sold": int(quantity or 0),
                "revenue": round(float(revenue or 0), 2),
                "times_ordered": int(times or 0),
                "current_price": float(item.price or 0) if item else None,
                "available": bool(item.available) if item else None,
            }
        )

    return {
        "range": label,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "limit": limit,
        "top_dishes": dishes,
        "has_data": bool(dishes),
    }


def revenue_by_category(db: Session, range_key: str = "all_time",
                        start: date | None = None,
                        end: date | None = None) -> dict:
    """Revenue grouped by menu category, from real order lines."""
    start, end, label = resolve_range(range_key, start, end)

    rows = (
        db.query(
            Menu.category,
            func.coalesce(func.sum(Order.quantity), 0),
            func.coalesce(func.sum(Order.total_price), 0.0),
        )
        .join(Order, Order.menu_item == Menu.name)
        .filter(_daterange(Order.created_at, start, end))
        .group_by(Menu.category)
        .order_by(func.coalesce(func.sum(Order.total_price), 0.0).desc())
        .all()
    )

    slices = []

    for category, quantity, revenue in rows:
        slices.append(
            {
                "category": category or "Uncategorised",
                "quantity_sold": int(quantity or 0),
                "revenue": round(float(revenue or 0), 2),
            }
        )

    return {
        "range": label,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "categories": slices,
        "total_revenue": round(sum(s["revenue"] for s in slices), 2),
        "has_data": bool(slices),
    }


# =========================================================
# ORDER LIFECYCLE AND PAYMENT
# =========================================================

def order_status_summary(db: Session) -> dict:
    """
    Real counts of each OrderHeader.status.

    Reported alongside payment counts as two independent facts. Nothing
    here treats a served order as paid.
    """
    status_rows = (
        db.query(OrderHeader.status, func.count(OrderHeader.id))
        .group_by(OrderHeader.status)
        .all()
    )

    counted = {str(status or "Unknown"): int(count) for status, count in status_rows}

    lifecycle = {
        status: counted.get(status, 0) for status in LIFECYCLE_STATUSES
    }

    # Anything not in the known lifecycle is still surfaced rather than
    # dropped, so an unexpected value cannot hide in a total.
    other = {
        status: count
        for status, count in counted.items()
        if status not in lifecycle
    }

    payment_rows = (
        db.query(OrderHeader.payment_status, func.count(OrderHeader.id))
        .group_by(OrderHeader.payment_status)
        .all()
    )

    payment = {
        str(status or "unknown"): int(count) for status, count in payment_rows
    }

    total = sum(lifecycle.values()) + sum(other.values())

    served_unpaid = (
        db.query(func.count(OrderHeader.id))
        .filter(
            OrderHeader.status == "Served",
            OrderHeader.payment_status != "paid",
        )
        .scalar()
    ) or 0

    return {
        "lifecycle": lifecycle,
        "other_statuses": other,
        "active_orders": sum(
            lifecycle.get(status, 0) for status in ACTIVE_LIFECYCLE_STATUSES
        ),
        "total_orders": total,
        "payment": payment,
        # A served order is frequently still unpaid in this restaurant,
        # because guests pay after they leave. That is a real count, not
        # an error to be reconciled.
        "served_unpaid_orders": int(served_unpaid),
        "has_data": total > 0,
    }


# =========================================================
# WASTAGE
# =========================================================

def wastage_summary(db: Session, range_key: str = "today",
                    start: date | None = None,
                    end: date | None = None) -> dict:
    """Wastage quantity and cost for a window, plus a daily series."""
    start, end, label = resolve_range(range_key, start, end)

    rows = (
        db.query(
            Waste.item_name,
            func.coalesce(func.sum(Waste.quantity), 0.0),
            func.coalesce(func.sum(Waste.cost), 0.0),
            func.count(Waste.id),
        )
        .filter(_daterange(Waste.recorded_at, start, end))
        .group_by(Waste.item_name)
        .order_by(func.coalesce(func.sum(Waste.cost), 0.0).desc())
        .all()
    )

    items = [
        {
            "item_name": name,
            "quantity": round(float(quantity or 0), 2),
            "cost": round(float(cost or 0), 2),
            "entries": int(entries or 0),
        }
        for name, quantity, cost, entries in rows
    ]

    day_rows = (
        db.query(
            func.date(Waste.recorded_at).label("day"),
            func.coalesce(func.sum(Waste.cost), 0.0),
            func.coalesce(func.sum(Waste.quantity), 0.0),
        )
        .filter(_daterange(Waste.recorded_at, start, end))
        .group_by(func.date(Waste.recorded_at))
        .all()
    )

    by_day = {
        str(day): {"cost": float(cost or 0), "quantity": float(quantity or 0)}
        for day, cost, quantity in day_rows
    }

    series = []

    for day in _days_between(start, end):
        entry = by_day.get(
            day.isoformat(), {"cost": 0.0, "quantity": 0.0}
        )

        series.append(
            {
                "date": day.isoformat(),
                "cost": round(entry["cost"], 2),
                "quantity": round(entry["quantity"], 2),
            }
        )

    highest = items[0] if items else None

    return {
        "range": label,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "total_cost": round(sum(item["cost"] for item in items), 2),
        "total_quantity": round(sum(item["quantity"] for item in items), 2),
        "items": items,
        "highest_wastage_item": highest,
        "trend": series,
        "has_data": bool(items),
    }


def highest_wastage(db: Session, range_key: str = "all_time",
                    start: date | None = None,
                    end: date | None = None) -> dict:
    """The single worst wastage item, by cost."""
    start, end, label = resolve_range(range_key, start, end)

    rows = (
        db.query(
            Waste.item_name,
            func.coalesce(func.sum(Waste.cost), 0.0),
            func.coalesce(func.sum(Waste.quantity), 0.0),
            func.count(Waste.id),
        )
        .filter(_daterange(Waste.recorded_at, start, end))
        .group_by(Waste.item_name)
        .order_by(func.coalesce(func.sum(Waste.cost), 0.0).desc())
        .limit(1)
        .first()
    )

    if not rows:
        return {
            "range": label,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "item": None,
            "has_data": False,
        }

    return {
        "range": label,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "item": {
            "item_name": rows[0],
            "cost": round(float(rows[1] or 0), 2),
            "quantity": round(float(rows[2] or 0), 2),
            "entries": int(rows[3] or 0),
        },
        "has_data": True,
    }


# =========================================================
# INVENTORY
# =========================================================

def inventory_summary(db: Session) -> dict:
    """
    Real stock counts using the inventory table's own minimum_stock rule.

    The split follows the schema:
      out_of_stock  quantity <= 0
      low_stock     0 < quantity <= minimum_stock
      available     quantity > minimum_stock

    An item with no minimum_stock recorded is treated as available,
    because there is no threshold in the data to say it is low.
    """
    rows = (
        db.query(
            Inventory.item_name,
            Inventory.category,
            Inventory.quantity,
            Inventory.minimum_stock,
            Inventory.unit,
            Inventory.supplier,
            Inventory.cost_per_unit,
        )
        .all()
    )

    available = []
    low = []
    out = []

    for name, category, quantity, minimum, unit, supplier, cost in rows:
        quantity = float(quantity or 0)
        minimum = float(minimum or 0)

        entry = {
            "item_name": name,
            "category": category,
            "quantity": quantity,
            "minimum_stock": minimum,
            "unit": unit,
            "supplier": supplier,
            "cost_per_unit": float(cost or 0),
            "shortfall": round(max(0.0, minimum - quantity), 2),
        }

        if quantity <= 0:
            out.append(entry)
        elif minimum > 0 and quantity <= minimum:
            low.append(entry)
        else:
            available.append(entry)

    low.sort(key=lambda entry: entry["shortfall"], reverse=True)

    return {
        "total_items": len(rows),
        "available_count": len(available),
        "low_stock_count": len(low),
        "out_of_stock_count": len(out),
        "low_stock_items": low,
        "out_of_stock_items": out,
        "total_stock_value": round(
            sum(
                float(quantity or 0) * float(cost or 0)
                for _, _, quantity, _, _, _, cost in rows
            ),
            2,
        ),
        "has_data": bool(rows),
    }


# =========================================================
# CUSTOMERS
# =========================================================

def customer_summary(db: Session) -> dict:
    """Customer records and what can actually be attributed to them."""
    total_customers = db.query(Customer).count()

    total_users = db.query(User).count()

    repeat = (
        db.query(Order.customer_name, func.count(Order.id))
        .filter(Order.customer_name.isnot(None))
        .group_by(Order.customer_name)
        .having(func.count(Order.id) > 1)
        .all()
    )

    top_spenders = (
        db.query(
            Order.customer_name,
            func.coalesce(func.sum(Order.total_price), 0.0),
            func.count(Order.id),
        )
        .filter(Order.customer_name.isnot(None))
        .group_by(Order.customer_name)
        .order_by(func.coalesce(func.sum(Order.total_price), 0.0).desc())
        .limit(5)
        .all()
    )

    linked_orders = (
        db.query(func.count(Order.id))
        .filter(Order.user_id.isnot(None))
        .scalar()
    ) or 0

    return {
        "total_customers": total_customers,
        "total_users": int(total_users),
        "distinct_order_names": len(
            db.query(Order.customer_name)
            .filter(Order.customer_name.isnot(None))
            .distinct()
            .all()
        ),
        "repeat_customers": len(repeat),
        "orders_linked_to_accounts": int(linked_orders),
        "top_spenders": [
            {
                "customer_name": name,
                "total_spent": round(float(spent or 0), 2),
                "orders": int(orders or 0),
            }
            for name, spent, orders in top_spenders
        ],
        "reservations": db.query(Reservation).count(),
        "has_data": total_customers > 0,
    }


# =========================================================
# OVERVIEW
# =========================================================

def data_quality_for_window(db: Session, start: date, end: date) -> dict:
    """
    Flags about how trustworthy a window's figures are.

    Three populations are counted, all real measurements:

    * `checkout_lines` - order lines that belong to an order header.
      These were priced by the server from menu.price, so their money is
      authoritative.

    * `legacy_lines` - unlinked order lines. These predate checkout.
      `legacy_unpriced_lines` have no `unit_price` at all, so their
      `total_price` was written by whatever created the row and never
      re-derived from the menu. `legacy_priced_lines` do carry a unit
      price captured at the time.

    * `price_mismatch_count` - lines whose stored total_price does not
      equal unit_price x quantity. This is a genuine arithmetic fault in
      the stored data, and it is reported rather than corrected: a
      rewrite would be a guess about what the guest was actually charged.

    Historical rows are never rewritten to match today's menu: an order
    keeps the price that was actually charged at the time.
    """
    checkout_lines = (
        db.query(func.count(Order.id))
        .filter(
            _daterange(Order.created_at, start, end),
            Order.order_id.isnot(None),
        )
        .scalar()
    ) or 0

    legacy_lines = (
        db.query(func.count(Order.id))
        .filter(
            _daterange(Order.created_at, start, end),
            Order.order_id.is_(None),
        )
        .scalar()
    ) or 0

    unpriced = (
        db.query(func.count(Order.id))
        .filter(
            _daterange(Order.created_at, start, end),
            Order.order_id.is_(None),
            Order.unit_price.is_(None),
        )
        .scalar()
    ) or 0

    # A stored line whose total is not its unit price times its quantity.
    # Rounding to two places on both sides avoids flagging a float
    # artefact such as 0.1 + 0.2 as a mismatch.
    mismatches = (
        db.query(func.count(Order.id))
        .filter(
            _daterange(Order.created_at, start, end),
            Order.unit_price.isnot(None),
            func.round(Order.total_price, 2) != (
                func.round(Order.unit_price * Order.quantity, 2)
            ),
        )
        .scalar()
    ) or 0

    # Phase 6A. A legacy line whose charged total is less than a tenth of
    # today's price for the same dish cannot be explained by the menu
    # having been repriced - a repricing moves a price, it does not move
    # it by a factor of ten or more. These are magnitude errors: a total
    # left in a different currency, or one written from a USD scaffold
    # price after the system moved to INR.
    #
    # They are reported, never rewritten. Deciding what the guest was
    # really charged is not something a report can do.
    implausible = (
        db.query(Order, Menu.price.label("current_price"))
        .join(Menu, Menu.name == Order.menu_item)
        .filter(
            _daterange(Order.created_at, start, end),
            Order.unit_price.is_(None),
            Order.total_price < (Menu.price * Order.quantity / 10.0),
        )
        .order_by(Order.id.asc())
        .all()
    )

    # Counted at order level, not line level, because that is the unit a
    # reader thinks in: one order header is one server-priced checkout,
    # and one unlinked `orders` row is one legacy order.
    server_priced_orders = (
        db.query(func.count(OrderHeader.id))
        .filter(_daterange(OrderHeader.placed_at, start, end))
        .scalar()
    ) or 0

    return {
        "checkout_lines": int(checkout_lines),
        "legacy_lines": int(legacy_lines),
        # Legacy rows whose price was never server-resolved.
        "legacy_priced_lines": int(legacy_lines - unpriced),
        "legacy_unpriced_lines": int(unpriced),
        # Phase 6A: the same facts under the names the Phase 6A brief asks
        # for, so no existing reader of this block breaks.
        "server_priced_order_count": int(server_priced_orders),
        "legacy_order_count": int(legacy_lines),
        "price_mismatch_count": int(mismatches),
        "implausible_total_lines": len(implausible),
        # The individual rows, so the count is actionable rather than
        # just a number to worry about. Capped so this stays a summary.
        "price_anomalies": [
            {
                "order_id": line.id,
                "customer_name": line.customer_name,
                "menu_item": line.menu_item,
                "quantity": line.quantity,
                "total_price": round(float(line.total_price or 0), 2),
                "current_menu_price": round(float(current_price or 0), 2),
                "reason": (
                    "charged total is more than 10x below the current "
                    "menu price for this dish"
                ),
            }
            for line, current_price in implausible[:10]
        ],
        "note": (
            "Legacy order rows keep the price charged at the time and "
            "are not restated to today's menu."
        ),
    }


def analytics_overview(db: Session) -> dict:
    """
    The admin landing figures, all measured today.

    `unpaid_served_orders` is reported because it is a genuine part of
    this restaurant's day: food served, payment collected later.
    """
    today = date.today()
    yesterday = today - timedelta(days=1)

    today_money = revenue_for_window(db, today, today)
    yesterday_money = revenue_for_window(db, yesterday, yesterday)

    today_sales = sales_summary(db, "today")
    today_waste = wastage_summary(db, "today")
    stock = inventory_summary(db)
    lifecycle = order_status_summary(db)

    total_orders = db.query(Order).count()

    return {
        "generated_at": datetime.utcnow().isoformat(timespec="seconds"),
        "today": {
            "date": today.isoformat(),
            "revenue": today_money["revenue"],
            "orders": today_money["orders"],
            "portions_sold": today_sales["portions_sold"],
            "average_order_value": today_money["average_order_value"],
            "wastage_cost": today_waste["total_cost"],
            "wastage_entries": len(today_waste["items"]),
            "data_quality": data_quality_for_window(db, today, today),
        },
        "yesterday": {
            "date": yesterday.isoformat(),
            "revenue": yesterday_money["revenue"],
            "orders": yesterday_money["orders"],
        },
        "revenue_change_percent": _percent_change(
            today_money["revenue"], yesterday_money["revenue"]
        ),
        "inventory": {
            "total_items": stock["total_items"],
            "low_stock": stock["low_stock_count"],
            "out_of_stock": stock["out_of_stock_count"],
            "available": stock["available_count"],
        },
        "order_lifecycle": lifecycle["lifecycle"],
        "active_orders": lifecycle["active_orders"],
        "served_orders": lifecycle["lifecycle"].get("Served", 0),
        "pending_orders": lifecycle["lifecycle"].get("Placed", 0),
        "payment": lifecycle["payment"],
        # Food status and payment status are separate facts. A served
        # order that is still unpaid is normal here and is reported as
        # such - it is never used to infer that payment happened.
        "unpaid_served_orders": lifecycle["served_unpaid_orders"],
        "all_time": {
            "order_lines": total_orders,
            "menu_items": db.query(Menu).count(),
            "available_menu_items": db.query(Menu).filter(Menu.available.is_(True)).count(),
            # The whole history's price provenance. Today's block above
            # answers "how much of today can I trust"; this one answers
            # "how much of everything can I trust", which is the question
            # that surfaces a row written on the wrong price scale years
            # ago.
            "data_quality": data_quality_for_window(
                db, date(1970, 1, 1), today
            ),
        },
        "has_data": today_money["orders"] > 0 or lifecycle["total_orders"] > 0,
    }


def _percent_change(current: float, previous: float) -> float | None:
    """
    Day-on-day change, or None when it cannot be computed.

    Returns None rather than 0 when yesterday had no revenue: a jump
    from nothing to something is not a 100% increase, and reporting it
    as one would be a fabricated figure.
    """
    if not previous:
        return None

    return round((current - previous) / previous * 100, 2)

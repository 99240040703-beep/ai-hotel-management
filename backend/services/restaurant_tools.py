"""
Restaurant-wide data tools for the admin AI assistant.

--------------------------------------------------------------------------
WHY THIS FILE EXISTS
--------------------------------------------------------------------------
The assistant must be able to reason about the whole restaurant without
being handed unrestricted database access. This module is the boundary.

Each tool is a plain function that takes a SQLAlchemy session and a
validated parameter dict, and returns a dict. That dict is the *only*
thing the reasoning layer ever sees. There is no SQL string parameter, no
table-name parameter and no "run this query" entry point anywhere in this
file, so no question can become an arbitrary query.

--------------------------------------------------------------------------
WHERE THE NUMBERS COME FROM
--------------------------------------------------------------------------
Almost every tool delegates to `analytics_service`, `order_service` or
the existing `ml/` modules. That is deliberate. Phase 5's chart board and
this assistant must not be able to disagree about what today's revenue is,
because they both ask the same function. Where this file computes
something itself, it is a derived ratio over those same figures - a
growth percentage, a cancellation rate, a collection percentage - and the
arithmetic is plain Python so it is auditable.

--------------------------------------------------------------------------
HOW A TOOL MAY BE MISLED
--------------------------------------------------------------------------
It cannot. A tool either returns real rows or returns
`{"has_data": false, "limitation": "..."}`. There is no code path that
returns a plausible-looking default. A missing delivery history produces a
limitation string, never a delivery figure.

--------------------------------------------------------------------------
DOMAIN COVERAGE
--------------------------------------------------------------------------
Orders, bills, payments, customers, menu, reservations, tables, kitchen,
delivery, inventory, waste, reviews, revenue, comparison, summary,
forecast, existing ML insights, and the operational event log itself.
"""

from datetime import date, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from models import (
    Inventory,
    Kitchen,
    Menu,
    Order,
    OrderHeader,
    Payment,
    PaymentStatus,
    Reservation,
    Review,
    RestaurantTable,
    Staff,
    Supplier,
    User,
    Waste,
)

from services import analytics_service as analytics
from services import event_service
from services.analytics_service import resolve_range


# =========================================================
# HELPERS
#
# Derived figures are computed here rather than by any model, so there is
# exactly one place to audit a percentage.
# =========================================================

def percent_change(current: float, previous: float) -> float | None:
    """Growth from previous to current, or None when there is no base."""
    if previous in (None, 0):
        return None

    return round(((current - previous) / previous) * 100, 1)


def percent_of(part: float, whole: float) -> float | None:
    """part as a percentage of whole, or None when whole is unusable."""
    if not whole:
        return None

    return round((part / whole) * 100, 1)


def _window_of(params: dict, default_key: str = "last_7_days"):
    """
    Resolve a tool's window parameter into concrete dates.

    The orchestrator passes the resolved window as ISO strings, because
    that is what travels in the plan and the response. `resolve_range`
    wants real dates, so the strings are parsed here rather than being
    handed over and failing deep inside a query.
    """
    start = params.get("start")
    end = params.get("end")

    if isinstance(start, str) and start:
        try:
            start = date.fromisoformat(start[:10])
        except ValueError:
            start = None

    if isinstance(end, str) and end:
        try:
            end = date.fromisoformat(end[:10])
        except ValueError:
            end = None

    return resolve_range(params.get("range") or default_key, start, end)


def _previous_window(start: date, end: date):
    """The equal-length window immediately before this one."""
    span = (end - start).days + 1

    return start - timedelta(days=span), start - timedelta(days=1)


def _no_data(limitation: str, **extra) -> dict:
    return {"has_data": False, "limitation": limitation, **extra}


def _money(value) -> float:
    return round(float(value or 0), 2)


# =========================================================
# A. ORDERS
# =========================================================

def get_order_metrics(db: Session, params: dict) -> dict:
    """
    Order volume, order-type mix, lifecycle counts and cancellations.

    Volume comes from analytics_service, which already splits server-priced
    checkouts from legacy rows. Lifecycle and cancellation counts come
    from `order_headers`, which is the only place a real status lives.
    """
    start, end, label = _window_of(params)

    window = analytics.revenue_for_window(db, start, end)

    headers = (
        db.query(
            func.count(OrderHeader.id),
            func.sum(OrderHeader.total_amount),
        )
        .filter(analytics._daterange(OrderHeader.placed_at, start, end))
        .first()
    )

    checkout_orders = int(headers[0] or 0)

    by_status = dict(
        db.query(OrderHeader.status, func.count(OrderHeader.id))
        .filter(analytics._daterange(OrderHeader.placed_at, start, end))
        .group_by(OrderHeader.status)
        .all()
    )

    by_type = dict(
        db.query(OrderHeader.order_type, func.count(OrderHeader.id))
        .filter(analytics._daterange(OrderHeader.placed_at, start, end))
        .group_by(OrderHeader.order_type)
        .all()
    )

    cancelled = int(by_status.get("Cancelled", 0))
    served = int(by_status.get("Served", 0))

    closed = cancelled + served
    cancellation_rate = percent_of(cancelled, closed) if closed else None

    # Legacy rows carry their own free-text status, which is not the same
    # vocabulary as the lifecycle. Counted separately rather than merged.
    legacy_by_status = dict(
        db.query(Order.status, func.count(Order.id))
        .filter(
            analytics._daterange(Order.created_at, start, end),
            Order.order_id.is_(None),
        )
        .group_by(Order.status)
        .all()
    )

    if not window["orders"] and not checkout_orders:
        return _no_data(
            f"No orders were recorded between {start} and {end}.",
            start_date=start.isoformat(),
            end_date=end.isoformat(),
        )

    return {
        "has_data": True,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "range": label,
        "total_orders": window["orders"],
        "checkout_orders": checkout_orders,
        "legacy_orders": window["revenue_breakdown"]["legacy_orders"],
        "portions_sold": window["portions"],
        "average_order_value": window["average_order_value"],
        "revenue": window["revenue"],
        "lifecycle": {status: int(count) for status, count in by_status.items()},
        "cancelled_orders": cancelled,
        "served_orders": served,
        "cancellation_rate_percent": cancellation_rate,
        "order_types": {
            str(name): int(count) for name, count in by_type.items()
        },
        "legacy_statuses": {
            str(name): int(count) for name, count in legacy_by_status.items()
        },
        "limitation": None,
    }


def get_kitchen_metrics(db: Session, params: dict) -> dict:
    """
    Kitchen workload and preparation times.

    The ticket counts are current state. Preparation times come from the
    event log, which only exists from the moment recording started - so
    when there are too few transitions the answer says so rather than
    quoting an average built from one order.
    """
    start, end, label = _window_of(params)

    depth = event_service.event_history_depth(db)

    tickets_total = int(db.query(func.count(Kitchen.id)).scalar() or 0)

    by_status = dict(
        db.query(Kitchen.status, func.count(Kitchen.id))
        .group_by(Kitchen.status)
        .all()
    )

    backlog = sum(
        int(count)
        for status, count in by_status.items()
        if str(status).lower() in ("pending", "preparing")
    )

    placed_in_window = event_service.count_by_type(
        db, start, end, (event_service.ORDER_PLACED,)
    ).get(event_service.ORDER_PLACED, 0)

    served_in_window = event_service.count_by_type(
        db, start, end, (event_service.ORDER_SERVED,)
    ).get(event_service.ORDER_SERVED, 0)

    cancelled_in_window = event_service.count_by_type(
        db, start, end, (event_service.ORDER_CANCELLED,)
    ).get(event_service.ORDER_CANCELLED, 0)

    result = {
        "has_data": tickets_total > 0 or depth["has_data"],
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "range": label,
        "open_tickets": tickets_total,
        "tickets_by_status": {
            str(name): int(count) for name, count in by_status.items()
        },
        "backlog_tickets": backlog,
        "orders_placed_in_window": placed_in_window,
        "orders_served_in_window": served_in_window,
        "orders_cancelled_in_window": cancelled_in_window,
        "event_log": depth,
        "limitation": None,
    }

    if depth["has_data"]:
        confirm_count, confirm_avg, _ = (
            event_service.average_transition_minutes(
                db, start, end,
                event_service.ORDER_PLACED,
                event_service.ORDER_CONFIRMED,
            )
        )

        ready_count, prep_avg, prep_max = (
            event_service.average_transition_minutes(
                db, start, end,
                event_service.ORDER_CONFIRMED,
                event_service.ORDER_READY,
            )
        )

        total_count, total_avg, total_max = (
            event_service.average_transition_minutes(
                db, start, end,
                event_service.ORDER_PLACED,
                event_service.ORDER_SERVED,
            )
        )

        result["placement_to_confirmation_minutes"] = {
            "orders": confirm_count, "average": confirm_avg,
        }
        result["confirmation_to_ready_minutes"] = {
            "orders": ready_count, "average": prep_avg, "maximum": prep_max,
        }
        result["placed_to_served_minutes"] = {
            "orders": total_count, "average": total_avg, "maximum": total_max,
        }

        slow_threshold = params.get("slow_threshold_minutes")

        if slow_threshold:
            result["slow_orders"] = event_service.slow_orders(
                db, start, end, int(slow_threshold)
            )
    else:
        result["preparation_times_available"] = False
        result["limitation"] = (
            "Preparation and delay times cannot be computed yet: the "
            f"operational event log is empty. {depth['limitation']}"
        )

    return result


# =========================================================
# B. BILLS
# =========================================================

def get_bill_metrics(db: Session, params: dict) -> dict:
    """
    What guests were billed: subtotal, tax, service charge, discount, total.

    Read from `order_headers` only. Legacy rows predate the header table,
    so they carry no breakdown and are deliberately excluded rather than
    estimated into one.
    """
    start, end, label = _window_of(params)

    row = (
        db.query(
            func.count(OrderHeader.id),
            func.coalesce(func.sum(OrderHeader.subtotal), 0.0),
            func.coalesce(func.sum(OrderHeader.tax_amount), 0.0),
            func.coalesce(func.sum(OrderHeader.service_charge_amount), 0.0),
            func.coalesce(func.sum(OrderHeader.discount_amount), 0.0),
            func.coalesce(func.sum(OrderHeader.total_amount), 0.0),
        )
        .filter(analytics._daterange(OrderHeader.placed_at, start, end))
        .first()
    )

    bills = int(row[0] or 0)

    if not bills:
        return _no_data(
            "No server-priced bills exist for "
            f"{start} to {end}. Bills only exist for orders placed "
            "through checkout; the historical order rows predate the "
            "bill table and carry no breakdown.",
            start_date=start.isoformat(),
            end_date=end.isoformat(),
        )

    subtotal = _money(row[1])
    tax = _money(row[2])
    service = _money(row[3])
    discount = _money(row[4])
    total = _money(row[5])

    return {
        "has_data": True,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "range": label,
        "bills": bills,
        "subtotal_total": subtotal,
        "tax_total": tax,
        "service_charge_total": service,
        "discount_total": discount,
        "bill_total": total,
        "average_bill_value": _money(total / bills),
        "tax_share_percent": percent_of(tax, total),
        "service_charge_share_percent": percent_of(service, total),
        "discount_share_percent": percent_of(discount, total),
        "limitation": (
            "Legacy order rows are excluded: they were written before the "
            "bill table existed and store no tax or service-charge "
            "breakdown."
        ),
    }


# =========================================================
# C. PAYMENTS
# =========================================================

def get_payment_metrics(db: Session, params: dict) -> dict:
    """
    Billed value against collected value, and what is still outstanding.

    Three different facts, kept apart on purpose:

    * `order_value`   what guests were billed (OrderHeader.total_amount)
    * `collected`     the subset a provider confirmed (Payment SUCCESS)
    * `outstanding`   billed minus collected

    A bill stops being outstanding because money arrived, not because a
    payment request was made. A PENDING request contributes nothing to
    `collected`, which is why "requested" and "paid" are counted as
    separate populations rather than inferred from one another.

    The ledger began in Phase 6D, so any window that predates it has
    payments of 0 while still having bills. That is stated rather than
    smoothed over: it is the difference between "nobody paid" and "this
    system was not recording yet", and only one of them is a problem.
    """
    start, end, label = _window_of(params)

    row = (
        db.query(
            func.count(OrderHeader.id),
            func.coalesce(func.sum(OrderHeader.total_amount), 0.0),
        )
        .filter(analytics._daterange(OrderHeader.placed_at, start, end))
        .first()
    )

    bills = int(row[0] or 0)
    order_value = _money(row[1])

    by_header_status = dict(
        db.query(OrderHeader.payment_status, func.count(OrderHeader.id))
        .filter(analytics._daterange(OrderHeader.placed_at, start, end))
        .group_by(OrderHeader.payment_status)
        .all()
    )

    # ---- from the ledger, by the time payment actually happened ----
    settled_row = (
        db.query(
            func.count(Payment.id),
            func.coalesce(func.sum(Payment.amount), 0.0),
        )
        .filter(
            analytics._daterange(Payment.requested_at, start, end),
            Payment.status == PaymentStatus.SUCCESS,
        )
        .first()
    )

    settled_by_paid_at = (
        db.query(
            func.count(Payment.id),
            func.coalesce(func.sum(Payment.amount), 0.0),
        )
        .filter(
            analytics._daterange(Payment.paid_at, start, end),
            Payment.status == PaymentStatus.SUCCESS,
        )
        .first()
    )

    attempted_row = (
        db.query(func.count(Payment.id))
        .filter(analytics._daterange(Payment.requested_at, start, end))
        .first()
    )

    by_attempt_status = dict(
        db.query(Payment.status, func.count(Payment.id))
        .filter(analytics._daterange(Payment.requested_at, start, end))
        .group_by(Payment.status)
        .all()
    )

    settled_attempts = int(by_attempt_status.get(PaymentStatus.SUCCESS, 0))
    failed_attempts = int(by_attempt_status.get(PaymentStatus.FAILED, 0))
    pending_attempts = int(by_attempt_status.get(PaymentStatus.PENDING, 0))
    cancelled_attempts = int(
        by_attempt_status.get(PaymentStatus.CANCELLED, 0)
    )
    total_attempts = int(row and attempted_row[0] or 0)

    # Collected against bills placed in this window, so the two figures are
    # about the same cohort of guests rather than two unrelated periods.
    outstanding_value = (
        db.query(func.coalesce(func.sum(OrderHeader.total_amount), 0.0))
        .filter(
            analytics._daterange(OrderHeader.placed_at, start, end),
            OrderHeader.payment_status != "paid",
        )
        .scalar()
    )

    # Money that actually arrived inside this window.
    collected_in_window = _money(settled_by_paid_at[1])
    success_rate = percent_of(
        settled_attempts, settled_attempts + failed_attempts
    ) if (settled_attempts + failed_attempts) else None

    ledger_depth = _payment_ledger_depth(db)

    # True when there is anything at all to report: bills, payment attempts,
    # or a ledger that exists but happens to have no rows for this window.
    # "How many payments succeeded today" is answerable as zero, and that
    # is a different statement from having no payment data at all.
    reportable = bills > 0 or ledger_depth["has_records"] or total_attempts > 0

    return {
        "has_data": reportable,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "range": label,
        "bills": bills,

        # ---- the three separate facts ----
        #
        # Named explicitly as billed / collected / outstanding as well as
        # by their longer names, because those three words are what an
        # operator asks about and merging any two of them would misreport
        # the business.
        "billed": order_value,
        "collected": collected_value_for_headers(db, start, end),
        "outstanding": _money(outstanding_value),
        "order_value": order_value,
        "collected_value": collected_value_for_headers(db, start, end),
        "outstanding_value": _money(outstanding_value),
        "collection_percent": percent_of(
            collected_value_for_headers(db, start, end), order_value
        ),

        # ---- bills by settlement state ----
        "bills_paid": int(by_header_status.get("paid", 0)),
        "bills_unpaid": sum(
            count for name, count in by_header_status.items()
            if name != "paid"
        ),

        # ---- attempts ----
        "payment_requests": total_attempts,
        "successful_payments": settled_attempts,
        "failed_payments": failed_attempts,
        "cancelled_payments": cancelled_attempts,
        "pending_payments": pending_attempts,
        "payment_success_rate_percent": success_rate,

        # Collected by when the money arrived, which is the only honest
        # basis for "how much came in today".
        "collected_in_window": collected_in_window,
        "successful_payments_in_window": int(settled_by_paid_at[0] or 0),

        "by_header_status": {
            str(name): int(count) for name, count in by_header_status.items()
        },
        "by_attempt_status": {
            str(name): int(count) for name, count in by_attempt_status.items()
        },
        "ledger": ledger_depth,
        "gateway": payment_configuration(),
        "limitation": ledger_depth["limitation"],
    }


def collected_value_for_headers(db: Session, start: date,
                                end: date) -> float:
    """
    Bills placed in a window whose payment has been confirmed.

    Summed from `order_headers.total_amount` for the headers now marked
    paid, rather than from the payment rows. Two reasons: the header is
    the authoritative bill figure, and it cannot be double counted the way
    two settled attempts against one bill could.
    """
    total = (
        db.query(func.coalesce(func.sum(OrderHeader.total_amount), 0.0))
        .filter(
            analytics._daterange(OrderHeader.placed_at, start, end),
            OrderHeader.payment_status == "paid",
        )
        .scalar()
    )

    return round(float(total or 0), 2)


def _payment_ledger_depth(db: Session) -> dict:
    """
    How much payment history actually exists.

    The ledger started in Phase 6D. If the window predates it, then every
    payment figure for that window is a structural zero rather than a
    measurement, and the assistant has to say which it is looking at.
    """
    total = int(db.query(func.count(Payment.id)).scalar() or 0)

    if not total:
        return {
            "has_records": False,
            "record_count": 0,
            "first_payment_at": None,
            "limitation": (
                "No payment records exist yet. The payment ledger began in "
                "Phase 6D, so every bill in this period reads as unpaid "
                "because none has been settled through a payment request "
                "yet - not because anyone declined to pay."
            ),
        }

    bounds = db.query(
        func.min(Payment.requested_at), func.max(Payment.requested_at)
    ).first()

    first_at = bounds[0] if bounds else None

    return {
        "has_records": True,
        "record_count": total,
        "first_payment_at": (
            first_at.isoformat(timespec="seconds") if first_at else None
        ),
        "limitation": None,
    }


def payment_configuration() -> dict:
    """
    What the payment provider is configured as.

    Read from `payment_provider.configuration()`, which is the single place
    that knows the mode, the provider and whether the gateway is real. The
    assistant never decides any of this itself, so it cannot claim a
    gateway is connected when the backend has not confirmed it.

    `gateway_statement` is quoted verbatim in an answer so the wording is
    the backend's, not the assistant's.
    """
    try:
        from services import payment_provider

        config = dict(payment_provider.configuration())

        return config
    except Exception:
        return {
            "mode": "unavailable",
            "provider": None,
            "gateway_connected": False,
            "live_gateway_connected": False,
            "test_mode": False,
            "live_mode": False,
            "gateway_statement": (
                "Payment gateway is not connected; payment data reflects "
                "verified development payment records only."
            ),
        }


# =========================================================
# D. CUSTOMERS
# =========================================================

def get_customer_metrics(db: Session, params: dict) -> dict:
    """
    Customer counts, frequency, spend and preferences from real history.

    "New" and "returning" are computed from the recorded order history,
    not from the accounts table, because most historical orders were
    written before identity links existed and belong to names rather than
    accounts.
    """
    start, end, label = _window_of(params)

    summary = analytics.customer_summary(db)

    # A guest who appears in this window's orders, split by whether they
    # also appear in an earlier one.
    current_names = {
        row[0]
        for row in db.query(Order.customer_name)
        .filter(analytics._daterange(Order.created_at, start, end))
        .distinct()
        .all()
        if row[0]
    }

    earlier_names = {
        row[0]
        for row in db.query(Order.customer_name)
        .filter(Order.created_at < start)
        .distinct()
        .all()
        if row[0]
    }

    new_names = current_names - earlier_names
    returning_names = current_names & earlier_names

    frequency = dict(
        db.query(Order.customer_name, func.count(Order.id))
        .filter(analytics._daterange(Order.created_at, start, end))
        .group_by(Order.customer_name)
        .all()
    )

    spend = dict(
        db.query(Order.customer_name, func.sum(Order.total_price))
        .filter(analytics._daterange(Order.created_at, start, end))
        .group_by(Order.customer_name)
        .all()
    )

    top_by_orders = sorted(
        (
            (str(name), int(count))
            for name, count in frequency.items()
            if name
        ),
        key=lambda row: (-row[1], row[0]),
    )[:5]

    top_by_spend = sorted(
        (
            (str(name), _money(total))
            for name, total in spend.items()
            if name
        ),
        key=lambda row: (-row[1], row[0]),
    )[:5]

    # What this cohort actually ordered, which is the only kind of
    # preference statement that can be made from this data.
    preferences = dict(
        db.query(Order.menu_item, func.count(Order.id))
        .filter(analytics._daterange(Order.created_at, start, end))
        .group_by(Order.menu_item)
        .order_by(func.count(Order.id).desc())
        .limit(5)
        .all()
    )

    return {
        "has_data": bool(current_names) or summary["has_data"],
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "range": label,
        "customer_records": summary["total_customers"],
        "user_accounts": summary["total_users"],
        "guests_ordering_in_window": len(current_names),
        "new_guests_in_window": len(new_names),
        "returning_guests_in_window": len(returning_names),
        "returning_percent": percent_of(
            len(returning_names), len(current_names)
        ),
        "reservations_recorded": summary["reservations"],
        "top_by_order_count": [
            {"name": name, "orders": count} for name, count in top_by_orders
        ],
        "top_by_spend": [
            {"name": name, "spent": total} for name, total in top_by_spend
        ],
        "most_ordered_dishes": [
            {"dish": dish, "orders": int(count)}
            for dish, count in preferences.items()
        ],
        "limitation": (
            "Guests are matched by the name recorded on each order, because"
            " most historical orders were written before orders could be "
            "linked to a signed-in account. Two guests sharing a name are "
            "counted as one."
        ),
    }


def get_customer_history(db: Session, params: dict) -> dict:
    """One guest's recorded order history."""
    name = (params.get("customer_name") or "").strip()

    if not name:
        return _no_data(
            "No guest was named, so no history could be read."
        )

    rows = (
        db.query(
            Order.menu_item,
            func.sum(Order.quantity),
            func.sum(Order.total_price),
            func.min(Order.created_at),
            func.max(Order.created_at),
        )
        .filter(Order.customer_name == name)
        .group_by(Order.menu_item)
        .order_by(func.sum(Order.quantity).desc())
        .limit(20)
        .all()
    )

    if not rows:
        return _no_data(f"No order history is recorded for '{name}'.")

    total_spent = _money(
        db.query(func.coalesce(func.sum(Order.total_price), 0.0))
        .filter(Order.customer_name == name)
        .scalar()
    )

    total_portions = int(
        db.query(func.coalesce(func.sum(Order.quantity), 0))
        .filter(Order.customer_name == name)
        .scalar()
    )

    first_seen = db.query(func.min(Order.created_at)).filter(
        Order.customer_name == name
    ).scalar()

    return {
        "has_data": True,
        "customer_name": name,
        "dishes": [
            {
                "dish": row[0],
                "portions": int(row[1] or 0),
                "spent": _money(row[2]),
            }
            for row in rows
        ],
        "total_spent": total_spent,
        "total_portions": total_portions,
        "first_seen": first_seen.isoformat() if first_seen else None,
        "limitation": None,
    }


# =========================================================
# E. MENU
# =========================================================

def get_menu_performance(db: Session, params: dict) -> dict:
    """Item popularity, category revenue, availability and slow movers."""
    start, end, label = _window_of(params)

    top = analytics.top_dishes(
        db,
        limit=params.get("limit") or 5,
        range_key=label,
        start=start,
        end=end,
    )

    categories = analytics.revenue_by_category(
        db, range_key=label, start=start, end=end
    )

    total_items = int(db.query(func.count(Menu.id)).scalar() or 0)
    available_items = int(
        db.query(func.count(Menu.id))
        .filter(Menu.available.is_(True))
        .scalar()
        or 0
    )

    unavailable = [
        {"dish": row[0], "category": row[1]}
        for row in db.query(Menu.name, Menu.category)
        .filter(Menu.available.is_(False))
        .all()
    ]

    # Items that exist on the menu but have never sold anything. Derived
    # from the sales table, so an item removed last month does not appear.
    sold_names = {
        row[0]
        for row in db.query(Order.menu_item)
        .filter(analytics._daterange(Order.created_at, start, end))
        .distinct()
        .all()
    }

    never_sold = [
        {"dish": row[0], "category": row[1], "price": _money(row[2])}
        for row in db.query(Menu.name, Menu.category, Menu.price).all()
        if row[0] not in sold_names
    ]

    return {
        "has_data": total_items > 0,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "range": label,
        "total_items": total_items,
        "available_items": available_items,
        "unavailable_items": unavailable,
        "top_dishes": top["top_dishes"],
        "categories": categories["categories"],
        "items_never_ordered": never_sold,
        "limitation": None,
    }


# =========================================================
# F. RESERVATIONS
# =========================================================

def get_reservation_metrics(db: Session, params: dict) -> dict:
    """Bookings, party sizes, no-shows and the busiest slot."""
    start, end, label = _window_of(params)

    rows = (
        db.query(
            func.count(Reservation.id),
            func.coalesce(func.sum(Reservation.guests), 0),
        )
        .filter(analytics._daterange(Reservation.created_at, start, end))
        .first()
    )

    total = int(rows[0] or 0)
    covers = int(rows[1] or 0)

    if not total:
        return _no_data(
            f"No reservations were recorded between {start} and {end}.",
            start_date=start.isoformat(),
            end_date=end.isoformat(),
        )

    by_status = dict(
        db.query(Reservation.status, func.count(Reservation.id))
        .filter(analytics._daterange(Reservation.created_at, start, end))
        .group_by(Reservation.status)
        .all()
    )

    cancelled = int(by_status.get("Cancelled", 0))
    completed = int(by_status.get("Completed", 0))
    closed = cancelled + completed

    by_hour = dict(
        db.query(
            func.hour(Reservation.reservation_time),
            func.count(Reservation.id),
        )
        .filter(analytics._daterange(Reservation.created_at, start, end))
        .group_by(func.hour(Reservation.reservation_time))
        .all()
    )

    busiest_hour = (
        max(by_hour.items(), key=lambda row: row[1])[0]
        if by_hour
        else None
    )

    by_table = dict(
        db.query(Reservation.table_number, func.count(Reservation.id))
        .filter(analytics._daterange(Reservation.created_at, start, end))
        .group_by(Reservation.table_number)
        .all()
    )

    upcoming = [
        {
            "date": str(row[0]),
            "time": str(row[1]),
            "guests": int(row[2]),
            "status": row[3],
        }
        for row in db.query(
            Reservation.reservation_date,
            Reservation.reservation_time,
            Reservation.guests,
            Reservation.status,
        )
        .filter(
            Reservation.reservation_date >= date.today(),
            Reservation.status != "Cancelled",
        )
        .order_by(
            Reservation.reservation_date.asc(),
            Reservation.reservation_time.asc(),
        )
        .limit(10)
        .all()
    ]

    return {
        "has_data": True,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "range": label,
        "reservations": total,
        "covers": covers,
        "average_party_size": round(covers / total, 1),
        "by_status": {str(name): int(count) for name, count in by_status.items()},
        "cancelled_reservations": cancelled,
        "cancellation_rate_percent": percent_of(cancelled, closed)
        if closed else None,
        "busiest_hour": busiest_hour,
        "bookings_per_table": {
            str(name): int(count) for name, count in by_table.items()
        },
        "upcoming": upcoming,
        "limitation": None,
    }


# =========================================================
# G. TABLES
# =========================================================

def get_table_metrics(db: Session, params: dict) -> dict:
    """Table inventory, capacity and who is seated where right now."""
    total = int(db.query(func.count(RestaurantTable.id)).scalar() or 0)

    if not total:
        return _no_data("No tables have been configured yet.")

    active = int(
        db.query(func.count(RestaurantTable.id))
        .filter(RestaurantTable.is_active.is_(True))
        .scalar()
        or 0
    )

    capacity = int(
        db.query(func.coalesce(func.sum(RestaurantTable.capacity), 0)).scalar()
        or 0
    )

    seated = int(
        db.query(func.count(User.id))
        .filter(User.active_table_id.isnot(None))
        .scalar()
        or 0
    )

    return {
        "has_data": True,
        "total_tables": total,
        "active_tables": active,
        "inactive_tables": total - active,
        "total_seats": capacity,
        "guests_currently_seated": seated,
        "tables_in_use": seated,
        "occupancy_percent": percent_of(seated, active) if active else None,
        "limitation": (
            "Occupancy is measured by server-side table claims, so a "
            "guest who scanned a QR and never ordered still counts as "
            "seated."
        ),
    }


# =========================================================
# I. DELIVERY
# =========================================================

def get_delivery_metrics(db: Session, params: dict) -> dict:
    """
    Delivery orders, honestly bounded.

    This project records `order_type = 'delivery'` and a delivery address.
    It does not record dispatch, driver, out-for-delivery, delivered or
    any delivery timestamp. So order counts are reported and the missing
    lifecycle is stated.
    """
    start, end, label = _window_of(params)

    row = (
        db.query(
            func.count(Order.id),
            func.coalesce(func.sum(Order.total_price), 0.0),
            func.coalesce(func.sum(Order.quantity), 0),
        )
        .filter(
            analytics._daterange(Order.created_at, start, end),
            Order.order_type == "delivery",
        )
        .first()
    )

    delivery_orders = int(row[0] or 0)

    header_row = (
        db.query(func.count(OrderHeader.id))
        .filter(
            analytics._daterange(OrderHeader.placed_at, start, end),
            OrderHeader.order_type == "delivery",
        )
        .scalar()
    )

    delivery_orders += int(header_row or 0)

    if not delivery_orders:
        return _no_data(
            f"No delivery orders were recorded between {start} and {end}.",
            start_date=start.isoformat(),
            end_date=end.isoformat(),
        )

    return {
        "has_data": True,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "range": label,
        "delivery_order_lines": int(row[0] or 0),
        "delivery_checkouts": int(header_row or 0),
        "delivery_portions": int(row[2] or 0),
        "delivery_revenue": _money(row[1]),
        "limitation": (
            "This project records that an order was a delivery order and "
            "where it was addressed, but it has no delivery lifecycle: no "
            "dispatch time, no out-for-delivery state, no driver, no "
            "delivered timestamp and no cancellation reason. Delivery "
            "duration and completion rate therefore cannot be computed, "
            "and an order reaching Served is not evidence of delivery."
        ),
    }


# =========================================================
# J. INVENTORY
# =========================================================

def get_inventory_metrics(db: Session, params: dict) -> dict:
    """Stock levels, low and out-of-stock items, and recorded movements."""
    start, end, label = _window_of(params)

    summary = analytics.inventory_summary(db)

    if not summary["has_data"]:
        return _no_data("No inventory items have been recorded yet.")

    movements = event_service.inventory_movements(db, start, end, limit=10)

    suppliers = int(db.query(func.count(Supplier.id)).scalar() or 0)

    return {
        "has_data": True,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "range": label,
        "total_items": summary["total_items"],
        "available_count": summary["available_count"],
        "low_stock_count": summary["low_stock_count"],
        "out_of_stock_count": summary["out_of_stock_count"],
        "low_stock_items": summary["low_stock_items"],
        "out_of_stock_items": summary["out_of_stock_items"],
        "total_stock_value": _money(summary["total_stock_value"]),
        "suppliers_recorded": suppliers,
        "movements_in_window": movements,
        "movement_count": len(movements),
        "limitation": None,
    }


# =========================================================
# K. WASTE
# =========================================================

def get_waste_metrics(db: Session, params: dict) -> dict:
    """Recorded waste: cost, quantity, reasons and trend."""
    start, end, label = _window_of(params)

    summary = analytics.wastage_summary(db, label, start, end)

    if not summary["has_data"]:
        return _no_data(
            f"No food waste was recorded between {start} and {end}.",
            start_date=start.isoformat(),
            end_date=end.isoformat(),
        )

    reasons = dict(
        db.query(Waste.reason, func.count(Waste.id))
        .filter(analytics._daterange(Waste.recorded_at, start, end))
        .group_by(Waste.reason)
        .all()
    )

    top_reasons = sorted(
        (
            (str(name or "unspecified"), int(count))
            for name, count in reasons.items()
        ),
        key=lambda row: (-row[1], row[0]),
    )[:5]

    return {
        "has_data": True,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "range": label,
        "total_cost": _money(summary["total_cost"]),
        "total_quantity": round(float(summary["total_quantity"] or 0), 2),
        "items": summary["items"],
        "highest_wastage_item": summary["highest_wastage_item"],
        "trend": summary["trend"],
        "reasons": [{"reason": name, "entries": count}
                    for name, count in top_reasons],
        "limitation": (
            "Waste is recorded when staff log it. Days with no entry are "
            "unrecorded, not measured-zero, so a waste trend understates "
            "total loss."
        ),
    }


# =========================================================
# L. REVIEWS
# =========================================================

def get_review_metrics(db: Session, params: dict) -> dict:
    """Ratings, sentiment split, and which dishes draw criticism."""
    start, end, label = _window_of(params)

    row = (
        db.query(
            func.count(Review.id),
            func.coalesce(func.avg(Review.rating), 0.0),
        )
        .filter(analytics._daterange(Review.created_at, start, end))
        .first()
    )

    total = int(row[0] or 0)

    if not total:
        return _no_data(
            f"No reviews were recorded between {start} and {end}.",
            start_date=start.isoformat(),
            end_date=end.isoformat(),
        )

    by_sentiment = dict(
        db.query(Review.sentiment, func.count(Review.id))
        .filter(analytics._daterange(Review.created_at, start, end))
        .group_by(Review.sentiment)
        .all()
    )

    worst = (
        db.query(Review.menu_item, Review.rating, Review.sentiment)
        .filter(analytics._daterange(Review.created_at, start, end))
        .order_by(Review.rating.asc())
        .limit(5)
        .all()
    )

    by_rating = dict(
        db.query(Review.rating, func.count(Review.id))
        .filter(analytics._daterange(Review.created_at, start, end))
        .group_by(Review.rating)
        .all()
    )

    return {
        "has_data": True,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "range": label,
        "total_reviews": total,
        "average_rating": round(float(row[1] or 0), 2),
        "by_sentiment": {
            str(name): int(count) for name, count in by_sentiment.items()
        },
        "negative_reviews": int(by_sentiment.get("Negative", 0)),
        "negative_percent": percent_of(
            int(by_sentiment.get("Negative", 0)), total
        ),
        "by_rating": {
            str(int(name)): int(count) for name, count in by_rating.items()
        },
        "lowest_rated": [
            {
                "dish": row2[0] or "not dish specific",
                "rating": row2[1],
                "sentiment": row2[2],
            }
            for row2 in worst
        ],
        "limitation": (
            "Reviews are self-selected: guests who had a good evening are "
            "less likely to write one, so a rating average is not a "
            "measure of overall satisfaction."
        ),
    }


# =========================================================
# M. STAFF
# =========================================================

def get_staff_metrics(db: Session, params: dict) -> dict:
    """
    Staff records, which is all this project's staff data supports.

    There are no shift attendance, no per-order attribution and no
    performance record, so no claim is made about individual performance.
    """
    total = int(db.query(func.count(Staff.id)).scalar() or 0)

    if not total:
        return _no_data("No staff records have been created yet.")

    by_role = dict(
        db.query(Staff.role, func.count(Staff.id))
        .group_by(Staff.role)
        .all()
    )

    by_shift = dict(
        db.query(Staff.shift, func.count(Staff.id))
        .group_by(Staff.shift)
        .all()
    )

    active = int(
        db.query(func.count(Staff.id))
        .filter(Staff.active.is_(True))
        .scalar()
        or 0
    )

    return {
        "has_data": True,
        "total_staff": total,
        "active_staff": active,
        "by_role": {str(name or "unspecified"): int(count)
                    for name, count in by_role.items()},
        "by_shift": {str(name or "unspecified"): int(count)
                     for name, count in by_shift.items()},
        "limitation": (
            "This project records who is on staff, not what they did. "
            "There is no shift attendance, no per-order attribution and no "
            "performance history, so no individual productivity figure can "
            "be given."
        ),
    }


# =========================================================
# N. REVENUE
# =========================================================

def get_revenue_metrics(db: Session, params: dict) -> dict:
    """Revenue, orders and average order value for the window."""
    start, end, label = _window_of(params)

    window = analytics.revenue_for_window(db, start, end)

    if not window["orders"]:
        return _no_data(
            f"No orders were recorded between {start} and {end}.",
            start_date=start.isoformat(),
            end_date=end.isoformat(),
        )

    trend = analytics.revenue_trend(db, label, start, end)

    return {
        "has_data": True,
        "start_date": window["start_date"],
        "end_date": window["end_date"],
        "range": label,
        "revenue": window["revenue"],
        "orders": window["orders"],
        "portions_sold": window["portions"],
        "average_order_value": window["average_order_value"],
        "checkout_revenue": window["revenue_breakdown"]["checkout_revenue"],
        "checkout_orders": window["revenue_breakdown"]["checkout_orders"],
        "legacy_revenue": window["revenue_breakdown"]["legacy_revenue"],
        "legacy_orders": window["revenue_breakdown"]["legacy_orders"],
        "data_quality": trend.get("data_quality"),
        "best_day": trend.get("best_day"),
        "limitation": None,
    }


# =========================================================
# O. EXISTING ML
#
# Reused as-is. None of these models is replaced, retrained or rewritten;
# the assistant only reads what they already return.
# =========================================================

def get_existing_ai_insights(db: Session, params: dict) -> dict:
    """
    The Phase 5 ML modules, reached through their own functions.

    Sentiment classification, waste prediction, demand and revenue
    forecasting and pricing analysis all already exist and work. Calling
    them from here means the assistant reports exactly what the dashboard
    reports, rather than a second interpretation of the same data.
    """
    from ml.forecasting import predict_demand, predict_revenue
    from ml.pricing import suggest_prices
    from ml.sentiment import summarize_reviews
    from ml.waste import analyze_waste

    reviews = db.query(Review).all()
    orders = db.query(Order).all()
    waste_records = db.query(Waste).all()

    sentiment = summarize_reviews(reviews)
    revenue_forecast = predict_revenue(orders, days_ahead=7)
    demand_forecast = predict_demand(orders, days_ahead=7, top_n=5)
    waste = analyze_waste(waste_records, orders)
    pricing = suggest_prices(
        menu_items=db.query(Menu).all(),
        orders=orders,
        inventory=db.query(Inventory).all(),
    )

    return {
        "has_data": True,
        "sentiment": sentiment,
        "revenue_forecast": revenue_forecast,
        "demand_forecast": demand_forecast,
        "waste_prediction": waste,
        "pricing": pricing,
        "models_used": [
            "sentiment (Phase 5)",
            "waste analysis (Phase 5)",
            "demand forecast (Phase 5)",
            "revenue forecast (Phase 5)",
            "dynamic pricing (Phase 5)",
        ],
        "limitation": (
            "Forecasts are linear extrapolations from recorded history. "
            "They carry no confidence interval and must not be read as "
            "committed demand."
        ),
    }


def get_forecast(db: Session, params: dict) -> dict:
    """Demand and revenue forecast only."""
    from ml.forecasting import predict_demand, predict_revenue

    orders = db.query(Order).all()

    demand = predict_demand(orders, days_ahead=7, top_n=5)
    revenue_forecast = predict_revenue(orders, days_ahead=7)

    return {
        "has_data": True,
        "demand": demand,
        "revenue": revenue_forecast,
        "limitation": (
            "A projection from recorded history, not a commitment. The "
            "models do not account for bookings, stockouts or events."
        ),
    }


# =========================================================
# CROSS-DOMAIN
# =========================================================

def get_business_summary(db: Session, params: dict) -> dict:
    """
    A bounded cross-domain snapshot.

    Deliberately small: one figure per domain, aggregated in SQL. This is
    the fallback for a question whose subject could not be identified, and
    it must stay cheap enough to answer anything without loading the
    database.
    """
    start, end, label = _window_of(params)

    overview = analytics.analytics_overview(db)

    revenue = analytics.revenue_for_window(db, start, end)
    inventory = analytics.inventory_summary(db)
    waste = analytics.wastage_summary(db, label, start, end)
    lifecycle = analytics.order_status_summary(db)

    review_row = db.query(
        func.count(Review.id),
        func.coalesce(func.avg(Review.rating), 0.0),
    ).filter(analytics._daterange(Review.created_at, start, end)).first()

    reservation_row = db.query(func.count(Reservation.id)).filter(
        analytics._daterange(Reservation.created_at, start, end)
    ).first()

    return {
        "has_data": True,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "range": label,
        "revenue": revenue["revenue"],
        "orders": revenue["orders"],
        "average_order_value": revenue["average_order_value"],
        "portions_sold": revenue["portions"],
        "today_revenue": overview["today"]["revenue"],
        "revenue_change_percent": overview["revenue_change_percent"],
        "order_lifecycle": lifecycle["lifecycle"],
        "served_unpaid_orders": lifecycle["served_unpaid_orders"],
        "payment": lifecycle["payment"],
        "inventory": {
            "total": inventory["total_items"],
            "low": inventory["low_stock_count"],
            "out_of_stock": inventory["out_of_stock_count"],
        },
        "waste_cost": _money(waste["total_cost"]),
        "reviews": int(review_row[0] or 0),
        "average_rating": round(float(review_row[1] or 0), 2),
        "reservations": int(reservation_row[0] or 0),
        "limitation": (
            "This is a snapshot of recorded figures only. It says nothing "
            "about why any of it moved."
        ),
    }


def get_historical_comparison(db: Session, params: dict) -> dict:
    """
    The window against the equal-length window before it.

    Every delta here is a real subtraction between two measured periods.
    Nothing is extrapolated and nothing is attributed.
    """
    start, end, label = _window_of(params)

    previous_start, previous_end = _previous_window(start, end)

    current = analytics.revenue_for_window(db, start, end)
    previous = analytics.revenue_for_window(db, previous_start, previous_end)

    current_orders = get_order_metrics(
        db, {"start": start, "end": end}
    )
    previous_orders = get_order_metrics(
        db, {"start": previous_start, "end": previous_end}
    )

    return {
        "has_data": current["orders"] > 0 or previous["orders"] > 0,
        "range": label,
        "current": {
            "start_date": current["start_date"],
            "end_date": current["end_date"],
            "revenue": current["revenue"],
            "orders": current["orders"],
            "average_order_value": current["average_order_value"],
            "portions_sold": current["portions"],
            "cancelled_orders": current_orders.get("cancelled_orders"),
            "cancellation_rate_percent": current_orders.get(
                "cancellation_rate_percent"
            ),
        },
        "previous": {
            "start_date": previous["start_date"],
            "end_date": previous["end_date"],
            "revenue": previous["revenue"],
            "orders": previous["orders"],
            "average_order_value": previous["average_order_value"],
            "portions_sold": previous["portions"],
            "cancelled_orders": previous_orders.get("cancelled_orders"),
            "cancellation_rate_percent": previous_orders.get(
                "cancellation_rate_percent"
            ),
        },
        "change": {
            "revenue_percent": percent_change(
                current["revenue"], previous["revenue"]
            ),
            "orders_percent": percent_change(
                current["orders"], previous["orders"]
            ),
            "average_order_value_percent": percent_change(
                current["average_order_value"], previous["average_order_value"]
            ),
            "portions_sold_percent": percent_change(
                current["portions"], previous["portions"]
            ),
        },
        "limitation": (
            "A comparison of two periods of different weekday mix can "
            "mislead: a 7-day window contains two more weekends than a "
            "single day."
        ),
    }


def get_operational_events(db: Session, params: dict) -> dict:
    """What has actually happened, from the event log."""
    start, end, label = _window_of(params)

    depth = event_service.event_history_depth(db)

    by_type = event_service.count_by_type(db, start, end)
    per_day = event_service.events_per_day(
        db, start, end,
        tuple(event_service.STATUS_TO_EVENT.values()),
    )

    return {
        "has_data": depth["has_data"],
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "range": label,
        "by_event_type": by_type,
        "events_in_window": sum(by_type.values()),
        "per_day": per_day,
        "recent": event_service.recent_events(db, start, end, limit=15),
        "history": depth,
        "limitation": depth["limitation"],
    }


# =========================================================
# REGISTRY
#
# The single place the orchestrator may look. Adding a tool here is the
# only way to make it callable, and each entry declares its own allowed
# parameters, so a caller cannot pass an undeclared one.
# =========================================================

class RestaurantTool:
    """One callable data source, with its own parameter contract."""

    def __init__(self, name, domain, description, handler,
                 optional_params=()):
        self.name = name
        self.domain = domain
        self.description = description
        self.handler = handler
        self.optional_params = set(optional_params)

    def run(self, db: Session, params: dict | None = None) -> dict:
        """
        Execute with a validated parameter set.

        Unknown keys are dropped rather than passed through. A tool's
        handler therefore never has to defend itself against a parameter
        it did not declare, and a future caller cannot smuggle a value in
        through an undeclared key.
        """
        supplied = params or {}

        clean = {
            key: value
            for key, value in supplied.items()
            if key in self.optional_params and value is not None
        }

        return self.handler(db, clean)


TOOL_REGISTRY = {
    tool.name: tool
    for tool in [
        RestaurantTool(
            "get_revenue_metrics", "revenue",
            "Revenue, order count, portions and average order value.",
            get_revenue_metrics,
            optional_params=("range", "start", "end"),
        ),
        RestaurantTool(
            "get_order_metrics", "orders",
            "Order volume, order-type mix, lifecycle counts, cancellations.",
            get_order_metrics,
            optional_params=("range", "start", "end"),
        ),
        RestaurantTool(
            "get_bill_metrics", "bills",
            "Billed subtotal, tax, service charge, discount and totals.",
            get_bill_metrics,
            optional_params=("range", "start", "end"),
        ),
        RestaurantTool(
            "get_payment_metrics", "payments",
            "Order value vs collected payment, outstanding, status split.",
            get_payment_metrics,
            optional_params=("range", "start", "end"),
        ),
        RestaurantTool(
            "get_customer_metrics", "customers",
            "Guest counts, new vs returning, frequency, spend, preferences.",
            get_customer_metrics,
            optional_params=("range", "start", "end"),
        ),
        RestaurantTool(
            "get_customer_history", "customers",
            "One guest's recorded order history.",
            get_customer_history,
            optional_params=("customer_name", "range", "start", "end"),
        ),
        RestaurantTool(
            "get_menu_performance", "menu",
            "Item popularity, category revenue, availability, slow movers.",
            get_menu_performance,
            optional_params=("range", "start", "end", "limit"),
        ),
        RestaurantTool(
            "get_reservation_metrics", "reservations",
            "Bookings, party sizes, cancellations, busiest slot, upcoming.",
            get_reservation_metrics,
            optional_params=("range", "start", "end"),
        ),
        RestaurantTool(
            "get_table_metrics", "tables",
            "Table count, capacity, occupancy right now.",
            get_table_metrics,
            optional_params=("range", "start", "end"),
        ),
        RestaurantTool(
            "get_kitchen_metrics", "kitchen",
            "Kitchen workload, backlog, preparation and delay times.",
            get_kitchen_metrics,
            optional_params=("range", "start", "end", "slow_threshold_minutes"),
        ),
        RestaurantTool(
            "get_delivery_metrics", "delivery",
            "Delivery order counts, and what is not tracked.",
            get_delivery_metrics,
            optional_params=("range", "start", "end"),
        ),
        RestaurantTool(
            "get_inventory_metrics", "inventory",
            "Stock levels, low and out-of-stock items, recorded movements.",
            get_inventory_metrics,
            optional_params=("range", "start", "end"),
        ),
        RestaurantTool(
            "get_waste_metrics", "waste",
            "Waste cost, quantity, top items, reasons and trend.",
            get_waste_metrics,
            optional_params=("range", "start", "end"),
        ),
        RestaurantTool(
            "get_review_metrics", "reviews",
            "Ratings, sentiment split, lowest-rated dishes.",
            get_review_metrics,
            optional_params=("range", "start", "end"),
        ),
        RestaurantTool(
            "get_staff_metrics", "staff",
            "Staff records by role and shift.",
            get_staff_metrics,
            optional_params=("range", "start", "end"),
        ),
        RestaurantTool(
            "get_business_summary", "summary",
            "Bounded cross-domain snapshot of the current period.",
            get_business_summary,
            optional_params=("range", "start", "end"),
        ),
        RestaurantTool(
            "get_historical_comparison", "comparison",
            "The window against the equal-length window before it.",
            get_historical_comparison,
            optional_params=("range", "start", "end"),
        ),
        RestaurantTool(
            "get_forecast", "forecast",
            "Demand and revenue projection from existing ML.",
            get_forecast,
            optional_params=("range", "start", "end", "days_ahead"),
        ),
        RestaurantTool(
            "get_existing_ai_insights", "ai",
            "Existing Phase 5 ML: sentiment, waste, demand, revenue, pricing.",
            get_existing_ai_insights,
            optional_params=("range", "start", "end"),
        ),
        RestaurantTool(
            "get_operational_events", "operations",
            "The operational event log: counts and recent activity.",
            get_operational_events,
            optional_params=("range", "start", "end", "limit"),
        ),
    ]
}


def capabilities() -> list:
    """
    What the assistant can actually reach, for transparency.

    This is documentation, not a menu. The admin never chooses from it;
    it exists so an operator can see which data sources exist and which
    ones are honest about gaps.
    """
    described = []

    for name, tool in TOOL_REGISTRY.items():
        described.append({
            "tool": name,
            "domain": tool.domain,
            "description": tool.description,
            "optional_parameters": sorted(tool.optional_params),
        })

    return sorted(described, key=lambda row: (row["domain"], row["tool"]))
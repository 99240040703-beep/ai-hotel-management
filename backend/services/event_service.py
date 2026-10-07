"""
Operational event history (Phase 6C).

--------------------------------------------------------------------------
WHAT THIS RECORDS AND WHY
--------------------------------------------------------------------------
Every table in this project stores *current state*. An order row says the
order is `Served`; it does not say when the kitchen started it, how long it
waited, or whether it was ever cancelled. `inventory` holds a quantity and
nothing about what changed it.

That gap is why four ordinary management questions have no answer at all:

    * how long does preparation actually take?
    * how often are orders cancelled, and at which stage?
    * what has been restocked this week, and by whom?
    * what happened yesterday, hour by hour?

This module writes the missing facts as they happen, and reads them back
in aggregate for the AI assistant.

--------------------------------------------------------------------------
ONE TABLE, NOT SEVERAL
--------------------------------------------------------------------------
`restaurant_events` holds everything, distinguished by `entity_type`.
Order transitions, reservations, inventory movements, waste, reviews and
payment outcomes all land here. Separate event tables per subsystem would
be several copies of one mechanism, and any question spanning two of them
would need a union that does not exist.

--------------------------------------------------------------------------
IT NEVER RECORDS A SECRET
--------------------------------------------------------------------------
`metadata` is free-form, so this is the one place where a careless caller
could write a password hash or a token into a table an admin AI reads
freely. `sanitise_metadata` is therefore applied to every write: it drops
any key that looks like a credential, and it coerces the payload to plain
JSON types so a non-serialisable object cannot reach the column.
"""

from datetime import date, datetime, timedelta

from sqlalchemy import func, literal_column
from sqlalchemy.orm import Session

from models import RestaurantEvent

# TIMESTAMPDIFF's unit is a bare keyword, not a bind parameter, so it has
# to be injected as a literal rather than as a bound value.
_MINUTE = literal_column("MINUTE")


# Event names, kept as constants so a typo becomes an import error rather
# than a silently unreadable row.
ORDER_PLACED = "ORDER_PLACED"
ORDER_CONFIRMED = "ORDER_CONFIRMED"
ORDER_PREPARING = "ORDER_PREPARING"
ORDER_READY = "ORDER_READY"
ORDER_SERVED = "ORDER_SERVED"
ORDER_CANCELLED = "ORDER_CANCELLED"

PAYMENT_CREATED = "PAYMENT_CREATED"
PAYMENT_FAILED = "PAYMENT_FAILED"

# Phase 6D. A payment request is not a payment, so it gets its own name.
# Keeping PAYMENT_REQUESTED distinct from the success name is what makes
# "how many bills were asked for but never paid" answerable.
PAYMENT_REQUESTED = "PAYMENT_REQUESTED"
PAYMENT_VERIFICATION_STARTED = "PAYMENT_VERIFICATION_STARTED"
PAYMENT_CANCELLED = "PAYMENT_CANCELLED"

# The confirmed-payment event. Named PAYMENT_SUCCEEDED because that is
# what a settled attempt is, and because "SUCCESS" reads like a status
# rather than something that happened.
PAYMENT_SUCCEEDED = "PAYMENT_SUCCEEDED"

# Phase 6C's name for the same fact, kept so the earlier
# `record_payment_status` helper still resolves. It is never written by
# the Phase 6D ledger; see payment_service, which uses PAYMENT_SUCCEEDED.
PAYMENT_SUCCESS = PAYMENT_SUCCEEDED

RESERVATION_CREATED = "RESERVATION_CREATED"
RESERVATION_CANCELLED = "RESERVATION_CANCELLED"

DELIVERY_STARTED = "DELIVERY_STARTED"
DELIVERY_COMPLETED = "DELIVERY_COMPLETED"

INVENTORY_UPDATED = "INVENTORY_UPDATED"
WASTE_RECORDED = "WASTE_RECORDED"
REVIEW_CREATED = "REVIEW_CREATED"

ENTITY_ORDER = "order"
ENTITY_RESERVATION = "reservation"
ENTITY_INVENTORY = "inventory"
ENTITY_WASTE = "waste"
ENTITY_REVIEW = "review"
ENTITY_PAYMENT = "payment"

# The transition a lifecycle status maps to. The kitchen ticket keeps its
# own status, so the two are reconciled by this table rather than by
# overwriting either.
STATUS_TO_EVENT = {
    "Placed": ORDER_PLACED,
    "Confirmed": ORDER_CONFIRMED,
    "Preparing": ORDER_PREPARING,
    "Ready": ORDER_READY,
    "Served": ORDER_SERVED,
    "Cancelled": ORDER_CANCELLED,
}

# Stages that mean the guest is still waiting.
ACTIVE_EVENT_TYPES = (
    ORDER_PLACED,
    ORDER_CONFIRMED,
    ORDER_PREPARING,
    ORDER_READY,
)

# Any key that would leak a credential if it were written to a table the
# assistant reads. Compared case-insensitively as a substring so
# "password_hash" and "apiKey" are both caught.
_FORBIDDEN_KEY_PARTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "private_key",
    "salt",
    "hash",
    "jwt",
    "signature",
)

MAX_EVENTS_PER_WINDOW = 5000


def sanitise_metadata(payload: dict | None) -> dict:
    """
    Strip anything credential-shaped out of an event payload.

    An event log is read by the admin assistant and is therefore part of
    the assistant's output surface. Writing a secret here would put that
    secret one question away from being printed in an answer, so the
    guard sits here rather than trusting every caller.

    Also coerces values to plain JSON scalars. A datetime or a SQLAlchemy
    object would otherwise raise at flush time, inside somebody else's
    transaction, long after the mistake was made.
    """
    if not payload:
        return {}

    clean = {}

    for key, value in payload.items():
        name = str(key)
        lowered = name.lower()

        if any(part in lowered for part in _FORBIDDEN_KEY_PARTS):
            continue

        if isinstance(value, (int, float, bool)) or value is None:
            clean[name] = value
        elif isinstance(value, (datetime, date)):
            clean[name] = value.isoformat()
        elif isinstance(value, str):
            clean[name] = value[:500]
        else:
            clean[name] = str(value)[:500]

    return clean


def record_event(
    db: Session,
    event_type: str,
    entity_type: str,
    entity_id: int | None = None,
    actor_user_id: int | None = None,
    metadata: dict | None = None,
) -> RestaurantEvent | None:
    """
    Append one event. Never raises into the caller's transaction.

    A history write must not be able to fail an order. If the log cannot
    be written the business operation still stands - losing one history
    row is recoverable, losing a customer's order is not - so the error is
    swallowed and the caller is not interrupted.
    """
    try:
        event = RestaurantEvent(
            event_type=str(event_type)[:50],
            entity_type=str(entity_type)[:30],
            entity_id=entity_id,
            actor_user_id=actor_user_id,
            metadata_json=sanitise_metadata(metadata),
            created_at=datetime.utcnow(),
        )

        db.add(event)
        db.flush()

        return event
    except Exception:
        # Roll the session back to a usable state, then give up on this
        # one row without disturbing whatever the caller was doing.
        try:
            db.rollback()
        except Exception:
            pass

        return None


def record_order_status(
    db: Session,
    header,
    previous_status: str,
    new_status: str,
    actor_user_id: int | None = None,
) -> None:
    """Record a lifecycle transition for an order header."""
    now = datetime.utcnow()

    # The three lifecycle stamps move with the transition. They are written
    # from a real observation, never inferred from an older column.
    try:
        header.status_changed_at = now

        if new_status == "Served":
            header.completed_at = now
    except Exception:
        pass

    event_type = STATUS_TO_EVENT.get(new_status)

    if not event_type:
        return

    payload = {
        "from_status": previous_status,
        "to_status": new_status,
        "reference": getattr(header, "reference", None),
        "order_type": getattr(header, "order_type", None),
        "total_amount": (
            round(float(header.total_amount), 2)
            if getattr(header, "total_amount", None) is not None
            else None
        ),
        "currency": getattr(header, "currency", None),
    }

    if getattr(header, "order_type", None) == "delivery":
        # Deliberately no DELIVERY_* event here.
        #
        # This project has no delivery lifecycle, so an order reaching
        # Served is evidence about the *food*, not about delivery. Writing
        # a delivery event would invent a delivery state the database
        # never observed, and the assistant would then be able to quote
        # delivery completions that did not happen.
        pass

    record_event(
        db,
        event_type,
        ENTITY_ORDER,
        entity_id=header.id,
        actor_user_id=actor_user_id,
        metadata=payload,
    )


def record_payment_status(
    db: Session,
    header,
    previous_payment_status: str,
    new_payment_status: str,
    actor_user_id: int | None = None,
) -> None:
    """
    Record a payment status change.

    Food lifecycle and payment lifecycle stay independent. A Served order
    does not generate a payment event, and no code path here sets `paid`
    without a caller that represents a real payment outcome.
    """
    event_type = {
        "pending": PAYMENT_CREATED,
        "paid": PAYMENT_SUCCESS,
        "failed": PAYMENT_FAILED,
    }.get(str(new_payment_status or "").lower())

    if not event_type:
        return

    now = datetime.utcnow()

    if str(new_payment_status or "").lower() == "paid":
        try:
            header.paid_at = now
        except Exception:
            pass

    record_event(
        db,
        event_type,
        ENTITY_PAYMENT,
        entity_id=header.id,
        actor_user_id=actor_user_id,
        metadata={
            "from_status": previous_payment_status,
            "to_status": new_payment_status,
            "reference": getattr(header, "reference", None),
            "amount": (
                round(float(header.total_amount), 2)
                if getattr(header, "total_amount", None) is not None
                else None
            ),
            "currency": getattr(header, "currency", None),
        },
    )


# =========================================================
# READ SIDE
#
# Aggregates only. Nothing here loads the table into Python, so the cost
# of an assistant question does not grow with the length of history.
# =========================================================

def _window(start: date, end: date):
    return func.date(RestaurantEvent.created_at).between(
        start.isoformat(), end.isoformat()
    )


def count_by_type(db: Session, start: date, end: date,
                  event_types: tuple | None = None) -> dict:
    """How many of each event type occurred in the window."""
    query = db.query(
        RestaurantEvent.event_type,
        func.count(RestaurantEvent.id),
    ).filter(_window(start, end))

    if event_types:
        query = query.filter(RestaurantEvent.event_type.in_(event_types))

    return {row[0]: int(row[1]) for row in query.group_by(
        RestaurantEvent.event_type
    )}


def distinct_orders_with_event(db: Session, start: date, end: date,
                               event_type: str) -> int:
    """How many distinct orders reached a given stage in the window."""
    return int(
        db.query(func.count(func.distinct(RestaurantEvent.entity_id)))
        .filter(
            _window(start, end),
            RestaurantEvent.event_type == event_type,
            RestaurantEvent.entity_type == ENTITY_ORDER,
        )
        .scalar()
        or 0
    )


def average_transition_minutes(db: Session, start: date, end: date,
                               from_event: str, to_event: str) -> tuple:
    """
    Mean minutes between two stages, over orders that have both.

    Implemented in SQL as a self-join on entity_id rather than by loading
    rows into Python. Orders missing either stage are simply absent from
    the average; the count of how many contributed is returned so the
    caller can say whether the figure rests on one order or five hundred.
    """
    earlier = (
        db.query(
            RestaurantEvent.entity_id.label("entity_id"),
            func.min(RestaurantEvent.created_at).label("t_from"),
        )
        .filter(
            _window(start, end),
            RestaurantEvent.event_type == from_event,
            RestaurantEvent.entity_type == ENTITY_ORDER,
        )
        .group_by(RestaurantEvent.entity_id)
        .subquery()
    )

    later = (
        db.query(
            RestaurantEvent.entity_id.label("entity_id"),
            func.min(RestaurantEvent.created_at).label("t_to"),
        )
        .filter(
            _window(start, end),
            RestaurantEvent.event_type == to_event,
            RestaurantEvent.entity_type == ENTITY_ORDER,
        )
        .group_by(RestaurantEvent.entity_id)
        .subquery()
    )

    rows = (
        db.query(
            func.count(later.c.entity_id),
            func.avg(
                func.timestampdiff(_MINUTE, earlier.c.t_from, later.c.t_to)
            ),
            func.max(
                func.timestampdiff(_MINUTE, earlier.c.t_from, later.c.t_to)
            ),
        )
        .select_from(earlier)
        .join(later, later.c.entity_id == earlier.c.entity_id)
        .filter(later.c.t_to >= earlier.c.t_from)
        .all()
    )

    if not rows:
        return (0, None, None)

    count = int(rows[0][0] or 0)

    if not count:
        return (0, None, None)

    return (
        count,
        round(float(rows[0][1]), 1),
        int(rows[0][2] or 0),
    )


def slow_orders(db: Session, start: date, end: date, threshold_minutes: int,
                limit: int = 5) -> list:
    """
    Orders whose placed→served time exceeded a threshold.

    The threshold is a parameter of the caller's question, never a
    constant buried here, so "orders taking over 45 minutes" is answerable
    without editing this module.
    """
    placed = (
        db.query(
            RestaurantEvent.entity_id.label("entity_id"),
            func.min(RestaurantEvent.created_at).label("t_placed"),
        )
        .filter(
            _window(start, end),
            RestaurantEvent.event_type == ORDER_PLACED,
            RestaurantEvent.entity_type == ENTITY_ORDER,
        )
        .group_by(RestaurantEvent.entity_id)
        .subquery()
    )

    served = (
        db.query(
            RestaurantEvent.entity_id.label("entity_id"),
            func.min(RestaurantEvent.created_at).label("t_served"),
        )
        .filter(
            _window(start, end),
            RestaurantEvent.event_type == ORDER_SERVED,
            RestaurantEvent.entity_type == ENTITY_ORDER,
        )
        .group_by(RestaurantEvent.entity_id)
        .subquery()
    )

    minutes = func.timestampdiff(_MINUTE, placed.c.t_placed, served.c.t_served)

    rows = (
        db.query(
            placed.c.entity_id,
            minutes.label("minutes"),
        )
        .select_from(placed)
        .join(served, served.c.entity_id == placed.c.entity_id)
        .filter(minutes >= threshold_minutes)
        .order_by(minutes.desc())
        .limit(max(1, min(int(limit or 5), 25)))
        .all()
    )

    return [
        {"order_line_id": int(row[0]), "minutes_to_serve": int(row[1] or 0)}
        for row in rows
    ]


def recent_events(db: Session, start: date, end: date, limit: int = 20) -> list:
    """
    The most recent events in the window, newest first.

    Bounded on both the row count and the window length so a question can
    never turn into a table scan of the whole log.
    """
    capped = min(int(limit or 20), 100)

    rows = (
        db.query(
            RestaurantEvent.event_type,
            RestaurantEvent.entity_type,
            RestaurantEvent.entity_id,
            RestaurantEvent.created_at,
        )
        .filter(_window(start, end))
        .order_by(RestaurantEvent.created_at.desc(), RestaurantEvent.id.desc())
        .limit(capped)
        .all()
    )

    return [
        {
            "event_type": row[0],
            "entity_type": row[1],
            "entity_id": row[2],
            "at": row[3].isoformat(timespec="seconds") if row[3] else None,
        }
        for row in rows
    ]


def event_history_depth(db: Session) -> dict:
    """
    How much history actually exists.

    The assistant calls this before quoting a duration, a delay or a
    cancellation rate. If recording only started recently, the honest
    answer is "the log starts on <date>", not a figure averaged over two
    days and presented as a trend.
    """
    total = int(
        db.query(func.count(RestaurantEvent.id)).scalar() or 0
    )

    if not total:
        return {
            "has_data": False,
            "event_count": 0,
            "first_event_at": None,
            "last_event_at": None,
            "limitation": (
                "No operational events have been recorded yet, so "
                "durations, delays and cancellation rates cannot be "
                "computed. The event log starts when recording starts."
            ),
        }

    bounds = (
        db.query(
            func.min(RestaurantEvent.created_at),
            func.max(RestaurantEvent.created_at),
        ).first()
    )

    first_at, last_at = bounds[0], bounds[1]

    depth_days = (
        (last_at - first_at).days if first_at and last_at else 0
    )

    return {
        "has_data": True,
        "event_count": total,
        "first_event_at": first_at.isoformat(timespec="seconds")
        if first_at else None,
        "last_event_at": last_at.isoformat(timespec="seconds")
        if last_at else None,
        "history_depth_days": depth_days,
        "limitation": None,
    }


def inventory_movements(db: Session, start: date, end: date,
                        limit: int = 10) -> list:
    """Recorded stock changes in the window, newest first."""
    rows = (
        db.query(
            RestaurantEvent.entity_id,
            RestaurantEvent.actor_user_id,
            RestaurantEvent.metadata_json,
            RestaurantEvent.created_at,
        )
        .filter(
            _window(start, end),
            RestaurantEvent.event_type == INVENTORY_UPDATED,
        )
        .order_by(RestaurantEvent.created_at.desc(), RestaurantEvent.id.desc())
        .limit(max(1, min(int(limit or 10), 100)))
        .all()
    )

    movements = []

    for row in rows:
        payload = row[2] or {}

        movements.append(
            {
                "inventory_id": row[0],
                "actor_user_id": row[1],
                "item_name": payload.get("item_name"),
                "previous_quantity": payload.get("previous_quantity"),
                "new_quantity": payload.get("new_quantity"),
                "at": row[3].isoformat(timespec="seconds") if row[3] else None,
            }
        )

    return movements


def events_per_day(db: Session, start: date, end: date,
                   event_types: tuple | None = None) -> list:
    """Daily event counts, so a timeline can be charted without a scan."""
    query = db.query(
        func.date(RestaurantEvent.created_at).label("day"),
        func.count(RestaurantEvent.id),
    ).filter(_window(start, end))

    if event_types:
        query = query.filter(RestaurantEvent.event_type.in_(event_types))

    rows = query.group_by(func.date(RestaurantEvent.created_at)).all()

    counts = {str(row[0]): int(row[1]) for row in rows}

    span = (end - start).days

    return [
        {"date": (start + timedelta(days=offset)).isoformat(),
         "count": counts.get((start + timedelta(days=offset)).isoformat(), 0)}
        for offset in range(span + 1)
    ]
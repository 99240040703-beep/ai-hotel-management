"""
Order lifecycle management.

Defines the authoritative order status lifecycle and validates transitions.

Status flow:
    PLACED -> CONFIRMED -> PREPARING -> READY -> SERVED

Payment status is independent and managed separately.
"""

from enum import Enum


class OrderStatus(str, Enum):
    """Authoritative order status values."""

    PLACED = "Placed"
    CONFIRMED = "Confirmed"
    PREPARING = "Preparing"
    READY = "Ready"
    SERVED = "Served"
    CANCELLED = "Cancelled"


class PaymentStatus(str, Enum):
    """Payment status values - independent from food status."""

    UNPAID = "unpaid"
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    REFUNDED = "refunded"


# The single authority on which status may follow which.
#
# Key = current status, Value = set of allowed next statuses. The flow is
# strictly one step at a time and states can never be skipped, for
# everyone: PLACED -> PREPARING, PLACED -> READY and CONFIRMED -> SERVED
# are all rejected. There is deliberately no privileged override table -
# an admin is authorised to *perform* transitions, never to invent a
# shortcut past a state the kitchen has not entered yet.
VALID_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.PLACED: {OrderStatus.CONFIRMED, OrderStatus.CANCELLED},
    OrderStatus.CONFIRMED: {OrderStatus.PREPARING, OrderStatus.CANCELLED},
    OrderStatus.PREPARING: {OrderStatus.READY, OrderStatus.CANCELLED},
    OrderStatus.READY: {OrderStatus.SERVED, OrderStatus.CANCELLED},
    OrderStatus.SERVED: {OrderStatus.CANCELLED},  # Refund scenario
    OrderStatus.CANCELLED: set(),  # Terminal state
}

# Statuses that are considered "active" (customer waiting for food)
ACTIVE_STATUSES = {
    OrderStatus.PLACED,
    OrderStatus.CONFIRMED,
    OrderStatus.PREPARING,
    OrderStatus.READY,
}

# Statuses where customer can cancel
CANCELLABLE_BY_CUSTOMER = {
    OrderStatus.PLACED,
    OrderStatus.CONFIRMED,
}

# Status display order for UI
STATUS_DISPLAY_ORDER = [
    OrderStatus.PLACED,
    OrderStatus.CONFIRMED,
    OrderStatus.PREPARING,
    OrderStatus.READY,
    OrderStatus.SERVED,
    OrderStatus.CANCELLED,
]

# Human-readable messages for each status
STATUS_MESSAGES = {
    OrderStatus.PLACED: "Your order has been placed and is awaiting confirmation.",
    OrderStatus.CONFIRMED: "Restaurant confirmed your order. Kitchen will start shortly.",
    OrderStatus.PREPARING: "Your food is being prepared.",
    OrderStatus.READY: "Your order is ready. Server is delivering to your table.",
    OrderStatus.SERVED: "Enjoy your meal!",
    OrderStatus.CANCELLED: "This order has been cancelled.",
}

# Payment status display messages
PAYMENT_STATUS_MESSAGES = {
    PaymentStatus.UNPAID: "Payment pending",
    PaymentStatus.PENDING: "Payment being processed",
    PaymentStatus.PAID: "Paid",
    PaymentStatus.FAILED: "Payment failed",
    PaymentStatus.REFUNDED: "Refunded",
}


def validate_transition(
    current: str,
    target: str,
    is_admin: bool = False,
) -> tuple[bool, str | None]:
    """
    Validate if a status transition is allowed.

    `is_admin` is accepted so existing call sites keep working, but it
    deliberately has no effect on which transitions are legal. The
    lifecycle is identical for staff and for guests.

    Returns (is_valid, error_message).
    """
    try:
        current_status = OrderStatus(current)
        target_status = OrderStatus(target)
    except ValueError:
        return False, f"Invalid status value: {current} -> {target}"

    # Same status is always allowed (idempotent)
    if current_status == target_status:
        return True, None

    allowed = VALID_TRANSITIONS

    if target_status not in allowed.get(current_status, set()):
        allowed_list = ", ".join(
            s.value for s in STATUS_DISPLAY_ORDER
            if s in allowed.get(current_status, set())
        )
        return False, (
            f"Invalid transition from {current_status.value} to {target_status.value}. "
            f"Allowed: {allowed_list or 'none'}"
        )

    return True, None


def get_next_statuses(current: str, is_admin: bool = False) -> list[str]:
    """
    List the statuses that may legally follow `current`.

    Returned in lifecycle display order so the API response is stable
    between calls. As with validate_transition, `is_admin` does not widen
    the result.
    """
    try:
        current_status = OrderStatus(current)
    except ValueError:
        return []

    allowed = VALID_TRANSITIONS.get(current_status, set())

    return [
        status.value
        for status in STATUS_DISPLAY_ORDER
        if status in allowed
    ]


def is_active_status(status: str) -> bool:
    """Check if status represents an active order (customer waiting)."""
    try:
        return OrderStatus(status) in ACTIVE_STATUSES
    except ValueError:
        return False


def is_cancellable_by_customer(status: str) -> bool:
    """Check if customer can cancel at this status."""
    try:
        return OrderStatus(status) in CANCELLABLE_BY_CUSTOMER
    except ValueError:
        return False


def get_status_message(status: str) -> str:
    """Get human-readable message for status."""
    try:
        return STATUS_MESSAGES[OrderStatus(status)]
    except (ValueError, KeyError):
        return ""


def get_payment_status_message(status: str) -> str:
    """Get human-readable message for payment status."""
    try:
        return PAYMENT_STATUS_MESSAGES[PaymentStatus(status)]
    except (ValueError, KeyError):
        return ""
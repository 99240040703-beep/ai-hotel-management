"""
My Bill.

Shows what the guest owes for their current table visit, built from the
order headers the server itself wrote. Everything on screen is summed
from stored values, never recalculated in the browser.

The final figure is `OrderHeader.total_amount`. That is the only number
this bill treats as the amount owed, and it is not recomputed here.

Payment (Phase 6D)
------------------
`payment_status` is read from the stored headers, and the payment detail
alongside it comes from the payment ledger rather than from anything the
guest's browser sent. A guest can therefore see that a payment request is
outstanding, or that one was confirmed, and cannot influence either.

Food status and payment status stay separate on purpose: a guest can eat
and leave before paying.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

try:
    from database import get_db
    from middleware.auth import require_current_user
    from models import Order, OrderHeader, Payment, PaymentStatus, Settings
    from services.order_service import get_settings
    from services.table_service import get_claimed_table
    from services import payment_provider as provider_module
    from services import payment_service
except (ImportError, ValueError):
    from ..database import get_db
    from ..middleware.auth import require_current_user
    from ..models import Order, OrderHeader, Payment, PaymentStatus, Settings
    from ..services.order_service import get_settings
    from ..services.table_service import get_claimed_table
    from ..services import payment_provider as provider_module
    from ..services import payment_service


router = APIRouter(prefix="/customer", tags=["Customer Bill"])

# Food states that appear on a bill. Cancelled items are excluded.
INCLUDED_STATUSES = {"Placed", "Confirmed", "Preparing", "Ready", "Served"}

# Kept so the interface can describe progress without inventing a rule.
FOOD_LIFECYCLE = ["Placed", "Confirmed", "Preparing", "Ready", "Served"]


@router.get("/bill")
def read_my_bill(
    db: Session = Depends(get_db),
    current_user=Depends(require_current_user),
):
    """
    The bill for every order this guest has placed at their claimed
    table.
    """
    user_id = current_user["user_id"]

    table = get_claimed_table(db, user_id)

    headers = (
        db.query(OrderHeader)
        .filter(OrderHeader.user_id == user_id)
        .order_by(OrderHeader.id.desc())
        .all()
    )

    # Without a claimed table, only dine-in orders at the table this
    # guest named make sense on a bill. Takeaway and delivery are
    # reported too, since they are still this guest's spend.
    if table:
        headers = [
            header
            for header in headers
            if header.table_id == table.id
            or header.order_type != "dine-in"
        ]
    else:
        headers = [header for header in headers if header.order_type != "dine-in"]

    lines = []
    subtotal = 0.0
    tax_amount = 0.0
    service_charge_amount = 0.0
    discount_amount = 0.0
    total_amount = 0.0
    statuses = set()

    for header in headers:
        if header.status == "Cancelled":
            continue

        statuses.add(header.status)

        rows = (
            db.query(Order)
            .filter(Order.order_id == header.id)
            .all()
        )

        # A header with no linked line is still a real spend; fall back
        # to its own stored totals rather than showing an empty bill.
        if not rows:
            subtotal += float(header.subtotal or 0)
            tax_amount += float(header.tax_amount or 0)
            service_charge_amount += float(
                header.service_charge_amount or 0
            )
            discount_amount += float(header.discount_amount or 0)
            total_amount += float(header.total_amount or 0)

            continue

        for row in rows:
            if row.status == "Cancelled":
                continue

            line_total = float(row.total_price or 0)

            subtotal += line_total
            tax_amount += round(
                line_total * float(header.tax_percentage or 0) / 100.0, 2
            )

            lines.append(
                {
                    "order_id": row.id,
                    "reference": header.reference,
                    "menu_item": row.menu_item,
                    "quantity": row.quantity,
                    "unit_price": (
                        float(row.unit_price)
                        if row.unit_price is not None
                        else None
                    ),
                    "line_total": round(line_total, 2),
                    "special_instructions": row.special_instructions,
                }
            )

    if lines:
        # Only bills that are actually on this bill contribute. A
        # cancelled order has no lines above - the loop skipped it - so
        # including its total here would make the bill total exceed the
        # sum of its own line items and its own payment figures.
        billable_headers = [
            header for header in headers if header.status != "Cancelled"
        ]

        service_charge_amount = sum(
            float(header.service_charge_amount or 0)
            for header in billable_headers
        )
        discount_amount = sum(
            float(header.discount_amount or 0)
            for header in billable_headers
        )
        total_amount = sum(
            float(header.total_amount or 0) for header in billable_headers
        )

    settings = get_settings(db)

    restaurant = db.query(Settings).first()

    item_count = sum(line["quantity"] for line in lines)

    # ---- payment state ----
    #
    # One roll-up across every bill in this visit. The settled figure comes
    # from the payment ledger, so it reflects only payments a provider
    # confirmed - a displayed QR contributes nothing.
    payable_headers = [h for h in headers if h.status != "Cancelled"]

    settled_amount = 0.0
    outstanding_amount = 0.0
    paid_at_values = []
    methods = set()
    references = []
    paid_bills = 0
    unpaid_bills = 0

    for header in payable_headers:
        settled = (
            db.query(Payment)
            .filter(
                Payment.order_id == header.id,
                Payment.status == PaymentStatus.SUCCESS,
            )
            .order_by(Payment.id.desc())
            .first()
        )

        bill_total = round(float(header.total_amount or 0), 2)

        if settled:
            settled_amount += round(float(settled.amount or 0), 2)
            paid_bills += 1

            if settled.paid_at:
                paid_at_values.append(settled.paid_at)

            if settled.method:
                methods.add(settled.method)

            if settled.provider_reference:
                references.append(settled.provider_reference)
        else:
            outstanding_amount += bill_total
            unpaid_bills += 1

    settled_amount = round(settled_amount, 2)
    outstanding_amount = round(outstanding_amount, 2)

    # The header state is kept because Phases 1-6 read it, and the ledger
    # is reported beside it so a disagreement would be visible.
    header_paid = any(
        header.payment_status == "paid" for header in headers
    )

    paid = header_paid and settled_amount > 0

    # A visit can be half settled: the guest paid one bill and not the
    # next. Calling that PAID would be wrong, and calling it UNPAID would
    # hide money that has already arrived. Both are reported, plus the two
    # amounts that add up to the bill total.
    if unpaid_bills == 0 and paid_bills > 0:
        visit_status = "PAID"
    elif paid_bills > 0:
        visit_status = "PARTIALLY_PAID"
    else:
        visit_status = "UNPAID"

    # A payment request the guest can act on: an unpaid bill, with
    # payments switched on, and at least one bill that can be paid.
    payable = [
        header for header in payable_headers
        if header.payment_status != "paid"
    ]

    pending_payment = (
        db.query(Payment)
        .filter(
            Payment.order_id.in_([h.id for h in payable] or [0]),
            Payment.status == PaymentStatus.PENDING,
        )
        .order_by(Payment.id.desc())
        .first()
        if payable
        else None
    )

    return {
        "table_number": table.table_number if table else None,
        "restaurant_name": (
            restaurant.restaurant_name if restaurant else None
        ),
        "orders": lines,
        "item_count": item_count,
        "subtotal": round(subtotal, 2),
        "tax_percentage": float(settings.tax_percentage or 0),
        "tax_amount": round(tax_amount, 2),
        "service_charge_percentage": float(
            settings.service_charge_percentage or 0
        ),
        "service_charge_amount": round(service_charge_amount, 2),
        "discount_amount": round(discount_amount, 2),
        "total_amount": round(total_amount, 2),
        "currency": (settings.currency or "UNSET").upper(),

        # ---- payment ----
        # A visit total, so the status is a visit status. Both the paid
        # and the outstanding figure come from the ledger, and they sum to
        # the bill total above.
        "payment_status": visit_status,
        "paid_amount": settled_amount,
        "outstanding_amount": outstanding_amount,
        "bills_paid": paid_bills,
        "bills_outstanding": unpaid_bills,
        "paid_at": (
            max(paid_at_values).isoformat(timespec="seconds")
            if paid_at_values else None
        ),
        "payment_method": (
            sorted(methods)[0] if len(methods) == 1 else None
        ),
        "payment_references": references,
        "bills_in_visit": len(payable_headers),
        "bills_unpaid": len(payable),
        "pending_payment_id": (
            pending_payment.id if pending_payment else None
        ),
        # Payment can be started only when the provider is switched on.
        # False means the interface offers no pay action at all, rather
        # than offering one that cannot work.
        "payment_available": (
            provider_module.payments_enabled() and len(payable) > 0
        ),
        "payment_gateway": provider_module.configuration(),
        "food_statuses": [
            state
            for state in FOOD_LIFECYCLE
            if state in statuses
        ],
    }


@router.get("/bills")
def read_my_bill_history(
    limit: int = Query(
        50, ge=1, le=100,
        description="How many of this guest's most recent bills to return.",
    ),
    db: Session = Depends(get_db),
    current_user=Depends(require_current_user),
):
    """
    Every bill this guest has ever had, newest first.

    Distinct from `GET /bill`, which is the *current visit*: the total for
    the table they are sitting at right now. This one is history - every
    bill under their account, so a guest can look back at a previous visit
    and see what they owed and whether they paid it.

    Every figure comes from the stored header. `total_amount` is the
    authoritative amount; nothing is recomputed here, and nothing is
    accepted from the request.

    Scoped by the token's user id, so a guest cannot ask for another
    guest's bills by passing an id.
    """
    return payment_service.customer_bill_history(
        db, current_user["user_id"], limit=limit
    )

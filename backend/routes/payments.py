"""
Payment endpoints.

--------------------------------------------------------------------------
AUTHORIZATION
--------------------------------------------------------------------------
Every route here is authenticated, and the simulated-provider routes are
admin-only on top of that.

    anonymous            401
    customer             own bills only
    another customer     403 - never even told the payment exists
    admin                any bill

Authorization is a route dependency, so it cannot be skipped by a client
that simply declines to send the check.

--------------------------------------------------------------------------
WHAT THE CLIENT MAY SEND
--------------------------------------------------------------------------
`POST /api/payments/request` accepts exactly two fields:

    {"order_id": 12, "method": "UPI"}

It does not accept `amount`, `total_amount`, `currency`, `customer_name`,
`provider_reference` or `status`. Those are not "validated then ignored" -
they are absent from the schema, so a request containing one is a 422
rather than a silently-trusted number that happened to be dropped. The
amount comes from `OrderHeader.total_amount` and nothing else.

`POST /api/payments/{id}/verify` accepts an empty body. It takes no
outcome, because the client has no standing to declare one.

--------------------------------------------------------------------------
THE DEVELOPMENT ROUTES
--------------------------------------------------------------------------
`/api/payments/dev/...` exists only while PAYMENT_MODE=development, and
returns 404 otherwise - 404 rather than 403 so that in production the
endpoint is not even discoverable.

Those routes do not write to the database. They publish an outcome on the
development provider, and the ordinary verification path then reads it.
There is deliberately no `POST /mark-paid`.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from datetime import date, datetime
from typing import Optional

try:
    from database import get_db
    from middleware.auth import require_current_user, require_admin
    from models import (
        OrderHeader,
        Payment,
        PaymentMethod,
        PaymentStatus,
        PaymentWebhookEvent,
        WebhookProcessResult,
    )
    from services import event_service
    from services import payment_provider as provider_module
    from services import razorpay_provider
    from services import payment_service
    from services.payment_service import PaymentError
except (ImportError, ValueError):
    from ..database import get_db
    from ..middleware.auth import require_current_user, require_admin
    from ..models import (
        OrderHeader,
        Payment,
        PaymentMethod,
        PaymentStatus,
        PaymentWebhookEvent,
        WebhookProcessResult,
    )
    from ..services import event_service
    from ..services import payment_provider as provider_module
    from ..services import razorpay_provider
    from ..services import payment_service
    from ..services.payment_service import PaymentError


router = APIRouter(prefix="/payments", tags=["Payments"])

# Declared before the schemas that reference them.
PaymentStatus_SUCCESS = "SUCCESS"
PaymentStatus_FAILED = "FAILED"
VALID_SIMULATIONS = (PaymentStatus_SUCCESS, PaymentStatus_FAILED)

# The settlement states a bill can be reported in. Derived from the ledger,
# never from a stored column.
BILL_STATES = ("PAID", "PARTIALLY_PAID", "UNPAID")

# Ranges the history endpoints understand. A caller can only pick one of
# these names - there is no way to supply a column, an operator or an
# expression.
HISTORY_RANGES = (
    "today", "yesterday", "last_7_days", "last_14_days", "last_30_days",
    "last_90_days", "this_month", "previous_month", "this_quarter",
    "last_quarter", "this_year", "all_time",
)

ORDER_STATUS_FILTERS = (
    "Placed", "Confirmed", "Preparing", "Ready", "Served", "Cancelled",
)

PAYMENT_STATUS_FILTERS = (
    "PENDING", "SUCCESS", "FAILED", "CANCELLED",
)


class PaymentRequestIn(BaseModel):
    """
    A request to pay one bill.

    `extra="forbid"` is the important part. A client that tries to send an
    amount is refused outright rather than having it quietly discarded -
    which means a UI bug that starts sending one fails loudly during
    development instead of silently paying the wrong figure.
    """

    order_id: int = Field(
        ..., gt=0, description="The order header to pay."
    )

    method: str = Field(
        default=PaymentMethod.UPI,
        description="UPI or CASH. No card or bank-transfer method exists.",
    )

    model_config = {"extra": "forbid"}


class DevelopmentSimulateIn(BaseModel):
    """
    A simulated provider outcome.

    `provider_reference` is looked up rather than trusted: the provider is
    asked whether it recognises it, and an unknown reference is a 404. A
    caller cannot invent a reference and thereby settle a payment.

    `amount` is deliberately absent. The verification path re-reads the
    bill's authoritative total, so there is nothing here to mismatch
    against - which is the point.
    """

    outcome: str = Field(
        default=PaymentStatus_SUCCESS,
        description="SUCCESS or FAILED.",
    )

    reason: Optional[str] = Field(
        default=None,
        max_length=300,
        description="Optional note recorded against a FAILED outcome.",
    )


class PaymentVerifyIn(BaseModel):
    """
    An empty body, deliberately.

    The client may ask the backend to check. It may not state the answer.
    """

    model_config = {"extra": "forbid"}


def _fail(error: PaymentError) -> HTTPException:
    return HTTPException(
        status_code=error.status_code, detail=error.message
    )


def _may_touch(db: Session, header, current_user) -> bool:
    """
    Whether this caller may act on this bill.

    Admins may act on any bill. A customer may act only on their own, and
    the ownership test uses `user_id` - never a name comparison, which two
    guests sharing a name would defeat.
    """
    if current_user["role"] == "admin":
        return True

    return header.user_id == current_user["user_id"]


def _load_header(db: Session, order_id: int):
    header = db.query(OrderHeader).filter(OrderHeader.id == order_id).first()

    if not header:
        raise HTTPException(status_code=404, detail="Order not found")

    return header


# =========================================================
# HISTORY  (Phase 6E)
#
# Registered before `/{payment_id}` on purpose. FastAPI matches in
# registration order, so a catch-all integer parameter declared first would
# swallow `/mine` and try to parse it as an id.
#
# Two audiences, and the split is the point:
#
#   /mine, /order/{id}      scoped to the authenticated guest
#   /admin/*               the whole restaurant, admin only
#
# Every figure below is read from `order_headers.total_amount` and the
# `payments` ledger. No history endpoint accepts an amount, a status or a
# total from the caller.
# =========================================================

@router.get("/mine")
def my_payment_history(
    limit: int = Query(
        50, ge=1, le=payment_service.MAX_PAGE_SIZE,
        description="How many of this guest's most recent attempts to return.",
    ),
    db: Session = Depends(get_db),
    current_user=Depends(require_current_user),
):
    """
    Every payment attempt this guest has made.

    Scoped by the token's user id, joined through the bill rather than
    trusted from the request. A FAILED and a CANCELLED attempt both remain
    visible: they happened, and hiding them would make a guest's history
    look tidier than the truth.
    """
    return payment_service.customer_payment_history(
        db, current_user["user_id"], limit=limit
    )


@router.get("/admin/bills")
def admin_bill_history(
    request: Request,
    payment_status: Optional[str] = Query(
        None,
        description="PAID, PARTIALLY_PAID or UNPAID. Filtered on the "
                    "ledger-derived state, not on a stored column.",
    ),
    order_status: Optional[str] = Query(
        None, description="A lifecycle status."
    ),
    customer_name: Optional[str] = Query(
        None, max_length=100, description="Exact customer name."
    ),
    order_reference: Optional[str] = Query(
        None, max_length=20, description="Exact order reference.",
    ),
    date_from: Optional[str] = Query(
        None, description="ISO date, inclusive. When the range keyword is "
                          "used this is ignored.",
    ),
    date_to: Optional[str] = Query(
        None, description="ISO date, inclusive."
    ),
    range_key: Optional[str] = Query(
        None, description=f"One of: {', '.join(HISTORY_RANGES)}."
    ),
    page: int = Query(1, ge=1, le=100000, description="1-based page."),
    page_size: int = Query(
        payment_service.DEFAULT_PAGE_SIZE, ge=1,
        le=payment_service.MAX_PAGE_SIZE,
        description="Rows per page, capped server-side.",
    ),
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    """
    Bills with their settlement state, filtered and paginated.

    Totals in `summary` describe the whole filtered set rather than the
    page on screen, so a paginated report still states a true outstanding
    figure instead of one page's worth.

    An unrecognised filter is rejected rather than ignored.
    """
    _reject_unknown_params(request, {
        "payment_status", "order_status", "customer_name",
        "order_reference", "date_from", "date_to", "range_key", "page",
        "page_size",
    })

    window = _window_from(range_key, date_from, date_to)

    filters = _history_filters(
        payment_status, order_status, customer_name, order_reference,
        window,
        BILL_STATES,
        ORDER_STATUS_FILTERS,
    )

    return payment_service.admin_bill_history(
        db, filters, page=page, page_size=page_size
    )


@router.get("/admin/history")
def admin_payment_history(
    request: Request,
    status: Optional[str] = Query(
        None, description="PENDING, SUCCESS, FAILED or CANCELLED."
    ),
    payment_status: Optional[str] = Query(
        None,
        description="An alias for `status`, so both history endpoints take "
                    "the same filter name.",
    ),
    order_status: Optional[str] = Query(
        None, description="A lifecycle status of the bill."
    ),
    customer_name: Optional[str] = Query(
        None, max_length=100, description="Exact customer name."
    ),
    order_reference: Optional[str] = Query(
        None, max_length=20, description="Exact order reference.",
    ),
    date_from: Optional[str] = Query(
        None, description="ISO date, inclusive."
    ),
    date_to: Optional[str] = Query(
        None, description="ISO date, inclusive."
    ),
    range_key: Optional[str] = Query(
        None, description=f"One of: {', '.join(HISTORY_RANGES)}."
    ),
    page: int = Query(1, ge=1, le=100000),
    page_size: int = Query(
        payment_service.DEFAULT_PAGE_SIZE, ge=1,
        le=payment_service.MAX_PAGE_SIZE,
    ),
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    """
    The payment ledger, filtered and paginated.

    Pagination is a SQL LIMIT, so a long ledger is never read in full to
    render one page. `total_matching` is a COUNT for the same reason - it
    would be wrong to report the page size as the history size.

    An unrecognised filter is rejected rather than ignored. Silently
    dropping `?payment_statu=PAID` would hand back the whole ledger while
    the caller believes they have filtered it, which is how an operator
    ends up chasing the wrong unpaid bills.
    """
    _reject_unknown_params(request, {
        "status", "payment_status", "order_status", "customer_name",
        "order_reference", "date_from", "date_to", "range_key", "page",
        "page_size",
    })

    if status and payment_status and status != payment_status:
        raise HTTPException(
            status_code=422,
            detail="status and payment_status disagree; send one",
        )

    effective_status = status or payment_status

    window = _window_from(range_key, date_from, date_to)

    filters = _history_filters(
        effective_status, order_status, customer_name, order_reference,
        window, PAYMENT_STATUS_FILTERS, ORDER_STATUS_FILTERS,
    )

    return payment_service.admin_payment_history(
        db, filters, page=page, page_size=page_size
    )


def _reject_unknown_params(request: Request, allowed: set) -> None:
    """
    Refuse a query parameter this endpoint does not define.

    FastAPI ignores unrecognised query parameters by default. For a
    filtered report that is the wrong default: a mistyped filter name would
    return the entire ledger while the caller believes they have narrowed
    it. Better to say so.
    """
    supplied = set(request.query_params.keys())

    unknown = sorted(supplied - set(allowed))

    if unknown:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unknown filter(s): {', '.join(unknown)}. "
                f"Accepted: {', '.join(sorted(allowed))}"
            ),
        )


@router.get("/admin/summary")
def admin_settlement_summary(
    range_key: str = Query(
        "last_30_days",
        description=f"One of: {', '.join(HISTORY_RANGES)}.",
    ),
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    """
    Billed, collected and outstanding for a period, plus attempt counts.

    The three figures are computed from different places and never merged:
    billed from `OrderHeader.total_amount` for bills raised in the period,
    collected from SUCCESS payments confirmed in it, outstanding as each
    bill's own residual. A bill that was raised in the period and has not
    been paid is outstanding, not revenue collected.
    """
    if range_key not in HISTORY_RANGES:
        raise HTTPException(
            status_code=422,
            detail=f"range must be one of: {', '.join(HISTORY_RANGES)}",
        )

    start, end, label = analytics_resolve_range(range_key)

    summary = payment_service.settlement_summary(db, start, end, label)

    return {
        **summary,
        "gateway": provider_module.configuration(),
        # Restated on the summary so no screen can show an outstanding
        # figure without also showing that no real gateway is attached.
        "gateway_connected": provider_module.configuration()[
            "live_gateway_connected"
        ],
    }


def analytics_resolve_range(range_key: str):
    """Reuse analytics_service's window resolution rather than restating it."""
    from services.analytics_service import resolve_range

    return resolve_range(range_key)


def _window_from(range_key: str, date_from: str | None,
                 date_to: str | None) -> dict:
    """
    Turn the range parameters into a concrete date window.

    A named range wins over a date pair, because a caller sending both has
    asked for a period and a range in one request and the named range is
    the more specific instruction.
    """
    if range_key:
        if range_key not in HISTORY_RANGES:
            raise HTTPException(
                status_code=422,
                detail=f"range_key must be one of: "
                       f"{', '.join(HISTORY_RANGES)}",
            )

        return {"range": range_key}

    if date_from and date_to:
        for value in (date_from, date_to):
            try:
                date.fromisoformat(value)
            except ValueError:
                raise HTTPException(
                    status_code=422,
                    detail=f"Dates must be ISO format, got {value!r}",
                )

        try:
            if date.fromisoformat(date_from) > date.fromisoformat(date_to):
                raise HTTPException(
                    status_code=422,
                    detail="date_from must not be after date_to",
                )
        except ValueError:
            pass

        return {"date_from": date_from, "date_to": date_to}

    if date_from or date_to:
        raise HTTPException(
            status_code=422,
            detail="date_from and date_to must be supplied together",
        )

    return {}


def _history_filters(payment_status, order_status, customer_name,
                     order_reference, window, allowed_payment_states,
                     allowed_order_states) -> dict:
    """
    Build the filter dict from validated query parameters.

    Every value is checked against a closed list before it reaches the
    service, and the service narrows to its own known keys anyway. Two
    independent gates: a caller cannot inject an expression, and a caller
    cannot smuggle a field the service did not expect.
    """
    filters = dict(window)

    if payment_status:
        if payment_status not in allowed_payment_states:
            raise HTTPException(
                status_code=422,
                detail=f"payment status must be one of: "
                       f"{', '.join(allowed_payment_states)}",
            )

        filters["payment_status"] = payment_status

    if order_status:
        if order_status not in allowed_order_states:
            raise HTTPException(
                status_code=422,
                detail=f"order status must be one of: "
                       f"{', '.join(allowed_order_states)}",
            )

        filters["order_status"] = order_status

    if customer_name:
        filters["customer_name"] = customer_name.strip()

    if order_reference:
        filters["order_reference"] = order_reference.strip()

    return filters


# =========================================================
# PAYMENT REQUEST
# =========================================================

@router.post("/request")
def create_payment_request(
    payload: PaymentRequestIn,
    db: Session = Depends(get_db),
    current_user=Depends(require_current_user),
):
    """
    Create a payment request for one bill.

    Returns the bill's own authoritative amount, a PENDING payment id, and
    - in development mode - a UPI URI the guest can open in any UPI app.

    Generating that URI changes nothing about the bill. `payment_status`
    stays `unpaid` until a provider confirms, and the response says so.
    """
    header = _load_header(db, payload.order_id)

    if not _may_touch(db, header, current_user):
        raise HTTPException(
            status_code=403,
            detail="You can only pay for your own order",
        )

    try:
        result = payment_service.create_payment_request(
            db,
            header.id,
            actor_user_id=current_user["user_id"],
            method=payload.method,
        )
    except PaymentError as error:
        raise _fail(error)

    payment = result["payment"]
    request = result["request"]

    return {
        **payment_service.payment_payload(payment, request),
        # What the guest is being asked for, stated separately from what
        # has been paid. Nothing has been paid at this point.
        "bill_total": round(float(header.total_amount or 0), 2),
        "currency": header.currency,
        "order_payment_status": header.payment_status,
        "reused_existing_request": result["reused"],
        "payments_enabled": provider_module.payments_enabled(),
        "gateway": provider_module.configuration(),
    }


# =========================================================
# READ
#
# Literal paths are registered before `/{payment_id}` on purpose. FastAPI
# matches in registration order, so a catch-all integer parameter
# declared first would swallow `/admin/orders` and fail to parse it as an
# id.
# =========================================================

@router.get("/admin/orders")
def admin_list_payable_orders(
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    """
    Every bill, with its payment state, for the admin bill screen.

    Bills are returned newest first, and each carries the authoritative
    total rather than a payment-derived figure, so a bill with no payment
    attempt still shows what it owes.
    """
    headers = (
        db.query(OrderHeader)
        .order_by(OrderHeader.id.desc())
        .limit(200)
        .all()
    )

    rows = []

    for header in headers:
        rows.append({
            "order_id": header.id,
            "reference": header.reference,
            "customer_name": header.customer_name,
            "order_type": header.order_type,
            "table_number": header.table_number,
            "status": header.status,
            "total_amount": round(float(header.total_amount or 0), 2),
            "currency": header.currency,
            "placed_at": (
                header.placed_at.isoformat(timespec="seconds")
                if header.placed_at else None
            ),
            "payment": payment_service.order_payment_state(db, header),
        })

    return {
        "orders": rows,
        "gateway": provider_module.configuration(),
        "payments_enabled": provider_module.payments_enabled(),
    }


@router.get("/order/{order_id}")
def read_order_payments(
    order_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_current_user),
):
    """Every attempt recorded against one bill."""
    header = _load_header(db, order_id)

    if not _may_touch(db, header, current_user):
        raise HTTPException(
            status_code=403,
            detail="You can only view your own order payments",
        )

    payments = payment_service.list_payments_for_order(db, header.id)

    return {
        "order_id": header.id,
        "order_reference": header.reference,
        "state": payment_service.order_payment_state(db, header),
        "payments": [
            payment_service.payment_payload(row) for row in payments
        ],
    }


@router.get("/{payment_id}")
def read_payment(
    payment_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_current_user),
):
    """
    Read one payment's current state.

    A customer who does not own the bill is told 403, which reveals neither
    the existence of the payment nor anything about it.
    """
    try:
        payment = payment_service.get_payment(db, payment_id)
    except PaymentError as error:
        raise _fail(error)

    header = _load_header(db, payment.order_id)

    if not _may_touch(db, header, current_user):
        raise HTTPException(
            status_code=403,
            detail="You can only view your own payment",
        )

    # A still-open attempt gets its UPI instructions re-issued, so a guest
    # who reloads the page still sees the QR rather than an empty form.
    # The reference is unchanged; only the display material is rebuilt.
    request = None

    if payment.status == PaymentStatus.PENDING:
        provider = provider_module.get_provider()

        if provider is not None:
            request = provider.payment_request_material(payment)

    return {
        **payment_service.payment_payload(payment, request),
        "order_payment_status": header.payment_status,
    }


# =========================================================
# VERIFY
# =========================================================

@router.post("/{payment_id}/verify")
def verify_payment(
    payment_id: int,
    payload: PaymentVerifyIn = None,
    db: Session = Depends(get_db),
    current_user=Depends(require_current_user),
):
    """
    Ask the backend to check a payment with the provider.

    Takes no outcome. The customer may trigger a check; only the provider
    may decide what the check finds.

    Idempotent: verifying an already-confirmed payment returns 200 and
    changes nothing.
    """
    try:
        payment = payment_service.get_payment(db, payment_id)
    except PaymentError as error:
        raise _fail(error)

    header = _load_header(db, payment.order_id)

    if not _may_touch(db, header, current_user):
        raise HTTPException(
            status_code=403,
            detail="You can only check your own payment",
        )

    try:
        result = payment_service.verify_payment(
            db,
            payment_id,
            actor_user_id=current_user["user_id"],
        )
    except PaymentError as error:
        raise _fail(error)

    payment = result["payment"]

    return {
        **payment_service.payment_payload(payment),
        "order_payment_status": header.payment_status,
        "verified": result["outcome"] != "PENDING",
        "outcome": result["outcome"],
        "changed": result["changed"],
        "message": result.get("message"),
        "paid_at": (
            header.paid_at.isoformat(timespec="seconds")
            if header.paid_at else None
        ),
    }


@router.post("/{payment_id}/cancel")
def cancel_payment(
    payment_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_current_user),
):
    """
    Withdraw a pending attempt.

    Only PENDING attempts can be withdrawn. A confirmed payment is a fact
    about money and is not editable from here.
    """
    try:
        payment = payment_service.get_payment(db, payment_id)
    except PaymentError as error:
        raise _fail(error)

    header = _load_header(db, payment.order_id)

    if not _may_touch(db, header, current_user):
        raise HTTPException(
            status_code=403,
            detail="You can only cancel your own payment",
        )

    try:
        payment = payment_service.cancel_payment(
            db, payment_id, actor_user_id=current_user["user_id"]
        )
    except PaymentError as error:
        raise _fail(error)

    return payment_service.payment_payload(payment)


# =========================================================
# DEVELOPMENT ONLY
#
# Registered unconditionally so the routes exist, but each one returns 404
# unless PAYMENT_MODE=development. In a real deployment the endpoints are
# therefore absent rather than merely forbidden.
# =========================================================

def _require_development_mode() -> None:
    if not provider_module.development_mode():
        raise HTTPException(
            status_code=404, detail="Not found"
        )


@router.post("/dev/{payment_id}/simulate")
def simulate_provider_outcome(
    payment_id: int,
    payload: DevelopmentSimulateIn,
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    """
    Publish a simulated outcome on the development provider.

    THIS IS A TEST ACTION. It writes nothing to `payments` and nothing to
    `order_headers`. It tells the development provider what it would have
    reported, and then calls the ordinary verification path - exactly the
    path a real webhook will call later.

    So this endpoint cannot settle a bill by itself, and there is no
    `POST /mark-paid` anywhere in the application.
    """
    _require_development_mode()

    outcome = (payload.outcome or PaymentStatus_SUCCESS).strip().upper()

    if outcome not in VALID_SIMULATIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"outcome must be one of: "
                f"{', '.join(VALID_SIMULATIONS)}"
            ),
        )

    try:
        payment = payment_service.get_payment(db, payment_id)
    except PaymentError as error:
        raise _fail(error)

    if not payment.provider_reference:
        raise HTTPException(
            status_code=409,
            detail=(
                "This payment has no provider reference, so there is "
                "nothing for the provider to confirm."
            ),
        )

    provider = provider_module.development_provider()

    # Look the reference up rather than trusting it: an unknown reference
    # is a 404, so a caller cannot invent one and settle a payment.
    known = provider.verify_payment(payment)

    if known.provider_reference != payment.provider_reference:
        raise HTTPException(
            status_code=404,
            detail="The provider does not recognise this reference",
        )

    provider.simulate_outcome(
        provider_reference=payment.provider_reference,
        status=outcome,
        message=payload.reason,
    )

    # The same verification any real confirmation would go through.
    try:
        result = payment_service.verify_payment(
            db,
            payment_id,
            actor_user_id=current_admin["user_id"],
        )
    except PaymentError as error:
        raise _fail(error)

    settled = result["payment"]

    header = _load_header(db, settled.order_id)

    return {
        **payment_service.payment_payload(settled),
        "simulated": True,
        "verified": result["outcome"] != "PENDING",
        "outcome": result["outcome"],
        "order_payment_status": header.payment_status,
        "paid_at": (
            header.paid_at.isoformat(timespec="seconds")
            if header.paid_at else None
        ),
        "note": (
            "Development simulation. This recorded no real money movement "
            "and reached the ledger through the normal verification path."
        ),
    }


# =========================================================
# PROVIDER WEBHOOK  (Phase 7F)
#
# WHY THIS ROUTE HAS NO JWT
# ---------------------------------------------------------------
# A payment provider has no account here and cannot hold a JWT. It calls
# this endpoint from the public internet with a signature over the exact
# bytes it sent. So authentication here is that signature, verified
# against RAZORPAY_WEBHOOK_SECRET, and it is verified BEFORE the body is
# parsed into anything that could touch money.
#
# That ordering is the whole design. Parse first and verify second is a
# real mistake: it runs whatever is in the body - including an
# attacker-chosen order id - before deciding whether the caller is
# allowed to say anything at all.
#
# The two authentication systems are independent. A customer JWT does not
# grant access here, and this route weakens nothing that does.
#
# WHAT IT REFUSES, AND WHAT IT SAYS
# ---------------------------------------------------------------
#     missing signature         401
#     wrong signature           401
#     malformed body            400
#     unusable event            recorded, not acted on
#     unknown payment           404
#     amount/currency mismatch  409, and the bill stays UNPAID
#     duplicate delivery        already processed, nothing changed
#
# The reason a signature was rejected is never returned. Telling an
# attacker which part was wrong tells them what to fix.
# =========================================================

SIGNATURE_HEADER = razorpay_provider.SIGNATURE_HEADER


@router.post("/webhook")
async def provider_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    """Receive a signed provider notification. No JWT, no user identity."""
    # ---- 1. the signature, over the exact bytes received ----

    raw_body = await request.body()

    signature = request.headers.get(SIGNATURE_HEADER)

    if not provider_module.uses_real_provider():
        # Refused as though it did not exist. In development mode there is
        # no secret to verify against, so accepting it would mean
        # accepting anything.
        raise HTTPException(status_code=404, detail="Not found")

    secret = provider_module.RAZORPAY_WEBHOOK_SECRET

    if not secret:
        raise HTTPException(
            status_code=503,
            detail="No webhook secret is configured",
        )

    if not signature:
        raise HTTPException(
            status_code=401, detail="Missing webhook signature"
        )

    if not razorpay_provider.verify_webhook_signature(
        raw_body, signature, secret
    ):
        raise HTTPException(
            status_code=401, detail="Invalid webhook signature"
        )

    # ---- 2. only now is the body trusted enough to read ----

    try:
        event = razorpay_provider.parse_webhook(raw_body)
    except razorpay_provider.WebhookPayloadError as error:
        raise HTTPException(
            status_code=400, detail=f"Malformed webhook: {error}"
        )

    # ---- 3. idempotency, before any financial work ----

    if event.event_id:
        existing = (
            db.query(PaymentWebhookEvent)
            .filter(
                PaymentWebhookEvent.provider == "razorpay",
                PaymentWebhookEvent.event_id == event.event_id,
            )
            .first()
        )

        if existing:
            # Delivered again. Acknowledged, and nothing changes: no second
            # settlement, no second paid_at, no second PAYMENT_SUCCEEDED.
            return {
                "received": True,
                "result": WebhookProcessResult.DUPLICATE,
                "event_id": event.event_id,
                "event": event.event,
                "detail": "This event was already processed.",
            }

    record = PaymentWebhookEvent(
        event_id=event.event_id,
        provider="razorpay",
        event_type=event.event,
        result=WebhookProcessResult.IGNORED,
        # Kept for reconciliation, through the credential sanitiser. A
        # webhook carries no secret today; the same filter runs anyway so
        # a future provider field cannot start storing one.
        metadata_json=event_service.sanitise_metadata({
            "provider_payment_id": event.provider_payment_id,
            "provider_order_id": event.provider_order_id,
            "amount_smallest": event.amount_smallest,
            "currency": event.currency,
            "provider_status": event.provider_status,
        }),
        received_at=datetime.utcnow(),
    )

    db.add(record)
    db.commit()

    outcome = razorpay_provider.outcome_from_event(event)

    if outcome is None:
        record.detail = "Event recorded; it does not settle a payment."
        db.commit()

        return {
            "received": True,
            "result": WebhookProcessResult.IGNORED,
            "event_id": event.event_id,
            "event": event.event,
            "detail": record.detail,
        }

    # ---- 4. match to a local payment ----

    payment = None

    if event.provider_order_id:
        payment = (
            db.query(Payment)
            .filter(Payment.provider_reference == event.provider_order_id)
            .first()
        )

    if payment is None and event.provider_payment_id:
        payment = (
            db.query(Payment)
            .filter(
                Payment.provider_payment_reference
                == event.provider_payment_id
            )
            .first()
        )

    if payment is None:
        record.result = WebhookProcessResult.REFUSED
        record.detail = "No local payment matches this provider reference."
        db.commit()

        raise HTTPException(
            status_code=404,
            detail="No payment matches this notification",
        )

    record.payment_id = payment.id
    record.order_id = payment.order_id

    # ---- 5. settle through the shared path ----

    try:
        result = payment_service.apply_verified_outcome(
            db,
            payment.id,
            outcome,
            provider_reference=event.provider_payment_id,
        )
    except PaymentError as error:
        # A mismatch, or a bill that is already closed. Refused loudly
        # rather than swallowed, because an operator has to see that money
        # moved for a figure this application did not expect.
        record.result = WebhookProcessResult.REFUSED
        record.detail = error.code
        db.commit()

        raise HTTPException(
            status_code=error.status_code, detail=error.message
        )

    settled = result["payment"]

    already_settled = result["outcome"] == "already_settled"

    record.result = (
        WebhookProcessResult.DUPLICATE
        if already_settled
        else WebhookProcessResult.APPLIED
    )
    record.detail = str(result["outcome"])[:300]
    db.commit()

    return {
        "received": True,
        "result": record.result,
        "event_id": event.event_id,
        "event": event.event,
        "payment_id": settled.id,
        "payment_status": settled.status,
        "changed": result["changed"],
        # Reports what happened. Never an instruction the caller should
        # act on.
        "detail": result.get("message"),
    }


@router.get("/admin/reconcile/{payment_id}")
def reconcile_payment(
    payment_id: int,
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    """
    Compare a local payment against the provider's record.

    Admin-only and read-only. Never settles and never repairs: a
    disagreement is reported so a person can look at it, because deciding
    which side is right is not something this application can do alone.
    """
    try:
        return payment_service.reconcile_payment(db, payment_id)
    except PaymentError as error:
        raise HTTPException(
            status_code=error.status_code, detail=error.message
        )

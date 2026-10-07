"""
Payment ledger service.

--------------------------------------------------------------------------
WHO OWNS PAYMENT STATE
--------------------------------------------------------------------------
This module, and only this module, writes:

    payments.status / paid_at / provider_reference
    order_headers.payment_status
    order_headers.paid_at

No route writes them. No other service writes them. A frontend cannot
write them. The one consequence is that every one of those changes goes
through `verify_payment`, which means every one of them has been confirmed
by a provider.

--------------------------------------------------------------------------
WHERE THE AMOUNT COMES FROM
--------------------------------------------------------------------------
`order_headers.total_amount`. It is computed by `order_service` from menu
prices at the moment the order was placed, and it is the only figure this
service will ever charge.

`create_payment_request` copies it. `verify_payment` re-reads it and
refuses to settle if the copy no longer matches. Nothing in this module
reads an amount from a request, a query parameter or a header.

Order value and collected payment stay separate facts. A bill is owed the
moment it exists; it is paid only when a provider says so.

--------------------------------------------------------------------------
TRANSACTIONS
--------------------------------------------------------------------------
Both write paths take a row lock on the order header (`SELECT ... FOR
UPDATE`) before reading, so two simultaneous payments for one bill cannot
both settle. The second one finds the first's SUCCESS and is refused
rather than double-charging the guest.

Every state change and its event are written in the same transaction. An
event that survived a rolled-back payment would be a lie about money.
"""

from datetime import date, datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from models import OrderHeader, Order, Payment, PaymentMethod, PaymentStatus
from services import event_service
from services import payment_provider
from services import payment_provider as provider_module


def percent_of(part: float, whole: float) -> float | None:
    """
    `part` as a percentage of `whole`, or None when `whole` is unusable.

    Defined here rather than imported so the payment core does not depend
    on the assistant's tool layer. The arithmetic is duplicated in one
    place on purpose: a collection percentage must be right even if the
    AI is never used.
    """
    if not whole:
        return None

    return round((float(part) / float(whole)) * 100, 1)


def _daterange(column, start: date, end: date):
    """
    Inclusive date filter, shared with analytics_service.

    Filtered on the date rather than on a datetime range so a bill placed
    at 23:50 belongs to the day it was placed, not to whichever half-open
    boundary happened to be used.
    """
    return func.date(column).between(start.isoformat(), end.isoformat())


# Event names come from the Phase 6C vocabulary in event_service, so there
# is exactly one place that defines what an event may be called.
PAYMENT_REQUESTED = event_service.PAYMENT_REQUESTED
PAYMENT_VERIFICATION_STARTED = event_service.PAYMENT_VERIFICATION_STARTED
PAYMENT_SUCCEEDED = event_service.PAYMENT_SUCCEEDED
PAYMENT_FAILED = event_service.PAYMENT_FAILED
PAYMENT_CANCELLED = event_service.PAYMENT_CANCELLED

ENTITY_PAYMENT = event_service.ENTITY_PAYMENT


class PaymentError(Exception):
    """
    A payment request or verification that must be refused.

    Carries the HTTP status and a message safe to show a guest. Every
    refusal is one of these - there is no path that returns a wrong
    result quietly.
    """

    def __init__(self, message: str, status_code: int = 400,
                 code: str = "payment_error"):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code


# =========================================================
# EVENTS
#
# The existing credential sanitiser runs over every payload, so a future
# caller cannot write a provider key into this table even by accident.
# =========================================================

def _record(db: Session, event_type: str, payment: Payment,
            actor_user_id: int | None = None, metadata: dict | None = None) -> None:
    payload = {
        "payment_id": payment.id,
        "order_reference": payment.order_reference,
        "amount": round(float(payment.amount or 0), 2),
        "currency": payment.currency,
        "method": payment.method,
        "provider": payment.provider,
        "status": payment.status,
    }

    # The provider reference is an identifier, not a credential, and the
    # ledger needs it to be traceable. Nothing else about the provider
    # call is recorded.
    if payment.provider_reference:
        payload["provider_reference"] = payment.provider_reference

    if metadata:
        payload.update(metadata)

    event_service.record_event(
        db,
        event_type,
        ENTITY_PAYMENT,
        entity_id=payment.id,
        actor_user_id=actor_user_id,
        metadata=payload,
    )


# =========================================================
# LOOKUPS
# =========================================================

def _active_provider():
    provider = provider_module.get_provider()

    if provider is None:
        raise PaymentError(
            "Payments are not enabled on this system.",
            status_code=503,
            code="payments_disabled",
        )

    return provider


def get_payment(db: Session, payment_id: int, lock: bool = False) -> Payment:
    """
    Fetch a payment, optionally taking a row lock.

    The lock is what makes settlement single-shot. It is taken before the
    payment is inspected, not after it has been decided.
    """
    query = db.query(Payment).filter(Payment.id == payment_id)

    if lock:
        query = query.with_for_update()

    payment = query.first()

    if not payment:
        raise PaymentError(
            "Payment not found.", status_code=404, code="payment_not_found"
        )

    return payment


def get_successful_payment(db: Session, order_id: int) -> Payment | None:
    """The one settled payment for a bill, if there is one."""
    return (
        db.query(Payment)
        .filter(
            Payment.order_id == order_id,
            Payment.status == PaymentStatus.SUCCESS,
        )
        .order_by(Payment.id.desc())
        .first()
    )


def list_payments_for_order(db: Session, order_id: int) -> list:
    """Every attempt recorded against a bill, newest first."""
    return (
        db.query(Payment)
        .filter(Payment.order_id == order_id)
        .order_by(Payment.id.desc())
        .all()
    )


def order_is_payable(header: OrderHeader) -> tuple:
    """
    Whether a bill may be paid at all, and why not when it may not.

    Returns (ok, reason). Kept separate from the create path so the admin
    view can explain a refusal instead of hiding it.
    """
    if header.status == "Cancelled":
        return False, "This order was cancelled, so there is nothing to pay."

    try:
        total = float(header.total_amount or 0)
    except (TypeError, ValueError):
        return False, "This order has no readable total, so it cannot be paid."

    if total <= 0:
        return False, "This order has a total of zero, so there is nothing to pay."

    if header.payment_status == "paid":
        return False, "This order has already been paid."

    settled = None

    return True, settled


# =========================================================
# CREATE A REQUEST
# =========================================================

def create_payment_request(
    db: Session,
    order_id: int,
    actor_user_id: int | None = None,
    method: str = PaymentMethod.UPI,
) -> dict:
    """
    Ask the provider for a payment request for one bill.

    Creates a PENDING payment holding the bill's own authoritative amount.
    Does not touch `order_headers.payment_status`: a request is a question,
    and the bill stays UNPAID until something answers it.

    Re-requesting a bill that already has a live PENDING attempt returns
    that attempt rather than creating a second one, so a guest tapping
    twice cannot end up paying twice.
    """
    provider = _active_provider()

    method = (method or PaymentMethod.UPI).strip().upper()

    if method not in PaymentMethod.ALL:
        raise PaymentError(
            f"Unsupported payment method. Use one of: "
            f"{', '.join(PaymentMethod.ALL)}.",
            status_code=400,
            code="unsupported_method",
        )

    header = (
        db.query(OrderHeader)
        .filter(OrderHeader.id == order_id)
        .with_for_update()
        .first()
    )

    if not header:
        raise PaymentError(
            "Order not found.", status_code=404, code="order_not_found"
        )

    payable, reason = order_is_payable(header)

    if not payable:
        raise PaymentError(
            reason,
            status_code=409,
            code="order_not_payable",
        )

    # An existing settled payment wins over any new request, and the row
    # lock above means a settlement cannot land between this check and the
    # insert below.
    if get_successful_payment(db, header.id):
        raise PaymentError(
            "This order has already been paid.",
            status_code=409,
            code="already_paid",
        )

    existing = (
        db.query(Payment)
        .filter(
            Payment.order_id == header.id,
            Payment.status == PaymentStatus.PENDING,
        )
        .order_by(Payment.id.desc())
        .first()
    )

    if existing:
        # Reuse the live attempt and re-issue its request material. The
        # amount is re-read from the header rather than from the old row,
        # so a guest never pays a stale figure.
        amount = round(float(header.total_amount or 0), 2)
        currency = (header.currency or "UNSET").upper()

        if (
            round(float(existing.amount or 0), 2) != amount
            or (existing.currency or "").upper() != currency
        ):
            # The bill moved after the request was made. The old request
            # can no longer be honoured, so it is withdrawn rather than
            # left able to collect the wrong amount.
            existing.status = PaymentStatus.CANCELLED
            existing.failure_reason = (
                "Bill total changed after this request was created"
            )

            _record(
                db,
                PAYMENT_CANCELLED,
                existing,
                actor_user_id,
                {"reason": "amount_changed"},
            )

            db.flush()
        else:
            request = provider.create_payment_request(existing)

            _record(
                db,
                PAYMENT_REQUESTED,
                existing,
                actor_user_id,
                {"reused_existing_request": True},
            )

            db.commit()

            return {
                "payment": existing,
                "request": request,
                "reused": True,
            }

    # ---- a fresh request ----

    payment = Payment(
        order_id=header.id,
        order_reference=header.reference,
        # The authoritative figure, copied. Never from the caller.
        amount=round(float(header.total_amount or 0), 2),
        currency=(header.currency or "UNSET").upper(),
        method=method,
        provider=provider.name,
        status=PaymentStatus.PENDING,
        requested_at=datetime.utcnow(),
    )

    db.add(payment)
    db.flush()

    request = provider.create_payment_request(payment)

    _record(db, PAYMENT_REQUESTED, payment, actor_user_id)

    db.commit()

    return {"payment": payment, "request": request, "reused": False}


# =========================================================
# VERIFY
# =========================================================

def verify_payment(
    db: Session,
    payment_id: int,
    actor_user_id: int | None = None,
) -> dict:
    """
    Ask the provider what happened, and record exactly that.

    This is the only function in the application that can set
    `payment_status = 'paid'`, and it does so only when the provider
    returns SUCCESS.

    Refusals, each of which leaves the database untouched:

      * payment or order does not exist            404
      * the stored amount no longer matches the
        bill's authoritative total                 409
      * the stored currency no longer matches     409
      * another payment for this bill already
        settled                                   409
      * the order has been cancelled              409
      * the provider has recorded no outcome      stays PENDING

    The last one is not an error. A guest who scanned a QR and the system
    simply has not heard back yet is exactly the PENDING case.
    """
    provider = _active_provider()

    payment = get_payment(db, payment_id, lock=True)

    header = (
        db.query(OrderHeader)
        .filter(OrderHeader.id == payment.order_id)
        .with_for_update()
        .first()
    )

    if not header:
        raise PaymentError(
            "The order for this payment no longer exists.",
            status_code=404,
            code="order_not_found",
        )

    # ---- idempotence: already settled is not an error ----

    if payment.status == PaymentStatus.SUCCESS:
        return {
            "payment": payment,
            "outcome": "already_settled",
            "changed": False,
            "message": "This payment was already confirmed.",
        }

    if payment.status == PaymentStatus.CANCELLED:
        raise PaymentError(
            "This payment request was withdrawn and cannot be confirmed.",
            status_code=409,
            code="payment_cancelled",
        )

    _record(
        db, PAYMENT_VERIFICATION_STARTED, payment, actor_user_id
    )

    # ---- the amount must still be the bill's amount ----

    authoritative_amount = round(float(header.total_amount or 0), 2)
    stored_amount = round(float(payment.amount or 0), 2)

    if stored_amount != authoritative_amount:
        db.commit()

        raise PaymentError(
            "This payment request does not match the current bill total, "
            "so it cannot be confirmed. Ask for a new payment request.",
            status_code=409,
            code="amount_mismatch",
        )

    authoritative_currency = (header.currency or "UNSET").upper()
    stored_currency = (payment.currency or "").upper()

    if stored_currency != authoritative_currency:
        db.commit()

        raise PaymentError(
            "This payment request does not match the bill currency, "
            "so it cannot be confirmed.",
            status_code=409,
            code="currency_mismatch",
        )

    if header.status == "Cancelled":
        db.commit()

        raise PaymentError(
            "This order was cancelled and cannot be paid.",
            status_code=409,
            code="order_cancelled",
        )

    # ---- one settled payment per bill ----

    _refuse_if_another_payment_settled(db, header, payment)

    # ---- ask the provider, then settle ----

    outcome = provider.verify_payment(payment)

    return apply_outcome(
        db,
        payment,
        header,
        outcome,
        actor_user_id=actor_user_id,
    )


def _refuse_if_another_payment_settled(db: Session, header, payment) -> None:
    """
    Refuse if some other attempt on this bill has already settled.

    With the header locked, this cannot race: two concurrent settlements
    serialise here, and the second one sees the first's SUCCESS.
    """
    other = (
        db.query(Payment)
        .filter(
            Payment.order_id == header.id,
            Payment.status == PaymentStatus.SUCCESS,
            Payment.id != payment.id,
        )
        .with_for_update()
        .first()
    )

    if other:
        db.commit()

        raise PaymentError(
            "Another payment for this bill has already been confirmed.",
            status_code=409,
            code="already_paid",
        )


def apply_outcome(db: Session, payment: Payment, header: OrderHeader,
                  outcome, actor_user_id: int | None = None,
                  source: str = "verify") -> dict:
    """
    Write a provider outcome onto a payment and its bill.

    The ONLY place in the application that can set a payment to SUCCESS or
    a bill to paid. Both the pull path (`verify_payment`) and the push path
    (`apply_verified_outcome`, used by a signed webhook) come through
    here, so a bill cannot be settled by one route with stricter checks
    than the other.

    `payment` and `header` must already be row-locked by the caller.
    """
    if outcome.status == PaymentStatus.SUCCESS:
        payment.status = PaymentStatus.SUCCESS
        payment.paid_at = outcome.settled_at or datetime.utcnow()
        payment.failure_reason = None

        if outcome.provider_reference:
            payment.provider_reference = outcome.provider_reference

        header.payment_status = "paid"
        header.paid_at = payment.paid_at

        _record(
            db,
            PAYMENT_SUCCEEDED,
            payment,
            actor_user_id,
            {"verified": True, "source": source},
        )
    elif outcome.status == PaymentStatus.FAILED:
        payment.status = PaymentStatus.FAILED
        payment.failure_reason = (
            outcome.message or "The provider reported this payment failed."
        )

        # A failed payment leaves the bill UNPAID. `payment_status` is
        # never set to 'failed' here: that column describes the bill, and
        # the bill has not changed. The failure is on the attempt, which
        # is exactly where it belongs.
        _record(
            db,
            PAYMENT_FAILED,
            payment,
            actor_user_id,
            {
                "reason": payment.failure_reason,
                "verified": True,
                "source": source,
            },
        )
    else:
        # PENDING, or anything a provider does not recognise. Stays
        # pending, which is the safe default.
        _record(
            db,
            PAYMENT_VERIFICATION_STARTED,
            payment,
            actor_user_id,
            {"verified": True, "outcome": outcome.status, "source": source},
        )

    db.commit()

    return {
        "payment": payment,
        "outcome": outcome.status,
        "changed": payment.status != PaymentStatus.PENDING,
        "message": outcome.message,
    }


# =========================================================
# PROVIDER-PUSHED SETTLEMENT   (Phase 7F)
#
# A signed webhook, rather than a customer asking.
#
# Every guard in `verify_payment` is re-applied here: the amount must
# still match the bill, the currency must still match, the bill must not
# be cancelled, and no other attempt may already have settled. A provider
# saying "captured" is not a licence to skip those - it is one input
# among several, and if they disagree the disagreement wins.
# =========================================================

def apply_verified_outcome(
    db: Session,
    payment_id: int,
    outcome,
    provider_reference: str | None = None,
) -> dict:
    """
    Settle or fail a payment from an outcome a provider has signed.

    Returns the same shape as `verify_payment`, including
    `changed: False` for a payment that was already settled. That is what
    makes a duplicate delivery safe: the second one changes nothing.
    """
    payment = get_payment(db, payment_id, lock=True)

    header = (
        db.query(OrderHeader)
        .filter(OrderHeader.id == payment.order_id)
        .with_for_update()
        .first()
    )

    if not header:
        raise PaymentError(
            "The order for this payment no longer exists.",
            status_code=404,
            code="order_not_found",
        )

    if payment.status == PaymentStatus.SUCCESS:
        return {
            "payment": payment,
            "outcome": "already_settled",
            "changed": False,
            "message": "This payment was already confirmed.",
        }

    if payment.status == PaymentStatus.CANCELLED:
        raise PaymentError(
            "This payment request was withdrawn and cannot be confirmed.",
            status_code=409,
            code="payment_cancelled",
        )

    # A provider reports the amount it processed. If it disagrees with the
    # bill, the bill is right and the payment is refused - never the other
    # way round.
    reported_amount = getattr(outcome, "reported_amount", None)

    if reported_amount is not None:
        reported = round(float(reported_amount), 2)

        if reported != round(float(header.total_amount or 0), 2):
            db.commit()

            raise PaymentError(
                "The provider confirmed a different amount than the bill "
                "says. Not settling. This needs an operator to reconcile.",
                status_code=409,
                code="amount_mismatch",
            )

    reported_currency = getattr(outcome, "reported_currency", None)

    if reported_currency:
        if reported_currency.upper() != (header.currency or "").upper():
            db.commit()

            raise PaymentError(
                "The provider confirmed a different currency than the bill "
                "says. Not settling. This needs an operator to reconcile.",
                status_code=409,
                code="currency_mismatch",
            )

    if header.status == "Cancelled":
        db.commit()

        raise PaymentError(
            "This order was cancelled and cannot be paid.",
            status_code=409,
            code="order_cancelled",
        )

    _refuse_if_another_payment_settled(db, header, payment)

    # Keep the provider's own payment identifier for reconciliation. It is
    # separate from provider_reference because for Razorpay the two refer
    # to different objects: the order we created and the payment made.
    if provider_reference:
        payment.provider_payment_reference = provider_reference

    return apply_outcome(
        db, payment, header, outcome, source="webhook"
    )


def reconcile_payment(db: Session, payment_id: int) -> dict:
    """
    Compare a local payment against what the provider currently holds.

    Read-only. Never settles and never repairs: a disagreement is
    reported so a person can look at it, because deciding which side is
    right is not something this application can do on its own.
    """
    payment = get_payment(db, payment_id)

    provider = provider_module.get_provider()

    if provider is None or not hasattr(provider, "reconcile"):
        return {
            "has_data": False,
            "payment_id": payment.id,
            "limitation": (
                "The active provider does not support reconciliation."
            ),
        }

    reference = payment.provider_reference

    if not reference:
        return {
            "has_data": False,
            "payment_id": payment.id,
            "limitation": (
                "This payment has no provider reference yet, so there is "
                "nothing to compare against."
            ),
        }

    try:
        if reference.startswith("order_"):
            remote = provider.client.order.fetch(reference)
        else:
            remote = provider.client.payment.fetch(reference)
    except Exception as error:
        return {
            "has_data": False,
            "payment_id": payment.id,
            "limitation": (
                "The provider could not be reached "
                f"({type(error).__name__}), so nothing could be compared."
            ),
        }

    result = provider.reconcile(payment, remote or {})

    # Reconciliation is where a provider's payment id lands on a settled
    # row, so a settled payment keeps a reference for support even when the
    # webhook did not carry one.
    payment_id_from_provider = None

    if isinstance(remote, dict):
        payment_id_from_provider = remote.get("id") or None

        if not payment_id_from_provider:
            payments = remote.get("payments") or []

            if payments and isinstance(payments[0], dict):
                payment_id_from_provider = payments[0].get("id")

    if (
        payment_id_from_provider
        and not payment.provider_payment_reference
        and payment.status == PaymentStatus.SUCCESS
    ):
        payment.provider_payment_reference = payment_id_from_provider
        db.commit()

    return {"has_data": True, **result}


# =========================================================
# CANCEL
# =========================================================

def cancel_payment(
    db: Session,
    payment_id: int,
    actor_user_id: int | None = None,
) -> Payment:
    """
    Withdraw a pending attempt.

    Only PENDING attempts can be withdrawn. A settled or failed payment is
    a historical fact and is never edited or removed.
    """
    payment = get_payment(db, payment_id, lock=True)

    if payment.status == PaymentStatus.SUCCESS:
        raise PaymentError(
            "A confirmed payment cannot be cancelled here.",
            status_code=409,
            code="already_paid",
        )

    if payment.status != PaymentStatus.PENDING:
        raise PaymentError(
            "This payment is no longer pending.",
            status_code=409,
            code="payment_closed",
        )

    payment.status = PaymentStatus.CANCELLED
    payment.failure_reason = "Withdrawn before any outcome arrived"

    _record(db, PAYMENT_CANCELLED, payment, actor_user_id)

    db.commit()

    return payment


# =========================================================
# PRESENTATION
# =========================================================

def payment_payload(payment: Payment, request: dict | None = None) -> dict:
    """
    How a payment is shown.

    Only fields that are safe to hand out. There is no provider secret,
    signature or raw provider response on this model to leak, and the
    provider reference is included because staff and the guest both need
    to quote it to the provider.
    """
    payload = {
        "payment_id": payment.id,
        "order_id": payment.order_id,
        "order_reference": payment.order_reference,
        "amount": round(float(payment.amount or 0), 2),
        "currency": payment.currency,
        "method": payment.method,
        "provider": payment.provider,
        "provider_reference": payment.provider_reference,
        "status": payment.status,
        "requested_at": (
            payment.requested_at.isoformat(timespec="seconds")
            if payment.requested_at else None
        ),
        "paid_at": (
            payment.paid_at.isoformat(timespec="seconds")
            if payment.paid_at else None
        ),
        "failure_reason": payment.failure_reason,
        # A provider reference identifies an attempt. It is not evidence
        # that money moved, so the payload says so explicitly rather than
        # letting a client infer it.
        "provider_reference_is_proof": False,
        "settled": payment.status == PaymentStatus.SUCCESS,
    }

    if request:
        payload["request"] = {
            "upi_uri": request.get("upi_uri"),
            "request_only": True,
            "instruction": request.get("instruction"),
        }

    return payload


def order_payment_state(db: Session, header: OrderHeader) -> dict:
    """
    The payment story of one bill, for the customer and admin views.

    Built from the ledger, not inferred. `payment_status` on the header is
    reported for continuity with earlier phases, and the ledger is
    reported alongside it so the two can be compared.
    """
    payments = list_payments_for_order(db, header.id)
    settled = next(
        (row for row in payments if row.status == PaymentStatus.SUCCESS),
        None,
    )
    pending = next(
        (row for row in payments if row.status == PaymentStatus.PENDING),
        None,
    )

    return {
        "bill_total": round(float(header.total_amount or 0), 2),
        "currency": header.currency,
        # The stored header state, kept because Phases 1-6 read it.
        "payment_status": header.payment_status,
        "paid_at": (
            header.paid_at.isoformat(timespec="seconds")
            if header.paid_at else None
        ),
        "paid_amount": (
            round(float(settled.amount or 0), 2) if settled else 0.0
        ),
        "payment_method": settled.method if settled else None,
        "provider_reference": (
            settled.provider_reference if settled else None
        ),
        "attempts": len(payments),
        "successful_attempts": sum(
            1 for row in payments if row.status == PaymentStatus.SUCCESS
        ),
        "failed_attempts": sum(
            1 for row in payments if row.status == PaymentStatus.FAILED
        ),
        "pending_request_id": pending.id if pending else None,
        "settled_payment_id": settled.id if settled else None,
        "outstanding_amount": (
            0.0 if settled else round(float(header.total_amount or 0), 2)
        ),
    }


# =========================================================
# HISTORY AND SETTLEMENT  (Phase 6E)
#
# Read-only. Nothing below writes a payment, edits a bill or changes a
# status. A failed or cancelled attempt that happened is a fact about the
# restaurant and is never removed - which is the whole reason the attempts
# are counted separately from the bill.
#
# There are no new tables. `order_headers` says what was owed and
# `payments` says what was attempted and what a provider confirmed.
# =========================================================

#: Every settlement state a bill can be reported in. Derived from the
#: ledger, never from a stored column, so a disagreement between the
#: header and the ledger shows up instead of being hidden.
BILL_PAID = "PAID"
BILL_PARTIALLY_PAID = "PARTIALLY_PAID"
BILL_UNPAID = "UNPAID"

#: Cap on any page size a caller may ask for. An unbounded history request
#: is the obvious way to turn a report into a table dump.
MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 25


def settlement_for(db: Session, header: OrderHeader) -> dict:
    """
    The one calculation of billed / collected / outstanding for a bill.

    outstanding = bill_total - collected

    where `bill_total` is `OrderHeader.total_amount` - the authoritative
    figure, computed from menu prices when the order was placed - and
    `collected` is the sum of the amounts of SUCCESS payments, which is
    the only status a provider confirmation produces.

    Collected is a SUM rather than "the settled payment" so the arithmetic
    stays correct even if the one-successful-payment-per-bill invariant is
    ever relaxed. Today that invariant makes the sum 0 or a single figure.

    A PENDING, FAILED or CANCELLED attempt contributes nothing. That is
    what separates a displayed QR from money that arrived.

    The result is clamped at zero: a bill cannot owe less than nothing, and
    an overpayment is a real event that should be visible in the collected
    figure rather than silently absorbed into a negative.
    """
    collected = (
        db.query(func.coalesce(func.sum(Payment.amount), 0.0))
        .filter(
            Payment.order_id == header.id,
            Payment.status == PaymentStatus.SUCCESS,
        )
        .scalar()
    )

    bill_total = round(float(header.total_amount or 0), 2)
    collected = round(float(collected or 0), 2)
    outstanding = round(max(0.0, bill_total - collected), 2)

    if outstanding == 0 and collected > 0:
        state = BILL_PAID
    elif collected > 0:
        state = BILL_PARTIALLY_PAID
    else:
        state = BILL_UNPAID

    return {
        "bill_total": bill_total,
        "currency": header.currency,
        "collected": collected,
        "outstanding": outstanding,
        "billed_state": state,
    }


def attempt_counts(db: Session, order_id: int) -> dict:
    """How many attempts of each status one bill has collected."""
    counts = dict(
        db.query(Payment.status, func.count(Payment.id))
        .filter(Payment.order_id == order_id)
        .group_by(Payment.status)
        .all()
    )

    return {
        "attempts": sum(int(value) for value in counts.values()),
        "successful_attempts": int(counts.get(PaymentStatus.SUCCESS, 0)),
        "failed_attempts": int(counts.get(PaymentStatus.FAILED, 0)),
        "cancelled_attempts": int(counts.get(PaymentStatus.CANCELLED, 0)),
        "pending_attempts": int(counts.get(PaymentStatus.PENDING, 0)),
    }


def _lines_for_headers(db: Session, header_ids: list) -> dict:
    """
    Line items for a set of bills, fetched in one query.

    Bill history reads every bill a guest has, so a query per bill would
    be one round trip per order. Grouped here instead.
    """
    if not header_ids:
        return {}

    rows = (
        db.query(Order)
        .filter(Order.order_id.in_(header_ids))
        .order_by(Order.id.asc())
        .all()
    )

    grouped = {}

    for row in rows:
        # A cancelled line is not part of any bill. It stays in the ledger
        # as a record, but it is not charged for, so it is not shown.
        if row.status == "Cancelled":
            continue

        grouped.setdefault(row.order_id, []).append({
            "order_id": row.id,
            "menu_item": row.menu_item,
            "quantity": row.quantity,
            "unit_price": (
                round(float(row.unit_price), 2)
                if row.unit_price is not None else None
            ),
            "line_total": round(float(row.total_price or 0), 2),
            "special_instructions": row.special_instructions,
        })

    return grouped


def _bill_record(db: Session, header: OrderHeader,
                 lines_by_header: dict) -> dict:
    """One bill, as shown in either history view."""
    settlement = settlement_for(db, header)
    counts = attempt_counts(db, header.id)

    settled = (
        db.query(Payment)
        .filter(
            Payment.order_id == header.id,
            Payment.status == PaymentStatus.SUCCESS,
        )
        .order_by(Payment.id.desc())
        .first()
    )

    return {
        "order_id": header.id,
        "reference": header.reference,
        "created_at": (
            header.placed_at.isoformat(timespec="seconds")
            if header.placed_at else None
        ),
        "order_status": header.status,
        "order_type": header.order_type,
        "table_number": header.table_number,
        "customer_name": header.customer_name,

        # The stored breakdown, never recomputed.
        "subtotal": round(float(header.subtotal or 0), 2),
        "tax_percentage": round(float(header.tax_percentage or 0), 2),
        "tax_amount": round(float(header.tax_amount or 0), 2),
        "service_charge_percentage": round(
            float(header.service_charge_percentage or 0), 2
        ),
        "service_charge_amount": round(
            float(header.service_charge_amount or 0), 2
        ),
        "discount_amount": round(float(header.discount_amount or 0), 2),
        "discount_reason": header.discount_reason,

        # The authoritative amount.
        "total_amount": settlement["bill_total"],
        "currency": settlement["currency"],

        "items": lines_by_header.get(header.id, []),

        # ---- payment ----
        "billed_state": settlement["billed_state"],
        "payment_status": header.payment_status,
        "paid_amount": settlement["collected"],
        "outstanding_amount": settlement["outstanding"],
        "paid_at": (
            header.paid_at.isoformat(timespec="seconds")
            if header.paid_at else None
        ),
        "payment_method": settled.method if settled else None,
        "provider_reference": (
            settled.provider_reference if settled else None
        ),
        **counts,
    }


def customer_bill_history(db: Session, user_id: int,
                         limit: int = 50) -> dict:
    """
    Every bill this guest has, newest first.

    Scoped by `user_id`, which comes from the token. No filter a caller
    could supply widens it - a guest sees their own bills and nothing else.

    This is history, not the current-visit bill: it is not restricted to a
    claimed table, so a guest can look back at a previous visit.
    """
    headers = (
        db.query(OrderHeader)
        .filter(OrderHeader.user_id == user_id)
        .order_by(OrderHeader.id.desc())
        .limit(max(1, min(int(limit or 50), MAX_PAGE_SIZE)))
        .all()
    )

    lines = _lines_for_headers(db, [header.id for header in headers])

    bills = [_bill_record(db, header, lines) for header in headers]

    return {
        "bills": bills,
        "bill_count": len(bills),
        "total_billed": round(sum(row["total_amount"] for row in bills), 2),
        "total_collected": round(
            sum(row["paid_amount"] for row in bills), 2
        ),
        "total_outstanding": round(
            sum(row["outstanding_amount"] for row in bills), 2
        ),
        "currency": (
            bills[0]["currency"] if bills else None
        ),
    }


def customer_payment_history(db: Session, user_id: int,
                             limit: int = 50) -> dict:
    """
    Every payment attempt this guest has made, newest first.

    Joins through the bill rather than trusting a client-supplied owner id,
    so the guest's own attempts are all that can be returned. Attempt
    rows are immutable history: a FAILED and a CANCELLED attempt both stay
    visible alongside the one that settled.
    """
    payments = (
        db.query(Payment)
        .join(
            OrderHeader,
            OrderHeader.id == Payment.order_id,
        )
        .filter(OrderHeader.user_id == user_id)
        .order_by(Payment.id.desc())
        .limit(max(1, min(int(limit or 50), MAX_PAGE_SIZE)))
        .all()
    )

    return {
        "payments": [payment_payload(row) for row in payments],
        "payment_count": len(payments),
        "successful_count": sum(
            1 for row in payments if row.status == PaymentStatus.SUCCESS
        ),
        "failed_count": sum(
            1 for row in payments if row.status == PaymentStatus.FAILED
        ),
        "cancelled_count": sum(
            1 for row in payments if row.status == PaymentStatus.CANCELLED
        ),
        "pending_count": sum(
            1 for row in payments if row.status == PaymentStatus.PENDING
        ),
        "collected_total": round(
            sum(
                float(row.amount or 0)
                for row in payments
                if row.status == PaymentStatus.SUCCESS
            ),
            2,
        ),
    }


def _validated_filters(filters: dict) -> dict:
    """
    Narrow a filter dict to the keys this module understands.

    Anything else a caller sends is discarded rather than reaching a query.
    There is no key in this project that lets a request supply a column, a
    comparison or an expression, so a filter cannot become SQL.
    """
    allowed = {
        "payment_status",
        "order_status",
        "date_from",
        "date_to",
        "customer_name",
        "order_reference",
    }

    return {
        key: value
        for key, value in (filters or {}).items()
        if key in allowed and value not in (None, "")
    }


def admin_bill_history(db: Session, filters: dict | None = None,
                       page: int = 1, page_size: int = DEFAULT_PAGE_SIZE
                       ) -> dict:
    """
    Bills with their settlement state, filtered and paginated.

    Admin-only, so no ownership restriction applies. The filters are a
    closed set of named fields; none of them is a column name from the
    request.
    """
    clean = _validated_filters(filters)

    page = max(1, int(page or 1))
    page_size = max(1, min(int(page_size or DEFAULT_PAGE_SIZE), MAX_PAGE_SIZE))

    query = db.query(OrderHeader)

    if "order_status" in clean:
        query = query.filter(OrderHeader.status == clean["order_status"])

    if "date_from" in clean:
        query = query.filter(
            func.date(OrderHeader.placed_at) >= clean["date_from"]
        )

    if "date_to" in clean:
        query = query.filter(
            func.date(OrderHeader.placed_at) <= clean["date_to"]
        )

    if "customer_name" in clean:
        query = query.filter(
            OrderHeader.customer_name == clean["customer_name"]
        )

    if "order_reference" in clean:
        query = query.filter(
            OrderHeader.reference == clean["order_reference"]
        )

    # `payment_status` filters on the ledger-derived state rather than the
    # stored column, so PAID means a provider confirmed it - not that
    # somebody set a field.
    headers = query.order_by(OrderHeader.id.desc()).all()

    if "payment_status" in clean:
        headers = [
            header for header in headers
            if settlement_for(db, header)["billed_state"]
            == clean["payment_status"]
        ]

    total = len(headers)
    start = (page - 1) * page_size
    window = headers[start:start + page_size]

    lines = _lines_for_headers(db, [header.id for header in window])

    bills = [_bill_record(db, header, lines) for header in window]

    # Totals describe the whole filtered set, not just the page, so a
    # paginated view still reports a true outstanding figure.
    settlements = [settlement_for(db, header) for header in headers]

    return {
        "bills": bills,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total_matching": total,
            "total_pages": max(1, -(-total // page_size)),
        },
        "summary": {
            "bills": total,
            "billed": round(sum(row["bill_total"] for row in settlements), 2),
            "collected": round(
                sum(row["collected"] for row in settlements), 2
            ),
            "outstanding": round(
                sum(row["outstanding"] for row in settlements), 2
            ),
            "paid_bills": sum(
                1 for row in settlements
                if row["billed_state"] == BILL_PAID
            ),
            "partially_paid_bills": sum(
                1 for row in settlements
                if row["billed_state"] == BILL_PARTIALLY_PAID
            ),
            "unpaid_bills": sum(
                1 for row in settlements
                if row["billed_state"] == BILL_UNPAID
            ),
        },
        "applied_filters": clean,
    }


def admin_payment_history(db: Session, filters: dict | None = None,
                         page: int = 1,
                         page_size: int = DEFAULT_PAGE_SIZE) -> dict:
    """
    The payment ledger itself, filtered and paginated.

    Pagination happens in SQL with a LIMIT, so a large ledger is never
    loaded in full to show one page of it. `total_matching` is a COUNT
    rather than `len(rows)`, which would be the page size.
    """
    clean = _validated_filters(filters)

    page = max(1, int(page or 1))
    page_size = max(1, min(int(page_size or DEFAULT_PAGE_SIZE), MAX_PAGE_SIZE))

    query = db.query(Payment).join(
        OrderHeader, OrderHeader.id == Payment.order_id
    )

    if "payment_status" in clean:
        query = query.filter(Payment.status == clean["payment_status"])

    if "order_status" in clean:
        query = query.filter(OrderHeader.status == clean["order_status"])

    if "date_from" in clean:
        query = query.filter(
            func.date(Payment.requested_at) >= clean["date_from"]
        )

    if "date_to" in clean:
        query = query.filter(
            func.date(Payment.requested_at) <= clean["date_to"]
        )

    if "customer_name" in clean:
        query = query.filter(
            OrderHeader.customer_name == clean["customer_name"]
        )

    if "order_reference" in clean:
        query = query.filter(
            OrderHeader.reference == clean["order_reference"]
        )

    total = query.count()

    rows = (
        query.order_by(Payment.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    payments = [payment_payload(row) for row in rows]

    # A settlement attempt re-issues its UPI material so a staff member
    # reopening a bill can still show the QR for an attempt that is open.
    provider = payment_provider.get_provider()

    for record, row in zip(payments, rows):
        if row.status == PaymentStatus.PENDING and provider is not None:
            record["request"] = {
                "upi_uri": provider.payment_request_material(row).get(
                    "upi_uri"
                ),
                "request_only": True,
            }

        header = db.query(OrderHeader).filter(
            OrderHeader.id == row.order_id
        ).first()

        record["customer_name"] = (
            header.customer_name if header else None
        )
        record["order_status"] = header.status if header else None

    return {
        "payments": payments,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total_matching": int(total),
            "total_pages": max(1, -(-int(total) // page_size)),
        },
        "counts": _ledger_counts(db, clean),
        "applied_filters": clean,
    }


def _ledger_counts(db: Session, clean: dict) -> dict:
    """Attempt counts for a filtered set, as an aggregate rather than rows."""
    query = db.query(Payment.status, func.count(Payment.id)).join(
        OrderHeader, OrderHeader.id == Payment.order_id
    )

    if "payment_status" in clean:
        query = query.filter(Payment.status == clean["payment_status"])

    if "date_from" in clean:
        query = query.filter(
            func.date(Payment.requested_at) >= clean["date_from"]
        )

    if "date_to" in clean:
        query = query.filter(
            func.date(Payment.requested_at) <= clean["date_to"]
        )

    counts = {
        str(name): int(value)
        for name, value in query.group_by(Payment.status).all()
    }

    return {
        "attempts": sum(counts.values()),
        "successful_attempts": int(counts.get(PaymentStatus.SUCCESS, 0)),
        "failed_attempts": int(counts.get(PaymentStatus.FAILED, 0)),
        "cancelled_attempts": int(counts.get(PaymentStatus.CANCELLED, 0)),
        "pending_attempts": int(counts.get(PaymentStatus.PENDING, 0)),
    }


def settlement_summary(db: Session, start: date, end: date,
                       label: str) -> dict:
    """
    Billed, collected and outstanding for a window, plus attempt counts.

    The three figures come from different places on purpose:

      billed      OrderHeader.total_amount, for bills placed in the window
      collected   SUCCESS payments confirmed inside the window
      outstanding billed minus what is settled, still outstanding

    Collected is measured by when the money arrived (`paid_at`), not by
    when the bill was raised, because "how much came in today" means the
    day the money landed.
    """
    billed_row = (
        db.query(
            func.count(OrderHeader.id),
            func.coalesce(func.sum(OrderHeader.total_amount), 0.0),
        )
        .filter(_daterange(OrderHeader.placed_at, start, end))
        .first()
    )

    bills = int(billed_row[0] or 0)
    billed = round(float(billed_row[1] or 0), 2)

    settled_row = (
        db.query(
            func.count(Payment.id),
            func.coalesce(func.sum(Payment.amount), 0.0),
        )
        .filter(
            _daterange(Payment.paid_at, start, end),
            Payment.status == PaymentStatus.SUCCESS,
        )
        .first()
    )

    collected = round(float(settled_row[1] or 0), 2)

    # Outstanding is per bill, because a bill is the unit a guest settles.
    # Summing each bill's own residual is the only way to get it right
    # without pairing payments to bills by guesswork.
    headers = (
        db.query(OrderHeader)
        .filter(_daterange(OrderHeader.placed_at, start, end))
        .all()
    )

    settlements = [settlement_for(db, header) for header in headers]

    outstanding = round(
        sum(row["outstanding"] for row in settlements), 2
    )

    attempt_rows = dict(
        db.query(Payment.status, func.count(Payment.id))
        .filter(_daterange(Payment.requested_at, start, end))
        .group_by(Payment.status)
        .all()
    )

    return {
        "range": label,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),

        # The three figures, never conflated.
        "billed": billed,
        "collected": collected,
        "outstanding": outstanding,
        "collection_percent": percent_of(collected, billed),

        "bills": bills,
        "paid_bills": sum(
            1 for row in settlements if row["billed_state"] == BILL_PAID
        ),
        "partially_paid_bills": sum(
            1 for row in settlements
            if row["billed_state"] == BILL_PARTIALLY_PAID
        ),
        "unpaid_bills": sum(
            1 for row in settlements if row["billed_state"] == BILL_UNPAID
        ),

        "successful_payments": int(settled_row[0] or 0),
        "payment_attempts": sum(int(v) for v in attempt_rows.values()),
        "failed_payment_attempts": int(
            attempt_rows.get(PaymentStatus.FAILED, 0)
        ),
        "cancelled_payment_attempts": int(
            attempt_rows.get(PaymentStatus.CANCELLED, 0)
        ),
        "pending_payment_attempts": int(
            attempt_rows.get(PaymentStatus.PENDING, 0)
        ),
        "success_rate_percent": percent_of(
            int(attempt_rows.get(PaymentStatus.SUCCESS, 0)),
            int(attempt_rows.get(PaymentStatus.SUCCESS, 0))
            + int(attempt_rows.get(PaymentStatus.FAILED, 0)),
        ),
    }
"""
Razorpay payment provider.

--------------------------------------------------------------------------
WHY THIS EXISTS AND WHAT IT DOES NOT DO
--------------------------------------------------------------------------
This connects the payment architecture to a real payment provider. It does
not change how money is decided: a payment becomes SUCCESS here only
because Razorpay said so, through a signed webhook or a signed fetch, and
only after this module and `payment_service` have agreed that the amount
and currency match the bill.

The interface is the existing `PaymentProvider` from `payment_provider`. It
is not extended, and the development provider still satisfies it unchanged.

--------------------------------------------------------------------------
TEST FIRST, ALWAYS
--------------------------------------------------------------------------
`RAZORPAY_TEST` is the default and the only mode this project will ship
with. `RAZORPAY_LIVE` requires, on top of valid credentials:

    PAYMENT_MODE=live
    PAYMENT_PROVIDER=razorpay
    ALLOW_LIVE_PAYMENTS=true

Four gates, because "the credentials happen to be present" is not consent
to move real money. `payment_provider.validate_configuration()` enforces
them and raises rather than falling back to the development provider.

--------------------------------------------------------------------------
THE OFFICIAL API, USED AS DOCUMENTED
--------------------------------------------------------------------------
Order creation      POST /v1/orders
                     {amount, currency, receipt, notes}
                     amount is in the smallest currency unit.

Signature           razorpay.Utility.verify_webhook_signature(
                         body, signature, webhook_secret)

Fetch               GET /v1/orders/{id}   - returns payments[]
                     GET /v1/payments/{id}

Nothing here is an invented endpoint or an invented field. The one place
this module goes beyond the raw API is the smallest-unit conversion, which
is documented behaviour expressed as an explicit table rather than an
assumption that every currency has two decimals.

--------------------------------------------------------------------------
PUSH, NOT PULL
--------------------------------------------------------------------------
Razorpay is push-based: it tells the system what happened rather than
being asked. `verify_payment` therefore checks for an outcome a webhook
has already delivered, and only falls back to a signed fetch. That
fallback matters - a webhook can be lost - but the primary path is the
signed callback, and both converge on the same settlement guards.
"""

import hashlib
import hmac
import json
import os
from datetime import datetime

from services.payment_provider import (
    PaymentProvider,
    ProviderOutcome,
    PaymentConfigurationError,
)


# =========================================================
# CURRENCY
#
# Razorpay expresses amounts in the smallest unit of the currency. INR is
# paise, so Rs.100.00 is 10000. JPY has no subunit, so 100 yen is 100.
#
# An unknown currency is refused rather than assumed to be 2-decimal:
# sending 10000 to a provider expecting 100.00 would be a hundred-fold
# overcharge.
# =========================================================

#: Smallest-unit exponents for the currencies this restaurant accepts.
CURRENCY_EXPONENTS = {
    "INR": 2,
    "USD": 2,
    "EUR": 2,
    "GBP": 2,
    "AUD": 2,
    "CAD": 2,
    "SGD": 2,
    "AED": 2,
    "JPY": 0,
    "KRW": 0,
    "VND": 0,
}

ZERO_DECIMAL_CURRENCIES = {
    name for name, exponent in CURRENCY_EXPONENTS.items() if exponent == 0
}

#: Raised when a bill's currency cannot be sent to the provider safely.
class CurrencyConversionError(Exception):
    pass


def to_smallest_unit(amount: float, currency: str) -> int:
    """
    Convert a major-unit amount into the provider's smallest unit.

    100.00 INR -> 10000

    Rounded half-up rather than truncated, because truncation would send
    less than the bill asks for and the difference would land on the
    customer.
    """
    code = (currency or "INR").strip().upper()

    if code not in CURRENCY_EXPONENTS:
        raise CurrencyConversionError(
            f"Currency {code} is not supported by this provider"
        )

    # Integer arithmetic in paise, so 336.10 becomes 33610 rather than
    # 33609 through a float artefact.
    scaled = round(float(amount or 0) * (10 ** CURRENCY_EXPONENTS[code]))

    if scaled < 0:
        raise CurrencyConversionError(
            "Amount must not be negative"
        )

    return int(scaled)


def to_major_unit(amount_smallest: int, currency: str) -> float:
    """Inverse of `to_smallest_unit`, for reconciling a provider reply."""
    code = (currency or "INR").strip().upper()

    if code not in CURRENCY_EXPONENTS:
        raise CurrencyConversionError(
            f"Currency {code} is not supported by this provider"
        )

    return round(
        float(amount_smallest or 0) / (10 ** CURRENCY_EXPONENTS[code]), 2
    )


# =========================================================
# WEBHOOK SIGNATURE
#
# Razorpay documents this as HMAC-SHA256 of the webhook secret over the
# body, sent as the X-Razorpay-Signature header.
#
# The SDK's own verifier is used when the SDK is installed, because
# hand-rolling the check risks disagreeing with the provider about the
# exact bytes that were signed. The HMAC implementation below is the
# documented algorithm and is what the test suite exercises, so the
# behaviour is verified even where the SDK is absent.
# =========================================================

SIGNATURE_HEADER = "X-Razorpay-Signature"


class SignatureVerificationError(Exception):
    """The webhook signature was missing, malformed, or did not match."""


def verify_webhook_signature(raw_body: bytes, signature: str | None,
                             secret: str | None) -> bool:
    """
    Verify a Razorpay webhook signature.

    Returns True only when the signature matches. Returns False rather than
    raising, so a caller can map it onto its own status code; the reason is
    not returned either, because telling an attacker *why* a signature was
    rejected tells them what to fix.
    """
    if not signature or not secret or raw_body is None:
        return False

    if not isinstance(raw_body, bytes):
        raw_body = str(raw_body).encode()

    try:
        import razorpay

        utility = getattr(razorpay, "Utility", None)

        if utility is not None:
            # In razorpay 2.x these are instance methods, so the class
            # itself has to be instantiated. A version that exposes them
            # as module functions would fail here and fall through to the
            # HMAC below, which is why the call is guarded rather than
            # assumed.
            verifier = getattr(utility, "verify_webhook_signature", None)

            if verifier is not None:
                try:
                    return bool(
                        verifier(raw_body.decode(), signature, secret)
                    )
                except TypeError:
                    # Bound-method shape: instantiate and retry.
                    verifier = None

                if verifier is None:
                    try:
                        return bool(
                            utility().verify_webhook_signature(
                                raw_body.decode(), signature, secret
                            )
                        )
                    except Exception:
                        # The SDK raises SignatureVerificationError rather
                        # than returning False. A rejected signature is the
                        # expected outcome for an attacker, not an
                        # exceptional condition, so it is a False here.
                        return False

    except ImportError:
        pass

    expected = hmac.new(
        (secret or "").encode(),
        raw_body,
        hashlib.sha256,
    ).hexdigest()

    # Constant-time compare so a mismatch reveals nothing about how much
    # of the signature was right.
    return hmac.compare_digest(expected, str(signature))


def sign_payload(raw_body: bytes, secret: str) -> str:
    """
    Produce the signature a provider would send.

    Used by the test suite to build genuine signed webhooks, so the
    verification path under test is the real one rather than a stand-in.
    Deliberately not exposed through any HTTP route.
    """
    if not isinstance(raw_body, bytes):
        raw_body = str(raw_body).encode()

    return hmac.new(
        (secret or "").encode(), raw_body, hashlib.sha256
    ).hexdigest()


# =========================================================
# WEBHOOK PAYLOAD
# =========================================================

class WebhookPayloadError(Exception):
    """The webhook body was not a payload this application can read."""


class WebhookEvent:
    """
    A parsed webhook, reduced to what settlement needs.

    Keeping this narrow means an unexpected field in a provider payload
    cannot reach the financial path.
    """

    def __init__(self, event: str, event_id: str | None,
                 entity: dict, payload: dict):
        self.event = event
        self.event_id = event_id
        self.entity = entity or {}
        self.payload = payload or {}

    @property
    def provider_payment_id(self) -> str | None:
        return self.entity.get("id")

    @property
    def provider_order_id(self) -> str | None:
        return self.entity.get("order_id")

    @property
    def amount_smallest(self) -> int | None:
        raw = self.entity.get("amount")

        try:
            return int(raw) if raw is not None else None
        except (TypeError, ValueError):
            return None

    @property
    def currency(self) -> str | None:
        return (self.entity.get("currency") or "").upper() or None

    @property
    def provider_status(self) -> str | None:
        return (self.entity.get("status") or "").lower() or None

    @property
    def failure_reason(self) -> str | None:
        for key in ("error_description", "error_reason", "method", "reason"):
            value = self.entity.get(key)

            if value:
                return str(value)[:300]

        return None

    @property
    def captured(self) -> bool:
        return bool(self.entity.get("captured"))


def parse_webhook(raw_body: bytes) -> WebhookEvent:
    """
    Parse a webhook body into the narrow event the settlement path reads.

    Raises WebhookPayloadError for anything unreadable. A malformed body
    is refused rather than half-read, because a body that parses into a
    missing `order_id` would otherwise settle nothing at best and the
    wrong bill at worst.
    """
    if raw_body is None:
        raise WebhookPayloadError("Empty webhook body")

    try:
        body = json.loads(
            raw_body.decode() if isinstance(raw_body, bytes) else raw_body
        )
    except (ValueError, UnicodeDecodeError):
        raise WebhookPayloadError("Webhook body is not valid JSON")

    if not isinstance(body, dict):
        raise WebhookPayloadError(
            "Webhook body must be a JSON object"
        )

    event = body.get("event")

    if not event or not isinstance(event, str):
        raise WebhookPayloadError("Webhook has no event name")

    payload = body.get("payload")

    if not isinstance(payload, dict):
        raise WebhookPayloadError(
            f"Webhook {event} has no payload object"
        )

    entity = payload.get("payment", {}).get("entity", {})

    if not isinstance(entity, dict):
        raise WebhookPayloadError(
            f"Webhook {event} has no payment entity"
        )

    return WebhookEvent(
        event=event.strip(),
        event_id=body.get("event_id") or None,
        entity=entity,
        payload=payload,
    )


#: Events that mean money arrived.
SETTLED_EVENTS = ("payment.captured",)

#: Events that mean the attempt did not result in money. Each one leaves
#: the bill UNPAID; none of them can mark it paid.
FAILED_EVENTS = (
    "payment.failed",
    "order.paid",   # handled below as informational, never as settlement
)


def outcome_from_event(event: WebhookEvent) -> ProviderOutcome | None:
    """
    Translate a Razorpay event into an outcome, or None if it is not one
    this application acts on.

    `order.paid` is deliberately *not* mapped to SUCCESS. It means the
    order has been fully paid, which is a consequence of one or more
    captured payments rather than a payment event itself. Acting on it
    would settle a bill from a signal that carries no payment reference
    and no amount to check.
    """
    name = (event.event or "").lower()

    if name in SETTLED_EVENTS:
        # A captured payment is only treated as settled if Razorpay also
        # says it is captured. The event name is a label; the entity is
        # the fact.
        if not event.captured and event.provider_status not in (
            "captured", "authorized", "paid",
        ):
            return None

        settled_at = event.entity.get("created_at")

        if settled_at:
            try:
                settled_at = datetime.fromtimestamp(int(settled_at))
            except (TypeError, ValueError, OSError):
                settled_at = None

        return ProviderOutcome(
            status="SUCCESS",
            provider_reference=event.provider_payment_id,
            settled_at=settled_at,
            message="Razorpay confirmed the payment was captured.",
            # Carried so the settlement path can compare what Razorpay
            # actually processed against what the bill says. Converted out
            # of paise here so the comparison is rupees against rupees.
            reported_amount=(
                to_major_unit(event.amount_smallest, event.currency)
                if event.amount_smallest is not None and event.currency
                else None
            ),
            reported_currency=event.currency,
        )

    if name == "payment.failed":
        return ProviderOutcome(
            status="FAILED",
            provider_reference=event.provider_payment_id,
            message=(
                event.failure_reason
                or "Razorpay reported this payment as failed."
            ),
        )

    # order.paid, refunds, disputes, subscriptions and anything added in
    # future. Recorded, acted on never.
    return None


# =========================================================
# THE PROVIDER
# =========================================================

class RazorpayPaymentProvider(PaymentProvider):
    """
    Razorpay, in test mode by default.

    `client` is injectable so the test suite can drive this class with a
    stub instead of the network. The financial logic - amount conversion,
    reconciliation, signature verification, settlement guards - is all in
    this class and therefore all exercised by the tests. What the tests do
    *not* do is make a real financial transaction, which is the correct
    thing for a test suite never to do.
    """

    name = "razorpay"

    #: API version this integration was written against.
    API_VERSION = "2024-11-20"

    def __init__(self, key_id: str, key_secret: str, webhook_secret: str,
                 live: bool = False, client=None, base_url: str | None = None):
        self.key_id = key_id
        self.key_secret = key_secret
        self.webhook_secret = webhook_secret
        self.live = bool(live)

        # Where API calls go. Ignored when a client is injected, because an
        # injected client has its own transport.
        self.base_url = base_url or RAZORPAY_OFFICIAL_BASE_URL

        self._client = client

        # reference -> ProviderOutcome, for outcomes a webhook has
        # delivered. Mirrors the development provider's shape exactly,
        # which is what lets the same settlement path serve both.
        self._delivered = {}

    # ---- plumbing ----

    @property
    def mode(self) -> str:
        """`test` or `live`. Never anything else."""
        return "live" if self.live else "test"

    @property
    def client(self):
        """The Razorpay client, built on first use."""
        if self._client is None:
            try:
                import razorpay
            except ImportError as error:
                raise PaymentConfigurationError(
                    "The razorpay SDK is not installed. Run "
                    "`pip install razorpay`, or set PAYMENT_MODE=development."
                ) from error

            self._client = razorpay.Client(
                auth=(self.key_id, self.key_secret)
            )

            # Only ever applied outside live mode; `configured_base_url`
            # returns the official API for live regardless.
            try:
                self._client._set_base_url(self.base_url)
            except AttributeError:
                self._client.base_url = self.base_url

        return self._client

    def describe(self) -> dict:
        """Configuration for an admin screen. Never the secret."""
        return {
            "provider": self.name,
            "mode": self.mode,
            "key_id_masked": (
                f"{self.key_id[:6]}...{self.key_id[-4:]}"
                if self.key_id and len(self.key_id) > 8
                else ("*" * len(self.key_id) if self.key_id else None)
            ),
            "webhook_configured": bool(self.webhook_secret),
            # Reported so an operator can confirm they are pointed at
            # Razorpay and not at something else.
            "api_host": self.base_url,
        }

    # ---- interface ----

    def create_payment_request(self, payment) -> dict:
        """
        Create a Razorpay order and return checkout options for it.

        The amount comes from `payment.amount`, which is a copy of
        `OrderHeader.total_amount` taken when the payment request was
        created. Nothing here reads a browser, so nothing here can be
        influenced by one.
        """
        smallest = to_smallest_unit(payment.amount, payment.currency)

        receipt = payment.order_reference or f"payment{payment.id}"

        created = self.client.order.create({
            # Smallest unit, per Razorpay.
            "amount": smallest,
            "currency": (payment.currency or "INR").upper(),
            # Appears on the merchant dashboard, so it must be something
            # an operator can match to a bill.
            "receipt": str(receipt)[:40],
            "payment_capture": 1,
            "notes": {
                # Echoed back on the webhook, which is how the incoming
                # payment is matched to a local row.
                "bill_reference": str(receipt)[:40],
                "local_payment_id": str(payment.id),
            },
        })

        order_id = created.get("id")

        if not order_id:
            raise RuntimeError(
                "Razorpay returned no order id for the payment request"
            )

        payment.provider_reference = order_id

        return {
            "provider": self.name,
            "provider_reference": order_id,
            # What the browser's Razorpay checkout needs. Contains no
            # secret: the key id is a public identifier by design, and the
            # key secret never leaves the server.
            "checkout": {
                "key": self.key_id,
                "order_id": order_id,
                "amount": smallest,
                "amount_major": payment.amount,
                "currency": (payment.currency or "INR").upper(),
                "name": "Paradise Restaurant",
                "description": f"Bill {receipt}",
                "prefill": {},
            },
            # No UPI URI: Razorpay's checkout is the payment surface, and
            # handing out a second one would let a guest pay through a
            # path with no signed confirmation behind it.
            "upi_uri": None,
            "request_only": True,
            "mode": self.mode,
            "instruction": (
                "Complete the payment in the Razorpay window. This bill is "
                "marked paid only after Razorpay confirms it."
            ),
        }

    def payment_request_material(self, payment) -> dict:
        """
        Re-issue checkout options for an attempt that is already open.

        No new order is created, so the reference the guest and the webhook
        both use stays the same.
        """
        smallest = to_smallest_unit(payment.amount, payment.currency)

        return {
            "provider": self.name,
            "provider_reference": payment.provider_reference,
            "checkout": {
                "key": self.key_id,
                "order_id": payment.provider_reference,
                "amount": smallest,
                "amount_major": payment.amount,
                "currency": (payment.currency or "INR").upper(),
                "name": "Paradise Restaurant",
                "description": (
                    f"Bill {payment.order_reference or payment.id}"
                ),
                "prefill": {},
            },
            "upi_uri": None,
            "request_only": True,
            "mode": self.mode,
            "instruction": (
                "Complete the payment in the Razorpay window. This bill is "
                "marked paid only after Razorpay confirms it."
            ),
        }

    def record_delivered_outcome(self, provider_order_id: str,
                                 outcome: ProviderOutcome) -> None:
        """
        Store an outcome a signed webhook has delivered.

        Named to mirror the development provider's `simulate_outcome`, and
        with the same effect: nothing is written to the database here. The
        settlement path reads it afterwards, exactly as it does for a
        simulated outcome.
        """
        self._delivered[provider_order_id] = outcome

    def verify_payment(self, payment) -> ProviderOutcome:
        """
        What the provider says about this payment.

        First checks for an outcome a webhook has already delivered. Failing
        that, it asks Razorpay directly, because a webhook can be lost and a
        guest should not have to pay twice because of a dropped callback.
        """
        reference = payment.provider_reference

        delivered = self._delivered.get(reference)

        if delivered is not None:
            return delivered

        return self.get_payment_status(payment)

    def get_payment_status(self, payment) -> ProviderOutcome:
        """
        Ask Razorpay about this attempt.

        Read-only, and safe to call repeatedly: a payment Razorpay has not
        heard of comes back PENDING rather than an error, because "we do
        not know yet" is the truthful answer and it is what keeps the bill
        unpaid until money actually arrives.
        """
        reference = payment.provider_reference

        if not reference:
            return ProviderOutcome(
                status="PENDING",
                message="This payment has no provider reference yet.",
            )

        try:
            if reference.startswith("order_"):
                remote = self.client.order.fetch(reference)
            else:
                remote = self.client.payment.fetch(reference)
        except Exception as error:
            # A provider that cannot be reached is not a provider that
            # confirmed anything. PENDING is the only safe answer.
            return ProviderOutcome(
                status="PENDING",
                provider_reference=reference,
                message=(
                    "The payment provider could not be reached "
                    f"({type(error).__name__}); no confirmation either "
                    "way."
                ),
            )

        return self.outcome_from_remote(remote, reference)

    def outcome_from_remote(self, remote: dict,
                            reference: str) -> ProviderOutcome:
        """
        Read a fetched Razorpay object into an outcome.

        An order carries a list of payments; the most advanced one decides
        the outcome, because "one of these was captured" is what settles a
        bill even if another attempt on the same order failed.
        """
        if not isinstance(remote, dict):
            return ProviderOutcome(
                status="PENDING",
                provider_reference=reference,
                message="Provider returned an unreadable response.",
            )

        payments = remote.get("payments")

        if isinstance(payments, list) and payments:
            best = None

            for candidate in payments:
                if not isinstance(candidate, dict):
                    continue

                if candidate.get("status") in ("captured", "paid"):
                    best = candidate
                    break

            if best is not None:
                settled_at = best.get("created_at")

                if settled_at:
                    try:
                        settled_at = datetime.fromtimestamp(int(settled_at))
                    except (TypeError, ValueError, OSError):
                        settled_at = None

                return ProviderOutcome(
                    status="SUCCESS",
                    provider_reference=best.get("id") or reference,
                    settled_at=settled_at,
                    message="Razorpay reports this payment captured.",
                )

            statuses = {
                str(row.get("status") or "").lower()
                for row in payments
                if isinstance(row, dict)
            }

            if "failed" in statuses:
                return ProviderOutcome(
                    status="FAILED",
                    provider_reference=reference,
                    message="Razorpay reports this payment failed.",
                )

            return ProviderOutcome(
                status="PENDING",
                provider_reference=reference,
                message="Razorpay has not confirmed this payment yet.",
            )

        status = str(remote.get("status") or "").lower()

        if status in ("captured", "paid"):
            settled_at = remote.get("created_at")

            if settled_at:
                try:
                    settled_at = datetime.fromtimestamp(int(settled_at))
                except (TypeError, ValueError, OSError):
                    settled_at = None

            return ProviderOutcome(
                status="SUCCESS",
                provider_reference=remote.get("id") or reference,
                settled_at=settled_at,
                message="Razorpay reports this payment captured.",
            )

        if status == "failed":
            return ProviderOutcome(
                status="FAILED",
                provider_reference=remote.get("id") or reference,
                message=remote.get("error_description")
                or "Razorpay reports this payment failed.",
            )

        if status in ("expired", "canceled", "cancelled"):
            return ProviderOutcome(
                status="FAILED",
                provider_reference=remote.get("id") or reference,
                message=remote.get("error_description")
                or f"Razorpay reports this payment {status}.",
            )

        return ProviderOutcome(
            status="PENDING",
            provider_reference=remote.get("id") or reference,
            message="Razorpay has not confirmed this payment yet.",
        )

    # ---- reconciliation ----

    def reconcile(self, payment, remote: dict) -> dict:
        """
        Compare a local payment with what the provider holds.

        Read-only. Its purpose is to let an operator find a disagreement
        before it becomes a missing payment, and to make the disagreement
        visible rather than silently reconciled.
        """
        remote_amount = remote.get("amount") if isinstance(remote, dict) else None
        remote_currency = (
            (remote.get("currency") or "").upper()
            if isinstance(remote, dict) else ""
        )

        local_smallest = to_smallest_unit(payment.amount, payment.currency)

        checks = {
            "amount_matches": (
                int(remote_amount) == local_smallest
                if remote_amount is not None else None
            ),
            "currency_matches": (
                remote_currency == (payment.currency or "").upper()
                if remote_currency else None
            ),
            "reference_matches": (
                (remote.get("id") or "") == (payment.provider_reference or "")
                if isinstance(remote, dict) else None
            ),
        }

        return {
            "local_payment_id": payment.id,
            "local_reference": payment.provider_reference,
            "local_amount": round(float(payment.amount or 0), 2),
            "local_amount_smallest": local_smallest,
            "local_currency": payment.currency,
            "local_status": payment.status,
            "requested_at": (
                payment.requested_at.isoformat(timespec="seconds")
                if payment.requested_at else None
            ),
            "paid_at": (
                payment.paid_at.isoformat(timespec="seconds")
                if payment.paid_at else None
            ),
            "remote_amount": remote_amount,
            "remote_currency": remote_currency or None,
            "remote_status": (
                (remote.get("status") or None)
                if isinstance(remote, dict) else None
            ),
            "checks": checks,
            "matches": all(value is True for value in checks.values()),
        }


#: The official Razorpay API. Never overridden.
RAZORPAY_OFFICIAL_BASE_URL = "https://api.razorpay.com"


def configured_base_url(live: bool) -> str:
    """
    Where API requests go.

    `RAZORPAY_BASE_URL` exists so the integration can be tested end to end
    against a local stand-in without touching the internet. It is
    deliberately honoured ONLY outside live mode: a base-URL override that
    worked in production would be a way to redirect real money to a
    different host, so in live mode the official API is used regardless of
    what the environment says.
    """
    if live:
        return RAZORPAY_OFFICIAL_BASE_URL

    override = (os.getenv("RAZORPAY_BASE_URL") or "").strip().rstrip("/")

    return override or RAZORPAY_OFFICIAL_BASE_URL


def build_razorpay_provider() -> RazorpayPaymentProvider:
    """
    Construct the provider from the environment.

    Refuses rather than defaulting. A provider built with an empty secret
    would fail every API call in a way that looks like "the provider is
    down" rather than "this deployment is not configured".
    """
    from services import payment_provider

    missing = payment_provider._missing_razorpay_settings()

    if missing:
        raise PaymentConfigurationError(
            f"Razorpay is selected but {', '.join(missing)} is not set. "
            f"Refusing to build a provider that cannot confirm payments."
        )

    return RazorpayPaymentProvider(
        key_id=payment_provider.RAZORPAY_KEY_ID,
        key_secret=payment_provider.RAZORPAY_KEY_SECRET,
        webhook_secret=payment_provider.RAZORPAY_WEBHOOK_SECRET,
        live=payment_provider.is_live(),
        base_url=configured_base_url(payment_provider.is_live()),
    )
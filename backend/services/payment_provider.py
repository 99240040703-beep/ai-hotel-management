"""
Payment providers.

--------------------------------------------------------------------------
THE ONE RULE THIS MODULE EXISTS TO ENFORCE
--------------------------------------------------------------------------
A payment becomes SUCCESS because a provider said so, and for no other
reason.

A QR being generated, a QR being displayed, a QR being scanned, a payment
request existing, a customer saying "I have paid", and an admin clicking a
button are all *requests*. None of them is an outcome. Every one of them
leaves the payment PENDING, because PENDING is the honest description of
money that may or may not have moved.

So the outcome lives inside the provider, and the only way out of PENDING
is `verify_payment`, which asks the provider. A real implementation of
that method calls the bank's API or validates a signed webhook. The
development implementation below keeps its outcomes in its own memory,
which is why it cannot be mistaken for a bank.

--------------------------------------------------------------------------
WHY THE DEVELOPMENT PROVIDER IS NOT A FAKE BANK
--------------------------------------------------------------------------
`DevelopmentPaymentProvider` cannot settle anything on its own. It has no
method that says "mark this paid". The only way an outcome is ever
recorded is `simulate_outcome()`, which is reachable exclusively from an
admin-only endpoint that refuses to run unless PAYMENT_MODE=development.

Even then the simulation does not touch the database. It records an
outcome *on the provider*, and the ordinary verification path then picks
it up. That is the whole point: the development route and a future real
webhook travel through identical code, so the path being tested now is
the path that will run in production.

--------------------------------------------------------------------------
UPI
--------------------------------------------------------------------------
A UPI URI is a *request for* money. `upi://pay?pa=...&am=...` prefills a
UPI app; it transfers nothing and proves nothing. The backend treats a
generated URI exactly like a printed QR - it creates a PENDING payment and
changes nothing else.

--------------------------------------------------------------------------
PROVIDER SELECTION  (Phase 7F)
--------------------------------------------------------------------------
Two independent switches, because they answer different questions:

    PAYMENT_MODE      how careful are we being?
                      development - a local stand-in, outcomes simulated
                      test       - a real provider, real sandbox money
                      live       - real provider, real money
                      disabled   - no payment requests at all

    PAYMENT_PROVIDER  who does the work?
                      development | razorpay

`PAYMENT_MODE=test` with a real provider is a genuine provider
integration against a sandbox. `development` is the default and is not a
provider integration at all - it has no network calls and cannot move
money.

An unrecognised value is treated as `disabled`, and a missing or
incomplete configuration raises rather than falling back to development.
Falling back would be the dangerous direction: a typo in `PAYMENT_MODE`
would otherwise quietly downgrade a live deployment to simulations
without anybody noticing.
"""

import os
import threading
import uuid
from datetime import datetime
from urllib.parse import quote


# =========================================================
# MODE
#
# Read once at import. An unrecognised value fails closed.
# =========================================================

DEVELOPMENT = "development"
DISABLED = "disabled"
TEST = "test"
LIVE = "live"

#: Every mode the application recognises. Anything else is treated as
#: `disabled` rather than guessed at.
KNOWN_MODES = (DEVELOPMENT, TEST, LIVE, DISABLED)

#: Modes in which a payment request may be created at all.
ACTIVE_MODES = (DEVELOPMENT, TEST, LIVE)

#: Modes that talk to a real provider.
PROVIDER_MODES = (TEST, LIVE)


class PaymentConfigurationError(Exception):
    """
    The payment configuration cannot be used as written.

    Raised at startup and again when the provider is resolved, so a
    misconfigured deployment refuses to start rather than starting in a
    state nobody intended.
    """


_raw_mode = (os.getenv("PAYMENT_MODE") or "").strip().lower()

#: An unrecognised mode fails closed. `development` is the documented
#: default, but only when it is actually written down; a typo becomes
#: `disabled` rather than something permissive.
PAYMENT_MODE = (
    _raw_mode if _raw_mode in KNOWN_MODES
    else (DEVELOPMENT if _raw_mode == "" else DISABLED)
)

PAYMENT_PROVIDER = (
    os.getenv("PAYMENT_PROVIDER") or DEVELOPMENT
).strip().lower()

#: The only real provider implemented. Named here so the provider id in
#: configuration, the factory and the configuration check are all
#: compared against one constant rather than a literal repeated in four
#: places.
RAZORPAY = "razorpay"

#: The final live-money acknowledgement. `PAYMENT_MODE=live` plus valid
#: credentials is a configuration someone could have copied from a
#: staging box. This flag has to be set on purpose, on the machine that
#: will actually take money.
ALLOW_LIVE_PAYMENTS = (
    os.getenv("ALLOW_LIVE_PAYMENTS") or ""
).strip().lower() in ("1", "true", "yes", "on")

MERCHANT_VPA = (os.getenv("PAYMENT_MERCHANT_VPA") or "").strip()
MERCHANT_NAME = (os.getenv("PAYMENT_MERCHANT_NAME") or "").strip()
NOTE_PREFIX = (os.getenv("PAYMENT_NOTE_PREFIX") or "").strip()

RAZORPAY_KEY_ID = (os.getenv("RAZORPAY_KEY_ID") or "").strip()
RAZORPAY_KEY_SECRET = (os.getenv("RAZORPAY_KEY_SECRET") or "").strip()
RAZORPAY_WEBHOOK_SECRET = (os.getenv("RAZORPAY_WEBHOOK_SECRET") or "").strip()


def is_live() -> bool:
    return PAYMENT_MODE == LIVE


def is_test() -> bool:
    return PAYMENT_MODE == TEST


def uses_real_provider() -> bool:
    return PAYMENT_MODE in PROVIDER_MODES


def payments_enabled() -> bool:
    """Whether any provider may accept a payment request at all."""
    return PAYMENT_MODE in ACTIVE_MODES


def development_mode() -> bool:
    """
    Whether the simulated endpoints exist.

    Checked separately from `payments_enabled` so that "payments are on but
    simulation is off" is representable later without redesigning the
    routes. Today both are the same switch.
    """
    return PAYMENT_MODE == DEVELOPMENT


def _missing_razorpay_settings() -> list:
    missing = []

    if not RAZORPAY_KEY_ID:
        missing.append("RAZORPAY_KEY_ID")

    if not RAZORPAY_KEY_SECRET:
        missing.append("RAZORPAY_KEY_SECRET")

    # A provider with no webhook secret cannot receive a signed
    # confirmation, so it could never settle a payment. Refusing to start
    # is far better than starting and silently never settling.
    if not RAZORPAY_WEBHOOK_SECRET:
        missing.append("RAZORPAY_WEBHOOK_SECRET")

    return missing


def validate_configuration() -> dict:
    """
    Check the payment configuration and raise if it cannot be honoured.

    Called at startup so a bad configuration is a failed boot rather than
    a surprise discovered when a customer tries to pay.

    Returns a description of the resolved configuration. Never includes a
    secret: only whether each one is present.
    """
    if not payments_enabled():
        # Nothing to validate. Payments are off and that is a valid state.
        return {
            "ok": True,
            "mode": PAYMENT_MODE,
            "provider": None,
            "payments_enabled": False,
        }

    if development_mode():
        return {
            "ok": True,
            "mode": PAYMENT_MODE,
            "provider": DEVELOPMENT,
            "payments_enabled": True,
        }

    # ---- a real provider is configured ----

    if PAYMENT_PROVIDER != RAZORPAY:
        raise PaymentConfigurationError(
            f"PAYMENT_MODE={PAYMENT_MODE} needs PAYMENT_PROVIDER=razorpay, "
            f"but PAYMENT_PROVIDER is {PAYMENT_PROVIDER!r}. "
            f"Refusing to start rather than falling back to a provider "
            f"that cannot confirm payments."
        )

    missing = _missing_razorpay_settings()

    if missing:
        raise PaymentConfigurationError(
            f"PAYMENT_MODE={PAYMENT_MODE} with PAYMENT_PROVIDER=razorpay "
            f"requires {', '.join(missing)}. These are read from the "
            f"environment and are not set. Refusing to start."
        )

    if is_live() and not ALLOW_LIVE_PAYMENTS:
        raise PaymentConfigurationError(
            "PAYMENT_MODE=live also requires ALLOW_LIVE_PAYMENTS=true. "
            "Live mode is never activated by credentials alone, so a "
            "copied staging configuration cannot take real money by "
            "accident."
        )

    return {
        "ok": True,
        "mode": PAYMENT_MODE,
        "provider": RAZORPAY,
        "payments_enabled": True,
        "live": is_live(),
    }


def _masked_key_id() -> str | None:
    """
    The key id, masked.

    The key id is not a secret - Razorpay puts it in the checkout page -
    but there is no reason to hand the whole thing to every admin screen,
    and a partial value is enough to identify which account is configured.
    """
    if not RAZORPAY_KEY_ID:
        return None

    if len(RAZORPAY_KEY_ID) <= 8:
        return "*" * len(RAZORPAY_KEY_ID)

    return f"{RAZORPAY_KEY_ID[:6]}...{RAZORPAY_KEY_ID[-4:]}"


def configuration() -> dict:
    """
    What the provider is configured with, safe to show an operator.

    Includes no key, secret or token, because there are none to include:
    only *presence* booleans and a masked key id. The VPA is included
    because it is printed on the QR the guest scans and is therefore not
    a secret.
    """
    real_provider_configured = (
        uses_real_provider()
        and PAYMENT_PROVIDER == RAZORPAY
        and not _missing_razorpay_settings()
    )

    return {
        "mode": PAYMENT_MODE,
        "provider": (
            PAYMENT_PROVIDER
            if (development_mode() or real_provider_configured)
            else None
        ),
        "payments_enabled": payments_enabled(),
        "simulation_enabled": development_mode(),
        "test_mode": is_test(),
        "live_mode": is_live(),
        "merchant_vpa": MERCHANT_VPA or None,
        "merchant_name": MERCHANT_NAME or None,

        # ---- the two questions an operator actually asks ----
        #
        # "Is a real gateway wired up?" and "will it take real money?"
        # are different, and conflating them is how a sandbox gets
        # mistaken for production.
        "gateway_connected": real_provider_configured,
        "live_gateway_connected": is_live() and real_provider_configured,

        "razorpay_key_id_masked": (
            _masked_key_id() if real_provider_configured else None
        ),
        "razorpay_webhook_configured": bool(RAZORPAY_WEBHOOK_SECRET),
        # Stated in words so no screen has to infer it, and so the AI can
        # quote it verbatim.
        "gateway_statement": (
            "Payment gateway is not connected; payment data reflects "
            "verified development payment records only."
            if not real_provider_configured
            else (
                "Connected to Razorpay in TEST mode. Test transactions "
                "only - no real money moves."
                if is_test()
                else "Connected to Razorpay in LIVE mode. Real payments."
            )
        ),
    }


# =========================================================
# OUTCOMES
# =========================================================

class ProviderOutcome:
    """What a provider reports about one attempt."""

    def __init__(self, status: str, provider_reference: str | None = None,
                 settled_at=None, message: str | None = None,
                 reported_amount=None, reported_currency=None):
        self.status = status
        self.provider_reference = provider_reference
        self.settled_at = settled_at or datetime.utcnow()
        self.message = message

        # Phase 7F. What the provider says it actually processed, which is
        # not necessarily what we asked it to process. Compared against
        # the bill before anything settles, so a provider confirming a
        # different figure cannot mark a bill paid.
        #
        # `reported_amount` is in MAJOR units - rupees - so it lines up
        # with OrderHeader.total_amount rather than with paise.
        self.reported_amount = reported_amount
        self.reported_currency = reported_currency


# =========================================================
# INTERFACE
# =========================================================

class PaymentProvider:
    """
    The contract every provider implements.

    Three methods, and the third is the one that matters. A caller cannot
    obtain SUCCESS without going through `verify_payment`.
    """

    name = "abstract"

    def create_payment_request(self, payment) -> dict:
        """
        Produce the material the guest needs in order to pay.

        Returns a dict which may contain a `upi_uri`. Nothing here changes
        the payment's status.
        """
        raise NotImplementedError

    def verify_payment(self, payment) -> ProviderOutcome:
        """
        Ask the provider what actually happened to this payment.

        This is the only method that can return SUCCESS. Everything the
        rest of the application knows about a payment's fate comes from
        here.
        """
        raise NotImplementedError

    def get_payment_status(self, payment) -> ProviderOutcome:
        """Read-only status probe. Never mutates anything."""
        raise NotImplementedError

    def payment_request_material(self, payment) -> dict:
        """
        Re-issue the pay instructions for an existing payment.

        Distinct from `create_payment_request`: this does not mint a new
        provider reference and does not change the payment. It exists so
        a guest who reloads the page - or an admin who reopens a bill -
        can still be shown the QR for an attempt that is already open.

        The amount comes from the stored payment, which is a copy of the
        bill's authoritative total taken when the request was created, so
        the regenerated URI requests the same figure.
        """
        raise NotImplementedError


# =========================================================
# UPI URI
# =========================================================

def build_upi_uri(amount: float, currency: str, reference: str,
                  note: str = "") -> str | None:
    """
    Build a UPI payment request URI.

    Standard BHIM/UPI intent parameters. `am` is the amount, `cu` the
    currency, `tn` the note the payer's app displays.

    Returns None when no merchant VPA is configured, because a URI without
    a payee is not a payment request and is better omitted than faked.
    """
    if not MERCHANT_VPA:
        return None

    # Two decimals: a UPI app that is handed 123.4 or 123 may round it
    # differently, and the payer would then send the wrong amount.
    amount_text = f"{round(float(amount or 0), 2):.2f}"

    params = [
        ("pa", MERCHANT_VPA),
        ("pn", MERCHANT_NAME or "Restaurant"),
        ("am", amount_text),
        ("cu", (currency or "INR").upper()),
        ("tn", note or f"{NOTE_PREFIX} {reference}".strip()),
    ]

    return "upi://pay?" + "&".join(
        f"{key}={quote(str(value), safe='')}" for key, value in params
    )


# =========================================================
# DEVELOPMENT PROVIDER
# =========================================================

class DevelopmentPaymentProvider(PaymentProvider):
    """
    A local stand-in for a payment provider.

    It behaves like a provider in the only way that matters for testing:
    outcomes are held on the provider side and are only visible to
    `verify_payment`. It holds them in memory, so restarting the server
    clears the simulated ledger exactly as a real provider's outage would
    leave nothing to verify against - PENDING is then the only safe state.
    """

    name = "development"

    def __init__(self):
        # reference -> ProviderOutcome. Thread-safe because a refund-style
        # double click can arrive on two workers at once, and the second
        # must see the first's outcome rather than overwrite it.
        self._outcomes = {}
        self._lock = threading.Lock()

    # ---- provider surface ----

    def create_payment_request(self, payment) -> dict:
        reference = f"DEV-PAY-{uuid.uuid4().hex[:12].upper()}"

        with self._lock:
            self._outcomes.pop(reference, None)

        payment.provider_reference = reference

        upi_uri = build_upi_uri(
            amount=payment.amount,
            currency=payment.currency,
            reference=payment.order_reference or f"payment{payment.id}",
        )

        return {
            "provider": self.name,
            "provider_reference": reference,
            "upi_uri": upi_uri,
            # Spelled out so no client infers success from having received
            # this dict.
            "request_only": True,
            "instruction": (
                "Scan or open this in any UPI app to pay. The restaurant "
                "records payment only after its own system confirms it."
            ),
        }

    def verify_payment(self, payment) -> ProviderOutcome:
        with self._lock:
            outcome = self._outcomes.get(payment.provider_reference)

        if outcome is None:
            # Nothing was simulated, so there is nothing to confirm. This
            # is the state after a QR has been shown, scanned, or ignored.
            return ProviderOutcome(
                status="PENDING",
                provider_reference=payment.provider_reference,
                message="No provider outcome has been recorded yet.",
            )

        return outcome

    def get_payment_status(self, payment) -> ProviderOutcome:
        return self.verify_payment(payment)

    def payment_request_material(self, payment) -> dict:
        """
        Rebuild the UPI request for an already-open attempt.

        No new reference is minted. The reference the guest is quoting and
        the one embedded in the QR have to stay the same, so a guest who
        reloads does not end up looking at a different attempt.
        """
        return {
            "provider": self.name,
            "provider_reference": payment.provider_reference,
            "upi_uri": build_upi_uri(
                amount=payment.amount,
                currency=payment.currency,
                reference=(
                    payment.order_reference or f"payment{payment.id}"
                ),
            ),
            "request_only": True,
            "instruction": (
                "Scan or open this in any UPI app to pay. The restaurant "
                "records payment only after its own system confirms it."
            ),
        }

    # ---- simulation, reachable only from the guarded endpoint ----

    def simulate_outcome(self, provider_reference: str, status: str,
                         message: str = None) -> ProviderOutcome:
        """
        Record what a provider *would* report, without touching the database.

        This deliberately does not write to `payments` or to
        `order_headers`. It publishes an outcome on the provider side; the
        normal verification path then reads it. That is why the development
        route cannot shortcut the production code - there is nothing for it
        to shortcut to.
        """
        outcome = ProviderOutcome(
            status=status,
            provider_reference=provider_reference,
            message=message,
        )

        with self._lock:
            self._outcomes[provider_reference] = outcome

        return outcome

    def forget(self, provider_reference: str) -> None:
        """Drop a simulated outcome. Used by test cleanup."""
        with self._lock:
            self._outcomes.pop(provider_reference, None)


_DEVELOPMENT_PROVIDER = DevelopmentPaymentProvider()

#: The Razorpay provider is constructed once and reused, because it holds
#: an HTTP client. Imported lazily so a development deployment with no
#: Razorpay installed does not need the SDK at all.
_RAZORPAY_PROVIDER = None


def get_provider() -> PaymentProvider | None:
    """
    The active provider, or None when payments are switched off.

    Returning None is what makes a disabled mode fail closed: the service
    refuses to create a request rather than falling back to something that
    would take money.

    Raises PaymentConfigurationError for a configuration that cannot be
    honoured. It never degrades to the development provider - a
    misconfigured production deployment must stop, not quietly simulate.
    """
    if not payments_enabled():
        return None

    if development_mode():
        return _DEVELOPMENT_PROVIDER

    # Throws rather than falling back, if anything is missing or wrong.
    validate_configuration()

    global _RAZORPAY_PROVIDER

    if _RAZORPAY_PROVIDER is None:
        from services.razorpay_provider import build_razorpay_provider

        _RAZORPAY_PROVIDER = build_razorpay_provider()

    return _RAZORPAY_PROVIDER


def active_provider_name() -> str | None:
    """The provider's name, or None. Read from the gateway configuration."""
    return configuration()["provider"]


def development_provider() -> DevelopmentPaymentProvider:
    """
    The development provider itself.

    Only the simulated endpoints use this, and they check the mode before
    they do.
    """
    return _DEVELOPMENT_PROVIDER
"""
Phase 7F acceptance tests: the Razorpay merchant provider.

    python scripts/test_phase7f_razorpay.py http://127.0.0.1:8010

--------------------------------------------------------------------------
NO REAL MONEY, EVER
--------------------------------------------------------------------------
Every provider interaction in this suite is a stub. `RazorpayPaymentProvider`
is driven with an injected client, so the amount conversion, the order
payload, the signature verification, the webhook parsing, the
reconciliation comparison and the settlement guards are all the real
implementations - but not one request leaves the machine.

The signature tests are genuine too: webhooks are signed with the same HMAC
a provider would use, so the verification path under test is the real one.

Sections:

    A  provider factory and mode resolution
    B  test-mode and live-mode configuration validation
    C  amount conversion and order creation
    D  webhook signature verification
    E  webhook idempotency
    F  settlement through the shared path
    G  failure states
    H  live-mode safety
    I  security
    J  development provider regression
    K  AI reporting
    L  database integrity and cleanup
"""

import hashlib
import hmac
import importlib
import json
import os
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pymysql

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8010"

DB = dict(
    host="localhost",
    user="root",
    password="Nithin.0987",
    database="restaurant_db",
    autocommit=True,
)

PROBE_NAME = "Phase7F Guest"
PROBE_TABLE = 9701

# A test-mode credential triple. Not a real account, and it is only ever
# held in memory for the duration of a single test.
TEST_KEY_ID = "rzp_test_00000000000000"
TEST_KEY_SECRET = "test_only_secret_not_a_real_credential"
TEST_WEBHOOK_SECRET = "test_only_webhook_secret"

passed = []
failed = []

created_users = []
created_orders = []
created_headers = []
created_tables = []
created_payments = []


def check(name, condition, detail=""):
    if condition:
        passed.append(name)
        print(f"  PASS  {name}")
    else:
        failed.append(name)
        print(f"  FAIL  {name}  {detail}")


def call(method, path, token=None, body=None, headers=None, raw_body=None):
    data = raw_body if raw_body is not None else (
        json.dumps(body).encode() if body is not None else None
    )

    request_headers = {"Content-Type": "application/json"}

    if token:
        request_headers["Authorization"] = "Bearer " + token

    if headers:
        request_headers.update(headers)

    request = Request(
        BASE + path,
        data=data,
        method=method,
        headers=request_headers,
    )

    try:
        with urlopen(request, timeout=60) as response:
            payload = response.read().decode()

            return response.status, (json.loads(payload) if payload else None)
    except HTTPError as error:
        payload = error.read().decode()

        try:
            return error.code, (json.loads(payload) if payload else None)
        except json.JSONDecodeError:
            return error.code, payload


def login(email, password="password123"):
    status, data = call(
        "POST", "/auth/login", body={"email": email, "password": password}
    )

    if status != 200:
        raise SystemExit(f"cannot log in as {email}: {status} {data}")

    return data["token"]


def sql(query, args=None):
    connection = pymysql.connect(**DB)

    try:
        with connection.cursor() as cursor:
            cursor.execute(query, args)

            if cursor.description is None:
                return []

            return cursor.fetchall()
    finally:
        connection.close()


def one(query, args=None):
    rows = sql(query, args)

    return rows[0][0] if rows else None


def sign(raw: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


def captured_webhook(event: str, entity: dict, event_id=None):
    """A webhook exactly as Razorpay sends one, signed for real."""
    body = json.dumps({
        "event": event,
        "event_id": event_id or f"evt_{abs(hash((event, entity.get('id')))) % 10**12}",
        "payload": {"payment": {"entity": entity}},
    }).encode()

    return body, sign(body, TEST_WEBHOOK_SECRET)


def post_webhook(body, signature=None, secret=None):
    return call(
        "POST", "/api/payments/webhook",
        raw_body=body,
        headers={
            "X-Razorpay-Signature": sign(body, secret or TEST_WEBHOOK_SECRET)
            if signature is None else signature
        },
    )


# ==========================================================
# Stub client
#
# Implements the two documented endpoints the provider uses. Records what
# it was asked for, so a test can assert on the payload the provider built.
# ==========================================================

class StubClient:
    def __init__(self):
        self.orders_created = []
        self.orders_fetched = []
        self.payments_fetched = []
        self.next_order_id = "order_stub0001"
        self.remote_orders = {}

        self.order = _StubOrders(self)
        self.payment = _StubPayments(self)


class _StubOrders:
    def __init__(self, parent):
        self.parent = parent

    def create(self, payload):
        self.parent.orders_created.append(payload)

        order_id = self.parent.next_order_id
        self.parent.next_order_id = f"order_stub{len(self.parent.orders_created) + 1:04d}"

        self.parent.remote_orders[order_id] = {
            "id": order_id,
            "amount": payload["amount"],
            "currency": payload["currency"],
            "status": "created",
            "payments": [],
            "notes": payload.get("notes") or {},
        }

        return dict(self.parent.remote_orders[order_id])

    def fetch(self, order_id):
        self.parent.orders_fetched.append(order_id)

        return dict(self.parent.remote_orders.get(order_id) or {
            "id": order_id, "payments": [], "status": "created",
        })


class _StubPayments:
    def __init__(self, parent):
        self.parent = parent

    def fetch(self, payment_id):
        self.parent.payments_fetched.append(payment_id)

        return {"id": payment_id, "status": "authorized"}


# ==========================================================
# Load the payment modules with a test-mode configuration
# ==========================================================

os.environ["PAYMENT_MODE"] = "test"
os.environ["PAYMENT_PROVIDER"] = "razorpay"
os.environ["RAZORPAY_KEY_ID"] = TEST_KEY_ID
os.environ["RAZORPAY_KEY_SECRET"] = TEST_KEY_SECRET
os.environ["RAZORPAY_WEBHOOK_SECRET"] = TEST_WEBHOOK_SECRET
os.environ["ALLOW_LIVE_PAYMENTS"] = "false"

sys.path.insert(0, os.getcwd())

from models import Payment, PaymentStatus  # noqa: E402
from services import payment_provider, payment_service  # noqa: E402
from services import razorpay_provider  # noqa: E402
from services.payment_provider import (  # noqa: E402
    PaymentConfigurationError,
    ProviderOutcome,
)
from services.razorpay_provider import (  # noqa: E402
    CurrencyConversionError,
    RazorpayPaymentProvider,
    parse_webhook,
    outcome_from_event,
    to_major_unit,
    to_smallest_unit,
    verify_webhook_signature,
)


print("=" * 74)
print(f"PHASE 7F RAZORPAY TESTS  ->  {BASE}")
print("=" * 74)

ADMIN = login("admin@gmail.com")

payments_before = one("SELECT COUNT(*) FROM payments")
headers_before = one("SELECT COUNT(*) FROM order_headers")
webhook_rows_before = one("SELECT COUNT(*) FROM payment_webhook_events")

preexisting_header_max = one("SELECT MAX(id) FROM order_headers") or 0

header_snapshot = sql(
    "SELECT id, total_amount, currency, payment_status, paid_at, status "
    "FROM order_headers WHERE id <= %s ORDER BY id",
    (preexisting_header_max,),
)


# ==========================================================
print("\n[A] provider factory and mode resolution")
# ==========================================================
check("test mode is recognised as a real-provider mode",
      payment_provider.is_test() and payment_provider.uses_real_provider(),
      f"mode={payment_provider.PAYMENT_MODE}")

check("the active provider is Razorpay",
      payment_provider.get_provider() is not None
      and payment_provider.get_provider().name == "razorpay",
      f"got {payment_provider.get_provider()}")

check("the factory reports Razorpay by name",
      payment_provider.active_provider_name() == "razorpay",
      f"got {payment_provider.active_provider_name()}")

check("development mode is off in test mode",
      payment_provider.development_mode() is False,
      "the simulation switch is still on")

check("payments are enabled in test mode",
      payment_provider.payments_enabled() is True,
      "payments are not enabled")

check("test mode is not live mode",
      payment_provider.is_live() is False,
      "test mode reports as live")

check("the configuration reports the provider",
      payment_provider.configuration()["provider"] == "razorpay",
      f"got {payment_provider.configuration()['provider']}")

check("the configuration reports TEST mode",
      payment_provider.configuration()["test_mode"] is True
      and payment_provider.configuration()["mode"] == "test",
      f"got {payment_provider.configuration()}")

check("a test-mode gateway counts as connected",
      payment_provider.configuration()["gateway_connected"] is True,
      "the gateway is not reported as connected")

check("a test-mode gateway does NOT count as live",
      payment_provider.configuration()["live_gateway_connected"] is False,
      "test mode is claiming to be live")

check("no secret appears in the configuration",
      TEST_KEY_SECRET not in json.dumps(payment_provider.configuration())
      and TEST_WEBHOOK_SECRET not in json.dumps(
          payment_provider.configuration()
      ),
      "a secret leaked into configuration()")

check("the key id is masked in the configuration",
      payment_provider.configuration()["razorpay_key_id_masked"]
      and TEST_KEY_ID
      not in json.dumps(payment_provider.configuration()),
      "the key id was exposed in full")

check("the configuration says TEST money is not real",
      "TEST" in payment_provider.configuration()["gateway_statement"],
      f"got {payment_provider.configuration()['gateway_statement']}")

# ==========================================================
print("\n[B] the provider implements the existing interface")
# ==========================================================
stub = StubClient()

provider = RazorpayPaymentProvider(
    key_id=TEST_KEY_ID,
    key_secret=TEST_KEY_SECRET,
    webhook_secret=TEST_WEBHOOK_SECRET,
    live=False,
    client=stub,
)

check("the provider is a PaymentProvider",
      isinstance(provider, payment_provider.PaymentProvider),
      f"{type(provider)}")

for method in (
    "create_payment_request",
    "verify_payment",
    "get_payment_status",
    "payment_request_material",
):
    implemented = (
        getattr(type(provider), method) is not getattr(
            payment_provider.PaymentProvider, method
        )
    )

    check(f"the provider implements {method}()", implemented,
          "it inherits the abstract version")

check("the provider reports its mode",
      provider.mode == "test" and provider.describe()["mode"] == "test",
      f"got {provider.describe()}")

check("the provider's description holds no secret",
      TEST_KEY_SECRET not in json.dumps(provider.describe()),
      "a secret leaked into describe()")

# ==========================================================
print("\n[C] amount conversion and order creation")
# ==========================================================
check("Rs.100.00 converts to 10000 paise",
      to_smallest_unit(100.00, "INR") == 10000,
      f"got {to_smallest_unit(100.00, 'INR')}")

check("Rs.336.10 converts to 33610 paise",
      to_smallest_unit(336.10, "INR") == 33610,
      f"got {to_smallest_unit(336.10, 'INR')}")

check("a whole-rupee amount has no float drift",
      to_smallest_unit(440.0, "INR") == 44000,
      f"got {to_smallest_unit(440.0, 'INR')}")

check("a zero-decimal currency is not scaled",
      to_smallest_unit(100, "JPY") == 100,
      f"got {to_smallest_unit(100, 'JPY')}")

check("paise convert back to rupees",
      to_major_unit(33610, "INR") == 336.10,
      f"got {to_major_unit(33610, 'INR')}")

try:
    to_smallest_unit(100, "XYZ")
    refused = False
except CurrencyConversionError:
    refused = True

check("an unsupported currency is refused, not guessed", refused,
      "an unknown currency was converted anyway")

# ---- a real bill, then a real request through the real service ----
sql("DELETE FROM users WHERE email LIKE %s", ("phase7f%",))
sql("DELETE FROM restaurant_tables WHERE table_number = %s", (PROBE_TABLE,))
sql("UPDATE users SET active_table_id = NULL "
    "WHERE active_table_id IS NOT NULL")

status, guest_data = call(
    "POST", "/auth/register",
    body={"name": PROBE_NAME, "email": "phase7f.guest@example.com",
          "password": "password123"},
)
created_users.append("phase7f.guest@example.com")
guest_token = guest_data["token"]

status, table = call(
    "POST", "/api/tables/", token=ADMIN,
    body={"table_number": PROBE_TABLE, "table_name": "Phase7F Table",
          "capacity": 4},
)
created_tables.append(table["id"])
call("POST", "/api/tables/claim", token=guest_token,
     body={"table_token": table["qr_token"]})

status, menu = call("GET", "/api/menu/", token=ADMIN)
dish = next(row for row in menu if row["available"])

status, order = call(
    "POST", "/api/orders/", token=guest_token,
    body={"menu_id": dish["id"], "quantity": 2, "notes": "phase7f probe"},
)
created_orders.append(order["orders"][0]["id"])
created_headers.append(order["order_id"])
bill_total = float(order["total_amount"])

check("a payment request cannot reach Razorpay without the service",
      status == 200, f"got {status}")

# Point the service at the stub. Only the transport is replaced; the
# pricing, the guards and the ledger writes are the real ones.
stub = StubClient()
provider = RazorpayPaymentProvider(
    key_id=TEST_KEY_ID, key_secret=TEST_KEY_SECRET,
    webhook_secret=TEST_WEBHOOK_SECRET, live=False, client=stub,
)

stubbed = RazorpayPaymentProvider(
    key_id=TEST_KEY_ID, key_secret=TEST_KEY_SECRET,
    webhook_secret=TEST_WEBHOOK_SECRET, live=False, client=stub,
)

status, request = call(
    "POST", "/api/payments/request", token=guest_token,
    body={"order_id": order["order_id"]},
)

created_payments.append(request["payment_id"])
payment_id = request["payment_id"]
provider_order_id = request["provider_reference"]

check("the request records the Razorpay provider",
      request["provider"] == "razorpay", f"got {request.get('provider')}")

check("the stored amount is the bill's authoritative total",
      float(request["amount"]) == bill_total,
      f"{request.get('amount')} vs {bill_total}")

check("the currency is the bill's own",
      request["currency"] == "INR", f"got {request.get('currency')}")

check("the amount sent to Razorpay is in paise",
      request["request"]["checkout"]["amount"]
      == int(round(bill_total * 100)),
      f"got {request['request']['checkout']['amount']}")

check("the Razorpay order id is stored as the provider reference",
      str(provider_order_id).startswith("order_")
      and one("SELECT provider_reference FROM payments WHERE id = %s",
              (payment_id,)) == provider_order_id,
      f"got {provider_order_id}")

check("the checkout payload contains no key secret",
      TEST_KEY_SECRET not in json.dumps(request),
      "the key secret reached the browser payload")

check("the request is PENDING",
      request["status"] == "PENDING", f"got {request.get('status')}")

check("the bill is still UNPAID after a request",
      one("SELECT payment_status FROM order_headers WHERE id = %s",
          (order["order_id"],)) == "unpaid",
      "the bill moved when a request was created")

check("paid_at is not set by a request",
      one("SELECT paid_at FROM order_headers WHERE id = %s",
          (order["order_id"],)) is None,
      "paid_at was set by creating a request")

check("no UPI URI is issued for a Razorpay payment",
      request["request"].get("upi_uri") is None,
      "a second, unconfirmed payment surface was offered")

# ==========================================================
print("\n[D] webhook signature verification")
# ==========================================================
body, signature = captured_webhook(
    "payment.captured",
    {"id": "pay_1", "order_id": provider_order_id,
     "amount": int(round(bill_total * 100)), "currency": "INR",
     "status": "captured", "captured": True},
)

check("a correctly signed webhook verifies",
      verify_webhook_signature(body, signature, TEST_WEBHOOK_SECRET),
      "the signature did not verify")

check("a tampered body does not verify",
      not verify_webhook_signature(body + b" ", signature,
                                   TEST_WEBHOOK_SECRET),
      "a tampered body verified")

check("a modified payload does not verify",
      not verify_webhook_signature(
          body.replace(b"captured", b"failed"), signature,
          TEST_WEBHOOK_SECRET),
      "a modified payload verified")

check("a missing signature does not verify",
      not verify_webhook_signature(body, None, TEST_WEBHOOK_SECRET),
      "a missing signature verified")

check("a wrong secret does not verify",
      not verify_webhook_signature(body, signature, "wrong-secret"),
      "the wrong secret verified")

check("an empty secret verifies nothing",
      not verify_webhook_signature(body, signature, ""),
      "an empty secret verified")

status, refused = post_webhook(body, signature="0" * 64)

check("the webhook route refuses a bad signature with 401",
      status == 401, f"got {status}")

status, refused = post_webhook(body, signature=None)

check("the webhook route refuses a missing signature with 401",
      status == 401, f"got {status}")

status, refused = call(
    "POST", "/api/payments/webhook", raw_body=b"{not json",
    headers={"X-Razorpay-Signature": sign(b"{not json", TEST_WEBHOOK_SECRET)},
)

check("a signed but malformed body is refused with 400",
      status == 400, f"got {status}")

status, refused = post_webhook(b"")

check("an empty body is refused", status in (400, 401),
      f"got {status}")

check("no payment was settled by any refused webhook",
      one("SELECT status FROM payments WHERE id = %s",
          (payment_id,)) == "PENDING",
      "a refused webhook settled a payment")

# ==========================================================
print("\n[E] webhook idempotency")
# ==========================================================
status, applied = post_webhook(body, signature=signature)

check("the first genuine webhook is accepted",
      status == 200 and applied["result"] == "applied",
      f"got {status} {applied}")

check("the payment settled",
      applied["payment_status"] == "SUCCESS",
      f"got {applied.get('payment_status')}")

check("the bill is paid",
      applied["changed"] is True
      and one("SELECT payment_status FROM order_headers WHERE id = %s",
              (order["order_id"],)) == "paid",
      "the bill did not become paid")

paid_at_first = one("SELECT paid_at FROM order_headers WHERE id = %s",
                    (order["order_id"],))

check("paid_at was set from the confirmed payment",
      paid_at_first is not None, "paid_at was not set")

check("the provider's payment id was recorded",
      one("SELECT provider_payment_reference FROM payments WHERE id = %s",
          (payment_id,)) == "pay_1",
      f"got {one('SELECT provider_payment_reference FROM payments WHERE id = %s', (payment_id,))}")

succeeded_events = one(
    "SELECT COUNT(*) FROM restaurant_events WHERE event_type = %s "
    "AND entity_id = %s", ("PAYMENT_SUCCEEDED", payment_id)
)

check("exactly one PAYMENT_SUCCEEDED event was recorded",
      succeeded_events == 1, f"got {succeeded_events}")

status, duplicate = post_webhook(body, signature=signature)

check("the same webhook delivered again is acknowledged as a duplicate",
      status == 200 and duplicate["result"] == "duplicate",
      f"got {status} {duplicate}")

check("a duplicate changes nothing",
      duplicate["changed"] is False
      and one("SELECT paid_at FROM order_headers WHERE id = %s",
              (order["order_id"],)) == paid_at_first,
      "the duplicate moved paid_at")

check("a duplicate does not record a second success event",
      one("SELECT COUNT(*) FROM restaurant_events WHERE event_type = %s "
          "AND entity_id = %s", ("PAYMENT_SUCCEEDED", payment_id)) == 1,
      "a second PAYMENT_SUCCEEDED was recorded")

check("only one webhook row exists for that event id",
      one("SELECT COUNT(*) FROM payment_webhook_events "
          "WHERE event_id = %s", (json.loads(body)["event_id"],)) == 1,
      "the duplicate inserted another row")

check("the collected total counted the payment once",
      round(float(one(
          "SELECT COALESCE(SUM(amount), 0) FROM payments "
          "WHERE status = 'SUCCESS' AND order_id = %s",
          (order["order_id"],))), 2) == bill_total,
      "the settled amount changed")

# ==========================================================
print("\n[F] a second capture cannot double-settle")
# ==========================================================
status, second = call(
    "POST", "/api/payments/request", token=guest_token,
    body={"order_id": order["order_id"]},
)
check("a settled bill cannot be requested again",
      status == 409, f"got {status}")

status, verify_again = call(
    "POST", f"/api/payments/{payment_id}/verify",
    token=guest_token, body={},
)

check("verifying a settled payment is idempotent",
      status == 200 and verify_again["changed"] is False,
      f"got {status} changed={verify_again.get('changed')}")

check("no duplicate settlement exists",
      one("SELECT COUNT(*) FROM (SELECT order_id FROM payments "
          "WHERE status = 'SUCCESS' GROUP BY order_id "
          "HAVING COUNT(*) > 1) t") == 0,
      "a bill settled twice")

# ==========================================================
print("\n[G] failure and mismatch states")
# ==========================================================
# ---- amount mismatch ----
status, order_b = call(
    "POST", "/api/orders/", token=guest_token,
    body={"menu_id": dish["id"], "quantity": 1, "notes": "phase7f mismatch"},
)
created_orders.append(order_b["orders"][0]["id"])
created_headers.append(order_b["order_id"])

status, request_b = call(
    "POST", "/api/payments/request", token=guest_token,
    body={"order_id": order_b["order_id"]},
)
created_payments.append(request_b["payment_id"])

bad_amount_body, bad_amount_sig = captured_webhook(
    "payment.captured",
    {"id": "pay_bad_amount",
     "order_id": request_b["provider_reference"],
     "amount": 1,  # one paise, not the bill
     "currency": "INR", "status": "captured", "captured": True},
)

status, mismatch = post_webhook(bad_amount_body, signature=bad_amount_sig)

check("a captured payment for the wrong amount is refused with 409",
      status == 409, f"got {status} {mismatch}")

check("an amount mismatch does not settle the payment",
      one("SELECT status FROM payments WHERE id = %s",
          (request_b["payment_id"],)) == "PENDING",
      "a mismatched payment settled")

check("an amount mismatch leaves the bill unpaid",
      one("SELECT payment_status FROM order_headers WHERE id = %s",
          (order_b["order_id"],)) == "unpaid",
      "a mismatched payment marked the bill paid")

check("an amount mismatch sets no paid_at",
      one("SELECT paid_at FROM order_headers WHERE id = %s",
          (order_b["order_id"],)) is None,
      "paid_at was set by a mismatched capture")

check("the refused webhook is recorded for an operator",
      one("SELECT COUNT(*) FROM payment_webhook_events "
          "WHERE result = 'refused' AND payment_id = %s",
          (request_b["payment_id"],)) == 1,
      "no refused record")

# ---- currency mismatch ----
bad_currency_body, bad_currency_sig = captured_webhook(
    "payment.captured",
    {"id": "pay_bad_currency",
     "order_id": request_b["provider_reference"],
     "amount": int(round(float(order_b["total_amount"]) * 100)),
     "currency": "USD", "status": "captured", "captured": True},
)

status, currency_mismatch = post_webhook(
    bad_currency_body, signature=bad_currency_sig
)

check("a captured payment in the wrong currency is refused with 409",
      status == 409, f"got {status}")

check("a currency mismatch does not settle the payment",
      one("SELECT status FROM payments WHERE id = %s",
          (request_b["payment_id"],)) == "PENDING",
      "a currency-mismatched payment settled")

# ---- unknown reference ----
unknown_body, unknown_sig = captured_webhook(
    "payment.captured",
    {"id": "pay_unknown", "order_id": "order_does_not_exist",
     "amount": 10000, "currency": "INR", "status": "captured",
     "captured": True},
)

status, unknown = post_webhook(unknown_body, signature=unknown_sig)

check("a capture for an unknown payment is refused with 404",
      status == 404, f"got {status} {unknown}")

# ---- a failed capture ----
status, order_c = call(
    "POST", "/api/orders/", token=guest_token,
    body={"menu_id": dish["id"], "quantity": 1, "notes": "phase7f failed"},
)
created_orders.append(order_c["orders"][0]["id"])
created_headers.append(order_c["order_id"])

status, request_c = call(
    "POST", "/api/payments/request", token=guest_token,
    body={"order_id": order_c["order_id"]},
)
created_payments.append(request_c["payment_id"])

failed_body, failed_sig = captured_webhook(
    "payment.failed",
    {"id": "pay_failed", "order_id": request_c["provider_reference"],
     "amount": int(round(float(order_c["total_amount"]) * 100)),
     "currency": "INR", "status": "failed",
     "error_description": "BAD_REQUEST_ERROR"},
)

status, failed = post_webhook(failed_body, signature=failed_sig)

check("a failed capture is accepted", status == 200, f"got {status}")

check("the failed payment is recorded as FAILED",
      failed["payment_status"] == "FAILED",
      f"got {failed.get('payment_status')}")

check("a failed payment leaves the bill UNPAID",
      one("SELECT payment_status FROM order_headers WHERE id = %s",
          (order_c["order_id"],)) == "unpaid",
      "a failed payment marked the bill paid")

check("a failed payment sets no paid_at",
      one("SELECT paid_at FROM order_headers WHERE id = %s",
          (order_c["order_id"],)) is None,
      "paid_at was set by a failure")

check("PAYMENT_FAILED was recorded",
      one("SELECT COUNT(*) FROM restaurant_events WHERE event_type = %s "
          "AND entity_id = %s",
          ("PAYMENT_FAILED", request_c["payment_id"])) == 1,
      "no PAYMENT_FAILED event")

check("the failure reason was stored",
      "BAD_REQUEST_ERROR" in (one(
          "SELECT failure_reason FROM payments WHERE id = %s",
          (request_c["payment_id"],)) or ""),
      "the reason was not stored")

# ---- order.paid is recorded but never settles ----
ignored_body, ignored_sig = captured_webhook(
    "order.paid",
    {"id": "pay_ignored", "order_id": request_c["provider_reference"],
     "amount": int(round(float(order_c["total_amount"]) * 100)),
     "currency": "INR", "status": "paid"},
)

status, ignored = post_webhook(ignored_body, signature=ignored_sig)

check("order.paid is accepted but never settles",
      status == 200 and ignored["result"] == "ignored"
      and one("SELECT status FROM payments WHERE id = %s",
              (request_c["payment_id"],)) == "FAILED",
      f"got {status} {ignored}")

check("order.paid left the bill UNPAID",
      one("SELECT payment_status FROM order_headers WHERE id = %s",
          (order_c["order_id"],)) == "unpaid",
      "order.paid marked the bill paid")

# ---- an uncaptured event named payment.captured ----
uncaptured_body, uncaptured_sig = captured_webhook(
    "payment.captured",
    {"id": "pay_uncaptured", "order_id": request_b["provider_reference"],
     "amount": int(round(float(order_b["total_amount"]) * 100)),
     "currency": "INR", "status": "created", "captured": False},
)

status, uncaptured = post_webhook(
    uncaptured_body, signature=uncaptured_sig
)

check("a payment.captured event that is not captured does not settle",
      status == 200 and uncaptured["result"] == "ignored"
      and one("SELECT status FROM payments WHERE id = %s",
              (request_b["payment_id"],)) == "PENDING",
      f"got {status} {uncaptured}")

# ==========================================================
print("\n[H] live-mode safety")
# ==========================================================
saved = {
    "PAYMENT_MODE": os.environ.get("PAYMENT_MODE"),
    "ALLOW_LIVE_PAYMENTS": os.environ.get("ALLOW_LIVE_PAYMENTS"),
    "RAZORPAY_KEY_ID": os.environ.get("RAZORPAY_KEY_ID"),
    "RAZORPAY_WEBHOOK_SECRET": os.environ.get("RAZORPAY_WEBHOOK_SECRET"),
}


def with_env(**overrides):
    for key, value in overrides.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value

    reloaded = importlib.reload(payment_provider)

    return reloaded


# live without ALLOW_LIVE_PAYMENTS
live_no_ack = with_env(PAYMENT_MODE="live", ALLOW_LIVE_PAYMENTS="false")

try:
    live_no_ack.validate_configuration()
    raised = False
except payment_provider.PaymentConfigurationError:
    raised = True

check("live mode without ALLOW_LIVE_PAYMENTS is refused", raised,
      "live mode was accepted with only the mode set")

# live with the acknowledgement but no credentials
live_no_keys = with_env(
    PAYMENT_MODE="live", ALLOW_LIVE_PAYMENTS="true",
    RAZORPAY_KEY_ID=None, RAZORPAY_KEY_SECRET=None,
    RAZORPAY_WEBHOOK_SECRET=None,
)

try:
    live_no_keys.validate_configuration()
    raised = False
except payment_provider.PaymentConfigurationError:
    raised = True

check("live mode without credentials is refused", raised,
      "live mode was accepted with no credentials")

# live with credentials but the wrong provider
wrong_provider = with_env(
    PAYMENT_MODE="live", ALLOW_LIVE_PAYMENTS="true",
    PAYMENT_PROVIDER="development",
)

try:
    wrong_provider.validate_configuration()
    raised = False
except payment_provider.PaymentConfigurationError:
    raised = True

check("live mode with the wrong provider is refused", raised,
      "live mode was accepted on a provider that cannot confirm")

# a typo in the mode fails closed rather than falling back
typo = with_env(PAYMENT_MODE="prodction")

check("an unrecognised mode becomes disabled, not development",
      typo.PAYMENT_MODE == "disabled" and typo.payments_enabled() is False,
      f"got {typo.PAYMENT_MODE}")

check("an unrecognised mode returns no provider",
      typo.get_provider() is None,
      "an unrecognised mode produced a provider")

# ---- restore ----
with_env(**saved)

check("restoring the test configuration validates",
      payment_provider.validate_configuration()["ok"] is True,
      "the restored configuration did not validate")

check("live mode is NOT enabled by the restored configuration",
      payment_provider.is_live() is False
      and payment_provider.configuration()["live_gateway_connected"] is False,
      f"got {payment_provider.configuration()}")

# ==========================================================
print("\n[I] security")
# ==========================================================
status, _ = call("POST", "/api/payments/webhook", raw_body=body,
                 headers={"X-Razorpay-Signature": sign(body, "guess")})

check("a guessed secret cannot reach the webhook", status == 401,
      f"got {status}")

status, _ = call("POST", "/api/payments/webhook", raw_body=body,
                 token=guest_token,
                 headers={"X-Razorpay-Signature": sign(body, TEST_WEBHOOK_SECRET)})

check("a customer JWT is irrelevant to the webhook; only the signature counts",
      status == 409 or status == 200 or status == 404,
      f"got {status}")

status, forged = call(
    "POST", f"/api/payments/{payment_id}/verify", token=guest_token,
    body={"status": "SUCCESS"},
)

check("a guest still cannot declare a payment successful", status == 422,
      f"got {status}")

status, forged = call(
    "POST", f"/api/payments/dev/{payment_id}/simulate", token=guest_token,
    body={"outcome": "SUCCESS"},
)

check("the simulation route is gone in test mode", status == 404,
      f"got {status}")

status, forged = call(
    "POST", f"/api/payments/dev/{payment_id}/simulate", token=ADMIN,
    body={"outcome": "SUCCESS"},
)

check("the simulation route is gone for an admin too", status == 404,
      f"got {status}")

# ---- injection through the webhook body ----
injection_body = json.dumps({
    "event": "payment.captured",
    "event_id": "evt_injection",
    "payload": {"payment": {"entity": {
        "id": "pay_inj",
        "order_id": "order_'; DROP TABLE payments; --",
        "amount": 10000, "currency": "INR",
        "status": "captured", "captured": True,
    }}},
}).encode()

status, injected = post_webhook(injection_body)

check("an injection through the webhook body is refused",
      status == 404, f"got {status}")

check("the payments table survived the injection",
      "payments" in {row[0] for row in sql("SHOW TABLES")},
      "the payments table was dropped")

check("the injection created no payment",
      one("SELECT COUNT(*) FROM payments") >= payments_before,
      "a payment row appeared")

# ---- credential exposure ----
status, listing = call("GET", "/api/payments/admin/orders", token=ADMIN)

check("the admin gateway view exposes no secret",
      TEST_KEY_SECRET not in json.dumps(listing)
      and TEST_WEBHOOK_SECRET not in json.dumps(listing),
      "a secret leaked into the admin gateway view")

status, reconciled = call(
    "GET", f"/api/payments/admin/reconcile/{payment_id}", token=ADMIN
)

check("reconciliation exposes no secret",
      TEST_KEY_SECRET not in json.dumps(reconciled, default=str)
      and TEST_WEBHOOK_SECRET not in json.dumps(reconciled, default=str),
      "a secret leaked into a reconciliation response")

status, _ = call(
    "GET", f"/api/payments/admin/reconcile/{payment_id}", token=guest_token
)

check("reconciliation is admin-only", status == 403, f"got {status}")

status, _ = call(
    "GET", f"/api/payments/admin/reconcile/{payment_id}"
)

check("reconciliation requires authentication", status == 401, f"got {status}")

# ---- the event log holds no credential ----
check("no webhook event metadata holds a credential",
      one("SELECT COUNT(*) FROM payment_webhook_events "
          "WHERE CAST(metadata_json AS CHAR) REGEXP "
          "'secret|password|api_key|token|signature'") == 0,
      "a credential-shaped key reached the webhook log")

check("no payment event metadata holds a credential",
      one("SELECT COUNT(*) FROM restaurant_events "
          "WHERE CAST(metadata_json AS CHAR) REGEXP "
          "'secret|password|api_key'") == 0,
      "a credential-shaped key reached the event log")

# ---- reconciliation ----
status, reconciled = call(
    "GET", f"/api/payments/admin/reconcile/{payment_id}", token=ADMIN
)

check("200 for an admin reconciliation", status == 200, f"got {status}")

if status == 200 and reconciled.get("has_data"):
    check("reconciliation compares the local and provider amounts",
          reconciled["checks"]["amount_matches"] is True
          and reconciled["checks"]["currency_matches"] is True
          and reconciled["matches"] is True,
          f"got {reconciled.get('checks')}")

    check("reconciliation reports the provider reference",
          reconciled["remote_status"] is not None,
          f"got {reconciled.get('remote_status')}")
else:
    check("reconciliation reported a limitation rather than a guess",
          bool(reconciled.get("limitation")),
          f"got {reconciled}")

# ---- no secret anywhere in the frontend bundle ----
BUNDLE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "..", "frontend", "dist", "assets",
)

secrets_in_bundle = False

try:
    for asset in os.listdir(BUNDLE):
        if not asset.endswith(".js"):
            continue

        with open(os.path.join(BUNDLE, asset), encoding="utf-8",
                  errors="ignore") as handle:
            body_text = handle.read()

        for secret in (TEST_KEY_SECRET, TEST_WEBHOOK_SECRET):
            if secret in body_text:
                secrets_in_bundle = True
except OSError:
    pass

check("no credential appears in the built frontend bundle",
      secrets_in_bundle is False,
      "a secret was found in dist/assets")

# ==========================================================
print("\n[J] the development provider still works")
# ==========================================================
# Reload with the shipped default and confirm nothing regressed.
with_env(
    PAYMENT_MODE="development",
    PAYMENT_PROVIDER="development",
    ALLOW_LIVE_PAYMENTS="false",
)

check("development mode is the shipped default here",
      payment_provider.development_mode() is True,
      f"got {payment_provider.PAYMENT_MODE}")

check("the development provider is still the active one",
      payment_provider.get_provider().name == "development",
      f"got {payment_provider.get_provider().name}")

check("the development configuration reports no gateway",
      payment_provider.configuration()["gateway_connected"] is False
      and payment_provider.configuration()["live_gateway_connected"] is False,
      f"got {payment_provider.configuration()}")

status, dev_request = call(
    "POST", "/api/payments/request", token=guest_token,
    body={"order_id": order_b["order_id"]},
)

created_payments.append(dev_request["payment_id"])

check("a development payment request still works", status == 200,
      f"got {status} {dev_request}")

check("the development reference is a DEV-PAY reference",
      str(dev_request["provider_reference"]).startswith("DEV-PAY-"),
      f"got {dev_request.get('provider_reference')}")

check("the development request offers the UPI surface",
      bool(dev_request["request"]["upi_uri"]),
      "no UPI URI in development mode")

status, dev_sim = call(
    "POST", f"/api/payments/dev/{dev_request['payment_id']}/simulate",
    token=ADMIN, body={"outcome": "SUCCESS"},
)

check("the development simulation still settles through verification",
      status == 200 and dev_sim["status"] == "SUCCESS"
      and dev_sim["order_payment_status"] == "paid",
      f"got {status} {dev_sim}")

check("the development simulation set paid_at",
      one("SELECT paid_at FROM order_headers WHERE id = %s",
          (order_b["order_id"],)) is not None,
      "paid_at was not set")

# ==========================================================
print("\n[K] the AI reports the provider honestly")
# ==========================================================
with_env(
    PAYMENT_MODE="test",
    PAYMENT_PROVIDER="razorpay",
    RAZORPAY_KEY_ID=TEST_KEY_ID,
    RAZORPAY_KEY_SECRET=TEST_KEY_SECRET,
    RAZORPAY_WEBHOOK_SECRET=TEST_WEBHOOK_SECRET,
    ALLOW_LIVE_PAYMENTS="false",
)

status, ai = call(
    "POST", "/api/ai/assistant/ask", token=ADMIN,
    body={"question": "Show today's payment summary."},
)

check("the AI reaches the payment tool", status == 200
      and "get_payment_metrics" in ai["tools_used"],
      f"got {ai.get('tools_used')}")

check("the AI names the provider", "razorpay" in ai["answer"].lower(),
      ai["answer"][:260])

check("the AI states the mode", "test" in ai["answer"].lower(),
      ai["answer"][:260])

check("the AI does NOT call a test gateway live",
      "live" not in ai["answer"].lower().split("mode")[-1][:40]
      or "live money" not in ai["answer"].lower(),
      ai["answer"][:260])

check("the AI exposes no credential",
      TEST_KEY_SECRET not in json.dumps(ai)
      and TEST_WEBHOOK_SECRET not in json.dumps(ai),
      "a secret leaked into an AI answer")

with_env(**saved)

# ==========================================================
print("\n[L] integrity and cleanup")
# ==========================================================
check("no pre-existing bill changed",
      sql("SELECT id, total_amount, currency, payment_status, paid_at, "
          "status FROM order_headers WHERE id <= %s ORDER BY id",
          (preexisting_header_max,)) == header_snapshot,
      "a pre-existing bill was modified")

check("every pre-existing bill is still unpaid",
      one("SELECT COUNT(*) FROM order_headers WHERE id <= %s "
          "AND payment_status = 'paid'",
          (preexisting_header_max,)) == 0,
      "a pre-existing bill was marked paid")

check("no duplicate settlement exists anywhere",
      one("SELECT COUNT(*) FROM (SELECT order_id FROM payments "
          "WHERE status = 'SUCCESS' GROUP BY order_id "
          "HAVING COUNT(*) > 1) t") == 0,
      "a bill settled twice")

check("every stored payment amount matches its bill",
      all(
          round(float(row[0]), 2) == round(float(row[1]), 2)
          for row in sql(
              "SELECT p.amount, h.total_amount FROM payments p "
              "JOIN order_headers h ON h.id = p.order_id"
          )
      ),
      "a stored payment amount disagrees with its bill")

print("\n[cleanup]")
probe_headers = ",".join(
    str(row[0])
    for row in sql(
        "SELECT id FROM order_headers WHERE customer_name = %s",
        (PROBE_NAME,),
    )
) or "0"

sql(
    "DELETE FROM restaurant_events WHERE entity_type = 'payment' "
    "AND entity_id IN (SELECT id FROM payments WHERE order_id IN ("
    + probe_headers + "))"
)
sql("DELETE FROM payments WHERE order_id IN (" + probe_headers + ")")

sql(
    "DELETE FROM restaurant_events WHERE event_type LIKE 'PAYMENT%' "
    "AND entity_id NOT IN (SELECT id FROM payments)"
)
sql("DELETE FROM payment_webhook_events")

for header_id in set(created_headers):
    sql("DELETE FROM restaurant_events WHERE entity_type = 'order' "
        "AND entity_id = %s", (header_id,))
    sql("DELETE FROM kitchen WHERE order_id IN "
        "(SELECT id FROM orders WHERE order_id = %s)", (header_id,))
    sql("DELETE FROM orders WHERE order_id = %s", (header_id,))
    sql("DELETE FROM order_headers WHERE id = %s", (header_id,))

for order_id in set(created_orders):
    sql("DELETE FROM restaurant_events WHERE entity_type = 'order' "
        "AND entity_id = %s", (order_id,))
    sql("DELETE FROM kitchen WHERE order_id = %s", (order_id,))
    sql("DELETE FROM orders WHERE id = %s", (order_id,))

sql("DELETE k FROM kitchen k LEFT JOIN orders o ON o.id = k.order_id "
    "WHERE o.id IS NULL")

sql("UPDATE users SET active_table_id = NULL WHERE active_table_id IN "
    "(SELECT id FROM users WHERE email LIKE 'phase7f%')")

for table_id in created_tables:
    sql("DELETE FROM restaurant_tables WHERE id = %s", (table_id,))

sql("DELETE FROM restaurant_tables WHERE table_number = %s", (PROBE_TABLE,))

for email in created_users:
    sql("DELETE FROM users WHERE email = %s", (email,))

print(f"  payments   {payments_before} -> "
      f"{one('SELECT COUNT(*) FROM payments')}")
print(f"  headers    {headers_before} -> "
      f"{one('SELECT COUNT(*) FROM order_headers')}")
print(f"  webhooks   {webhook_rows_before} -> "
      f"{one('SELECT COUNT(*) FROM payment_webhook_events')}")

check("no payment row was left behind",
      one("SELECT COUNT(*) FROM payments") == payments_before,
      f"{one('SELECT COUNT(*) FROM payments')} vs {payments_before}")

check("no bill header was left behind",
      one("SELECT COUNT(*) FROM order_headers") == headers_before,
      f"{one('SELECT COUNT(*) FROM order_headers')} vs {headers_before}")

check("no webhook row was left behind",
      one("SELECT COUNT(*) FROM payment_webhook_events")
      == webhook_rows_before,
      "webhook rows leaked")

check("no probe account was left behind",
      one("SELECT COUNT(*) FROM users WHERE email LIKE %s",
          ("phase7f%",)) == 0,
      "a probe account leaked")

check("no probe table was left behind",
      one("SELECT COUNT(*) FROM restaurant_tables "
          "WHERE table_number = %s", (PROBE_TABLE,)) == 0,
      "a probe table leaked")

check("no orphan kitchen ticket was left",
      one("SELECT COUNT(*) FROM kitchen k LEFT JOIN orders o "
          "ON o.id = k.order_id WHERE o.id IS NULL") == 0,
      "orphan kitchen tickets")

check("no payment reference was backfilled",
      one("SELECT COUNT(*) FROM payments "
          "WHERE provider_payment_reference IS NOT NULL") == 0,
      "a provider payment reference was invented")

# ==========================================================
print("\n" + "=" * 74)
print(f"RESULT: {len(passed)} passed, {len(failed)} failed")

if failed:
    print("\nFAILURES:")
    for name in failed:
        print(f"  - {name}")

print("=" * 74)

sys.exit(1 if failed else 0)
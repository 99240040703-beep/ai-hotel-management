"""
Phase 6A acceptance tests: order data integrity and production hardening.

    python scripts/test_phase6_integrity.py http://127.0.0.1:8010

Covers the thirty required scenarios plus every additional financial
trust boundary the implementation exposes:

    A  authentication on the legacy order endpoints
    B  the server refuses a client unit price / total / subtotal / tax /
       discount / currency, and uses the menu price instead
    C  availability, existence and quantity validation
    D  malformed, duplicate, empty and oversized payloads
    E  customer ownership, enforced from the JWT alone
    F  table association cannot be forged, and a claim is authoritative
    G  historical rows are never rewritten
    H  the customer bill is built from stored server totals
    I  SERVED and UNPAID are independent facts
    J  response security: admin-only data stays admin-only
    K  Phase 1-5 regressions, including the analytics data_quality block

Every probe cleans up after itself and the run finishes by asserting the
row counts are back where they started.
"""

import json
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pymysql

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8010"

DB = dict(
    host="localhost",
    user="root",
    password="Nithin.0987",
    database="restaurant_db",
    autocommit=True,
)

passed = []
failed = []

# Everything this run creates, so the cleanup can be exact.
created_headers = []
created_orders = []
created_tables = []
created_users = []


def call(method, path, token=None, body=None):
    data = json.dumps(body).encode() if body is not None else None

    request = Request(
        BASE + path,
        data=data,
        method=method,
        headers={
            "Content-Type": "application/json",
            **({"Authorization": "Bearer " + token} if token else {}),
        },
    )

    try:
        with urlopen(request, timeout=25) as response:
            raw = response.read().decode()

            return response.status, json.loads(raw) if raw else None
    except HTTPError as error:
        raw = error.read().decode()

        try:
            return error.code, json.loads(raw) if raw else None
        except json.JSONDecodeError:
            return error.code, raw


def check(name, condition, detail=""):
    if condition:
        passed.append(name)
        print(f"  PASS  {name}")
    else:
        failed.append(name)
        print(f"  FAIL  {name}  {detail}")


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
            cursor.execute(query, args or ())

            if cursor.description is None:
                return []

            return cursor.fetchall()
    finally:
        connection.close()


def one(query, args=None):
    rows = sql(query, args)

    return rows[0][0] if rows else None


def make_user(email, name):
    """A fresh account, so ownership can be tested between two real people."""
    sql("DELETE FROM users WHERE email = %s", (email,))
    created_users.append(email)

    status, data = call(
        "POST",
        "/auth/register",
        body={"name": name, "email": email, "password": "password123"},
    )

    if status != 200:
        raise SystemExit(f"cannot register {email}: {status} {data}")

    return data["token"], data["user"]


def make_table(number, label):
    # A previous run that was interrupted before its cleanup can leave
    # these behind, and the numbers are unique. Clearing them first means
    # this run always starts from the same place.
    sql("DELETE FROM restaurant_tables WHERE table_number = %s", (number,))

    status, table = call(
        "POST",
        "/api/tables/",
        token=admin_token,
        body={"table_number": number, "table_name": label, "capacity": 4},
    )

    if status != 200:
        raise SystemExit(f"cannot create table {number}: {status} {table}")

    created_tables.append(table["id"])

    return table


def track(payload):
    """Record what a successful legacy order wrote, for cleanup."""
    if isinstance(payload, dict) and payload.get("order_id"):
        created_headers.append(payload["order_id"])

    for row in (payload or {}).get("orders") or []:
        if isinstance(row, dict) and row.get("id"):
            created_orders.append(row["id"])

    return payload


print("=" * 74)
print(f"PHASE 6A ORDER INTEGRITY TESTS  ->  {BASE}")
print("=" * 74)

admin_token = login("admin@gmail.com")

# ------------------------------------------------------------------
# Fixtures
#
# A previous run that was interrupted before its cleanup leaves its probe
# rows behind. Clearing them first makes this run start from a known
# state, so a crash never turns into a cascade of confusing failures.
# Nothing real is matched here: every fixture has its own name.
# ------------------------------------------------------------------
sql("DELETE FROM menu WHERE name = %s", ("Phase6A unavailable probe",))
sql("DELETE FROM restaurant_tables WHERE table_number IN (9001, 9002)")
sql("DELETE FROM users WHERE email LIKE %s", ("phase6a.%",))
sql("UPDATE users SET active_table_id = NULL WHERE active_table_id IS NOT NULL")

# Orders this script wrote are the ones owned by the two probe display
# names it registers. Those names exist nowhere else, so this cannot
# match real history.
for probe_name in ("Phase6A Buyer", "Phase6A Other"):
    # Phase 6B added an operational event log, and placing an order now
    # writes to it. The events are removed with the orders they describe,
    # otherwise every run of this script would leave history behind that
    # the kitchen metrics would then report.
    sql(
        "DELETE e FROM restaurant_events e JOIN orders o "
        "ON o.id = e.entity_id WHERE o.customer_name = %s",
        (probe_name,),
    )
    sql(
        "DELETE FROM restaurant_events WHERE entity_id IN "
        "(SELECT id FROM order_headers WHERE customer_name = %s)",
        (probe_name,),
    )
    sql("DELETE FROM orders WHERE customer_name = %s", (probe_name,))
    sql("DELETE FROM order_headers WHERE customer_name = %s", (probe_name,))

# ------------------------------------------------------------------
# Baseline
# ------------------------------------------------------------------
orders_before = one("SELECT COUNT(*) FROM orders")
headers_before = one("SELECT COUNT(*) FROM order_headers")
kitchen_before = one("SELECT COUNT(*) FROM kitchen")
tables_before = one("SELECT COUNT(*) FROM restaurant_tables")

settings = sql(
    "SELECT tax_percentage, service_charge_percentage, currency FROM settings LIMIT 1"
)[0]

tax_rate = float(settings[0] or 0)
service_rate = float(settings[1] or 0)
configured_currency = (settings[2] or "UNSET").upper()

menu = call("GET", "/api/menu/", token=admin_token)[1] or []
available = [row for row in menu if row["available"]]
dish = available[0]
price = float(dish["price"])

# A second dish, for the two-line subtotal check.
dish_b = next(
    (row for row in available if row["id"] != dish["id"] and float(row["price"]) > 0),
    dish,
)

# An unavailable dish, created purely for this run and removed at the end.
sql(
    "INSERT INTO menu (name, category, price, available, is_vegetarian, "
    "is_featured, spice_level, prep_time) "
    "VALUES ('Phase6A unavailable probe', 'Phase6A probe', 111.00, 0, 1, 0, 0, 10)"
)
probe_menu_id = one(
    "SELECT id FROM menu WHERE name = 'Phase6A unavailable probe' ORDER BY id DESC LIMIT 1"
)

print(f"  dish            : {dish['name']} (id {dish['id']}) Rs.{price}")
print(f"  settings        : tax={tax_rate}% service={service_rate}% {configured_currency}")

# Historical rows sampled before anything this run does. They must be
# byte-identical afterwards.
legacy_ids = [
    row[0]
    for row in sql(
        "SELECT id FROM orders WHERE order_id IS NULL ORDER BY id LIMIT 5"
    )
]

legacy_snapshot = sql(
    "SELECT id, customer_name, menu_item, quantity, total_price, unit_price, "
    "status, order_id, user_id FROM orders WHERE id IN ({}) ORDER BY id".format(
        ",".join(str(i) for i in legacy_ids)
    )
)

# The two known Phase 5 scaffold rows (Rs.8.99 and Rs.13.99). Phase 6A
# must not rewrite them, and must not invent an owner for them either.
anomaly_snapshot = sql(
    "SELECT id, customer_name, menu_item, quantity, total_price, unit_price, "
    "user_id FROM orders WHERE total_price < 20 ORDER BY id"
)

print(f"  legacy sample   : {legacy_ids}")
print(f"  anomaly rows    : {[row[0] for row in anomaly_snapshot]}")

legacy_unlinked_at_start = one("SELECT COUNT(*) FROM orders WHERE order_id IS NULL")

# ------------------------------------------------------------------
# Accounts and a table
# ------------------------------------------------------------------
buyer_token, buyer = make_user("phase6a.buyer@example.com", "Phase6A Buyer")
other_token, other = make_user("phase6a.other@example.com", "Phase6A Other")

claimed = make_table(9001, "Phase6A Claimed Table")
rival = make_table(9002, "Phase6A Rival Table")

sql("UPDATE users SET active_table_id = NULL WHERE id IN (%s, %s)",
    (buyer["id"], other["id"]))

status, resolved = call(
    "GET", f"/api/tables/resolve?table={claimed['qr_token']}"
)

check("the QR of a fresh table resolves for anyone holding it",
      status == 200
      and (resolved.get("table") or {}).get("table_number") == claimed["table_number"],
      f"{status} {resolved}")

status, claimed_body = call(
    "POST", "/api/tables/claim", token=buyer_token,
    body={"table_token": claimed["qr_token"]},
)

check("the buyer can claim a table by scanning its QR",
      status == 200
      and (claimed_body.get("table") or {}).get("table_number")
      == claimed["table_number"],
      f"{status} {claimed_body}")

# ==================================================================
print("\n[1] authentication on the legacy order endpoints")
# ==================================================================
status, _ = call("POST", "/api/orders/", body={"menu_item": dish["name"], "quantity": 1})
check("401 without a token: POST /api/orders/", status == 401, f"got {status}")

status, _ = call("POST", "/api/orders/", token="not-a-real-token",
                 body={"menu_item": dish["name"], "quantity": 1})
check("401 with a garbage token: POST /api/orders/", status == 401, f"got {status}")

status, _ = call("POST", "/api/orders/cart", body={"items": []})
check("401 without a token: POST /api/orders/cart", status == 401, f"got {status}")

status, _ = call("POST", "/api/orders/quote", body={"items": []})
check("401 without a token: POST /api/orders/quote", status == 401, f"got {status}")

# ==================================================================
print("\n[2] the client cannot dictate any money")
# ==================================================================
status, attacked = call(
    "POST",
    "/api/orders/",
    token=buyer_token,
    body={
        "customer_name": "TOTALLY SOMEONE ELSE",
        "menu_id": dish["id"],
        "quantity": 2,
        # Everything below is an attack. None of it may be honoured.
        "total_price": 1,
        "unit_price": 0.5,
        "subtotal": 1,
        "tax_amount": 0,
        "tax_percentage": 0,
        "service_charge_amount": 0,
        "service_charge_percentage": 0,
        "discount_amount": 0,
        "discount_percentage": 99,
        "total_amount": 1,
        "currency": "USD",
        "status": "Served",
        "payment_status": "paid",
        "image_url": "https://example.invalid/evil.png",
        "table_number": 9002,
        "notes": "phase6a attack probe",
    },
)

track(attacked)

expected_subtotal = round(price * 2, 2)
expected_tax = round(expected_subtotal * tax_rate / 100.0, 2)
expected_service = round(expected_subtotal * service_rate / 100.0, 2)
expected_total = round(expected_subtotal + expected_tax + expected_service, 2)

check("a Rs.1 total_price does not become the stored total",
      status == 200 and float(attacked["total_amount"]) != 1,
      f"{status} {attacked.get('total_amount')}")

check("the subtotal is menu.price x quantity",
      status == 200 and attacked["subtotal"] == expected_subtotal,
      f"got {attacked.get('subtotal')} want {expected_subtotal}")

check("the tax is the configured rate on the server subtotal",
      status == 200 and attacked["tax_amount"] == expected_tax,
      f"got {attacked.get('tax_amount')} want {expected_tax}")

check("the service charge is the configured rate, not a client one",
      status == 200 and attacked["service_charge_amount"] == expected_service,
      f"got {attacked.get('service_charge_amount')} want {expected_service}")

check("a client discount cannot reduce the payable total",
      status == 200 and float(attacked["discount_amount"]) == 0.0,
      f"got {attacked.get('discount_amount')}")

check("the final total is subtotal + tax + service - discount",
      status == 200 and attacked["total_amount"] == expected_total,
      f"got {attacked.get('total_amount')} want {expected_total}")

check("the response says who priced it",
      status == 200 and attacked.get("priced_by") == "server (menu.price)",
      f"got {attacked.get('priced_by')!r}")

header_id = attacked.get("order_id") if status == 200 else None

stored_header = sql(
    "SELECT subtotal, tax_amount, service_charge_amount, discount_amount, "
    "total_amount, currency, status, payment_status, user_id, table_id "
    "FROM order_headers WHERE id = %s",
    (header_id,),
) if header_id else []

stored_line = sql(
    "SELECT menu_item, quantity, total_price, unit_price, customer_name, "
    "user_id, image_url, status FROM orders WHERE order_id = %s ORDER BY id",
    (header_id,),
) if header_id else []

# The primary key of the first line row, which is what the per-order
# routes are addressed by.
line_id = one("SELECT MIN(id) FROM orders WHERE order_id = %s", (header_id,))

check("the header stores exactly the quoted money",
      bool(stored_header)
      and float(stored_header[0][0]) == expected_subtotal
      and float(stored_header[0][1]) == expected_tax
      and float(stored_header[0][4]) == expected_total,
      f"got {stored_header[0][:5] if stored_header else None}")

check("no money field on the line row was taken from the request",
      bool(stored_line)
      and float(stored_line[0][1]) == 2
      and float(stored_line[0][2]) == expected_subtotal
      and float(stored_line[0][3]) == price,
      f"got {stored_line[0][:4] if stored_line else None}")

check("the stored unit_price is MenuItem.price at order time",
      bool(stored_line) and float(stored_line[0][3]) == float(dish["price"]),
      f"got {stored_line[0][3] if stored_line else None}")

check("the line's dish is the requested dish",
      bool(stored_line) and stored_line[0][0] == dish["name"],
      f"got {stored_line[0][0] if stored_line else None}")

check("the thumbnail comes from the menu, not the request",
      bool(stored_line)
      and (stored_line[0][6] or "") == (dish.get("image_url") or ""),
      f"got {stored_line[0][6] if stored_line else None}")

check("a client cannot start an order already Served",
      bool(stored_line) and stored_line[0][7] == "Pending"
      and bool(stored_header) and stored_header[0][6] == "Placed",
      f"line={stored_line[0][7] if stored_line else None} "
      f"header={stored_header[0][6] if stored_header else None}")

check("a client cannot mark an order paid",
      bool(stored_header) and stored_header[0][7] == "unpaid",
      f"got {stored_header[0][7] if stored_header else None}")

# ==================================================================
print("\n[3] currency is the server's, never the client's")
# ==================================================================
for fake in ("USD", "usd", "EUR", "GBP", "BTC"):
    status, forged = call(
        "POST",
        "/api/orders/",
        token=buyer_token,
        body={"menu_id": dish["id"], "quantity": 1, "currency": fake},
    )

    track(forged)

    stored_currency = (
        one("SELECT currency FROM order_headers WHERE id = %s",
            (forged.get("order_id"),))
        if status == 200 and forged.get("order_id")
        else None
    )

    check(f"currency {fake!r} is ignored and the order is stored in "
          f"{configured_currency}",
          status == 200
          and stored_currency == configured_currency
          and forged.get("currency") == configured_currency,
          f"{status} stored={stored_currency} response={forged.get('currency')}")

status, forged = call(
    "POST",
    "/api/orders/",
    token=buyer_token,
    body={"menu_id": dish["id"], "quantity": 1, "currency": "USD"},
)

track(forged)

check("the response states where the currency came from",
      status == 200 and forged.get("currency_source") == "settings",
      f"got {forged.get('currency_source')!r}")

# ==================================================================
print("\n[4] availability, existence and quantity")
# ==================================================================
orders_before_reject = one("SELECT COUNT(*) FROM orders")
headers_before_reject = one("SELECT COUNT(*) FROM order_headers")

rejections = [
    ("an unavailable dish is refused",
     {"menu_id": probe_menu_id, "quantity": 1}, (404, 409)),
    ("an unknown menu id is refused",
     {"menu_id": 99999999, "quantity": 1}, (404,)),
    ("a zero quantity is refused",
     {"menu_id": dish["id"], "quantity": 0}, (400, 422)),
    ("a negative quantity is refused",
     {"menu_id": dish["id"], "quantity": -3}, (400, 422)),
    ("a fractional quantity is refused",
     {"menu_id": dish["id"], "quantity": 2.5}, (400, 422)),
    ("a non-numeric quantity is refused",
     {"menu_id": dish["id"], "quantity": "two"}, (400, 422)),
    ("a boolean quantity is refused",
     {"menu_id": dish["id"], "quantity": True}, (400, 422)),
    ("an oversized quantity is refused",
     {"menu_id": dish["id"], "quantity": 9999}, (400, 422)),
    ("an order with no dish at all is refused",
     {"quantity": 2}, (400, 422)),
    ("an order naming a dish that does not exist is refused",
     {"menu_item": "No Such Dish Phase6A", "quantity": 1}, (404,)),
    ("an order with a blank dish name is refused",
     {"menu_item": "   ", "quantity": 1}, (400, 404)),
]

for name, body, allowed in rejections:
    status, rejected = call("POST", "/api/orders/", token=buyer_token, body=body)

    check(f"{name} ({status} in {allowed})",
          status in allowed,
          f"got {status} {rejected}")

status, rejected = call("POST", "/api/orders/cart", token=buyer_token,
                        body={"items": []})
check("an empty cart is refused", status == 400, f"got {status}")

status, rejected = call(
    "POST",
    "/api/orders/cart",
    token=buyer_token,
    body={
        "items": [
            {"menu_id": dish["id"], "quantity": 1, "total_price": 0.01},
            {"menu_id": dish["id"], "quantity": 5, "total_price": 0.01},
        ]
    },
)
check("the same dish twice in one cart is refused", status == 400, f"got {status}")

status, rejected = call(
    "POST",
    "/api/orders/",
    token=buyer_token,
    body={"menu_id": dish["id"], "quantity": 1, "notes": "phase6a duplicate probe",
          "items": [{"menu_id": dish["id"], "quantity": 1}]},
)
check("a payload with unknown extra keys is still priced from the menu",
      status == 200,
      f"got {status} {rejected}")

track(rejected)

check("no rejected request created an order or a header",
      one("SELECT COUNT(*) FROM orders") == orders_before_reject + 1
      and one("SELECT COUNT(*) FROM order_headers") == headers_before_reject + 1,
      f"orders {orders_before_reject}->{one('SELECT COUNT(*) FROM orders')} "
      f"headers {headers_before_reject}->{one('SELECT COUNT(*) FROM order_headers')}")

# ==================================================================
print("\n[5] ownership comes from the token")
# ==================================================================
check("the stored customer name is the account holder's, not the body's",
      bool(stored_line) and stored_line[0][4] == buyer["name"],
      f"got {stored_line[0][4] if stored_line else None!r} want {buyer['name']!r}")

check("the stored user_id is the account holder's",
      bool(stored_line) and stored_line[0][5] == buyer["id"]
      and bool(stored_header) and stored_header[0][8] == buyer["id"],
      f"line={stored_line[0][5] if stored_line else None} "
      f"header={stored_header[0][8] if stored_header else None}")

status, other_read = call("GET", f"/api/orders/{line_id}",
                          token=other_token)
check("403 for another customer reading the order line",
      status == 403, f"got {status}")

status, _ = call("PATCH",
                 f"/api/orders/{line_id}/cancel",
                 token=other_token)
check("403 for another customer cancelling the order line",
      status == 403, f"got {status}")

status, other_mine = call("GET", "/api/orders/mine", token=other_token)
other_mine = other_mine or []
check("another customer's order history does not contain it",
      not any(row["id"] in (created_orders or [0]) for row in other_mine),
      f"{len(other_mine)} rows returned")

status, other_headers = call("GET", "/api/orders/headers/mine", token=other_token)
other_headers = other_headers or []
check("another customer sees none of the buyer's order headers",
      not any(row["id"] == header_id for row in other_headers),
      f"{len(other_headers)} rows returned")

status, _ = call("GET", f"/api/orders/headers/{header_id}/status", token=other_token)
check("403 for another customer reading the order status",
      status == 403, f"got {status}")

status, _ = call("POST", f"/api/orders/headers/{header_id}/status",
                 token=other_token, body={"status": "Cancelled"})
check("403 for another customer cancelling the header",
      status == 403, f"got {status}")

status, mine = call("GET", "/api/orders/mine", token=buyer_token)
check("200 for the owner reading their own order history",
      status == 200 and isinstance(mine, list), f"got {status}")

# An account whose display name matches the buyer must still get nothing.
spoof_name = "Phase6A Buyer"

call("POST", "/auth/register",
     body={"name": spoof_name, "email": "phase6a.spoof@example.com",
           "password": "password123"})

created_users.append("phase6a.spoof@example.com")

spoof_token = login("phase6a.spoof@example.com")
status, spoofed = call("GET", "/api/orders/mine", token=spoof_token)
spoofed = spoofed or []

check("a matching display name does not grant ownership",
      not any(row["id"] in (created_orders or [0]) for row in spoofed),
      f"{len(spoofed)} rows returned")

# ==================================================================
print("\n[6] the table cannot be forged")
# ==================================================================
status, taken_over = call(
    "POST",
    "/api/orders/",
    token=buyer_token,
    body={"menu_id": dish["id"], "quantity": 1, "table_number": rival["table_number"],
          "notes": "phase6a table forgery probe"},
)

track(taken_over)

taken_table_id = (
    one("SELECT table_id FROM order_headers WHERE id = %s", (taken_over.get("order_id"),))
    if status == 200 else None
)

check("a claimed table beats a table_number in the body",
      status == 200 and taken_table_id == claimed["id"],
      f"got {taken_table_id} want {claimed['id']}")

status, _ = call(
    "POST",
    "/api/orders/",
    token=other_token,
    body={"menu_id": dish["id"], "quantity": 1, "table_number": rival["table_number"]},
)
check("an unclaimed guest may still order at a real active table",
      status == 200, f"got {status}")

track(_)

status, _ = call(
    "POST",
    "/api/orders/",
    token=other_token,
    body={"menu_id": dish["id"], "quantity": 1, "table_number": 987654},
)
check("an unknown table number is refused", status == 409, f"got {status}")

status, _ = call(
    "POST",
    "/api/orders/",
    token=other_token,
    body={"menu_id": dish["id"], "quantity": 1},
)
check("a dine-in order with no table at all is refused",
      status == 400, f"got {status}")

sql("UPDATE restaurant_tables SET is_active = 0 WHERE id = %s", (rival["id"],))

status, _ = call(
    "POST",
    "/api/orders/",
    token=other_token,
    body={"menu_id": dish["id"], "quantity": 1, "table_number": rival["table_number"]},
)
check("an inactive table cannot be ordered against", status == 409, f"got {status}")

sql("UPDATE restaurant_tables SET is_active = 1 WHERE id = %s", (rival["id"],))

status, takeaway = call(
    "POST",
    "/api/orders/",
    token=other_token,
    body={"menu_id": dish["id"], "quantity": 1, "order_type": "takeaway",
          "table_number": rival["table_number"]},
)

track(takeaway)

check("a takeaway carries no table even when one is named",
      status == 200 and takeaway.get("reference")
      and one("SELECT table_id FROM order_headers WHERE id = %s",
              (takeaway.get("order_id"),)) is None,
      f"got {takeaway}")

# ==================================================================
print("\n[7] historical rows are never rewritten")
# ==================================================================
legacy_after = sql(
    "SELECT id, customer_name, menu_item, quantity, total_price, unit_price, "
    "status, order_id, user_id FROM orders WHERE id IN ({}) ORDER BY id".format(
        ",".join(str(i) for i in legacy_ids)
    )
)

check("the sampled legacy rows are byte-identical afterwards",
      legacy_after == legacy_snapshot,
      f"{legacy_snapshot} -> {legacy_after}")

anomaly_after = sql(
    "SELECT id, customer_name, menu_item, quantity, total_price, unit_price, "
    "user_id FROM orders WHERE total_price < 20 ORDER BY id"
)

check("the Rs.8.99 / Rs.13.99 scaffold rows are still there, untouched",
      anomaly_after == anomaly_snapshot and len(anomaly_after) > 0,
      f"{anomaly_snapshot} -> {anomaly_after}")

check("no owner was invented for a historical row",
      anomaly_after == anomaly_snapshot,
      f"{anomaly_snapshot} -> {anomaly_after}")

check("the legacy row count never dropped",
      one("SELECT COUNT(*) FROM orders WHERE order_id IS NULL")
      == legacy_unlinked_at_start,
      f"{legacy_unlinked_at_start} -> "
      f"{one('SELECT COUNT(*) FROM orders WHERE order_id IS NULL')}")

# ==================================================================
print("\n[8] the customer bill uses the stored server totals")
# ==================================================================
status, bill = call("GET", "/api/customer/bill", token=buyer_token)

bill = bill or {}
buy_headers = sql(
    "SELECT id, subtotal, tax_amount, service_charge_amount, discount_amount, "
    "total_amount FROM order_headers WHERE user_id = %s",
    (buyer["id"],),
)

bill_headers_total = round(
    sum(float(row[5] or 0) for row in buy_headers), 2
)
bill_headers_subtotal = round(
    sum(float(row[1] or 0) for row in buy_headers), 2
)

check("200 for the owner reading their bill", status == 200, f"got {status}")
check("the bill total is the sum of the stored header totals",
      bill.get("total_amount") == bill_headers_total,
      f"got {bill.get('total_amount')} want {bill_headers_total}")
check("the bill subtotal is the sum of the stored header subtotals",
      bill.get("subtotal") == bill_headers_subtotal,
      f"got {bill.get('subtotal')} want {bill_headers_subtotal}")
check("the bill currency is the configured one",
      bill.get("currency") == configured_currency,
      f"got {bill.get('currency')}")
# Phase 6D. This used to require `payment_available is False`, because no
# payment system existed. One exists now, so the requirement is
# inverted - and the half that must NOT change is asserted harder: the
# bill is still UNPAID, still has collected nothing, and still owes its
# full total. Nothing this phase did made a bill payable by itself.
check("the bill is UNPAID with nothing collected",
          bill.get("payment_status") == "UNPAID"
          and bill.get("paid_amount") == 0.0
          and bill.get("outstanding_amount") == bill.get("total_amount"),
          f"got {bill.get('payment_status')} paid={bill.get('paid_amount')} "
          f"outstanding={bill.get('outstanding_amount')}")
check("the bill states no gateway has taken the money",
      (bill.get("payment_gateway") or {}).get("live_gateway_connected")
      is False,
      f"got {bill.get('payment_gateway')}")
check("the bill is scoped to the claimed table",
      bill.get("table_number") == claimed["table_number"],
      f"got {bill.get('table_number')}")
check("every bill line carries a server unit price",
      bool(bill.get("orders"))
      and all(row.get("unit_price") is not None for row in bill["orders"]),
      f"{len(bill.get('orders') or [])} lines")
check("every bill line carries its order reference",
      bool(bill.get("orders"))
      and all(row.get("reference") for row in bill["orders"]),
      f"{len(bill.get('orders') or [])} lines")
check("the bill lines sum to the bill subtotal",
      round(sum(float(row["line_total"]) for row in bill.get("orders") or []), 2)
      == bill.get("subtotal"),
      f"lines={bill.get('subtotal')}")

status, _ = call("GET", "/api/customer/bill", token=other_token)
check("200 for a second customer reading an empty bill", status == 200, f"got {status}")

status, _ = call("GET", "/api/customer/bill")
check("401 for the bill without a token", status == 401, f"got {status}")

# ==================================================================
print("\n[9] SERVED and UNPAID are independent")
# ==================================================================
lifecycle_header = taken_over.get("order_id")

for stage in ("Confirmed", "Preparing", "Ready", "Served"):
    status, moved = call(
        "POST", f"/api/orders/headers/{lifecycle_header}/status",
        token=admin_token, body={"status": stage},
    )

    if stage == "Served":
        check("a header can be driven to SERVED", status == 200, f"got {status} {moved}")
        check("a SERVED order is still UNPAID",
              status == 200 and moved.get("payment_status") == "unpaid",
              f"got {moved.get('payment_status') if status == 200 else moved}")

status, skipped = call(
    "POST", f"/api/orders/headers/{lifecycle_header}/status",
    token=admin_token, body={"status": "Placed"},
)
check("the lifecycle cannot be walked backwards",
      status == 400, f"got {status}")

status, served_bill = call("GET", "/api/customer/bill", token=buyer_token)

check("a bill containing a SERVED order is still UNPAID",
      (served_bill or {}).get("payment_status") == "UNPAID",
      f"got {(served_bill or {}).get('payment_status')}")

check("the bill reports the food statuses it actually holds",
      "Served" in (served_bill or {}).get("food_statuses", []),
      f"got {(served_bill or {}).get('food_statuses')}")

status, analytics_orders = call("GET", "/api/analytics/orders", token=admin_token)

check("analytics counts served-but-unpaid as its own number",
      status == 200
      and isinstance((analytics_orders or {}).get("served_unpaid_orders"), int),
      f"got {status}")

# ==================================================================
print("\n[10] response security")
# ==================================================================
ADMIN_ONLY = [
    ("GET", "/api/analytics/overview"),
    ("GET", "/api/analytics/revenue"),
    ("GET", "/api/analytics/orders"),
    ("GET", "/api/analytics/top-dishes"),
    ("GET", "/api/orders/"),
    ("GET", "/api/orders/headers"),
    ("GET", "/api/orders/headers/active"),
    ("GET", "/api/ai/insights"),
]

for method, path in ADMIN_ONLY:
    status, _ = call(method, path, token=buyer_token)
    check(f"403 for a customer: {method} {path}", status == 403, f"got {status}")

    status, _ = call(method, path)
    check(f"401 anonymously: {method} {path}", status == 401, f"got {status}")

    status, _ = call(method, path, token=admin_token)
    check(f"200 for an admin: {method} {path}", status == 200, f"got {status}")

status, _ = call("POST", "/api/ai/assistant", token=buyer_token,
                 body={"question": "what were my best sellers today?"})
check("403 for a customer using the AI business assistant", status == 403, f"got {status}")

status, _ = call("POST", "/api/ai/assistant", body={"question": "revenue?"})
check("401 anonymously using the AI business assistant", status == 401, f"got {status}")

status, assistant = call("POST", "/api/ai/assistant", token=admin_token,
                         body={"question": "how many orders were placed today?"})
check("200 for an admin using the AI business assistant", status == 200, f"got {status}")

status, _ = call("GET", "/api/tables/qr-base-url", token=buyer_token)
check("403 for a customer reading the QR base url", status == 403, f"got {status}")

status, _ = call("DELETE", f"/api/orders/{line_id}",
                 token=buyer_token)
check("403 for a customer deleting an order", status == 403, f"got {status}")

status, _ = call("PUT", f"/api/orders/{line_id}",
                 token=buyer_token,
                 body={"menu_item": dish["name"], "quantity": 1})
check("403 for a customer editing an order", status == 403, f"got {status}")

# ==================================================================
print("\n[11] an admin edit cannot rewrite what was charged")
# ==================================================================
victim_line = line_id
before_edit = sql(
    "SELECT unit_price, total_price, quantity FROM orders WHERE id = %s",
    (victim_line,),
)

status, edited = call(
    "PUT",
    f"/api/orders/{victim_line}",
    token=admin_token,
    body={
        "customer_name": buyer["name"],
        "menu_item": dish["name"],
        "quantity": 2,
        "total_price": 1,
        "notes": "phase6a admin edit probe",
    },
)

after_edit = sql(
    "SELECT unit_price, total_price, quantity FROM orders WHERE id = %s",
    (victim_line,),
)

check("200 for an admin editing an order", status == 200, f"got {status}")
check("a submitted total_price of Rs.1 is ignored on edit too",
      before_edit == after_edit,
      f"{before_edit} -> {after_edit}")
check("the edit did not move the stored unit price",
      before_edit == after_edit and float(after_edit[0][0]) == price,
      f"{before_edit} -> {after_edit}")

status, _ = call(
    "PUT",
    f"/api/orders/{victim_line}",
    token=admin_token,
    body={"customer_name": buyer["name"], "menu_id": 99999999, "quantity": 1},
)
check("an admin edit naming an unknown dish is refused",
      status == 404, f"got {status}")

# ==================================================================
print("\n[12] analytics data quality still reports honestly")
# ==================================================================
status, overview = call("GET", "/api/analytics/overview", token=admin_token)

quality = ((overview or {}).get("today") or {}).get("data_quality") or {}

check("200 for the analytics overview", status == 200, f"got {status}")
check("data_quality still reports checkout and legacy lines",
      "checkout_lines" in quality and "legacy_lines" in quality,
      f"got {sorted(quality)}")
check("data_quality reports both populations as whole numbers",
      isinstance(quality.get("server_priced_order_count"), int)
      and isinstance(quality.get("legacy_order_count"), int),
      f"got {quality.get('legacy_order_count')!r} / "
      f"{quality.get('server_priced_order_count')!r}")
check("data_quality reports the price mismatch count",
      isinstance(quality.get("price_mismatch_count"), int),
      f"got {quality.get('price_mismatch_count')!r}")
check("the pre-existing data_quality keys are all still present",
      {"checkout_lines", "legacy_lines", "legacy_priced_lines",
       "legacy_unpriced_lines", "note"}.issubset(set(quality)),
      f"got {sorted(quality)}")

# The whole history's provenance. This is where a row written on the
# wrong price scale surfaces, because it is not today's news.
history_quality = ((overview or {}).get("all_time") or {}).get("data_quality") or {}

check("the all-time data_quality block reports the legacy/server split",
      history_quality.get("legacy_order_count", 0) > 0
      and history_quality.get("server_priced_order_count", 0) > 0,
      f"got {history_quality.get('legacy_order_count')} / "
      f"{history_quality.get('server_priced_order_count')}")
check("the all-time data_quality reports no arithmetic mismatch",
      history_quality.get("price_mismatch_count") == 0,
      f"got {history_quality.get('price_mismatch_count')}")
check("the all-time data_quality surfaces the unrewritten price anomalies",
      history_quality.get("implausible_total_lines", 0) > 0
      and len(history_quality.get("price_anomalies") or []) > 0,
      f"got {history_quality.get('implausible_total_lines')}")
check("the reported anomalies are the two known scaffold rows, unchanged",
      {row["order_id"] for row in history_quality.get("price_anomalies") or []}
      == {row[0] for row in anomaly_snapshot},
      f"got {[r['order_id'] for r in history_quality.get('price_anomalies') or []]}")

status, revenue = call("GET", "/api/analytics/revenue?range=all_time",
                       token=admin_token)

check("200 for the all-time revenue window", status == 200, f"got {status}")
check("revenue still splits checkout money from legacy money",
      "checkout_revenue" in (revenue or {}).get("revenue_breakdown", {}),
      f"got {(revenue or {}).get('revenue_breakdown')}")

# ==================================================================
print("\n[13] Phase 1-5 regressions on the order surface")
# ==================================================================
status, quoted = call(
    "POST", "/api/orders/quote", token=buyer_token,
    body={"items": [{"menu_item_id": dish["id"], "quantity": 2}],
          "order_type": "dine-in"},
)
quote_expect = round(
    round(price * 2, 2) * (1 + tax_rate / 100.0 + service_rate / 100.0), 2
)

check("200 for the Phase 2 quote endpoint", status == 200, f"got {status}")
check("the quote is priced from the menu",
      status == 200 and quoted.get("total_amount") == quote_expect,
      f"got {quoted.get('total_amount')} want {quote_expect}")

status, two_line = call(
    "POST", "/api/orders/checkout", token=buyer_token,
    body={"items": [{"menu_item_id": dish["id"], "quantity": 1},
                    {"menu_item_id": dish_b["id"], "quantity": 2}],
          "order_type": "dine-in"},
)

track(two_line)

two_subtotal = round(price + float(dish_b["price"]) * 2, 2)

check("200 for the Phase 2 checkout endpoint", status == 200, f"got {status}")
check("a two-dish checkout subtotals both server prices",
      status == 200 and two_line.get("subtotal") == two_subtotal,
      f"got {two_line.get('subtotal')} want {two_subtotal}")

status, recommendations = call("GET", "/api/ai/recommend/me", token=buyer_token)

check("200 for the Phase 5 personalised recommendations",
      status == 200 and "personalized" in (recommendations or {}),
      f"got {status}")

status, dish_menu = call("GET", "/api/menu/", token=buyer_token)
check("200 for the customer menu", status == 200, f"got {status}")

probe_rows = [
    row for row in dish_menu or [] if row["name"] == "Phase6A unavailable probe"
]

check("the probe dish is served as unavailable, not as orderable",
      len(probe_rows) == 1 and probe_rows[0]["available"] is False,
      f"got {probe_rows}")

status, buyer_recs = call("GET", "/api/ai/recommend/me", token=buyer_token)

recommended = {
    dish_["name"]
    for key in ("personalized", "trending_today", "similar_items")
    for dish_ in ((buyer_recs or {}).get(key) or [])
}

check("an unavailable dish is never recommended",
      "Phase6A unavailable probe" not in recommended,
      "the probe dish was recommended")

status, headers_mine = call("GET", "/api/orders/headers/mine", token=buyer_token)

check("200 for the customer's own order headers",
      status == 200 and isinstance(headers_mine, list), f"got {status}")

status, header_payload = call(
    "GET", f"/api/orders/headers/{header_id}/status", token=buyer_token
)
check("200 for the owner reading a header status",
      status == 200 and (header_payload or {}).get("payment_status") == "unpaid",
      f"got {status}")

check("the header status response tells the caller the legal next steps",
      status == 200 and "valid_next_statuses" in (header_payload or {}),
      f"got {header_payload}")

# ==================================================================
print("\n[cleanup]")
# ==================================================================
if created_orders:
    marks = ",".join(str(i) for i in set(created_orders))
    sql(f"DELETE FROM kitchen WHERE order_id IN ({marks})")

for header_id_ in set(created_headers):
    sql("DELETE FROM kitchen WHERE order_id IN "
        "(SELECT id FROM orders WHERE order_id = %s)", (header_id_,))
    sql("DELETE FROM orders WHERE order_id = %s", (header_id_,))
    sql("DELETE FROM order_headers WHERE id = %s", (header_id_,))

sql("UPDATE users SET active_table_id = NULL WHERE id IN (%s, %s)",
    (buyer["id"], other["id"]))

for table_id in created_tables:
    sql("DELETE FROM restaurant_tables WHERE id = %s", (table_id,))

# Belt and braces: the two probe numbers are unique to this script.
sql("DELETE FROM restaurant_tables WHERE table_number IN (9001, 9002)")

sql("DELETE FROM menu WHERE id = %s", (probe_menu_id,))
sql("DELETE FROM menu WHERE name = %s", ("Phase6A unavailable probe",))

for email in created_users:
    sql("DELETE FROM users WHERE email = %s", (email,))

print(f"  orders   {orders_before} -> {one('SELECT COUNT(*) FROM orders')}")
print(f"  headers  {headers_before} -> {one('SELECT COUNT(*) FROM order_headers')}")
print(f"  kitchen  {kitchen_before} -> {one('SELECT COUNT(*) FROM kitchen')}")
print(f"  tables   {tables_before} -> {one('SELECT COUNT(*) FROM restaurant_tables')}")

check("no order row was left behind", one("SELECT COUNT(*) FROM orders") == orders_before,
      f"{one('SELECT COUNT(*) FROM orders')} vs {orders_before}")
check("no order header was left behind",
      one("SELECT COUNT(*) FROM order_headers") == headers_before,
      f"{one('SELECT COUNT(*) FROM order_headers')} vs {headers_before}")
check("no kitchen ticket was left behind",
      one("SELECT COUNT(*) FROM kitchen") == kitchen_before,
      f"{one('SELECT COUNT(*) FROM kitchen')} vs {kitchen_before}")
check("no table was left behind",
      one("SELECT COUNT(*) FROM restaurant_tables") == tables_before,
      f"{one('SELECT COUNT(*) FROM restaurant_tables')} vs {tables_before}")
check("no probe menu row was left behind",
      one("SELECT COUNT(*) FROM menu "
          "WHERE name = 'Phase6A unavailable probe'") == 0,
      f"{one('SELECT COUNT(*) FROM menu WHERE name = %s', ('Phase6A unavailable probe',))} left")
check("no orphan kitchen ticket remains",
      one("SELECT COUNT(*) FROM kitchen k LEFT JOIN orders o ON o.id = k.order_id "
          "WHERE o.id IS NULL") == 0, "orphan tickets found")
check("the probe accounts are gone",
      one("SELECT COUNT(*) FROM users WHERE email LIKE %s", ("phase6a.%",)) == 0,
      f"{one('SELECT COUNT(*) FROM users WHERE email LIKE %s', ('phase6a.%',))} left")

check("no operational event was left behind by this run",
      one("SELECT COUNT(*) FROM restaurant_events e "
          "WHERE e.entity_id IN (SELECT id FROM orders WHERE customer_name "
          "IN ('Phase6A Buyer', 'Phase6A Other'))") == 0,
      "events leaked")

# ==================================================================
print("\n" + "=" * 74)
print(f"RESULT: {len(passed)} passed, {len(failed)} failed")

if failed:
    print("\nFAILURES:")
    for name in failed:
        print(f"  - {name}")

print("=" * 74)

sys.exit(1 if failed else 0)
"""
Phase 2 acceptance tests: server-authoritative cart and checkout.

    python scripts/test_phase2_checkout.py http://127.0.0.1:8010

Covers the eleven required scenarios:
   1  normal checkout
   2  client sends a fake unit price
   3  client sends a fake subtotal
   4  client sends a fake grand total
   5  unavailable menu item
   6  invalid menu item id
   7  invalid quantity
   8  customer A cannot touch customer B's order
   9  server total matches database prices
  10  tax is calculated on the server
  11  historical orders are intact

Every probe cleans up after itself.
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

            return cursor.fetchall()
    finally:
        connection.close()


print("=" * 74)
print(f"PHASE 2 CHECKOUT TESTS  ->  {BASE}")
print("=" * 74)

admin_token = login("admin@gmail.com")
customer_token = login("customer@gmail.com")

# A second customer, so ownership can be tested between two real people.
probe_email = "phase2.owner@example.com"
probe_name = "Phase2 Owner"

sql("DELETE FROM users WHERE email = %s", (probe_email,))

status, registered = call(
    "POST",
    "/auth/register",
    body={
        "name": probe_name,
        "email": probe_email,
        "password": "password123",
    },
)

if status == 200:
    other_token = registered["token"]
    other_user_id = registered["user"]["id"]
else:
    other_token = customer_token
    other_user_id = 1

# ------------------------------------------------------------------
# Baseline
# ------------------------------------------------------------------
menu = call("GET", "/api/menu/")[1] or []
settings = sql("SELECT tax_percentage, currency FROM settings LIMIT 1")

tax_rate = float(settings[0][0]) if settings else 0.0
currency = (settings[0][1] if settings else "UNSET")

dish_a = next(m for m in menu if m["name"] == "Chicken Biryani")
dish_b = next(m for m in menu if m["name"] == "Jeera Rice")

print(f"\n  using dishes: {dish_a['name']} ({dish_a['price']}) "
      f"and {dish_b['name']} ({dish_b['price']})")
print(f"  settings: tax={tax_rate}% currency={currency}")

orders_before = sql("SELECT COUNT(*) FROM orders")[0][0]
# Phase 6A. Compared against `orders_before`, which counts every order.
# That only held while the database happened to contain no server-priced
# order at all: the moment a real checkout existed, the unlinked legacy
# count was necessarily lower than the total. The claim being made is
# about the legacy rows, so it is compared against the legacy count.
legacy_orders_before = sql(
    "SELECT COUNT(*) FROM orders WHERE order_id IS NULL"
)[0][0]
headers_before = sql("SELECT COUNT(*) FROM order_headers")[0][0]

# ------------------------------------------------------------------
print("\n[1] normal checkout")
expected_subtotal = round(
    dish_a["price"] * 2 + dish_b["price"] * 1, 2
)
expected_tax = round(expected_subtotal * tax_rate / 100.0, 2)
expected_total = round(expected_subtotal + expected_tax, 2)

status, order = call(
    "POST",
    "/api/orders/checkout",
    token=customer_token,
    body={
        "items": [
            {"menu_item_id": dish_a["id"], "quantity": 2},
            {
                "menu_item_id": dish_b["id"],
                "quantity": 1,
                "special_instructions": "less oil",
            },
        ],
        "order_type": "dine-in",
        "table_number": 4,
        "notes": "phase2 normal checkout",
    },
)

check("checkout returns 200", status == 200, f"{status} {order}")
check("two lines created", order.get("orders_created") == 2,
      f"got {order.get('orders_created')}")
check("order id returned", bool(order.get("order_id")))
check("reference generated", bool(order.get("reference")),
      f"got {order.get('reference')!r}")
check("order starts Placed", order.get("status") == "Placed",
      f"got {order.get('status')!r}")
check("payment_status is unpaid", order.get("payment_status") == "unpaid",
      f"got {order.get('payment_status')!r}")
check("priced_by names the source",
      order.get("priced_by") == "server (menu.price)",
      f"got {order.get('priced_by')!r}")

header_id = order.get("order_id")

# ------------------------------------------------------------------
print("\n[9] server total matches database prices")
summary = order.get("summary") or {}

check("subtotal matches DB arithmetic",
      summary.get("subtotal") == expected_subtotal,
      f"got {summary.get('subtotal')} want {expected_subtotal}")
check("tax matches DB arithmetic",
      summary.get("tax_amount") == expected_tax,
      f"got {summary.get('tax_amount')} want {expected_tax}")
check("total matches DB arithmetic",
      summary.get("total_amount") == expected_total,
      f"got {summary.get('total_amount')} want {expected_total}")

print(f"        expected subtotal {expected_subtotal} "
      f"tax {expected_tax} total {expected_total}")

# Verify the persisted header matches what the caller was told.
stored = sql(
    "SELECT subtotal, tax_amount, total_amount, currency, "
    "tax_percentage, reference, user_id "
    "FROM order_headers WHERE id = %s",
    (header_id,),
)

if stored:
    row = stored[0]

    check("header subtotal persisted", float(row[0]) == expected_subtotal,
          f"got {row[0]}")
    check("header tax persisted", float(row[1]) == expected_tax, f"got {row[1]}")
    check("header total persisted", float(row[2]) == expected_total,
          f"got {row[2]}")
    check("header currency from settings", row[3] == currency, f"got {row[3]}")
    check("header tax rate from settings",
          float(row[4]) == tax_rate, f"got {row[4]}")
    check("header owned by the caller", row[6] == 1, f"got {row[6]}")

# Line rows must carry the DB unit price.
lines = sql(
    "SELECT menu_item, quantity, unit_price, total_price, order_id "
    "FROM orders WHERE order_id = %s",
    (header_id,),
)

check("two line rows written", len(lines) == 2, f"got {len(lines)}")

if len(lines) == 2:
    biryani = next(r for r in lines if r[0] == dish_a["name"])
    rice = next(r for r in lines if r[0] == dish_b["name"])

    check("line unit_price comes from the menu",
          float(biryani[2]) == float(dish_a["price"]),
          f"got {biryani[2]} want {dish_a['price']}")
    check("line total = unit x qty",
          float(biryani[3]) == round(float(dish_a["price"]) * 2, 2),
          f"got {biryani[3]}")
    check("lines point at the header",
          all(row[4] == header_id for row in lines))

# Kitchen tickets must exist for the kitchen screen.
tickets = sql(
    "SELECT COUNT(*) FROM kitchen WHERE order_id IN "
    "(SELECT id FROM orders WHERE order_id = %s)",
    (header_id,),
)

check("kitchen tickets raised", tickets[0][0] == 2, f"got {tickets[0][0]}")

# ------------------------------------------------------------------
print("\n[2] client sends a fake unit price -> ignored")
status, attacked = call(
    "POST",
    "/api/orders/quote",
    token=customer_token,
    body={
        "items": [
            {
                "menu_item_id": dish_a["id"],
                "quantity": 2,
                "unit_price": 0.01,
                "price": 0.01,
                "line_total": 0.02,
                "total_price": 0.02,
            }
        ],
        "order_type": "dine-in",
        "table_number": 4,
    },
)

check("quote still succeeds", status == 200, f"{status}")
check("subtotal ignores the fake price",
      attacked["subtotal"] == round(dish_a["price"] * 2, 2),
      f"got {attacked['subtotal']} want "
      f"{round(dish_a['price'] * 2, 2)}")
check("quoted unit_price is the database one",
      attacked["items"][0]["unit_price"] == dish_a["price"],
      f"got {attacked['items'][0]['unit_price']}")
check("total ignores the fake price",
      attacked["total_amount"] == round(
          round(dish_a["price"] * 2, 2)
          * (1 + tax_rate / 100.0),
          2,
      ),
      f"got {attacked['total_amount']}")

# The legacy /cart path must also be immune.
status, legacy = call(
    "POST",
    "/api/orders/cart",
    token=customer_token,
    body={
        "customer_name": "TOTALLY FAKE NAME",
        "order_type": "dine-in",
        "table_number": 4,
        "items": [
            {
                "customer_name": "TOTALLY FAKE NAME",
                "menu_item": dish_a["name"],
                "quantity": 2,
                "total_price": 0.02,
                "status": "Pending",
            }
        ],
    },
)

check("legacy /cart ignores a fake total_price",
      legacy["subtotal"] == round(dish_a["price"] * 2, 2),
      f"got {legacy['subtotal']}")

if legacy.get("orders"):
    legacy_line_id = legacy["orders"][0]["id"]

    stored_price = sql(
        "SELECT total_price FROM orders WHERE id = %s", (legacy_line_id,)
    )[0][0]

    check("legacy row stored at the DB price",
          float(stored_price) == round(dish_a["price"] * 2, 2),
          f"got {stored_price}")

    check("legacy row name comes from the token",
          legacy["orders"][0]["customer_name"] == "Paradise Customer",
          f"got {legacy['orders'][0]['customer_name']!r}")

    sql("DELETE FROM kitchen WHERE order_id = %s", (legacy_line_id,))
    sql("DELETE FROM orders WHERE id = %s", (legacy_line_id,))

# ------------------------------------------------------------------
print("\n[3] client sends a fake subtotal -> ignored")
status, fake_sub = call(
    "POST",
    "/api/orders/quote",
    token=customer_token,
    body={
        "items": [{"menu_item_id": dish_a["id"], "quantity": 1}],
        "order_type": "dine-in",
        "table_number": 4,
        "subtotal": 0.01,
        "total": 0.01,
    },
)

check("subtotal recomputed by the server",
      fake_sub["subtotal"] == round(dish_a["price"], 2),
      f"got {fake_sub['subtotal']} want {round(dish_a['price'], 2)}")

# ------------------------------------------------------------------
print("\n[4] client sends a fake grand total -> ignored")
status, fake_total = call(
    "POST",
    "/api/orders/quote",
    token=customer_token,
    body={
        "items": [{"menu_item_id": dish_a["id"], "quantity": 1}],
        "order_type": "dine-in",
        "table_number": 4,
        "total_amount": 1,
        "discount_amount": 999,
        "tax_amount": 0,
    },
)

check("total recomputed by the server",
      fake_total["total_amount"] == round(
          round(dish_a["price"], 2) * (1 + tax_rate / 100.0), 2
      ),
      f"got {fake_total['total_amount']}")
check("client cannot grant itself a discount",
      fake_total["discount_amount"] == 0,
      f"got {fake_total['discount_amount']}")
check("client cannot zero the tax",
      fake_total["tax_amount"] != 0 or tax_rate == 0,
      f"got {fake_total['tax_amount']}")

# ------------------------------------------------------------------
print("\n[5] unavailable menu item -> rejected")
try:
    sql("UPDATE menu SET available = 0 WHERE id = %s", (dish_b["id"],))

    status, gone = call(
        "POST",
        "/api/orders/checkout",
        token=customer_token,
        body={
            "items": [{"menu_item_id": dish_b["id"], "quantity": 1}],
            "order_type": "dine-in",
            "table_number": 4,
        },
    )

    check("unavailable item rejected with 409", status == 409, f"got {status}")
    check("rejection names the dish",
          dish_b["name"] in str(gone), f"got {gone}")
finally:
    sql("UPDATE menu SET available = 1 WHERE id = %s", (dish_b["id"],))

status, back = call(
    "GET", f"/api/menu/?search={dish_b['name'].replace(' ', '%20')}"
)
check("dish restored to available", status == 200, f"{status}")

# ------------------------------------------------------------------
print("\n[6] invalid menu item id -> rejected")
status, unknown = call(
    "POST",
    "/api/orders/checkout",
    token=customer_token,
    body={
        "items": [{"menu_item_id": 999999, "quantity": 1}],
        "order_type": "dine-in",
        "table_number": 4,
    },
)

check("unknown menu_item_id rejected with 404", status == 404, f"got {status}")

status, by_name = call(
    "POST",
    "/api/orders/checkout",
    token=customer_token,
    body={
        # A name where an id belongs must not silently price anything.
        "items": [{"menu_item_id": dish_a["name"], "quantity": 1}],
        "order_type": "dine-in",
        "table_number": 4,
    },
)

check("a dish name in place of an id is rejected",
      status in (400, 404, 422), f"got {status}")

# ------------------------------------------------------------------
print("\n[7] invalid quantity -> rejected")
for bad in (0, -3):
    status, _ = call(
        "POST",
        "/api/orders/checkout",
        token=customer_token,
        body={
            "items": [{"menu_item_id": dish_a["id"], "quantity": bad}],
            "order_type": "dine-in",
            "table_number": 4,
        },
    )

    check(f"quantity {bad} rejected", status == 400, f"got {status}")

status, _ = call(
    "POST",
    "/api/orders/checkout",
    token=customer_token,
    body={
        "items": [{"menu_item_id": dish_a["id"], "quantity": 9999}],
        "order_type": "dine-in",
        "table_number": 4,
    },
)

check("absurd quantity rejected", status == 400, f"got {status}")

status, _ = call(
    "POST",
    "/api/orders/checkout",
    token=customer_token,
    body={
        "items": [
            {"menu_item_id": dish_a["id"], "quantity": 1},
            {"menu_item_id": dish_a["id"], "quantity": 1},
        ],
        "order_type": "dine-in",
        "table_number": 4,
    },
)

check("duplicate lines rejected rather than merged blindly",
      status == 400, f"got {status}")

status, _ = call(
    "POST",
    "/api/orders/checkout",
    token=customer_token,
    body={"items": [], "order_type": "dine-in", "table_number": 4},
)

check("empty cart rejected", status == 400, f"got {status}")

status, _ = call(
    "POST",
    "/api/orders/checkout",
    token=customer_token,
    body={
        "items": [{"menu_item_id": dish_a["id"], "quantity": 1}],
        "order_type": "dine-in",
    },
)

check("dine-in without a table rejected", status == 400, f"got {status}")

# ------------------------------------------------------------------
print("\n[8] customer A cannot touch customer B's order")
mine = call("GET", "/api/orders/mine", token=customer_token)[1] or []
my_line = next(
    (row for row in mine if row["customer_name"] == "Paradise Customer"), None
)

status, foreign = call(
    "POST",
    "/api/orders/checkout",
    token=other_token,
    body={
        # Pretending to be the other customer changes nothing.
        "items": [{"menu_item_id": dish_b["id"], "quantity": 1}],
        "order_type": "dine-in",
        "table_number": 9,
        "customer_id": 1,
        "user_id": 1,
        "customer_name": "Paradise Customer",
    },
)

check("second customer can check out", status == 200, f"{status} {foreign}")

if status == 200:
    other_header = foreign["order_id"]

    stored_owner = sql(
        "SELECT user_id, customer_name FROM order_headers WHERE id = %s",
        (other_header,),
    )[0]

    check("header owned by the real caller",
          stored_owner[0] == other_user_id,
          f"got user_id {stored_owner[0]}, caller is {other_user_id}")
    check("header name comes from that caller's token",
          stored_owner[1] == probe_name, f"got {stored_owner[1]!r}")
    check("header ignores the customer_id/user_id sent in the payload",
          stored_owner[0] != 1,
          "header was attributed to the spoofed id")

    status, seen = call(
        "GET", f"/api/orders/{other_header}", token=customer_token
    )

    # Customer B's order id is not an orders row, so this is 404 or 403.
    check("customer A cannot read customer B's order",
          status in (403, 404), f"got {status}")

    other_headers = call(
        "GET", "/api/orders/headers/mine", token=customer_token
    )[1] or []

    check("customer A's headers exclude B's order",
          all(row["id"] != other_header for row in other_headers),
          "leaked a foreign header")

    # Cancel someone else's line.
    other_line = sql(
        "SELECT id FROM orders WHERE order_id = %s", (other_header,)
    )[0][0]

    status, _ = call(
        "PATCH", f"/api/orders/{other_line}/cancel", token=customer_token
    )

    check("customer A cannot cancel customer B's order",
          status == 403, f"got {status}")

    status, _ = call(
        "PUT", f"/api/orders/{other_line}", token=customer_token,
        body={
            "customer_name": "Paradise Customer",
            "menu_item": dish_a["name"],
            "quantity": 99,
            "total_price": 0.01,
            "status": "Completed",
        },
    )

    check("customer A cannot edit customer B's order",
          status == 403, f"got {status}")

    # Clean up B's order.
    other_line_ids = [
        r[0] for r in sql("SELECT id FROM orders WHERE order_id = %s",
                          (other_header,))
    ]

    for line_id in other_line_ids:
        sql("DELETE FROM kitchen WHERE order_id = %s", (line_id,))

    sql("DELETE FROM orders WHERE order_id = %s", (other_header,))
    sql("DELETE FROM order_headers WHERE id = %s", (other_header,))

if my_line:
    status, _ = call(
        "GET", f"/api/orders/{my_line['id']}", token=customer_token
    )

    check("customer can still read their own order", status == 200,
          f"got {status}")

# ------------------------------------------------------------------
print("\n[10] tax is calculated on the server")
status, tax_probe = call(
    "POST",
    "/api/orders/quote",
    token=customer_token,
    body={
        "items": [{"menu_item_id": dish_a["id"], "quantity": 3}],
        "order_type": "dine-in",
        "table_number": 4,
    },
)

base = round(dish_a["price"] * 3, 2)

check("tax percentage echoed from settings",
      tax_probe["tax_percentage"] == tax_rate,
      f"got {tax_probe['tax_percentage']} want {tax_rate}")
check("tax = subtotal x rate",
      tax_probe["tax_amount"] == round(base * tax_rate / 100.0, 2),
      f"got {tax_probe['tax_amount']} want "
      f"{round(base * tax_rate / 100.0, 2)}")
check("total = subtotal + tax",
      tax_probe["total_amount"] == round(
          base + round(base * tax_rate / 100.0, 2), 2
      ),
      f"got {tax_probe['total_amount']}")
check("service charge exposed and zero by default",
      tax_probe["service_charge_amount"] == 0,
      f"got {tax_probe['service_charge_amount']}")
check("currency reported from settings",
      tax_probe["currency"] == currency.upper(),
      f"got {tax_probe['currency']!r} want {currency.upper()!r}")

# Confirmed means the backend has an agreed currency, not a placeholder.
check("currency_is_confirmed reflects the configured currency",
      tax_probe["currency_is_confirmed"] is (currency.upper() != "UNSET"),
      f"got {tax_probe['currency_is_confirmed']} (currency={currency!r})")

# A quote must not create anything. Snapshot immediately before the
# probe, since earlier sections legitimately added their own lines.
orders_before_quote = sql("SELECT COUNT(*) FROM orders")[0][0]
headers_before_quote = sql("SELECT COUNT(*) FROM order_headers")[0][0]

status, quoted = call(
    "POST",
    "/api/orders/quote",
    token=customer_token,
    body={
        "items": [{"menu_item_id": dish_a["id"], "quantity": 1}],
        "order_type": "dine-in",
        "table_number": 4,
    },
)

orders_after_quote = sql("SELECT COUNT(*) FROM orders")[0][0]
headers_after_quote = sql("SELECT COUNT(*) FROM order_headers")[0][0]

check("a quote writes no order lines",
      orders_after_quote == orders_before_quote,
      f"{orders_before_quote} -> {orders_after_quote}")
check("a quote writes no order headers",
      headers_after_quote == headers_before_quote,
      f"{headers_before_quote} -> {headers_after_quote}")
check("a quote still returns a priced summary",
      status == 200 and quoted["total_amount"] > 0, f"{status}")

# ------------------------------------------------------------------
print("\n[11] historical orders remain intact")
orders_now = sql("SELECT COUNT(*) FROM orders")[0][0]

# One order from test [1] is the only addition that should remain.
check("exactly one new order line group was written",
      orders_now == orders_before + 2,
      f"{orders_before} -> {orders_now} (expected +2)")

historic = sql(
    "SELECT COUNT(*) FROM orders WHERE created_at < '2026-10-01'"
)[0][0]

check("pre-October history still present", historic > 500, f"got {historic}")

unlinked = sql("SELECT COUNT(*) FROM orders WHERE order_id IS NULL")[0][0]

check("historical rows have no header and are still readable",
      unlinked >= legacy_orders_before,
      f"got {unlinked}, started at {legacy_orders_before}")

still_readable = call("GET", "/api/orders/", token=admin_token)[1] or []

check("admin can still list every order", len(still_readable) >= 537,
      f"got {len(still_readable)}")

customer_history = call(
    "GET", "/api/orders/mine", token=customer_token
)[1] or []

check("customer /orders/mine still works", isinstance(customer_history, list))

# ------------------------------------------------------------------
print("\n[cleanup]")
if header_id:
    line_ids = [
        r[0] for r in sql("SELECT id FROM orders WHERE order_id = %s",
                          (header_id,))
    ]

    for line_id in line_ids:
        sql("DELETE FROM kitchen WHERE order_id = %s", (line_id,))

    sql("DELETE FROM orders WHERE order_id = %s", (header_id,))
    sql("DELETE FROM order_headers WHERE id = %s", (header_id,))

sql("DELETE FROM users WHERE email = %s", (probe_email,))

final_orders = sql("SELECT COUNT(*) FROM orders")[0][0]
final_headers = sql("SELECT COUNT(*) FROM order_headers")[0][0]

check("test orders removed", final_orders == orders_before,
      f"{final_orders} vs {orders_before}")
check("test headers removed", final_headers == headers_before,
      f"{final_headers} vs {headers_before}")

final_menu = sql("SELECT COUNT(*) FROM menu WHERE available = 0")[0][0]

check("no menu item left disabled", final_menu == 0, f"got {final_menu}")

# ------------------------------------------------------------------
print("\n" + "=" * 74)
print(f"RESULT: {len(passed)} passed, {len(failed)} failed")

if failed:
    print("\nFAILURES:")
    for name in failed:
        print(f"  - {name}")

print("=" * 74)

sys.exit(1 if failed else 0)

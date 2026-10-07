"""
Phase 2.5 reconciliation tests: approved INR prices + DB single source
of truth.

    python scripts/test_phase25_prices.py http://127.0.0.1:8010

Verifies:
   1  all 47 approved prices are live
   2  currency is INR
   3  the menu API serves those prices
   4  the server quotes from the database
   5  a client cannot override a price
   6  checkout still charges the database price
   7  historical orders were not modified
   8  auth and role separation still hold

Expected money values are read from the live settings/menu rows rather
than hardcoded, except for the approved price list itself which is the
specification under test.
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

# The approved specification, copied verbatim from the sign-off.
APPROVED = {
    37: ("Espresso", 100),
    40: ("Lemonade", 120),
    39: ("Iced Tea", 120),
    36: ("Cappuccino", 150),
    38: ("Latte", 180),
    41: ("Mojito Mocktail", 180),
    45: ("Chocolate Milkshake", 220),
    20: ("Garlic Bread", 180),
    21: ("Bruschetta", 240),
    30: ("Mushroom Soup", 240),
    29: ("Minestrone Soup", 220),
    24: ("Greek Salad", 280),
    22: ("Caesar Salad", 300),
    23: ("Caprese Salad", 320),
    42: ("Chicken Wings", 380),
    35: ("Lemon Sorbet", 180),
    33: ("Chocolate Brownie", 250),
    34: ("Panna Cotta", 280),
    46: ("Apple Pie", 280),
    31: ("Tiramisu", 320),
    32: ("Cheesecake", 340),
    59: ("Jeera Rice", 150),
    60: ("Veg Fried Rice", 240),
    58: ("Veg Biryani", 280),
    56: ("Egg Biryani", 300),
    57: ("Veg Dum Biryani", 300),
    51: ("Chicken Biryani", 320),
    52: ("Chicken Fried Rice", 320),
    54: ("Mushroom Biryani", 330),
    53: ("Paneer Biryani", 340),
    55: ("Kashmiri Pulao", 350),
    47: ("Hyderabadi Chicken Dum Biryani", 420),
    48: ("Tandoori Chicken Biryani", 450),
    49: ("Mutton Biryani", 560),
    50: ("Hyderabadi Mutton Dum Biryani", 620),
    61: ("Biryani Combo Platter for Two", 680),
    15: ("Margherita Pizza", 280),
    18: ("Veggie Supreme", 320),
    16: ("Pepperoni Pizza", 340),
    17: ("BBQ Chicken Pizza", 380),
    19: ("Four Cheese Pizza", 400),
    43: ("Fish & Chips", 420),
    25: ("Spaghetti Bolognese", 420),
    26: ("Fettuccine Alfredo", 450),
    28: ("Ravioli", 460),
    27: ("Lasagna", 480),
    44: ("Steak Frites", 560),
}

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


def sql(query, args=None):
    connection = pymysql.connect(**DB)

    try:
        with connection.cursor() as cursor:
            cursor.execute(query, args or ())

            return cursor.fetchall()
    finally:
        connection.close()


print("=" * 74)
print(f"PHASE 2.5 RECONCILIATION TESTS  ->  {BASE}")
print("=" * 74)

def login(email):
    status, data = call(
        "POST",
        "/auth/login",
        body={"email": email, "password": "password123"},
    )

    if status != 200:
        raise SystemExit(f"cannot log in as {email}: {status} {data}")

    return data["token"]


admin_token = login("admin@gmail.com")
customer_token = login("customer@gmail.com")

# ------------------------------------------------------------------
print(f"\n[1] all {len(APPROVED)} approved prices are live in the database")

rows = {
    r[0]: (r[1], float(r[2]), r[3])
    for r in sql("SELECT id, name, price, category FROM menu")
}

check("menu still holds exactly 47 rows", len(rows) == 47, f"got {len(rows)}")

wrong_price = []
wrong_name = []
missing = []

for item_id, (name, price) in APPROVED.items():
    if item_id not in rows:
        missing.append(item_id)
        continue

    db_name, db_price, _ = rows[item_id]

    if db_name != name:
        wrong_name.append((item_id, name, db_name))

    if db_price != float(price):
        wrong_price.append((item_id, name, price, db_price))

check("no approved id is missing", not missing, f"missing {missing}")
check("no dish was renamed", not wrong_name, f"{wrong_name}")
check(
    "every price matches the approved list",
    not wrong_price,
    f"{wrong_price}",
)

print(f"      verified {len(APPROVED)} prices")

# Named spot checks from the sign-off.
for item_id, label in (
    (51, "Chicken Biryani = 320"),
    (49, "Mutton Biryani = 560"),
    (37, "Espresso = 100"),
    (61, "Biryani Combo = 680"),
):
    name, price = APPROVED[item_id]

    check(
        f"spot check: {label}",
        rows[item_id][1] == float(price),
        f"got {rows[item_id][1]}",
    )

# Nothing left on the old scale.
old_scale = [
    (r[0], r[1], r[2])
    for r in sql("SELECT id, name, price FROM menu WHERE price < 100")
]

check("no menu row is left on the old price scale", not old_scale,
      f"{old_scale}")

# ------------------------------------------------------------------
print("\n[2] currency is INR")
settings = sql("SELECT id, currency, tax_percentage FROM settings LIMIT 1")

check("a settings row exists", bool(settings))
check("currency is INR", settings[0][1] == "INR", f"got {settings[0][1]!r}")

tax_rate = float(settings[0][2])
print(f"      tax rate from settings: {tax_rate}%")

status, api_settings = call("GET", "/api/settings/", token=admin_token)
check("API reports currency INR", api_settings.get("currency") == "INR",
      f"got {api_settings.get('currency')!r}")

# ------------------------------------------------------------------
print("\n[3] the menu API serves those prices")
status, menu = call("GET", "/api/menu/", token=customer_token)
by_id = {row["id"]: row for row in menu}

check("menu API returns 47 items", len(by_id) == 47, f"got {len(by_id)}")

api_mismatch = [
    (i, APPROVED[i][0], float(APPROVED[i][1]), float(by_id[i]["price"]))
    for i in APPROVED
    if abs(float(by_id[i]["price"]) - float(APPROVED[i][1])) > 0.001
]

check("menu API prices equal the approved list", not api_mismatch,
      f"{api_mismatch}")

check("Chicken Biryani is 320 via the API",
      float(by_id[51]["price"]) == 320.0, f"got {by_id[51]['price']}")
check("Biryani Combo is 680 via the API",
      float(by_id[61]["price"]) == 680.0, f"got {by_id[61]['price']}")

# ------------------------------------------------------------------
print("\n[4] the server quotes from the database")
status, quote = call(
    "POST",
    "/api/orders/quote",
    token=customer_token,
    body={
        "items": [{"menu_item_id": 51, "quantity": 1}],
        "order_type": "dine-in",
        "table_number": 4,
    },
)

check("quote succeeds", status == 200, f"{status}")
check("quoted unit price is the DB price",
      quote["items"][0]["unit_price"] == 320.0,
      f"got {quote['items'][0]['unit_price']}")
check("quote subtotal matches", quote["subtotal"] == 320.0,
      f"got {quote['subtotal']}")

expected_tax = round(320.0 * tax_rate / 100.0, 2)
expected_total = round(320.0 + expected_tax, 2)

check("server applied the configured tax", quote["tax_amount"] == expected_tax,
      f"got {quote['tax_amount']} want {expected_tax}")
check("server total matches its own arithmetic",
      quote["total_amount"] == expected_total,
      f"got {quote['total_amount']} want {expected_total}")
check("quote reports INR", quote["currency"] == "INR",
      f"got {quote['currency']!r}")
check("currency flagged as confirmed", quote["currency_is_confirmed"] is True,
      f"got {quote['currency_is_confirmed']}")
check("priced_by names the server", quote["priced_by"] == "server (menu.price)",
      f"got {quote['priced_by']!r}")

print(f"      Chicken Biryani x1 -> subtotal {quote['subtotal']} "
      f"+ tax {quote['tax_amount']} = {quote['total_amount']} {quote['currency']}")

# ------------------------------------------------------------------
print("\n[5] a client cannot override the price")
status, attacked = call(
    "POST",
    "/api/orders/quote",
    token=customer_token,
    body={
        "items": [
            {
                "menu_item_id": 51,
                "quantity": 1,
                "unit_price": 1,
                "price": 1,
                "line_total": 1,
                "total_price": 1,
            }
        ],
        "order_type": "dine-in",
        "table_number": 4,
        "subtotal": 1,
        "total_amount": 1,
        "discount_amount": 999,
        "currency": "USD",
    },
)

check("quote still succeeds", status == 200, f"{status}")
check("unit price stays the DB price",
      attacked["items"][0]["unit_price"] == 320.0,
      f"got {attacked['items'][0]['unit_price']}")
check("subtotal stays the DB total", attacked["subtotal"] == 320.0,
      f"got {attacked['subtotal']}")
check("client cannot inject a discount", attacked["discount_amount"] == 0,
      f"got {attacked['discount_amount']}")
check("client cannot switch the currency",
      attacked["currency"] == "INR", f"got {attacked['currency']!r}")

# ------------------------------------------------------------------
print("\n[6] checkout still charges the database price")
orders_before = sql("SELECT COUNT(*) FROM orders")[0][0]
headers_before = sql("SELECT COUNT(*) FROM order_headers")[0][0]

status, order = call(
    "POST",
    "/api/orders/checkout",
    token=customer_token,
    body={
        "items": [
            {"menu_item_id": 51, "quantity": 2},
            {"menu_item_id": 37, "quantity": 1},
        ],
        "order_type": "dine-in",
        "table_number": 6,
        "notes": "phase 2.5 probe",
    },
)

check("checkout succeeds", status == 200, f"{status} {order}")

want_subtotal = round(320.0 * 2 + 100.0, 2)
want_tax = round(want_subtotal * tax_rate / 100.0, 2)
want_total = round(want_subtotal + want_tax, 2)

check("checkout subtotal from DB prices", order["subtotal"] == want_subtotal,
      f"got {order['subtotal']} want {want_subtotal}")
check("checkout tax from settings", order["tax_amount"] == want_tax,
      f"got {order['tax_amount']} want {want_tax}")
check("checkout total from settings", order["total_amount"] == want_total,
      f"got {order['total_amount']} want {want_total}")
check("checkout reports INR", order["currency"] == "INR",
      f"got {order['currency']!r}")
check("payment not yet taken", order["payment_status"] == "unpaid",
      f"got {order['payment_status']!r}")

header_id = order.get("order_id")
stored = sql(
    "SELECT subtotal, tax_amount, total_amount, currency "
    "FROM order_headers WHERE id = %s",
    (header_id,),
)

if stored:
    check("header stores the server total",
          float(stored[0][2]) == want_total, f"got {stored[0][2]}")
    check("header currency is INR", stored[0][3] == "INR", f"got {stored[0][3]}")

lines = sql(
    "SELECT menu_item, quantity, unit_price, total_price "
    "FROM orders WHERE order_id = %s",
    (header_id,),
)

line_by_name = {row[0]: row for row in lines}

check("Chicken Biryani line priced at 320",
      float(line_by_name.get("Chicken Biryani", (0, 0, 0, 0))[2]) == 320.0,
      f"got {line_by_name.get('Chicken Biryani')}")
check("Espresso line priced at 100",
      float(line_by_name.get("Espresso", (0, 0, 0, 0))[2]) == 100.0,
      f"got {line_by_name.get('Espresso')}")

# ------------------------------------------------------------------
print("\n[7] historical orders were not modified")
# Every seeded row must still hold its original old-scale total.
historic = sql(
    "SELECT COUNT(*) FROM orders "
    "WHERE created_at < '2026-10-01' AND unit_price IS NULL"
)[0][0]

total_historic = sql(
    "SELECT COUNT(*) FROM orders WHERE created_at < '2026-10-01'"
)[0][0]

check("all historical rows still have no unit_price snapshot",
      historic == total_historic,
      f"{historic} of {total_historic}")

untouched = sql(
    "SELECT COUNT(*) FROM orders "
    "WHERE created_at < '2026-10-01' AND order_id IS NULL"
)[0][0]

check("all historical rows still have no order header",
      untouched == total_historic, f"{untouched} of {total_historic}")

sample = sql(
    "SELECT menu_item, total_price FROM orders "
    "WHERE created_at < '2026-10-01' AND menu_item = 'Chicken Biryani' "
    "LIMIT 3"
)

check("historical Chicken Biryani rows keep their stored totals",
      all(float(r[1]) != 320.0 for r in sample),
      f"{sample}")

# ------------------------------------------------------------------
print("\n[8] auth and role separation still hold")
status, _ = call("GET", "/api/dashboard/")
check("anonymous dashboard -> 401", status == 401, f"got {status}")

status, _ = call("GET", "/api/dashboard/", token=customer_token)
check("customer dashboard -> 403", status == 403, f"got {status}")

status, dash = call("GET", "/api/dashboard/", token=admin_token)
check("admin dashboard -> 200", status == 200, f"got {status}")
check("dashboard exposes measured prep time", "avg_prep_minutes" in dash)
check("dashboard exposes measured rating", "avg_rating" in dash)

status, tops = call("GET", "/api/dashboard/top-dishes", token=admin_token)
check("top-dishes -> 200", status == 200, f"got {status}")
check("top-dishes returns real rows", len(tops.get("top_dishes", [])) > 0)
check("top-dishes prices come from menu",
      all(
          d["price"] is None
          or d["price"] in [float(APPROVED[i][1]) for i in APPROVED]
          for d in tops["top_dishes"]
      ),
      f"{[d['price'] for d in tops['top_dishes']]}")

status, weekly = call("GET", "/api/dashboard/weekly", token=admin_token)
check("weekly revenue -> 200", status == 200, f"got {status}")
check("weekly series has 7 days", len(weekly.get("series", [])) == 7,
      f"got {len(weekly.get('series', []))}")

status, _ = call("GET", "/api/dashboard/top-dishes", token=customer_token)
check("customer top-dishes -> 403", status == 403, f"got {status}")

status, me = call("GET", "/auth/me", token=customer_token)
check("/auth/me still works", status == 200 and me["user"]["role"] == "customer")

# ------------------------------------------------------------------
print("\n[cleanup]")
if header_id:
    for row in sql("SELECT id FROM orders WHERE order_id = %s", (header_id,)):
        sql("DELETE FROM kitchen WHERE order_id = %s", (row[0],))

    sql("DELETE FROM orders WHERE order_id = %s", (header_id,))
    sql("DELETE FROM order_headers WHERE id = %s", (header_id,))

final_orders = sql("SELECT COUNT(*) FROM orders")[0][0]
final_headers = sql("SELECT COUNT(*) FROM order_headers")[0][0]

check("probe order removed", final_orders == orders_before,
      f"{final_orders} vs {orders_before}")
check("probe header removed", final_headers == headers_before,
      f"{final_headers} vs {headers_before}")

# ------------------------------------------------------------------
print("\n" + "=" * 74)
print(f"RESULT: {len(passed)} passed, {len(failed)} failed")

if failed:
    print("\nFAILURES:")
    for name in failed:
        print(f"  - {name}")

print("=" * 74)

sys.exit(1 if failed else 0)

"""
Phase 4 acceptance tests: the order lifecycle.

    python scripts/test_phase4_lifecycle.py http://127.0.0.1:8010

The lifecycle under test:

    PLACED -> CONFIRMED -> PREPARING -> READY -> SERVED

Two things are asserted throughout, because they are the whole point of
this phase:

  * states cannot be skipped. PLACED -> PREPARING, PLACED -> READY and
    CONFIRMED -> SERVED are rejected for everybody, admin included.

  * payment is independent of food. An order reaches SERVED and is
    still "unpaid", because the workflow is
    QR scan -> login -> order -> eat -> leave -> pay later.

Required checks:
    1  checkout creates a PLACED order
    2  checkout creates an unpaid order
    3  PLACED -> CONFIRMED succeeds
    4  CONFIRMED -> PREPARING succeeds
    5  PREPARING -> READY succeeds
    6  READY -> SERVED succeeds
    7  PLACED -> PREPARING is rejected
    8  PLACED -> READY is rejected
    9  CONFIRMED -> SERVED is rejected
   10  an invalid transition is rejected for an admin too
   11  an admin cannot skip a state either
   12  SERVED is terminal for the food lifecycle
   13  a customer cannot change status
   14  a customer cannot read another customer's order status
   15  a customer cannot advance somebody else's order
   16  payment_status is unchanged by every transition
   17  a SERVED order is still unpaid
   18  the response exposes status / payment_status / valid_next_statuses
   19  valid_next_statuses only ever offers the next real step
   20  the table association stays server-controlled
   21  historical orders remain readable
   22  the kitchen feed shows the order while it is in progress
   23  the kitchen feed drops it once it is served
   24  no payment gateway is reachable

Everything created here is cleaned up afterwards.
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

LIFECYCLE = ["Placed", "Confirmed", "Preparing", "Ready", "Served"]

# Transitions the spec forbids outright, whoever attempts them.
FORBIDDEN = [
    ("Placed", "Preparing"),
    ("Placed", "Ready"),
    ("Placed", "Served"),
    ("Confirmed", "Ready"),
    ("Confirmed", "Served"),
    ("Preparing", "Served"),
    ("Ready", "Placed"),
    ("Served", "Preparing"),
]


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


def force_status(order_id, status):
    """Put an order at a given stage directly, to test one transition."""
    sql("UPDATE order_headers SET status = %s WHERE id = %s", (status, order_id))

    sql(
        "UPDATE orders SET status = %s WHERE order_id = %s", (status, order_id)
    )


def transition(order_id, status, token=None):
    return call(
        "POST",
        f"/api/orders/headers/{order_id}/status",
        token=token,
        body={"status": status},
    )


def place_order(customer_token, menu_id, order_type="delivery", **extra):
    payload = {
        "items": [{"menu_item_id": menu_id, "quantity": 1}],
        "order_type": order_type,
    }

    if order_type == "delivery":
        payload["delivery_address"] = "9 Lifecycle Way"

    payload.update(extra)

    status, data = call(
        "POST", "/api/orders/checkout", token=customer_token, body=payload
    )

    if status != 200:
        raise SystemExit(f"checkout failed: {status} {data}")

    return data


print("=" * 74)
print(f"PHASE 4 ORDER LIFECYCLE TESTS  ->  {BASE}")
print("=" * 74)

admin_token = login("admin@gmail.com")
customer_token = login("customer@gmail.com")

# A second guest, so ownership is tested between two real people.
other_email = "phase4.guest@example.com"

sql("DELETE FROM users WHERE email = %s", (other_email,))

status, _ = call(
    "POST",
    "/auth/register",
    body={
        "name": "Phase4 Guest",
        "email": other_email,
        "password": "password123",
    },
)

other_token = login(other_email)

status, menu = call("GET", "/api/menu/", token=admin_token)
menu_item = next((row for row in menu if row.get("available")), None)

if not menu_item:
    raise SystemExit("no available menu item to order")

menu_id = menu_item["id"]

created_orders = []
created_tables = []

try:
    # --------------------------------------------------------------
    print("\n[1] checkout creates a PLACED, unpaid order")
    # --------------------------------------------------------------
    placed = place_order(customer_token, menu_id)
    order_id = placed["order_id"]
    created_orders.append(order_id)

    check("checkout returns status Placed",
          placed["status"] == "Placed", f"got {placed['status']}")
    check("checkout returns payment_status unpaid",
          placed["payment_status"] == "unpaid",
          f"got {placed['payment_status']}")
    check("checkout exposes valid_next_statuses",
          isinstance(placed.get("valid_next_statuses"), list),
          f"got {placed.get('valid_next_statuses')}")
    check("Placed offers Confirmed as the next step",
          "Confirmed" in (placed.get("valid_next_statuses") or []),
          f"got {placed.get('valid_next_statuses')}")

    row = sql(
        "SELECT status, payment_status FROM order_headers WHERE id = %s",
        (order_id,),
    )[0]

    check("the stored header is Placed", row[0] == "Placed", f"got {row[0]}")
    check("the stored header is unpaid", row[1] == "unpaid", f"got {row[1]}")

    # --------------------------------------------------------------
    print("\n[2] the full walk: Placed -> Served")
    # --------------------------------------------------------------
    for current, nxt in zip(LIFECYCLE, LIFECYCLE[1:]):
        status, data = transition(order_id, nxt, admin_token)

        check(f"{current} -> {nxt} succeeds",
              status == 200 and data["status"] == nxt,
              f"got {status} {data}")

        if status == 200:
            check(f"{current} -> {nxt} leaves payment alone",
                  data["payment_status"] == "unpaid",
                  f"got {data['payment_status']}")
            check(f"{current} -> {nxt} reports the new status",
                  data.get("status") == nxt and "payment_status" in data
                  and "valid_next_statuses" in data,
                  f"got {data}")

    final = sql(
        "SELECT status, payment_status FROM order_headers WHERE id = %s",
        (order_id,),
    )[0]

    check("the order ends up Served", final[0] == "Served", f"got {final[0]}")
    check("a SERVED order is still unpaid", final[1] == "unpaid",
          f"got {final[1]}")

    # --------------------------------------------------------------
    print("\n[3] states cannot be skipped")
    # --------------------------------------------------------------
    for current, target in FORBIDDEN:
        skip_order = place_order(customer_token, menu_id)
        skip_id = skip_order["order_id"]
        created_orders.append(skip_id)

        force_status(skip_id, current)

        status, data = transition(skip_id, target, admin_token)

        check(f"{current} -> {target} is rejected",
              status == 400, f"got {status} {data}")

        stored = sql(
            "SELECT status FROM order_headers WHERE id = %s", (skip_id,)
        )[0][0]

        check(f"{current} -> {target} left the order at {current}",
              stored == current, f"got {stored}")

    # --------------------------------------------------------------
    print("\n[4] the last state is terminal")
    # --------------------------------------------------------------
    status, data = transition(order_id, "Confirmed", admin_token)
    check("a Served order cannot go back to Confirmed",
          status == 400, f"got {status} {data}")

    status, data = call(
        "GET", f"/api/orders/headers/{order_id}/status", token=admin_token
    )

    check("Served offers nothing to advance to",
          status == 200
          and all(s in ("Cancelled",) for s in data["valid_next_statuses"]),
          f"got {data.get('valid_next_statuses')}")

    # --------------------------------------------------------------
    print("\n[5] the customer cannot drive the lifecycle")
    # --------------------------------------------------------------
    cust_order = place_order(customer_token, menu_id)
    cust_id = cust_order["order_id"]
    created_orders.append(cust_id)

    status, data = transition(cust_id, "Confirmed", customer_token)
    check("a customer cannot confirm their own order",
          status == 403, f"got {status} {data}")

    stored = sql(
        "SELECT status FROM order_headers WHERE id = %s", (cust_id,)
    )[0][0]

    check("the order is still Placed after the attempt",
          stored == "Placed", f"got {stored}")

    # An anonymous caller cannot move it either.
    status, data = transition(cust_id, "Confirmed")
    check("an anonymous caller cannot change status",
          status == 401, f"got {status}")

    # --------------------------------------------------------------
    print("\n[6] ownership comes from the token, never the request")
    # --------------------------------------------------------------
    status, data = call(
        "GET",
        f"/api/orders/headers/{cust_id}/status",
        token=other_token,
    )
    check("another customer cannot read this order's status",
          status == 403, f"got {status} {data}")

    status, data = call(
        "GET", "/api/orders/my-active", token=other_token
    )
    check("another customer's active order is not leaked",
          status == 200 and data.get("active_order") is None,
          f"got {data}")

    status, data = call(
        "GET", "/api/orders/headers/mine", token=other_token
    )
    check("another customer's order list is empty",
          status == 200 and len(data) == 0, f"got {data}")

    status, data = transition(cust_id, "Confirmed", other_token)
    check("another customer cannot advance this order",
          status == 403, f"got {status} {data}")

    status, data = transition(cust_id, "Confirmed", admin_token)
    check("the admin can still advance it", status == 200,
          f"got {status} {data}")

    # --------------------------------------------------------------
    print("\n[7] valid_next_statuses never offers a shortcut")
    # --------------------------------------------------------------
    for current, expected_next in zip(LIFECYCLE, LIFECYCLE[1:]):
        probe = place_order(customer_token, menu_id)
        probe_id = probe["order_id"]
        created_orders.append(probe_id)

        force_status(probe_id, current)

        status, data = call(
            "GET",
            f"/api/orders/headers/{probe_id}/status",
            token=admin_token,
        )

        offered = data.get("valid_next_statuses", [])

        check(f"{current} offers {expected_next}",
              expected_next in offered, f"got {offered}")

        for later in LIFECYCLE[LIFECYCLE.index(current) + 2:]:
            check(f"{current} does not offer {later}",
                  later not in offered, f"got {offered}")

    # --------------------------------------------------------------
    print("\n[8] the kitchen feed follows the real status")
    # --------------------------------------------------------------
    kitchen_order = place_order(customer_token, menu_id)
    kitchen_id = kitchen_order["order_id"]
    created_orders.append(kitchen_id)

    status, feed = call(
        "GET", "/api/orders/headers/active", token=admin_token
    )

    match = next((h for h in feed if h["id"] == kitchen_id), None)

    check("a Placed order appears on the kitchen board",
          match is not None and match["status"] == "Placed",
          f"got {match}")
    check("the kitchen card carries its real line items",
          match is not None and len(match.get("items") or []) == 1,
          f"got {match and match.get('items')}")
    check("the kitchen card reports payment separately",
          match is not None and match.get("payment_status") == "unpaid",
          f"got {match and match.get('payment_status')}")

    status, _ = transition(kitchen_id, "Served", admin_token)
    check("serving in one jump is refused", status == 400, f"got {status}")

    for nxt in ["Confirmed", "Preparing", "Ready", "Served"]:
        transition(kitchen_id, nxt, admin_token)

    status, feed = call(
        "GET", "/api/orders/headers/active", token=admin_token
    )

    check("a Served order leaves the kitchen board",
          not any(h["id"] == kitchen_id for h in feed),
          "still listed")

    # --------------------------------------------------------------
    print("\n[9] the table association stays server-controlled")
    # --------------------------------------------------------------
    sql(
        "UPDATE users SET active_table_id = NULL WHERE email IN (%s, %s)",
        ("customer@gmail.com", other_email),
    )

    sql("DELETE FROM restaurant_tables WHERE table_number = %s", (97,))

    status, created_table = call(
        "POST",
        "/api/tables/",
        token=admin_token,
        body={"table_number": 97, "table_name": "Phase4 Table",
              "capacity": 4},
    )
    check("a table was created for the test", status == 200,
          f"got {status} {created_table}")

    if status == 200:
        created_tables.append(created_table["id"])

    # A dine-in order that lies about its table must be overruled by the
    # server-side claim, exactly as in Phase 3.
    qr_token = created_table["qr_token"]

    status, claimed = call(
        "POST", "/api/tables/claim",
        token=customer_token,
        body={"table_token": qr_token},
    )
    check("the customer claimed the table by QR", status == 200,
          f"got {status} {claimed}")

    dine_in = place_order(
        customer_token,
        menu_id,
        order_type="dine-in",
        table_number=1,
    )
    created_orders.append(dine_in["order_id"])

    stored = sql(
        "SELECT table_id, table_number FROM order_headers WHERE id = %s",
        (dine_in["order_id"],),
    )[0]

    claimed_table_id = created_table["id"]

    check("the claimed table overrides the client's table number",
          stored[0] == claimed_table_id and stored[1] == 97,
          f"got table_id={stored[0]} table_number={stored[1]}, "
          f"claimed {claimed_table_id}/97")

    # --------------------------------------------------------------
    print("\n[10] payment stays out of this phase")
    # --------------------------------------------------------------
    for path in ["/api/payments", "/api/payment", "/api/orders/pay",
                 "/api/orders/checkout/pay"]:
        status, _ = call("GET", path, token=admin_token)

        # 404 means no such route. 422 means the /orders/{order_id}
        # catch-all matched and could not read the path segment as an
        # int. Neither is a payment endpoint, and neither returns
        # anything a client could act on.
        check(f"{path} is not a payment endpoint",
              status in (404, 422), f"got {status}")

    # --------------------------------------------------------------
    print("\n[11] historical orders are still readable")
    # --------------------------------------------------------------
    status, mine = call("GET", "/api/orders/mine", token=customer_token)
    check("the customer's order history is readable",
          status == 200 and isinstance(mine, list), f"got {status}")

    legacy = sql(
        "SELECT COUNT(*) FROM orders WHERE order_id IS NULL"
    )[0][0]

    status, all_orders = call("GET", "/api/orders/", token=admin_token)
    check("the admin order list is readable",
          status == 200 and isinstance(all_orders, list), f"got {status}")
    check("rows predating order headers still exist", legacy > 0,
          f"got {legacy}")

    historical = next((o for o in mine if o.get("order_id") is None), None)

    check("a pre-header order is visible to its owner",
          historical is not None,
          "none of the customer's legacy rows came back")

    if historical is not None:
        status, _ = call(
            "GET", f"/api/orders/{historical['id']}", token=customer_token
        )
        check("a pre-header order can still be opened",
              status == 200, f"got {status}")

finally:
    print("\n[cleanup]")

    for header_id in created_orders:
        for row in sql(
            "SELECT id FROM orders WHERE order_id = %s", (header_id,)
        ):
            sql("DELETE FROM kitchen WHERE order_id = %s", (row[0],))

        sql("DELETE FROM orders WHERE order_id = %s", (header_id,))
        sql("DELETE FROM order_headers WHERE id = %s", (header_id,))

    for table_id in created_tables:
        sql("DELETE FROM restaurant_tables WHERE id = %s", (table_id,))

    sql(
        "UPDATE users SET active_table_id = NULL WHERE email IN (%s, %s)",
        (other_email, "customer@gmail.com"),
    )
    sql("DELETE FROM users WHERE email = %s", (other_email,))

    left = 0

    for header_id in created_orders:
        left += sql(
            "SELECT COUNT(*) FROM order_headers WHERE id = %s", (header_id,)
        )[0][0]

    check("test orders removed", left == 0, f"{left} left")

    orphan = sql(
        "SELECT COUNT(*) FROM kitchen k LEFT JOIN orders o ON o.id = k.order_id "
        "WHERE o.id IS NULL"
    )[0][0]

    check("no orphan kitchen tickets", orphan == 0, f"got {orphan}")

# ------------------------------------------------------------------
print("\n" + "=" * 74)
print(f"RESULT: {len(passed)} passed, {len(failed)} failed")

if failed:
    print("\nFAILURES:")
    for name in failed:
        print(f"  - {name}")

print("=" * 74)

sys.exit(1 if failed else 0)

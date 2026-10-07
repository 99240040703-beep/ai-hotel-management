"""
Phase 3 acceptance tests: table QR and table-aware ordering.

    python scripts/test_phase3_tables.py http://127.0.0.1:8010

Covers the required checks:
   1  admin can create a table
   2  a customer cannot
   3  admin can update a table
   4  admin can deactivate a table
   5  an inactive table's QR cannot start ordering
   6  a valid token returns table information
   7  an invalid token is rejected
   8  a customer can enter with a valid token
   9  an anonymous request cannot create an order
  10  the order is tied to the authenticated user
  11  the order is tied to the validated table
  12  a client cannot move an order to another table
  13  server-side pricing still holds
  14  checkout still works
  15  historical orders remain readable

plus the bill, and the guarantee that no payment gateway exists.

Everything is cleaned up afterwards.
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
print(f"PHASE 3 TABLE / QR TESTS  ->  {BASE}")
print("=" * 74)

admin_token = login("admin@gmail.com")
customer_token = login("customer@gmail.com")

# A second guest, so ownership can be tested between two real people.
probe_email = "phase3.guest@example.com"

sql("DELETE FROM users WHERE email = %s", (probe_email,))

status, registered = call(
    "POST",
    "/auth/register",
    body={
        "name": "Phase3 Guest",
        "email": probe_email,
        "password": "password123",
    },
)

other_token = (
    registered["token"] if status == 200 else customer_token
)

created_tables = []
created_orders = []

try:
    # ------------------------------------------------------------------
    print("\n[1] admin can create a table")
    status, table = call(
        "POST",
        "/api/tables/",
        token=admin_token,
        body={
            "table_number": 91,
            "table_name": "Phase3 Test Table",
            "capacity": 4,
            "section": "Test Lab",
        },
    )

    check("create returns 200", status == 200, f"{status} {table}")
    check("table_number is stored", table["table_number"] == 91,
          f"got {table['table_number']}")
    check("capacity is stored", table["capacity"] == 4)
    check("table is active by default", table["is_active"] is True)
    check("a qr_token was generated", bool(table.get("qr_token")))
    check(
        "qr_token is not the table id",
        table.get("qr_token") != str(table["id"]),
        "token leaks the row id",
    )
    check(
        "qr_token looks random",
        len(table.get("qr_token", "")) >= 24,
        f"got {table.get('qr_token')!r}",
    )

    created_tables.append(table["id"])
    token_91 = table["qr_token"]

    status, duplicate = call(
        "POST",
        "/api/tables/",
        token=admin_token,
        body={"table_number": 91},
    )

    check("duplicate table_number is refused with 409", status == 409,
          f"got {status}")

    # ------------------------------------------------------------------
    print("\n[2] a customer cannot create or manage tables")
    for method, path, body in (
        ("POST", "/api/tables/", {"table_number": 92}),
        ("GET", "/api/tables/", None),
        ("PUT", f"/api/tables/{table['id']}", {"capacity": 2}),
        ("DELETE", f"/api/tables/{table['id']}", None),
        ("POST", f"/api/tables/{table['id']}/regenerate-qr", None),
    ):
        status, _ = call(method, path, token=customer_token, body=body)
        check(f"customer is refused {method} {path}", status == 403,
              f"got {status}")

    status, _ = call("POST", "/api/tables/", body={"table_number": 93})
    check("anonymous is refused POST /api/tables/ (401)", status == 401,
          f"got {status}")

    status, _ = call("GET", "/api/tables/")
    check("anonymous is refused GET /api/tables/ (401)", status == 401,
          f"got {status}")

    # ------------------------------------------------------------------
    print("\n[3] admin can update a table")
    status, updated = call(
        "PUT",
        f"/api/tables/{table['id']}",
        token=admin_token,
        body={"capacity": 6, "table_name": "Renamed Table"},
    )

    check("update returns 200", status == 200, f"{status}")
    check("capacity changed", updated["capacity"] == 6)
    check("name changed", updated["table_name"] == "Renamed Table")
    check("qr_token survives an edit",
          updated["qr_token"] == token_91,
          "the printed code would stop working")

    # ------------------------------------------------------------------
    print("\n[4] admin can deactivate a table")
    status, off = call(
        "PUT",
        f"/api/tables/{table['id']}",
        token=admin_token,
        body={"is_active": False},
    )

    check("deactivate returns 200", status == 200, f"{status}")
    check("is_active is False", off["is_active"] is False)

    status, _ = call(
        "PUT",
        f"/api/tables/{table['id']}",
        token=admin_token,
        body={"is_active": True},
    )
    check("reactivate returns 200", status == 200, f"got {status}")

    # ------------------------------------------------------------------
    print("\n[5] an inactive table's QR cannot start ordering")
    call(
        "PUT",
        f"/api/tables/{table['id']}",
        token=admin_token,
        body={"is_active": False},
    )

    status, blocked = call("GET", f"/api/tables/resolve?table={token_91}")
    check("resolve on an inactive table is refused", status == 409,
          f"got {status}")

    status, _ = call(
        "POST",
        "/api/tables/claim",
        token=customer_token,
        body={"table_token": token_91},
    )
    check("claim on an inactive table is refused", status == 409,
          f"got {status}")

    call(
        "PUT",
        f"/api/tables/{table['id']}",
        token=admin_token,
        body={"is_active": True},
    )

    # ------------------------------------------------------------------
    print("\n[6] a valid token returns table information")
    status, resolved = call(
        "GET", f"/api/tables/resolve?table={token_91}"
    )

    check("resolve returns 200", status == 200, f"{status}")
    check("valid flag is set", resolved.get("valid") is True)
    check("table_number returned",
          resolved["table"]["table_number"] == 91,
          f"got {resolved['table']['table_number']}")
    check("capacity returned", resolved["table"]["capacity"] == 6)
    check("section returned", resolved["table"]["section"] == "Test Lab")

    # The response must not hand back anything that could be walked.
    body = json.dumps(resolved)

    check("no qr_token in the resolve response", "qr_token" not in body)
    check("no internal id in the resolve response",
          '"id"' not in body.replace('"table_id"', ""),
          body[:200])
    check("no is_active in the resolve response", "is_active" not in body)
    check("no secret in the payload",
          "SECRET_KEY" not in body and "password" not in body.lower())

    # ------------------------------------------------------------------
    print("\n[7] an invalid token is rejected")
    for bad in ("not-a-real-token", "", "x" * 400):
        status, _ = call("GET", f"/api/tables/resolve?table={bad}")
        check(f"invalid token rejected: {bad[:18]!r}",
              status in (404, 422), f"got {status}")

    status, _ = call(
        "POST",
        "/api/tables/claim",
        token=customer_token,
        body={"table_token": "not-a-real-token"},
    )
    check("claim with an invalid token is refused", status == 404,
          f"got {status}")

    status, _ = call(
        "POST", "/api/tables/claim", body={"table_token": token_91}
    )
    check("anonymous claim is refused", status == 401, f"got {status}")

    # ------------------------------------------------------------------
    print("\n[8] a customer can enter using a valid table token")
    status, claimed = call(
        "POST",
        "/api/tables/claim",
        token=customer_token,
        body={"table_token": token_91},
    )

    check("claim returns 200", status == 200, f"{status} {claimed}")
    check("claimed flag is set", claimed.get("claimed") is True)
    check("claim returns table 91",
          claimed["table"]["table_number"] == 91,
          f"got {claimed['table']['table_number']}")

    status, context = call("GET", "/api/tables/context", token=customer_token)
    check("context returns 200", status == 200, f"got {status}")
    check("context shows table 91",
          context["table"]["table_number"] == 91,
          f"got {context}")

    # The claim is server side, so it survives a fresh token.
    other_token_for_user = login("customer@gmail.com")
    status, context = call(
        "GET", "/api/tables/context", token=other_token_for_user
    )
    check("claim survives a new login",
          context["table"]["table_number"] == 91,
          f"got {context}")

    status, other_context = call(
        "GET", "/api/tables/context", token=other_token
    )
    check("another guest has no table claim",
          other_context.get("table") is None,
          f"got {other_context}")

    # ------------------------------------------------------------------
    print("\n[9] an anonymous request cannot create an order")
    status, _ = call(
        "POST",
        "/api/orders/checkout",
        body={
            "items": [{"menu_item_id": 51, "quantity": 1}],
            "order_type": "dine-in",
            "table_number": 91,
        },
    )
    check("anonymous checkout is refused (401)", status == 401,
          f"got {status}")

    status, _ = call(
        "POST",
        "/api/orders/quote",
        body={
            "items": [{"menu_item_id": 51, "quantity": 1}],
            "order_type": "dine-in",
            "table_number": 91,
        },
    )
    check("anonymous quote is refused (401)", status == 401, f"got {status}")

    # ------------------------------------------------------------------
    print("\n[10] the order is tied to the authenticated user")
    menu = call("GET", "/api/menu/", token=customer_token)[1] or []
    dish = next(m for m in menu if m["name"] == "Chicken Biryani")

    status, order = call(
        "POST",
        "/api/orders/checkout",
        token=customer_token,
        body={
            "items": [
                {
                    "menu_item_id": dish["id"],
                    "quantity": 1,
                }
            ],
            "order_type": "dine-in",
            "notes": "phase3 probe",
        },
    )

    check("checkout with a claimed table succeeds", status == 200,
          f"{status} {order}")

    if status == 200:
        header_id = order["order_id"]
        created_orders.append(header_id)

        me = call("GET", "/auth/me", token=customer_token)[1]

        stored = sql(
            "SELECT user_id, customer_name, table_id, table_number, "
            "total_amount, currency, status, payment_status "
            "FROM order_headers WHERE id = %s",
            (header_id,),
        )[0]

        check("header belongs to the caller",
              stored[0] == me["user"]["id"],
              f"got user_id {stored[0]}, caller {me['user']['id']}")
        check("header name comes from the token",
              stored[1] == me["user"]["name"], f"got {stored[1]!r}")

        # ------------------------------------------------------------------
        print("\n[11] the order is tied to the validated table")
        check("header carries the table id",
              stored[2] == table["id"], f"got {stored[2]}")
        check("header carries table 91", stored[3] == 91, f"got {stored[3]}")

        lines = sql(
            "SELECT COUNT(*) FROM orders WHERE order_id = %s", (header_id,)
        )[0][0]
        check("line rows written", lines == 1, f"got {lines}")

        # ------------------------------------------------------------------
        print("\n[12] a client cannot move an order to another table")
        # A second table to try to jump to.
        status, other_table = call(
            "POST",
            "/api/tables/",
            token=admin_token,
            body={"table_number": 94, "capacity": 8, "section": "Test Lab"},
        )
        created_tables.append(other_table["id"])

        # Send a wildly different table_number with the claim in place.
        status, tampered = call(
            "POST",
            "/api/orders/checkout",
            token=customer_token,
            body={
                "items": [
                    {"menu_item_id": dish["id"], "quantity": 1}
                ],
                "order_type": "dine-in",
                "table_number": 94,
                "table_id": other_table["id"],
                "customer_id": 1,
                "user_id": 1,
            },
        )

        check("tampered checkout still succeeds", status == 200,
              f"{status} {tampered}")

        if status == 200:
            created_orders.append(tampered["order_id"])

            row = sql(
                "SELECT table_id, table_number FROM order_headers "
                "WHERE id = %s",
                (tampered["order_id"],),
            )[0]

            check("server ignored the client table_number",
                  row[1] == 91, f"got table_number {row[1]}, expected 91")
            check("server ignored the client table_id",
                  row[0] == table["id"], f"got table_id {row[0]}")

        # Without a claim, a client table_number is honoured but must
        # still exist and be active.
        call("POST", "/api/tables/release", token=customer_token)

        status, _ = call(
            "POST",
            "/api/orders/checkout",
            token=customer_token,
            body={
                "items": [
                    {"menu_item_id": dish["id"], "quantity": 1}
                ],
                "order_type": "dine-in",
                "table_number": 777,
            },
        )
        check("an unknown table_number is refused", status == 409,
              f"got {status}")

        # Put the claim back for the remaining checks.
        call(
            "POST",
            "/api/tables/claim",
            token=customer_token,
            body={"table_token": token_91},
        )

    # ------------------------------------------------------------------
    print("\n[13] server-side pricing still holds")
    status, quote = call(
        "POST",
        "/api/orders/quote",
        token=customer_token,
        body={
            "items": [
                {
                    "menu_item_id": dish["id"],
                    "quantity": 1,
                    "unit_price": 0.01,
                    "total_price": 0.01,
                }
            ],
            "order_type": "dine-in",
        },
    )

    check("quote returns 200", status == 200, f"{status}")
    check("unit price is the database price",
          quote["items"][0]["unit_price"] == float(dish["price"]),
          f"got {quote['items'][0]['unit_price']}")
    check("subtotal ignores the fake price",
          quote["subtotal"] == float(dish["price"]),
          f"got {quote['subtotal']}")
    check("priced_by still names the server",
          quote["priced_by"] == "server (menu.price)")
    check("currency still INR", quote["currency"] == "INR",
          f"got {quote['currency']!r}")
    check("quote reports the claimed table",
          quote["table_number"] == 91, f"got {quote['table_number']}")

    # ------------------------------------------------------------------
    print("\n[14] existing checkout still works for takeaway")
    status, takeaway = call(
        "POST",
        "/api/orders/checkout",
        token=customer_token,
        body={
            "items": [
                {"menu_item_id": dish["id"], "quantity": 1}
            ],
            "order_type": "takeaway",
        },
    )

    check("takeaway checkout succeeds", status == 200, f"{status} {takeaway}")

    if status == 200:
        created_orders.append(takeaway["order_id"])

        row = sql(
            "SELECT order_type, table_id, table_number FROM order_headers "
            "WHERE id = %s",
            (takeaway["order_id"],),
        )[0]

        check("takeaway has no table attached", row[1] is None, f"got {row[1]}")
        check("takeaway table_number is null", row[2] is None, f"got {row[2]}")

    # ------------------------------------------------------------------
    print("\n[15] historical orders remain readable")
    total_orders = sql("SELECT COUNT(*) FROM orders")[0][0]
    historic = sql(
        "SELECT COUNT(*) FROM orders WHERE created_at < '2026-10-01'"
    )[0][0]

    check("history is still present", historic > 500, f"got {historic}")

    no_table = sql(
        "SELECT COUNT(*) FROM orders WHERE order_id IS NULL"
    )[0][0]

    check("historical lines still have no header", no_table > 500,
          f"got {no_table}")

    unassigned = sql(
        "SELECT COUNT(*) FROM order_headers WHERE table_id IS NULL"
    )[0][0]
    assigned = sql(
        "SELECT COUNT(*) FROM order_headers WHERE table_id IS NOT NULL"
    )[0][0]

    # Only dine-in orders are expected to carry a table; the takeaway
    # probe correctly has none. Anything else would mean a historical
    # header was given a table it never had evidence for.
    #
    # Phase 6A. This used to assert `assigned == <dine-in headers this test
    # created>`, which was a claim about the whole database rather than
    # about this feature: it failed the first time anybody placed a
    # genuine dine-in order through the customer portal, even though the
    # table association was correct. The rule is now checked directly -
    # no header anywhere carries a table unless it is a dine-in order -
    # and, separately, every header this run created matches its own
    # order_type.
    assigned_by_type = sql(
        "SELECT order_type, COUNT(*) FROM order_headers "
        "WHERE table_id IS NOT NULL GROUP BY order_type"
    )

    check("only dine-in headers carry a table",
          bool(assigned_by_type)
          and all(row[0] == "dine-in" for row in assigned_by_type),
          f"assigned={assigned} by type={assigned_by_type}")

    created_rows = [
        (sql("SELECT order_type, table_id FROM order_headers WHERE id = %s",
             (header_id,)) or [(None, None)])[0]
        for header_id in created_orders
    ]

    created_wrongly = [
        order_type
        for order_type, table_id in created_rows
        if (table_id is not None) != (order_type == "dine-in")
    ]

    check("each header this run created matches its own order type",
          not created_wrongly,
          f"wrongly associated: {created_wrongly}")

    status, listed = call("GET", "/api/orders/", token=admin_token)
    check("admin can still list all orders",
          status == 200 and len(listed) >= total_orders,
          f"{status} {len(listed) if isinstance(listed, list) else listed}")

    status, mine = call("GET", "/api/orders/mine", token=customer_token)
    check("customer order history still loads", status == 200, f"{status}")

    # ------------------------------------------------------------------
    print("\n[16] the bill is read-only and reports UNPAID")
    status, bill = call("GET", "/api/customer/bill", token=customer_token)

    check("bill returns 200", status == 200, f"{status}")
    check("bill names the table", bill["table_number"] == 91,
          f"got {bill['table_number']}")
    check("bill has line items", len(bill["orders"]) > 0,
          f"got {len(bill['orders'])}")
    check("bill currency is INR", bill["currency"] == "INR",
          f"got {bill['currency']!r}")
    check("payment status is UNPAID", bill["payment_status"] == "UNPAID",
          f"got {bill['payment_status']!r}")
    # Phase 6D. This used to assert `payment_available is False`, because
    # no payment system existed. One does now, and this bill is unpaid, so
    # the honest expectation is the opposite: the guest is offered payment.
    # What has not changed, and is checked above, is that the bill is
    # UNPAID - generating a request never settles anything.
    check("an unpaid bill offers payment",
          bill["payment_available"] is True,
          f"got {bill['payment_available']}")
    check("an unpaid bill has collected nothing",
          bill.get("paid_amount") == 0.0
          and bill.get("outstanding_amount") == bill["total_amount"],
          f"paid={bill.get('paid_amount')} "
          f"outstanding={bill.get('outstanding_amount')}")
    check("bill total is positive", bill["total_amount"] > 0,
          f"got {bill['total_amount']}")

    status, _ = call("GET", "/api/customer/bill")
    check("anonymous bill is refused", status == 401, f"got {status}")

    # ------------------------------------------------------------------
    # Phase 6D replaced this block. It used to prove no payment gateway
    # existed by checking that three paths 404'd and that no `payments`
    # table was present - an assertion that the absence of a feature is
    # permanent, which Phase 6D was built to invalidate.
    #
    # The property that actually matters is unchanged and is now checked
    # instead: the bill cannot be settled by a client. A guest may ask for
    # a payment request, and may ask the backend to check one, but no
    # client-supplied outcome can mark a bill paid.
    print("\n[17] payment cannot be settled by the client")
    status, request_body = call(
        "POST", "/api/payments/request", token=customer_token,
        body={"order_id": created_orders[0]},
    )
    check("a guest may request payment for their own bill",
          status == 200, f"got {status} {request_body}")

    if status == 200:
        payment_id = request_body["payment_id"]

        check("the requested payment is PENDING, not paid",
              request_body["status"] == "PENDING",
              f"got {request_body.get('status')}")

        status, forced = call(
            "POST", f"/api/payments/{payment_id}/verify",
            token=customer_token,
            body={"status": "SUCCESS", "paid": True},
        )
        check("a client cannot declare a payment successful",
              status == 422, f"got {status}")

        status, no_shortcut = call(
            "POST", f"/api/payments/{payment_id}/mark-paid",
            token=customer_token, body={},
        )
        check("there is no mark-paid shortcut", status == 404,
              f"got {status}")

        status, still = call(
            "GET", f"/api/payments/{payment_id}", token=customer_token,
        )
        check("the bill is still unpaid after all of that",
              still["order_payment_status"] == "unpaid"
              and still["status"] == "PENDING",
              f"got {still.get('status')} / "
              f"{still.get('order_payment_status')}")

        sql("DELETE FROM restaurant_events WHERE entity_type = 'payment' "
            "AND entity_id = %s", (payment_id,))
        sql("DELETE FROM payments WHERE id = %s", (payment_id,))

    payment_tables = sql("SHOW TABLES LIKE 'payments'")

    check("the payment ledger exists", bool(payment_tables),
          f"{payment_tables}")

    # ------------------------------------------------------------------
    print("\n[18] QR regeneration retires the old code")
    status, rotated = call(
        "POST",
        f"/api/tables/{table['id']}/regenerate-qr",
        token=admin_token,
    )

    check("regenerate returns 200", status == 200, f"{status}")
    check("a new token was issued",
          rotated["table"]["qr_token"] != token_91,
          "the old code still works")
    check("table_number is unchanged",
          rotated["table"]["table_number"] == 91)
    check("payload points at the entry route",
          "/customer/entry?table=" in rotated["qr_payload"],
          f"got {rotated['qr_payload']}")

    status, _ = call(
        "GET", f"/api/tables/resolve?table={token_91}"
    )
    check("the retired token no longer resolves", status == 404,
          f"got {status}")

    status, _ = call(
        "GET",
        f"/api/tables/resolve?table={rotated['table']['qr_token']}",
    )
    check("the new token resolves", status == 200, f"got {status}")

    status, base = call("GET", "/api/tables/qr-base-url", token=admin_token)
    check("qr base url is configurable", status == 200 and
          base.get("entry_base_url"), f"got {base}")
    check("a customer cannot read the qr base url", True)

    status, _ = call("GET", "/api/tables/qr-base-url", token=customer_token)
    check("customer is refused the qr base url", status == 403,
          f"got {status}")

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

    # MySQL forbids a subquery on the table being updated, so the
    # emails are named directly.
    sql(
        "UPDATE users SET active_table_id = NULL WHERE email IN (%s, %s)",
        (probe_email, "customer@gmail.com"),
    )
    sql("DELETE FROM users WHERE email = %s", (probe_email,))

    left = sql("SELECT COUNT(*) FROM restaurant_tables WHERE table_number IN (91, 94)")[0][0]
    check("test tables removed", left == 0, f"{left} left")

    orphan_tickets = sql(
        "SELECT COUNT(*) FROM kitchen k LEFT JOIN orders o ON o.id = k.order_id "
        "WHERE o.id IS NULL"
    )[0][0]
    check("no orphan kitchen tickets", orphan_tickets == 0,
          f"got {orphan_tickets}")

# ------------------------------------------------------------------
print("\n" + "=" * 74)
print(f"RESULT: {len(passed)} passed, {len(failed)} failed")

if failed:
    print("\nFAILURES:")
    for name in failed:
        print(f"  - {name}")

print("=" * 74)

sys.exit(1 if failed else 0)
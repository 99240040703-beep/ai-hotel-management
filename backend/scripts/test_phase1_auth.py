"""
Phase 1 acceptance tests: auth, identity and authorization.

Run against a live backend:

    python scripts/test_phase1_auth.py http://127.0.0.1:8010

Covers:
  * unauthenticated request -> 401
  * admin can reach admin endpoints
  * customer is refused admin endpoints -> 403
  * customer A cannot read customer B's order
  * a deactivated account cannot sign in
  * /auth/me returns the server's view of the account
  * the AI recommend endpoint ignores a spoofed customer name
"""

import json
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8010"

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
        with urlopen(request, timeout=20) as response:
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

    return data


print("=" * 72)
print(f"PHASE 1 AUTH MATRIX  ->  {BASE}")
print("=" * 72)

# ------------------------------------------------------------------
print("\n[1] credentials")
admin = login("admin@gmail.com")
customer_a = login("customer@gmail.com")

admin_token = admin["token"]
customer_token = customer_a["token"]

print(f"  admin    id={admin['user']['id']} role={admin['user']['role']}")
print(f"  customer id={customer_a['user']['id']} role={customer_a['user']['role']}")

check("login returns a token", bool(admin_token) and bool(customer_token))
check(
    "login response carries active flag",
    admin["user"].get("active") is True,
    f"got {admin['user'].get('active')!r}",
)
check(
    "login never returns the password hash",
    "password" not in json.dumps(admin).lower().replace('"password"', ""),
)

# ------------------------------------------------------------------
print("\n[2] JWT claims")
status, payload = call(
    "GET",
    "/auth/me",
    token=admin_token,
)

check("/auth/me works for admin", status == 200, f"{status}")

import base64


def decode_claims(token):
    body = token.split(".")[1]
    body += "=" * (-len(body) % 4)

    return json.loads(base64.urlsafe_b64decode(body))


claims = decode_claims(admin_token)

check("token has sub claim", claims.get("sub") == str(admin["user"]["id"]))
check("token has jti claim", bool(claims.get("jti")))
check("token has iat claim", claims.get("iat") is not None)
check("token has exp claim", claims.get("exp") is not None)
check(
    "each token is unique",
    decode_claims(customer_token)["jti"] != claims["jti"],
)

# ------------------------------------------------------------------
print("\n[3] /auth/me is the source of truth")
status, me = call("GET", "/auth/me", token=customer_token)

check("/auth/me works for customer", status == 200, f"{status}")
check(
    "/auth/me reports the server-side role",
    me["user"]["role"] == "customer",
    f"got {me['user']['role']!r}",
)
check(
    "/auth/me reports an id",
    me["user"]["id"] == customer_a["user"]["id"],
)

# ------------------------------------------------------------------
print("\n[4] unauthenticated access")
ADMIN_PATHS = [
    "/api/dashboard/",
    "/api/customers/",
    "/api/inventory/",
    "/api/kitchen/",
    "/api/staff/",
    "/api/analytics/",
    "/api/suppliers/",
    "/api/settings/",
    "/api/users/",
    "/api/waste/",
    "/api/orders/",
    "/api/reservations/",
    "/api/ai/insights",
    "/api/ai/demand-forecast",
    "/api/ai/revenue-forecast",
    "/api/ai/waste-analysis",
    "/api/ai/dynamic-pricing",
]

for path in ADMIN_PATHS:
    status, _ = call("GET", path)
    check(f"401 without a token: GET {path}", status == 401, f"got {status}")

status, _ = call("GET", "/api/orders/mine")
check("401 without a token: GET /api/orders/mine", status == 401, f"got {status}")

status, _ = call("POST", "/api/orders/cart", body={"items": []})
check("401 without a token: POST /api/orders/cart", status == 401, f"got {status}")

status, _ = call(
    "POST", "/api/reviews/", body={"menu_item": "X", "rating": 5, "comment": "no"}
)
check("401 without a token: POST /api/reviews/", status == 401, f"got {status}")

# ------------------------------------------------------------------
print("\n[5] admin CAN reach admin endpoints")
for path in ADMIN_PATHS:
    status, _ = call("GET", path, token=admin_token)
    check(f"200 for admin: GET {path}", status == 200, f"got {status}")

status, _ = call("POST", "/api/waste/", token=admin_token, body={
    "item_name": "Phase1 probe", "quantity": 0, "unit": "kg",
    "reason": "phase1 auth test", "cost": 0,
})
check("200 for admin: POST /api/waste/", status == 200, f"got {status}")

# ------------------------------------------------------------------
print("\n[6] customer is REFUSED admin endpoints (403)")
for path in ADMIN_PATHS:
    status, _ = call("GET", path, token=customer_token)
    check(f"403 for customer: GET {path}", status == 403, f"got {status}")

status, _ = call("POST", "/api/waste/", token=customer_token, body={
    "item_name": "probe", "quantity": 1, "unit": "kg", "reason": "x", "cost": 1,
})
check("403 for customer: POST /api/waste/", status == 403, f"got {status}")

status, _ = call("DELETE", "/api/reviews/1", token=customer_token)
check("403 for customer: DELETE /api/reviews/1", status == 403, f"got {status}")

# ------------------------------------------------------------------
print("\n[7] customer keeps working on customer endpoints")
status, orders = call("GET", "/api/orders/mine", token=customer_token)
check("200 for customer: GET /api/orders/mine", status == 200, f"got {status}")

status, reservations = call(
    "GET", "/api/reservations/mine", token=customer_token
)
check(
    "200 for customer: GET /api/reservations/mine",
    status == 200,
    f"got {status}",
)

status, menu = call("GET", "/api/menu/", token=customer_token)
check("200 for customer: GET /api/menu/", status == 200, f"got {status}")

status, recs = call(
    "GET", "/api/ai/recommend/Paradise%20Customer", token=customer_token
)
check("200 for customer: GET /api/ai/recommend/...", status == 200, f"got {status}")

# ------------------------------------------------------------------
print("\n[8] a new order is stamped with the caller's user_id")
menu_items = call("GET", "/api/menu/")[1] or []
dish = menu_items[0]

status, placed = call(
    "POST",
    "/api/orders/cart",
    token=customer_token,
    body={
        "customer_name": "SOMEONE ELSE ENTIRELY",
        "order_type": "dine-in",
        "table_number": 2,
        "notes": "phase1 ownership probe",
        "items": [
            {
                "customer_name": "SOMEONE ELSE ENTIRELY",
                "menu_item": dish["name"],
                "quantity": 1,
                "total_price": dish["price"],
                "status": "Pending",
            }
        ],
    },
)

check("customer can place an order", status == 200, f"{status} {placed}")

created_id = None

if status == 200 and placed.get("orders"):
    created_id = placed["orders"][0]["id"]
    created = placed["orders"][0]

    check(
        "order name comes from the token, not the payload",
        created["customer_name"] == customer_a["user"]["name"],
        f"got {created['customer_name']!r}",
    )
    check(
        "order carries user_id",
        created.get("user_id") == customer_a["user"]["id"],
        f"got {created.get('user_id')!r}",
    )

# ------------------------------------------------------------------
print("\n[9] customer A cannot read customer B's order")
# A row belonging to a different person: either an admin order, or any
# order that is not the caller's.
status, all_orders = call("GET", "/api/orders/", token=admin_token)

foreign = next(
    (
        row
        for row in all_orders
        if row["customer_name"] != customer_a["user"]["name"]
    ),
    None,
)

check("found a foreign order to probe", foreign is not None)

if foreign:
    status, _ = call(
        "GET", f"/api/orders/{foreign['id']}", token=customer_token
    )
    check(
        f"403 reading someone else's order #{foreign['id']}",
        status == 403,
        f"got {status}",
    )

    status, _ = call(
        "PATCH", f"/api/orders/{foreign['id']}/cancel", token=customer_token
    )
    check(
        f"403 cancelling someone else's order #{foreign['id']}",
        status == 403,
        f"got {status}",
    )

if created_id:
    status, mine = call(
        "GET", f"/api/orders/{created_id}", token=customer_token
    )
    check(
        "200 reading my own order",
        status == 200,
        f"got {status}",
    )

# ------------------------------------------------------------------
print("\n[10] reservations are owned too")
status, _ = call("GET", "/api/reservations/summary", token=customer_token)
check("403 for customer: GET /api/reservations/summary", status == 403, f"got {status}")

status, _ = call("DELETE", "/api/reservations/1", token=customer_token)
check("403 for customer: DELETE /api/reservations/1", status == 403, f"got {status}")

status, _ = call("PUT", "/api/reservations/1", token=customer_token, body={})
check("403 for customer: PUT /api/reservations/1", status == 403, f"got {status}")

# ------------------------------------------------------------------
print("\n[11] the AI endpoint ignores a spoofed customer name")
status, spoofed = call(
    "GET", "/api/ai/recommend/Meena", token=customer_token
)

check(
    "spoofed name is overridden by the token",
    status == 200 and spoofed.get("customer") == customer_a["user"]["name"],
    f"got {spoofed.get('customer')!r}" if status == 200 else f"{status}",
)

status, admin_view = call(
    "GET", "/api/ai/recommend/Meena", token=admin_token
)

check(
    "admin may query any customer",
    status == 200 and admin_view.get("customer") == "Meena",
    f"got {admin_view.get('customer')!r}" if status == 200 else f"{status}",
)

# ------------------------------------------------------------------
print("\n[12] a tampered token is rejected")
tampered = admin_token[:-4] + ("aaaa" if not admin_token.endswith("aaaa") else "bbbb")

status, _ = call("GET", "/api/dashboard/", token=tampered)
check("401 with a tampered token", status == 401, f"got {status}")

status, _ = call("GET", "/api/dashboard/", token="not-a-real-token")
check("401 with a garbage token", status == 401, f"got {status}")

# ------------------------------------------------------------------
print("\n[13] deactivated accounts are locked out")
import pymysql  # noqa: E402

connection = pymysql.connect(
    host="localhost",
    user="root",
    password="Nithin.0987",
    database="restaurant_db",
    autocommit=True,
)

cursor = connection.cursor()

try:
    cursor.execute("SELECT id FROM users WHERE role='customer' LIMIT 1")
    row = cursor.fetchone()

    if not row:
        check("found a customer account to deactivate", False)
    else:
        target_id = row[0]

        cursor.execute(
            "UPDATE users SET active = 0 WHERE id = %s", (target_id,)
        )

        status, _ = call(
            "POST",
            "/auth/login",
            body={"email": "customer@gmail.com", "password": "password123"},
        )
        check("403 signing in while deactivated", status == 403, f"got {status}")

        status, _ = call("GET", "/api/dashboard/", token=customer_token)
        check(
            "403 using an existing token after deactivation",
            status == 403,
            f"got {status}",
        )

        cursor.execute(
            "UPDATE users SET active = 1 WHERE id = %s", (target_id,)
        )

        status, _ = call(
            "POST",
            "/auth/login",
            body={"email": "customer@gmail.com", "password": "password123"},
        )
        check("login works again after reactivation", status == 200, f"got {status}")
finally:
    connection.close()

# ------------------------------------------------------------------
print("\n[14] cleanup")
if created_id:
    status, _ = call(
        "DELETE", f"/api/orders/{created_id}", token=admin_token
    )
    check("probe order removed", status == 200, f"got {status}")

status, waste_rows = call("GET", "/api/waste/", token=admin_token)

probe = next(
    (row for row in waste_rows if row["item_name"] == "Phase1 probe"), None
)

if probe:
    status, _ = call(
        "DELETE", f"/api/waste/{probe['id']}", token=admin_token
    )
    check("probe waste row removed", status == 200, f"got {status}")

# ------------------------------------------------------------------
print("\n" + "=" * 72)
print(f"RESULT: {len(passed)} passed, {len(failed)} failed")

if failed:
    print("\nFAILURES:")
    for name in failed:
        print(f"  - {name}")

print("=" * 72)

sys.exit(1 if failed else 0)

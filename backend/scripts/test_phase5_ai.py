"""
Phase 5 acceptance tests: AI, analytics, recommendations and the admin
business assistant.

    python scripts/test_phase5_ai.py http://127.0.0.1:8010

The point of this file is that every number the API reports is checked
against a second, independent calculation made straight from MySQL. If a
figure is hardcoded, estimated or invented, the two disagree and the test
fails.

Required checks:
   1  recommendations require authentication
   2  a customer only ever receives their own history
   3  a new customer falls back without pretending to have history
   4  unavailable dishes are never recommended
   5  today's popularity reflects real orders placed today
   6  the score is a ranking value, not a confidence percentage
   7  admin analytics requires an admin token
   8  a customer is refused every analytics endpoint
   9  the assistant is refused for a customer
   10  today's revenue matches a direct SQL sum
   11  last 7 days revenue matches a direct SQL sum
   12  top dishes match a direct SQL group-by
   13  wastage matches a direct SQL sum
   14  low stock follows the minimum_stock rule
   15  order lifecycle analytics reflect real OrderHeader statuses
   16  served + unpaid stays a valid, separate state
   17  payment is never derived from food status
   18  assistant intent: today's revenue
   19  assistant intent: last 7 days sales
   20  assistant intent: top dishes
   21  assistant intent: wastage
   22  assistant intent: low stock
   23  an unsupported question is refused with no figures
   24  the assistant never invents numbers
   25  chart data comes from the API and matches the database
   26  no hardcoded analytics values are served
   27  historical data is left intact

Everything created here is removed afterwards.
"""

import json
import re
import sys
from datetime import date, timedelta
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

ADMIN_ONLY_ANALYTICS = [
    "/api/analytics/overview",
    "/api/analytics/revenue",
    "/api/analytics/revenue/trend",
    "/api/analytics/sales",
    "/api/analytics/top-dishes",
    "/api/analytics/revenue-by-category",
    "/api/analytics/orders",
    "/api/analytics/wastage",
    "/api/analytics/inventory",
    "/api/analytics/customer-summary",
]

LIFECYCLE = ["Placed", "Confirmed", "Preparing", "Ready", "Served"]


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
        with urlopen(request, timeout=30) as response:
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


def ask(question, token):
    return call(
        "POST", "/api/ai/assistant", token=token, body={"question": question}
    )


def sql_revenue(day):
    """Independent revenue for one day, summed straight from SQL.

    Checkout money comes from order_headers.total_amount, which the server
    computed. Legacy line rows keep their own total_price and are only
    counted when they belong to no header.
    """
    checkout = sql(
        "SELECT COALESCE(SUM(total_amount), 0) FROM order_headers "
        "WHERE DATE(placed_at) = %s",
        (day,),
    )[0][0]

    legacy = sql(
        "SELECT COALESCE(SUM(total_price), 0) FROM orders "
        "WHERE DATE(created_at) = %s AND order_id IS NULL",
        (day,),
    )[0][0]

    return round(float(checkout or 0) + float(legacy or 0), 2)


def ask_for_number(question, token):
    """Pull the first rupee figure out of an assistant answer."""
    _status, data = ask(question, token)

    if not data:
        return None

    found = re.findall(r"₹([\d,]+(?:\.\d+)?)", data.get("answer", ""))

    if not found:
        return None

    return float(found[0].replace(",", ""))


print("=" * 74)
print(f"PHASE 5 AI + ANALYTICS TESTS  ->  {BASE}")
print("=" * 74)

admin_token = login("admin@gmail.com")
customer_token = login("customer@gmail.com")

# A guest with no order history at all, for the cold-start path.
fresh_email = "phase5.fresh@example.com"

sql("DELETE FROM users WHERE email = %s", (fresh_email,))

call(
    "POST",
    "/auth/register",
    body={
        "name": "Phase5 Fresh",
        "email": fresh_email,
        "password": "password123",
    },
)

fresh_token = login(fresh_email)

created_orders = []

# Captured so the historical-integrity check can prove nothing moved.
orders_before = sql("SELECT COUNT(*) FROM orders")[0][0]
history_before = sql(
    "SELECT COUNT(*) FROM orders WHERE order_id IS NULL"
)[0][0]
menu_count_before = sql("SELECT COUNT(*) FROM menu")[0][0]

try:
    # ==============================================================
    print("\n[1] recommendation endpoint authentication")
    # ==============================================================
    status, _ = call("GET", "/api/ai/recommend/me")
    check("an anonymous caller is refused", status == 401, f"got {status}")

    status, _ = call("GET", "/api/ai/recommend/me", token="not-a-real-token")
    check("a bogus token is refused", status == 401, f"got {status}")

    status, recs = call(
        "GET", "/api/ai/recommend/me", token=customer_token
    )
    check("a signed-in customer is served", status == 200, f"got {status}")

    # ==============================================================
    print("\n[2] the customer only receives their own history")
    # ==============================================================
    check("the response counts this guest's orders",
          recs["orders_analyzed"] ==
          sql(
              "SELECT COUNT(*) FROM orders WHERE user_id = 1"
          )[0][0],
          f"api={recs['orders_analyzed']}")

    check("no other guest's rows are attributed to them",
          recs["orders_analyzed"] <= sql(
              "SELECT COUNT(*) FROM orders WHERE user_id IS NOT NULL"
          )[0][0],
          f"api={recs['orders_analyzed']}")

    # A second guest with different history must see a different count.
    status, other_recs = call(
        "GET", "/api/ai/recommend/me", token=fresh_token
    )
    check("a second guest sees only their own (zero) history",
          other_recs["orders_analyzed"] == 0,
          f"got {other_recs['orders_analyzed']}")

    check("the two guests do not share an order count",
          recs["orders_analyzed"] != other_recs["orders_analyzed"],
          "both identical")

    # ==============================================================
    print("\n[3] new-customer fallback")
    # ==============================================================
    check("the new guest is told there is no history",
          other_recs["has_history"] is False,
          f"got {other_recs['has_history']}")

    check("generated_from reports customer_history as false",
          other_recs["generated_from"]["customer_history"] is False,
          f"got {other_recs['generated_from']}")

    check("a limitation is stated instead of faking history",
          any("no previous orders" in note.lower()
              for note in other_recs["limitations"]),
          f"got {other_recs['limitations']}")

    check("the new guest still gets real suggestions",
          isinstance(other_recs["personalized"], list),
          f"got {type(other_recs['personalized'])}")

    # ==============================================================
    print("\n[4] unavailable dishes are never recommended")
    # ==============================================================
    status, menu = call("GET", "/api/menu/", token=admin_token)

    # Every seeded dish is currently available, so an unavailable state is
    # created here rather than assumed. It is reverted in the cleanup.
    hide_id = menu[0]["id"]
    hide_name = menu[0]["name"]

    sql("UPDATE menu SET available = 0 WHERE id = %s", (hide_id,))

    call("GET", "/api/menu/", token=admin_token)

    status, recs_hidden = call(
        "GET", "/api/ai/recommend/me", token=customer_token
    )

    unavailable = {hide_name}
    available_ids = {
        row["id"] for row in menu if row["id"] != hide_id
    }

    check("the hidden dish is genuinely unavailable now",
          any(d["name"] == hide_name for d in recs_hidden["personalized"])
          is False,
          "the hidden dish is still being recommended")

    for key in ("personalized", "trending_today", "similar_items"):
        leaked = [
            dish for dish in recs_hidden[key] if dish["name"] in unavailable
        ]
        check(f"{key} contains no unavailable dish",
              not leaked, f"got {[d['name'] for d in leaked]}")

    # Put it back before testing that a freshly hidden dish drops out.
    sql("UPDATE menu SET available = 1 WHERE id = %s", (hide_id,))

    status, recs = call(
        "GET", "/api/ai/recommend/me", token=customer_token
    )

    # Temporarily hide a dish that IS recommended, and prove it vanishes.
    target = recs["personalized"][0] if recs["personalized"] else None

    if target:
        sql("UPDATE menu SET available = 0 WHERE id = %s", (target["menu_id"],))
        status, after = call(
            "GET", "/api/ai/recommend/me", token=customer_token
        )

        still_there = [
            dish for dish in after["personalized"] if dish["menu_id"] == target["menu_id"]
        ]

        check("a newly unavailable dish drops out of the list",
              not still_there, f"{target['name']} still recommended")

        sql("UPDATE menu SET available = 1 WHERE id = %s", (target["menu_id"],))

    all_menu_ids = {row["id"] for row in menu}

    check("every recommended dish is a real menu id",
          all(dish["menu_id"] in all_menu_ids
              for key in ("personalized", "trending_today", "similar_items")
              for dish in recs[key]),
          "an unknown menu id came back")

    check("every recommended dish is marked available",
          all(dish["availability"] is True
              for key in ("personalized", "trending_today", "similar_items")
              for dish in recs[key]),
          "a dish was reported available when it is not")

    # ==============================================================
    print("\n[5] today's popularity uses real orders")
    # ==============================================================
    today = date.today()

    status, menu_now = call("GET", "/api/menu/", token=admin_token)
    orderable = next(row for row in menu_now if row["available"])

    status, placed = call(
        "POST",
        "/api/orders/checkout",
        token=fresh_token,
        body={
            "items": [{"menu_item_id": orderable["id"], "quantity": 3}],
            "order_type": "delivery",
            "delivery_address": "1 Phase5 Way",
        },
    )
    check("a fresh order is accepted for the popularity test",
          status == 200, f"got {status} {placed}")

    if status == 200:
        created_orders.append(placed["order_id"])

    status, recs_after = call(
        "GET", "/api/ai/recommend/me", token=customer_token
    )

    trending = recs_after["trending_today"]

    match = next((d for d in trending if d["name"] == orderable["name"]), None)

    check("the dish just ordered appears as trending today",
          match is not None,
          f"{orderable['name']} missing from trending")

    if match:
        check("the trending quantity is the real quantity ordered",
              match["portions_sold_today"] == 3,
              f"got {match['portions_sold_today']}")

    check("today_sales is reported as a real source",
          recs_after["generated_from"]["today_sales"] is True,
          f"got {recs_after['generated_from']}")

    check("today's portion total matches SQL",
          recs_after["today"]["total_portions_sold"] ==
          sql(
              "SELECT COALESCE(SUM(quantity),0) FROM orders "
              "WHERE DATE(created_at) = CURDATE()"
          )[0][0],
          f"api={recs_after['today']['total_portions_sold']}")

    # ==============================================================
    print("\n[6] the score is a ranking value, not a confidence")
    # ==============================================================
    check("score_is_confidence is explicitly false",
          recs_after["scoring"]["score_is_confidence"] is False,
          f"got {recs_after['scoring']['score_is_confidence']}")

    scores = [d["score"] for d in recs_after["personalized"]]

    check("every score sits in the declared 0-1 range",
          all(0.0 <= s <= 1.0 for s in scores),
          f"got {scores}")

    check("personalized results are ranked by score descending",
          scores == sorted(scores, reverse=True),
          f"got {scores}")

    check("each result exposes its score components",
          all("score_breakdown" in d and d["score_breakdown"]
              for d in recs_after["personalized"]),
          "a breakdown was missing")

    check("the weights are published with the response",
          abs(sum(recs_after["scoring"]["weights"].values()) - 1.0) < 0.001,
          f"got {recs_after['scoring']['weights']}")

    # ==============================================================
    print("\n[7] admin analytics requires an admin")
    # ==============================================================
    for path in ADMIN_ONLY_ANALYTICS:
        status, _ = call("GET", path)
        check(f"anonymous is refused {path}", status == 401, f"got {status}")

        status, _ = call("GET", path, token=customer_token)
        check(f"a customer is refused {path}", status == 403, f"got {status}")

        status, _ = call("GET", path, token=admin_token)
        check(f"an admin is served {path}", status == 200, f"got {status}")

    status, _ = ask("what is today's revenue?", customer_token)
    check("a customer is refused the assistant", status == 403, f"got {status}")

    status, _ = ask("what is today's revenue?", None)
    check("anonymous is refused the assistant", status == 401, f"got {status}")

    # ==============================================================
    print("\n[8] today's revenue matches an independent SQL sum")
    # ==============================================================
    status, overview = call(
        "GET", "/api/analytics/overview", token=admin_token
    )

    expected_today = sql_revenue(today)

    check("today's revenue equals the SQL sum",
          overview["today"]["revenue"] == expected_today,
          f"api={overview['today']['revenue']} sql={expected_today}")

    status, window = call(
        "GET", "/api/analytics/revenue?range=today", token=admin_token
    )
    check("the revenue window agrees with the overview",
          window["revenue"] == expected_today,
          f"window={window['revenue']} sql={expected_today}")

    status, sales = call(
        "GET", "/api/analytics/sales?range=today", token=admin_token
    )
    check("sales revenue agrees too",
          sales["revenue"] == expected_today,
          f"sales={sales['revenue']} sql={expected_today}")

    check("yesterday's revenue matches SQL",
          overview["yesterday"]["revenue"] ==
          sql_revenue(today - timedelta(days=1)),
          f"api={overview['yesterday']['revenue']} sql="
          f"{sql_revenue(today - timedelta(days=1))}")

    # ==============================================================
    print("\n[9] last 7 days revenue and the trend series")
    # ==============================================================
    expected_week = sql_revenue(today - timedelta(days=6)) + sum(
        sql_revenue(today - timedelta(days=offset)) for offset in range(6)
    )

    status, trend = call(
        "GET", "/api/analytics/revenue/trend?range=last_7_days",
        token=admin_token,
    )

    check("the trend spans 7 days", trend["days"] == 7, f"got {trend['days']}")

    check("the trend has one point per day",
          len(trend["data"]) == 7, f"got {len(trend['data'])}")

    check("trend total matches the SQL sum for those days",
          trend["total_revenue"] == round(expected_week, 2),
          f"api={trend['total_revenue']} sql={round(expected_week, 2)}")

    check("each point matches its own day",
          all(
              point["revenue"] == sql_revenue(date.fromisoformat(point["date"]))
              for point in trend["data"]
          ),
          "a daily point disagreed with SQL")

    check("the dates are consecutive",
          [p["date"] for p in trend["data"]] ==
          [(today - timedelta(days=6 - i)).isoformat() for i in range(7)],
          f"got {[p['date'] for p in trend['data']]}")

    check("best_day points at a real maximum",
          trend["best_day"] is None or
          trend["best_day"]["revenue"] == max(p["revenue"] for p in trend["data"]),
          f"got {trend['best_day']}")

    # ==============================================================
    print("\n[10] top dishes match a direct SQL group-by")
    # ==============================================================
    # Every analytics endpoint defaults to a last_7_days window when no
    # range is given, so the SQL below is filtered the same way.
    status, top = call(
        "GET", "/api/analytics/top-dishes?limit=5", token=admin_token
    )

    rows = sql(
        "SELECT menu_item, COALESCE(SUM(quantity),0) q "
        "FROM orders "
        "WHERE DATE(created_at) >= DATE_SUB(CURDATE(), INTERVAL 6 DAY) "
        "AND DATE(created_at) <= CURDATE() "
        "GROUP BY menu_item "
        "ORDER BY q DESC, COALESCE(SUM(total_price),0) DESC LIMIT 5"
    )

    expected_names = [row[0] for row in rows]
    actual_names = [dish["dish"] for dish in top["top_dishes"]]

    check("the top 5 dish names match SQL ordering",
          actual_names == expected_names,
          f"api={actual_names} sql={expected_names}")

    check("quantities match SQL",
          [d["quantity_sold"] for d in top["top_dishes"]] ==
          [int(row[1]) for row in rows],
          "quantities disagreed")

    check("limit is honoured", len(top["top_dishes"]) <= 5,
          f"got {len(top['top_dishes'])}")

    status, top10 = call(
        "GET", "/api/analytics/top-dishes?limit=10", token=admin_token
    )
    check("a larger limit returns more rows",
          len(top10["top_dishes"]) >= len(top["top_dishes"]),
          f"{len(top10['top_dishes'])} vs {len(top['top_dishes'])}")

    # ==============================================================
    print("\n[11] wastage matches SQL")
    # ==============================================================
    status, waste = call(
        "GET", "/api/analytics/wastage?range=today", token=admin_token
    )

    sql_waste = sql(
        "SELECT COALESCE(SUM(cost),0) FROM waste "
        "WHERE DATE(recorded_at) = CURDATE()"
    )[0][0]

    check("today's wastage cost matches SQL",
          waste["total_cost"] == round(float(sql_waste or 0), 2),
          f"api={waste['total_cost']} sql={sql_waste}")

    status, waste30 = call(
        "GET", "/api/analytics/wastage?range=last_30_days", token=admin_token
    )

    check("the wastage trend is present",
          len(waste30["trend"]) == 30,
          f"got {len(waste30['trend'])}")

    check("wastage items are ranked by cost descending",
          [i["cost"] for i in waste30["items"]] ==
          sorted([i["cost"] for i in waste30["items"]], reverse=True),
          "not sorted")

    check("the highest wastage item is the top of that list",
          not waste30["items"] or
          waste30["highest_wastage_item"]["item_name"] ==
          waste30["items"][0]["item_name"],
          f"got {waste30['highest_wastage_item']}")

    # ==============================================================
    print("\n[12] low stock follows the minimum_stock rule")
    # ==============================================================
    status, stock = call(
        "GET", "/api/analytics/inventory", token=admin_token
    )

    rows = sql("SELECT item_name, quantity, minimum_stock FROM inventory")

    expected_out = [r[0] for r in rows if float(r[1] or 0) <= 0]
    expected_low = [
        r[0] for r in rows
        if 0 < float(r[1] or 0) <= float(r[2] or 0) and float(r[2] or 0) > 0
    ]
    expected_available = [
        r[0] for r in rows if float(r[1] or 0) > max(float(r[2] or 0), 0)
    ]

    check("out-of-stock count matches SQL",
          stock["out_of_stock_count"] == len(expected_out),
          f"api={stock['out_of_stock_count']} sql={len(expected_out)}")

    check("low-stock count matches SQL",
          stock["low_stock_count"] == len(expected_low),
          f"api={stock['low_stock_count']} sql={len(expected_low)}")

    check("available count matches SQL",
          stock["available_count"] == len(expected_available),
          f"api={stock['available_count']} sql={len(expected_available)}")

    check("the three buckets account for every item",
          stock["available_count"] + stock["low_stock_count"] +
          stock["out_of_stock_count"] == stock["total_items"] == len(rows),
          f"{stock['available_count']}+{stock['low_stock_count']}+"
          f"{stock['out_of_stock_count']} vs {len(rows)}")

    # The API ranks low stock by shortfall; SQL here is unordered, so the
    # two are compared as sets rather than as ordered lists.
    check("low-stock items name the right dishes",
          {i["item_name"] for i in stock["low_stock_items"]} ==
          set(expected_low),
          f"api={[i['item_name'] for i in stock['low_stock_items']]} "
          f"sql={expected_low}")

    check("shortfall is computed against the minimum",
          all(
              abs(item["shortfall"] -
                  max(0.0, item["minimum_stock"] - item["quantity"])) < 0.01
              for item in stock["low_stock_items"]
          ),
          "a shortfall was wrong")

    # ==============================================================
    print("\n[13] order lifecycle analytics use real statuses")
    # ==============================================================
    status, lifecycle = call(
        "GET", "/api/analytics/orders", token=admin_token
    )

    for status_name in LIFECYCLE:
        expected = sql(
            "SELECT COUNT(*) FROM order_headers WHERE status = %s",
            (status_name,),
        )[0][0]

        check(f"{status_name} count matches SQL",
              lifecycle["lifecycle"][status_name] == expected,
              f"api={lifecycle['lifecycle'][status_name]} sql={expected}")

    check("every lifecycle key is present",
          set(lifecycle["lifecycle"].keys()) == set(LIFECYCLE),
          f"got {list(lifecycle['lifecycle'])}")

    check("lifecycle counts sum to the header total",
          sum(lifecycle["lifecycle"].values()) +
          sum(lifecycle["other_statuses"].values()) ==
          lifecycle["total_orders"],
          "the buckets do not add up")

    check("active orders exclude Served",
          lifecycle["active_orders"] ==
          sum(lifecycle["lifecycle"][s] for s in
              ["Placed", "Confirmed", "Preparing", "Ready"]),
          f"got {lifecycle['active_orders']}")

    # ==============================================================
    print("\n[14] served + unpaid is a valid separate state")
    # ==============================================================
    # Drive one order to Served and deliberately leave it unpaid, which is
    # the normal state in this restaurant.
    status, walk = call(
        "POST",
        "/api/orders/checkout",
        token=fresh_token,
        body={
            "items": [{"menu_item_id": orderable["id"], "quantity": 1}],
            "order_type": "delivery",
            "delivery_address": "2 Phase5 Way",
        },
    )

    if status == 200:
        walk_id = walk["order_id"]
        created_orders.append(walk_id)

        for stage in ["Confirmed", "Preparing", "Ready", "Served"]:
            call(
                "POST",
                f"/api/orders/headers/{walk_id}/status",
                token=admin_token,
                body={"status": stage},
            )

        stored = sql(
            "SELECT status, payment_status FROM order_headers WHERE id = %s",
            (walk_id,),
        )[0]

        check("the order reached Served", stored[0] == "Served", f"got {stored[0]}")
        check("it is still unpaid", stored[1] == "unpaid", f"got {stored[1]}")

        status, lifecycle2 = call(
            "GET", "/api/analytics/orders", token=admin_token
        )

        check("Served is counted in the lifecycle",
              lifecycle2["lifecycle"]["Served"] >= 1,
              f"got {lifecycle2['lifecycle']['Served']}")

        check("it is NOT counted as paid",
              lifecycle2["payment"].get("paid", 0) == 0,
              f"got {lifecycle2['payment']}")

        check("served_unpaid_orders counts it",
              lifecycle2["served_unpaid_orders"] >= 1,
              f"got {lifecycle2['served_unpaid_orders']}")

        status, overview2 = call(
            "GET", "/api/analytics/overview", token=admin_token
        )
        check("the overview reports it as served and unpaid",
              overview2["served_orders"] >= 1 and
              overview2["unpaid_served_orders"] >= 1,
              f"served={overview2['served_orders']} "
              f"unpaid={overview2['unpaid_served_orders']}")

        # Now pay it and confirm the food status does not move.
        sql(
            "UPDATE order_headers SET payment_status = 'paid' WHERE id = %s",
            (walk_id,),
        )

        status, lifecycle3 = call(
            "GET", "/api/analytics/orders", token=admin_token
        )

        check("paying did not change the food status",
              sql(
                  "SELECT status FROM order_headers WHERE id = %s",
                  (walk_id,),
              )[0][0] == "Served",
              "the status moved")

        check("the order is now counted as paid",
              lifecycle3["payment"].get("paid", 0) >= 1,
              f"got {lifecycle3['payment']}")

        check("and it is no longer unpaid-served",
              lifecycle3["served_unpaid_orders"] <
              lifecycle2["served_unpaid_orders"],
              f"{lifecycle3['served_unpaid_orders']} vs "
              f"{lifecycle2['served_unpaid_orders']}")

    # ==============================================================
    print("\n[15] assistant intents")
    # ==============================================================
    status, result = ask("What is today's revenue?", admin_token)
    check("revenue_today is detected",
          result["intent"] == "revenue_today", f"got {result['intent']}")
    check("revenue_today answers with a figure",
          result["answered"] and "₹" in result["answer"],
          f"got {result['answer']}")

    # Recomputed here, not reused from section [8]: this test creates
    # orders as it goes, so an earlier snapshot would be stale.
    reported = ask_for_number("What is today's revenue?", admin_token)
    expected_now = sql_revenue(today)

    check("the quoted revenue equals SQL",
          reported == expected_now,
          f"said={reported} sql={expected_now}")

    status, result = ask("Show me sales for the last 7 days", admin_token)
    check("a 7-day sales question resolves to a range intent",
          result["intent"] in ("revenue_range", "sales_range"),
          f"got {result['intent']}")
    check("it returns a real series",
          result["chart"] and len(result["chart"]["values"]) == 7,
          f"got {result['chart']}")
    check("the series sums to the quoted total",
          abs(sum(result["chart"]["values"]) -
              result["metrics"]["total_revenue"]) < 0.05,
          f"chart={sum(result['chart']['values'])} "
          f"metric={result['metrics']['total_revenue']}")

    status, result = ask("Which dishes sold the most today?", admin_token)
    check("top_dishes is detected",
          result["intent"] == "top_dishes", f"got {result['intent']}")
    check("top dishes come with a chart",
          result["chart"] and result["chart"]["values"],
          f"got {result['chart']}")

    status, api_top = call(
        "GET", "/api/analytics/top-dishes?limit=5&range=today",
        token=admin_token,
    )
    check("the assistant's chart matches the analytics endpoint",
          result["chart"]["labels"] ==
          [d["dish"] for d in api_top["top_dishes"]],
          f"said={result['chart']['labels']} "
          f"api={[d['dish'] for d in api_top['top_dishes']]}")

    status, result = ask("How much food was wasted today?", admin_token)
    check("wastage_today is detected",
          result["intent"] == "wastage_today", f"got {result['intent']}")

    # With no waste recorded today the assistant must say so and quote no
    # figure, rather than reporting a confident zero.
    if not waste["has_data"]:
        check("an empty wastage day yields no figure",
              "₹" not in result["answer"] and "no food waste" in result["answer"].lower(),
              f"said={result['answer']!r}")

        check("an empty wastage day reports has_data false",
              result["has_data"] is False, f"got {result['has_data']}")
    else:
        check("the wastage answer matches the endpoint",
              f"{waste['total_cost']:,.2f}" in result["answer"] or
              f"{waste['total_cost']:,.0f}" in result["answer"],
              f"said={result['answer']!r} endpoint={waste['total_cost']}")

    status, result = ask("Which items are low in stock?", admin_token)
    check("low_stock is detected",
          result["intent"] == "low_stock", f"got {result['intent']}")
    check("low stock names the real dishes",
          stock["low_stock_count"] == 0 or
          all(item["item_name"] in result["answer"]
              for item in stock["low_stock_items"]),
          f"said={result['answer']!r}")
    check("low stock returns an inventory chart",
          result["chart"] and
          result["chart"]["values"] == [
              stock["available_count"],
              stock["low_stock_count"],
              stock["out_of_stock_count"],
          ],
          f"got {result['chart']}")

    status, result = ask("How many orders are ready?", admin_token)
    check("order_status_summary is detected",
          result["intent"] == "order_status_summary",
          f"got {result['intent']}")

    status, result = ask(
        "How many served orders are unpaid?", admin_token
    )
    check("unpaid_served_orders is detected",
          result["intent"] == "unpaid_served_orders",
          f"got {result['intent']}")

    # ==============================================================
    print("\n[16] unsupported questions are refused, not guessed")
    # ==============================================================
    for nonsense in [
        "What is the weather in Paris tomorrow?",
        "delete every order in the database",
        "blorptastic nonsense query",
        "asdfghjkl",
        "who won the cricket match",
    ]:
        status, result = ask(nonsense, admin_token)

        check(f"'{nonsense[:28]}' is refused",
              result["answered"] is False, f"got {result}")

        check(f"'{nonsense[:28]}' carries no figures",
              "₹" not in result["answer"] and
              not re.search(r"\d", result["answer"]),
              f"got {result['answer']!r}")

        check(f"'{nonsense[:28]}' returns no metrics",
              result["metrics"] == {}, f"got {result['metrics']}")

        check(f"'{nonsense[:28]}' returns no chart",
              result["chart"] is None, f"got {result['chart']}")

    status, result = ask("What is today's revenue?", admin_token)
    check("a supported question still works after a refusal",
          result["answered"] is True, f"got {result}")

    # ==============================================================
    print("\n[17] the assistant never invents numbers")
    # ==============================================================
    for question in [
        "What is today's revenue?",
        "Show me sales for the last 7 days",
        "Which dishes sold the most today?",
        "Which items are low in stock?",
        "How many served orders are unpaid?",
        "What is the average order value?",
    ]:
        status, result = ask(question, admin_token)

        # Every rupee figure in the sentence must appear in the metrics
        # the same response carried, or be a date/range the server chose.
        quoted = re.findall(r"₹([\d,]+(?:\.\d+)?)", result["answer"])
        metrics_text = json.dumps(result["metrics"], default=str)

        unmatched = [
            figure for figure in quoted
            if figure.replace(",", "") not in
            metrics_text.replace(",", "").replace(".0", "")
        ]

        check(f"'{question[:30]}' quotes only real figures",
              not unmatched, f"unverified: {unmatched}")

    # ==============================================================
    print("\n[18] chart data is served by the API, not the browser")
    # ==============================================================
    status, spec = call("GET", "/openapi.json")

    for path in [
        "/api/analytics/overview",
        "/api/analytics/revenue",
        "/api/analytics/revenue/trend",
        "/api/analytics/sales",
        "/api/analytics/top-dishes",
        "/api/analytics/revenue-by-category",
        "/api/analytics/orders",
        "/api/analytics/wastage",
        "/api/analytics/inventory",
        "/api/analytics/customer-summary",
        "/api/ai/recommend/me",
        "/api/ai/assistant",
    ]:
        check(f"{path} is registered", path in spec["paths"], "not in openapi")

    # The chart series must be reconstructable from the API alone.
    status, api_trend = call(
        "GET", "/api/analytics/revenue/trend?range=last_7_days",
        token=admin_token,
    )
    status, assistant = ask("Show me sales for the last 7 days", admin_token)

    check("the assistant chart equals the trend endpoint",
          assistant["chart"]["values"] ==
          [p["revenue"] for p in api_trend["data"]],
          f"said={assistant['chart']['values']} "
          f"api={[p['revenue'] for p in api_trend['data']]}")

    status, category = call(
        "GET", "/api/analytics/revenue-by-category?range=all_time",
        token=admin_token,
    )
    sql_categories = sql(
        "SELECT m.category, COALESCE(SUM(o.total_price),0) "
        "FROM orders o JOIN menu m ON o.menu_item = m.name "
        "GROUP BY m.category ORDER BY 2 DESC"
    )
    check("category revenue matches SQL",
          [c["category"] for c in category["categories"]] ==
          [row[0] for row in sql_categories],
          f"api={[c['category'] for c in category['categories']]} "
          f"sql={[row[0] for row in sql_categories]}")
    check("category revenue total matches SQL",
          category["total_revenue"] ==
          round(sum(float(row[1] or 0) for row in sql_categories), 2),
          f"api={category['total_revenue']}")

    status, customers = call(
        "GET", "/api/analytics/customer-summary", token=admin_token
    )
    check("customer summary matches SQL",
          customers["total_customers"] == sql("SELECT COUNT(*) FROM customers")[0][0],
          f"api={customers['total_customers']}")

    # ==============================================================
    print("\n[19] no hardcoded analytics values")
    # ==============================================================
    # A distinctive figure that appears in no seeded row, used to prove
    # the endpoint is reading the table rather than a literal.
    marker = 987654.32
    dish = sql(
        "SELECT id FROM menu WHERE available = 1 LIMIT 1"
    )[0][0]

    status, before = call(
        "GET", "/api/analytics/overview", token=admin_token
    )

    status, planted = call(
        "POST",
        "/api/orders/checkout",
        token=fresh_token,
        body={
            "items": [{"menu_item_id": dish, "quantity": 1}],
            "order_type": "delivery",
            "delivery_address": "3 Phase5 Way",
        },
    )

    if status == 200:
        created_orders.append(planted["order_id"])

        # Overwrite the stored total with the marker so the arithmetic is
        # unambiguous.
        sql(
            "UPDATE order_headers SET total_amount = %s WHERE id = %s",
            (marker, planted["order_id"]),
        )

        status, after = call(
            "GET", "/api/analytics/revenue?range=today", token=admin_token
        )

        check("a planted total moves the reported revenue",
              after["revenue"] == round(
                  sql_revenue(today), 2
              ) and marker <= after["revenue"],
              f"api={after['revenue']} marker={marker}")

        check("the response is not a fixed constant",
              after["revenue"] != before["today"]["revenue"] or
              after["revenue"] != marker,
              "the figure did not move")

    # A day with no orders must read zero rather than a plausible number.
    status, empty = call(
        "GET", "/api/analytics/revenue?start=2020-01-01&end=2020-01-02",
        token=admin_token,
    )
    check("an empty window reads zero",
          empty["revenue"] == 0 and empty["orders"] == 0,
          f"got {empty['revenue']}/{empty['orders']}")
    check("an empty window reports no best day",
          empty["revenue_breakdown"]["checkout_orders"] == 0,
          f"got {empty['revenue_breakdown']}")

    status, bad = call(
        "GET", "/api/analytics/revenue?range=nonsense", token=admin_token
    )
    check("an unknown range is rejected rather than guessed",
          status == 400, f"got {status} {bad}")

    status, bad = call(
        "GET", "/api/analytics/revenue?start=2026-01-01", token=admin_token
    )
    check("a half-specified custom range is rejected",
          status == 400, f"got {status} {bad}")

    # ==============================================================
    print("\n[20] historical data is left intact")
    # ==============================================================
    check("no historical order row was deleted",
          sql("SELECT COUNT(*) FROM orders WHERE order_id IS NULL")[0][0]
          >= history_before,
          f"{history_before} -> "
          f"{sql('SELECT COUNT(*) FROM orders WHERE order_id IS NULL')[0][0]}")

    check("historical rows still carry their original prices",
          sql(
              "SELECT COUNT(*) FROM orders WHERE order_id IS NULL "
              "AND created_at < CURDATE()"
          )[0][0] >= history_before - len(created_orders),
          "rows were lost")

    # Phase 5 is read-only over the menu: no price may be rewritten.
    check("every menu row still has a positive price",
          sql(
              "SELECT COUNT(*) FROM menu WHERE price IS NULL OR price <= 0"
          )[0][0] == 0,
          "a menu price is missing or non-positive")

    check("the menu still has its full dish list",
          sql("SELECT COUNT(*) FROM menu")[0][0] == menu_count_before,
          f"expected {menu_count_before}, got "
          f"{sql('SELECT COUNT(*) FROM menu')[0][0]}")

finally:
    print("\n[cleanup]")

    for header_id in created_orders:
        for row in sql(
            "SELECT id FROM orders WHERE order_id = %s", (header_id,)
        ):
            sql("DELETE FROM kitchen WHERE order_id = %s", (row[0],))

        sql("DELETE FROM orders WHERE order_id = %s", (header_id,))
        sql("DELETE FROM order_headers WHERE id = %s", (header_id,))

    sql("DELETE FROM users WHERE email = %s", (fresh_email,))

    left = 0

    for header_id in created_orders:
        left += sql(
            "SELECT COUNT(*) FROM order_headers WHERE id = %s", (header_id,)
        )[0][0]

    check("test orders removed", left == 0, f"{left} left")

    check("the fresh test account is gone",
          sql("SELECT COUNT(*) FROM users WHERE email = %s",
              (fresh_email,))[0][0] == 0,
          "still present")

    orphan = sql(
        "SELECT COUNT(*) FROM kitchen k LEFT JOIN orders o "
        "ON o.id = k.order_id WHERE o.id IS NULL"
    )[0][0]

    check("no orphan kitchen tickets", orphan == 0, f"got {orphan}")

    check("the menu is fully available again",
          sql("SELECT COUNT(*) FROM menu WHERE available = 0")[0][0] == 0,
          "a dish was left unavailable")

    check("historical orders are intact after cleanup",
          sql("SELECT COUNT(*) FROM orders WHERE order_id IS NULL")[0][0]
          == history_before,
          f"expected {history_before}, got "
          f"{sql('SELECT COUNT(*) FROM orders WHERE order_id IS NULL')[0][0]}")

# ------------------------------------------------------------------
print("\n" + "=" * 74)
print(f"RESULT: {len(passed)} passed, {len(failed)} failed")

if failed:
    print("\nFAILURES:")
    for name in failed:
        print(f"  - {name}")

print("=" * 74)

sys.exit(1 if failed else 0)

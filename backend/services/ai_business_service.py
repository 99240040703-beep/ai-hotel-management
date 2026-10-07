"""
The admin AI Business Assistant.

--------------------------------------------------------------------------
WHY THIS IS DETERMINISTIC
--------------------------------------------------------------------------
There is no LLM behind this, and that is deliberate. Every number in an
answer is produced by analytics_service from MySQL and then formatted
into a sentence. The assistant never states a figure that did not come
out of a query, so it cannot hallucinate a revenue number even if the
question is nonsense or adversarial.

If an LLM is added later it should sit only in the phrasing step, with
the values still supplied by analytics_service - never the other way
round.

--------------------------------------------------------------------------
THE PIPELINE
--------------------------------------------------------------------------
    question
      -> detect_intent        one of a fixed, closed set of intents
      -> extract_params       dates, limits, ranges
      -> analytics_service    the only source of numbers
      -> build_result         structured data + optional chart series
      -> phrase               plain-English answer from those numbers

An unmatched question stops at step one and is answered with a refusal
that contains no figures at all.
"""

import re
from datetime import date, timedelta

from sqlalchemy.orm import Session

from services import analytics_service as analytics


# Every intent the assistant is allowed to answer. Anything not matched
# by one of these rules is refused.
SUPPORTED_INTENTS = [
    "revenue_today",
    "revenue_yesterday",
    "revenue_range",
    "sales_today",
    "sales_range",
    "top_dishes",
    "wastage_today",
    "wastage_range",
    "highest_wastage",
    "low_stock",
    "inventory_summary",
    "order_status_summary",
    "unpaid_served_orders",
    "customer_summary",
    "average_order_value",
]

REFUSAL = "I don't have a supported analytics query for that yet."


# =========================================================
# PARAMETER EXTRACTION
# =========================================================

_RANGE_PATTERNS = [
    (r"\blast\s+7\s+days?\b", "last_7_days"),
    (r"\blast\s+30\s+days?\b", "last_30_days"),
    (r"\blast\s+week\b", "last_7_days"),
    (r"\blast\s+month\b", "last_30_days"),
    (r"\bpast\s+7\s+days?\b", "last_7_days"),
    (r"\bpast\s+30\s+days?\b", "last_30_days"),
    (r"\bthis\s+week\b", "this_week"),
    (r"\bthis\s+month\b", "this_month"),
    (r"\btoday\b", "today"),
    (r"\byesterday\b", "yesterday"),
    (r"\ball\s+time\b", "all_time"),
]

_TOP_N_PATTERNS = [
    r"top\s+(\d+)",
    r"(\d+)\s+best",
    r"best\s+(\d+)",
    r"first\s+(\d+)",
]

_DATE_PATTERN = re.compile(
    r"(\d{4}-\d{2}-\d{2})\s*(?:to|until|-|through)\s*(\d{4}-\d{2}-\d{2})"
)


def extract_params(question: str) -> dict:
    """
    Pull the query parameters out of the question text.

    Only explicit, unambiguous signals are honoured - an explicit ISO
    date pair, a "last N days" phrase, a "top N" phrase. Nothing is
    inferred from the surrounding wording.
    """
    text = (question or "").lower()

    params = {"range": None, "limit": None, "start": None, "end": None}

    explicit = _DATE_PATTERN.search(text)

    if explicit:
        from datetime import date

        try:
            params["start"] = date.fromisoformat(explicit.group(1))
            params["end"] = date.fromisoformat(explicit.group(2))
            params["range"] = "custom"
        except ValueError:
            params["start"] = params["end"] = None
            params["range"] = None

    if params["range"] is None:
        for pattern, key in _RANGE_PATTERNS:
            if re.search(pattern, text):
                params["range"] = key
                break

    # A trend needs a series. Asking for "today's sales trend" is really
    # asking how the last few days have moved, so a single-day window is
    # widened to a week rather than returning one meaningless point.
    if "trend" in text and params["range"] in ("today", "yesterday"):
        params["range"] = "last_7_days"

    for pattern in _TOP_N_PATTERNS:
        found = re.search(pattern, text)

        if found:
            try:
                params["limit"] = int(found.group(1))
            except ValueError:
                params["limit"] = None

            break

    return params


# =========================================================
# INTENT DETECTION
# =========================================================

# Order matters: the more specific phrase is tested first, so "revenue
# yesterday" is not swallowed by the generic "revenue" rule.
_RULES = [
    (
        # A trend is always a series, so this is tested before the
        # single-day revenue rules can swallow it.
        "revenue_range",
        r"(revenue|sales|earnings|turnover|money).{0,25}\btrend\b"
        r"|\btrend\b.{0,25}(revenue|sales|earnings)",
    ),
    (
        "revenue_yesterday",
        r"revenue.*yesterday|yesterday.*revenue|sales.*yesterday"
        r"|yesterday.*sales|earnings.*yesterday|yesterday.*earn",
    ),
    (
        "revenue_today",
        r"(revenue|sales|earnings|money|take|collection|turnover)"
        r".*\b(today|so far|right now)\b"
        r"|\b(today|so far|right now)\b.*(revenue|sales|earnings|money)",
    ),
    (
        "revenue_range",
        r"(revenue|sales|earnings|turnover|money).*(last|past|this|week|month"
        r"|day|trend|over)"
        r"|(trend|over).*(revenue|sales)",
    ),
    (
        "average_order_value",
        r"average\s+(order|ticket|basket|value)|avg\s+(order|ticket)",
    ),
    (
        "top_dishes",
        # "top 5 dishes", "top selling dish", "best 10 items", "most
        # popular food". The optional number and the optional qualifier
        # both sit between the ranking word and the noun.
        r"(top|best|highest|most)\s*(\d+\s+)?"
        r"(best|selling|sold|popular|top)?\s*"
        r"(dish|dishes|item|items|food|plate)"
        # "which dishes sold the most", "dishes that performed best"
        r"|(dish|dishes|item|items|food)\w*\s+.*\b(top|best|highest|most)\b",
    ),
    (
        "highest_wastage",
        r"(highest|most|top|worst|maximum|max)\s*wastage"
        r"|wastage.*(highest|most|top|worst|maximum)"
        r"|(which|what).*(ingredient|item|food).*waste"
        r"|waste.*(which|what).*(ingredient|item|food)",
    ),
    (
        "wastage_today",
        r"(wastage|wasted|waste).*\b(today|so far|right now)\b"
        r"|\b(today|so far|right now)\b.*(wastage|wasted|waste)",
    ),
    (
        "wastage_range",
        r"(wastage|wasted|waste).*(last|past|this|week|month|day|trend|over)",
    ),
    (
        "unpaid_served_orders",
        r"(unpaid|unpaid\s+orders?|not\s+paid|pending\s+payment|payment"
        r"\s*pending).*(served|orders?)|served.*(unpaid|not\s+paid)"
        r"|how\s+many.*(unpaid|not\s+paid)",
    ),
    (
        "low_stock",
        r"low\s*(stock|inventory)"
        # "low in stock", "which items are running low"
        r"|\blow\b[^?]*\b(stock|inventory)\b"
        r"|(stock|inventory).*\blow\b"
        r"|running\s+low|below\s+minimum|need\s+reorder"
        r"|reorder|out\s+of\s+stock",
    ),
    (
        "inventory_summary",
        r"inventory|stock\s*(level|status|summary|on\s+hand)|how\s+much\s+stock",
    ),
    (
        "order_status_summary",
        r"(how\s+many|order)\s*(orders?\s*)?.*(preparing|ready|placed"
        r"|confirmed|served|status|lifecycle|pending)"
        r"|(preparing|ready|served|placed|confirmed).*(how\s+many|orders?|count)",
    ),
    (
        "customer_summary",
        r"customers?|guests?|repeat\s+customers?|top\s+spenders?"
        r"|who\s+spends",
    ),
    (
        "sales_today",
        r"(sold|sell|selling|sales|portions?|items?|dishes|quantity)"
        r".*\b(today|so far|right now)\b"
        r"|\b(today|so far|right now)\b.*(sold|sell|selling|portions?|quantity)",
    ),
    (
        "sales_range",
        r"(sold|sell|selling|sales|portions?|items?|quantity).*(last|past|this"
        r"|week|month|day|trend|over)",
    ),
]


def detect_intent(question: str) -> str | None:
    """
    Map a question onto one supported intent, or None.

    Returns None for anything unrecognised so the caller can refuse
    instead of guessing.
    """
    text = (question or "").strip().lower()

    if not text:
        return None

    # A greeting or a thank-you is a real question with no data behind
    # it; answer it as such rather than forcing it into an intent.
    if re.fullmatch(
        r"(hi|hello|hey|thanks|thank you|ok|okay|bye|good morning|good evening)[\s.!?]*",
        text,
    ):
        return "greeting"

    for intent, pattern in _RULES:
        if re.search(pattern, text):
            return intent

    return None


# =========================================================
# NUMBER FORMATTING
# =========================================================

def rupees(value: float | None) -> str:
    """
    Format a rupee amount with Indian digit grouping.

    Returns an explicit "no data" string for None so a missing figure is
    never rendered as 0.
    """
    if value is None:
        return "no recorded figure"

    amount = round(float(value), 2)

    # Indian grouping: the last three digits, then pairs.
    negative = amount < 0
    whole, _, fraction = f"{abs(amount):.2f}".partition(".")

    if len(whole) > 3:
        head = whole[:-3]
        tail = whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]

        if head:
            groups.insert(0, head)

        whole = ",".join(groups + [tail])

    rendered = f"{'-' if negative else ''}₹{whole}"

    if fraction.strip("0"):
        rendered += "." + fraction.rstrip("0")

    return rendered


def plural(count: int, singular: str, many: str | None = None) -> str:
    return f"{count} {singular if count == 1 else (many or singular + 's')}"


# =========================================================
# RESULT BUILDING
# =========================================================

def _chart(labels: list, values: list, title: str,
           value_label: str) -> dict:
    """A minimal chart payload for the frontend to render as-is."""
    return {
        "type": "bar",
        "title": title,
        "labels": labels,
        "values": values,
        "value_label": value_label,
    }


def _empty(intent: str, message: str, **extra) -> dict:
    """
    A result for a valid intent that has no matching rows.

    Says so plainly and returns no numbers, instead of reporting zeros
    that read like a real measurement.
    """
    return {
        "intent": intent,
        "answered": True,
        "answer": message,
        "chart": None,
        "table": None,
        "metrics": {},
        "has_data": False,
        **extra,
    }


def build_result(db: Session, intent: str, params: dict) -> dict:
    """
    Query the database and shape the answer.

    This is the only place numbers enter the assistant's output.
    """
    range_key = params.get("range")
    start = params.get("start")
    end = params.get("end")

    # ----------------------------------------------------------
    if intent == "revenue_today":
        today = date.today()

        window = analytics.revenue_for_window(db, today, today)

        if not window["orders"]:
            return _empty(
                intent,
                "No orders have been recorded today, so there is no "
                "revenue to report yet.",
                range="today",
            )

        return {
            "intent": intent,
            "answered": True,
            "answer": (
                f"Today's revenue is {rupees(window['revenue'])} from "
                f"{plural(window['orders'], 'order')}, averaging "
                f"{rupees(window['average_order_value'])} per order."
            ),
            "chart": None,
            "table": None,
            "metrics": window,
            "has_data": True,
            "range": "today",
        }

    # ----------------------------------------------------------
    if intent == "revenue_yesterday":
        yesterday = date.today() - timedelta(days=1)

        window = analytics.revenue_for_window(db, yesterday, yesterday)

        if not window["orders"]:
            return _empty(
                intent,
                "No orders were recorded yesterday.",
                range="yesterday",
            )

        return {
            "intent": intent,
            "answered": True,
            "answer": (
                f"Yesterday's revenue was {rupees(window['revenue'])} from "
                f"{plural(window['orders'], 'order')}."
            ),
            "chart": None,
            "table": None,
            "metrics": window,
            "has_data": True,
            "range": "yesterday",
        }

    # ----------------------------------------------------------
    if intent == "revenue_range":
        trend = analytics.revenue_trend(db, range_key or "last_7_days", start, end)

        if not trend["has_data"]:
            return _empty(
                intent,
                f"No orders were recorded between "
                f"{trend['start_date']} and {trend['end_date']}.",
                range=trend["range"],
            )

        best = trend["best_day"]

        sentence = (
            f"Revenue from {trend['start_date']} to {trend['end_date']} "
            f"totalled {rupees(trend['total_revenue'])} across "
            f"{plural(trend['total_orders'], 'order')}."
        )

        if best:
            sentence += (
                f" The best day was {best['date']} at "
                f"{rupees(best['revenue'])}."
            )

        return {
            "intent": intent,
            "answered": True,
            "answer": sentence,
            "chart": {
                "type": "line",
                "title": "Revenue by day",
                "labels": [point["date"] for point in trend["data"]],
                "values": [point["revenue"] for point in trend["data"]],
                "value_label": "Revenue (INR)",
            },
            "table": {
                "columns": ["Date", "Revenue", "Orders"],
                "rows": [
                    [point["date"], rupees(point["revenue"]), point["orders"]]
                    for point in trend["data"]
                ],
            },
            "metrics": {
                "range": trend["range"],
                "start_date": trend["start_date"],
                "end_date": trend["end_date"],
                "total_revenue": trend["total_revenue"],
                "total_orders": trend["total_orders"],
                "average_order_value": trend["average_order_value"],
                "best_day": best,
            },
            "has_data": True,
            "range": trend["range"],
        }

    # ----------------------------------------------------------
    if intent in ("sales_today", "sales_range"):
        key = "today" if intent == "sales_today" else (range_key or "last_7_days")

        sales = analytics.sales_summary(db, key, start, end)

        if not sales["has_data"]:
            return _empty(
                intent,
                f"No sales were recorded between {sales['start_date']} "
                f"and {sales['end_date']}.",
                range=sales["range"],
            )

        answer = (
            f"{plural(sales['portions_sold'], 'portion')} were sold between "
            f"{sales['start_date']} and {sales['end_date']} across "
            f"{plural(sales['orders'], 'order')}, totalling "
            f"{rupees(sales['revenue'])}."
        )

        return {
            "intent": intent,
            "answered": True,
            "answer": answer,
            "chart": None,
            "table": None,
            "metrics": sales,
            "has_data": True,
            "range": sales["range"],
        }

    # ----------------------------------------------------------
    if intent == "top_dishes":
        limit = params.get("limit") or 5

        top = analytics.top_dishes(db, limit=limit, range_key=range_key or "all_time",
                                   start=start, end=end)

        if not top["has_data"]:
            return _empty(
                intent,
                f"No dishes have been sold between {top['start_date']} "
                f"and {top['end_date']}.",
                range=top["range"],
            )

        leader = top["top_dishes"][0]

        return {
            "intent": intent,
            "answered": True,
            "answer": (
                f"'{leader['dish']}' is the top seller with "
                f"{plural(leader['quantity_sold'], 'portion')} sold "
                f"({rupees(leader['revenue'])})"
                + (
                    f". It is in the {leader['category']} category."
                    if leader["category"]
                    else "."
                )
            ),
            "chart": _chart(
                [dish["dish"] for dish in top["top_dishes"]],
                [dish["quantity_sold"] for dish in top["top_dishes"]],
                "Top selling dishes",
                "Portions sold",
            ),
            "table": {
                "columns": ["Dish", "Category", "Portions", "Revenue"],
                "rows": [
                    [
                        dish["dish"],
                        dish["category"] or "-",
                        dish["quantity_sold"],
                        rupees(dish["revenue"]),
                    ]
                    for dish in top["top_dishes"]
                ],
            },
            "metrics": top,
            "has_data": True,
            "range": top["range"],
        }

    # ----------------------------------------------------------
    if intent == "wastage_today":
        waste = analytics.wastage_summary(db, "today")

        if not waste["has_data"]:
            return _empty(
                intent,
                "No food waste has been recorded today.",
                range="today",
            )

        return {
            "intent": intent,
            "answered": True,
            "answer": (
                f"{rupees(waste['total_cost'])} of food waste was recorded "
                f"today across {plural(len(waste['items']), 'item')} "
                f"({waste['total_quantity']} units)."
            ),
            "chart": None,
            "table": {
                "columns": ["Item", "Quantity", "Cost"],
                "rows": [
                    [item["item_name"], item["quantity"], rupees(item["cost"])]
                    for item in waste["items"]
                ],
            },
            "metrics": waste,
            "has_data": True,
            "range": "today",
        }

    # ----------------------------------------------------------
    if intent == "wastage_range":
        waste = analytics.wastage_summary(
            db, range_key or "last_7_days", start, end
        )

        if not waste["has_data"]:
            return _empty(
                intent,
                f"No food waste was recorded between {waste['start_date']} "
                f"and {waste['end_date']}.",
                range=waste["range"],
            )

        return {
            "intent": intent,
            "answered": True,
            "answer": (
                f"Food waste between {waste['start_date']} and "
                f"{waste['end_date']} cost {rupees(waste['total_cost'])} "
                f"({waste['total_quantity']} units)."
            ),
            "chart": {
                "type": "line",
                "title": "Wastage cost by day",
                "labels": [point["date"] for point in waste["trend"]],
                "values": [point["cost"] for point in waste["trend"]],
                "value_label": "Wastage cost (INR)",
            },
            "table": None,
            "metrics": waste,
            "has_data": True,
            "range": waste["range"],
        }

    # ----------------------------------------------------------
    if intent == "highest_wastage":
        worst = analytics.highest_wastage(
            db, range_key or "all_time", start, end
        )

        if not worst["has_data"]:
            return _empty(
                intent,
                f"No food waste was recorded between {worst['start_date']} "
                f"and {worst['end_date']}.",
                range=worst["range"],
            )

        item = worst["item"]

        return {
            "intent": intent,
            "answered": True,
            "answer": (
                f"'{item['item_name']}' has the highest recorded wastage: "
                f"{rupees(item['cost'])} across {item['quantity']} units "
                f"over {plural(item['entries'], 'entry', 'entries')}."
            ),
            "chart": None,
            "table": None,
            "metrics": worst,
            "has_data": True,
            "range": worst["range"],
        }

    # ----------------------------------------------------------
    if intent == "low_stock":
        stock = analytics.inventory_summary(db)

        if not stock["has_data"]:
            return _empty(
                intent,
                "No inventory items have been recorded yet.",
            )

        low = stock["low_stock_items"]
        out = stock["out_of_stock_items"]

        if not low and not out:
            return {
                "intent": intent,
                "answered": True,
                "answer": (
                    f"No inventory items are at or below their minimum "
                    f"stock. All {stock['total_items']} tracked "
                    f"{'item is' if stock['total_items'] == 1 else 'items are'} "
                    f"above threshold."
                ),
                "chart": _chart(
                    ["Available", "Low stock", "Out of stock"],
                    [
                        stock["available_count"],
                        stock["low_stock_count"],
                        stock["out_of_stock_count"],
                    ],
                    "Inventory status",
                    "Items",
                ),
                "table": None,
                "metrics": stock,
                "has_data": True,
            }

        parts = []

        if low:
            parts.append(
                f"{plural(len(low), 'item')} at or below minimum stock: "
                + ", ".join(
                    f"{item['item_name']} ({item['quantity']}{'' if not item['unit'] else ' ' + item['unit']},"
                    f" needs {item['shortfall']} more)"
                    for item in low[:5]
                )
            )

        if out:
            parts.append(
                f"{plural(len(out), 'item')} out of stock: "
                + ", ".join(item["item_name"] for item in out[:5])
            )

        return {
            "intent": intent,
            "answered": True,
            "answer": ". ".join(parts) + ".",
            "chart": _chart(
                ["Available", "Low stock", "Out of stock"],
                [
                    stock["available_count"],
                    stock["low_stock_count"],
                    stock["out_of_stock_count"],
                ],
                "Inventory status",
                "Items",
            ),
            "table": {
                "columns": ["Item", "Quantity", "Minimum", "Shortfall"],
                "rows": [
                    [
                        item["item_name"],
                        item["quantity"],
                        item["minimum_stock"],
                        item["shortfall"],
                    ]
                    for item in low + out
                ],
            },
            "metrics": stock,
            "has_data": True,
        }

    # ----------------------------------------------------------
    if intent == "inventory_summary":
        stock = analytics.inventory_summary(db)

        if not stock["has_data"]:
            return _empty(intent, "No inventory items have been recorded yet.")

        return {
            "intent": intent,
            "answered": True,
            "answer": (
                f"{plural(stock['total_items'], 'inventory item')} tracked: "
                f"{stock['available_count']} available, "
                f"{stock['low_stock_count']} low, "
                f"{stock['out_of_stock_count']} out of stock. "
                f"Stock on hand is valued at "
                f"{rupees(stock['total_stock_value'])}."
            ),
            "chart": _chart(
                ["Available", "Low stock", "Out of stock"],
                [
                    stock["available_count"],
                    stock["low_stock_count"],
                    stock["out_of_stock_count"],
                ],
                "Inventory status",
                "Items",
            ),
            "table": None,
            "metrics": stock,
            "has_data": True,
        }

    # ----------------------------------------------------------
    if intent == "order_status_summary":
        lifecycle = analytics.order_status_summary(db)

        if not lifecycle["has_data"]:
            return _empty(
                intent,
                "No orders have been placed through checkout yet, so there "
                "is no order lifecycle to report.",
            )

        parts = [
            f"{lifecycle['lifecycle'].get(status, 0)} {status.lower()}"
            for status in analytics.LIFECYCLE_STATUSES
        ]

        return {
            "intent": intent,
            "answered": True,
            "answer": (
                "Current order status: " + ", ".join(parts) + "."
            ),
            "chart": _chart(
                list(analytics.LIFECYCLE_STATUSES),
                [
                    lifecycle["lifecycle"].get(status, 0)
                    for status in analytics.LIFECYCLE_STATUSES
                ],
                "Order lifecycle",
                "Orders",
            ),
            "table": None,
            "metrics": lifecycle,
            "has_data": True,
        }

    # ----------------------------------------------------------
    if intent == "unpaid_served_orders":
        lifecycle = analytics.order_status_summary(db)

        served = lifecycle["lifecycle"].get("Served", 0)
        unpaid_served = lifecycle["served_unpaid_orders"]

        return {
            "intent": intent,
            "answered": True,
            "answer": (
                f"{plural(unpaid_served, 'served order')} "
                f"{'is' if unpaid_served == 1 else 'are'} still unpaid. "
                f"Food status and payment are tracked separately, so a "
                f"served order is not assumed to be paid - there are "
                f"{served} served order(s) in total and "
                f"{lifecycle['payment'].get('paid', 0)} paid."
            ),
            "chart": _chart(
                list(lifecycle["payment"].keys()) or ["unpaid"],
                list(lifecycle["payment"].values()) or [0],
                "Payment status",
                "Orders",
            ),
            "table": None,
            "metrics": lifecycle,
            "has_data": True,
        }

    # ----------------------------------------------------------
    if intent == "customer_summary":
        customers = analytics.customer_summary(db)

        if not customers["has_data"]:
            return _empty(intent, "No customer records have been created yet.")

        top = customers["top_spenders"][0] if customers["top_spenders"] else None

        answer = (
            f"{plural(customers['total_customers'], 'customer record')} and "
            f"{plural(customers['total_users'], 'user account')} exist. "
            f"{plural(customers['distinct_order_names'], 'name')} appear on "
            f"order history and {plural(customers['repeat_customers'], 'name')} "
            f"have ordered more than once."
        )

        if top:
            answer += (
                f" '{top['customer_name']}' has spent the most at "
                f"{rupees(top['total_spent'])} across "
                f"{plural(top['orders'], 'order')}."
            )

        return {
            "intent": intent,
            "answered": True,
            "answer": answer,
            "chart": None,
            "table": {
                "columns": ["Customer", "Orders", "Total spent"],
                "rows": [
                    [row["customer_name"], row["orders"], rupees(row["total_spent"])]
                    for row in customers["top_spenders"]
                ],
            },
            "metrics": customers,
            "has_data": True,
        }

    # ----------------------------------------------------------
    if intent == "average_order_value":
        start_date, end_date, label = analytics.resolve_range(
            range_key or "last_7_days", start, end
        )

        window = analytics.revenue_for_window(db, start_date, end_date)

        if not window["orders"]:
            return _empty(
                intent,
                f"No orders were recorded between {window['start_date']} "
                f"and {window['end_date']}.",
                range=label,
            )

        return {
            "intent": intent,
            "answered": True,
            "answer": (
                f"The average order value was "
                f"{rupees(window['average_order_value'])} across "
                f"{plural(window['orders'], 'order')} totalling "
                f"{rupees(window['revenue'])}."
            ),
            "chart": None,
            "table": None,
            "metrics": {**window, "range": label},
            "has_data": True,
            "range": label,
        }

    # Anything not handled above is refused rather than guessed at.
    return {
        "intent": intent,
        "answered": False,
        "answer": REFUSAL,
        "chart": None,
        "table": None,
        "metrics": {},
        "has_data": False,
    }


# =========================================================
# ENTRY POINT
# =========================================================

GREETING = (
    "Ask me about revenue, sales, top dishes, food waste, inventory "
    "stock or order status. For example: \"what is today's revenue?\" "
    "or \"show me sales for the last 7 days\"."
)


def answer_question(db: Session, question: str) -> dict:
    """
    The whole pipeline: detect, extract, query, phrase.

    An unsupported question produces a refusal carrying no metrics and no
    chart, so nothing downstream can render a number it did not earn.
    """
    intent = detect_intent(question)

    if intent == "greeting":
        return {
            "intent": "greeting",
            "answered": True,
            "answer": GREETING,
            "chart": None,
            "table": None,
            "metrics": {},
            "has_data": False,
        }

    if intent is None:
        return {
            "intent": None,
            "answered": False,
            "answer": REFUSAL,
            "chart": None,
            "table": None,
            "metrics": {},
            "has_data": False,
            "suggestions": SUGGESTED_QUESTIONS,
        }

    params = extract_params(question)

    # extract_params widens a "today/yesterday trend" question to a week,
    # because a single day is not a trend. The single-day intent would
    # ignore that, so it is re-dispatched to the series handler.
    effective = params.get("range")

    if intent in ("revenue_today", "revenue_yesterday", "sales_today"):
        if effective not in ("today", "yesterday", None):
            intent = "revenue_range" if intent.startswith("revenue") else "sales_range"
            result = build_result(db, intent, params)
            result["intent"] = intent
            result["note"] = (
                "The question mentioned a trend, so a multi-day series "
                "was returned instead of a single day."
            )
            result["question"] = question
            result["params"] = _param_summary(params, result)
            result["supported_intents"] = SUPPORTED_INTENTS
            return result

    result = build_result(db, intent, params)

    result["question"] = question
    result["params"] = _param_summary(params, result)
    result["supported_intents"] = SUPPORTED_INTENTS

    return result


def _param_summary(params: dict, result: dict) -> dict:
    return {
        "range": result.get("range"),
        "limit": params.get("limit"),
        "start": params["start"].isoformat() if params.get("start") else None,
        "end": params["end"].isoformat() if params.get("end") else None,
    }


SUGGESTED_QUESTIONS = [
    "What is today's revenue?",
    "How much did we sell today?",
    "Show me sales for the last 7 days",
    "What was our revenue yesterday?",
    "Which dishes sold the most today?",
    "What are the top 5 dishes this week?",
    "How much food was wasted today?",
    "Which ingredient has the highest wastage?",
    "Which items are low in stock?",
    "How many orders are currently preparing?",
    "How many orders are ready?",
    "How many served orders are unpaid?",
]

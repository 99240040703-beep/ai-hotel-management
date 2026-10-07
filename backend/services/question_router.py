"""
Question understanding for the restaurant-wide assistant.

--------------------------------------------------------------------------
WHAT THIS DOES AND DELIBERATELY DOES NOT DO
--------------------------------------------------------------------------
It resolves *what period* a question is about and *which parts of the
restaurant* it touches. It does not choose an answer, does not write
prose, and does not have a fixed list of acceptable questions.

The Phase 5 assistant mapped a question onto one of fifteen closed
intents and refused anything else. That is the wrong shape for an
operations assistant: "why did sales decrease" and "which areas need
attention" are both legitimate questions that span five data sources, and
neither is in any list of intents.

So this module does two things and nothing else:

    1. reads a time window out of the text (or inherits one from the
       conversation);
    2. scores the text against per-domain vocabularies and returns a
       ranked list of domains.

A question that matches nothing is not refused. It gets the summary
tool, because "the admin asked something I do not have a topic for" and
"the restaurant has no data for that" are different situations and only
the second one is a limitation.

--------------------------------------------------------------------------
FOLLOW-UP QUESTIONS
--------------------------------------------------------------------------
Context carries the last resolved window and the domains behind it. "What
about the previous week?" and "Why was it lower?" then mean something,
because the period and the subject were both remembered. Context holds
resolved ranges and domain names only - never the question text itself.

--------------------------------------------------------------------------
MATCHING, NOT PARSING
--------------------------------------------------------------------------
Vocabulary scoring, with longer and rarer phrases worth more than a
common word. This is deliberately shallow: it decides *what to look at*,
not *what the answer is*. Every figure still comes from a database query.
"""

import re
from datetime import date, timedelta


# =========================================================
# TIME WINDOWS
#
# Ordered most-specific first. The first match wins, so "previous week"
# is tested before "last week", and an explicit ISO date pair is tested
# before any relative phrase.
# =========================================================

_ISO_RANGE = re.compile(
    r"(\d{4}-\d{2}-\d{2})\s*(?:to|until|through|-)\s*(\d{4}-\d{2}-\d{2})"
)

# (pattern, resolver name). Kept as data so adding a phrase is a one-line
# change rather than an edit to a branching function.
_WINDOW_PATTERNS = [
    (r"\bthis\s+week\b", "this_week"),
    (r"\blast\s+week\b", "last_7_days"),
    (r"\bthis\s+month\b", "this_month"),
    (r"\blast\s+30\s+days?\b", "last_30_days"),
    (r"\bpast\s+30\s+days?\b", "last_30_days"),
    (r"\bthis\s+quarter\b", "this_quarter"),
    (r"\blast\s+quarter\b", "last_quarter"),
    (r"\blast\s+7\s+days?\b", "last_7_days"),
    (r"\bpast\s+7\s+days?\b", "last_7_days"),
    (r"\blast\s+24\s+hours?\b", "last_7_days"),
    (r"\blast\s+14\s+days?\b", "last_14_days"),
    (r"\bpast\s+14\s+days?\b", "last_14_days"),
    (r"\blast\s+(couple\s+of\s+)?days?\b", "last_3_days"),
    (r"\blast\s+night\b", "yesterday"),
    (r"\btoday\b|\bso\s+far\b|\bright\s+now\b|\bcurrently\b|\bat\s+the\s+moment\b",
     "today"),
    (r"\byesterday\b|\blast\s+night\b", "yesterday"),
    # "the previous week" and "the week before" both mean the window
    # before last week's, because "last week" is the current one.
    (r"\bprevious\s+week\b|\bweek\s+before\b|\bprior\s+week\b",
     "previous_week"),
    (r"\bprevious\s+month\b|\bmonth\s+before\b|\bprior\s+month\b",
     "previous_month"),
    (r"\byesterday\b", "yesterday"),
    (r"\blast\s+(90|three\s+month|3\s+month)\b", "last_90_days"),
    (r"\ball[\s-]?time\b|\beverything\b|\boverall\b|\bin\s+total\b",
     "all_time"),
    (r"\brecent(?:ly)?\b|\blately\b|\bnowadays\b", "last_7_days"),
    (r"\bthis\s+year\b|\bytd\b|\byear[\s-]to[\s-]date\b", "this_year"),
    # Tested last on purpose. "The previous period" means whatever comes
    # before the window the rest of the sentence already named, so every
    # phrase that names a window directly has to be tried first -
    # otherwise "compare our recent performance with the previous period"
    # resolves the *current* window to the prior one and compares the
    # wrong two periods.
    (r"\bprevious\s+period\b|\bprior\s+period\b", "previous_period"),
]


def _window_for(key: str, context: dict | None = None) -> tuple:
    """Resolve a window key to concrete inclusive dates and a label."""
    today = date.today()

    if key == "today":
        return today, today, "today"

    if key == "yesterday":
        day = today - timedelta(days=1)

        return day, day, "yesterday"

    if key == "last_3_days":
        return today - timedelta(days=2), today, "last_3_days"

    if key == "last_7_days":
        return today - timedelta(days=6), today, "last_7_days"

    if key == "last_14_days":
        return today - timedelta(days=13), today, "last_14_days"

    if key == "last_30_days":
        return today - timedelta(days=29), today, "last_30_days"

    if key == "last_90_days":
        return today - timedelta(days=89), today, "last_90_days"

    if key == "this_week":
        return today - timedelta(days=today.weekday()), today, "this_week"

    if key == "this_month":
        return today.replace(day=1), today, "this_month"

    if key == "this_quarter":
        month = ((today.month - 1) // 3) * 3 + 1

        return today.replace(month=month, day=1), today, "this_quarter"

    if key == "last_quarter":
        month = ((today.month - 1) // 3) * 3 + 1

        end = today.replace(month=month, day=1) - timedelta(days=1)

        start = end.replace(
            month=((end.month - 1) // 3) * 3 + 1, day=1
        )

        return start, end, "last_quarter"

    if key == "this_year":
        return today.replace(month=1, day=1), today, "this_year"

    if key == "all_time":
        return date(1970, 1, 1), today, "all_time"

    # ---- windows defined relative to a previous window ----

    if key == "previous_week":
        this_week_start = today - timedelta(days=today.weekday())

        end = this_week_start - timedelta(days=1)

        return end - timedelta(days=6), end, "previous_week"

    if key == "previous_month":
        this_month_start = today.replace(day=1)

        end = this_month_start - timedelta(days=1)

        return end.replace(day=1), end, "previous_month"

    if key == "previous_period":
        # Handled against the conversation's last window, which is what
        # makes "and the previous period?" mean something. The stored
        # window is serialised as ISO strings, so those keys are read
        # rather than date objects that are not there.
        inherited = _inherited_window(context)

        if inherited:
            previous_start, previous_end = inherited[0], inherited[1]

            span = (previous_end - previous_start).days + 1

            return (
                previous_start - timedelta(days=span),
                previous_start - timedelta(days=1),
                "previous_period",
            )

        # Nothing to sit behind, so read it as the recent window and let
        # the comparison tool derive the prior period from it.
        return _window_for("last_7_days")

    return None, None, None


def _inherited_window(context: dict | None):
    """
    The conversation's last window as real dates, or None.

    The single place a serialised window becomes dates again. Called from
    the window resolver, which is why it is not a method.
    """
    if not context:
        return None

    window = context.get("window") or {}

    raw_start = window.get("start_date") or window.get("start")
    raw_end = window.get("end_date") or window.get("end")

    if not raw_start or not raw_end:
        return None

    if isinstance(raw_start, date) and isinstance(raw_end, date):
        return raw_start, raw_end, window.get("label")

    try:
        return (
            date.fromisoformat(str(raw_start)[:10]),
            date.fromisoformat(str(raw_end)[:10]),
            window.get("label"),
        )
    except ValueError:
        return None


def resolve_window(question: str, context: dict | None = None) -> dict:
    """
    Work out which dates the question is about.

    Precedence: an explicit ISO pair, then an explicit relative phrase,
    then the conversation's inherited window, then a sensible default.

    The default is last_7_days rather than today because "how is the
    restaurant doing" with no period named is nearly always a request for
    the recent picture, not for one partial day.
    """
    text = (question or "").lower()
    context = context or {}

    explicit = _ISO_RANGE.search(text)

    if explicit:
        try:
            start = date.fromisoformat(explicit.group(1))
            end = date.fromisoformat(explicit.group(2))

            return {
                "start": start,
                "end": end,
                "label": "custom",
                "source": "explicit_dates",
                "inherited": False,
            }
        except ValueError:
            pass

    for pattern, key in _WINDOW_PATTERNS:
        if not re.search(pattern, text):
            continue

        start, end, label = _window_for(key, context)

        if start is None:
            # "previous period" means the window before whatever the last
            # turn resolved, which is what makes a follow-up work.
            inherited = context.get("window") or {}

            if inherited.get("start") and inherited.get("end"):
                span = (inherited["end"] - inherited["start"]).days + 1

                return {
                    "start": inherited["start"] - timedelta(days=span),
                    "end": inherited["start"] - timedelta(days=1),
                    "label": "previous_period",
                    "source": "relative_to_context",
                    "inherited": False,
                }

            continue

        return {
            "start": start,
            "end": end,
            "label": label,
            "source": "question",
            "inherited": False,
        }

    # No period named. Reuse the conversation's, which is how "and
    # reservations?" keeps meaning the same week as the revenue question.
    inherited = _inherited_window(context)

    if inherited:
        return {
            "start": inherited[0],
            "end": inherited[1],
            "label": inherited[2] or "inherited",
            "source": "conversation",
            "inherited": True,
        }

    start, end, label = _window_for("last_7_days", context)

    return {
        "start": start,
        "end": end,
        "label": label,
        "source": "default",
        "inherited": False,
    }


# =========================================================
# DOMAIN VOCABULARIES
#
# Each entry is a domain and the words that point at it. Multi-word
# phrases are matched before single words and score higher, which is how
# "low stock" reaches inventory rather than being read as two unrelated
# nouns.
# =========================================================

PHRASES = [
    # (domain, phrase, weight)
    ("revenue", "revenue", 2.0),
    ("revenue", "sales", 2.0),
    ("revenue", "earnings", 2.0),
    ("revenue", "turnover", 2.0),
    ("revenue", "money", 1.5),
    ("revenue", "takings", 2.0),
    ("revenue", "income", 1.5),
    ("revenue", "how much did we make", 3.0),
    ("revenue", "how are we doing", 3.0),
    ("revenue", "performance", 2.0),
    ("revenue", "business", 1.0),
    ("revenue", "trading", 1.5),
    ("revenue", "growth", 2.0),
    ("revenue", "average order value", 3.0),
    ("revenue", "aov", 2.0),
    ("revenue", "bill value", 1.5),
    # "Ticket" is a kitchen word and a money word. The money reading is
    # the more common one and is worth more, so it wins the score.
    ("revenue", "average ticket", 3.5),
    ("revenue", "average bill", 3.5),

    ("orders", "order", 1.5),
    ("orders", "orders", 1.5),
    ("orders", "order status", 2.5),
    ("orders", "cancelled", 2.0),
    ("orders", "cancellation", 2.0),
    ("orders", "completed order", 2.5),
    ("orders", "dine-in", 2.0),
    ("orders", "dine in", 2.0),
    ("orders", "takeaway", 2.0),
    ("orders", "walk-in", 2.0),
    ("orders", "how many orders", 3.0),
    ("orders", "busiest", 1.5),
    ("orders", "quietest", 1.5),

    ("bills", "bill", 2.0),
    ("bills", "gst", 2.5),
    ("bills", "tax", 2.0),
    ("bills", "service charge", 3.0),
    ("bills", "discount", 2.0),
    ("bills", "subtotal", 2.5),
    ("bills", "outstanding", 2.0),
    ("bills", "unpaid", 2.0),
    ("bills", "receipt", 1.5),

    ("payments", "payment", 2.5),
    ("payments", "paid", 2.0),
    ("payments", "payment status", 3.0),
    ("payments", "collection", 2.0),
    ("payments", "collected", 2.0),
    ("payments", "collect", 2.0),
    ("payments", "refund", 2.0),
    ("payments", "gateway", 2.0),
    ("payments", "settled", 1.5),
    # Phase 6E. Bills and money are the same subject once a payment
    # exists, so these route to the payment tool rather than the bill
    # breakdown: "how much money is outstanding" is a settlement question,
    # not a tax question.
    ("payments", "outstanding", 3.0),
    ("payments", "billed", 2.5),
    ("payments", "payment attempt", 3.5),
    ("payments", "attempts", 2.5),
    ("payments", "failed payment", 3.5),
    ("payments", "payment summary", 3.5),
    ("payments", "how much money", 3.0),
    ("payments", "money", 1.5),
    ("payments", "unpaid bill", 3.5),
    ("payments", "paid bill", 3.5),
    ("payments", "settle", 2.5),

    ("customers", "customer", 2.0),
    ("customers", "customers", 2.0),
    ("customers", "guest", 2.0),
    ("customers", "guests", 2.0),
    ("customers", "repeat", 2.5),
    ("customers", "returning", 2.5),
    ("customers", "new customer", 3.0),
    ("customers", "loyal", 2.5),
    ("customers", "spender", 2.0),
    ("customers", "spending", 1.5),
    ("customers", "retention", 2.5),
    ("customers", "preference", 2.0),
    ("customers", "frequency", 2.0),

    ("menu", "menu", 2.0),
    ("menu", "dish", 2.0),
    ("menu", "dishes", 2.0),
    ("menu", "item", 1.5),
    ("menu", "items", 1.5),
    ("menu", "food", 1.5),
    ("menu", "price", 2.0),
    ("menu", "pricing", 2.0),
    ("menu", "category", 2.0),
    ("menu", "popular", 2.0),
    ("menu", "popularity", 2.5),
    ("menu", "best seller", 3.0),
    ("menu", "best-selling", 3.0),
    ("menu", "availability", 2.5),
    ("menu", "available", 2.0),
    ("menu", "vegan", 1.5),
    ("menu", "vegetarian", 1.5),
    ("menu", "spicy", 1.5),
    ("menu", "less popular", 3.0),
    ("menu", "losing popularity", 3.0),

    ("reservations", "reservation", 2.5),
    ("reservations", "reservations", 2.5),
    ("reservations", "booking", 2.5),
    ("reservations", "bookings", 2.5),
    ("reservations", "booked", 2.0),
    ("reservations", "table booking", 3.0),
    ("reservations", "no-show", 3.0),
    ("reservations", "noshow", 3.0),
    ("reservations", "party size", 3.0),
    ("reservations", "guests booked", 3.0),

    ("tables", "table", 1.5),
    ("tables", "tables", 1.5),
    ("tables", "seating", 2.5),
    ("tables", "seated", 2.0),
    ("tables", "occupancy", 3.0),
    ("tables", "capacity", 2.5),
    ("tables", "qr", 2.0),
    ("tables", "floor", 1.5),
    ("tables", "section", 1.5),

    ("kitchen", "kitchen", 2.5),
    ("kitchen", "chef", 2.0),
    ("kitchen", "preparation", 2.5),
    ("kitchen", "prep", 2.0),
    ("kitchen", "preparing", 2.0),
    ("kitchen", "ready", 1.5),
    ("kitchen", "ticket", 2.5),
    ("kitchen", "tickets", 2.5),
    ("kitchen", "delay", 2.5),
    ("kitchen", "delayed", 2.5),
    ("kitchen", "slow", 1.5),
    ("kitchen", "wait time", 3.0),
    ("kitchen", "backlog", 2.5),
    ("kitchen", "workload", 2.5),
    ("kitchen", "served", 2.5),
    ("kitchen", "serve", 2.0),
    ("kitchen", "serving", 2.5),
    ("kitchen", "how long", 2.5),
    ("kitchen", "keeping up", 3.0),
    ("kitchen", "turnaround", 3.0),
    # A duration on its own is weak evidence, but paired with "serve" or
    # "ready" it is the clearest signal a question is about throughput.
    ("kitchen", "minutes", 1.2),
    ("kitchen", "minute", 1.2),
    ("kitchen", "took", 1.2),

    ("delivery", "delivery", 2.5),
    ("delivery", "deliver", 2.5),
    ("delivery", "delivered", 2.5),
    ("delivery", "out for delivery", 3.5),
    ("delivery", "takeout", 1.5),
    ("delivery", "driver", 2.5),
    ("delivery", "dispatch", 2.5),
    ("delivery", "shipping", 2.0),

    ("inventory", "stock", 2.5),
    ("inventory", "inventory", 2.5),
    ("inventory", "ingredient", 2.0),
    ("inventory", "ingredients", 2.0),
    ("inventory", "supplier", 2.5),
    ("inventory", "suppliers", 2.5),
    ("inventory", "restock", 3.0),
    ("inventory", "reorder", 3.0),
    ("inventory", "run out", 2.5),
    ("inventory", "running low", 3.5),
    ("inventory", "out of stock", 3.5),
    ("inventory", "low stock", 3.5),

    ("waste", "waste", 2.5),
    ("waste", "wastage", 2.5),
    ("waste", "wasted", 2.5),
    ("waste", "discard", 2.0),
    ("waste", "discarded", 2.0),
    ("waste", "spoil", 2.0),
    ("waste", "spoilage", 2.5),
    ("waste", "leftover", 2.0),

    ("reviews", "review", 2.5),
    ("reviews", "reviews", 2.5),
    ("reviews", "rating", 2.5),
    ("reviews", "ratings", 2.5),
    ("reviews", "feedback", 2.5),
    ("reviews", "sentiment", 2.5),
    ("reviews", "unhappy", 2.5),
    ("reviews", "complaint", 2.5),
    ("reviews", "complaints", 2.5),
    ("reviews", "satisfied", 2.0),
    ("reviews", "happy", 1.5),
    ("reviews", "negative", 2.0),

    ("staff", "staff", 2.5),
    ("staff", "employee", 2.5),
    ("staff", "employees", 2.5),
    ("staff", "team", 1.5),
    ("staff", "shift", 2.5),
    ("staff", "roster", 2.5),
    ("staff", "waiter", 2.5),

    ("forecast", "forecast", 3.0),
    ("forecast", "predict", 3.0),
    ("forecast", "prediction", 3.0),
    ("forecast", "expect", 2.5),
    ("forecast", "expected", 2.0),
    ("forecast", "next week", 3.0),
    ("forecast", "tomorrow", 2.5),
    ("forecast", "upcoming", 2.0),
    ("forecast", "future", 1.5),
    ("forecast", "prepare more", 3.5),
    ("forecast", "demand", 2.5),

    ("comparison", "compare", 3.0),
    ("comparison", "comparison", 3.0),
    ("comparison", "versus", 3.0),
    ("comparison", " vs ", 3.0),
    ("comparison", "than before", 3.0),
    ("comparison", "compared", 3.0),
    ("comparison", "decrease", 2.5),
    ("comparison", "decline", 2.5),
    ("comparison", "drop", 2.0),
    ("comparison", "dropped", 2.0),
    ("comparison", "lower", 2.0),
    ("comparison", "higher", 2.0),
    ("comparison", "increase", 2.5),
    ("comparison", "grew", 2.0),
    ("comparison", "improved", 2.5),
    ("comparison", "worse", 2.0),
    ("comparison", "trend", 2.5),
    ("comparison", "trending", 2.5),
    ("comparison", "change", 1.5),
    ("comparison", "movement", 1.5),

    ("summary", "summary", 3.0),
    ("summary", "summarise", 3.0),
    ("summary", "summarize", 3.0),
    ("summary", "overview", 3.0),
    ("summary", "brief", 2.0),
    ("summary", "recap", 3.0),
    ("summary", "happening", 2.5),
    ("summary", "attention", 3.0),
    ("summary", "problems", 3.0),
    ("summary", "problem", 3.0),
    ("summary", "issues", 3.0),
    ("summary", "issue", 3.0),
    ("summary", "worried", 2.5),
    ("summary", "should i worry", 3.5),
    ("summary", "need attention", 3.5),
]

# Words that imply the admin is asking *why*, which is the one request
# that cannot be answered from a single domain.
_CAUSAL_MARKERS = (
    "why",
    "reason",
    "because",
    "cause",
    "caused",
    "explain",
    "what happened",
    "what is wrong",
    "went wrong",
)


def score_domains(question: str) -> list:
    """
    Rank restaurant domains against the question text.

    Returns [(domain, score)] sorted by score, highest first. A domain is
    only returned once it has actually matched something, so an
    unrelated question cannot drag in a data source nobody asked about.
    """
    text = f" {re.sub(r'[^a-z0-9% ]', ' ', (question or '').lower())} "

    scores = {}

    # Longer phrases first so "out of stock" is scored as one phrase
    # rather than as "out" plus "stock" arriving in any order.
    for domain, phrase, weight in sorted(
        PHRASES, key=lambda row: -len(row[1])
    ):
        if phrase in text:
            scores[domain] = scores.get(domain, 0.0) + weight

    ranked = sorted(
        scores.items(), key=lambda row: (-row[1], row[0])
    )

    return ranked


def select_domains(question: str, context: dict | None = None,
                   limit: int = 4) -> list:
    """
    Choose which domains this question needs.

    Three cases, in order:

    1. The question asks *why* something happened. A causal question is
       never answerable from one domain, so the surrounding comparison and
       the people/quality signals are added deliberately - and the answer
       will still only claim what the data supports.

    2. The question matches some domains. Take the strongest few.

    3. Nothing matched. Fall back to the summary rather than refusing,
       because an unrecognised subject is not a missing measurement.
    """
    ranked = score_domains(question)
    context = context or {}

    # ---- case 1: a causal question ----

    if any(marker in (question or "").lower() for marker in _CAUSAL_MARKERS):
        chosen = ["revenue", "orders", "comparison"]

        # Support the likely explanation with the data that could support
        # one, while leaving the conclusion to the evidence.
        for supportive in ("reviews", "reservations", "menu", "kitchen"):
            if supportive in dict(ranked):
                chosen.append(supportive)

        for domain, _score in ranked[:4]:
            if domain not in chosen:
                chosen.append(domain)

        return chosen[:limit + 2]

    # ---- case 2: matched something ----

    if ranked:
        domains = [domain for domain, _score in ranked[:limit]]

        # A comparison word with no other signal still means "against
        # something", so the comparison tool must be available.
        if "comparison" in dict(ranked) and "comparison" not in domains:
            domains.append("comparison")

        return domains

    # ---- case 3: a follow-up with nothing new in it ----

    previous = context.get("domains") or []

    if previous:
        return list(previous[:limit])

    return ["summary"]


def is_causal(question: str) -> bool:
    """Whether the admin is asking for a cause rather than a number."""
    text = (question or "").lower()

    return any(marker in text for marker in _CAUSAL_MARKERS)


# =========================================================
# DOMAIN -> TOOL PLAN
#
# Domains say what the question is about; tools say what will be read.
# A domain can need more than one tool (revenue needs both the revenue
# tool and the order breakdown), and one tool can serve several domains.
# =========================================================

DOMAIN_TOOLS = {
    "revenue": ["get_revenue_metrics"],
    "orders": ["get_order_metrics"],
    "bills": ["get_bill_metrics"],
    "payments": ["get_payment_metrics"],
    "customers": ["get_customer_metrics"],
    "menu": ["get_menu_performance"],
    "reservations": ["get_reservation_metrics"],
    "tables": ["get_table_metrics"],
    "kitchen": ["get_kitchen_metrics"],
    "delivery": ["get_delivery_metrics"],
    "inventory": ["get_inventory_metrics"],
    "waste": ["get_waste_metrics"],
    "reviews": ["get_review_metrics"],
    "staff": ["get_staff_metrics"],
    "forecast": ["get_forecast"],
    "comparison": ["get_historical_comparison"],
    "summary": ["get_business_summary"],
    "operations": ["get_operational_events"],
    "ai": ["get_existing_ai_insights"],
}

# A causal or summary question is never answered by one tool, so these
# are added whenever the question is broad. Deliberately a short list:
# each extra tool is another aggregation the database has to compute.
BROADENING_TOOLS = {
    "causal": ["get_review_metrics", "get_kitchen_metrics"],
    "broad": ["get_inventory_metrics", "get_reservation_metrics"],
}


def plan_tools(question: str, context: dict | None = None) -> dict:
    """
    The full plan for one question: window, domains and tools.

    Returns a dict the orchestrator executes without further interpretation.
    """
    window = resolve_window(question, context)

    domains = select_domains(question, context)

    tools = []

    for domain in domains:
        for tool in DOMAIN_TOOLS.get(domain, []):
            if tool not in tools:
                tools.append(tool)

    causal = is_causal(question)

    if causal:
        for tool in BROADENING_TOOLS["causal"]:
            if tool not in tools:
                tools.append(tool)

    # A question that names several domains, or asks for a broad picture,
    # is a place where a whole second set of sources would help.
    if len(domains) >= 3 or "summary" in domains:
        for tool in BROADENING_TOOLS["broad"]:
            if tool not in tools:
                tools.append(tool)

    # Hard ceiling. Each tool is at least one aggregation, and an
    # unbounded fan-out is how an assistant turns a question into a
    # table scan.
    tools = tools[:6]

    return {
        "window": {
            "start_date": window["start"].isoformat(),
            "end_date": window["end"].isoformat(),
            "label": window["label"],
            "source": window["source"],
            "inherited": window["inherited"],
        },
        "domains": domains,
        "tools": tools,
        "causal": causal,
        "domain_scores": [
            {"domain": domain, "score": score}
            for domain, score in score_domains(question)[:8]
        ],
    }


def extract_named_guest(question: str, db_guest_names=None) -> str | None:
    """
    Find a guest name in free text, when one can be matched safely.

    Only a name that actually appears as a customer on an order is
    accepted, and only on word boundaries. Guessing a person from
    arbitrary capitalised words would let an unrelated phrase be treated
    as a customer, so the recorded names are the only accepted answers.

    The longest match wins, so a full name is preferred over a first name
    that happens to be a substring of it. When the question says more
    than the record holds - "Rahul Verma" against a record that only
    stores "Rahul" - the tool reports the recorded name, so the answer
    names the record rather than the phrase.
    """
    if not question:
        return None

    candidates = [
        name for name in (db_guest_names or []) if name and len(name) > 2
    ]

    lowered = question.lower()

    matches = []

    for name in candidates:
        pattern = r"\b" + re.escape(name.lower()) + r"\b"

        if re.search(pattern, lowered):
            matches.append(name)

    if not matches:
        return None

    return max(matches, key=len)


def extract_threshold(question: str) -> int | None:
    """
    A duration or count threshold stated in the question.

    "orders taking over 45 minutes" -> 45. This is why the kitchen tool
    takes a threshold parameter rather than hard-coding one.
    """
    match = re.search(
        r"(\d+)\s*(?:min|minute|minutes|mins)\b", question or "", re.IGNORECASE
    )

    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return None

    return None
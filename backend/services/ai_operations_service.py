"""
The restaurant-wide AI operations assistant.

--------------------------------------------------------------------------
PIPELINE
--------------------------------------------------------------------------
    question (+ conversation context)
      -> question_router     which dates, which domains, which tools
      -> restaurant_tools    validated dicts, or an explicit limitation
      -> arithmetic          computed here, in plain Python
      -> composition         conclusion / numbers / observations /
                             inference / recommendation / limitations

--------------------------------------------------------------------------
WHY THERE IS NO LANGUAGE MODEL
--------------------------------------------------------------------------
Every number in an answer is a value a tool returned from MySQL. Growth
percentages, cancellation rates and collection rates are Python
subtractions over those same values, so they can be checked by hand.

The reasoning step is deterministic phrasing over validated data rather
than a model. That is a deliberate constraint, not a shortcut: an
assistant that can read the restaurant's money and customers must not be
able to invent a figure, and the cheapest way to guarantee it is for
there to be no step where a figure could be invented at all.

It also means the assistant can only be as good as the data behind it.
Where the database holds no delivery lifecycle, the assistant reports no
delivery performance. That is the correct behaviour, and it is the reason
this is not a hallucination risk.

--------------------------------------------------------------------------
FACT, INFERENCE, RECOMMENDATION
--------------------------------------------------------------------------
The answer is assembled in sections, and each section may only contain
one kind of claim:

  FACTS          values a tool returned. Always traceable.
  OBSERVATIONS   arithmetic over those facts, still factual.
  INFERENCE      what the pattern *suggests*, phrased as a suggestion
                 and only raised when supporting data was actually
                 retrieved. A causal claim requires an explicit source
                 for the cause; without one, the section says the data is
                 insufficient rather than guessing.
  RECOMMENDATION advice, explicitly labelled as a recommendation, and
                 derived from a named observation rather than invented.
  LIMITATIONS    what could not be answered, and why.

--------------------------------------------------------------------------
CONVERSATION CONTEXT
--------------------------------------------------------------------------
Held in memory on the session, never in the database, and it carries only
the resolved window, the domains and the tool names from recent turns.
The admin's question text is not retained. That is enough for "what about
the previous week?" and "why was it lower?" to mean something, without
storing anything about what was asked.
"""

import re
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from models import Order

from services import question_router
from services import restaurant_tools
from services.restaurant_tools import (
    TOOL_REGISTRY,
    capabilities,
    percent_change,
)


# How many turns of resolved context to remember. Three is enough for
# "sales yesterday" -> "previous week" -> "why was it lower", and short
# enough that context cannot drift far from what the admin is looking at.
CONTEXT_TURNS = 3

# Refusal to guess at a number that is absent from the tool output. Any
# formatter asked for a value that is None must render the no-data
# string, never 0.
NO_FIGURE = "no recorded figure"


def rupees(value) -> str:
    """Rupee amount with Indian digit grouping, or an explicit absence."""
    if value is None:
        return NO_FIGURE

    amount = round(float(value), 2)
    negative = amount < 0

    whole, _, fraction = f"{abs(amount):.2f}".partition(".")

    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
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


def plural(count, singular: str, many: str | None = None) -> str:
    if count is None:
        return f"{NO_FIGURE} {singular}"

    return f"{count} {singular if count == 1 else (many or singular + 's')}"


def pct(value, suffix: str = "%") -> str:
    if value is None:
        return NO_FIGURE

    return f"{round(float(value), 1)}{suffix}"


# =========================================================
# CONTEXT
# =========================================================

def new_context() -> dict:
    return {"turns": []}


def remember_turn(context: dict | None, plan: dict, evidence: dict) -> dict:
    """
    Fold one completed turn into the conversation memory.

    Only the resolved window, the domains and the tool names are kept.
    The question itself is deliberately not stored: it is not needed to
    make a follow-up work, and keeping admin questions around would create
    a record of what the operator was investigating for no benefit.
    """
    memory = dict(context or new_context())

    turns = list(memory.get("turns") or [])

    turns.append({
        "window": plan["window"],
        "domains": plan["domains"],
        "tools": plan["tools"],
        "answered": bool(evidence.get("tools_with_data")),
        "at": datetime.utcnow().isoformat(timespec="seconds"),
    })

    memory["turns"] = turns[-CONTEXT_TURNS:]

    latest = memory["turns"][-1]

    # Flattened for the router, which reads these two keys directly.
    memory["window"] = latest["window"]
    memory["domains"] = latest["domains"]

    return memory


# =========================================================
# EVIDENCE GATHERING
# =========================================================

def gather_evidence(db: Session, plan: dict, question: str,
                    guest: str | None = None) -> dict:
    """
    Run the planned tools and collect what they actually returned.

    One failing tool does not abort the answer. Its failure becomes a
    limitation the admin can read, which is far more useful than an
    error page that hides the tools that did work.
    """
    window = plan["window"]
    evidence = {
        "tools": {},
        "tools_with_data": [],
        "tools_without_data": [],
        "limitations": [],
        "failures": [],
    }

    params = {
        "range": window["label"],
        "start": window["start_date"],
        "end": window["end_date"],
    }

    threshold = question_router.extract_threshold(question)

    if threshold:
        params["slow_threshold_minutes"] = threshold

    # A named guest is only recognised if that name exists on an order.
    # A random capitalised word in a sentence is not a person.
    if guest:
        params["customer_name"] = guest

    for tool_name in plan["tools"]:
        tool = TOOL_REGISTRY.get(tool_name)

        if not tool:
            continue

        try:
            result = tool.run(db, params)
        except Exception as error:
            # Deliberately broad. A tool that blows up must degrade the
            # answer, never break it, and must never leak its internals.
            evidence["failures"].append({
                "tool": tool_name,
                "message": f"{type(error).__name__} while reading this data",
            })

            continue

        evidence["tools"][tool_name] = result

        if result.get("has_data"):
            evidence["tools_with_data"].append(tool_name)
        else:
            evidence["tools_without_data"].append(tool_name)

        # A limitation is reported whenever the tool states one, whether
        # or not it returned rows. The delivery tool is the case that
        # matters: it finds delivery orders *and* has to say that this
        # project has no delivery lifecycle. Dropping the limitation
        # because rows came back would leave a confident-looking delivery
        # answer with the honest half of it removed.
        limitation = result.get("limitation")

        if limitation:
            evidence["limitations"].append({
                "tool": tool_name,
                "domain": tool.domain,
                "message": limitation,
            })

    return evidence


def _find_named_guest(db: Session, question: str) -> str | None:
    """
    Resolve a guest name mentioned in free text.

    The candidate list is the names actually present on orders, so this
    cannot latch onto an arbitrary capitalised word in a sentence. A
    capitalised token has to be present for the lookup to be worth making,
    so an all-lowercase question never pays for the distinct-name query.
    """
    if not re.search(r"[A-Z]", question or ""):
        return None

    names = [
        row[0]
        for row in db.query(Order.customer_name)
        .filter(Order.customer_name.isnot(None))
        .distinct()
        .limit(500)
        .all()
    ]

    return question_router.extract_named_guest(question, names)


# =========================================================
# COMPOSITION
#
# Each builder receives the evidence dict and returns the sections it can
# support from the data actually present. Nothing here invents a value.
# =========================================================

def _conclusion_from(evidence: dict, window: dict) -> str | None:
    """The one-sentence headline, taken from the strongest tool present."""
    tools = evidence["tools"]

    comparison = tools.get("get_historical_comparison")

    if comparison and comparison.get("has_data"):
        change = comparison.get("change") or {}
        revenue_change = change.get("revenue_percent")

        if revenue_change is None:
            return (
                f"Across {window['label']} the recorded revenue totals "
                f"{rupees(comparison['current']['revenue'])}, and there is "
                f"no comparable figure in the preceding period to measure "
                f"it against."
            )

        direction = "higher" if revenue_change > 0 else (
            "lower" if revenue_change < 0 else "level"
        )

        return (
            f"Revenue for {window['label']} was "
            f"{rupees(comparison['current']['revenue'])}, "
            f"{abs(revenue_change)}% {direction} than the preceding "
            f"{comparison['previous']['start_date']} to "
            f"{comparison['previous']['end_date']} period."
        )

    revenue = tools.get("get_revenue_metrics")

    if revenue and revenue.get("has_data"):
        return (
            f"Revenue for {window['label']} totals "
            f"{rupees(revenue['revenue'])} across "
            f"{plural(revenue['orders'], 'order')}, averaging "
            f"{rupees(revenue['average_order_value'])} per order."
        )

    summary = tools.get("get_business_summary")

    if summary and summary.get("has_data"):
        # "Billed", never "recorded" or "earned". The summary figure is
        # what guests were charged; whether it has been paid is a separate
        # question, and phrasing it as revenue would imply it had been.
        return (
            f"Across {window['label']} the restaurant billed "
            f"{rupees(summary['revenue'])} across "
            f"{plural(summary['orders'], 'order')}, with "
            f"{plural(summary['reviews'], 'review')} and "
            f"{plural(summary['reservations'], 'reservation')}. That is "
            f"the amount owed, not the amount collected."
        )

    return None


def _key_numbers(evidence: dict, window: dict) -> list:
    """The figures worth reading first. Each traceable to a tool."""
    tools = evidence["tools"]
    lines = []

    revenue = tools.get("get_revenue_metrics")

    if revenue and revenue.get("has_data"):
        lines.append(
            f"Revenue {rupees(revenue['revenue'])}, "
            f"orders {revenue['orders']}, "
            f"portions {revenue['portions_sold']}, "
            f"average order {rupees(revenue['average_order_value'])}"
        )

    comparison = tools.get("get_historical_comparison")

    if comparison and comparison.get("has_data"):
        change = comparison.get("change") or {}

        lines.append(
            "Against the previous period: revenue "
            f"{pct(change.get('revenue_percent'))}, orders "
            f"{pct(change.get('orders_percent'))}, average order value "
            f"{pct(change.get('average_order_value_percent'))}"
        )

    orders = tools.get("get_order_metrics")

    if orders and orders.get("has_data"):
        lines.append(
            f"Orders: {orders['checkout_orders']} through checkout, "
            f"{orders['legacy_orders']} legacy rows, "
            f"{orders['cancelled_orders']} cancelled "
            f"(cancellation rate {pct(orders.get('cancellation_rate_percent'))})"
        )

    bills = tools.get("get_bill_metrics")

    if bills and bills.get("has_data"):
        lines.append(
            f"Bills: {bills['bills']} totalling {rupees(bills['bill_total'])} "
            f"(tax {rupees(bills['tax_total'])}, service charge "
            f"{rupees(bills['service_charge_total'])}, discount "
            f"{rupees(bills['discount_total'])})"
        )

    payments = tools.get("get_payment_metrics")

    if payments and payments.get("has_data"):
        lines.append(
            f"Billed {rupees(payments['billed'])} across "
            f"{plural(payments.get('bills'), 'bill')}; collected "
            f"{rupees(payments['collected'])} "
            f"({pct(payments.get('collection_percent'))}), outstanding "
            f"{rupees(payments['outstanding'])}"
        )

        if payments.get("payment_requests"):
            lines.append(
                f"Payment requests: {payments['payment_requests']} "
                f"({payments['successful_payments']} confirmed, "
                f"{payments['failed_payments']} failed, "
                f"{payments.get('cancelled_payments', 0)} withdrawn, "
                f"{payments['pending_payments']} still awaiting "
                f"confirmation)"
            )

        if payments.get("bills") is not None:
            lines.append(
                f"Bills by state: {payments.get('bills_paid', 0)} paid, "
                f"{payments.get('bills_unpaid', 0)} not yet paid"
            )

    customers = tools.get("get_customer_metrics")

    if customers and customers.get("has_data"):
        lines.append(
            f"Guests ordering: {customers['guests_ordering_in_window']} "
            f"({customers['returning_guests_in_window']} returning, "
            f"{customers['new_guests_in_window']} new)"
        )

    menu = tools.get("get_menu_performance")

    if menu and menu.get("has_data"):
        dishes = menu.get("top_dishes") or []

        if dishes:
            lines.append(
                "Top dishes: "
                + ", ".join(
                    f"{dish['dish']} ({dish['quantity_sold']})"
                    for dish in dishes[:3]
                )
            )

    kitchen = tools.get("get_kitchen_metrics")

    if kitchen and kitchen.get("has_data"):
        durations = kitchen.get("placed_to_served_minutes") or {}

        lines.append(
            f"Kitchen: {kitchen['open_tickets']} open tickets, "
            f"{kitchen['backlog_tickets']} pending or preparing, "
            f"placed to served average "
            f"{_minutes(durations.get('average'))} "
            f"over {durations.get('orders', 0)} orders"
        )

    reservations = tools.get("get_reservation_metrics")

    if reservations and reservations.get("has_data"):
        lines.append(
            f"Reservations: {reservations['reservations']} covering "
            f"{reservations['covers']} guests, average party "
            f"{reservations['average_party_size']}"
        )

    inventory = tools.get("get_inventory_metrics")

    if inventory and inventory.get("has_data"):
        lines.append(
            f"Inventory: {inventory['total_items']} items tracked, "
            f"{inventory['low_stock_count']} low, "
            f"{inventory['out_of_stock_count']} out of stock, valued at "
            f"{rupees(inventory['total_stock_value'])}"
        )

    waste = tools.get("get_waste_metrics")

    if waste and waste.get("has_data"):
        lines.append(
            f"Waste: {rupees(waste['total_cost'])} recorded "
            f"({waste['total_quantity']} units)"
        )

    reviews = tools.get("get_review_metrics")

    if reviews and reviews.get("has_data"):
        lines.append(
            f"Reviews: {reviews['total_reviews']} at an average "
            f"{reviews['average_rating']}, "
            f"{reviews['negative_reviews']} negative"
        )

    tables = tools.get("get_table_metrics")

    if tables and tables.get("has_data"):
        lines.append(
            f"Tables: {tables['total_tables']} configured, "
            f"{tables['guests_currently_seated']} guests currently seated"
        )

    delivery = tools.get("get_delivery_metrics")

    if delivery and delivery.get("has_data"):
        lines.append(
            f"Delivery: {delivery['delivery_order_lines']} delivery order "
            f"lines totalling {rupees(delivery['delivery_revenue'])}"
        )

    history = tools.get("get_customer_history")

    if history and history.get("has_data"):
        dishes = history.get("dishes") or []

        lines.append(
            f"{history['customer_name']}: "
            f"{plural(history.get('total_portions'), 'portion')} ordered, "
            f"{rupees(history.get('total_spent'))} spent, first seen "
            f"{(history.get('first_seen') or 'unknown')[:10]}"
        )

        if dishes:
            lines.append(
                f"{history['customer_name']}'s recorded dishes: "
                + ", ".join(
                    f"{dish['dish']} x{dish['portions']}"
                    for dish in dishes[:6]
                )
            )

    return lines


def _minutes(value) -> str:
    if value is None:
        return NO_FIGURE

    return f"{round(float(value))} minutes"


def _observations(evidence: dict) -> list:
    """
    Patterns in the data, phrased without claiming a cause.

    Each observation is arithmetic on retrieved facts. Where two facts move
    in the same direction the observation names the coincidence and stops
    there, because "these moved together" is a fact and "one caused the
    other" is not.
    """
    tools = evidence["tools"]
    lines = []

    comparison = tools.get("get_historical_comparison")

    if comparison and comparison.get("has_data"):
        change = comparison.get("change") or {}
        current = comparison.get("current") or {}
        previous = comparison.get("previous") or {}

        revenue_change = change.get("revenue_percent")
        orders_change = change.get("orders_percent")
        aov_change = change.get("average_order_value_percent")

        if None not in (revenue_change, orders_change):
            if (revenue_change or 0) < 0 and (orders_change or 0) < 0:
                lines.append(
                    f"Order count fell {abs(orders_change)}% while average "
                    f"order value moved {_signed(aov_change)}, so the "
                    f"revenue difference is accounted for mainly by fewer "
                    f"orders rather than by smaller ones."
                )
            elif (revenue_change or 0) < 0 and (orders_change or 0) >= 0:
                lines.append(
                    f"Order count did not fall ({_signed(orders_change)}) "
                    f"but revenue did ({_signed(revenue_change)}), with "
                    f"average order value at {_signed(aov_change)}."
                )
            elif (revenue_change or 0) > 0:
                lines.append(
                    f"Both order count ({_signed(orders_change)}) and "
                    f"average order value ({_signed(aov_change)}) moved in "
                    f"the same direction as revenue."
                )

        current_cancel = current.get("cancellation_rate_percent")
        previous_cancel = previous.get("cancellation_rate_percent")

        if current_cancel is not None and previous_cancel is not None:
            if current_cancel > previous_cancel:
                lines.append(
                    f"Cancellation rate rose from {pct(previous_cancel)} to "
                    f"{pct(current_cancel)} of closed orders in the same "
                    f"comparison."
                )

    orders = tools.get("get_order_metrics")

    if orders and orders.get("has_data"):
        mix = orders.get("order_types") or {}

        if mix:
            parts = ", ".join(
                f"{name} {count}" for name, count in sorted(mix.items())
            )

            lines.append(f"Order type mix in the window: {parts}.")

        lifecycle = orders.get("lifecycle") or {}

        active = {
            status: lifecycle.get(status, 0)
            for status in ("Placed", "Confirmed", "Preparing", "Ready")
        }

        in_flight = sum(active.values())

        if in_flight:
            lines.append(
                f"{in_flight} order(s) are still in progress: "
                + ", ".join(
                    f"{status.lower()} {count}"
                    for status, count in active.items()
                    if count
                )
                + "."
            )

    kitchen = tools.get("get_kitchen_metrics")

    if kitchen and kitchen.get("has_data"):
        durations = kitchen.get("placed_to_served_minutes") or {}

        if durations.get("average") is not None:
            lines.append(
                f"Average time from order placed to served was "
                f"{_minutes(durations['average'])} across "
                f"{plural(durations.get('orders'), 'order')}, longest "
                f"{_minutes(durations.get('maximum'))}."
            )
        elif durations.get("orders") == 0:
            lines.append(
                "No order has completed the full placed-to-served path in "
                "this window."
            )

        slow = kitchen.get("slow_orders") or []

        if slow:
            lines.append(
                f"{len(slow)} order(s) took longer than the threshold "
                f"asked about, the longest at "
                f"{_minutes(max(item['minutes_to_serve'] for item in slow))}."
            )

    menu = tools.get("get_menu_performance")

    if menu and menu.get("has_data"):
        never = menu.get("items_never_ordered") or []

        if never:
            lines.append(
                f"{len(never)} menu item(s) have no recorded sales in this "
                f"window: "
                + ", ".join(item["dish"] for item in never[:5])
                + "."
            )

        unavailable = menu.get("unavailable_items") or []

        if unavailable:
            lines.append(
                f"{len(unavailable)} menu item(s) are currently marked "
                f"unavailable."
            )

    reviews = tools.get("get_review_metrics")

    if reviews and reviews.get("has_data"):
        negative = reviews.get("negative_reviews") or 0
        total = reviews.get("total_reviews") or 0

        if negative:
            lines.append(
                f"{negative} of {total} recorded reviews were classified "
                f"negative ({pct(reviews.get('negative_percent'))}). "
                f"The lowest rated were "
                + ", ".join(
                    f"{item['dish']} ({item['rating']})"
                    for item in (reviews.get("lowest_rated") or [])[:3]
                )
                + "."
            )

    inventory = tools.get("get_inventory_metrics")

    if inventory and inventory.get("has_data"):
        out = inventory.get("out_of_stock_items") or []
        low = inventory.get("low_stock_items") or []

        if out:
            lines.append(
                f"{len(out)} inventory item(s) are out of stock: "
                + ", ".join(item["item_name"] for item in out[:5])
                + "."
            )
        elif low:
            lines.append(
                f"{len(low)} inventory item(s) are at or below minimum "
                f"stock."
            )

    reservations = tools.get("get_reservation_metrics")

    if reservations and reservations.get("has_data"):
        cancelled = reservations.get("cancelled_reservations") or 0

        if cancelled:
            lines.append(
                f"{cancelled} reservation(s) were cancelled "
                f"({pct(reservations.get('cancellation_rate_percent'))} of "
                f"closed bookings)."
            )

        if reservations.get("busiest_hour") is not None:
            lines.append(
                f"The busiest booked hour was "
                f"{reservations['busiest_hour']:02d}:00."
            )

    payments = tools.get("get_payment_metrics")

    if payments and payments.get("has_data"):
        collected = payments.get("collection_percent")

        if collected is not None and collected < 100:
            lines.append(
                f"Only {pct(collected)} of the value billed in this window "
                f"has been confirmed as collected, leaving "
                f"{rupees(payments['outstanding_value'])} outstanding. A "
                f"payment request is not a payment: an attempt is counted "
                f"as collected only after a provider confirms it."
            )

        if (payments.get("pending_payments") or 0) > 0:
            lines.append(
                f"{payments['pending_payments']} payment request(s) have "
                f"been issued but not yet confirmed. Nothing can be counted "
                f"as collected until the provider reports back."
            )

    gateway = (payments or {}).get("gateway") or {}

    if gateway:
        # The provider and mode come from the backend's own configuration.
        # The assistant states them; it never infers them, and it never says
        # a gateway is connected unless the backend said so.
        provider_name = gateway.get("provider") or "none"
        mode = gateway.get("mode") or "unknown"

        lines.append(
            f"Payment provider: {provider_name} in {mode} mode."
        )

    if gateway and gateway.get("live_gateway_connected") is False:
        statement = gateway.get("gateway_statement")

        if statement:
            lines.append(statement)

    delivery = tools.get("get_delivery_metrics")

    if delivery and delivery.get("has_data"):
        lines.append(
            f"Delivery order lines recorded: "
            f"{delivery['delivery_order_lines']}."
        )

    forecast = tools.get("get_forecast")

    if forecast and forecast.get("has_data"):
        revenue_forecast = forecast.get("revenue") or {}
        predicted = revenue_forecast.get("predicted_total_revenue")

        if predicted is not None:
            lines.append(
                f"The existing revenue model projects "
                f"{rupees(predicted)} over the next "
                f"{revenue_forecast.get('days_ahead', 7)} days. This is a "
                f"linear extrapolation of recorded history, not a "
                f"commitment."
            )

    return lines


def _signed(value) -> str:
    if value is None:
        return NO_FIGURE

    return f"{'+' if value > 0 else ''}{round(float(value), 1)}%"


def _inference(evidence: dict, causal: bool) -> list:
    """
    What the retrieved data suggests, and nothing more.

    Only raised when a supporting tool was actually read. A causal
    question with no explanatory data returns a statement that the
    available data is insufficient, which is the honest answer and is
    required behaviour rather than a fallback.
    """
    tools = evidence["tools"]
    lines = []

    comparison = tools.get("get_historical_comparison")
    reviews = tools.get("get_review_metrics")
    reservations = tools.get("get_reservation_metrics")
    menu = tools.get("get_menu_performance")

    if comparison and comparison.get("has_data"):
        change = comparison.get("change") or {}
        revenue_change = change.get("revenue_percent")

        if revenue_change is not None and revenue_change < 0:
            lines.append(
                f"The data suggests the fall is a volume pattern rather "
                f"than a pricing one, because order count and average "
                f"order value moved separately and only their combination "
                f"reaches the recorded revenue figure."
            )

    # Review activity alongside revenue movement: report the coincidence,
    # explicitly refusing to call it a cause.
    if comparison and comparison.get("has_data") and reviews:
        if reviews.get("has_data"):
            lines.append(
                f"Review activity in the same window totals "
                f"{plural(reviews.get('total_reviews'), 'review')} with an "
                f"average rating of {reviews.get('average_rating')}. The "
                f"data does not establish that review sentiment caused the "
                f"revenue movement, and this assistant will not assert a "
                f"cause the recorded data does not show."
            )
        else:
            lines.append(
                f"No reviews were recorded in this window, so review "
                f"sentiment cannot be offered as an explanation for the "
                f"revenue movement."
            )

    if menu and menu.get("has_data"):
        never = menu.get("items_never_ordered") or []

        if never:
            lines.append(
                f"The data suggests the menu is wider than demand: "
                f"{len(never)} item(s) have no recorded sales in this "
                f"window."
            )

    if reservations and reservations.get("has_data"):
        cancelled = reservations.get("cancelled_reservations") or 0

        if cancelled:
            lines.append(
                f"The data suggests some demand did not convert: "
                f"{cancelled} booking(s) were cancelled."
            )

    if causal and not lines:
        lines.append(
            "The data retrieved does not explain the cause of what was "
            "asked about. It records what happened; the systems that would "
            "explain why - kitchen delay reasons, cancellation reasons, "
            "payment failures - do not exist in this project yet, so no "
            "cause is asserted."
        )

    return lines


def _recommendations(evidence: dict) -> list:
    """
    Advice, each one traceable to an observation already made.

    A recommendation is only emitted where the evidence contains the
    specific trigger for it. Nothing here fires on a hunch.
    """
    tools = evidence["tools"]
    lines = []

    inventory = tools.get("get_inventory_metrics")

    if inventory and inventory.get("has_data"):
        out = inventory.get("out_of_stock_items") or []
        low = inventory.get("low_stock_items") or []

        if out:
            names = ", ".join(item["item_name"] for item in out[:5])

            lines.append(
                f"I recommend reordering {names} before service, because "
                f"these items are recorded at or below zero while still "
                f"being counted as tracked stock."
            )
        elif low:
            names = ", ".join(item["item_name"] for item in low[:5])

            lines.append(
                f"I recommend reviewing the reorder point for {names}; "
                f"these are at or below their recorded minimum."
            )

    payments = tools.get("get_payment_metrics")

    if payments and payments.get("has_data"):
        outstanding = payments.get("outstanding_value") or 0

        if outstanding > 0:
            requests = payments.get("payment_requests") or 0

            if requests:
                lines.append(
                    f"I recommend chasing the "
                    f"{rupees(outstanding)} of outstanding billed value; "
                    f"{requests} payment request(s) exist and only "
                    f"{payments.get('successful_payments') or 0} have been "
                    f"confirmed. Confirming an existing request is faster "
                    f"than issuing a new one."
                )
            else:
                lines.append(
                    f"I recommend chasing the "
                    f"{rupees(outstanding)} of outstanding billed value. "
                    f"No payment request has been raised for it yet, so "
                    f"nobody has been asked to pay."
                )

    reviews = tools.get("get_review_metrics")

    if reviews and reviews.get("has_data"):
        low_rated = [
            item for item in (reviews.get("lowest_rated") or [])
            if item.get("dish") and item["dish"] != "not dish specific"
        ]

        if reviews.get("negative_percent") and reviews["negative_percent"] >= 25:
            if low_rated:
                names = ", ".join(
                    item["dish"] for item in low_rated[:3]
                )

                lines.append(
                    f"I recommend looking at {names}, which carry the "
                    f"lowest recorded ratings, while treating these few "
                    f"reviews as a signal rather than a verdict."
                )

    menu = tools.get("get_menu_performance")

    if menu and menu.get("has_data"):
        never = menu.get("items_never_ordered") or []

        if len(never) >= 5:
            lines.append(
                f"I recommend reviewing whether the "
                f"{len(never)} menu item(s) with no recorded sales this "
                f"window belong on the menu."
            )

    kitchen = tools.get("get_kitchen_metrics")

    if kitchen and kitchen.get("has_data"):
        durations = kitchen.get("placed_to_served_minutes") or {}
        average = durations.get("average")

        if average is not None and average > 45:
            lines.append(
                f"I recommend reviewing kitchen throughput: the recorded "
                f"placed-to-served average is "
                f"{_minutes(average)}."
            )

    return lines


def _limitations(evidence: dict) -> list:
    """What could not be answered, stated plainly."""
    lines = []

    for entry in evidence["limitations"]:
        lines.append(f"{entry['message']}")

    for failure in evidence["failures"]:
        lines.append(
            f"The {failure['tool']} data source could not be read "
            f"({failure['message']}), so it is not represented in this "
            f"answer."
        )

    return lines


def _sources(evidence: dict) -> list:
    """
    Which data sources actually contributed.

    Names the tools that returned data. Tools that returned nothing are
    excluded, because listing a source that contributed nothing would
    overstate how much was actually known.
    """
    rows = []

    for name in evidence["tools_with_data"]:
        tool = TOOL_REGISTRY.get(name)

        if not tool:
            continue

        rows.append({
            "tool": name,
            "domain": tool.domain,
            "description": tool.description,
        })

    return rows


# =========================================================
# ENTRY POINT
# =========================================================

GREETING = (
    "Ask me anything about the restaurant - sales, orders, bills, "
    "payments, customers, menu, reservations, tables, kitchen, "
    "inventory, waste or reviews. Every figure I give you is read from "
    "the database at the moment you ask, and where the data does not "
    "exist I will say so instead of estimating."
)


def answer_operations_question(
    db: Session,
    question: str,
    context: dict | None = None,
) -> dict:
    """
    Answer one restaurant-wide question.

    Returns the composed answer together with everything behind it: the
    plan, the tools that ran, the context update for the next turn, and
    the capabilities list so a client can show what is available.
    """
    text = (question or "").strip()

    if not text:
        return {
            "question": question,
            "answer": GREETING,
            "greeting": True,
            "conclusion": None,
            "key_numbers": [],
            "observations": [],
            "inference": [],
            "recommendations": [],
            "limitations": [],
            "data_sources": [],
            "window": None,
            "domains": [],
            "tools_used": [],
            "tools_without_data": [],
            "answered": False,
            "has_data": False,
            "capabilities": capabilities(),
            "context": context or new_context(),
            "generated_at": datetime.utcnow().isoformat(timespec="seconds"),
        }

    if text.lower().strip(".!? ") in (
        "hi", "hello", "hey", "thanks", "thank you", "ok", "okay", "bye",
    ):
        return {
            "question": question,
            "answer": GREETING,
            "greeting": True,
            "conclusion": None,
            "key_numbers": [],
            "observations": [],
            "inference": [],
            "recommendations": [],
            "limitations": [],
            "data_sources": [],
            "window": None,
            "domains": [],
            "tools_used": [],
            "tools_without_data": [],
            "answered": False,
            "has_data": False,
            "capabilities": capabilities(),
            "context": context or new_context(),
            "generated_at": datetime.utcnow().isoformat(timespec="seconds"),
        }

    plan = question_router.plan_tools(text, context)

    # A guest named in the question gets their own history read, in
    # addition to whatever the domains selected. Resolved before the
    # tools run so `customer_name` is already in the parameter dict.
    guest = _find_named_guest(db, text)

    if guest and "get_customer_history" not in plan["tools"]:
        plan["tools"] = (plan["tools"] + ["get_customer_history"])[:6]

    evidence = gather_evidence(db, plan, text, guest=guest)

    conclusion = _conclusion_from(evidence, plan["window"])

    key_numbers = _key_numbers(evidence, plan["window"])
    observations = _observations(evidence)
    inference = _inference(evidence, plan["causal"])
    recommendations = _recommendations(evidence)
    limitations = _limitations(evidence)

    # A spoken answer, assembled from the same validated sections. The
    # prose cannot contain a figure that is not in one of them, because
    # it is built from them.
    spoken = _speak(conclusion, key_numbers, observations, inference,
                    recommendations, limitations)

    answered = bool(evidence["tools_with_data"])

    if not answered:
        spoken = (
            "I could not find recorded data for what you asked about. "
            + (
                " ".join(limitations)
                if limitations
                else "The sources I would need returned no rows."
            )
        )

    updated_context = remember_turn(context, plan, evidence)

    return {
        "question": question,
        "answer": spoken,
        "greeting": False,
        "conclusion": conclusion,
        "key_numbers": key_numbers,
        "observations": observations,
        "inference": inference,
        "recommendations": recommendations,
        "limitations": limitations,
        "data_sources": _sources(evidence),
        "window": plan["window"],
        "domains": plan["domains"],
        "tools_used": evidence["tools_with_data"],
        "tools_without_data": evidence["tools_without_data"],
        "plan": {
            "window": plan["window"],
            "domains": plan["domains"],
            "tools": plan["tools"],
            "causal": plan["causal"],
        },
        "answered": answered,
        "has_data": answered,
        "capabilities": capabilities(),
        "context": updated_context,
        "generated_at": datetime.utcnow().isoformat(timespec="seconds"),
    }


def _speak(conclusion, key_numbers, observations, inference,
           recommendations, limitations) -> str:
    """
    Render the sections as one paragraph.

    Deliberately plain. Each part is a string that was already built from
    tool output, so this step performs no arithmetic and cannot introduce
    a figure.
    """
    parts = []

    if conclusion:
        parts.append(conclusion)

    for line in key_numbers:
        parts.append(line)

    if observations:
        parts.append(
            "Observations from the recorded data: "
            + " ".join(observations)
        )

    if inference:
        parts.append(
            "What the data suggests: " + " ".join(inference)
        )

    if recommendations:
        parts.append("Recommendations: " + " ".join(recommendations))

    if limitations:
        parts.append(
            "What I could not tell you: " + " ".join(limitations)
        )

    return " ".join(parts) if parts else (
        "I did not find recorded data for that question."
    )


def new_session() -> dict:
    """A fresh, empty conversation memory."""
    return new_context()
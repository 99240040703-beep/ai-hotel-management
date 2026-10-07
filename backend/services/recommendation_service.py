"""
Personalized dish recommendations for the signed-in customer.

--------------------------------------------------------------------------
IDENTITY
--------------------------------------------------------------------------
The only thing that identifies the customer here is `user_id`, taken
from the verified JWT by the caller. Names, emails and request bodies
are never used to look history up.

That matters in this dataset: the seeded history is written against CRM
names such as "Meena" and "Karthik" which have no login account, and
`orders.user_id` is NULL on every one of those rows. Those sales are
still real and are still used for *aggregate* signals such as today's
trending dishes, but they are never attributed to a person, because
nothing links them to one. A customer with no linked orders is reported
as having no history rather than being handed someone else's taste.

--------------------------------------------------------------------------
SCORING
--------------------------------------------------------------------------
Every candidate dish is scored from five measured signals, each
normalised to 0..1 and then combined with fixed weights:

    score = 0.34 * category_affinity      how much this guest already
                                          buys from this dish's category
        + 0.26 * today_popularity         how much of it sold today,
                                          across all guests
        + 0.22 * similarity               TF-IDF cosine between this
                                          dish and what the guest ate
        + 0.12 * recency                  how recently the guest's own
                                          last order in this category was
        + 0.06 * discovery                a nudge toward dishes the
                                          guest has never ordered

The weights favour personal taste, then what is selling right now, then
text similarity. `score` is a ranking value in 0..1 - it is NOT a
confidence percentage and is never presented as one. There is no
"98% AI confidence" anywhere in this system, because nothing here
computes a calibrated probability.

--------------------------------------------------------------------------
REASONS
--------------------------------------------------------------------------
A reason is emitted only when the signal behind it actually fired, and
it quotes the measurement that produced it ("you have ordered Biryani 3
times", "6 portions sold today"). A dish with no supporting evidence is
either given no reason or is not recommended at all - the UI is never
told to invent a justification.
"""

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from math import exp

from sqlalchemy import func
from sqlalchemy.orm import Session

from models import Menu, Order


# Component weights. They sum to 1.0 so `score` stays in 0..1.
WEIGHTS = {
    "category_affinity": 0.34,
    "today_popularity": 0.26,
    "similarity": 0.22,
    "recency": 0.12,
    "discovery": 0.06,
}

DEFAULT_TOP_N = 8

# A dish whose combined score is below this is not worth showing, so a
# guest is never handed a list of unrelated food to pad the card out.
MIN_SCORE = 0.02


def _to_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def dish_profile(item: Menu) -> str:
    """
    The text used for TF-IDF.

    Name, category and description are all included: two dishes can share
    a category and differ only in description, and matching on category
    alone would rate them as identical.
    """
    parts = [item.name or "", item.category or "", item.description or ""]

    return " ".join(part for part in parts if part).lower()


# =========================================================
# SIGNALS
# =========================================================

def customer_order_history(db: Session, user_id: int) -> list:
    """
    This guest's own order lines, newest first.

    Filtered on `user_id` only. Rows with a NULL user_id belong to no
    account and are excluded, so no guest can inherit another guest's
    history through a shared display name.
    """
    if not user_id:
        return []

    return (
        db.query(Order)
        .filter(Order.user_id == user_id)
        .order_by(Order.created_at.desc(), Order.id.desc())
        .all()
    )


def today_popularity(db: Session) -> dict:
    """
    Portions sold per dish for the current restaurant day.

    Aggregate across every guest - this is a property of the restaurant,
    not of a person, so it carries no ownership problem. One grouped
    query, not one query per dish.
    """
    today = date.today()

    rows = (
        db.query(
            Order.menu_item,
            func.coalesce(func.sum(Order.quantity), 0),
        )
        .filter(func.date(Order.created_at) == today.isoformat())
        .group_by(Order.menu_item)
        .all()
    )

    counts = {name: int(total or 0) for name, total in rows}

    peak = max(counts.values()) if counts else 0

    return {
        "date": today.isoformat(),
        "quantities": counts,
        # Normalised against the best-selling dish of the day.
        "normalized": {
            name: (total / peak if peak else 0.0)
            for name, total in counts.items()
        },
        "total_portions": sum(counts.values()),
        "peak": peak,
    }


def category_affinity(history: list, menu_by_name: dict) -> dict:
    """
    How much of this guest's spending sits in each category.

    Measured in portions ordered, then normalised against the category
    the guest ordered most, so the value is a share of their own
    behaviour rather than an absolute count.
    """
    per_category = Counter()

    for order in history:
        item = menu_by_name.get(order.menu_item)

        if not item or not item.category:
            continue

        per_category[item.category] += order.quantity or 1

    peak = max(per_category.values()) if per_category else 0

    return {
        category: (count / peak if peak else 0.0)
        for category, count in per_category.items()
    }


def category_recency(history: list, menu_by_name: dict) -> dict:
    """
    How recently the guest last ordered in each category.

    An exponential decay on days-since-last-order, so a category they
    ordered today scores far higher than one they last touched a month
    ago. Half-life is 21 days: after three weeks the signal is worth
    about half of what it was on the day.
    """
    latest = {}

    now = datetime.utcnow()

    for order in history:
        item = menu_by_name.get(order.menu_item)

        if not item or not item.category:
            continue

        created = order.created_at

        if not created:
            continue

        days = max(0, (now - created).days)

        current = latest.get(item.category)

        if current is None or days < current:
            latest[item.category] = days

    return {
        category: exp(-days / 21.0)
        for category, days in latest.items()
    }


def dish_frequency(history: list) -> Counter:
    """Portions of each named dish this guest has ordered."""
    counter = Counter()

    for order in history:
        counter[order.menu_item] += order.quantity or 1

    return counter


def last_ordered_at(history: list) -> dict:
    """Most recent order timestamp per dish name."""
    latest = {}

    for order in history:
        if not order.created_at:
            continue

        current = latest.get(order.menu_item)

        if current is None or order.created_at > current:
            latest[order.menu_item] = order.created_at

    return latest


def similarity_scores(menu_items: list, history: list) -> dict:
    """
    TF-IDF cosine between each dish and the guest's own taste profile.

    The profile is the concatenation of every dish this guest actually
    ordered, so a dish they order often weighs more in the profile text
    than one they tried once.

    Returns {} when there is no history or nothing to compare against,
    which the caller treats as "this signal is unavailable" rather than
    as a score of zero.
    """
    if not history or not menu_items:
        return {}

    # Imported here so the module still imports if scikit-learn is
    # absent, and the endpoint can report the limitation instead of
    # crashing on startup.
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
    except ImportError:
        return {}

    corpus = [dish_profile(item) for item in menu_items]

    # A corpus of blank strings makes the vectorizer raise, and every
    # menu row lacking a description would produce exactly that.
    if not any(corpus):
        return {}

    ordered = [order.menu_item for order in history]

    if not ordered:
        return {}

    try:
        vectorizer = TfidfVectorizer(stop_words="english")

        matrix = vectorizer.fit_transform(corpus)

        profile = vectorizer.transform([" ".join(ordered).lower()])

        scores = cosine_similarity(profile, matrix)[0]
    except ValueError:
        return {}

    return {
        item.id: float(score)
        for item, score in zip(menu_items, scores)
    }


# =========================================================
# SCORING
# =========================================================

def score_dishes(db: Session, user_id: int, menu_items: list) -> dict:
    """
    Score every available menu item for one guest.

    Returns the per-dish signals so the caller can explain a ranking
    instead of presenting an unexplained number.
    """
    menu_by_name = {item.name: item for item in menu_items}

    history = customer_order_history(db, user_id)

    trending = today_popularity(db)

    affinity = category_affinity(history, menu_by_name)
    recency = category_recency(history, menu_by_name)
    frequency = dish_frequency(history)
    similarity = similarity_scores(menu_items, history)

    has_history = bool(history)

    scored = []

    for item in menu_items:
        category = item.category or ""

        signals = {
            # A dish in a category this guest buys scores on their own
            # measured share of that category.
            "category_affinity": affinity.get(category, 0.0),
            # Aggregate restaurant-wide popularity for today.
            "today_popularity": trending["normalized"].get(item.name, 0.0),
            # Text similarity to what this guest has eaten.
            "similarity": similarity.get(item.id, 0.0),
            "recency": recency.get(category, 0.0),
            # Genuine novelty: never ordered by this guest.
            "discovery": 0.0 if item.name in frequency else 1.0,
        }

        score = sum(
            WEIGHTS[name] * value for name, value in signals.items()
        )

        scored.append(
            {
                "menu": item,
                "score": round(score, 4),
                "signals": {name: round(value, 4) for name, value in signals.items()},
            }
        )

    return {
        "scored": scored,
        "history": history,
        "trending": trending,
        "frequency": frequency,
        "last_ordered": last_ordered_at(history),
        "has_history": has_history,
    }


def build_reasons(entry: dict, context: dict) -> list:
    """
    Evidence-based reasons for one recommendation.

    A reason is only produced when the signal that justifies it is above
    zero AND the supporting measurement exists. Returns an empty list
    rather than a generic filler when there is nothing to say.
    """
    item = entry["menu"]
    signals = entry["signals"]

    reasons = []

    frequency = context["frequency"]
    trending = context["trending"]

    # Personal: a dish this guest has actually reordered.
    if signals["category_affinity"] > 0 and item.category:
        ordered_here = sum(
            count
            for name, count in frequency.items()
            if name == item.name
        )

        if ordered_here > 0:
            reasons.append(
                {
                    "kind": "personal",
                    "text": (
                        f"You have ordered {item.name} "
                        f"{ordered_here} time(s) before."
                    ),
                }
            )
        else:
            category_count = context["category_counts"].get(item.category, 0)

            if category_count > 0:
                reasons.append(
                    {
                        "kind": "personal",
                        "text": (
                            f"You often order {item.category} - "
                            f"{category_count} portion(s) so far."
                        ),
                    }
                )

    # Trending: measured across the restaurant today.
    sold_today = trending["quantities"].get(item.name, 0)

    if sold_today > 0:
        reasons.append(
            {
                "kind": "trending",
                "text": f"Trending today - {sold_today} portion(s) sold.",
            }
        )

    # Similarity, but only when the cosine is actually meaningful. A
    # near-zero cosine means "nothing in common", not "a little similar".
    if signals["similarity"] >= 0.15:
        reasons.append(
            {
                "kind": "similar",
                "text": (
                    f"Similar to dishes in your order history"
                    f"{f' ({item.category})' if item.category else ''}."
                ),
            }
        )

    if signals["recency"] >= 0.6 and item.category:
        reasons.append(
            {
                "kind": "recency",
                "text": f"You ordered {item.category} recently.",
            }
        )

    return reasons


def _recommendation_payload(entry: dict, reasons: list, limit_reasons: int = 2) -> dict:
    """The wire shape for one recommended dish."""
    item = entry["menu"]

    return {
        "menu_id": item.id,
        "name": item.name,
        "category": item.category,
        "price": round(_to_float(item.price), 2),
        "availability": bool(item.available),
        "score": entry["score"],
        # The raw components, so a ranking can be audited rather than
        # taken on trust.
        "score_breakdown": entry["signals"],
        "reasons": reasons[:limit_reasons],
        "reason": (
            reasons[0]["text"] if reasons else "Available and on today's menu"
        ),
        "image_url": item.image_url,
        "is_vegetarian": bool(item.is_vegetarian),
        "prep_time": item.prep_time,
    }


def recommend_for_user(
    db: Session,
    user_id: int,
    top_n: int = DEFAULT_TOP_N,
) -> dict:
    """
    Recommendations for the account identified by `user_id`.

    Only available dishes are ever returned: an unavailable dish is
    filtered out before scoring, so it cannot appear under any heading.
    """
    top_n = max(1, min(int(top_n or DEFAULT_TOP_N), 25))

    menu_items = db.query(Menu).filter(Menu.available.is_(True)).all()

    if not menu_items:
        return {
            "personalized": [],
            "trending_today": [],
            "similar_items": [],
            "has_history": False,
            "orders_analyzed": 0,
            "reason": (
                "No dishes are currently available, so there is "
                "nothing to recommend right now."
            ),
            "generated_from": {
                "customer_history": False,
                "today_sales": False,
                "menu_similarity": False,
            },
            "scoring": _scoring_metadata(False),
            "limitations": ["The menu currently has no available dishes."],
        }

    context = score_dishes(db, user_id, menu_items)

    scored = context["scored"]
    history = context["history"]
    trending = context["trending"]
    has_history = context["has_history"]

    menu_by_name = {item.name: item for item in menu_items}

    # Portions this guest has ordered per category, for the reason text.
    category_counts = Counter()

    for order in history:
        item = menu_by_name.get(order.menu_item)

        if item and item.category:
            category_counts[item.category] += order.quantity or 1

    context["category_counts"] = category_counts

    # ---- trending today: real sales, independent of the guest ----
    trending_today = []

    for name, quantity in sorted(
        trending["quantities"].items(),
        key=lambda pair: pair[1],
        reverse=True,
    ):
        item = menu_by_name.get(name)

        # Only dishes that are actually on the menu and orderable.
        if not item:
            continue

        trending_today.append(
            {
                "menu_id": item.id,
                "name": item.name,
                "category": item.category,
                "price": round(_to_float(item.price), 2),
                "availability": True,
                "portions_sold_today": quantity,
                "score": round(trending["normalized"].get(name, 0.0), 4),
                "reason": f"{quantity} portion(s) sold today.",
            }
        )

    trending_today = trending_today[:top_n]

    # ---- personalized: the scored ranking ----
    ranked = sorted(scored, key=lambda entry: entry["score"], reverse=True)

    with_reasons = []

    for entry in ranked:
        reasons = build_reasons(entry, context)

        # A dish with neither evidence nor a meaningful score is padding.
        if not reasons and entry["score"] < MIN_SCORE:
            continue

        with_reasons.append(_recommendation_payload(entry, reasons))

    personalized = with_reasons[:top_n]

    # ---- similar: purely content-based, for guests with history ----
    similar_items = []

    if has_history:
        similarity_ranked = sorted(
            scored,
            key=lambda entry: entry["signals"]["similarity"],
            reverse=True,
        )

        for entry in similarity_ranked:
            if entry["signals"]["similarity"] < 0.15:
                continue

            similar_items.append(
                {
                    "menu_id": entry["menu"].id,
                    "name": entry["menu"].name,
                    "category": entry["menu"].category,
                    "price": round(_to_float(entry["menu"].price), 2),
                    "availability": True,
                    "similarity": entry["signals"]["similarity"],
                    "score": entry["signals"]["similarity"],
                    "reason": (
                        "Text-similar to dishes in your order history."
                    ),
                }
            )

            if len(similar_items) >= top_n:
                break

    # ---- how the answer was reached, stated honestly ----
    limitations = []

    if not has_history:
        limitations.append(
            "You have no previous orders linked to this account, so "
            "recommendations are based on what the restaurant is selling "
            "today rather than on your own history."
        )

    if not trending["total_portions"]:
        limitations.append(
            "No orders have been recorded today, so there is no trending "
            "signal to use."
        )

    if has_history and not similar_items:
        limitations.append(
            "No dish in the menu is textually similar to your past orders."
        )

    if not personalized:
        limitations.append(
            "No dish scored highly enough to recommend right now."
        )

    return {
        "personalized": personalized,
        "trending_today": trending_today,
        "similar_items": similar_items,
        "has_history": has_history,
        "orders_analyzed": len(history),
        "distinct_dishes_ordered": len(context["frequency"]),
        "today": {
            "date": trending["date"],
            "total_portions_sold": trending["total_portions"],
        },
        "reason": _headline(has_history, len(history), trending, personalized),
        "generated_from": {
            "customer_history": has_history,
            "today_sales": trending["total_portions"] > 0,
            "menu_similarity": bool(similar_items),
        },
        "scoring": _scoring_metadata(has_history),
        "limitations": limitations,
    }


def _headline(has_history: bool, order_count: int, trending: dict,
              personalized: list) -> str:
    """One honest sentence about how the list was produced."""
    if has_history:
        return (
            f"Ranked from your {order_count} previous order(s) and "
            f"what is selling today."
        )

    if trending["total_portions"]:
        return (
            "You have no order history yet, so these come from what the "
            "restaurant is selling today."
        )

    if personalized:
        return (
            "You have no order history and nothing has sold today, so "
            "these are simply the available dishes."
        )

    return "No recommendations could be generated from current data."


def _scoring_metadata(has_history: bool) -> dict:
    """
    The weights, returned so the score on screen is explainable.

    `score_is_confidence` is False by design: this is a ranking score,
    not a calibrated probability, and the API says so explicitly.
    """
    return {
        "weights": dict(WEIGHTS),
        "score_range": [0.0, 1.0],
        "score_is_confidence": False,
        "method": (
            "weighted blend of category affinity, today's popularity, "
            "TF-IDF similarity, recency decay and discovery"
        ),
        "uses_customer_history": has_history,
    }

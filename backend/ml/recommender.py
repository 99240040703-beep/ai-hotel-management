"""
Food Recommendation module.

Recommends dishes based on previous orders, customer
preferences, popular dishes, food category and rating/feedback.

Hybrid approach:
  * Content-based  -> TF-IDF over (dish name + category), cosine similarity
                      against the customer's previously ordered dishes.
  * Popularity     -> order frequency, used for new customers (cold start)
                      and to break ties.
"""

from collections import Counter

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


def _dish_profile(item) -> str:
    """Text profile of a menu item for TF-IDF."""
    return f"{item.name} {item.category or ''}".lower()


def popular_dishes(orders, top_n: int = 5) -> list:
    """Most frequently ordered dishes (handles quantity)."""
    counter = Counter()

    for order in orders:
        counter[order.menu_item] += order.quantity or 1

    return [
        {"menu_item": name, "times_ordered": int(count)}
        for name, count in counter.most_common(top_n)
    ]


def recommend_for_customer(
    customer_name: str,
    menu_items: list,
    orders: list,
    top_n: int = 5,
) -> dict:
    """
    Returns recommended dishes for one customer.

    menu_items : list of Menu ORM objects
    orders     : list of Order ORM objects (all customers)
    """
    available = [m for m in menu_items if m.available]

    if not available:
        return {
            "customer": customer_name,
            "strategy": "none",
            "recommendations": [],
            "message": "No menu items available.",
        }

    history = [
        o.menu_item for o in orders
        if (o.customer_name or "").lower() == customer_name.lower()
    ]

    # ---------- Cold start: no order history ----------
    if not history:
        popular = popular_dishes(orders, top_n)

        if popular:
            recommendations = [
                {
                    "menu_item": p["menu_item"],
                    "reason": (
                        f"Popular choice - ordered "
                        f"{p['times_ordered']} times"
                    ),
                    "score": 1.0,
                }
                for p in popular
            ]
        else:
            recommendations = [
                {
                    "menu_item": m.name,
                    "reason": "New on the menu",
                    "score": 0.5,
                }
                for m in available[:top_n]
            ]

        return {
            "customer": customer_name,
            "strategy": "popularity (new customer)",
            "recommendations": recommendations,
        }

    # ---------- Content-based filtering ----------
    corpus = [_dish_profile(m) for m in available]

    vectorizer = TfidfVectorizer(stop_words="english")
    matrix = vectorizer.fit_transform(corpus)

    # Build one profile vector from everything the customer ordered
    profile_text = " ".join(history).lower()
    profile_vector = vectorizer.transform([profile_text])

    scores = cosine_similarity(profile_vector, matrix)[0]

    already_ordered = {h.lower() for h in history}
    frequency = Counter(h.lower() for h in history)

    unseen = [
        (item, float(score))
        for item, score in zip(available, scores)
        if item.name.lower() not in already_ordered
    ]

    # If the customer has already tried the whole menu, fall back to
    # re-suggesting their best matches instead of returning nothing.
    ranked = unseen or [
        (item, float(score))
        for item, score in zip(available, scores)
    ]

    ranked.sort(key=lambda pair: pair[1], reverse=True)

    recommendations = []

    for item, score in ranked[:top_n]:
        if score > 0.15:
            reason = (
                f"Similar to your past orders in "
                f"{item.category or 'this category'}"
            )
        else:
            reason = "Try something different from our menu"

        recommendations.append({
            "menu_item": item.name,
            "category": item.category,
            "price": float(item.price or 0),
            "reason": reason,
            "score": round(score, 3),
        })

    favourite = frequency.most_common(1)[0][0] if frequency else None

    return {
        "customer": customer_name,
        "strategy": "content-based (TF-IDF + cosine similarity)",
        "orders_analyzed": len(history),
        "favourite_dish": favourite,
        "recommendations": recommendations,
    }

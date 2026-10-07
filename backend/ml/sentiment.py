"""
Sentiment Analysis module.

Customer reviews -> NLP -> Positive / Negative / Neutral

Implementation: CountVectorizer (bag of words, 1-2 grams) + Multinomial
Naive Bayes, trained once on a small labelled seed corpus of restaurant
review sentences.  The model is cached in memory after the first call.
"""

from sklearn.feature_extraction.text import CountVectorizer
from sklearn.naive_bayes import MultinomialNB
from sklearn.pipeline import Pipeline

# ---------------------------------------------------------------
# Seed training corpus
# ---------------------------------------------------------------

POSITIVE = [
    "the food was delicious and fresh",
    "excellent service and tasty biryani",
    "amazing taste, will visit again",
    "loved the ambience and quick service",
    "best restaurant in the city",
    "very good quality and worth the price",
    "friendly staff and hot fresh food",
    "the dessert was wonderful",
    "great experience, highly recommended",
    "perfectly cooked and well presented",
    "value for money and clean place",
    "super tasty, my family enjoyed it",
]

NEGATIVE = [
    "the food was cold and stale",
    "very bad service, waited one hour",
    "too salty and oily, not edible",
    "worst experience, rude staff",
    "overpriced and poor quality",
    "the chicken was undercooked",
    "dirty tables and slow service",
    "disappointed with the taste",
    "never coming back to this place",
    "the order was wrong and late",
    "bad smell from the kitchen",
    "terrible food, waste of money",
]

NEUTRAL = [
    "the food was okay nothing special",
    "average taste, normal service",
    "it was fine but could be better",
    "decent place, ordinary food",
    "not bad not good, just average",
    "the portion size was standard",
    "regular quality as expected",
    "service was acceptable",
]

_TEXTS = POSITIVE + NEGATIVE + NEUTRAL
_LABELS = (
    ["Positive"] * len(POSITIVE)
    + ["Negative"] * len(NEGATIVE)
    + ["Neutral"] * len(NEUTRAL)
)

_model = None


def _get_model() -> Pipeline:
    """Build and cache the pipeline on first use."""
    global _model

    if _model is None:
        _model = Pipeline([
            ("vectorizer", CountVectorizer(ngram_range=(1, 2))),
            ("classifier", MultinomialNB(alpha=0.3)),
        ])
        _model.fit(_TEXTS, _LABELS)

    return _model


def analyze_sentiment(text: str) -> dict:
    """Classify one review. Returns label + confidence."""
    if not text or not text.strip():
        return {"sentiment": "Neutral", "score": 0.0}

    model = _get_model()

    label = str(model.predict([text])[0])
    confidence = float(max(model.predict_proba([text])[0]))

    # score: +confidence for positive, -confidence for negative
    score = confidence
    if label == "Negative":
        score = -confidence
    elif label == "Neutral":
        score = 0.0

    return {
        "sentiment": label,
        "score": round(score, 3),
        "confidence": round(confidence, 3),
    }


def summarize_reviews(reviews: list) -> dict:
    """
    Aggregate sentiment over a list of Review ORM objects.
    Used by the admin dashboard.
    """
    total = len(reviews)

    if total == 0:
        return {
            "total_reviews": 0,
            "positive": 0,
            "negative": 0,
            "neutral": 0,
            "positive_percentage": 0.0,
            "average_rating": 0.0,
            "overall": "No reviews yet",
            "top_complaints": [],
        }

    counts = {"Positive": 0, "Negative": 0, "Neutral": 0}
    ratings = []
    complaints = []

    for review in reviews:
        label = review.sentiment or analyze_sentiment(
            review.comment
        )["sentiment"]

        counts[label] = counts.get(label, 0) + 1

        if review.rating:
            ratings.append(review.rating)

        if label == "Negative":
            complaints.append({
                "menu_item": review.menu_item,
                "comment": review.comment,
                "rating": review.rating,
            })

    positive_pct = counts["Positive"] / total * 100

    if positive_pct >= 70:
        overall = "Customers are largely satisfied"
    elif positive_pct >= 40:
        overall = "Mixed customer feedback"
    else:
        overall = "Customer satisfaction needs attention"

    return {
        "total_reviews": total,
        "positive": counts["Positive"],
        "negative": counts["Negative"],
        "neutral": counts["Neutral"],
        "positive_percentage": round(positive_pct, 2),
        "average_rating": round(
            sum(ratings) / len(ratings), 2
        ) if ratings else 0.0,
        "overall": overall,
        "top_complaints": complaints[:5],
    }

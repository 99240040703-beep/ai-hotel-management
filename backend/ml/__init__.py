"""AI / Machine-Learning engine for the restaurant management system."""

from .recommender import recommend_for_customer, popular_dishes
from .sentiment import analyze_sentiment, summarize_reviews
from .forecasting import predict_demand, predict_revenue
from .waste import analyze_waste
from .pricing import suggest_prices

__all__ = [
    "recommend_for_customer",
    "popular_dishes",
    "analyze_sentiment",
    "summarize_reviews",
    "predict_demand",
    "predict_revenue",
    "analyze_waste",
    "suggest_prices",
]

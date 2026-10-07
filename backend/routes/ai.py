"""
AI / ML endpoints.

One endpoint per AI component from the presentation:
  1. /ai/recommend/{customer_name}   Food Recommendation
  2. /ai/sentiment  +  /ai/sentiment/summary   Sentiment Analysis
  3. /ai/demand-forecast             Demand Prediction
  4. /ai/revenue-forecast            Revenue Prediction
  5. /ai/waste-analysis              Waste Analysis
  6. /ai/dynamic-pricing             Dynamic Pricing
  7. /ai/insights                    Combined dashboard summary
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

try:
    from database import get_db
    from middleware.auth import require_current_user, require_admin
except (ImportError, ValueError):
    from ..database import get_db
    from ..middleware.auth import require_current_user, require_admin
from models import Menu, Order, Review, Waste, Inventory
from schemas import SentimentRequest

from crud import (
    get_total_revenue,
    get_total_orders,
    get_total_customers,
    get_total_reservations,
    get_low_stock_items,
)

from ml.recommender import recommend_for_customer, popular_dishes
from ml.sentiment import analyze_sentiment, summarize_reviews
from ml.forecasting import predict_demand, predict_revenue
from ml.waste import analyze_waste
from ml.pricing import suggest_prices

from schemas import AssistantQuestion, AssistantResponse, PersonalizedRecommendation
from schemas import OperationsAnswer, OperationsQuestion

from services.recommendation_service import recommend_for_user
from services.ai_business_service import answer_question, SUGGESTED_QUESTIONS
from services.ai_operations_service import (
    answer_operations_question,
    new_session,
)
from services.restaurant_tools import capabilities as tool_capabilities

router = APIRouter(prefix="/ai", tags=["AI & Machine Learning"])


# =========================================================
# PHASE 5 - PERSONALIZED RECOMMENDATIONS FOR THE SIGNED-IN GUEST
#
# There is no customer id, name or email in the request. The account is
# taken from the verified JWT, so a guest can only ever be shown their
# own history - there is nothing to tamper with.
# =========================================================

@router.get("/recommend/me", response_model=PersonalizedRecommendation)
def my_recommendations(
    limit: int = 8,
    db: Session = Depends(get_db),
    current_user=Depends(require_current_user),
):
    """
    Recommendations for whoever is signed in.

    Only currently available dishes are returned. Every recommendation
    carries the score components that produced it, and `reason` is only
    populated when there is real evidence behind it.

    `scoring.score_is_confidence` is False: the score is a ranking value,
    not a calibrated probability, and this system does not display a
    confidence percentage it has not computed.
    """
    limit = max(1, min(int(limit or 8), 25))

    return recommend_for_user(
        db,
        user_id=current_user["user_id"],
        top_n=limit,
    )


# =========================================================
# PHASE 5 - ADMIN AI BUSINESS ASSISTANT
#
# Deterministic: the question is matched to a fixed intent, the numbers
# come from analytics_service, and the sentence is assembled from those
# numbers. An unrecognised question is refused with no figures at all.
# =========================================================

@router.post("/assistant", response_model=AssistantResponse)
def ask_business_question(
    payload: AssistantQuestion,
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    """Answer one business question from real database figures."""
    return answer_question(db, payload.question)


@router.get("/assistant/suggestions")
def assistant_suggestions(
    current_admin=Depends(require_admin),
):
    """The questions the assistant is known to answer."""
    return {
        "suggestions": SUGGESTED_QUESTIONS,
    }


# =========================================================
# PHASE 6B - RESTAURANT-WIDE AI OPERATIONS ASSISTANT
#
# The endpoint above answers one of fifteen closed intents. This one
# answers open questions: it works out which period the question is about,
# selects whichever data sources that implies, reads them, and composes an
# answer from validated values.
#
# It is a separate route on purpose. `/assistant` above keeps its exact
# Phase 5 contract, including its `intent` field, so nothing that depends
# on it changes behaviour.
#
# Authorization is `require_admin`, the same dependency every other admin
# analytics route uses. A customer token is refused here with 403 and an
# anonymous request with 401, before any restaurant data is read - the
# check is a route dependency, so it cannot be bypassed by a client that
# simply does not send it.
# =========================================================

@router.post("/assistant/ask", response_model=OperationsAnswer)
def ask_restaurant_question(
    payload: OperationsQuestion,
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    """
    Answer any question about the restaurant that the recorded data can
    support.

    Returns the answer plus, deliberately, everything behind it: which
    period it describes, which domains were identified, which data sources
    actually contributed, which returned nothing, and what could not be
    answered. A client can therefore always show the provenance of a
    number, and can never be handed a number with nothing behind it.
    """
    return answer_operations_question(
        db,
        payload.question,
        context=payload.context,
    )


@router.get("/assistant/context")
def start_assistant_conversation(
    current_admin=Depends(require_admin),
):
    """
    Begin a conversation.

    Returns an empty context to send back with the first question. There
    is no server-side session to leak or to expire: the client holds the
    context and the server has no record of it.
    """
    return {"context": new_session()}


@router.get("/assistant/capabilities")
def assistant_capabilities(
    current_admin=Depends(require_admin),
):
    """
    What the assistant can actually reach.

    Documentation, not a menu. The admin never chooses from this - the
    assistant picks its own data sources. It exists so an operator can
    audit which data sources exist and which of them are honest about
    gaps. It lists tool names and descriptions only: no configuration, no
    credentials, no query.
    """
    return {
        "capabilities": tool_capabilities(),
        "count": len(tool_capabilities()),
        "note": (
            "The assistant selects these automatically. This list is here "
            "for auditing, not for choosing."
        ),
    }



# =========================================================
# 1. FOOD RECOMMENDATION
# =========================================================

@router.get("/recommend/{customer_name}")
def food_recommendation(
    customer_name: str,
    top_n: int = 5,
    db: Session = Depends(get_db),
    current_user=Depends(require_current_user),
):
    """
    Recommendations for one guest.

    A customer token always resolves to that customer's own history, so
    the name in the path cannot be used to read someone else's taste
    profile. An admin may query any customer by name.
    """
    target = customer_name

    if current_user["role"] != "admin":
        target = current_user["user_name"]

    return recommend_for_customer(
        customer_name=target,
        menu_items=db.query(Menu).all(),
        orders=db.query(Order).all(),
        top_n=top_n,
    )


@router.get("/popular-dishes")
def trending_dishes(
    top_n: int = 5,
    db: Session = Depends(get_db),
    current_user=Depends(require_current_user),
):
    return {
        "popular_dishes": popular_dishes(db.query(Order).all(), top_n)
    }


# =========================================================
# 2. SENTIMENT ANALYSIS
# =========================================================

@router.post("/sentiment")
def classify_text(
    data: SentimentRequest,
    current_user=Depends(require_current_user),
):
    """Classify any free-text review without storing it."""
    return analyze_sentiment(data.text)


@router.get("/sentiment/summary")
def sentiment_summary(
    db: Session = Depends(get_db),
    current_user=Depends(require_current_user),
):
    return summarize_reviews(db.query(Review).all())


# =========================================================
# 3. DEMAND PREDICTION
# ADMIN ONLY
# =========================================================

@router.get("/demand-forecast")
def demand_forecast(
    days_ahead: int = 7,
    top_n: int = 5,
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    return predict_demand(
        db.query(Order).all(),
        days_ahead=days_ahead,
        top_n=top_n,
    )


# =========================================================
# 4. REVENUE PREDICTION
# ADMIN ONLY
# =========================================================

@router.get("/revenue-forecast")
def revenue_forecast(
    days_ahead: int = 7,
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    return predict_revenue(
        db.query(Order).all(),
        days_ahead=days_ahead,
    )


# =========================================================
# 5. WASTE ANALYSIS
# ADMIN ONLY
# =========================================================

@router.get("/waste-analysis")
def ai_waste_analysis(
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    return analyze_waste(
        db.query(Waste).all(),
        db.query(Order).all(),
    )


# =========================================================
# 6. DYNAMIC PRICING
# ADMIN ONLY
# =========================================================

@router.get("/dynamic-pricing")
def dynamic_pricing(
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    return suggest_prices(
        menu_items=db.query(Menu).all(),
        orders=db.query(Order).all(),
        inventory=db.query(Inventory).all(),
    )


# =========================================================
# 7. COMBINED INSIGHTS  (admin dashboard)
# ADMIN ONLY
# =========================================================

@router.get("/insights")
def get_ai_insights(
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    orders = db.query(Order).all()

    revenue = get_total_revenue(db)
    order_count = get_total_orders(db)
    customers = get_total_customers(db)
    reservations = get_total_reservations(db)
    low_stock = get_low_stock_items(db)

    sentiment = summarize_reviews(db.query(Review).all())
    forecast = predict_revenue(orders, days_ahead=7)
    demand = predict_demand(orders, days_ahead=7, top_n=3)
    waste = analyze_waste(db.query(Waste).all(), orders)

    insights = []

    if order_count > 0:
        insights.append(
            f"Average order value is ₹{revenue / order_count:.2f} "
            f"across {order_count} orders."
        )
    else:
        insights.append("No orders have been recorded yet.")

    insights.append(
        f"Predicted revenue for the next 7 days is "
        f"₹{forecast.get('predicted_total_revenue', 0):.2f}. "
        f"{forecast.get('outlook', '')}"
    )

    if demand.get("forecast"):
        top = demand["forecast"][0]
        insights.append(
            f"'{top['menu_item']}' shows a {top['trend']} demand trend "
            f"- about {top['predicted_total']:.0f} units expected "
            f"this week."
        )

    if sentiment["total_reviews"] > 0:
        insights.append(
            f"{sentiment['positive_percentage']}% of "
            f"{sentiment['total_reviews']} reviews are positive. "
            f"{sentiment['overall']}."
        )
    else:
        insights.append("No customer reviews collected yet.")

    if waste.get("total_waste_quantity", 0) > 0:
        insights.append(
            f"Recorded food waste costs ₹"
            f"{waste['total_waste_cost']:.2f}; about "
            f"{waste['predicted_next_week_quantity']:.1f} units are "
            f"predicted for next week."
        )

    if low_stock:
        insights.append(
            f"{len(low_stock)} inventory items are at or below "
            f"minimum stock and need reordering."
        )
    else:
        insights.append("Inventory levels are currently healthy.")

    return {
        "revenue": revenue,
        "orders": order_count,
        "customers": customers,
        "reservations": reservations,
        "low_stock_count": len(low_stock),
        "sentiment": sentiment,
        "revenue_forecast": forecast,
        "demand_forecast": demand,
        "waste": waste,
        "insights": insights,
    }
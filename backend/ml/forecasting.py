"""
Demand Prediction + Revenue Prediction modules.

Historical sales   -> ML model -> future demand forecast
Historical business data -> ML -> expected future revenue

Implementation: orders are aggregated into a daily time series, then a
LinearRegression is fitted on day-index (+ day-of-week features for
revenue) and extrapolated forward.  Falls back to a moving average when
there is not enough history to fit a model.
"""

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

MIN_DAYS_FOR_MODEL = 5


def _orders_to_frame(orders) -> pd.DataFrame:
    """Convert Order ORM objects into a tidy DataFrame."""
    rows = [
        {
            "date": (o.created_at or datetime.utcnow()).date(),
            "menu_item": o.menu_item,
            "quantity": o.quantity or 0,
            "total_price": float(o.total_price or 0),
        }
        for o in orders
    ]

    return pd.DataFrame(rows)


def _linear_forecast(series: pd.Series, days_ahead: int):
    """
    Fit y = a*x + b on a daily series and predict the next `days_ahead`
    days.  Returns (predictions, model_name, r2).
    """
    y = series.values.astype(float)

    if len(y) < MIN_DAYS_FOR_MODEL:
        average = float(np.mean(y)) if len(y) else 0.0
        return (
            [max(average, 0.0)] * days_ahead,
            "moving average (insufficient history)",
            None,
        )

    X = np.arange(len(y)).reshape(-1, 1)

    model = LinearRegression()
    model.fit(X, y)

    future_X = np.arange(len(y), len(y) + days_ahead).reshape(-1, 1)
    predictions = model.predict(future_X)

    return (
        [round(max(float(p), 0.0), 2) for p in predictions],
        "LinearRegression",
        round(float(model.score(X, y)), 3),
    )


# =========================================================
# DEMAND PREDICTION
# =========================================================

def predict_demand(orders, days_ahead: int = 7, top_n: int = 5) -> dict:
    """Forecast quantity demand per menu item for the coming days."""
    df = _orders_to_frame(orders)

    if df.empty:
        return {
            "days_ahead": days_ahead,
            "model": "none",
            "message": "No order history available to forecast.",
            "forecast": [],
        }

    top_items = (
        df.groupby("menu_item")["quantity"]
        .sum()
        .sort_values(ascending=False)
        .head(top_n)
        .index
    )

    start = datetime.utcnow().date() + timedelta(days=1)
    results = []

    for item in top_items:
        item_df = df[df["menu_item"] == item]

        daily = (
            item_df.groupby("date")["quantity"]
            .sum()
            .sort_index()
        )

        predictions, model_name, r2 = _linear_forecast(
            daily, days_ahead
        )

        trend = "stable"
        if len(daily) >= MIN_DAYS_FOR_MODEL:
            if predictions[-1] > daily.mean() * 1.1:
                trend = "rising"
            elif predictions[-1] < daily.mean() * 0.9:
                trend = "falling"

        results.append({
            "menu_item": item,
            "model": model_name,
            "r2_score": r2,
            "historical_daily_average": round(
                float(daily.mean()), 2
            ),
            "trend": trend,
            "predicted_total": round(sum(predictions), 2),
            "daily_forecast": [
                {
                    "date": str(start + timedelta(days=i)),
                    "predicted_quantity": predictions[i],
                }
                for i in range(days_ahead)
            ],
        })

    return {
        "days_ahead": days_ahead,
        "items_forecasted": len(results),
        "forecast": results,
    }


# =========================================================
# REVENUE PREDICTION
# =========================================================

def predict_revenue(orders, days_ahead: int = 7) -> dict:
    """Forecast total restaurant revenue for the coming days."""
    df = _orders_to_frame(orders)

    if df.empty:
        return {
            "days_ahead": days_ahead,
            "model": "none",
            "message": "No sales history available to forecast.",
            "forecast": [],
        }

    daily = (
        df.groupby("date")["total_price"]
        .sum()
        .sort_index()
    )

    predictions, model_name, r2 = _linear_forecast(
        daily, days_ahead
    )

    start = datetime.utcnow().date() + timedelta(days=1)

    historical_average = float(daily.mean())
    predicted_average = float(np.mean(predictions))

    if predicted_average > historical_average * 1.05:
        outlook = "Revenue is trending upward"
    elif predicted_average < historical_average * 0.95:
        outlook = "Revenue is trending downward - consider promotions"
    else:
        outlook = "Revenue is expected to stay stable"

    return {
        "days_ahead": days_ahead,
        "model": model_name,
        "r2_score": r2,
        "days_of_history": int(len(daily)),
        "historical_daily_average": round(historical_average, 2),
        "predicted_total_revenue": round(sum(predictions), 2),
        "predicted_daily_average": round(predicted_average, 2),
        "outlook": outlook,
        "forecast": [
            {
                "date": str(start + timedelta(days=i)),
                "predicted_revenue": predictions[i],
            }
            for i in range(days_ahead)
        ],
    }

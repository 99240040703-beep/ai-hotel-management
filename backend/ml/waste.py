"""
Food Waste Analysis module.

Turns inventory + sales + waste data into waste patterns and
reduction insights.

Implementation:
  * Pattern mining  -> pandas aggregation by item, reason and weekday.
  * Prediction      -> RandomForestRegressor on (day-index, weekday)
                       to estimate next week's waste quantity.
"""

from datetime import datetime

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor

MIN_RECORDS_FOR_MODEL = 8


def _waste_to_frame(records) -> pd.DataFrame:
    rows = [
        {
            "date": (w.recorded_at or datetime.utcnow()).date(),
            "item_name": w.item_name,
            "quantity": float(w.quantity or 0),
            "reason": w.reason or "Unspecified",
            "cost": float(w.cost or 0),
        }
        for w in records
    ]

    return pd.DataFrame(rows)


def analyze_waste(waste_records, orders=None) -> dict:
    """Full waste report: patterns, cost impact, prediction, actions."""
    df = _waste_to_frame(waste_records)

    if df.empty:
        return {
            "total_waste_quantity": 0.0,
            "total_waste_cost": 0.0,
            "message": "No waste records available.",
            "patterns": {},
            "recommendations": [],
        }

    df["date"] = pd.to_datetime(df["date"])
    df["weekday"] = df["date"].dt.day_name()

    # ---------- Patterns ----------
    by_item = (
        df.groupby("item_name")
        .agg(quantity=("quantity", "sum"), cost=("cost", "sum"))
        .sort_values("quantity", ascending=False)
    )

    by_reason = (
        df.groupby("reason")["quantity"].sum()
        .sort_values(ascending=False)
    )

    by_weekday = (
        df.groupby("weekday")["quantity"].sum()
        .sort_values(ascending=False)
    )

    # ---------- Prediction ----------
    daily = (
        df.groupby("date")["quantity"].sum().sort_index()
    )

    if len(daily) >= MIN_RECORDS_FOR_MODEL:
        X = np.column_stack([
            np.arange(len(daily)),
            daily.index.dayofweek.values,
        ])
        y = daily.values

        model = RandomForestRegressor(
            n_estimators=120,
            random_state=42,
        )
        model.fit(X, y)

        future = np.column_stack([
            np.arange(len(daily), len(daily) + 7),
            [(daily.index[-1].dayofweek + i) % 7 for i in range(1, 8)],
        ])

        predicted_week = float(model.predict(future).sum())
        model_name = "RandomForestRegressor"
    else:
        predicted_week = float(daily.mean() * 7) if len(daily) else 0.0
        model_name = "moving average (insufficient history)"

    # ---------- Recommendations ----------
    recommendations = []

    if not by_item.empty:
        worst = by_item.index[0]
        recommendations.append(
            f"'{worst}' accounts for the highest waste "
            f"({by_item.iloc[0]['quantity']:.2f} units) - "
            f"reduce its purchase quantity or portion size."
        )

    if not by_reason.empty:
        recommendations.append(
            f"Most waste is caused by '{by_reason.index[0]}' - "
            f"review the process behind it."
        )

    if not by_weekday.empty:
        recommendations.append(
            f"{by_weekday.index[0]} records the most waste - "
            f"lower prep volume on that day."
        )

    total_cost = float(df["cost"].sum())

    if total_cost > 0:
        recommendations.append(
            f"Total waste cost is Rs.{total_cost:.2f}; a 20% reduction "
            f"would save about Rs.{total_cost * 0.2:.2f}."
        )

    return {
        "total_waste_quantity": round(float(df["quantity"].sum()), 2),
        "total_waste_cost": round(total_cost, 2),
        "records_analyzed": int(len(df)),
        "model": model_name,
        "predicted_next_week_quantity": round(predicted_week, 2),
        "patterns": {
            "by_item": [
                {
                    "item_name": name,
                    "quantity": round(float(row["quantity"]), 2),
                    "cost": round(float(row["cost"]), 2),
                }
                for name, row in by_item.head(5).iterrows()
            ],
            "by_reason": [
                {"reason": r, "quantity": round(float(q), 2)}
                for r, q in by_reason.head(5).items()
            ],
            "by_weekday": [
                {"weekday": d, "quantity": round(float(q), 2)}
                for d, q in by_weekday.items()
            ],
        },
        "recommendations": recommendations,
    }

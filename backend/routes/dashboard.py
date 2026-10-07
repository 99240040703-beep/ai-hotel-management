from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

try:
    from database import get_db
    from middleware.auth import require_admin
except (ImportError, ValueError):
    from ..database import get_db
    from ..middleware.auth import require_admin
from models import Kitchen, Menu, Order, Reservation, Review, User

router = APIRouter(
    prefix="/dashboard",
    tags=["Dashboard"]
)


@router.get("/")
def get_dashboard(
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):

    total_menu_items = db.query(Menu).count()
    total_orders = db.query(Order).count()
    total_reservations = db.query(Reservation).count()
    total_users = db.query(User).count()

    total_revenue = db.query(
        func.sum(Order.total_price)
    ).scalar() or 0

    # Every figure below is measured rather than assumed, so the
    # dashboard has no hardcoded percentages or counts left in it.
    avg_prep_minutes = db.query(
        func.avg(Menu.prep_time)
    ).scalar()

    avg_rating = db.query(
        func.avg(Review.rating)
    ).scalar()

    kitchen_total = db.query(Kitchen).count()

    kitchen_open = (
        db.query(Kitchen)
        .filter(Kitchen.status.notin_(["Served", "Completed", "Cancelled"]))
        .count()
    )

    return {
        "total_menu_items": total_menu_items,
        "total_orders": total_orders,
        "total_reservations": total_reservations,
        "total_users": total_users,
        "total_revenue": float(total_revenue),
        "avg_prep_minutes": (
            round(float(avg_prep_minutes), 1)
            if avg_prep_minutes is not None
            else None
        ),
        "avg_rating": (
            round(float(avg_rating), 2) if avg_rating is not None else None
        ),
        "review_count": db.query(Review).count(),
        "kitchen_total": kitchen_total,
        "kitchen_open": kitchen_open,
        "kitchen_load_pct": (
            round(kitchen_open / kitchen_total * 100)
            if kitchen_total
            else 0
        ),
    }


# =========================================================
# WEEKLY REVENUE
# ADMIN ONLY
#
# A real 7-day revenue series, used by the dashboard chart instead of
# a hardcoded list of numbers.
# =========================================================

@router.get("/weekly")
def get_weekly_revenue(
    days: int = 7,
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    from datetime import date, timedelta

    days = max(2, min(int(days or 7), 90))
    today = date.today()
    start = today - timedelta(days=days - 1)

    rows = (
        db.query(
            func.date(Order.created_at).label("day"),
            func.sum(Order.total_price).label("revenue"),
            func.sum(Order.quantity).label("portions"),
        )
        .filter(Order.created_at >= start)
        .group_by(func.date(Order.created_at))
        .all()
    )

    by_day = {
        row[0]: (float(row[1] or 0), int(row[2] or 0)) for row in rows
    }

    series = []

    for offset in range(days):
        day = start + timedelta(days=offset)
        revenue, portions = by_day.get(day, (0.0, 0))

        series.append(
            {
                "date": day.isoformat(),
                "revenue": round(revenue, 2),
                "portions": portions,
            }
        )

    total = sum(row["revenue"] for row in series)

    return {
        "days": days,
        "series": series,
        "total_revenue": round(total, 2),
        "peak_day": (
            max(series, key=lambda row: row["revenue"])["date"]
            if total
            else None
        ),
    }


# =========================================================
# TOP DISHES
# ADMIN ONLY
#
# Replaces the hardcoded list the dashboard used to render. Every
# figure comes from the orders table, and `price` is joined from
# menu so the dashboard shows the same price the guest is charged.
# A dish that has never been ordered does not appear.
# =========================================================

@router.get("/top-dishes")
def get_top_dishes(
    limit: int = 5,
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    limit = max(1, min(int(limit or 5), 20))

    rows = (
        db.query(
            Order.menu_item,
            func.sum(Order.quantity).label("times_ordered"),
            func.sum(Order.total_price).label("revenue"),
        )
        .group_by(Order.menu_item)
        .order_by(func.sum(Order.quantity).desc())
        .limit(limit)
        .all()
    )

    # Current menu price, so the figure on screen is menu.price and not
    # a historical average.
    prices = {
        row.name: float(row.price or 0)
        for row in db.query(Menu).all()
    }

    dishes = []

    for menu_item, times_ordered, revenue in rows:
        dishes.append(
            {
                "menu_item": menu_item,
                "times_ordered": int(times_ordered or 0),
                "revenue": round(float(revenue or 0), 2),
                # None when the dish has since been removed from the menu.
                "price": prices.get(menu_item),
            }
        )

    return {"top_dishes": dishes}
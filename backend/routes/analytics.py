"""
Admin analytics endpoints.

Every route here requires an admin token. A customer token is refused
with 403 and an anonymous request with 401, so business figures are
never reachable from the customer surface.

The aggregation itself lives in services/analytics_service.py. These
routes only translate HTTP into a service call and declare the response
shape, which keeps the SQL out of the routing layer.
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

try:
    from database import get_db
    from middleware.auth import require_admin
except (ImportError, ValueError):
    from ..database import get_db
    from ..middleware.auth import require_admin

from crud import (
    get_total_revenue,
    get_total_orders,
    get_total_customers,
    get_total_reservations,
    get_total_menu_items,
)

from schemas import (
    AnalyticsOverview,
    CategoryRevenueResponse,
    CustomerSummary,
    InventorySummary,
    OrderStatusSummary,
    RevenueTrend,
    RevenueWindow,
    SalesSummary,
    TopDishesResponse,
    WastageSummary,
)

from services import analytics_service as analytics


router = APIRouter(
    prefix="/analytics",
    tags=["Analytics"],
)


# The keyword ranges a caller may pass. Anything else is rejected rather
# than silently coerced, so a typo cannot quietly return the wrong week.
ALLOWED_RANGES = {
    "today",
    "yesterday",
    "last_7_days",
    "last_30_days",
    "this_week",
    "this_month",
    "all_time",
    "custom",
}


def _clean_range(range_key: str | None, start: str | None,
                 end: str | None) -> str:
    """
    Validate the range arguments.

    An explicit ISO start/end pair is parsed here so a malformed date
    produces a clear 400 instead of a database error.
    """
    if start or end:
        if not (start and end):
            raise HTTPException(
                status_code=400,
                detail="Both start and end are required for a custom range",
            )

        try:
            start_date = date.fromisoformat(start)
            end_date = date.fromisoformat(end)
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=400,
                detail="start and end must be ISO dates (YYYY-MM-DD)",
            )

        if end_date < start_date:
            start_date, end_date = end_date, start_date

        analytics.resolve_range("custom", start_date, end_date)

        return "custom"

    key = (range_key or "last_7_days").strip().lower()

    if key not in ALLOWED_RANGES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported range '{key}'. Use one of: "
                + ", ".join(sorted(ALLOWED_RANGES - {"custom"}))
            ),
        )

    return key


def _clean_limit(limit: int | None, default: int = 5,
                 ceiling: int = 25) -> int:
    try:
        value = int(limit) if limit is not None else default
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="limit must be a whole number")

    return max(1, min(value, ceiling))


# =========================================================
# OVERALL ANALYTICS
# Kept for backwards compatibility with the existing dashboard.
# =========================================================

@router.get("/")
def read_analytics(
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    total_revenue = get_total_revenue(db)

    total_orders = get_total_orders(db)

    total_customers = get_total_customers(db)

    total_reservations = get_total_reservations(db)

    total_menu_items = get_total_menu_items(db)

    average_order_value = 0

    if total_orders > 0:
        average_order_value = (
            total_revenue / total_orders
        )

    return {
        "total_revenue": total_revenue,
        "total_orders": total_orders,
        "total_customers": total_customers,
        "total_reservations": total_reservations,
        "total_menu_items": total_menu_items,
        "average_order_value": average_order_value,
    }


# =========================================================
# PHASE 5 - REAL DASHBOARD OVERVIEW
# =========================================================

@router.get("/overview", response_model=AnalyticsOverview)
def read_overview(
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    """
    Today's measured figures.

    `unpaid_served_orders` is reported as its own number: food status and
    payment status are independent, and a served order is never counted
    as paid on the strength of having been served.
    """
    return analytics.analytics_overview(db)


# =========================================================
# PHASE 5 - REVENUE
# =========================================================

@router.get("/revenue", response_model=RevenueWindow)
def read_revenue(
    range: str | None = None,
    start: str | None = None,
    end: str | None = None,
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    """Totals for one window, with checkout and legacy money split out."""
    key = _clean_range(range, start, end)

    start_date, end_date, label = analytics.resolve_range(
        key,
        date.fromisoformat(start) if start else None,
        date.fromisoformat(end) if end else None,
    )

    window = analytics.revenue_for_window(db, start_date, end_date)

    window["range"] = label

    return window


@router.get("/revenue/trend", response_model=RevenueTrend)
def read_revenue_trend(
    range: str | None = None,
    start: str | None = None,
    end: str | None = None,
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    """
    A daily revenue and order series.

    The frontend renders these rows directly; it does not build the
    series itself. Days with no orders are present as zeros so the x
    axis stays evenly spaced.
    """
    key = _clean_range(range, start, end)

    return analytics.revenue_trend(
        db,
        key,
        date.fromisoformat(start) if start else None,
        date.fromisoformat(end) if end else None,
    )


# =========================================================
# PHASE 5 - SALES
# =========================================================

@router.get("/sales", response_model=SalesSummary)
def read_sales(
    range: str | None = None,
    start: str | None = None,
    end: str | None = None,
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    """Portions, order lines and average values for a window."""
    key = _clean_range(range, start, end)

    return analytics.sales_summary(
        db,
        key,
        date.fromisoformat(start) if start else None,
        date.fromisoformat(end) if end else None,
    )


# =========================================================
# PHASE 5 - TOP DISHES
# =========================================================

@router.get("/top-dishes", response_model=TopDishesResponse)
def read_top_dishes(
    limit: int = 5,
    range: str | None = None,
    start: str | None = None,
    end: str | None = None,
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    """Best sellers by quantity, with the revenue each actually produced."""
    key = _clean_range(range, start, end)

    return analytics.top_dishes(
        db,
        limit=_clean_limit(limit),
        range_key=key,
        start=date.fromisoformat(start) if start else None,
        end=date.fromisoformat(end) if end else None,
    )


@router.get("/revenue-by-category", response_model=CategoryRevenueResponse)
def read_revenue_by_category(
    range: str | None = None,
    start: str | None = None,
    end: str | None = None,
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    """Real revenue grouped by menu category."""
    key = _clean_range(range, start, end)

    return analytics.revenue_by_category(
        db,
        range_key=key,
        start=date.fromisoformat(start) if start else None,
        end=date.fromisoformat(end) if end else None,
    )


# =========================================================
# PHASE 5 - ORDERS
# =========================================================

@router.get("/orders", response_model=OrderStatusSummary)
def read_order_analytics(
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    """
    Lifecycle counts and payment counts as two separate facts.

    Nothing here infers payment from food status.
    """
    return analytics.order_status_summary(db)


# =========================================================
# PHASE 5 - WASTAGE
# =========================================================

@router.get("/wastage", response_model=WastageSummary)
def read_wastage(
    range: str | None = None,
    start: str | None = None,
    end: str | None = None,
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    """Recorded food waste for a window, with a daily trend."""
    key = _clean_range(range, start, end)

    return analytics.wastage_summary(
        db,
        range_key=key,
        start=date.fromisoformat(start) if start else None,
        end=date.fromisoformat(end) if end else None,
    )


# =========================================================
# PHASE 5 - INVENTORY
# =========================================================

@router.get("/inventory", response_model=InventorySummary)
def read_inventory_analytics(
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    """
    Stock counts using the inventory table's own minimum_stock rule.

    available  quantity > minimum_stock
    low_stock  0 < quantity <= minimum_stock
    out        quantity <= 0
    """
    return analytics.inventory_summary(db)


# =========================================================
# PHASE 5 - CUSTOMERS
# =========================================================

@router.get("/customer-summary", response_model=CustomerSummary)
def read_customer_analytics(
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    """Customer records and what can genuinely be attributed to them."""
    return analytics.customer_summary(db)

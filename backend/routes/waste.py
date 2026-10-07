from datetime import date as date_type, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

try:
    from database import get_db
    from middleware.auth import require_admin
except (ImportError, ValueError):
    from ..database import get_db
    from ..middleware.auth import require_admin
from services import event_service
from models import Waste, Order, Menu, Inventory
from schemas import WasteCreate
from ml.waste import analyze_waste

router = APIRouter(prefix="/waste", tags=["Food Waste"])


def _sold_quantities(db: Session, day: date_type):
    """Portions of each dish that were actually ordered on a given day."""
    start = datetime.combine(day, datetime.min.time())
    end = datetime.combine(day, datetime.max.time())

    rows = (
        db.query(Order.menu_item, func.sum(Order.quantity))
        .filter(
            Order.created_at >= start,
            Order.created_at <= end,
        )
        .group_by(Order.menu_item)
        .all()
    )

    return {name: float(total or 0) for name, total in rows}


def _menu_prices(db: Session):
    return {
        item.name: float(item.price or 0)
        for item in db.query(Menu).all()
    }


@router.get("/")
def read_waste(
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    return db.query(Waste).order_by(Waste.id.desc()).all()


@router.post("/")
def add_waste(
    item: WasteCreate,
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    record = Waste(**item.model_dump())

    db.add(record)
    db.commit()
    db.refresh(record)

    # Phase 6C. Waste already keeps its own recorded_at, so this event
    # does not duplicate that history - it exists so that "what has been
    # discarded, and why" is reachable from one event log alongside
    # everything else the assistant reads.
    event_service.record_event(
        db,
        event_service.WASTE_RECORDED,
        event_service.ENTITY_WASTE,
        entity_id=record.id,
        actor_user_id=current_admin["user_id"],
        metadata={
            "item_name": record.item_name,
            "quantity": round(float(record.quantity or 0), 2),
            "unit": record.unit,
            "cost": round(float(record.cost or 0), 2),
            "reason": record.reason,
        },
    )

    try:
        db.commit()
        # A commit expires the instance; FastAPI serialises from __dict__
        # without reloading, so refresh before returning it.
        db.refresh(record)
    except Exception:
        db.rollback()

    return record


@router.get("/analysis")
def waste_analysis(
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    """ML-backed waste patterns, next-week prediction and actions."""
    return analyze_waste(
        db.query(Waste).all(),
        db.query(Order).all(),
    )


# ============================================================
# END OF DAY CLOSING
#
# The kitchen prepares dishes from inventory during the day.  At
# closing time whatever was prepared but never sold is waste.
# This report compares what was prepared against what was ordered
# so the leftover quantity can be recorded against inventory.
# ============================================================
@router.get("/end-of-day")
def end_of_day_report(
    day: date_type = None,
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    target = day or date_type.today()

    sold = _sold_quantities(db, target)
    prices = _menu_prices(db)

    inventory_rows = db.query(Inventory).all()

    inventory_by_name = {
        row.item_name.strip().lower(): row for row in inventory_rows
    }

    dishes = []

    for item in db.query(Menu).all():
        sold_qty = sold.get(item.name, 0.0)
        stock = inventory_by_name.get(item.name.strip().lower())

        dishes.append(
            {
                "item_name": item.name,
                "category": item.category,
                "sold_quantity": sold_qty,
                # Nothing prepared was recorded, so the safest assumption
                # is that only what was ordered actually got made.
                "prepared_quantity": sold_qty,
                "leftover_quantity": 0.0,
                "unit": "portion",
                "unit_cost": float(item.price or 0),
                "estimated_cost": 0.0,
                "inventory_quantity": float(stock.quantity) if stock else None,
                "inventory_unit": stock.unit if stock else None,
            }
        )

    # The kitchen may prepare a dish that never sold, and the waste is
    # per dish so the leftover quantity is only known once prepared is set.
    return {
        "date": target,
        "dishes": dishes,
        "totals": {
            "dishes_sold": sum(row["sold_quantity"] for row in dishes),
            "dishes_prepared": sum(row["prepared_quantity"] for row in dishes),
            "leftover_quantity": 0.0,
            "estimated_cost": 0.0,
        },
        "inventory": [
            {
                "item_name": row.item_name,
                "category": row.category,
                "quantity": float(row.quantity),
                "unit": row.unit,
                "minimum_stock": float(row.minimum_stock or 0),
                "cost_per_unit": float(row.cost_per_unit or 0),
                "is_low": float(row.quantity) <= float(row.minimum_stock or 0),
            }
            for row in inventory_rows
        ],
    }


@router.post("/end-of-day")
def close_day(
    payload: dict,
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    """Record the prepared-but-unsold quantity as waste.

    Body: {"date": "2026-10-03",
           "prepared": [{"item_name": "Paneer Tikka", "quantity": 20}, ...]}
    """
    target = payload.get("date")

    if isinstance(target, str) and target:
        target = date_type.fromisoformat(target)
    else:
        target = date_type.today()

    prepared_rows = payload.get("prepared") or []

    if not prepared_rows:
        raise HTTPException(
            status_code=400,
            detail="prepared quantities are required to close the day",
        )

    sold = _sold_quantities(db, target)
    prices = _menu_prices(db)

    created = []
    skipped = []

    for row in prepared_rows:
        item_name = (row.get("item_name") or "").strip()

        if not item_name:
            continue

        try:
            prepared_qty = float(row.get("quantity") or 0)
        except (TypeError, ValueError):
            prepared_qty = 0.0

        sold_qty = sold.get(item_name, 0.0)
        leftover = round(prepared_qty - sold_qty, 2)

        if leftover <= 0:
            skipped.append(
                {
                    "item_name": item_name,
                    "prepared_quantity": prepared_qty,
                    "sold_quantity": sold_qty,
                    "reason": "nothing left over",
                }
            )
            continue

        unit_cost = prices.get(item_name, 0.0)

        record = Waste(
            item_name=item_name,
            quantity=leftover,
            unit="portion",
            reason=f"End of day leftover ({target.isoformat()})",
            cost=round(leftover * unit_cost, 2),
        )

        db.add(record)
        created.append(
            {
                "item_name": item_name,
                "leftover_quantity": leftover,
                "unit": "portion",
                "cost": round(leftover * unit_cost, 2),
            }
        )

    if not created:
        db.rollback()

        return {
            "date": target,
            "message": "No leftover quantity to record.",
            "created": [],
            "skipped": skipped,
        }

    db.commit()

    return {
        "date": target,
        "message": (
            f"Recorded {len(created)} waste record(s) for "
            f"{target.isoformat()}."
        ),
        "created": created,
        "skipped": skipped,
        "total_leftover": sum(row["leftover_quantity"] for row in created),
        "total_cost": round(sum(row["cost"] for row in created), 2),
    }


@router.delete("/{waste_id}")
def remove_waste(
    waste_id: int,
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    record = db.query(Waste).filter(Waste.id == waste_id).first()

    if not record:
        raise HTTPException(status_code=404, detail="Record not found")

    db.delete(record)
    db.commit()

    return {"message": "Waste record deleted successfully"}

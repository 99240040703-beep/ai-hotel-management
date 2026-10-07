from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

try:
    from database import get_db
    from middleware.auth import require_admin
    from models import Inventory
except (ImportError, ValueError):
    from ..database import get_db
    from ..middleware.auth import require_admin
    from ..models import Inventory

from services import event_service
from crud import (
    get_all_inventory,
    get_inventory_item,
    create_inventory,
    update_inventory,
    delete_inventory,
    get_low_stock_items,
)

from schemas import InventoryCreate


router = APIRouter(
    prefix="/inventory",
    tags=["Inventory"]
)


# =========================================================
# GET ALL INVENTORY
# =========================================================

@router.get("/")
def read_inventory(
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    return get_all_inventory(db)


# =========================================================
# GET LOW STOCK ITEMS
# =========================================================

@router.get("/low-stock")
def read_low_stock(
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    return get_low_stock_items(db)


# =========================================================
# GET INVENTORY ITEM
# =========================================================

@router.get("/{inventory_id}")
def read_inventory_item(
    inventory_id: int,
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    item = get_inventory_item(
        db,
        inventory_id
    )

    if not item:
        raise HTTPException(
            status_code=404,
            detail="Inventory item not found"
        )

    return item


# =========================================================
# CREATE INVENTORY ITEM
# =========================================================

@router.post("/")
def add_inventory(
    item: InventoryCreate,
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    created = create_inventory(db, item)

    # Phase 6C. A first count is a movement from nothing to something,
    # and recording it means "what did we start with" stays answerable.
    event_service.record_event(
        db,
        event_service.INVENTORY_UPDATED,
        event_service.ENTITY_INVENTORY,
        entity_id=created.id,
        actor_user_id=current_admin["user_id"],
        metadata={
            "item_name": created.item_name,
            "previous_quantity": None,
            "new_quantity": round(float(created.quantity or 0), 2),
            "minimum_stock": round(float(created.minimum_stock or 0), 2),
            "unit": created.unit,
            "note": "item created",
        },
    )

    try:
        db.commit()
        # A commit expires the instance; FastAPI serialises from __dict__
        # without reloading, so refresh before returning it.
        db.refresh(created)
    except Exception:
        db.rollback()

    return created


# =========================================================
# UPDATE INVENTORY ITEM
# =========================================================

@router.put("/{inventory_id}")
def edit_inventory(
    inventory_id: int,
    item: InventoryCreate,
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    # Read the current quantity before the write, so the event records a
    # movement rather than just a new number. Without the before value,
    # "what has been restocked this week" has nothing to work with.
    previous = (
        db.query(Inventory)
        .filter(Inventory.id == inventory_id)
        .first()
    )

    previous_quantity = (
        round(float(previous.quantity), 2) if previous else None
    )

    inventory = update_inventory(
        db,
        inventory_id,
        item
    )

    if not inventory:
        raise HTTPException(
            status_code=404,
            detail="Inventory item not found"
        )

    # Phase 6C. Inventory has no movement ledger of its own; the event
    # log is where a change is remembered.
    event_service.record_event(
        db,
        event_service.INVENTORY_UPDATED,
        event_service.ENTITY_INVENTORY,
        entity_id=inventory_id,
        actor_user_id=current_admin["user_id"],
        metadata={
            "item_name": inventory.item_name,
            "previous_quantity": previous_quantity,
            "new_quantity": round(float(inventory.quantity or 0), 2),
            "minimum_stock": round(float(inventory.minimum_stock or 0), 2),
            "unit": inventory.unit,
        },
    )

    try:
        db.commit()
        db.refresh(inventory)
    except Exception:
        db.rollback()

    return inventory


# =========================================================
# DELETE INVENTORY ITEM
# =========================================================

@router.delete("/{inventory_id}")
def remove_inventory(
    inventory_id: int,
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    inventory = delete_inventory(
        db,
        inventory_id
    )

    if not inventory:
        raise HTTPException(
            status_code=404,
            detail="Inventory item not found"
        )

    return {
        "message": "Inventory item deleted successfully"
    }
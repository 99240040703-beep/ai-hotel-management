from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

try:
    from database import get_db
    from middleware.auth import require_admin
except (ImportError, ValueError):
    from ..database import get_db
    from ..middleware.auth import require_admin

from crud import (
    get_all_kitchen_orders,
    get_kitchen_order,
    create_kitchen_order,
    update_kitchen_order,
    delete_kitchen_order,
    get_kitchen_orders_by_status,
)

from schemas import (
    KitchenCreate,
    KitchenUpdate,
)


router = APIRouter(
    prefix="/kitchen",
    tags=["Kitchen"]
)


# =========================================================
# GET ALL KITCHEN ORDERS
# =========================================================

@router.get("/")
def read_kitchen_orders(
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    return get_all_kitchen_orders(db)


# =========================================================
# GET ORDERS BY STATUS
# =========================================================

@router.get("/status/{status}")
def read_kitchen_orders_by_status(
    status: str,
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    return get_kitchen_orders_by_status(
        db,
        status
    )


# =========================================================
# GET SINGLE KITCHEN ORDER
# =========================================================

@router.get("/{kitchen_id}")
def read_kitchen_order(
    kitchen_id: int,
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    order = get_kitchen_order(
        db,
        kitchen_id
    )

    if not order:
        raise HTTPException(
            status_code=404,
            detail="Kitchen order not found"
        )

    return order


# =========================================================
# CREATE KITCHEN ORDER
# =========================================================

@router.post("/")
def add_kitchen_order(
    item: KitchenCreate,
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    return create_kitchen_order(
        db,
        item
    )


# =========================================================
# UPDATE KITCHEN ORDER
# =========================================================

@router.put("/{kitchen_id}")
def edit_kitchen_order(
    kitchen_id: int,
    item: KitchenUpdate,
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    order = update_kitchen_order(
        db,
        kitchen_id,
        item
    )

    if not order:
        raise HTTPException(
            status_code=404,
            detail="Kitchen order not found"
        )

    return order


# =========================================================
# DELETE KITCHEN ORDER
# =========================================================

@router.delete("/{kitchen_id}")
def remove_kitchen_order(
    kitchen_id: int,
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    order = delete_kitchen_order(
        db,
        kitchen_id
    )

    if not order:
        raise HTTPException(
            status_code=404,
            detail="Kitchen order not found"
        )

    return {
        "message": "Kitchen order deleted successfully"
    }
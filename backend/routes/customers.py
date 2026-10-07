from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

try:
    from database import get_db
    from middleware.auth import require_admin
except (ImportError, ValueError):
    from ..database import get_db
    from ..middleware.auth import require_admin

from crud import (
    get_all_customers,
    get_customer,
    create_customer,
    update_customer,
    delete_customer,
)

from schemas import CustomerCreate


router = APIRouter(
    prefix="/customers",
    tags=["Customers"]
)


# =========================================================
# GET ALL CUSTOMERS
# =========================================================

@router.get("/")
def read_customers(
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    return get_all_customers(db)


# =========================================================
# GET ONE CUSTOMER
# =========================================================

@router.get("/{customer_id}")
def read_customer(
    customer_id: int,
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    customer = get_customer(
        db,
        customer_id
    )

    if not customer:
        raise HTTPException(
            status_code=404,
            detail="Customer not found"
        )

    return customer


# =========================================================
# CREATE CUSTOMER
# =========================================================

@router.post("/")
def add_customer(
    item: CustomerCreate,
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    return create_customer(db, item)


# =========================================================
# UPDATE CUSTOMER
# =========================================================

@router.put("/{customer_id}")
def edit_customer(
    customer_id: int,
    item: CustomerCreate,
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    customer = update_customer(
        db,
        customer_id,
        item
    )

    if not customer:
        raise HTTPException(
            status_code=404,
            detail="Customer not found"
        )

    return customer


# =========================================================
# DELETE CUSTOMER
# =========================================================

@router.delete("/{customer_id}")
def remove_customer(
    customer_id: int,
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    customer = delete_customer(
        db,
        customer_id
    )

    if not customer:
        raise HTTPException(
            status_code=404,
            detail="Customer not found"
        )

    return {
        "message": "Customer deleted successfully"
    }
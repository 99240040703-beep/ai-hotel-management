from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

try:
    from database import get_db
    from middleware.auth import require_admin
except (ImportError, ValueError):
    from ..database import get_db
    from ..middleware.auth import require_admin
from models import Supplier
from schemas import SupplierCreate

router = APIRouter(prefix="/suppliers", tags=["Suppliers"])


@router.get("/")
def read_suppliers(
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    return db.query(Supplier).all()


@router.post("/")
def add_supplier(
    item: SupplierCreate,
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    supplier = Supplier(**item.model_dump())

    db.add(supplier)
    db.commit()
    db.refresh(supplier)

    return supplier


@router.put("/{supplier_id}")
def edit_supplier(
    supplier_id: int,
    item: SupplierCreate,
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    supplier = (
        db.query(Supplier).filter(Supplier.id == supplier_id).first()
    )

    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found")

    for key, value in item.model_dump().items():
        setattr(supplier, key, value)

    db.commit()
    db.refresh(supplier)

    return supplier


@router.delete("/{supplier_id}")
def remove_supplier(
    supplier_id: int,
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    supplier = (
        db.query(Supplier).filter(Supplier.id == supplier_id).first()
    )

    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found")

    db.delete(supplier)
    db.commit()

    return {"message": "Supplier deleted successfully"}
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

try:
    from database import get_db
    from middleware.auth import require_admin
except (ImportError, ValueError):
    from ..database import get_db
    from ..middleware.auth import require_admin
from models import Staff
from schemas import StaffCreate

router = APIRouter(prefix="/staff", tags=["Staff Management"])


@router.get("/")
def read_staff(
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    return db.query(Staff).all()


@router.post("/")
def add_staff(
    item: StaffCreate,
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    member = Staff(**item.model_dump())

    db.add(member)
    db.commit()
    db.refresh(member)

    return member


@router.put("/{staff_id}")
def edit_staff(
    staff_id: int,
    item: StaffCreate,
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    member = db.query(Staff).filter(Staff.id == staff_id).first()

    if not member:
        raise HTTPException(status_code=404, detail="Staff not found")

    for key, value in item.model_dump().items():
        setattr(member, key, value)

    db.commit()
    db.refresh(member)

    return member


@router.delete("/{staff_id}")
def remove_staff(
    staff_id: int,
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    member = db.query(Staff).filter(Staff.id == staff_id).first()

    if not member:
        raise HTTPException(status_code=404, detail="Staff not found")

    db.delete(member)
    db.commit()

    return {"message": "Staff removed successfully"}
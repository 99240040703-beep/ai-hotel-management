"""
Table QR and table context.

Three audiences, deliberately separated:

  public   GET  /resolve      a phone reading a QR before signing in
  customer POST /claim        bind the signed-in guest to that table
           POST /context      read back the guest's current table
           POST /release      clear it on sign out
  admin    GET/POST/PUT/DELETE /           manage the dining room
           POST /{id}/regenerate-qr         rotate a printed code

Only the restaurant's table number, capacity and section are public.
A qr_token never appears in a resolve response, so the entry page cannot
be used to walk the token space.
"""

import os

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

try:
    from database import get_db
    from middleware.auth import require_admin, require_current_user
    from models import RestaurantTable, Settings
    from schemas import (
        RestaurantTableCreate,
        RestaurantTableUpdate,
        TableClaimRequest,
    )
    from services.table_service import (
        assign_token_if_missing,
        claim_table,
        generate_table_token,
        get_claimed_table,
        get_table_by_token,
        public_table_info,
        release_table,
        table_qr_payload,
    )
except (ImportError, ValueError):
    from ..database import get_db
    from ..middleware.auth import require_admin, require_current_user
    from ..models import RestaurantTable, Settings
    from ..schemas import (
        RestaurantTableCreate,
        RestaurantTableUpdate,
        TableClaimRequest,
    )
    from ..services.table_service import (
        assign_token_if_missing,
        claim_table,
        generate_table_token,
        get_claimed_table,
        get_table_by_token,
        public_table_info,
        release_table,
        table_qr_payload,
    )


router = APIRouter(prefix="/tables", tags=["Tables & QR"])

# Where the printed QR should point. Configured per environment so no
# production hostname is ever committed to the repository.
DEFAULT_ENTRY_BASE_URL = "http://localhost:5173"


def entry_base_url() -> str:
    return (
        os.getenv("CUSTOMER_ENTRY_BASE_URL") or DEFAULT_ENTRY_BASE_URL
    ).rstrip("/")


def restaurant_name(db: Session):
    settings = db.query(Settings).first()

    return settings.restaurant_name if settings else None


def _validated_table_number(db: Session, value, current_id=None):
    """
    Check a table number is sane and not already taken.

    The unique constraint on the column is the real guarantee; this
    turns the collision into a readable 409 instead of an IntegrityError.
    """
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=400,
            detail="table_number must be a whole number",
        )

    if number < 1:
        raise HTTPException(
            status_code=400,
            detail="table_number must be 1 or greater",
        )

    clash = (
        db.query(RestaurantTable)
        .filter(
            RestaurantTable.table_number == number,
            RestaurantTable.id != current_id,
        )
        .first()
    )

    if clash:
        raise HTTPException(
            status_code=409,
            detail=f"Table number {number} is already in use",
        )

    return number


# ============================================================
# PUBLIC - resolve a scanned QR
# ============================================================
#
# Deliberately unauthenticated: a guest scans before they have an
# account. Only the table's public description comes back.

@router.get("/resolve")
def resolve_table_token(
    table: str = Query(..., description="qr_token from the scanned QR"),
    db: Session = Depends(get_db),
):
    row = get_table_by_token(db, table)

    if not row:
        raise HTTPException(
            status_code=404,
            detail="This QR code is not recognised",
        )

    if not row.is_active:
        raise HTTPException(
            status_code=409,
            detail=f"Table {row.table_number} is not currently accepting orders",
        )

    return {
        "valid": True,
        "table": public_table_info(row, restaurant_name(db)),
    }


# ============================================================
# CUSTOMER - claim and read the table context
# ============================================================

@router.post("/claim")
def claim(
    payload: TableClaimRequest,
    db: Session = Depends(get_db),
    current_user=Depends(require_current_user),
):
    """
    Bind the signed-in guest to the scanned table.

    Authentication is required: a QR identifies a table, not a person.
    The claim is written to the users row, which is what later orders
    are checked against.
    """
    row, error = claim_table(
        db,
        current_user["user_id"],
        payload.table_token,
    )

    if not row:
        # 404 for an unknown token, 409 for a table that is not taking
        # orders, so the guest gets a message they can act on.
        status = 409 if error and "not currently" in error else 404

        raise HTTPException(status_code=status, detail=error)

    return {
        "claimed": True,
        "table": public_table_info(row, restaurant_name(db)),
    }


@router.get("/context")
def read_context(
    db: Session = Depends(get_db),
    current_user=Depends(require_current_user),
):
    """
    The guest's current table, as decided by the server.

    The portal reads this instead of trusting anything the browser kept.
    """
    row = get_claimed_table(db, current_user["user_id"])

    if not row:
        return {"table": None}

    return {
        "table": public_table_info(row, restaurant_name(db)),
    }


@router.post("/release")
def release(
    db: Session = Depends(get_db),
    current_user=Depends(require_current_user),
):
    """Clear the table context, called when the guest signs out."""
    released = release_table(db, current_user["user_id"])

    return {"released": released}


# ============================================================
# ADMIN - manage tables
# ============================================================

@router.get("/")
def read_tables(
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    return (
        db.query(RestaurantTable)
        .order_by(RestaurantTable.table_number)
        .all()
    )


@router.get("/qr-base-url")
def read_qr_base_url(
    current_admin=Depends(require_admin),
):
    """
    The configured customer entry URL.

    Surfaced so an admin can see exactly what the printed QR encodes
    without having to read the server environment.
    """
    return {
        "entry_base_url": entry_base_url(),
        "example": table_qr_payload(
            type("T", (), {"qr_token": "<table-token>"})(),
            entry_base_url(),
        ),
    }


@router.post("/")
def create_table(
    item: RestaurantTableCreate,
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    number = _validated_table_number(db, item.table_number)

    table = RestaurantTable(
        table_number=number,
        table_name=item.table_name,
        capacity=item.capacity,
        section=item.section,
        is_active=item.is_active,
    )

    assign_token_if_missing(db, table)

    db.add(table)
    db.commit()
    db.refresh(table)

    return table


@router.put("/{table_id}")
def update_table(
    table_id: int,
    item: RestaurantTableUpdate,
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    table = (
        db.query(RestaurantTable)
        .filter(RestaurantTable.id == table_id)
        .first()
    )

    if not table:
        raise HTTPException(status_code=404, detail="Table not found")

    if item.table_number is not None:
        table.table_number = _validated_table_number(
            db,
            item.table_number,
            current_id=table.id,
        )

    if item.table_name is not None:
        table.table_name = item.table_name

    if item.capacity is not None:
        table.capacity = item.capacity

    if item.section is not None:
        table.section = item.section

    if item.is_active is not None:
        table.is_active = item.is_active

    db.commit()
    db.refresh(table)

    return table


@router.post("/{table_id}/regenerate-qr")
def regenerate_qr(
    table_id: int,
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    """
    Issue a new token, retiring the previous printed code.

    The table number is unchanged, so history still lines up.
    """
    table = (
        db.query(RestaurantTable)
        .filter(RestaurantTable.id == table_id)
        .first()
    )

    if not table:
        raise HTTPException(status_code=404, detail="Table not found")

    table.qr_token = generate_table_token()

    db.commit()
    db.refresh(table)

    return {
        "message": f"New QR issued for table {table.table_number}",
        "table": table,
        "qr_payload": table_qr_payload(table, entry_base_url()),
    }


@router.delete("/{table_id}")
def delete_table(
    table_id: int,
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    """
    Remove a table that was created by mistake.

    Deactivating is the normal route; this exists so an admin can clear
    a duplicate entry without leaving it on the floor plan.
    """
    table = (
        db.query(RestaurantTable)
        .filter(RestaurantTable.id == table_id)
        .first()
    )

    if not table:
        raise HTTPException(status_code=404, detail="Table not found")

    db.delete(table)
    db.commit()

    return {"message": f"Table {table.table_number} deleted"}

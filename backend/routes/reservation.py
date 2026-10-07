from datetime import date as date_type

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

try:
    from database import get_db
    from middleware.auth import require_current_user, require_admin
    from models import Reservation
    from crud import (
        get_all_reservations,
        create_reservation,
        update_reservation,
        delete_reservation,
        cancel_reservation,
        get_reservations_by_customer,
        get_reservations_by_user_id,
        update_reservation_status,
    )
    from schemas import ReservationCreate, ReservationStatusUpdate
except (ImportError, ValueError):
    from ..database import get_db
    from ..middleware.auth import require_current_user, require_admin
    from ..models import Reservation
    from ..crud import (
        get_all_reservations,
        create_reservation,
        update_reservation,
        delete_reservation,
        cancel_reservation,
        get_reservations_by_customer,
        get_reservations_by_user_id,
        update_reservation_status,
    )
    from ..schemas import ReservationCreate, ReservationStatusUpdate


from services import event_service

router = APIRouter(
    prefix="/reservations",
    tags=["Reservations"],
)


# Statuses a customer is allowed to cancel themselves.
CANCELLABLE_STATUSES = {"Pending", "Booked"}


def _owns_reservation(current_user, reservation) -> bool:
    """
    Ownership check for a single booking.

    The authenticated user id decides. customer_name is only consulted
    for rows that predate identity links, and even then only when the
    row has no user_id of its own.
    """
    if reservation.user_id is not None:
        return reservation.user_id == current_user["user_id"]

    return reservation.customer_name == current_user["user_name"]


# ============================================================
# GET ALL RESERVATIONS
# ADMIN ONLY
# ============================================================
@router.get("/")
def read_reservations(
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    return get_all_reservations(db)


# ============================================================
# GET MY RESERVATIONS
# AUTHENTICATED USERS
#
# The customer booking screen uses this so a guest can see the
# status of every table they have reserved.
# ============================================================
@router.get("/mine")
def read_my_reservations(
    db: Session = Depends(get_db),
    current_user=Depends(require_current_user),
):
    reservations = get_reservations_by_user_id(
        db,
        current_user["user_id"],
    )

    if not reservations:
        reservations = [
            row
            for row in get_reservations_by_customer(
                db,
                current_user["user_name"],
            )
            if row.user_id in (None, current_user["user_id"])
        ]

    return reservations


# ============================================================
# CHECK TABLE AVAILABILITY
# AUTHENTICATED USERS
#
# Stops two guests from booking the same table at the same slot.
# ============================================================
@router.get("/availability")
def check_table_availability(
    reservation_date: date_type,
    reservation_time: str,
    db: Session = Depends(get_db),
    current_user=Depends(require_current_user),
):
    taken = (
        db.query(Reservation)
        .filter(
            Reservation.reservation_date == reservation_date,
            Reservation.reservation_time == reservation_time,
            Reservation.status.notin_(["Cancelled"]),
        )
        .all()
    )

    free_tables = sorted(
        set(range(1, 13)) - {row.table_number for row in taken}
    )

    return {
        "reservation_date": reservation_date,
        "reservation_time": reservation_time,
        "booked_tables": sorted({row.table_number for row in taken}),
        "available_tables": free_tables,
    }


# ============================================================
# RESERVATION SUMMARY
# ADMIN ONLY
#
# Powers the admin booking board: how many tables are taken per
# day and how many guests to expect, so staff can plan seating.
# ============================================================
@router.get("/summary")
def reservation_summary(
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    total_tables = 12
    today = date_type.today()

    rows = (
        db.query(Reservation)
        .filter(
            Reservation.status.notin_(["Cancelled"]),
            Reservation.reservation_date >= today,
        )
        .all()
    )

    by_date = {}

    for row in rows:
        entry = by_date.setdefault(
            row.reservation_date,
            {
                "date": row.reservation_date,
                "total_bookings": 0,
                "total_guests": 0,
                "tables": set(),
                "by_status": {},
            },
        )

        entry["total_bookings"] += 1
        entry["total_guests"] += row.guests or 0
        entry["tables"].add(row.table_number)
        entry["by_status"][row.status] = (
            entry["by_status"].get(row.status, 0) + 1
        )

    upcoming = []

    for entry in sorted(by_date.values(), key=lambda item: item["date"]):
        booked = sorted(entry["tables"])

        upcoming.append(
            {
                "date": entry["date"],
                "total_bookings": entry["total_bookings"],
                "total_guests": entry["total_guests"],
                "booked_tables": booked,
                "free_tables": sorted(set(range(1, total_tables + 1)) - set(booked)),
                "tables_free_count": total_tables - len(booked),
                "by_status": entry["by_status"],
                "is_today": entry["date"] == today,
            }
        )

    today_entry = next(
        (item for item in upcoming if item["is_today"]),
        None,
    )

    return {
        "total_tables": total_tables,
        "today": today_entry,
        "upcoming": upcoming,
        "total_upcoming_bookings": sum(item["total_bookings"] for item in upcoming),
        "total_upcoming_guests": sum(item["total_guests"] for item in upcoming),
    }


# ============================================================
# CREATE RESERVATION
# AUTHENTICATED USERS
# ============================================================
@router.post("/")
def add_reservation(
    item: ReservationCreate,
    db: Session = Depends(get_db),
    current_user=Depends(require_current_user),
):
    if item.reservation_date < date_type.today():
        raise HTTPException(
            status_code=400,
            detail="Reservation date cannot be in the past",
        )

    item.customer_name = current_user["user_name"]

    if not item.customer_email:
        item.customer_email = current_user.get("email")

    # A new booking always starts as Pending until staff confirm it.
    item.status = "Pending"

    created = create_reservation(
        db,
        item,
        user_id=current_user["user_id"],
    )

    # Phase 6C. A booking's own history: created, then cancelled or
    # completed. Without this, "how many bookings did we lose this month"
    # has no answer.
    event_service.record_event(
        db,
        event_service.RESERVATION_CREATED,
        event_service.ENTITY_RESERVATION,
        entity_id=created.id,
        actor_user_id=current_user["user_id"],
        metadata={
            "reservation_date": str(created.reservation_date),
            "reservation_time": str(created.reservation_time),
            "guests": created.guests,
            "table_number": created.table_number,
        },
    )

    try:
        db.commit()
        # A commit expires every loaded instance, and FastAPI serialises
        # the return value from `__dict__` without triggering a lazy
        # reload. Without this refresh the caller receives an empty
        # object.
        db.refresh(created)
    except Exception:
        db.rollback()

    return created


# ============================================================
# CANCEL MY RESERVATION
# AUTHENTICATED USERS
# ============================================================
@router.patch("/{reservation_id}/cancel")
def cancel_my_reservation(
    reservation_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_current_user),
):
    reservation = (
        db.query(Reservation)
        .filter(Reservation.id == reservation_id)
        .first()
    )

    if not reservation:
        raise HTTPException(
            status_code=404,
            detail="Reservation not found",
        )

    if not _owns_reservation(current_user, reservation):
        raise HTTPException(
            status_code=403,
            detail="You can only cancel your own reservation",
        )

    if reservation.status not in CANCELLABLE_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"A {reservation.status.lower()} reservation "
                "can no longer be cancelled"
            ),
        )

    cancelled = cancel_reservation(db, reservation_id)

    event_service.record_event(
        db,
        event_service.RESERVATION_CANCELLED,
        event_service.ENTITY_RESERVATION,
        entity_id=reservation_id,
        actor_user_id=current_user["user_id"],
        metadata={
            "reservation_date": str(reservation.reservation_date),
            "guests": reservation.guests,
            "table_number": reservation.table_number,
            "from_status": reservation.status,
        },
    )

    try:
        db.commit()
        # See add_reservation: a commit expires the instance, and the
        # serialiser reads __dict__ without reloading it.
        db.refresh(cancelled)
    except Exception:
        db.rollback()

    return cancelled


# ============================================================
# UPDATE RESERVATION STATUS
# ADMIN ONLY
#
# Staff move a booking from Pending to Booked, then Completed.
# ============================================================
@router.patch("/{reservation_id}/status")
def set_reservation_status(
    reservation_id: int,
    payload: ReservationStatusUpdate,
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    allowed = {"Pending", "Booked", "Completed", "Cancelled"}

    if payload.status not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Status must be one of: {', '.join(sorted(allowed))}",
        )

    reservation = update_reservation_status(
        db,
        reservation_id,
        payload.status,
    )

    if not reservation:
        raise HTTPException(
            status_code=404,
            detail="Reservation not found",
        )

    if payload.status == "Cancelled":
        event_service.record_event(
            db,
            event_service.RESERVATION_CANCELLED,
            event_service.ENTITY_RESERVATION,
            entity_id=reservation_id,
            actor_user_id=current_admin["user_id"],
            metadata={
                "reservation_date": str(reservation.reservation_date),
                "guests": reservation.guests,
                "table_number": reservation.table_number,
                "set_by": "admin",
            },
        )

    try:
        db.commit()
        db.refresh(reservation)
    except Exception:
        db.rollback()

    return reservation


# ============================================================
# UPDATE RESERVATION
# ADMIN ONLY
# ============================================================
@router.put("/{reservation_id}")
def edit_reservation(
    reservation_id: int,
    item: ReservationCreate,
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    reservation = update_reservation(
        db,
        reservation_id,
        item,
    )

    if not reservation:
        raise HTTPException(
            status_code=404,
            detail="Reservation not found",
        )

    return reservation


# ============================================================
# DELETE RESERVATION
# ADMIN ONLY
# ============================================================
@router.delete("/{reservation_id}")
def remove_reservation(
    reservation_id: int,
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    reservation = delete_reservation(
        db,
        reservation_id,
    )

    if not reservation:
        raise HTTPException(
            status_code=404,
            detail="Reservation not found",
        )

    return {
        "message": "Reservation deleted successfully",
    }

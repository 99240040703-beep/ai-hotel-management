from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

try:
    from database import get_db
    from middleware.auth import require_current_user, require_admin
    from models import Kitchen, Order, OrderHeader, Menu
    from crud import (
        get_all_orders,
        create_order,
        update_order,
        delete_order,
        cancel_order,
        get_orders_by_customer,
        get_orders_by_user_id,
        update_order_header_status,
        get_order_header_by_id,
        get_order_headers_by_user,
        get_active_order_headers,
    )
    from schemas import CartOrderCreate, OrderCreate, CheckoutRequest, OrderStatusUpdate, OrderStatusResponse
    from services.order_service import (
        CheckoutError,
        checkout as run_checkout,
        quote as run_quote,
        price_named_cart,
        place_legacy_order,
        resolve_table_for_order,
        reprice_existing_line,
    )
    from services.order_lifecycle import (
        validate_transition,
        get_next_statuses,
        is_active_status,
        is_cancellable_by_customer,
    )
    from services import event_service
except (ImportError, ValueError):
    from ..database import get_db
    from ..middleware.auth import require_current_user, require_admin
    from ..models import Kitchen, Order, OrderHeader, Menu
    from ..crud import (
        get_all_orders,
        create_order,
        update_order,
        delete_order,
        cancel_order,
        get_orders_by_customer,
        get_orders_by_user_id,
        update_order_header_status,
        get_order_header_by_id,
        get_order_headers_by_user,
        get_active_order_headers,
    )
    from ..schemas import CartOrderCreate, OrderCreate, CheckoutRequest, OrderStatusUpdate, OrderStatusResponse
    from ..services.order_service import (
        CheckoutError,
        checkout as run_checkout,
        quote as run_quote,
        price_named_cart,
        place_legacy_order,
        resolve_table_for_order,
        reprice_existing_line,
    )
    from ..services.order_lifecycle import (
        validate_transition,
        get_next_statuses,
        is_active_status,
        is_cancellable_by_customer,
    )
    from ..services import event_service


router = APIRouter(
    prefix="/orders",
    tags=["Orders"],
)


# A customer can only stop a ticket that the kitchen has not started.
CANCELLABLE_STATUSES = {"Pending", "Confirmed"}


def _header_lines(db: Session, header_id: int):
    """The `orders` rows belonging to one checkout, in insertion order."""
    return (
        db.query(Order)
        .filter(Order.order_id == header_id)
        .order_by(Order.id.asc())
        .all()
    )


def _line_payload(line: Order) -> dict:
    return {
        "id": line.id,
        "menu_item": line.menu_item,
        "quantity": line.quantity,
        "unit_price": line.unit_price,
        "line_total": line.total_price,
        "special_instructions": line.special_instructions,
    }


def serialize_header(db: Session, header: OrderHeader, is_admin: bool = False) -> dict:
    """
    Render an order header for the API.

    Always exposes the three things the client needs to render the
    lifecycle honestly and nothing it could use to guess a price:

        status              current food status
        payment_status      completely independent of `status`
        valid_next_statuses the only transitions the server will accept

    Line items are included because the kitchen ticket and the admin
    order table both need them, and they belong server-side rather than
    being reassembled per screen.
    """
    return _header_payload(
        header,
        _header_lines(db, header.id),
        is_admin=is_admin,
    )


def serialize_headers(db: Session, headers, is_admin: bool = False) -> list:
    """serialize_header for a collection, reading the lines only once."""
    headers = list(headers)

    if not headers:
        return []

    lines_by_header = {header.id: [] for header in headers}

    for line in (
        db.query(Order)
        .filter(Order.order_id.in_(list(lines_by_header.keys())))
        .order_by(Order.id.asc())
        .all()
    ):
        if line.order_id in lines_by_header:
            lines_by_header[line.order_id].append(line)

    return [
        _header_payload(header, lines_by_header.get(header.id, []), is_admin=is_admin)
        for header in headers
    ]


def _header_payload(header: OrderHeader, lines, is_admin: bool = False) -> dict:
    """The wire shape itself, shared by both serializers above."""
    return {
        "id": header.id,
        "order_id": header.id,
        "reference": header.reference,
        "customer_name": header.customer_name,
        "customer_email": header.customer_email,
        "order_type": header.order_type,
        "table_id": header.table_id,
        "table_number": header.table_number,
        "delivery_address": header.delivery_address,
        "notes": header.notes,
        "subtotal": header.subtotal,
        "tax_amount": header.tax_amount,
        "service_charge_amount": header.service_charge_amount,
        "discount_amount": header.discount_amount,
        "total_amount": header.total_amount,
        "currency": header.currency,
        "status": header.status,
        # Independent of status: an order can be SERVED and still unpaid,
        # because guests pay after they leave.
        "payment_status": header.payment_status,
        "valid_next_statuses": get_next_statuses(header.status, is_admin=is_admin),
        "placed_at": header.placed_at.isoformat() if header.placed_at else None,
        "updated_at": header.updated_at.isoformat() if header.updated_at else None,
        "items": [_line_payload(line) for line in lines],
        "item_count": sum(line.quantity or 0 for line in lines),
    }


def _legacy_order_groups(db: Session):
    """
    Group legacy orders (orders with order_id = NULL) by customer_name and date.

    Returns a list of dicts with the same structure as _header_payload,
    representing virtual order headers for historical data.
    """
    from sqlalchemy import func

    # Group by customer_name and date(created_at)
    groups = (
        db.query(
            Order.customer_name,
            func.date(Order.created_at).label("order_date"),
            func.min(Order.created_at).label("placed_at"),
            func.max(Order.created_at).label("updated_at"),
            func.count(Order.id).label("item_count"),
            func.sum(Order.total_price).label("total_amount"),
            func.group_concat(Order.id).label("order_ids"),
        )
        .filter(Order.order_id.is_(None))
        .group_by(Order.customer_name, func.date(Order.created_at))
        .order_by(func.max(Order.created_at).desc())
        .all()
    )

    result = []
    for idx, group in enumerate(groups):
        # Fetch the individual order lines for this group
        order_ids = [int(x) for x in group.order_ids.split(",")] if group.order_ids else []
        lines = (
            db.query(Order)
            .filter(Order.id.in_(order_ids))
            .order_by(Order.id.asc())
            .all()
        ) if order_ids else []

        # Determine order_type from the first line (most common)
        order_type = lines[0].order_type if lines else "dine-in"
        table_number = lines[0].table_number if lines else None

        # Create a virtual reference for legacy orders
        date_str = group.order_date.strftime("%y%m%d") if group.order_date else "legacy"
        reference = f"LEGACY-{date_str}-{idx + 1:04d}"

        # Legacy orders use old statuses like "Completed" - map to new lifecycle
        # For display purposes, we'll use the most common status in the group
        statuses = [line.status for line in lines]
        status = max(set(statuses), key=statuses.count) if statuses else "Completed"

        # Map legacy statuses to new lifecycle for valid_next_statuses
        legacy_to_lifecycle = {
            "Pending": "Placed",
            "Confirmed": "Confirmed",
            "Preparing": "Preparing",
            "Ready": "Ready",
            "Served": "Served",
            "Completed": "Served",
            "Cancelled": "Cancelled",
        }
        lifecycle_status = legacy_to_lifecycle.get(status, "Served")

        result.append({
            "id": -(idx + 1),  # Negative IDs for virtual legacy headers
            "order_id": -(idx + 1),
            "reference": reference,
            "customer_name": group.customer_name,
            "customer_email": None,
            "order_type": order_type,
            "table_id": None,
            "table_number": table_number,
            "delivery_address": lines[0].delivery_address if lines else None,
            "notes": lines[0].notes if lines else None,
            "subtotal": round(float(group.total_amount or 0), 2),
            "tax_amount": 0.0,
            "service_charge_amount": 0.0,
            "discount_amount": 0.0,
            "total_amount": round(float(group.total_amount or 0), 2),
            "currency": "INR",
            "status": lifecycle_status,
            "payment_status": "unpaid",  # Unknown for legacy orders
            "valid_next_statuses": [],  # Legacy orders are terminal
            "placed_at": group.placed_at.isoformat() if group.placed_at else None,
            "updated_at": group.updated_at.isoformat() if group.updated_at else None,
            "items": [_line_payload(line) for line in lines],
            "item_count": group.item_count or 0,
            "is_legacy": True,
        })

    return result


# ============================================================
# GET MY ORDERS
# AUTHENTICATED USERS
#
# Scoped to the authenticated user id, never to anything the browser
# sends. Rows seeded before identity links existed have no user_id, so
# they are matched on the display name as a fallback - that keeps the
# demo history visible without ever widening access to another
# account's data.
#
# Registered before /{order_id} so "mine" is not read as an id.
# ============================================================
@router.get("/mine")
def read_my_orders(
    current_user=Depends(require_current_user),
    db: Session = Depends(get_db),
):
    orders = get_orders_by_user_id(
        db,
        current_user["user_id"],
    )

    if not orders:
        orders = get_orders_by_customer(
            db,
            current_user["user_name"],
        )

        orders = [
            order
            for order in orders
            if order.user_id in (None, current_user["user_id"])
        ]

    return orders


# ============================================================
# ORDER LIFECYCLE READS
#
# These are registered before the /{order_id} catch-all below, because
# FastAPI matches in registration order and "/headers" would otherwise
# be swallowed by it and fail int parsing with a 422.
# ============================================================

# MY ORDER HEADERS - AUTHENTICATED USERS
#
# One entry per checkout, scoped to the token's user id. Historical
# orders placed before headers existed have no header and are still
# reachable through /orders/mine.
@router.get("/headers/mine")
def read_my_order_headers(
    db: Session = Depends(get_db),
    current_user=Depends(require_current_user),
):
    headers = (
        db.query(OrderHeader)
        .filter(OrderHeader.user_id == current_user["user_id"])
        .order_by(OrderHeader.id.desc())
        .all()
    )

    # A customer is never shown staff-only shortcuts.
    return serialize_headers(
        db, headers, is_admin=current_user["role"] == "admin"
    )


# GET ALL ORDER HEADERS - ADMIN ONLY
@router.get("/headers")
def read_order_headers(
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    headers = (
        db.query(OrderHeader)
        .order_by(OrderHeader.id.desc())
        .all()
    )

    # Serialize real order headers
    real_headers = serialize_headers(db, headers, is_admin=True)

    # Add legacy order groups as virtual headers
    legacy_headers = _legacy_order_groups(db)

    # Combine: real headers first (newest first), then legacy groups (also newest first)
    return real_headers + legacy_headers


# ACTIVE ORDER HEADERS - ADMIN / KITCHEN
#
# The kitchen display's feed: everything not yet served, oldest first so
# the longest-waiting ticket leads the queue.
@router.get("/headers/active")
def read_active_order_headers(
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    headers = get_active_order_headers(db)

    return serialize_headers(db, headers, is_admin=True)


# ORDER STATUS - AUTHENTICATED USERS, OWNERSHIP CHECKED
@router.get("/headers/{header_id}/status")
def read_order_header_status(
    header_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_current_user),
):
    """Current status and the only statuses the server will accept next."""
    header = get_order_header_by_id(db, header_id)

    if not header:
        raise HTTPException(status_code=404, detail="Order header not found")

    is_admin = current_user["role"] == "admin"

    # Never trust an id from the frontend: ownership comes from the JWT.
    if not is_admin and header.user_id != current_user["user_id"]:
        raise HTTPException(
            status_code=403, detail="You can only view your own order status"
        )

    payload = serialize_header(db, header, is_admin=is_admin)

    return {
        "order_id": payload["order_id"],
        "reference": payload["reference"],
        "status": payload["status"],
        "payment_status": payload["payment_status"],
        "valid_next_statuses": payload["valid_next_statuses"],
        "is_admin": is_admin,
    }


# ORDER STATUS TRANSITION - STAFF ONLY
#
# A generic endpoint rather than one path per stage. It accepts only the
# statuses validate_transition allows, which is exactly one step forward
# in the lifecycle - PLACED -> CONFIRMED -> PREPARING -> READY -> SERVED -
# for admin and staff alike. No path through this endpoint can skip a
# state, whatever the caller sends.
@router.post("/headers/{header_id}/status")
def update_order_header_status_endpoint(
    header_id: int,
    payload: OrderStatusUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(require_current_user),
):
    header = get_order_header_by_id(db, header_id)

    if not header:
        raise HTTPException(status_code=404, detail="Order header not found")

    role = current_user["role"]

    # A customer may stop their own order while the kitchen has not
    # started it. They may never advance the lifecycle themselves.
    is_staff = role in ("admin", "staff", "kitchen", "chef", "manager")

    if not is_staff:
        if header.user_id != current_user["user_id"]:
            raise HTTPException(
                status_code=403, detail="You can only update your own order"
            )

        if payload.status != "Cancelled":
            raise HTTPException(
                status_code=403,
                detail=(
                    "Customers cannot change order status. "
                    "Contact staff to update your order."
                ),
            )

        if not is_cancellable_by_customer(header.status):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Order in '{header.status}' status cannot be cancelled"
                ),
            )

    valid, error = validate_transition(
        header.status,
        payload.status,
        is_admin=is_staff,
    )

    if not valid:
        raise HTTPException(status_code=400, detail=error)

    previous_status = header.status

    updated = update_order_header_status(db, header_id, payload.status)

    # Phase 6C. The transition itself is the fact worth keeping: it is
    # what makes preparation time, delay and cancellation rate computable
    # later. Recording happens after the status is committed, so a failure
    # here cannot undo an order the kitchen has already actioned.
    event_service.record_order_status(
        db,
        updated,
        previous_status,
        payload.status,
        actor_user_id=current_user["user_id"],
    )

    try:
        db.commit()
        # A commit expires every loaded instance, and this handler reads
        # the header's fields straight after. Refresh so those reads are
        # real values rather than a silent reload mid-response.
        db.refresh(updated)
    except Exception:
        db.rollback()

    # payment_status is never touched here. Advancing the food status
    # says nothing about whether the guest has paid, and the two are
    # deliberately not coupled in either direction.
    return {
        "order_id": updated.id,
        "reference": updated.reference,
        "status": updated.status,
        "payment_status": updated.payment_status,
        "message": f"Order status updated to {updated.status}",
        "valid_next_statuses": get_next_statuses(
            updated.status, is_admin=is_staff
        ),
    }


# MY ACTIVE ORDER - AUTHENTICATED USERS
#
# The live tracking poll. Scoped to the token's user id, so one guest
# can never read another's ticket by guessing an id.
@router.get("/my-active")
def read_my_active_order(
    db: Session = Depends(get_db),
    current_user=Depends(require_current_user),
):
    headers = get_order_headers_by_user(db, current_user["user_id"])

    active = [header for header in headers if is_active_status(header.status)]

    if not active:
        return {"active_order": None}

    # get_order_headers_by_user returns newest first, so this is the
    # guest's most recent order that is still in progress.
    payload = serialize_header(
        db,
        active[0],
        is_admin=current_user["role"] == "admin",
    )

    return {"active_order": payload}


# ============================================================
# GET A SINGLE ORDER
# AUTHENTICATED USERS
#
# Used by the live tracking screen to poll one order's status.
# ============================================================
@router.get("/{order_id}")
def read_my_order(
    order_id: int,
    current_user=Depends(require_current_user),
    db: Session = Depends(get_db),
):
    order = db.query(Order).filter(Order.id == order_id).first()

    if not order:
        raise HTTPException(
            status_code=404,
            detail="Order not found",
        )

    if current_user["role"] == "admin":
        return order

    owned_by_id = order.user_id == current_user["user_id"]
    owned_by_name = (
        order.user_id is None
        and order.customer_name == current_user["user_name"]
    )

    if not (owned_by_id or owned_by_name):
        raise HTTPException(
            status_code=403,
            detail="You can only view your own order",
        )

    return order


# ============================================================
# CANCEL MY ORDER
# AUTHENTICATED USERS
# ============================================================
@router.patch("/{order_id}/cancel")
def cancel_my_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_current_user),
):
    order = db.query(Order).filter(Order.id == order_id).first()

    if not order:
        raise HTTPException(
            status_code=404,
            detail="Order not found",
        )

    owned_by_id = order.user_id == current_user["user_id"]
    owned_by_name = (
        order.user_id is None
        and order.customer_name == current_user["user_name"]
    )

    if not (owned_by_id or owned_by_name):
        raise HTTPException(
            status_code=403,
            detail="You can only cancel your own order",
        )

    if order.status not in CANCELLABLE_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"A {order.status.lower()} order can no longer "
                "be cancelled - please speak to the counter"
            ),
        )

    return cancel_order(db, order_id)


# ============================================================
# CHECKOUT QUOTE
# AUTHENTICATED USERS
#
# Prices a cart and returns the server's arithmetic without writing
# anything. This is what the checkout screen shows before the guest
# commits, and it is produced by the same code that later charges them.
# ============================================================
@router.post("/quote")
def quote_cart(
    payload: CheckoutRequest,
    db: Session = Depends(get_db),
    current_user=Depends(require_current_user),
):
    try:
        return run_quote(db, payload.model_dump(), current_user)
    except CheckoutError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.message,
        )


# ============================================================
# CHECKOUT
# AUTHENTICATED USERS
#
# Prices the cart on the server and persists it: one order header plus
# one `orders` row per dish, and a kitchen ticket for each line.
#
# Every amount comes from menu.price. Any price, subtotal or total the
# browser sent is discarded before this runs.
# ============================================================
@router.post("/checkout")
def checkout_cart(
    payload: CheckoutRequest,
    db: Session = Depends(get_db),
    current_user=Depends(require_current_user),
):
    try:
        result = run_checkout(db, payload.model_dump(), current_user)
    except CheckoutError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.message,
        )

    return {
        "message": "Order placed successfully",
        "orders_created": len(result["lines"]),
        "reference": result["reference"],
        "order_id": result["order_id"],
        "subtotal": result["subtotal"],
        "tax_amount": result["tax_amount"],
        "discount_amount": result["discount_amount"],
        "total_amount": result["total_amount"],
        "currency": result["currency"],
        "currency_source": result["currency_source"],
        "priced_by": result["priced_by"],
        "payment_status": result["payment_status"],
        "status": result["status"],
        "valid_next_statuses": result["valid_next_statuses"],
        "summary": result,
        "orders": [
            Order(id=line["id"], menu_item=line["menu_item"],
                  quantity=line["quantity"], total_price=line["line_total"])
            for line in result["lines"]
        ],
    }


# ============================================================
# PLACE A FULL CART  (legacy shape)
# AUTHENTICATED USERS
#
# The customer checkout submits every selected dish in one request.
#
# Kept for the existing customer screens, but it no longer trusts the
# browser. Phase 6A closed the last two gaps here:
#
#   * availability - an unavailable dish is now refused instead of being
#     sold, matching /checkout.
#   * table - the table is resolved server-side. A guest's own QR claim
#     wins outright, and a bare table_number has to name a real active
#     table. Previously any number in the body was accepted.
#
# Pricing is delegated to order_service.price_named_cart so this path and
# /checkout share one implementation rather than two that can drift.
#
# The response shape and the header-less line rows are unchanged, so the
# existing screens and tests that read `orders[].id` keep working.
# ============================================================
@router.post("/cart")
def place_cart(
    payload: CartOrderCreate,
    db: Session = Depends(get_db),
    current_user=Depends(require_current_user),
):
    if not payload.items:
        raise HTTPException(
            status_code=400,
            detail="Cart is empty",
        )

    # The guest's display name comes from the token. A body field of the
    # same name is ignored.
    customer_name = current_user.get("user_name") or payload.customer_name

    try:
        summary = price_named_cart(
            db,
            [
                {
                    "menu_id": entry.menu_id,
                    "menu_item": entry.menu_item,
                    "quantity": entry.quantity,
                    "special_instructions": entry.special_instructions,
                }
                for entry in payload.items
            ],
            current_user,
            order_type=payload.order_type,
            table_number=payload.table_number,
            delivery_address=payload.delivery_address,
            notes=payload.notes,
        )
    except CheckoutError as error:
        raise HTTPException(
            status_code=error.status_code, detail=error.message
        )

    # The table the server decided on - a claim beats the request body.
    table_id, table_number = summary["table_id"], summary["table_number"]

    order_rows = []

    for line in summary["items"]:
        order_row = Order(
            customer_name=customer_name,
            menu_item=line["menu_item"],
            quantity=line["quantity"],
            # From the menu, via the shared pricing path above.
            total_price=line["line_total"],
            status="Pending",
            order_type=summary["order_type"],
            table_number=table_number,
            delivery_address=summary["delivery_address"],
            notes=summary["notes"],
            special_instructions=(
                line["special_instructions"] or summary["notes"]
            ),
            image_url=line["image_url"],
            unit_price=line["unit_price"],
            # Ownership from the token, never from the body.
            user_id=current_user["user_id"],
        )

        db.add(order_row)
        order_rows.append(order_row)

    # One transaction for the whole cart. Committing per line used to
    # leave a half-written order behind whenever anything failed midway,
    # which is exactly the sort of orphan row a guest can never see and
    # staff cannot explain.
    try:
        # Two flushes, no commits: the first gives the rows their ids,
        # the second exists so nothing can be half-written if the insert
        # itself fails.
        db.flush()

        for order_row in order_rows:
            db.add(
                Kitchen(
                    order_id=order_row.id,
                    customer_name=customer_name,
                    menu_item=order_row.menu_item,
                    quantity=order_row.quantity,
                    status="Pending",
                    priority="Normal",
                    notes=order_row.special_instructions or summary["notes"],
                )
            )

        db.commit()
    except Exception:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail="The order could not be saved. Nothing was charged.",
        )

    created_ids = [row.id for row in order_rows]

    created = (
        db.query(Order)
        .filter(Order.id.in_(created_ids))
        .all()
        if created_ids
        else []
    )

    created.sort(key=lambda order: created_ids.index(order.id))

    return {
        "message": "Order placed successfully",
        "orders_created": len(created),
        "subtotal": summary["subtotal"],
        "tax_amount": summary["tax_amount"],
        "service_charge_amount": summary["service_charge_amount"],
        "discount_amount": summary["discount_amount"],
        "total_amount": summary["total_amount"],
        "currency": summary["currency"],
        "currency_source": summary["currency_source"],
        "table_number": table_number,
        "priced_by": summary["priced_by"],
        "orders": created,
    }


# ============================================================
# GET ALL ORDERS
# ADMIN ONLY
#
# Customers must never receive the complete order list.
# ============================================================
@router.get("/")
def read_orders(
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    return get_all_orders(db)


# ============================================================
# CREATE A SINGLE-DISH ORDER  (legacy shape)
# AUTHENTICATED USERS
#
# Phase 6A. This endpoint used to pass the client's `total_price`
# straight into the orders table, so a request carrying
# `{"menu_item": "X", "quantity": 2, "total_price": 1}` stored a Rs.1
# order. It is now a thin wrapper over the same pricing used by
# /checkout, so it produces a real OrderHeader, server-priced lines and
# kitchen tickets like every other order.
#
# The client may still say WHICH dish and HOW MANY. It may not say what
# that costs, what currency it is in, whose name it is, or which table
# it belongs to - all of those are read from the database or the token.
# ============================================================
@router.post("/")
def add_order(
    item: OrderCreate,
    db: Session = Depends(get_db),
    current_user=Depends(require_current_user),
):
    """
    Place a one-dish order at the server's price.

    This endpoint used to pass the client's `total_price` straight into
    the orders table, so a request carrying
    `{"menu_id": 51, "quantity": 2, "total_price": 1}` stored a Rs.1
    order. It is now a thin wrapper over `place_legacy_order`, which
    delegates to the same code as /checkout.

    The client may still say WHICH dish (by menu_id, or by an
    unambiguous menu_item name) and HOW MANY. It may not say what that
    costs, what currency it is in, whose name it is, which table it
    belongs to, or what status it starts in.
    """
    try:
        result = place_legacy_order(
            db,
            current_user,
            menu_id=item.menu_id,
            menu_name=item.menu_item,
            quantity=item.quantity,
            order_type=item.order_type,
            table_number=item.table_number,
            delivery_address=item.delivery_address,
            notes=item.notes,
            special_instructions=item.special_instructions,
        )
    except CheckoutError as error:
        raise HTTPException(
            status_code=error.status_code, detail=error.message
        )

    # The legacy response exposed the created line rows under "orders",
    # so that key is kept for older callers. Everything financial in it
    # is the server's figure.
    line_ids = [line["id"] for line in result["lines"]]

    created = (
        db.query(Order).filter(Order.id.in_(line_ids)).all()
        if line_ids
        else []
    )

    created.sort(key=lambda order: line_ids.index(order.id))

    return {
        "message": "Order placed successfully",
        "orders_created": len(created),
        "order_id": result["order_id"],
        "reference": result["reference"],
        # Server figures. The submitted total_price is not echoed back,
        # because echoing it could be mistaken for what was charged.
        "subtotal": result["subtotal"],
        "tax_amount": result["tax_amount"],
        "service_charge_amount": result["service_charge_amount"],
        "discount_amount": result["discount_amount"],
        "total_amount": result["total_amount"],
        "currency": result["currency"],
        "currency_source": result["currency_source"],
        "status": result["status"],
        "payment_status": result["payment_status"],
        "priced_by": result["priced_by"],
        "items": result["items"],
        "orders": created,
    }


# ============================================================
# UPDATE ORDER
# ADMIN ONLY
#
# Order status and management operations belong to the
# restaurant/admin side.
#
# Phase 6A: this used to copy the submitted `total_price` onto the
# stored row, so an admin edit could silently rewrite what a customer
# had already been charged. The total is now recomputed from the menu
# when the dish or quantity actually changes, and left untouched when
# they do not - so correcting a status or a note never rewrites
# financial history.
# ============================================================
@router.put("/{order_id}")
def edit_order(
    order_id: int,
    item: OrderCreate,
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    order = db.query(Order).filter(Order.id == order_id).first()

    if not order:
        raise HTTPException(
            status_code=404,
            detail="Order not found",
        )
# Which dish is being ordered has to be explicit on an edit. An
    # omitted menu_item used to be silently stored as NULL, which is how a
    # line could lose its dish entirely.
    if item.menu_id is None and not item.menu_item:
        raise HTTPException(
            status_code=400,
            detail="A menu_item or menu_id is required to edit an order",
        )

    dish_changed = item.menu_id is not None or (
        (item.menu_item or "") != (order.menu_item or "")
    )
    quantity_changed = item.quantity != order.quantity

    unit_price = order.unit_price
    line_total = order.total_price

    if dish_changed or quantity_changed:
        try:
            unit_price, line_total = reprice_existing_line(
                db,
                order,
                menu_name_id=item.menu_id,
                menu_name=item.menu_item,
                quantity=item.quantity,
            )
        except CheckoutError as error:
            raise HTTPException(
                status_code=error.status_code, detail=error.message
            )

    # An edit addressed by id still needs the dish's canonical name on the
    # row, and `orders.menu_item` is NOT NULL.
    if item.menu_id is not None:
        resolved = (
            db.query(Menu).filter(Menu.id == item.menu_id).first()
        )

        item.menu_item = resolved.name if resolved else order.menu_item

    # customer_name is display-only and nullable in the request, so a
    # blank field keeps the name already on the row instead of erasing it.
    if not item.customer_name:
        item.customer_name = order.customer_name

    updated = update_order(
        db,
        order_id,
        item,
        # Server-computed. The submitted total_price is never consulted.
        unit_price=unit_price,
        total_price=line_total,
    )

    if not updated:
        raise HTTPException(
            status_code=404,
            detail="Order not found",
        )

    return updated


# ============================================================
# DELETE ORDER
# ADMIN ONLY
# ============================================================
@router.delete("/{order_id}")
def remove_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_admin=Depends(require_admin),
):
    order = delete_order(db, order_id)

    if not order:
        raise HTTPException(
            status_code=404,
            detail="Order not found",
        )

    return {
        "message": "Order deleted successfully",
    }


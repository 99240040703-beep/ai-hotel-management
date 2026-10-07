"""
Server-authoritative pricing for checkout.

Everything a customer is charged is worked out here, from the database,
and nowhere else. The browser may say what it *wants* to buy; it can
never say what that costs.

What this module refuses to accept from the client:
  - unit prices and line totals
  - subtotal, tax, discount and grand total
  - customer id, customer name or user id
  - whether an item is available

The checkout flow is:

    quote()     validate the cart and return the server's arithmetic,
                writing nothing at all
    checkout()  re-validate, then persist an order header plus one
                `orders` row per dish, and raise kitchen tickets

Both return the same summary shape, so a quote shown to the guest is
produced by the same code that later charges them.
"""

from datetime import datetime

from sqlalchemy.orm import Session

from models import Kitchen, Menu, Order, OrderHeader, Settings
from services.table_service import (
    get_active_table_by_number,
    get_claimed_table,
)
from services.order_lifecycle import (
    OrderStatus,
    VALID_TRANSITIONS,
    get_next_statuses,
)

# Phase 6C. Imported for the side effect of being the single writer of
# operational history; no query in this module reads the event log.
from services import event_service
from services.event_service import record_order_status


# Order types the guest may choose.
ALLOWED_ORDER_TYPES = {"dine-in", "takeaway", "delivery"}

# A single line cannot exceed this, and a single order cannot contain
# more than this many lines. Both stop a client from submitting an
# absurd payload.
MAX_QUANTITY_PER_LINE = 50
MAX_LINES_PER_ORDER = 50


class CheckoutError(Exception):
    """
    A checkout request that must be rejected.

    Carries the HTTP status and a message that is safe to show a guest.
    """

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# =========================================================
# SCALAR VALIDATION
#
# These parse the handful of values a client is allowed to influence.
# They are deliberately strict: a value that is not exactly what it
# claims to be is refused rather than coerced, so `2.5` can never be
# quietly rounded down to two portions.
# =========================================================

def parse_quantity(raw) -> int:
    """
    Accept a whole number of portions and nothing else.

    Rejected: booleans (True is not one portion), non-integral floats
    (2.5), values that are not numeric at all, and out-of-range counts.
    Accepted: 2, 2.0 and "2", which all unambiguously mean two.
    """
    if isinstance(raw, bool):
        raise CheckoutError("Quantity must be a whole number", status_code=400)

    if isinstance(raw, int):
        quantity = raw
    elif isinstance(raw, float):
        if not raw.is_integer():
            raise CheckoutError("Quantity must be a whole number", status_code=400)

        quantity = int(raw)
    elif isinstance(raw, str):
        text = raw.strip()

        # int() alone would accept "+3", "1_0" and unicode digits, and
        # would also accept "3.0" - none of which is a clean request.
        if not text or not text.lstrip("+-").isdigit():
            raise CheckoutError("Quantity must be a whole number", status_code=400)

        quantity = int(text)
    else:
        raise CheckoutError("Quantity must be a whole number", status_code=400)

    if quantity < 1:
        raise CheckoutError("Quantity must be at least 1", status_code=400)

    if quantity > MAX_QUANTITY_PER_LINE:
        raise CheckoutError(
            f"Maximum {MAX_QUANTITY_PER_LINE} portions per dish per order",
            status_code=400,
        )

    return quantity


def authoritative_currency(db: Session) -> str:
    """
    The currency every amount in this system is denominated in.

    Read from the settings table - the single row an admin edits - and
    never from a request. A request that names a different currency is
    ignored; it cannot change what an order is charged in.
    """
    return (get_settings(db).currency or "UNSET").upper()


# =========================================================
# SETTINGS
# =========================================================

def get_settings(db: Session) -> Settings:
    """
    The single configuration row, created by scripts/seed_settings.py.

    If it is somehow missing the caller still gets usable values rather
    than a crash, but the flag on the response tells the front end that
    tax was not read from configuration.
    """
    row = db.query(Settings).first()

    if row:
        return row

    return Settings(
        currency="UNSET",
        tax_percentage=0.0,
        service_charge_percentage=0.0,
    )


# =========================================================
# LINE VALIDATION AND PRICING
# =========================================================

def _resolve_lines(db: Session, requested_lines):
    """
    Turn a client cart into priced lines using menu.price.

    requested_lines: list of dicts with at least menu_item_id and
    quantity. Any price fields present are deliberately ignored.
    """
    if not requested_lines:
        raise CheckoutError("Your cart is empty")

    if len(requested_lines) > MAX_LINES_PER_ORDER:
        raise CheckoutError(
            f"An order can contain at most {MAX_LINES_PER_ORDER} items"
        )

    # Reject the whole request if the cart repeats a dish, so merging is
    # never ambiguous.
    seen = set()

    for line in requested_lines:
        item_id = line.get("menu_item_id")

        if item_id in seen:
            raise CheckoutError(
                "The same dish appears twice in your cart. "
                "Combine the quantities into one line.",
                status_code=400,
            )

        seen.add(item_id)

    menu_ids = []

    for line in requested_lines:
        item_id = line.get("menu_item_id")

        # Accept a numeric id only. A dish name is never used to price
        # something, because names are not unique.
        try:
            menu_ids.append(int(item_id))
        except (TypeError, ValueError):
            raise CheckoutError(
                "Every cart line must reference a menu_item_id",
                status_code=400,
            )

    menu_rows = db.query(Menu).filter(Menu.id.in_(menu_ids)).all()

    by_id = {row.id: row for row in menu_rows}

    missing = [item_id for item_id in menu_ids if item_id not in by_id]

    if missing:
        raise CheckoutError(
            f"Unknown menu item id(s): {', '.join(str(m) for m in missing)}",
            status_code=404,
        )

    priced = []

    for line in requested_lines:
        item_id = int(line["menu_item_id"])
        item = by_id[item_id]

        quantity = parse_quantity(line.get("quantity"))

        if not item.available:
            raise CheckoutError(
                f"'{item.name}' is currently unavailable",
                status_code=409,
            )

        unit_price = round(float(item.price or 0), 2)

        priced.append(
            {
                "menu_item_id": item.id,
                "menu_item": item.name,
                "category": item.category,
                "quantity": quantity,
                # Straight from the database. The client cannot set this.
                "unit_price": unit_price,
                "line_total": round(unit_price * quantity, 2),
                "image_url": item.image_url,
                "special_instructions": (
                    line.get("special_instructions") or None
                ),
                "prep_time": item.prep_time,
                "is_vegetarian": item.is_vegetarian,
            }
        )

    return priced


def _validate_order_context(payload):
    order_type = (payload.get("order_type") or "dine-in").strip().lower()

    if order_type not in ALLOWED_ORDER_TYPES:
        raise CheckoutError(
            "order_type must be one of: "
            + ", ".join(sorted(ALLOWED_ORDER_TYPES))
        )

    delivery_address = payload.get("delivery_address")

    if order_type == "delivery" and not delivery_address:
        raise CheckoutError(
            "A delivery address is required for delivery orders"
        )

    return order_type, delivery_address


def _resolve_table(db: Session, order_type: str, payload: dict, user: dict):
    """
    Decide which table this order belongs to.

    Two cases:

      * the guest scanned a table QR and claimed it. Their claim lives on
        the users row, so the server knows the table and the
        table_number in the request is ignored entirely. Editing it in
        devtools moves nothing.

      * no claim. Then a dine-in order must name a table, and that
        number has to exist and be active in restaurant_tables.

    Returns (table_id, table_number). Both None for non-dine-in.
    """
    if order_type != "dine-in":
        return None, None

    claimed = get_claimed_table(db, user["user_id"])

    if claimed:
        # The claim wins. The client value is not even read.
        return claimed.id, claimed.table_number

    raw = payload.get("table_number")

    if raw is None:
        raise CheckoutError(
            "A table number is required for dine-in orders"
        )

    try:
        requested = int(raw)
    except (TypeError, ValueError):
        raise CheckoutError("table_number must be a whole number")

    table = get_active_table_by_number(db, requested)

    if not table:
        raise CheckoutError(
            f"Table {requested} is not available. Please check the "
            "table number, or scan the QR code on your table.",
            status_code=409,
        )

    return table.id, table.table_number


def resolve_table_for_order(db: Session, order_type: str, payload: dict,
                            user: dict):
    """
    Public wrapper for `_resolve_table`.

    The legacy `POST /orders/cart` path used to copy `table_number`
    straight from the request, which let a client file an order against
    any table it liked. Routing it through here means a claimed table
    always wins and an unclaimed number has to exist and be active.
    """
    return _resolve_table(db, order_type, payload, user)


def _next_reference(db: Session) -> str:
    """
    Short human-readable order number, e.g. A-1007.

    Not sequential-per-customer and not a secret - it is only there so a
    guest and the kitchen can talk about the same order.
    """
    today = datetime.utcnow().strftime("%y%m%d")

    prefix = f"A-{today}-"

    last = (
        db.query(OrderHeader.reference)
        .filter(OrderHeader.reference.like(f"{prefix}%"))
        .order_by(OrderHeader.reference.desc())
        .first()
    )

    sequence = 1

    if last and last[0]:
        try:
            sequence = int(last[0].rsplit("-", 1)[1]) + 1
        except (ValueError, IndexError):
            sequence = 1

    return f"{prefix}{sequence:04d}"


def build_summary(db: Session, payload: dict, user: dict):
    """
    Price a cart without writing anything.

    This is what the checkout screen shows, and it is the identical
    arithmetic used when the order is actually created.
    """
    settings = get_settings(db)

    order_type, delivery_address = _validate_order_context(payload)

    table_id, table_number = _resolve_table(
        db,
        order_type,
        payload,
        user,
    )

    lines = _resolve_lines(db, payload.get("items") or [])

    subtotal = round(sum(line["line_total"] for line in lines), 2)

    tax_rate = float(settings.tax_percentage or 0)
    service_rate = float(settings.service_charge_percentage or 0)

    tax_amount = round(subtotal * tax_rate / 100.0, 2)
    service_charge_amount = round(subtotal * service_rate / 100.0, 2)

    # Phase 6 will source this from the loyalty table. Until then no
    # discount can exist, so the server - not the browser - decides it
    # is zero.
    discount_amount = 0.0
    discount_reason = None

    total = round(
        subtotal + tax_amount + service_charge_amount - discount_amount,
        2,
    )

    if total < 0:
        total = 0.0

    currency = (settings.currency or "UNSET").upper()

    return {
        "reference": None,
        "order_type": order_type,
        "table_number": table_number,
        "table_id": table_id,
        "delivery_address": delivery_address,
        "notes": payload.get("notes") or None,
        "customer_name": user["user_name"],
        "user_id": user["user_id"],
        "items": [
            {
                "menu_item_id": line["menu_item_id"],
                "menu_item": line["menu_item"],
                "category": line["category"],
                "quantity": line["quantity"],
                "unit_price": line["unit_price"],
                "line_total": line["line_total"],
                "special_instructions": line["special_instructions"],
                "image_url": line["image_url"],
            }
            for line in lines
        ],
        "item_count": sum(line["quantity"] for line in lines),
        "subtotal": subtotal,
        "tax_percentage": tax_rate,
        "tax_amount": tax_amount,
        "service_charge_percentage": service_rate,
        "service_charge_amount": service_charge_amount,
        "discount_amount": discount_amount,
        "discount_reason": discount_reason,
        "total_amount": total,
        "currency": currency,
        # Stated explicitly so no caller has to guess whether a currency
        # in the response reflects a setting or something a client asked
        # for. It is always the former.
        "currency_source": "settings",
        "currency_is_confirmed": currency != "UNSET",
        "priced_by": "server (menu.price)",
        "computed_at": datetime.utcnow().isoformat(timespec="seconds"),
        "status": OrderStatus.PLACED.value,
        "valid_next_statuses": get_next_statuses(OrderStatus.PLACED.value),
    }


def quote(db: Session, payload: dict, user: dict):
    """Price a cart. Writes nothing."""
    return build_summary(db, payload, user)


# =========================================================
# PHASE 6A - SHARED ENTRY POINTS FOR THE LEGACY ENDPOINTS
#
# `POST /orders/` and `POST /orders/cart` still exist because older
# screens and the existing tests call them. They used to carry their own
# pricing code, which is how a client-managed total_price survived.
#
# Both now funnel through the functions below, so every order in the
# system is priced by `_resolve_lines` and settled by `build_summary`.
# There is one arithmetic implementation, not three.
# =========================================================

def resolve_menu_id_by_name(db: Session, name) -> int:
    """
    Turn a dish name into its menu id, or refuse.

    The legacy endpoints address dishes by name. Names are not a safe
    key on their own, so an unknown name is a 404 and an ambiguous one is
    a 409 rather than a silent pick.
    """
    if name is None or not str(name).strip():
        raise CheckoutError("A menu_item name is required", status_code=400)

    matches = (
        db.query(Menu)
        .filter(Menu.name == str(name).strip())
        .all()
    )

    if not matches:
        raise CheckoutError(f"Unknown menu item: {name}", status_code=404)

    if len(matches) > 1:
        raise CheckoutError(
            f"'{name}' matches more than one menu item; "
            "order it by menu_item_id instead",
            status_code=409,
        )

    return matches[0].id


def resolve_menu_id(db: Session, menu_id=None, menu_name=None) -> int:
    """
    The one place a requested dish is turned into a menu id.

    An id is authoritative when both are sent: a client cannot name one
    dish and be charged for another. A name is only used when no id was
    supplied, and an unknown or ambiguous name is refused rather than
    resolved to a near match.

    Raises CheckoutError; the caller never gets a half-resolved dish.
    """
    if menu_id is not None:
        try:
            resolved = int(menu_id)
        except (TypeError, ValueError):
            raise CheckoutError(
                "menu_id must be a whole number", status_code=400
            )

        if not db.query(Menu).filter(Menu.id == resolved).first():
            raise CheckoutError(
                f"Unknown menu item id: {menu_id}", status_code=404
            )

        return resolved

    if menu_name is not None and str(menu_name).strip():
        return resolve_menu_id_by_name(db, menu_name)

    raise CheckoutError(
        "A menu item is required (menu_id or menu_item)", status_code=400
    )


def price_named_cart(
    db: Session,
    entries,
    user: dict,
    order_type: str = None,
    table_number=None,
    delivery_address=None,
    notes=None,
):
    """
    Price a name-addressed cart with the authoritative rules.

    `entries` is a list of dicts carrying at least `menu_item` and
    `quantity`. Any price, unit_price, total_price, currency,
    customer_name or status a caller includes is ignored outright - the
    values used here come from the menu table, the settings row and the
    authenticated token.

    Returns the same summary shape as `quote`, so a caller that already
    understands the checkout response needs no special case.
    """
    if not entries:
        raise CheckoutError("Your cart is empty")

    lines = []

    for entry in entries:
        if not isinstance(entry, dict):
            raise CheckoutError(
                "Each cart line must be an object", status_code=400
            )

        menu_id = resolve_menu_id(
            db, entry.get("menu_id"), entry.get("menu_item")
        )

        lines.append(
            {
                "menu_item_id": menu_id,
                "quantity": entry.get("quantity"),
                "special_instructions": entry.get("special_instructions"),
            }
        )

    payload = {
        "items": lines,
        "order_type": order_type or "dine-in",
        "table_number": table_number,
        "delivery_address": delivery_address,
        "notes": notes,
    }

    return build_summary(db, payload, user)


def place_legacy_order(
    db: Session,
    user: dict,
    menu_id=None,
    menu_name=None,
    quantity=None,
    order_type: str = None,
    table_number=None,
    delivery_address=None,
    notes=None,
    special_instructions=None,
):
    """
    Place the legacy single-dish order at the server's price.

    This is the whole of `POST /orders/`. The client may state which dish
    (by id or by unambiguous name) and how many. Everything else is
    refused or ignored:

        total_price / unit_price   discarded; menu.price is used
        currency                   discarded; the settings row is used
        customer_name              discarded; the JWT is used
        table_number               ignored when the guest has a claim
        status                     always Placed

    It returns exactly what `checkout` returns, so the single-dish
    endpoint and the cart endpoint share one implementation, one
    arithmetic and one set of stored columns. That is what makes
    `OrderHeader.total_amount` safe to hand to a payment gateway later:
    there is exactly one thing that can write it.

    Note there is no `currency` parameter on purpose. Accepting one and
    then ignoring it is worse than not having it, because a caller would
    believe it had an effect.
    """
    resolved_id = resolve_menu_id(db, menu_id, menu_name)

    resolved_type = (order_type or "dine-in").strip().lower()

    result = checkout(
        db,
        {
            "items": [
                {
                    "menu_item_id": resolved_id,
                    "quantity": quantity,
                    "special_instructions": special_instructions,
                }
            ],
            "order_type": resolved_type,
            "table_number": table_number,
            "delivery_address": delivery_address,
            "notes": notes,
        },
        user,
    )

    return result


def reprice_existing_line(db: Session, line, menu_name_id=None,
                          menu_name=None, quantity=None):
    """
    Recalculate an existing order line after an admin edit.

    Used by `PUT /orders/{order_id}`. When the dish or the quantity
    changes the line total must be recomputed from the current menu,
    because the old arithmetic no longer describes the dish being sold.

    When neither changed the stored totals are left exactly as they are,
    so editing a status or a note never rewrites financial history.

    Returns (unit_price, line_total).
    """
    menu_id = resolve_menu_id(db, menu_name_id, menu_name)

    item = db.query(Menu).filter(Menu.id == menu_id).first()

    if not item:
        raise CheckoutError(
            "Unknown menu item", status_code=404
        )

    if not item.available:
        raise CheckoutError(
            f"'{item.name}' is currently unavailable",
            status_code=409,
        )

    parsed = parse_quantity(quantity)

    unit_price = round(float(item.price or 0), 2)

    return unit_price, round(unit_price * parsed, 2)


def checkout(db: Session, payload: dict, user: dict):
    """
    Price the cart, then persist it.

    The total written to the order header is the total returned to the
    caller, so the amount Phase 3 hands to the payment gateway is
    exactly the amount the guest was shown.
    """
    summary = build_summary(db, payload, user)

    if summary["item_count"] == 0:
        raise CheckoutError("Your cart is empty")

    reference = _next_reference(db)

    header = OrderHeader(
        reference=reference,
        user_id=user["user_id"],
        # Display only. The account came from the token.
        customer_name=user["user_name"],
        customer_email=user.get("email"),
        order_type=summary["order_type"],
        table_number=summary["table_number"],
        # Set from the guest's validated table claim. NULL for takeaway
        # and delivery.
        table_id=summary["table_id"],
        delivery_address=summary["delivery_address"],
        notes=summary["notes"],
        subtotal=summary["subtotal"],
        tax_percentage=summary["tax_percentage"],
        tax_amount=summary["tax_amount"],
        service_charge_percentage=summary["service_charge_percentage"],
        service_charge_amount=summary["service_charge_amount"],
        discount_amount=summary["discount_amount"],
        discount_reason=summary["discount_reason"],
        total_amount=summary["total_amount"],
        currency=summary["currency"],
        status="Placed",
        # Phase 3 flips this to 'paid' after the gateway verifies.
        payment_status="unpaid",
    )

    db.add(header)

    created_lines = []

    # One transaction for the header, every line and every kitchen
    # ticket. A failure halfway through used to leave a header with only
    # some of its lines - an order that looks real, is already counted
    # in analytics, and can never be billed correctly. Nothing is
    # committed until every row exists, so a failure writes nothing.
    try:
        db.flush()

        order_rows = []

        for line in summary["items"]:
            # `orders` remains the line table, exactly as the historical
            # rows are. order_id is what ties a line to its header.
            order_row = Order(
                customer_name=summary["customer_name"],
                menu_item=line["menu_item"],
                quantity=line["quantity"],
                # Line total comes from the arithmetic above.
                total_price=line["line_total"],
                status="Pending",
                order_type=summary["order_type"],
                table_number=summary["table_number"],
                delivery_address=summary["delivery_address"],
                notes=summary["notes"],
                special_instructions=line["special_instructions"],
                image_url=line["image_url"],
                unit_price=line["unit_price"],
                user_id=user["user_id"],
                order_id=header.id,
            )

            db.add(order_row)
            order_rows.append((order_row, line))

        # A second flush so every line row has its primary key before the
        # kitchen tickets reference it. No commit yet.
        db.flush()

        for order_row, line in order_rows:
            db.add(
                Kitchen(
                    order_id=order_row.id,
                    customer_name=summary["customer_name"],
                    menu_item=line["menu_item"],
                    quantity=line["quantity"],
                    status="Pending",
                    priority="Normal",
                    notes=line["special_instructions"] or summary["notes"],
                )
            )

            created_lines.append(
                {
                    "id": order_row.id,
                    "menu_item_id": line["menu_item_id"],
                    "menu_item": line["menu_item"],
                    "quantity": line["quantity"],
                    "unit_price": line["unit_price"],
                    "line_total": line["line_total"],
                    "special_instructions": line["special_instructions"],
                }
            )

        db.commit()
    except Exception:
        db.rollback()

        raise CheckoutError(
            "The order could not be saved. Nothing was charged.",
            status_code=500,
        )

    db.refresh(header)

    result = dict(summary)
    result["reference"] = header.reference
    result["order_id"] = header.id
    result["status"] = header.status
    result["payment_status"] = header.payment_status
    result["valid_next_statuses"] = get_next_statuses(header.status)
    result["lines"] = created_lines

    # Phase 6C. The moment the order entered the system. Without this
    # first event there is no baseline to measure preparation time
    # against, and every later duration would be unanchored.
    record_order_status(
        db,
        header,
        previous_status="",
        new_status=OrderStatus.PLACED.value,
        actor_user_id=user.get("user_id"),
    )

    try:
        db.commit()
    except Exception:
        pass

    return result

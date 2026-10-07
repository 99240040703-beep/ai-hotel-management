from sqlalchemy.orm import Session
from datetime import datetime

from models import (
    Menu,
    Order,
    OrderHeader,
    Reservation,
    User,
    Customer,
    Inventory,
    Kitchen,
    Settings,
)

from services.order_lifecycle import ACTIVE_STATUSES

# =========================================================
# USERS
# =========================================================

def get_all_users(db: Session):
    return db.query(User).all()


def create_user(db: Session, user_data):
    """
    user_data can be a dict or a Pydantic schema object with
    name/email/password fields — used by routes/users.py.
    """
    if hasattr(user_data, "model_dump"):
        data = user_data.model_dump()
    else:
        data = dict(user_data)

    user = User(**data)

    db.add(user)
    db.commit()
    db.refresh(user)

    return user

# =========================================================
# MENU CRUD
# =========================================================

def get_all_menu(db: Session):
    return db.query(Menu).all()


def create_menu(db: Session, item):
    new_menu = Menu(
        name=item.name,
        category=item.category,
        price=item.price,
        available=item.available,
        image_url=item.image_url
    )

    db.add(new_menu)
    db.commit()
    db.refresh(new_menu)

    return new_menu


def update_menu(db: Session, menu_id: int, item):
    menu = db.query(Menu).filter(Menu.id == menu_id).first()

    if not menu:
        return None

    menu.name = item.name
    menu.category = item.category
    menu.price = item.price
    menu.available = item.available
    menu.image_url = item.image_url

    db.commit()
    db.refresh(menu)

    return menu


def delete_menu(db: Session, menu_id: int):
    menu = db.query(Menu).filter(Menu.id == menu_id).first()

    if not menu:
        return None

    db.delete(menu)
    db.commit()

    return menu


def toggle_menu_availability(db: Session, menu_id: int):
    menu = db.query(Menu).filter(Menu.id == menu_id).first()

    if not menu:
        return None

    menu.available = not menu.available

    db.commit()
    db.refresh(menu)

    return menu


# =========================================================
# ORDER CRUD
# =========================================================

def get_all_orders(db: Session):
    return db.query(Order).all()


def create_order(db: Session, item, user_id: int = None):
    # Create customer order
    new_order = Order(
        customer_name=item.customer_name,
        menu_item=item.menu_item,
        quantity=item.quantity,
        total_price=item.total_price,
        status=item.status,
        order_type=getattr(item, "order_type", "dine-in"),
        table_number=getattr(item, "table_number", None),
        delivery_address=getattr(item, "delivery_address", None),
        notes=getattr(item, "notes", None),
        special_instructions=getattr(item, "special_instructions", None),
        image_url=getattr(item, "image_url", None),
        # Price the server resolved from menu.price, kept so the charge
        # can be audited later.
        unit_price=getattr(item, "unit_price", None),
        # Ownership is recorded from the authenticated session, never
        # from anything the client sent.
        user_id=getattr(item, "user_id", None) or user_id,
    )

    db.add(new_order)
    db.commit()
    db.refresh(new_order)

    # Automatically create kitchen order
    kitchen_order = Kitchen(
        order_id=new_order.id,
        customer_name=new_order.customer_name,
        menu_item=new_order.menu_item,
        quantity=new_order.quantity,
        status="Pending",
        priority="Normal",
        notes=new_order.special_instructions or new_order.notes
    )

    db.add(kitchen_order)
    db.commit()
    db.refresh(kitchen_order)

    # The kitchen commit expires every instance in the session, so the
    # order is loaded again before it is handed back to the caller.
    db.refresh(new_order)

    return new_order


def update_order(db: Session, order_id: int, item, unit_price=None,
                 total_price=None):
    """
    Update a stored order line.

    Phase 6A: the price is no longer read from `item`. It is passed in
    explicitly by the caller, which is the only place that can compute it
    from the menu. `item.total_price` is ignored even if it is set, so a
    request body can no longer rewrite what a customer was charged.
    """
    order = (
        db.query(Order)
        .filter(Order.id == order_id)
        .first()
    )

    if not order:
        return None

    # Update customer order
    order.customer_name = item.customer_name
    order.menu_item = item.menu_item
    order.quantity = item.quantity
    order.status = item.status

    order.order_type = getattr(item, "order_type", order.order_type)
    order.table_number = getattr(item, "table_number", order.table_number)
    order.delivery_address = getattr(
        item, "delivery_address", order.delivery_address
    )
    order.notes = getattr(item, "notes", order.notes)
    order.special_instructions = getattr(
        item, "special_instructions", order.special_instructions
    )
    order.image_url = getattr(item, "image_url", order.image_url)

    # Only touch the money when the caller supplied server-computed
    # figures. Otherwise the original totals stay exactly as they were,
    # so a status correction cannot rewrite financial history.
    if unit_price is not None:
        order.unit_price = unit_price

    if total_price is not None:
        order.total_price = total_price

    # Synchronize corresponding kitchen order
    kitchen_order = (
        db.query(Kitchen)
        .filter(Kitchen.order_id == order.id)
        .first()
    )

    if kitchen_order:
        kitchen_order.customer_name = order.customer_name
        kitchen_order.menu_item = order.menu_item
        kitchen_order.quantity = order.quantity
        kitchen_order.status = order.status
        kitchen_order.notes = (
            order.special_instructions or order.notes
        )

    db.commit()
    db.refresh(order)

    return order


def delete_order(db: Session, order_id: int):
    order = (
        db.query(Order)
        .filter(Order.id == order_id)
        .first()
    )

    if not order:
        return None

    # The kitchen ticket is created alongside the order, so it has to go
    # with it. Leaving it behind put a phantom ticket on the kitchen
    # display for an order that no longer exists.
    db.query(Kitchen).filter(Kitchen.order_id == order_id).delete(
        synchronize_session=False
    )

    db.delete(order)
    db.commit()

    return order


# =========================================================
# RESERVATION CRUD
# =========================================================

def get_all_reservations(db: Session):
    return db.query(Reservation).all()


def create_reservation(db: Session, item, user_id: int = None):
    new_reservation = Reservation(
        customer_name=item.customer_name,
        table_number=item.table_number,
        reservation_date=item.reservation_date,
        reservation_time=item.reservation_time,
        guests=item.guests,
        customer_email=getattr(item, "customer_email", None),
        status=getattr(item, "status", None) or "Pending",
        special_request=getattr(item, "special_request", None),
        # Recorded from the authenticated session, not the payload.
        user_id=getattr(item, "user_id", None) or user_id,
        created_at=datetime.utcnow()
    )

    db.add(new_reservation)
    db.commit()
    db.refresh(new_reservation)

    return new_reservation


def get_reservations_by_customer(db: Session, customer_name: str):
    return (
        db.query(Reservation)
        .filter(Reservation.customer_name == customer_name)
        .order_by(
            Reservation.reservation_date.desc(),
            Reservation.id.desc()
        )
        .all()
    )


def get_reservations_by_user_id(db: Session, user_id: int):
    """Ownership lookup keyed on the authenticated account."""
    return (
        db.query(Reservation)
        .filter(Reservation.user_id == user_id)
        .order_by(
            Reservation.reservation_date.desc(),
            Reservation.id.desc()
        )
        .all()
    )


def get_orders_by_customer(db: Session, customer_name: str):
    return (
        db.query(Order)
        .filter(Order.customer_name == customer_name)
        .order_by(Order.created_at.desc(), Order.id.desc())
        .all()
    )


def get_orders_by_user_id(db: Session, user_id: int):
    """
    Ownership lookup used by the customer screens.

    Keyed on the authenticated user id, so a guest can only ever see
    their own orders even if two accounts share a display name.
    """
    return (
        db.query(Order)
        .filter(Order.user_id == user_id)
        .order_by(Order.created_at.desc(), Order.id.desc())
        .all()
    )


def cancel_order(db: Session, order_id: int):
    order = db.query(Order).filter(Order.id == order_id).first()

    if not order:
        return None

    order.status = "Cancelled"

    kitchen_order = (
        db.query(Kitchen)
        .filter(Kitchen.order_id == order.id)
        .first()
    )

    if kitchen_order:
        kitchen_order.status = "Cancelled"

    db.commit()
    db.refresh(order)

    return order


def update_order_header_status(
    db: Session,
    header_id: int,
    new_status: str,
):
    """Update the status of an order header and its linked order lines."""
    header = db.query(OrderHeader).filter(OrderHeader.id == header_id).first()

    if not header:
        return None

    header.status = new_status

    # Also update linked order lines
    db.query(Order).filter(Order.order_id == header_id).update(
        {Order.status: new_status}, synchronize_session=False
    )

    # Also update kitchen tickets
    order_ids = [
        r[0]
        for r in db.query(Order.id).filter(Order.order_id == header_id).all()
    ]
    if order_ids:
        db.query(Kitchen).filter(Kitchen.order_id.in_(order_ids)).update(
            {Kitchen.status: new_status}, synchronize_session=False
        )

    db.commit()
    db.refresh(header)

    return header


def get_order_header_by_id(db: Session, header_id: int):
    return db.query(OrderHeader).filter(OrderHeader.id == header_id).first()


def get_order_headers_by_user(db: Session, user_id: int):
    """Get order headers for a specific user, ordered by most recent."""
    return (
        db.query(OrderHeader)
        .filter(OrderHeader.user_id == user_id)
        .order_by(OrderHeader.id.desc())
        .all()
    )


def get_active_order_headers(db: Session):
    """
    Order headers still in progress, oldest first.

    The status list comes from the lifecycle module rather than being
    repeated here, so the kitchen feed can never drift from the
    transitions the server actually accepts.
    """
    active_statuses = [status.value for status in ACTIVE_STATUSES]

    return (
        db.query(OrderHeader)
        .filter(OrderHeader.status.in_(active_statuses))
        .order_by(OrderHeader.placed_at.asc(), OrderHeader.id.asc())
        .all()
    )


def cancel_reservation(db: Session, reservation_id: int):
    reservation = (
        db.query(Reservation)
        .filter(Reservation.id == reservation_id)
        .first()
    )

    if not reservation:
        return None

    reservation.status = "Cancelled"

    db.commit()
    db.refresh(reservation)

    return reservation


def update_reservation_status(
    db: Session,
    reservation_id: int,
    status: str,
):
    reservation = (
        db.query(Reservation)
        .filter(Reservation.id == reservation_id)
        .first()
    )

    if not reservation:
        return None

    reservation.status = status

    db.commit()
    db.refresh(reservation)

    return reservation


def update_reservation(
    db: Session,
    reservation_id: int,
    item
):
    reservation = (
        db.query(Reservation)
        .filter(Reservation.id == reservation_id)
        .first()
    )

    if not reservation:
        return None

    reservation.customer_name = item.customer_name
    reservation.table_number = item.table_number
    reservation.reservation_date = item.reservation_date
    reservation.reservation_time = item.reservation_time
    reservation.guests = item.guests
    reservation.customer_email = getattr(
        item, "customer_email", reservation.customer_email
    )
    reservation.special_request = getattr(
        item, "special_request", reservation.special_request
    )

    if getattr(item, "status", None):
        reservation.status = item.status

    db.commit()
    db.refresh(reservation)

    return reservation


def delete_reservation(
    db: Session,
    reservation_id: int
):
    reservation = (
        db.query(Reservation)
        .filter(Reservation.id == reservation_id)
        .first()
    )

    if not reservation:
        return None

    db.delete(reservation)
    db.commit()

    return reservation


# =========================================================
# CUSTOMER CRUD
# =========================================================

def get_all_customers(db: Session):
    return db.query(Customer).all()


def get_customer(db: Session, customer_id: int):
    return (
        db.query(Customer)
        .filter(Customer.id == customer_id)
        .first()
    )


def create_customer(db: Session, item):
    new_customer = Customer(
        name=item.name,
        email=item.email,
        phone=item.phone,
        address=item.address,
        total_orders=item.total_orders,
        total_spent=item.total_spent,
        created_at=datetime.now()
    )

    db.add(new_customer)
    db.commit()
    db.refresh(new_customer)

    return new_customer


def update_customer(
    db: Session,
    customer_id: int,
    item
):
    customer = (
        db.query(Customer)
        .filter(Customer.id == customer_id)
        .first()
    )

    if not customer:
        return None

    customer.name = item.name
    customer.email = item.email
    customer.phone = item.phone
    customer.address = item.address
    customer.total_orders = item.total_orders
    customer.total_spent = item.total_spent

    db.commit()
    db.refresh(customer)

    return customer


def delete_customer(
    db: Session,
    customer_id: int
):
    customer = (
        db.query(Customer)
        .filter(Customer.id == customer_id)
        .first()
    )

    if not customer:
        return None

    db.delete(customer)
    db.commit()

    return customer


# =========================================================
# INVENTORY CRUD
# =========================================================

def get_all_inventory(db: Session):
    return db.query(Inventory).all()


def get_inventory_item(
    db: Session,
    inventory_id: int
):
    return (
        db.query(Inventory)
        .filter(Inventory.id == inventory_id)
        .first()
    )


def create_inventory(db: Session, item):
    new_inventory = Inventory(
        item_name=item.item_name,
        category=item.category,
        quantity=item.quantity,
        unit=item.unit,
        minimum_stock=item.minimum_stock,
        supplier=item.supplier,
        cost_per_unit=item.cost_per_unit,
        created_at=datetime.now()
    )

    db.add(new_inventory)
    db.commit()
    db.refresh(new_inventory)

    return new_inventory


def update_inventory(
    db: Session,
    inventory_id: int,
    item
):
    inventory = (
        db.query(Inventory)
        .filter(Inventory.id == inventory_id)
        .first()
    )

    if not inventory:
        return None

    inventory.item_name = item.item_name
    inventory.category = item.category
    inventory.quantity = item.quantity
    inventory.unit = item.unit
    inventory.minimum_stock = item.minimum_stock
    inventory.supplier = item.supplier
    inventory.cost_per_unit = item.cost_per_unit

    db.commit()
    db.refresh(inventory)

    return inventory


def delete_inventory(
    db: Session,
    inventory_id: int
):
    inventory = (
        db.query(Inventory)
        .filter(Inventory.id == inventory_id)
        .first()
    )

    if not inventory:
        return None

    db.delete(inventory)
    db.commit()

    return inventory


# =========================================================
# INVENTORY - LOW STOCK
# =========================================================

def get_low_stock_items(db: Session):
    return (
        db.query(Inventory)
        .filter(
            Inventory.quantity <= Inventory.minimum_stock
        )
        .all()
    )


# =========================================================
# KITCHEN CRUD
# =========================================================

def get_all_kitchen_orders(db: Session):
    return db.query(Kitchen).all()


def get_kitchen_order(
    db: Session,
    kitchen_id: int
):
    return (
        db.query(Kitchen)
        .filter(Kitchen.id == kitchen_id)
        .first()
    )


def create_kitchen_order(db: Session, item):
    new_kitchen_order = Kitchen(
        order_id=item.order_id,
        customer_name=item.customer_name,
        menu_item=item.menu_item,
        quantity=item.quantity,
        status=item.status,
        priority=item.priority,
        notes=item.notes,
        created_at=datetime.now()
    )

    db.add(new_kitchen_order)
    db.commit()
    db.refresh(new_kitchen_order)

    return new_kitchen_order


def update_kitchen_order(
    db: Session,
    kitchen_id: int,
    item
):
    kitchen_order = (
        db.query(Kitchen)
        .filter(Kitchen.id == kitchen_id)
        .first()
    )

    if not kitchen_order:
        return None

    # Update kitchen order
    kitchen_order.status = item.status
    kitchen_order.priority = item.priority
    kitchen_order.notes = item.notes

    # Synchronize with customer order
    if kitchen_order.order_id:
        order = (
            db.query(Order)
            .filter(Order.id == kitchen_order.order_id)
            .first()
        )

        if order:
            order.status = item.status

    db.commit()
    db.refresh(kitchen_order)

    return kitchen_order


def delete_kitchen_order(
    db: Session,
    kitchen_id: int
):
    kitchen_order = (
        db.query(Kitchen)
        .filter(Kitchen.id == kitchen_id)
        .first()
    )

    if not kitchen_order:
        return None

    db.delete(kitchen_order)
    db.commit()

    return kitchen_order


# =========================================================
# KITCHEN - FILTER BY STATUS
# =========================================================

def get_kitchen_orders_by_status(
    db: Session,
    status: str
):
    return (
        db.query(Kitchen)
        .filter(Kitchen.status == status)
        .all()
    )


# =========================================================
# SETTINGS CRUD
# =========================================================

def get_settings(db: Session):
    return db.query(Settings).first()


def create_settings(db: Session, item):
    new_settings = Settings(
        restaurant_name=item.restaurant_name,
        restaurant_address=item.restaurant_address,
        phone=item.phone,
        email=item.email,
        currency=item.currency,
        tax_percentage=item.tax_percentage,
        service_charge_percentage=item.service_charge_percentage,
        opening_time=item.opening_time,
        closing_time=item.closing_time,
        notifications_enabled=item.notifications_enabled,
        ai_enabled=item.ai_enabled
    )

    db.add(new_settings)
    db.commit()
    db.refresh(new_settings)

    return new_settings


def update_settings(
    db: Session,
    settings_id: int,
    item
):
    settings = (
        db.query(Settings)
        .filter(Settings.id == settings_id)
        .first()
    )

    if not settings:
        return None

    if item.restaurant_name is not None:
        settings.restaurant_name = item.restaurant_name

    if item.restaurant_address is not None:
        settings.restaurant_address = item.restaurant_address

    if item.phone is not None:
        settings.phone = item.phone

    if item.email is not None:
        settings.email = item.email

    if item.currency is not None:
        settings.currency = item.currency

    if item.tax_percentage is not None:
        settings.tax_percentage = item.tax_percentage

    if item.service_charge_percentage is not None:
        settings.service_charge_percentage = (
            item.service_charge_percentage
        )

    if item.opening_time is not None:
        settings.opening_time = item.opening_time

    if item.closing_time is not None:
        settings.closing_time = item.closing_time

    if item.notifications_enabled is not None:
        settings.notifications_enabled = (
            item.notifications_enabled
        )

    if item.ai_enabled is not None:
        settings.ai_enabled = item.ai_enabled

    db.commit()
    db.refresh(settings)

    return settings


# =========================================================
# ANALYTICS HELPERS
# =========================================================

def get_total_revenue(db: Session):
    orders = db.query(Order).all()

    total = 0

    for order in orders:
        total += float(order.total_price or 0)

    return total


def get_total_orders(db: Session):
    return db.query(Order).count()


def get_total_customers(db: Session):
    return db.query(Customer).count()


def get_total_reservations(db: Session):
    return db.query(Reservation).count()


def get_total_menu_items(db: Session):
    return db.query(Menu).count()
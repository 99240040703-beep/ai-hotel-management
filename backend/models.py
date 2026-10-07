from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Boolean,
    Date,
    Time,
    DECIMAL,
    Text,
    DateTime,
    JSON,
    ForeignKey,
    Index,
)

from datetime import datetime

from database import Base


# =========================================================
# MENU
# =========================================================

class Menu(Base):
    __tablename__ = "menu"

    id = Column(Integer, primary_key=True, index=True)

    name = Column(String(100), nullable=False)

    category = Column(String(50))

    price = Column(DECIMAL(10, 2))

    # Optional rating for the dish (out of 5)
    rating = Column(Float, nullable=True)

    available = Column(Boolean, default=True)

    # Optional URL to an image representing the menu item
    image_url = Column(String(255), nullable=True)

    # Short description shown on the customer digital menu
    description = Column(Text, nullable=True)

    # Drives the green/red dot on the customer menu card
    is_vegetarian = Column(Boolean, default=True)

    # Chef's pick - pinned to the top of the customer menu
    is_featured = Column(Boolean, default=False)

    # 0 = not spicy, 3 = extra hot
    spice_level = Column(Integer, default=0)

    # Kitchen prep time in minutes, used for wait-time estimates
    prep_time = Column(Integer, default=15)


# =========================================================
# ORDER
# =========================================================

class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)

    customer_name = Column(String(100), nullable=False)

    menu_item = Column(String(100), nullable=False)

    quantity = Column(Integer, nullable=False)

    total_price = Column(Float, nullable=False)

    status = Column(String(50), default="Pending")

    # dine-in / takeaway / delivery
    order_type = Column(String(20), default="dine-in")

    # Table number for dine-in orders
    table_number = Column(Integer, nullable=True)

    # Address for delivery orders
    delivery_address = Column(String(255), nullable=True)

    # Cooking instructions typed by the customer
    notes = Column(Text, nullable=True)

    # Per dish request typed by the customer, e.g. "extra salt",
    # "less spicy". The kitchen ticket copies this through.
    special_instructions = Column(Text, nullable=True)

    # Thumbnail of the dish at the time the order was placed
    image_url = Column(String(255), nullable=True)

    # Predicted wait time in minutes for the order (optional)
    predicted_wait_time = Column(Float, nullable=True)

    # The signed-in account that placed this order. Ownership checks use
    # this, never customer_name. NULL for rows seeded before identity
    # links existed.
    user_id = Column(Integer, nullable=True, index=True)

    # Checkout linkage. A row is one dish on an order; rows that share an
    # order_id belong to the same checkout. NULL on every historical row
    # seeded before order headers existed, so that data keeps working
    # exactly as before.
    order_id = Column(Integer, nullable=True, index=True)

    # Menu price captured at the moment of purchase. Historical rows do
    # not have this; the service falls back to total_price for them.
    unit_price = Column(Float, nullable=True)

    # Needed by the ML modules: every forecast is a time series.
    created_at = Column(DateTime, default=datetime.utcnow)


# =========================================================
# RESERVATION
# =========================================================

class Reservation(Base):
    __tablename__ = "reservations"

    id = Column(Integer, primary_key=True, index=True)

    customer_name = Column(String(100), nullable=False)

    # Contact email so the guest can be reached about the booking
    customer_email = Column(String(100), nullable=True)

    table_number = Column(Integer, nullable=False)

    reservation_date = Column(Date, nullable=False)

    reservation_time = Column(Time, nullable=False)

    guests = Column(Integer, nullable=False)

    # Pending / Booked / Completed / Cancelled
    status = Column(String(20), default="Pending")

    # e.g. window seat, birthday celebration, high chair
    special_request = Column(Text, nullable=True)

    # The signed-in account that made the booking.
    user_id = Column(Integer, nullable=True, index=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    # Phase 6C. Lets a reservation's own history be read rather than only
    # its current status.
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


# =========================================================
# USER
# =========================================================

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)

    name = Column(String(100), nullable=False)

    email = Column(String(100), unique=True, nullable=False)

    password = Column(String(255), nullable=False)

    role = Column(String(20), default="customer")

    loyalty_points = Column(Integer, default=0)

    # A deactivated account keeps its history but cannot sign in or
    # call any protected endpoint. server_default matters here: an
    # ALTER TABLE ADD COLUMN on a NOT NULL column with only a python
    # side default fills existing rows with 0, which would deactivate
    # every account already in the table.
    active = Column(
        Boolean,
        nullable=False,
        default=True,
        server_default="1",
    )

    # Links a login account to its CRM customer record. The 537 seeded
    # orders were written against customers.name, so this is what makes
    # that history attributable to a real signed-in user.
    customer_id = Column(Integer, nullable=True, index=True)

    # The table this guest is currently seated at, set by scanning a
    # table QR and claiming it server side. This is the authority for
    # which table an order belongs to - the client never chooses it.
    active_table_id = Column(Integer, nullable=True, index=True)


# =========================================================
# CUSTOMER
# =========================================================

class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)

    name = Column(String(100), nullable=False)

    email = Column(String(100), unique=True, nullable=False)

    phone = Column(String(20), nullable=False)

    address = Column(String(255))

    total_orders = Column(Integer, default=0)

    total_spent = Column(Float, default=0.0)

    loyalty_points = Column(Integer, default=0)

    created_at = Column(DateTime, default=datetime.utcnow)


# =========================================================
# INVENTORY
# =========================================================

class Inventory(Base):
    __tablename__ = "inventory"

    id = Column(Integer, primary_key=True, index=True)

    item_name = Column(String(100), nullable=False)

    category = Column(String(50))

    quantity = Column(Float, nullable=False, default=0)

    unit = Column(String(30))

    minimum_stock = Column(Float, default=0)

    supplier = Column(String(100))

    cost_per_unit = Column(Float, default=0.0)

    created_at = Column(DateTime)


# =========================================================
# KITCHEN / KITCHEN DISPLAY SYSTEM
# =========================================================

class Kitchen(Base):
    __tablename__ = "kitchen"

    id = Column(Integer, primary_key=True, index=True)

    order_id = Column(Integer, nullable=False)

    customer_name = Column(String(100))

    menu_item = Column(String(100), nullable=False)

    quantity = Column(Integer, nullable=False, default=1)

    status = Column(String(50), default="Pending")

    priority = Column(String(30), default="Normal")

    notes = Column(Text)

    created_at = Column(DateTime)


# =========================================================
# SETTINGS
# =========================================================

class Settings(Base):
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, index=True)

    restaurant_name = Column(
        String(150),
        default="Restaurant"
    )

    restaurant_address = Column(String(255))

    phone = Column(String(20))

    email = Column(String(100))

    currency = Column(String(10), default="INR")

    tax_percentage = Column(Float, default=5.0)

    service_charge_percentage = Column(Float, default=0.0)

    opening_time = Column(String(20))

    closing_time = Column(String(20))

    notifications_enabled = Column(Boolean, default=True)

    ai_enabled = Column(Boolean, default=True)

# =========================================================
# REVIEW  (feeds the sentiment-analysis module)
# =========================================================

class Review(Base):
    __tablename__ = "reviews"

    id = Column(Integer, primary_key=True, index=True)

    customer_name = Column(String(100), nullable=False)

    menu_item = Column(String(100))

    rating = Column(Integer, default=5)

    comment = Column(Text, nullable=False)

    # Filled in automatically by ml/sentiment.py
    sentiment = Column(String(20), default="Neutral")

    sentiment_score = Column(Float, default=0.0)

    # The signed-in account that wrote the review.
    user_id = Column(Integer, nullable=True, index=True)

    created_at = Column(DateTime, default=datetime.utcnow)


# =========================================================
# RESTAURANT TABLE
#
# One row per physical table. A printed QR carries only qr_token,
# which is a random public identifier: it reveals nothing about the
# database, a user, or any credential, and it can be rotated without
# changing the table number.
# =========================================================

class RestaurantTable(Base):
    __tablename__ = "restaurant_tables"

    id = Column(Integer, primary_key=True, index=True)

    # The number printed on the table and shown to guests.
    table_number = Column(Integer, unique=True, nullable=False, index=True)

    table_name = Column(String(100), nullable=True)

    capacity = Column(Integer, default=4, nullable=False)

    # dining room / terrace / balcony / private room
    section = Column(String(50), nullable=True)

    # Random, unique, non-guessable. Only this ever appears in a QR.
    qr_token = Column(String(64), unique=True, nullable=True, index=True)

    # An inactive table keeps its history but cannot start an order.
    # server_default matters: a NOT NULL column added to a populated
    # table would otherwise default to 0 and deactivate everything.
    is_active = Column(
        Boolean,
        nullable=False,
        default=True,
        server_default="1",
    )

    created_at = Column(DateTime, default=datetime.utcnow)

    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


# =========================================================
# ORDER HEADER
#
# One row per checkout. The individual dishes stay in `orders`,
# pointing back here through orders.order_id, so the historical
# one-row-per-dish data is untouched.
#
# Every money column is written by the server from menu.price. No
# value in this table is ever taken from the client.
# =========================================================

class OrderHeader(Base):
    __tablename__ = "order_headers"

    id = Column(Integer, primary_key=True, index=True)

    # Public reference shown to the guest and printed on the kitchen
    # ticket, e.g. "A-1001".
    reference = Column(String(20), unique=True, nullable=False)

    # The signed-in account that owns this order.
    user_id = Column(Integer, nullable=True, index=True)

    # Denormalised for display only; ownership always uses user_id.
    customer_name = Column(String(100), nullable=False)

    customer_email = Column(String(100), nullable=True)

    # dine-in / takeaway / delivery
    order_type = Column(String(20), default="dine-in")

    table_number = Column(Integer, nullable=True)

    # The RestaurantTable this order was placed at, set from the
    # authenticated guest's server-side table claim. NULL on every
    # historical order, which is left untouched rather than guessed at.
    table_id = Column(Integer, nullable=True, index=True)

    delivery_address = Column(String(255), nullable=True)

    notes = Column(Text, nullable=True)

    # ---- server-calculated money ----

    subtotal = Column(Float, nullable=False, default=0.0)

    tax_percentage = Column(Float, nullable=False, default=0.0)

    tax_amount = Column(Float, nullable=False, default=0.0)

    service_charge_percentage = Column(Float, nullable=False, default=0.0)

    service_charge_amount = Column(Float, nullable=False, default=0.0)

    discount_amount = Column(Float, nullable=False, default=0.0)

    discount_reason = Column(String(100), nullable=True)

    total_amount = Column(Float, nullable=False, default=0.0)

    # Read from the settings table, never from the client.
    currency = Column(String(10), default="UNSET")

    # ---- lifecycle ----

    # Placed / Confirmed / Preparing / Ready / Served / Cancelled
    status = Column(String(20), default="Placed")

    # unpaid / pending / paid / failed / refunded
    # Phase 3 writes this when the payment gateway confirms a charge.
    payment_status = Column(String(20), default="unpaid")

    placed_at = Column(DateTime, default=datetime.utcnow)

    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    # ---- Phase 6C lifecycle timestamps ----
    #
    # NULL on every historical row, and deliberately left that way. These
    # record when a transition actually happened; filling them in from
    # `updated_at` or from `placed_at` would be inventing a moment the
    # database never witnessed. The full history of transitions lives in
    # `restaurant_events`, which is written from now on.
    status_changed_at = Column(DateTime, nullable=True)

    # Set once when the food actually reached the guest.
    completed_at = Column(DateTime, nullable=True)

    # Set only by a payment provider confirmation. Nothing in this
    # project sets it yet, and that is the correct state: an order being
    # served does not make it paid.
    paid_at = Column(DateTime, nullable=True)


# =========================================================
# SUPPLIER
# =========================================================

class Supplier(Base):
    __tablename__ = "suppliers"

    id = Column(Integer, primary_key=True, index=True)

    name = Column(String(100), nullable=False)

    contact_person = Column(String(100))

    phone = Column(String(20))

    email = Column(String(100))

    category = Column(String(50))

    address = Column(String(255))

    created_at = Column(DateTime, default=datetime.utcnow)


# =========================================================
# STAFF
# =========================================================

class Staff(Base):
    __tablename__ = "staff"

    id = Column(Integer, primary_key=True, index=True)

    name = Column(String(100), nullable=False)

    role = Column(String(50))

    phone = Column(String(20))

    email = Column(String(100))

    shift = Column(String(30), default="Morning")

    salary = Column(Float, default=0.0)

    active = Column(Boolean, default=True)

    joined_on = Column(Date)


# =========================================================
# FOOD WASTE  (feeds the waste-analysis module)
# =========================================================

class Waste(Base):
    __tablename__ = "waste"

    id = Column(Integer, primary_key=True, index=True)

    item_name = Column(String(100), nullable=False)

    quantity = Column(Float, nullable=False, default=0)

    unit = Column(String(30), default="kg")

    reason = Column(String(100))

    cost = Column(Float, default=0.0)

    recorded_at = Column(DateTime, default=datetime.utcnow)


# =========================================================
# PAYMENT LEDGER   (Phase 6D)
# =========================================================
#
# WHAT THIS IS, AND WHAT IT IS NOT
# -------------------------------
# This is a ledger of payment *attempts and outcomes*. It is not a second
# source of truth for what a bill costs. That remains
# `OrderHeader.total_amount`, which the server computed from menu prices
# when the order was placed.
#
# `amount` and `currency` are therefore copies of that authoritative
# figure, taken when the payment request was created. They are stored so
# the ledger records what was actually requested, and they are re-checked
# against the header on every verification. If the two ever disagree, the
# verification is refused rather than resolved in either direction.
#
# WHY A LEDGER RATHER THAN THE payment_status COLUMN
# -------------------------------------------------
# `OrderHeader.payment_status` is a single word: it cannot say which
# attempt succeeded, how many failed, what the provider called it, or
# when. It stays as the one-line answer the customer bill displays, and it
# is only ever written by the verification path below.
#
# `OrderHeader.paid_at` is set at the same moment, from the verified
# timestamp, and never when a request is merely created.

class PaymentStatus:
    """
    The complete set of payment states. Nothing outside this list.

    PENDING   a request exists; no provider outcome has arrived
    SUCCESS   the provider confirmed this payment
    FAILED    the provider reported this payment as not taken
    CANCELLED the attempt was abandoned before any outcome

    There is no "assumed", "likely" or "pending review" state on purpose.
    Anything short of a provider confirmation stays PENDING, which is the
    honest description of a QR that has been displayed and possibly
    scanned.
    """

    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

    ALL = (PENDING, SUCCESS, FAILED, CANCELLED)

    #: States from which a further attempt is still meaningful.
    OPEN = (PENDING, FAILED)


class PaymentMethod:
    UPI = "UPI"
    CASH = "CASH"

    ALL = (UPI, CASH)


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)

    # The bill this payment is for. RESTRICT rather than CASCADE: a paid
    # bill must not disappear because its order row was removed, because
    # that would erase the only evidence money changed hands.
    order_id = Column(
        Integer,
        ForeignKey("order_headers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # The public order reference, copied for readability. The header row
    # remains authoritative; this is never used to look anything up.
    order_reference = Column(String(20), nullable=True, index=True)

    # ---- the money ----
    #
    # Copied from OrderHeader.total_amount at request time. Never accepted
    # from a request body.
    amount = Column(Float, nullable=False)

    # Copied from OrderHeader.currency. Never accepted from a request body.
    currency = Column(String(10), nullable=False, default="UNSET")

    method = Column(String(20), nullable=False, default=PaymentMethod.UPI)

    # "development" now; a real provider name later. Stored so a ledger
    # row says which system produced its outcome.
    provider = Column(String(40), nullable=False, default="development")

    # The provider's own identifier for this attempt, e.g.
    # "DEV-PAY-3f9a1c2b4d55". UNIQUE, because a provider reference is how
    # a real webhook would be matched to this row.
    #
    # It is an identifier, never proof. Only verify_payment can move this
    # row out of PENDING.
    provider_reference = Column(
        String(80), nullable=True, unique=True, index=True
    )

    # Phase 7F. A second provider identifier, for the case where they are
    # genuinely different things.
    #
    # For Razorpay, `provider_reference` holds the *order* id created when
    # the request was made, and `provider_payment_reference` holds the
    # *payment* id that arrives when money moves. Reconciliation and
    # support both need the payment id, and it only exists after the
    # fact, so it cannot share the column.
    #
    # NULL for the development provider, which has one identifier.
    provider_payment_reference = Column(String(80), nullable=True, index=True)

    status = Column(
        String(20),
        nullable=False,
        default=PaymentStatus.PENDING,
        index=True,
    )

    requested_at = Column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    # Set from the provider's confirmed settlement time. NULL while
    # pending - the difference between "asked for" and "paid".
    paid_at = Column(DateTime, nullable=True)

    # Why a provider rejected it. Free text from the provider, so it is
    # only ever displayed, never interpreted.
    failure_reason = Column(Text, nullable=True)

    created_at = Column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    __table_args__ = (
        # The ledger's two hot queries: "what is outstanding on this
        # bill" and "what did we collect in this period".
        Index("ix_payments_order_status", "order_id", "status"),
        Index("ix_payments_status_requested", "status", "requested_at"),
    )

    # ---- helpers, not columns ----

    @property
    def is_settled(self) -> bool:
        return self.status == PaymentStatus.SUCCESS

    @property
    def is_open(self) -> bool:
        return self.status in PaymentStatus.OPEN


# =========================================================
# RECEIVED WEBHOOK EVENTS   (Phase 7F)
# =========================================================
#
# WHY THIS TABLE IS NECESSARY
# ---------------------------
# A payment provider delivers the same event more than once. That is
# normal, not an attack, and the settlement path must survive it - which
# it does, because a payment that is already SUCCESS is left alone. What
# the payment row alone cannot answer is "did we already receive *this*
# event?".
#
# Two things need that:
#
#   1. Idempotent acknowledgement. The second delivery is answered as
#      already processed, with no second PAYMENT_SUCCEEDED event and no
#      second change to paid_at.
#   2. An audit trail. When a merchant and the provider disagree, the
#      first question is what actually arrived. Without a record of the
#      raw event, that question cannot be answered after the fact.
#
# The provider's `event_id` is UNIQUE, so a duplicate cannot even be
# inserted twice - the database enforces idempotency rather than relying
# on application code alone.
#
# Only the fields needed for reconciliation are stored, plus the payload
# with credential-shaped keys stripped. A webhook payload carries no
# secret, but the same sanitiser as the event log is applied anyway so
# that a future provider field cannot quietly start storing one.

class WebhookProcessResult:
    """What happened when a received event was processed."""

    APPLIED = "applied"
    DUPLICATE = "duplicate"
    IGNORED = "ignored"
    REFUSED = "refused"


class PaymentWebhookEvent(Base):
    __tablename__ = "payment_webhook_events"

    id = Column(Integer, primary_key=True, index=True)

    # The provider's own event identifier, e.g. "evt_abc123". UNIQUE: this
    # is the idempotency guarantee.
    event_id = Column(String(120), unique=True, index=True)

    provider = Column(String(40), nullable=False, default="razorpay")

    event_type = Column(String(60), nullable=False, index=True)

    # The local payment the event was matched to, when it matched.
    payment_id = Column(Integer, nullable=True, index=True)
    order_id = Column(Integer, nullable=True, index=True)

    # APPLIED / DUPLICATE / IGNORED / REFUSED.
    result = Column(String(20), nullable=False)

    # A short note for an operator. Never a signature, never a secret.
    detail = Column(String(300), nullable=True)

    metadata_json = Column(JSON, nullable=True)

    received_at = Column(
        DateTime, default=datetime.utcnow, nullable=False, index=True
    )

    __table_args__ = (
        Index("ix_webhook_events_provider_result", "provider", "result"),
    )


# =========================================================
# OPERATIONAL EVENT HISTORY   (Phase 6C)
# =========================================================
#
# WHY THIS TABLE EXISTS
# ---------------------
# The tables above hold *current state*. An order row says an order is
# `Served`; it does not say when it was placed, when the kitchen started,
# how long it waited, or whether it was ever cancelled. Inventory holds a
# quantity with no record of what changed it. A reservation holds a status
# with no record of how it got there.
#
# Without that history, four questions simply cannot be answered at all:
# how long does preparation take, how often are orders cancelled, what
# has been restocked this week, and what actually happened yesterday.
#
# WHY ONE TABLE
# -------------
# Everything writes here - order transitions, reservations, inventory
# movements, waste, reviews, payment events - distinguished by
# `entity_type` and named by `event_type`. A separate OrderEvent,
# InventoryEvent, WasteEvent and ReservationEvent would be four copies of
# the same mechanism, and any question spanning two of them would need a
# union across tables that does not exist.
#
# WHAT IS DELIBERATELY NOT HERE
# -----------------------------
# * No backfill. A historical transition was never recorded, so its
#   timestamp would be a guess. History starts when recording starts.
# * No denormalised money or quantities. This is a log of what happened,
#   not a second source of truth for what it cost.

class RestaurantEvent(Base):
    __tablename__ = "restaurant_events"

    id = Column(Integer, primary_key=True, index=True)

    # ORDER_PLACED / ORDER_CONFIRMED / ORDER_PREPARING / ORDER_READY /
    # ORDER_SERVED / ORDER_CANCELLED / PAYMENT_CREATED / PAYMENT_SUCCESS /
    # PAYMENT_FAILED / RESERVATION_CREATED / RESERVATION_CANCELLED /
    # DELIVERY_STARTED / DELIVERY_COMPLETED / INVENTORY_UPDATED /
    # WASTE_RECORDED / REVIEW_CREATED
    event_type = Column(String(50), nullable=False, index=True)

    # order / reservation / inventory / waste / review / payment
    entity_type = Column(String(30), nullable=False, index=True)

    # Primary key within the entity's own table.
    entity_id = Column(Integer, nullable=True, index=True)

    # The account that caused it, when there was one. NULL for a
    # system-recorded event such as a stock count.
    actor_user_id = Column(Integer, nullable=True, index=True)

    # Small, non-sensitive facts about the event. Never a credential, a
    # password hash, a token, or a SQL fragment.
    metadata_json = Column(JSON, nullable=True)

    created_at = Column(
        DateTime, default=datetime.utcnow, index=True, nullable=False
    )
from pydantic import BaseModel, EmailStr, Field, field_validator
from datetime import date, time
from typing import Optional


class _QuantityGuard:
    """
    Shared quantity rule for every order payload.

    `bool` is a subclass of `int` in Python, so `True` would otherwise be
    read as "one portion". A JSON `true` is a malformed order, not a
    request for a single dish, so it is refused here rather than being
    quietly turned into a quantity of one.
    """

    @field_validator("quantity", mode="before")
    @classmethod
    def _reject_boolean_quantity(cls, value):
        if isinstance(value, bool):
            raise ValueError("quantity must be a whole number, not true/false")

        return value



# =========================================================
# MENU SCHEMA
# =========================================================

class MenuCreate(BaseModel):
    name: str
    category: Optional[str] = None
    price: float
    image_url: Optional[str] = None
    available: bool = True
    description: Optional[str] = None
    is_vegetarian: bool = True
    is_featured: bool = False
    spice_level: int = 0
    prep_time: int = 15


class MenuBulkUpdate(BaseModel):
    """Applies one change to many menu items at once."""

    ids: list[int]

    available: Optional[bool] = None
    is_featured: Optional[bool] = None
    is_vegetarian: Optional[bool] = None
    category: Optional[str] = None


class ImageUpload(BaseModel):
    """A base64 encoded dish image."""

    data: str
    file_name: Optional[str] = None
    content_type: Optional[str] = None


# =========================================================
# ORDER SCHEMA
# =========================================================

class OrderCreate(_QuantityGuard, BaseModel):
    """
    The legacy order payload.

    Phase 6A. Fields are grouped by how much the server trusts them.

    TRUSTWORTHY - the client decides these:
        menu_id / menu_item   which dish
        quantity              how many portions
        special_instructions  how to cook it
        notes, delivery_address, order_type

    ACCEPTED BUT IGNORED - kept only so an older client is not rejected:
        customer_name  identity comes from the JWT
        total_price    money comes from menu.price
        unit_price     money comes from menu.price
        currency       money's currency comes from the settings table
        image_url      a snapshot taken from menu.image_url

    `status` is likewise never taken from here: a new order is always
    Placed, because the lifecycle is server-driven.
    """

    # Either address works. An id is preferred because a dish name is not
    # unique; the service refuses an ambiguous name rather than guessing.
    menu_id: Optional[int] = None
    menu_item: Optional[str] = None

    quantity: int

    # ---- accepted for backwards compatibility, never used ----
    customer_name: Optional[str] = None
    total_price: Optional[float] = None
    unit_price: Optional[float] = None
    currency: Optional[str] = None
    # ---------------------------------------------------

    status: str = "Pending"
    order_type: str = "dine-in"
    table_number: Optional[int] = None
    delivery_address: Optional[str] = None
    notes: Optional[str] = None
    special_instructions: Optional[str] = None
    image_url: Optional[str] = None


class CartOrderCreate(BaseModel):
    """
    A full cart placed in one request.

    Priced by the server exactly like /checkout. Any price inside an
    item, and any total at this level, is discarded.
    """

    customer_name: Optional[str] = None
    items: list[OrderCreate]
    order_type: str = "dine-in"
    table_number: Optional[int] = None
    delivery_address: Optional[str] = None
    notes: Optional[str] = None
    # Accepted and ignored: the settings row is the only currency source.
    currency: Optional[str] = None


class CheckoutLine(_QuantityGuard, BaseModel):
    """
    One requested dish.

    Deliberately has no price field. The server prices every line from
    menu.price, so a price here would simply be discarded.
    """

    menu_item_id: int
    quantity: int
    special_instructions: Optional[str] = None


class RestaurantTableCreate(BaseModel):
    """Admin creates a physical table."""

    table_number: int
    table_name: Optional[str] = None
    capacity: int = 4
    section: Optional[str] = None
    is_active: bool = True


class RestaurantTableUpdate(BaseModel):
    """Admin edits a table. table_number is included so it can be moved."""

    table_number: Optional[int] = None
    table_name: Optional[str] = None
    capacity: Optional[int] = None
    section: Optional[str] = None
    is_active: Optional[bool] = None


class TablePublicInfo(BaseModel):
    """
    What the entry page may show before anyone signs in.

    No qr_token, no id, no internal flags.
    """

    table_number: int
    table_name: Optional[str] = None
    capacity: Optional[int] = None
    section: Optional[str] = None
    restaurant_name: Optional[str] = None


class TableClaimRequest(BaseModel):
    """A signed-in guest claiming the table whose QR they scanned."""

    table_token: str


class CustomerBillLine(BaseModel):
    order_id: int
    reference: Optional[str] = None
    menu_item: str
    quantity: int
    unit_price: Optional[float] = None
    line_total: float
    special_instructions: Optional[str] = None


class CustomerBillResponse(BaseModel):
    """
    The bill for the guest's current table visit.

    `payment_status` is reported from the order header. It is never
    accepted from the client, and in this phase it stays UNPAID because
    no payment gateway exists yet.
    """

    table_number: Optional[int] = None
    restaurant_name: Optional[str] = None
    orders: list[CustomerBillLine]
    item_count: int
    subtotal: float
    tax_percentage: float
    tax_amount: float
    service_charge_percentage: float
    service_charge_amount: float
    discount_amount: float
    total_amount: float
    currency: str
    payment_status: str
    payment_available: bool
    food_statuses: list[str]


class CheckoutRequest(BaseModel):
    """
    A cart submitted for server-side pricing.

    There is intentionally no subtotal, tax, discount, total, price,
    customer_id or user_id field. Anything the browser puts in those
    positions is ignored - and because Pydantic drops unknown keys, a
    client that sends them simply has them discarded.
    """

    items: list[CheckoutLine]
    order_type: str = "dine-in"
    table_number: Optional[int] = None
    delivery_address: Optional[str] = None
    notes: Optional[str] = None


# =========================================================
# ORDER STATUS TRANSITION SCHEMAS
# =========================================================

class OrderStatusUpdate(BaseModel):
    """Admin/Kitchen updates an order status."""

    status: str


class OrderStatusResponse(BaseModel):
    """Response for order status operations."""

    order_id: int
    reference: Optional[str] = None
    status: str
    payment_status: str
    message: str
    valid_next_statuses: list[str]


# =========================================================
# RESERVATION SCHEMA
# =========================================================

class ReservationCreate(BaseModel):
    customer_name: str
    table_number: int
    reservation_date: date
    reservation_time: time
    guests: int
    customer_email: Optional[str] = None
    status: str = "Pending"
    special_request: Optional[str] = None


class ReservationStatusUpdate(BaseModel):
    """Admin changes a booking to Booked / Completed / Cancelled."""

    status: str


# =========================================================
# USER SCHEMA
# =========================================================

class UserCreate(BaseModel):
    name: str
    email: EmailStr
    password: str


# =========================================================
# CUSTOMER SCHEMA
# =========================================================

class CustomerCreate(BaseModel):
    name: str
    email: EmailStr
    phone: str
    address: Optional[str] = None

    total_orders: int = 0
    total_spent: float = 0.0


# =========================================================
# INVENTORY SCHEMA
# =========================================================

class InventoryCreate(BaseModel):
    item_name: str

    category: Optional[str] = None

    quantity: float = 0

    unit: Optional[str] = None

    minimum_stock: float = 0

    supplier: Optional[str] = None

    cost_per_unit: float = 0.0


# =========================================================
# KITCHEN SCHEMA
# =========================================================

class KitchenCreate(BaseModel):
    order_id: int

    customer_name: Optional[str] = None

    menu_item: str

    quantity: int = 1

    status: str = "Pending"

    priority: str = "Normal"

    notes: Optional[str] = None


class KitchenUpdate(BaseModel):
    status: Optional[str] = None

    priority: Optional[str] = None

    notes: Optional[str] = None


# =========================================================
# SETTINGS SCHEMA
# =========================================================

class SettingsCreate(BaseModel):
    restaurant_name: str = "Restaurant"

    restaurant_address: Optional[str] = None

    phone: Optional[str] = None

    email: Optional[EmailStr] = None

    currency: str = "INR"

    tax_percentage: float = 5.0

    service_charge_percentage: float = 0.0

    opening_time: Optional[str] = None

    closing_time: Optional[str] = None

    notifications_enabled: bool = True

    ai_enabled: bool = True


class SettingsUpdate(BaseModel):
    restaurant_name: Optional[str] = None

    restaurant_address: Optional[str] = None

    phone: Optional[str] = None

    email: Optional[EmailStr] = None

    currency: Optional[str] = None

    tax_percentage: Optional[float] = None

    service_charge_percentage: Optional[float] = None

    opening_time: Optional[str] = None

    closing_time: Optional[str] = None

    notifications_enabled: Optional[bool] = None

    ai_enabled: Optional[bool] = None

# =========================================================
# REVIEW SCHEMA
# =========================================================

class ReviewCreate(BaseModel):
    customer_name: str
    menu_item: Optional[str] = None
    rating: int = 5
    comment: str


# =========================================================
# SUPPLIER SCHEMA
# =========================================================

class SupplierCreate(BaseModel):
    name: str
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    category: Optional[str] = None
    address: Optional[str] = None


# =========================================================
# STAFF SCHEMA
# =========================================================

class StaffCreate(BaseModel):
    name: str
    role: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    shift: str = "Morning"
    salary: float = 0.0
    active: bool = True
    joined_on: Optional[date] = None


# =========================================================
# WASTE SCHEMA
# =========================================================

class WasteCreate(BaseModel):
    item_name: str
    quantity: float
    unit: str = "kg"
    reason: Optional[str] = None
    cost: float = 0.0


# =========================================================
# AUTH SCHEMAS
# =========================================================

class RegisterRequest(BaseModel):
    name: str
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

    user: dict


# =========================================================
# AI REQUEST SCHEMAS
# =========================================================

class SentimentRequest(BaseModel):
    text: str
    


# =========================================================
# PHASE 5 - AI RECOMMENDATION SCHEMAS
#
# Responses are declared rather than returned as bare dicts, so a
# missing or renamed field fails loudly instead of reaching the
# frontend as undefined.
# =========================================================

class RecommendationReason(BaseModel):
    kind: str
    text: str


class RecommendedDish(BaseModel):
    menu_id: Optional[int] = None
    name: str
    category: Optional[str] = None
    price: float = 0.0
    availability: bool = True
    score: float = 0.0
    reason: str = ""
    reasons: list[RecommendationReason] = []
    score_breakdown: Optional[dict] = None
    image_url: Optional[str] = None
    is_vegetarian: Optional[bool] = None
    prep_time: Optional[int] = None


class TrendingDish(BaseModel):
    menu_id: Optional[int] = None
    name: str
    category: Optional[str] = None
    price: float = 0.0
    availability: bool = True
    portions_sold_today: int = 0
    score: float = 0.0
    reason: str = ""


class SimilarDish(BaseModel):
    menu_id: Optional[int] = None
    name: str
    category: Optional[str] = None
    price: float = 0.0
    availability: bool = True
    similarity: float = 0.0
    score: float = 0.0
    reason: str = ""


class RecommendationScoring(BaseModel):
    """How the score was produced, so it is auditable."""

    weights: dict
    score_range: list
    # Always False. `score` is a ranking value, not a calibrated
    # probability, and the API refuses to imply otherwise.
    score_is_confidence: bool = False
    method: str
    uses_customer_history: bool = False


class PersonalizedRecommendation(BaseModel):
    """GET /api/ai/recommend/me"""

    personalized: list[RecommendedDish] = []
    trending_today: list[TrendingDish] = []
    similar_items: list[SimilarDish] = []
    has_history: bool = False
    orders_analyzed: int = 0
    distinct_dishes_ordered: int = 0
    reason: str = ""
    generated_from: dict
    scoring: RecommendationScoring
    # Stated plainly when the answer is weaker than it looks.
    limitations: list[str] = []
    today: Optional[dict] = None


# =========================================================
# PHASE 5 - ANALYTICS RESPONSE SCHEMAS
# =========================================================

class RevenueWindow(BaseModel):
    range: Optional[str] = None
    start_date: str
    end_date: str
    revenue: float = 0.0
    orders: int = 0
    portions: int = 0
    average_order_value: float = 0.0
    revenue_breakdown: dict = {}


class RevenuePoint(BaseModel):
    date: str
    revenue: float = 0.0
    orders: int = 0
    portions: int = 0


class RevenueTrend(BaseModel):
    range: str
    start_date: str
    end_date: str
    days: int = 0
    data: list[RevenuePoint] = []
    total_revenue: float = 0.0
    total_orders: int = 0
    average_order_value: float = 0.0
    best_day: Optional[dict] = None
    has_data: bool = False


class SalesSummary(BaseModel):
    range: str
    start_date: str
    end_date: str
    revenue: float = 0.0
    orders: int = 0
    portions_sold: int = 0
    order_lines: int = 0
    average_order_value: float = 0.0
    average_portion_price: float = 0.0
    has_data: bool = False


class TopDish(BaseModel):
    dish: str
    menu_id: Optional[int] = None
    category: Optional[str] = None
    quantity_sold: int = 0
    revenue: float = 0.0
    times_ordered: int = 0
    current_price: Optional[float] = None
    available: Optional[bool] = None


class TopDishesResponse(BaseModel):
    range: str
    start_date: str
    end_date: str
    limit: int = 5
    top_dishes: list[TopDish] = []
    has_data: bool = False


class CategoryRevenue(BaseModel):
    category: str
    quantity_sold: int = 0
    revenue: float = 0.0


class CategoryRevenueResponse(BaseModel):
    range: str
    start_date: str
    end_date: str
    categories: list[CategoryRevenue] = []
    total_revenue: float = 0.0
    has_data: bool = False


class OrderStatusSummary(BaseModel):
    lifecycle: dict
    other_statuses: dict = {}
    active_orders: int = 0
    total_orders: int = 0
    payment: dict = {}
    # Served and unpaid is a valid state in this restaurant and is
    # reported rather than reconciled.
    served_unpaid_orders: int = 0
    has_data: bool = False


class WastageItem(BaseModel):
    item_name: str
    quantity: float = 0.0
    cost: float = 0.0
    entries: int = 0


class WastagePoint(BaseModel):
    date: str
    cost: float = 0.0
    quantity: float = 0.0


class WastageSummary(BaseModel):
    range: str
    start_date: str
    end_date: str
    total_cost: float = 0.0
    total_quantity: float = 0.0
    items: list[WastageItem] = []
    highest_wastage_item: Optional[WastageItem] = None
    trend: list[WastagePoint] = []
    has_data: bool = False


class InventoryEntry(BaseModel):
    item_name: str
    category: Optional[str] = None
    quantity: float = 0.0
    minimum_stock: float = 0.0
    unit: Optional[str] = None
    supplier: Optional[str] = None
    cost_per_unit: float = 0.0
    shortfall: float = 0.0


class InventorySummary(BaseModel):
    total_items: int = 0
    available_count: int = 0
    low_stock_count: int = 0
    out_of_stock_count: int = 0
    low_stock_items: list[InventoryEntry] = []
    out_of_stock_items: list[InventoryEntry] = []
    total_stock_value: float = 0.0
    has_data: bool = False


class CustomerSummary(BaseModel):
    total_customers: int = 0
    total_users: int = 0
    distinct_order_names: int = 0
    repeat_customers: int = 0
    orders_linked_to_accounts: int = 0
    top_spenders: list[dict] = []
    reservations: int = 0
    has_data: bool = False


class AnalyticsOverview(BaseModel):
    generated_at: str
    today: dict
    yesterday: dict
    # None rather than 0 when yesterday had no revenue, because a jump
    # from nothing is not a 0% change.
    revenue_change_percent: Optional[float] = None
    inventory: dict
    order_lifecycle: dict
    active_orders: int = 0
    served_orders: int = 0
    pending_orders: int = 0
    payment: dict
    unpaid_served_orders: int = 0
    all_time: dict
    has_data: bool = False


# =========================================================
# PHASE 5 - AI BUSINESS ASSISTANT SCHEMAS
# =========================================================

class AssistantQuestion(BaseModel):
    question: str


class AssistantChart(BaseModel):
    """Chart data for the assistant to render exactly as returned."""

    type: str = "bar"
    title: str = ""
    labels: list[str] = []
    values: list[float] = []
    value_label: str = ""


class AssistantTable(BaseModel):
    columns: list[str] = []
    rows: list[list] = []


class AssistantResponse(BaseModel):
    intent: Optional[str] = None
    # False means the question was not understood. The answer is then a
    # refusal and carries no metrics.
    answered: bool = False
    answer: str
    chart: Optional[AssistantChart] = None
    table: Optional[AssistantTable] = None
    metrics: dict = {}
    has_data: bool = False
    question: Optional[str] = None
    params: Optional[dict] = None
    supported_intents: list[str] = []
    suggestions: list[str] = []
    range: Optional[str] = None


# =========================================================
# PHASE 6B - RESTAURANT-WIDE AI OPERATIONS ASSISTANT
#
# A separate schema, and a separate endpoint, from AssistantResponse
# above. The Phase 5 assistant answers one closed intent at a time and
# its intent field is asserted by the Phase 5 suite; this one answers
# open questions by combining several data sources.
# =========================================================

class OperationsQuestion(BaseModel):
    """
    One free-text question about the restaurant.

    context is the conversation memory returned by the previous call.
    It is optional and carries only the resolved window and the domains
    behind it - never the question text.
    """

    question: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="A natural-language question about the restaurant.",
    )

    @field_validator("question", mode="before")
    @classmethod
    def _reject_blank_question(cls, value):
        """
        A question of only whitespace is not a question.

        `min_length` counts characters, so "   " would otherwise satisfy
        it and reach the router as an empty prompt. Refusing it here stops
        it before any tool is planned.
        """
        if isinstance(value, str) and not value.strip():
            raise ValueError("question must not be blank")

        return value

    context: Optional[dict] = Field(
        None,
        description=(
            "The context object from the previous answer in this "
            "conversation, or null to start a new one."
        ),
    )


class OperationsWindow(BaseModel):
    """The period the answer actually describes."""

    start_date: Optional[str] = None
    end_date: Optional[str] = None
    label: Optional[str] = None
    source: Optional[str] = None
    inherited: bool = False


class OperationsDataSource(BaseModel):
    """One data source that contributed to the answer."""

    tool: str
    domain: str
    description: str


class OperationsAnswer(BaseModel):
    """
    The composed answer, split so a reader can tell what kind of claim
    each part is making.
    """

    question: Optional[str] = None
    answer: str
    greeting: bool = False

    # A one-line headline, or null when the data did not support one.
    conclusion: Optional[str] = None

    # Figures read from the database. Each traceable to a data source.
    key_numbers: list[str] = []

    # Arithmetic over those figures. Still factual.
    observations: list[str] = []

    # What the data suggests, phrased as a suggestion. Never a claim of
    # cause unless a source for the cause was actually retrieved.
    inference: list[str] = []

    # Advice, labelled as a recommendation.
    recommendations: list[str] = []

    # What could not be answered, and why. Never omitted just because it
    # is inconvenient.
    limitations: list[str] = []

    data_sources: list[OperationsDataSource] = []
    window: Optional[OperationsWindow] = None
    domains: list[str] = []
    tools_used: list[str] = []
    tools_without_data: list[str] = []

    answered: bool = False
    has_data: bool = False

    capabilities: list[dict] = []
    context: dict = {}

    plan: Optional[dict] = None
    generated_at: Optional[str] = None

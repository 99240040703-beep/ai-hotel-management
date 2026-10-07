import React, { useState, useEffect } from "react";
import { QRCodeSVG } from "qrcode.react";
import {
 getMenu,
 quoteCart,
 checkoutCart,
 getMyOrders,
 getTableContext,
 getMyBill,
 getMyBillHistory,
 createPaymentRequest,
 getPayment,
 verifyPayment,
 cancelPayment,
 getMyActiveOrder,
 getMyRecommendations,
 createReservation,
 getMyReservations,
 createReview,
 getReviews,
 getPopularDishes,
 classifySentiment,
} from "./api";
import { getDishImage, isVegItem, spiceLabel } from "./dishImages";
import { formatMoney } from "./money";
import AppShell from "./AppShell";

// ============================================================
// ORDER LIFECYCLE
//
// These names are the ones the backend stores in
// OrderHeader.status. They are read from the server on every poll and
// never invented here: the screen shows the status the restaurant
// actually recorded, and a stage is only lit up once the API has
// reported it.
//
// Payment is NOT part of this flow. A guest pays after they leave, so
// an order can reach "Served"and still be unpaid, and nothing below
// infers one from the other.
// ============================================================

const ORDER_STATUSES = [
 "Placed",
 "Confirmed",
 "Preparing",
 "Ready",
 "Served",
];

// The statuses the server treats as "still in progress", i.e. the order
// a guest can watch live.
const ACTIVE_ORDER_STATUSES = [
 "Placed",
 "Confirmed",
 "Preparing",
 "Ready",
];

const CANCELLED_ORDER_STATUS = "Cancelled";

const LIFECYCLE_STAGES = [
 { key: "Placed", label: "Placed", icon: "" },
 { key: "Confirmed", label: "Confirmed", icon: "" },
 { key: "Preparing", label: "Preparing", icon: "" },
 { key: "Ready", label: "Ready", icon: "" },
 { key: "Served", label: "Served", icon: "" },
];

// Plain wording for each status, so the guest is told what the
// restaurant's own record says rather than a guessed ETA.
const STATUS_MESSAGES = {
 Placed: "Your order has been placed and is awaiting confirmation.",
 Confirmed: "Restaurant confirmed your order. Kitchen will start shortly.",
 Preparing: "Your food is being prepared.",
 Ready: "Your order is ready. Server is delivering to your table.",
 Served: "Enjoy your meal!",
 Cancelled: "This order has been cancelled.",
};

// ============================================================
// PHASE 5 - ONE RECOMMENDED DISH
//
// A thin renderer over the API's dish object. It shows the reason only
// when the backend sent one, and labels the score as a score: this
// system computes a ranking value, not a confidence probability, so
// there is deliberately no "98% match"anywhere.
// ============================================================
function RecCard({ dish, trending = false }) {
 const reasons = dish.reasons || [];

 return (
 <article className="recs-card">
 <div className="recs-card-top">
 {dish.image_url ? (
 <img
 src={dish.image_url}
 alt={dish.name}
 className="recs-card-image"
 loading="lazy"
 />
 ) : (
 <div className="recs-card-image recs-card-image-fallback">
 {null}
 </div>
 )}

 <div className="recs-card-head">
 <h4>{dish.name}</h4>

 {dish.category && (
 <span className="recs-card-category">{dish.category}</span>
 )}
 </div>

 {dish.is_vegetarian && (
 <span className="recs-veg-dot"title="Vegetarian">
 
 </span>
 )}
 </div>

 {/* Reasons are evidence the backend actually had. The primary
 reason is always shown when present; extras are listed. */}
 {reasons.length > 0 && (
 <ul className="recs-reasons">
 {reasons.map((reason, index) => (
 <li key={index} className={`recs-reason recs-reason-${reason.kind}`}>
 {reason.text}
 </li>
 ))}
 </ul>
 )}

 {trending && dish.portions_sold_today > 0 && (
 <span className="recs-trending-badge">
 {dish.portions_sold_today} sold today
 </span>
 )}

 <div className="recs-card-foot">
 <span className="recs-score"title="Ranking score out of 1. Not a confidence.">
 Score {(dish.score ?? 0).toFixed(2)}
 </span>

 <strong className="recs-price">{formatMoney(dish.price)}</strong>
 </div>

 {dish.prep_time ? (
 <span className="recs-prep">~{dish.prep_time} min</span>
 ) : null}
 </article>
 );
}

function CustomerPortal({ user, onLogout }) {
 const [activeTab, setActiveTab] = useState("menu"); // menu, cart, tracking, reservations, reviews, loyalty
 const [menu, setMenu] = useState([]);
 const [loading, setLoading] = useState(true);
 // Phase 5 personalized recommendations, resolved from the JWT by the
 // backend. Loading and error are tracked separately so a failure shows
 // a message instead of an empty list that looks like "nothing to
 // recommend".
 const [recommendations, setRecommendations] = useState(null);
 const [recsLoading, setRecsLoading] = useState(false);
 const [recsError, setRecsError] = useState("");
 const [popularDishes, setPopularDishes] = useState([]);

 // Filter & Search
 const [searchQuery, setSearchQuery] = useState("");
 const [selectedCategory, setSelectedCategory] = useState("All");
 const [dietFilter, setDietFilter] = useState("all"); // all, veg, nonveg
 const [sortBy, setSortBy] = useState("recommended"); // recommended, price-low, price-high, fastest
 const [hideUnavailable, setHideUnavailable] = useState(false);
 const [favourites, setFavourites] = useState(() => {
 try {
 const saved = JSON.parse(
 localStorage.getItem("restaurant_favourites") || "[]"
 );

 return Array.isArray(saved) ? saved : [];
 } catch {
 return [];
 }
 });

 // Multi-select: tick dishes and add them to the cart in one go
 const [selectedDishes, setSelectedDishes] = useState([]);

 // Dish quick view
 const [previewItem, setPreviewItem] = useState(null);

 // Cart & Ordering
 const [cart, setCart] = useState([]);
 const [orderType, setOrderType] = useState("dine-in"); // dine-in, takeaway, delivery
 const [tableNumber, setTableNumber] = useState("4");
 const [deliveryAddress, setDeliveryAddress] = useState("");
 const [orderNotes, setOrderNotes] = useState("");
 // Server-priced checkout summary from POST /api/orders/quote.
 const [quote, setQuote] = useState(null);
 const [quoteError, setQuoteError] = useState("");

 const [orderSuccessMsg, setOrderSuccessMsg] = useState("");
 const [isSubmittingOrder, setIsSubmittingOrder] = useState(false);

 // Live Orders
 const [myOrders, setMyOrders] = useState([]);

 // Reservations
 const [resForm, setResForm] = useState({
 table_number: 2,
 reservation_date: new Date().toISOString().split("T")[0],
 reservation_time: "19:30",
 guests: 2,
 special_request: "Window table if possible",
 });
 const [resSuccessMsg, setResSuccessMsg] = useState("");
 const [myReservations, setMyReservations] = useState([]);

 // Reviews & Sentiment
 const [reviewForm, setReviewForm] = useState({
 menu_item: "Chicken Biryani",
 rating: 5,
 comment: "The food was delicious, super fresh and served hot!",
 });
 const [liveSentiment, setLiveSentiment] = useState(null);
 const [reviewSuccessMsg, setReviewSuccessMsg] = useState("");
 const [recentReviews, setRecentReviews] = useState([]);

// Loyalty
 //
 // Earning and redemption are not configured on the server yet, so
 // there is deliberately no balance here. This is not read from the
 // database because no such column is written yet - the loyalty
 // phase will replace it with GET /api/customer/loyalty.
 const loyaltyPoints = 0;

 // Which table this guest is sitting at, as reported by the server.
 // Never taken from browser storage: the claim lives on the users
 // row, so a tampered localStorage cannot move the guest.
 const [tableContext, setTableContext] = useState(null);

// The bill for the current visit. Read-only - there is no payment
 // gateway in this phase.
 const [bill, setBill] = useState(null);

 // Phase 6E. Which of the two bill views is showing, plus the history
 // itself. History is fetched when the guest opens it rather than with the
 // rest of the portal, so opening the menu does not pull every past bill.
 const [billView, setBillView] = useState("visit");
 const [history, setHistory] = useState(null);
 const [historyError, setHistoryError] = useState("");

 // Declared here rather than further down: loadHistory below resets this
 // spinner, and reading it before its declaration is a temporal dead
 // zone reference that throws the moment the history view is opened.
 const [billLoading, setBillLoading] = useState(false);

 const loadHistory = async () => {
 try {
 setBillLoading(true);
 setHistoryError("");
 setHistory(await getMyBillHistory(50));
 } catch (err) {
 console.error("Failed to load bill history:", err);
 setHistoryError(
 err.response?.data?.detail || "Could not load your bill history.",
 );
 } finally {
 setBillLoading(false);
 }
 };

 useEffect(() => {
 if (billView === "history") {
 loadHistory();
 }
 }, [billView]);

 // Active order for live tracking (from order headers)
 const [activeOrder, setActiveOrder] = useState(null);

 const customerName = user?.name || "Guest";

 useEffect(() => {
 loadInitialData();
 }, []);

 // Live sentiment analysis debounced
 useEffect(() => {
 if (!reviewForm.comment || reviewForm.comment.trim().length < 4) {
 setLiveSentiment(null);
 return;
 }
 const timer = setTimeout(async () => {
 try {
 const res = await classifySentiment(reviewForm.comment);
 setLiveSentiment(res);
 } catch (e) {
 console.error("Live sentiment check error:", e);
 }
 }, 400);
 return () =>clearTimeout(timer);
 }, [reviewForm.comment]);

 const loadInitialData = async () => {
 try {
 setLoading(true);
 const [menuData, ordersData, recData, popData, reviewsData, reservationsData] =
 await Promise.allSettled([
 getMenu(),
 getMyOrders(),
 // Phase 5: recommendations now come from the account in the
 // JWT rather than from a display name in the URL. The old
 // name-based call could be pointed at another guest's taste
 // profile; this endpoint cannot.
 getMyRecommendations(8),
 getPopularDishes(4),
 getReviews(),
 // The guest's own bookings. This used to call the admin list,
 // which answers 403 for a customer, so a guest's reservations
 // silently never loaded.
 getMyReservations(),
 ]);

 if (menuData.status === "fulfilled") {
 const menuItems = menuData.value || [];
 setMenu(menuItems);

 if (menuItems.length > 0) {
 setReviewForm((previous) => ({
 ...previous,
 menu_item: menuItems[0].name,
 }));
 }
 }
 if (ordersData.status === "fulfilled") {
 setMyOrders(ordersData.value || []);
 }
 if (recData.status === "fulfilled") {
 setRecommendations(recData.value || null);
 }
 if (popData.status === "fulfilled") {
 setPopularDishes(popData.value?.popular_dishes || []);
 }
 if (reviewsData.status === "fulfilled") {
 setRecentReviews(reviewsData.value || []);
 }
 if (reservationsData.status === "fulfilled") {
 const allRes = reservationsData.value || [];
 const userRes = allRes.filter(
 (r) =>r.customer_name?.toLowerCase() === customerName.toLowerCase()
 );
 setMyReservations(userRes);
 }
 } catch (err) {
 console.error("Error loading customer portal data:", err);
 } finally {
 setLoading(false);
 }
 };

 // Refresh only the live tracking list
 const refreshOrders = async () => {
 try {
 const updatedOrders = await getMyOrders();
 setMyOrders(updatedOrders || []);
 } catch (err) {
 console.error("Failed to refresh orders:", err);
 }
 };

 // The table this guest is attached to, straight from the API. The
 // server decides, so this is display only.
 const refreshTableContext = async () => {
 try {
 const data = await getTableContext();
 setTableContext(data.table);
 } catch (err) {
 console.error("Failed to load table context:", err);
 }
 };

 // Fetch active order for live tracking
 const refreshActiveOrder = async () => {
 try {
 const data = await getMyActiveOrder();
 setActiveOrder(data.active_order || null);
 } catch (err) {
 console.error("Failed to load active order:", err);
 setActiveOrder(null);
 }
 };

 // ============================================================
 // PHASE 5 - PERSONALIZED RECOMMENDATIONS
 //
 // The request carries no customer id. The backend takes the account
 // from the JWT, so this guest can only ever be shown their own
 // history. Every field rendered below - the score, the reason text and
 // the availability - comes from that response; nothing is derived in
 // the browser and there is no placeholder list behind an error.
 // ============================================================
 const refreshRecommendations = async () => {
 try {
 setRecsLoading(true);
 setRecsError("");

 const data = await getMyRecommendations(8);

 setRecommendations(data);
 } catch (err) {
 console.error("Failed to load recommendations:", err);

 setRecommendations(null);
 setRecsError(
 err.response?.data?.detail || "Could not load recommendations."
 );
 } finally {
 setRecsLoading(false);
 }
 };

 // Which table this guest is at, decided by the server's claim on their
 // account rather than anything the browser kept. Read on load so the
 // banner is right from the first paint.
 useEffect(() => {
 refreshTableContext();
 refreshActiveOrder();
 }, []);

 // Poll the tracking tab so the stage on screen is the stage the
 // restaurant actually recorded, rather than whatever it said when the
 // page loaded. Polling is enough here: there is no websocket in this
 // project and one is not needed to follow a five-step lifecycle.
 //
 // It only runs while the guest is looking at the tracking tab and
 // there is still an order in progress, so an idle tab makes no
 // requests, and stops on its own once the order reaches a terminal
 // status.
 useEffect(() => {
 if (activeTab !== "tracking") return;

 if (!activeOrder) return;

 if (!ACTIVE_ORDER_STATUSES.includes(activeOrder.status)) return;

 const interval = setInterval(refreshActiveOrder, 15000);

 return () =>clearInterval(interval);
 }, [activeTab, activeOrder]);

 const refreshBill = async () => {
 try {
 setBillLoading(true);
 setBill(await getMyBill());
 } catch (err) {
 console.error("Failed to load bill:", err);
 } finally {
 setBillLoading(false);
 }
 };

 /* ============================================================
 PAYMENT (Phase 6D)

 Everything the guest sees here comes from the server. There is no
 client-side success path: `payState.status` only ever becomes SUCCESS
 because the backend verified it with the provider, and the only way
 this component learns that is by calling verifyPayment and reading
 the reply.
 ============================================================ */

 // `payment` holds the server's payment record verbatim. It is never
 // mutated locally.
 const [payState, setPayState] = useState({
 payment: null,
 status: "",
 amount: null,
 currency: "INR",
 upiUri: null,
 failureReason: null,
 providerReference: null,
 busy: false,
 error: "",
 });

 const resetPayState = () =>
 setPayState({
 payment: null,
 status: "",
 amount: null,
 currency: "INR",
 upiUri: null,
 failureReason: null,
 providerReference: null,
 busy: false,
 error: "",
 });

 // Adopt whatever payment the bill already has, so a guest who leaves the
 // screen and comes back sees the real state rather than an empty form.
 //
 // The effect depends only on `bill`. Re-entrancy is handled inside the
 // state updater rather than by reading current state here, so this
 // cannot fetch on every render.
 useEffect(() => {
 const existing = bill?.pending_payment_id;

 if (!bill || bill.payment_status === "PAID" || !existing) {
 resetPayState();
 return;
 }

 let cancelled = false;

 getPayment(existing)
 .then((data) => {
 if (cancelled) return;

 setPayState((previous) =>
 previous.payment?.payment_id === existing
 ? previous
 : {
 ...previous,
 payment: data,
 status: data.status,
 amount: data.amount,
 currency: data.currency,
 // The server re-issues the UPI instructions for an open
 // attempt, so the QR survives a page reload.
 upiUri: data.request?.upi_uri ?? null,
 failureReason: data.failure_reason,
 providerReference: data.provider_reference,
 },
 );
 })
 .catch((err) => {
 if (cancelled) return;

 console.error("Failed to read payment state:", err);
 resetPayState();
 });

 return () => {
 cancelled = true;
 };
 }, [bill]);

 // Which payment surface is active, and in what mode. Read from the
 // server, never assumed: with the development provider a guest scans a
 // UPI QR, with Razorpay they complete a checkout window.
 const providerLabel = (
 bill?.payment_gateway?.provider === "razorpay"
 ? "razorpay"
 : ""
 );

 const providerMode = bill?.payment_gateway?.live_mode
 ? "LIVE"
 : bill?.payment_gateway?.test_mode
 ? "TEST"
 : null;

 const applyPayment = (data) =>
 setPayState((previous) => ({
 ...previous,
 payment: data,
 status: data.status,
 amount: data.amount,
 currency: data.currency,
 upiUri:
 data.status === "PENDING"
 ? (data.request?.upi_uri ?? previous.upiUri)
 : null,
 failureReason: data.failure_reason,
 providerReference: data.provider_reference,
 error: "",
 }));

 const startPayment = async () => {
 // The first unpaid bill is the one to request payment for. The amount
 // is never computed here - the server reads it from the order header.
 const target = bill?.orders?.[0];

 if (!target) return;

 try {
 setPayState((previous) => ({ ...previous, busy: true, error: "" }));

 const data = await createPaymentRequest(target.order_id);

 applyPayment(data);

 await refreshBill();
 } catch (err) {
 setPayState((previous) => ({
 ...previous,
 busy: false,
 error:
 err.response?.data?.detail ||
 "Could not start a payment. Please ask the restaurant for help.",
 }));
 }
 };

 const checkPayment = async () => {
 if (!payState.payment?.payment_id) return;

 try {
 setPayState((previous) => ({ ...previous, busy: true, error: "" }));

 const data = await verifyPayment(payState.payment.payment_id);

 applyPayment(data);

 // A confirmed payment changes the bill, so re-read it.
 if (data.status === "SUCCESS") {
 await refreshBill();
 }
 } catch (err) {
 setPayState((previous) => ({
 ...previous,
 busy: false,
 error:
 err.response?.data?.detail ||
 "Could not check the payment. Please try again.",
 }));
 } finally {
 setPayState((previous) => ({ ...previous, busy: false }));
 }
 };

 const discardPayment = async () => {
 if (!payState.payment?.payment_id) return;

 try {
 setPayState((previous) => ({ ...previous, busy: true, error: "" }));

 await cancelPayment(payState.payment.payment_id);

 resetPayState();

 await refreshBill();
 } catch (err) {
 setPayState((previous) => ({
 ...previous,
 busy: false,
 error: err.response?.data?.detail || "Could not cancel the request.",
 }));
 }
 };

 // Cart operations
 const addToCart = (item) => {
 setCart((prev) => {
 const existing = prev.find((c) =>c.id === item.id);
 if (existing) {
 return prev.map((c) =>
 c.id === item.id ? { ...c, quantity: c.quantity + 1 } : c
 );
 }
 return [...prev, { ...item, quantity: 1, specifications: "" }];
 });
 };

 const addManyToCart = (items) => {
 setCart((prev) => {
 const next = [...prev];

 items.forEach((item) => {
 const existing = next.find((c) =>c.id === item.id);

 if (existing) {
 const index = next.indexOf(existing);
 next[index] = { ...existing, quantity: existing.quantity + 1 };
 } else {
 next.push({ ...item, quantity: 1, specifications: "" });
 }
 });

 return next;
 });
 };

 const updateCartQty = (id, delta) => {
 setCart((prev) =>
 prev
 .map((c) => {
 if (c.id === id) {
 const newQty = c.quantity + delta;
 return newQty > 0 ? { ...c, quantity: newQty } : null;
 }
 return c;
 })
 .filter(Boolean)
 );
 };

 const updateCartSpecifications = (id, specs) => {
 setCart((prev) =>
 prev.map((c) =>
 c.id === id ? { ...c, specifications: specs } : c
 )
 );
 };

 const toggleFavourite = (itemId) => {
 setFavourites((previous) => {
 const next = previous.includes(itemId)
 ? previous.filter((id) =>id !== itemId)
 : [...previous, itemId];

 localStorage.setItem("restaurant_favourites", JSON.stringify(next));

 return next;
 });
 };

 const toggleDishSelected = (itemId) => {
 setSelectedDishes((previous) =>
 previous.includes(itemId)
 ? previous.filter((id) =>id !== itemId)
 : [...previous, itemId]
 );
 };

 const selectedMenuItems = menu.filter((item) =>
 selectedDishes.includes(item.id)
 );

 const addSelectedToCart = () => {
 const orderable = selectedMenuItems.filter(
 (item) =>item.available !== false
 );

 if (orderable.length === 0) {
 alert("None of the selected dishes are available right now.");
 return;
 }

 addManyToCart(orderable);

 setSelectedDishes([]);
 setActiveTab("cart");
 };

 const cartTotalItems = cart.reduce((sum, item) =>sum + item.quantity, 0);

 // ---------------------------------------------------------------
 // MONEY IS SERVER-AUTHORITATIVE
 //
 // Nothing below computes a price. `quote` is the response from
 // POST /api/orders/quote, which prices the cart from menu.price and
 // applies settings.tax_percentage on the server. The browser only
 // displays what comes back.
 //
 // The local subtotal is retained purely as a fallback for the few
 // milliseconds before the first quote returns, and it is never used
 // as the amount that gets charged.
 // ---------------------------------------------------------------
 const localSubtotalFallback = cart.reduce(
 (sum, item) =>sum + Number(item.price) * item.quantity,
 0
 );

 const cartSubtotal = quote?.subtotal ?? localSubtotalFallback;
 const cartTax = quote?.tax_amount ?? 0;
 const cartServiceCharge = quote?.service_charge_amount ?? 0;
 const cartDiscount = quote?.discount_amount ?? 0;
 const cartTaxRate = quote?.tax_percentage ?? null;
 const cartGrandTotal = quote?.total_amount ?? cartSubtotal;
 const quoteCurrency = quote?.currency ?? null;
 const quoteIsSettled = Boolean(quote);

 // Estimated wait time = slowest dish in the cart
 const cartWaitTime = cart.reduce(
 (slowest, item) =>Math.max(slowest, Number(item.prep_time) || 0),
 0
 );

 // Everything this guest has ever ordered at the restaurant.
 // Counts are grouped by the status the backend reports. A dish is
 // never counted twice just because its order was cancelled after the
 // fact, but the order itself still appears in history.
 const isLiveOrder = (order) =>order.status !== CANCELLED_ORDER_STATUS;

 const myOrderStats = {
 totalOrders: myOrders.length,
 liveOrders: myOrders.filter((order) =>
 ACTIVE_ORDER_STATUSES.includes(order.status)
 ).length,
 completedOrders: myOrders.filter(
 (order) =>order.status === "Served"
 ).length,
 cancelledOrders: myOrders.filter(
 (order) =>order.status === CANCELLED_ORDER_STATUS
 ).length,
 dishesOrdered: myOrders
 .filter(isLiveOrder)
 .reduce((sum, order) =>sum + (Number(order.quantity) || 0), 0),
 totalSpent: myOrders
 .filter(isLiveOrder)
 .reduce((sum, order) =>sum + (Number(order.total_price) || 0), 0),
 visits: new Set(
 myOrders
 .filter(isLiveOrder)
 .map((order) =>String(order.created_at || "").slice(0, 10))
 .filter(Boolean)
 ).size,
 favourite: myOrders.reduce((best, order) => {
 const name = order.menu_item || "Dish";
 const seen = best[name] || { count: 0, quantity: 0 };

 seen.count += 1;
 seen.quantity += Number(order.quantity) || 0;

 return { ...best, [name]: seen };
 }, {}),
 };

 const favouriteDish = Object.entries(myOrderStats.favourite).sort(
 (a, b) =>b[1].quantity - a[1].quantity
 )[0];

 const [historyFilter, setHistoryFilter] = useState("all");

 // ---- the greeting ----
 //
 // Time of day comes from the browser clock. It is a greeting, not a
 // measurement about the restaurant, so it is presentation and stays out
 // of every API call.
 const greetingPeriod = (() => {
 const hour = new Date().getHours();

 if (hour < 12) return "Good morning";
 if (hour < 17) return "Good afternoon";
 if (hour < 21) return "Good evening";

 return "Good evening";
 })();

 // The time of day on its own, for the heading. `greetingPeriod` already
 // carries the word "Good", so the heading cannot repeat it.
 const greetingWord = greetingPeriod.replace(/^Good\s+/i, "");

 // A guest's registered name can be "Ananya Sharma"; a greeting that says
 // "Good evening, Ananya Sharma"is correct but reads like a form field.
 const firstName = (customerName || "Guest").trim().split(/\s+/)[0];

 // The payload the server prices. It carries ids and quantities only -
 // no price, no total, no customer identity.
 const buildCheckoutPayload = () => ({
 items: cart.map((item) => ({
 menu_item_id: item.id,
 quantity: item.quantity,
 special_instructions: item.specifications || null,
 })),
 order_type: orderType,
 table_number:
 orderType === "dine-in" && !tableContext
 ? Number(tableNumber)
 : null,
 delivery_address:
 orderType === "delivery" ? deliveryAddress.trim() : null,
 notes: orderNotes.trim() || null,
 });

 // Re-price on the server whenever the cart or the order details change,
 // so every figure on screen came from menu.price and the settings row.
 useEffect(() => {
 // With an empty cart there is nothing to price. Clearing the quote
 // is handled where the cart is emptied, so this path just returns.
 if (cart.length === 0) {
 return;
 }

 if (orderType === "delivery" && !deliveryAddress.trim()) {
 return;
 }

 let cancelled = false;

 const refreshQuote = async () => {
 try {
 const priced = await quoteCart(buildCheckoutPayload());

 if (!cancelled) {
 setQuote(priced);
 setQuoteError("");
 }
 } catch (err) {
 if (cancelled) return;

 setQuote(null);
 setQuoteError(
 err.response?.data?.detail ||
 "Could not price this cart. Please try again.",
 );
 }
 };

 refreshQuote();

 return () => {
 cancelled = true;
 };
 }, [cart, orderType, tableNumber, deliveryAddress, orderNotes]);

 // Submit Order - the whole cart goes to the kitchen in one request
 const handlePlaceOrder = async (e) => {
 e.preventDefault();
 if (cart.length === 0) return;

 if (orderType === "delivery" && !deliveryAddress.trim()) {
 alert("Please enter a delivery address.");
 return;
 }

 try {
 setIsSubmittingOrder(true);
 setOrderSuccessMsg("");

 // The server re-prices the cart, writes the order header and its
 // lines, and returns the authoritative total. The figure the guest
 // was shown above is the same figure that gets charged.
 const result = await checkoutCart(buildCheckoutPayload());

 setOrderSuccessMsg(
 ` Order ${
 result.reference || ""
 } placed successfully! ${result.orders_created} item(s) sent to the kitchen. Total charged: ${formatMoney(
 result.total_amount,
 result.currency,
 )}.`
 );

 setCart([]);
 setOrderNotes("");
 setQuote(null);

 await refreshOrders();

 setTimeout(() => {
 setActiveTab("tracking");
 }, 1500);
 } catch (err) {
 console.error("Failed to place order:", err);
 alert(
 err.response?.data?.detail || "Failed to place order. Please try again."
 );
 } finally {
 setIsSubmittingOrder(false);
 }
 };

 // Submit Reservation
 const handlePlaceReservation = async (e) => {
 e.preventDefault();
 try {
 setResSuccessMsg("");
 await createReservation({
 customer_name: customerName,
 table_number: Number(resForm.table_number),
 reservation_date: resForm.reservation_date,
 reservation_time: resForm.reservation_time,
 guests: Number(resForm.guests),
 });

 setResSuccessMsg("Table reservation confirmed! We look forward to hosting you.");
 const updatedRes = await getMyReservations();
 // /mine is already scoped to the signed-in account, so these are
 // the guest's own rows with no further filtering needed.
 setMyReservations(updatedRes || []);
 } catch (err) {
 console.error("Reservation error:", err);
 alert("Failed to create reservation.");
 }
 };

 // Submit Review
 const handlePlaceReview = async (e) => {
 e.preventDefault();
 try {
 setReviewSuccessMsg("");
 await createReview({
 customer_name: customerName,
 menu_item: reviewForm.menu_item,
 rating: Number(reviewForm.rating),
 comment: reviewForm.comment,
 });

 setReviewSuccessMsg("Thank you! Your review and AI sentiment analysis were saved.");
 setReviewForm((previous) => ({ ...previous, comment: "" }));
 setLiveSentiment(null);

 const updatedReviews = await getReviews();
 setRecentReviews(updatedReviews);
 } catch (err) {
 console.error("Review error:", err);
 alert("Failed to submit review.");
 }
 };

 // Filter Menu
 const categories = ["All", ...new Set(menu.map((m) =>m.category).filter(Boolean))];

 const featuredDishes = menu.filter((item) =>item.is_featured);

 const filteredMenu = menu
 .filter((item) => {
 const matchesCategory =
 selectedCategory === "All" || item.category === selectedCategory;
 const term = searchQuery.trim().toLowerCase();
 const matchesSearch =
 !term ||
 item.name.toLowerCase().includes(term) ||
 (item.category || "").toLowerCase().includes(term) ||
 (item.description || "").toLowerCase().includes(term);
 const itemIsVeg = isVegItem(item);
 const matchesDiet =
 dietFilter === "all" ||
 (dietFilter === "veg" && itemIsVeg) ||
 (dietFilter === "nonveg" && !itemIsVeg);
 const matchesAvailability = !hideUnavailable || item.available !== false;
 return matchesCategory && matchesSearch && matchesDiet && matchesAvailability;
 })
 .sort((a, b) => {
 if (sortBy === "price-low") return Number(a.price) - Number(b.price);
 if (sortBy === "price-high") return Number(b.price) - Number(a.price);
 if (sortBy === "fastest") {
 return (Number(a.prep_time) || 99) - (Number(b.prep_time) || 99);
 }

 // "recommended" - featured dishes first, then the rest by name
 if (Boolean(b.is_featured) !== Boolean(a.is_featured)) {
 return b.is_featured ? 1 : -1;
 }

 return a.name.localeCompare(b.name);
 });

 // Customer-only navigation. These screens belong to the customer
 // portal alone and are never shown to an admin. The shell is shared with
 // the admin portal; only the contents differ.
 const customerNavItems = [
 {
 key: "overview",
 label: "Overview",
 description: "Your table and your evening",
 icon: "overview",
 group: "Your Evening",
 badge: myOrderStats.liveOrders || 0,
 },
 {
 key: "menu",
 label: "Digital Menu",
 description: "Everything we are serving",
 icon: "menu",
 group: "Your Evening",
 },
 {
 key: "recommendations",
 label: "Recommended for You",
 description: "Picked from your own orders",
 icon: "spark",
 group: "Your Evening",
 badge: recommendations?.personalized?.length || 0,
 },
 {
 key: "cart",
 label: "Cart & Checkout",
 description: "Review before you send it",
 icon: "cart",
 group: "Your Evening",
 badge: cartTotalItems,
 },
 {
 key: "tracking",
 label: "My Orders",
 description: "From the pass to your table",
 icon: "orders",
 group: "Your Evening",
 badge: myOrders.length,
 },
 {
 key: "reservations",
 label: "Reservations",
 description: "Book a table",
 icon: "calendar",
 group: "Your Evening",
 },
 {
 key: "bill",
 label: "Bill & Payment History",
 description: "This visit and every past one",
 icon: "receipt",
 group: "Your Account",
 },
 {
 key: "reviews",
 label: "Reviews",
 description: "Share how it went",
 icon: "star",
 group: "Your Account",
 },
 {
 key: "loyalty",
 label: "Loyalty & Rewards",
 description: "Rewards with the restaurant",
 icon: "gift",
 group: "Your Account",
 },
 {
 key: "settings",
 label: "Profile",
 description: "Your account",
 icon: "user",
 group: "Your Account",
 },
 ];

 // The page heading follows the same shape the admin pages use, so the
 // guest and the manager are reading the same product.
 const customerPages = {
 overview: {
 title: "Overview",
 subtitle: "Your table, your current order and what is owed.",
 },
 menu: {
 title: "Digital Menu",
 subtitle: "Everything the kitchen is serving tonight.",
 },
 recommendations: {
 title: "Recommended for You",
 subtitle: "Chosen from the dishes you have ordered before.",
 },
 cart: {
 title: "Cart & Checkout",
 subtitle: "Review the order, then send it to the kitchen.",
 },
 tracking: {
 title: "My Orders",
 subtitle: "Where your order is, from placed to served.",
 },
 reservations: {
 title: "Reservations",
 subtitle: "Book a table, and keep an eye on what is coming up.",
 },
 bill: {
 title: "Bill & Payment History",
 subtitle: "This visit, and every bill before it.",
 },
 reviews: {
 title: "Reviews",
 subtitle: "Tell us how the evening went.",
 },
 loyalty: {
 title: "Loyalty & Rewards",
 subtitle: "Rewards the restaurant offers its guests.",
 },
 settings: {
 title: "Profile",
 subtitle: "Your account details.",
 },
 };

 const activeCustomerPage = customerPages[activeTab] || customerPages.menu;

 const handleCustomerNav = (tab) => {
 setActiveTab(tab);

 // The bill changes as orders are placed, so it is re-read when the
 // guest opens it rather than only on first load.
 if (tab === "bill") {
 refreshBill();
 }

 // Recommendations are read fresh when the tab is opened so the list
 // reflects today's sales rather than whatever was loaded at sign-in.
 if (tab === "recommendations") {
 refreshRecommendations();
 }
 };

 return (
 <AppShell
 user={user}
 role="customer"
 navItems={customerNavItems}
 currentPage={activeTab}
 onNavigate={handleCustomerNav}
 onLogout={onLogout}
 sectionLabel="Guest Portal"
 pageEyebrow="Paradise Restaurant"
 pageTitle={activeCustomerPage.title}
 pageSubtitle={activeCustomerPage.subtitle}
 banner={
 /* The table stays visible on every screen. It is read back from
 the server, so it reflects the claim rather than anything
 the browser kept. */
 tableContext ? (
 <div className="table-context-bar">
 <span className="table-context-brand">
 {bill?.restaurant_name ||
 tableContext.restaurant_name ||
 "Paradise Restaurant"}
 </span>

 <span className="table-context-divider">|</span>

 <span className="table-context-table">
 Table {tableContext.table_number}
 {tableContext.table_name
 ? ` · ${tableContext.table_name}`
 : ""}
 </span>

 <small>
 Seats {tableContext.capacity}
 {tableContext.section ? ` · ${tableContext.section}` : ""}
 </small>
 </div>
 ) : null
 }
 >
 {/* =========================================================
 THE GREETING

 On every screen, not just the overview, so moving between
 tabs never feels like leaving the restaurant.
 ========================================================= */}
 <section className="cp-greeting">
 <span className="cp-greeting-eyebrow">
 {greetingPeriod} &middot; {tableContext
 ? `Table ${tableContext.table_number}`
 : "Paradise Restaurant"}
 </span>

 <h1>
 Good {greetingWord.toLowerCase()},{" "}
 <span className="gold-text">{firstName}</span>
 </h1>

 <p>Your dining experience, beautifully organized.</p>
 </section>

 {/* =========================================================
 0. OVERVIEW

 Every figure below is one the backend already returned. Where
 a value does not exist the card says so rather than showing a
 zero that would read as a real measurement.
 ========================================================= */}
 {activeTab === "overview" && (
 <div className="overview-tab-view">
 <div className="stats-grid">
 <div className="stat-card">
 <h3>Current order</h3>

                    {activeOrder ? (
                      <>
                        <strong className="gold order-reference">
                          {activeOrder.reference || `#${activeOrder.id}`}
                        </strong>


 <small>
 {activeOrder.status}
 {activeOrder.total_price
 ? ` · ${formatMoney(
 activeOrder.total_price,
 activeOrder.currency,
 )}`
 : ""}
 </small>
 </>
 ) : (
 <>
 <strong>—</strong>
 <small>
 Nothing in the kitchen right now. Order from the
 menu to start.
 </small>
 </>
 )}
 </div>

 <div className="stat-card">
 <h3>Outstanding bill</h3>

 {bill && bill.payment_status !== "PAID" ? (
 <>
 <strong className="gold">
 {formatMoney(
 bill.outstanding_amount ?? bill.total_amount,
 bill.currency,
 )}
 </strong>

 <small>
 {bill.bills_unpaid ?? 0} bill
 {(bill.bills_unpaid ?? 0) === 1 ? "" : "s"} unpaid
 </small>
 </>
 ) : (
 <>
 <strong className="collected">
 {formatMoney(0, bill?.currency)}
 </strong>

 <small>
 {bill
 ? "Everything at this table is settled."
 : "No bill for this visit yet."}
 </small>
 </>
 )}
 </div>

 <div className="stat-card">
 <h3>Reservations</h3>

 {myReservations.length > 0 ? (
 <>
 <strong>{myReservations.length}</strong>

 <small>
 {(() => {
 const next =
 myReservations.find(
 (row) =>row.status !== "Cancelled"
 )?.reservation_date;

 // The API returns an ISO date. A missing or
 // unparseable value prints the date rather than
 // "Invalid Date".
 if (!next) {
 return "Next booking to be confirmed";
 }

 const parsed = new Date(next);

 return Number.isNaN(parsed.getTime())
 ? `Next: ${next}`
 : `Next: ${parsed.toLocaleDateString("en-IN", {
 day: "numeric",
 month: "short",
 })}`;
 })()}
 </small>
 </>
 ) : (
 <>
 <strong>—</strong>
 <small>No tables booked yet.</small>
 </>
 )}
 </div>

 <div className="stat-card">
 <h3>Loyalty points</h3>

 <strong className="gold">{loyaltyPoints}</strong>

 <small>
 {/* Not fabricated: the portal shows the figure the
 project actually tracks, and says plainly when the
 earning rate is not configured. */}
 Points accumulate once the restaurant sets a rate.
 </small>
 </div>
 </div>

 {/* ---- where to go next ---- */}
 <div className="panel">
 <div className="panel-header">
 <h2>Your evening so far</h2>
 </div>

 <div className="status-list">
 <div className="status-item">
 <span className="status-label">Orders placed</span>

 <strong>{myOrderStats.totalOrders}</strong>
 </div>

 <div className="status-item">
 <span className="status-label">In the kitchen now</span>

 <strong>{myOrderStats.liveOrders}</strong>
 </div>

 <div className="status-item">
 <span className="status-label">Served</span>

 <strong>{myOrderStats.completedOrders}</strong>
 </div>

 <div className="status-item">
 <span className="status-label">Total spent</span>

 <strong>
 {formatMoney(myOrderStats.totalSpent)}
 </strong>
 </div>

 {favouriteDish && (
 <div className="status-item">
 <span className="status-label">Most ordered</span>

 <strong>{favouriteDish[0]}</strong>
 </div>
 )}
 </div>

 <div className="form-actions">
 <button
 className="primary-btn"
 onClick={() =>handleCustomerNav("menu")}
 >
 Browse the menu
 </button>

 {activeOrder && (
 <button
 className="secondary-btn"
 onClick={() =>handleCustomerNav("tracking")}
 >
 Track my order
 </button>
 )}

 <button
 className="secondary-btn"
 onClick={() =>handleCustomerNav("bill")}
 >
 Bill &amp; payment history
 </button>
 </div>
 </div>
 </div>
 )}

 {/* =========================================================
 1. DIGITAL MENU & AI RECOMMENDATIONS TAB
 ========================================================= */}
 {activeTab === "menu" && (
 <div className="menu-tab-view">
 {/* AI Recommendation Showcase */}
 {recommendations?.personalized?.length > 0 && (
 <section className="ai-recommendations-banner">
 <div className="ai-rec-header">
 <div>
 <span className="ai-kicker">AI Recommendation Engine</span>
 <h2>Recommended For You, {customerName}</h2>
 {/* The backend's own explanation of how this list was
 produced, rather than a fixed claim about "past
 orders and ratings"that may not be true for a
 guest with no history yet. */}
 <p>{recommendations.reason}</p>
 </div>
 <div className="ai-badge-chip">
 <span>
 {recommendations.scoring?.method || "Content-based ML"}
 </span>
 </div>
 </div>

 <div className="ai-rec-grid">
 {recommendations.personalized.map((rec, idx) => {
 const matched = menu.find(
 (m) =>m.name.toLowerCase() === rec.name?.toLowerCase()
 );

 return (
 <div className="ai-rec-card"key={rec.menu_id ?? idx}>
 <div className="ai-rec-img-wrap">
 <img
 src={getDishImage(matched || rec.name)}
 alt={rec.name}
 className="dish-photo"
 />
 {/* A ranking score, not a match probability. The
 old "% Match"label implied a confidence the
 model never produced. */}
 <span
 className="ai-match-badge"
 title="Ranking score out of 1. Not a confidence."
 >
 Score {(rec.score ?? 0).toFixed(2)}
 </span>
 </div>
 <div className="ai-rec-body">
 <div className="rec-title-row">
 <h4>{rec.name}</h4>
 <span className="rec-price">{formatMoney(rec.price)}</span>
 </div>
 <p className="rec-reason"> {rec.reason}</p>
 <button
 className="add-to-cart-btn-primary"
 onClick={() =>
 addToCart({
 id: matched?.id ?? rec.menu_id ?? `rec-${idx}`,
 name: rec.name,
 price: rec.price,
 category: rec.category,
 image_url: rec.image_url || matched?.image_url,
 prep_time: rec.prep_time ?? matched?.prep_time,
 })
 }
 >
 + Add to Cart
 </button>
 </div>
 </div>
 );
 })}
 </div>
 </section>
 )}

 {/* Chef's Featured Picks */}
 {featuredDishes.length > 0 && selectedCategory === "All" && !searchQuery && (
 <section className="featured-strip">
 <h3 className="featured-strip-title">Chef's Featured Picks</h3>

 <div className="featured-strip-grid">
 {featuredDishes.map((item) => (
 <button
 type="button"
 className="featured-chip"
 key={item.id}
 onClick={() =>setPreviewItem(item)}
 >
 <img
 src={getDishImage(item)}
 alt={item.name}
 loading="lazy"
 />
 <span>{item.name}</span>
 </button>
 ))}
 </div>
 </section>
 )}

 {/* Search & Filter Controls */}
 <div className="menu-filters-panel">
 <div className="search-box">
 <span className="search-icon"></span>
 <input
 type="text"
 placeholder="Search dishes, starters, desserts..."
 value={searchQuery}
 onChange={(e) =>setSearchQuery(e.target.value)}
 />
 {searchQuery && (
 <button
 className="clear-search-btn"
 onClick={() =>setSearchQuery("")}
 >
 ×
 </button>
 )}
 </div>

 <div className="diet-toggles">
 <button
 className={dietFilter === "all" ? "diet-chip active" : "diet-chip"}
 onClick={() =>setDietFilter("all")}
 >
 All Items
 </button>
 <button
 className={dietFilter === "veg" ? "diet-chip active veg" : "diet-chip veg"}
 onClick={() =>setDietFilter("veg")}
 >
 Veg Only
 </button>
 <button
 className={dietFilter === "nonveg" ? "diet-chip active nonveg" : "diet-chip nonveg"}
 onClick={() =>setDietFilter("nonveg")}
 >
 Non-Veg
 </button>
 </div>

 <div className="menu-sort-toggles">
 <label>
 Sort
 <select
 value={sortBy}
 onChange={(e) =>setSortBy(e.target.value)}
 >
 <option value="recommended">Recommended</option>
 <option value="price-low">Price: Low to High</option>
 <option value="price-high">Price: High to Low</option>
 <option value="fastest">Fastest to Prepare</option>
 </select>
 </label>

 <label className="hide-unavailable-toggle">
 <input
 type="checkbox"
 checked={hideUnavailable}
 onChange={(e) =>setHideUnavailable(e.target.checked)}
 />
 <span>Hide sold out</span>
 </label>
 </div>
 </div>

 {/* Category Pills */}
 <div className="category-pills">
 {categories.map((cat) => (
 <button
 key={cat}
 className={selectedCategory === cat ? "cat-pill active" : "cat-pill"}
 onClick={() =>setSelectedCategory(cat)}
 >
 {cat}
 </button>
 ))}
 </div>

 {/* Digital Menu Grid */}
 {filteredMenu.length === 0 ? (
 <div className="empty-state">
 <span className="empty-icon"></span>
 <h3>No dishes match your filters</h3>
 <p>Try another category, clear the search or turn off the sold out filter.</p>
 </div>
 ) : (
 <div className="digital-menu-grid">
 {filteredMenu.map((item) => {
 const veg = isVegItem(item);
 const inCart = cart.find((c) =>c.id === item.id);
 const isFavourite = favourites.includes(item.id);
 return (
 <div className="menu-card"key={item.id}>
 <div
 className="card-image-wrap"
 onClick={() =>setPreviewItem(item)}
 role="button"
 tabIndex={0}
 onKeyDown={(e) => {
 if (e.key === "Enter") setPreviewItem(item);
 }}
 >
 <img
 src={getDishImage(item)}
 alt={item.name}
 className="menu-card-img"
 loading="lazy"
 />
 <span className={`diet-badge ${veg ? "veg" : "non-veg"}`}>
 {veg ? "VEG" : "NON-VEG"}
 </span>
 {item.is_featured && (
 <span className="featured-ribbon">Featured</span>
 )}
 {item.available === false && (
 <span className="sold-out-overlay">Sold Out</span>
 )}
 <span className="card-zoom-hint">View dish</span>

 <label
 className="dish-select-box"
 onClick={(e) =>e.stopPropagation()}
 >
 <input
 type="checkbox"
 checked={selectedDishes.includes(item.id)}
 disabled={item.available === false}
 onChange={() =>toggleDishSelected(item.id)}
 aria-label={`Select ${item.name}`}
 />
 <span>Select</span>
 </label>
 </div>

 <div className="menu-card-content">
 <div className="card-header-row">
 <h3>{item.name}</h3>
 <span className="dish-price">{formatMoney(item.price)}</span>
 </div>

 <span className="dish-category">{item.category || "Special"}</span>

 <div className="dish-meta-row">
 <span> {spiceLabel(item.spice_level)}</span>
 <span> {item.prep_time || 0} min</span>
 </div>

 {item.description && (
 <p className="dish-description">{item.description}</p>
 )}

 <div className="card-actions">
 {inCart ? (
 <div className="cart-stepper">
 <button onClick={() =>updateCartQty(item.id, -1)}>−</button>
 <span>{inCart.quantity}</span>
 <button onClick={() =>updateCartQty(item.id, 1)}>+</button>
 </div>
 ) : (
 <button
 className="add-btn"
 disabled={item.available === false}
 onClick={() =>addToCart(item)}
 >
 {item.available === false ? "Unavailable" : "+ Add"}
 </button>
 )}

 <button
 className={isFavourite ? "fav-btn active" : "fav-btn"}
 onClick={() =>toggleFavourite(item.id)}
 title={
 isFavourite
 ? "Remove from favourites"
 : "Save to favourites"
 }
 >
 {isFavourite ? "" : ""}
 </button>
 </div>
 </div>
 </div>
 );
 })}
 </div>
 )}

 {/* Multi-Select Action Bar */}
 {selectedDishes.length > 0 && (
 <div className="selection-action-bar">
 <div className="selection-info">
 <strong>{selectedDishes.length} dish(es) selected</strong>
 <span>
 Estimated{" "}
 {selectedMenuItems.reduce(
 (slowest, item) =>
 Math.max(slowest, Number(item.prep_time) || 0),
 0
 )}{" "}
 min in the kitchen
 </span>
 </div>

 <div className="selection-buttons">
 <button
 className="secondary-btn"
 onClick={() =>setSelectedDishes([])}
 >
 Clear
 </button>

 <button
 className="primary-btn"
 onClick={addSelectedToCart}
 >
 Add selected to cart →
 </button>
 </div>
 </div>
 )}

 {/* Favourites Tray */}
 {favourites.length > 0 && (
 <section className="favourites-tray">
 <h3 className="featured-strip-title">
 Your Saved Dishes ({favourites.length})
 </h3>

 <div className="featured-strip-grid">
 {favourites
 .map((id) =>menu.find((m) =>m.id === id))
 .filter(Boolean)
 .map((item) => (
 <button
 type="button"
 className="featured-chip"
 key={item.id}
 onClick={() =>setPreviewItem(item)}
 >
 <img
 src={getDishImage(item)}
 alt={item.name}
 loading="lazy"
 />
 <span>{item.name}</span>
 </button>
 ))}
 </div>

 <button
 className="secondary-btn"
 onClick={() => {
 localStorage.setItem(
 "restaurant_favourites",
 JSON.stringify([])
 );
 setFavourites([]);
 }}
 >
 Clear saved dishes
 </button>
 </section>
 )}

 {/* Floating Cart Button */}
 {cartTotalItems > 0 && (
 <div className="floating-cart-bar">
 <div className="floating-cart-info">
 <span className="count">{cartTotalItems} items</span>
 <span className="divider">|</span>
 <span className="price">
 {formatMoney(cartGrandTotal, quoteCurrency)}
 </span>
 {cartWaitTime > 0 && (
 <span className="divider">|</span>
 )}
 {cartWaitTime > 0 && (
 <span className="wait-hint"> ~{cartWaitTime} min</span>
 )}
 </div>
 <button
 className="view-cart-btn"
 onClick={() =>setActiveTab("cart")}
 >
 Proceed to Checkout →
 </button>
 </div>
 )}

 {/* Dish Quick View Modal */}
 {previewItem && (
 <div
 className="dish-modal-backdrop"
 onClick={() =>setPreviewItem(null)}
 role="presentation"
 >
 <div
 className="dish-modal"
 onClick={(e) =>e.stopPropagation()}
 role="dialog"
 aria-modal="true"
 aria-label={previewItem.name}
 >
 <button
 className="dish-modal-close"
 onClick={() =>setPreviewItem(null)}
 aria-label="Close dish details"
 >
 ×
 </button>

 <img
 src={getDishImage(previewItem)}
 alt={previewItem.name}
 className="dish-modal-img"
 />

 <div className="dish-modal-body">
 <div className="dish-modal-tags">
 <span
 className={`diet-badge ${
 isVegItem(previewItem) ? "veg" : "non-veg"
 }`}
 >
 {isVegItem(previewItem) ? "VEG" : "NON-VEG"}
 </span>

 {previewItem.is_featured && (
 <span className="featured-ribbon inline">Featured</span>
 )}

 <span className="modal-meta-chip">
 {previewItem.category || "Special"}
 </span>

 <span className="modal-meta-chip">
 {spiceLabel(previewItem.spice_level)}
 </span>

 <span className="modal-meta-chip">
 {previewItem.prep_time || 0} min
 </span>
 </div>

 <h2>{previewItem.name}</h2>

 <p className="dish-modal-description">
 {previewItem.description ||
 "A chef's speciality prepared fresh to order."}
 </p>

 <div className="dish-modal-price">
 {formatMoney(previewItem.price)}
 </div>

 <div className="dish-modal-actions">
 <button
 className="add-btn"
 disabled={previewItem.available === false}
 onClick={() =>addToCart(previewItem)}
 >
 {previewItem.available === false
 ? "Unavailable"
 : "+ Add to Cart"}
 </button>

 <button
 className={
 favourites.includes(previewItem.id)
 ? "fav-btn active"
 : "fav-btn"
 }
 onClick={() =>toggleFavourite(previewItem.id)}
 >
 {favourites.includes(previewItem.id) ? "" : ""}
 </button>
 </div>
 </div>
 </div>
 </div>
 )}
 </div>
 )}

 {/* =========================================================
 1b. RECOMMENDED FOR YOU (Phase 5)

 Every card here comes from GET /api/ai/recommend/me, which
 resolves the account from the JWT. A reason is only rendered
 when the backend supplied one, so nothing on screen invents a
 justification. The score is shown as a raw 0-1 ranking value
 and is deliberately not labelled a confidence.
 ========================================================= */}
 {activeTab === "recommendations" && (
 <div className="recs-tab-view">
 <h2>Recommended for You</h2>

 {recsError && (
 <div className="error-message">
 {recsError}{" "}
 <button
 type="button"
 className="secondary-btn"
 onClick={refreshRecommendations}
 >
 Try again
 </button>
 </div>
 )}

 {recsLoading && !recommendations && (
 <div className="recs-loading">Finding dishes for you…</div>
 )}

 {recommendations && (
 <>
 <div className="recs-explainer">
 <p>{recommendations.reason}</p>

 {/* The backend states plainly when the answer is
 weaker than it looks - no history, nothing sold
 today, nothing similar. That is shown rather than
 hidden behind a confident-looking list. */}
 {recommendations.limitations?.length > 0 && (
 <ul className="recs-limitations">
 {recommendations.limitations.map((note, index) => (
 <li key={index}>{note}</li>
 ))}
 </ul>
 )}
 </div>

 <div className="recs-source-chips">
 <span className="recs-chip">
 Your history:{" "}
 {recommendations.generated_from?.customer_history
 ? `${recommendations.orders_analyzed} order(s)`
 : "none yet"}
 </span>
 <span className="recs-chip">
 Today&apos;s sales:{" "}
 {recommendations.generated_from?.today_sales
 ? `${recommendations.today?.total_portions_sold ?? 0} portions`
 : "no sales yet"}
 </span>
 <span className="recs-chip">
 Menu similarity:{" "}
 {recommendations.generated_from?.menu_similarity
 ? "used"
 : "not available"}
 </span>
 </div>

 {recommendations.personalized?.length === 0 &&
 recommendations.trending_today?.length === 0 ? (
 <div className="recs-empty">
 <h3>Nothing to recommend right now</h3>
 <p>
 There are no available dishes that score highly enough
 to suggest. Please check back once the kitchen has
 items available.
 </p>
 </div>
 ) : (
 <>
 {recommendations.personalized?.length > 0 && (
 <>
 <h3 className="recs-section-title">
 Picked for you
 </h3>

 <div className="recs-grid">
 {recommendations.personalized.map((dish) => (
 <RecCard key={`p-${dish.menu_id}`} dish={dish} />
 ))}
 </div>
 </>
 )}

 {recommendations.trending_today?.length > 0 && (
 <>
 <h3 className="recs-section-title">
 Trending today
 </h3>

 <div className="recs-grid">
 {recommendations.trending_today.map((dish) => (
 <RecCard
 key={`t-${dish.menu_id}`}
 dish={dish}
 trending
 />
 ))}
 </div>
 </>
 )}

 {recommendations.similar_items?.length > 0 && (
 <>
 <h3 className="recs-section-title">
 Because you ordered before
 </h3>

 <div className="recs-grid">
 {recommendations.similar_items.map((dish) => (
 <RecCard key={`s-${dish.menu_id}`} dish={dish} />
 ))}
 </div>
 </>
 )}
 </>
 )}
 </>
 )}
 </div>
 )}

 {/* =========================================================
 2. CART & ORDERING TAB
 ========================================================= */}
 {activeTab === "cart" && (
 <div className="cart-tab-view">
 <h2>Your Dining Cart & Order Placement</h2>
 <p className="section-desc">
 Review your selected delicacies, customize dining preference, and place order directly to the kitchen.
 </p>

 {orderSuccessMsg && (
 <div className="success-banner">{orderSuccessMsg}</div>
 )}

 {cart.length === 0 ? (
 <div className="empty-state">
 <span className="empty-icon"></span>
 <h3>Your cart is empty</h3>
 <p>Explore our AI-recommended dishes and digital menu to add items.</p>
 <button
 className="primary-btn"
 onClick={() =>setActiveTab("menu")}
 >
 Browse Menu
 </button>
 </div>
 ) : (
 <div className="cart-layout">
 <div className="cart-items-column">
 <div className="cart-items-card">
 <h3>Selected Items ({cartTotalItems})</h3>
 {cart.map((item) => (
 <>
 <div className="cart-row"key={item.id}>
 <img
 src={getDishImage(item)}
 alt={item.name}
 className="cart-thumb"
 />
 <div className="cart-item-info">
 <h4>{item.name}</h4>
 <span className="cart-unit-price">
 {formatMoney(item.price)} each
 </span>
 {item.prep_time > 0 && (
 <span className="cart-prep-hint">
 {item.prep_time} min
 </span>
 )}
 </div>
 <div className="cart-stepper">
 <button onClick={() =>updateCartQty(item.id, -1)}>−</button>
 <span>{item.quantity}</span>
 <button onClick={() =>updateCartQty(item.id, 1)}>+</button>
 </div>
 <div className="cart-item-total">
 {formatMoney(
 Number(item.price) * item.quantity,
 )}
 </div>
 </div>
 <div className="cart-item-specifications">
 <label>
 Special instructions (e.g., add salt, less spices, extra sauce)
 <input
 type="text"
 placeholder="Customize this dish..."
 value={item.specifications || ""}
 onChange={(e) =>updateCartSpecifications(item.id, e.target.value)}
 />
 </label>
 </div>
 </>
 ))}
 </div>

 {/* Dining Options */}
 <div className="dining-options-card">
 <h3>Dining Preference</h3>
 <div className="dining-mode-selector">
 <label
 className={orderType === "dine-in" ? "mode-radio active" : "mode-radio"}
 >
 <input
 type="radio"
 name="orderType"
 value="dine-in"
 checked={orderType === "dine-in"}
 onChange={(e) =>setOrderType(e.target.value)}
 />
 <span>Dine-In (Table Service)</span>
 </label>
 <label
 className={orderType === "takeaway" ? "mode-radio active" : "mode-radio"}
 >
 <input
 type="radio"
 name="orderType"
 value="takeaway"
 checked={orderType === "takeaway"}
 onChange={(e) =>setOrderType(e.target.value)}
 />
 <span>Takeaway (Pickup)</span>
 </label>
 <label
 className={orderType === "delivery" ? "mode-radio active" : "mode-radio"}
 >
 <input
 type="radio"
 name="orderType"
 value="delivery"
 checked={orderType === "delivery"}
 onChange={(e) =>setOrderType(e.target.value)}
 />
 <span>Home Delivery</span>
 </label>
 </div>

 {orderType === "dine-in" && tableContext && (
 <div className="field-group">
 <label>Your Table (from QR scan)</label>
 <div className="claimed-table-display">
 <strong>Table {tableContext.table_number}</strong>
 {tableContext.table_name && (
 <span> · {tableContext.table_name}</span>
 )}
 <small>
 Seats {tableContext.capacity}
 {tableContext.section && ` · {tableContext.section}`}
 </small>
 </div>
 </div>
 )}

 {orderType === "dine-in" && !tableContext && (
 <div className="field-group">
 <label>Select Table Number</label>
 <select
 value={tableNumber}
 onChange={(e) =>setTableNumber(e.target.value)}
 >
 {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12].map((num) => (
 <option key={num} value={num}>
 Table #{num} (Indoor Dining)
 </option>
 ))}
 </select>
 <small className="form-hint">
 Scan a table QR to lock your table automatically
 </small>
 </div>
 )}

 {orderType === "delivery" && (
 <div className="field-group">
 <label>Delivery Address</label>
 <input
 type="text"
 placeholder="House/Street, Landmark, Area..."
 value={deliveryAddress}
 onChange={(e) =>setDeliveryAddress(e.target.value)}
 />
 </div>
 )}

 <div className="field-group">
 <label>Kitchen / Cooking Instructions (Optional)</label>
 <input
 type="text"
 placeholder="e.g. Medium spice, extra sambar, cutlery requested"
 value={orderNotes}
 onChange={(e) =>setOrderNotes(e.target.value)}
 />
 </div>
 </div>
 </div>

 {/* Order Summary Checkout Card */}
 <div className="cart-summary-column">
 <div className="summary-card">
 <h3>Bill Summary</h3>

 {quoteError && (
 <p className="auth-error"role="alert">
 {quoteError}
 </p>
 )}

 <div className="summary-line">
 <span>Item Subtotal</span>
 <strong>
 {formatMoney(cartSubtotal, quoteCurrency)}
 </strong>
 </div>

 <div className="summary-line">
 <span>
 Restaurant Tax
 {cartTaxRate === null
 ? ""
 : ` (GST ${cartTaxRate}%)`}
 </span>
 <strong>
 {formatMoney(cartTax, quoteCurrency)}
 </strong>
 </div>

 {cartServiceCharge > 0 && (
 <div className="summary-line">
 <span>
 Service Charge (
 {quote?.service_charge_percentage}%)
 </span>
 <strong>
 {formatMoney(cartServiceCharge, quoteCurrency)}
 </strong>
 </div>
 )}

 {cartDiscount > 0 && (
 <div className="summary-line">
 <span>
 Discount
 {quote?.discount_reason
 ? ` (${quote.discount_reason})`
 : ""}
 </span>
 <strong>
 -{formatMoney(cartDiscount, quoteCurrency)}
 </strong>
 </div>
 )}

 <div className="summary-divider" />

 <div className="summary-line">
 <span>Estimated Kitchen Time</span>
 <strong>{cartWaitTime || 0} min</strong>
 </div>

 <div className="summary-line total">
 <span>Grand Total</span>
 <strong>
 {formatMoney(cartGrandTotal, quoteCurrency)}
 </strong>
 </div>

 <button
 className="checkout-btn"
 onClick={handlePlaceOrder}
 disabled={isSubmittingOrder || !quoteIsSettled}
 >
 {isSubmittingOrder
 ? "Placing order..."
 : quoteIsSettled
 ? `Confirm & Place Order (${formatMoney(
 cartGrandTotal,
 quoteCurrency,
 )})`
 : "Pricing your order..."}
 </button>

 <p className="order-guarantee">
 Priced by the server from the live menu. Tax and
 totals are calculated on our server, not in your
 browser.
 </p>
 </div>
 </div>
 </div>
 )}
 </div>
 )}

 {/* =========================================================
 3. LIVE ORDER TRACKING TAB
 ========================================================= */}
 {activeTab === "tracking" && (
 <div className="tracking-tab-view">
 <div className="section-title-row">
 <div>
 <h2>Real-Time Order Tracking</h2>
 <p>Live status pipeline connected directly to our Kitchen Display System (KDS).</p>
 </div>
 <div style={{display: 'flex', gap: '8px', flexWrap: 'wrap'}}>
 <button className="secondary-btn"onClick={refreshOrders}>
 Refresh History
 </button>
 <button className="primary-btn"onClick={refreshActiveOrder}>
 Refresh Active Order
 </button>
 </div>
 </div>

 {/* Active Order Tracking - Shows the currently active order with live stepper */}
 {activeOrder && (
 <div className="active-order-tracker">
 <div className="active-order-header">
 <div className="active-order-info">
 <span className="order-tag">Order #{activeOrder.order_id}</span>
 <h3>{activeOrder.reference}</h3>
 <div className="active-order-meta">
 <span> {activeOrder.order_type === 'dine-in' ? `Dine-In · Table #${activeOrder.table_number}` : activeOrder.order_type === 'delivery' ? ' Delivery' : ' Takeaway'}</span>
 <span> {formatMoney(activeOrder.total_amount, activeOrder.currency)}</span>
 <span>Placed: {activeOrder.placed_at ? new Date(activeOrder.placed_at).toLocaleTimeString() : '-'}</span>
 </div>
 </div>
 <div className={`status-pill-large ${activeOrder.status.toLowerCase()}`}>
 {activeOrder.status}
 </div>
 </div>

 {/* Status stepper. Driven entirely by the status the API
 just returned - a stage is never lit speculatively. */}
 <div className="lifecycle-stepper">
 {LIFECYCLE_STAGES.map((stage, index) => (
 <div key={stage.key} className="lifecycle-stage">
 <div className={`stage-circle ${activeOrder.status === stage.key ? 'active' : (ORDER_STATUSES.indexOf(activeOrder.status) >index ? 'completed' : '')}`}>
 <span>{stage.icon}</span>
 </div>
 <div className={`stage-label ${activeOrder.status === stage.key ? 'active' : ''}`}>
 {stage.label}
 </div>
 {index < LIFECYCLE_STAGES.length - 1 && (
 <div className={`stage-line ${ORDER_STATUSES.indexOf(activeOrder.status) >index ? 'completed' : ''}`} />
 )}
 </div>
 ))}
 </div>

 {/* Status Message */}
 <div className="status-message">
 {STATUS_MESSAGES[activeOrder.status] || ""}
 </div>

 {/* Payment Status */}
 <div className="payment-status-card">
 <span className="payment-label">Payment Status:</span>
 <span className={`payment-status ${activeOrder.payment_status.toLowerCase()}`}>
 {activeOrder.payment_status === 'unpaid' ? 'UNPAID' : activeOrder.payment_status.toUpperCase()}
 </span>
 <small>Food status and payment status are tracked separately</small>
 </div>
 </div>
 )}

 {/* =========================================================
 MY ORDER HISTORY - how many orders this guest has placed
 ========================================================= */}

 <div className="stats-grid customer-order-stats">
 <div className="stat-card">
 <h3>Total Orders</h3>
 <strong>{myOrderStats.totalOrders}</strong>
 <small>orders placed at this restaurant</small>
 </div>

 <div className="stat-card">
 <h3>In Progress</h3>
 <strong>{myOrderStats.liveOrders}</strong>
 <small>active right now</small>
 </div>

 <div className="stat-card">
 <h3>Completed</h3>
 <strong>{myOrderStats.completedOrders}</strong>
 <small>{myOrderStats.cancelledOrders} cancelled</small>
 </div>

 <div className="stat-card">
 <h3>Dishes Ordered</h3>
 <strong>{myOrderStats.dishesOrdered}</strong>
 <small>total portions</small>
 </div>

 <div className="stat-card">
 <h3>Total Spent</h3>
 <strong>{formatMoney(myOrderStats.totalSpent)}</strong>
 <small>excluding cancelled orders</small>
 </div>

 <div className="stat-card">
 <h3>Your Dining Visits</h3>
 <strong>{myOrderStats.visits}</strong>
 <small>different days ordered</small>
 </div>

 {favouriteDish && (
 <div className="stat-card">
 <h3>Most Ordered</h3>
 <strong>{favouriteDish[1].quantity}</strong>
 <small>{favouriteDish[0]}</small>
 </div>
 )}

 <div className="stat-card">
 <h3>Loyalty Points</h3>
 <strong>{loyaltyPoints}</strong>
 <small>earned on your orders</small>
 </div>
 </div>

 {myOrders.length > 0 && (
 <div className="order-history">
 <div className="order-history-head">
 <h3>Your Order History</h3>

 <div className="history-filters">
 {[
 { key: "all", label: "All" },
 { key: "live", label: "In Progress" },
 { key: "completed", label: "Served" },
 { key: "cancelled", label: "Cancelled" },
 ].map((filter) => (
 <button
 key={filter.key}
 type="button"
 className={
 historyFilter === filter.key
 ? "history-filter-btn active"
 : "history-filter-btn"
 }
 onClick={() =>setHistoryFilter(filter.key)}
 >
 {filter.label}
 </button>
 ))}
 </div>
 </div>

 <table className="history-table">
 <thead>
 <tr>
 <th>Order</th>
 <th>Dish</th>
 <th>Qty</th>
 <th>Total</th>
 <th>Type</th>
 <th>Status</th>
 <th>Payment</th>
 </tr>
 </thead>

 <tbody>
 {myOrders
 .filter((order) => {
 if (historyFilter === "live") {
 return ACTIVE_ORDER_STATUSES.includes(order.status);
 }

 if (historyFilter === "completed") {
 return order.status === "Served";
 }

 if (historyFilter === "cancelled") {
 return order.status === CANCELLED_ORDER_STATUS;
 }

 return true;
 })
 .map((order) => (
 <tr key={order.id}>
 <td>#{order.id}</td>
 <td>{order.menu_item}</td>
 <td>{order.quantity}</td>
 <td>{formatMoney(order.total_price || 0)}</td>
 <td>
 {order.order_type === "dine-in"
 ? `Dine-In · T${order.table_number ?? "-"}`
 : order.order_type === "delivery"
 ? "Delivery"
 : "Takeaway"}
 </td>
 <td>
 <span
 className={`status-pill ${order.status.toLowerCase()}`}
 >
 {order.status}
 </span>
 </td>
 <td>
 <span
 className={`payment-status-pill ${(order.payment_status || "unpaid").toLowerCase()}`}
 >
 {order.payment_status === 'unpaid' ? 'UNPAID' : (order.payment_status || 'unpaid').toUpperCase()}
 </span>
 </td>
 </tr>
 ))}
 </tbody>
 </table>
 </div>
 )}

 {myOrders.length === 0 ? (
 <div className="empty-state">
 <span className="empty-icon"></span>
 <h3>No active orders placed yet</h3>
 <p>Place an order from the digital menu to watch its live preparation lifecycle!</p>
 <button className="primary-btn"onClick={() =>setActiveTab("menu")}>
 Start Dining
 </button>
 </div>
 ) : (
 <div className="orders-timeline-grid">
 {myOrders.map((ord) => {
 // The status exactly as the backend reports it. Orders
 // placed before the lifecycle existed carry an older
 // label; that is shown as-is rather than relabelled
 // into a stage the kitchen never entered.
 const status = ord.status;
 const statusIndex = ORDER_STATUSES.indexOf(status);
 const isTracked = statusIndex >= 0;

 return (
 <div className="order-track-card"key={ord.id}>
 <div className="track-header">
 <img
 src={getDishImage(ord)}
 alt={ord.menu_item}
 className="track-dish-thumb"
 />

 <div>
 <span className="order-tag">Order #{ord.id}</span>
 <h3>{ord.menu_item}</h3>
 <span className="order-meta">
 Qty: {ord.quantity} | Total: {formatMoney(ord.total_price)} | Customer:{" "}
 {ord.customer_name}
 </span>
 <span className="order-meta">
 {ord.order_type === "dine-in"
 ? ` Dine-In · Table #${ord.table_number ?? "-"}`
 : ord.order_type === "delivery"
 ? ` Delivery · ${ord.delivery_address || "Address on file"}`
 : "Takeaway (Pickup)"}
 </span>
 {ord.notes && (
 <span className="order-meta"> {ord.notes}</span>
 )}
 </div>
 <div className={`status-pill ${status.toLowerCase()}`}>
 {status}
 </div>
 </div>

 {/* Visual stepper. A stage is only marked reached
 once the API has reported the order as being in
 it or past it. */}
 <div className="lifecycle-stepper">
 {LIFECYCLE_STAGES.map((stage, index) => (
 <div key={stage.key} className="lifecycle-stage">
 <div className={`stage-circle ${status === stage.key ? 'active' : (statusIndex >index ? 'completed' : '')}`}>
 <span>{stage.icon}</span>
 </div>
 <div className={`stage-label ${status === stage.key ? 'active' : ''}`}>
 {stage.label}
 </div>
 {index < LIFECYCLE_STAGES.length - 1 && (
 <div className={`stage-line ${statusIndex >index ? 'completed' : ''}`} />
 )}
 </div>
 ))}
 </div>

 <div className="tracker-footer">
 {isTracked ? (
 <div className="live-status-indicator">
 <span>{STATUS_MESSAGES[status]}</span>
 </div>
 ) : (
 <div className="live-legacy-indicator">
 <span>
 This order was placed before live tracking was
 introduced, so it has no preparation stages to
 show.
 </span>
 </div>
 )}
 </div>
 </div>
 );
 })}
 </div>
 )}
 </div>
 )}

 {/* =========================================================
 4. TABLE RESERVATION TAB
 ========================================================= */}
 {activeTab === "reservations" && (
 <div className="reservation-tab-view">
 <div className="reservation-layout">
 <div className="reservation-form-column">
 <h2>Book a Table Reservation</h2>
 <p>
 Reserve your table in advance with instant digital confirmation.
 </p>

 {resSuccessMsg && (
 <div className="success-banner">{resSuccessMsg}</div>
 )}

 <form onSubmit={handlePlaceReservation} className="res-card-form">
 <div className="form-row">
 <div className="field-group">
 <label>Guest Name</label>
 <input
 type="text"
 value={customerName}
 disabled
 className="disabled-input"
 />
 </div>
 <div className="field-group">
 <label>Party Size (Number of Guests)</label>
 <select
 value={resForm.guests}
 onChange={(e) =>
 setResForm({ ...resForm, guests: Number(e.target.value) })
 }
 >
 {[1, 2, 3, 4, 5, 6, 8, 10, 12].map((g) => (
 <option key={g} value={g}>
 {g} {g === 1 ? "Guest" : "Guests"}
 </option>
 ))}
 </select>
 </div>
 </div>

 <div className="form-row">
 <div className="field-group">
 <label>Reservation Date</label>
 <input
 type="date"
 value={resForm.reservation_date}
 min={new Date().toISOString().split("T")[0]}
 onChange={(e) =>
 setResForm({ ...resForm, reservation_date: e.target.value })
 }
 required
 />
 </div>
 <div className="field-group">
 <label>Time Slot</label>
 <select
 value={resForm.reservation_time}
 onChange={(e) =>
 setResForm({ ...resForm, reservation_time: e.target.value })
 }
 >
 <option value="12:30">12:30 PM (Lunch)</option>
 <option value="13:30">01:30 PM (Lunch)</option>
 <option value="14:00">02:00 PM (Lunch)</option>
 <option value="19:00">07:00 PM (Dinner)</option>
 <option value="19:30">07:30 PM (Dinner)</option>
 <option value="20:30">08:30 PM (Dinner)</option>
 <option value="21:15">09:15 PM (Late Dinner)</option>
 </select>
 </div>
 </div>

 <div className="form-row">
 <div className="field-group">
 <label>Preferred Table Area</label>
 <select
 value={resForm.table_number}
 onChange={(e) =>
 setResForm({ ...resForm, table_number: Number(e.target.value) })
 }
 >
 <option value={2}>Table #2 (Window View)</option>
 <option value={4}>Table #4 (Center Garden)</option>
 <option value={6}>Table #6 (Private Booth)</option>
 <option value={8}>Table #8 (Family Long Table)</option>
 </select>
 </div>
 <div className="field-group">
 <label>Special Requests</label>
 <input
 type="text"
 placeholder="e.g. Birthday celebration, High chair"
 value={resForm.special_request}
 onChange={(e) =>
 setResForm({ ...resForm, special_request: e.target.value })
 }
 />
 </div>
 </div>

 <button type="submit"className="primary-btn submit-btn">
 Confirm Reservation
 </button>
 </form>
 </div>

 {/* My Reservations List */}
 <div className="reservations-list-column">
 <h3>Your Active Reservations ({myReservations.length})</h3>
 {myReservations.length === 0 ? (
 <p className="subtle-text">No previous bookings found. Book one now!</p>
 ) : (
 <div className="res-cards-list">
 {myReservations.map((res) => (
 <div className="res-pass-card"key={res.id}>
 <div className="pass-header">
 <span className="pass-brand">PARADISE DINING PASS</span>
 <span className="pass-status">Confirmed</span>
 </div>
 <div className="pass-body">
 <div>
 <span className="pass-label">Date</span>
 <strong>{res.reservation_date}</strong>
 </div>
 <div>
 <span className="pass-label">Time</span>
 <strong>{res.reservation_time}</strong>
 </div>
 <div>
 <span className="pass-label">Table</span>
 <strong>#{res.table_number}</strong>
 </div>
 <div>
 <span className="pass-label">Guests</span>
 <strong>{res.guests}</strong>
 </div>
 </div>
 </div>
 ))}
 </div>
 )}
 </div>
 </div>
 </div>
 )}

 {/* =========================================================
 5. FEEDBACK & REAL-TIME AI SENTIMENT TAB
 ========================================================= */}
 {activeTab === "reviews" && (
 <div className="reviews-tab-view">
 <div className="reviews-layout">
 <div className="review-form-column">
 <div className="ai-module-badge">
 <span>Real-Time NLP Sentiment Analysis</span>
 </div>
 <h2>Feedback & Customer Reviews</h2>
 <p>
 Share your dining experience. As you type, our Natural Language Processing model evaluates your feedback sentiment in real-time.
 </p>

 {reviewSuccessMsg && (
 <div className="success-banner">{reviewSuccessMsg}</div>
 )}

 <form onSubmit={handlePlaceReview} className="review-form-card">
 <div className="field-group">
 <label>Menu Item / Experience</label>
 <select
 value={reviewForm.menu_item}
 onChange={(e) =>
 setReviewForm({ ...reviewForm, menu_item: e.target.value })
 }
 >
 {menu.length === 0 && (
 <option value="Overall Experience">
 Overall Restaurant Experience
 </option>
 )}
 {menu.map((m) => (
 <option key={m.id} value={m.name}>
 {m.name} ({m.category})
 </option>
 ))}
 <option value="Overall Experience">
 Overall Restaurant Experience
 </option>
 </select>
 </div>

 <div className="field-group">
 <label>Rating (1 to 5 Stars)</label>
 <div className="star-picker">
 {[1, 2, 3, 4, 5].map((star) => (
 <button
 type="button"
 key={star}
 className={reviewForm.rating >= star ? "star-btn active" : "star-btn"}
 onClick={() =>setReviewForm({ ...reviewForm, rating: star })}
 >
 ★
 </button>
 ))}
 <span className="star-rating-text">{reviewForm.rating} of 5 Stars</span>
 </div>
 </div>

 <div className="field-group">
 <label>Your Review & Comments</label>
 <textarea
 rows="4"
 placeholder="Write your honest thoughts about taste, speed, service, or freshness..."
 value={reviewForm.comment}
 onChange={(e) =>
 setReviewForm({ ...reviewForm, comment: e.target.value })
 }
 required
 />
 </div>

 {/* Real-Time Sentiment Feedback Box */}
 {liveSentiment && (
 <div className={`live-sentiment-box ${liveSentiment.sentiment.toLowerCase()}`}>
 <div className="sentiment-box-header">
 <span className="ai-chip-tag">Live AI Sentiment Detection</span>
 <strong className="sentiment-result-text">
 {liveSentiment.sentiment === "Positive"
 ? "Positive "
 : liveSentiment.sentiment === "Negative"
 ? "Negative "
 : "Neutral "}
 </strong>
 </div>
 <p className="sentiment-detail-text">
 Sentiment Score: <strong>{Number(liveSentiment.score).toFixed(2)}</strong> |
 Confidence: <strong>{Math.round(Math.abs(liveSentiment.score) * 100)}%</strong>
 </p>
 </div>
 )}

 <button type="submit"className="primary-btn submit-btn">
 Submit Verified Review
 </button>
 </form>
 </div>

 {/* Feed of Recent Reviews */}
 <div className="reviews-feed-column">
 <h3>Customer Reviews Feed ({recentReviews.length})</h3>
 <div className="reviews-scroll-list">
 {recentReviews.slice(0, 8).map((rev) => (
 <div className="review-item-card"key={rev.id}>
 <div className="rev-head">
 <div>
 <strong>{rev.customer_name}</strong>
 <span className="rev-dish-tag">{rev.menu_item}</span>
 </div>
 <div className="rev-stars">
 {"★".repeat(rev.rating || 5)}
 <span className={`sentiment-badge-sm ${(rev.sentiment || "neutral").toLowerCase()}`}>
 {rev.sentiment}
 </span>
 </div>
 </div>
 <p className="rev-comment">"{rev.comment}"</p>
 </div>
 ))}
 </div>
 </div>
 </div>
 </div>
 )}

 {/* =========================================================
 BILL TAB (Phase 6E adds the second view)

 visit the current table's bill, with the Pay action
 history every bill this guest has ever had

 Both read stored server totals. Nothing here recalculates an
 amount, and nothing here decides that a payment succeeded.
 ========================================================= */}
 {activeTab === "bill" && (
 <div className="bill-tab-view">
 <div className="section-title-row">
 <div>
 <h2>
 {" "}
 {billView === "history"
 ? "Bill & Payment History"
 : "My Bill"}
 </h2>
 <p>
 {billView === "history"
 ? "Every bill you have had. Amounts and payment states come from the server's own records."
 : "Everything ordered at your table this visit. Amounts come from the server's own stored totals."}
 </p>
 </div>

 <div className="section-title-actions">
 <div className="pill-switch">
 <button
 className={billView === "visit" ? "active" : ""}
 onClick={() =>setBillView("visit")}
 >
 This visit
 </button>
 <button
 className={billView === "history" ? "active" : ""}
 onClick={() =>setBillView("history")}
 >
 History
 </button>
 </div>

 <button
 className="secondary-btn"
 onClick={
 billView === "history" ? loadHistory : refreshBill
 }
 disabled={billLoading}
 >
 {billLoading
 ? "Refreshing…"
 : "Refresh"}
 </button>
 </div>
 </div>

 {billView === "history" && (
 <>
 {!history ? (
 <p className="empty-note">Loading your history…</p>
 ) : historyError ? (
 <div className="error-message">{historyError}</div>
 ) : history.bills.length === 0 ? (
 <p className="empty-note">
 You do not have any bills yet.
 </p>
 ) : (
 <>
 <div className="history-totals">
 <div className="history-total">
 <span className="history-total-label">
 Total billed
 </span>
 <strong>
 {formatMoney(
 history.total_billed,
 history.currency || "INR",
 )}
 </strong>
 </div>

 <div className="history-total">
 <span className="history-total-label">
 Total collected
 </span>
 <strong className="collected">
 {formatMoney(
 history.total_collected,
 history.currency || "INR",
 )}
 </strong>
 </div>

 <div className="history-total">
 <span className="history-total-label">
 Total outstanding
 </span>
 <strong className="outstanding">
 {formatMoney(
 history.total_outstanding,
 history.currency || "INR",
 )}
 </strong>
 </div>
 </div>

 {history.bills.map((entry) => (
 <article
 key={entry.order_id}
 className={`history-bill history-${entry.billed_state.toLowerCase()}`}
 >
 <header className="history-bill-head">
 <div>
 <strong className="history-ref">
 Order #{entry.reference}
 </strong>
 <span className="history-date">
 {entry.created_at
 ? entry.created_at.replace("T", " ")
 : ""}
 </span>
 </div>

 <span
 className={`history-state history-state-${entry.billed_state.toLowerCase()}`}
 >
 {entry.billed_state === "PARTIALLY_PAID"
 ? "Partially Paid"
 : entry.billed_state === "PAID"
 ? "Paid"
 : "Unpaid"}
 </span>
 </header>

 <ul className="history-items">
 {entry.items.map((item, index) => (
 <li key={index}>
 <span>{item.menu_item}</span>
 <span className="history-item-qty">
 × {item.quantity}
 </span>
 <span className="history-item-total">
 {formatMoney(item.line_total, entry.currency)}
 </span>
 </li>
 ))}
 </ul>

 <div className="history-bill-lines">
 <div>
 <span>Subtotal</span>
 <strong>
 {formatMoney(entry.subtotal, entry.currency)}
 </strong>
 </div>
 <div>
 <span>Tax</span>
 <strong>
 {formatMoney(entry.tax_amount, entry.currency)}
 </strong>
 </div>

 {entry.service_charge_amount > 0 && (
 <div>
 <span>Service charge</span>
 <strong>
 {formatMoney(
 entry.service_charge_amount,
 entry.currency,
 )}
 </strong>
 </div>
 )}

 {entry.discount_amount > 0 && (
 <div>
 <span>Discount</span>
 <strong>
 −
 {formatMoney(
 entry.discount_amount,
 entry.currency,
 )}
 </strong>
 </div>
 )}

 <div className="history-total-line">
 <span>Total</span>
 <strong>
 {formatMoney(entry.total_amount, entry.currency)}
 </strong>
 </div>

 {/* Only money a provider confirmed is called
 paid. Outstanding sits on its own line so
 the two are never added together by eye. */}
 {entry.paid_amount > 0 && (
 <div className="history-settled">
 <span>Paid</span>
 <strong>
 {formatMoney(entry.paid_amount, entry.currency)}
 </strong>
 </div>
 )}

 {entry.outstanding_amount > 0 && (
 <div className="history-due">
 <span>Outstanding</span>
 <strong>
 {formatMoney(
 entry.outstanding_amount,
 entry.currency,
 )}
 </strong>
 </div>
 )}
 </div>

 <footer className="history-bill-foot">
 <span className="history-order-status">
 Order: {entry.order_status}
 </span>

 {entry.paid_at && (
 <span className="history-paid-at">
 Paid on {entry.paid_at.replace("T", " ")}
 </span>
 )}

 {entry.attempts > 1 && (
 <span className="history-attempts">
 {entry.attempts} payment attempts (
 {entry.failed_attempts} failed,{" "}
 {entry.cancelled_attempts} withdrawn)
 </span>
 )}

 {entry.provider_reference && (
 <span className="history-provider-ref">
 Ref:{" "}
 <code>{entry.provider_reference}</code>
 </span>
 )}
 </footer>
 </article>
 ))}
 </>
 )}
 </>
 )}

 {billView === "visit" && (
 !bill ? (
 <p className="empty-note">
 {billLoading ? "Loading your bill…" : "No bill available yet."}
 </p>
 ) : bill.orders.length === 0 ? (
 <div className="summary-card">
 <h3>Nothing on this bill yet</h3>
 <p>
 {bill.table_number
 ? `You have not ordered anything at Table ${bill.table_number} yet.`
 : "Scan the QR code on your table, or order from the menu."}
 </p>
 </div>
 ) : (
 <>
 <div className="table-card">
 <table>
 <thead>
 <tr>
 <th>Item</th>
 <th>Qty</th>
 <th>Unit</th>
 <th>Amount</th>
 </tr>
 </thead>

 <tbody>
 {bill.orders.map((line) => (
 <tr key={line.order_id}>
 <td>
 {line.menu_item}
 {line.special_instructions && (
 <small className="bill-note">
 {line.special_instructions}
 </small>
 )}
 </td>
 <td>{line.quantity}</td>
 <td>
 {line.unit_price === null
 ? "-"
 : formatMoney(line.unit_price, bill.currency)}
 </td>
 <td>
 {formatMoney(line.line_total, bill.currency)}
 </td>
 </tr>
 ))}
 </tbody>
 </table>
 </div>

 <div className="summary-card bill-summary">
 <div className="summary-line">
 <span>Subtotal</span>
 <strong>
 {formatMoney(bill.subtotal, bill.currency)}
 </strong>
 </div>

 <div className="summary-line">
 <span>Tax ({bill.tax_percentage}%)</span>
 <strong>
 {formatMoney(bill.tax_amount, bill.currency)}
 </strong>
 </div>

 {bill.service_charge_amount > 0 && (
 <div className="summary-line">
 <span>
 Service charge ({bill.service_charge_percentage}%)
 </span>
 <strong>
 {formatMoney(
 bill.service_charge_amount,
 bill.currency,
 )}
 </strong>
 </div>
 )}

 {bill.discount_amount > 0 && (
 <div className="summary-line">
 <span>Discount</span>
 <strong>
 -{formatMoney(
 bill.discount_amount,
 bill.currency,
 )}
 </strong>
 </div>
 )}

 <div className="summary-divider" />

 <div className="summary-line total">
 <span>Total</span>
 <strong>
 {formatMoney(bill.total_amount, bill.currency)}
 </strong>
 </div>

 <div className="summary-line">
 <span>Payment status</span>
 <strong
 className={
 bill.payment_status === "PAID"
 ? "bill-paid"
 : "bill-unpaid"
 }
 >
 {bill.payment_status}
 </strong>
 </div>

 {bill.food_statuses.length > 0 && (
 <div className="summary-line">
 <span>Food status</span>
 <strong>{bill.food_statuses.join(" → ")}</strong>
 </div>
 )}

 {/* ---- Payment ----
 `payment_available` comes from the server. When it
 is false no pay action is rendered at all, rather
 than a control that would not work.

 Nothing here sends an amount or claims a payment
 succeeded: the figure displayed is the server's, and
 the state shown is whatever the server last
 verified. */}
 {bill.payment_status === "PAID" ? (
 <div className="pay-panel pay-panel-settled">
 <div className="pay-panel-head">
 <span className="pay-panel-title">
 ✓ Payment received
 </span>
 <span className="pay-amount">
 {formatMoney(bill.paid_amount, bill.currency)}
 </span>
 </div>

 <p className="pay-panel-note">
 Confirmed by the restaurant&rsquo;s payment
 provider
 {bill.paid_at
 ? ` on ${bill.paid_at.replace("T", " ")}`
 : ""}
 {bill.payment_method
 ? ` · ${bill.payment_method}`
 : ""}
 .
 </p>
 </div>
 ) : bill.payment_available ? (
 <div className="pay-panel">
 <div className="pay-panel-head">
 <span className="pay-panel-title">Pay this bill</span>
 <span className="pay-amount">
 {formatMoney(bill.total_amount, bill.currency)}
 </span>
 </div>

 {!payState.payment ? (
 <>
 <p className="pay-panel-note">
 Ask the restaurant for a payment request, then
 open it in PhonePe, Google Pay, Paytm or any
 UPI app. The bill is marked paid only once the
 restaurant&rsquo;s system confirms it.
 </p>

 <div className="pay-actions">
 <button
 className="checkout-btn"
 onClick={startPayment}
 disabled={payState.busy}
 >
 {payState.busy
 ? "Preparing…"
 : providerLabel
 ? ` Pay Bill with ${providerLabel}`
 : "Pay Bill"}
 </button>
 </div>

 {providerMode === "TEST" && (
 <p className="pay-panel-note pay-panel-test">
 Test mode. This restaurant&rsquo;s payment
 connection is in TEST, so no real money moves
 and no bank account is involved.
 </p>
 )}
 </>
 ) : (
 <>
 <div className="pay-status-row">
 <span
 className={`pay-state-badge pay-state-${payState.status.toLowerCase()}`}
 >
 {/*
 Four states, and only the last one means
 money arrived. "Requested"is what the
 screen shows the moment a payment request
 is made, which is deliberately not the
 same as pending: one is a fact about what
 we did, the other is an absence of news
 from the provider.
 */}
 {payState.status === "SUCCESS"
 ? "Payment Successful"
 : payState.status === "FAILED"
 ? "Payment Failed"
 : providerLabel
 ? "Payment Processing"
 : "Payment Requested"}
 </span>

 <span className="pay-amount">
 {formatMoney(
 payState.amount,
 payState.currency,
 )}
 </span>
 </div>

 {payState.upiUri && (
 <div className="pay-qr-wrap">
 {/*
 Rendered locally by qrcode.react. No
 third-party image service is involved,
 which matters: a remote QR generator would
 receive the payment URI - merchant, exact
 amount and order reference - and pass it to
 somebody else's server.
 */}
 <QRCodeSVG
 className="pay-qr"
 value={payState.upiUri}
 size={216}
 level="M"
 marginSize={2}
 title="UPI payment QR code"
 />

 <p className="pay-panel-note">
 Scan with any UPI app, or{" "}
 <a
 className="pay-upi-link"
 href={payState.upiUri}
 >
 open the payment request
 </a>
 .
 </p>
 </div>
 )}

 {payState.status === "PENDING" && (
 <p className="pay-panel-note pay-panel-warn">
 Waiting for the restaurant&rsquo;s system to
 confirm. This screen does not mark the bill
 paid — press &ldquo;Check again&rdquo; once
 you have paid.
 </p>
 )}

 {payState.failureReason && (
 <p className="pay-panel-note pay-panel-warn">
 {payState.failureReason}
 </p>
 )}

 {payState.providerReference && (
 <p className="pay-panel-ref">
 Provider reference:{" "}
 <code>{payState.providerReference}</code>
 </p>
 )}

 <div className="pay-actions">
 {payState.status === "PENDING" && (
 <button
 className="checkout-btn"
 onClick={checkPayment}
 disabled={payState.busy}
 >
 {payState.busy
 ? "Checking…"
 : "Check again"}
 </button>
 )}

 {payState.status === "PENDING" && (
 <button
 className="secondary-btn"
 onClick={discardPayment}
 disabled={payState.busy}
 >
 Cancel request
 </button>
 )}
 </div>
 </>
 )}
 </div>
 ) : (
 <p className="pay-panel-note pay-panel-off">
 {bill.payment_gateway?.payments_enabled === false
 ? "Online payment is not enabled on this system yet. Please settle your bill at the counter."
 : "Nothing on this bill is payable at the moment."}
 </p>
 )}

 <p className="order-guarantee">
 Food status and payment status are tracked separately on
 purpose: you can finish your meal before settling the
 bill.
 </p>
 </div>
 </>
 )
 )}
 </div>
 )}

 {/* =========================================================
 6. LOYALTY & REWARDS TAB
 ========================================================= */}
 {activeTab === "loyalty" && (
 <div className="loyalty-tab-view">
 <h2>Guest Loyalty & Rewards Program</h2>
 <p className="section-desc">
 Points are earned on completed orders and redeemed against your
 bill.
 </p>

 <div className="loyalty-notice">
 <strong>Loyalty earning and redemption rates are not configured
 yet.</strong>
 <p>
 No points are added to your balance and no discount is applied
 at checkout until the restaurant sets these rates. The balance
 below is for display only.
 </p>
 </div>

 <div className="loyalty-hero-card">
 <div className="loyalty-balance-stat">
 <span className="kicker">Available Rewards Balance</span>
 <h1 className="points-display">{loyaltyPoints} <span>Points</span></h1>
 <p className="equiv-text">
 Redemption value not yet configured
 </p>
 </div>

 <div className="tier-progress-card">
 <div className="tier-header">
 <span>Current Status: <strong>Gold VIP Member</strong></span>
 <span>Next Tier: <strong>Platinum (600 Pts)</strong></span>
 </div>
 <div className="tier-bar-track">
 <div
 className="tier-bar-fill"
 style={{ width: `${Math.min(100, (loyaltyPoints / 600) * 100)}%` }}
 />
 </div>
 <p className="tier-perks">
 Perks: 10% faster table seating, priority weekend reservations, and exclusive chef tastings.
 </p>
 </div>
 </div>

 <h3 className="rewards-section-title">Redeemable Rewards Vouchers</h3>

 <div className="loyalty-notice">
 <strong>Reward vouchers are not available yet.</strong>
 <p>
 Voucher values and their loyalty point costs are not
 configured, so none can be redeemed. Discounts, when they are
 enabled, are calculated on the server at checkout - never in
 your browser.
 </p>
 </div>
 </div>
 )}

 {/* =========================================================
 7. SETTINGS TAB
 ========================================================= */}
 {activeTab === "settings" && (
 <div className="settings-tab-view">
 <h2>Account Settings</h2>
 <p className="section-desc">
 Manage your profile information and preferences.
 </p>

 <div className="settings-card">
 <h3>Profile Information</h3>
 <div className="settings-field">
 <label>Full Name</label>
 <input
 type="text"
 value={user?.name || ""}
 disabled
 className="disabled-input"
 />
 </div>
 <div className="settings-field">
 <label>Email Address</label>
 <input
 type="email"
 value={user?.email || ""}
 disabled
 className="disabled-input"
 />
 </div>
 <div className="settings-field">
 <label>Role</label>
 <input
 type="text"
 value={user?.role || "customer"}
 disabled
 className="disabled-input"
 />
 </div>
 <div className="settings-field">
 <label>Loyalty Points</label>
 <input
 type="text"
 value={loyaltyPoints + "Points"}
 disabled
 className="disabled-input"
 />
 </div>
 </div>

 <div className="settings-card">
 <h3>Account Actions</h3>
 <button
 className="danger-btn"
 onClick={() => {
 localStorage.removeItem("restaurant_user");
 localStorage.removeItem("restaurant_token");
 localStorage.removeItem("restaurant_favourites");
 onLogout();
 }}
 >
 Logout
 </button>
 </div>
 </div>
 )}

 {/* Footer Presentation Credits */}
 <footer className="customer-footer">
 <div className="footer-credits">
 <strong>Paradise Restaurant</strong>
 </div>
 </footer>
 </AppShell>
 );
}

export default CustomerPortal;

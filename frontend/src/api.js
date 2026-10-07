import axios from "axios";

const API = axios.create({
  baseURL: import.meta.env.VITE_API_URL || "http://127.0.0.1:8000",
  timeout: 10000,
});

// Called when the session is no longer valid. App.jsx registers the
// real handler so a dead or revoked token lands the guest back on the
// login page instead of leaving a half-rendered screen.
let onSessionExpired = null;

export const setSessionExpiredHandler = (handler) => {
  onSessionExpired = handler;
};

// Clears the locally cached identity. The backend stays the authority -
// this only removes stale data from the browser.
export const clearStoredSession = () => {
  localStorage.removeItem("restaurant_token");
  localStorage.removeItem("restaurant_user");
};

// Add token to requests if available
API.interceptors.request.use((config) => {
  const token = localStorage.getItem("restaurant_token");

  if (token) {
    config.headers.Authorization = "Bearer " + token;
  }

  return config;
});

// Response interceptor for handling auth errors
API.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error.response?.status;

    // 401 means the token is missing, expired or revoked. 403 means
    // this account is not allowed to do that - the session itself is
    // still fine, so only 401 triggers a logout.
    if (status === 401) {
      clearStoredSession();

      if (onSessionExpired) {
        onSessionExpired();
      }
    }

    return Promise.reject(error);
  }
);

// ============================================================
// AUTHENTICATION
// These routes are NOT under /api
// ============================================================

export const registerUser = async (user) => {
  const response = await API.post("/auth/register", user);
  return response.data;
};

export const loginUser = async (credentials) => {
  const response = await API.post("/auth/login", credentials);
  return response.data;
};

// Asks the backend who the current token belongs to. Used instead of
// trusting the role that was cached in localStorage at login time.
export const getCurrentUser = async () => {
  const response = await API.get("/auth/me");
  return response.data;
};

// ============================================================
// DASHBOARD
// ============================================================

export const getDashboard = async () => {
  const response = await API.get("/api/dashboard/");
  return response.data;
};

// Real aggregation from the orders table. Replaces the dashboard's
// hardcoded dish list.
export const getTopDishes = async (limit = 5) => {
  const response = await API.get("/api/dashboard/top-dishes", {
    params: { limit },
  });
  return response.data;
};

// Real 7-day revenue series. Replaces the hardcoded chart bars.
export const getWeeklyRevenue = async (days = 7) => {
  const response = await API.get("/api/dashboard/weekly", {
    params: { days },
  });
  return response.data;
};

// ============================================================
// MENU
// ============================================================

export const getMenu = async (params = {}) => {
  const response = await API.get("/api/menu/", { params });
  return response.data;
};

export const getMenuCategories = async () => {
  const response = await API.get("/api/menu/categories");
  return response.data;
};

export const createMenu = async (menuItem) => {
  const response = await API.post("/api/menu/", menuItem);
  return response.data;
};

export const updateMenu = async (id, menuItem) => {
  const response = await API.put("/api/menu/" + String(id), menuItem);
  return response.data;
};

export const deleteMenu = async (id) => {
  const response = await API.delete("/api/menu/" + String(id));
  return response.data;
};

export const bulkUpdateMenu = async (payload) => {
  const response = await API.patch("/api/menu/bulk", payload);
  return response.data;
};

export const bulkDeleteMenu = async (ids) => {
  const response = await API.delete("/api/menu/bulk", {
    data: { ids },
  });
  return response.data;
};

const fileToBase64 = (file) =>
  new Promise((resolve, reject) => {
    const reader = new FileReader();

    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("Could not read the image file"));

    reader.readAsDataURL(file);
  });

export const uploadMenuImage = async (file) => {
  const formData = new FormData();

  formData.append("file", file);

  try {
    const response = await API.post("/api/menu/upload-image-file", formData, {
      headers: { "Content-Type": "multipart/form-data" },
    });

    return response.data;
  } catch {
    // Multipart upload is unavailable - fall back to a base64 upload.
    const data = await fileToBase64(file);

    const response = await API.post("/api/menu/upload-image", {
      data,
      file_name: file.name,
      content_type: file.type || "image/png",
    });

    return response.data;
  }
};

export const toggleMenuAvailability = async (id) => {
  const response = await API.patch("/api/menu/" + String(id) + "/availability");
  return response.data;
};

export const updateMenuPrice = async (id, price) => {
  const response = await API.patch("/api/menu/" + String(id) + "/price", { price });
  return response.data;
};

export const updateMenuPriceByName = async (name, price) => {
  const response = await API.patch(
    "/api/menu/by-name/" + encodeURIComponent(name) + "/price",
    { price }
  );

  return response.data;
};

// ============================================================
// ORDERS
// ============================================================

export const getOrders = async () => {
  const response = await API.get("/api/orders/");
  return response.data;
};

export const getMyOrders = async () => {
  const response = await API.get("/api/orders/mine");
  return response.data;
};

// Phase 6A - the browser never sends a price.
//
// `total_price`, `unit_price`, `currency`, `customer_name`, `status`,
// `image_url` and a per-line `user_id` are dropped here rather than
// being sent and quietly ignored on the server. Keeping them in a
// request body invites the belief that they matter, and the whole point
// of server-authoritative pricing is that nothing the browser says can
// change what a guest is charged.
const UNTRUSTED_ORDER_FIELDS = [
  "total_price",
  "subtotal",
  "unit_price",
  "price",
  "amount",
  "currency",
  "customer_name",
  "user_id",
  "status",
  "image_url",
];

const stripUntrustedMoney = (value) => {
  if (Array.isArray(value)) return value.map(stripUntrustedMoney);
  if (value === null || typeof value !== "object") return value;

  return Object.fromEntries(
    Object.entries(value).filter(([key]) => !UNTRUSTED_ORDER_FIELDS.includes(key))
  );
};

// Legacy single-dish endpoint. Sends {menu_id | menu_item, quantity} and
// whatever kitchen notes the guest typed. The response carries the
// server's subtotal, tax, total and currency.
export const createOrder = async (order) => {
  const response = await API.post("/api/orders/", stripUntrustedMoney(order));
  return response.data;
};

// Legacy full-cart endpoint. Same rule: dishes and quantities only.
export const placeCartOrder = async (cart) => {
  const response = await API.post("/api/orders/cart", stripUntrustedMoney(cart));
  return response.data;
};

// Phase 2 - server-authoritative pricing.
//
// Both endpoints take only {menu_item_id, quantity} per line. The
// browser sends no prices and no totals; subtotal, tax, service charge,
// discount and the grand total all come back from the server, computed
// from menu.price and settings.tax_percentage.
export const quoteCart = async (cart) => {
  const response = await API.post("/api/orders/quote", cart);
  return response.data;
};

export const checkoutCart = async (cart) => {
  const response = await API.post("/api/orders/checkout", cart);
  return response.data;
};

export const getMyOrderHeaders = async () => {
  const response = await API.get("/api/orders/headers/mine");
  return response.data;
};

export const getOrderHeaders = async () => {
  const response = await API.get("/api/orders/headers");
  return response.data;
};

export const getActiveOrderHeaders = async () => {
  const response = await API.get("/api/orders/headers/active");
  return response.data;
};

export const getOrderHeaderStatus = async (headerId) => {
  const response = await API.get("/api/orders/headers/" + String(headerId) + "/status");
  return response.data;
};

// The server decides which statuses are reachable, and rejects anything
// that skips a step. Callers must render `valid_next_statuses` from the
// response rather than computing a next stage locally, so the UI can
// never offer a transition the API will refuse.
export const updateOrderHeaderStatus = async (headerId, status) => {
  const response = await API.post("/api/orders/headers/" + String(headerId) + "/status", { status });
  return response.data;
};

export const getMyActiveOrder = async () => {
  const response = await API.get("/api/orders/my-active");
  return response.data;
};

// An admin edit also never carries money. The server recomputes the line
// from menu.price when the dish or quantity changes and leaves the
// stored totals alone when they do not, so a correction can never rewrite
// what a guest was charged.
export const updateOrder = async (id, order) => {
  const response = await API.put("/api/orders/" + String(id), stripUntrustedMoney(order));
  return response.data;
};

export const deleteOrder = async (id) => {
  const response = await API.delete("/api/orders/" + String(id));
  return response.data;
};

// ============================================================
// TABLES & TABLE QR
// ============================================================

// Public. Called by the entry page straight from a phone camera,
// before the guest has an account, so it needs no token.
export const resolveTableToken = async (tableToken) => {
  const response = await API.get("/api/tables/resolve", {
    params: { table: tableToken },
  });
  return response.data;
};

export const claimTable = async (tableToken) => {
  const response = await API.post("/api/tables/claim", {
    table_token: tableToken,
  });
  return response.data;
};

// The server's own view of which table this guest is sitting at.
// The portal renders this rather than anything the browser stored.
export const getTableContext = async () => {
  const response = await API.get("/api/tables/context");
  return response.data;
};

export const releaseTable = async () => {
  const response = await API.post("/api/tables/release");
  return response.data;
};

export const getTables = async () => {
  const response = await API.get("/api/tables/");
  return response.data;
};

export const getQrBaseUrl = async () => {
  const response = await API.get("/api/tables/qr-base-url");
  return response.data;
};

export const createTable = async (table) => {
  const response = await API.post("/api/tables/", table);
  return response.data;
};

export const updateTable = async (tableId, table) => {
  const response = await API.put(
    "/api/tables/" + String(tableId),
    table
  );
  return response.data;
};

export const regenerateTableQr = async (tableId) => {
  const response = await API.post(
    "/api/tables/" + String(tableId) + "/regenerate-qr"
  );
  return response.data;
};

export const deleteTable = async (tableId) => {
  const response = await API.delete("/api/tables/" + String(tableId));
  return response.data;
};

// ============================================================
// MY BILL
//
// The bill is the server's arithmetic, not the browser's. `total_amount`
// comes from OrderHeader and is displayed as received - it is never
// recalculated here.
//
// `payment_available` decides whether the Pay action is offered at all.
// When it is false there is no payment button, rather than a button that
// cannot work.
// ============================================================

export const getMyBill = async () => {
  const response = await API.get("/api/customer/bill");
  return response.data;
};

// ============================================================
// PHASE 6D - PAYMENTS
//
// None of these functions sends an amount, a currency or an outcome.
// The request body carries an order id and nothing else; the server reads
// the figure from OrderHeader.total_amount and reads the outcome from the
// provider. There is deliberately no function here that could mark a
// payment successful - the UI cannot express that, even by accident.
// ============================================================

// Ask the backend to request payment for one bill. Returns a PENDING
// payment plus, in development mode, a UPI URI to open in a UPI app.
export const createPaymentRequest = async (orderId, method = "UPI") => {
  const response = await API.post("/api/payments/request", {
    order_id: orderId,
    method,
  });

  return response.data;
};

// Read one payment's current state.
export const getPayment = async (paymentId) => {
  const response = await API.get("/api/payments/" + String(paymentId));
  return response.data;
};

// Every attempt recorded against one bill.
export const getOrderPayments = async (orderId) => {
  const response = await API.get("/api/payments/order/" + String(orderId));
  return response.data;
};

// Ask the backend to check with the provider. Sends an empty body: the
// client may request a check but may not state its result.
export const verifyPayment = async (paymentId) => {
  const response = await API.post(
    "/api/payments/" + String(paymentId) + "/verify",
    {},
  );

  return response.data;
};

// Withdraw a pending attempt.
export const cancelPayment = async (paymentId) => {
  const response = await API.post(
    "/api/payments/" + String(paymentId) + "/cancel",
  );

  return response.data;
};

// Every bill with its payment state, for the admin bill screen.
export const getAdminPayableOrders = async () => {
  const response = await API.get("/api/payments/admin/orders");
  return response.data;
};

// DEVELOPMENT ONLY. Publishes a simulated outcome on the development
// provider; the ordinary verification path then reads it. It is a test
// action and it records no real money.
//
// There is no `markAsPaid` function, and that omission is the design.
export const simulateDevelopmentPayment = async (paymentId, outcome = "SUCCESS") => {
  const response = await API.post(
    "/api/payments/dev/" + String(paymentId) + "/simulate",
    { outcome },
  );

  return response.data;
};

// ============================================================
// PHASE 6E - BILL AND PAYMENT HISTORY
//
// Read-only views. None of these sends an amount, a status or a total:
// every figure is returned by the server and displayed as received.
//
// Filters are plain query strings built from a closed set of values the
// server validates. Nothing here can express a column name or an
// expression.
// ============================================================

// Every bill this guest has, newest first. Distinct from `getMyBill`,
// which is the current visit's bill.
export const getMyBillHistory = async (limit = 50) => {
  const response = await API.get("/api/customer/bills", {
    params: { limit },
  });

  return response.data;
};

// Every payment attempt this guest has made.
export const getMyPaymentHistory = async (limit = 50) => {
  const response = await API.get("/api/payments/mine", {
    params: { limit },
  });

  return response.data;
};

// Builds a query string from a filter object, dropping empty values so a
// blank form control does not turn into `?status=`.
export const buildHistoryQuery = (filters = {}) => {
  const params = {};

  Object.entries(filters).forEach(([key, value]) => {
    if (value !== "" && value !== null && value !== undefined) {
      params[key] = value;
    }
  });

  return params;
};

// Admin: bills with their settlement state, filtered and paginated.
export const getAdminBillHistory = async (filters = {}, page = 1, pageSize = 25) => {
  const response = await API.get("/api/payments/admin/bills", {
    params: { ...buildHistoryQuery(filters), page, page_size: pageSize },
  });

  return response.data;
};

// Admin: the payment ledger, filtered and paginated.
export const getAdminPaymentHistory = async (filters = {}, page = 1, pageSize = 25) => {
  const response = await API.get("/api/payments/admin/history", {
    params: { ...buildHistoryQuery(filters), page, page_size: pageSize },
  });

  return response.data;
};

// Admin: billed / collected / outstanding for a period.
export const getAdminSettlementSummary = async (rangeKey = "last_30_days") => {
  const response = await API.get("/api/payments/admin/summary", {
    params: { range_key: rangeKey },
  });

  return response.data;
};

// ============================================================
// PHASE 7F - PROVIDER WEBHOOK AND RECONCILIATION
//
// `reconcilePayment` is a read-only comparison for an operator. It never
// settles anything, and the server returns a limitation rather than a
// guess when the provider cannot be reached.
//
// There is deliberately no function that posts to the webhook: the
// webhook is not an application API, it is a provider callback that
// authenticates with a signature. A browser cannot produce one, and a
// function here that tried would be a forgery tool.
// ============================================================

export const reconcilePayment = async (paymentId) => {
  const response = await API.get(
    "/api/payments/admin/reconcile/" + String(paymentId),
  );

  return response.data;
};

// ============================================================
// RESERVATIONS
// ============================================================

export const getReservations = async () => {
  const response = await API.get("/api/reservations/");
  return response.data;
};

export const getReservationSummary = async () => {
  const response = await API.get("/api/reservations/summary");
  return response.data;
};

export const updateReservationStatus = async (id, status) => {
  const response = await API.patch(
    "/api/reservations/" + String(id) + "/status",
    { status }
  );

  return response.data;
};

export const createReservation = async (reservation) => {
  const response = await API.post("/api/reservations/", reservation);
  return response.data;
};

/**
 * The signed-in user's own reservations.
 *
 * Distinct from `getReservations`, which is the admin list and returns 403
 * for a customer. The backend exposes /api/reservations/mine for exactly
 * this - it resolves the user from the token, so no id is sent and there
 * is nothing for a caller to tamper with.
 *
 * The customer portal was calling the admin list here, which meant a
 * guest's bookings silently never loaded. This is the endpoint they
 * should have been using.
 */
export const getMyReservations = async () => {
  const response = await API.get("/api/reservations/mine");
  return response.data;
};

export const updateReservation = async (id, reservation) => {
  const response = await API.put("/api/reservations/" + String(id), reservation);
  return response.data;
};

export const deleteReservation = async (id) => {
  const response = await API.delete("/api/reservations/" + String(id));
  return response.data;
};

// ============================================================
// CUSTOMERS
// ============================================================

export const getCustomers = async () => {
  const response = await API.get("/api/customers/");
  return response.data;
};

export const createCustomer = async (customer) => {
  const response = await API.post("/api/customers/", customer);
  return response.data;
};

export const updateCustomer = async (id, customer) => {
  const response = await API.put("/api/customers/" + String(id), customer);
  return response.data;
};

export const deleteCustomer = async (id) => {
  const response = await API.delete("/api/customers/" + String(id));
  return response.data;
};

// ============================================================
// INVENTORY
// ============================================================

export const getInventory = async () => {
  const response = await API.get("/api/inventory/");
  return response.data;
};

export const getLowStock = async () => {
  const response = await API.get("/api/inventory/low-stock");
  return response.data;
};

export const createInventory = async (item) => {
  const response = await API.post("/api/inventory/", item);
  return response.data;
};

export const updateInventory = async (id, item) => {
  const response = await API.put("/api/inventory/" + String(id), item);
  return response.data;
};

export const deleteInventory = async (id) => {
  const response = await API.delete("/api/inventory/" + String(id));
  return response.data;
};

// ============================================================
// KITCHEN
// ============================================================

export const getKitchenOrders = async () => {
  const response = await API.get("/api/kitchen/");
  return response.data;
};

export const createKitchenOrder = async (order) => {
  const response = await API.post("/api/kitchen/", order);
  return response.data;
};

export const updateKitchenOrder = async (id, order) => {
  const response = await API.put("/api/kitchen/" + String(id), order);
  return response.data;
};

export const deleteKitchenOrder = async (id) => {
  const response = await API.delete("/api/kitchen/" + String(id));
  return response.data;
};

// ============================================================
// ANALYTICS
// ============================================================

export const getAnalytics = async () => {
  const response = await API.get("/api/analytics/");
  return response.data;
};

// ============================================================
// AI FEATURES
// ============================================================

export const getAIInsights = async () => {
  const response = await API.get("/api/ai/insights");
  return response.data;
};

export const getFoodRecommendations = async (customerName, topN = 5) => {
  const response = await API.get(
    "/api/ai/recommend/" + encodeURIComponent(customerName) + "?top_n=" + topN
  );

  return response.data;
};

// ============================================================
// PHASE 5 - PERSONALIZED RECOMMENDATIONS
//
// There is no customer identifier in this call. The backend takes the
// account from the JWT, so a guest can only ever be shown their own
// history and there is no id in the browser to tamper with.
//
// Every field comes from the server, including the score components and
// the reason text. Nothing here is computed locally.
// ============================================================

export const getMyRecommendations = async (limit = 8) => {
  const response = await API.get("/api/ai/recommend/me?limit=" + limit);
  return response.data;
};

// ============================================================
// PHASE 5 - ADMIN ANALYTICS
//
// Every function below is admin-only on the server. A customer token is
// refused with 403, so the UI never has to hide these figures itself.
// ============================================================

export const getAnalyticsOverview = async () => {
  const response = await API.get("/api/analytics/overview");
  return response.data;
};

export const getRevenueAnalytics = async (range = "last_7_days") => {
  const response = await API.get(
    "/api/analytics/revenue?range=" + encodeURIComponent(range)
  );
  return response.data;
};

export const getRevenueTrend = async (range = "last_7_days") => {
  const response = await API.get(
    "/api/analytics/revenue/trend?range=" + encodeURIComponent(range)
  );
  return response.data;
};

export const getSalesAnalytics = async (range = "last_7_days") => {
  const response = await API.get(
    "/api/analytics/sales?range=" + encodeURIComponent(range)
  );
  return response.data;
};

export const getTopDishesAnalytics = async (limit = 5, range = null) => {
  let path = "/api/analytics/top-dishes?limit=" + limit;

  if (range) {
    path += "&range=" + encodeURIComponent(range);
  }

  const response = await API.get(path);
  return response.data;
};

export const getRevenueByCategory = async (range = "all_time") => {
  const response = await API.get(
    "/api/analytics/revenue-by-category?range=" + encodeURIComponent(range)
  );
  return response.data;
};

export const getOrderAnalytics = async () => {
  const response = await API.get("/api/analytics/orders");
  return response.data;
};

export const getWastageAnalytics = async (range = "last_30_days") => {
  const response = await API.get(
    "/api/analytics/wastage?range=" + encodeURIComponent(range)
  );
  return response.data;
};

export const getInventoryAnalytics = async () => {
  const response = await API.get("/api/analytics/inventory");
  return response.data;
};

export const getCustomerAnalytics = async () => {
  const response = await API.get("/api/analytics/customer-summary");
  return response.data;
};

// ============================================================
// PHASE 5 - ADMIN AI BUSINESS ASSISTANT
//
// Deterministic on the server: the question is matched to a fixed
// intent and the numbers come from MySQL. `answered: false` means the
// question was not recognised and `answer` is a refusal carrying no
// figures - the UI shows it as-is and renders no chart.
// ============================================================

export const askBusinessQuestion = async (question) => {
  const response = await API.post("/api/ai/assistant", { question });
  return response.data;
};

export const getAssistantSuggestions = async () => {
  const response = await API.get("/api/ai/assistant/suggestions");
  return response.data;
};

// ============================================================
// PHASE 6B - RESTAURANT-WIDE AI OPERATIONS ASSISTANT
//
// The Phase 5 endpoints above stay in place and keep working. These are
// the open-question ones: no intent, no category, no menu to pick from.
//
// `context` carries the conversation. The server returns an updated one on
// every answer and the caller sends it back with the next question, which
// is what lets "what about the previous week?" mean something. The
// context holds only the resolved window and domains - no question text -
// and it lives in the browser, so there is no server-side conversation to
// store, expire or leak.
// ============================================================

export const askRestaurantQuestion = async (question, context = null) => {
  const response = await API.post("/api/ai/assistant/ask", {
    question,
    context: context ?? null,
  });

  return response.data;
};

export const startAssistantConversation = async () => {
  const response = await API.get("/api/ai/assistant/context");
  return response.data.context;
};

// Documentation of what the assistant can reach. Shown for transparency
// only - the admin never chooses a source; the server picks them.
export const getAssistantCapabilities = async () => {
  const response = await API.get("/api/ai/assistant/capabilities");
  return response.data;
};

export const getPopularDishes = async (topN = 5) => {
  const response = await API.get(
    "/api/ai/popular-dishes?top_n=" + topN
  );

  return response.data;
};

export const classifySentiment = async (text) => {
  const response = await API.post("/api/ai/sentiment", { text });
  return response.data;
};

export const getSentimentSummary = async () => {
  const response = await API.get("/api/ai/sentiment/summary");
  return response.data;
};

export const getDemandForecast = async (daysAhead = 7, topN = 5) => {
  const response = await API.get(
    "/api/ai/demand-forecast?days_ahead=" + daysAhead + "&top_n=" + topN
  );

  return response.data;
};

export const getRevenueForecast = async (daysAhead = 7) => {
  const response = await API.get(
    "/api/ai/revenue-forecast?days_ahead=" + daysAhead
  );

  return response.data;
};

export const getWasteAnalysisAI = async () => {
  const response = await API.get("/api/ai/waste-analysis");
  return response.data;
};

export const getDynamicPricing = async () => {
  const response = await API.get("/api/ai/dynamic-pricing");
  return response.data;
};

// ============================================================
// REVIEWS
// ============================================================

export const getReviews = async () => {
  const response = await API.get("/api/reviews/");
  return response.data;
};

export const createReview = async (review) => {
  const response = await API.post("/api/reviews/", review);
  return response.data;
};

export const deleteReview = async (id) => {
  const response = await API.delete("/api/reviews/" + String(id));
  return response.data;
};

// ============================================================
// SUPPLIERS
// ============================================================

export const getSuppliers = async () => {
  const response = await API.get("/api/suppliers/");
  return response.data;
};

export const createSupplier = async (supplier) => {
  const response = await API.post("/api/suppliers/", supplier);
  return response.data;
};

export const updateSupplier = async (id, supplier) => {
  const response = await API.put("/api/suppliers/" + String(id), supplier);
  return response.data;
};

export const deleteSupplier = async (id) => {
  const response = await API.delete("/api/suppliers/" + String(id));
  return response.data;
};

// ============================================================
// STAFF
// ============================================================

export const getStaff = async () => {
  const response = await API.get("/api/staff/");
  return response.data;
};

export const createStaff = async (member) => {
  const response = await API.post("/api/staff/", member);
  return response.data;
};

export const updateStaff = async (id, member) => {
  const response = await API.put("/api/staff/" + String(id), member);
  return response.data;
};

export const deleteStaff = async (id) => {
  const response = await API.delete("/api/staff/" + String(id));
  return response.data;
};

// ============================================================
// WASTE
// ============================================================

export const getWaste = async () => {
  const response = await API.get("/api/waste/");
  return response.data;
};

export const getWasteAnalysis = async () => {
  const response = await API.get("/api/waste/analysis");
  return response.data;
};

export const getEndOfDayReport = async (date) => {
  const response = await API.get("/api/waste/end-of-day", {
    params: date ? { day: date } : {},
  });

  return response.data;
};

export const closeDay = async (date, prepared) => {
  const response = await API.post("/api/waste/end-of-day", {
    date,
    prepared,
  });

  return response.data;
};

export const createWaste = async (record) => {
  const response = await API.post("/api/waste/", record);
  return response.data;
};

export const deleteWaste = async (id) => {
  const response = await API.delete("/api/waste/" + String(id));
  return response.data;
};

// ============================================================
// SETTINGS
// ============================================================

export const getSettings = async () => {
  const response = await API.get("/api/settings/");
  return response.data;
};

export const createSettings = async (settings) => {
  const response = await API.post("/api/settings/", settings);
  return response.data;
};

export const updateSettings = async (id, settings) => {
  const response = await API.put("/api/settings/" + String(id), settings);
  return response.data;
};

// ============================================================
// EXPORT AXIOS INSTANCE
// ============================================================

export default API;

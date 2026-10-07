import React, { useCallback, useEffect, useState } from "react";
import { QRCodeSVG } from "qrcode.react";

import {
 getOrderHeaders,
 updateOrderHeaderStatus,
 getOrderPayments,
 createPaymentRequest,
 verifyPayment,
 simulateDevelopmentPayment,
 getAdminPayableOrders,
 getAdminBillHistory,
 getAdminPaymentHistory,
 getAdminSettlementSummary,
 reconcilePayment,
} from "./api";
import { formatMoney } from "./money";

// The lifecycle, for display and the filter tabs. Which status may
// follow which is NOT decided here: every header carries
// valid_next_statuses from the server, and that is what the buttons are
// built from. A local copy of the rules could drift from the API and
// end up offering a transition the server refuses, so there isn't one.
const LIFECYCLE_STAGES = [
 "Placed",
 "Confirmed",
 "Preparing",
 "Ready",
 "Served",
 "Cancelled",
];

// ============================================================
// PAYMENTS & BILLS (Phase 6E)
//
// A separate view rather than another column on the orders table, because
// the question this answers is different: the order table answers "what
// has the kitchen got", this answers "what has the restaurant earned and
// what is still owed".
//
// The three headline figures are kept apart on purpose:
//
// billed what guests were charged
// collected what a payment provider confirmed
// outstanding billed minus collected
//
// Every figure arrives from the server. Nothing here sums rows to work out
// an amount, and there is no control that marks a bill paid.
function PaymentsAndBills() {
 const [view, setView] = useState("bills");

 const [range, setRange] = useState("last_30_days");
 const [summary, setSummary] = useState(null);

 // Filters are a draft. They only take effect when Apply is pressed, so
 // typing a customer name does not fire a query on every keystroke.
 const [billFilters, setBillFilters] = useState({
 payment_status: "",
 order_status: "",
 customer_name: "",
 range_key: "",
 });
 const [appliedBills, setAppliedBills] = useState(billFilters);
 const [bills, setBills] = useState(null);
 const [billPage, setBillPage] = useState(1);

 const [historyFilters, setHistoryFilters] = useState({
 payment_status: "",
 customer_name: "",
 range_key: "",
 });
 const [appliedLedger, setAppliedLedger] = useState(historyFilters);
 const [ledger, setLedger] = useState(null);
 const [ledgerPage, setLedgerPage] = useState(1);

 const [detail, setDetail] = useState(null);
 const [error, setError] = useState("");
 const [reconcileBusy, setReconcileBusy] = useState(null);
 const [reconcileResult, setReconcileResult] = useState(null);

 const PAGE_SIZE = 10;

 // Three pure fetchers and three state writers, deliberately separate.
 // The effects below need a request that does not touch state, and the
 // pager buttons need one that does; sharing a single function that did
 // both would force the effects to update state during the render phase.
 const fetchSummary = useCallback(
 () =>getAdminSettlementSummary(range),
 [range],
 );

 const fetchBills = useCallback(
 (page = 1) =>getAdminBillHistory(appliedBills, page, PAGE_SIZE),
 [appliedBills],
 );

 const fetchLedger = useCallback(
 (page = 1) =>getAdminPaymentHistory(appliedLedger, page, PAGE_SIZE),
 [appliedLedger],
 );

 const loadSummary = useCallback(() => {
 fetchSummary()
 .then(setSummary)
 .catch((err) =>console.error(err));
 }, [fetchSummary]);

 // Used by the pager buttons, so it may set state directly.
 const loadBills = useCallback(
 (page = 1) =>
 fetchBills(page)
 .then((data) => {
 setBills(data);
 setBillPage(page);
 setError("");
 })
 .catch((err) => {
 setError(
 err.response?.data?.detail || "Could not load the bill history.",
 );
 }),
 [fetchBills],
 );

 const loadLedger = useCallback(
 (page = 1) =>
 fetchLedger(page)
 .then((data) => {
 setLedger(data);
 setLedgerPage(page);
 setError("");
 })
 .catch((err) => {
 setError(
 err.response?.data?.detail || "Could not load the payment ledger.",
 );
 }),
 [fetchLedger],
 );

 // Loading is derived, not assigned: the active view is loading exactly
 // when it has no rows yet. A stored flag would be a second thing that
 // has to be kept in step with the data.
 const loading =
 view === "bills" ? bills === null : ledger === null;

 // Only the active view is fetched. An operator opening this page should
 // not pay for both queries.
 useEffect(() => {
 loadSummary();
 }, [loadSummary]);

 useEffect(() => {
 let cancelled = false;

 const request =
 view === "bills" ? fetchBills(1) : fetchLedger(1);

 request
 .then((data) => {
 if (cancelled) return;

 if (view === "bills") {
 setBills(data);
 setBillPage(1);
 } else {
 setLedger(data);
 setLedgerPage(1);
 }

 setError("");
 })
 .catch((err) => {
 if (cancelled) return;

 setError(
 err.response?.data?.detail || "Could not load the payment data.",
 );
 });

 // A filter change or a view switch leaves the previous request in
 // flight. Dropping its result stops a slow page 1 overwriting page 2.
 return () => {
 cancelled = true;
 };
 }, [view, fetchBills, fetchLedger]);

 const runReconcile = async (paymentId) => {
 setReconcileBusy(paymentId);
 setReconcileResult(null);

 try {
 setReconcileResult(await reconcilePayment(paymentId));
 } catch (err) {
 setReconcileResult({
 payment_id: paymentId,
 limitation:
 err.response?.data?.detail || "Could not reach the provider.",
 });
 } finally {
 setReconcileBusy(null);
 }
 };

 const openDetail = async (bill) => {
 setDetail({ bill, attempts: null });

 try {
 const data = await getOrderPayments(bill.order_id);
 setDetail({ bill, attempts: data.payments || [] });
 } catch (err) {
 console.error(err);
 setDetail({ bill, attempts: [], error: true });
 }
 };

 const totals = summary || {};

 // One place decides the badge, from the server's own flags, so the
 // colour and the word can never disagree.
 const providerModeClass = totals.gateway?.live_mode
 ? "live"
 : totals.gateway?.test_mode
 ? "test"
 : "dev";

 return (
 <div className="payments-page">
 <div className="page-header">
 <div>
 <h1>Payments &amp; Bills</h1>
 <p>
 What guests have been charged, what has actually been collected,
 and what is still owed.
 </p>
 </div>

 <div className="pay-view-switch">
 <button
 className={view === "bills" ? "active" : ""}
 onClick={() =>setView("bills")}
 >
 Bills
 </button>
 <button
 className={view === "ledger" ? "active" : ""}
 onClick={() =>setView("ledger")}
 >
 Payment attempts
 </button>
 </div>
 </div>

 {/* ---- the three figures, never added together ---- */}
 <div className="settle-tiles">
 <div className="settle-tile settle-tile-billed">
 <span className="settle-tile-label">Total billed</span>
 <strong>
 {formatMoney(totals.billed ?? 0, "INR")}
 </strong>
 <span className="settle-tile-sub">
 {totals.bills ?? 0} bill{totals.bills === 1 ? "" : "s"} raised
 </span>
 </div>

 <div className="settle-tile settle-tile-collected">
 <span className="settle-tile-label">Total collected</span>
 <strong>
 {formatMoney(totals.collected ?? 0, "INR")}
 </strong>
 <span className="settle-tile-sub">
 {totals.paid_bills ?? 0} fully paid, confirmed by the provider
 </span>
 </div>

 <div className="settle-tile settle-tile-outstanding">
 <span className="settle-tile-label">Total outstanding</span>
 <strong>
 {formatMoney(totals.outstanding ?? 0, "INR")}
 </strong>
 <span className="settle-tile-sub">
 {totals.unpaid_bills ?? 0} unpaid
 {totals.partially_paid_bills > 0
 ? `, ${totals.partially_paid_bills} part paid`
 : ""}
 </span>
 </div>

 <div className="settle-tile">
 <span className="settle-tile-label">Failed attempts</span>
 <strong>{totals.failed_payment_attempts ?? 0}</strong>
 <span className="settle-tile-sub">
 {totals.payment_attempts ?? 0} attempt
 {totals.payment_attempts === 1 ? "" : "s"} in total
 </span>
 </div>
 </div>

 {/* Provider and mode, straight from the backend's own
 configuration. Never inferred in the browser, and never shown as
 LIVE unless the server said so. */}
 <div className="settle-provider-bar">
 <span className="settle-provider-name">
 Provider: {totals.gateway?.provider || "none"}
 </span>

 <span className={"settle-mode settle-mode-" + providerModeClass}>
 Mode:{" "}
 {totals.gateway?.live_mode
 ? "LIVE"
 : totals.gateway?.test_mode
 ? "TEST"
 : (totals.gateway?.mode || "unknown").toUpperCase()}
 </span>

 <span className="settle-provider-note">
 {totals.gateway?.gateway_statement}
 </span>
 </div>

 <div className="pay-range-row">
 <label htmlFor="settle-range">Period</label>
 <select
 id="settle-range"
 value={range}
 onChange={(event) =>setRange(event.target.value)}
 >
 {[
 "today", "yesterday", "last_7_days", "last_14_days",
 "last_30_days", "last_90_days", "this_month", "previous_month",
 "this_quarter", "last_quarter", "this_year", "all_time",
 ].map((key) => (
 <option key={key} value={key}>
 {key.replace(/_/g, " ")}
 </option>
 ))}
 </select>
 </div>

 {error && <div className="error-message">{error}</div>}

 {view === "bills" && (
 <div className="settle-panel">
 <div className="pay-filter-row">
 <select
 value={billFilters.payment_status}
 onChange={(event) =>
 setBillFilters((previous) => ({
 ...previous,
 payment_status: event.target.value,
 }))
 }
 >
 <option value="">Any payment state</option>
 <option value="PAID">Paid</option>
 <option value="PARTIALLY_PAID">Partially paid</option>
 <option value="UNPAID">Unpaid</option>
 </select>

 <select
 value={billFilters.order_status}
 onChange={(event) =>
 setBillFilters((previous) => ({
 ...previous,
 order_status: event.target.value,
 }))
 }
 >
 <option value="">Any order status</option>
 {LIFECYCLE_STAGES.map((stage) => (
 <option key={stage} value={stage}>
 {stage}
 </option>
 ))}
 </select>

 <input
 type="text"
 placeholder="Customer name"
 value={billFilters.customer_name}
 onChange={(event) =>
 setBillFilters((previous) => ({
 ...previous,
 customer_name: event.target.value,
 }))
 }
 />

 <button
 className="action-btn"
 onClick={() =>setAppliedBills({ ...billFilters })}
 >
 Apply
 </button>
 </div>

 {loading && <p className="empty-note">Loading bills…</p>}

 {!loading && bills && bills.bills.length === 0 && (
 <p className="empty-note">No bills match these filters.</p>
 )}

 {!loading && bills && bills.bills.length > 0 && (
 <>
 <p className="settle-summary-line">
 {bills.summary.bills} bill
 {bills.summary.bills === 1 ? "" : "s"} matching — billed{" "}
 {formatMoney(bills.summary.billed, "INR")}, collected{" "}
 {formatMoney(bills.summary.collected, "INR")}, outstanding{" "}
 {formatMoney(bills.summary.outstanding, "INR")}
 </p>

 <div className="table-responsive">
 <table>
 <thead>
 <tr>
 <th>Order</th>
 <th>Customer</th>
 <th>Bill</th>
 <th>Paid</th>
 <th>Outstanding</th>
 <th>Status</th>
 <th>Date</th>
 <th />
 </tr>
 </thead>
 <tbody>
 {bills.bills.map((bill) => (
 <tr key={bill.order_id}>
 <td>
 <strong>{bill.reference}</strong>
 </td>
 <td>{bill.customer_name || "-"}</td>
 <td>
 {formatMoney(bill.total_amount, bill.currency)}
 </td>
 <td className="settle-cell-collected">
 {bill.paid_amount > 0
 ? formatMoney(bill.paid_amount, bill.currency)
 : "-"}
 </td>
 <td className="settle-cell-outstanding">
 {bill.outstanding_amount > 0
 ? formatMoney(
 bill.outstanding_amount,
 bill.currency,
 )
 : "-"}
 </td>
 <td>
 <span
 className={`history-state history-state-${bill.billed_state.toLowerCase()}`}
 >
 {bill.billed_state === "PARTIALLY_PAID"
 ? "Part paid"
 : bill.billed_state === "PAID"
 ? "Paid"
 : "Unpaid"}
 </span>
 </td>
 <td>
 {bill.created_at
 ? bill.created_at.replace("T", " ").slice(0, 16)
 : "-"}
 </td>
 <td>
 <button
 className="action-btn"
 onClick={() =>openDetail(bill)}
 >
 Detail
 </button>
 </td>
 </tr>
 ))}
 </tbody>
 </table>
 </div>

 <div className="pay-pager">
 <button
 className="action-btn"
 disabled={billPage <= 1}
 onClick={() =>loadBills(billPage - 1)}
 >
 ← Previous
 </button>
 <span>
 Page {bills.pagination.page} of{" "}
 {bills.pagination.total_pages} ·{" "}
 {bills.pagination.total_matching} matching
 </span>
 <button
 className="action-btn"
 disabled={billPage >= bills.pagination.total_pages}
 onClick={() =>loadBills(billPage + 1)}
 >
 Next →
 </button>
 </div>
 </>
 )}
 </div>
 )}

 {view === "ledger" && (
 <div className="settle-panel">
 <div className="pay-filter-row">
 <select
 value={historyFilters.payment_status}
 onChange={(event) =>
 setHistoryFilters((previous) => ({
 ...previous,
 payment_status: event.target.value,
 }))
 }
 >
 <option value="">Any attempt state</option>
 <option value="SUCCESS">Confirmed</option>
 <option value="PENDING">Awaiting confirmation</option>
 <option value="FAILED">Failed</option>
 <option value="CANCELLED">Withdrawn</option>
 </select>

 <input
 type="text"
 placeholder="Customer name"
 value={historyFilters.customer_name}
 onChange={(event) =>
 setHistoryFilters((previous) => ({
 ...previous,
 customer_name: event.target.value,
 }))
 }
 />

 <button
 className="action-btn"
 onClick={() =>setAppliedLedger({ ...historyFilters })}
 >
 Apply
 </button>
 </div>

 <p className="settle-summary-line">
 {ledger
 ? `${ledger.counts.attempts} attempt${
 ledger.counts.attempts === 1 ? "" : "s"
 } — ${ledger.counts.successful_attempts} confirmed, ${
 ledger.counts.failed_attempts
 } failed, ${ledger.counts.cancelled_attempts} withdrawn, ${
 ledger.counts.pending_attempts
 } awaiting confirmation`
 : ""}
 </p>

 {loading && <p className="empty-note">Loading attempts…</p>}

 {!loading && ledger && ledger.payments.length === 0 && (
 <p className="empty-note">
 No payment attempts have been made yet.
 </p>
 )}

 {!loading && ledger && ledger.payments.length > 0 && (
 <>
 <div className="table-responsive">
 <table>
 <thead>
 <tr>
 <th>Attempt</th>
 <th>Order</th>
 <th>Customer</th>
 <th>Amount</th>
 <th>State</th>
 <th>Provider</th>
 <th>Reference</th>
 <th>Requested</th>
 </tr>
 </thead>
 <tbody>
 {ledger.payments.map((payment) => (
 <tr key={payment.payment_id}>
 <td>#{payment.payment_id}</td>
 <td>{payment.order_reference || payment.order_id}</td>
 <td>{payment.customer_name || "-"}</td>
 <td>
 {formatMoney(payment.amount, payment.currency)}
 </td>
 <td>
 <span
 className={`pay-state-badge pay-state-${payment.status.toLowerCase()}`}
 >
 {payment.status}
 </span>
 </td>
 <td>{payment.provider}</td>
 <td>
 <code>{payment.provider_reference || "-"}</code>
 </td>
 <td>
 {payment.requested_at
 ? payment.requested_at.replace("T", " ").slice(0, 16)
 : "-"}
 </td>
 </tr>
 ))}
 </tbody>
 </table>
 </div>

 <div className="pay-pager">
 <button
 className="action-btn"
 disabled={ledgerPage <= 1}
 onClick={() =>loadLedger(ledgerPage - 1)}
 >
 ← Previous
 </button>
 <span>
 Page {ledger.pagination.page} of{" "}
 {ledger.pagination.total_pages} ·{" "}
 {ledger.pagination.total_matching} attempts
 </span>
 <button
 className="action-btn"
 disabled={ledgerPage >= ledger.pagination.total_pages}
 onClick={() =>loadLedger(ledgerPage + 1)}
 >
 Next →
 </button>
 </div>
 </>
 )}
 </div>
 )}

 {/* ---- one bill, every attempt it ever had ---- */}
 {detail && (
 <div
 className="modal-backdrop"
 onClick={() =>setDetail(null)}
 >
 <div
 className="order-detail-modal"
 onClick={(event) =>event.stopPropagation()}
 >
 <div className="modal-header">
 <h2>Bill {detail.bill.reference}</h2>
 <button
 className="modal-close"
 onClick={() =>setDetail(null)}
 >
 ✕
 </button>
 </div>

 <div className="modal-content">
 <div className="detail-section">
 <h3>Bill summary</h3>

 <div className="detail-grid">
 <div>
 <label>Customer</label>
 <strong>
 {detail.bill.customer_name || "-"}
 </strong>
 </div>
 <div>
 <label>Order status</label>
 <strong>{detail.bill.order_status}</strong>
 </div>
 <div>
 <label>Bill total</label>
 <strong>
 {formatMoney(
 detail.bill.total_amount,
 detail.bill.currency,
 )}
 </strong>
 </div>
 <div>
 <label>Paid</label>
 <strong>
 {formatMoney(
 detail.bill.paid_amount,
 detail.bill.currency,
 )}
 </strong>
 </div>
 <div>
 <label>Outstanding</label>
 <strong>
 {formatMoney(
 detail.bill.outstanding_amount,
 detail.bill.currency,
 )}
 </strong>
 </div>
 <div>
 <label>Payment state</label>
 <strong>{detail.bill.billed_state}</strong>
 </div>
 </div>
 </div>

 <div className="detail-section">
 <h3>Payment attempts</h3>

 {!detail.attempts ? (
 <p className="pay-panel-note">Loading attempts…</p>
 ) : detail.attempts.length === 0 ? (
 <p className="pay-panel-note">
 No payment has ever been requested for this bill.
 </p>
 ) : (
 <div className="pay-attempts">
 {detail.attempts.map((payment, index) => (
 <div key={payment.payment_id} className="pay-attempt">
 <div className="pay-attempt-head">
 <span className="pay-attempt-label">
 Attempt #{index + 1}
 </span>

 <span
 className={`pay-state-badge pay-state-${payment.status.toLowerCase()}`}
 >
 {payment.status}
 </span>

 <strong>
 {formatMoney(
 payment.amount,
 payment.currency,
 )}
 </strong>
 </div>

 <div className="pay-attempt-meta">
 <span>
 {payment.method} · {payment.provider}
 </span>

 {payment.provider_reference && (
 <code>{payment.provider_reference}</code>
 )}
 </div>

 <div className="pay-attempt-meta">
 Requested{" "}
 {payment.requested_at
 ? payment.requested_at.replace("T", " ")
 : "-"}

 {payment.paid_at
 ? ` · Paid ${payment.paid_at.replace("T", " ")}`
 : ""}
 </div>

 {/* A comparison, never a repair. If the provider
 disagrees with this row the answer is reported
 for a person to look at. */}
 <div className="pay-attempt-actions">
 <button
 className="action-btn"
 disabled={reconcileBusy === payment.payment_id}
 onClick={() =>runReconcile(payment.payment_id)}
 >
 {reconcileBusy === payment.payment_id
 ? "Comparing\u2026"
 : "Reconcile with provider"}
 </button>
 </div>

 {reconcileResult &&
 reconcileResult.payment_id ===
 payment.payment_id && (
 <div className="pay-attempt-meta pay-reconcile">
 {reconcileResult.limitation
 ? reconcileResult.limitation
 : `Local ${reconcileResult.local_amount} ${
 reconcileResult.local_currency
 } vs provider ${
 reconcileResult.remote_amount
 } ${reconcileResult.remote_currency || "?"} ${
 reconcileResult.matches
 ? "\u2014 agrees"
 : "\u2014 DIFFERS, needs review"
 }`}
 </div>
 )}

 {payment.failure_reason && (
 <div className="pay-attempt-meta pay-panel-warn">
 {payment.failure_reason}
 </div>
 )}
 </div>
 ))}
 </div>
 )}
 </div>
 </div>
 </div>
 </div>
 )}
 </div>
 );
}

function Orders() {
 const [orderHeaders, setOrderHeaders] = useState([]);
 const [loading, setLoading] = useState(true);
 const [error, setError] = useState("");
 const [filterStatus, setFilterStatus] = useState("All");
 const [selectedHeader, setSelectedHeader] = useState(null);

 /* ============================================================
 PAYMENT PANEL (Phase 6D)

 Deliberately absent: a "Mark as Paid"button. There is no such
 action anywhere in this application, because a bill is paid when a
 provider confirms it, not when somebody clicks.

 What staff can do is ask for payment - which produces a QR the guest
 can scan - and check whether a payment has been confirmed. Both are
 requests to the backend; neither decides anything.
 ============================================================ */

 // The server's ledger view of the selected bill. Read fresh whenever a
 // bill is opened, so nothing here is inferred from the header row.
 const [billPayments, setBillPayments] = useState(null);
 const [payBusy, setPayBusy] = useState(false);
 const [payNotice, setPayNotice] = useState("");

 // Whether the development simulation control is offered at all. It is
 // driven by the server's own configuration, never by a build flag, so
 // it disappears the moment payments stop being in development mode.
 const [simEnabled, setSimEnabled] = useState(false);

 // Read the gateway configuration once. Simulation is offered only when
 // the server says it is available, so the control disappears on its own
 // when payments leave development mode - there is no build flag and no
 // local setting that could keep it visible.
 useEffect(() => {
 getAdminPayableOrders()
 .then((data) =>
 setSimEnabled(Boolean(data?.gateway?.simulation_enabled)),
 )
 .catch(() =>setSimEnabled(false));
 }, []);

 useEffect(() => {
 loadData();
 }, []);

const loadBillPayments = async (headerId) => {
  try {
  setPayNotice("");
  const data = await getOrderPayments(headerId);

  setBillPayments(data);
  } catch (err) {
  console.error(err);
  setBillPayments(null);
  }
  };

const isLegacyHeader = (header) => header.is_legacy === true || header.id < 0;

  const openHeader = async (header) => {
  setSelectedHeader(header);
  setBillPayments(null);
  setPayNotice("");
  if (!isLegacyHeader(header)) {
  await loadBillPayments(header.id);
  }
  };

 useEffect(() => {
 loadData();
 }, []);

 const loadData = async () => {
 try {
 setLoading(true);
 setError("");
 const headersData = await getOrderHeaders();
 setOrderHeaders(headersData);
 } catch (err) {
 console.error(err);
 setError("Failed to load orders.");
 } finally {
 setLoading(false);
 }
 };

 const handleStatusChange = async (headerId, newStatus) => {
 try {
 const updated = await updateOrderHeaderStatus(headerId, newStatus);
 await loadData();
 // The response is authoritative for the new status, the payment
 // status (unchanged) and the remaining transitions, so the modal
 // is refreshed from it rather than from a guess.
 if (selectedHeader && selectedHeader.id === headerId) {
 setSelectedHeader({ ...selectedHeader, ...updated, id: headerId });
 }
 } catch (err) {
 console.error(err);
 setError(`Failed to update order: ${err.response?.data?.detail || err.message}`);
 }
 };

 const getValidNextStatuses = (header) =>header?.valid_next_statuses || [];

 const filteredHeaders = filterStatus === "All"
 ? orderHeaders
 : orderHeaders.filter(h =>h.status === filterStatus);

 const statusCounts = orderHeaders.reduce((acc, h) => {
 acc[h.status] = (acc[h.status] || 0) + 1;
 return acc;
 }, {});

 if (loading) {
 return (
 <div className="orders-page">
 <div className="page-header">
 <div>
 <h1>Order Management</h1>
 <p>Manage your restaurant orders.</p>
 </div>
 </div>
 <p>Loading orders...</p>
 </div>
);
  }

  // Compute payment attempts content for non-legacy headers
  const paymentAttemptsContent = !isLegacyHeader(selectedHeader) && billPayments ? (
    billPayments.payments.length === 0 ? (
      <p className="pay-panel-note">
        No payment has been requested for this bill yet.
      </p>
    ) : (
      <div className="pay-attempts">
        {billPayments.payments.map((payment) => (
          <div key={payment.payment_id} className="pay-attempt">
            <div className="pay-attempt-head">
              <span className={`pay-state-badge pay-state-${payment.status.toLowerCase()}`}>
                {payment.status}
              </span>
              <strong>{formatMoney(payment.amount, payment.currency)}</strong>
            </div>
            <div className="pay-attempt-meta">
              <span>{payment.method} \u00b7 {payment.provider}</span>
              {payment.provider_reference && <code>{payment.provider_reference}</code>}
            </div>
            {payment.paid_at && (
              <div className="pay-attempt-meta">
                Paid {new Date(payment.paid_at).toLocaleString()}
              </div>
            )}
            {payment.failure_reason && (
              <div className="pay-attempt-meta pay-panel-warn">
                {payment.failure_reason}
              </div>
            )}
            {payment.status === "PENDING" && payment.request?.upi_uri && (
              <div className="pay-qr-wrap pay-qr-small">
                <QRCodeSVG className="pay-qr" value={payment.request.upi_uri} size={168} level="M" marginSize={2} title="UPI payment QR code" />
                <p className="pay-panel-note">
                  Show this to the guest, or <a className="pay-upi-link" href={payment.request.upi_uri}>open it</a>.
                </p>
              </div>
            )}
            <div className="pay-attempt-actions">
              {payment.status === "PENDING" && (
                <button className="action-btn" disabled={payBusy} onClick={() => runAdminAction("Check payment", () => verifyPayment(payment.payment_id))}>
                  Check payment
                </button>
              )}
              {simEnabled && payment.status !== "SUCCESS" && (
                <button className="action-btn dev-action" disabled={payBusy} onClick={() => runAdminAction("Simulate payment", () => simulateDevelopmentPayment(payment.payment_id, "SUCCESS"))}>
                  Simulate verified payment (TEST)
                </button>
              )}
            </div>
          </div>
        ))}
      </div>
    )
  ) : null;

  return (
 <div className="orders-page">
 <div className="page-header">
 <div>
 <h1>Order Management</h1>
 <p>Manage your restaurant orders.</p>
 </div>
 </div>

 {error && <div className="error-message">{error}</div>}

 {/* Status Filter Tabs */}
 <div className="status-filter-tabs">
 {["All", ...LIFECYCLE_STAGES].map((status) => (
 <button
 key={status}
 className={filterStatus === status ? "active" : ""}
 onClick={() =>setFilterStatus(status)}
 >
 {status} <span className="count-badge">{statusCounts[status] || 0}</span>
 </button>
 ))}
 </div>

 {/* Orders Table */}
 <div className="orders-table-panel">
 {filteredHeaders.length === 0 ? (
 <div className="empty-state">
 <h3>No Orders</h3>
 <p>No orders match the current filter.</p>
 </div>
 ) : (
 <div className="table-responsive">
 <table>
 <thead>
 <tr>
 <th>Reference</th>
 <th>Customer</th>
 <th>Table</th>
 <th>Items</th>
 <th>Total</th>
 <th>Status</th>
 <th>Payment</th>
 <th>Placed</th>
 <th>Updated</th>
 <th>Actions</th>
 </tr>
 </thead>
 <tbody>
 {filteredHeaders.map((header) => (<tr key={header.id} onClick={() =>openHeader(header)}>
 <td><strong>{header.reference}</strong></td>
 <td>{header.customer_name}</td>
 <td>
 {header.table_number ? `Table ${header.table_number}` : header.order_type}
 </td>
 <td>
 {header.items && header.items.map((item, idx) => (
 <div key={idx} className="table-item">
 {item.menu_item} × {item.quantity}
 </div>
 ))}
 </td>
 <td>{formatMoney(header.total_amount, header.currency)}</td>
 <td>
 <span className={`status-pill ${header.status.toLowerCase()}`}>
 {header.status}
 </span>
 </td>
 <td>
 <span className={`payment-status-pill ${(header.payment_status || 'unpaid').toLowerCase()}`}>
 {header.payment_status === 'unpaid' ? 'UNPAID' : (header.payment_status || 'unpaid').toUpperCase()}
 </span>
 </td>
 <td>{header.placed_at ? new Date(header.placed_at).toLocaleString() : '-'}</td>
 <td>{header.updated_at ? new Date(header.updated_at).toLocaleString() : '-'}</td>
<td>
  <button
  className="action-btn"
  onClick={(e) => { e.stopPropagation(); openHeader(header); }}
  >
  {isLegacyHeader(header) ? "View (Legacy)" : "View"}
  </button>
  </td>
 </tr>
 ))}
 </tbody>
 </table>
 </div>
 )}
 </div>

 {/* Order Detail Modal */}
 {selectedHeader && (
 <div className="modal-backdrop"onClick={() =>setSelectedHeader(null)}>
 <div className="order-detail-modal"onClick={(e) =>e.stopPropagation()}>
 <div className="modal-header">
 <h2>Order {selectedHeader.reference}</h2>
 <button className="modal-close"onClick={() =>setSelectedHeader(null)}>✕</button>
 </div>

<div className="modal-content">
  {isLegacyHeader(selectedHeader) && (
  <div className="legacy-notice">
  <strong>Legacy Order</strong> — This order was created before the current order header system.
  Status transitions and payment actions are not available for historical records.
  </div>
  )}

  <div className="detail-section">
  <h3>Order Info</h3>
 <div className="detail-grid">
 <div><label>Reference</label> <strong>{selectedHeader.reference}</strong></div>
 <div><label>Customer</label> <strong>{selectedHeader.customer_name}</strong></div>
 <div><label>Email</label> <strong>{selectedHeader.customer_email || '-'}</strong></div>
 <div><label>Type</label> <strong>{selectedHeader.order_type}</strong></div>
 <div><label>Table</label> <strong>{selectedHeader.table_number ? `Table ${selectedHeader.table_number}` : 'N/A'}</strong></div>
 <div><label>Total</label> <strong>{formatMoney(selectedHeader.total_amount, selectedHeader.currency)}</strong></div>
 <div><label>Currency</label> <strong>{selectedHeader.currency}</strong></div>
 <div><label>Placed</label> <strong>{selectedHeader.placed_at ? new Date(selectedHeader.placed_at).toLocaleString() : '-'}</strong></div>
 <div><label>Updated</label> <strong>{selectedHeader.updated_at ? new Date(selectedHeader.updated_at).toLocaleString() : '-'}</strong></div>
 </div>
 </div>

 <div className="detail-section">
 <h3>Items</h3>
 <div className="items-list">
 {selectedHeader.items && selectedHeader.items.map((item, idx) => (
 <div key={idx} className="detail-item">
 <div className="item-main">
 <span className="item-name">{item.menu_item}</span>
 <span className="item-qty">× {item.quantity}</span>
 <span className="item-price">{formatMoney(item.line_total, selectedHeader.currency)}</span>
 </div>
 {item.special_instructions && (
 <div className="item-notes"> {item.special_instructions}</div>
 )}
 </div>
 ))}
 </div>
 </div>

 <div className="detail-section">
 <h3>Status Management</h3>
 <div className="status-management">
 <div className="current-status">
 <label>Current Status:</label>
 <span className={`status-pill-large ${selectedHeader.status.toLowerCase()}`}>
 {selectedHeader.status}
 </span>
 <span className="payment-status">
 Payment: <strong>{selectedHeader.payment_status === 'unpaid' ? 'UNPAID' : selectedHeader.payment_status.toUpperCase()}</strong>
 </span>
 </div>

 <div className="status-actions">
 <label>Transition to:</label>
 <div className="transition-buttons">
 {getValidNextStatuses(selectedHeader).map((nextStatus) => (
 <button
 key={nextStatus}
 className={`transition-btn ${nextStatus === 'Cancelled' ? 'danger' : ''}`}
 onClick={() =>handleStatusChange(selectedHeader.id, nextStatus)}
 >
 {nextStatus}
 </button>
 ))}
 {getValidNextStatuses(selectedHeader).length === 0 && (
 <span className="no-transitions">No valid transitions (terminal state)</span>
 )}
 </div>
 </div>

 <div className="lifecycle-visual">
 <h4>Order Lifecycle</h4>
 <div className="lifecycle-bar">
 {LIFECYCLE_STAGES.map((stage, index) => (
 <div key={stage} className={`lifecycle-step ${selectedHeader.status === stage ? 'active' : (LIFECYCLE_STAGES.indexOf(selectedHeader.status) >index ? 'completed' : '')}`}>
 <div className="step-circle">{index + 1}</div>
 <div className="step-label">{stage}</div>
 </div>
 ))}
 </div>
</div>
  </div>
  </div>

  {/* ---- Payment (Phase 6D) ----
  The amount shown is the header's own total. The actions
  are: ask for a payment, or check whether one has been
  confirmed. There is no control that sets paid. */}
  <div className="detail-section admin-pay-section">
  <h3>Bill & Payment</h3>

  <div className="detail-grid">
  <div>
  <label>Bill total</label>
  <strong>
  {formatMoney(
  selectedHeader.total_amount,
  selectedHeader.currency,
  )}
  </strong>
  </div>
  <div>
  <label>Amount paid</label>
  <strong>
  {formatMoney(
  billPayments?.state?.paid_amount ?? 0,
  selectedHeader.currency,
  )}
  </strong>
  </div>
  <div>
  <label>Outstanding</label>
  <strong>
  {formatMoney(
  billPayments?.state?.outstanding_amount ??
  selectedHeader.total_amount,
  selectedHeader.currency,
  )}
  </strong>
  </div>
  <div>
  <label>Payment status</label>
  <strong>
  {selectedHeader.payment_status === "unpaid"
  ? "UNPAID"
  : selectedHeader.payment_status.toUpperCase()}
  </strong>
  </div>
  </div>

  {!billPayments && (
  <p className="pay-panel-note">
  {payBusy ? "Reading payment records…" : ""}
  </p>
  )}

  {billPayments && (
  <>
  {billPayments.payments.length === 0 && (
  <p className="pay-panel-note">
  No payment has been requested for this bill yet.
  </p>
  )}

  {billPayments.payments.length > 0 && (
  <div className="pay-attempts">
  {billPayments.payments.map((payment) => (
  <div
  key={payment.payment_id}
  className="pay-attempt"
  >
  <div className="pay-attempt-head">
  <span
  className={`pay-state-badge pay-state-${payment.status.toLowerCase()}`}
  >
  {payment.status}
  </span>
  <strong>
  {formatMoney(
  payment.amount,
  payment.currency,
  )}
  </strong>
  </div>

  <div className="pay-attempt-meta">
  <span>
  {payment.method} · {payment.provider}
  </span>
  {payment.provider_reference && (
  <code>
  {payment.provider_reference}
 </code>
 )}
 </div>

 {payment.paid_at && (
 <div className="pay-attempt-meta">
 Paid{" "}
 {new Date(payment.paid_at).toLocaleString()}
 </div>
 )}

 {payment.failure_reason && (
 <div className="pay-attempt-meta pay-panel-warn">
 {payment.failure_reason}
 </div>
 )}

 {payment.status === "PENDING" &&
 payment.request?.upi_uri && (
 <div className="pay-qr-wrap pay-qr-small">
 <QRCodeSVG
 className="pay-qr"
 value={payment.request.upi_uri}
 size={168}
 level="M"
 marginSize={2}
 title="UPI payment QR code"
 />
 <p className="pay-panel-note">
 Show this to the guest, or{" "}
 <a
 className="pay-upi-link"
 href={payment.request.upi_uri}
 >
 open it
 </a>
 .
 </p>
 </div>
 )}

 <div className="pay-attempt-actions">
 {payment.status === "PENDING" && (
 <button
 className="action-btn"
 disabled={payBusy}
 onClick={() =>
 runAdminAction(
 "Check payment",
 () =>
 verifyPayment(payment.payment_id),
 )
 }
 >
 Check payment
 </button>
 )}

{/* A TEST ACTION, and only rendered when
  the server reports that development
  simulation is enabled. It publishes an
  outcome on the development provider;
  it does not set the bill paid itself. */}
  {simEnabled && payment.status !== "SUCCESS" ? (
  <button
  className="action-btn dev-action"
  disabled={payBusy}
  onClick={() =>
  runAdminAction(
  "Simulate payment",
  () =>
  simulateDevelopmentPayment(
  payment.payment_id,
  "SUCCESS",
  )
  )
  }
  >
  Simulate verified payment (TEST)
  </button>
) : null}
  </div>
  </div>
  ))}
  </div>
  )}

  {selectedHeader.payment_status !== "paid" && (
 <div className="pay-attempt-actions">
 <button
 className="action-btn"
 disabled={payBusy}
 onClick={() =>
 runAdminAction("Payment request", () =>
 createPaymentRequest(selectedHeader.id),
 )
 }
 >
 Request payment / show QR
 </button>
</div>
  )}

  {payNotice && (
  <p className="pay-panel-note">{payNotice}</p>
  )}

  <p className="pay-panel-note">
  A bill is marked paid only when the payment provider
  confirms it. Displaying a QR, scanning it, and a
  guest saying they have paid all leave it UNPAID.
  </p>
  </>
  )}
  </div>
  </div>
  </div>
  </div>
 </div>
 )}
 );
}

export { PaymentsAndBills };
export default Orders;

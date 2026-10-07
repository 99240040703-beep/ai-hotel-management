import React, { useEffect, useState } from "react";

import {
 getActiveOrderHeaders,
 updateOrderHeaderStatus,
} from "./api";
import { formatMoney } from "./money";

const LIFECYCLE_STAGES = [
 { key: "Placed", label: "Placed", icon: "", action: "Confirm", next: "Confirmed" },
 { key: "Confirmed", label: "Confirmed", icon: "", action: "Start Prep", next: "Preparing" },
 { key: "Preparing", label: "Preparing", icon: "", action: "Mark Ready", next: "Ready" },
 { key: "Ready", label: "Ready", icon: "", action: "Mark Served", next: "Served" },
];

function Kitchen() {
 const [orderHeaders, setOrderHeaders] = useState([]);
 const [loading, setLoading] = useState(true);
 const [error, setError] = useState("");
 const [autoRefresh, setAutoRefresh] = useState(true);

 useEffect(() => {
 loadKitchenOrders();
 }, []);

 // Auto-refresh every 10 seconds when enabled
 useEffect(() => {
 if (!autoRefresh) return;
 const interval = setInterval(loadKitchenOrders, 10000);
 return () =>clearInterval(interval);
 }, [autoRefresh]);

 const loadKitchenOrders = async () => {
 try {
 setError("");
 const data = await getActiveOrderHeaders();
 setOrderHeaders(data);
 } catch (err) {
 console.error(err);
 setError("Failed to load kitchen orders.");
 } finally {
 setLoading(false);
 }
 };

 const handleStatusTransition = async (headerId, currentStatus, nextStatus) => {
 try {
 await updateOrderHeaderStatus(headerId, nextStatus);
 await loadKitchenOrders();
 } catch (err) {
 console.error(err);
 setError(`Failed to update order: ${err.response?.data?.detail || err.message}`);
 }
 };

 const getStageIndex = (status) => {
 return LIFECYCLE_STAGES.findIndex(s =>s.key === status);
 };

 const getOrdersForStage = (stageKey) => {
 return orderHeaders.filter(h =>h.status === stageKey);
 };

 if (loading) {
 return (
 <div className="page-container">
 <div className="page-header">
 <div>
 <h1>Kitchen Display System</h1>
 <p>Monitor and manage kitchen orders</p>
 </div>
 </div>
 <p>Loading kitchen orders...</p>
 </div>
 );
 }

 return (
 <div className="page-container kitchen-page">
 <div className="page-header">
 <div>
 <h1>Kitchen Display System</h1>
 <p>Monitor and manage kitchen orders</p>
 </div>
 <div style={{display: 'flex', gap: '12px', alignItems: 'center'}}>
 <label style={{display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer'}}>
 <input
 type="checkbox"
 checked={autoRefresh}
 onChange={(e) =>setAutoRefresh(e.target.checked)}
 />
 <span>Auto-refresh (10s)</span>
 </label>
 <button className="secondary-btn"onClick={loadKitchenOrders}>
 Refresh Now
 </button>
 </div>
 </div>

 {error && (
 <div className="error-message"style={{marginBottom: '16px'}}>
 {error}
 </div>
 )}

 {/* Kitchen Workflow Columns */}
 <div className="kitchen-workflow">
 {LIFECYCLE_STAGES.map((stage) => {
 const orders = getOrdersForStage(stage.key);
 const isLastStage = stage.key === "Served";

 return (
 <div key={stage.key} className={`kitchen-column ${stage.key.toLowerCase()}`}>
 <div className="kitchen-column-header">
 <div className="column-title">
 <span className="column-icon">{stage.icon}</span>
 <h2>{stage.label}</h2>
 <span className="order-count">{orders.length}</span>
 </div>
 </div>

 <div className="kitchen-orders-list">
 {orders.length === 0 ? (
 <div className="empty-column">
 <span className="empty-icon">{stage.icon}</span>
 <p>No orders</p>
 </div>
 ) : (
 orders.map((header) => (
 <div key={header.id} className="kitchen-order-card">
 <div className="order-card-header">
 <div className="order-ref">
 <strong>{header.reference}</strong>
 {header.table_number && (
 <span className="table-badge">Table {header.table_number}</span>
 )}
 </div>
 <div className="order-time">
 {header.placed_at && new Date(header.placed_at).toLocaleTimeString()}
 </div>
 </div>

 <div className="order-items">
 {header.items && header.items.map((item, idx) => (
 <div key={idx} className="order-item-line">
 <span className="item-name">{item.menu_item}</span>
 <span className="item-qty">× {item.quantity}</span>
 {item.special_instructions && (
 <span className="item-notes"> {item.special_instructions}</span>
 )}
 </div>
 ))}
 </div>

 <div className="order-footer">
 <div className="order-total">
 {formatMoney(header.total_amount, header.currency)}
 </div>
 {!isLastStage && (
 <button
 className="kitchen-action-btn"
 onClick={() =>handleStatusTransition(header.id, stage.key, stage.next)}
 >
 {stage.action}
 </button>
 )}
 {isLastStage && (
 <span className="served-badge">Served</span>
 )}
 </div>
 </div>
 ))
 )}
 </div>
 </div>
 );
 })}
 </div>

 {/* All Orders Table View - Collapsible */}
 <details className="all-orders-table">
 <summary>
 <h3>All Active Orders (Table View)</h3>
 </summary>
 {orderHeaders.length === 0 ? (
 <p className="empty-note">No active orders</p>
 ) : (
 <div className="table-responsive">
 <table>
 <thead>
 <tr>
 <th>Reference</th>
 <th>Table</th>
 <th>Items</th>
 <th>Total</th>
 <th>Status</th>
 <th>Placed</th>
 <th>Actions</th>
 </tr>
 </thead>
 <tbody>
 {orderHeaders.map((header) => {
 const currentStageIndex = getStageIndex(header.status);
 const nextStage = currentStageIndex >= 0 && currentStageIndex < LIFECYCLE_STAGES.length - 1
 ? LIFECYCLE_STAGES[currentStageIndex + 1]
 : null;

 return (
 <tr key={header.id}>
 <td><strong>{header.reference}</strong></td>
 <td>{header.table_number ? `Table ${header.table_number}` : header.order_type}</td>
 <td>
 {header.items && header.items.map((item, idx) => (
 <div key={idx} className="table-item">
 {item.menu_item} × {item.quantity}
 {item.special_instructions && <span className="notes"> ({item.special_instructions})</span>}
 </div>
 ))}
 </td>
 <td>{formatMoney(header.total_amount, header.currency)}</td>
 <td>
 <span className={`status-pill ${header.status.toLowerCase()}`}>
 {header.status}
 </span>
 </td>
 <td>{header.placed_at ? new Date(header.placed_at).toLocaleTimeString() : '-'}</td>
 <td>
 {nextStage && (
 <button
 className="kitchen-action-btn small"
 onClick={() =>handleStatusTransition(header.id, header.status, nextStage.key)}
 >
 {nextStage.action}
 </button>
 )}
 {header.status === "Served" && (
 <span className="served-badge">Served</span>
 )}
 </td>
 </tr>
 );
 })}
 </tbody>
 </table>
 </div>
 )}
 </details>
 </div>
 );
}

export default Kitchen;
import { useEffect, useMemo, useState } from "react";

import { QRCodeSVG } from "qrcode.react";

import {
 createTable,
 deleteTable,
 getQrBaseUrl,
 getTables,
 regenerateTableQr,
 updateTable,
} from "./api";

const BLANK_FORM = {
 table_number: "",
 table_name: "",
 capacity: 4,
 section: "",
 is_active: true,
};

function Tables() {
 const [tables, setTables] = useState([]);
 const [qrBaseUrl, setQrBaseUrl] = useState("");
 const [loading, setLoading] = useState(true);
 const [error, setError] = useState("");
 const [notice, setNotice] = useState("");

 const [form, setForm] = useState(BLANK_FORM);
 const [editingId, setEditingId] = useState(null);
 const [saving, setSaving] = useState(false);

 // Which table's QR is on screen, if any.
 const [qrTableId, setQrTableId] = useState(null);

 const load = async () => {
 try {
 setLoading(true);
 setError("");

 const [rows, base] = await Promise.all([
 getTables(),
 getQrBaseUrl().catch(() => ({ entry_base_url: "" })),
 ]);

 setTables(rows);
 setQrBaseUrl(base.entry_base_url || "");
 } catch (err) {
 console.error(err);
 setError("Could not load tables.");
 } finally {
 setLoading(false);
 }
 };

 useEffect(() => {
 load();
 }, []);

 const qrPayload = useMemo(
 () => (table) =>
 `${qrBaseUrl}/customer/entry?table=${table.qr_token}`,
 [qrBaseUrl]
 );

 const handleChange = (event) => {
 const { name, value, type, checked } = event.target;

 setForm((previous) => ({
 ...previous,
 [name]:
 type === "checkbox"
 ? checked
 : name === "capacity" || name === "table_number"
 ? value === "" ? "" : Number(value)
 : value,
 }));
 };

 const startEdit = (table) => {
 setEditingId(table.id);
 setQrTableId(null);
 setNotice("");
 setForm({
 table_number: table.table_number,
 table_name: table.table_name || "",
 capacity: table.capacity,
 section: table.section || "",
 is_active: Boolean(table.is_active),
 });
 };

 const resetForm = () => {
 setEditingId(null);
 setForm(BLANK_FORM);
 };

 const handleSubmit = async (event) => {
 event.preventDefault();

 try {
 setSaving(true);
 setError("");

 if (editingId) {
 await updateTable(editingId, form);
 setNotice(`Table ${form.table_number} updated.`);
 } else {
 await createTable({
 table_number: Number(form.table_number),
 table_name: form.table_name || null,
 capacity: Number(form.capacity) || 4,
 section: form.section || null,
 is_active: form.is_active,
 });
 setNotice(`Table ${form.table_number} created with a new QR code.`);
 }

 resetForm();
 await load();
 } catch (err) {
 setError(
 err.response?.data?.detail || "Could not save the table."
 );
 } finally {
 setSaving(false);
 }
 };

 const toggleActive = async (table) => {
 try {
 await updateTable(table.id, { is_active: !table.is_active });
 await load();
 setNotice(
 `Table ${table.table_number} ${
 table.is_active ? "deactivated" : "activated"
 }.`
 );
 } catch (err) {
 setError(err.response?.data?.detail || "Could not update the table.");
 }
 };

 const regenerate = async (table) => {
 const confirmed = window.confirm(
 `Issue a new QR code for Table ${table.table_number}?\n\n` +
 "The printed code for this table stops working immediately. " +
 "Every other table is unaffected."
 );

 if (!confirmed) return;

 try {
 await regenerateTableQr(table.id);
 await load();
 setNotice(
 `New QR issued for Table ${table.table_number}. Reprint it.`
 );
 } catch (err) {
 setError(err.response?.data?.detail || "Could not regenerate the QR.");
 }
 };

 const remove = async (table) => {
 const confirmed = window.confirm(
 `Delete Table ${table.table_number}?\n\n` +
 "Existing orders keep their stored table number. " +
 "Deactivating is usually the better choice."
 );

 if (!confirmed) return;

 try {
 await deleteTable(table.id);
 await load();
 setNotice(`Table ${table.table_number} deleted.`);
 } catch (err) {
 setError(err.response?.data?.detail || "Could not delete the table.");
 }
 };

 const downloadQr = (table) => {
 // Render the SVG to a canvas so the guest-facing artefact can be
 // saved for printing rather than only viewed on screen.
 const svg = document.getElementById(`qr-svg-${table.id}`);
 if (!svg) return;

 const xml = new XMLSerializer().serializeToString(svg);
 const svgBlob = new Blob([xml], {
 type: "image/svg+xml;charset=utf-8",
 });
 const url = URL.createObjectURL(svgBlob);

 const image = new Image();
 image.onload = () => {
 const canvas = document.createElement("canvas");

 canvas.width = 512;
 canvas.height = 512;

 const context = canvas.getContext("2d");
 context.fillStyle = "#ffffff";
 context.fillRect(0, 0, canvas.width, canvas.height);
 context.drawImage(
 image,
 0,
 0,
 canvas.width,
 canvas.height
 );

 const link = document.createElement("a");
 link.download = `table-${table.table_number}-qr.png`;
 link.href = canvas.toDataURL("image/png");
 link.click();

 URL.revokeObjectURL(url);
 };
 image.src = url;
 };

 const printQr = (table) => {
 const svg = document.getElementById(`qr-svg-${table.id}`);
 if (!svg) return;

 const payload = qrPayload(table);
 const win = window.open("", "_blank", "width=520,height=680");

 if (!win) {
 setError(
 "The print window was blocked. Allow pop-ups to print a QR.",
 );
 return;
 }

 // A dedicated print document: the SVG is inlined so it renders
 // without a network request.
 const svgMarkup = new XMLSerializer().serializeToString(svg);

 win.document.write(`
 <!doctype html>
 <html>
 <head>
 <title>Table ${table.table_number} QR</title>
 <style>
 body {
 font-family: system-ui, sans-serif;
 text-align: center;
 padding: 24px;
 }
 h1 { margin: 0 0 4px; font-size: 28px; }
 p.sub { margin: 0 0 20px; color: #555; }
 .frame {
 display: inline-block;
 padding: 20px;
 border: 3px solid #111;
 border-radius: 16px;
 }
 .url {
 margin-top: 16px;
 font-family: ui-monospace, monospace;
 font-size: 12px;
 word-break: break-all;
 color: #444;
 }
 @media print {
 button { display: none; }
 }
 </style>
 </head>
 <body>
 <h1>${restaurantLabel()}</h1>
 <p class="sub">Table ${table.table_number}${
 table.section ? ` · ${table.section}` : ""
 }</p>
 <div class="frame">${svgMarkup}</div>
 <div class="url">${payload}</div>
 <p><button onclick="window.print()">Print</button></p>
 </body>
 </html>
 `);
 win.document.close();
 };

 const restaurantLabel = () => "Paradise Restaurant";

 const showQrFor = tables.find((row) =>row.id === qrTableId);

 return (
 <div className="page">
 <div className="page-header">
 <h2>Tables &amp; QR Codes</h2>
 <p className="section-desc">
 Each table gets its own printed QR. Scanning it sends the guest
 to the customer entry page with that table attached. Only the
 table's random token is encoded - never a customer id, a
 password or a session token.
 </p>
 </div>

 {error && <div className="error-message">{error}</div>}
 {notice && <div className="auth-success">{notice}</div>}

 {qrBaseUrl && (
 <p className="form-hint">
 Printed QR points at <code>{qrBaseUrl}/customer/entry</code>
 </p>
 )}

 {/* ---------------- QR preview ---------------- */}

 {showQrFor && (
 <div className="qr-preview-card">
 <div>
 <h3>
 {restaurantLabel()} · Table{" "}
 {showQrFor.table_number}
 </h3>

 <p className="qr-url">{qrPayload(showQrFor)}</p>

 <div className="qr-actions">
 <button
 className="secondary-btn"
 onClick={() =>downloadQr(showQrFor)}
 >
 Download PNG
 </button>

 <button
 className="primary-btn"
 onClick={() =>printQr(showQrFor)}
 >
 Print
 </button>

 <button
 className="secondary-btn"
 onClick={() =>setQrTableId(null)}
 >
 Close
 </button>
 </div>
 </div>

 {/* Kept mounted while the dialog is open so print/download can
 serialise it. */}
 <div className="qr-frame"id={`qr-host-${showQrFor.id}`}>
 <QRCodeSVG
 id={`qr-svg-${showQrFor.id}`}
 value={qrPayload(showQrFor)}
 size={220}
 level="M"
 marginSize={2}
 />
 </div>
 </div>
 )}

 {/* ---------------- add / edit ---------------- */}

 <div className="form-card">
 <h3>{editingId ? "Edit table" : "Add a table"}</h3>

 <form onSubmit={handleSubmit}>
 <div className="form-grid">
 <div className="form-group">
 <label>Table number</label>

 <input
 name="table_number"
 type="number"
 min="1"
 value={form.table_number}
 onChange={handleChange}
 required
 />
 </div>

 <div className="form-group">
 <label>Capacity (seats)</label>

 <input
 name="capacity"
 type="number"
 min="1"
 value={form.capacity}
 onChange={handleChange}
 required
 />
 </div>

 <div className="form-group">
 <label>Name (optional)</label>

 <input
 name="table_name"
 type="text"
 value={form.table_name}
 onChange={handleChange}
 placeholder="Window corner"
 />
 </div>

 <div className="form-group">
 <label>Section</label>

 <input
 name="section"
 type="text"
 value={form.section}
 onChange={handleChange}
 placeholder="Dining Room"
 />
 </div>
 </div>

 <label className="checkbox-row">
 <input
 name="is_active"
 type="checkbox"
 checked={form.is_active}
 onChange={handleChange}
 />
 Accepting orders
 </label>

 <div className="form-actions">
 <button
 type="submit"
 className="primary-btn"
 disabled={saving}
 >
 {saving
 ? "Saving..."
 : editingId
 ? "Save changes"
 : "Create table"}
 </button>

 {editingId && (
 <button
 type="button"
 className="secondary-btn"
 onClick={resetForm}
 >
 Cancel
 </button>
 )}
 </div>
 </form>
 </div>

 {/* ---------------- list ---------------- */}

 <div className="table-card">
 <h3>All tables ({tables.length})</h3>

 {loading ? (
 <p className="empty-note">Loading…</p>
 ) : tables.length === 0 ? (
 <p className="empty-note">
 No tables yet. Create the first one above, then print its QR.
 </p>
 ) : (
 <table>
 <thead>
 <tr>
 <th>Table</th>
 <th>Name</th>
 <th>Capacity</th>
 <th>Section</th>
 <th>Status</th>
 <th>Actions</th>
 </tr>
 </thead>

 <tbody>
 {tables.map((table) => (
 <tr key={table.id}>
 <td>
 <strong>Table {table.table_number}</strong>
 </td>

 <td>{table.table_name || "-"}</td>

 <td>{table.capacity}</td>

 <td>{table.section || "-"}</td>

 <td>
 {table.is_active ? (
 <span className="panel-tag success">Active</span>
 ) : (
 <span className="panel-tag danger">Inactive</span>
 )}
 </td>

 <td className="row-actions">
 <button
 className="secondary-btn"
 disabled={!table.qr_token}
 onClick={() => {
 setQrTableId(table.id);
 setNotice("");
 }}
 >
 {table.qr_token ? "View QR" : "No QR"}
 </button>

 <button
 className="secondary-btn"
 onClick={() =>regenerate(table)}
 >
 Regenerate QR
 </button>

 <button
 className="secondary-btn"
 onClick={() =>startEdit(table)}
 >
 Edit
 </button>

 <button
 className="secondary-btn"
 onClick={() =>toggleActive(table)}
 >
 {table.is_active ? "Deactivate" : "Activate"}
 </button>

 <button
 className="danger-btn"
 onClick={() =>remove(table)}
 >
 Delete
 </button>
 </td>
 </tr>
 ))}
 </tbody>
 </table>
 )}
 </div>
 </div>
 );
}

export default Tables;
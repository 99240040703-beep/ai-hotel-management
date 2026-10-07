import React, { useEffect, useState } from "react";

import {
 getReservations,
 getReservationSummary,
 createReservation,
 updateReservation,
 deleteReservation,
} from "./api";


function Reservations() {

 // =========================
 // STATE
 // =========================

 const [reservations, setReservations] = useState([]);

 const [summary, setSummary] = useState(null);

 const [showForm, setShowForm] = useState(false);

 const [editingId, setEditingId] = useState(null);

 const [loading, setLoading] = useState(true);

 const [error, setError] = useState("");


 const [form, setForm] = useState({
 customer_name: "",
 table_number: "",
 reservation_date: "",
 reservation_time: "",
 guests: 1,
 });


 // =========================
 // LOAD RESERVATIONS
 // =========================

 useEffect(() => {
 loadReservations();
 }, []);


 const loadReservations = async () => {

 try {

 setLoading(true);
 setError("");

 const data = await getReservations();

 setReservations(data);

 } catch (err) {

 console.error(err);

 setError("Failed to load reservations.");

 } finally {

 setLoading(false);

 }

 };


 // A booking made in the customer portal shows up here on its own,
 // so staff never have to refresh the page to see the table plan.
 useEffect(() => {

 const pullSummary = () => {

 getReservationSummary()
 .then(setSummary)
 .catch((err) =>console.error(err));

 };

 pullSummary();

 const timer = setInterval(pullSummary, 15000);

 return () =>clearInterval(timer);

 }, []);


 // =========================
 // FORM CHANGE
 // =========================

 const handleChange = (e) => {

 const { name, value } = e.target;

 setForm({
 ...form,
 [name]: value,
 });

 };


 // =========================
 // SUBMIT
 // =========================

 const handleSubmit = async (e) => {

 e.preventDefault();

 try {

 const reservationData = {

 customer_name:
 form.customer_name,

 table_number:
 Number(form.table_number),

 reservation_date:
 form.reservation_date,

 reservation_time:
 form.reservation_time,

 guests:
 Number(form.guests),

 };


 if (editingId) {

 await updateReservation(
 editingId,
 reservationData
 );

 alert(
 "Reservation updated successfully!"
 );

 } else {

 await createReservation(
 reservationData
 );

 alert(
 "Reservation created successfully!"
 );

 }


 resetForm();

 await loadReservations();

 } catch (err) {

 console.error(err);

 alert(
 "Failed to save reservation."
 );

 }

 };


 // =========================
 // EDIT
 // =========================

 const handleEdit = (reservation) => {

 setEditingId(reservation.id);

 setForm({

 customer_name:
 reservation.customer_name || "",

 table_number:
 reservation.table_number || "",

 reservation_date:
 reservation.reservation_date || "",

 reservation_time:
 reservation.reservation_time || "",

 guests:
 reservation.guests || 1,

 });

 setShowForm(true);

 };


 // =========================
 // DELETE
 // =========================

 const handleDelete = async (id) => {

 const confirmDelete =
 window.confirm(
 "Are you sure you want to delete this reservation?"
 );


 if (!confirmDelete) {
 return;
 }


 try {

 await deleteReservation(id);

 alert(
 "Reservation deleted successfully!"
 );

 await loadReservations();

 } catch (err) {

 console.error(err);

 alert(
 "Failed to delete reservation."
 );

 }

 };


 // =========================
 // RESET
 // =========================

 const resetForm = () => {

 setForm({

 customer_name: "",

 table_number: "",

 reservation_date: "",

 reservation_time: "",

 guests: 1,

 });

 setEditingId(null);

 setShowForm(false);

 };


 // =========================
 // OPEN ADD FORM
 // =========================

 const openAddReservation = () => {

 resetForm();

 setShowForm(true);

 };


 // =========================
 // UI
 // =========================

 return (

 <div
 style={{
 padding: "30px",
 }}
 >

 {/* =========================
 HEADER
 ========================= */}

 <div
 style={{
 display: "flex",
 justifyContent: "space-between",
 alignItems: "center",
 marginBottom: "25px",
 }}
 >

 <div>

 <h1>
 Reservation Management
 </h1>

 <p>
 Manage restaurant table reservations.
 </p>

 </div>


 <button
 onClick={openAddReservation}
 style={{
 padding: "12px 20px",
 border: "none",
 borderRadius: "8px",
 cursor: "pointer",
 fontWeight: "bold",
 }}
 >
 + Add Reservation
 </button>

 </div>


 {/* =========================
 SEATING BOARD
 ========================= */}

 {summary && (
 <div className="stats-grid"style={{ marginBottom: "25px" }}>
 <div className="stat-card">
 <h3>Tables Today</h3>
 <strong>
 {summary.today?.booked_tables?.length ?? 0} /{" "}
 {summary.total_tables}
 </strong>
 <small>
 {summary.today?.tables_free_count ?? summary.total_tables} free
 </small>
 </div>

 <div className="stat-card">
 <h3>Bookings Today</h3>
 <strong>{summary.today?.total_bookings ?? 0}</strong>
 <small>pending + booked</small>
 </div>

 <div className="stat-card">
 <h3>Guests Expected</h3>
 <strong>{summary.today?.total_guests ?? 0}</strong>
 <small>across all bookings</small>
 </div>

 <div className="stat-card">
 <h3>Upcoming</h3>
 <strong>{summary.total_upcoming_bookings}</strong>
 <small>{summary.total_upcoming_guests} guests</small>
 </div>
 </div>
 )}

 {summary && summary.upcoming.length > 0 && (
 <div className="table-card"style={{ marginBottom: "25px" }}>
 <h2>Table Plan</h2>

 <table>
 <thead>
 <tr>
 <th>Date</th>
 <th>Bookings</th>
 <th>Guests</th>
 <th>Tables Taken</th>
 <th>Tables Free</th>
 <th>Pending</th>
 </tr>
 </thead>

 <tbody>
 {summary.upcoming.map((day) => (
 <tr key={day.date}>
 <td>
 {day.date}
 {day.is_today && "(today)"}
 </td>
 <td>{day.total_bookings}</td>
 <td>{day.total_guests}</td>
 <td>
 {day.booked_tables.length > 0
 ? day.booked_tables.join(", ")
 : "-"}
 </td>
 <td>{day.tables_free_count}</td>
 <td>{day.by_status.Pending || 0}</td>
 </tr>
 ))}
 </tbody>
 </table>
 </div>
 )}

 {/* =========================
 FORM
 ========================= */}

 {showForm && (

 <div
 style={{
 padding: "25px",
 marginBottom: "25px",
 border: "1px solid #ddd",
 borderRadius: "12px",
 background: "#fff",
 }}
 >

 <h2>

 {editingId
 ? "Edit Reservation"
 : "Add New Reservation"}

 </h2>


 <form onSubmit={handleSubmit}>


 {/* CUSTOMER */}

 <div
 style={{
 marginBottom: "15px",
 }}
 >

 <label>
 Customer Name
 </label>


 <input
 type="text"
 name="customer_name"
 value={form.customer_name}
 onChange={handleChange}
 required

 style={{
 display: "block",
 width: "100%",
 padding: "10px",
 marginTop: "5px",
 boxSizing: "border-box",
 }}
 />

 </div>


 {/* TABLE */}

 <div
 style={{
 marginBottom: "15px",
 }}
 >

 <label>
 Table Number
 </label>


 <input
 type="number"
 name="table_number"
 value={form.table_number}
 onChange={handleChange}
 min="1"
 required

 style={{
 display: "block",
 width: "100%",
 padding: "10px",
 marginTop: "5px",
 boxSizing: "border-box",
 }}
 />

 </div>


 {/* DATE */}

 <div
 style={{
 marginBottom: "15px",
 }}
 >

 <label>
 Reservation Date
 </label>


 <input
 type="date"
 name="reservation_date"
 value={form.reservation_date}
 onChange={handleChange}
 required

 style={{
 display: "block",
 width: "100%",
 padding: "10px",
 marginTop: "5px",
 boxSizing: "border-box",
 }}
 />

 </div>


 {/* TIME */}

 <div
 style={{
 marginBottom: "15px",
 }}
 >

 <label>
 Reservation Time
 </label>


 <input
 type="time"
 name="reservation_time"
 value={form.reservation_time}
 onChange={handleChange}
 required

 style={{
 display: "block",
 width: "100%",
 padding: "10px",
 marginTop: "5px",
 boxSizing: "border-box",
 }}
 />

 </div>


 {/* GUESTS */}

 <div
 style={{
 marginBottom: "20px",
 }}
 >

 <label>
 Number of Guests
 </label>


 <input
 type="number"
 name="guests"
 value={form.guests}
 onChange={handleChange}
 min="1"
 required

 style={{
 display: "block",
 width: "100%",
 padding: "10px",
 marginTop: "5px",
 boxSizing: "border-box",
 }}
 />

 </div>


 {/* BUTTONS */}

 <button
 type="submit"
 style={{
 padding: "10px 18px",
 marginRight: "10px",
 cursor: "pointer",
 }}
 >

 {editingId
 ? "Update Reservation"
 : "Save Reservation"}

 </button>


 <button
 type="button"
 onClick={resetForm}
 style={{
 padding: "10px 18px",
 cursor: "pointer",
 }}
 >
 Cancel
 </button>


 </form>

 </div>

 )}


 {/* ERROR */}

 {error && (

 <p
 style={{
 color: "red",
 }}
 >
 {error}
 </p>

 )}


 {/* LOADING */}

 {loading && (
 <p>
 Loading reservations...
 </p>
 )}


 {/* TABLE */}

 {!loading && !error && (

 reservations.length === 0 ? (

 <div
 style={{
 padding: "30px",
 border: "1px solid #ddd",
 borderRadius: "10px",
 textAlign: "center",
 }}
 >

 <h2>
 No Reservations Yet
 </h2>

 <p>
 Click{" "}
 <b>+ Add Reservation</b>{" "}
 to create your first reservation.
 </p>

 </div>

 ) : (

 <table
 style={{
 width: "100%",
 borderCollapse: "collapse",
 }}
 >

 <thead>

 <tr>

 <th>ID</th>

 <th>
 Customer Name
 </th>

 <th>
 Table
 </th>

 <th>
 Date
 </th>

 <th>
 Time
 </th>

 <th>
 Guests
 </th>

 <th>
 Actions
 </th>

 </tr>

 </thead>


 <tbody>

 {reservations.map(
 (reservation, index) => (

 <tr
 key={reservation.id}
 >

 <td>
 #{index + 1}
 </td>

 <td>
 {reservation.customer_name}
 </td>

 <td>
 Table{" "}
 {reservation.table_number}
 </td>

 <td>
 {reservation.reservation_date}
 </td>

 <td>
 {reservation.reservation_time}
 </td>

 <td>
 {reservation.guests}
 </td>

 <td>

 <button
 onClick={() =>
 handleEdit(
 reservation
 )
 }
 style={{
 marginRight: "8px",
 cursor: "pointer",
 }}
 >
 Edit
 </button>


 <button
 onClick={() =>
 handleDelete(
 reservation.id
 )
 }
 style={{
 cursor: "pointer",
 }}
 >
 Delete
 </button>

 </td>

 </tr>

 )
 )}

 </tbody>

 </table>

 )

 )}

 </div>

 );

}


export default Reservations;
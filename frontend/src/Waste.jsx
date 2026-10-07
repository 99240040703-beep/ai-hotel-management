import { useEffect, useState } from "react";

import {
  getWaste,
  getWasteAnalysis,
  createWaste,
  deleteWaste,
  getEndOfDayReport,
  closeDay,
} from "./api";
import { formatMoney } from "./money";

function Waste() {
  const [wasteRecords, setWasteRecords] = useState([]);
  const [analysis, setAnalysis] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // End-of-day closing: prepared vs sold per dish, leftover ->waste
  const [closing, setClosing] = useState(null);
  const [prepared, setPrepared] = useState({});
  const [closingResult, setClosingResult] = useState("");
  const [closingBusy, setClosingBusy] = useState(false);

  const [form, setForm] = useState({
    item_name: "",
    quantity: 0,
    unit: "kg",
    reason: "",
    cost: 0,
  });

  const loadWaste = async () => {
    try {
      setLoading(true);
      const [records, wasteAnalysis] = await Promise.all([
        getWaste(),
        getWasteAnalysis(),
      ]);
      setWasteRecords(records);
      setAnalysis(wasteAnalysis);
    } catch (err) {
      console.error(err);
      setError("Failed to load waste data.");
    } finally {
      setLoading(false);
    }
  };

  const loadClosing = async () => {
    try {
      const report = await getEndOfDayReport();
      setClosing(report);

      // Default the prepared box to whatever was actually sold today.
      const seeded = {};

      report.dishes.forEach((dish) => {
        seeded[dish.item_name] = String(dish.sold_quantity || 0);
      });

      setPrepared(seeded);
    } catch (err) {
      console.error(err);
    }
  };

  useEffect(() => {
    loadWaste();
    loadClosing();
  }, []);

  const handlePreparedChange = (itemName, value) => {
    setPrepared((previous) => ({ ...previous, [itemName]: value }));
  };

  const handleCloseDay = async (event) => {
    event.preventDefault();

    try {
      setClosingBusy(true);
      setClosingResult("");

      const payload = Object.entries(prepared).map(
        ([item_name, quantity]) => ({
          item_name,
          quantity: Number(quantity) || 0,
        })
      );

      const result = await closeDay(closing.date, payload);

      setClosingResult(
        `${result.message} ${
          result.total_leftover
            ? `Leftover ${result.total_leftover} portion(s), ${formatMoney(result.total_cost)}.`
            : ""
        }`
      );

      await Promise.all([loadWaste(), loadClosing()]);
    } catch (err) {
      console.error(err);
      setError("Failed to close the day.");
    } finally {
      setClosingBusy(false);
    }
  };

  const handleChange = (e) => {
    setForm({
      ...form,
      [e.target.name]: e.target.value,
    });
  };

  const handleSubmit = async (e) => {
    e.preventDefault();

    try {
      await createWaste({
        ...form,
        quantity: Number(form.quantity),
        cost: Number(form.cost),
      });

      setForm({
        item_name: "",
        quantity: 0,
        unit: "kg",
        reason: "",
        cost: 0,
      });

      await loadWaste();
    } catch (err) {
      console.error(err);
      setError("Failed to save waste record.");
    }
  };

  const handleDelete = async (id) => {
    try {
      await deleteWaste(id);
      await loadWaste();
    } catch (err) {
      console.error(err);
      setError("Failed to delete waste record.");
    }
  };

  return (
    <div className="page-container">
      <div className="page-header">
        <div>
          <h1>Food Waste</h1>
          <p>Track wastage, reasons, and cost impact</p>
        </div>
      </div>

      {error && <div className="error-message">{error}</div>}

      {/* =========================================================
          END OF DAY CLOSING
          Prepared quantity minus what was sold becomes today's waste.
      ========================================================= */}

      {closing && (
        <div className="form-card">
          <h2>End of Day Closing</h2>
          <p className="section-desc">
            Inventory is turned into dishes during service. Enter what the
            kitchen actually prepared for {closing.date} - anything left over
            after the sold quantity is recorded as waste.
          </p>

          <form onSubmit={handleCloseDay}>
            <table>
              <thead>
                <tr>
                  <th>Dish</th>
                  <th>Sold Today</th>
                  <th>Prepared</th>
                  <th>Leftover</th>
                  <th>In Stock</th>
                </tr>
              </thead>

              <tbody>
                {closing.dishes.map((dish) => {
                  const preparedQty = Number(prepared[dish.item_name]) || 0;
                  const leftover = Math.max(
                    0,
                    preparedQty - (dish.sold_quantity || 0)
                  );

                  return (
                    <tr key={dish.item_name}>
                      <td>{dish.item_name}</td>
                      <td>{dish.sold_quantity || 0}</td>
                      <td>
                        <input
                          type="number"
                          min="0"
                          step="1"
                          value={prepared[dish.item_name] ?? "0"}
                          onChange={(event) =>
                            handlePreparedChange(
                              dish.item_name,
                              event.target.value
                            )
                          }
                          style={{ width: "90px" }}
                        />
                      </td>
                      <td>
                        <strong>{leftover}</strong>
                      </td>
                      <td>
                        {dish.inventory_quantity === null
                          ? "-"
                          : `${dish.inventory_quantity} ${
                              dish.inventory_unit || ""
                            }`}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>

            <div className="form-actions">
              <button
                type="submit"
                className="primary-btn"
                disabled={closingBusy}
              >
                {closingBusy ? "Closing day..." : "Close Day & Record Waste"}
              </button>
            </div>

            {closingResult && <p className="auth-error">{closingResult}</p>}
          </form>
        </div>
      )}

      {closing && closing.inventory.length > 0 && (
        <div className="table-card">
          <h2>Inventory Snapshot</h2>

          <table>
            <thead>
              <tr>
                <th>Item</th>
                <th>Category</th>
                <th>Quantity</th>
                <th>Min Stock</th>
                <th>Cost / Unit</th>
              </tr>
            </thead>

            <tbody>
              {closing.inventory.map((row) => (
                <tr key={row.item_name}>
                  <td>{row.item_name}</td>
                  <td>{row.category || "-"}</td>
                  <td>
                    {row.quantity} {row.unit || ""}
                    {row.is_low && (
                      <span className="panel-tag danger">low</span>
                    )}
                  </td>
                  <td>{row.minimum_stock}</td>
                  <td>{formatMoney(row.cost_per_unit || 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {analysis && (
        <div className="stats-grid">
          <div className="stat-card">
            <h3>Total Waste Qty</h3>
            <strong>
              {Number(analysis.total_waste_quantity || 0).toFixed(1)}
            </strong>
          </div>
          <div className="stat-card">
            <h3>Waste Cost</h3>
            <strong>
              {formatMoney(analysis.total_waste_cost || 0)}
            </strong>
          </div>
          <div className="stat-card">
            <h3>Next Week</h3>
            <strong>
              {Number(analysis.predicted_next_week_quantity || 0).toFixed(1)}
            </strong>
          </div>
        </div>
      )}

      <div className="form-card">
        <h2>Add Waste Record</h2>
        <form onSubmit={handleSubmit} className="form-grid">
          <input
            type="text"
            name="item_name"
            value={form.item_name}
            onChange={handleChange}
            placeholder="Item name"
            required
          />
          <input
            type="number"
            name="quantity"
            value={form.quantity}
            onChange={handleChange}
            placeholder="Quantity"
            step="0.1"
            required
          />
          <input
            type="text"
            name="unit"
            value={form.unit}
            onChange={handleChange}
            placeholder="Unit"
          />
          <input
            type="text"
            name="reason"
            value={form.reason}
            onChange={handleChange}
            placeholder="Reason"
          />
          <input
            type="number"
            name="cost"
            value={form.cost}
            onChange={handleChange}
            placeholder="Cost"
            step="0.01"
          />
          <div className="form-actions">
            <button type="submit"className="primary-btn">
              Add Waste
            </button>
          </div>
        </form>
      </div>

      <div className="table-card">
        <h2>Waste Records</h2>
        {loading ? (
          <p>Loading waste records...</p>
        ) : wasteRecords.length === 0 ? (
          <p>No waste records found.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Item</th>
                <th>Quantity</th>
                <th>Reason</th>
                <th>Cost</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {wasteRecords.map((record) => (
                <tr key={record.id}>
                  <td>{record.item_name}</td>
                  <td>
                    {record.quantity} {record.unit || "kg"}
                  </td>
                  <td>{record.reason || "-"}</td>
                  <td>{formatMoney(record.cost || 0)}</td>
                  <td>
                    <button
                      type="button"
                      className="secondary-btn"
                      onClick={() =>handleDelete(record.id)}
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

export default Waste;

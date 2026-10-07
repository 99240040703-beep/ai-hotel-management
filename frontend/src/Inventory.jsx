import React, { useEffect, useState } from "react";

import {
  getInventory,
  getLowStock,
  createInventory,
  updateInventory,
  deleteInventory,
} from "./api";
import { formatMoney } from "./money";

function Inventory() {
  const [inventory, setInventory] = useState([]);
  const [lowStock, setLowStock] = useState([]);

  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState(null);

  const [form, setForm] = useState({
    item_name: "",
    category: "",
    quantity: 0,
    unit: "",
    minimum_stock: 0,
    supplier: "",
    cost_per_unit: 0,
  });

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    loadInventory();
  }, []);

  const loadInventory = async () => {
    try {
      setLoading(true);
      setError("");

      const data = await getInventory();
      const low = await getLowStock();

      setInventory(data);
      setLowStock(low);
    } catch (err) {
      console.error(err);
      setError("Failed to load inventory.");
    } finally {
      setLoading(false);
    }
  };

  const handleChange = (e) => {
    const { name, value } = e.target;

    setForm({
      ...form,
      [name]: value,
    });
  };

  const handleSubmit = async (e) => {
    e.preventDefault();

    try {
      setError("");

      const item = {
        item_name: form.item_name,
        category: form.category || null,
        quantity: Number(form.quantity),
        unit: form.unit || null,
        minimum_stock: Number(form.minimum_stock),
        supplier: form.supplier || null,
        cost_per_unit: Number(form.cost_per_unit),
      };

      if (editingId) {
        await updateInventory(editingId, item);
      } else {
        await createInventory(item);
      }

      resetForm();
      await loadInventory();
    } catch (err) {
      console.error(err);
      setError("Failed to save inventory item.");
    }
  };

  const handleEdit = (item) => {
    setEditingId(item.id);

    setForm({
      item_name: item.item_name || "",
      category: item.category || "",
      quantity: item.quantity || 0,
      unit: item.unit || "",
      minimum_stock: item.minimum_stock || 0,
      supplier: item.supplier || "",
      cost_per_unit: item.cost_per_unit || 0,
    });

    setShowForm(true);
  };

  const handleDelete = async (id) => {
    const confirmed = window.confirm(
      "Are you sure you want to delete this inventory item?"
    );

    if (!confirmed) return;

    try {
      setError("");

      await deleteInventory(id);
      await loadInventory();
    } catch (err) {
      console.error(err);
      setError("Failed to delete inventory item.");
    }
  };

  const resetForm = () => {
    setForm({
      item_name: "",
      category: "",
      quantity: 0,
      unit: "",
      minimum_stock: 0,
      supplier: "",
      cost_per_unit: 0,
    });

    setEditingId(null);
    setShowForm(false);
  };

  const totalStockValue = inventory.reduce(
    (total, item) =>
      total +
      Number(item.quantity || 0) *
        Number(item.cost_per_unit || 0),
    0
  );

  return (
    <div className="page-container">

      {/* HEADER */}
      <div className="page-header">

        <div>
          <h1>Inventory</h1>

          <p>
            Manage restaurant stock and supplies
          </p>
        </div>

        <button
          className="primary-btn"
          onClick={() => {
            resetForm();
            setShowForm(true);
          }}
        >
          + Add Inventory
        </button>

      </div>

      {/* ERROR */}
      {error && (
        <div className="error-message">
          {error}
        </div>
      )}

      {/* STATISTICS */}
      <div className="stats-grid">

        <div className="stat-card">
          <h3>Total Items</h3>

          <strong>
            {inventory.length}
          </strong>
        </div>

        <div className="stat-card">
          <h3>Low Stock</h3>

          <strong>
            {lowStock.length}
          </strong>
        </div>

        <div className="stat-card">
          <h3>Stock Value</h3>

          <strong>
            {formatMoney(totalStockValue)}
          </strong>
        </div>

      </div>

      {/* FORM */}
      {showForm && (
        <div className="form-card">

          <h2>
            {editingId
              ? "Edit Inventory Item"
              : "Add Inventory Item"}
          </h2>

          <form onSubmit={handleSubmit}>

            <div className="form-grid">

              {/* ITEM NAME */}
              <div className="form-group">

                <label>
                  Item Name
                </label>

                <input
                  type="text"
                  name="item_name"
                  value={form.item_name}
                  onChange={handleChange}
                  placeholder="Example: Rice"
                  required
                />

              </div>

              {/* CATEGORY */}
              <div className="form-group">

                <label>
                  Category
                </label>

                <input
                  type="text"
                  name="category"
                  value={form.category}
                  onChange={handleChange}
                  placeholder="Example: Grains"
                />

              </div>

              {/* QUANTITY */}
              <div className="form-group">

                <label>
                  Quantity
                </label>

                <input
                  type="number"
                  step="0.01"
                  name="quantity"
                  value={form.quantity}
                  onChange={handleChange}
                  required
                />

              </div>

              {/* UNIT */}
              <div className="form-group">

                <label>
                  Unit
                </label>

                <input
                  type="text"
                  name="unit"
                  value={form.unit}
                  onChange={handleChange}
                  placeholder="kg / litre / pieces"
                />

              </div>

              {/* MINIMUM STOCK */}
              <div className="form-group">

                <label>
                  Minimum Stock
                </label>

                <input
                  type="number"
                  step="0.01"
                  name="minimum_stock"
                  value={form.minimum_stock}
                  onChange={handleChange}
                />

              </div>

              {/* SUPPLIER */}
              <div className="form-group">

                <label>
                  Supplier
                </label>

                <input
                  type="text"
                  name="supplier"
                  value={form.supplier}
                  onChange={handleChange}
                  placeholder="Supplier name"
                />

              </div>

              {/* COST */}
              <div className="form-group">

                <label>
                  Cost Per Unit
                </label>

                <input
                  type="number"
                  step="0.01"
                  name="cost_per_unit"
                  value={form.cost_per_unit}
                  onChange={handleChange}
                  required
                />

              </div>

            </div>

            <div className="form-actions">

              <button
                type="submit"
                className="primary-btn"
              >
                {editingId
                  ? "Update Item"
                  : "Add Item"}
              </button>

              <button
                type="button"
                className="secondary-btn"
                onClick={resetForm}
              >
                Cancel
              </button>

            </div>

          </form>

        </div>
      )}

      {/* INVENTORY TABLE */}
      <div className="table-card">

        <h2>
          Inventory Items
        </h2>

        {loading ? (
          <p>
            Loading inventory...
          </p>
        ) : inventory.length === 0 ? (
          <div className="empty-state">

            <h3>
              No Inventory Items
            </h3>

            <p>
              Add your first inventory item.
            </p>

          </div>
        ) : (

          <table>

            <thead>

              <tr>
                <th>ID</th>
                <th>Item</th>
                <th>Category</th>
                <th>Quantity</th>
                <th>Unit</th>
                <th>Minimum Stock</th>
                <th>Supplier</th>
                <th>Cost / Unit</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>

            </thead>

            <tbody>

              {inventory.map(
                (item, index) => {

                  const isLow =
                    Number(item.quantity) <=
                    Number(item.minimum_stock);

                  return (
                    <tr key={item.id}>

                      <td>
                        {index + 1}
                      </td>

                      <td>
                        {item.item_name}
                      </td>

                      <td>
                        {item.category || "-"}
                      </td>

                      <td>
                        {item.quantity}
                      </td>

                      <td>
                        {item.unit || "-"}
                      </td>

                      <td>
                        {item.minimum_stock}
                      </td>

                      <td>
                        {item.supplier || "-"}
                      </td>

<td>
                          {formatMoney(
                            item.cost_per_unit || 0
                          )}
                        </td>

                      <td>

                        <span
                          className={
                            isLow
                              ? "status-danger"
                              : "status-success"
                          }
                        >
                          {isLow
                            ? "Low Stock"
                            : "In Stock"}
                        </span>

                      </td>

                      <td>

                        <button
                          className="edit-btn"
                          onClick={() =>
                            handleEdit(item)
                          }
                        >
                          Edit
                        </button>

                        <button
                          className="delete-btn"
                          onClick={() =>
                            handleDelete(
                              item.id
                            )
                          }
                        >
                          Delete
                        </button>

                      </td>

                    </tr>
                  );
                }
              )}

            </tbody>

          </table>

        )}

      </div>

    </div>
  );
}

export default Inventory;
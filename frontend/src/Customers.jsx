import { useEffect, useState } from "react";

import {
  getCustomers,
  createCustomer,
  updateCustomer,
  deleteCustomer,
} from "./api";
import { formatMoney } from "./money";

function Customers() {
  const [customers, setCustomers] = useState([]);

  const [form, setForm] = useState({
    name: "",
    email: "",
    phone: "",
    address: "",
  });

  const [editingId, setEditingId] = useState(null);
  const [loading, setLoading] = useState(false);

  // =========================
  // LOAD CUSTOMERS
  // =========================

  const loadCustomers = async () => {
    try {
      setLoading(true);

      const data = await getCustomers();

      setCustomers(data);
    } catch (error) {
      console.error("Error loading customers:", error);
      alert("Failed to load customers");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadCustomers();
  }, []);

  // =========================
  // FORM CHANGE
  // =========================

  const handleChange = (e) => {
    setForm({
      ...form,
      [e.target.name]: e.target.value,
    });
  };

  // =========================
  // ADD / UPDATE
  // =========================

  const handleSubmit = async (e) => {
    e.preventDefault();

    if (!form.name || !form.email || !form.phone) {
      alert("Please fill Name, Email and Phone");
      return;
    }

    try {
      if (editingId) {
        await updateCustomer(editingId, {
          ...form,
          total_orders:
            customers.find((c) =>c.id === editingId)?.total_orders || 0,
          total_spent:
            customers.find((c) =>c.id === editingId)?.total_spent || 0,
        });

        alert("Customer updated successfully");
      } else {
        await createCustomer({
          ...form,
          total_orders: 0,
          total_spent: 0,
        });

        alert("Customer added successfully");
      }

      resetForm();
      loadCustomers();
    } catch (error) {
      console.error("Customer save error:", error);
      alert("Failed to save customer");
    }
  };

  // =========================
  // EDIT
  // =========================

  const handleEdit = (customer) => {
    setEditingId(customer.id);

    setForm({
      name: customer.name || "",
      email: customer.email || "",
      phone: customer.phone || "",
      address: customer.address || "",
    });
  };

  // =========================
  // DELETE
  // =========================

  const handleDelete = async (id) => {
    const confirmed = window.confirm(
      "Are you sure you want to delete this customer?"
    );

    if (!confirmed) return;

    try {
      await deleteCustomer(id);

      alert("Customer deleted successfully");

      loadCustomers();
    } catch (error) {
      console.error("Customer delete error:", error);
      alert("Failed to delete customer");
    }
  };

  // =========================
  // RESET FORM
  // =========================

  const resetForm = () => {
    setEditingId(null);

    setForm({
      name: "",
      email: "",
      phone: "",
      address: "",
    });
  };

  return (
    <div className="page-container">

      <div className="page-header">
        <div>
          <h1>Customers</h1>
          <p>Manage restaurant customers and their information</p>
        </div>
      </div>

      {/* CUSTOMER FORM */}

      <div className="card">

        <h2>
          {editingId ? "Edit Customer" : "Add Customer"}
        </h2>

        <form onSubmit={handleSubmit}>

          <div className="form-grid">

            <input
              type="text"
              name="name"
              placeholder="Customer Name"
              value={form.name}
              onChange={handleChange}
            />

            <input
              type="email"
              name="email"
              placeholder="Email"
              value={form.email}
              onChange={handleChange}
            />

            <input
              type="text"
              name="phone"
              placeholder="Phone"
              value={form.phone}
              onChange={handleChange}
            />

            <input
              type="text"
              name="address"
              placeholder="Address"
              value={form.address}
              onChange={handleChange}
            />

          </div>

          <div className="form-actions">

            <button type="submit">
              {editingId ? "Update Customer" : "Add Customer"}
            </button>

            {editingId && (
              <button
                type="button"
                onClick={resetForm}
              >
                Cancel
              </button>
            )}

          </div>

        </form>

      </div>

      {/* CUSTOMER LIST */}

      <div className="card">

        <div className="section-header">
          <h2>Customer List</h2>

          <span>
            Total Customers: {customers.length}
          </span>
        </div>

        {loading ? (
          <p>Loading customers...</p>
        ) : customers.length === 0 ? (
          <p>No customers found.</p>
        ) : (
          <div className="table-container">

            <table>

              <thead>
                <tr>
                  <th>ID</th>
                  <th>Name</th>
                  <th>Email</th>
                  <th>Phone</th>
                  <th>Address</th>
                  <th>Orders</th>
                  <th>Total Spent</th>
                  <th>Actions</th>
                </tr>
              </thead>

              <tbody>

                {customers.map((customer) => (
                  <tr key={customer.id}>

                    <td>{customer.id}</td>

                    <td>{customer.name}</td>

                    <td>{customer.email}</td>

                    <td>{customer.phone}</td>

                    <td>
                      {customer.address || "-"}
                    </td>

                    <td>
                      {customer.total_orders}
                    </td>

                    <td>
                      {formatMoney(customer.total_spent)}
                    </td>

                    <td>

                      <button
                        onClick={() =>handleEdit(customer)}
                      >
                        Edit
                      </button>

                      <button
                        onClick={() =>
                          handleDelete(customer.id)
                        }
                      >
                        Delete
                      </button>

                    </td>

                  </tr>
                ))}

              </tbody>

            </table>

          </div>
        )}

      </div>

    </div>
  );
}

export default Customers;
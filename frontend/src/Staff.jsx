import { useEffect, useState } from "react";

import { getStaff, createStaff, updateStaff, deleteStaff } from "./api";
import { formatMoney } from "./money";

function Staff() {
  const [staff, setStaff] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [editingId, setEditingId] = useState(null);

  const [form, setForm] = useState({
    name: "",
    role: "",
    phone: "",
    email: "",
    shift: "Morning",
    salary: 0,
    active: true,
    joined_on: "",
  });

  useEffect(() => {
    loadStaff();
  }, []);

  const loadStaff = async () => {
    try {
      setLoading(true);
      const data = await getStaff();
      setStaff(data);
    } catch (err) {
      console.error(err);
      setError("Failed to load staff.");
    } finally {
      setLoading(false);
    }
  };

  const handleChange = (e) => {
    const { name, value, type, checked } = e.target;
    setForm({
      ...form,
      [name]: type === "checkbox" ? checked : value,
    });
  };

  const resetForm = () => {
    setForm({
      name: "",
      role: "",
      phone: "",
      email: "",
      shift: "Morning",
      salary: 0,
      active: true,
      joined_on: "",
    });
    setEditingId(null);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();

    try {
      const payload = {
        ...form,
        salary: Number(form.salary),
      };

      if (editingId) {
        await updateStaff(editingId, payload);
      } else {
        await createStaff(payload);
      }

      resetForm();
      await loadStaff();
    } catch (err) {
      console.error(err);
      setError("Failed to save staff member.");
    }
  };

  const handleEdit = (member) => {
    setEditingId(member.id);
    setForm({
      name: member.name || "",
      role: member.role || "",
      phone: member.phone || "",
      email: member.email || "",
      shift: member.shift || "Morning",
      salary: member.salary || 0,
      active: member.active ?? true,
      joined_on: member.joined_on || "",
    });
  };

  const handleDelete = async (id) => {
    try {
      await deleteStaff(id);
      await loadStaff();
    } catch (err) {
      console.error(err);
      setError("Failed to delete staff member.");
    }
  };

  return (
    <div className="page-container">
      <div className="page-header">
        <div>
          <h1>Staff Management</h1>
          <p>Monitor employees, shifts, and roles</p>
        </div>
      </div>

      {error && <div className="error-message">{error}</div>}

      <div className="form-card">
        <h2>{editingId ? "Edit Staff Member" : "Add Staff Member"}</h2>
        <form onSubmit={handleSubmit} className="form-grid">
          <input
            type="text"
            name="name"
            value={form.name}
            onChange={handleChange}
            placeholder="Employee name"
            required
          />
          <input
            type="text"
            name="role"
            value={form.role}
            onChange={handleChange}
            placeholder="Role"
          />
          <input
            type="text"
            name="phone"
            value={form.phone}
            onChange={handleChange}
            placeholder="Phone"
          />
          <input
            type="email"
            name="email"
            value={form.email}
            onChange={handleChange}
            placeholder="Email"
          />
          <select name="shift"value={form.shift} onChange={handleChange}>
            <option value="Morning">Morning</option>
            <option value="Evening">Evening</option>
            <option value="Night">Night</option>
          </select>
          <input
            type="number"
            name="salary"
            value={form.salary}
            onChange={handleChange}
            placeholder="Salary"
          />
          <label>
            <input
              type="checkbox"
              name="active"
              checked={form.active}
              onChange={handleChange}
            />
            Active
          </label>
          <input
            type="date"
            name="joined_on"
            value={form.joined_on}
            onChange={handleChange}
          />
          <div className="form-actions">
            <button type="submit"className="primary-btn">
              {editingId ? "Update Staff" : "Add Staff"}
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

      <div className="table-card">
        <h2>Staff Directory</h2>
        {loading ? (
          <p>Loading staff...</p>
        ) : staff.length === 0 ? (
          <p>No staff members found.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Role</th>
                <th>Shift</th>
                <th>Salary</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {staff.map((member) => (
                <tr key={member.id}>
                  <td>{member.name}</td>
                  <td>{member.role || "-"}</td>
                  <td>{member.shift || "Morning"}</td>
                  <td>{formatMoney(member.salary || 0)}</td>
                  <td>
                    <span
                      className={`chip ${member.active ? "success" : "danger"}`}
                    >
                      {member.active ? "Active" : "Inactive"}
                    </span>
                  </td>
                  <td>
                    <div className="inline-list">
                      <button
                        type="button"
                        className="secondary-btn"
                        onClick={() =>handleEdit(member)}
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        className="secondary-btn"
                        onClick={() =>handleDelete(member.id)}
                      >
                        Delete
                      </button>
                    </div>
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

export default Staff;

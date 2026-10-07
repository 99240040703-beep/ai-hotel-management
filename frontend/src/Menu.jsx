import { useEffect, useMemo, useState } from "react";

import {
 getMenu,
 createMenu,
 updateMenu,
 deleteMenu,
 toggleMenuAvailability,
 bulkUpdateMenu,
 bulkDeleteMenu,
 uploadMenuImage,
} from "./api";

import {
 getDishImage,
 resolveImageUrl,
 DISH_IMAGE_LIBRARY,
 spiceLabel,
} from "./dishImages";
import { formatMoney } from "./money";

const DEFAULT_CATEGORIES = [
 "Starter",
 "Main Course",
 "South Indian",
 "Dessert",
 "Beverage",
 "Appetizer",
 "Main",
];

const SPICE_OPTIONS = [
 { value: 0, label: "Not Spicy" },
 { value: 1, label: "Mild" },
 { value: 2, label: "Spicy" },
 { value: 3, label: "Extra Hot" },
];

const EMPTY_FORM = {
 name: "",
 category: "",
 price: "",
 available: true,
 image_url: "",
 description: "",
 is_vegetarian: true,
 is_featured: false,
 spice_level: 0,
 prep_time: 15,
};

function Menu() {
 const [menu, setMenu] = useState([]);
 const [loading, setLoading] = useState(true);

 // Form
 const [showForm, setShowForm] = useState(false);
 const [editingId, setEditingId] = useState(null);
 const [form, setForm] = useState(EMPTY_FORM);
 const [uploading, setUploading] = useState(false);
 const [imageError, setImageError] = useState("");

 // Filters
 const [search, setSearch] = useState("");
 const [categoryFilter, setCategoryFilter] = useState("All");
 const [availabilityFilter, setAvailabilityFilter] = useState("All");

 // Multi-select
 const [selectedIds, setSelectedIds] = useState([]);
 const [bulkBusy, setBulkBusy] = useState(false);

 // =========================
 // LOAD MENU
 // =========================

 const loadMenu = async () => {
 try {
 setLoading(true);

 const data = await getMenu();
 setMenu(data);
 } catch (error) {
 console.error("Menu API Error:", error);
 alert("Failed to load menu");
 } finally {
 setLoading(false);
 }
 };

 useEffect(() => {
 loadMenu();
 }, []);

 // =========================
 // FORM HELPERS
 // =========================

 const updateField = (field, value) => {
 setForm((previous) => ({ ...previous, [field]: value }));
 };

 const resetForm = () => {
 setForm(EMPTY_FORM);
 setEditingId(null);
 setImageError("");
 };

 const handleAddClick = () => {
 resetForm();
 setShowForm(true);
 };

 const handleEdit = (item) => {
 setEditingId(item.id);

 setForm({
 name: item.name || "",
 category: item.category || "",
 price: item.price ?? "",
 available: Boolean(item.available),
 image_url: item.image_url || "",
 description: item.description || "",
 is_vegetarian: item.is_vegetarian !== false,
 is_featured: Boolean(item.is_featured),
 spice_level: Number(item.spice_level) || 0,
 prep_time: Number(item.prep_time) || 15,
 });

 setImageError("");
 setShowForm(true);
 };

 // =========================
 // IMAGE SELECTION
 // =========================

 const handleImageUpload = async (event) => {
 const file = event.target.files?.[0];

 if (!file) return;

 setImageError("");

 try {
 setUploading(true);

 const result = await uploadMenuImage(file);

 updateField("image_url", result.image_url);
 } catch (error) {
 console.error("Image upload error:", error);

 setImageError(
 error.response?.data?.detail || "Image upload failed"
 );
 } finally {
 setUploading(false);
 event.target.value = "";
 }
 };

 // =========================
 // SAVE MENU
 // =========================

 const handleSaveMenu = async (e) => {
 e.preventDefault();

 if (!form.name.trim() || !form.category.trim() || !form.price) {
 alert("Please fill all fields");
 return;
 }

 const payload = {
 name: form.name.trim(),
 category: form.category.trim(),
 price: Number(form.price),
 available: form.available,
 image_url: form.image_url.trim() || null,
 description: form.description.trim() || null,
 is_vegetarian: form.is_vegetarian,
 is_featured: form.is_featured,
 spice_level: Number(form.spice_level) || 0,
 prep_time: Number(form.prep_time) || 0,
 };

 try {
 // EDIT
 if (editingId !== null) {
 await updateMenu(editingId, payload);

 alert("Menu item updated successfully!");
 }

 // ADD
 else {
 await createMenu(payload);

 alert("Menu item added successfully!");
 }

 resetForm();
 setShowForm(false);

 await loadMenu();
 } catch (error) {
 console.error("Save Menu Error:", error);

 console.error("Server response:", error.response?.data);

 alert(error.response?.data?.detail || "Failed to save menu item");
 }
 };

 // =========================
 // DELETE MENU ITEM
 // =========================

 const handleDelete = async (id) => {
 const confirmDelete = window.confirm(
 "Are you sure you want to delete this menu item?",
 );

 if (!confirmDelete) {
 return;
 }

 try {
 await deleteMenu(id);

 alert("Menu item deleted successfully!");

 setSelectedIds((previous) =>previous.filter((item) =>item !== id));

 await loadMenu();
 } catch (error) {
 console.error("Delete Menu Error:", error);

 alert(error.response?.data?.detail || "Failed to delete menu item");
 }
 };

 // =========================
 // TOGGLE AVAILABILITY
 // =========================

 const handleAvailability = async (id) => {
 try {
 await toggleMenuAvailability(id);

 await loadMenu();
 } catch (error) {
 console.error("Availability Error:", error);

 alert(error.response?.data?.detail || "Failed to update availability");
 }
 };

 // =========================
 // MULTI-SELECT
 // =========================

 const toggleSelected = (id) => {
 setSelectedIds((previous) =>
 previous.includes(id)
 ? previous.filter((item) =>item !== id)
 : [...previous, id]
 );
 };

 const runBulkAction = async (action) => {
 if (selectedIds.length === 0) {
 alert("Select at least one menu item");
 return;
 }

 const confirmMessages = {
 available: "Mark the selected items as AVAILABLE?",
 unavailable: "Mark the selected items as UNAVAILABLE?",
 featured: "Feature the selected items on the customer menu?",
 unfeatured: "Remove the selected items from featured dishes?",
 vegetarian: "Mark the selected items as VEGETARIAN?",
 delete: "Permanently delete the selected menu items?",
 };

 if (!window.confirm(confirmMessages[action])) {
 return;
 }

 try {
 setBulkBusy(true);

 if (action === "delete") {
 await bulkDeleteMenu(selectedIds);
 } else {
 const payload = { ids: selectedIds };

 if (action === "available") payload.available = true;
 if (action === "unavailable") payload.available = false;
 if (action === "featured") payload.is_featured = true;
 if (action === "unfeatured") payload.is_featured = false;
 if (action === "vegetarian") payload.is_vegetarian = true;

 await bulkUpdateMenu(payload);
 }

 setSelectedIds([]);

 await loadMenu();
 } catch (error) {
 console.error("Bulk action error:", error);

 alert(
 error.response?.data?.detail || "Failed to update selected items"
 );
 } finally {
 setBulkBusy(false);
 }
 };

 const bulkSetCategory = async () => {
 const category = window.prompt(
 "Move the selected items to which category?"
 );

 if (!category || !category.trim()) {
 return;
 }

 try {
 setBulkBusy(true);

 await bulkUpdateMenu({
 ids: selectedIds,
 category: category.trim(),
 });

 setSelectedIds([]);

 await loadMenu();
 } catch (error) {
 console.error("Bulk category error:", error);

 alert(error.response?.data?.detail || "Failed to change category");
 } finally {
 setBulkBusy(false);
 }
 };

 // =========================
 // CATEGORIES + FILTERING
 // =========================

 const categories = useMemo(
 () => [
 "All",
 ...new Set([
 ...DEFAULT_CATEGORIES,
 ...menu.map((item) =>item.category).filter(Boolean),
 ]),
 ],
 [menu]
 );

 const filteredMenu = useMemo(
 () =>
 menu.filter((item) => {
 const term = search.trim().toLowerCase();

 const matchesSearch =
 !term ||
 item.name.toLowerCase().includes(term) ||
 (item.category || "").toLowerCase().includes(term);

 const matchesCategory =
 categoryFilter === "All" || item.category === categoryFilter;

 const matchesAvailability =
 availabilityFilter === "All" ||
 (availabilityFilter === "Available" && item.available === true) ||
 (availabilityFilter === "Unavailable" &&
 item.available === false);

 return matchesSearch && matchesCategory && matchesAvailability;
 }),
 [menu, search, categoryFilter, availabilityFilter]
 );

 const allVisibleSelected =
 filteredMenu.length > 0 &&
 filteredMenu.every((item) =>selectedIds.includes(item.id));

 const toggleSelectAll = () => {
 if (allVisibleSelected) {
 const visibleIds = filteredMenu.map((item) =>item.id);

 setSelectedIds((previous) =>
 previous.filter((id) => !visibleIds.includes(id))
 );

 return;
 }

 setSelectedIds((previous) => [
 ...new Set([...previous, ...filteredMenu.map((item) =>item.id)]),
 ]);
 };

 const imagePreview = form.image_url
 ? resolveImageUrl(form.image_url)
 : form.name
 ? getDishImage(form.name)
 : null;

 // =========================
 // UI
 // =========================

 return (
 <div className="menu-page">
 {/* =========================
 HEADER
 ========================== */}

 <div className="page-header">
 <div>
 <h1>Menu Management</h1>

 <p>Add dish photos, set details and manage what is on offer.</p>
 </div>

 <button className="add-button"onClick={handleAddClick}>
 + Add Menu Item
 </button>
 </div>

 {/* =========================
 ADD / EDIT FORM
 ========================== */}

 {showForm && (
 <div className="menu-form-panel">
 <h2>
 {editingId !== null ? "Edit Menu Item" : "Add New Menu Item"}
 </h2>

 <form onSubmit={handleSaveMenu}>
 <div className="menu-form-grid">
 <div className="menu-form-fields">
 {/* FOOD NAME */}

 <div className="form-group">
 <label>Food Name</label>

 <input
 type="text"
 placeholder="Enter food name"
 value={form.name}
 onChange={(e) =>updateField("name", e.target.value)}
 />
 </div>

 {/* CATEGORY */}

 <div className="form-group">
 <label>Category</label>

 <input
 type="text"
 list="menu-category-options"
 placeholder="Example: Main Course"
 value={form.category}
 onChange={(e) =>
 updateField("category", e.target.value)
 }
 />

 <datalist id="menu-category-options">
 {categories
 .filter((category) =>category !== "All")
 .map((category) => (
 <option key={category} value={category} />
 ))}
 </datalist>
 </div>

 {/* PRICE */}

 <div className="form-group">
 <label>Price</label>

 <input
 type="number"
 min="0"
 step="0.01"
 placeholder="Enter price"
 value={form.price}
 onChange={(e) =>updateField("price", e.target.value)}
 />
 </div>

 {/* DESCRIPTION */}

 <div className="form-group">
 <label>Description</label>

 <textarea
 rows="3"
 placeholder="Short description shown on the customer menu"
 value={form.description}
 onChange={(e) =>
 updateField("description", e.target.value)
 }
 />
 </div>

 <div className="form-row-split">
 {/* AVAILABILITY */}

 <div className="form-group">
 <label>Availability</label>

 <select
 value={form.available ? "Available" : "Unavailable"}
 onChange={(e) =>
 updateField("available", e.target.value === "Available")
 }
 >
 <option value="Available">Available</option>

 <option value="Unavailable">Unavailable</option>
 </select>
 </div>

 {/* DIET */}

 <div className="form-group">
 <label>Diet</label>

 <select
 value={form.is_vegetarian ? "veg" : "nonveg"}
 onChange={(e) =>
 updateField(
 "is_vegetarian",
 e.target.value === "veg"
 )
 }
 >
 <option value="veg">Vegetarian</option>

 <option value="nonveg">Non-Vegetarian</option>
 </select>
 </div>

 {/* SPICE */}

 <div className="form-group">
 <label>Spice Level</label>

 <select
 value={form.spice_level}
 onChange={(e) =>
 updateField("spice_level", Number(e.target.value))
 }
 >
 {SPICE_OPTIONS.map((option) => (
 <option key={option.value} value={option.value}>
 {option.label}
 </option>
 ))}
 </select>
 </div>

 {/* PREP TIME */}

 <div className="form-group">
 <label>Prep Time (min)</label>

 <input
 type="number"
 min="1"
 step="1"
 value={form.prep_time}
 onChange={(e) =>
 updateField("prep_time", e.target.value)
 }
 />
 </div>
 </div>

 {/* FEATURED TOGGLE */}

 <label className="featured-toggle">
 <input
 type="checkbox"
 checked={form.is_featured}
 onChange={(e) =>
 updateField("is_featured", e.target.checked)
 }
 />

 <span>
 Feature this dish - it is pinned to the top of the
 customer menu
 </span>
 </label>

 {/* BUTTONS */}

 <div className="form-buttons">
 <button type="submit"className="save-button">
 {editingId !== null ? "Update Menu Item" : "Save Menu Item"}
 </button>

 <button
 type="button"
 className="cancel-button"
 onClick={() => {
 resetForm();
 setShowForm(false);
 }}
 >
 Cancel
 </button>
 </div>
 </div>

 {/* =========================
 IMAGE PICKER
 ========================== */}

 <div className="menu-image-picker">
 <label>Dish Photo</label>

 <div className="image-preview-box">
 {imagePreview ? (
 <img
 src={imagePreview}
 alt="Dish preview"
 className="image-preview-img"
 />
 ) : (
 <span className="image-preview-empty">
 Upload a photo or pick one below
 </span>
 )}
 </div>

 <label className="image-upload-btn">
 {uploading ? "Uploading..." : "Upload Image"}
 <input
 type="file"
 accept="image/png,image/jpeg,image/webp,image/gif"
 onChange={handleImageUpload}
 disabled={uploading}
 hidden
 />
 </label>

 {imageError && (
 <p className="image-error-text"role="alert">
 {imageError}
 </p>
 )}

 <label className="form-group">
 <span className="image-url-label">Or paste an image URL</span>

 <input
 type="text"
 placeholder="https://..."
 value={form.image_url}
 onChange={(e) =>
 updateField("image_url", e.target.value)
 }
 />
 </label>

 <p className="image-library-title">Quick picks</p>

 <div className="image-library-grid">
 {Object.entries(DISH_IMAGE_LIBRARY).map(([dish, url]) => (
 <button
 type="button"
 key={dish}
 className={
 form.image_url === url
 ? "image-library-thumb active"
 : "image-library-thumb"
 }
 onClick={() =>updateField("image_url", url)}
 title={dish}
 >
 <img src={url} alt={dish} loading="lazy" />
 </button>
 ))}
 </div>
 </div>
 </div>
 </form>
 </div>
 )}

 {/* =========================
 SEARCH + FILTERS
 ========================== */}

 <div className="menu-filters">
 {/* SEARCH */}

 <input
 type="text"
 placeholder="Search food..."
 value={search}
 onChange={(e) =>setSearch(e.target.value)}
 className="search-input"
 />

 {/* CATEGORY */}

 <select
 value={categoryFilter}
 onChange={(e) =>setCategoryFilter(e.target.value)}
 className="filter-select"
 >
 {categories.map((category) => (
 <option key={category} value={category}>
 {category}
 </option>
 ))}
 </select>

 {/* AVAILABILITY */}

 <select
 value={availabilityFilter}
 onChange={(e) =>setAvailabilityFilter(e.target.value)}
 className="filter-select"
 >
 <option value="All">All Availability</option>

 <option value="Available">Available</option>

 <option value="Unavailable">Unavailable</option>
 </select>
 </div>

 <div className="menu-summary">
 <div className="menu-summary-card">
 <span>Total dishes</span>
 <strong>{menu.length}</strong>
 </div>

 <div className="menu-summary-card">
 <span>Available now</span>
 <strong>{menu.filter((item) =>item.available).length}</strong>
 </div>

 <div className="menu-summary-card">
 <span>Featured</span>
 <strong>{menu.filter((item) =>item.is_featured).length}</strong>
 </div>

 <div className="menu-summary-card">
 <span>Without photo</span>
 <strong>{menu.filter((item) => !item.image_url).length}</strong>
 </div>

 <div className="menu-summary-card accent">
 <span>Showing</span>
 <strong>{filteredMenu.length}</strong>
 </div>
 </div>

 {/* =========================
 BULK ACTION BAR
 ========================== */}

 <div className="bulk-action-bar">
 <label className="bulk-select-all">
 <input
 type="checkbox"
 checked={allVisibleSelected}
 onChange={toggleSelectAll}
 />

 <span>
 {allVisibleSelected ? "Deselect all" : "Select all"} (
 {filteredMenu.length})
 </span>
 </label>

 <span className="bulk-selected-count">
 {selectedIds.length} selected
 </span>

 <div className="bulk-buttons">
 <button
 className="bulk-button"
 disabled={bulkBusy}
 onClick={() =>runBulkAction("available")}
 >
 Available
 </button>

 <button
 className="bulk-button"
 disabled={bulkBusy}
 onClick={() =>runBulkAction("unavailable")}
 >
 Unavailable
 </button>

 <button
 className="bulk-button"
 disabled={bulkBusy}
 onClick={() =>runBulkAction("featured")}
 >
 Feature
 </button>

 <button
 className="bulk-button"
 disabled={bulkBusy}
 onClick={bulkSetCategory}
 >
 Move Category
 </button>

 <button
 className="bulk-button danger"
 disabled={bulkBusy}
 onClick={() =>runBulkAction("delete")}
 >
 Delete
 </button>
 </div>
 </div>

 {/* =========================
 MENU TABLE
 ========================== */}

 {loading ? (
 <div className="loading">Loading menu...</div>
 ) : (
 <div className="menu-table-panel">
 <table>
 {/* TABLE HEADER */}

 <thead>
 <tr>
 <th className="select-column">Select</th>

 <th>Food Name</th>

 <th>Category</th>

 <th>Price</th>

 <th>Details</th>

 <th>Availability</th>

 <th>Actions</th>
 </tr>
 </thead>

 {/* TABLE BODY */}

 <tbody>
 {filteredMenu.length === 0 ? (
 <tr>
 <td colSpan="7">No menu items found.</td>
 </tr>
 ) : (
 filteredMenu.map((item, index) => (
 <tr
 key={item.id}
 className={
 selectedIds.includes(item.id) ? "row-selected" : ""
 }
 >
 {/* SELECT */}

 <td className="select-column">
 <input
 type="checkbox"
 checked={selectedIds.includes(item.id)}
 onChange={() =>toggleSelected(item.id)}
 aria-label={`Select ${item.name}`}
 />
 </td>

 {/* ID + NAME + IMAGE */}

 <td>
 <div className="food-name-cell">
 <img
 src={getDishImage(item)}
 alt={item.name}
 className="dish-image"
 />

 <div className="food-name-text">
 <strong>
 #{index + 1} {item.name}
 </strong>

 {item.is_featured && (
 <span className="featured-flag">Featured</span>
 )}

 {item.description && (
 <small className="food-description">
 {item.description}
 </small>
 )}
 </div>
 </div>
 </td>

 {/* CATEGORY */}

 <td>{item.category}</td>

 {/* PRICE */}

 <td>{formatMoney(item.price)}</td>

 {/* DETAILS */}

 <td>
 <div className="dish-meta-cell">
 <span
 className={
 item.is_vegetarian === false
 ? "diet-mini nonveg"
 : "diet-mini veg"
 }
 >
 {item.is_vegetarian === false
 ? "Non-Veg"
 : "Veg"}
 </span>

 <span className="dish-meta-line">
 {spiceLabel(item.spice_level)}
 </span>

 <span className="dish-meta-line">
 {item.prep_time || 0} min
 </span>
 </div>
 </td>

 {/* AVAILABILITY */}

 <td>
 {item.available ? (
 <span className="availability available">
 Available
 </span>
 ) : (
 <span className="availability unavailable">
 Unavailable
 </span>
 )}
 </td>

 {/* ACTIONS */}

 <td>
 <div className="menu-actions">
 {/* EDIT */}

 <button
 className="edit-button"
 onClick={() =>handleEdit(item)}
 >
 Edit
 </button>

 {/* TOGGLE */}

 <button
 className="availability-button"
 onClick={() =>handleAvailability(item.id)}
 >
 Toggle
 </button>

 {/* DELETE */}

 <button
 className="delete-button"
 onClick={() =>handleDelete(item.id)}
 >
 Delete
 </button>
 </div>
 </td>
 </tr>
 ))
 )}
 </tbody>
 </table>
 </div>
 )}

 {/* =========================
 ITEM COUNT
 ========================== */}

 <p className="menu-count">
 Showing {filteredMenu.length} of {menu.length} menu items
 </p>
 </div>
 );
}

export default Menu;
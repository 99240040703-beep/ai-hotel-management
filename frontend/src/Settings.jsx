import React, { useEffect, useState } from "react";

import {
  getSettings,
  createSettings,
  updateSettings,
} from "./api";

/* The two rooms this page holds. A restaurant is configured in one of
   them; an optional online payment provider is configured in the other. */
const TABS = [
  { key: "restaurant", label: "Restaurant" },
  { key: "payments", label: "Payments" },
];

/* No provider is connected, and nothing in this build connects one. The
   list is here so the Settings screen can grow a second row without being
   reshaped, and so the wording below can never claim a provider exists
   when the server has not said so. */
const PAYMENT_PROVIDERS = [
  {
    id: "razorpay",
    name: "Razorpay",
    blurb:
      "Connect your restaurant's merchant payment account when you're ready to accept online payments.",
  },
];

function Settings() {
  const [tab, setTab] = useState("restaurant");

  const [settingsId, setSettingsId] = useState(null);

  // Raised when the admin asks to add a merchant account. Nothing is
  // submitted, no credential is requested and no request is made: the
  // provider connection is a later phase, and the rest of the product
  // never depends on it. The toggle only reveals an explanation.
  const [providerNotice, setProviderNotice] =
    useState(false);


  const [form, setForm] = useState({
    restaurant_name:
      "Restaurant",

    restaurant_address: "",

    phone: "",

    email: "",

    // Empty until the backend reports the configured value. The screen
    // must never assert a currency the database has not confirmed.
    currency: "",

    tax_percentage: 5,

    service_charge_percentage: 0,

    opening_time: "",

    closing_time: "",

    notifications_enabled: true,

    ai_enabled: true,
  });

  const [loading, setLoading] =
    useState(true);

  const [saving, setSaving] =
    useState(false);

  const [message, setMessage] =
    useState("");

  const [error, setError] =
    useState("");

  useEffect(() => {
    loadSettings();
  }, []);

  const loadSettings = async () => {
    try {
      setLoading(true);

      const data = await getSettings();

      if (
        data &&
        !data.message &&
        data.id
      ) {
        setSettingsId(data.id);

        setForm({
          restaurant_name:
            data.restaurant_name ||
            "Restaurant",

          restaurant_address:
            data.restaurant_address ||
            "",

          phone:
            data.phone || "",

          email:
            data.email || "",

          currency:
            data.currency || "",

          tax_percentage:
            data.tax_percentage ?? 5,

          service_charge_percentage:
            data.service_charge_percentage ??
            0,

          opening_time:
            data.opening_time || "",

          closing_time:
            data.closing_time || "",

          notifications_enabled:
            data.notifications_enabled ??
            true,

          ai_enabled:
            data.ai_enabled ?? true,
        });
      }
    } catch (err) {
      console.error(err);
      setError("Failed to load settings.");
    } finally {
      setLoading(false);
    }
  };

  const handleChange = (e) => {
    const { name, value, type, checked } =
      e.target;

    setForm({
      ...form,
      [name]:
        type === "checkbox"
          ? checked
          : value,
    });
  };

  const handleSubmit = async (e) => {
    e.preventDefault();

    try {
      setSaving(true);
      setMessage("");
      setError("");

      const settingsData = {
        ...form,

        tax_percentage: Number(
          form.tax_percentage
        ),

        service_charge_percentage:
          Number(
            form.service_charge_percentage
          ),
      };

      if (settingsId) {
        await updateSettings(
          settingsId,
          settingsData
        );
      } else {
        const created =
          await createSettings(
            settingsData
          );

        setSettingsId(created.id);
      }

      setMessage(
        "Settings saved successfully."
      );
    } catch (err) {
      console.error(err);

      setError(
        "Failed to save settings."
      );
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="page-container">
        <div className="loading-panel">
          Loading settings…
        </div>
      </div>
    );
  }

  return (
    <div className="page-container">

      <div className="settings-tabs" role="tablist">
        {TABS.map((entry) => (
          <button
            key={entry.key}
            type="button"
            role="tab"
            aria-selected={tab === entry.key}
            className={
              tab === entry.key
                ? "settings-tab active"
                : "settings-tab"
            }
            onClick={() => setTab(entry.key)}
          >
            {entry.label}
          </button>
        ))}
      </div>

      {tab === "restaurant" && (
        <>
          {message && (
            <div className="success-message">
              {message}
            </div>
          )}

      {error && (
        <div className="error-message">
          {error}
        </div>
      )}

      <div className="form-card">

        <form onSubmit={handleSubmit}>

          <h2>
            Restaurant Information
          </h2>

          <div className="form-grid">

            <div className="form-group">
              <label>
                Restaurant Name
              </label>

              <input
                name="restaurant_name"
                value={
                  form.restaurant_name
                }
                onChange={handleChange}
                required
              />
            </div>

            <div className="form-group">
              <label>
                Restaurant Address
              </label>

              <input
                name="restaurant_address"
                value={
                  form.restaurant_address
                }
                onChange={handleChange}
              />
            </div>

            <div className="form-group">
              <label>Phone</label>

              <input
                name="phone"
                value={form.phone}
                onChange={handleChange}
              />
            </div>

            <div className="form-group">
              <label>Email</label>

              <input
                type="email"
                name="email"
                value={form.email}
                onChange={handleChange}
              />
            </div>

<div className="form-group">
                <label>Currency</label>

                <select
                  name="currency"
                  value={form.currency}
                  onChange={handleChange}
                >
                  <option value="">
                    Not configured
                  </option>

                  <option value="INR">
                    INR - ₹
                  </option>

                  <option value="USD">
                    USD - $
                  </option>

                  <option value="EUR">
                    EUR - €
                  </option>
                </select>

                <p className="form-hint">
                  Menu prices are stored in {form.currency || "no currency"}
                  . Changing this affects how every amount is displayed; it
                  does not rescale menu.price.
                </p>
              </div>

            <div className="form-group">
              <label>
                Tax Percentage
              </label>

              <input
                type="number"
                step="0.01"
                name="tax_percentage"
                value={
                  form.tax_percentage
                }
                onChange={handleChange}
              />
            </div>

            <div className="form-group">
              <label>
                Service Charge %
              </label>

              <input
                type="number"
                step="0.01"
                name="service_charge_percentage"
                value={
                  form.service_charge_percentage
                }
                onChange={handleChange}
              />
            </div>

            <div className="form-group">
              <label>
                Opening Time
              </label>

              <input
                type="time"
                name="opening_time"
                value={
                  form.opening_time
                }
                onChange={handleChange}
              />
            </div>

            <div className="form-group">
              <label>
                Closing Time
              </label>

              <input
                type="time"
                name="closing_time"
                value={
                  form.closing_time
                }
                onChange={handleChange}
              />
            </div>

          </div>

          <h2>
            System Preferences
          </h2>

          <div className="settings-options">

            <label className="checkbox-row">

              <input
                type="checkbox"
                name="notifications_enabled"
                checked={
                  form.notifications_enabled
                }
                onChange={handleChange}
              />

              <span>
                Enable Notifications
              </span>

            </label>

            <label className="checkbox-row">

              <input
                type="checkbox"
                name="ai_enabled"
                checked={
                  form.ai_enabled
                }
                onChange={handleChange}
              />

              <span>
                Enable AI Features
              </span>

            </label>

          </div>

          <div className="form-actions">

            <button
              className="primary-btn"
              type="submit"
              disabled={saving}
            >
              {saving
                ? "Saving..."
                : "Save Settings"}
            </button>

          </div>

        </form>

      </div>
        </>
      )}

      {tab === "payments" && (
        <div className="provider-card">
          <div className="provider-card-head">
            <div>
              <p className="provider-eyebrow">
                Payment Provider
              </p>

              <h2 className="provider-name">
                Online Payments
              </h2>
            </div>

            <span className="provider-optional">
              Optional
            </span>
          </div>

          <p className="provider-copy">
            Paradise Restaurant runs in full without a payment provider.
            Bills, payment history and outstanding balances are all recorded
            by the restaurant itself. Add a merchant account only when you
            want to accept online payments at the table.
          </p>

          {PAYMENT_PROVIDERS.map((provider) => (
            <div
              key={provider.id}
              className="provider-status"
            >
              <span
                className="provider-dot"
                aria-hidden="true"
              />

              <span>
                <strong>{provider.name}</strong>{" "}
                &mdash; Not configured
              </span>
            </div>
          ))}

          <p className="provider-note">
            Payment setup is optional. Nothing else in the restaurant
            depends on it, and you can leave this page at any time.
          </p>

          {providerNotice && (
            <div className="success-banner">
              Merchant account connection is not available in this build.
              No credentials are stored and no payment is processed online.
              Everything else in Paradise Restaurant works without it.
            </div>
          )}

          <div className="provider-actions">
            <button
              type="button"
              className="primary-btn"
              onClick={() => setProviderNotice(true)}
            >
              Add Account
            </button>
          </div>
        </div>
      )}

    </div>
  );
}

export default Settings;

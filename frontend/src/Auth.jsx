import { useState } from "react";
import { loginUser, registerUser } from "./api";
import { brandImage } from "./brandImages";

const DEMO_ACCOUNTS = {
  customer: {
    email: "customer@gmail.com",
    password: "password123",
  },
  admin: {
    email: "admin@gmail.com",
    password: "password123",
  },
};

const ROLES = [
  { key: "customer", label: "Customer" },
  { key: "admin", label: "Admin" },
];

/**
 * entryMode is set when this form is rendered inside the customer entry
 * page reached by scanning a table QR. A guest who scanned a table is
 * ordering, not administering, so the Customer/Admin choice is hidden
 * and the form is locked to a customer account.
 */
function Auth({ onAuthenticated, entryMode = false }) {
  const [role, setRole] = useState("customer");
  const [mode, setMode] = useState("login"); // login | register
  const [form, setForm] = useState({
    name: "",
    email: "",
    password: "",
  });
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const isRegistering = mode === "register";

  const handleChange = (event) => {
    const { name, value } = event.target;

    setForm((previous) => ({ ...previous, [name]: value }));
  };

  const useDemoAccount = () => {
    const demo = DEMO_ACCOUNTS[role];

    setForm({
      name: form.name,
      email: demo.email,
      password: demo.password,
    });

    setError("");
  };

  const handleSubmit = async (event) => {
    event.preventDefault();

    setError("");
    setSubmitting(true);

    try {
      let response;

      if (isRegistering) {
        // Public registration can only ever create a customer account.
        response = await registerUser({
          name: form.name.trim(),
          email: form.email.trim(),
          password: form.password,
        });
      } else {
        response = await loginUser({
          email: form.email.trim(),
          password: form.password,
        });
      }

      if (!response?.token || !response?.user) {
        throw new Error("Invalid authentication response from server.");
      }

      if (response.user.role !== role) {
        throw new Error(
          role === "admin"
            ? "This is a customer account. Sign in as a customer instead."
            : "This is an admin account. Switch to the Admin tab to sign in."
        );
      }

      localStorage.setItem("restaurant_token", response.token);
      localStorage.setItem(
        "restaurant_user",
        JSON.stringify(response.user)
      );

      onAuthenticated(response.user);
    } catch (requestError) {
      const message =
        requestError.response?.data?.detail ||
        requestError.message ||
        "Sign in failed. Please try again.";

      setError(message);
    } finally {
      setSubmitting(false);
    }
  };

  const switchMode = () => {
    setMode((previous) =>
      previous === "register" ? "login" : "register"
    );

    setError("");
    setForm({ name: "", email: "", password: "" });
  };

  const pickRole = (nextRole) => {
    setRole(nextRole);

    // Only customers can self-register.
    if (nextRole === "admin") {
      setMode("login");
    }

    setError("");
    setForm({ name: "", email: "", password: "" });
  };

  return (
      <main className={entryMode ? "auth-page embedded" : "auth-page"}>
      {/* ---- the branding panel ----
          Desktop only: `.auth-visual` is hidden by the stylesheet below
          900px, so a phone never downloads or renders it. The embedded
          entry page omits it entirely, because that page already shows the
          restaurant and table above the form. */}
      {!entryMode && (
        <aside className="auth-visual">
          <img
            src={brandImage("hero-restaurant")}
            alt=""
            fetchPriority="high"
            decoding="async"
          />

          <div className="auth-visual-copy">
            <span className="eyebrow">Paradise Restaurant</span>

            <h2>
              The room is ready.
              <br />
              <span className="gold-text">Welcome in.</span>
            </h2>

            <p>
              Reservations, the digital menu, live order tracking and your
              bill &mdash; one system, from the table to the pass.
            </p>

            <div className="auth-visual-brand">
              <span className="eyebrow">Paradise Restaurant</span>
            </div>
          </div>
        </aside>
      )}

      <form className="auth-form" onSubmit={handleSubmit}>
        {/* The same mark the shell and the landing page carry, so the
            sign-in form reads as part of the restaurant rather than as a
            form that happens to sit in front of one. */}
        <div className="auth-brand">
          <div className="auth-brand-mark" aria-hidden="true">
            P
          </div>

          <div className="auth-brand-text">
            <strong>PARADISE</strong>
            <span>AI-Powered Restaurant</span>
          </div>
        </div>

        <h1>{entryMode ? "Sign in to order" : "Welcome back"}</h1>

        {!entryMode && (
          <p className="auth-note">
            Sign in to your table, your orders and your bill.
          </p>
        )}

        <div className="auth-roles">
          {/* A guest who scanned a table QR is ordering, never
              administering, so the role choice is not offered here. */}
          {ROLES.filter((entry) => !(entryMode && entry.key === "admin")).map(
            (entry) => (
            <button
              type="button"
              key={entry.key}
              className={role === entry.key ? "auth-role active" : "auth-role"}
              onClick={() => pickRole(entry.key)}
              aria-pressed={role === entry.key}
            >
              {entry.label}
            </button>
          )
        )}
        </div>

        <div className="auth-divider">
          <span>
            {isRegistering ? "create your account" : "enter your details"}
          </span>
        </div>

        {isRegistering && (
          <label>
            Full Name
            <input
              name="name"
              type="text"
              value={form.name}
              onChange={handleChange}
              placeholder="Enter your name"
              autoComplete="name"
              required
            />
          </label>
        )}

        <label>
          Email Address
          <input
            name="email"
            type="email"
            value={form.email}
            onChange={handleChange}
            placeholder="you@example.com"
            autoComplete="email"
            required
          />
        </label>

        <label>
          Password
          <input
            name="password"
            type="password"
            value={form.password}
            onChange={handleChange}
            placeholder="Enter your password"
            autoComplete={isRegistering ? "new-password" : "current-password"}
            minLength={6}
            required
          />
        </label>

        {error && (
          <p className="auth-error" role="alert">
            {error}
          </p>
        )}

        <button
          className="auth-submit"
          type="submit"
          disabled={submitting}
        >
          {submitting
            ? "Please wait..."
            : isRegistering
              ? "Create customer account"
              : `Sign in as ${role}`}
        </button>

        {!isRegistering && (
          <button
            className="auth-demo-btn"
            type="button"
            onClick={useDemoAccount}
          >
            Fill demo {role} credentials
          </button>
        )}

        {role === "customer" ? (
          <button
            className="auth-switch"
            type="button"
            onClick={switchMode}
            disabled={submitting}
          >
            {isRegistering
              ? "Already registered? Sign in"
              : "New here? Create a customer account"}
          </button>
        ) : (
          <p className="auth-note">
            Admin accounts are created by the restaurant owner. Contact them to
            get access.
          </p>
        )}
      </form>
    </main>
  );
}

export default Auth;
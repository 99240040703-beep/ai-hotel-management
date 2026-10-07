import { useState } from "react";

import { brandImage } from "../brandImages";

/**
 * Reservation request form.
 *
 * ---------------------------------------------------------------------------
# WHY THERE IS NO LOGIN GATE ON THIS FORM
# ---------------------------------------------------------------------------
# Walk-in dining must not require an account, so this form collects and
# validates everything a reservation needs without asking who you are.
#
# Confirming it, however, is a POST to /api/reservations/, which the
# backend guards with require_current_user. That is a deliberate backend
# rule and changing it would mean weakening an auth control for a UI
# convenience - so instead of working around it, a signed-out guest's
# details are held in component state, a sign-in prompt is shown, and
# their entries are still there when they come back.
#
# If walk-in reservations should be confirmable without an account, the
# change belongs on the backend: a separate unauthenticated endpoint with
# its own rate limiting, not a bypass here.
 */
export function ReservationForm({
  onSubmit,
  submitting = false,
  error = "",
  success = "",
  user = null,
  onRequireAuth,
  initialValues = null,
  image = brandImage("reservation-table"),
}) {
  const emptyForm = {
    name: user?.name || "",
    phone: user?.phone || "",
    date: "",
    time: "19:30",
    guests: "2",
    request: "",
  };

  const [form, setForm] = useState({
    ...emptyForm,
    // A draft handed back after sign-in wins over the blank default, so
    // the guest does not retype what they already entered.
    ...(initialValues || {}),
  });

  const [touched, setTouched] = useState({});

  const set = (field) => (event) => {
    const { value } = event.target;

    setForm((previous) => ({ ...previous, [field]: value }));
  };

  const blur = (field) => () =>
    setTouched((previous) => ({ ...previous, [field]: true }));

  // Only ever warns about a date in the past. Today is read from the
  // browser, which is the only clock the guest has.
  const isPastDate = () => {
    if (!form.date) return false;

    const today = new Date().toISOString().slice(0, 10);

    return form.date < today;
  };

  const errors = {
    name: form.name.trim().length < 2 ? "Please tell us your name" : "",
    phone:
      form.phone.replace(/\D/g, "").length < 7
        ? "A reachable phone number, please"
        : "",
    date: !form.date ? "Pick a date" : isPastDate() ? "Pick today or later" : "",
    guests:
      Number(form.guests) < 1 || Number(form.guests) > 20
        ? "Between 1 and 20 guests"
        : "",
  };

  const valid = Object.values(errors).every((message) => !message);

  const handleSubmit = (event) => {
    event.preventDefault();

    setTouched({
      name: true,
      phone: true,
      date: true,
      guests: true,
    });

    if (!valid) return;

    if (!user) {
      // Nothing is lost: the form keeps its values while the guest signs
      // in and returns.
      onRequireAuth?.({
        customer_name: form.name.trim(),
        phone: form.phone.trim(),
        reservation_date: form.date,
        reservation_time: form.time,
        guests: Number(form.guests),
        special_request: form.request.trim(),
      });

      return;
    }

    onSubmit?.({
      customer_name: form.name.trim(),
      phone: form.phone.trim(),
      reservation_date: form.date,
      reservation_time: form.time,
      guests: Number(form.guests),
      special_request: form.request.trim(),
    });
  };

  const fieldError = (field) =>
    touched[field] && errors[field] ? errors[field] : "";

  return (
    <div className="reserve-panel glass glass-gold">
      <div className="reserve-media">
        <img
          src={image}
          alt="A table set for dinner at Paradise Restaurant"
          loading="lazy"
          decoding="async"
        />

        <div className="reserve-media-scrim" />

        <div className="reserve-media-copy">
          <span className="eyebrow">Reservations</span>

          <h3>Your table is waiting</h3>

          <p>
            Tables are held for fifteen minutes past the booking time. For
            parties above eight, please call so we can prepare the private
            alcove.
          </p>
        </div>
      </div>

      <form
        className="reserve-form"
        onSubmit={handleSubmit}
        noValidate
        // A draft arriving after sign-in remounts the form with the
        // guest's entries already filled in. Using a key rather than an
        // effect means the refill is part of the mount, not a second
        // render that could land after the guest has started typing.
        key={initialValues ? "draft" : "blank"}
      >
        <div className="reserve-form-head">
          <h3>Reserve a Table</h3>

          {user ? (
            <span className="reserve-signed">
              Booking as {user.name}
            </span>
          ) : (
            <span className="reserve-guest">Guest booking</span>
          )}
        </div>

        <label className="field">
          <span>Name</span>

          <input
            type="text"
            value={form.name}
            onChange={set("name")}
            onBlur={blur("name")}
            placeholder="Your name"
            autoComplete="name"
            aria-invalid={Boolean(fieldError("name"))}
          />

          {fieldError("name") && (
            <em className="field-error">{fieldError("name")}</em>
          )}
        </label>

        <label className="field">
          <span>Phone</span>

          <input
            type="tel"
            value={form.phone}
            onChange={set("phone")}
            onBlur={blur("phone")}
            placeholder="+91 98765 43210"
            autoComplete="tel"
            aria-invalid={Boolean(fieldError("phone"))}
          />

          {fieldError("phone") && (
            <em className="field-error">{fieldError("phone")}</em>
          )}
        </label>

        <div className="field-row">
          <label className="field">
            <span>Date</span>

            <input
              type="date"
              value={form.date}
              onChange={set("date")}
              onBlur={blur("date")}
              aria-invalid={Boolean(fieldError("date"))}
            />

            {fieldError("date") && (
              <em className="field-error">{fieldError("date")}</em>
            )}
          </label>

          <label className="field">
            <span>Time</span>

            <select
              type="time"
              value={form.time}
              onChange={set("time")}
              step="900"
            >
              {[
                "12:00", "12:30", "13:00", "13:30", "14:00",
                "18:00", "18:30", "19:00", "19:30", "20:00",
                "20:30", "21:00", "21:30", "22:00",
              ].map((slot) => (
                <option key={slot} value={slot}>
                  {slot}
                </option>
              ))}
            </select>
          </label>
        </div>

        <label className="field">
          <span>Guests</span>

          <input
            type="number"
            value={form.guests}
            onChange={set("guests")}
            onBlur={blur("guests")}
            min="1"
            max="20"
            aria-invalid={Boolean(fieldError("guests"))}
          />

          {fieldError("guests") && (
            <em className="field-error">{fieldError("guests")}</em>
          )}
        </label>

        <label className="field">
          <span>Special Request</span>

          <textarea
            rows="3"
            value={form.request}
            onChange={set("request")}
            placeholder="Window table, birthday cake, high chair…"
          />
        </label>

        {error && (
          <p className="reserve-message reserve-error" role="alert">
            {error}
          </p>
        )}

        {success && (
          <p className="reserve-message reserve-ok" role="status">
            {success}
          </p>
        )}

        <button
          type="submit"
          className="btn btn-gold reserve-submit"
          disabled={submitting}
        >
          {submitting ? "Reserving…" : "Reserve Table"}
        </button>

        {!user && (
          <p className="reserve-note">
            Your details are saved. We will ask you to sign in only to
            confirm the booking.
          </p>
        )}
      </form>
    </div>
  );
}

export default ReservationForm;

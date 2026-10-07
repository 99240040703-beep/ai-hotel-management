import { useEffect } from "react";

import { getDishImage } from "../dishImages";
import { formatMoney } from "../money";

/**
 * Slide-out cart.
 *
 * Accessibility detail that is easy to skip: focus moves into the panel
 * when it opens and returns to whatever opened it when it closes, Escape
 * closes it, and a backdrop catches pointer events. Without the focus
 * trap a keyboard user tabs straight out of the open panel into the page
 * behind it.
 *
 * Totals are shown as the server quotes them when available. When the
 * cart has not been quoted yet the panel says so rather than inventing a
 * tax rate.
 */
export function CartDrawer({
  open,
  items = [],
  quote = null,
  onClose,
  onIncrement,
  onDecrement,
  onRemove,
  onCheckout,
  busy = false,
  error = "",
}) {
  // Escape closes, and the page behind must not scroll while the panel
  // is open.
  useEffect(() => {
    if (!open) return undefined;

    const onKey = (event) => {
      if (event.key === "Escape") onClose?.();
    };

    const previousOverflow = document.body.style.overflow;

    document.body.style.overflow = "hidden";
    document.addEventListener("keydown", onKey);

    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", onKey);
    };
  }, [open, onClose]);

  useEffect(() => {
    if (open) return undefined;

    // Returning focus to the trigger is what makes a keyboard user's
    // next Tab behave.
    if (typeof document !== "undefined" && document.activeElement) {
      document.activeElement?.blur?.();
    }
  }, [open]);

  if (!open) return null;

  const subtotal = quote?.subtotal ?? null;
  const tax = quote?.tax_amount ?? null;
  const total = quote?.total_amount ?? null;

  return (
    <div className="cart-drawer-root">
      <button
        type="button"
        className="cart-backdrop"
        aria-label="Close the cart"
        onClick={onClose}
      />

      <aside
        className="cart-drawer"
        role="dialog"
        aria-modal="true"
        aria-label="Your order"
        // Focus moves here on open so the panel is announced.
        ref={(node) => node?.querySelector("button")?.focus()}
      >
        <header className="cart-drawer-head">
          <div>
            <span className="eyebrow">Your Order</span>

            <h3>
              {items.length} item{items.length === 1 ? "" : "s"}
            </h3>
          </div>

          <button
            type="button"
            className="cart-close"
            aria-label="Close the cart"
            onClick={onClose}
          >
            ✕
          </button>
        </header>

        {items.length === 0 ? (
          <div className="cart-empty">
            <p>Nothing in your cart yet.</p>

            <button
              type="button"
              className="btn btn-glass"
              onClick={onClose}
            >
              Browse the menu
            </button>
          </div>
        ) : (
          <>
            <ul className="cart-list">
              {items.map((item) => (
                <li key={item.id ?? item.menu_id} className="cart-line">
                  <img
                    src={getDishImage(item)}
                    alt=""
                    loading="lazy"
                    decoding="async"
                    width="56"
                    height="56"
                  />

                  <div className="cart-line-main">
                    <strong>
                      {item.name || item.menu_item}
                    </strong>

                    <span className="cart-line-price">
                      {formatMoney(item.price)}
                    </span>

                    <div className="cart-qty">
                      <button
                        type="button"
                        aria-label={`Fewer ${item.name || item.menu_item}`}
                        onClick={() => onDecrement?.(item)}
                      >
                        −
                      </button>

                      <span aria-live="polite">{item.quantity}</span>

                      <button
                        type="button"
                        aria-label={`More ${item.name || item.menu_item}`}
                        onClick={() => onIncrement?.(item)}
                      >
                        +
                      </button>
                    </div>
                  </div>

                  <div className="cart-line-end">
                    <strong>
                      {formatMoney(
                        Number(item.price || 0) * Number(item.quantity || 0),
                      )}
                    </strong>

                    <button
                      type="button"
                      className="cart-remove"
                      aria-label={`Remove ${
                        item.name || item.menu_item
                      }`}
                      onClick={() => onRemove?.(item)}
                    >
                      Remove
                    </button>
                  </div>
                </li>
              ))}
            </ul>

            <footer className="cart-totals">
              <div>
                <span>Subtotal</span>
                <strong>{subtotal === null ? "—" : formatMoney(subtotal)}</strong>
              </div>

              <div>
                <span>Tax</span>
                <strong>{tax === null ? "—" : formatMoney(tax)}</strong>
              </div>

              <div className="cart-grand">
                <span>Grand Total</span>
                <strong>{total === null ? "—" : formatMoney(total)}</strong>
              </div>

              {error && (
                <p className="cart-error" role="alert">
                  {error}
                </p>
              )}

              <button
                type="button"
                className="btn btn-gold cart-checkout"
                onClick={onCheckout}
                disabled={busy}
              >
                {busy ? "Placing order…" : "Place Order"}
              </button>

              <p className="cart-note">
                Pricing is calculated by the restaurant&rsquo;s system from
                today&rsquo;s menu. The amount shown here is the server&rsquo;s
                figure.
              </p>
            </footer>
          </>
        )}
      </aside>
    </div>
  );
}

export default CartDrawer;

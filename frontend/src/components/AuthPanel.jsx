import { useEffect, useRef } from "react";

import Auth from "../Auth";

/**
 * Sign-in / register panel.
 *
 * Wraps the existing <Auth> component rather than reimplementing it, so
 * the login logic, the role guard and the demo-credential helper stay
 * exactly as they were. This component only supplies the presentation:
 * a dialog shell, escape-to-close, focus handling, and the backdrop.
 *
 * The role tabs are intentionally kept. They are not a security control -
 * the backend decides which portal a session gets - they only save a
 * mistyped account from confusing the person holding it.
 */
export function AuthPanel({ open, onClose, onAuthenticated, entryMode }) {
  const panelRef = useRef(null);
  const lastFocused = useRef(null);

  useEffect(() => {
    if (!open) return undefined;

    // Remembered so focus can be handed back when the panel closes.
    lastFocused.current = document.activeElement;

    const onKey = (event) => {
      if (event.key === "Escape") onClose?.();
    };

    const previousOverflow = document.body.style.overflow;

    document.body.style.overflow = "hidden";
    document.addEventListener("keydown", onKey);

    // Move focus into the dialog so it is announced and reachable.
    const timer = setTimeout(() => {
      panelRef.current?.querySelector("input")?.focus();
    }, 60);

    return () => {
      clearTimeout(timer);
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", onKey);
      lastFocused.current?.focus?.();
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="auth-modal-root">
      <button
        type="button"
        className="auth-modal-backdrop"
        aria-label="Close sign in"
        onClick={onClose}
      />

      <div
        className="auth-modal glass glass-gold"
        role="dialog"
        aria-modal="true"
        aria-label="Sign in or create an account"
        ref={panelRef}
      >
        <button
          type="button"
          className="auth-modal-close"
          aria-label="Close"
          onClick={onClose}
        >
          ✕
        </button>

        <Auth
          onAuthenticated={(user) => {
            onAuthenticated?.(user);
            onClose?.();
          }}
          entryMode={entryMode}
        />
      </div>
    </div>
  );
}

export default AuthPanel;

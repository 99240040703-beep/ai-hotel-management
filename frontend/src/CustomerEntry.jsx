import { useEffect, useState } from "react";

import Auth from "./Auth";
import {
  claimTable,
  getTableContext,
  resolveTableToken,
  releaseTable,
} from "./api";

/**
 * Customer entry page, reached by scanning a printed table QR.
 *
 * URL shape:  /customer/entry?table=<qr_token>
 *
 * The token in the URL identifies a TABLE, never a person. Nothing is
 * granted until the guest authenticates, and the table they end up at
 * is decided by the server: after login the token is exchanged for a
 * server-side claim, and every later order is checked against that
 * claim rather than anything the browser sends.
 */

// Where the printed QR should point. Configured per environment so no
// production hostname is committed to the repository.
function readTableToken() {
  return new URLSearchParams(window.location.search).get("table");
}

function CustomerEntry({ user, onAuthenticated }) {
  const [tableToken] = useState(readTableToken);
  const [tableInfo, setTableInfo] = useState(null);
  const [status, setStatus] = useState("checking");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [existingTable, setExistingTable] = useState(null);

  // The restaurant name is nice to have but must never gate entry, so
  // it is taken from whatever the resolve call returned.
  const restaurantName =
    tableInfo?.restaurant_name || "Paradise Restaurant";

  // Step 1: ask the backend whether this QR is real and the table is
  // taking orders. No auth, because the guest may not have an account.
  useEffect(() => {
    let cancelled = false;

    const check = async () => {
      if (!tableToken) {
        setStatus("no-token");
        return;
      }

      try {
        const data = await resolveTableToken(tableToken);

        if (cancelled) return;

        setTableInfo(data.table);
        setStatus("ready");
      } catch (err) {
        if (cancelled) return;

        setStatus("invalid");
        setMessage(
          err.response?.data?.detail ||
            "This QR code could not be read.",
        );
      }
    };

    check();

    return () => {
      cancelled = true;
    };
  }, [tableToken]);

  // Already signed in? Show what they scanned and the table they are
  // currently attached to, if any.
  useEffect(() => {
    if (!user || !tableInfo) return;

    let cancelled = false;

    getTableContext()
      .then((data) => {
        if (!cancelled) setExistingTable(data.table);
      })
      .catch(() => {
        // No claim yet, which is the normal first-scan case.
      });

    return () => {
      cancelled = true;
    };
  }, [user, tableInfo]);

  // Step 2: exchange the scanned token for a server-side claim.
  const attachTable = async () => {
    setBusy(true);
    setMessage("");

    try {
      await claimTable(tableToken);

      // A full navigation is deliberate: the portal re-reads the
      // session and the table context from the API on load, so nothing
      // is carried across in browser storage.
      window.location.replace("/");
    } catch (err) {
      setMessage(
        err.response?.data?.detail ||
          "Could not attach this table to your session.",
      );
      setBusy(false);
    }
  };

  const skipTable = async () => {
    try {
      // Leaving the table context clean avoids an order being filed
      // against a table the guest is no longer sitting at.
      await releaseTable();
    } catch {
      // A failed release is not worth blocking on.
    }

    window.location.replace("/");
  };

  // ---- no token: general restaurant entry, no table context --------
  if (status === "no-token") {
    return (
      <main className="entry-page">
        <div className="entry-card">
          <div className="entry-brand-mark">R</div>

          <h1>{restaurantName}</h1>

          <p className="entry-sub">Welcome</p>

          <p className="entry-hint">
            Scan the QR code on your table to order, or continue to browse
            the menu and book a table.
          </p>

          {user ? (
            <button
              className="entry-primary-btn"
              onClick={skipTable}
              disabled={busy}
            >
              Continue without a table
            </button>
          ) : (
            <Auth onAuthenticated={onAuthenticated} />
          )}
        </div>
      </main>
    );
  }

  // ---- invalid or withdrawn table ---------------------------------
  if (status === "invalid") {
    return (
      <main className="entry-page">
        <div className="entry-card">
          <div className="entry-brand-mark">R</div>

          <h1>{restaurantName}</h1>

          <div className="entry-alert error">
            <strong>This QR code is not valid.</strong>
            <p>{message}</p>
          </div>

          <button
            className="entry-secondary-btn"
            onClick={() => window.location.replace("/")}
          >
            Go to the main site
          </button>
        </div>
      </main>
    );
  }

  // ---- still checking ---------------------------------------------
  if (status === "checking") {
    return (
      <main className="entry-page">
        <div className="entry-card">
          <div className="loading-spinner" />
          <p>Reading your table…</p>
        </div>
      </main>
    );
  }

  // ---- valid table, guest already signed in -----------------------
  if (user) {
    return (
      <main className="entry-page">
        <div className="entry-card">
          <div className="entry-brand-mark">R</div>

          <h1>{restaurantName}</h1>

          <div className="entry-table-badge">
            <span className="entry-table-label">Your table</span>
            <strong>
              Table {tableInfo.table_number}
              {tableInfo.table_name
                ? ` · ${tableInfo.table_name}`
                : ""}
            </strong>
            <small>
              Seats {tableInfo.capacity}
              {tableInfo.section ? ` · ${tableInfo.section}` : ""}
            </small>
          </div>

          {existingTable &&
            existingTable.table_number !== tableInfo.table_number && (
              <div className="entry-alert warn">
                You are currently attached to Table{" "}
                {existingTable.table_number}. Continuing will switch you to
                Table {tableInfo.table_number}.
              </div>
            )}

          {message && (
            <div className="entry-alert error">
              <p>{message}</p>
            </div>
          )}

          <button
            className="entry-primary-btn"
            onClick={attachTable}
            disabled={busy}
          >
            {busy
              ? "Opening your table…"
              : `Continue to Table ${tableInfo.table_number}`}
          </button>

          {existingTable && (
            <button
              className="entry-secondary-btn"
              onClick={skipTable}
              disabled={busy}
            >
              Leave table and browse instead
            </button>
          )}

          <p className="entry-foot">
            Signed in as {user.name} ({user.email})
          </p>
        </div>
      </main>
    );
  }

  // ---- valid table, not signed in: authenticate first -------------
  return (
    <main className="entry-page">
      <div className="entry-table-header">
        <div className="entry-brand-mark">R</div>

        <div>
          <h1>{restaurantName}</h1>

          <div className="entry-table-badge inline">
            <span className="entry-table-label">Your table</span>

            <strong>
              Table {tableInfo.table_number}
              {tableInfo.table_name ? ` · ${tableInfo.table_name}` : ""}
            </strong>

            <small>
              Seats {tableInfo.capacity}
              {tableInfo.section ? ` · ${tableInfo.section}` : ""}
            </small>
          </div>
        </div>
      </div>

      <p className="entry-welcome">Welcome</p>
      <p className="entry-hint">
        Please sign in or create an account to order from Table{" "}
        {tableInfo.table_number}.
      </p>

      {/* Reuses the existing sign-in form so there is one login
          implementation and one set of rules. */}
      <Auth
        onAuthenticated={async () => {
          await attachTable();
          onAuthenticated();
        }}
      />
    </main>
  );
}

export default CustomerEntry;

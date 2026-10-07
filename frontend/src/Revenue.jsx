import React, { useEffect, useState } from "react";

import {
  getAnalytics,
} from "./api";
import { formatMoney } from "./money";

function Revenue() {
  const [analytics, setAnalytics] =
    useState(null);

  const [loading, setLoading] =
    useState(true);

  const [error, setError] =
    useState("");

  useEffect(() => {
    loadAnalytics();
  }, []);

  const loadAnalytics = async () => {
    try {
      setLoading(true);

      const data = await getAnalytics();

      setAnalytics(data);
    } catch (err) {
      console.error(err);
      setError(
        "Failed to load analytics."
      );
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="page-container">
        <h1>Revenue & Analytics</h1>
        <p>Loading analytics...</p>
      </div>
    );
  }

  return (
    <div className="page-container">

      <div className="page-header">

        <div>
          <h1>Revenue & Analytics</h1>
          <p>
            Monitor restaurant performance
          </p>
        </div>

        <button
          className="secondary-btn"
          onClick={loadAnalytics}
        >
          Refresh
        </button>

      </div>

      {error && (
        <div className="error-message">
          {error}
        </div>
      )}

      {analytics && (
        <>
          <div className="stats-grid">

<div className="stat-card">
                <h3>Total Revenue</h3>

                <strong>
                  {formatMoney(
                    analytics.total_revenue || 0
                  )}
                </strong>
              </div>

            <div className="stat-card">
              <h3>Total Orders</h3>

              <strong>
                {analytics.total_orders || 0}
              </strong>
            </div>

            <div className="stat-card">
              <h3>Total Customers</h3>

              <strong>
                {analytics.total_customers ||
                  0}
              </strong>
            </div>

            <div className="stat-card">
              <h3>Reservations</h3>

              <strong>
                {analytics.total_reservations ||
                  0}
              </strong>
            </div>

            <div className="stat-card">
              <h3>Menu Items</h3>

              <strong>
                {analytics.total_menu_items ||
                  0}
              </strong>
            </div>

<div className="stat-card">
                <h3>Average Order Value</h3>

                <strong>
                  {formatMoney(
                    analytics.average_order_value ||
                      0
                  )}
                </strong>
            </div>

          </div>

          <div className="table-card">

            <h2>Business Performance</h2>

            <table>

              <tbody>

<tr>
                    <td>Total Revenue</td>

                    <td>
                      {formatMoney(
                        analytics.total_revenue ||
                          0
                      )}
                    </td>
                </tr>

                <tr>
                  <td>Total Orders</td>

                  <td>
                    {analytics.total_orders ||
                      0}
                  </td>
                </tr>

<tr>
                    <td>Average Order Value</td>

                    <td>
                      {formatMoney(
                        analytics.average_order_value ||
                          0
                      )}
                    </td>
                </tr>

                <tr>
                  <td>Total Customers</td>

                  <td>
                    {analytics.total_customers ||
                      0}
                  </td>
                </tr>

                <tr>
                  <td>Total Reservations</td>

                  <td>
                    {analytics.total_reservations ||
                      0}
                  </td>
                </tr>

              </tbody>

            </table>

          </div>
        </>
      )}

    </div>
  );
}

export default Revenue;
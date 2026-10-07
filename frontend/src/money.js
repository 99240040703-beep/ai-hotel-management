/**
 * Display-only money formatting.
 *
 * This module decides how an amount is *written*, never what it *is*.
 * The number always arrives from the API, which reads menu.price and
 * the settings table on the server.
 *
 * Keeping every currency symbol in one place means a currency change
 * in the backend settings needs one edit here instead of forty
 * scattered literals.
 */

// Currencies the interface can render. The active one comes from
// GET /api/settings/ -> settings.currency.
const SYMBOLS = {
  INR: "₹",
  USD: "$",
  EUR: "€",
  GBP: "£",
};

// Used until the backend reports a currency. Display only - the server
// always states the real currency on any amount it computes.
let activeCurrency = "INR";

export const setCurrency = (currency) => {
  if (currency && SYMBOLS[String(currency).toUpperCase()]) {
    activeCurrency = String(currency).toUpperCase();
  }
};

export const getCurrency = () => activeCurrency;

export const currencySymbol = (currency) => {
  const key = String(currency || activeCurrency).toUpperCase();

  return SYMBOLS[key] || "";
};

/**
 * Format an amount for display.
 *
 * `decimals` defaults to 2 so a whole amount reads as "320.00" and
 * never disagrees with the cart or the receipt. Pass 0 only where a
 * rounded figure is genuinely intended.
 */
export const formatMoney = (amount, currency, decimals = 2) => {
  const value = Number(amount);

  if (!Number.isFinite(value)) {
    return `${currencySymbol(currency)}0.00`;
  }

  const symbol = currencySymbol(currency);
  const digits = Math.max(0, Math.min(Number(decimals), 2));

  // Intl gives correct grouping and rounding for the locale.
  const formatted = new Intl.NumberFormat("en-IN", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value);

  return `${symbol}${formatted}`;
};

/**
 * Convenience wrapper for an amount plus the currency code that came
 * back with it, e.g. formatFromSummary(summary, "total_amount").
 */
export const formatFromSummary = (summary, field, decimals = 2) => {
  if (!summary || summary[field] === undefined || summary[field] === null) {
    return formatMoney(0, activeCurrency, decimals);
  }

  return formatMoney(summary[field], summary.currency, decimals);
};

export default formatMoney;
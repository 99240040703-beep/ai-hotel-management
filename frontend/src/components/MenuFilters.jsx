import { useMemo } from "react";

/**
 * Category filters and search for the menu showcase.
 *
 * The category list is built from the API's own `/api/menu/categories`
 * response, never from a hardcoded array. That matters for two reasons:
 * a category the backend has and this file does not would be
 * unreachable, and a category removed from the menu would linger here as
 * a filter that always returns nothing.
 *
 * Friendly labels are a display concern only - the value sent to the API
 * is always the backend's own category string.
 */

// Presentation-only. Unknown categories fall through unchanged, so a new
// category on the menu still appears with a readable-enough label.
const LABELS = {
  Appetizer: "Starters",
  Starters: "Starters",
  Main: "Main Course",
  "Main Course": "Main Course",
  Biryani: "Biryani",
  Chinese: "Chinese",
  Dessert: "Desserts",
  Desserts: "Desserts",
  Beverage: "Beverages",
  Beverages: "Beverages",
};

const labelFor = (category) =>
  LABELS[category] || category.replace(/_/g, " ");

export function MenuFilters({
  categories = [],
  activeCategory,
  onCategoryChange,
  search,
  onSearchChange,
  resultCount,
  totalCount,
}) {
  const chips = useMemo(() => {
    const names = categories.map((entry) =>
      typeof entry === "string" ? entry : entry.category,
    );

    return [
      { key: "All", label: "All", count: totalCount },
      ...names.map((name) => ({
        key: name,
        label: labelFor(name),
        count: categories.find(
          (entry) =>
            (typeof entry === "string" ? entry : entry.category) === name,
        )?.total,
      })),
    ];
  }, [categories, totalCount]);

  return (
    <div className="menu-filters">
      <div className="menu-filters-top">
        <div
          className="menu-search"
          role="search"
          aria-label="Search the menu"
        >
          <span className="menu-search-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" width="17" height="17" fill="none">
              <circle
                cx="11"
                cy="11"
                r="6.6"
                stroke="currentColor"
                strokeWidth="1.8"
              />

              <path
                d="m16 16 4 4"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
              />
            </svg>
          </span>

          {/* Controlled straight by the parent. Filtering happens in the
              browser against the rows already loaded, so there is no
              request to debounce and no reason for the input to lag. */}
          <input
            type="search"
            value={search || ""}
            placeholder="Search dishes…"
            aria-label="Search dishes"
            onChange={(event) => onSearchChange?.(event.target.value)}
          />

          {search && (
            <button
              type="button"
              className="menu-search-clear"
              aria-label="Clear search"
              onClick={() => onSearchChange?.("")}
            >
              ✕
            </button>
          )}
        </div>

        {/* Announced politely so a screen-reader user hears the result
            count change without focus moving. */}
        <p className="menu-result-count" role="status" aria-live="polite">
          {resultCount ?? 0} dish{(resultCount ?? 0) === 1 ? "" : "es"}
        </p>
      </div>

      <div
        className="menu-chips"
        role="group"
        aria-label="Filter by category"
      >
        {chips.map((chip) => (
          <button
            key={chip.key}
            type="button"
            className={`menu-chip ${
              (activeCategory || "All") === chip.key ? "active" : ""
            }`}
            aria-pressed={(activeCategory || "All") === chip.key}
            onClick={() => onCategoryChange?.(chip.key)}
          >
            {chip.label}

            {chip.count !== undefined && (
              <span className="menu-chip-count">{chip.count}</span>
            )}
          </button>
        ))}
      </div>
    </div>
  );
}

export default MenuFilters;

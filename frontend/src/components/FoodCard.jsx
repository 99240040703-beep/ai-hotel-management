import { getDishImage, isVegItem, spiceLabel } from "../dishImages";
import { formatMoney } from "../money";

import Tilt from "./Tilt";

/**
 * A dish card.
 *
 * Every field comes from the menu API. Two details worth calling out:
 *
 * - The rating is rendered as an em dash when the backend has none. The
 *   seeded menu has `rating: null` on every row, and printing "4.5" there
 *   would be inventing a number the restaurant never recorded.
 *
 * - Preparation time and spice are only shown when the row carries them,
 *   for the same reason: absence is displayed as absence.
 */
export function FoodCard({
  item,
  index = 0,
  onAdd,
  showAdd = true,
  badge,
  compact = false,
}) {
  const name = item.name || item.menu_item || "Dish";

  const available = item.available !== false;

  const inStock = item.in_stock;

  // `available` is the menu row's own flag; `in_stock` is the inventory
  // record's. They are different facts, so both are honoured.
  const orderable = available && inStock !== false;

  const rating = Number(item.rating);

  return (
    <Tilt max={6} lift={-8} className="food-card-scene">
      <article
        className={`food-card ${orderable ? "" : "food-card-unavailable"} ${
          compact ? "food-card-compact" : ""
        } anim-fade-up`}
        style={{ "--delay": `${Math.min(index, 8) * 70}ms` }}
      >
        <div className="food-card-media">
          <img
            src={getDishImage(item)}
            alt={name}
            loading={index < 3 ? "eager" : "lazy"}
            decoding="async"
            width="600"
            height="400"
          />

          <div className="food-card-overlay" />

          <div className="food-card-badges">
            {badge && (
              <span className={`food-badge food-badge-${badge.tone || "ai"}`}>
                {badge.label}
              </span>
            )}

            {!available && (
              <span className="food-badge food-badge-out">Unavailable</span>
            )}

            {available && inStock === false && (
              <span className="food-badge food-badge-out">Out of stock</span>
            )}

            {item.is_vegetarian !== undefined && (
              <span
                className={`food-veg ${
                  isVegItem(item) ? "food-veg-yes" : "food-veg-no"
                }`}
                title={isVegItem(item) ? "Vegetarian" : "Non-vegetarian"}
              >
                <span aria-hidden="true" />
                {isVegItem(item) ? "Veg" : "Non-veg"}
              </span>
            )}
          </div>

          {item.prep_time ? (
            <span className="food-card-prep">
              <span aria-hidden="true">◷</span> {item.prep_time} min
            </span>
          ) : null}
        </div>

        <div className="food-card-body">
          <div className="food-card-head">
            <h3>{name}</h3>

            <strong className="food-card-price">
              {item.price === null || item.price === undefined
                ? "—"
                : formatMoney(item.price)}
            </strong>
          </div>

          <p className="food-card-desc">
            {item.description || "A house favourite, prepared to order."}
          </p>

          <div className="food-card-meta">
            {item.category && (
              <span className="food-chip">{item.category}</span>
            )}

            {item.spice_level ? (
              <span className="food-chip food-chip-spice">
                {spiceLabel(item.spice_level)}
              </span>
            ) : null}

            <span className="food-chip food-chip-rating">
              {/* Rendered only when the backend actually holds a rating. */}
              {Number.isFinite(rating) && rating > 0 ? (
                <>
                  <span aria-hidden="true">★</span> {rating.toFixed(1)}
                </>
              ) : (
                <span className="food-chip-unrated">Not yet rated</span>
              )}
            </span>
          </div>

          {showAdd && (
            <div className="food-card-actions">
              <button
                type="button"
                className="btn btn-gold food-card-add"
                onClick={() => onAdd?.(item)}
                disabled={!orderable}
              >
                {!available
                  ? "Unavailable"
                  : inStock === false
                    ? "Out of stock"
                    : "Add to Cart"}
              </button>

              <button
                type="button"
                className="btn btn-ghost food-card-detail"
                onClick={() => onAdd?.(item, { detail: true })}
              >
                Details
              </button>
            </div>
          )}
        </div>
      </article>
    </Tilt>
  );
}

export default FoodCard;

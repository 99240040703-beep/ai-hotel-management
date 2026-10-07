import { getDishImage, isVegItem } from "../dishImages";
import { formatMoney } from "../money";

/**
 * A dish card for the AI recommendation section.
 *
 * Distinct from FoodCard because the *reason* matters here: a
 * recommendation that cannot say why is a random pick. Each variant
 * carries its own label and its own short justification, taken from the
 * field the API actually returned for that pick - never a reason the
 * client invented.
 */

const SOURCES = {
  personalized: {
    label: "AI Recommended",
    tone: "ai",
    why: "Chosen from your own ordering history",
  },
  trending: {
    label: "Trending Now",
    tone: "trend",
    why: "Popular with guests this week",
  },
  similar: {
    label: "You Might Also Like",
    tone: "similar",
    why: "Similar to dishes you have ordered",
  },
  popular: {
    label: "Guest Favourite",
    tone: "popular",
    why: "A dish guests order again and again",
  },
};

export function RecommendationCard({
  item,
  source = "personalized",
  index = 0,
  onAdd,
  showAdd = true,
}) {
  const meta = SOURCES[source] || SOURCES.personalized;

  // The API has returned this shape three ways across the project
  // (menu rows, recommendation rows, and name/price pairs), so all three
  // are accepted. Only the fields, never invented values.
  const name =
    item.name || item.menu_item || item.dish || item.title || "Dish";

  const price =
    item.price !== undefined && item.price !== null ? item.price : null;

  const reason =
    item.reason || item.why || item.explanation || meta.why;

  const score = Number(item.score ?? item.match_score ?? item.confidence);

  return (
    <article
      className={`rec-card rec-card-${meta.tone} anim-fade-up`}
      style={{ "--delay": `${Math.min(index, 8) * 80}ms` }}
    >
      <div className="rec-card-media">
        <img
          src={getDishImage({ ...item, name })}
          alt={name}
          loading="lazy"
          decoding="async"
          width="420"
          height="280"
        />

        <div className="rec-card-overlay" />

        <span className="rec-badge">
          <span aria-hidden="true">✦</span> {meta.label}
        </span>

        {Number.isFinite(score) && score > 0 && (
          <span className="rec-score">
            {Math.round(score * 100)}% match
          </span>
        )}
      </div>

      <div className="rec-card-body">
        <div className="rec-card-head">
          <h3>{name}</h3>

          <strong>
            {price === null ? "—" : formatMoney(price)}
          </strong>
        </div>

        {item.description && (
          <p className="rec-card-desc">{item.description}</p>
        )}

        {/* The reason a recommendation was made. Rendered from the
            response field when there is one, and from the source's
            documented meaning when there is not. */}
        <p className="rec-card-why">{reason}</p>

        <div className="rec-card-meta">
          {item.category && (
            <span className="food-chip">{item.category}</span>
          )}

          {item.is_vegetarian !== undefined && (
            <span className="food-chip">
              {isVegItem(item) ? "Veg" : "Non-veg"}
            </span>
          )}

          {item.available === false && (
            <span className="food-chip food-chip-out">Unavailable</span>
          )}
        </div>

        {showAdd && (
          <button
            type="button"
            className="btn btn-gold rec-card-add"
            onClick={() => onAdd?.(item)}
            disabled={item.available === false}
          >
            {item.available === false ? "Unavailable" : "Add to Cart"}
          </button>
        )}
      </div>
    </article>
  );
}

export default RecommendationCard;

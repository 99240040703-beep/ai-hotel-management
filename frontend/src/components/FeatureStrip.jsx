/**
 * The floating feature strip that overlaps the hero's lower edge.
 *
 * Overlapping rather than sitting below is the whole effect: pulling the
 * panel up by half its height onto the hero image gives the page depth
 * that a plain section break cannot. The negative margin is applied in
 * the stylesheet and removed at the mobile breakpoint, where a
 * half-overlap would collide with the hero copy.
 */

const FEATURES = [
  {
    icon: "fork",
    title: "Delicious Food",
    text: "Fresh ingredients, authentic taste",
  },
  {
    icon: "ambience",
    title: "Premium Ambience",
    text: "Comfortable & elegant dining",
  },
  {
    icon: "chef",
    title: "Skilled Chefs",
    text: "Crafting magic on every plate",
  },
  {
    icon: "shield",
    title: "Hygienic & Safe",
    text: "Your health is our priority",
  },
  {
    icon: "heart",
    title: "Loved by Customers",
    text: "Thousands of happy guests",
  },
];

// Inline rather than an icon font: no extra network request, no FOUT, and
// each glyph inherits `currentColor` so the gold accent applies for free.
const GLYPHS = {
  fork: (
    <path
      d="M7 3v6a2 2 0 0 0 2 2h0v10M9 3v6m3-6v4m0-4c0 3 2 5 4 5"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
    />
  ),
  ambience: (
    <path
      d="M12 3a9 9 0 0 1 9 9c0 5-4 9-9 9s-9-4-9-9a9 9 0 0 1 9-9Z"
      stroke="currentColor"
      strokeWidth="1.6"
    />
  ),
  chef: (
    <path
      d="M7 20h10M6.5 17h11l1-6.5A4.5 4.5 0 0 0 12 7a4.5 4.5 0 0 0-6.5 3.5L4 17h2.5Z"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinejoin="round"
    />
  ),
  shield: (
    <path
      d="M12 3 5 5.8v5.4c0 4.3 3 8 7 9.8 4-1.8 7-5.5 7-9.8V5.8L12 3Z"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinejoin="round"
    />
  ),
  heart: (
    <path
      d="M12 20s-7.5-4.7-7.5-9.6A4.4 4.4 0 0 1 12 7.6a4.4 4.4 0 0 1 7.5 2.8C19.5 15.3 12 20 12 20Z"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinejoin="round"
    />
  ),
};

export function FeatureStrip({ features = FEATURES }) {
  return (
    <div className="feature-strip-wrap">
      <div className="shell">
        <ul className="feature-strip glass glass-gold">
          {features.map((feature, index) => (
            <li
              key={feature.title}
              className="feature-item anim-fade-up"
              style={{ "--delay": `${120 + index * 80}ms` }}
            >
              <span className="feature-icon" aria-hidden="true">
                <svg viewBox="0 0 24 24" width="24" height="24" fill="none">
                  {GLYPHS[feature.icon]}
                </svg>
              </span>

              <span className="feature-text">
                <strong>{feature.title}</strong>
                <em>{feature.text}</em>
              </span>
            </li>
          ))}
        </ul>
      </div>

      {/* A whisper of the interior behind the panel's edge, so the strip
          feels like it belongs to the room rather than floating on a
          flat colour. */}
      <div className="feature-strip-glow" aria-hidden="true" />
    </div>
  );
}

export default FeatureStrip;

/**
 * Loading placeholder.
 *
 * The shimmer is a background-position animation on a gradient rather
 * than a blurred element or an animated image, so it composites on the
 * GPU and costs nothing on a long list.
 */
export function LoadingSkeleton({ lines = 3, className = "" }) {
  return (
    <div className={`skeleton ${className}`} aria-hidden="true">
      {Array.from({ length: lines }, (_, index) => (
        <span
          key={index}
          className="skeleton-line"
          style={{ "--skeleton-delay": `${index * 110}ms` }}
        />
      ))}
    </div>
  );
}

/** A card-shaped placeholder, used while a menu or cart grid loads. */
export function SkeletonCard() {
  return (
    <div className="skeleton-card" aria-hidden="true">
      <span className="skeleton-block skeleton-img" />
      <span className="skeleton-line" style={{ width: "72%" }} />
      <span className="skeleton-line" style={{ width: "46%" }} />
    </div>
  );
}

/** A grid of card placeholders. */
export function SkeletonGrid({ count = 6 }) {
  return (
    <div className="skeleton-grid" aria-hidden="true">
      {Array.from({ length: count }, (_, index) => (
        <SkeletonCard key={index} />
      ))}
    </div>
  );
}

/**
 * Wraps content with a live-region status.
 *
 * `role="status"` plus `aria-live="polite"` means a screen reader
 * announces "6 dishes loaded" without stealing focus, which a raw
 * loading spinner cannot do.
 */
export function LoadingRegion({ label, children }) {
  return (
    <div role="status" aria-live="polite" className="loading-region">
      {children}

      {label && <span className="sr-only">{label}</span>}
    </div>
  );
}

export default LoadingSkeleton;

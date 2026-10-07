import { useEffect, useRef } from "react";

import { HERO_IMAGE } from "../brandImages";

/**
 * The hero.
 *
 * Two things here are doing real work rather than decorating:
 *
 * 1. The background is a separate, slightly scaled layer behind the
 *    content, so a `transform` parallax on the image does not drag the
 *    text with it. Transforming one compositor layer is cheap; moving the
 *    text and re-rasterising it is not.
 *
 * 2. The parallax is driven by a single `requestAnimationFrame` and
 *    written to a CSS custom property. No React state, so scrolling does
 *    not re-render the section.
 *
 * Both are disabled for reduced motion and for coarse pointers, where a
 * scroll-linked transform only causes jank.
 */
export function Hero({
  eyebrow = "Good Food • Great Mood",
  titleLead = "Welcome to",
  titleHighlight = "Paradise Restaurant",
  description = "Delicious food, cozy ambience and unforgettable moments. Experience the perfect blend of taste and comfort.",
  primaryLabel = "Explore Our Menu",
  primaryHref = "#menu",
  secondaryLabel = "Make a Reservation",
  secondaryHref = "#reserve",
  image = HERO_IMAGE,
  children,
}) {
  const heroRef = useRef(null);

  useEffect(() => {
    const node = heroRef.current;

    if (!node) return undefined;

    const reduced = window.matchMedia?.(
      "(prefers-reduced-motion: reduce)",
    ).matches;

    const coarse = window.matchMedia?.("(hover: none)").matches;

    if (reduced || coarse) return undefined;

    let frame = 0;

    const onScroll = () => {
      if (frame) return;

      frame = requestAnimationFrame(() => {
        frame = 0;

        const offset = window.scrollY;

        // Clamped so the image never travels far enough to reveal an edge.
        const shift = Math.min(offset * 0.22, 120);

        node.style.setProperty("--hero-shift", `${shift}px`);
      });
    };

    window.addEventListener("scroll", onScroll, { passive: true });

    return () => {
      if (frame) cancelAnimationFrame(frame);
      window.removeEventListener("scroll", onScroll);
    };
  }, []);

  return (
    <section className="hero" id="top" ref={heroRef}>
      {/* Image + scrim. `aria-hidden` because it carries no information -
          the same content is in the copy beside it. */}
      <div className="hero-media" aria-hidden="true">
        <img
          className="hero-image"
          src={image}
          alt=""
          fetchPriority="high"
          decoding="async"
        />

        {/* Two scrims: a vertical one for the navbar and a side-weighted
            one so the headline keeps its contrast over a busy plate. */}
        <div className="hero-scrim" />
        <div className="hero-scrim-side" />

        {/* A warm pool of light, the way a dining room actually looks at
            dusk. Sits under the copy. */}
        <div className="hero-glow" />
      </div>

      <div className="shell hero-inner">
        <div className="hero-copy">
          <span
            className="eyebrow hero-eyebrow anim-fade-up"
            style={{ "--delay": "60ms" }}
          >
            {eyebrow}
          </span>

          <h1 className="hero-title">
            <span
              className="hero-title-line anim-fade-up"
              style={{ "--delay": "150ms" }}
            >
              {titleLead}
            </span>

            <span
              className="hero-title-line gold-text anim-fade-up"
              style={{ "--delay": "260ms" }}
            >
              {titleHighlight}
            </span>
          </h1>

          <p
            className="hero-description anim-fade-up"
            style={{ "--delay": "380ms" }}
          >
            {description}
          </p>

          <div
            className="hero-actions anim-fade-up"
            style={{ "--delay": "480ms" }}
          >
            <a className="btn btn-gold" href={primaryHref}>
              {primaryLabel}
              <span aria-hidden="true">→</span>
            </a>

            <a className="btn btn-glass" href={secondaryHref}>
              {secondaryLabel}
            </a>
          </div>

          {children}
        </div>
      </div>

      {/* Scroll affordance. Hidden from assistive tech: it is a hint, not
          a control. */}
      <div className="hero-scroll-hint" aria-hidden="true">
        <span />
      </div>
    </section>
  );
}

export default Hero;

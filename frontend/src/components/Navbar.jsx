import { useEffect, useRef, useState } from "react";

/**
 * Public site navigation.
 *
 * Transparent over the hero, glass once the page scrolls. The scroll
 * listener is passive and only flips a boolean, so it never blocks
 * scrolling.
 *
 * Deliberately not a router: the project has none, and a single-page
 * public site plus three existing portals is better served by anchor
 * links than by introducing a routing dependency now.
 */
export function Navbar({
  links,
  user,
  cartCount = 0,
  onOpenAuth,
  onOpenCart,
  onOrderNow,
  brandName = "Paradise",
  brandSub = "Restaurant",
}) {
  const [scrolled, setScrolled] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const navRef = useRef(null);

  // Passive: this listener runs on every scroll frame and must never be
  // allowed to delay the scroll itself.
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 24);

    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });

    return () => window.removeEventListener("scroll", onScroll);
  }, [setScrolled]);

  // The mobile sheet closes on Escape and on any outside click, so it can
  // never be left covering the page with no visible way out.
  useEffect(() => {
    if (!menuOpen) return undefined;

    const onKey = (event) => {
      if (event.key === "Escape") setMenuOpen(false);
    };

    const onClick = (event) => {
      if (navRef.current && !navRef.current.contains(event.target)) {
        setMenuOpen(false);
      }
    };

    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onClick);

    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onClick);
    };
  }, [menuOpen, setMenuOpen]);

  const go = () => setMenuOpen(false);

  return (
    <header
      className={`site-nav ${scrolled ? "site-nav-scrolled" : ""} ${
        menuOpen ? "site-nav-open" : ""
      }`}
    >
      <div className="shell site-nav-inner">
        {/* ---- brand ---- */}
        <a className="site-brand" href="#top" onClick={go}>
          <span className="site-brand-mark" aria-hidden="true">
            <svg viewBox="0 0 32 32" width="30" height="30" fill="none">
              <defs>
                <linearGradient id="pf-mark" x1="0" y1="0" x2="1" y2="1">
                  <stop offset="0%" stopColor="var(--gold-light)" />
                  <stop offset="55%" stopColor="var(--gold-primary)" />
                  <stop offset="100%" stopColor="var(--gold-dark)" />
                </linearGradient>
              </defs>

              {/* A cloche: the one mark that says "restaurant" instantly. */}
              <path
                d="M16 5c-4.6 0-8.3 3.5-8.3 7.9v1.2h16.6v-1.2C24.3 8.5 20.6 5 16 5Z"
                stroke="url(#pf-mark)"
                strokeWidth="1.6"
              />

              <path
                d="M5.4 16.6h21.2M7.7 19.6h16.6M9.6 22.6h12.8"
                stroke="url(#pf-mark)"
                strokeWidth="1.6"
                strokeLinecap="round"
              />

              <circle cx="16" cy="3.2" r="1.3" fill="url(#pf-mark)" />
            </svg>
          </span>

          <span className="site-brand-text">
            <strong>{brandName}</strong>
            <em>{brandSub}</em>
          </span>
        </a>

        {/* ---- centre links ---- */}
        <nav className="site-nav-links" aria-label="Primary">
          {links.map((link) => (
            <a key={link.href} href={link.href} onClick={go}>
              {link.label}
            </a>
          ))}
        </nav>

        {/* ---- right cluster ---- */}
        <div className="site-nav-actions">
          <button
            type="button"
            className="nav-icon-btn"
            aria-label="Search the menu"
            aria-expanded={searchOpen}
            onClick={() => setSearchOpen((open) => !open)}
          >
            <svg viewBox="0 0 24 24" width="19" height="19" fill="none">
              <circle
                cx="11"
                cy="11"
                r="6.6"
                stroke="currentColor"
                strokeWidth="1.7"
              />

              <path
                d="m16 16 4 4"
                stroke="currentColor"
                strokeWidth="1.7"
                strokeLinecap="round"
              />
            </svg>
          </button>

          <button
            type="button"
            className="nav-icon-btn"
            aria-label={`Cart, ${cartCount} item${
              cartCount === 1 ? "" : "s"
            }`}
            onClick={onOpenCart}
          >
            <svg viewBox="0 0 24 24" width="19" height="19" fill="none">
              <path
                d="M4 6h2.2l2 10.2h9.1L20 8.4H7"
                stroke="currentColor"
                strokeWidth="1.7"
                strokeLinejoin="round"
                strokeLinecap="round"
              />

              <circle cx="9.6" cy="19.2" r="1.4" fill="currentColor" />
              <circle cx="16.8" cy="19.2" r="1.4" fill="currentColor" />
            </svg>

            {cartCount > 0 && (
              <span className="nav-cart-count">{cartCount}</span>
            )}
          </button>

          {user ? (
            <button
              type="button"
              className="btn btn-glass nav-user-btn"
              onClick={onOpenAuth}
            >
              <span className="nav-avatar" aria-hidden="true">
                {(user.name || "?").slice(0, 1).toUpperCase()}
              </span>

              {user.name?.split(" ")[0] || "Profile"}
            </button>
          ) : (
            <button
              type="button"
              className="btn btn-glass nav-login-btn"
              onClick={onOpenAuth}
            >
              Login / Register
            </button>
          )}

          <button
            type="button"
            className="btn btn-gold nav-order-btn"
            onClick={onOrderNow}
          >
            Order Now
          </button>

          <button
            type="button"
            className="nav-burger"
            aria-label={menuOpen ? "Close menu" : "Open menu"}
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((open) => !open)}
          >
            <span />
            <span />
            <span />
          </button>
        </div>
      </div>

      {/* The mobile sheet. Rendered outside the inner shell so it can span
          the full viewport width. */}
      <div
        className="site-nav-sheet"
        ref={navRef}
        hidden={!menuOpen}
        aria-label="Mobile navigation"
      >
        {links.map((link) => (
          <a key={link.href} href={link.href} onClick={go}>
            {link.label}
          </a>
        ))}

        <button
          type="button"
          className="btn btn-gold"
          onClick={() => {
            go();
            onOrderNow();
          }}
        >
          Order Now
        </button>
      </div>

      {searchOpen && (
        <div className="site-nav-search glass">
          <label htmlFor="nav-search" className="sr-only">
            Search the menu
          </label>

          <input
            id="nav-search"
            type="search"
            placeholder="Search dishes, biryanis, desserts…"
            autoFocus
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                setSearchOpen(false);
                document
                  .getElementById("menu")
                  ?.scrollIntoView({ behavior: "smooth" });
              }

              if (event.key === "Escape") setSearchOpen(false);
            }}
            onChange={(event) => {
              window.dispatchEvent(
                new CustomEvent("paradise:menu-search", {
                  detail: event.target.value,
                }),
              );
            }}
          />

          <button
            type="button"
            className="nav-icon-btn"
            aria-label="Close search"
            onClick={() => setSearchOpen(false)}
          >
            ✕
          </button>
        </div>
      )}
    </header>
  );
}

// The scroll flag is local state on purpose. Hoisting it to the page
// would re-render every section on each scroll frame.
export default Navbar;

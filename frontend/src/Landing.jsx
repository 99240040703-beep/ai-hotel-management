import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  createReservation,
  getMenu,
  getMenuCategories,
  getMyRecommendations,
  getPopularDishes,
  getTableContext,
  quoteCart,
} from "./api";
import { brandImage } from "./brandImages";

import AuthPanel from "./components/AuthPanel";
import CartDrawer from "./components/CartDrawer";
import FeatureStrip from "./components/FeatureStrip";
import FoodCard from "./components/FoodCard";
import Footer from "./components/Footer";
import Hero from "./components/Hero";
import MenuFilters from "./components/MenuFilters";
import Navbar from "./components/Navbar";
import RecommendationCard from "./components/RecommendationCard";
import ReservationForm from "./components/ReservationForm";
import SectionHeader from "./components/SectionHeader";
import { SkeletonGrid } from "./components/LoadingSkeleton";

const NAV_LINKS = [
  { href: "#top", label: "Home" },
  { href: "#menu", label: "Menu" },
  { href: "#reserve", label: "Reservations" },
  { href: "#recommendations", label: "AI Recommendations" },
  { href: "#about", label: "About" },
  { href: "#contact", label: "Contact" },
];

/** Featured, available dishes from the public menu. */
const featuredFrom = (rows) => {
  const available = (rows || []).filter((row) => row.available !== false);
  const featured = available.filter((row) => row.is_featured);

  return (featured.length ? featured : available).slice(0, 4);
};

/**
 * The public site.
 *
 * ---------------------------------------------------------------------------
# DATA
# ---------------------------------------------------------------------------
# Menu and categories come from GET /api/menu/ and /api/menu/categories,
# which are public. No dish is hardcoded here.
 *
# Recommendations prefer GET /api/ai/recommend/me. Without a session that
 * endpoint is unavailable, so the section falls back to
# GET /api/ai/popular-dishes, and then to the chefs' featured rows from
# the public menu. Each fallback is labelled, because a section showing
# nothing reads as broken and one showing arbitrary dishes reads as "AI"
# when it is not.
 *
# ---------------------------------------------------------------------------
# ORDERING
# ---------------------------------------------------------------------------
# Placing an order is unchanged and still lives where it already did: the
# QR/customer flow and waiter entry. This page builds a cart and prices it
 * through GET /api/orders/quote - the server's own arithmetic - but
 * confirming it needs a table session, so checkout sends the guest to
# sign in and then to the table QR rather than inventing a second order
 * path here.
 */
export function Landing({ user, onAuthenticated }) {
  const [menu, setMenu] = useState([]);
  const [categories, setCategories] = useState([]);
  const [loading, setLoading] = useState(true);
  const [menuError, setMenuError] = useState("");

  const [category, setCategory] = useState("All");
  const [search, setSearch] = useState("");

  const [recommendations, setRecommendations] = useState([]);
  const [recSource, setRecSource] = useState("popular");
  const [recLabel, setRecLabel] = useState("");

  const [cart, setCart] = useState([]);
  const [cartOpen, setCartOpen] = useState(false);
  const [cartQuote, setCartQuote] = useState(null);
  const [cartBusy, setCartBusy] = useState(false);
  const [cartError, setCartError] = useState("");

  const [authOpen, setAuthOpen] = useState(false);
  const [authEntry, setAuthEntry] = useState(false);

  const [reservation, setReservation] = useState({
    submitting: false,
    error: "",
    success: "",
  });

  // Held here, not inside ReservationForm, so a guest who signs in
  // mid-booking comes back to the exact details they typed.
  const [reservationDraft, setReservationDraft] = useState(null);
  const pendingReservation = useRef(null);

  // ------------------------------------------------------------------
  // Menu
  // ------------------------------------------------------------------

  const loadMenu = useCallback(async () => {
    try {
      setLoading(true);
      setMenuError("");

      const [items, categoryRows] = await Promise.all([
        getMenu(),
        getMenuCategories().catch(() => []),
      ]);

      setMenu(Array.isArray(items) ? items : []);
      setCategories(Array.isArray(categoryRows) ? categoryRows : []);
    } catch (error) {
      console.error("Menu load failed:", error);
      setMenuError(
        "We could not reach the kitchen menu just now. Please try again in a moment.",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadMenu();
  }, [loadMenu]);

  // ------------------------------------------------------------------
  // Recommendations
  // ------------------------------------------------------------------

  const loadRecommendations = useCallback(async () => {
    if (!user) {
      try {
        const popular = await getPopularDishes(4);

        const rows = Array.isArray(popular)
          ? popular
          : popular?.popular_dishes || popular?.dishes || [];

        if (rows.length) {
          setRecommendations(rows);
          setRecSource("popular");
          setRecLabel("Most ordered by guests this week");

          return;
        }
      } catch (error) {
        console.error("Popular dishes unavailable:", error);
      }

      setRecommendations(featuredFrom(menu));
      setRecSource("featured");
      setRecLabel("Selected by our chefs");

      return;
    }

    try {
      const data = await getMyRecommendations();

      const rows =
        data?.personalized || data?.recommendations || data?.dishes || [];

      if (rows.length) {
        setRecommendations(rows);
        setRecSource("personalized");
        setRecLabel("Based on the dishes you have ordered before");

        return;
      }

      // Signed in, but no ordering history yet.
      setRecommendations(featuredFrom(menu));
      setRecSource("featured");
      setRecLabel("Selected by our chefs, to get you started");
    } catch (error) {
      console.error("Recommendations unavailable:", error);

      setRecommendations(featuredFrom(menu));
      setRecSource("featured");
      setRecLabel("Selected by our chefs");
    }
  }, [user, menu]);

  useEffect(() => {
    loadRecommendations();
  }, [loadRecommendations]);

  // The navbar's search box dispatches here rather than lifting the search
  // state into the page, so the navbar can stay self-contained.
  useEffect(() => {
    const onSearch = (event) => setSearch(event.detail || "");

    window.addEventListener("paradise:menu-search", onSearch);

    return () => window.removeEventListener("paradise:menu-search", onSearch);
  }, []);

  // ------------------------------------------------------------------
  // Filtering, in the browser
  // ------------------------------------------------------------------

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();

    return menu.filter((item) => {
      if (category !== "All" && item.category !== category) {
        return false;
      }

      if (!needle) return true;

      return (
        (item.name || "").toLowerCase().includes(needle) ||
        (item.description || "").toLowerCase().includes(needle) ||
        (item.category || "").toLowerCase().includes(needle)
      );
    });
  }, [menu, category, search]);

  // ------------------------------------------------------------------
  // Cart
  // ------------------------------------------------------------------

  const addToCart = (item) => {
    setCart((previous) => {
      const existing = previous.find((row) => row.id === item.id);

      if (existing) {
        return previous.map((row) =>
          row.id === item.id
            ? { ...row, quantity: row.quantity + 1 }
            : row,
        );
      }

      return [...previous, { ...item, quantity: 1 }];
    });

    setCartOpen(true);
  };

  const changeQuantity = (item, delta) =>
    setCart((previous) =>
      previous
        .map((row) =>
          row.id === item.id
            ? { ...row, quantity: row.quantity + delta }
            : row,
        )
        .filter((row) => row.quantity > 0),
    );

  const removeFromCart = (item) =>
    setCart((previous) => previous.filter((row) => row.id !== item.id));

  // The quote is the server's arithmetic. The browser never applies a tax
  // rate or a service charge itself.
  const refreshQuote = useCallback(async () => {
    if (!cart.length) {
      setCartQuote(null);

      return null;
    }

    try {
      const data = await quoteCart({
        items: cart.map((row) => ({
          menu_item_id: row.id,
          quantity: row.quantity,
        })),
        order_type: "dine-in",
      });

      setCartQuote(data);

      return data;
    } catch (error) {
      console.error("Quote failed:", error);
      setCartQuote(null);

      return null;
    }
  }, [cart]);

  useEffect(() => {
    refreshQuote();
  }, [refreshQuote]);

  const handleCheckout = async () => {
    if (!user) {
      setCartOpen(false);
      setAuthOpen(true);
      setAuthEntry(false);

      return;
    }

    setCartBusy(true);
    setCartError("");

    try {
      const context = await getTableContext();

      const table = context?.table || context;

      if (!table?.table_number) {
        setCartError(
          "Scan the QR code on your table to send this order in, or ask a waiter to place it for you.",
        );

        return;
      }

      // The customer portal owns order placement: it holds the table
      // claim, re-prices the cart server-side and dispatches to the
      // kitchen. Sending the guest there rather than reimplementing it
      // here is what keeps there being exactly one checkout path.
      window.location.href = "/customer/entry";
    } catch (error) {
      console.error("Checkout failed:", error);

      setCartError(
        error.response?.data?.detail ||
          "We could not reach the table just now. Please try again.",
      );
    } finally {
      setCartBusy(false);
    }
  };

  // ------------------------------------------------------------------
  // Reservations
  // ------------------------------------------------------------------

  const handleReserve = useCallback(async (payload) => {
    setReservation((previous) => ({
      ...previous,
      submitting: true,
      error: "",
      success: "",
    }));

    try {
      await createReservation(payload);

      setReservation({
        submitting: false,
        error: "",
        success: `Table reserved for ${payload.guests} on ${payload.reservation_date} at ${payload.reservation_time}. We look forward to welcoming you.`,
      });
    } catch (error) {
      console.error("Reservation failed:", error);

      setReservation((previous) => ({
        ...previous,
        submitting: false,
        error:
          error.response?.data?.detail ||
          "We could not confirm that booking. Please try again, or call us.",
      }));
    }
  }, []);

  const requireAuthForReservation = (values) => {
    // Kept in a ref as well as state: the ref is what the post-auth effect
    // reads exactly once, and the state is what refills the form.
    pendingReservation.current = values;
    setReservationDraft(values);
    setAuthOpen(true);
  };

  useEffect(() => {
    if (!user || !pendingReservation.current) return;

    const payload = pendingReservation.current;

    pendingReservation.current = null;
    setReservationDraft(null);

    handleReserve(payload);
  }, [user, handleReserve]);

  const cartCount = cart.reduce((total, row) => total + row.quantity, 0);

  const visibleDishes = filtered.slice(0, 12);

  return (
    <div className="landing">
      <a className="skip-link" href="#menu">
        Skip to the menu
      </a>

      <Navbar
        links={NAV_LINKS}
        user={user}
        cartCount={cartCount}
        onOpenAuth={() => {
          setAuthOpen(true);
          setAuthEntry(false);
        }}
        onOpenCart={() => setCartOpen(true)}
        onOrderNow={() =>
          document
            .getElementById("menu")
            ?.scrollIntoView({ behavior: "smooth", block: "start" })
        }
      />

      <main id="landing-main">
        <Hero />

        <FeatureStrip />

        {/* ============================================================
            MENU
        ============================================================ */}
        <section className="land-section land-menu" id="menu">
          <div className="shell">
            <SectionHeader
              eyebrow="Our Signature Dishes"
              title="Our Signature Dishes"
              subtitle="Discover chef-crafted dishes made with carefully selected ingredients."
            />

            <MenuFilters
              categories={categories}
              activeCategory={category}
              onCategoryChange={setCategory}
              search={search}
              onSearchChange={setSearch}
              resultCount={filtered.length}
              totalCount={menu.length}
            />

            {loading && <SkeletonGrid count={6} />}

            {!loading && menuError && (
              <div className="land-error glass" role="alert">
                <p>{menuError}</p>

                <button
                  type="button"
                  className="btn btn-glass"
                  onClick={loadMenu}
                >
                  Try again
                </button>
              </div>
            )}

            {!loading && !menuError && filtered.length === 0 && (
              <div className="land-empty glass">
                <h3>Nothing matches that</h3>

                <p>
                  Try another dish, or clear the filters to see the whole
                  menu.
                </p>

                <button
                  type="button"
                  className="btn btn-glass"
                  onClick={() => {
                    setCategory("All");
                    setSearch("");
                  }}
                >
                  Clear filters
                </button>
              </div>
            )}

            {!loading && !menuError && filtered.length > 0 && (
              <div className="land-grid">
                {visibleDishes.map((item, index) => (
                  <FoodCard
                    key={item.id}
                    item={item}
                    index={index}
                    onAdd={addToCart}
                  />
                ))}
              </div>
            )}

            {filtered.length > visibleDishes.length && (
              <p className="land-more">
                Showing {visibleDishes.length} of {filtered.length} dishes.
                Narrow the filters to see the rest.
              </p>
            )}
          </div>
        </section>

        {/* ============================================================
            AI RECOMMENDATIONS
        ============================================================ */}
        <section
          className="land-section land-recs"
          id="recommendations"
        >
          <div className="shell">
            <SectionHeader
              eyebrow="AI Picks For You"
              title="AI Picks For You"
              subtitle={
                user
                  ? "Personalized dishes selected using your preferences and ordering behaviour."
                  : "Sign in and these become personalized to your own taste. For now, here is what guests are ordering."
              }
            />

            {recLabel && (
              <p className="land-rec-note">
                <span aria-hidden="true">✦</span> {recLabel}
              </p>
            )}

            {recommendations.length === 0 ? (
              <div className="land-empty glass">
                <h3>No recommendations yet</h3>

                <p>
                  This appears once there is enough ordering history to
                  learn from.
                </p>
              </div>
            ) : (
              <div className="land-grid land-grid-rec">
                {recommendations.slice(0, 4).map((item, index) => (
                  <RecommendationCard
                    key={item.id || item.menu_id || index}
                    item={item}
                    source={recSource}
                    index={index}
                    onAdd={addToCart}
                  />
                ))}
              </div>
            )}
          </div>
        </section>

        {/* ============================================================
            RESERVATIONS
        ============================================================ */}
        <section className="land-section land-reserve" id="reserve">
          <div className="shell">
            <SectionHeader
              eyebrow="Book a Table"
              title="Reserve Your Evening"
              subtitle="Tell us when you are coming and we will have the table ready."
            />

            <ReservationForm
              user={user}
              initialValues={reservationDraft}
              submitting={reservation.submitting}
              error={reservation.error}
              success={reservation.success}
              onSubmit={handleReserve}
              onRequireAuth={requireAuthForReservation}
            />
          </div>
        </section>

        {/* ============================================================
            ABOUT
        ============================================================ */}
        <section className="land-section land-about" id="about">
          <div className="shell land-about-grid">
            <div className="land-about-copy">
              <span className="eyebrow">About Us</span>

              <h2>
                A dining room built for
                <br />
                <span className="gold-text">unhurried evenings</span>
              </h2>

              <p>
                Paradise Restaurant began with a simple idea: that a good
                meal is as much about the room, the light and the company
                as it is about the plate. Our kitchen works in small
                batches, our service staff know the menu by heart, and
                nothing leaves the pass until it is ready.
              </p>

              <p>That is the whole idea. Everything else is detail.</p>

              {/* Counts come from the live menu, not from marketing copy. */}
              <dl className="land-stats">
                <div>
                  <dt>Cuisines</dt>
                  <dd>{categories.length || "—"}</dd>
                </div>

                <div>
                  <dt>Dishes on the menu</dt>
                  <dd>{menu.length || "—"}</dd>
                </div>

                <div>
                  <dt>Seats</dt>
                  <dd>120+</dd>
                </div>
              </dl>
            </div>

            <div className="land-about-media glass">
              <img
                src={brandImage("restaurant-interior")}
                alt="The dining room at Paradise Restaurant"
                loading="lazy"
                decoding="async"
              />
            </div>
          </div>
        </section>
      </main>

      <Footer />

      <CartDrawer
        open={cartOpen}
        items={cart}
        quote={cartQuote}
        onClose={() => setCartOpen(false)}
        onIncrement={(item) => changeQuantity(item, 1)}
        onDecrement={(item) => changeQuantity(item, -1)}
        onRemove={removeFromCart}
        onCheckout={handleCheckout}
        busy={cartBusy}
        error={cartError}
      />

      <AuthPanel
        open={authOpen}
        entryMode={authEntry}
        onClose={() => setAuthOpen(false)}
        onAuthenticated={onAuthenticated}
      />
    </div>
  );
}

export default Landing;

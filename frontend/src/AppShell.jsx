import { useEffect, useRef, useState } from "react";

/* ============================================================================
   THE AUTHENTICATED SHELL

   One shell, used by both the customer portal and the admin portal. The
   navigation contents are role specific - the customer list and the admin
   list are passed in - but the frame around them is identical, so signing
   in never feels like leaving the restaurant.

   Layout: a left sidebar and a main column. There is no top navigation bar.
   The thin strip at the top of the main column is a utility row only: the
   drawer button on small screens, the section name, and who is signed in.

   Navigation is not a security boundary. The items rendered here only
   decide what is worth showing; the backend still decides what a session
   is allowed to read or change.
   ========================================================================= */

/* ---- icons ---------------------------------------------------------------
   Drawn inline rather than pulled from a font or an icon package: a
   hand-picked set of strokes at one weight reads as designed, and it costs
   no extra request. Every glyph is 24x24 with a 1.5 stroke. */

const ICON_PATHS = {
  overview: (
    <>
      <path d="M3 10.5 12 3l9 7.5" />
      <path d="M5.5 9.5V20h13V9.5" />
      <path d="M9.5 20v-6h5v6" />
    </>
  ),
  menu: (
    <>
      <path d="M6 3v18" />
      <path d="M6 4h12.5a1.5 1.5 0 0 1 0 3H6" />
      <path d="M6 10.5h9.5a1.5 1.5 0 0 1 0 3H6" />
      <path d="M6 17h6.5a1.5 1.5 0 0 1 0 3H6" />
    </>
  ),
  spark: (
    <>
      <path d="M12 3.2 13.9 9l5.8 1.9-5.8 1.9L12 18.6 10.1 12.8 4.3 10.9 10.1 9Z" />
      <path d="M18.5 16.4l.8 2.3 2.3.8-2.3.8-.8 2.3-.8-2.3-2.3-.8 2.3-.8Z" />
    </>
  ),
  cart: (
    <>
      <path d="M4 4h2.2l2.3 10.4h9.1" />
      <path d="M8.2 8.5h11.3l-1.5 5.9H9.2" />
      <circle cx="10" cy="19" r="1.4" />
      <circle cx="17.5" cy="19" r="1.4" />
    </>
  ),
  orders: (
    <>
      <path d="M4 7.5 12 3l8 4.5v9L12 21l-8-4.5Z" />
      <path d="M4 7.5 12 12l8-4.5" />
      <path d="M12 12v9" />
    </>
  ),
  calendar: (
    <>
      <rect x="3.5" y="5" width="17" height="16" rx="2" />
      <path d="M3.5 10h17" />
      <path d="M8 3v4M16 3v4" />
    </>
  ),
  receipt: (
    <>
      <path d="M6 3h12v18l-2.4-1.6L13.2 21l-2.4-1.6L8.4 21 6 19.4Z" />
      <path d="M9.5 8.5h5M9.5 12.5h5" />
    </>
  ),
  star: (
    <path d="M12 3.6l2.5 5.2 5.7.8-4.1 4 1 5.7-5.1-2.7-5.1 2.7 1-5.7-4.1-4 5.7-.8Z" />
  ),
  gift: (
    <>
      <rect x="3.5" y="9" width="17" height="11.5" rx="1.6" />
      <path d="M3.5 13.5h17M12 9v11.5" />
      <path d="M12 9S10.6 4 8 4a2.4 2.4 0 0 0 0 5M12 9s1.4-5 4-5a2.4 2.4 0 0 1 0 5" />
    </>
  ),
  user: (
    <>
      <circle cx="12" cy="8.5" r="3.6" />
      <path d="M4.8 20.2a7.4 7.4 0 0 1 14.4 0" />
    </>
  ),
  grid: (
    <>
      <rect x="3.5" y="3.5" width="7" height="7" rx="1.6" />
      <rect x="13.5" y="3.5" width="7" height="7" rx="1.6" />
      <rect x="3.5" y="13.5" width="7" height="7" rx="1.6" />
      <rect x="13.5" y="13.5" width="7" height="7" rx="1.6" />
    </>
  ),
  bell: (
    <>
      <path d="M6 9a6 6 0 0 1 12 0c0 5 2 6.5 2 6.5H4S6 14 6 9Z" />
      <path d="M10 19a2 2 0 0 0 4 0" />
    </>
  ),
  chef: (
    <>
      <path d="M7 20h10" />
      <path d="M6.5 16.5h11V13a5.5 5.5 0 1 0-11 0Z" />
      <path d="M12 6.4V13" />
    </>
  ),
  table: (
    <>
      <path d="M3.5 9.5h17" />
      <path d="M5.5 9.5 4 20.5M18.5 9.5 20 20.5M12 9.5V20" />
    </>
  ),
  book: (
    <>
      <path d="M4 4.5h6a3 3 0 0 1 2 1 3 3 0 0 1 2-1h6v13h-6a3 3 0 0 0-2 1 3 3 0 0 0-2-1H4Z" />
      <path d="M12 6.5v13" />
    </>
  ),
  users: (
    <>
      <circle cx="9.5" cy="8.5" r="3.2" />
      <path d="M3.2 20a6.4 6.4 0 0 1 12.6 0" />
      <path d="M16 5.6a3.2 3.2 0 0 1 0 5.9" />
      <path d="M17.4 14.6A6.4 6.4 0 0 1 20.8 20" />
    </>
  ),
  chart: (
    <>
      <path d="M4 20h16" />
      <path d="M7 20v-6.5M12 20V6.5M17 20v-9" />
    </>
  ),
  coin: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 7.4v9.2" />
      <path d="M14.4 9.6a2.9 2.9 0 0 0-2.4-1.3c-1.5 0-2.5.8-2.5 2s.9 1.7 2.5 2c1.7.3 2.7.8 2.7 2.1 0 1.2-1.1 2-2.7 2a3.1 3.1 0 0 1-2.6-1.4" />
    </>
  ),
  trend: (
    <>
      <path d="M3.5 16.5 9 11l4 4 7.5-7.5" />
      <path d="M15.5 7.5h5v5" />
    </>
  ),
  box: (
    <>
      <path d="M3.5 7.5 12 3.5l8.5 4v9L12 20.5l-8.5-4Z" />
      <path d="M3.5 7.5 12 11.7l8.5-4.2" />
      <path d="M12 11.7v8.8" />
    </>
  ),
  leaf: (
    <>
      <path d="M5 19c0-7 4.5-12 15-12 0 8-4.5 12.5-11 12.5" />
      <path d="M5 19c3-4 6-6 9-7" />
    </>
  ),
  truck: (
    <>
      <path d="M3.5 6.5h10v9.5h-10z" />
      <path d="M13.5 9.5h4l3 3v3.5h-7z" />
      <circle cx="7" cy="18" r="1.7" />
      <circle cx="17" cy="18" r="1.7" />
    </>
  ),
  gear: (
    <>
      <circle cx="12" cy="12" r="3.2" />
      <path d="M12 3.5v2.2M12 18.3v2.2M4.8 7.8l1.9 1.1M17.3 15.1l1.9 1.1M4.8 16.2l1.9-1.1M17.3 8.9l1.9-1.1" />
    </>
  ),
  logout: (
    <>
      <path d="M14 7.5V5.2A1.7 1.7 0 0 0 12.3 3.5H5.7A1.7 1.7 0 0 0 4 5.2v13.6a1.7 1.7 0 0 0 1.7 1.7h6.6a1.7 1.7 0 0 0 1.7-1.7v-2.3" />
      <path d="M9.5 12h10.5" />
      <path d="M17 9l3 3-3 3" />
    </>
  ),
  panel: (
    <>
      <rect x="3.5" y="4.5" width="17" height="15" rx="2" />
      <path d="M10 4.5v15" />
    </>
  ),
};

function NavIcon({ name }) {
  return (
    <svg
      className="nav-icon"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {ICON_PATHS[name] || ICON_PATHS.grid}
    </svg>
  );
}

/* Below this width the sidebar stops being furniture and becomes a drawer.
   Kept here rather than only in CSS because the collapse toggle and the
   drawer share the same threshold, and the two must not drift apart. */
const DRAWER_BREAKPOINT = 1080;

function useIsNarrow() {
  const [isNarrow, setIsNarrow] = useState(
    () => window.innerWidth <= DRAWER_BREAKPOINT,
  );

  useEffect(() => {
    const onResize = () => setIsNarrow(window.innerWidth <= DRAWER_BREAKPOINT);

    window.addEventListener("resize", onResize);

    return () => window.removeEventListener("resize", onResize);
  }, []);

  return isNarrow;
}

function AppShell({
  user,
  role = "admin",
  navItems,
  currentPage,
  onNavigate,
  onLogout,
  sectionLabel,
  pageTitle,
  pageSubtitle,
  pageEyebrow,
  actions,
  banner,
  children,
}) {
  const isNarrow = useIsNarrow();
  const [collapsed, setCollapsed] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const navRef = useRef(null);

  // A collapsed rail is meaningless once the sidebar is a drawer, so the
  // rail state is simply ignored below the breakpoint rather than being
  // synchronised back to false: deriving it costs nothing and cannot leave
  // the two states disagreeing.
  const railCollapsed = collapsed && !isNarrow;

  // Escape closes the drawer, and the page behind it must not scroll while
  // the drawer is over it.
  useEffect(() => {
    if (!drawerOpen) return undefined;

    const onKey = (event) => {
      if (event.key === "Escape") setDrawerOpen(false);
    };

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    document.addEventListener("keydown", onKey);

    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", onKey);
    };
  }, [drawerOpen]);

  // The active item is moved into view on a narrow screen, where the rail
  // is taller than the viewport.
  useEffect(() => {
    if (!isNarrow) return;

    navRef.current
      ?.querySelector('[aria-current="page"]')
      ?.scrollIntoView({ block: "nearest" });
  }, [currentPage, isNarrow]);

  const handleNavigate = (key) => {
    onNavigate(key);

    // On a drawer the navigation has done its job once the page is chosen,
    // so the drawer closes rather than covering what was just opened.
    if (isNarrow) setDrawerOpen(false);
  };

  // Grouped, in the order the groups first appear. A flat list of seventeen
  // items reads as a settings dump; six labelled groups read as a room.
  const groups = [];
  navItems.forEach((item) => {
    const groupName = item.group || "";

    let group = groups.find((entry) => entry.name === groupName);

    if (!group) {
      group = { name: groupName, items: [] };
      groups.push(group);
    }

    group.items.push(item);
  });

  const roleLabel = role === "admin" ? "Administrator" : "Guest";
  const initial = (user?.name || "G").trim().charAt(0).toUpperCase();

  return (
    <div
      className={[
        "shell-root",
        `shell-${role}`,
        railCollapsed ? "shell-collapsed" : "",
        drawerOpen ? "shell-drawer-open" : "",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <button
        type="button"
        className="shell-scrim"
        onClick={() => setDrawerOpen(false)}
        aria-label="Close navigation"
        tabIndex={drawerOpen ? 0 : -1}
      />

      <aside className="shell-sidebar" aria-label={`${roleLabel} navigation`}>
        <div className="shell-brand">
          <div className="shell-brand-mark" aria-hidden="true">
            P
          </div>

          <div className="shell-brand-text">
            <strong>PARADISE</strong>
            <span>AI-Powered Restaurant</span>
          </div>

          {/* Only rendered as a drawer below the breakpoint, where the
              utility row carries the same control. */}
          <button
            type="button"
            className="shell-drawer-close"
            onClick={() => setDrawerOpen(false)}
            aria-label="Close navigation"
            tabIndex={isNarrow ? 0 : -1}
          >
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              aria-hidden="true"
            >
              <path d="M6 6l12 12M18 6 6 18" />
            </svg>
          </button>
        </div>

        <nav className="shell-nav" ref={navRef} aria-label="Main">
          {groups.map((group) => (
            <div className="shell-nav-group" key={group.name || "main"}>
              {group.name && (
                <p className="shell-nav-group-label">{group.name}</p>
              )}

              {group.items.map((item) => {
                const isActive = currentPage === item.key;

                return (
                  <button
                    key={item.key}
                    type="button"
                    className={
                      isActive ? "shell-nav-item is-active" : "shell-nav-item"
                    }
                    onClick={() => handleNavigate(item.key)}
                    aria-current={isActive ? "page" : undefined}
                    // The label is hidden on the collapsed rail, so the
                    // tooltip carries the name. It is also the title on a
                    // drawer, where a hover is not available.
                    data-tip={item.label}
                    title={isNarrow ? item.label : undefined}
                  >
                    <NavIcon name={item.icon} />

                    <span className="shell-nav-copy">
                      <span className="shell-nav-label">{item.label}</span>

                      {item.description && (
                        <span className="shell-nav-hint">
                          {item.description}
                        </span>
                      )}
                    </span>

                    {item.badge > 0 && (
                      <span className="shell-nav-badge">
                        {item.badge > 99 ? "99+" : item.badge}
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          ))}
        </nav>

        <div className="shell-account">
          <div className="shell-account-card">
            <span className="shell-account-avatar" aria-hidden="true">
              {initial}
            </span>

            <span className="shell-account-copy">
              <strong>{user?.name || "Guest"}</strong>
              <span>{roleLabel}</span>
            </span>
          </div>

          <button
            type="button"
            className="shell-signout"
            onClick={onLogout}
            data-tip="Sign out"
          >
            <NavIcon name="logout" />

            <span className="shell-nav-label">Sign out</span>
          </button>
        </div>
      </aside>

      <div className="shell-main">
        {/* A utility row, not a navigation bar: the drawer button, where
            you are, and who you are. All navigation lives in the sidebar. */}
        <div className="shell-utility">
          <button
            type="button"
            className="shell-menu-button"
            onClick={() => setDrawerOpen(true)}
            aria-label="Open navigation"
            aria-expanded={drawerOpen}
          >
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              aria-hidden="true"
            >
              <path d="M4 7h16M4 12h16M4 17h10" />
            </svg>
          </button>

          <p className="shell-utility-section">{sectionLabel}</p>

          <div className="shell-utility-tools">
            {actions}

            <button
              type="button"
              className="shell-collapse"
              onClick={() => setCollapsed((value) => !value)}
              aria-label={railCollapsed ? "Expand sidebar" : "Collapse sidebar"}
              aria-pressed={railCollapsed}
            >
              {/* A single rule that rotates into an arrow. In the collapsed
                  rail the same control points the other way. */}
              <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <rect x="3.5" y="4.5" width="17" height="15" rx="2" />
                <path d="M10 4.5v15" />
                <path d="M16 9.5 13.5 12 16 14.5" />
              </svg>
            </button>
          </div>
        </div>

        <main className="shell-content" id="main-content">
          <div className="shell-page">
            {pageTitle && (
              <div className="shell-page-head">
                <div className="shell-page-headings">
                  {pageEyebrow && (
                    <p className="shell-eyebrow">{pageEyebrow}</p>
                  )}

                  <h1 className="shell-page-title">{pageTitle}</h1>

                  {pageSubtitle && (
                    <p className="shell-page-subtitle">{pageSubtitle}</p>
                  )}
                </div>

                {actions && <div className="shell-page-actions">{actions}</div>}
              </div>
            )}

            {banner}

            {children}
          </div>
        </main>
      </div>
    </div>
  );
}

export default AppShell;

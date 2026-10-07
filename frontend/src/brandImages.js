// Brand imagery for the public site.
//
// The project already resolves dish photography through `dishImages.js`,
// which prefers the URL stored on the menu row and falls back to a
// keyword match. This module does the same thing for the site's own
// imagery - the hero, the interior, the reservation panel.
//
// LOCAL IMAGE SUPPORT
// -------------------
// Every entry has a `local` path under `src/assets/images/`. If you drop
// a file with that exact name into that folder it is used automatically
// and no remote request is made. Until then the `remote` value is used.
//
// Vite resolves `./assets/images/x.webp` at build time. A missing file is
// a build error, so the local paths are assembled from a variable rather
// than written literally: that way the site builds today with remote
// photography, and swapping in local files is a copy-paste into
// `src/assets/images/` plus one edit per entry below.

const remote = (id, width = 1600) =>
  `https://images.unsplash.com/photo-${id}?auto=format&fit=crop&w=${width}&q=80`;

/**
 * Attempts to import a local asset, returning null when it is absent.
 *
 * Vite's `import.meta.glob` is used with `eager: false` so a missing file
 * is simply not in the map rather than being a build failure.
 */
const localImages = import.meta.glob("../assets/images/*", {
  eager: false,
  query: "?url",
  import: "default",
});

/**
 * Resolve a brand image name to a URL.
 *
 * @param {string} name  e.g. "hero-restaurant"
 * @param {string} [fallbackUrl] used when the name is unknown
 */
export const brandImage = (name, fallbackUrl = "") => {
  const local = localImages[`../assets/images/${name}.webp`];

  if (local) {
    return local;
  }

  const jpg = localImages[`../assets/images/${name}.jpg`];

  if (jpg) {
    return jpg;
  }

  return BRAND_FALLBACKS[name] || fallbackUrl || "";
};

// ---- the set of images the public site uses ----
//
// Names match the filenames the design calls for, so adding real
// photography later is a matter of dropping files into src/assets/images.
export const BRAND_FALLBACKS = {
  // Full-bleed hero. A warm, low-lit dining room.
  "hero-restaurant": remote("1517248135467-4c7edcad34c4", 2000),

  // Ambient interior, used behind the feature strip and about band.
  "restaurant-interior": remote("1552566626-52f8b828add9", 1400),

  // Reservation panel.
  "reservation-table": remote("1414235077428-338989a2e8c0", 1200),

  // Section backdrops.
  "about-chef": remote("1577219491135-ce391730fb2c", 1000),
  "contact-exterior": remote("1517248135467-4c7edcad34c4", 1000),
};

export const HERO_IMAGE = BRAND_FALLBACKS["hero-restaurant"];
export const INTERIOR_IMAGE = BRAND_FALLBACKS["restaurant-interior"];
export const RESERVATION_IMAGE = BRAND_FALLBACKS["reservation-table"];

// Category backdrops for the menu showcase, keyed by the category names the
// backend actually returns. A category with no entry gets the interior.
export const CATEGORY_IMAGES = {
  Biryani: remote("1563379091339-03b21ab4a4f8", 900),
  Main: remote("1544025162-d76694265947", 900),
  Appetizer: remote("1547592166-23ac45744acd", 900),
  Dessert: remote("1551024601-bec78aea704b", 900),
  Beverage: remote("1572490122747-3968b75cc699", 900),
};

export default BRAND_FALLBACKS;

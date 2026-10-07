// Shared dish image helpers.
//
// The backend stores an image URL on every menu item (either an
// uploaded file under /static/menu or a remote URL). These helpers
// resolve that value into something renderable and fall back to a
// matching stock photo when a dish has no image yet.

const API_BASE =
  import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

const stock = (id) =>
  `https://images.unsplash.com/photo-${id}?auto=format&fit=crop&w=700&q=80`;

export const FALLBACK_DISH_IMAGE =
  "https://images.unsplash.com/photo-1544025162-d76694265947?auto=format&fit=crop&w=600&q=80";

// Images used when an admin saves a dish without picking a photo.
export const DISH_IMAGE_LIBRARY = {
  "Chicken Biryani":
    "https://images.unsplash.com/photo-1631452180519-c014fe946bc7?auto=format&fit=crop&w=600&q=80",
  "Mutton Biryani":
    "https://images.unsplash.com/photo-1604908176997-125e7c0d7f0f?auto=format&fit=crop&w=600&q=80",
  "Hyderabadi Chicken Dum Biryani":
    "https://images.unsplash.com/photo-1563379091339-03b21ab4a4f8?auto=format&fit=crop&w=600&q=80",
  "Paneer Butter Masala":
    "https://images.unsplash.com/photo-1603894584373-5ac82b2ae398?auto=format&fit=crop&w=600&q=80",
  "Butter Chicken":
    "https://images.unsplash.com/photo-1603894584373-5ac82b2ae398?auto=format&fit=crop&w=600&q=80",
  "Veg Fried Rice":
    "https://images.unsplash.com/photo-1512058564366-18510be2db19?auto=format&fit=crop&w=600&q=80",
  "Masala Dosa":
    "https://images.unsplash.com/photo-1601050690597-df0568f70950?auto=format&fit=crop&w=600&q=80",
  "Idli Sambar":
    "https://images.unsplash.com/photo-1589302168068-964664d93dc0?auto=format&fit=crop&w=600&q=80",
  "Chicken 65":
    "https://images.unsplash.com/photo-1604908556856-b7a6c479f62d?auto=format&fit=crop&w=600&q=80",
  "Gobi Manchurian":
    "https://images.unsplash.com/photo-1547592166-23ac45744acd?auto=format&fit=crop&w=600&q=80",
  "Gulab Jamun":
    "https://images.unsplash.com/photo-1601055654745-9f7d84fbb0d7?auto=format&fit=crop&w=600&q=80",
  "Filter Coffee":
    "https://images.unsplash.com/photo-1498804103079-a6351b050096?auto=format&fit=crop&w=600&q=80",
  "Veg Samosa":
    "https://images.unsplash.com/photo-1601050690117-94f5f6fa8bd7?auto=format&fit=crop&w=600&q=80",
  "Choco Brownie":
    "https://images.unsplash.com/photo-1606313564200-e75d5e30476c?auto=format&fit=crop&w=600&q=80",
  "Margherita Pizza":
    "https://images.unsplash.com/photo-1574071318508-1cdbab80d002?auto=format&fit=crop&w=600&q=80",
  "Pepperoni Pizza":
    "https://images.unsplash.com/photo-1565299624946-b28f40a0ae38?auto=format&fit=crop&w=600&q=80",
  "Garlic Bread":
    "https://images.unsplash.com/photo-1573140401552-3fab0b24306f?auto=format&fit=crop&w=600&q=80",
  "Caesar Salad":
    "https://images.unsplash.com/photo-1546793665-c74683f339c1?auto=format&fit=crop&w=600&q=80",
  "Tiramisu":
    "https://images.unsplash.com/photo-1571877227200-a0d98ea607e9?auto=format&fit=crop&w=600&q=80",
  Cappuccino: stock("1572442388796-11668a67e53d"),
  Milkshake: stock("1572490122747-3968b75cc699"),
};

// Keywords used to guess a photo for an unknown dish name.
const KEYWORD_IMAGES = [
  ["biryani", "https://images.unsplash.com/photo-1563379091339-03b21ab4a4f8?auto=format&fit=crop&w=600&q=80"],
  ["pizza", "https://images.unsplash.com/photo-1574071318508-1cdbab80d002?auto=format&fit=crop&w=600&q=80"],
  ["burger", "https://images.unsplash.com/photo-1568901346375-23c9450c58cd?auto=format&fit=crop&w=600&q=80"],
  ["pasta", "https://images.unsplash.com/photo-1621996346565-e3dbc646d9a9?auto=format&fit=crop&w=600&q=80"],
  ["salad", "https://images.unsplash.com/photo-1546793665-c74683f339c1?auto=format&fit=crop&w=600&q=80"],
  ["soup", "https://images.unsplash.com/photo-1547592166-23ac45744acd?auto=format&fit=crop&w=600&q=80"],
  ["dessert", "https://images.unsplash.com/photo-1551024601-bec78aea704b?auto=format&fit=crop&w=600&q=80"],
  ["cake", "https://images.unsplash.com/photo-1578985545062-69928b1d9587?auto=format&fit=crop&w=600&q=80"],
  ["coffee", "https://images.unsplash.com/photo-1498804103079-a6351b050096?auto=format&fit=crop&w=600&q=80"],
  ["tea", "https://images.unsplash.com/photo-1556679343-c7306c1976bc?auto=format&fit=crop&w=600&q=80"],
  ["juice", "https://images.unsplash.com/photo-1621263764928-df1444c5e859?auto=format&fit=crop&w=600&q=80"],
  ["rice", "https://images.unsplash.com/photo-1512058564366-18510be2db19?auto=format&fit=crop&w=600&q=80"],
  ["chicken", "https://images.unsplash.com/photo-1604908556856-b7a6c479f62d?auto=format&fit=crop&w=600&q=80"],
  ["fish", "https://images.unsplash.com/photo-1544943910-4c1dc44aab44?auto=format&fit=crop&w=600&q=80"],
  ["dosa", "https://images.unsplash.com/photo-1601050690597-df0568f70950?auto=format&fit=crop&w=600&q=80"],
];

// Turns an uploaded file path such as "/static/menu/ab12.png" into
// an absolute URL the browser can load.
export const resolveImageUrl = (imageUrl) => {
  if (!imageUrl) {
    return "";
  }

  if (imageUrl.startsWith("http://") || imageUrl.startsWith("https://")) {
    return imageUrl;
  }

  if (imageUrl.startsWith("/static/")) {
    return API_BASE.replace(/\/$/, "") + imageUrl;
  }

  return imageUrl;
};

// Accepts a menu item or a bare dish name and returns a usable URL.
export const getDishImage = (source) => {
  const name =
    typeof source === "string"
      ? source
      : source?.name ?? source?.menu_item ?? "";

  const stored = typeof source === "string" ? "" : source?.image_url;

  const resolved = resolveImageUrl(stored);

  if (resolved) {
    return resolved;
  }

  if (DISH_IMAGE_LIBRARY[name]) {
    return DISH_IMAGE_LIBRARY[name];
  }

  const lower = name.toLowerCase();

  const keywordMatch = KEYWORD_IMAGES.find(([keyword]) =>
    lower.includes(keyword)
  );

  if (keywordMatch) {
    return keywordMatch[1];
  }

  return FALLBACK_DISH_IMAGE;
};

// A menu item may declare is_vegetarian; older rows do not, so fall
// back to reading the dish name.
export const isVegItem = (item) => {
  if (typeof item?.is_vegetarian === "boolean") {
    return item.is_vegetarian;
  }

  const nonVegKeywords = [
    "chicken",
    "mutton",
    "fish",
    "meat",
    "prawn",
    "egg",
    "beef",
    "pork",
    "wings",
    "steak",
  ];

  const lower =
    ((item?.name ?? "") + " " + (item?.category ?? "")).toLowerCase();

  return !nonVegKeywords.some((keyword) => lower.includes(keyword));
};

export const spiceLabel = (level) => {
  const value = Number(level) || 0;

  if (value >= 3) return "Extra Hot";
  if (value === 2) return "Spicy";
  if (value === 1) return "Mild";
  return "Not Spicy";
};
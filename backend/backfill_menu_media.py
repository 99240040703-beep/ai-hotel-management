"""
Backfill dish photos and details on menu rows that already exist.

seed_data.py only inserts when the table is empty, so an existing
database keeps its original dishes with blank image_url /
description values. This script fills those in by matching the dish
name against a reference catalogue, and gives anything unknown a
category-based photo.

    cd backend
    python backfill_menu_media.py

Add --force to overwrite rows that already have an image.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from database import SessionLocal
from models import Menu


# name -> (image, description, is_vegetarian, spice_level, prep_time)
CATALOGUE = {
    "Chicken Biryani": (
        "https://images.unsplash.com/photo-1631452180519-c014fe946bc7?auto=format&fit=crop&w=600&q=80",
        "Fragrant basmati layered with slow-cooked chicken and saffron milk.",
        False, 2, 25,
    ),
    "Mutton Biryani": (
        "https://images.unsplash.com/photo-1604908176997-125e7c0d7f0f?auto=format&fit=crop&w=600&q=80",
        "Tender mutton shank braised in biryani masala with long grain rice.",
        False, 3, 30,
    ),
    "Hyderabadi Chicken Dum Biryani": (
        "https://images.unsplash.com/photo-1563379091339-03b21ab4a4f8?auto=format&fit=crop&w=600&q=80",
        "Sealed-pot biryani with tender chicken, saffron and fried onions.",
        False, 3, 35,
    ),
    "Paneer Butter Masala": (
        "https://images.unsplash.com/photo-1603894584373-5ac82b2ae398?auto=format&fit=crop&w=600&q=80",
        "Soft paneer cubes in a rich tomato and cashew gravy finished with cream.",
        True, 1, 18,
    ),
    "Butter Chicken": (
        "https://images.unsplash.com/photo-1603894584373-5ac82b2ae398?auto=format&fit=crop&w=600&q=80",
        "Tandoor-roasted chicken folded into a mild tomato and butter gravy.",
        False, 1, 20,
    ),
    "Veg Fried Rice": (
        "https://images.unsplash.com/photo-1512058564366-18510be2db19?auto=format&fit=crop&w=600&q=80",
        "Wok-tossed rice with crisp vegetables, spring onion and a light seasoning.",
        True, 1, 15,
    ),
    "Masala Dosa": (
        "https://images.unsplash.com/photo-1601050690597-df0568f70950?auto=format&fit=crop&w=600&q=80",
        "Paper-thin fermented dosa served with potato palya and coconut chutney.",
        True, 1, 12,
    ),
    "Idli Sambar": (
        "https://images.unsplash.com/photo-1589302168068-964664d93dc0?auto=format&fit=crop&w=600&q=80",
        "Steamed rice cakes dunked in a hot sambar and served with two chutneys.",
        True, 1, 8,
    ),
    "Chicken 65": (
        "https://images.unsplash.com/photo-1604908556856-b7a6c479f62d?auto=format&fit=crop&w=600&q=80",
        "Crisp fried chicken tossed with curry leaf, chilli and yoghurt.",
        False, 3, 14,
    ),
    "Gobi Manchurian": (
        "https://images.unsplash.com/photo-1547592166-23ac45744acd?auto=format&fit=crop&w=600&q=80",
        "Crisp cauliflower in a tangy garlic soy glaze, served dry or saucy.",
        True, 2, 13,
    ),
    "Gulab Jamun": (
        "https://images.unsplash.com/photo-1601055654745-9f7d84fbb0d7?auto=format&fit=crop&w=600&q=80",
        "Warm milk dumplings soaked in cardamom sugar syrup.",
        True, 0, 5,
    ),
    "Filter Coffee": (
        "https://images.unsplash.com/photo-1498804103079-a6351b050096?auto=format&fit=crop&w=600&q=80",
        "South Indian decoction blended with hot milk and poured tall.",
        True, 0, 4,
    ),
    "Veg Samosa": (
        "https://images.unsplash.com/photo-1601050690117-94f5f6fa8bd7?auto=format&fit=crop&w=600&q=80",
        "Flaky pastry triangles packed with spiced potato peas.",
        True, 1, 9,
    ),
    "Choco Brownie": (
        "https://images.unsplash.com/photo-1606313564200-e75d5e30476c?auto=format&fit=crop&w=600&q=80",
        "Fudgy dark chocolate brownie served warm with vanilla cream.",
        True, 0, 6,
    ),
    "Chicken Wings": (
        "https://images.unsplash.com/photo-1604908556856-b7a6c479f62d?auto=format&fit=crop&w=600&q=80",
        "Oven baked wings glazed in sticky hot honey and lime.",
        False, 2, 20,
    ),
    "Fish & Chips": (
        "https://images.unsplash.com/photo-1544943910-4c1dc44aab44?auto=format&fit=crop&w=600&q=80",
        "Beer-battered fillet with hand-cut chips and mushy peas.",
        False, 1, 20,
    ),
    "Steak Frites": (
        "https://images.unsplash.com/photo-1546833999-b9f581a1996d?auto=format&fit=crop&w=600&q=80",
        "Grilled sirloin with crisp fries and a peppercorn sauce.",
        False, 0, 25,
    ),
    "Chocolate Milkshake": (
        "https://images.unsplash.com/photo-1572490122747-3968b75cc699?auto=format&fit=crop&w=600&q=80",
        "Thick chocolate shake topped with whipped cream and cocoa.",
        True, 0, 6,
    ),
    "Margherita Pizza": (
        "https://images.unsplash.com/photo-1574071318508-1cdbab80d002?auto=format&fit=crop&w=600&q=80",
        "Stone-baked base, San Marzano tomato and torn mozzarella with basil.",
        True, 0, 14,
    ),
    "Pepperoni Pizza": (
        "https://images.unsplash.com/photo-1565299624946-b28f40a0ae38?auto=format&fit=crop&w=600&q=80",
        "Crisp pepperoni cups over a double mozzarella and oregano base.",
        False, 1, 14,
    ),
    "Garlic Bread": (
        "https://images.unsplash.com/photo-1573140401552-3fab0b24306f?auto=format&fit=crop&w=600&q=80",
        "Buttered baguette slices baked with garlic parsley and parmesan.",
        True, 0, 8,
    ),
    "Caesar Salad": (
        "https://images.unsplash.com/photo-1546793665-c74683f339c1?auto=format&fit=crop&w=600&q=80",
        "Cos lettuce, shaved parmesan and croutons in a classic dressing.",
        True, 0, 7,
    ),
    "Tiramisu": (
        "https://images.unsplash.com/photo-1571877227200-a0d98ea607e9?auto=format&fit=crop&w=600&q=80",
        "Espresso soaked savoiardi layered with mascarpone cream.",
        True, 0, 5,
    ),
    "Cappuccino": (
        "https://images.unsplash.com/photo-1572442388796-11668a67e53d?auto=format&fit=crop&w=600&q=80",
        "Double espresso steamed milk under a thick velvet foam.",
        True, 0, 3,
    ),
}

# Used for dishes that are not in the catalogue above.
CATEGORY_FALLBACK = {
    "Starter": "https://images.unsplash.com/photo-1547592166-23ac45744acd?auto=format&fit=crop&w=600&q=80",
    "Appetizer": "https://images.unsplash.com/photo-1547592166-23ac45744acd?auto=format&fit=crop&w=600&q=80",
    "Main Course": "https://images.unsplash.com/photo-1544025162-d76694265947?auto=format&fit=crop&w=600&q=80",
    "Main": "https://images.unsplash.com/photo-1544025162-d76694265947?auto=format&fit=crop&w=600&q=80",
    "South Indian": "https://images.unsplash.com/photo-1601050690597-df0568f70950?auto=format&fit=crop&w=600&q=80",
    "Dessert": "https://images.unsplash.com/photo-1551024601-bec78aea704b?auto=format&fit=crop&w=600&q=80",
    "Beverage": "https://images.unsplash.com/photo-1498804103079-a6351b050096?auto=format&fit=crop&w=600&q=80",
}

GENERIC_IMAGE = "https://images.unsplash.com/photo-1544025162-d76694265947?auto=format&fit=crop&w=600&q=80"


def backfill(force: bool = False) -> None:
    db = SessionLocal()

    try:
        items = db.query(Menu).all()

        if not items:
            print("Menu table is empty - nothing to backfill.")
            print("Run 'python seed_data.py' to insert the demo dishes.")
            return

        updated = 0
        skipped = 0

        for item in items:
            # A row that already carries a photo was set up by hand,
            # so leave it alone unless --force was passed.
            if item.image_url and not force:
                skipped += 1
                continue

            entry = CATALOGUE.get(item.name)

            if entry:
                image, description, veg, spice, prep = entry

                item.image_url = image
                item.description = description
                item.is_vegetarian = veg
                item.spice_level = spice
                item.prep_time = prep
            else:
                # Unknown dish: only supply a photo, keep its own details.
                item.image_url = CATEGORY_FALLBACK.get(
                    item.category, GENERIC_IMAGE
                )

                if not item.prep_time:
                    item.prep_time = 15

            updated += 1

        db.commit()

        print(f"Updated {updated} menu item(s), skipped {skipped} that already had a photo.")
    finally:
        db.close()


if __name__ == "__main__":
    backfill(force="--force" in sys.argv)
"""Seed the menu table with a ready-to-browse set of dishes.

Each dish carries an image, a short description and the dietary /
prep metadata used by the customer menu and the admin menu screen:

    python seed_menu.py
"""

import random

from database import SessionLocal
from models import Menu

# name, category, price, image, description, veg, featured, spice, prep(min)
SAMPLE_DISHES = [
    ("Margherita Pizza", "Main", 280,
     "https://images.unsplash.com/photo-1574071318508-1cdbab80d002?auto=format&fit=crop&w=600&q=80",
     "Stone-baked base, San Marzano tomato and torn mozzarella with basil.",
     True, True, 0, 14),
    ("Pepperoni Pizza", "Main", 340,
     "https://images.unsplash.com/photo-1565299624946-b28f40a0ae38?auto=format&fit=crop&w=600&q=80",
     "Crisp pepperoni cups over a double mozzarella and oregano base.",
     False, True, 1, 14),
    ("BBQ Chicken Pizza", "Main", 380,
     "https://images.unsplash.com/photo-1579751626657-72bc17010498?auto=format&fit=crop&w=600&q=80",
     "Smoked barbecue chicken, red onion and sweetcorn on a thin crust.",
     False, False, 2, 16),
    ("Veggie Supreme", "Main", 320,
     "https://images.unsplash.com/photo-1593560708920-61dd98c46a4e?auto=format&fit=crop&w=600&q=80",
     "Roast peppers, courgette, olives and artichoke with a herb dressing.",
     True, False, 0, 15),
    ("Four Cheese Pizza", "Main", 400,
     "https://images.unsplash.com/photo-1548365328-8b849e6c7b26?auto=format&fit=crop&w=600&q=80",
     "Mozzarella, gorgonzola, smoked cheddar and parmesan melted together.",
     True, False, 0, 15),
    ("Garlic Bread", "Appetizer", 180,
     "https://images.unsplash.com/photo-1573140401552-3fab0b24306f?auto=format&fit=crop&w=600&q=80",
     "Buttered baguette slices baked with garlic parsley and parmesan.",
     True, False, 0, 8),
    ("Bruschetta", "Appetizer", 240,
     "https://images.unsplash.com/photo-1547592180-85f173990554?auto=format&fit=crop&w=600&q=80",
     "Grilled sourdough topped with tomato, garlic and fresh basil.",
     True, False, 0, 7),
    ("Caesar Salad", "Appetizer", 300,
     "https://images.unsplash.com/photo-1546793665-c74683f339c1?auto=format&fit=crop&w=600&q=80",
     "Cos lettuce, shaved parmesan and croutons in a classic dressing.",
     True, False, 0, 7),
    ("Caprese Salad", "Appetizer", 320,
     "https://images.unsplash.com/photo-1592417817098-8fd3d9eb14a5?auto=format&fit=crop&w=600&q=80",
     "Tomato, buffalo mozzarella and basil with aged balsamic.",
     True, False, 0, 7),
    ("Greek Salad", "Appetizer", 280,
     "https://images.unsplash.com/photo-1540420773420-3366772f4999?auto=format&fit=crop&w=600&q=80",
     "Tomato, cucumber, olives and feta with oregano and olive oil.",
     True, False, 0, 6),
    ("Spaghetti Bolognese", "Main", 420,
     "https://images.unsplash.com/photo-1622973536968-3ead9e780960?auto=format&fit=crop&w=600&q=80",
     "Hand-cut spaghetti slow-cooked in a rich beef and tomato ragù.",
     False, False, 1, 22),
    ("Fettuccine Alfredo", "Main", 450,
     "https://images.unsplash.com/photo-1621996346565-e3dbc646d9a9?auto=format&fit=crop&w=600&q=80",
     "Silky ribbon pasta in a parmesan cream sauce with cracked pepper.",
     True, False, 0, 18),
    ("Lasagna", "Main", 480,
     "https://images.unsplash.com/photo-1614895090293-ab1100badc2b?auto=format&fit=crop&w=600&q=80",
     "Layered pasta sheets with beef ragù, béchamel and mozzarella.",
     False, False, 1, 26),
    ("Ravioli", "Main", 460,
     "https://images.unsplash.com/photo-1551183053-bf91a1d81141?auto=format&fit=crop&w=600&q=80",
     "Pasta pillows filled with ricotta and spinach in a brown butter sauce.",
     True, False, 0, 19),
    ("Minestrone Soup", "Appetizer", 220,
     "https://images.unsplash.com/photo-1547592166-23ac45744acd?auto=format&fit=crop&w=600&q=80",
     "Seasonal vegetables and beans simmered in a light tomato broth.",
     True, False, 0, 10),
    ("Mushroom Soup", "Appetizer", 240,
     "https://images.unsplash.com/photo-1547592166-23ac45744acd?auto=format&fit=crop&w=600&q=80",
     "Creamy woodland mushroom soup finished with chives and cream.",
     True, False, 0, 10),
    ("Tiramisu", "Dessert", 320,
     "https://images.unsplash.com/photo-1571877227200-a0d98ea607e9?auto=format&fit=crop&w=600&q=80",
     "Espresso soaked savoiardi layered with mascarpone cream.",
     True, True, 0, 5),
    ("Cheesecake", "Dessert", 340,
     "https://images.unsplash.com/photo-1533134242443-d4fd215305ad?auto=format&fit=crop&w=600&q=80",
     "Baked vanilla cheesecake on a biscuit base with berry coulis.",
     True, False, 0, 5),
    ("Chocolate Brownie", "Dessert", 250,
     "https://images.unsplash.com/photo-1606313564200-e75d5e30476c?auto=format&fit=crop&w=600&q=80",
     "Fudgy dark chocolate brownie served warm with vanilla cream.",
     True, False, 0, 6),
    ("Panna Cotta", "Dessert", 280,
     "https://images.unsplash.com/photo-1488477181946-6428a0291777?auto=format&fit=crop&w=600&q=80",
     "Vanilla bean cream set soft, topped with a seasonal fruit coulis.",
     True, False, 0, 4),
    ("Lemon Sorbet", "Dessert", 180,
     "https://images.unsplash.com/photo-1497534446932-c925b458314e?auto=format&fit=crop&w=600&q=80",
     "Chilled lemon sorbet scooped with a mint sprig.",
     True, False, 0, 4),
    ("Cappuccino", "Beverage", 150,
     "https://images.unsplash.com/photo-1572442388796-11668a67e53d?auto=format&fit=crop&w=600&q=80",
     "Double espresso steamed milk under a thick velvet foam.",
     True, False, 0, 3),
    ("Espresso", "Beverage", 100,
     "https://images.unsplash.com/photo-1510707577719-ae7c14805e3a?auto=format&fit=crop&w=600&q=80",
     "A short, intense single-origin double shot.",
     True, False, 0, 2),
    ("Latte", "Beverage", 180,
     "https://images.unsplash.com/photo-1572442388796-11668a67e53d?auto=format&fit=crop&w=600&q=80",
     "Long espresso with textured milk, served hot or over ice.",
     True, False, 0, 3),
    ("Iced Tea", "Beverage", 120,
     "https://images.unsplash.com/photo-1556679343-c7306c1976bc?auto=format&fit=crop&w=600&q=80",
     "Black tea chilled over ice with lemon and a hint of mint.",
     True, False, 0, 3),
    ("Lemonade", "Beverage", 120,
     "https://images.unsplash.com/photo-1621263764928-df1444c5e859?auto=format&fit=crop&w=600&q=80",
     "Fresh pressed lemon sweetened and served over crushed ice.",
     True, False, 0, 3),
    ("Mojito Mocktail", "Beverage", 180,
     "https://images.unsplash.com/photo-1513558161293-cdaf765ed2fd?auto=format&fit=crop&w=600&q=80",
     "Alcohol-free lime, mint and soda with a sugar cane stirrer.",
     True, False, 0, 5),
    ("Chicken Wings", "Appetizer", 380,
     "https://images.unsplash.com/photo-1604908556856-b7a6c479f62d?auto=format&fit=crop&w=600&q=80",
     "Oven baked wings glazed in sticky hot honey and lime.",
     False, False, 2, 20),
    ("Fish & Chips", "Main", 420,
     "https://images.unsplash.com/photo-1544943910-4c1dc44aab44?auto=format&fit=crop&w=600&q=80",
     "Beer-battered fillet with hand-cut chips and mushy peas.",
     False, False, 1, 20),
    ("Steak Frites", "Main", 560,
     "https://images.unsplash.com/photo-1546833999-b9f581a1996d?auto=format&fit=crop&w=600&q=80",
     "Grilled sirloin with crisp fries and a peppercorn sauce.",
     False, True, 0, 25),
    ("Chocolate Milkshake", "Beverage", 220,
     "https://images.unsplash.com/photo-1572490122747-3968b75cc699?auto=format&fit=crop&w=600&q=80",
     "Thick chocolate shake topped with whipped cream and cocoa.",
     True, False, 0, 6),
    ("Apple Pie", "Dessert", 280,
     "https://images.unsplash.com/photo-1621743478914-cc8a86d7e7b5?auto=format&fit=crop&w=600&q=80",
     "Shortcrust apple pie served warm with vanilla ice cream.",
     True, False, 0, 5),
]


# Biryani and rice dishes. Kept as their own list so the same set can be
# added to an existing menu without wiping the dishes already there.
#
# name, category, price, image, description, veg, featured, spice, prep(min)
BIRYANI_DISHES = [
    ("Hyderabadi Chicken Dum Biryani", "Biryani", 420,
     "https://images.unsplash.com/photo-1563379091339-03b21ab4a4f8?auto=format&fit=crop&w=600&q=80",
     "Sealed-pot dum biryani with long-grain basmati, saffron and fried onions.",
     False, True, 3, 25),
    ("Tandoori Chicken Biryani", "Biryani", 450,
     "https://images.unsplash.com/photo-1631452180519-c014fe946bc7?auto=format&fit=crop&w=600&q=80",
     "Charred tandoori chicken folded into masala rice with mint chutney.",
     False, True, 3, 25),
    ("Mutton Biryani", "Biryani", 560,
     "https://images.unsplash.com/photo-1604908176997-125e7c0d7f0f?auto=format&fit=crop&w=600&q=80",
     "Slow-cooked mutton shank with whole spices and caramelised onion.",
     False, False, 3, 30),
    ("Hyderabadi Mutton Dum Biryani", "Biryani", 620,
     "https://images.unsplash.com/photo-1563379091339-03b21ab4a4f8?auto=format&fit=crop&w=600&q=80",
     "Restaurant-style dum biryani, serve for two with raita and salad.",
     False, False, 3, 32),
    ("Chicken Biryani", "Biryani", 320,
     "https://images.unsplash.com/photo-1631452180519-c014fe946bc7?auto=format&fit=crop&w=600&q=80",
     "Everyday chicken biryani with tomato masala and boiled egg.",
     False, False, 2, 22),
    ("Chicken Fried Rice", "Biryani", 320,
     "https://images.unsplash.com/photo-1512058564366-18510be2db19?auto=format&fit=crop&w=600&q=80",
     "Wok-tossed rice with shredded chicken, spring onion and soy.",
     False, False, 2, 18),
    ("Paneer Biryani", "Biryani", 340,
     "https://images.unsplash.com/photo-1563379091339-03b21ab4a4f8?auto=format&fit=crop&w=600&q=80",
     "Soft paneer cubes, cashew and raisin biryani finished in ghee.",
     True, False, 2, 22),
    ("Mushroom Biryani", "Biryani", 330,
     "https://images.unsplash.com/photo-1512058564366-18510be2db19?auto=format&fit=crop&w=600&q=80",
     "Button mushrooms and shallots in a lightly spiced dum finish.",
     True, False, 1, 22),
    ("Kashmiri Pulao", "Biryani", 350,
     "https://images.unsplash.com/photo-1563379091339-03b21ab4a4f8?auto=format&fit=crop&w=600&q=80",
     "Saffron long-grain rice with fried cashew, almond and raisin.",
     True, False, 1, 22),
    ("Egg Biryani", "Biryani", 300,
     "https://images.unsplash.com/photo-1631452180519-c014fe946bc7?auto=format&fit=crop&w=600&q=80",
     "Boiled egg buried in spiced rice with fried onion and lemon.",
     False, False, 2, 20),
    ("Veg Dum Biryani", "Biryani", 300,
     "https://images.unsplash.com/photo-1512058564366-18510be2db19?auto=format&fit=crop&w=600&q=80",
     "Seasonal vegetables layered with rice and slow-cooked on dum.",
     True, False, 1, 20),
    ("Veg Biryani", "Biryani", 280,
     "https://images.unsplash.com/photo-1563379091339-03b21ab4a4f8?auto=format&fit=crop&w=600&q=80",
     "Fragrant basmati with mixed vegetables and mint coriander.",
     True, False, 1, 20),
    ("Jeera Rice", "Biryani", 150,
     "https://images.unsplash.com/photo-1512058564366-18510be2db19?auto=format&fit=crop&w=600&q=80",
     "Basmati tempered with cumin, curry leaf and ghee.",
     True, False, 0, 15),
    ("Veg Fried Rice", "Biryani", 240,
     "https://images.unsplash.com/photo-1512058564366-18510be2db19?auto=format&fit=crop&w=600&q=80",
     "Wok-tossed rice with carrot, beans and spring onion.",
     True, False, 1, 16),
    ("Biryani Combo Platter for Two", "Biryani", 680,
     "https://images.unsplash.com/photo-1563379091339-03b21ab4a4f8?auto=format&fit=crop&w=600&q=80",
     "Two chicken biryanis, raita, salad and gulab jamun.",
     False, False, 2, 30),
]


def seed_menu(reset=False):
    """Insert any missing dish.

    Matches on the dish name, so running this twice is safe and a menu
    that is already stocked only gains the new dishes. Pass reset=True to
    wipe the table first and rebuild it from SAMPLE_DISHES.
    """
    db = SessionLocal()

    try:
        if reset:
            db.query(Menu).delete()
            db.commit()

        added = 0
        existing = {row.name for row in db.query(Menu).all()}

        for dish in SAMPLE_DISHES + BIRYANI_DISHES:
            (
                name, category, price, image_url, description,
                is_vegetarian, is_featured, spice_level, prep_time,
            ) = dish

            if name in existing:
                continue

            db.add(Menu(
                name=name,
                category=category,
                price=price,
                image_url=image_url,
                description=description,
                is_vegetarian=is_vegetarian,
                is_featured=is_featured,
                spice_level=spice_level,
                prep_time=prep_time,
                available=True,
            ))

            existing.add(name)
            added += 1

        db.commit()

        total = db.query(Menu).count()

        print(f"Added {added} new menu item(s). Menu now has {total} items.")

        return added

    finally:
        db.close()


if __name__ == "__main__":
    random.seed(42)

    seed_menu()

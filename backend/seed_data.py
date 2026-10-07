"""
Seed the database with 60 days of demo data.

ML models cannot learn from an empty table - run this once before
opening the AI Insights page:

    python seed_data.py
"""

import random
from datetime import datetime, timedelta

from database import SessionLocal, engine, Base
from models import (
    Menu, Order, Customer, Inventory, Review, Supplier,
    Staff, Waste, Reservation,
)
from ml.sentiment import analyze_sentiment

random.seed(42)

# name, category, price, image, description, veg, featured, spice, prep(min)
MENU = [
    (
        "Chicken Biryani", "Main Course", 220,
        "https://images.unsplash.com/photo-1631452180519-c014fe946bc7"
        "?auto=format&fit=crop&w=600&q=80",
        "Fragrant basmati layered with slow-cooked chicken and saffron milk.",
        False, True, 2, 25,
    ),
    (
        "Mutton Biryani", "Main Course", 320,
        "https://images.unsplash.com/photo-1604908176997-125e7c0d7f0f"
        "?auto=format&fit=crop&w=600&q=80",
        "Tender mutton shank braised in biryani masala with long grain rice.",
        False, False, 3, 30,
    ),
    (
        "Paneer Butter Masala", "Main Course", 180,
        "https://images.unsplash.com/photo-1603894584373-5ac82b2ae398"
        "?auto=format&fit=crop&w=600&q=80",
        "Soft paneer cubes in a rich tomato and cashew gravy finished with cream.",
        True, True, 1, 18,
    ),
    (
        "Veg Fried Rice", "Main Course", 140,
        "https://images.unsplash.com/photo-1512058564366-18510be2db19"
        "?auto=format&fit=crop&w=600&q=80",
        "Wok-tossed rice with crisp vegetables, spring onion and a light seasoning.",
        True, False, 1, 15,
    ),
    (
        "Masala Dosa", "South Indian", 90,
        "https://images.unsplash.com/photo-1601050690597-df0568f70950"
        "?auto=format&fit=crop&w=600&q=80",
        "Paper-thin fermented dosa served with potato palya and coconut chutney.",
        True, False, 1, 12,
    ),
    (
        "Idli Sambar", "South Indian", 60,
        "https://images.unsplash.com/photo-1589302168068-964664d93dc0"
        "?auto=format&fit=crop&w=600&q=80",
        "Steamed rice cakes dunked in a hot sambar and served with two chutneys.",
        True, False, 1, 8,
    ),
    (
        "Chicken 65", "Starter", 190,
        "https://images.unsplash.com/photo-1604908556856-b7a6c479f62d"
        "?auto=format&fit=crop&w=600&q=80",
        "Crisp fried chicken tossed with curry leaf, chilli and yoghurt.",
        False, False, 3, 14,
    ),
    (
        "Gobi Manchurian", "Starter", 150,
        "https://images.unsplash.com/photo-1547592166-23ac45744acd"
        "?auto=format&fit=crop&w=600&q=80",
        "Crisp cauliflower in a tangy garlic soy glaze, served dry or saucy.",
        True, False, 2, 13,
    ),
    (
        "Gulab Jamun", "Dessert", 70,
        "https://images.unsplash.com/photo-1601055654745-9f7d84fbb0d7"
        "?auto=format&fit=crop&w=600&q=80",
        "Warm milk dumplings soaked in cardamom sugar syrup.",
        True, False, 0, 5,
    ),
    (
        "Filter Coffee", "Beverage", 40,
        "https://images.unsplash.com/photo-1498804103079-a6351b050096"
        "?auto=format&fit=crop&w=600&q=80",
        "South Indian decoction blended with hot milk and poured tall.",
        True, False, 0, 4,
    ),
    (
        "Hyderabadi Chicken Dum Biryani", "Main Course", 340,
        "https://images.unsplash.com/photo-1563379091339-03b21ab4a4f8"
        "?auto=format&fit=crop&w=600&q=80",
        "Sealed-pot biryani with tender chicken, saffron and fried onions.",
        False, True, 3, 35,
    ),
    (
        "Butter Chicken", "Main Course", 260,
        "https://images.unsplash.com/photo-1603894584373-5ac82b2ae398"
        "?auto=format&fit=crop&w=600&q=80",
        "Tandoor-roasted chicken folded into a mild tomato and butter gravy.",
        False, False, 1, 20,
    ),
    (
        "Veg Samosa", "Starter", 80,
        "https://images.unsplash.com/photo-1601050690117-94f5f6fa8bd7"
        "?auto=format&fit=crop&w=600&q=80",
        "Flaky pastry triangles packed with spiced potato peas.",
        True, False, 1, 9,
    ),
    (
        "Choco Brownie", "Dessert", 150,
        "https://images.unsplash.com/photo-1606313564200-e75d5e30476c"
        "?auto=format&fit=crop&w=600&q=80",
        "Fudgy dark chocolate brownie served warm with vanilla cream.",
        True, False, 0, 6,
    ),
    (
        "Paneer Tikka Masala", "Main Course", 210,
        "https://images.unsplash.com/photo-1631452180519-c014fe946bc7"
        "?auto=format&fit=crop&w=600&q=80",
        "Charred paneer tikka folded into a smoky onion and tomato masala.",
        True, True, 2, 22,
    ),
    (
        "Dal Makhani", "Main Course", 170,
        "https://images.unsplash.com/photo-1546833999-b9f581a1996d"
        "?auto=format&fit=crop&w=600&q=80",
        "Black lentils simmered overnight on low heat with butter and cream.",
        True, False, 1, 20,
    ),
    (
        "Chana Masala", "Main Course", 150,
        "https://images.unsplash.com/photo-1547592180-85f173990554"
        "?auto=format&fit=crop&w=600&q=80",
        "Chickpeas simmered in a warm ginger and garam masala gravy.",
        True, False, 2, 18,
    ),
    (
        "Jeera Rice", "Main Course", 110,
        "https://images.unsplash.com/photo-1596797038530-2c107229654b"
        "?auto=format&fit=crop&w=600&q=80",
        "Basmati tempered with cumin, ghee and fresh coriander.",
        True, False, 0, 12,
    ),
    (
        "Tandoori Roti", "Main Course", 40,
        "https://images.unsplash.com/photo-1601050690597-df0568f70950"
        "?auto=format&fit=crop&w=600&q=80",
        "Whole wheat bread blistered in the tandoor, brushed with ghee.",
        True, False, 0, 6,
    ),
    (
        "Garlic Naan", "Main Course", 70,
        "https://images.unsplash.com/photo-1610057099443-fde8c4d50f91"
        "?auto=format&fit=crop&w=600&q=80",
        "Naan folded with garlic, coriander and a knob of butter.",
        True, False, 1, 7,
    ),
    (
        "Veg Spring Roll", "Starter", 130,
        "https://images.unsplash.com/photo-1544025162-d76694265947"
        "?auto=format&fit=crop&w=600&q=80",
        "Crisp rolls packed with julienned vegetables and glass noodles.",
        True, False, 1, 12,
    ),
    (
        "Paneer Tikka", "Starter", 200,
        "https://images.unsplash.com/photo-1567188040759-fb8a883dc6d8"
        "?auto=format&fit=crop&w=600&q=80",
        "Marinated paneer, peppers and onion charred over open flame.",
        True, True, 2, 16,
    ),
    (
        "Tandoori Chicken", "Starter", 280,
        "https://images.unsplash.com/photo-1598103442097-8b74394b95c6"
        "?auto=format&fit=crop&w=600&q=80",
        "Chicken marinated in yoghurt and roasted until charred at the edges.",
        False, False, 2, 24,
    ),
    (
        "Egg Curry", "Main Course", 160,
        "https://images.unsplash.com/photo-1606491956689-2ea866880c84"
        "?auto=format&fit=crop&w=600&q=80",
        "Boiled eggs in a spiced onion tomato gravy, best with paratha.",
        False, False, 2, 17,
    ),
    (
        "Rajma Chawal", "Main Course", 130,
        "https://images.unsplash.com/photo-1589302168068-964664d93dc0"
        "?auto=format&fit=crop&w=600&q=80",
        "Kidney bean curry served with steamed rice and pickle.",
        True, False, 2, 15,
    ),
    (
        "Butter Naan", "Main Course", 65,
        "https://images.unsplash.com/photo-1610057099443-fde8c4d50f91"
        "?auto=format&fit=crop&w=600&q=80",
        "Soft naan brushed with spiced tomato butter.",
        True, False, 1, 7,
    ),
    (
        "Papadum", "Starter", 45,
        "https://images.unsplash.com/photo-1606491956689-2ea866880c84"
        "?auto=format&fit=crop&w=600&q=80",
        "Crisp papad roasted over flame, served with chutney and salsa.",
        True, False, 0, 5,
    ),
    (
        "Mango Lassi", "Beverage", 90,
        "https://images.unsplash.com/photo-1621263764928-df1444c5e859"
        "?auto=format&fit=crop&w=600&q=80",
        "Thick mango pulp whisked with cool yoghurt and a touch of honey.",
        True, False, 0, 5,
    ),
    (
        "Masala Chai", "Beverage", 45,
        "https://images.unsplash.com/photo-1571934811356-5cc061b6821f"
        "?auto=format&fit=crop&w=600&q=80",
        "Ginger cardamom milk boiled with loose leaf tea.",
        True, False, 0, 6,
    ),
    (
        "Fresh Lime Soda", "Beverage", 70,
        "https://images.unsplash.com/photo-1621263764928-df1444c5e859"
        "?auto=format&fit=crop&w=600&q=80",
        "Sweet or salted lime soda with a sprig of mint.",
        True, False, 0, 4,
    ),
    (
        "Gulab Jamun with Rabri", "Dessert", 120,
        "https://images.unsplash.com/photo-1601055654745-9f7d84fbb0d7"
        "?auto=format&fit=crop&w=600&q=80",
        "Two warm jamuns served with thickened saffron milk.",
        True, False, 0, 6,
    ),
    (
        "Gajar Ka Halwa", "Dessert", 140,
        "https://images.unsplash.com/photo-1606313564200-e75d5e30476c"
        "?auto=format&fit=crop&w=600&q=80",
        "Slow cooked carrot dessert with ghee, cardamom and almond slivers.",
        True, False, 0, 12,
    ),
    (
        "Rasmalai", "Dessert", 130,
        "https://images.unsplash.com/photo-1571877227200-a0d98ea607e9"
        "?auto=format&fit=crop&w=600&q=80",
        "Soft cheese dumplings in a saffron pistachio milk reduction.",
        True, False, 0, 5,
    ),
]

CUSTOMERS = [
    "Priya", "Arjun", "Meena",
    "Karthik", "Divya", "Rahul",
]

POSITIVE_COMMENTS = [
    "the food was delicious and fresh",
    "excellent service and tasty biryani",
    "loved the ambience and quick service",
    "great experience, highly recommended",
]

NEGATIVE_COMMENTS = [
    "the food was cold and stale",
    "very bad service, waited one hour",
    "overpriced and poor quality",
    "the order was wrong and late",
]

NEUTRAL_COMMENTS = [
    "the food was okay nothing special",
    "average taste, normal service",
    "decent place, ordinary food",
]

WASTE_REASONS = [
    "Expired", "Over-preparation", "Spoiled",
    "Customer return", "Storage damage",
]


def seed():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    if db.query(Menu).count() == 0:
        for (
            name, category, price, image_url, description,
            is_vegetarian, is_featured, spice_level, prep_time,
        ) in MENU:
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
        db.commit()
        print(f"Inserted {len(MENU)} menu items")

    # ---------- Customers ----------
    if db.query(Customer).count() == 0:
        for i, name in enumerate(CUSTOMERS):
            db.add(Customer(
                name=name,
                email=f"{name.lower()}@example.com",
                phone=f"90000000{i:02d}",
                address="Chennai, Tamil Nadu",
                loyalty_points=random.randint(0, 500),
            ))
        db.commit()
        print(f"Inserted {len(CUSTOMERS)} customers")

    # ---------- 60 days of orders ----------
    if db.query(Order).count() == 0:
        count = 0
        for day_offset in range(60, 0, -1):
            order_date = datetime.utcnow() - timedelta(days=day_offset)

            # weekends are busier -> gives the models a real pattern
            base = 12 if order_date.weekday() >= 5 else 7

            for _ in range(random.randint(base - 3, base + 4)):
                name, category, price, image_url, description, _v, _f, _s, _p = random.choice(MENU)
                quantity = random.randint(1, 3)

                db.add(Order(
                    customer_name=random.choice(CUSTOMERS),
                    menu_item=name,
                    quantity=quantity,
                    total_price=price * quantity,
                    status="Completed",
                    image_url=image_url,
                    order_type=random.choice(["dine-in", "dine-in", "takeaway", "delivery"]),
                    created_at=order_date,
                ))
                count += 1

        db.commit()
        print(f"Inserted {count} orders across 60 days")

    # ---------- Inventory ----------
    if db.query(Inventory).count() == 0:
        items = [
            ("Basmati Rice", "Grains", 40, "kg", 15, 95),
            ("Chicken", "Meat", 8, "kg", 10, 220),
            ("Paneer", "Dairy", 5, "kg", 6, 320),
            ("Onion", "Vegetable", 25, "kg", 10, 35),
            ("Tomato", "Vegetable", 4, "kg", 8, 40),
            ("Cooking Oil", "Grocery", 30, "litre", 12, 130),
        ]
        for n, c, q, u, m, cost in items:
            db.add(Inventory(
                item_name=n, category=c, quantity=q, unit=u,
                minimum_stock=m, supplier="Local Vendor",
                cost_per_unit=cost, created_at=datetime.utcnow(),
            ))
        db.commit()
        print(f"Inserted {len(items)} inventory items")

    # ---------- Reviews (auto-classified) ----------
    if db.query(Review).count() == 0:
        pool = (
            POSITIVE_COMMENTS * 5
            + NEUTRAL_COMMENTS * 2
            + NEGATIVE_COMMENTS * 2
        )
        for i, comment in enumerate(pool):
            result = analyze_sentiment(comment)
            db.add(Review(
                customer_name=random.choice(CUSTOMERS),
                menu_item=random.choice(MENU)[0],
                rating=(
                    5 if result["sentiment"] == "Positive"
                    else 2 if result["sentiment"] == "Negative"
                    else 3
                ),
                comment=comment,
                sentiment=result["sentiment"],
                sentiment_score=result["score"],
                created_at=datetime.utcnow() - timedelta(days=i),
            ))
        db.commit()
        print(f"Inserted {len(pool)} reviews")

    # ---------- Waste records ----------
    if db.query(Waste).count() == 0:
        count = 0
        for day_offset in range(30, 0, -1):
            record_date = datetime.utcnow() - timedelta(days=day_offset)

            for _ in range(random.randint(1, 3)):
                item, _c, _q, _u, _m, cost = random.choice([
                    ("Chicken", "", 0, "", 0, 220),
                    ("Tomato", "", 0, "", 0, 40),
                    ("Paneer", "", 0, "", 0, 320),
                    ("Basmati Rice", "", 0, "", 0, 95),
                ])
                quantity = round(random.uniform(0.3, 3.0), 2)

                db.add(Waste(
                    item_name=item,
                    quantity=quantity,
                    unit="kg",
                    reason=random.choice(WASTE_REASONS),
                    cost=round(quantity * cost, 2),
                    recorded_at=record_date,
                ))
                count += 1

        db.commit()
        print(f"Inserted {count} waste records")

    # ---------- Suppliers & staff ----------
    if db.query(Supplier).count() == 0:
        for name, category in [
            ("Sri Vegetables", "Vegetable"),
            ("Anand Meat Supply", "Meat"),
            ("Krishna Dairy", "Dairy"),
        ]:
            db.add(Supplier(
                name=name,
                contact_person="Manager",
                phone="9876543210",
                email=f"{name.split()[0].lower()}@supply.com",
                category=category,
                address="Chennai",
            ))
        db.commit()
        print("Inserted suppliers")

    if db.query(Staff).count() == 0:
        for name, role, shift, salary in [
            ("Ramesh", "Head Chef", "Morning", 35000),
            ("Suresh", "Chef", "Evening", 25000),
            ("Lakshmi", "Waiter", "Morning", 15000),
            ("Vijay", "Cashier", "Evening", 18000),
        ]:
            db.add(Staff(
                name=name, role=role, phone="9000000000",
                email=f"{name.lower()}@restaurant.com",
                shift=shift, salary=salary, active=True,
                joined_on=datetime.utcnow().date(),
            ))
        db.commit()
        print("Inserted staff")

    db.close()
    print("\nSeeding complete. Start the server with: uvicorn main:app --reload")


if __name__ == "__main__":
    seed()
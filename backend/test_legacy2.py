import sys
sys.path.insert(0, r"C:\Users\BUDDY\Downloads\Ai-Restaurant-Management-system-main (1) zip file\Ai-Restaurant-Management-system-main\backend")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Order
from sqlalchemy import func, cast, Date
from database import engine

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
db = SessionLocal()

try:
    # Test the legacy order grouping query
    groups = (
        db.query(
            Order.customer_name,
            func.date(Order.created_at).label("order_date"),
            func.min(Order.created_at).label("placed_at"),
            func.max(Order.created_at).label("updated_at"),
            func.count(Order.id).label("item_count"),
            func.sum(Order.total_price).label("total_amount"),
            func.group_concat(Order.id).label("order_ids"),
        )
        .filter(Order.order_id.is_(None))
        .group_by(Order.customer_name, func.date(Order.created_at))
        .order_by(func.max(Order.created_at).desc())
        .limit(5)
        .all()
    )

    for group in groups:
        print(f'Legacy group: {group}')

finally:
    db.close()
import sys
sys.path.insert(0, r"C:\Users\BUDDY\Downloads\Ai-Restaurant-Management-system-main (1) zip file\Ai-Restaurant-Management-system-main\backend")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Order
from database import engine
from routes.orders import _legacy_order_groups

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
db = SessionLocal()

try:
    legacy = _legacy_order_groups(db)
    print(f"Number of legacy groups: {len(legacy)}")
    for group in legacy[:5]:
        print(f"  {group['reference']} - {group['customer_name']} - {group['status']} - {group['total_amount']}")

finally:
    db.close()
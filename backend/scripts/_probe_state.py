import pymysql

c = pymysql.connect(
    host="localhost",
    user="root",
    password="Nithin.0987",
    database="restaurant_db",
    autocommit=True,
)
cur = c.cursor()

cur.execute("SELECT COUNT(*) FROM orders")
print("orders total          :", cur.fetchone()[0])

cur.execute("SELECT COUNT(*) FROM orders WHERE order_id IS NULL")
print("orders with NO header :", cur.fetchone()[0])

cur.execute("SELECT COUNT(*) FROM orders WHERE order_id IS NOT NULL")
print("orders WITH a header  :", cur.fetchone()[0])

cur.execute(
    "SELECT o.id, o.order_id, o.created_at, h.reference "
    "FROM orders o LEFT JOIN order_headers h ON h.id = o.order_id "
    "WHERE o.order_id IS NOT NULL"
)
print("\nlines that still carry a header:")
for row in cur.fetchall():
    print("   line id=%s header=%s created=%s reference=%s" % row)

cur.execute("SELECT COUNT(*) FROM order_headers")
print("\norder_headers total   :", cur.fetchone()[0])

cur.execute(
    "SELECT id, reference, table_id, table_number, created_at "
    "FROM order_headers ORDER BY id"
)
print("\nheaders:")
for row in cur.fetchall():
    print("   ", row)

c.close()
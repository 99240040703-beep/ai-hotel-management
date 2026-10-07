import sqlite3
conn = sqlite3.connect('restaurant.db')
cursor = conn.cursor()

# Check tables
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = cursor.fetchall()
print('Tables:', tables)

# Check orders table
cursor.execute('SELECT COUNT(*) FROM orders')
print('orders count:', cursor.fetchone()[0])

# Check order_headers table
cursor.execute('SELECT COUNT(*) FROM order_headers')
print('order_headers count:', cursor.fetchone()[0])

# Check order_headers data
cursor.execute('SELECT id, reference, customer_name, status, payment_status, total_amount, placed_at FROM order_headers')
for row in cursor.fetchall():
    print('  Header:', row)

# Check orders data (first 10)
cursor.execute('SELECT id, order_id, customer_name, menu_item, quantity, total_price, status, created_at FROM orders LIMIT 10')
for row in cursor.fetchall():
    print('  Order:', row)

conn.close()
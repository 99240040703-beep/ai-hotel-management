import pymysql

c = pymysql.connect(
    host="localhost",
    user="root",
    password="Nithin.0987",
    database="restaurant_db",
)
cur = c.cursor()

cur.execute("SHOW TABLES LIKE %s", ("restaurant_tables",))
print("restaurant_tables exists:", bool(cur.fetchone()))

cur.execute("SHOW COLUMNS FROM restaurant_tables")
print("\ncolumns:")
for r in cur.fetchall():
    print("  %-14s %-16s null=%-4s key=%s" % (r[0], r[1], r[2], r[3]))

cur.execute("SHOW COLUMNS FROM order_headers LIKE %s", ("table_id",))
print("\norder_headers.table_id present:", bool(cur.fetchone()))

cur.execute("SHOW COLUMNS FROM users LIKE %s", ("active_table_id",))
print("users.active_table_id present:", bool(cur.fetchone()))

cur.execute(
    "SELECT COUNT(*) FROM order_headers WHERE table_id IS NOT NULL"
)
print(
    "order_headers with a table (must be 0, no guessing):",
    cur.fetchone()[0],
)

cur.execute("SELECT COUNT(*) FROM restaurant_tables")
print("restaurant_tables rows:", cur.fetchone()[0])

c.close()

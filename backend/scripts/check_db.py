import pymysql

conn = pymysql.connect(host='localhost', user='root', password='Nithin.0987', database='restaurant_db', autocommit=True)
with conn.cursor() as cur:
    cur.execute('SHOW TABLES LIKE "restaurant_tables"')
    print('restaurant_tables exists:', cur.fetchone())
    cur.execute('SELECT * FROM restaurant_tables')
    for row in cur.fetchall():
        print(row)
    cur.execute('SELECT COUNT(*) FROM menu')
    print('menu count:', cur.fetchone())
    cur.execute('SELECT currency, tax_percentage FROM settings LIMIT 1')
    print('settings:', cur.fetchone())
conn.close()
import mysql.connector
conn = mysql.connector.connect(
    host='localhost',
    user='root',
    password='Nithin.0987',
    database='restaurant_db'
)
cursor = conn.cursor()

# Test the legacy order grouping query
cursor.execute('''
    SELECT 
        customer_name,
        DATE(created_at) as order_date,
        MIN(created_at) as placed_at,
        MAX(created_at) as updated_at,
        COUNT(*) as item_count,
        SUM(total_price) as total_amount,
        GROUP_CONCAT(id) as order_ids
    FROM orders 
    WHERE order_id IS NULL
    GROUP BY customer_name, DATE(created_at)
    ORDER BY MAX(created_at) DESC
    LIMIT 5
''')
for row in cursor.fetchall():
    print(f'Legacy group: {row}')

conn.close()
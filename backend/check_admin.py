import mysql.connector
conn = mysql.connector.connect(
    host='localhost',
    user='root',
    password='Nithin.0987',
    database='restaurant_db'
)
cursor = conn.cursor()
cursor.execute("SELECT email, name, role FROM users WHERE role = 'admin'")
for row in cursor.fetchall():
    print(row)
conn.close()
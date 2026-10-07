"""Print every user row stored in the restaurant database.

Database credentials are read from backend/.env so that no secret
is hardcoded in this script:

    DB_USER, DB_PASSWORD, DB_HOST, DB_NAME
"""

import os
from pathlib import Path

import pymysql
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / "backend" / ".env")

conn = pymysql.connect(
    host=os.getenv("DB_HOST", "localhost"),
    user=os.getenv("DB_USER", "root"),
    password=os.getenv("DB_PASSWORD", ""),
    database=os.getenv("DB_NAME", "restaurant_db"),
)

cursor = conn.cursor()
cursor.execute("SELECT * FROM users")
users = cursor.fetchall()

print("Users in database:")
for user in users:
    print(f"  ID: {user[0]}, Name: {user[1]}, Email: {user[2]}, Role: {user[5]}")

cursor.close()
conn.close()
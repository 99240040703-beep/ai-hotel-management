import requests
import json

# First login
url = "http://127.0.0.1:8000/auth/login"
payload = {"email": "admin@gmail.com", "password": "password123"}
response = requests.post(url, json=payload)
print(f"Login Status: {response.status_code}")

if response.status_code == 200:
    data = response.json()
    token = data["token"]
    print(f"Login successful, token: {token[:20]}...")
    
    # Test dashboard with token
    headers = {"Authorization": f"Bearer {token}"}
    dashboard_url = "http://127.0.0.1:8000/api/dashboard/"
    dash_response = requests.get(dashboard_url, headers=headers)
    print(f"Dashboard Status: {dash_response.status_code}")
    print(f"Dashboard Response: {dash_response.json()}")
else:
    print(f"Login failed: {response.text}")
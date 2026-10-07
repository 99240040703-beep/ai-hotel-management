import requests
import json

# Login as admin
response = requests.post(
    'http://127.0.0.1:8000/auth/login',
    json={'email': 'admin@gmail.com', 'password': 'password123'}
)
print('Login response:', response.status_code)
if response.status_code == 200:
    data = response.json()
    token = data.get('token')
    print('Token:', token[:50] + '...')
    
    # Test orders headers endpoint
    headers = {'Authorization': 'Bearer ' + token}
    response = requests.get('http://127.0.0.1:8000/api/orders/headers', headers=headers)
    print('\nOrders headers response:', response.status_code)
    if response.status_code == 200:
        orders = response.json()
        print('Number of orders:', len(orders))
        for order in orders[:10]:
            print('  ' + order['reference'] + ' - ' + order['customer_name'] + ' - ' + order['status'] + ' - ' + str(order['total_amount']))
    else:
        print('Error:', response.text)
else:
    print('Login error:', response.text)
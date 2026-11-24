"""Server-side search and suggestions on real PostgreSQL, including cache invalidation."""
from test_postgres_api import client  # noqa: F401  (PostgreSQL fixture)
from test_admin_profile import demo, login
from test_operator_api import custom_detector  # noqa: F401  (light detector fixture)
from app import schema as s


def publish(client, lat, street, neighborhood, risk='HIGH', description='Hueco profundo en el carril'):
    async def geocode(position):
        return {'cacheKey': f'{position.lat:.5f},{position.lng:.5f}', 'source': 'nominatim', 'street': street,
                'neighborhood': neighborhood, 'city': 'Pasto', 'region': 'Nariño', 'countryCode': 'co',
                'country': 'Colombia', 'fullAddress': f'{street}, {neighborhood}, Pasto'}
    client.app.state.geocoder.resolve = geocode
    response = client.post('/api/community/reports', json={'position': {'lat': lat, 'lng': -77.29, 'accuracy': 6},
                           'capturedAt': s.Clock.now(), 'risk': risk, 'description': description})
    assert response.status_code == 201, response.text
    return response.json()['report']


def test_search_requires_session_and_validates_input(client):
    assert client.get('/api/reports/search?q=calle').status_code == 401
    accounts = demo(client)
    login(client, accounts['Conductor']['email'], accounts['Conductor']['password'])
    assert client.get('/api/reports/search?q=').status_code == 422
    assert client.get('/api/reports/search?q=' + 'x' * 121).status_code == 422
    empty = client.get('/api/reports/search?q=de la').json()
    assert empty['reports'] == [] and empty['tokens'] == []


def test_search_ranks_pages_and_refreshes_after_changes(client):
    accounts = demo(client)
    login(client, accounts['Conductor']['email'], accounts['Conductor']['password'])
    critical = publish(client, 1.2100, 'Avenida Panamericana', 'La Primavera', 'CRITICAL')
    medium = publish(client, 1.2200, 'Avenida Panamericana', 'La Primavera', 'MEDIUM')
    other = publish(client, 1.2300, 'Carrera 45', 'Pandiaco', 'HIGH', 'Grieta ancha junto al separador')

    first = client.get('/api/reports/search?q=avenida panam').json()
    assert [item['id'] for item in first['reports']] == [critical['id'], medium['id']] and first['total'] == 2
    assert first['index']['rebuilt'] is True and first['index']['documents'] == 3
    again = client.get('/api/reports/search?q=avenida panam&limit=1&offset=1').json()
    assert [item['id'] for item in again['reports']] == [medium['id']] and again['hasMore'] is False
    assert again['index']['rebuilt'] is False  # Same database fingerprint: cached index reused.
    assert [item['id'] for item in client.get('/api/reports/search?q=separador').json()['reports']] == [other['id']]

    suggestions = client.get('/api/reports/suggest?prefix=panam').json()['suggestions']
    assert suggestions == [{'label': 'Avenida Panamericana', 'kind': 'street', 'count': 2}]

    # A status change made through any replica changes the fingerprint and rebuilds the index.
    login(client, accounts['Operario']['email'], accounts['Operario']['password'])
    assert client.post(f"/api/operator/reports/{medium['id']}/transition", json={'status': 'REJECTED'}).status_code == 200
    after = client.get('/api/reports/search?q=avenida panam').json()
    assert after['index']['rebuilt'] is True and [item['id'] for item in after['reports']] == [critical['id']]

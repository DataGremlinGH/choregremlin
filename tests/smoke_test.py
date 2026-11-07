import pytest
from app import app

@pytest.fixture
def client():
    with app.test_client() as client:
        yield client

def test_app(client):
    response = client.get('/')
    assert response.status_code == 200
    assert b'Chore Gremlin' in response.data

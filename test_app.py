import os
import sys

import mongomock
import pymongo
import pytest

# Replace the real MongoDB client before app.py is imported (it pings Atlas on import)
pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017/parking_management")

sys.path.insert(0, os.path.dirname(__file__))
import app as parking_app  # noqa: E402


@pytest.fixture
def client():
    parking_app.app.config["TESTING"] = True
    parking_app.app.config["WTF_CSRF_ENABLED"] = False
    with parking_app.app.test_client() as c:
        yield c


def test_home_page_returns_200(client):
    assert client.get("/").status_code == 200


def test_login_page_returns_200(client):
    assert client.get("/login").status_code == 200


def test_register_page_returns_200(client):
    assert client.get("/register").status_code == 200


def test_health_returns_200(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json()["status"] == "healthy"


def test_metrics_returns_200(client):
    response = client.get("/metrics")
    assert response.status_code == 200
    assert b"flask_http_request_total" in response.data or b"parking_checkins_total" in response.data


def test_fee_calculation():
    from datetime import datetime, timedelta
    start = datetime(2026, 1, 1, 10, 0, 0)
    assert parking_app.calculate_parking_fee(start, start + timedelta(hours=2), 30) == 60.0


def test_invoice_number_format():
    number = parking_app.generate_invoice_number()
    assert number.startswith("INV-")
    assert len(number.split("-")) == 3


def test_dashboard_requires_login(client):
    response = client.get("/user/dashboard")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_admin_page_requires_login(client):
    response = client.get("/admin/dashboard")
    assert response.status_code in (302, 403)


def test_unknown_page_returns_404(client):
    assert client.get("/this-page-does-not-exist").status_code == 404

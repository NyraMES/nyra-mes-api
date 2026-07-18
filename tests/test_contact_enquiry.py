"""Tests for public contact enquiry endpoint."""

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


def test_contact_enquiry_disabled_returns_503(monkeypatch):
    monkeypatch.setattr(settings, "contact_enquiry_enabled", False)
    client = TestClient(app)
    response = client.post(
        "/public/contact-enquiry",
        json={
            "name": "Test User",
            "email": "test@example.com",
            "organisation": "Test Co",
            "message": "Interested in a demo for our plant.",
        },
    )
    assert response.status_code == 503


def test_contact_enquiry_dry_run_returns_success(monkeypatch):
    monkeypatch.setattr(settings, "contact_enquiry_enabled", True)
    monkeypatch.setattr(settings, "contact_enquiry_dry_run", True)
    client = TestClient(app)
    response = client.post(
        "/public/contact-enquiry",
        json={
            "name": "Test User",
            "email": "test@example.com",
            "message": "Interested in a demo for our plant.",
        },
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True

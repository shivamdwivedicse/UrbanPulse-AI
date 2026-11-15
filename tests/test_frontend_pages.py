from fastapi.testclient import TestClient

from backend.main import app


def test_public_homepage_and_operations_dashboard_are_served():
    with TestClient(app) as client:
        homepage = client.get("/")
        dashboard = client.get("/dashboard")
        dashboard_slash = client.get("/dashboard/")

    assert homepage.status_code == 200
    assert "Building cleaner cities through" in homepage.text
    assert "/dashboard" in homepage.text
    assert dashboard.status_code == 200
    assert "id=\"overview\"" in dashboard.text
    assert "id=\"complaints\"" in dashboard.text
    assert dashboard_slash.status_code == 200


def test_dashboard_assets_are_served_at_stable_paths():
    with TestClient(app) as client:
        stylesheet = client.get("/assets/css/style.css")
        application = client.get("/assets/js/app.js")

    assert stylesheet.status_code == 200
    assert "--color-forest: #163B32" in stylesheet.text
    assert application.status_code == 200
    assert "/api/v1/bins" in application.text

"""
API tests for GET /api/v1/bins/{bin_id}/history.
Uses cleaned CSV observations only; does not retrain or load the champion model.
"""

import sys
from pathlib import Path

root_dir = Path(__file__).resolve().parents[1]
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.services.bin_service import BinService, get_bin_service


class DummyPredictor:
    """Stand-in so BinService can start without the joblib artifact."""

    model = object()
    champion_name = "dummy"
    target_name = "latestFullness"
    feature_names = [
        "lag_1",
        "lag_2",
        "lag_3",
        "lag_7",
        "rolling_mean_3",
        "rolling_mean_7",
        "day_of_week",
        "month",
    ]


@pytest.fixture
def fixture_csv(tmp_path: Path) -> Path:
    csv_path = tmp_path / "history_fixture.csv"
    csv_path.write_text(
        "timestamp_julian,latestFullness,datetime\n"
        "2458295.0,6.0,2018-06-25 12:00:00\n"
        "2458296.0,0.0,2018-06-26 12:00:00\n"
        "2458297.0,10.0,2018-06-27 12:00:00\n",
        encoding="utf-8",
    )
    return csv_path


@pytest.fixture
def client(fixture_csv: Path):
    service = BinService(data_csv_path=fixture_csv, predictor=DummyPredictor())
    app.dependency_overrides[get_bin_service] = lambda: service
    test_client = TestClient(app)
    yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def real_history_client():
    csv_path = root_dir / "datasets" / "processed" / "smart_bin_cleaned.csv"
    service = BinService(data_csv_path=csv_path, predictor=DummyPredictor())
    app.dependency_overrides[get_bin_service] = lambda: service
    test_client = TestClient(app)
    yield test_client
    app.dependency_overrides.clear()


def test_history_endpoint_returns_fixture_observations(client: TestClient):
    response = client.get("/api/v1/bins/BIN-PROTOTYPE-01/history")
    assert response.status_code == 200

    payload = response.json()
    assert payload["bin_id"] == "BIN-PROTOTYPE-01"
    assert payload["is_live_iot"] is False
    assert payload["total_observations"] == 3
    assert payload["start_date"] == "2018-06-25 12:00:00"
    assert payload["end_date"] == "2018-06-27 12:00:00"
    assert payload["min_fill_level"] == 0.0
    assert payload["max_fill_level"] == 10.0
    assert payload["average_fill_level"] == 5.3333
    assert payload["observations"] == [
        {"datetime": "2018-06-25 12:00:00", "fill_level": 6.0},
        {"datetime": "2018-06-26 12:00:00", "fill_level": 0.0},
        {"datetime": "2018-06-27 12:00:00", "fill_level": 10.0},
    ]


def test_history_unknown_bin_returns_404(client: TestClient):
    response = client.get("/api/v1/bins/BIN-DOES-NOT-EXIST/history")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_prediction_route_still_registered():
    paths = app.openapi()["paths"]
    assert "/api/v1/bins/{bin_id}/history" in paths
    assert "/api/v1/bins/{bin_id}/prediction" in paths
    assert "get" in paths["/api/v1/bins/{bin_id}/prediction"]


def test_history_matches_cleaned_dataset(real_history_client: TestClient):
    csv_path = root_dir / "datasets" / "processed" / "smart_bin_cleaned.csv"
    df = pd.read_csv(csv_path)
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.sort_values("datetime").reset_index(drop=True)

    response = real_history_client.get("/api/v1/bins/BIN-PROTOTYPE-01/history")
    assert response.status_code == 200

    payload = response.json()
    assert payload["total_observations"] == len(df)
    assert payload["start_date"] == df["datetime"].iloc[0].strftime("%Y-%m-%d %H:%M:%S")
    assert payload["end_date"] == df["datetime"].iloc[-1].strftime("%Y-%m-%d %H:%M:%S")
    assert payload["min_fill_level"] == float(df["latestFullness"].min())
    assert payload["max_fill_level"] == float(df["latestFullness"].max())
    assert payload["average_fill_level"] == round(float(df["latestFullness"].mean()), 4)
    assert len(payload["observations"]) == len(df)
    assert payload["observations"][0]["fill_level"] == float(df["latestFullness"].iloc[0])
    assert payload["observations"][-1]["fill_level"] == float(df["latestFullness"].iloc[-1])
    assert payload["is_live_iot"] is False

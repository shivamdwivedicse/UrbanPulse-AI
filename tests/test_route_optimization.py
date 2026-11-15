"""Tests for illustrative OR-Tools bin collection route optimization."""

import math

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.main import app
from backend.services import route_optimization_service
from backend.services.route_optimization_service import haversine_distance_km


DEPOT = {
    "name": "Illustrative depot",
    "latitude": 37.5665,
    "longitude": 126.9780,
}

SAMPLE_STOPS = [
    {
        "bin_id": "DEMO-BIN-01",
        "latitude": 37.5675,
        "longitude": 126.9790,
        "fill_level": 8.2,
        "priority": "HIGH",
    },
    {
        "bin_id": "DEMO-BIN-02",
        "latitude": 37.5700,
        "longitude": 126.9810,
        "fill_level": 4.5,
        "priority": "LOW",
    },
    {
        "bin_id": "DEMO-BIN-03",
        "latitude": 37.5655,
        "longitude": 126.9750,
        "fill_level": 6.7,
        "priority": "MEDIUM",
    },
]


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_haversine_calculates_known_equatorial_distance():
    assert haversine_distance_km(0, 0, 1, 0) == pytest.approx(111.195, abs=0.01)


def test_route_optimization_returns_valid_order_and_distance(client):
    response = client.post(
        "/api/v1/routes/optimize",
        json={"depot": DEPOT, "stops": SAMPLE_STOPS},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["number_of_stops"] == len(SAMPLE_STOPS)
    assert result["optimization_status"] == "SOLUTION_FOUND"
    assert result["return_to_depot"] is True
    assert "Haversine" in result["distance_methodology"]
    assert "not road distance" in result["distance_methodology"]
    assert [stop["stop_number"] for stop in result["stops"]] == [1, 2, 3]
    assert {stop["bin_id"] for stop in result["stops"]} == {
        stop["bin_id"] for stop in SAMPLE_STOPS
    }

    ordered_priorities = [stop["priority"] for stop in result["stops"]]
    assert max(
        index for index, priority in enumerate(ordered_priorities) if priority == "HIGH"
    ) < min(
        index for index, priority in enumerate(ordered_priorities) if priority == "MEDIUM"
    )
    assert max(
        index for index, priority in enumerate(ordered_priorities) if priority == "MEDIUM"
    ) < min(
        index for index, priority in enumerate(ordered_priorities) if priority == "LOW"
    )

    points = [DEPOT, *[
        next(stop for stop in SAMPLE_STOPS if stop["bin_id"] == stop_result["bin_id"])
        for stop_result in result["stops"]
    ], DEPOT]
    expected_distance = sum(
        haversine_distance_km(
            first["latitude"],
            first["longitude"],
            second["latitude"],
            second["longitude"],
        )
        for first, second in zip(points, points[1:])
    )
    assert result["total_estimated_distance_km"] == pytest.approx(
        expected_distance, abs=0.003
    )


def test_route_endpoint_returns_required_response_fields(client):
    response = client.post(
        "/api/v1/routes/optimize",
        json={"depot": DEPOT, "stops": SAMPLE_STOPS[:1]},
    )

    assert response.status_code == 200
    result = response.json()
    assert {
        "depot",
        "stops",
        "total_estimated_distance_km",
        "number_of_stops",
        "optimization_status",
        "distance_methodology",
        "return_to_depot",
    } <= result.keys()
    assert {
        "bin_id",
        "latitude",
        "longitude",
        "fill_level",
        "priority",
        "stop_number",
        "distance_from_previous_km",
    } <= result["stops"][0].keys()


@pytest.mark.parametrize(
    ("depot", "stops"),
    [
        ({**DEPOT, "latitude": 91}, SAMPLE_STOPS),
        (DEPOT, [{**SAMPLE_STOPS[0], "longitude": -181}]),
        (DEPOT, [{**SAMPLE_STOPS[0], "fill_level": 10.1}]),
        (DEPOT, []),
    ],
)
def test_route_endpoint_rejects_invalid_coordinates_and_empty_stops(client, depot, stops):
    response = client.post(
        "/api/v1/routes/optimize",
        json={"depot": depot, "stops": stops},
    )
    assert response.status_code == 422


def test_schema_rejects_non_finite_coordinates():
    from backend.schemas.route_optimization import RouteOptimizeRequest

    with pytest.raises(ValidationError):
        RouteOptimizeRequest.model_validate(
            {
                "depot": DEPOT,
                "stops": [{**SAMPLE_STOPS[0], "latitude": math.nan}],
            }
        )


def test_route_endpoint_rejects_duplicate_bin_ids(client):
    duplicate = {**SAMPLE_STOPS[1], "bin_id": SAMPLE_STOPS[0]["bin_id"].lower()}
    response = client.post(
        "/api/v1/routes/optimize",
        json={"depot": DEPOT, "stops": [SAMPLE_STOPS[0], duplicate]},
    )
    assert response.status_code == 422


def test_route_endpoint_returns_error_when_solver_has_no_solution(client, monkeypatch):
    routing_model = route_optimization_service.pywrapcp.RoutingModel
    original_model = routing_model

    class NoSolutionRoutingModel:
        def __new__(cls, *args, **kwargs):
            instance = original_model(*args, **kwargs)
            instance.SolveWithParameters = lambda _parameters: None
            return instance

    monkeypatch.setattr(
        route_optimization_service.pywrapcp,
        "RoutingModel",
        NoSolutionRoutingModel,
    )
    response = client.post(
        "/api/v1/routes/optimize",
        json={"depot": DEPOT, "stops": SAMPLE_STOPS},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "No feasible route was found for the supplied stops."

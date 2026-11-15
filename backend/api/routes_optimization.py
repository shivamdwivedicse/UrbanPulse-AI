"""Route optimization API."""

from fastapi import APIRouter, Depends

from backend.schemas.route_optimization import (
    RouteOptimizationResponse,
    RouteOptimizeRequest,
)
from backend.services.route_optimization_service import RouteOptimizationService


router = APIRouter(prefix="/api/v1/routes", tags=["Route Optimization"])


def get_route_optimization_service() -> RouteOptimizationService:
    return RouteOptimizationService()


@router.post(
    "/optimize",
    response_model=RouteOptimizationResponse,
    summary="Optimize a bin collection route",
    description=(
        "Optimize an illustrative single-vehicle collection sequence using "
        "Haversine straight-line distances."
    ),
)
def optimize_route(
    request: RouteOptimizeRequest,
    service: RouteOptimizationService = Depends(get_route_optimization_service),
) -> RouteOptimizationResponse:
    return service.optimize(request)

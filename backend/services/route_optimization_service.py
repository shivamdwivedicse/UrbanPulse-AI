"""Single-vehicle route optimization using OR-Tools and Haversine distances."""

from math import asin, cos, radians, sin, sqrt

from fastapi import HTTPException, status
from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from backend.schemas.route_optimization import (
    CollectionPriority,
    OptimizedRouteStop,
    RouteOptimizationResponse,
    RouteOptimizeRequest,
)


EARTH_RADIUS_KM = 6371.0088
SOLVER_TIME_LIMIT_SECONDS = 1
DISTANCE_METHODOLOGY = (
    "Haversine great-circle distance using mean Earth radius 6,371.0088 km; "
    "straight-line approximation, not road distance. Distance includes "
    "the return to depot when enabled."
)
_PRIORITY_RANK = {
    CollectionPriority.HIGH: 0,
    CollectionPriority.MEDIUM: 1,
    CollectionPriority.LOW: 2,
}


def haversine_distance_km(
    latitude_a: float,
    longitude_a: float,
    latitude_b: float,
    longitude_b: float,
) -> float:
    """Calculate great-circle distance between two latitude/longitude points."""
    lat_a, lat_b = radians(latitude_a), radians(latitude_b)
    delta_lat = lat_b - lat_a
    delta_lon = radians(longitude_b - longitude_a)
    haversine = (
        sin(delta_lat / 2) ** 2
        + cos(lat_a) * cos(lat_b) * sin(delta_lon / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * asin(sqrt(min(1.0, haversine)))


class RouteOptimizationService:
    def optimize(self, request: RouteOptimizeRequest) -> RouteOptimizationResponse:
        points = [request.depot, *request.stops]
        distance_matrix_m = [
            [
                round(
                    haversine_distance_km(
                        point_a.latitude,
                        point_a.longitude,
                        point_b.latitude,
                        point_b.longitude,
                    )
                    * 1000
                )
                for point_b in points
            ]
            for point_a in points
        ]

        manager = pywrapcp.RoutingIndexManager(
            len(points),
            1,
            [0],
            [0],
        )
        routing = pywrapcp.RoutingModel(manager)

        def distance_callback(from_index: int, to_index: int) -> int:
            from_node = manager.IndexToNode(from_index)
            to_node = manager.IndexToNode(to_index)
            return distance_matrix_m[from_node][to_node]

        distance_callback_index = routing.RegisterTransitCallback(distance_callback)
        routing.SetArcCostEvaluatorOfAllVehicles(distance_callback_index)

        def visit_order_callback(_from_index: int, _to_index: int) -> int:
            return 1

        order_callback_index = routing.RegisterTransitCallback(visit_order_callback)
        routing.AddDimension(
            order_callback_index,
            0,
            len(request.stops) + 1,
            True,
            "VisitOrder",
        )
        visit_order = routing.GetDimensionOrDie("VisitOrder")
        solver = routing.solver()
        for earlier_stop_index, earlier_stop in enumerate(request.stops, start=1):
            for later_stop_index, later_stop in enumerate(request.stops, start=1):
                if _PRIORITY_RANK[earlier_stop.priority] < _PRIORITY_RANK[later_stop.priority]:
                    solver.Add(
                        visit_order.CumulVar(manager.NodeToIndex(earlier_stop_index))
                        < visit_order.CumulVar(manager.NodeToIndex(later_stop_index))
                    )

        search_parameters = pywrapcp.DefaultRoutingSearchParameters()
        search_parameters.first_solution_strategy = (
            routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
        )
        search_parameters.local_search_metaheuristic = (
            routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
        )
        search_parameters.time_limit.FromSeconds(SOLVER_TIME_LIMIT_SECONDS)
        assignment = routing.SolveWithParameters(search_parameters)
        if assignment is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="No feasible route was found for the supplied stops.",
            )

        ordered_nodes: list[int] = []
        index = routing.Start(0)
        while not routing.IsEnd(index):
            node = manager.IndexToNode(index)
            if node != 0:
                ordered_nodes.append(node)
            index = assignment.Value(routing.NextVar(index))

        optimized_stops: list[OptimizedRouteStop] = []
        total_distance_m = 0
        previous_node = 0
        for stop_number, node in enumerate(ordered_nodes, start=1):
            stop = request.stops[node - 1]
            distance_m = distance_matrix_m[previous_node][node]
            total_distance_m += distance_m
            optimized_stops.append(
                OptimizedRouteStop(
                    **stop.model_dump(),
                    stop_number=stop_number,
                    distance_from_previous_km=distance_m / 1000,
                )
            )
            previous_node = node

        total_distance_m += distance_matrix_m[previous_node][0]

        return RouteOptimizationResponse(
            depot=request.depot,
            stops=optimized_stops,
            total_estimated_distance_km=total_distance_m / 1000,
            number_of_stops=len(optimized_stops),
            optimization_status="SOLUTION_FOUND",
            distance_methodology=DISTANCE_METHODOLOGY,
            return_to_depot=True,
        )

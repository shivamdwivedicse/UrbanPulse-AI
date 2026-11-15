from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.api.routes_bins import router as bins_router
from backend.api.routes_complaints import router as complaints_router
from backend.api.routes_health import router as health_router
from backend.api.routes_optimization import router as route_optimization_router
from backend.api.routes_waste import router as waste_router


app = FastAPI(
    title="UrbanPulse AI",
    description="Smart City Waste Management and Prediction API",
    version="1.0.0"
)

FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend"
app.mount(
    "/assets",
    StaticFiles(directory=FRONTEND_DIR / "assets"),
    name="frontend-assets",
)

# Frontend development access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API routes
app.include_router(health_router)
app.include_router(bins_router)
app.include_router(waste_router)
app.include_router(route_optimization_router)
app.include_router(complaints_router)


@app.get("/", include_in_schema=False)
def public_homepage() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "home.html")


@app.get("/dashboard", include_in_schema=False)
@app.get("/dashboard/", include_in_schema=False)
def operations_dashboard() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")

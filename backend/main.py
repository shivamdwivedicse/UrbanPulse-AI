from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes_bins import router as bins_router
from backend.api.routes_health import router as health_router


app = FastAPI(
    title="UrbanPulse AI",
    description="Smart City Waste Management and Prediction API",
    version="1.0.0"
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


@app.get("/")
def root():
    return {
        "message": "Welcome to UrbanPulse AI API",
        "status": "running",
        "docs": "/docs"
    }

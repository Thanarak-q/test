from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.envelope import EnvelopeRoute, register_error_handlers
from app.routers import health

app = FastAPI(title="matthew-api")
app.router.route_class = EnvelopeRoute

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_error_handlers(app)

app.include_router(health.router, prefix="/v1")

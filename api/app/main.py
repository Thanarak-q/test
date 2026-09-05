from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.envelope import EnvelopeRoute, register_error_handlers
from app.routers import health, llm
from app.services import llm_provider


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await llm_provider.aclose()


app = FastAPI(title="matthew-api", lifespan=lifespan)
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
app.include_router(llm.router, prefix="/v1")

from fastapi import APIRouter

from app.envelope import EnvelopeRoute

router = APIRouter(route_class=EnvelopeRoute)


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}

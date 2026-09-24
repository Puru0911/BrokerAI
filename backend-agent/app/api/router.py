from fastapi import APIRouter

from app.api.routes.broker import router as broker_router
from app.api.routes.connections import router as connections_router
from app.api.routes.health import router as health_router
from app.api.routes.internal import router as internal_router
from app.api.routes.users import router as users_router

api_router = APIRouter()
api_router.include_router(broker_router, prefix="/broker", tags=["broker"])
api_router.include_router(connections_router, prefix="/broker", tags=["connections"])
api_router.include_router(health_router, prefix="/health", tags=["health"])
api_router.include_router(internal_router, prefix="/internal", tags=["internal"])
api_router.include_router(users_router, prefix="/users", tags=["users"])

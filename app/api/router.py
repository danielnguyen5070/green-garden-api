from fastapi import APIRouter

from app.api.v1 import auth as auth_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth_router.router)

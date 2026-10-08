from fastapi import APIRouter

from app.api.v1 import chat as chat_router
from app.api.v1 import overview as overview_router
from app.db import registry  # noqa: F401
from app.features.admins import router as admins_router
from app.features.auth import router as auth_router
from app.features.categories import public_router as categories_public_router
from app.features.categories import router as categories_router
from app.features.customers import router as customers_router
from app.features.notifications import router as notifications_router
from app.features.orders import public_router as orders_public_router
from app.features.orders import router as orders_router
from app.features.payments import router as payments_router
from app.features.plants import public_router as plants_public_router
from app.features.plants import router as plants_router
from app.features.reviews import public_router as reviews_public_router
from app.features.reviews import router as reviews_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth_router.router)
api_router.include_router(admins_router.router)
api_router.include_router(categories_router.router)
api_router.include_router(plants_router.router)
api_router.include_router(customers_router.router)
api_router.include_router(orders_router.router)
api_router.include_router(overview_router.router)
api_router.include_router(reviews_router.router)
api_router.include_router(notifications_router.router)
api_router.include_router(categories_public_router.router)
api_router.include_router(plants_public_router.router)
api_router.include_router(reviews_public_router.router)
api_router.include_router(orders_public_router.router)
api_router.include_router(payments_router.router)
api_router.include_router(chat_router.router)

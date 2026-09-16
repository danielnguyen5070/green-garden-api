from fastapi import APIRouter

from app.api.v1 import admins as admins_router
from app.api.v1 import auth as auth_router
from app.api.v1 import categories as categories_router
from app.api.v1 import customers as customers_router
from app.api.v1 import orders as orders_router
from app.api.v1 import overview as overview_router
from app.api.v1 import plants as plants_router
from app.api.v1 import storefront as storefront_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth_router.router)
api_router.include_router(admins_router.router)
api_router.include_router(categories_router.router)
api_router.include_router(plants_router.router)
api_router.include_router(customers_router.router)
api_router.include_router(orders_router.router)
api_router.include_router(overview_router.router)
api_router.include_router(storefront_router.router)

"""Import every model so SQLAlchemy resolves string relationships and Alembic sees all tables."""

from app.features.admins.models import Admin
from app.db.base import Base
from app.features.categories.models import Category
from app.features.customers.models import Customer
from app.models.order import Order, OrderStatus, PaymentMethod, PaymentStatus
from app.models.order_item import OrderItem
from app.models.payment_transaction import (
    PaymentMatchStatus,
    PaymentProvider,
    PaymentTransaction,
)
from app.features.plants.models import (
    Plant,
    PlantDifficulty,
    PlantGrowthRate,
    PlantImage,
    PlantImageType,
    PlantPotSize,
    PlantSlugHistory,
    PlantSpaceRequirement,
    PlantSunlight,
    PlantType,
    PlantWatering,
)
from app.features.reviews.models import Review, ReviewStatus
from app.features.notifications.models import Notification, NotificationType

__all__ = [
    "Base",
    "Admin",
    "Category",
    "Customer",
    "Order",
    "OrderStatus",
    "OrderItem",
    "PaymentMatchStatus",
    "PaymentMethod",
    "PaymentProvider",
    "PaymentStatus",
    "PaymentTransaction",
    "Plant",
    "PlantDifficulty",
    "PlantGrowthRate",
    "PlantSpaceRequirement",
    "PlantSunlight",
    "PlantType",
    "PlantWatering",
    "PlantImage",
    "PlantImageType",
    "PlantPotSize",
    "PlantSlugHistory",
    "Review",
    "ReviewStatus",
    "Notification",
    "NotificationType",
]

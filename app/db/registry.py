"""Import every model so SQLAlchemy resolves string relationships and Alembic sees all tables."""

from app.features.admins.models import Admin
from app.db.base import Base
from app.features.categories.models import Category
from app.features.customers.models import Customer
from app.features.orders.models import (
    Order,
    OrderItem,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
)
from app.features.payments.models import (
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

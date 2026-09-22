"""Add plant care and suitability attribute columns.

Revision ID: 010_plant_care_attributes
Revises: 009_plant_long_description
Create Date: 2026-09-22

Nullable enum columns for categorical care attributes and nullable booleans
for suitability flags. Existing plant rows keep NULL until an admin fills them in.

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "010_plant_care_attributes"
down_revision: Union[str, None] = "009_plant_long_description"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

plant_type = postgresql.ENUM(
    "foliage",
    "flowering",
    "succulent",
    "cactus",
    "herb",
    "fern",
    "vine",
    "tree",
    "palm",
    "bamboo",
    "aquatic",
    "other",
    name="plant_type",
    create_type=False,
)
plant_difficulty = postgresql.ENUM(
    "easy",
    "moderate",
    "hard",
    name="plant_difficulty",
    create_type=False,
)
plant_growth_rate = postgresql.ENUM(
    "slow",
    "moderate",
    "fast",
    name="plant_growth_rate",
    create_type=False,
)
plant_sunlight = postgresql.ENUM(
    "full_sun",
    "partial_sun",
    "partial_shade",
    "shade",
    "low_light",
    name="plant_sunlight",
    create_type=False,
)
plant_watering = postgresql.ENUM(
    "low",
    "moderate",
    "high",
    name="plant_watering",
    create_type=False,
)
plant_space_requirement = postgresql.ENUM(
    "small",
    "medium",
    "large",
    name="plant_space_requirement",
    create_type=False,
)


def upgrade() -> None:
    plant_type.create(op.get_bind(), checkfirst=True)
    plant_difficulty.create(op.get_bind(), checkfirst=True)
    plant_growth_rate.create(op.get_bind(), checkfirst=True)
    plant_sunlight.create(op.get_bind(), checkfirst=True)
    plant_watering.create(op.get_bind(), checkfirst=True)
    plant_space_requirement.create(op.get_bind(), checkfirst=True)

    op.add_column("plants", sa.Column("plant_type", plant_type, nullable=True))
    op.add_column("plants", sa.Column("difficulty", plant_difficulty, nullable=True))
    op.add_column("plants", sa.Column("growth_rate", plant_growth_rate, nullable=True))
    op.add_column("plants", sa.Column("sunlight", plant_sunlight, nullable=True))
    op.add_column("plants", sa.Column("watering", plant_watering, nullable=True))
    op.add_column(
        "plants",
        sa.Column("space_requirement", plant_space_requirement, nullable=True),
    )
    op.add_column("plants", sa.Column("indoor_suitable", sa.Boolean(), nullable=True))
    op.add_column("plants", sa.Column("outdoor_suitable", sa.Boolean(), nullable=True))
    op.add_column("plants", sa.Column("pet_safe", sa.Boolean(), nullable=True))
    op.add_column("plants", sa.Column("beginner_friendly", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("plants", "beginner_friendly")
    op.drop_column("plants", "pet_safe")
    op.drop_column("plants", "outdoor_suitable")
    op.drop_column("plants", "indoor_suitable")
    op.drop_column("plants", "space_requirement")
    op.drop_column("plants", "watering")
    op.drop_column("plants", "sunlight")
    op.drop_column("plants", "growth_rate")
    op.drop_column("plants", "difficulty")
    op.drop_column("plants", "plant_type")

    plant_space_requirement.drop(op.get_bind(), checkfirst=True)
    plant_watering.drop(op.get_bind(), checkfirst=True)
    plant_sunlight.drop(op.get_bind(), checkfirst=True)
    plant_growth_rate.drop(op.get_bind(), checkfirst=True)
    plant_difficulty.drop(op.get_bind(), checkfirst=True)
    plant_type.drop(op.get_bind(), checkfirst=True)

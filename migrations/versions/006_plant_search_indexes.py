"""Add trigram indexes for storefront plant keyword search.

Revision ID: 006_plant_search_indexes
Revises: 005_plant_og_image_url
Create Date: 2026-09-20

`ILIKE '%keyword%'` cannot use a btree index. Enable `pg_trgm` and add GIN
trigram indexes on the English and Vietnamese copy columns the storefront
search endpoint matches against.

"""

from typing import Sequence, Union

from alembic import op

revision: str = "006_plant_search_indexes"
down_revision: Union[str, None] = "005_plant_og_image_url"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_plants_name_trgm "
        "ON plants USING gin (name gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_plants_name_vi_trgm "
        "ON plants USING gin (name_vi gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_plants_description_trgm "
        "ON plants USING gin (description gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_plants_description_vi_trgm "
        "ON plants USING gin (description_vi gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_plants_description_vi_trgm")
    op.execute("DROP INDEX IF EXISTS ix_plants_description_trgm")
    op.execute("DROP INDEX IF EXISTS ix_plants_name_vi_trgm")
    op.execute("DROP INDEX IF EXISTS ix_plants_name_trgm")
    # Leave pg_trgm installed: other objects outside this revision may use it.

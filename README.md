# Green Garden API

Backend foundation for the Green Garden storefront (FastAPI + PostgreSQL).

This repository currently provides **infrastructure and database schema only**.
Business API endpoints, admin UI, storefront, and blog are out of scope for this stage.

## Requirements

- Docker and Docker Compose
- Python 3.12+ (only needed for local tooling outside Docker)

PostgreSQL runs **inside Docker** — it is not required on the host.

## Project layout

```
app/
  main.py              # FastAPI app + GET /health
  core/
    config.py          # Pydantic Settings from env
    database.py        # Async SQLAlchemy engine + session dependency
  models/              # SQLAlchemy 2.x ORM models (one file per entity)
migrations/            # Alembic migrations
tests/                 # Basic model / constraint tests
Dockerfile
docker-compose.yml
alembic.ini
requirements.txt
```

Future layers (`api/`, `schemas/`, `services/`) can be added when implementing endpoints.

## Environment variables

Copy the example file and edit secrets:

```bash
cp .env.example .env
```

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | SQLAlchemy async URL (`postgresql+psycopg://...`) |
| `POSTGRES_DB` | PostgreSQL database name |
| `POSTGRES_USER` | PostgreSQL user |
| `POSTGRES_PASSWORD` | PostgreSQL password |
| `POSTGRES_PORT` | Host port mapped to container `5432` (change if `5432` is already in use) |

Do not commit `.env`.

## Docker setup

Start PostgreSQL and the FastAPI app:

```bash
docker compose up --build
```

- API: http://localhost:8000
- Health: http://localhost:8000/health
- Postgres: `localhost:${POSTGRES_PORT}` (credentials from `.env`)

The API waits until Postgres is **healthy** (`pg_isready`), not merely started.
Postgres data is stored in the named volume `postgres_data` and survives restarts.

## Running migrations

Apply all migrations (from the host with env loaded, or inside the API container):

```bash
# Inside the running API container
docker compose exec api alembic upgrade head
```

Or with a local venv pointing at Docker Postgres (set `DATABASE_URL` host to `localhost`):

```bash
alembic upgrade head
```

Verify downgrade of the initial revision:

```bash
docker compose exec api alembic downgrade -1
docker compose exec api alembic upgrade head
```

### Creating a new migration

After changing models:

```bash
docker compose exec api alembic revision --autogenerate -m "describe_change"
docker compose exec api alembic upgrade head
```

**Do not** use SQLAlchemy `create_all()` for production schema management.

## Running tests

With Compose services running and migrations applied:

```bash
docker compose exec api pytest
```

Tests cover connection, relationships, uniqueness, and check constraints
(negative prices, invalid quantities).

## Database architecture

UUID primary keys (`gen_random_uuid()`), timezone-aware timestamps, `NUMERIC(12,2)` for money.

### Tables

| Table | Notes |
|---|---|
| `admins` | Admin users; stores `password_hash` only (no auth yet) |
| `categories` | Soft-deactivated via `is_active` |
| `plants` | Belongs to category; price/stock constraints |
| `plant_images` | External media URLs (`image` / `video`); no binary blobs |
| `plant_pot_sizes` | Size variants with non-negative `price_adjustment` |
| `customers` | Identified by unique `phone` (no accounts) |
| `orders` | `shipping_address` as TEXT; status enum |
| `order_items` | Snapshots of `plant_name`, `unit_price`, `pot_size` |

### Relationships

```
categories 1──N plants 1──N plant_images
                   └──N plant_pot_sizes

customers 1──N orders 1──N order_items N──1 plants
```

### Delete behavior

- Prefer soft deactivation (`is_active`) for admins, categories, plants, customers.
- `orders.customer_id` and `order_items.plant_id` use `ON DELETE RESTRICT` so historical order data is not wiped by deleting customers or plants.
- `plant_images` / `plant_pot_sizes` cascade when a plant row is removed (non-historical).

### Order status

`pending` → `confirmed` → `processing` → `shipping` → `completed` (or `cancelled`)

No payment tables in this schema.

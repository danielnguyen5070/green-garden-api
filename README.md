# Green Garden API

FastAPI backend for the Green Garden storefront and admin panel.

Current scope: **database schema** + **admin authentication** + **admin management API** + **categories management API** + **plants management API** + **public storefront catalogue**.

Full endpoint reference: [`doc.md`](doc.md).

## Requirements

- Docker and Docker Compose
- Python 3.12+ (only for host-side tooling if needed)

PostgreSQL runs **inside Docker** — it is not required on the host.

## Quick start

```bash
cp .env.example .env
# Set a strong JWT_SECRET_KEY in .env for any shared environment

docker compose up --build
docker compose exec api alembic upgrade head
```

- Health: http://localhost:8000/health
- OpenAPI: http://localhost:8000/docs
- Postgres host port: `${POSTGRES_PORT}` (default `5432`; use `5433` if busy)

## Create the first admin

There is **no** public registration endpoint. Bootstrap via CLI:

```bash
docker compose exec -it api python -m app.cli create-admin
```

You will be prompted for name, email, and password (password is hashed with Argon2id and never printed).

After the first admin exists, additional admins can be created from the Admin Dashboard via `POST /api/v1/admins`.

## Admin authentication

| Method | Path | Notes |
|---|---|---|
| POST | `/api/v1/auth/login` | Sets HttpOnly `gg_access_token` + `gg_refresh_token` cookies |
| POST | `/api/v1/auth/logout` | Clears auth cookies (no valid token required) |
| GET | `/api/v1/auth/me` | Requires access cookie |
| POST | `/api/v1/auth/refresh` | Issues a new access cookie from refresh cookie |

Tokens are **never** returned in JSON. Frontends must use `credentials: "include"` and must not store tokens in localStorage/sessionStorage.

TODO (production): rate-limit `POST /api/v1/auth/login`.

### Example login

```bash
curl -c cookies.txt -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@greengarden.vn","password":"your-password"}'

curl -b cookies.txt http://localhost:8000/api/v1/auth/me
```

## Admin management

All endpoints require an authenticated admin (access cookie). Every active admin has the same permissions — there is no role/permission system.

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/admins` | Paginated list (`?page=1&page_size=20`) |
| GET | `/api/v1/admins/{id}` | Single admin |
| POST | `/api/v1/admins` | Create admin (`is_active=true`) |
| PATCH | `/api/v1/admins/{id}` | Update name / email / is_active |
| PATCH | `/api/v1/admins/{id}/status` | Activate / deactivate |
| PATCH | `/api/v1/admins/{id}/password` | Set a new password (Argon2id) |

Responses never include `password`, `password_hash`, or JWT tokens. Duplicate emails return `409 Conflict`. An admin cannot deactivate their own account.

### Example: create admin

```bash
curl -b cookies.txt -X POST http://localhost:8000/api/v1/admins \
  -H "Content-Type: application/json" \
  -d '{"name":"Nguyen Van A","email":"admin2@example.com","password":"StrongPassword123!"}'
```

## Categories management

Admin-only (access cookie). Categories are never hard-deleted — deactivate them instead, which keeps existing plants and order history intact.

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/categories` | Pagination + `search` (name/slug) and `is_active` |
| GET | `/api/v1/categories/{category_id}` | Detail, active or inactive |
| POST | `/api/v1/categories` | `name` + `slug` required; slug normalized and unique |
| PATCH | `/api/v1/categories/{category_id}` | Partial update |
| PATCH | `/api/v1/categories/{category_id}/status` | Activate / deactivate |

Listings are ordered by `sort_order ASC`, then `created_at ASC`. Duplicate slug returns `409 Conflict`.

### Example: create category

```bash
curl -b cookies.txt -X POST http://localhost:8000/api/v1/categories \
  -H "Content-Type: application/json" \
  -d '{"name":"Indoor Plants","slug":"indoor-plants","sort_order":1}'
```

## Plants management

Admin-only (access cookie). Plants are never hard-deleted — deactivate them instead.

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/plants` | Pagination + `search`, `category_id`, `is_active`, `is_featured`, `min_price`, `max_price`, `sort`, `order` |
| GET | `/api/v1/plants/{plant_id}` | Detail with category, images and pot sizes |
| POST | `/api/v1/plants` | Validates category, unique slug and SKU |
| PATCH | `/api/v1/plants/{plant_id}` | Partial update |
| PATCH | `/api/v1/plants/{plant_id}/status` | Activate / deactivate |
| GET/POST | `/api/v1/plants/{plant_id}/images` | External media URLs (`image` / `video`) |
| PATCH/DELETE | `/api/v1/plants/{plant_id}/images/{image_id}` | Image must belong to the plant |
| GET/POST | `/api/v1/plants/{plant_id}/pot-sizes` | Pot size variants |
| PATCH/DELETE | `/api/v1/plants/{plant_id}/pot-sizes/{size_id}` | Pot size must belong to the plant |

Duplicate slug or SKU returns `409 Conflict`; an unknown category returns `404 Not Found`. Money uses `Decimal` / `NUMERIC(12,2)` and is serialized as a string.

### Example: create plant

```bash
curl -b cookies.txt -X POST http://localhost:8000/api/v1/plants \
  -H "Content-Type: application/json" \
  -d '{"category_id":"<category-uuid>","name":"Monstera Deliciosa","slug":"monstera-deliciosa","price":250000,"stock":20,"sku":"MON-001"}'
```

## Public storefront

No authentication. Only active records are exposed, and admin fields (`sku`, `stock`, `is_active`, timestamps) are omitted.

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/storefront/categories` | Active categories for navigation |
| GET | `/api/v1/storefront/plants` | Active catalogue with the same filters (minus `is_active`) |
| GET | `/api/v1/storefront/plants/{slug}` | Detail by slug; active pot sizes only |

Admin detail uses UUIDs (`/api/v1/plants/{plant_id}`) and the storefront uses slugs, so the two never collide on one route.

```bash
curl http://localhost:8000/api/v1/storefront/plants/monstera-deliciosa
```

## Environment variables

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | SQLAlchemy async URL |
| `TEST_DATABASE_URL` | Separate DB for pytest |
| `POSTGRES_*` | Docker Postgres settings |
| `JWT_SECRET_KEY` | Signing secret (required) |
| `JWT_ALGORITHM` | Default `HS256` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Access JWT lifetime |
| `REFRESH_TOKEN_EXPIRE_DAYS` | Refresh JWT lifetime |
| `AUTH_COOKIE_SECURE` | `true` in production (HTTPS) |
| `AUTH_COOKIE_SAMESITE` | `lax` / `strict` / `none` |
| `CORS_ORIGINS` | Comma-separated Next.js origins |

Do not commit `.env`. Never use `allow_origins=["*"]` with cookie credentials.

## Migrations

```bash
docker compose exec api alembic upgrade head
docker compose exec api alembic revision --autogenerate -m "describe_change"
```

Do **not** use SQLAlchemy `create_all()` for production schema management.

## Tests

```bash
docker compose exec api pytest
```

Auth and admin tests run against `TEST_DATABASE_URL` (`green_garden_test`), not the primary app database.

## Project layout

```
app/
  main.py
  cli.py                 # python -m app.cli create-admin
  api/v1/auth.py         # Auth routes
  api/v1/admins.py       # Admin management routes
  api/v1/categories.py   # Categories (admin)
  api/v1/plants.py       # Plants / images / pot sizes (admin)
  api/v1/storefront.py   # Public catalogue routes
  core/security.py       # Argon2id + JWT
  core/cookies.py        # HttpOnly cookie helpers
  core/text.py           # Slug / SKU normalization
  dependencies/auth.py   # get_current_admin()
  schemas/auth.py
  schemas/admin.py
  schemas/category.py
  schemas/plant.py
  schemas/plant_image.py
  schemas/plant_pot_size.py
  services/auth_service.py
  services/admin_service.py
  services/category_service.py
  services/plant_service.py
  models/
```

## Database architecture

UUID PKs, timezone-aware timestamps, `NUMERIC(12,2)` for money.

Tables: `admins`, `categories`, `plants`, `plant_images`, `plant_pot_sizes`, `customers`, `orders`, `order_items`.

Customers have **no** login — identified by unique phone only.

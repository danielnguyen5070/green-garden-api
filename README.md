# Green Garden API

FastAPI backend for the Green Garden storefront and admin panel.

Current scope: **database schema** + **admin authentication** + **admin management API** + **categories management API** + **plants management API** + **customers management API** + **orders management API** + **public storefront catalogue**.

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

`name` / `description` carry the English (default) copy and the optional `name_vi` / `description_vi` the Vietnamese copy. The `slug` is shared by both locales.

### Example: create category

```bash
curl -b cookies.txt -X POST http://localhost:8000/api/v1/categories \
  -H "Content-Type: application/json" \
  -d '{"name":"Fruit Trees","name_vi":"Cây ăn quả","slug":"fruit-trees","sort_order":1}'
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

Plants carry optional `name_vi`, `description_vi` and `price_vi` alongside the English fields, and pot sizes carry `price_adjustment_vi` alongside `price_adjustment`, so each locale is priced independently.

### Example: create plant

```bash
curl -b cookies.txt -X POST http://localhost:8000/api/v1/plants \
  -H "Content-Type: application/json" \
  -d '{"category_id":"<category-uuid>","name":"Monstera Deliciosa","name_vi":"Cây Trầu Bà Nam Mỹ","slug":"monstera-deliciosa","price":25,"price_vi":650000,"stock":20,"sku":"MON-001"}'
```

## Customers management

Admin-only (access cookie). Customers are guests: no password, no login, no customer-facing endpoints — the unique phone number is their identity. They are never hard-deleted; deactivate them instead, which keeps their order history intact.

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/customers` | Pagination + `search` (phone/name/email) and `is_active` |
| GET | `/api/v1/customers/{customer_id}` | Detail, active or inactive |
| POST | `/api/v1/customers` | `phone` + `name` required; duplicate phone returns `409` |
| PATCH | `/api/v1/customers/{customer_id}` | Update phone / name / email |
| PATCH | `/api/v1/customers/{customer_id}/status` | Activate / deactivate |

Phone numbers are stored without spaces, so `090 123 4567` and `0901234567` are the same customer. An inactive customer cannot place new orders.

### Example: create customer

```bash
curl -b cookies.txt -X POST http://localhost:8000/api/v1/customers \
  -H "Content-Type: application/json" \
  -d '{"phone":"0901234567","name":"Nguyen Van A","email":"customer@example.com"}'
```

## Orders management

Admin-only (access cookie). Orders are historical business records: there is no `DELETE` and no way to edit their contents — only `status` moves forward, or the order is cancelled.

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/orders` | Pagination + `search` (order number / customer phone / name), `status`, `customer_id`, `date_from`, `date_to` |
| GET | `/api/v1/orders/{order_id}` | Detail with customer and item snapshots |
| POST | `/api/v1/orders` | Resolves the customer by phone, prices the order, deducts stock |
| PATCH | `/api/v1/orders/{order_id}/status` | Advance the pipeline or cancel |

Key rules:

- **The backend owns the money.** `unit_price = plant.price + pot_size.price_adjustment` and `total_amount = sum(unit_price × quantity)`, all in `Decimal` / `NUMERIC(12,2)`. Prices or totals sent by the client are ignored.
- **Items are snapshots.** `plant_name`, `unit_price` and `pot_size` are copied at purchase time, so renaming, repricing, deactivating or retiring a plant never rewrites an existing order.
- **One transaction.** Customer upsert, order, items and stock deduction commit together, with the plant rows locked so concurrent checkouts cannot oversell. Insufficient stock returns `400` and writes nothing.
- **Customers by phone.** A known phone reuses the existing customer (their stored name is preserved); an unknown phone creates one.
- **Status pipeline.** `pending → confirmed → processing → shipping → completed`, forward-only, cancellable from any non-terminal status. Cancelling restores stock exactly once; `completed` and `cancelled` are final.

### Example: create order

```bash
curl -b cookies.txt -X POST http://localhost:8000/api/v1/orders \
  -H "Content-Type: application/json" \
  -d '{"customer":{"phone":"0901234567","name":"Nguyen Van A"},"shipping_address":"123 Nguyen Trai, District 1, HCMC","items":[{"plant_id":"<plant-uuid>","quantity":2,"pot_size":"Large"}]}'
```

## Dashboard overview

Admin-only (access cookie), read-only, uncached. One request returns everything the admin dashboard renders.

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/overview` | `summary`, `sales.today` / `sales.this_month`, `orders_by_status`, `revenue_by_day`, `top_plants`, `low_stock`, `recent_orders` |

Key rules:

- **Revenue means `completed` orders only.** Other statuses are counted, but never earn money; revenue is `SUM(orders.total_amount)` and reads `"0.00"` instead of `null`.
- **Aggregated in PostgreSQL.** Seven fixed queries built from `COUNT` / `SUM` / `GROUP BY` / `LIMIT` — no table is loaded into Python, so the cost does not grow with the shop. No analytics, statistics or cache table was added.
- **UTC everywhere.** "Today" and "this month" are UTC windows, and `revenue_by_day` covers the 1st of the current month up to today with a zero-filled entry for every quiet day.
- **Snapshots for history.** Top sellers are named from `order_items.plant_name`, so renaming a plant never rewrites past sales.
- **Low stock** means an **active** plant with `stock <= 5`, scarcest first, at most 5 rows.

```bash
curl -b cookies.txt http://localhost:8000/api/v1/overview
```

## Public storefront

No authentication. Only active records are exposed, and admin fields (`sku`, `is_active`, timestamps) are omitted.

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/storefront/categories` | Active categories for navigation |
| GET | `/api/v1/storefront/plants` | Active catalogue with the same filters (minus `is_active`) |
| GET | `/api/v1/storefront/plants/{slug}` | Detail by slug; active pot sizes only |

The plant listing returns a complete catalogue card: `name` / `name_vi`, `description` / `description_vi`, `price` / `price_vi`, the shared `slug`, `stock`, `is_featured`, the category summary and the plant's `images` ordered by `sort_order`. Media is eager-loaded with one extra query per page, so the homepage renders without a detail call per plant. The detail endpoint still reports availability as `in_stock` rather than an exact count.

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
  api/v1/customers.py    # Customers (admin)
  api/v1/orders.py       # Orders (admin)
  api/v1/overview.py     # Dashboard statistics (admin)
  api/v1/storefront.py   # Public catalogue routes
  core/security.py       # Argon2id + JWT
  core/cookies.py        # HttpOnly cookie helpers
  core/text.py           # Slug / SKU / phone normalization
  dependencies/auth.py   # get_current_admin()
  schemas/auth.py
  schemas/admin.py
  schemas/category.py
  schemas/plant.py
  schemas/plant_image.py
  schemas/plant_pot_size.py
  schemas/customer.py
  schemas/order.py
  schemas/overview.py
  services/auth_service.py
  services/admin_service.py
  services/category_service.py
  services/plant_service.py
  services/customer_service.py
  services/order_service.py
  services/overview_service.py
  models/
```

## Database architecture

UUID PKs, timezone-aware timestamps, `NUMERIC(12,2)` for money.

Tables: `admins`, `categories`, `plants`, `plant_images`, `plant_pot_sizes`, `customers`, `orders`, `order_items`.

Customers have **no** login — identified by unique phone only.

Orders keep their shipping address and their line items (`plant_name`, `unit_price`, `pot_size`) as snapshots, so there is no separate address table and no dependency on the current catalogue. There is no payment table.

Indexes: `customers.phone` (unique), `customers.name`, `customers.is_active`, `orders.order_number` (unique), `orders.customer_id`, `orders.status`, `orders.created_at`, `order_items.order_id`, `order_items.plant_id`.

The dashboard overview needed no new index or migration: its order, order item and plant filters are already covered by `orders.status`, `orders.created_at`, `order_items.order_id`, `order_items.plant_id` and `plants.is_active`.

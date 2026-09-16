# Green Garden API Documentation

Base URL (local): `http://localhost:8000`

Interactive OpenAPI UI: [http://localhost:8000/docs](http://localhost:8000/docs)

API prefix for versioned routes: `/api/v1`

---

## Overview

| Area | Endpoints | Auth |
|---|---|---|
| Health | `GET /health` | Public |
| Auth | `/api/v1/auth/*` | Mixed |
| Admin management | `/api/v1/admins/*` | Admin |
| Categories management | `/api/v1/categories/*` | Admin |
| Plants management | `/api/v1/plants/*` | Admin |
| Customers management | `/api/v1/customers/*` | Admin |
| Orders management | `/api/v1/orders/*` | Admin |
| Public storefront | `/api/v1/storefront/*` | Public |

There is **no** public registration. Bootstrap the first admin with:

```bash
docker compose exec -it api python -m app.cli create-admin
```

There is **no** role/permission system. Every authenticated active admin has the same access.

---

## Authentication

Auth uses **JWT in HttpOnly cookies**. Tokens are **never** returned in JSON response bodies.

| Cookie | Default name | Purpose | Default lifetime |
|---|---|---|---|
| Access | `gg_access_token` | Authenticate protected requests | 30 minutes |
| Refresh | `gg_refresh_token` | Issue a new access cookie | 7 days |

Cookie flags (from settings):

- `HttpOnly`: always `true`
- `Secure`: `AUTH_COOKIE_SECURE` (use `true` in production)
- `SameSite`: `AUTH_COOKIE_SAMESITE` (`lax` / `strict` / `none`)
- `Path`: `/` by default

### Frontend requirements

- Send cookies on every request: `credentials: "include"`
- Do **not** store tokens in `localStorage` / `sessionStorage`
- CORS origins must be explicit (never `*` with credentialed cookies)

### Auth header

Protected endpoints do **not** use `Authorization: Bearer`. The access token is read from the access cookie.

---

## Common schemas

### AdminResponse

Returned by auth and admin management endpoints. Never includes `password` or `password_hash`.

```json
{
  "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "name": "Nguyen Van A",
  "email": "admin@example.com",
  "is_active": true,
  "created_at": "2026-09-15T09:00:00Z",
  "updated_at": "2026-09-15T09:00:00Z"
}
```

| Field | Type | Notes |
|---|---|---|
| `id` | UUID | Primary key |
| `name` | string | Display name |
| `email` | string | Normalized (trimmed + lowercase) |
| `is_active` | boolean | Inactive admins cannot authenticate |
| `created_at` | datetime (ISO 8601) | UTC |
| `updated_at` | datetime (ISO 8601) | UTC |

### MessageResponse

```json
{
  "message": "Logged out successfully"
}
```

### Password rules

Used when creating an admin or changing a password:

- Minimum 8 characters
- At least one letter
- At least one digit
- Maximum 128 characters

### Error shape

FastAPI default:

```json
{
  "detail": "Error message or validation errors"
}
```

| Status | Meaning |
|---|---|
| `400` | Business rule violation (e.g. self-deactivation) |
| `401` | Not authenticated / invalid credentials / invalid token |
| `404` | Resource not found |
| `409` | Conflict (duplicate email) |
| `422` | Invalid request body / query params |

---

## Health

### `GET /health`

Public. Liveness check.

**Auth:** none

**Response `200`**

```json
{
  "status": "ok"
}
```

---

## Auth API

Base path: `/api/v1/auth`

### `POST /api/v1/auth/login`

Authenticate an admin and set access + refresh cookies.

**Auth:** none

**Request body**

```json
{
  "email": "admin@example.com",
  "password": "your-password"
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `email` | email | yes | Normalized before lookup |
| `password` | string | yes | Min length 1 |

**Response `200`**

```json
{
  "admin": {
    "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "name": "Nguyen Van A",
    "email": "admin@example.com",
    "is_active": true,
    "created_at": "2026-09-15T09:00:00Z",
    "updated_at": "2026-09-15T09:00:00Z"
  }
}
```

Also sets cookies:

- `gg_access_token`
- `gg_refresh_token`

**Errors**

| Status | When |
|---|---|
| `401` | Invalid email/password, or inactive admin |
| `422` | Invalid body |

**Example**

```bash
curl -c cookies.txt -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@example.com","password":"your-password"}'
```

---

### `POST /api/v1/auth/logout`

Clear auth cookies. Does not require a valid access token.

**Auth:** none

**Response `200`**

```json
{
  "message": "Logged out successfully"
}
```

**Example**

```bash
curl -b cookies.txt -c cookies.txt -X POST http://localhost:8000/api/v1/auth/logout
```

---

### `GET /api/v1/auth/me`

Return the currently authenticated admin.

**Auth:** required (access cookie)

**Response `200`** — `AdminResponse`

**Errors**

| Status | When |
|---|---|
| `401` | Missing/invalid/expired access cookie, or admin inactive/missing |

**Example**

```bash
curl -b cookies.txt http://localhost:8000/api/v1/auth/me
```

---

### `POST /api/v1/auth/refresh`

Validate the refresh cookie and issue a new access cookie.

**Auth:** refresh cookie (`gg_refresh_token`)

**Response `200`**

```json
{
  "message": "Token refreshed"
}
```

Also updates cookie: `gg_access_token`

**Errors**

| Status | When |
|---|---|
| `401` | Missing/invalid/expired refresh cookie, wrong token type, or admin inactive/missing |

**Example**

```bash
curl -b cookies.txt -c cookies.txt -X POST http://localhost:8000/api/v1/auth/refresh
```

---

## Admin management API

Base path: `/api/v1/admins`

All endpoints below require an authenticated **active** admin (access cookie).

---

### `GET /api/v1/admins`

List admins with simple pagination.

**Auth:** required

**Query params**

| Param | Type | Default | Constraints |
|---|---|---|---|
| `page` | integer | `1` | `>= 1` |
| `page_size` | integer | `20` | `1..100` |

**Response `200`**

```json
{
  "items": [
    {
      "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
      "name": "Nguyen Van A",
      "email": "admin@example.com",
      "is_active": true,
      "created_at": "2026-09-15T09:00:00Z",
      "updated_at": "2026-09-15T09:00:00Z"
    }
  ],
  "page": 1,
  "page_size": 20,
  "total": 1
}
```

Items are ordered by `created_at` descending.

**Errors**

| Status | When |
|---|---|
| `401` | Not authenticated |
| `422` | Invalid query params |

**Example**

```bash
curl -b cookies.txt "http://localhost:8000/api/v1/admins?page=1&page_size=20"
```

---

### `GET /api/v1/admins/{id}`

Get a single admin by UUID.

**Auth:** required

**Path params**

| Param | Type |
|---|---|
| `id` | UUID |

**Response `200`** — `AdminResponse`

**Errors**

| Status | When |
|---|---|
| `401` | Not authenticated |
| `404` | Admin does not exist |
| `422` | Invalid UUID |

**Example**

```bash
curl -b cookies.txt http://localhost:8000/api/v1/admins/3fa85f64-5717-4562-b3fc-2c963f66afa6
```

---

### `POST /api/v1/admins`

Create a new admin. `is_active` defaults to `true`. Password is hashed with Argon2id; only `password_hash` is stored.

**Auth:** required

**Request body**

```json
{
  "name": "Nguyen Van A",
  "email": "admin2@example.com",
  "password": "StrongPassword123!"
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `name` | string | yes | 1–255 chars after trim |
| `email` | email | yes | Normalized; must be unique |
| `password` | string | yes | Strength rules above |

**Response `201`** — `AdminResponse`

**Errors**

| Status | When |
|---|---|
| `401` | Not authenticated |
| `409` | Email already exists |
| `422` | Invalid body / weak password |

**Example**

```bash
curl -b cookies.txt -X POST http://localhost:8000/api/v1/admins \
  -H "Content-Type: application/json" \
  -d '{"name":"Nguyen Van A","email":"admin2@example.com","password":"StrongPassword123!"}'
```

---

### `PATCH /api/v1/admins/{id}`

Partial update of an admin.

**Auth:** required

**Path params**

| Param | Type |
|---|---|
| `id` | UUID |

**Request body** (all fields optional)

```json
{
  "name": "Updated Name",
  "email": "updated@example.com",
  "is_active": true
}
```

| Field | Type | Notes |
|---|---|---|
| `name` | string \| null | 1–255 chars after trim |
| `email` | email \| null | Must be unique if changed |
| `is_active` | boolean \| null | Cannot set own account to `false` |

**Response `200`** — `AdminResponse`

**Errors**

| Status | When |
|---|---|
| `400` | Trying to deactivate your own account |
| `401` | Not authenticated |
| `404` | Admin does not exist |
| `409` | Email already used by another admin |
| `422` | Invalid body |

**Example**

```bash
curl -b cookies.txt -X PATCH http://localhost:8000/api/v1/admins/3fa85f64-5717-4562-b3fc-2c963f66afa6 \
  -H "Content-Type: application/json" \
  -d '{"name":"Updated Name"}'
```

---

### `PATCH /api/v1/admins/{id}/status`

Activate or deactivate an admin.

**Auth:** required

**Path params**

| Param | Type |
|---|---|
| `id` | UUID |

**Request body**

```json
{
  "is_active": false
}
```

| Field | Type | Required |
|---|---|---|
| `is_active` | boolean | yes |

An admin **cannot** deactivate their own account.

**Response `200`** — `AdminResponse`

**Errors**

| Status | When |
|---|---|
| `400` | Self-deactivation attempt |
| `401` | Not authenticated |
| `404` | Admin does not exist |
| `422` | Invalid body |

**Example**

```bash
curl -b cookies.txt -X PATCH http://localhost:8000/api/v1/admins/3fa85f64-5717-4562-b3fc-2c963f66afa6/status \
  -H "Content-Type: application/json" \
  -d '{"is_active":false}'
```

---

### `PATCH /api/v1/admins/{id}/password`

Set a new password for an admin. Hashed with Argon2id before save.

**Auth:** required

**Path params**

| Param | Type |
|---|---|
| `id` | UUID |

**Request body**

```json
{
  "password": "NewStrongPassword123!"
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `password` | string | yes | Strength rules above |

**Response `200`**

```json
{
  "message": "Password updated successfully"
}
```

Never returns the password or `password_hash`.

**Errors**

| Status | When |
|---|---|
| `401` | Not authenticated |
| `404` | Admin does not exist |
| `422` | Invalid body / weak password |

**Example**

```bash
curl -b cookies.txt -X PATCH http://localhost:8000/api/v1/admins/3fa85f64-5717-4562-b3fc-2c963f66afa6/password \
  -H "Content-Type: application/json" \
  -d '{"password":"NewStrongPassword123!"}'
```

---

## Categories management API

Base path: `/api/v1/categories`

All category endpoints require an authenticated **active** admin (access cookie) and can see both active and inactive categories. The public navigation list is `GET /api/v1/storefront/categories`.

There is **no** `DELETE /api/v1/categories/{id}`. Retire a category with `PATCH /api/v1/categories/{id}/status`, which keeps existing plants and order history intact.

### CategoryResponse

`CategoryListItem` (list rows) currently carries the same fields.

```json
{
  "id": "8c1f1a2e-2b44-4f8e-9a47-4a1d2f2b7f10",
  "name": "Fruit Trees",
  "name_vi": "Cây ăn quả",
  "slug": "fruit-trees",
  "description": "Fruit trees for your garden.",
  "description_vi": "Các loại cây ăn quả phù hợp cho khu vườn.",
  "image_url": "https://example.com/fruit-trees.jpg",
  "sort_order": 1,
  "is_active": true,
  "created_at": "2026-09-16T09:00:00Z",
  "updated_at": "2026-09-16T09:00:00Z"
}
```

### Field rules

`name` / `description` hold the English (default) copy and `name_vi` / `description_vi` the Vietnamese copy. The `slug` is shared by both locales — there is no `slug_vi`.

| Field | Type | Rules |
|---|---|---|
| `name` | string | Required, trimmed, max 255 |
| `name_vi` | string \| null | Optional, trimmed, max 255 |
| `slug` | string | Required, normalized to `a-z0-9-`, unique |
| `description` | string \| null | Optional, trimmed |
| `description_vi` | string \| null | Optional, trimmed |
| `image_url` | URL \| null | Optional, valid http(s), max 1024 |
| `sort_order` | integer | `>= 0`, defaults `0` |
| `is_active` | boolean | Defaults `true` |

---

### `GET /api/v1/categories`

Paginated admin listing, ordered by `sort_order ASC` then `created_at ASC`.

**Auth:** required

**Query params**

| Param | Type | Default | Notes |
|---|---|---|---|
| `page` | integer | `1` | `>= 1` |
| `page_size` | integer | `20` | `1..100` |
| `search` | string | — | Matches `name` or `slug` (case-insensitive) |
| `is_active` | boolean | — | Omit to return both active and inactive |

**Response `200`**

```json
{
  "items": [
    {
      "id": "8c1f1a2e-2b44-4f8e-9a47-4a1d2f2b7f10",
      "name": "Fruit Trees",
      "name_vi": "Cây ăn quả",
      "slug": "fruit-trees",
      "description": "Fruit trees for your garden.",
      "description_vi": "Các loại cây ăn quả phù hợp cho khu vườn.",
      "image_url": "https://example.com/fruit-trees.jpg",
      "sort_order": 1,
      "is_active": true,
      "created_at": "2026-09-16T09:00:00Z",
      "updated_at": "2026-09-16T09:00:00Z"
    }
  ],
  "page": 1,
  "page_size": 20,
  "total": 1
}
```

**Errors:** `401`, `422`

```bash
curl -b cookies.txt "http://localhost:8000/api/v1/categories?page=1&page_size=20&search=indoor&is_active=true"
```

---

### `GET /api/v1/categories/{category_id}`

**Auth:** required

**Response `200`** — `CategoryResponse` (active or inactive)

**Errors**

| Status | When |
|---|---|
| `401` | Not authenticated |
| `404` | Category does not exist |
| `422` | `category_id` is not a UUID |

```bash
curl -b cookies.txt http://localhost:8000/api/v1/categories/8c1f1a2e-2b44-4f8e-9a47-4a1d2f2b7f10
```

---

### `POST /api/v1/categories`

**Auth:** required

**Request body**

```json
{
  "name": "Fruit Trees",
  "name_vi": "Cây ăn quả",
  "slug": "fruit-trees",
  "description": "Fruit trees for your garden.",
  "description_vi": "Các loại cây ăn quả phù hợp cho khu vườn.",
  "image_url": "https://example.com/fruit-trees.jpg",
  "sort_order": 1,
  "is_active": true
}
```

Only `name` and `slug` are required. Omitted Vietnamese fields are stored as `null`.

**Response `201`** — `CategoryResponse`

**Errors**

| Status | When |
|---|---|
| `401` | Not authenticated |
| `409` | Slug already exists |
| `422` | Invalid body (empty name, unusable slug, bad URL, negative `sort_order`) |

```bash
curl -b cookies.txt -X POST http://localhost:8000/api/v1/categories \
  -H "Content-Type: application/json" \
  -d '{"name":"Fruit Trees","name_vi":"Cây ăn quả","slug":"fruit-trees","sort_order":1}'
```

---

### `PATCH /api/v1/categories/{category_id}`

Partial update; all fields optional. Changing the slug re-checks uniqueness. Sending `"description": null`, `"image_url": null`, `"name_vi": null` or `"description_vi": null` clears the field; omitting a field leaves it as is, so Vietnamese copy can be updated without touching the English values.

**Auth:** required

**Request body**

```json
{
  "name_vi": "Cây ăn quả",
  "description_vi": "Các loại cây ăn quả phù hợp cho khu vườn.",
  "sort_order": 2
}
```

**Response `200`** — `CategoryResponse`

**Errors:** `401`, `404`, `409` (slug), `422`

---

### `PATCH /api/v1/categories/{category_id}/status`

**Auth:** required

**Request body**

```json
{
  "is_active": false
}
```

Deactivation is always allowed, even when the category still has active plants: the plants keep their `category_id` and stay untouched so product and order history remain valid. Records are never deleted.

**Response `200`** — `CategoryResponse`

**Errors:** `401`, `404`, `422`

```bash
curl -b cookies.txt -X PATCH http://localhost:8000/api/v1/categories/8c1f1a2e-2b44-4f8e-9a47-4a1d2f2b7f10/status \
  -H "Content-Type: application/json" \
  -d '{"is_active":false}'
```

---

## Plants management API

Base path: `/api/v1/plants`

All plant endpoints require an authenticated **active** admin (access cookie) and can see both active and inactive plants. The public catalogue lives under `/api/v1/storefront` (see below).

There is **no** `DELETE /api/v1/plants/{id}`. Retire a plant with `PATCH /api/v1/plants/{id}/status`.

### Shared schemas

#### PlantResponse (detail)

```json
{
  "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "category_id": "8c1f1a2e-2b44-4f8e-9a47-4a1d2f2b7f10",
  "category": {
    "id": "8c1f1a2e-2b44-4f8e-9a47-4a1d2f2b7f10",
    "name": "Fruit Trees",
    "name_vi": "Cây ăn quả",
    "slug": "fruit-trees"
  },
  "name": "Monstera Deliciosa",
  "name_vi": "Cây Trầu Bà Nam Mỹ",
  "slug": "monstera-deliciosa",
  "description": "A beautiful tropical indoor plant.",
  "description_vi": "Một loại cây nhiệt đới đẹp, phù hợp trồng trong nhà.",
  "price": "25.00",
  "price_vi": "650000.00",
  "stock": 20,
  "sku": "MON-001",
  "is_featured": true,
  "is_active": true,
  "created_at": "2026-09-16T09:00:00Z",
  "updated_at": "2026-09-16T09:00:00Z",
  "images": [],
  "pot_sizes": []
}
```

`PlantListItem` is the lightweight listing row: same fields **without** `description`, `description_vi`, `images` and `pot_sizes`.

#### Field rules

`name` / `description` / `price` hold the English (default) locale and `name_vi` / `description_vi` / `price_vi` the Vietnamese one. The `slug` is shared by both locales — there is no `slug_vi`.

| Field | Type | Rules |
|---|---|---|
| `category_id` | UUID | Must reference an existing category |
| `name` | string | Required, trimmed, max 255 |
| `name_vi` | string \| null | Optional, trimmed, max 255 |
| `slug` | string | Required, normalized to `a-z0-9-`, unique |
| `description` | string \| null | Optional, trimmed |
| `description_vi` | string \| null | Optional, trimmed |
| `price` | Decimal (string in JSON) | `>= 0`, `NUMERIC(12,2)` |
| `price_vi` | Decimal \| null | Optional, `>= 0`, `NUMERIC(12,2)` — DB check `ck_plants_price_vi_non_negative` |
| `stock` | integer | `>= 0` |
| `sku` | string | Required, trimmed + uppercased, unique, max 100 |
| `is_featured` | boolean | Defaults `false` |
| `is_active` | boolean | Defaults `true` |

Money is always `Decimal` / PostgreSQL `NUMERIC(12,2)` — never floats. JSON encodes it as a string.

---

### `GET /api/v1/plants`

Paginated admin listing. Default order is `created_at DESC`.

**Auth:** required

**Query params**

| Param | Type | Default | Notes |
|---|---|---|---|
| `page` | integer | `1` | `>= 1` |
| `page_size` | integer | `20` | `1..100` |
| `search` | string | — | Matches `name` or `sku` (case-insensitive) |
| `category_id` | UUID | — | Filter by category |
| `is_active` | boolean | — | Filter by status |
| `is_featured` | boolean | — | Filter featured plants |
| `min_price` | Decimal | — | `>= 0` |
| `max_price` | Decimal | — | `>= 0` |
| `sort` | enum | `created_at` | `created_at` \| `name` \| `price` \| `stock` |
| `order` | enum | `desc` | `asc` \| `desc` |

**Response `200`**

```json
{
  "items": [],
  "page": 1,
  "page_size": 20,
  "total": 100
}
```

**Errors:** `401`, `422`

**Example**

```bash
curl -b cookies.txt "http://localhost:8000/api/v1/plants?page=1&page_size=20&search=monstera&sort=price&order=asc"
```

---

### `GET /api/v1/plants/{plant_id}`

Full detail including category, images and pot sizes (eager-loaded, no N+1).

**Auth:** required

**Response `200`** — `PlantResponse`

**Errors:** `401`, `404`, `422`

```bash
curl -b cookies.txt http://localhost:8000/api/v1/plants/3fa85f64-5717-4562-b3fc-2c963f66afa6
```

---

### `POST /api/v1/plants`

**Auth:** required

**Request body**

```json
{
  "category_id": "8c1f1a2e-2b44-4f8e-9a47-4a1d2f2b7f10",
  "name": "Monstera Deliciosa",
  "name_vi": "Cây Trầu Bà Nam Mỹ",
  "slug": "monstera-deliciosa",
  "description": "A beautiful tropical indoor plant.",
  "description_vi": "Một loại cây nhiệt đới đẹp, phù hợp trồng trong nhà.",
  "price": 25.00,
  "price_vi": 650000,
  "stock": 20,
  "sku": "MON-001",
  "is_featured": true,
  "is_active": true
}
```

Vietnamese fields are optional; omitting them stores `null`.

**Response `201`** — `PlantResponse`

**Errors**

| Status | When |
|---|---|
| `401` | Not authenticated |
| `404` | Category does not exist |
| `409` | Slug or SKU already used |
| `422` | Invalid body (negative price/stock, empty name, unusable slug) |

```bash
curl -b cookies.txt -X POST http://localhost:8000/api/v1/plants \
  -H "Content-Type: application/json" \
  -d '{"category_id":"8c1f1a2e-2b44-4f8e-9a47-4a1d2f2b7f10","name":"Monstera Deliciosa","slug":"monstera-deliciosa","price":250000,"stock":20,"sku":"MON-001"}'
```

---

### `PATCH /api/v1/plants/{plant_id}`

Partial update; all fields optional.

**Auth:** required

**Request body**

```json
{
  "name": "Monstera Deliciosa XL",
  "price": 32.00,
  "name_vi": "Cây Trầu Bà Nam Mỹ XL",
  "price_vi": 820000
}
```

Changing `category_id` re-validates the category, and changing `slug` / `sku` re-checks uniqueness. Sending `"name_vi": null`, `"description_vi": null` or `"price_vi": null` clears that field; omitted fields keep their stored values, so the two locales can be edited independently.

**Response `200`** — `PlantResponse`

**Errors:** `401`, `404` (plant or category), `409` (slug/SKU), `422`

---

### `PATCH /api/v1/plants/{plant_id}/status`

Soft activate/deactivate. Records are never deleted, and inactive plants disappear from the storefront.

**Auth:** required

**Request body**

```json
{
  "is_active": false
}
```

**Response `200`** — `PlantResponse`

**Errors:** `401`, `404`, `422`

---

## Plant images API

Base path: `/api/v1/plants/{plant_id}/images`

Only external media **URLs** are stored — there is no file upload service in this project. Images are ordered by `sort_order`, then `created_at`.

### PlantImageResponse

```json
{
  "id": "5a0b9c2d-1e3f-4a5b-8c7d-9e0f1a2b3c4d",
  "plant_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "url": "https://cdn.example.com/monstera.jpg",
  "type": "image",
  "alt_text": "Monstera Deliciosa",
  "sort_order": 0,
  "created_at": "2026-09-16T09:00:00Z"
}
```

| Field | Type | Rules |
|---|---|---|
| `url` | URL | Required, valid http(s), max 1024 chars |
| `type` | enum | `image` \| `video` (DB enum `plant_image_type`), defaults `image` |
| `alt_text` | string \| null | Optional, max 255 |
| `sort_order` | integer | `>= 0`, defaults `0` |

| Method | Path | Success | Errors |
|---|---|---|---|
| `GET` | `/api/v1/plants/{plant_id}/images` | `200` list | `401`, `404` |
| `POST` | `/api/v1/plants/{plant_id}/images` | `201` | `401`, `404`, `422` |
| `PATCH` | `/api/v1/plants/{plant_id}/images/{image_id}` | `200` | `401`, `404`, `422` |
| `DELETE` | `/api/v1/plants/{plant_id}/images/{image_id}` | `204` no body | `401`, `404` |

An image must belong to `{plant_id}`; otherwise the request returns `404`. Deleting removes only the image row — the plant is untouched.

```bash
curl -b cookies.txt -X POST http://localhost:8000/api/v1/plants/3fa85f64-5717-4562-b3fc-2c963f66afa6/images \
  -H "Content-Type: application/json" \
  -d '{"url":"https://cdn.example.com/monstera.jpg","type":"image","alt_text":"Monstera Deliciosa","sort_order":0}'
```

---

## Pot sizes API

Base path: `/api/v1/plants/{plant_id}/pot-sizes`

Ordered by `sort_order`, then `name`.

### PlantPotSizeResponse

```json
{
  "id": "7b1c2d3e-4f5a-6b7c-8d9e-0f1a2b3c4d5e",
  "plant_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "name": "Large",
  "price_adjustment": "5.00",
  "price_adjustment_vi": "100000.00",
  "sort_order": 1,
  "is_active": true,
  "created_at": "2026-09-16T09:00:00Z",
  "updated_at": "2026-09-16T09:00:00Z"
}
```

| Field | Type | Rules |
|---|---|---|
| `name` | string | Required, trimmed, max 100 |
| `price_adjustment` | Decimal | `>= 0`, `NUMERIC(12,2)` — enforced by DB check `ck_plant_pot_sizes_price_adjustment_non_negative` |
| `price_adjustment_vi` | Decimal \| null | Optional, `>= 0`, `NUMERIC(12,2)` — enforced by DB check `ck_plant_pot_sizes_price_adjustment_vi_non_negative` |
| `sort_order` | integer | `>= 0`, defaults `0` |
| `is_active` | boolean | Defaults `true` |

Each locale keeps its own adjustment, applied on top of the matching plant price. A plant at `price` 25 AUD / `price_vi` 650,000 VND with the pot size above sells for 30 AUD and 750,000 VND respectively. `PATCH` with `"price_adjustment_vi": null` clears the Vietnamese adjustment and leaves `price_adjustment` untouched.

| Method | Path | Success | Errors |
|---|---|---|---|
| `GET` | `/api/v1/plants/{plant_id}/pot-sizes` | `200` list | `401`, `404` |
| `POST` | `/api/v1/plants/{plant_id}/pot-sizes` | `201` | `401`, `404`, `422` |
| `PATCH` | `/api/v1/plants/{plant_id}/pot-sizes/{size_id}` | `200` | `401`, `404`, `422` |
| `DELETE` | `/api/v1/plants/{plant_id}/pot-sizes/{size_id}` | `204` no body | `401`, `404` |

A pot size must belong to `{plant_id}`; otherwise the request returns `404`.

```bash
curl -b cookies.txt -X POST http://localhost:8000/api/v1/plants/3fa85f64-5717-4562-b3fc-2c963f66afa6/pot-sizes \
  -H "Content-Type: application/json" \
  -d '{"name":"Large","price_adjustment":5,"price_adjustment_vi":100000,"sort_order":1,"is_active":true}'
```

---

## Customers management API

Base path: `/api/v1/customers`

All customer endpoints require an authenticated **active** admin (access cookie). Customers are **guests**: they have no password, no login and no endpoints of their own — the phone number is their identity.

There is **no** `DELETE /api/v1/customers/{id}`. Retire a customer with `PATCH /api/v1/customers/{id}/status`, which keeps the customer row and their whole order history intact.

### CustomerResponse

```json
{
  "id": "b7f4c1d2-9e3a-4b58-8c17-5d2e6f7a8b90",
  "phone": "0901234567",
  "name": "Nguyen Van A",
  "email": "customer@example.com",
  "is_active": true,
  "created_at": "2026-09-16T09:00:00Z",
  "updated_at": "2026-09-16T09:00:00Z"
}
```

### Field rules

| Field | Type | Rules |
|---|---|---|
| `phone` | string | Required, unique, max 32 chars. Spaces are stripped (`090 123 4567` → `0901234567`), so the same number cannot be stored twice. Must be at least 6 digits and may only contain digits with an optional leading `+` and `()`, `-`, `.` separators |
| `name` | string | Required, trimmed, max 255 |
| `email` | email \| null | Optional, validated and normalized (trimmed + lowercase) |
| `is_active` | boolean | Defaults `true`; inactive customers cannot place new orders |

---

### `GET /api/v1/customers`

Paginated admin listing, ordered by `created_at` descending. Includes inactive customers.

**Auth:** required

**Query params**

| Param | Type | Default | Notes |
|---|---|---|---|
| `page` | integer | `1` | `>= 1` |
| `page_size` | integer | `20` | `1..100` |
| `search` | string | — | Matches `phone`, `name` or `email` (case-insensitive) |
| `is_active` | boolean | — | Omit to return both active and inactive |

**Response `200`**

```json
{
  "items": [
    {
      "id": "b7f4c1d2-9e3a-4b58-8c17-5d2e6f7a8b90",
      "phone": "0901234567",
      "name": "Nguyen Van A",
      "email": "customer@example.com",
      "is_active": true,
      "created_at": "2026-09-16T09:00:00Z",
      "updated_at": "2026-09-16T09:00:00Z"
    }
  ],
  "page": 1,
  "page_size": 20,
  "total": 1
}
```

**Errors:** `401`, `422`

```bash
curl -b cookies.txt "http://localhost:8000/api/v1/customers?page=1&page_size=20&search=0901&is_active=true"
```

---

### `GET /api/v1/customers/{customer_id}`

**Auth:** required

**Response `200`** — `CustomerResponse` (active or inactive)

**Errors:** `401`, `404`, `422`

---

### `POST /api/v1/customers`

**Auth:** required

**Request body**

```json
{
  "phone": "0901234567",
  "name": "Nguyen Van A",
  "email": "customer@example.com"
}
```

Only `phone` and `name` are required. `is_active` is always `true` on creation.

**Response `201`** — `CustomerResponse`

**Errors**

| Status | When |
|---|---|
| `401` | Not authenticated |
| `409` | Phone already used by another customer |
| `422` | Missing/empty/unusable phone, empty name, invalid email |

```bash
curl -b cookies.txt -X POST http://localhost:8000/api/v1/customers \
  -H "Content-Type: application/json" \
  -d '{"phone":"0901234567","name":"Nguyen Van A","email":"customer@example.com"}'
```

---

### `PATCH /api/v1/customers/{customer_id}`

Partial update of `phone`, `name` and `email`. Changing the phone re-checks uniqueness. Sending `"email": null` clears the email; omitted fields keep their stored values.

`id`, `created_at`, `updated_at` and order history are never writable — unknown fields in the body are ignored.

**Auth:** required

**Request body**

```json
{
  "name": "Nguyen Van B",
  "email": "new@example.com"
}
```

**Response `200`** — `CustomerResponse`

**Errors:** `401`, `404`, `409` (phone), `422`

---

### `PATCH /api/v1/customers/{customer_id}/status`

**Auth:** required

**Request body**

```json
{
  "is_active": false
}
```

Soft deactivation only: no data is deleted, historical orders stay exactly as they were, and the customer keeps their phone number. An inactive customer cannot be used for a **new** order (`400`).

**Response `200`** — `CustomerResponse`

**Errors:** `401`, `404`, `422`

```bash
curl -b cookies.txt -X PATCH http://localhost:8000/api/v1/customers/b7f4c1d2-9e3a-4b58-8c17-5d2e6f7a8b90/status \
  -H "Content-Type: application/json" \
  -d '{"is_active":false}'
```

---

## Orders management API

Base path: `/api/v1/orders`

All order endpoints require an authenticated **active** admin (access cookie).

Orders are historical business records, so there is **no** `DELETE /api/v1/orders/{id}` and no way to edit an order's contents — only its `status` moves. Order items are **snapshots**: `plant_name` and `unit_price` are copied when the order is created and never recalculated from the plant afterwards.

There is no payment API or payment table: money handling stops at `total_amount`.

### OrderResponse

List rows and the detail response share the same shape.

```json
{
  "id": "1c9d2e3f-4a5b-6c7d-8e9f-0a1b2c3d4e5f",
  "order_number": "GG-20260916-0001",
  "status": "pending",
  "total_amount": "800000.00",
  "shipping_address": "123 Nguyen Trai, District 1, HCMC",
  "note": "Please call before delivery",
  "customer": {
    "id": "b7f4c1d2-9e3a-4b58-8c17-5d2e6f7a8b90",
    "name": "Nguyen Van A",
    "phone": "0901234567",
    "email": "customer@example.com"
  },
  "items": [
    {
      "id": "5f4e3d2c-1b0a-9f8e-7d6c-5b4a39281706",
      "plant_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
      "plant_name": "Monstera Deliciosa",
      "quantity": 2,
      "unit_price": "400000.00",
      "pot_size": "Large"
    }
  ],
  "created_at": "2026-09-16T09:00:00Z",
  "updated_at": "2026-09-16T09:00:00Z"
}
```

| Field | Type | Notes |
|---|---|---|
| `order_number` | string | Generated as `GG-YYYYMMDD-NNNN` (UTC date + daily sequence), unique |
| `status` | enum | `pending` \| `confirmed` \| `processing` \| `shipping` \| `completed` \| `cancelled` |
| `total_amount` | Decimal (string in JSON) | Always calculated by the backend, `NUMERIC(12,2)` |
| `shipping_address` | string | Snapshot text on the order — there is no address table |
| `customer` | object | `id`, `name`, `phone`, `email` — eager-loaded, no N+1 |
| `items[].unit_price` | Decimal (string in JSON) | Plant price **plus** the selected pot size adjustment at purchase time |
| `items[].pot_size` | string \| null | Snapshot of the chosen pot size name |

---

### `GET /api/v1/orders`

Paginated admin listing, ordered by `created_at` descending. Customer and items are eager-loaded in fixed query counts.

**Auth:** required

**Query params**

| Param | Type | Default | Notes |
|---|---|---|---|
| `page` | integer | `1` | `>= 1` |
| `page_size` | integer | `20` | `1..100` |
| `search` | string | — | Matches `order_number`, customer `phone` or customer `name` (case-insensitive) |
| `status` | enum | — | One of the six order statuses |
| `customer_id` | UUID | — | Orders of one customer |
| `date_from` | date | — | `created_at` on or after this UTC date (`YYYY-MM-DD`) |
| `date_to` | date | — | `created_at` on or before this UTC date (inclusive) |

**Response `200`**

```json
{
  "items": [],
  "page": 1,
  "page_size": 20,
  "total": 0
}
```

**Errors:** `401`, `422` (unknown status, bad date, bad page size)

```bash
curl -b cookies.txt "http://localhost:8000/api/v1/orders?page=1&page_size=20&search=0901234567&status=pending&date_from=2026-09-01&date_to=2026-09-16"
```

---

### `GET /api/v1/orders/{order_id}`

Full detail: order fields, customer, item snapshots, total, shipping address, note and timestamps.

**Auth:** required

**Response `200`** — `OrderResponse`

**Errors:** `401`, `404`, `422`

```bash
curl -b cookies.txt http://localhost:8000/api/v1/orders/1c9d2e3f-4a5b-6c7d-8e9f-0a1b2c3d4e5f
```

---

### `POST /api/v1/orders`

**Auth:** required

**Request body**

```json
{
  "customer": {
    "phone": "0901234567",
    "name": "Nguyen Van A",
    "email": "customer@example.com"
  },
  "shipping_address": "123 Nguyen Trai, District 1, HCMC",
  "note": "Please call before delivery",
  "items": [
    {
      "plant_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
      "quantity": 2,
      "pot_size": "Large"
    }
  ]
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `customer.phone` | string | yes | Same rules as `POST /api/v1/customers` |
| `customer.name` | string | yes | Used only when a new customer is created |
| `customer.email` | email \| null | no | Stored only when the existing customer has no email yet |
| `shipping_address` | string | yes | Non-empty after trim |
| `note` | string \| null | no | |
| `items` | array | yes | At least one line |
| `items[].plant_id` | UUID | yes | Must exist and be active |
| `items[].quantity` | integer | yes | `>= 1` |
| `items[].pot_size` | string \| null | no | Active pot size **name** of that plant, matched case-insensitively |

**Customer resolution.** The phone number decides everything: an existing phone reuses that customer (their stored `name` is kept, and `email` is only filled in when it was empty), an unknown phone creates a new customer. Duplicate customers can never be created for one phone.

**Pricing.** The client never sets money — `unit_price`, `total_amount` or any other price in the request body is ignored. For every line the backend loads the plant, checks it is active, verifies stock, then calculates:

```
unit_price   = plant.price + pot_size.price_adjustment
line_total   = unit_price × quantity
total_amount = sum(line_total)
```

All arithmetic uses `Decimal` / `NUMERIC(12,2)`. Prices come from the default-locale `price` / `price_adjustment` columns.

**Stock and transaction.** Stock is verified and deducted inside the same transaction as the customer upsert, the order and the item snapshots, with the plant rows locked (`SELECT ... FOR UPDATE`) so concurrent checkouts cannot oversell. If any line fails, nothing is written at all: no order, no customer, no stock movement. Stock never goes negative, and quantities are summed per plant when the same plant appears on several lines.

New orders always start as `pending`.

**Response `201`** — `OrderResponse`

**Errors**

| Status | When |
|---|---|
| `400` | Insufficient stock, inactive plant, unknown/inactive pot size, inactive customer |
| `401` | Not authenticated |
| `404` | `plant_id` does not exist |
| `422` | Invalid body (no items, `quantity < 1`, empty shipping address, unusable phone) |

```bash
curl -b cookies.txt -X POST http://localhost:8000/api/v1/orders \
  -H "Content-Type: application/json" \
  -d '{"customer":{"phone":"0901234567","name":"Nguyen Van A"},"shipping_address":"123 Nguyen Trai, District 1, HCMC","items":[{"plant_id":"3fa85f64-5717-4562-b3fc-2c963f66afa6","quantity":2,"pot_size":"Large"}]}'
```

---

### `PATCH /api/v1/orders/{order_id}/status`

**Auth:** required

**Request body**

```json
{
  "status": "confirmed"
}
```

Only the six known statuses are accepted; anything else is `422`. Nothing but `status` changes — items, totals, address and customer are untouched.

**Allowed transitions**

| From | To |
|---|---|
| `pending` | `confirmed`, `processing`, `shipping`, `completed`, `cancelled` |
| `confirmed` | `processing`, `shipping`, `completed`, `cancelled` |
| `processing` | `shipping`, `completed`, `cancelled` |
| `shipping` | `completed`, `cancelled` |
| `completed` | — (final) |
| `cancelled` | — (final) |

The pipeline only moves forward; going back (for example `shipping` → `confirmed`) is `400`. Re-sending the current status is a no-op that returns the unchanged order.

**Cancellation and stock.** Cancelling restores the ordered quantities to the plants in one transaction with the status change. Because stock is deducted exactly once at creation and `cancelled` is final, stock can never be restored twice — repeating `{"status":"cancelled"}` changes nothing.

**Response `200`** — `OrderResponse`

**Errors**

| Status | When |
|---|---|
| `400` | Backwards transition, or the order is already `completed` / `cancelled` |
| `401` | Not authenticated |
| `404` | Order does not exist |
| `422` | Unknown status value |

```bash
curl -b cookies.txt -X PATCH http://localhost:8000/api/v1/orders/1c9d2e3f-4a5b-6c7d-8e9f-0a1b2c3d4e5f/status \
  -H "Content-Type: application/json" \
  -d '{"status":"confirmed"}'
```

---

## Dashboard overview API

Base path: `/api/v1/overview`

One authenticated request returns every statistic the admin dashboard shows. It is **read-only**: nothing is written, nothing is cached, and there is no analytics, statistics or daily-revenue table behind it — every number is aggregated in PostgreSQL from the eight existing tables (`categories`, `plants`, `customers`, `orders`, `order_items`) at request time.

Two definitions decide what the numbers mean:

- **Revenue = `completed` orders only.** `pending`, `confirmed`, `processing`, `shipping` and `cancelled` orders are counted in `summary.total_orders` and `orders_by_status`, but never earn money. Revenue is always `SUM(orders.total_amount)`, never recalculated from the items, and reads `"0.00"` instead of `null` when nothing has been completed.
- **Days and months are cut in UTC**, the timezone the API stores and filters every timestamp in, so the dashboard does not drift with the server's local clock.

### `GET /api/v1/overview`

**Auth:** required (active admin, access cookie). Inactive admins cannot log in, and an admin deactivated after logging in is rejected on the next request.

**Response `200`**

```json
{
  "summary": {
    "total_plants": 120,
    "active_plants": 110,
    "total_categories": 10,
    "active_categories": 9,
    "total_customers": 350,
    "active_customers": 340,
    "total_orders": 520,
    "pending_orders": 12,
    "total_revenue": "125000000.00"
  },
  "sales": {
    "today": { "orders": 8, "revenue": "2400000.00" },
    "this_month": { "orders": 120, "revenue": "32000000.00" }
  },
  "orders_by_status": {
    "pending": 12,
    "confirmed": 20,
    "processing": 15,
    "shipping": 18,
    "completed": 440,
    "cancelled": 15
  },
  "revenue_by_day": [
    { "date": "2026-09-01", "orders": 5, "revenue": "1200000.00" },
    { "date": "2026-09-02", "orders": 0, "revenue": "0.00" }
  ],
  "top_plants": [
    {
      "plant_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
      "plant_name": "Monstera Deliciosa",
      "quantity_sold": 42,
      "revenue": "12600000.00"
    }
  ],
  "low_stock": [
    {
      "plant_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
      "plant_name": "Monstera Deliciosa",
      "stock": 3
    }
  ],
  "recent_orders": [
    {
      "id": "1c9d2e3f-4a5b-6c7d-8e9f-0a1b2c3d4e5f",
      "order_number": "GG-20260916-0001",
      "customer_name": "Nguyen Van A",
      "customer_phone": "0901234567",
      "status": "pending",
      "total_amount": "850000.00",
      "created_at": "2026-09-16T09:00:00Z"
    }
  ]
}
```

| Section | Notes |
|---|---|
| `summary` | Counts **all** rows; the `active_*` counters additionally require `is_active = true`. `total_revenue` is lifetime completed revenue |
| `sales.today` | Orders created today (UTC) and the revenue of the completed ones |
| `sales.this_month` | Same for the current calendar month |
| `orders_by_status` | All six statuses (`pending`, `confirmed`, `processing`, `shipping`, `completed`, `cancelled`); unused statuses report `0` and are never omitted |
| `revenue_by_day` | One entry per day from the 1st of the current month up to today, chronological, days without sales included. `orders` counts every order created that day, `revenue` only the completed ones |
| `top_plants` | Top 5 plants by `quantity_sold` (ties broken by revenue), from **completed** orders only. `plant_name` is the `order_items` snapshot from the most recent sale, and revenue is `SUM(quantity × unit_price)` |
| `low_stock` | Up to 5 **active** plants with `stock <= 5`, scarcest first. Inactive plants are never listed |
| `recent_orders` | The 5 newest orders by `created_at`, customer joined in the same query. `customer_name` / `customer_phone` are `null` only if the customer row is unexpectedly missing, which never fails the response |

Money fields are `NUMERIC(12,2)` and serialize as JSON strings, exactly like `OrderResponse.total_amount`.

**Errors**

| Status | When |
|---|---|
| `401` | Not authenticated, or the admin is inactive |
| `500` | Statistics could not be calculated (database details are never exposed) |

```bash
curl -b cookies.txt http://localhost:8000/api/v1/overview
```

---

## Public storefront API

Base path: `/api/v1/storefront`

**No authentication.** Only `is_active = true` plants are returned, and admin-only fields (`sku`, `stock`, `is_active`, audit timestamps) are never exposed.

Plant detail is addressed by **slug** here, while the admin API uses **UUID** under `/api/v1/plants/{plant_id}` — so UUIDs and slugs can never collide on the same route.

### `GET /api/v1/storefront/categories`

Active category navigation, ordered by `sort_order ASC` then `created_at ASC`.

**Query params:** `page`, `page_size`, `search`

**Response `200`**

```json
{
  "items": [
    {
      "id": "8c1f1a2e-2b44-4f8e-9a47-4a1d2f2b7f10",
      "name": "Fruit Trees",
      "name_vi": "Cây ăn quả",
      "slug": "fruit-trees",
      "description": "Fruit trees for your garden.",
      "description_vi": "Các loại cây ăn quả phù hợp cho khu vườn.",
      "image_url": "https://example.com/fruit-trees.jpg",
      "sort_order": 1
    }
  ],
  "page": 1,
  "page_size": 20,
  "total": 1
}
```

`is_active` and the audit timestamps are omitted, and inactive categories are never returned.

**Errors:** `422`

```bash
curl http://localhost:8000/api/v1/storefront/categories
```

### `GET /api/v1/storefront/plants`

Same pagination, search, sorting and price filters as the admin list, minus `is_active` (always `true`).

**Query params:** `page`, `page_size`, `search`, `category_id`, `is_featured`, `min_price`, `max_price`, `sort`, `order`

**Response `200`**

```json
{
  "items": [
    {
      "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
      "name": "Monstera Deliciosa",
      "name_vi": "Cây Trầu Bà Nam Mỹ",
      "slug": "monstera-deliciosa",
      "price": "25.00",
      "price_vi": "650000.00",
      "is_featured": true,
      "category": {
        "id": "8c1f1a2e-2b44-4f8e-9a47-4a1d2f2b7f10",
        "name": "Fruit Trees",
        "name_vi": "Cây ăn quả",
        "slug": "fruit-trees"
      }
    }
  ],
  "page": 1,
  "page_size": 20,
  "total": 1
}
```

**Errors:** `422`

### `GET /api/v1/storefront/plants/{slug}`

**Response `200`**

```json
{
  "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "name": "Monstera Deliciosa",
  "name_vi": "Cây Trầu Bà Nam Mỹ",
  "slug": "monstera-deliciosa",
  "description": "A beautiful tropical indoor plant.",
  "description_vi": "Một loại cây nhiệt đới đẹp, phù hợp trồng trong nhà.",
  "price": "25.00",
  "price_vi": "650000.00",
  "is_featured": true,
  "in_stock": true,
  "category": {
    "id": "8c1f1a2e-2b44-4f8e-9a47-4a1d2f2b7f10",
    "name": "Fruit Trees",
    "name_vi": "Cây ăn quả",
    "slug": "fruit-trees"
  },
  "images": [],
  "pot_sizes": []
}
```

Exact stock counts are hidden — the storefront only sees `in_stock`. Only **active** pot sizes are included.

**Errors**

| Status | When |
|---|---|
| `404` | Slug unknown **or** plant is inactive |

```bash
curl http://localhost:8000/api/v1/storefront/plants/monstera-deliciosa
```

---

## Endpoint summary

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/health` | No | Health check |
| `POST` | `/api/v1/auth/login` | No | Login; sets cookies |
| `POST` | `/api/v1/auth/logout` | No | Clear cookies |
| `GET` | `/api/v1/auth/me` | Access cookie | Current admin |
| `POST` | `/api/v1/auth/refresh` | Refresh cookie | Renew access cookie |
| `GET` | `/api/v1/admins` | Access cookie | List admins |
| `GET` | `/api/v1/admins/{id}` | Access cookie | Get admin |
| `POST` | `/api/v1/admins` | Access cookie | Create admin |
| `PATCH` | `/api/v1/admins/{id}` | Access cookie | Update admin |
| `PATCH` | `/api/v1/admins/{id}/status` | Access cookie | Activate/deactivate |
| `PATCH` | `/api/v1/admins/{id}/password` | Access cookie | Change password |
| `GET` | `/api/v1/categories` | Access cookie | List categories (search, status filter) |
| `GET` | `/api/v1/categories/{category_id}` | Access cookie | Category detail |
| `POST` | `/api/v1/categories` | Access cookie | Create category |
| `PATCH` | `/api/v1/categories/{category_id}` | Access cookie | Update category |
| `PATCH` | `/api/v1/categories/{category_id}/status` | Access cookie | Activate/deactivate category |
| `GET` | `/api/v1/plants` | Access cookie | List plants (filters, sorting) |
| `GET` | `/api/v1/plants/{plant_id}` | Access cookie | Plant detail |
| `POST` | `/api/v1/plants` | Access cookie | Create plant |
| `PATCH` | `/api/v1/plants/{plant_id}` | Access cookie | Update plant |
| `PATCH` | `/api/v1/plants/{plant_id}/status` | Access cookie | Activate/deactivate plant |
| `GET` | `/api/v1/plants/{plant_id}/images` | Access cookie | List images |
| `POST` | `/api/v1/plants/{plant_id}/images` | Access cookie | Add image URL |
| `PATCH` | `/api/v1/plants/{plant_id}/images/{image_id}` | Access cookie | Update image |
| `DELETE` | `/api/v1/plants/{plant_id}/images/{image_id}` | Access cookie | Delete image |
| `GET` | `/api/v1/plants/{plant_id}/pot-sizes` | Access cookie | List pot sizes |
| `POST` | `/api/v1/plants/{plant_id}/pot-sizes` | Access cookie | Add pot size |
| `PATCH` | `/api/v1/plants/{plant_id}/pot-sizes/{size_id}` | Access cookie | Update pot size |
| `DELETE` | `/api/v1/plants/{plant_id}/pot-sizes/{size_id}` | Access cookie | Delete pot size |
| `GET` | `/api/v1/customers` | Access cookie | List customers (search, status filter) |
| `GET` | `/api/v1/customers/{customer_id}` | Access cookie | Customer detail |
| `POST` | `/api/v1/customers` | Access cookie | Create customer |
| `PATCH` | `/api/v1/customers/{customer_id}` | Access cookie | Update phone / name / email |
| `PATCH` | `/api/v1/customers/{customer_id}/status` | Access cookie | Activate / deactivate customer |
| `GET` | `/api/v1/orders` | Access cookie | List orders (search, status, customer, date range) |
| `GET` | `/api/v1/orders/{order_id}` | Access cookie | Order detail with customer and items |
| `POST` | `/api/v1/orders` | Access cookie | Create order (backend pricing + stock deduction) |
| `PATCH` | `/api/v1/orders/{order_id}/status` | Access cookie | Advance or cancel an order |
| `GET` | `/api/v1/overview` | Access cookie | Dashboard statistics (summary, sales, statuses, daily revenue, top plants, low stock, recent orders) |
| `GET` | `/api/v1/storefront/categories` | No | Public active categories |
| `GET` | `/api/v1/storefront/plants` | No | Public active catalogue |
| `GET` | `/api/v1/storefront/plants/{slug}` | No | Public plant detail by slug |

---

## Security notes

- No plaintext passwords stored or returned
- No `password_hash` in API responses
- No JWT tokens in API response bodies
- Inactive admins cannot log in or use protected endpoints
- Duplicate emails return `409 Conflict`
- No RBAC — all active admins share the same permissions
- No public admin registration endpoint
- Plants and categories are never hard-deleted; use the `/status` endpoints
- Deactivating a category never deletes or cascades to its plants
- Inactive plants and categories are excluded from every `/api/v1/storefront` response
- Storefront responses omit `sku`, exact `stock`, `is_active` and audit timestamps
- Customers have no password, no login and no self-service endpoints; admin auth guards every customer and order route
- Customers and orders are never hard-deleted; customers are retired with `/status` and orders only change `status`
- Order totals and unit prices are always calculated server-side; money in the request body is ignored
- Stock deduction and order creation share one transaction, and cancellation restores stock exactly once
- No payment table and no payment endpoints exist
- `/api/v1/overview` is admin-only and read-only: it never writes, and it only ever reports revenue for `completed` orders

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
  "name": "Indoor Plants",
  "slug": "indoor-plants",
  "description": "Plants suitable for indoor spaces.",
  "image_url": "https://example.com/indoor-plants.jpg",
  "sort_order": 1,
  "is_active": true,
  "created_at": "2026-09-16T09:00:00Z",
  "updated_at": "2026-09-16T09:00:00Z"
}
```

### Field rules

| Field | Type | Rules |
|---|---|---|
| `name` | string | Required, trimmed, max 255 |
| `slug` | string | Required, normalized to `a-z0-9-`, unique |
| `description` | string \| null | Optional, trimmed |
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
      "name": "Indoor Plants",
      "slug": "indoor-plants",
      "description": "Plants suitable for indoor spaces.",
      "image_url": "https://example.com/indoor-plants.jpg",
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
  "name": "Indoor Plants",
  "slug": "indoor-plants",
  "description": "Plants suitable for indoor spaces.",
  "image_url": "https://example.com/indoor-plants.jpg",
  "sort_order": 1,
  "is_active": true
}
```

Only `name` and `slug` are required.

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
  -d '{"name":"Indoor Plants","slug":"indoor-plants","sort_order":1}'
```

---

### `PATCH /api/v1/categories/{category_id}`

Partial update; all fields optional. Changing the slug re-checks uniqueness. Sending `"description": null` or `"image_url": null` clears the field.

**Auth:** required

**Request body**

```json
{
  "name": "Indoor Plants & Ferns",
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
    "name": "Indoor Plants",
    "slug": "indoor-plants"
  },
  "name": "Monstera Deliciosa",
  "slug": "monstera-deliciosa",
  "description": "Beautiful tropical plant.",
  "price": "250000.00",
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

`PlantListItem` is the lightweight listing row: same fields **without** `description`, `images` and `pot_sizes`.

#### Field rules

| Field | Type | Rules |
|---|---|---|
| `category_id` | UUID | Must reference an existing category |
| `name` | string | Required, trimmed, max 255 |
| `slug` | string | Required, normalized to `a-z0-9-`, unique |
| `description` | string \| null | Optional, trimmed |
| `price` | Decimal (string in JSON) | `>= 0`, `NUMERIC(12,2)` |
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
  "slug": "monstera-deliciosa",
  "description": "Beautiful tropical plant.",
  "price": 250000,
  "stock": 20,
  "sku": "MON-001",
  "is_featured": true,
  "is_active": true
}
```

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
  "price": 320000,
  "category_id": "8c1f1a2e-2b44-4f8e-9a47-4a1d2f2b7f10"
}
```

Changing `category_id` re-validates the category, and changing `slug` / `sku` re-checks uniqueness.

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
  "name": "Size M",
  "price_adjustment": "50000.00",
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
| `sort_order` | integer | `>= 0`, defaults `0` |
| `is_active` | boolean | Defaults `true` |

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
  -d '{"name":"Size M","price_adjustment":50000,"sort_order":1,"is_active":true}'
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
      "name": "Indoor Plants",
      "slug": "indoor-plants",
      "description": "Plants suitable for indoor spaces.",
      "image_url": "https://example.com/indoor-plants.jpg",
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
      "slug": "monstera-deliciosa",
      "price": "250000.00",
      "is_featured": true,
      "category": {
        "id": "8c1f1a2e-2b44-4f8e-9a47-4a1d2f2b7f10",
        "name": "Indoor Plants",
        "slug": "indoor-plants"
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
  "slug": "monstera-deliciosa",
  "description": "Beautiful tropical plant.",
  "price": "250000.00",
  "is_featured": true,
  "in_stock": true,
  "category": {
    "id": "8c1f1a2e-2b44-4f8e-9a47-4a1d2f2b7f10",
    "name": "Indoor Plants",
    "slug": "indoor-plants"
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

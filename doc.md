# Green Garden API Documentation

Base URL (local): `http://localhost:8000`

Interactive OpenAPI UI: [http://localhost:8000/docs](http://localhost:8000/docs)

API prefix for versioned routes: `/api/v1`

---

## Overview

| Area | Endpoints |
|---|---|
| Health | `GET /health` |
| Auth | `/api/v1/auth/*` |
| Admin management | `/api/v1/admins/*` |

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

---

## Security notes

- No plaintext passwords stored or returned
- No `password_hash` in API responses
- No JWT tokens in API response bodies
- Inactive admins cannot log in or use protected endpoints
- Duplicate emails return `409 Conflict`
- No RBAC — all active admins share the same permissions
- No public admin registration endpoint

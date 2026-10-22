# CareerLine API: how to use it

For the frontend (Andrew) and anyone calling the API. The contract is `openapi.json` at the repo root; this page explains how to use it and how changes are announced.

## Base URLs

| Where | API base | Interactive docs |
| --- | --- | --- |
| Local | `http://localhost:8000/api/v1` | `http://localhost:8000/docs` |
| Test server (Render) | `https://<careerline-api service URL>/api/v1` (shown at the top of the service in Render, e.g. `https://careerline-api.onrender.com`) | `https://<service URL>/docs` |

Outside the `/api/v1` prefix: `GET /healthz` (the app is up), `GET /readyz` (the database is reachable and migrated), `/docs` (Swagger) and `/openapi.json` (the live contract).

## Log in

1. `POST /api/v1/auth/register` with JSON `{ "full_name", "email", "phone", "password" }` (password at least 8 characters). The answer already holds a token.
2. `POST /api/v1/auth/login` as a **form** (`application/x-www-form-urlencoded`), not JSON: `username=<email>&password=<password>`. The answer is the standard OAuth2 body `{ "access_token", "token_type": "bearer", "learner_id", "full_name" }` (no envelope).
3. Send `Authorization: Bearer <access_token>` on every protected call. A token lasts 24 hours; a 401 means log in again.

```ts
const form = new URLSearchParams({ username: email, password });
const res = await fetch(`${API}/auth/login`, { method: "POST", body: form });
const { access_token } = await res.json();
```

## Answers and errors

Every answer except login is an envelope:

```json
{ "success": true, "message": null, "data": { "...": "..." } }
```

```json
{ "success": false, "error": { "code": "not_found", "message": "Attempt 9 not found", "request_id": "3f2a…" } }
```

- Read `data` on success. On error, branch on `error.code` (stable) and show `error.message` (human text, may change). Validation errors (`422`) also have `error.details`: a list of `{ loc, msg, type }`, e.g. `loc: ["body", "email"]`.
- Every response has an `X-Request-ID` header, the same as `error.request_id`. Put it in bug reports: it finds the request in the server logs.
- Lists are pages: `data = { items, total, limit, offset }`; send `?limit=&offset=`.
- Money is in the smallest unit: `{ "amount": 500000, "currency": "NGN" }` is NGN 5,000.00 (Paystack's kobo).
- Times are ISO 8601 in UTC (`2026-10-22T09:00:00Z`); dates are `YYYY-MM-DD`. Ids are integers, except payment references and invitation tokens (strings).
- Levels are `BEGINNER`, `JUNIOR`, `MID`, `ADVANCED`.

| Status | `error.code` | Meaning | What the app should do |
| --- | --- | --- | --- |
| 400 | `bad_request` | Invalid input (message says what) | Show the message |
| 401 | `unauthenticated` | No token, bad token or expired | Send to login |
| 402 | `payment_required` | Not enough credits / no subscription | Send to buy credits or plans |
| 403 | `forbidden` | Logged in, but not allowed (someone else's data, wrong account type) | Show "not allowed" |
| 404 | `not_found` | Doesn't exist (or isn't yours) | Show "not found" |
| 405 | `method_not_allowed` | Wrong HTTP method | Bug in the call |
| 409 | `conflict` | Already done (e.g. submitted twice, invitation already used) | Refresh the item |
| 410 | `expired` / `gone` | Link, token or offer expired / old route retired | Ask for a new link |
| 422 | `validation_error` | Body or parameters invalid (`details` lists the fields) | Show the field errors |
| 429 | `rate_limited` | Too many requests (`Retry-After` header, seconds) | Wait and retry |
| 500 | `internal_error` | Our bug | Generic error + request id |
| 503 | `service_unavailable` | Down or database migrating | Retry shortly |

## Sample data

Endpoints that are not built yet answer with **realistic, typed sample data**, on their real path, in the real envelope, with the real response model. Build the screens against them now: when the real feature lands (Days 6–27) the path and the shape stay the same, only the data becomes real.

How to tell:

- Response header `X-Sample-Data: true` (the browser can read it: it is in `Access-Control-Expose-Headers`), and `"message": "Sample data"` on success.
- In `/docs` and `openapi.json` they are tagged `Sample: …` and carry `"x-sample": true`. When an endpoint becomes real, its `Sample:` tag and `x-sample` go away (see Changes below).
- Protected sample endpoints need a real token from `/auth/login`. Recruiter and organisation accounts don't exist yet, so any learner token works on their endpoints for now.

What is real today: `/auth/register`, `/auth/login`, `/learners/*`, `/skills/*`, `/attempts/*` and `/recommendations/*` (they use the database). Everything tagged `Sample:` is sample.

### Force an edge case: `X-Mock-Scenario`

Send the header `X-Mock-Scenario: <name>` on any sample call to get that case, with the real status code and error envelope:

| Scenario | Answer |
| --- | --- |
| `unauthenticated` | 401 `unauthenticated` |
| `payment_required` | 402 `payment_required` |
| `forbidden` | 403 `forbidden` |
| `not_found` | 404 `not_found` |
| `conflict` | 409 `conflict` |
| `expired` | 410 `expired` |
| `validation_error` | 422 `validation_error` with `details` |
| `rate_limited` | 429 `rate_limited` with `Retry-After: 30` |
| `server_error` | 500 `internal_error` |
| `unavailable` | 503 `service_unavailable` |
| `slow` | the normal answer after 2 seconds (loading states) |

Some endpoints offer more (listed in their description in `/docs` and in `x-sample-scenarios`): `empty` (lists come back empty: empty states), `pending` / `paid` / `failed` (payment status), `generating` / `failed` (PDF report), `past_due` / `cancelled` / `no_subscription` (subscription). A name the endpoint doesn't offer is a 400 that lists the ones it does, so a typo never looks like a normal answer. Names ignore case.

```bash
curl -H "Authorization: Bearer $TOKEN" -H "X-Mock-Scenario: empty" "$API/results"
curl -H "Authorization: Bearer $TOKEN" -H "X-Mock-Scenario: payment_required" "$API/tests/202/access"
```

```ts
// e.g. a dev-only switch in the app that adds the header to every call
fetch(`${API}/results`, { headers: { Authorization: `Bearer ${token}`, "X-Mock-Scenario": "empty" } });
```

Real endpoints ignore the header.

### Flows that work end to end on sample data

The sample server keeps a little state (on the server, gone after a restart or `POST /api/v1/sample/reset`), so these flows can be clicked through:

**Buying credits or a plan (Paystack):**

1. `POST /payments/checkout` `{ "item_type": "credit_pack", "item_id": 1, "callback_url": "https://<website>/payment/done" }` (or `POST /subscriptions` `{ "plan_id": 11, "callback_url": … }`) → 201, `status: "pending"`, `authorization_url`, `reference`.
2. Send the browser to `authorization_url`. On the test server it is a sample Paystack page that pays at once and redirects to `callback_url?reference=…&trxref=…`, like Paystack does. Add `?outcome=failed` or `?outcome=abandoned` to the URL to try those.
3. On the callback page, `GET /payments/{reference}` → `status: "paid"`, `credits_added`. `GET /credits` shows the new balance; `GET /subscriptions/me` shows the active plan.

Paystack's webhook (`POST /payments/webhooks/paystack`, `charge.success`) does the same as step 2; it is the server's business, the app never calls it.

**Inviting someone to a test:**

1. Recruiter (or organisation): `POST /invitations` `{ "email", "full_name", "test_id": 202 }` → `status: "sent"`, `token`, `invite_url` (the link in the email: `https://<website>/invite/<token>`).
2. Invitee opens the link: `GET /invitations/token/{token}` (no login needed) shows who invited them and the test. After login, `POST /invitations/token/{token}/accept` → `status: "accepted"` and an `attempt_id`.
3. The invitee finishes the test → `status: "completed"` with a `result_id` (real: when the attempt is submitted; sample: `POST /sample/invitations/{token}/complete`).
4. The sender sees each step in `GET /invitations/{invitation_id}` and `GET /invitations`.

Out-of-order steps are a 409, an expired invitation is a 410 (`POST /sample/invitations/{token}/expire` makes one expire now), a revoked one can't be accepted.

`/api/v1/sample/*` endpoints (tag `Sample: helpers`) only exist to stand in for Paystack and for finishing a test. Never call them from the real app.

## TypeScript types from `openapi.json`

`openapi.json` in the repo is the whole contract (real + sample endpoints), regenerated in every PR that changes the API. Generate types from it, e.g. with [openapi-typescript](https://openapi-ts.dev):

```bash
npx openapi-typescript ../careerline-api/openapi.json -o src/api/schema.d.ts
# or straight from the test server
npx openapi-typescript https://<service URL>/openapi.json -o src/api/schema.d.ts
```

```ts
import type { components } from "./api/schema";
type Result = components["schemas"]["ResultDetail"];
type Envelope<T> = { success: true; message: string | null; data: T };
```

`openapi-fetch` (same project) gives typed calls on top of the same file. Regenerate whenever `openapi.json` changes (it is listed in the PR, see below).

## Versioning and how changes are announced

- Everything is under `/api/v1`. Inside v1 we only make **additive** changes without notice to the code: new endpoints, new optional fields, new error codes, new scenarios. The app must ignore fields it doesn't know.
- A **breaking** change (removing or renaming a field or endpoint, changing a type, making a field required) is never made silently. The old one is first marked `deprecated` in `openapi.json` and kept for at least one week (or a `/api/v2` route is added), and it is announced as below.
- A sample endpoint becoming real is not a breaking change: same path, same shape. It loses its `Sample:` tag and `x-sample`, and starts using real data (it may then answer 404/403 where the sample answered with made-up data).
- **How changes are announced:** every PR that changes the API
  1. regenerates and commits `openapi.json` (CI fails otherwise), so the PR diff shows exactly what changed;
  2. has the label `api-change` (and `breaking-change` if it breaks anything);
  3. adds a line to the Changelog below;
  4. is posted in the team channel with the PR link when merged into `dev` (the test server deploys `dev`).

## Test server (Render)

`render.yaml` is a Render Blueprint: a web service (the API), a background worker and a Postgres 16 database, in Frankfurt.

- Every deploy runs `scripts/start.sh`: `alembic upgrade head` first, then the server. If a migration fails, the new version never takes traffic.
- `SECRET_KEY` is generated by Render once (`generateValue`) and shared with the worker; it never appears in the repo.
- `CORS_ORIGINS` is the website's address(es), comma-separated, set in the dashboard: only those origins can call the API from a browser.
- `APP_ENV=staging` and `SAMPLE_API_ENABLED=true`: the sample endpoints are on. In production they are off.
- The worker (`python -m app.worker`) is a placeholder until Day 5: it starts, checks the database and logs a heartbeat.

## Changelog

Newest first. One line per API change, with the PR.

- **Day 3**: sample endpoints for privacy, payments (Paystack checkout, credits), subscriptions, recruiter, invitations, organisation audit, heatmap and targets; checkout and invitation flows work end to end on sample data; `/api/v1/sample/*` helpers.
- **Day 2**: sample endpoints for contact, accounts, skills and roles, tests, results (PDF report), profile, beginner path and programme clicks; `X-Sample-Data` and `X-Mock-Scenario`; new error codes `payment_required` (402), `expired` (410), `rate_limited` (429); `openapi.json` committed.

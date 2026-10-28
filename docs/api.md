# CareerLine API: how to use it

For the frontend (Andrew) and anyone calling the API. The contract is `openapi.json` at the repo root; this page explains how to use it and how changes are announced.

## Base URLs

| Where | API base | Interactive docs |
| --- | --- | --- |
| Local | `http://localhost:8000/api/v1` | `http://localhost:8000/docs` |
| Test server (Render) | `https://<careerline-api service URL>/api/v1` (shown at the top of the service in Render, e.g. `https://careerline-api.onrender.com`) | `https://<service URL>/docs` |

Outside the `/api/v1` prefix: `GET /healthz` (the app is up), `GET /readyz` (the database is reachable and migrated), `/docs` (Swagger) and `/openapi.json` (the live contract).

## Log in

1. **Sign up:** `POST /api/v1/auth/register` with JSON `{ "full_name", "email", "phone", "password" }` (password at least 8 characters). The answer already holds a token (the new account is signed in). A confirmation email is sent at the same time.
2. **Sign in:** `POST /api/v1/auth/login` as a **form** (`application/x-www-form-urlencoded`), not JSON: `username=<email>&password=<password>`. The answer is the standard OAuth2 body `{ "access_token", "token_type": "bearer", "learner_id", "full_name" }` (no envelope). Emails are not case-sensitive.
3. Send `Authorization: Bearer <access_token>` on every protected call. A token lasts 24 hours; a `401` means sign in again.
4. **Sign out:** `POST /api/v1/auth/logout` (with the token). That token stops working at once; other devices stay signed in. `?everywhere=true` signs out every device.

```ts
const form = new URLSearchParams({ username: email, password });
const res = await fetch(`${API}/auth/login`, { method: "POST", body: form });
const { access_token } = await res.json();
```

**Sessions.** Every sign-in is a session on the server. Sign-out ends one; a password reset ends all of them; changing the password ends all the others (the device that changed it stays signed in). Tokens issued before Day 6 no longer work: sign in again.

**Too many failed sign-ins.** After 5 failed sign-ins for one email (whether or not it has an account) or 20 from one IP address within 15 minutes, `POST /auth/login` answers `429 rate_limited` with `Retry-After` (seconds), even with the right password. Show "Too many attempts, try again in N minutes". A wrong password and an unknown email get exactly the same `401` ("Invalid email or password").

### Email confirmation and password reset

The emails link to two pages of the website (`FRONTEND_URL` on the server, e.g. `http://localhost:5173`), with the token in the query string:

| Email | Link | The page calls | Answers |
| --- | --- | --- | --- |
| Confirm your email (after sign-up) | `/verify-email?token=…` | `POST /api/v1/accounts/verify-email` `{ "token" }` | `200`, or `410 expired` (old, used or unknown link: offer "send a new link") |
| Reset your password | `/reset-password?token=…` | `POST /api/v1/accounts/password-reset/confirm` `{ "token", "new_password" }` | `200` (every device is signed out: send to sign-in), or `410 expired` |

- `POST /api/v1/accounts/password-reset` `{ "email" }` (forgot password) always answers `202`, whether or not the email has an account. The link works once, for 60 minutes; asking again makes the older link stop working.
- `POST /api/v1/accounts/verify-email/resend` (signed in) sends a new confirmation link (the old one stops working); at most 3 an hour. Confirmation links work once, for 48 hours.
- `GET /api/v1/accounts/me` shows `email_verified`. Signing in does not require a confirmed email (yet).
- `POST /api/v1/accounts/me/password` `{ "current_password", "new_password" }`: a wrong current password is `400 wrong_password`.
- On the test server, read these emails (and their `links`) from the test mailbox (below).

## Answers and errors

Every answer except login is an envelope:

```json
{ "success": true, "message": null, "data": { "...": "..." } }
```

```json
{ "success": false, "error": { "code": "not_found", "message": "Attempt 9 not found", "request_id": "3f2a…" } }
```

- Read `data` on success. On error, branch on `error.code` (stable) and show `error.message` (human text, may change). Validation errors (`422`) also have `error.details`: a list of `{ loc, msg, type }`, e.g. `loc: ["body", "email"]`.
- Every error has a **reference number**: `error.request_id`, also sent as the `X-Request-ID` header (every response has it). Show it with the error ("Something went wrong. Reference: 3f2a…") and put it in bug reports: it finds the request, and for a 500 the full stack trace, in the server logs. You can send your own `X-Request-ID` (letters, digits, `-`, `_`, up to 64 characters) and it is kept.
- Errors never contain internal details: a `500` always says "Something went wrong. Please try again later." (the cause is only in the server log), and `422` details never echo what was sent.
- Lists are pages: `data = { items, total, limit, offset }`; send `?limit=&offset=`.
- Money is in the smallest unit: `{ "amount": 500000, "currency": "NGN" }` is NGN 5,000.00 (Paystack's kobo).
- Times are ISO 8601 in UTC (`2026-10-22T09:00:00Z`); dates are `YYYY-MM-DD`. Ids are integers, except payment references and invitation tokens (strings).
- Levels are `BEGINNER`, `JUNIOR`, `MID`, `ADVANCED`.

| Status | `error.code` | Meaning | What the app should do |
| --- | --- | --- | --- |
| 400 | `bad_request` | Invalid input (message says what) | Show the message |
| 400 | `wrong_password` | Change password: the current password is not correct | Show it on the field |
| 401 | `unauthenticated` | No token, bad token or expired | Send to login |
| 402 | `payment_required` | Not enough credits / no subscription | Send to buy credits or plans |
| 403 | `forbidden` | Logged in, but not allowed (someone else's data, wrong account type) | Show "not allowed" |
| 404 | `not_found` | Doesn't exist (or isn't yours) | Show "not found" |
| 405 | `method_not_allowed` | Wrong HTTP method | Bug in the call |
| 409 | `conflict` | Already done (e.g. invitation already used); tests also use `not_current_question`, `attempt_finished`, `skill_not_ready` | Refresh the item |
| 410 | `expired` / `gone` | Link, token, offer or test time expired / old route retired | Ask for a new link, or show the test's end |
| 422 | `validation_error` | Body or parameters invalid (`details` lists the fields) | Show the field errors |
| 429 | `rate_limited` | Too many requests (`Retry-After` header, seconds) | Wait and retry |
| 500 | `internal_error` | Our bug | Generic error + request id |
| 503 | `service_unavailable` | Down or database migrating | Retry shortly |

## Contact form

`POST /api/v1/contact` (public, no login) with `{ "full_name", "email", "topic", "organisation"?, "message" }` (`topic`: `general`, `support`, `sales`, `partnership`, `organisation_audit`; `message` 10 to 5000 characters). Answer `201` `{ ticket_id, status: "received", received_at }`. The team gets an email they can reply to, and the sender gets an acknowledgement with the ticket number.

- **Spam trap:** the optional field `website` must stay empty. Render it as a text input hidden from people (e.g. off-screen, `tabindex="-1"`, `autocomplete="off"`); bots fill it. A filled one gets a normal-looking answer and nothing is sent.
- At most 5 messages an hour per email address and per IP address, then `429 rate_limited` with `Retry-After`.

## Emails and the test mailbox (test server only)

Every email (contact form today; sign-up confirmation and password reset next) is sent by a background job a few seconds after the request, never during it. On the test server emails are not really sent: they go to a **test mailbox** you can read through the API, so tests can follow a whole flow (e.g. sign up, read the confirmation email, open its link).

```http
GET /api/v1/test-mailbox?to=ada@example.com        # newest first: subject, text, html, links[]
DELETE /api/v1/test-mailbox?to=ada@example.com     # empty it before a test
X-Test-Mailbox-Token: <ask the backend lead>       # only when the server has a token set
```

`links` lists every link in the email (e.g. the confirmation link), so a test can take `links[0]`. The test mailbox does not exist in production, and answers `404` when emails really go out.

## Who can call what (Day 7)

The signed-in person always comes from the token's session, never from the request. Use the `/me` routes: `GET /learners/me`, `/attempts/me`, `/recommendations/levels/me`, `/recommendations/pathway/me/{skill_id}`. The older routes with a learner id in the path still work for your own id (`403` for anyone else's) and are marked deprecated. `learner_id` in the body of `POST /learners/behavioural-answers` is no longer needed.

An account can belong to one organisation, with one role. `GET /accounts/me` shows it: `account_type` (`learner`, `recruiter`, or `organisation_admin` for owners and admins), `organisation_id` and `organisation_role` (`owner`, `admin`, `recruiter` or `null`).

| | Owner | Admin | Recruiter | Learner (no organisation) |
| --- | --- | --- | --- | --- |
| Learner routes (tests, results, profile, payments, ...) for themselves | ✓ | ✓ | ✓ | ✓ |
| `/recruiter/*`, sending and reading `/invitations` | ✓ | ✓ | ✓ | 403 |
| `GET /organisations/me` | ✓ | ✓ | ✓ | 403 |
| Audit roster (`/members`), audits, heatmap, targets | ✓ | ✓ | 403 | 403 |
| `/organisations/{id}/users`: add, change, remove admins and recruiters | ✓ | ✓ | 403 | 403 |
| Make, demote or remove owners | ✓ | 403 | 403 | 403 |

- Not signed in: `401`. Signed in without the permission: `403 forbidden`. Another organisation's id in the path: `404` (its existence is never confirmed).
- Opening and accepting an invitation (`/invitations/token/...`) works for any account.
- Organisation accounts: `GET /organisations/{id}/users` lists them; `POST` `{ "email", "role" }` gives an existing account a role (`404` if nobody has signed up with that email, `409` if it belongs to an organisation already); `PATCH /organisations/{id}/users/{learner_id}` `{ "role" }`; `DELETE` removes it from the organisation (the account stays). The last owner can't be demoted or removed (`409`).
- The rules live in one file, `app/core/permissions.py`, with a test that calls every route as every role.

## Demo accounts (test server only)

The test server loads these on every deploy (`DEMO_DATA_ON_START=true`). Every account has the password **`demo-password-not-secret`** (public and fake on purpose; any change you make to a demo account is undone at the next deploy).

| Email | Is |
| --- | --- |
| `demo.learner@example.com` | a learner |
| `demo.learner2@example.com` | a second learner (e.g. the candidate a recruiter invites) |
| `demo.professional@example.com` | a professional with four finished tests and a skill history (Frontend Web Development twice, JUNIOR then MID; API Design; Backend Development) for the results and history screens |
| `demo.owner@example.com` | owner of Demo Company Ltd (organisation id 41) |
| `demo.admin@example.com` | admin of Demo Company Ltd |
| `demo.recruiter@example.com` | recruiter of Demo Company Ltd |

Organisation 41 is also the sample organisation, so the sample audit, heatmap and target routes answer for it. Emails to these accounts land in the test mailbox.

## Job roles, titles and which skills can be tested (Day 8)

- `GET /roles` lists the 8 pilot job roles (ids 101 to 108; 101 Frontend Developer, 102 Backend Developer and 103 Data Analyst keep the sample ids). `GET /roles/{role_id}` gives a role's skills, main skill first. `target_level` is the level the role needs at the **mid** title.
- `GET /job-titles` is the ladder: intern (BEGINNER), junior (JUNIOR), mid (MID), senior (ADVANCED), lead (ADVANCED). For another title, a skill's level moves by as many steps as the title is from mid, staying within BEGINNER to ADVANCED. Example: Frontend Developer needs Frontend Web Development at MID; a senior needs ADVANCED, an intern BEGINNER.
- `test_ids` in a role: one per skill that can be tested now. Until `GET /tests` is real, a test id is `200 + skill_id` (so 201 is Frontend Web Development); start it with `POST /attempts/start` and that `skill_id`.
- `GET /skills/` has `testable` for each skill. A skill can be tested only when every level has at least 15 questions that passed the question-quality check. Otherwise `POST /attempts/start` answers `409` with code `skill_not_ready` and `details: {"minimum_per_level": 15, "short_by": {"MID": 3}}`. Show those skills as "coming soon". Today 14 of the 50 skills can be tested.

## Taking a test (Day 10)

The adaptive test: 16 questions, one at a time, harder after a right answer and easier after a wrong one, 30 minutes. No pass or fail and no self-declared level: the test finds the level (docs/adaptive-engine.md).

1. `POST /attempts/start` with `{"skill_id": 1}` → the attempt state with the first `question` (`question_id`, `question_text`, `subskill_id`, `options` with `option_id` and `option_text`; never which option is right). If a test of that skill is already in progress it is resumed: same attempt, same question, `resumed: true`. `declared_level` is retired: still accepted, ignored. A first test starts at JUNIOR, a retake at the level the person reached last time.
2. `POST /attempts/{attempt_id}/answer` with `{"question_id": …, "selected_option_id": …}` → the next question (`answered` goes up; the response never says whether the answer was right), or after the last one `status: "completed"` with `result` and `recommendations`.
3. After a reload, `GET /attempts/{attempt_id}/question` gives the same state again.

`result`: `score` (0–100), `level` (BEGINNER 0–40, JUNIOR 41–60, MID 61–80, ADVANCED 81–100), `confidence` (0–1) and `confidence_label` (low/medium/high), `answered`, `correct`, `strengths` and `weaknesses` (subskills), `subskills` (each with `band`: strong/developing/weak), `ended_by` (`finished` or `time_up`), `completed_at`. `GET /attempts/{attempt_id}` carries the same `result`.

Errors: `409 not_current_question` (that question is not the one to answer now: already answered or never served), `409 attempt_finished` (the test is over or cancelled: start a new one), `400` (an option of another question), `410 expired` (the 30 minutes ran out; `details.status` is `completed` when at least 8 questions were answered, so there is a result with `ended_by: "time_up"`, or `expired` with no result), `409 skill_not_ready` (Day 8). `POST /attempts/submit` (the old fixed test) answers `410 gone`.

My skills: `GET /profile/skills` is the latest level per skill tested; `GET /profile/skills/history` (optionally `?skill_id=`) every finished test, newest first, with level, score, confidence, strengths and weaknesses.

## Background jobs

Slow work runs in background jobs, after the request has answered: emails, and the AI advice for weak subskills. The answer that finishes a test (before Day 10, `POST /attempts/submit`) answers at once with plain advice and `recommendations.ai_advice`: `"queued"` (the AI advice replaces it within a minute or so: read it from `GET /recommendations/pathway/...`) or `"unavailable"` (no AI configured: the plain advice stays).

## Sample data

Endpoints that are not built yet answer with **realistic, typed sample data**, on their real path, in the real envelope, with the real response model. Build the screens against them now: when the real feature lands (Days 6–27) the path and the shape stay the same, only the data becomes real.

How to tell:

- Response header `X-Sample-Data: true` (the browser can read it: it is in `Access-Control-Expose-Headers`), and `"message": "Sample data"` on success.
- In `/docs` and `openapi.json` they are tagged `Sample: …` and carry `"x-sample": true`. When an endpoint becomes real, its `Sample:` tag and `x-sample` go away (see Changes below).
- Protected sample endpoints need a real sign-in, and the organisation and recruiter ones the right organisation role (see "Who can call what"). On the test server, use the demo accounts.

What is real today: `/auth/*`, `/accounts/*`, `/learners/*`, `/skills/*`, `/roles`, `/job-titles`, `/attempts/*`, `/profile/skills` (and its history), `/recommendations/*`, `/contact`, `/organisations/{id}/users` and who may call every route (they use the database; on the test server it holds the real question bank from `seeds/`). Everything tagged `Sample:` is sample.

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
3. The invitee finishes the test → `status: "completed"` with a `result_id` (real: when the attempt is finished; sample: `POST /sample/invitations/{token}/complete`).
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
- The worker (`python -m app.worker`) runs the background jobs (emails, AI advice). On the **free plan** there is no worker service: set `RUN_JOBS_IN_WEB=true` on the web service and the API process runs the jobs itself.
- `DEMO_DATA_ON_START=true` loads the demo accounts and Demo Company Ltd on every deploy (see "Demo accounts"); it is refused in production.
- Emails: `APP_ENV=staging` sends them to the test mailbox (see "Emails and the test mailbox"); set `TEST_MAILBOX_TOKEN` to keep it private. Production needs `EMAIL_BACKEND=smtp` with `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `EMAIL_FROM` and `SUPPORT_EMAIL`.

## Changelog

Newest first. One line per API change, with the PR.

- **Day 10**: real test-taking (see "Taking a test"). `POST /attempts/start` returns the attempt state with one `question` (was: all questions at once) and resumes a test in progress; `declared_level` is ignored (was: required, `400` when invalid). New `GET /attempts/{attempt_id}/question` and `POST /attempts/{attempt_id}/answer`. `POST /attempts/submit` answers `410 gone` (the pass/fail result, `status: passed/failed`, `confirmed_level` and `level_suggestion` are gone). `GET /attempts/{attempt_id}`: new `result`, and `attempt_status` can be `expired`. `GET /profile/skills` is real (no more `X-Sample-Data`; `level` and `percentage_score` come from the latest test) and new `GET /profile/skills/history`. New demo account `demo.professional@example.com`. Still sample and unchanged: `/results` (its `passed` field will go when it is made real).
- **Day 9**: no API change. The adaptive test engine and its simulation (docs/adaptive-engine.md); Day 10 serves it.
- **Day 8**: `GET /roles` and `GET /roles/{role_id}` are real (same shapes, no more `X-Sample-Data`; 8 pilot roles, ids 101 to 108; `test_ids` only lists skills that can be tested now, as `200 + skill_id`). New `GET /job-titles` (the title ladder with the expected level for each). `GET /skills/`: new field `testable`. `POST /attempts/start`: new `409 skill_not_ready` for a skill without enough reviewed questions; only questions that passed the quality check are served.
- **Day 7**: who may call what is enforced on every route (table in "Who can call what"): organisation and recruiter routes need an organisation role (learners get `403`; before, any token worked), another organisation's id is `404`. New `/me` routes (`/learners/me`, `/attempts/me`, `/recommendations/levels/me`, `/recommendations/pathway/me/{skill_id}`); the learner-id routes are deprecated. New `/organisations/{id}/users` (accounts and roles). `/accounts/me`: real `account_type` and `organisation_id`, new field `organisation_role`. `learner_id` optional in `POST /learners/behavioural-answers`. Demo accounts on the test server.
- **Day 6**: accounts are real (same paths and shapes, no more `X-Sample-Data` on `/accounts/*`): confirmation and reset emails with links to `/verify-email?token=` and `/reset-password?token=` on the website; new `POST /api/v1/auth/logout` (`?everywhere=true`); sign-in answers `429` after too many failures; tokens from before Day 6 must sign in again; new error code `wrong_password` (400, change password).
- **Day 5**: every error carries a reference number (`error.request_id` = `X-Request-ID`) and a `500` never shows internals. `POST /api/v1/contact` is real (same shape; new optional spam-trap field `website`; `429` after 5 messages an hour). New, test server only: `GET`/`DELETE /api/v1/test-mailbox`. `POST /attempts/submit`: the AI advice now arrives later through a background job; new field `recommendations.ai_advice` (`queued` / `unavailable`).

- **Day 4** (breaking, for old clients only): removed the old duplicate `/api/*` routes (use `/api/v1`) and the open sign-up `POST /api/v1/learners/register` (use `POST /api/v1/auth/register`). A fresh database now has the 4 levels and the question bank (seed files).
- **Day 3**: sample endpoints for privacy, payments (Paystack checkout, credits), subscriptions, recruiter, invitations, organisation audit, heatmap and targets; checkout and invitation flows work end to end on sample data; `/api/v1/sample/*` helpers.
- **Day 2**: sample endpoints for contact, accounts, skills and roles, tests, results (PDF report), profile, beginner path and programme clicks; `X-Sample-Data` and `X-Mock-Scenario`; new error codes `payment_required` (402), `expired` (410), `rate_limited` (429); `openapi.json` committed.

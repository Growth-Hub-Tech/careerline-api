# CareerLine API: how to use it

For the frontend (Andrew) and anyone calling the API. The contract is `openapi.json` at the repo root; this page explains how to use it and how changes are announced.

## Base URLs

| Where | API base | Interactive docs |
| --- | --- | --- |
| Local | `http://localhost:8000/api/v1` | `http://localhost:8000/docs` |
| Test server (Render) | `https://<careerline-api service URL>/api/v1` (shown at the top of the service in Render, e.g. `https://careerline-api.onrender.com`) | `https://<service URL>/docs` |

Outside the `/api/v1` prefix: `GET /healthz` (the app is up), `GET /readyz` (the database is reachable and migrated), `/docs` (Swagger) and `/openapi.json` (the live contract). Production does not serve `/docs`, `/redoc` or `/openapi.json`; the contract is `openapi.json` in this repo.

## Log in

1. **Sign up:** `POST /api/v1/auth/register` with JSON `{ "full_name", "email", "phone", "password" }` (password at least 8 characters). The answer already holds a token (the new account is signed in). A confirmation email is sent at the same time.
2. **Sign in:** `POST /api/v1/auth/login` as a **form** (`application/x-www-form-urlencoded`), not JSON: `username=<email>&password=<password>`. The answer is the standard OAuth2 body `{ "access_token", "token_type": "bearer", "learner_id", "full_name" }` (no envelope). Emails are not case-sensitive.
3. **The website** does not keep the token: sign-in also sets it in the `careerline_session` cookie (HttpOnly, Secure, 24 hours), and the browser sends it back when every request is made with `credentials: "include"`. On a `POST`, `PUT`, `PATCH` or `DELETE` the cookie counts only when the request's `Origin` is one of `CORS_ORIGINS` (other sites can make a browser send the cookie, not the `Origin`). Other clients send `Authorization: Bearer <access_token>`; when both are sent, the header wins. A token lasts 24 hours; a `401` means sign in again.
4. **Sign out:** `POST /api/v1/auth/logout` (with the cookie or the token). That session stops working at once and the cookie is deleted; other devices stay signed in. `?everywhere=true` signs out every device.

```ts
const form = new URLSearchParams({ username: email, password });
await fetch(`${API}/auth/login`, { method: "POST", body: form, credentials: "include" });
const me = await fetch(`${API}/accounts/me`, { credentials: "include" }); // the cookie signs it in
```

`SESSION_COOKIE_SAMESITE` sets the cookie's `SameSite`: `lax` (the default, and production's) needs the website and the API on one domain (for example `careerline.ng` and `api.careerline.ng`); the test server, whose website and API are on different domains, uses `none`, which Safari and private windows block.

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
| 409 | `conflict` | Already done (e.g. invitation already used); tests also use `not_current_question`, `attempt_finished`, `skill_not_ready`, `attempt_not_finished` | Refresh the item |
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
X-Test-Mailbox-Token: <ask the backend lead>       # always needed
```

`links` lists every link in the email (e.g. the confirmation link), so a test can take `links[0]`. The test mailbox does not exist in production, and answers `404` when emails really go out or when the server has no `TEST_MAILBOX_TOKEN`.

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

Organisation 41 (the id the sample organisation routes used) has 50 seats and a team roster of 3 (Day 21): `demo.learner@` (Frontend Developer), `demo.learner2@` (Backend Developer) and `demo.professional@` (Data Analyst), so audit emails reach accounts you can sign in with. Emails to these accounts land in the test mailbox.

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

### Reviewing a finished test (Day 11)

`GET /attempts/{attempt_id}/review` → the test question by question, **only once it is over** (`completed`, `expired` or `cancelled`). While it is running the answer is `409 attempt_not_finished` and nothing about the answers is sent.

- `items[]`: `position`, `question_id`, `question_text`, `subskill_id`, `subskill_name`, `level`, `options` (in the order they were shown, each with `is_correct` and `chosen`), `selected_option_id` (`null`: not answered before the end), `correct_option_id`, `is_correct`, `explanation` and `explanation_source`.
- `explanation_source`: `ai` (written by the AI, once per question, then kept for everyone) or `standard` (a plain sentence naming the right answer and the choice).
- `ai_explanations`: `ready` (every item has its AI explanation), `generating` (being written in the background: ask again in a few seconds, e.g. every 3 s up to a minute) or `unavailable` (standard explanations only: no AI configured, or the AI failed).
- Also `attempt_id`, `skill_id`, `status` and `result` (the same `result` as above; `null` for an expired test without one).

My skills: `GET /profile/skills` is the latest level per skill tested; `GET /profile/skills/history` (optionally `?skill_id=`) every finished test, newest first, with level, score, confidence, strengths and weaknesses.

## Results and PDF skill reports (Day 12)

A result is a finished test: `result_id` is the test's `attempt_id` (the one in `GET /attempts/me`).

- `GET /results?limit=&offset=` → my results, newest first (a page): `result_id`, `attempt_id`, `test_id` (200 + `skill_id`), `skill_id`, `skill_name`, `level`, `percentage_score`, `completed_at`.
- `GET /results/{result_id}` → the same plus `confidence` (0–1), `confidence_label`, `percentile` (the share of all results of that skill with a lower score, in %; `null` until the skill has at least 5 results), `subskills` (with `band`), `strengths` and `gaps` (subskill names), `recommendations` (`subskill_name`, `text`, `programme_id`: the programme that best covers the result's skill, see "Programmes"; `null` when none does). Day 24 (re-tests): `previous_result` (`{ result_id, level, percentage_score, completed_at }` of my result in the same skill just before this one, `null` for a first test) and `score_delta` (this `percentage_score` minus the previous one, `null` without one).
- Someone else's result, a test still running and an expired test without a result are all `404`.

**The PDF report:**

1. `GET /results/{result_id}/report` → `status: "generating"` the first time (the PDF is made in the background, usually within a few seconds).
2. Poll the same call every 2–3 s until `status: "ready"`: then `download_url` and `expires_at` (15 minutes) are set. Open `download_url` directly (a link or `window.open`): it needs no `Authorization` header and answers the PDF as a download. Each poll gives a fresh link; an expired or changed link answers `410 expired` (poll again for a new one).
3. `status: "failed"`: show "try again" and call `POST /results/{result_id}/report` (`202`, `status: "generating"`). POST also makes a new version on purpose; the older links stop working.

The PDF has the skill, the person's name and date, level and score, right answers, confidence, every subskill with its band, strengths and areas to work on, the advice and the person's history in that skill.

## Beginner path (Days 13–15)

For people new to tech: a short questionnaire, then up to three career paths.

1. `GET /beginner-path/intake` (public) → `version` and `questions[]` (`question_id`, `section`: personality / goals / time / finances, `text`, `kind`: `single_choice` or `multi_choice`, `options[]` with `value` and `label`).
2. `POST /beginner-path/intake` (signed in) with `{ "version", "answers": [{ "question_id", "values": ["…"] }] }`: every question once, values from its options, one value for `single_choice`. `201` → `{ intake_id, submitted_at, recommendations[] }`, best first: `rank`, `role_id` (as in `GET /roles`), `title`, `match_score` (0–100: how well the answers fit the role), `reasons` (up to 3 short sentences to show), `starting_test_id` (the test to take first, 200 + `skill_id`; `null` when none of the role's skills can be tested yet), `programme` (the programme that best prepares for the role, as in `GET /programmes`: Day 15, the best one within the person's budget, or else the role's cheapest; `null` when the role has none) and `programme_within_budget` (Day 15: `true` the programme fits the budget answer, `false` nothing of this role does so it is the cheapest, `null` no programme). `400 bad_request`: an unknown question or value, a missing answer, two values for a single choice, or an old `version` (load the questionnaire again).
3. `GET /beginner-path/recommendations` (signed in) → the latest intake's paths; before any intake `{ "intake_id": null, "submitted_at": null, "recommendations": [] }`.

The same answers always give the same paths (for the same programme catalogue). The questionnaire's text and scoring live in `seeds/beginner_intake.json`.

How the budget counts (Day 15): each budget answer is a price limit (free only = NGN 0, under 50k = up to NGN 49,999.99, 50k–200k = up to NGN 200,000, over 200k = no limit). A role with a programme within the limit gets 2 extra points in its `match_score` and, when there is a limit, the reason "There is a free programme for this path" or "There is a programme within your budget" (always one of the 3 reasons). A role whose programmes are all over the limit gets nothing, so it scores a little lower. Weekly hours are scored as before (by the answer points) and do not filter programmes.

## Programmes (Day 14)

Incubate's own and partner courses that prepare for a job role. The catalogue lives in `seeds/programmes.json` (prices in kobo, like every `Money`).

- `GET /programmes` (public, `?role_id=`, `limit` 1–100, `offset`) → a page of `{ programme_id, name, provider, provider_type: incubate | partner, mode: online | in_person | hybrid, duration_weeks, price }`. Order: Incubate first, then the cheapest, then by id. The same order picks the programme shown on a career path or a result.
- `GET /programmes/{programme_id}` (public) → the same plus `summary`, `skills` (names), `role_ids` and `url`. An unknown or retired programme is `404`.
- `POST /programmes/{programme_id}/clicks` (signed in) with `{ "source": "result" | "beginner_path" | "programme_list" | "profile", "result_id"?: … }` → `201 { click_id, programme_id, redirect_url, clicked_at }`. Record the click first, then send the person to `redirect_url` (the provider's page with `ref=careerline&click=<click_id>`). `result_id`, when sent, must be one of your own finished results (`404` otherwise).

## Payments and credits (Days 16–17, Paystack)

Credits pay for tests (see "Paying for tests with credits"). People buy credit packs through Paystack. The test server uses Paystack's **test mode**: pay with Paystack's test cards, and no real money moves.

1. `GET /payments/credit-packs` (public) → `[{ pack_id, name, credits, price }]` (prices in kobo).
2. `POST /payments/checkout` (signed in) with `{ "item_type": "credit_pack", "item_id": <pack_id>, "callback_url"?: "<a page of the website>" }` → `201` a pending payment plus `authorization_url`. Send the person there (a full-page redirect, not an iframe). `callback_url` defaults to `<website>/payments/callback`; it must be on the website (`FRONTEND_URL` or one of `CORS_ORIGINS`), `400` otherwise. `item_type: "subscription_plan"` buys a plan (Day 25, see "Subscriptions"). `404`: no such pack or plan. `429 rate_limited` (with `Retry-After`): more than 20 payments started by the same person in an hour (Day 29). `503 service_unavailable`: payments are not set up or Paystack is not answering; nothing was charged, try again later.
3. Paystack sends the person back to `callback_url?reference=…&trxref=…`. Call `GET /payments/{reference}`: it asks Paystack about a pending payment, so it shows `paid` as soon as Paystack has the money. Show `pending` with a "checking…" state and poll every 2–3 s for up to a minute; `failed` → "payment failed, try again"; `abandoned` → the checkout was left unpaid (after an hour).
4. `GET /credits` → `credits_balance` and the latest 50 `transactions` (`change`, `reason`: purchase / test_started / refund / subscription_grant, `balance_after`). `GET /payments` → my payments, newest first (`limit` 1–100, `offset`).

A payment is paid, and its credits added, exactly once, however many times Paystack retries its webhook or the page is reloaded. Someone else's payment is `404`.

For the team: Paystack's webhook URL (Paystack dashboard → Settings → API Keys & Webhooks) is `<API base>/api/v1/payments/webhooks/paystack`. Paystack signs every call (`x-paystack-signature`, HMAC-SHA512 of the body with the secret key); anything unsigned or wrongly signed is `401`. A `charge.success` whose amount or currency is not the payment's is logged and never paid.

## Paying for tests with credits (Day 17)

- `GET /tests` (public; `?skill_id=`, `?role_id=`, `limit` 1–100, `offset`) is the real catalogue: every skill that can be tested now, `test_id` = 200 + `skill_id`. Every test is the adaptive test (all four `levels`, `format: "adaptive"`, `question_count` 16, `duration_minutes` 30). `price_credits` is the price (`0` = free). `GET /tests/{test_id}` adds `description`, `subskills` and `what_you_get`; a skill that cannot be tested yet is `404`.
- `GET /tests/{test_id}/access` (signed in) → `{ test_id, can_start, reason: free | credits | insufficient_credits, price_credits, credits_balance }`. When `can_start` is false, offer a credit pack.
- `POST /attempts/start` takes the price when a **new** test starts (a resumed test costs nothing more). Without enough credits it is `402 payment_required` and nothing starts. The charge shows in `GET /credits` as `test_started` (a negative `change`).
- A paid test that ends before any answer (cancelled with `PATCH /attempts/{id}/cancel`, or out of time) gives its credits back once (`refund`). After the first answer the credits are spent.
- Prices live in `seeds/test_prices.json` (by `skill_id`; a skill not listed is free). For now: Backend Development and Database Management 2 credits, Version Control (Git) 1, everything else free (the sample's prices; the team sets the real ones).

## Privacy (Day 18, NDPR / GDPR)

All signed in, except the download link.

- `GET /privacy/consents` → `{ items: [{ key, granted, updated_at }] }` for `marketing_emails`, `share_profile_with_recruiters`, `product_research`, `aux_hr_sharing` and `incubate_sharing` (the last two since Day 31). All are off until the person turns them on (`updated_at` is then the account's creation time). `PUT /privacy/consents` with `{ items: [{ key, granted }] }` changes only the keys sent and answers the full list. Every real change is kept with its time (setting a consent to what it already is records nothing).
- `POST /privacy/data-exports` → `202 { export_id, status: "queued", requested_at, download_url: null, expires_at: null }`. Only one at a time: while one is queued or ready, asking again answers that one. A background job makes one JSON file with everything held about the person (account, consents and their history, behavioural answers, every test with its answers and result, skill history, beginner-path answers, payments, subscriptions, credits, programme clicks, organisations, sign-in sessions, contact messages; never the password hash), then emails them that it is ready. The email links to `FRONTEND_URL/settings/privacy`, never to the file.
- `GET /privacy/data-exports/{export_id}`: poll until `status: "ready"`. `download_url` works for 15 minutes (`DATA_EXPORT_LINK_MINUTES`), so GET again for a fresh one. `expires_at` is when the copy is deleted (7 days, `DATA_EXPORT_DAYS`); after that it is `410 expired`, and a new one can be asked for. Someone else's export is `404`.
- `GET /privacy/data-exports/download/{token}` (no login: the link is the proof) → the JSON file as an attachment; `410 expired` for an old or bad link.
- `POST /privacy/account-deletion` with `{ password, reason? }` → `202 { status: "scheduled", requested_at, scheduled_for }`, 30 days ahead (`ACCOUNT_DELETION_GRACE_DAYS`). A wrong password is `400 wrong_password`. The person gets an email with the date. The account keeps working until then. `GET /privacy/account-deletion` shows the request (`404` if there is none). `DELETE /privacy/account-deletion` cancels it → `{ status: "cancelled", requested_at, scheduled_for: null }` (`404` if nothing is scheduled).
- When the date comes, a background job erases the person: their name, email, phone and password are replaced, the account is switched off (every session ends and sign-in fails), and their consents, beginner-path answers, behavioural answers, exports, programme clicks, organisation memberships, PDF reports, contact messages and emails are deleted. The webhook copies of their Paystack events are emptied, and a subscription is cancelled at once and its saved card forgotten (it is never charged again). What stays, with nothing pointing back to the person: test attempts and scores (so other people's percentiles do not change) and payment and credit records (kept for the accounts). Separately, for everyone, a daily job deletes sent emails (which hold the address they went to), finished background jobs and expired sign-in sessions once they are 30 days old.

## Recruiters: candidates and invitations (Day 19)

For owners, admins and recruiters of an organisation; everything is limited to the caller's organisation, and another organisation's candidate or invitation is `404`. A learner with no organisation gets `403`.

- `GET /recruiter/candidates` (`?status=added|invited|in_progress|completed`, `limit` 1–100, `offset`): newest first. A candidate's `status` follows their invitations: `completed` once one is completed, `in_progress` while one is accepted, `invited` while one is waiting, otherwise `added`. `POST /recruiter/candidates` `{ full_name, email, role_id? }` → `201` (an email already on the list is `409 conflict`; an unknown `role_id` is `404`). A shortlist holds `RECRUITER_SHORTLIST_LIMIT` candidates (25 by default): a new one past that is `409 shortlist_full` with `details: { limit, count }` (Day 31). `GET /recruiter/candidates/{candidate_id}`.
- `POST /invitations` `{ email, full_name, test_id, kind?: candidate | team_member, candidate_id?, organisation_id?, message?, expires_in_days? (1–30, default 7) }` → `201`. `test_id` is from `GET /tests`. For `kind: candidate` the candidate is found by `candidate_id` or email, or added. The invitee gets an email with the link `invite_url` = `FRONTEND_URL/invite/{token}` and the message.
- `GET /invitations` (newest first), `GET /invitations/{invitation_id}`, `POST /invitations/{invitation_id}/revoke` (revoking twice is fine; `409` once expired or completed). `status`: `sent`, `accepted`, `completed`, `revoked`, or `expired` (sent and past `expires_at`; an accepted one no longer expires).
- The invitee's page: `GET /invitations/token/{token}` is public → `{ token, status, invited_by, full_name, test_id, test_title, duration_minutes, message, expires_at, attempt_id }` (`404` unknown, `410 expired`). `POST /invitations/token/{token}/accept` (signed in, any email) starts the invited test **free of charge** and returns its `attempt_id`; the test is then taken with `/attempts/{attempt_id}/…`. Accepting twice is fine. Another account, or a revoked or completed invitation, is `409`.
- **Day 20**: when the invited test finishes, its invitation becomes `completed` (`result_id` = the attempt), and the candidate shows `latest_result` (`{ test_id, test_title, level, percentage_score, passed, completed_at, result_id }`; `passed`: the level meets what the candidate's role needs for that skill, or JUNIOR and up without a role). If the invited test is cancelled or runs out before a result, accepting again starts a new one. The learner's own tests never complete an invitation.
- `GET /recruiter/candidates/{candidate_id}/report` (Day 20; `404` until an invited test is finished) → `{ candidate_id, full_name, role_title, fit, summary, results, report_url }`. `fit` compares the newest result of each invited test with the level the role needs: all met → `strong_fit`, the worst one level short → `possible_fit`, otherwise `not_a_fit` (without a role the bar is MID). `summary`: "Confirmed MID in Python: strong on …, developing on …". `results`: every finished invited test, newest first; each has `shared` (Day 31: `true` when the result is shared with the organisation; a result that is not shared has no score to show). `report_url`: the newest result's PDF (works 15 minutes, no login needed); `null` while the PDF is being made, so GET again.

## Organisation audit (Days 21–24)

For owners and admins of an organisation (recruiters only see `GET /organisations/me`); everything is the caller's own organisation, and another organisation's id is `404`.

- `GET /organisations/me` → `{ organisation_id, name, industry, size, seats_total, seats_used, created_at }`. `seats_used` is the number of people on the team roster; `seats_total` is how many it may hold (25 for now; an organisation plan sets it from Days 25–26).
- `GET /organisations/{organisation_id}/members` (`?department=` any case, `limit` 1–100, default 50, `offset`): the team roster by name → `Page` of `{ member_id, full_name, email, department, role_id, role_title, status, latest_level }`. `status` follows the member's team invitations (an audit sends them): `not_invited`, `invited` (one waiting), `in_progress` (one accepted, or some finished and others still open), `completed` (all finished). `latest_level`: their newest team result in their role's main skill (`null` until then).
- `POST /organisations/{organisation_id}/members` `{ members: [{ full_name, email, department?, role_id }] }` (1–1000 people) → `{ added, updated, members_total }`. People already on the roster (same email, any case) get the uploaded name, department and role; the others are added. `role_id` is from `GET /roles`. Errors, where **nothing is saved**: `402 payment_required` (more people than seats; updating people already there needs no seat), `404` (an unknown `role_id`), `400` (the same email twice in one upload), `422` (no people, a bad email).
- Roster people do not need an account: their tests come as invitation emails, which they accept with any account (like a candidate's).
- `GET /organisations/{organisation_id}/audits` (`limit` 1–100, default 20, `offset`): newest first → `Page` of `{ audit_id, name, status, role_ids, members_total, members_completed, started_at, completed_at }`.
- `POST /organisations/{organisation_id}/audits` `{ name, role_ids, member_ids?, send_invitations? }` → `201` the audit. Its members are the roster people in `role_ids` (or the `member_ids` given, who must be on the roster and in those roles) whose role has at least one test that can be taken. With `send_invitations: true` (the default) each of them gets an invitation email for **every testable skill of their role** (one email per test, link `FRONTEND_URL/invite/{token}`, valid `AUDIT_INVITATION_DAYS`, 14 days; free for them, accepted with any account, exactly like a candidate's invitation). `send_invitations: false` makes a `draft`: nothing is sent until `POST /organisations/{organisation_id}/audits/{audit_id}/start` (`409` if already started). Errors: `404` an unknown role or member, `400` a member outside the roles, nobody on the roster in those roles, or none of the roles has a test yet.
- `GET /organisations/{organisation_id}/audits/{audit_id}` → the audit plus `benchmarks`. `status` follows the invitations: `draft`, `in_progress`, `completed` (every member has finished every test of the audit; revoked invitations don't count; `completed_at` = the last one finished). `members_completed`: members who finished all their tests. `benchmarks`: one per role and skill with at least one finished test, in the role's order: `target_level` (what the role needs, from `GET /roles/{role_id}`), `team_average_score` (the members' newest result in this audit), `members_at_or_above_target`, `members_tested`, and `industry_average_score` (everyone's newest score in that skill on CareerLine; `null` until 5 people have one, so no single person's score can be worked out).
- The team's invitations also show in `GET /invitations` (`kind: "team_member"`), and can be revoked there.
- `PUT /organisations/{organisation_id}/targets` `{ items: [{ role_id, skill_id, target_level, due_date? }] }` replaces **all** the organisation's targets (`[]` clears them) → the same as `GET`. `GET /organisations/{organisation_id}/targets` → `{ organisation_id, items: [{ role_id, role_title, skill_id, skill_name, target_level, due_date, members_total, members_meeting, progress_percent }] }`, by role then skill. `members_total`: roster people in that role; `members_meeting`: those whose newest team result in that skill is at or above the target. Errors (nothing changes): `400` the same role and skill twice, `404` an unknown role or skill, `422` a bad level. Audit benchmarks and the heatmap use the organisation's target when there is one, else what the role needs.
- `GET /organisations/{organisation_id}/heatmap?group_by=department|role|member&audit_id=` → `{ organisation_id, audit_id, group_by, skills: [{ skill_id, skill_name }], rows: [{ key, label, members, cells: [{ skill_id, average_score, level, members_tested, band }] }] }`. Columns are the skills of the people's roles (roles by title, each role's skills in its order); every row has one cell per column, in that order. A cell averages the people's newest team result in that skill; `level` is that average's level (the test's score bands: 0–40 BEGINNER, 41–60 JUNIOR, 61–80 MID, 81–100 ADVANCED); `band` compares it with the target (the highest among the row's people): `strong` meets it, `developing` one level short, `weak` further, `not_tested` nobody has a result (`average_score` and `level` `null`). Rows by label; `key` is the department in lower case with `-` for spaces (`none`: no department, label "No department"), the `role_id`, or the `member_id`. Without `audit_id` (`audit_id: null` in the answer): everyone on the roster, their newest team results from any audit. With `audit_id`: only that audit's people (with the role they had then) and its results (`404` for an audit that is not yours).

- **Re-test (Day 24, PRD "pre/post re-test")**: `POST /organisations/{organisation_id}/audits/{audit_id}/retest` `{ name?, member_ids?, send_invitations? }` → `201` a new audit with `baseline_audit_id` = that audit: the same people (or the `member_ids` given, who must have been in it: `400` otherwise) invited to **the same tests** again, e.g. after a course. `name` defaults to "<name> (re-test)"; `send_invitations: false` makes a draft (start it with `.../start`). `409` while the audit being re-tested is still a draft. **Day 31**: a re-test comes at least `RETEST_COOLDOWN_DAYS` (14) days after the audit's last test was started (the audit itself, or its last re-test): sooner is `409 retest_too_soon` with `details: { try_again_on: "2026-11-19", available_at }` (the date it can run again, UTC) and a message saying so. Every audit now carries `baseline_audit_id` (`null` for a first audit), and a re-test's benchmarks carry `baseline_average_score` (the baseline's team average for that role and skill) and `score_delta` (this audit's average minus it); both are `null` otherwise. `GET /organisations/{organisation_id}/audits/{audit_id}/deltas` → `{ audit_id, baseline_audit_id, items: [{ member_id, full_name, role_id, skill_id, skill_name, before_score, before_level, after_score, after_level, score_delta }] }`, by name: each person's newest result per skill in the baseline (before) and in the re-test (after); `score_delta` = after − before, `null` until both exist. `400` for an audit that is not a re-test.

## Background jobs

Slow work runs in background jobs, after the request has answered: emails, the AI advice for weak subskills, (Day 11) the AI explanations of a finished test's answers and (Day 12) the PDF skill reports. The answer that finishes a test (before Day 10, `POST /attempts/submit`) answers at once with plain advice and `recommendations.ai_advice`: `"queued"` (the AI advice replaces it within a minute or so: read it from `GET /recommendations/pathway/...`) or `"unavailable"` (no AI configured: the plain advice stays).

## Subscriptions (Days 25–26, Paystack)

Plans are real (`seeds/subscription_plans.json`): **Individual Monthly** (anyone), **Recruiter Monthly** (an organisation account: owner, admin or recruiter) and **Organisation Yearly** (an organisation's owner or an admin; one per organisation; gives the organisation its seats). Paying works like buying credits (test mode on the test server).

1. `GET /subscriptions/plans` (public) → `[{ plan_id, name, audience, interval, price, credits_per_interval, seats, features }]`.
2. `POST /subscriptions` `{ plan_id, callback_url? }` (signed in; the same as `POST /payments/checkout` with `item_type: "subscription_plan"`) → `201` a pending payment plus `authorization_url`: send the person there, then `GET /payments/{reference}` on the callback page, exactly as for credits. `403`: the plan is not for this account (the message says why). `409`: a plan is already live (cancel it and subscribe again when it ends), or the organisation already has one. `404`: no such plan. `503`: payments are not set up.
3. Once Paystack has the money the plan is **active** from now to the same day next month (or next year), and its `credits_per_interval` are added (`reason: "subscription_grant"` in `GET /credits`). An organisation plan's `seats` become the organisation's `seats_total` (`GET /organisations/me`) while it is live.
4. `GET /subscriptions/me` → the live subscription (`status: "active"`; `"past_due"`: the period ended unpaid, still usable for `SUBSCRIPTION_GRACE_DAYS`, 3; paying again with `POST /subscriptions` renews it), else the newest ended one (`"cancelled"`), else `null`. Day 31: `grace_ends_at` is the day that grace ends while `past_due` (`current_period_end` + `SUBSCRIPTION_GRACE_DAYS`), else `null`.
5. `POST /subscriptions/me/cancel` → `cancel_at_period_end: true`; the plan (and its seats) stays until `current_period_end`, then it is `cancelled`. Calling it again changes nothing; `404` without a live plan.
6. **Day 31**: `POST /subscriptions/me/resume` undoes the cancellation while the period still runs → `200` the subscription with `cancel_at_period_end: false`, and it renews as usual. `409 conflict` when the plan is not cancelled or no live plan is left to resume (after the period has ended, subscribe again).

A plan is started (or renewed) and its credits added exactly once per payment, however often Paystack retries.

**Renewals (Day 26).** Nothing for the app to do: an hour before a period ends the server charges the card of the first payment again (when it was a card Paystack can charge again). Paid: the next period starts where the last one ended, its credits are added, and `GET /payments` shows a payment "… subscription (renewal)". Declined, or no card to charge (e.g. a bank transfer): the person gets one email ("Your … subscription could not be renewed") with a link to `<website>/subscription`, and the card is tried again once a day, up to `SUBSCRIPTION_RENEW_ATTEMPTS` (3) times. Unpaid when the period ends: `past_due` for the grace days, during which `POST /subscriptions` pays it again (a new period from that moment); then `cancelled`. A plan with `cancel_at_period_end` is never charged. When an organisation plan ends, the organisation's `seats_total` goes back to 25 (people already on the roster stay; uploads past the seats are `402`).


## Profile (Day 28)

- `GET /profile` → `{ learner_id, full_name, headline, location, current_role, years_experience, goals, weekly_hours, budget, linkedin_url, visibility, completeness, updated_at }`. Empty (`null`s, `goals: []`) and `visibility: "private"` until the person fills it in. `completeness` is the share filled in, in % (the name counts, so a new profile is 11).
- `PATCH /profile` with only the fields to change; `null` clears one. `goals`: up to 10, each 1–100 characters (`422` otherwise). `linkedin_url` must be a LinkedIn link (`https://www.linkedin.com/...`, `400` otherwise). `visibility: "recruiters"` turns on the `share_profile_with_recruiters` consent and `"private"` turns it off: it is the same switch as in `GET /privacy/consents`, and every change is kept.

## No sample data

Since Day 28 every endpoint is real: nothing answers `X-Sample-Data` any more, `X-Mock-Scenario` means nothing, and `openapi.json` has no `Sample:` tags or `x-sample`. For empty states and errors, use real data on the test server (the demo accounts, a new account, or the cases each endpoint's description lists).

## TypeScript types from `openapi.json`

`openapi.json` in the repo is the whole contract, regenerated in every PR that changes the API. Generate types from it, e.g. with [openapi-typescript](https://openapi-ts.dev):

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

- Everything is under `/api/v1`. Inside v1 we only make **additive** changes without notice to the code: new endpoints, new optional fields, new error codes. The app must ignore fields it doesn't know.
- A **breaking** change (removing or renaming a field or endpoint, changing a type, making a field required) is never made silently. The old one is first marked `deprecated` in `openapi.json` and kept for at least one week (or a `/api/v2` route is added), and it is announced as below.
- **How changes are announced:** every PR that changes the API
  1. regenerates and commits `openapi.json` (CI fails otherwise), so the PR diff shows exactly what changed;
  2. has the label `api-change` (and `breaking-change` if it breaks anything);
  3. adds a line to the Changelog below;
  4. is posted in the team channel with the PR link when merged into `dev` (the test server deploys `dev`).

## Test server (Render)

`render.yaml` is a Render Blueprint: for the test server and for production (see `docs/launch.md`), each a web service (the API), a background worker and a Postgres 16 database, in Frankfurt.

- Every deploy runs `scripts/start.sh`: `alembic upgrade head` first, then the server. If a migration fails, the new version never takes traffic.
- `SECRET_KEY` is generated by Render once (`generateValue`) and shared with the worker; it never appears in the repo.
- `CORS_ORIGINS` is the website's address(es), comma-separated, set in the dashboard: only those origins can call the API from a browser.
- `APP_ENV=staging`: the test mailbox and the demo accounts are on. In production they are off; production is set up with the checklist in `docs/launch.md`.
- The worker (`python -m app.worker`) runs the background jobs (emails, AI advice). On the **free plan** there is no worker service: set `RUN_JOBS_IN_WEB=true` on the web service and the API process runs the jobs itself.
- `PAYSTACK_SECRET_KEY`: Paystack's **test** secret key (`sk_test_…`) on the test server, set in the dashboard. Without it checkout and the webhook answer `503` (nothing is charged). Set Paystack's webhook URL to `<API base>/api/v1/payments/webhooks/paystack`.
- `DEMO_DATA_ON_START=true` loads the demo accounts and Demo Company Ltd on every deploy (see "Demo accounts"); it is refused in production.
- Emails: `APP_ENV=staging` sends them to the test mailbox (see "Emails and the test mailbox"); it answers only with `TEST_MAILBOX_TOKEN` (`404` while that is unset). Production needs `EMAIL_BACKEND=smtp` with `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `EMAIL_FROM` and `SUPPORT_EMAIL`.

## Changelog

Newest first. One line per API change, with the PR.

- **Day 31** (gap fixes, nothing that needed a team decision): additive only, no route or existing field changed meaning. New: `POST /subscriptions/me/resume` (see "Subscriptions", 6); `grace_ends_at` on the subscription; `409 retest_too_soon` with `details.try_again_on` on `POST .../audits/{audit_id}/retest` (cooldown `RETEST_COOLDOWN_DAYS`, 14); `409 shortlist_full` on `POST /recruiter/candidates` (limit `RECRUITER_SHORTLIST_LIMIT`, 25); `shared` on each candidate report result (and each `latest_result`); consent keys `aux_hr_sharing` and `incubate_sharing` (off by default). No migration.
- **Day 30**: ready for launch: every endpoint is real and this file plus `openapi.json` is the contract the website ships against; from here a breaking change follows "Versioning" above. The launch checklist is `docs/launch.md`. No route or response shape changed.
- **Day 29**: launch hardening. `POST /payments/checkout` and `POST /subscriptions` answer `429 rate_limited` (with `Retry-After`) after 20 payments started by one person in an hour (`CHECKOUTS_PER_HOUR`). In production the API refuses to start with unsafe or test settings (see README, "Going live"). No route or response shape changed.
- **Day 28**: the profile is real (`GET`/`PATCH /profile`, see "Profile"), so **every endpoint is real**. **Breaking against the sample:** a new profile is empty and private (the sample showed "Ada Okafor"); `full_name` is the account's name; `visibility` is the `share_profile_with_recruiters` consent (changing one changes the other); `goals` are checked (up to 10, 1–100 characters, `422`) and `linkedin_url` must be a LinkedIn link (`400`). The sample API is gone: no `X-Sample-Data` header (also gone from `Access-Control-Expose-Headers`), no `X-Mock-Scenario`, no `Sample:` tags or `x-sample` in `openapi.json`; `SAMPLE_API_ENABLED` is no longer read.
- **Day 26**: subscriptions renew themselves (see "Subscriptions": the saved card is charged an hour before the period ends; a decline emails the person and retries daily). No route or response shape changed. New optional env var `SUBSCRIPTION_RENEW_ATTEMPTS=3`; the website needs a `/subscription` page (the renewal email links to it). Nothing breaking.
- **Day 25**: subscriptions are real (see "Subscriptions"; no more `X-Sample-Data` on `/subscriptions/*`). `item_type: "subscription_plan"` on `POST /payments/checkout` now works (it was `400`). **Breaking against the sample:** `POST /subscriptions` answers Paystack's real (test-mode) `authorization_url`, not the sample Paystack page; a subscription exists only once paid (`GET /subscriptions/me` is `null` before); `403` when the plan is not for the account (recruiter and organisation plans), `409` for a second live plan, `503` without payments set up; the sample scenarios `past_due`, `cancelled` and `no_subscription` are gone; `/api/v1/sample/paystack/{reference}`, `/api/v1/sample/reset` and the other sample helpers are gone. `POST /payments/checkout` can also answer `403`/`409` for plans. Same paths and response shapes. New optional env var `SUBSCRIPTION_GRACE_DAYS=3`; `SAMPLE_STATE_FILE` is no longer read.
- **Day 24**: pre/post re-tests. New: `POST /organisations/{organisation_id}/audits/{audit_id}/retest` and `GET .../audits/{audit_id}/deltas` (see "Re-test"). New fields, all additive: `baseline_audit_id` on audits, `baseline_average_score` and `score_delta` on benchmarks, `previous_result` and `score_delta` on `GET /results/{result_id}`. Nothing breaking.
- **Day 23**: targets (`GET`/`PUT /organisations/{organisation_id}/targets`) and the capability heatmap (`GET /organisations/{organisation_id}/heatmap`) are real, so the whole organisation audit is real (see "Organisation audit"; no more `X-Sample-Data` under `/organisations`). Audit benchmarks now use the organisation's targets. **Breaking against the sample:** the sample targets and heatmap rows are gone (a new organisation has none); without `audit_id` the heatmap's `audit_id` is `null` (everyone's newest results, not one audit); columns are the skills of the roster's roles; `level` and `band` follow the rules above (`band` is against the target, not fixed score lines); `PUT` refuses a repeated role and skill (`400`) and unknown ones (`404`); the sample's `empty` scenario is gone. Same paths and response shapes.
- **Day 22**: audits are real: `GET`/`POST /organisations/{organisation_id}/audits` and `GET .../audits/{audit_id}` (see "Organisation audit"; no more `X-Sample-Data` on them). New: `POST /organisations/{organisation_id}/audits/{audit_id}/start` starts a draft. Starting an audit emails every member an invitation per testable skill of their role; the members' `status` and `latest_level` now move. **Breaking against the sample:** the sample audit 1201 is gone; `members_total` counts only people whose role has a test; `benchmarks` lists only roles and skills with a finished test (empty until then); `industry_average_score` is `null` until 5 people have a result in that skill; `limit` is checked (1–100); unknown roles or members are `404`, bad picks `400`. Same paths and response shapes. Still sample: heatmap, targets.
- **Day 21**: `GET /organisations/me` and the team roster (`GET`/`POST /organisations/{organisation_id}/members`) are real (see "Organisation audit"; no more `X-Sample-Data` on them). New: `seats_total` is enforced (`402 payment_required`, nothing saved) and `seats_used` is the roster's size. **Breaking against the sample:** the sample members 901–904 are gone (a new organisation's roster is empty; the demo company has 3 people); `status` is `not_invited` and `latest_level` `null` until audits send tests (Day 22); `limit` is checked (1–100); an unknown `role_id` is `404` and a repeated email `400`; these routes need a real organisation role (a learner gets `403`; the sample's `empty` and `forbidden` scenarios are gone). Same paths and response shapes. Still sample: audits, heatmap, targets.
- **Day 20**: invitations complete when the test finishes, candidates carry `latest_result`, and `GET /recruiter/candidates/{candidate_id}/report` is real (no more sample routes under `/recruiter`). **Breaking:** `report_url` can be `null` while the PDF is being made (GET again); it is a 15-minute link to the PDF itself, not a lasting URL. `passed` now means "meets the role's level" (there is no pass mark).
- **Day 19**: candidates and invitations are real (see "Recruiters: candidates and invitations"; no more `X-Sample-Data` on them). `invite_url` is now `FRONTEND_URL/invite/{token}` (the sample used the API's host). **Breaking:** the sample helpers `POST /sample/invitations/{token}/complete` and `/expire` are gone. `test_id` must be a real catalogue test, not the sample's 201/202/203/208. Accepting needs a real account and starts a real test. A recruiter needs a real organisation role (the sample let any login through and had a `forbidden` scenario). Candidate lists are limited to 1–100 per page, and a bad `status` filter is `422`.
- **Day 18**: privacy is real (see "Privacy"; no more `X-Sample-Data` on `/privacy/*`). Consents start off for everyone (the sample had `share_profile_with_recruiters` on). New: `GET /privacy/account-deletion` and `GET /privacy/data-exports/download/{token}`. **Breaking:** `download_url` now works for only 15 minutes (GET the export again for a fresh one); an expired export is `410 expired`; deletion now really checks the password (`400 wrong_password`). The sample's `pending` scenario is gone.
- **Day 17**: the test catalogue is real (see "Paying for tests with credits"; no more `X-Sample-Data` on `/tests/*`): it lists every testable skill (the sample had 4 made-up tests), always adaptive with 16 questions and 30 minutes; the sample's test `208` (fixed format) and `levels` subsets are gone; `limit` is checked (1–100). `GET /tests/{test_id}/access` is real. **Breaking:** `POST /attempts/start` on a paid test now takes credits and answers `402 payment_required` without enough (before, every test was free); new credit `reason` values in use: `test_started`, `refund`. The sample's `empty` and `payment_required` scenarios on `/tests` are gone.
- **Day 16**: payments and credits are real (see "Payments and credits"; no more `X-Sample-Data` on `/payments/*` and `/credits`). **Breaking against the sample:** the sample Paystack page is gone for credit packs: `authorization_url` is Paystack's real (test-mode) checkout page; a new person's `credits_balance` starts at `0` (the sample gave 3); `item_type: "subscription_plan"` on `POST /payments/checkout` is `400` until Days 25–26 (`POST /subscriptions` is still sample and still uses the sample Paystack page); `callback_url` must be a page of the website (`400` otherwise); `503 service_unavailable` when payments are not set up; the webhook needs Paystack's signature (`401`) and no longer takes the sample body; the sample scenarios on these routes (`empty`, `pending`, `paid`, `failed`) are gone. `GET /payments` checks `limit` (1–100). Same paths and response shapes.
- **Day 15**: beginner path: the budget answer now counts (see "Beginner path", "How the budget counts"). New field `recommendations[].programme_within_budget` (`true` / `false` / `null`). `programme` is now the best programme within the budget, or the role's cheapest when none fits. `match_score` values can change for the same answers (a path with an affordable programme scores higher), and a budget reason can be one of the 3 `reasons`. Intakes saved before this deploy read back with `programme_within_budget: null`. No route or field removed.
- **Day 14**: `/programmes/*` is real (see "Programmes"; no more `X-Sample-Data`): 14 programmes covering all 8 pilot roles; the sample's `empty` scenario is gone; `limit` above 100 or below 1 is `422`. `POST /programmes/{programme_id}/clicks`: `result_id` must be your own finished result (`404` otherwise; the sample accepted any id), and `redirect_url` is the programme's real `url` with `ref` and `click`. Beginner path: each path's `programme` is now filled (`null` only when the role has no programme). Results: `recommendations[].programme_id` is now filled when a programme covers the result's skill. No route or field removed.
- **Day 13**: `/beginner-path/*` is real (see "Beginner path"; no more `X-Sample-Data`). The questionnaire has 6 questions (version `2026-11`; the sample's `2026-10` answers `400`). Every question must be answered; values are checked. `recommendations` has up to 3 paths; `starting_test_id` can be `null`; `programme` is `null` for now. `GET /beginner-path/recommendations` before any intake: `intake_id` and `submitted_at` are `null` with an empty list (the sample's `empty` scenario is gone).
- **Day 12**: `/results` is real (see "Results and PDF skill reports"; no more `X-Sample-Data`): `result_id` is the `attempt_id` of a finished test (the sample ids 501 and 502 are gone). Breaking against the sample: `passed` (list and detail) and `declared_level` (detail) are removed; new in the detail: `confidence` and `confidence_label`; `percentile` is `null` until a skill has 5 results; `recommendations[].programme_id` is `null` for now. Someone else's result is `404`. `GET /results/{result_id}/report` is real (same shape): `generating`, then `ready` with a 15-minute `download_url`; new public `GET /reports/{token}` (that link) answers the PDF, or `410 expired`. `POST /results/{result_id}/report` makes it again (`202`). The report's sample `X-Mock-Scenario` values (`generating`, `failed`) are gone.
- **Day 11**: new `GET /attempts/{attempt_id}/review` (see "Reviewing a finished test"): every question of a finished test with the right answer, the choice and an explanation (AI or standard); `409 attempt_not_finished` while the test runs. New error code `attempt_not_finished` (409). No change to existing routes.
- **Day 10**: real test-taking (see "Taking a test"). `POST /attempts/start` returns the attempt state with one `question` (was: all questions at once) and resumes a test in progress; `declared_level` is ignored (was: required, `400` when invalid). New `GET /attempts/{attempt_id}/question` and `POST /attempts/{attempt_id}/answer`. `POST /attempts/submit` answers `410 gone` (the pass/fail result, `status: passed/failed`, `confirmed_level` and `level_suggestion` are gone). `GET /attempts/{attempt_id}`: new `result`, and `attempt_status` can be `expired`. `GET /profile/skills` is real (no more `X-Sample-Data`; `level` and `percentage_score` come from the latest test) and new `GET /profile/skills/history`. New demo account `demo.professional@example.com`. Still sample and unchanged: `/results` (its `passed` field will go when it is made real).
- **Day 9**: no API change. The adaptive test engine and its simulation (docs/adaptive-engine.md); Day 10 serves it.
- **Day 8**: `GET /roles` and `GET /roles/{role_id}` are real (same shapes, no more `X-Sample-Data`; 8 pilot roles, ids 101 to 108; `test_ids` only lists skills that can be tested now, as `200 + skill_id`). New `GET /job-titles` (the title ladder with the expected level for each). `GET /skills/`: new field `testable`. `POST /attempts/start`: new `409 skill_not_ready` for a skill without enough reviewed questions; only questions that passed the quality check are served.
- **Day 7**: who may call what is enforced on every route (table in "Who can call what"): organisation and recruiter routes need an organisation role (learners get `403`; before, any token worked), another organisation's id is `404`. New `/me` routes (`/learners/me`, `/attempts/me`, `/recommendations/levels/me`, `/recommendations/pathway/me/{skill_id}`); the learner-id routes are deprecated. New `/organisations/{id}/users` (accounts and roles). `/accounts/me`: real `account_type` and `organisation_id`, new field `organisation_role`. `learner_id` optional in `POST /learners/behavioural-answers`. Demo accounts on the test server.
- **Day 6**: accounts are real (same paths and shapes, no more `X-Sample-Data` on `/accounts/*`): confirmation and reset emails with links to `/verify-email?token=` and `/reset-password?token=` on the website; new `POST /api/v1/auth/logout` (`?everywhere=true`); sign-in answers `429` after too many failures; tokens from before Day 6 must sign in again; new error code `wrong_password` (400, change password).
- **Day 5**: every error carries a reference number (`error.request_id` = `X-Request-ID`) and a `500` never shows internals. `POST /api/v1/contact` is real (same shape; new optional spam-trap field `website`; `429` after 5 messages an hour). New, test server only: `GET`/`DELETE /api/v1/test-mailbox`. `POST /attempts/submit`: the AI advice now arrives later through a background job; new field `recommendations.ai_advice` (`queued` / `unavailable`).

- **Day 4** (breaking, for old clients only): removed the old duplicate `/api/*` routes (use `/api/v1`) and the open sign-up `POST /api/v1/learners/register` (use `POST /api/v1/auth/register`). A fresh database now has the 4 levels and the question bank (seed files).
- **Day 3**: sample endpoints for privacy, payments (Paystack checkout, credits), subscriptions, recruiter, invitations, organisation audit, heatmap and targets; checkout and invitation flows work end to end on sample data; `/api/v1/sample/*` helpers.
- **Day 2**: sample endpoints for contact, accounts, skills and roles, tests, results (PDF report), profile, beginner path and programme clicks; `X-Sample-Data` and `X-Mock-Scenario`; new error codes `payment_required` (402), `expired` (410), `rate_limited` (429); `openapi.json` committed.

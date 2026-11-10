# Going live: the launch checklist (Day 30)

Everything the API needs before real people and real money use it. `render.yaml` holds both the test server (`careerline-api`, `careerline-worker`, `careerline-test-db`: branch `dev`, `APP_ENV=staging`) and production (`careerline-api-production`, `careerline-worker-production`, `careerline-production-db`: branch `main`, `APP_ENV=production`), each with its own database. Syncing the Blueprint creates every service in it, so check the production plans first; the dashboard then asks for each `sync: false` value. Tick each line in the launch PR.

## 1. Services

- [ ] A **production** Postgres 16 database, separate from the test one, with daily backups and point-in-time recovery switched on, in the same region as the API (Frankfurt today).
- [ ] The **web service**: `pip install -r requirements.txt`, start `bash scripts/start.sh` (migrates, then serves), health check `/healthz`, readiness `/readyz`. At least 2 workers (`WEB_CONCURRENCY=2`).
- [ ] The **worker service**: `python -m app.worker`, same code, same environment. It sends every email, makes PDF reports and data exports, erases deleted accounts and renews subscriptions, so it must run in production (`RUN_JOBS_IN_WEB=false` on the web service).
- [ ] Deploys come from `main` only (see README, "Branches and releases"); a failed migration stops the deploy before it takes traffic.

## 2. Settings (production)

`APP_ENV=production` makes the API refuse to start, listing every reason, while one of these is wrong. Check a configuration first with `APP_ENV=production python -m app.core.launch_checks`.

- [ ] `SECRET_KEY`: random, at least 32 characters (Render: `generateValue`), shared by the web service and the worker. Changing it signs everyone out.
- [ ] `DATABASE_URL`: the production database.
- [ ] `FRONTEND_URL`: the website's https address (every link in an email points there: `/verify-email`, `/reset-password`, `/forgot-password`, `/invitations/<token>`, `/settings/privacy`, `/billing`).
- [ ] `CORS_ORIGINS`: the website's https origin(s) only.
- [ ] The website and the API on one domain (for example `careerline.ng` and `api.careerline.ng`), so the sign-in cookie works with `SESSION_COOKIE_SAMESITE=lax` (the default; `none` is refused in production).
- [ ] `PAYSTACK_SECRET_KEY`: the **live** secret key (`sk_live_…`).
- [ ] Email: `EMAIL_BACKEND=smtp` (or unset), `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_SECURITY`, a real `EMAIL_FROM` on a domain with SPF, DKIM and DMARC set up, and `SUPPORT_EMAIL`.
- [ ] `LOG_JSON=true`, `CHECK_MIGRATIONS_ON_STARTUP=true` (the default).
- [ ] `SENTRY_DSN`: the Sentry project's DSN, on the web service and the worker, so 500s and failed or dead background jobs reach the team. In Sentry, turn on server-side data scrubbing (some error URLs hold short-lived download or invitation tokens).
- [ ] `OPENAI_API_KEY`: optional (without it the plain advice and explanations are used).
- [ ] **Not** set in production: `DEMO_DATA_ON_START` (refused anyway), `TEST_MAILBOX_TOKEN` (there is no test mailbox in production). `SEED_ON_START=true` only for the first deploy and when the seed files change.
- [ ] Optional, with their defaults: `AUDIT_INVITATION_DAYS=14`, `SUBSCRIPTION_GRACE_DAYS=3`, `SUBSCRIPTION_RENEW_ATTEMPTS=3`, `CHECKOUTS_PER_HOUR=20`, `ACCOUNT_DELETION_GRACE_DAYS=30`, `DATA_EXPORT_DAYS=7`, `RETEST_COOLDOWN_DAYS=14`, `RECRUITER_SHORTLIST_LIMIT=25` (every variable is in `.env.example`).

## 3. Paystack

- [ ] Live mode on the Paystack account (business verified).
- [ ] Webhook URL (Paystack dashboard, Settings, API Keys & Webhooks): `<API base>/api/v1/payments/webhooks/paystack`.
- [ ] One real low-value card payment end to end on production (a credit pack), then refund it in Paystack.
- [ ] Plan prices in `seeds/subscription_plans.json` and pack prices in `seeds/credit_packs.json` are the real ones (they are placeholders today), loaded with `SEED_ON_START=true` once.

## 4. Data

- [ ] The real programme catalogue in `seeds/programmes.json` (a placeholder today) and the real test prices in `seeds/test_prices.json`.
- [ ] The question bank's review decisions applied (`scripts/check_questions.py --apply-reviews`, docs/question-quality.md).
- [ ] No copy of the old MySQL data with personal data on the production database; if accounts are migrated, run `scripts/sql/` repairs and check the sequences.
- [ ] The privacy notice on the website matches what the API keeps and deletes (docs/api.md, "Privacy").

## 5. The website

- [ ] Types regenerated from the final `openapi.json`; nothing reads `X-Sample-Data` or sends `X-Mock-Scenario` (gone since Day 28).
- [ ] The pages the API sends people to exist: `/verify-email`, `/reset-password`, `/forgot-password`, `/invitations/<token>`, `/settings/privacy`, `/billing` (emails) and `/payments/callback` (back from Paystack).

## 6. On launch day

- [ ] Deploy, then `GET /readyz` is `200`.
- [ ] Sign up with a real address: the confirmation email arrives and its link works.
- [ ] Take one test, open the PDF report, buy the smallest credit pack.
- [ ] Watch the logs for `startup_refused`, `job_failed` and `paystack_amount_mismatch` for the first day.

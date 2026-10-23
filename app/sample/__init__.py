"""Sample API: typed sample answers for the endpoints that are not built yet.

Every sample route lives in this package, under the real /api/v1 path and envelope, so the
frontend can build against the final contract today. When a feature is built for real, its
route moves to app/api/routes, keeps the same response model (app/schemas), and the sample
route is deleted. Sample routes are switched on by settings.sample_api_enabled (off in
production unless SAMPLE_API_ENABLED says otherwise), and every answer carries the header
X-Sample-Data: true. See docs/api.md.
"""

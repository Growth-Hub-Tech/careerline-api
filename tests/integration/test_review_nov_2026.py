"""Review, November 2026: tests for the bugs found in the bug hunt.

Each test states the correct behaviour. Run against the code before the fix, they fail; the
fix in the same commit makes them pass.
"""

from app.core.config import settings
from tests.integration.conftest import take_test

API = settings.API_PREFIX


async def test_out_of_range_paging_on_my_attempts_is_refused_not_a_server_error(client, learner):
    # a limit outside 1-100 or a negative offset is a bad request (422 from the paging check)
    for query in ("limit=-1", "offset=-1", "limit=0", "limit=101"):
        response = await client.get(f"{API}/attempts/me?{query}", headers=learner["headers"])
        assert response.status_code == 422, (query, response.status_code, response.text)


async def test_attempt_history_total_is_the_whole_count_not_the_page(client, learner, skill):
    for _ in range(2):
        await take_test(client, learner["headers"], skill)
    page = await client.get(f"{API}/attempts/me?limit=1", headers=learner["headers"])
    body = page.json()["data"]
    assert len(body["attempts"]) == 1
    assert body["total"] == 2, body["total"]

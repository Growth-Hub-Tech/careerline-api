"""Open bugs, written as tests of the CORRECT behaviour and marked xfail(strict=True).

Today each one fails, so pytest shows "xfailed" and the run stays green. When a later change
fixes the bug, the test passes, pytest reports "XPASS(strict)" and the run turns red: that is
the reminder to delete the xfail mark (and move the test next to its friends) so the fix stays
locked in.
"""

# No open bugs right now. (Day 5 fixed the last one: submit no longer waits for the AI; that
# test now lives in test_ai_recommendations.py.)

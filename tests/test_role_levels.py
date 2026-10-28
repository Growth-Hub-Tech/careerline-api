"""Day 8: the level a role needs in each skill at each job title (no database)."""

import pytest

from app.services.roles_service import expected_level_for_title


@pytest.mark.parametrize(
    ("target_at_mid", "title_level", "expected"),
    [
        ("MID", "BEGINNER", "BEGINNER"),  # main skill, intern
        ("MID", "JUNIOR", "JUNIOR"),
        ("MID", "MID", "MID"),
        ("MID", "ADVANCED", "ADVANCED"),  # senior and lead
        ("JUNIOR", "BEGINNER", "BEGINNER"),  # supporting skill: never below BEGINNER
        ("JUNIOR", "JUNIOR", "BEGINNER"),
        ("JUNIOR", "MID", "JUNIOR"),
        ("JUNIOR", "ADVANCED", "MID"),
        ("ADVANCED", "ADVANCED", "ADVANCED"),  # never above ADVANCED
    ],
)
def test_a_role_skill_moves_with_the_title(target_at_mid, title_level, expected):
    assert expected_level_for_title(target_at_mid, title_level) == expected

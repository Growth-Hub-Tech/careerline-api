"""Question quality (Day 8): what is wrong with a question, and may it be served?

One check for the whole bank, used by the seed loader (which stores each question's status
and issues in the database) and by scripts/check_questions.py (the report and the experts'
review file). It replaces the length-only scripts/check_option_bias.py.

Each issue is either BLOCK (the question is not served until it is fixed in the seed files,
or an expert approves it where approval is allowed) or REVIEW (served, but listed for the
experts). The length check is the old option-bias check: in a 4-option question the correct
answer should be the longest about a quarter of the time; when it is the single longest AND
clearly longer than the average wrong option, a learner can pick it without knowing anything.

Statuses:
- ACTIVE: served in tests
- NEEDS_REVIEW: has a BLOCK issue; not served
- RETIRED: an expert rejected it; not served

A skill can be tested only when every level has at least MIN_ACTIVE_QUESTIONS_PER_LEVEL
active questions (skill_readiness).
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from app.models.models import QuestionStatus

__all__ = [
    "Issue",
    "Option",
    "QuestionIn",
    "QuestionStatus",
    "Severity",
    "Thresholds",
    "check_bank",
    "check_question",
    "decide_status",
    "skill_readiness",
]

LEVELS = ("BEGINNER", "JUNIOR", "MID", "ADVANCED")


class Severity(StrEnum):
    BLOCK = "block"
    REVIEW = "review"


# What an expert may write in seeds/question_reviews.json
DECISIONS = ("approved", "rejected")

# Issues an expert approval can overrule (a judgement call). The others mean the question is
# broken and must be fixed in the seed file.
APPROVABLE = frozenset({"length_giveaway", "all_none_of_the_above", "not_four_options"})

ISSUE_TEXT = {
    "no_single_correct": "must have exactly one correct option",
    "too_few_options": "needs at least 3 options",
    "empty_option": "has an empty option",
    "duplicate_option": "has two options with the same text",
    "duplicate_question": "the same question already exists in this skill",
    "length_giveaway": "the correct option is the longest by far, so it gives itself away",
    "all_none_of_the_above": 'uses "all/none of the above"',
    "not_four_options": "does not have 4 options",
}

_ABOVE = re.compile(r"\b(all|none|both) of (the )?(above|these|the options)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Option:
    text: str
    is_correct: bool


@dataclass(frozen=True)
class QuestionIn:
    question_id: int
    skill_id: int
    text: str
    options: tuple[Option, ...]


@dataclass(frozen=True)
class Issue:
    code: str
    severity: Severity
    detail: str


@dataclass(frozen=True)
class Thresholds:
    # Correct option is the single longest and at least this many times the average wrong one
    review_ratio: float = 1.3  # -> REVIEW (the old check_option_bias.py limit)
    block_ratio: float = 2.0  # -> BLOCK


def _issue(code: str, severity: Severity, extra: str = "") -> Issue:
    return Issue(code, severity, ISSUE_TEXT[code] + (f" ({extra})" if extra else ""))


def length_ratio(question: QuestionIn) -> tuple[bool, float]:
    """(is the correct option the single longest?, its length / the average wrong length)"""
    correct = [len(o.text.strip()) for o in question.options if o.is_correct]
    wrong = [len(o.text.strip()) for o in question.options if not o.is_correct]
    if len(correct) != 1 or not wrong:
        return False, 0.0
    average = sum(wrong) / len(wrong)
    ratio = correct[0] / average if average else float("inf")
    return correct[0] > max(wrong), ratio


def check_question(question: QuestionIn, limits: Thresholds = Thresholds()) -> list[Issue]:
    """Everything wrong with one question on its own (duplicates need the bank: check_bank)."""
    issues: list[Issue] = []
    texts = [o.text.strip() for o in question.options]
    if sum(o.is_correct for o in question.options) != 1:
        issues.append(_issue("no_single_correct", Severity.BLOCK))
    if len(texts) < 3:
        issues.append(_issue("too_few_options", Severity.BLOCK))
    if any(not t for t in texts):
        issues.append(_issue("empty_option", Severity.BLOCK))
    normalised = [" ".join(t.lower().split()) for t in texts if t]
    if len(set(normalised)) != len(normalised):
        issues.append(_issue("duplicate_option", Severity.BLOCK))
    longest, ratio = length_ratio(question)
    if longest and ratio >= limits.block_ratio:
        issues.append(_issue("length_giveaway", Severity.BLOCK, f"{ratio:.1f}x"))
    elif longest and ratio >= limits.review_ratio:
        issues.append(_issue("length_giveaway", Severity.REVIEW, f"{ratio:.1f}x"))
    if any(_ABOVE.search(t) for t in texts):
        issues.append(_issue("all_none_of_the_above", Severity.REVIEW))
    if len(texts) >= 3 and len(texts) != 4:
        issues.append(_issue("not_four_options", Severity.REVIEW))
    return issues


def check_bank(
    questions: Iterable[QuestionIn], limits: Thresholds = Thresholds()
) -> dict[int, list[Issue]]:
    """check_question for every question, plus: the same text twice in one skill blocks every
    copy but the first (lowest question_id)."""
    result: dict[int, list[Issue]] = {}
    first_seen: dict[tuple[int, str], int] = {}
    for question in sorted(questions, key=lambda item: item.question_id):
        issues = check_question(question, limits)
        key = (question.skill_id, " ".join(question.text.lower().split()))
        if key in first_seen:
            issues.append(
                _issue("duplicate_question", Severity.BLOCK, f"question {first_seen[key]}")
            )
        else:
            first_seen[key] = question.question_id
        result[question.question_id] = issues
    return result


def decide_status(issues: list[Issue], decision: str | None) -> QuestionStatus:
    """The status a question gets from its issues and the experts' decision (if any)."""
    if decision is not None and decision not in DECISIONS:
        raise ValueError(f"decision must be one of {DECISIONS}, not {decision!r}")
    if decision == "rejected":
        return QuestionStatus.RETIRED
    blocking = [i for i in issues if i.severity == Severity.BLOCK]
    if decision == "approved":
        blocking = [i for i in blocking if i.code not in APPROVABLE]
    return QuestionStatus.NEEDS_REVIEW if blocking else QuestionStatus.ACTIVE


def skill_readiness(active_by_level: dict[str, int], minimum: int) -> tuple[bool, dict[str, int]]:
    """(can the skill be tested?, how many active questions each short level still needs)"""
    short = {
        level: minimum - active_by_level.get(level, 0)
        for level in LEVELS
        if active_by_level.get(level, 0) < minimum
    }
    return not short, short

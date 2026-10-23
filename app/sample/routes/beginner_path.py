from fastapi import APIRouter, Depends

from app.core.exceptions import BadRequestError
from app.core.responses import ApiResponse
from app.sample.core import SampleRoute, Scenario, sample, sample_route, sample_user, scenario
from app.sample.data import NOW, programme_summary
from app.schemas.beginner_path import (
    BeginnerPath,
    CareerPathRecommendation,
    IntakeOption,
    IntakeQuestion,
    IntakeQuestionnaire,
    IntakeSubmission,
)

router = APIRouter(
    prefix="/beginner-path",
    tags=["Sample: Beginner path"],
    route_class=SampleRoute,
    dependencies=[Depends(scenario)],
)

INTAKE_VERSION = "2026-10"


def _options(*pairs: tuple[str, str]) -> list[IntakeOption]:
    return [IntakeOption(value=value, label=label) for value, label in pairs]


QUESTIONNAIRE = IntakeQuestionnaire(
    version=INTAKE_VERSION,
    questions=[
        IntakeQuestion(
            question_id="work_style",
            section="personality",
            text="Which sounds most like you?",
            kind="single_choice",
            options=_options(
                ("visual", "I like making things look and feel right"),
                ("logic", "I like solving puzzles and making systems work"),
                ("data", "I like finding patterns in numbers"),
                ("people", "I like explaining and persuading"),
            ),
        ),
        IntakeQuestion(
            question_id="goal",
            section="goals",
            text="What do you want in the next 12 months?",
            kind="multi_choice",
            options=_options(
                ("first_job", "My first tech job"),
                ("switch", "Switch from my current career"),
                ("freelance", "Freelance income"),
                ("promotion", "Grow in my current company"),
            ),
        ),
        IntakeQuestion(
            question_id="weekly_hours",
            section="time",
            text="How many hours a week can you study?",
            kind="single_choice",
            options=_options(
                ("lt5", "Less than 5"),
                ("5_10", "5 to 10"),
                ("10_20", "10 to 20"),
                ("gt20", "More than 20"),
            ),
        ),
        IntakeQuestion(
            question_id="budget",
            section="finances",
            text="How much can you spend on training?",
            kind="single_choice",
            options=_options(
                ("free_only", "Free options only"),
                ("under_50k", "Under NGN 50,000"),
                ("50k_to_200k", "NGN 50,000 to 200,000"),
                ("over_200k", "Over NGN 200,000"),
            ),
        ),
    ],
)
QUESTION_IDS = {question.question_id for question in QUESTIONNAIRE.questions}

RECOMMENDATIONS = [
    CareerPathRecommendation(
        rank=1,
        role_id=101,
        title="Frontend Developer",
        match_score=86,
        reasons=[
            "You enjoy making things look and feel right",
            "10 hours a week is enough for a 12-week bootcamp",
            "Entry-level roles are common in Lagos and remote",
        ],
        starting_test_id=201,
        programme=programme_summary(301),
    ),
    CareerPathRecommendation(
        rank=2,
        role_id=103,
        title="Data Analyst",
        match_score=71,
        reasons=["You like finding patterns", "SQL is quick to start and in demand"],
        starting_test_id=203,
        programme=programme_summary(303),
    ),
    CareerPathRecommendation(
        rank=3,
        role_id=102,
        title="Backend Developer",
        match_score=58,
        reasons=["You like making systems work", "Takes longer to job-ready than frontend"],
        starting_test_id=202,
        programme=programme_summary(302),
    ),
]


# INTAKE QUESTIONS: personality, goals, time and money (PRD 4.2). Public.
@router.get(
    "/intake", response_model=ApiResponse[IntakeQuestionnaire], openapi_extra=sample_route()
)
async def get_intake_questionnaire():
    return sample(QUESTIONNAIRE)


# SUBMIT THE INTAKE: answers come back as ranked career paths, each with reasons and a programme
@router.post(
    "/intake",
    status_code=201,
    response_model=ApiResponse[BeginnerPath],
    openapi_extra=sample_route(),
)
async def submit_intake(data: IntakeSubmission, learner_id: int = Depends(sample_user)):
    unknown = sorted({answer.question_id for answer in data.answers} - QUESTION_IDS)
    if unknown:
        raise BadRequestError(f"Unknown intake question ids: {', '.join(unknown)}")
    return sample(BeginnerPath(intake_id=7001, submitted_at=NOW, recommendations=RECOMMENDATIONS))


# MY CAREER PATHS: the latest intake's recommendations ("empty" = no intake yet)
@router.get(
    "/recommendations",
    response_model=ApiResponse[BeginnerPath],
    openapi_extra=sample_route("empty"),
)
async def get_my_career_paths(
    sc: Scenario = Depends(scenario), learner_id: int = Depends(sample_user)
):
    return sample(
        BeginnerPath(
            intake_id=7001, submitted_at=NOW, recommendations=[] if sc.empty else RECOMMENDATIONS
        )
    )

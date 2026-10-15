from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.repositories.attempt_repo import (
    create_attempt, get_level_id_by_name,
    get_questions_for_attempt, get_options_for_question,
    record_attempt_questions
)

#Validate declared level
VALID_LEVELS = ["BEGINNER", "JUNIOR", "MID", "ADVANCED"]

#START A TEST ATTEMPT
async def start_attempt(db: AsyncSession, learner_id: int, skill_id: int, declared_level: str):

    #Validate declared level
    declared_level = declared_level.upper()
    if declared_level not in VALID_LEVELS:
        raise ValueError(f"Invalid level: {declared_level}. Must be one of {VALID_LEVELS}")

    #Get level ID from database
    level_id = await get_level_id_by_name(db, declared_level)
    if not level_id:
        raise ValueError(f"Level {declared_level} not found in database")

    #Create the attempt
    attempt_id = await create_attempt(db, learner_id, skill_id, level_id)

    #Pick this attempt's questions (seeded by attempt_id, balanced by subskill,
    #least-seen first so retakes get different questions when the pool allows it)
    questions = await get_questions_for_attempt(
        db, skill_id, declared_level,
        attempt_id=attempt_id, learner_id=learner_id, count=settings.QUESTIONS_PER_LEVEL
    )
    print(f"Fetched {len(questions)} questions for skill_id={skill_id} at {declared_level} level")

    #Store the served questions so submit can check the answers against them
    await record_attempt_questions(db, attempt_id, [q.question_id for q in questions])

    #Fetch options for each question
    questions_with_options = []
    for question in questions:
        options = await get_options_for_question(db, question.question_id, attempt_id)
        questions_with_options.append({
            "question_id": question.question_id,
            "question_text": question.question_text,
            "difficulty_level": question.difficulty_level.value,
            "subskill_id": question.subskill_id,
            "options": options
        })

    #Return attempt details and questions
    return {
        "attempt_id": attempt_id,
        "learner_id": learner_id,
        "skill_id": skill_id,
        "declared_level": declared_level,
        "total_questions": len(questions_with_options),
        "questions": questions_with_options
    }
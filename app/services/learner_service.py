from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.models import BehaviouralQuestion, Skill
from app.repositories.learner_repo import create_learner

logger = get_logger(__name__)

#REGISTER A NEW LEARNER OR FETCH DETAILS IF ALREADY EXISTS
async def register_learner(db: AsyncSession, full_name: str, email: str, phone: str):
    #create_learner handles duplicate check internally
    learner_id = await create_learner(db, full_name, email, phone)
    return learner_id


#GET BEHAVIOURAL QUESTIONS FOR A SKILL
async def get_behavioural_questions(db: AsyncSession, skill_id: int):
    #Fetch skill name
    skill_result = await db.execute(
        select(Skill).where(Skill.skill_id == skill_id)
    )
    skill = skill_result.scalar_one_or_none()
    if not skill:
        return None

    #Fetch 5 general questions that apply to everyone
    general_result = await db.execute(
        select(BehaviouralQuestion)
        .where(
            BehaviouralQuestion.question_type == "GENERAL",
            BehaviouralQuestion.is_active.is_(True)
        )
        .limit(5)
    )
    general_questions = general_result.scalars().all()

    #Fetch 5 skill-specific questions for this skill
    skill_result_q = await db.execute(
        select(BehaviouralQuestion)
        .where(
            BehaviouralQuestion.skill_id == skill_id,
            BehaviouralQuestion.question_type == "SKILL_SPECIFIC",
            BehaviouralQuestion.is_active.is_(True)
        )
        .limit(5)
    )
    skill_questions = skill_result_q.scalars().all()

    #Combine both lists
    all_questions = list(general_questions) + list(skill_questions)

    return {
        "skill_id": skill_id,
        "skill_name": skill.skill_name,
        "total_questions": len(all_questions),
        "questions": [
            {
                "question_id": q.question_id,
                "question_text": q.question_text,
                "question_type": q.question_type.value
            }
            for q in all_questions
        ]
    }


#SUBMIT BEHAVIOURAL ANSWERS
async def submit_behavioural_answers(db: AsyncSession, learner_id: int, attempt_id: int, answers: list):
    from app.models.models import LearnerProfile

    #Save each answer
    for answer in answers:
        profile = LearnerProfile(
            learner_id=learner_id,
            attempt_id=attempt_id,
            question_id=answer["question_id"],
            answer_text=answer["answer_text"]
        )
        db.add(profile)

    #await db.commit()
    logger.info("behavioural_answers_saved", learner_id=learner_id, attempt_id=attempt_id, count=len(answers))
    return {
        "learner_id": learner_id,
        "attempt_id": attempt_id,
        "total_answers": len(answers),
        "message": "Behavioural answers saved successfully"
    }

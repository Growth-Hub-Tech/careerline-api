from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.scoring_repo import (
    save_answer, get_answers_for_attempt,
    update_attempt_score, save_difficulty_stats,
    save_subskill_stats, assign_learner_level
)
from app.repositories.recommendation_repo import (
    get_subskill_scores, get_skill_name_for_attempt,
    get_level_name_for_attempt, save_recommendations
)
from app.core.config import settings
from app.models.models import AttemptStatus
from openai_engine import get_ai_benchmark

#Suggests a level for the learner if they fail the test.
#For example, if a learner declares themselves as "JUNIOR" but fails, we suggest "BEGINNER".
#If they declare "MID" and fail, we suggest "JUNIOR", and so on.
#If they declare "BEGINNER" and fail, we don't suggest anything since it's the lowest level.
LEVEL_SUGGESTION = {
    "JUNIOR": "BEGINNER",
    "MID": "JUNIOR",
    "ADVANCED": "MID",
    "BEGINNER": None
}


#SUBMIT AND SCORE AN ATTEMPT
async def submit_and_score(db: AsyncSession, attempt_id: int, learner_id: int, answers: list):

    #Save all answers
    for answer in answers:
        await save_answer(
            db,
            attempt_id,
            answer["question_id"],
            answer["selected_option_id"]
        )
    print(f"All answers saved for attempt_id={attempt_id}")

    #Fetch all answers and calculate score
    answer_rows = await get_answers_for_attempt(db, attempt_id)

    correct = 0
    level_stats = {}
    subskill_stats = {}

    for row in answer_rows:
        level = row.difficulty_level.value
        subskill = row.subskill_id

        if level not in level_stats:
            level_stats[level] = {"correct": 0, "total": 0}
        if subskill not in subskill_stats:
            subskill_stats[subskill] = {"correct": 0, "total": 0}

        level_stats[level]["total"] += 1
        subskill_stats[subskill]["total"] += 1

        if row.is_correct:
            correct += 1
            level_stats[level]["correct"] += 1
            subskill_stats[subskill]["correct"] += 1

    #Calculate percentage out of 25
    percentage = round((correct / settings.QUESTIONS_PER_LEVEL) * 100, 2)
    passed = percentage >= settings.PASS_THRESHOLD

    #Get declared level name
    from app.repositories.scoring_repo import get_level_from_score
    from app.repositories.recommendation_repo import get_level_name_for_attempt
    declared_level = await get_level_name_for_attempt(db, attempt_id)

    #Determine pass/fail and level
    if passed:
        status = AttemptStatus.PASSED
        confirmed_level = declared_level
        level_suggestion = None
        from app.repositories.scoring_repo import get_level_from_score
        level_id = await get_level_from_score(db, percentage)
    else:
        status = AttemptStatus.FAILED
        confirmed_level = None
        level_suggestion = LEVEL_SUGGESTION.get(declared_level, None)
        level_id = None

    #Update attempt record
    await update_attempt_score(db, attempt_id, percentage, level_id, status)
    print(f"Scoring complete: {percentage}%  Status: {status.value}")

    #Save analytics
    await save_difficulty_stats(db, attempt_id, level_stats)
    await save_subskill_stats(db, attempt_id, subskill_stats)

    #Assign level if passed
    if passed and level_id:
        await assign_learner_level(db, learner_id, None, attempt_id, level_id)
        print(f"Level assigned: {confirmed_level}")

    #Return result
    return {
        "score": correct,
        "total_possible": settings.QUESTIONS_PER_LEVEL,
        "percentage": percentage,
        "declared_level": declared_level,
        "status": status.value.lower(),  #API keeps returning "passed" / "failed"
        "confirmed_level": confirmed_level,
        "level_suggestion": level_suggestion,
        "level_id": level_id,
        "level_breakdown": level_stats,
        "subskill_breakdown": subskill_stats
    }


#GENERATE RECOMMENDATIONS AFTER SCORING
async def generate_recommendations(db: AsyncSession, attempt_id: int, learner_id: int):

    #Fetch subskill scores
    subskill_scores = await get_subskill_scores(db, attempt_id)
    if not subskill_scores:
        return None

    #Fetch skill name and level name
    skill_name = await get_skill_name_for_attempt(db, attempt_id)
    level_name = await get_level_name_for_attempt(db, attempt_id)

    #Identify weak subskills below threshold
    weak_subskills = [
        s for s in subskill_scores
        if float(s.percentage_score) < settings.WEAK_THRESHOLD
    ]

    if not weak_subskills:
        print("No weak subskills found — learner is strong across all areas")
        return {"message": "Great job! No weak areas found.", "recommendations": []}

    #Sort by lowest score first. most urgent first
    weak_subskills = sorted(weak_subskills, key=lambda x: float(x.percentage_score))

    #Generate recommendations
    recommendations = []
    for priority, subskill in enumerate(weak_subskills, start=1):
        score = float(subskill.percentage_score)
        name = subskill.subskill_name

        #Call OpenAI for enriched recommendation
        print(f"Calling OpenAI for {name} (score: {score}%)...")
        action = get_ai_benchmark(skill_name, name, level_name, score)

        recommendations.append({
            "priority": priority,
            "subskill_id": subskill.subskill_id,
            "subskill_name": name,
            "percentage_score": score,
            "recommendation": action
        })

    #Save recommendations to database
    await save_recommendations(db, attempt_id, learner_id, recommendations)
    print(f"{len(recommendations)} recommendations saved for attempt_id={attempt_id}")

    return {
        "total_weak_areas": len(recommendations),
        "recommendations": recommendations
    }
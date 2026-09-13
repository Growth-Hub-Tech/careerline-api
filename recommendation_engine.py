#MAKING RECOMMENDATION FOR LEANER BASED ON THE WEAKNESS
from database import fetch_all, fetch_one, execute, get_connection
from openai_engine import get_ai_benchmark

#WEAKNESS THERESHOLD (ANY SUBSKILL BELOW 60%, TO BE CONSIDERED AS WEAK)
WEAK_THERESHOLD = 60

#GENERATING RECOMMENDATIONS BASED ON THE WEAKNESS
def generate_recommendations(attempt_id, learner_id):

    #Fetch the learner's subskill performance for an attempt
    subskill_scores = fetch_all("""
        SELECT 
            ass.subskill_id,
            sub.subskill_name,
            ass.total_questions,
            ass.correct_answers,
            ass.percentage_score
        FROM attempt_subskill_score ass
        JOIN subskills sub ON ass.subskill_id = sub.subskill_id
        WHERE ass.attempt_id = %s
    """, (attempt_id,))

    if not subskill_scores:
        print(f"No subskill scores found for attempt_id={attempt_id}")
        return None

    #Fetch skill name for this attempt
    skill_data = fetch_one("""
        SELECT s.skill_name 
        FROM test_attempt ta
        JOIN skills s ON ta.skill_id = s.skill_id
        WHERE ta.attempt_id = %s
    """, (attempt_id,))
    skill_name = skill_data["skill_name"] if skill_data else "Tech"

    #Fetch learner's current level for this attempt
    level_data = fetch_one("""
        SELECT pl.level_name
        FROM test_attempt ta
        JOIN learner_level ll ON ta.learner_id = ll.learner_id AND ta.skill_id = ll.skill_id
        JOIN proficiency_level pl ON ll.level_id = pl.level_id
        WHERE ta.attempt_id = %s
    """, (attempt_id,))
    level_name = level_data["level_name"] if level_data else "JUNIOR"

    #Identifying weak subskills below 60
    weak_subskills = [
        s for s in subskill_scores
        if s["percentage_score"] < WEAK_THERESHOLD
    ]

    if not weak_subskills:
        print(f"No weak subskills found. This learner is strong across all areas")
        return {
            "attempt_id": attempt_id,
            "learner_id": learner_id,
            "weak_subskills": [],
            "message": "Great job! No weak areas found."
        }

    #Sort weak subskills from lowest score to highest
    weak_subskills = sorted(weak_subskills, key=lambda x: x["percentage_score"])

    #Save recommendations to DB and build pathway
    conn = get_connection()
    recommendations = []

    try:
        with conn.cursor() as cursor:

            #Clear old recommendations for this attempt first
            cursor.execute(
                "DELETE FROM subskill_recommendation WHERE attempt_id = %s",
                (attempt_id,)
            )

            for priority, subskill in enumerate(weak_subskills, start=1):

                score = subskill["percentage_score"]
                name = subskill["subskill_name"]

                #Calling OpenAI API to get recommendation for this weak subskill
                print(f"Calling OpenAI for {name} (score: {score}%)...")
                action = get_ai_benchmark(skill_name, name, level_name, score)

                #Insert recommendation into DB
                cursor.execute("""
                    INSERT INTO subskill_recommendation 
                    (attempt_id, learner_id, priority, percentage_score, subskill_id, recommendation_text)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (
                    attempt_id,
                    learner_id,
                    priority,
                    score,
                    subskill["subskill_id"],
                    action
                ))

                #Add to recommendations list for return
                recommendations.append({
                    "priority": priority,
                    "subskill_id": subskill["subskill_id"],
                    "subskill_name": name,
                    "percentage_score": score,
                    "recommendation": action
                })

        conn.commit()
        print(f"{len(recommendations)} recommendations saved for attempt_id={attempt_id}")

    except Exception as e:
        conn.rollback()
        print(f"Failed to save recommendations: {e}")
        raise

    finally:
        conn.close()

    return {
        "attempt_id": attempt_id,
        "learner_id": learner_id,
        "total_weak_areas": len(recommendations),
        "recommendations": recommendations
    }

#AFTER RECOMENDAION, GET LEARNING PATHWAY
def get_learning_pathway(learner_id, skill_id):

    #Fetch learner details
    learner = fetch_one(
        "SELECT full_name FROM learner WHERE learner_id = %s",
        (learner_id,)
    )

    #Fetch skill name
    skill = fetch_one(
        "SELECT skill_name FROM skills WHERE skill_id = %s",
        (skill_id,)
    )

    #Fetch learner's current level for the skill fetched
    learner_level = fetch_one("""
        SELECT pl.level_name
        FROM learner_level ll
        JOIN proficiency_level pl ON ll.level_id = pl.level_id
        WHERE ll.learner_id = %s AND ll.skill_id = %s
    """, (learner_id, skill_id))

    #Fetch the latest attempt_id for this learner and skill
    latest_attempt = fetch_one("""
        SELECT attempt_id FROM test_attempt
        WHERE learner_id = %s AND skill_id = %s
        ORDER BY start_time DESC
        LIMIT 1
    """, (learner_id, skill_id))

    if not latest_attempt:
        print(f"No attempt found for learner_id={learner_id}, skill_id={skill_id}")
        return None

    attempt_id = latest_attempt["attempt_id"]

    #Fetch saved recommendations for this attempt in priority order
    recommendations = fetch_all("""
        SELECT 
            sr.priority,
            sr.percentage_score,
            sr.recommendation_text,
            sub.subskill_name
        FROM subskill_recommendation sr
        JOIN subskills sub ON sr.subskill_id = sub.subskill_id
        WHERE sr.attempt_id = %s
        ORDER BY sr.priority ASC
    """, (attempt_id,))

    return {
        "learner_name": learner["full_name"],
        "skill_name": skill["skill_name"],
        "current_level": learner_level["level_name"] if learner_level else "UNKNOWN",
        "attempt_id": attempt_id,
        "learning_pathway": recommendations
    }

#TESTING
if __name__ == "__main__":

    #Generate recommendations for learner 6, attempt 12
    print("\n--- Generating Recommendations ---")
    result = generate_recommendations(attempt_id=12, learner_id=6)
    print(f"Total weak areas: {result['total_weak_areas']}")

    #Get and display the full learning pathway
    print("\n--- Fetching Learning Pathway ---")
    pathway = get_learning_pathway(learner_id=6, skill_id=1)

    print("\n========== LEARNING PATHWAY ==========")
    print(f"Learner        : {pathway['learner_name']}")
    print(f"Skill          : {pathway['skill_name']}")
    print(f"Current Level  : {pathway['current_level']}")
    print(f"\nYour Learning Pathway ({len(pathway['learning_pathway'])} areas to focus on):\n")
    for item in pathway["learning_pathway"]:
        print(f"  Priority {item['priority']}: {item['subskill_name']},Score: {item['percentage_score']}%. {item['recommendation_text']}")
    print(f"\nGoal: Improve these areas to reach the next level")
    print("=======================================")
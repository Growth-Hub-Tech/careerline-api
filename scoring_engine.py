from database import fetch_all, fetch_one, get_connection

#PASS THRESHOLD — learner must score 60% or above to be confirmed at declared level
PASS_THRESHOLD = 60

#LEVEL SUGGESTION MAP — if learner fails, suggest the level below
LEVEL_SUGGESTION = {
    "JUNIOR": "BEGINNER",
    "MID": "JUNIOR",
    "ADVANCED": "MID",
    "BEGINNER": None  #No lower level to suggest
}


#SAVE DIFFICULTY ANALYTICS
def save_difficulty_stats(attempt_id, level_stats):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            #Clear old data first to avoid duplicate key errors on re-runs
            cursor.execute(
                "DELETE FROM attempt_difficulty_score WHERE attempt_id = %s",
                (attempt_id,)
            )
            query = """
                INSERT INTO attempt_difficulty_score
                (attempt_id, difficulty_level, total_questions, correct_answers, percentage_score)
                VALUES (%s, %s, %s, %s, %s)
            """
            for level, data in level_stats.items():
                total = data["total"]
                correct = data["correct"]
                if total == 0:
                    continue
                percentage = round((correct / total * 100), 2)
                cursor.execute(query, (attempt_id, level, total, correct, percentage))
        conn.commit()
        print(f"Difficulty stats saved for attempt_id={attempt_id}")
    except Exception as e:
        conn.rollback()
        print(f"Failed to save difficulty stats: {e}")
        raise
    finally:
        conn.close()


#SAVE SUBSKILL ANALYTICS
def save_subskill_stats(attempt_id, subskill_stats):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            #Clear old data first
            cursor.execute(
                "DELETE FROM attempt_subskill_score WHERE attempt_id = %s",
                (attempt_id,)
            )
            query = """
                INSERT INTO attempt_subskill_score
                (attempt_id, subskill_id, total_questions, correct_answers, percentage_score)
                VALUES (%s, %s, %s, %s, %s)
            """
            for subskill_id, data in subskill_stats.items():
                total = data["total"]
                correct = data["correct"]
                if total == 0:
                    continue
                percentage = round((correct / total * 100), 2)
                cursor.execute(query, (attempt_id, subskill_id, total, correct, percentage))
        conn.commit()
        print(f"Subskill stats saved for attempt_id={attempt_id}")
    except Exception as e:
        conn.rollback()
        print(f"Failed to save subskill stats: {e}")
        raise
    finally:
        conn.close()


#MAIN SCORING FUNCTION
def score_attempt(attempt_id):

    #Fetch the declared level for this attempt
    attempt_data = fetch_one(
        """
        SELECT pl.level_name as declared_level
        FROM test_attempt ta
        JOIN proficiency_level pl ON ta.declared_level_id = pl.level_id
        WHERE ta.attempt_id = %s
        """,
        (attempt_id,)
    )
    declared_level = attempt_data["declared_level"] if attempt_data else "BEGINNER"

    #Fetch answers with joins
    fetch_query = """
        SELECT 
            opt.is_correct,
            quest.difficulty_level,
            quest.subskill_id
        FROM learner_answer la
        JOIN options opt ON la.selected_option_id = opt.option_id
        JOIN questions quest ON la.question_id = quest.question_id
        WHERE la.attempt_id = %s
    """
    answers = fetch_all(fetch_query, (attempt_id,))

    if not answers:
        print(f"No answers found for attempt_id={attempt_id}")
        return None

    #Initialize counters
    correct = 0
    subskill_stats = {}
    level_stats = {}

    #Process answers
    for ans in answers:
        level = ans["difficulty_level"]
        subskill = ans["subskill_id"]

        if level not in level_stats:
            level_stats[level] = {"correct": 0, "total": 0}
        if subskill not in subskill_stats:
            subskill_stats[subskill] = {"correct": 0, "total": 0}

        level_stats[level]["total"] += 1
        subskill_stats[subskill]["total"] += 1

        if ans["is_correct"]:
            correct += 1
            level_stats[level]["correct"] += 1
            subskill_stats[subskill]["correct"] += 1

    #Calculate percentage out of 25 questions
    total_answered = len(answers)
    percentage = round((correct / 25) * 100, 2)

    #Determine pass or fail based on threshold
    passed = percentage >= PASS_THRESHOLD

    #If passed — confirmed at declared level
    #If failed — no level assigned, suggest level below
    if passed:
        status = "PASSED"
        confirmed_level = declared_level
        level_suggestion = None

        #Fetch level_id for confirmed level
        level_data = fetch_one(
            "SELECT level_id FROM proficiency_level WHERE level_name = %s",
            (declared_level,)
        )
        level_id = level_data["level_id"] if level_data else None

    else:
        status = "FAILED"
        confirmed_level = None
        level_suggestion = LEVEL_SUGGESTION.get(declared_level, None)
        level_id = None

    #Update test_attempt record
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE test_attempt 
                SET overall_percentage = %s,
                    assigned_level_id = %s,
                    attempt_status = 'COMPLETED',
                    end_time = NOW()
                WHERE attempt_id = %s
            """, (percentage, level_id, attempt_id))
        conn.commit()
        print(f"test_attempt updated for attempt_id={attempt_id}")
    except Exception as e:
        conn.rollback()
        print(f"Failed to update test_attempt: {e}")
        raise
    finally:
        conn.close()

    #Save analytics
    save_difficulty_stats(attempt_id, level_stats)
    save_subskill_stats(attempt_id, subskill_stats)

    #Return result
    return {
        "score": correct,
        "total_answered": total_answered,
        "total_possible": 25,
        "percentage": percentage,
        "declared_level": declared_level,
        "passed": passed,
        "status": status,
        "confirmed_level": confirmed_level,
        "level_suggestion": level_suggestion,
        "level_id": level_id,
        "level_breakdown": level_stats,
        "subskill_breakdown": subskill_stats
    }


#TEST
if __name__ == "__main__":
    attempt_id = 1
    result = score_attempt(attempt_id)
    print("\nFINAL RESULT:", result)
from database import fetch_all, fetch_one, get_connection


# SAVE DIFFICULTY ANALYTICS
def save_difficulty_stats(attempt_id, level_stats):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            # Clear old data first to avoid duplicate key errors on re-runs
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

                # Skip levels with no questions — avoid inserting empty rows
                if total == 0:
                    continue

                percentage = round((correct / total * 100), 2)

                cursor.execute(query, (
                    attempt_id,
                    level,
                    total,
                    correct,
                    percentage
                ))

        conn.commit()
        print(f"[OK] Difficulty stats saved for attempt_id={attempt_id}")

    except Exception as e:
        conn.rollback()
        print(f"[ERROR] Failed to save difficulty stats: {e}")
        raise  # Re-raise so the caller knows something went wrong

    finally:
        conn.close()


# SAVE SUBSKILL ANALYTICS
def save_subskill_stats(attempt_id, subskill_stats):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            # Clear old data first
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

                cursor.execute(query, (
                    attempt_id,
                    subskill_id,
                    total,
                    correct,
                    percentage
                ))

        conn.commit()
        print(f"[OK] Subskill stats saved for attempt_id={attempt_id}")

    except Exception as e:
        conn.rollback()
        print(f"[ERROR] Failed to save subskill stats: {e}")
        raise

    finally:
        conn.close()


# MAIN SCORING FUNCTION
def score_attempt(attempt_id):

    # STEP 1: Get difficulty levels dynamically
    levels_data = fetch_all(
        "SELECT DISTINCT difficulty_level FROM questions"
    )
    level_stats = {
        lvl["difficulty_level"]: {"correct": 0, "total": 0}
        for lvl in levels_data
    }

    # STEP 2: Fetch answers with joins
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
        print(f"[WARN] No answers found for attempt_id={attempt_id}")
        return None

    # STEP 3: Initialize counters
    correct = 0
    subskill_stats = {}

    # STEP 4: Process answers
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

    # STEP 5: Calculate overall percentage
    total = len(answers)
    total_answered = len(answers)
    percentage = round(correct, 2)

    # STEP 6: Get proficiency level from DB
    level_data = fetch_one("""
        SELECT level_id 
        FROM level_threshold 
        WHERE %s BETWEEN min_score AND max_score
    """, (percentage,))
    level_id = level_data["level_id"] if level_data else None

    # STEP 7: Update test_attempt record
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
        print(f"[OK] test_attempt updated for attempt_id={attempt_id}")
    except Exception as e:
        conn.rollback()
        print(f"[ERROR] Failed to update test_attempt: {e}")
        raise
    finally:
        conn.close()

    # STEP 8: Save analytics
    save_difficulty_stats(attempt_id, level_stats)
    save_subskill_stats(attempt_id, subskill_stats)

    # STEP 9: Return result
    return {
        "score": correct,
        "total": total,
        "percentage": percentage,
        "level_id": level_id,
        "level_breakdown": level_stats,
        "subskill_breakdown": subskill_stats
    }


# TEST
if __name__ == "__main__":
    attempt_id = 1
    result = score_attempt(attempt_id)
    print("\nFINAL RESULT:", result)
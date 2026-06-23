from database import fetch_one, get_connection

def assign_level(learner_id, attempt_id, level_id):

    #Get the skill_id from the attempt
    attempt = fetch_one(
        "SELECT skill_id FROM test_attempt WHERE attempt_id = %s",
        (attempt_id,)
    )

    if not attempt:
        print(f"No attempt found with attempt_id={attempt_id}")
        return None

    skill_id = attempt["skill_id"]

    #Get level name for readable output
    level = fetch_one(
        "SELECT level_name FROM proficiency_level WHERE level_id = %s",
        (level_id,)
    )

    level_name = level["level_name"] if level else "UNKNOWN"

    #UPSERT into learner_level
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            query = """
                INSERT INTO learner_level (learner_id, skill_id, attempt_id, level_id)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    level_id = VALUES(level_id),
                    attempt_id = VALUES(attempt_id),
                    assigned_at = NOW()
            """
            cursor.execute(query, (learner_id, skill_id, attempt_id, level_id))
        conn.commit()
        print(f"Level assigned: learner={learner_id}, skill={skill_id}, level={level_name}")

    except Exception as e:
        conn.rollback()
        print(f"Failed to assign level: {e}")
        raise

    finally:
        conn.close()

    #Return confirmation
    return {
        "learner_id": learner_id,
        "skill_id": skill_id,
        "attempt_id": attempt_id,
        "level_id": level_id,
        "level_name": level_name,
        "status": "assigned"
    }


# TEST
if __name__ == "__main__":
    result = assign_level(learner_id=1, attempt_id=1, level_id=1)
    print("\nLEVEL ENGINE RESULT:", result)
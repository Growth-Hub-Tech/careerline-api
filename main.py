from database import fetch_one, fetch_all, execute, get_connection
from scoring_engine import score_attempt
from level_engine import assign_level

#LEARNER REGISTRATION
def register_learner(full_name, email, phone):
    # Check if email already exists
    existing = fetch_one("SELECT * FROM learner WHERE email = %s", (email,))
    if existing:
        print(f"Learner with email {email} already exists with ID {existing['learner_id']}")
        return existing["learner_id"]
    
    #Creating new learner
    execute("INSERT INTO learner (full_name, email, phone_number) VALUES (%s, %s, %s)", (full_name, email, phone))
    new_learner = fetch_one("SELECT learner_id FROM learner WHERE email = %s", (email,)) #Selecting the new learner to get the ID
    print(f"New learner created with ID {new_learner['learner_id']}")
    return new_learner["learner_id"]


#START TEST ATTEMPT
def start_attempt(learner_id, skill_id):
    # Create a new test attempt to get its ID
    execute("INSERT INTO test_attempt (learner_id, skill_id) VALUES (%s, %s)", (learner_id, skill_id))
    
    # Fetch the latest attempt for this learner and skill to get the ID
    attempt = fetch_one("SELECT attempt_id FROM test_attempt WHERE learner_id = %s AND skill_id = %s ORDER BY start_time DESC LIMIT 1", (learner_id, skill_id))
    attempt_id = attempt["attempt_id"] # Extract attempt_id from the fetched row
    print(f"New attempt started with ID {attempt_id}")
    
    # Fetch 25 random questions per difficulty level
    questions = []
    levels = ["BEGINNER", "JUNIOR", "MID", "ADVANCED"]
    for level in levels:
        # Fetch 25 random questions for this skill and difficulty level
        level_questions = fetch_all("""SELECT q.question_id, q.question_text, q.difficulty_level, q.subskill_id
            FROM questions q
            JOIN subskills sub ON q.subskill_id = sub.subskill_id
            WHERE sub.skill_id = %s AND q.difficulty_level = %s
            ORDER BY RAND()
            LIMIT 25""", (skill_id, level))
        questions.extend(level_questions)
    print(f"Fetched {len(questions)} questions for skill_id={skill_id}")

    # Fetch answer options for each question without revealing correct answer
    for i, question in enumerate(questions):
        options = fetch_all(
            "SELECT option_id, option_text FROM options WHERE question_id = %s",
            (question["question_id"],))
        question_dict = dict(question)          # Convert to plain dict
        question_dict["options"] = list(options) # Attach options to the plain dict
        questions[i] = question_dict             # Put the complete dict back into the list

    # Return attempt details and questions to the caller
    return {
        "attempt_id": attempt_id,
        "learner_id": learner_id,
        "skill_id": skill_id,
        "total_questions": len(questions),
        "questions": questions
    }


#SUBMIT ANSWER AND SCORE
def submit_and_score(attempt_id, learner_id, answers):

    # Saving all learner answers to the DB in one transaction
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            for answer in answers:
                question_id = answer["question_id"]
                selected_option_id = answer["selected_option_id"]

                # Checking if the selected option is correct from the options table
                option = fetch_one(
                    "SELECT is_correct FROM options WHERE option_id = %s",
                    (selected_option_id,)
                )
                is_correct = option["is_correct"] if option else False

                # Insert the learner's answer into learner_answer table
                cursor.execute(
                    """
                    INSERT INTO learner_answer (attempt_id, question_id, selected_option_id, is_correct)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (attempt_id, question_id, selected_option_id, is_correct)
                )

        # Commit all answers at once
        conn.commit()
        print(f"All answers saved for attempt_id={attempt_id}")

    except Exception as e:
        conn.rollback()
        print(f"Failed to save answers: {e}")
        raise

    finally:
        conn.close()

    # Score the attempt using the scoring engine
    score_result = score_attempt(attempt_id)
    print(f"Scoring complete: {score_result['percentage']}%")

    # Assign proficiency level using the level engine
    level_result = assign_level(
        learner_id=learner_id,
        attempt_id=attempt_id,
        level_id=score_result["level_id"]
    )
    print(f"Level assigned: {level_result['level_name']}")

    # Return the final combined result
    return {
        "learner_id": learner_id,
        "attempt_id": attempt_id,
        "score": score_result["score"],
        "total_possible": 100,
        "percentage": score_result["percentage"],
        "level": level_result["level_name"],
        "level_id": score_result["level_id"],
        "difficulty_breakdown": score_result["level_breakdown"],
        "subskill_breakdown": score_result["subskill_breakdown"]
    }


#TESTING
if __name__ == "__main__":

    # Register a learner
    learner_id = register_learner(
        full_name="Joshua Excel",
        email="joshxcel@email.com",
        phone="08012345678"
    )

    # Start a test attempt for skill 1
    attempt_data = start_attempt(learner_id=learner_id, skill_id=1)
    attempt_id = attempt_data["attempt_id"]
    questions = attempt_data["questions"]

    # Simulate answers by always picking the first option
    answers = [
        {
            "question_id": q["question_id"],
            "selected_option_id": q["options"][0]["option_id"]
        }
        for q in questions
    ]

    # Submit answers and get final result
    final_result = submit_and_score(
        attempt_id=attempt_id,
        learner_id=learner_id,
        answers=answers
    )

    # Print final summary
    print("\n========== FINAL RESULT ==========")
    print(f"Learner ID     : {final_result['learner_id']}")
    print(f"Attempt ID     : {final_result['attempt_id']}")
    print(f"Score          : {final_result['score']} / {final_result['total_possible']}")
    print(f"Percentage     : {final_result['percentage']}%")
    print(f"Level Assigned : {final_result['level']}")
    print("==================================")
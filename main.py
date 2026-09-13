from database import fetch_one, fetch_all, execute, get_connection
from scoring_engine import score_attempt
from level_engine import assign_level
import random


#LEARNER REGISTRATION
def register_learner(full_name, email, phone):
    #Check if email already exists
    existing = fetch_one("SELECT * FROM learner WHERE email = %s", (email,))
    if existing:
        print(f"Learner with email {email} already exists with ID {existing['learner_id']}")
        return existing["learner_id"]

    #Creating new learner
    execute("INSERT INTO learner (full_name, email, phone_number) VALUES (%s, %s, %s)", (full_name, email, phone))
    new_learner = fetch_one("SELECT learner_id FROM learner WHERE email = %s", (email,)) #Selecting the new learner to get the ID
    print(f"New learner created with ID {new_learner['learner_id']}")
    return new_learner["learner_id"]


#GET BEHAVIOURAL QUESTIONS — fetches 5 general + 5 skill-specific questions
def get_behavioural_questions(skill_id):

    #Fetch 5 general questions that apply to everyone
    general_questions = fetch_all(
        """
        SELECT question_id, question_text, question_type
        FROM behavioural_questions
        WHERE question_type = 'GENERAL' AND is_active = TRUE
        LIMIT 5
        """,
        None
    )

    #Fetch 5 skill-specific questions for the selected skill
    skill_questions = fetch_all(
        """
        SELECT question_id, question_text, question_type
        FROM behavioural_questions
        WHERE skill_id = %s AND question_type = 'SKILL_SPECIFIC' AND is_active = TRUE
        LIMIT 5
        """,
        (skill_id,)
    )

    #Fetch skill name for context
    skill = fetch_one(
        "SELECT skill_name FROM skills WHERE skill_id = %s",
        (skill_id,)
    )

    #Combine both lists — general first then skill-specific
    all_questions = list(general_questions) + list(skill_questions)

    return {
        "skill_id": skill_id,
        "skill_name": skill["skill_name"] if skill else "Unknown",
        "total_questions": len(all_questions),
        "questions": all_questions
    }


#SUBMIT BEHAVIOURAL ANSWERS — saves learner's answers to learner_profile table
def submit_behavioural_answers(learner_id, attempt_id, answers):

    #Save each answer to the learner_profile table
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            for answer in answers:
                cursor.execute(
                    """
                    INSERT INTO learner_profile
                    (learner_id, attempt_id, question_id, answer_text)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (learner_id, attempt_id, answer["question_id"], answer["answer_text"])
                )
        #Commit all answers at once
        conn.commit()
        print(f"Behavioural answers saved for learner_id={learner_id}")

    except Exception as e:
        conn.rollback()
        print(f"[ERROR] Failed to save behavioural answers: {e}")
        raise

    finally:
        conn.close()

    return {
        "learner_id": learner_id,
        "attempt_id": attempt_id,
        "total_answers": len(answers),
        "message": "Behavioural answers saved successfully"
    }

    

#START TEST ATTEMPT
def start_attempt(learner_id, skill_id, declared_level):

    #Validate declared level — must be one of the four accepted values
    valid_levels = ["BEGINNER", "JUNIOR", "MID", "ADVANCED"]
    declared_level = declared_level.upper()
    if declared_level not in valid_levels:
        raise ValueError(f"Invalid level declared: {declared_level}. Must be one of {valid_levels}")

    #Fetch the level_id for the declared level from proficiency_level table
    level_data = fetch_one(
        "SELECT level_id FROM proficiency_level WHERE level_name = %s",
        (declared_level,)
    )
    if not level_data:
        raise ValueError(f"Level {declared_level} not found in database")
    declared_level_id = level_data["level_id"]

    #Create a new test attempt and store the declared level
    execute(
        "INSERT INTO test_attempt (learner_id, skill_id, declared_level_id) VALUES (%s, %s, %s)",
        (learner_id, skill_id, declared_level_id)
    )

    #Fetch the attempt that was just created to get its ID
    attempt = fetch_one(
        "SELECT attempt_id FROM test_attempt WHERE learner_id = %s AND skill_id = %s ORDER BY start_time DESC LIMIT 1",
        (learner_id, skill_id)
    )
    attempt_id = attempt["attempt_id"]
    print(f"New attempt started with ID {attempt_id}")

    #Fetch 25 random questions for the declared level only
    questions = fetch_all(
        """
        SELECT q.question_id, q.question_text, q.difficulty_level, q.subskill_id
        FROM questions q
        JOIN subskills sub ON q.subskill_id = sub.subskill_id
        WHERE sub.skill_id = %s AND q.difficulty_level = %s
        ORDER BY RAND()
        LIMIT 25
        """,
        (skill_id, declared_level)
    )
    print(f"Fetched {len(questions)} questions for skill_id={skill_id} at {declared_level} level")

    #Fetch answer options for each question without revealing correct answer
    for i, question in enumerate(questions):
        options = fetch_all(
            "SELECT option_id, option_text FROM options WHERE question_id = %s",
            (question["question_id"],))
        question_dict = dict(question)          #Convert to plain dict
        question_dict["options"] = random.sample(list(options), len(options)) #Shuffle options randomly
        questions[i] = question_dict

    #Return attempt details and questions to the caller
    return {
        "attempt_id": attempt_id,
        "learner_id": learner_id,
        "skill_id": skill_id,
        "declared_level": declared_level,
        "total_questions": len(questions),
        "questions": questions
    }


#SUBMIT ANSWER AND SCORE
def submit_and_score(attempt_id, learner_id, answers):

    #Save all learner answers to the DB in one transaction
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            for answer in answers:
                question_id = answer["question_id"]
                selected_option_id = answer["selected_option_id"]

                #Check if the selected option is correct by looking it up in options table
                option = fetch_one(
                    "SELECT is_correct FROM options WHERE option_id = %s",
                    (selected_option_id,)
                )
                is_correct = option["is_correct"] if option else False

                #Insert the learner's answer into learner_answer table
                cursor.execute(
                    """
                    INSERT INTO learner_answer (attempt_id, question_id, selected_option_id, is_correct)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (attempt_id, question_id, selected_option_id, is_correct)
                )

        #Commit all answers at once
        conn.commit()
        print(f"All answers saved for attempt_id={attempt_id}")

    except Exception as e:
        conn.rollback()
        print(f"Failed to save answers: {e}")
        raise

    finally:
        conn.close()

    #Score the attempt using the scoring engine
    score_result = score_attempt(attempt_id)
    print(f"Scoring complete: {score_result['percentage']}%")

    #Assign proficiency level using the level engine only if passed
    if score_result["passed"]:
        level_result = assign_level(
            learner_id=learner_id,
            attempt_id=attempt_id,
            level_id=score_result["level_id"]
        )
        print(f"Level assigned: {level_result['level_name']}")
    else:
        print(f"Learner did not pass declared level — level not assigned")

    #Return the final combined result
    return {
        "learner_id": learner_id,
        "attempt_id": attempt_id,
        "score": score_result["score"],
        "total_possible": 25,
        "percentage": score_result["percentage"],
        "declared_level": score_result["declared_level"],
        "status": score_result["status"],
        "confirmed_level": score_result["confirmed_level"],
        "level_suggestion": score_result["level_suggestion"],
        "difficulty_breakdown": score_result["level_breakdown"],
        "subskill_breakdown": score_result["subskill_breakdown"]
    }


#TESTING
if __name__ == "__main__":

    #Register a learner
    learner_id = register_learner(
        full_name="Joshua Excel",
        email="joshxcel@email.com",
        phone="08012345678"
    )

    #Start a test attempt for skill 1 at JUNIOR level
    attempt_data = start_attempt(learner_id=learner_id, skill_id=1, declared_level="JUNIOR")
    attempt_id = attempt_data["attempt_id"]
    questions = attempt_data["questions"]

    #Simulate answers by always picking the first option
    answers = [
        {
            "question_id": q["question_id"],
            "selected_option_id": q["options"][0]["option_id"]
        }
        for q in questions
    ]

    #Submit answers and get final result
    final_result = submit_and_score(
        attempt_id=attempt_id,
        learner_id=learner_id,
        answers=answers
    )

    #Print final summary
    print("\n========== FINAL RESULT ==========")
    print(f"Learner ID      : {final_result['learner_id']}")
    print(f"Attempt ID      : {final_result['attempt_id']}")
    print(f"Score           : {final_result['score']} / {final_result['total_possible']}")
    print(f"Percentage      : {final_result['percentage']}%")
    print(f"Declared Level  : {final_result['declared_level']}")
    print(f"Status          : {final_result['status']}")
    print(f"Confirmed Level : {final_result['confirmed_level']}")
    print(f"Level Suggestion: {final_result['level_suggestion']}")
    print("==================================")
import os

import psycopg2
import pymysql
from dotenv import load_dotenv
from psycopg2.extras import execute_values

load_dotenv()

#MySQL connection (my local device DB)
mysql_conn = pymysql.connect(
    host=os.getenv("DB_HOST"),
    port=int(os.getenv("DB_PORT", "3306")),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    database=os.getenv("DB_NAME"),
    cursorclass=pymysql.cursors.DictCursor
)

#PostgreSQL connection with render cloud db
pg_conn = psycopg2.connect(os.getenv("DATABASE_URL"))

pg_cursor = pg_conn.cursor()
mysql_cursor = mysql_conn.cursor()

print("Connected to both databases successfully!")

#Helper function to fetch all rows from MySQL
def fetch_mysql(query):
    mysql_cursor.execute(query)
    return mysql_cursor.fetchall()

#Point every serial/identity sequence at MAX(id) so new rows don't collide.
#Same logic as scripts/reset_sequences.sql (use that one to fix an already-migrated DB).
def reset_sequences(cursor):
    cursor.execute("""
        SELECT c.table_name, c.column_name,
               pg_get_serial_sequence(format('%I.%I', c.table_schema, c.table_name), c.column_name)
        FROM information_schema.columns c
        JOIN information_schema.tables t
          ON t.table_schema = c.table_schema AND t.table_name = c.table_name AND t.table_type = 'BASE TABLE'
        WHERE c.table_schema = 'public'
          AND pg_get_serial_sequence(format('%I.%I', c.table_schema, c.table_name), c.column_name) IS NOT NULL
    """)
    for table, column, seq in cursor.fetchall():
        cursor.execute(
            f'SELECT setval(%s, COALESCE((SELECT MAX("{column}") FROM "{table}"), 0) + 1, false)',
            (seq,)
        )
        print(f"  {table}.{column}: next id {cursor.fetchone()[0]}")

try:
    #Migrate proficiency_level (STEP 1)
    print("\nMigrating proficiency_level...")
    rows = fetch_mysql("SELECT level_id, level_name, created_at FROM proficiency_level")
    if rows:
        execute_values(pg_cursor, """
            INSERT INTO proficiency_level (level_id, level_name, created_at)
            VALUES %s ON CONFLICT (level_id) DO NOTHING
        """, [(r["level_id"], r["level_name"], r["created_at"]) for r in rows])
    print(f"  Migrated {len(rows)} rows")

    #Migrate level_threshold(STEP 2)
    print("Migrating level_threshold...")
    rows = fetch_mysql("SELECT threshold_id, level_id, min_score, max_score FROM level_threshold")
    if rows:
        execute_values(pg_cursor, """
            INSERT INTO level_threshold (threshold_id, level_id, min_score, max_score)
            VALUES %s ON CONFLICT (threshold_id) DO NOTHING
        """, [(r["threshold_id"], r["level_id"], r["min_score"], r["max_score"]) for r in rows])
    print(f"  Migrated {len(rows)} rows")

    #Migrate skills (STEP 3)
    print("Migrating skills...")
    rows = fetch_mysql("SELECT skill_id, skill_name, category, skill_descr, created_at FROM skills")
    if rows:
        execute_values(pg_cursor, """
            INSERT INTO skills (skill_id, skill_name, category, skill_descr, created_at)
            VALUES %s ON CONFLICT (skill_id) DO NOTHING
        """, [(r["skill_id"], r["skill_name"], r["category"], r["skill_descr"], r["created_at"]) for r in rows])
    print(f"  Migrated {len(rows)} rows")

    #Migrate subskills (STEP 4)
    print("Migrating subskills...")
    rows = fetch_mysql("SELECT subskill_id, skill_id, subskill_name FROM subskills")
    if rows:
        execute_values(pg_cursor, """
            INSERT INTO subskills (subskill_id, skill_id, subskill_name)
            VALUES %s ON CONFLICT (subskill_id) DO NOTHING
        """, [(r["subskill_id"], r["skill_id"], r["subskill_name"]) for r in rows])
    print(f"  Migrated {len(rows)} rows")

    #Migrate questions (STEP 5)
    print("Migrating questions...")
    rows = fetch_mysql("SELECT question_id, subskill_id, question_text, difficulty_level, weight, created_at FROM questions")
    if rows:
        execute_values(pg_cursor, """
            INSERT INTO questions (question_id, subskill_id, question_text, difficulty_level, weight, created_at)
            VALUES %s ON CONFLICT (question_id) DO NOTHING
        """, [(r["question_id"], r["subskill_id"], r["question_text"], r["difficulty_level"], r["weight"], r["created_at"]) for r in rows])
    print(f"  Migrated {len(rows)} rows")

    #Migrate options (STEP 6)
    print("Migrating options...")
    rows = fetch_mysql("SELECT option_id, question_id, option_text, is_correct FROM options")
    if rows:
        execute_values(pg_cursor, """
            INSERT INTO options (option_id, question_id, option_text, is_correct)
            VALUES %s ON CONFLICT (option_id) DO NOTHING
        """, [(r["option_id"], r["question_id"], r["option_text"], bool(r["is_correct"])) for r in rows])
    print(f"  Migrated {len(rows)} rows")

    #Migrate behavioural_questions(STEP 7)
    print("Migrating behavioural_questions...")
    rows = fetch_mysql("SELECT question_id, skill_id, question_text, question_type, is_active, created_at FROM behavioural_questions")
    if rows:
        execute_values(pg_cursor, """
            INSERT INTO behavioural_questions (question_id, skill_id, question_text, question_type, is_active, created_at)
            VALUES %s ON CONFLICT (question_id) DO NOTHING
        """, [(r["question_id"], r["skill_id"], r["question_text"], r["question_type"], bool(r["is_active"]), r["created_at"]) for r in rows])
    print(f"  Migrated {len(rows)} rows")

    #Migrate learner (STEP 8)
    print("Migrating learner...")
    rows = fetch_mysql("SELECT learner_id, full_name, email, phone_number, registration_date, learner_status, created_at, updated_at FROM learner")
    if rows:
        execute_values(pg_cursor, """
            INSERT INTO learner (learner_id, full_name, email, phone_number, registration_date, learner_status, created_at, updated_at)
            VALUES %s ON CONFLICT (learner_id) DO NOTHING
        """, [(r["learner_id"], r["full_name"], r["email"], r["phone_number"], r["registration_date"], r["learner_status"].upper(), r["created_at"], r["updated_at"]) for r in rows])
    print(f"  Migrated {len(rows)} rows")

    #Migrate test_attempt (STEP 9)
    print("Migrating test_attempt...")
    rows = fetch_mysql("SELECT attempt_id, learner_id, skill_id, declared_level_id, start_time, end_time, overall_percentage, assigned_level_id, attempt_status, created_at, updated_at FROM test_attempt")
    if rows:
        execute_values(pg_cursor, """
            INSERT INTO test_attempt (attempt_id, learner_id, skill_id, declared_level_id, start_time, end_time, overall_percentage, assigned_level_id, attempt_status, created_at, updated_at)
            VALUES %s ON CONFLICT (attempt_id) DO NOTHING
        """, [(r["attempt_id"], r["learner_id"], r["skill_id"], r["declared_level_id"], r["start_time"], r["end_time"], r["overall_percentage"], r["assigned_level_id"], r["attempt_status"].upper(), r["created_at"], r["updated_at"]) for r in rows])
    print(f"  Migrated {len(rows)} rows")

    #Migrate learner_answer
    print("Migrating learner_answer...")
    rows = fetch_mysql("SELECT learner_answer_id, attempt_id, question_id, selected_option_id, is_correct, answered_at FROM learner_answer")
    if rows:
        execute_values(pg_cursor, """
            INSERT INTO learner_answer (learner_answer_id, attempt_id, question_id, selected_option_id, is_correct, answered_at)
            VALUES %s ON CONFLICT (learner_answer_id) DO NOTHING
        """, [(r["learner_answer_id"], r["attempt_id"], r["question_id"], r["selected_option_id"], bool(r["is_correct"]), r["answered_at"]) for r in rows])
    print(f"  Migrated {len(rows)} rows")

    #Migrate learner_level
    print("Migrating learner_level...")
    rows = fetch_mysql("SELECT learner_level_id, learner_id, skill_id, attempt_id, level_id, assigned_at FROM learner_level")
    if rows:
        execute_values(pg_cursor, """
            INSERT INTO learner_level (learner_level_id, learner_id, skill_id, attempt_id, level_id, assigned_at)
            VALUES %s ON CONFLICT (learner_level_id) DO NOTHING
        """, [(r["learner_level_id"], r["learner_id"], r["skill_id"], r["attempt_id"], r["level_id"], r["assigned_at"]) for r in rows])
    print(f"  Migrated {len(rows)} rows")

    #Migrate attempt_difficulty_score (STEP 12)
    print("Migrating attempt_difficulty_score...")
    rows = fetch_mysql("SELECT attempt_id, difficulty_level, total_questions, correct_answers, percentage_score FROM attempt_difficulty_score")
    if rows:
        execute_values(pg_cursor, """
            INSERT INTO attempt_difficulty_score (attempt_id, difficulty_level, total_questions, correct_answers, percentage_score)
            VALUES %s
        """, [(r["attempt_id"], r["difficulty_level"], r["total_questions"], r["correct_answers"], r["percentage_score"]) for r in rows])
    print(f"  Migrated {len(rows)} rows")

    #Migrate attempt_subskill_score (STEP 13)
    print("Migrating attempt_subskill_score...")
    rows = fetch_mysql("SELECT attempt_id, subskill_id, total_questions, correct_answers, percentage_score FROM attempt_subskill_score")
    if rows:
        execute_values(pg_cursor, """
            INSERT INTO attempt_subskill_score (attempt_id, subskill_id, total_questions, correct_answers, percentage_score)
            VALUES %s
        """, [(r["attempt_id"], r["subskill_id"], r["total_questions"], r["correct_answers"], r["percentage_score"]) for r in rows])
    print(f"  Migrated {len(rows)} rows")

    #Migrate subskill_recommendation (STEP 14)
    print("Migrating subskill_recommendation...")
    rows = fetch_mysql("SELECT recommendation_id, attempt_id, learner_id, priority, percentage_score, subskill_id, recommendation_text, created_at FROM subskill_recommendation")
    if rows:
        execute_values(pg_cursor, """
            INSERT INTO subskill_recommendation (recommendation_id, attempt_id, learner_id, priority, percentage_score, subskill_id, recommendation_text, created_at)
            VALUES %s ON CONFLICT (recommendation_id) DO NOTHING
        """, [(r["recommendation_id"], r["attempt_id"], r["learner_id"], r["priority"], r["percentage_score"], r["subskill_id"], r["recommendation_text"], r["created_at"]) for r in rows])
    print(f"  Migrated {len(rows)} rows")

    #Migrate learner_profile (STEP 15)
    print("Migrating learner_profile...")
    rows = fetch_mysql("SELECT profile_id, learner_id, attempt_id, question_id, answer_text, created_at FROM learner_profile")
    if rows:
        execute_values(pg_cursor, """
            INSERT INTO learner_profile (profile_id, learner_id, attempt_id, question_id, answer_text, created_at)
            VALUES %s ON CONFLICT (profile_id) DO NOTHING
        """, [(r["profile_id"], r["learner_id"], r["attempt_id"], r["question_id"], r["answer_text"], r["created_at"]) for r in rows])
    print(f"  Migrated {len(rows)} rows")

    #Reset every id counter (sequence) to MAX(id). The rows above were inserted WITH
    #their old ids, which does not move the sequences, so without this the next
    #register/start attempt reuses id 1 and fails with "duplicate key" (500).
    print("Resetting id sequences...")
    reset_sequences(pg_cursor)

    #Commit all changes to PostgreSQL
    pg_conn.commit()
    print("\nALL DATA MIGRATED SUCCESSFULLY!")

except Exception as e:
    pg_conn.rollback()
    print(f"\nMigration failed: {e}")
    raise

finally:
    mysql_cursor.close()
    mysql_conn.close()
    pg_cursor.close()
    pg_conn.close()
    print("Both connections closed.")

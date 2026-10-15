-- One-time repair for rows saved before fix 4 (run AFTER deploying fix 4).
-- 1) learner_level rows saved with skill_id = NULL get the skill of their attempt.
-- 2) Passed attempts get the level they were actually taken at (declared level),
--    instead of the score-based level (JUNIOR test at 100% was saved as ADVANCED).
--
--   psql "$DATABASE_URL" -f scripts/fix_learner_levels.sql

BEGIN;

-- Preview what will change
SELECT ll.learner_level_id, ll.learner_id, ll.skill_id AS old_skill, ta.skill_id AS new_skill,
       ll.level_id AS old_level, ta.declared_level_id AS new_level
FROM learner_level ll
JOIN test_attempt ta ON ta.attempt_id = ll.attempt_id
WHERE ll.skill_id IS NULL
   OR (ta.attempt_status = 'PASSED' AND ll.level_id IS DISTINCT FROM ta.declared_level_id);

UPDATE learner_level ll
SET skill_id = ta.skill_id
FROM test_attempt ta
WHERE ta.attempt_id = ll.attempt_id
  AND ll.skill_id IS NULL;

UPDATE learner_level ll
SET level_id = ta.declared_level_id
FROM test_attempt ta
WHERE ta.attempt_id = ll.attempt_id
  AND ta.attempt_status = 'PASSED'
  AND ta.declared_level_id IS NOT NULL
  AND ll.level_id IS DISTINCT FROM ta.declared_level_id;

UPDATE test_attempt
SET assigned_level_id = declared_level_id
WHERE attempt_status = 'PASSED'
  AND declared_level_id IS NOT NULL
  AND assigned_level_id IS DISTINCT FROM declared_level_id;

-- Duplicates left over (same learner + skill more than once)? Listed here, not deleted.
SELECT learner_id, skill_id, COUNT(*) AS rows_for_same_skill
FROM learner_level
GROUP BY learner_id, skill_id
HAVING COUNT(*) > 1;

COMMIT;

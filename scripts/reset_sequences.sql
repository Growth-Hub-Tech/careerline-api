-- Reset every serial / identity id counter so the next INSERT gets MAX(id) + 1.
--
-- Why: migrate_data.py copied rows WITH their original ids, but Postgres only
-- moves a sequence forward when IT hands out the id. So the counters stayed at 1
-- and the next "register" tried learner_id = 1 again -> duplicate key -> 500.
--
-- Safe to run any number of times. Run it against your database (after migrate_data.py):
--   psql "$DATABASE_URL" -f scripts/reset_sequences.sql

DO $$
DECLARE
    r   record;
    nxt bigint;
BEGIN
    FOR r IN
        SELECT c.table_schema, c.table_name, c.column_name,
               pg_get_serial_sequence(format('%I.%I', c.table_schema, c.table_name), c.column_name) AS seq
        FROM information_schema.columns c
        JOIN information_schema.tables t
          ON t.table_schema = c.table_schema AND t.table_name = c.table_name AND t.table_type = 'BASE TABLE'
        WHERE c.table_schema = 'public'
          AND pg_get_serial_sequence(format('%I.%I', c.table_schema, c.table_name), c.column_name) IS NOT NULL
    LOOP
        EXECUTE format('SELECT MAX(%I) FROM %I.%I', r.column_name, r.table_schema, r.table_name) INTO nxt;
        IF nxt IS NULL THEN
            PERFORM setval(r.seq, 1, false);      -- empty table: next id is 1
        ELSE
            PERFORM setval(r.seq, nxt, true);     -- next id is MAX(id) + 1
        END IF;
        RAISE NOTICE '%.%: max id %, next id %', r.table_name, r.column_name, COALESCE(nxt, 0), COALESCE(nxt, 0) + 1;
    END LOOP;
END $$;

-- Check: last_value should equal the table's MAX(id) (empty for empty tables)
SELECT sequencename AS sequence, last_value
FROM pg_sequences
WHERE schemaname = 'public'
ORDER BY sequencename;

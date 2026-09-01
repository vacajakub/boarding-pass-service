BEGIN;

DROP SCHEMA IF EXISTS boarding_pass CASCADE;

CREATE SCHEMA boarding_pass AUTHORIZATION boarding_pass;

-- gen_random_uuid() is in pg_catalog since postgres 13, so no extension is needed for it

COMMIT;

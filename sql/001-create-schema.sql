BEGIN;

-- gen_random_uuid() lives in pgcrypto on older postgres, core since 13
CREATE EXTENSION IF NOT EXISTS pgcrypto;

COMMIT;

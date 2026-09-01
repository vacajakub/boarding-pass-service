DO
$do$
BEGIN
   IF EXISTS (
      SELECT FROM pg_catalog.pg_roles
      WHERE  rolname = 'boarding_pass') THEN

      RAISE NOTICE 'Role "boarding_pass" already exists. Skipping.';
   ELSE
      CREATE USER boarding_pass WITH ENCRYPTED PASSWORD 'boarding_pass';
   END IF;
END
$do$;


DO
$do$
BEGIN
   IF EXISTS (
      SELECT FROM pg_catalog.pg_database
      WHERE  datname = 'boarding_pass') THEN
      RAISE NOTICE 'DB "boarding_pass" already exists. Skipping.';
   ELSE
      CREATE DATABASE boarding_pass;
   END IF;
END
$do$;


GRANT ALL PRIVILEGES ON DATABASE boarding_pass TO boarding_pass;

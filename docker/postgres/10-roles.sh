#!/bin/sh
# Runs once, when the Postgres volume is first created. Sets up the three
# roles BACKEND-SETUP.md describes:
#   $POSTGRES_USER        owns the schema; migrations only
#   inventoryai_app       the API's tenant sessions: not owner, not BYPASSRLS,
#                         so Row-Level Security applies to every query
#   inventoryai_platform  BYPASSRLS: seeding, sign-in lookups, impersonation
# The two role names are fixed: the migrations grant to them by name.
set -eu

: "${APP_DB_PASSWORD:?APP_DB_PASSWORD is required}"
: "${PLATFORM_DB_PASSWORD:?PLATFORM_DB_PASSWORD is required}"

psql -v ON_ERROR_STOP=1 \
     -v app_pw="$APP_DB_PASSWORD" -v platform_pw="$PLATFORM_DB_PASSWORD" \
     -v owner="$POSTGRES_USER" -v db="$POSTGRES_DB" \
     --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
CREATE EXTENSION IF NOT EXISTS vector;

CREATE ROLE inventoryai_app WITH LOGIN PASSWORD :'app_pw';
CREATE ROLE inventoryai_platform WITH LOGIN PASSWORD :'platform_pw' BYPASSRLS;

GRANT CONNECT ON DATABASE :"db" TO inventoryai_app, inventoryai_platform;
GRANT USAGE ON SCHEMA public TO inventoryai_app, inventoryai_platform;
ALTER DEFAULT PRIVILEGES FOR ROLE :"owner" IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO inventoryai_app, inventoryai_platform;
ALTER DEFAULT PRIVILEGES FOR ROLE :"owner" IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO inventoryai_app, inventoryai_platform;
SQL

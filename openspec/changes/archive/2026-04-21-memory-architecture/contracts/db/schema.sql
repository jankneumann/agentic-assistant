-- memory-architecture database schema contract
-- Target: ParadeDB Postgres (asyncpg driver)
-- Managed by: Alembic migration 001_initial_memory_schema

CREATE TABLE IF NOT EXISTS memory (
    id          SERIAL PRIMARY KEY,
    persona     VARCHAR(64)  NOT NULL,
    key         VARCHAR(256) NOT NULL,
    value       JSONB        NOT NULL DEFAULT '{}',
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (persona, key)
);

CREATE INDEX idx_memory_persona ON memory (persona);

CREATE TABLE IF NOT EXISTS preferences (
    id          SERIAL PRIMARY KEY,
    persona     VARCHAR(64)  NOT NULL,
    category    VARCHAR(128) NOT NULL,
    key         VARCHAR(256) NOT NULL,
    value       JSONB        NOT NULL DEFAULT '{}',
    confidence  REAL         NOT NULL DEFAULT 0.5,
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (persona, category, key)
);

CREATE INDEX idx_preferences_persona_category ON preferences (persona, category);

CREATE TABLE IF NOT EXISTS interactions (
    id          SERIAL PRIMARY KEY,
    persona     VARCHAR(64)  NOT NULL,
    role        VARCHAR(64)  NOT NULL,
    summary     TEXT         NOT NULL,
    metadata    JSONB        NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_interactions_persona_created ON interactions (persona, created_at DESC);

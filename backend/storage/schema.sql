-- Kaagaz case files (Phase 9). Created on startup if missing; plain SQL, no migrations tool.
-- Never stored: raw phone numbers, images, crops, videos, ID numbers (not even the last 4 digits).

CREATE TABLE IF NOT EXISTS users (
    id          uuid PRIMARY KEY,
    phone_hash  text NOT NULL UNIQUE,          -- HMAC-SHA256(PHONE_HASH_KEY, normalized number), hex
    phone_last4 text NOT NULL,                 -- for display only ("ending 3210")
    language    text NOT NULL,
    created     date NOT NULL DEFAULT current_date
);

CREATE TABLE IF NOT EXISTS checks (
    id          uuid PRIMARY KEY,
    user_id     uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    session_id  text NOT NULL UNIQUE,          -- the run it came from (re-plans after a close-up update it)
    previous_id uuid REFERENCES checks (id) ON DELETE SET NULL,  -- "Check again": the check it re-checks
    language    text NOT NULL,
    created     timestamptz NOT NULL DEFAULT now(),
    updated     timestamptz NOT NULL DEFAULT now(),
    data        jsonb NOT NULL                 -- storage.models.CheckData (allow-listed fields only)
);
CREATE INDEX IF NOT EXISTS checks_user_created ON checks (user_id, created DESC);

CREATE TABLE IF NOT EXISTS step_progress (
    check_id uuid NOT NULL REFERENCES checks (id) ON DELETE CASCADE,
    step     integer NOT NULL,
    done     boolean NOT NULL,
    updated  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (check_id, step)
);

-- Placeholder for Ask Kaagaz conversations (Phase 10).
CREATE TABLE IF NOT EXISTS chats (
    id       uuid PRIMARY KEY,
    user_id  uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    check_id uuid REFERENCES checks (id) ON DELETE CASCADE,
    created  timestamptz NOT NULL DEFAULT now(),
    messages jsonb NOT NULL DEFAULT '[]'
);

-- Anonymous: a random session id, never a user.
CREATE TABLE IF NOT EXISTS feedback (
    id         bigserial PRIMARY KEY,
    session_id text NOT NULL,
    target     text NOT NULL,
    value      text NOT NULL,
    comment    text,
    created    date NOT NULL DEFAULT current_date
);

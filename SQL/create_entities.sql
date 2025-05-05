CREATE EXTENSION IF NOT EXISTS vector;



-- chat_session

CREATE TABLE IF NOT EXISTS chat_session (

                                            session_id SERIAL PRIMARY KEY,

                                            timestamp TIMESTAMP WITHOUT TIME ZONE,

                                            voice_enabled BOOLEAN,

                                            duration_minutes INTEGER

);



-- message

CREATE TABLE IF NOT EXISTS message (

                                       message_id SERIAL PRIMARY KEY,

                                       session_id INTEGER REFERENCES chat_session(session_id),

    content TEXT,

    timestamp TIMESTAMP WITHOUT TIME ZONE,

    message_type VARCHAR(50),

    embedding vector(3072)

    );



-- Enforce message_type integrity

DO $$

BEGIN

    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'message_type_check') THEN

ALTER TABLE message

    ADD CONSTRAINT message_type_check CHECK (message_type IN ('user', 'bot', 'system'));

END IF;

END $$;



-- feedback

CREATE TABLE IF NOT EXISTS feedback (

                                        feedback_id SERIAL PRIMARY KEY,

                                        session_id INTEGER REFERENCES chat_session(session_id),

    rating INTEGER,

    comment TEXT,

    timestamp TIMESTAMP WITHOUT TIME ZONE

    );



-- bravur_data

CREATE TABLE IF NOT EXISTS bravur_data (

                                           entry_id SERIAL PRIMARY KEY,

                                           message_id INTEGER,  -- plain integer, NO FOREIGN KEY

                                           title VARCHAR(255),

    content TEXT,

    file_type VARCHAR(50),

    content_embedding vector(3072),

    last_updated_content TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),

    last_updated_embedding TIMESTAMP WITHOUT TIME ZONE

    );



-- Clean up accidental old 'last_updated'

DO $$

BEGIN

    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='bravur_data' AND column_name='last_updated') THEN

ALTER TABLE bravur_data DROP COLUMN last_updated;

END IF;

END $$;



-- Safe vector dimension patch

DO $$

BEGIN

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='bravur_data' AND column_name='content_embedding') THEN

ALTER TABLE bravur_data ADD COLUMN content_embedding vector(3072);

ELSE

ALTER TABLE bravur_data ALTER COLUMN content_embedding TYPE vector(3072);

END IF;

END $$;



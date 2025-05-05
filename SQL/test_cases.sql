--TEST CASE 1
-- Insert a new chat session that's 8 days old
INSERT INTO chat_session (timestamp, voice_enabled, duration_minutes)
VALUES (CURRENT_TIMESTAMP - INTERVAL '8 days', true, 30);

-- Query to select chat sessions older than 7 days with duration of 30 minutes
SELECT * FROM chat_session WHERE timestamp < NOW() - INTERVAL '7 days' AND duration_minutes = 30;

-- Altering the chat_session table to disable a trigger
ALTER TABLE chat_session DISABLE TRIGGER trigger_delete_old_chat_sessions;

-- TEST CASE 2
-- Just under 7 days (should NOT be deleted)
INSERT INTO chat_session (timestamp, voice_enabled, duration_minutes)
VALUES (CURRENT_TIMESTAMP - INTERVAL '6 days 23 hours 59 minutes', false, 10);

-- Just over 7 days (should be deleted)
INSERT INTO chat_session (timestamp, voice_enabled, duration_minutes)
VALUES (CURRENT_TIMESTAMP - INTERVAL '7 days 1 minute', true, 20);

-- TEST CASE 3
-- Call the cleanup function
SELECT manually_delete_old_chat_sessions();

-- Should show the 6-day 23-hour 59-minute session
SELECT * FROM chat_session WHERE duration_minutes = 10;

-- Should return no rows for the 7-day 1-minute session
SELECT * FROM chat_session WHERE duration_minutes = 20;

-- TEST CASE 4
-- Create an old session
INSERT INTO chat_session (timestamp, voice_enabled, duration_minutes)
VALUES (CURRENT_TIMESTAMP - INTERVAL '8 days', true, 25)
RETURNING session_id INTO session_id_var;

-- Insert feedback for this session
INSERT INTO feedback (session_id, rating, comment, timestamp)
VALUES (session_id_var, 4, 'Test feedback for deletion case', CURRENT_TIMESTAMP - INTERVAL '8 days');

-- Find orphaned feedback (feedback without a parent session)
SELECT f.*
FROM feedback f
LEFT JOIN chat_session cs ON f.session_id = cs.session_id
WHERE f.comment = 'Test feedback for deletion case' AND cs.session_id IS NULL;

-- TEST CASE 5
DO $$
DECLARE
    new_session_id1 integer;
    new_session_id2 integer;
    new_session_id3 integer;
    new_session_id4 integer;
BEGIN
    -- Current date chat session
    INSERT INTO chat_session (timestamp, voice_enabled, duration_minutes)
    VALUES (CURRENT_TIMESTAMP, true, 15)
    RETURNING session_id INTO new_session_id1;
    
    -- 6-day old chat session
    INSERT INTO chat_session (timestamp, voice_enabled, duration_minutes)
    VALUES (CURRENT_TIMESTAMP - INTERVAL '6 days 23 hours', false, 10)
    RETURNING session_id INTO new_session_id2;
    
    -- 7-day old chat session
    INSERT INTO chat_session (timestamp, voice_enabled, duration_minutes)
    VALUES (CURRENT_TIMESTAMP - INTERVAL '7 days 1 hour', true, 20)
    RETURNING session_id INTO new_session_id3;
    
    -- 8-day old chat session
    INSERT INTO chat_session (timestamp, voice_enabled, duration_minutes)
    VALUES (CURRENT_TIMESTAMP - INTERVAL '8 days', false, 5)
    RETURNING session_id INTO new_session_id4;
    
    -- Insert messages for all sessions
    INSERT INTO message (session_id, content, timestamp, message_type)
    VALUES
    (new_session_id1, 'Current day message', CURRENT_TIMESTAMP, 'user'),
    (new_session_id2, 'Six day old message', CURRENT_TIMESTAMP - INTERVAL '6 days 23 hours', 'user'),
    (new_session_id3, 'Seven day old message', CURRENT_TIMESTAMP - INTERVAL '7 days 1 hour', 'user'),
    (new_session_id4, 'Eight day old message', CURRENT_TIMESTAMP - INTERVAL '8 days', 'user');
    
    -- Insert feedback for all sessions
    INSERT INTO feedback (session_id, rating, comment, timestamp)
    VALUES
    (new_session_id1, 5, 'Current day feedback', CURRENT_TIMESTAMP),
    (new_session_id2, 4, 'Six day old feedback', CURRENT_TIMESTAMP - INTERVAL '6 days 23 hours'),
    (new_session_id3, 3, 'Seven day old feedback', CURRENT_TIMESTAMP - INTERVAL '7 days 1 hour'),
    (new_session_id4, 2, 'Eight day old feedback', CURRENT_TIMESTAMP - INTERVAL '8 days');
    
    RAISE NOTICE 'Created test sessions with IDs: %, %, %, %', 
        new_session_id1, new_session_id2, new_session_id3, new_session_id4;
END $$;

-- VERIFYING THE TEST CASES
-- Check final state of sessions (7+ day old sessions should be gone)
SELECT 
    session_id,
    timestamp,
    duration_minutes
FROM chat_session
WHERE duration_minutes IN (5, 10, 15, 20)
ORDER BY timestamp DESC;

-- Check messages (messages for deleted sessions should be gone)
SELECT
    m.session_id,
    m.content,
    m.timestamp
FROM message m
JOIN chat_session cs ON m.session_id = cs.session_id
WHERE cs.duration_minutes IN (5, 10, 15, 20)
ORDER BY m.timestamp DESC;

-- Check feedback (all feedback should be preserved)
SELECT
    f.session_id,
    f.rating,
    f.comment,
    f.timestamp,
    CASE
        WHEN cs.session_id IS NULL THEN 'Orphaned (session deleted)'
        ELSE 'Has parent session'
    END AS feedback_status
FROM feedback f
LEFT JOIN chat_session cs ON f.session_id = cs.session_id
WHERE f.comment IN ('Current day feedback', 'Six day old feedback', 'Seven day old feedback', 'Eight day old feedback')
ORDER BY f.timestamp DESC;

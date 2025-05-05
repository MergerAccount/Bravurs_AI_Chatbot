CREATE OR REPLACE FUNCTION delete_old_chat_sessions()
RETURNS TRIGGER AS $$
DECLARE
    sessions_before integer;
    sessions_old integer;
    sessions_after integer;
BEGIN
    -- Count sessions before deletion
    SELECT COUNT(*) INTO sessions_before FROM chat_session;
    
    -- Count sessions older than 7 days
    SELECT COUNT(*) INTO sessions_old
    FROM chat_session
    WHERE timestamp < NOW() - INTERVAL '7 days';
    
    RAISE NOTICE 'Trigger cleanup function executing, current time: %', NOW();
    RAISE NOTICE 'Sessions before deletion: %', sessions_before;
    RAISE NOTICE 'Sessions older than 7 days: %', sessions_old;
    
    -- Delete messages from sessions older than 7 days
    DELETE FROM message
    WHERE session_id IN (
        SELECT session_id
        FROM chat_session
        WHERE timestamp < NOW() - INTERVAL '7 days'
    );
    
    -- Delete chat sessions older than 7 days
    DELETE FROM chat_session
    WHERE timestamp < NOW() - INTERVAL '7 days';
    
    -- Count sessions after deletion
    SELECT COUNT(*) INTO sessions_after FROM chat_session;
    RAISE NOTICE 'Sessions after deletion: %', sessions_after;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

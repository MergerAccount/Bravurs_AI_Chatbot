CREATE OR REPLACE FUNCTION deactivate_old_sessions()
RETURNS TRIGGER AS $$
BEGIN
    -- Deactivate sessions older than 3 days whenever a new session is created
    UPDATE chat_session
    SET is_active = FALSE
    WHERE is_active = TRUE
    AND timestamp < NOW() - INTERVAL '3 days';

    RAISE NOTICE 'Deactivated old sessions older than 3 days';

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger that runs after an insert
   CREATE TRIGGER trigger_deactivate_old_sessions
    AFTER INSERT ON chat_session
    FOR EACH ROW
    EXECUTE FUNCTION deactivate_old_sessions();




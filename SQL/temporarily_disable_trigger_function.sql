DROP TRIGGER IF EXISTS trigger_delete_old_chat_sessions ON chat_session;
CREATE TRIGGER trigger_delete_old_chat_sessions
AFTER INSERT ON chat_session
EXECUTE FUNCTION delete_old_chat_sessions();

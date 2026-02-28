-- Add metadata column to chat_history to store agent results JSON
ALTER TABLE chat_history ADD COLUMN metadata TEXT;

use std::fs::File;
use std::io::{Read, Write};
use std::path::Path;
use crate::chat::domain::{ChatHistoryStore, ChatMessage, ChatSession};

const CHATS_FILE: &str = "chat_history.json";

pub fn read_chat_history() -> ChatHistoryStore {
    let path = Path::new(CHATS_FILE);
    if !path.exists() {
        return ChatHistoryStore { sessions: Vec::new() };
    }

    let file = match File::open(path) {
        Ok(f) => f,
        Err(_) => return ChatHistoryStore { sessions: Vec::new() },
    };

    let mut content = String::new();
    let mut reader = std::io::BufReader::new(file);
    if reader.read_to_string(&mut content).is_err() {
        return ChatHistoryStore { sessions: Vec::new() };
    }

    serde_json::from_str(&content).unwrap_or_else(|_| ChatHistoryStore { sessions: Vec::new() })
}

pub fn write_chat_history(data: &ChatHistoryStore) -> Result<(), std::io::Error> {
    let content = serde_json::to_string_pretty(data)?;
    let mut file = File::create(CHATS_FILE)?;
    file.write_all(content.as_bytes())?;
    Ok(())
}

pub fn save_or_update_session(session: ChatSession) -> Result<ChatSession, std::io::Error> {
    let mut store = read_chat_history();
    if let Some(pos) = store.sessions.iter().position(|s| s.id == session.id) {
        store.sessions[pos] = session.clone();
    } else {
        store.sessions.insert(0, session.clone());
    }
    write_chat_history(&store)?;
    Ok(session)
}

pub fn add_message_to_session(session_id: &str, message: ChatMessage) -> Result<ChatSession, std::io::Error> {
    let mut store = read_chat_history();
    if let Some(pos) = store.sessions.iter().position(|s| s.id == session_id) {
        store.sessions[pos].messages.push(message);
        let updated = store.sessions[pos].clone();
        write_chat_history(&store)?;
        Ok(updated)
    } else {
        let title = if message.text.len() > 30 {
            format!("{}...", &message.text[..30])
        } else {
            message.text.clone()
        };
        let new_session = ChatSession {
            id: session_id.to_string(),
            title,
            created_at: message.timestamp.clone(),
            messages: vec![message],
        };
        store.sessions.insert(0, new_session.clone());
        write_chat_history(&store)?;
        Ok(new_session)
    }
}

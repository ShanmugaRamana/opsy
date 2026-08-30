use std::future::Future;
use std::pin::Pin;
use crate::chat::domain::{ChatMessage, ChatSession};
use crate::chat::infra::{chat_storage, llm_client};
use crate::onboard::infra::storage::read_user_data;
use crate::shared::command::{Command, CommandHandler};
use crate::shared::error::AppError;

pub struct CreateChatSessionCommand {
    pub session: ChatSession,
}

impl Command for CreateChatSessionCommand {
    type Output = ChatSession;
}

pub struct CreateChatSessionHandler;

impl CommandHandler<CreateChatSessionCommand> for CreateChatSessionHandler {
    fn handle(&self, command: CreateChatSessionCommand) -> Pin<Box<dyn Future<Output = Result<ChatSession, AppError>> + Send>> {
        Box::pin(async move {
            tracing::info!("Creating new chat session: ID={}, Title={}", command.session.id, command.session.title);
            chat_storage::save_or_update_session(command.session)
                .map_err(|e| AppError::Internal(e.to_string()))
        })
    }
}

pub struct SendChatMessageCommand {
    pub session_id: String,
    pub user_message: ChatMessage,
}

impl Command for SendChatMessageCommand {
    type Output = (ChatSession, ChatMessage);
}

pub struct SendChatMessageHandler;

impl CommandHandler<SendChatMessageCommand> for SendChatMessageHandler {
    fn handle(&self, command: SendChatMessageCommand) -> Pin<Box<dyn Future<Output = Result<(ChatSession, ChatMessage), AppError>> + Send>> {
        Box::pin(async move {
            tracing::info!(
                "Processing message for session {}: user prompt='{}'",
                command.session_id,
                command.user_message.text
            );

            // 1. Store user message in history
            let _ = chat_storage::add_message_to_session(&command.session_id, command.user_message.clone());

            // 2. Fetch current user config & generate reply via LLM
            let user_data = read_user_data();
            let reply_text = llm_client::generate_reply(&user_data, &command.user_message.text).await?;
            tracing::info!(
                "Generated assistant response for session {}: length={}",
                command.session_id,
                reply_text.len()
            );

            let assistant_message = ChatMessage {
                id: (chrono_like_id()).to_string(),
                sender: "assistant".to_string(),
                text: reply_text,
                timestamp: current_timestamp(),
            };

            // 3. Store assistant message in history
            let updated_session = chat_storage::add_message_to_session(&command.session_id, assistant_message.clone())
                .map_err(|e| AppError::Internal(e.to_string()))?;

            Ok((updated_session, assistant_message))
        })
    }
}

fn chrono_like_id() -> u128 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis())
        .unwrap_or(0)
}

fn current_timestamp() -> String {
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    let hours = (now / 3600) % 24;
    let minutes = (now / 60) % 60;
    format!("{:02}:{:02}", hours, minutes)
}

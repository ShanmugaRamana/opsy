use std::future::Future;
use std::pin::Pin;
use crate::chat::domain::ChatSession;
use crate::chat::infra::chat_storage;
use crate::shared::error::AppError;
use crate::shared::query::{Query, QueryHandler};

pub struct GetChatSessionsQuery;

impl Query for GetChatSessionsQuery {
    type Output = Vec<ChatSession>;
}

pub struct GetChatSessionsHandler;

impl QueryHandler<GetChatSessionsQuery> for GetChatSessionsHandler {
    fn handle(&self, _query: GetChatSessionsQuery) -> Pin<Box<dyn Future<Output = Result<Vec<ChatSession>, AppError>> + Send>> {
        Box::pin(async move {
            let store = chat_storage::read_chat_history();
            Ok(store.sessions)
        })
    }
}

pub struct GetChatSessionQuery {
    pub session_id: String,
}

impl Query for GetChatSessionQuery {
    type Output = Option<ChatSession>;
}

pub struct GetChatSessionHandler;

impl QueryHandler<GetChatSessionQuery> for GetChatSessionHandler {
    fn handle(&self, query: GetChatSessionQuery) -> Pin<Box<dyn Future<Output = Result<Option<ChatSession>, AppError>> + Send>> {
        Box::pin(async move {
            let store = chat_storage::read_chat_history();
            let session = store.sessions.into_iter().find(|s| s.id == query.session_id);
            Ok(session)
        })
    }
}

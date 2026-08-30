pub mod domain;
pub mod commands;
pub mod queries;
pub(crate) mod infra;
pub mod http;

#[allow(unused_imports)]
pub use domain::{ChatMessage, ChatSession, ChatHistoryStore};
#[allow(unused_imports)]
pub use commands::{CreateChatSessionCommand, CreateChatSessionHandler, SendChatMessageCommand, SendChatMessageHandler};
#[allow(unused_imports)]
pub use queries::{GetChatSessionQuery, GetChatSessionHandler, GetChatSessionsQuery, GetChatSessionsHandler};

use crate::shared::bus::{CommandBusBuilder, QueryBusBuilder};

pub fn register_commands(builder: CommandBusBuilder) -> CommandBusBuilder {
    builder
        .register(CreateChatSessionHandler)
        .register(SendChatMessageHandler)
}

pub fn register_queries(builder: QueryBusBuilder) -> QueryBusBuilder {
    builder
        .register(GetChatSessionsHandler)
        .register(GetChatSessionHandler)
}

use std::future::Future;
use std::pin::Pin;
use crate::onboard::domain::UserData;
use crate::onboard::infra::api_key_store;
use crate::shared::command::{Command, CommandHandler};
use crate::shared::error::AppError;

pub struct SaveApiKeyCommand {
    pub provider: String,
    pub key: String,
}

impl Command for SaveApiKeyCommand {
    type Output = UserData;
}

pub struct SaveApiKeyHandler;

impl CommandHandler<SaveApiKeyCommand> for SaveApiKeyHandler {
    fn handle(&self, command: SaveApiKeyCommand) -> Pin<Box<dyn Future<Output = Result<UserData, AppError>> + Send>> {
        Box::pin(async move {
            api_key_store::save_provider_api_key(command.provider, command.key)
        })
    }
}

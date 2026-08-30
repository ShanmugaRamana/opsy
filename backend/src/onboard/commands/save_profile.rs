use std::future::Future;
use std::pin::Pin;
use crate::onboard::domain::UserData;
use crate::onboard::infra::storage;
use crate::shared::command::{Command, CommandHandler};
use crate::shared::error::AppError;

pub struct SaveProfileCommand {
    pub profile: UserData,
}

impl Command for SaveProfileCommand {
    type Output = UserData;
}

pub struct SaveProfileHandler;

impl CommandHandler<SaveProfileCommand> for SaveProfileHandler {
    fn handle(&self, command: SaveProfileCommand) -> Pin<Box<dyn Future<Output = Result<UserData, AppError>> + Send>> {
        Box::pin(async move {
            storage::write_user_data(&command.profile)
                .map_err(|e| AppError::Internal(format!("Failed to write user_data.json: {}", e)))?;
            Ok(command.profile)
        })
    }
}

use std::future::Future;
use std::pin::Pin;
use crate::onboard::infra::runner::{self, ActiveProcess};
use crate::shared::command::{Command, CommandHandler};
use crate::shared::error::AppError;

pub struct CancelRunCommand {
    pub active_proc: ActiveProcess,
}

impl Command for CancelRunCommand {
    type Output = ();
}

pub struct CancelRunHandler;

impl CommandHandler<CancelRunCommand> for CancelRunHandler {
    fn handle(&self, command: CancelRunCommand) -> Pin<Box<dyn Future<Output = Result<(), AppError>> + Send>> {
        Box::pin(async move {
            runner::cancel_active_process(command.active_proc)
                .await
                .map_err(AppError::BadRequest)
        })
    }
}

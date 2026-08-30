use std::future::Future;
use std::pin::Pin;
use tokio::sync::mpsc;
use crate::onboard::domain::ProgressEvent;
use crate::onboard::infra::runner::{self, ActiveProcess};
use crate::shared::command::{Command, CommandHandler};
use crate::shared::error::AppError;

pub struct PullModelCommand {
    pub model_name: String,
    pub active_proc: ActiveProcess,
}

impl Command for PullModelCommand {
    type Output = mpsc::Receiver<ProgressEvent>;
}

pub struct PullModelHandler;

impl CommandHandler<PullModelCommand> for PullModelHandler {
    fn handle(&self, command: PullModelCommand) -> Pin<Box<dyn Future<Output = Result<mpsc::Receiver<ProgressEvent>, AppError>> + Send>> {
        Box::pin(async move {
            let (tx, rx) = mpsc::channel(100);
            tokio::spawn(runner::run_install_and_pull(
                command.model_name,
                tx,
                command.active_proc,
            ));
            Ok(rx)
        })
    }
}

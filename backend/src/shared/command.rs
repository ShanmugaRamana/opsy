use std::any::Any;
use std::future::Future;
use std::pin::Pin;
use crate::shared::error::AppError;

pub trait Command: Send + Sync + 'static {
    type Output: Send + 'static;
}

pub trait CommandHandler<C: Command>: Send + Sync + 'static {
    fn handle(&self, command: C) -> Pin<Box<dyn Future<Output = Result<C::Output, AppError>> + Send>>;
}

pub(crate) trait DynamicCommandHandler: Send + Sync + 'static {
    fn handle_dyn(&self, command: Box<dyn Any + Send>) -> Pin<Box<dyn Future<Output = Result<Box<dyn Any + Send>, AppError>> + Send>>;
}

pub(crate) struct CommandHandlerWrapper<C: Command, H: CommandHandler<C>> {
    pub(crate) handler: H,
    pub(crate) _marker: std::marker::PhantomData<C>,
}

impl<C: Command, H: CommandHandler<C>> DynamicCommandHandler for CommandHandlerWrapper<C, H> {
    fn handle_dyn(&self, command: Box<dyn Any + Send>) -> Pin<Box<dyn Future<Output = Result<Box<dyn Any + Send>, AppError>> + Send>> {
        match command.downcast::<C>() {
            Ok(cmd) => {
                let fut = self.handler.handle(*cmd);
                Box::pin(async move {
                    let res = fut.await?;
                    Ok(Box::new(res) as Box<dyn Any + Send>)
                })
            }
            Err(_) => Box::pin(async {
                Err(AppError::Internal("Downcast failed in DynamicCommandHandler".to_string()))
            }),
        }
    }
}

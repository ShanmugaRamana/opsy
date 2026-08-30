use std::any::TypeId;
use std::collections::HashMap;
use std::sync::Arc;
use crate::shared::command::{Command, CommandHandler, DynamicCommandHandler, CommandHandlerWrapper};
use crate::shared::query::{Query, QueryHandler, DynamicQueryHandler, QueryHandlerWrapper};
use crate::shared::error::AppError;

#[derive(Default, Clone)]
pub struct CommandBus {
    handlers: Arc<HashMap<TypeId, Box<dyn DynamicCommandHandler>>>,
}

#[derive(Default)]
pub struct CommandBusBuilder {
    handlers: HashMap<TypeId, Box<dyn DynamicCommandHandler>>,
}

impl CommandBusBuilder {
    pub fn new() -> Self {
        Self {
            handlers: HashMap::new(),
        }
    }

    pub fn register<C: Command, H: CommandHandler<C>>(mut self, handler: H) -> Self {
        let type_id = TypeId::of::<C>();
        let wrapper = CommandHandlerWrapper {
            handler,
            _marker: std::marker::PhantomData,
        };
        self.handlers.insert(type_id, Box::new(wrapper));
        self
    }

    pub fn build(self) -> CommandBus {
        CommandBus {
            handlers: Arc::new(self.handlers),
        }
    }
}

impl CommandBus {
    pub fn builder() -> CommandBusBuilder {
        CommandBusBuilder::new()
    }

    pub async fn dispatch<C: Command>(&self, command: C) -> Result<C::Output, AppError> {
        let type_id = TypeId::of::<C>();
        let handler = self.handlers.get(&type_id).ok_or_else(|| {
            AppError::Internal(format!(
                "No CommandHandler registered for command type: {}",
                std::any::type_name::<C>()
            ))
        })?;

        let res_boxed = handler.handle_dyn(Box::new(command)).await?;
        match res_boxed.downcast::<C::Output>() {
            Ok(output) => Ok(*output),
            Err(_) => Err(AppError::Internal(format!(
                "Failed to downcast command output for type: {}",
                std::any::type_name::<C::Output>()
            ))),
        }
    }
}

#[derive(Default, Clone)]
pub struct QueryBus {
    handlers: Arc<HashMap<TypeId, Box<dyn DynamicQueryHandler>>>,
}

#[derive(Default)]
pub struct QueryBusBuilder {
    handlers: HashMap<TypeId, Box<dyn DynamicQueryHandler>>,
}

impl QueryBusBuilder {
    pub fn new() -> Self {
        Self {
            handlers: HashMap::new(),
        }
    }

    pub fn register<Q: Query, H: QueryHandler<Q>>(mut self, handler: H) -> Self {
        let type_id = TypeId::of::<Q>();
        let wrapper = QueryHandlerWrapper {
            handler,
            _marker: std::marker::PhantomData,
        };
        self.handlers.insert(type_id, Box::new(wrapper));
        self
    }

    pub fn build(self) -> QueryBus {
        QueryBus {
            handlers: Arc::new(self.handlers),
        }
    }
}

impl QueryBus {
    pub fn builder() -> QueryBusBuilder {
        QueryBusBuilder::new()
    }

    pub async fn dispatch<Q: Query>(&self, query: Q) -> Result<Q::Output, AppError> {
        let type_id = TypeId::of::<Q>();
        let handler = self.handlers.get(&type_id).ok_or_else(|| {
            AppError::Internal(format!(
                "No QueryHandler registered for query type: {}",
                std::any::type_name::<Q>()
            ))
        })?;

        let res_boxed = handler.handle_dyn(Box::new(query)).await?;
        match res_boxed.downcast::<Q::Output>() {
            Ok(output) => Ok(*output),
            Err(_) => Err(AppError::Internal(format!(
                "Failed to downcast query output for type: {}",
                std::any::type_name::<Q::Output>()
            ))),
        }
    }
}

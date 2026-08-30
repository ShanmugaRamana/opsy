use std::any::Any;
use std::future::Future;
use std::pin::Pin;
use crate::shared::error::AppError;

pub trait Query: Send + Sync + 'static {
    type Output: Send + 'static;
}

pub trait QueryHandler<Q: Query>: Send + Sync + 'static {
    fn handle(&self, query: Q) -> Pin<Box<dyn Future<Output = Result<Q::Output, AppError>> + Send>>;
}

pub(crate) trait DynamicQueryHandler: Send + Sync + 'static {
    fn handle_dyn(&self, query: Box<dyn Any + Send>) -> Pin<Box<dyn Future<Output = Result<Box<dyn Any + Send>, AppError>> + Send>>;
}

pub(crate) struct QueryHandlerWrapper<Q: Query, H: QueryHandler<Q>> {
    pub(crate) handler: H,
    pub(crate) _marker: std::marker::PhantomData<Q>,
}

impl<Q: Query, H: QueryHandler<Q>> DynamicQueryHandler for QueryHandlerWrapper<Q, H> {
    fn handle_dyn(&self, query: Box<dyn Any + Send>) -> Pin<Box<dyn Future<Output = Result<Box<dyn Any + Send>, AppError>> + Send>> {
        match query.downcast::<Q>() {
            Ok(qry) => {
                let fut = self.handler.handle(*qry);
                Box::pin(async move {
                    let res = fut.await?;
                    Ok(Box::new(res) as Box<dyn Any + Send>)
                })
            }
            Err(_) => Box::pin(async {
                Err(AppError::Internal("Downcast failed in DynamicQueryHandler".to_string()))
            }),
        }
    }
}

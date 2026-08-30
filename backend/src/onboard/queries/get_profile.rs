use std::future::Future;
use std::pin::Pin;
use crate::onboard::domain::UserData;
use crate::onboard::infra::storage;
use crate::shared::error::AppError;
use crate::shared::query::{Query, QueryHandler};

pub struct GetProfileQuery;

impl Query for GetProfileQuery {
    type Output = UserData;
}

pub struct GetProfileHandler;

impl QueryHandler<GetProfileQuery> for GetProfileHandler {
    fn handle(&self, _query: GetProfileQuery) -> Pin<Box<dyn Future<Output = Result<UserData, AppError>> + Send>> {
        Box::pin(async move {
            let data = storage::read_user_data();
            Ok(data)
        })
    }
}

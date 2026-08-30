use std::future::Future;
use std::pin::Pin;
use crate::onboard::domain::LlmSuggestion;
use crate::onboard::infra::recommender;
use crate::shared::error::AppError;
use crate::shared::query::{Query, QueryHandler};
use crate::system::domain::SystemSpecs;

pub struct GetRecommendationsQuery {
    pub specs: SystemSpecs,
}

impl Query for GetRecommendationsQuery {
    type Output = Vec<LlmSuggestion>;
}

pub struct GetRecommendationsHandler;

impl QueryHandler<GetRecommendationsQuery> for GetRecommendationsHandler {
    fn handle(&self, query: GetRecommendationsQuery) -> Pin<Box<dyn Future<Output = Result<Vec<LlmSuggestion>, AppError>> + Send>> {
        Box::pin(async move {
            let suggestions = recommender::get_recommendations(&query.specs);
            Ok(suggestions)
        })
    }
}

pub mod get_profile;
pub mod get_recommendations;

pub use get_profile::{GetProfileHandler, GetProfileQuery};
pub use get_recommendations::{GetRecommendationsHandler, GetRecommendationsQuery};

use crate::shared::bus::QueryBusBuilder;

pub fn register_queries(builder: QueryBusBuilder) -> QueryBusBuilder {
    builder
        .register(GetProfileHandler)
        .register(GetRecommendationsHandler)
}

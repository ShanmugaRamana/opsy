pub mod domain;
pub mod commands;
pub mod queries;
pub(crate) mod infra;
pub mod http;

#[allow(unused_imports)]
pub use domain::{ApiKeyConfig, LlmSuggestion, ProgressEvent, UserData};
pub use infra::runner::ActiveProcess;
pub use commands::register_commands;
pub use queries::register_queries;

#[cfg(test)]
mod tests {
    use super::*;
    use crate::shared::bus::{CommandBus, QueryBus};
    use crate::onboard::commands::SaveProfileCommand;
    use crate::onboard::queries::GetProfileQuery;
    use crate::onboard::domain::UserData;

    #[tokio::test]
    async fn test_onboard_cqrs() {
        let query_bus = register_queries(QueryBus::builder()).build();
        let command_bus = register_commands(CommandBus::builder()).build();

        let initial_profile = query_bus.dispatch(GetProfileQuery).await.expect("GetProfile failed");

        let test_profile = UserData {
            onboarded: true,
            username: "test_user".to_string(),
            system_specs: None,
            suggestions: vec![],
            api_key: None,
            active_model: None,
        };

        let saved = command_bus.dispatch(SaveProfileCommand { profile: test_profile.clone() }).await.expect("SaveProfile failed");
        assert_eq!(saved.username, "test_user");

        let fetched = query_bus.dispatch(GetProfileQuery).await.expect("GetProfile failed");
        assert_eq!(fetched.username, "test_user");

        // Restore initial profile
        let _ = command_bus.dispatch(SaveProfileCommand { profile: initial_profile }).await;
    }
}

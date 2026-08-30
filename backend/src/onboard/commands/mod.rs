pub mod save_profile;
pub mod save_api_key;
pub mod pull_model;
pub mod cancel_run;

pub use save_profile::{SaveProfileHandler, SaveProfileCommand};
pub use save_api_key::{SaveApiKeyHandler, SaveApiKeyCommand};
pub use pull_model::{PullModelHandler, PullModelCommand};
pub use cancel_run::{CancelRunHandler, CancelRunCommand};

use crate::shared::bus::CommandBusBuilder;

pub fn register_commands(builder: CommandBusBuilder) -> CommandBusBuilder {
    builder
        .register(SaveProfileHandler)
        .register(SaveApiKeyHandler)
        .register(PullModelHandler)
        .register(CancelRunHandler)
}

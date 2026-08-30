use serde::{Deserialize, Serialize};
use crate::system::domain::SystemSpecs;

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct LlmSuggestion {
    pub name: String,
    pub size: String,
    pub description: String,
    pub gpu_accel: String,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct ApiKeyConfig {
    pub provider: String,
    pub key: String,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct UserData {
    pub onboarded: bool,
    pub username: String,
    pub system_specs: Option<SystemSpecs>,
    pub suggestions: Vec<LlmSuggestion>,
    pub api_key: Option<ApiKeyConfig>,
    pub active_model: Option<String>,
}

#[derive(Serialize, Clone, Debug)]
pub struct ProgressEvent {
    pub status: String,
    pub percentage: u32,
    pub message: String,
}

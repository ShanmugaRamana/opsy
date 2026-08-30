use crate::onboard::domain::{ApiKeyConfig, UserData};
use crate::onboard::infra::storage::{read_user_data, write_user_data};
use crate::shared::error::AppError;

pub fn save_provider_api_key(provider: String, key: String) -> Result<UserData, AppError> {
    let mut data = read_user_data();
    if key.is_empty() {
        data.api_key = None;
    } else {
        data.api_key = Some(ApiKeyConfig { provider, key });
    }
    
    write_user_data(&data)
        .map_err(|e| AppError::Internal(format!("Failed to write api key: {}", e)))?;
        
    Ok(data)
}

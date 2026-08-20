use std::fs::File;
use std::io::{Read, Write};
use std::path::Path;
use super::types::UserData;

const STORAGE_FILE: &str = "user_data.json";

pub fn read_user_data() -> UserData {
    let path = Path::new(STORAGE_FILE);
    if !path.exists() {
        return UserData {
            onboarded: false,
            username: String::new(),
            system_specs: None,
            suggestions: Vec::new(),
            api_key: None,
            active_model: None,
        };
    }

    let file = match File::open(path) {
        Ok(f) => f,
        Err(_) => return UserData {
            onboarded: false,
            username: String::new(),
            system_specs: None,
            suggestions: Vec::new(),
            api_key: None,
            active_model: None,
        },
    };

    let mut content = String::new();
    let mut reader = std::io::BufReader::new(file);
    if reader.read_to_string(&mut content).is_err() {
        return UserData {
            onboarded: false,
            username: String::new(),
            system_specs: None,
            suggestions: Vec::new(),
            api_key: None,
            active_model: None,
        };
    }

    serde_json::from_str(&content).unwrap_or_else(|_| UserData {
        onboarded: false,
        username: String::new(),
        system_specs: None,
        suggestions: Vec::new(),
        api_key: None,
        active_model: None,
    })
}

pub fn write_user_data(data: &UserData) -> Result<(), std::io::Error> {
    let content = serde_json::to_string_pretty(data)?;
    let mut file = File::create(STORAGE_FILE)?;
    file.write_all(content.as_bytes())?;
    Ok(())
}

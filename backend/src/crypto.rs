use aes_gcm::aead::{Aead, KeyInit, OsRng};
use aes_gcm::{Aes256Gcm, Nonce};
use base64::engine::general_purpose::STANDARD as BASE64;
use base64::Engine;
use rand::RngCore;
use std::fs;
use std::path::PathBuf;
use tracing::info;

fn secret_key_path() -> PathBuf {
    let home = std::env::var("HOME").unwrap_or_else(|_| "/tmp".to_string());
    PathBuf::from(home).join(".local/share/opsy/secret.key")
}

fn load_or_create_key() -> [u8; 32] {
    let path = secret_key_path();
    if path.exists() {
        if let Ok(bytes) = fs::read(&path) {
            if bytes.len() >= 32 {
                let mut key = [0u8; 32];
                key.copy_from_slice(&bytes[..32]);
                return key;
            }
        }
    }

    if let Some(parent) = path.parent() {
        let _ = fs::create_dir_all(parent);
    }

    let mut key = [0u8; 32];
    OsRng.fill_bytes(&mut key);
    let _ = fs::write(&path, &key);
    info!("Generated new secret key at {:?}", path);
    key
}

pub fn encrypt(plaintext: &str) -> Result<String, String> {
    let key_bytes = load_or_create_key();
    let cipher = Aes256Gcm::new_from_slice(&key_bytes).map_err(|e| e.to_string())?;

    let mut nonce_bytes = [0u8; 12];
    OsRng.fill_bytes(&mut nonce_bytes);
    let nonce = Nonce::from_slice(&nonce_bytes);

    let ciphertext = cipher
        .encrypt(nonce, plaintext.as_bytes())
        .map_err(|e| e.to_string())?;

    let mut combined = nonce_bytes.to_vec();
    combined.extend(ciphertext);
    Ok(BASE64.encode(combined))
}

pub fn decrypt(ciphertext: &str) -> Result<String, String> {
    let key_bytes = load_or_create_key();
    let cipher = Aes256Gcm::new_from_slice(&key_bytes).map_err(|e| e.to_string())?;

    let combined = BASE64.decode(ciphertext).map_err(|e| e.to_string())?;
    if combined.len() < 12 {
        return Err("Invalid ciphertext length".to_string());
    }

    let (nonce_bytes, encrypted) = combined.split_at(12);
    let nonce = Nonce::from_slice(nonce_bytes);

    let decrypted = cipher
        .decrypt(nonce, encrypted)
        .map_err(|e| e.to_string())?;

    String::from_utf8(decrypted).map_err(|e| e.to_string())
}

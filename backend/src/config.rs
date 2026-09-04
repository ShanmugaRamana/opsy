use std::env;

#[derive(Clone, Debug)]
pub struct Config {
    pub host: String,
    pub port: u16,
    pub db_host: String,
    pub db_port: u16,
    pub db_name: String,
    pub db_user: String,
    pub db_pass: String,
    pub ollama_base_url: String,
}

impl Config {
    pub fn from_env() -> Self {
        let _ = dotenvy::dotenv();

        let host = env::var("HOST").unwrap_or_else(|_| "0.0.0.0".to_string());
        let port = env::var("PORT")
            .ok()
            .and_then(|p| p.parse().ok())
            .unwrap_or(8008);

        let db_host = env::var("SUPABASE_DB_HOST").unwrap_or_else(|_| "localhost".to_string());
        let db_port = env::var("SUPABASE_DB_PORT")
            .ok()
            .and_then(|p| p.parse().ok())
            .unwrap_or(5432);
        let db_name = env::var("SUPABASE_DB_NAME").unwrap_or_else(|_| "postgres".to_string());
        let db_user = env::var("SUPABASE_DB_USER").unwrap_or_else(|_| "postgres".to_string());
        let db_pass = env::var("SUPABASE_DB_PASSWORD").unwrap_or_default();
        let ollama_base_url = env::var("OLLAMA_BASE_URL").unwrap_or_else(|_| "http://127.0.0.1:11434".to_string());

        Self {
            host,
            port,
            db_host,
            db_port,
            db_name,
            db_user,
            db_pass,
            ollama_base_url,
        }
    }

    pub fn database_url(&self) -> String {
        format!(
            "postgres://{}:{}@{}:{}/{}",
            self.db_user, self.db_pass, self.db_host, self.db_port, self.db_name
        )
    }
}

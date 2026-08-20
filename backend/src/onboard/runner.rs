use std::process::Stdio;
use tokio::process::Command;
use tokio::io::{AsyncBufReadExt, BufReader};
use tokio::sync::mpsc::Sender;
use serde::Serialize;
use std::sync::Arc;
use tokio::sync::Mutex;
use tokio::sync::oneshot;

#[derive(Serialize, Clone, Debug)]
pub struct ProgressEvent {
    pub status: String,
    pub percentage: u32,
    pub message: String,
}

pub type ActiveProcess = Arc<Mutex<Option<oneshot::Sender<()>>>>;

const ALL_AVAILABLE_MODELS: &[(&str, &str)] = &[
    ("qwen 2.5 0.5b", "qwen2.5:0.5b"),
    ("qwen 2.5 1.5b", "qwen2.5:1.5b"),
    ("qwen 2.5 3b", "qwen2.5:3b"),
    ("qwen 2.5 7b", "qwen2.5:7b"),
    ("qwen 2.5 14b", "qwen2.5:14b"),
    ("qwen 2.5 72b", "qwen2.5:72b"),
    ("llama 3.2 1b", "llama3.2:1b"),
    ("llama 3.2 3b", "llama3.2:3b"),
    ("llama 3 8b", "llama3"),
    ("llama 3.3 70b", "llama3.3"),
    ("gemma 2 2b", "gemma2:2b"),
    ("gemma 2 9b", "gemma2:9b"),
    ("phi 3.5 mini", "phi3.5"),
    ("mistral 7b", "mistral"),
    ("mistral nemo 12b", "mistral-nemo"),
    ("codestral 22b", "codestral"),
    ("command r 35b", "command-r"),
    ("command r+ 104b", "command-r-plus"),
    ("mixtral 8x7b", "mixtral"),
    ("smollm2 1.7b", "smollm2:1.7b"),
];

fn get_ollama_tag(model_name: &str) -> &'static str {
    let name_lower = model_name.to_lowercase();
    for (key, tag) in ALL_AVAILABLE_MODELS {
        if name_lower.contains(key) {
            return tag;
        }
    }
    "llama3.2:3b" // Default fallback
}

pub async fn run_install_and_pull(
    model_name: String,
    tx: Sender<ProgressEvent>,
    active_proc: ActiveProcess,
) {
    let ollama_tag = get_ollama_tag(&model_name);

    // 1. Check if Ollama is installed
    let _ = tx.send(ProgressEvent {
        status: "checking".to_string(),
        percentage: 0,
        message: "Checking if Ollama is installed...".to_string(),
    }).await;

    let has_ollama = Command::new("which")
        .arg("ollama")
        .output()
        .await
        .map(|o| o.status.success())
        .unwrap_or(false);

    if !has_ollama {
        let _ = tx.send(ProgressEvent {
            status: "installing".to_string(),
            percentage: 5,
            message: "Ollama not found. Running installer...".to_string(),
        }).await;

        // Setup oneshot cancel channel for installation step
        let (cancel_tx, mut cancel_rx) = oneshot::channel::<()>();
        {
            let mut guard = active_proc.lock().await;
            *guard = Some(cancel_tx);
        }

        let install_cmd = Command::new("sh")
            .arg("-c")
            .arg("curl -fsSL https://ollama.com/install.sh | sh")
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn();

        match install_cmd {
            Ok(mut child) => {
                let stdout = child.stdout.take();
                let mut reader = stdout.map(|s| BufReader::new(s).lines());
                let mut progress = 5;
                let mut cancelled = false;

                if let Some(ref mut lines_reader) = reader {
                    loop {
                        tokio::select! {
                            line_res = lines_reader.next_line() => {
                                match line_res {
                                    Ok(Some(line)) => {
                                        progress = std::cmp::min(progress + 3, 90);
                                        let _ = tx.send(ProgressEvent {
                                            status: "installing".to_string(),
                                            percentage: progress,
                                            message: format!("Installing Ollama: {}", line),
                                        }).await;
                                    }
                                    _ => break,
                                }
                            }
                            _ = &mut cancel_rx => {
                                let _ = child.kill().await;
                                cancelled = true;
                                break;
                            }
                        }
                    }
                }

                if cancelled {
                    let _ = tx.send(ProgressEvent {
                        status: "failed".to_string(),
                        percentage: 0,
                        message: "Installation cancelled by user.".to_string(),
                    }).await;
                    return;
                }

                // Wait for exit
                let success = tokio::select! {
                    status_res = child.wait() => {
                        status_res.map(|s| s.success()).unwrap_or(false)
                    }
                    _ = &mut cancel_rx => {
                        let _ = child.kill().await;
                        false
                    }
                };

                if !success {
                    let _ = tx.send(ProgressEvent {
                        status: "failed".to_string(),
                        percentage: 0,
                        message: "Failed to install Ollama. You may need manual sudo installation.".to_string(),
                    }).await;
                    return;
                }
            }
            Err(e) => {
                let _ = tx.send(ProgressEvent {
                    status: "failed".to_string(),
                    percentage: 0,
                    message: format!("Failed to start installation command: {}", e),
                }).await;
                return;
            }
        }
    }

    // Check if cancellation happened between steps
    {
        let guard = active_proc.lock().await;
        if guard.is_none() && !has_ollama {
            // Cancelled in step 1
            return;
        }
    }

    // 2. Start the model download/pull
    let _ = tx.send(ProgressEvent {
        status: "downloading".to_string(),
        percentage: 0,
        message: format!("Starting download of {}...", ollama_tag),
    }).await;

    // Setup oneshot cancel channel for download step
    let (cancel_tx, mut cancel_rx) = oneshot::channel::<()>();
    {
        let mut guard = active_proc.lock().await;
        *guard = Some(cancel_tx);
    }

    let pull_cmd = Command::new("ollama")
        .arg("pull")
        .arg(ollama_tag)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn();

    match pull_cmd {
        Ok(mut child) => {
            let stderr = child.stderr.take();
            let mut reader = stderr.map(|s| BufReader::new(s).lines());
            let mut cancelled = false;

            if let Some(ref mut lines_reader) = reader {
                loop {
                    tokio::select! {
                        line_res = lines_reader.next_line() => {
                            match line_res {
                                Ok(Some(line)) => {
                                    let clean_line = line.trim();
                                    if clean_line.is_empty() {
                                        continue;
                                    }

                                    let mut pct = 0;
                                    let mut found_pct = false;

                                    if let Some(pct_idx) = clean_line.find('%') {
                                        let mut start = pct_idx;
                                        while start > 0 {
                                            let prev_char = clean_line.chars().nth(start - 1).unwrap_or(' ');
                                            if prev_char.is_ascii_digit() {
                                                start -= 1;
                                            } else {
                                                break;
                                            }
                                        }
                                        if start < pct_idx {
                                            if let Ok(val) = clean_line[start..pct_idx].parse::<u32>() {
                                                pct = val;
                                                found_pct = true;
                                            }
                                        }
                                    }

                                    let _ = tx.send(ProgressEvent {
                                        status: "downloading".to_string(),
                                        percentage: if found_pct { pct } else { 0 },
                                        message: clean_line.to_string(),
                                    }).await;
                                }
                                _ => break,
                            }
                        }
                        _ = &mut cancel_rx => {
                            let _ = child.kill().await;
                            cancelled = true;
                            break;
                        }
                    }
                }
            }

            if cancelled {
                let _ = tx.send(ProgressEvent {
                    status: "failed".to_string(),
                    percentage: 0,
                    message: "Download cancelled by user.".to_string(),
                }).await;
                return;
            }

            let success = tokio::select! {
                status_res = child.wait() => {
                    status_res.map(|s| s.success()).unwrap_or(false)
                }
                _ = &mut cancel_rx => {
                    let _ = child.kill().await;
                    false
                }
            };

            if success {
                let _ = tx.send(ProgressEvent {
                    status: "completed".to_string(),
                    percentage: 100,
                    message: format!("Successfully pulled and initialized model {}!", ollama_tag),
                }).await;

                // Save model to user profile
                let mut data = super::read_user_data();
                data.active_model = Some(model_name.clone());
                let _ = super::write_user_data(&data);
            } else {
                let _ = tx.send(ProgressEvent {
                    status: "failed".to_string(),
                    percentage: 0,
                    message: "Download process returned an error status.".to_string(),
                }).await;
            }
        }
        Err(e) => {
            let _ = tx.send(ProgressEvent {
                status: "failed".to_string(),
                percentage: 0,
                message: format!("Failed to spawn download process: {}", e),
            }).await;
        }
    }

    // Reset process state
    {
        let mut guard = active_proc.lock().await;
        *guard = None;
    }
}

pub async fn cancel_active_process(active_proc: ActiveProcess) -> Result<(), String> {
    let mut guard = active_proc.lock().await;
    if let Some(cancel_tx) = guard.take() {
        let _ = cancel_tx.send(());
        Ok(())
    } else {
        Err("No active download or installation process to cancel.".to_string())
    }
}

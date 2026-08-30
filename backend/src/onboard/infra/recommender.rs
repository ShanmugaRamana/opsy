use crate::system::domain::SystemSpecs;
use crate::onboard::domain::LlmSuggestion;

pub fn get_recommendations(specs: &SystemSpecs) -> Vec<LlmSuggestion> {
    let ram = specs.ram.total_gb;
    let mut suggestions = Vec::new();

    let has_gpu = !specs.gpus.is_empty();
    let mut gpu_brand = String::new();
    if has_gpu {
        gpu_brand = specs.gpus[0].vendor.clone();
    }

    let gpu_acceleration = if has_gpu {
        format!("Supported (Accel: {})", gpu_brand)
    } else {
        "None (CPU Only)".to_string()
    };

    if ram < 4.0 {
        suggestions.push(LlmSuggestion {
            name: "Qwen 2.5 0.5B (Q4_K_M)".to_string(),
            size: "Ultra-Light (~0.35GB VRAM/RAM)".to_string(),
            description: "Extremely small model optimized to run on devices with very limited memory. Fast CPU execution.".to_string(),
            gpu_accel: gpu_acceleration.clone(),
        });
        suggestions.push(LlmSuggestion {
            name: "Qwen 2.5 1.5B (Q4_K_M)".to_string(),
            size: "Ultra-Light (~1.0GB VRAM/RAM)".to_string(),
            description: "A great balance of minimal footprint and basic text reasoning capabilities.".to_string(),
            gpu_accel: gpu_acceleration.clone(),
        });
        suggestions.push(LlmSuggestion {
            name: "Llama 3.2 1B (Q4_K_M)".to_string(),
            size: "Very Small (~0.8GB VRAM/RAM)".to_string(),
            description: "Meta's highly optimized small model, perfect for summarization and low-resource tasks.".to_string(),
            gpu_accel: gpu_acceleration.clone(),
        });
        suggestions.push(LlmSuggestion {
            name: "SmolLM2 1.7B (Q4_K_M)".to_string(),
            size: "Very Small (~1.1GB VRAM/RAM)".to_string(),
            description: "High-quality small model trained on highly curated educational data.".to_string(),
            gpu_accel: gpu_acceleration.clone(),
        });
    } else if ram >= 4.0 && ram < 8.0 {
        suggestions.push(LlmSuggestion {
            name: "Llama 3.2 3B (Q4_K_M)".to_string(),
            size: "Light (~2.0GB VRAM/RAM)".to_string(),
            description: "Meta's state-of-the-art lightweight model for general reasoning, writing, and instructions.".to_string(),
            gpu_accel: gpu_acceleration.clone(),
        });
        suggestions.push(LlmSuggestion {
            name: "Gemma 2 2B (Q4_K_M)".to_string(),
            size: "Light (~1.6GB VRAM/RAM)".to_string(),
            description: "Google's highly efficient open model with strong reasoning, logic, and safety features.".to_string(),
            gpu_accel: gpu_acceleration.clone(),
        });
        suggestions.push(LlmSuggestion {
            name: "Qwen 2.5 3B (Q4_K_M)".to_string(),
            size: "Light (~2.2GB VRAM/RAM)".to_string(),
            description: "A powerful multilingual model with solid coding capabilities and conversational skills.".to_string(),
            gpu_accel: gpu_acceleration.clone(),
        });
        suggestions.push(LlmSuggestion {
            name: "Phi 3.5 Mini (3.8B)".to_string(),
            size: "Light (~2.6GB VRAM/RAM)".to_string(),
            description: "Microsoft's small language model with outstanding coding, logic, and mathematics capabilities.".to_string(),
            gpu_accel: gpu_acceleration.clone(),
        });
    } else if ram >= 8.0 && ram < 16.0 {
        suggestions.push(LlmSuggestion {
            name: "Llama 3 8B (Q4_K_M)".to_string(),
            size: "Medium (~4.8GB VRAM/RAM)".to_string(),
            description: "Meta's standard model for conversations, coding helper, and complex instructions.".to_string(),
            gpu_accel: gpu_acceleration.clone(),
        });
        suggestions.push(LlmSuggestion {
            name: "Mistral 7B (Q4_K_M)".to_string(),
            size: "Medium (~4.5GB VRAM/RAM)".to_string(),
            description: "A classic high-performance 7B parameter model with highly balanced general capability.".to_string(),
            gpu_accel: gpu_acceleration.clone(),
        });
        suggestions.push(LlmSuggestion {
            name: "Qwen 2.5 7B (Q4_K_M)".to_string(),
            size: "Medium (~4.7GB VRAM/RAM)".to_string(),
            description: "Exceptional multilingual capabilities, strong tool usage, and general coding logic.".to_string(),
            gpu_accel: gpu_acceleration.clone(),
        });
        suggestions.push(LlmSuggestion {
            name: "Gemma 2 9B (Q4_K_M)".to_string(),
            size: "Medium (~5.5GB VRAM/RAM)".to_string(),
            description: "Highly rated 9B model that matches or outperforms many larger configurations.".to_string(),
            gpu_accel: gpu_acceleration.clone(),
        });
    } else if ram >= 16.0 && ram < 32.0 {
        suggestions.push(LlmSuggestion {
            name: "Qwen 2.5 14B (Q4_K_M)".to_string(),
            size: "Heavy (~9.0GB VRAM/RAM)".to_string(),
            description: "Excellent intermediate option offering complex multi-step reasoning and deep knowledge.".to_string(),
            gpu_accel: gpu_acceleration.clone(),
        });
        suggestions.push(LlmSuggestion {
            name: "Mistral Nemo 12B (Q4_K_M)".to_string(),
            size: "Heavy (~8.0GB VRAM/RAM)".to_string(),
            description: "Co-developed with NVIDIA. Features large 128k context support and strong translation.".to_string(),
            gpu_accel: gpu_acceleration.clone(),
        });
        suggestions.push(LlmSuggestion {
            name: "Codestral 22B (Q4_K_M)".to_string(),
            size: "Heavy (~14GB VRAM/RAM)".to_string(),
            description: "Mistral's highly specialized model optimized specifically for coding in 80+ languages.".to_string(),
            gpu_accel: gpu_acceleration.clone(),
        });
        suggestions.push(LlmSuggestion {
            name: "Command R 35B (Q4_K_M)".to_string(),
            size: "Heavy (~22GB VRAM/RAM)".to_string(),
            description: "Cohere's business model optimized for Retrieval Augmented Generation (RAG) and tool usage.".to_string(),
            gpu_accel: gpu_acceleration.clone(),
        });
    } else {
        suggestions.push(LlmSuggestion {
            name: "Llama 3.3 70B (Q4_K_M)".to_string(),
            size: "Extreme (~42GB VRAM/RAM)".to_string(),
            description: "Meta's flagship SOTA model. Matches top commercial APIs in reasoning and task automation.".to_string(),
            gpu_accel: gpu_acceleration.clone(),
        });
        suggestions.push(LlmSuggestion {
            name: "Qwen 2.5 72B (Q4_K_M)".to_string(),
            size: "Extreme (~45GB VRAM/RAM)".to_string(),
            description: "Top-tier open-weight model with exceptional coding skills and mathematical logic.".to_string(),
            gpu_accel: gpu_acceleration.clone(),
        });
        suggestions.push(LlmSuggestion {
            name: "Mixtral 8x7B (Q4_K_M)".to_string(),
            size: "Extreme (~26GB VRAM/RAM)".to_string(),
            description: "High-quality Mixture of Experts (MoE) model with fast inference times for its scale.".to_string(),
            gpu_accel: gpu_acceleration.clone(),
        });
        suggestions.push(LlmSuggestion {
            name: "Command R+ 104B (Q4_K_M)".to_string(),
            size: "Extreme (~65GB VRAM/RAM)".to_string(),
            description: "Massive scale model designed for multi-step agents and advanced corporate automation.".to_string(),
            gpu_accel: gpu_acceleration.clone(),
        });
    }

    suggestions
}

# Zyros: AI-Powered Linux Operations Assistant Using Natural Language Queries

Zyros is an intelligent, privacy-first desktop assistant designed specifically for Linux. It translates natural language questions and administrative requests into real-time Linux system diagnostics, inspection reports, and operations without requiring users to memorize complex terminal syntax or manually parse terminal commands.

---

## Key Features

- **Natural Language System Diagnostics**: Query OS specifications, Linux kernel versions, RAM usage, storage breakdown, open ports, network interfaces, and running processes using everyday conversational prompts.
- **Direct System Inspection**: Directly observes your system in real time and provides factual, actionable answers rather than generic tutorial steps.
- **High-Performance Rust Backend**: Built with Axum, Tokio, SQLx, and native Linux diagnostic tooling for ultra-fast, lightweight execution.
- **Flexible Model Provider Support**:
  - **Local Models (Ollama)**: Full offline privacy with local LLMs (e.g. Qwen, LLaMA, Gemma).
  - **Bring Your Own Key (BYOK)**: Securely encrypted cloud API key integration for OpenAI, Anthropic, Gemini, and Groq.
- **Hardware-Aware Recommendations**: Automatically inspects available CPU, RAM, and GPU hardware to recommend the optimal local AI model tier.
- **Persistent Sessions & History**: Stores conversational history, multi-turn diagnostics, and session state in PostgreSQL.

---

## Project Architecture

```
opsy/
├── app/                  # Desktop application GUI runner (PyWebView / WebKitGTK)
│   ├── main.py           # Main window & lifecycle manager
│   └── screens/          # Application window templates (e.g., splash screen)
├── backend/              # High-performance Rust backend (Axum + Tokio + SQLx)
│   ├── src/
│   │   ├── main.rs       # Server entrypoint & routing (Port 8008)
│   │   ├── system_tools.rs # Linux system context & inspection engine
│   │   ├── crypto.rs     # AES-GCM BYOK API key encryption
│   │   ├── db.rs         # PostgreSQL connection pool & schema migrations
│   │   └── routers/      # Orchestrator, Hardware, BYOK, Sessions, Models
│   └── Cargo.toml
├── frontend/             # Desktop UI client & Express server (Port 3000)
│   ├── index.js          # Express static & template server
│   ├── views/            # EJS template views (Home, Onboarding, Settings, etc.)
│   └── public/           # Client-side JavaScript, CSS styles, and media assets
└── README.md
```

---

## Prerequisites

- **Linux OS** (Arch Linux, Ubuntu, Debian, Fedora, etc.)
- **Rust** (1.75+ / `cargo`)
- **Node.js** (v18+) & `npm`
- **Python 3.10+** (with `pywebview` and WebKitGTK bindings)
- **PostgreSQL** (running locally or via Supabase/cloud instance)
- *(Optional)* **Ollama** installed and running for local LLM inference

---

## Getting Started

### 1. Configure Environment Variables
Create or verify your `.env` file in the project root:

```env
HOST=0.0.0.0
PORT=8008
DB_HOST=localhost
DB_PORT=5432
DB_NAME=postgres
DB_USER=postgres
DB_PASSWORD=yourpassword
ENCRYPTION_KEY=your-32-byte-hex-key-here
OLLAMA_BASE_URL=http://localhost:11434
```

### 2. Launching Zyros

You can launch the complete Zyros desktop environment with a single command:

```bash
cd app
./venv/bin/python main.py
```

*This will automatically launch the Rust backend on port `8008`, the frontend server on port `3000`, and present the native Zyros desktop window.*

---

## Running Individual Services (Development Mode)

If you prefer to run services in separate terminals:

1. **Rust Backend Server** (Port `8008`):
   ```bash
   cd backend
   cargo run --release
   ```

2. **Frontend UI Server** (Port `3000`):
   ```bash
   cd frontend
   npm install
   npm start
   ```

---

## Contributing

Contributions are welcome! Please check out our [Contributing Guidelines](CONTRIBUTING.md) to get started.

---

## License

Distributed under the Apache License 2.0. See [LICENSE](LICENSE) for more information.

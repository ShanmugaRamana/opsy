# Contributing to Zyros

Thank you for your interest in contributing to **Zyros: AI-Powered Linux Operations Assistant Using Natural Language Queries**! 

We welcome contributions of all kinds: bug reports, documentation improvements, feature requests, system inspection tool additions, and code changes.

---

## Code of Conduct

Please be respectful, constructive, and considerate when participating in discussions, issue threads, and pull requests.

---

## How Can I Contribute?

### 1. Reporting Bugs
- Search existing issues before creating a new one.
- Provide a clear and descriptive title.
- Include detailed steps to reproduce the issue, your Linux distribution, kernel version, and terminal logs where applicable.

### 2. Suggesting Features & System Tools
- Describe the feature or Linux diagnostic command you would like Zyros to support.
- Explain why this capability would be beneficial for Linux system administration or desktop users.

### 3. Submitting Code Changes (Pull Requests)

1. **Fork the repository** on GitHub.
2. **Clone your fork** locally:
   ```bash
   git clone https://github.com/<your-username>/opsy.git
   cd opsy
   ```
3. **Create a topic branch** from `main`:
   ```bash
   git checkout -b feature/your-feature-name
   ```
4. **Make your changes**:
   - For backend changes (Rust): Ensure your code formats and compiles cleanly (`cargo check` / `cargo build`).
   - For frontend changes: Test with the Express server and desktop GUI.
5. **Commit your changes** with clear commit messages:
   ```bash
   git commit -m "feat(backend): add network routing diagnostics"
   ```
6. **Push to your branch**:
   ```bash
   git push origin feature/your-feature-name
   ```
7. **Open a Pull Request** against the `main` branch with a description of your changes.

---

## Development Guidelines

- **Rust Backend**: Located in `backend/`. Adhere to idiomatic Rust standards and ensure no unhandled panics occur in diagnostic routines.
- **System Commands**: Ensure all inspection commands in `system_tools.rs` are **safe and read-only**. Zyros should never run destructive or unapproved modifying operations.
- **Frontend / UI**: Located in `frontend/`. Keep styling clean, responsive, and aligned with modern dark-mode aesthetic standards.

---

## License

By contributing to Zyros, you agree that your contributions will be licensed under the [Apache License 2.0](LICENSE).

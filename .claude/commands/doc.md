# CLAUDE.md — Global Project Instructions

## Project Context

This project combines:
- **Python** as the main backend / business logic layer
- **HTML + optional JS/CSS** as the browser-based UI
- **An Android smartphone running PAW Server** as both the web server and a bridge to device hardware (storage, sensors, network)

---

## Documentation Task

When asked to document this project, generate a **single, complete `/doc` file** in clear technical English.

### Required Sections

1. **Project Overview & Purpose**
   - What the system does and the real-world problem it solves
   - Main features and user flows (browser → PAW → Python)
   - How the phone, HTML UI, and Python scripts work together

2. **High-Level Architecture & Tech Stack**
   - Textual architecture diagram (phone/PAW, HTTP, routing, Python)
   - What runs on the Android device vs. another machine
   - All technologies and versions (Python libs, HTML/JS/CSS, PAW Server, Termux, APIs, etc.)

3. **Setup & Installation**
   - Prerequisites: Android version, PAW install, permissions, Wi-Fi config
   - Deploying HTML files into the PAW `/html` directory
   - Where Python scripts live and how PAW pages call them (HTTP / shell)
   - Step-by-step: get the full system running on a new phone and dev machine

4. **Configuration & Environment**
   - Config files and environment variables (IP/port, API keys, Python paths)
   - PAW configuration: port, root folders, security, user accounts
   - Dev vs. production notes (local network vs. internet exposure)

5. **Module / Code-Level Documentation**
   - Each Python module: responsibilities, key functions, parameters, return values, usage examples
   - Each HTML page / UI component: purpose, UI elements, which Python/PAW functions it calls
   - Shared utilities and helpers
   - Complex logic explained with code snippets and sequence descriptions

6. **Interaction with Android via PAW**
   - How the project accesses device features (files, sensors, logs) via PAW handlers/plugins
   - URL paths, query parameters, and scripts bridging HTML ↔ PAW ↔ Python
   - Security and permission considerations (Wi-Fi only, auth, port forwarding, NAT)

7. **Data & Storage**
   - Where data lives: local phone files, external storage, database, or remote services
   - Data model / schema (tables, JSON structures, file formats)
   - Full data flow: browser input → PAW → Python → storage → back to user

8. **Testing**
   - Running automated Python tests (pytest / unittest commands)
   - Manually testing HTML pages and PAW routes from desktop browser and phone
   - Test data or demo mode if available

9. **Deployment & Operations**
   - Updating the project: copying HTML files, updating Python scripts, restarting PAW
   - Backup and restore procedures for config and data
   - Logs location (Python logs, PAW logs), common errors, and fixes

10. **Security, Performance & Limitations**
    - Access control, recommended network setup, HTTPS / VPN recommendations
    - Known PAW limitations (Wi-Fi only, beta status, Android constraints)
    - Performance considerations and optimizations (caching, lightweight pages)

11. **Known Issues, Roadmap & Future Work**
    - Current bugs or incomplete features with workarounds
    - Planned improvements (pure Python migration, authentication, database storage)

12. **Glossary & External References**
    - Key terms: PAW server, HTML app, backend script, etc.
    - Links to PAW docs, Android permissions, Python libraries

---

## Documentation Style Rules

- Use **headings, subheadings, bullet lists, and code blocks** throughout
- Be **thorough and explicit** — document every major file, module, script, and design decision
- When something is not obvious from the code, **make a reasonable assumption and mark it clearly**: `> ⚠️ Assumption: ...`
- Code examples should be minimal but complete enough to illustrate the point

---

## Coding Conventions

- **Python**: follow PEP 8; use type hints where practical; log with the `logging` module
- **HTML/JS**: keep pages lightweight (PAW runs on phone hardware); avoid heavy frameworks
- **PAW scripts**: prefer HTTP calls to Python over shell execution where possible
- **Paths**: use relative paths inside the PAW `/html` root; document any absolute paths explicitly

---

## /doc — Documentation Generation

### Trigger
Only generate `/doc` output **when explicitly asked** (e.g. "generate the doc", "write /doc", "update the documentation").
Never generate it automatically on code changes or session start.

### Output Format
When `/doc` is requested, produce **two files** every time:

| File | Location |
|------|----------|
| `PROJECT_DOC.md` | Project root **and** `/docs/PROJECT_DOC.md` **and** inline summary inside `CLAUDE.md` under a `## Generated Doc Summary` heading |
| `PROJECT_DOC.pdf` | Same three locations as above |

Generate both files in a single pass. If PDF generation is not possible in the current environment, produce the `.md` first and note the limitation clearly.

### Inline CLAUDE.md Summary
After generating the full doc, append (or update) a short `## Generated Doc Summary` section at the bottom of `CLAUDE.md` containing:
- Date/time of generation
- List of modules and HTML pages documented
- Any `⚠️ Assumption:` items flagged during generation

### Content Rules
- Follow all 12 required sections listed in **Documentation Task** above
- Use the actual file and module names from the codebase — no generic placeholders
- Mark every gap or unclear item with `> ⚠️ Assumption: ...`
- Keep the PDF visually clean: use a table of contents, page numbers, and code blocks with monospace font

---

## When the Codebase Is Provided

If a repo link or file tree is given, **adapt every section above to use the actual file and module names** from the codebase instead of generic placeholders.

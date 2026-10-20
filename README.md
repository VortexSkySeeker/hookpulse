<div align="center">

# ⚡ HookPulse

**Interactive Terminal (TUI) Webhook & API Request Debugger for Python Developers**

Capture incoming webhooks (Stripe, GitHub, Telegram, Svix, or any HTTP request), inspect syntax-highlighted JSON payloads, **replay requests to your `localhost` with a single keystroke (`r`)**, and **auto-generate ready-to-use `Pydantic v2` models (`p`)** without leaving your terminal.

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Built with Textual](https://img.shields.io/badge/TUI-Textual-purple.svg)](https://github.com/Textualize/textual)
[![Code Style: PEP 8](https://img.shields.io/badge/code%20style-PEP%208-orange.svg)](https://peps.python.org/pep-0008/)

[**English**](README.md) | [**Русский**](README.ru.md)

<br>

![HookPulse Interactive TUI Demo](assets/demo.gif)

</div>

## Why HookPulse?

Testing webhooks locally shouldn't require spinning up heavy desktop REST clients, digging through unformatted `stdout` logs, or manually writing boilerplate `BaseModel` classes for nested 50-field JSON payloads from Stripe or GitHub.

* **Instant One-Key Replay (`r`):** Forward any captured request (preserving headers, cryptographic signatures, query params, and raw body) straight to your local FastAPI / Django / Flask / Litestar service and see the HTTP status code and latency in milliseconds.
* **Automatic `Pydantic v2` Code Generation (`p`):** Recursively inspects any captured JSON body and generates clean, nested `Pydantic v2` `BaseModel` classes (handling `Optional` fields, typed lists, and reserved Python keywords with `Field(alias=...)`).
* **Smart Provider Detection:** Automatically badges incoming events from **Stripe**, **GitHub** (including event name like `GitHub:push`), **Telegram**, and **Svix**.
* **One-Key `cURL` Export (`c`):** Copy a properly escaped, ready-to-run `curl` command to reproduce any webhook in CI or share with teammates.
* **Built-in Demo Mode (`--demo` or `d`):** Preloaded with realistic Stripe, GitHub, and Telegram webhook payloads so you can test the UI and schema generator immediately.

## Quick Start

### 1. Run Locally from Source (Zero Setup)

Clone the repository and install dependencies:

```bash
git clone https://github.com/YOUR_USERNAME/hookpulse.git
cd hookpulse
pip install -e .
```

Launch **HookPulse** with realistic sample webhooks (Stripe, GitHub, Telegram):

```bash
python -m hookpulse.cli --demo
```

Or run the single-file standalone script directly:

```bash
python hookpulse.py --demo
```

### 2. Run via `uvx` Directly from GitHub (or PyPI once published)

```bash
uvx --from git+https://github.com/YOUR_USERNAME/hookpulse hookpulse --demo
```

Once published to PyPI under `hookpulse`:

```bash
uvx hookpulse --port 9000 --target http://localhost:8000
```

## How to Test Live Webhook Capture & Replay

1. Start **HookPulse** listening on port `9000` and forwarding replays to `localhost:8000`:
   ```bash
   python hookpulse.py --port 9000 --target http://localhost:8000
   ```
2. Open a second terminal and send a test webhook:
   ```bash
   curl -X POST http://localhost:9000/webhooks/stripe \
     -H "Content-Type: application/json" \
     -H "Stripe-Signature: t=1729412400,v1=demo" \
     -d '{"event": "payment_intent.succeeded", "amount": 4900, "currency": "usd"}'
   ```
3. In **HookPulse**, select the newly captured row and press:
   - **`p`** to copy the generated `Pydantic v2` schema to your clipboard.
   - **`r`** to replay the request to `http://localhost:8000/webhooks/stripe`.
   - **`c`** to copy the full `cURL` command.

## Keyboard Shortcuts

| Key | Action | Description |
| :--- | :--- | :--- |
| `r` | **Replay Request** | Re-sends the selected webhook to `--target` (e.g., `http://localhost:8000`) and records HTTP status & latency |
| `p` | **Copy Pydantic v2** | Generates nested `Pydantic v2` models from the JSON body and copies them to your clipboard |
| `c` | **Copy cURL** | Copies a complete `curl -X ...` command with headers and payload |
| `d` | **Load Demo Webhooks** | Injects sample Stripe, GitHub, and Telegram webhooks into the live feed |
| `s` | **Save History** | Exports all captured requests in the current session to `hookpulse_history.json` |
| `x` | **Clear Feed** | Clears all captured requests from the table |
| `q` | **Quit** | Exits HookPulse |

## CLI Options

| Flag | Default | Description |
| :--- | :--- | :--- |
| `-p`, `--port` | `9000` | Local port where HookPulse listens for incoming webhooks |
| `--host` | `0.0.0.0` | Host interface to bind the listener server |
| `-t`, `--target` | `http://localhost:8000` | Target local server base URL where requests are replayed |
| `--demo` | `False` | Preloads sample Stripe, GitHub, and Telegram webhooks on launch |
| `--schema-from-file` | `None` | Headless mode: reads a `.json` file, prints `Pydantic v2` models to `stdout`, and exits |

## Pair with Any Tunnel (Cloudflare / ngrok / SSH)

Expose your local HookPulse listener to external webhook providers in one command:

```bash
python hookpulse.py --port 9000 --target http://localhost:8000
```

In a second terminal:

```bash
cloudflared tunnel --url http://localhost:9000
```

Every webhook sent to your tunnel URL is captured in **HookPulse**, ready to be inspected, converted into Pydantic schemas, and replayed to `localhost:8000` as many times as you need while editing your handler code.

## Running Tests

```bash
python -m unittest discover -s tests -v
```

## License

Released under the [MIT License](LICENSE).

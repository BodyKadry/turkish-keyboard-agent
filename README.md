# Turkish Keyboard Agent

A Windows desktop AI agent for correcting selected Turkish text anywhere you can copy and paste text. The app has a modern PySide6 UI, system tray controls, settings management, live logs, and the original global hotkey correction workflow.

Select Turkish text in any Windows app, press the configured hotkey, and the agent sends only that selected text to the configured Ollama API. It receives corrected Turkish text and pastes it back into the same place.

```text
Input: dunku yemek cok guzeldi
Output: dünkü yemek çok güzeldi
```

## Features

- Modern dark Windows desktop UI.
- System tray menu with Show Window, Start Agent, Stop Agent, and Exit.
- Start and stop controls for the global hotkey agent.
- Status indicator: Running, Stopped, Correcting..., Error.
- WhatsApp-style Correction Chat using the same `TextCorrector` and Ollama path as the hotkey system.
- Persistent chat history in `data/chat_history.json`.
- Settings editor for hotkey, Ollama API key, base URL, model, timeout, copy delay, paste delay, and loading overlay.
- Live log viewer inside the app.
- Open Data Folder, Open Logs, and Clear Logs buttons.
- Clipboard-based selected text capture and replacement.
- Animated loading overlay while correction is running when `SHOW_LOADING_OVERLAY=true`.
- Local learning files for custom dictionary hints and recent correction examples.

## How It Works

1. Open the app with `python main.py`.
2. Click **Start Agent**.
3. Select Turkish text in another Windows app.
4. Press the configured hotkey, `Ctrl + Alt + T` by default.
5. The app copies only the selected text using the clipboard.
6. The text, recent examples, and custom dictionary hints are sent to `{OLLAMA_BASE_URL}/generate`.
7. The corrected Turkish text is validated and pasted over the selection.
8. The loading overlay, clipboard, and hotkey state are restored after success, failure, timeout, or skipped correction.

## Installation

Use Python 3.10 or newer.

```powershell
cd "c:\Users\bodym\Desktop\Cahit Hoca\turkish-keyboard-agent - Copy"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Configure `.env`

Create your local `.env` file:

```powershell
Copy-Item .env.example .env
```

Minimum Ollama settings:

```env
OLLAMA_API_KEY=your_ollama_api_key_here
OLLAMA_BASE_URL=https://ollama.com/api
OLLAMA_MODEL=gpt-oss:120b
OLLAMA_TIMEOUT_SECONDS=60
```

Common app settings:

```env
HOTKEY=ctrl+alt+t
COPY_DELAY=0.2
PASTE_DELAY=0.2
SHOW_LOADING_OVERLAY=true
```

`SHOW_BUSY_CURSOR` is still accepted for backward compatibility, but new settings should use `SHOW_LOADING_OVERLAY`. The UI can also edit and save these settings. The API key field is treated as a secret and should not be printed in logs.

## Run In Development

```powershell
python main.py
```

The UI opens first. Click **Start Agent** to register the global hotkey. Closing the window hides it to the tray; use the tray menu **Exit** action to stop the listener and quit.

## Use The UI

- **Start Agent** registers the hotkey listener.
- **Stop Agent** unregisters the hotkey listener.
- **Correction Chat** lets you send short Turkish text and see corrected replies as chat bubbles.
- **Send** submits the chat message; Enter sends, and Shift+Enter adds a new line.
- **Clear Chat** clears the visible conversation and `data/chat_history.json`.
- **Save Settings** writes the current UI settings to `.env` and reloads the agent configuration.
- **Open Data Folder** opens `data/`, which contains learning files.
- **Open Logs** opens `logs/`.
- **Clear Logs** clears `logs/app.log` and the live viewer.

Chat example:

```text
dunku yemek cok guzeldi
```

Expected output:

```text
dünkü yemek çok güzeldi
```

Chat messages are restored when the app restarts. Only the latest 200 messages are stored.

## Learning Files

The app does not fine-tune the model. It uses lightweight local learning data:

- `data/custom_dictionary.json` stores direct word or phrase hints.
- `data/corrections.json` stores recent successful correction examples.
- `data/chat_history.json` stores Correction Chat messages.
- Recent examples are included in the Ollama prompt to improve consistency.
- Saved examples may include Turkish character restoration, spelling correction, typo fixes, and simple grammar correction.

## Logs

Logs are written to:

```text
logs/app.log
```

The UI also shows recent log lines in the live log viewer. API keys are not intentionally logged; when displayed, they should be masked.

## Build EXE

Install dependencies first, then run:

```powershell
.\build.bat
```

The build script runs PyInstaller through Python so it also works when `pyinstaller.exe` is not on PATH:

```powershell
python -m PyInstaller --noconfirm --clean --windowed --name "TurkishKeyboardAgent" main.py
```

It also includes hidden imports, `data/`, `.env.example`, and `README.md`. It does **not** include your real `.env` file or API key.

If `app.ico` exists in the project root, the build uses it:

```text
--icon app.ico
```

The EXE output appears at:

```text
dist/TurkishKeyboardAgent/TurkishKeyboardAgent.exe
```

## Windows Permissions And Safety

- Some apps may require running Turkish Keyboard Agent as Administrator for global hotkeys to work.
- Some protected apps may block simulated `Ctrl + C`, `Ctrl + V`, or clipboard automation.
- Antivirus tools may warn because the app uses global hotkeys, clipboard automation, and PyInstaller packaging.
- The selected text is sent to the configured Ollama API endpoint. If you use Ollama Cloud, the selected text leaves your machine and is handled by that service.

## Troubleshooting

- **Hotkey not working:** Click **Start Agent**, check the hotkey setting, and try running as Administrator for elevated/protected apps.
- **No selected text found:** Make sure text is actually selected and the target app allows `Ctrl + C`.
- **OLLAMA_API_KEY is not set:** Add it in the Settings panel or `.env`, then click **Save Settings**.
- **Loading overlay stuck:** Restart the app or set `SHOW_LOADING_OVERLAY=false`.
- **Correction returns original text:** Check the live logs for Ollama API errors, timeouts, or rejected model output.
- **Antivirus warning after build:** This can happen with PyInstaller apps that use hotkeys and clipboard automation. Build locally from source and review the code before allowing it.

## Project Structure

```text
main.py
app_ui.py
agent_controller.py
settings_manager.py
loading_overlay.py
chat_store.py
clipboard_manager.py
hotkey_listener.py
corrector.py
ollama_client.py
learning_store.py
config.py
logger.py
requirements.txt
README.md
.env.example
build.bat
data/
logs/
```

# Bureau
A terminal wrangling dashboard

## Features
* Python + Textual interface
* Spawn terminals and track and manage them via PIDs
* Adjust and remember terminal window arrangements
* Remember "Favorite" terminals and group them
* Command/text injection into terminals
* Glean status from terminals and display it in the dashboard (working, waiting, idle, memory/CPU usage, etc.)
* Search/filter sessions in real time
* Export/import configurations as JSON
* Runs on Windows, macOS, and Linux (including Raspberry Pi OS)

## Install

```bash
python -m pip install -e .

# Windows additionally needs:
python -m pip install pywin32
```

## Run

```bash
python -m termdash
```

## Keybindings

| Key | Action |
|-----|--------|
| `Ctrl+N` | Spawn new terminal |
| `Ctrl+K` | Kill selected session |
| `Ctrl+F` | Focus (bring to foreground) |
| `Ctrl+I` | Inject text into terminal |
| `Ctrl+S` | Save session as favorite |
| `Ctrl+G` | Launch a group |
| `Ctrl+L` | Capture window layout |
| `/` | Filter sessions |
| `Esc` | Back to session table |
| `Ctrl+R` | Refresh |
| `Ctrl+Q` | Quit |

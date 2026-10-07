# Claude Lights

A small always-on-top traffic light that shows what Claude Code is doing:

| Light  | Meaning                                          |
|--------|--------------------------------------------------|
| Green  | Claude is working                                |
| Yellow | Claude is waiting for you (e.g. a permission prompt) |
| Red    | Claude is done / idle                            |

Claude Code hooks call `set_state.py`, which writes the state to a temp file;
`hud.py` watches that file and lights the matching lamp.

## Requirements

- Python 3 with Tkinter and Pillow
- **Windows:** `pip install pillow`
- **Linux (X11):**
  ```bash
  sudo apt install -y python3-tk python3-pil.imagetk
  ```

## Setup

```bash
git clone https://github.com/ramazan-karatas/claude_lights.git
cd claude_lights
python3 install.py
```

`install.py` adds the hooks to your `~/.claude/settings.json`, pointing at
this folder. Your existing settings are kept, and a backup is saved as
`settings.json.bak`. Run it again if you move the folder. On Windows use
`python` instead of `python3`.

Then start the light:

```bash
python3 hud.py
```

The hooks take effect in Claude Code sessions started after installing.

To remove the hooks:

```bash
python3 install.py --uninstall
```

## Controls

- **Drag** to move (position is remembered)
- **Mouse wheel** or **Ctrl + drag** to resize
- **Hover** to show the handle below the light: drag the arrow to resize,
  click the gear for settings
- **Right-click** for a menu (settings, size, center, close)

Settings include two designs (Classic, Liquid glass), two themes (Black,
White), always-on-top, pulse animation, position lock and a status caption.

## Linux notes

- Needs X11 or XWayland.
- Soft shadows aren't drawn, and Liquid glass uses a flat gray backdrop
  instead of the blurred desktop.

## License

MIT, see [LICENSE](LICENSE).

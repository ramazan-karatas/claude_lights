# -*- coding: utf-8 -*-
"""
Claude Code hooklarini kullanicinin ~/.claude/settings.json dosyasina ekler.

    python3 install.py              # hooklari kur (ya da yollari guncelle)
    python3 install.py --uninstall  # hooklari kaldir

Var olan ayarlar korunur; yalnizca set_state.py'yi cagiran hooklar eklenir ya
da degistirilir. Tekrar calistirmak guvenli: eski kayitlar yenisiyle
degistirilir, ust uste binmez. Degistirmeden once dosyanin yedegi alinir.
"""
import os
import sys
import json
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
SET_STATE = os.path.join(HERE, "set_state.py")
SETTINGS = os.path.join(os.path.expanduser("~"), ".claude", "settings.json")

# olay -> (matcher, durum)
EVENTS = {
    "UserPromptSubmit": (None, "green"),
    "PreToolUse": ("*", "green"),
    "PostToolUse": ("*", "green"),
    "Notification": (None, "yellow"),
    "Stop": (None, "red"),
}


def command(state):
    # Bu betigi calistiran Python ile ayni; yollardaki bosluklar icin tirnakli
    return '"%s" "%s" %s' % (sys.executable, SET_STATE, state)


def ours(group):
    return any("set_state.py" in h.get("command", "") for h in group.get("hooks", []))


def main():
    uninstall = "--uninstall" in sys.argv[1:]

    settings = {}
    if os.path.exists(SETTINGS):
        with open(SETTINGS, "r", encoding="utf-8") as f:
            text = f.read()
        if text.strip():
            try:
                settings = json.loads(text)
            except ValueError as e:
                sys.exit("%s okunamadi (gecersiz JSON): %s" % (SETTINGS, e))
        shutil.copy2(SETTINGS, SETTINGS + ".bak")

    hooks = settings.setdefault("hooks", {})
    for event, (matcher, state) in EVENTS.items():
        # once eski kayitlarimizi cikar (yol degismis olabilir)
        groups = [g for g in hooks.get(event, []) if not ours(g)]
        if not uninstall:
            group = {"hooks": [{"type": "command", "command": command(state)}]}
            if matcher:
                group = {"matcher": matcher, **group}
            groups.append(group)
        if groups:
            hooks[event] = groups
        else:
            hooks.pop(event, None)
    if not hooks:
        settings.pop("hooks")

    os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
    tmp = SETTINGS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")
    os.replace(tmp, SETTINGS)

    if uninstall:
        print("Hooks removed from %s" % SETTINGS)
    else:
        print("Hooks installed in %s" % SETTINGS)
        print("Start the light with: \"%s\" \"%s\"" % (sys.executable, os.path.join(HERE, "hud.py")))


if __name__ == "__main__":
    main()

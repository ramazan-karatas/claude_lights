# -*- coding: utf-8 -*-
"""
Durum yazan minik yardimci. Hooklar bunu cagirir:

    python set_state.py green
    python set_state.py yellow "Onay bekliyor"   <- istege bagli ozel etiket

Etiket verilmezse HUD kendi varsayilan yazisini gosterir.
"""
import os
import sys
import tempfile

STATE_FILE = os.path.join(tempfile.gettempdir(), "cc_hud_state.txt")
VALID = ("green", "yellow", "red")

state = sys.argv[1].strip().lower() if len(sys.argv) > 1 else "red"
if state not in VALID:
    state = "red"

label = " ".join(sys.argv[2:]).strip().replace("|", " ").replace("\n", " ")
payload = state + ("|" + label if label else "")

# Once gecici dosyaya yaz, sonra yerine koy: HUD yarim yazilmis dosyayi
# okuyup bir anligina kirmiziya dusmesin.
tmp = STATE_FILE + ".tmp"
with open(tmp, "w", encoding="utf-8") as f:
    f.write(payload)
os.replace(tmp, STATE_FILE)

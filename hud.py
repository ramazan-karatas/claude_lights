# -*- coding: utf-8 -*-
r"""
Claude Code HUD - yesil / sari / kirmizi durum gostergesi.

Ekranin ustunde duran, her zaman en onde, surukleyebildiginiz kucuk bir pencere.
State dosyasini (%TEMP%\cc_hud_state.txt) surekli okur; hooklar oraya
"green" / "yellow" / "red" yazar. Istege bagli olarak "green|Kod yaziyor"
seklinde ozel bir etiket de verilebilir.

  Sol tik + surukle : tasi (konum hatirlanir)
  Sag tik           : menu (Ortala / Kapat)

Pillow varsa yumusak kenarli, golgeli, isildayan bir kart cizilir;
yoksa sade bir tkinter surumune duser.
"""

import os
import sys
import math
import time
import tempfile
import tkinter as tk

try:
    from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageTk
    HAVE_PIL = True
except ImportError:
    HAVE_PIL = False

STATE_FILE = os.path.join(tempfile.gettempdir(), "cc_hud_state.txt")
POS_FILE = os.path.join(tempfile.gettempdir(), "cc_hud_pos.txt")

POLL_MS = 150    # durum dosyasi okuma araligi
FRAME_MS = 33    # ~30 fps animasyon

# Windows'ta bu renk tamamen seffaf olur (kose yuvarlatma bu sayede calisir).
KEY_RGB = (8, 8, 10)
KEY_HEX = "#08080a"

# Kart olculeri (mantiksal piksel; DPI'ya gore olceklenir)
MARGIN = 6       # kenar payi
CARD_W = 198
CARD_H = 46
RADIUS = 23      # tam hap (pill) formu

CARD_TOP = (28, 29, 34)
CARD_BOTTOM = (18, 19, 23)
TEXT_RGB = (232, 233, 238)

STATES = {
    "green":  {"label": "Çalışıyor",      "rgb": (40, 214, 126), "pulse": 0.55, "bars": True},
    "yellow": {"label": "Girdi bekliyor", "rgb": (247, 199, 46), "pulse": 1.20, "bars": False},
    "red":    {"label": "Boşta",          "rgb": (228, 78, 72),  "pulse": 0.00, "bars": False},
}


def read_state():
    """(state, label) dondurur. Dosya "green" veya "green|Ozel yazi" olabilir."""
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            raw = f.read().strip()
    except Exception:
        return "red", None
    if not raw:
        return "red", None
    parts = raw.split("|", 1)
    state = parts[0].strip().lower()
    if state not in STATES:
        return "red", None
    label = parts[1].strip() if len(parts) > 1 and parts[1].strip() else None
    return state, label


def blend(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def enable_dpi_awareness():
    if sys.platform != "win32":
        return
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)   # per-monitor
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def load_font(px):
    fonts_dir = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    for name in ("seguisb.ttf", "segoeuib.ttf", "segoeui.ttf", "arial.ttf"):
        path = os.path.join(fonts_dir, name)
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, px)
            except Exception:
                pass
    return ImageFont.load_default()


def draw_tracked(draw, xy, text, font, fill, tracking):
    """Harf araligi biraz acilmis metin - daha ferah gorunuyor."""
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill, anchor="lm")
        x += draw.textlength(ch, font=font) + tracking


class Renderer:
    """Kartin tum gorsel isini yapar; agir parcalari onbellekler."""

    def __init__(self, scale):
        self.scale = scale
        self.font = load_font(self.s(12))
        self.iw = self.s(CARD_W + 2 * MARGIN)
        self.ih = self.s(CARD_H + 2 * MARGIN)
        self.cx = self.s(MARGIN + 26)          # isik merkezi
        self.cy = self.s(MARGIN + CARD_H / 2)
        self.core_r = self.s(6.5)
        self.halo_r = self.s(18)
        self.text_x = self.s(MARGIN + 44)
        self.base = self._build_base()
        self._plates = {}
        self._halo_masks = {}
        self._glow = {}
        self._cores = {}
        self._halo_base = self._build_halo_mask()

    def s(self, v):
        return int(round(v * self.scale))

    # ---------- statik kart ----------

    def _build_base(self):
        # Not: Windows renk anahtari yari saydamlik desteklemedigi icin
        # gercek bir golge cizilemiyor; kenar yumusatmasi zaten ince koyu
        # bir kenarlik birakiyor ve acik zeminde de temiz duruyor.
        img = Image.new("RGB", (self.iw, self.ih), KEY_RGB)

        w, h = self.s(CARD_W), self.s(CARD_H)
        ss = 4

        # hap maskesi (supersample -> yumusak kenar)
        mask = Image.new("L", (w * ss, h * ss), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            [0, 0, w * ss - 1, h * ss - 1], radius=self.s(RADIUS) * ss, fill=255)
        mask = mask.resize((w, h), Image.LANCZOS)

        # dikey degrade govde
        card = Image.new("RGB", (w, h), CARD_BOTTOM)
        d = ImageDraw.Draw(card)
        for y in range(h):
            d.line([(0, y), (w, y)], fill=blend(CARD_TOP, CARD_BOTTOM, y / max(1, h - 1)))
        card = card.convert("RGBA")
        card.putalpha(mask)

        # ince cerceve
        ring = Image.new("L", (w * ss, h * ss), 0)
        ImageDraw.Draw(ring).rounded_rectangle(
            [0, 0, w * ss - 1, h * ss - 1], radius=self.s(RADIUS) * ss,
            outline=255, width=max(2, ss))
        ring = ring.resize((w, h), Image.LANCZOS)

        border = Image.new("RGBA", (w, h), (255, 255, 255, 0))
        border.putalpha(ring.point(lambda v: v * 34 // 255))
        card = Image.alpha_composite(card, border)

        # ust kenarda hafif isik cizgisi
        fade = Image.new("L", (w, h), 0)
        fd = ImageDraw.Draw(fade)
        cut = max(1, int(h * 0.45))
        for y in range(cut):
            fd.line([(0, y), (w, y)], fill=int(255 * (1 - y / cut) ** 2))
        gloss = Image.new("RGBA", (w, h), (255, 255, 255, 0))
        gloss.putalpha(ImageChops.multiply(ring, fade).point(lambda v: v * 60 // 255))
        card = Image.alpha_composite(card, gloss)

        img.paste(card, (self.s(MARGIN), self.s(MARGIN)), card)
        return img

    def plate(self, label):
        """Kart + metin (etikete gore onbellekli)."""
        img = self._plates.get(label)
        if img is None:
            img = self.base.copy()
            d = ImageDraw.Draw(img)
            draw_tracked(d, (self.text_x, self.cy + self.s(0.5)), label,
                         self.font, TEXT_RGB, max(0.4, 0.35 * self.scale))
            if len(self._plates) > 24:
                self._plates.clear()
            self._plates[label] = img
        return img

    # ---------- isik ----------

    def _build_halo_mask(self):
        r = self.halo_r
        size = r * 2
        ss = 2
        mask = Image.new("L", (size * ss, size * ss), 0)
        px = mask.load()
        rr = r * ss
        core = self.core_r * ss * 0.95
        for y in range(size * ss):
            dy = y - rr + 0.5
            for x in range(size * ss):
                dx = x - rr + 0.5
                dist = math.hypot(dx, dy)
                if dist >= rr:
                    continue
                t = max(0.0, (dist - core) / max(1.0, rr - core))
                px[x, y] = int(255 * (1 - t) ** 3.1)
        mask = mask.resize((size, size), Image.LANCZOS)
        return mask.filter(ImageFilter.GaussianBlur(self.scale * 0.9))

    def _halo(self, step):
        m = self._halo_masks.get(step)
        if m is None:
            k = step / 20.0
            m = self._halo_base.point(lambda v: int(v * k))
            self._halo_masks[step] = m
        return m

    def glow(self, rgb, step):
        key = (rgb, step)
        img = self._glow.get(key)
        if img is None:
            mask = self._halo(step)
            img = Image.new("RGBA", mask.size, rgb + (0,))
            img.putalpha(mask)
            if len(self._glow) > 260:
                self._glow.clear()
            self._glow[key] = img
        return img

    def core(self, rgb):
        img = self._cores.get(rgb)
        if img is not None:
            return img
        r = self.core_r
        size = r * 2 + 2
        ss = 4
        mask = Image.new("L", (size * ss, size * ss), 0)
        ImageDraw.Draw(mask).ellipse(
            [ss, ss, (size - 1) * ss, (size - 1) * ss], fill=255)
        mask = mask.resize((size, size), Image.LANCZOS)

        top = blend(rgb, (255, 255, 255), 0.30)
        bottom = blend(rgb, (0, 0, 0), 0.14)
        grad = Image.new("RGB", (size, size), bottom)
        d = ImageDraw.Draw(grad)
        for y in range(size):
            d.line([(0, y), (size, y)], fill=blend(top, bottom, y / max(1, size - 1)))
        img = grad.convert("RGBA")
        img.putalpha(mask)

        # ust-solda kucuk parlama
        spec = Image.new("L", (size * ss, size * ss), 0)
        ImageDraw.Draw(spec).ellipse(
            [int(size * ss * 0.22), int(size * ss * 0.14),
             int(size * ss * 0.74), int(size * ss * 0.52)], fill=95)
        spec = spec.resize((size, size), Image.LANCZOS)
        spec = spec.filter(ImageFilter.GaussianBlur(max(1, self.scale)))
        layer = Image.new("RGBA", (size, size), (255, 255, 255, 0))
        layer.putalpha(ImageChops.multiply(spec, mask))
        img = Image.alpha_composite(img, layer)

        if len(self._cores) > 120:
            self._cores.clear()
        self._cores[rgb] = img
        return img

    # ---------- kare ----------

    def frame(self, label, rgb, intensity, bar_phase):
        img = self.plate(label).copy()

        step = max(0, min(20, int(round(intensity * 20))))
        halo = self.glow(rgb, step)
        img.paste(halo, (self.cx - halo.width // 2, self.cy - halo.height // 2), halo)
        core = self.core(rgb)
        img.paste(core, (self.cx - core.width // 2, self.cy - core.height // 2), core)

        if bar_phase is not None:
            self._bars(img, rgb, bar_phase)
        return img

    def _bars(self, img, rgb, phase):
        d = ImageDraw.Draw(img)
        color = blend((25, 26, 30), rgb, 0.85)
        bw = self.s(3)
        gap = self.s(4)
        x = self.s(MARGIN + CARD_W - 34)
        for i in range(3):
            k = 0.5 + 0.5 * math.sin(phase * 2 * math.pi * 1.5 + i * 2.1)
            h = self.s(5) + int(self.s(13) * k)
            y0 = self.cy - h // 2
            d.rounded_rectangle([x, y0, x + bw, y0 + h],
                                radius=bw / 2, fill=color)
            x += bw + gap


class HUD:
    def __init__(self):
        enable_dpi_awareness()
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=KEY_HEX)

        try:
            self.scale = max(1.0, min(2.5, self.root.winfo_fpixels("1i") / 96.0))
        except Exception:
            self.scale = 1.0

        if HAVE_PIL and sys.platform == "win32":
            try:
                self.root.attributes("-transparentcolor", KEY_HEX)
            except tk.TclError:
                pass

        self.state, self.label = read_state()
        self.rgb = STATES[self.state]["rgb"]
        self.target = self.rgb
        self._photo = None
        self._sig = None
        self._t0 = time.perf_counter()

        if HAVE_PIL:
            self.renderer = Renderer(self.scale)
            self.view = tk.Label(self.root, bd=0, highlightthickness=0, bg=KEY_HEX)
            self.view.pack()
            w, h = self.renderer.iw, self.renderer.ih
        else:
            self.renderer = None
            w, h = int(200 * self.scale), int(56 * self.scale)
            self.view = tk.Canvas(self.root, width=w, height=h,
                                  bg="#16171b", highlightthickness=0)
            self.view.pack()
            pad = int(14 * self.scale)
            self.f_light = self.view.create_oval(
                pad, h // 2 - int(13 * self.scale),
                pad + int(26 * self.scale), h // 2 + int(13 * self.scale),
                fill="#e44e48", outline="")
            self.f_text = self.view.create_text(
                pad + int(38 * self.scale), h // 2, anchor="w", fill="#e8e9ee",
                font=("Segoe UI Semibold", int(11 * self.scale)), text="Boşta")

        self._place(w, h)
        self._bind()
        self.root.deiconify()
        self.poll()
        self.animate()

    # ---------- pencere ----------

    def _place(self, w, h):
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x, y = (sw - w) // 2, int(6 * self.scale)
        try:
            with open(POS_FILE, "r", encoding="utf-8") as f:
                px, py = (int(v) for v in f.read().split(","))
            if -w + 40 < px < sw - 40 and -20 < py < sh - 20:
                x, y = px, py
        except Exception:
            pass
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def _bind(self):
        self.view.bind("<Button-1>", self._grab)
        self.view.bind("<B1-Motion>", self._drag)
        self.view.bind("<ButtonRelease-1>", self._save_pos)
        self.view.bind("<Button-3>", self._popup)

        self.menu = tk.Menu(self.root, tearoff=0, bd=0, relief="flat",
                            bg="#1b1c20", fg="#e8e9ee",
                            activebackground="#2c2e36", activeforeground="#ffffff",
                            font=("Segoe UI", 9))
        self.menu.add_command(label="Ortala", command=self.center)
        self.menu.add_separator()
        self.menu.add_command(label="Kapat", command=self.root.destroy)

    def _popup(self, e):
        try:
            self.menu.tk_popup(e.x_root, e.y_root)
        finally:
            self.menu.grab_release()

    def _grab(self, e):
        self._dx, self._dy = e.x, e.y

    def _drag(self, e):
        x = self.root.winfo_x() + e.x - self._dx
        y = self.root.winfo_y() + e.y - self._dy
        self.root.geometry(f"+{x}+{y}")

    def _save_pos(self, _e=None):
        try:
            with open(POS_FILE, "w", encoding="utf-8") as f:
                f.write(f"{self.root.winfo_x()},{self.root.winfo_y()}")
        except Exception:
            pass

    def center(self):
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() - self.root.winfo_width()) // 2
        self.root.geometry(f"+{x}+{int(6 * self.scale)}")
        self._save_pos()

    # ---------- dongu ----------

    def poll(self):
        state, label = read_state()
        if state != self.state or label != self.label:
            self.state, self.label = state, label
            self.target = STATES[state]["rgb"]
        self.root.after(POLL_MS, self.poll)

    def animate(self):
        cfg = STATES[self.state]
        if self.rgb != self.target:
            self.rgb = blend(self.rgb, self.target, 0.22)
            if max(abs(a - b) for a, b in zip(self.rgb, self.target)) <= 1:
                self.rgb = self.target

        t = time.perf_counter() - self._t0
        pulse = cfg["pulse"]
        if pulse:
            k = 0.5 + 0.5 * math.sin(2 * math.pi * pulse * t)
            lo, hi = (0.55, 0.92) if self.state == "green" else (0.38, 1.0)
            intensity = lo + (hi - lo) * k
        else:
            intensity = 0.30

        label = self.label or cfg["label"]

        if self.renderer:
            phase = t if cfg["bars"] else None
            rgbq = tuple(v & ~3 for v in self.rgb)
            sig = (label, rgbq, int(intensity * 20),
                   None if phase is None else int(phase * 60))
            if sig != self._sig:
                self._sig = sig
                img = self.renderer.frame(label, rgbq, intensity, phase)
                self._photo = ImageTk.PhotoImage(img)
                self.view.configure(image=self._photo)
        else:
            hexcol = "#%02x%02x%02x" % self.rgb
            self.view.itemconfig(self.f_light, fill=hexcol)
            self.view.itemconfig(self.f_text, text=label)

        self.root.after(FRAME_MS, self.animate)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    HUD().run()

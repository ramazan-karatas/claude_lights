# -*- coding: utf-8 -*-
r"""
Claude Code HUD - minik bir trafik lambasi.

Ekranin ustunde duran, her zaman en onde, surukleyebildiginiz kucuk bir
sinyal govdesi. State dosyasini (%TEMP%\cc_hud_state.txt) surekli okur;
hooklar oraya "green" / "yellow" / "red" yazar. "green|Ozel yazi"
bicimindeki etiketler de okunur; ayarlardan durum yazisi acilirsa isigin
altinda gosterilir.

  Sol tik + surukle        : tasi (konum hatirlanir)
  Alttaki tutamak          : noktalari surukle = boyutlandir, disli = ayarlar
  Tekerlek                 : boyutlandir
  Ctrl + sol tik + surukle : boyutlandir
  Sag tik                  : menu (Ayarlar / Buyut / Kucult / Normal boyut /
                             Ortala / Kapat)

Fare isigin uzerine gelince altinda kucuk bir tutamac belirir: sol yarisi
ayirici gibi suruklenip boyutu degistirir, sagindaki disli ayarlar panelini
acar. Boyut, konum ve ayarlar hatirlanir.

Gercek bir sinyal diregindeki gibi ustte kirmizi, ortada sari, altta yesil
lamba vardir. Yalnizca sirasi gelen yanar, otekiler sonuk cam gibi kalir;
durum degisince eski lamba soner, yenisi yanar.

Pillow yoksa sade bir tkinter surumune duser (ayarlar paneli, tutamac ve
durum yazisi yalnizca Pillow ile var).
"""

import os
import sys
import json
import math
import time
import tempfile
import tkinter as tk

try:
    from PIL import (Image, ImageChops, ImageDraw, ImageFilter, ImageFont,
                     ImageTk)
    HAVE_PIL = True
except ImportError:
    HAVE_PIL = False

STATE_FILE = os.path.join(tempfile.gettempdir(), "cc_hud_state.txt")
POS_FILE = os.path.join(tempfile.gettempdir(), "cc_hud_pos.txt")
ZOOM_FILE = os.path.join(tempfile.gettempdir(), "cc_hud_zoom.txt")
SETTINGS_FILE = os.path.join(tempfile.gettempdir(), "cc_hud_settings.json")
PID_FILE = os.path.join(tempfile.gettempdir(), "cc_hud.pid")

POLL_MS = 150    # durum dosyasi okuma araligi
FRAME_MS = 33    # ~30 fps animasyon

# Boyut surekli: tek sinir alt/ust uc. Yeniden cizim yalnizca pencerenin tam
# sayi piksel olcusu degistiginde yapiliyor, yani gecisler 1 piksel
# inceliginde ve puruzsuz.
ZOOM_MIN = 0.55
ZOOM_MAX = 3.30
DEFAULT_ZOOM = 1.0
ZOOM_WHEEL = 1.10    # bir tekerlek tiki
ZOOM_MENU = 1.25     # menuden buyut/kucult

# Ayarlar paneli ve varsayilanlari
DEFAULT_SETTINGS = {
    "topmost": True,     # her zaman ustte
    "pulse": True,       # nabiz animasyonu
    "lock": False,       # konumu kilitle
    "label": False,      # durum yazisini goster
}

# Isigin altinda beliren tutamac: solda ayirici noktalari, sagda disli
CHIP_W = 44          # tutamac genisligi
CHIP_H = 13          # tutamac yuksekligi
CHIP_SPLIT = 27      # ayirici ile disli arasindaki cizgi (soldan)
CHIP_GAP = 5         # ustteki ogeyle (isik ya da yazi) tutamac arasi
CHIP_DOT = 1.6       # nokta yaricapi
CHIP_PITCH = 6       # noktalar arasi mesafe
CHIP_SHOW_MS = 320   # uzerine gelince bu kadar bekleyip ac
CHIP_HIDE_MS = 480   # ayrilinca bu kadar bekleyip kapat
CHIP_TOP = (48, 50, 58)
CHIP_BOTTOM = (27, 28, 34)
CHIP_DOT_RGB = (168, 172, 184)
CHIP_GEAR_RGB = (190, 194, 205)

# Durum yazisi: isigin altinda, isikla birlikte buyuyup kuculen bir plaka
CAP_PX = 11          # yazi boyu (boyut orani 1.0'da)
CAP_MIN_PX = 9       # en kucuk boyutta bile okunur kalsin
CAP_GAP = 4          # govdeyle plaka arasi
CAP_MAX_CHARS = 48   # cok uzun ozel etiketler kisaltilir

# Ayarlar paneli
PANEL_W = 232
PANEL_HEAD = 40
PANEL_ROW = 34
PANEL_FOOT = 40
PANEL_PAD = 16
PANEL_GAP = 10       # isikla panel arasi

TEXT_RGB = (233, 234, 240)
MUTED_RGB = (146, 150, 162)
ACCENT_RGB = (52, 211, 153)
LINE_RGB = (48, 50, 58)

UI_FONTS = ("segoeui.ttf", "arial.ttf")
UIB_FONTS = ("seguisb.ttf", "segoeuib.ttf", "segoeui.ttf", "arial.ttf")
ICON_FONTS = ("SegoeIcons.ttf", "segmdl2.ttf")   # Win11 / Win10 simge yazisi
GEAR_GLYPH = "\ue713"
CLOSE_GLYPH = "\ue711"

# Windows'ta bu renk tamamen seffaf olur (kose yuvarlatma bu sayede calisir).
# Sanatta hic olusmayacak bir ton secildi: en koyu yer (6,7,9) oldugundan
# R=5 ve G<R hicbir pikselde cikmaz, yani govdenin icinde delik acilmaz.
KEY_RGB = (5, 4, 7)
KEY_HEX = "#050407"

# Olculer (mantiksal piksel; DPI'ya gore olceklenir)
MARGIN = 6           # kenar payi - kenar yumusatmasi icin
LAMP_R = 6           # lamba yaricapi
LAMP_PITCH = 18      # lamba merkezleri arasi dikey mesafe
BOX_PAD_X = 9        # govde ici yatay pay
BOX_PAD_Y = 9        # govde ici dikey pay
BOX_W = 2 * BOX_PAD_X + 2 * LAMP_R
BOX_H = 2 * BOX_PAD_Y + 2 * LAMP_PITCH + 2 * LAMP_R
BOX_R = 11           # govdenin kose yaricapi
BLOOM_R = 13         # yanan lambanin dagilma yaricapi

BOX_TOP = (34, 36, 42)
BOX_BOTTOM = (16, 17, 21)
LAMP_OFF = (9, 10, 13)          # sonuk lambanin karistigi koyu ton

# Gercek bir trafik lambasindaki gibi: kirmizi ustte, yesil altta.
LAMP_ORDER = ("red", "yellow", "green")

STATES = {
    "red":    {"label": "Boşta",          "rgb": (240, 92, 88),
               "pulse": 0.00, "idx": 0},
    "yellow": {"label": "Girdi bekliyor", "rgb": (250, 198, 54),
               "pulse": 1.15, "idx": 1},
    "green":  {"label": "Çalışıyor",      "rgb": (52, 211, 153),
               "pulse": 0.45, "idx": 2},
}
LAMP_RGB = tuple(STATES[name]["rgb"] for name in LAMP_ORDER)


def read_state():
    """(durum, etiket) dondurur. Dosya "green" ya da "green|Ozel yazi" olabilir."""
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
    label = parts[1].strip() if len(parts) > 1 else ""
    return state, (label or None)


def read_settings():
    """Kayitli ayarlar; eksik ya da bozuk alanlar varsayilana doner."""
    settings = dict(DEFAULT_SETTINGS)
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            for key, value in data.items():
                if key in settings and isinstance(value, bool):
                    settings[key] = value
    except Exception:
        pass
    return settings


def save_settings(settings):
    # Once gecici dosyaya, sonra yerine: yarim yazilmis dosya kalmasin.
    try:
        tmp = SETTINGS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
        os.replace(tmp, SETTINGS_FILE)
    except Exception:
        pass


# ---------- ortak cizim yardimcilari ----------

_FONTS = {}


def find_font(names):
    fonts_dir = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    for name in names:
        path = os.path.join(fonts_dir, name)
        if os.path.exists(path):
            return path
    return None


def load_font(names, px):
    """Ilk bulunan yazi tipini istenen boyda verir (onbellekli)."""
    key = (names, px)
    font = _FONTS.get(key)
    if font is None:
        path = find_font(names)
        try:
            font = ImageFont.truetype(path, px) if path else ImageFont.load_default()
        except Exception:
            font = ImageFont.load_default()
        _FONTS[key] = font
    return font


def ss_mask(w, h, paint, ss=4):
    """Buyuk cizip kucultulmus maske - kenarlar yumusak kalsin."""
    m = Image.new("L", (w * ss, h * ss), 0)
    paint(ImageDraw.Draw(m), ss)
    return m.resize((w, h), Image.LANCZOS)


def material(w, h, r, top, bottom, edge):
    """Isigin malzemesi: dikey degrade + ustte belirgin, altta sonen kil cizgi."""
    fill = ss_mask(w, h, lambda d, k: d.rounded_rectangle(
        [0, 0, w * k - 1, h * k - 1], radius=r * k, fill=255))
    ring = ss_mask(w, h, lambda d, k: d.rounded_rectangle(
        [0, 0, w * k - 1, h * k - 1], radius=r * k, outline=255, width=max(2, k)))
    body = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(body)
    for y in range(h):
        d.line([(0, y), (w, y)], fill=blend(top, bottom, y / max(1, h - 1)))
    body = body.convert("RGBA")
    body.putalpha(fill)
    if edge:
        fade = Image.new("L", (w, h))
        fd = ImageDraw.Draw(fade)
        for y in range(h):
            fd.line([(0, y), (w, y)], fill=int(255 - 190 * y / max(1, h - 1)))
        hair = Image.new("RGBA", (w, h), (255, 255, 255, 0))
        hair.putalpha(ImageChops.multiply(ring, fade).point(lambda v: v * edge // 255))
        body = Image.alpha_composite(body, hair)
    return body


def draw_icon(img, cx, cy, glyph, px, color):
    """Windows simge yazisindan bir simge; yazi yoksa basit bir cizim."""
    d = ImageDraw.Draw(img)
    if find_font(ICON_FONTS):
        d.text((cx, cy), glyph, font=load_font(ICON_FONTS, px), fill=color,
               anchor="mm")
        return
    r = px * 0.38
    w = max(1, int(round(px * 0.13)))
    if glyph == GEAR_GLYPH:
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=w)
        d.ellipse([cx - r * 0.3, cy - r * 0.3, cx + r * 0.3, cy + r * 0.3],
                  fill=color)
    else:
        d.line([cx - r, cy - r, cx + r, cy + r], fill=color, width=w)
        d.line([cx - r, cy + r, cx + r, cy - r], fill=color, width=w)


def acquire_singleton():
    """Ayni anda tek HUD calissin.

    Ikinci kopya acilmaya calisirsa sessizce cikar; boylece bir baslatici
    (ya da elle acma) ust uste pencere birakamaz. Kilit isletim sistemine
    ait oldugu icin surec cokse bile kendiliginden serbest kalir.
    """
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        # use_last_error olmadan ctypes.get_last_error() hep 0 doner;
        # o yuzden windll yerine acikca WinDLL kuruluyor.
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL,
                                     wintypes.LPCWSTR]
        k32.CreateMutexW.restype = wintypes.HANDLE
        handle = k32.CreateMutexW(None, True, "Local\\cc_hud_singleton")
        if not handle or ctypes.get_last_error() == 183:   # ALREADY_EXISTS
            return None
        return handle

    # diger platformlar: pid dosyasi yeter
    try:
        with open(PID_FILE, "r", encoding="utf-8") as f:
            old = int(f.read().strip())
        os.kill(old, 0)
    except Exception:
        return True          # dosya yok, bozuk ya da surec olmus
    return None


def write_pid():
    """Calisan kopyanin pid'i - hangi pencerenin canli oldugu belli olsun."""
    try:
        with open(PID_FILE, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
    except Exception:
        pass


def clear_pid():
    try:
        if os.path.exists(PID_FILE):
            with open(PID_FILE, "r", encoding="utf-8") as f:
                if int(f.read().strip()) == os.getpid():
                    os.remove(PID_FILE)
    except Exception:
        pass


def read_zoom():
    """Kayitli boyut oranini dondurur."""
    try:
        with open(ZOOM_FILE, "r", encoding="utf-8") as f:
            z = float(f.read().strip())
    except Exception:
        return DEFAULT_ZOOM
    return max(ZOOM_MIN, min(ZOOM_MAX, z))


def window_size(scale):
    """Pencerenin bu olcekteki piksel olcusu - cizer kurmadan hesaplanir."""
    def s(v):
        return int(round(v * scale))
    return s(BOX_W + 2 * MARGIN), s(BOX_H + 2 * MARGIN)


# Bloom ve yikama maskelerinin bicimi olcekle degismiyor (yaricap oranlari
# sabit), yalnizca buyuklugu degisiyor. Bu yuzden her olcek icin pikselleri
# tek tek hesaplamak yerine sabit cozunurlukte bir sablon bir kez uretilip
# istenen boya olcekleniyor - buyuk boyutlarda kurulum cok daha hizli.
TPL_RES = 160
_TEMPLATES = {}


def _radial_template(key, peak, power, core_ratio):
    m = _TEMPLATES.get(key)
    if m is not None:
        return m
    n = TPL_RES
    m = Image.new("L", (n, n), 0)
    px = m.load()
    r = n / 2.0
    core = r * core_ratio
    for y in range(n):
        dy = y - r + 0.5
        for x in range(n):
            dx = x - r + 0.5
            dist = math.hypot(dx, dy)
            if dist >= r:
                continue
            t = max(0.0, (dist - core) / max(1e-6, r - core))
            px[x, y] = int(peak * (1 - t) ** power)
    _TEMPLATES[key] = m
    return m


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


class Renderer:
    """Govdenin tum gorsel isini yapar; agir parcalari onbellekler."""

    def __init__(self, scale):
        self.scale = scale
        self.pad = self.s(MARGIN)
        self.iw = self.s(BOX_W + 2 * MARGIN)
        self.ih = self.s(BOX_H + 2 * MARGIN)
        self.bw = self.iw - 2 * self.pad
        self.bh = self.ih - 2 * self.pad
        self.lamp_r = self.s(LAMP_R)
        self.bloom_r = self.s(BLOOM_R)

        # lamba merkezleri: x sabit, y yukaridan asagi
        self.lx = self.pad + self.s(BOX_PAD_X + LAMP_R)
        self.ly = tuple(self.pad + self.s(BOX_PAD_Y + LAMP_R + i * LAMP_PITCH)
                        for i in range(3))

        self._washes = {}
        self._blooms = {}
        self._lamps = {}
        self._fill = self._round_mask(False)
        self._ring = self._round_mask(True)
        self._bloom_base = self._build_bloom_mask()
        self._wash_base = self._build_wash_mask()
        self._base = self._build_base()

    def s(self, v):
        return int(round(v * self.scale))

    # ---------- govde ----------

    def _round_mask(self, outline):
        w, h, ss = self.bw, self.bh, 4
        r = self.s(BOX_R) * ss
        m = Image.new("L", (w * ss, h * ss), 0)
        box = [0, 0, w * ss - 1, h * ss - 1]
        if outline:
            ImageDraw.Draw(m).rounded_rectangle(
                box, radius=r, outline=255, width=max(2, ss))
        else:
            ImageDraw.Draw(m).rounded_rectangle(box, radius=r, fill=255)
        return m.resize((w, h), Image.LANCZOS)

    def _vgrad(self, top, bottom):
        """Ustten alta duz gecisli gri - maskeleri zayiflatmak icin."""
        g = Image.new("L", (self.bw, self.bh))
        d = ImageDraw.Draw(g)
        for y in range(self.bh):
            t = y / max(1, self.bh - 1)
            d.line([(0, y), (self.bw, y)], fill=int(round(top + (bottom - top) * t)))
        return g

    def _build_base(self):
        """Lambasiz sinyal govdesi - yukaridan isik alan kati bir cisim."""
        w, h = self.bw, self.bh

        body = Image.new("RGB", (w, h))
        d = ImageDraw.Draw(body)
        for y in range(h):
            t = (y / max(1, h - 1)) ** 0.82
            d.line([(0, y), (w, y)], fill=blend(BOX_TOP, BOX_BOTTOM, t))
        body = body.convert("RGBA")
        body.putalpha(self._fill)

        # kil payi cerceve: ustte belirgin, altta neredeyse yok
        border = Image.new("RGBA", (w, h), (255, 255, 255, 0))
        border.putalpha(ImageChops.multiply(self._ring, self._vgrad(255, 58))
                        .point(lambda v: v * 54 // 255))
        body = Image.alpha_composite(body, border)

        # ust kenarda ince isik cizgisi
        fade = Image.new("L", (w, h), 0)
        fd = ImageDraw.Draw(fade)
        cut = max(1, int(h * 0.26))
        for y in range(cut):
            fd.line([(0, y), (w, y)], fill=int(255 * (1 - y / cut) ** 2.2))
        gloss = Image.new("RGBA", (w, h), (255, 255, 255, 0))
        gloss.putalpha(ImageChops.multiply(self._ring, fade)
                       .point(lambda v: v * 72 // 255))
        body = Image.alpha_composite(body, gloss)

        # Not: Windows renk anahtari yari saydamlik desteklemedigi icin
        # gercek bir golge cizilemiyor; kenar yumusatmasi zaten ince koyu
        # bir kenarlik birakiyor ve acik zeminde de temiz duruyor.
        img = Image.new("RGB", (self.iw, self.ih), KEY_RGB)
        img.paste(body, (self.pad, self.pad), body)
        return img

    # ---------- yanan lambanin govdeye vurmasi ----------

    def _build_wash_mask(self):
        """Yanan lambanin govde yuzeyine yaydigi genis, cok sonuk renk yikamasi."""
        size = self.s(BOX_H * 0.5) * 2
        return _radial_template("wash", 30, 2.2, 0.0).resize(
            (size, size), Image.LANCZOS)

    def _wash(self, idx, step):
        key = (idx, step)
        img = self._washes.get(key)
        if img is None:
            k = step / 20.0
            g = self._wash_base.point(lambda v: int(v * k))
            m = Image.new("L", (self.bw, self.bh), 0)
            m.paste(g, (self.lx - self.pad - g.width // 2,
                        self.ly[idx] - self.pad - g.height // 2))
            m = ImageChops.multiply(m, self._fill)
            img = Image.new("RGBA", (self.bw, self.bh), LAMP_RGB[idx] + (0,))
            img.putalpha(m)
            if len(self._washes) > 72:
                self._washes.clear()
            self._washes[key] = img
        return img

    # ---------- lambalar ----------

    def _build_bloom_mask(self):
        size = self.bloom_r * 2
        m = _radial_template("bloom", 190, 2.7, LAMP_R * 0.8 / BLOOM_R)
        m = m.resize((size, size), Image.LANCZOS)
        return m.filter(ImageFilter.GaussianBlur(self.scale * 1.1))

    def bloom(self, idx, step):
        key = (idx, step)
        img = self._blooms.get(key)
        if img is None:
            k = step / 20.0
            mask = self._bloom_base.point(lambda v: int(v * k))
            img = Image.new("RGBA", mask.size, LAMP_RGB[idx] + (0,))
            img.putalpha(mask)
            if len(self._blooms) > 96:
                self._blooms.clear()
            self._blooms[key] = img
        return img

    def lamp(self, idx, step):
        """Lamba camı: step 0 sonuk, 20 tam yanik."""
        key = (idx, step)
        img = self._lamps.get(key)
        if img is not None:
            return img

        k = step / 20.0
        rgb = LAMP_RGB[idx]
        col = blend(blend(rgb, LAMP_OFF, 0.90), rgb, k)
        col = blend(col, (255, 255, 255), 0.13 * k)

        r = self.lamp_r
        size = r * 2 + 4
        ss = 4
        c = size * ss / 2.0
        socket = Image.new("L", (size * ss, size * ss), 0)
        ImageDraw.Draw(socket).ellipse(
            [c - (r + 1.4) * ss, c - (r + 1.4) * ss,
             c + (r + 1.4) * ss, c + (r + 1.4) * ss], fill=255)
        glass = Image.new("L", (size * ss, size * ss), 0)
        ImageDraw.Draw(glass).ellipse(
            [c - r * ss, c - r * ss, c + r * ss, c + r * ss], fill=255)
        socket = socket.resize((size, size), Image.LANCZOS)
        glass = glass.resize((size, size), Image.LANCZOS)

        # once koyu yuva, sonra cam - lamba govdeye oturmus gibi dursun
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        rim = Image.new("RGBA", (size, size), (6, 7, 9, 0))
        rim.putalpha(socket)
        img = Image.alpha_composite(img, rim)

        top = blend(col, (255, 255, 255), 0.20 + 0.10 * k)
        bottom = blend(col, (0, 0, 0), 0.22 - 0.10 * k)
        grad = Image.new("RGB", (size, size), bottom)
        d = ImageDraw.Draw(grad)
        for y in range(size):
            d.line([(0, y), (size, y)], fill=blend(top, bottom, y / max(1, size - 1)))
        bulb = grad.convert("RGBA")
        bulb.putalpha(glass)
        img = Image.alpha_composite(img, bulb)

        # cam boncuk parlamasi degil; ust yariya dusen genis, yumusak bir isik
        spec = Image.new("L", (size * ss, size * ss), 0)
        ImageDraw.Draw(spec).ellipse(
            [int(size * ss * 0.18), int(size * ss * 0.10),
             int(size * ss * 0.82), int(size * ss * 0.58)],
            fill=int(42 + 34 * k))
        spec = spec.resize((size, size), Image.LANCZOS)
        spec = spec.filter(ImageFilter.GaussianBlur(max(1.0, self.scale * 1.4)))
        layer = Image.new("RGBA", (size, size), (255, 255, 255, 0))
        layer.putalpha(ImageChops.multiply(spec, glass))
        img = Image.alpha_composite(img, layer)

        if len(self._lamps) > 96:
            self._lamps.clear()
        self._lamps[key] = img
        return img

    # ---------- kare ----------

    def frame(self, steps):
        img = self._base.copy()

        top = max(range(3), key=lambda i: steps[i])
        if steps[top]:
            wash = self._wash(top, steps[top])
            img.paste(wash, (self.pad, self.pad), wash)

        for i, st in enumerate(steps):
            if st:
                sp = self.bloom(i, st)
                img.paste(sp, (self.lx - sp.width // 2,
                               self.ly[i] - sp.height // 2), sp)
        for i, st in enumerate(steps):
            sp = self.lamp(i, st)
            img.paste(sp, (self.lx - sp.width // 2,
                           self.ly[i] - sp.height // 2), sp)
        return img


class Panel:
    """Ayarlar paneli: cizim ve tiklanabilir bolgeler (panel penceresine gore).

    Degismeyen kisim (zemin, baslik, satir yazilari) bir kez ciziliyor;
    anahtarlar, kaydirici ve uzerine gelme vurgusu her seferinde ustune
    ekleniyor - fare gezerken yeniden cizim hafif kalsin.
    """

    ROWS = (("topmost", "Her zaman üstte"),
            ("pulse", "Nabız animasyonu"),
            ("lock", "Konumu kilitle"),
            ("label", "Durum yazısını göster"))

    def __init__(self, scale):
        self.scale = scale
        s = self.s
        self.m = max(2, s(2))                  # anahtar renk icin kenar payi
        self.w = s(PANEL_W)
        self.pad = s(PANEL_PAD)
        self.head, self.row, self.foot = s(PANEL_HEAD), s(PANEL_ROW), s(PANEL_FOOT)
        self.h = self.head + self.row * (1 + len(self.ROWS)) + self.foot
        self.iw, self.ih = self.w + 2 * self.m, self.h + 2 * self.m

        self.f_title = load_font(UIB_FONTS, s(12.5))
        self.f_text = load_font(UI_FONTS, s(11))
        self.f_small = load_font(UI_FONTS, s(10.5))
        self.icon_px = s(9)

        m, w = self.m, self.w
        self.row_cy = [m + self.head + i * self.row + self.row // 2
                       for i in range(1 + len(self.ROWS))]
        self.foot_y = m + self.h - self.foot

        # boyut kaydiricisi: sagda yuzde, solunda kanal
        self.knob_r = s(6.5)
        self.slider_w = s(92)
        self.slider_h = s(16)
        right = m + w - self.pad - s(34) - s(6)
        self.slider_x = right - self.slider_w
        # topuzun merkezinin gidebildigi aralik (pencere koordinati)
        self.track = (self.slider_x + self.knob_r,
                      self.slider_x + self.slider_w - self.knob_r)

        self.close_c = (m + w - self.pad - s(5), m + self.head // 2 + s(1))
        reset_w = int(self.f_small.getlength("Varsayılana dön"))

        hit = s(12)
        self.regions = [
            ("close", (self.close_c[0] - hit, self.close_c[1] - hit,
                       self.close_c[0] + hit, self.close_c[1] + hit)),
            ("slider", (self.slider_x - s(4), self.row_cy[0] - self.row // 2,
                        self.slider_x + self.slider_w + s(4),
                        self.row_cy[0] + self.row // 2)),
            ("reset", (m + self.pad - s(6), self.foot_y,
                       m + self.pad + reset_w + s(6), m + self.h)),
        ]
        for (key, _), cy in zip(self.ROWS, self.row_cy[1:]):
            self.regions.append(("row:" + key, (m + s(6), cy - self.row // 2,
                                                m + w - s(6), cy + self.row // 2)))

        self._base = self._build_base()
        self._toggles = {on: self._toggle(on) for on in (True, False)}
        rw, rh = w - 2 * s(6), self.row - s(4)
        self._row_glow = Image.new("RGBA", (rw, rh), (255, 255, 255, 0))
        self._row_glow.putalpha(ss_mask(rw, rh, lambda d, k: d.rounded_rectangle(
            [0, 0, rw * k - 1, rh * k - 1], radius=s(7) * k, fill=12)))

    def s(self, v):
        return int(round(v * self.scale))

    def hit(self, x, y):
        for name, (x0, y0, x1, y1) in self.regions:
            if x0 <= x <= x1 and y0 <= y <= y1:
                return name
        return None

    @staticmethod
    def frac(zoom):
        """Kaydirici logaritmik: her bolum ayni oranda buyutsun."""
        return math.log(zoom / ZOOM_MIN) / math.log(ZOOM_MAX / ZOOM_MIN)

    @staticmethod
    def zoom_at(frac):
        return ZOOM_MIN * (ZOOM_MAX / ZOOM_MIN) ** max(0.0, min(1.0, frac))

    def _build_base(self):
        s, m = self.s, self.m
        body = material(self.w, self.h, s(12), (37, 39, 46), (22, 23, 28), 62)
        img = Image.new("RGB", (self.iw, self.ih), KEY_RGB)
        img.paste(body, (m, m), body)
        d = ImageDraw.Draw(img)
        d.text((m + self.pad, m + self.head // 2 + s(1)), "Ayarlar",
               font=self.f_title, fill=TEXT_RGB, anchor="lm")
        lw = max(1, s(0.6))
        for y in (m + self.head, self.foot_y):
            d.line([(m + self.pad, y), (m + self.w - self.pad, y)],
                   fill=LINE_RGB, width=lw)
        labels = ["Boyut"] + [label for _, label in self.ROWS]
        for label, cy in zip(labels, self.row_cy):
            d.text((m + self.pad, cy), label, font=self.f_text, fill=TEXT_RGB,
                   anchor="lm")
        return img

    def _toggle(self, on):
        s = self.s
        w, h = s(28), s(16)
        if on:
            t = material(w, h, h // 2, blend(ACCENT_RGB, (255, 255, 255), 0.08),
                         blend(ACCENT_RGB, (0, 0, 0), 0.18), 40)
        else:
            t = material(w, h, h // 2, (60, 63, 72), (44, 46, 54), 40)
        kr = h / 2.0 - s(2.5)
        kx = w - h / 2.0 if on else h / 2.0
        knob = Image.new("RGBA", (w, h), (244, 245, 248, 0))
        knob.putalpha(ss_mask(w, h, lambda d, k: d.ellipse(
            [(kx - kr) * k, (h / 2.0 - kr) * k, (kx + kr) * k, (h / 2.0 + kr) * k],
            fill=255)))
        return Image.alpha_composite(t, knob)

    def _slider(self, frac):
        w, h, kr = self.slider_w, self.slider_h, self.knob_r
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        cy, th = h / 2.0, self.scale * 3.2
        x0, x1 = kr, w - kr
        kx = x0 + (x1 - x0) * max(0.0, min(1.0, frac))

        def bar(xa, xb, color):
            lay = Image.new("RGBA", (w, h), color + (0,))
            lay.putalpha(ss_mask(w, h, lambda d, k: d.rounded_rectangle(
                [xa * k, (cy - th / 2) * k, xb * k, (cy + th / 2) * k],
                radius=th / 2 * k, fill=255)))
            img.alpha_composite(lay)

        bar(x0, x1, (60, 63, 72))
        if kx > x0 + 1:
            bar(x0, kx, ACCENT_RGB)
        knob = Image.new("RGBA", (w, h), (244, 245, 248, 0))
        knob.putalpha(ss_mask(w, h, lambda d, k: d.ellipse(
            [(kx - kr) * k, (cy - kr) * k, (kx + kr) * k, (cy + kr) * k], fill=255)))
        img.alpha_composite(knob)
        return img

    def image(self, settings, zoom, hover):
        s, m = self.s, self.m
        img = self._base.copy()
        if hover and hover.startswith("row:"):
            key = hover[4:]
            i = [k for k, _ in self.ROWS].index(key) + 1
            g = self._row_glow
            img.paste(g, (m + s(6), self.row_cy[i] - g.height // 2), g)

        for (key, _), cy in zip(self.ROWS, self.row_cy[1:]):
            t = self._toggles[bool(settings.get(key))]
            img.paste(t, (m + self.w - self.pad - t.width, cy - t.height // 2), t)

        sl = self._slider(self.frac(zoom))
        img.paste(sl, (self.slider_x, self.row_cy[0] - sl.height // 2), sl)

        d = ImageDraw.Draw(img)
        d.text((m + self.w - self.pad, self.row_cy[0]), "%d%%" % round(zoom * 100),
               font=self.f_small, fill=MUTED_RGB, anchor="rm")
        d.text((m + self.pad, self.foot_y + self.foot // 2), "Varsayılana dön",
               font=self.f_small, fill=TEXT_RGB if hover == "reset" else MUTED_RGB,
               anchor="lm")
        draw_icon(img, self.close_c[0], self.close_c[1], CLOSE_GLYPH, self.icon_px,
                  TEXT_RGB if hover == "close" else MUTED_RGB)
        return img


class HUD:
    def __init__(self):
        enable_dpi_awareness()
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.overrideredirect(True)
        self.root.configure(bg=KEY_HEX)

        try:
            self.dpi = max(1.0, min(2.5, self.root.winfo_fpixels("1i") / 96.0))
        except Exception:
            self.dpi = 1.0

        if HAVE_PIL and sys.platform == "win32":
            try:
                self.root.attributes("-transparentcolor", KEY_HEX)
            except tk.TclError:
                pass

        self.settings = read_settings()
        self.root.attributes("-topmost", self.settings["topmost"])

        self.state, self.label = read_state()
        # her lambanin 0..1 arasi sonme/yanma seviyesi
        self.fade = [1.0 if STATES[self.state]["idx"] == i else 0.0 for i in range(3)]
        self._photo = None
        self._sig = None
        self._steps = None
        self._t0 = time.perf_counter()

        # Pencerelerin konumu burada tutuluyor; winfo_x/y geometri
        # degisiminden hemen sonra eski degeri dondurdugu icin ona
        # guvenilmiyor.
        self._xy = (0, 0)
        self._size = (0, 0)
        self.zoom = read_zoom()
        self._renderers = {}
        self.renderer = None
        self._pending_zoom = None
        self._zoom_job = None
        self._anchor = None

        # tasima ve boyutlandirma
        self._dx = self._dy = 0
        self._grab_off = 0
        self._resizing = False

        # alttaki tutamac (ayirici + disli)
        self.chip = None
        self._chip_on = False
        self._chip_xy = (0, 0)
        self._chip_size = (0, 0)
        self._grip_dragging = False
        self._gear_down = False
        self._near_at = None
        self._away_at = None

        # durum yazisi
        self.cap = None
        self._cap_on = False
        self._cap_xy = (0, 0)
        self._cap_size = (0, 0)
        self._cap_margin = 0
        self._cap_key = None
        self._cap_cache = {}

        # ayarlar paneli
        self.panel = None
        self._panel = None
        self._panel_open = False
        self._panel_side = "right"
        self._panel_xy = (0, 0)
        self._panel_hover = None
        self._slider_drag = False
        self._track_x = (0, 1)

        if HAVE_PIL:
            self.view = tk.Label(self.root, bd=0, highlightthickness=0, bg=KEY_HEX)
        else:
            self.view = tk.Canvas(self.root, bg="#1a1b20", highlightthickness=0)
            self.f_lamps = []
        self.view.pack()

        w, h = self._build_size()
        self._size = (w, h)
        self._place(w, h)
        self._bind()
        self.root.deiconify()
        if self.settings["label"]:
            self._show_caption()
        self.poll()
        self.animate()

    # ---------- yardimci pencereler ----------

    def _make_layer(self, topmost):
        """Cercevesiz, seffaf anahtarli, isigin yaninda duran ek pencere."""
        win = tk.Toplevel(self.root)
        win.withdraw()
        win.overrideredirect(True)
        win.attributes("-topmost", topmost)
        win.configure(bg=KEY_HEX)
        if sys.platform == "win32":
            try:
                win.attributes("-transparentcolor", KEY_HEX)
            except tk.TclError:
                pass
        view = tk.Label(win, bd=0, highlightthickness=0, bg=KEY_HEX)
        view.pack()
        return win, view

    def _lpad(self, zoom=None):
        """Isik penceresinin govde etrafindaki seffaf kenar payi."""
        return int(round(MARGIN * self.dpi * (self.zoom if zoom is None else zoom)))

    def _cluster_half(self):
        """Isik + (varsa) altindaki yazi: yarim genislik."""
        cap_w = self._cap_size[0] if self._cap_on else 0
        return max(self._size[0], cap_w) / 2.0

    def _layout(self):
        """Yazi, tutamac ve paneli isigin kayitli konum/olcusune gore dizer."""
        x, y = self._xy
        w, h = self._size
        cx = x + w / 2.0
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        bottom = y + h

        if self._cap_on:
            cw, ch = self._cap_size
            m = self._cap_margin
            sc = self.dpi * self.zoom
            # Iki pencerenin seffaf kenar paylari ust uste biniyor; gorunen
            # aralik govdeyle plaka arasinda tam CAP_GAP kadar.
            cap_x = int(round(cx - cw / 2.0))
            cap_y = y + h - self._lpad() + int(round(CAP_GAP * sc)) - m
            self._cap_xy = (cap_x, cap_y)
            self.cap.geometry(f"{cw}x{ch}+{cap_x}+{cap_y}")
            bottom = cap_y + ch

        if self._chip_on:
            _, pad, cw, chh, _ = self._chip_metrics()
            bw, bh = cw + 2 * pad, chh + 2 * pad
            gap = int(round(CHIP_GAP * self.dpi))
            gx = int(round(cx - bw / 2.0))
            gy = bottom + gap - pad
            if gy + bh > sh - 4:                  # asagi sigmiyorsa ustte goster
                gy = y - bh - gap + pad
            gx = max(2, min(sw - bw - 2, gx))
            gy = max(2, gy)
            self._chip_xy = (gx, gy)
            self._chip_size = (bw, bh)
            self.chip.geometry(f"{bw}x{bh}+{gx}+{gy}")

        if self._panel_open:
            self._place_panel()
        self._commit()

    def _commit(self):
        # Tk pencere tasimalarini bosta uygular. Araya bir lift() girerse
        # Windows pencerenin ESKI konumunu bildiriyor ve bekleyen tasima
        # kayboluyordu (panel yerinde kalip tiklamalar 19 px kayiyordu).
        # Konumlari hemen uygulatip ondan sonra one aliyoruz.
        self.root.update_idletasks()

    # ---------- alttaki tutamac: ayirici + disli ----------

    def _chip_metrics(self):
        s = self.dpi
        return (s, int(round(5 * s)), int(round(CHIP_W * s)),
                int(round(CHIP_H * s)), int(round(CHIP_SPLIT * s)))

    def _chip_image(self, grip_hot, gear_hot):
        s, pad, w, h, split = self._chip_metrics()
        chip = material(w, h, h // 2, CHIP_TOP, CHIP_BOTTOM, 62)
        if gear_hot:                           # panel acikken disli kismi aydinlik
            lit = Image.new("L", (w, h), 0)
            ImageDraw.Draw(lit).rectangle([split, 0, w, h], fill=26)
            glow = Image.new("RGBA", (w, h), (255, 255, 255, 0))
            glow.putalpha(ImageChops.multiply(lit, chip.getchannel("A")))
            chip = Image.alpha_composite(chip, glow)

        img = Image.new("RGB", (w + 2 * pad, h + 2 * pad), KEY_RGB)
        img.paste(chip, (pad, pad), chip)
        d = ImageDraw.Draw(img)
        d.line([(pad + split, pad + int(round(3 * s))),
                (pad + split, pad + h - int(round(3 * s)))],
               fill=(70, 73, 84), width=max(1, int(round(0.6 * s))))

        # noktalar - suruklerken yanan lambanin rengini aliyor
        cx, cy = pad + split / 2.0 + 0.5 * s, pad + h / 2.0
        dr, pitch = CHIP_DOT * s, CHIP_PITCH * s
        iw, ih = img.size

        def dots(dd, k):
            for i in (-1, 0, 1):
                x = cx + i * pitch
                dd.ellipse([(x - dr) * k, (cy - dr) * k, (x + dr) * k, (cy + dr) * k],
                           fill=255)

        color = STATES[self.state]["rgb"] if grip_hot else CHIP_DOT_RGB
        lay = Image.new("RGBA", (iw, ih), color + (0,))
        lay.putalpha(ss_mask(iw, ih, dots).point(
            lambda v: v * (255 if grip_hot else 205) // 255))
        img.paste(lay, (0, 0), lay)

        draw_icon(img, pad + split + (w - split) / 2.0, cy + 0.3 * s, GEAR_GLYPH,
                  int(round(8.5 * s)), TEXT_RGB if gear_hot else CHIP_GEAR_RGB)
        return img

    def _draw_chip(self):
        self._chip_photo = ImageTk.PhotoImage(self._chip_image(
            self._grip_dragging, self._panel_open or self._gear_down))
        self.chip_view.configure(image=self._chip_photo)

    def _show_chip(self):
        if not HAVE_PIL:
            return
        if self.chip is None:
            self.chip, self.chip_view = self._make_layer(topmost=True)
            self.chip_view.bind("<Button-1>", self._chip_press)
            self.chip_view.bind("<B1-Motion>", self._chip_move)
            self.chip_view.bind("<ButtonRelease-1>", self._chip_release)
        self._chip_on = True
        self._draw_chip()
        self._layout()
        self.chip.deiconify()
        self.chip.lift()
        self._away_at = None

    def _hide_chip(self):
        self._chip_on = False
        self._near_at = self._away_at = None
        if self.chip is not None:
            self.chip.withdraw()

    def _chip_press(self, e):
        _, pad, _, _, split = self._chip_metrics()
        if e.x >= pad + split:                 # sag yari: disli
            self._gear_down = True
            self._draw_chip()
            return
        # Sol yari: gercek bir ayirici gibi govdenin ust kenari yerinde
        # kalir, alt kenari imleci birebir izler.
        x, y = self._xy
        w, h = self._size
        lpad = self._lpad()
        self._grip_dragging = True
        self._anchor = ("top", x + w / 2.0, y + lpad)
        self._grab_off = e.y_root - (y + h - lpad)
        self._away_at = None
        self._draw_chip()

    def _chip_move(self, e):
        if not self._grip_dragging:
            return
        self._away_at = None
        want = e.y_root - self._grab_off - self._anchor[2]     # govde yuksekligi
        self._request_zoom(want / (BOX_H * self.dpi))

    def _chip_release(self, e):
        if self._gear_down:
            self._gear_down = False
            _, pad, w, h, split = self._chip_metrics()
            if pad + split <= e.x <= pad + w + pad and 0 <= e.y <= h + 2 * pad:
                self._toggle_panel()
            else:
                self._draw_chip()
            return
        if self._grip_dragging:
            # Bekleyen son boyut, capa birakilmadan once uygulanmali; yoksa
            # merkez capasiyla uygulanip isik bir an zipliyordu.
            self._flush_zoom()
            self._grip_dragging = False
            self._anchor = None
            self._save_zoom()
            self._save_pos()
            if self._chip_on:
                self._draw_chip()
                self._layout()

    # ---------- durum yazisi ----------

    def _caption_text(self):
        text = self.label or STATES[self.state]["label"]
        if len(text) > CAP_MAX_CHARS:
            text = text[:CAP_MAX_CHARS - 1].rstrip() + "…"
        return text

    def _caption_image(self, text, px):
        font = load_font(UIB_FONTS, px)
        tw = int(math.ceil(font.getlength(text)))
        padx = int(round(px * 0.85))
        h = int(round(px * 1.85))
        m = max(2, int(round(px * 0.2)))
        w = tw + 2 * padx
        body = material(w, h, h // 2, (40, 42, 50), (22, 23, 28), 60)
        img = Image.new("RGB", (w + 2 * m, h + 2 * m), KEY_RGB)
        img.paste(body, (m, m), body)
        ImageDraw.Draw(img).text((m + w / 2.0, m + h / 2.0), text, font=font,
                                 fill=TEXT_RGB, anchor="mm")
        return img, m

    def _render_caption(self):
        text = self._caption_text()
        px = max(CAP_MIN_PX, int(round(CAP_PX * self.dpi * self.zoom)))
        key = (text, px)
        if key == self._cap_key:
            return
        got = self._cap_cache.get(key)
        if got is None:
            got = self._caption_image(text, px)
            if len(self._cap_cache) > 24:
                self._cap_cache.clear()
            self._cap_cache[key] = got
        img, m = got
        self._cap_photo = ImageTk.PhotoImage(img)
        self.cap_view.configure(image=self._cap_photo)
        self._cap_size = img.size
        self._cap_margin = m
        self._cap_key = key

    def _show_caption(self):
        if not HAVE_PIL:
            return
        if self.cap is None:
            self.cap, self.cap_view = self._make_layer(self.settings["topmost"])
            # yazi isigin parcasi: ondan da tasinip menu acilabilsin
            self.cap_view.bind("<Button-1>", self._grab)
            self.cap_view.bind("<B1-Motion>", self._drag)
            self.cap_view.bind("<ButtonRelease-1>", self._release)
            self.cap_view.bind("<Button-3>", self._popup)
            for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                self.cap_view.bind(seq, self._wheel)
        self._cap_on = True
        self._render_caption()
        self._layout()
        self.cap.deiconify()

    def _hide_caption(self):
        self._cap_on = False
        if self.cap is not None:
            self.cap.withdraw()

    # ---------- ayarlar paneli ----------

    def _toggle_panel(self):
        if self._panel_open:
            self._close_panel()
        else:
            self._open_panel()

    def _open_panel(self):
        if not HAVE_PIL:
            return
        if self.panel is None:
            self.panel, self.panel_view = self._make_layer(topmost=True)
            self.panel_view.bind("<Button-1>", self._panel_press)
            self.panel_view.bind("<B1-Motion>", self._panel_drag)
            self.panel_view.bind("<ButtonRelease-1>", self._panel_release)
            self.panel_view.bind("<Motion>", self._panel_motion)
            self.panel_view.bind("<Leave>", lambda e: self._set_hover(None))
            self._panel = Panel(self.dpi)
        if not self._panel_open:
            # Saga sigiyorsa sag, yoksa sol. Panel acik kaldikca taraf sabit.
            x, _ = self._xy
            right = x + self._size[0] / 2.0 + self._cluster_half()
            gap = int(round(PANEL_GAP * self.dpi))
            fits = right + gap + self._panel.w <= self.root.winfo_screenwidth() - 4
            self._panel_side = "right" if fits else "left"
            self._panel_hover = None
        self._panel_open = True
        self._draw_panel()
        self._place_panel()
        self._commit()
        self.panel.deiconify()
        self.panel.lift()
        if self._chip_on:
            self._draw_chip()

    def _close_panel(self):
        self._panel_open = False
        self._panel_hover = None
        self._slider_drag = False
        if self.panel is not None:
            self.panel.withdraw()
        if self._chip_on:
            self._draw_chip()

    def _draw_panel(self):
        if not self._panel_open:
            return
        img = self._panel.image(self.settings, self.zoom, self._panel_hover)
        self._panel_photo = ImageTk.PhotoImage(img)
        self.panel_view.configure(image=self._panel_photo)

    def _place_panel(self):
        x, y = self._xy
        cx = x + self._size[0] / 2.0
        half = self._cluster_half()
        left, right = cx - half, cx + half
        p = self._panel
        gap = int(round(PANEL_GAP * self.dpi))
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        if not self._slider_drag:
            # tasinirken bir kenara dayandiysa oteki tarafa gec
            fits_r = right + gap + p.w <= sw - 4
            fits_l = left - gap - p.w >= 4
            if self._panel_side == "right" and not fits_r and fits_l:
                self._panel_side = "left"
            elif self._panel_side == "left" and not fits_l and fits_r:
                self._panel_side = "right"
        if self._panel_side == "right":
            px = int(round(right + gap - p.m))
        else:
            px = int(round(left - gap - p.w - p.m))
        py = y + self._lpad() - p.m            # panelin ustu govdenin ustuyle hizali
        px = max(2, min(sw - p.iw - 2, px))
        py = max(2, min(sh - p.ih - 2, py))
        self._panel_xy = (px, py)
        self.panel.geometry(f"{p.iw}x{p.ih}+{px}+{py}")

    def _set_hover(self, region):
        if region != self._panel_hover:
            self._panel_hover = region
            self._draw_panel()

    def _panel_motion(self, e):
        self._set_hover(self._panel.hit(e.x, e.y))

    def _panel_press(self, e):
        region = self._panel.hit(e.x, e.y)
        if region == "slider":
            # Panel tarafindaki kenar ve govdenin ustu sabit: isik panelden
            # uzaga dogru buyur, panel yerinden oynamaz, topuz imlecin
            # altinda kalir.
            self._anchor = self._panel_anchor()
            px = self._panel_xy[0]
            self._track_x = (px + self._panel.track[0], px + self._panel.track[1])
            self._slider_drag = True
            self._slider_to(e.x_root)
        elif region == "close":
            self._close_panel()
        elif region == "reset":
            self._reset_settings()
        elif region and region.startswith("row:"):
            self._toggle_setting(region[4:])

    def _panel_drag(self, e):
        if self._slider_drag:
            self._slider_to(e.x_root)

    def _panel_release(self, _e=None):
        if self._slider_drag:
            self._flush_zoom()
            self._slider_drag = False
            self._anchor = None
            self._save_zoom()
            self._save_pos()
            self._layout()
            self._draw_panel()

    def _panel_anchor(self):
        x, y = self._xy
        cx = x + self._size[0] / 2.0
        half = self._cluster_half()
        top = y + self._lpad()
        if self._panel_side == "right":
            return ("cluster_right", cx + half, top)
        return ("cluster_left", cx - half, top)

    def _slider_to(self, x_root):
        x0, x1 = self._track_x
        self._request_zoom(Panel.zoom_at((x_root - x0) / float(max(1, x1 - x0))))

    def _toggle_setting(self, key):
        self.settings[key] = not self.settings[key]
        save_settings(self.settings)
        self._apply_setting(key)
        self._draw_panel()

    def _apply_setting(self, key):
        on = self.settings[key]
        if key == "topmost":
            self.root.attributes("-topmost", on)
            if self.cap is not None:
                self.cap.attributes("-topmost", on)
            # tutamac ve panel her zaman ustte; isigin altinda kalmasinlar
            self._commit()
            for win in (self.chip, self.panel):
                if win is not None:
                    win.lift()
        elif key == "label":
            if on:
                self._show_caption()
            else:
                self._hide_caption()
            self._layout()
        # "pulse" ve "lock" her karede / suruklemede okunuyor

    def _reset_settings(self):
        old = dict(self.settings)
        self.settings = dict(DEFAULT_SETTINGS)
        save_settings(self.settings)
        for key, value in self.settings.items():
            if value != old[key]:
                self._apply_setting(key)
        if self._panel_open:
            self._anchor = self._panel_anchor()
        self.set_zoom(DEFAULT_ZOOM)
        self._anchor = None
        self._save_zoom()
        self._save_pos()
        self._draw_panel()

    # ---------- imlec izleme ----------

    @staticmethod
    def _over(px, py, xy, size, slack):
        """Imlec bu dikdortgenin uzerinde mi? (biraz pay birakarak)"""
        x, y = xy
        w, h = size
        return (x - slack <= px <= x + w + slack and
                y - slack <= py <= y + h + slack)

    def _track_pointer(self):
        """Tutamaci ac/kapat.

        <Enter>/<Leave> olaylari bu pencere icin guvenilir degil (hic odak
        almiyor, ustte duruyor ve imlec sicrayarak gelebiliyor); bu yuzden
        karar dogrudan imlec konumuna bakilarak veriliyor.
        """
        try:
            px, py = self.root.winfo_pointerxy()
        except tk.TclError:
            return
        now = time.perf_counter()
        near = (self._over(px, py, self._xy, self._size, 0) or
                (self._cap_on and self._over(px, py, self._cap_xy, self._cap_size, 0)) or
                (self._chip_on and self._over(px, py, self._chip_xy, self._chip_size, 10)))

        if self._panel_open and self._panel_hover and not self._over(
                px, py, self._panel_xy, (self._panel.iw, self._panel.ih), 0):
            self._set_hover(None)

        # Panel acikken disli gorunur kalsin ki paneli kapatabilesiniz.
        busy = (self._grip_dragging or self._gear_down or self._slider_drag or
                self._panel_open)
        if busy or near:
            self._away_at = None
            if not self._chip_on:
                if self._near_at is None:
                    self._near_at = now
                elif now - self._near_at >= CHIP_SHOW_MS / 1000.0:
                    self._show_chip()
        else:
            self._near_at = None
            if self._chip_on:
                if self._away_at is None:
                    self._away_at = now
                elif now - self._away_at >= CHIP_HIDE_MS / 1000.0:
                    self._hide_chip()

    # ---------- boyut ----------

    def _request_zoom(self, z):
        # Fare olaylari cizimden hizli gelebiliyor; en son istenen boyut
        # tutulup olay kuyrugu bosaldiginda bir kez uygulaniyor. Animasyon
        # karesini (33 ms) beklemedigi icin gecikme hissedilmiyor.
        self._pending_zoom = z
        if self._zoom_job is None:
            self._zoom_job = self.root.after_idle(self._flush_zoom)

    def _flush_zoom(self):
        if self._zoom_job is not None:
            try:
                self.root.after_cancel(self._zoom_job)
            except tk.TclError:
                pass
            self._zoom_job = None
        if self._pending_zoom is not None:
            z, self._pending_zoom = self._pending_zoom, None
            self.set_zoom(z)

    def _build_size(self):
        """Gecerli orana gore cizeri/tuvali hazirlar, pencere olcusunu dondurur."""
        scale = self.dpi * self.zoom
        if HAVE_PIL:
            # Surekli boyutta sonsuz cizer olabilir; anahtar olarak pencerenin
            # piksel olcusu kullaniliyor (ayni olcu = ayni cizim) ve son
            # kullanilanlardan birkaci tutuluyor.
            key = window_size(scale)
            r = self._renderers.get(key)
            if r is None:
                r = Renderer(scale)
                if len(self._renderers) > 8:
                    self._renderers.clear()
                self._renderers[key] = r
            self.renderer = r
            return r.iw, r.ih

        # Pillow yoksa: tuvali bastan ciz
        w, h = int(42 * scale), int(78 * scale)
        self.view.config(width=w, height=h)
        self.view.delete("all")
        rr = max(2, int(7 * scale))
        y = h // 2 - int(19 * scale)
        self.f_lamps = []
        for _ in range(3):
            self.f_lamps.append(self.view.create_oval(
                w // 2 - rr, y - rr, w // 2 + rr, y + rr,
                fill="#1a1b20", outline=""))
            y += int(19 * scale)
        return w, h

    def set_zoom(self, z):
        """Boyutu degistirir; nereye capalanacagini self._anchor belirler.

        Capa (tur, x, y):
          center         isik merkezi sabit (tekerlek, menu)
          top            govdenin ustu ve yatay merkez sabit (ayirici)
          cluster_right  govdenin ustu ve isik+yazi kumesinin sag kenari
          cluster_left   ... sol kenari (panel kaydiricisi: panel kipirdamaz)
        """
        z = max(ZOOM_MIN, min(ZOOM_MAX, z))
        if window_size(self.dpi * z) == self._size and self.renderer is not None:
            # Pencere ayni boyda kaliyor; yalnizca paneldeki yuzde guncellensin.
            self.zoom = z
            self._draw_panel()
            return

        x, y = self._xy
        w0, h0 = self._size
        anchor = self._anchor or ("center", x + w0 / 2.0, y + h0 / 2.0)
        self.zoom = z
        w, h = self._build_size()
        self._size = (w, h)

        # Yeni cizer = yeni boyutta resim. Her zaman yeniden ciziliyor;
        # yalnizca lamba parlakligi degisince cizilirse sabit yanan kirmizida
        # pencere buyurken icinde eski kucuk resim kaliyordu.
        self._sig = None
        if self._steps is not None:
            self._paint(self._steps)
        if self._cap_on:
            self._render_caption()

        kind, ax, ay = anchor
        if kind == "center":
            nx, ny = ax - w / 2.0, ay - h / 2.0
        else:
            if kind == "top":
                cx = ax
            elif kind == "cluster_right":
                cx = ax - self._cluster_half()
            else:
                cx = ax + self._cluster_half()
            nx, ny = cx - w / 2.0, ay - self._lpad()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        nx = max(-w + 24, min(sw - 24, int(round(nx))))
        ny = max(-20, min(sh - 20, int(round(ny))))
        self._xy = (nx, ny)
        self.root.geometry(f"{w}x{h}+{nx}+{ny}")

        # Yazi, tutamac ve panel isikla cakismayacak yerlere diziliyor;
        # one almaya (lift) gerek yok - bkz. _commit.
        self._layout()
        self._draw_panel()
        # Bekleyen cizimi hemen bosalt: pencere yeni boyuta gecerken icerik de
        # ayni anda yenilensin, arada bos ya da eski bir kare gorunmesin.
        self.root.update_idletasks()
        # Surukleme suruyorsa her adimda diske yazma; bitince bir kez yaz.
        if self._anchor is None:
            self._save_zoom()
            self._save_pos()

    def reset_zoom(self):
        self.set_zoom(DEFAULT_ZOOM)

    def _wheel(self, e):
        # Bu pencere hicbir zaman odak almiyor; tekerlek yine de geliyor
        # cunku Windows 10/11'de "fareyle uzerine gelinen pencereyi kaydir"
        # varsayilan olarak acik. Kapaliysa Ctrl+surukleme ve menu calisir.
        if getattr(e, "num", None) in (4, 5):
            step = 1 if e.num == 4 else -1
        else:
            step = 1 if e.delta > 0 else -1
        self.set_zoom(self.zoom * (ZOOM_WHEEL if step > 0 else 1 / ZOOM_WHEEL))

    # Ctrl + sol tik surukleme: ayiriciyla ayni, alt kenar imleci izler.
    # Dugme olaylari odak gerektirmedigi icin bu her zaman calisir.
    def _resize_grab(self, e):
        x, y = self._xy
        w, h = self._size
        lpad = self._lpad()
        self._resizing = True
        self._anchor = ("top", x + w / 2.0, y + lpad)
        self._grab_off = e.y_root - (y + h - lpad)

    def _resize_drag(self, e):
        if not self._resizing:
            return
        want = e.y_root - self._grab_off - self._anchor[2]
        self._request_zoom(want / (BOX_H * self.dpi))

    def _release(self, _e=None):
        if self._resizing:
            self._flush_zoom()
            self._resizing = False
            self._anchor = None
            self._save_zoom()
        self._save_pos()

    def _save_zoom(self):
        try:
            with open(ZOOM_FILE, "w", encoding="utf-8") as f:
                f.write("%.4f" % self.zoom)
        except Exception:
            pass

    # ---------- pencere ----------

    def _place(self, w, h):
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x, y = (sw - w) // 2, int(6 * self.dpi)
        try:
            with open(POS_FILE, "r", encoding="utf-8") as f:
                px, py = (int(v) for v in f.read().split(","))
            if -w + 24 < px < sw - 24 and -20 < py < sh - 20:
                x, y = px, py
        except Exception:
            pass
        self._xy = (x, y)
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def _bind(self):
        self.view.bind("<Button-1>", self._grab)
        self.view.bind("<B1-Motion>", self._drag)
        self.view.bind("<ButtonRelease-1>", self._release)
        self.view.bind("<Button-3>", self._popup)
        # Ctrl'lu olaylar daha ozel oldugu icin yukaridakilerin onune geciyor
        self.view.bind("<Control-Button-1>", self._resize_grab)
        self.view.bind("<Control-B1-Motion>", self._resize_drag)

        # tekerlek: buyut / kucult (Linux'ta ayri dugme olaylari geliyor)
        for w in (self.root, self.view):
            w.bind("<MouseWheel>", self._wheel)
            w.bind("<Button-4>", self._wheel)
            w.bind("<Button-5>", self._wheel)

        self.menu = tk.Menu(self.root, tearoff=0, bd=0, relief="flat",
                            bg="#1b1c20", fg="#e8e9ee",
                            activebackground="#2c2e36", activeforeground="#ffffff",
                            font=("Segoe UI", 9))
        if HAVE_PIL:
            self.menu.add_command(label="Ayarlar…", command=self._open_panel)
            self.menu.add_separator()
        self.menu.add_command(label="Büyüt",
                              command=lambda: self.set_zoom(self.zoom * ZOOM_MENU))
        self.menu.add_command(label="Küçült",
                              command=lambda: self.set_zoom(self.zoom / ZOOM_MENU))
        self.menu.add_command(label="Normal boyut", command=self.reset_zoom)
        self.menu.add_separator()
        self.menu.add_command(label="Ortala", command=self.center)
        self.menu.add_separator()
        self.menu.add_command(label="Kapat", command=self.root.destroy)

    def _popup(self, e):
        try:
            self.menu.tk_popup(e.x_root, e.y_root)
        finally:
            self.menu.grab_release()

    def _grab(self, e):
        # imlecin pencereye gore yeri; tasima sirasinda ekran koordinati
        # kullaniliyor ki gecikmeli winfo_x yuzunden isik titremesin
        x, y = self._xy
        self._dx, self._dy = e.x_root - x, e.y_root - y

    def _drag(self, e):
        if self._resizing or self.settings["lock"]:
            return
        x, y = e.x_root - self._dx, e.y_root - self._dy
        self._xy = (x, y)
        self.root.geometry(f"+{x}+{y}")
        self._layout()

    def _save_pos(self, _e=None):
        try:
            with open(POS_FILE, "w", encoding="utf-8") as f:
                f.write("%d,%d" % self._xy)
        except Exception:
            pass

    def center(self):
        x = (self.root.winfo_screenwidth() - self._size[0]) // 2
        y = int(6 * self.dpi)
        self._xy = (x, y)
        self.root.geometry(f"+{x}+{y}")
        self._layout()
        self._save_pos()

    # ---------- dongu ----------

    def poll(self):
        state, label = read_state()
        if (state, label) != (self.state, self.label):
            self.state, self.label = state, label
            if self._chip_on:
                self._draw_chip()
            if self._cap_on:
                self._render_caption()
                self._layout()
        self._track_pointer()
        self.root.after(POLL_MS, self.poll)

    def animate(self):
        cfg = STATES[self.state]
        active = cfg["idx"]

        t = time.perf_counter() - self._t0
        lo, hi = (0.70, 0.92) if self.state == "green" else (0.40, 1.0)
        if not cfg["pulse"]:
            intensity = 0.82       # kirmizi sabit yanar
        elif self.settings["pulse"]:
            k = 0.5 + 0.5 * math.sin(2 * math.pi * cfg["pulse"] * t)
            intensity = lo + (hi - lo) * k
        else:
            intensity = (lo + hi) / 2.0     # nabiz kapali: ortada sabit

        # eski lamba soner, yenisi yanar
        for i in range(3):
            tgt = 1.0 if i == active else 0.0
            self.fade[i] += (tgt - self.fade[i]) * 0.20
            if abs(self.fade[i] - tgt) < 0.004:
                self.fade[i] = tgt

        steps = tuple(
            max(0, min(20, int(round(self.fade[i] *
                                     (intensity if i == active else 0.62) * 20))))
            for i in range(3))

        self._steps = steps
        if steps != self._sig:
            self._paint(steps)

        self.root.after(FRAME_MS, self.animate)

    def _paint(self, steps):
        self._sig = steps
        if self.renderer:
            self._photo = ImageTk.PhotoImage(self.renderer.frame(steps))
            self.view.configure(image=self._photo)
        else:
            for i, item in enumerate(self.f_lamps):
                col = blend(blend(LAMP_RGB[i], LAMP_OFF, 0.90),
                            LAMP_RGB[i], steps[i] / 20.0)
                self.view.itemconfig(item, fill="#%02x%02x%02x" % col)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    _lock = acquire_singleton()
    if not _lock:
        sys.exit(0)              # zaten bir HUD acik
    write_pid()
    try:
        HUD().run()
    finally:
        clear_pid()

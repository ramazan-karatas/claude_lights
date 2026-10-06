# -*- coding: utf-8 -*-
r"""
Claude Code HUD - minik bir trafik lambasi.

Ekranin ustunde duran, her zaman en onde, surukleyebildiginiz kucuk bir
sinyal govdesi. State dosyasini (%TEMP%\cc_hud_state.txt) surekli okur;
hooklar oraya "green" / "yellow" / "red" yazar. "green|Ozel yazi"
bicimindeki etiketler de okunur; ayarlardan durum yazisi acilirsa isigin
altinda gosterilir.

  Sol tik + surukle        : tasi (konum hatirlanir)
  Alttaki tutamak          : oku surukle = boyutlandir, disli = ayarlar
  Tekerlek                 : boyutlandir
  Ctrl + sol tik + surukle : boyutlandir
  Sag tik                  : menu (Ayarlar / Buyut / Kucult / Normal boyut /
                             Ortala / Kapat)

Ayarlardan iki tasarim (Klasik, Sivi cam) ve iki tema (Siyah, Beyaz)
secilir. Sivi cam tasariminda govdeler arkadaki masaustunu bulanik ve
kenarlarda kirilmis gosterir. Bunun icin pencereler ekran yakalamadan haric
tutuluyor; yani bu tasarimda HUD ekran goruntulerinde ve kayitlarda gorunmez.

Gercek bir sinyal diregindeki gibi ustte kirmizi, ortada sari, altta yesil
lamba vardir. Yalnizca sirasi gelen yanar, otekiler sonuk cam gibi kalir;
durum degisince eski lamba soner, yenisi yanar.

Pencereler Tk'nin kendi cizimini kullanmaz: her biri piksel basina saydam
bir bitmap gosterir (UpdateLayeredWindow). Boylece kenarlar her zeminde
temiz, golgeler yumusak ve cam gercekten arkasini gosterebiliyor.
"""

import os
import sys
import json
import math
import time
import ctypes
import tempfile
import tkinter as tk
from ctypes import wintypes as wt

from PIL import (Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter,
                 ImageFont)

STATE_FILE = os.path.join(tempfile.gettempdir(), "cc_hud_state.txt")
POS_FILE = os.path.join(tempfile.gettempdir(), "cc_hud_pos.txt")
ZOOM_FILE = os.path.join(tempfile.gettempdir(), "cc_hud_zoom.txt")
SETTINGS_FILE = os.path.join(tempfile.gettempdir(), "cc_hud_settings.json")

POLL_MS = 150        # durum dosyasi okuma araligi
FRAME_MS = 33        # ~30 fps animasyon
BACKDROP_MS = 250    # sivi cam: arkadaki masaustunu yeniden okuma araligi
BACKDROP_EDGE = 10   # kenar kirilmasi icin govdenin disindan da okunan pay

# Boyut surekli: tek sinir alt/ust uc. Yeniden cizim yalnizca pencerenin tam
# sayi piksel olcusu degistiginde yapiliyor, yani gecisler 1 piksel
# inceliginde ve puruzsuz.
ZOOM_MIN = 0.55
ZOOM_MAX = 3.30
DEFAULT_ZOOM = 1.0
ZOOM_WHEEL = 1.10    # bir tekerlek tiki
ZOOM_MENU = 1.25     # menuden buyut/kucult

# Gorunum secenekleri
DESIGNS = ("solid", "glass")
THEMES = ("dark", "light")
CHOICES = {"design": DESIGNS, "theme": THEMES}
CHOICE_LABELS = {"solid": "Klasik", "glass": "Sıvı cam",
                 "dark": "Siyah", "light": "Beyaz"}

DEFAULT_SETTINGS = {
    "design": "solid",   # klasik ya da sivi cam
    "theme": "dark",     # siyah ya da beyaz
    "topmost": True,     # her zaman ustte
    "pulse": True,       # nabiz animasyonu
    "lock": False,       # konumu kilitle
    "label": False,      # durum yazisini goster
}

# Isigin altinda beliren tutamac: solda boyutlandirma oku, sagda disli
CHIP_W = 44          # tutamac genisligi
CHIP_H = 13          # tutamac yuksekligi
CHIP_SPLIT = 27      # ok ile disli arasindaki cizgi (soldan)
CHIP_GAP = 5         # ustteki ogeyle (isik ya da yazi) tutamac arasi
CHIP_SHOW_MS = 320   # uzerine gelince bu kadar bekleyip ac
CHIP_HIDE_MS = 480   # ayrilinca bu kadar bekleyip kapat

# Durum yazisi: isigin altinda, isikla birlikte buyuyup kuculen bir plaka
CAP_PX = 11          # yazi boyu (boyut orani 1.0'da)
CAP_MIN_PX = 9       # en kucuk boyutta bile okunur kalsin
CAP_GAP = 4          # govdeyle plaka arasi
CAP_MAX_CHARS = 48   # cok uzun ozel etiketler kisaltilir

# Ayarlar paneli
PANEL_W = 236
PANEL_HEAD = 40
PANEL_ROW = 34
PANEL_FOOT = 40
PANEL_PAD = 16
PANEL_GAP = 10       # isikla panel arasi
PANEL_SHADOW = 14    # panel golgesi icin kenar payi

ACCENT_RGB = (52, 211, 153)
KNOB_RGB = (246, 247, 249)

FONTS_DIR = os.path.join(os.environ["WINDIR"], "Fonts")
UI_FONT = "segoeui.ttf"
UIB_FONT = "seguisb.ttf"        # Segoe UI Semibold
# Simge yazisi: Windows 11'de Segoe Fluent Icons, Windows 10'da MDL2 Assets
ICON_FONT = ("SegoeIcons.ttf"
             if os.path.exists(os.path.join(FONTS_DIR, "SegoeIcons.ttf"))
             else "segmdl2.ttf")
GEAR_GLYPH = ""
CLOSE_GLYPH = ""

# Olculer (mantiksal piksel; DPI'ya gore olceklenir)
MARGIN = 6           # govde cevresindeki pay - golge ve kenar yumusatmasi icin
LAMP_R = 6           # lamba yaricapi
LAMP_PITCH = 18      # lamba merkezleri arasi dikey mesafe
BOX_PAD_X = 9        # govde ici yatay pay
BOX_PAD_Y = 9        # govde ici dikey pay
BOX_W = 2 * BOX_PAD_X + 2 * LAMP_R
BOX_H = 2 * BOX_PAD_Y + 2 * LAMP_PITCH + 2 * LAMP_R
BOX_R = 11           # govdenin kose yaricapi
BLOOM_R = 13         # yanan lambanin dagilma yaricapi

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


# ---------- gorunum: tasarim x tema ----------

def _style(design, theme, **colors):
    colors.update(design=design, theme=theme)
    return colors


# Klasik tasarimda govdeler dikey degradeli kati yuzeyler. Sivi camda dolgu
# arkadaki masaustunun bulanik goruntusu; ton, parlaklik, kenar isigi ve
# golge buradaki degerlerle ustune ekleniyor.
STYLES = {
    ("solid", "dark"): _style(
        "solid", "dark",
        box=((34, 36, 42), (16, 17, 21)), chip=((48, 50, 58), (27, 28, 34)),
        plate=((40, 42, 50), (22, 23, 28)), panel=((37, 39, 46), (22, 23, 28)),
        hair=(255, 255, 255, 58), gloss=72, outline=(0, 0, 0, 0), shadow=90,
        text=(233, 234, 240), muted=(146, 150, 162), line=(48, 50, 58, 255),
        toggle_off=((60, 63, 72), (44, 46, 54)), track=(60, 63, 72, 255),
        knob_ring=(0, 0, 0, 0),
        seg_bg=((19, 20, 24), (25, 26, 31)), seg_on=((72, 75, 86), (57, 59, 68)),
        seg_on_text=(255, 255, 255), press=(255, 255, 255, 26),
        glyph=(168, 172, 184), gear=(190, 194, 205), divider=(70, 73, 84, 255),
        socket=(6, 7, 9), lamp_off=(9, 10, 13), hover=(255, 255, 255, 12)),
    ("solid", "light"): _style(
        "solid", "light",
        box=((248, 249, 251), (220, 222, 228)), chip=((254, 254, 255), (232, 234, 238)),
        plate=((254, 254, 255), (234, 236, 240)), panel=((252, 252, 253), (240, 241, 244)),
        hair=(255, 255, 255, 220), gloss=0, outline=(0, 0, 0, 40), shadow=60,
        text=(26, 27, 32), muted=(104, 108, 118), line=(222, 224, 229, 255),
        toggle_off=((214, 217, 223), (201, 204, 211)), track=(210, 213, 220, 255),
        knob_ring=(0, 0, 0, 40),
        seg_bg=((224, 226, 231), (231, 233, 237)), seg_on=((255, 255, 255), (249, 249, 251)),
        seg_on_text=(26, 27, 32), press=(0, 0, 0, 16),
        glyph=(92, 96, 106), gear=(92, 96, 106), divider=(206, 209, 215, 255),
        socket=(52, 54, 62), lamp_off=(30, 32, 38), hover=(0, 0, 0, 10)),
    ("glass", "dark"): _style(
        "glass", "dark",
        tint=(14, 16, 22, 104), panel_tint=(14, 16, 22, 146), fallback=(38, 40, 48),
        bright=0.82, sat=1.5, blur=7.0, rim=(235, 85), sheen=46, glow=85, edge_light=26,
        outline=(0, 0, 0, 70), shadow=70,
        text=(242, 243, 247), muted=(184, 188, 198), line=(255, 255, 255, 36),
        toggle_off=((255, 255, 255, 54), (255, 255, 255, 38)), track=(255, 255, 255, 58),
        knob_ring=(0, 0, 0, 0),
        seg_bg=((0, 0, 0, 62), (0, 0, 0, 46)), seg_on=((255, 255, 255, 74), (255, 255, 255, 50)),
        seg_on_text=(255, 255, 255), press=(255, 255, 255, 30),
        glyph=(228, 231, 238), gear=(228, 231, 238), divider=(255, 255, 255, 58),
        socket=(6, 7, 9), lamp_off=(9, 10, 13), hover=(255, 255, 255, 16)),
    ("glass", "light"): _style(
        "glass", "light",
        tint=(255, 255, 255, 136), panel_tint=(255, 255, 255, 168), fallback=(232, 234, 238),
        bright=1.12, sat=1.4, blur=7.0, rim=(250, 130), sheen=70, glow=115, edge_light=40,
        outline=(0, 0, 0, 42), shadow=45,
        text=(22, 23, 28), muted=(76, 80, 90), line=(0, 0, 0, 28),
        toggle_off=((0, 0, 0, 46), (0, 0, 0, 32)), track=(0, 0, 0, 46),
        knob_ring=(0, 0, 0, 34),
        seg_bg=((0, 0, 0, 30), (0, 0, 0, 22)), seg_on=((255, 255, 255, 228), (255, 255, 255, 204)),
        seg_on_text=(22, 23, 28), press=(0, 0, 0, 16),
        glyph=(54, 58, 68), gear=(54, 58, 68), divider=(0, 0, 0, 44),
        socket=(40, 42, 50), lamp_off=(28, 30, 36), hover=(0, 0, 0, 12)),
}


# ---------- dosyalar ----------

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
                if key in CHOICES:
                    if value in CHOICES[key]:
                        settings[key] = value
                elif key in settings and isinstance(value, bool):
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


def read_zoom():
    """Kayitli boyut oranini dondurur."""
    try:
        with open(ZOOM_FILE, "r", encoding="utf-8") as f:
            z = float(f.read().strip())
    except Exception:
        return DEFAULT_ZOOM
    return max(ZOOM_MIN, min(ZOOM_MAX, z))


def window_size(scale):
    """Isik penceresinin bu olcekteki piksel olcusu - cizer kurmadan."""
    def s(v):
        return int(round(v * scale))
    return s(BOX_W + 2 * MARGIN), s(BOX_H + 2 * MARGIN)


# ---------- Windows ----------

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32")
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

GA_ROOT = 2
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x80000
ULW_ALPHA = 2
SRCCOPY = 0x00CC0020
WDA_NONE = 0
WDA_EXCLUDEFROMCAPTURE = 0x11


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                ("biPlanes", wt.WORD), ("biBitCount", wt.WORD),
                ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
                ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]


def _api(fn, restype, *argtypes):
    # 64 bit tutamaclar int'e sigmiyor; tipler acikca bildirilmeli.
    fn.restype = restype
    fn.argtypes = list(argtypes)


_api(user32.GetAncestor, wt.HWND, wt.HWND, wt.UINT)
_api(user32.GetWindowLongPtrW, ctypes.c_ssize_t, wt.HWND, ctypes.c_int)
_api(user32.SetWindowLongPtrW, ctypes.c_ssize_t, wt.HWND, ctypes.c_int, ctypes.c_ssize_t)
_api(user32.GetDC, wt.HDC, wt.HWND)
_api(user32.ReleaseDC, ctypes.c_int, wt.HWND, wt.HDC)
_api(user32.UpdateLayeredWindow, wt.BOOL, wt.HWND, wt.HDC, ctypes.POINTER(wt.POINT),
     ctypes.POINTER(wt.SIZE), wt.HDC, ctypes.POINTER(wt.POINT), wt.DWORD,
     ctypes.POINTER(BLENDFUNCTION), wt.DWORD)
_api(user32.SetWindowDisplayAffinity, wt.BOOL, wt.HWND, wt.DWORD)
_api(gdi32.CreateCompatibleDC, wt.HDC, wt.HDC)
_api(gdi32.CreateDIBSection, wt.HBITMAP, wt.HDC, ctypes.c_void_p, wt.UINT,
     ctypes.POINTER(ctypes.c_void_p), wt.HANDLE, wt.DWORD)
_api(gdi32.SelectObject, wt.HGDIOBJ, wt.HDC, wt.HGDIOBJ)
_api(gdi32.DeleteObject, wt.BOOL, wt.HGDIOBJ)
_api(gdi32.DeleteDC, wt.BOOL, wt.HDC)
_api(gdi32.BitBlt, wt.BOOL, wt.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int,
     ctypes.c_int, wt.HDC, ctypes.c_int, ctypes.c_int, wt.DWORD)
_api(kernel32.CreateMutexW, wt.HANDLE, wt.LPVOID, wt.BOOL, wt.LPCWSTR)


class _Dib:
    """Ekranla uyumlu, ustten alta 32 bitlik bir bitmap."""

    def __init__(self, w, h):
        self.screen = user32.GetDC(None)
        self.dc = gdi32.CreateCompatibleDC(self.screen)
        self.bits = ctypes.c_void_p()
        header = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, -h, 1, 32)
        self.bmp = gdi32.CreateDIBSection(self.dc, ctypes.byref(header), 0,
                                          ctypes.byref(self.bits), None, 0)
        self.old = gdi32.SelectObject(self.dc, self.bmp)

    def close(self):
        gdi32.SelectObject(self.dc, self.old)
        gdi32.DeleteObject(self.bmp)
        gdi32.DeleteDC(self.dc)
        user32.ReleaseDC(None, self.screen)


def present(hwnd, img, x, y):
    """RGBA goruntuyu pencerenin icerigi yap ve pencereyi (x, y)'ye koy."""
    w, h = img.size
    r, g, b, a = img.split()
    # Windows on carpilmis (premultiplied) BGRA bekliyor
    data = Image.merge("RGBA", (ImageChops.multiply(b, a), ImageChops.multiply(g, a),
                                ImageChops.multiply(r, a), a)).tobytes()
    dib = _Dib(w, h)
    try:
        ctypes.memmove(dib.bits, data, len(data))
        return bool(user32.UpdateLayeredWindow(
            hwnd, dib.screen, ctypes.byref(wt.POINT(x, y)), ctypes.byref(wt.SIZE(w, h)),
            dib.dc, ctypes.byref(wt.POINT(0, 0)), 0,
            ctypes.byref(BLENDFUNCTION(0, 0, 255, 1)), ULW_ALPHA))
    finally:
        dib.close()


def capture(x, y, w, h):
    """Ekranin bir bolgesi. HUD pencereleri yakalamadan haric tutuldugunda
    arkalarindaki goruntu gelir."""
    dib = _Dib(w, h)
    try:
        gdi32.BitBlt(dib.dc, 0, 0, w, h, dib.screen, x, y, SRCCOPY)
        data = ctypes.string_at(dib.bits, w * h * 4)
    finally:
        dib.close()
    return Image.frombuffer("RGBA", (w, h), data, "raw", "BGRA", 0, 1).convert("RGB")


class Layer:
    """Icerigini Tk degil, piksel basina saydam bir bitmap belirleyen pencere.

    Tamamen saydam pikseller tiklamayi alttaki pencereye gecirir. Tk'nin
    pencere olcusu de her seferinde ayni tutuluyor ki olay koordinatlari ve
    imlec dogru kalsin.
    """

    def __init__(self, win, topmost):
        self.win = win
        win.withdraw()
        win.overrideredirect(True)
        win.attributes("-topmost", topmost)
        # Tk dis pencereyi ancak ilk gosterimde olusturuyor; bunu ekran
        # disinda yapiyoruz. Pencere orada acik kaliyor: icerigi olmayan
        # katmanli pencere zaten gorunmez. Gizleyip yeniden gostermek ise Tk'nin
        # pencereyi diger katman kipine (SetLayeredWindowAttributes) almasina
        # yol aciyor; o kipte UpdateLayeredWindow reddedilip Tk'nin duz gri
        # zemini gorunuyordu.
        win.geometry("1x1+-32000+-32000")
        win.deiconify()
        win.update_idletasks()
        self.hwnd = user32.GetAncestor(win.winfo_id(), GA_ROOT)
        self._make_layered()
        self.img = None
        self.xy = None
        self.size = None
        self.visible = True

    def _make_layered(self):
        # Katmanli bayragini kaldirip geri koymak pencereyi kipsiz baslatir;
        # ardindan UpdateLayeredWindow kabul edilir.
        ex = user32.GetWindowLongPtrW(self.hwnd, GWL_EXSTYLE)
        user32.SetWindowLongPtrW(self.hwnd, GWL_EXSTYLE, ex & ~WS_EX_LAYERED)
        user32.SetWindowLongPtrW(self.hwnd, GWL_EXSTYLE, ex | WS_EX_LAYERED)

    def show(self, img, x, y):
        if self.visible and img is self.img and (x, y) == self.xy:
            return                  # zaten ekranda, ayni yerde
        if img.size != self.size or (x, y) != self.xy:
            self.win.geometry("%dx%d+%d+%d" % (img.size[0], img.size[1], x, y))
        self.img, self.size, self.xy = img, img.size, (x, y)
        if not self.visible:
            self.win.deiconify()
            self.visible = True
        if not present(self.hwnd, img, x, y):
            # Tk pencereyi yeniden gosterirken diger katman kipine almis
            # olabilir: kipi sifirlayip bir kez daha dene.
            self._make_layered()
            present(self.hwnd, img, x, y)

    def move(self, x, y):
        if self.img is not None:
            self.show(self.img, x, y)

    def hide(self):
        if self.visible:
            self.win.withdraw()
            self.visible = False

    def exclude_from_capture(self, on):
        user32.SetWindowDisplayAffinity(self.hwnd, WDA_EXCLUDEFROMCAPTURE if on
                                        else WDA_NONE)


def acquire_singleton():
    """Ayni anda tek HUD calissin.

    Ikinci kopya acilmaya calisirsa sessizce cikar; boylece bir baslatici
    (ya da elle acma) ust uste pencere birakamaz. Kilit isletim sistemine
    ait oldugu icin surec cokse bile kendiliginden serbest kalir.
    """
    handle = kernel32.CreateMutexW(None, True, "Local\\cc_hud_singleton")
    if not handle or ctypes.get_last_error() == 183:   # ALREADY_EXISTS
        return None
    return handle


def enable_dpi_awareness():
    ctypes.windll.shcore.SetProcessDpiAwareness(2)   # monitor basina


# ---------- cizim yardimcilari ----------

_FONTS = {}
_CACHE = {}


def load_font(name, px):
    """Windows yazi tipini istenen boyda verir (onbellekli)."""
    key = (name, px)
    font = _FONTS.get(key)
    if font is None:
        font = _FONTS[key] = ImageFont.truetype(os.path.join(FONTS_DIR, name), px)
    return font


def cached(key, make):
    value = _CACHE.get(key)
    if value is None:
        if len(_CACHE) > 600:
            _CACHE.clear()
        value = _CACHE[key] = make()
    return value


def rgba(color):
    return tuple(color) if len(color) == 4 else tuple(color) + (255,)


def blend(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def ss_mask(w, h, paint, ss=4):
    """Buyuk cizip kucultulmus maske - kenarlar yumusak kalsin."""
    m = Image.new("L", (w * ss, h * ss), 0)
    paint(ImageDraw.Draw(m), ss)
    return m.resize((w, h), Image.LANCZOS)


def rounded(w, h, r, outline=False):
    """Yuvarlak koseli dikdortgen maskesi ya da yalnizca kenar cizgisi."""
    def make():
        def paint(d, k):
            box = [0, 0, w * k - 1, h * k - 1]
            if outline:
                d.rounded_rectangle(box, radius=r * k, outline=255, width=max(2, k))
            else:
                d.rounded_rectangle(box, radius=r * k, fill=255)
        return ss_mask(w, h, paint)
    return cached(("round", w, h, round(r, 2), outline), make)


def ramp(w, h, top, bottom, power=1.0):
    """Ustten alta degisen gri ton (0-255)."""
    def make():
        g = Image.new("L", (w, h))
        d = ImageDraw.Draw(g)
        for y in range(h):
            t = (y / max(1, h - 1)) ** power
            d.line([(0, y), (w, y)], fill=int(round(top + (bottom - top) * t)))
        return g
    return cached(("ramp", w, h, top, bottom, power), make)


def gradient(w, h, top, bottom, power=1.0):
    """Ustten alta renk gecisi (RGB ya da RGBA)."""
    top, bottom = rgba(top), rgba(bottom)
    img = Image.new("RGBA", (w, h))
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = (y / max(1, h - 1)) ** power
        d.line([(0, y), (w, y)],
               fill=tuple(int(round(top[i] + (bottom[i] - top[i]) * t)) for i in range(4)))
    return img


def colored(size, color, mask=None):
    """Tek renkli katman; saydamligi maske ile rengin kendi saydamliginin carpimi."""
    c = rgba(color)
    layer = Image.new("RGBA", size, c[:3] + (0,))
    alpha = mask if mask is not None else Image.new("L", size, 255)
    if c[3] != 255:
        alpha = alpha.point(lambda v, k=c[3]: v * k // 255)
    layer.putalpha(alpha)
    return layer


def clip(img, mask):
    img.putalpha(ImageChops.multiply(img.getchannel("A"), mask))
    return img


def stroke(img, color, draw):
    """Bir maske cizip tek renkle uygula. Yazi ve cizgiler saydam katmana
    dogrudan cizilince kenarlari kararir; maske uzerinden bu olmuyor."""
    m = Image.new("L", img.size, 0)
    draw(ImageDraw.Draw(m))
    img.alpha_composite(colored(img.size, color, m))


def draw_icon(img, cx, cy, glyph, px, color):
    """Windows simge yazisindan bir simge cizer."""
    font = load_font(ICON_FONT, px)
    stroke(img, color, lambda d: d.text((cx, cy), glyph, font=font, fill=255,
                                        anchor="mm"))


def drop_shadow(w, h, r, pad, alpha):
    """Govdenin altina dusen yumusak golge; (w+2pad, h+2pad) boyunda."""
    def make():
        dy = max(1, int(round(pad * 0.22)))
        m = Image.new("L", (w + 2 * pad, h + 2 * pad), 0)
        m.paste(rounded(w, h, r), (pad, pad + dy))
        m = m.filter(ImageFilter.GaussianBlur(max(1.0, pad * 0.42)))
        return m.point(lambda v: v * alpha // 255)
    return colored((w + 2 * pad, h + 2 * pad), (0, 0, 0),
                   cached(("shadow", w, h, round(r, 2), pad, alpha), make))


def solid_body(w, h, r, kind, st):
    """Klasik yuzey: dikey degrade, ustte belirgin kil cizgisi."""
    top, bottom = st[kind]
    fill = rounded(w, h, r)
    ring = rounded(w, h, r, True)
    body = clip(gradient(w, h, top, bottom, 0.82), fill)
    hair = st["hair"]
    body.alpha_composite(colored((w, h), hair[:3], ImageChops.multiply(
        ring, ramp(w, h, hair[3], hair[3] * 23 // 100))))
    if kind == "box" and st["gloss"]:
        def make():
            cut = max(1, int(h * 0.26))
            fade = Image.new("L", (w, h), 0)
            fd = ImageDraw.Draw(fade)
            for y in range(cut):
                fd.line([(0, y), (w, y)], fill=int(255 * (1 - y / cut) ** 2.2))
            return ImageChops.multiply(ring, fade)
        gloss = cached(("gloss", w, h, round(r, 2)), make)
        body.alpha_composite(colored((w, h), (255, 255, 255, st["gloss"]), gloss))
    if st["outline"][3]:
        body.alpha_composite(colored((w, h), st["outline"], ring))
    return body


def glass_body(w, h, r, st, backdrop, tint, scale):
    """Sivi cam: arkadaki bulanik masaustu, kenarlarda kirilmis; ustunde ton,
    yumusak parlama ve kenar isigi."""
    fill = rounded(w, h, r)
    ring = rounded(w, h, r, True)
    if backdrop is None:
        base = Image.new("RGB", (w, h), st["fallback"])
    else:
        e = (backdrop.width - w) // 2
        inner = backdrop.crop((e, e, e + w, e + h))
        # Kenara yakin yerde govdenin disindaki goruntu iceri sikistirilarak
        # gosteriliyor: isik kalin camin kenarinda kirilmis gibi.
        squeezed = backdrop.resize((w, h), Image.BILINEAR)

        def lens():
            soft = fill.filter(ImageFilter.GaussianBlur(max(1.5, min(w, h) * 0.16)))
            return ImageChops.subtract(fill, soft).point(lambda v: min(255, int(v * 3.5)))
        band = cached(("lens", w, h, round(r, 2)), lens)
        base = Image.composite(squeezed, inner, band)
        base = ImageEnhance.Color(base).enhance(st["sat"])
        base = ImageEnhance.Brightness(base).enhance(st["bright"])
    body = base.convert("RGBA")
    body.alpha_composite(colored((w, h), tint))
    if backdrop is not None:
        # kirilan isik kenarda toplanir: bant biraz aydinlik
        body.alpha_composite(colored((w, h), (255, 255, 255, st["edge_light"]), band))

    def sheen():
        m = Image.new("L", (w, h), 0)
        ImageDraw.Draw(m).ellipse([-w * 0.25, -h * 0.75, w * 1.25, h * 0.38], fill=255)
        return m.filter(ImageFilter.GaussianBlur(max(1.0, min(w, h) * 0.15)))
    body.alpha_composite(colored((w, h), (255, 255, 255, st["sheen"]),
                                 cached(("sheen", w, h), sheen)))

    def rim():
        # kenar isigi: ustte guclu, ortada zayif, altta yansima kadar
        top, bottom = st["rim"]
        g = Image.new("L", (w, h))
        d = ImageDraw.Draw(g)
        for y in range(h):
            t = y / max(1, h - 1)
            d.line([(0, y), (w, y)], fill=int(top * (1 - t) ** 2 + bottom * t ** 2))
        return ImageChops.multiply(ring, g)
    body.alpha_composite(colored((w, h), (255, 255, 255),
                                 cached(("rim", w, h, round(r, 2), st["rim"]), rim)))

    def glow():
        # camin kalinligi: kenarin hemen icinde yumusak bir aydinlik
        soft = ring.filter(ImageFilter.GaussianBlur(max(1.0, 1.6 * scale)))
        return ImageChops.multiply(soft, fill).point(lambda v: v * st["glow"] // 255)
    body.alpha_composite(colored((w, h), (255, 255, 255),
                                 cached(("glow", w, h, round(r, 2), st["glow"]), glow)))
    if st["outline"][3]:
        body.alpha_composite(colored((w, h), st["outline"], ring))
    return clip(body, fill)


def card(w, h, r, pad, kind, st, scale, backdrop=None):
    """Golgesiyle bir yuzey: (w+2pad, h+2pad) RGBA, govde (pad, pad)'de."""
    img = drop_shadow(w, h, r, pad, st["shadow"])
    if st["design"] == "glass":
        tint = st["panel_tint"] if kind == "panel" else st["tint"]
        body = glass_body(w, h, r, st, backdrop, tint, scale)
    else:
        body = solid_body(w, h, r, kind, st)
    img.alpha_composite(body, (pad, pad))
    return img


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


class Renderer:
    """Isigin tum gorsel isini yapar; agir parcalari onbellekler."""

    def __init__(self, scale, st):
        self.scale = scale
        self.st = st
        self.pad = self.s(MARGIN)
        self.iw = self.s(BOX_W + 2 * MARGIN)
        self.ih = self.s(BOX_H + 2 * MARGIN)
        self.bw = self.iw - 2 * self.pad
        self.bh = self.ih - 2 * self.pad
        self.r = self.s(BOX_R)
        self.lamp_r = self.s(LAMP_R)
        self.bloom_r = self.s(BLOOM_R)

        # lamba merkezleri: x sabit, y yukaridan asagi
        self.lx = self.pad + self.s(BOX_PAD_X + LAMP_R)
        self.ly = tuple(self.pad + self.s(BOX_PAD_Y + LAMP_R + i * LAMP_PITCH)
                        for i in range(3))

        self._washes = {}
        self._blooms = {}
        self._lamps = {}
        self._fill = rounded(self.bw, self.bh, self.r)
        self._bloom_base = self._build_bloom_mask()
        self._wash_base = self._build_wash_mask()
        self.backdrop_version = None
        self.set_backdrop(None)

    def s(self, v):
        return int(round(v * self.scale))

    def set_backdrop(self, backdrop, version=None):
        """Govde: klasikte sabit, camda arkadaki masaustune gore."""
        self._base = card(self.bw, self.bh, self.r, self.pad, "box", self.st,
                          self.scale, backdrop)
        self.backdrop_version = version

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
            img = colored((self.bw, self.bh), LAMP_RGB[idx],
                          ImageChops.multiply(m, self._fill))
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
            img = colored(self._bloom_base.size, LAMP_RGB[idx],
                          self._bloom_base.point(lambda v: int(v * k)))
            if len(self._blooms) > 96:
                self._blooms.clear()
            self._blooms[key] = img
        return img

    def lamp(self, idx, step):
        """Lamba cami: step 0 sonuk, 20 tam yanik."""
        key = (idx, step)
        img = self._lamps.get(key)
        if img is not None:
            return img

        k = step / 20.0
        rgb = LAMP_RGB[idx]
        col = blend(blend(rgb, self.st["lamp_off"], 0.90), rgb, k)
        col = blend(col, (255, 255, 255), 0.13 * k)

        r = self.lamp_r
        size = r * 2 + 4
        c = size / 2.0
        socket = ss_mask(size, size, lambda d, s: d.ellipse(
            [(c - r - 1.4) * s, (c - r - 1.4) * s, (c + r + 1.4) * s, (c + r + 1.4) * s],
            fill=255))
        glass = ss_mask(size, size, lambda d, s: d.ellipse(
            [(c - r) * s, (c - r) * s, (c + r) * s, (c + r) * s], fill=255))

        # once koyu yuva, sonra cam - lamba govdeye oturmus gibi dursun
        img = colored((size, size), self.st["socket"], socket)
        top = blend(col, (255, 255, 255), 0.20 + 0.10 * k)
        bottom = blend(col, (0, 0, 0), 0.22 - 0.10 * k)
        img.alpha_composite(clip(gradient(size, size, top, bottom), glass))

        # cam boncuk parlamasi degil; ust yariya dusen genis, yumusak bir isik
        spec = ss_mask(size, size, lambda d, s: d.ellipse(
            [size * s * 0.18, size * s * 0.10, size * s * 0.82, size * s * 0.58],
            fill=int(42 + 34 * k)))
        spec = spec.filter(ImageFilter.GaussianBlur(max(1.0, self.scale * 1.4)))
        img.alpha_composite(colored((size, size), (255, 255, 255),
                                    ImageChops.multiply(spec, glass)))

        if len(self._lamps) > 96:
            self._lamps.clear()
        self._lamps[key] = img
        return img

    # ---------- kare ----------

    def frame(self, steps):
        img = self._base.copy()

        top = max(range(3), key=lambda i: steps[i])
        if steps[top]:
            img.alpha_composite(self._wash(top, steps[top]), (self.pad, self.pad))

        for i, st in enumerate(steps):
            if st:
                sp = self.bloom(i, st)
                img.alpha_composite(sp, (self.lx - sp.width // 2,
                                         self.ly[i] - sp.height // 2))
        for i, st in enumerate(steps):
            sp = self.lamp(i, st)
            img.alpha_composite(sp, (self.lx - sp.width // 2,
                                     self.ly[i] - sp.height // 2))
        return img


class Panel:
    """Ayarlar paneli: cizim ve tiklanabilir bolgeler (panel penceresine gore).

    Degismeyen kisim (zemin, baslik, satir yazilari) bir kez ciziliyor;
    secimler, anahtarlar, kaydirici ve uzerine gelme vurgusu her seferinde
    ustune ekleniyor - fare gezerken yeniden cizim hafif kalsin.
    """

    ROWS = (("design", "Tasarım", "seg"),
            ("theme", "Tema", "seg"),
            ("size", "Boyut", "slider"),
            ("topmost", "Her zaman üstte", "toggle"),
            ("pulse", "Nabız animasyonu", "toggle"),
            ("lock", "Konumu kilitle", "toggle"),
            ("label", "Durum yazısını göster", "toggle"))

    def __init__(self, scale, st):
        self.scale = scale
        self.st = st
        s = self.s
        self.m = s(PANEL_SHADOW)
        self.w = s(PANEL_W)
        self.pad = s(PANEL_PAD)
        self.head, self.row, self.foot = s(PANEL_HEAD), s(PANEL_ROW), s(PANEL_FOOT)
        self.h = self.head + self.row * len(self.ROWS) + self.foot
        self.iw, self.ih = self.w + 2 * self.m, self.h + 2 * self.m

        self.f_title = load_font(UIB_FONT, s(12.5))
        self.f_text = load_font(UI_FONT, s(11))
        self.f_small = load_font(UI_FONT, s(10.5))
        self.icon_px = s(9)

        m, w = self.m, self.w
        self.row_cy = {key: m + self.head + i * self.row + self.row // 2
                       for i, (key, _, _) in enumerate(self.ROWS)}
        self.foot_y = m + self.h - self.foot
        right = m + w - self.pad

        # boyut kaydiricisi: sagda yuzde, solunda kanal
        self.knob_r = s(6.5)
        self.slider_w = s(92)
        self.slider_h = s(16)
        self.slider_x = right - s(34) - s(6) - self.slider_w
        # topuzun merkezinin gidebildigi aralik (pencere koordinati)
        self.track = (self.slider_x + self.knob_r,
                      self.slider_x + self.slider_w - self.knob_r)

        # iki secenekli secimler (tasarim, tema)
        self.seg_w, self.seg_h = s(132), s(22)
        self.seg_x = right - self.seg_w

        self.close_c = (right - s(5), m + self.head // 2 + s(1))
        reset_w = int(self.f_small.getlength("Varsayılana dön"))

        hit = s(12)
        self.regions = [
            ("close", (self.close_c[0] - hit, self.close_c[1] - hit,
                       self.close_c[0] + hit, self.close_c[1] + hit)),
            ("slider", (self.slider_x - s(4), self.row_cy["size"] - self.row // 2,
                        self.slider_x + self.slider_w + s(4),
                        self.row_cy["size"] + self.row // 2)),
            ("reset", (m + self.pad - s(6), self.foot_y,
                       m + self.pad + reset_w + s(6), m + self.h)),
            ("quit", (right - int(self.f_small.getlength("Kapat")) - s(6), self.foot_y,
                      right + s(6), m + self.h)),
        ]
        for key, _, kind in self.ROWS:
            cy = self.row_cy[key]
            if kind == "seg":
                for value, (x0, x1) in self.seg_boxes(key):
                    self.regions.append(("seg:%s:%s" % (key, value),
                                         (x0, cy - self.seg_h // 2, x1, cy + self.seg_h // 2)))
            elif kind == "toggle":
                self.regions.append(("row:" + key, (m + s(6), cy - self.row // 2,
                                                    m + w - s(6), cy + self.row // 2)))

        self._toggles = {on: self._toggle(on) for on in (True, False)}
        rw, rh = w - 2 * s(6), self.row - s(4)
        self._row_glow = colored((rw, rh), st["hover"], rounded(rw, rh, s(7)))
        self.backdrop_version = None
        self.set_backdrop(None)

    def s(self, v):
        return int(round(v * self.scale))

    def hit(self, x, y):
        for name, (x0, y0, x1, y1) in self.regions:
            if x0 <= x <= x1 and y0 <= y <= y1:
                return name
        return None

    def seg_boxes(self, key):
        half = self.seg_w / 2.0
        return [(value, (int(self.seg_x + i * half), int(self.seg_x + (i + 1) * half)))
                for i, value in enumerate(CHOICES[key])]

    @staticmethod
    def frac(zoom):
        """Kaydirici logaritmik: her bolum ayni oranda buyutsun."""
        return math.log(zoom / ZOOM_MIN) / math.log(ZOOM_MAX / ZOOM_MIN)

    @staticmethod
    def zoom_at(frac):
        return ZOOM_MIN * (ZOOM_MAX / ZOOM_MIN) ** max(0.0, min(1.0, frac))

    def set_backdrop(self, backdrop, version=None):
        s, m, st = self.s, self.m, self.st
        img = card(self.w, self.h, s(12), m, "panel", st, self.scale, backdrop)
        stroke(img, st["text"], lambda d: d.text(
            (m + self.pad, m + self.head // 2 + s(1)), "Ayarlar",
            font=self.f_title, fill=255, anchor="lm"))
        lw = max(1, s(0.6))
        stroke(img, st["line"], lambda d: [
            d.line([(m + self.pad, y), (m + self.w - self.pad, y)], fill=255, width=lw)
            for y in (m + self.head, self.foot_y)])
        stroke(img, st["text"], lambda d: [
            d.text((m + self.pad, self.row_cy[key]), label, font=self.f_text,
                   fill=255, anchor="lm") for key, label, _ in self.ROWS])
        self._base = img
        self.backdrop_version = version

    def _pill(self, w, h, colors, edge=0):
        img = clip(gradient(w, h, colors[0], colors[1]), rounded(w, h, h / 2.0))
        if edge:
            img.alpha_composite(colored((w, h), (255, 255, 255, edge),
                                        rounded(w, h, h / 2.0, True)))
        return img

    def _toggle(self, on):
        s, st = self.s, self.st
        w, h = s(28), s(16)
        if on:
            t = self._pill(w, h, (blend(ACCENT_RGB, (255, 255, 255), 0.08),
                                  blend(ACCENT_RGB, (0, 0, 0), 0.18)), 40)
        else:
            t = self._pill(w, h, st["toggle_off"], 40 if st["theme"] == "dark" else 0)
        kr = h / 2.0 - s(2.5)
        kx = w - h / 2.0 if on else h / 2.0
        knob = ss_mask(w, h, lambda d, k: d.ellipse(
            [(kx - kr) * k, (h / 2.0 - kr) * k, (kx + kr) * k, (h / 2.0 + kr) * k], fill=255))
        t.alpha_composite(colored((w, h), KNOB_RGB, knob))
        if st["knob_ring"][3]:
            ring = ss_mask(w, h, lambda d, k: d.ellipse(
                [(kx - kr) * k, (h / 2.0 - kr) * k, (kx + kr) * k, (h / 2.0 + kr) * k],
                outline=255, width=k))
            t.alpha_composite(colored((w, h), st["knob_ring"], ring))
        return t

    def _slider(self, frac):
        w, h, kr, st = self.slider_w, self.slider_h, self.knob_r, self.st
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        cy, th = h / 2.0, self.scale * 3.2
        x0, x1 = kr, w - kr
        kx = x0 + (x1 - x0) * max(0.0, min(1.0, frac))

        def bar(xa, xb):
            return ss_mask(w, h, lambda d, k: d.rounded_rectangle(
                [xa * k, (cy - th / 2) * k, xb * k, (cy + th / 2) * k],
                radius=th / 2 * k, fill=255))

        img.alpha_composite(colored((w, h), st["track"], bar(x0, x1)))
        if kx > x0 + 1:
            img.alpha_composite(colored((w, h), ACCENT_RGB, bar(x0, kx)))
        knob = ss_mask(w, h, lambda d, k: d.ellipse(
            [(kx - kr) * k, (cy - kr) * k, (kx + kr) * k, (cy + kr) * k], fill=255))
        img.alpha_composite(colored((w, h), KNOB_RGB, knob))
        if st["knob_ring"][3]:
            ring = ss_mask(w, h, lambda d, k: d.ellipse(
                [(kx - kr) * k, (cy - kr) * k, (kx + kr) * k, (cy + kr) * k],
                outline=255, width=k))
            img.alpha_composite(colored((w, h), st["knob_ring"], ring))
        return img

    def _segments(self, img, key, current, hover):
        s, st = self.s, self.st
        cy = self.row_cy[key]
        top = cy - self.seg_h // 2
        img.alpha_composite(self._pill(self.seg_w, self.seg_h, st["seg_bg"]),
                            (self.seg_x, top))
        inset = s(2)
        for value, (x0, x1) in self.seg_boxes(key):
            on = value == current
            if on:
                pill = self._pill(x1 - x0 - 2 * inset, self.seg_h - 2 * inset,
                                  st["seg_on"], 30 if st["theme"] == "dark" else 0)
                img.alpha_composite(pill, (x0 + inset, top + inset))
            name = "seg:%s:%s" % (key, value)
            color = (st["seg_on_text"] if on else
                     st["text"] if hover == name else st["muted"])
            stroke(img, color, lambda d, x0=x0, x1=x1, value=value: d.text(
                ((x0 + x1) / 2.0, cy), CHOICE_LABELS[value], font=self.f_small,
                fill=255, anchor="mm"))

    def image(self, settings, zoom, hover):
        s, m, st = self.s, self.m, self.st
        img = self._base.copy()
        if hover and hover.startswith("row:"):
            g = self._row_glow
            img.alpha_composite(g, (m + s(6), self.row_cy[hover[4:]] - g.height // 2))

        for key, _, kind in self.ROWS:
            cy = self.row_cy[key]
            if kind == "seg":
                self._segments(img, key, settings[key], hover)
            elif kind == "toggle":
                t = self._toggles[bool(settings[key])]
                img.alpha_composite(t, (m + self.w - self.pad - t.width, cy - t.height // 2))

        sl = self._slider(self.frac(zoom))
        img.alpha_composite(sl, (self.slider_x, self.row_cy["size"] - sl.height // 2))
        stroke(img, st["muted"], lambda d: d.text(
            (m + self.w - self.pad, self.row_cy["size"]), "%d%%" % round(zoom * 100),
            font=self.f_small, fill=255, anchor="rm"))
        stroke(img, st["text"] if hover == "reset" else st["muted"], lambda d: d.text(
            (m + self.pad, self.foot_y + self.foot // 2), "Varsayılana dön",
            font=self.f_small, fill=255, anchor="lm"))
        stroke(img, (232, 72, 66) if hover == "quit" else st["muted"], lambda d: d.text(
            (m + self.w - self.pad, self.foot_y + self.foot // 2), "Kapat",
            font=self.f_small, fill=255, anchor="rm"))
        draw_icon(img, self.close_c[0], self.close_c[1], CLOSE_GLYPH, self.icon_px,
                  st["text"] if hover == "close" else st["muted"])
        return img


class HUD:
    def __init__(self):
        enable_dpi_awareness()
        self.root = tk.Tk()
        self.dpi = max(1.0, min(2.5, self.root.winfo_fpixels("1i") / 96.0))
        self.settings = read_settings()
        self.style = STYLES[(self.settings["design"], self.settings["theme"])]
        self.light = Layer(self.root, self.settings["topmost"])

        self.state, self.label = read_state()
        # her lambanin 0..1 arasi sonme/yanma seviyesi
        self.fade = [1.0 if STATES[self.state]["idx"] == i else 0.0 for i in range(3)]
        self._sig = None
        self._steps = None
        self._t0 = time.perf_counter()

        # Pencerelerin konumu burada tutuluyor; Tk'ye sorulmuyor.
        self._xy = (0, 0)
        self._size = (0, 0)
        self.zoom = read_zoom()
        self._renderers = {}
        self.renderer = None
        self._pending_zoom = None
        self._zoom_job = None
        self._move_job = None
        self._anchor = None

        # tasima ve boyutlandirma
        self._dx = self._dy = 0
        self._grab_off = 0
        self._resizing = False

        # alttaki tutamac (ok + disli)
        self.chip = None
        self._chip_on = False
        self._chip_xy = (0, 0)
        self._chip_size = (0, 0)
        self._chip_key = None
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
        self._cap_spec = None
        self._cap_key = None

        # ayarlar paneli
        self.panel = None
        self._panel = None
        self._panel_open = False
        self._panel_side = "right"
        self._panel_xy = (0, 0)
        self._panel_hover = None
        self._slider_drag = False
        self._track_x = (0, 1)
        self._panel_key = None

        # sivi cam: her pencerenin arkasindaki son goruntu
        self._backdrops = {}

        w, h = self._build_size()
        self._size = (w, h)
        self._place(w)
        self.light.exclude_from_capture(self.glass)
        self._bind()
        if self.settings["label"]:
            self._show_caption()
        self.poll()
        self.animate()
        self._backdrop_tick()

    @property
    def glass(self):
        return self.style["design"] == "glass"

    # ---------- yardimci pencereler ----------

    def _make_layer(self, topmost):
        layer = Layer(tk.Toplevel(self.root), topmost)
        layer.exclude_from_capture(self.glass)
        return layer

    def _lpad(self, zoom=None):
        """Isik penceresinin govde etrafindaki saydam kenar payi."""
        return int(round(MARGIN * self.dpi * (self.zoom if zoom is None else zoom)))

    def _cluster_half(self):
        """Isik + (varsa) altindaki yazi: yarim genislik."""
        cap_w = self._cap_size[0] if self._cap_on else 0
        return max(self._size[0], cap_w) / 2.0

    def _backdrop(self, name, x, y, w, h):
        """Bir govdenin arkasindaki masaustu, bulanik. Kenar kirilmasi icin
        biraz genis okunuyor. Degismediyse onceki sonuc ve surumu doner."""
        e = int(round(BACKDROP_EDGE * self.dpi))
        rect = (x - e, y - e, w + 2 * e, h + 2 * e)
        raw = capture(*rect)
        digest = hash(raw.tobytes())
        prev = self._backdrops.get(name)
        if prev is not None and prev[0] == rect and prev[1] == digest:
            return prev[2], prev[3]
        img = raw.filter(ImageFilter.GaussianBlur(self.style["blur"] * self.dpi))
        version = prev[3] + 1 if prev is not None else 1
        self._backdrops[name] = (rect, digest, img, version)
        return img, version

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
            # Iki pencerenin saydam kenar paylari ust uste biniyor; gorunen
            # aralik govdeyle plaka arasinda tam CAP_GAP kadar.
            self._cap_xy = (int(round(cx - cw / 2.0)),
                            y + h - self._lpad() + int(round(CAP_GAP * sc)) - m)
            self._render_caption()
            bottom = self._cap_xy[1] + ch

        if self._chip_on:
            _, pad, cw, chh, _ = self._chip_metrics()
            bw, bh = cw + 2 * pad, chh + 2 * pad
            gap = int(round(CHIP_GAP * self.dpi))
            gx = int(round(cx - bw / 2.0))
            gy = bottom + gap - pad
            if gy + bh > sh - 4:                  # asagi sigmiyorsa ustte goster
                gy = y - bh - gap + pad
            self._chip_xy = (max(2, min(sw - bw - 2, gx)), max(2, gy))
            self._chip_size = (bw, bh)
            self._render_chip()

        if self._panel_open:
            self._place_panel()
            self._render_panel()

    # ---------- isik ----------

    def _refresh_light_glass(self):
        """Camda isigin arkasini yeniden oku; degistiyse True."""
        if not self.glass:
            return False
        r = self.renderer
        x, y = self._xy
        bd, version = self._backdrop("light", x + r.pad, y + r.pad, r.bw, r.bh)
        if version == r.backdrop_version:
            return False
        r.set_backdrop(bd, version)
        return True

    def _paint(self):
        if self._steps is None:
            return
        self._sig = self._steps
        self.light.show(self.renderer.frame(self._steps), *self._xy)

    # ---------- alttaki tutamac: ok + disli ----------

    def _chip_metrics(self):
        s = self.dpi
        return (s, int(round(5 * s)), int(round(CHIP_W * s)),
                int(round(CHIP_H * s)), int(round(CHIP_SPLIT * s)))

    def _chip_image(self, grip_hot, gear_hot, backdrop):
        st = self.style
        s, pad, w, h, split = self._chip_metrics()
        img = card(w, h, h / 2.0, pad, "chip", st, s, backdrop)
        if gear_hot:                           # panel acikken disli kismi vurgulu
            lit = Image.new("L", img.size, 0)
            ImageDraw.Draw(lit).rectangle([pad + split, pad, pad + w, pad + h], fill=255)
            body = Image.new("L", img.size, 0)
            body.paste(rounded(w, h, h / 2.0), (pad, pad))
            img.alpha_composite(colored(img.size, st["press"],
                                        ImageChops.multiply(lit, body)))
        stroke(img, st["divider"], lambda d: d.line(
            [(pad + split, pad + int(round(3 * s))),
             (pad + split, pad + h - int(round(3 * s)))],
            fill=255, width=max(1, int(round(0.6 * s)))))

        # Dikey cift yonlu ok: buranin boyut icin oldugunu anlatiyor (Windows'un
        # dikey boyutlandirma imleciyle ayni isaret). Suruklerken yanan
        # lambanin rengini aliyor.
        cx, cy = pad + split / 2.0 + 0.5 * s, pad + h / 2.0
        a, hw, hh, sw = 4.9 * s, 3.0 * s, 2.8 * s, 0.8 * s  # yarim boy, uc, govde
        iw, ih = img.size

        def arrow(dd, k):
            for tip, base in ((cy - a, cy - a + hh), (cy + a, cy + a - hh)):
                dd.polygon([(cx * k, tip * k), ((cx - hw) * k, base * k),
                            ((cx + hw) * k, base * k)], fill=255)
            dd.rectangle([(cx - sw) * k, (cy - a + hh - 0.3 * s) * k,
                          (cx + sw) * k, (cy + a - hh + 0.3 * s) * k], fill=255)

        color = STATES[self.state]["rgb"] if grip_hot else st["glyph"]
        img.alpha_composite(colored((iw, ih), color, ss_mask(iw, ih, arrow).point(
            lambda v: v * (255 if grip_hot else 215) // 255)))

        draw_icon(img, pad + split + (w - split) / 2.0, cy + 0.3 * s, GEAR_GLYPH,
                  int(round(8.5 * s)), st["text"] if gear_hot else st["gear"])
        return img

    def _render_chip(self):
        if not self._chip_on:
            return
        grip_hot = self._grip_dragging
        gear_hot = self._panel_open or self._gear_down
        bd, version = None, None
        if self.glass:
            _, pad, w, h, _ = self._chip_metrics()
            bd, version = self._backdrop("chip", self._chip_xy[0] + pad,
                                         self._chip_xy[1] + pad, w, h)
        key = (grip_hot, gear_hot, self.state if grip_hot else None,
               id(self.style), version)
        if key != self._chip_key:
            self._chip_img = self._chip_image(grip_hot, gear_hot, bd)
            self._chip_key = key
        self.chip.show(self._chip_img, *self._chip_xy)

    def _show_chip(self):
        if self.chip is None:
            self.chip = self._make_layer(topmost=True)
            win = self.chip.win
            win.bind("<Button-1>", self._chip_press)
            win.bind("<B1-Motion>", self._chip_move)
            win.bind("<ButtonRelease-1>", self._chip_release)
            win.bind("<Motion>", self._chip_cursor)
        self._chip_on = True
        self._layout()
        self.chip.win.lift()
        self._away_at = None

    def _hide_chip(self):
        self._chip_on = False
        self._near_at = self._away_at = None
        if self.chip is not None:
            self.chip.hide()

    def _chip_cursor(self, e):
        # Imlec de anlatsin: okun uzerinde dikey boyutlandirma, dislide el.
        _, pad, _, _, split = self._chip_metrics()
        cursor = "hand2" if e.x >= pad + split else "sb_v_double_arrow"
        if self.chip.win.cget("cursor") != cursor:
            self.chip.win.configure(cursor=cursor)

    def _chip_press(self, e):
        _, pad, _, _, split = self._chip_metrics()
        if e.x >= pad + split:                 # sag yari: disli
            self._gear_down = True
            self._render_chip()
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
        self._render_chip()

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
                self._render_chip()
            return
        if self._grip_dragging:
            # Bekleyen son boyut, capa birakilmadan once uygulanmali; yoksa
            # merkez capasiyla uygulanip isik bir an zipliyordu.
            self._flush_zoom()
            self._grip_dragging = False
            self._anchor = None
            self._save_zoom()
            self._save_pos()
            self._layout()

    # ---------- durum yazisi ----------

    def _caption_text(self):
        text = self.label or STATES[self.state]["label"]
        if len(text) > CAP_MAX_CHARS:
            text = text[:CAP_MAX_CHARS - 1].rstrip() + "…"
        return text

    def _measure_caption(self):
        """Yazi plakasinin olcusu - konumu hesaplamak icin cizmeden once."""
        text = self._caption_text()
        px = max(CAP_MIN_PX, int(round(CAP_PX * self.dpi * self.zoom)))
        font = load_font(UIB_FONT, px)
        w = int(math.ceil(font.getlength(text))) + 2 * int(round(px * 0.85))
        h = int(round(px * 1.85))
        m = max(3, int(round(px * 0.5)))       # golge payi
        self._cap_spec = (text, px, w, h, m)
        self._cap_size = (w + 2 * m, h + 2 * m)
        self._cap_margin = m

    def _render_caption(self):
        text, px, w, h, m = self._cap_spec
        bd, version = None, None
        if self.glass:
            bd, version = self._backdrop("cap", self._cap_xy[0] + m,
                                         self._cap_xy[1] + m, w, h)
        key = (self._cap_spec, id(self.style), version)
        if key != self._cap_key:
            img = card(w, h, h / 2.0, m, "plate", self.style, self.dpi * self.zoom, bd)
            font = load_font(UIB_FONT, px)
            stroke(img, self.style["text"], lambda d: d.text(
                (m + w / 2.0, m + h / 2.0), text, font=font, fill=255, anchor="mm"))
            self._cap_img = img
            self._cap_key = key
        self.cap.show(self._cap_img, *self._cap_xy)

    def _show_caption(self):
        if self.cap is None:
            self.cap = self._make_layer(self.settings["topmost"])
            # yazi isigin parcasi: ondan da tasinip menu acilabilsin
            win = self.cap.win
            win.bind("<Button-1>", self._grab)
            win.bind("<B1-Motion>", self._drag)
            win.bind("<ButtonRelease-1>", self._release)
            win.bind("<Button-3>", self._popup)
            win.bind("<MouseWheel>", self._wheel)
        self._cap_on = True
        self._measure_caption()
        self._layout()

    def _hide_caption(self):
        self._cap_on = False
        if self.cap is not None:
            self.cap.hide()

    # ---------- ayarlar paneli ----------

    def _toggle_panel(self):
        if self._panel_open:
            self._close_panel()
        else:
            self._open_panel()

    def _open_panel(self):
        if self.panel is None:
            self.panel = self._make_layer(topmost=True)
            win = self.panel.win
            win.bind("<Button-1>", self._panel_press)
            win.bind("<B1-Motion>", self._panel_drag)
            win.bind("<ButtonRelease-1>", self._panel_release)
            win.bind("<Motion>", self._panel_motion)
            win.bind("<Leave>", lambda e: self._set_hover(None))
        if self._panel is None:
            self._panel = Panel(self.dpi, self.style)
        if not self._panel_open:
            # Saga sigiyorsa sag, yoksa sol. Panel acik kaldikca taraf sabit.
            x, _ = self._xy
            right = x + self._size[0] / 2.0 + self._cluster_half()
            gap = int(round(PANEL_GAP * self.dpi))
            fits = right + gap + self._panel.w <= self.root.winfo_screenwidth() - 4
            self._panel_side = "right" if fits else "left"
            self._panel_hover = None
        self._panel_open = True
        self._place_panel()
        self._render_panel()
        self.panel.win.lift()
        self._render_chip()

    def _close_panel(self):
        self._panel_open = False
        self._panel_hover = None
        self._slider_drag = False
        if self.panel is not None:
            self.panel.hide()
        self._render_chip()

    def _render_panel(self):
        if not self._panel_open:
            return
        p = self._panel
        if self.glass:
            bd, version = self._backdrop("panel", self._panel_xy[0] + p.m,
                                         self._panel_xy[1] + p.m, p.w, p.h)
            if version != p.backdrop_version:
                p.set_backdrop(bd, version)
        key = (p, tuple(sorted(self.settings.items())), round(self.zoom, 4),
               self._panel_hover, p.backdrop_version)
        if key != self._panel_key:
            self._panel_img = p.image(self.settings, self.zoom, self._panel_hover)
            self._panel_key = key
        self.panel.show(self._panel_img, *self._panel_xy)

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
        self._panel_xy = (max(2 - p.m, min(sw - p.iw + p.m - 2, px)),
                          max(2 - p.m, min(sh - p.ih + p.m - 2, py)))

    def _set_hover(self, region):
        if region != self._panel_hover:
            self._panel_hover = region
            self._render_panel()

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
        elif region == "quit":
            self.root.destroy()             # uygulamayi kapat
        elif region and region.startswith("seg:"):
            _, key, value = region.split(":")
            self._choose(key, value)
        elif region and region.startswith("row:"):
            self._toggle_setting(region[4:])

    def _panel_drag(self, e):
        if self._slider_drag:
            self._slider_to(e.x_root)

    def _panel_release(self, _e):
        if self._slider_drag:
            self._flush_zoom()
            self._slider_drag = False
            self._anchor = None
            self._save_zoom()
            self._save_pos()
            self._layout()

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

    def _choose(self, key, value):
        if self.settings[key] == value:
            return
        self.settings[key] = value
        save_settings(self.settings)
        self._apply_style()

    def _apply_style(self):
        """Tasarim ya da tema degisti: her seyi yeni gorunumle ciz."""
        self.style = STYLES[(self.settings["design"], self.settings["theme"])]
        for layer in (self.light, self.chip, self.cap, self.panel):
            if layer is not None:
                layer.exclude_from_capture(self.glass)
        self._renderers.clear()
        self._backdrops.clear()
        self._chip_key = self._cap_key = None
        self._build_size()
        self._refresh_light_glass()
        self._paint()
        if self._panel is not None:
            self._panel = Panel(self.dpi, self.style)
        self._layout()

    def _toggle_setting(self, key):
        self.settings[key] = not self.settings[key]
        save_settings(self.settings)
        self._apply_setting(key)
        self._render_panel()

    def _apply_setting(self, key):
        on = self.settings[key]
        if key == "topmost":
            self.root.attributes("-topmost", on)
            if self.cap is not None:
                self.cap.win.attributes("-topmost", on)
            # tutamac ve panel her zaman ustte; isigin altinda kalmasinlar
            for layer in (self.chip, self.panel):
                if layer is not None:
                    layer.win.lift()
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
        if (old["design"], old["theme"]) != (self.settings["design"], self.settings["theme"]):
            self._apply_style()
        for key in ("topmost", "label"):
            if self.settings[key] != old[key]:
                self._apply_setting(key)
        if self._panel_open:
            self._anchor = self._panel_anchor()
        self.set_zoom(DEFAULT_ZOOM)
        self._anchor = None
        self._save_zoom()
        self._save_pos()
        self._render_panel()

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
        px, py = self.root.winfo_pointerxy()
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
            self.root.after_cancel(self._zoom_job)
            self._zoom_job = None
        if self._pending_zoom is not None:
            z, self._pending_zoom = self._pending_zoom, None
            self.set_zoom(z)

    def _build_size(self):
        """Gecerli orana ve gorunume gore cizeri hazirlar, olcusunu dondurur."""
        # Surekli boyutta sonsuz cizer olabilir; anahtar olarak pencerenin
        # piksel olcusu kullaniliyor (ayni olcu = ayni cizim) ve son
        # kullanilanlardan birkaci tutuluyor.
        scale = self.dpi * self.zoom
        key = window_size(scale)
        r = self._renderers.get(key)
        if r is None:
            r = Renderer(scale, self.style)
            if len(self._renderers) > 8:
                self._renderers.clear()
            self._renderers[key] = r
        self.renderer = r
        return r.iw, r.ih

    def set_zoom(self, z):
        """Boyutu degistirir; nereye capalanacagini self._anchor belirler.

        Capa (tur, x, y):
          center         isik merkezi sabit (tekerlek, menu)
          top            govdenin ustu ve yatay merkez sabit (ayirici)
          cluster_right  govdenin ustu ve isik+yazi kumesinin sag kenari
          cluster_left   ... sol kenari (panel kaydiricisi: panel kipirdamaz)
        """
        z = max(ZOOM_MIN, min(ZOOM_MAX, z))
        if window_size(self.dpi * z) == self._size:
            # Pencere ayni boyda kaliyor; yalnizca paneldeki yuzde guncellensin.
            self.zoom = z
            self._render_panel()
            return

        x, y = self._xy
        w0, h0 = self._size
        anchor = self._anchor or ("center", x + w0 / 2.0, y + h0 / 2.0)
        self.zoom = z
        w, h = self._build_size()
        self._size = (w, h)
        if self._cap_on:
            self._measure_caption()

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
        self._xy = (max(-w + 24, min(sw - 24, int(round(nx)))),
                    max(-20, min(sh - 20, int(round(ny)))))

        # Yeni cizer = yeni boyutta resim; her zaman yeniden ciziliyor.
        self._refresh_light_glass()
        self._paint()
        self._layout()
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
        self.set_zoom(self.zoom * (ZOOM_WHEEL if e.delta > 0 else 1 / ZOOM_WHEEL))

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

    def _release(self, _e):
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

    def _place(self, w):
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

    def _bind(self):
        # Kok pencereye baglanan olaylar menu gibi alt pencerelerden de
        # geliyor; yalnizca isigin kendisinden gelenler isleniyor.
        def own(handler):
            return lambda e: handler(e) if e.widget is self.root else None

        root = self.root
        root.bind("<Button-1>", own(self._grab))
        root.bind("<B1-Motion>", own(self._drag))
        root.bind("<ButtonRelease-1>", own(self._release))
        root.bind("<Button-3>", own(self._popup))
        # Ctrl'lu olaylar daha ozel oldugu icin yukaridakilerin onune geciyor
        root.bind("<Control-Button-1>", own(self._resize_grab))
        root.bind("<Control-B1-Motion>", own(self._resize_drag))
        root.bind("<MouseWheel>", own(self._wheel))

        self.menu = tk.Menu(root, tearoff=0, bd=0, relief="flat",
                            bg="#1b1c20", fg="#e8e9ee",
                            activebackground="#2c2e36", activeforeground="#ffffff",
                            font=("Segoe UI", 9))
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
        self.menu.add_command(label="Kapat", command=root.destroy)

    def _popup(self, e):
        try:
            self.menu.tk_popup(e.x_root, e.y_root)
        finally:
            self.menu.grab_release()

    def _grab(self, e):
        # imlecin pencereye gore yeri; tasima ekran koordinatiyla yapiliyor
        x, y = self._xy
        self._dx, self._dy = e.x_root - x, e.y_root - y

    def _drag(self, e):
        if self._resizing or self.settings["lock"]:
            return
        self._xy = (e.x_root - self._dx, e.y_root - self._dy)
        # Fare olaylari cizimden hizli gelebiliyor; konum bosta bir kez uygulanir.
        if self._move_job is None:
            self._move_job = self.root.after_idle(self._flush_move)

    def _flush_move(self):
        self._move_job = None
        if self._refresh_light_glass():
            self._paint()
        else:
            self.light.move(*self._xy)
        self._layout()

    def _save_pos(self):
        try:
            with open(POS_FILE, "w", encoding="utf-8") as f:
                f.write("%d,%d" % self._xy)
        except Exception:
            pass

    def center(self):
        self._xy = ((self.root.winfo_screenwidth() - self._size[0]) // 2,
                    int(6 * self.dpi))
        self._flush_move()
        self._save_pos()

    # ---------- dongu ----------

    def poll(self):
        state, label = read_state()
        if (state, label) != (self.state, self.label):
            self.state, self.label = state, label
            self._render_chip()
            if self._cap_on:
                self._measure_caption()
                self._layout()
        self._track_pointer()
        self.root.after(POLL_MS, self.poll)

    def _backdrop_tick(self):
        # Sivi cam: arkadaki masaustu degistikce camlar da guncellensin.
        if self.glass:
            if self._refresh_light_glass():
                self._paint()
            if self._cap_on:
                self._render_caption()
            self._render_chip()
            self._render_panel()
        self.root.after(BACKDROP_MS, self._backdrop_tick)

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

        self._steps = tuple(
            max(0, min(20, int(round(self.fade[i] *
                                     (intensity if i == active else 0.62) * 20))))
            for i in range(3))
        if self._steps != self._sig:
            self._paint()

        self.root.after(FRAME_MS, self.animate)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    if not acquire_singleton():
        sys.exit(0)              # zaten bir HUD acik
    HUD().run()

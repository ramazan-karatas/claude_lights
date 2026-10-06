# -*- coding: utf-8 -*-
r"""
Claude Code HUD - minik bir trafik lambasi.

Ekranin ustunde duran, her zaman en onde, surukleyebildiginiz kucuk bir
sinyal govdesi. State dosyasini (%TEMP%\cc_hud_state.txt) surekli okur;
hooklar oraya "green" / "yellow" / "red" yazar.

  Sol tik + surukle        : tasi (konum hatirlanir)
  Altindaki tutamagi cek   : boyutlandir (asagi buyutur, yukari kucultur)
  Tekerlek                 : boyutlandir
  Ctrl + sol tik + surukle : boyutlandir
  Sag tik                  : menu (Buyut / Kucult / Normal boyut / Ortala / Kapat)

Fare isigin uzerine gelince altinda kucuk bir ayirici tutamac belirir;
uzaklasinca kaybolur. Secilen boyut da konum gibi hatirlanir.

Gercek bir sinyal diregindeki gibi ustte kirmizi, ortada sari, altta yesil
lamba vardir. Yalnizca sirasi gelen yanar, otekiler sonuk cam gibi kalir;
durum degisince eski lamba soner, yenisi yanar.

Not: "green|Ozel yazi" bicimindeki etiketler hala sorunsuz okunur ama
govdede yazi olmadigi icin gosterilmez - durumu yalnizca yanan lamba anlatir.

Pillow yoksa sade bir tkinter surumune duser.
"""

import os
import sys
import math
import time
import tempfile
import tkinter as tk

try:
    from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageTk
    HAVE_PIL = True
except ImportError:
    HAVE_PIL = False

STATE_FILE = os.path.join(tempfile.gettempdir(), "cc_hud_state.txt")
POS_FILE = os.path.join(tempfile.gettempdir(), "cc_hud_pos.txt")
ZOOM_FILE = os.path.join(tempfile.gettempdir(), "cc_hud_zoom.txt")
PID_FILE = os.path.join(tempfile.gettempdir(), "cc_hud.pid")

POLL_MS = 150    # durum dosyasi okuma araligi
FRAME_MS = 33    # ~30 fps animasyon

# Kullanicinin secebilecegi boyut kademeleri. Surekli olcek yerine kademe
# kullaniliyor: her kademenin cizici nesnesi onbelleklenebiliyor, tekerlegi
# hizli cevirince takilma olmuyor ve boyutlar tahmin edilebilir kaliyor.
# Boyut artik kademeli degil, surekli: tek sinir alt/ust uc. Yeniden cizim
# yalnizca pencerenin tam sayi piksel olcusu degistiginde yapiliyor, yani
# gecisler 1 piksel inceliginde ve puruzsuz.
ZOOM_MIN = 0.55
ZOOM_MAX = 3.30
DEFAULT_ZOOM = 1.0
ZOOM_WHEEL = 1.10    # bir tekerlek tiki
ZOOM_MENU = 1.25     # menuden buyut/kucult

# Isigin uzerine gelince altinda beliren kucuk ayirici (splitter) tutamaci
GRIP_W = 26          # tutamac genisligi
GRIP_H = 10          # tutamac yuksekligi
GRIP_R = 5           # kose yaricapi
GRIP_GAP = 5         # isikla tutamac arasi
GRIP_DOT = 1.6       # tutamactaki nokta yaricapi
GRIP_PITCH = 6       # noktalar arasi mesafe
GRIP_DOUBLE = 150    # bu kadar piksel surukleme boyutu iki katina cikarir
GRIP_SHOW_MS = 320   # uzerine gelince bu kadar bekleyip ac
GRIP_HIDE_MS = 480   # ayrilinca bu kadar bekleyip kapat
GRIP_TOP = (46, 48, 56)
GRIP_BOTTOM = (26, 27, 33)
GRIP_DOT_RGB = (168, 172, 184)

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
    "red":    {"rgb": (240, 92, 88),  "pulse": 0.00, "idx": 0},
    "yellow": {"rgb": (250, 198, 54), "pulse": 1.15, "idx": 1},
    "green":  {"rgb": (52, 211, 153), "pulse": 0.45, "idx": 2},
}
LAMP_RGB = tuple(STATES[name]["rgb"] for name in LAMP_ORDER)


def read_state():
    """Durum adini dondurur. Dosya "green" veya "green|Ozel yazi" olabilir."""
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            raw = f.read().strip()
    except Exception:
        return "red"
    if not raw:
        return "red"
    state = raw.split("|", 1)[0].strip().lower()
    return state if state in STATES else "red"


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


class HUD:
    def __init__(self):
        enable_dpi_awareness()
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
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

        self.state = read_state()
        # her lambanin 0..1 arasi sonme/yanma seviyesi
        self.fade = [1.0 if STATES[self.state]["idx"] == i else 0.0 for i in range(3)]
        self._photo = None
        self._sig = None
        self._resizing = False
        self._t0 = time.perf_counter()
        self.grip = None
        self._grip_on = False
        self._grip_size = (0, 0)
        self._grip_dragging = False
        self._drag_y = 0
        self._drag_zoom = DEFAULT_ZOOM
        self._anchor = None
        self._steps = None
        self._near_at = None
        self._away_at = None

        self.zoom = read_zoom()
        self._renderers = {}
        self._pending_zoom = None
        self.renderer = None
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
        self.poll()
        self.animate()

    # ---------- boyut cubugu ----------

    def _ss_mask(self, size, paint, ss=4):
        """Buyuk cizip kucultulmus maske - kenarlar yumusak kalsin."""
        w, h = size
        m = Image.new("L", (w * ss, h * ss), 0)
        paint(ImageDraw.Draw(m), ss)
        return m.resize((w, h), Image.LANCZOS)

    def _grip_metrics(self):
        s = self.dpi
        pad = int(round(5 * s))
        return s, pad, int(round(GRIP_W * s)), int(round(GRIP_H * s))

    def _grip_image(self, hot):
        """Kucuk ayirici tutamaci: uzeri uc noktali, hafif kabarik bir cip."""
        s, pad, w, h = self._grip_metrics()
        r = GRIP_R * s

        fill = self._ss_mask((w, h), lambda d, ss: d.rounded_rectangle(
            [0, 0, w * ss - 1, h * ss - 1], radius=r * ss, fill=255))
        ring = self._ss_mask((w, h), lambda d, ss: d.rounded_rectangle(
            [0, 0, w * ss - 1, h * ss - 1], radius=r * ss,
            outline=255, width=max(2, ss)))

        top = blend(GRIP_TOP, (255, 255, 255), 0.12) if hot else GRIP_TOP
        bottom = blend(GRIP_BOTTOM, (255, 255, 255), 0.08) if hot else GRIP_BOTTOM
        body = Image.new("RGB", (w, h))
        d = ImageDraw.Draw(body)
        for y in range(h):
            d.line([(0, y), (w, y)], fill=blend(top, bottom, y / max(1, h - 1)))
        body = body.convert("RGBA")
        body.putalpha(fill)
        edge = Image.new("RGBA", (w, h), (255, 255, 255, 0))
        edge.putalpha(ring.point(lambda v: v * 58 // 255))
        body = Image.alpha_composite(body, edge)

        img = Image.new("RGB", (w + 2 * pad, h + 2 * pad), KEY_RGB)
        img.paste(body, (pad, pad), body)

        # tutus noktalari - suruklerken yanan lambanin rengini aliyor
        iw, ih = img.size
        cx, cy = iw / 2.0, ih / 2.0
        dr, pitch = GRIP_DOT * s, GRIP_PITCH * s

        def dots(dd, ss):
            for k in (-1, 0, 1):
                x = cx + k * pitch
                dd.ellipse([(x - dr) * ss, (cy - dr) * ss,
                            (x + dr) * ss, (cy + dr) * ss], fill=255)

        m = self._ss_mask((iw, ih), dots)
        color = STATES[self.state]["rgb"] if hot else GRIP_DOT_RGB
        lay = Image.new("RGBA", (iw, ih), color + (0,))
        lay.putalpha(m.point(lambda v: v * (255 if hot else 205) // 255))
        img.paste(lay, (0, 0), lay)
        return img

    def _ensure_grip(self):
        if self.grip is not None:
            return
        self.grip = tk.Toplevel(self.root)
        self.grip.withdraw()
        self.grip.overrideredirect(True)
        self.grip.attributes("-topmost", True)
        self.grip.configure(bg=KEY_HEX)
        if HAVE_PIL and sys.platform == "win32":
            try:
                self.grip.attributes("-transparentcolor", KEY_HEX)
            except tk.TclError:
                pass
        self.grip_view = tk.Label(self.grip, bd=0, highlightthickness=0, bg=KEY_HEX)
        self.grip_view.pack()
        self.grip_view.bind("<Button-1>", self._grip_press)
        self.grip_view.bind("<B1-Motion>", self._grip_move)
        self.grip_view.bind("<ButtonRelease-1>", self._grip_release)

    def _draw_grip(self):
        self._grip_photo = ImageTk.PhotoImage(
            self._grip_image(self._grip_dragging))
        self.grip_view.configure(image=self._grip_photo)

    def _place_grip(self, lx=None, ly=None):
        s, pad, w, h = self._grip_metrics()
        bw, bh = w + 2 * pad, h + 2 * pad
        lw, lh = self._size
        if lx is None:
            lx, ly = self.root.winfo_x(), self.root.winfo_y()
        x = lx + (lw - bw) // 2
        y = ly + lh + int(round(GRIP_GAP * s)) - pad
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        if y + bh > sh - 4:                       # asagi sigmiyorsa ustte goster
            y = ly - bh - int(round(GRIP_GAP * s)) + pad
        x = max(2, min(sw - bw - 2, x))
        self._grip_size = (bw, bh)
        self.grip.geometry(f"{bw}x{bh}+{x}+{max(2, y)}")

    def _show_grip(self):
        if not HAVE_PIL:
            return
        self._ensure_grip()
        self._draw_grip()
        self._place_grip()
        self.grip.deiconify()
        self.grip.lift()
        self._grip_on = True
        self._away_at = None

    def _hide_grip(self):
        self._grip_on = False
        self._near_at = self._away_at = None
        if self.grip is not None:
            self.grip.withdraw()

    def _over(self, px, py, win, size, slack):
        """Imlec bu pencerenin uzerinde mi? (biraz pay birakarak)"""
        try:
            x, y = win.winfo_x(), win.winfo_y()
        except tk.TclError:
            return False
        w, h = size
        return (x - slack <= px <= x + w + slack and
                y - slack <= py <= y + h + slack)

    def _track_pointer(self):
        """Cubugu ac/kapat.

        <Enter>/<Leave> olaylari bu pencere icin guvenilir degil (hic odak
        almiyor, ustte duruyor ve imlec siçrayarak gelebiliyor); bu yuzden
        karar dogrudan imlec konumuna bakilarak veriliyor.
        """
        try:
            px, py = self.root.winfo_pointerxy()
        except tk.TclError:
            return
        now = time.perf_counter()
        on_light = self._over(px, py, self.root, self._size, 0)
        on_grip = (self._grip_on and self.grip is not None and
                  self._over(px, py, self.grip, self._grip_size, 10))

        if self._grip_dragging or on_light or on_grip:
            self._away_at = None
            if not self._grip_on:
                if self._near_at is None:
                    self._near_at = now
                elif now - self._near_at >= GRIP_SHOW_MS / 1000.0:
                    self._show_grip()
        else:
            self._near_at = None
            if self._grip_on:
                if self._away_at is None:
                    self._away_at = now
                elif now - self._away_at >= GRIP_HIDE_MS / 1000.0:
                    self._hide_grip()

    def _grip_press(self, e):
        # Referans basildigi anda donduruluyor: tutamac isikla birlikte yer
        # degistirse de surukleme kaymiyor (basili tutuldugu surece olaylar
        # zaten bu pencereye geliyor).
        self._grip_dragging = True
        self._drag_y = e.y_root
        self._drag_zoom = self.zoom
        self._anchor = (self.root.winfo_x() + self._size[0] / 2.0,
                        self.root.winfo_y() + self._size[1] / 2.0)
        self._away_at = None
        self._draw_grip()

    def _grip_release(self, _e=None):
        self._grip_dragging = False
        self._anchor = None
        self._save_zoom()
        self._save_pos()
        if self._grip_on:
            self._draw_grip()
            self._place_grip()

    def _grip_move(self, e):
        # Fare olaylari kareden sik gelebiliyor; hedef burada not edilip
        # animasyon dongusunde bir kez uygulaniyor.
        self._away_at = None
        dy = e.y_root - self._drag_y
        self._pending_zoom = self._drag_zoom * 2.0 ** (
            dy / (GRIP_DOUBLE * self.dpi))

    # ---------- boyut ----------

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

    def set_zoom(self, z, paint=True):
        """Kademeyi degistirir; isik yerinde buyuyup kuculsun diye merkez sabit."""
        z = max(ZOOM_MIN, min(ZOOM_MAX, z))
        self.zoom = z
        # Pencere olcusu ayni kaliyorsa yeniden cizmeye gerek yok: surukleme
        # sirasinda is yalnizca gercekten bir piksel degistiginde yapiliyor.
        if window_size(self.dpi * z) == self._size and self.renderer is not None:
            return
        # Capa noktasi: surukleme boyunca basta hesaplanan merkez kullanilir.
        # Her adimda yeniden olcmek tam sayi bolmesi yuzunden isigi birkac
        # piksel kaydiriyordu (titreme gibi gorunuyordu).
        if self._anchor is None:
            old_w, old_h = self._size
            anchor = (self.root.winfo_x() + old_w / 2.0,
                      self.root.winfo_y() + old_h / 2.0)
        else:
            anchor = self._anchor
        cx, cy = anchor

        w, h = self._build_size()
        self._size = (w, h)

        # Once yeni gorsel, hemen ardindan yeni geometri: ikisi ayni geri
        # cagirmada oldugu icin arada eski resim yeni pencerede gorunmuyor.
        if paint and self._steps is not None:
            self._paint(self._steps)

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = max(-w + 24, min(sw - 24, int(round(cx - w / 2.0))))
        y = max(-20, min(sh - 20, int(round(cy - h / 2.0))))
        self.root.geometry(f"{w}x{h}+{x}+{y}")

        if self._grip_on:
            self._draw_grip()
            # Yeni koordinatlar acikca veriliyor: winfo_x() geometri
            # degisiminden hemen sonra hala eski degeri dondurdugu icin
            # tutamac ortadan kayiyordu.
            self._place_grip(x, y)
            self.grip.lift()           # buyuyen isik cubugu ortmesin
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

    # Ctrl + sol tik surukleme: asagi cekince buyur, yukari cekince kuculur.
    # Dugme olaylari odak gerektirmedigi icin bu her zaman calisir.
    def _resize_grab(self, e):
        self._resizing = True
        self._ry = e.y_root
        self._rzoom = self.zoom
        self._anchor = (self.root.winfo_x() + self._size[0] / 2.0,
                        self.root.winfo_y() + self._size[1] / 2.0)

    def _resize_drag(self, e):
        if not self._resizing:
            return
        self._pending_zoom = self._rzoom * 2.0 ** (
            (e.y_root - self._ry) / (GRIP_DOUBLE * self.dpi))

    def _release(self, _e=None):
        if self._resizing:
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
        self._dx, self._dy = e.x, e.y

    def _drag(self, e):
        if self._resizing:
            return
        x = self.root.winfo_x() + e.x - self._dx
        y = self.root.winfo_y() + e.y - self._dy
        self.root.geometry(f"+{x}+{y}")
        if self._grip_on:
            self._place_grip()

    def _save_pos(self, _e=None):
        try:
            with open(POS_FILE, "w", encoding="utf-8") as f:
                f.write(f"{self.root.winfo_x()},{self.root.winfo_y()}")
        except Exception:
            pass

    def center(self):
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() - self.root.winfo_width()) // 2
        self.root.geometry(f"+{x}+{int(6 * self.dpi)}")
        self._save_pos()

    # ---------- dongu ----------

    def poll(self):
        state = read_state()
        if state != self.state:
            self.state = state
            if self._grip_on:
                self._draw_grip()
        self._track_pointer()
        self.root.after(POLL_MS, self.poll)

    def animate(self):
        if self._pending_zoom is not None:
            z, self._pending_zoom = self._pending_zoom, None
            self.set_zoom(z, paint=False)   # bu karede zaten cizilecek

        cfg = STATES[self.state]
        active = cfg["idx"]

        t = time.perf_counter() - self._t0
        pulse = cfg["pulse"]
        if pulse:
            k = 0.5 + 0.5 * math.sin(2 * math.pi * pulse * t)
            lo, hi = (0.70, 0.92) if self.state == "green" else (0.40, 1.0)
            intensity = lo + (hi - lo) * k
        else:
            intensity = 0.82       # kirmizi sabit yanar

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

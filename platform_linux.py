"""Linux (X11 / XWayland) karsiligi: platform_win ile ayni adlar.

Tk X11'de piksel basina saydam pencere acamiyor. Onun yerine pencereye
X Shape eklentisiyle goruntunun bicimi veriliyor: yari saydamdan koyu
pikseller gorunur, otesi tamamen yok (tiklama da alttakine gecer). Yumusak
golgeler bu yuzden cizilmiyor.

HUD kendini ekran yakalamadan gizleyemedigi icin sivi cam gercek arka plani
okuyamiyor; duz, notr bir zemin kullaniliyor.
"""

import os
import fcntl
import ctypes
import ctypes.util
import tempfile
import tkinter as tk

from PIL import Image, ImageTk

# Pillow, adi verilen yazi tipini sistem yazi tipi klasorlerinde kendisi arar
FONTS_DIR = ""
UI_FONT = "DejaVuSans.ttf"
UIB_FONT = "DejaVuSans-Bold.ttf"
ICON_FONT = "DejaVuSans.ttf"
GEAR_GLYPH = "⚙"
CLOSE_GLYPH = "✕"

ALPHA_CUT = 128          # bu saydamligin altindaki pikseller pencereden kesilir
GLASS_BACKDROP = (128, 130, 136)

_x11 = ctypes.CDLL(ctypes.util.find_library("X11"))
_xext = ctypes.CDLL(ctypes.util.find_library("Xext"))
_x11.XOpenDisplay.restype = ctypes.c_void_p
_x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
_x11.XCreateBitmapFromData.restype = ctypes.c_ulong
_x11.XCreateBitmapFromData.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_char_p,
                                       ctypes.c_uint, ctypes.c_uint]
_x11.XFreePixmap.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
_x11.XFlush.argtypes = [ctypes.c_void_p]
_xext.XShapeCombineMask.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, ctypes.c_ulong, ctypes.c_int]
_dpy = _x11.XOpenDisplay(None)
SHAPE_BOUNDING, SHAPE_SET = 0, 0


def system_is_turkish():
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        if os.environ.get(var):
            return os.environ[var].lower().startswith("tr")
    return False


def capture(x, y, w, h):
    return Image.new("RGB", (w, h), GLASS_BACKDROP)


class Layer:
    """Goruntuyu bir Label'da gosteren, bicimi goruntunun saydamligindan
    alinan pencere. platform_win.Layer ile ayni arayuz."""

    def __init__(self, win, topmost):
        self.win = win
        # Pencere hic gizlenmiyor: bazi bilesikciler (WSLg) gizlenip yeniden
        # gosterilen kenarliksiz pencereyi bir daha gostermiyor. Gizlemek
        # yerine bicim bosaltiliyor.
        win.overrideredirect(True)
        win.attributes("-topmost", topmost)
        win.geometry("1x1+0+0")
        self.view = tk.Label(win, bd=0, highlightthickness=0, padx=0, pady=0)
        self.view.place(x=0, y=0)
        win.update_idletasks()
        self.photo = None
        self.mask = None
        self.img = None
        self.xy = None
        self.size = None
        self.visible = True
        self.hide()

    def _shape(self, img):
        bits = img.getchannel("A").point(lambda a: 255 if a >= ALPHA_CUT else 0).convert("1")
        self._set_mask(bits.tobytes("raw", "1;R"), img.size)   # XBM: once dusuk bit

    def _set_mask(self, data, size):
        if data == self.mask:
            return
        self.mask = data
        xid = int(self.win.wm_frame(), 16)
        pixmap = _x11.XCreateBitmapFromData(_dpy, xid, data, size[0], size[1])
        _xext.XShapeCombineMask(_dpy, xid, SHAPE_BOUNDING, 0, 0, pixmap, SHAPE_SET)
        _x11.XFreePixmap(_dpy, pixmap)
        _x11.XFlush(_dpy)

    def show(self, img, x, y):
        if self.visible and img is self.img and (x, y) == self.xy:
            return
        if img.size != self.size or (x, y) != self.xy:
            self.win.geometry("%dx%d+%d+%d" % (img.size[0], img.size[1], x, y))
        new = img is not self.img or not self.visible
        if img is not self.img:
            self.photo = ImageTk.PhotoImage(img.convert("RGB"))
            self.view.configure(image=self.photo)
        self.img, self.size, self.xy = img, img.size, (x, y)
        self.visible = True
        if new:
            self._shape(img)

    def move(self, x, y):
        if self.img is not None:
            self.show(self.img, x, y)

    def hide(self):
        if self.visible:
            self._set_mask(b"\0", (1, 1))    # bos bicim: gorunmez, tiklama gecer
            self.visible = False

    def exclude_from_capture(self, on):
        pass


def acquire_singleton():
    lock = open(os.path.join(tempfile.gettempdir(), "cc_hud.lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock.close()
        return None
    return lock


def enable_dpi_awareness():
    pass

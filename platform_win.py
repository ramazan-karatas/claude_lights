"""Windows'a ozgu her sey: katmanli pencereler, ekran yakalama, tek kopya
kilidi, DPI, yazi tipleri ve arayuz dili. Baska bir isletim sistemi icin ayni
adlari saglayan bir modul yazmak yeterli."""

import os
import ctypes
from ctypes import wintypes as wt

from PIL import Image, ImageChops

FONTS_DIR = os.path.join(os.environ["WINDIR"], "Fonts")
UI_FONT = "segoeui.ttf"
UIB_FONT = "seguisb.ttf"        # Segoe UI Semibold
# Simge yazisi: Windows 11'de Segoe Fluent Icons, Windows 10'da MDL2 Assets
ICON_FONT = ("SegoeIcons.ttf"
             if os.path.exists(os.path.join(FONTS_DIR, "SegoeIcons.ttf"))
             else "segmdl2.ttf")
GEAR_GLYPH = ""
CLOSE_GLYPH = ""


def system_is_turkish():
    return ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF == 0x1F


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

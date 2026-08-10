import ctypes
import ctypes.wintypes
import time

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
INPUT_KEYBOARD = 1

VK_MAP = {
    "1": 0x31, "2": 0x32, "3": 0x33, "4": 0x34, "5": 0x35,
    "6": 0x36, "7": 0x37, "8": 0x38, "9": 0x39, "0": 0x30,
    "a": 0x41, "b": 0x42, "c": 0x43, "d": 0x44, "e": 0x45,
    "f": 0x46, "g": 0x47, "h": 0x48, "i": 0x49, "j": 0x4A,
    "k": 0x4B, "l": 0x4C, "m": 0x4D, "n": 0x4E, "o": 0x4F,
    "p": 0x50, "q": 0x51, "r": 0x52, "s": 0x53, "t": 0x54,
    "u": 0x55, "v": 0x56, "w": 0x57, "x": 0x58, "y": 0x59, "z": 0x5A,
    "escape": 0x1B, "esc": 0x1B, "tab": 0x09, "space": 0x20,
    "enter": 0x0D, "return": 0x0D, "backspace": 0x08,
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74,
    "f6": 0x75, "f7": 0x76, "f8": 0x77, "f9": 0x78,
    "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
}


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.wintypes.WORD),
        ("wScan", ctypes.wintypes.WORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _INPUT(ctypes.Structure):
    class _INPUT_UNION(ctypes.Union):
        _fields_ = [("ki", _KEYBDINPUT)]

    _fields_ = [
        ("type", ctypes.wintypes.DWORD),
        ("union", _INPUT_UNION),
    ]


class InputHandler:
    @staticmethod
    def move_cursor(x, y):
        ctypes.windll.user32.SetCursorPos(int(x), int(y))

    @staticmethod
    def click_mouse(x=None, y=None, delay=0.1):
        if x is not None and y is not None:
            InputHandler.move_cursor(x, y)
            time.sleep(0.05)
        ctypes.windll.user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(delay)
        ctypes.windll.user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

    @staticmethod
    def hold_mouse_start(x=None, y=None):
        if x is not None and y is not None:
            InputHandler.move_cursor(x, y)
            time.sleep(0.05)
        ctypes.windll.user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)

    @staticmethod
    def hold_mouse_end():
        ctypes.windll.user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

    @staticmethod
    def press_key(key: str, hold_time: float = 0.05):
        vk = VK_MAP.get(key.lower())
        if vk is None:
            result = ctypes.windll.user32.VkKeyScanW(ord(key[0]))
            if result == -1:
                return
            vk = result & 0xFF
        scan = ctypes.windll.user32.MapVirtualKeyW(vk, 0)
        inp_down = _INPUT()
        inp_down.type = INPUT_KEYBOARD
        inp_down.union.ki.wVk = vk
        inp_down.union.ki.wScan = scan
        inp_down.union.ki.dwFlags = 0
        inp_down.union.ki.time = 0
        inp_down.union.ki.dwExtraInfo = ctypes.pointer(ctypes.c_ulong(0))
        ctypes.windll.user32.SendInput(1, ctypes.byref(inp_down), ctypes.sizeof(_INPUT))
        time.sleep(hold_time)
        inp_up = _INPUT()
        inp_up.type = INPUT_KEYBOARD
        inp_up.union.ki.wVk = vk
        inp_up.union.ki.wScan = scan
        inp_up.union.ki.dwFlags = KEYEVENTF_KEYUP
        inp_up.union.ki.time = 0
        inp_up.union.ki.dwExtraInfo = ctypes.pointer(ctypes.c_ulong(0))
        ctypes.windll.user32.SendInput(1, ctypes.byref(inp_up), ctypes.sizeof(_INPUT))

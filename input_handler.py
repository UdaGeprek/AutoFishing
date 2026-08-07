import ctypes
import time

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004

class InputHandler:
    @staticmethod
    def move_cursor(x, y):
        """Аппаратное перемещение курсора мыши в физические координаты экрана."""
        ctypes.windll.user32.SetCursorPos(int(x), int(y))

    @staticmethod
    def click_mouse(x=None, y=None, delay=0.1):
        """
        Делает физический клик ЛКМ. 
        Если переданы x и y — курсор автоматически перемещается в эту точку перед кликом.
        """
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
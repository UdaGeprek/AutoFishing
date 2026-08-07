import cv2
import numpy as np
import mss


class Vision:
    def __init__(self):
        self.sct = mss.mss()

    def capture_screen(self, region):
        screenshot = self.sct.grab(region)
        # Отбрасываем Alpha-канал прямым срезом NumPy без вызова cv2.cvtColor (ускорение в 3-5 раз)
        return np.ascontiguousarray(np.array(screenshot)[:, :, :3])

    def find_color_object(self, img, lower_color, upper_color, min_area=40, is_float=False):
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

        if is_float:
            mask1 = cv2.inRange(hsv, lower_color, upper_color)
            lower_dark_red = np.array([165, 50, 50])
            upper_dark_red = np.array([179, 255, 255])
            mask2 = cv2.inRange(hsv, lower_dark_red, upper_dark_red)
            mask = cv2.bitwise_or(mask1, mask2)
        else:
            mask = cv2.inRange(hsv, lower_color, upper_color)

        contours, _ = cv2.findContours(mask, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

        for cnt in contours:
            area = cv2.contourArea(cnt)

            if is_float:
                if 75 < area < 400:
                    x, y, w, h = cv2.boundingRect(cnt)
                    solidity = float(area) / (w * h)
                    if solidity > 0.25 and w < 35 and h < 35:
                        return (x + w // 2, y + h // 2), (x, y, w, h)
            else:
                if 20 < area < 500:
                    x, y, w, h = cv2.boundingRect(cnt)
                    return (x + w // 2, y + h // 2), (x, y, w, h)

        return None, None
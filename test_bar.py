import cv2
import numpy as np
import time
from vision import Vision
from input_handler import InputHandler

def main():
    vision = Vision()
    
    # 1. Безопасный регион захвата воды (Отрезали нижний интерфейс и скиллы)
    water_region = {"top": 100, "left": 500, "width": 900, "height": 450}
    # Регион для шкалы мини-игры (центр экрана)
    bar_region = {"top": 350, "left": 750, "width": 450, "height": 300}
    
    # 2. Твои стабильные ручные настройки HSV для поплавка
    lower_float = np.array([0, 185, 100])
    upper_float = np.array([10, 255, 255])
    
    # Твои идеальные настройки для элементов мини-игры
    lower_fish = np.array([90, 0, 200])
    upper_fish = np.array([130, 90, 255])
    
    lower_zone = np.array([35, 80, 80])
    upper_zone = np.array([85, 255, 255])

    STATE_FISHING = 0
    STATE_MINIGAME = 1
    current_state = STATE_FISHING

    is_float_tracked = False
    lost_frames_counter = 0
    REQUIRED_LOST_FRAMES = 15  # Защита от ложных срабатываний мерцания воды

    print("[SYSTEM] Бот запущен со стабильными HSV-параметрами. Ожидание заброса...")

    while True:
        # === РЕЖИМ 1: СЛЕДИМ ЗА ПОПЛАВКОМ НА ВОДЕ ===
        if current_state == STATE_FISHING:
            frame = vision.capture_screen(water_region)
            
            # Дебаг-маска воды
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            debug_mask = cv2.inRange(hsv, lower_float, upper_float)
            cv2.imshow("DEBUG MASK (Must be Black before cast!)", debug_mask)

            center, bbox = vision.find_color_object(frame, lower_float, upper_float)
            
            if center and bbox:
                lost_frames_counter = 0
                is_float_tracked = True  # Бот зафиксировал поплавок в воде
                
                x, y, w, h = bbox
                cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
                cv2.circle(frame, center, 4, (0, 0, 255), -1)
                print(f"[FISHING] Слежка... Поплавок стабилен.            ", end="\r")
            else:
                if is_float_tracked:
                    lost_frames_counter += 1
                    print(f"[WARN] Потеря кадра! Под водой: {lost_frames_counter}/{REQUIRED_LOST_FRAMES}  ", end="\r")
                    
                    if lost_frames_counter >= REQUIRED_LOST_FRAMES:
                        print("\n[🔥 TRIGGER] ПОКЛЕВКА! Подсекаем и переходим в мини-игру!")
                        InputHandler.click_mouse()
                        
                        is_float_tracked = False
                        lost_frames_counter = 0
                        current_state = STATE_MINIGAME
                        time.sleep(1.5)  # Время на появление интерфейса шкалы
                else:
                    print("[LOG] Ожидание заброса (Вода должна быть чистой)...", end="\r")
            
            cv2.imshow("Bot Active Viewport", frame)

        # === РЕЖИМ 2: АВТОМАТИЧЕСКАЯ МИНИ-ИГРА ===
        elif current_state == STATE_MINIGAME:
            bar_frame = vision.capture_screen(bar_region)
            fish_center, _ = vision.find_color_object(bar_frame, lower_fish, upper_fish)
            zone_center, _ = vision.find_color_object(bar_frame, lower_zone, upper_zone)
            
            if fish_center and zone_center:
                fish_x = fish_center
                zone_x = zone_center
                
                if fish_x < zone_x:
                    print(f"[MINIGAME] Рыбка ({fish_x}) < Зоны ({zone_x}) -> ЗАЖИМАЕМ ЛКМ  ", end="\r")
                    InputHandler.hold_mouse_start()
                else:
                    print(f"[MINIGAME] Рыбка ({fish_x}) > Зоны ({zone_x}) -> ОТПУСКАЕМ ЛКМ  ", end="\r")
                    InputHandler.hold_mouse_end()
            else:
                print("\n[✔ SYSTEM] Шкала исчезла. Рыба поймана! Возврат в режим ожидания.")
                InputHandler.hold_mouse_end()
                is_float_tracked = False
                lost_frames_counter = 0
                current_state = STATE_FISHING
                time.sleep(3.0)  # Пауза для скрытия уведомлений
                
            cv2.imshow("Bot Active Viewport", bar_frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
            
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()

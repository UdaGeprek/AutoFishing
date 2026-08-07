import cv2
import numpy as np
import time
import keyboard  # Импортируем библиотеку для глобальных хоткеев
from vision import Vision
from input_handler import InputHandler

def main():
    vision = Vision()
    
    # 1. Наша проверенная геометрия регионов
    water_region = {"top": 220, "left": 500, "width": 900, "height": 400}
    bar_region = {"top": 450, "left": 710, "width": 500, "height": 180}
    
    # =========================================================================
    # ⚙️ ТВОЯ НАСТРОЙКА ДАЛЬНОСТИ ЗАБРОСА УДОЧКИ (РЕГУЛИРУЙ ЗДЕСЬ!)
    # =========================================================================
    CAST_POWER_TIME = 0.55  # Время зажатия ЛКМ в секундах. 
                            # 0.3 - под ноги, 0.55 - средний, 0.9 - дальний.
    # =========================================================================
    
    # Имена окон для жесткого закрепления поверх игры (Always on Top)
    window_main = "Bot Active Viewport"
    window_zone = "DEBUG ZONE MASK"
    window_float = "INVERSE FLOAT TARGET" 
    window_water_debug = "DEBUG MASK (Water)"
    
    cv2.namedWindow(window_main)
    cv2.setWindowProperty(window_main, cv2.WND_PROP_TOPMOST, 1)
    
    # 2. ПОЛНОСТЬЮ ЗАПОЛНЕННЫЕ НАСТРОЙКИ HSV (Ошибок больше не будет!)
    lower_float = np.array([0, 100, 100])
    upper_float = np.array([10, 255, 255])
    
    lower_dark_float = np.array([0, 185, 100])
    upper_dark_float = np.array([10, 255, 255])
    
    lower_fish = np.array([0, 220, 200])
    upper_fish = np.array([10, 255, 255])
    
    lower_zone = np.array([35, 100, 100])
    upper_zone = np.array([85, 255, 255])

    # СТАТУСЫ НАШЕЙ СИСТЕМЫ:
    STATE_PAUSED = -1    # Бот спит и ничего не делает
    STATE_CASTING = 0    # Шаг 1: Авто-заброс удочки
    STATE_FISHING = 1    # Шаг 2: Слежка за поплавком в воде
    STATE_MINIGAME = 2   # Шаг 3: Авто-мини-игра
    
    # СТАРТУЕМ В РЕЖИМЕ ПАУЗЫ (ЖДЕМ НАЖАТИЯ F1)
    current_state = STATE_PAUSED
    bot_active = False

    is_float_tracked = False
    lost_frames_counter = 0
    REQUIRED_LOST_FRAMES = 3   # Молниеносная подсечка дня за 3 кадра
    minigame_lost_frames = 0   

    print("[SYSTEM] ПОЛНАЯ АВТОМАТИКА С КНОПКОЙ ПАУЗЫ ЗАПУЩЕНА!")
    print("[SYSTEM] Нажмите клавишу F1 в игре, чтобы запустить или остановить цикл.")

    while True:
        # ОБРАБОТКА ХОТКЕЯ F1 НА ХОДУ
        if keyboard.is_pressed('f1'):
            bot_active = not bot_active
            time.sleep(0.3)  # Защита от дребезга контактов клавиатуры
            
            if bot_active:
                print("\n[⚡ СТАРТ] Бот активирован! Начинаем цикл рыбалки...")
                current_state = STATE_CASTING
            else:
                print("\n[💤 ПАУЗА] Бот остановлен! Мышь освобождена.")
                InputHandler.hold_mouse_end()  # Принудительно отпускаем ЛКМ при паузе
                current_state = STATE_PAUSED
                
                # Мгновенно закрываем дебаг-окна, чтобы они не мешали играть руками
                try:
                    cv2.destroyWindow(window_zone)
                    cv2.destroyWindow(window_float)
                    cv2.destroyWindow(window_water_debug)
                except: pass

        # === РЕЖИМ: БОТ НА ПАУЗЕ ===
        if current_state == STATE_PAUSED:
            frame = vision.capture_screen(water_region)
            cv2.putText(frame, "BOT PAUSED - Press F1 to Start", (20, 40), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
            cv2.imshow(window_main, frame)
            cv2.waitKey(1)
            continue

        # === РЕЖИМ 0: АВТОМАТИЧЕСКИЙ ЗАБРОС УДОЧКИ ===
        elif current_state == STATE_CASTING:
            print("\n[ACTION] Замахиваемся и закидываем удочку...")
            
            InputHandler.hold_mouse_start()
            time.sleep(CAST_POWER_TIME)
            InputHandler.hold_mouse_end()
            
            print(f"[ACTION] Заброс выполнен. Ожидаем падения поплавка...")
            time.sleep(2.5)  
            
            is_float_tracked = False
            lost_frames_counter = 0
            current_state = STATE_FISHING

        # === РЕЖИМ 1: СЛЕДИМ ЗА ПОПЛАВКОМ НА ВОДЕ ===
        elif current_state == STATE_FISHING:
            frame = vision.capture_screen(water_region)
            
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            mask1 = cv2.inRange(hsv, lower_float, upper_float)
            mask2 = cv2.inRange(hsv, lower_dark_float, upper_dark_float)
            debug_mask = cv2.bitwise_or(mask1, mask2)
            
            cv2.namedWindow(window_water_debug)
            cv2.setWindowProperty(window_water_debug, cv2.WND_PROP_TOPMOST, 1)
            cv2.imshow(window_water_debug, debug_mask)

            center, bbox = vision.find_color_object(frame, lower_float, upper_float, is_float=True)
            
            if center and bbox:
                lost_frames_counter = 0
                is_float_tracked = True
                
                x, y, w, h = bbox
                cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
                cv2.circle(frame, center, 4, (0, 0, 255), -1)
                print(f"[FISHING] Слежка... Поплавок стабилен.            ", end="\r")
            else:
                if is_float_tracked:
                    lost_frames_counter += 1
                    print(f"[WARN] Потеря кадра! Под водой: {lost_frames_counter}/{REQUIRED_LOST_FRAMES}  ", end="\r")
                    
                    if lost_frames_counter >= REQUIRED_LOST_FRAMES:
                        print("\n[🔥 TRIGGER] ПОКЛЕВКА! Подсекаем рыбу!")
                        InputHandler.click_mouse() 
                        
                        try: cv2.destroyWindow(window_water_debug)
                        except: pass
                        
                        is_float_tracked = False
                        lost_frames_counter = 0
                        minigame_lost_frames = 0
                        current_state = STATE_MINIGAME
                else:
                    print("[LOG] Поплавок еще летит или ищется на воде...  ", end="\r")
            
            cv2.imshow(window_main, frame)

        # === РЕЖИМ 2: АВТОМАТИЧЕСКАЯ МИНИ-ИГРА ===
        elif current_state == STATE_MINIGAME:
            bar_frame = vision.capture_screen(bar_region)
            hsv_bar = cv2.cvtColor(bar_frame, cv2.COLOR_BGR2HSV)
            
            mask_zone = cv2.inRange(hsv_bar, lower_zone, upper_zone)
            cv2.namedWindow(window_zone)
            cv2.setWindowProperty(window_zone, cv2.WND_PROP_TOPMOST, 1)
            cv2.imshow(window_zone, mask_zone)
            
            if cv2.countNonZero(mask_zone) > 1000:
                minigame_lost_frames = 0
                mask_inv = cv2.bitwise_not(mask_zone)
                
                cv2.namedWindow(window_float)
                cv2.setWindowProperty(window_float, cv2.WND_PROP_TOPMOST, 1)
                cv2.imshow(window_float, mask_inv)
                
                contours_inv, _ = cv2.findContours(mask_inv, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
                
                float_x = None
                for cnt in contours_inv:
                    area = cv2.contourArea(cnt)
                    if 15 < area < 200:
                        x, y, w, h = cv2.boundingRect(cnt)
                        if 10 < y < 150:
                            float_x = x + w // 2
                            break
                
                if float_x is not None:
                    SCREEN_CENTER_X = 250  
                    cv2.line(bar_frame, (SCREEN_CENTER_X, 0), (SCREEN_CENTER_X, 180), (0, 255, 0), 2)
                    cv2.circle(bar_frame, (float_x, 90), 6, (0, 0, 255), -1)
                    
                    if float_x < SCREEN_CENTER_X:
                        print(f"[RELAIS] Поплавок ({float_x}) < Центра (250) -> ЗАЖАТИЕ ЛКМ...           ", end="\r")
                        InputHandler.hold_mouse_start()
                        time.sleep(0.005)
                    else:
                        print(f"[RELAIS] Поплавок ({float_x}) >= Центра (250) -> ОТПУСКАЕМ (ОТДЫХ 20мс)    ", end="\r")
                        InputHandler.hold_mouse_end()
                        time.sleep(0.020)
                else:
                    InputHandler.hold_mouse_end()
            else:
                minigame_lost_frames += 1
                print(f"[WARN-MINIGAME] Ожидание закрытия шкалы: {minigame_lost_frames}/45          ", end="\r")
                
                if minigame_lost_frames >= 45:
                    print("\n[✔ SYSTEM] Шкала исчезла. Рыба в сумке!")
                    InputHandler.hold_mouse_end()
                    
                    try:
                        cv2.destroyWindow(window_zone)
                        cv2.destroyWindow(window_float)
                    except: pass
                    
                    print("[SYSTEM] Перезапуск цикла через 3.5 секунды...")
                    time.sleep(3.5) 
                    current_state = STATE_CASTING 
                
            cv2.imshow(window_main, bar_frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
            
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()

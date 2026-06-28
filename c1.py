import socket
import time
import math
import threading
import os
import urllib.request
import json
import zipfile  # مورد نیاز برای آنزیپ کردن خودکار مدل صوتی

# --- تنظیمات شبکه و ربات ---
ROBOT_IP = "192.168.1.6"  
DASHBOARD_PORT = 29999    
MOTION_PORT = 30003       
UDP_IN_IP = "127.0.0.1"  
UDP_IN_PORT = 5005        
UNITY_VIDEO_PORT = 5006   

latest_udp_msg = None
last_vr_packet_time = 0
webcam_reset_triggered = False  
webcam_hand_data = None  # داده‌های جهانی انتقال دست (x, y, depth, is_active)
voice_command_action = None  # پورت اشتراک‌گذاری فرامن صوتی گسسته و گام‌به‌گام
data_lock = threading.Lock()
running = True

def send_dashboard_cmd(sock, cmd):
    try:
        sock.sendall((cmd + "\n").encode('utf-8'))
        time.sleep(0.005)
        return sock.recv(1024).decode('utf-8')
    except:
        return "Error"

def send_motion_cmd(sock, cmd):
    try:
        sock.sendall((cmd + "\n").encode('utf-8'))
    except Exception as e:
        print(f"Motion send error: {e}")

def udp_receiver(sock):
    global latest_udp_msg, last_vr_packet_time, running
    sock.setblocking(False)
    while running:
        last_msg = None
        while True:
            try:
                data, _ = sock.recvfrom(1024)
                last_msg = data.decode('utf-8')
            except BlockingIOError:
                break  
            except:
                break
        
        if last_msg:
            with data_lock:
                latest_udp_msg = last_msg
                last_vr_packet_time = time.perf_counter()
        time.sleep(0.002)

def dist3d(p1, p2):
    return math.sqrt((p1.x - p2.x)**2 + (p1.y - p2.y)**2 + (p1.z - p2.z)**2)

# 🎙️ ترد کنترل صوتی آفلاین انگلیسی (نسخه ارتقا یافته با فیلتر لغات/گرامر جهت دقت حداکثری)
def voice_analyzer():
    global webcam_reset_triggered, voice_command_action, running
    try:
        import vosk
        import sounddevice as sd
    except ImportError:
        print(">> Core Error: Please install 'vosk' and 'sounddevice' for voice features.")
        return

    # پیدا کردن مسیر مطلق پوشه مدل صوتی انگلیسی در کنار خود اسکریپت
    script_dir = os.path.dirname(os.path.abspath(__file__))
    model_path = os.path.join(script_dir, "vosk-model-en")
    
    # دانلود و استخراج خودکار مدل صوتی انگلیسی در صورت عدم وجود
    if not os.path.exists(model_path):
        print(">> WARNING: English voice model folder not found!")
        print(">> Downloading English Voice Model automatically (approx. 40MB)... Please wait...")
        zip_path = os.path.join(script_dir, "vosk-model-en.zip")
        url = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
        try:
            urllib.request.urlretrieve(url, zip_path)
            print(">> Extracting voice model...")
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(script_dir)
            
            # تغییر نام پوشه استخراج شده به نام استاندارد کد
            extracted_folder = os.path.join(script_dir, "vosk-model-small-en-us-0.15")
            if os.path.exists(extracted_folder):
                os.rename(extracted_folder, model_path)
            # پاک کردن فایل زیپ دانلودی
            if os.path.exists(zip_path):
                os.remove(zip_path)
            print(">> English voice model setup completed successfully!")
        except Exception as e:
            print(f">> Core Error: Failed to auto-download voice model: {e}")
            print(">> Voice control disabled.")
            return

    try:
        model = vosk.Model(model_path)
        
        # ✨ فیلتر گرامر: محدود کردن دایره لغات Vosk فقط به دستورات ربات جهت صفر کردن خطای تشخیص
        allowed_words = [
            "forward", "backward", "left", "right", "up", "down", 
            "home", "stop", "halt", "reset", "clear", "front", "back", "[unk]"
        ]
        grammar_json = json.dumps(allowed_words)
        rec = vosk.KaldiRecognizer(model, 16000, grammar_json)
        
        print(">> English Voice Recognition System Initialized (with accuracy filter). Listening...")
    except Exception as e:
        print(f">> Voice model initialization failed: {e}")
        return
    
    with sd.RawInputStream(samplerate=16000, blocksize=4000, dtype='int16', channels=1) as stream:
        while running:
            data, _ = stream.read(4000)
            if rec.AcceptWaveform(bytes(data)):
                result = json.loads(rec.Result())
                text = result.get("text", "").strip().lower()
                
                if text and text != "[unk]":
                    print(f"[Voice Heard]: {text}")
                    
                    # 🛑 دستورات کنترلی اصلی (English)
                    if "stop" in text or "halt" in text:
                        with data_lock: voice_command_action = "STOP"
                    elif "reset" in text or "clear" in text:
                        with data_lock: webcam_reset_triggered = True
                    elif "home" in text:
                        with data_lock: voice_command_action = "HOME"
                    
                    # 🔄 دستورات گام حرکتی ۲۰ میلی‌متری (English)
                    elif "forward" in text or "front" in text:
                        with data_lock: voice_command_action = "FORWARD"
                    elif "backward" in text or "back" in text:
                        with data_lock: voice_command_action = "BACKWARD"
                    elif "left" in text:
                        with data_lock: voice_command_action = "LEFT"
                    elif "right" in text:
                        with data_lock: voice_command_action = "RIGHT"
                    elif "up" in text:
                        with data_lock: voice_command_action = "UP"
                    elif "down" in text:
                        with data_lock: voice_command_action = "DOWN"

# 🎥 : پردازشگر وبکم با هندسه سه‌بعدی و انتقال صحیح متغیرها
def webcam_analyzer():
    global webcam_reset_triggered, webcam_hand_data, running
    try:
        import cv2
        import mediapipe as mp
        from mediapipe.tasks import python
        from mediapipe.tasks.python import vision
    except ImportError:
        print(">> Core Error: Please install 'opencv-python' and 'mediapipe' for webcam features.")
        return

    script_dir = os.path.dirname(os.path.abspath(__file__))
    model_path = os.path.join(script_dir, "hand_landmarker.task")
    
    if not os.path.exists(model_path):
        print(">> Downloading MediaPipe Hand Landmarker Model...")
        url = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
        try:
            urllib.request.urlretrieve(url, model_path)
            print(">> MediaPipe Model downloaded.")
        except Exception as e:
            print(f">> Core Error: Failed to download model: {e}")
            return

    video_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    base_options = python.BaseOptions(model_asset_path=model_path, delegate=python.BaseOptions.Delegate.CPU)
    options = vision.HandLandmarkerOptions(base_options=base_options, running_mode=vision.RunningMode.VIDEO, num_hands=2)
    
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    active_hand_raised_start_time = None
    frame_counter = 0
    detection_result = None
    
    with vision.HandLandmarker.create_from_options(options) as detector:
        while running:
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.005)
                continue
                
            frame = cv2.flip(frame, 1)
            h, w, _ = frame.shape
            reset_zone_y = int(h * 0.20)
            cv2.line(frame, (0, reset_zone_y), (w, reset_zone_y), (0, 0, 255), 2)
            
            frame_counter += 1
            if frame_counter % 2 == 0:
                small_input = cv2.resize(frame, (320, 240))
                rgb_frame = cv2.cvtColor(small_input, cv2.COLOR_BGR2RGB)
                mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
                timestamp_ms = int(time.perf_counter() * 1000)
                detection_result = detector.detect_for_video(mp_img, timestamp_ms)
            
            any_hand_in_reset_zone = False
            current_hand_frame_data = None
            
            if detection_result and detection_result.hand_landmarks and detection_result.handedness:
                for idx, hand_handedness in enumerate(detection_result.handedness):
                    label = hand_handedness[0].category_name
                    l = detection_result.hand_landmarks[idx]
                    wrist_y = int(l[0].y * h)
                    
                    if wrist_y < reset_zone_y:
                        any_hand_in_reset_zone = True
                    
                    if label == "Right": 
                        for lm in l: cv2.circle(frame, (int(lm.x*w), int(lm.y*h)), 4, (0, 255, 0), -1)
                    
                    elif label == "Left": 
                        hand_size_3d = dist3d(l[0], l[9])
                        
                        index_extended = dist3d(l[8], l[5]) > 0.65 * hand_size_3d
                        middle_folded = dist3d(l[12], l[9]) < 0.45 * hand_size_3d
                        ring_folded = dist3d(l[16], l[13]) < 0.45 * hand_size_3d
                        pinky_folded = dist3d(l[20], l[17]) < 0.45 * hand_size_3d
                        is_index_active = index_extended and middle_folded and ring_folded and pinky_folded
                        
                        color = (0, 255, 0) if is_index_active else (0, 255, 255)
                        for lm in l: cv2.circle(frame, (int(lm.x*w), int(lm.y*h)), 4, color, -1)
                        
                        raw_depth_size = math.sqrt((l[0].x - l[9].x)**2 + (l[0].y - l[9].y)**2)
                        current_hand_frame_data = (l[0].x, l[0].y, raw_depth_size, is_index_active)
            
            with data_lock:
                webcam_hand_data = current_hand_frame_data

            if any_hand_in_reset_zone:
                cv2.line(frame, (0, reset_zone_y), (w, reset_zone_y), (0, 255, 0), 3)
                if active_hand_raised_start_time is None: active_hand_raised_start_time = time.perf_counter()
                else:
                    elapsed = time.perf_counter() - active_hand_raised_start_time
                    cv2.putText(frame, f"HAND RESET: {3.0 - elapsed:.1f}s", (50, reset_zone_y - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0,0,255), 2)
                    if elapsed >= 3.0:
                        with data_lock: webcam_reset_triggered = True
                        active_hand_raised_start_time = None
            else: active_hand_raised_start_time = None
            
            cv2.imshow("MG400 Standalone Controller", frame)
            try:
                unity_ready_frame = cv2.resize(frame, (240, 180)) 
                _, encoded_img = cv2.imencode('.jpg', unity_ready_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 40])
                video_sock.sendto(encoded_img.tobytes(), ("127.0.0.1", UNITY_VIDEO_PORT))
            except: pass
            if cv2.waitKey(1) & 0xFF == ord('q'): break
    cap.release()
    cv2.destroyAllWindows()

def main():
    global latest_udp_msg, webcam_reset_triggered, webcam_hand_data, voice_command_action, running
    print("Connecting to Dobot MG400...")
    try:
        dash_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        dash_sock.connect((ROBOT_IP, DASHBOARD_PORT))
        motion_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        motion_sock.connect((ROBOT_IP, MOTION_PORT))
        motion_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        dash_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        print("Robot Connected.")
    except Exception as e:
        print(f"Robot connection failed: {e}.")
        return

    send_dashboard_cmd(dash_sock, "ClearError()")
    send_dashboard_cmd(dash_sock, "EnableRobot()")
    
    send_dashboard_cmd(dash_sock, "SpeedFactor(100)") 
    send_dashboard_cmd(dash_sock, "CP(100)")           
    send_dashboard_cmd(dash_sock, "VelJ(100)")          
    send_dashboard_cmd(dash_sock, "AccJ(85)")           

    send_motion_cmd(motion_sock, "MovJ(350, 0, 0, 0)") 
    time.sleep(1.2)

    udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_sock.bind(("127.0.0.1", UDP_IN_PORT))
    
    threading.Thread(target=udp_receiver, args=(udp_sock,), daemon=True).start()
    threading.Thread(target=webcam_analyzer, daemon=True).start()
    threading.Thread(target=voice_analyzer, daemon=True).start()

    active_mode = None 
    robot_start_x, robot_start_y, robot_start_z = 350.0, 0.0, 0.0
    vr_start_x, vr_start_y, vr_start_z = 0.0, 0.0, 0.0
    w_start_x, w_start_y, w_start_depth = 0.0, 0.0, 0.0
    
    last_sent_x, last_sent_y, last_sent_z = 350.0, 0.0, 0.0
    last_command_time = time.perf_counter()

    SCALE_FACTOR = 1.0 / 3.0  
    ALPHA = 0.90  

    try:
        while True:
            local_webcam_reset = False
            local_hand_data = None
            local_voice_action = None
            
            with data_lock:
                if webcam_reset_triggered:
                    local_webcam_reset = True
                    webcam_reset_triggered = False
                local_hand_data = webcam_hand_data
                if voice_command_action:
                    local_voice_action = voice_command_action
                    voice_command_action = None

            if local_voice_action == "STOP":
                print(">> VOICE COMMAND: EMERGENCY STOP!")
                send_dashboard_cmd(dash_sock, "ResetRobot()") 
                active_mode = None
                continue
                
            elif local_voice_action == "HOME":
                print(">> VOICE COMMAND: MOVING HOME...")
                send_motion_cmd(motion_sock, "MovJ(350, 0, 0, 0)")
                last_sent_x, last_sent_y, last_sent_z = 350.0, 0.0, 0.0
                robot_start_x, robot_start_y, robot_start_z = 350.0, 0.0, 0.0
                active_mode = None
                time.sleep(1.0)
                continue

            # 🎙️ ۲. پردازش فرامین صوتی گام حرکتی ۲۰ میلی‌متری (English)
            elif local_voice_action in ["FORWARD", "BACKWARD", "LEFT", "RIGHT", "UP", "DOWN"]:
                step_x, step_y, step_z = 0.0, 0.0, 0.0
                if local_voice_action == "FORWARD": step_x = 20.0
                elif local_voice_action == "BACKWARD": step_x = -20.0
                elif local_voice_action == "LEFT": step_y = 20.0
                elif local_voice_action == "RIGHT": step_y = -20.0
                elif local_voice_action == "UP": step_z = 20.0
                elif local_voice_action == "DOWN": step_z = -20.0

                target_x = max(130.0, min(415.0, last_sent_x + step_x))   
                target_y = max(-300.0, min(300.0, last_sent_y + step_y)) 
                target_z = max(-55.0, min(270.0, last_sent_z + step_z))   

                print(f">> VOICE STEP [{local_voice_action}]: Moving to ({target_x:.1f}, {target_y:.1f}, {target_z:.1f})")
                send_motion_cmd(motion_sock, f"MovJ({target_x:.2f},{target_y:.2f},{target_z:.2f},0.0)")
                
                last_sent_x, last_sent_y, last_sent_z = target_x, target_y, target_z
                robot_start_x, robot_start_y, robot_start_z = target_x, target_y, target_z
                active_mode = None
                time.sleep(0.2) 
                continue

            if local_webcam_reset:
                print(">> EMERGENCY SYSTEM RESET EXECUTED!")
                send_dashboard_cmd(dash_sock, "ClearError()")
                time.sleep(0.05)
                send_dashboard_cmd(dash_sock, "EnableRobot()")
                time.sleep(0.05)
                send_motion_cmd(motion_sock, "MovJ(350, 0, 0, 0)")
                active_mode = None
                last_sent_x, last_sent_y, last_sent_z = 350.0, 0.0, 0.0
                robot_start_x, robot_start_y, robot_start_z = 350.0, 0.0, 0.0
                time.sleep(1.0)
                continue

            msg = None
            v_time = 0
            with data_lock:
                msg = latest_udp_msg
                v_time = last_vr_packet_time

            grip_pressed = False
            vr_timeout = (time.perf_counter() - v_time) > 0.15 

            if msg and not vr_timeout and msg != "QUIT":
                parts = msg.split(',')
                if len(parts) >= 5:
                    grip_pressed = int(parts[0]) == 1
                    vr_x, vr_y, vr_z = float(parts[1]), float(parts[2]), float(parts[3])
                    if int(parts[4]) == 1: 
                        with data_lock: webcam_reset_triggered = True
                        continue

            if grip_pressed:
                if active_mode != "VR":
                    active_mode = "VR"
                    vr_start_x, vr_start_y, vr_start_z = vr_x, vr_y, vr_z
                    robot_start_x, robot_start_y, robot_start_z = last_sent_x, last_sent_y, last_sent_z
                
                delta_x = (vr_z - vr_start_z) * 1000 * SCALE_FACTOR  
                delta_y = (vr_x - vr_start_x) * -1000 * SCALE_FACTOR 
                delta_z = (vr_y - vr_start_y) * 1000 * SCALE_FACTOR  

                raw_target_x = robot_start_x + delta_x
                raw_target_y = robot_start_y + delta_y
                raw_target_z = robot_start_z + delta_z

            elif local_hand_data is not None and local_hand_data[3] is True:
                hx, hy, h_depth, _ = local_hand_data
                
                if active_mode != "WEBCAM":
                    active_mode = "WEBCAM"
                    w_start_x, w_start_y, w_start_depth = hx, hy, h_depth
                    robot_start_x, robot_start_y, robot_start_z = last_sent_x, last_sent_y, last_sent_z
                
                delta_x = (h_depth - w_start_depth) * 1500 * SCALE_FACTOR  
                delta_y = (w_start_x - hx) * 750 * SCALE_FACTOR  
                delta_z = (w_start_y - hy) * 750 * SCALE_FACTOR  

                raw_target_x = robot_start_x + delta_x
                raw_target_y = robot_start_y + delta_y
                raw_target_z = robot_start_z + delta_z
            
            else:
                if active_mode is not None:
                    active_mode = None
                    robot_start_x, robot_start_y, robot_start_z = last_sent_x, last_sent_y, last_sent_z
                time.sleep(0.005)
                continue

            raw_target_x = max(130.0, min(415.0, raw_target_x))   
            raw_target_y = max(-300.0, min(300.0, raw_target_y)) 
            raw_target_z = max(-55.0, min(270.0, raw_target_z))   

            target_x = last_sent_x + ALPHA * (raw_target_x - last_sent_x)
            target_y = last_sent_y + ALPHA * (raw_target_y - last_sent_y)
            target_z = last_sent_z + ALPHA * (raw_target_z - last_sent_z)

            move_dist = math.sqrt((target_x - last_sent_x)**2 + (target_y - last_sent_y)**2 + (target_z - last_sent_z)**2)

            current_time = time.perf_counter()
            if (current_time - last_command_time > 0.130):
                if move_dist > 2.0:  
                    send_motion_cmd(motion_sock, f"MovJ({target_x:.2f},{target_y:.2f},{target_z:.2f},0.0)")
                    last_sent_x, last_sent_y, last_sent_z = target_x, target_y, target_z
                last_command_time = current_time
            
            time.sleep(0.002)

    except KeyboardInterrupt: pass
    finally:
        running = False
        print("Closing Connections...")
        dash_sock.close()
        motion_sock.close()
        udp_sock.close()

if __name__ == "__main__":
    main()

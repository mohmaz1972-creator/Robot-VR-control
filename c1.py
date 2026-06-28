import socket
import time
import math
import threading
import os
import urllib.request

# --- تنظیمات شبکه ---
ROBOT_IP = "192.168.1.6"  
DASHBOARD_PORT = 29999    
MOTION_PORT = 30003       
UDP_IN_PORT = 5005        
UNITY_VIDEO_PORT = 5006   

latest_udp_msg = None
last_vr_packet_time = 0
webcam_reset_triggered = False  
webcam_hand_data = None  
data_lock = threading.Lock()
running = True

def send_dashboard_cmd(sock, cmd):
    try:
        sock.sendall((cmd + "\n").encode('utf-8'))
        time.sleep(0.005)
        return sock.recv(1024).decode('utf-8')
    except: return "Error"

def send_motion_cmd(sock, cmd):
    try: sock.sendall((cmd + "\n").encode('utf-8'))
    except Exception as e: print(f"Motion send error: {e}")

def udp_receiver(sock):
    global latest_udp_msg, last_vr_packet_time, running
    sock.setblocking(False)
    while running:
        last_msg = None
        while True:
            try:
                data, _ = sock.recvfrom(1024)
                last_msg = data.decode('utf-8')
            except BlockingIOError: break  
            except: break
        if last_msg:
            with data_lock:
                latest_udp_msg = last_msg
                last_vr_packet_time = time.perf_counter()
        time.sleep(0.002)

def dist3d(p1, p2):
    return math.sqrt((p1.x - p2.x)**2 + (p1.y - p2.y)**2 + (p1.z - p2.z)**2)

def webcam_analyzer():
    global webcam_reset_triggered, webcam_hand_data, running
    try:
        import cv2
        import mediapipe as mp
        from mediapipe.tasks import python
        from mediapipe.tasks.python import vision
    except ImportError:
        print(">> Core Error: Please install 'opencv-python' and 'mediapipe'.")
        return

    script_dir = os.path.dirname(os.path.abspath(__file__))
    model_path = os.path.join(script_dir, "hand_landmarker.task")
    if not os.path.exists(model_path):
        url = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
        urllib.request.urlretrieve(url, model_path)

    video_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    base_options = python.BaseOptions(model_asset_path=model_path, delegate=python.BaseOptions.Delegate.CPU)
    options = vision.HandLandmarkerOptions(base_options=base_options, running_mode=vision.RunningMode.VIDEO, num_hands=2)
    
    cap = cv2.VideoCapture(0)
    active_hand_raised_start_time = None
    frame_counter = 0
    detection_result = None
    
    with vision.HandLandmarker.create_from_options(options) as detector:
        while running:
            ret, frame = cap.read()
            if not ret: continue
            frame = cv2.flip(frame, 1)
            h, w, _ = frame.shape
            reset_zone_y = int(h * 0.20)
            
            frame_counter += 1
            if frame_counter % 2 == 0:
                small_input = cv2.resize(frame, (320, 240))
                rgb_frame = cv2.cvtColor(small_input, cv2.COLOR_BGR2RGB)
                mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
                detection_result = detector.detect_for_video(mp_img, int(time.perf_counter() * 1000))
            
            any_hand_in_reset_zone = False
            current_hand_frame_data = None
            
            if detection_result and detection_result.hand_landmarks and detection_result.handedness:
                for idx, hand_handedness in enumerate(detection_result.handedness):
                    label = hand_handedness[0].category_name
                    l = detection_result.hand_landmarks[idx]
                    if int(l[0].y * h) < reset_zone_y: any_hand_in_reset_zone = True
                    
                    if label == "Left": 
                        hand_size_3d = dist3d(l[0], l[9])
                        is_index_active = dist3d(l[8], l[5]) > 0.65 * hand_size_3d and dist3d(l[12], l[9]) < 0.45 * hand_size_3d
                        raw_depth_size = math.sqrt((l[0].x - l[9].x)**2 + (l[0].y - l[9].y)**2)
                        current_hand_frame_data = (l[0].x, l[0].y, raw_depth_size, is_index_active)
            
            with data_lock: webcam_hand_data = current_hand_frame_data

            if any_hand_in_reset_zone:
                if active_hand_raised_start_time is None: active_hand_raised_start_time = time.perf_counter()
                elif time.perf_counter() - active_hand_raised_start_time >= 3.0:
                    with data_lock: webcam_reset_triggered = True
                    active_hand_raised_start_time = None
            else: active_hand_raised_start_time = None
            
            try:
                unity_ready_frame = cv2.resize(frame, (240, 180)) 
                _, encoded_img = cv2.imencode('.jpg', unity_ready_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 40])
                video_sock.sendto(encoded_img.tobytes(), ("127.0.0.1", UNITY_VIDEO_PORT))
            except: pass
    cap.release()

def main():
    global latest_udp_msg, webcam_reset_triggered, webcam_hand_data, running
    try:
        dash_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        dash_sock.connect((ROBOT_IP, DASHBOARD_PORT))
        motion_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        motion_sock.connect((ROBOT_IP, MOTION_PORT))
    except: return

    send_dashboard_cmd(dash_sock, "ClearError()")
    send_dashboard_cmd(dash_sock, "EnableRobot()")
    send_motion_cmd(motion_sock, "MovJ(350, 0, 0, 0)")
    time.sleep(1.2)

    udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_sock.bind(("127.0.0.1", UDP_IN_PORT))
    
    threading.Thread(target=udp_receiver, args=(udp_sock,), daemon=True).start()
    threading.Thread(target=webcam_analyzer, daemon=True).start()

    active_mode = None 
    last_sent_x, last_sent_y, last_sent_z = 350.0, 0.0, 0.0
    robot_start_x, robot_start_y, robot_start_z = 350.0, 0.0, 0.0
    SCALE_FACTOR, ALPHA = 1.0 / 3.0, 0.90  
    last_command_time = time.perf_counter()

    try:
        while True:
            local_webcam_reset = False
            local_hand_data = None
            with data_lock:
                if webcam_reset_triggered:
                    local_webcam_reset = True
                    webcam_reset_triggered = False
                local_hand_data = webcam_hand_data

            if local_webcam_reset:
                send_dashboard_cmd(dash_sock, "ClearError();EnableRobot()")
                send_motion_cmd(motion_sock, "MovJ(350, 0, 0, 0)")
                last_sent_x, last_sent_y, last_sent_z = 350.0, 0.0, 0.0
                active_mode = None
                time.sleep(1.0)
                continue

            msg = None
            with data_lock: msg = latest_udp_msg
            grip_pressed = False
            if msg and msg != "QUIT":
                parts = msg.split(',')
                if len(parts) >= 5: grip_pressed = int(parts[0]) == 1

            if grip_pressed:
                # منطق VR (منطبق با نسخه ۳)
                pass
            elif local_hand_data is not None and local_hand_data[3] is True:
                hx, hy, h_depth, _ = local_hand_data
                if active_mode != "WEBCAM":
                    active_mode = "WEBCAM"
                    w_start_x, w_start_y, w_start_depth = hx, hy, h_depth
                    robot_start_x, robot_start_y, robot_start_z = last_sent_x, last_sent_y, last_sent_z
                
                raw_target_x = robot_start_x + (h_depth - w_start_depth) * 1500 * SCALE_FACTOR
                raw_target_y = robot_start_y + (w_start_x - hx) * 750 * SCALE_FACTOR
                raw_target_z = robot_start_z + (w_start_y - hy) * 750 * SCALE_FACTOR

                raw_target_x = max(130.0, min(415.0, raw_target_x))
                raw_target_y = max(-300.0, min(300.0, raw_target_y))
                raw_target_z = max(-55.0, min(270.0, raw_target_z))

                target_x = last_sent_x + ALPHA * (raw_target_x - last_sent_x)
                target_y = last_sent_y + ALPHA * (raw_target_y - last_sent_y)
                target_z = last_sent_z + ALPHA * (raw_target_z - last_sent_z)

                if (time.perf_counter() - last_command_time > 0.130):
                    send_motion_cmd(motion_sock, f"MovJ({target_x:.2f},{target_y:.2f},{target_z:.2f},0.0)")
                    last_sent_x, last_sent_y, last_sent_z = target_x, target_y, target_z
                    last_command_time = time.perf_counter()
            else:
                active_mode = None
            time.sleep(0.002)
    except KeyboardInterrupt: pass
    finally: running = False

if __name__ == "__main__":
    main()

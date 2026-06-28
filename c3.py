import socket
import time
import math
import threading

# --- تنظیمات شبکه و ربات ---
ROBOT_IP = "192.168.1.6"  
DASHBOARD_PORT = 29999    
MOTION_PORT = 30003       
UDP_IN_PORT = 5005        

latest_udp_msg = None
last_vr_packet_time = 0
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

def main():
    global latest_udp_msg, running
    try:
        dash_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        dash_sock.connect((ROBOT_IP, DASHBOARD_PORT))
        motion_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        motion_sock.connect((ROBOT_IP, MOTION_PORT))
        print("Robot Connected. Starting VR Loop...")
    except Exception as e:
        print(f"Connection failed: {e}")
        return

    send_dashboard_cmd(dash_sock, "ClearError()")
    send_dashboard_cmd(dash_sock, "EnableRobot()")
    send_motion_cmd(motion_sock, "MovJ(350, 0, 0, 0)") 
    time.sleep(1.2)

    udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_sock.bind(("127.0.0.1", UDP_IN_PORT))
    threading.Thread(target=udp_receiver, args=(udp_sock,), daemon=True).start()

    active_mode = None 
    last_sent_x, last_sent_y, last_sent_z = 350.0, 0.0, 0.0
    robot_start_x, robot_start_y, robot_start_z = 350.0, 0.0, 0.0
    vr_start_x, vr_start_y, vr_start_z = 0.0, 0.0, 0.0
    last_command_time = time.perf_counter()

    SCALE_FACTOR = 1.0 / 3.0  
    ALPHA = 0.90  

    try:
        while True:
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

                raw_target_x = max(130.0, min(415.0, raw_target_x))   
                raw_target_y = max(-300.0, min(300.0, raw_target_y)) 
                raw_target_z = max(-55.0, min(270.0, raw_target_z))   

                target_x = last_sent_x + ALPHA * (raw_target_x - last_sent_x)
                target_y = last_sent_y + ALPHA * (raw_target_y - last_sent_y)
                target_z = last_sent_z + ALPHA * (raw_target_z - last_sent_z)

                move_dist = math.sqrt((target_x - last_sent_x)**2 + (target_y - last_sent_y)**2 + (target_z - last_sent_z)**2)
                current_time = time.perf_counter()
                if (current_time - last_command_time > 0.130) and move_dist > 2.0:
                    send_motion_cmd(motion_sock, f"MovJ({target_x:.2f},{target_y:.2f},{target_z:.2f},0.0)")
                    last_sent_x, last_sent_y, last_sent_z = target_x, target_y, target_z
                    last_command_time = current_time
            else:
                active_mode = None
            time.sleep(0.002)
    except KeyboardInterrupt: pass
    finally:
        running = False
        dash_sock.close()
        motion_sock.close()
        udp_sock.close()

if __name__ == "__main__":
    main()

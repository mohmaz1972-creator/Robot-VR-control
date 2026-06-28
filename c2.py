import socket
import time

# --- تنظیمات شبکه و ربات ---
ROBOT_IP = "192.168.1.6"  
DASHBOARD_PORT = 29999    
MOTION_PORT = 30003       

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

def main():
    print("Connecting to Dobot MG400...")
    try:
        dash_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        dash_sock.connect((ROBOT_IP, DASHBOARD_PORT))
        motion_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        motion_sock.connect((ROBOT_IP, MOTION_PORT))
        motion_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        dash_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        print("Robot Connected successfully.")
    except Exception as e:
        print(f"Robot connection failed: {e}.")
        return

    # مقداردهی اولیه ربات
    send_dashboard_cmd(dash_sock, "ClearError()")
    send_dashboard_cmd(dash_sock, "EnableRobot()")
    
    send_dashboard_cmd(dash_sock, "SpeedFactor(100)") 
    send_dashboard_cmd(dash_sock, "CP(100)")           
    send_dashboard_cmd(dash_sock, "VelJ(100)")          
    send_dashboard_cmd(dash_sock, "AccJ(85)")           

    # حرکت به نقطه صفر فرضی
    print("Moving to Home position...")
    send_motion_cmd(motion_sock, "MovJ(350, 0, 0, 0)") 
    time.sleep(1.2)

    print("Target reached. Closing connections.")
    dash_sock.close()
    motion_sock.close()

if __name__ == "__main__":
    main()

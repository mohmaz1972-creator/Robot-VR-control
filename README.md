# Robot-VR-control
Control the dobot mg400 robotic arm with the Meta Quest 3 virtual reality headset + voice control + visual control
# Real-Time VR & AI Robotic Arm Controller (Robot-VR-control)

An advanced, multithreaded cyber-physical system built to establish real-time teleoperation and control over the **Dobot MG400** robotic arm. By integrating **Meta Quest 3** VR hardware with **Python-driven AI algorithms**, this project bridges immersive virtual reality environments with precise physical automation.

---

## 🚀 Key Features

*   **Immersive VR Teleoperation:** Real-time tracking of the Meta Quest 3 Right Controller's position to control the physical robotic arm coordinates over UDP.
*   **Dual-Stream Vision:** High-speed streaming of live webcam feeds back to the VR headset, including target tracking visual overlays.
*   **AI-Powered Hand Tracking:** Real-time computer vision integration using MediaPipe to map hand movements dynamically.
*   **Offline Voice Automation:** Integrated offline speech recognition via the Vosk framework to dispatch asynchronous voice commands to the robot.
*   **Safe Network Architecture:** Implements optimized C# UDP/TCP sockets in Unity and low-latency multithreaded networking loops in Python to ensure stutter-free performance.

---

## 🏗️ Repository Architecture

The repository archives the progressive evolution of the project's development across distinct logical layers:

```text
├── Unity_Project/                # Immersive XR Environment
│   ├── SampleScene.unity        # Main virtual reality control layout
│   ├── VRControllerTracker.cs  # Extracts Quest 3 tracking data and dispatches to Python
│   ├── WebcamStreamReceiver.cs  # Receives and renders external camera streams on Unity main thread
│   └── LiveRobotCamera.cs       # Direct interface for local virtual/physical camera drivers (e.g., Iriun)
│
├── c1.py                        # Architecture initialization and base network routing
├── c2.py                        # TCP/IP communication protocols and Dobot MG400 API integration
├── c3.py                        # UDP listener loop for Quest 3 controller packet parsing
├── c4.py                        # MediaPipe pipeline execution and frame-buffer streaming to Unity
└── c5.py                        # Vosk speech processing engine and finalized multithreaded robot controller

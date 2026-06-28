using UnityEngine;

public class LiveRobotCamera : MonoBehaviour
{
    private WebCamTexture webcamTexture;
    private Renderer screenRenderer;

    void Start()
    {
        screenRenderer = GetComponent<Renderer>();
        if (screenRenderer == null)
        {
            Debug.LogError("[CAMERA_ERROR] This script must be attached to an object with a Renderer component (e.g., a Quad)!");
            return;
        }

        // 1. Log all detected camera devices to the console for debugging
        WebCamDevice[] devices = WebCamTexture.devices;
        Debug.Log("[CAMERA_INFO] Number of detected cameras: " + devices.Length);
        
        string selectedCameraName = "";
        foreach (var device in devices)
        {
            Debug.Log("[CAMERA_LIST] Found camera: " + device.name);
            if (device.name.ToLower().Contains("iriun"))
            {
                selectedCameraName = device.name;
            }
        }

        // 2. Fallback: If Iriun Webcam is not found, select the first available camera
        if (string.IsNullOrEmpty(selectedCameraName) && devices.Length > 0)
        {
            selectedCameraName = devices[0].name;
            Debug.LogWarning("[CAMERA_WARN] Iriun camera not found! Falling back to: " + selectedCameraName);
        }

        // 3. Initialize the camera stream using default resolution settings
        if (!string.IsNullOrEmpty(selectedCameraName))
        {
            // Removed forced resolution and frame rate to ensure 100% compatibility with Windows/driver defaults
            webcamTexture = new WebCamTexture(selectedCameraName);
            
            // Material compatibility fix for Built-in Pipeline, URP, and VR projects
            Material mat = screenRenderer.material;
            mat.mainTexture = webcamTexture; // Fallback for Built-in Pipeline
            if (mat.HasProperty("_BaseMap"))   // Target for Universal Render Pipeline (URP / VR Headsets)
            {
                mat.SetTexture("_BaseMap", webcamTexture);
            }

            webcamTexture.Play();
            Debug.Log("[CAMERA_SUCCESS] Live stream started successfully from: " + selectedCameraName);
        }
        else
        {
            Debug.LogError("[CAMERA_ERROR] No webcam device (physical or virtual) was detected on this system!");
        }
    }

    void OnDestroy()
    {
        if (webcamTexture != null && webcamTexture.isPlaying)
        {
            webcamTexture.Stop();
        }
    }
}

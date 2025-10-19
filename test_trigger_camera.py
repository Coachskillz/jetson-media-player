"""Simple test of trigger service with camera - no IPC."""

import cv2
import time
from src.trigger_engine.age_detector import AgeDetector

print("Testing camera with age detector...")

# Initialize detector
detector = AgeDetector(use_gpu=False)
print("✅ Detector initialized")

# Open camera
camera = cv2.VideoCapture(0)

if not camera.isOpened():
    print("❌ Cannot open camera")
    exit(1)

print("✅ Camera opened")
print("Press 'q' to quit")

last_trigger = None
frame_count = 0

while True:
    ret, frame = camera.read()
    
    if not ret:
        print("Failed to read frame")
        break
    
    # Detect and estimate every 10 frames (for performance)
    if frame_count % 10 == 0:
        detections = detector.detect_and_estimate(frame)
        
        if detections:
            trigger, confidence = detector.determine_trigger(detections)
            
            if trigger != last_trigger:
                print(f"🎯 Trigger: {trigger} (confidence: {confidence:.2f})")
                print(f"   Detected {len(detections)} face(s)")
                for i, d in enumerate(detections):
                    print(f"   Face {i+1}: Age {d.age}, Gender {d.gender}")
                last_trigger = trigger
        else:
            if last_trigger != "no_faces":
                print("👤 No faces detected")
                last_trigger = "no_faces"
    
    frame_count += 1
    
    # Show frame
    cv2.imshow('Trigger Test', frame)
    
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

camera.release()
cv2.destroyAllWindows()
print("\n✅ Test completed")

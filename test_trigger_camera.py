"""Simple test of trigger service with camera - no IPC."""

import cv2
import time
from src.trigger_engine.age_detector import AgeDetector

print("Testing camera with REAL age/gender models...")

# Initialize detector with REAL models
detector = AgeDetector(use_gpu=False)
print("✅ Detector initialized with REAL models")

# Open camera
camera = cv2.VideoCapture(0)

if not camera.isOpened():
    print("❌ Cannot open camera")
    exit(1)

# Give camera time to initialize
time.sleep(1)

print("✅ Camera opened")
print("Press 'q' to quit")
print("\nNOTE: Ages and gender are now REAL predictions from ML models!")

last_trigger = None
frame_count = 0

try:
    while True:
        ret, frame = camera.read()
        
        if not ret:
            print("⚠️  Failed to read frame, retrying...")
            time.sleep(0.1)
            continue
        
        # Detect and estimate every 10 frames (for performance)
        if frame_count % 10 == 0:
            detections = detector.detect_and_estimate(frame)
            
            if detections:
                trigger, confidence = detector.determine_trigger(detections)
                
                if trigger != last_trigger:
                    print(f"\n🎯 Trigger: {trigger} (confidence: {confidence:.2f})")
                    print(f"   Detected {len(detections)} face(s)")
                    for i, d in enumerate(detections):
                        print(f"   Face {i+1}: Age {d.age}, Gender {d.gender}, " +
                              f"Age Conf: {d.age_confidence:.2f}, Gender Conf: {d.gender_confidence:.2f}")
                    last_trigger = trigger
            else:
                if last_trigger != "no_faces":
                    print("\n👤 No faces detected")
                    last_trigger = "no_faces"
        
        frame_count += 1
        
        # Show frame
        cv2.imshow('REAL Age/Gender Detection', frame)
        
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

except KeyboardInterrupt:
    print("\n\n⚠️  Interrupted by user")

finally:
    camera.release()
    cv2.destroyAllWindows()
    print("\n✅ Test completed")

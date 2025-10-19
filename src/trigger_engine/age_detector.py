"""
Age and gender detection using real ML models.
Detects faces and estimates demographics.
"""

import cv2
import numpy as np
from typing import List, Tuple
from dataclasses import dataclass
from src.common.logger import setup_logger

logger = setup_logger(__name__)


@dataclass
class FaceDetection:
    """Represents a detected face with age and gender estimation."""
    bbox: Tuple[int, int, int, int]
    age: int
    gender: str
    age_confidence: float
    gender_confidence: float


class AgeDetector:
    """Age and gender detection system using real ML models."""
    
    def __init__(self, use_gpu: bool = False):
        """Initialize age detector with real models."""
        self.use_gpu = use_gpu
        
        # Face detector
        self.face_detector = cv2.CascadeClassifier(
            cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        )
        
        # Load age estimation model
        age_proto = "models/age_deploy.prototxt"
        age_model = "models/age_net.caffemodel"
        self.age_net = cv2.dnn.readNet(age_model, age_proto)
        
        # Load gender detection model
        gender_proto = "models/gender_deploy.prototxt"
        gender_model = "models/gender_net.caffemodel"
        self.gender_net = cv2.dnn.readNet(gender_model, gender_proto)
        
        # Model parameters
        self.MODEL_MEAN_VALUES = (78.4263377603, 87.7689143744, 114.895847746)
        
        # Age ranges the model predicts
        self.AGE_LIST = ['(0-2)', '(4-6)', '(8-12)', '(15-20)', '(25-32)', 
                         '(38-43)', '(48-53)', '(60-100)']
        self.GENDER_LIST = ['Male', 'Female']
        
        logger.info(f"Age detector initialized with REAL models (GPU: {use_gpu})")
    
    def detect_faces(self, frame: np.ndarray) -> List[Tuple[int, int, int, int]]:
        """Detect faces in a frame."""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = self.face_detector.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30)
        )
        return faces
    
    def estimate_demographics(self, frame: np.ndarray, bbox: Tuple[int, int, int, int]) -> Tuple[int, float, str, float]:
        """
        Estimate age and gender using REAL ML models.
        
        Args:
            frame: Input image
            bbox: Face bounding box (x, y, width, height)
            
        Returns:
            Tuple of (estimated_age, age_confidence, gender, gender_confidence)
        """
        x, y, w, h = bbox
        
        # Extract face with padding
        padding = 20
        face = frame[max(0, y-padding):min(frame.shape[0], y+h+padding),
                     max(0, x-padding):min(frame.shape[1], x+w+padding)]
        
        if face.size == 0:
            return 30, 0.5, "unknown", 0.5
        
        # Prepare blob for models (227x227 input)
        blob = cv2.dnn.blobFromImage(face, 1.0, (227, 227), 
                                      self.MODEL_MEAN_VALUES, swapRB=False)
        
        # Predict gender
        self.gender_net.setInput(blob)
        gender_preds = self.gender_net.forward()
        gender_idx = gender_preds[0].argmax()
        gender = self.GENDER_LIST[gender_idx].lower()
        gender_conf = float(gender_preds[0][gender_idx])
        
        # Predict age
        self.age_net.setInput(blob)
        age_preds = self.age_net.forward()
        age_idx = age_preds[0].argmax()
        age_range = self.AGE_LIST[age_idx]
        age_conf = float(age_preds[0][age_idx])
        
        # Convert age range to single age value (use midpoint)
        age_map = {
            '(0-2)': 1,
            '(4-6)': 5,
            '(8-12)': 10,
            '(15-20)': 18,
            '(25-32)': 28,
            '(38-43)': 40,
            '(48-53)': 50,
            '(60-100)': 70
        }
        estimated_age = age_map.get(age_range, 30)
        
        return estimated_age, age_conf, gender, gender_conf
    
    def detect_and_estimate(self, frame: np.ndarray) -> List[FaceDetection]:
        """Detect faces and estimate demographics using REAL models."""
        faces = self.detect_faces(frame)
        results = []
        
        for (x, y, w, h) in faces:
            age, age_conf, gender, gender_conf = self.estimate_demographics(frame, (x, y, w, h))
            results.append(FaceDetection(
                bbox=(x, y, w, h),
                age=age,
                gender=gender,
                age_confidence=age_conf,
                gender_confidence=gender_conf
            ))
        
        return results
    
    def determine_trigger(self, detections: List[FaceDetection]) -> Tuple[str, float]:
        """
        Determine which trigger to send based on detected faces.
        
        Rules:
        - If ANY face < 27: trigger "age:under_27" (safety/default)
        - If all faces 27-60: trigger "age:adult"  
        - If all faces 61+: trigger "age:senior"
        - If no faces: trigger "age:default"
        """
        if not detections:
            return "age:default", 1.0
        
        ages = [d.age for d in detections]
        confidences = [d.age_confidence for d in detections]
        avg_confidence = sum(confidences) / len(confidences)
        
        # Safety check: If ANY face under 27
        if any(age < 27 for age in ages):
            logger.info(f"Safety trigger: Face under 27 detected (ages: {ages})")
            return "age:under_27", avg_confidence
        
        # All faces 61+
        if all(age >= 61 for age in ages):
            logger.info(f"Senior trigger: All faces 61+ (ages: {ages})")
            return "age:senior", avg_confidence
        
        # All faces 27-60
        if all(27 <= age <= 60 for age in ages):
            logger.info(f"Adult trigger: All faces 27-60 (ages: {ages})")
            return "age:adult", avg_confidence
        
        # Mixed ages (27+), default to adult
        logger.info(f"Mixed ages detected, defaulting to adult (ages: {ages})")
        return "age:adult", avg_confidence

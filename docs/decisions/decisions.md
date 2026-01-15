# Architectural Decisions Log

## 2026-01-15 - DeepStream for Face Detection
**Context:** Need real-time face detection on Jetson Orin Nano
**Decision:** Use NVIDIA DeepStream SDK
**Reasoning:** Hardware-optimized pipeline, nvtracker, batched inference
**Alternatives:** Custom GStreamer + TensorRT, OpenCV DNN

## 2026-01-15 - FAISS-GPU for Face Matching
**Context:** Match faces against 100K+ database in <5ms
**Decision:** Use FAISS with GPU support
**Reasoning:** <1ms search time vs 50ms+ on CPU
**Alternatives:** Annoy, custom cosine similarity

## 2026-01-15 - Three-Tier Architecture
**Context:** Manage 250+ edge devices across 37 states
**Decision:** Central Hub → Local Hub → Jetson
**Reasoning:** Offline resilience, reduced WAN bandwidth, local caching
**Alternatives:** Direct cloud-to-device, peer-to-peer

## 2026-01-15 - NCMEC Poster API Integration
**Context:** Need to fetch missing children data for facial recognition matching
**Decision:** Use existing NCMECPosterClient with OAuth2 client credentials
**Reasoning:** Already have working API client, proven authentication flow
**Endpoints:** /Auth/Token for auth, /Poster/Search for data
**Data Flow:** Central Hub → FAISS embeddings → Local Hub → Jetson

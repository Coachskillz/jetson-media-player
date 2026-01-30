# Dual Camera Architecture Technical Specification

## Skillz Media - Edge AI Digital Signage Platform

**Version:** 1.0
**Date:** January 2026
**Platform:** NVIDIA Jetson Orin NX / Orin Nano

---

## 1. System Overview

### 1.1 Purpose

The Skillz Media dual-camera system separates safety functionality (NCMEC missing children detection) from commercial functionality (marketing analytics, loyalty recognition, age-gated content) using physically separate cameras and logically isolated pipelines. This separation ensures legal compliance, privacy protection, and clear audit boundaries.

### 1.2 Hardware Requirements

| Component | Specification |
|-----------|--------------|
| **Compute Module** | NVIDIA Jetson Orin NX 8GB / Orin Nano 8GB |
| **OS** | JetPack 6.x (L4T R36.4+, Ubuntu 22.04) |
| **Camera 1 (Safety)** | IMX219 CSI camera on CSI Port 0 |
| **Camera 2 (Commercial)** | IMX219 CSI camera on CSI Port 1 |
| **Storage** | NVMe SSD (minimum 64GB) |
| **Network** | Gigabit Ethernet (primary), WiFi (fallback) |
| **Display** | HDMI output for digital signage screen |

### 1.3 Software Stack

| Layer | Technology |
|-------|-----------|
| **OS** | Ubuntu 22.04 (JetPack 6.x) |
| **GPU Framework** | CUDA 12.x, cuDNN 9.x |
| **Video Pipeline** | DeepStream 7.x, GStreamer 1.20 |
| **Inference** | TensorRT 10.x (INT8/FP16) |
| **Face Detection** | RetinaFace (TensorRT engine) |
| **Face Encoding** | ArcFace (TensorRT engine, 512-dim) |
| **Age/Gender** | Custom classifier (TensorRT engine) |
| **Vector Search** | FAISS-GPU |
| **IPC** | ZeroMQ (inter-process triggers) |
| **Runtime** | Python 3.10+ |

### 1.4 Network Architecture

```
                    +-----------------------+
                    |     Central Hub       |
                    |  (Cloud / Railway)    |
                    |                       |
                    |  - CMS Admin          |
                    |  - Content Catalog    |
                    |  - NCMEC Sync         |
                    |  - Alert Dashboard    |
                    +-----------+-----------+
                                |
                          WAN (TLS 1.3)
                                |
                    +-----------+-----------+
                    |     Local Hub         |
                    |  (Per-Store Server)   |
                    |                       |
                    |  - Content Cache      |
                    |  - FAISS Index Cache  |
                    |  - Alert Relay        |
                    |  - Device Manager     |
                    +-----------+-----------+
                                |
                          LAN (Gigabit)
                                |
         +----------------------+----------------------+
         |                                             |
+--------+--------+                          +--------+--------+
|  Camera 1 (CSI0) |                          |  Camera 2 (CSI1) |
|  SAFETY SYSTEM   |                          |  COMMERCIAL SYS  |
|                  |                          |                  |
|  RetinaFace      |     Jetson Orin NX       |  RetinaFace      |
|  ArcFace         |     +-----------+        |  Age/Gender      |
|  NCMEC Match     +---->| Media     |<-------+  ArcFace Loyalty |
|                  |     | Player    |        |  People Count    |
|  Alerts Only     |     | (HDMI)   |        |  Dwell Time      |
+------------------+     +-----------+        +------------------+
```

### 1.5 Process Architecture

The system runs as three independent systemd services:

| Service | Process | Camera | Purpose |
|---------|---------|--------|---------|
| `skillz-player.service` | Media Player | None | Content playback on HDMI |
| `skillz-safety.service` | Safety Pipeline | CSI Port 0 | NCMEC detection + alerts |
| `skillz-commercial.service` | Commercial Pipeline | CSI Port 1 | Analytics + loyalty + triggers |

Inter-process communication uses ZeroMQ:
- **Commercial -> Player:** Content triggers (age gate, loyalty, demographic)
- **Safety -> Hub:** NCMEC alert notifications
- **Both -> Hub:** Heartbeat and status reporting

---

## 2. Camera 1 - Safety System (NCMEC)

### 2.1 Purpose

Camera 1 is dedicated exclusively to missing children identification through the National Center for Missing & Exploited Children (NCMEC) partnership. This camera operates under public safety exemptions and maintains strict data handling requirements.

### 2.2 DeepStream Pipeline

```
nvarguscamerasrc (sensor-id=0, 1920x1080 @ 30fps)
    |
nvvideoconvert (NVMM format)
    |
capsfilter (video/x-raw(memory:NVMM), NV12)
    |
nvstreammux (batch-size=1, live-source=1)
    |
nvinfer [PGIE] (RetinaFace - face detection)
    |    - Confidence threshold: 0.7
    |    - Process interval: 2 (every 3rd frame = 10fps)
    |    - Min face size: 64x64 pixels
    |
nvtracker (IOU tracker)
    |    - Max simultaneous tracks: 30
    |    - Min track age: 3 frames
    |    - Max missed frames: 30
    |
nvinfer [SGIE1] (ArcFace - face encoding)
    |    - Output: 512-dim embedding vector
    |    - output-tensor-meta=1
    |
probe callback (FAISS-GPU matching)
    |    - NCMEC database search (threshold: 0.6)
    |    - Match -> queue alert
    |    - No match -> discard embedding immediately
    |
fakesink (no display output)
```

### 2.3 Model Specifications

#### RetinaFace (Primary Detector)
| Parameter | Value |
|-----------|-------|
| Input Resolution | 640x640 |
| Precision | FP16 |
| Batch Size | 1 |
| Process Interval | 2 (every 3rd frame) |
| Confidence Threshold | 0.7 |
| NMS IOU Threshold | 0.5 |
| Min Detection Size | 64x64 pixels |
| Inference Time | <20ms |

#### ArcFace (Face Encoder)
| Parameter | Value |
|-----------|-------|
| Input Resolution | 112x112 (aligned face) |
| Precision | FP16 |
| Batch Size | 16 |
| Embedding Dimension | 512 |
| Inference Time | <10ms per face |

### 2.4 NCMEC Database Sync Protocol

```
Central Hub (Cloud)
    |
    | 1. Daily batch from NCMEC Poster API
    |    POST /Auth/Token (OAuth2 client credentials)
    |    POST /Poster/Search (fetch poster data)
    |
    | 2. Extract face images from posters
    | 3. Generate 512-dim ArcFace embeddings
    | 4. Build FAISS IVF index
    |
    v
Local Hub (Per-Store)
    |
    | 5. Pull FAISS index every 6 hours
    |    GET /api/v1/databases/ncmec/version
    |    GET /api/v1/databases/ncmec/download
    |
    v
Jetson Device
    |
    | 6. Load FAISS index to GPU memory on startup
    | 7. Hot-reload on version change (no restart needed)
    |
    v
GPU Memory (FAISS-GPU index, ~100K vectors)
```

**Index Format:** FAISS IVFFlat with GPU acceleration
**Search Time:** <1ms for 100K vectors
**Memory Usage:** ~200MB GPU for 100K x 512-dim vectors

### 2.5 Alert Notification Flow

```
1. Face detected by RetinaFace
2. Tracked across frames by nvtracker (avoid re-processing)
3. Embedding extracted by ArcFace (512-dim)
4. FAISS-GPU search against NCMEC index
5. If match (similarity > 0.6):
   a. Generate alert with:
      - Alert UUID
      - Device ID + Location ID
      - Timestamp (UTC)
      - Confidence score
      - Matched NCMEC case ID
      - NO face image stored
   b. Queue alert for immediate transmission
   c. Send to Local Hub: POST /api/v1/alerts
   d. Local Hub forwards to Central: POST /api/alerts
   e. Central notifies NCMEC + designated contacts
6. If no match:
   - Embedding discarded immediately
   - No logging of the face
```

**Alert Latency Target:** <2 seconds from face detection to alert queued

### 2.6 Data Handling Rules

| Data Type | Stored? | Retention | Encryption |
|-----------|---------|-----------|------------|
| Camera frames | NO | None | N/A |
| Face embeddings | NO (memory only) | Discarded per-frame | N/A |
| NCMEC index | YES (GPU memory) | Until next sync | AES-256 at rest |
| Match alerts | YES (transit only) | Forwarded immediately | TLS 1.3 in transit |
| Alert metadata | YES (audit log) | 7 years | AES-256 |
| Non-match events | NO | None | N/A |

### 2.7 Logging Requirements

The safety system logs ONLY:
- Service start/stop events
- NCMEC database sync events (version, count, timestamp)
- Match alert events (alert ID, confidence, case ID - NO images)
- Pipeline errors and recovery events
- System health metrics (CPU, GPU, memory)

**Log location:** `/var/log/skillz/safety.log` (encrypted, rotated daily)

---

## 3. Camera 2 - Commercial System

### 3.1 Purpose

Camera 2 handles all commercial functionality including demographic analysis for content targeting, loyalty member recognition (opt-in only), people counting, and dwell time analytics. This system drives the advertising intelligence of the platform.

### 3.2 DeepStream Pipeline

```
nvarguscamerasrc (sensor-id=1, 1920x1080 @ 30fps)
    |
nvvideoconvert (NVMM format)
    |
capsfilter (video/x-raw(memory:NVMM), NV12)
    |
nvstreammux (batch-size=1, live-source=1)
    |
nvinfer [PGIE] (RetinaFace - face detection)
    |    - Confidence threshold: 0.6
    |    - Process interval: 2 (every 3rd frame)
    |
nvtracker (IOU tracker)
    |    - Max simultaneous tracks: 50
    |    - Min track age: 3 frames
    |
+---+---+
|       |
|   nvinfer [SGIE1] (Age/Gender classifier)
|       |    - Output: age bucket + gender
|       |
|   nvinfer [SGIE2] (ArcFace - loyalty recognition)
|       |    - Output: 512-dim embedding
|       |    - Only runs when loyalty DB loaded
|       |
+---+---+
    |
nvdsanalytics (people counting, line crossing, dwell time)
    |    - ROI zones for counting
    |    - Line crossing for entry/exit
    |    - Dwell time per zone
    |
probe callback (trigger logic)
    |    - Age gating decisions
    |    - Loyalty member matching
    |    - Demographic triggers -> ZeroMQ -> Player
    |    - Analytics aggregation
    |
fakesink (no display output)
```

### 3.3 Model Specifications

#### Age/Gender Classifier
| Parameter | Value |
|-----------|-------|
| Input Resolution | 112x112 (aligned face) |
| Precision | INT8 |
| Batch Size | 16 |
| Age Buckets | 0-12, 13-17, 18-24, 25-34, 35-44, 45-54, 55-64, 65+ |
| Gender Classes | Male, Female |
| Inference Time | <5ms per face |

#### ArcFace (Loyalty Recognition)
| Parameter | Value |
|-----------|-------|
| Input Resolution | 112x112 |
| Precision | FP16 |
| Batch Size | 16 |
| Embedding Dimension | 512 |
| Match Threshold | 0.7 (stricter than NCMEC for fewer false positives) |

### 3.4 Age Gating Logic

Content categories and minimum age requirements:

| Content Category | Minimum Age | Examples |
|-----------------|-------------|---------|
| `general` | 0 | Family products, general retail |
| `teen` | 13 | Video games, teen fashion |
| `mature` | 18 | R-rated movie trailers |
| `alcohol` | 21 | Beer, wine, spirits |
| `tobacco` | 21 | Tobacco products |
| `gambling` | 21 | Casino, sports betting |

**Decision Logic:**
```
1. Face detected, age estimated
2. Current content has age rating tag
3. If youngest detected face < content threshold:
   a. Send trigger to player: switch to alternative content
   b. Alternative content selected from same advertiser (family-friendly)
   c. If no alternative, show default playlist content
4. Resume original content when audience changes
5. All decisions based on aggregate (youngest face in view)
```

**Buffer Period:** 5 seconds after underage face exits before returning to age-restricted content.

### 3.5 Loyalty Recognition System

**Consent Model:** Explicit opt-in only. Members enroll via:
1. Mobile app face enrollment
2. In-store kiosk enrollment
3. Web portal photo upload

**Recognition Flow:**
```
1. Face detected and tracked
2. ArcFace embedding extracted
3. Search loyalty FAISS index (threshold: 0.7)
4. If match found:
   a. Retrieve member preferences (stored locally)
   b. Send personalized trigger to player
   c. Log: member_uuid, timestamp, location (for rewards)
5. If no match:
   - Treat as anonymous visitor
   - Use demographic data only for content selection
```

**Loyalty Database Sync:**
- Sync from Local Hub every 4 hours
- Index contains only opted-in members for this network
- Member can revoke consent at any time (removed from next sync)

### 3.6 People Counting & Analytics

Using `nvdsanalytics` plugin with configurable zones:

**Metrics Collected:**
| Metric | Method | Storage |
|--------|--------|---------|
| People count (per zone) | nvtracker + ROI | Aggregated per 15-min bucket |
| Entry/exit count | Line crossing | Aggregated per 15-min bucket |
| Dwell time (per zone) | Track duration in ROI | Averaged per 15-min bucket |
| Peak occupancy | Max simultaneous tracks | Per 15-min bucket |
| Age distribution | Age classifier | Aggregated percentages |
| Gender distribution | Gender classifier | Aggregated percentages |

**All analytics are:**
- Aggregated (never individual-level)
- Anonymized (no face data stored)
- Bucketed in 15-minute windows
- Synced to hub hourly
- Retained for 90 days locally, then deleted

### 3.7 ZeroMQ Trigger Protocol

Commercial system sends triggers to the media player via ZeroMQ PUB/SUB on port 5556:

```json
{
  "type": "trigger",
  "source": "commercial",
  "timestamp": "2026-01-28T21:00:00Z",
  "trigger_type": "demographic",
  "data": {
    "age_range": "25-34",
    "gender": "male",
    "confidence": 0.85,
    "people_count": 3
  },
  "content_id": "ad-beer-brand-summer-2026",
  "priority": 5
}
```

```json
{
  "type": "trigger",
  "source": "commercial",
  "trigger_type": "loyalty",
  "data": {
    "member_uuid": "abc-123",
    "preferences": ["outdoor", "fishing"],
    "tier": "gold"
  },
  "content_id": "loyalty-welcome-gold",
  "priority": 10
}
```

```json
{
  "type": "trigger",
  "source": "commercial",
  "trigger_type": "age_gate",
  "data": {
    "youngest_detected": 15,
    "action": "switch_to_alternative"
  },
  "content_id": "family-friendly-alternative-001",
  "priority": 100
}
```

**Priority:** Higher number = higher priority. Age gating (100) overrides loyalty (10) which overrides demographic (5).

---

## 4. Privacy & Compliance

### 4.1 Data Flow Diagrams

#### Safety System Data Flow
```
Camera 1 Frame
    |
    v
[GPU] Face Detection (frame discarded after detection)
    |
    v
[GPU] Face Encoding (face crop discarded after encoding)
    |
    v
[GPU] FAISS Search (embedding discarded after search)
    |
    +---> No Match: ALL data discarded. Nothing logged.
    |
    +---> Match: Alert metadata only (no image/embedding)
              |
              v
          Alert Queue --> Local Hub --> Central Hub --> NCMEC
```

#### Commercial System Data Flow
```
Camera 2 Frame
    |
    v
[GPU] Face Detection (frame discarded after detection)
    |
    +---> Age/Gender Estimation
    |         |
    |         v
    |     Aggregated demographics (anonymous, 15-min buckets)
    |         |
    |         v
    |     Analytics DB (local, 90-day retention)
    |
    +---> Loyalty Recognition (opt-in members only)
    |         |
    |         v
    |     Member UUID + timestamp (no image/embedding stored)
    |         |
    |         v
    |     Loyalty engagement log (synced to hub)
    |
    +---> People Counting
    |         |
    |         v
    |     Anonymous count per zone (aggregated)
    |
    v
Frame + embedding discarded after processing
```

### 4.2 Consent Requirements Matrix

| Function | Consent Type | Mechanism | Opt-Out |
|----------|-------------|-----------|---------|
| NCMEC Detection | Public safety exemption | None required | N/A |
| Age/Gender Analytics | Notice-based | Signage at entrance | Not applicable (anonymous) |
| People Counting | Notice-based | Signage at entrance | Not applicable (anonymous) |
| Dwell Time Analytics | Notice-based | Signage at entrance | Not applicable (anonymous) |
| Loyalty Recognition | Explicit opt-in | App/kiosk enrollment | Remove via app/support |
| Content Personalization | Legitimate interest | Privacy policy | Opt-out via contact |

### 4.3 Data Retention Policies

| Data Type | Retention | Location | Deletion Method |
|-----------|-----------|----------|----------------|
| Camera frames | 0 (never stored) | N/A | N/A |
| Face embeddings | 0 (memory only) | GPU RAM | Automatic per-frame |
| NCMEC FAISS index | Until replaced | GPU RAM + encrypted disk | Overwritten on sync |
| Loyalty FAISS index | Until replaced | GPU RAM + encrypted disk | Overwritten on sync |
| NCMEC alerts | 7 years | Central Hub (encrypted) | Automated purge |
| Aggregated analytics | 90 days local, 2 years central | SSD + Cloud DB | Automated purge |
| Loyalty engagement | 2 years | Central Hub | Member deletion request |
| Audit logs | 7 years | Encrypted local + central | Automated purge |

### 4.4 Audit Logging Specifications

All audit logs include:
- Event UUID
- Timestamp (UTC, millisecond precision)
- Device ID + Location ID
- Event type and category
- Actor (system/user/service)
- Result (success/failure)

**Safety Audit Events:**
- `safety.service.start` / `safety.service.stop`
- `safety.ncmec.sync` (version, count)
- `safety.ncmec.match` (alert_id, case_id, confidence)
- `safety.ncmec.alert_sent` (alert_id, destination)
- `safety.pipeline.error` / `safety.pipeline.recovery`

**Commercial Audit Events:**
- `commercial.service.start` / `commercial.service.stop`
- `commercial.loyalty.match` (member_uuid, confidence)
- `commercial.loyalty.sync` (version, count)
- `commercial.analytics.export` (bucket_count, destination)
- `commercial.age_gate.triggered` (content_id, detected_age_bucket)
- `commercial.pipeline.error` / `commercial.pipeline.recovery`

### 4.5 Legal Separation

The two camera systems are separated at every level:

| Boundary | Implementation |
|----------|---------------|
| **Physical** | Separate CSI cameras on separate ports |
| **Process** | Separate systemd services, separate PIDs |
| **Memory** | Separate GPU contexts, separate FAISS indexes |
| **Storage** | Separate log files, separate databases |
| **Network** | Separate API endpoints, separate data streams |
| **Audit** | Separate audit trails, separate retention policies |
| **Legal** | Separate consent models, separate compliance frameworks |

---

## 5. API Endpoints

### 5.1 Safety System Endpoints (Jetson -> Hub)

```
POST /api/v1/alerts
    Body: {
        "alert_id": "uuid",
        "type": "ncmec",
        "device_id": "SKZ-D-0001",
        "location_id": "loc-uuid",
        "timestamp": "2026-01-28T21:00:00Z",
        "confidence": 0.87,
        "matched_case_id": "NCMEC-12345",
        "pipeline": "safety"
    }
    Response: 201 Created

GET /api/v1/safety/status
    Response: {
        "pipeline_running": true,
        "ncmec_db_version": "2026-01-28",
        "ncmec_db_count": 85432,
        "last_sync": "2026-01-28T06:00:00Z",
        "alerts_sent_today": 0,
        "uptime_seconds": 86400
    }

GET /api/v1/databases/ncmec/version
    Response: {
        "version": "2026-01-28",
        "count": 85432,
        "checksum": "sha256:abc123..."
    }

GET /api/v1/databases/ncmec/download
    Response: Binary FAISS index file
    Headers: Content-Type: application/octet-stream
```

### 5.2 Commercial System Endpoints (Jetson -> Hub)

```
POST /api/v1/analytics/batch
    Body: {
        "device_id": "SKZ-D-0001",
        "period_start": "2026-01-28T20:00:00Z",
        "period_end": "2026-01-28T20:15:00Z",
        "metrics": {
            "people_count": 47,
            "peak_occupancy": 12,
            "avg_dwell_seconds": 34,
            "age_distribution": {
                "0-12": 0.05, "13-17": 0.08, "18-24": 0.22,
                "25-34": 0.30, "35-44": 0.18, "45-54": 0.10,
                "55-64": 0.05, "65+": 0.02
            },
            "gender_distribution": {
                "male": 0.55, "female": 0.45
            }
        }
    }
    Response: 201 Created

POST /api/v1/loyalty/engagement
    Body: {
        "device_id": "SKZ-D-0001",
        "member_uuid": "member-uuid",
        "timestamp": "2026-01-28T21:00:00Z",
        "trigger_sent": true,
        "content_id": "loyalty-welcome-gold"
    }
    Response: 201 Created

GET /api/v1/databases/loyalty/version
    Response: {
        "version": "2026-01-28",
        "count": 1234,
        "network": "high-octane"
    }

GET /api/v1/databases/loyalty/download
    Response: Binary FAISS index file

GET /api/v1/commercial/status
    Response: {
        "pipeline_running": true,
        "loyalty_db_version": "2026-01-28",
        "loyalty_db_count": 1234,
        "analytics_pending_export": 3,
        "triggers_sent_today": 156,
        "uptime_seconds": 86400
    }
```

### 5.3 CMS Integration Endpoints (Hub -> CMS)

```
POST /api/v1/alerts                    # Forward NCMEC alerts
GET  /api/v1/content/triggers          # Get trigger rules for device
POST /api/v1/analytics/ingest          # Ingest aggregated analytics
POST /api/v1/loyalty/engagement        # Forward loyalty engagements
GET  /api/v1/devices/{id}/config       # Get device configuration
POST /api/v1/devices/{id}/heartbeat    # Device health update
```

---

## 6. Configuration Files

### 6.1 DeepStream Config - Safety Pipeline

**File:** `jetson_player/config/deepstream_safety.txt`

See implementation in `jetson_player/config/deepstream_safety.txt`

Key parameters:
- Source: CSI sensor-id=0, 1920x1080 @ 30fps
- PGIE: RetinaFace, FP16, interval=2
- Tracker: IOU, max 30 tracks
- SGIE: ArcFace, FP16, output-tensor-meta=1
- Sink: Fakesink (no display)

### 6.2 DeepStream Config - Commercial Pipeline

**File:** `jetson_player/config/deepstream_commercial.txt`

Key parameters:
- Source: CSI sensor-id=1, 1920x1080 @ 30fps
- PGIE: RetinaFace, FP16, interval=2
- Tracker: IOU, max 50 tracks
- SGIE1: Age/Gender classifier, INT8
- SGIE2: ArcFace (loyalty), FP16
- Analytics: nvdsanalytics with counting zones
- Sink: Fakesink (no display)

### 6.3 Analytics Zone Config

**File:** `jetson_player/config/analytics_config.txt`

Configurable per-location:
- ROI polygons for counting zones
- Line crossing definitions for entry/exit
- Dwell time thresholds

### 6.4 Environment Variables

```bash
# Camera Configuration
SKILLZ_SAFETY_CAMERA_ID=0
SKILLZ_COMMERCIAL_CAMERA_ID=1
SKILLZ_CAMERA_WIDTH=1920
SKILLZ_CAMERA_HEIGHT=1080
SKILLZ_CAMERA_FPS=30

# Model Paths
SKILLZ_MODELS_PATH=/opt/skillz/models
SKILLZ_RETINAFACE_ENGINE=retinaface_fp16.engine
SKILLZ_ARCFACE_ENGINE=arcface_fp16.engine
SKILLZ_AGEGENDER_ENGINE=agegender_int8.engine

# Database Paths
SKILLZ_DATABASES_PATH=/opt/skillz/databases
SKILLZ_NCMEC_INDEX=ncmec.faiss
SKILLZ_LOYALTY_INDEX=loyalty.faiss

# NCMEC Configuration
SKILLZ_NCMEC_MATCH_THRESHOLD=0.6
SKILLZ_NCMEC_SYNC_INTERVAL_HOURS=6

# Commercial Configuration
SKILLZ_LOYALTY_MATCH_THRESHOLD=0.7
SKILLZ_LOYALTY_SYNC_INTERVAL_HOURS=4
SKILLZ_ANALYTICS_BUCKET_MINUTES=15
SKILLZ_ANALYTICS_EXPORT_INTERVAL_MINUTES=60
SKILLZ_ANALYTICS_RETENTION_DAYS=90
SKILLZ_AGE_GATE_BUFFER_SECONDS=5

# Network
SKILLZ_HUB_URL=http://192.168.1.100:5000
SKILLZ_ZMQ_TRIGGER_PORT=5556
SKILLZ_ZMQ_SAFETY_PORT=5557

# Logging
SKILLZ_LOG_LEVEL=INFO
SKILLZ_SAFETY_LOG=/var/log/skillz/safety.log
SKILLZ_COMMERCIAL_LOG=/var/log/skillz/commercial.log
SKILLZ_AUDIT_LOG=/var/log/skillz/audit.log
```

---

## 7. Performance Targets

| Metric | Target | Measured On |
|--------|--------|-------------|
| Face detection latency | <20ms per frame | Orin NX |
| Face encoding latency | <10ms per face | Orin NX |
| Age/gender inference | <5ms per face | Orin NX |
| FAISS search (100K vectors) | <1ms | Orin NX GPU |
| NCMEC alert end-to-end | <2 seconds | Detection to alert queued |
| Loyalty recognition | <500ms | Detection to trigger sent |
| Content trigger | <200ms | Detection to ZMQ message |
| Camera-to-frame latency | <50ms | Pipeline startup to first frame |
| GPU memory (both pipelines) | <4GB total | Orin NX 8GB |
| CPU usage (both pipelines) | <60% | 6-core ARM |
| Power consumption | <15W total | Orin NX module |

---

## 8. Failure Modes & Recovery

| Failure | Detection | Recovery | Impact |
|---------|-----------|----------|--------|
| Camera disconnected | Pipeline error | Auto-restart after 5s | Pipeline affected only |
| NCMEC DB corrupt | Checksum mismatch | Re-download from hub | Safety reduced until fixed |
| Hub unreachable | Heartbeat timeout | Queue alerts locally | Alerts delayed, not lost |
| GPU OOM | CUDA error | Restart service | Brief service interruption |
| Model file missing | Startup check | Alert admin, safe mode | Pipeline cannot start |
| FAISS index too large | Memory check | Use CPU fallback | Slower but functional |

**Safe Mode:** If safety pipeline cannot start, commercial pipeline still operates. If commercial pipeline fails, media player continues with default content.

---

## 9. Deployment Checklist

- [ ] Install JetPack 6.x with DeepStream SDK
- [ ] Connect dual IMX219 cameras to CSI ports 0 and 1
- [ ] Apply camera device tree overlay (`imx219-dual.dtbo`)
- [ ] Copy TensorRT model engines to `/opt/skillz/models/`
- [ ] Copy FAISS indexes to `/opt/skillz/databases/`
- [ ] Install Python dependencies
- [ ] Configure environment variables
- [ ] Install systemd services
- [ ] Verify camera detection (`python3 -m src.detection.test_camera`)
- [ ] Run safety pipeline test
- [ ] Run commercial pipeline test
- [ ] Verify ZeroMQ trigger delivery to player
- [ ] Verify hub connectivity and alert delivery
- [ ] Run 24-hour burn-in test
- [ ] Review audit logs for completeness

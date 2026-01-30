"""
Commercial Camera - Marketing, Loyalty, and Analytics (CSI Port 1).

Runs a dedicated DeepStream pipeline for age/gender estimation,
loyalty member recognition, people counting, and dwell time analytics.
Sends content triggers to the media player via ZeroMQ.
"""

import os
import logging
import time
import numpy as np
from typing import Optional, Dict, List
from dataclasses import dataclass, field
from datetime import datetime, timezone

from jetson_player.cameras.base_camera import BaseCamera

logger = logging.getLogger(__name__)

DEFAULT_LOYALTY_THRESHOLD = 0.7
DEFAULT_ANALYTICS_BUCKET_MINUTES = 15


@dataclass
class TrackState:
    """State for a tracked person in the commercial pipeline."""
    track_id: int
    first_seen: float
    last_seen: float
    age_bucket: Optional[str] = None
    gender: Optional[str] = None
    age_confidence: float = 0.0
    gender_confidence: float = 0.0
    loyalty_member_uuid: Optional[str] = None
    loyalty_checked: bool = False
    demographic_sent: bool = False
    zone_id: Optional[str] = None


@dataclass
class AnalyticsBucket:
    """Aggregated analytics for a time window."""
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    end_time: Optional[datetime] = None
    people_count: int = 0
    peak_occupancy: int = 0
    total_dwell_seconds: float = 0.0
    dwell_count: int = 0
    age_distribution: Dict[str, int] = field(default_factory=lambda: {
        "0-12": 0, "13-17": 0, "18-24": 0, "25-34": 0,
        "35-44": 0, "45-54": 0, "55-64": 0, "65+": 0,
    })
    gender_distribution: Dict[str, int] = field(default_factory=lambda: {
        "male": 0, "female": 0,
    })

    @property
    def avg_dwell_seconds(self) -> float:
        return self.total_dwell_seconds / self.dwell_count if self.dwell_count > 0 else 0.0

    def to_dict(self) -> dict:
        total_age = sum(self.age_distribution.values()) or 1
        total_gender = sum(self.gender_distribution.values()) or 1
        return {
            "period_start": self.start_time.isoformat(),
            "period_end": (self.end_time or datetime.now(timezone.utc)).isoformat(),
            "people_count": self.people_count,
            "peak_occupancy": self.peak_occupancy,
            "avg_dwell_seconds": round(self.avg_dwell_seconds, 1),
            "age_distribution": {
                k: round(v / total_age, 3) for k, v in self.age_distribution.items()
            },
            "gender_distribution": {
                k: round(v / total_gender, 3) for k, v in self.gender_distribution.items()
            },
        }


# Age bucket mapping from classifier output
AGE_BUCKETS = ["0-12", "13-17", "18-24", "25-34", "35-44", "45-54", "55-64", "65+"]
GENDER_CLASSES = ["male", "female"]


class CommercialCamera(BaseCamera):
    """
    Camera 2 pipeline for commercial analytics and loyalty recognition.

    Pipeline: nvarguscamerasrc -> nvinfer(RetinaFace) -> nvtracker ->
              nvinfer(AgeGender) -> nvinfer(ArcFace) -> nvdsanalytics ->
              probe(triggers + analytics) -> fakesink

    Data policy:
    - Age/gender: aggregated only, never linked to individuals
    - Loyalty: opt-in members only, member_uuid + timestamp logged
    - People counting: anonymous aggregate counts
    - No face images or embeddings are stored
    """

    def __init__(
        self,
        sensor_id: int = 1,
        loyalty_threshold: float = DEFAULT_LOYALTY_THRESHOLD,
        models_path: str = "/opt/skillz/models",
        databases_path: str = "/opt/skillz/databases",
        trigger_callback=None,
        analytics_callback=None,
        **kwargs,
    ):
        super().__init__(sensor_id=sensor_id, **kwargs)

        self.loyalty_threshold = float(
            os.environ.get("SKILLZ_LOYALTY_MATCH_THRESHOLD", loyalty_threshold)
        )
        self.models_path = os.environ.get("SKILLZ_MODELS_PATH", models_path)
        self.databases_path = os.environ.get("SKILLZ_DATABASES_PATH", databases_path)
        self._trigger_callback = trigger_callback
        self._analytics_callback = analytics_callback

        # Loyalty FAISS index
        self._loyalty_index = None
        self._loyalty_metadata = None

        # Track management
        self._active_tracks: Dict[int, TrackState] = {}

        # Analytics aggregation
        bucket_minutes = int(os.environ.get(
            "SKILLZ_ANALYTICS_BUCKET_MINUTES", DEFAULT_ANALYTICS_BUCKET_MINUTES
        ))
        self._bucket_duration = bucket_minutes * 60
        self._current_bucket = AnalyticsBucket()
        self._completed_buckets: List[dict] = []

        # Age gating state
        self._youngest_detected_age: Optional[int] = None
        self._age_gate_active = False

        # Metrics
        self.loyalty_matches = 0
        self.triggers_sent = 0

    def _get_pipeline_name(self) -> str:
        return "CommercialPipeline"

    def start(self):
        """Start commercial pipeline and load loyalty database."""
        self._load_loyalty_database()
        super().start()

    def _load_loyalty_database(self):
        """Load loyalty FAISS index into GPU memory."""
        loyalty_index_path = os.path.join(self.databases_path, "loyalty.faiss")
        loyalty_meta_path = os.path.join(self.databases_path, "loyalty_metadata.json")

        if not os.path.exists(loyalty_index_path):
            logger.info(
                "Loyalty index not found. Loyalty recognition disabled."
            )
            return

        try:
            import faiss
            import json

            cpu_index = faiss.read_index(loyalty_index_path)

            try:
                gpu_res = faiss.StandardGpuResources()
                self._loyalty_index = faiss.index_cpu_to_gpu(gpu_res, 0, cpu_index)
                logger.info(f"Loyalty index loaded to GPU: {cpu_index.ntotal} members")
            except Exception:
                self._loyalty_index = cpu_index
                logger.warning("FAISS GPU not available, using CPU index")

            if os.path.exists(loyalty_meta_path):
                with open(loyalty_meta_path, "r") as f:
                    self._loyalty_metadata = json.load(f)

        except ImportError:
            logger.error("FAISS not installed. pip install faiss-gpu")
        except Exception as e:
            logger.error(f"Failed to load loyalty database: {e}")

    def reload_database(self):
        """Hot-reload loyalty database without restarting pipeline."""
        logger.info("Hot-reloading loyalty database...")
        old_index = self._loyalty_index
        self._load_loyalty_database()
        del old_index

    def _build_pipeline(self):
        """Build the commercial DeepStream pipeline."""
        import gi
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst

        pipeline = Gst.Pipeline.new("commercial-pipeline")

        # Source: CSI camera
        source = self._create_element("nvarguscamerasrc", "commercial-source", {
            "sensor-id": self.sensor_id,
            "bufapi-version": 1,
        })

        src_caps = self._create_caps_filter(
            f"video/x-raw(memory:NVMM),width={self.width},"
            f"height={self.height},framerate={self.fps}/1",
            "commercial-src-caps",
        )

        nvvidconv = self._create_element("nvvideoconvert", "commercial-vidconv")

        format_caps = self._create_caps_filter(
            "video/x-raw(memory:NVMM),format=NV12",
            "commercial-format-caps",
        )

        streammux = self._create_element("nvstreammux", "commercial-mux", {
            "batch-size": 1,
            "width": self.width,
            "height": self.height,
            "live-source": 1,
            "batched-push-timeout": 40000,
        })

        # Primary GIE: RetinaFace
        pgie = self._create_element("nvinfer", "commercial-pgie", {
            "config-file-path": os.path.join(
                self.models_path, "retinaface_commercial_config.txt"
            ),
            "batch-size": 1,
            "interval": 2,
            "unique-id": 1,
        })

        # Tracker
        tracker = self._create_element("nvtracker", "commercial-tracker", {
            "tracker-width": 640,
            "tracker-height": 384,
            "ll-lib-file": "/opt/nvidia/deepstream/deepstream/lib/libnvds_nvmultiobjecttracker.so",
        })

        # SGIE 1: Age/Gender classifier
        sgie_agegender = self._create_element("nvinfer", "commercial-sgie-agegender", {
            "config-file-path": os.path.join(
                self.models_path, "agegender_config.txt"
            ),
            "batch-size": 16,
            "unique-id": 2,
        })

        # SGIE 2: ArcFace for loyalty
        sgie_arcface = self._create_element("nvinfer", "commercial-sgie-arcface", {
            "config-file-path": os.path.join(
                self.models_path, "arcface_loyalty_config.txt"
            ),
            "batch-size": 16,
            "unique-id": 3,
        })

        # Fakesink
        sink = self._create_element("fakesink", "commercial-sink", {
            "sync": False,
            "async": False,
        })

        for element in [source, src_caps, nvvidconv, format_caps, streammux,
                        pgie, tracker, sgie_agegender, sgie_arcface, sink]:
            pipeline.add(element)

        source.link(src_caps)
        src_caps.link(nvvidconv)
        nvvidconv.link(format_caps)

        sinkpad = streammux.get_request_pad("sink_0")
        srcpad = format_caps.get_static_pad("src")
        srcpad.link(sinkpad)

        streammux.link(pgie)
        pgie.link(tracker)
        tracker.link(sgie_agegender)
        sgie_agegender.link(sgie_arcface)
        sgie_arcface.link(sink)

        return pipeline

    def _attach_probes(self):
        """Attach probe to final element for commercial processing."""
        if self._pipeline is None:
            return

        sgie = self._pipeline.get_by_name("commercial-sgie-arcface")
        if sgie is None:
            logger.error("Could not find commercial-sgie-arcface element")
            return

        srcpad = sgie.get_static_pad("src")
        if srcpad is None:
            logger.error("Could not get src pad")
            return

        srcpad.add_probe(1, self._commercial_probe_callback, None)
        logger.info("Commercial probe attached")

    def _commercial_probe_callback(self, pad, info, user_data):
        """
        Probe callback for commercial pipeline.

        Processes age/gender classifications, loyalty matches,
        and aggregates analytics data.
        """
        import gi
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst

        self.frames_processed += 1
        current_time = time.time()

        try:
            buf = info.get_buffer()
            if buf is None:
                return Gst.PadProbeReturn.OK

            import pyds

            batch_meta = pyds.gst_buffer_get_nvds_batch_meta(hash(buf))
            if batch_meta is None:
                return Gst.PadProbeReturn.OK

            current_occupancy = 0

            l_frame = batch_meta.frame_meta_list
            while l_frame is not None:
                frame_meta = pyds.NvDsFrameMeta.cast(l_frame.data)
                frame_number = frame_meta.frame_num

                l_obj = frame_meta.obj_meta_list
                while l_obj is not None:
                    obj_meta = pyds.NvDsObjectMeta.cast(l_obj.data)
                    track_id = obj_meta.object_id
                    self.detections_count += 1
                    current_occupancy += 1

                    # Get or create track state
                    track = self._get_or_create_track(track_id, current_time)
                    track.last_seen = current_time

                    # Extract age/gender from classifier metadata
                    self._process_age_gender(obj_meta, track)

                    # Extract loyalty embedding and match
                    if not track.loyalty_checked and self._loyalty_index is not None:
                        self._process_loyalty(obj_meta, track)

                    # Send demographic trigger if not sent
                    if not track.demographic_sent and track.age_bucket:
                        self._send_demographic_trigger(track)
                        track.demographic_sent = True

                    try:
                        l_obj = l_obj.next
                    except StopIteration:
                        break

                try:
                    l_frame = l_frame.next
                except StopIteration:
                    break

            # Update analytics
            self._update_analytics(current_occupancy, current_time)

            # Clean up old tracks
            self._cleanup_tracks(current_time)

        except Exception as e:
            logger.error(f"Commercial probe error: {e}")
            self.errors_count += 1

        return Gst.PadProbeReturn.OK

    def _get_or_create_track(self, track_id: int, current_time: float) -> TrackState:
        """Get existing track or create new one."""
        if track_id not in self._active_tracks:
            self._active_tracks[track_id] = TrackState(
                track_id=track_id,
                first_seen=current_time,
                last_seen=current_time,
            )
            self._current_bucket.people_count += 1
        return self._active_tracks[track_id]

    def _process_age_gender(self, obj_meta, track: TrackState):
        """Extract age/gender classification from SGIE metadata."""
        if track.age_bucket is not None:
            return  # Already classified

        try:
            import pyds

            l_classifier = obj_meta.classifier_meta_list
            while l_classifier is not None:
                classifier_meta = pyds.NvDsClassifierMeta.cast(l_classifier.data)

                # SGIE unique-id=2 is age/gender
                if classifier_meta.unique_component_id == 2:
                    l_label = classifier_meta.label_info_list
                    label_count = 0
                    while l_label is not None:
                        label_info = pyds.NvDsLabelInfo.cast(l_label.data)
                        label_id = label_info.result_class_id

                        if label_count == 0:
                            # First output: age bucket
                            if 0 <= label_id < len(AGE_BUCKETS):
                                track.age_bucket = AGE_BUCKETS[label_id]
                                track.age_confidence = label_info.result_prob
                                self._current_bucket.age_distribution[track.age_bucket] += 1
                        elif label_count == 1:
                            # Second output: gender
                            if 0 <= label_id < len(GENDER_CLASSES):
                                track.gender = GENDER_CLASSES[label_id]
                                track.gender_confidence = label_info.result_prob
                                self._current_bucket.gender_distribution[track.gender] += 1

                        label_count += 1
                        try:
                            l_label = l_label.next
                        except StopIteration:
                            break

                try:
                    l_classifier = l_classifier.next
                except StopIteration:
                    break

        except Exception as e:
            logger.debug(f"Age/gender extraction error: {e}")

    def _process_loyalty(self, obj_meta, track: TrackState):
        """Check face against loyalty database."""
        try:
            import pyds

            # Extract embedding from tensor meta (SGIE unique-id=3)
            l_user = obj_meta.obj_user_meta_list
            while l_user is not None:
                user_meta = pyds.NvDsUserMeta.cast(l_user.data)
                if user_meta.base_meta.meta_type == pyds.NVDSINFER_TENSOR_OUTPUT_META:
                    tensor_meta = pyds.NvDsInferTensorMeta.cast(
                        user_meta.user_meta_data
                    )
                    # Check this is from loyalty SGIE (unique-id=3)
                    if tensor_meta.unique_id == 3:
                        layer = pyds.get_nvds_LayerInfo(tensor_meta, 0)
                        if layer:
                            embedding = np.array(
                                pyds.get_detections(layer.buffer, layer.dims.numElements),
                                dtype=np.float32,
                            )
                            norm = np.linalg.norm(embedding)
                            if norm > 0:
                                embedding = embedding / norm

                            self._match_loyalty(embedding, track)
                            track.loyalty_checked = True
                            # Embedding discarded here - not stored

                try:
                    l_user = l_user.next
                except StopIteration:
                    break

        except Exception as e:
            logger.debug(f"Loyalty extraction error: {e}")

    def _match_loyalty(self, embedding: np.ndarray, track: TrackState):
        """Search loyalty database for a match."""
        if self._loyalty_index is None:
            return

        try:
            import faiss

            embedding_2d = embedding.reshape(1, -1).astype(np.float32)
            distances, indices = self._loyalty_index.search(embedding_2d, 1)

            similarity = 1.0 - (distances[0][0] / 2.0)

            if similarity >= self.loyalty_threshold:
                matched_index = int(indices[0][0])
                self.loyalty_matches += 1

                member_uuid = None
                member_data = {}
                if self._loyalty_metadata and matched_index < len(self._loyalty_metadata):
                    member_data = self._loyalty_metadata[matched_index]
                    member_uuid = member_data.get("member_uuid")

                track.loyalty_member_uuid = member_uuid

                logger.info(
                    f"Loyalty match: track={track.track_id} "
                    f"member={member_uuid} confidence={similarity:.3f}"
                )

                self._send_loyalty_trigger(track, member_data, similarity)

        except Exception as e:
            logger.error(f"Loyalty match error: {e}")

    def _send_demographic_trigger(self, track: TrackState):
        """Send demographic content trigger to media player."""
        if self._trigger_callback is None:
            return

        trigger = {
            "type": "trigger",
            "source": "commercial",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "trigger_type": "demographic",
            "data": {
                "age_range": track.age_bucket,
                "gender": track.gender,
                "confidence": round(track.age_confidence, 2),
                "people_count": len(self._active_tracks),
            },
            "priority": 5,
        }

        self.triggers_sent += 1
        self._trigger_callback(trigger)

    def _send_loyalty_trigger(self, track: TrackState, member_data: dict,
                              confidence: float):
        """Send loyalty recognition trigger to media player."""
        if self._trigger_callback is None:
            return

        trigger = {
            "type": "trigger",
            "source": "commercial",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "trigger_type": "loyalty",
            "data": {
                "member_uuid": track.loyalty_member_uuid,
                "preferences": member_data.get("preferences", []),
                "tier": member_data.get("tier", "standard"),
                "confidence": round(confidence, 3),
            },
            "priority": 10,
        }

        self.triggers_sent += 1
        self._trigger_callback(trigger)

    def _update_analytics(self, current_occupancy: int, current_time: float):
        """Update analytics aggregation bucket."""
        # Update peak occupancy
        if current_occupancy > self._current_bucket.peak_occupancy:
            self._current_bucket.peak_occupancy = current_occupancy

        # Check if bucket should rotate
        elapsed = (
            current_time -
            self._current_bucket.start_time.timestamp()
        )
        if elapsed >= self._bucket_duration:
            self._rotate_bucket()

    def _rotate_bucket(self):
        """Complete current bucket and start a new one."""
        now = datetime.now(timezone.utc)
        self._current_bucket.end_time = now

        # Calculate dwell times from active tracks
        for track in self._active_tracks.values():
            dwell = track.last_seen - track.first_seen
            if dwell > 1.0:  # Minimum 1 second
                self._current_bucket.total_dwell_seconds += dwell
                self._current_bucket.dwell_count += 1

        bucket_data = self._current_bucket.to_dict()
        self._completed_buckets.append(bucket_data)

        logger.info(
            f"Analytics bucket completed: {bucket_data['people_count']} people, "
            f"peak={bucket_data['peak_occupancy']}, "
            f"avg_dwell={bucket_data['avg_dwell_seconds']}s"
        )

        if self._analytics_callback:
            self._analytics_callback(bucket_data)

        # Start new bucket
        self._current_bucket = AnalyticsBucket(start_time=now)

    def _cleanup_tracks(self, current_time: float):
        """Remove tracks not seen for >5 seconds."""
        stale_ids = [
            tid for tid, track in self._active_tracks.items()
            if (current_time - track.last_seen) > 5.0
        ]
        for tid in stale_ids:
            del self._active_tracks[tid]

    def get_pending_analytics(self) -> List[dict]:
        """Get completed analytics buckets for export."""
        buckets = list(self._completed_buckets)
        self._completed_buckets.clear()
        return buckets

    def get_youngest_detected(self) -> Optional[int]:
        """Get the youngest detected age bucket's minimum age."""
        age_bucket_mins = {
            "0-12": 0, "13-17": 13, "18-24": 18, "25-34": 25,
            "35-44": 35, "45-54": 45, "55-64": 55, "65+": 65,
        }
        youngest = None
        for track in self._active_tracks.values():
            if track.age_bucket:
                min_age = age_bucket_mins.get(track.age_bucket, 0)
                if youngest is None or min_age < youngest:
                    youngest = min_age
        return youngest

    def get_health(self) -> dict:
        """Return commercial pipeline health metrics."""
        health = super().get_health()
        health.update({
            "loyalty_db_loaded": self._loyalty_index is not None,
            "loyalty_db_size": (
                self._loyalty_index.ntotal if self._loyalty_index else 0
            ),
            "loyalty_threshold": self.loyalty_threshold,
            "loyalty_matches": self.loyalty_matches,
            "triggers_sent": self.triggers_sent,
            "active_tracks": len(self._active_tracks),
            "pending_analytics_buckets": len(self._completed_buckets),
        })
        return health

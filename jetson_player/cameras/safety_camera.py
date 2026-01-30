"""
Safety Camera - NCMEC Missing Children Detection (CSI Port 0).

Runs a dedicated DeepStream pipeline for face detection and encoding,
matching against the NCMEC FAISS database. No face data is stored.
Only alert metadata is emitted on match.
"""

import os
import logging
import time
import numpy as np
from typing import Optional

from jetson_player.cameras.base_camera import BaseCamera

logger = logging.getLogger(__name__)

# Default configuration
DEFAULT_NCMEC_THRESHOLD = 0.6
DEFAULT_MIN_FACE_SIZE = 64
DEFAULT_PROCESS_INTERVAL = 2  # Every 3rd frame


class SafetyCamera(BaseCamera):
    """
    Camera 1 pipeline for NCMEC missing children detection.

    Pipeline: nvarguscamerasrc -> nvinfer(RetinaFace) -> nvtracker ->
              nvinfer(ArcFace) -> probe(FAISS match) -> fakesink

    Data policy: No frames, embeddings, or face images are stored.
    Only match alert metadata is emitted.
    """

    def __init__(
        self,
        sensor_id: int = 0,
        ncmec_threshold: float = DEFAULT_NCMEC_THRESHOLD,
        models_path: str = "/opt/skillz/models",
        databases_path: str = "/opt/skillz/databases",
        alert_callback=None,
        **kwargs,
    ):
        super().__init__(sensor_id=sensor_id, **kwargs)

        self.ncmec_threshold = float(
            os.environ.get("SKILLZ_NCMEC_MATCH_THRESHOLD", ncmec_threshold)
        )
        self.models_path = os.environ.get("SKILLZ_MODELS_PATH", models_path)
        self.databases_path = os.environ.get("SKILLZ_DATABASES_PATH", databases_path)
        self._alert_callback = alert_callback

        # FAISS index (loaded on start)
        self._ncmec_index = None
        self._ncmec_metadata = None

        # Track management (avoid re-processing same face)
        self._processed_tracks = {}  # track_id -> last_checked_frame
        self._track_check_interval = 30  # Re-check every 30 frames (~3 seconds)

        # Metrics
        self.matches_count = 0
        self.alerts_sent = 0

    def _get_pipeline_name(self) -> str:
        return "SafetyPipeline"

    def start(self):
        """Start safety pipeline and load NCMEC database."""
        self._load_ncmec_database()
        super().start()

    def _load_ncmec_database(self):
        """Load NCMEC FAISS index into GPU memory."""
        ncmec_index_path = os.path.join(self.databases_path, "ncmec.faiss")
        ncmec_meta_path = os.path.join(self.databases_path, "ncmec_metadata.json")

        if not os.path.exists(ncmec_index_path):
            logger.warning(
                f"NCMEC index not found at {ncmec_index_path}. "
                "Safety pipeline will run without matching."
            )
            return

        try:
            import faiss
            import json

            # Load index
            cpu_index = faiss.read_index(ncmec_index_path)

            # Move to GPU
            try:
                gpu_res = faiss.StandardGpuResources()
                self._ncmec_index = faiss.index_cpu_to_gpu(gpu_res, 0, cpu_index)
                logger.info(
                    f"NCMEC index loaded to GPU: {cpu_index.ntotal} vectors"
                )
            except Exception:
                # Fallback to CPU
                self._ncmec_index = cpu_index
                logger.warning("FAISS GPU not available, using CPU index")

            # Load metadata
            if os.path.exists(ncmec_meta_path):
                with open(ncmec_meta_path, "r") as f:
                    self._ncmec_metadata = json.load(f)

        except ImportError:
            logger.error("FAISS not installed. pip install faiss-gpu")
        except Exception as e:
            logger.error(f"Failed to load NCMEC database: {e}")

    def reload_database(self):
        """Hot-reload NCMEC database without restarting pipeline."""
        logger.info("Hot-reloading NCMEC database...")
        old_index = self._ncmec_index
        self._load_ncmec_database()
        # Old index will be garbage collected
        del old_index

    def _build_pipeline(self):
        """Build the safety DeepStream pipeline."""
        import gi
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst

        pipeline = Gst.Pipeline.new("safety-pipeline")

        # Source: CSI camera
        source = self._create_element("nvarguscamerasrc", "safety-source", {
            "sensor-id": self.sensor_id,
            "bufapi-version": 1,
        })

        # Caps filter for source
        src_caps = self._create_caps_filter(
            f"video/x-raw(memory:NVMM),width={self.width},"
            f"height={self.height},framerate={self.fps}/1",
            "safety-src-caps",
        )

        # Video converter
        nvvidconv = self._create_element("nvvideoconvert", "safety-vidconv")

        # Format caps
        format_caps = self._create_caps_filter(
            "video/x-raw(memory:NVMM),format=NV12",
            "safety-format-caps",
        )

        # Stream muxer
        streammux = self._create_element("nvstreammux", "safety-mux", {
            "batch-size": 1,
            "width": self.width,
            "height": self.height,
            "live-source": 1,
            "batched-push-timeout": 40000,
        })

        # Primary GIE: RetinaFace face detector
        pgie = self._create_element("nvinfer", "safety-pgie", {
            "config-file-path": os.path.join(
                self.models_path, "retinaface_safety_config.txt"
            ),
            "batch-size": 1,
            "interval": DEFAULT_PROCESS_INTERVAL,
            "unique-id": 1,
        })

        # Tracker
        tracker = self._create_element("nvtracker", "safety-tracker", {
            "tracker-width": 640,
            "tracker-height": 384,
            "ll-lib-file": "/opt/nvidia/deepstream/deepstream/lib/libnvds_nvmultiobjecttracker.so",
        })

        # Secondary GIE: ArcFace encoder
        sgie = self._create_element("nvinfer", "safety-sgie-arcface", {
            "config-file-path": os.path.join(
                self.models_path, "arcface_safety_config.txt"
            ),
            "batch-size": 16,
            "unique-id": 2,
        })

        # Fakesink (no display)
        sink = self._create_element("fakesink", "safety-sink", {
            "sync": False,
            "async": False,
        })

        # Add elements to pipeline
        for element in [source, src_caps, nvvidconv, format_caps, streammux,
                        pgie, tracker, sgie, sink]:
            pipeline.add(element)

        # Link source chain
        source.link(src_caps)
        src_caps.link(nvvidconv)
        nvvidconv.link(format_caps)

        # Link format_caps to streammux sink pad
        sinkpad = streammux.get_request_pad("sink_0")
        srcpad = format_caps.get_static_pad("src")
        srcpad.link(sinkpad)

        # Link processing chain
        streammux.link(pgie)
        pgie.link(tracker)
        tracker.link(sgie)
        sgie.link(sink)

        return pipeline

    def _attach_probes(self):
        """Attach probe to ArcFace output for NCMEC matching."""
        if self._pipeline is None:
            return

        # Get the src pad of the SGIE (ArcFace)
        sgie = self._pipeline.get_by_name("safety-sgie-arcface")
        if sgie is None:
            logger.error("Could not find safety-sgie-arcface element")
            return

        srcpad = sgie.get_static_pad("src")
        if srcpad is None:
            logger.error("Could not get src pad from safety-sgie-arcface")
            return

        srcpad.add_probe(
            1,  # GST_PAD_PROBE_TYPE_BUFFER
            self._safety_probe_callback,
            None,
        )
        logger.info("Safety probe attached to ArcFace output")

    def _safety_probe_callback(self, pad, info, user_data):
        """
        Probe callback for safety pipeline.

        Extracts face embeddings from ArcFace output tensor metadata
        and matches against NCMEC FAISS index.
        """
        import gi
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst

        self.frames_processed += 1

        try:
            # Get buffer
            buf = info.get_buffer()
            if buf is None:
                return Gst.PadProbeReturn.OK

            # Import DeepStream metadata utilities
            import pyds

            batch_meta = pyds.gst_buffer_get_nvds_batch_meta(hash(buf))
            if batch_meta is None:
                return Gst.PadProbeReturn.OK

            l_frame = batch_meta.frame_meta_list
            while l_frame is not None:
                frame_meta = pyds.NvDsFrameMeta.cast(l_frame.data)
                frame_number = frame_meta.frame_num

                l_obj = frame_meta.obj_meta_list
                while l_obj is not None:
                    obj_meta = pyds.NvDsObjectMeta.cast(l_obj.data)
                    track_id = obj_meta.object_id
                    self.detections_count += 1

                    # Skip if recently checked
                    if self._should_skip_track(track_id, frame_number):
                        try:
                            l_obj = l_obj.next
                        except StopIteration:
                            break
                        continue

                    # Extract embedding from tensor metadata
                    embedding = self._extract_embedding(obj_meta)
                    if embedding is not None:
                        self._match_ncmec(embedding, track_id, frame_number)
                        # Embedding is NOT stored - used and discarded

                    self._processed_tracks[track_id] = frame_number

                    try:
                        l_obj = l_obj.next
                    except StopIteration:
                        break

                try:
                    l_frame = l_frame.next
                except StopIteration:
                    break

        except Exception as e:
            logger.error(f"Safety probe error: {e}")
            self.errors_count += 1

        return Gst.PadProbeReturn.OK

    def _should_skip_track(self, track_id: int, frame_number: int) -> bool:
        """Check if this track was recently processed."""
        last_frame = self._processed_tracks.get(track_id)
        if last_frame is None:
            return False
        return (frame_number - last_frame) < self._track_check_interval

    def _extract_embedding(self, obj_meta) -> Optional[np.ndarray]:
        """Extract face embedding from DeepStream tensor output metadata."""
        try:
            import pyds

            l_user = obj_meta.obj_user_meta_list
            while l_user is not None:
                user_meta = pyds.NvDsUserMeta.cast(l_user.data)
                if user_meta.base_meta.meta_type == pyds.NVDSINFER_TENSOR_OUTPUT_META:
                    tensor_meta = pyds.NvDsInferTensorMeta.cast(
                        user_meta.user_meta_data
                    )
                    # First output layer is the embedding
                    layer = pyds.get_nvds_LayerInfo(tensor_meta, 0)
                    if layer:
                        embedding = np.array(
                            pyds.get_detections(layer.buffer, layer.dims.numElements),
                            dtype=np.float32,
                        )
                        # L2 normalize
                        norm = np.linalg.norm(embedding)
                        if norm > 0:
                            embedding = embedding / norm
                        return embedding

                try:
                    l_user = l_user.next
                except StopIteration:
                    break

        except Exception as e:
            logger.debug(f"Embedding extraction error: {e}")

        return None

    def _match_ncmec(self, embedding: np.ndarray, track_id: int, frame_number: int):
        """Search NCMEC database for a match."""
        if self._ncmec_index is None:
            return

        try:
            import faiss

            # Search FAISS index
            embedding_2d = embedding.reshape(1, -1).astype(np.float32)
            distances, indices = self._ncmec_index.search(embedding_2d, 1)

            # Convert L2 distance to cosine similarity
            # For normalized vectors: cosine_sim = 1 - (L2^2 / 2)
            similarity = 1.0 - (distances[0][0] / 2.0)

            if similarity >= self.ncmec_threshold:
                matched_index = int(indices[0][0])
                self.matches_count += 1

                # Get case ID from metadata
                case_id = None
                if self._ncmec_metadata and matched_index < len(self._ncmec_metadata):
                    case_id = self._ncmec_metadata[matched_index].get("case_id")

                logger.warning(
                    f"NCMEC MATCH: track={track_id} confidence={similarity:.3f} "
                    f"case_id={case_id}"
                )

                # Emit alert (NO image or embedding included)
                self._emit_alert(
                    case_id=case_id,
                    confidence=float(similarity),
                    track_id=track_id,
                    frame_number=frame_number,
                )

        except Exception as e:
            logger.error(f"NCMEC match error: {e}")

    def _emit_alert(self, case_id: str, confidence: float,
                    track_id: int, frame_number: int):
        """Emit an NCMEC alert. No image or embedding data is included."""
        import uuid
        from datetime import datetime, timezone

        alert = {
            "alert_id": str(uuid.uuid4()),
            "type": "ncmec",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "confidence": round(confidence, 4),
            "matched_case_id": case_id,
            "track_id": track_id,
            "frame_number": frame_number,
            "pipeline": "safety",
            "sensor_id": self.sensor_id,
            # NO image, NO embedding, NO face data
        }

        self.alerts_sent += 1
        logger.info(f"NCMEC Alert emitted: {alert['alert_id']}")

        if self._alert_callback:
            self._alert_callback(alert)

    def get_health(self) -> dict:
        """Return safety pipeline health metrics."""
        health = super().get_health()
        health.update({
            "ncmec_db_loaded": self._ncmec_index is not None,
            "ncmec_db_size": (
                self._ncmec_index.ntotal if self._ncmec_index else 0
            ),
            "ncmec_threshold": self.ncmec_threshold,
            "matches_count": self.matches_count,
            "alerts_sent": self.alerts_sent,
            "active_tracks": len(self._processed_tracks),
        })
        return health

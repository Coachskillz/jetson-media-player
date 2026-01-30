"""
CSI Camera Discovery for Jetson Orin Nano.

Detects available CSI cameras connected to the Jetson's MIPI CSI-2 ports,
tests each one, and reports capabilities. Supports both CSI and USB cameras.

Usage:
    from src.detection.camera_discovery import CameraDiscovery
    discovery = CameraDiscovery()
    cameras = discovery.discover()
"""

import subprocess
import re
import os
import logging
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class CameraInfo:
    """Information about a detected camera."""
    sensor_id: int
    device_path: str = ""
    camera_type: str = ""       # "csi" or "usb"
    driver: str = ""            # e.g. "tegra-video", "uvcvideo"
    name: str = ""              # Human-readable name
    resolutions: List[str] = field(default_factory=list)
    working: bool = False
    error: Optional[str] = None

    def __str__(self):
        status = "OK" if self.working else f"FAIL ({self.error})"
        return (
            f"Camera sensor_id={self.sensor_id} [{self.camera_type.upper()}] "
            f"device={self.device_path} driver={self.driver} "
            f"name='{self.name}' status={status}"
        )


class CameraDiscovery:
    """Discovers and tests CSI and USB cameras on Jetson platforms."""

    # Jetson Orin Nano has 2 CSI ports (sensor-id 0 and 1)
    MAX_CSI_SENSORS = 2

    # Known CSI camera drivers
    CSI_DRIVERS = ["tegra-video", "nvcsi"]

    def __init__(self):
        self._is_jetson = self._detect_jetson()

    def discover(self) -> List[CameraInfo]:
        """
        Discover all available cameras.

        Returns:
            List of CameraInfo objects for each detected camera.
        """
        cameras = []

        # Step 1: Enumerate /dev/video* devices
        v4l2_devices = self._list_v4l2_devices()
        logger.info(f"Found {len(v4l2_devices)} video device entries")

        # Step 2: Parse device info to identify CSI vs USB
        device_map = self._parse_device_info()

        # Step 3: Test CSI cameras via nvarguscamerasrc
        if self._is_jetson:
            for sensor_id in range(self.MAX_CSI_SENSORS):
                camera = self._test_csi_camera(sensor_id, device_map)
                cameras.append(camera)
        else:
            logger.warning("Not a Jetson platform - skipping CSI camera test")

        # Step 4: Detect USB cameras
        usb_cameras = self._find_usb_cameras(device_map)
        cameras.extend(usb_cameras)

        return cameras

    def discover_csi_only(self) -> List[CameraInfo]:
        """Discover only CSI cameras (skip USB)."""
        cameras = []
        if not self._is_jetson:
            logger.warning("Not a Jetson platform - no CSI cameras available")
            return cameras

        device_map = self._parse_device_info()
        for sensor_id in range(self.MAX_CSI_SENSORS):
            camera = self._test_csi_camera(sensor_id, device_map)
            if camera.working:
                cameras.append(camera)
        return cameras

    def get_working_csi_cameras(self) -> List[int]:
        """Return list of working CSI sensor IDs."""
        cameras = self.discover_csi_only()
        return [c.sensor_id for c in cameras if c.working]

    def _detect_jetson(self) -> bool:
        """Check if running on a Jetson platform."""
        # Method 1: Check Tegra release file
        if os.path.exists("/etc/nv_tegra_release"):
            return True

        # Method 2: Check for NVIDIA Jetson in device tree
        try:
            result = subprocess.run(
                ["cat", "/proc/device-tree/model"],
                capture_output=True, text=True, timeout=5
            )
            if "jetson" in result.stdout.lower() or "orin" in result.stdout.lower():
                return True
        except (subprocess.SubprocessError, FileNotFoundError):
            pass

        # Method 3: Check for nvarguscamerasrc availability
        try:
            result = subprocess.run(
                ["gst-inspect-1.0", "nvarguscamerasrc"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                return True
        except (subprocess.SubprocessError, FileNotFoundError):
            pass

        return False

    def _list_v4l2_devices(self) -> List[str]:
        """List all /dev/video* devices."""
        devices = []
        for entry in sorted(os.listdir("/dev") if os.path.exists("/dev") else []):
            if entry.startswith("video"):
                devices.append(f"/dev/{entry}")
        return devices

    def _parse_device_info(self) -> dict:
        """
        Parse v4l2-ctl --list-devices output.

        Returns:
            Dict mapping device name/driver to list of device paths.
            Example: {"NVIDIA Tegra Video (platform:tegra-camrtc-ca)": ["/dev/video0", "/dev/video1"]}
        """
        device_map = {}
        try:
            result = subprocess.run(
                ["v4l2-ctl", "--list-devices"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0:
                logger.warning(f"v4l2-ctl failed: {result.stderr}")
                return device_map

            current_name = None
            for line in result.stdout.splitlines():
                line = line.rstrip()
                if not line:
                    continue
                if not line.startswith("\t") and not line.startswith(" "):
                    # Device name line
                    current_name = line.rstrip(":")
                    device_map[current_name] = []
                elif current_name:
                    # Device path line
                    device_path = line.strip()
                    if device_path.startswith("/dev/"):
                        device_map[current_name].append(device_path)

        except FileNotFoundError:
            logger.warning("v4l2-ctl not found - install v4l-utils")
        except subprocess.SubprocessError as e:
            logger.warning(f"v4l2-ctl error: {e}")

        return device_map

    def _test_csi_camera(self, sensor_id: int, device_map: dict) -> CameraInfo:
        """
        Test a CSI camera by sensor ID using nvarguscamerasrc.

        Creates a brief GStreamer pipeline to verify the camera responds.
        """
        camera = CameraInfo(
            sensor_id=sensor_id,
            camera_type="csi",
        )

        # Try to find matching device in v4l2 listing
        for name, paths in device_map.items():
            if any(d in name.lower() for d in ["tegra", "nvcsi", "csi"]):
                camera.driver = "tegra-video"
                camera.name = name
                if sensor_id < len(paths):
                    camera.device_path = paths[sensor_id]
                break

        # Test with GStreamer pipeline
        # Run a short pipeline that captures 1 frame and exits
        pipeline_str = (
            f"gst-launch-1.0 -e "
            f"nvarguscamerasrc sensor-id={sensor_id} num-buffers=5 ! "
            f"'video/x-raw(memory:NVMM),width=1280,height=720,framerate=30/1' ! "
            f"nvvidconv ! "
            f"video/x-raw,format=I420 ! "
            f"fakesink"
        )

        try:
            logger.info(f"Testing CSI camera sensor-id={sensor_id}...")
            result = subprocess.run(
                pipeline_str,
                shell=True,
                capture_output=True,
                text=True,
                timeout=15,
            )

            if result.returncode == 0:
                camera.working = True
                camera.resolutions = self._query_csi_resolutions(sensor_id)
                logger.info(f"CSI camera sensor-id={sensor_id}: OK")
            else:
                camera.working = False
                # Parse common errors
                stderr = result.stderr
                if "could not open camera" in stderr.lower():
                    camera.error = "No camera connected to this CSI port"
                elif "argus" in stderr.lower() and "error" in stderr.lower():
                    camera.error = "Argus daemon error - camera may be in use"
                else:
                    camera.error = stderr.strip()[-200:] if stderr else "Unknown error"
                logger.warning(f"CSI camera sensor-id={sensor_id}: {camera.error}")

        except subprocess.TimeoutExpired:
            camera.working = False
            camera.error = "Timeout - camera not responding"
            logger.warning(f"CSI camera sensor-id={sensor_id}: timeout")
        except Exception as e:
            camera.working = False
            camera.error = str(e)
            logger.error(f"CSI camera sensor-id={sensor_id}: {e}")

        return camera

    def _query_csi_resolutions(self, sensor_id: int) -> List[str]:
        """Query supported resolutions for a CSI camera."""
        resolutions = []
        try:
            # Use v4l2-ctl to list supported formats
            device = f"/dev/video{sensor_id}"
            if not os.path.exists(device):
                return ["1280x720", "1920x1080"]  # Default for IMX219/IMX477

            result = subprocess.run(
                ["v4l2-ctl", "-d", device, "--list-formats-ext"],
                capture_output=True, text=True, timeout=10,
            )

            for line in result.stdout.splitlines():
                match = re.search(r"(\d{3,4})x(\d{3,4})", line)
                if match:
                    res = f"{match.group(1)}x{match.group(2)}"
                    if res not in resolutions:
                        resolutions.append(res)

        except (subprocess.SubprocessError, FileNotFoundError):
            pass

        if not resolutions:
            resolutions = ["1280x720", "1920x1080"]  # Default

        return resolutions

    def _find_usb_cameras(self, device_map: dict) -> List[CameraInfo]:
        """Find USB cameras from v4l2 device list."""
        usb_cameras = []
        sensor_id = 100  # USB cameras start at sensor_id 100 to avoid CSI collision

        for name, paths in device_map.items():
            # Skip CSI/Tegra cameras
            if any(d in name.lower() for d in ["tegra", "nvcsi", "csi"]):
                continue

            for path in paths:
                # Only include actual video capture devices (even-numbered usually)
                camera = CameraInfo(
                    sensor_id=sensor_id,
                    device_path=path,
                    camera_type="usb",
                    driver="uvcvideo",
                    name=name,
                )

                # Quick test with v4l2
                try:
                    result = subprocess.run(
                        ["v4l2-ctl", "-d", path, "--all"],
                        capture_output=True, text=True, timeout=5,
                    )
                    if "video capture" in result.stdout.lower():
                        camera.working = True
                        # Extract resolutions
                        for line in result.stdout.splitlines():
                            match = re.search(r"(\d{3,4})x(\d{3,4})", line)
                            if match:
                                res = f"{match.group(1)}x{match.group(2)}"
                                if res not in camera.resolutions:
                                    camera.resolutions.append(res)
                    else:
                        camera.working = False
                        camera.error = "Not a video capture device"
                except Exception as e:
                    camera.working = False
                    camera.error = str(e)

                if camera.working:
                    usb_cameras.append(camera)
                    sensor_id += 1

        return usb_cameras

    def print_report(self, cameras: List[CameraInfo] = None):
        """Print a formatted camera discovery report."""
        if cameras is None:
            cameras = self.discover()

        print("=" * 70)
        print("  Skillz Media - Camera Discovery Report")
        print("  Platform: Jetson" if self._is_jetson else "  Platform: Non-Jetson")
        print("=" * 70)

        csi_cameras = [c for c in cameras if c.camera_type == "csi"]
        usb_cameras = [c for c in cameras if c.camera_type == "usb"]

        # CSI Cameras
        print(f"\nCSI Cameras ({len(csi_cameras)} ports scanned):")
        print("-" * 50)
        for cam in csi_cameras:
            status = "CONNECTED" if cam.working else "NOT FOUND"
            print(f"  Port {cam.sensor_id}: {status}")
            if cam.working:
                print(f"    Device: {cam.device_path}")
                print(f"    Driver: {cam.driver}")
                print(f"    Resolutions: {', '.join(cam.resolutions)}")
            elif cam.error:
                print(f"    Reason: {cam.error}")

        # USB Cameras
        if usb_cameras:
            print(f"\nUSB Cameras ({len(usb_cameras)} found):")
            print("-" * 50)
            for cam in usb_cameras:
                print(f"  {cam.device_path}: {cam.name}")
                if cam.resolutions:
                    print(f"    Resolutions: {', '.join(cam.resolutions)}")

        # Summary
        working = [c for c in cameras if c.working]
        print(f"\nSummary: {len(working)} working camera(s) detected")
        print("=" * 70)

        return cameras

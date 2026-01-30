#!/usr/bin/env python3
"""
Standalone CSI Camera Test for Jetson Orin Nano.

Discovers all cameras, tests them, and optionally captures a snapshot.

Usage:
    python3 -m src.detection.test_camera                  # Discover all cameras
    python3 -m src.detection.test_camera --snapshot       # Capture test snapshots
    python3 -m src.detection.test_camera --sensor-id 0    # Test specific CSI port
"""

import argparse
import subprocess
import sys
import os
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def capture_snapshot(sensor_id: int, output_path: str) -> bool:
    """
    Capture a single JPEG snapshot from a CSI camera.

    Args:
        sensor_id: CSI sensor ID (0 or 1)
        output_path: Path to save the JPEG file

    Returns:
        True if snapshot captured successfully
    """
    pipeline_str = (
        f"gst-launch-1.0 -e "
        f"nvarguscamerasrc sensor-id={sensor_id} num-buffers=10 ! "
        f"'video/x-raw(memory:NVMM),width=1280,height=720,framerate=30/1' ! "
        f"nvvidconv ! "
        f"video/x-raw,format=I420 ! "
        f"videoconvert ! "
        f"jpegenc quality=90 ! "
        f"multifilesink location={output_path} max-files=1"
    )

    try:
        logger.info(f"Capturing snapshot from CSI sensor-id={sensor_id}...")
        result = subprocess.run(
            pipeline_str,
            shell=True,
            capture_output=True,
            text=True,
            timeout=15,
        )

        if result.returncode == 0 and os.path.exists(output_path):
            file_size = os.path.getsize(output_path)
            logger.info(f"Snapshot saved: {output_path} ({file_size} bytes)")
            return True
        else:
            logger.error(f"Snapshot failed: {result.stderr}")
            return False

    except subprocess.TimeoutExpired:
        logger.error("Snapshot capture timed out")
        return False
    except Exception as e:
        logger.error(f"Snapshot error: {e}")
        return False


def check_system_info():
    """Print system information relevant to camera operation."""
    print("\n--- System Info ---")

    # Jetson model
    try:
        result = subprocess.run(
            ["cat", "/proc/device-tree/model"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            print(f"Device: {result.stdout.strip()}")
    except (subprocess.SubprocessError, FileNotFoundError):
        print("Device: Unknown (not Jetson?)")

    # JetPack / L4T version
    if os.path.exists("/etc/nv_tegra_release"):
        try:
            result = subprocess.run(
                ["cat", "/etc/nv_tegra_release"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                print(f"L4T: {result.stdout.strip()[:80]}")
        except subprocess.SubprocessError:
            pass

    # GStreamer version
    try:
        result = subprocess.run(
            ["gst-launch-1.0", "--version"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            version_line = result.stdout.strip().split("\n")[0]
            print(f"GStreamer: {version_line}")
    except (subprocess.SubprocessError, FileNotFoundError):
        print("GStreamer: NOT FOUND")

    # nvarguscamerasrc available
    try:
        result = subprocess.run(
            ["gst-inspect-1.0", "nvarguscamerasrc"],
            capture_output=True, text=True, timeout=5,
        )
        available = result.returncode == 0
        print(f"nvarguscamerasrc: {'Available' if available else 'NOT AVAILABLE'}")
    except (subprocess.SubprocessError, FileNotFoundError):
        print("nvarguscamerasrc: Cannot check")

    # Argus daemon
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "nvargus-daemon"],
            capture_output=True, text=True, timeout=5,
        )
        status = result.stdout.strip()
        print(f"nvargus-daemon: {status}")
    except (subprocess.SubprocessError, FileNotFoundError):
        print("nvargus-daemon: Cannot check")

    # /dev/video devices
    video_devs = sorted([
        f"/dev/{e}" for e in os.listdir("/dev")
        if e.startswith("video")
    ]) if os.path.exists("/dev") else []
    print(f"Video devices: {', '.join(video_devs) if video_devs else 'None'}")

    print()


def main():
    parser = argparse.ArgumentParser(
        description="Skillz Media - CSI Camera Discovery & Test"
    )
    parser.add_argument(
        "--snapshot", action="store_true",
        help="Capture a test snapshot from each working camera"
    )
    parser.add_argument(
        "--sensor-id", type=int, default=None,
        help="Test a specific CSI sensor ID (0 or 1)"
    )
    parser.add_argument(
        "--output-dir", type=str, default="/tmp",
        help="Directory to save snapshots (default: /tmp)"
    )
    parser.add_argument(
        "--system-info", action="store_true", default=True,
        help="Show system information (default: true)"
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  Skillz Media - Camera Discovery & Test")
    print("=" * 60)

    # Show system info
    if args.system_info:
        check_system_info()

    # Import discovery (handle case where it's run on non-Jetson)
    from src.detection.camera_discovery import CameraDiscovery

    discovery = CameraDiscovery()

    if args.sensor_id is not None:
        # Test specific sensor
        print(f"Testing CSI sensor-id={args.sensor_id}...")
        device_map = discovery._parse_device_info()
        camera = discovery._test_csi_camera(args.sensor_id, device_map)
        print(f"\nResult: {camera}")

        if camera.working and args.snapshot:
            output = os.path.join(args.output_dir, f"csi_test_sensor{args.sensor_id}.jpg")
            capture_snapshot(args.sensor_id, output)
    else:
        # Full discovery
        cameras = discovery.print_report()

        # Capture snapshots if requested
        if args.snapshot:
            working_csi = [c for c in cameras if c.working and c.camera_type == "csi"]
            if working_csi:
                print("\nCapturing test snapshots...")
                os.makedirs(args.output_dir, exist_ok=True)
                for cam in working_csi:
                    output = os.path.join(
                        args.output_dir,
                        f"csi_test_sensor{cam.sensor_id}.jpg"
                    )
                    success = capture_snapshot(cam.sensor_id, output)
                    if success:
                        print(f"  Sensor {cam.sensor_id}: Saved to {output}")
                    else:
                        print(f"  Sensor {cam.sensor_id}: FAILED")
            else:
                print("\nNo working CSI cameras to capture snapshots from.")

    return 0


if __name__ == "__main__":
    sys.exit(main())

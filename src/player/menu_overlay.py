"""
Menu overlay module for Jetson Media Player.
Re-exports MenuOverlay component for easy access at the player level.

The MenuOverlay displays a semi-transparent menu with device info and actions.
Features:
- Device Information (ID, screen ID, connection mode, status)
- Network Info (IP address, network status, CMS URL)
- Settings (camera toggle)
- Action buttons: Manual Refresh, Re-pair Device, Exit Player

Touch and Keyboard Support:
- Keyboard: Escape or F1 to toggle menu
- Touch: Corner tap detection (100x100px zones in all 4 corners)

Usage:
    from src.player.menu_overlay import MenuOverlay

    overlay = MenuOverlay(
        on_close=lambda: print("Menu closed"),
        on_re_pair=lambda: print("Re-pair requested"),
        on_refresh=lambda: print("Manual refresh"),
        on_exit=lambda: print("Exit requested"),
        on_camera_toggle=lambda enabled: print(f"Camera: {enabled}")
    )

    # Update device info
    overlay.update_device_info(
        device_id="device-001",
        screen_id="screen-123",
        connection_mode="hub",
        status="active",
        current_content="promo-video.mp4",
        ip_address="192.168.1.100",
        network_status="Connected",
        cms_url="http://cms.example.com:5002"
    )

    # Or update network info separately
    overlay.update_network_info(
        ip_address="192.168.1.100",
        network_status="Connected",
        cms_url="http://cms.example.com:5002"
    )
"""

# Re-export MenuOverlay from the UI module
from src.player.ui.menu_overlay import MenuOverlay

__all__ = ['MenuOverlay']

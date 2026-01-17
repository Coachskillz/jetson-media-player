"""
Pairing screen module for Jetson Media Player.
Re-exports PairingScreen component for easy access at the player level.

The PairingScreen displays a large 6-digit pairing code for CMS device registration.
Features:
- Large, centered pairing code (readable from 3+ meters)
- CMS URL display for user reference
- Network status indicator with spinner
- Success/error state display

Usage:
    from src.player.pairing_screen import PairingScreen

    screen = PairingScreen(
        pairing_code="123456",
        cms_url="http://cms.example.com:5002",
        device_id="device-001"
    )
    screen.set_pairing_code("654321")  # Update code
    screen.set_status("Connecting...")  # Update status
    screen.show_success()  # Show paired state
"""

# Re-export PairingScreen from the UI module
from src.player.ui.pairing_screen import PairingScreen

__all__ = ['PairingScreen']

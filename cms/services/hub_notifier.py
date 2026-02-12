"""
Hub Notification Service.

Notifies registered Hubs when playlist changes occur so they can
immediately sync the updated playlist instead of waiting for the
polling interval.
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, List

import requests

logger = logging.getLogger(__name__)

# Thread pool for async notifications
_executor = ThreadPoolExecutor(max_workers=5)


def notify_playlist_updated(
    device_id: Optional[str] = None,
    playlist_id: Optional[int] = None,
    action: str = 'updated'
) -> None:
    """
    Notify relevant Hubs that a playlist has been updated.

    If device_id is provided, only notifies the Hub for that device.
    Otherwise notifies all active Hubs.

    This triggers immediate sync on the Hub instead of waiting for
    the polling interval (typically 5 minutes).

    Args:
        device_id: Optional device hardware_id to sync specific device
        playlist_id: Optional playlist ID that was changed
        action: Action type ('updated', 'deleted', 'assigned')
    """
    from cms.models import Hub, Device

    hubs_to_notify = []

    # If device_id provided, find the specific Hub for that device
    if device_id:
        device = Device.query.filter_by(hardware_id=device_id).first()
        if not device:
            device = Device.query.filter_by(device_id=device_id).first()

        if device and device.hub_id:
            from cms.models import db
            hub = db.session.get(Hub, device.hub_id)
            if hub and hub.status == 'active':
                hubs_to_notify.append(hub)
        elif device:
            logger.debug(f"Device {device_id} is in direct mode, no Hub to notify")
            return
    else:
        # Notify all active hubs
        hubs_to_notify = Hub.query.filter(Hub.status == 'active').all()

    if not hubs_to_notify:
        logger.debug("No active hubs to notify")
        return

    # Send notifications asynchronously to avoid blocking the request
    for hub in hubs_to_notify:
        webhook_url = _get_hub_webhook_url(hub)
        if webhook_url:
            _executor.submit(
                _send_notification,
                webhook_url,
                device_id,
                playlist_id,
                action,
                hub.code
            )
        else:
            logger.warning(f"No webhook URL available for Hub {hub.code}")


def notify_specific_hubs(
    hub_urls: List[str],
    device_id: Optional[str] = None,
    playlist_id: Optional[int] = None,
    action: str = 'updated'
) -> None:
    """
    Notify specific Hub URLs about a playlist change.

    Args:
        hub_urls: List of webhook URLs to notify
        device_id: Optional device hardware_id
        playlist_id: Optional playlist ID
        action: Action type
    """
    for url in hub_urls:
        _executor.submit(
            _send_notification,
            url,
            device_id,
            playlist_id,
            action,
            'direct'
        )


def _get_hub_webhook_url(hub) -> Optional[str]:
    """
    Get the webhook URL for a Hub.

    Tries in order:
    1. Explicit webhook_url field
    2. Construct from ip_address
    3. Construct from last_ip (from heartbeat)

    Args:
        hub: Hub model instance

    Returns:
        Webhook URL or None if not available
    """
    # Try explicit webhook URL first
    if hasattr(hub, 'webhook_url') and hub.webhook_url:
        return hub.webhook_url

    # Try to construct from IP address
    if hasattr(hub, 'ip_address') and hub.ip_address:
        return f"http://{hub.ip_address}:5000/api/v1/screens/webhook/playlist-updated"

    # Try last known IP from heartbeat
    if hasattr(hub, 'last_ip') and hub.last_ip:
        return f"http://{hub.last_ip}:5000/api/v1/screens/webhook/playlist-updated"

    return None


def _send_notification(
    webhook_url: str,
    device_id: Optional[str],
    playlist_id: Optional[int],
    action: str,
    hub_code: str
) -> bool:
    """
    Send a single notification to a Hub webhook.

    Args:
        webhook_url: Hub's webhook endpoint URL
        device_id: Optional device hardware_id
        playlist_id: Optional playlist ID
        action: Action type
        hub_code: Hub code for logging

    Returns:
        True if notification was successful, False otherwise
    """
    try:
        payload = {
            'action': action
        }
        if device_id:
            payload['device_id'] = device_id
        if playlist_id:
            payload['playlist_id'] = playlist_id

        response = requests.post(
            webhook_url,
            json=payload,
            timeout=10,
            headers={'Content-Type': 'application/json'}
        )

        if response.status_code in (200, 207):
            logger.info(
                f"Successfully notified hub {hub_code} at {webhook_url}: "
                f"action={action}, device={device_id}, playlist={playlist_id}"
            )
            return True
        else:
            logger.warning(
                f"Hub {hub_code} returned status {response.status_code}: "
                f"{response.text[:200]}"
            )
            return False

    except requests.Timeout:
        logger.warning(f"Timeout notifying hub {hub_code} at {webhook_url}")
        return False
    except requests.RequestException as e:
        logger.warning(f"Failed to notify hub {hub_code} at {webhook_url}: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error notifying hub {hub_code}: {e}")
        return False

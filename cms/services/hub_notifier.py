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
    Notify all registered Hubs that a playlist has been updated.

    This triggers immediate sync on the Hub instead of waiting for
    the polling interval (typically 5 minutes).

    Args:
        device_id: Optional device hardware_id to sync specific device
        playlist_id: Optional playlist ID that was changed
        action: Action type ('updated', 'deleted', 'assigned')
    """
    from cms.models import Hub

    # Get all active hubs with webhook URLs
    hubs = Hub.query.filter(
        Hub.status == 'active',
        Hub.webhook_url.isnot(None)
    ).all()

    if not hubs:
        logger.debug("No active hubs with webhook URLs to notify")
        return

    # Send notifications asynchronously to avoid blocking the request
    for hub in hubs:
        _executor.submit(
            _send_notification,
            hub.webhook_url,
            device_id,
            playlist_id,
            action,
            hub.code
        )


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

#!/usr/bin/env python3
"""
Hub Pairing Script - Pairs the local hub with the CMS.

Run this script to register the hub with the CMS:
    python pair_hub.py [CONFIG_PATH]

The script will:
1. Generate a unique hardware ID and pairing code
2. Display the pairing code
3. Wait for an admin to enter the code in the CMS
4. Store the credentials for future use

Example:
    python pair_hub.py
    python pair_hub.py /etc/skillz-hub/config.json
"""

import os
import sys
import time

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import load_config
from services.hub_pairing import HubPairingService, get_hardware_id


def display_pairing_screen(pairing_code: str, hardware_id: str, cms_url: str):
    """Display the pairing code."""
    print('\n' + '=' * 60)
    print('    ╔═══════════════════════════════════════════════╗')
    print('    ║                                               ║')
    print('    ║         🖥️  SKILLZ MEDIA LOCAL HUB            ║')
    print('    ║                                               ║')
    print('    ║           Waiting for Pairing...              ║')
    print('    ║                                               ║')
    print(f'    ║         PAIRING CODE: {pairing_code}             ║')
    print('    ║                                               ║')
    print(f'    ║         Hardware: {hardware_id}          ║')
    print('    ║                                               ║')
    print('    ║   Enter this code in the CMS to pair hub      ║')
    print('    ║                                               ║')
    print('    ╚═══════════════════════════════════════════════╝')
    print('=' * 60)
    print(f'\nCMS URL: {cms_url}')
    print('Go to the CMS Hubs page and enter the pairing code\n')


def main():
    # Load config
    config_path = sys.argv[1] if len(sys.argv) > 1 else None

    if config_path is None:
        # Try common locations
        for path in [
            'config.dev.json',
            '/etc/skillz-hub/config.json',
            os.path.expanduser('~/.skillz-hub/config.json'),
        ]:
            if os.path.exists(path):
                config_path = path
                break

    config = load_config(config_path)
    cms_url = config.cms_url

    print(f'\n🔧 Skillz Media Hub Pairing')
    print(f'   CMS URL: {cms_url}')

    # Initialize Flask app context for database access
    from app import create_app
    app = create_app(config_path)

    with app.app_context():
        from models.hub_config import HubConfig

        hub_config = HubConfig.get_instance()

        # Check if already registered
        if hub_config.is_registered:
            print(f'\n✅ Hub is already registered!')
            print(f'   Hub ID: {hub_config.hub_id}')
            print(f'   Hub Code: {hub_config.hub_code}')
            print(f'   Hub Name: {hub_config.hub_name}')
            print(f'   Network: {hub_config.network_id}')
            print(f'\nTo re-pair, clear the hub config first.')
            return

        # Start pairing
        hardware_id = get_hardware_id()
        service = HubPairingService(cms_url=cms_url, hardware_id=hardware_id)

        # Announce to CMS
        result = service.announce()

        if result.get('status') == 'already_paired':
            # Hub was paired by CMS already - store credentials
            HubConfig.update_registration(
                hub_id=result.get('hub_id'),
                hub_token=result.get('api_token'),
                hub_code=result.get('hub_code'),
                hub_name=result.get('store_name'),
                network_id=result.get('network_id'),
                status='active',
            )
            print(f'\n✅ Hub is already paired!')
            print(f'   Store: {result.get("store_name")}')
            print(f'   Hub Code: {result.get("hub_code")}')
            return

        if result.get('status') == 'error':
            print(f'\n❌ Failed to announce hub: {result.get("error")}')
            print('   Make sure the CMS is running and accessible.')
            return

        # Display pairing screen
        display_pairing_screen(service.pairing_code, hardware_id, cms_url)

        print('⏳ Polling for pairing status every 5 seconds...')
        print('   Press Ctrl+C to cancel\n')

        try:
            poll_count = 0
            while True:
                status = service.check_pairing_status()
                status_type = status.get('status')

                if status_type == 'paired':
                    # Store credentials
                    HubConfig.update_registration(
                        hub_id=status.get('hub_id'),
                        hub_token=status.get('api_token'),
                        hub_code=status.get('hub_code'),
                        hub_name=status.get('store_name'),
                        network_id=status.get('network_id'),
                        status='active',
                    )

                    print('\n' + '=' * 60)
                    print('    🎉 HUB PAIRED SUCCESSFULLY!')
                    print('=' * 60)
                    print(f'\n   Hub ID: {status.get("hub_id")}')
                    print(f'   Hub Code: {status.get("hub_code")}')
                    print(f'   Store Name: {status.get("store_name")}')
                    print(f'   Network ID: {status.get("network_id")}')
                    print('\n   Credentials saved. Restart the hub service to begin operation.')
                    print()
                    return

                elif status_type == 'expired':
                    print('\n⚠️  Pairing code expired. Regenerating...')
                    result = service.announce()
                    if result.get('status') == 'error':
                        print(f'   Error: {result.get("error")}')
                        return
                    display_pairing_screen(service.pairing_code, hardware_id, cms_url)
                    poll_count = 0

                elif status_type == 'pending':
                    print(f'   [{poll_count + 1}] Status: pending... waiting for admin')

                else:
                    print(f'   [{poll_count + 1}] Status: {status_type}')

                poll_count += 1
                time.sleep(5)

        except KeyboardInterrupt:
            print('\n\n👋 Pairing cancelled.')


if __name__ == '__main__':
    main()

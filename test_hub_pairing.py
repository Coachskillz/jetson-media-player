#!/usr/bin/env python3
"""
Test script for Hub Pairing Flow.

This script simulates a local hub announcing itself to the CMS
and polling for pairing status. Run this to test the pairing system.

Usage:
    python test_hub_pairing.py [CMS_URL]

    Default CMS_URL: http://localhost:5002

Example:
    python test_hub_pairing.py
    python test_hub_pairing.py http://192.168.1.90:5002
"""

import sys
import time
import random
import string
import socket
import requests


def get_local_ip():
    """Get the local IP address of this machine."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'


def generate_hardware_id():
    """Generate a unique hardware ID for the hub."""
    chars = ''.join(random.choices(string.hexdigits.upper(), k=8))
    return f'HUB-{chars}'


def generate_pairing_code():
    """Generate a pairing code to display on the hub screen."""
    part1 = ''.join(random.choices(string.ascii_uppercase, k=3))
    part2 = ''.join(random.choices(string.digits, k=3))
    return f'{part1}-{part2}'


def announce_hub(cms_url, hardware_id, pairing_code):
    """Announce the hub to the CMS."""
    url = f'{cms_url}/api/v1/hubs/announce'
    payload = {
        'hardware_id': hardware_id,
        'pairing_code': pairing_code,
        'wan_ip': get_local_ip(),
        'lan_ip': '10.10.10.1',
        'tunnel_url': f'{hardware_id.lower()}.skillzmedia.local',
        'version': '1.0.0'
    }

    print(f'\n📡 Announcing hub to CMS...')
    print(f'   URL: {url}')
    print(f'   Hardware ID: {hardware_id}')
    print(f'   Pairing Code: {pairing_code}')

    try:
        response = requests.post(url, json=payload, timeout=10)
        data = response.json()
        print(f'   Response: {response.status_code} - {data}')
        return data
    except Exception as e:
        print(f'   ❌ Error: {e}')
        return None


def poll_pairing_status(cms_url, hardware_id):
    """Poll the CMS to check if pairing is complete."""
    url = f'{cms_url}/api/v1/hubs/pairing-status'
    params = {'hardware_id': hardware_id}

    try:
        response = requests.get(url, params=params, timeout=10)
        return response.json()
    except Exception as e:
        print(f'   ❌ Poll error: {e}')
        return None


def display_pairing_screen(pairing_code, hardware_id):
    """Display the pairing code (simulates what the hub would show on screen)."""
    print('\n' + '=' * 60)
    print('    ╔═══════════════════════════════════════════════╗')
    print('    ║                                               ║')
    print('    ║         🖥️  SKILLZ MEDIA HUB                  ║')
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


def main():
    # Get CMS URL from command line or use default
    cms_url = sys.argv[1] if len(sys.argv) > 1 else 'http://localhost:5002'

    print(f'\n🔧 Hub Pairing Test Script')
    print(f'   CMS URL: {cms_url}')

    # Generate unique IDs for this test session
    hardware_id = generate_hardware_id()
    pairing_code = generate_pairing_code()

    # Announce hub to CMS
    result = announce_hub(cms_url, hardware_id, pairing_code)

    if not result:
        print('\n❌ Failed to announce hub. Is the CMS running?')
        return

    if result.get('status') == 'already_paired':
        print(f'\n✅ Hub is already paired!')
        print(f'   Hub ID: {result.get("hub_id")}')
        print(f'   Store: {result.get("store_name")}')
        print(f'   API Token: {result.get("api_token")[:20]}...')
        return

    # Display pairing screen
    display_pairing_screen(pairing_code, hardware_id)

    # Poll for pairing status
    print(f'\n⏳ Polling for pairing status every 5 seconds...')
    print('   (Go to the CMS Hubs page and enter the pairing code)')
    print('   Press Ctrl+C to stop\n')

    poll_count = 0
    max_polls = 180  # 15 minutes (180 * 5 seconds)

    try:
        while poll_count < max_polls:
            status = poll_pairing_status(cms_url, hardware_id)

            if not status:
                poll_count += 1
                time.sleep(5)
                continue

            status_type = status.get('status')

            if status_type == 'paired':
                print('\n' + '=' * 60)
                print('    🎉 HUB PAIRED SUCCESSFULLY!')
                print('=' * 60)
                print(f'\n   Hub ID: {status.get("hub_id")}')
                print(f'   Hub Code: {status.get("hub_code")}')
                print(f'   Store Name: {status.get("store_name")}')
                print(f'   Network ID: {status.get("network_id")}')
                print(f'   API Token: {status.get("api_token")[:20]}...')
                print('\n   Save these values for the hub configuration!')
                print()
                return

            elif status_type == 'expired':
                print(f'\n⚠️  Pairing code expired. Regenerating...')
                pairing_code = generate_pairing_code()
                announce_hub(cms_url, hardware_id, pairing_code)
                display_pairing_screen(pairing_code, hardware_id)
                poll_count = 0

            elif status_type == 'pending':
                print(f'   [{poll_count + 1}] Status: pending... waiting for admin')

            else:
                print(f'   [{poll_count + 1}] Status: {status_type}')

            poll_count += 1
            time.sleep(5)

        print('\n⏰ Polling timeout. Pairing code may have expired.')

    except KeyboardInterrupt:
        print('\n\n👋 Pairing cancelled by user.')


if __name__ == '__main__':
    main()

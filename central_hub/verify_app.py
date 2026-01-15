#!/usr/bin/env python3
"""
End-to-End Verification Script for Central Hub Flask Application

This script verifies:
1. Flask app can be created successfully
2. Health endpoint responds correctly
3. All blueprints are registered
4. Basic API connectivity works

Usage:
    python central_hub/verify_app.py

Expected output on success:
    - App creation successful
    - All routes registered
    - Health check returns 200 with status: ok
"""

import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def verify_app_creation():
    """Verify the Flask application can be created successfully."""
    print("=" * 60)
    print("STEP 1: Verifying Flask App Creation")
    print("=" * 60)

    try:
        from central_hub.app import create_app
        app = create_app('testing')
        print("  [PASS] Flask app created successfully")
        print(f"  [INFO] App name: {app.name}")
        print(f"  [INFO] Debug mode: {app.debug}")
        return app
    except Exception as e:
        print(f"  [FAIL] Failed to create Flask app: {e}")
        return None


def verify_routes_registered(app):
    """Verify all expected routes are registered."""
    print("\n" + "=" * 60)
    print("STEP 2: Verifying Route Registration")
    print("=" * 60)

    expected_routes = [
        '/api/health',
        '/api/v1/health',
        '/api/test',
        '/api/v1/ncmec/records',
        '/api/v1/ncmec/compile',
        '/api/v1/alerts/',
        '/api/v1/notification-settings',
    ]

    registered_routes = [str(rule) for rule in app.url_map.iter_rules()]

    all_found = True
    for route in expected_routes:
        if any(route in r for r in registered_routes):
            print(f"  [PASS] Route registered: {route}")
        else:
            print(f"  [FAIL] Route NOT found: {route}")
            all_found = False

    # Print all registered routes for debugging
    print("\n  [INFO] All registered routes:")
    for rule in sorted(app.url_map.iter_rules(), key=lambda x: str(x)):
        if not str(rule).startswith('/static'):
            print(f"    - {rule.methods}: {rule}")

    return all_found


def verify_health_endpoint(app):
    """Verify health endpoint responds correctly."""
    print("\n" + "=" * 60)
    print("STEP 3: Verifying Health Endpoint")
    print("=" * 60)

    with app.test_client() as client:
        # Test /api/v1/health (the one in verification spec)
        response = client.get('/api/v1/health', headers={'Content-Type': 'application/json'})

        print(f"  [INFO] GET /api/v1/health")
        print(f"  [INFO] Status Code: {response.status_code}")

        if response.status_code == 200:
            print("  [PASS] Health endpoint returned 200")

            data = response.get_json()
            print(f"  [INFO] Response: {data}")

            if data.get('status') == 'ok':
                print("  [PASS] Status is 'ok'")
            else:
                print(f"  [FAIL] Unexpected status: {data.get('status')}")
                return False

            if data.get('service') == 'central_hub':
                print("  [PASS] Service name is 'central_hub'")
            else:
                print(f"  [WARN] Unexpected service: {data.get('service')}")

            if 'timestamp' in data:
                print("  [PASS] Timestamp present")
            else:
                print("  [WARN] Timestamp missing")

            return True
        else:
            print(f"  [FAIL] Health endpoint returned {response.status_code}")
            return False


def verify_test_endpoint(app):
    """Verify test endpoint responds correctly."""
    print("\n" + "=" * 60)
    print("STEP 4: Verifying Test Endpoint")
    print("=" * 60)

    with app.test_client() as client:
        response = client.get('/api/test')

        print(f"  [INFO] GET /api/test")
        print(f"  [INFO] Status Code: {response.status_code}")

        if response.status_code == 200:
            print("  [PASS] Test endpoint returned 200")
            data = response.get_json()
            print(f"  [INFO] Response: {data}")
            return True
        else:
            print(f"  [FAIL] Test endpoint returned {response.status_code}")
            return False


def main():
    """Run all verification steps."""
    print("\n")
    print("*" * 60)
    print("*  Central Hub End-to-End Verification")
    print("*" * 60)

    results = []

    # Step 1: Create app
    app = verify_app_creation()
    if app is None:
        print("\n[FATAL] Cannot continue without Flask app")
        sys.exit(1)
    results.append(("App Creation", True))

    # Step 2: Verify routes
    routes_ok = verify_routes_registered(app)
    results.append(("Routes Registration", routes_ok))

    # Step 3: Health endpoint
    health_ok = verify_health_endpoint(app)
    results.append(("Health Endpoint", health_ok))

    # Step 4: Test endpoint
    test_ok = verify_test_endpoint(app)
    results.append(("Test Endpoint", test_ok))

    # Summary
    print("\n" + "=" * 60)
    print("VERIFICATION SUMMARY")
    print("=" * 60)

    all_passed = True
    for name, passed in results:
        status = "[PASS]" if passed else "[FAIL]"
        print(f"  {status} {name}")
        if not passed:
            all_passed = False

    print("\n" + "=" * 60)
    if all_passed:
        print("ALL VERIFICATIONS PASSED!")
        print("=" * 60)
        print("\nThe Flask app is ready for production use.")
        print("\nTo start the server manually:")
        print("  export FLASK_APP=central_hub/app.py")
        print("  export FLASK_ENV=development")
        print("  flask run --port 5002")
        print("\nThen test with:")
        print('  curl -X GET http://localhost:5002/api/v1/health -H "Content-Type: application/json"')
        sys.exit(0)
    else:
        print("SOME VERIFICATIONS FAILED!")
        print("=" * 60)
        sys.exit(1)


if __name__ == '__main__':
    main()

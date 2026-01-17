#!/bin/bash
#
# API Contract Verification Script for Hub Sync Protocol
#
# This script verifies that CMS endpoints return the expected structure
# for the hub sync protocol. It tests:
# - POST /api/v1/hubs/register - Hub registration with API token
# - PUT /api/v1/hubs/{hub_id}/approve - Hub approval
# - GET /api/v1/hubs/{hub_id}/playlists - Playlist manifest
# - POST /api/v1/hubs/{hub_id}/heartbeats - Batched heartbeats
#
# Prerequisites:
# - CMS service running on port 5002
# - jq installed for JSON parsing
#
# Usage:
#   ./tests/integration/verify_api_contracts.sh
#
# Environment Variables:
#   CMS_URL - CMS base URL (default: http://localhost:5002)
#   DEBUG - Set to 1 for verbose output
#

set -e

# Configuration
CMS_URL="${CMS_URL:-http://localhost:5002}"
DEBUG="${DEBUG:-0}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Test counters
TESTS_PASSED=0
TESTS_FAILED=0

# ============================================================================
# Helper Functions
# ============================================================================

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[PASS]${NC} $1"
    ((TESTS_PASSED++))
}

log_fail() {
    echo -e "${RED}[FAIL]${NC} $1"
    ((TESTS_FAILED++))
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_debug() {
    if [[ "$DEBUG" == "1" ]]; then
        echo -e "${YELLOW}[DEBUG]${NC} $1"
    fi
}

# Check if jq is installed
check_dependencies() {
    if ! command -v jq &> /dev/null; then
        log_fail "jq is required but not installed. Install with: brew install jq"
        exit 1
    fi
    if ! command -v curl &> /dev/null; then
        log_fail "curl is required but not installed."
        exit 1
    fi
    log_info "Dependencies verified: curl, jq"
}

# Check if CMS is running
check_cms_running() {
    log_info "Checking if CMS is running at $CMS_URL..."
    if curl -s -o /dev/null -w "%{http_code}" "$CMS_URL/health" 2>/dev/null | grep -q "200\|404"; then
        log_info "CMS is accessible"
        return 0
    else
        log_fail "CMS is not running or not accessible at $CMS_URL"
        echo ""
        echo "To start CMS, run:"
        echo "  cd cms && python app.py"
        exit 1
    fi
}

# Make API request and return response
api_request() {
    local method="$1"
    local endpoint="$2"
    local data="$3"
    local auth_token="$4"

    local url="$CMS_URL$endpoint"
    local headers="-H 'Content-Type: application/json'"

    if [[ -n "$auth_token" ]]; then
        headers="$headers -H 'Authorization: Bearer $auth_token'"
    fi

    log_debug "Request: $method $url"
    log_debug "Data: $data"

    if [[ "$method" == "GET" ]]; then
        if [[ -n "$auth_token" ]]; then
            response=$(curl -s -X GET "$url" -H "Content-Type: application/json" -H "Authorization: Bearer $auth_token")
        else
            response=$(curl -s -X GET "$url" -H "Content-Type: application/json")
        fi
    elif [[ "$method" == "POST" ]]; then
        if [[ -n "$auth_token" ]]; then
            response=$(curl -s -X POST "$url" -H "Content-Type: application/json" -H "Authorization: Bearer $auth_token" -d "$data")
        else
            response=$(curl -s -X POST "$url" -H "Content-Type: application/json" -d "$data")
        fi
    elif [[ "$method" == "PUT" ]]; then
        if [[ -n "$auth_token" ]]; then
            response=$(curl -s -X PUT "$url" -H "Content-Type: application/json" -H "Authorization: Bearer $auth_token" -d "$data")
        else
            response=$(curl -s -X PUT "$url" -H "Content-Type: application/json" -d "$data")
        fi
    fi

    log_debug "Response: $response"
    echo "$response"
}

# Check if JSON field exists and is not null
check_field_exists() {
    local json="$1"
    local field="$2"
    local description="$3"

    local value
    value=$(echo "$json" | jq -r ".$field // empty")

    if [[ -n "$value" ]]; then
        log_success "$description: $field exists (value: $value)"
        return 0
    else
        log_fail "$description: $field is missing or null"
        return 1
    fi
}

# Check if JSON field equals expected value
check_field_equals() {
    local json="$1"
    local field="$2"
    local expected="$3"
    local description="$4"

    local actual
    actual=$(echo "$json" | jq -r ".$field // empty")

    if [[ "$actual" == "$expected" ]]; then
        log_success "$description: $field == $expected"
        return 0
    else
        log_fail "$description: $field expected '$expected' but got '$actual'"
        return 1
    fi
}

# Check if JSON field is an array
check_field_is_array() {
    local json="$1"
    local field="$2"
    local description="$3"

    local is_array
    is_array=$(echo "$json" | jq ".$field | type == \"array\"")

    if [[ "$is_array" == "true" ]]; then
        log_success "$description: $field is an array"
        return 0
    else
        log_fail "$description: $field is not an array"
        return 1
    fi
}

# ============================================================================
# Test Setup - Create Test Data
# ============================================================================

setup_test_network() {
    log_info "Setting up test network..."

    # Try to create a network (may fail if it exists, which is fine)
    local network_response
    network_response=$(api_request POST "/api/v1/networks" '{"name":"Test Network","slug":"test-network"}')

    # Check if it was created or already exists
    if echo "$network_response" | jq -e '.id' > /dev/null 2>&1; then
        NETWORK_ID=$(echo "$network_response" | jq -r '.id')
        log_info "Created test network: $NETWORK_ID"
    elif echo "$network_response" | jq -e '.error' | grep -q "already exists" 2>/dev/null; then
        # Network exists, query it
        local networks_response
        networks_response=$(api_request GET "/api/v1/networks")
        NETWORK_ID=$(echo "$networks_response" | jq -r '.networks[] | select(.slug == "test-network") | .id')
        log_info "Using existing test network: $NETWORK_ID"
    else
        log_warn "Could not create/find network, tests may fail"
        # Try to get the first network
        local networks_response
        networks_response=$(api_request GET "/api/v1/networks")
        NETWORK_ID=$(echo "$networks_response" | jq -r '.networks[0].id // empty')
        if [[ -n "$NETWORK_ID" ]]; then
            log_info "Using first available network: $NETWORK_ID"
        fi
    fi

    export NETWORK_ID
}

# ============================================================================
# Test 1: Hub Registration API Contract
# ============================================================================

test_hub_registration() {
    echo ""
    log_info "========================================="
    log_info "Test 1: Hub Registration API Contract"
    log_info "Endpoint: POST /api/v1/hubs/register"
    log_info "========================================="

    if [[ -z "$NETWORK_ID" ]]; then
        log_fail "No network ID available, skipping registration test"
        return 1
    fi

    # Generate unique hub code
    local hub_code="TST$(date +%s | tail -c 4)"

    # Make registration request
    local register_data=$(cat <<EOF
{
    "code": "$hub_code",
    "name": "API Contract Test Hub",
    "network_id": "$NETWORK_ID",
    "ip_address": "192.168.1.100",
    "mac_address": "AA:BB:CC:DD:EE:FF",
    "hostname": "test-hub-verify"
}
EOF
)

    local response
    response=$(api_request POST "/api/v1/hubs/register" "$register_data")

    log_info "Response received, verifying contract..."

    # Verify response structure
    echo ""
    log_info "Expected Response Structure:"
    log_info "  - id: UUID of created hub"
    log_info "  - code: Hub code (2-4 uppercase letters)"
    log_info "  - name: Hub name"
    log_info "  - status: 'pending' for new hubs"
    log_info "  - api_token: Token starting with 'hub_'"
    log_info "  - ip_address, mac_address, hostname: Optional fields"
    echo ""

    # Required fields
    check_field_exists "$response" "id" "Hub Registration"
    check_field_equals "$response" "code" "$hub_code" "Hub Registration"
    check_field_equals "$response" "status" "pending" "Hub Registration"
    check_field_exists "$response" "api_token" "Hub Registration"
    check_field_equals "$response" "ip_address" "192.168.1.100" "Hub Registration"
    check_field_equals "$response" "mac_address" "AA:BB:CC:DD:EE:FF" "Hub Registration"
    check_field_equals "$response" "hostname" "test-hub-verify" "Hub Registration"

    # Store hub ID and token for later tests
    HUB_ID=$(echo "$response" | jq -r '.id')
    HUB_CODE=$(echo "$response" | jq -r '.code')
    API_TOKEN=$(echo "$response" | jq -r '.api_token')

    # Verify API token format
    if [[ "$API_TOKEN" =~ ^hub_ ]]; then
        log_success "Hub Registration: api_token has correct prefix 'hub_'"
    else
        log_fail "Hub Registration: api_token should start with 'hub_' but got '$API_TOKEN'"
    fi

    export HUB_ID HUB_CODE API_TOKEN
}

# ============================================================================
# Test 2: Hub Approval API Contract
# ============================================================================

test_hub_approval() {
    echo ""
    log_info "========================================="
    log_info "Test 2: Hub Approval API Contract"
    log_info "Endpoint: PUT /api/v1/hubs/{hub_id}/approve"
    log_info "========================================="

    if [[ -z "$HUB_ID" ]]; then
        log_fail "No hub ID available, skipping approval test"
        return 1
    fi

    # Make approval request
    local response
    response=$(api_request PUT "/api/v1/hubs/$HUB_ID/approve")

    log_info "Response received, verifying contract..."

    # Verify response structure
    echo ""
    log_info "Expected Response Structure:"
    log_info "  - id: UUID of approved hub"
    log_info "  - code: Hub code"
    log_info "  - status: 'active' after approval"
    log_info "  - All other hub fields preserved"
    echo ""

    # Required fields
    check_field_equals "$response" "id" "$HUB_ID" "Hub Approval"
    check_field_equals "$response" "code" "$HUB_CODE" "Hub Approval"
    check_field_equals "$response" "status" "active" "Hub Approval"
    check_field_exists "$response" "created_at" "Hub Approval"
    check_field_exists "$response" "network_id" "Hub Approval"

    # Verify fields were preserved
    check_field_exists "$response" "ip_address" "Hub Approval (preserved)"
    check_field_exists "$response" "mac_address" "Hub Approval (preserved)"
    check_field_exists "$response" "hostname" "Hub Approval (preserved)"
}

# ============================================================================
# Test 3: Playlist Manifest API Contract
# ============================================================================

test_playlist_manifest() {
    echo ""
    log_info "========================================="
    log_info "Test 3: Playlist Manifest API Contract"
    log_info "Endpoint: GET /api/v1/hubs/{hub_id}/playlists"
    log_info "========================================="

    if [[ -z "$HUB_ID" ]]; then
        log_fail "No hub ID available, skipping playlist test"
        return 1
    fi

    # Make playlist manifest request
    local response
    response=$(api_request GET "/api/v1/hubs/$HUB_ID/playlists" "" "$API_TOKEN")

    log_info "Response received, verifying contract..."

    # Verify response structure
    echo ""
    log_info "Expected Response Structure:"
    log_info "  - hub_id: UUID of the hub"
    log_info "  - hub_code: Code of the hub"
    log_info "  - network_id: Network UUID"
    log_info "  - manifest_version: Version number (integer)"
    log_info "  - playlists: Array of playlist objects"
    log_info "  - count: Number of playlists"
    log_info ""
    log_info "Each playlist object should have:"
    log_info "  - id, name, description"
    log_info "  - trigger_type, trigger_config"
    log_info "  - is_active, created_at, updated_at"
    log_info "  - items: Array of playlist items"
    echo ""

    # Required fields
    check_field_equals "$response" "hub_id" "$HUB_ID" "Playlist Manifest"
    check_field_equals "$response" "hub_code" "$HUB_CODE" "Playlist Manifest"
    check_field_exists "$response" "network_id" "Playlist Manifest"
    check_field_exists "$response" "manifest_version" "Playlist Manifest"
    check_field_is_array "$response" "playlists" "Playlist Manifest"
    check_field_exists "$response" "count" "Playlist Manifest"

    # Verify manifest_version is a number
    local version
    version=$(echo "$response" | jq '.manifest_version')
    if [[ "$version" =~ ^[0-9]+$ ]]; then
        log_success "Playlist Manifest: manifest_version is a number ($version)"
    else
        log_fail "Playlist Manifest: manifest_version should be a number but got '$version'"
    fi

    # If there are playlists, verify their structure
    local playlist_count
    playlist_count=$(echo "$response" | jq '.count')
    if [[ "$playlist_count" -gt 0 ]]; then
        log_info "Found $playlist_count playlists, verifying structure..."

        # Check first playlist structure
        local first_playlist
        first_playlist=$(echo "$response" | jq '.playlists[0]')

        check_field_exists "$first_playlist" "id" "Playlist Object"
        check_field_exists "$first_playlist" "name" "Playlist Object"
        check_field_exists "$first_playlist" "is_active" "Playlist Object"
        check_field_is_array "$first_playlist" "items" "Playlist Object"
    else
        log_info "No playlists found (count: $playlist_count) - this is expected for a new network"
        log_success "Playlist Manifest: Empty playlists array is valid"
    fi
}

# ============================================================================
# Test 4: Heartbeat Batch API Contract
# ============================================================================

test_heartbeat_batch() {
    echo ""
    log_info "========================================="
    log_info "Test 4: Heartbeat Batch API Contract"
    log_info "Endpoint: POST /api/v1/hubs/{hub_id}/heartbeats"
    log_info "========================================="

    if [[ -z "$HUB_ID" ]]; then
        log_fail "No hub ID available, skipping heartbeat test"
        return 1
    fi

    # Make heartbeat request (empty batch - should work)
    local heartbeat_data='{"heartbeats": []}'

    local response
    response=$(api_request POST "/api/v1/hubs/$HUB_ID/heartbeats" "$heartbeat_data" "$API_TOKEN")

    log_info "Response received, verifying contract..."

    # Verify response structure
    echo ""
    log_info "Expected Response Structure:"
    log_info "  - processed: Number of heartbeats processed (integer)"
    log_info "  - errors: Array of error messages (can be empty)"
    log_info "  - hub_last_heartbeat: ISO timestamp of last heartbeat"
    echo ""

    # Required fields
    check_field_exists "$response" "processed" "Heartbeat Batch"
    check_field_is_array "$response" "errors" "Heartbeat Batch"
    check_field_exists "$response" "hub_last_heartbeat" "Heartbeat Batch"

    # Verify processed is a number
    local processed
    processed=$(echo "$response" | jq '.processed')
    if [[ "$processed" =~ ^[0-9]+$ ]]; then
        log_success "Heartbeat Batch: processed is a number ($processed)"
    else
        log_fail "Heartbeat Batch: processed should be a number but got '$processed'"
    fi

    # Test with a heartbeat for a non-existent device (should still work but with error)
    echo ""
    log_info "Testing with non-existent device (should return partial success)..."

    local heartbeat_with_device='{"heartbeats": [{"device_id": "SKZ-H-TST-9999", "status": "active"}]}'
    local response2
    response2=$(api_request POST "/api/v1/hubs/$HUB_ID/heartbeats" "$heartbeat_with_device" "$API_TOKEN")

    # Should still return 200 with error in errors array
    check_field_exists "$response2" "processed" "Heartbeat with Error"
    check_field_is_array "$response2" "errors" "Heartbeat with Error"

    local errors_count
    errors_count=$(echo "$response2" | jq '.errors | length')
    if [[ "$errors_count" -gt 0 ]]; then
        log_success "Heartbeat with Error: errors array contains error message (expected behavior)"
        log_debug "Error message: $(echo "$response2" | jq -r '.errors[0]')"
    else
        log_info "Heartbeat with Error: No errors (device may exist)"
    fi
}

# ============================================================================
# Test 5: Error Response Contract
# ============================================================================

test_error_responses() {
    echo ""
    log_info "========================================="
    log_info "Test 5: Error Response Contract"
    log_info "========================================="

    # Test 404 - Hub not found
    log_info "Testing 404 response for non-existent hub..."
    local response404
    response404=$(api_request GET "/api/v1/hubs/non-existent-hub-id/playlists")

    if echo "$response404" | jq -e '.error' > /dev/null 2>&1; then
        log_success "404 Response: Contains 'error' field"
        local error_msg
        error_msg=$(echo "$response404" | jq -r '.error')
        if echo "$error_msg" | grep -iq "not found"; then
            log_success "404 Response: Error message contains 'not found'"
        else
            log_fail "404 Response: Error message should contain 'not found' but got '$error_msg'"
        fi
    else
        log_fail "404 Response: Missing 'error' field"
    fi

    # Test 400 - Bad request (invalid heartbeat data)
    log_info "Testing 400 response for invalid request..."
    if [[ -n "$HUB_ID" ]]; then
        local response400
        response400=$(api_request POST "/api/v1/hubs/$HUB_ID/heartbeats" '{"invalid": "data"}')

        if echo "$response400" | jq -e '.error' > /dev/null 2>&1; then
            log_success "400 Response: Contains 'error' field"
        else
            log_fail "400 Response: Missing 'error' field"
        fi
    fi
}

# ============================================================================
# Test Summary
# ============================================================================

print_summary() {
    echo ""
    log_info "========================================="
    log_info "API Contract Verification Summary"
    log_info "========================================="
    echo ""
    echo -e "Tests Passed: ${GREEN}$TESTS_PASSED${NC}"
    echo -e "Tests Failed: ${RED}$TESTS_FAILED${NC}"
    echo ""

    if [[ $TESTS_FAILED -eq 0 ]]; then
        echo -e "${GREEN}✓ All API contracts verified successfully!${NC}"
        return 0
    else
        echo -e "${RED}✗ Some API contract tests failed${NC}"
        return 1
    fi
}

# ============================================================================
# Cleanup
# ============================================================================

cleanup() {
    log_info "Cleaning up test data..."
    # Note: In production, you might want to delete the test hub
    # For now, we leave it for inspection
    log_info "Test hub ID: $HUB_ID (not deleted for inspection)"
}

# ============================================================================
# Main
# ============================================================================

main() {
    echo ""
    log_info "========================================="
    log_info "Hub Sync Protocol - API Contract Verification"
    log_info "CMS URL: $CMS_URL"
    log_info "========================================="
    echo ""

    # Setup
    check_dependencies
    check_cms_running
    setup_test_network

    # Run tests
    test_hub_registration
    test_hub_approval
    test_playlist_manifest
    test_heartbeat_batch
    test_error_responses

    # Summary and cleanup
    cleanup
    print_summary
}

# Run main
main "$@"

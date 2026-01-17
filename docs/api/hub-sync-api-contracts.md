# Hub Sync Protocol - API Contracts

This document defines the API contracts for the Hub Sync Protocol endpoints. These contracts
specify the request/response formats that CMS endpoints must follow for local hubs to properly
communicate with the CMS.

## Table of Contents

1. [Hub Registration](#hub-registration)
2. [Hub Approval](#hub-approval)
3. [Playlist Manifest](#playlist-manifest)
4. [Batched Heartbeats](#batched-heartbeats)
5. [Error Responses](#error-responses)

---

## Hub Registration

**Endpoint:** `POST /api/v1/hubs/register`
**Auth Required:** No
**Description:** Register a new hub with the CMS

### Request Body

```json
{
    "code": "WM",                           // Required: 2-4 uppercase letters
    "name": "West Marine Hub",              // Required: Hub name (max 200 chars)
    "network_id": "uuid-of-network",        // Required: Network UUID
    "location": "123 Main St",              // Optional: Location string (max 500 chars)
    "ip_address": "192.168.1.100",          // Optional: IPv4 or IPv6 (max 45 chars)
    "mac_address": "AA:BB:CC:DD:EE:FF",     // Optional: MAC address format
    "hostname": "hub-westmarine"            // Optional: Hostname (max 255 chars)
}
```

### Success Response (201 Created)

```json
{
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "code": "WM",
    "name": "West Marine Hub",
    "network_id": "uuid-of-network",
    "status": "pending",
    "created_at": "2024-01-15T10:00:00+00:00",
    "ip_address": "192.168.1.100",
    "mac_address": "AA:BB:CC:DD:EE:FF",
    "hostname": "hub-westmarine",
    "last_heartbeat": null,
    "api_token": "hub_abc123xyz..."
}
```

### Key Contract Points

- `id`: UUID, auto-generated
- `code`: Exactly as provided, uppercase
- `status`: Always `"pending"` for new registrations
- `api_token`: Starts with `"hub_"` prefix, used for future authenticated requests
- `mac_address`: Stored in uppercase

### Error Responses

| Status | Error | Description |
|--------|-------|-------------|
| 400 | `"code is required"` | Missing required field |
| 400 | `"code must be 2-4 uppercase letters"` | Invalid code format |
| 400 | `"mac_address must be in format XX:XX:XX:XX:XX:XX"` | Invalid MAC format |
| 404 | `"Network with id {id} not found"` | Network doesn't exist |
| 409 | `"Hub with code 'XX' already exists"` | Duplicate hub code |

---

## Hub Approval

**Endpoint:** `PUT /api/v1/hubs/{hub_id}/approve`
**Auth Required:** Yes (login required)
**Description:** Approve a pending hub to activate it

### Path Parameters

- `hub_id`: Hub UUID or code

### Success Response (200 OK)

```json
{
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "code": "WM",
    "name": "West Marine Hub",
    "network_id": "uuid-of-network",
    "status": "active",                    // Changed from "pending"
    "created_at": "2024-01-15T10:00:00+00:00",
    "ip_address": "192.168.1.100",
    "mac_address": "AA:BB:CC:DD:EE:FF",
    "hostname": "hub-westmarine",
    "last_heartbeat": null,
    "api_token": "hub_abc123xyz..."
}
```

### Key Contract Points

- `status`: Changes from `"pending"` to `"active"`
- All other fields preserved unchanged
- Only works on hubs with `status: "pending"`

### Error Responses

| Status | Error | Description |
|--------|-------|-------------|
| 400 | `"Hub is not in pending state"` | Hub already active/inactive |
| 404 | `"Hub not found"` | Hub doesn't exist |

---

## Playlist Manifest

**Endpoint:** `GET /api/v1/hubs/{hub_id}/playlists`
**Auth Required:** No (but token should be sent)
**Description:** Get playlist manifest for a hub's network

### Path Parameters

- `hub_id`: Hub UUID or code

### Success Response (200 OK)

```json
{
    "hub_id": "550e8400-e29b-41d4-a716-446655440000",
    "hub_code": "WM",
    "network_id": "network-uuid",
    "manifest_version": 1,
    "playlists": [
        {
            "id": "playlist-uuid",
            "name": "Morning Playlist",
            "description": "Plays in the morning",
            "network_id": "network-uuid",
            "trigger_type": "time",
            "trigger_config": "{\"start\": \"08:00\", \"end\": \"12:00\"}",
            "is_active": true,
            "created_at": "2024-01-15T10:00:00+00:00",
            "updated_at": "2024-01-15T10:00:00+00:00",
            "item_count": 5,
            "items": [
                {
                    "id": "item-uuid",
                    "playlist_id": "playlist-uuid",
                    "content_id": "content-uuid",
                    "position": 0,
                    "duration_override": null,
                    "created_at": "2024-01-15T10:00:00+00:00",
                    "content": {
                        "id": "content-uuid",
                        "filename": "promo.mp4",
                        "mime_type": "video/mp4",
                        "file_size": 52428800
                    }
                }
            ]
        }
    ],
    "count": 1
}
```

### Key Contract Points

- `hub_id`, `hub_code`: Identifies the hub
- `network_id`: Hub's network UUID
- `manifest_version`: Integer, currently always `1`
- `playlists`: Array of playlist objects (may be empty)
- `count`: Number of playlists in array
- Only **active** playlists are included (`is_active: true`)
- Only playlists for the hub's network are included
- Each playlist includes full `items` array with content details

### Error Responses

| Status | Error | Description |
|--------|-------|-------------|
| 404 | `"Hub not found"` | Hub doesn't exist |

---

## Batched Heartbeats

**Endpoint:** `POST /api/v1/hubs/{hub_id}/heartbeats`
**Auth Required:** No (but token should be sent)
**Description:** Receive batched device heartbeats from a hub

### Path Parameters

- `hub_id`: Hub UUID or code

### Request Body

```json
{
    "heartbeats": [
        {
            "device_id": "SKZ-H-WM-0001",       // Required
            "status": "active",                  // Optional: active, offline, error
            "timestamp": "2024-01-15T10:00:00Z" // Optional: ISO format, defaults to now
        },
        {
            "device_id": "SKZ-H-WM-0002",
            "status": "offline"
        }
    ]
}
```

### Success Response (200 OK)

```json
{
    "processed": 2,
    "errors": [],
    "hub_last_heartbeat": "2024-01-15T10:00:00+00:00"
}
```

### Partial Success Response (200 OK)

When some heartbeats fail to process:

```json
{
    "processed": 1,
    "errors": [
        "Device SKZ-H-WM-9999 not found"
    ],
    "hub_last_heartbeat": "2024-01-15T10:00:00+00:00"
}
```

### Key Contract Points

- `processed`: Integer count of successfully processed heartbeats
- `errors`: Array of error messages (can be empty)
- `hub_last_heartbeat`: ISO timestamp, always updated
- Empty heartbeats array is valid (returns `processed: 0`)
- Unknown devices are reported in errors, not rejected

### Error Responses

| Status | Error | Description |
|--------|-------|-------------|
| 400 | `"Request body is required"` | Empty request body |
| 400 | `"heartbeats field is required"` | Missing heartbeats field |
| 400 | `"heartbeats must be an array"` | Invalid heartbeats type |
| 404 | `"Hub not found"` | Hub doesn't exist |

---

## Error Responses

All error responses follow a consistent format:

```json
{
    "error": "Human-readable error message"
}
```

### Common HTTP Status Codes

| Status | Meaning |
|--------|---------|
| 200 | Success |
| 201 | Created (for registration) |
| 400 | Bad Request (validation error) |
| 404 | Not Found |
| 409 | Conflict (duplicate) |
| 500 | Internal Server Error |

---

## Local Hub Client Usage

The local hub should use these endpoints via `HQClient`:

```python
from services.hq_client import HQClient

# Initialize client with CMS URL
client = HQClient("http://cms.example.com:5002")

# Register hub (no auth needed)
result = client.register_hub("test-network", machine_id="AA:BB:CC:DD:EE:FF")
# Token is automatically set after registration

# Get playlists (uses hub's token)
manifest = client.get_playlists(hub_id)
for playlist in manifest.get('playlists', []):
    print(f"Playlist: {playlist['name']}")

# Send batched heartbeats
heartbeats = [
    {"device_id": "SKZ-H-WM-0001", "status": "active"},
    {"device_id": "SKZ-H-WM-0002", "status": "active"},
]
result = client.send_batched_heartbeats(hub_id, heartbeats)
```

---

## Verification

To verify these API contracts are implemented correctly:

```bash
# Run the API contract verification script
./tests/integration/verify_api_contracts.sh

# Or with debug output
DEBUG=1 ./tests/integration/verify_api_contracts.sh

# Or with custom CMS URL
CMS_URL=http://cms.example.com:5002 ./tests/integration/verify_api_contracts.sh
```

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2024-01-17 | Initial API contract specification |

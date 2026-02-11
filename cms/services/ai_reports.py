"""
NVIDIA-powered AI Reporting Engine.

Converts natural language questions into SQL queries,
runs them against the database, and formats results.

Uses NVIDIA build.nvidia.com API (Option A) for LLM inference.
Can be switched to NVIDIA NIM (Option B) for self-hosted deployments.
"""

import os
import json
import logging
import requests
from datetime import datetime, timezone

from cms.models import db

logger = logging.getLogger(__name__)

# NVIDIA API configuration
NVIDIA_API_KEY = os.environ.get('NVIDIA_API_KEY')
NVIDIA_API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
NVIDIA_MODEL = os.environ.get('NVIDIA_MODEL', 'meta/llama-3.1-70b-instruct')

# Database schema description for the LLM
DB_SCHEMA = """
You have access to a SQLite database with these tables:

TABLE: devices
  - id (string, UUID primary key)
  - device_id (string, unique identifier like "SKZ-H-WM-0001")
  - hardware_id (string, hardware serial)
  - status (string: "active", "pending", "rejected")
  - mode (string: "hub" or "direct")
  - hub_id (string, nullable, which hub this device connects through)
  - network_id (string, nullable, e.g. "west_marine", "high_octane")
  - store_name (string, nullable, e.g. "West Marine Tampa")
  - screen_location (string, nullable, e.g. "Fishing Counter", "Register 1")
  - pairing_code (string, 6-digit code)
  - software_version (string, nullable)
  - created_at (datetime)
  - last_seen (datetime, nullable)

TABLE: heartbeats
  - id (integer, primary key)
  - device_id (string, references devices)
  - hub_id (string, nullable)
  - network_id (string, nullable)
  - store_name (string, nullable)
  - location (string, nullable)
  - status (string: "online")
  - current_content (string, nullable, filename currently playing)
  - ip_address (string)
  - cpu_temp (float, nullable, Celsius)
  - storage_free_mb (integer, nullable)
  - software_version (string, nullable)
  - mode (string, nullable)
  - timestamp (datetime, when heartbeat was received)

TABLE: playback_logs
  - id (integer, primary key)
  - device_id (string, references devices)
  - hub_id (string, nullable)
  - network_id (string, nullable)
  - store_name (string, nullable)
  - location (string, nullable)
  - content_filename (string, name of video file played)
  - started_at (datetime, when playback started)
  - ended_at (datetime, nullable)
  - duration_seconds (integer, how long it played)
  - created_at (datetime)

TABLE: alerts
  - id (integer, primary key)
  - device_id (string)
  - hub_id (string, nullable)
  - network_id (string, nullable)
  - store_name (string, nullable)
  - alert_type (string: "ncmec", "offline", "error", "update")
  - severity (string: "info", "warning", "critical")
  - message (text)
  - data_json (text, JSON blob)
  - acknowledged (boolean)
  - acknowledged_by (string, nullable)
  - created_at (datetime)

TABLE: hubs
  - id (string, UUID primary key)
  - hub_id (string, unique identifier like "HUB-WM-001")
  - name (string, hub name)
  - status (string: "active", "pending")
  - network_id (string, nullable)
  - store_name (string, nullable)
  - last_seen (datetime)

NETWORKS:
  - "west_marine" or network names containing "wave" = On The Wave TV (West Marine stores)
  - "high_octane" or network names containing "octane" = The High Octane Network (gas stations, convenience stores)

The current date/time is: {current_time}
"""

SYSTEM_PROMPT = """You are a data analyst for Skillz Media, a digital signage and retail media company.
You help generate SQL queries and format reports based on the database.

When asked a question:
1. Generate a valid SQLite SQL query to answer it
2. Return ONLY a JSON object with this format:
{{
  "sql": "SELECT ... FROM ...",
  "explanation": "Brief explanation of what this query does",
  "format": "table" or "number" or "list"
}}

Rules:
- Use SQLite syntax ONLY (not PostgreSQL)
- Always use lowercase table and column names
- For current time, use: datetime('now')
- For date arithmetic, use: datetime('now', '-5 minutes') or datetime('now', '-7 days')
- Example: WHERE timestamp > datetime('now', '-5 minutes')
- For "online" devices: check devices.status = 'active' or look for recent heartbeats (within last 5 minutes)
- For "offline" devices: no heartbeat in last 5 minutes OR devices.status != 'active'
- For uptime: count heartbeats vs expected (1 every 5 minutes = 288/day)
- Content plays = rows in playback_logs
- Always include relevant context (store name, network, device id) in results
- Limit results to 100 rows max unless asked for more
- Do NOT use DELETE, UPDATE, INSERT, DROP, ALTER, or any write operations
- Only SELECT queries are allowed
- Do NOT use PostgreSQL syntax like NOW(), INTERVAL, or ::type casting
"""


def query_nvidia_llm(user_question):
    """
    Send question to NVIDIA LLM, get back SQL query.

    Args:
        user_question: Natural language question from user

    Returns:
        Tuple of (result_dict, error_string)
        result_dict contains 'sql', 'explanation', 'format' keys
    """
    if not NVIDIA_API_KEY:
        return None, "NVIDIA_API_KEY not configured. Add it to your environment variables."

    schema_with_time = DB_SCHEMA.format(
        current_time=datetime.now(timezone.utc).isoformat()
    )

    headers = {
        "Authorization": f"Bearer {NVIDIA_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": NVIDIA_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"{schema_with_time}\n\nQuestion: {user_question}"}
        ],
        "temperature": 0.1,
        "max_tokens": 1024
    }

    try:
        response = requests.post(
            NVIDIA_API_URL,
            headers=headers,
            json=payload,
            timeout=30
        )

        if response.status_code != 200:
            logger.error(f"NVIDIA API error: {response.status_code} - {response.text[:500]}")
            return None, f"NVIDIA API error: {response.status_code}"

        data = response.json()
        content = data['choices'][0]['message']['content']

        # Parse JSON from response (may be wrapped in markdown code blocks)
        content = content.strip()
        if content.startswith('```'):
            # Remove ```json or ``` prefix
            lines = content.split('\n')
            content = '\n'.join(lines[1:])  # Skip first line
            if content.endswith('```'):
                content = content[:-3]  # Remove trailing ```
        content = content.strip()

        result = json.loads(content)
        return result, None

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse AI response as JSON: {e}")
        return None, f"Failed to parse AI response as JSON: {str(e)}"
    except requests.exceptions.Timeout:
        return None, "NVIDIA API timeout - try again"
    except requests.exceptions.RequestException as e:
        logger.error(f"NVIDIA API request error: {e}")
        return None, f"Network error: {str(e)}"
    except Exception as e:
        logger.error(f"Unexpected error in query_nvidia_llm: {e}")
        return None, f"Error: {str(e)}"


def validate_sql(sql):
    """
    Safety check - only allow SELECT queries.

    Args:
        sql: SQL query string

    Returns:
        Tuple of (is_safe, error_message)
    """
    sql_upper = sql.strip().upper()

    # Block dangerous keywords
    dangerous = ['DELETE', 'DROP', 'INSERT', 'UPDATE', 'ALTER', 'TRUNCATE',
                 'EXEC', 'EXECUTE', 'CREATE', 'GRANT', 'REVOKE']
    for word in dangerous:
        # Check for word as a separate token (not part of another word)
        if f' {word} ' in f' {sql_upper} ' or sql_upper.startswith(f'{word} '):
            return False, f"Blocked: {word} not allowed"

    if not sql_upper.startswith('SELECT'):
        return False, "Only SELECT queries allowed"

    return True, None


def run_query(sql):
    """
    Execute SQL query against the database and return results.

    Args:
        sql: SQL query string (must be SELECT only)

    Returns:
        Tuple of (result_dict, error_string)
        result_dict contains 'columns', 'rows', 'count' keys
    """
    safe, error = validate_sql(sql)
    if not safe:
        return None, error

    try:
        result = db.session.execute(db.text(sql))
        columns = list(result.keys())
        rows = []
        for row in result.fetchall():
            row_dict = {}
            for i, col in enumerate(columns):
                val = row[i]
                # Convert datetime to ISO string
                if isinstance(val, datetime):
                    val = val.isoformat()
                row_dict[col] = val
            rows.append(row_dict)

        return {'columns': columns, 'rows': rows, 'count': len(rows)}, None

    except Exception as e:
        logger.error(f"Query execution error: {e}")
        return None, f"Query error: {str(e)}"


def format_report(question, ai_result, query_result):
    """
    Send results back to NVIDIA LLM to format into a readable report.

    Args:
        question: Original user question
        ai_result: Dict with 'sql', 'explanation', 'format' from LLM
        query_result: Dict with 'columns', 'rows', 'count' from query

    Returns:
        Tuple of (report_string, error_string)
    """
    if not NVIDIA_API_KEY:
        return None, "NVIDIA_API_KEY not configured"

    # Truncate if too many rows to avoid token limits
    rows_for_formatting = query_result['rows'][:50]

    headers = {
        "Authorization": f"Bearer {NVIDIA_API_KEY}",
        "Content-Type": "application/json"
    }

    format_prompt = f"""The user asked: "{question}"

The SQL query returned these results:
Columns: {query_result['columns']}
Total rows: {query_result['count']}
Data (first 50 rows): {json.dumps(rows_for_formatting, default=str, indent=2)}

Format this data into a clean, professional report. Use:
- A brief summary sentence at the top
- A well-formatted markdown table if appropriate
- Key insights or callouts (e.g., "3 screens are offline", "Coca Cola ad played 12,450 times")
- If there are numbers, provide totals and averages where relevant
- Keep it concise but complete
- Use markdown formatting

Do NOT include the SQL query in your response. Just the formatted report."""

    payload = {
        "model": NVIDIA_MODEL,
        "messages": [
            {
                "role": "system",
                "content": "You are a professional data analyst. Format query results into clean, readable reports using markdown. Be concise and highlight key insights."
            },
            {"role": "user", "content": format_prompt}
        ],
        "temperature": 0.3,
        "max_tokens": 2048
    }

    try:
        response = requests.post(
            NVIDIA_API_URL,
            headers=headers,
            json=payload,
            timeout=30
        )

        if response.status_code == 200:
            data = response.json()
            report = data['choices'][0]['message']['content']
            return report, None
        else:
            return None, f"Format API error: {response.status_code}"

    except Exception as e:
        logger.error(f"Format error: {e}")
        return None, f"Format error: {str(e)}"


def ask_report(question):
    """
    Full pipeline: question -> SQL -> execute -> format -> report.

    Args:
        question: Natural language question from user

    Returns:
        Dict with keys:
        - question: Original question
        - report: Formatted markdown report
        - raw_data: Dict with columns, rows, count
        - sql: Generated SQL query
        - explanation: LLM's explanation of the query
        - error: Error message if any
    """
    result = {
        'question': question,
        'report': None,
        'raw_data': None,
        'sql': None,
        'explanation': None,
        'error': None,
    }

    # Step 1: Ask NVIDIA LLM to generate SQL
    ai_result, error = query_nvidia_llm(question)
    if error:
        result['error'] = error
        return result

    sql = ai_result.get('sql', '')
    result['sql'] = sql
    result['explanation'] = ai_result.get('explanation', '')

    # Step 2: Run the SQL query
    query_result, error = run_query(sql)
    if error:
        result['error'] = error
        return result

    result['raw_data'] = query_result

    # Step 3: Format into a report
    report, error = format_report(question, ai_result, query_result)
    if error:
        # Return raw data even if formatting fails
        result['error'] = f"Report formatting failed: {error}"
        result['report'] = f"Query returned {query_result['count']} rows. Raw data available for export."
        return result

    result['report'] = report
    return result


def get_quick_stats():
    """
    Get quick statistics for the dashboard without AI.

    Returns:
        Dict with various stats
    """
    try:
        from cms.models.device import Device
        from cms.models.heartbeat import Heartbeat
        from cms.models.playback_log import PlaybackLog
        from cms.models.alert import Alert
        from datetime import timedelta

        now = datetime.now(timezone.utc)
        five_mins_ago = now - timedelta(minutes=5)
        one_day_ago = now - timedelta(days=1)
        seven_days_ago = now - timedelta(days=7)

        # Device counts
        total_devices = Device.query.count()
        active_devices = Device.query.filter_by(status='active').count()

        # Recent heartbeats (online devices)
        recent_heartbeats = db.session.query(
            db.func.count(db.func.distinct(Heartbeat.device_id))
        ).filter(Heartbeat.timestamp >= five_mins_ago).scalar() or 0

        # Playback stats
        plays_today = PlaybackLog.query.filter(
            PlaybackLog.started_at >= one_day_ago
        ).count()
        plays_week = PlaybackLog.query.filter(
            PlaybackLog.started_at >= seven_days_ago
        ).count()

        # Alert stats
        unacked_alerts = Alert.query.filter_by(acknowledged=False).count()
        critical_alerts = Alert.query.filter(
            Alert.severity == 'critical',
            Alert.acknowledged == False
        ).count()

        return {
            'total_devices': total_devices,
            'active_devices': active_devices,
            'online_now': recent_heartbeats,
            'plays_today': plays_today,
            'plays_week': plays_week,
            'unacked_alerts': unacked_alerts,
            'critical_alerts': critical_alerts,
        }

    except Exception as e:
        logger.error(f"Error getting quick stats: {e}")
        return {}

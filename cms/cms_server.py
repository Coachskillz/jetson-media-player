"""
Jetson Media Player CMS - Version 1
Minimal working CMS with dashboard
"""

from flask import Flask, render_template, jsonify
import sqlite3
from datetime import datetime

app = Flask(__name__)
app.config['DATABASE'] = 'cms.db'


def get_db():
    """Get database connection."""
    db = sqlite3.connect(app.config['DATABASE'])
    db.row_factory = sqlite3.Row
    return db


def init_db():
    """Initialize database."""
    db = get_db()
    db.execute('''
        CREATE TABLE IF NOT EXISTS devices (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            location TEXT,
            last_seen TIMESTAMP
        )
    ''')
    db.commit()


# Initialize database on startup
with app.app_context():
    init_db()


@app.route('/')
def index():
    """Dashboard."""
    db = get_db()
    device_count = db.execute('SELECT COUNT(*) as count FROM devices').fetchone()['count']
    
    return render_template('dashboard.html', device_count=device_count)


@app.route('/api/test')
def test_api():
    """Test API endpoint."""
    return jsonify({
        "status": "ok",
        "message": "CMS is working!",
        "timestamp": datetime.now().isoformat()
    })


if __name__ == '__main__':
    print("=" * 60)
    print("🎬 Jetson Media Player CMS")
    print("=" * 60)
    print("Starting server...")
    print("Open browser: http://localhost:5001")
    print("Press Ctrl+C to stop")
    print("=" * 60)
    app.run(debug=True, host='0.0.0.0', port=5001)

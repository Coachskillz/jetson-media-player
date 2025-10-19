"""
Jetson Media Player CMS - Complete with Video Preview
"""

from flask import Flask, render_template, jsonify, request, send_from_directory
from werkzeug.utils import secure_filename
import sqlite3
import os
from datetime import datetime

app = Flask(__name__)

app.config['DATABASE'] = 'cms.db'
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024
ALLOWED_EXTENSIONS = {'mp4', 'avi', 'mov', 'mkv', 'webm'}

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def get_db():
    db = sqlite3.connect(app.config['DATABASE'])
    db.row_factory = sqlite3.Row
    return db


def init_db():
    db = get_db()
    db.executescript('''
        CREATE TABLE IF NOT EXISTS devices (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            location TEXT,
            last_seen TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS content (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            title TEXT NOT NULL,
            duration REAL DEFAULT 30.0,
            file_size INTEGER,
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    ''')
    db.commit()
    print("✅ Database initialized")


with app.app_context():
    init_db()


@app.route('/')
def index():
    db = get_db()
    device_count = db.execute('SELECT COUNT(*) as count FROM devices').fetchone()['count']
    content_count = db.execute('SELECT COUNT(*) as count FROM content').fetchone()['count']
    return render_template('dashboard.html', device_count=device_count, content_count=content_count)


@app.route('/content')
def content_page():
    db = get_db()
    content = db.execute('SELECT * FROM content ORDER BY uploaded_at DESC').fetchall()
    return render_template('content.html', content=content)


@app.route('/devices')
def devices_page():
    db = get_db()
    devices = db.execute('SELECT * FROM devices ORDER BY last_seen DESC').fetchall()
    return render_template('devices.html', devices=devices)


@app.route('/cms/uploads/<filename>')
def serve_upload(filename):
    """Serve uploaded video files for preview."""
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


@app.route('/api/test')
def test_api():
    return jsonify({"status": "ok", "message": "CMS is working!", "timestamp": datetime.now().isoformat()})


@app.route('/api/v1/register', methods=['POST'])
def register_device():
    data = request.json
    device_id = data.get('device_id')
    device_name = data.get('name', f'Device-{device_id[:8]}')
    location = data.get('location', 'Unknown')
    
    db = get_db()
    existing = db.execute('SELECT * FROM devices WHERE id = ?', (device_id,)).fetchone()
    
    if existing:
        db.execute('UPDATE devices SET last_seen = ? WHERE id = ?', (datetime.now(), device_id))
        db.commit()
        return jsonify({"status": "existing", "device_id": device_id, "message": "Device already registered"})
    
    db.execute('INSERT INTO devices (id, name, location, last_seen) VALUES (?, ?, ?, ?)',
               (device_id, device_name, location, datetime.now()))
    db.commit()
    return jsonify({"status": "registered", "device_id": device_id, "message": "Device successfully registered"})


@app.route('/api/v1/device/<device_id>/config')
def get_device_config(device_id):
    db = get_db()
    device = db.execute('SELECT * FROM devices WHERE id = ?', (device_id,)).fetchone()
    
    if not device:
        return jsonify({"error": "Device not found"}), 404
    
    db.execute('UPDATE devices SET last_seen = ? WHERE id = ?', (datetime.now(), device_id))
    db.commit()
    
    return jsonify({
        "device_id": device['id'],
        "name": device['name'],
        "location": device['location'],
        "last_seen": device['last_seen']
    })


@app.route('/api/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400
    
    file = request.files['file']
    title = request.form.get('title', file.filename)
    duration = float(request.form.get('duration', 30.0))
    
    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400
    
    if not allowed_file(file.filename):
        return jsonify({"error": "File type not allowed"}), 400
    
    filename = secure_filename(file.filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)
    
    file_size = os.path.getsize(filepath)
    
    db = get_db()
    cursor = db.execute('INSERT INTO content (filename, title, duration, file_size) VALUES (?, ?, ?, ?)',
                       (filename, title, duration, file_size))
    db.commit()
    
    return jsonify({"status": "ok", "content_id": cursor.lastrowid, "filename": filename, "title": title})


@app.route('/api/content')
def list_content():
    db = get_db()
    content = db.execute('SELECT * FROM content ORDER BY uploaded_at DESC').fetchall()
    return jsonify([dict(c) for c in content])


@app.route('/api/devices')
def list_devices():
    db = get_db()
    devices = db.execute('SELECT * FROM devices ORDER BY last_seen DESC').fetchall()
    return jsonify([dict(d) for d in devices])


if __name__ == '__main__':
    print("=" * 60)
    print("🎬 Jetson Media Player CMS")
    print("=" * 60)
    print("Dashboard:  http://localhost:5001")
    print("Content:    http://localhost:5001/content")
    print("Devices:    http://localhost:5001/devices")
    print("=" * 60)
    app.run(debug=True, host='0.0.0.0', port=5001)

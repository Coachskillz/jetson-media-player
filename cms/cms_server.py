"""
Jetson Media Player CMS - Complete with Playlists
"""

from flask import Flask, render_template, jsonify, request, send_from_directory
from werkzeug.utils import secure_filename
import sqlite3
import os
import json
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
            pairing_code TEXT,
            paired INTEGER DEFAULT 0,
            mac_address TEXT,
            playlist_id INTEGER,
            last_seen TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (playlist_id) REFERENCES playlists (id)
        );
        
        CREATE TABLE IF NOT EXISTS content (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            title TEXT NOT NULL,
            duration REAL DEFAULT 30.0,
            file_size INTEGER,
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS playlists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS playlist_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            playlist_id INTEGER NOT NULL,
            content_id INTEGER NOT NULL,
            triggers TEXT NOT NULL,
            position INTEGER DEFAULT 0,
            FOREIGN KEY (playlist_id) REFERENCES playlists (id),
            FOREIGN KEY (content_id) REFERENCES content (id)
        );
    ''')
    db.commit()
    print("✅ Database initialized with playlists support")


with app.app_context():
    init_db()


@app.route('/')
def index():
    db = get_db()
    device_count = db.execute('SELECT COUNT(*) as count FROM devices').fetchone()['count']
    content_count = db.execute('SELECT COUNT(*) as count FROM content').fetchone()['count']
    playlist_count = db.execute('SELECT COUNT(*) as count FROM playlists').fetchone()['count']
    return render_template('dashboard.html', 
                         device_count=device_count, 
                         content_count=content_count,
                         playlist_count=playlist_count)


@app.route('/content')
def content_page():
    db = get_db()
    content = db.execute('SELECT * FROM content ORDER BY uploaded_at DESC').fetchall()
    return render_template('content.html', content=content)


@app.route('/devices')
def devices_page():
    db = get_db()
    devices = db.execute('''
        SELECT d.*, p.name as playlist_name 
        FROM devices d 
        LEFT JOIN playlists p ON d.playlist_id = p.id
        ORDER BY d.last_seen DESC
    ''').fetchall()
    playlists = db.execute('SELECT * FROM playlists ORDER BY name').fetchall()
    return render_template('devices.html', devices=devices, playlists=playlists)


@app.route('/playlists')
def playlists_page():
    db = get_db()
    playlists = db.execute('SELECT * FROM playlists ORDER BY created_at DESC').fetchall()
    content = db.execute('SELECT * FROM content ORDER BY title').fetchall()
    return render_template('playlists.html', playlists=playlists, content=content)


@app.route('/cms/uploads/<filename>')
def serve_upload(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


@app.route('/api/test')
def test_api():
    return jsonify({"status": "ok", "message": "CMS is working!", "timestamp": datetime.now().isoformat()})


@app.route('/api/v1/pairing/request', methods=['POST'])
def request_pairing():
    data = request.json
    device_id = data.get('device_id')
    pairing_code = data.get('pairing_code')
    device_name = data.get('name', f'Device-{device_id[:8]}')
    mac_address = data.get('mac_address', 'unknown')
    
    db = get_db()
    existing = db.execute('SELECT * FROM devices WHERE id = ?', (device_id,)).fetchone()
    
    if existing:
        if existing['paired'] == 1:
            return jsonify({"status": "already_paired", "message": "Device already paired"})
        db.execute('UPDATE devices SET pairing_code = ?, last_seen = ? WHERE id = ?',
                  (pairing_code, datetime.now(), device_id))
    else:
        db.execute('''
            INSERT INTO devices (id, name, pairing_code, paired, mac_address, last_seen)
            VALUES (?, ?, ?, 0, ?, ?)
        ''', (device_id, device_name, pairing_code, mac_address, datetime.now()))
    
    db.commit()
    return jsonify({"status": "pending", "pairing_code": pairing_code, "message": "Waiting for approval"})


@app.route('/api/v1/pairing/status/<device_id>')
def pairing_status(device_id):
    db = get_db()
    device = db.execute('SELECT * FROM devices WHERE id = ?', (device_id,)).fetchone()
    
    if not device:
        return jsonify({"paired": False, "message": "Device not found"})
    
    return jsonify({
        "paired": device['paired'] == 1,
        "device_id": device_id,
        "name": device['name']
    })


@app.route('/api/admin/pairing/approve', methods=['POST'])
def approve_pairing():
    data = request.json
    pairing_code = data.get('pairing_code')
    location = data.get('location', 'Unknown')
    
    db = get_db()
    device = db.execute('SELECT * FROM devices WHERE pairing_code = ? AND paired = 0', 
                       (pairing_code,)).fetchone()
    
    if not device:
        return jsonify({"error": "Invalid pairing code"}), 404
    
    db.execute('UPDATE devices SET paired = 1, location = ? WHERE id = ?',
               (location, device['id']))
    db.commit()
    
    return jsonify({
        "status": "ok",
        "device_id": device['id'],
        "name": device['name'],
        "message": "Device paired successfully"
    })


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
        "playlist_id": device['playlist_id'],
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


@app.route('/api/playlists', methods=['GET'])
def list_playlists():
    db = get_db()
    playlists = db.execute('SELECT * FROM playlists ORDER BY created_at DESC').fetchall()
    return jsonify([dict(p) for p in playlists])


@app.route('/api/playlists', methods=['POST'])
def create_playlist():
    data = request.json
    name = data.get('name')
    description = data.get('description', '')
    
    db = get_db()
    cursor = db.execute('INSERT INTO playlists (name, description) VALUES (?, ?)',
                       (name, description))
    db.commit()
    
    return jsonify({"status": "ok", "playlist_id": cursor.lastrowid, "name": name})


@app.route('/api/playlists/<int:playlist_id>/items', methods=['GET'])
def get_playlist_items(playlist_id):
    db = get_db()
    items = db.execute('''
        SELECT pi.*, c.title, c.filename, c.duration
        FROM playlist_items pi
        JOIN content c ON pi.content_id = c.id
        WHERE pi.playlist_id = ?
        ORDER BY pi.position
    ''', (playlist_id,)).fetchall()
    return jsonify([dict(i) for i in items])


@app.route('/api/playlists/<int:playlist_id>/items', methods=['POST'])
def add_playlist_item(playlist_id):
    data = request.json
    content_id = data.get('content_id')
    triggers = data.get('triggers', [])
    
    db = get_db()
    cursor = db.execute('''
        INSERT INTO playlist_items (playlist_id, content_id, triggers)
        VALUES (?, ?, ?)
    ''', (playlist_id, content_id, json.dumps(triggers)))
    db.commit()
    
    return jsonify({"status": "ok", "item_id": cursor.lastrowid})


@app.route('/api/devices/<device_id>/playlist', methods=['PUT'])
def assign_playlist_to_device(device_id):
    data = request.json
    playlist_id = data.get('playlist_id')
    
    db = get_db()
    db.execute('UPDATE devices SET playlist_id = ? WHERE id = ?', (playlist_id, device_id))
    db.commit()
    
    return jsonify({"status": "ok", "device_id": device_id, "playlist_id": playlist_id})


if __name__ == '__main__':
    print("=" * 60)
    print("🎬 Jetson Media Player CMS")
    print("=" * 60)
    print("Dashboard:  http://localhost:5001")
    print("Content:    http://localhost:5001/content")
    print("Devices:    http://localhost:5001/devices")
    print("Playlists:  http://localhost:5001/playlists")
    print("=" * 60)
    app.run(debug=True, host='0.0.0.0', port=5001)

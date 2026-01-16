"""
Skillz Media Screens CMS - Complete System with Locations
"""

from flask import Flask, render_template, jsonify, request, send_from_directory
from werkzeug.utils import secure_filename
import sqlite3
import os
import json
from datetime import datetime
import subprocess

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


def get_video_duration(filepath):
    """Extract video duration using ffprobe if available, otherwise return None"""
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', 
             '-of', 'default=noprint_wrappers=1:nokey=1', filepath],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10
        )
        duration = float(result.stdout.strip())
        return round(duration, 2)
    except Exception as e:
        print(f"Could not extract duration with ffprobe: {e}")
        return None


def init_db():
    db = get_db()
    db.executescript('''
        CREATE TABLE IF NOT EXISTS locations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            address TEXT,
            icon TEXT DEFAULT '📍',
            color TEXT DEFAULT '#667eea',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS devices (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            location_id INTEGER,
            pairing_code TEXT,
            paired INTEGER DEFAULT 0,
            mac_address TEXT,
            last_seen TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (location_id) REFERENCES locations (id)
        );
        
        CREATE TABLE IF NOT EXISTS folders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            color TEXT DEFAULT '#667eea',
            icon TEXT DEFAULT '📁',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS content (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            title TEXT NOT NULL,
            duration REAL DEFAULT 30.0,
            file_size INTEGER,
            folder_id INTEGER,
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (folder_id) REFERENCES folders (id)
        );
        
        CREATE TABLE IF NOT EXISTS playlists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            trigger_type TEXT DEFAULT 'default',
            trigger_value TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS playlist_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            playlist_id INTEGER NOT NULL,
            content_id INTEGER NOT NULL,
            position INTEGER DEFAULT 0,
            FOREIGN KEY (playlist_id) REFERENCES playlists (id),
            FOREIGN KEY (content_id) REFERENCES content (id)
        );
        
        CREATE TABLE IF NOT EXISTS device_playlists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL,
            playlist_id INTEGER NOT NULL,
            FOREIGN KEY (device_id) REFERENCES devices (id),
            FOREIGN KEY (playlist_id) REFERENCES playlists (id)
        );
    ''')
    
    db.commit()
    print("✅ Database initialized - Locations & Folders ready!")


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
    content = db.execute('''
        SELECT c.*, f.name as folder_name, f.color as folder_color, f.icon as folder_icon
        FROM content c
        LEFT JOIN folders f ON c.folder_id = f.id
        ORDER BY c.uploaded_at DESC
    ''').fetchall()
    folders = db.execute('SELECT * FROM folders ORDER BY name').fetchall()
    return render_template('content.html', content=content, folders=folders)


@app.route('/devices')
def devices_page():
    db = get_db()
    devices = db.execute('''
        SELECT d.*, l.name as location_name, l.icon as location_icon, l.color as location_color
        FROM devices d
        LEFT JOIN locations l ON d.location_id = l.id
        ORDER BY d.last_seen DESC
    ''').fetchall()
    playlists = db.execute('SELECT * FROM playlists ORDER BY name').fetchall()
    locations = db.execute('SELECT * FROM locations ORDER BY name').fetchall()
    
    device_list = []
    for device in devices:
        device_dict = dict(device)
        assigned = db.execute('''
            SELECT p.id, p.name, p.trigger_type, p.trigger_value
            FROM device_playlists dp 
            JOIN playlists p ON dp.playlist_id = p.id 
            WHERE dp.device_id = ?
        ''', (device['id'],)).fetchall()
        device_dict['assigned_playlists'] = [dict(a) for a in assigned]
        device_list.append(device_dict)
    
    return render_template('devices.html', devices=device_list, playlists=playlists, locations=locations)


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


# ============= LOCATION MANAGEMENT =============

@app.route('/api/locations', methods=['GET'])
def list_locations():
    db = get_db()
    locations = db.execute('SELECT * FROM locations ORDER BY name').fetchall()
    return jsonify([dict(l) for l in locations])


@app.route('/api/locations', methods=['POST'])
def create_location():
    data = request.json
    name = data.get('name')
    address = data.get('address', '')
    icon = data.get('icon', '📍')
    color = data.get('color', '#667eea')
    
    if not name:
        return jsonify({"error": "Location name required"}), 400
    
    db = get_db()
    try:
        cursor = db.execute('''
            INSERT INTO locations (name, address, icon, color) 
            VALUES (?, ?, ?, ?)
        ''', (name, address, icon, color))
        db.commit()
        return jsonify({"status": "ok", "location_id": cursor.lastrowid, "name": name})
    except sqlite3.IntegrityError:
        return jsonify({"error": "Location name already exists"}), 400


@app.route('/api/locations/<int:location_id>', methods=['DELETE'])
def delete_location(location_id):
    db = get_db()
    
    # Set devices to no location
    db.execute('UPDATE devices SET location_id = NULL WHERE location_id = ?', (location_id,))
    
    db.execute('DELETE FROM locations WHERE id = ?', (location_id,))
    db.commit()
    return jsonify({"status": "ok"})


# ============= FOLDER MANAGEMENT =============

@app.route('/api/folders', methods=['GET'])
def list_folders():
    db = get_db()
    folders = db.execute('SELECT * FROM folders ORDER BY name').fetchall()
    return jsonify([dict(f) for f in folders])


@app.route('/api/folders', methods=['POST'])
def create_folder():
    data = request.json
    name = data.get('name')
    color = data.get('color', '#667eea')
    icon = data.get('icon', '📁')
    
    if not name:
        return jsonify({"error": "Folder name required"}), 400
    
    db = get_db()
    try:
        cursor = db.execute('''
            INSERT INTO folders (name, color, icon) 
            VALUES (?, ?, ?)
        ''', (name, color, icon))
        db.commit()
        return jsonify({"status": "ok", "folder_id": cursor.lastrowid, "name": name})
    except sqlite3.IntegrityError:
        return jsonify({"error": "Folder name already exists"}), 400


@app.route('/api/folders/<int:folder_id>', methods=['DELETE'])
def delete_folder(folder_id):
    db = get_db()
    
    # Set content to no folder
    db.execute('UPDATE content SET folder_id = NULL WHERE folder_id = ?', (folder_id,))
    
    db.execute('DELETE FROM folders WHERE id = ?', (folder_id,))
    db.commit()
    return jsonify({"status": "ok"})


# ============= CONTENT MANAGEMENT =============

@app.route('/api/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400
    
    file = request.files['file']
    title = request.form.get('title', file.filename)
    folder_id = request.form.get('folder_id', None)
    
    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400
    
    if not allowed_file(file.filename):
        return jsonify({"error": "File type not allowed"}), 400
    
    filename = secure_filename(file.filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)
    
    file_size = os.path.getsize(filepath)
    
    # Auto-detect duration
    duration = get_video_duration(filepath)
    if duration is None:
        duration = 30.0  # Default fallback
    
    db = get_db()
    
    cursor = db.execute('''
        INSERT INTO content (filename, title, duration, file_size, folder_id) 
        VALUES (?, ?, ?, ?, ?)
    ''', (filename, title, duration, file_size, folder_id if folder_id else None))
    db.commit()
    
    return jsonify({
        "status": "ok", 
        "content_id": cursor.lastrowid, 
        "filename": filename, 
        "title": title,
        "duration": duration
    })


@app.route('/api/content')
def list_content():
    db = get_db()
    folder_id = request.args.get('folder_id', None)
    
    if folder_id:
        content = db.execute('''
            SELECT c.*, f.name as folder_name, f.color as folder_color 
            FROM content c
            LEFT JOIN folders f ON c.folder_id = f.id
            WHERE c.folder_id = ?
            ORDER BY c.uploaded_at DESC
        ''', (folder_id,)).fetchall()
    else:
        content = db.execute('''
            SELECT c.*, f.name as folder_name, f.color as folder_color 
            FROM content c
            LEFT JOIN folders f ON c.folder_id = f.id
            ORDER BY c.uploaded_at DESC
        ''').fetchall()
    
    return jsonify([dict(c) for c in content])


@app.route('/api/content/<int:content_id>/move', methods=['PUT'])
def move_content(content_id):
    data = request.json
    folder_id = data.get('folder_id')
    
    db = get_db()
    db.execute('UPDATE content SET folder_id = ? WHERE id = ?', (folder_id, content_id))
    db.commit()
    
    return jsonify({"status": "ok"})


# ============= DEVICE MANAGEMENT =============

@app.route('/api/devices')
def list_devices():
    db = get_db()
    devices = db.execute('''
        SELECT d.*, l.name as location_name, l.icon as location_icon, l.color as location_color
        FROM devices d
        LEFT JOIN locations l ON d.location_id = l.id
        ORDER BY d.last_seen DESC
    ''').fetchall()
    return jsonify([dict(d) for d in devices])


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
    location_id = data.get('location_id', None)
    
    db = get_db()
    device = db.execute('SELECT * FROM devices WHERE pairing_code = ? AND paired = 0', 
                       (pairing_code,)).fetchone()
    
    if not device:
        return jsonify({"error": "Invalid pairing code"}), 404
    
    db.execute('UPDATE devices SET paired = 1, location_id = ? WHERE id = ?',
               (location_id, device['id']))
    db.commit()
    
    return jsonify({
        "status": "ok",
        "device_id": device['id'],
        "name": device['name'],
        "message": "Device paired successfully"
    })


@app.route('/api/devices/<device_id>/location', methods=['PUT'])
def update_device_location(device_id):
    data = request.json
    location_id = data.get('location_id')
    
    db = get_db()
    db.execute('UPDATE devices SET location_id = ? WHERE id = ?', (location_id, device_id))
    db.commit()
    
    return jsonify({"status": "ok"})


@app.route('/api/v1/device/<device_id>/config')
def get_device_config(device_id):
    db = get_db()
    device = db.execute('SELECT * FROM devices WHERE id = ?', (device_id,)).fetchone()
    
    if not device:
        return jsonify({"error": "Device not found"}), 404
    
    db.execute('UPDATE devices SET last_seen = ? WHERE id = ?', (datetime.now(), device_id))
    db.commit()
    
    assigned = db.execute('''
        SELECT p.id, p.name, p.trigger_type, p.trigger_value
        FROM device_playlists dp
        JOIN playlists p ON dp.playlist_id = p.id
        WHERE dp.device_id = ?
    ''', (device_id,)).fetchall()
    
    location = db.execute('''
        SELECT l.name, l.address FROM locations l
        JOIN devices d ON d.location_id = l.id
        WHERE d.id = ?
    ''', (device_id,)).fetchone()
    
    return jsonify({
        "device_id": device['id'],
        "name": device['name'],
        "location": dict(location) if location else None,
        "playlists": [dict(a) for a in assigned],
        "last_seen": device['last_seen']
    })


@app.route('/api/devices/<device_id>/assign-playlist', methods=['POST'])
def assign_playlist_to_device(device_id):
    data = request.json
    playlist_id = data.get('playlist_id')
    
    db = get_db()
    
    existing = db.execute('''
        SELECT * FROM device_playlists 
        WHERE device_id = ? AND playlist_id = ?
    ''', (device_id, playlist_id)).fetchone()
    
    if not existing:
        db.execute('''
            INSERT INTO device_playlists (device_id, playlist_id)
            VALUES (?, ?)
        ''', (device_id, playlist_id))
        db.commit()
    
    return jsonify({"status": "ok", "device_id": device_id, "playlist_id": playlist_id})


# ============= PLAYLIST MANAGEMENT =============

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
    trigger_type = data.get('trigger_type', 'default')
    trigger_value = data.get('trigger_value', '')
    
    db = get_db()
    cursor = db.execute('''
        INSERT INTO playlists (name, description, trigger_type, trigger_value) 
        VALUES (?, ?, ?, ?)
    ''', (name, description, trigger_type, trigger_value))
    db.commit()
    
    return jsonify({"status": "ok", "playlist_id": cursor.lastrowid, "name": name})


@app.route('/api/playlists/<int:playlist_id>', methods=['PUT'])
def update_playlist(playlist_id):
    data = request.json
    trigger_type = data.get('trigger_type')
    trigger_value = data.get('trigger_value', '')
    
    db = get_db()
    db.execute('''
        UPDATE playlists 
        SET trigger_type = ?, trigger_value = ?
        WHERE id = ?
    ''', (trigger_type, trigger_value, playlist_id))
    db.commit()
    
    return jsonify({"status": "ok", "playlist_id": playlist_id})


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
    
    db = get_db()
    cursor = db.execute('''
        INSERT INTO playlist_items (playlist_id, content_id)
        VALUES (?, ?)
    ''', (playlist_id, content_id))
    db.commit()
    
    return jsonify({"status": "ok", "item_id": cursor.lastrowid})


if __name__ == '__main__':
    print("=" * 60)
    print("🎬 Skillz Media Screens CMS")
    print("=" * 60)
    print("Dashboard:  http://localhost:5001")
    print("Content:    http://localhost:5001/content")
    print("Devices:    http://localhost:5001/devices")
    print("Playlists:  http://localhost:5001/playlists")
    print("=" * 60)
    print("✨ Features: Locations, Folders, Auto-duration, Triggers")
    print("=" * 60)
    app.run(debug=True, host='0.0.0.0', port=5001)

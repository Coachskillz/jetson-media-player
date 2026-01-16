"""
CMS Web UI Routes

Blueprint for web page rendering:
- GET /: Dashboard
- GET /devices: Device management page
- GET /hubs: Hub management page
- GET /content: Content management page
- GET /playlists: Playlist management page
"""

from flask import Blueprint, render_template, abort

from cms.models import db, Device, Hub, Content, Playlist, Network, DeviceAssignment
from cms.models.device_assignment import TRIGGER_TYPES


# Create web blueprint (no url_prefix since these are root-level pages)
web_bp = Blueprint('web', __name__)


@web_bp.route('/')
def dashboard():
    """
    Dashboard page showing system overview.

    Displays counts of devices, hubs, content items, and playlists
    for a quick system status overview.

    Returns:
        Rendered dashboard.html template with stats
    """
    device_count = Device.query.count()
    hub_count = Hub.query.count()
    content_count = Content.query.count()
    playlist_count = Playlist.query.count()
    network_count = Network.query.count()

    return render_template(
        'dashboard.html',
        active_page='dashboard',
        device_count=device_count,
        hub_count=hub_count,
        content_count=content_count,
        playlist_count=playlist_count,
        network_count=network_count
    )


@web_bp.route('/devices')
def devices_page():
    """
    Device management page.

    Lists all registered devices with their details including:
    - Device ID (SKZ-D-XXXX or SKZ-H-CODE-XXXX format)
    - Name, status, mode
    - Associated hub and network
    - Last seen timestamp

    Returns:
        Rendered devices.html template with device list
    """
    devices = Device.query.order_by(Device.created_at.desc()).all()
    hubs = Hub.query.order_by(Hub.name).all()
    networks = Network.query.order_by(Network.name).all()
    playlists = Playlist.query.filter_by(is_active=True).order_by(Playlist.name).all()

    return render_template(
        'devices.html',
        active_page='devices',
        devices=devices,
        hubs=hubs,
        networks=networks,
        playlists=playlists
    )


@web_bp.route('/hubs')
def hubs_page():
    """
    Hub management page.

    Lists all registered hubs with their details including:
    - Hub code and name
    - Associated network
    - Connected device count
    - Status

    Returns:
        Rendered hubs.html template with hub list
    """
    hubs = Hub.query.order_by(Hub.created_at.desc()).all()
    networks = Network.query.order_by(Network.name).all()

    # Enrich hubs with device count
    hub_list = []
    for hub in hubs:
        hub_data = {
            'hub': hub,
            'device_count': Device.query.filter_by(hub_id=hub.id).count()
        }
        hub_list.append(hub_data)

    return render_template(
        'hubs.html',
        active_page='hubs',
        hubs=hub_list,
        networks=networks
    )


@web_bp.route('/content')
def content_page():
    """
    Content management page with 16:9 aspect ratio preview.

    Lists all uploaded content with metadata and preview capabilities:
    - Filename and original name
    - File size and MIME type
    - Dimensions and duration (for video)
    - Network association

    Returns:
        Rendered content.html template with content list
    """
    content_items = Content.query.order_by(Content.created_at.desc()).all()
    networks = Network.query.order_by(Network.name).all()

    # Enrich content with template-expected fields
    content = []
    for item in content_items:
        content.append({
            'id': item.id,
            'filename': item.filename,
            'title': item.original_name,  # Template expects 'title'
            'duration': item.duration or 0,
            'file_size': item.file_size,
            'mime_type': item.mime_type,
            'folder_id': None,  # No folder support yet
            'folder_name': None,
            'folder_color': None,
            'folder_icon': None,
        })

    return render_template(
        'content.html',
        active_page='content',
        content=content,
        networks=networks,
        folders=[]  # Empty folders list for now
    )


@web_bp.route('/playlists')
def playlists_page():
    """
    Playlist management page with trigger configuration.

    Lists all playlists with their details including:
    - Name and description
    - Trigger type and configuration
    - Item count
    - Active status

    Also provides content list for adding items to playlists.

    Returns:
        Rendered playlists.html template with playlist and content lists
    """
    playlists = Playlist.query.order_by(Playlist.created_at.desc()).all()
    content = Content.query.order_by(Content.original_name).all()
    networks = Network.query.order_by(Network.name).all()

    return render_template(
        'playlists.html',
        active_page='playlists',
        playlists=playlists,
        content=content,
        networks=networks
    )


@web_bp.route('/devices/<device_id>')
def device_detail_page(device_id):
    """
    Device detail page with camera controls and playlist management.

    Shows detailed device information including:
    - Device status and metadata
    - Camera 1 settings (demographics, loyalty recognition)
    - Camera 2 settings (NCMEC detection)
    - Assigned playlists with triggers

    Args:
        device_id: Device ID (can be UUID or SKZ-X-XXXX format)

    Returns:
        Rendered device_detail.html template with device data
    """
    # Try to find device by device_id (SKZ format) first, then by UUID
    device = Device.query.filter_by(device_id=device_id).first()
    if not device:
        device = db.session.get(Device, device_id)

    if not device:
        abort(404)

    # Get playlist assignments
    assignments = DeviceAssignment.query.filter_by(device_id=device.id).all()
    device_playlists = []
    for assignment in assignments:
        if assignment.playlist:
            device_playlists.append({
                'assignment_id': assignment.id,
                'playlist_id': assignment.playlist.id,
                'playlist_name': assignment.playlist.name,
                'trigger_type': assignment.trigger_type,
                'priority': assignment.priority
            })

    # Get all available playlists for assignment dropdown
    all_playlists = Playlist.query.filter_by(is_active=True).order_by(Playlist.name).all()

    # Trigger type info for the UI
    trigger_info = [
        {'value': 'default', 'label': 'Default', 'description': 'Always plays (fallback content)', 'icon': '📺'},
        {'value': 'face_detected', 'label': 'Face Detected', 'description': 'Plays when any face is detected', 'icon': '👤'},
        {'value': 'age_child', 'label': 'Age: Child', 'description': 'Plays for children (0-12)', 'icon': '👶'},
        {'value': 'age_teen', 'label': 'Age: Teen', 'description': 'Plays for teens (13-19)', 'icon': '🧑'},
        {'value': 'age_adult', 'label': 'Age: Adult', 'description': 'Plays for adults (20-64)', 'icon': '👨'},
        {'value': 'age_senior', 'label': 'Age: Senior', 'description': 'Plays for seniors (65+)', 'icon': '👴'},
        {'value': 'gender_male', 'label': 'Gender: Male', 'description': 'Plays for male viewers', 'icon': '♂️'},
        {'value': 'gender_female', 'label': 'Gender: Female', 'description': 'Plays for female viewers', 'icon': '♀️'},
        {'value': 'loyalty_recognized', 'label': 'Loyalty Member', 'description': 'Plays for loyalty members', 'icon': '⭐'},
        {'value': 'ncmec_alert', 'label': 'NCMEC Alert', 'description': 'Plays during NCMEC alert', 'icon': '🚨'},
    ]

    return render_template(
        'device_detail.html',
        active_page='devices',
        device=device,
        device_playlists=device_playlists,
        all_playlists=all_playlists,
        trigger_types=trigger_info
    )

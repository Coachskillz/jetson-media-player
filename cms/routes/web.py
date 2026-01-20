"""
CMS Web UI Routes

Blueprint for web page rendering:
- GET /: Dashboard
- GET /devices: Device management page
- GET /hubs: Hub management page
- GET /content: Content management page
- GET /playlists: Playlist management page
"""

from flask import Blueprint, render_template, abort, redirect, url_for, request, flash, jsonify, send_from_directory, current_app
from flask_login import login_required

from cms.models import db, Device, Hub, Content, Playlist, Network, DeviceAssignment, Folder
from cms.routes.locations import Location
from cms.models.device_assignment import TRIGGER_TYPES
from cms.models.synced_content import SyncedContent
from cms.services.content_sync_service import ContentSyncService


# Create web blueprint (no url_prefix since these are root-level pages)
web_bp = Blueprint('web', __name__)



@web_bp.route("/cms/uploads/<filename>")
def serve_upload(filename):
    """Serve uploaded content files."""
    uploads_path = current_app.config.get("UPLOADS_PATH", "./uploads")
    return send_from_directory(uploads_path, filename)
@web_bp.route('/')
@login_required
def dashboard():
    """
    Dashboard page showing system overview.

    Displays:
    - System health/alerts
    - Networks with their screens
    - Screen layouts and current content

    Returns:
        Rendered dashboard.html template with data
    """
    from cms.models.layout import ScreenLayout

    # Get all networks with their devices
    networks = Network.query.order_by(Network.name).all()

    # Build network data with screens
    network_data = []
    system_alerts = []
    total_screens = 0
    online_screens = 0

    for network in networks:
        devices = Device.query.filter_by(network_id=network.id).filter(Device.status != 'pending').all()
        screen_list = []

        for device in devices:
            total_screens += 1
            if device.status == 'active':
                online_screens += 1
            elif device.status == 'offline':
                system_alerts.append({
                    'type': 'warning',
                    'message': f'Screen "{device.name or device.device_id}" is offline',
                    'device_id': device.device_id
                })

            # Get layout info
            layout = None
            if device.layout_id:
                layout = db.session.get(ScreenLayout, device.layout_id)

            # Get current playlist (first assignment)
            current_playlist = None
            assignment = DeviceAssignment.query.filter_by(device_id=device.id).first()
            if assignment and assignment.playlist:
                current_playlist = assignment.playlist.name

            screen_list.append({
                'id': device.id,
                'device_id': device.device_id,
                'name': device.name or device.device_id,
                'status': device.status,
                'last_seen': device.last_seen,
                'layout_name': layout.name if layout else 'No layout',
                'layout_id': device.layout_id,
                'current_playlist': current_playlist or 'No playlist',
                'description': f'{device.mode} mode'
            })

        network_data.append({
            'id': network.id,
            'name': network.name,
            'description': getattr(network, 'description', None),
            'screen_count': len(screen_list),
            'online_count': sum(1 for s in screen_list if s['status'] == 'active'),
            'screens': screen_list
        })

    # System health summary
    system_health = {
        'status': 'healthy' if not system_alerts else 'warning',
        'total_screens': total_screens,
        'online_screens': online_screens,
        'offline_screens': total_screens - online_screens,
        'alerts': system_alerts
    }

    # Get all hubs for pairing
    hubs = Hub.query.order_by(Hub.name).all()

    return render_template(
        'dashboard.html',
        active_page='dashboard',
        networks=network_data,
        hubs=hubs,
        system_health=system_health
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

    Supports filtering by hub via ?hub=<hub_id> query parameter.

    Returns:
        Rendered devices.html template with device list
    """
    from cms.models.layout import ScreenLayout

    # Check for hub filter
    hub_filter = request.args.get('hub')
    filtered_hub = None

    if hub_filter:
        filtered_hub = Hub.query.get(hub_filter)

    devices = Device.query.filter(Device.status != 'pending').order_by(Device.created_at.desc()).all()
    hubs = Hub.query.order_by(Hub.name).all()
    playlists = Playlist.query.filter_by(is_active=True).order_by(Playlist.name).all()
    locations = Location.query.all()

    # If filtering by hub, only show devices for that hub
    if filtered_hub:
        hub_devices = Device.query.filter_by(hub_id=filtered_hub.id).filter(Device.status != 'pending').all()
        hub_screen_list = []

        for device in hub_devices:
            layout = None
            if device.layout_id:
                layout = db.session.get(ScreenLayout, device.layout_id)

            current_playlist = None
            assignment = DeviceAssignment.query.filter_by(device_id=device.id).first()
            if assignment and assignment.playlist:
                current_playlist = assignment.playlist.name

            hub_screen_list.append({
                'id': device.id,
                'device_id': device.device_id,
                'name': device.name or device.device_id,
                'status': device.status,
                'last_seen': device.last_seen,
                'layout_name': layout.name if layout else 'No layout',
                'layout_id': device.layout_id,
                'current_playlist': current_playlist or 'No playlist',
                'mode': device.mode or 'hub'
            })

        return render_template(
            'devices.html',
            active_page='devices',
            devices=devices,
            hubs=hubs,
            networks=[],
            unassigned_devices=[],
            filtered_hub=filtered_hub,
            hub_screens=hub_screen_list,
            playlists=playlists,
            locations=locations
        )

    # Build network data with screens (same as dashboard)
    networks_raw = Network.query.order_by(Network.name).all()
    network_data = []

    for network in networks_raw:
        network_devices = Device.query.filter_by(network_id=network.id).filter(Device.status != 'pending').all()
        screen_list = []

        for device in network_devices:
            # Get layout info
            layout = None
            if device.layout_id:
                layout = db.session.get(ScreenLayout, device.layout_id)

            # Get current playlist (first assignment)
            current_playlist = None
            assignment = DeviceAssignment.query.filter_by(device_id=device.id).first()
            if assignment and assignment.playlist:
                current_playlist = assignment.playlist.name

            screen_list.append({
                'id': device.id,
                'device_id': device.device_id,
                'name': device.name or device.device_id,
                'status': device.status,
                'last_seen': device.last_seen,
                'layout_name': layout.name if layout else 'No layout',
                'layout_id': device.layout_id,
                'current_playlist': current_playlist or 'No playlist',
            })

        network_data.append({
            'id': network.id,
            'name': network.name,
            'description': getattr(network, 'description', None),
            'screen_count': len(screen_list),
            'online_count': sum(1 for s in screen_list if s['status'] == 'active'),
            'screens': screen_list
        })

    # Get unassigned devices (not part of any network)
    unassigned_devices = Device.query.filter(
        Device.network_id.is_(None),
        Device.status != 'pending'
    ).order_by(Device.created_at.desc()).all()

    return render_template(
        'devices.html',
        active_page='devices',
        devices=devices,
        hubs=hubs,
        networks=network_data,
        unassigned_devices=unassigned_devices,
        filtered_hub=None,
        hub_screens=[],
        playlists=playlists,
        locations=locations
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

    Lists approved content synced from the Content Catalog.
    All content must go through the Content Catalog approval workflow
    before appearing here - no direct uploads allowed.

    Returns:
        Rendered content.html template with content list and filter options
    """
    # Query synced content from Content Catalog
    synced_items = SyncedContent.query.order_by(SyncedContent.synced_at.desc()).all()

    # Query local content
    content_items = Content.query.order_by(Content.created_at.desc()).all()

    networks = Network.query.order_by(Network.name).all()

    # Fetch organizations for partner filter dropdown (from synced content)
    organizations = ContentSyncService.get_organizations()

    content = []

    # Add synced content with full metadata
    for item in synced_items:
        # Get folder info if content is in a folder
        folder = Folder.query.get(item.folder_id) if item.folder_id else None

        content.append({
            'id': item.id,
            'filename': item.filename,
            'local_filename': item.local_filename if item.local_filename else (item.file_path.split('/')[-1] if item.file_path else item.filename),
            'title': item.title,
            'duration': item.duration or 0,
            'file_size': item.file_size or 0,
            'mime_type': item.format,
            'network_ids': item.get_network_ids_list(),
            'organization_id': item.organization_id,
            'organization_name': item.organization_name,
            'content_type': item.content_type,
            'status': item.status,
            'thumbnail_url': item.thumbnail_url,
            'folder_id': item.folder_id,
            'folder_name': folder.name if folder else None,
            'folder_color': folder.color if folder else None,
            'folder_icon': folder.icon if folder else None,
        })

    # Add local content (uploaded directly to CMS)
    for item in content_items:
        # Convert single network_id to list for network filter compatibility
        network_ids = [item.network_id] if item.network_id else []
        # Determine content type from mime_type
        content_type = 'video'
        if item.mime_type:
            if 'image' in item.mime_type:
                content_type = 'image'
            elif 'audio' in item.mime_type:
                content_type = 'audio'

        content.append({
            'id': item.id,
            'filename': item.filename,
            'local_filename': item.local_filename if item.local_filename else (item.file_path.split('/')[-1] if item.file_path else item.filename),
            'title': item.original_name,  # Template expects 'title'
            'duration': item.duration or 0,
            'file_size': item.file_size,
            'mime_type': item.mime_type,
            'network_ids': network_ids,  # For network filter
            'organization_id': None,  # Local upload
            'organization_name': None,  # Local upload
            'content_type': content_type,
            'status': None,  # Local uploads have no workflow status
            'thumbnail_url': None,  # Local uploads have no thumbnails yet
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
        organizations=organizations,  # Partner filter options
        folders=Folder.query.filter_by(parent_id=None).order_by(Folder.name).all()
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
    folders = Folder.query.filter_by(parent_id=None).order_by(Folder.name).all()

    return render_template(
        'playlists.html',
        active_page='playlists',
        playlists=playlists,
        content=content,
        networks=networks,
        folders=folders
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
                'priority': assignment.priority,
                'is_enabled': assignment.is_enabled if hasattr(assignment, 'is_enabled') else True
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

    # Get all available layouts for assignment (exclude templates)
    from cms.models.layout import ScreenLayout
    all_layouts = ScreenLayout.query.filter_by(is_template=False).order_by(ScreenLayout.name).all()

    return render_template(
        'device_detail.html',
        active_page='devices',
        device=device,
        device_playlists=device_playlists,
        all_playlists=all_playlists,
        all_layouts=all_layouts,
        trigger_types=trigger_info
    )

@web_bp.route('/login')
def login_page():
    """Render the login page."""
    from flask_login import current_user
    if current_user.is_authenticated:
        return redirect(url_for('web.dashboard'))
    return render_template('auth/login.html')

@web_bp.route('/logout')
def logout_page():
    """Handle logout and redirect to login."""
    from flask_login import logout_user
    logout_user()
    return redirect(url_for('web.login_page'))

@web_bp.route('/login', methods=['GET', 'POST'])
def web_login():
    """Handle web login - both display form and process submission."""
    from flask import request, flash
    from flask_login import current_user, login_user, login_required
    from cms.models.user import User
    
    if current_user.is_authenticated:
        return redirect(url_for('web.dashboard'))
    
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        remember = request.form.get('remember_me') == 'on'
        
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            login_user(user, remember=remember)
            return redirect(url_for('web.dashboard'))
        else:
            flash('Invalid email or password', 'error')
    
    return render_template('auth/login.html')


@web_bp.route('/api/admin/pairing/approve', methods=['POST'])
@login_required
def approve_pairing():
    """
    Approve a device by its pairing code and assign to network/hub.

    Required fields for pairing:
    - pairing_code: The device's pairing code
    - network_id: Network to assign the device to
    - store_name: Store name or number
    - store_address: Street address
    - store_city: City
    - store_state: State
    - store_zipcode: Zipcode
    - screen_location: Location within the store
    - manager_name: Store manager's name
    - store_phone: Store phone number

    Optional fields:
    - hub_id: Hub to assign the device to (sets mode to 'hub')
    - name: Device display name
    """
    data = request.get_json()
    pairing_code = data.get('pairing_code')

    if not pairing_code:
        return jsonify({'error': 'Pairing code is required'}), 400

    device = Device.query.filter_by(pairing_code=pairing_code).first()
    if not device:
        return jsonify({'error': 'Device not found with that pairing code'}), 404

    # Validate required fields
    required_fields = {
        'network_id': 'Network',
        'store_name': 'Store Name',
        'store_address': 'Address',
        'store_city': 'City',
        'store_state': 'State',
        'store_zipcode': 'Zipcode',
        'screen_location': 'Screen Location',
        'manager_name': 'Manager Name',
        'store_phone': 'Store Phone'
    }

    missing_fields = []
    for field, label in required_fields.items():
        value = data.get(field)
        if not value or str(value).strip() == '':
            missing_fields.append(label)

    if missing_fields:
        return jsonify({
            'error': 'Missing required fields',
            'missing_fields': missing_fields
        }), 400

    # Activate device and set all fields
    device.status = 'active'
    device.network_id = data.get('network_id')
    device.store_name = data.get('store_name')
    device.store_address = data.get('store_address')
    device.store_city = data.get('store_city')
    device.store_state = data.get('store_state')
    device.store_zipcode = data.get('store_zipcode')
    device.screen_location = data.get('screen_location')
    device.manager_name = data.get('manager_name')
    device.store_phone = data.get('store_phone')

    # Optional: set device name
    if data.get('name'):
        device.name = data.get('name')

    # Assign to hub (if provided)
    hub_id = data.get('hub_id')
    if hub_id:
        device.hub_id = hub_id
        device.mode = 'hub'
    else:
        device.mode = 'direct'

    db.session.commit()

    return jsonify({
        'message': 'Device paired successfully',
        'device': device.to_dict()
    })


# ============================================
# FOLDER ROUTES
# ============================================

@web_bp.route('/folders', methods=['GET'])
@login_required
def list_folders():
    """Get all folders as a nested tree structure."""
    # Get root folders (no parent)
    root_folders = Folder.query.filter_by(parent_id=None).order_by(Folder.name).all()
    return jsonify([f.to_dict(include_children=True) for f in root_folders])


@web_bp.route('/folders', methods=['POST'])
@login_required
def create_folder():
    """Create a new folder."""
    data = request.get_json()
    
    if not data.get('name'):
        return jsonify({'error': 'Folder name is required'}), 400
    
    folder = Folder(
        name=data['name'],
        icon=data.get('icon', '📁'),
        color=data.get('color', '#667eea'),
        parent_id=data.get('parent_id')  # None for root folders
    )
    
    db.session.add(folder)
    db.session.commit()
    
    return jsonify(folder.to_dict()), 201


@web_bp.route('/folders/<folder_id>', methods=['DELETE'])
@login_required
def delete_folder(folder_id):
    """Delete a folder and optionally its contents."""
    folder = Folder.query.get(folder_id)
    
    if not folder:
        return jsonify({'error': 'Folder not found'}), 404
    
    # Delete all child folders recursively
    def delete_children(parent):
        for child in parent.children:
            delete_children(child)
            db.session.delete(child)
    
    delete_children(folder)
    db.session.delete(folder)
    db.session.commit()
    
    return jsonify({'message': 'Folder deleted successfully'})


@web_bp.route('/folders/<folder_id>', methods=['PUT'])
@login_required
def update_folder(folder_id):
    """Update a folder's name, icon, color, or parent."""
    folder = Folder.query.get(folder_id)
    
    if not folder:
        return jsonify({'error': 'Folder not found'}), 404
    
    data = request.get_json()
    
    if 'name' in data:
        folder.name = data['name']
    if 'icon' in data:
        folder.icon = data['icon']
    if 'color' in data:
        folder.color = data['color']
    if 'parent_id' in data:
        folder.parent_id = data['parent_id']
    
    db.session.commit()
    
    return jsonify(folder.to_dict())


@web_bp.route('/content/<content_id>/move', methods=['POST'])
@login_required
def move_content_to_folder(content_id):
    """Move content to a folder. Supports both SyncedContent and Content models."""
    data = request.get_json()
    folder_id = data.get('folder_id')  # None to remove from folder

    # Try SyncedContent first, then Content
    content = SyncedContent.query.get(content_id)
    if not content:
        content = Content.query.get(content_id)

    if not content:
        return jsonify({'error': 'Content not found'}), 404

    # Verify folder exists if provided
    if folder_id:
        folder = Folder.query.get(folder_id)
        if not folder:
            return jsonify({'error': 'Folder not found'}), 404

    content.folder_id = folder_id
    db.session.commit()

    return jsonify({'message': 'Content moved successfully', 'folder_id': folder_id})

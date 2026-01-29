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
from flask_login import login_required, current_user

from datetime import datetime, timezone
from cms.models import db, Device, Hub, PendingHub, Content, Playlist, Network, DeviceAssignment, Folder
from cms.routes.locations import Location
from cms.models.device_assignment import TRIGGER_TYPES
from cms.models.synced_content import SyncedContent
from cms.services.content_sync_service import ContentSyncService


# Create web blueprint (no url_prefix since these are root-level pages)
web_bp = Blueprint('web', __name__)


def get_user_network_filter():
    """
    Get network IDs the current user has access to.

    Returns:
        tuple: (has_all_access, network_ids_list)
        - has_all_access: True if user can see all networks
        - network_ids_list: List of network IDs user can access (empty if all)
    """
    if not current_user.is_authenticated:
        return False, []

    # Super admins or users with no restrictions see everything
    if current_user.has_all_network_access():
        return True, []

    return False, current_user.get_network_ids_list()


def filter_networks_for_user(networks_query):
    """
    Filter a networks query based on current user's access.

    Args:
        networks_query: SQLAlchemy query for Network model

    Returns:
        Filtered query
    """
    has_all, network_ids = get_user_network_filter()
    if has_all:
        return networks_query

    if not network_ids:
        # User has no network access - return empty
        return networks_query.filter(Network.id == None)

    return networks_query.filter(Network.id.in_(network_ids))



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

    # Get networks filtered by user's access
    networks_query = Network.query.order_by(Network.name)
    networks = filter_networks_for_user(networks_query).all()

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
    total_screen_count = len(devices)

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
            locations=locations,
            total_screen_count=total_screen_count
        )

    # Build network data with stores (grouped by store_name)
    # Filter networks by user's access
    networks_query = Network.query.order_by(Network.name)
    networks_raw = filter_networks_for_user(networks_query).all()
    network_data = []

    for network in networks_raw:
        network_devices = Device.query.filter_by(network_id=network.id).filter(Device.status != 'pending').all()

        # Group devices by store_name
        stores_dict = {}
        for device in network_devices:
            store_key = device.store_name or 'Unassigned'
            if store_key not in stores_dict:
                stores_dict[store_key] = {
                    'name': store_key,
                    'city': device.store_city,
                    'state': device.store_state,
                    'screens': [],
                    'screen_count': 0,
                    'online_count': 0
                }

            # Get layout info
            layout = None
            if device.layout_id:
                layout = db.session.get(ScreenLayout, device.layout_id)

            # Get current playlist (first assignment)
            current_playlist = None
            assignment = DeviceAssignment.query.filter_by(device_id=device.id).first()
            if assignment and assignment.playlist:
                current_playlist = assignment.playlist.name

            screen_data = {
                'id': device.id,
                'device_id': device.device_id,
                'name': device.name or device.device_id,
                'status': device.status,
                'last_seen': device.last_seen,
                'layout_name': layout.name if layout else 'No layout',
                'layout_id': device.layout_id,
                'current_playlist': current_playlist or 'No playlist',
                'screen_location': device.screen_location or 'Unknown'
            }

            stores_dict[store_key]['screens'].append(screen_data)
            stores_dict[store_key]['screen_count'] += 1
            if device.status == 'active':
                stores_dict[store_key]['online_count'] += 1

        # Convert to list and sort by store name
        stores_list = sorted(stores_dict.values(), key=lambda x: x['name'])

        total_screens = sum(s['screen_count'] for s in stores_list)
        total_online = sum(s['online_count'] for s in stores_list)

        network_data.append({
            'id': network.id,
            'name': network.name,
            'description': getattr(network, 'description', None),
            'screen_count': total_screens,
            'online_count': total_online,
            'store_count': len(stores_list),
            'stores': stores_list
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
        locations=locations,
        total_screen_count=total_screen_count
    )


@web_bp.route('/hubs')
@login_required
def hubs_page():
    """
    Hub management page.

    Lists all registered hubs with their details including:
    - Hub code and name
    - Associated network
    - Connected device count
    - Status

    Also shows pending hubs waiting to be paired.

    Returns:
        Rendered hubs.html template with hub list and pending hubs
    """
    # Filter networks and hubs by user's access
    has_all_access, user_network_ids = get_user_network_filter()

    if has_all_access:
        hubs = Hub.query.order_by(Hub.created_at.desc()).all()
    else:
        hubs = Hub.query.filter(Hub.network_id.in_(user_network_ids)).order_by(Hub.created_at.desc()).all()

    networks = filter_networks_for_user(Network.query.order_by(Network.name)).all()

    # Get pending hubs (not expired)
    now = datetime.now(timezone.utc)
    pending_hubs = PendingHub.query.filter(
        (PendingHub.expires_at > now) | (PendingHub.expires_at.is_(None))
    ).order_by(PendingHub.created_at.desc()).all()

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
        networks=networks,
        pending_hubs=pending_hubs
    )


@web_bp.route('/content')
@login_required
def content_page():
    """
    Content management page with 16:9 aspect ratio preview.

    Lists approved content synced from the Content Catalog.
    All content must go through the Content Catalog approval workflow
    before appearing here - no direct uploads allowed.

    Returns:
        Rendered content.html template with content list and filter options
    """
    # Get user's network access
    has_all_access, user_network_ids = get_user_network_filter()

    # Query synced content from Content Catalog
    synced_items = SyncedContent.query.order_by(SyncedContent.synced_at.desc()).all()

    # Query local content
    content_items = Content.query.order_by(Content.created_at.desc()).all()

    # Filter networks by user's access
    networks = filter_networks_for_user(Network.query.order_by(Network.name)).all()

    # Fetch organizations for partner filter dropdown (from synced content)
    organizations = ContentSyncService.get_organizations()

    content = []

    # Helper to check if content is accessible to user
    def content_accessible(content_network_ids):
        if has_all_access:
            return True
        if not content_network_ids:
            # Content with no network restriction is visible to all
            return True
        # Check if any of the content's networks overlap with user's networks
        return bool(set(content_network_ids) & set(user_network_ids))

    # Add synced content with full metadata
    for item in synced_items:
        item_network_ids = item.get_network_ids_list()
        if not content_accessible(item_network_ids):
            continue
        # Get folder info if content is in a folder
        folder = Folder.query.get(item.folder_id) if item.folder_id else None

        content.append({
            'id': item.id,
            'filename': item.filename,
            'local_filename': getattr(item, 'local_filename', None) or (getattr(item, 'file_path', '').split('/')[-1] if getattr(item, 'file_path', None) else item.filename),
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

        # Check if user can see this content
        if not content_accessible(network_ids):
            continue

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
            'local_filename': getattr(item, 'local_filename', None) or (getattr(item, 'file_path', '').split('/')[-1] if getattr(item, 'file_path', None) else item.filename),
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
        organizations=organizations  # Partner filter options
    )


@web_bp.route('/playlists')
@login_required
def playlists_page():
    """
    Playlist management page with trigger configuration.

    Lists all playlists with their details including:
    - Name and description
    - Trigger type and configuration
    - Item count
    - Active status

    Also provides content list for adding items to playlists.
    Uses same content source as Content Library (SyncedContent + Content).

    Returns:
        Rendered playlists.html template with playlist and content lists
    """
    # Filter playlists by user's network access
    has_all_access, user_network_ids = get_user_network_filter()
    if has_all_access:
        playlists = Playlist.query.filter_by(is_active=True).order_by(Playlist.created_at.desc()).all()
    else:
        playlists = Playlist.query.filter(
            Playlist.is_active == True,
            Playlist.network_id.in_(user_network_ids)
        ).order_by(Playlist.created_at.desc()).all()

    # Filter networks by user's access
    networks = filter_networks_for_user(Network.query.order_by(Network.name)).all()

    # Use same content source as content_page for consistency
    synced_items = SyncedContent.query.order_by(SyncedContent.synced_at.desc()).all()
    content_items = Content.query.order_by(Content.created_at.desc()).all()

    # Helper to check if content is accessible to user
    def content_accessible(content_network_ids):
        if has_all_access:
            return True
        if not content_network_ids:
            return True
        return bool(set(content_network_ids) & set(user_network_ids))

    content = []

    # Add synced content (same logic as content_page)
    for item in synced_items:
        item_network_ids = item.get_network_ids_list()
        if not content_accessible(item_network_ids):
            continue

        folder = Folder.query.get(item.folder_id) if item.folder_id else None
        content.append({
            'id': item.id,
            'original_name': item.title,
            'filename': getattr(item, 'local_filename', None) or item.filename,
            'duration': item.duration or 0,
            'file_size': item.file_size or 0,
            'network_ids': item_network_ids,  # List of network IDs
            'folder_id': item.folder_id,
            'folder': folder,
            'status': item.status,
            'is_video': item.content_type == 'video',
            'is_image': item.content_type == 'image',
        })

    # Add local content (not synced)
    synced_uuids = {item.source_uuid for item in synced_items if item.source_uuid}
    for item in content_items:
        if item.catalog_asset_uuid and item.catalog_asset_uuid in synced_uuids:
            continue  # Skip if already added from synced

        network_ids = [item.network_id] if item.network_id else []
        if not content_accessible(network_ids):
            continue

        folder = Folder.query.get(item.folder_id) if item.folder_id else None
        content.append({
            'id': item.id,
            'original_name': item.original_name or item.filename,
            'filename': item.filename,
            'duration': item.duration or 0,
            'file_size': item.file_size or 0,
            'network_ids': network_ids,  # List of network IDs
            'folder_id': item.folder_id,
            'folder': folder,
            'status': item.status,
            'is_video': item.is_video,
            'is_image': item.is_image,
        })

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
                'priority': assignment.priority,
                'is_enabled': assignment.is_enabled if hasattr(assignment, 'is_enabled') else True
            })

    # Get playlists for this device's network only
    if device.network_id:
        all_playlists = Playlist.query.filter_by(
            is_active=True,
            network_id=device.network_id
        ).order_by(Playlist.name).all()
    else:
        # Fallback to all playlists if device has no network
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

@web_bp.route('/logout')
def logout_page():
    """Handle logout and redirect to login."""
    from flask_login import logout_user
    logout_user()
    return redirect(url_for('web.login'))


@web_bp.route('/settings')
@login_required
def settings_page():
    """
    User profile/account settings page.

    Allows users to:
    - View and update their profile information
    - Change password
    - View active sessions
    - Manage security settings
    """
    from cms.models import UserSession

    # Get user's active sessions
    sessions = UserSession.query.filter_by(
        user_id=current_user.id,
        is_valid=True
    ).order_by(UserSession.created_at.desc()).all()

    return render_template(
        'account/settings.html',
        active_page='profile',
        user=current_user,
        sessions=sessions
    )


@web_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Handle web login - both display form and process submission."""
    from flask import request, flash
    from flask_login import current_user, login_user
    from cms.models.user import User

    if current_user.is_authenticated:
        return redirect(url_for('web.dashboard'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password')
        remember = request.form.get('remember_me') in ['on', '1', 'true', True]

        # Case-insensitive email lookup
        from sqlalchemy import func
        user = User.query.filter(func.lower(User.email) == email).first()
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

    # Activate device and clear pairing code
    device.status = 'active'
    device.pairing_code = None
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
    """Get all folders, optionally filtered by network_id."""
    network_id = request.args.get('network_id')

    if network_id:
        # Get all folders for this network (flat list for client-side processing)
        folders = Folder.query.filter_by(network_id=network_id).order_by(Folder.name).all()
        return jsonify([f.to_dict() for f in folders])
    else:
        # Get all root folders (no parent, no network) - legacy behavior
        root_folders = Folder.query.filter_by(parent_id=None).order_by(Folder.name).all()
        return jsonify([f.to_dict(include_children=True) for f in root_folders])


@web_bp.route('/folders', methods=['POST'])
@login_required
def create_folder():
    """Create a new folder within a network."""
    data = request.get_json()

    if not data.get('name'):
        return jsonify({'error': 'Folder name is required'}), 400

    if not data.get('network_id'):
        return jsonify({'error': 'Network ID is required'}), 400

    folder = Folder(
        name=data['name'],
        icon=data.get('icon', '📁'),
        color=data.get('color', '#667eea'),
        network_id=data['network_id'],
        parent_id=data.get('parent_id')  # None for root folders within network
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


# ============================================================================
# Admin Routes
# ============================================================================

@web_bp.route('/admin/users')
@login_required
def admin_users_page():
    """
    User management page for admins.

    Displays all users with ability to:
    - Invite new users
    - Edit user roles and permissions
    - Suspend/reactivate users
    - View user activity

    Requires admin, super_admin, or project_manager role.
    """
    from flask_login import current_user
    from cms.models import User, UserInvitation, Network

    # Check if user has admin/management access
    if current_user.role not in ['admin', 'super_admin', 'project_manager']:
        abort(403)

    # Get user's network access
    has_all_access, user_network_ids = get_user_network_filter()

    # For project_managers, filter users to only show those in their networks
    if current_user.role == 'project_manager' and not has_all_access:
        # Get users that share at least one network with the project_manager
        all_users = User.query.order_by(User.created_at.desc()).all()
        users = []
        for u in all_users:
            # Project managers can only see users with lower roles
            if u.role in ['content_manager', 'viewer']:
                u_networks = u.get_network_ids_list()
                # If user has no network restriction or shares a network
                if not u_networks or set(u_networks) & set(user_network_ids):
                    users.append(u)

        # Filter invitations to those the PM created or in their networks
        all_invitations = UserInvitation.query.filter_by(status='pending').order_by(UserInvitation.created_at.desc()).all()
        invitations = [inv for inv in all_invitations if inv.invited_by == current_user.id]

        # Filter networks to only those the PM has access to
        networks = filter_networks_for_user(Network.query.order_by(Network.name)).all()
    else:
        # Admins and super_admins see all
        users = User.query.order_by(User.created_at.desc()).all()
        invitations = UserInvitation.query.filter_by(status='pending').order_by(UserInvitation.created_at.desc()).all()
        networks = Network.query.order_by(Network.name).all()

    return render_template(
        'admin/users.html',
        active_page='users',
        users=users,
        invitations=invitations,
        networks=networks
    )


@web_bp.route('/admin/users/<user_id>')
@login_required
def admin_user_detail_page(user_id):
    """
    User detail page showing user info and activity.
    """
    from flask_login import current_user
    from cms.models import User, UserSession, Network
    from cms.models.audit_log import AuditLog

    # Check if user has admin/management access
    if current_user.role not in ['admin', 'super_admin', 'project_manager']:
        abort(403)

    user = User.query.get_or_404(user_id)

    # Project managers can only view users they can manage
    if current_user.role == 'project_manager':
        if user.role not in ['content_manager', 'viewer']:
            abort(403)

    # Get user's sessions
    sessions = UserSession.query.filter_by(user_id=user_id).order_by(UserSession.created_at.desc()).limit(10).all()

    # Get user's recent activity
    activity = AuditLog.query.filter_by(user_id=user_id).order_by(AuditLog.created_at.desc()).limit(20).all()

    # Get networks for assignment
    networks = Network.query.order_by(Network.name).all()

    return render_template(
        'admin/user_detail.html',
        active_page='users',
        user=user,
        sessions=sessions,
        activity=activity,
        networks=networks
    )


@web_bp.route('/admin/audit-logs')
@login_required
def admin_audit_logs_page():
    """
    Audit logs page showing system activity.
    """
    from flask_login import current_user
    from cms.models.audit_log import AuditLog

    # Check if user has admin access
    if current_user.role not in ['admin', 'super_admin']:
        abort(403)

    # Get recent audit logs
    logs = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(100).all()

    return render_template(
        'admin/audit_logs.html',
        active_page='audit',
        logs=logs
    )

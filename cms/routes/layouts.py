"""
CMS Layouts Routes

Blueprint for screen layout management API endpoints:
- POST /: Create layout
- GET /: List all layouts
- GET /<layout_id>: Get layout details
- PUT /<layout_id>: Update layout
- DELETE /<layout_id>: Delete layout
- POST /<layout_id>/duplicate: Duplicate layout
- GET /templates: Get system templates
- GET /<layout_id>/layers: List all layers in a layout
- POST /<layout_id>/layers: Add a layer to a layout
- GET /<layout_id>/layers/<layer_id>: Get a specific layer
- PUT /<layout_id>/layers/<layer_id>: Update a layer
- DELETE /<layout_id>/layers/<layer_id>: Delete a layer
- PUT /<layout_id>/layers/reorder: Reorder layers by z_index
- POST /<layout_id>/layers/<layer_id>/content: Assign static content to a layer
- GET /<layout_id>/layers/<layer_id>/content: List content assignments for a layer
- GET /<layout_id>/layers/<layer_id>/content/<content_id>: Get a specific content assignment
- PUT /<layout_id>/layers/<layer_id>/content/<content_id>: Update a content assignment
- DELETE /<layout_id>/layers/<layer_id>/content/<content_id>: Remove a content assignment
- POST /<layout_id>/layers/<layer_id>/playlists: Assign a playlist to a layer
- GET /<layout_id>/layers/<layer_id>/playlists: List playlist assignments for a layer
- DELETE /<layout_id>/layers/<layer_id>/playlists/<assignment_id>: Remove a playlist assignment
- POST /<layout_id>/assign: Assign layout to device with scheduling
- GET /<layout_id>/assignments: List all device assignments for a layout
- DELETE /<layout_id>/assign/<assignment_id>: Remove device assignment

All endpoints are prefixed with /api/v1/layouts when registered with the app.
"""

from datetime import datetime, timezone

from flask import Blueprint, request, jsonify, render_template, abort
from flask_login import login_required

from cms.models import db, ScreenLayout, ScreenLayer, LayerContent, LayerPlaylistAssignment, Device, Playlist, DeviceLayout, Content
from cms.models.layout import CONTENT_MODES, TICKER_DIRECTIONS, LAYER_TRIGGER_TYPES
from cms.services.layout_service import LayoutService


def _parse_datetime(datetime_str):
    """Parse datetime string to datetime object.

    Supports ISO format with optional timezone.

    Args:
        datetime_str: Datetime string to parse

    Returns:
        datetime object or None if invalid
    """
    if not datetime_str:
        return None

    try:
        # Handle ISO format with Z suffix
        return datetime.fromisoformat(datetime_str.replace('Z', '+00:00'))
    except ValueError:
        return None


# Create layouts blueprint
layouts_bp = Blueprint('layouts', __name__)


# Valid values for layout fields
VALID_ORIENTATIONS = ['landscape', 'portrait']
VALID_BACKGROUND_TYPES = ['solid', 'transparent', 'image']

# Valid values for layer fields
VALID_LAYER_TYPES = ['content', 'text', 'widget', 'image', 'weather', 'ticker', 'clock', 'html']
VALID_LAYER_BACKGROUND_TYPES = ['solid', 'transparent', 'image', 'none']


@layouts_bp.route('', methods=['POST'])
def create_layout():
    """
    Create a new screen layout.

    Request Body:
        {
            "name": "My Layout" (required),
            "description": "Optional description",
            "canvas_width": 1920 (optional, default: 1920),
            "canvas_height": 1080 (optional, default: 1080),
            "orientation": "landscape" | "portrait" (optional, default: "landscape"),
            "background_type": "solid" | "transparent" | "image" (optional, default: "solid"),
            "background_color": "#000000" (optional, default: "#000000"),
            "background_opacity": 1.0 (optional, default: 1.0),
            "is_template": false (optional, default: false)
        }

    Returns:
        201: Layout created successfully
            { layout data }
        400: Missing required field or invalid data
            {
                "error": "error message"
            }
    """
    data = request.get_json()

    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    # Validate name
    name = data.get('name')
    if not name:
        return jsonify({'error': 'name is required'}), 400

    if not isinstance(name, str) or len(name) > 255:
        return jsonify({
            'error': 'name must be a string with max 255 characters'
        }), 400

    # Validate canvas_width if provided
    canvas_width = data.get('canvas_width', 1920)
    try:
        canvas_width = int(canvas_width)
    except (TypeError, ValueError):
        return jsonify({'error': 'canvas_width must be an integer'}), 400

    if canvas_width < 20 or canvas_width > 10000:
        return jsonify({
            'error': 'canvas_width must be between 20 and 10000 pixels'
        }), 400

    # Validate canvas_height if provided
    canvas_height = data.get('canvas_height', 1080)
    try:
        canvas_height = int(canvas_height)
    except (TypeError, ValueError):
        return jsonify({'error': 'canvas_height must be an integer'}), 400

    if canvas_height < 20 or canvas_height > 10000:
        return jsonify({
            'error': 'canvas_height must be between 20 and 10000 pixels'
        }), 400

    # Validate orientation if provided
    orientation = data.get('orientation', 'landscape')
    if orientation not in VALID_ORIENTATIONS:
        return jsonify({
            'error': f"Invalid orientation: {orientation}. Valid values: {', '.join(VALID_ORIENTATIONS)}"
        }), 400

    # Validate background_type if provided
    background_type = data.get('background_type', 'solid')
    if background_type not in VALID_BACKGROUND_TYPES:
        return jsonify({
            'error': f"Invalid background_type: {background_type}. Valid values: {', '.join(VALID_BACKGROUND_TYPES)}"
        }), 400

    # Validate background_opacity if provided
    background_opacity = data.get('background_opacity', 1.0)
    try:
        background_opacity = float(background_opacity)
    except (TypeError, ValueError):
        return jsonify({'error': 'background_opacity must be a number'}), 400

    if not (0.0 <= background_opacity <= 1.0):
        return jsonify({
            'error': 'background_opacity must be between 0.0 and 1.0'
        }), 400

    # Create layout
    layout = ScreenLayout(
        name=name,
        description=data.get('description'),
        canvas_width=canvas_width,
        canvas_height=canvas_height,
        orientation=orientation,
        background_type=background_type,
        background_color=data.get('background_color', '#000000'),
        background_opacity=background_opacity,
        is_template=data.get('is_template', False)
    )

    try:
        db.session.add(layout)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to create layout: {str(e)}'
        }), 500

    return jsonify(layout.to_dict()), 201


@layouts_bp.route('', methods=['GET'])
def list_layouts():
    """
    List all screen layouts.

    Returns a list of all layouts in the CMS,
    with optional filtering by template status or orientation.

    Query Parameters:
        is_template: Filter by template status (true/false)
        orientation: Filter by orientation (landscape/portrait)

    Returns:
        200: List of layouts
            {
                "layouts": [ { layout data }, ... ],
                "count": 5
            }
    """
    # Build query with optional filters
    query = ScreenLayout.query

    # Filter by template status
    is_template = request.args.get('is_template')
    if is_template is not None:
        is_template_bool = is_template.lower() == 'true'
        query = query.filter_by(is_template=is_template_bool)

    # Filter by orientation
    orientation = request.args.get('orientation')
    if orientation:
        if orientation not in VALID_ORIENTATIONS:
            return jsonify({
                'error': f"Invalid orientation: {orientation}. Valid values: {', '.join(VALID_ORIENTATIONS)}"
            }), 400
        query = query.filter_by(orientation=orientation)

    # Execute query
    layouts = query.order_by(ScreenLayout.updated_at.desc()).all()

    return jsonify({
        'layouts': [l.to_dict() for l in layouts],
        'count': len(layouts)
    }), 200


@layouts_bp.route('/templates', methods=['GET'])
def list_templates():
    """
    List all template layouts.

    Returns a list of all layouts marked as templates.
    Templates are reusable layout configurations.

    Returns:
        200: List of template layouts
            {
                "templates": [ { layout data }, ... ],
                "count": 3
            }
    """
    templates = ScreenLayout.get_templates()

    return jsonify({
        'templates': [t.to_dict() for t in templates],
        'count': len(templates)
    }), 200


@layouts_bp.route('/<layout_id>', methods=['GET'])
def get_layout(layout_id):
    """
    Get details for a specific layout including all layers.

    Args:
        layout_id: Layout UUID

    Query Parameters:
        include_layers: Include layers in response (default: true)

    Returns:
        200: Layout data with layers
            { layout data with layers }
        400: Invalid layout_id format
            {
                "error": "Invalid layout_id format"
            }
        404: Layout not found
            {
                "error": "Layout not found"
            }
    """
    # Validate layout_id format
    if not isinstance(layout_id, str) or len(layout_id) > 64:
        return jsonify({
            'error': 'Invalid layout_id format'
        }), 400

    layout = db.session.get(ScreenLayout, layout_id)

    if not layout:
        return jsonify({'error': 'Layout not found'}), 404

    # Check if layers should be included
    include_layers = request.args.get('include_layers', 'true').lower() == 'true'

    return jsonify(layout.to_dict(include_layers=include_layers)), 200


@layouts_bp.route('/<layout_id>/preview', methods=['GET'])
def get_layout_preview(layout_id):
    """
    Get layout data formatted for preview display with content URLs.

    Returns layout with layers including content URLs, thumbnails, and
    media type information needed to render a visual preview.

    Args:
        layout_id: Layout UUID

    Returns:
        200: Layout preview data
            {
                "id": "uuid",
                "name": "Layout Name",
                "width": 1920,
                "height": 1080,
                "orientation": "landscape",
                "layers": [
                    {
                        "id": "uuid",
                        "name": "Zone 1",
                        "x": 0,
                        "y": 0,
                        "width": 960,
                        "height": 1080,
                        "zIndex": 0,
                        "contentSource": "static",
                        "playlistName": "",
                        "contentName": "video.mp4",
                        "thumbnailUrl": "/api/v1/content/uuid/download",
                        "contentUrl": "/api/v1/content/uuid/download",
                        "mimeType": "video/mp4",
                        "contentType": "video"
                    }
                ]
            }
        404: Layout not found
    """
    layout = db.session.get(ScreenLayout, layout_id)
    if not layout:
        return jsonify({'error': 'Layout not found'}), 404

    layers_data = []
    for idx, layer in enumerate(layout.layers.order_by(ScreenLayer.z_index).all()):
        layer_data = {
            'id': layer.id,
            'name': layer.name or f'Zone {idx + 1}',
            'x': layer.x,
            'y': layer.y,
            'width': layer.width,
            'height': layer.height,
            'zIndex': layer.z_index,
            'contentSource': layer.content_source or 'none',
            'playlistName': layer.playlist.name if layer.playlist else '',
            'contentName': '',
            'isPrimary': idx == 0,
            'thumbnailUrl': None,
            'contentUrl': None,
            'mimeType': None,
            'contentType': 'none'
        }

        # Get content details based on content source
        if layer.content_source == 'static' and layer.content_id:
            content = layer.content
            if content:
                # Handle both Content and SyncedContent
                content_name = getattr(content, 'original_name', None) or getattr(content, 'title', '') or ''
                mime_type = getattr(content, 'mime_type', None) or ''
                content_format = getattr(content, 'format', None) or ''
                thumbnail_url = getattr(content, 'thumbnail_url', None)

                is_video = mime_type.startswith('video/') if mime_type else content_format in ['mp4', 'webm', 'mov', 'avi']
                is_image = mime_type.startswith('image/') if mime_type else content_format in ['jpeg', 'jpg', 'png', 'gif', 'webp']

                layer_data['contentName'] = content_name
                layer_data['contentUrl'] = f'/api/v1/content/{content.id}/download'
                layer_data['mimeType'] = mime_type or content_format
                layer_data['contentType'] = 'video' if is_video else 'image' if is_image else 'other'

                if thumbnail_url:
                    layer_data['thumbnailUrl'] = thumbnail_url
                elif is_image:
                    layer_data['thumbnailUrl'] = f'/api/v1/content/{content.id}/download'

        elif layer.content_source == 'playlist' and layer.playlist_id:
            playlist = layer.playlist
            if playlist:
                layer_data['playlistName'] = playlist.name
                # Get first item for preview
                first_item = playlist.items.first()
                if first_item and first_item.content:
                    content = first_item.content
                    mime_type = content.mime_type or ''
                    is_video = mime_type.startswith('video/')
                    is_image = mime_type.startswith('image/')

                    layer_data['contentName'] = content.original_name or ''
                    layer_data['contentUrl'] = f'/api/v1/content/{content.id}/download'
                    layer_data['mimeType'] = mime_type
                    layer_data['contentType'] = 'video' if is_video else 'image' if is_image else 'other'

                    if is_image:
                        layer_data['thumbnailUrl'] = f'/api/v1/content/{content.id}/download'

        layers_data.append(layer_data)

    return jsonify({
        'id': layout.id,
        'name': layout.name,
        'width': layout.canvas_width,
        'height': layout.canvas_height,
        'orientation': layout.orientation,
        'layers': layers_data
    }), 200


@layouts_bp.route('/<layout_id>', methods=['PUT'])
def update_layout(layout_id):
    """
    Update a layout.

    Args:
        layout_id: Layout UUID

    Request Body:
        {
            "name": "Updated Name" (optional),
            "description": "Updated description" (optional),
            "canvas_width": 1920 (optional),
            "canvas_height": 1080 (optional),
            "orientation": "landscape" | "portrait" (optional),
            "background_type": "solid" | "transparent" | "image" (optional),
            "background_color": "#000000" (optional),
            "background_opacity": 1.0 (optional),
            "background_content": "path/to/image" (optional),
            "is_template": true/false (optional),
            "thumbnail_path": "path/to/thumbnail" (optional)
        }

    Returns:
        200: Layout updated successfully
            { updated layout data }
        400: Invalid data
            {
                "error": "error message"
            }
        404: Layout not found
            {
                "error": "Layout not found"
            }
    """
    # Validate layout_id format
    if not isinstance(layout_id, str) or len(layout_id) > 64:
        return jsonify({
            'error': 'Invalid layout_id format'
        }), 400

    layout = db.session.get(ScreenLayout, layout_id)

    if not layout:
        return jsonify({'error': 'Layout not found'}), 404

    data = request.get_json()

    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    # Update name if provided
    if 'name' in data:
        name = data['name']
        if not isinstance(name, str) or len(name) > 255:
            return jsonify({
                'error': 'name must be a string with max 255 characters'
            }), 400
        layout.name = name

    # Update description if provided
    if 'description' in data:
        layout.description = data['description']

    # Update canvas_width if provided
    if 'canvas_width' in data:
        try:
            canvas_width = int(data['canvas_width'])
        except (TypeError, ValueError):
            return jsonify({'error': 'canvas_width must be an integer'}), 400

        if canvas_width < 20 or canvas_width > 10000:
            return jsonify({
                'error': 'canvas_width must be between 20 and 10000 pixels'
            }), 400
        layout.canvas_width = canvas_width

    # Update canvas_height if provided
    if 'canvas_height' in data:
        try:
            canvas_height = int(data['canvas_height'])
        except (TypeError, ValueError):
            return jsonify({'error': 'canvas_height must be an integer'}), 400

        if canvas_height < 20 or canvas_height > 10000:
            return jsonify({
                'error': 'canvas_height must be between 20 and 10000 pixels'
            }), 400
        layout.canvas_height = canvas_height

    # Update orientation if provided
    if 'orientation' in data:
        orientation = data['orientation']
        if orientation not in VALID_ORIENTATIONS:
            return jsonify({
                'error': f"Invalid orientation: {orientation}. Valid values: {', '.join(VALID_ORIENTATIONS)}"
            }), 400
        layout.orientation = orientation

    # Update background_type if provided
    if 'background_type' in data:
        background_type = data['background_type']
        if background_type not in VALID_BACKGROUND_TYPES:
            return jsonify({
                'error': f"Invalid background_type: {background_type}. Valid values: {', '.join(VALID_BACKGROUND_TYPES)}"
            }), 400
        layout.background_type = background_type

    # Update background_color if provided
    if 'background_color' in data:
        layout.background_color = data['background_color']

    # Update background_opacity if provided
    if 'background_opacity' in data:
        try:
            background_opacity = float(data['background_opacity'])
        except (TypeError, ValueError):
            return jsonify({'error': 'background_opacity must be a number'}), 400

        if not (0.0 <= background_opacity <= 1.0):
            return jsonify({
                'error': 'background_opacity must be between 0.0 and 1.0'
            }), 400
        layout.background_opacity = background_opacity

    # Update background_content if provided
    if 'background_content' in data:
        layout.background_content = data['background_content']

    # Update is_template if provided
    if 'is_template' in data:
        layout.is_template = bool(data['is_template'])

    # Update thumbnail_path if provided
    if 'thumbnail_path' in data:
        layout.thumbnail_path = data['thumbnail_path']

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to update layout: {str(e)}'
        }), 500

    return jsonify(layout.to_dict()), 200


@layouts_bp.route('/<layout_id>', methods=['DELETE'])
def delete_layout(layout_id):
    """
    Delete a layout and all its layers.

    Due to cascade delete, all layers, content assignments, and
    playlist assignments will be automatically removed.

    Args:
        layout_id: Layout UUID

    Returns:
        200: Layout deleted successfully
            {
                "message": "Layout deleted successfully",
                "id": "uuid"
            }
        400: Invalid layout_id format
            {
                "error": "Invalid layout_id format"
            }
        404: Layout not found
            {
                "error": "Layout not found"
            }
    """
    # Validate layout_id format
    if not isinstance(layout_id, str) or len(layout_id) > 64:
        return jsonify({
            'error': 'Invalid layout_id format'
        }), 400

    layout = db.session.get(ScreenLayout, layout_id)

    if not layout:
        return jsonify({'error': 'Layout not found'}), 404

    # Store id and name for response
    layout_id_response = layout.id
    layout_name = layout.name

    try:
        # Delete associated DeviceLayout assignments first
        DeviceLayout.query.filter_by(layout_id=layout_id).delete()

        # Delete the layout (layers will cascade)
        db.session.delete(layout)
        db.session.commit()

        current_app.logger.info(f"Layout deleted: {layout_name} ({layout_id_response})")

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Failed to delete layout {layout_id}: {str(e)}")
        return jsonify({
            'error': f'Failed to delete layout: {str(e)}'
        }), 500

    return jsonify({
        'message': 'Layout deleted successfully',
        'id': layout_id_response,
        'name': layout_name
    }), 200


@layouts_bp.route('/<layout_id>/duplicate', methods=['POST'])
def duplicate_layout(layout_id):
    """
    Duplicate a layout with optional layers.

    Creates a copy of the layout with all its layers.

    Args:
        layout_id: Layout UUID to duplicate

    Request Body:
        {
            "name": "New Layout Name" (optional, defaults to "Copy of {original name}"),
            "include_layers": true (optional, default: true)
        }

    Returns:
        201: Layout duplicated successfully
            { new layout data }
        400: Invalid layout_id format or invalid data
            {
                "error": "error message"
            }
        404: Layout not found
            {
                "error": "Layout not found"
            }
    """
    # Validate layout_id format
    if not isinstance(layout_id, str) or len(layout_id) > 64:
        return jsonify({
            'error': 'Invalid layout_id format'
        }), 400

    layout = db.session.get(ScreenLayout, layout_id)

    if not layout:
        return jsonify({'error': 'Layout not found'}), 404

    data = request.get_json() or {}

    # Get new name
    new_name = data.get('name')
    if new_name and (not isinstance(new_name, str) or len(new_name) > 255):
        return jsonify({
            'error': 'name must be a string with max 255 characters'
        }), 400

    # Get include_layers flag
    include_layers = data.get('include_layers', True)
    if not isinstance(include_layers, bool):
        include_layers = str(include_layers).lower() == 'true'

    try:
        # Use the service to duplicate
        new_layout = LayoutService.duplicate_layout(
            layout_id=layout_id,
            new_name=new_name,
            include_layers=include_layers
        )
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to duplicate layout: {str(e)}'
        }), 500

    return jsonify(new_layout.to_dict(include_layers=include_layers)), 201


# =============================================================================
# Layer CRUD Endpoints
# =============================================================================


@layouts_bp.route('/<layout_id>/layers', methods=['GET'])
def list_layers(layout_id):
    """
    List all layers for a specific layout.

    Args:
        layout_id: Layout UUID

    Query Parameters:
        is_visible: Filter by visibility (true/false)

    Returns:
        200: List of layers
            {
                "layers": [ { layer data }, ... ],
                "count": 5
            }
        400: Invalid layout_id format
            {
                "error": "Invalid layout_id format"
            }
        404: Layout not found
            {
                "error": "Layout not found"
            }
    """
    # Validate layout_id format
    if not isinstance(layout_id, str) or len(layout_id) > 64:
        return jsonify({
            'error': 'Invalid layout_id format'
        }), 400

    layout = db.session.get(ScreenLayout, layout_id)

    if not layout:
        return jsonify({'error': 'Layout not found'}), 404

    # Build query with optional filters
    query = ScreenLayer.query.filter_by(layout_id=layout_id)

    # Filter by visibility
    is_visible = request.args.get('is_visible')
    if is_visible is not None:
        is_visible_bool = is_visible.lower() == 'true'
        query = query.filter_by(is_visible=is_visible_bool)

    # Execute query ordered by z_index
    layers = query.order_by(ScreenLayer.z_index).all()

    return jsonify({
        'layers': [layer.to_dict() for layer in layers],
        'count': len(layers)
    }), 200


@layouts_bp.route('/<layout_id>/layers', methods=['POST'])
def add_layer(layout_id):
    """
    Add a layer to a layout.

    Args:
        layout_id: Layout UUID

    Request Body:
        {
            "name": "Layer Name" (required),
            "layer_type": "content" | "text" | "widget" | "image" (optional, default: "content"),
            "x": 0 (optional, default: 0),
            "y": 0 (optional, default: 0),
            "width": 400 (optional, default: 400),
            "height": 300 (optional, default: 300),
            "z_index": 0 (optional, default: next available z_index),
            "opacity": 1.0 (optional, default: 1.0),
            "background_type": "solid" | "transparent" | "image" (optional, default: "transparent"),
            "background_color": "#000000" (optional),
            "is_visible": true (optional, default: true),
            "is_locked": false (optional, default: false),
            "content_config": "{...}" (optional, JSON string)
        }

    Returns:
        201: Layer added successfully
            { layer data }
        400: Missing required field or invalid data
            {
                "error": "error message"
            }
        404: Layout not found
            {
                "error": "Layout not found"
            }
    """
    # Validate layout_id format
    if not isinstance(layout_id, str) or len(layout_id) > 64:
        return jsonify({
            'error': 'Invalid layout_id format'
        }), 400

    layout = db.session.get(ScreenLayout, layout_id)

    if not layout:
        return jsonify({'error': 'Layout not found'}), 404

    data = request.get_json()

    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    # Validate name
    name = data.get('name')
    if not name:
        return jsonify({'error': 'name is required'}), 400

    if not isinstance(name, str) or len(name) > 255:
        return jsonify({
            'error': 'name must be a string with max 255 characters'
        }), 400

    # Validate layer_type if provided
    layer_type = data.get('layer_type', 'content')
    if layer_type not in VALID_LAYER_TYPES:
        return jsonify({
            'error': f"Invalid layer_type: {layer_type}. Valid values: {', '.join(VALID_LAYER_TYPES)}"
        }), 400

    # Validate x if provided
    x = data.get('x', 0)
    try:
        x = int(x)
    except (TypeError, ValueError):
        return jsonify({'error': 'x must be an integer'}), 400

    # Validate y if provided
    y = data.get('y', 0)
    try:
        y = int(y)
    except (TypeError, ValueError):
        return jsonify({'error': 'y must be an integer'}), 400

    # Validate width if provided
    width = data.get('width', 400)
    try:
        width = int(width)
    except (TypeError, ValueError):
        return jsonify({'error': 'width must be an integer'}), 400

    if width < 1:
        return jsonify({'error': 'width must be at least 1 pixel'}), 400

    # Validate height if provided
    height = data.get('height', 300)
    try:
        height = int(height)
    except (TypeError, ValueError):
        return jsonify({'error': 'height must be an integer'}), 400

    if height < 1:
        return jsonify({'error': 'height must be at least 1 pixel'}), 400

    # Determine z_index
    z_index = data.get('z_index')
    if z_index is None:
        # Get max z_index and add 1
        max_z_index = db.session.query(db.func.max(ScreenLayer.z_index)).filter(
            ScreenLayer.layout_id == layout_id
        ).scalar()
        z_index = (max_z_index or -1) + 1
    else:
        try:
            z_index = int(z_index)
        except (TypeError, ValueError):
            return jsonify({'error': 'z_index must be an integer'}), 400

    # Validate opacity if provided
    opacity = data.get('opacity', 1.0)
    try:
        opacity = float(opacity)
    except (TypeError, ValueError):
        return jsonify({'error': 'opacity must be a number'}), 400

    if not (0.0 <= opacity <= 1.0):
        return jsonify({
            'error': 'opacity must be between 0.0 and 1.0'
        }), 400

    # Validate background_type if provided
    background_type = data.get('background_type', 'transparent')
    if background_type not in VALID_LAYER_BACKGROUND_TYPES:
        return jsonify({
            'error': f"Invalid background_type: {background_type}. Valid values: {', '.join(VALID_LAYER_BACKGROUND_TYPES)}"
        }), 400

    # Handle content_config - serialize to JSON if it's a dict
    import json
    content_config = data.get('content_config')
    if content_config and isinstance(content_config, dict):
        content_config = json.dumps(content_config)

    # Create layer
    layer = ScreenLayer(
        layout_id=layout_id,
        name=name,
        layer_type=layer_type,
        x=x,
        y=y,
        width=width,
        height=height,
        z_index=z_index,
        opacity=opacity,
        background_type=background_type,
        background_color=data.get('background_color'),
        is_visible=data.get('is_visible', True),
        is_locked=data.get('is_locked', False),
        content_source=data.get('content_source', 'none'),
        playlist_id=data.get('playlist_id'),
        content_id=data.get('content_id'),
        is_primary=data.get('is_primary', False),
        content_config=content_config
    )

    try:
        db.session.add(layer)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to add layer: {str(e)}'
        }), 500

    return jsonify(layer.to_dict()), 201


@layouts_bp.route('/<layout_id>/layers/<layer_id>', methods=['GET'])
def get_layer(layout_id, layer_id):
    """
    Get details for a specific layer.

    Args:
        layout_id: Layout UUID
        layer_id: Layer UUID

    Returns:
        200: Layer data
            { layer data }
        400: Invalid ID format
            {
                "error": "Invalid ID format"
            }
        404: Layout or layer not found
            {
                "error": "error message"
            }
    """
    # Validate layout_id format
    if not isinstance(layout_id, str) or len(layout_id) > 64:
        return jsonify({
            'error': 'Invalid layout_id format'
        }), 400

    # Validate layer_id format
    if not isinstance(layer_id, str) or len(layer_id) > 64:
        return jsonify({
            'error': 'Invalid layer_id format'
        }), 400

    layout = db.session.get(ScreenLayout, layout_id)

    if not layout:
        return jsonify({'error': 'Layout not found'}), 404

    # Find the layer
    layer = ScreenLayer.query.filter_by(
        id=layer_id,
        layout_id=layout_id
    ).first()

    if not layer:
        return jsonify({'error': 'Layer not found'}), 404

    return jsonify(layer.to_dict()), 200


@layouts_bp.route('/<layout_id>/layers/<layer_id>', methods=['PUT'])
def update_layer(layout_id, layer_id):
    """
    Update a layer.

    Args:
        layout_id: Layout UUID
        layer_id: Layer UUID

    Request Body:
        {
            "name": "Updated Name" (optional),
            "layer_type": "content" | "text" | "widget" | "image" (optional),
            "x": 0 (optional),
            "y": 0 (optional),
            "width": 400 (optional),
            "height": 300 (optional),
            "z_index": 0 (optional),
            "opacity": 1.0 (optional),
            "background_type": "solid" | "transparent" | "image" (optional),
            "background_color": "#000000" (optional),
            "is_visible": true/false (optional),
            "is_locked": true/false (optional),
            "content_config": "{...}" (optional)
        }

    Returns:
        200: Layer updated successfully
            { updated layer data }
        400: Invalid data
            {
                "error": "error message"
            }
        404: Layout or layer not found
            {
                "error": "error message"
            }
    """
    # Validate layout_id format
    if not isinstance(layout_id, str) or len(layout_id) > 64:
        return jsonify({
            'error': 'Invalid layout_id format'
        }), 400

    # Validate layer_id format
    if not isinstance(layer_id, str) or len(layer_id) > 64:
        return jsonify({
            'error': 'Invalid layer_id format'
        }), 400

    layout = db.session.get(ScreenLayout, layout_id)

    if not layout:
        return jsonify({'error': 'Layout not found'}), 404

    # Find the layer
    layer = ScreenLayer.query.filter_by(
        id=layer_id,
        layout_id=layout_id
    ).first()

    if not layer:
        return jsonify({'error': 'Layer not found'}), 404

    data = request.get_json()

    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    # Update name if provided
    if 'name' in data:
        name = data['name']
        if not isinstance(name, str) or len(name) > 255:
            return jsonify({
                'error': 'name must be a string with max 255 characters'
            }), 400
        layer.name = name

    # Update layer_type if provided
    if 'layer_type' in data:
        layer_type = data['layer_type']
        if layer_type not in VALID_LAYER_TYPES:
            return jsonify({
                'error': f"Invalid layer_type: {layer_type}. Valid values: {', '.join(VALID_LAYER_TYPES)}"
            }), 400
        layer.layer_type = layer_type

    # Update x if provided
    if 'x' in data:
        try:
            layer.x = int(data['x'])
        except (TypeError, ValueError):
            return jsonify({'error': 'x must be an integer'}), 400

    # Update y if provided
    if 'y' in data:
        try:
            layer.y = int(data['y'])
        except (TypeError, ValueError):
            return jsonify({'error': 'y must be an integer'}), 400

    # Update width if provided
    if 'width' in data:
        try:
            width = int(data['width'])
        except (TypeError, ValueError):
            return jsonify({'error': 'width must be an integer'}), 400

        if width < 1:
            return jsonify({'error': 'width must be at least 1 pixel'}), 400
        layer.width = width

    # Update height if provided
    if 'height' in data:
        try:
            height = int(data['height'])
        except (TypeError, ValueError):
            return jsonify({'error': 'height must be an integer'}), 400

        if height < 1:
            return jsonify({'error': 'height must be at least 1 pixel'}), 400
        layer.height = height

    # Update z_index if provided
    if 'z_index' in data:
        try:
            layer.z_index = int(data['z_index'])
        except (TypeError, ValueError):
            return jsonify({'error': 'z_index must be an integer'}), 400

    # Update opacity if provided
    if 'opacity' in data:
        try:
            opacity = float(data['opacity'])
        except (TypeError, ValueError):
            return jsonify({'error': 'opacity must be a number'}), 400

        if not (0.0 <= opacity <= 1.0):
            return jsonify({
                'error': 'opacity must be between 0.0 and 1.0'
            }), 400
        layer.opacity = opacity

    # Update background_type if provided
    if 'background_type' in data:
        background_type = data['background_type']
        if background_type not in VALID_LAYER_BACKGROUND_TYPES:
            return jsonify({
                'error': f"Invalid background_type: {background_type}. Valid values: {', '.join(VALID_LAYER_BACKGROUND_TYPES)}"
            }), 400
        layer.background_type = background_type

    # Update background_color if provided
    if 'background_color' in data:
        layer.background_color = data['background_color']

    # Update is_visible if provided
    if 'is_visible' in data:
        layer.is_visible = bool(data['is_visible'])

    # Update is_locked if provided
    if 'is_locked' in data:
        layer.is_locked = bool(data['is_locked'])

    # Update content_source if provided
    if 'content_source' in data:
        valid_sources = ['none', 'playlist', 'static', 'widget']
        if data['content_source'] not in valid_sources:
            return jsonify({
                'error': f"Invalid content_source. Valid values: {', '.join(valid_sources)}"
            }), 400
        layer.content_source = data['content_source']

    # Update playlist_id if provided
    if 'playlist_id' in data:
        layer.playlist_id = data['playlist_id'] if data['playlist_id'] else None

    # Update content_id if provided
    if 'content_id' in data:
        layer.content_id = data['content_id'] if data['content_id'] else None

    # Update is_primary if provided
    if 'is_primary' in data:
        is_primary = bool(data['is_primary'])
        if is_primary:
            # Clear is_primary on all other layers in this layout
            ScreenLayer.query.filter(
                ScreenLayer.layout_id == layout_id,
                ScreenLayer.id != layer_id
            ).update({'is_primary': False})
        layer.is_primary = is_primary

    # Update content_config if provided
    if 'content_config' in data:
        import json
        content_config = data['content_config']
        if content_config and isinstance(content_config, dict):
            content_config = json.dumps(content_config)
        layer.content_config = content_config

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to update layer: {str(e)}'
        }), 500

    return jsonify(layer.to_dict()), 200


@layouts_bp.route('/<layout_id>/layers/<layer_id>', methods=['DELETE'])
def delete_layer(layout_id, layer_id):
    """
    Delete a layer from a layout.

    Args:
        layout_id: Layout UUID
        layer_id: Layer UUID

    Returns:
        200: Layer deleted successfully
            {
                "message": "Layer deleted successfully",
                "id": "uuid"
            }
        400: Invalid ID format
            {
                "error": "Invalid ID format"
            }
        404: Layout or layer not found
            {
                "error": "error message"
            }
    """
    # Validate layout_id format
    if not isinstance(layout_id, str) or len(layout_id) > 64:
        return jsonify({
            'error': 'Invalid layout_id format'
        }), 400

    # Validate layer_id format
    if not isinstance(layer_id, str) or len(layer_id) > 64:
        return jsonify({
            'error': 'Invalid layer_id format'
        }), 400

    layout = db.session.get(ScreenLayout, layout_id)

    if not layout:
        return jsonify({'error': 'Layout not found'}), 404

    # Find the layer
    layer = ScreenLayer.query.filter_by(
        id=layer_id,
        layout_id=layout_id
    ).first()

    if not layer:
        return jsonify({'error': 'Layer not found'}), 404

    # Store info for response
    layer_id_response = layer.id

    try:
        db.session.delete(layer)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to delete layer: {str(e)}'
        }), 500

    return jsonify({
        'message': 'Layer deleted successfully',
        'id': layer_id_response
    }), 200


@layouts_bp.route('/<layout_id>/layers/reorder', methods=['PUT'])
def reorder_layers(layout_id):
    """
    Reorder layers in a layout by updating their z_index values.

    Args:
        layout_id: Layout UUID

    Request Body:
        {
            "layer_ids": ["layer-uuid-1", "layer-uuid-2", ...] (required, new order from bottom to top)
        }

    Returns:
        200: Layers reordered successfully
            {
                "message": "Layers reordered",
                "layers": [ { layer data }, ... ]
            }
        400: Invalid data
            {
                "error": "error message"
            }
        404: Layout or layer not found
            {
                "error": "error message"
            }
    """
    # Validate layout_id format
    if not isinstance(layout_id, str) or len(layout_id) > 64:
        return jsonify({
            'error': 'Invalid layout_id format'
        }), 400

    layout = db.session.get(ScreenLayout, layout_id)

    if not layout:
        return jsonify({'error': 'Layout not found'}), 404

    data = request.get_json()

    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    # Validate layer_ids
    layer_ids = data.get('layer_ids')
    if not layer_ids or not isinstance(layer_ids, list):
        return jsonify({'error': 'layer_ids array is required'}), 400

    # Verify all layers exist and belong to this layout
    existing_layers = ScreenLayer.query.filter_by(layout_id=layout_id).all()
    existing_ids = {layer.id for layer in existing_layers}

    for lid in layer_ids:
        if lid not in existing_ids:
            return jsonify({
                'error': f'Layer {lid} not found in layout'
            }), 404

    # Update z_index values
    try:
        for z_index, lid in enumerate(layer_ids):
            layer = db.session.get(ScreenLayer, lid)
            if layer:
                layer.z_index = z_index

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to reorder layers: {str(e)}'
        }), 500

    # Get updated layers
    updated_layers = ScreenLayer.query.filter_by(
        layout_id=layout_id
    ).order_by(ScreenLayer.z_index).all()

    return jsonify({
        'message': 'Layers reordered',
        'layers': [layer.to_dict() for layer in updated_layers]
    }), 200


# =============================================================================
# Layer Content Assignment Endpoints
# =============================================================================


@layouts_bp.route('/<layout_id>/layers/<layer_id>/content', methods=['POST'])
def assign_layer_content(layout_id, layer_id):
    """
    Assign static content to a layer for a specific device.

    Creates a content assignment for displaying static files (images, videos, PDFs)
    or ticker content in a layer for a particular device.

    Args:
        layout_id: Layout UUID
        layer_id: Layer UUID

    Request Body:
        {
            "device_id": "uuid-of-device" (required),
            "content_mode": "static" | "ticker" (optional, default: "static"),
            "static_file_id": "uuid-of-content" (optional, for static mode),
            "static_file_url": "path/to/file" (optional, for static mode),
            "pdf_page_duration": 10 (optional, seconds per PDF page, default: 10),
            "ticker_items": "[{...}]" (optional, JSON string for ticker mode),
            "ticker_speed": 100 (optional, pixels per second, default: 100),
            "ticker_direction": "left" | "right" | "up" | "down" (optional, default: "left")
        }

    Returns:
        201: Content assigned successfully
            { layer content data }
        400: Missing required field or invalid data
            {
                "error": "error message"
            }
        404: Layout, layer, or device not found
            {
                "error": "error message"
            }
    """
    # Validate layout_id format
    if not isinstance(layout_id, str) or len(layout_id) > 64:
        return jsonify({
            'error': 'Invalid layout_id format'
        }), 400

    # Validate layer_id format
    if not isinstance(layer_id, str) or len(layer_id) > 64:
        return jsonify({
            'error': 'Invalid layer_id format'
        }), 400

    layout = db.session.get(ScreenLayout, layout_id)
    if not layout:
        return jsonify({'error': 'Layout not found'}), 404

    # Find the layer
    layer = ScreenLayer.query.filter_by(
        id=layer_id,
        layout_id=layout_id
    ).first()

    if not layer:
        return jsonify({'error': 'Layer not found'}), 404

    data = request.get_json()

    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    # Validate device_id
    device_id = data.get('device_id')
    if not device_id:
        return jsonify({'error': 'device_id is required'}), 400

    device = db.session.get(Device, device_id)
    if not device:
        return jsonify({
            'error': f'Device with id {device_id} not found'
        }), 404

    # Check for existing assignment
    existing = LayerContent.query.filter_by(
        device_id=device_id,
        layer_id=layer_id
    ).first()

    if existing:
        return jsonify({
            'error': 'Content is already assigned to this layer for this device',
            'content': existing.to_dict()
        }), 400

    # Validate content_mode if provided
    content_mode = data.get('content_mode', 'static')
    if content_mode not in CONTENT_MODES:
        return jsonify({
            'error': f"Invalid content_mode: {content_mode}. Valid values: {', '.join(CONTENT_MODES)}"
        }), 400

    # Validate ticker_direction if provided
    ticker_direction = data.get('ticker_direction', 'left')
    if ticker_direction not in TICKER_DIRECTIONS:
        return jsonify({
            'error': f"Invalid ticker_direction: {ticker_direction}. Valid values: {', '.join(TICKER_DIRECTIONS)}"
        }), 400

    # Validate pdf_page_duration if provided
    pdf_page_duration = data.get('pdf_page_duration', 10)
    try:
        pdf_page_duration = int(pdf_page_duration)
    except (TypeError, ValueError):
        return jsonify({
            'error': 'pdf_page_duration must be an integer'
        }), 400

    if pdf_page_duration < 1:
        return jsonify({
            'error': 'pdf_page_duration must be at least 1 second'
        }), 400

    # Validate ticker_speed if provided
    ticker_speed = data.get('ticker_speed', 100)
    try:
        ticker_speed = int(ticker_speed)
    except (TypeError, ValueError):
        return jsonify({
            'error': 'ticker_speed must be an integer'
        }), 400

    if ticker_speed < 1:
        return jsonify({
            'error': 'ticker_speed must be at least 1 pixel per second'
        }), 400

    # Create layer content assignment
    layer_content = LayerContent(
        device_id=device_id,
        layer_id=layer_id,
        content_mode=content_mode,
        static_file_id=data.get('static_file_id'),
        static_file_url=data.get('static_file_url'),
        pdf_page_duration=pdf_page_duration,
        ticker_items=data.get('ticker_items'),
        ticker_speed=ticker_speed,
        ticker_direction=ticker_direction
    )

    try:
        db.session.add(layer_content)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to assign content to layer: {str(e)}'
        }), 500

    return jsonify(layer_content.to_dict()), 201


@layouts_bp.route('/<layout_id>/layers/<layer_id>/content', methods=['GET'])
def list_layer_content(layout_id, layer_id):
    """
    List all content assignments for a specific layer.

    Args:
        layout_id: Layout UUID
        layer_id: Layer UUID

    Query Parameters:
        device_id: Filter by device UUID
        content_mode: Filter by content mode (static/ticker)

    Returns:
        200: List of content assignments
            {
                "content": [ { content data }, ... ],
                "count": 5
            }
        400: Invalid ID format
            {
                "error": "Invalid ID format"
            }
        404: Layout or layer not found
            {
                "error": "error message"
            }
    """
    # Validate layout_id format
    if not isinstance(layout_id, str) or len(layout_id) > 64:
        return jsonify({
            'error': 'Invalid layout_id format'
        }), 400

    # Validate layer_id format
    if not isinstance(layer_id, str) or len(layer_id) > 64:
        return jsonify({
            'error': 'Invalid layer_id format'
        }), 400

    layout = db.session.get(ScreenLayout, layout_id)
    if not layout:
        return jsonify({'error': 'Layout not found'}), 404

    # Find the layer
    layer = ScreenLayer.query.filter_by(
        id=layer_id,
        layout_id=layout_id
    ).first()

    if not layer:
        return jsonify({'error': 'Layer not found'}), 404

    # Build query with optional filters
    query = LayerContent.query.filter_by(layer_id=layer_id)

    # Filter by device
    device_id = request.args.get('device_id')
    if device_id:
        query = query.filter_by(device_id=device_id)

    # Filter by content_mode
    content_mode = request.args.get('content_mode')
    if content_mode:
        if content_mode not in CONTENT_MODES:
            return jsonify({
                'error': f"Invalid content_mode: {content_mode}. Valid values: {', '.join(CONTENT_MODES)}"
            }), 400
        query = query.filter_by(content_mode=content_mode)

    # Execute query
    content_list = query.all()

    return jsonify({
        'content': [c.to_dict() for c in content_list],
        'count': len(content_list)
    }), 200


@layouts_bp.route('/<layout_id>/layers/<layer_id>/content/<content_id>', methods=['GET'])
def get_layer_content(layout_id, layer_id, content_id):
    """
    Get details for a specific layer content assignment.

    Args:
        layout_id: Layout UUID
        layer_id: Layer UUID
        content_id: LayerContent UUID

    Returns:
        200: Content assignment data
            { content data }
        400: Invalid ID format
            {
                "error": "Invalid ID format"
            }
        404: Layout, layer, or content assignment not found
            {
                "error": "error message"
            }
    """
    # Validate layout_id format
    if not isinstance(layout_id, str) or len(layout_id) > 64:
        return jsonify({
            'error': 'Invalid layout_id format'
        }), 400

    # Validate layer_id format
    if not isinstance(layer_id, str) or len(layer_id) > 64:
        return jsonify({
            'error': 'Invalid layer_id format'
        }), 400

    # Validate content_id format
    if not isinstance(content_id, str) or len(content_id) > 64:
        return jsonify({
            'error': 'Invalid content_id format'
        }), 400

    layout = db.session.get(ScreenLayout, layout_id)
    if not layout:
        return jsonify({'error': 'Layout not found'}), 404

    # Find the layer
    layer = ScreenLayer.query.filter_by(
        id=layer_id,
        layout_id=layout_id
    ).first()

    if not layer:
        return jsonify({'error': 'Layer not found'}), 404

    # Find the content assignment
    layer_content = LayerContent.query.filter_by(
        id=content_id,
        layer_id=layer_id
    ).first()

    if not layer_content:
        return jsonify({'error': 'Content assignment not found'}), 404

    return jsonify(layer_content.to_dict_with_relations()), 200


@layouts_bp.route('/<layout_id>/layers/<layer_id>/content/<content_id>', methods=['PUT'])
def update_layer_content(layout_id, layer_id, content_id):
    """
    Update a layer content assignment.

    Args:
        layout_id: Layout UUID
        layer_id: Layer UUID
        content_id: LayerContent UUID

    Request Body:
        {
            "content_mode": "static" | "ticker" (optional),
            "static_file_id": "uuid-of-content" (optional),
            "static_file_url": "path/to/file" (optional),
            "pdf_page_duration": 10 (optional),
            "ticker_items": "[{...}]" (optional),
            "ticker_speed": 100 (optional),
            "ticker_direction": "left" | "right" | "up" | "down" (optional)
        }

    Returns:
        200: Content assignment updated successfully
            { updated content data }
        400: Invalid data
            {
                "error": "error message"
            }
        404: Layout, layer, or content assignment not found
            {
                "error": "error message"
            }
    """
    # Validate layout_id format
    if not isinstance(layout_id, str) or len(layout_id) > 64:
        return jsonify({
            'error': 'Invalid layout_id format'
        }), 400

    # Validate layer_id format
    if not isinstance(layer_id, str) or len(layer_id) > 64:
        return jsonify({
            'error': 'Invalid layer_id format'
        }), 400

    # Validate content_id format
    if not isinstance(content_id, str) or len(content_id) > 64:
        return jsonify({
            'error': 'Invalid content_id format'
        }), 400

    layout = db.session.get(ScreenLayout, layout_id)
    if not layout:
        return jsonify({'error': 'Layout not found'}), 404

    # Find the layer
    layer = ScreenLayer.query.filter_by(
        id=layer_id,
        layout_id=layout_id
    ).first()

    if not layer:
        return jsonify({'error': 'Layer not found'}), 404

    # Find the content assignment
    layer_content = LayerContent.query.filter_by(
        id=content_id,
        layer_id=layer_id
    ).first()

    if not layer_content:
        return jsonify({'error': 'Content assignment not found'}), 404

    data = request.get_json()

    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    # Update content_mode if provided
    if 'content_mode' in data:
        content_mode = data['content_mode']
        if content_mode not in CONTENT_MODES:
            return jsonify({
                'error': f"Invalid content_mode: {content_mode}. Valid values: {', '.join(CONTENT_MODES)}"
            }), 400
        layer_content.content_mode = content_mode

    # Update static_file_id if provided
    if 'static_file_id' in data:
        layer_content.static_file_id = data['static_file_id']

    # Update static_file_url if provided
    if 'static_file_url' in data:
        layer_content.static_file_url = data['static_file_url']

    # Update pdf_page_duration if provided
    if 'pdf_page_duration' in data:
        try:
            pdf_page_duration = int(data['pdf_page_duration'])
        except (TypeError, ValueError):
            return jsonify({
                'error': 'pdf_page_duration must be an integer'
            }), 400

        if pdf_page_duration < 1:
            return jsonify({
                'error': 'pdf_page_duration must be at least 1 second'
            }), 400
        layer_content.pdf_page_duration = pdf_page_duration

    # Update ticker_items if provided
    if 'ticker_items' in data:
        layer_content.ticker_items = data['ticker_items']

    # Update ticker_speed if provided
    if 'ticker_speed' in data:
        try:
            ticker_speed = int(data['ticker_speed'])
        except (TypeError, ValueError):
            return jsonify({
                'error': 'ticker_speed must be an integer'
            }), 400

        if ticker_speed < 1:
            return jsonify({
                'error': 'ticker_speed must be at least 1 pixel per second'
            }), 400
        layer_content.ticker_speed = ticker_speed

    # Update ticker_direction if provided
    if 'ticker_direction' in data:
        ticker_direction = data['ticker_direction']
        if ticker_direction not in TICKER_DIRECTIONS:
            return jsonify({
                'error': f"Invalid ticker_direction: {ticker_direction}. Valid values: {', '.join(TICKER_DIRECTIONS)}"
            }), 400
        layer_content.ticker_direction = ticker_direction

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to update content assignment: {str(e)}'
        }), 500

    return jsonify(layer_content.to_dict()), 200


@layouts_bp.route('/<layout_id>/layers/<layer_id>/content/<content_id>', methods=['DELETE'])
def remove_layer_content(layout_id, layer_id, content_id):
    """
    Remove a content assignment from a layer.

    Args:
        layout_id: Layout UUID
        layer_id: Layer UUID
        content_id: LayerContent UUID

    Returns:
        200: Content assignment removed successfully
            {
                "message": "Content assignment removed",
                "id": "uuid"
            }
        400: Invalid ID format
            {
                "error": "Invalid ID format"
            }
        404: Layout, layer, or content assignment not found
            {
                "error": "error message"
            }
    """
    # Validate layout_id format
    if not isinstance(layout_id, str) or len(layout_id) > 64:
        return jsonify({
            'error': 'Invalid layout_id format'
        }), 400

    # Validate layer_id format
    if not isinstance(layer_id, str) or len(layer_id) > 64:
        return jsonify({
            'error': 'Invalid layer_id format'
        }), 400

    # Validate content_id format
    if not isinstance(content_id, str) or len(content_id) > 64:
        return jsonify({
            'error': 'Invalid content_id format'
        }), 400

    layout = db.session.get(ScreenLayout, layout_id)
    if not layout:
        return jsonify({'error': 'Layout not found'}), 404

    # Find the layer
    layer = ScreenLayer.query.filter_by(
        id=layer_id,
        layout_id=layout_id
    ).first()

    if not layer:
        return jsonify({'error': 'Layer not found'}), 404

    # Find the content assignment
    layer_content = LayerContent.query.filter_by(
        id=content_id,
        layer_id=layer_id
    ).first()

    if not layer_content:
        return jsonify({'error': 'Content assignment not found'}), 404

    # Store id for response
    content_id_response = layer_content.id

    try:
        db.session.delete(layer_content)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to remove content assignment: {str(e)}'
        }), 500

    return jsonify({
        'message': 'Content assignment removed',
        'id': content_id_response
    }), 200


# =============================================================================
# Layer Playlist Assignment Endpoints
# =============================================================================


@layouts_bp.route('/<layout_id>/layers/<layer_id>/playlists', methods=['POST'])
def assign_layer_playlist(layout_id, layer_id):
    """
    Assign a playlist to a layer for a specific device with trigger-based activation.

    Creates a playlist assignment for displaying playlist content in a layer.
    Multiple playlists can be assigned with different triggers and priorities.

    Args:
        layout_id: Layout UUID
        layer_id: Layer UUID

    Request Body:
        {
            "device_id": "uuid-of-device" (required),
            "playlist_id": "uuid-of-playlist" (required),
            "trigger_type": "default" | "face_detected" | "age_child" | ... (optional, default: "default"),
            "priority": 0 (optional, default: 0)
        }

    Returns:
        201: Playlist assigned successfully
            { playlist assignment data }
        400: Missing required field or invalid data
            {
                "error": "error message"
            }
        404: Layout, layer, device, or playlist not found
            {
                "error": "error message"
            }
    """
    # Validate layout_id format
    if not isinstance(layout_id, str) or len(layout_id) > 64:
        return jsonify({
            'error': 'Invalid layout_id format'
        }), 400

    # Validate layer_id format
    if not isinstance(layer_id, str) or len(layer_id) > 64:
        return jsonify({
            'error': 'Invalid layer_id format'
        }), 400

    layout = db.session.get(ScreenLayout, layout_id)
    if not layout:
        return jsonify({'error': 'Layout not found'}), 404

    # Find the layer
    layer = ScreenLayer.query.filter_by(
        id=layer_id,
        layout_id=layout_id
    ).first()

    if not layer:
        return jsonify({'error': 'Layer not found'}), 404

    data = request.get_json()

    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    # Validate device_id
    device_id = data.get('device_id')
    if not device_id:
        return jsonify({'error': 'device_id is required'}), 400

    device = db.session.get(Device, device_id)
    if not device:
        return jsonify({
            'error': f'Device with id {device_id} not found'
        }), 404

    # Validate playlist_id
    playlist_id = data.get('playlist_id')
    if not playlist_id:
        return jsonify({'error': 'playlist_id is required'}), 400

    playlist = db.session.get(Playlist, playlist_id)
    if not playlist:
        return jsonify({
            'error': f'Playlist with id {playlist_id} not found'
        }), 404

    # Check for existing assignment with same device, layer, and playlist
    existing = LayerPlaylistAssignment.query.filter_by(
        device_id=device_id,
        layer_id=layer_id,
        playlist_id=playlist_id
    ).first()

    if existing:
        return jsonify({
            'error': 'This playlist is already assigned to this layer for this device',
            'assignment': existing.to_dict()
        }), 400

    # Validate trigger_type if provided
    trigger_type = data.get('trigger_type', 'default')
    if trigger_type not in LAYER_TRIGGER_TYPES:
        return jsonify({
            'error': f"Invalid trigger_type: {trigger_type}. Valid values: {', '.join(LAYER_TRIGGER_TYPES)}"
        }), 400

    # Parse priority
    priority = data.get('priority', 0)
    try:
        priority = int(priority)
    except (TypeError, ValueError):
        return jsonify({
            'error': 'priority must be an integer'
        }), 400

    # Create layer playlist assignment
    assignment = LayerPlaylistAssignment(
        device_id=device_id,
        layer_id=layer_id,
        playlist_id=playlist_id,
        trigger_type=trigger_type,
        priority=priority
    )

    try:
        db.session.add(assignment)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to assign playlist to layer: {str(e)}'
        }), 500

    return jsonify(assignment.to_dict_with_relations()), 201


@layouts_bp.route('/<layout_id>/layers/<layer_id>/playlists', methods=['GET'])
def list_layer_playlists(layout_id, layer_id):
    """
    List all playlist assignments for a specific layer.

    Args:
        layout_id: Layout UUID
        layer_id: Layer UUID

    Query Parameters:
        device_id: Filter by device UUID
        trigger_type: Filter by trigger type

    Returns:
        200: List of playlist assignments
            {
                "assignments": [ { assignment data }, ... ],
                "count": 5
            }
        400: Invalid ID format
            {
                "error": "Invalid ID format"
            }
        404: Layout or layer not found
            {
                "error": "error message"
            }
    """
    # Validate layout_id format
    if not isinstance(layout_id, str) or len(layout_id) > 64:
        return jsonify({
            'error': 'Invalid layout_id format'
        }), 400

    # Validate layer_id format
    if not isinstance(layer_id, str) or len(layer_id) > 64:
        return jsonify({
            'error': 'Invalid layer_id format'
        }), 400

    layout = db.session.get(ScreenLayout, layout_id)
    if not layout:
        return jsonify({'error': 'Layout not found'}), 404

    # Find the layer
    layer = ScreenLayer.query.filter_by(
        id=layer_id,
        layout_id=layout_id
    ).first()

    if not layer:
        return jsonify({'error': 'Layer not found'}), 404

    # Build query with optional filters
    query = LayerPlaylistAssignment.query.filter_by(layer_id=layer_id)

    # Filter by device
    device_id = request.args.get('device_id')
    if device_id:
        query = query.filter_by(device_id=device_id)

    # Filter by trigger_type
    trigger_type = request.args.get('trigger_type')
    if trigger_type:
        if trigger_type not in LAYER_TRIGGER_TYPES:
            return jsonify({
                'error': f"Invalid trigger_type: {trigger_type}. Valid values: {', '.join(LAYER_TRIGGER_TYPES)}"
            }), 400
        query = query.filter_by(trigger_type=trigger_type)

    # Execute query ordered by priority
    assignments = query.order_by(LayerPlaylistAssignment.priority.desc()).all()

    return jsonify({
        'assignments': [a.to_dict_with_relations() for a in assignments],
        'count': len(assignments)
    }), 200


@layouts_bp.route('/<layout_id>/layers/<layer_id>/playlists/<assignment_id>', methods=['DELETE'])
def remove_layer_playlist(layout_id, layer_id, assignment_id):
    """
    Remove a playlist assignment from a layer.

    Args:
        layout_id: Layout UUID
        layer_id: Layer UUID
        assignment_id: LayerPlaylistAssignment UUID

    Returns:
        200: Playlist assignment removed successfully
            {
                "message": "Playlist assignment removed",
                "id": "uuid"
            }
        400: Invalid ID format
            {
                "error": "Invalid ID format"
            }
        404: Layout, layer, or assignment not found
            {
                "error": "error message"
            }
    """
    # Validate layout_id format
    if not isinstance(layout_id, str) or len(layout_id) > 64:
        return jsonify({
            'error': 'Invalid layout_id format'
        }), 400

    # Validate layer_id format
    if not isinstance(layer_id, str) or len(layer_id) > 64:
        return jsonify({
            'error': 'Invalid layer_id format'
        }), 400

    # Validate assignment_id format
    if not isinstance(assignment_id, str) or len(assignment_id) > 64:
        return jsonify({
            'error': 'Invalid assignment_id format'
        }), 400

    layout = db.session.get(ScreenLayout, layout_id)
    if not layout:
        return jsonify({'error': 'Layout not found'}), 404

    # Find the layer
    layer = ScreenLayer.query.filter_by(
        id=layer_id,
        layout_id=layout_id
    ).first()

    if not layer:
        return jsonify({'error': 'Layer not found'}), 404

    # Find the assignment
    assignment = LayerPlaylistAssignment.query.filter_by(
        id=assignment_id,
        layer_id=layer_id
    ).first()

    if not assignment:
        return jsonify({'error': 'Playlist assignment not found'}), 404

    # Store id for response
    assignment_id_response = assignment.id

    try:
        db.session.delete(assignment)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to remove playlist assignment: {str(e)}'
        }), 500

    return jsonify({
        'message': 'Playlist assignment removed',
        'id': assignment_id_response
    }), 200


# =============================================================================
# Device Layout Assignment Endpoints
# =============================================================================


@layouts_bp.route('/<layout_id>/assign', methods=['POST'])
def assign_layout_to_device(layout_id):
    """
    Assign a layout to a device with optional scheduling.

    Args:
        layout_id: Layout UUID

    Request Body:
        {
            "device_id": "uuid-of-device" (required),
            "priority": 0 (optional, default: 0),
            "start_date": "2024-01-15T10:00:00Z" (optional),
            "end_date": "2024-12-31T23:59:59Z" (optional)
        }

    Returns:
        201: Assignment created successfully
            { assignment data }
        400: Missing required field or invalid data
            {
                "error": "error message"
            }
        404: Layout or device not found
            {
                "error": "error message"
            }
    """
    # Validate layout_id format
    if not isinstance(layout_id, str) or len(layout_id) > 64:
        return jsonify({
            'error': 'Invalid layout_id format'
        }), 400

    layout = db.session.get(ScreenLayout, layout_id)

    if not layout:
        return jsonify({'error': 'Layout not found'}), 404

    data = request.get_json()

    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    # Validate device_id
    device_id = data.get('device_id')
    if not device_id:
        return jsonify({'error': 'device_id is required'}), 400

    device = db.session.get(Device, device_id)
    if not device:
        return jsonify({
            'error': f'Device with id {device_id} not found'
        }), 404

    # Check for existing assignment
    existing = DeviceLayout.query.filter_by(
        device_id=device_id,
        layout_id=layout_id
    ).first()

    if existing:
        return jsonify({
            'error': 'Layout is already assigned to this device',
            'assignment': existing.to_dict()
        }), 400

    # Parse priority
    priority = data.get('priority', 0)
    try:
        priority = int(priority)
    except (TypeError, ValueError):
        return jsonify({
            'error': 'priority must be an integer'
        }), 400

    # Parse dates
    start_date = _parse_datetime(data.get('start_date'))
    end_date = _parse_datetime(data.get('end_date'))

    # Validate date range
    if start_date and end_date and start_date > end_date:
        return jsonify({
            'error': 'start_date must be before end_date'
        }), 400

    # Create assignment
    assignment = DeviceLayout(
        device_id=device_id,
        layout_id=layout_id,
        priority=priority,
        start_date=start_date,
        end_date=end_date
    )

    try:
        db.session.add(assignment)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to create assignment: {str(e)}'
        }), 500

    return jsonify(assignment.to_dict_with_relations()), 201


@layouts_bp.route('/<layout_id>/assign/<assignment_id>', methods=['DELETE'])
def remove_device_layout_assignment(layout_id, assignment_id):
    """
    Remove a device assignment from a layout.

    Args:
        layout_id: Layout UUID
        assignment_id: DeviceLayout UUID

    Returns:
        200: Assignment removed successfully
            {
                "message": "Assignment removed",
                "id": "uuid"
            }
        400: Invalid ID format
            {
                "error": "Invalid ID format"
            }
        404: Layout or assignment not found
            {
                "error": "error message"
            }
    """
    # Validate layout_id format
    if not isinstance(layout_id, str) or len(layout_id) > 64:
        return jsonify({
            'error': 'Invalid layout_id format'
        }), 400

    # Validate assignment_id format
    if not isinstance(assignment_id, str) or len(assignment_id) > 64:
        return jsonify({
            'error': 'Invalid assignment_id format'
        }), 400

    layout = db.session.get(ScreenLayout, layout_id)

    if not layout:
        return jsonify({'error': 'Layout not found'}), 404

    # Find the assignment
    assignment = DeviceLayout.query.filter_by(
        id=assignment_id,
        layout_id=layout_id
    ).first()

    if not assignment:
        return jsonify({'error': 'Assignment not found'}), 404

    # Store id for response
    assignment_id_response = assignment.id

    try:
        db.session.delete(assignment)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to remove assignment: {str(e)}'
        }), 500

    return jsonify({
        'message': 'Assignment removed',
        'id': assignment_id_response
    }), 200


@layouts_bp.route('/<layout_id>/assignments', methods=['GET'])
def list_layout_assignments(layout_id):
    """
    List all device assignments for a layout.

    Args:
        layout_id: Layout UUID

    Returns:
        200: List of assignments
            {
                "assignments": [ { assignment data }, ... ],
                "count": 5
            }
        400: Invalid layout_id format
            {
                "error": "Invalid layout_id format"
            }
        404: Layout not found
            {
                "error": "Layout not found"
            }
    """
    # Validate layout_id format
    if not isinstance(layout_id, str) or len(layout_id) > 64:
        return jsonify({
            'error': 'Invalid layout_id format'
        }), 400

    layout = db.session.get(ScreenLayout, layout_id)

    if not layout:
        return jsonify({'error': 'Layout not found'}), 404

    assignments = DeviceLayout.query.filter_by(
        layout_id=layout_id
    ).all()

    return jsonify({
        'assignments': [a.to_dict_with_relations() for a in assignments],
        'count': len(assignments)
    }), 200


# =============================================================================
# Layout Push/Sync Endpoints
# =============================================================================


@layouts_bp.route('/<layout_id>/push', methods=['POST'])
def push_layout_to_device(layout_id):
    """
    Push a layout (with all associated content) to a device.

    This endpoint bundles the layout configuration along with all content
    files referenced by the layout's layers (playlists, static content, etc.)
    and initiates a sync to the specified device.

    The content is uploaded to the device's local storage so it can play
    offline without requiring an internet connection.

    Args:
        layout_id: Layout UUID

    Request Body:
        {
            "device_id": "uuid-of-device" (required)
        }

    Returns:
        200: Push initiated successfully
            {
                "status": "success",
                "message": "Layout push initiated",
                "layout_id": "...",
                "device_id": "...",
                "content_files": [...],  # List of content files to sync
                "assignment_id": "..."   # DeviceLayout assignment ID
            }
        400: Missing required field or invalid data
        404: Layout or device not found
    """
    import json

    # Validate layout_id format
    if not isinstance(layout_id, str) or len(layout_id) > 64:
        return jsonify({'error': 'Invalid layout_id format'}), 400

    layout = db.session.get(ScreenLayout, layout_id)
    if not layout:
        return jsonify({'error': 'Layout not found'}), 404

    data = request.get_json()
    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    # Validate device_id
    device_id = data.get('device_id')
    if not device_id:
        return jsonify({'error': 'device_id is required'}), 400

    device = db.session.get(Device, device_id)
    if not device:
        return jsonify({'error': f'Device with id {device_id} not found'}), 404

    # Get all layers for this layout
    layers = ScreenLayer.query.filter_by(layout_id=layout_id).order_by(ScreenLayer.z_index).all()

    # Collect all content that needs to be synced
    content_to_sync = set()
    playlists_to_sync = []

    for layer in layers:
        # Check for direct content assignment on layer
        if layer.content_id:
            content_to_sync.add(layer.content_id)

        # Check for playlist assignment on layer
        if layer.playlist_id:
            playlist = db.session.get(Playlist, layer.playlist_id)
            if playlist:
                playlists_to_sync.append({
                    'id': playlist.id,
                    'name': playlist.name,
                    'layer_id': layer.id
                })
                # Get all content in the playlist
                from cms.models import PlaylistItem
                items = PlaylistItem.query.filter_by(playlist_id=playlist.id).all()
                for item in items:
                    if item.content_id:
                        content_to_sync.add(item.content_id)

        # Check for LayerContent assignments (device-specific static content)
        layer_contents = LayerContent.query.filter_by(layer_id=layer.id).all()
        for lc in layer_contents:
            if lc.static_file_id:
                content_to_sync.add(lc.static_file_id)

        # Check for LayerPlaylistAssignments (device-specific playlists)
        layer_playlists = LayerPlaylistAssignment.query.filter_by(layer_id=layer.id).all()
        for lp in layer_playlists:
            if lp.playlist_id:
                playlist = db.session.get(Playlist, lp.playlist_id)
                if playlist:
                    playlists_to_sync.append({
                        'id': playlist.id,
                        'name': playlist.name,
                        'layer_id': layer.id,
                        'trigger_type': lp.trigger_type
                    })
                    from cms.models import PlaylistItem
                    items = PlaylistItem.query.filter_by(playlist_id=playlist.id).all()
                    for item in items:
                        if item.content_id:
                            content_to_sync.add(item.content_id)

    # Get content details for sync manifest
    content_files = []
    for content_id in content_to_sync:
        content = db.session.get(Content, content_id)
        if content:
            content_files.append({
                'id': content.id,
                'name': content.original_name,
                'filename': content.filename,
                'type': content.content_type,
                'file_path': content.file_path,
                'file_size': content.file_size,
                'checksum': content.checksum if hasattr(content, 'checksum') else None
            })

    # Create or update DeviceLayout assignment
    assignment = DeviceLayout.query.filter_by(
        device_id=device_id,
        layout_id=layout_id
    ).first()

    if not assignment:
        assignment = DeviceLayout(
            device_id=device_id,
            layout_id=layout_id,
            priority=0
        )
        db.session.add(assignment)

    # Update assignment with sync info
    assignment.last_pushed_at = datetime.now(timezone.utc)

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to create assignment: {str(e)}'}), 500

    # Build layout package manifest
    layout_package = {
        'layout': layout.to_dict(include_layers=True),
        'playlists': playlists_to_sync,
        'content_manifest': content_files,
        'pushed_at': datetime.now(timezone.utc).isoformat()
    }

    return jsonify({
        'status': 'success',
        'message': 'Layout push initiated',
        'layout_id': layout_id,
        'device_id': device_id,
        'device_name': device.name or device.device_id,
        'content_files_count': len(content_files),
        'playlists_count': len(playlists_to_sync),
        'assignment_id': assignment.id,
        'package': layout_package
    }), 200


@layouts_bp.route('/<layout_id>/sync-status', methods=['GET'])
def get_layout_sync_status(layout_id):
    """
    Get the sync status of a layout across all assigned devices.

    Returns information about which devices have this layout and their
    sync status.

    Args:
        layout_id: Layout UUID

    Returns:
        200: Sync status for all assigned devices
            {
                "layout_id": "...",
                "layout_name": "...",
                "device_syncs": [
                    {
                        "device_id": "...",
                        "device_name": "...",
                        "sync_status": "synced|pending|syncing|failed",
                        "last_pushed_at": "...",
                        "last_confirmed_at": "..."
                    }
                ]
            }
        404: Layout not found
    """
    # Validate layout_id format
    if not isinstance(layout_id, str) or len(layout_id) > 64:
        return jsonify({'error': 'Invalid layout_id format'}), 400

    layout = db.session.get(ScreenLayout, layout_id)
    if not layout:
        return jsonify({'error': 'Layout not found'}), 404

    # Get all device assignments for this layout
    assignments = DeviceLayout.query.filter_by(layout_id=layout_id).all()

    device_syncs = []
    for assignment in assignments:
        device = assignment.device
        device_syncs.append({
            'device_id': assignment.device_id,
            'device_name': device.name if device else 'Unknown',
            'device_status': device.status if device else 'unknown',
            'assignment_id': assignment.id,
            'priority': assignment.priority,
            'last_pushed_at': assignment.last_pushed_at.isoformat() if hasattr(assignment, 'last_pushed_at') and assignment.last_pushed_at else None,
            'start_date': assignment.start_date.isoformat() if assignment.start_date else None,
            'end_date': assignment.end_date.isoformat() if assignment.end_date else None
        })

    return jsonify({
        'layout_id': layout_id,
        'layout_name': layout.name,
        'total_devices': len(device_syncs),
        'device_syncs': device_syncs
    }), 200


# =============================================================================
# Web UI Routes
# =============================================================================

# Create layouts web blueprint (no url_prefix for root-level pages)
layouts_web_bp = Blueprint('layouts_web', __name__)


@layouts_web_bp.route('/layouts')
def layouts_page():
    """
    Layout list page.

    Lists all screen layouts with thumbnails and management options.
    Provides access to create new layouts and open the designer.

    Returns:
        Rendered layouts/list.html template with layout list
    """
    layouts = ScreenLayout.query.order_by(ScreenLayout.updated_at.desc()).all()

    # Add layer_count and device_count to each layout for template use
    for layout in layouts:
        layout.layer_count = ScreenLayer.query.filter_by(layout_id=layout.id).count()
        # Get device assignment info
        assignments = DeviceLayout.query.filter_by(layout_id=layout.id).all()
        layout.device_count = len(assignments)
        # Get most recent push time
        pushed_times = [a.last_pushed_at for a in assignments if a.last_pushed_at]
        layout.last_pushed_at = max(pushed_times) if pushed_times else None

    return render_template(
        'layouts/list.html',
        active_page='layouts',
        layouts=layouts
    )


@layouts_web_bp.route('/layouts/<layout_id>/delete', methods=['POST'])
def delete_layout_web(layout_id):
    """
    Delete a layout via form POST (more reliable than JavaScript fetch).
    Redirects back to layouts list after deletion.
    """
    from flask import redirect, url_for, flash

    layout = db.session.get(ScreenLayout, layout_id)

    if not layout:
        flash('Layout not found', 'error')
        return redirect(url_for('layouts_web.layouts_page'))

    layout_name = layout.name

    try:
        # Delete associated DeviceLayout assignments first
        DeviceLayout.query.filter_by(layout_id=layout_id).delete()

        # Delete the layout (layers will cascade)
        db.session.delete(layout)
        db.session.commit()

        flash(f'Layout "{layout_name}" deleted successfully', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'Failed to delete layout: {str(e)}', 'error')

    return redirect(url_for('layouts_web.layouts_page'))


@layouts_web_bp.route('/layouts/<layout_id>/designer')
def layout_designer_page(layout_id):
    """
    Layout designer page with canvas editor.

    Provides a visual canvas editor for creating and editing
    screen layouts with layers, content assignment, and properties.

    Args:
        layout_id: Layout UUID

    Returns:
        Rendered layouts/designer.html template with layout data
    """
    layout = db.session.get(ScreenLayout, layout_id)

    if not layout:
        abort(404)

    # Get layers for this layout (serialized for JavaScript)
    layers_query = ScreenLayer.query.filter_by(
        layout_id=layout_id
    ).order_by(ScreenLayer.z_index).all()
    layers = [layer.to_dict() for layer in layers_query]

    # Get available content for assignment
    content = Content.query.order_by(Content.original_name).all()

    # Get available playlists for assignment
    playlists = Playlist.query.filter_by(is_active=True).order_by(Playlist.name).all()

    # Get template layouts for quick start
    templates = ScreenLayout.query.filter_by(is_template=True).all()

    return render_template(
        'layouts/designer.html',
        active_page='layouts',
        layout=layout,
        layers=layers,
        content=content,
        playlists=playlists,
        templates=templates
    )


@layouts_web_bp.route('/devices/<device_id>/layout')
def device_layout_page(device_id):
    """
    Device layout assignment page.

    Allows assigning and scheduling layouts for a specific device.
    Shows current layout assignments and available layouts.

    Args:
        device_id: Device ID (can be UUID or SKZ-X-XXXX format)

    Returns:
        Rendered layouts/assign.html template with device and layout data
    """
    # Try to find device by device_id (SKZ format) first, then by UUID
    device = Device.query.filter_by(device_id=device_id).first()
    if not device:
        device = db.session.get(Device, device_id)

    if not device:
        abort(404)

    # Get current layout assignments for this device
    assignments = DeviceLayout.query.filter_by(
        device_id=device.id
    ).order_by(DeviceLayout.priority.desc()).all()

    # Enrich assignments with layout data
    device_layouts = []
    for assignment in assignments:
        if assignment.layout:
            device_layouts.append({
                'assignment': assignment,
                'layout': assignment.layout,
                'layer_count': ScreenLayer.query.filter_by(
                    layout_id=assignment.layout_id
                ).count()
            })

    # Get all available layouts for assignment
    available_layouts = ScreenLayout.query.filter_by(
        is_template=False
    ).order_by(ScreenLayout.name).all()

    return render_template(
        'layouts/assign.html',
        active_page='devices',
        device=device,
        device_layouts=device_layouts,
        available_layouts=available_layouts
    )



@layouts_web_bp.route('/layouts/zone-editor-test')
def zone_editor_test():
    """
    Test page for the vanilla JS zone editor.

    This is a standalone test page to verify drag-and-drop
    functionality works correctly without Fabric.js.
    """
    return render_template('layouts/zone_editor_test.html')

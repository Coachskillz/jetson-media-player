"""
Unit tests for CMS Layout model serialization methods.

Tests all layout model to_dict methods:
- ScreenLayout.to_dict() - Layout serialization with optional layers
- ScreenLayer.to_dict() - Layer serialization
- LayerContent.to_dict() - Layer content assignment serialization
- LayerPlaylistAssignment.to_dict() - Layer playlist assignment serialization
- DeviceLayout.to_dict() - Device layout assignment serialization

Each test class covers a specific model with comprehensive
serialization validation including all fields and relationships.
"""

import pytest
from datetime import datetime, timezone

from cms.models import (
    db,
    Device,
    Network,
    Playlist,
    ScreenLayout,
    ScreenLayer,
    LayerContent,
    LayerPlaylistAssignment,
    DeviceLayout,
)


# =============================================================================
# Fixtures for Layout Tests
# =============================================================================

@pytest.fixture(scope='function')
def sample_layout(db_session, sample_network):
    """
    Create a sample ScreenLayout for testing.

    Args:
        db_session: Database session fixture
        sample_network: Network fixture for context

    Returns:
        ScreenLayout instance
    """
    layout = ScreenLayout(
        name='Test Layout',
        description='A test layout for unit testing',
        canvas_width=1920,
        canvas_height=1080,
        orientation='landscape',
        background_type='solid',
        background_color='#000000',
        background_opacity=1.0,
        background_content=None,
        is_template=False,
        thumbnail_path='/thumbnails/test-layout.png'
    )
    db_session.add(layout)
    db_session.commit()
    return layout


@pytest.fixture(scope='function')
def sample_template_layout(db_session):
    """
    Create a sample template ScreenLayout for testing.

    Args:
        db_session: Database session fixture

    Returns:
        ScreenLayout instance marked as template
    """
    layout = ScreenLayout(
        name='Template Layout',
        description='A reusable template layout',
        canvas_width=1080,
        canvas_height=1920,
        orientation='portrait',
        background_type='image',
        background_color='#FFFFFF',
        background_opacity=0.8,
        background_content='/backgrounds/template-bg.jpg',
        is_template=True,
        thumbnail_path='/thumbnails/template-layout.png'
    )
    db_session.add(layout)
    db_session.commit()
    return layout


@pytest.fixture(scope='function')
def sample_layer(db_session, sample_layout):
    """
    Create a sample ScreenLayer for testing.

    Args:
        db_session: Database session fixture
        sample_layout: Layout fixture for foreign key

    Returns:
        ScreenLayer instance
    """
    layer = ScreenLayer(
        layout_id=sample_layout.id,
        name='Main Content Layer',
        layer_type='content',
        x=100,
        y=50,
        width=800,
        height=600,
        z_index=1,
        opacity=1.0,
        background_type='transparent',
        background_color=None,
        is_visible=True,
        is_locked=False,
        content_config='{"fit": "contain"}'
    )
    db_session.add(layer)
    db_session.commit()
    return layer


@pytest.fixture(scope='function')
def sample_layer_styled(db_session, sample_layout):
    """
    Create a sample ScreenLayer with custom styling for testing.

    Args:
        db_session: Database session fixture
        sample_layout: Layout fixture for foreign key

    Returns:
        ScreenLayer instance with styling
    """
    layer = ScreenLayer(
        layout_id=sample_layout.id,
        name='Styled Widget Layer',
        layer_type='widget',
        x=0,
        y=0,
        width=400,
        height=100,
        z_index=10,
        opacity=0.9,
        background_type='solid',
        background_color='#FF5500',
        is_visible=True,
        is_locked=True,
        content_config='{"widget_type": "clock", "format": "24h"}'
    )
    db_session.add(layer)
    db_session.commit()
    return layer


@pytest.fixture(scope='function')
def sample_layer_content(db_session, sample_layer, sample_device_direct):
    """
    Create a sample LayerContent assignment for testing.

    Args:
        db_session: Database session fixture
        sample_layer: Layer fixture for foreign key
        sample_device_direct: Device fixture for foreign key

    Returns:
        LayerContent instance
    """
    layer_content = LayerContent(
        device_id=sample_device_direct.id,
        layer_id=sample_layer.id,
        content_mode='static',
        static_file_id='file-123-abc',
        static_file_url='/content/video.mp4',
        pdf_page_duration=10,
        ticker_items=None,
        ticker_speed=100,
        ticker_direction='left'
    )
    db_session.add(layer_content)
    db_session.commit()
    return layer_content


@pytest.fixture(scope='function')
def sample_layer_content_ticker(db_session, sample_layer, sample_device_direct):
    """
    Create a sample LayerContent assignment in ticker mode for testing.

    Args:
        db_session: Database session fixture
        sample_layer: Layer fixture for foreign key
        sample_device_direct: Device fixture for foreign key

    Returns:
        LayerContent instance in ticker mode
    """
    layer_content = LayerContent(
        device_id=sample_device_direct.id,
        layer_id=sample_layer.id,
        content_mode='ticker',
        static_file_id=None,
        static_file_url=None,
        pdf_page_duration=10,
        ticker_items='["Breaking News!", "Weather Update"]',
        ticker_speed=150,
        ticker_direction='up'
    )
    db_session.add(layer_content)
    db_session.commit()
    return layer_content


@pytest.fixture(scope='function')
def sample_layer_playlist_assignment(db_session, sample_layer, sample_device_direct, sample_playlist):
    """
    Create a sample LayerPlaylistAssignment for testing.

    Args:
        db_session: Database session fixture
        sample_layer: Layer fixture for foreign key
        sample_device_direct: Device fixture for foreign key
        sample_playlist: Playlist fixture for foreign key

    Returns:
        LayerPlaylistAssignment instance
    """
    assignment = LayerPlaylistAssignment(
        device_id=sample_device_direct.id,
        layer_id=sample_layer.id,
        playlist_id=sample_playlist.id,
        trigger_type='default',
        priority=1
    )
    db_session.add(assignment)
    db_session.commit()
    return assignment


@pytest.fixture(scope='function')
def sample_layer_playlist_assignment_trigger(db_session, sample_layer, sample_device_direct, sample_playlist):
    """
    Create a sample LayerPlaylistAssignment with trigger for testing.

    Args:
        db_session: Database session fixture
        sample_layer: Layer fixture for foreign key
        sample_device_direct: Device fixture for foreign key
        sample_playlist: Playlist fixture for foreign key

    Returns:
        LayerPlaylistAssignment instance with trigger
    """
    assignment = LayerPlaylistAssignment(
        device_id=sample_device_direct.id,
        layer_id=sample_layer.id,
        playlist_id=sample_playlist.id,
        trigger_type='face_detected',
        priority=5
    )
    db_session.add(assignment)
    db_session.commit()
    return assignment


@pytest.fixture(scope='function')
def sample_device_layout(db_session, sample_layout, sample_device_direct):
    """
    Create a sample DeviceLayout assignment for testing.

    Args:
        db_session: Database session fixture
        sample_layout: Layout fixture for foreign key
        sample_device_direct: Device fixture for foreign key

    Returns:
        DeviceLayout instance
    """
    device_layout = DeviceLayout(
        device_id=sample_device_direct.id,
        layout_id=sample_layout.id,
        priority=1,
        start_date=None,
        end_date=None
    )
    db_session.add(device_layout)
    db_session.commit()
    return device_layout


@pytest.fixture(scope='function')
def sample_device_layout_scheduled(db_session, sample_layout, sample_device_direct):
    """
    Create a sample DeviceLayout assignment with schedule for testing.

    Args:
        db_session: Database session fixture
        sample_layout: Layout fixture for foreign key
        sample_device_direct: Device fixture for foreign key

    Returns:
        DeviceLayout instance with schedule
    """
    device_layout = DeviceLayout(
        device_id=sample_device_direct.id,
        layout_id=sample_layout.id,
        priority=10,
        start_date=datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        end_date=datetime(2024, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
    )
    db_session.add(device_layout)
    db_session.commit()
    return device_layout


# =============================================================================
# ScreenLayout Model Serialization Tests
# =============================================================================

class TestScreenLayoutSerialization:
    """Tests for ScreenLayout.to_dict() method."""

    def test_to_dict_includes_all_basic_fields(self, app, sample_layout):
        """to_dict should include all basic layout fields."""
        data = sample_layout.to_dict()

        assert 'id' in data
        assert data['id'] == sample_layout.id
        assert data['name'] == 'Test Layout'
        assert data['description'] == 'A test layout for unit testing'
        assert data['canvas_width'] == 1920
        assert data['canvas_height'] == 1080
        assert data['orientation'] == 'landscape'
        assert data['background_type'] == 'solid'
        assert data['background_color'] == '#000000'
        assert data['background_opacity'] == 1.0
        assert data['background_content'] is None
        assert data['is_template'] is False
        assert data['thumbnail_path'] == '/thumbnails/test-layout.png'

    def test_to_dict_includes_timestamps(self, app, sample_layout):
        """to_dict should include properly formatted timestamps."""
        data = sample_layout.to_dict()

        assert 'created_at' in data
        assert 'updated_at' in data
        assert data['created_at'] is not None
        assert data['updated_at'] is not None
        # Timestamps should be ISO format strings
        assert isinstance(data['created_at'], str)
        assert isinstance(data['updated_at'], str)

    def test_to_dict_includes_layer_count(self, app, sample_layout):
        """to_dict should include layer_count field."""
        data = sample_layout.to_dict()

        assert 'layer_count' in data
        assert data['layer_count'] == 0

    def test_to_dict_layer_count_with_layers(self, app, sample_layout, sample_layer, sample_layer_styled):
        """to_dict should reflect accurate layer count when layers exist."""
        data = sample_layout.to_dict()

        assert data['layer_count'] == 2

    def test_to_dict_excludes_layers_by_default(self, app, sample_layout, sample_layer):
        """to_dict should not include layers array by default."""
        data = sample_layout.to_dict()

        assert 'layers' not in data

    def test_to_dict_includes_layers_when_requested(self, app, sample_layout, sample_layer):
        """to_dict should include layers array when include_layers=True."""
        data = sample_layout.to_dict(include_layers=True)

        assert 'layers' in data
        assert isinstance(data['layers'], list)
        assert len(data['layers']) == 1
        assert data['layers'][0]['id'] == sample_layer.id

    def test_to_dict_template_layout(self, app, sample_template_layout):
        """to_dict should correctly serialize template layouts."""
        data = sample_template_layout.to_dict()

        assert data['name'] == 'Template Layout'
        assert data['canvas_width'] == 1080
        assert data['canvas_height'] == 1920
        assert data['orientation'] == 'portrait'
        assert data['background_type'] == 'image'
        assert data['background_color'] == '#FFFFFF'
        assert data['background_opacity'] == 0.8
        assert data['background_content'] == '/backgrounds/template-bg.jpg'
        assert data['is_template'] is True

    def test_to_dict_layers_ordered_by_z_index(self, app, sample_layout, sample_layer, sample_layer_styled):
        """to_dict should return layers ordered by z_index."""
        data = sample_layout.to_dict(include_layers=True)

        # sample_layer has z_index=1, sample_layer_styled has z_index=10
        assert len(data['layers']) == 2
        assert data['layers'][0]['z_index'] == 1
        assert data['layers'][1]['z_index'] == 10


# =============================================================================
# ScreenLayer Model Serialization Tests
# =============================================================================

class TestScreenLayerSerialization:
    """Tests for ScreenLayer.to_dict() method."""

    def test_to_dict_includes_all_fields(self, app, sample_layer):
        """to_dict should include all layer fields."""
        data = sample_layer.to_dict()

        assert 'id' in data
        assert data['id'] == sample_layer.id
        assert data['layout_id'] == sample_layer.layout_id
        assert data['name'] == 'Main Content Layer'
        assert data['layer_type'] == 'content'

    def test_to_dict_includes_geometry_fields(self, app, sample_layer):
        """to_dict should include all geometry fields."""
        data = sample_layer.to_dict()

        assert data['x'] == 100
        assert data['y'] == 50
        assert data['width'] == 800
        assert data['height'] == 600
        assert data['z_index'] == 1

    def test_to_dict_includes_styling_fields(self, app, sample_layer):
        """to_dict should include all styling fields."""
        data = sample_layer.to_dict()

        assert data['opacity'] == 1.0
        assert data['background_type'] == 'transparent'
        assert data['background_color'] is None

    def test_to_dict_includes_visibility_fields(self, app, sample_layer):
        """to_dict should include visibility and lock state."""
        data = sample_layer.to_dict()

        assert data['is_visible'] is True
        assert data['is_locked'] is False

    def test_to_dict_includes_content_config(self, app, sample_layer):
        """to_dict should include content configuration."""
        data = sample_layer.to_dict()

        assert data['content_config'] == '{"fit": "contain"}'

    def test_to_dict_includes_timestamps(self, app, sample_layer):
        """to_dict should include properly formatted timestamps."""
        data = sample_layer.to_dict()

        assert 'created_at' in data
        assert 'updated_at' in data
        assert data['created_at'] is not None
        assert data['updated_at'] is not None

    def test_to_dict_styled_layer(self, app, sample_layer_styled):
        """to_dict should correctly serialize styled layers."""
        data = sample_layer_styled.to_dict()

        assert data['name'] == 'Styled Widget Layer'
        assert data['layer_type'] == 'widget'
        assert data['x'] == 0
        assert data['y'] == 0
        assert data['width'] == 400
        assert data['height'] == 100
        assert data['z_index'] == 10
        assert data['opacity'] == 0.9
        assert data['background_type'] == 'solid'
        assert data['background_color'] == '#FF5500'
        assert data['is_visible'] is True
        assert data['is_locked'] is True
        assert data['content_config'] == '{"widget_type": "clock", "format": "24h"}'


# =============================================================================
# LayerContent Model Serialization Tests
# =============================================================================

class TestLayerContentSerialization:
    """Tests for LayerContent.to_dict() and to_dict_with_relations() methods."""

    def test_to_dict_includes_all_fields(self, app, sample_layer_content):
        """to_dict should include all layer content fields."""
        data = sample_layer_content.to_dict()

        assert 'id' in data
        assert data['id'] == sample_layer_content.id
        assert data['device_id'] == sample_layer_content.device_id
        assert data['layer_id'] == sample_layer_content.layer_id
        assert data['content_mode'] == 'static'

    def test_to_dict_includes_static_file_fields(self, app, sample_layer_content):
        """to_dict should include static file fields."""
        data = sample_layer_content.to_dict()

        assert data['static_file_id'] == 'file-123-abc'
        assert data['static_file_url'] == '/content/video.mp4'
        assert data['pdf_page_duration'] == 10

    def test_to_dict_includes_ticker_fields(self, app, sample_layer_content):
        """to_dict should include ticker fields even in static mode."""
        data = sample_layer_content.to_dict()

        assert data['ticker_items'] is None
        assert data['ticker_speed'] == 100
        assert data['ticker_direction'] == 'left'

    def test_to_dict_includes_timestamps(self, app, sample_layer_content):
        """to_dict should include properly formatted timestamps."""
        data = sample_layer_content.to_dict()

        assert 'created_at' in data
        assert 'updated_at' in data
        assert data['created_at'] is not None
        assert data['updated_at'] is not None

    def test_to_dict_ticker_mode(self, app, sample_layer_content_ticker):
        """to_dict should correctly serialize ticker mode content."""
        data = sample_layer_content_ticker.to_dict()

        assert data['content_mode'] == 'ticker'
        assert data['static_file_id'] is None
        assert data['static_file_url'] is None
        assert data['ticker_items'] == '["Breaking News!", "Weather Update"]'
        assert data['ticker_speed'] == 150
        assert data['ticker_direction'] == 'up'

    def test_to_dict_with_relations_includes_layer(self, app, sample_layer_content):
        """to_dict_with_relations should include nested layer data."""
        data = sample_layer_content.to_dict_with_relations()

        assert 'layer' in data
        assert data['layer'] is not None
        assert data['layer']['id'] == sample_layer_content.layer_id
        assert data['layer']['name'] == 'Main Content Layer'

    def test_to_dict_with_relations_includes_base_fields(self, app, sample_layer_content):
        """to_dict_with_relations should include all base to_dict fields."""
        data = sample_layer_content.to_dict_with_relations()

        assert data['id'] == sample_layer_content.id
        assert data['device_id'] == sample_layer_content.device_id
        assert data['content_mode'] == 'static'


# =============================================================================
# LayerPlaylistAssignment Model Serialization Tests
# =============================================================================

class TestLayerPlaylistAssignmentSerialization:
    """Tests for LayerPlaylistAssignment.to_dict() and to_dict_with_relations() methods."""

    def test_to_dict_includes_all_fields(self, app, sample_layer_playlist_assignment):
        """to_dict should include all assignment fields."""
        data = sample_layer_playlist_assignment.to_dict()

        assert 'id' in data
        assert data['id'] == sample_layer_playlist_assignment.id
        assert data['device_id'] == sample_layer_playlist_assignment.device_id
        assert data['layer_id'] == sample_layer_playlist_assignment.layer_id
        assert data['playlist_id'] == sample_layer_playlist_assignment.playlist_id
        assert data['trigger_type'] == 'default'
        assert data['priority'] == 1

    def test_to_dict_includes_timestamps(self, app, sample_layer_playlist_assignment):
        """to_dict should include properly formatted timestamp."""
        data = sample_layer_playlist_assignment.to_dict()

        assert 'created_at' in data
        assert data['created_at'] is not None

    def test_to_dict_with_trigger(self, app, sample_layer_playlist_assignment_trigger):
        """to_dict should correctly serialize assignment with trigger."""
        data = sample_layer_playlist_assignment_trigger.to_dict()

        assert data['trigger_type'] == 'face_detected'
        assert data['priority'] == 5

    def test_to_dict_with_relations_includes_layer(self, app, sample_layer_playlist_assignment):
        """to_dict_with_relations should include nested layer data."""
        data = sample_layer_playlist_assignment.to_dict_with_relations()

        assert 'layer' in data
        assert data['layer'] is not None
        assert data['layer']['id'] == sample_layer_playlist_assignment.layer_id

    def test_to_dict_with_relations_includes_playlist(self, app, sample_layer_playlist_assignment):
        """to_dict_with_relations should include nested playlist data."""
        data = sample_layer_playlist_assignment.to_dict_with_relations()

        assert 'playlist' in data
        assert data['playlist'] is not None
        assert data['playlist']['id'] == sample_layer_playlist_assignment.playlist_id

    def test_to_dict_with_relations_includes_base_fields(self, app, sample_layer_playlist_assignment):
        """to_dict_with_relations should include all base to_dict fields."""
        data = sample_layer_playlist_assignment.to_dict_with_relations()

        assert data['id'] == sample_layer_playlist_assignment.id
        assert data['device_id'] == sample_layer_playlist_assignment.device_id
        assert data['trigger_type'] == 'default'
        assert data['priority'] == 1


# =============================================================================
# DeviceLayout Model Serialization Tests
# =============================================================================

class TestDeviceLayoutSerialization:
    """Tests for DeviceLayout.to_dict() and to_dict_with_relations() methods."""

    def test_to_dict_includes_all_fields(self, app, sample_device_layout):
        """to_dict should include all device layout fields."""
        data = sample_device_layout.to_dict()

        assert 'id' in data
        assert data['id'] == sample_device_layout.id
        assert data['device_id'] == sample_device_layout.device_id
        assert data['layout_id'] == sample_device_layout.layout_id
        assert data['priority'] == 1
        assert data['start_date'] is None
        assert data['end_date'] is None

    def test_to_dict_includes_timestamps(self, app, sample_device_layout):
        """to_dict should include properly formatted timestamp."""
        data = sample_device_layout.to_dict()

        assert 'created_at' in data
        assert data['created_at'] is not None

    def test_to_dict_with_schedule(self, app, sample_device_layout_scheduled):
        """to_dict should correctly serialize scheduled assignment."""
        data = sample_device_layout_scheduled.to_dict()

        assert data['priority'] == 10
        assert data['start_date'] is not None
        assert data['end_date'] is not None
        # Dates should be ISO format strings
        assert isinstance(data['start_date'], str)
        assert isinstance(data['end_date'], str)
        assert '2024-01-01' in data['start_date']
        assert '2024-12-31' in data['end_date']

    def test_to_dict_with_relations_includes_device(self, app, sample_device_layout):
        """to_dict_with_relations should include nested device data."""
        data = sample_device_layout.to_dict_with_relations()

        assert 'device' in data
        assert data['device'] is not None
        assert data['device']['id'] == sample_device_layout.device_id

    def test_to_dict_with_relations_includes_layout(self, app, sample_device_layout):
        """to_dict_with_relations should include nested layout data."""
        data = sample_device_layout.to_dict_with_relations()

        assert 'layout' in data
        assert data['layout'] is not None
        assert data['layout']['id'] == sample_device_layout.layout_id

    def test_to_dict_with_relations_includes_base_fields(self, app, sample_device_layout):
        """to_dict_with_relations should include all base to_dict fields."""
        data = sample_device_layout.to_dict_with_relations()

        assert data['id'] == sample_device_layout.id
        assert data['device_id'] == sample_device_layout.device_id
        assert data['layout_id'] == sample_device_layout.layout_id
        assert data['priority'] == 1


# =============================================================================
# Layout Create API Tests (POST /api/v1/layouts)
# =============================================================================

class TestLayoutCreateAPI:
    """Tests for POST /api/v1/layouts endpoint."""

    def test_create_layout_success(self, client, app):
        """POST /layouts should create a new layout with required fields."""
        response = client.post('/api/v1/layouts', json={
            'name': 'Test Layout API'
        })

        assert response.status_code == 201
        data = response.get_json()
        assert data['name'] == 'Test Layout API'
        assert data['canvas_width'] == 1920  # default
        assert data['canvas_height'] == 1080  # default
        assert data['orientation'] == 'landscape'  # default
        assert data['background_type'] == 'solid'  # default
        assert data['background_color'] == '#000000'  # default
        assert data['background_opacity'] == 1.0  # default
        assert data['is_template'] is False  # default
        assert 'id' in data
        assert 'created_at' in data
        assert 'updated_at' in data

    def test_create_layout_with_all_fields(self, client, app):
        """POST /layouts should create a layout with all optional fields."""
        response = client.post('/api/v1/layouts', json={
            'name': 'Full Layout',
            'description': 'A complete layout with all fields',
            'canvas_width': 1080,
            'canvas_height': 1920,
            'orientation': 'portrait',
            'background_type': 'image',
            'background_color': '#FFFFFF',
            'background_opacity': 0.8,
            'is_template': True
        })

        assert response.status_code == 201
        data = response.get_json()
        assert data['name'] == 'Full Layout'
        assert data['description'] == 'A complete layout with all fields'
        assert data['canvas_width'] == 1080
        assert data['canvas_height'] == 1920
        assert data['orientation'] == 'portrait'
        assert data['background_type'] == 'image'
        assert data['background_color'] == '#FFFFFF'
        assert data['background_opacity'] == 0.8
        assert data['is_template'] is True

    def test_create_layout_missing_name(self, client, app):
        """POST /layouts should reject missing name."""
        response = client.post('/api/v1/layouts', json={
            'canvas_width': 1920
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'name is required' in data['error']

    def test_create_layout_empty_body(self, client, app):
        """POST /layouts should reject empty body."""
        response = client.post('/api/v1/layouts',
                               data='',
                               content_type='application/json')

        assert response.status_code == 400
        data = response.get_json()
        assert 'Request body is required' in data['error']

    def test_create_layout_name_too_long(self, client, app):
        """POST /layouts should reject name > 255 characters."""
        response = client.post('/api/v1/layouts', json={
            'name': 'x' * 256
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'max 255 characters' in data['error']

    def test_create_layout_invalid_orientation(self, client, app):
        """POST /layouts should reject invalid orientation."""
        response = client.post('/api/v1/layouts', json={
            'name': 'Test Layout',
            'orientation': 'diagonal'
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'Invalid orientation' in data['error']

    def test_create_layout_invalid_background_type(self, client, app):
        """POST /layouts should reject invalid background_type."""
        response = client.post('/api/v1/layouts', json={
            'name': 'Test Layout',
            'background_type': 'gradient'
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'Invalid background_type' in data['error']

    def test_create_layout_invalid_canvas_width(self, client, app):
        """POST /layouts should reject invalid canvas_width."""
        response = client.post('/api/v1/layouts', json={
            'name': 'Test Layout',
            'canvas_width': 'not-a-number'
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'canvas_width must be an integer' in data['error']

    def test_create_layout_canvas_width_too_small(self, client, app):
        """POST /layouts should reject canvas_width < 20."""
        response = client.post('/api/v1/layouts', json={
            'name': 'Test Layout',
            'canvas_width': 10
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'between 20 and 10000' in data['error']

    def test_create_layout_canvas_width_too_large(self, client, app):
        """POST /layouts should reject canvas_width > 10000."""
        response = client.post('/api/v1/layouts', json={
            'name': 'Test Layout',
            'canvas_width': 20000
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'between 20 and 10000' in data['error']

    def test_create_layout_invalid_opacity(self, client, app):
        """POST /layouts should reject opacity outside 0.0-1.0."""
        response = client.post('/api/v1/layouts', json={
            'name': 'Test Layout',
            'background_opacity': 1.5
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'between 0.0 and 1.0' in data['error']

    def test_create_layout_invalid_opacity_type(self, client, app):
        """POST /layouts should reject non-numeric opacity."""
        response = client.post('/api/v1/layouts', json={
            'name': 'Test Layout',
            'background_opacity': 'high'
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'background_opacity must be a number' in data['error']


# =============================================================================
# Layout List API Tests (GET /api/v1/layouts)
# =============================================================================

class TestLayoutListAPI:
    """Tests for GET /api/v1/layouts endpoint."""

    def test_list_layouts_empty(self, client, app):
        """GET /layouts should return empty list when no layouts."""
        response = client.get('/api/v1/layouts')

        assert response.status_code == 200
        data = response.get_json()
        assert data['layouts'] == []
        assert data['count'] == 0

    def test_list_layouts_all(self, client, app, sample_layout, sample_template_layout):
        """GET /layouts should return all layouts."""
        response = client.get('/api/v1/layouts')

        assert response.status_code == 200
        data = response.get_json()
        assert data['count'] == 2
        layout_names = [l['name'] for l in data['layouts']]
        assert 'Test Layout' in layout_names
        assert 'Template Layout' in layout_names

    def test_list_layouts_filter_by_template(self, client, app, sample_layout, sample_template_layout):
        """GET /layouts?is_template=true should filter by template status."""
        response = client.get('/api/v1/layouts?is_template=true')

        assert response.status_code == 200
        data = response.get_json()
        assert data['count'] == 1
        assert all(l['is_template'] is True for l in data['layouts'])

    def test_list_layouts_filter_by_non_template(self, client, app, sample_layout, sample_template_layout):
        """GET /layouts?is_template=false should filter by non-template status."""
        response = client.get('/api/v1/layouts?is_template=false')

        assert response.status_code == 200
        data = response.get_json()
        assert data['count'] == 1
        assert all(l['is_template'] is False for l in data['layouts'])

    def test_list_layouts_filter_by_orientation(self, client, app, sample_layout, sample_template_layout):
        """GET /layouts?orientation=portrait should filter by orientation."""
        response = client.get('/api/v1/layouts?orientation=portrait')

        assert response.status_code == 200
        data = response.get_json()
        assert all(l['orientation'] == 'portrait' for l in data['layouts'])

    def test_list_layouts_invalid_orientation_filter(self, client, app):
        """GET /layouts?orientation=invalid should return 400."""
        response = client.get('/api/v1/layouts?orientation=diagonal')

        assert response.status_code == 400
        data = response.get_json()
        assert 'Invalid orientation' in data['error']


# =============================================================================
# Layout Templates API Tests (GET /api/v1/layouts/templates)
# =============================================================================

class TestLayoutTemplatesAPI:
    """Tests for GET /api/v1/layouts/templates endpoint."""

    def test_list_templates_empty(self, client, app, sample_layout):
        """GET /layouts/templates should return empty list when no templates."""
        response = client.get('/api/v1/layouts/templates')

        assert response.status_code == 200
        data = response.get_json()
        assert data['templates'] == []
        assert data['count'] == 0

    def test_list_templates_returns_only_templates(self, client, app, sample_layout, sample_template_layout):
        """GET /layouts/templates should return only template layouts."""
        response = client.get('/api/v1/layouts/templates')

        assert response.status_code == 200
        data = response.get_json()
        assert data['count'] == 1
        assert data['templates'][0]['name'] == 'Template Layout'
        assert data['templates'][0]['is_template'] is True


# =============================================================================
# Layout Get API Tests (GET /api/v1/layouts/<layout_id>)
# =============================================================================

class TestLayoutGetAPI:
    """Tests for GET /api/v1/layouts/<layout_id> endpoint."""

    def test_get_layout_success(self, client, app, sample_layout):
        """GET /layouts/<id> should return layout with layers by default."""
        response = client.get(f'/api/v1/layouts/{sample_layout.id}')

        assert response.status_code == 200
        data = response.get_json()
        assert data['id'] == sample_layout.id
        assert data['name'] == 'Test Layout'
        assert 'layers' in data

    def test_get_layout_includes_layers(self, client, app, sample_layout, sample_layer):
        """GET /layouts/<id> should include layers data."""
        response = client.get(f'/api/v1/layouts/{sample_layout.id}')

        assert response.status_code == 200
        data = response.get_json()
        assert 'layers' in data
        assert len(data['layers']) == 1
        assert data['layers'][0]['id'] == sample_layer.id

    def test_get_layout_exclude_layers(self, client, app, sample_layout, sample_layer):
        """GET /layouts/<id>?include_layers=false should exclude layers."""
        response = client.get(f'/api/v1/layouts/{sample_layout.id}?include_layers=false')

        assert response.status_code == 200
        data = response.get_json()
        assert 'layers' not in data

    def test_get_layout_not_found(self, client, app):
        """GET /layouts/<id> should return 404 for non-existent layout."""
        response = client.get('/api/v1/layouts/non-existent-layout-id')

        assert response.status_code == 404
        data = response.get_json()
        assert 'Layout not found' in data['error']


# =============================================================================
# Layout Update API Tests (PUT /api/v1/layouts/<layout_id>)
# =============================================================================

class TestLayoutUpdateAPI:
    """Tests for PUT /api/v1/layouts/<layout_id> endpoint."""

    def test_update_layout_name(self, client, app, sample_layout):
        """PUT /layouts/<id> should update layout name."""
        response = client.put(f'/api/v1/layouts/{sample_layout.id}', json={
            'name': 'Updated Layout Name'
        })

        assert response.status_code == 200
        data = response.get_json()
        assert data['name'] == 'Updated Layout Name'

    def test_update_layout_multiple_fields(self, client, app, sample_layout):
        """PUT /layouts/<id> should update multiple fields."""
        response = client.put(f'/api/v1/layouts/{sample_layout.id}', json={
            'name': 'Renamed Layout',
            'description': 'New description',
            'canvas_width': 800,
            'canvas_height': 600,
            'orientation': 'portrait',
            'background_type': 'transparent',
            'background_opacity': 0.5,
            'is_template': True
        })

        assert response.status_code == 200
        data = response.get_json()
        assert data['name'] == 'Renamed Layout'
        assert data['description'] == 'New description'
        assert data['canvas_width'] == 800
        assert data['canvas_height'] == 600
        assert data['orientation'] == 'portrait'
        assert data['background_type'] == 'transparent'
        assert data['background_opacity'] == 0.5
        assert data['is_template'] is True

    def test_update_layout_not_found(self, client, app):
        """PUT /layouts/<id> should return 404 for non-existent layout."""
        response = client.put('/api/v1/layouts/non-existent-layout-id', json={
            'name': 'Updated Name'
        })

        assert response.status_code == 404
        data = response.get_json()
        assert 'Layout not found' in data['error']

    def test_update_layout_empty_body(self, client, app, sample_layout):
        """PUT /layouts/<id> should reject empty body."""
        response = client.put(f'/api/v1/layouts/{sample_layout.id}',
                              data='',
                              content_type='application/json')

        assert response.status_code == 400
        data = response.get_json()
        assert 'Request body is required' in data['error']

    def test_update_layout_invalid_orientation(self, client, app, sample_layout):
        """PUT /layouts/<id> should reject invalid orientation."""
        response = client.put(f'/api/v1/layouts/{sample_layout.id}', json={
            'orientation': 'diagonal'
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'Invalid orientation' in data['error']

    def test_update_layout_invalid_canvas_dimensions(self, client, app, sample_layout):
        """PUT /layouts/<id> should reject invalid canvas dimensions."""
        response = client.put(f'/api/v1/layouts/{sample_layout.id}', json={
            'canvas_width': 5  # too small
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'between 20 and 10000' in data['error']

    def test_update_layout_invalid_name_length(self, client, app, sample_layout):
        """PUT /layouts/<id> should reject name > 255 characters."""
        response = client.put(f'/api/v1/layouts/{sample_layout.id}', json={
            'name': 'x' * 256
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'max 255 characters' in data['error']


# =============================================================================
# Layout Delete API Tests (DELETE /api/v1/layouts/<layout_id>)
# =============================================================================

class TestLayoutDeleteAPI:
    """Tests for DELETE /api/v1/layouts/<layout_id> endpoint."""

    def test_delete_layout_success(self, client, app, sample_layout):
        """DELETE /layouts/<id> should delete layout."""
        layout_id = sample_layout.id

        response = client.delete(f'/api/v1/layouts/{layout_id}')

        assert response.status_code == 200
        data = response.get_json()
        assert data['message'] == 'Layout deleted successfully'
        assert data['id'] == layout_id

        # Verify layout is deleted
        get_response = client.get(f'/api/v1/layouts/{layout_id}')
        assert get_response.status_code == 404

    def test_delete_layout_with_layers(self, client, app, sample_layout, sample_layer):
        """DELETE /layouts/<id> should cascade delete layers."""
        layout_id = sample_layout.id

        response = client.delete(f'/api/v1/layouts/{layout_id}')

        assert response.status_code == 200
        assert response.get_json()['message'] == 'Layout deleted successfully'

    def test_delete_layout_not_found(self, client, app):
        """DELETE /layouts/<id> should return 404 for non-existent layout."""
        response = client.delete('/api/v1/layouts/non-existent-layout-id')

        assert response.status_code == 404
        data = response.get_json()
        assert 'Layout not found' in data['error']


# =============================================================================
# Layout Duplicate API Tests (POST /api/v1/layouts/<layout_id>/duplicate)
# =============================================================================

class TestLayoutDuplicateAPI:
    """Tests for POST /api/v1/layouts/<layout_id>/duplicate endpoint."""

    def test_duplicate_layout_success(self, client, app, sample_layout):
        """POST /layouts/<id>/duplicate should create a copy of the layout."""
        response = client.post(f'/api/v1/layouts/{sample_layout.id}/duplicate', json={})

        assert response.status_code == 201
        data = response.get_json()
        assert data['name'] == f'Copy of {sample_layout.name}'
        assert data['id'] != sample_layout.id
        assert data['canvas_width'] == sample_layout.canvas_width

    def test_duplicate_layout_with_custom_name(self, client, app, sample_layout):
        """POST /layouts/<id>/duplicate should use custom name if provided."""
        response = client.post(f'/api/v1/layouts/{sample_layout.id}/duplicate', json={
            'name': 'My Duplicate Layout'
        })

        assert response.status_code == 201
        data = response.get_json()
        assert data['name'] == 'My Duplicate Layout'

    def test_duplicate_layout_with_layers(self, client, app, sample_layout, sample_layer):
        """POST /layouts/<id>/duplicate should include layers by default."""
        response = client.post(f'/api/v1/layouts/{sample_layout.id}/duplicate', json={})

        assert response.status_code == 201
        data = response.get_json()
        assert 'layers' in data
        assert len(data['layers']) == 1

    def test_duplicate_layout_without_layers(self, client, app, sample_layout, sample_layer):
        """POST /layouts/<id>/duplicate?include_layers=false should exclude layers."""
        response = client.post(f'/api/v1/layouts/{sample_layout.id}/duplicate', json={
            'include_layers': False
        })

        assert response.status_code == 201
        data = response.get_json()
        # When include_layers=False, layers should be empty or not included
        assert 'layers' not in data or len(data.get('layers', [])) == 0

    def test_duplicate_layout_not_found(self, client, app):
        """POST /layouts/<id>/duplicate should return 404 for non-existent layout."""
        response = client.post('/api/v1/layouts/non-existent-layout-id/duplicate', json={})

        assert response.status_code == 404
        data = response.get_json()
        assert 'Layout not found' in data['error']

    def test_duplicate_layout_invalid_name(self, client, app, sample_layout):
        """POST /layouts/<id>/duplicate should reject invalid name."""
        response = client.post(f'/api/v1/layouts/{sample_layout.id}/duplicate', json={
            'name': 'x' * 256
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'max 255 characters' in data['error']


# =============================================================================
# Layer CRUD API Tests
# =============================================================================

class TestLayerCreateAPI:
    """Tests for POST /api/v1/layouts/<layout_id>/layers endpoint."""

    def test_create_layer_success(self, client, app, sample_layout):
        """POST /layouts/<id>/layers should create a new layer."""
        response = client.post(f'/api/v1/layouts/{sample_layout.id}/layers', json={
            'name': 'New Layer'
        })

        assert response.status_code == 201
        data = response.get_json()
        assert data['name'] == 'New Layer'
        assert data['layout_id'] == sample_layout.id
        assert data['layer_type'] == 'content'  # default
        assert data['x'] == 0  # default
        assert data['y'] == 0  # default
        assert data['opacity'] == 1.0  # default
        assert 'id' in data

    def test_create_layer_with_all_fields(self, client, app, sample_layout):
        """POST /layouts/<id>/layers should create layer with all fields."""
        response = client.post(f'/api/v1/layouts/{sample_layout.id}/layers', json={
            'name': 'Full Layer',
            'layer_type': 'widget',
            'x': 100,
            'y': 200,
            'width': 500,
            'height': 400,
            'z_index': 5,
            'opacity': 0.8,
            'background_type': 'solid',
            'background_color': '#FF0000',
            'is_visible': True,
            'is_locked': False
        })

        assert response.status_code == 201
        data = response.get_json()
        assert data['name'] == 'Full Layer'
        assert data['layer_type'] == 'widget'
        assert data['x'] == 100
        assert data['y'] == 200
        assert data['width'] == 500
        assert data['height'] == 400
        assert data['z_index'] == 5
        assert data['opacity'] == 0.8
        assert data['background_type'] == 'solid'
        assert data['background_color'] == '#FF0000'

    def test_create_layer_missing_name(self, client, app, sample_layout):
        """POST /layouts/<id>/layers should reject missing name."""
        response = client.post(f'/api/v1/layouts/{sample_layout.id}/layers', json={
            'layer_type': 'content'
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'name is required' in data['error']

    def test_create_layer_layout_not_found(self, client, app):
        """POST /layouts/<id>/layers should return 404 for non-existent layout."""
        response = client.post('/api/v1/layouts/non-existent-id/layers', json={
            'name': 'Test Layer'
        })

        assert response.status_code == 404
        data = response.get_json()
        assert 'Layout not found' in data['error']

    def test_create_layer_invalid_layer_type(self, client, app, sample_layout):
        """POST /layouts/<id>/layers should reject invalid layer_type."""
        response = client.post(f'/api/v1/layouts/{sample_layout.id}/layers', json={
            'name': 'Test Layer',
            'layer_type': 'invalid'
        })

        assert response.status_code == 400
        data = response.get_json()
        assert 'Invalid layer_type' in data['error']


class TestLayerListAPI:
    """Tests for GET /api/v1/layouts/<layout_id>/layers endpoint."""

    def test_list_layers_empty(self, client, app, sample_layout):
        """GET /layouts/<id>/layers should return empty list when no layers."""
        response = client.get(f'/api/v1/layouts/{sample_layout.id}/layers')

        assert response.status_code == 200
        data = response.get_json()
        assert data['layers'] == []
        assert data['count'] == 0

    def test_list_layers_success(self, client, app, sample_layout, sample_layer, sample_layer_styled):
        """GET /layouts/<id>/layers should return all layers ordered by z_index."""
        response = client.get(f'/api/v1/layouts/{sample_layout.id}/layers')

        assert response.status_code == 200
        data = response.get_json()
        assert data['count'] == 2
        # Verify ordering by z_index
        assert data['layers'][0]['z_index'] < data['layers'][1]['z_index']

    def test_list_layers_filter_by_visibility(self, client, app, sample_layout, sample_layer):
        """GET /layouts/<id>/layers?is_visible=true should filter by visibility."""
        response = client.get(f'/api/v1/layouts/{sample_layout.id}/layers?is_visible=true')

        assert response.status_code == 200
        data = response.get_json()
        assert all(l['is_visible'] is True for l in data['layers'])

    def test_list_layers_layout_not_found(self, client, app):
        """GET /layouts/<id>/layers should return 404 for non-existent layout."""
        response = client.get('/api/v1/layouts/non-existent-id/layers')

        assert response.status_code == 404
        data = response.get_json()
        assert 'Layout not found' in data['error']


class TestLayerGetAPI:
    """Tests for GET /api/v1/layouts/<layout_id>/layers/<layer_id> endpoint."""

    def test_get_layer_success(self, client, app, sample_layout, sample_layer):
        """GET /layouts/<id>/layers/<layer_id> should return layer details."""
        response = client.get(
            f'/api/v1/layouts/{sample_layout.id}/layers/{sample_layer.id}'
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data['id'] == sample_layer.id
        assert data['name'] == 'Main Content Layer'

    def test_get_layer_not_found(self, client, app, sample_layout):
        """GET /layouts/<id>/layers/<layer_id> should return 404 for non-existent layer."""
        response = client.get(
            f'/api/v1/layouts/{sample_layout.id}/layers/non-existent-layer-id'
        )

        assert response.status_code == 404
        data = response.get_json()
        assert 'Layer not found' in data['error']

    def test_get_layer_layout_not_found(self, client, app, sample_layer):
        """GET /layouts/<id>/layers/<layer_id> should return 404 for non-existent layout."""
        response = client.get(
            f'/api/v1/layouts/non-existent-layout/layers/{sample_layer.id}'
        )

        assert response.status_code == 404
        data = response.get_json()
        assert 'Layout not found' in data['error']


class TestLayerUpdateAPI:
    """Tests for PUT /api/v1/layouts/<layout_id>/layers/<layer_id> endpoint."""

    def test_update_layer_success(self, client, app, sample_layout, sample_layer):
        """PUT /layouts/<id>/layers/<layer_id> should update layer."""
        response = client.put(
            f'/api/v1/layouts/{sample_layout.id}/layers/{sample_layer.id}',
            json={'name': 'Updated Layer Name'}
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data['name'] == 'Updated Layer Name'

    def test_update_layer_multiple_fields(self, client, app, sample_layout, sample_layer):
        """PUT /layouts/<id>/layers/<layer_id> should update multiple fields."""
        response = client.put(
            f'/api/v1/layouts/{sample_layout.id}/layers/{sample_layer.id}',
            json={
                'x': 50,
                'y': 100,
                'width': 600,
                'height': 400,
                'opacity': 0.5,
                'is_visible': False
            }
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data['x'] == 50
        assert data['y'] == 100
        assert data['width'] == 600
        assert data['height'] == 400
        assert data['opacity'] == 0.5
        assert data['is_visible'] is False

    def test_update_layer_not_found(self, client, app, sample_layout):
        """PUT /layouts/<id>/layers/<layer_id> should return 404 for non-existent layer."""
        response = client.put(
            f'/api/v1/layouts/{sample_layout.id}/layers/non-existent-layer-id',
            json={'name': 'Updated'}
        )

        assert response.status_code == 404
        data = response.get_json()
        assert 'Layer not found' in data['error']

    def test_update_layer_empty_body(self, client, app, sample_layout, sample_layer):
        """PUT /layouts/<id>/layers/<layer_id> should reject empty body."""
        response = client.put(
            f'/api/v1/layouts/{sample_layout.id}/layers/{sample_layer.id}',
            data='',
            content_type='application/json'
        )

        assert response.status_code == 400
        data = response.get_json()
        assert 'Request body is required' in data['error']


class TestLayerDeleteAPI:
    """Tests for DELETE /api/v1/layouts/<layout_id>/layers/<layer_id> endpoint."""

    def test_delete_layer_success(self, client, app, sample_layout, sample_layer):
        """DELETE /layouts/<id>/layers/<layer_id> should delete layer."""
        layer_id = sample_layer.id

        response = client.delete(
            f'/api/v1/layouts/{sample_layout.id}/layers/{layer_id}'
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data['message'] == 'Layer deleted successfully'
        assert data['id'] == layer_id

    def test_delete_layer_not_found(self, client, app, sample_layout):
        """DELETE /layouts/<id>/layers/<layer_id> should return 404 for non-existent layer."""
        response = client.delete(
            f'/api/v1/layouts/{sample_layout.id}/layers/non-existent-layer-id'
        )

        assert response.status_code == 404
        data = response.get_json()
        assert 'Layer not found' in data['error']


class TestLayerReorderAPI:
    """Tests for PUT /api/v1/layouts/<layout_id>/layers/reorder endpoint."""

    def test_reorder_layers_success(self, client, app, sample_layout, sample_layer, sample_layer_styled):
        """PUT /layouts/<id>/layers/reorder should reorder layers."""
        # Reorder to put styled layer first (z_index=0), then main layer (z_index=1)
        response = client.put(
            f'/api/v1/layouts/{sample_layout.id}/layers/reorder',
            json={
                'layer_ids': [sample_layer_styled.id, sample_layer.id]
            }
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data['message'] == 'Layers reordered'
        # Verify new order
        assert data['layers'][0]['id'] == sample_layer_styled.id
        assert data['layers'][0]['z_index'] == 0
        assert data['layers'][1]['id'] == sample_layer.id
        assert data['layers'][1]['z_index'] == 1

    def test_reorder_layers_missing_layer_ids(self, client, app, sample_layout):
        """PUT /layouts/<id>/layers/reorder should reject missing layer_ids."""
        response = client.put(
            f'/api/v1/layouts/{sample_layout.id}/layers/reorder',
            json={}
        )

        assert response.status_code == 400
        data = response.get_json()
        assert 'layer_ids array is required' in data['error']

    def test_reorder_layers_invalid_layer_id(self, client, app, sample_layout, sample_layer):
        """PUT /layouts/<id>/layers/reorder should return 404 for invalid layer_id."""
        response = client.put(
            f'/api/v1/layouts/{sample_layout.id}/layers/reorder',
            json={
                'layer_ids': [sample_layer.id, 'non-existent-layer-id']
            }
        )

        assert response.status_code == 404
        data = response.get_json()
        assert 'not found in layout' in data['error']


# =============================================================================
# Device Layout Assignment API Tests
# =============================================================================

class TestDeviceLayoutAssignmentAPI:
    """Tests for device layout assignment endpoints."""

    def test_assign_layout_to_device_success(self, client, app, sample_layout, sample_device_direct):
        """POST /layouts/<id>/assign should assign layout to device."""
        response = client.post(
            f'/api/v1/layouts/{sample_layout.id}/assign',
            json={'device_id': sample_device_direct.id}
        )

        assert response.status_code == 201
        data = response.get_json()
        assert data['layout_id'] == sample_layout.id
        assert data['device_id'] == sample_device_direct.id
        assert data['priority'] == 0  # default
        assert 'device' in data
        assert 'layout' in data

    def test_assign_layout_with_priority(self, client, app, sample_layout, sample_device_direct):
        """POST /layouts/<id>/assign should accept priority."""
        response = client.post(
            f'/api/v1/layouts/{sample_layout.id}/assign',
            json={
                'device_id': sample_device_direct.id,
                'priority': 10
            }
        )

        assert response.status_code == 201
        data = response.get_json()
        assert data['priority'] == 10

    def test_assign_layout_with_schedule(self, client, app, sample_layout, sample_device_direct):
        """POST /layouts/<id>/assign should accept schedule dates."""
        response = client.post(
            f'/api/v1/layouts/{sample_layout.id}/assign',
            json={
                'device_id': sample_device_direct.id,
                'start_date': '2024-01-01T00:00:00Z',
                'end_date': '2024-12-31T23:59:59Z'
            }
        )

        assert response.status_code == 201
        data = response.get_json()
        assert data['start_date'] is not None
        assert data['end_date'] is not None

    def test_assign_layout_missing_device_id(self, client, app, sample_layout):
        """POST /layouts/<id>/assign should reject missing device_id."""
        response = client.post(
            f'/api/v1/layouts/{sample_layout.id}/assign',
            json={}
        )

        assert response.status_code == 400
        data = response.get_json()
        assert 'device_id is required' in data['error']

    def test_assign_layout_device_not_found(self, client, app, sample_layout):
        """POST /layouts/<id>/assign should return 404 for non-existent device."""
        response = client.post(
            f'/api/v1/layouts/{sample_layout.id}/assign',
            json={'device_id': 'non-existent-device-id'}
        )

        assert response.status_code == 404
        data = response.get_json()
        assert 'not found' in data['error']

    def test_assign_layout_duplicate(self, client, app, sample_layout, sample_device_direct):
        """POST /layouts/<id>/assign should reject duplicate assignment."""
        # First assignment
        client.post(
            f'/api/v1/layouts/{sample_layout.id}/assign',
            json={'device_id': sample_device_direct.id}
        )

        # Duplicate assignment
        response = client.post(
            f'/api/v1/layouts/{sample_layout.id}/assign',
            json={'device_id': sample_device_direct.id}
        )

        assert response.status_code == 400
        data = response.get_json()
        assert 'already assigned' in data['error']

    def test_list_layout_assignments_success(self, client, app, sample_device_layout):
        """GET /layouts/<id>/assignments should list all device assignments."""
        response = client.get(
            f'/api/v1/layouts/{sample_device_layout.layout_id}/assignments'
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data['count'] == 1
        assert data['assignments'][0]['id'] == sample_device_layout.id

    def test_list_layout_assignments_layout_not_found(self, client, app):
        """GET /layouts/<id>/assignments should return 404 for non-existent layout."""
        response = client.get('/api/v1/layouts/non-existent-layout-id/assignments')

        assert response.status_code == 404
        data = response.get_json()
        assert 'Layout not found' in data['error']

    def test_remove_layout_assignment_success(self, client, app, sample_device_layout):
        """DELETE /layouts/<id>/assign/<assignment_id> should remove assignment."""
        response = client.delete(
            f'/api/v1/layouts/{sample_device_layout.layout_id}/assign/{sample_device_layout.id}'
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data['message'] == 'Assignment removed'
        assert data['id'] == sample_device_layout.id

    def test_remove_layout_assignment_not_found(self, client, app, sample_layout):
        """DELETE /layouts/<id>/assign/<assignment_id> should return 404 for non-existent assignment."""
        response = client.delete(
            f'/api/v1/layouts/{sample_layout.id}/assign/non-existent-assignment-id'
        )

        assert response.status_code == 404
        data = response.get_json()
        assert 'Assignment not found' in data['error']


# =============================================================================
# Cascade Delete Tests
# =============================================================================

class TestLayoutCascadeDelete:
    """Tests for cascade delete behavior when deleting layouts and layers."""

    # -------------------------------------------------------------------------
    # Layout Cascade Delete Tests
    # -------------------------------------------------------------------------

    def test_delete_layout_cascades_to_layers(self, client, app, db_session, sample_layout, sample_layer, sample_layer_styled):
        """Deleting a layout should cascade delete all its layers."""
        layout_id = sample_layout.id
        layer_id = sample_layer.id
        layer_styled_id = sample_layer_styled.id

        # Verify layers exist
        assert ScreenLayer.query.get(layer_id) is not None
        assert ScreenLayer.query.get(layer_styled_id) is not None

        # Delete the layout
        response = client.delete(f'/api/v1/layouts/{layout_id}')
        assert response.status_code == 200

        # Verify layout is deleted
        assert ScreenLayout.query.get(layout_id) is None

        # Verify layers are cascade deleted
        assert ScreenLayer.query.get(layer_id) is None
        assert ScreenLayer.query.get(layer_styled_id) is None

    def test_delete_layout_cascades_to_device_assignments(self, client, app, db_session, sample_device_layout):
        """Deleting a layout should cascade delete all device-layout assignments."""
        layout_id = sample_device_layout.layout_id
        assignment_id = sample_device_layout.id

        # Verify assignment exists
        assert DeviceLayout.query.get(assignment_id) is not None

        # Delete the layout
        response = client.delete(f'/api/v1/layouts/{layout_id}')
        assert response.status_code == 200

        # Verify assignment is cascade deleted
        assert DeviceLayout.query.get(assignment_id) is None

    def test_delete_layout_cascades_to_layer_content(self, client, app, db_session, sample_layout, sample_layer_content):
        """Deleting a layout should cascade delete layer content through layers."""
        layout_id = sample_layout.id
        layer_id = sample_layer_content.layer_id
        content_id = sample_layer_content.id

        # Verify layer content exists
        assert LayerContent.query.get(content_id) is not None
        assert ScreenLayer.query.get(layer_id) is not None

        # Delete the layout
        response = client.delete(f'/api/v1/layouts/{layout_id}')
        assert response.status_code == 200

        # Verify layer and content are cascade deleted
        assert ScreenLayer.query.get(layer_id) is None
        assert LayerContent.query.get(content_id) is None

    def test_delete_layout_cascades_to_layer_playlist_assignments(self, client, app, db_session, sample_layout, sample_layer_playlist_assignment):
        """Deleting a layout should cascade delete layer playlist assignments through layers."""
        layout_id = sample_layout.id
        layer_id = sample_layer_playlist_assignment.layer_id
        assignment_id = sample_layer_playlist_assignment.id

        # Verify playlist assignment exists
        assert LayerPlaylistAssignment.query.get(assignment_id) is not None

        # Delete the layout
        response = client.delete(f'/api/v1/layouts/{layout_id}')
        assert response.status_code == 200

        # Verify layer and playlist assignment are cascade deleted
        assert ScreenLayer.query.get(layer_id) is None
        assert LayerPlaylistAssignment.query.get(assignment_id) is None

    def test_delete_layout_cascades_multiple_content_and_assignments(self, client, app, db_session, sample_layout, sample_layer, sample_layer_content, sample_layer_playlist_assignment, sample_device_layout):
        """Deleting a layout should cascade delete all related layers, content, and assignments."""
        layout_id = sample_layout.id
        layer_id = sample_layer.id
        content_id = sample_layer_content.id
        playlist_assignment_id = sample_layer_playlist_assignment.id
        device_layout_id = sample_device_layout.id

        # Verify all related records exist
        assert ScreenLayout.query.get(layout_id) is not None
        assert ScreenLayer.query.get(layer_id) is not None
        assert LayerContent.query.get(content_id) is not None
        assert LayerPlaylistAssignment.query.get(playlist_assignment_id) is not None
        assert DeviceLayout.query.get(device_layout_id) is not None

        # Delete the layout
        response = client.delete(f'/api/v1/layouts/{layout_id}')
        assert response.status_code == 200

        # Verify all are cascade deleted
        assert ScreenLayout.query.get(layout_id) is None
        assert ScreenLayer.query.get(layer_id) is None
        assert LayerContent.query.get(content_id) is None
        assert LayerPlaylistAssignment.query.get(playlist_assignment_id) is None
        assert DeviceLayout.query.get(device_layout_id) is None

    # -------------------------------------------------------------------------
    # Layer Cascade Delete Tests
    # -------------------------------------------------------------------------

    def test_delete_layer_cascades_to_layer_content(self, client, app, db_session, sample_layout, sample_layer_content):
        """Deleting a layer should cascade delete all its content assignments."""
        layout_id = sample_layout.id
        layer_id = sample_layer_content.layer_id
        content_id = sample_layer_content.id

        # Verify layer content exists
        assert LayerContent.query.get(content_id) is not None

        # Delete the layer
        response = client.delete(f'/api/v1/layouts/{layout_id}/layers/{layer_id}')
        assert response.status_code == 200

        # Verify layer is deleted
        assert ScreenLayer.query.get(layer_id) is None

        # Verify layer content is cascade deleted
        assert LayerContent.query.get(content_id) is None

    def test_delete_layer_cascades_to_playlist_assignments(self, client, app, db_session, sample_layout, sample_layer_playlist_assignment):
        """Deleting a layer should cascade delete all its playlist assignments."""
        layout_id = sample_layout.id
        layer_id = sample_layer_playlist_assignment.layer_id
        assignment_id = sample_layer_playlist_assignment.id

        # Verify playlist assignment exists
        assert LayerPlaylistAssignment.query.get(assignment_id) is not None

        # Delete the layer
        response = client.delete(f'/api/v1/layouts/{layout_id}/layers/{layer_id}')
        assert response.status_code == 200

        # Verify layer and assignment are deleted
        assert ScreenLayer.query.get(layer_id) is None
        assert LayerPlaylistAssignment.query.get(assignment_id) is None

    def test_delete_layer_cascades_multiple_assignments(self, client, app, db_session, sample_layout, sample_layer, sample_layer_content, sample_layer_playlist_assignment):
        """Deleting a layer should cascade delete both content and playlist assignments."""
        layout_id = sample_layout.id
        layer_id = sample_layer.id
        content_id = sample_layer_content.id
        playlist_assignment_id = sample_layer_playlist_assignment.id

        # Verify all related records exist
        assert ScreenLayer.query.get(layer_id) is not None
        assert LayerContent.query.get(content_id) is not None
        assert LayerPlaylistAssignment.query.get(playlist_assignment_id) is not None

        # Delete the layer
        response = client.delete(f'/api/v1/layouts/{layout_id}/layers/{layer_id}')
        assert response.status_code == 200

        # Verify all are cascade deleted
        assert ScreenLayer.query.get(layer_id) is None
        assert LayerContent.query.get(content_id) is None
        assert LayerPlaylistAssignment.query.get(playlist_assignment_id) is None

    def test_delete_layer_preserves_other_layers(self, client, app, db_session, sample_layout, sample_layer, sample_layer_styled):
        """Deleting one layer should not affect other layers in the same layout."""
        layout_id = sample_layout.id
        layer_id = sample_layer.id
        other_layer_id = sample_layer_styled.id

        # Verify both layers exist
        assert ScreenLayer.query.get(layer_id) is not None
        assert ScreenLayer.query.get(other_layer_id) is not None

        # Delete one layer
        response = client.delete(f'/api/v1/layouts/{layout_id}/layers/{layer_id}')
        assert response.status_code == 200

        # Verify deleted layer is gone
        assert ScreenLayer.query.get(layer_id) is None

        # Verify other layer still exists
        assert ScreenLayer.query.get(other_layer_id) is not None

    def test_delete_layer_preserves_layout(self, client, app, db_session, sample_layout, sample_layer):
        """Deleting a layer should not delete its parent layout."""
        layout_id = sample_layout.id
        layer_id = sample_layer.id

        # Delete the layer
        response = client.delete(f'/api/v1/layouts/{layout_id}/layers/{layer_id}')
        assert response.status_code == 200

        # Verify layer is deleted
        assert ScreenLayer.query.get(layer_id) is None

        # Verify layout still exists
        layout = ScreenLayout.query.get(layout_id)
        assert layout is not None
        assert layout.name == 'Test Layout'

    # -------------------------------------------------------------------------
    # Device Assignment Cascade Tests (via layout deletion)
    # -------------------------------------------------------------------------

    def test_delete_layout_with_multiple_device_assignments(self, client, app, db_session, sample_layout, sample_device_direct, sample_network):
        """Deleting a layout with multiple device assignments should cascade delete all."""
        # Create additional device and assignment
        from cms.models import Device, Hub
        device2 = Device(
            hardware_id='hw-cascade-test-002',
            device_id='SKZ-D-CASCADE-002',
            mode='direct',
            name='Cascade Test Device 2',
            status='active'
        )
        db_session.add(device2)
        db_session.commit()

        # Create assignments for both devices
        assignment1 = DeviceLayout(
            device_id=sample_device_direct.id,
            layout_id=sample_layout.id,
            priority=1
        )
        assignment2 = DeviceLayout(
            device_id=device2.id,
            layout_id=sample_layout.id,
            priority=2
        )
        db_session.add_all([assignment1, assignment2])
        db_session.commit()

        assignment1_id = assignment1.id
        assignment2_id = assignment2.id

        # Verify assignments exist
        assert DeviceLayout.query.get(assignment1_id) is not None
        assert DeviceLayout.query.get(assignment2_id) is not None

        # Delete the layout
        response = client.delete(f'/api/v1/layouts/{sample_layout.id}')
        assert response.status_code == 200

        # Verify both assignments are cascade deleted
        assert DeviceLayout.query.get(assignment1_id) is None
        assert DeviceLayout.query.get(assignment2_id) is None

        # Verify devices still exist (only assignments should be deleted)
        assert Device.query.get(sample_device_direct.id) is not None
        assert Device.query.get(device2.id) is not None

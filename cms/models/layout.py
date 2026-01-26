"""
Layout Models for CMS Service.

Represents screen layouts with canvas configuration including:
- Canvas settings: name, dimensions, orientation, background
- Visual styling: background_type, background_color, background_opacity
- Organization: thumbnail_path, is_template for templates
- Timestamps: created_at, updated_at

Screen layers with positioning and styling including:
- Geometry: x, y, width, height, z_index for positioning
- Styling: opacity, background_type, background_color for visual appearance
- Visibility: is_visible, is_locked for editing state
- Content: name, layer_type, content configuration

Layer content assignments for device-specific content:
- Static files: images, videos, PDFs with page duration
- Ticker mode: scrolling text with items, speed, direction

Layer playlist assignments for trigger-based content:
- Playlist mapping: links playlists to layers for specific devices
- Triggers: audience detection (age, gender, face), loyalty, NCMEC alerts
- Priority: ordering for multiple playlists on same layer

Device-to-layout assignments with scheduling:
- Assignment mapping: links devices to screen layouts
- Scheduling: time-bounded assignments with start/end dates
- Priority: ordering for multiple layouts on same device
"""

from datetime import datetime, timezone
import uuid

from cms.models import db


class ScreenLayout(db.Model):
    """
    SQLAlchemy model representing a screen layout with canvas configuration.

    A screen layout defines the visual canvas on which layers are placed.
    It stores canvas dimensions, orientation, and background settings.
    Layouts can be marked as templates for reuse across devices.

    Attributes:
        id: Unique UUID identifier
        name: Human-readable layout name
        description: Optional detailed description
        canvas_width: Width of the canvas in pixels (default 1920)
        canvas_height: Height of the canvas in pixels (default 1080)
        orientation: Screen orientation ('landscape' or 'portrait')
        background_type: Type of background ('solid', 'image', 'transparent')
        background_color: Background color in hex format (e.g., '#000000')
        background_opacity: Background opacity from 0.0 to 1.0
        background_content: Optional path/URL to background image
        is_template: Whether this layout is a reusable template
        thumbnail_path: Path to layout thumbnail image
        created_at: Timestamp when the layout was created
        updated_at: Timestamp when the layout was last modified
    """

    __tablename__ = 'screen_layouts'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    canvas_width = db.Column(db.Integer, nullable=False, default=1920)
    canvas_height = db.Column(db.Integer, nullable=False, default=1080)
    orientation = db.Column(db.String(50), nullable=False, default='landscape')
    background_type = db.Column(db.String(50), nullable=False, default='solid')
    background_color = db.Column(db.String(50), nullable=True, default='#000000')
    background_opacity = db.Column(db.Float, nullable=False, default=1.0)
    background_content = db.Column(db.Text, nullable=True)
    is_template = db.Column(db.Boolean, nullable=False, default=False)
    thumbnail_path = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    layers = db.relationship(
        'ScreenLayer',
        backref='layout',
        lazy='dynamic',
        cascade='all, delete-orphan',
        order_by='ScreenLayer.z_index'
    )

    def to_dict(self, include_layers=False):
        """
        Serialize the layout to a dictionary for API responses.

        Args:
            include_layers: If True, include all layers in the response

        Returns:
            Dictionary containing all layout fields
        """
        result = {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'canvas_width': self.canvas_width,
            'canvas_height': self.canvas_height,
            'orientation': self.orientation,
            'background_type': self.background_type,
            'background_color': self.background_color,
            'background_opacity': self.background_opacity,
            'background_content': self.background_content,
            'is_template': self.is_template,
            'thumbnail_path': self.thumbnail_path,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        result['layer_count'] = self.layers.count() if self.layers else 0
        if include_layers:
            result['layers'] = [layer.to_dict() for layer in self.layers.order_by(ScreenLayer.z_index).all()]
        return result

    @property
    def is_landscape(self):
        """
        Check if layout is in landscape orientation.

        Returns:
            bool: True if orientation is landscape or width > height
        """
        if self.orientation == 'landscape':
            return True
        return self.canvas_width > self.canvas_height

    @property
    def is_portrait(self):
        """
        Check if layout is in portrait orientation.

        Returns:
            bool: True if orientation is portrait or height > width
        """
        if self.orientation == 'portrait':
            return True
        return self.canvas_height > self.canvas_width

    @property
    def aspect_ratio(self):
        """
        Calculate aspect ratio of the layout canvas.

        Returns:
            float or None: Width/height ratio, None if dimensions not set
        """
        if self.canvas_width and self.canvas_height:
            return self.canvas_width / self.canvas_height
        return None

    @property
    def resolution(self):
        """
        Get resolution as a formatted string.

        Returns:
            str: Resolution in 'WIDTHxHEIGHT' format
        """
        return f'{self.canvas_width}x{self.canvas_height}'

    @classmethod
    def get_templates(cls):
        """
        Get all template layouts.

        Returns:
            list: List of ScreenLayout instances marked as templates
        """
        return cls.query.filter_by(is_template=True).all()

    @classmethod
    def get_non_templates(cls):
        """
        Get all non-template layouts.

        Returns:
            list: List of ScreenLayout instances not marked as templates
        """
        return cls.query.filter_by(is_template=False).all()

    def duplicate(self, new_name=None):
        """
        Create a duplicate of this layout.

        Args:
            new_name: Optional name for the duplicate (defaults to 'Copy of {name}')

        Returns:
            ScreenLayout: A new unsaved ScreenLayout instance with copied properties
        """
        return ScreenLayout(
            name=new_name or f'Copy of {self.name}',
            description=self.description,
            canvas_width=self.canvas_width,
            canvas_height=self.canvas_height,
            orientation=self.orientation,
            background_type=self.background_type,
            background_color=self.background_color,
            background_opacity=self.background_opacity,
            background_content=self.background_content,
            is_template=False,  # Duplicates are not templates by default
            thumbnail_path=None,  # Will need new thumbnail
        )

    def __repr__(self):
        """String representation for debugging."""
        return f'<ScreenLayout {self.name} ({self.resolution})>'


class ScreenLayer(db.Model):
    """
    SQLAlchemy model representing a layer within a screen layout.

    A screen layer is a positioned rectangular region that can display
    content such as playlists, images, text, or widgets. Layers have
    geometry (position and size), styling (opacity, background), and
    visibility controls.

    Attributes:
        id: Unique UUID identifier
        layout_id: Foreign key reference to the parent layout
        name: Human-readable layer name
        layer_type: Type of layer ('content', 'text', 'widget', 'image')
        x: X position from left edge in pixels
        y: Y position from top edge in pixels
        width: Width of the layer in pixels
        height: Height of the layer in pixels
        z_index: Stacking order (higher values appear on top)
        opacity: Layer opacity from 0.0 (transparent) to 1.0 (opaque)
        background_type: Type of background ('solid', 'transparent', 'image')
        background_color: Background color in hex format (e.g., '#000000')
        is_visible: Whether the layer is visible in the layout
        is_locked: Whether the layer is locked from editing
        content_config: JSON configuration for the layer content
        created_at: Timestamp when the layer was created
        updated_at: Timestamp when the layer was last modified
    """

    __tablename__ = 'screen_layers'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    layout_id = db.Column(
        db.String(36),
        db.ForeignKey('screen_layouts.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    name = db.Column(db.String(255), nullable=False)
    layer_type = db.Column(db.String(50), nullable=False, default='content')

    # Geometry fields
    x = db.Column(db.Integer, nullable=False, default=0)
    y = db.Column(db.Integer, nullable=False, default=0)
    width = db.Column(db.Integer, nullable=False, default=400)
    height = db.Column(db.Integer, nullable=False, default=300)
    z_index = db.Column(db.Integer, nullable=False, default=0)

    # Styling fields
    opacity = db.Column(db.Float, nullable=False, default=1.0)
    background_type = db.Column(db.String(50), nullable=False, default='transparent')
    background_color = db.Column(db.String(50), nullable=True)

    # Visibility fields
    is_visible = db.Column(db.Boolean, nullable=False, default=True)
    is_locked = db.Column(db.Boolean, nullable=False, default=False)

    # Content source configuration
    content_source = db.Column(db.String(50), nullable=False, default='none')  # 'none', 'playlist', 'static', 'widget'
    playlist_id = db.Column(db.String(36), db.ForeignKey('playlists.id', ondelete='SET NULL'), nullable=True, index=True)
    content_id = db.Column(db.String(36), nullable=True, index=True)  # Can reference Content or SyncedContent
    is_primary = db.Column(db.Boolean, nullable=False, default=False)  # Primary layer for triggered content

    # Content configuration (JSON string for widget settings)
    content_config = db.Column(db.Text, nullable=True)

    # Relationships
    playlist = db.relationship('Playlist', backref=db.backref('layers', lazy='dynamic'))

    # Timestamps
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        """
        Serialize the layer to a dictionary for API responses.

        Returns:
            Dictionary containing all layer fields
        """
        import json
        # Parse content_config from JSON string to dict if present
        content_config = None
        if self.content_config:
            try:
                content_config = json.loads(self.content_config)
            except (json.JSONDecodeError, TypeError):
                content_config = self.content_config  # Keep as-is if not valid JSON

        return {
            'id': self.id,
            'layout_id': self.layout_id,
            'name': self.name,
            'layer_type': self.layer_type,
            'x': self.x,
            'y': self.y,
            'width': self.width,
            'height': self.height,
            'z_index': self.z_index,
            'opacity': self.opacity,
            'background_type': self.background_type,
            'background_color': self.background_color,
            'is_visible': self.is_visible,
            'is_locked': self.is_locked,
            'content_source': self.content_source,
            'playlist_id': self.playlist_id,
            'content_id': self.content_id,
            'is_primary': self.is_primary,
            'playlist_name': self.playlist.name if self.playlist else None,
            'content_config': content_config,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    @property
    def bounds(self):
        """
        Get the bounding box of the layer.

        Returns:
            dict: Dictionary with x, y, width, height, right, bottom
        """
        return {
            'x': self.x,
            'y': self.y,
            'width': self.width,
            'height': self.height,
            'right': self.x + self.width,
            'bottom': self.y + self.height,
        }

    @property
    def center(self):
        """
        Get the center point of the layer.

        Returns:
            tuple: (center_x, center_y) coordinates
        """
        return (self.x + self.width // 2, self.y + self.height // 2)

    @property
    def content(self):
        """
        Get the content associated with this layer.

        Resolves content_id to either a Content or SyncedContent instance.

        Returns:
            Content or SyncedContent instance, or None if not found
        """
        if not self.content_id:
            return None

        # Import here to avoid circular imports
        from cms.models.content import Content
        from cms.models.synced_content import SyncedContent

        # Try Content first (uploaded content)
        content = db.session.get(Content, self.content_id)
        if content:
            return content

        # Try SyncedContent (content catalog)
        synced = db.session.get(SyncedContent, self.content_id)
        return synced

    @classmethod
    def get_by_layout(cls, layout_id):
        """
        Get all layers for a specific layout ordered by z_index.

        Args:
            layout_id: The layout ID to filter by

        Returns:
            list: List of ScreenLayer instances for the layout
        """
        return cls.query.filter_by(layout_id=layout_id).order_by(cls.z_index).all()

    @classmethod
    def get_visible_by_layout(cls, layout_id):
        """
        Get all visible layers for a specific layout ordered by z_index.

        Args:
            layout_id: The layout ID to filter by

        Returns:
            list: List of visible ScreenLayer instances for the layout
        """
        return cls.query.filter_by(layout_id=layout_id, is_visible=True).order_by(cls.z_index).all()

    def duplicate(self, new_name=None, z_offset=1):
        """
        Create a duplicate of this layer.

        Args:
            new_name: Optional name for the duplicate (defaults to 'Copy of {name}')
            z_offset: Z-index offset for the new layer (default 1)

        Returns:
            ScreenLayer: A new unsaved ScreenLayer instance with copied properties
        """
        return ScreenLayer(
            layout_id=self.layout_id,
            name=new_name or f'Copy of {self.name}',
            layer_type=self.layer_type,
            x=self.x + 10,  # Offset slightly for visibility
            y=self.y + 10,
            width=self.width,
            height=self.height,
            z_index=self.z_index + z_offset,
            opacity=self.opacity,
            background_type=self.background_type,
            background_color=self.background_color,
            is_visible=self.is_visible,
            is_locked=False,  # Duplicates are not locked
            content_config=self.content_config,
        )

    def __repr__(self):
        """String representation for debugging."""
        return f'<ScreenLayer {self.name} z={self.z_index}>'


# Valid content modes for layer content assignments
CONTENT_MODES = [
    'static',     # Single static file (image, video, PDF)
    'playlist',   # Playlist-based content with triggers
    'ticker',     # Scrolling text ticker
]

# Valid ticker scroll directions
TICKER_DIRECTIONS = [
    'left',       # Scroll from right to left
    'right',      # Scroll from left to right
    'up',         # Scroll from bottom to top
    'down',       # Scroll from top to bottom
]


class LayerContent(db.Model):
    """
    SQLAlchemy model representing content assignment for a layer on a specific device.

    LayerContent defines what content should be displayed in a layer for a specific
    device. This allows the same layout to show different content on different devices.
    Content can be a static file (image, video, PDF) or a ticker with scrolling text.

    For playlist-based content, use LayerPlaylistAssignment instead.

    Attributes:
        id: Unique UUID identifier
        device_id: Foreign key reference to the device
        layer_id: Foreign key reference to the screen layer
        content_mode: Type of content ('static', 'playlist', 'ticker')
        static_file_id: Optional ID of the static file to display
        static_file_url: Optional URL/path to the static file
        pdf_page_duration: Duration in seconds for each PDF page (default 10)
        ticker_items: JSON array of text items for ticker display
        ticker_speed: Speed of ticker scroll in pixels per second (default 100)
        ticker_direction: Direction of ticker scroll ('left', 'right', 'up', 'down')
        created_at: Timestamp when the content assignment was created
        updated_at: Timestamp when the content assignment was last modified
    """

    __tablename__ = 'layer_content'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    device_id = db.Column(
        db.String(36),
        db.ForeignKey('devices.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    layer_id = db.Column(
        db.String(36),
        db.ForeignKey('screen_layers.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    content_mode = db.Column(db.String(50), nullable=False, default='static', index=True)

    # Static file fields
    static_file_id = db.Column(db.String(36), nullable=True)
    static_file_url = db.Column(db.Text, nullable=True)

    # PDF display settings
    pdf_page_duration = db.Column(db.Integer, nullable=False, default=10)

    # Ticker settings
    ticker_items = db.Column(db.Text, nullable=True)  # JSON array of text items
    ticker_speed = db.Column(db.Integer, nullable=False, default=100)
    ticker_direction = db.Column(db.String(50), nullable=False, default='left')

    # Timestamps
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    layer = db.relationship('ScreenLayer', backref=db.backref('content_assignments', lazy='dynamic', cascade='all, delete-orphan'))

    def to_dict(self):
        """
        Serialize the layer content to a dictionary for API responses.

        Returns:
            Dictionary containing all layer content fields
        """
        return {
            'id': self.id,
            'device_id': self.device_id,
            'layer_id': self.layer_id,
            'content_mode': self.content_mode,
            'static_file_id': self.static_file_id,
            'static_file_url': self.static_file_url,
            'pdf_page_duration': self.pdf_page_duration,
            'ticker_items': self.ticker_items,
            'ticker_speed': self.ticker_speed,
            'ticker_direction': self.ticker_direction,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    def to_dict_with_relations(self):
        """
        Serialize the layer content with related layer info.

        Returns:
            Dictionary containing layer content fields with nested layer
        """
        result = self.to_dict()
        result['layer'] = self.layer.to_dict() if self.layer else None
        return result

    def is_static_mode(self):
        """
        Check if this content assignment is in static file mode.

        Returns:
            bool: True if content_mode is 'static'
        """
        return self.content_mode == 'static'

    def is_playlist_mode(self):
        """
        Check if this content assignment is in playlist mode.

        Returns:
            bool: True if content_mode is 'playlist'
        """
        return self.content_mode == 'playlist'

    def is_ticker_mode(self):
        """
        Check if this content assignment is in ticker mode.

        Returns:
            bool: True if content_mode is 'ticker'
        """
        return self.content_mode == 'ticker'

    @classmethod
    def get_for_device_layer(cls, device_id, layer_id):
        """
        Get content assignment for a specific device and layer combination.

        Args:
            device_id: The device ID to filter by
            layer_id: The layer ID to filter by

        Returns:
            LayerContent instance or None if not found
        """
        return cls.query.filter_by(device_id=device_id, layer_id=layer_id).first()

    @classmethod
    def get_by_device(cls, device_id):
        """
        Get all content assignments for a specific device.

        Args:
            device_id: The device ID to filter by

        Returns:
            list: List of LayerContent instances for the device
        """
        return cls.query.filter_by(device_id=device_id).all()

    @classmethod
    def get_by_layer(cls, layer_id):
        """
        Get all content assignments for a specific layer.

        Args:
            layer_id: The layer ID to filter by

        Returns:
            list: List of LayerContent instances for the layer
        """
        return cls.query.filter_by(layer_id=layer_id).all()

    def __repr__(self):
        """String representation for debugging."""
        return f'<LayerContent device={self.device_id} layer={self.layer_id} mode={self.content_mode}>'


# Valid trigger types for layer playlist assignments (same as device assignments)
LAYER_TRIGGER_TYPES = [
    'default',          # Always plays (fallback content)
    'face_detected',    # Plays when any face is detected
    'age_child',        # Plays when child is detected (0-12)
    'age_teen',         # Plays when teen is detected (13-19)
    'age_adult',        # Plays when adult is detected (20-64)
    'age_senior',       # Plays when senior is detected (65+)
    'gender_male',      # Plays when male is detected
    'gender_female',    # Plays when female is detected
    'loyalty_recognized',  # Plays when loyalty member is recognized
    'ncmec_alert',      # Plays during NCMEC alert (amber alert content)
]


class LayerPlaylistAssignment(db.Model):
    """
    SQLAlchemy model representing a playlist-to-layer assignment for a specific device.

    A LayerPlaylistAssignment links a playlist to a layer for a specific device with
    trigger-based activation and priority information. This allows different content
    to be displayed in the same layer based on audience detection triggers.

    Multiple playlists can be assigned to a single layer with different triggers and
    priorities. When content_mode is 'playlist' in LayerContent, these assignments
    determine which playlist plays based on detected triggers.

    Attributes:
        id: Unique UUID identifier
        device_id: Foreign key reference to the device
        layer_id: Foreign key reference to the screen layer
        playlist_id: Foreign key reference to the assigned playlist
        trigger_type: Type of trigger that activates this playlist
        priority: Priority level for playlist ordering (higher = more important)
        created_at: Timestamp when the assignment was created
    """

    __tablename__ = 'layer_playlist_assignments'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    device_id = db.Column(
        db.String(36),
        db.ForeignKey('devices.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    layer_id = db.Column(
        db.String(36),
        db.ForeignKey('screen_layers.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    playlist_id = db.Column(
        db.String(36),
        db.ForeignKey('playlists.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    trigger_type = db.Column(db.String(50), nullable=False, default='default', index=True)
    priority = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Unique constraint on (device_id, layer_id, playlist_id)
    __table_args__ = (
        db.UniqueConstraint('device_id', 'layer_id', 'playlist_id', name='uq_device_layer_playlist'),
    )

    # Relationships
    layer = db.relationship('ScreenLayer', backref=db.backref('playlist_assignments', lazy='dynamic', cascade='all, delete-orphan'))
    playlist = db.relationship('Playlist', backref=db.backref('layer_assignments', lazy='dynamic', cascade='all, delete-orphan'))

    def to_dict(self):
        """
        Serialize the layer playlist assignment to a dictionary for API responses.

        Returns:
            Dictionary containing all assignment fields
        """
        return {
            'id': self.id,
            'device_id': self.device_id,
            'layer_id': self.layer_id,
            'playlist_id': self.playlist_id,
            'trigger_type': self.trigger_type,
            'priority': self.priority,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

    def to_dict_with_relations(self):
        """
        Serialize the assignment with related layer and playlist info.

        Returns:
            Dictionary containing assignment fields with nested layer and playlist
        """
        result = self.to_dict()
        result['layer'] = self.layer.to_dict() if self.layer else None
        result['playlist'] = self.playlist.to_dict() if self.playlist else None
        return result

    @classmethod
    def get_for_device_layer(cls, device_id, layer_id):
        """
        Get all playlist assignments for a specific device and layer, ordered by priority.

        Args:
            device_id: The device ID to filter by
            layer_id: The layer ID to filter by

        Returns:
            list: List of LayerPlaylistAssignment instances ordered by priority (desc)
        """
        return cls.query.filter_by(
            device_id=device_id,
            layer_id=layer_id
        ).order_by(cls.priority.desc()).all()

    @classmethod
    def get_by_trigger(cls, device_id, layer_id, trigger_type):
        """
        Get playlist assignments for a specific trigger type.

        Args:
            device_id: The device ID to filter by
            layer_id: The layer ID to filter by
            trigger_type: The trigger type to filter by

        Returns:
            list: List of LayerPlaylistAssignment instances for the trigger
        """
        return cls.query.filter_by(
            device_id=device_id,
            layer_id=layer_id,
            trigger_type=trigger_type
        ).order_by(cls.priority.desc()).all()

    @classmethod
    def get_by_playlist(cls, playlist_id):
        """
        Get all layer assignments for a specific playlist.

        Args:
            playlist_id: The playlist ID to filter by

        Returns:
            list: List of LayerPlaylistAssignment instances for the playlist
        """
        return cls.query.filter_by(playlist_id=playlist_id).all()

    @classmethod
    def get_by_layer(cls, layer_id):
        """
        Get all playlist assignments for a specific layer across all devices.

        Args:
            layer_id: The layer ID to filter by

        Returns:
            list: List of LayerPlaylistAssignment instances for the layer
        """
        return cls.query.filter_by(layer_id=layer_id).all()

    @classmethod
    def get_default_for_device_layer(cls, device_id, layer_id):
        """
        Get the default (fallback) playlist assignment for a device and layer.

        Args:
            device_id: The device ID to filter by
            layer_id: The layer ID to filter by

        Returns:
            LayerPlaylistAssignment instance or None if no default exists
        """
        return cls.query.filter_by(
            device_id=device_id,
            layer_id=layer_id,
            trigger_type='default'
        ).order_by(cls.priority.desc()).first()

    def __repr__(self):
        """String representation for debugging."""
        return f'<LayerPlaylistAssignment device={self.device_id} layer={self.layer_id} playlist={self.playlist_id} priority={self.priority}>'


class DeviceLayout(db.Model):
    """
    SQLAlchemy model representing a device-to-layout assignment with scheduling.

    A DeviceLayout links a device to a screen layout with scheduling and priority
    information. Multiple layouts can be assigned to a single device with different
    priorities and time-bounded schedules. The active layout is determined by
    checking date constraints and priority ordering.

    Attributes:
        id: Unique UUID identifier
        device_id: Foreign key reference to the assigned device
        layout_id: Foreign key reference to the assigned screen layout
        priority: Priority level for layout ordering (higher = more important)
        start_date: Optional start date for the assignment
        end_date: Optional end date for the assignment
        created_at: Timestamp when the assignment was created
    """

    __tablename__ = 'device_layouts'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    device_id = db.Column(
        db.String(36),
        db.ForeignKey('devices.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    layout_id = db.Column(
        db.String(36),
        db.ForeignKey('screen_layouts.id', ondelete='CASCADE'),
        nullable=False,
        index=True
    )
    priority = db.Column(db.Integer, nullable=False, default=0)
    start_date = db.Column(db.DateTime, nullable=True)
    end_date = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    last_pushed_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    device = db.relationship('Device', backref=db.backref('layout_assignments', lazy='dynamic', cascade='all, delete-orphan'))
    layout = db.relationship('ScreenLayout', backref=db.backref('device_assignments', lazy='dynamic', cascade='all, delete-orphan'))

    def to_dict(self):
        """
        Serialize the device layout assignment to a dictionary for API responses.

        Returns:
            Dictionary containing all device layout fields
        """
        return {
            'id': self.id,
            'device_id': self.device_id,
            'layout_id': self.layout_id,
            'priority': self.priority,
            'start_date': self.start_date.isoformat() if self.start_date else None,
            'end_date': self.end_date.isoformat() if self.end_date else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_pushed_at': self.last_pushed_at.isoformat() if self.last_pushed_at else None
        }

    def to_dict_with_relations(self):
        """
        Serialize the device layout assignment with related device and layout info.

        Returns:
            Dictionary containing assignment fields with nested device and layout
        """
        result = self.to_dict()
        result['device'] = self.device.to_dict() if self.device else None
        result['layout'] = self.layout.to_dict() if self.layout else None
        return result

    def is_active(self):
        """
        Check if the assignment is currently active based on date constraints.

        Returns:
            bool: True if assignment is active (within date range or no dates set)
        """
        now = datetime.now(timezone.utc)

        # If no date constraints, always active
        if not self.start_date and not self.end_date:
            return True

        # Check start date
        if self.start_date and now < self.start_date:
            return False

        # Check end date
        if self.end_date and now > self.end_date:
            return False

        return True

    @classmethod
    def get_active_for_device(cls, device_id):
        """
        Get all currently active layout assignments for a device, ordered by priority.

        Args:
            device_id: The device ID to filter by

        Returns:
            list: List of active DeviceLayout instances ordered by priority (desc)
        """
        now = datetime.now(timezone.utc)
        return cls.query.filter(
            cls.device_id == device_id,
            db.or_(cls.start_date.is_(None), cls.start_date <= now),
            db.or_(cls.end_date.is_(None), cls.end_date >= now)
        ).order_by(cls.priority.desc()).all()

    @classmethod
    def get_by_layout(cls, layout_id):
        """
        Get all assignments for a specific layout.

        Args:
            layout_id: The layout ID to filter by

        Returns:
            list: List of DeviceLayout instances for the layout
        """
        return cls.query.filter_by(layout_id=layout_id).all()

    @classmethod
    def get_current_layout_for_device(cls, device_id):
        """
        Get the currently active layout for a device (highest priority active assignment).

        Args:
            device_id: The device ID to get current layout for

        Returns:
            ScreenLayout instance or None if no active layout is assigned
        """
        active_assignments = cls.get_active_for_device(device_id)
        if active_assignments:
            return active_assignments[0].layout
        return None

    def __repr__(self):
        """String representation for debugging."""
        return f'<DeviceLayout device={self.device_id} layout={self.layout_id} priority={self.priority}>'
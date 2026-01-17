"""
Layout Service for CMS.

Provides business logic for screen layout operations including:
- Layout CRUD: create, read, update, delete layouts
- Layer management: create, update, delete, reorder layers
- Validation: size constraints, canvas bounds, z-index management
- Duplication: copy layouts and layers with all settings

The service follows the existing CMS patterns with class methods
for operations and proper database transaction handling.
"""

from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Tuple

from cms.models import db
from cms.models.layout import (
    ScreenLayout,
    ScreenLayer,
    LayerContent,
    LayerPlaylistAssignment,
    DeviceLayout,
    CONTENT_MODES,
    TICKER_DIRECTIONS,
    LAYER_TRIGGER_TYPES,
)


class LayoutService:
    """
    Service class for managing screen layouts and layers.

    This service provides all business logic for layout operations,
    including CRUD operations, layer management, validation, and
    device assignments. All methods use the Flask-SQLAlchemy db session.
    """

    # Validation constants
    MIN_LAYER_SIZE = 20  # Minimum layer width/height in pixels
    MAX_LAYER_SIZE = 10000  # Maximum layer dimension
    DEFAULT_CANVAS_WIDTH = 1920
    DEFAULT_CANVAS_HEIGHT = 1080
    DEFAULT_LAYER_WIDTH = 400
    DEFAULT_LAYER_HEIGHT = 300

    # Valid background types
    BACKGROUND_TYPES = ['solid', 'transparent', 'image']

    # Valid orientations
    ORIENTATIONS = ['landscape', 'portrait']

    # Valid layer types
    LAYER_TYPES = ['content', 'text', 'widget', 'image', 'ticker', 'clock', 'weather', 'html', 'shape']

    # ==========================================================================
    # Layout CRUD Operations
    # ==========================================================================

    @classmethod
    def create_layout(
        cls,
        name: str,
        canvas_width: int = None,
        canvas_height: int = None,
        description: str = None,
        orientation: str = 'landscape',
        background_type: str = 'solid',
        background_color: str = '#000000',
        background_opacity: float = 1.0,
        is_template: bool = False,
    ) -> ScreenLayout:
        """
        Create a new screen layout.

        Args:
            name: Human-readable layout name (required)
            canvas_width: Width in pixels (default 1920)
            canvas_height: Height in pixels (default 1080)
            description: Optional description
            orientation: 'landscape' or 'portrait'
            background_type: 'solid', 'transparent', or 'image'
            background_color: Hex color (e.g., '#000000')
            background_opacity: Opacity from 0.0 to 1.0
            is_template: Whether this is a reusable template

        Returns:
            ScreenLayout: The newly created layout

        Raises:
            ValueError: If validation fails
        """
        # Apply defaults
        canvas_width = canvas_width or cls.DEFAULT_CANVAS_WIDTH
        canvas_height = canvas_height or cls.DEFAULT_CANVAS_HEIGHT

        # Validate inputs
        cls._validate_layout_inputs(
            name=name,
            canvas_width=canvas_width,
            canvas_height=canvas_height,
            orientation=orientation,
            background_type=background_type,
            background_opacity=background_opacity,
        )

        # Create layout
        layout = ScreenLayout(
            name=name,
            description=description,
            canvas_width=canvas_width,
            canvas_height=canvas_height,
            orientation=orientation,
            background_type=background_type,
            background_color=background_color,
            background_opacity=background_opacity,
            is_template=is_template,
        )

        db.session.add(layout)
        db.session.commit()

        return layout

    @classmethod
    def get_layout(cls, layout_id: str) -> Optional[ScreenLayout]:
        """
        Get a layout by ID.

        Args:
            layout_id: The UUID of the layout

        Returns:
            ScreenLayout or None if not found
        """
        return ScreenLayout.query.get(layout_id)

    @classmethod
    def get_layout_or_404(cls, layout_id: str) -> ScreenLayout:
        """
        Get a layout by ID or raise a 404 error.

        Args:
            layout_id: The UUID of the layout

        Returns:
            ScreenLayout instance

        Raises:
            ValueError: If layout not found
        """
        layout = cls.get_layout(layout_id)
        if not layout:
            raise ValueError(f"Layout with ID '{layout_id}' not found")
        return layout

    @classmethod
    def list_layouts(
        cls,
        include_templates: bool = True,
        templates_only: bool = False,
    ) -> List[ScreenLayout]:
        """
        List all layouts with optional filtering.

        Args:
            include_templates: Include template layouts
            templates_only: Only return templates

        Returns:
            List of ScreenLayout instances
        """
        query = ScreenLayout.query

        if templates_only:
            query = query.filter_by(is_template=True)
        elif not include_templates:
            query = query.filter_by(is_template=False)

        return query.order_by(ScreenLayout.updated_at.desc()).all()

    @classmethod
    def update_layout(
        cls,
        layout_id: str,
        **kwargs,
    ) -> ScreenLayout:
        """
        Update a layout's properties.

        Args:
            layout_id: The UUID of the layout
            **kwargs: Fields to update (name, description, canvas_width, etc.)

        Returns:
            ScreenLayout: The updated layout

        Raises:
            ValueError: If layout not found or validation fails
        """
        layout = cls.get_layout_or_404(layout_id)

        # Validate any dimension or background changes
        canvas_width = kwargs.get('canvas_width', layout.canvas_width)
        canvas_height = kwargs.get('canvas_height', layout.canvas_height)
        orientation = kwargs.get('orientation', layout.orientation)
        background_type = kwargs.get('background_type', layout.background_type)
        background_opacity = kwargs.get('background_opacity', layout.background_opacity)

        if 'name' in kwargs or 'canvas_width' in kwargs or 'canvas_height' in kwargs:
            cls._validate_layout_inputs(
                name=kwargs.get('name', layout.name),
                canvas_width=canvas_width,
                canvas_height=canvas_height,
                orientation=orientation,
                background_type=background_type,
                background_opacity=background_opacity,
            )

        # Update fields
        allowed_fields = [
            'name', 'description', 'canvas_width', 'canvas_height',
            'orientation', 'background_type', 'background_color',
            'background_opacity', 'background_content', 'is_template',
            'thumbnail_path'
        ]

        for field in allowed_fields:
            if field in kwargs:
                setattr(layout, field, kwargs[field])

        layout.updated_at = datetime.now(timezone.utc)
        db.session.commit()

        return layout

    @classmethod
    def delete_layout(cls, layout_id: str) -> bool:
        """
        Delete a layout and all associated layers.

        Due to cascade delete, all layers, content assignments, and
        playlist assignments will be automatically removed.

        Args:
            layout_id: The UUID of the layout

        Returns:
            bool: True if deleted successfully

        Raises:
            ValueError: If layout not found
        """
        layout = cls.get_layout_or_404(layout_id)

        db.session.delete(layout)
        db.session.commit()

        return True

    @classmethod
    def duplicate_layout(
        cls,
        layout_id: str,
        new_name: str = None,
        include_layers: bool = True,
    ) -> ScreenLayout:
        """
        Duplicate a layout with optional layers.

        Args:
            layout_id: The UUID of the layout to duplicate
            new_name: Name for the new layout (defaults to 'Copy of {name}')
            include_layers: Whether to copy all layers too

        Returns:
            ScreenLayout: The newly created duplicate layout

        Raises:
            ValueError: If source layout not found
        """
        source_layout = cls.get_layout_or_404(layout_id)

        # Create duplicate layout
        new_layout = source_layout.duplicate(new_name)
        db.session.add(new_layout)
        db.session.flush()  # Get the new layout ID

        # Duplicate layers if requested
        if include_layers:
            for source_layer in source_layout.layers.order_by(ScreenLayer.z_index).all():
                new_layer = ScreenLayer(
                    layout_id=new_layout.id,
                    name=source_layer.name,
                    layer_type=source_layer.layer_type,
                    x=source_layer.x,
                    y=source_layer.y,
                    width=source_layer.width,
                    height=source_layer.height,
                    z_index=source_layer.z_index,
                    opacity=source_layer.opacity,
                    background_type=source_layer.background_type,
                    background_color=source_layer.background_color,
                    is_visible=source_layer.is_visible,
                    is_locked=False,
                    content_config=source_layer.content_config,
                )
                db.session.add(new_layer)

        db.session.commit()

        return new_layout

    # ==========================================================================
    # Layer CRUD Operations
    # ==========================================================================

    @classmethod
    def create_layer(
        cls,
        layout_id: str,
        name: str,
        x: int = 0,
        y: int = 0,
        width: int = None,
        height: int = None,
        layer_type: str = 'content',
        z_index: int = None,
        opacity: float = 1.0,
        background_type: str = 'transparent',
        background_color: str = None,
        is_visible: bool = True,
    ) -> ScreenLayer:
        """
        Create a new layer in a layout.

        Args:
            layout_id: The UUID of the parent layout
            name: Human-readable layer name
            x: X position from left edge in pixels
            y: Y position from top edge in pixels
            width: Width in pixels (default 400)
            height: Height in pixels (default 300)
            layer_type: Type of layer ('content', 'text', etc.)
            z_index: Stacking order (auto-assigns if None)
            opacity: Layer opacity (0.0 to 1.0)
            background_type: 'solid', 'transparent', or 'image'
            background_color: Hex color for background
            is_visible: Whether layer is visible

        Returns:
            ScreenLayer: The newly created layer

        Raises:
            ValueError: If validation fails or layout not found
        """
        layout = cls.get_layout_or_404(layout_id)

        # Apply defaults
        width = width or cls.DEFAULT_LAYER_WIDTH
        height = height or cls.DEFAULT_LAYER_HEIGHT

        # Auto-assign z_index if not provided
        if z_index is None:
            max_z = db.session.query(db.func.max(ScreenLayer.z_index)).filter(
                ScreenLayer.layout_id == layout_id
            ).scalar()
            z_index = (max_z or 0) + 1

        # Validate layer inputs
        cls._validate_layer_inputs(
            layout=layout,
            x=x,
            y=y,
            width=width,
            height=height,
            layer_type=layer_type,
            opacity=opacity,
            background_type=background_type,
        )

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
            background_color=background_color,
            is_visible=is_visible,
            is_locked=False,
        )

        db.session.add(layer)
        db.session.commit()

        return layer

    @classmethod
    def get_layer(cls, layer_id: str) -> Optional[ScreenLayer]:
        """
        Get a layer by ID.

        Args:
            layer_id: The UUID of the layer

        Returns:
            ScreenLayer or None if not found
        """
        return ScreenLayer.query.get(layer_id)

    @classmethod
    def get_layer_or_404(cls, layer_id: str) -> ScreenLayer:
        """
        Get a layer by ID or raise an error.

        Args:
            layer_id: The UUID of the layer

        Returns:
            ScreenLayer instance

        Raises:
            ValueError: If layer not found
        """
        layer = cls.get_layer(layer_id)
        if not layer:
            raise ValueError(f"Layer with ID '{layer_id}' not found")
        return layer

    @classmethod
    def get_layers_for_layout(cls, layout_id: str) -> List[ScreenLayer]:
        """
        Get all layers for a layout ordered by z_index.

        Args:
            layout_id: The UUID of the layout

        Returns:
            List of ScreenLayer instances
        """
        return ScreenLayer.get_by_layout(layout_id)

    @classmethod
    def update_layer(
        cls,
        layer_id: str,
        **kwargs,
    ) -> ScreenLayer:
        """
        Update a layer's properties.

        Args:
            layer_id: The UUID of the layer
            **kwargs: Fields to update (name, x, y, width, height, etc.)

        Returns:
            ScreenLayer: The updated layer

        Raises:
            ValueError: If layer not found or validation fails
        """
        layer = cls.get_layer_or_404(layer_id)
        layout = layer.layout

        # Validate geometry changes
        x = kwargs.get('x', layer.x)
        y = kwargs.get('y', layer.y)
        width = kwargs.get('width', layer.width)
        height = kwargs.get('height', layer.height)
        layer_type = kwargs.get('layer_type', layer.layer_type)
        opacity = kwargs.get('opacity', layer.opacity)
        background_type = kwargs.get('background_type', layer.background_type)

        if any(k in kwargs for k in ['x', 'y', 'width', 'height', 'opacity', 'layer_type', 'background_type']):
            cls._validate_layer_inputs(
                layout=layout,
                x=x,
                y=y,
                width=width,
                height=height,
                layer_type=layer_type,
                opacity=opacity,
                background_type=background_type,
            )

        # Update fields
        allowed_fields = [
            'name', 'layer_type', 'x', 'y', 'width', 'height', 'z_index',
            'opacity', 'background_type', 'background_color',
            'is_visible', 'is_locked', 'content_config'
        ]

        for field in allowed_fields:
            if field in kwargs:
                setattr(layer, field, kwargs[field])

        layer.updated_at = datetime.now(timezone.utc)
        db.session.commit()

        return layer

    @classmethod
    def delete_layer(cls, layer_id: str) -> bool:
        """
        Delete a layer.

        Due to cascade delete, all content assignments and playlist
        assignments will be automatically removed.

        Args:
            layer_id: The UUID of the layer

        Returns:
            bool: True if deleted successfully

        Raises:
            ValueError: If layer not found
        """
        layer = cls.get_layer_or_404(layer_id)

        db.session.delete(layer)
        db.session.commit()

        return True

    @classmethod
    def duplicate_layer(
        cls,
        layer_id: str,
        new_name: str = None,
    ) -> ScreenLayer:
        """
        Duplicate a layer within the same layout.

        Args:
            layer_id: The UUID of the layer to duplicate
            new_name: Name for the new layer (defaults to 'Copy of {name}')

        Returns:
            ScreenLayer: The newly created duplicate layer

        Raises:
            ValueError: If source layer not found
        """
        source_layer = cls.get_layer_or_404(layer_id)

        new_layer = source_layer.duplicate(new_name)
        db.session.add(new_layer)
        db.session.commit()

        return new_layer

    # ==========================================================================
    # Layer Ordering Operations
    # ==========================================================================

    @classmethod
    def reorder_layers(cls, layout_id: str, layer_ids: List[str]) -> List[ScreenLayer]:
        """
        Reorder layers by setting z_index based on list order.

        Args:
            layout_id: The UUID of the layout
            layer_ids: List of layer IDs in desired z-order (first = bottom)

        Returns:
            List of updated ScreenLayer instances

        Raises:
            ValueError: If layout not found or layer IDs don't match
        """
        layout = cls.get_layout_or_404(layout_id)

        # Get all existing layer IDs
        existing_ids = {layer.id for layer in layout.layers.all()}

        # Validate all provided IDs exist in the layout
        for layer_id in layer_ids:
            if layer_id not in existing_ids:
                raise ValueError(f"Layer ID '{layer_id}' not found in layout")

        # Update z_index for each layer
        updated_layers = []
        for z_index, layer_id in enumerate(layer_ids):
            layer = ScreenLayer.query.get(layer_id)
            layer.z_index = z_index
            layer.updated_at = datetime.now(timezone.utc)
            updated_layers.append(layer)

        db.session.commit()

        return updated_layers

    @classmethod
    def bring_layer_forward(cls, layer_id: str) -> ScreenLayer:
        """
        Move a layer one step forward (increase z_index).

        Args:
            layer_id: The UUID of the layer

        Returns:
            ScreenLayer: The updated layer

        Raises:
            ValueError: If layer not found
        """
        layer = cls.get_layer_or_404(layer_id)

        # Find the layer with the next higher z_index
        next_layer = ScreenLayer.query.filter(
            ScreenLayer.layout_id == layer.layout_id,
            ScreenLayer.z_index > layer.z_index
        ).order_by(ScreenLayer.z_index).first()

        if next_layer:
            # Swap z_index values
            current_z = layer.z_index
            layer.z_index = next_layer.z_index
            next_layer.z_index = current_z
            layer.updated_at = datetime.now(timezone.utc)
            next_layer.updated_at = datetime.now(timezone.utc)
            db.session.commit()

        return layer

    @classmethod
    def send_layer_backward(cls, layer_id: str) -> ScreenLayer:
        """
        Move a layer one step backward (decrease z_index).

        Args:
            layer_id: The UUID of the layer

        Returns:
            ScreenLayer: The updated layer

        Raises:
            ValueError: If layer not found
        """
        layer = cls.get_layer_or_404(layer_id)

        # Find the layer with the next lower z_index
        prev_layer = ScreenLayer.query.filter(
            ScreenLayer.layout_id == layer.layout_id,
            ScreenLayer.z_index < layer.z_index
        ).order_by(ScreenLayer.z_index.desc()).first()

        if prev_layer:
            # Swap z_index values
            current_z = layer.z_index
            layer.z_index = prev_layer.z_index
            prev_layer.z_index = current_z
            layer.updated_at = datetime.now(timezone.utc)
            prev_layer.updated_at = datetime.now(timezone.utc)
            db.session.commit()

        return layer

    @classmethod
    def bring_layer_to_front(cls, layer_id: str) -> ScreenLayer:
        """
        Move a layer to the front (highest z_index).

        Args:
            layer_id: The UUID of the layer

        Returns:
            ScreenLayer: The updated layer

        Raises:
            ValueError: If layer not found
        """
        layer = cls.get_layer_or_404(layer_id)

        # Get max z_index in layout
        max_z = db.session.query(db.func.max(ScreenLayer.z_index)).filter(
            ScreenLayer.layout_id == layer.layout_id
        ).scalar() or 0

        if layer.z_index < max_z:
            layer.z_index = max_z + 1
            layer.updated_at = datetime.now(timezone.utc)
            db.session.commit()

        return layer

    @classmethod
    def send_layer_to_back(cls, layer_id: str) -> ScreenLayer:
        """
        Move a layer to the back (lowest z_index).

        Args:
            layer_id: The UUID of the layer

        Returns:
            ScreenLayer: The updated layer

        Raises:
            ValueError: If layer not found
        """
        layer = cls.get_layer_or_404(layer_id)

        # Get min z_index in layout
        min_z = db.session.query(db.func.min(ScreenLayer.z_index)).filter(
            ScreenLayer.layout_id == layer.layout_id
        ).scalar() or 0

        if layer.z_index > min_z:
            layer.z_index = min_z - 1
            layer.updated_at = datetime.now(timezone.utc)
            db.session.commit()

        return layer

    # ==========================================================================
    # Device Layout Assignment Operations
    # ==========================================================================

    @classmethod
    def assign_layout_to_device(
        cls,
        device_id: str,
        layout_id: str,
        priority: int = 0,
        start_date: datetime = None,
        end_date: datetime = None,
    ) -> DeviceLayout:
        """
        Assign a layout to a device.

        Args:
            device_id: The UUID of the device
            layout_id: The UUID of the layout
            priority: Priority for ordering (higher = more important)
            start_date: Optional scheduled start date
            end_date: Optional scheduled end date

        Returns:
            DeviceLayout: The assignment record

        Raises:
            ValueError: If layout not found
        """
        # Validate layout exists
        cls.get_layout_or_404(layout_id)

        # Check for existing assignment
        existing = DeviceLayout.query.filter_by(
            device_id=device_id,
            layout_id=layout_id
        ).first()

        if existing:
            # Update existing assignment
            existing.priority = priority
            existing.start_date = start_date
            existing.end_date = end_date
            db.session.commit()
            return existing

        # Create new assignment
        assignment = DeviceLayout(
            device_id=device_id,
            layout_id=layout_id,
            priority=priority,
            start_date=start_date,
            end_date=end_date,
        )

        db.session.add(assignment)
        db.session.commit()

        return assignment

    @classmethod
    def unassign_layout_from_device(
        cls,
        device_id: str,
        layout_id: str,
    ) -> bool:
        """
        Remove a layout assignment from a device.

        Args:
            device_id: The UUID of the device
            layout_id: The UUID of the layout

        Returns:
            bool: True if removed, False if not found
        """
        assignment = DeviceLayout.query.filter_by(
            device_id=device_id,
            layout_id=layout_id
        ).first()

        if assignment:
            db.session.delete(assignment)
            db.session.commit()
            return True

        return False

    @classmethod
    def get_device_layouts(cls, device_id: str) -> List[DeviceLayout]:
        """
        Get all layout assignments for a device.

        Args:
            device_id: The UUID of the device

        Returns:
            List of DeviceLayout instances ordered by priority
        """
        return DeviceLayout.query.filter_by(
            device_id=device_id
        ).order_by(DeviceLayout.priority.desc()).all()

    @classmethod
    def get_current_layout_for_device(cls, device_id: str) -> Optional[ScreenLayout]:
        """
        Get the currently active layout for a device.

        Args:
            device_id: The UUID of the device

        Returns:
            ScreenLayout or None if no active layout
        """
        return DeviceLayout.get_current_layout_for_device(device_id)

    # ==========================================================================
    # Layer Content Operations
    # ==========================================================================

    @classmethod
    def set_layer_content(
        cls,
        device_id: str,
        layer_id: str,
        content_mode: str,
        static_file_id: str = None,
        static_file_url: str = None,
        pdf_page_duration: int = 10,
        ticker_items: str = None,
        ticker_speed: int = 100,
        ticker_direction: str = 'left',
    ) -> LayerContent:
        """
        Set content for a layer on a specific device.

        Args:
            device_id: The UUID of the device
            layer_id: The UUID of the layer
            content_mode: 'static', 'playlist', or 'ticker'
            static_file_id: ID of static file (for static mode)
            static_file_url: URL/path of static file (for static mode)
            pdf_page_duration: Seconds per PDF page (for static mode)
            ticker_items: JSON array of ticker items (for ticker mode)
            ticker_speed: Ticker scroll speed (for ticker mode)
            ticker_direction: Ticker direction (for ticker mode)

        Returns:
            LayerContent: The content assignment record

        Raises:
            ValueError: If validation fails
        """
        # Validate layer exists
        cls.get_layer_or_404(layer_id)

        # Validate content mode
        if content_mode not in CONTENT_MODES:
            raise ValueError(f"Invalid content mode '{content_mode}'. Must be one of: {CONTENT_MODES}")

        # Validate ticker direction
        if ticker_direction not in TICKER_DIRECTIONS:
            raise ValueError(f"Invalid ticker direction '{ticker_direction}'. Must be one of: {TICKER_DIRECTIONS}")

        # Get or create content assignment
        content = LayerContent.get_for_device_layer(device_id, layer_id)

        if content:
            # Update existing
            content.content_mode = content_mode
            content.static_file_id = static_file_id
            content.static_file_url = static_file_url
            content.pdf_page_duration = pdf_page_duration
            content.ticker_items = ticker_items
            content.ticker_speed = ticker_speed
            content.ticker_direction = ticker_direction
            content.updated_at = datetime.now(timezone.utc)
        else:
            # Create new
            content = LayerContent(
                device_id=device_id,
                layer_id=layer_id,
                content_mode=content_mode,
                static_file_id=static_file_id,
                static_file_url=static_file_url,
                pdf_page_duration=pdf_page_duration,
                ticker_items=ticker_items,
                ticker_speed=ticker_speed,
                ticker_direction=ticker_direction,
            )
            db.session.add(content)

        db.session.commit()

        return content

    @classmethod
    def get_layer_content(
        cls,
        device_id: str,
        layer_id: str,
    ) -> Optional[LayerContent]:
        """
        Get content assignment for a layer on a device.

        Args:
            device_id: The UUID of the device
            layer_id: The UUID of the layer

        Returns:
            LayerContent or None if not found
        """
        return LayerContent.get_for_device_layer(device_id, layer_id)

    @classmethod
    def delete_layer_content(
        cls,
        device_id: str,
        layer_id: str,
    ) -> bool:
        """
        Remove content assignment from a layer.

        Args:
            device_id: The UUID of the device
            layer_id: The UUID of the layer

        Returns:
            bool: True if deleted, False if not found
        """
        content = LayerContent.get_for_device_layer(device_id, layer_id)

        if content:
            db.session.delete(content)
            db.session.commit()
            return True

        return False

    # ==========================================================================
    # Layer Playlist Assignment Operations
    # ==========================================================================

    @classmethod
    def assign_playlist_to_layer(
        cls,
        device_id: str,
        layer_id: str,
        playlist_id: str,
        trigger_type: str = 'default',
        priority: int = 0,
    ) -> LayerPlaylistAssignment:
        """
        Assign a playlist to a layer for a specific device.

        Args:
            device_id: The UUID of the device
            layer_id: The UUID of the layer
            playlist_id: The UUID of the playlist
            trigger_type: Trigger type (e.g., 'default', 'face_detected')
            priority: Priority for ordering (higher = more important)

        Returns:
            LayerPlaylistAssignment: The assignment record

        Raises:
            ValueError: If validation fails
        """
        # Validate layer exists
        cls.get_layer_or_404(layer_id)

        # Validate trigger type
        if trigger_type not in LAYER_TRIGGER_TYPES:
            raise ValueError(f"Invalid trigger type '{trigger_type}'. Must be one of: {LAYER_TRIGGER_TYPES}")

        # Check for existing assignment with same device/layer/playlist
        existing = LayerPlaylistAssignment.query.filter_by(
            device_id=device_id,
            layer_id=layer_id,
            playlist_id=playlist_id
        ).first()

        if existing:
            # Update existing
            existing.trigger_type = trigger_type
            existing.priority = priority
            db.session.commit()
            return existing

        # Create new assignment
        assignment = LayerPlaylistAssignment(
            device_id=device_id,
            layer_id=layer_id,
            playlist_id=playlist_id,
            trigger_type=trigger_type,
            priority=priority,
        )

        db.session.add(assignment)
        db.session.commit()

        return assignment

    @classmethod
    def unassign_playlist_from_layer(
        cls,
        device_id: str,
        layer_id: str,
        playlist_id: str,
    ) -> bool:
        """
        Remove a playlist assignment from a layer.

        Args:
            device_id: The UUID of the device
            layer_id: The UUID of the layer
            playlist_id: The UUID of the playlist

        Returns:
            bool: True if removed, False if not found
        """
        assignment = LayerPlaylistAssignment.query.filter_by(
            device_id=device_id,
            layer_id=layer_id,
            playlist_id=playlist_id
        ).first()

        if assignment:
            db.session.delete(assignment)
            db.session.commit()
            return True

        return False

    @classmethod
    def get_layer_playlist_assignments(
        cls,
        device_id: str,
        layer_id: str,
    ) -> List[LayerPlaylistAssignment]:
        """
        Get all playlist assignments for a layer on a device.

        Args:
            device_id: The UUID of the device
            layer_id: The UUID of the layer

        Returns:
            List of LayerPlaylistAssignment instances ordered by priority
        """
        return LayerPlaylistAssignment.get_for_device_layer(device_id, layer_id)

    # ==========================================================================
    # Validation Methods
    # ==========================================================================

    @classmethod
    def _validate_layout_inputs(
        cls,
        name: str,
        canvas_width: int,
        canvas_height: int,
        orientation: str,
        background_type: str,
        background_opacity: float,
    ) -> None:
        """
        Validate layout creation/update inputs.

        Args:
            name: Layout name
            canvas_width: Canvas width in pixels
            canvas_height: Canvas height in pixels
            orientation: Layout orientation
            background_type: Background type
            background_opacity: Background opacity

        Raises:
            ValueError: If validation fails
        """
        if not name or not name.strip():
            raise ValueError("Layout name is required")

        if canvas_width < cls.MIN_LAYER_SIZE:
            raise ValueError(f"Canvas width must be at least {cls.MIN_LAYER_SIZE} pixels")

        if canvas_width > cls.MAX_LAYER_SIZE:
            raise ValueError(f"Canvas width cannot exceed {cls.MAX_LAYER_SIZE} pixels")

        if canvas_height < cls.MIN_LAYER_SIZE:
            raise ValueError(f"Canvas height must be at least {cls.MIN_LAYER_SIZE} pixels")

        if canvas_height > cls.MAX_LAYER_SIZE:
            raise ValueError(f"Canvas height cannot exceed {cls.MAX_LAYER_SIZE} pixels")

        if orientation not in cls.ORIENTATIONS:
            raise ValueError(f"Invalid orientation '{orientation}'. Must be one of: {cls.ORIENTATIONS}")

        if background_type not in cls.BACKGROUND_TYPES:
            raise ValueError(f"Invalid background type '{background_type}'. Must be one of: {cls.BACKGROUND_TYPES}")

        if not (0.0 <= background_opacity <= 1.0):
            raise ValueError("Background opacity must be between 0.0 and 1.0")

    @classmethod
    def _validate_layer_inputs(
        cls,
        layout: ScreenLayout,
        x: int,
        y: int,
        width: int,
        height: int,
        layer_type: str,
        opacity: float,
        background_type: str,
    ) -> None:
        """
        Validate layer creation/update inputs.

        Args:
            layout: The parent layout
            x: Layer x position
            y: Layer y position
            width: Layer width
            height: Layer height
            layer_type: Layer type
            opacity: Layer opacity
            background_type: Background type

        Raises:
            ValueError: If validation fails
        """
        # Validate minimum size
        if width < cls.MIN_LAYER_SIZE:
            raise ValueError(f"Layer width must be at least {cls.MIN_LAYER_SIZE} pixels")

        if height < cls.MIN_LAYER_SIZE:
            raise ValueError(f"Layer height must be at least {cls.MIN_LAYER_SIZE} pixels")

        # Validate maximum size (cannot exceed canvas)
        if width > layout.canvas_width:
            raise ValueError(f"Layer width cannot exceed canvas width ({layout.canvas_width} pixels)")

        if height > layout.canvas_height:
            raise ValueError(f"Layer height cannot exceed canvas height ({layout.canvas_height} pixels)")

        # Validate layer type
        if layer_type not in cls.LAYER_TYPES:
            raise ValueError(f"Invalid layer type '{layer_type}'. Must be one of: {cls.LAYER_TYPES}")

        # Validate opacity
        if not (0.0 <= opacity <= 1.0):
            raise ValueError("Layer opacity must be between 0.0 and 1.0")

        # Validate background type
        if background_type not in cls.BACKGROUND_TYPES:
            raise ValueError(f"Invalid background type '{background_type}'. Must be one of: {cls.BACKGROUND_TYPES}")

    @classmethod
    def validate_layer_bounds(
        cls,
        layout: ScreenLayout,
        x: int,
        y: int,
        width: int,
        height: int,
    ) -> Tuple[int, int, int, int]:
        """
        Constrain layer bounds to canvas dimensions.

        This method ensures a layer fits within the canvas by adjusting
        position and size as needed, rather than raising an error.

        Args:
            layout: The parent layout
            x: Desired x position
            y: Desired y position
            width: Desired width
            height: Desired height

        Returns:
            Tuple of (x, y, width, height) constrained to canvas
        """
        # Ensure minimum size
        width = max(width, cls.MIN_LAYER_SIZE)
        height = max(height, cls.MIN_LAYER_SIZE)

        # Constrain size to canvas
        width = min(width, layout.canvas_width)
        height = min(height, layout.canvas_height)

        # Constrain position to keep layer visible
        x = max(0, min(x, layout.canvas_width - width))
        y = max(0, min(y, layout.canvas_height - height))

        return (int(x), int(y), int(width), int(height))

    # ==========================================================================
    # Utility Methods
    # ==========================================================================

    @classmethod
    def get_layout_summary(cls, layout_id: str) -> Dict[str, Any]:
        """
        Get a summary of a layout including layer count and content.

        Args:
            layout_id: The UUID of the layout

        Returns:
            Dictionary with layout summary information

        Raises:
            ValueError: If layout not found
        """
        layout = cls.get_layout_or_404(layout_id)

        layers = layout.layers.all()
        visible_count = sum(1 for l in layers if l.is_visible)
        locked_count = sum(1 for l in layers if l.is_locked)

        return {
            'id': layout.id,
            'name': layout.name,
            'resolution': layout.resolution,
            'orientation': layout.orientation,
            'layer_count': len(layers),
            'visible_layers': visible_count,
            'locked_layers': locked_count,
            'is_template': layout.is_template,
            'created_at': layout.created_at.isoformat() if layout.created_at else None,
            'updated_at': layout.updated_at.isoformat() if layout.updated_at else None,
        }

    @classmethod
    def get_full_layout_config(
        cls,
        layout_id: str,
        device_id: str = None,
    ) -> Dict[str, Any]:
        """
        Get complete layout configuration including layers and content.

        This method returns a complete layout structure suitable for
        rendering on a device, including all layers and their content
        assignments for the specified device.

        Args:
            layout_id: The UUID of the layout
            device_id: Optional device ID to include content assignments

        Returns:
            Dictionary with complete layout configuration

        Raises:
            ValueError: If layout not found
        """
        layout = cls.get_layout_or_404(layout_id)

        config = layout.to_dict(include_layers=True)

        if device_id:
            # Add content assignments for each layer
            for layer_dict in config.get('layers', []):
                layer_id = layer_dict['id']

                # Get content assignment
                content = LayerContent.get_for_device_layer(device_id, layer_id)
                layer_dict['content'] = content.to_dict() if content else None

                # Get playlist assignments
                playlist_assignments = LayerPlaylistAssignment.get_for_device_layer(
                    device_id, layer_id
                )
                layer_dict['playlists'] = [a.to_dict_with_relations() for a in playlist_assignments]

        return config

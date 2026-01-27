/**
 * Skillz Media CMS - Layout Designer
 *
 * Main canvas editor JavaScript for the visual layout designer.
 * Provides:
 * - Canvas initialization with Fabric.js
 * - Drawing tool for creating new layers
 * - Selection tool for selecting, moving, and resizing layers
 * - Zoom controls (25%-200% and fit-to-window)
 * - API integration for saving layer positions
 * - Keyboard shortcuts
 */

(function(window) {
    'use strict';

    // =========================================================================
    // Constants
    // =========================================================================

    /** Tool types */
    const TOOLS = {
        SELECT: 'select',
        DRAW: 'draw'
    };

    /** Zoom levels */
    const ZOOM_LEVELS = [0.25, 0.50, 0.75, 1.00, 1.50, 2.00];

    /** Default new layer configuration */
    const DEFAULT_LAYER = {
        name: 'New Layer',
        width: 400,
        height: 300,
        opacity: 1.0,
        backgroundColor: 'transparent',
        borderWidth: 0,
        borderColor: '#333333',
        borderRadius: 0,
        fitMode: 'cover',
        zIndex: 0
    };

    /** Minimum dimensions for drawn layers */
    const MIN_DRAW_SIZE = 20;

    /** Debounce delay for API updates (ms) */
    const API_DEBOUNCE_DELAY = 500;

    /** Auto-save delay after modifications (ms) */
    const AUTOSAVE_DELAY = 1000;

    // =========================================================================
    // LayoutDesigner Class
    // =========================================================================

    /**
     * LayoutDesigner manages the canvas editor interface
     * @class
     */
    class LayoutDesigner {
        /**
         * Create a LayoutDesigner instance
         * @param {Object} layoutData - Initial layout data from server
         * @param {Object} apiEndpoints - API endpoint URLs
         */
        constructor(layoutData, apiEndpoints) {
            this.layoutData = layoutData;
            this.apiEndpoints = apiEndpoints;
            this.layers = new Map();
            this.selectedLayerId = null;
            this.currentTool = TOOLS.SELECT;
            this.currentZoom = 1.0;
            this.isDirty = false;
            this.isDrawing = false;
            this.drawStartPoint = null;
            this.drawingRect = null;
            this.canvas = null;
            this.fabricExtensions = null;
            this.saveTimeout = null;
            this.layerCounter = 0;
            this.gridVisible = false;
            this.snapEnabled = false;

            this._init();
        }

        // =====================================================================
        // Initialization
        // =====================================================================

        /**
         * Initialize the layout designer
         * @private
         */
        _init() {
            this._initCanvas();
            this._initFabricExtensions();
            this._loadExistingLayers();
            this._bindToolbar();
            this._bindKeyboard();
            this._bindCanvasEvents();
            this._bindPanelEvents();
            this._updateLayerList();
            this._updateInfoBar();
            this._updateZoomButtonStates();
            this._setTool(TOOLS.SELECT);

            // Auto-fit canvas to available space on load
            // Use requestAnimationFrame to ensure DOM is fully rendered
            requestAnimationFrame(() => {
                this._zoomFit();

                // Ensure all layers are interactive after initial render
                this._configureLayerControls(true);
                this._enableLayerSelection(true);

                // Force update coordinates for all objects
                this.canvas.getObjects().forEach(obj => {
                    obj.setCoords();
                });
                this.canvas.renderAll();

                console.log('Canvas ready - layers:', this.layers.size);
            });

            // Re-fit when window is resized
            let resizeTimeout;
            window.addEventListener('resize', () => {
                clearTimeout(resizeTimeout);
                resizeTimeout = setTimeout(() => {
                    this._zoomFit();
                }, 150);
            });

            // Warn before leaving with unsaved changes
            window.addEventListener('beforeunload', (e) => {
                if (this.isDirty) {
                    e.preventDefault();
                    e.returnValue = '';
                }
            });

            console.log('Layout Designer initialized successfully');
        }

        /**
         * Initialize Fabric.js canvas
         * @private
         */
        _initCanvas() {
            const canvasEl = document.getElementById('layout-canvas');
            if (!canvasEl) {
                throw new Error('Canvas element not found');
            }

            // Create Fabric canvas with full interactivity
            this.canvas = new fabric.Canvas('layout-canvas', {
                width: this.layoutData.canvasWidth,
                height: this.layoutData.canvasHeight,
                backgroundColor: this._getCanvasBackground(),
                selection: true,
                preserveObjectStacking: true,
                stopContextMenu: true,
                fireRightClick: true,
                // Enable object interaction
                interactive: true,
                renderOnAddRemove: true,
                skipTargetFind: false,
                // Cursor styles
                hoverCursor: 'move',
                moveCursor: 'grabbing',
                defaultCursor: 'default',
                freeDrawingCursor: 'crosshair'
            });

            // Update wrapper dimensions
            const wrapper = document.getElementById('canvas-wrapper');
            if (wrapper) {
                wrapper.style.width = this.layoutData.canvasWidth + 'px';
                wrapper.style.height = this.layoutData.canvasHeight + 'px';
            }
        }

        /**
         * Get canvas background color/style
         * @returns {string} Background color
         * @private
         */
        _getCanvasBackground() {
            const bgType = this.layoutData.backgroundType;
            const bgColor = this.layoutData.backgroundColor;
            const bgOpacity = this.layoutData.backgroundOpacity;

            if (bgType === 'transparent' || bgColor === 'transparent') {
                return 'transparent';
            }

            // Apply opacity to background color
            if (bgOpacity < 1 && bgColor && bgColor !== 'transparent') {
                const rgb = FabricExtensions.utils.hexToRgb(bgColor);
                if (rgb) {
                    return FabricExtensions.utils.toRgba({ ...rgb, a: bgOpacity });
                }
            }

            return bgColor || '#000000';
        }

        /**
         * Initialize Fabric extensions for constraints
         * @private
         */
        _initFabricExtensions() {
            this.fabricExtensions = new FabricExtensions(this.canvas, {
                snapToGrid: false,
                gridSize: 10,
                enforceMinSize: true,
                enforceMaxSize: true,
                enforceIntegerCoords: true,
                canvasBounds: {
                    width: this.layoutData.canvasWidth,
                    height: this.layoutData.canvasHeight
                },
                onObjectModified: (obj, bounds) => this._handleObjectModified(obj, bounds),
                onObjectMoving: (obj, bounds) => this._handleObjectMoving(obj, bounds),
                onObjectScaling: (obj, bounds) => this._handleObjectScaling(obj, bounds)
            });
        }

        /**
         * Load existing layers from layout data
         * @private
         */
        _loadExistingLayers() {
            if (!this.layoutData.layers || !Array.isArray(this.layoutData.layers)) {
                return;
            }

            // Sort by z_index ascending so they render in correct order
            const sortedLayers = [...this.layoutData.layers].sort((a, b) => a.z_index - b.z_index);

            sortedLayers.forEach(layerData => {
                this._createLayerFromData(layerData);
            });

            // Track layer count for naming new layers (IDs are UUIDs not integers)
            this.layerCounter = this.layers.size;

            this.canvas.renderAll();
        }

        /**
         * Create a canvas layer from server data
         * @param {Object} data - Layer data from server
         * @private
         */
        _createLayerFromData(data) {
            const fill = this._getLayerFill(data);

            // Determine if this is a transparent overlay layer
            const bgType = data.background_type || 'none';
            const isTransparent = bgType === 'none' || bgType === 'transparent';

            const rect = this.fabricExtensions.createLayerRect({
                x: data.x || 0,
                y: data.y || 0,
                width: data.width || DEFAULT_LAYER.width,
                height: data.height || DEFAULT_LAYER.height,
                fill: fill,
                stroke: '#00D4AA',
                strokeWidth: 2,
                layerId: data.id,
                layerName: data.name,
                layerData: data
            });

            // Set dashed border for transparent overlay layers (visible in editor only)
            if (isTransparent) {
                rect.set('strokeDashArray', [5, 5]);
            }

            // Apply opacity
            rect.set('opacity', data.opacity !== undefined ? data.opacity : 1.0);

            // Apply visibility
            if (data.is_visible === false) {
                rect.set('visible', false);
                rect.set('selectable', false);
                rect.set('evented', false);
                rect.set('hasControls', false);
            }

            // Apply locked state
            if (data.is_locked) {
                rect.set('selectable', false);
                rect.set('evented', false);
                rect.set('hasControls', false);
                rect.set('lockMovementX', true);
                rect.set('lockMovementY', true);
                rect.set('lockScalingX', true);
                rect.set('lockScalingY', true);
            } else {
                // Ensure unlocked layers have full 8-point controls and are interactive
                rect.set('hasControls', true);
                rect.set('hasBorders', true);
                rect.set('selectable', true);
                rect.set('evented', true);
                rect.set('lockMovementX', false);
                rect.set('lockMovementY', false);
                rect.set('lockScalingX', false);
                rect.set('lockScalingY', false);
                rect.set('lockRotation', true);
                rect.set('hasRotatingPoint', false);
            }

            // Ensure coordinates are set for proper control rendering
            rect.setCoords();

            this.canvas.add(rect);
            this.layers.set(data.id, {
                fabricObject: rect,
                data: data
            });
        }

        /**
         * Get fill color for a layer
         * @param {Object} data - Layer data
         * @returns {string} Fill color
         * @private
         */
        _getLayerFill(data) {
            const bgType = data.background_type || 'none';
            const bgColor = data.background_color;
            const bgOpacity = data.background_opacity !== undefined ? data.background_opacity : 1.0;

            // True transparent for overlays (QR codes, weather widgets, etc.)
            if (bgType === 'none' || bgType === 'transparent') {
                return 'transparent';
            }

            // Solid color background
            if (bgType === 'solid' && bgColor) {
                // Apply background opacity
                if (bgOpacity < 1) {
                    const rgb = FabricExtensions.utils.hexToRgb(bgColor);
                    if (rgb) {
                        return FabricExtensions.utils.toRgba({ ...rgb, a: bgOpacity });
                    }
                }
                return bgColor;
            }

            return 'transparent';
        }

        // =====================================================================
        // Tool Management
        // =====================================================================

        /**
         * Set the current tool
         * @param {string} tool - Tool name (select or draw)
         * @private
         */
        _setTool(tool) {
            this.currentTool = tool;

            // Update toolbar button states
            const selectBtn = document.getElementById('tool-select');
            const drawBtn = document.getElementById('tool-draw');

            if (selectBtn) selectBtn.classList.toggle('active', tool === TOOLS.SELECT);
            if (drawBtn) drawBtn.classList.toggle('active', tool === TOOLS.DRAW);

            // Update canvas interaction mode
            if (tool === TOOLS.SELECT) {
                this.canvas.selection = true;
                this.canvas.defaultCursor = 'default';
                this.canvas.hoverCursor = 'move';
                this.canvas.moveCursor = 'move';
                this._enableLayerSelection(true);
                this._configureLayerControls(true);
            } else if (tool === TOOLS.DRAW) {
                this.canvas.selection = false;
                this.canvas.defaultCursor = 'crosshair';
                this.canvas.hoverCursor = 'crosshair';
                this._enableLayerSelection(false);
                this._configureLayerControls(false);
                this.canvas.discardActiveObject();
                this.canvas.renderAll();
            }
        }

        /**
         * Configure layer controls visibility and behavior
         * @param {boolean} enabled - Whether controls should be enabled
         * @private
         */
        _configureLayerControls(enabled) {
            this.layers.forEach(layer => {
                const obj = layer.fabricObject;
                const data = layer.data;

                // Don't enable controls for hidden or locked layers
                if (!data.is_visible || data.is_locked) {
                    obj.set('hasControls', false);
                    obj.set('hasBorders', enabled);
                    return;
                }

                // Enable/disable 8-point resize controls
                obj.set('hasControls', enabled);
                obj.set('hasBorders', enabled);
                obj.set('lockMovementX', !enabled);
                obj.set('lockMovementY', !enabled);
                obj.set('lockScalingX', !enabled);
                obj.set('lockScalingY', !enabled);

                // Ensure coordinates are updated after control changes
                obj.setCoords();
            });
            this.canvas.renderAll();
        }

        /**
         * Enable or disable layer selection
         * @param {boolean} enabled - Whether selection is enabled
         * @private
         */
        _enableLayerSelection(enabled) {
            this.layers.forEach(layer => {
                const obj = layer.fabricObject;
                const data = layer.data;

                // Don't enable selection for hidden or locked layers
                if (!data.is_visible || data.is_locked) {
                    return;
                }

                obj.set('selectable', enabled);
                obj.set('evented', enabled);
            });
        }

        // =====================================================================
        // Drawing Tool
        // =====================================================================

        /**
         * Start drawing a new layer
         * @param {Object} pointer - Canvas pointer coordinates
         * @private
         */
        _startDrawing(pointer) {
            if (this.currentTool !== TOOLS.DRAW) return;

            this.isDrawing = true;
            this.drawStartPoint = {
                x: Math.round(pointer.x),
                y: Math.round(pointer.y)
            };

            // Create temporary drawing rectangle
            this.drawingRect = new fabric.Rect({
                left: this.drawStartPoint.x,
                top: this.drawStartPoint.y,
                width: 1,
                height: 1,
                fill: 'rgba(0, 212, 170, 0.2)',
                stroke: '#00D4AA',
                strokeWidth: 2,
                strokeDashArray: [5, 5],
                selectable: false,
                evented: false
            });

            this.canvas.add(this.drawingRect);
        }

        /**
         * Continue drawing (update rectangle size)
         * @param {Object} pointer - Canvas pointer coordinates
         * @private
         */
        _continueDrawing(pointer) {
            if (!this.isDrawing || !this.drawingRect) return;

            const x = Math.round(pointer.x);
            const y = Math.round(pointer.y);

            // Calculate dimensions (handle negative drag)
            const left = Math.min(this.drawStartPoint.x, x);
            const top = Math.min(this.drawStartPoint.y, y);
            const width = Math.abs(x - this.drawStartPoint.x);
            const height = Math.abs(y - this.drawStartPoint.y);

            this.drawingRect.set({
                left: left,
                top: top,
                width: Math.max(width, 1),
                height: Math.max(height, 1)
            });

            this.canvas.renderAll();

            // Update info bar with drawing dimensions
            this._updateInfoPosition(left, top);
            this._updateInfoSize(width, height);
        }

        /**
         * Finish drawing and create the layer
         * @private
         */
        async _finishDrawing() {
            if (!this.isDrawing || !this.drawingRect) return;

            this.isDrawing = false;

            // Get final dimensions
            const left = Math.round(this.drawingRect.left);
            const top = Math.round(this.drawingRect.top);
            const width = Math.round(this.drawingRect.width);
            const height = Math.round(this.drawingRect.height);

            // Remove temporary rectangle
            this.canvas.remove(this.drawingRect);
            this.drawingRect = null;

            // Only create layer if size is above minimum
            if (width >= MIN_DRAW_SIZE && height >= MIN_DRAW_SIZE) {
                await this._createNewLayer(left, top, width, height);
            }

            this.canvas.renderAll();

            // Switch back to SELECT tool after drawing so user can move/resize the layer
            this._setTool(TOOLS.SELECT);
        }

        /**
         * Cancel drawing operation
         * @private
         */
        _cancelDrawing() {
            if (!this.isDrawing) return;

            this.isDrawing = false;

            if (this.drawingRect) {
                this.canvas.remove(this.drawingRect);
                this.drawingRect = null;
            }

            this.canvas.renderAll();
        }

        // =====================================================================
        // Layer CRUD Operations
        // =====================================================================

        /**
         * Create a new layer via API
         * @param {number} x - X position
         * @param {number} y - Y position
         * @param {number} width - Width
         * @param {number} height - Height
         * @private
         */
        async _createNewLayer(x, y, width, height) {
            // Generate temporary name
            this.layerCounter++;
            const layerName = 'Layer ' + this.layerCounter;

            // Calculate z_index (one above current maximum)
            let maxZIndex = 0;
            this.layers.forEach(layer => {
                if (layer.data.z_index > maxZIndex) {
                    maxZIndex = layer.data.z_index;
                }
            });

            const layerData = {
                name: layerName,
                x: x,
                y: y,
                width: width,
                height: height,
                z_index: maxZIndex + 1,
                opacity: DEFAULT_LAYER.opacity,
                background_type: 'transparent',
                background_color: null,
                background_opacity: 1.0,
                is_visible: true,
                is_locked: false,
                fit_mode: DEFAULT_LAYER.fitMode
            };

            try {
                // Create layer via API
                const response = await CMS.api.post(this.apiEndpoints.layers, layerData);

                if (response && response.id) {
                    // Update layer data with server response
                    layerData.id = response.id;
                    this._createLayerFromData(layerData);

                    // Select the new layer
                    this._selectLayer(layerData.id);

                    this._updateLayerList();
                    this._showStatus('success', 'Layer created');

                    // Switch to select tool
                    this._setTool(TOOLS.SELECT);
                }
            } catch (error) {
                this._showStatus('error', 'Failed to create layer: ' + error.message);
            }
        }

        /**
         * Update a layer via API
         * @param {number|string} layerId - Layer ID
         * @param {Object} updates - Properties to update
         * @private
         */
        async _updateLayer(layerId, updates) {
            const layer = this.layers.get(layerId);
            if (!layer) return;

            try {
                const url = this.apiEndpoints.layers + '/' + layerId;
                await CMS.api.put(url, updates);

                // Update local data
                Object.assign(layer.data, updates);
                this.isDirty = false;

                this._showStatus('success', 'Layer updated');
            } catch (error) {
                this._showStatus('error', 'Failed to update layer: ' + error.message);
            }
        }

        /**
         * Delete a layer via API
         * @param {number|string} layerId - Layer ID
         * @private
         */
        async _deleteLayer(layerId) {
            const layer = this.layers.get(layerId);
            if (!layer) return;

            try {
                const url = this.apiEndpoints.layers + '/' + layerId;
                await CMS.api.delete(url);

                // Remove from canvas
                this.canvas.remove(layer.fabricObject);
                this.layers.delete(layerId);

                // Clear selection if this was selected
                if (this.selectedLayerId === layerId) {
                    this.selectedLayerId = null;
                    this._hideProperties();
                }

                this._updateLayerList();
                this.canvas.renderAll();

                this._showStatus('success', 'Layer deleted');
            } catch (error) {
                this._showStatus('error', 'Failed to delete layer: ' + error.message);
            }
        }

        /**
         * Schedule an update to the API (debounced)
         * @param {number|string} layerId - Layer ID
         * @param {Object} updates - Properties to update
         * @private
         */
        _scheduleUpdate(layerId, updates) {
            this.isDirty = true;

            if (this.saveTimeout) {
                clearTimeout(this.saveTimeout);
            }

            this.saveTimeout = setTimeout(() => {
                this._updateLayer(layerId, updates);
            }, AUTOSAVE_DELAY);
        }

        // =====================================================================
        // Selection Management
        // =====================================================================

        /**
         * Select a layer by ID
         * @param {number|string} layerId - Layer ID
         * @private
         */
        _selectLayer(layerId) {
            const layer = this.layers.get(layerId);
            if (!layer) return;

            this.selectedLayerId = layerId;

            // Ensure the object has controls enabled
            const obj = layer.fabricObject;
            if (!layer.data.is_locked && layer.data.is_visible !== false) {
                obj.set({
                    hasControls: true,
                    hasBorders: true,
                    selectable: true,
                    evented: true
                });
            }

            // Update coordinates for proper control positioning
            obj.setCoords();

            // Select on canvas
            this.canvas.setActiveObject(obj);
            this.canvas.renderAll();

            // Update UI
            this._updateLayerListSelection();
            this._showProperties(layer.data);
        }

        /**
         * Deselect all layers
         * @private
         */
        _deselectAll() {
            this.selectedLayerId = null;
            this.canvas.discardActiveObject();
            this.canvas.renderAll();

            this._updateLayerListSelection();
            this._hideProperties();
        }

        // =====================================================================
        // Canvas Event Handlers
        // =====================================================================

        /**
         * Bind canvas event handlers
         * @private
         */
        _bindCanvasEvents() {
            // Mouse down - start drawing or select
            this.canvas.on('mouse:down', (e) => {
                if (this.currentTool === TOOLS.DRAW && !e.target) {
                    const pointer = this.canvas.getPointer(e.e);
                    this._startDrawing(pointer);
                }
            });

            // Mouse move - continue drawing
            this.canvas.on('mouse:move', (e) => {
                const pointer = this.canvas.getPointer(e.e);

                if (this.isDrawing) {
                    this._continueDrawing(pointer);
                } else {
                    // Update position info on hover
                    this._updateInfoPosition(Math.round(pointer.x), Math.round(pointer.y));
                }
            });

            // Mouse up - finish drawing
            this.canvas.on('mouse:up', () => {
                if (this.isDrawing) {
                    this._finishDrawing();
                }
            });

            // Also handle mouse:out to finish drawing if mouse leaves canvas
            this.canvas.on('mouse:out', () => {
                if (this.isDrawing) {
                    this._finishDrawing();
                }
            });

            // Handle document-level mouseup in case mouse is released outside canvas
            document.addEventListener('mouseup', () => {
                if (this.isDrawing) {
                    this._finishDrawing();
                }
            });

            document.addEventListener('pointerup', () => {
                if (this.isDrawing) {
                    this._finishDrawing();
                }
            });

            // Selection changed
            this.canvas.on('selection:created', (e) => this._handleSelectionChanged(e));
            this.canvas.on('selection:updated', (e) => this._handleSelectionChanged(e));
            this.canvas.on('selection:cleared', () => this._handleSelectionCleared());

            // Object moving
            this.canvas.on('object:moving', (e) => {
                const obj = e.target;
                if (obj && obj.layerId !== undefined) {
                    const bounds = this.fabricExtensions.getObjectBounds(obj);
                    this._updateInfoPosition(bounds.x, bounds.y);
                    this._updateInfoSize(bounds.width, bounds.height);
                }
            });

            // Object scaling
            this.canvas.on('object:scaling', (e) => {
                const obj = e.target;
                if (obj && obj.layerId !== undefined) {
                    const bounds = this.fabricExtensions.getObjectBounds(obj);
                    this._updateInfoPosition(bounds.x, bounds.y);
                    this._updateInfoSize(bounds.width, bounds.height);
                }
            });
        }

        /**
         * Handle object modified event (from FabricExtensions)
         * @param {fabric.Object} obj - Modified object
         * @param {Object} bounds - New bounds
         * @private
         */
        _handleObjectModified(obj, bounds) {
            if (obj.layerId === undefined) return;

            const layer = this.layers.get(obj.layerId);
            if (!layer) return;

            // Update local data
            layer.data.x = bounds.x;
            layer.data.y = bounds.y;
            layer.data.width = bounds.width;
            layer.data.height = bounds.height;

            // Schedule API update
            this._scheduleUpdate(obj.layerId, {
                x: bounds.x,
                y: bounds.y,
                width: bounds.width,
                height: bounds.height
            });

            // Update properties panel
            if (this.selectedLayerId === obj.layerId) {
                this._showProperties(layer.data);
            }

            // Update layer list
            this._updateLayerList();
        }

        /**
         * Handle object moving event (from FabricExtensions)
         * @param {fabric.Object} obj - Moving object
         * @param {Object} bounds - Current bounds
         * @private
         */
        _handleObjectMoving(obj, bounds) {
            // Real-time update of properties panel
            if (this.selectedLayerId === obj.layerId) {
                this._updatePropertyInputs(bounds);
            }
        }

        /**
         * Handle object scaling event (from FabricExtensions)
         * @param {fabric.Object} obj - Scaling object
         * @param {Object} bounds - Current bounds
         * @private
         */
        _handleObjectScaling(obj, bounds) {
            // Real-time update of properties panel
            if (this.selectedLayerId === obj.layerId) {
                this._updatePropertyInputs(bounds);
            }
        }

        /**
         * Handle selection changed event
         * @param {Object} e - Fabric event
         * @private
         */
        _handleSelectionChanged(e) {
            const selected = e.selected;
            if (selected && selected.length === 1) {
                const obj = selected[0];
                if (obj.layerId !== undefined) {
                    this.selectedLayerId = obj.layerId;
                    const layer = this.layers.get(obj.layerId);
                    if (layer) {
                        this._updateLayerListSelection();
                        this._showProperties(layer.data);
                    }
                }
            }
        }

        /**
         * Handle selection cleared event
         * @private
         */
        _handleSelectionCleared() {
            this.selectedLayerId = null;
            this._updateLayerListSelection();
            this._hideProperties();
        }

        // =====================================================================
        // Toolbar Event Handlers
        // =====================================================================

        /**
         * Bind toolbar button event handlers
         * @private
         */
        _bindToolbar() {
            // Tool buttons
            const selectBtn = document.getElementById('tool-select');
            const drawBtn = document.getElementById('tool-draw');

            if (selectBtn) {
                selectBtn.addEventListener('click', () => this._setTool(TOOLS.SELECT));
            }
            if (drawBtn) {
                drawBtn.addEventListener('click', () => this._setTool(TOOLS.DRAW));
            }

            // Zoom controls
            const zoomIn = document.getElementById('zoom-in');
            const zoomOut = document.getElementById('zoom-out');
            const zoomLevel = document.getElementById('zoom-level');
            const zoomFit = document.getElementById('zoom-fit');

            if (zoomIn) {
                zoomIn.addEventListener('click', () => this._zoomIn());
            }
            if (zoomOut) {
                zoomOut.addEventListener('click', () => this._zoomOut());
            }
            if (zoomLevel) {
                zoomLevel.addEventListener('change', (e) => this._setZoom(parseFloat(e.target.value)));
            }
            if (zoomFit) {
                zoomFit.addEventListener('click', () => this._zoomFit());
            }

            // Grid controls
            const toggleGrid = document.getElementById('toggle-grid');
            const toggleSnap = document.getElementById('toggle-snap');
            const gridSize = document.getElementById('grid-size');

            if (toggleGrid) {
                toggleGrid.addEventListener('click', () => this._toggleGrid());
            }
            if (toggleSnap) {
                toggleSnap.addEventListener('click', () => this._toggleSnap());
            }
            if (gridSize) {
                gridSize.addEventListener('change', (e) => this._setGridSize(parseInt(e.target.value)));
            }

            // Layer controls
            const layerFront = document.getElementById('layer-front');
            const layerBack = document.getElementById('layer-back');
            const layerDelete = document.getElementById('layer-delete');
            const addLayer = document.getElementById('add-layer');

            if (layerFront) {
                layerFront.addEventListener('click', () => this._bringLayerForward());
            }
            if (layerBack) {
                layerBack.addEventListener('click', () => this._sendLayerBackward());
            }
            if (layerDelete) {
                layerDelete.addEventListener('click', () => this._deleteSelectedLayer());
            }
            if (addLayer) {
                addLayer.addEventListener('click', () => this._addLayerAtCenter());
            }

            // Save button
            const saveBtn = document.getElementById('save-layout');
            if (saveBtn) {
                saveBtn.addEventListener('click', () => this._saveLayout());
            }

            // Canvas preset selector
            const canvasPreset = document.getElementById('canvas-preset');
            if (canvasPreset) {
                canvasPreset.addEventListener('change', (e) => this._changeCanvasPreset(e.target.value));
            }
        }

        /**
         * Change canvas size based on preset
         * @param {string} preset - Preset value (e.g., "1920x1080")
         * @private
         */
        async _changeCanvasPreset(preset) {
            if (preset === 'custom') {
                // TODO: Show custom size dialog
                return;
            }

            const [width, height] = preset.split('x').map(Number);
            if (!width || !height) return;

            try {
                // Update via API
                await CMS.api.put(this.apiEndpoints.layout, {
                    canvas_width: width,
                    canvas_height: height
                });

                // Update local data
                this.layoutData.canvasWidth = width;
                this.layoutData.canvasHeight = height;

                // Resize canvas
                this._resizeCanvas(width, height);

                // Update dimensions display
                const dimsEl = document.getElementById('canvas-dimensions');
                if (dimsEl) {
                    dimsEl.textContent = `${width} x ${height}`;
                }

                this._showStatus('success', `Canvas resized to ${width}x${height}`);
            } catch (error) {
                this._showStatus('error', 'Failed to resize canvas: ' + error.message);
            }
        }

        /**
         * Resize the canvas
         * @param {number} width - New width
         * @param {number} height - New height
         * @private
         */
        _resizeCanvas(width, height) {
            // Update canvas dimensions
            this.canvas.setWidth(width);
            this.canvas.setHeight(height);

            // Update checkerboard background
            const checkerboard = document.getElementById('canvas-checkerboard');
            if (checkerboard) {
                checkerboard.style.width = width + 'px';
                checkerboard.style.height = height + 'px';
            }

            // Update screen label
            const screenLabel = document.getElementById('screen-label');
            if (screenLabel) {
                screenLabel.textContent = `Screen: ${width} x ${height}`;
            }

            // Update dimension labels
            const dimWidth = document.getElementById('dim-width');
            const dimHeight = document.getElementById('dim-height');
            if (dimWidth) dimWidth.textContent = `${width}px`;
            if (dimHeight) dimHeight.textContent = `${height}px`;

            // Re-render
            this.canvas.renderAll();

            // Fit to window if canvas is larger than viewport
            this._zoomFit();
        }

        /**
         * Bind keyboard shortcuts
         * @private
         */
        _bindKeyboard() {
            document.addEventListener('keydown', (e) => {
                // Don't handle shortcuts when typing in inputs
                if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') {
                    return;
                }

                switch (e.key.toLowerCase()) {
                    case 'v':
                        this._setTool(TOOLS.SELECT);
                        break;
                    case 'd':
                        this._setTool(TOOLS.DRAW);
                        break;
                    case 'g':
                        this._toggleGrid();
                        break;
                    case 's':
                        if (!e.ctrlKey && !e.metaKey) {
                            this._toggleSnap();
                        }
                        break;
                    case 'delete':
                    case 'backspace':
                        if (this.selectedLayerId) {
                            e.preventDefault();
                            this._deleteSelectedLayer();
                        }
                        break;
                    case 'escape':
                        if (this.isDrawing) {
                            this._cancelDrawing();
                        } else {
                            this._deselectAll();
                        }
                        break;
                    case '=':
                    case '+':
                        if (e.ctrlKey || e.metaKey) {
                            e.preventDefault();
                            this._zoomIn();
                        }
                        break;
                    case '-':
                        if (e.ctrlKey || e.metaKey) {
                            e.preventDefault();
                            this._zoomOut();
                        }
                        break;
                    case '0':
                        if (e.ctrlKey || e.metaKey) {
                            e.preventDefault();
                            this._setZoom(1.0);
                        }
                        break;
                    case 's':
                        if (e.ctrlKey || e.metaKey) {
                            e.preventDefault();
                            this._saveLayout();
                        }
                        break;
                    case 'arrowup':
                    case 'arrowdown':
                    case 'arrowleft':
                    case 'arrowright':
                        if (this.selectedLayerId && this.currentTool === TOOLS.SELECT) {
                            e.preventDefault();
                            this._moveLayerByKey(e.key.toLowerCase(), e.shiftKey ? 10 : 1);
                        }
                        break;
                }
            });
        }

        /**
         * Move selected layer by arrow key
         * @param {string} key - Arrow key name
         * @param {number} amount - Pixels to move
         * @private
         */
        _moveLayerByKey(key, amount) {
            const layer = this.layers.get(this.selectedLayerId);
            if (!layer || layer.data.is_locked) return;

            const obj = layer.fabricObject;
            let newLeft = obj.left;
            let newTop = obj.top;

            switch (key) {
                case 'arrowup':
                    newTop = Math.max(0, obj.top - amount);
                    break;
                case 'arrowdown':
                    newTop = Math.min(
                        this.layoutData.canvasHeight - (obj.height * obj.scaleY),
                        obj.top + amount
                    );
                    break;
                case 'arrowleft':
                    newLeft = Math.max(0, obj.left - amount);
                    break;
                case 'arrowright':
                    newLeft = Math.min(
                        this.layoutData.canvasWidth - (obj.width * obj.scaleX),
                        obj.left + amount
                    );
                    break;
            }

            // Apply new position
            obj.set({
                left: Math.round(newLeft),
                top: Math.round(newTop)
            });
            obj.setCoords();
            this.canvas.renderAll();

            // Update UI and schedule save
            const bounds = this.fabricExtensions.getObjectBounds(obj);
            this._updateInfoPosition(bounds.x, bounds.y);
            this._updatePropertyInputs(bounds);

            // Update local data and schedule API update
            layer.data.x = bounds.x;
            layer.data.y = bounds.y;
            this._scheduleUpdate(this.selectedLayerId, {
                x: bounds.x,
                y: bounds.y
            });
        }

        // =====================================================================
        // Zoom Controls
        // =====================================================================

        /**
         * Set zoom level
         * @param {number} level - Zoom level (0.25 to 2.0)
         * @private
         */
        _setZoom(level) {
            // Clamp zoom level to valid range (10% to 200%)
            level = Math.max(0.1, Math.min(2.0, level));
            this.currentZoom = level;

            // Calculate zoomed dimensions for display
            const zoomedWidth = this.layoutData.canvasWidth * level;
            const zoomedHeight = this.layoutData.canvasHeight * level;

            // Set canvas dimensions to zoomed size
            this.canvas.setDimensions({
                width: zoomedWidth,
                height: zoomedHeight
            });

            // Apply zoom using viewport transform
            // This scales the content while keeping mouse coordinates working
            this.canvas.setViewportTransform([level, 0, 0, level, 0, 0]);

            // Update wrapper dimensions
            const wrapper = document.getElementById('canvas-wrapper');
            if (wrapper) {
                wrapper.style.width = zoomedWidth + 'px';
                wrapper.style.height = zoomedHeight + 'px';
                wrapper.style.transform = 'none';
            }

            // Update checkerboard background size
            const checkerboard = document.getElementById('canvas-checkerboard');
            if (checkerboard) {
                checkerboard.style.width = zoomedWidth + 'px';
                checkerboard.style.height = zoomedHeight + 'px';
            }

            // Update dimension labels
            const dimWidth = document.getElementById('dim-width');
            const dimHeight = document.getElementById('dim-height');
            if (dimWidth) dimWidth.textContent = this.layoutData.canvasWidth + 'px';
            if (dimHeight) dimHeight.textContent = this.layoutData.canvasHeight + 'px';

            // Update all object coordinates for proper control rendering
            this.canvas.getObjects().forEach(obj => {
                obj.setCoords();
            });

            // Re-render
            this.canvas.renderAll();

            // Update info bar zoom display
            const infoZoom = document.getElementById('info-zoom');
            if (infoZoom) {
                infoZoom.textContent = Math.round(level * 100) + '%';
            }

            // Update zoom select dropdown
            const zoomLevel = document.getElementById('zoom-level');
            if (zoomLevel) {
                // Find the closest matching option value
                const optionValue = level.toFixed(2);
                const hasExactMatch = Array.from(zoomLevel.options).some(
                    opt => opt.value === optionValue
                );
                if (hasExactMatch) {
                    zoomLevel.value = optionValue;
                } else {
                    // For non-standard zoom levels, find closest
                    let closest = ZOOM_LEVELS[0];
                    let closestDiff = Math.abs(level - closest);
                    for (const z of ZOOM_LEVELS) {
                        const diff = Math.abs(level - z);
                        if (diff < closestDiff) {
                            closest = z;
                            closestDiff = diff;
                        }
                    }
                    zoomLevel.value = closest.toFixed(2);
                }
            }

            // Update zoom button states (disable at min/max)
            this._updateZoomButtonStates();

            // Update info bar
            this._updateInfoZoom();
        }

        /**
         * Update zoom button enabled/disabled states
         * @private
         */
        _updateZoomButtonStates() {
            const minZoom = ZOOM_LEVELS[0];
            const maxZoom = ZOOM_LEVELS[ZOOM_LEVELS.length - 1];

            const zoomOutBtn = document.getElementById('zoom-out');
            const zoomInBtn = document.getElementById('zoom-in');

            if (zoomOutBtn) {
                const atMin = this.currentZoom <= minZoom;
                zoomOutBtn.disabled = atMin;
                zoomOutBtn.style.opacity = atMin ? '0.5' : '1';
                zoomOutBtn.style.cursor = atMin ? 'not-allowed' : 'pointer';
            }

            if (zoomInBtn) {
                const atMax = this.currentZoom >= maxZoom;
                zoomInBtn.disabled = atMax;
                zoomInBtn.style.opacity = atMax ? '0.5' : '1';
                zoomInBtn.style.cursor = atMax ? 'not-allowed' : 'pointer';
            }
        }

        /**
         * Zoom in one step
         * @private
         */
        _zoomIn() {
            const maxZoom = ZOOM_LEVELS[ZOOM_LEVELS.length - 1];
            if (this.currentZoom >= maxZoom) return;

            // Find the next zoom level higher than current
            let nextZoom = maxZoom;
            for (const z of ZOOM_LEVELS) {
                if (z > this.currentZoom) {
                    nextZoom = z;
                    break;
                }
            }

            this._setZoom(nextZoom);
        }

        /**
         * Zoom out one step
         * @private
         */
        _zoomOut() {
            const minZoom = ZOOM_LEVELS[0];
            if (this.currentZoom <= minZoom) return;

            // Find the next zoom level lower than current
            let nextZoom = minZoom;
            for (let i = ZOOM_LEVELS.length - 1; i >= 0; i--) {
                if (ZOOM_LEVELS[i] < this.currentZoom) {
                    nextZoom = ZOOM_LEVELS[i];
                    break;
                }
            }

            this._setZoom(nextZoom);
        }

        /**
         * Fit canvas to window
         * @private
         */
        _zoomFit() {
            const container = document.getElementById('canvas-container');
            if (!container) return;

            // Calculate available space (accounting for padding, labels, and info bar)
            const padding = 120;
            const containerWidth = container.clientWidth - padding;
            const containerHeight = container.clientHeight - padding;

            if (containerWidth <= 0 || containerHeight <= 0) return;

            // Calculate scale to fit canvas in container while maintaining aspect ratio
            const scaleX = containerWidth / this.layoutData.canvasWidth;
            const scaleY = containerHeight / this.layoutData.canvasHeight;
            const scale = Math.min(scaleX, scaleY);

            // Clamp to reasonable range (10% to 200%)
            const clampedScale = Math.max(0.1, Math.min(2.0, scale));

            // Use exact scale for perfect fit
            this._setZoom(clampedScale);
        }

        // =====================================================================
        // Grid Controls
        // =====================================================================

        /**
         * Toggle grid visibility
         * @private
         */
        _toggleGrid() {
            this.gridVisible = !this.gridVisible;
            this.fabricExtensions.toggleGrid(this.gridVisible, 'rgba(255, 255, 255, 0.15)');

            // Update button state
            const btn = document.getElementById('toggle-grid');
            if (btn) {
                btn.classList.toggle('active', this.gridVisible);
            }

            this._showStatus('info', this.gridVisible ? 'Grid visible' : 'Grid hidden');
        }

        /**
         * Toggle snap to grid
         * @private
         */
        _toggleSnap() {
            this.snapEnabled = !this.snapEnabled;
            this.fabricExtensions.setSnapToGrid(this.snapEnabled);

            // Update button state
            const btn = document.getElementById('toggle-snap');
            if (btn) {
                btn.classList.toggle('active', this.snapEnabled);
            }

            this._showStatus('info', this.snapEnabled ? 'Snap to grid enabled' : 'Snap to grid disabled');
        }

        /**
         * Set grid size
         * @param {number} size - Grid size in pixels
         * @private
         */
        _setGridSize(size) {
            this.fabricExtensions.setSnapToGrid(this.snapEnabled, size);

            // Redraw grid if visible
            if (this.gridVisible) {
                this.fabricExtensions.toggleGrid(true, 'rgba(255, 255, 255, 0.15)');
            }

            this._showStatus('info', 'Grid size: ' + size + 'px');
        }

        // =====================================================================
        // Layer Controls
        // =====================================================================

        /**
         * Bring selected layer forward
         * @private
         */
        _bringLayerForward() {
            if (!this.selectedLayerId) return;
            this.fabricExtensions.bringForward();
            this._updateZIndexes();
        }

        /**
         * Send selected layer backward
         * @private
         */
        _sendLayerBackward() {
            if (!this.selectedLayerId) return;
            this.fabricExtensions.sendBackward();
            this._updateZIndexes();
        }

        /**
         * Update z-indexes after reordering
         * @private
         */
        async _updateZIndexes() {
            const objects = this.canvas.getObjects();
            const layerOrder = [];

            objects.forEach((obj, index) => {
                if (obj.layerId !== undefined) {
                    const layer = this.layers.get(obj.layerId);
                    if (layer) {
                        layer.data.z_index = index;
                        layerOrder.push({
                            id: obj.layerId,
                            z_index: index
                        });
                    }
                }
            });

            // Update via API
            try {
                await CMS.api.put(this.apiEndpoints.reorder, { layers: layerOrder });
                this._updateLayerList();
                this._showStatus('success', 'Layer order updated');
            } catch (error) {
                this._showStatus('error', 'Failed to update layer order');
            }
        }

        /**
         * Delete the currently selected layer
         * @private
         */
        async _deleteSelectedLayer() {
            if (!this.selectedLayerId) return;

            const confirmed = await CMS.util.confirm('Are you sure you want to delete this layer?');
            if (confirmed) {
                await this._deleteLayer(this.selectedLayerId);
            }
        }

        /**
         * Add a new layer at the center of the canvas
         * @private
         */
        async _addLayerAtCenter() {
            const x = Math.round((this.layoutData.canvasWidth - DEFAULT_LAYER.width) / 2);
            const y = Math.round((this.layoutData.canvasHeight - DEFAULT_LAYER.height) / 2);
            await this._createNewLayer(x, y, DEFAULT_LAYER.width, DEFAULT_LAYER.height);
        }

        // =====================================================================
        // Save Layout
        // =====================================================================

        /**
         * Save layout (manual save)
         * @private
         */
        async _saveLayout() {
            // If there's a pending save, execute it immediately
            if (this.saveTimeout) {
                clearTimeout(this.saveTimeout);
                this.saveTimeout = null;
            }

            try {
                // Save layout metadata
                await CMS.api.put(this.apiEndpoints.layout, {
                    name: this.layoutData.name,
                    canvas_width: this.layoutData.canvasWidth,
                    canvas_height: this.layoutData.canvasHeight,
                    background_type: this.layoutData.backgroundType,
                    background_color: this.layoutData.backgroundColor,
                    background_opacity: this.layoutData.backgroundOpacity
                });

                this.isDirty = false;
                this._showStatus('success', 'Layout saved');
            } catch (error) {
                this._showStatus('error', 'Failed to save layout: ' + error.message);
            }
        }

        // =====================================================================
        // Panel Event Handlers
        // =====================================================================

        /**
         * Bind panel event handlers
         * @private
         */
        _bindPanelEvents() {
            // Percentage-based position/size inputs (like OptiSigns)
            this._bindPercentageInput('prop-left-pct', 'left');
            this._bindPercentageInput('prop-top-pct', 'top');
            this._bindPercentageInput('prop-width-pct', 'width');
            this._bindPercentageInput('prop-height-pct', 'height');

            // Other property inputs
            this._bindPropertyInput('prop-name', 'name', String);
            this._bindPropertyInput('prop-opacity-value', 'opacity', (v) => parseInt(v) / 100);
            this._bindPropertyInput('prop-border-width', 'border_width', parseInt);
            this._bindPropertyInput('prop-border-color', 'border_color', String);
            this._bindPropertyInput('prop-border-radius', 'border_radius', parseInt);

            // Background type selector
            const bgType = document.getElementById('prop-background-type');
            const bgColorRow = document.getElementById('background-color-row');
            const bgColor = document.getElementById('prop-background');

            if (bgType) {
                bgType.addEventListener('change', (e) => {
                    const type = e.target.value;
                    // Show/hide color picker
                    if (bgColorRow) {
                        bgColorRow.style.display = type === 'solid' ? 'flex' : 'none';
                    }
                    // Update layer
                    this._updateLayerProperty('background_type', type);
                    if (type === 'none') {
                        this._updateLayerProperty('background_color', null);
                    }
                });
            }

            if (bgColor) {
                bgColor.addEventListener('change', (e) => {
                    this._updateLayerProperty('background_color', e.target.value);
                });
            }

            // Opacity slider
            const opacitySlider = document.getElementById('prop-opacity');
            const opacityValue = document.getElementById('prop-opacity-value');
            if (opacitySlider && opacityValue) {
                opacitySlider.addEventListener('input', (e) => {
                    const value = parseInt(e.target.value);
                    opacityValue.value = value;
                    this._updateLayerProperty('opacity', value / 100);
                });
            }

            // Fit mode select
            const fitMode = document.getElementById('prop-fit-mode');
            if (fitMode) {
                fitMode.addEventListener('change', (e) => {
                    this._updateLayerProperty('fit_mode', e.target.value);
                });
            }

            // Z-index controls
            const zUp = document.getElementById('prop-z-up');
            const zDown = document.getElementById('prop-z-down');
            if (zUp) zUp.addEventListener('click', () => this._bringLayerForward());
            if (zDown) zDown.addEventListener('click', () => this._sendLayerBackward());

            // Content mode tabs
            document.querySelectorAll('.content-mode-tab').forEach(tab => {
                tab.addEventListener('click', (e) => {
                    const mode = e.target.dataset.mode;
                    this._setContentMode(mode);
                });
            });

            // Layer type selector
            const layerType = document.getElementById('prop-layer-type');
            if (layerType) {
                layerType.addEventListener('change', (e) => {
                    this._setLayerType(e.target.value);
                });
            }

            // Content source selector
            const contentSource = document.getElementById('prop-content-source');
            if (contentSource) {
                contentSource.addEventListener('change', (e) => {
                    this._setContentSource(e.target.value);
                });
            }

            // Playlist selector
            const playlistId = document.getElementById('prop-playlist-id');
            if (playlistId) {
                playlistId.addEventListener('change', (e) => {
                    this._updateLayerProperty('playlist_id', e.target.value || null);
                });
            }

            // Content selector
            const contentId = document.getElementById('prop-content-id');
            if (contentId) {
                contentId.addEventListener('change', (e) => {
                    this._updateLayerProperty('content_id', e.target.value || null);
                });
            }

            // Primary layer toggle
            const isPrimary = document.getElementById('prop-is-primary');
            if (isPrimary) {
                isPrimary.addEventListener('change', (e) => {
                    this._setPrimaryLayer(e.target.checked);
                });
            }

            // Widget configuration inputs
            this._bindWidgetConfigInputs();
        }

        /**
         * Set content source for the selected layer
         * @param {string} source - Content source ('none', 'playlist', 'static', 'widget')
         * @private
         */
        _setContentSource(source) {
            // Show/hide appropriate selectors
            const playlistRow = document.getElementById('playlist-selector-row');
            const contentRow = document.getElementById('content-selector-row');

            if (playlistRow) playlistRow.style.display = source === 'playlist' ? 'flex' : 'none';
            if (contentRow) contentRow.style.display = source === 'static' ? 'flex' : 'none';

            // Update layer property
            this._updateLayerProperty('content_source', source);

            // Clear the non-relevant ID
            if (source !== 'playlist') {
                this._updateLayerProperty('playlist_id', null);
            }
            if (source !== 'static') {
                this._updateLayerProperty('content_id', null);
            }
        }

        /**
         * Set the selected layer as primary
         * @param {boolean} isPrimary - Whether this layer is primary
         * @private
         */
        async _setPrimaryLayer(isPrimary) {
            if (!this.selectedLayerId) return;

            try {
                await this._updateLayer(this.selectedLayerId, { is_primary: isPrimary });

                // Update local layer data
                const layer = this.layers.get(this.selectedLayerId);
                if (layer) {
                    layer.data.is_primary = isPrimary;
                }

                // If setting as primary, clear primary from other layers locally
                if (isPrimary) {
                    this.layers.forEach((otherLayer, id) => {
                        if (id !== this.selectedLayerId) {
                            otherLayer.data.is_primary = false;
                        }
                    });
                }

                // Update layer list to show primary indicator
                this._updateLayerList();

                this._showStatus('success', isPrimary ? 'Set as primary layer' : 'Removed primary status');
            } catch (error) {
                this._showStatus('error', 'Failed to update primary layer: ' + error.message);
                // Revert checkbox
                const checkbox = document.getElementById('prop-is-primary');
                if (checkbox) checkbox.checked = !isPrimary;
            }
        }

        /**
         * Bind widget configuration input handlers
         * @private
         */
        _bindWidgetConfigInputs() {
            // Weather widget
            this._bindWidgetInput('weather-location', 'weather', 'location');
            this._bindWidgetInput('weather-units', 'weather', 'units');
            this._bindWidgetInput('weather-display', 'weather', 'display');
            this._bindWidgetInput('weather-style', 'weather', 'style');

            // RSS Ticker widget
            this._bindWidgetInput('ticker-feed-url', 'ticker', 'feed_url');
            this._bindWidgetInput('ticker-speed', 'ticker', 'speed');
            this._bindWidgetInput('ticker-direction', 'ticker', 'direction');
            this._bindWidgetInput('ticker-max-items', 'ticker', 'max_items', parseInt);
            this._bindWidgetInput('ticker-separator', 'ticker', 'separator');
            this._bindWidgetInput('ticker-font-size', 'ticker', 'font_size', parseInt);
            this._bindWidgetInput('ticker-text-color', 'ticker', 'text_color');

            // Clock widget
            this._bindWidgetInput('clock-format', 'clock', 'format');
            this._bindWidgetInput('clock-show', 'clock', 'show');
            this._bindWidgetInput('clock-timezone', 'clock', 'timezone');
            this._bindWidgetInput('clock-font-size', 'clock', 'font_size', parseInt);
            this._bindWidgetInput('clock-text-color', 'clock', 'text_color');

            // Text widget
            this._bindWidgetInput('text-content', 'text', 'content');
            this._bindWidgetInput('text-font-size', 'text', 'font_size', parseInt);
            this._bindWidgetInput('text-font-family', 'text', 'font_family');
            this._bindWidgetInput('text-color', 'text', 'color');
            this._bindWidgetInput('text-align', 'text', 'align');

            // HTML widget
            this._bindWidgetInput('html-content', 'html', 'content');
            this._bindWidgetInput('html-refresh', 'html', 'refresh_interval', parseInt);
        }

        /**
         * Bind a widget configuration input
         * @param {string} elementId - Input element ID
         * @param {string} widgetType - Widget type name
         * @param {string} configKey - Configuration key
         * @param {Function} [parser] - Value parser function
         * @private
         */
        _bindWidgetInput(elementId, widgetType, configKey, parser) {
            const input = document.getElementById(elementId);
            if (!input) return;

            const eventType = input.tagName === 'SELECT' ? 'change' : 'change';
            input.addEventListener(eventType, (e) => {
                const value = parser ? parser(e.target.value) : e.target.value;
                this._updateWidgetConfig(widgetType, configKey, value);
            });
        }

        /**
         * Update widget configuration
         * @param {string} widgetType - Widget type
         * @param {string} key - Configuration key
         * @param {*} value - Configuration value
         * @private
         */
        _updateWidgetConfig(widgetType, key, value) {
            if (!this.selectedLayerId) return;

            const layer = this.layers.get(this.selectedLayerId);
            if (!layer) return;

            // Initialize content_config if needed
            if (!layer.data.content_config) {
                layer.data.content_config = {};
            }

            // Update the config
            layer.data.content_config[key] = value;

            // Schedule API update
            this._scheduleUpdate(this.selectedLayerId, {
                content_config: layer.data.content_config
            });
        }

        /**
         * Set layer type and show appropriate config panel
         * @param {string} type - Layer type
         * @private
         */
        _setLayerType(type) {
            if (!this.selectedLayerId) return;

            const layer = this.layers.get(this.selectedLayerId);
            if (!layer) return;

            // Update layer type
            layer.data.layer_type = type;

            // Hide all widget config panels
            document.querySelectorAll('.widget-config').forEach(panel => {
                panel.style.display = 'none';
            });

            // Show the appropriate config panel
            const configPanel = document.getElementById('config-' + type);
            if (configPanel) {
                configPanel.style.display = 'block';
            }

            // Update canvas layer appearance based on type
            this._updateLayerAppearanceForType(layer, type);

            // Schedule API update
            this._scheduleUpdate(this.selectedLayerId, { layer_type: type });
        }

        /**
         * Update layer visual appearance based on type
         * @param {Object} layer - Layer object
         * @param {string} type - Layer type
         * @private
         */
        _updateLayerAppearanceForType(layer, type) {
            const obj = layer.fabricObject;
            const typeColors = {
                content: '#00D4AA',
                weather: '#FFB800',
                ticker: '#FF6B6B',
                clock: '#A78BFA',
                text: '#60A5FA',
                html: '#F472B6'
            };

            const color = typeColors[type] || '#00D4AA';
            obj.set('stroke', color);
            this.canvas.renderAll();
        }

        /**
         * Bind a property input element
         * @param {string} elementId - Input element ID
         * @param {string} propertyName - Property name in layer data
         * @param {Function} parser - Value parser function
         * @private
         */
        _bindPropertyInput(elementId, propertyName, parser) {
            const input = document.getElementById(elementId);
            if (!input) return;

            input.addEventListener('change', (e) => {
                const value = parser(e.target.value);
                this._updateLayerProperty(propertyName, value);
            });
        }

        /**
         * Bind a percentage-based input for position/size
         * @param {string} elementId - Input element ID
         * @param {string} dimension - 'left', 'top', 'width', or 'height'
         * @private
         */
        _bindPercentageInput(elementId, dimension) {
            const input = document.getElementById(elementId);
            if (!input) return;

            // Update on change and input (for real-time updates)
            const updateFromInput = () => {
                if (!this.selectedLayerId) return;

                const layer = this.layers.get(this.selectedLayerId);
                if (!layer) return;

                const pct = parseFloat(input.value) || 0;
                const canvasWidth = this.layoutData.canvasWidth;
                const canvasHeight = this.layoutData.canvasHeight;

                // Convert percentage to pixels
                let pixelValue;
                switch (dimension) {
                    case 'left':
                        pixelValue = Math.round((pct / 100) * canvasWidth);
                        layer.data.x = pixelValue;
                        layer.fabricObject.set('left', pixelValue);
                        break;
                    case 'top':
                        pixelValue = Math.round((pct / 100) * canvasHeight);
                        layer.data.y = pixelValue;
                        layer.fabricObject.set('top', pixelValue);
                        break;
                    case 'width':
                        pixelValue = Math.max(20, Math.round((pct / 100) * canvasWidth));
                        layer.data.width = pixelValue;
                        layer.fabricObject.set('width', pixelValue);
                        layer.fabricObject.set('scaleX', 1);
                        break;
                    case 'height':
                        pixelValue = Math.max(20, Math.round((pct / 100) * canvasHeight));
                        layer.data.height = pixelValue;
                        layer.fabricObject.set('height', pixelValue);
                        layer.fabricObject.set('scaleY', 1);
                        break;
                }

                layer.fabricObject.setCoords();
                this.canvas.renderAll();
                this._updatePixelsInfo(layer.data);
                this._updateLayerList();

                // Schedule API update
                this._scheduleUpdate(this.selectedLayerId, {
                    x: layer.data.x,
                    y: layer.data.y,
                    width: layer.data.width,
                    height: layer.data.height
                });
            };

            input.addEventListener('change', updateFromInput);
            input.addEventListener('input', updateFromInput);
        }

        /**
         * Update the pixels info display
         * @param {Object} data - Layer data
         * @private
         */
        _updatePixelsInfo(data) {
            const info = document.getElementById('prop-pixels-info');
            if (info) {
                const x = data.x || 0;
                const y = data.y || 0;
                const w = data.width || 100;
                const h = data.height || 100;
                info.textContent = `${x}, ${y} - ${w} x ${h}`;
            }
        }

        /**
         * Update a layer property
         * @param {string} propertyName - Property name
         * @param {*} value - New value
         * @private
         */
        _updateLayerProperty(propertyName, value) {
            if (!this.selectedLayerId) return;

            const layer = this.layers.get(this.selectedLayerId);
            if (!layer) return;

            // Update local data
            layer.data[propertyName] = value;

            // Update canvas object for visual properties
            const obj = layer.fabricObject;
            switch (propertyName) {
                case 'x':
                    obj.set('left', value);
                    obj.setCoords();
                    break;
                case 'y':
                    obj.set('top', value);
                    obj.setCoords();
                    break;
                case 'width':
                    obj.set('width', Math.max(value, 20));
                    obj.set('scaleX', 1);
                    obj.setCoords();
                    break;
                case 'height':
                    obj.set('height', Math.max(value, 20));
                    obj.set('scaleY', 1);
                    obj.setCoords();
                    break;
                case 'opacity':
                    obj.set('opacity', value);
                    break;
                case 'background_type':
                    if (value === 'none') {
                        // True transparent - just show a subtle dashed border for editing
                        obj.set('fill', 'transparent');
                        obj.set('strokeDashArray', [5, 5]);
                    } else {
                        obj.set('strokeDashArray', null);
                        // Use the current background_color or default
                        const bgColor = layer.data.background_color || '#000000';
                        obj.set('fill', bgColor);
                    }
                    break;
                case 'background_color':
                    if (layer.data.background_type === 'solid') {
                        obj.set('fill', value || '#000000');
                    }
                    break;
            }

            this.canvas.renderAll();
            this._updateLayerList();

            // Schedule API update
            this._scheduleUpdate(this.selectedLayerId, { [propertyName]: value });
        }

        /**
         * Set content mode (static or playlist)
         * @param {string} mode - Content mode
         * @private
         */
        _setContentMode(mode) {
            document.querySelectorAll('.content-mode-tab').forEach(tab => {
                tab.classList.toggle('active', tab.dataset.mode === mode);
            });

            const staticContent = document.getElementById('content-static');
            const playlistContent = document.getElementById('content-playlist');

            if (staticContent) staticContent.style.display = mode === 'static' ? 'block' : 'none';
            if (playlistContent) playlistContent.style.display = mode === 'playlist' ? 'block' : 'none';
        }

        // =====================================================================
        // UI Updates
        // =====================================================================

        /**
         * Update the layer list in the left panel
         * @private
         */
        _updateLayerList() {
            const listEl = document.getElementById('layer-list');
            const emptyEl = document.getElementById('layers-empty');
            if (!listEl) return;

            // Sort layers by z_index descending (top to bottom in list)
            const sortedLayers = Array.from(this.layers.values())
                .sort((a, b) => b.data.z_index - a.data.z_index);

            // Show/hide empty state
            if (emptyEl) {
                emptyEl.style.display = sortedLayers.length === 0 ? 'block' : 'none';
            }

            // Build layer list HTML
            listEl.innerHTML = sortedLayers.map(layer => {
                const data = layer.data;
                const isSelected = this.selectedLayerId === data.id;
                const isVisible = data.is_visible !== false;
                const isLocked = data.is_locked === true;

                return `
                    <div class="layer-item ${isSelected ? 'selected' : ''}" data-layer-id="${data.id}">
                        <span class="layer-visibility ${isVisible ? 'visible' : ''}"
                              data-action="toggle-visibility" title="${isVisible ? 'Hide' : 'Show'}">
                            ${isVisible ? '&#128065;' : '&#128064;'}
                        </span>
                        <div class="layer-preview" style="background: ${data.background_color || '#1a1a24'};"></div>
                        <div class="layer-info">
                            <div class="layer-name">${this._escapeHtml(data.name || 'Unnamed')}</div>
                            <div class="layer-dims">${data.width} x ${data.height}</div>
                        </div>
                        <span class="layer-lock ${isLocked ? 'locked' : ''}"
                              data-action="toggle-lock" title="${isLocked ? 'Unlock' : 'Lock'}">
                            ${isLocked ? '&#128274;' : '&#128275;'}
                        </span>
                    </div>
                `;
            }).join('');

            // Bind click handlers
            listEl.querySelectorAll('.layer-item').forEach(item => {
                const layerId = item.dataset.layerId;

                // Click to select
                item.addEventListener('click', (e) => {
                    if (e.target.closest('[data-action]')) return;
                    this._selectLayer(layerId);
                });

                // Visibility toggle
                const visBtn = item.querySelector('[data-action="toggle-visibility"]');
                if (visBtn) {
                    visBtn.addEventListener('click', () => this._toggleLayerVisibility(layerId));
                }

                // Lock toggle
                const lockBtn = item.querySelector('[data-action="toggle-lock"]');
                if (lockBtn) {
                    lockBtn.addEventListener('click', () => this._toggleLayerLock(layerId));
                }
            });
        }

        /**
         * Update layer list selection highlighting
         * @private
         */
        _updateLayerListSelection() {
            const listEl = document.getElementById('layer-list');
            if (!listEl) return;

            listEl.querySelectorAll('.layer-item').forEach(item => {
                const layerId = item.dataset.layerId;
                item.classList.toggle('selected', layerId === this.selectedLayerId);
            });
        }

        /**
         * Toggle layer visibility
         * @param {number|string} layerId - Layer ID
         * @private
         */
        _toggleLayerVisibility(layerId) {
            const layer = this.layers.get(layerId);
            if (!layer) return;

            const isVisible = layer.data.is_visible !== false;
            const newVisible = !isVisible;

            layer.data.is_visible = newVisible;
            layer.fabricObject.set('visible', newVisible);
            layer.fabricObject.set('selectable', newVisible && !layer.data.is_locked);
            layer.fabricObject.set('evented', newVisible && !layer.data.is_locked);

            this.canvas.renderAll();
            this._updateLayerList();
            this._scheduleUpdate(layerId, { is_visible: newVisible });
        }

        /**
         * Toggle layer lock state
         * @param {number|string} layerId - Layer ID
         * @private
         */
        _toggleLayerLock(layerId) {
            const layer = this.layers.get(layerId);
            if (!layer) return;

            const isLocked = layer.data.is_locked === true;
            const newLocked = !isLocked;

            layer.data.is_locked = newLocked;
            layer.fabricObject.set('selectable', !newLocked && layer.data.is_visible !== false);
            layer.fabricObject.set('evented', !newLocked && layer.data.is_visible !== false);
            layer.fabricObject.set('hasControls', !newLocked);

            if (newLocked && this.selectedLayerId === layerId) {
                this._deselectAll();
            }

            this.canvas.renderAll();
            this._updateLayerList();
            this._scheduleUpdate(layerId, { is_locked: newLocked });
        }

        /**
         * Show properties panel for a layer
         * @param {Object} data - Layer data
         * @private
         */
        _showProperties(data) {
            const noSelection = document.getElementById('no-selection');
            const layerProps = document.getElementById('layer-properties');

            if (noSelection) noSelection.style.display = 'none';
            if (layerProps) layerProps.style.display = 'block';

            // Calculate percentage values from pixel values
            const canvasWidth = this.layoutData.canvasWidth;
            const canvasHeight = this.layoutData.canvasHeight;
            const x = data.x || 0;
            const y = data.y || 0;
            const w = data.width || 400;
            const h = data.height || 300;

            const leftPct = ((x / canvasWidth) * 100).toFixed(1);
            const topPct = ((y / canvasHeight) * 100).toFixed(1);
            const widthPct = ((w / canvasWidth) * 100).toFixed(1);
            const heightPct = ((h / canvasHeight) * 100).toFixed(1);

            // Update percentage inputs
            this._setPropertyValue('prop-left-pct', leftPct);
            this._setPropertyValue('prop-top-pct', topPct);
            this._setPropertyValue('prop-width-pct', widthPct);
            this._setPropertyValue('prop-height-pct', heightPct);

            // Update pixels info
            this._updatePixelsInfo(data);

            this._setPropertyValue('prop-name', data.name || '');
            this._setPropertyValue('prop-opacity', Math.round((data.opacity || 1) * 100));
            this._setPropertyValue('prop-opacity-value', Math.round((data.opacity || 1) * 100));

            // Background type and color
            const bgType = data.background_type || (data.background_color ? 'solid' : 'none');
            this._setPropertyValue('prop-background-type', bgType);
            this._setPropertyValue('prop-background', data.background_color || '#000000');

            // Show/hide color picker based on type
            const bgColorRow = document.getElementById('background-color-row');
            if (bgColorRow) {
                bgColorRow.style.display = bgType === 'solid' ? 'flex' : 'none';
            }

            this._setPropertyValue('prop-border-width', data.border_width || 0);
            this._setPropertyValue('prop-border-color', data.border_color || '#333333');
            this._setPropertyValue('prop-border-radius', data.border_radius || 0);
            this._setPropertyValue('prop-z-index', data.z_index || 0);
            this._setPropertyValue('prop-fit-mode', data.fit_mode || 'cover');

            // Set layer type and show appropriate config panel
            const layerType = data.layer_type || 'content';
            this._setPropertyValue('prop-layer-type', layerType);

            // Hide all widget config panels
            document.querySelectorAll('.widget-config').forEach(panel => {
                panel.style.display = 'none';
            });

            // Show the appropriate config panel
            const configPanel = document.getElementById('config-' + layerType);
            if (configPanel) {
                configPanel.style.display = 'block';
            }

            // Populate widget configuration values
            this._populateWidgetConfig(layerType, data.content_config || {});

            // Set content source and show appropriate selectors
            const contentSource = data.content_source || 'none';
            this._setPropertyValue('prop-content-source', contentSource);

            const playlistRow = document.getElementById('playlist-selector-row');
            const contentRow = document.getElementById('content-selector-row');

            if (playlistRow) playlistRow.style.display = contentSource === 'playlist' ? 'flex' : 'none';
            if (contentRow) contentRow.style.display = contentSource === 'static' ? 'flex' : 'none';

            // Set playlist and content selections
            this._setPropertyValue('prop-playlist-id', data.playlist_id || '');
            this._setPropertyValue('prop-content-id', data.content_id || '');

            // Set primary layer toggle
            const isPrimaryCheckbox = document.getElementById('prop-is-primary');
            if (isPrimaryCheckbox) {
                isPrimaryCheckbox.checked = data.is_primary === true;
            }
        }

        /**
         * Populate widget configuration inputs with stored values
         * @param {string} type - Widget type
         * @param {Object} config - Configuration values
         * @private
         */
        _populateWidgetConfig(type, config) {
            switch (type) {
                case 'weather':
                    this._setPropertyValue('weather-location', config.location || '');
                    this._setPropertyValue('weather-units', config.units || 'imperial');
                    this._setPropertyValue('weather-display', config.display || 'current');
                    this._setPropertyValue('weather-style', config.style || 'minimal');
                    break;

                case 'ticker':
                    this._setPropertyValue('ticker-feed-url', config.feed_url || '');
                    this._setPropertyValue('ticker-speed', config.speed || 'medium');
                    this._setPropertyValue('ticker-direction', config.direction || 'left');
                    this._setPropertyValue('ticker-max-items', config.max_items || 10);
                    this._setPropertyValue('ticker-separator', config.separator || ' • ');
                    this._setPropertyValue('ticker-font-size', config.font_size || 24);
                    this._setPropertyValue('ticker-text-color', config.text_color || '#FFFFFF');
                    break;

                case 'clock':
                    this._setPropertyValue('clock-format', config.format || '12h');
                    this._setPropertyValue('clock-show', config.show || 'both');
                    this._setPropertyValue('clock-timezone', config.timezone || 'local');
                    this._setPropertyValue('clock-font-size', config.font_size || 48);
                    this._setPropertyValue('clock-text-color', config.text_color || '#FFFFFF');
                    break;

                case 'text':
                    this._setPropertyValue('text-content', config.content || '');
                    this._setPropertyValue('text-font-size', config.font_size || 32);
                    this._setPropertyValue('text-font-family', config.font_family || 'Arial, sans-serif');
                    this._setPropertyValue('text-color', config.color || '#FFFFFF');
                    this._setPropertyValue('text-align', config.align || 'left');
                    break;

                case 'html':
                    this._setPropertyValue('html-content', config.content || '');
                    this._setPropertyValue('html-refresh', config.refresh_interval || 0);
                    break;
            }
        }

        /**
         * Hide properties panel
         * @private
         */
        _hideProperties() {
            const noSelection = document.getElementById('no-selection');
            const layerProps = document.getElementById('layer-properties');

            if (noSelection) noSelection.style.display = 'block';
            if (layerProps) layerProps.style.display = 'none';
        }

        /**
         * Update property inputs during drag/resize (percentage-based)
         * @param {Object} bounds - Current bounds in pixels
         * @private
         */
        _updatePropertyInputs(bounds) {
            const canvasWidth = this.layoutData.canvasWidth;
            const canvasHeight = this.layoutData.canvasHeight;

            // Calculate percentages
            const leftPct = ((bounds.x / canvasWidth) * 100).toFixed(1);
            const topPct = ((bounds.y / canvasHeight) * 100).toFixed(1);
            const widthPct = ((bounds.width / canvasWidth) * 100).toFixed(1);
            const heightPct = ((bounds.height / canvasHeight) * 100).toFixed(1);

            // Update percentage inputs
            this._setPropertyValue('prop-left-pct', leftPct);
            this._setPropertyValue('prop-top-pct', topPct);
            this._setPropertyValue('prop-width-pct', widthPct);
            this._setPropertyValue('prop-height-pct', heightPct);

            // Update pixels info
            const info = document.getElementById('prop-pixels-info');
            if (info) {
                info.textContent = `${bounds.x}, ${bounds.y} - ${bounds.width} x ${bounds.height}`;
            }
        }

        /**
         * Set a property input value
         * @param {string} elementId - Input element ID
         * @param {*} value - Value to set
         * @private
         */
        _setPropertyValue(elementId, value) {
            const el = document.getElementById(elementId);
            if (el) {
                el.value = value;
            }
        }

        /**
         * Update info bar position display
         * @param {number} x - X coordinate
         * @param {number} y - Y coordinate
         * @private
         */
        _updateInfoPosition(x, y) {
            const el = document.getElementById('info-position');
            if (el) {
                el.textContent = x + ', ' + y;
            }
        }

        /**
         * Update info bar size display
         * @param {number} width - Width
         * @param {number} height - Height
         * @private
         */
        _updateInfoSize(width, height) {
            const el = document.getElementById('info-size');
            if (el) {
                el.textContent = width + ' x ' + height;
            }
        }

        /**
         * Update info bar zoom display
         * @private
         */
        _updateInfoZoom() {
            const el = document.getElementById('info-zoom');
            if (el) {
                el.textContent = Math.round(this.currentZoom * 100) + '%';
            }
        }

        /**
         * Update all info bar values
         * @private
         */
        _updateInfoBar() {
            this._updateInfoPosition('--', '--');
            this._updateInfoSize('--', '--');
            this._updateInfoZoom();
        }

        /**
         * Show a status message
         * @param {string} type - Status type (success, error, warning)
         * @param {string} message - Message to display
         * @private
         */
        _showStatus(type, message) {
            if (window.CMS && CMS.status && CMS.status.toast) {
                CMS.status.toast(message, type);
            }
        }

        /**
         * Escape HTML special characters
         * @param {string} str - String to escape
         * @returns {string} Escaped string
         * @private
         */
        _escapeHtml(str) {
            const div = document.createElement('div');
            div.textContent = str;
            return div.innerHTML;
        }

        // =====================================================================
        // Public API
        // =====================================================================

        /**
         * Get current tool
         * @returns {string} Current tool name
         */
        getCurrentTool() {
            return this.currentTool;
        }

        /**
         * Get current zoom level
         * @returns {number} Zoom level
         */
        getZoom() {
            return this.currentZoom;
        }

        /**
         * Set zoom level
         * @param {number} level - Zoom level (0.25 to 2.0)
         */
        setZoom(level) {
            this._setZoom(level);
        }

        /**
         * Zoom in one step
         */
        zoomIn() {
            this._zoomIn();
        }

        /**
         * Zoom out one step
         */
        zoomOut() {
            this._zoomOut();
        }

        /**
         * Fit canvas to window
         */
        zoomFit() {
            this._zoomFit();
        }

        /**
         * Get selected layer ID
         * @returns {number|string|null} Selected layer ID
         */
        getSelectedLayerId() {
            return this.selectedLayerId;
        }

        /**
         * Get layer by ID
         * @param {number|string} layerId - Layer ID
         * @returns {Object|null} Layer data
         */
        getLayer(layerId) {
            const layer = this.layers.get(layerId);
            return layer ? layer.data : null;
        }

        /**
         * Get all layers
         * @returns {Array} Array of layer data objects
         */
        getAllLayers() {
            return Array.from(this.layers.values()).map(l => l.data);
        }

        /**
         * Check if there are unsaved changes
         * @returns {boolean} True if there are unsaved changes
         */
        hasUnsavedChanges() {
            return this.isDirty;
        }

        /**
         * Get the Fabric.js canvas instance
         * @returns {fabric.Canvas} Canvas instance
         */
        getCanvas() {
            return this.canvas;
        }

        /**
         * Get the FabricExtensions instance
         * @returns {FabricExtensions} Extensions instance
         */
        getExtensions() {
            return this.fabricExtensions;
        }
    }

    // =========================================================================
    // Auto-initialization
    // =========================================================================

    /**
     * Initialize layout designer when DOM is ready
     */
    function init() {
        console.log('Layout Designer: Checking initialization requirements...');

        // Check if we have layout data
        if (!window.LAYOUT_DATA || !window.API_ENDPOINTS) {
            console.error('Layout Designer: Missing LAYOUT_DATA or API_ENDPOINTS');
            return;
        }
        console.log('Layout Designer: Layout data found', window.LAYOUT_DATA);

        // Wait for dependencies
        if (typeof fabric === 'undefined') {
            console.error('Layout Designer: Fabric.js not loaded');
            return;
        }
        console.log('Layout Designer: Fabric.js loaded');

        if (typeof FabricExtensions === 'undefined') {
            console.error('Layout Designer: FabricExtensions not loaded');
            return;
        }
        console.log('Layout Designer: FabricExtensions loaded');

        // Check if CMS.api is available
        if (typeof CMS === 'undefined' || !CMS.api) {
            console.error('Layout Designer: CMS.api not available');
            return;
        }
        console.log('Layout Designer: CMS.api available');

        try {
            // Create designer instance
            window.layoutDesigner = new LayoutDesigner(
                window.LAYOUT_DATA,
                window.API_ENDPOINTS
            );
            console.log('Layout Designer: Instance created successfully');
        } catch (error) {
            console.error('Layout Designer: Failed to initialize', error);
        }
    }

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        // Small delay to ensure all scripts are loaded
        setTimeout(init, 100);
    }

    // =========================================================================
    // Export to Global Namespace
    // =========================================================================

    window.LayoutDesigner = LayoutDesigner;

    // Export constants
    window.LayoutDesigner.TOOLS = TOOLS;
    window.LayoutDesigner.ZOOM_LEVELS = ZOOM_LEVELS;

})(window);

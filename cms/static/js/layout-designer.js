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

            // Warn before leaving with unsaved changes
            window.addEventListener('beforeunload', (e) => {
                if (this.isDirty) {
                    e.preventDefault();
                    e.returnValue = '';
                }
            });
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

            // Create Fabric canvas
            this.canvas = new fabric.Canvas('layout-canvas', {
                width: this.layoutData.canvasWidth,
                height: this.layoutData.canvasHeight,
                backgroundColor: this._getCanvasBackground(),
                selection: true,
                preserveObjectStacking: true,
                stopContextMenu: true,
                fireRightClick: true
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
                // Ensure unlocked layers have full 8-point controls
                rect.set('hasControls', true);
                rect.set('hasBorders', true);
                rect.set('lockMovementX', false);
                rect.set('lockMovementY', false);
                rect.set('lockScalingX', false);
                rect.set('lockScalingY', false);
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
            const bgType = data.background_type || 'transparent';
            const bgColor = data.background_color;
            const bgOpacity = data.background_opacity !== undefined ? data.background_opacity : 1.0;

            if (bgType === 'transparent' || !bgColor || bgColor === 'transparent') {
                return 'rgba(0, 212, 170, 0.1)'; // Subtle indicator for transparent layers
            }

            // Apply background opacity
            if (bgOpacity < 1) {
                const rgb = FabricExtensions.utils.hexToRgb(bgColor);
                if (rgb) {
                    return FabricExtensions.utils.toRgba({ ...rgb, a: bgOpacity });
                }
            }

            return bgColor;
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

            // Select on canvas
            this.canvas.setActiveObject(layer.fabricObject);
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
            // Clamp zoom level to valid range
            const minZoom = ZOOM_LEVELS[0];
            const maxZoom = ZOOM_LEVELS[ZOOM_LEVELS.length - 1];
            level = Math.max(minZoom, Math.min(maxZoom, level));
            this.currentZoom = level;

            // Apply zoom via CSS transform on the canvas wrapper
            const wrapper = document.getElementById('canvas-wrapper');
            if (wrapper) {
                wrapper.style.transform = 'scale(' + level + ')';
                wrapper.style.transformOrigin = 'center center';
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

            // Calculate available space (accounting for padding)
            const padding = 80;
            const containerWidth = container.clientWidth - padding;
            const containerHeight = container.clientHeight - padding;

            if (containerWidth <= 0 || containerHeight <= 0) return;

            // Calculate scale to fit canvas in container
            const scaleX = containerWidth / this.layoutData.canvasWidth;
            const scaleY = containerHeight / this.layoutData.canvasHeight;
            const scale = Math.min(scaleX, scaleY);

            // Clamp to valid zoom range (allow fitting smaller canvases to larger too)
            const minZoom = ZOOM_LEVELS[0];
            const maxZoom = ZOOM_LEVELS[ZOOM_LEVELS.length - 1];
            const clampedScale = Math.max(minZoom, Math.min(maxZoom, scale));

            // Find the closest standard zoom level that fits
            let fitZoom = minZoom;
            for (const z of ZOOM_LEVELS) {
                if (z <= clampedScale) {
                    fitZoom = z;
                }
            }

            this._setZoom(fitZoom);
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
            // Property inputs
            this._bindPropertyInput('prop-x', 'x', parseInt);
            this._bindPropertyInput('prop-y', 'y', parseInt);
            this._bindPropertyInput('prop-width', 'width', parseInt);
            this._bindPropertyInput('prop-height', 'height', parseInt);
            this._bindPropertyInput('prop-name', 'name', String);
            this._bindPropertyInput('prop-opacity-value', 'opacity', (v) => parseInt(v) / 100);
            this._bindPropertyInput('prop-background', 'background_color', String);
            this._bindPropertyInput('prop-border-width', 'border_width', parseInt);
            this._bindPropertyInput('prop-border-color', 'border_color', String);
            this._bindPropertyInput('prop-border-radius', 'border_radius', parseInt);

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
                case 'background_color':
                    obj.set('fill', value || 'rgba(0, 212, 170, 0.1)');
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

            // Update property inputs
            this._setPropertyValue('prop-x', data.x || 0);
            this._setPropertyValue('prop-y', data.y || 0);
            this._setPropertyValue('prop-width', data.width || 400);
            this._setPropertyValue('prop-height', data.height || 300);
            this._setPropertyValue('prop-name', data.name || '');
            this._setPropertyValue('prop-opacity', Math.round((data.opacity || 1) * 100));
            this._setPropertyValue('prop-opacity-value', Math.round((data.opacity || 1) * 100));
            this._setPropertyValue('prop-background', data.background_color || 'transparent');
            this._setPropertyValue('prop-border-width', data.border_width || 0);
            this._setPropertyValue('prop-border-color', data.border_color || '#333333');
            this._setPropertyValue('prop-border-radius', data.border_radius || 0);
            this._setPropertyValue('prop-z-index', data.z_index || 0);
            this._setPropertyValue('prop-fit-mode', data.fit_mode || 'cover');
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
         * Update property inputs during drag/resize
         * @param {Object} bounds - Current bounds
         * @private
         */
        _updatePropertyInputs(bounds) {
            this._setPropertyValue('prop-x', bounds.x);
            this._setPropertyValue('prop-y', bounds.y);
            this._setPropertyValue('prop-width', bounds.width);
            this._setPropertyValue('prop-height', bounds.height);
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
        // Check if we have layout data
        if (!window.LAYOUT_DATA || !window.API_ENDPOINTS) {
            return;
        }

        // Wait for dependencies
        if (typeof fabric === 'undefined' || typeof FabricExtensions === 'undefined') {
            return;
        }

        // Create designer instance
        window.layoutDesigner = new LayoutDesigner(
            window.LAYOUT_DATA,
            window.API_ENDPOINTS
        );
    }

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        // Small delay to ensure all scripts are loaded
        setTimeout(init, 0);
    }

    // =========================================================================
    // Export to Global Namespace
    // =========================================================================

    window.LayoutDesigner = LayoutDesigner;

    // Export constants
    window.LayoutDesigner.TOOLS = TOOLS;
    window.LayoutDesigner.ZOOM_LEVELS = ZOOM_LEVELS;

})(window);

/**
 * Skillz Media CMS - Fabric.js Extensions
 *
 * Custom Fabric.js behaviors for the Layout Designer:
 * - Snap to grid functionality
 * - Minimum size constraints (prevent invisible layers)
 * - Maximum size constraints (canvas bounds)
 * - Integer coordinate enforcement
 * - Layer-specific control customization
 */

(function(window) {
    'use strict';

    // =========================================================================
    // Constants
    // =========================================================================

    /** Minimum layer dimensions in pixels */
    const MIN_LAYER_WIDTH = 20;
    const MIN_LAYER_HEIGHT = 20;

    /** Default grid size for snapping */
    const DEFAULT_GRID_SIZE = 10;

    /** Default control appearance */
    const CONTROL_CONFIG = {
        cornerColor: '#00D4AA',
        cornerStrokeColor: '#00D4AA',
        cornerSize: 10,
        cornerStyle: 'circle',
        transparentCorners: false,
        borderColor: '#00D4AA',
        borderScaleFactor: 2,
        padding: 0,
        rotatingPointOffset: 0
    };

    /**
     * 8-point control visibility configuration
     * - 4 corners: tl, tr, bl, br (top-left, top-right, bottom-left, bottom-right)
     * - 4 edges: mt, mb, ml, mr (middle-top, middle-bottom, middle-left, middle-right)
     * - mtr: rotation control (hidden)
     */
    const CONTROL_VISIBILITY = {
        tl: true,   // top-left corner
        tr: true,   // top-right corner
        bl: true,   // bottom-left corner
        br: true,   // bottom-right corner
        mt: true,   // middle-top edge
        mb: true,   // middle-bottom edge
        ml: true,   // middle-left edge
        mr: true,   // middle-right edge
        mtr: false  // rotation control (disabled)
    };

    /**
     * Cursor styles for each control point
     */
    const CONTROL_CURSORS = {
        tl: 'nwse-resize',
        tr: 'nesw-resize',
        bl: 'nesw-resize',
        br: 'nwse-resize',
        mt: 'ns-resize',
        mb: 'ns-resize',
        ml: 'ew-resize',
        mr: 'ew-resize'
    };

    /** Selection rectangle styling */
    const SELECTION_CONFIG = {
        selectionColor: 'rgba(0, 212, 170, 0.1)',
        selectionBorderColor: '#00D4AA',
        selectionLineWidth: 1
    };

    // =========================================================================
    // FabricExtensions Class
    // =========================================================================

    /**
     * FabricExtensions provides custom behaviors for Fabric.js canvas
     * @class
     */
    class FabricExtensions {
        /**
         * Create a FabricExtensions instance
         * @param {fabric.Canvas} canvas - The Fabric.js canvas instance
         * @param {Object} options - Configuration options
         */
        constructor(canvas, options = {}) {
            this.canvas = canvas;
            this.options = {
                snapToGrid: options.snapToGrid || false,
                gridSize: options.gridSize || DEFAULT_GRID_SIZE,
                enforceMinSize: options.enforceMinSize !== false,
                enforceMaxSize: options.enforceMaxSize !== false,
                enforceIntegerCoords: options.enforceIntegerCoords !== false,
                minWidth: options.minWidth || MIN_LAYER_WIDTH,
                minHeight: options.minHeight || MIN_LAYER_HEIGHT,
                maxWidth: options.maxWidth || null,
                maxHeight: options.maxHeight || null,
                canvasBounds: options.canvasBounds || null,
                onObjectModified: options.onObjectModified || null,
                onObjectMoving: options.onObjectMoving || null,
                onObjectScaling: options.onObjectScaling || null
            };

            this._setupCanvas();
            this._setupEventHandlers();
        }

        // =====================================================================
        // Setup Methods
        // =====================================================================

        /**
         * Configure canvas with custom settings
         * @private
         */
        _setupCanvas() {
            // Apply selection styling
            Object.assign(this.canvas, SELECTION_CONFIG);

            // Disable rotation on all objects by default
            fabric.Object.prototype.lockRotation = true;
            fabric.Object.prototype.hasRotatingPoint = false;

            // Apply default control styles
            this._applyControlStyles(fabric.Object.prototype);
        }

        /**
         * Apply control styles to an object or prototype
         * @param {fabric.Object} target - Object or prototype to apply styles to
         * @private
         */
        _applyControlStyles(target) {
            Object.assign(target, CONTROL_CONFIG);

            // Apply cursor styles for each control point
            if (target.controls) {
                Object.keys(CONTROL_CURSORS).forEach(controlName => {
                    if (target.controls[controlName]) {
                        target.controls[controlName].cursorStyle = CONTROL_CURSORS[controlName];
                    }
                });
            }
        }

        /**
         * Set up canvas event handlers
         * @private
         */
        _setupEventHandlers() {
            // Object moving event
            this.canvas.on('object:moving', (e) => this._handleObjectMoving(e));

            // Object scaling event
            this.canvas.on('object:scaling', (e) => this._handleObjectScaling(e));

            // Object modified event (after drag/resize ends)
            this.canvas.on('object:modified', (e) => this._handleObjectModified(e));

            // Object added event
            this.canvas.on('object:added', (e) => this._handleObjectAdded(e));
        }

        // =====================================================================
        // Event Handlers
        // =====================================================================

        /**
         * Handle object moving event
         * @param {Object} e - Fabric event object
         * @private
         */
        _handleObjectMoving(e) {
            const obj = e.target;
            if (!obj) return;

            // Snap to grid if enabled
            if (this.options.snapToGrid) {
                this._snapToGrid(obj);
            }

            // Constrain to canvas bounds
            if (this.options.canvasBounds) {
                this._constrainToBounds(obj);
            }

            // Enforce integer coordinates
            if (this.options.enforceIntegerCoords) {
                this._enforceIntegerPosition(obj);
            }

            // Update coordinates for controls
            obj.setCoords();

            // Call custom callback
            if (this.options.onObjectMoving) {
                this.options.onObjectMoving(obj, this._getObjectBounds(obj));
            }
        }

        /**
         * Handle object scaling event
         * @param {Object} e - Fabric event object
         * @private
         */
        _handleObjectScaling(e) {
            const obj = e.target;
            if (!obj) return;

            // Get scaled dimensions
            const scaledWidth = obj.width * obj.scaleX;
            const scaledHeight = obj.height * obj.scaleY;

            // Enforce minimum size
            if (this.options.enforceMinSize) {
                this._enforceMinimumSize(obj, scaledWidth, scaledHeight);
            }

            // Enforce maximum size
            if (this.options.enforceMaxSize) {
                this._enforceMaximumSize(obj, scaledWidth, scaledHeight);
            }

            // Constrain to canvas bounds
            if (this.options.canvasBounds) {
                this._constrainToBounds(obj);
            }

            // Snap to grid if enabled
            if (this.options.snapToGrid) {
                this._snapToGrid(obj);
            }

            // Update coordinates for controls
            obj.setCoords();

            // Call custom callback
            if (this.options.onObjectScaling) {
                this.options.onObjectScaling(obj, this._getObjectBounds(obj));
            }
        }

        /**
         * Handle object modified event (after interaction ends)
         * @param {Object} e - Fabric event object
         * @private
         */
        _handleObjectModified(e) {
            const obj = e.target;
            if (!obj) return;

            // Final enforcement of integer coordinates
            if (this.options.enforceIntegerCoords) {
                this._enforceIntegerPosition(obj);
                this._normalizeScale(obj);
            }

            // Final snap to grid
            if (this.options.snapToGrid) {
                this._snapToGrid(obj);
            }

            // Ensure coordinates are updated
            obj.setCoords();

            // Call custom callback with final bounds
            if (this.options.onObjectModified) {
                const bounds = this._getObjectBounds(obj);
                this.options.onObjectModified(obj, bounds);
            }
        }

        /**
         * Handle object added event
         * @param {Object} e - Fabric event object
         * @private
         */
        _handleObjectAdded(e) {
            const obj = e.target;
            if (!obj) return;

            // Apply control styles to new objects
            this._applyControlStyles(obj);

            // Disable rotation
            obj.lockRotation = true;
            obj.hasRotatingPoint = false;

            // Configure 8-point resize controls (4 corners + 4 edges)
            // Hide only the rotation control (mtr)
            obj.setControlsVisibility(CONTROL_VISIBILITY);

            // Apply cursor styles for each control
            this._applyControlCursors(obj);
        }

        /**
         * Apply cursor styles to object controls
         * @param {fabric.Object} obj - The object to configure
         * @private
         */
        _applyControlCursors(obj) {
            if (!obj.controls) return;

            Object.keys(CONTROL_CURSORS).forEach(controlName => {
                if (obj.controls[controlName]) {
                    obj.controls[controlName].cursorStyle = CONTROL_CURSORS[controlName];
                }
            });
        }

        // =====================================================================
        // Constraint Methods
        // =====================================================================

        /**
         * Snap object position to grid
         * @param {fabric.Object} obj - The object to snap
         * @private
         */
        _snapToGrid(obj) {
            const gridSize = this.options.gridSize;
            obj.left = Math.round(obj.left / gridSize) * gridSize;
            obj.top = Math.round(obj.top / gridSize) * gridSize;
        }

        /**
         * Snap a value to grid
         * @param {number} value - The value to snap
         * @returns {number} - Snapped value
         */
        snapValueToGrid(value) {
            const gridSize = this.options.gridSize;
            return Math.round(value / gridSize) * gridSize;
        }

        /**
         * Enforce integer position on object
         * @param {fabric.Object} obj - The object to modify
         * @private
         */
        _enforceIntegerPosition(obj) {
            obj.left = Math.round(obj.left);
            obj.top = Math.round(obj.top);
        }

        /**
         * Normalize scale values to integers and reset scale to 1
         * This converts scaled dimensions to actual dimensions
         * @param {fabric.Object} obj - The object to normalize
         * @private
         */
        _normalizeScale(obj) {
            // Calculate final dimensions
            const finalWidth = Math.round(obj.width * obj.scaleX);
            const finalHeight = Math.round(obj.height * obj.scaleY);

            // Set actual dimensions and reset scale
            obj.set({
                width: finalWidth,
                height: finalHeight,
                scaleX: 1,
                scaleY: 1
            });
        }

        /**
         * Enforce minimum size constraints
         * @param {fabric.Object} obj - The object to constrain
         * @param {number} scaledWidth - Current scaled width
         * @param {number} scaledHeight - Current scaled height
         * @private
         */
        _enforceMinimumSize(obj, scaledWidth, scaledHeight) {
            const minWidth = this.options.minWidth;
            const minHeight = this.options.minHeight;

            if (scaledWidth < minWidth) {
                obj.scaleX = minWidth / obj.width;
            }

            if (scaledHeight < minHeight) {
                obj.scaleY = minHeight / obj.height;
            }
        }

        /**
         * Enforce maximum size constraints
         * @param {fabric.Object} obj - The object to constrain
         * @param {number} scaledWidth - Current scaled width
         * @param {number} scaledHeight - Current scaled height
         * @private
         */
        _enforceMaximumSize(obj, scaledWidth, scaledHeight) {
            let maxWidth = this.options.maxWidth;
            let maxHeight = this.options.maxHeight;

            // Use canvas bounds if no explicit max set
            if (this.options.canvasBounds) {
                maxWidth = maxWidth || this.options.canvasBounds.width;
                maxHeight = maxHeight || this.options.canvasBounds.height;
            }

            if (maxWidth && scaledWidth > maxWidth) {
                obj.scaleX = maxWidth / obj.width;
            }

            if (maxHeight && scaledHeight > maxHeight) {
                obj.scaleY = maxHeight / obj.height;
            }
        }

        /**
         * Constrain object to canvas bounds
         * @param {fabric.Object} obj - The object to constrain
         * @private
         */
        _constrainToBounds(obj) {
            const bounds = this.options.canvasBounds;
            if (!bounds) return;

            const scaledWidth = obj.width * obj.scaleX;
            const scaledHeight = obj.height * obj.scaleY;

            // Constrain left position
            if (obj.left < 0) {
                obj.left = 0;
            } else if (obj.left + scaledWidth > bounds.width) {
                obj.left = bounds.width - scaledWidth;
            }

            // Constrain top position
            if (obj.top < 0) {
                obj.top = 0;
            } else if (obj.top + scaledHeight > bounds.height) {
                obj.top = bounds.height - scaledHeight;
            }
        }

        // =====================================================================
        // Utility Methods
        // =====================================================================

        /**
         * Get object bounds as integer pixel values
         * @param {fabric.Object} obj - The object to get bounds for
         * @returns {Object} - Object with x, y, width, height properties
         */
        _getObjectBounds(obj) {
            return {
                x: Math.round(obj.left),
                y: Math.round(obj.top),
                width: Math.round(obj.width * obj.scaleX),
                height: Math.round(obj.height * obj.scaleY)
            };
        }

        /**
         * Get object bounds (public method)
         * @param {fabric.Object} obj - The object to get bounds for
         * @returns {Object} - Object with x, y, width, height properties
         */
        getObjectBounds(obj) {
            return this._getObjectBounds(obj);
        }

        /**
         * Set canvas bounds for constraint checking
         * @param {number} width - Canvas width
         * @param {number} height - Canvas height
         */
        setCanvasBounds(width, height) {
            this.options.canvasBounds = { width, height };
        }

        /**
         * Enable or disable snap to grid
         * @param {boolean} enabled - Whether snap to grid is enabled
         * @param {number} [gridSize] - Optional new grid size
         */
        setSnapToGrid(enabled, gridSize) {
            this.options.snapToGrid = enabled;
            if (gridSize !== undefined) {
                this.options.gridSize = gridSize;
            }
        }

        /**
         * Get current snap to grid status
         * @returns {Object} - Object with enabled and gridSize properties
         */
        getSnapToGridStatus() {
            return {
                enabled: this.options.snapToGrid,
                gridSize: this.options.gridSize
            };
        }

        /**
         * Set minimum size constraints
         * @param {number} minWidth - Minimum width
         * @param {number} minHeight - Minimum height
         */
        setMinimumSize(minWidth, minHeight) {
            this.options.minWidth = minWidth;
            this.options.minHeight = minHeight;
        }

        /**
         * Set maximum size constraints
         * @param {number} maxWidth - Maximum width
         * @param {number} maxHeight - Maximum height
         */
        setMaximumSize(maxWidth, maxHeight) {
            this.options.maxWidth = maxWidth;
            this.options.maxHeight = maxHeight;
        }

        // =====================================================================
        // Object Creation Helpers
        // =====================================================================

        /**
         * Create a layer rectangle with proper constraints
         * @param {Object} config - Layer configuration
         * @returns {fabric.Rect} - The created rectangle
         */
        createLayerRect(config) {
            const {
                x = 0,
                y = 0,
                width = 200,
                height = 150,
                fill = 'rgba(0, 212, 170, 0.2)',
                stroke = '#00D4AA',
                strokeWidth = 2,
                layerId = null,
                layerName = null,
                layerData = null
            } = config;

            // Ensure integer values and minimum size
            const rectConfig = {
                left: Math.round(x),
                top: Math.round(y),
                width: Math.max(Math.round(width), this.options.minWidth),
                height: Math.max(Math.round(height), this.options.minHeight),
                fill: fill,
                stroke: stroke,
                strokeWidth: strokeWidth,
                hasControls: true,
                hasBorders: true,
                lockRotation: true,
                hasRotatingPoint: false,
                ...CONTROL_CONFIG
            };

            const rect = new fabric.Rect(rectConfig);

            // Store custom layer data
            if (layerId !== null) {
                rect.set('layerId', layerId);
            }
            if (layerName !== null) {
                rect.set('layerName', layerName);
            }
            if (layerData !== null) {
                rect.set('layerData', layerData);
            }

            // Configure 8-point resize controls (4 corners + 4 edges)
            // Hide only the rotation control (mtr)
            rect.setControlsVisibility(CONTROL_VISIBILITY);

            // Apply cursor styles for resize handles
            this._applyControlCursors(rect);

            return rect;
        }

        /**
         * Update an existing layer rectangle
         * @param {fabric.Rect} rect - The rectangle to update
         * @param {Object} config - New configuration values
         */
        updateLayerRect(rect, config) {
            const updates = {};

            if (config.x !== undefined) {
                updates.left = Math.round(config.x);
            }
            if (config.y !== undefined) {
                updates.top = Math.round(config.y);
            }
            if (config.width !== undefined) {
                updates.width = Math.max(Math.round(config.width), this.options.minWidth);
                updates.scaleX = 1;
            }
            if (config.height !== undefined) {
                updates.height = Math.max(Math.round(config.height), this.options.minHeight);
                updates.scaleY = 1;
            }
            if (config.fill !== undefined) {
                updates.fill = config.fill;
            }
            if (config.stroke !== undefined) {
                updates.stroke = config.stroke;
            }
            if (config.strokeWidth !== undefined) {
                updates.strokeWidth = config.strokeWidth;
            }
            if (config.opacity !== undefined) {
                updates.opacity = config.opacity;
            }
            if (config.visible !== undefined) {
                updates.visible = config.visible;
            }
            if (config.selectable !== undefined) {
                updates.selectable = config.selectable;
                updates.evented = config.selectable;
            }

            rect.set(updates);

            // Update custom data
            if (config.layerId !== undefined) {
                rect.set('layerId', config.layerId);
            }
            if (config.layerName !== undefined) {
                rect.set('layerName', config.layerName);
            }
            if (config.layerData !== undefined) {
                rect.set('layerData', config.layerData);
            }

            // CRITICAL: Must call setCoords after programmatic changes
            rect.setCoords();
        }

        // =====================================================================
        // Canvas Grid Drawing
        // =====================================================================

        /**
         * Draw grid lines on the canvas
         * @param {string} [color='rgba(255, 255, 255, 0.1)'] - Grid line color
         */
        drawGrid(color = 'rgba(255, 255, 255, 0.1)') {
            if (!this.options.canvasBounds) return;

            const gridSize = this.options.gridSize;
            const width = this.options.canvasBounds.width;
            const height = this.options.canvasBounds.height;
            const gridLines = [];

            // Vertical lines
            for (let x = gridSize; x < width; x += gridSize) {
                const line = new fabric.Line([x, 0, x, height], {
                    stroke: color,
                    selectable: false,
                    evented: false,
                    excludeFromExport: true
                });
                line.set('isGridLine', true);
                gridLines.push(line);
            }

            // Horizontal lines
            for (let y = gridSize; y < height; y += gridSize) {
                const line = new fabric.Line([0, y, width, y], {
                    stroke: color,
                    selectable: false,
                    evented: false,
                    excludeFromExport: true
                });
                line.set('isGridLine', true);
                gridLines.push(line);
            }

            // Add all grid lines to canvas (at the back)
            gridLines.forEach(line => {
                this.canvas.add(line);
                this.canvas.sendToBack(line);
            });

            this.canvas.renderAll();
        }

        /**
         * Remove grid lines from the canvas
         */
        removeGrid() {
            const objects = this.canvas.getObjects();
            const gridLines = objects.filter(obj => obj.isGridLine === true);
            gridLines.forEach(line => this.canvas.remove(line));
            this.canvas.renderAll();
        }

        /**
         * Toggle grid visibility
         * @param {boolean} visible - Whether grid should be visible
         * @param {string} [color] - Grid line color
         */
        toggleGrid(visible, color) {
            this.removeGrid();
            if (visible) {
                this.drawGrid(color);
            }
        }

        // =====================================================================
        // Selection Helpers
        // =====================================================================

        /**
         * Select a layer by its ID
         * @param {string|number} layerId - The layer ID to select
         * @returns {fabric.Object|null} - The selected object or null
         */
        selectLayerById(layerId) {
            const objects = this.canvas.getObjects();
            const obj = objects.find(o => o.layerId === layerId);

            if (obj) {
                this.canvas.setActiveObject(obj);
                this.canvas.renderAll();
                return obj;
            }

            return null;
        }

        /**
         * Deselect all objects
         */
        deselectAll() {
            this.canvas.discardActiveObject();
            this.canvas.renderAll();
        }

        /**
         * Get the currently selected layer object
         * @returns {fabric.Object|null} - Selected object or null
         */
        getSelectedLayer() {
            return this.canvas.getActiveObject();
        }

        /**
         * Get layer object by ID
         * @param {string|number} layerId - The layer ID
         * @returns {fabric.Object|null} - The layer object or null
         */
        getLayerById(layerId) {
            const objects = this.canvas.getObjects();
            return objects.find(o => o.layerId === layerId) || null;
        }

        /**
         * Get all layer objects (excluding grid lines, etc.)
         * @returns {fabric.Object[]} - Array of layer objects
         */
        getAllLayers() {
            const objects = this.canvas.getObjects();
            return objects.filter(obj =>
                obj.layerId !== undefined &&
                obj.isGridLine !== true
            );
        }

        // =====================================================================
        // Z-Index Helpers
        // =====================================================================

        /**
         * Bring selected object forward
         */
        bringForward() {
            const obj = this.canvas.getActiveObject();
            if (obj) {
                this.canvas.bringForward(obj);
                this.canvas.renderAll();
            }
        }

        /**
         * Send selected object backward
         */
        sendBackward() {
            const obj = this.canvas.getActiveObject();
            if (obj) {
                this.canvas.sendBackwards(obj);
                this.canvas.renderAll();
            }
        }

        /**
         * Bring selected object to front
         */
        bringToFront() {
            const obj = this.canvas.getActiveObject();
            if (obj) {
                this.canvas.bringToFront(obj);
                this.canvas.renderAll();
            }
        }

        /**
         * Send selected object to back
         */
        sendToBack() {
            const obj = this.canvas.getActiveObject();
            if (obj) {
                this.canvas.sendToBack(obj);
                this.canvas.renderAll();
            }
        }

        /**
         * Get the z-index of an object
         * @param {fabric.Object} obj - The object
         * @returns {number} - The z-index
         */
        getObjectZIndex(obj) {
            const objects = this.canvas.getObjects();
            return objects.indexOf(obj);
        }

        /**
         * Set the z-index of an object
         * @param {fabric.Object} obj - The object
         * @param {number} index - The new z-index
         */
        setObjectZIndex(obj, index) {
            this.canvas.moveTo(obj, index);
            this.canvas.renderAll();
        }

        // =====================================================================
        // Cleanup
        // =====================================================================

        /**
         * Remove all event handlers and clean up
         */
        destroy() {
            this.canvas.off('object:moving');
            this.canvas.off('object:scaling');
            this.canvas.off('object:modified');
            this.canvas.off('object:added');
        }
    }

    // =========================================================================
    // Utility Functions
    // =========================================================================

    /**
     * Round a number to integer
     * @param {number} value - The value to round
     * @returns {number} - Rounded integer
     */
    function roundToInt(value) {
        return Math.round(value);
    }

    /**
     * Clamp a value between min and max
     * @param {number} value - The value to clamp
     * @param {number} min - Minimum value
     * @param {number} max - Maximum value
     * @returns {number} - Clamped value
     */
    function clamp(value, min, max) {
        return Math.max(min, Math.min(max, value));
    }

    /**
     * Parse RGBA color string to object
     * @param {string} rgba - RGBA color string
     * @returns {Object|null} - Object with r, g, b, a properties or null
     */
    function parseRgba(rgba) {
        const match = rgba.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\)/);
        if (!match) return null;
        return {
            r: parseInt(match[1], 10),
            g: parseInt(match[2], 10),
            b: parseInt(match[3], 10),
            a: match[4] !== undefined ? parseFloat(match[4]) : 1
        };
    }

    /**
     * Convert object to RGBA string
     * @param {Object} color - Object with r, g, b, a properties
     * @returns {string} - RGBA color string
     */
    function toRgba(color) {
        const a = color.a !== undefined ? color.a : 1;
        return `rgba(${color.r}, ${color.g}, ${color.b}, ${a})`;
    }

    /**
     * Parse hex color to RGB object
     * @param {string} hex - Hex color string (with or without #)
     * @returns {Object|null} - Object with r, g, b properties or null
     */
    function hexToRgb(hex) {
        // Remove # if present
        hex = hex.replace(/^#/, '');

        // Handle 3-character hex
        if (hex.length === 3) {
            hex = hex.split('').map(char => char + char).join('');
        }

        const result = /^([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
        return result ? {
            r: parseInt(result[1], 16),
            g: parseInt(result[2], 16),
            b: parseInt(result[3], 16)
        } : null;
    }

    /**
     * Convert RGB object to hex string
     * @param {Object} rgb - Object with r, g, b properties
     * @returns {string} - Hex color string with #
     */
    function rgbToHex(rgb) {
        const toHex = (c) => {
            const hex = c.toString(16);
            return hex.length === 1 ? '0' + hex : hex;
        };
        return '#' + toHex(rgb.r) + toHex(rgb.g) + toHex(rgb.b);
    }

    // =========================================================================
    // Export to Global Namespace
    // =========================================================================

    window.FabricExtensions = FabricExtensions;

    // Also expose constants and utilities
    window.FabricExtensions.constants = {
        MIN_LAYER_WIDTH,
        MIN_LAYER_HEIGHT,
        DEFAULT_GRID_SIZE,
        CONTROL_CONFIG,
        CONTROL_VISIBILITY,
        CONTROL_CURSORS,
        SELECTION_CONFIG
    };

    window.FabricExtensions.utils = {
        roundToInt,
        clamp,
        parseRgba,
        toRgba,
        hexToRgb,
        rgbToHex
    };

})(window);

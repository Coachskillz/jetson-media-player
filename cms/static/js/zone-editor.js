/**
 * ZoneEditor - Vanilla JavaScript Photoshop-style Zone Editor
 *
 * A drop-in replacement/alternative to Fabric.js for the layout designer.
 * Uses Pointer Events for unified mouse + touch support.
 *
 * Usage:
 *   const editor = new ZoneEditor({
 *     container: document.getElementById('canvas-container'),
 *     canvasWidth: 1920,
 *     canvasHeight: 1080,
 *     zoom: 0.5,
 *     onChange: (zones) => console.log('Zones updated:', zones)
 *   });
 */

(function(window) {
    'use strict';

    // ========================================================================
    // Constants
    // ========================================================================

    const HANDLE_SIZE = 14;
    const MIN_ZONE_SIZE = 20;
    const COLORS = ['#00D4AA', '#667EEA', '#F59E0B', '#EF4444', '#8B5CF6', '#EC4899'];

    // 8-point resize handles
    const HANDLES = [
        { id: 'tl', cursor: 'nwse-resize', x: 0, y: 0 },
        { id: 'tm', cursor: 'ns-resize', x: 0.5, y: 0 },
        { id: 'tr', cursor: 'nesw-resize', x: 1, y: 0 },
        { id: 'ml', cursor: 'ew-resize', x: 0, y: 0.5 },
        { id: 'mr', cursor: 'ew-resize', x: 1, y: 0.5 },
        { id: 'bl', cursor: 'nesw-resize', x: 0, y: 1 },
        { id: 'bm', cursor: 'ns-resize', x: 0.5, y: 1 },
        { id: 'br', cursor: 'nwse-resize', x: 1, y: 1 },
    ];

    // ========================================================================
    // ZoneEditor Class
    // ========================================================================

    class ZoneEditor {
        constructor(options = {}) {
            this.container = options.container;
            this.canvasWidth = options.canvasWidth || 1920;
            this.canvasHeight = options.canvasHeight || 1080;
            this.zoom = options.zoom || 0.5;
            this.onChange = options.onChange || null;
            this.onSelect = options.onSelect || null;

            // State
            this.zones = [];
            this.selectedId = null;
            this.dragState = null;
            this.rafId = null;
            this.pendingUpdate = null;
            this.zCounter = 1;

            // DOM elements
            this.canvas = null;
            this.zoneElements = new Map();

            // Bind methods
            this._handlePointerMove = this._handlePointerMove.bind(this);
            this._handlePointerUp = this._handlePointerUp.bind(this);
            this._handleKeyDown = this._handleKeyDown.bind(this);

            // Initialize
            this._init();
        }

        // ====================================================================
        // Initialization
        // ====================================================================

        _init() {
            this._createCanvas();
            this._bindEvents();
        }

        _createCanvas() {
            // Clear container
            this.container.innerHTML = '';

            // Create canvas wrapper
            this.canvasWrapper = document.createElement('div');
            this.canvasWrapper.style.cssText = `
                display: flex;
                align-items: center;
                justify-content: center;
                width: 100%;
                height: 100%;
                background: #1a1a2e;
                overflow: auto;
                padding: 40px;
                box-sizing: border-box;
            `;

            // Create canvas
            this.canvas = document.createElement('div');
            this.canvas.style.cssText = `
                position: relative;
                width: ${this.canvasWidth * this.zoom}px;
                height: ${this.canvasHeight * this.zoom}px;
                background: #000;
                border: 3px solid #667eea;
                box-shadow: 0 0 0 1px rgba(102, 126, 234, 0.3), 0 20px 60px rgba(0, 0, 0, 0.5);
                touch-action: none;
                user-select: none;
            `;

            this.canvasWrapper.appendChild(this.canvas);
            this.container.appendChild(this.canvasWrapper);
        }

        _bindEvents() {
            // Canvas click to deselect
            this.canvas.addEventListener('pointerdown', (e) => {
                if (e.target === this.canvas) {
                    this.select(null);
                }
            });

            // IMPORTANT: Bind move/up to document for reliable capture
            // This ensures we catch events even when pointer leaves the element
            document.addEventListener('pointermove', this._handlePointerMove);
            document.addEventListener('pointerup', this._handlePointerUp);
            document.addEventListener('pointercancel', this._handlePointerUp);

            // Keyboard events
            window.addEventListener('keydown', this._handleKeyDown);
        }

        // ====================================================================
        // Public API
        // ====================================================================

        /**
         * Set zones from external data
         */
        setZones(zones) {
            // Clear existing
            this.zoneElements.forEach((el) => el.remove());
            this.zoneElements.clear();

            // Add new zones
            this.zones = zones.map((z, i) => ({
                id: z.id || String(Date.now() + i),
                x: z.x !== undefined ? this._pixelsToPct(z.x, 'x') : (z.left || 0),
                y: z.y !== undefined ? this._pixelsToPct(z.y, 'y') : (z.top || 0),
                width: z.width !== undefined ? this._pixelsToPct(z.width, 'width') : 100,
                height: z.height !== undefined ? this._pixelsToPct(z.height, 'height') : 100,
                z: z.z_index || z.z || ++this.zCounter,
                name: z.name || `Zone ${i + 1}`,
                color: z.color || COLORS[i % COLORS.length],
                data: z // Keep original data
            }));

            // Render all zones
            this.zones.forEach(zone => this._renderZone(zone));

            return this;
        }

        /**
         * Get zones as pixel values (for saving)
         */
        getZones() {
            return this.zones.map(z => ({
                id: z.id,
                x: Math.round(this._pctToPixels(z.x, 'x')),
                y: Math.round(this._pctToPixels(z.y, 'y')),
                width: Math.round(this._pctToPixels(z.width, 'width')),
                height: Math.round(this._pctToPixels(z.height, 'height')),
                z_index: z.z,
                name: z.name,
                ...z.data // Include original data
            }));
        }

        /**
         * Get zones as percentage values
         */
        getZonesAsPercent() {
            return this.zones.map(z => ({
                id: z.id,
                left: z.x,
                top: z.y,
                width: z.width,
                height: z.height,
                z: z.z,
                name: z.name
            }));
        }

        /**
         * Add a new zone
         */
        addZone(config = {}) {
            const id = config.id || String(Date.now());
            const maxZ = this.zones.length > 0 ? Math.max(...this.zones.map(z => z.z)) : 0;

            const zone = {
                id,
                x: config.x !== undefined ? config.x : 10,
                y: config.y !== undefined ? config.y : 10,
                width: config.width !== undefined ? config.width : 30,
                height: config.height !== undefined ? config.height : 30,
                z: maxZ + 1,
                name: config.name || `Zone ${this.zones.length + 1}`,
                color: config.color || COLORS[this.zones.length % COLORS.length],
                data: config.data || {}
            };

            this.zones.push(zone);
            this._renderZone(zone);
            this.select(id);
            this._notifyChange();

            return zone;
        }

        /**
         * Remove a zone
         */
        removeZone(id) {
            const index = this.zones.findIndex(z => z.id === id);
            if (index === -1) return;

            this.zones.splice(index, 1);
            const el = this.zoneElements.get(id);
            if (el) {
                el.remove();
                this.zoneElements.delete(id);
            }

            if (this.selectedId === id) {
                this.select(null);
            }

            this._notifyChange();
        }

        /**
         * Select a zone
         */
        select(id) {
            this.selectedId = id;

            // Update visual selection
            this.zoneElements.forEach((el, zoneId) => {
                const isSelected = zoneId === id;
                el.classList.toggle('selected', isSelected);

                // Show/hide handles
                const handles = el.querySelectorAll('.zone-handle');
                handles.forEach(h => h.style.display = isSelected ? 'block' : 'none');
            });

            // Bring to front
            if (id) {
                const zone = this.zones.find(z => z.id === id);
                if (zone) {
                    const maxZ = Math.max(...this.zones.map(z => z.z));
                    if (zone.z < maxZ) {
                        zone.z = maxZ + 1;
                        this._updateZoneStyle(zone);
                    }
                }
            }

            // Callback
            if (this.onSelect) {
                const zone = this.zones.find(z => z.id === id);
                this.onSelect(zone || null);
            }
        }

        /**
         * Update zone properties
         */
        updateZone(id, updates) {
            const zone = this.zones.find(z => z.id === id);
            if (!zone) return;

            // Apply updates
            Object.assign(zone, updates);

            // Constrain to bounds
            this._constrainZone(zone);

            // Update visual
            this._updateZoneStyle(zone);
            this._notifyChange();

            return zone;
        }

        /**
         * Set zoom level
         */
        setZoom(zoom) {
            this.zoom = Math.max(0.1, Math.min(2, zoom));
            this.canvas.style.width = `${this.canvasWidth * this.zoom}px`;
            this.canvas.style.height = `${this.canvasHeight * this.zoom}px`;

            // Update all zones
            this.zones.forEach(zone => this._updateZoneStyle(zone));
        }

        /**
         * Get selected zone
         */
        getSelectedZone() {
            return this.zones.find(z => z.id === this.selectedId) || null;
        }

        /**
         * Destroy the editor
         */
        destroy() {
            // Remove document-level event listeners
            document.removeEventListener('pointermove', this._handlePointerMove);
            document.removeEventListener('pointerup', this._handlePointerUp);
            document.removeEventListener('pointercancel', this._handlePointerUp);
            window.removeEventListener('keydown', this._handleKeyDown);

            // Cancel any pending animation frame
            if (this.rafId) cancelAnimationFrame(this.rafId);

            // Clear drag state
            this.dragState = null;
            document.body.style.cursor = '';

            // Clear container
            this.container.innerHTML = '';
        }

        // ====================================================================
        // Internal Methods
        // ====================================================================

        _renderZone(zone) {
            const el = document.createElement('div');
            el.className = 'zone-item';
            el.dataset.id = zone.id;

            // Zone content
            el.innerHTML = `
                <div class="zone-label">${zone.name}</div>
                <div class="zone-dims"></div>
                ${HANDLES.map(h => `
                    <div class="zone-handle" data-handle="${h.id}"
                         style="left: ${h.x * 100}%; top: ${h.y * 100}%; cursor: ${h.cursor};"></div>
                `).join('')}
            `;

            // Apply styles
            this._applyZoneStyles(el, zone);

            // Bind events
            el.addEventListener('pointerdown', (e) => this._handleZonePointerDown(e, zone.id));

            // Handle events
            el.querySelectorAll('.zone-handle').forEach(handle => {
                handle.addEventListener('pointerdown', (e) => {
                    e.stopPropagation();
                    this._handleZonePointerDown(e, zone.id, handle.dataset.handle);
                });
            });

            this.canvas.appendChild(el);
            this.zoneElements.set(zone.id, el);
            this._updateZoneStyle(zone);
        }

        _applyZoneStyles(el, zone) {
            el.style.cssText = `
                position: absolute;
                border: 2px solid ${zone.color};
                background: ${zone.color}1A;
                box-sizing: border-box;
                user-select: none;
                touch-action: none;
                cursor: grab;
                transition: background-color 0.15s;
            `;

            // Label
            const label = el.querySelector('.zone-label');
            label.style.cssText = `
                position: absolute;
                top: 8px;
                left: 8px;
                font-size: 12px;
                font-weight: 600;
                color: #fff;
                text-shadow: 0 1px 2px rgba(0,0,0,0.5);
                pointer-events: none;
            `;

            // Dimensions
            const dims = el.querySelector('.zone-dims');
            dims.style.cssText = `
                position: absolute;
                bottom: 8px;
                right: 8px;
                font-size: 10px;
                color: rgba(255,255,255,0.7);
                font-family: Monaco, Menlo, monospace;
                pointer-events: none;
            `;

            // Handles
            el.querySelectorAll('.zone-handle').forEach(handle => {
                handle.style.cssText += `
                    position: absolute;
                    width: ${HANDLE_SIZE}px;
                    height: ${HANDLE_SIZE}px;
                    background: ${zone.color};
                    border: 2px solid #1a1a1f;
                    border-radius: 2px;
                    transform: translate(-50%, -50%);
                    touch-action: none;
                    display: none;
                `;
            });
        }

        _updateZoneStyle(zone) {
            const el = this.zoneElements.get(zone.id);
            if (!el) return;

            const scaledWidth = this.canvasWidth * this.zoom;
            const scaledHeight = this.canvasHeight * this.zoom;

            const x = (zone.x / 100) * scaledWidth;
            const y = (zone.y / 100) * scaledHeight;
            const width = (zone.width / 100) * scaledWidth;
            const height = (zone.height / 100) * scaledHeight;

            el.style.left = `${x}px`;
            el.style.top = `${y}px`;
            el.style.width = `${width}px`;
            el.style.height = `${height}px`;
            el.style.zIndex = zone.z;

            // Update label
            const label = el.querySelector('.zone-label');
            if (label) label.textContent = zone.name;

            // Update dimensions display
            const dims = el.querySelector('.zone-dims');
            if (dims) dims.textContent = `${zone.width.toFixed(1)}% x ${zone.height.toFixed(1)}%`;

            // Update selection style
            const isSelected = zone.id === this.selectedId;
            el.style.background = isSelected ? `${zone.color}33` : `${zone.color}1A`;
        }

        _constrainZone(zone) {
            const minW = this._pixelsToPct(MIN_ZONE_SIZE, 'width');
            const minH = this._pixelsToPct(MIN_ZONE_SIZE, 'height');

            zone.width = Math.max(minW, Math.min(100, zone.width));
            zone.height = Math.max(minH, Math.min(100, zone.height));
            zone.x = Math.max(0, Math.min(100 - zone.width, zone.x));
            zone.y = Math.max(0, Math.min(100 - zone.height, zone.y));
        }

        _pctToPixels(pct, dimension) {
            const size = dimension === 'x' || dimension === 'width' ? this.canvasWidth : this.canvasHeight;
            return (pct / 100) * size;
        }

        _pixelsToPct(pixels, dimension) {
            const size = dimension === 'x' || dimension === 'width' ? this.canvasWidth : this.canvasHeight;
            return (pixels / size) * 100;
        }

        _getPointerPosition(e) {
            const rect = this.canvas.getBoundingClientRect();
            return {
                x: (e.clientX - rect.left) / this.zoom,
                y: (e.clientY - rect.top) / this.zoom
            };
        }

        _notifyChange() {
            if (this.onChange) {
                this.onChange(this.getZones());
            }
        }

        // ====================================================================
        // Event Handlers
        // ====================================================================

        _handleZonePointerDown(e, zoneId, handle = null) {
            e.preventDefault();
            e.stopPropagation();

            const pos = this._getPointerPosition(e);
            const zone = this.zones.find(z => z.id === zoneId);
            if (!zone) return;

            // Select zone
            this.select(zoneId);

            // Set cursor on body to ensure it shows during drag
            document.body.style.cursor = 'grabbing';

            // Set cursor on zone element
            const el = this.zoneElements.get(zoneId);
            if (el) el.style.cursor = 'grabbing';

            // Store drag state with captured element info
            this.dragState = {
                zoneId,
                handle,
                startX: pos.x,
                startY: pos.y,
                initialZone: { ...zone },
                capturedElement: e.target,
                pointerId: e.pointerId
            };

            // Capture pointer on the target element
            try {
                e.target.setPointerCapture(e.pointerId);
            } catch (err) {
                // Pointer capture not supported or failed
                console.log('Pointer capture not available');
            }
        }

        _handlePointerMove(e) {
            if (!this.dragState) return;

            const pos = this._getPointerPosition(e);
            const { zoneId, handle, startX, startY, initialZone } = this.dragState;

            // Calculate delta
            const deltaXPx = pos.x - startX;
            const deltaYPx = pos.y - startY;
            const deltaX = this._pixelsToPct(deltaXPx, 'x');
            const deltaY = this._pixelsToPct(deltaYPx, 'y');

            // Store pending update
            this.pendingUpdate = { zoneId, handle, deltaX, deltaY, initialZone };

            // Use RAF for smooth 60fps updates
            if (!this.rafId) {
                this.rafId = requestAnimationFrame(() => {
                    if (this.pendingUpdate) {
                        const { zoneId, handle, deltaX, deltaY, initialZone } = this.pendingUpdate;
                        const zone = this.zones.find(z => z.id === zoneId);
                        if (!zone) return;

                        let updates = {};

                        if (!handle) {
                            // Moving
                            updates = {
                                x: initialZone.x + deltaX,
                                y: initialZone.y + deltaY
                            };
                        } else {
                            // Resizing based on handle
                            switch (handle) {
                                case 'tl':
                                    updates = {
                                        x: initialZone.x + deltaX,
                                        y: initialZone.y + deltaY,
                                        width: initialZone.width - deltaX,
                                        height: initialZone.height - deltaY
                                    };
                                    break;
                                case 'tm':
                                    updates = {
                                        y: initialZone.y + deltaY,
                                        height: initialZone.height - deltaY
                                    };
                                    break;
                                case 'tr':
                                    updates = {
                                        y: initialZone.y + deltaY,
                                        width: initialZone.width + deltaX,
                                        height: initialZone.height - deltaY
                                    };
                                    break;
                                case 'ml':
                                    updates = {
                                        x: initialZone.x + deltaX,
                                        width: initialZone.width - deltaX
                                    };
                                    break;
                                case 'mr':
                                    updates = { width: initialZone.width + deltaX };
                                    break;
                                case 'bl':
                                    updates = {
                                        x: initialZone.x + deltaX,
                                        width: initialZone.width - deltaX,
                                        height: initialZone.height + deltaY
                                    };
                                    break;
                                case 'bm':
                                    updates = { height: initialZone.height + deltaY };
                                    break;
                                case 'br':
                                    updates = {
                                        width: initialZone.width + deltaX,
                                        height: initialZone.height + deltaY
                                    };
                                    break;
                            }
                        }

                        this.updateZone(zoneId, updates);
                    }
                    this.rafId = null;
                });
            }
        }

        _handlePointerUp(e) {
            if (!this.dragState) return;

            // Reset body cursor
            document.body.style.cursor = '';

            // Reset zone cursor
            const el = this.zoneElements.get(this.dragState.zoneId);
            if (el) el.style.cursor = 'grab';

            // Release pointer capture on the original element
            try {
                if (this.dragState.capturedElement && this.dragState.pointerId !== undefined) {
                    this.dragState.capturedElement.releasePointerCapture(this.dragState.pointerId);
                }
            } catch (err) {
                // Ignore - capture may have already been released
            }

            // Clear drag state
            this.dragState = null;
            this.pendingUpdate = null;

            if (this.rafId) {
                cancelAnimationFrame(this.rafId);
                this.rafId = null;
            }
        }

        _handleKeyDown(e) {
            if (e.key === 'Delete' || e.key === 'Backspace') {
                if (this.selectedId && document.activeElement.tagName !== 'INPUT') {
                    e.preventDefault();
                    this.removeZone(this.selectedId);
                }
            }
        }
    }

    // Export
    window.ZoneEditor = ZoneEditor;

})(window);

/**
 * Skillz Media CMS - Layer Panel
 *
 * This module provides layer management functionality for the layout designer:
 * - Layer list with drag-to-reorder support
 * - Visibility toggles (eye icon)
 * - Lock toggles (lock icon)
 * - Z-order controls (bring forward/send backward)
 * - Layer selection and highlighting
 */

(function(window) {
    'use strict';

    // =========================================================================
    // Constants
    // =========================================================================

    /** Layer item HTML template */
    const LAYER_ITEM_TEMPLATE = `
        <div class="layer-item" data-layer-id="{id}">
            <span class="layer-visibility {visibleClass}"
                  data-action="toggle-visibility"
                  title="{visibilityTitle}"
                  role="button"
                  tabindex="0"
                  aria-label="{visibilityTitle}">
                {visibilityIcon}
            </span>
            <div class="layer-preview" style="background: {previewBg};"></div>
            <div class="layer-info">
                <div class="layer-name">{name}</div>
                <div class="layer-dims">{width} x {height}</div>
            </div>
            <span class="layer-lock {lockedClass}"
                  data-action="toggle-lock"
                  title="{lockTitle}"
                  role="button"
                  tabindex="0"
                  aria-label="{lockTitle}">
                {lockIcon}
            </span>
        </div>
    `;

    /** Default options */
    const DEFAULT_OPTIONS = {
        listId: 'layer-list',
        emptyId: 'layers-empty',
        addButtonId: 'add-layer',
        bringForwardId: 'layer-front',
        sendBackwardId: 'layer-back',
        deleteLayerId: 'layer-delete',
        sortDescending: true
    };

    // =========================================================================
    // LayerPanel Class
    // =========================================================================

    /**
     * LayerPanel manages the layer list UI and interactions
     * @class
     */
    class LayerPanel {
        /**
         * Create a LayerPanel instance
         * @param {Object} options - Configuration options
         */
        constructor(options = {}) {
            this.options = { ...DEFAULT_OPTIONS, ...options };
            this.layers = new Map();
            this.selectedLayerId = null;
            this.callbacks = {
                onSelect: null,
                onVisibilityChange: null,
                onLockChange: null,
                onReorder: null,
                onDelete: null,
                onAdd: null
            };

            this._init();
        }

        // =====================================================================
        // Initialization
        // =====================================================================

        /**
         * Initialize the layer panel
         * @private
         */
        _init() {
            this._bindControls();
        }

        /**
         * Bind control button event handlers
         * @private
         */
        _bindControls() {
            // Add layer button
            const addBtn = document.getElementById(this.options.addButtonId);
            if (addBtn) {
                addBtn.addEventListener('click', () => this._handleAdd());
            }

            // Bring forward button
            const forwardBtn = document.getElementById(this.options.bringForwardId);
            if (forwardBtn) {
                forwardBtn.addEventListener('click', () => this._handleBringForward());
            }

            // Send backward button
            const backwardBtn = document.getElementById(this.options.sendBackwardId);
            if (backwardBtn) {
                backwardBtn.addEventListener('click', () => this._handleSendBackward());
            }

            // Delete button
            const deleteBtn = document.getElementById(this.options.deleteLayerId);
            if (deleteBtn) {
                deleteBtn.addEventListener('click', () => this._handleDelete());
            }
        }

        // =====================================================================
        // Public API - Layer Management
        // =====================================================================

        /**
         * Set layers data and render the list
         * @param {Array|Map} layers - Array of layer data or Map of layer objects
         */
        setLayers(layers) {
            this.layers.clear();

            if (layers instanceof Map) {
                layers.forEach((layer, id) => {
                    this.layers.set(id, layer.data || layer);
                });
            } else if (Array.isArray(layers)) {
                layers.forEach(layer => {
                    this.layers.set(layer.id, layer);
                });
            }

            this.render();
        }

        /**
         * Add a layer to the panel
         * @param {Object} layerData - Layer data object
         */
        addLayer(layerData) {
            if (!layerData || !layerData.id) return;
            this.layers.set(layerData.id, layerData);
            this.render();
        }

        /**
         * Update a layer's data
         * @param {number|string} layerId - Layer ID
         * @param {Object} updates - Properties to update
         */
        updateLayer(layerId, updates) {
            const layer = this.layers.get(layerId);
            if (!layer) return;

            Object.assign(layer, updates);
            this.render();
        }

        /**
         * Remove a layer from the panel
         * @param {number|string} layerId - Layer ID
         */
        removeLayer(layerId) {
            this.layers.delete(layerId);
            if (this.selectedLayerId === layerId) {
                this.selectedLayerId = null;
            }
            this.render();
        }

        /**
         * Get a layer by ID
         * @param {number|string} layerId - Layer ID
         * @returns {Object|null} Layer data
         */
        getLayer(layerId) {
            return this.layers.get(layerId) || null;
        }

        /**
         * Get all layers as an array
         * @returns {Array} Array of layer data objects
         */
        getAllLayers() {
            return Array.from(this.layers.values());
        }

        /**
         * Get sorted layers (by z_index)
         * @returns {Array} Sorted array of layer data objects
         */
        getSortedLayers() {
            const layers = this.getAllLayers();
            return this.options.sortDescending
                ? layers.sort((a, b) => (b.z_index || 0) - (a.z_index || 0))
                : layers.sort((a, b) => (a.z_index || 0) - (b.z_index || 0));
        }

        // =====================================================================
        // Public API - Selection
        // =====================================================================

        /**
         * Select a layer by ID
         * @param {number|string} layerId - Layer ID
         */
        selectLayer(layerId) {
            this.selectedLayerId = layerId;
            this._updateSelection();

            if (this.callbacks.onSelect) {
                const layer = this.layers.get(layerId);
                this.callbacks.onSelect(layerId, layer);
            }
        }

        /**
         * Deselect all layers
         */
        deselectAll() {
            this.selectedLayerId = null;
            this._updateSelection();
        }

        /**
         * Get selected layer ID
         * @returns {number|string|null} Selected layer ID
         */
        getSelectedLayerId() {
            return this.selectedLayerId;
        }

        /**
         * Get selected layer data
         * @returns {Object|null} Selected layer data
         */
        getSelectedLayer() {
            if (!this.selectedLayerId) return null;
            return this.layers.get(this.selectedLayerId) || null;
        }

        // =====================================================================
        // Public API - Visibility and Lock
        // =====================================================================

        /**
         * Toggle layer visibility
         * @param {number|string} layerId - Layer ID
         * @returns {boolean} New visibility state
         */
        toggleVisibility(layerId) {
            const layer = this.layers.get(layerId);
            if (!layer) return false;

            const isVisible = layer.is_visible !== false;
            const newVisible = !isVisible;

            layer.is_visible = newVisible;
            this.render();

            if (this.callbacks.onVisibilityChange) {
                this.callbacks.onVisibilityChange(layerId, newVisible, layer);
            }

            return newVisible;
        }

        /**
         * Set layer visibility
         * @param {number|string} layerId - Layer ID
         * @param {boolean} visible - Visibility state
         */
        setVisibility(layerId, visible) {
            const layer = this.layers.get(layerId);
            if (!layer) return;

            layer.is_visible = visible;
            this.render();

            if (this.callbacks.onVisibilityChange) {
                this.callbacks.onVisibilityChange(layerId, visible, layer);
            }
        }

        /**
         * Toggle layer lock state
         * @param {number|string} layerId - Layer ID
         * @returns {boolean} New lock state
         */
        toggleLock(layerId) {
            const layer = this.layers.get(layerId);
            if (!layer) return false;

            const isLocked = layer.is_locked === true;
            const newLocked = !isLocked;

            layer.is_locked = newLocked;
            this.render();

            if (this.callbacks.onLockChange) {
                this.callbacks.onLockChange(layerId, newLocked, layer);
            }

            return newLocked;
        }

        /**
         * Set layer lock state
         * @param {number|string} layerId - Layer ID
         * @param {boolean} locked - Lock state
         */
        setLocked(layerId, locked) {
            const layer = this.layers.get(layerId);
            if (!layer) return;

            layer.is_locked = locked;
            this.render();

            if (this.callbacks.onLockChange) {
                this.callbacks.onLockChange(layerId, locked, layer);
            }
        }

        // =====================================================================
        // Public API - Z-Order
        // =====================================================================

        /**
         * Bring selected layer forward (increase z_index)
         */
        bringForward() {
            if (!this.selectedLayerId) return;
            this._handleBringForward();
        }

        /**
         * Send selected layer backward (decrease z_index)
         */
        sendBackward() {
            if (!this.selectedLayerId) return;
            this._handleSendBackward();
        }

        /**
         * Bring selected layer to front (highest z_index)
         */
        bringToFront() {
            if (!this.selectedLayerId) return;

            const layers = this.getSortedLayers();
            const maxZIndex = Math.max(...layers.map(l => l.z_index || 0));
            const layer = this.layers.get(this.selectedLayerId);

            if (layer && layer.z_index < maxZIndex) {
                layer.z_index = maxZIndex + 1;
                this._normalizeZIndexes();
                this.render();
                this._triggerReorder();
            }
        }

        /**
         * Send selected layer to back (lowest z_index)
         */
        sendToBack() {
            if (!this.selectedLayerId) return;

            const layers = this.getSortedLayers();
            const minZIndex = Math.min(...layers.map(l => l.z_index || 0));
            const layer = this.layers.get(this.selectedLayerId);

            if (layer && layer.z_index > minZIndex) {
                layer.z_index = minZIndex - 1;
                this._normalizeZIndexes();
                this.render();
                this._triggerReorder();
            }
        }

        /**
         * Check if selected layer can be moved forward
         * @returns {boolean} True if layer can be moved forward
         */
        canMoveForward() {
            return this._canMoveForward();
        }

        /**
         * Check if selected layer can be moved backward
         * @returns {boolean} True if layer can be moved backward
         */
        canMoveBackward() {
            return this._canMoveBackward();
        }

        /**
         * Check if selected layer is at the front (highest z-index)
         * @returns {boolean} True if layer is at front
         */
        isAtFront() {
            return !this._canMoveForward();
        }

        /**
         * Check if selected layer is at the back (lowest z-index)
         * @returns {boolean} True if layer is at back
         */
        isAtBack() {
            return !this._canMoveBackward();
        }

        // =====================================================================
        // Public API - Callbacks
        // =====================================================================

        /**
         * Set callback for layer selection
         * @param {Function} callback - (layerId, layerData) => void
         */
        onSelect(callback) {
            this.callbacks.onSelect = callback;
        }

        /**
         * Set callback for visibility changes
         * @param {Function} callback - (layerId, isVisible, layerData) => void
         */
        onVisibilityChange(callback) {
            this.callbacks.onVisibilityChange = callback;
        }

        /**
         * Set callback for lock changes
         * @param {Function} callback - (layerId, isLocked, layerData) => void
         */
        onLockChange(callback) {
            this.callbacks.onLockChange = callback;
        }

        /**
         * Set callback for reorder events
         * @param {Function} callback - (layerOrder) => void
         */
        onReorder(callback) {
            this.callbacks.onReorder = callback;
        }

        /**
         * Set callback for delete events
         * @param {Function} callback - (layerId) => void
         */
        onDelete(callback) {
            this.callbacks.onDelete = callback;
        }

        /**
         * Set callback for add layer events
         * @param {Function} callback - () => void
         */
        onAdd(callback) {
            this.callbacks.onAdd = callback;
        }

        // =====================================================================
        // Rendering
        // =====================================================================

        /**
         * Render the layer list
         */
        render() {
            const listEl = document.getElementById(this.options.listId);
            const emptyEl = document.getElementById(this.options.emptyId);

            if (!listEl) return;

            const sortedLayers = this.getSortedLayers();

            // Show/hide empty state
            if (emptyEl) {
                emptyEl.style.display = sortedLayers.length === 0 ? 'block' : 'none';
            }

            // Build layer list HTML
            listEl.innerHTML = sortedLayers.map(layer => this._renderLayerItem(layer)).join('');

            // Bind event handlers
            this._bindLayerItems(listEl);

            // Update control button states
            this._updateControlStates();
        }

        /**
         * Render a single layer item
         * @param {Object} layer - Layer data
         * @returns {string} HTML string
         * @private
         */
        _renderLayerItem(layer) {
            const isSelected = this.selectedLayerId === layer.id;
            const isVisible = layer.is_visible !== false;
            const isLocked = layer.is_locked === true;

            let html = LAYER_ITEM_TEMPLATE;

            // Replace placeholders
            html = html.replace('{id}', layer.id);
            html = html.replace('{visibleClass}', isVisible ? 'visible' : '');
            html = html.replace('{visibilityTitle}', isVisible ? 'Hide layer' : 'Show layer');
            html = html.replace('{visibilityIcon}', isVisible ? '&#128065;' : '&#128064;');
            html = html.replace('{previewBg}', layer.background_color || '#1a1a24');
            html = html.replace('{name}', this._escapeHtml(layer.name || 'Unnamed'));
            html = html.replace('{width}', layer.width || 0);
            html = html.replace('{height}', layer.height || 0);
            html = html.replace('{lockedClass}', isLocked ? 'locked' : '');
            html = html.replace('{lockTitle}', isLocked ? 'Unlock layer' : 'Lock layer');
            html = html.replace('{lockIcon}', isLocked ? '&#128274;' : '&#128275;');

            // Add selected class if needed
            if (isSelected) {
                html = html.replace('class="layer-item"', 'class="layer-item selected"');
            }

            return html;
        }

        /**
         * Bind event handlers to layer items
         * @param {HTMLElement} listEl - Layer list element
         * @private
         */
        _bindLayerItems(listEl) {
            listEl.querySelectorAll('.layer-item').forEach(item => {
                const layerId = this._parseLayerId(item.dataset.layerId);

                // Click to select
                item.addEventListener('click', (e) => {
                    // Ignore clicks on action buttons
                    if (e.target.closest('[data-action]')) return;
                    this.selectLayer(layerId);
                });

                // Double-click to rename (future enhancement)
                item.addEventListener('dblclick', (e) => {
                    if (e.target.closest('[data-action]')) return;
                    // Could trigger rename modal here
                });

                // Visibility toggle
                const visBtn = item.querySelector('[data-action="toggle-visibility"]');
                if (visBtn) {
                    visBtn.addEventListener('click', (e) => {
                        e.stopPropagation();
                        this.toggleVisibility(layerId);
                    });
                    // Keyboard support for accessibility
                    visBtn.addEventListener('keydown', (e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                            e.preventDefault();
                            e.stopPropagation();
                            this.toggleVisibility(layerId);
                        }
                    });
                }

                // Lock toggle
                const lockBtn = item.querySelector('[data-action="toggle-lock"]');
                if (lockBtn) {
                    lockBtn.addEventListener('click', (e) => {
                        e.stopPropagation();
                        this.toggleLock(layerId);
                    });
                    // Keyboard support for accessibility
                    lockBtn.addEventListener('keydown', (e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                            e.preventDefault();
                            e.stopPropagation();
                            this.toggleLock(layerId);
                        }
                    });
                }
            });
        }

        /**
         * Update selection highlighting
         * @private
         */
        _updateSelection() {
            const listEl = document.getElementById(this.options.listId);
            if (!listEl) return;

            listEl.querySelectorAll('.layer-item').forEach(item => {
                const layerId = this._parseLayerId(item.dataset.layerId);
                item.classList.toggle('selected', layerId === this.selectedLayerId);
            });

            this._updateControlStates();
        }

        /**
         * Update control button states
         * @private
         */
        _updateControlStates() {
            const hasSelection = this.selectedLayerId !== null;
            const forwardBtn = document.getElementById(this.options.bringForwardId);
            const backwardBtn = document.getElementById(this.options.sendBackwardId);
            const deleteBtn = document.getElementById(this.options.deleteLayerId);

            // Check if layer can move forward or backward
            const canMoveForward = this._canMoveForward();
            const canMoveBackward = this._canMoveBackward();

            if (forwardBtn) {
                forwardBtn.disabled = !hasSelection || !canMoveForward;
                forwardBtn.style.opacity = (!hasSelection || !canMoveForward) ? '0.5' : '1';
                forwardBtn.style.cursor = (!hasSelection || !canMoveForward) ? 'not-allowed' : 'pointer';
            }
            if (backwardBtn) {
                backwardBtn.disabled = !hasSelection || !canMoveBackward;
                backwardBtn.style.opacity = (!hasSelection || !canMoveBackward) ? '0.5' : '1';
                backwardBtn.style.cursor = (!hasSelection || !canMoveBackward) ? 'not-allowed' : 'pointer';
            }
            if (deleteBtn) {
                deleteBtn.disabled = !hasSelection;
                deleteBtn.style.opacity = !hasSelection ? '0.5' : '1';
                deleteBtn.style.cursor = !hasSelection ? 'not-allowed' : 'pointer';
            }
        }

        /**
         * Check if selected layer can move forward (higher z-index)
         * @returns {boolean} True if layer can move forward
         * @private
         */
        _canMoveForward() {
            if (!this.selectedLayerId) return false;

            const layers = this.getSortedLayers();
            if (layers.length <= 1) return false;

            const currentIndex = layers.findIndex(l => l.id === this.selectedLayerId);
            // In descending sort, index 0 is highest z-index (front)
            return this.options.sortDescending ? currentIndex > 0 : currentIndex < layers.length - 1;
        }

        /**
         * Check if selected layer can move backward (lower z-index)
         * @returns {boolean} True if layer can move backward
         * @private
         */
        _canMoveBackward() {
            if (!this.selectedLayerId) return false;

            const layers = this.getSortedLayers();
            if (layers.length <= 1) return false;

            const currentIndex = layers.findIndex(l => l.id === this.selectedLayerId);
            // In descending sort, last index is lowest z-index (back)
            return this.options.sortDescending ? currentIndex < layers.length - 1 : currentIndex > 0;
        }

        // =====================================================================
        // Event Handlers
        // =====================================================================

        /**
         * Handle add layer button click
         * @private
         */
        _handleAdd() {
            if (this.callbacks.onAdd) {
                this.callbacks.onAdd();
            }
        }

        /**
         * Handle delete button click
         * @private
         */
        _handleDelete() {
            if (!this.selectedLayerId) return;

            if (this.callbacks.onDelete) {
                this.callbacks.onDelete(this.selectedLayerId);
            }
        }

        /**
         * Handle bring forward button click
         * @private
         */
        _handleBringForward() {
            if (!this.selectedLayerId) return;
            if (!this._canMoveForward()) return;

            const layers = this.getSortedLayers();
            const currentIndex = layers.findIndex(l => l.id === this.selectedLayerId);

            if (currentIndex < 0) return;

            // Determine which layer to swap with based on sort order
            const swapIndex = this.options.sortDescending ? currentIndex - 1 : currentIndex + 1;
            if (swapIndex < 0 || swapIndex >= layers.length) return;

            // Swap z_index with the adjacent layer
            const current = layers[currentIndex];
            const adjacent = layers[swapIndex];

            const tempZ = current.z_index;
            current.z_index = adjacent.z_index;
            adjacent.z_index = tempZ;

            this.render();
            this._triggerReorder();
        }

        /**
         * Handle send backward button click
         * @private
         */
        _handleSendBackward() {
            if (!this.selectedLayerId) return;
            if (!this._canMoveBackward()) return;

            const layers = this.getSortedLayers();
            const currentIndex = layers.findIndex(l => l.id === this.selectedLayerId);

            if (currentIndex < 0) return;

            // Determine which layer to swap with based on sort order
            const swapIndex = this.options.sortDescending ? currentIndex + 1 : currentIndex - 1;
            if (swapIndex < 0 || swapIndex >= layers.length) return;

            // Swap z_index with the adjacent layer
            const current = layers[currentIndex];
            const adjacent = layers[swapIndex];

            const tempZ = current.z_index;
            current.z_index = adjacent.z_index;
            adjacent.z_index = tempZ;

            this.render();
            this._triggerReorder();
        }

        /**
         * Normalize z-indexes to sequential values
         * @private
         */
        _normalizeZIndexes() {
            const layers = Array.from(this.layers.values())
                .sort((a, b) => (a.z_index || 0) - (b.z_index || 0));

            layers.forEach((layer, index) => {
                layer.z_index = index;
            });
        }

        /**
         * Trigger reorder callback with current layer order
         * @private
         */
        _triggerReorder() {
            if (this.callbacks.onReorder) {
                // Build ordered list with z_index values
                const sortedLayers = this.getSortedLayers();
                const layerOrder = sortedLayers.map((l, index) => ({
                    id: l.id,
                    z_index: l.z_index,
                    // Include display order (0 = top in UI)
                    displayOrder: index
                }));

                // Call callback with layer order and selected layer ID
                this.callbacks.onReorder(layerOrder, this.selectedLayerId);
            }
        }

        // =====================================================================
        // Utility Methods
        // =====================================================================

        /**
         * Parse layer ID (handle string/number)
         * @param {string} idStr - Layer ID string
         * @returns {number|string} Parsed layer ID
         * @private
         */
        _parseLayerId(idStr) {
            const parsed = parseInt(idStr, 10);
            return isNaN(parsed) ? idStr : parsed;
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
    }

    // =========================================================================
    // Export to Global Namespace
    // =========================================================================

    window.LayerPanel = LayerPanel;

})(window);

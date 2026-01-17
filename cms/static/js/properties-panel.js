/**
 * Skillz Media CMS - Properties Panel
 *
 * This module provides properties panel functionality for the layout designer:
 * - Position inputs (X, Y) with numeric validation
 * - Size inputs (W, H) with minimum constraints
 * - Opacity slider (0-100%) with real-time canvas preview
 * - Synchronized slider and number input for opacity
 * - Spectrum color picker with alpha/transparency support
 * - Background color and border color selection
 * - Numeric input handling with step increment/decrement
 * - Real-time updates with change callbacks
 * - Layer property synchronization
 * - Content mode toggle (Static/Playlist)
 * - Static content file selector with modal
 * - Content assignment API integration
 * - Playlist assignment UI with priority and trigger configuration
 * - Multiple playlist support per layer with trigger-based activation
 * - Playlist picker modal with add/remove functionality
 */

(function(window) {
    'use strict';

    // =========================================================================
    // Constants
    // =========================================================================

    /** Default options */
    const DEFAULT_OPTIONS = {
        // Panel elements
        panelId: 'properties-panel',
        noSelectionId: 'no-selection',
        layerPropertiesId: 'layer-properties',

        // Position/Size inputs
        xInputId: 'prop-x',
        yInputId: 'prop-y',
        widthInputId: 'prop-width',
        heightInputId: 'prop-height',

        // Opacity inputs
        opacitySliderId: 'prop-opacity',
        opacityValueId: 'prop-opacity-value',

        // Color picker inputs
        backgroundColorId: 'prop-background',
        borderColorId: 'prop-border-color',

        // Constraints
        minWidth: 20,
        minHeight: 20,
        maxWidth: null,  // Set dynamically from canvas size
        maxHeight: null, // Set dynamically from canvas size

        // Position constraints (relative to canvas)
        minX: 0,
        minY: 0,
        maxX: null,  // Set dynamically
        maxY: null,  // Set dynamically

        // Opacity constraints
        minOpacity: 0,
        maxOpacity: 100,

        // Input behavior
        stepSmall: 1,
        stepLarge: 10,
        debounceDelay: 100,

        // Color picker defaults
        defaultBackgroundColor: 'transparent',
        defaultBorderColor: '#333333',

        // Content assignment
        contentModeTabsClass: 'content-mode-tabs',
        contentModeTabClass: 'content-mode-tab',
        contentStaticId: 'content-static',
        contentPlaylistId: 'content-playlist',
        contentFilePickerId: 'content-file-picker',
        contentPlaylistPickerId: 'content-playlist-picker',

        // Content API endpoint (set dynamically)
        contentApiEndpoint: '/api/v1/content'
    };

    /** Spectrum color picker default settings */
    const SPECTRUM_DEFAULTS = {
        showAlpha: true,
        showInput: true,
        showInitial: true,
        showPalette: true,
        showSelectionPalette: true,
        maxSelectionSize: 10,
        preferredFormat: 'rgb',
        allowEmpty: true,
        palette: [
            ['#000000', '#333333', '#666666', '#999999', '#cccccc', '#ffffff'],
            ['#ff0000', '#ff6600', '#ffcc00', '#00ff00', '#0066ff', '#9900ff'],
            ['#ff6666', '#ffcc66', '#ffff66', '#66ff66', '#66ccff', '#cc66ff'],
            ['rgba(0,0,0,0)', 'rgba(255,255,255,0.5)', 'rgba(0,212,170,1)', 'rgba(102,126,234,1)']
        ],
        localStorageKey: 'skillz.spectrum.colors'
    };

    /** Key codes for special handling */
    const KEY_CODES = {
        UP: 'ArrowUp',
        DOWN: 'ArrowDown',
        ENTER: 'Enter',
        ESCAPE: 'Escape',
        TAB: 'Tab'
    };

    /** Content mode options */
    const CONTENT_MODES = {
        STATIC: 'static',
        PLAYLIST: 'playlist'
    };

    /** Trigger types for playlist assignments (matches backend LAYER_TRIGGER_TYPES) */
    const TRIGGER_TYPES = {
        DEFAULT: 'default',
        FACE_DETECTED: 'face_detected',
        AGE_CHILD: 'age_child',
        AGE_TEEN: 'age_teen',
        AGE_ADULT: 'age_adult',
        AGE_SENIOR: 'age_senior',
        GENDER_MALE: 'gender_male',
        GENDER_FEMALE: 'gender_female',
        LOYALTY_RECOGNIZED: 'loyalty_recognized',
        NCMEC_ALERT: 'ncmec_alert'
    };

    /** Trigger type labels for display */
    const TRIGGER_TYPE_LABELS = {
        'default': 'Default (Always)',
        'face_detected': 'Face Detected',
        'age_child': 'Child (0-12)',
        'age_teen': 'Teen (13-19)',
        'age_adult': 'Adult (20-64)',
        'age_senior': 'Senior (65+)',
        'gender_male': 'Male',
        'gender_female': 'Female',
        'loyalty_recognized': 'Loyalty Member',
        'ncmec_alert': 'NCMEC Alert'
    };

    /** Supported file types for static content */
    const SUPPORTED_FILE_TYPES = {
        video: ['mp4', 'mov', 'avi', 'mkv', 'webm', 'm4v', 'wmv', 'flv'],
        image: ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'svg', 'tiff'],
        document: ['pdf']
    };

    /** Get file type category from mime type */
    function getFileCategory(mimeType) {
        if (!mimeType) return 'unknown';
        if (mimeType.startsWith('video/')) return 'video';
        if (mimeType.startsWith('image/')) return 'image';
        if (mimeType === 'application/pdf') return 'document';
        return 'unknown';
    }

    /** Get file icon based on mime type */
    function getFileIcon(mimeType) {
        const category = getFileCategory(mimeType);
        switch (category) {
            case 'video': return '🎬';
            case 'image': return '🖼️';
            case 'document': return '📄';
            default: return '📁';
        }
    }

    /** Format file size in human-readable format */
    function formatFileSize(bytes) {
        if (!bytes) return '0 B';
        const units = ['B', 'KB', 'MB', 'GB'];
        let unitIndex = 0;
        let size = bytes;
        while (size >= 1024 && unitIndex < units.length - 1) {
            size /= 1024;
            unitIndex++;
        }
        return `${size.toFixed(1)} ${units[unitIndex]}`;
    }

    /** Format duration in human-readable format */
    function formatDuration(seconds) {
        if (!seconds) return '';
        const mins = Math.floor(seconds / 60);
        const secs = Math.floor(seconds % 60);
        return `${mins}:${secs.toString().padStart(2, '0')}`;
    }

    // =========================================================================
    // PropertiesPanel Class
    // =========================================================================

    /**
     * PropertiesPanel manages the layer properties UI
     * @class
     */
    class PropertiesPanel {
        /**
         * Create a PropertiesPanel instance
         * @param {Object} options - Configuration options
         */
        constructor(options = {}) {
            this.options = { ...DEFAULT_OPTIONS, ...options };
            this.selectedLayer = null;
            this.callbacks = {
                onPositionChange: null,
                onSizeChange: null,
                onOpacityChange: null,
                onBackgroundColorChange: null,
                onBorderColorChange: null,
                onChange: null,
                onContentModeChange: null,
                onStaticContentSelect: null,
                onStaticContentClear: null,
                onPlaylistAdd: null,
                onPlaylistRemove: null,
                onPlaylistUpdate: null
            };
            this.debounceTimers = {};
            this.inputs = {};
            this.isUpdatingFromExternal = false;

            // Content assignment state
            this.contentMode = CONTENT_MODES.STATIC;
            this.selectedContent = null;
            this.availableContent = [];
            this.filePickerModal = null;

            // Playlist assignment state
            this.availablePlaylists = [];
            this.assignedPlaylists = [];
            this.playlistPickerModal = null;

            this._init();
        }

        // =====================================================================
        // Initialization
        // =====================================================================

        /**
         * Initialize the properties panel
         * @private
         */
        _init() {
            this._cacheElements();
            this._bindInputs();
            this._bindContentAssignment();
            this._createFilePickerModal();
            this._createPlaylistPickerModal();
        }

        /**
         * Cache DOM element references
         * @private
         */
        _cacheElements() {
            this.elements = {
                panel: document.getElementById(this.options.panelId),
                noSelection: document.getElementById(this.options.noSelectionId),
                layerProperties: document.getElementById(this.options.layerPropertiesId)
            };

            // Cache input elements
            this.inputs = {
                x: document.getElementById(this.options.xInputId),
                y: document.getElementById(this.options.yInputId),
                width: document.getElementById(this.options.widthInputId),
                height: document.getElementById(this.options.heightInputId),
                opacitySlider: document.getElementById(this.options.opacitySliderId),
                opacityValue: document.getElementById(this.options.opacityValueId),
                backgroundColor: document.getElementById(this.options.backgroundColorId),
                borderColor: document.getElementById(this.options.borderColorId)
            };

            // Color picker instances (will be set after Spectrum init)
            this.colorPickers = {
                background: null,
                border: null
            };

            // Content assignment elements
            this.contentElements = {
                modeTabs: document.querySelector('.' + this.options.contentModeTabsClass),
                staticContainer: document.getElementById(this.options.contentStaticId),
                playlistContainer: document.getElementById(this.options.contentPlaylistId),
                filePicker: document.getElementById(this.options.contentFilePickerId),
                playlistPicker: document.getElementById(this.options.contentPlaylistPickerId)
            };
        }

        /**
         * Bind event handlers to input elements
         * @private
         */
        _bindInputs() {
            // Position inputs
            if (this.inputs.x) {
                this._bindNumericInput(this.inputs.x, 'x', {
                    min: this.options.minX,
                    max: this.options.maxX,
                    onChange: (value) => this._handlePositionChange('x', value)
                });
            }

            if (this.inputs.y) {
                this._bindNumericInput(this.inputs.y, 'y', {
                    min: this.options.minY,
                    max: this.options.maxY,
                    onChange: (value) => this._handlePositionChange('y', value)
                });
            }

            // Size inputs
            if (this.inputs.width) {
                this._bindNumericInput(this.inputs.width, 'width', {
                    min: this.options.minWidth,
                    max: this.options.maxWidth,
                    onChange: (value) => this._handleSizeChange('width', value)
                });
            }

            if (this.inputs.height) {
                this._bindNumericInput(this.inputs.height, 'height', {
                    min: this.options.minHeight,
                    max: this.options.maxHeight,
                    onChange: (value) => this._handleSizeChange('height', value)
                });
            }

            // Opacity inputs
            this._bindOpacityInputs();

            // Color picker inputs (requires jQuery and Spectrum.js)
            this._initColorPickers();
        }

        /**
         * Bind opacity slider and value input handlers
         * @private
         */
        _bindOpacityInputs() {
            const slider = this.inputs.opacitySlider;
            const valueInput = this.inputs.opacityValue;

            if (!slider || !valueInput) return;

            // Slider input event - real-time updates with canvas preview
            slider.addEventListener('input', (e) => {
                if (this.isUpdatingFromExternal) return;

                const value = parseInt(e.target.value, 10);
                valueInput.value = value;

                // Trigger real-time opacity change
                this._handleOpacityChange(value);
            });

            // Value input event - numeric input with debouncing
            valueInput.addEventListener('input', (e) => {
                if (this.isUpdatingFromExternal) return;

                // Clear any existing debounce timer
                if (this.debounceTimers.opacity) {
                    clearTimeout(this.debounceTimers.opacity);
                }

                // Debounce the change callback
                this.debounceTimers.opacity = setTimeout(() => {
                    const value = this._parseAndValidate(
                        valueInput.value,
                        this.options.minOpacity,
                        this.options.maxOpacity
                    );
                    if (value !== null) {
                        valueInput.value = value;
                        slider.value = value;
                        this._handleOpacityChange(value);
                    }
                }, this.options.debounceDelay);
            });

            // Value input blur - final validation
            valueInput.addEventListener('blur', (e) => {
                if (this.isUpdatingFromExternal) return;

                // Clear any pending debounce
                if (this.debounceTimers.opacity) {
                    clearTimeout(this.debounceTimers.opacity);
                    this.debounceTimers.opacity = null;
                }

                const value = this._parseAndValidate(
                    valueInput.value,
                    this.options.minOpacity,
                    this.options.maxOpacity
                );
                if (value !== null) {
                    valueInput.value = value;
                    slider.value = value;
                    this._handleOpacityChange(value);
                } else {
                    // Revert to previous valid value
                    this._restoreOpacityValue();
                }
            });

            // Value input keydown - arrow key increment/decrement
            valueInput.addEventListener('keydown', (e) => {
                if (this.isUpdatingFromExternal) return;

                const step = e.shiftKey ? this.options.stepLarge : this.options.stepSmall;
                let handled = false;

                switch (e.key) {
                    case KEY_CODES.UP:
                        e.preventDefault();
                        this._incrementOpacity(step);
                        handled = true;
                        break;

                    case KEY_CODES.DOWN:
                        e.preventDefault();
                        this._incrementOpacity(-step);
                        handled = true;
                        break;

                    case KEY_CODES.ENTER:
                        e.preventDefault();
                        valueInput.blur();
                        break;

                    case KEY_CODES.ESCAPE:
                        e.preventDefault();
                        this._restoreOpacityValue();
                        valueInput.blur();
                        break;
                }

                if (handled) {
                    this._handleOpacityChange(parseInt(valueInput.value, 10));
                }
            });

            // Prevent non-numeric input in value field
            valueInput.addEventListener('keypress', (e) => {
                if (e.ctrlKey || e.metaKey) return;
                if (['Tab', 'Enter', 'Escape', 'Backspace', 'Delete'].includes(e.key)) return;
                if (e.key.startsWith('Arrow')) return;
                if (!/\d/.test(e.key)) {
                    e.preventDefault();
                }
            });
        }

        /**
         * Increment opacity value by step
         * @param {number} delta - Amount to change (+/-)
         * @private
         */
        _incrementOpacity(delta) {
            const current = parseInt(this.inputs.opacityValue.value, 10) || 0;
            const newValue = this._parseAndValidate(
                current + delta,
                this.options.minOpacity,
                this.options.maxOpacity
            );

            if (newValue !== null) {
                this.inputs.opacityValue.value = newValue;
                this.inputs.opacitySlider.value = newValue;
            }
        }

        /**
         * Restore opacity inputs to previously stored valid value
         * @private
         */
        _restoreOpacityValue() {
            if (this.selectedLayer) {
                const opacity = this.selectedLayer.opacity !== undefined
                    ? Math.round(this.selectedLayer.opacity * 100)
                    : 100;
                this.inputs.opacityValue.value = opacity;
                this.inputs.opacitySlider.value = opacity;
            }
        }

        // =====================================================================
        // Color Picker Initialization (Spectrum.js)
        // =====================================================================

        /**
         * Initialize Spectrum color pickers with alpha support
         * @private
         */
        _initColorPickers() {
            // Check if jQuery and Spectrum are available
            if (typeof jQuery === 'undefined' || typeof jQuery.fn.spectrum === 'undefined') {
                // Retry after a short delay (in case scripts are still loading)
                setTimeout(() => this._initColorPickers(), 100);
                return;
            }

            // Initialize background color picker
            this._initBackgroundColorPicker();

            // Initialize border color picker
            this._initBorderColorPicker();
        }

        /**
         * Initialize background color picker with alpha support
         * @private
         */
        _initBackgroundColorPicker() {
            const input = this.inputs.backgroundColor;
            if (!input) return;

            const self = this;
            const $input = jQuery(input);

            // Initialize Spectrum with alpha support
            $input.spectrum({
                ...SPECTRUM_DEFAULTS,
                color: this.options.defaultBackgroundColor,
                allowEmpty: true,
                showAlpha: true,
                preferredFormat: 'rgb',

                // Color change event (fires on every change)
                change: function(color) {
                    self._handleBackgroundColorChange(color);
                },

                // Move event (fires while dragging)
                move: function(color) {
                    if (!self.isUpdatingFromExternal) {
                        self._handleBackgroundColorChange(color, true);
                    }
                },

                // Hide event (fires when picker closes)
                hide: function(color) {
                    self._handleBackgroundColorChange(color);
                }
            });

            this.colorPickers.background = $input;
        }

        /**
         * Initialize border color picker with alpha support
         * @private
         */
        _initBorderColorPicker() {
            const input = this.inputs.borderColor;
            if (!input) return;

            const self = this;
            const $input = jQuery(input);

            // Initialize Spectrum with alpha support
            $input.spectrum({
                ...SPECTRUM_DEFAULTS,
                color: this.options.defaultBorderColor,
                allowEmpty: false,
                showAlpha: true,
                preferredFormat: 'rgb',

                // Color change event (fires on every change)
                change: function(color) {
                    self._handleBorderColorChange(color);
                },

                // Move event (fires while dragging)
                move: function(color) {
                    if (!self.isUpdatingFromExternal) {
                        self._handleBorderColorChange(color, true);
                    }
                },

                // Hide event (fires when picker closes)
                hide: function(color) {
                    self._handleBorderColorChange(color);
                }
            });

            this.colorPickers.border = $input;
        }

        /**
         * Handle background color change from picker
         * @param {tinycolor} color - Spectrum color object
         * @param {boolean} isPreview - If true, this is a preview during drag
         * @private
         */
        _handleBackgroundColorChange(color, isPreview = false) {
            if (!this.selectedLayer || this.isUpdatingFromExternal) return;

            // Get RGBA string (or 'transparent' if empty)
            const colorValue = this._colorToRgbaString(color);

            // Update local layer data
            this.selectedLayer.background_color = colorValue;

            // Extract alpha for background_opacity (if applicable)
            if (color) {
                this.selectedLayer.background_opacity = color.getAlpha();
            } else {
                this.selectedLayer.background_opacity = 0;
            }

            // Trigger background color change callback
            if (this.callbacks.onBackgroundColorChange) {
                this.callbacks.onBackgroundColorChange({
                    layerId: this.selectedLayer.id,
                    color: colorValue,
                    rgba: color ? color.toRgb() : null,
                    alpha: color ? color.getAlpha() : 0,
                    isPreview: isPreview
                });
            }

            // Trigger generic change callback (only for final changes)
            if (!isPreview) {
                this._triggerChange('background_color', colorValue);
            }
        }

        /**
         * Handle border color change from picker
         * @param {tinycolor} color - Spectrum color object
         * @param {boolean} isPreview - If true, this is a preview during drag
         * @private
         */
        _handleBorderColorChange(color, isPreview = false) {
            if (!this.selectedLayer || this.isUpdatingFromExternal) return;

            // Get RGBA string
            const colorValue = this._colorToRgbaString(color) || this.options.defaultBorderColor;

            // Update local layer data
            this.selectedLayer.border_color = colorValue;

            // Trigger border color change callback
            if (this.callbacks.onBorderColorChange) {
                this.callbacks.onBorderColorChange({
                    layerId: this.selectedLayer.id,
                    color: colorValue,
                    rgba: color ? color.toRgb() : null,
                    alpha: color ? color.getAlpha() : 1,
                    isPreview: isPreview
                });
            }

            // Trigger generic change callback (only for final changes)
            if (!isPreview) {
                this._triggerChange('border_color', colorValue);
            }
        }

        /**
         * Convert Spectrum color to RGBA string
         * @param {tinycolor|null} color - Spectrum color object
         * @returns {string} RGBA color string or 'transparent'
         * @private
         */
        _colorToRgbaString(color) {
            if (!color) {
                return 'transparent';
            }

            const alpha = color.getAlpha();

            // If fully transparent, return 'transparent'
            if (alpha === 0) {
                return 'transparent';
            }

            // Return RGBA string for colors with alpha
            const rgb = color.toRgb();
            if (alpha < 1) {
                return `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, ${alpha})`;
            }

            // Return RGB for fully opaque colors
            return color.toRgbString();
        }

        /**
         * Parse a color string to a format Spectrum can use
         * @param {string} colorStr - Color string (hex, rgb, rgba, transparent)
         * @returns {string|null} Color value or null for transparent
         * @private
         */
        _parseColorString(colorStr) {
            if (!colorStr || colorStr === 'transparent' || colorStr === 'none') {
                return null;
            }
            return colorStr;
        }

        // =====================================================================
        // Content Assignment
        // =====================================================================

        /**
         * Bind content assignment event handlers
         * @private
         */
        _bindContentAssignment() {
            // Bind content mode tabs
            if (this.contentElements.modeTabs) {
                const tabs = this.contentElements.modeTabs.querySelectorAll('.' + this.options.contentModeTabClass);
                tabs.forEach(tab => {
                    tab.addEventListener('click', (e) => {
                        const mode = e.target.dataset.mode;
                        if (mode) {
                            this._setContentMode(mode);
                        }
                    });
                });
            }

            // Bind static file picker click
            if (this.contentElements.filePicker) {
                this.contentElements.filePicker.addEventListener('click', () => {
                    this._openFilePicker();
                });
            }

            // Bind playlist picker click
            if (this.contentElements.playlistPicker) {
                this.contentElements.playlistPicker.addEventListener('click', () => {
                    this._openPlaylistPicker();
                });
            }
        }

        /**
         * Create the file picker modal dynamically
         * @private
         */
        _createFilePickerModal() {
            // Check if modal already exists
            if (document.getElementById('file-picker-modal')) {
                this.filePickerModal = document.getElementById('file-picker-modal');
                return;
            }

            // Create modal HTML
            const modal = document.createElement('div');
            modal.id = 'file-picker-modal';
            modal.className = 'modal file-picker-modal';
            modal.innerHTML = `
                <div class="modal-content file-picker-content">
                    <div class="modal-header">
                        <h3 class="modal-title">Select Content</h3>
                        <button class="close-btn" type="button">&times;</button>
                    </div>
                    <div class="modal-body">
                        <div class="file-picker-toolbar">
                            <div class="file-picker-search">
                                <input type="text" id="file-picker-search" class="property-input" placeholder="Search files...">
                            </div>
                            <div class="file-picker-filters">
                                <button class="filter-btn active" data-filter="all">All</button>
                                <button class="filter-btn" data-filter="image">Images</button>
                                <button class="filter-btn" data-filter="video">Videos</button>
                                <button class="filter-btn" data-filter="document">PDFs</button>
                            </div>
                        </div>
                        <div class="file-picker-grid" id="file-picker-grid">
                            <div class="file-picker-loading">Loading content...</div>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button class="btn btn-secondary" id="file-picker-clear">Clear Selection</button>
                        <button class="btn btn-primary" id="file-picker-select" disabled>Select</button>
                    </div>
                </div>
            `;

            // Add modal styles if not already present
            this._addFilePickerStyles();

            // Append to body
            document.body.appendChild(modal);
            this.filePickerModal = modal;

            // Bind modal events
            this._bindFilePickerEvents();
        }

        /**
         * Add CSS styles for the file picker modal
         * @private
         */
        _addFilePickerStyles() {
            if (document.getElementById('file-picker-styles')) return;

            const styles = document.createElement('style');
            styles.id = 'file-picker-styles';
            styles.textContent = `
                .file-picker-modal .modal-content {
                    max-width: 800px;
                    max-height: 80vh;
                    display: flex;
                    flex-direction: column;
                }
                .file-picker-modal .modal-header {
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    padding: 16px 20px;
                    border-bottom: 1px solid #333;
                }
                .file-picker-modal .modal-title {
                    margin: 0;
                    color: #fff;
                    font-size: 18px;
                    font-weight: 600;
                }
                .file-picker-modal .close-btn {
                    background: none;
                    border: none;
                    color: #888;
                    font-size: 24px;
                    cursor: pointer;
                    padding: 0;
                    line-height: 1;
                }
                .file-picker-modal .close-btn:hover {
                    color: #fff;
                }
                .file-picker-modal .modal-body {
                    flex: 1;
                    overflow: hidden;
                    display: flex;
                    flex-direction: column;
                    padding: 16px 20px;
                }
                .file-picker-toolbar {
                    display: flex;
                    gap: 12px;
                    margin-bottom: 16px;
                    flex-wrap: wrap;
                }
                .file-picker-search {
                    flex: 1;
                    min-width: 200px;
                }
                .file-picker-search input {
                    width: 100%;
                }
                .file-picker-filters {
                    display: flex;
                    gap: 4px;
                }
                .filter-btn {
                    padding: 8px 12px;
                    background: rgba(255, 255, 255, 0.05);
                    border: 1px solid #333;
                    border-radius: 6px;
                    color: #888;
                    font-size: 12px;
                    cursor: pointer;
                    transition: all 0.2s;
                }
                .filter-btn:hover {
                    background: rgba(255, 255, 255, 0.1);
                    color: #fff;
                }
                .filter-btn.active {
                    background: rgba(0, 212, 170, 0.15);
                    border-color: #00D4AA;
                    color: #00D4AA;
                }
                .file-picker-grid {
                    flex: 1;
                    overflow-y: auto;
                    display: grid;
                    grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
                    gap: 12px;
                    padding-right: 8px;
                }
                .file-picker-loading {
                    grid-column: 1 / -1;
                    text-align: center;
                    color: #666;
                    padding: 40px 20px;
                }
                .file-picker-empty {
                    grid-column: 1 / -1;
                    text-align: center;
                    color: #666;
                    padding: 40px 20px;
                }
                .file-picker-item {
                    background: rgba(255, 255, 255, 0.03);
                    border: 2px solid transparent;
                    border-radius: 8px;
                    padding: 8px;
                    cursor: pointer;
                    transition: all 0.2s;
                }
                .file-picker-item:hover {
                    background: rgba(255, 255, 255, 0.06);
                    border-color: #333;
                }
                .file-picker-item.selected {
                    background: rgba(0, 212, 170, 0.1);
                    border-color: #00D4AA;
                }
                .file-picker-thumb {
                    width: 100%;
                    aspect-ratio: 16/9;
                    background: #1a1a24;
                    border-radius: 4px;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    overflow: hidden;
                    margin-bottom: 8px;
                }
                .file-picker-thumb img {
                    width: 100%;
                    height: 100%;
                    object-fit: cover;
                }
                .file-picker-thumb-icon {
                    font-size: 32px;
                    opacity: 0.6;
                }
                .file-picker-name {
                    color: #fff;
                    font-size: 12px;
                    white-space: nowrap;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    margin-bottom: 4px;
                }
                .file-picker-meta {
                    color: #666;
                    font-size: 11px;
                    display: flex;
                    justify-content: space-between;
                }
                .file-picker-modal .modal-footer {
                    display: flex;
                    justify-content: flex-end;
                    gap: 8px;
                    padding: 16px 20px;
                    border-top: 1px solid #333;
                }
                .file-picker-modal .btn {
                    padding: 10px 20px;
                    border-radius: 6px;
                    font-size: 14px;
                    font-weight: 500;
                    cursor: pointer;
                    transition: all 0.2s;
                }
                .file-picker-modal .btn-secondary {
                    background: rgba(255, 255, 255, 0.05);
                    border: 1px solid #333;
                    color: #888;
                }
                .file-picker-modal .btn-secondary:hover {
                    background: rgba(255, 255, 255, 0.1);
                    color: #fff;
                }
                .file-picker-modal .btn-primary {
                    background: linear-gradient(135deg, #00D4AA 0%, #00B090 100%);
                    border: none;
                    color: #050508;
                }
                .file-picker-modal .btn-primary:hover:not(:disabled) {
                    transform: translateY(-1px);
                    box-shadow: 0 4px 12px rgba(0, 212, 170, 0.3);
                }
                .file-picker-modal .btn-primary:disabled {
                    opacity: 0.5;
                    cursor: not-allowed;
                }
                /* Content preview in properties panel */
                .content-preview.has-content {
                    padding: 12px;
                    text-align: left;
                }
                .content-preview-info {
                    display: flex;
                    align-items: center;
                    gap: 12px;
                }
                .content-preview-thumb {
                    width: 60px;
                    height: 45px;
                    background: #1a1a24;
                    border-radius: 4px;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    overflow: hidden;
                    flex-shrink: 0;
                }
                .content-preview-thumb img {
                    width: 100%;
                    height: 100%;
                    object-fit: cover;
                }
                .content-preview-thumb-icon {
                    font-size: 24px;
                    opacity: 0.6;
                }
                .content-preview-details {
                    flex: 1;
                    min-width: 0;
                }
                .content-preview-name {
                    color: #fff;
                    font-size: 13px;
                    white-space: nowrap;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    margin-bottom: 4px;
                }
                .content-preview-meta {
                    color: #666;
                    font-size: 11px;
                }
                .content-preview-clear {
                    background: none;
                    border: none;
                    color: #666;
                    font-size: 16px;
                    cursor: pointer;
                    padding: 4px;
                    transition: color 0.2s;
                }
                .content-preview-clear:hover {
                    color: #ff6b6b;
                }
            `;
            document.head.appendChild(styles);
        }

        /**
         * Bind file picker modal events
         * @private
         */
        _bindFilePickerEvents() {
            if (!this.filePickerModal) return;

            const self = this;

            // Close button
            const closeBtn = this.filePickerModal.querySelector('.close-btn');
            if (closeBtn) {
                closeBtn.addEventListener('click', () => this._closeFilePicker());
            }

            // Backdrop click
            this.filePickerModal.addEventListener('click', (e) => {
                if (e.target === this.filePickerModal) {
                    this._closeFilePicker();
                }
            });

            // Search input
            const searchInput = this.filePickerModal.querySelector('#file-picker-search');
            if (searchInput) {
                searchInput.addEventListener('input', () => {
                    this._filterFilePickerContent();
                });
            }

            // Filter buttons
            const filterBtns = this.filePickerModal.querySelectorAll('.filter-btn');
            filterBtns.forEach(btn => {
                btn.addEventListener('click', (e) => {
                    filterBtns.forEach(b => b.classList.remove('active'));
                    e.target.classList.add('active');
                    this._filterFilePickerContent();
                });
            });

            // Clear button
            const clearBtn = this.filePickerModal.querySelector('#file-picker-clear');
            if (clearBtn) {
                clearBtn.addEventListener('click', () => {
                    this._clearContentSelection();
                    this._closeFilePicker();
                });
            }

            // Select button
            const selectBtn = this.filePickerModal.querySelector('#file-picker-select');
            if (selectBtn) {
                selectBtn.addEventListener('click', () => {
                    this._confirmContentSelection();
                });
            }

            // Escape key
            document.addEventListener('keydown', (e) => {
                if (e.key === 'Escape' && this.filePickerModal.classList.contains('active')) {
                    this._closeFilePicker();
                }
            });
        }

        /**
         * Set the content mode (static or playlist)
         * @param {string} mode - Content mode ('static' or 'playlist')
         * @private
         */
        _setContentMode(mode) {
            if (this.isUpdatingFromExternal) return;
            if (mode === this.contentMode) return;

            this.contentMode = mode;

            // Update tab UI
            if (this.contentElements.modeTabs) {
                const tabs = this.contentElements.modeTabs.querySelectorAll('.' + this.options.contentModeTabClass);
                tabs.forEach(tab => {
                    tab.classList.toggle('active', tab.dataset.mode === mode);
                });
            }

            // Show/hide content containers
            if (this.contentElements.staticContainer) {
                this.contentElements.staticContainer.style.display = mode === CONTENT_MODES.STATIC ? 'block' : 'none';
            }
            if (this.contentElements.playlistContainer) {
                this.contentElements.playlistContainer.style.display = mode === CONTENT_MODES.PLAYLIST ? 'block' : 'none';
            }

            // Trigger callback
            if (this.callbacks.onContentModeChange && this.selectedLayer) {
                this.callbacks.onContentModeChange({
                    layerId: this.selectedLayer.id,
                    mode: mode
                });
            }
        }

        /**
         * Open the file picker modal
         * @private
         */
        _openFilePicker() {
            if (!this.filePickerModal || !this.selectedLayer) return;

            // Show modal
            this.filePickerModal.classList.add('active');
            document.body.style.overflow = 'hidden';

            // Load content if not already loaded
            this._loadAvailableContent();
        }

        /**
         * Close the file picker modal
         * @private
         */
        _closeFilePicker() {
            if (!this.filePickerModal) return;

            this.filePickerModal.classList.remove('active');
            document.body.style.overflow = '';

            // Clear search
            const searchInput = this.filePickerModal.querySelector('#file-picker-search');
            if (searchInput) {
                searchInput.value = '';
            }
        }

        /**
         * Load available content from API
         * @private
         */
        async _loadAvailableContent() {
            const grid = this.filePickerModal.querySelector('#file-picker-grid');
            if (!grid) return;

            // Show loading state
            grid.innerHTML = '<div class="file-picker-loading">Loading content...</div>';

            try {
                const response = await fetch(this.options.contentApiEndpoint);
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}`);
                }

                const data = await response.json();
                this.availableContent = data.content || data || [];

                // Render content grid
                this._renderFilePickerGrid();
            } catch (error) {
                grid.innerHTML = `<div class="file-picker-empty">Failed to load content: ${error.message}</div>`;
            }
        }

        /**
         * Render the file picker grid with content items
         * @private
         */
        _renderFilePickerGrid() {
            const grid = this.filePickerModal.querySelector('#file-picker-grid');
            if (!grid) return;

            const content = this._getFilteredContent();

            if (content.length === 0) {
                grid.innerHTML = '<div class="file-picker-empty">No content found</div>';
                return;
            }

            grid.innerHTML = content.map(item => {
                const category = getFileCategory(item.mime_type);
                const icon = getFileIcon(item.mime_type);
                const selected = this.selectedContent && this.selectedContent.id === item.id;
                const thumbUrl = category === 'image' ? `/api/v1/content/${item.id}/download` : null;

                return `
                    <div class="file-picker-item${selected ? ' selected' : ''}" data-id="${item.id}">
                        <div class="file-picker-thumb">
                            ${thumbUrl
                                ? `<img src="${thumbUrl}" alt="${item.original_name}" loading="lazy">`
                                : `<span class="file-picker-thumb-icon">${icon}</span>`
                            }
                        </div>
                        <div class="file-picker-name" title="${item.original_name}">${item.original_name}</div>
                        <div class="file-picker-meta">
                            <span>${formatFileSize(item.file_size)}</span>
                            ${item.duration ? `<span>${formatDuration(item.duration)}</span>` : ''}
                        </div>
                    </div>
                `;
            }).join('');

            // Bind click events
            grid.querySelectorAll('.file-picker-item').forEach(item => {
                item.addEventListener('click', () => {
                    const contentId = item.dataset.id;
                    const contentData = this.availableContent.find(c => c.id === contentId);
                    this._selectContentItem(contentData, item);
                });

                // Double-click to select and close
                item.addEventListener('dblclick', () => {
                    const contentId = item.dataset.id;
                    const contentData = this.availableContent.find(c => c.id === contentId);
                    this._selectContentItem(contentData, item);
                    this._confirmContentSelection();
                });
            });
        }

        /**
         * Get filtered content based on search and filter
         * @returns {Array} Filtered content items
         * @private
         */
        _getFilteredContent() {
            let content = [...this.availableContent];

            // Apply search filter
            const searchInput = this.filePickerModal.querySelector('#file-picker-search');
            const searchTerm = searchInput ? searchInput.value.toLowerCase().trim() : '';

            if (searchTerm) {
                content = content.filter(item =>
                    item.original_name.toLowerCase().includes(searchTerm)
                );
            }

            // Apply type filter
            const activeFilter = this.filePickerModal.querySelector('.filter-btn.active');
            const filterType = activeFilter ? activeFilter.dataset.filter : 'all';

            if (filterType !== 'all') {
                content = content.filter(item => {
                    const category = getFileCategory(item.mime_type);
                    return category === filterType;
                });
            }

            return content;
        }

        /**
         * Filter file picker content based on search and type filter
         * @private
         */
        _filterFilePickerContent() {
            this._renderFilePickerGrid();
        }

        /**
         * Select a content item in the file picker
         * @param {Object} contentData - Content data object
         * @param {HTMLElement} itemElement - The clicked item element
         * @private
         */
        _selectContentItem(contentData, itemElement) {
            // Deselect previous
            const grid = this.filePickerModal.querySelector('#file-picker-grid');
            if (grid) {
                grid.querySelectorAll('.file-picker-item').forEach(item => {
                    item.classList.remove('selected');
                });
            }

            // Select new item
            if (itemElement) {
                itemElement.classList.add('selected');
            }

            this.selectedContent = contentData;

            // Enable select button
            const selectBtn = this.filePickerModal.querySelector('#file-picker-select');
            if (selectBtn) {
                selectBtn.disabled = !contentData;
            }
        }

        /**
         * Confirm the content selection and close modal
         * @private
         */
        _confirmContentSelection() {
            if (!this.selectedContent || !this.selectedLayer) {
                this._closeFilePicker();
                return;
            }

            // Update the preview in properties panel
            this._updateContentPreview(this.selectedContent);

            // Trigger callback
            if (this.callbacks.onStaticContentSelect) {
                this.callbacks.onStaticContentSelect({
                    layerId: this.selectedLayer.id,
                    content: this.selectedContent
                });
            }

            this._closeFilePicker();
        }

        /**
         * Clear the content selection
         * @private
         */
        _clearContentSelection() {
            this.selectedContent = null;

            // Update the preview in properties panel
            this._updateContentPreview(null);

            // Disable select button
            const selectBtn = this.filePickerModal.querySelector('#file-picker-select');
            if (selectBtn) {
                selectBtn.disabled = true;
            }

            // Trigger callback
            if (this.callbacks.onStaticContentClear && this.selectedLayer) {
                this.callbacks.onStaticContentClear({
                    layerId: this.selectedLayer.id
                });
            }
        }

        /**
         * Update the content preview in the properties panel
         * @param {Object|null} content - Content data or null to clear
         * @private
         */
        _updateContentPreview(content) {
            const picker = this.contentElements.filePicker;
            if (!picker) return;

            if (!content) {
                // Show empty state
                picker.classList.remove('has-content');
                picker.innerHTML = `
                    <div class="content-preview-icon">📁</div>
                    <div>Click to select file</div>
                `;
            } else {
                // Show content info
                const category = getFileCategory(content.mime_type);
                const icon = getFileIcon(content.mime_type);
                const thumbUrl = category === 'image' ? `/api/v1/content/${content.id}/download` : null;

                picker.classList.add('has-content');
                picker.innerHTML = `
                    <div class="content-preview-info">
                        <div class="content-preview-thumb">
                            ${thumbUrl
                                ? `<img src="${thumbUrl}" alt="${content.original_name}">`
                                : `<span class="content-preview-thumb-icon">${icon}</span>`
                            }
                        </div>
                        <div class="content-preview-details">
                            <div class="content-preview-name" title="${content.original_name}">${content.original_name}</div>
                            <div class="content-preview-meta">
                                ${formatFileSize(content.file_size)}
                                ${content.duration ? ` • ${formatDuration(content.duration)}` : ''}
                            </div>
                        </div>
                        <button class="content-preview-clear" type="button" title="Clear selection">&times;</button>
                    </div>
                `;

                // Bind clear button (stop propagation to prevent opening picker)
                const clearBtn = picker.querySelector('.content-preview-clear');
                if (clearBtn) {
                    clearBtn.addEventListener('click', (e) => {
                        e.stopPropagation();
                        this._clearContentSelection();
                    });
                }
            }
        }

        // =====================================================================
        // Playlist Picker Modal
        // =====================================================================

        /**
         * Create the playlist picker modal dynamically
         * @private
         */
        _createPlaylistPickerModal() {
            // Check if modal already exists
            if (document.getElementById('playlist-picker-modal')) {
                this.playlistPickerModal = document.getElementById('playlist-picker-modal');
                return;
            }

            // Create modal HTML
            const modal = document.createElement('div');
            modal.id = 'playlist-picker-modal';
            modal.className = 'modal playlist-picker-modal';
            modal.innerHTML = `
                <div class="modal-content playlist-picker-content">
                    <div class="modal-header">
                        <h3 class="modal-title">Manage Playlists</h3>
                        <button class="close-btn" type="button">&times;</button>
                    </div>
                    <div class="modal-body">
                        <div class="playlist-picker-sections">
                            <!-- Assigned Playlists Section -->
                            <div class="playlist-section assigned-section">
                                <div class="playlist-section-header">
                                    <span class="playlist-section-title">Assigned Playlists</span>
                                    <span class="playlist-count" id="assigned-playlist-count">0</span>
                                </div>
                                <div class="playlist-assigned-list" id="assigned-playlists-list">
                                    <div class="playlist-empty">No playlists assigned</div>
                                </div>
                            </div>

                            <!-- Add Playlist Section -->
                            <div class="playlist-section add-section">
                                <div class="playlist-section-header">
                                    <span class="playlist-section-title">Add Playlist</span>
                                </div>
                                <div class="playlist-add-form">
                                    <div class="playlist-form-row">
                                        <label class="playlist-form-label">Playlist</label>
                                        <select class="playlist-form-select" id="playlist-select">
                                            <option value="">Select a playlist...</option>
                                        </select>
                                    </div>
                                    <div class="playlist-form-row">
                                        <label class="playlist-form-label">Trigger</label>
                                        <select class="playlist-form-select" id="playlist-trigger-select">
                                            ${Object.entries(TRIGGER_TYPE_LABELS).map(([value, label]) =>
                                                `<option value="${value}">${label}</option>`
                                            ).join('')}
                                        </select>
                                    </div>
                                    <div class="playlist-form-row">
                                        <label class="playlist-form-label">Priority</label>
                                        <input type="number" class="playlist-form-input" id="playlist-priority-input" value="0" min="0" max="100">
                                        <span class="playlist-form-hint">Higher = more important</span>
                                    </div>
                                    <button class="btn btn-primary playlist-add-btn" id="playlist-add-btn" disabled>
                                        Add Playlist
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button class="btn btn-secondary" id="playlist-picker-close">Close</button>
                    </div>
                </div>
            `;

            // Add modal styles if not already present
            this._addPlaylistPickerStyles();

            // Append to body
            document.body.appendChild(modal);
            this.playlistPickerModal = modal;

            // Bind modal events
            this._bindPlaylistPickerEvents();
        }

        /**
         * Add CSS styles for the playlist picker modal
         * @private
         */
        _addPlaylistPickerStyles() {
            if (document.getElementById('playlist-picker-styles')) return;

            const styles = document.createElement('style');
            styles.id = 'playlist-picker-styles';
            styles.textContent = `
                .playlist-picker-modal .modal-content {
                    max-width: 600px;
                    max-height: 80vh;
                    display: flex;
                    flex-direction: column;
                }
                .playlist-picker-modal .modal-header {
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    padding: 16px 20px;
                    border-bottom: 1px solid #333;
                }
                .playlist-picker-modal .modal-title {
                    margin: 0;
                    color: #fff;
                    font-size: 18px;
                    font-weight: 600;
                }
                .playlist-picker-modal .close-btn {
                    background: none;
                    border: none;
                    color: #888;
                    font-size: 24px;
                    cursor: pointer;
                    padding: 0;
                    line-height: 1;
                }
                .playlist-picker-modal .close-btn:hover {
                    color: #fff;
                }
                .playlist-picker-modal .modal-body {
                    flex: 1;
                    overflow-y: auto;
                    padding: 16px 20px;
                }
                .playlist-picker-sections {
                    display: flex;
                    flex-direction: column;
                    gap: 20px;
                }
                .playlist-section {
                    background: rgba(255, 255, 255, 0.02);
                    border: 1px solid #333;
                    border-radius: 8px;
                    padding: 16px;
                }
                .playlist-section-header {
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    margin-bottom: 12px;
                }
                .playlist-section-title {
                    color: #fff;
                    font-size: 14px;
                    font-weight: 600;
                    text-transform: uppercase;
                    letter-spacing: 0.5px;
                }
                .playlist-count {
                    background: rgba(0, 212, 170, 0.15);
                    color: #00D4AA;
                    font-size: 12px;
                    font-weight: 600;
                    padding: 2px 8px;
                    border-radius: 10px;
                }
                .playlist-assigned-list {
                    display: flex;
                    flex-direction: column;
                    gap: 8px;
                    max-height: 200px;
                    overflow-y: auto;
                }
                .playlist-empty {
                    color: #666;
                    font-size: 13px;
                    text-align: center;
                    padding: 20px;
                }
                .playlist-assigned-item {
                    display: flex;
                    align-items: center;
                    gap: 12px;
                    padding: 12px;
                    background: rgba(255, 255, 255, 0.03);
                    border: 1px solid #333;
                    border-radius: 6px;
                    transition: all 0.2s;
                }
                .playlist-assigned-item:hover {
                    background: rgba(255, 255, 255, 0.05);
                    border-color: #444;
                }
                .playlist-item-icon {
                    width: 36px;
                    height: 36px;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    border-radius: 6px;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    font-size: 18px;
                    flex-shrink: 0;
                }
                .playlist-item-info {
                    flex: 1;
                    min-width: 0;
                }
                .playlist-item-name {
                    color: #fff;
                    font-size: 13px;
                    font-weight: 500;
                    white-space: nowrap;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    margin-bottom: 4px;
                }
                .playlist-item-meta {
                    display: flex;
                    gap: 12px;
                    flex-wrap: wrap;
                }
                .playlist-item-trigger,
                .playlist-item-priority {
                    color: #888;
                    font-size: 11px;
                }
                .playlist-item-trigger span,
                .playlist-item-priority span {
                    color: #00D4AA;
                }
                .playlist-item-actions {
                    display: flex;
                    gap: 4px;
                }
                .playlist-item-btn {
                    width: 28px;
                    height: 28px;
                    border-radius: 4px;
                    background: rgba(255, 255, 255, 0.05);
                    border: 1px solid #333;
                    color: #888;
                    font-size: 12px;
                    cursor: pointer;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    transition: all 0.2s;
                }
                .playlist-item-btn:hover {
                    background: rgba(255, 255, 255, 0.1);
                    color: #fff;
                }
                .playlist-item-btn.delete:hover {
                    background: rgba(255, 107, 107, 0.2);
                    border-color: #ff6b6b;
                    color: #ff6b6b;
                }
                .playlist-add-form {
                    display: flex;
                    flex-direction: column;
                    gap: 12px;
                }
                .playlist-form-row {
                    display: flex;
                    align-items: center;
                    gap: 12px;
                }
                .playlist-form-label {
                    width: 70px;
                    color: #888;
                    font-size: 12px;
                    flex-shrink: 0;
                }
                .playlist-form-select,
                .playlist-form-input {
                    flex: 1;
                    background: rgba(255, 255, 255, 0.05);
                    border: 1px solid #333;
                    border-radius: 6px;
                    color: #fff;
                    padding: 10px 12px;
                    font-size: 13px;
                }
                .playlist-form-select:focus,
                .playlist-form-input:focus {
                    outline: none;
                    border-color: #00D4AA;
                }
                .playlist-form-input[type="number"] {
                    width: 80px;
                    flex: 0 0 auto;
                }
                .playlist-form-hint {
                    color: #666;
                    font-size: 11px;
                    margin-left: 8px;
                }
                .playlist-add-btn {
                    margin-top: 8px;
                    align-self: flex-end;
                }
                .playlist-picker-modal .modal-footer {
                    display: flex;
                    justify-content: flex-end;
                    gap: 8px;
                    padding: 16px 20px;
                    border-top: 1px solid #333;
                }
                .playlist-picker-modal .btn {
                    padding: 10px 20px;
                    border-radius: 6px;
                    font-size: 14px;
                    font-weight: 500;
                    cursor: pointer;
                    transition: all 0.2s;
                }
                .playlist-picker-modal .btn-secondary {
                    background: rgba(255, 255, 255, 0.05);
                    border: 1px solid #333;
                    color: #888;
                }
                .playlist-picker-modal .btn-secondary:hover {
                    background: rgba(255, 255, 255, 0.1);
                    color: #fff;
                }
                .playlist-picker-modal .btn-primary {
                    background: linear-gradient(135deg, #00D4AA 0%, #00B090 100%);
                    border: none;
                    color: #050508;
                }
                .playlist-picker-modal .btn-primary:hover:not(:disabled) {
                    transform: translateY(-1px);
                    box-shadow: 0 4px 12px rgba(0, 212, 170, 0.3);
                }
                .playlist-picker-modal .btn-primary:disabled {
                    opacity: 0.5;
                    cursor: not-allowed;
                }
                /* Playlist preview in properties panel */
                .playlist-preview.has-playlists {
                    padding: 12px;
                    text-align: left;
                }
                .playlist-preview-list {
                    display: flex;
                    flex-direction: column;
                    gap: 6px;
                }
                .playlist-preview-item {
                    display: flex;
                    align-items: center;
                    gap: 8px;
                    padding: 8px;
                    background: rgba(255, 255, 255, 0.03);
                    border-radius: 4px;
                }
                .playlist-preview-icon {
                    width: 24px;
                    height: 24px;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    border-radius: 4px;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    font-size: 12px;
                    flex-shrink: 0;
                }
                .playlist-preview-name {
                    flex: 1;
                    color: #fff;
                    font-size: 12px;
                    white-space: nowrap;
                    overflow: hidden;
                    text-overflow: ellipsis;
                }
                .playlist-preview-badge {
                    font-size: 10px;
                    color: #888;
                    background: rgba(255, 255, 255, 0.05);
                    padding: 2px 6px;
                    border-radius: 3px;
                }
                .playlist-preview-more {
                    color: #666;
                    font-size: 11px;
                    text-align: center;
                    padding: 4px;
                }
            `;
            document.head.appendChild(styles);
        }

        /**
         * Bind playlist picker modal events
         * @private
         */
        _bindPlaylistPickerEvents() {
            if (!this.playlistPickerModal) return;

            // Close button
            const closeBtn = this.playlistPickerModal.querySelector('.close-btn');
            if (closeBtn) {
                closeBtn.addEventListener('click', () => this._closePlaylistPicker());
            }

            // Close button in footer
            const closeFooterBtn = this.playlistPickerModal.querySelector('#playlist-picker-close');
            if (closeFooterBtn) {
                closeFooterBtn.addEventListener('click', () => this._closePlaylistPicker());
            }

            // Backdrop click
            this.playlistPickerModal.addEventListener('click', (e) => {
                if (e.target === this.playlistPickerModal) {
                    this._closePlaylistPicker();
                }
            });

            // Playlist select change - enable/disable add button
            const playlistSelect = this.playlistPickerModal.querySelector('#playlist-select');
            if (playlistSelect) {
                playlistSelect.addEventListener('change', () => {
                    this._updateAddButtonState();
                });
            }

            // Add button click
            const addBtn = this.playlistPickerModal.querySelector('#playlist-add-btn');
            if (addBtn) {
                addBtn.addEventListener('click', () => {
                    this._addPlaylistAssignment();
                });
            }

            // Escape key
            document.addEventListener('keydown', (e) => {
                if (e.key === 'Escape' && this.playlistPickerModal.classList.contains('active')) {
                    this._closePlaylistPicker();
                }
            });
        }

        /**
         * Update the add button state based on selection
         * @private
         */
        _updateAddButtonState() {
            const playlistSelect = this.playlistPickerModal.querySelector('#playlist-select');
            const addBtn = this.playlistPickerModal.querySelector('#playlist-add-btn');

            if (playlistSelect && addBtn) {
                addBtn.disabled = !playlistSelect.value;
            }
        }

        /**
         * Open the playlist picker modal
         * @private
         */
        _openPlaylistPicker() {
            if (!this.playlistPickerModal || !this.selectedLayer) return;

            // Show modal
            this.playlistPickerModal.classList.add('active');
            document.body.style.overflow = 'hidden';

            // Load playlists and render
            this._loadAvailablePlaylists();
        }

        /**
         * Close the playlist picker modal
         * @private
         */
        _closePlaylistPicker() {
            if (!this.playlistPickerModal) return;

            this.playlistPickerModal.classList.remove('active');
            document.body.style.overflow = '';

            // Update preview in properties panel
            this._updatePlaylistPreview();
        }

        /**
         * Load available playlists from API
         * @private
         */
        async _loadAvailablePlaylists() {
            try {
                const response = await fetch('/api/v1/playlists');
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}`);
                }

                const data = await response.json();
                this.availablePlaylists = data.playlists || data || [];

                // Render the modal content
                this._renderPlaylistPickerContent();
            } catch (error) {
                this.availablePlaylists = [];
                this._renderPlaylistPickerContent();
            }
        }

        /**
         * Render the playlist picker modal content
         * @private
         */
        _renderPlaylistPickerContent() {
            // Update playlist select options
            const playlistSelect = this.playlistPickerModal.querySelector('#playlist-select');
            if (playlistSelect) {
                // Get IDs of already assigned playlists
                const assignedIds = new Set(this.assignedPlaylists.map(p => p.playlist_id));

                playlistSelect.innerHTML = '<option value="">Select a playlist...</option>';
                this.availablePlaylists.forEach(playlist => {
                    // Skip already assigned playlists
                    if (assignedIds.has(playlist.id)) return;

                    const option = document.createElement('option');
                    option.value = playlist.id;
                    option.textContent = playlist.name;
                    playlistSelect.appendChild(option);
                });
            }

            // Reset form
            const triggerSelect = this.playlistPickerModal.querySelector('#playlist-trigger-select');
            const priorityInput = this.playlistPickerModal.querySelector('#playlist-priority-input');

            if (triggerSelect) triggerSelect.value = 'default';
            if (priorityInput) priorityInput.value = '0';

            this._updateAddButtonState();

            // Render assigned playlists
            this._renderAssignedPlaylists();
        }

        /**
         * Render the assigned playlists list
         * @private
         */
        _renderAssignedPlaylists() {
            const listEl = this.playlistPickerModal.querySelector('#assigned-playlists-list');
            const countEl = this.playlistPickerModal.querySelector('#assigned-playlist-count');

            if (!listEl) return;

            // Update count
            if (countEl) {
                countEl.textContent = this.assignedPlaylists.length;
            }

            // Render list
            if (this.assignedPlaylists.length === 0) {
                listEl.innerHTML = '<div class="playlist-empty">No playlists assigned</div>';
                return;
            }

            // Sort by priority (descending)
            const sorted = [...this.assignedPlaylists].sort((a, b) => b.priority - a.priority);

            listEl.innerHTML = sorted.map(assignment => {
                // Find playlist details
                const playlist = this.availablePlaylists.find(p => p.id === assignment.playlist_id);
                const playlistName = playlist ? playlist.name : `Playlist ${assignment.playlist_id}`;
                const triggerLabel = TRIGGER_TYPE_LABELS[assignment.trigger_type] || assignment.trigger_type;

                return `
                    <div class="playlist-assigned-item" data-assignment-id="${assignment.id}">
                        <div class="playlist-item-icon">🎬</div>
                        <div class="playlist-item-info">
                            <div class="playlist-item-name" title="${playlistName}">${playlistName}</div>
                            <div class="playlist-item-meta">
                                <span class="playlist-item-trigger">Trigger: <span>${triggerLabel}</span></span>
                                <span class="playlist-item-priority">Priority: <span>${assignment.priority}</span></span>
                            </div>
                        </div>
                        <div class="playlist-item-actions">
                            <button class="playlist-item-btn delete" title="Remove" data-action="remove" data-id="${assignment.id}">
                                ✕
                            </button>
                        </div>
                    </div>
                `;
            }).join('');

            // Bind remove buttons
            listEl.querySelectorAll('.playlist-item-btn[data-action="remove"]').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    const id = e.currentTarget.dataset.id;
                    this._removePlaylistAssignment(id);
                });
            });
        }

        /**
         * Add a new playlist assignment
         * @private
         */
        _addPlaylistAssignment() {
            const playlistSelect = this.playlistPickerModal.querySelector('#playlist-select');
            const triggerSelect = this.playlistPickerModal.querySelector('#playlist-trigger-select');
            const priorityInput = this.playlistPickerModal.querySelector('#playlist-priority-input');

            if (!playlistSelect || !playlistSelect.value) return;

            const playlistId = playlistSelect.value;
            const triggerType = triggerSelect ? triggerSelect.value : 'default';
            const priority = priorityInput ? parseInt(priorityInput.value, 10) || 0 : 0;

            // Create new assignment (local only - API call happens via callback)
            const newAssignment = {
                id: `temp-${Date.now()}`,  // Temporary ID until API returns real ID
                playlist_id: playlistId,
                layer_id: this.selectedLayer.id,
                trigger_type: triggerType,
                priority: priority
            };

            // Add to local list
            this.assignedPlaylists.push(newAssignment);

            // Re-render
            this._renderPlaylistPickerContent();

            // Trigger callback
            if (this.callbacks.onPlaylistAdd && this.selectedLayer) {
                this.callbacks.onPlaylistAdd({
                    layerId: this.selectedLayer.id,
                    playlistId: playlistId,
                    triggerType: triggerType,
                    priority: priority,
                    assignment: newAssignment
                });
            }
        }

        /**
         * Remove a playlist assignment
         * @param {string} assignmentId - Assignment ID to remove
         * @private
         */
        _removePlaylistAssignment(assignmentId) {
            const index = this.assignedPlaylists.findIndex(a => a.id === assignmentId);
            if (index === -1) return;

            const removed = this.assignedPlaylists.splice(index, 1)[0];

            // Re-render
            this._renderPlaylistPickerContent();

            // Trigger callback
            if (this.callbacks.onPlaylistRemove && this.selectedLayer) {
                this.callbacks.onPlaylistRemove({
                    layerId: this.selectedLayer.id,
                    assignmentId: assignmentId,
                    playlistId: removed.playlist_id,
                    assignment: removed
                });
            }
        }

        /**
         * Update the playlist preview in the properties panel
         * @private
         */
        _updatePlaylistPreview() {
            const picker = this.contentElements.playlistPicker;
            if (!picker) return;

            if (this.assignedPlaylists.length === 0) {
                // Show empty state
                picker.classList.remove('has-playlists');
                picker.innerHTML = `
                    <div class="content-preview-icon">🎬</div>
                    <div>Click to assign playlists</div>
                `;
            } else {
                // Show playlist summary
                picker.classList.add('has-playlists');

                // Sort by priority (descending) and take top 2 for preview
                const sorted = [...this.assignedPlaylists].sort((a, b) => b.priority - a.priority);
                const preview = sorted.slice(0, 2);
                const remaining = sorted.length - 2;

                picker.innerHTML = `
                    <div class="playlist-preview-list">
                        ${preview.map(assignment => {
                            const playlist = this.availablePlaylists.find(p => p.id === assignment.playlist_id);
                            const name = playlist ? playlist.name : `Playlist`;
                            const triggerLabel = TRIGGER_TYPE_LABELS[assignment.trigger_type] || assignment.trigger_type;

                            return `
                                <div class="playlist-preview-item">
                                    <div class="playlist-preview-icon">🎬</div>
                                    <div class="playlist-preview-name" title="${name}">${name}</div>
                                    <span class="playlist-preview-badge">${triggerLabel}</span>
                                </div>
                            `;
                        }).join('')}
                        ${remaining > 0 ? `<div class="playlist-preview-more">+${remaining} more</div>` : ''}
                    </div>
                `;
            }
        }

        /**
         * Bind numeric input handlers with validation
         * @param {HTMLInputElement} input - Input element
         * @param {string} name - Input name for tracking
         * @param {Object} config - Configuration { min, max, onChange }
         * @private
         */
        _bindNumericInput(input, name, config) {
            const { min, max, onChange } = config;

            // Input event for real-time updates
            input.addEventListener('input', (e) => {
                if (this.isUpdatingFromExternal) return;

                // Clear any existing debounce timer
                if (this.debounceTimers[name]) {
                    clearTimeout(this.debounceTimers[name]);
                }

                // Debounce the change callback
                this.debounceTimers[name] = setTimeout(() => {
                    const value = this._parseAndValidate(input.value, min, max);
                    if (value !== null) {
                        input.value = value;
                        if (onChange) onChange(value);
                    }
                }, this.options.debounceDelay);
            });

            // Blur event for final validation
            input.addEventListener('blur', (e) => {
                if (this.isUpdatingFromExternal) return;

                // Clear any pending debounce
                if (this.debounceTimers[name]) {
                    clearTimeout(this.debounceTimers[name]);
                    this.debounceTimers[name] = null;
                }

                const value = this._parseAndValidate(input.value, min, max);
                if (value !== null) {
                    input.value = value;
                    if (onChange) onChange(value);
                } else {
                    // Revert to previous valid value
                    this._restoreInputValue(input, name);
                }
            });

            // Keydown for special key handling
            input.addEventListener('keydown', (e) => {
                if (this.isUpdatingFromExternal) return;

                const step = e.shiftKey ? this.options.stepLarge : this.options.stepSmall;
                let handled = false;

                switch (e.key) {
                    case KEY_CODES.UP:
                        e.preventDefault();
                        this._incrementValue(input, step, min, max);
                        handled = true;
                        break;

                    case KEY_CODES.DOWN:
                        e.preventDefault();
                        this._incrementValue(input, -step, min, max);
                        handled = true;
                        break;

                    case KEY_CODES.ENTER:
                        e.preventDefault();
                        input.blur();
                        break;

                    case KEY_CODES.ESCAPE:
                        e.preventDefault();
                        this._restoreInputValue(input, name);
                        input.blur();
                        break;
                }

                if (handled) {
                    const value = this._parseAndValidate(input.value, min, max);
                    if (value !== null && onChange) {
                        onChange(value);
                    }
                }
            });

            // Prevent non-numeric input
            input.addEventListener('keypress', (e) => {
                // Allow control keys
                if (e.ctrlKey || e.metaKey) return;

                // Allow navigation keys
                if (['Tab', 'Enter', 'Escape', 'Backspace', 'Delete'].includes(e.key)) return;

                // Allow arrow keys
                if (e.key.startsWith('Arrow')) return;

                // Allow negative sign only at start
                if (e.key === '-' && input.selectionStart === 0 && !input.value.includes('-')) return;

                // Block non-numeric characters
                if (!/\d/.test(e.key)) {
                    e.preventDefault();
                }
            });
        }

        /**
         * Parse and validate a numeric value
         * @param {string} value - Input value
         * @param {number|null} min - Minimum value
         * @param {number|null} max - Maximum value
         * @returns {number|null} Validated integer or null if invalid
         * @private
         */
        _parseAndValidate(value, min, max) {
            // Handle empty or whitespace
            if (value === '' || value === null || value === undefined) {
                return min !== null ? min : 0;
            }

            // Parse as integer
            const parsed = parseInt(value, 10);

            // Check for NaN
            if (isNaN(parsed)) {
                return null;
            }

            // Apply constraints
            let result = parsed;

            if (min !== null && result < min) {
                result = min;
            }

            if (max !== null && result > max) {
                result = max;
            }

            return result;
        }

        /**
         * Increment/decrement input value
         * @param {HTMLInputElement} input - Input element
         * @param {number} delta - Amount to change (+/-)
         * @param {number|null} min - Minimum value
         * @param {number|null} max - Maximum value
         * @private
         */
        _incrementValue(input, delta, min, max) {
            const current = parseInt(input.value, 10) || 0;
            const newValue = this._parseAndValidate(current + delta, min, max);

            if (newValue !== null) {
                input.value = newValue;
            }
        }

        /**
         * Restore input to previously stored valid value
         * @param {HTMLInputElement} input - Input element
         * @param {string} name - Input name
         * @private
         */
        _restoreInputValue(input, name) {
            if (this.selectedLayer) {
                const value = this._getLayerValue(name);
                if (value !== null) {
                    input.value = value;
                }
            }
        }

        /**
         * Get value from selected layer
         * @param {string} name - Property name (x, y, width, height)
         * @returns {number|null} Value or null
         * @private
         */
        _getLayerValue(name) {
            if (!this.selectedLayer) return null;

            const mapping = {
                x: 'x',
                y: 'y',
                width: 'width',
                height: 'height'
            };

            const prop = mapping[name];
            return prop && this.selectedLayer[prop] !== undefined
                ? this.selectedLayer[prop]
                : null;
        }

        // =====================================================================
        // Change Handlers
        // =====================================================================

        /**
         * Handle position change (X or Y)
         * @param {string} axis - 'x' or 'y'
         * @param {number} value - New value
         * @private
         */
        _handlePositionChange(axis, value) {
            if (!this.selectedLayer || this.isUpdatingFromExternal) return;

            // Update local layer data
            this.selectedLayer[axis] = value;

            // Trigger position change callback
            if (this.callbacks.onPositionChange) {
                this.callbacks.onPositionChange({
                    layerId: this.selectedLayer.id,
                    x: this.selectedLayer.x,
                    y: this.selectedLayer.y,
                    changedAxis: axis
                });
            }

            // Trigger generic change callback
            this._triggerChange(axis, value);
        }

        /**
         * Handle size change (width or height)
         * @param {string} dimension - 'width' or 'height'
         * @param {number} value - New value
         * @private
         */
        _handleSizeChange(dimension, value) {
            if (!this.selectedLayer || this.isUpdatingFromExternal) return;

            // Update local layer data
            this.selectedLayer[dimension] = value;

            // Trigger size change callback
            if (this.callbacks.onSizeChange) {
                this.callbacks.onSizeChange({
                    layerId: this.selectedLayer.id,
                    width: this.selectedLayer.width,
                    height: this.selectedLayer.height,
                    changedDimension: dimension
                });
            }

            // Trigger generic change callback
            this._triggerChange(dimension, value);
        }

        /**
         * Handle opacity change (0-100%)
         * @param {number} percentValue - Opacity as percentage (0-100)
         * @private
         */
        _handleOpacityChange(percentValue) {
            if (!this.selectedLayer || this.isUpdatingFromExternal) return;

            // Convert percentage to decimal (0.0-1.0)
            const decimalValue = percentValue / 100;

            // Update local layer data
            this.selectedLayer.opacity = decimalValue;

            // Trigger opacity change callback for real-time canvas preview
            if (this.callbacks.onOpacityChange) {
                this.callbacks.onOpacityChange({
                    layerId: this.selectedLayer.id,
                    opacity: decimalValue,
                    opacityPercent: percentValue
                });
            }

            // Trigger generic change callback
            this._triggerChange('opacity', decimalValue);
        }

        /**
         * Trigger generic change callback
         * @param {string} property - Property name
         * @param {*} value - New value
         * @private
         */
        _triggerChange(property, value) {
            if (this.callbacks.onChange && this.selectedLayer) {
                this.callbacks.onChange({
                    layerId: this.selectedLayer.id,
                    property: property,
                    value: value,
                    layer: this.selectedLayer
                });
            }
        }

        // =====================================================================
        // Public API - Layer Selection
        // =====================================================================

        /**
         * Set the selected layer and update panel
         * @param {Object|null} layerData - Layer data object or null to deselect
         */
        setSelectedLayer(layerData) {
            this.selectedLayer = layerData;

            if (layerData) {
                this._showProperties();
                this._updateInputs(layerData);
            } else {
                this._showNoSelection();
            }
        }

        /**
         * Clear the selection
         */
        clearSelection() {
            this.setSelectedLayer(null);
        }

        /**
         * Get the currently selected layer
         * @returns {Object|null} Selected layer data
         */
        getSelectedLayer() {
            return this.selectedLayer;
        }

        // =====================================================================
        // Public API - Input Updates
        // =====================================================================

        /**
         * Update position inputs without triggering callbacks
         * @param {number} x - X position
         * @param {number} y - Y position
         */
        updatePosition(x, y) {
            this.isUpdatingFromExternal = true;

            if (this.inputs.x) {
                this.inputs.x.value = Math.round(x);
            }
            if (this.inputs.y) {
                this.inputs.y.value = Math.round(y);
            }

            // Update local layer data
            if (this.selectedLayer) {
                this.selectedLayer.x = Math.round(x);
                this.selectedLayer.y = Math.round(y);
            }

            this.isUpdatingFromExternal = false;
        }

        /**
         * Update size inputs without triggering callbacks
         * @param {number} width - Width
         * @param {number} height - Height
         */
        updateSize(width, height) {
            this.isUpdatingFromExternal = true;

            if (this.inputs.width) {
                this.inputs.width.value = Math.round(width);
            }
            if (this.inputs.height) {
                this.inputs.height.value = Math.round(height);
            }

            // Update local layer data
            if (this.selectedLayer) {
                this.selectedLayer.width = Math.round(width);
                this.selectedLayer.height = Math.round(height);
            }

            this.isUpdatingFromExternal = false;
        }

        /**
         * Update all geometry inputs (position and size) without triggering callbacks
         * @param {Object} geometry - { x, y, width, height }
         */
        updateGeometry(geometry) {
            this.isUpdatingFromExternal = true;

            if (geometry.x !== undefined && this.inputs.x) {
                this.inputs.x.value = Math.round(geometry.x);
            }
            if (geometry.y !== undefined && this.inputs.y) {
                this.inputs.y.value = Math.round(geometry.y);
            }
            if (geometry.width !== undefined && this.inputs.width) {
                this.inputs.width.value = Math.round(geometry.width);
            }
            if (geometry.height !== undefined && this.inputs.height) {
                this.inputs.height.value = Math.round(geometry.height);
            }

            // Update local layer data
            if (this.selectedLayer) {
                if (geometry.x !== undefined) this.selectedLayer.x = Math.round(geometry.x);
                if (geometry.y !== undefined) this.selectedLayer.y = Math.round(geometry.y);
                if (geometry.width !== undefined) this.selectedLayer.width = Math.round(geometry.width);
                if (geometry.height !== undefined) this.selectedLayer.height = Math.round(geometry.height);
            }

            this.isUpdatingFromExternal = false;
        }

        /**
         * Update opacity inputs without triggering callbacks
         * @param {number} opacity - Opacity as decimal (0.0-1.0) or percentage (0-100)
         * @param {boolean} [isPercent=false] - If true, opacity is interpreted as percentage
         */
        updateOpacity(opacity, isPercent = false) {
            this.isUpdatingFromExternal = true;

            // Convert to percentage if necessary
            const percentValue = isPercent ? opacity : Math.round(opacity * 100);

            // Clamp to valid range
            const clampedValue = Math.max(
                this.options.minOpacity,
                Math.min(this.options.maxOpacity, percentValue)
            );

            if (this.inputs.opacitySlider) {
                this.inputs.opacitySlider.value = clampedValue;
            }
            if (this.inputs.opacityValue) {
                this.inputs.opacityValue.value = clampedValue;
            }

            // Update local layer data (store as decimal)
            if (this.selectedLayer) {
                this.selectedLayer.opacity = clampedValue / 100;
            }

            this.isUpdatingFromExternal = false;
        }

        /**
         * Update background color picker without triggering callbacks
         * @param {string} color - Color value (hex, rgb, rgba, or 'transparent')
         */
        updateBackgroundColor(color) {
            this.isUpdatingFromExternal = true;

            const colorValue = this._parseColorString(color);

            if (this.colorPickers.background) {
                this.colorPickers.background.spectrum('set', colorValue);
            }

            // Update local layer data
            if (this.selectedLayer) {
                this.selectedLayer.background_color = color || 'transparent';
            }

            this.isUpdatingFromExternal = false;
        }

        /**
         * Update border color picker without triggering callbacks
         * @param {string} color - Color value (hex, rgb, rgba)
         */
        updateBorderColor(color) {
            this.isUpdatingFromExternal = true;

            const colorValue = this._parseColorString(color) || this.options.defaultBorderColor;

            if (this.colorPickers.border) {
                this.colorPickers.border.spectrum('set', colorValue);
            }

            // Update local layer data
            if (this.selectedLayer) {
                this.selectedLayer.border_color = colorValue;
            }

            this.isUpdatingFromExternal = false;
        }

        /**
         * Get the current background color value
         * @returns {string} RGBA color string or 'transparent'
         */
        getBackgroundColor() {
            if (this.colorPickers.background) {
                const color = this.colorPickers.background.spectrum('get');
                return this._colorToRgbaString(color);
            }
            return 'transparent';
        }

        /**
         * Get the current border color value
         * @returns {string} RGBA color string
         */
        getBorderColor() {
            if (this.colorPickers.border) {
                const color = this.colorPickers.border.spectrum('get');
                return this._colorToRgbaString(color) || this.options.defaultBorderColor;
            }
            return this.options.defaultBorderColor;
        }

        // =====================================================================
        // Public API - Constraints
        // =====================================================================

        /**
         * Set canvas bounds for max position/size constraints
         * @param {number} canvasWidth - Canvas width
         * @param {number} canvasHeight - Canvas height
         */
        setCanvasBounds(canvasWidth, canvasHeight) {
            this.options.maxWidth = canvasWidth;
            this.options.maxHeight = canvasHeight;
            this.options.maxX = canvasWidth;
            this.options.maxY = canvasHeight;
        }

        /**
         * Set minimum layer size
         * @param {number} minWidth - Minimum width
         * @param {number} minHeight - Minimum height
         */
        setMinSize(minWidth, minHeight) {
            this.options.minWidth = minWidth;
            this.options.minHeight = minHeight;
        }

        // =====================================================================
        // Public API - Callbacks
        // =====================================================================

        /**
         * Set callback for position changes
         * @param {Function} callback - ({ layerId, x, y, changedAxis }) => void
         */
        onPositionChange(callback) {
            this.callbacks.onPositionChange = callback;
        }

        /**
         * Set callback for size changes
         * @param {Function} callback - ({ layerId, width, height, changedDimension }) => void
         */
        onSizeChange(callback) {
            this.callbacks.onSizeChange = callback;
        }

        /**
         * Set callback for opacity changes
         * @param {Function} callback - ({ layerId, opacity, opacityPercent }) => void
         */
        onOpacityChange(callback) {
            this.callbacks.onOpacityChange = callback;
        }

        /**
         * Set callback for background color changes
         * @param {Function} callback - ({ layerId, color, rgba, alpha, isPreview }) => void
         */
        onBackgroundColorChange(callback) {
            this.callbacks.onBackgroundColorChange = callback;
        }

        /**
         * Set callback for border color changes
         * @param {Function} callback - ({ layerId, color, rgba, alpha, isPreview }) => void
         */
        onBorderColorChange(callback) {
            this.callbacks.onBorderColorChange = callback;
        }

        /**
         * Set callback for any property change
         * @param {Function} callback - ({ layerId, property, value, layer }) => void
         */
        onChange(callback) {
            this.callbacks.onChange = callback;
        }

        /**
         * Set callback for content mode changes
         * @param {Function} callback - ({ layerId, mode }) => void
         */
        onContentModeChange(callback) {
            this.callbacks.onContentModeChange = callback;
        }

        /**
         * Set callback for static content selection
         * @param {Function} callback - ({ layerId, content }) => void
         */
        onStaticContentSelect(callback) {
            this.callbacks.onStaticContentSelect = callback;
        }

        /**
         * Set callback for static content clearing
         * @param {Function} callback - ({ layerId }) => void
         */
        onStaticContentClear(callback) {
            this.callbacks.onStaticContentClear = callback;
        }

        /**
         * Set callback for playlist addition
         * @param {Function} callback - ({ layerId, playlistId, triggerType, priority, assignment }) => void
         */
        onPlaylistAdd(callback) {
            this.callbacks.onPlaylistAdd = callback;
        }

        /**
         * Set callback for playlist removal
         * @param {Function} callback - ({ layerId, assignmentId, playlistId, assignment }) => void
         */
        onPlaylistRemove(callback) {
            this.callbacks.onPlaylistRemove = callback;
        }

        /**
         * Set callback for playlist update (priority/trigger changes)
         * @param {Function} callback - ({ layerId, assignmentId, updates }) => void
         */
        onPlaylistUpdate(callback) {
            this.callbacks.onPlaylistUpdate = callback;
        }

        // =====================================================================
        // Public API - Content Assignment
        // =====================================================================

        /**
         * Set the content mode externally (without triggering callback)
         * @param {string} mode - 'static' or 'playlist'
         */
        setContentMode(mode) {
            this.isUpdatingFromExternal = true;
            this.contentMode = mode;

            // Update tab UI
            if (this.contentElements.modeTabs) {
                const tabs = this.contentElements.modeTabs.querySelectorAll('.' + this.options.contentModeTabClass);
                tabs.forEach(tab => {
                    tab.classList.toggle('active', tab.dataset.mode === mode);
                });
            }

            // Show/hide content containers
            if (this.contentElements.staticContainer) {
                this.contentElements.staticContainer.style.display = mode === CONTENT_MODES.STATIC ? 'block' : 'none';
            }
            if (this.contentElements.playlistContainer) {
                this.contentElements.playlistContainer.style.display = mode === CONTENT_MODES.PLAYLIST ? 'block' : 'none';
            }

            this.isUpdatingFromExternal = false;
        }

        /**
         * Get the current content mode
         * @returns {string} 'static' or 'playlist'
         */
        getContentMode() {
            return this.contentMode;
        }

        /**
         * Set static content externally (without triggering callback)
         * @param {Object|null} content - Content data object or null
         */
        setStaticContent(content) {
            this.isUpdatingFromExternal = true;
            this.selectedContent = content;
            this._updateContentPreview(content);
            this.isUpdatingFromExternal = false;
        }

        /**
         * Get the currently selected static content
         * @returns {Object|null} Content data object or null
         */
        getStaticContent() {
            return this.selectedContent;
        }

        /**
         * Clear static content selection externally
         */
        clearStaticContent() {
            this.isUpdatingFromExternal = true;
            this.selectedContent = null;
            this._updateContentPreview(null);
            this.isUpdatingFromExternal = false;
        }

        /**
         * Get the available content list (after loading from API)
         * @returns {Array} Array of content objects
         */
        getAvailableContent() {
            return this.availableContent;
        }

        /**
         * Set the available content list (pre-load content)
         * @param {Array} content - Array of content objects
         */
        setAvailableContent(content) {
            this.availableContent = content || [];
        }

        // =====================================================================
        // Public API - Playlist Assignment
        // =====================================================================

        /**
         * Get the currently assigned playlists
         * @returns {Array} Array of playlist assignment objects
         */
        getAssignedPlaylists() {
            return [...this.assignedPlaylists];
        }

        /**
         * Set assigned playlists externally (without triggering callbacks)
         * @param {Array} assignments - Array of playlist assignment objects
         */
        setAssignedPlaylists(assignments) {
            this.isUpdatingFromExternal = true;
            this.assignedPlaylists = assignments || [];
            this._updatePlaylistPreview();
            this.isUpdatingFromExternal = false;
        }

        /**
         * Clear all playlist assignments externally
         */
        clearAssignedPlaylists() {
            this.isUpdatingFromExternal = true;
            this.assignedPlaylists = [];
            this._updatePlaylistPreview();
            this.isUpdatingFromExternal = false;
        }

        /**
         * Get the available playlists list (after loading from API)
         * @returns {Array} Array of playlist objects
         */
        getAvailablePlaylists() {
            return [...this.availablePlaylists];
        }

        /**
         * Set the available playlists list (pre-load playlists)
         * @param {Array} playlists - Array of playlist objects
         */
        setAvailablePlaylists(playlists) {
            this.availablePlaylists = playlists || [];
        }

        /**
         * Add a playlist assignment externally (without triggering callback)
         * @param {Object} assignment - Playlist assignment { id, playlist_id, trigger_type, priority }
         */
        addPlaylistAssignment(assignment) {
            this.isUpdatingFromExternal = true;
            this.assignedPlaylists.push(assignment);
            this._updatePlaylistPreview();
            this.isUpdatingFromExternal = false;
        }

        /**
         * Remove a playlist assignment externally (without triggering callback)
         * @param {string} assignmentId - Assignment ID to remove
         */
        removePlaylistAssignment(assignmentId) {
            this.isUpdatingFromExternal = true;
            const index = this.assignedPlaylists.findIndex(a => a.id === assignmentId);
            if (index !== -1) {
                this.assignedPlaylists.splice(index, 1);
                this._updatePlaylistPreview();
            }
            this.isUpdatingFromExternal = false;
        }

        /**
         * Update a playlist assignment's properties externally
         * @param {string} assignmentId - Assignment ID to update
         * @param {Object} updates - Properties to update { trigger_type, priority }
         */
        updatePlaylistAssignment(assignmentId, updates) {
            this.isUpdatingFromExternal = true;
            const assignment = this.assignedPlaylists.find(a => a.id === assignmentId);
            if (assignment) {
                if (updates.trigger_type !== undefined) {
                    assignment.trigger_type = updates.trigger_type;
                }
                if (updates.priority !== undefined) {
                    assignment.priority = updates.priority;
                }
                this._updatePlaylistPreview();
            }
            this.isUpdatingFromExternal = false;
        }

        // =====================================================================
        // Private - UI Updates
        // =====================================================================

        /**
         * Show the properties form
         * @private
         */
        _showProperties() {
            if (this.elements.noSelection) {
                this.elements.noSelection.style.display = 'none';
            }
            if (this.elements.layerProperties) {
                this.elements.layerProperties.style.display = 'block';
            }
        }

        /**
         * Show the no selection state
         * @private
         */
        _showNoSelection() {
            if (this.elements.noSelection) {
                this.elements.noSelection.style.display = 'block';
            }
            if (this.elements.layerProperties) {
                this.elements.layerProperties.style.display = 'none';
            }

            // Clear inputs
            this._clearInputs();
        }

        /**
         * Update inputs from layer data
         * @param {Object} layerData - Layer data
         * @private
         */
        _updateInputs(layerData) {
            this.isUpdatingFromExternal = true;

            // Position
            if (this.inputs.x && layerData.x !== undefined) {
                this.inputs.x.value = Math.round(layerData.x);
            }
            if (this.inputs.y && layerData.y !== undefined) {
                this.inputs.y.value = Math.round(layerData.y);
            }

            // Size
            if (this.inputs.width && layerData.width !== undefined) {
                this.inputs.width.value = Math.round(layerData.width);
            }
            if (this.inputs.height && layerData.height !== undefined) {
                this.inputs.height.value = Math.round(layerData.height);
            }

            // Opacity (convert decimal 0-1 to percentage 0-100)
            if (layerData.opacity !== undefined) {
                const opacityPercent = Math.round(layerData.opacity * 100);
                if (this.inputs.opacitySlider) {
                    this.inputs.opacitySlider.value = opacityPercent;
                }
                if (this.inputs.opacityValue) {
                    this.inputs.opacityValue.value = opacityPercent;
                }
            }

            // Background color (with alpha support)
            if (this.colorPickers.background) {
                const bgColor = this._parseColorString(layerData.background_color);
                this.colorPickers.background.spectrum('set', bgColor);
            }

            // Border color
            if (this.colorPickers.border) {
                const borderColor = this._parseColorString(layerData.border_color) ||
                    this.options.defaultBorderColor;
                this.colorPickers.border.spectrum('set', borderColor);
            }

            // Content assignment - reset to default state when layer changes
            // Content assignments are device-specific, so reset to empty state
            this.contentMode = CONTENT_MODES.STATIC;
            this.selectedContent = null;

            // Reset content mode tabs to Static
            if (this.contentElements.modeTabs) {
                const tabs = this.contentElements.modeTabs.querySelectorAll('.' + this.options.contentModeTabClass);
                tabs.forEach(tab => {
                    tab.classList.toggle('active', tab.dataset.mode === CONTENT_MODES.STATIC);
                });
            }

            // Show static container, hide playlist container
            if (this.contentElements.staticContainer) {
                this.contentElements.staticContainer.style.display = 'block';
            }
            if (this.contentElements.playlistContainer) {
                this.contentElements.playlistContainer.style.display = 'none';
            }

            // Reset content preview to empty state
            this._updateContentPreview(null);

            // Reset playlist assignments when layer changes
            this.assignedPlaylists = [];
            this._updatePlaylistPreview();

            this.isUpdatingFromExternal = false;
        }

        /**
         * Clear all inputs
         * @private
         */
        _clearInputs() {
            this.isUpdatingFromExternal = true;

            if (this.inputs.x) this.inputs.x.value = 0;
            if (this.inputs.y) this.inputs.y.value = 0;
            if (this.inputs.width) this.inputs.width.value = this.options.minWidth;
            if (this.inputs.height) this.inputs.height.value = this.options.minHeight;
            if (this.inputs.opacitySlider) this.inputs.opacitySlider.value = this.options.maxOpacity;
            if (this.inputs.opacityValue) this.inputs.opacityValue.value = this.options.maxOpacity;

            // Reset color pickers
            if (this.colorPickers.background) {
                this.colorPickers.background.spectrum('set', null);
            }
            if (this.colorPickers.border) {
                this.colorPickers.border.spectrum('set', this.options.defaultBorderColor);
            }

            // Reset content assignment
            this.contentMode = CONTENT_MODES.STATIC;
            this.selectedContent = null;

            // Reset content mode tabs to Static
            if (this.contentElements.modeTabs) {
                const tabs = this.contentElements.modeTabs.querySelectorAll('.' + this.options.contentModeTabClass);
                tabs.forEach(tab => {
                    tab.classList.toggle('active', tab.dataset.mode === CONTENT_MODES.STATIC);
                });
            }

            // Show static container, hide playlist container
            if (this.contentElements.staticContainer) {
                this.contentElements.staticContainer.style.display = 'block';
            }
            if (this.contentElements.playlistContainer) {
                this.contentElements.playlistContainer.style.display = 'none';
            }

            // Reset content preview to empty state
            this._updateContentPreview(null);

            // Reset playlist assignments
            this.assignedPlaylists = [];
            this._updatePlaylistPreview();

            this.isUpdatingFromExternal = false;
        }

        // =====================================================================
        // Utility Methods
        // =====================================================================

        /**
         * Check if an input is currently focused
         * @returns {boolean} True if any property input is focused
         */
        hasInputFocus() {
            const activeElement = document.activeElement;
            return Object.values(this.inputs).some(input => input === activeElement);
        }

        /**
         * Focus a specific input
         * @param {string} name - Input name (x, y, width, height)
         */
        focusInput(name) {
            const input = this.inputs[name];
            if (input) {
                input.focus();
                input.select();
            }
        }

        /**
         * Validate all current input values
         * @returns {boolean} True if all inputs are valid
         */
        validateInputs() {
            const fields = ['x', 'y', 'width', 'height'];
            for (const field of fields) {
                const input = this.inputs[field];
                if (!input) continue;

                const min = field === 'width' ? this.options.minWidth :
                           field === 'height' ? this.options.minHeight :
                           field === 'x' ? this.options.minX :
                           this.options.minY;

                const max = field === 'width' ? this.options.maxWidth :
                           field === 'height' ? this.options.maxHeight :
                           field === 'x' ? this.options.maxX :
                           this.options.maxY;

                const value = this._parseAndValidate(input.value, min, max);
                if (value === null) {
                    return false;
                }
            }
            return true;
        }

        /**
         * Get current values from inputs
         * @returns {Object} { x, y, width, height, opacity, backgroundColor, borderColor }
         */
        getValues() {
            return {
                x: parseInt(this.inputs.x?.value, 10) || 0,
                y: parseInt(this.inputs.y?.value, 10) || 0,
                width: parseInt(this.inputs.width?.value, 10) || this.options.minWidth,
                height: parseInt(this.inputs.height?.value, 10) || this.options.minHeight,
                opacity: this.getOpacity(),
                backgroundColor: this.getBackgroundColor(),
                borderColor: this.getBorderColor()
            };
        }

        /**
         * Get current opacity value
         * @param {boolean} [asPercent=false] - If true, return as percentage (0-100), otherwise decimal (0.0-1.0)
         * @returns {number} Current opacity value
         */
        getOpacity(asPercent = false) {
            const percentValue = parseInt(this.inputs.opacityValue?.value, 10) || this.options.maxOpacity;
            return asPercent ? percentValue : percentValue / 100;
        }

        /**
         * Destroy color pickers and cleanup resources
         */
        destroy() {
            // Destroy Spectrum color pickers
            if (this.colorPickers.background) {
                this.colorPickers.background.spectrum('destroy');
                this.colorPickers.background = null;
            }
            if (this.colorPickers.border) {
                this.colorPickers.border.spectrum('destroy');
                this.colorPickers.border = null;
            }

            // Remove file picker modal
            if (this.filePickerModal) {
                this.filePickerModal.remove();
                this.filePickerModal = null;
            }

            // Remove file picker styles
            const fileStyles = document.getElementById('file-picker-styles');
            if (fileStyles) {
                fileStyles.remove();
            }

            // Remove playlist picker modal
            if (this.playlistPickerModal) {
                this.playlistPickerModal.remove();
                this.playlistPickerModal = null;
            }

            // Remove playlist picker styles
            const playlistStyles = document.getElementById('playlist-picker-styles');
            if (playlistStyles) {
                playlistStyles.remove();
            }

            // Clear debounce timers
            Object.keys(this.debounceTimers).forEach(key => {
                if (this.debounceTimers[key]) {
                    clearTimeout(this.debounceTimers[key]);
                }
            });
            this.debounceTimers = {};

            // Clear references
            this.selectedLayer = null;
            this.selectedContent = null;
            this.availableContent = [];
            this.assignedPlaylists = [];
            this.availablePlaylists = [];
            this.callbacks = {};
        }

        /**
         * Check if color pickers are initialized
         * @returns {boolean} True if color pickers are ready
         */
        isColorPickerReady() {
            return !!(this.colorPickers.background || this.colorPickers.border);
        }
    }

    // =========================================================================
    // Export to Global Namespace
    // =========================================================================

    window.PropertiesPanel = PropertiesPanel;

})(window);

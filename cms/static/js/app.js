/**
 * Skillz Media CMS - Shared Frontend JavaScript
 *
 * This module provides common functionality used across all CMS pages:
 * - API helpers for fetch requests
 * - Modal management
 * - Status/notification display
 * - Form utilities
 * - UI interaction helpers
 */

(function(window) {
    'use strict';

    // =========================================================================
    // API Helpers
    // =========================================================================

    /**
     * Make an API request with standard error handling
     * @param {string} url - The API endpoint URL
     * @param {Object} options - Fetch options (method, body, headers, etc.)
     * @returns {Promise<Object>} - Response data or throws error
     */
    async function apiRequest(url, options = {}) {
        const defaultOptions = {
            headers: {
                'Content-Type': 'application/json'
            }
        };

        const mergedOptions = {
            ...defaultOptions,
            ...options,
            headers: {
                ...defaultOptions.headers,
                ...(options.headers || {})
            }
        };

        // Stringify body if it's an object
        if (mergedOptions.body && typeof mergedOptions.body === 'object') {
            mergedOptions.body = JSON.stringify(mergedOptions.body);
        }

        const response = await fetch(url, mergedOptions);
        const data = await response.json();

        if (!response.ok) {
            const error = new Error(data.error || data.message || 'Request failed');
            error.status = response.status;
            error.data = data;
            throw error;
        }

        return data;
    }

    /**
     * GET request helper
     * @param {string} url - The API endpoint URL
     * @returns {Promise<Object>} - Response data
     */
    async function apiGet(url) {
        return apiRequest(url, { method: 'GET' });
    }

    /**
     * POST request helper
     * @param {string} url - The API endpoint URL
     * @param {Object} data - Request body data
     * @returns {Promise<Object>} - Response data
     */
    async function apiPost(url, data) {
        return apiRequest(url, {
            method: 'POST',
            body: data
        });
    }

    /**
     * PUT request helper
     * @param {string} url - The API endpoint URL
     * @param {Object} data - Request body data
     * @returns {Promise<Object>} - Response data
     */
    async function apiPut(url, data) {
        return apiRequest(url, {
            method: 'PUT',
            body: data
        });
    }

    /**
     * PATCH request helper
     * @param {string} url - The API endpoint URL
     * @param {Object} data - Request body data
     * @returns {Promise<Object>} - Response data
     */
    async function apiPatch(url, data) {
        return apiRequest(url, {
            method: 'PATCH',
            body: data
        });
    }

    /**
     * DELETE request helper
     * @param {string} url - The API endpoint URL
     * @returns {Promise<Object>} - Response data
     */
    async function apiDelete(url) {
        return apiRequest(url, { method: 'DELETE' });
    }

    // =========================================================================
    // Modal Management
    // =========================================================================

    /**
     * Open a modal by ID
     * @param {string} modalId - The modal element ID
     */
    function openModal(modalId) {
        const modal = document.getElementById(modalId);
        if (modal) {
            modal.classList.add('active');
            document.body.style.overflow = 'hidden';
        }
    }

    /**
     * Close a modal by ID
     * @param {string} modalId - The modal element ID
     */
    function closeModal(modalId) {
        const modal = document.getElementById(modalId);
        if (modal) {
            modal.classList.remove('active');
            document.body.style.overflow = '';
        }
    }

    /**
     * Close all open modals
     */
    function closeAllModals() {
        document.querySelectorAll('.modal.active').forEach(modal => {
            modal.classList.remove('active');
        });
        document.body.style.overflow = '';
    }

    /**
     * Initialize modal with backdrop click and escape key handling
     * @param {string} modalId - The modal element ID
     * @param {Function} onClose - Optional callback when modal closes
     */
    function initModal(modalId, onClose) {
        const modal = document.getElementById(modalId);
        if (!modal) return;

        // Close on backdrop click
        modal.addEventListener('click', function(e) {
            if (e.target === this) {
                closeModal(modalId);
                if (onClose) onClose();
            }
        });

        // Close button handler
        const closeBtn = modal.querySelector('.close-btn');
        if (closeBtn) {
            closeBtn.addEventListener('click', function() {
                closeModal(modalId);
                if (onClose) onClose();
            });
        }
    }

    /**
     * Initialize escape key to close modals globally
     */
    function initEscapeKeyHandler() {
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape') {
                closeAllModals();
            }
        });
    }

    // =========================================================================
    // Status/Notification Display
    // =========================================================================

    const STATUS_STYLES = {
        loading: { background: '#e0e7ff', color: '#3730a3', icon: '...' },
        success: { background: '#d1fae5', color: '#065f46', icon: '' },
        error: { background: '#fee2e2', color: '#991b1b', icon: '' },
        warning: { background: '#fef3c7', color: '#92400e', icon: '' },
        info: { background: '#e0e7ff', color: '#3730a3', icon: '' }
    };

    /**
     * Show a status message in a status element
     * @param {string} elementId - The status element ID
     * @param {string} type - Status type: 'loading', 'success', 'error', 'warning', 'info'
     * @param {string} message - The message to display
     */
    function showStatus(elementId, type, message) {
        const statusEl = document.getElementById(elementId);
        if (!statusEl) return;

        const style = STATUS_STYLES[type] || STATUS_STYLES.info;

        statusEl.style.display = 'block';
        statusEl.style.background = style.background;
        statusEl.style.color = style.color;
        statusEl.textContent = style.icon + ' ' + message;
    }

    /**
     * Hide a status element
     * @param {string} elementId - The status element ID
     */
    function hideStatus(elementId) {
        const statusEl = document.getElementById(elementId);
        if (statusEl) {
            statusEl.style.display = 'none';
        }
    }

    /**
     * Show a toast notification (auto-dismissing)
     * @param {string} message - The message to display
     * @param {string} type - Notification type: 'success', 'error', 'warning', 'info'
     * @param {number} duration - Duration in ms (default: 3000)
     */
    function showToast(message, type = 'info', duration = 3000) {
        // Create toast container if it doesn't exist
        let container = document.getElementById('toast-container');
        if (!container) {
            container = document.createElement('div');
            container.id = 'toast-container';
            container.style.cssText = 'position: fixed; top: 20px; right: 20px; z-index: 9999; display: flex; flex-direction: column; gap: 10px;';
            document.body.appendChild(container);
        }

        const style = STATUS_STYLES[type] || STATUS_STYLES.info;

        const toast = document.createElement('div');
        toast.style.cssText = `
            padding: 16px 24px;
            border-radius: 12px;
            background: ${style.background};
            color: ${style.color};
            font-weight: 500;
            font-size: 14px;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15);
            transform: translateX(120%);
            transition: transform 0.3s ease;
            max-width: 400px;
        `;
        toast.textContent = style.icon + ' ' + message;

        container.appendChild(toast);

        // Animate in
        requestAnimationFrame(() => {
            toast.style.transform = 'translateX(0)';
        });

        // Auto dismiss
        setTimeout(() => {
            toast.style.transform = 'translateX(120%)';
            setTimeout(() => {
                toast.remove();
                if (container.children.length === 0) {
                    container.remove();
                }
            }, 300);
        }, duration);
    }

    // =========================================================================
    // Formatting Utilities
    // =========================================================================

    /**
     * Format file size in human-readable format
     * @param {number} bytes - File size in bytes
     * @returns {string} - Formatted size string
     */
    function formatFileSize(bytes) {
        if (bytes === 0) return '0 Bytes';
        const k = 1024;
        const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    }

    /**
     * Format duration in seconds to human-readable format
     * @param {number} seconds - Duration in seconds
     * @returns {string} - Formatted duration string
     */
    function formatDuration(seconds) {
        if (seconds < 60) {
            return seconds + 's';
        }
        const minutes = Math.floor(seconds / 60);
        const remainingSeconds = seconds % 60;
        if (minutes < 60) {
            return remainingSeconds > 0 ?
                `${minutes}m ${remainingSeconds}s` :
                `${minutes}m`;
        }
        const hours = Math.floor(minutes / 60);
        const remainingMinutes = minutes % 60;
        return `${hours}h ${remainingMinutes}m`;
    }

    /**
     * Format a date string to a relative time (e.g., "2 hours ago")
     * @param {string} dateStr - ISO date string
     * @returns {string} - Relative time string
     */
    function formatRelativeTime(dateStr) {
        const date = new Date(dateStr);
        const now = new Date();
        const diffMs = now - date;
        const diffSec = Math.floor(diffMs / 1000);
        const diffMin = Math.floor(diffSec / 60);
        const diffHour = Math.floor(diffMin / 60);
        const diffDay = Math.floor(diffHour / 24);

        if (diffSec < 60) return 'just now';
        if (diffMin < 60) return `${diffMin} minute${diffMin !== 1 ? 's' : ''} ago`;
        if (diffHour < 24) return `${diffHour} hour${diffHour !== 1 ? 's' : ''} ago`;
        if (diffDay < 7) return `${diffDay} day${diffDay !== 1 ? 's' : ''} ago`;

        return date.toLocaleDateString();
    }

    // =========================================================================
    // Picker Utilities
    // =========================================================================

    /**
     * Initialize an icon picker with selection handling
     * @param {string} containerSelector - CSS selector for the picker container
     * @param {Function} onChange - Callback when selection changes (receives icon value)
     * @returns {Object} - Object with getSelected() method
     */
    function initIconPicker(containerSelector, onChange) {
        const container = document.querySelector(containerSelector);
        if (!container) return null;

        let selectedIcon = null;
        const options = container.querySelectorAll('.icon-option');

        // Find initially selected
        options.forEach(option => {
            if (option.classList.contains('selected')) {
                selectedIcon = option.dataset.icon;
            }
        });

        // Add click handlers
        options.forEach(option => {
            option.addEventListener('click', function() {
                options.forEach(o => o.classList.remove('selected'));
                this.classList.add('selected');
                selectedIcon = this.dataset.icon;
                if (onChange) onChange(selectedIcon);
            });
        });

        return {
            getSelected: () => selectedIcon,
            setSelected: (icon) => {
                options.forEach(option => {
                    if (option.dataset.icon === icon) {
                        options.forEach(o => o.classList.remove('selected'));
                        option.classList.add('selected');
                        selectedIcon = icon;
                    }
                });
            }
        };
    }

    /**
     * Initialize a color picker with selection handling
     * @param {string} containerSelector - CSS selector for the picker container
     * @param {Function} onChange - Callback when selection changes (receives color value)
     * @returns {Object} - Object with getSelected() method
     */
    function initColorPicker(containerSelector, onChange) {
        const container = document.querySelector(containerSelector);
        if (!container) return null;

        let selectedColor = null;
        const options = container.querySelectorAll('.color-option');

        // Find initially selected
        options.forEach(option => {
            if (option.classList.contains('selected')) {
                selectedColor = option.dataset.color;
            }
        });

        // Add click handlers
        options.forEach(option => {
            option.addEventListener('click', function() {
                options.forEach(o => o.classList.remove('selected'));
                this.classList.add('selected');
                selectedColor = this.dataset.color;
                if (onChange) onChange(selectedColor);
            });
        });

        return {
            getSelected: () => selectedColor,
            setSelected: (color) => {
                options.forEach(option => {
                    if (option.dataset.color === color) {
                        options.forEach(o => o.classList.remove('selected'));
                        option.classList.add('selected');
                        selectedColor = color;
                    }
                });
            }
        };
    }

    // =========================================================================
    // Form Utilities
    // =========================================================================

    /**
     * Serialize form data to an object
     * @param {HTMLFormElement} form - The form element
     * @returns {Object} - Form data as key-value pairs
     */
    function serializeForm(form) {
        const formData = new FormData(form);
        const data = {};
        for (const [key, value] of formData.entries()) {
            data[key] = value;
        }
        return data;
    }

    /**
     * Disable form during submission
     * @param {HTMLFormElement} form - The form element
     * @param {boolean} disabled - Whether to disable
     */
    function setFormDisabled(form, disabled) {
        const elements = form.querySelectorAll('input, select, textarea, button');
        elements.forEach(el => {
            el.disabled = disabled;
        });
    }

    // =========================================================================
    // Upload Utilities
    // =========================================================================

    /**
     * Initialize drag and drop upload area
     * @param {string} areaId - The drop area element ID
     * @param {string} inputId - The file input element ID
     * @param {Object} options - Configuration options
     */
    function initDragDropUpload(areaId, inputId, options = {}) {
        const area = document.getElementById(areaId);
        const input = document.getElementById(inputId);
        if (!area || !input) return;

        const {
            onFileSelect,
            onDragOver,
            onDragLeave,
            activeClass = 'dragging',
            selectedClass = 'selected'
        } = options;

        // Handle drag events
        area.addEventListener('dragover', (e) => {
            e.preventDefault();
            area.classList.add(activeClass);
            if (onDragOver) onDragOver(e);
        });

        area.addEventListener('dragleave', () => {
            area.classList.remove(activeClass);
            if (onDragLeave) onDragLeave();
        });

        area.addEventListener('drop', (e) => {
            e.preventDefault();
            area.classList.remove(activeClass);

            if (e.dataTransfer.files.length > 0) {
                input.files = e.dataTransfer.files;
                area.classList.add(selectedClass);
                if (onFileSelect) onFileSelect(e.dataTransfer.files[0]);
            }
        });

        // Handle file input change
        input.addEventListener('change', function() {
            if (this.files.length > 0) {
                area.classList.add(selectedClass);
                if (onFileSelect) onFileSelect(this.files[0]);
            } else {
                area.classList.remove(selectedClass);
            }
        });
    }

    /**
     * Upload file with progress tracking
     * @param {string} url - Upload endpoint URL
     * @param {FormData} formData - Form data with file
     * @param {Object} options - Configuration options
     * @returns {Promise<Object>} - Response data
     */
    function uploadWithProgress(url, formData, options = {}) {
        const { onProgress, onComplete, onError } = options;

        return new Promise((resolve, reject) => {
            const xhr = new XMLHttpRequest();

            xhr.upload.addEventListener('progress', (e) => {
                if (e.lengthComputable && onProgress) {
                    const percentComplete = Math.round((e.loaded / e.total) * 100);
                    onProgress(percentComplete);
                }
            });

            xhr.addEventListener('load', () => {
                try {
                    const data = JSON.parse(xhr.responseText);
                    if (xhr.status >= 200 && xhr.status < 300) {
                        if (onComplete) onComplete(data);
                        resolve(data);
                    } else {
                        const error = new Error(data.error || 'Upload failed');
                        error.status = xhr.status;
                        error.data = data;
                        if (onError) onError(error);
                        reject(error);
                    }
                } catch (e) {
                    const error = new Error('Invalid response');
                    if (onError) onError(error);
                    reject(error);
                }
            });

            xhr.addEventListener('error', () => {
                const error = new Error('Upload failed');
                if (onError) onError(error);
                reject(error);
            });

            xhr.open('POST', url);
            xhr.send(formData);
        });
    }

    // =========================================================================
    // Video Player Utilities
    // =========================================================================

    /**
     * Create a video player in a container
     * @param {string} containerId - Container element ID
     * @param {string} src - Video source URL
     * @param {Object} options - Player options
     * @returns {HTMLVideoElement} - The created video element
     */
    function createVideoPlayer(containerId, src, options = {}) {
        const container = document.getElementById(containerId);
        if (!container) return null;

        const {
            autoplay = true,
            controls = true,
            loop = false,
            muted = false,
            onEnded,
            onTimeUpdate
        } = options;

        const video = document.createElement('video');
        video.autoplay = autoplay;
        video.controls = controls;
        video.loop = loop;
        video.muted = muted;
        video.style.cssText = 'position: absolute; top: 0; left: 0; width: 100%; height: 100%; object-fit: contain;';

        const source = document.createElement('source');
        source.src = src;
        source.type = 'video/mp4';

        video.appendChild(source);

        // Clear container and add video
        container.innerHTML = '';
        container.appendChild(video);

        // Event handlers
        if (onEnded) {
            video.addEventListener('ended', onEnded);
        }

        if (onTimeUpdate) {
            video.addEventListener('timeupdate', () => {
                onTimeUpdate(video.currentTime, video.duration);
            });
        }

        return video;
    }

    // =========================================================================
    // Confirm Dialog
    // =========================================================================

    /**
     * Show a confirmation dialog
     * @param {string} message - The confirmation message
     * @param {Object} options - Configuration options
     * @returns {Promise<boolean>} - True if confirmed, false otherwise
     */
    function confirm(message, options = {}) {
        // For now, use native confirm
        // This can be enhanced to use a custom modal
        return Promise.resolve(window.confirm(message));
    }

    // =========================================================================
    // Debounce and Throttle
    // =========================================================================

    /**
     * Debounce a function
     * @param {Function} func - The function to debounce
     * @param {number} wait - Wait time in ms
     * @returns {Function} - Debounced function
     */
    function debounce(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func.apply(this, args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    }

    /**
     * Throttle a function
     * @param {Function} func - The function to throttle
     * @param {number} limit - Limit in ms
     * @returns {Function} - Throttled function
     */
    function throttle(func, limit) {
        let inThrottle;
        return function executedFunction(...args) {
            if (!inThrottle) {
                func.apply(this, args);
                inThrottle = true;
                setTimeout(() => inThrottle = false, limit);
            }
        };
    }

    // =========================================================================
    // Initialize on DOM Ready
    // =========================================================================

    function init() {
        // Initialize escape key handler for modals
        initEscapeKeyHandler();

        // Auto-initialize modals with data-modal attribute
        document.querySelectorAll('[data-modal]').forEach(modal => {
            initModal(modal.id);
        });
    }

    // Run init when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    // =========================================================================
    // Export to Global Namespace
    // =========================================================================

    window.CMS = {
        // API Helpers
        api: {
            request: apiRequest,
            get: apiGet,
            post: apiPost,
            put: apiPut,
            patch: apiPatch,
            delete: apiDelete
        },

        // Modal Management
        modal: {
            open: openModal,
            close: closeModal,
            closeAll: closeAllModals,
            init: initModal
        },

        // Status/Notifications
        status: {
            show: showStatus,
            hide: hideStatus,
            toast: showToast
        },

        // Formatting
        format: {
            fileSize: formatFileSize,
            duration: formatDuration,
            relativeTime: formatRelativeTime
        },

        // Pickers
        picker: {
            initIcon: initIconPicker,
            initColor: initColorPicker
        },

        // Forms
        form: {
            serialize: serializeForm,
            setDisabled: setFormDisabled
        },

        // Upload
        upload: {
            initDragDrop: initDragDropUpload,
            withProgress: uploadWithProgress
        },

        // Video
        video: {
            create: createVideoPlayer
        },

        // Utilities
        util: {
            confirm: confirm,
            debounce: debounce,
            throttle: throttle
        }
    };

})(window);

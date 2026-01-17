/**
 * Content Catalog Partner Portal - Shared Frontend JavaScript
 *
 * This module provides common functionality used across all Partner Portal pages:
 * - API helpers for fetch requests
 * - Modal management
 * - Status/notification display
 * - Form utilities
 * - Upload progress tracking
 * - Asset management helpers
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
        document.querySelectorAll('.modal-overlay.active').forEach(modal => {
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
        const closeBtn = modal.querySelector('.modal-close');
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
        loading: { icon: '&#8987;', className: 'info' },
        success: { icon: '&#10003;', className: 'success' },
        error: { icon: '&#10007;', className: 'error' },
        warning: { icon: '&#9888;', className: 'warning' },
        info: { icon: '&#9432;', className: 'info' }
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
        statusEl.className = `upload-status visible ${style.className}`;
        statusEl.innerHTML = `<span class="status-icon">${style.icon}</span> ${message}`;
    }

    /**
     * Hide a status element
     * @param {string} elementId - The status element ID
     */
    function hideStatus(elementId) {
        const statusEl = document.getElementById(elementId);
        if (statusEl) {
            statusEl.style.display = 'none';
            statusEl.classList.remove('visible');
        }
    }

    /**
     * Show a toast notification (auto-dismissing)
     * @param {string} message - The message to display
     * @param {string} type - Notification type: 'success', 'error', 'warning', 'info'
     * @param {number} duration - Duration in ms (default: 5000)
     */
    function showToast(message, type = 'info', duration = 5000) {
        const style = STATUS_STYLES[type] || STATUS_STYLES.info;

        // Create notification element
        const notification = document.createElement('div');
        notification.className = `flash-message ${style.className}`;
        notification.innerHTML = `
            <span class="flash-icon">${style.icon}</span>
            <span class="flash-text">${message}</span>
            <button class="flash-close" aria-label="Close notification">&times;</button>
        `;

        // Add close button handler
        notification.querySelector('.flash-close').addEventListener('click', function() {
            removeNotification(notification);
        });

        // Add to page
        let container = document.querySelector('.flash-messages');
        if (!container) {
            container = document.createElement('div');
            container.className = 'flash-messages';
            const pageContent = document.querySelector('.page-content');
            if (pageContent) {
                pageContent.prepend(container);
            } else {
                document.body.prepend(container);
            }
        }
        container.appendChild(notification);

        // Auto-remove after duration
        setTimeout(() => {
            removeNotification(notification);
        }, duration);
    }

    /**
     * Remove a notification element with animation
     * @param {HTMLElement} notification - The notification element
     */
    function removeNotification(notification) {
        if (!notification || !notification.parentNode) return;

        notification.style.opacity = '0';
        notification.style.transform = 'translateX(100px)';
        setTimeout(() => {
            if (notification.parentNode) {
                notification.remove();
            }
        }, 300);
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
            return Math.round(seconds) + 's';
        }
        const minutes = Math.floor(seconds / 60);
        const remainingSeconds = Math.round(seconds % 60);
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

    /**
     * Format a date string to a readable date/time
     * @param {string} dateStr - ISO date string
     * @param {Object} options - Intl.DateTimeFormat options
     * @returns {string} - Formatted date string
     */
    function formatDate(dateStr, options = {}) {
        if (!dateStr) return '-';
        const date = new Date(dateStr);
        const defaultOptions = {
            year: 'numeric',
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        };
        return date.toLocaleDateString(undefined, { ...defaultOptions, ...options });
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

    /**
     * Reset form to initial state
     * @param {HTMLFormElement|string} form - Form element or ID
     */
    function resetForm(form) {
        if (typeof form === 'string') {
            form = document.getElementById(form);
        }
        if (form) {
            form.reset();
        }
    }

    /**
     * Validate form fields
     * @param {HTMLFormElement} form - The form element
     * @returns {boolean} - Whether the form is valid
     */
    function validateForm(form) {
        return form.checkValidity();
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
            selectedClass = 'selected',
            maxSize = 500 * 1024 * 1024, // 500MB default
            acceptedTypes = null
        } = options;

        // Handle drag events
        area.addEventListener('dragover', (e) => {
            e.preventDefault();
            area.classList.add(activeClass);
            if (onDragOver) onDragOver(e);
        });

        area.addEventListener('dragleave', (e) => {
            // Only trigger if leaving the actual drop area
            if (!area.contains(e.relatedTarget)) {
                area.classList.remove(activeClass);
                if (onDragLeave) onDragLeave();
            }
        });

        area.addEventListener('drop', (e) => {
            e.preventDefault();
            area.classList.remove(activeClass);

            if (e.dataTransfer.files.length > 0) {
                const file = e.dataTransfer.files[0];

                // Validate file size
                if (file.size > maxSize) {
                    showToast(`File too large. Maximum size is ${formatFileSize(maxSize)}`, 'error');
                    return;
                }

                // Validate file type if specified
                if (acceptedTypes && !acceptedTypes.includes(file.type)) {
                    showToast('File type not supported', 'error');
                    return;
                }

                input.files = e.dataTransfer.files;
                area.classList.add(selectedClass);
                if (onFileSelect) onFileSelect(file);
            }
        });

        // Handle file input change
        input.addEventListener('change', function() {
            if (this.files.length > 0) {
                const file = this.files[0];

                // Validate file size
                if (file.size > maxSize) {
                    showToast(`File too large. Maximum size is ${formatFileSize(maxSize)}`, 'error');
                    this.value = '';
                    return;
                }

                area.classList.add(selectedClass);
                if (onFileSelect) onFileSelect(file);
            } else {
                area.classList.remove(selectedClass);
            }
        });

        // Click on area triggers file input
        area.addEventListener('click', (e) => {
            if (e.target === area || !e.target.closest('input')) {
                input.click();
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
        const { onProgress, onComplete, onError, onStart } = options;

        return new Promise((resolve, reject) => {
            const xhr = new XMLHttpRequest();

            if (onStart) onStart();

            xhr.upload.addEventListener('progress', (e) => {
                if (e.lengthComputable && onProgress) {
                    const percentComplete = Math.round((e.loaded / e.total) * 100);
                    onProgress(percentComplete, e.loaded, e.total);
                }
            });

            xhr.addEventListener('load', () => {
                try {
                    const data = JSON.parse(xhr.responseText);
                    if (xhr.status >= 200 && xhr.status < 300) {
                        if (onComplete) onComplete(data);
                        resolve(data);
                    } else {
                        const error = new Error(data.error || data.message || 'Upload failed');
                        error.status = xhr.status;
                        error.data = data;
                        if (onError) onError(error);
                        reject(error);
                    }
                } catch (e) {
                    const error = new Error('Invalid response from server');
                    if (onError) onError(error);
                    reject(error);
                }
            });

            xhr.addEventListener('error', () => {
                const error = new Error('Network error during upload');
                if (onError) onError(error);
                reject(error);
            });

            xhr.addEventListener('abort', () => {
                const error = new Error('Upload cancelled');
                error.aborted = true;
                if (onError) onError(error);
                reject(error);
            });

            xhr.open('POST', url);
            xhr.send(formData);
        });
    }

    /**
     * Update progress bar UI
     * @param {string} containerId - Progress container element ID
     * @param {number} percent - Progress percentage
     * @param {string} text - Optional progress text
     */
    function updateProgress(containerId, percent, text) {
        const container = document.getElementById(containerId);
        if (!container) return;

        const fill = container.querySelector('.progress-fill');
        const textEl = container.querySelector('.progress-text');

        if (fill) {
            fill.style.width = percent + '%';
        }

        if (textEl && text) {
            textEl.textContent = text;
        }

        // Show container if hidden
        container.classList.add('visible');
    }

    /**
     * Hide progress bar
     * @param {string} containerId - Progress container element ID
     */
    function hideProgress(containerId) {
        const container = document.getElementById(containerId);
        if (container) {
            container.classList.remove('visible');
        }
    }

    // =========================================================================
    // Tags Input Handler
    // =========================================================================

    /**
     * Initialize a tags input field
     * @param {string} wrapperId - Tags wrapper element ID
     * @param {string} inputId - Text input element ID
     * @param {string} hiddenId - Hidden input element ID for storing tags
     * @param {Object} options - Configuration options
     * @returns {Object} - Tags controller with getTags, addTag, removeTag methods
     */
    function initTagsInput(wrapperId, inputId, hiddenId, options = {}) {
        const wrapper = document.getElementById(wrapperId);
        const input = document.getElementById(inputId);
        const hidden = document.getElementById(hiddenId);

        if (!wrapper || !input || !hidden) return null;

        const {
            maxTags = 10,
            delimiter = ',',
            onChange
        } = options;

        let tags = [];

        // Parse existing tags from hidden input
        if (hidden.value) {
            tags = hidden.value.split(delimiter).map(t => t.trim()).filter(t => t);
        }

        function renderTags() {
            // Remove existing tag items
            wrapper.querySelectorAll('.tag-item').forEach(el => el.remove());

            // Add tags before input
            tags.forEach((tag, index) => {
                const tagEl = document.createElement('span');
                tagEl.className = 'tag-item';
                tagEl.innerHTML = `${escapeHtml(tag)}<button type="button" aria-label="Remove tag">&times;</button>`;
                tagEl.querySelector('button').addEventListener('click', () => {
                    removeTag(index);
                });
                input.parentElement.insertBefore(tagEl, input);
            });

            // Update hidden input
            hidden.value = tags.join(delimiter);

            if (onChange) onChange(tags);
        }

        function addTag(value) {
            value = value.trim();
            if (!value) return false;
            if (tags.includes(value)) return false;
            if (tags.length >= maxTags) {
                showToast(`Maximum ${maxTags} tags allowed`, 'warning');
                return false;
            }
            tags.push(value);
            renderTags();
            return true;
        }

        function removeTag(index) {
            tags.splice(index, 1);
            renderTags();
        }

        // Handle keyboard input
        input.addEventListener('keydown', function(e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                if (addTag(this.value)) {
                    this.value = '';
                }
            }
            if (e.key === 'Backspace' && !this.value && tags.length > 0) {
                removeTag(tags.length - 1);
            }
        });

        // Focus input when clicking wrapper
        wrapper.addEventListener('click', () => {
            input.focus();
        });

        // Initial render
        renderTags();

        return {
            getTags: () => [...tags],
            addTag: addTag,
            removeTag: removeTag,
            setTags: (newTags) => {
                tags = [...newTags];
                renderTags();
            },
            clear: () => {
                tags = [];
                renderTags();
            }
        };
    }

    // =========================================================================
    // Category Picker
    // =========================================================================

    /**
     * Initialize category picker with visual selection
     * @param {string} containerSelector - CSS selector for category container
     * @param {Function} onChange - Callback when selection changes
     * @returns {Object} - Category controller with getSelected, setSelected methods
     */
    function initCategoryPicker(containerSelector, onChange) {
        const container = document.querySelector(containerSelector);
        if (!container) return null;

        const options = container.querySelectorAll('.category-option');
        let selectedValue = null;

        // Find initially selected
        options.forEach(option => {
            const input = option.querySelector('input');
            if (input && input.checked) {
                selectedValue = input.value;
                option.classList.add('selected');
            }
        });

        // Add click handlers
        options.forEach(option => {
            option.addEventListener('click', function() {
                options.forEach(o => o.classList.remove('selected'));
                this.classList.add('selected');

                const input = this.querySelector('input');
                if (input) {
                    input.checked = true;
                    selectedValue = input.value;
                }

                if (onChange) onChange(selectedValue);
            });
        });

        return {
            getSelected: () => selectedValue,
            setSelected: (value) => {
                options.forEach(option => {
                    const input = option.querySelector('input');
                    if (input && input.value === value) {
                        options.forEach(o => o.classList.remove('selected'));
                        option.classList.add('selected');
                        input.checked = true;
                        selectedValue = value;
                    }
                });
            }
        };
    }

    // =========================================================================
    // Asset Management Helpers
    // =========================================================================

    /**
     * Submit an asset for review
     * @param {string} assetUuid - Asset UUID
     * @param {Object} options - Additional options
     * @returns {Promise<Object>} - Response data
     */
    async function submitAssetForReview(assetUuid, options = {}) {
        if (!options.skipConfirm && !window.confirm('Submit this asset for review?')) {
            return null;
        }

        try {
            const data = await apiPost(`/api/v1/partner/assets/${assetUuid}/submit`, {
                notes: options.notes || ''
            });
            showToast('Asset submitted for review', 'success');
            if (options.onSuccess) options.onSuccess(data);
            return data;
        } catch (error) {
            showToast(error.message || 'Failed to submit asset', 'error');
            if (options.onError) options.onError(error);
            throw error;
        }
    }

    /**
     * Delete an asset (drafts only)
     * @param {string} assetUuid - Asset UUID
     * @param {string} assetTitle - Asset title for confirmation
     * @param {Object} options - Additional options
     * @returns {Promise<Object>} - Response data
     */
    async function deleteAsset(assetUuid, assetTitle, options = {}) {
        if (!options.skipConfirm && !window.confirm(`Are you sure you want to delete "${assetTitle}"? This cannot be undone.`)) {
            return null;
        }

        try {
            const data = await apiDelete(`/api/v1/partner/assets/${assetUuid}`);
            showToast('Asset deleted successfully', 'success');
            if (options.onSuccess) options.onSuccess(data);
            return data;
        } catch (error) {
            showToast(error.message || 'Failed to delete asset', 'error');
            if (options.onError) options.onError(error);
            throw error;
        }
    }

    /**
     * Get asset details
     * @param {string} assetUuid - Asset UUID
     * @returns {Promise<Object>} - Asset data
     */
    async function getAsset(assetUuid) {
        return apiGet(`/api/v1/partner/assets/${assetUuid}`);
    }

    /**
     * Update asset metadata
     * @param {string} assetUuid - Asset UUID
     * @param {Object} metadata - Updated metadata
     * @param {Object} options - Additional options
     * @returns {Promise<Object>} - Response data
     */
    async function updateAsset(assetUuid, metadata, options = {}) {
        try {
            const data = await apiPut(`/api/v1/partner/assets/${assetUuid}`, metadata);
            showToast('Asset updated successfully', 'success');
            if (options.onSuccess) options.onSuccess(data);
            return data;
        } catch (error) {
            showToast(error.message || 'Failed to update asset', 'error');
            if (options.onError) options.onError(error);
            throw error;
        }
    }

    // =========================================================================
    // Utility Functions
    // =========================================================================

    /**
     * Escape HTML special characters
     * @param {string} str - String to escape
     * @returns {string} - Escaped string
     */
    function escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    /**
     * Show a confirmation dialog
     * @param {string} message - The confirmation message
     * @param {Object} options - Configuration options
     * @returns {Promise<boolean>} - True if confirmed, false otherwise
     */
    function confirmAction(message, options = {}) {
        return Promise.resolve(window.confirm(message));
    }

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

    /**
     * Copy text to clipboard
     * @param {string} text - Text to copy
     * @returns {Promise<boolean>} - True if successful
     */
    async function copyToClipboard(text) {
        try {
            await navigator.clipboard.writeText(text);
            showToast('Copied to clipboard', 'success', 2000);
            return true;
        } catch (error) {
            showToast('Failed to copy to clipboard', 'error');
            return false;
        }
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

        // Auto-initialize modals with modal-overlay class
        document.querySelectorAll('.modal-overlay').forEach(modal => {
            if (modal.id) {
                initModal(modal.id);
            }
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

    window.Partner = {
        // API Helpers
        api: {
            request: apiRequest,
            get: apiGet,
            post: apiPost,
            put: apiPut,
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
            relativeTime: formatRelativeTime,
            date: formatDate
        },

        // Forms
        form: {
            serialize: serializeForm,
            setDisabled: setFormDisabled,
            reset: resetForm,
            validate: validateForm
        },

        // Upload
        upload: {
            initDragDrop: initDragDropUpload,
            withProgress: uploadWithProgress,
            updateProgress: updateProgress,
            hideProgress: hideProgress
        },

        // Input Handlers
        input: {
            initTags: initTagsInput,
            initCategory: initCategoryPicker
        },

        // Asset Management
        asset: {
            submitForReview: submitAssetForReview,
            delete: deleteAsset,
            get: getAsset,
            update: updateAsset
        },

        // Utilities
        util: {
            confirm: confirmAction,
            debounce: debounce,
            throttle: throttle,
            escapeHtml: escapeHtml,
            copyToClipboard: copyToClipboard
        }
    };

})(window);

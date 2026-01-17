/**
 * Content Catalog Admin Portal - Shared Frontend JavaScript
 *
 * This module provides common functionality used across all Admin Portal pages:
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
        statusEl.className = `status-message ${style.className}`;
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
    // User Management Helpers
    // =========================================================================

    /**
     * Approve a user
     * @param {number} userId - User ID
     * @param {string} userName - User name for confirmation
     * @param {Object} options - Additional options
     * @returns {Promise<Object>} - Response data
     */
    async function approveUser(userId, userName, options = {}) {
        if (!options.skipConfirm && !window.confirm(`Are you sure you want to approve "${userName}"?`)) {
            return null;
        }

        try {
            const data = await apiPost(`/api/v1/approvals/${userId}/approve`, {
                status: 'active',
                notes: options.notes || ''
            });
            showToast('User approved successfully', 'success');
            if (options.onSuccess) options.onSuccess(data);
            return data;
        } catch (error) {
            showToast(error.message || 'Failed to approve user', 'error');
            if (options.onError) options.onError(error);
            throw error;
        }
    }

    /**
     * Reject a user
     * @param {number} userId - User ID
     * @param {string} reason - Rejection reason
     * @param {Object} options - Additional options
     * @returns {Promise<Object>} - Response data
     */
    async function rejectUser(userId, reason, options = {}) {
        if (!reason || !reason.trim()) {
            showToast('Please provide a rejection reason', 'warning');
            return null;
        }

        try {
            const data = await apiPost(`/api/v1/approvals/${userId}/reject`, {
                reason: reason.trim()
            });
            showToast('User rejected successfully', 'success');
            if (options.onSuccess) options.onSuccess(data);
            return data;
        } catch (error) {
            showToast(error.message || 'Failed to reject user', 'error');
            if (options.onError) options.onError(error);
            throw error;
        }
    }

    /**
     * Suspend a user
     * @param {number} userId - User ID
     * @param {string} userName - User name for confirmation
     * @param {Object} options - Additional options
     * @returns {Promise<Object>} - Response data
     */
    async function suspendUser(userId, userName, options = {}) {
        if (!options.skipConfirm && !window.confirm(`Are you sure you want to suspend "${userName}"?`)) {
            return null;
        }

        try {
            const data = await apiPost(`/api/v1/users/${userId}/suspend`, {
                reason: options.reason || ''
            });
            showToast('User suspended successfully', 'success');
            if (options.onSuccess) options.onSuccess(data);
            return data;
        } catch (error) {
            showToast(error.message || 'Failed to suspend user', 'error');
            if (options.onError) options.onError(error);
            throw error;
        }
    }

    /**
     * Reactivate a user
     * @param {number} userId - User ID
     * @param {string} userName - User name for confirmation
     * @param {Object} options - Additional options
     * @returns {Promise<Object>} - Response data
     */
    async function reactivateUser(userId, userName, options = {}) {
        if (!options.skipConfirm && !window.confirm(`Are you sure you want to reactivate "${userName}"?`)) {
            return null;
        }

        try {
            const data = await apiPost(`/api/v1/users/${userId}/reactivate`, {});
            showToast('User reactivated successfully', 'success');
            if (options.onSuccess) options.onSuccess(data);
            return data;
        } catch (error) {
            showToast(error.message || 'Failed to reactivate user', 'error');
            if (options.onError) options.onError(error);
            throw error;
        }
    }

    /**
     * Get user details
     * @param {number} userId - User ID
     * @returns {Promise<Object>} - User data
     */
    async function getUser(userId) {
        return apiGet(`/api/v1/users/${userId}`);
    }

    // =========================================================================
    // Content Asset Helpers
    // =========================================================================

    /**
     * Submit an asset for review
     * @param {string} assetId - Asset UUID
     * @param {Object} options - Additional options
     * @returns {Promise<Object>} - Response data
     */
    async function submitAssetForReview(assetId, options = {}) {
        try {
            const data = await apiPost(`/api/v1/assets/${assetId}/submit`, {
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
     * Approve an asset
     * @param {string} assetId - Asset UUID
     * @param {Object} options - Additional options
     * @returns {Promise<Object>} - Response data
     */
    async function approveAsset(assetId, options = {}) {
        try {
            const data = await apiPost(`/api/v1/assets/${assetId}/approve`, {
                notes: options.notes || ''
            });
            showToast('Asset approved successfully', 'success');
            if (options.onSuccess) options.onSuccess(data);
            return data;
        } catch (error) {
            showToast(error.message || 'Failed to approve asset', 'error');
            if (options.onError) options.onError(error);
            throw error;
        }
    }

    /**
     * Reject an asset
     * @param {string} assetId - Asset UUID
     * @param {string} reason - Rejection reason
     * @param {Object} options - Additional options
     * @returns {Promise<Object>} - Response data
     */
    async function rejectAsset(assetId, reason, options = {}) {
        if (!reason || !reason.trim()) {
            showToast('Please provide a rejection reason', 'warning');
            return null;
        }

        try {
            const data = await apiPost(`/api/v1/assets/${assetId}/reject`, {
                reason: reason.trim()
            });
            showToast('Asset rejected', 'success');
            if (options.onSuccess) options.onSuccess(data);
            return data;
        } catch (error) {
            showToast(error.message || 'Failed to reject asset', 'error');
            if (options.onError) options.onError(error);
            throw error;
        }
    }

    /**
     * Publish an asset
     * @param {string} assetId - Asset UUID
     * @param {Object} options - Additional options
     * @returns {Promise<Object>} - Response data
     */
    async function publishAsset(assetId, options = {}) {
        try {
            const data = await apiPost(`/api/v1/assets/${assetId}/publish`, {});
            showToast('Asset published successfully', 'success');
            if (options.onSuccess) options.onSuccess(data);
            return data;
        } catch (error) {
            showToast(error.message || 'Failed to publish asset', 'error');
            if (options.onError) options.onError(error);
            throw error;
        }
    }

    /**
     * Get asset details
     * @param {string} assetId - Asset UUID
     * @returns {Promise<Object>} - Asset data
     */
    async function getAsset(assetId) {
        return apiGet(`/api/v1/assets/${assetId}`);
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
    function confirmAction(message, options = {}) {
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
    // Table Utilities
    // =========================================================================

    /**
     * Initialize sortable table headers
     * @param {string} tableId - Table element ID
     * @param {Function} onSort - Callback when sorting changes
     */
    function initSortableTable(tableId, onSort) {
        const table = document.getElementById(tableId);
        if (!table) return;

        const headers = table.querySelectorAll('th[data-sort]');
        headers.forEach(header => {
            header.style.cursor = 'pointer';
            header.addEventListener('click', function() {
                const field = this.dataset.sort;
                const currentOrder = this.dataset.order || 'asc';
                const newOrder = currentOrder === 'asc' ? 'desc' : 'asc';

                // Update all headers
                headers.forEach(h => {
                    h.dataset.order = '';
                    h.classList.remove('sorted-asc', 'sorted-desc');
                });

                // Update clicked header
                this.dataset.order = newOrder;
                this.classList.add(`sorted-${newOrder}`);

                if (onSort) onSort(field, newOrder);
            });
        });
    }

    /**
     * Update table row after action
     * @param {number|string} rowId - Row identifier
     * @param {Object} data - New data for the row
     * @param {Function} renderFn - Function to render row HTML
     */
    function updateTableRow(rowId, data, renderFn) {
        const row = document.querySelector(`tr[data-user-id="${rowId}"], tr[data-asset-id="${rowId}"]`);
        if (row && renderFn) {
            const newRow = document.createElement('tr');
            newRow.innerHTML = renderFn(data);
            row.replaceWith(newRow);
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

    window.Admin = {
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
            withProgress: uploadWithProgress
        },

        // User Management
        user: {
            approve: approveUser,
            reject: rejectUser,
            suspend: suspendUser,
            reactivate: reactivateUser,
            get: getUser
        },

        // Content Assets
        asset: {
            submitForReview: submitAssetForReview,
            approve: approveAsset,
            reject: rejectAsset,
            publish: publishAsset,
            get: getAsset
        },

        // Table Utilities
        table: {
            initSortable: initSortableTable,
            updateRow: updateTableRow
        },

        // Utilities
        util: {
            confirm: confirmAction,
            debounce: debounce,
            throttle: throttle
        }
    };

})(window);

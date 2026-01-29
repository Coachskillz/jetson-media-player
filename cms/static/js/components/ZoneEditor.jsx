/**
 * ZoneEditor - A Photoshop-style draggable zone editor
 *
 * Features:
 * - Drag zones to reposition
 * - Resize zones with 8-point handles
 * - Percentage-based positioning
 * - Touch + mouse support via Pointer Events
 * - 60fps smooth dragging
 * - Constrained to canvas bounds
 */

import React, { useState, useRef, useCallback, useEffect } from 'react';

// ============================================================================
// Constants
// ============================================================================

const HANDLE_SIZE = 12;
const MIN_ZONE_SIZE = 20;
const COLORS = ['#00D4AA', '#667EEA', '#F59E0B', '#EF4444', '#8B5CF6', '#EC4899'];

// Handle positions for 8-point resize
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

// ============================================================================
// ZoneEditor Component
// ============================================================================

export default function ZoneEditor({
  canvasWidth = 1920,
  canvasHeight = 1080,
  initialZones = [],
  onChange,
  zoom = 0.5
}) {
  // State
  const [zones, setZones] = useState(() =>
    initialZones.length > 0 ? initialZones : [
      { id: '1', x: 0, y: 0, width: 100, height: 100, z: 1, name: 'Zone 1', color: COLORS[0] }
    ]
  );
  const [selectedId, setSelectedId] = useState(null);
  const [dragState, setDragState] = useState(null);

  // Refs
  const canvasRef = useRef(null);
  const rafRef = useRef(null);
  const pendingUpdate = useRef(null);

  // Scaled dimensions
  const scaledWidth = canvasWidth * zoom;
  const scaledHeight = canvasHeight * zoom;

  // ============================================================================
  // Utility Functions
  // ============================================================================

  // Convert percentage to pixels
  const pctToPixels = useCallback((pct, dimension) => {
    const size = dimension === 'x' || dimension === 'width' ? canvasWidth : canvasHeight;
    return (pct / 100) * size;
  }, [canvasWidth, canvasHeight]);

  // Convert pixels to percentage
  const pixelsToPct = useCallback((pixels, dimension) => {
    const size = dimension === 'x' || dimension === 'width' ? canvasWidth : canvasHeight;
    return (pixels / size) * 100;
  }, [canvasWidth, canvasHeight]);

  // Constrain zone to canvas bounds
  const constrainZone = useCallback((zone) => {
    const x = Math.max(0, Math.min(100 - zone.width, zone.x));
    const y = Math.max(0, Math.min(100 - zone.height, zone.y));
    const width = Math.max(pixelsToPct(MIN_ZONE_SIZE, 'width'), Math.min(100 - x, zone.width));
    const height = Math.max(pixelsToPct(MIN_ZONE_SIZE, 'height'), Math.min(100 - y, zone.height));
    return { ...zone, x, y, width, height };
  }, [pixelsToPct]);

  // Get pointer position relative to canvas
  const getPointerPosition = useCallback((e) => {
    if (!canvasRef.current) return { x: 0, y: 0 };
    const rect = canvasRef.current.getBoundingClientRect();
    return {
      x: (e.clientX - rect.left) / zoom,
      y: (e.clientY - rect.top) / zoom
    };
  }, [zoom]);

  // ============================================================================
  // Zone Operations
  // ============================================================================

  // Bring zone to front
  const bringToFront = useCallback((id) => {
    setZones(prev => {
      const maxZ = Math.max(...prev.map(z => z.z));
      return prev.map(z => z.id === id ? { ...z, z: maxZ + 1 } : z);
    });
  }, []);

  // Update a zone
  const updateZone = useCallback((id, updates) => {
    setZones(prev => {
      const newZones = prev.map(z => z.id === id ? constrainZone({ ...z, ...updates }) : z);
      onChange?.(newZones);
      return newZones;
    });
  }, [constrainZone, onChange]);

  // Add new zone
  const addZone = useCallback(() => {
    const newId = String(Date.now());
    const maxZ = zones.length > 0 ? Math.max(...zones.map(z => z.z)) : 0;
    const newZone = {
      id: newId,
      x: 10,
      y: 10,
      width: 30,
      height: 30,
      z: maxZ + 1,
      name: `Zone ${zones.length + 1}`,
      color: COLORS[zones.length % COLORS.length]
    };
    setZones(prev => [...prev, newZone]);
    setSelectedId(newId);
  }, [zones]);

  // Delete selected zone
  const deleteZone = useCallback(() => {
    if (!selectedId) return;
    setZones(prev => prev.filter(z => z.id !== selectedId));
    setSelectedId(null);
  }, [selectedId]);

  // ============================================================================
  // Drag Handling with 60fps Updates
  // ============================================================================

  const handlePointerDown = useCallback((e, zoneId, handle = null) => {
    e.preventDefault();
    e.stopPropagation();

    // Capture pointer for smooth dragging
    e.target.setPointerCapture(e.pointerId);

    const pos = getPointerPosition(e);
    const zone = zones.find(z => z.id === zoneId);
    if (!zone) return;

    // Select and bring to front
    setSelectedId(zoneId);
    bringToFront(zoneId);

    // Store initial state for dragging
    setDragState({
      zoneId,
      handle,
      startX: pos.x,
      startY: pos.y,
      initialZone: { ...zone }
    });
  }, [zones, getPointerPosition, bringToFront]);

  const handlePointerMove = useCallback((e) => {
    if (!dragState) return;

    const pos = getPointerPosition(e);
    const { zoneId, handle, startX, startY, initialZone } = dragState;

    // Calculate delta in pixels, then convert to percentage
    const deltaXPx = pos.x - startX;
    const deltaYPx = pos.y - startY;
    const deltaX = pixelsToPct(deltaXPx, 'x');
    const deltaY = pixelsToPct(deltaYPx, 'y');

    // Store pending update for RAF
    pendingUpdate.current = { zoneId, handle, deltaX, deltaY, initialZone };

    // Use RAF for 60fps updates
    if (!rafRef.current) {
      rafRef.current = requestAnimationFrame(() => {
        if (pendingUpdate.current) {
          const { zoneId, handle, deltaX, deltaY, initialZone } = pendingUpdate.current;

          let updates = {};

          if (!handle) {
            // Moving the entire zone
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
                updates = {
                  width: initialZone.width + deltaX
                };
                break;
              case 'bl':
                updates = {
                  x: initialZone.x + deltaX,
                  width: initialZone.width - deltaX,
                  height: initialZone.height + deltaY
                };
                break;
              case 'bm':
                updates = {
                  height: initialZone.height + deltaY
                };
                break;
              case 'br':
                updates = {
                  width: initialZone.width + deltaX,
                  height: initialZone.height + deltaY
                };
                break;
            }
          }

          updateZone(zoneId, updates);
        }
        rafRef.current = null;
      });
    }
  }, [dragState, getPointerPosition, pixelsToPct, updateZone]);

  const handlePointerUp = useCallback((e) => {
    if (dragState) {
      e.target.releasePointerCapture(e.pointerId);
    }
    setDragState(null);
    pendingUpdate.current = null;
    if (rafRef.current) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
  }, [dragState]);

  // Canvas click to deselect
  const handleCanvasClick = useCallback((e) => {
    if (e.target === canvasRef.current) {
      setSelectedId(null);
    }
  }, []);

  // ============================================================================
  // Keyboard Shortcuts
  // ============================================================================

  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Delete' || e.key === 'Backspace') {
        if (selectedId && document.activeElement.tagName !== 'INPUT') {
          e.preventDefault();
          deleteZone();
        }
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [selectedId, deleteZone]);

  // ============================================================================
  // Render
  // ============================================================================

  const selectedZone = zones.find(z => z.id === selectedId);

  return (
    <div style={styles.container}>
      {/* Toolbar */}
      <div style={styles.toolbar}>
        <button style={styles.button} onClick={addZone}>
          + Add Zone
        </button>
        <button
          style={{ ...styles.button, ...(!selectedId && styles.buttonDisabled) }}
          onClick={deleteZone}
          disabled={!selectedId}
        >
          Delete
        </button>
        <span style={styles.info}>
          Canvas: {canvasWidth} x {canvasHeight} | Zoom: {Math.round(zoom * 100)}%
        </span>
      </div>

      {/* Canvas Area */}
      <div style={styles.canvasContainer}>
        <div
          ref={canvasRef}
          style={{
            ...styles.canvas,
            width: scaledWidth,
            height: scaledHeight,
          }}
          onClick={handleCanvasClick}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onPointerLeave={handlePointerUp}
        >
          {/* Render zones sorted by z-index */}
          {[...zones].sort((a, b) => a.z - b.z).map(zone => {
            const isSelected = zone.id === selectedId;
            const x = (zone.x / 100) * scaledWidth;
            const y = (zone.y / 100) * scaledHeight;
            const width = (zone.width / 100) * scaledWidth;
            const height = (zone.height / 100) * scaledHeight;

            return (
              <div
                key={zone.id}
                style={{
                  ...styles.zone,
                  left: x,
                  top: y,
                  width,
                  height,
                  borderColor: zone.color,
                  backgroundColor: isSelected ? `${zone.color}33` : `${zone.color}1A`,
                  zIndex: zone.z,
                  cursor: dragState?.zoneId === zone.id ? 'grabbing' : 'grab',
                }}
                onPointerDown={(e) => handlePointerDown(e, zone.id)}
              >
                {/* Zone Label */}
                <div style={styles.zoneLabel}>{zone.name}</div>

                {/* Dimensions */}
                <div style={styles.zoneDims}>
                  {zone.width.toFixed(1)}% x {zone.height.toFixed(1)}%
                </div>

                {/* Resize Handles (only when selected) */}
                {isSelected && HANDLES.map(handle => (
                  <div
                    key={handle.id}
                    style={{
                      ...styles.handle,
                      left: handle.x * 100 + '%',
                      top: handle.y * 100 + '%',
                      cursor: handle.cursor,
                      backgroundColor: zone.color,
                    }}
                    onPointerDown={(e) => handlePointerDown(e, zone.id, handle.id)}
                  />
                ))}
              </div>
            );
          })}
        </div>
      </div>

      {/* Properties Panel */}
      {selectedZone && (
        <div style={styles.properties}>
          <h3 style={styles.propTitle}>Zone Properties</h3>
          <div style={styles.propGrid}>
            <label style={styles.propLabel}>Name</label>
            <input
              style={styles.propInput}
              value={selectedZone.name}
              onChange={(e) => updateZone(selectedId, { name: e.target.value })}
            />

            <label style={styles.propLabel}>Left (%)</label>
            <input
              type="number"
              style={styles.propInput}
              value={selectedZone.x.toFixed(1)}
              onChange={(e) => updateZone(selectedId, { x: parseFloat(e.target.value) || 0 })}
              step="0.1"
              min="0"
              max="100"
            />

            <label style={styles.propLabel}>Top (%)</label>
            <input
              type="number"
              style={styles.propInput}
              value={selectedZone.y.toFixed(1)}
              onChange={(e) => updateZone(selectedId, { y: parseFloat(e.target.value) || 0 })}
              step="0.1"
              min="0"
              max="100"
            />

            <label style={styles.propLabel}>Width (%)</label>
            <input
              type="number"
              style={styles.propInput}
              value={selectedZone.width.toFixed(1)}
              onChange={(e) => updateZone(selectedId, { width: parseFloat(e.target.value) || 1 })}
              step="0.1"
              min="1"
              max="100"
            />

            <label style={styles.propLabel}>Height (%)</label>
            <input
              type="number"
              style={styles.propInput}
              value={selectedZone.height.toFixed(1)}
              onChange={(e) => updateZone(selectedId, { height: parseFloat(e.target.value) || 1 })}
              step="0.1"
              min="1"
              max="100"
            />
          </div>

          <div style={styles.pixelInfo}>
            Pixels: {Math.round(pctToPixels(selectedZone.x, 'x'))}, {Math.round(pctToPixels(selectedZone.y, 'y'))} - {Math.round(pctToPixels(selectedZone.width, 'width'))} x {Math.round(pctToPixels(selectedZone.height, 'height'))}
          </div>
        </div>
      )}
    </div>
  );
}

// ============================================================================
// Styles
// ============================================================================

const styles = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    height: '100%',
    backgroundColor: '#1a1a1f',
    color: '#fff',
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
  },
  toolbar: {
    display: 'flex',
    alignItems: 'center',
    gap: '12px',
    padding: '12px 16px',
    backgroundColor: '#2d2d35',
    borderBottom: '1px solid #3d3d45',
  },
  button: {
    padding: '8px 16px',
    backgroundColor: '#00D4AA',
    color: '#1a1a1f',
    border: 'none',
    borderRadius: '6px',
    fontSize: '14px',
    fontWeight: '600',
    cursor: 'pointer',
    transition: 'opacity 0.2s',
  },
  buttonDisabled: {
    opacity: 0.5,
    cursor: 'not-allowed',
  },
  info: {
    marginLeft: 'auto',
    color: '#888',
    fontSize: '13px',
  },
  canvasContainer: {
    flex: 1,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    padding: '40px',
    backgroundColor: '#1a1a2e',
    overflow: 'auto',
  },
  canvas: {
    position: 'relative',
    backgroundColor: '#000',
    border: '3px solid #667eea',
    boxShadow: '0 0 0 1px rgba(102, 126, 234, 0.3), 0 20px 60px rgba(0, 0, 0, 0.5)',
    touchAction: 'none', // Prevent browser handling of touch
  },
  zone: {
    position: 'absolute',
    border: '2px solid',
    boxSizing: 'border-box',
    userSelect: 'none',
    touchAction: 'none',
    transition: 'background-color 0.15s',
  },
  zoneLabel: {
    position: 'absolute',
    top: '8px',
    left: '8px',
    fontSize: '12px',
    fontWeight: '600',
    color: '#fff',
    textShadow: '0 1px 2px rgba(0,0,0,0.5)',
  },
  zoneDims: {
    position: 'absolute',
    bottom: '8px',
    right: '8px',
    fontSize: '10px',
    color: 'rgba(255,255,255,0.7)',
    fontFamily: 'Monaco, Menlo, monospace',
  },
  handle: {
    position: 'absolute',
    width: HANDLE_SIZE,
    height: HANDLE_SIZE,
    transform: 'translate(-50%, -50%)',
    border: '2px solid #1a1a1f',
    borderRadius: '2px',
    touchAction: 'none',
  },
  properties: {
    padding: '16px',
    backgroundColor: '#2d2d35',
    borderTop: '1px solid #3d3d45',
  },
  propTitle: {
    margin: '0 0 12px 0',
    fontSize: '14px',
    fontWeight: '600',
    color: '#fff',
  },
  propGrid: {
    display: 'grid',
    gridTemplateColumns: '80px 1fr',
    gap: '8px',
    alignItems: 'center',
  },
  propLabel: {
    fontSize: '12px',
    color: '#888',
  },
  propInput: {
    padding: '6px 10px',
    backgroundColor: 'rgba(255,255,255,0.05)',
    border: '1px solid #3d3d45',
    borderRadius: '4px',
    color: '#fff',
    fontSize: '13px',
    outline: 'none',
  },
  pixelInfo: {
    marginTop: '12px',
    paddingTop: '12px',
    borderTop: '1px solid #3d3d45',
    fontSize: '11px',
    color: '#666',
  },
};

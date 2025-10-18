"""
Playlist management for Jetson Media Player.
Handles content organization and selection logic.
"""

from typing import List, Dict, Optional, Any
from dataclasses import dataclass
from pathlib import Path
import json


@dataclass
class MediaItem:
    """Represents a single piece of media content."""
    
    id: str
    filename: str
    path: str
    duration: float  # seconds
    triggers: List[str]  # e.g., ["age:adult", "age:senior", "default"]
    metadata: Dict[str, Any]
    
    def matches_trigger(self, trigger: str) -> bool:
        """
        Check if this media item matches a trigger.
        
        Args:
            trigger: Trigger string (e.g., "age:adult")
            
        Returns:
            True if this item should play for this trigger
        """
        return trigger in self.triggers 


class Playlist:
    """Manages a collection of media items with trigger-based selection."""
    
    def __init__(self, name: str, items: Optional[List[MediaItem]] = None):
        """
        Initialize playlist.
        
        Args:
            name: Playlist name
            items: List of media items
        """
        self.name = name
        self.items: List[MediaItem] = items or []
        self.current_index = 0
    
    def add_item(self, item: MediaItem) -> None:
        """Add a media item to the playlist."""
        self.items.append(item)
    
    def get_default_item(self) -> Optional[MediaItem]:
        """
        Get the default media item (for when no triggers match).
        
        Returns:
            MediaItem with "default" trigger, or first item if none found
        """
        for item in self.items:
            if "default" in item.triggers:
                return item
        
        return self.items[0] if self.items else None
    
    def get_item_for_trigger(self, trigger: str) -> Optional[MediaItem]:
        """
        Get media item matching a specific trigger.
        
        Args:
            trigger: Trigger string (e.g., "age:child", "age:adult")
            
        Returns:
            Matching MediaItem or None
        """
        # Find all matching items
        matching = [item for item in self.items if item.matches_trigger(trigger)]
        
        if not matching:
            return self.get_default_item()
        
        # For now, return first match
        # TODO: Add logic for rotation, priority, etc.
        return matching[0]
    
    def get_next_item(self) -> Optional[MediaItem]:
        """
        Get next item in sequence (for default playback loop).
        
        Returns:
            Next MediaItem in playlist
        """
        if not self.items:
            return None
        
        item = self.items[self.current_index]
        self.current_index = (self.current_index + 1) % len(self.items)
        return item
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert playlist to dictionary for serialization."""
        return {
            "name": self.name,
            "items": [
                {
                    "id": item.id,
                    "filename": item.filename,
                    "path": item.path,
                    "duration": item.duration,
                    "triggers": item.triggers,
                    "metadata": item.metadata
                }
                for item in self.items
            ]
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Playlist":
        """Create playlist from dictionary."""
        items = [
            MediaItem(
                id=item_data["id"],
                filename=item_data["filename"],
                path=item_data["path"],
                duration=item_data["duration"],
                triggers=item_data["triggers"],
                metadata=item_data.get("metadata", {})
            )
            for item_data in data.get("items", [])
        ]
        return cls(name=data["name"], items=items)
    
    def save(self, filepath: str) -> None:
        """Save playlist to JSON file."""
        with open(filepath, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)
    
    @classmethod
    def load(cls, filepath: str) -> "Playlist":
        """Load playlist from JSON file."""
        with open(filepath, 'r') as f:
            data = json.load(f)
        return cls.from_dict(data)
    
    def __len__(self) -> int:
        """Get number of items in playlist."""
        return len(self.items)
    
    def __repr__(self) -> str:
        """String representation."""
        return f"Playlist(name='{self.name}', items={len(self.items)})"

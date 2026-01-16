"""
Device ID Generator Service for CMS.

Generates unique device IDs based on registration mode:
- Direct mode: SKZ-D-XXXX (device connects directly to CMS)
- Hub mode: SKZ-H-{CODE}-XXXX (device connects through a hub)

The ID format follows the Skillz Media convention:
- SKZ: Skillz Media prefix
- D/H: Mode indicator (Direct/Hub)
- CODE: Hub code (only for hub mode, 2-4 uppercase letters)
- XXXX: Zero-padded 4-digit sequential number
"""

from typing import Optional


class DeviceIDGenerator:
    """
    Generate unique device IDs based on registration mode.

    This service handles ID generation for two device registration modes:
    1. Direct mode: Devices that connect directly to the CMS
    2. Hub mode: Devices that connect through a local hub

    The generator uses database queries to ensure sequential numbering
    and thread-safe ID generation within database transactions.
    """

    # ID format constants
    PREFIX = "SKZ"
    DIRECT_MODE = "D"
    HUB_MODE = "H"
    SEPARATOR = "-"
    NUMBER_PADDING = 4

    @classmethod
    def generate_direct_id_preview(cls, sequence_number: int) -> str:
        """
        Generate a preview of a direct mode device ID.

        This method generates an ID without database access, useful for
        previewing what an ID would look like at a given sequence number.

        Args:
            sequence_number: The sequence number for the ID (1-based)

        Returns:
            Device ID string in format: SKZ-D-XXXX
        """
        return cls._format_direct_id(sequence_number)

    @classmethod
    def generate_hub_id_preview(cls, hub_code: str, sequence_number: int) -> str:
        """
        Generate a preview of a hub mode device ID.

        This method generates an ID without database access, useful for
        previewing what an ID would look like at a given sequence number.

        Args:
            hub_code: The hub's unique code (e.g., 'WM', 'HON')
            sequence_number: The sequence number for the ID (1-based)

        Returns:
            Device ID string in format: SKZ-H-{CODE}-XXXX
        """
        return cls._format_hub_id(hub_code, sequence_number)

    @classmethod
    def generate_direct_id(cls, db_session) -> str:
        """
        Generate a unique direct mode device ID.

        Queries the database to determine the next sequence number
        for direct mode devices and generates a unique ID.

        Args:
            db_session: SQLAlchemy database session

        Returns:
            Device ID string in format: SKZ-D-XXXX

        Note:
            This method should be called within a database transaction
            to ensure thread-safe ID generation.
        """
        from cms.models.device import Device

        # Count existing direct mode devices
        count = db_session.query(Device).filter(
            Device.mode == 'direct'
        ).count()

        # Generate the next sequential ID
        next_number = count + 1
        return cls._format_direct_id(next_number)

    @classmethod
    def generate_hub_id(cls, hub_code: str, db_session) -> str:
        """
        Generate a unique hub mode device ID.

        Queries the database to determine the next sequence number
        for devices associated with the specified hub.

        Args:
            hub_code: The hub's unique code (e.g., 'WM', 'HON')
            db_session: SQLAlchemy database session

        Returns:
            Device ID string in format: SKZ-H-{CODE}-XXXX

        Note:
            This method should be called within a database transaction
            to ensure thread-safe ID generation.
        """
        from cms.models.device import Device
        from cms.models.hub import Hub

        # Get the hub by code
        hub = db_session.query(Hub).filter(Hub.code == hub_code).first()
        if not hub:
            raise ValueError(f"Hub with code '{hub_code}' not found")

        # Count existing devices for this hub
        count = db_session.query(Device).filter(
            Device.mode == 'hub',
            Device.hub_id == hub.id
        ).count()

        # Generate the next sequential ID
        next_number = count + 1
        return cls._format_hub_id(hub_code, next_number)

    @classmethod
    def generate_hub_id_by_hub_id(cls, hub_id: str, hub_code: str, db_session) -> str:
        """
        Generate a unique hub mode device ID using hub's internal ID.

        This is more efficient when you already have the hub's UUID.

        Args:
            hub_id: The hub's UUID (internal database ID)
            hub_code: The hub's unique code (e.g., 'WM', 'HON')
            db_session: SQLAlchemy database session

        Returns:
            Device ID string in format: SKZ-H-{CODE}-XXXX
        """
        from cms.models.device import Device

        # Count existing devices for this hub
        count = db_session.query(Device).filter(
            Device.mode == 'hub',
            Device.hub_id == hub_id
        ).count()

        # Generate the next sequential ID
        next_number = count + 1
        return cls._format_hub_id(hub_code, next_number)

    @classmethod
    def _format_direct_id(cls, sequence_number: int) -> str:
        """
        Format a direct mode device ID.

        Args:
            sequence_number: The sequence number (1-based)

        Returns:
            Formatted ID string: SKZ-D-XXXX
        """
        padded_number = str(sequence_number).zfill(cls.NUMBER_PADDING)
        return f"{cls.PREFIX}{cls.SEPARATOR}{cls.DIRECT_MODE}{cls.SEPARATOR}{padded_number}"

    @classmethod
    def _format_hub_id(cls, hub_code: str, sequence_number: int) -> str:
        """
        Format a hub mode device ID.

        Args:
            hub_code: The hub's unique code
            sequence_number: The sequence number (1-based)

        Returns:
            Formatted ID string: SKZ-H-{CODE}-XXXX
        """
        # Normalize hub code to uppercase
        normalized_code = hub_code.upper()
        padded_number = str(sequence_number).zfill(cls.NUMBER_PADDING)
        return f"{cls.PREFIX}{cls.SEPARATOR}{cls.HUB_MODE}{cls.SEPARATOR}{normalized_code}{cls.SEPARATOR}{padded_number}"

    @classmethod
    def parse_device_id(cls, device_id: str) -> Optional[dict]:
        """
        Parse a device ID and extract its components.

        Args:
            device_id: The device ID string to parse

        Returns:
            Dictionary with components if valid, None if invalid:
            - For direct mode: {'mode': 'direct', 'sequence': int}
            - For hub mode: {'mode': 'hub', 'hub_code': str, 'sequence': int}
        """
        if not device_id or not device_id.startswith(cls.PREFIX):
            return None

        parts = device_id.split(cls.SEPARATOR)

        if len(parts) < 3:
            return None

        # Check for direct mode: SKZ-D-XXXX
        if len(parts) == 3 and parts[1] == cls.DIRECT_MODE:
            try:
                sequence = int(parts[2])
                return {
                    'mode': 'direct',
                    'sequence': sequence
                }
            except ValueError:
                return None

        # Check for hub mode: SKZ-H-CODE-XXXX
        if len(parts) == 4 and parts[1] == cls.HUB_MODE:
            try:
                sequence = int(parts[3])
                return {
                    'mode': 'hub',
                    'hub_code': parts[2],
                    'sequence': sequence
                }
            except ValueError:
                return None

        return None

    @classmethod
    def validate_hub_code(cls, code: str) -> bool:
        """
        Validate a hub code format.

        Hub codes must be 2-4 uppercase letters.

        Args:
            code: The hub code to validate

        Returns:
            True if valid, False otherwise
        """
        if not code:
            return False
        if len(code) < 2 or len(code) > 4:
            return False
        return code.isalpha() and code.isupper()

"""
Central Hub Services Package

Core business logic services for face encoding, database compilation,
alert processing, and notifications.
"""

from central_hub.services.face_encoder import (
    extract_encoding,
    extract_encoding_from_bytes,
    validate_image_file,
    FaceEncodingError,
    NoFaceDetectedError,
    InvalidImageError,
)

from central_hub.services.database_compiler import (
    compile_ncmec_database,
    compile_loyalty_database,
    get_latest_ncmec_version,
    get_latest_loyalty_version,
    verify_database_integrity,
    DatabaseCompilationError,
    EmptyDatabaseError,
    InvalidEncodingError,
)

from central_hub.services.notifier import (
    send_email,
    send_sms,
    send_notification,
    send_bulk_notifications,
    get_notification_status,
    NotificationError,
    EmailSendError,
    SMSSendError,
    InvalidRecipientError,
    NotificationResult,
    NotificationChannel,
)

from central_hub.services.alert_processor import (
    process_alert,
    get_alert_notification_history,
    retry_failed_notifications,
    get_alert_processing_status,
    AlertProcessingError,
    InvalidAlertError,
    NotificationDispatchError,
    DuplicateAlertError,
    AlertProcessingResult,
    AlertPriority,
)

__all__ = [
    # Face encoder
    'extract_encoding',
    'extract_encoding_from_bytes',
    'validate_image_file',
    'FaceEncodingError',
    'NoFaceDetectedError',
    'InvalidImageError',
    # Database compiler
    'compile_ncmec_database',
    'compile_loyalty_database',
    'get_latest_ncmec_version',
    'get_latest_loyalty_version',
    'verify_database_integrity',
    'DatabaseCompilationError',
    'EmptyDatabaseError',
    'InvalidEncodingError',
    # Notifier
    'send_email',
    'send_sms',
    'send_notification',
    'send_bulk_notifications',
    'get_notification_status',
    'NotificationError',
    'EmailSendError',
    'SMSSendError',
    'InvalidRecipientError',
    'NotificationResult',
    'NotificationChannel',
    # Alert processor
    'process_alert',
    'get_alert_notification_history',
    'retry_failed_notifications',
    'get_alert_processing_status',
    'AlertProcessingError',
    'InvalidAlertError',
    'NotificationDispatchError',
    'DuplicateAlertError',
    'AlertProcessingResult',
    'AlertPriority',
]

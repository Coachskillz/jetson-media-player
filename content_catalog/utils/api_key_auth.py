"""
API Key authentication for service-to-service communication.
"""
import os
from functools import wraps
from flask import request, jsonify

SERVICE_API_KEY = os.environ.get('CONTENT_CATALOG_SERVICE_KEY', 'skillz-cms-service-key-2026')

def api_key_or_jwt_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        api_key = request.headers.get('X-Service-API-Key')
        if api_key and api_key == SERVICE_API_KEY:
            return fn(*args, **kwargs)
        
        from flask_jwt_extended import verify_jwt_in_request
        try:
            verify_jwt_in_request()
            return fn(*args, **kwargs)
        except Exception:
            return jsonify({'error': 'Unauthorized', 'message': 'Valid API key or JWT required'}), 401
    
    return wrapper

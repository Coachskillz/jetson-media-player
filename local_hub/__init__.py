"""
Local Hub Service for Store Locations

This service runs on an Intel NUC at each store location, acting as an intermediary
between the cloud HQ and LAN-connected Jetson screens. It syncs content and databases
from HQ, serves cached content to screens, receives alerts from screens and forwards
them to HQ with reliable retry logic, and monitors screen health.
"""

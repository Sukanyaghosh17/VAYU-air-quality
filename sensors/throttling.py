"""
sensors/throttling.py — Custom DRF rate throttling classes for VAYU
===================================================================
Provides scoped rate throttling specifically tailored for sensor telemetry
ingestion, protecting the API from compromised tokens or runaway simulator processes.
"""

from rest_framework.throttling import ScopedRateThrottle


class IngestScopedRateThrottle(ScopedRateThrottle):
    """
    Custom ScopedRateThrottle for sensor reading ingestion.
    Resolves scope from the view's `throttle_scope` attribute (defaulting to 'readings_ingest').
    """
    scope_attr = "throttle_scope"

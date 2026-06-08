"""
retention/
Data retention policy management and pruning logic.

This package provides:
    * pure retention cutoff computation (``policy.py``);
    * retention policy persistence and detection pruning (``service.py``);
    * ``GET/PUT /api/config/retention`` router (``routers/retention.py``).

Requirements: 16.1, 16.2, 16.3, 16.4
"""

"""v1 report code, ported as-is from the unversioned mustafa-league-reporting/ copy.

This is the bug-fixed version that actually produced the 2025 reports. It is kept only to
stop the two copies diverging; M1 replaces its espn-api usage with mustafatron's own client
and M4 replaces the matplotlib charts with web pages, after which this package is deleted.
Needs the ``legacy`` extra: ``uv sync --extra legacy``. Charts are written to ``output/plots/``.
"""

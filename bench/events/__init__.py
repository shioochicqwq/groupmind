"""Event layer (sidecar). Built from the frozen B blocks; never feeds back into B/RRF retrieval.

Events hold references (block ids, message id ranges), never copies of the text. See
docs/research/2026-11-event-layer-design.md.
"""

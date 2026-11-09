# RGB inspection integration contracts

Run `python -m maek.inspection_bridge --port 8765` for the loopback-only RGB bridge.
It accepts unannotated PNG pixels and returns request IDs, hashes and image-space
HSV rust evidence. It does not predict cracks or establish pipe integrity.

`maek.inspection_routing` plans follow-up work from explicitly located observations
and inventory requirements. The Unity demo and thermal pipeline are separate dependent PRs.

Validation: `python -m pytest tests/test_inspection_bridge.py tests/test_inspection_routing.py -q`.

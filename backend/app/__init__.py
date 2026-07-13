import os

__version__ = "0.6.14"
__channel__ = os.environ.get("BRIDGE_CHANNEL", "release").strip() or "release"
__commit__ = os.environ.get("BRIDGE_COMMIT", "").strip() or None

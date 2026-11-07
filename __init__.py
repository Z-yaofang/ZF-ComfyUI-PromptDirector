from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS
from .sam3_tracking import ZVSAM3TrackVideo

NODE_CLASS_MAPPINGS["ZVSAM3TrackVideo"] = ZVSAM3TrackVideo
NODE_DISPLAY_NAME_MAPPINGS["ZVSAM3TrackVideo"] = "ZV SAM3 彩色编号跟踪视频"

from . import server as _server  # noqa: F401

WEB_DIRECTORY = "./web"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]

"""ComfyUI-specific storage location, kept outside the pure contract."""
import threading
from .storage import MediaStore
from .preset_store import PresetError, PresetLibrary

_store = None
_lock = threading.Lock()


def get_preset_library(request):
    from server import PromptServer
    user_root = PromptServer.instance.user_manager.get_request_user_filepath(request, None, create_dir=False)
    if not user_root:
        raise PresetError("preset_path", "无法定位当前 ComfyUI 用户配置目录；项目快照仍可使用")
    return PresetLibrary(user_root)


def get_store():
    global _store
    with _lock:
        if _store is None:
            import folder_paths
            _store = MediaStore(folder_paths.get_input_directory())
        return _store

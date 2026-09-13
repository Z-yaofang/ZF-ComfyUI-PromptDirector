"""A bounded preset library in the host's current-user directory."""
import copy
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import uuid
from .contract import parse_project, shape_errors
from .presets import BUILTIN_PRESETS, normalize_snapshot, rule_errors

PRESET_SCHEMA = json.loads((Path(__file__).resolve().parents[1] / "schemas" / "zv-processing-preset-v1.schema.json").read_text(encoding="utf-8"))
_write_lock = threading.Lock()


class PresetError(ValueError):
    def __init__(self, code, message):
        self.code, self.message = code, message
        super().__init__(message)


def validate_snapshot(snapshot):
    errors = rule_errors(snapshot)
    if errors:
        raise PresetError("preset_rules", "；".join(errors))


class PresetLibrary:
    def __init__(self, user_root):
        self.root = Path(user_root).resolve()
        self.directory = self.root / "zf_media_evidence"
        self.path = self.directory / "processing_presets.json"

    def safe(self):
        if not self.directory.resolve().is_relative_to(self.root) or not self.path.resolve().is_relative_to(self.directory.resolve()) or self.path.is_symlink():
            raise PresetError("preset_path", "用户预设配置路径无效，已拒绝写入")

    def read(self):
        self.safe()
        if not self.path.exists():
            return []
        if self.path.stat().st_size > 262144:
            raise PresetError("preset_library", "用户预设库超过 256 KiB，原文件保留")
        data = parse_project(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or set(data) != {"schema_version", "presets"} or data["schema_version"] != 1 or not isinstance(data["presets"], list) or len(data["presets"]) > 128:
            raise PresetError("preset_library", "用户预设库结构无效，原文件保留")
        ids = set()
        for preset in data["presets"]:
            if isinstance(preset, dict) and "snapshot" in preset:
                preset["snapshot"] = normalize_snapshot(preset["snapshot"])
            if shape_errors(preset, PRESET_SCHEMA) or not re.fullmatch(r"user\.[a-f0-9]{32}", preset["preset_id"]) or preset["preset_id"] in ids:
                raise PresetError("preset_library", "用户预设库条目无效，原文件保留")
            validate_snapshot(preset["snapshot"])
            ids.add(preset["preset_id"])
        return data["presets"]

    def listing(self):
        return {"builtins": copy.deepcopy(BUILTIN_PRESETS), "users": self.read()}

    def write(self, presets):
        self.safe()
        text = json.dumps({"schema_version": 1, "presets": presets}, ensure_ascii=False, allow_nan=False, indent=2)
        if len(text.encode("utf-8")) > 262144:
            raise PresetError("preset_library", "用户预设库最多 256 KiB")
        self.directory.mkdir(parents=True, exist_ok=True)
        self.safe()
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.directory, prefix=".presets-", suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(text)
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def save(self, snapshot, preset_id=None, version=None):
        snapshot = normalize_snapshot(snapshot)
        validate_snapshot(snapshot)
        if preset_id is not None and not re.fullmatch(r"user\.[a-f0-9]{32}", preset_id):
            raise PresetError("preset_builtin", "内置预设不可覆盖，请复制为用户预设")
        with _write_lock:
            presets = self.read()
            previous = next((p for p in presets if p["preset_id"] == preset_id), None)
            if preset_id is not None and previous is None:
                raise PresetError("preset_missing", "该用户预设已删除，请复制当前快照创建")
            if previous and (type(version) is not int or version != previous["preset_version"]):
                raise PresetError("preset_conflict", "预设已被修改，请重新载入后编辑；项目快照未改写")
            if previous is None and len(presets) >= 128:
                raise PresetError("preset_limit", "最多保存 128 个用户预设")
            preset = {"preset_id": preset_id or "user."+uuid.uuid4().hex, "preset_version": previous["preset_version"]+1 if previous else 1, "snapshot": copy.deepcopy(snapshot)}
            if shape_errors(preset, PRESET_SCHEMA):
                raise PresetError("preset_rules", "预设字段类型或版本无效")
            self.write([p for p in presets if p["preset_id"] != preset_id] + [preset])
            return preset

    def delete(self, preset_id, version):
        if not re.fullmatch(r"user\.[a-f0-9]{32}", preset_id):
            raise PresetError("preset_builtin", "内置预设不可删除")
        with _write_lock:
            presets = self.read()
            previous = next((p for p in presets if p["preset_id"] == preset_id), None)
            if previous is None:
                raise PresetError("preset_missing", "该用户预设已删除，项目快照仍可使用")
            if type(version) is not int or version != previous["preset_version"]:
                raise PresetError("preset_conflict", "预设已被修改，请重新载入后删除")
            self.write([p for p in presets if p["preset_id"] != preset_id])

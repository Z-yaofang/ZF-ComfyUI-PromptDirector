"""Per-user SQLite interview library, with transactional compare-and-swap."""

from contextlib import contextmanager
import json
from pathlib import Path
import re
import sqlite3
import time
import uuid

from .presets import PresetError, MAX_BYTES, strict_json, validate_template, keys

ID_RE = re.compile(r"h3\.[a-f0-9]{32}")


def name_value(value):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 120 or any(ord(char) < 32 for char in value):
        raise PresetError("preset_name", "名称需为1–120字符，不含控制字符")
    return value.strip()


def preset_id(value):
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise PresetError("preset_id", "需要服务器生成的预设 UUID")
    return value


class InterviewLibrary:
    def __init__(self, user_root):
        self.root = Path(user_root).absolute()
        self.directory = self.root / "zf_h3_interview"
        self.path = self.directory / "presets.sqlite3"
        self._trusted_root = None

    def safe(self):
        # The request user directory is the trust boundary and may itself be a
        # platform-managed junction. Pin its resolved destination, then require
        # every database path to remain below it on every transaction.
        try:
            current_root = self.root.resolve(strict=True)
        except OSError:
            raise PresetError("preset_path", "当前用户目录无效") from None
        if not current_root.is_dir():
            raise PresetError("preset_path", "当前用户目录无效")
        if self._trusted_root is None:
            self._trusted_root = current_root
        elif current_root != self._trusted_root:
            raise PresetError("preset_path", "当前用户目录指向已改变，已拒绝访问")
        targets = [self.directory, self.path, *(self.directory / ("presets.sqlite3" + suffix) for suffix in ("-journal", "-wal", "-shm"))]
        for target in targets:
            try:
                link_stat = target.lstat()
            except FileNotFoundError:
                continue
            except OSError:
                raise PresetError("preset_path", "预设路径无法安全解析") from None
            if target.is_symlink() or getattr(link_stat, "st_file_attributes", 0) & 0x400:
                raise PresetError("preset_path", "用户目录下的预设路径包含链接/reparse point，已拒绝访问")
            try:
                resolved = target.resolve(strict=False)
                if not resolved.is_relative_to(self._trusted_root):
                    raise PresetError("preset_path", "预设路径越出当前用户目录，已拒绝访问")
                stat = resolved.stat()
            except FileNotFoundError:
                continue
            except OSError:
                raise PresetError("preset_path", "预设路径无法安全解析") from None
            if resolved.is_file() and stat.st_nlink > 1:
                raise PresetError("preset_path", "预设库文件存在硬链接，已拒绝访问")

    @contextmanager
    def transaction(self, write=False):
        self.safe()
        self.directory.mkdir(exist_ok=True)
        self.safe()
        existed = self.path.exists()
        connection = None
        try:
            connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
            connection.row_factory = sqlite3.Row
            connection.execute("BEGIN IMMEDIATE")  # Also serialize concurrent first initialization.
            if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise PresetError("preset_library", "预设库损坏，原库保留")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if not existed and version == 0:
                connection.execute("CREATE TABLE presets (sequence INTEGER PRIMARY KEY AUTOINCREMENT, preset_id TEXT NOT NULL UNIQUE, version INTEGER NOT NULL, name TEXT NOT NULL, name_key TEXT NOT NULL UNIQUE, template TEXT NOT NULL, created INTEGER NOT NULL, updated INTEGER NOT NULL)")
                connection.execute("PRAGMA user_version=1")
                connection.commit()  # Initialization survives a first missing-ID/business failure.
                connection.execute("BEGIN IMMEDIATE")
            elif version != 1 or [row[1] for row in connection.execute("PRAGMA table_info(presets)")] != ["sequence", "preset_id", "version", "name", "name_key", "template", "created", "updated"]:
                raise PresetError("preset_library", "预设库版本或结构无效，未重建")
            yield connection
            connection.commit()
        except (sqlite3.Error, OSError):
            raise PresetError("preset_library", "预设库事务/访问失败，既存条目未清空；请检查磁盘和库状态", 503) from None
        finally:
            if connection is not None:
                connection.close()  # Any uncommitted transaction rolls back.

    def decode(self, row, full=True):
        if row is None:
            raise PresetError("preset_missing", "预设已删除或不属于当前用户", 404)
        if not isinstance(row["preset_id"], str) or not ID_RE.fullmatch(row["preset_id"]) or type(row["version"]) is not int or row["version"] < 1 or not isinstance(row["name"], str) or not 1 <= len(row["name"].strip()) <= 120 or row["name"].strip() != row["name"] or any(ord(char) < 32 for char in row["name"]) or row["name_key"] != row["name"].casefold() or any(type(row[key]) is not int or row[key] < 0 for key in ("created", "updated")):
            raise PresetError("preset_library", "库条目元数据损坏，原库保留")
        value = {"preset_id": row["preset_id"], "preset_version": row["version"], "name": row["name"], "created": row["created"], "updated": row["updated"]}
        if full:
            try:
                value["template"] = validate_template(strict_json(row["template"]))
            except PresetError:
                raise PresetError("preset_library", "库模板损坏，原条目保留") from None
        return value

    def listing(self, cursor=0, limit=50):
        if type(cursor) is not int or cursor < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise PresetError("preset_page", "分页 cursor/limit 无效")
        with self.transaction() as db:
            rows = db.execute("SELECT * FROM presets WHERE (?=0 OR sequence<?) ORDER BY sequence DESC LIMIT ?", (cursor, cursor, limit + 1)).fetchall()
            return {"presets": [self.decode(row, full=False) for row in rows[:limit]], "next_cursor": rows[limit - 1]["sequence"] if len(rows) > limit else None}

    def get(self, identifier):
        with self.transaction() as db:
            return self.decode(db.execute("SELECT * FROM presets WHERE preset_id=?", (preset_id(identifier),)).fetchone())

    def unique_name(self, db, name):
        candidate, index = name_value(name), 1
        while db.execute("SELECT 1 FROM presets WHERE name_key=?", (candidate.casefold(),)).fetchone():
            index += 1
            suffix = f"（副本 {index}）"
            candidate = name[:120 - len(suffix)] + suffix
        return candidate

    def insert(self, db, name, template):
        identifier, name, clock = "h3." + uuid.uuid4().hex, self.unique_name(db, name), time.time_ns()
        db.execute("INSERT INTO presets(preset_id,version,name,name_key,template,created,updated) VALUES(?,?,?,?,?,?,?)", (identifier, 1, name, name.casefold(), json.dumps(template, ensure_ascii=False, allow_nan=False), clock, clock))
        return self.decode(db.execute("SELECT * FROM presets WHERE preset_id=?", (identifier,)).fetchone())

    def create(self, name, template):
        name, template = name_value(name), validate_template(template)
        with self.transaction(write=True) as db:
            return self.insert(db, name, template)

    def previous(self, db, identifier, version):
        row = db.execute("SELECT * FROM presets WHERE preset_id=?", (preset_id(identifier),)).fetchone()
        value = self.decode(row)
        if type(version) is not int or version != value["preset_version"]:
            raise PresetError("preset_conflict", "预设已被修改，请重新载入后操作；当前表格保留", 409)
        return row

    def update(self, identifier, version, name, template=None):
        name = name_value(name)
        if template is not None: template = validate_template(template)
        with self.transaction(write=True) as db:
            previous = self.previous(db, identifier, version)
            duplicate = db.execute("SELECT 1 FROM presets WHERE name_key=? AND preset_id<>?", (name.casefold(), identifier)).fetchone()
            if duplicate:
                raise PresetError("preset_name_conflict", "该名称已存在，请换名", 409)
            db.execute("UPDATE presets SET version=version+1,name=?,name_key=?,template=?,updated=? WHERE preset_id=? AND version=?", (name, name.casefold(), json.dumps(template, ensure_ascii=False, allow_nan=False) if template is not None else previous["template"], time.time_ns(), identifier, version))
            return self.decode(db.execute("SELECT * FROM presets WHERE preset_id=?", (identifier,)).fetchone())

    def delete(self, identifier, version):
        with self.transaction(write=True) as db:
            self.previous(db, identifier, version)
            db.execute("DELETE FROM presets WHERE preset_id=? AND version=?", (identifier, version))

    def export(self, identifiers):
        if not isinstance(identifiers, list) or not 1 <= len(identifiers) <= 256 or any(not isinstance(identifier, str) for identifier in identifiers) or len(set(identifiers)) != len(identifiers):
            raise PresetError("preset_ids", "导出需选择1–256项不同预设")
        with self.transaction() as db:
            values, size = [], 128
            for identifier in identifiers:
                row = db.execute("SELECT * FROM presets WHERE preset_id=?", (preset_id(identifier),)).fetchone()
                if row is None: self.decode(row)
                size += len(row["template"].encode("utf-8")) + len(row["name"].encode("utf-8")) + 128
                if size > MAX_BYTES: raise PresetError("preset_size", "导出集合超过2 MiB，请少选几项")
                value = self.decode(row); values.append({"name": value["name"], "template": value["template"]})
            return {"schema_version": "zv-h3-interview-library-v1", "presets": values}

    def import_collection(self, value):
        keys(value, {"schema_version", "presets"})
        if value["schema_version"] != "zv-h3-interview-library-v1" or not isinstance(value["presets"], list) or not 1 <= len(value["presets"]) <= 256:
            raise PresetError("preset_import", "导入集合版本或条目数无效")
        entries = []
        for entry in value["presets"]:
            keys(entry, {"name", "template"})
            entries.append((name_value(entry["name"]), validate_template(entry["template"])))
        with self.transaction(write=True) as db:
            return [self.insert(db, name, template) for name, template in entries]


def get_interview_library(request):
    from server import PromptServer
    root = PromptServer.instance.user_manager.get_request_user_filepath(request, None, create_dir=False)
    if not root:
        raise PresetError("preset_path", "无法定位当前 ComfyUI 用户目录")
    return InterviewLibrary(root)

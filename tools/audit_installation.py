"""Read-only check for duplicate PromptDirector installations and retired nodes."""

import argparse
import ast
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RETIRED_NODES = frozenset({
    "ZVH3InterviewForm", "ZVH3FocusCompiler",
    "ZVPictureSlotOutlet", "ZVVideoSlotOutlet", "ZVAudioSlotOutlet",
    "ZFBlueprintParser", "ZFSinglePromptTask",
})


def registered_nodes(directory):
    """Inspect literal mappings without executing plugin code or importing models."""
    for name in ("nodes.py", "__init__.py"):
        path = directory / name
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8-sig")
        if "ZFPromptDirector" not in text or "NODE_CLASS_MAPPINGS" not in text:
            continue
        try:
            tree = ast.parse(text)
        except (UnicodeError, SyntaxError):
            continue
        for statement in tree.body:
            if not isinstance(statement, ast.Assign) or not isinstance(statement.value, ast.Dict):
                continue
            if not any(isinstance(target, ast.Name) and target.id == "NODE_CLASS_MAPPINGS" for target in statement.targets):
                continue
            keys = {key.value for key in statement.value.keys if isinstance(key, ast.Constant) and isinstance(key.value, str)}
            if "ZFPromptDirector" in keys:
                return keys
    return set()


def audit(custom_nodes):
    if not custom_nodes.is_dir():
        raise ValueError(f"插件目录不存在：{custom_nodes}")
    installations = []
    for directory in sorted(custom_nodes.iterdir()):
        if not directory.is_dir() or directory.name.endswith(".disabled") or directory.name == "__pycache__":
            continue
        names = registered_nodes(directory)
        if names:
            installations.append({"path": str(directory), "node_count": len(names), "retired_nodes": sorted(names & RETIRED_NODES)})
    errors = []
    if not installations:
        errors.append("未找到可核对的 PromptDirector 节点注册表。")
    if len(installations) > 1:
        errors.append(f"发现 {len(installations)} 份 PromptDirector 会被扫描；备份和 Git worktree 必须移到 custom_nodes 之外，点号前缀不会禁用插件。")
    for entry in installations:
        if entry["retired_nodes"]:
            errors.append(f"{Path(entry['path']).name} 仍注册废弃节点：" + "、".join(entry["retired_nodes"]))
    return {"ready": not errors, "custom_nodes": str(custom_nodes), "installations": installations, "errors": errors}


def main():
    parser = argparse.ArgumentParser(description="只读检查 PromptDirector 重复安装与废弃节点；不导入节点、不联网、不修改文件。")
    parser.add_argument("--custom-nodes", type=Path, default=ROOT.parent)
    parser.add_argument("--json", action="store_true", help="输出 JSON 检查报告")
    args = parser.parse_args()
    try:
        report = audit(args.custom_nodes.resolve())
    except (OSError, ValueError) as error:
        parser.exit(2, str(error) + "\n")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for entry in report["installations"]:
            print(f"{entry['path']}：{entry['node_count']} 个节点")
        for error in report["errors"]:
            print(error)
        if report["ready"]:
            print("通过：仅一份安装，未注册废弃节点。若刚清理过旧副本，请保存工作流、重启 ComfyUI 并刷新前端。")
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

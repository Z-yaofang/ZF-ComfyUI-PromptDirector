# Compatibility and releases

- Maintain Windows local and Linux/RunningHub compatibility together. Cloud compatibility is part of correctness for every plugin change, not a later optional task.
- Preserve node IDs, socket contracts, saved workflows and media unless the requested change explicitly requires migration.
- Keep runtime code compatible with Python 3.10+. Do not add machine-specific paths or make optional audio/model packages mandatory at plugin import. Prefer ComfyUI's existing APIs; document host capabilities and any execution-only fallback dependencies in `docs/CLOUD_TESTING.md`.
- RunningHub republishes frontend modules. Keep relative imports free of query strings and fragments, resolve sibling assets from `import.meta.url`, and use the existing Comfy API bridge for requests and media URLs. Do not require `/scripts/api.js` or a fixed plugin install-directory URL.
- Before publishing runtime changes, verify node registration, affected CPU regressions, Linux path handling, and browser loading with hashed modules, remapped assets and prefixed APIs. Cover new and restored nodes. Check native VIDEO and codec requirements when media execution changes.
- Distinguish local simulations from actual RunningHub acceptance. A Git push does not update the platform's published frontend or prove a cloud generation run succeeded; record untested boundaries plainly.
- Stage only the requested release files. Preserve unrelated local changes and do not publish personal workflows, media, credentials or local audit artifacts. Follow the user's explicit scope for test-file publication.

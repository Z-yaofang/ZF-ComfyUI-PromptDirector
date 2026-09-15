import assert from "node:assert/strict";
import test from "node:test";
import { readdir, readFile } from "node:fs/promises";

const webRoot = new URL("../web/", import.meta.url);

test("cloud frontend modules do not import the legacy /scripts/api.js path", async () => {
  const entries = await readdir(webRoot, { withFileTypes: true });
  const modules = entries.filter(entry => entry.isFile() && /\.(?:m?js)$/.test(entry.name));

  for (const module of modules) {
    const source = await readFile(new URL(module.name, webRoot), "utf8");
    assert.doesNotMatch(
      source,
      /\/scripts\/api\.js/,
      `${module.name} must use the injected or global Comfy API bridge`,
    );
  }
});

test("frontend entry modules provide a cloud-safe Comfy API bridge", async () => {
  for (const name of ["h3_interview.js", "media_evidence_desk.js"]) {
    const source = await readFile(new URL(name, webRoot), "utf8");
    assert.match(source, /globalThis\.comfyAPI\?\.api\?\.api/);
    assert.match(source, /apiURL:\s*path\s*=>\s*path/);
    assert.match(source, /fetchApi:\s*\(path, options\)\s*=>\s*fetch\(path, options\)/);
  }
});

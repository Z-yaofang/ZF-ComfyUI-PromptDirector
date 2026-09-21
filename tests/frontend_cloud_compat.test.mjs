import assert from "node:assert/strict";
import test from "node:test";
import { readdir, readFile } from "node:fs/promises";

const webRoot = new URL("../web/", import.meta.url);

function relativeModuleSpecifiers(source) {
  const modules = /\b(?:import|export)\s+(?:[^;"'`]*?\bfrom\s*)?(["'])(\.{1,2}\/[^"']+)\1|\bimport\s*\(\s*(["'])(\.{1,2}\/[^"']+)\3/g;
  return [...source.matchAll(modules)].map(match => match[2] || match[4]);
}

test("relative module scan covers imports, re-exports and literal dynamic imports", () => {
  assert.deepEqual(relativeModuleSpecifiers(`
    import * as outlets from "./media_evidence_outlets.mjs?v=h3-v2-07";
    import "./side-effect.js#build";
    import { one,
      two } from "../shared.mjs?version=2";
    export { one } from "./public.mjs#v2";
    export * from "./all.mjs?version=2";
    const later = import("./lazy.mjs?v=2");
    import { app } from "/scripts/app.js";
    fetch("./preview?frame=1");
  `), [
    "./media_evidence_outlets.mjs?v=h3-v2-07", "./side-effect.js#build",
    "../shared.mjs?version=2", "./public.mjs#v2", "./all.mjs?version=2", "./lazy.mjs?v=2",
  ]);
});

test("relative frontend module imports stay compatible with cloud asset hashing", async () => {
  const entries = await readdir(webRoot, { withFileTypes: true });
  const invalid = [];
  for (const entry of entries.filter(entry => entry.isFile() && /\.(?:m?js)$/.test(entry.name))) {
    const source = await readFile(new URL(entry.name, webRoot), "utf8");
    for (const specifier of relativeModuleSpecifiers(source)) {
      if (/[?#]/.test(specifier)) invalid.push(`${entry.name}: ${specifier}`);
    }
  }
  assert.deepEqual(invalid, [], "RunningHub's hashed asset rewrite misses relative module specifiers with query/hash suffixes");
});

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

import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { promisify } from "node:util";
import { fileURLToPath } from "node:url";

import test from "node:test";
import sharp from "sharp";

const execFileAsync = promisify(execFile);
const extensionDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const faviconPath = resolve(extensionDir, "..", "frontend", "public", "favicon.png");

test("usa el favicon como icono de la extensión en Chrome y Firefox", async () => {
  await execFileAsync(process.execPath, ["build.mjs"], { cwd: extensionDir });

  for (const browser of ["chrome", "firefox"]) {
    const targetDir = join(extensionDir, "dist", browser);
    const manifest = JSON.parse(readFileSync(join(targetDir, "manifest.json"), "utf8"));

    assert.deepEqual(manifest.action.default_icon, manifest.icons);
    assert.ok(
      Object.values(manifest.icons).every((path) => path.includes("/brand-")),
    );
    assert.equal(existsSync(join(targetDir, "assets", "icons", "active-128.png")), false);
    assert.equal(existsSync(join(targetDir, "assets", "icons", "idle-128.png")), false);

    const expected = await sharp(faviconPath).resize(128, 128).png().toBuffer();
    const generated = readFileSync(join(targetDir, "assets", "icons", "brand-128.png"));
    assert.deepEqual(generated, expected);
  }
});

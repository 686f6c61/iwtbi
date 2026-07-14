import { cpSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import sharp from "sharp";

const __dirname = dirname(fileURLToPath(import.meta.url));
const rootDir = resolve(__dirname);
const distDir = join(rootDir, "dist");
const commonDir = join(rootDir, "src", "common");
const iconsDir = join(rootDir, "src", "assets", "icons");
const brandIconSource = resolve(rootDir, "..", "frontend", "public", "favicon.png");
const fontsDir = resolve(rootDir, "..", "frontend", "public", "fonts");
const packageJson = JSON.parse(readFileSync(join(rootDir, "package.json"), "utf8"));
const appBaseUrl = (process.env.IWTBI_APP_URL || "http://localhost:3410").replace(/\/+$/, "");
const firefoxExtensionId =
  process.env.IWTBI_FIREFOX_EXTENSION_ID || "iwtbi-self-host@example.invalid";

const iconSizes = [16, 32, 48, 128];

const defaultManifest = {
  manifest_version: 3,
  version: packageJson.version,
  name: "IWTBI for GitHub",
  description:
    "Convierte repositorios de GitHub en documentos listos para reconstruirlos con IA.",
  host_permissions: ["https://github.com/*"],
  permissions: ["storage"],
  background: {
    service_worker: "background.js",
  },
  action: {
    default_title: "IWTBI",
    default_popup: "popup.html",
  },
  content_scripts: [
    {
      matches: ["https://github.com/*"],
      js: ["config.js", "repo.js", "content.js"],
      css: ["content.css"],
      run_at: "document_idle",
    },
  ],
};

function iconMap(prefix) {
  return Object.fromEntries(iconSizes.map((size) => [size, `assets/icons/${prefix}-${size}.png`]));
}

function ensureDir(path) {
  mkdirSync(path, { recursive: true });
}

async function generateIcons(targetDir) {
  const iconTargetDir = join(targetDir, "assets", "icons");
  ensureDir(iconTargetDir);

  for (const state of ["active", "idle"]) {
    const sourceSvg = join(iconsDir, `icon-${state}.svg`);
    cpSync(sourceSvg, join(iconTargetDir, `${state}.svg`));

    for (const size of iconSizes) {
      await sharp(sourceSvg)
        .resize(size, size)
        .png()
        .toFile(join(iconTargetDir, `${state}-${size}.png`));
    }
  }

  for (const size of iconSizes) {
    await sharp(brandIconSource)
      .resize(size, size)
      .png()
      .toFile(join(iconTargetDir, `brand-${size}.png`));
  }
}

async function generateBrandAssets(targetDir) {
  const brandTargetDir = join(targetDir, "assets", "brand");
  ensureDir(brandTargetDir);

  cpSync(brandIconSource, join(brandTargetDir, "favicon.png"));

  for (const size of [48, 64, 96, 128]) {
    await sharp(brandIconSource)
      .resize(size, size)
      .png()
      .toFile(join(brandTargetDir, `icon-${size}.png`));
  }
}

function writeManifest(targetDir, browser) {
  const manifest = structuredClone(defaultManifest);
  manifest.icons = iconMap("brand");
  manifest.action.default_icon = iconMap("idle");
  manifest.web_accessible_resources = [
    {
      resources: ["assets/brand/*"],
      matches: ["https://github.com/*"],
    },
  ];

  if (browser === "firefox") {
    delete manifest.background.service_worker;
    manifest.background.scripts = ["repo.js", "background.js"];
    manifest.browser_specific_settings = {
      gecko: {
        id: firefoxExtensionId,
        strict_min_version: "140.0",
        data_collection_permissions: {
          required: ["none"],
        },
      },
      gecko_android: {
        strict_min_version: "142.0",
      },
    };
  }

  writeFileSync(join(targetDir, "manifest.json"), `${JSON.stringify(manifest, null, 2)}\n`);
}

function copyCommonFiles(targetDir) {
  cpSync(commonDir, targetDir, { recursive: true });

  const targetFontsDir = join(targetDir, "assets", "fonts");
  ensureDir(targetFontsDir);

  if (existsSync(fontsDir)) {
    cpSync(fontsDir, targetFontsDir, { recursive: true });
  }
}

function writeRuntimeConfig(targetDir) {
  const config = `globalThis.IWTBI_CONFIG = Object.freeze(${JSON.stringify({ appBaseUrl })});\n`;
  writeFileSync(join(targetDir, "config.js"), config);
}

async function build(browser) {
  const targetDir = join(distDir, browser);
  rmSync(targetDir, { recursive: true, force: true });
  ensureDir(targetDir);
  copyCommonFiles(targetDir);
  writeRuntimeConfig(targetDir);
  await generateIcons(targetDir);
  await generateBrandAssets(targetDir);
  writeManifest(targetDir, browser);
  console.log(`Built ${browser} extension in ${targetDir}`);
}

rmSync(distDir, { recursive: true, force: true });
ensureDir(distDir);

await build("chrome");
await build("firefox");

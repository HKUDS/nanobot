// Generates Apple PWA launch assets from public/brand/nanobot_mark.svg:
//   - apple-touch-startup-image splash screens (light #ffffff background,
//     centered mark) for the device table below
//   - nanobot_icon_1024.png for the manifest "any" icon set
//
// Why this exists: iOS Safari has no fallback for apple-touch-startup-image —
// a media query must match exactly or the system shows a plain background
// color. Keeping the table and the generated <link> tags in one script makes
// the set reproducible and auditable.
//
// Usage: node scripts/generate-apple-assets.mjs
// Prints the <link rel="apple-touch-startup-image" .../> block to paste into
// index.html (values use ?v1 cache busting, bump the query on regen).

import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import sharp from "sharp";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const SOURCE_SVG = resolve(ROOT, "public/brand/nanobot_mark.svg");
const SPLASH_DIR = resolve(ROOT, "public/brand/splash");
const ICON_OUT = resolve(ROOT, "public/brand/nanobot_icon_1024.png");

const SPLASH_BACKGROUND = "#ffffff";
const CACHE_BUST = "v1";

// CSS-point dimensions per device generation (width x height x devicePixelRatio).
// Portrait entry; landscape swaps width/height in the media query.
const DEVICES = [
  { label: "iPhone SE (2nd/3rd gen)", width: 375, height: 667, dpr: 2 },
  { label: "iPhone 12 mini / 13 mini / XS / X / 11 Pro", width: 375, height: 812, dpr: 3 },
  { label: "iPhone 12 / 13 / 14", width: 390, height: 844, dpr: 3 },
  { label: "iPhone 15 / 16", width: 393, height: 852, dpr: 3 },
  { label: "iPhone 16 Pro", width: 402, height: 874, dpr: 3 },
  { label: "iPhone XS Max / 11 Pro Max", width: 414, height: 896, dpr: 3 },
  { label: "iPhone 14 Pro Max / 15 Plus / 16 Plus", width: 430, height: 932, dpr: 3 },
  { label: "iPhone 16 Pro Max", width: 440, height: 956, dpr: 3 },
  { label: "iPad mini (5th gen)", width: 768, height: 1024, dpr: 2 },
  { label: "iPad mini (6th gen)", width: 744, height: 1133, dpr: 2 },
  { label: "iPad 10.9-inch", width: 820, height: 1180, dpr: 2 },
  { label: "iPad Pro 10.5 / iPad Air 3", width: 834, height: 1112, dpr: 2 },
  { label: "iPad Pro 11-inch / iPad Air 4-6", width: 834, height: 1194, dpr: 2 },
  { label: "iPad Pro 12.9-inch", width: 1024, height: 1366, dpr: 2 },
];

// Mark occupies ~30% of the shorter visual axis so it stays prominent on
// small phones but never crowds the fold on tablets.
function logoHeightPt(orientation, ptWidth, ptHeight) {
  const byHeight = orientation === "portrait" ? ptHeight * 0.3 : ptHeight * 0.45;
  const byWidth = ptWidth * 0.5;
  return Math.max(96, Math.min(byHeight, byWidth));
}

async function renderMarkPng(targetHeightPx) {
  const svg = await readFile(SOURCE_SVG);
  return sharp(svg).resize({ height: Math.round(targetHeightPx) }).png().toBuffer();
}

async function renderSplash(device, orientation) {
  const ptWidth = orientation === "portrait" ? device.width : device.height;
  const ptHeight = orientation === "portrait" ? device.height : device.width;
  const pxWidth = Math.round(ptWidth * device.dpr);
  const pxHeight = Math.round(ptHeight * device.dpr);
  const markHeightPx = Math.round(logoHeightPt(orientation, ptWidth, ptHeight) * device.dpr);

  const mark = await renderMarkPng(markHeightPx);
  const canvas = sharp({
    create: {
      width: pxWidth,
      height: pxHeight,
      channels: 3,
      background: SPLASH_BACKGROUND,
    },
  });
  const png = await canvas.composite([{ input: mark, gravity: "centre" }]).png().toBuffer();

  const base = `nanobot-${ptWidth}x${ptHeight}@${device.dpr}x-${orientation}.png`;
  await writeFile(resolve(SPLASH_DIR, base), png);
  return { ptWidth, ptHeight, dpr: device.dpr, orientation, base };
}

async function renderIcon1024() {
  // App-store style: opaque background, mark fitted to ~78% of the canvas.
  const mark = await renderMarkPng(820);
  const canvas = sharp({
    create: { width: 1024, height: 1024, channels: 3, background: SPLASH_BACKGROUND },
  });
  const png = await canvas.composite([{ input: mark, gravity: "centre" }]).png().toBuffer();
  await writeFile(ICON_OUT, png);
}

function mediaQuery({ ptWidth, ptHeight, dpr, orientation }) {
  return (
    `screen and (device-width: ${ptWidth}px) and (device-height: ${ptHeight}px)` +
    ` and (-webkit-device-pixel-ratio: ${dpr}) and (orientation: ${orientation})`
  );
}

async function main() {
  await mkdir(SPLASH_DIR, { recursive: true });
  const rendered = [];
  for (const device of DEVICES) {
    for (const orientation of ["portrait", "landscape"]) {
      rendered.push(await renderSplash(device, orientation));
    }
  }
  await renderIcon1024();

  const lines = rendered.map(
    (r) =>
      `    <link rel="apple-touch-startup-image" media="${mediaQuery(r)}" ` +
      `href="/brand/splash/${r.base}?${CACHE_BUST}" />`,
  );

  console.log(`Wrote ${rendered.length} splash screens to public/brand/splash/`);
  console.log(`Wrote ${ICON_OUT}`);
  console.log("\n--- link block for index.html ---\n");
  console.log(lines.join("\n"));
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});

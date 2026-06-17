#!/usr/bin/env node

const fs = require("node:fs/promises");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const { chromium } = require("playwright");

const EXPORT_CSS = (width, height) => `
html,
body {
  width: ${width}px !important;
  height: ${height}px !important;
  min-height: ${height}px !important;
  margin: 0 !important;
  overflow: hidden !important;
}

.deck {
  width: ${width}px !important;
  height: ${height}px !important;
  min-height: ${height}px !important;
  padding: 0 !important;
}

.slide {
  width: ${width}px !important;
  height: ${height}px !important;
  aspect-ratio: auto !important;
  box-shadow: none !important;
  transition: none !important;
  transform: none !important;
}

.slide.is-active {
  transform: none !important;
}

.controls,
.progress {
  display: none !important;
}

video,
.video-fullscreen {
  display: none !important;
}

.video-poster-fallback {
  position: absolute !important;
  inset: 0 !important;
  display: block !important;
  width: 100% !important;
  height: 100% !important;
  object-fit: cover !important;
}
`;

async function waitForSlideMedia(page) {
  await page.evaluate(async () => {
    const activeSlide = document.querySelector(".slide.is-active");
    if (!activeSlide) return;

    const images = Array.from(activeSlide.querySelectorAll("img"));
    await Promise.all(
      images.map((img) => {
        if (img.complete && img.naturalWidth > 0) return Promise.resolve();
        return new Promise((resolve) => {
          img.addEventListener("load", resolve, { once: true });
          img.addEventListener("error", resolve, { once: true });
        });
      }),
    );

    const videos = Array.from(activeSlide.querySelectorAll("video"));
    await Promise.all(
      videos.map(async (video) => {
        video.muted = true;
        video.removeAttribute("controls");
        video.pause();
        if (video.readyState < 1) {
          await new Promise((resolve) => {
            video.addEventListener("loadedmetadata", resolve, { once: true });
            video.addEventListener("error", resolve, { once: true });
          });
        }
        const duration = Number.isFinite(video.duration) ? video.duration : 0;
        const targetTime = duration > 3 ? 2 : duration > 0.5 ? 0.35 : 0;
        if (Math.abs(video.currentTime - targetTime) > 0.05) {
          await new Promise((resolve) => {
            video.addEventListener("seeked", resolve, { once: true });
            video.addEventListener("error", resolve, { once: true });
            video.currentTime = targetTime;
          });
        }
        video.pause();
      }),
    );
  });
}

function readArg(name, fallback) {
  const index = process.argv.indexOf(name);
  if (index === -1) return fallback;
  return process.argv[index + 1] ?? fallback;
}

async function main() {
  const deckPath = path.resolve(readArg("--deck", "outputs/html-presentation/index.html"));
  const slideDir = path.resolve(readArg("--slide-dir", "outputs/browser-slide-captures"));
  const width = Number(readArg("--width", "1600"));
  const height = Number(readArg("--height", "900"));

  await fs.mkdir(slideDir, { recursive: true });
  const url = pathToFileURL(deckPath).href;

  const launchOptions = {};
  if (process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE) {
    launchOptions.executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE;
  }
  const browser = await chromium.launch(launchOptions);
  const page = await browser.newPage({
    viewport: { width, height },
    deviceScaleFactor: 1,
  });

  await page.goto(url, { waitUntil: "networkidle" });
  await page.addStyleTag({ content: EXPORT_CSS(width, height) });
  const slideCount = await page.locator(".slide").count();

  for (let index = 0; index < slideCount; index += 1) {
    await page.goto(`${url}#${index + 1}`, { waitUntil: "networkidle" });
    await page.addStyleTag({ content: EXPORT_CSS(width, height) });
    await waitForSlideMedia(page);
    await page.waitForTimeout(150);
    await page.locator(".slide.is-active").screenshot({
      path: path.join(slideDir, `slide-${String(index + 1).padStart(2, "0")}.png`),
      animations: "disabled",
    });
  }

  await browser.close();
  console.log(`Captured ${slideCount} slides to ${slideDir}`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});

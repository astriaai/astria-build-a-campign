#!/usr/bin/env python3
"""Capture the HTML deck slide-by-slide in Chromium and assemble a PDF."""

from __future__ import annotations

import argparse
import asyncio
import re
from pathlib import Path

from PIL import Image
from playwright.async_api import async_playwright


EXPORT_CSS = """
html,
body {
  width: 1600px !important;
  height: 900px !important;
  min-height: 900px !important;
  margin: 0 !important;
  overflow: hidden !important;
}

.deck {
  width: 1600px !important;
  height: 900px !important;
  min-height: 900px !important;
  padding: 0 !important;
}

.slide {
  width: 1600px !important;
  height: 900px !important;
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
"""


async def wait_for_slide_media(page) -> None:
    await page.evaluate(
        """
        async () => {
          const activeSlide = document.querySelector(".slide.is-active");
          if (!activeSlide) return;

          const images = Array.from(activeSlide.querySelectorAll("img"));
          await Promise.all(images.map((img) => {
            if (img.complete && img.naturalWidth > 0) return Promise.resolve();
            return new Promise((resolve) => {
              img.addEventListener("load", resolve, { once: true });
              img.addEventListener("error", resolve, { once: true });
            });
          }));

          const videos = Array.from(activeSlide.querySelectorAll("video"));
          await Promise.all(videos.map(async (video) => {
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
          }));
        }
        """
    )


async def capture_slides(deck_html: Path, slide_dir: Path, width: int, height: int) -> list[Path]:
    slide_dir.mkdir(parents=True, exist_ok=True)

    url = deck_html.resolve().as_uri()
    screenshots: list[Path] = []

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
        await page.goto(url, wait_until="networkidle")
        await page.add_style_tag(content=EXPORT_CSS.replace("1600", str(width)).replace("900", str(height)))

        slide_count = await page.locator(".slide").count()
        for index in range(slide_count):
            await page.goto(f"{url}#{index + 1}", wait_until="networkidle")
            await page.add_style_tag(content=EXPORT_CSS.replace("1600", str(width)).replace("900", str(height)))
            await wait_for_slide_media(page)
            await page.wait_for_timeout(150)

            slide = page.locator(".slide.is-active")
            filename = slide_dir / f"slide-{index + 1:02d}.png"
            await slide.screenshot(path=str(filename), animations="disabled")
            screenshots.append(filename)

        await browser.close()

    return screenshots


def natural_sort_key(path: Path) -> list[int | str]:
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", path.name)]


def build_pdf(slides: list[Path], pdf_path: Path) -> None:
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    images = [Image.open(slide).convert("RGB") for slide in sorted(slides, key=natural_sort_key)]
    if not images:
        raise RuntimeError("No slide images were captured")

    first, rest = images[0], images[1:]
    first.save(pdf_path, "PDF", save_all=True, append_images=rest, resolution=72.0)

    for image in images:
        image.close()


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deck", type=Path, default=Path("outputs/html-presentation/index.html"))
    parser.add_argument("--slide-dir", type=Path, default=Path("outputs/browser-slide-captures"))
    parser.add_argument("--pdf", type=Path, default=Path("outputs/pdf/astria-campaigns-lookbook-browser-capture.pdf"))
    parser.add_argument("--width", type=int, default=1600)
    parser.add_argument("--height", type=int, default=900)
    args = parser.parse_args()

    slides = await capture_slides(args.deck, args.slide_dir, args.width, args.height)
    build_pdf(slides, args.pdf)

    print(f"Captured {len(slides)} slides to {args.slide_dir}")
    print(f"Wrote {args.pdf}")


if __name__ == "__main__":
    asyncio.run(main())

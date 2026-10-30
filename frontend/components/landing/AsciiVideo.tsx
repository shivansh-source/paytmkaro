"use client";

import { useEffect, useRef } from "react";

const RAMP = " .,:;-~=+*xX#%@";
const FPS = 24;

/** Renders a video as live gold ASCII characters on a canvas. */
export function AsciiVideo({ name }: { name: string }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const video = videoRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !video || !ctx) return;

    const sample = document.createElement("canvas");
    const sctx = sample.getContext("2d", { willReadFrequently: true });
    if (!sctx) return;

    let cols = 0;
    let rows = 0;
    let cell = 12;
    let width = 0;
    let height = 0;
    let frame = 0;
    let last = 0;

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      width = canvas.clientWidth;
      height = canvas.clientHeight;
      canvas.width = width * dpr;
      canvas.height = height * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      cell = width < 700 ? 9 : 12;
      cols = Math.ceil(width / (cell * 0.6));
      rows = Math.ceil(height / cell);
      sample.width = cols;
      sample.height = rows;
    };

    // Draw `source` cover-fitted into the character grid.
    const render = (source: CanvasImageSource, sw: number, sh: number) => {
      if (!sw || !sh || !cols) return;
      const target = width / height;
      let cw = sw;
      let ch = sh;
      if (sw / sh > target) cw = sh * target;
      else ch = sw / target;
      sctx.drawImage(source, (sw - cw) / 2, (sh - ch) / 2, cw, ch, 0, 0, cols, rows);
      const { data } = sctx.getImageData(0, 0, cols, rows);

      ctx.clearRect(0, 0, width, height);
      ctx.font = `${cell}px ui-monospace, SFMono-Regular, Consolas, monospace`;
      ctx.textBaseline = "top";
      const top = RAMP.length - 1;
      for (let y = 0; y < rows; y++) {
        let dim = "";
        let bright = "";
        for (let x = 0; x < cols; x++) {
          const i = (y * cols + x) * 4;
          const lum = (0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2]) / 255;
          const ch2 = RAMP[Math.min(top, Math.floor(Math.pow(lum, 0.6) * top * 1.4))];
          if (lum > 0.3) {
            bright += ch2;
            dim += " ";
          } else {
            dim += ch2;
            bright += " ";
          }
        }
        ctx.fillStyle = "rgba(242, 181, 68, 0.6)";
        ctx.fillText(dim, 0, y * cell);
        ctx.fillStyle = "#f6c35d";
        ctx.fillText(bright, 0, y * cell);
      }
    };

    const loop = (t: number) => {
      frame = requestAnimationFrame(loop);
      if (t - last < 1000 / FPS || video.readyState < 2) return;
      last = t;
      render(video, video.videoWidth, video.videoHeight);
    };

    resize();
    window.addEventListener("resize", resize);

    // Static frame from the poster until (or instead of) the video plays.
    const poster = new Image();
    poster.onload = () => render(poster, poster.naturalWidth, poster.naturalHeight);
    poster.src = `/media/${name}.jpg`;

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (reduced) return;
        if (entry.isIntersecting) {
          if (!video.getAttribute("src")) video.src = `/media/${name}.mp4`;
          video.play().catch(() => {});
          cancelAnimationFrame(frame);
          frame = requestAnimationFrame(loop);
        } else {
          video.pause();
          cancelAnimationFrame(frame);
        }
      },
      { rootMargin: "200px" }
    );
    observer.observe(canvas);

    return () => {
      observer.disconnect();
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", resize);
    };
  }, [name]);

  return (
    <>
      <canvas ref={canvasRef} className="ascii-canvas" data-ascii aria-hidden="true" />
      <video ref={videoRef} className="ascii-source" muted loop playsInline preload="none" aria-hidden="true" />
    </>
  );
}

"use client";

import { useEffect, useRef } from "react";

/** Muted looping background video that only loads and plays while on screen. */
export function BgVideo({ name }: { name: string }) {
  const ref = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    const video = ref.current;
    if (!video) return;
    const saveData = (navigator as Navigator & { connection?: { saveData?: boolean } }).connection?.saveData;
    if (saveData || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          if (!video.getAttribute("src")) video.src = `/media/${name}.mp4`;
          video.play().catch(() => {});
        } else {
          video.pause();
        }
      },
      { rootMargin: "300px" }
    );
    observer.observe(video);
    return () => observer.disconnect();
  }, [name]);

  return (
    <video
      ref={ref}
      className="bg-video"
      poster={`/media/${name}.jpg`}
      muted
      loop
      playsInline
      preload="none"
      aria-hidden="true"
    />
  );
}

"use client";

import { useEffect } from "react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import Lenis from "lenis";

const GLYPHS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789#%₹";

/** Resolve an element's text out of random glyphs, left to right. */
function scramble(el: HTMLElement, duration = 0.9) {
  const final = el.dataset.text ?? el.textContent ?? "";
  el.dataset.text = final;
  const state = { p: 0 };
  gsap.to(state, {
    p: 1,
    duration,
    ease: "none",
    onUpdate: () => {
      const shown = Math.floor(state.p * final.length);
      el.textContent = [...final]
        .map((ch, i) => (i < shown || ch === " " ? ch : GLYPHS[Math.floor(Math.random() * GLYPHS.length)]))
        .join("");
    },
    onComplete: () => {
      el.textContent = final;
    }
  });
}

const all = <T extends Element = HTMLElement>(selector: string, scope: ParentNode = document) =>
  Array.from(scope.querySelectorAll<T>(selector) as NodeListOf<T>);

/** Every scroll effect on the landing page. Elements opt in with data-* attributes. */
export function LandingMotion() {
  useEffect(() => {
    gsap.registerPlugin(ScrollTrigger);
    const reveal = () => gsap.set("[data-hero-title]", { visibility: "visible" });

    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      reveal();
      gsap.set(".fill-word", { opacity: 1 });
      gsap.set("[data-reel]", { y: "-24em" });
      return;
    }

    const lenis = new Lenis({ lerp: 0.09, anchors: true });
    lenis.on("scroll", ScrollTrigger.update);
    const tick = (time: number) => lenis.raf(time * 1000);
    gsap.ticker.add(tick);
    gsap.ticker.lagSmoothing(0);

    const cleanups: Array<() => void> = [];

    const ctx = gsap.context(() => {
      // ---- Chrome: progress bar + hide-on-scroll nav ----
      gsap.to("[data-progress]", { scaleX: 1, ease: "none", scrollTrigger: { start: 0, end: "max", scrub: 0.3 } });
      const nav = document.querySelector<HTMLElement>("[data-nav]");
      ScrollTrigger.create({
        start: 0,
        end: "max",
        onUpdate: (self) => nav?.classList.toggle("nav-hidden", self.direction === 1 && self.scroll() > 240)
      });

      // ---- Hero: intro, then parallax out ----
      reveal();
      gsap
        .timeline({ delay: 0.1 })
        .from("[data-hero-media]", { scale: 1.3, opacity: 0, duration: 2.4, ease: "power3.out" })
        .from("[data-hero] .char", { yPercent: 120, rotate: 12, duration: 1.2, ease: "power4.out", stagger: 0.028 }, 0.25)
        .from("[data-hero-fade]", { y: 30, opacity: 0, duration: 1, ease: "power3.out", stagger: 0.12 }, 1);

      gsap
        .timeline({ scrollTrigger: { trigger: "[data-hero]", start: "top top", end: "bottom top", scrub: true } })
        .to("[data-hero-title]", { yPercent: -40, opacity: 0.1, ease: "none" }, 0)
        .to("[data-hero-zoom]", { scale: 1.2, ease: "none" }, 0);

      // ---- Problem: pinned, statements swap one at a time over live ASCII ----
      const problem = document.querySelector<HTMLElement>("[data-problem]");
      if (problem) {
        const spans = all("[data-swap] > .mask > span", problem);
        const counter = problem.querySelector<HTMLElement>("[data-swap-count]");
        gsap.set(spans.slice(1), { yPercent: 110 });
        const tl = gsap.timeline({
          scrollTrigger: {
            trigger: problem,
            start: "top top",
            end: `+=${spans.length * 90}%`,
            pin: true,
            scrub: 0.8,
            onUpdate: (self) => {
              if (counter) {
                const n = Math.min(spans.length, Math.floor(self.progress * spans.length) + 1);
                counter.textContent = `0${n} / 0${spans.length}`;
              }
            }
          }
        });
        tl.fromTo("[data-ascii]", { scale: 1 }, { scale: 1.45, ease: "none", duration: spans.length }, 0);
        spans.forEach((span, i) => {
          if (i === 0) return;
          tl.to(spans[i - 1], { yPercent: -110, duration: 0.5, ease: "power3.in" }, i - 0.5).to(
            span,
            { yPercent: 0, duration: 0.5, ease: "power3.out" },
            i - 0.15
          );
        });
      }

      // ---- "Not yet": words light up one by one as you scroll ----
      gsap.to("[data-fill] .fill-word", {
        opacity: 1,
        stagger: 0.1,
        ease: "none",
        scrollTrigger: { trigger: "[data-fill]", start: "top 75%", end: "bottom 50%", scrub: true }
      });

      gsap.from("[data-panel-row]", {
        y: 40,
        opacity: 0,
        duration: 0.9,
        ease: "power3.out",
        stagger: 0.14,
        scrollTrigger: { trigger: "[data-panel]", start: "top 80%" }
      });

      // ---- Process: plays once on entry. Digit reels spin to the score, gauge draws, checks appear ----
      const process = document.querySelector<HTMLElement>("[data-process]");
      if (process) {
        const ring = process.querySelector<SVGCircleElement>("[data-score-ring]");
        const length = ring ? ring.getTotalLength() : 0;
        const value = Number(ring?.dataset.value ?? 0) / 100;
        const reels = all("[data-reel]", process);
        if (ring) gsap.set(ring, { strokeDasharray: length, strokeDashoffset: length });
        gsap.set(reels, { y: 0 });
        gsap.set("[data-check]", { opacity: 0, y: 24 });

        gsap
          .timeline({ scrollTrigger: { trigger: process, start: "top 55%", once: true } })
          .to(ring, { strokeDashoffset: length * (1 - value), duration: 2.2, ease: "power3.inOut" }, 0)
          .to(
            reels,
            // Land on the extra digit after two full 0-9 cycles.
            { y: "-24em", duration: 2, ease: "power4.inOut", stagger: 0.2 },
            0
          )
          .to("[data-check]", { opacity: 1, y: 0, duration: 0.7, ease: "power3.out", stagger: 0.15 }, 1.6);
      }

      gsap.from("[data-step]", {
        y: 60,
        opacity: 0,
        duration: 1,
        ease: "power3.out",
        stagger: 0.1,
        scrollTrigger: { trigger: "[data-steps]", start: "top 85%" }
      });

      // ---- Compare: hairlines draw, then text rises ----
      all("[data-compare-row]").forEach((row) => {
        gsap
          .timeline({ scrollTrigger: { trigger: row, start: "top 90%" } })
          .from(row.querySelector(".rule"), { scaleX: 0, transformOrigin: "left center", duration: 1.1, ease: "power3.inOut" })
          .from(all(".them, .us", row), { y: 26, opacity: 0, stagger: 0.1, duration: 0.7, ease: "power3.out" }, 0.3);
      });

      // ---- Languages: pinned, each language blurs into the next ----
      const langs = document.querySelector<HTMLElement>("[data-langs]");
      if (langs) {
        const items = all("[data-lang]", langs);
        gsap.set(items.slice(1), { opacity: 0, yPercent: 45, filter: "blur(16px)" });
        const tl = gsap.timeline({
          scrollTrigger: { trigger: langs, start: "top top", end: `+=${items.length * 70}%`, pin: true, scrub: 0.8 }
        });
        items.forEach((item, i) => {
          if (i === 0) return;
          tl.to(items[i - 1], { opacity: 0, yPercent: -45, filter: "blur(16px)", duration: 0.5 }, i - 0.5).to(
            item,
            { opacity: 1, yPercent: 0, filter: "blur(0px)", duration: 0.5 },
            i - 0.25
          );
        });
        tl.to({}, { duration: 0.4 });
      }

      // ---- Video band: gentle parallax inside its frame ----
      gsap.fromTo(
        "[data-band-inner]",
        { yPercent: -12 },
        { yPercent: 12, ease: "none", scrollTrigger: { trigger: "[data-band]", start: "top bottom", end: "bottom top", scrub: true } }
      );

      // ---- CTA: tunnel rushes in, title grows ----
      gsap
        .timeline({ scrollTrigger: { trigger: "[data-cta]", start: "top bottom", end: "center center", scrub: true } })
        .fromTo("[data-cta] video", { scale: 1.6 }, { scale: 1, ease: "none" }, 0)
        .from("[data-cta-title]", { scale: 0.6, opacity: 0, ease: "none" }, 0);

      // ---- Generic: masked line reveals, fades, scrambles ----
      all("[data-lines]").forEach((block) => {
        gsap.from(all(".mask > span", block), {
          yPercent: 110,
          duration: 1.1,
          ease: "power4.out",
          stagger: 0.1,
          scrollTrigger: { trigger: block, start: "top 85%" }
        });
      });
      all("[data-reveal]").forEach((el) => {
        gsap.from(el, { y: 50, opacity: 0, duration: 1, ease: "power3.out", scrollTrigger: { trigger: el, start: "top 88%" } });
      });
      all("[data-scramble]").forEach((el) => {
        ScrollTrigger.create({ trigger: el, start: "top 92%", once: true, onEnter: () => scramble(el) });
      });
    });

    // ---- Pointer: custom cursor + magnetic buttons (mouse only) ----
    if (window.matchMedia("(pointer: fine)").matches) {
      const cursor = document.querySelector<HTMLElement>("[data-cursor]");
      if (cursor) {
        const xTo = gsap.quickTo(cursor, "x", { duration: 0.35, ease: "power3" });
        const yTo = gsap.quickTo(cursor, "y", { duration: 0.35, ease: "power3" });
        const move = (e: MouseEvent) => {
          xTo(e.clientX);
          yTo(e.clientY);
        };
        window.addEventListener("mousemove", move);
        cleanups.push(() => window.removeEventListener("mousemove", move));
        all("a, button").forEach((el) => {
          const on = () => cursor.classList.add("cursor-grow");
          const off = () => cursor.classList.remove("cursor-grow");
          el.addEventListener("mouseenter", on);
          el.addEventListener("mouseleave", off);
          cleanups.push(() => {
            el.removeEventListener("mouseenter", on);
            el.removeEventListener("mouseleave", off);
          });
        });
      }

      all("[data-magnetic]").forEach((btn) => {
        const bx = gsap.quickTo(btn, "x", { duration: 0.5, ease: "power3" });
        const by = gsap.quickTo(btn, "y", { duration: 0.5, ease: "power3" });
        const onMove = (e: MouseEvent) => {
          const r = btn.getBoundingClientRect();
          bx((e.clientX - r.left - r.width / 2) * 0.3);
          by((e.clientY - r.top - r.height / 2) * 0.45);
        };
        const onLeave = () => {
          bx(0);
          by(0);
        };
        btn.addEventListener("mousemove", onMove);
        btn.addEventListener("mouseleave", onLeave);
        cleanups.push(() => {
          btn.removeEventListener("mousemove", onMove);
          btn.removeEventListener("mouseleave", onLeave);
        });
      });
    }

    // Fonts change line heights; re-measure pins once they land.
    document.fonts?.ready.then(() => ScrollTrigger.refresh());

    return () => {
      cleanups.forEach((fn) => fn());
      ctx.revert();
      gsap.ticker.remove(tick);
      lenis.destroy();
    };
  }, []);

  return null;
}

"use client";

import { useEffect, useState } from "react";

/** The landing page's odometer + gauge ring: digits roll to the score, the ring draws to score%. Plays once. */
export function ScoreDial({ score }: { score: number }) {
  const [run, setRun] = useState(false);
  useEffect(() => {
    const id = requestAnimationFrame(() => setRun(true));
    return () => cancelAnimationFrame(id);
  }, []);

  const digits = String(score).split("");
  const circumference = 2 * Math.PI * 46;

  return (
    <div className="dial" aria-label={`Readiness score ${score} out of 100`}>
      <svg viewBox="0 0 100 100" className="dial-ring" aria-hidden="true">
        <circle cx="50" cy="50" r="46" className="dial-track" />
        <circle
          cx="50"
          cy="50"
          r="46"
          className="dial-fill"
          style={{ strokeDasharray: circumference, strokeDashoffset: run ? circumference * (1 - score / 100) : circumference }}
        />
      </svg>
      <div className="dial-digits" aria-hidden="true">
        {digits.map((d, i) => (
          <span key={i} className="dial-digit">
            <span className="dial-reel" style={{ transform: `translateY(${run ? -(20 + Number(d)) * 1.15 : 0}em)`, transitionDelay: `${i * 0.15}s` }}>
              {Array.from({ length: 30 }, (_, n) => (
                <span key={n}>{n % 10}</span>
              ))}
            </span>
          </span>
        ))}
      </div>
    </div>
  );
}

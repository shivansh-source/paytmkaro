export function BridgeMark({ size = 30 }: { size?: number }) {
  return (
    <svg width={size} height={(size * 18) / 30} viewBox="0 0 30 18" fill="none" aria-hidden="true">
      <path d="M1.5 16.5 Q15 -5 28.5 16.5" stroke="#f2b544" strokeWidth="2.2" />
      <path d="M1.5 16.5 H28.5" stroke="#f4efe6" strokeWidth="1.4" />
      <path d="M8.5 16.5 V8.2 M15 16.5 V5.3 M21.5 16.5 V8.2" stroke="#f2b544" strokeWidth="1.1" opacity="0.7" />
    </svg>
  );
}

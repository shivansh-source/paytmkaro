/** @type {import("next").NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Reading a phone photo can take a minute on the VLM free tier; the proxy's default is 30 s.
  experimental: { proxyTimeout: 180_000 },
  // The dashboard calls /api/v1/*; Next forwards it to FastAPI, so no CORS setup is needed.
  async rewrites() {
    const backend = process.env.BACKEND_URL ?? "http://localhost:8000";
    return [{ source: "/api/v1/:path*", destination: `${backend}/v1/:path*` }];
  }
};

export default nextConfig;

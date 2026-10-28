import type { NextConfig } from "next";

const config: NextConfig = {
  // In local development the FastAPI backend runs on port 8000. On Vercel, the services
  // routing in vercel.json sends /api/* to it instead, so no rewrite is needed there.
  async rewrites() {
    return process.env.NODE_ENV === "development"
      ? [{ source: "/api/:path*", destination: "http://127.0.0.1:8000/api/:path*" }]
      : [];
  },
};

export default config;

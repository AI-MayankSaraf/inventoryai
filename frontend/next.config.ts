import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // `next build` also writes a self-contained server (.next/standalone) that
  // the Docker image runs without node_modules. No effect on `next dev`.
  output: "standalone",
};

export default nextConfig;

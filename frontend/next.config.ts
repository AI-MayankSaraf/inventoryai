import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // `next build` also writes a self-contained server (.next/standalone) that
  // the Docker image runs without node_modules. No effect on `next dev`.
  output: "standalone",
  // tests/test_stack.py runs a second dev server for the automated suites;
  // it needs its own build folder or the two servers lock each other out.
  distDir: process.env.NEXT_DIST_DIR || ".next",
};

export default nextConfig;

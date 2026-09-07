import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  // Category metadata depends on the same data snapshot as the page body.
  // Make every crawler wait for blocking metadata so a partial streamed HTML
  // response cannot turn a temporary API outage into an indexable 200.
  htmlLimitedBots: /.*/,
  experimental: {
    optimizePackageImports: ["lucide-react"],
  },
};

export default nextConfig;

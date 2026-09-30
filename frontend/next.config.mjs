/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // the repo lives inside a larger folder; pin the build root to this app
  turbopack: { root: import.meta.dirname },
  env: {
    NEXT_PUBLIC_API_BASE: process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000",
  },
};

export default nextConfig;

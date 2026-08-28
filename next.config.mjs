/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Next.js 16 auto-generates /AGENTS.md and a root /CLAUDE.md on every
  // `next dev`/`next build` (see Task 1.1's Out of Scope Observation in
  // sessions/S01_SESSION_LOG.md) — collides with this project's PBVI
  // root-stub convention (Claude.md.ROOT_STUB.txt -> docs/Claude.md).
  // Disabled at the source instead of just gitignoring the generated files.
  agentRules: false,
};

export default nextConfig;

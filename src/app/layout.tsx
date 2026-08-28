import type { Metadata } from 'next';
import { Barlow_Semi_Condensed, IBM_Plex_Mono, Inter } from 'next/font/google';
import IconSprite from '@/components/IconSprite';
import './globals.css';

// Design reference: engineer-supplied Figma HTML mockups (2026-08-27) — see
// sessions/S02_SESSION_LOG.md Decision Log. Self-hosted via next/font (no
// external Google Fonts request at runtime, CSP-friendly), same three
// typefaces the mockups use.
const barlowSemiCondensed = Barlow_Semi_Condensed({
  subsets: ['latin'],
  weight: ['500', '600', '700'],
  variable: '--font-display',
  display: 'swap',
});
const inter = Inter({
  subsets: ['latin'],
  weight: ['400', '500', '600', '700'],
  variable: '--font-body',
  display: 'swap',
});
const ibmPlexMono = IBM_Plex_Mono({
  subsets: ['latin'],
  weight: ['400', '500'],
  variable: '--font-mono',
  display: 'swap',
});

export const metadata: Metadata = {
  title: 'VIVE Statement Reconciliation',
  description: 'Automated AP reconciliation for VIVE Collision',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${barlowSemiCondensed.variable} ${inter.variable} ${ibmPlexMono.variable}`}>
      <body>
        <IconSprite />
        {children}
      </body>
    </html>
  );
}

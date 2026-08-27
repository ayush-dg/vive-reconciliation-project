import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'VIVE Statement Reconciliation',
  description: 'Automated AP reconciliation for VIVE Collision',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

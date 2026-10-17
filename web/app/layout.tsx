import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "VaidyaVaani — Clinic Console",
  description: "Two-way voice interpreter for government hospital consultations.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  // A tablet propped on a desk: a pinch-zoom that shifts the PTT buttons mid-turn
  // is worse than no zoom at all.
  maximumScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

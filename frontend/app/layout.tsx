import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = {
  title: "NetSim — 5-Layer Network Simulator",
  description: "Protocol-accurate 5-Layer  TCP/Ip Network Simulator",
};
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

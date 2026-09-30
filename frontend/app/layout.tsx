import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "surveil - product interaction monitoring",
  description:
    "Laptop-camera product detection, tracking and interaction ledger for a shop.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen">
        <div className="mx-auto flex min-h-screen max-w-[1800px] flex-col">
          {children}
        </div>
      </body>
    </html>
  );
}

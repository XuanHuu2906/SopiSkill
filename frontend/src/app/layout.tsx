import type { Metadata } from "next";
import Providers from "./providers";
import AppFrame from "@/components/layout/AppFrame";
import "./fonts.css";
import "./globals.css";

export const metadata: Metadata = {
  title: "SopiSkill",
  description: "Biến chủ đề thành khóa học có cấu trúc",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="vi">
      <body>
        <Providers>
          <AppFrame>{children}</AppFrame>
        </Providers>
      </body>
    </html>
  );
}

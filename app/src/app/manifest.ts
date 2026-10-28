import type { MetadataRoute } from "next";

// "Add to Home Screen" opens FINN full-screen with its own icon, like an installed app.
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "FINN",
    short_name: "FINN",
    description: "What changed in your portfolio today, and whether management did what it said.",
    start_url: "/",
    display: "standalone",
    orientation: "portrait",
    background_color: "#0b0d0f",
    theme_color: "#0b0d0f",
    icons: [
      { src: "/icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png" },
      { src: "/icon-maskable.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}

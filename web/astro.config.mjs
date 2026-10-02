// @ts-check
import { defineConfig } from "astro/config";

// A fully static site: every page is prerendered at build time from the JSON in public/data/
// (written by `uv run mustafatron publish`). There is no server and no runtime data fetching.
export default defineConfig({
  output: "static",
  trailingSlash: "ignore",
  build: { format: "directory" },
});

// The site's top-level sections, in nav order. Each page passes its section's `href` to the layout
// so the nav can mark it current.

export interface NavItem {
  href: string;
  label: string;
}

export const NAV: NavItem[] = [
  { href: "/", label: "Home" },
  { href: "/h2h", label: "Head-to-head" },
  { href: "/standings", label: "Standings" },
  { href: "/seasons", label: "Seasons" },
];

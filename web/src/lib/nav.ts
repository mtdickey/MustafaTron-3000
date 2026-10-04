// The site's top-level sections, in nav order. Each page passes its section's `href` to the layout
// so the nav can mark it current.

export interface NavItem {
  href: string;
  label: string;
}

export const NAV: NavItem[] = [
  { href: "/", label: "Home" },
  { href: "/week", label: "Weekly" },
  { href: "/h2h", label: "Head-to-head" },
  { href: "/rivalries", label: "Rivalries" },
  { href: "/standings", label: "Standings" },
  { href: "/records", label: "Records" },
  { href: "/luck", label: "Luck" },
  { href: "/coaching", label: "Coaching" },
  { href: "/draft", label: "Draft" },
  { href: "/trades", label: "Trades" },
  { href: "/awards", label: "Awards" },
  { href: "/seasons", label: "Seasons" },
  { href: "/managers", label: "Managers" },
];

// Build-time access to the published JSON (web/public/data/, written by `uv run mustafatron publish`).
//
// Pages import from here, never fetch(): the data only changes when the ETL reruns, so every page is
// rendered complete at build time with no loading states. Files are read once per build and cached.
//
// Everything here is presentation glue. Analytics belong in the Python stats layer and arrive
// through the contract (src/types/contract.ts), so the site never re-derives a number the ETL owns.

import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import type {
  GamesFile,
  H2HFile,
  ManagerOut,
  ManagersFile,
  Meta,
  ProfilesFile,
  RecordsFile,
  SeasonFile,
  StandingsFile,
} from "../types/contract";

// Astro always runs from web/, and publicDir is the default public/.
const DATA_DIR = resolve(process.cwd(), "public", "data");
const cache = new Map<string, unknown>();

function load<T>(relpath: string): T {
  if (!cache.has(relpath)) {
    const path = resolve(DATA_DIR, relpath);
    if (!existsSync(path)) {
      throw new Error(
        `${path} is missing. Generate the site data first: \`uv run mustafatron publish --offline\` ` +
          "(finished seasons only) or `uv run mustafatron publish` (with ESPN cookies).",
      );
    }
    cache.set(relpath, JSON.parse(readFileSync(path, "utf8")));
  }
  return cache.get(relpath) as T;
}

export const meta = (): Meta => load("meta.json");
export const managersFile = (): ManagersFile => load("managers.json");
export const gamesFile = (): GamesFile => load("games.json");
export const h2h = (): H2HFile => load("h2h.json");
export const standings = (): StandingsFile => load("standings.json");
export const records = (): RecordsFile => load("records.json");
export const season = (year: number): SeasonFile => load(`seasons/${year}.json`);
export const profiles = (): ProfilesFile => load("profiles.json");

export const managerHref = (id: string) => `/managers/${id}`;

// Managers ----------------------------------------------------------------------------------------

export type Manager = ManagerOut;

export function managers(): Manager[] {
  return managersFile().managers;
}

let byId: Map<string, Manager> | undefined;
export function manager(id: string): Manager {
  byId ??= new Map(managers().map((m) => [m.id, m]));
  const m = byId.get(id);
  if (!m) throw new Error(`unknown manager id ${id}`);
  return m;
}

/** Managers with a team in the latest published season, in name order. */
export function currentManagers(): Manager[] {
  const latest = meta().current_season;
  return managers().filter((m) => m.seasons.includes(latest));
}

// Games -------------------------------------------------------------------------------------------

export interface Game {
  season: number;
  week: number;
  tier: string;
  home: string;
  away: string;
  homeScore: number;
  awayScore: number;
  winner: string | null;
}

export const REGULAR_SEASON = "NONE";
export const WINNERS_BRACKET = "WINNERS_BRACKET";

type Row = GamesFile["games"][number];

export function decodeGame(row: Row, tiers: string[] = gamesFile().tiers): Game {
  const [season, week, tier, home, away, homeScore, awayScore, winner] = row;
  return { season, week, tier: tiers[tier] ?? "NONE", home, away, homeScore, awayScore, winner };
}

let allGames: Game[] | undefined;
/** Every final game, all seasons, oldest first. */
export function games(): Game[] {
  allGames ??= gamesFile().games.map((r) => decodeGame(r));
  return allGames;
}

export const isPlayoff = (g: Game) => g.tier !== REGULAR_SEASON;
export const scoreOf = (g: Game, id: string) => (g.home === id ? g.homeScore : g.awayScore);
export const opponentOf = (g: Game, id: string) => (g.home === id ? g.away : g.home);
export const resultFor = (g: Game, id: string): "W" | "L" | "T" =>
  g.winner === null ? "T" : g.winner === id ? "W" : "L";

// Head-to-head --------------------------------------------------------------------------------------

export type Pair = H2HFile["pairs"][number];

/** URL of the rivalry page for two managers, in either order. */
export function rivalryHref(x: string, y: string): string {
  const [a, b] = [x, y].sort();
  return `/rivalries/${a}-${b}`;
}

export interface Series {
  me: string;
  them: string;
  pair: Pair | undefined;
  wins: number;
  losses: number;
  ties: number;
  /** Regular season only: the pair's record minus its playoff games (playoff ties are broken by ESPN). */
  regWins: number;
  regLosses: number;
}

let pairIndex: Map<string, Pair> | undefined;
/** The all-time series from ``me``'s side, whichever way round h2h.json stores it. */
export function series(me: string, them: string): Series {
  pairIndex ??= new Map(h2h().pairs.map((p) => [`${p.a}|${p.b}`, p]));
  const [a, b] = [me, them].sort();
  const pair = pairIndex.get(`${a}|${b}`);
  if (!pair) return { me, them, pair, wins: 0, losses: 0, ties: 0, regWins: 0, regLosses: 0 };
  const flip = pair.a !== me;
  const wins = flip ? pair.losses : pair.wins;
  const losses = flip ? pair.wins : pair.losses;
  const poWins = flip ? pair.playoff_losses : pair.playoff_wins;
  const poLosses = flip ? pair.playoff_wins : pair.playoff_losses;
  return { me, them, pair, wins, losses, ties: pair.ties, regWins: wins - poWins, regLosses: losses - poLosses };
}

let pairList: Pair[] | undefined;
export function pairs(): Pair[] {
  pairList ??= h2h().pairs;
  return pairList;
}

/** Every final meeting between two managers, oldest first. */
export function meetings(x: string, y: string): Game[] {
  return games().filter((g) => (g.home === x && g.away === y) || (g.home === y && g.away === x));
}

/** Where a game lives on its season page: its week's column, or the bracket for a playoff matchup. */
export function gameHref(g: Pick<Game, "season" | "week" | "tier">): string {
  return `/seasons/${g.season}#${g.tier === REGULAR_SEASON ? `week-${g.week}` : "playoffs"}`;
}

export const TIER_LABELS: Record<string, string> = {
  NONE: "Regular season",
  WINNERS_BRACKET: "Playoffs",
  WINNERS_CONSOLATION_LADDER: "3rd place game",
  LOSERS_CONSOLATION_LADDER: "Consolation",
};

// Pure: what the user chip shows.

/** The letter an avatar shows: a name's first, upper-cased; "?" for none. */
export function initialOf(name: string): string {
  return name.trim().charAt(0).toUpperCase() || "?";
}

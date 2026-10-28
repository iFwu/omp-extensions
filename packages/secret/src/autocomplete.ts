import type { AutocompleteItem, AutocompleteProvider } from "@oh-my-pi/pi-tui";
import type { Vault } from "./vault.ts";

/** Completes explicit references from public names; delegates all ordinary editor input. */
const PREFIX = "{{sec:";

/** The partially-typed ref immediately before the cursor, or null. */
export function refPrefixBefore(textBeforeCursor: string): { prefix: string; typed: string } | null {
  const m = /\{\{sec:([a-z0-9_-]*)$/.exec(textBeforeCursor);
  if (!m) return null;
  return { prefix: PREFIX + m[1]!, typed: m[1]! };
}

/**
 * `base` is pi's CURRENT provider — the built-in command/file provider, or another
 * extension's wrapper. `ctx.ui.addAutocompleteProvider` is a WRAPPER hook: pi calls
 * `factory(current)` and installs the result, so a provider that ignores `current` does not
 * "add" completion, it REPLACES the chain. That was the bug this parameter fixes: every
 * completion the base provider used to answer (`/` commands, `@` files, Tab file
 * completion) came back null, which the user experiences as the Tab key being broken.
 *
 * So this provider answers only the slice of the editor it owns and delegates everything
 * else, unchanged, to the provider underneath.
 */
export function createSecAutocompleteProvider(
  getVault: () => Vault,
  base?: AutocompleteProvider,
): AutocompleteProvider {
  const provider: AutocompleteProvider = {
    // OMP has no provider-defined trigger characters. Tab reaches this provider;
    // all unrelated completion and text-assist hooks remain delegated below.
    async getSuggestions(lines, cursorLine, cursorCol, signal, onPartial) {
      const line = lines[cursorLine] ?? "";
      const match = refPrefixBefore(line.slice(0, cursorCol));
      if (!match) return base ? base.getSuggestions(lines, cursorLine, cursorCol, signal, onPartial) : null;
      let entries;
      try {
        entries = getVault().entries();
      } catch {
        // No session bound yet (the dispatcher and tools can run before session_start).
        // An autocomplete popup that throws would take the editor's key handling with it.
        return null;
      }
      const items: AutocompleteItem[] = entries
        .filter((e) => e.name.startsWith(match.typed))
        .map((e) => ({
          value: e.name,
          label: e.name,
          description: "Session secret reference",
        }));
      return items.length ? { items, prefix: match.prefix } : null;
    },

    applyCompletion(lines, cursorLine, cursorCol, item, prefix) {
      // The prefix identifies whose suggestion is being applied. Ours is always the ref
      // prefix (the editor echoes back what `getSuggestions` returned), so anything else
      // belongs to the base provider and must be applied by it, not rewritten here.
      if (!prefix.startsWith(PREFIX)) {
        return base
          ? base.applyCompletion(lines, cursorLine, cursorCol, item, prefix)
          : { lines, cursorLine, cursorCol };
      }
      const line = lines[cursorLine] ?? "";
      // Only the typed token is replaced; anything the user already typed after the
      // cursor (a closing `}}`, a trailing argument) stays where it is, so completing
      // inside `{{sec:gh}} tail` does not eat the rest of the command.
      const before = line.slice(0, Math.max(0, cursorCol - prefix.length));
      // Completing inside `{{sec:gh}}` must consume the `}}` the user already typed,
      // or the line ends up as `{{sec:gh_pat}}}}`.
      const after = line.slice(cursorCol).replace(/^\}\}/, "");
      const next = [...lines];
      const rewritten = `${before}${PREFIX}${item.value}}}${after}`;
      next[cursorLine] = rewritten;
      return { lines: next, cursorLine, cursorCol: before.length + PREFIX.length + item.value.length + 2 };
    },

    // OMP routes force-Tab through a separate entry point. Refs must be handled
    // here as well, while ordinary paths retain the base provider's behavior.
    ...(base?.getForceFileSuggestions
      ? {
          async getForceFileSuggestions(lines: string[], cursorLine: number, cursorCol: number, signal?: AbortSignal) {
            if (refPrefixBefore((lines[cursorLine] ?? "").slice(0, cursorCol))) {
              return provider.getSuggestions(lines, cursorLine, cursorCol, signal);
            }
            return base.getForceFileSuggestions!(lines, cursorLine, cursorCol, signal);
          },
        }
      : {}),
    ...(base?.shouldTriggerFileCompletion
      ? { shouldTriggerFileCompletion: base.shouldTriggerFileCompletion.bind(base) }
      : {}),
    ...(base?.getInlineHint ? { getInlineHint: base.getInlineHint.bind(base) } : {}),
    ...(base?.trySyncSlashCompletion ? { trySyncSlashCompletion: base.trySyncSlashCompletion.bind(base) } : {}),
    ...(base?.trySyncInlineReplace ? { trySyncInlineReplace: base.trySyncInlineReplace.bind(base) } : {}),
  };
  return provider;
}
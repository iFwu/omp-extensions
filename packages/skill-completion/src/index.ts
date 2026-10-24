import type { ExtensionAPI, ExtensionContext } from "@oh-my-pi/pi-coding-agent";
import type { AutocompleteProvider } from "@oh-my-pi/pi-tui";
import { CustomEditor } from "@oh-my-pi/pi-tui/prompt/custom-editor";

function skillToken(lines: string[], line: number, col: number): string | undefined {
  if (/^[!/%]/.test(lines.join("\n").trimStart())) return;
  const before = lines[line].slice(0, col);
  const token = /(?:^|\s)([$¥￥](?:[a-z][a-z0-9-]*(?:\/[a-z0-9-]*)?)?)$/.exec(before)?.[1];
  if (!token || (token.length > 1 && Object.hasOwn(process.env, token.slice(1)))) return;
  const preceding = [...lines.slice(0, line), before].join("\n");
  if ((preceding.match(/`/g)?.length ?? 0) % 2 !== 0) return;
  return token;
}

export default function (pi: ExtensionAPI) {
  let failed = false;
  let installed = false;
  let context: ExtensionContext | undefined;
  const cleanups: (() => void)[] = [];
  function cleanup() {
    for (const undo of cleanups.splice(0).reverse()) {
      try { undo(); }
      catch (error) { console.error("[skill-completion] cleanup failed", error); }
    }
  }
  function fail(error: unknown) {
    if (failed) return;
    failed = true;
    cleanup();
    console.error("[skill-completion] skill completion disabled", error);
    try { context?.ui.notify("$ / ¥ / ￥ skill completion disabled after an error; /skill: remains available.", "warning"); }
    catch (error) { console.error("[skill-completion] notification failed", error); }
  }

  pi.on("session_start", (_event, ctx) => {
    context = ctx;
    if (installed || failed || !ctx.hasUI) return;
    installed = true;
    try {
      ctx.ui.addAutocompleteProvider((current): AutocompleteProvider => {
        async function suggestions(lines: string[], line: number, col: number, signal?: AbortSignal) {
          const token = skillToken(lines, line, col);
          if (!token || failed) return null;
          const query = `/skill:${token.slice(1)}`;
          // Native discovery, filtering, ordering and refresh remain the source of truth.
          const result = await current.getSuggestions([query], 0, query.length, signal);
          if (!result || signal?.aborted || failed) return null;
          try {
            const items = result.items.filter(item => item.value.startsWith("skill:") && item.value !== "skill:");
            return items.length ? { items, prefix: token } : null;
          } catch (error) { fail(error); return null; }
        }
        return {
          async getSuggestions(lines, line, col, signal, onPartial) {
            if (!failed && skillToken(lines, line, col)) return suggestions(lines, line, col, signal);
            return current.getSuggestions(lines, line, col, signal, onPartial);
          },
          async getForceFileSuggestions(lines, line, col, signal) {
            if (!failed && skillToken(lines, line, col)) return suggestions(lines, line, col, signal);
            return current.getForceFileSuggestions?.(lines, line, col, signal) ?? null;
          },
          applyCompletion(lines, line, col, item, prefix) {
            if (!failed && /^[$¥￥]/.test(prefix) && item.value.startsWith("skill:")) {
              try {
                const token = skillToken(lines, line, col);
                if (token !== prefix) return { lines, cursorLine: line, cursorCol: col };
                const start = col - token.length;
                const insert = `/${item.value} `;
                const updated = [...lines];
                updated[line] = lines[line].slice(0, start) + insert + lines[line].slice(col);
                return { lines: updated, cursorLine: line, cursorCol: start + insert.length };
              } catch (error) { fail(error); return { lines, cursorLine: line, cursorCol: col }; }
            }
            return current.applyCompletion(lines, line, col, item, prefix);
          },
          getInlineHint: current.getInlineHint?.bind(current),
          trySyncSlashCompletion: current.trySyncSlashCompletion?.bind(current),
          trySyncInlineReplace: current.trySyncInlineReplace?.bind(current),
          shouldTriggerFileCompletion: current.shouldTriggerFileCompletion?.bind(current),
        };
      });
      const previous = ctx.ui.getEditorComponent();
      const factory: NonNullable<typeof previous> = (tui, theme, keybindings) => {
        const editor = previous ? previous(tui, theme, keybindings) : new CustomEditor(tui, theme, keybindings);
        const original = editor.handleInput;
        const handleInput = (data: string) => {
          const revision = editor.textRevision;
          original.call(editor, data);
          if (failed || editor.textRevision === revision || editor.isAutocompleteActive() || !/^[\x20-\x7e\x7f¥￥]+$/.test(data)) return;
          let trigger = false;
          try {
            const cursor = editor.getCursor();
            trigger = !!skillToken(editor.getLines(), cursor.line, cursor.col);
          } catch (error) { fail(error); }
          // shortcut: OMP 18.12.6 has no public popup trigger; replace when the editor exposes one.
          // Native Tab opens a list (even for one match); it does not accept it.
          if (trigger) original.call(editor, "\t");
        };
        cleanups.push(() => { if (editor.handleInput === handleInput) editor.handleInput = original; });
        editor.handleInput = handleInput;
        return editor;
      };
      cleanups.push(() => { if (ctx.ui.getEditorComponent() === factory) ctx.ui.setEditorComponent(previous); });
      ctx.ui.setEditorComponent(factory);
    } catch (error) { fail(error); }
  });
  pi.on("session_shutdown", cleanup);
}

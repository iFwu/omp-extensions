import type { ExtensionAPI } from "@oh-my-pi/pi-coding-agent";
import { fieldComposerStyle, theme, truncateToWidth, visibleWidth } from "@oh-my-pi/pi-tui";

function sessionTitle(name: string | undefined): string {
  if (!name) return "";
  return name.replace(/\u001b\[[0-?]*[ -/]*[@-~]/g, "").replace(/[\u0000-\u001f\u007f]/g, "").trim();
}

function renderSessionTitle(
  chrome: { width: number; paddingX: number; accentColor: (text: string) => string },
  name: string | undefined,
): string {
  const title = sessionTitle(name);
  if (!title || chrome.width <= 0) return "";
  const margin = Math.min(chrome.paddingX, chrome.width);
  const text = truncateToWidth(title, chrome.width - margin);
  const gap = chrome.width - margin - visibleWidth(text);
  return `${" ".repeat(Math.max(0, gap))}${chrome.accentColor(text)}`;
}

const TITLE_AND_BORDER = 2;

// shortcut: omp 18.11 editor max-height (`eve`); upgrade when that cap changes.
function editorMaxHeight(terminalRows: number): number {
  const rows = Number.isFinite(terminalRows) && terminalRows > 0 ? terminalRows : 24;
  const preferred = Math.max(6, Math.min(18, rows - 12));
  return Math.max(3, Math.min(preferred, rows - 4));
}

function shadedPadding(): number {
  return editorMaxHeight(process.stdout.rows || 24) >= TITLE_AND_BORDER + 3 ? 1 : 0;
}

export function registerComposer(pi: ExtensionAPI, displayFailure: (name: string, error: unknown) => void) {
  let inputRows = 0;
  let composerFailed = false;
  function failComposer(error: unknown) {
    if (composerFailed) return;
    composerFailed = true;
    displayFailure("Composer styling", error);
  }

  pi.registerComposerShape({
    label: "Shaded Input + OMP Dock",
    description: "Shaded input with a blank row above and below the text, and the native OMP status below",
    style: {
      ...fieldComposerStyle,
      id: "dotfiles/claude-context",
      filledSurface: true,
      get verticalChrome() {
        // shortcut: OMP 18.12 budgets arbitrary rows; remove this cast when custom chrome counts are typed.
        return (TITLE_AND_BORDER + shadedPadding() * 2) as typeof fieldComposerStyle.verticalChrome;
      },
      statusAttachment: "top-border",
      bottomBar: "none",
      bottomBarGap: false,
      defaultPaddingX() {
        return 2;
      },
      sideChromeWidth(paddingX) {
        return paddingX;
      },
      renderTop(chrome) {
        inputRows = 0;
        if (composerFailed) return undefined;
        try { return renderSessionTitle(chrome, pi.getSessionName()); }
        catch (error) { failComposer(error); return undefined; }
      },
      renderRow(row) {
        const content = " ".repeat(row.paddingX) + row.gutter + row.text;
        const plain = row.imeSafeCursorTail ? content
          : content + row.pad + " ".repeat(Math.max(0, row.paddingX - row.cursorOverflow));
        if (composerFailed) return [plain];
        try {
          const line = theme.bgFill("statusLineBg", plain);
          const padding = shadedPadding();
          const empty = theme.bgFill("statusLineBg", " ".repeat(row.width));
          const lines = [];
          if (inputRows === 0 && padding > 0) lines.push(empty);
          lines.push(line);
          inputRows++;
          if (row.isLastRow) {
            if (padding > 0) {
              lines.push(empty);
            } else {
              const terminalRows = process.stdout.rows || 24;
              const minimumRows = Math.min(3, Math.max(1, terminalRows - 2));
              if (inputRows < minimumRows) {
                if (inputRows === 1 && minimumRows === 3) {
                  lines.unshift(empty);
                  inputRows++;
                }
                while (inputRows < minimumRows) {
                  lines.push(empty);
                  inputRows++;
                }
              }
            }
          }
          return lines;
        } catch (error) { failComposer(error); return [plain]; }
      },
      renderBottom(chrome) {
        if (composerFailed || (process.stdout.rows || 24) < 2) return undefined;
        try {
          const border = chrome.topBorder;
          if (!border) return chrome.borderColor(chrome.box.horizontal.repeat(chrome.width));
          return border.content
            + chrome.borderColor(chrome.box.horizontal.repeat(Math.max(0, chrome.width - border.width)));
        } catch (error) { failComposer(error); return undefined; }
      },
    },
  });
}

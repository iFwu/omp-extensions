import type { ExtensionContext } from "@oh-my-pi/pi-coding-agent";

export async function promptMaskedSecret(
  ctx: ExtensionContext,
  title: string,
  signal?: AbortSignal,
): Promise<string | undefined> {
  if (ctx.mode !== "tui" || !ctx.hasUI) return undefined;
  const value = await ctx.ui.input(title, undefined, { secret: true, signal });
  return value && value.trim() ? value : undefined;
}

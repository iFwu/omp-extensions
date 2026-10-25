import { closeSync, constants, mkdirSync, openSync, writeSync } from "node:fs";
import type { Suggestion, SuggestionContext } from "./suggestion";

export type FeedbackEvent =
  | { type: "requested"; context: SuggestionContext; model: string; effort: string; promptVersion: string }
  | { type: "generated"; context: SuggestionContext; result: Suggestion; model: string; effort: string; promptVersion: string; latencyMs: number }
  | { type: "displayed" }
  | { type: "accepted"; index: number; draft: string }
  | { type: "submitted"; outcome: "accepted" | "edited" | "other"; text: string; displayed: boolean; truncated: boolean }
  | { type: "ended"; reason: string; displayed: boolean; accepted: boolean }
  | { type: "cancelled" | "dismissed" | "skipped" | "failed"; reason: string };

export function appendFeedback(directory: string, file: string, id: string, event: FeedbackEvent): void {
  mkdirSync(directory, { recursive: true, mode: 0o700 });
  const fd = openSync(file, constants.O_WRONLY | constants.O_APPEND | constants.O_CREAT | constants.O_NOFOLLOW, 0o600);
  try {
    const line = Buffer.from(`${JSON.stringify({ schema: 1, id, at: new Date().toISOString(), ...event })}\n`);
    let written = 0;
    while (written < line.length) written += writeSync(fd, line, written, line.length - written);
  } finally {
    closeSync(fd);
  }
}

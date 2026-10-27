export function summarizeError(error: unknown, stage: "provider" | "parse"): string {
  // JSON parser messages can quote the model's private response.
  if (stage === "parse" && error instanceof SyntaxError) return "Invalid suggestion JSON";
  const message = error instanceof Error ? error.message : typeof error === "string" ? error : "Unknown generation error";
  const code = error instanceof Error && "code" in error && typeof error.code === "string" && /^[A-Z][A-Z0-9_]{1,79}$/.test(error.code)
    ? `${error.code}: ` : "";
  const summary = Bun.stripANSI(code + message).split(/[\r\n\u2028\u2029]/, 1)[0]!
    .replace(/(?:\{|\[|<!doctype\b|<html\b|(?:request|response)\s*(?:body|headers)\s*[:=])[\s\S]*/i, " [details omitted]")
    .replace(/https?:\/\/[^\s<>"']+/gi, "<URL>")
    .replace(/\b(?:Bearer|Basic)\s+[^\s,;]+/gi, "<credential>")
    .replace(/\b(?:authorization|api[-_ ]?key|access[-_]?token|refresh[-_]?token|token|password|secret|cookie)\b\s*[:=]\s*(?:"[^"]*"|'[^']*'|[^\s,;]+)/gi, "<credential>")
    .replace(/\b(?:sk-|sess-)[a-zA-Z0-9_-]+/g, "<credential>")
    .replace(/"[^"\r\n]*"|'[^'\r\n]*'/g, "<quoted detail>")
    .replace(/[\u0000-\u001f\u007f-\u009f]/g, " ")
    .trim();
  return summary.length > 500 ? `${summary.slice(0, 499)}…` : summary || "Unknown generation error";
}

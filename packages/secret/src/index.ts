import type { ExtensionAPI, ExtensionContext } from "@oh-my-pi/pi-coding-agent";
import { getPluginSettings } from "@oh-my-pi/pi-coding-agent/extensibility/plugins";
import { activeVault, activeScopeKey, dropSessionVault, setActiveScopeKey, vaultForSession, type Vault } from "./vault.ts";
import {
  captureFromText,
  findGuesses,
  injectToolCall,
  scrubDeepFailClosed,
  scrubOutputSnapshot,
  recordReadOrigins,
  scrubToolResult,
  vaultAdopter,
  type CaptureScope,
} from "./glue.ts";
import { bashIsOwnedByPiSecret, registerSecureBash } from "./tools/bash.ts";
import { createSecretTool } from "./tools/secret.ts";
import { bashRedirectWarning } from "./redirect.ts";
import { createSecAutocompleteProvider } from "./autocomplete.ts";
import { RECEIPT_TYPE, type Receipt, type ReceiptItem } from "./receipt.ts";
import { fingerprint } from "./refs.ts";
import { isEnabled, setEnabled, isDeclined, declineValue, resetDeclined } from "./state.ts";
import { registerCommands } from "./commands.ts";
import { withPiSecretPrompt } from "./prompt.ts";


/**
 * "Session" means one session FILE (spec §7). Keying the vault by it is what makes
 * `/reload` survive — pi re-evaluates this module on reload, so ordinary module
 * state is destroyed — while `/new`, `/fork` and `/resume` land on a different key
 * and therefore a different vault.
 */
function sessionScope(ctx: ExtensionContext): string {
  return ctx.sessionManager.getSessionFile() ?? `ephemeral:${ctx.sessionManager.getSessionId()}`;
}

/**
 * Deliberately NOT `activeVault()`: the dispatcher and tools may be invoked before
 * any session_start has bound a scope, and activeVault() throws when none is. The
 * ctx always carries the session file, so this is total.
 */
function vault(ctx: ExtensionContext): Vault {
  return vaultForSession(sessionScope(ctx));
}

/**
 * The receipt is for auditability, not correctness: if it cannot be written the
 * capture is still valid, so a throwing appendEntry must never cost the user their
 * (already vaulted) secret or abort the turn.
 */
function appendReceipt(pi: ExtensionAPI, captured: ReceiptItem[]): void {
  try {
    pi.appendEntry(RECEIPT_TYPE, { captured } satisfies Receipt);
  } catch {
    /* best-effort: the capture already happened and the vault already holds it */
  }
}

function fileReadsEnabled(pi: ExtensionAPI): boolean {
  try {
    return Boolean(pi.getFlag("sec-file-reads"));
  } catch {
    return false;
  }
}

/**
 * Among extensions the FIRST registration of a tool name wins, so another loaded
 * extension can take `bash` from us silently: refs would then reach the child as
 * literal `{{sec:…}}` text with no error from pi at all. That is worth saying out
 * loud, once per session, but never at the cost of failing session start.
 */
/**
 * Tracks whether pi's provider-level payload hook actually ran. See the `turn_end`
 * handler for why this is measured rather than assumed.
 */
let providerHookFired = false;
let providerHookWarned = false;

function ownsBash(pi: ExtensionAPI): boolean {
  try {
    return bashIsOwnedByPiSecret(pi);
  } catch {
    return true;
  }
}

/**
 * The shape-only candidates, as one question a person can answer.
 *
 * Every field is a REASON we think this is a secret and nothing that says it is: no
 * keyword, no provider format, just length and character distribution. Showing that
 * plainly is the point — the alternative is what a receipt said on 2026-10-09,
 * `sec:secret · len 21`, which gave the reader no way to tell a guess from a fact.
 */
function guessSummary(guesses: Array<{ value: string; evidence?: string }>): string {
  const lines = guesses.map((g, i) => {
    const parts = [`len ${g.value.length}`, `sha ${fingerprint(g.value)}`, g.evidence ?? ""];
    return `  ${i + 1}. ${parts.filter(Boolean).join(" · ")}`;
  });
  return [
    "possible secret, but nothing but its shape says so",
    "",
    ...lines,
    "",
    "Capture? yes = replace with a secret reference. no = send your text unchanged.",
    "Declining remembers this value: it will not ask again this session.",
  ].join("\n");
}

/**
 * The capture policy on the input path.
 *
 * A capture backed by evidence — a provider prefix, a keyword, a flag, a Chinese password
 * word — is applied without asking, exactly as before. A capture backed only by shape is
 * ASKED about first, because rewriting someone's sentence on a guess is the one failure
 * that is both silent and unrecoverable: the rewrite happens before the message is
 * persisted, so the original text is gone from the session file afterwards.
 *
 * Where asking is impossible — `pi --print`, an RPC client with no dialogs, or the flag
 * turned off — the guess is DROPPED rather than applied. Dropping is the safe direction
 * for automation: the value reaches the endpoint unmasked, which is a false negative
 * someone can see in the request, while an unattended false positive silently rewrites
 * work the user can no longer reconstruct.
 */
async function decideScope(
  text: string,
  ctx: ExtensionContext,
  confirmGuesses: boolean,
): Promise<{ scope: CaptureScope; leftAlone: number }> {
  const pending = findGuesses(text).filter((c) => !isDeclined(c.value));
  if (!pending.length) return { scope: "all", leftAlone: 0 };
  // Flag off is the user opting OUT of the gate, which restores the old behaviour of
  // applying every guess. It is NOT the same as having no way to ask: see below.
  if (!confirmGuesses) return { scope: "all", leftAlone: 0 };
  // No dialog-capable UI (pi --print, an RPC client): there is nobody to answer the
  // question, so the guess is DROPPED rather than applied unattended. The value reaches
  // the endpoint unmasked, which is a false negative visible in the request, while an
  // unattended false positive silently rewrites work the user cannot reconstruct.
  if (!ctx.hasUI) return { scope: "evidenced", leftAlone: pending.length };
  const approved = await ctx.ui.confirm("pi-secret: capture a possible secret?", guessSummary(pending));
  if (approved) return { scope: "all", leftAlone: 0 };
  for (const g of pending) declineValue(g.value);
  return { scope: "evidenced", leftAlone: pending.length };
}

/**
 * The adopter for the hooks that see the whole conversation (`context`, the provider
 * payload). Whatever first lands in the vault from there is announced by name, same as
 * from tool_result: an adopted credential is the one entry nobody typed. A repeat is
 * silent, because the adopter reports only names that are new.
 */
function announcingAdopter(v: Vault, ctx: ExtensionContext) {
  return vaultAdopter(v, (name) => {
    if (!ctx.hasUI) return;
    try {
      ctx.ui.notify(`pi-secret: stored sec:${name} from the conversation for this session`, "info");
      ctx.ui.setStatus("pi-secret", `sec: ${v.size()} active`);
    } catch {
      /* a notice is not worth failing the request over */
    }
  });
}

export default function secretExtension(pi: ExtensionAPI): void {
  pi.registerFlag("secret", { type: "boolean", description: "Enable session-local masked credential input" });
  pi.registerFlag("sec-file-reads", { type: "boolean", default: true, description: "Mask credential shapes in file-tool output" });
  pi.registerFlag("sec-confirm-guess", { type: "boolean", default: true, description: "Confirm shape-only credential capture" });
  let initialized = false;
  pi.on("session_start", async (_event, ctx) => {
    if (initialized || ctx.agent.kind !== "main") return;
    initialized = true;
    const [standalone, suite] = await Promise.all([
      getPluginSettings("@ifwu/omp-secret", ctx.cwd),
      getPluginSettings("@ifwu/omp-extensions", ctx.cwd),
    ]);
    if ((pi.getFlag("secret") ?? standalone.enabled ?? suite.secret) !== true) return;
    const bash = pi.getAllTools().find(tool => tool.name === "bash");
    if (!bash || bash.sourceInfo.path !== "<builtin:bash>" || !pi.getActiveTools().includes("bash")) {
      if (ctx.hasUI) ctx.ui.notify("Session credentials require the native Bash tool; credential support remains disabled.", "warning");
      return;
    }
    activate(pi, ctx);
  });
}

function activate(pi: ExtensionAPI, ctx: ExtensionContext): void {
  setEnabled(true);
  pi.registerTool(createSecretTool(activeVault));
    // A reload rebuilds the extension but not the process, so these two must not be
    // sticky across sessions or the warning would never fire for a later session.
    providerHookFired = false;
    providerHookWarned = false;
    resetDeclined();
    setActiveScopeKey(sessionScope(ctx));
    registerSecureBash(pi, ctx.cwd, { vault: activeVault });
    // spec §5's discovery surface: `{{sec:` completes from the vault. It lives on the UI
    // context, not the ExtensionAPI, so it is registered here rather than at load. The
    // provider itself handles being asked before a vault exists (activeVault throws, and
    // the provider returns null) — an autocomplete popup that throws would take the
    // editor's key handling down with it.
    try {
      // WRAPPER, not replacement: pi calls the factory with the provider already
      // installed (its built-in command/file provider, or another extension's wrapper)
      // and uses the RESULT. Returning a standalone provider silently discards the
      // built-in completion chain — `/` commands, `@` files and Tab file completion all
      // answer null — so `current` must be threaded through.
      ctx.ui.addAutocompleteProvider((current) => createSecAutocompleteProvider(activeVault, current));
    } catch {
      // Headless (no UI context): there is no editor to complete in.
    }

    if (!ownsBash(pi)) {
      // Best-effort, like appendReceipt above: a UI context without notify must not cost
      // the user their session, and this is a diagnostic rather than something they can act
      // on mid-startup anyway.
      try {
        ctx.ui.notify(
          "pi-secret: another extension owns `bash`, so {{sec:…}} refs will NOT expand. " +
            "Extension load order decides this — first registration of a tool name wins — " +
            "so load pi-secret before the other extension, or disable it.",
          "error",
        );
      } catch {
        /* no UI to tell; the failure mode is visible anyway the moment a ref is used */
      }
    }
    if (ctx.hasUI) ctx.ui.setStatus("pi-secret", `sec: ${vault(ctx).size()} active`);

  const resetSession = (_event: unknown, ctx: ExtensionContext) => {
    if (ctx.agent.kind !== "main") return;
    const previous = activeScopeKey();
    if (previous) dropSessionVault(previous);
    setActiveScopeKey(sessionScope(ctx));
    resetDeclined();
    setEnabled(true);
    if (ctx.hasUI) ctx.ui.setStatus("pi-secret", "sec: 0 active");
  };
  pi.on("session_switch", resetSession);
  pi.on("session_branch", resetSession);
  pi.on("session_shutdown", async (_event, ctx) => {
    if (ctx.agent.kind !== "main") return;
    const previous = activeScopeKey();
    if (previous) dropSessionVault(previous);
    setActiveScopeKey(undefined);
    if (ctx.hasUI) ctx.ui.setStatus("pi-secret", undefined);
  });

  pi.on("before_agent_start", async (event, ctx) => {
    if (!isEnabled() || ctx.agent.kind !== "main") return undefined;
    return { systemPrompt: withPiSecretPrompt(event.systemPrompt) };
  });

  pi.on("input", async (event, ctx) => {
    if (!isEnabled() || event.source === "extension") return undefined;
    let confirmGuesses = true;
    try {
      confirmGuesses = pi.getFlag("sec-confirm-guess") !== false;
    } catch {
      /* no flag support: keep the safer default */
    }
    const { scope, leftAlone } = await decideScope(event.text, ctx, confirmGuesses);
    const out = captureFromText(event.text, vault(ctx), { scope });
    if (out.captured.length) {
      appendReceipt(pi, out.captured);
      ctx.ui.notify(
        out.captured
          .map((c) => `captured sec:${c.name} · ${c.label} · len ${c.length}${c.evidence ? ` · ${c.evidence}` : ""}`)
          .join("\n"),
        "info",
      );
    }
    if (leftAlone > 0) {
      // Said out loud on purpose: a silent no-op looks identical to a detector that
      // simply did not fire, and the user cannot tell those apart.
      ctx.ui.notify(
        `pi-secret: left ${leftAlone} possible secret(s) in your text (no keyword, shape only)`,
        "warning",
      );
    }
    if (out.captured.length && ctx.hasUI) ctx.ui.setStatus("pi-secret", `sec: ${vault(ctx).size()} active`);
    if (!out.captured.length) return undefined;
    // The value is already in the vault and the text now carries only the ref, so
    // this transform runs BEFORE persistence — nothing sensitive reaches the file.
    return { text: out.text };
  });

  pi.on("tool_call", async (event, ctx) => {
    if (event.toolName === "bash" && isEnabled()) {
      // spec §9's notify-only row. The command still runs — blocking would break
      // `printf '%s' {{sec:x}} > ~/.netrc`, which is a real thing to want, and the file it
      // lands in is outside our protection anyway.
      //
      // The warning goes to ctx.ui.notify ONLY. It must never enter model context: a model
      // told "your command wrote a masked ref to a file" reliably tries to fix it by
      // rewriting the file, which is exactly the corruption this row exists to avoid. So
      // this hook still returns undefined on the warn path.
      const rawCommand = (event.input as { command?: unknown }).command;
      const warning = bashRedirectWarning(typeof rawCommand === "string" ? rawCommand : "");
      if (warning) ctx.ui.notify(warning.message, "warning");
    }
    if (!isEnabled()) return undefined;
    // OMP persists revised tool_call inputs; expansion must never mutate this event.
    const input = structuredClone(event.input) as Record<string, unknown>;
    const out = injectToolCall(event.toolName, input, vault(ctx), { cwd: ctx.cwd });
    // §12h: deliberate allows on doc/test targets tell the USER (names only, no
    // values) — same channel and same rule as the redirect warning above.
    if (out.notify && ctx.hasUI) ctx.ui.notify(out.notify, "info");
    if (out.blocked) return { block: true, reason: out.blocked.reason };
    if (out.expanded.length) return {
      block: true,
      reason: "pi-secret: OMP credential substitution is supported in bash only. Use a foreground bash command with {{sec:NAME}}; never request or print the value.",
    };
    return undefined;
  });

  pi.on("tool_result", async (event, ctx) => {
    const v = vault(ctx);
    const adopted: string[] = [];
    // Gated on the switch, unlike the scrub itself: `/sec off` empties the vault on purpose,
    // and adopting here would quietly refill it. Masking still happens, with the marker.
    const enabled = isEnabled();
    const adopt = enabled ? vaultAdopter(v, (name) => adopted.push(name)) : undefined;
    const out = scrubToolResult(
      { toolName: event.toolName, content: event.content as unknown[], details: event.details },
      v,
      { fileReads: fileReadsEnabled(pi), adopt },
    );
    // pi writes an UNSCRUBBED snapshot when bash truncates, and hands the model a
    // path to read it from — rewrite or drop it before the result is persisted.
    scrubOutputSnapshot(out.details ?? event.details, v, adopt);
    // After the scrub, so a credential adopted from this read already has a vault entry.
    if (enabled) try {
      recordReadOrigins(
        { toolName: event.toolName, input: event.input as Record<string, unknown>, content: event.content as unknown[] },
        v,
        ctx.cwd,
      );
    } catch {
      /* best-effort: without an origin a write-back is refused, which is the old behaviour */
    }
    if (out.hits && ctx.hasUI) {
      // Never interpolate event.input here: it carries EXPANDED args with real values.
      // Names only, and the user sees them: an adopted credential is the one vault entry
      // nobody typed, so it is announced rather than appearing silently in /sec list.
      const stored = adopted.length ? ` — stored as ${adopted.map((n) => `sec:${n}`).join(", ")} for this session` : "";
      ctx.ui.notify(`pi-secret masked ${out.hits} secret occurrence(s) in ${event.toolName} output${stored}`, "info");
    }
    if (adopted.length && ctx.hasUI) ctx.ui.setStatus("pi-secret", `sec: ${v.size()} active`);
    // A screenshot cannot be scrubbed — masking base64 corrupts the image and the
    // provider rejects the request — so image and other binary payloads pass through
    // byte-identical. Saying so is the whole point: a silent pass-through reads as
    // "checked, found nothing", and this is the one case where that is false.
    if (out.skippedBinary && ctx.hasUI) {
      ctx.ui.notify(
        `pi-secret left ${out.skippedBinary} binary payload(s) in ${event.toolName} unscrubbed — ` +
          "image/audio content is never filtered, so a secret visible inside a screenshot still reaches the provider",
        "info",
      );
    }
    // Returned unconditionally, including when hits === 0: this hook is the primary
    // guarantee (it runs before the result message is built and persisted), so the
    // caller must never be left deciding what to do with unsanitised text.
    return { content: out.content as never, details: out.details as never, isError: event.isError };
  });

  pi.on("context", async (event, ctx) => {
    if (!isEnabled()) return undefined;
    // Adopts too: content that reached context without passing tool_result (`!` user bash,
    // a session from before pi-secret, `sec-file-reads` off) gets usable refs, not the marker.
    const v = vault(ctx);
    const out = scrubDeepFailClosed(event.messages as unknown, v, { shapes: true, adopt: announcingAdopter(v, ctx) }, (cls) =>
      ctx.ui.notify(`pi-secret: context scrub failed closed (${cls})`, "error"),
    );
    return out.hits ? { messages: out.value as never } : undefined;
  });

  /**
   * NOTHING is hooked on the model's own output. Deliberate, not an omission.
   *
   * The contract is one-directional: a secret must never REACH the endpoint. Text
   * that came FROM the model is left exactly as the model produced it — no
   * `message_end` rewrite, no compaction-summary rewrite, no on-disk mending of
   * the session file. `context` and `before_provider_request` already scrub that
   * same text on the way out, so filtering it again here bought nothing outbound
   * and cost a rewritten transcript: a literal the model echoed (only reachable
   * after a leak upstream, e.g. `sec-file-reads` off) used to be replaced in the
   * session JSONL, /export and /resume. It now stays verbatim there, and still
   * never leaves the machine.
   */
  pi.on("before_provider_request", (event, ctx) => {
    // Recorded BEFORE the enabled check on purpose: this measures whether the HOST
    // provides the hook, which is a property of the provider, not of our switch. A
    // deliberate `/sec off` must not read as a provider defect — and that case is
    // suppressed separately in turn_end.
    providerHookFired = true;
    if (!isEnabled()) return undefined;
    // Last mile: the bytes actually leaving the machine. Note the layering, because it is
    // not uniform: `context` fires on EVERY provider request, while this hook only exists
    // where the provider's own api invokes onPayload (all of pi-ai 0.85.1's do; the faux
    // provider does not, which is why the canary harness has to inject the callback
    // itself). The durable guarantee is context + message_end + tool_result; this is a
    // provider-dependent extra layer, and `turn_end` below measures whether it exists.
    const v = vault(ctx);
    const out = scrubDeepFailClosed(event.payload as unknown, v, { shapes: true, adopt: announcingAdopter(v, ctx) }, (cls) =>
      ctx.ui.notify(`pi-secret: provider payload scrub failed closed (${cls})`, "error"),
    );
    return out.hits ? (out.value as never) : undefined;
  });

  pi.on("turn_end", async (_event, ctx) => {
    if (providerHookFired || providerHookWarned || !isEnabled()) return;
    providerHookWarned = true;
    ctx.ui.notify(
      "pi-secret: this provider never invoked the payload hook, so the provider-level net is absent. " +
        "The transcript, tool results and model context are still scrubbed — only the final " +
        "provider-specific request body is not double-checked.",
      "warning",
    );
  });

  registerCommands(pi);
}

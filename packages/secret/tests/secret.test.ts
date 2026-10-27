import { beforeEach, describe, expect, it } from "bun:test";
import type { ExtensionContext, ToolDefinition } from "@oh-my-pi/pi-coding-agent";
import { createSecretTool } from "../src/tools/secret.ts";
import { Vault } from "../src/vault.ts";
import { setEnabled } from "../src/state.ts";

beforeEach(() => setEnabled(true));

const VALUE = "fake-for-tests-only-'\"$ space";

function context(custom: () => Promise<{ value?: string }>, hasUI = true): ExtensionContext {
  return { mode: hasUI ? "tui" : "rpc", hasUI, ui: { custom, setStatus() {} } } as unknown as ExtensionContext;
}

async function invoke(tool: ToolDefinition, input: Record<string, unknown>, ctx: ExtensionContext, signal?: AbortSignal) {
  const result = await tool.execute("fixture", input, signal, undefined, ctx);
  const raw = JSON.stringify(result);
  expect(raw).not.toContain(VALUE);
  const block = result.content[0];
  if (block?.type !== "text") throw new Error("Expected credential result text");
  return JSON.parse(block.text);
}

const request = { action: "request", name: "api", reason: "Authenticate the requested test operation" };

describe("on-demand session credentials", () => {
  it("lists only refs, without values, previews, fingerprints or lengths", async () => {
    const vault = new Vault("list");
    vault.add("api", VALUE, "prompt");
    const tool = createSecretTool(() => vault);
    const result = await invoke(tool, { action: "list" }, context(async () => { throw new Error("unexpected dialog"); }));
    expect(result).toEqual({ status: "listed", refs: ["{{sec:api}}"] });
  });

  it("does not expose the main-session vault to a subagent", async () => {
    const ctx = context(async () => { throw new Error("unexpected dialog"); });
    ctx.agent = { kind: "sub", id: "child", name: "worker", depth: 1, parentId: "main" };
    const tool = createSecretTool(() => { throw new Error("subagent reached the main vault"); });
    expect((await invoke(tool, { action: "list" }, ctx)).status).toBe("unavailable");
    expect((await invoke(tool, request, ctx)).status).toBe("unavailable");
  });

  it("stores dialog input and reuses an existing name without overwriting or prompting", async () => {
    const vault = new Vault("request");
    const tool = createSecretTool(() => vault);
    let prompts = 0;
    const ctx = context(async () => { prompts++; return { value: VALUE }; });
    expect(await invoke(tool, request, ctx)).toEqual({ status: "stored", ref: "{{sec:api}}" });
    expect(vault.resolve("api")).toBe(VALUE);
    expect(await invoke(tool, request, ctx)).toEqual({ status: "available", ref: "{{sec:api}}" });
    expect(prompts).toBe(1);
  });

  it("refuses headless input without falling back to a plaintext prompt", async () => {
    const vault = new Vault("headless");
    const result = await invoke(createSecretTool(() => vault), request,
      context(async () => { throw new Error("unexpected dialog"); }, false));
    expect(result.status).toBe("unavailable");
    expect(vault.size()).toBe(0);
  });

  it("cancellation and a pre-aborted call do not store credentials", async () => {
    const vault = new Vault("cancel");
    const tool = createSecretTool(() => vault);
    expect(await invoke(tool, request, context(async () => ({})))).toEqual({ status: "cancelled" });
    expect(await invoke(tool, request, context(async () => { throw new Error("unexpected dialog"); }), AbortSignal.abort()))
      .toEqual({ status: "cancelled" });
    expect(vault.size()).toBe(0);
  });

  it("rejects a short value without reflecting it in the result", async () => {
    const vault = new Vault("short");
    const result = await invoke(createSecretTool(() => vault), request, context(async () => ({ value: "1234" })));
    expect(result.status).toBe("invalid");
    expect(JSON.stringify(result)).not.toContain("1234");
    expect(vault.size()).toBe(0);
  });

  it("rejects NUL-bearing input without returning or storing it", async () => {
    const vault = new Vault("nul");
    const value = "synthetic\u0000credential";
    const result = await invoke(createSecretTool(() => vault), request, context(async () => ({ value })));
    expect(result.status).toBe("invalid");
    expect(JSON.stringify(result)).not.toContain("synthetic");
    expect(vault.size()).toBe(0);
  });

  it("discards input when disabled while the dialog is pending", async () => {
    const vault = new Vault("disabled");
    const gate = Promise.withResolvers<{ value?: string }>();
    const pending = invoke(createSecretTool(() => vault), request, context(() => gate.promise));
    setEnabled(false);
    gate.resolve({ value: VALUE });
    expect(await pending).toEqual({ status: "cancelled" });
    expect(vault.size()).toBe(0);
  });

  it("discards input when aborted while the dialog is pending", async () => {
    const vault = new Vault("aborted");
    const gate = Promise.withResolvers<{ value?: string }>();
    const controller = new AbortController();
    const pending = invoke(createSecretTool(() => vault), request, context(() => gate.promise), controller.signal);
    controller.abort();
    gate.resolve({ value: VALUE });
    expect(await pending).toEqual({ status: "cancelled" });
    expect(vault.size()).toBe(0);
  });

  it("refuses a second dialog while the first is pending, then releases the gate", async () => {
    const vault = new Vault("concurrent");
    const tool = createSecretTool(() => vault);
    const gate = Promise.withResolvers<{ value?: string }>();
    const ctx = context(() => gate.promise);
    const first = invoke(tool, request, ctx);
    expect(await invoke(tool, { ...request, name: "other" }, ctx)).toEqual({ status: "busy" });
    gate.resolve({ value: VALUE });
    expect((await first).status).toBe("stored");
    expect((await invoke(tool, { ...request, name: "other" }, context(async () => ({})))).status).toBe("cancelled");
  });

  it("discards input if the active session changes while its dialog is open", async () => {
    const before = new Vault("before");
    const after = new Vault("after");
    let current = before;
    const gate = Promise.withResolvers<{ value?: string }>();
    const pending = invoke(createSecretTool(() => current), request, context(() => gate.promise));
    current = after;
    gate.resolve({ value: VALUE });
    expect(await pending).toEqual({ status: "cancelled" });
    expect(before.size()).toBe(0);
    expect(after.size()).toBe(0);
  });

  it("never returns a raw UI exception", async () => {
    const vault = new Vault("error");
    const result = await invoke(createSecretTool(() => vault), request, context(async () => { throw new Error(VALUE); }));
    expect(result).toEqual({ status: "unavailable" });
    expect(vault.size()).toBe(0);
  });
});

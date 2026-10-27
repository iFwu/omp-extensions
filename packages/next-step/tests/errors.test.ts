import { expect, test } from "bun:test";
import { summarizeError } from "../src/errors";

test("retains actionable provider messages and transport codes", () => {
  const error = Object.assign(new Error("certificate has expired"), { code: "CERT_HAS_EXPIRED" });
  expect(summarizeError(error, "provider")).toBe("CERT_HAS_EXPIRED: certificate has expired");
  expect(summarizeError(new Error("429 Rate limit exceeded"), "provider")).toBe("429 Rate limit exceeded");
  expect(summarizeError("Connection refused", "provider")).toBe("Connection refused");
});

test("does not expose credentials, URLs, headers, or embedded bodies", () => {
  const secrets = [
    "https://user:private-url@example.test/path?key=private-query",
    "Authorization: Bearer private-bearer",
    "api_key=private-key",
    "password='private password'",
    "sk-privatekey",
    'response body: {"prompt":"private prompt"}',
    '\nrequest headers: Authorization: private-header',
    ' {"messages":["private body"]}',
    ' \"private quoted response\"',
  ];
  for (const secret of secrets) {
    const summary = summarizeError(new Error(`TLS failure ${secret}`), "provider");
    expect(summary).toContain("TLS failure");
    expect(summary).not.toContain("private");
  }
  expect(summarizeError({ message: "private object", request: { token: "private key" } }, "provider"))
    .toBe("Unknown generation error");
});

test("parse diagnostics omit syntax excerpts but retain schema violations", () => {
  expect(summarizeError(new SyntaxError('Unexpected token in "private response"'), "parse"))
    .toBe("Invalid suggestion JSON");
  expect(summarizeError(new Error("Invalid action cardinality"), "parse"))
    .toBe("Invalid action cardinality");
});

test("bounds summaries and removes terminal control sequences", () => {
  const summary = summarizeError(new Error(`\x1b[31mTLS\x1b[0m\x00 failure ${"x".repeat(1000)}`), "provider");
  expect(summary).toStartWith("TLS  failure ");
  expect(summary).toHaveLength(500);
  expect(summary).toEndWith("…");
  expect(summary).not.toContain("\x1b");
});

import { describe, expect, it } from "bun:test";
import { envVarName, findRefs, refToken, type Ref } from "../src/refs.ts";

describe("findRefs", () => {
  it("finds every ref with offsets, in order", () => {
    const text = `curl ${refToken("gh_pat")} and ${refToken("db_url")}`;
    const expected: Array<Pick<Ref, "raw" | "name">> = [
      { raw: "{{sec:gh_pat}}", name: "gh_pat" },
      { raw: "{{sec:db_url}}", name: "db_url" },
    ];
    expect(findRefs(text).map((r) => ({ raw: r.raw, name: r.name }))).toEqual(expected);
  });

  it("ignores malformed or uppercase names", () => {
    expect(findRefs("{{sec:GH_PAT}} {{sec:}} {{ sec:x }} {{sec:ok-name}}")).toHaveLength(1);
  });

  it("finds the inner well-formed ref inside a malformed outer token", () => {
    expect(findRefs("{{sec:{{sec:gh}}}}")).toEqual([
      { raw: "{{sec:gh}}", name: "gh", start: 6, end: 16 },
    ]);
  });

  it("returns nothing for plain text", () => {
    expect(findRefs("no refs here")).toEqual([]);
  });
});


describe("envVarName", () => {
  it("maps a secret name to a distinct shell identifier", () => {
    expect(envVarName("gh_pat")).toMatch(/^__PISEC_GH_PAT_[0-9a-f]{16}$/);
    expect(envVarName("db_url-v2")).toMatch(/^__PISEC_DB_URL_V2_[0-9a-f]{16}$/);
  });

  it("is deterministic", () => {
    expect(envVarName("gh_pat")).toBe(envVarName("gh_pat"));
  });

  it("is always a valid POSIX env var name", () => {
    for (const name of ["gh", "a", "z".repeat(64), "with-dash", "with.dot"]) {
      expect(envVarName(name)).toMatch(/^[A-Za-z_][A-Za-z0-9_]*$/);
    }
  });

  it("differs for names that sanitize alike and for long shared prefixes", () => {
    expect(envVarName("a-b")).not.toBe(envVarName("a_b"));
    // No truncation plus a 64-bit tag: names differing anywhere in their first 64
    // chars already differ here, and the 32-bit-tag birthday walk is closed.
    const long = "x".repeat(45);
    expect(envVarName(long + "_a")).not.toBe(envVarName(long + "_b"));
  });

  it("stays a valid identifier and within bounds for a maximum-length name", () => {
    const name = "a".repeat(64);
    expect(envVarName(name)).toMatch(/^[A-Za-z_][A-Za-z0-9_]*$/);
    expect(envVarName(name).length).toBeLessThanOrEqual(89);
  });
});

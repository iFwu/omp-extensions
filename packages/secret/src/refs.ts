import { createHash } from "node:crypto";

/** Explicit reference syntax accepted by credential bash. */
export const REF_RE = /\{\{sec:([a-z][a-z0-9_-]{0,63})\}\}/g;


export interface Ref {
  raw: string;
  name: string;
  start: number;
  end: number;
}

export type SecretResolver = (name: string) => string | undefined;

export function findRefs(text: string): Ref[] {
  const refs: Ref[] = [];
  REF_RE.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = REF_RE.exec(text))) {
    refs.push({ raw: m[0], name: m[1] as string, start: m.index, end: m.index + m[0].length });
  }
  return refs;
}
export const MAX_REF_BYTES = 1024 * 1024;
/** Minimum length for exact-value output redaction. */
export const MIN_CREDENTIAL_LENGTH = 8;

export function validateCredential(value: string): void {
  if (!value.trim()) throw new Error("secret value is empty");
  if (value.length < MIN_CREDENTIAL_LENGTH || value.includes("\u0000")) {
    throw new Error("secret input requires at least 8 characters and cannot contain NUL");
  }
  if (Buffer.byteLength(value, "utf8") > MAX_REF_BYTES) {
    throw new Error("secret value is too large (>1MiB)");
  }
}

export function isValidName(name: string): boolean {
  return /^[a-z][a-z0-9_-]{0,63}$/.test(name);
}

export function parseRef(text: string): string | undefined {
  const m = /^\{\{sec:([a-z][a-z0-9_-]{0,63})\}\}$/.exec(text);
  return m ? m[1] : undefined;
}


/**
 * The shell variable a secret is exported as.
 *
 * The public name is hashed for shell-variable identity, never the credential value.
 * Distinct names must not deliver the wrong credential through a shared variable.
 *
 * Two properties, in order of importance:
 *  - the sanitized body is NOT truncated, so names differing anywhere in their first
 *    64 chars (isValidName caps at 64) already differ here;
 *  - the tag is 64 bits of sha256 over the whole name. 32 bits was breakable: a
 *    40-char window plus an 8-hex tag makes "x"x45+"4a5" and "x"x45+"1y32" collide,
 *    which is a ~2^16 birthday walk. 64 bits makes the targeted search infeasible.
 *
 * Bound: 8 + up to 64 + 1 + 16 = 89 chars, always a valid POSIX identifier.
 */
export function envVarName(name: string): string {
  const sanitized = name.toUpperCase().replace(/[^A-Z0-9]/g, "_");
  const tag = createHash("sha256").update(name, "utf8").digest("hex").slice(0, 16);
  return `__PISEC_${sanitized}_${tag}`;
}

/**
 * Which already-held name, if any, would claim the same shell variable as `name`.
 * Extracted with an injectable resolver so the refusal path is testable: a genuine
 * 64-bit collision cannot be found in a test, and asserting "no collision" on
 * `a-b` vs `a_b` would not exercise the throw at all.
 */
export function findEnvVarCollision(
  existing: Iterable<string>,
  name: string,
  toVar: (n: string) => string = envVarName,
): string | undefined {
  const candidate = toVar(name);
  for (const other of existing) {
    if (other !== name && toVar(other) === candidate) return other;
  }
  return undefined;
}

export function refToken(name: string): string {
  return `{{sec:${name}}}`;
}

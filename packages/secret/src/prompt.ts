export const PI_SECRET_PROMPT = "<pi_secret>Temporary credentials: read xd://secret, then invoke it via write for request/list. Never request credential text in chat. Use {{sec:NAME}} only in foreground bash, without PTY/async. Never print or recover values. Do not retry cancelled requests without user approval.</pi_secret>";

export function withPiSecretPrompt(systemPrompt: string[]): string[] {
  if (systemPrompt.some(part => part.includes("<pi_secret>"))) return systemPrompt;
  return [...systemPrompt, PI_SECRET_PROMPT];
}

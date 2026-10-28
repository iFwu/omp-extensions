export const SECRET_PROMPT = "<secret>When a requested operation needs a temporary credential, read xd://secret and invoke it via write with request/list. Request opens masked user input and returns only a session-local {{sec:NAME}} reference. Never ask for credential text in chat or arguments. Consume references only in foreground bash without PTY/async. Only explicitly entered values are redacted from that command's output; ordinary input and tool output are unchanged. Never print or recover values. Do not retry a cancelled request without user approval.</secret>";

export function withSecretPrompt(systemPrompt: string[]): string[] {
  if (systemPrompt.some(part => part.includes("<secret>"))) return systemPrompt;
  return [...systemPrompt, SECRET_PROMPT];
}

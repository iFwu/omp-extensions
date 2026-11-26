import type { Model } from "@oh-my-pi/pi-ai";
import * as AIError from "@oh-my-pi/pi-ai/error";
import type { ExtensionContext } from "@oh-my-pi/pi-coding-agent";
import { settings } from "@oh-my-pi/pi-coding-agent/config/settings";
import {
  findRetryFallbackCandidates,
  getRetryFallbackChains,
  resolveRetryFallbackChainKey,
  retryFallbackAdmits,
} from "@oh-my-pi/pi-coding-agent/session/retry-fallback-chains";
import { cfgRetry } from "@oh-my-pi/pi-coding-agent/session/settings";

/**
 * Credentialed models to try after `primary` fails, in native `retry.fallbackChains` order.
 * Empty when native retry or model fallback is off, matching the main session's hard-error fallback.
 */
export function fallbackModels(ctx: ExtensionContext, primary: Model, role?: string): Model[] {
  const retry = cfgRetry.get(settings);
  if (!retry.enabled || !retry.modelFallback) return [];
  const registry = ctx.modelRegistry;
  const context = { chains: getRetryFallbackChains(settings), getModelRole: (name: string) => settings.getModelRole(name), modelLookup: registry };
  const selector = `${primary.provider}/${primary.id}`;
  const key = resolveRetryFallbackChainKey(context, selector, primary, role);
  if (!key) return [];
  const models: Model[] = [];
  for (const candidate of findRetryFallbackCandidates(context, key, selector, primary)) {
    const model = registry.find(candidate.provider, candidate.id);
    if (model && model !== primary && !models.includes(model) && registry.hasConfiguredAuth(model)) models.push(model);
  }
  return models;
}

/** Whether a classified provider failure may move to the next model; cancellations never do. */
export function admitsFallback(id: number): boolean {
  if (AIError.is(id, AIError.Flag.Abort) || AIError.is(id, AIError.Flag.UserInterrupt)) return false;
  return retryFallbackAdmits(cfgRetry.get(settings).fallbackOn, AIError.is(id, AIError.Flag.UsageLimit));
}

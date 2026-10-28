let enabled = true;
let generation = 0;

export function setEnabled(value: boolean): void {
  if (enabled !== value) generation++;
  enabled = value;
}

export function isEnabled(): boolean {
  return enabled;
}

/** Pending masked input cannot survive an off/on cycle. */
export function enabledGeneration(): number {
  return generation;
}

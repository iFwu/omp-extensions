"""Grouping labels sit at the native text column and shorten without wrapping."""

from pathlib import Path
import shutil
import subprocess
import unittest

from support import SRC


@unittest.skipUnless(shutil.which("bun"), "Bun is not installed")
class GroupingLineTests(unittest.TestCase):
    def run_formatter(self, assertions):
        script = r"""
import assert from "node:assert/strict";
import { mock } from "bun:test";
const plain = text => text.replace(/\x1b\[[0-9;]*m/g, "");
// All formatter glyphs occupy one cell; only the native width primitive is mocked.
const visibleWidth = text => Array.from(plain(text)).length;
mock.module("@oh-my-pi/pi-tui", () => ({ visibleWidth }));
const { renderGroupingLabel } = await import(process.argv[1]);
const codes = { dim: 2, mdLinkUrl: 34, mdHr: 90, mdLink: 94, borderMuted: 37 };
const theme = isLight => ({ isLight, fg: (color, text) => `\x1b[${codes[color]}m${text}\x1b[0m` });
const colors = theme(false);
const render = (marker, limit) => renderGroupingLabel(marker, limit, colors);
""" + assertions
        result = subprocess.run(
            [shutil.which("bun"), "--no-install", "--eval", script,
             str(SRC / "grouping-line.ts")],
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_blocking_time_yields_to_required_information(self):
        self.run_formatter(r"""
const blocked = plain(render({ kind: "phase", seconds: 1101, tools: 28, failures: 1, blocking: 23 }, 100));
assert.ok(blocked.includes("⟡ 23s") && blocked.includes("28 tools") && blocked.includes("1 failed"));
const narrow = plain(render({ kind: "phase", seconds: 123, tools: 1, failures: 0, blocking: 108 }, 20));
assert.ok(!narrow.includes("⟡") && narrow.includes("2m03s") && narrow.includes("1 tool"));
for (const blocking of [undefined, 0]) {
  assert.ok(!plain(render({ kind: "phase", seconds: 123, tools: 1, failures: 0, blocking }, 100)).includes("⟡"));
}
""")

    def test_duration_boundaries(self):
        self.run_formatter(r"""
for (const [seconds, duration] of [[0, "0s"], [59, "59s"], [60, "1m00s"],
  [182, "3m02s"], [3599, "59m59s"], [3600, "1h00m00s"],
  [3723, "1h02m03s"], [360000, "100h00m00s"]]) {
  assert.ok(plain(render({ kind: "gap", seconds, tools: 0, failures: 0 }, 80)).includes(duration));
}
""")

    def test_only_final_labels_require_two_minutes_of_round_time(self):
        self.run_formatter(r"""
for (const seconds of [0, 10, 30, 119, 119.9]) {
  assert.equal(render({ kind: "final", seconds, tools: 13, failures: 1 }, 160), "");
}
const final = plain(render({ kind: "final", seconds: 120, tools: 0, failures: 0 }, 160));
assert.match(final, /^══ Done · 2m00s ═+$/);
assert.equal(plain(render({ kind: "gap", seconds: 1, tools: 10, failures: 0 }, 160)), "1s · 10 tools");
""")

    def test_narrow_limits_shorten_units_then_drop_time_then_tools(self):
        self.run_formatter(r"""
const final = { kind: "final", seconds: 182, tools: 4, failures: 1 };
const phase = { kind: "phase", seconds: 182, tools: 4, failures: 1 };
for (const marker of [final, phase, { kind: "gap", seconds: 3723, tools: 124, failures: 12 }]) {
  for (const limit of [-2, 0, ...Array.from({ length: 80 }, (_, i) => i + 1), 1000]) {
    const label = render(marker, limit);
    assert.ok(visibleWidth(label) <= Math.max(0, limit), `${marker.kind} at ${limit}`);
    assert.ok(!/[\r\n\t]/.test(plain(label)));
    if (limit >= (marker.kind === "final" ? 10 : 3)) assert.ok(label, `${marker.kind} at ${limit}`);
  }
}
assert.equal(plain(render(phase, 26)), "3m02s · 4 tools · 1 failed");
assert.equal(plain(render(phase, 15)), "3m02s · 4t · 1!");
assert.equal(plain(render(phase, 12)), "3:02 4t 1!");
assert.equal(plain(render(final, 18)), "══ Done 3:02 4t 1!");
assert.equal(plain(render(final, 13)), "══ Done 4t 1!");
assert.equal(plain(render(final, 10)), "══ Done 1!");
assert.equal(render(final, 9), "");
assert.equal(plain(render(phase, 2)), "1!");
""")


if __name__ == "__main__":
    unittest.main()

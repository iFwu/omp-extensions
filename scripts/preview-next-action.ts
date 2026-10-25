// Offline fixture controls only. All suggestion state, rendering and acceptance live in next-step.
import type { ExtensionAPI } from "@oh-my-pi/pi-coding-agent";
import fixtures from "./preview-next-action.fixtures.json";

const scenes = Object.keys(fixtures) as Array<keyof typeof fixtures>;

export default function (pi: ExtensionAPI) {
  pi.registerCommand("preview", {
    description: "Local fixtures: scene ready|decision|done|blocked; delay <seconds>; invalid; failure",
    handler: async (args, ctx) => {
      let command = args.trim();
      if (!command) {
        const choices = [
          ...scenes.map(scene => ({ label: fixtures[scene].name, command: `scene ${scene}` })),
          { label: "延迟建议 3 秒（期间输入再删除，检查过期取消）", command: "delay 3" },
          { label: "建议模型返回无效 JSON", command: "invalid" },
          { label: "建议 provider 失败", command: "failure" },
          { label: "采纳说明（使用真实 /next-step pick）", command: "help" },
        ];
        const selected = await ctx.ui.select("离线 Next-step 场景", choices.map(choice => choice.label));
        command = choices.find(choice => choice.label === selected)?.command ?? "";
        if (!command) return;
      }
      const [kind, value] = command.split(/\s+/);
      if (kind === "scene" && scenes.includes(value as keyof typeof fixtures)) {
        pi.sendUserMessage(fixtures[value as keyof typeof fixtures].prompt);
      } else if (kind === "delay" && value !== undefined && Number.isFinite(Number(value)) && Number(value) >= 0) {
        pi.sendUserMessage(`${fixtures.ready.prompt}\n[preview:delay=${Number(value)}]`);
      } else if (kind === "invalid" || kind === "failure") {
        pi.sendUserMessage(`${fixtures.ready.prompt}\n[preview:${kind}]`);
      } else {
        ctx.ui.notify("/preview scene ready|decision|done|blocked · /preview delay 3 · /preview invalid|failure。单条建议：Enter 发送、Tab 填入输入框；多个选项：↑↓ 选择后 Enter 发送、Tab 填入输入框；Alt+1/2/3 或 /next-step pick 只填入不发送。", "info");
      }
    },
  });
}

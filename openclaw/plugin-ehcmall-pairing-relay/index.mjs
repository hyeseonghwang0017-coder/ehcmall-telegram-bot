/**
 * OpenClaw plugin — pairing relay
 *
 * Owner가 텔레그램 1:1 DM에서 보내는 명령을 가로채서
 * `openclaw pairing` CLI 로 연결한다.
 *
 *   /approve <CODE>   →  openclaw pairing approve telegram <CODE>
 *   /pending          →  openclaw pairing list
 *   /pair-help        →  명령 도움말
 *
 * Owner Telegram 사용자 ID 는 plugin config 로 받는다.
 * Owner 의 다른 일반 메시지는 그대로 통과시켜 본래 봇 동작을 유지한다.
 */
import { spawnSync } from "node:child_process";
import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";

const APPROVE_RE = /^\/approve\s+([A-Za-z0-9]+)\s*$/;
const PENDING_RE = /^\/pending\s*$/;
const HELP_RE = /^\/pair-help\s*$/;

function runCli(args, timeoutMs = 30000) {
  const res = spawnSync("openclaw", args, {
    encoding: "utf-8",
    timeout: timeoutMs,
    maxBuffer: 4 * 1024 * 1024,
  });
  return {
    ok: res.status === 0,
    code: res.status ?? -1,
    stdout: (res.stdout || "").trim(),
    stderr: (res.stderr || "").trim(),
  };
}

export default definePluginEntry({
  id: "ehcmall-pairing-relay",
  name: "EHC Mall pairing relay",
  description:
    "Telegram ehcmall: owner-only /approve, /pending bridge to `openclaw pairing` CLI.",
  register(api) {
    api.on(
      "before_dispatch",
      async (event, ctx) => {
        try {
          if (event.channel !== "telegram") return;

          const acct = api.pluginConfig?.telegramAccountId || "ehcmall";
          if (ctx.accountId !== acct) return;

          const ownerId = String(api.pluginConfig?.ownerTelegramId || "").trim();
          if (!ownerId) return;
          const senderId = String(ctx.senderId || event.senderId || "").trim();
          if (senderId !== ownerId) return;

          const sk = String(event.sessionKey || "");
          if (!sk.includes(":direct:")) return;

          const body = (event.body || event.content || "").trim();
          if (!body) return;

          const mApprove = body.match(APPROVE_RE);
          if (mApprove) {
            const code = mApprove[1].toUpperCase();
            api.logger?.info?.(
              `[pairing-relay] approve request code=${code} owner=${ownerId}`,
            );
            const r = runCli(["pairing", "approve", "telegram", code]);
            if (r.ok) {
              return {
                handled: true,
                text: `✅ 승인 완료: \`${code}\`\n\n\`\`\`\n${r.stdout || "(ok)"}\n\`\`\``,
              };
            }
            return {
              handled: true,
              text: `❌ 승인 실패: \`${code}\`\n\n\`\`\`\n${
                r.stderr || r.stdout || `exit=${r.code}`
              }\n\`\`\``,
            };
          }

          if (PENDING_RE.test(body)) {
            const r = runCli(["pairing", "list"]);
            return {
              handled: true,
              text: r.ok
                ? `📋 대기 중인 pairing 요청:\n\`\`\`\n${r.stdout || "(없음)"}\n\`\`\``
                : `❌ pairing list 실패\n\`\`\`\n${r.stderr || `exit=${r.code}`}\n\`\`\``,
            };
          }

          if (HELP_RE.test(body)) {
            return {
              handled: true,
              text:
                "🔐 *Pairing 명령*\n\n" +
                "`/approve <CODE>` — pairing 승인\n" +
                "`/pending` — 대기 목록\n" +
                "`/pair-help` — 이 도움말",
            };
          }

          return; // owner 의 일반 메시지는 통과
        } catch (err) {
          api.logger?.error?.(`[pairing-relay] error: ${String(err)}`);
          return;
        }
      },
      { priority: 3000 },
    );
  },
});

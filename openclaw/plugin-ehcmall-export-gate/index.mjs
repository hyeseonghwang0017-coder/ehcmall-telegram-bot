/**
 * OpenClaw plugin — before_dispatch (optional)
 *
 * Default `beforeDispatchMode: "agent"`: do nothing here so the conversation LLM
 * can run SKILL_export (1) --search-json-only (2) --tables + --reasons.
 *
 * `beforeDispatchMode: "auto-export"`: run export_tables.py --auto-filter here and
 * skip the chat model for that turn (script-side LLM/heuristic only).
 */
import { spawnSync } from "node:child_process";
import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";

const DEFAULT_PYTHON = "/opt/anaconda3/bin/python3";
const DEFAULT_EXPORT_SCRIPT =
  "/Users/hyeseong/Downloads/ehcmall/ehcmall-telegram-bot/scripts/export_tables.py";

/** DB 전체 개요 리포트(generate_report) 쪽으로 보내야 하는 표현은 게이트 제외 */
function isWholeDbOverviewIntent(text) {
  return /전체\s*(db|데이터베이스)|db\s*전체|개요\s*만|핵심\s*테이블\s*top|reply_report_markdown|\/v1\/overview/i.test(
    text,
  );
}

/**
 * 프로젝트별 테이블·컬럼 메타 export 로 읽히는 요청인지 (느슨하지만 산문 일반 질의는 제외)
 */
function wantsProjectTableExport(text) {
  const t = (text || "").trim();
  if (!t || t.length < 8) return false;
  if (isWholeDbOverviewIntent(t)) return false;

  const hasFileVerb = /(써줘|작성|만들어|뽑아|보내|받고\s*싶|정리해서)/.test(t);
  const hasArtifact = /\b(csv|pdf)\b|리포트|파일|엑셀|스프레드시트/i.test(t);
  const hasTableTopic =
    /(테이블|칼럼|컬럼|메타|카탈로그|스키마|구성안|추천안|분석안)/.test(t) ||
    /(무슨|어떤|뭘)\s*(테이블|칼럼|컬럼)/.test(t) ||
    /추천\s*리포트|관련\s*테이블|쓸\s*테이블|필요한\s*테이블|추천\s*구성안|테이블\s*구성/.test(t);

  if (hasArtifact && hasFileVerb) return true;
  if (/추천\s*리포트/.test(t) && hasFileVerb) return true;
  if (hasTableTopic && hasFileVerb && hasArtifact) return true;
  if (hasTableTopic && /(뽑아|보내|만들어|pdf|csv)/i.test(t)) return true;

  return false;
}

const STOP = new Set([
  "있어요",
  "있어",
  "합니다",
  "해줘",
  "주세요",
  "싶은데",
  "모르겠어",
  "알려",
  "알려줘",
  "추천",
  "리포트를",
  "리포트가",
  "테이블을",
  "테이블은",
  "칼럼은",
  "컬럼은",
  "무슨",
  "어떤",
  "뭘",
  "해야",
  "하는지",
  "구축하고",
  "같은",
  "이런",
  "그런",
  "정말",
  "진짜",
]);

function tokenizeKorean(text) {
  return text.match(/[\u3131-\u318E\uAC00-\uD7A3]{2,}/g) || [];
}

/** 도메인 힌트 → 검색 키워드 (API search에 맞게 짧은 명사 위주) */
function keywordDefaults(text) {
  if (/추천|회원|상품|주문|장바구니|조회|세션|관심/.test(text))
    return ["상품", "회원", "주문"];
  if (/재고/.test(text)) return ["재고"];
  if (/매출|판매/.test(text)) return ["매출"];
  return null;
}

function pickKeywords(text) {
  const hinted = keywordDefaults(text);
  if (hinted) return hinted;
  const out = [];
  for (const w of tokenizeKorean(text)) {
    if (STOP.has(w)) continue;
    if (!out.includes(w)) out.push(w);
    if (out.length >= 3) break;
  }
  if (out.length === 0) return ["데이터"];
  return out;
}

function pickFormat(text) {
  if (/csv|엑셀|스프레드시트/i.test(text)) return "csv";
  return "pdf";
}

function pickProject(text) {
  const m = text.match(
    /([\u3131-\u318E\uAC00-\uD7A3\d\s]{3,48}?)\s*(프로젝트|구축|분석|최적화|시스템)/,
  );
  if (m) return m[1].replace(/\s+/g, " ").trim().slice(0, 80);
  const first = tokenizeKorean(text).find((w) => w.length >= 4 && !STOP.has(w));
  return (first || "프로젝트").slice(0, 80);
}

/** PDF --summary 용 한국어 산문 생성 (auto-export 전용) */
function buildAutoSummary(project, keywords) {
  const kwStr = keywords.join("·");
  return (
    `이번 리포트는 ${project}에 필요한 핵심 데이터를 중심으로 구성했습니다. ` +
    `${kwStr} 관련 도메인의 테이블을 메타데이터 카탈로그에서 수집하여, ` +
    `업무 목적에 직접 연관되는 항목만 선별했습니다. ` +
    `아래 표에서 각 테이블의 구성과 설명을 확인하시기 바랍니다.`
  );
}

export default definePluginEntry({
  id: "ehcmall-export-gate",
  name: "EHC Mall export gate",
  description: "Telegram ehcmall: run export_tables.py on export-shaped messages (before_dispatch).",
  register(api) {
    api.on(
      "before_dispatch",
      async (event, ctx) => {
        try {
          if (ctx.accountId !== (api.pluginConfig?.telegramAccountId || "ehcmall")) return;
          if (event.channel !== "telegram") return;
          const sk = event.sessionKey || "";
          if (!sk.startsWith("agent:ehcmall:")) return;

          const body = (event.body || event.content || "").trim();
          if (!wantsProjectTableExport(body)) return;

          /** agent: pass through to conversation LLM (JSON 1단계 + 스킬). auto-export: 여기서 스크립트만 실행 */
          const gateMode = (api.pluginConfig?.beforeDispatchMode ?? "agent").trim();
          if (gateMode !== "auto-export") return;

          const chatId = String(ctx.senderId || event.senderId || "").trim();
          if (!chatId) {
            return {
              handled: true,
              text: "[export-gate] Telegram chat_id(senderId)를 확인할 수 없어 export를 실행하지 못했습니다.",
            };
          }

          const pythonPath = api.pluginConfig?.pythonPath || DEFAULT_PYTHON;
          const exportScriptPath =
            api.pluginConfig?.exportScriptPath || DEFAULT_EXPORT_SCRIPT;
          const ocAccount = api.pluginConfig?.openclawAccount || "ehcmall";

          const kw = pickKeywords(body);
          const fmt = pickFormat(body);
          const project = pickProject(body);

          const maxPicks = Number(api.pluginConfig?.maxPicks ?? 12) || 12;
          const args = [
            exportScriptPath,
            chatId,
            ...kw,
            "--format",
            fmt,
            "--auto-filter",
            "--max-picks",
            String(maxPicks),
            "--project",
            project,
            "--account",
            ocAccount,
            ...(fmt === "pdf" ? ["--summary", buildAutoSummary(project, kw)] : []),
          ];

          api.logger?.info?.(
            `[ehcmall-export-gate] beforeDispatchMode=auto-export spawn: ${pythonPath} … --auto-filter --max-picks ${maxPicks} (${fmt})`,
          );

          const res = spawnSync(pythonPath, args, {
            encoding: "utf-8",
            maxBuffer: 12 * 1024 * 1024,
            timeout: 300_000,
            env: {
              ...process.env,
              EXPORT_USER_CONTEXT: body.slice(0, 8000),
            },
          });

          const stderr = (res.stderr || "").trim();
          const stdout = (res.stdout || "").trim();

          if (res.status !== 0) {
            const errTail = stderr.slice(-3500) || stdout.slice(-3500) || `exit=${res.status}`;
            return {
              handled: true,
              text: `[DB export 자동 실행 실패]\n\`\`\`\n${errTail}\n\`\`\``,
            };
          }

          return {
            handled: true,
            text: `요청하신 ${fmt.toUpperCase()}를 전송했습니다. (자동 선별·최대 ${maxPicks}개, 추천 이유는 파일 안 표에 있습니다.)`,
          };
        } catch (err) {
          api.logger?.error?.(`[ehcmall-export-gate] ${String(err)}`);
          return {
            handled: true,
            text: `[export-gate 오류] ${String(err)}`,
          };
        }
      },
      { priority: 2000 },
    );
  },
});

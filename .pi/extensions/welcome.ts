/**
 * CHATLabAI welcome header.
 *
 * A project-local pi extension that replaces pi's default verbose startup banner
 * with a friendly CHATLabAI greeting listing what the assistant can do. The
 * greeting text is factored into the exported, pure `welcomeLines()` function so
 * it can be unit-tested without a TUI or theme.
 *
 * Loading: pi auto-discovers `.pi/extensions/*.ts` (via jiti, so TypeScript works
 * without compilation). `quietStartup: true` in .pi/settings.json hides pi's
 * built-in header so only this greeting shows.
 *
 * API reference (mirrors examples/extensions/custom-header.ts):
 *   pi.on("session_start", async (_event, ctx) => { ... })
 *   ctx.ui.setHeader((tui, theme) => ({ render(width): string[], invalidate() {} }))
 *   ctx.ui.setHeader(undefined)   // restore built-in header
 *   theme.fg("accent" | "muted" | "dim", text)
 */

import type { ExtensionAPI, Theme } from "@earendil-works/pi-coding-agent";

/**
 * The raw (uncoloured) greeting lines. Pure and side-effect-free so it can be
 * unit-tested without a TUI/theme. Render() applies theme colours; this owns
 * the CONTENT.
 *
 * Lines are returned with leading spaces preserved; the first/last blank lines
 * give the header breathing room.
 */
export function welcomeLines(): string[] {
  return [
    "",
    "  Hi — I'm CHATLabAI, your Penn Center for Neuroaesthetics research assistant.",
    "  Remember — it's methods, not methodology.",
    "",
    "  Pick a number, or just tell me what you need:",
    "    1. Review a manuscript (21 writing rules)",
    "    2. Track-change edit a Word doc",
    "    3. Check citations & retractions",
    "    4. Find citation gaps (what's missing)",
    "    5. Literature review on a topic",
    "    6. Format for a journal",
    "    7. Power analysis & sample size",
    "    8. Run stats (t-test, ANOVA, mixed)",
    "    9. Figures & brain maps",
    "   10. Organize data / lab calendar",
    "",
    "  (type a number to start, or ask anything)",
    "",
  ];
}

export default function (pi: ExtensionAPI) {
  // Render the custom header on session_start, but only in TUI mode so -p / json
  // / rpc modes are unaffected. session_start fires on fresh launch and on
  // new/resume; showing the greeting each time in TUI is the intended behaviour.
  pi.on("session_start", async (_event, ctx) => {
    if (ctx.mode !== "tui") return;

    ctx.ui.setHeader((_tui, theme) => {
      return {
        render(_width: number): string[] {
          // Apply theme colours: accent for the title line, muted for the
          // secondary/closing line. The numbered menu items stay plain for
          // readability. If a theme colour call were to throw, degrade to the
          // plain lines (never break the TUI).
          try {
            const lines = welcomeLines();
            const title = lines[1];
            const closing = lines[lines.length - 2];
            const out = [...lines];
            out[1] = theme.fg("accent", title);
            out[out.length - 2] = theme.fg("muted", closing);
            return out;
          } catch {
            // Degrade gracefully: plain strings, no colour.
            return welcomeLines();
          }
        },
        invalidate() {},
      };
    });
  });

  // Escape hatch: restore pi's built-in header on demand.
  pi.registerCommand("builtin-header", {
    description: "Restore pi's built-in startup header",
    handler: async (_args, ctx) => {
      ctx.ui.setHeader(undefined);
      ctx.ui.notify("Built-in header restored", "info");
    },
  });
}

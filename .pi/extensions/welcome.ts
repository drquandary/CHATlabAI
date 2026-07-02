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
    "  Hello — remember, it's methods, not methodology.",
    "",
    "  I can help you:",
    "    - Review a manuscript against the lab's 21 writing rules",
    "    - Track-change edit your Word doc (preserving your voice)",
    "    - Check citations and flag retractions",
    "    - Run a neuroaesthetics literature review",
    "    - Format a manuscript for a target journal",
    "    - Power analysis and statistics (R + Python)",
    "    - Make publication figures and brain maps",
    "    - Organize data into BIDS and manage the lab calendar",
    "",
    "  Just tell me what you need, in plain English.   (Ctrl+O for shortcuts)",
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
          // secondary/closing line. The capability lines stay plain for
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

#!/usr/bin/env sh
# chatlab-bootscreen.sh — shared "PARCC is booting" splash for CHATLabAI.
#
# Source this file, then call:
#   chatlab_bootscreen "<headline>" ["<subnote>"]   # clear screen + branded banner
#   chatlab_boot_note  "<line>"                       # one dim status line under it
#
# POSIX sh, safe under `set -eu`. Degrades to plain text when stdout is not a
# TTY, when $NO_COLOR is set, or on a dumb terminal — so it never corrupts CI
# logs or piped output. Purely cosmetic: it must never fail a caller, so every
# helper returns 0.

# True (0) only when it's safe to emit ANSI colour / cursor control.
chatlab__tty() {
  [ -t 1 ] || return 1
  [ -z "${NO_COLOR:-}" ] || return 1
  case "${TERM:-}" in dumb | "") return 1 ;; esac
  return 0
}

# chatlab_bootscreen <headline> [subnote]
# Clears the screen (TTY only) and paints the CHATLabAI / PARCC boot banner
# with the given headline and optional secondary note.
chatlab_bootscreen() {
  _bs_head="${1:-PARCC is booting…}"
  _bs_note="${2:-}"
  if chatlab__tty; then
    _bs_a='\033[38;5;39m'    # accent  (blue)
    _bs_m='\033[38;5;245m'   # muted   (grey)
    _bs_b='\033[1m'          # bold
    _bs_r='\033[0m'          # reset
    printf '\033[2J\033[H'   # clear + home
  else
    _bs_a='' _bs_m='' _bs_b='' _bs_r=''
  fi
  printf '\n'
  printf '   %b══════════════════════════════════════════════════%b\n' "$_bs_m" "$_bs_r"
  printf '    %b%bCHATLabAI%b  %b·  Penn Center for Neuroaesthetics%b\n' "$_bs_b" "$_bs_a" "$_bs_r" "$_bs_m" "$_bs_r"
  printf '    %bPARCC research environment%b\n' "$_bs_m" "$_bs_r"
  printf '   %b══════════════════════════════════════════════════%b\n' "$_bs_m" "$_bs_r"
  printf '\n'
  printf '    %b→ %s%b\n' "$_bs_a" "$_bs_head" "$_bs_r"
  if [ -n "$_bs_note" ]; then
    printf '      %b%s%b\n' "$_bs_m" "$_bs_note" "$_bs_r"
  fi
  printf '\n'
  return 0
}

# chatlab_boot_note <line> — a single dim progress line beneath the banner.
chatlab_boot_note() {
  if chatlab__tty; then
    printf '      \033[38;5;245m%s\033[0m\n' "${1:-}"
  else
    printf '      %s\n' "${1:-}"
  fi
  return 0
}

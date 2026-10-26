# Reporting upstream

Nothing here has been sent. Posting to the kernel list is public and
permanent, under your name, so it's yours to do.

| File | What it is | Ready? |
|---|---|---|
| `02-v11-kbd-rgb-test-report.txt` | Reply to the v11 keyboard LED patch: test results, the firmware's zone-0 blue bug, interleaved writes, the backlight key, a real off | **Yes.** Fill in your name and e-mail, then send |
| `01-hp-wmi-board-8746.txt` | Cover letter for a 4-patch series: profile at EC 0x29, ignore event 0x1B, fan RPM via 0x2D, cool as low-power | **No.** The patches have to be rebased onto pdx86 `for-next`, split, and run through `checkpatch.pl` first (steps at the top of the file) |
| `hp-wmi-8746-on-7.0-plus-v11.diff` | Everything this project changes in `hp-wmi.c`, against Ubuntu 7.0 + v11. Byte-identical to the installed driver | Reference for both |

## Sending 02

It is a reply, so it has to thread under the original patch:

1. Open the v11 message in the list archive (search lore.kernel.org for
   `0Ja9VPr1QTSihXZrbKAgzg@aquinas.su`) and use its **Reply** link, which
   sets `In-Reply-To` for you; or set that header yourself.
2. Plain text only, no HTML, no attachments. Paste the text below the
   `Subject:` line as the body.
3. To and Cc exactly as at the top of the file. Replace
   `<Your Name> <you@example.com>` in `Tested-by:`.

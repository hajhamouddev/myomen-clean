#!/usr/bin/env python3
"""UNTESTED - DO NOT USE. The laptop hard-froze (2026-09-28 ~13:50) while a
build from this script was being test-loaded; the cause is not known. It is
not used by install-8746.sh. Investigate in a VM or with a serial/netconsole
log before loading it on real hardware again.

Apply the board-8746 (HP OMEN 15-dh1xxx) quirks to a stock hp-bioscfg.

    patch-bioscfg-8746.py <in: hp-bioscfg source dir> <out: dir>

Stock hp-bioscfg on 8746 shows only Sure_Start: none of the firmware's 24
string, 1 integer and 77 enumeration settings (Fan Always On, Adaptive Battery
Extender, ...). Two parser assumptions don't hold for this firmware:

 1. Strings are expected hex-encoded ("0x46 0x61 0x6E ..."), as on HP business
    firmware. 8746 returns plain ASCII ("Fan Always On", DSL line 64826), so
    hp_convert_hexstr_to_str() decodes nothing and returns -EFAULT for every
    name. Fix: a string that doesn't start with "0x" is taken as-is.

 2. After reading PREREQUISITES_SIZE prerequisite strings, the package parsers
    don't step over them. 8746 packages carry 3 (" ", " ", " "), so the next
    field read is a prerequisite instead of SECURITY_LEVEL: "Error expected
    type 1 for elem 9, but got type 2 instead". Fix: skip the strings read.

Both edits apply only on board 8746. (The WQBE AE_AML_BUFFER_LIMIT error is a
separate firmware bug in the 2 ordered-list entries, and is left alone.)

Loading reads only. BIOS settings are written only when a current_value file
is written.

Every anchor must match exactly once or nothing is written.
"""
import os
import shutil
import sys

HELPER_ANCHOR = "int hp_convert_hexstr_to_str(const char *input, u32 input_len, char **str, int *len);\n"
HELPER = HELPER_ANCHOR + (
    "\n"
    "/* Board 8746 (OMEN by HP Laptop 15-dh1xxx) - omen-sense local patch. */\n"
    "static inline bool hp_bioscfg_board_is_8746(void)\n"
    "{\n"
    "\tconst char *board_name = dmi_get_system_info(DMI_BOARD_NAME);\n"
    "\n"
    "\treturn board_name && !strcmp(board_name, \"8746\");\n"
    "}\n"
)
H_INC_OLD = "#include <linux/wmi.h>\n"
H_INC_NEW = "#include <linux/wmi.h>\n#include <linux/dmi.h>\n#include <linux/string.h>\n"

HEX_FUNC = "int hp_convert_hexstr_to_str(const char *input, u32 input_len, char **str, int *len)\n{"
HEX_OLD = (
    "\t*len = 0;\n"
    "\t*str = NULL;\n"
    "\n"
    "\tnew_str = kmalloc(input_len, GFP_KERNEL);\n"
)
HEX_NEW = (
    "\t*len = 0;\n"
    "\t*str = NULL;\n"
    "\n"
    "\t/* 8746 firmware returns plain ASCII, not \"0x41 0x42 ...\" */\n"
    "\tif (hp_bioscfg_board_is_8746() && strncasecmp(input, \"0x\", 2)) {\n"
    "\t\t*str = kstrndup(input, input_len, GFP_KERNEL);\n"
    "\t\tif (!*str)\n"
    "\t\t\treturn -ENOMEM;\n"
    "\t\t*len = strlen(*str);\n"
    "\t\treturn *len ? 0 : -EFAULT;\n"
    "\t}\n"
    "\n"
    "\tnew_str = kmalloc(input_len, GFP_KERNEL);\n"
)

PARSERS = ["enum-attributes.c", "string-attributes.c", "int-attributes.c",
           "order-list-attributes.c", "passwdobj-attributes.c"]
CASE = "\t\tcase PREREQUISITES:\n"
CASE_END = "\n\t\t\tbreak;\n"
SKIP = (
    "\n"
    "\t\t\t/* 8746: step over the prerequisite strings just read */\n"
    "\t\t\tif (hp_bioscfg_board_is_8746() && size > 1)\n"
    "\t\t\t\telem += size - 1;"
)


def die(msg):
    sys.exit(f"patch-bioscfg-8746: {msg} - source not as expected, nothing written")


def once(src, needle, what):
    n = src.count(needle)
    if n != 1:
        die(f"{what}: expected 1 match, found {n}")
    return src.index(needle)


def read(d, name):
    return open(os.path.join(d, name), encoding="utf-8").read().replace("\r\n", "\n")


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    src_dir, out_dir = sys.argv[1], sys.argv[2]
    out = {}

    h = read(src_dir, "bioscfg.h")
    if "hp_bioscfg_board_is_8746" in h:
        die("already patched")
    once(h, H_INC_OLD, "bioscfg.h wmi include")
    once(h, HELPER_ANCHOR, "bioscfg.h hexstr prototype")
    out["bioscfg.h"] = h.replace(H_INC_OLD, H_INC_NEW, 1).replace(HELPER_ANCHOR, HELPER, 1)

    # 1. plain-ASCII strings
    c = read(src_dir, "bioscfg.c")
    i_func = once(c, HEX_FUNC, "hp_convert_hexstr_to_str definition")
    if once(c, HEX_OLD, "hexstr allocation") < i_func:
        die("allocation is not inside hp_convert_hexstr_to_str")
    out["bioscfg.c"] = c.replace(HEX_OLD, HEX_NEW, 1)

    # 2. step over prerequisites, in each package parser
    for name in PARSERS:
        s = read(src_dir, name)
        i = once(s, CASE, f"{name} PREREQUISITES case")
        j = s.find(CASE_END, i)
        body = s[i:j]
        if j < 0 or "for (reqs = 0; reqs < size; reqs++)" not in body:
            die(f"{name}: PREREQUISITES case is not the expected loop")
        out[name] = s[:j] + SKIP + s[j:]

    os.makedirs(out_dir, exist_ok=True)
    for name in os.listdir(src_dir):
        if name.endswith((".c", ".h")) and name not in out:
            shutil.copy(os.path.join(src_dir, name), os.path.join(out_dir, name))
    for name, text in out.items():
        open(os.path.join(out_dir, name), "w", encoding="utf-8", newline="\n").write(text)
    print(f"patch-bioscfg-8746: wrote {out_dir} ({len(out)} files patched)")


if __name__ == "__main__":
    main()

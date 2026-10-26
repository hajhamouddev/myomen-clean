#!/usr/bin/env python3
"""Apply the board-8746 (HP OMEN 15-dh1xxx) quirk to a stock hp-wmi.c.

    patch-8746.py <in: hp-wmi.c> <out: hp-wmi.c>

Six edits, each gated on DMI board name "8746" so every other board keeps the
stock behaviour. Evidence for all of them: docs/findings-8746.md.

 1. Thermal profile read-back. Upstream reads EC 0x95 (HPCM on sibling boards).
    On 8746 that byte is inside the battery string ('C' = 0x43), so setup fails
    and no platform_profile is registered. The firmware's GM1A handler stores the
    mode in OCCM = EC 0x29 bits 0-1 (DSL line 62987; EC field map line 68820),
    with values 0/1/2 = the V0 default/performance/cool the kernel already uses.

 2. Fan RPM. Upstream query 0x11 (GM11) returns a hard-coded zero buffer on 8746
    (DSL line 62863). GM2D (query 0x2D) reads the real RPM/100 per fan through
    the EC mailbox with firmware-authored constants and ignores its input
    (DSL line 63329). Read-only: it sends no payload the firmware uses.

 3. WMI event 0x1B. Upstream treats it as the Fn+P key and cycles the profile.
    On 8746 GM1A raises GWEV(0x1B, 5|6) after every mode write, so each cycle
    triggers the next: an endless loop of mode writes (~700/s, seen with ftrace
    on 2026-09-28). The event is ignored on 8746.

 4. Cool is offered as "low-power". power-profiles-daemon has no mapping for
    "cool", so its Power Saver left the firmware mode alone. Same V0 payload.

 5. Keyboard (needs kbd-rgb-v11.patch applied first): start each zone's
    channel values from its real colour, not full white. Otherwise lighting
    one zone while the backlight is off turns the other three white.

 6. Keyboard colour writes (needs kbd-rgb-v11.patch). The firmware's colour
    read (LM02) returns zone 0's blue from Z02B instead of Z01B, so v11's
    read-modify-write of any zone copies zone 1's blue into zone 0 - the right
    side of the keyboard flashes during effects, and keeps a wrong blue after
    another zone changes (proved through ec_sys on 2026-09-28). On 8746 the
    table is written whole from the driver's own record of every zone, the
    payload shape OMEN Gaming Hub sends here (byte 0 = 3, colours from 25),
    with no read; a mutex keeps zone writes from interleaving; and zone 0's
    blue is read from the EC at probe. The backlight key reaches no driver on
    this board, so the backlight is switched on only when a zone goes from
    dark to lit, not on every colour write, or the key cannot stay off; and
    when every zone is at brightness 0 it is switched off for real, with the
    off payload OMEN Gaming Hub sends here (type 0x05, 0x64).

No new write path is added. Profile writes stay the upstream V0 payloads
{0xFF,0|1|2}, all observed from OMEN Gaming Hub on this machine.

Every anchor must match exactly once or nothing is written.
"""
import sys

QUIRK = r'''
/*
 * Board 8746 (OMEN by HP Laptop 15-dh1xxx) quirk - omen-sense local patch.
 *
 * The OMEN thermal-profile byte is not at EC 0x95 on this board: the
 * firmware's GM1A handler keeps it in OCCM, EC offset 0x29 bits 0-1, with the
 * V0 values the driver already uses. EC 0x95 lies inside the battery string,
 * which made profile setup fail and left the board with no platform_profile.
 *
 * Fan speed query 0x11 returns a zero buffer on this board. Query 0x2D reads
 * RPM/100 per fan from the EC; it takes no input the firmware uses.
 */
#define HP_OMEN_8746_EC_THERMAL_PROFILE_OFFSET	0x29
#define HP_OMEN_8746_EC_THERMAL_PROFILE_MASK	0x03
#define HP_OMEN_8746_FAN_LEVEL_GET_QUERY	0x2D

static bool hp_wmi_board_is_8746(void)
{
	const char *board_name = dmi_get_system_info(DMI_BOARD_NAME);

	return board_name && !strcmp(board_name, "8746");
}

static int hp_wmi_get_fan_speed_8746(int fan)
{
	u8 fan_data[128] = {};
	int ret;

	if (fan < 0 || fan > 1)
		return -EINVAL;

	ret = hp_wmi_perform_query(HP_OMEN_8746_FAN_LEVEL_GET_QUERY, HPWMI_GM,
				   &fan_data, sizeof(u8), sizeof(fan_data));
	if (ret != 0)
		return -EINVAL;

	return fan_data[fan] * 100;
}

static int hp_wmi_get_fan_speed_legacy(int fan);

static int hp_wmi_get_fan_speed(int fan)
{
	if (hp_wmi_board_is_8746()) {
		pr_info_once("board 8746 quirk: fan RPM via query 0x2D, profile at EC 0x29\n");
		return hp_wmi_get_fan_speed_8746(fan);
	}

	return hp_wmi_get_fan_speed_legacy(fan);
}

'''

PROFILE_OLD = "\tint ret = ec_read(HP_OMEN_EC_THERMAL_PROFILE_OFFSET, &data);\n"
PROFILE_NEW = (
    "\tint ret;\n"
    "\n"
    "\tif (hp_wmi_board_is_8746()) {\n"
    "\t\tret = ec_read(HP_OMEN_8746_EC_THERMAL_PROFILE_OFFSET, &data);\n"
    "\t\tif (ret)\n"
    "\t\t\treturn ret;\n"
    "\n"
    "\t\treturn data & HP_OMEN_8746_EC_THERMAL_PROFILE_MASK;\n"
    "\t}\n"
    "\n"
    "\tret = ec_read(HP_OMEN_EC_THERMAL_PROFILE_OFFSET, &data);\n"
)

FNP_OLD = (
    "\tcase HPWMI_FN_P_HOTKEY:\n"
    "\t\tplatform_profile_cycle();\n"
    "\t\tbreak;\n"
)
FNP_NEW = (
    "\tcase HPWMI_FN_P_HOTKEY:\n"
    "\t\t/*\n"
    "\t\t * On 8746 event 0x1B is GM1A's echo of every mode write, not a\n"
    "\t\t * key. Cycling here writes the mode again and loops forever.\n"
    "\t\t */\n"
    "\t\tif (!hp_wmi_board_is_8746())\n"
    "\t\t\tplatform_profile_cycle();\n"
    "\t\tbreak;\n"
)

# 4. Report cool as low-power. power-profiles-daemon has no mapping for
#    "cool", so its power-saver did nothing and it misread cool as balanced.
LP_PROBE_OLD = (
    "\tif (is_omen_thermal_profile()) {\n"
    "\t\tset_bit(PLATFORM_PROFILE_COOL, choices);\n"
)
LP_PROBE_NEW = (
    "\tif (hp_wmi_board_is_8746()) {\n"
    "\t\t/* the cool mode, named so power-profiles-daemon maps it */\n"
    "\t\tset_bit(PLATFORM_PROFILE_LOW_POWER, choices);\n"
    "\t} else if (is_omen_thermal_profile()) {\n"
    "\t\tset_bit(PLATFORM_PROFILE_COOL, choices);\n"
)
LP_GET_OLD = (
    "\tcase HP_OMEN_V1_THERMAL_PROFILE_COOL:\n"
    "\t\t*profile = PLATFORM_PROFILE_COOL;\n"
)
LP_GET_NEW = (
    "\tcase HP_OMEN_V1_THERMAL_PROFILE_COOL:\n"
    "\t\t*profile = hp_wmi_board_is_8746() ? PLATFORM_PROFILE_LOW_POWER :\n"
    "\t\t\t\t\t\t   PLATFORM_PROFILE_COOL;\n"
)
LP_SET_OLD = (
    "\tcase PLATFORM_PROFILE_COOL:\n"
    "\t\tif (tp_version == 0)\n"
    "\t\t\ttp = HP_OMEN_V0_THERMAL_PROFILE_COOL;\n"
)
LP_SET_NEW = (
    "\tcase PLATFORM_PROFILE_LOW_POWER:\t/* only offered on board 8746 */\n"
    + LP_SET_OLD
)

# 5. kbd-rgb-v11.patch initialises every zone's per-channel brightness to
#    LED_FULL. Setting one zone while the backlight is off turns the whole
#    backlight on and rewrites the other zones from those values: they go
#    white. Start from the real colour (or 0 when the backlight is off).
KBD_OLD = "\t\t\tmc_subled_info[i].brightness = LED_FULL;\n"
KBD_NEW = (
    "\t\t\tif (hp_wmi_board_is_8746())\n"
    "\t\t\t\tmc_subled_info[i].brightness = led_cdev->brightness ?\n"
    "\t\t\t\t\t\t\t\t color_table[off] : 0;\n"
    "\t\t\telse\n"
    "\t\t\t\tmc_subled_info[i].brightness = LED_FULL;\n"
)

# 6. Keyboard colour writes: see the docstring. Inserted just above v11's
#    hp_kbd_set_brightness, below everything it uses.
KBD_WRITE_ANCHOR = ("static int hp_kbd_set_brightness(struct led_classdev *led_cdev,\n"
                    "\t\t\t\t\tenum led_brightness brightness)\n{\n")
KBD_WRITE_NEW = r"""/*
 * Board 8746: keyboard colour writes - omen-sense local patch.
 *
 * The firmware's colour-table read (LM02) fills byte 0x1B, zone 0's blue, from
 * Z02B instead of Z01B. A read-modify-write of any other zone therefore copies
 * zone 1's blue into zone 0, the right-hand zone. Write the whole table from
 * the driver's own record of every zone instead, with no read first: the
 * payload shape OMEN Gaming Hub sends on this machine, byte 0 = 3, zeros, then
 * twelve colour bytes from offset 25.
 *
 * The backlight key is handled by the firmware alone here; no event reaches
 * the driver. So switch the backlight on only when a zone goes from dark to
 * lit, not on every colour write, or the key cannot keep the keyboard off.
 *
 * And when every zone is at brightness 0, switch the backlight off for real
 * (type 0x05, 0x64 - what OMEN Gaming Hub sends here to turn it off) rather
 * than leaving it lit with a black table. LM05 only sets KBLS; it raises no
 * event.
 */
#define HP_KBD_8746_ZONE0_BLUE_EC	0x0A	/* Z01B */

static DEFINE_MUTEX(hp_kbd_8746_lock);
static enum led_brightness hp_kbd_8746_shown[4];

static int hp_kbd_set_brightness(struct led_classdev *led_cdev,
				 enum led_brightness brightness);

static int hp_kbd_8746_write_table(void)
{
	u8 color_table[128] = { 0x03 };
	struct led_classdev_mc *device;
	int ret;

	for (int zone = 0; zone < ARRAY_SIZE(hp_multicolor_leds.devices); zone++) {
		device = &hp_multicolor_leds.devices[zone];
		for (int i = 0; i < HP_KBD_RGB_COLORS; i++)
			color_table[HP_COLOR_TABLE_PADDING +
				    zone * HP_KBD_RGB_COLORS + i] =
				device->subled_info[i].brightness;
	}

	ret = hp_wmi_perform_query(HPWMI_BACKLIGHT_COLOR_SET_QUERY, HPWMI_BACKLIGHT,
				   color_table, sizeof(color_table),
				   sizeof(color_table));
	if (ret < 0)
		return ret;
	if (ret)
		return -EINVAL;

	return 0;
}

static int hp_kbd_set_brightness_8746(struct led_classdev *led_cdev,
				      enum led_brightness brightness)
{
	struct hp_kbd_led_priv *priv = hp_led_get_priv(led_cdev);
	int ret = 0;

	/* Until every zone is registered there is no full record to write. */
	for (int i = 0; i < ARRAY_SIZE(hp_multicolor_leds.devices); i++)
		if (!hp_multicolor_leds.devices[i].subled_info)
			return hp_kbd_set_brightness(led_cdev, brightness);

	mutex_lock(&hp_kbd_8746_lock);

	if (brightness && !hp_kbd_8746_shown[priv->zone] &&
	    !hp_kbd_backlight_is_on()) {
		u8 data = HPWMI_BACKLIGHT_SET_ON_QUERY;

		ret = hp_wmi_perform_query(HPWMI_BACKLIGHT_BRIGHTNESS_SET_QUERY,
					   HPWMI_BACKLIGHT, &data,
					   sizeof(data), sizeof(data));
		if (ret)
			goto out;
	}

	/*
	 * led_cdev->brightness is left to the LED core, which has already set
	 * it; suspend calls this with 0 without changing it, so resume can put
	 * the saved level back.
	 */
	led_mc_calc_color_components(lcdev_to_mccdev(led_cdev), brightness);

	ret = hp_kbd_8746_write_table();
	if (ret)
		goto out;
	hp_kbd_8746_shown[priv->zone] = brightness;

	if (!brightness) {
		bool all_dark = true;

		for (int i = 0; i < ARRAY_SIZE(hp_kbd_8746_shown); i++)
			all_dark &= !hp_kbd_8746_shown[i];
		if (all_dark) {
			u8 data = HPWMI_BACKLIGHT_SET_OFF_QUERY;

			ret = hp_wmi_perform_query(HPWMI_BACKLIGHT_BRIGHTNESS_SET_QUERY,
						   HPWMI_BACKLIGHT, &data,
						   sizeof(data), sizeof(data));
		}
	}
out:
	mutex_unlock(&hp_kbd_8746_lock);
	return ret;
}

"""
KBD_SETTER_OLD = "\t\tled_cdev->brightness_set_blocking = hp_kbd_set_brightness;\n"
KBD_SETTER_NEW = (
    "\t\tled_cdev->brightness_set_blocking = hp_wmi_board_is_8746() ?\n"
    "\t\t\thp_kbd_set_brightness_8746 : hp_kbd_set_brightness;\n"
)
KBD_SHOWN_OLD = "\t\tpriv->last_brightness = LED_FULL;\n"
KBD_SHOWN_NEW = (
    "\t\tpriv->last_brightness = LED_FULL;\n"
    "\t\thp_kbd_8746_shown[zone] = led_cdev->brightness;\n"
)
KBD_PROBE_OLD = ("\tif (ret)\n\t\treturn ret;\n\n"
                 "\tfor (int zone = 0; zone < num_zones; zone++) {\n")
KBD_PROBE_NEW = (
    "\tif (ret)\n\t\treturn ret;\n\n"
    "\tif (hp_wmi_board_is_8746()) {\n"
    "\t\tu8 blue;\n"
    "\n"
    "\t\t/* LM02 reports zone 0's blue from the wrong field. */\n"
    "\t\tif (!ec_read(HP_KBD_8746_ZONE0_BLUE_EC, &blue))\n"
    "\t\t\tcolor_table[HP_COLOR_TABLE_PADDING + 2] = blue;\n"
    "\t}\n"
    "\n"
    "\tfor (int zone = 0; zone < num_zones; zone++) {\n"
)

# plain string edits, all below the quirk block, applied last
SIMPLE = [
    (FNP_OLD, FNP_NEW, "Fn+P event handler"),
    (LP_PROBE_OLD, LP_PROBE_NEW, "omen choices in profile probe"),
    (LP_GET_OLD, LP_GET_NEW, "omen cool read-back"),
    (LP_SET_OLD, LP_SET_NEW, "omen cool write"),
    (KBD_OLD, KBD_NEW, "kbd-rgb-v11 subled init (apply kbd-rgb-v11.patch first)"),
    (KBD_WRITE_ANCHOR, KBD_WRITE_NEW + KBD_WRITE_ANCHOR, "kbd-rgb-v11 zone setter"),
    (KBD_SETTER_OLD, KBD_SETTER_NEW, "kbd-rgb-v11 setter assignment"),
    (KBD_SHOWN_OLD, KBD_SHOWN_NEW, "kbd-rgb-v11 zone private data init"),
    (KBD_PROBE_OLD, KBD_PROBE_NEW, "kbd-rgb-v11 colour table read at probe"),
]

FAN_DEF = "static int hp_wmi_get_fan_speed(int fan)\n{"
PERFORM_DEF = "static int hp_wmi_perform_query("
PROFILE_DEF = "static int omen_thermal_profile_get(void)\n{"


def die(msg):
    sys.exit(f"patch-8746: {msg} - source not as expected, nothing written")


def once(src, needle, what):
    n = src.count(needle)
    if n != 1:
        die(f"{what}: expected 1 match, found {n}")
    return src.index(needle)


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    src = open(sys.argv[1], encoding="utf-8").read().replace("\r\n", "\n")

    if "hp_wmi_board_is_8746" in src:
        die("already patched")

    i_perf = once(src, PERFORM_DEF, "hp_wmi_perform_query definition")
    i_fan = once(src, FAN_DEF, "hp_wmi_get_fan_speed definition")
    i_prof = once(src, PROFILE_DEF, "omen_thermal_profile_get definition")
    once(src, PROFILE_OLD, "EC 0x95 profile read")
    i_simple = [(once(src, old, what), what) for old, _, what in SIMPLE]

    # the quirk block needs hp_wmi_perform_query above it, and must sit above
    # both functions that use it
    at = min(i_fan, i_prof)
    if i_perf > at:
        die("hp_wmi_perform_query is defined after its users")
    for i, what in i_simple:
        if i < max(i_fan, i_prof):
            die(f"{what} is above the functions the quirk block precedes")

    # 1. profile read-back (inside omen_thermal_profile_get)
    body_start = i_prof
    body_end = src.index("\n}\n", body_start)
    body = src[body_start:body_end]
    if PROFILE_OLD not in body:
        die("EC 0x95 read is not inside omen_thermal_profile_get")
    src = src[:body_start] + body.replace(PROFILE_OLD, PROFILE_NEW) + src[body_end:]

    # 2. rename the stock fan reader, then put the quirk block above both users
    src = src.replace(FAN_DEF, "static int hp_wmi_get_fan_speed_legacy(int fan)\n{", 1)
    at = min(src.index("static int hp_wmi_get_fan_speed_legacy(int fan)\n{"),
             src.index(PROFILE_DEF))
    src = src[:at] + QUIRK.lstrip("\n") + src[at:]

    # 3-6. event 0x1B, cool as low-power, keyboard zone init and writes
    for old, new, what in SIMPLE:
        if src.count(old) != 1:
            die(f"{what}: anchor not unique after earlier edits")
        src = src.replace(old, new, 1)

    open(sys.argv[2], "w", encoding="utf-8", newline="\n").write(src)
    print(f"patch-8746: wrote {sys.argv[2]}")


if __name__ == "__main__":
    main()

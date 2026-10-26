"""Logic tests for omensense with sysfs and PySide6 stubbed out.

    python3 tests/test_logic.py        # no Qt, no driver, no root needed
"""
import os
import sys
import tempfile
import types
from pathlib import Path

LOCAL_GUI = str(Path(__file__).resolve().parent.parent / "gui")
sys.path = [p for p in sys.path if "my proj" not in p and "OmenSense" not in p]
if LOCAL_GUI not in sys.path:
    sys.path.insert(0, LOCAL_GUI)

# --- stub PySide6 so keyboard.py imports without Qt ------------------------
class Anything:
    """Any attribute, any call, any operator: enough for module-level Qt use."""
    def __init__(self, *a, **k): pass
    def __getattr__(self, _name): return Anything()
    def __call__(self, *a, **k): return Anything()
    def __or__(self, _o): return Anything()
    __ror__ = __and__ = __add__ = __radd__ = __truediv__ = __or__
    def __iter__(self): return iter(())
    def __mro_entries__(self, _bases): return (object,)


class QtModule(types.ModuleType):
    def __getattr__(self, _name): return Anything()


qt = types.ModuleType("PySide6")
for name in ("QtCore", "QtGui", "QtWidgets"):
    mod = QtModule(name)
    setattr(qt, name, mod)
    sys.modules[f"PySide6.{name}"] = mod
sys.modules["PySide6"] = qt

from omensense import effects, hw, keyboard, reactive, smart, state  # noqa: E402

failures = []


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


# --- keyboard layout --------------------------------------------------------
for i, row in enumerate(keyboard.MAIN_ROWS):
    width = sum(w for _, w in row)
    check(abs(width - 15) < 1e-9, f"main row {i} is 15 units (got {width})")
for i, row in enumerate(keyboard.NUMPAD_ROWS):
    check(sum(w for _, w in row) == 4, f"numpad row {i} is 4 units")
zones = {z for z, *_ in keyboard.KEYS}
check(zones == set(hw.ZONES), f"every zone has keys: {sorted(zones)}")
wasd = sorted(l for z, l, *_ in keyboard.KEYS if z == "wasd")
check(wasd == ["A", "D", "S", "W"], f"WASD zone is exactly W A S D: {wasd}")

# --- fake machine -----------------------------------------------------------
class Machine:
    def __init__(self):
        self.mode = "balanced"
        self.writes = []
        self.zone = {z: [(255, 0, 0), 255] for z in hw.ZONES}
        self.maxfan = False
        self.key_off = False      # the backlight key has turned the keyboard off

m = Machine()
hw.profile_path = lambda: "/fake/profile"
hw.profile = lambda: m.mode
hw.profile_choices = lambda: ["low-power", "balanced", "performance"]
def _set_profile(name):
    m.writes.append(("profile", name)); m.mode = name
hw.set_profile = _set_profile
hw.zone_colour = lambda z: tuple(m.zone[z][0])
hw.zone_brightness = lambda z: m.zone[z][1]
hw.backlight_off_by_key = lambda: m.key_off
def _set_colour(z, rgb):
    m.writes.append(("colour", z)); m.zone[z][0] = tuple(rgb)
def _set_bright(z, v):
    m.writes.append(("bright", z)); m.zone[z][1] = v
hw.set_zone_colour = _set_colour
hw.set_zone_brightness = _set_bright
hw.max_fan = lambda: m.maxfan
real_set_max_fan = hw.set_max_fan
def _set_max(on):
    m.writes.append(("maxfan", on)); m.maxfan = on
hw.set_max_fan = _set_max

# --- smart mode -------------------------------------------------------------
s = smart.SmartMode(cool_below=55, performance_above=80)
s.start(now=0.0)
t = 0.0
# Hot for 30 s on AC: switches to performance at once (first decision is free).
s.tick(85, True, t)
check(m.mode == "performance", "smart: hot -> performance immediately")
# Temperature wobbling around 78-80 must not flap within the dwell.
before = len(m.writes)
for i in range(1, 300):          # 5 minutes of 1 s ticks
    temp = 78 if i % 2 else 80
    s.tick(temp, True, float(i))
check(len(m.writes) == before, "smart: 78/80 wobble near the limit writes nothing")
# Cools right down: should step to balanced, then only after a dwell to cool.
writes_at = len(m.writes)
for i in range(300, 600):
    s.tick(40, True, float(i))
changes = [w for w in m.writes[writes_at:] if w[0] == "profile"]
check([c[1] for c in changes] == ["balanced", "low-power"],
      f"smart: cooling steps performance->balanced->low-power: {changes}")
# Rate: never more than one profile write per DWELL_S.
times, last = [], None
m2 = Machine(); m.mode = "balanced"
s = smart.SmartMode(); s.start(0.0)
flips = 0
for i in range(0, 3600):
    temp = 90 if (i // 7) % 2 else 40       # violent swing every 7 s
    before = m.mode
    s.tick(temp, True, float(i))
    if m.mode != before:
        times.append(i)
gaps = [b - a for a, b in zip(times, times[1:])]
check(all(g >= smart.DWELL_S for g in gaps),
      f"smart: {len(times)} changes in an hour of violent swings, min gap {min(gaps) if gaps else '-'} s")
# On battery never chooses performance.
m.mode = "balanced"; s = smart.SmartMode(); s.start(0.0)
s.tick(95, False, 0.0)
check(m.mode != "performance", "smart: never performance on battery")
# External change is followed, not fought.
m.mode = "balanced"; s = smart.SmartMode(); s.start(0.0)
m.mode = "low-power"; n = len(m.writes)
s.tick(70, True, 10.0)
check(len(m.writes) == n and s.current == "low-power", "smart: follows a mode set elsewhere")
# Stop restores the mode from before start.
m.mode = "low-power"; s = smart.SmartMode(); s.start(0.0)
s.tick(90, True, 0.0)
s.stop()
check(m.mode == "low-power", "smart: stop restores the previous mode")

# --- reactive lighting ------------------------------------------------------
import random
random.seed(1)
r = reactive.Reactive()
r.start("temperature")
m.writes.clear()
temp = 60.0
worst = 0
for centre in range(45, 91):          # every possible resting temperature
    r.stop(); r.start("temperature"); m.writes.clear()
    for i in range(600):              # 10 minutes, 1 Hz, ±1 °C noise
        r.tick({"cpu_temp": round(centre + random.uniform(-1.0, 1.0))}, now=float(i))
    worst = max(worst, sum(1 for w in m.writes if w[0] == "colour"))
# The first colour is always written; at most one settling change after it.
check(worst <= 2 * len(hw.ZONES),
      f"reactive: ±1 °C noise, worst resting temperature -> {worst} zone writes in 10 min")
r.stop(); r.start("temperature"); m.writes.clear()
for i, temp in enumerate(range(45, 91)):   # a real climb, 1 °C per 10 s
    for k in range(10):
        r.tick({"cpu_temp": temp}, now=float(i * 10 + k))
steps_seen = sum(1 for w in m.writes if w[0] == "colour") // len(hw.ZONES)
check(steps_seen >= 8, f"reactive: a 45->90 °C climb still moves the colour ({steps_seen} changes)")
saved = {z: tuple(m.zone[z][0]) for z in hw.ZONES}
r.stop()
check(all(m.zone[z][0] == (255, 0, 0) for z in hw.ZONES),
      "reactive: stop puts the user's colours back")

# --- layouts and animations -------------------------------------------------
check(all(len(l["zones"]) == len(hw.ZONES) and
          all(len(c) == 3 and all(0 <= v <= 255 for v in c) for c in l["zones"])
          for l in effects.LAYOUTS.values()),
      "layouts: every layout has one valid colour per zone")
for z in hw.ZONES:
    m.zone[z] = [(9, 9, 9), 0]
m.writes.clear()
effects.apply_layout("rainbow")
check(effects.matching_layout({z: hw.zone_colour(z) for z in hw.ZONES}) == "rainbow"
      and all(m.zone[z][1] == hw.LED_MAX for z in hw.ZONES),
      "layouts: rainbow is written, recognised, and lights dark zones")
check(effects.apply_layout("nope") != [], "layouts: an unknown name is refused")

user = {z: [(1, 2, 3), 128] for z in hw.ZONES}
for mode in effects.ANIMATIONS:
    for z in hw.ZONES:
        m.zone[z] = list(user[z])
    a = effects.Animator(seed=1)
    a.start(mode, now=0.0)
    m.writes.clear()
    for i in range(6000):                # 10 minutes of 100 ms calls
        a.tick(now=i / 10)
    frames = 600 / effects.FRAME_S
    colour_writes = sum(1 for w in m.writes if w[0] == "colour")
    check(colour_writes <= frames * len(hw.ZONES),
          f"{mode}: 100 ms ticks still write at most 5 frames/s "
          f"({colour_writes} zone writes in 10 min, cap {int(frames * len(hw.ZONES))})")
    per_zone = {z: sum(1 for w in m.writes if w == ("colour", z)) for z in hw.ZONES}
    check(min(per_zone.values()) > 0, f"{mode}: every zone moves ({per_zone})")
    a.stop()
    check(all(m.zone[z] == [(1, 2, 3), 128] for z in hw.ZONES),
          f"{mode}: stop puts the user's colours and brightness back")
# A frame that repeats the last colour writes nothing.
a = effects.Animator(); a.start("cycle", now=0.0); a.tick(now=0.0)
m.writes.clear()
a.tick(now=effects.PERIOD_S)                # one full turn later: same colours
check(not any(w[0] == "colour" for w in m.writes),
      "cycle: unchanged zones are not rewritten")
import colorsys
import statistics


def _hue(rgb):
    return colorsys.rgb_to_hsv(*[v / 255 for v in rgb])[0] * 360


def _real_frames(seconds, seed=0):
    """Frame times as the window makes them: 50 ms timer, jitter, FRAME_S floor."""
    jitter = random.Random(seed)
    t, last, out = 0.0, float("-inf"), []
    while t < seconds:
        t += 0.05 + jitter.uniform(0, 0.012)
        if t - last >= effects.FRAME_S:
            out.append(t); last = t
    return out


frames_real = _real_frames(600)
check(max(b - a for a, b in zip(frames_real, frames_real[1:])) <= effects.FRAME_GAP_MAX_S,
      "timing: real frame gaps stay within FRAME_GAP_MAX_S")

# Zone positions must be the drawn keyboard's, or the wave is drawn wrong.
width = max(k[2] + k[4] for k in keyboard.KEYS)
for z in hw.ZONES:
    keys = [k for k in keyboard.KEYS if k[0] == z]
    centre = sum((k[2] + k[4] / 2) * k[4] for k in keys) / sum(k[4] for k in keys) / width
    check(abs(centre - effects.ZONE_X[z]) < 0.02,
          f"geometry: {z} centre {centre:.2f} matches ZONE_X {effects.ZONE_X[z]}")

by_x = sorted(hw.ZONES, key=effects.ZONE_X.get)
for t in (0.0, 5.0, 10.0):
    hues = [_hue(effects.frame("wave", t)[z]) for z in by_x]
    rises = all(((b - a) % 360) < 180 for a, b in zip(hues, hues[1:]))
    check(rises, f"wave: hue rises left to right, in rainbow order, at t={t} ({[round(h) for h in hues]})")
w0 = effects.frame("wave", 0.0)
check(abs(_hue(w0["left"]) - _hue(w0["wasd"])) < 20,
      "wave: WASD, inside the Left zone, matches its neighbours")
later = effects.frame("wave", 1.0)
check(((_hue(w0["center"]) - _hue(later["center"])) % 360) < 180,
      "wave: the pattern moves right (each zone takes on its left neighbour's hue)")
wsteps = [max(max(abs(x - y) for x, y in zip(effects.frame("wave", t1)[z],
                                                effects.frame("wave", t0)[z])) for z in hw.ZONES)
          for t0, t1 in zip(frames_real, frames_real[1:400])]
check(statistics.median(wsteps) <= 24, f"wave: smooth, median step {statistics.median(wsteps)}/255 a frame")
check(len(set(effects.frame("cycle", 7.0).values())) == 1, "cycle: all zones share one colour")

mine = {z: (0, 200, 100) for z in hw.ZONES}
low = effects.frame("breathing", 0.0, mine)["left"]
high = effects.frame("breathing", effects.BREATH_S / 2, mine)["left"]
check(high == (0, 200, 100) and max(low) < 20,
      f"breathing: your colour fades from dim {low} to full {high}")

red = {z: (255, 0, 0) for z in hw.ZONES}
whole = 0
beats = int(frames_real[-1] // effects.HEARTBEAT_S)
for i in range(beats):
    seen = {effects.frame("heartbeat", f, red)["left"][0] for f in frames_real
            if i * effects.HEARTBEAT_S <= f < (i + 1) * effects.HEARTBEAT_S}
    whole += {255, 76, 204} <= seen
check(whole == beats, f"heartbeat: lub, gap and dub all shown on real frame timing ({whole}/{beats})")

lit = [[z for z, c in effects.frame("chase", t * effects.CHASE_STEP_S, mine).items()
        if c == (0, 200, 100)] for t in range(4)]
check(lit == [[z] for z in hw.ZONES], f"chase: one zone lit at a time ({lit})")

fire = [effects.frame("fire", f, seed=3) for f in frames_real[:2000]]
check(all(c[2] == 0 and c[0] >= c[1] for fr in fire for c in fr.values())
      and len({c for fr in fire for c in fr.values()}) > 50,
      "fire: always red-orange, always moving")
fsteps = [abs(b[z][0] - a[z][0]) for a, b in zip(fire, fire[1:]) for z in hw.ZONES]
check(statistics.median(fsteps) <= 30, f"fire: flickers, not strobes (median step {statistics.median(fsteps)})")

aur = [c for f in frames_real for c in effects.frame("aurora", f, seed=7).values()]
ah = [_hue(c) for c in aur]
green = sum(h < 150 for h in ah) / len(ah)
violet = sum(h >= 250 for h in ah) / len(ah)
check(green >= 0.45 and violet >= 0.05,
      f"aurora: mostly green ({green:.0%}) with violet surges ({violet:.0%})")
check(all(90 <= h <= 320 for h in ah), "aurora: never red, orange or yellow")
check(min(max(c) for c in aur) >= 60, f"aurora: never goes dark (dimmest {min(max(c) for c in aur)}/255)")
check(effects.frame("aurora", 12.3, seed=5) == effects.frame("aurora", 12.3, seed=5),
      "aurora: frames are repeatable for a given seed")

# The backlight key: any colour write turns the backlight back on, so nothing
# that writes by itself may write while the key has it off.
for z in hw.ZONES:
    m.zone[z] = [(10, 20, 30), 255]
b = effects.Animator(seed=1); b.start("wave", now=0.0); b.tick(now=0.0)
m.key_off = True
m.writes.clear()
for i in range(1, 50):
    b.tick(now=i * 0.25)
check(not m.writes and b.paused, "backlight key off: the animation writes nothing")
m.key_off = False
b.tick(now=13.0)
check(sum(1 for w in m.writes if w[0] == "colour") == len(hw.ZONES) and not b.paused,
      "backlight key on again: the animation resumes on its next frame")
b.stop()
rr = reactive.Reactive(); rr.start("temperature"); m.key_off = True; m.writes.clear()
for i in range(0, 120, 6):
    rr.tick({"cpu_temp": 45 + i % 40}, now=float(i))
check(not m.writes, "backlight key off: temperature lighting writes nothing")
m.key_off = False
rr.tick({"cpu_temp": 70}, now=200.0)
check(any(w[0] == "colour" for w in m.writes), "backlight key on again: temperature lighting resumes")
rr.stop()
a.stop()

# --- CPU load and RAM ---------------------------------------------------------
from omensense import monitoring  # noqa: E402
with tempfile.TemporaryDirectory() as tmp:
    stat = os.path.join(tmp, "stat")
    def _stat(user, idle):     # user nice system idle iowait irq softirq
        with open(stat, "w") as f:
            f.write(f"cpu  {user} 0 0 {idle} 0 0 0\ncpu0 1 2 3 4 5\n")
    meter = monitoring.CpuLoad(stat)
    _stat(100, 900)
    check(meter.percent() is None, "cpu load: nothing to compare on the first call")
    _stat(175, 925)            # +75 busy, +25 idle
    check(meter.percent() == 75, "cpu load: 75 % from the /proc/stat difference")
    check(meter.percent() is None, "cpu load: no time passed, no number")
    mem = os.path.join(tmp, "meminfo")
    with open(mem, "w") as f:
        f.write("MemTotal:       16000000 kB\nMemFree: 1 kB\nMemAvailable:    4000000 kB\n")
    ram = monitoring.memory(mem)
    check(ram.get("percent") == 75 and abs(ram["total_gb"] - 15.26) < 0.01,
          f"ram: used = total - available ({ram})")
    check(monitoring.memory(os.path.join(tmp, "missing")) == {}, "ram: missing file gives nothing")

# --- HP's DTS tuning: decoding and presets (synthetic data, no HP files) ------
import struct  # noqa: E402
from omensense import audio, dts  # noqa: E402


def _q(value, integer_bits):
    return round(value * 2 ** (32 - integer_bits))


# Two biquads: one in Q2.30, one in Q1.31, as the real tables mix them.
# Invented values, not HP's, chosen so each section has unity DC gain.
first = (0.95, -1.9, 0.955, 1.9, -0.905)
second = (0.9, 0.0, 0.6, 0.0, -0.5)
blob = struct.pack("<ii", 4, 511)
blob += struct.pack("<i5i", 2, *(_q(v, 2) for v in first))
blob += struct.pack("<i5i", 1, *(_q(v, 1) for v in second))
blob += struct.pack("<ii", 1, 0x7FFFFFFF) + bytes(64)
decoded = dts.parse_gpeq(blob)
check(len(decoded) == 2, f"dts: header gives the biquad count ({len(decoded)})")
check(all(abs(x - y) < 1e-6 for x, y in zip(decoded[0], (*first[:3], -first[3], -first[4])))
      and all(abs(x - y) < 1e-6 for x, y in zip(decoded[1], (*second[:3], -second[3], -second[4]))),
      "dts: Q2.30 and Q1.31 records decode, denominator flipped to PipeWire's sign")
check(all(abs((b0 + b1 + b2) / (1 + a1 + a2) - 1) < 2e-3 for b0, b1, b2, a1, a2 in decoded),
      "dts: decoded EQ sections have unity DC gain")

xml = """<srs_configuration><operating_mode>
<control name="APO4-Operating Mode">APO4-Voice</control>
<control name="APO4-Speaker Type">APO4-Internal Stereo</control>
<control name="MFX:Eagle-HPF Enable">1</control>
<control name="MFX:Eagle-HPF Freq">180</control>
<control name="MFX:Eagle-HPF Order">4</control>
</operating_mode><operating_mode>
<control name="APO4-Operating Mode">APO4-Voice</control>
<control name="APO4-Speaker Type">APO4-Headphone</control>
</operating_mode></srs_configuration>"""
modes = dts.parse_modes(xml)
check(list(modes) == ["APO4-Voice"] and modes["APO4-Voice"]["MFX:Eagle-HPF Freq"] == "180",
      "dts: only the internal-speaker modes are read")

tuning = {"modes": {"voice": {"hpf": [{"freq": 180.0, "order": 4}],
                              "biquads": {"48000": decoded, "44100": decoded[:1]}}}}
presets = audio.hp_presets(tuning)
bands = presets["voice"]["bands"]
check([b[0] for b in bands[:2]] == ["bq_highpass", "bq_highpass"]
      and [b[2] for b in bands[:2]] == [0.5412, 1.3066],
      "audio: a 4th-order high-pass is two Butterworth sections")
check(len(bands) == 4 and sorted(bands[2]["raw"]) == [44100, 48000] and list(bands[3]["raw"]) == [48000],
      "audio: HP's biquads carry one coefficient set per sample rate")
config = audio._config(bands, "alsa_output.test_Speaker__sink")
check("label = bq_raw" in config and "rate = 44100" in config and "a0 = 1.0" in config,
      "audio: bq_raw nodes are written with per-rate coefficients")
check('filter.smart.target = { node.name = "alsa_output.test_Speaker__sink" }' in config,
      "audio: the speaker target is match rules, which WirePlumber needs")
check('filter.smart.target' not in audio._config(bands), "audio: no target, no target line")
bass = audio._bankstown({"level": 52.0, "speaker_size": 160.0})
check(bass["amt"] == 1.45 and bass["ceil"] == 160.0 and audio._bankstown({"level": 0}) is None
      and audio._bankstown({"level": 10.0, "speaker_size": 400.0})["ceil"] == 250.0,
      "audio: bass stand-in scales HP's bass level, ceiling within the plugin's range")
stereo = audio._config(bands, None, bass, True)
check('plugin = "https://chadmed.au/bankstown"' in stereo and 'plugin = "http://lsp-plug.in/plugins/lv2/limiter_stereo"' in stereo
      and 'inputs  = [ "bass:in_l" "bass:in_r" ]' in stereo and 'outputs = [ "limit:out_l" "limit:out_r" ]' in stereo,
      "audio: stereo chain runs bass first and the limiter last")
check('output = "bass:out_l" input = "l0:In"' in stereo and 'output = "r3:Out" input = "limit:in_r"' in stereo
      and stereo.count("label = bq_raw") == 4,
      "audio: each channel gets its own copy of the EQ between them")
check('"th" = 0.891' in stereo and '"alr" = 0' in stereo and '"boost" = 0' in stereo,
      "audio: limiter at -1 dBFS, no level regulation, no gain boost")
check(audio.hp_presets(None) == {} and audio.ALIASES["shooter"] == "game",
      "audio: no tuning, no HP presets; old game presets map to Game")

# --- headphones -----------------------------------------------------------------
xf = audio._crossfeed_graph()
check('label = bs2b' in xf and '"Feeding level (dB)" = 6.0' in xf
      and '"Lowpass filter cut frequency (Hz)" = 700.0' in xf,
      "headphones: crossfeed is bs2b at its Chu Moy setting (700 Hz, 6 dB)")
vs = audio._virtual_speakers_graph(True)
check('"Azimuth" = 30.0' in vs and '"Azimuth" = 330.0' in vs and vs.count("label = spatializer") == 2,
      "headphones: virtual speakers sit at +-30 degrees")
check(all(link in vs for link in ('output = "spk_l:Out L" input = "ear_l:In 1"',
                                   'output = "spk_r:Out L" input = "ear_l:In 2"',
                                   'output = "spk_l:Out R" input = "ear_r:In 1"',
                                   'output = "spk_r:Out R" input = "ear_r:In 2"'))
      and 'outputs = [ "limit:out_l" "limit:out_r" ]' in vs,
      "headphones: each ear hears both speakers, then the limiter")
hp_conf = audio._config([], "alsa_output.x__Headphones__sink", slot="headphones", graph=xf)
check('node.name = "omen_sense_hp"' in hp_conf and 'filter.smart.name = "omen_sense_hp"' in hp_conf
      and 'node.name = "alsa_output.x__Headphones__sink"' in hp_conf,
      "headphones: own filter name, targeted at the headphone sink")
check(audio.SLOTS["speakers"]["sink"] != audio.SLOTS["headphones"]["sink"]
      and audio.SLOTS["speakers"]["prefix"] != audio.SLOTS["headphones"]["prefix"],
      "headphones: the two slots never share a filter or a config prefix")
real_hs = audio.headphone_sink
audio.headphone_sink = lambda: None
engine = audio.PresetEngine.__new__(audio.PresetEngine)
engine.slot, engine.presets = "headphones", audio.HEADPHONE_PRESETS
import io  # noqa: E402
buffer = io.StringIO()
real_exists = audio.os.path.exists
audio.os.path.exists = lambda path: True
refused = engine._write_config("crossfeed", buffer)
audio.os.path.exists = real_exists
audio.headphone_sink = real_hs
check(refused and buffer.getvalue() == "",
      "headphones: with no headphone output found, nothing runs untargeted")

# --- max fan gate -----------------------------------------------------------
hw.set_max_fan = real_set_max_fan
hw.hwmon_path = lambda: "/fake/hwmon"
wrote = []
hw._write = lambda path, value: wrote.append((path, value))
hw.MAX_FAN_OBSERVED = False
msg = hw.set_max_fan(True)
check(msg is not None and not wrote, "hw: max fan ON refused while unobserved")
hw.MAX_FAN_OBSERVED = True
wrote.clear()
check(hw.set_max_fan(True) is None and wrote and wrote[-1][1] == "0",
      "hw: max fan ON writes pwm1_enable=0 once observed")
hw.MAX_FAN_OBSERVED = False    # the profile-gate test below checks the closed gate
hw.set_max_fan(False)
check(wrote and wrote[-1][1] == "2", "hw: max fan OFF writes pwm1_enable=2")

# --- state: remember / restore lighting, profile apply gate ----------------
hw.set_max_fan = _set_max
with tempfile.TemporaryDirectory() as tmp:
    os.environ["XDG_CONFIG_HOME"] = tmp
    for z in hw.ZONES:
        m.zone[z] = [(10, 20, 30), 200]
    check(state.remember_lighting() is None, "state: remember_lighting saves")
    for z in hw.ZONES:
        m.zone[z] = [(255, 255, 255), 255]      # firmware reset at boot
    problems = state.apply_lighting(state.last_lighting())
    check(not problems and all(m.zone[z] == [(10, 20, 30), 200] for z in hw.ZONES),
          "state: last colours restored after a 'boot'")
    m.writes.clear(); m.maxfan = False
    state.audio.PresetEngine = lambda: types.SimpleNamespace(current=None, apply=lambda p: None, stop=lambda: None)
    state.apply({"power": "performance", "max_fan": True, "zones": {}})
    check(("maxfan", True) not in m.writes, "state: a profile cannot smuggle in max fan ON")
    check(m.mode == "performance", "state: profile applies the mode")
    check(state.remember("Gaming", {"power": "balanced"}) is None and state.names() == ["Gaming"],
          "state: profiles save and list")
    check(state.set_startup("Gaming") is None and state.startup() == "Gaming",
          "state: startup profile")

    # Keyboard off / on: off is brightness 0 everywhere (the driver turns that
    # into HP's backlight-off), and on brings back exactly what was lit.
    m.zone = {"left": [(1, 2, 3), 255], "wasd": [(4, 5, 6), 128],
              "center": [(7, 8, 9), 255], "right": [(10, 11, 12), 64]}
    lit = {z: list(v) for z, v in m.zone.items()}
    check(not state.keyboard_off() and state.keyboard_is_off()
          and all(m.zone[z][0] == lit[z][0] for z in hw.ZONES),
          "keyboard off: every zone dark, colours kept")
    check(all(v["brightness"] == 0 for v in state.last_lighting().values()),
          "keyboard off: remembered, so it stays off after a login")
    state.keyboard_off()                       # twice must not lose the levels
    check(not state.keyboard_on() and m.zone == lit,
          f"keyboard on: the same colours and levels come back ({m.zone})")
    check(not state.keyboard_is_off(), "keyboard on: no longer reported off")
    check(state.settings()["effect"] is None and state.set_setting("effect", "aurora") is None
          and state.settings()["effect"] == "aurora", "effect: the running effect is remembered")

print()
print("ALL PASS" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)

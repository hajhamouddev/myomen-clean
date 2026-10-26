"""Audio presets, as PipeWire filter-chains - one for the speakers, one for
headphones.

Speakers: on Windows this laptop runs DTS:X Ultra with HP's own tuning. With
that tuning imported (dts.py) the speaker presets are HP's EQ, coefficient for
coefficient, plus stand-ins for two DTS effects; without it they are plain
parametric EQ. Headphones: HP's tuning has no headphone EQ (dts.py says why),
so the headphone options are the two established Linux ones - bs2b crossfeed,
and virtual speakers through PipeWire's SOFA spatializer.

Mechanics: each preset is a standalone `pipewire -c` process publishing one
filter-chain node as a **smart filter** targeted at one output: the speakers
or the headphones. Nothing is written to the user's PipeWire configuration, so
turning a preset off - or the application exiting, or crashing - leaves the
audio graph exactly as it was. WirePlumber only puts a targeted filter in
front of that exact output and skips it while the output is gone, so the
speaker EQ never reaches headphones and the reverse.
"""

from __future__ import annotations

import glob
import json
import os
import re
import time
import shutil
import subprocess
import tempfile

#: One filter per output. Config files carry the prefix so a running filter
#: can be found again by a later process.
SLOTS = {
    "speakers": {"sink": "omen_sense_eq", "prefix": "omen-eq-",
                 "description": "MyOmen"},
    "headphones": {"sink": "omen_sense_hp", "prefix": "omen-hp-",
                   "description": "MyOmen headphones"},
}
SINK_NAME = SLOTS["speakers"]["sink"]
CONFIG_PREFIX = os.path.join(tempfile.gettempdir(), SLOTS["speakers"]["prefix"])

#: Six bands per preset: (label, centre Hz, Q, gain dB). The first is a low
#: shelf and the last a high shelf; the rest are peaking. Gains stay within
#: +/-6 dB - past that a preset stops being a voicing and starts being damage,
#: and there is no makeup gain stage here to compensate.
#: Used when HP's tuning has not been imported: plain parametric EQ written
#: from what each name is for.
GENERIC_PRESETS: dict[str, dict] = {
    "shooter": {
        "title": "Shooter",
        "detail": "Lifts footstep and reload detail, keeps bass from masking it",
        "bands": [("bq_lowshelf", 90, 0.8, -2.0), ("bq_peaking", 300, 1.0, -2.5),
                  ("bq_peaking", 1200, 1.0, 1.5), ("bq_peaking", 3500, 1.2, 4.5),
                  ("bq_peaking", 6000, 1.4, 3.0), ("bq_highshelf", 10000, 0.8, 1.5)],
    },
    "rpg": {
        "title": "RPG",
        "detail": "Wide and warm, with dialogue kept forward",
        "bands": [("bq_lowshelf", 110, 0.8, 3.0), ("bq_peaking", 400, 1.0, -1.0),
                  ("bq_peaking", 1500, 1.0, 0.5), ("bq_peaking", 3000, 1.2, 2.0),
                  ("bq_peaking", 7000, 1.2, 1.0), ("bq_highshelf", 11000, 0.8, 2.0)],
    },
    "strategy": {
        "title": "Strategy",
        "detail": "Separates many simultaneous cues; restrained low end",
        "bands": [("bq_lowshelf", 100, 0.8, -1.5), ("bq_peaking", 500, 1.2, -1.5),
                  ("bq_peaking", 1800, 1.0, 2.5), ("bq_peaking", 4000, 1.2, 2.5),
                  ("bq_peaking", 8000, 1.2, 1.5), ("bq_highshelf", 12000, 0.8, 1.0)],
    },
    "movies": {
        "title": "Movies",
        "detail": "Cinematic low end with dialogue lifted clear of it",
        "bands": [("bq_lowshelf", 120, 0.7, 4.5), ("bq_peaking", 350, 1.0, -2.0),
                  ("bq_peaking", 2500, 1.1, 2.5), ("bq_peaking", 4500, 1.2, 1.5),
                  ("bq_peaking", 9000, 1.0, 1.0), ("bq_highshelf", 12000, 0.8, 2.5)],
    },
    "music": {
        "title": "Music",
        "detail": "Gentle lift at both ends, mids left alone",
        "bands": [("bq_lowshelf", 100, 0.8, 3.5), ("bq_peaking", 250, 1.0, -1.0),
                  ("bq_peaking", 1000, 1.0, 0.0), ("bq_peaking", 3000, 1.0, 0.5),
                  ("bq_peaking", 8000, 1.0, 1.5), ("bq_highshelf", 11000, 0.8, 3.0)],
    },
    "voice": {
        "title": "Voice",
        "detail": "Speech intelligibility: rumble out, presence in",
        "bands": [("bq_lowshelf", 120, 0.7, -6.0), ("bq_peaking", 300, 1.0, -2.0),
                  ("bq_peaking", 1600, 1.1, 3.5), ("bq_peaking", 3200, 1.2, 4.0),
                  ("bq_peaking", 6000, 1.2, 1.0), ("bq_highshelf", 10000, 0.8, -1.0)],
    },
}


# ------------------------------------------------------ HP's own tuning

#: Butterworth sections for an Nth-order high-pass, as DTS's "HPF Order" means.
_BUTTERWORTH_Q = {1: [0.7071], 2: [0.7071], 4: [0.5412, 1.3066]}

_HP_TEXT = {
    "hp": ("HP Windows Tuning",
           "HP factory calibrated speaker response matching Windows DTS:X driver tuning with -1 dB distortion limiter"),
    "music": ("Music", "HP's Music EQ for these speakers, 100 Hz high-pass"),
    "movies": ("Movie", "HP's Movie EQ, a little deeper in the mids than Music"),
    "voice": ("Voice", "HP's Voice EQ: bass rolled off at 180 Hz, speech kept clear"),
    "game": ("Game", "HP's game high-pass. The three DTS game modes differ only "
             "in effects that are not reproduced, so they are one preset here"),
}

#: Presets saved before HP's tuning was imported, mapped to their HP twin.
ALIASES = {"shooter": "game", "rpg": "game", "strategy": "game"}


def hp_presets(tuning: dict | None) -> dict[str, dict]:
    """Presets built from HP's DTS tuning (dts.py), or {} without it."""
    modes = (tuning or {}).get("modes") or {}
    presets = {}
    for key, (title, detail) in _HP_TEXT.items():
        mode = modes.get(key)
        if mode is None:
            continue
        bands = [("bq_highpass", h["freq"], q, 0.0)
                 for h in mode.get("hpf", [])
                 for q in _BUTTERWORTH_Q.get(h["order"], [0.7071] * (h["order"] // 2))]
        by_rate = {int(rate): biquads for rate, biquads in mode.get("biquads", {}).items()}
        for index in range(max((len(b) for b in by_rate.values()), default=0)):
            bands.append({"raw": {rate: biquads[index] for rate, biquads in by_rate.items()
                                  if index < len(biquads)}})
        presets[key] = {"title": title, "detail": detail, "bands": bands,
                        "speakers_only": True, "limit": True,
                        "bass": _bankstown(mode.get("bass"))}
    return presets


def _bankstown(bass: dict | None) -> dict | None:
    """Stand-in settings for DTS TruBass HD-X, from HP's own bass settings.

    Scaled around Asahi Linux's tuning for MacBook speakers (amount 1.2-1.45,
    harmonics 1.05-1.35 / 1.3-2.25): HP's highest bass level here (52, Music
    and Movie) maps to Asahi's 1.45, Voice's 10 to almost none. The ceiling -
    the bass the speakers cannot play, which becomes harmonics - is HP's
    "speaker size", within the plugin's 250 Hz limit.
    """
    if not bass or bass.get("level", 0) <= 0:
        return None
    return {"amt": round(1.45 * bass["level"] / 52, 3), "sat_second": 1.35,
            "sat_third": 2.25, "blend": 1.0, "floor": 20.0,
            "ceil": min(250.0, max(100.0, bass.get("speaker_size") or 200.0)),
            "final_hp": 60.0}


def _load_presets() -> tuple[dict[str, dict], bool]:
    from . import dts
    hp = hp_presets(dts.load())
    return (hp, True) if hp else (GENERIC_PRESETS, False)


#: What the Audio page and `omen-sense audio` offer.
PRESETS, HP_TUNING = _load_presets()


def speaker_sink() -> str | None:
    """node.name of the laptop speakers' sink, so HP's speaker EQ never reaches
    headphones or anything else plugged in."""
    try:
        dump = json.loads(subprocess.run(["pw-dump"], capture_output=True,
                                         text=True, timeout=3, check=True).stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    for obj in dump:
        props = (obj.get("info") or {}).get("props") or {}
        name = props.get("node.name", "")
        if (props.get("media.class") == "Audio/Sink" and "Speaker" in name
                and name.startswith("alsa_output.")):
            return name
    return None


def available() -> bool:
    """Whether a filter-chain preset can be run at all."""
    return bool(shutil.which("pipewire") and shutil.which("pactl"))


def _node(index: int, band) -> str:
    if isinstance(band, dict):
        # HP's own biquad, one set of coefficients per sample rate; PipeWire
        # picks the rate closest to the graph's.
        rates = " ".join(
            f"{{ rate = {rate} b0 = {c[0]:.12f} b1 = {c[1]:.12f} b2 = {c[2]:.12f} "
            f"a0 = 1.0 a1 = {c[3]:.12f} a2 = {c[4]:.12f} }}"
            for rate, c in sorted(band["raw"].items()))
        return (f"{{ type = builtin name = b{index} label = bq_raw "
                f"config = {{ coefficients = [ {rates} ] }} }}")
    label, freq, q, gain = band
    return (f'{{ type = builtin name = b{index} label = {label} '
            f'control = {{ "Freq" = {float(freq)} "Q" = {q} "Gain" = {gain} }} }}')


#: Where LV2 bundles are installed (Debian/Ubuntu put them in /usr/lib/lv2).
LV2_DIRS = ("/usr/lib/lv2", "/usr/lib/x86_64-linux-gnu/lv2", "/usr/local/lib/lv2",
            os.path.expanduser("~/.lv2"))
BANKSTOWN = "https://chadmed.au/bankstown"
LIMITER = "http://lsp-plug.in/plugins/lv2/limiter_stereo"


def lv2_installed(bundle: str) -> bool:
    return any(os.path.isdir(os.path.join(d, bundle)) for d in LV2_DIRS)


def _controls(values: dict) -> str:
    return " ".join(f'"{k}" = {v}' for k, v in values.items())


def _stereo_graph(bands, bass: dict | None, limit: bool) -> str:
    """Bass stand-in, then the EQ per channel, then a safety limiter.

    The order Asahi Linux uses for small laptop speakers: synthesise bass
    first, correct the speaker after, and protect last.
    """
    nodes, links = [], []
    heads = {"l": None, "r": None}              # port feeding the next stage
    inputs = {}
    if bass:
        nodes.append(f'{{ type = lv2 name = bass plugin = "{BANKSTOWN}" '
                     f'control = {{ {_controls(bass)} }} }}')
        inputs = {"l": "bass:in_l", "r": "bass:in_r"}
        heads = {"l": "bass:out_l", "r": "bass:out_r"}
    for side in ("l", "r"):
        for index, band in enumerate(bands):
            nodes.append(_node(index, band).replace(f"name = b{index} ",
                                                    f"name = {side}{index} ", 1))
            port_in = f"{side}{index}:In"
            if heads[side]:
                links.append(f'{{ output = "{heads[side]}" input = "{port_in}" }}')
            else:
                inputs[side] = port_in
            heads[side] = f"{side}{index}:Out"
    outputs = heads
    if limit:
        # -1 dBFS brickwall, no automatic level regulation (that is what
        # pumps) and no gain boost: it only ever catches peaks.
        nodes.append(f'{{ type = lv2 name = limit plugin = "{LIMITER}" control = {{ '
                     '"th" = 0.891 "alr" = 0 "boost" = 0 "lk" = 5.0 "mode" = 0 } }')
        for side in ("l", "r"):
            if heads[side]:
                links.append(f'{{ output = "{heads[side]}" input = "limit:in_{side}" }}')
            else:
                inputs[side] = f"limit:in_{side}"
        outputs = {"l": "limit:out_l", "r": "limit:out_r"}
    return ("nodes = [\n      " + "\n      ".join(nodes) + "\n    ]\n"
            "    links = [\n      " + "\n      ".join(links) + "\n    ]\n"
            f'    inputs  = [ "{inputs["l"]}" "{inputs["r"]}" ]\n'
            f'    outputs = [ "{outputs["l"]}" "{outputs["r"]}" ]')


def _graph(bands, bass: dict | None = None, limit: bool = False) -> str:
    if bass or limit:
        return _stereo_graph(bands, bass, limit)
    nodes, links = [], []
    for index, band in enumerate(bands):
        nodes.append(_node(index, band))
        if index:
            links.append(f'{{ output = "b{index - 1}:Out" input = "b{index}:In" }}')
    return ("nodes = [\n      " + "\n      ".join(nodes) + "\n    ]\n"
            "    links = [\n      " + "\n      ".join(links) + "\n    ]")


def _config(bands, target: str | None = None, bass: dict | None = None,
            limit: bool = False, slot: str = "speakers",
            graph: str | None = None) -> str:
    sink, description = SLOTS[slot]["sink"], SLOTS[slot]["description"]
    # WirePlumber reads the target as match rules, an object of properties
    # the sink must have; a bare string is ignored and the filter never links.
    target_line = (f'\n                         filter.smart.target = {{ node.name = "{target}" }}'
                   if target else "")
    return f"""
context.properties = {{ log.level = 0 }}
context.spa-libs  = {{ audio.convert.* = audioconvert/libspa-audioconvert }}
context.modules = [
  {{ name = libpipewire-module-rt   flags = [ ifexists nofail ] }}
  {{ name = libpipewire-module-protocol-native }}
  {{ name = libpipewire-module-client-node }}
  {{ name = libpipewire-module-adapter }}
  {{ name = libpipewire-module-filter-chain
    args = {{
      node.description = "{description}"
      media.name       = "{description}"
      filter.graph = {{
    {graph or _graph(bands, bass, limit)}
      }}
      capture.props  = {{ node.name = "{sink}" media.class = Audio/Sink
                         filter.smart = true
                         filter.smart.name = "{sink}"{target_line}
                         audio.channels = 2 audio.position = [ FL FR ] }}
      playback.props = {{ node.name = "{sink}_out" node.passive = true
                         audio.channels = 2 audio.position = [ FL FR ] }}
    }}
  }}
]
"""


# ----------------------------------------------------------- headphones

BS2B = "/usr/lib/x86_64-linux-gnu/ladspa/bs2b.so"
HRTF = "/usr/share/libmysofa/default.sofa"      # MIT KEMAR, from libmysofa


def _crossfeed_graph() -> str:
    # bs2b's "Chu Moy" preset, the most used of its three: 700 Hz, 6 dB.
    return (f'nodes = [ {{ type = ladspa name = xf plugin = "{BS2B}" label = bs2b '
            'control = { "Lowpass filter cut frequency (Hz)" = 700.0 '
            '"Feeding level (dB)" = 6.0 } } ]\n'
            '    inputs  = [ "xf:Input left" "xf:Input right" ]\n'
            '    outputs = [ "xf:Output left" "xf:Output right" ]')


def _virtual_speakers_graph(limit: bool) -> str:
    """Two virtual speakers at +-30 degrees, the standard stereo triangle.

    Each channel goes through the spatializer at its speaker's position, and
    each ear hears both speakers - that is what gives headphones a front.
    """
    nodes = [
        f'{{ type = sofa label = spatializer name = spk_l config = {{ filename = "{HRTF}" }} '
        'control = { "Azimuth" = 30.0 "Elevation" = 0.0 "Radius" = 1.0 } }',
        f'{{ type = sofa label = spatializer name = spk_r config = {{ filename = "{HRTF}" }} '
        'control = { "Azimuth" = 330.0 "Elevation" = 0.0 "Radius" = 1.0 } }',
        # 0.8 per speaker: measured, it brings the result to within 0.2 dB of
        # crossfeed's level, so switching between the two does not jump.
        '{ type = builtin label = mixer name = ear_l control = { "Gain 1" = 0.8 "Gain 2" = 0.8 } }',
        '{ type = builtin label = mixer name = ear_r control = { "Gain 1" = 0.8 "Gain 2" = 0.8 } }',
    ]
    links = ['{ output = "spk_l:Out L" input = "ear_l:In 1" }',
             '{ output = "spk_r:Out L" input = "ear_l:In 2" }',
             '{ output = "spk_l:Out R" input = "ear_r:In 1" }',
             '{ output = "spk_r:Out R" input = "ear_r:In 2" }']
    outputs = ('"ear_l:Out" "ear_r:Out"')
    if limit:
        nodes.append(f'{{ type = lv2 name = limit plugin = "{LIMITER}" control = {{ '
                     '"th" = 0.891 "alr" = 0 "boost" = 0 "lk" = 5.0 "mode" = 0 } }')
        links += ['{ output = "ear_l:Out" input = "limit:in_l" }',
                  '{ output = "ear_r:Out" input = "limit:in_r" }']
        outputs = '"limit:out_l" "limit:out_r"'
    return ("nodes = [\n      " + "\n      ".join(nodes) + "\n    ]\n"
            "    links = [\n      " + "\n      ".join(links) + "\n    ]\n"
            '    inputs  = [ "spk_l:In" "spk_r:In" ]\n'
            f"    outputs = [ {outputs} ]")


HEADPHONE_PRESETS: dict[str, dict] = {
    "crossfeed": {
        "title": "Crossfeed", "needs": BS2B,
        "detail": "Blends a little of each side into the other (bs2b, Chu Moy), "
                  "so music stops sitting inside your head",
    },
    "speakers": {
        "title": "Virtual speakers", "needs": HRTF,
        "detail": "Two speakers in front of you at 30 degrees, from the MIT KEMAR "
                  "dummy-head measurements. A generic head, so it suits some ears "
                  "more than others",
    },
}


def headphone_sink() -> str | None:
    """node.name of the headphone jack's sink, plugged in or not.

    With headphones in, the card switches profile and the sink exists under
    its own name. Without them it does not exist yet, so its name is derived
    from the speaker sink's: the same card and UCM naming, HiFi__<device>__sink.
    """
    try:
        dump = json.loads(subprocess.run(["pw-dump"], capture_output=True,
                                         text=True, timeout=3, check=True).stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    speaker = None
    for obj in dump:
        props = (obj.get("info") or {}).get("props") or {}
        name = props.get("node.name", "")
        if props.get("media.class") != "Audio/Sink" or not name.startswith("alsa_output."):
            continue
        if "__Headphones__" in name:
            return name
        if "__Speaker__" in name:
            speaker = name
    return speaker.replace("__Speaker__", "__Headphones__") if speaker else None


class PresetEngine:
    """Runs at most one preset, as a smart filter on the current output.

    A preset outlives the process that started it, exactly like the power mode
    and the lighting do. That is what makes `omen-sense audio voice` from a
    login script meaningful, and it is the consistent rule: closing a window
    does not undo the settings made in it. Nothing has to be put back either -
    the default sink is never touched, so a leftover filter is inert until
    something turns it off.
    """

    def __init__(self, slot: str = "speakers"):
        self.slot = slot
        self.sink = SLOTS[slot]["sink"]
        self.prefix = os.path.join(tempfile.gettempdir(), SLOTS[slot]["prefix"])
        self.presets = PRESETS if slot == "speakers" else HEADPHONE_PRESETS
        self.current: str | None = None
        self._process: subprocess.Popen | None = None
        self._config_path: str | None = None
        self.discover()

    # ------------------------------------------------------------- helpers

    def _node_exists(self) -> bool:
        try:
            listing = subprocess.run(["pactl", "list", "sinks", "short"],
                                     capture_output=True, text=True, timeout=2,
                                     check=True).stdout
        except (subprocess.SubprocessError, OSError):
            return False
        return any(line.split("\t")[1:2] == [self.sink] for line in listing.splitlines())

    def _running_preset(self) -> tuple[int, str] | None:
        """Find this slot's already-running filter process, and its preset.

        The preset name is recovered from the config file the process was
        started with, so a window opening later shows what is actually running
        rather than "Off" over an audible filter.
        """
        try:
            listing = subprocess.run(
                ["ps", "-eo", "pid,args"], capture_output=True, text=True,
                timeout=2, check=True).stdout
        except (subprocess.SubprocessError, OSError):
            return None
        for line in listing.splitlines():
            if self.prefix not in line or "pipewire" not in line:
                continue
            parts = line.split()
            path = next((p for p in parts if self.prefix in p), None)
            if not path or not os.path.exists(path):
                continue
            try:
                marker = open(path).read()
            except OSError:
                continue
            for name in self.presets:
                if f"preset.name = {name}\n" in marker:
                    try:
                        return int(parts[0]), name
                    except ValueError:
                        return None
        return None

    def discover(self):
        """Adopt a preset left running by an earlier process."""
        found = self._running_preset()
        if found and self._node_exists():
            self._pid, self.current = found
        else:
            self._pid, self.current = None, None

    def in_effect(self) -> bool:
        """Whether the running preset's filter is still there."""
        return bool(self.current) and self._node_exists()

    # --------------------------------------------------------------- state

    def stop(self) -> str | None:
        """Remove the filter. The audio graph returns to how it was."""
        try:
            listing = subprocess.run(
                ["ps", "-eo", "pid,args"], capture_output=True, text=True,
                timeout=2).stdout
            for line in listing.splitlines():
                if "pipewire" in line and self.prefix in line:
                    parts = line.split()
                    try:
                        p = int(parts[0])
                        os.kill(p, 15)
                    except (ValueError, ProcessLookupError, PermissionError, OSError):
                        pass
        except Exception:
            pass

        pid = self._process.pid if self._process else getattr(self, "_pid", None)
        if pid:
            try:
                os.killpg(os.getpgid(pid), 15)
            except (ProcessLookupError, PermissionError, OSError):
                if self._process:
                    self._process.terminate()
            if self._process:
                try:
                    self._process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self._process.kill()
        self._process = None
        self._pid = None

        # A config left by a process we adopted rather than started.
        for stale in glob.glob(f"{self.prefix}*.conf"):
            try:
                os.unlink(stale)
            except OSError:
                pass

        if self._config_path and os.path.exists(self._config_path):
            os.unlink(self._config_path)
        self._config_path = None
        self.current = None
        return None

    def _write_config(self, preset: str, handle) -> str | None:
        chosen = self.presets[preset]
        if self.slot == "headphones":
            if not os.path.exists(chosen["needs"]):
                return (f"{chosen['title']} needs {chosen['needs']}, which is not "
                        "installed (packages bs2b-ladspa and libmysofa1).")
            target = headphone_sink()
            if not target:
                # Never run untargeted: it would land on the speakers.
                return "Could not find the headphone output, so nothing was changed."
            limit = lv2_installed("lsp-plugins.lv2")
            graph = (_crossfeed_graph() if preset == "crossfeed"
                     else _virtual_speakers_graph(limit))
            handle.write(_config([], target, slot="headphones", graph=graph))
            return None
        target = speaker_sink() if chosen.get("speakers_only") else None
        # The stand-ins need their plugins; without them the EQ still runs.
        bass = chosen.get("bass") if lv2_installed("bankstown.lv2") else None
        limit = chosen.get("limit", False) and lv2_installed("lsp-plugins.lv2")
        handle.write(_config(chosen["bands"], target, bass, limit))
        return None

    def apply(self, preset: str) -> str | None:
        """Start `preset`. Returns None on success, else a message to show."""
        if self.slot == "speakers" and HP_TUNING:
            preset = ALIASES.get(preset, preset)
        if preset not in self.presets:
            return f"No such preset: {preset}"
        if not available():
            return "PipeWire tools are not installed, so presets cannot run."

        self.stop()

        handle, path = tempfile.mkstemp(prefix=os.path.basename(self.prefix),
                                        suffix=".conf")
        with os.fdopen(handle, "w") as config:
            # The name is written as a comment so a later process can read back
            # which preset is running, not merely that one is.
            config.write(f"# preset.name = {preset}\n")
            error = self._write_config(preset, config)
        if error:
            os.unlink(path)
            return error
        self._config_path = path

        try:
            self._process = subprocess.Popen(
                ["pipewire", "-c", path],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True)
        except OSError as error:
            os.unlink(path)
            self._config_path = None
            return f"Could not start the preset: {error}"

        # The node takes a moment to register with the session manager.
        for _ in range(25):
            if self._node_exists():
                self.current = preset
                return None
            time.sleep(0.1)

        self.stop()
        return "The preset did not load; audio is unchanged."


def output_sinks() -> list[dict]:
    """List available audio output sinks with node.name and user-friendly description."""
    sinks = []
    try:
        dump = json.loads(subprocess.run(["pw-dump"], capture_output=True,
                                         text=True, timeout=3, check=True).stdout)
        default_sink = None
        try:
            info = subprocess.run(["pactl", "info"], capture_output=True, text=True, timeout=2).stdout
            for line in info.splitlines():
                if line.startswith("Default Sink:"):
                    default_sink = line.split(":", 1)[1].strip()
        except Exception:
            pass

        for obj in dump:
            props = (obj.get("info") or {}).get("props") or {}
            media_class = props.get("media.class", "")
            if media_class == "Audio/Sink":
                name = props.get("node.name", "")
                if not name or name.startswith("omen_sense_"):
                    continue
                desc = props.get("node.description") or props.get("device.description") or name
                sinks.append({
                    "name": name,
                    "description": desc,
                    "is_default": (name == default_sink),
                })
    except Exception:
        pass
    return sinks


def set_default_sink(sink_name: str) -> str | None:
    """Set the default PipeWire output sink."""
    try:
        res = subprocess.run(["pactl", "set-default-sink", sink_name],
                             capture_output=True, text=True, timeout=3)
        if res.returncode != 0:
            return res.stderr.strip() or "Failed to set default sink"
        return None
    except Exception as e:
        return str(e)


def latency_status() -> dict:
    """Read active PipeWire latency, quantum, and sample rate."""
    status = {"rate": 48000, "quantum": 1024, "latency_ms": 21.3, "version": "1.6.2", "active": True}
    try:
        out = subprocess.run(["pw-metadata", "-n", "settings"], capture_output=True, text=True, timeout=2).stdout
        for line in out.splitlines():
            if "clock.rate" in line and "value:" in line:
                m = re.search(r"value:'(\d+)'", line)
                if m:
                    status["rate"] = int(m.group(1))
            elif "clock.quantum" in line and "value:" in line:
                m = re.search(r"value:'(\d+)'", line)
                if m:
                    status["quantum"] = int(m.group(1))
        if status["rate"] > 0:
            status["latency_ms"] = round((status["quantum"] / status["rate"]) * 1000.0, 1)
    except Exception:
        pass
    try:
        v_out = subprocess.run(["pipewire", "--version"], capture_output=True, text=True, timeout=2).stdout
        for line in v_out.splitlines():
            if "pipewire" in line.lower() or "version" in line.lower():
                parts = line.split()
                if len(parts) >= 2:
                    status["version"] = parts[-1]
                break
    except Exception:
        pass
    return status


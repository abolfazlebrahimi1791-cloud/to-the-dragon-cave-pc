#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""To the Dragon Cave - speech output backends.

Windows : accessible_output2 (NVDA/JAWS/SAPI) -> pyttsx3 -> dummy
Linux   : Orca over D-Bus (org.gnome.Orca.Service) via DASBUS
          (python3-dbus fallback) -> accessible_output2 -> pyttsx3 -> dummy

The Linux backend mirrors the Rust nvda2speechd-style Orca backend (zbus
sample):
    service    org.gnome.Orca.Service
    path       /org/gnome/Orca/Service
    interface  org.gnome.Orca.Service
    method     PresentMessage(s: text) -> bool
      - speak text   : PresentMessage(text)
      - cancel speech: PresentMessage("")
    Braille messages are intentionally ignored (as in the Rust backend).
"""

import time
import threading

class _OrcaDBus:
    """Speak through the running Orca screen reader via D-Bus.

    Mirrors the Rust nvda2speechd-style Orca backend (zbus sample):
        service    org.gnome.Orca.Service
        path       /org/gnome/Orca/Service
        interface  org.gnome.Orca.Service
        method     PresentMessage(s: text) -> bool
          - speak text   : PresentMessage(text)
          - cancel speech: PresentMessage("")
        Braille messages are intentionally ignored.

    Primary implementation uses dasbus (the sample code below), with a
    python3-dbus fallback for systems that ship only python3-dbus."""
    SERVICE = "org.gnome.Orca.Service"
    PATH = "/org/gnome/Orca/Service"

    def __init__(self):
        self._proxy = None      # dasbus proxy (primary)
        self._obj = None        # python3-dbus object (fallback)
        self._iface = self.SERVICE
        # --- primary: dasbus (sample style) ---
        try:
            from dasbus.connection import SessionMessageBus
            proxy = SessionMessageBus().get_proxy(self.SERVICE, self.PATH)
            proxy.PresentMessage("")     # probe = cancel, like the Rust backend
            self._proxy = proxy
            return
        except Exception:
            self._proxy = None
        # --- fallback: python3-dbus ---
        try:
            import dbus
            bus = dbus.SessionBus()
            obj = bus.get_object(self.SERVICE, self.PATH)
            obj.PresentMessage("", dbus_interface=self._iface)
            self._obj = obj
        except Exception:
            self._obj = None

    def ok(self):
        return self._proxy is not None or self._obj is not None

    def say(self, text, interrupt=True):
        try:
            if self._proxy is not None:
                self._proxy.PresentMessage(text)
            elif self._obj is not None:
                self._obj.PresentMessage(text, dbus_interface=self._iface)
        except Exception:
            pass

class _DummySpeaker:
    def braille(self, *a, **k): pass
    def output(self, *a, **k): pass
    def speak(self, text, *a, **k):
        try:
            print("[SPEECH]", text)
        except Exception:
            pass

class Speaker:
    def __init__(self):
        self.speaker = None
        self.engine = None
        self.orca = None
        self.lock = threading.Lock()
        import platform
        if platform.system() != "Windows":
            try:
                o = _OrcaDBus()
                if o.ok():
                    self.orca = o
            except Exception:
                self.orca = None
        if self.orca is None:
            try:
                from accessible_output2.outputs.auto import Auto
                self.speaker = Auto()
                self._force_english_ao2()
            except Exception:
                self.speaker = None
        if self.orca is None and self.speaker is None:
            try:
                import pyttsx3
                self.engine = pyttsx3.init()
                self._force_english_pyttsx3()
                self.engine.startLoop(False)
                self._tts_thread = threading.Thread(target=self._tts_loop, daemon=True)
                self._tts_thread.start()
            except Exception:
                self.engine = None
        if self.orca is None and self.speaker is None and self.engine is None:
            self.speaker = _DummySpeaker()
        self._last_text = None
        self._last_time = 0.0

    def _force_english_ao2(self):
        """Best-effort: if accessible_output2 uses SAPI, select an English voice.
        Fully guarded - if anything differs, the default voice is kept."""
        try:
            spk = self.speaker
            out = None
            if hasattr(spk, "get_first_available_output"):
                out = spk.get_first_available_output()
            if out is None:
                outs = getattr(spk, "outputs", None)
                if outs:
                    try:
                        vals = list(outs.values())
                    except Exception:
                        vals = list(outs)
                    out = vals[0] if vals else None
            if out is None:
                return
            name = (type(out).__name__ or "").lower()
            mod = (type(out).__module__ or "").lower()
            if "sapi" not in name and "sapi" not in mod:
                return  # NVDA/JAWS read the text with the user's screen reader anyway
            voices = None
            for m in ("list_voices", "voices"):
                if hasattr(out, m):
                    try:
                        voices = getattr(out, m)()
                        break
                    except Exception:
                        voices = None
            if not voices:
                return
            pairs = list(voices.items()) if isinstance(voices, dict) \
                else [(None, v) for v in voices]
            for vid, desc in pairs:
                d = str(desc).lower()
                if "english" in d or d.startswith("en-us") or d.startswith("en-gb") \
                        or "microsoft david" in d or "microsoft zira" in d:
                    try:
                        out.voice = vid if vid is not None else desc
                    except Exception:
                        pass
                    return
        except Exception:
            pass

    def _force_english_pyttsx3(self):
        try:
            eng = self.engine
            for v in eng.getProperty("voices"):
                nm = (getattr(v, "name", "") or "").lower()
                vid = str(getattr(v, "id", "") or "").lower()
                if "english" in nm or "en_us" in vid or "en-us" in vid or "en_gb" in vid:
                    eng.setProperty("voice", v.id)
                    return
        except Exception:
            pass

    def _tts_loop(self):
        while True:
            try:
                self.engine.iterate()
            except Exception:
                pass
            time.sleep(0.05)

    def say(self, text, interrupt=False):
        if not text:
            return
        now = time.time()
        if text == self._last_text and now - self._last_time < 0.1:
            return
        self._last_text = text
        self._last_time = now
        try:
            if self.engine is not None:
                with self.lock:
                    try:
                        self.engine.stop()
                    except Exception:
                        pass
                    self.engine.say(text)
                    try:
                        self.engine.iterate()
                    except Exception:
                        pass
            elif self.orca is not None:
                self.orca.say(text, interrupt=interrupt)
            else:
                self.speaker.output(text, interrupt=interrupt)
        except Exception:
            pass

SPEECH = Speaker()

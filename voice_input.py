import os

import streamlit.components.v1 as components

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "voice_component")
_component = components.declare_component("voice_loop", path=_DIR)


def voice_bar(speak=None, ack=None, tick=0, key="voice_bar"):
    """
    speak: {"id": str, "audio": base64 wav, "final": bool} or None
    ack:   id of the last event Python has taken in (lets the bar resume listening)
    tick:  changes when new messages appear (the bar scrolls the page down)
    Returns the latest event from the bar:
      {"event": "audio", "id", "b64"} or {"event": "text", "id", "text"}
    """
    return _component(speak=speak, ack=ack, tick=tick, key=key, default=None)
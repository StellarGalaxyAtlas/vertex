"""Vertex for StreamController: Sonar's volumes and devices, and Moments'
clips, on a Stream Deck.

The keys talk to the running Vertex through its control socket (see
`vertex_client`). One connection follows Vertex's state for every key, so a
change made in Vertex's window, by a shortcut or by another key shows up on
the deck at once.
"""

from __future__ import annotations

from src.backend.DeckManagement.InputIdentifier import Input
from src.backend.PluginManager.ActionHolder import ActionHolder
from src.backend.PluginManager.ActionInputSupport import ActionInputSupport
from src.backend.PluginManager.PluginBase import PluginBase

from .actions.keys import NextMic, NextOutput, SaveClip, ShowVertex, Volume
from .vertex_client import Vertex

KEY_ONLY = {Input.Key: ActionInputSupport.SUPPORTED,
            Input.Dial: ActionInputSupport.UNSUPPORTED,
            Input.Touchscreen: ActionInputSupport.UNSUPPORTED}
KEY_OR_DIAL = {Input.Key: ActionInputSupport.SUPPORTED,
               Input.Dial: ActionInputSupport.SUPPORTED,
               Input.Touchscreen: ActionInputSupport.UNSUPPORTED}


class VertexPlugin(PluginBase):
    def __init__(self):
        super().__init__()
        self.vertex = Vertex()
        self.vertex.start()

        for action, suffix, name, support in (
            (Volume, "Volume", "Volume", KEY_OR_DIAL),
            (NextOutput, "NextOutput", "Next output device", KEY_ONLY),
            (NextMic, "NextMic", "Next microphone", KEY_ONLY),
            (SaveClip, "SaveClip", "Save clip", KEY_ONLY),
            (ShowVertex, "Show", "Show Vertex", KEY_ONLY),
        ):
            self.add_action_holder(ActionHolder(plugin_base=self, action_base=action,
                                                action_id_suffix=suffix, action_name=name,
                                                action_support=support))

        self.register(plugin_name="Vertex",
                      github_repo="https://github.com/StellarGalaxyAtlas/vertex",
                      plugin_version="0.1.0", app_version="1.5.0-beta.16")

    def on_uninstall(self) -> None:
        self.vertex.stop()
        super().on_uninstall()

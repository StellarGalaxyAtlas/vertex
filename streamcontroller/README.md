# Vertex for StreamController

Keys for a Stream Deck that control the running Vertex: Sonar's volumes and
devices, and Moments' replay buffer and clips.

| Key | Shows | When pressed |
| --- | --- | --- |
| Sonar Information | a channel's volume (Game, Chat, Media or Mic), or "Muted" | nothing |
| Sonar Volume | the step (+5%, -5%) and the channel's volume | turns the channel up or down by the step (both set in the key's settings). On a dial: turn for up or down, press to mute |
| Sonar Channel Toggle | whether a channel is muted | mutes or unmutes it |
| Sonar Next Microphone | the mic in use | the next one in the device manager's list, for now |
| Sonar Next Output Device | the output in use | the next one in the device manager's list, for now |
| Sonar Toggle Microphone | Mic 1, Mic 2, or "No mic" when neither is in use | the other one, for now |
| Sonar Toggle Output Device | Output 1, Output 2, or "No output" | the other one, for now |
| Replay Buffer Toggle | On, Off, Starting or Failed | starts or stops it |
| Replay Save Clip | the length it saves, or "Replay off" | saves a clip; the key flashes green when it lands |
| Show Vertex | | brings Vertex's window to the front |

"For now" means what it means in Vertex: until a device is plugged in. The
device manager's order stays as it is. The two-device keys list the devices
Sonar knows in their settings; pick the first and the second there.

## Pictures

The keys that change state (Sonar Toggle Microphone, Sonar Toggle Output
Device, Sonar Channel Toggle and Replay Buffer Toggle) take a picture for
each state in their settings, such as "Mic 1 picture" and "Mic 2 picture",
and switch to it as the state changes. Leave the key's own image in
StreamController empty: StreamController keeps an image set there and
doesn't let the plugin change it.

## Install

Clone Vertex and link this folder into StreamController's plugins:

```fish
git clone https://github.com/StellarGalaxyAtlas/vertex.git ~/vertex-plugin
mkdir -p ~/.var/app/com.core447.StreamController/data/plugins
ln -s ~/vertex-plugin/streamcontroller ~/.var/app/com.core447.StreamController/data/plugins/com_stellargalaxyatlas_Vertex
```

Restart StreamController; the keys are under "Vertex".

## The Flatpak

The StreamController Flatpak can't see the folder where Vertex listens
(`$XDG_RUNTIME_DIR/vertex`). Give it that folder with Flatseal:

1. Open Flatseal and pick StreamController in the list on the left.
2. Scroll to **Filesystem**. Under **Other files**, click the add button and
   type `xdg-run/vertex`.
3. Close Flatseal and restart StreamController.

Or, in a terminal: `flatpak override --user --filesystem=xdg-run/vertex com.core447.StreamController`

Flatpak only hands over a folder that exists when StreamController starts,
and Vertex makes it the first time it runs after you log in. If
StreamController starts first, or without this permission, the plugin
reaches Vertex through `flatpak-spawn --host` instead, which needs nothing
set up but starts a small helper on each key press.

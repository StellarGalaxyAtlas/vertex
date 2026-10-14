# Vertex for StreamController

Keys for a Stream Deck that control the running Vertex: Sonar's volumes and
devices, and Moments' replay buffer and clips.

| Key | Shows | When pressed |
| --- | --- | --- |
| Volume | a channel's volume (Game, Chat, Media or Mic) | nothing, or mutes it (a setting). On a dial: turn for volume, press to mute |
| Mute | whether a channel is muted | mutes or unmutes it |
| Next output device | the output in use | the next one in the device manager's list, for now |
| Next microphone | the mic in use | the next one in the device manager's list, for now |
| Switch between two microphones | Mic 1, Mic 2, or "No mic" when neither is in use | the other one, for now |
| Switch between two outputs | Output 1, Output 2, or "No output" | the other one, for now |
| Replay buffer on or off | On, Off, Starting or Failed | starts or stops it |
| Save clip | the length it saves, or "Replay off" | saves a clip; the key flashes green when it lands |
| Show Vertex | | brings Vertex's window to the front |

"For now" means what it means in Vertex: until a device is plugged in. The
device manager's order stays as it is. The two-device keys list the devices
Sonar knows in their settings; pick the first and the second there.

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

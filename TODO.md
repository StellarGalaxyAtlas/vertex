# To-Do

One item at a time, top to bottom unless we decide otherwise. New requests
and bugs get the next free number: 68.

---

## Open

**66.**
**Record on Windows with OBS**
OBS Studio is the recorder on Windows, driven over obs-websocket (v5).
Vertex sets up the replay buffer from Settings › Recording (monitor, fps,
quality, buffer length, clip folder), starts and stops it, saves clips and
picks them up into the library like GSR's. Each track (Game, Chat, Mic)
records a device the user picks: they bring their own virtual devices,
whatever made them; Vertex makes none. OBS is not bundled: Vertex finds it
and says where to get it.

**67.**
**Hotkeys in Settings**
Vertex registers its own global hotkeys on Windows (save clip, save the last
30 seconds, start and stop the replay buffer, show Vertex), set with a key
picker in Settings › Shortcuts, in place of binding commands to keys.

## Decided

- No Sonar, and nothing about it in the UI. Stream Deck left out for now.
- This stays a separate repository from `vertex`.

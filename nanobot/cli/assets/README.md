# Dock artwork

`dock-icon.png` is a deterministic composition of the existing MIT-licensed nanobot cat from `webui/public/brand/nanobot_icon_512.png` (SHA-256 `d4cf9edb3c30b9e43d02fcd9974c87a8046afbf1b13903c68100ab510bd2cd41`). The cat is uniformly scaled without redrawing or recoloring. The user-approved design uses a 1024-pixel canvas, an 824-pixel rounded white tile at (100, 100), and a 656-pixel cat at (184, 168). Its optical center is 16 pixels below the tile center; shadows are separate from the original art.

The packaged helper loads this PNG through AppKit. It needs neither a generated application executable nor an icon compiler at installation or launch. Keep artwork changes independent of the WebUI brand asset and of gateway lifecycle policy.

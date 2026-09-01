# Right-click tool

The tool turns a file or highlighted text into a DensePack picture
from the shell, with no window and no app open. The picture costs
fewer tokens than the text it holds, so it pastes into any AI chat in
the text's place.

## Install

| System | Install |
| --- | --- |
| Windows | Run `install-densepack.bat`. It installs Python, Pillow and AutoHotkey if they are missing, adds the shell menu entry and starts the hotkeys |
| Linux | Run `sh install-densepack.sh`. It checks Python and Pillow and writes the Open With entry under your home folder |
| macOS | Open `DensePack it.workflow`. macOS asks once, then the Finder right-click menu carries DensePack it |

## Use

| Action | Result |
| --- | --- |
| Right-click a file, DensePack it | Writes the file's picture as a PNG beside it |
| `Ctrl + Shift + D` | Replaces the highlighted text with its picture, Windows |
| `Ctrl + Shift + C` | Copies the picture and leaves the text, Windows |
| Linux Open With sizes | The menu offers one entry per type size: 8 px for Fable 5, 10 px for Opus 5, 12 px for Sonnet 5 |

## The files

| File | Job |
| --- | --- |
| densepack.py | The packing engine. Text in, PNG out, smaller type for a stronger reader |
| install-densepack.bat, install-densepack.ps1 | The Windows install: the downloads, the registry entry and the hotkeys |
| uninstall-densepack.bat | Removes the Windows registry entry and the hotkeys |
| DensePack.ahk | The two hotkeys |
| densepack-clip.ps1 | Puts the picture on the Windows clipboard |
| reading_card.py | Draws the reading card that teaches a model the color code |
| install-densepack.sh, densepack-file.sh, densepack.desktop | The Linux install, the shell packer and the Open With entry |
| DensePack it.workflow | The macOS Finder Quick Action |

## The registry change

Windows gets one key, `HKCU\Software\Classes\*\shell\DensePack`, in
your own user hive, never the machine's. It adds the right-click entry
for every file type, and `uninstall-densepack.bat` deletes it.

## How the picture works

Text costs about 1 token per 2.40 characters. An image costs 1 token
per 28 by 28 pixel patch. Small dense type puts more characters into
each patch, so the picture costs 50 to 75 per cent less than the text.
Letters print black, digits blue, symbols red, and a green mark ends
each line. The type size decides which model reads it: Fable 5 reads
8 px, Opus 5 reads 10 px, Sonnet 5 reads 12 px.

# Right-click tool

DensePack right-click tool turns a file or highlighted text into a DensePack image. The packed image costs fewer input tokens than text. Paste into top vision capable models instead of raw text.

## Install

| System  | Install                                                                                                                                      |
| ------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| Windows | Run `install-densepack.bat`. It installs Python, Pillow, freetype-py, NumPy and AutoHotkey if they are missing, adds the shell menu entry and starts the hotkeys. It also adds a reading card hook to `~\.claude\settings.json`, which runs before every prompt in every Claude Code project. To skip the hook, run `powershell -ExecutionPolicy Bypass -File install-densepack.ps1 -NoCard`. It also adds a DensePack shortcut to your Windows Startup folder, so the hotkeys start with Windows. `DensePack.ahk` takes Ctrl+Right-click in every application. To skip the hotkeys, add `-NoHotkey` |
| Linux   | Run `sh install-densepack.sh`. It checks Python, installs Pillow, freetype-py and NumPy, and writes the Open With entry under your home folder. Ubuntu 24.04 and later block that install; the script then prints the command to run. `sh uninstall-densepack.sh` removes the tool |
| macOS   | Open `DensePack it.workflow`. macOS asks once, then the Finder right-click menu carries DensePack it. The workflow runs `~/DensePack/tools/densepack.py`; edit its PACKER line when the download sits elsewhere. A GitHub zip unpacks to a folder named DensePack-main. Rename that folder to DensePack |

## DensePack it

| Action                        | What the tool does                                                          |
| ----------------------------- | --------------------------------------------------------------------------- |
| Right-click a file            | Writes the file's image as a PNG beside it                                  |
| `Ctrl + Shift + D`            | <strong>Replaces</strong> the highlighted text with a packed image, Windows |
| `Ctrl + Shift + C`            | Copies the image and leaves the text, Windows                               |
| `Ctrl + Right-click`          | Opens the DensePack menu in any text box, Windows                           |
| Linux Open With, DensePack it | Writes the file's image as a PNG beside it                                  |

Every entry and hotkey passes no size. The packer produces the plugin's one
image for every model, 17 px unless `DENSEPACK_CODE_PX` names another number.
`densepack.py --size N` sets that number for one run from the shell.

## The files

| File | What it does |
| --- | --- |
| densepack.py | Text in, PNG out, through the plugin's own renderer at the plugin's one size |
| install-densepack.bat, install-densepack.ps1 | The Windows install: the downloads, the registry entry and the hotkeys |
| uninstall-densepack.bat | Removes the Windows registry entry, the hotkeys and the reading card hook |
| uninstall-densepack.sh | Removes the Linux menu items, the Open With entry and the packer copy |
| DensePack.ahk | The two hotkeys and the Ctrl+Right-click menu |
| densepack-clip.ps1 | Puts the image on the Windows clipboard |
| reading_card.py | The Claude Code hook that tells a model what each mark on the image means |
| install-densepack.sh, densepack-file.sh, densepack.desktop | The Linux install, the shell packer and the Open With entry |
| DensePack it.workflow | The macOS Finder Quick Action |

## The registry change

Windows gets one key, `HKCU\Software\Classes\*\shell\DensePack`, in
your own user hive, never the machine's. It adds the right-click entry
for every file type.
`uninstall-densepack.bat` deletes the key, the Startup shortcut, the hotkeys and the reading card hook in `~/.claude`.

## The image

Text costs about 1 token per 2.40 characters. An image costs 1 token
per 28 by 28 pixel patch. Small dense type puts more characters into
each patch, so the image costs fewer tokens than the text.


This tool and the DensePack plugin use the same renderer and pack the same image, regardless of the model, through `plugin/scripts/codepack.py`. 

| Ink colour                            | The characters it prints            |
| ------------------------------------- | ----------------------------------- |
| Black                                 | Letters                             |
| Blue                                  | Digits                              |
| Red                                   | Most other characters               |
| Green number inside black box outline | Literal line number in source file  |
| Missing green numbers                 | Blank lines                         |
| A red number after the green one      | That line's exact indent, in spaces |
| A purple mark at the right edge       | The line continues on the next row  |
| The band colour                       | The line's nesting depth            |
| The top row of image one              | Names every mark on the image       |

There is no line end mark and no legend file. Every menu item and hotkey
runs `densepack.py` with no `--size`, so each one produces the plugin's image.

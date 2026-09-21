<!-- DensePack 1.1 -->
# Right-click tool

The DensePack right-click tool turns a file or highlighted text into a DensePack image. The packed image costs fewer input tokens than text. Paste the image into a top vision capable model instead of the raw text.

## Install

| System | Install |
| --- | --- |
| Windows | Run `install-densepack.bat`. It installs Python, Pillow, freetype-py, NumPy and AutoHotkey if they are missing. Windows can ask for administrator rights for AutoHotkey. The installer adds the shell menu entry and starts the hotkeys. It also adds a reading card hook to `~\.claude\settings.json`. That hook runs before each prompt in each Claude Code project. To skip the hook, run `powershell -ExecutionPolicy Bypass -File install-densepack.ps1 -NoCard`. It also adds a DensePack shortcut to your Windows Startup folder. The hotkeys start with Windows. `DensePack.ahk` takes Ctrl+Right-click in each application. To skip the hotkeys, add `-NoHotkey` |
| Linux | Run `sh install-densepack.sh`. It checks Python and installs Pillow, freetype-py and NumPy. It writes the Open With entry in your home folder. Ubuntu 24.04 and later block that install. The script then prints the command to run. `sh uninstall-densepack.sh` removes the tool |
| macOS | Open `DensePack it.workflow`. macOS asks once, then the Finder right-click menu contains DensePack it. The workflow runs `~/DensePack/tools/densepack.py`. Edit its PACKER line when the download is in a different folder. A GitHub zip unpacks to a folder named DensePack-main. Rename that folder to DensePack |

## DensePack it

| Action | What the tool does |
| --- | --- |
| Right-click a file | Writes the file's image as a PNG beside it |
| `Ctrl + Shift + D` | <strong>Replaces</strong> the highlighted text with a packed image, Windows |
| `Ctrl + Shift + C` | Copies the image and leaves the text, Windows |
| `Ctrl + Right-click` | Opens the DensePack menu in each text box, Windows |
| Linux Open With, DensePack it | Writes the file's image as a PNG beside it |

No entry or hotkey passes a size. The packer produces the plugin's one
image for all models, 17 px unless `DENSEPACK_CODE_PX` names another number.
`densepack.py --size N` sets that number for one run from the shell.

## Where the text and the images go

On Windows, each hotkey and each menu item saves the text and all images in a new folder. The folder name is the first three words of the text.

| You used | The new folder is in |
| --- | --- |
| `Ctrl + Shift + D` or `Ctrl + Shift + C` | `tools\ctrl-shift-vault` |
| The `Ctrl + Right-click` menu | `tools\ctrl-right_click-vault` |

Each folder contains `text.txt` with the exact text and one PNG for each image, such as `image-1.png` and `image-2.png`. File Explorer shows the time of each pack.

`Ctrl + Shift + D` and the menu item DensePack it remove the selected text and paste the image in its place. When the text needs more than one image, the tool pastes all images in order. The first time you use one of them, a window tells you this. Tick "Do not show this message again" to stop the window. The text also stays in the Windows clipboard history (`Win + V`) when clipboard history is on.

The tool never deletes these folders. The uninstall keeps them. Delete them by hand when you do not need them. Git ignores `ctrl-shift-vault` and `ctrl-right_click-vault`.

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
for each file type.
`uninstall-densepack.bat` deletes the key, the Startup shortcut, the hotkeys and the reading card hook in `~/.claude`.

## The image

Text costs about 1 token per 2.40 characters. An image costs 1 token
per 28 by 28 pixel patch. Small dense type puts more characters into
each patch. For most text the image costs fewer tokens than the text.
`densepack.py` prints the text cost and the image cost after a run from the shell. It prints
WORSE when the image costs more.


This tool and the DensePack plugin use the same renderer and pack the same image, regardless of the model, through `plugin/scripts/codepack.py`. 

| Ink colour | The characters it prints |
| --- | --- |
| Black | Letters |
| Blue | Digits |
| Red | Most other characters |
| Green number inside black box outline | Literal line number in source file |
| Missing green numbers | Blank lines |
| A red number after the green one | That line's exact indent, in spaces |
| A purple mark at the right edge | The line continues on the next row |
| The band colour | The line's nesting depth |
| The top row of image one | Names each mark on the image |

There is no line end mark and no legend file. Each menu item and hotkey
runs `densepack.py` with no `--size` and produces the plugin's image.

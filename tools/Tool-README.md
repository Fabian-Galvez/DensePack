<!-- DensePack 1.3 -->
# Right-click tool

The DensePack right-click tool packs a file or selected text into a DensePack image that costs fewer input tokens than the text. Paste the image in place of the text into a model that reads images well.

## Install

| System | Install |
| --- | --- |
| Windows | Run `install-densepack.bat`. It installs Python, Pillow, freetype-py, NumPy and AutoHotkey when they are missing, and Windows can ask for administrator rights for AutoHotkey. The installer adds the shell menu entry, starts the hotkeys and puts a DensePack shortcut in your Windows Startup folder, and the hotkeys then start with Windows. `DensePack.ahk` takes Ctrl+Right-click in each application. The installer also adds a reading card hook to `~\.claude\settings.json`, and that hook runs before each prompt in each Claude Code project. To install without the hook, run `powershell -ExecutionPolicy Bypass -File install-densepack.ps1 -NoCard`. To install without the hotkeys, add `-NoHotkey` |
| Linux | Run `sh install-densepack.sh`. It checks Python, installs Pillow, freetype-py and NumPy, and writes the file manager menu items and the Open With entry in your home folder. Ubuntu 24.04 and later block a pip install into the system Python, and on those systems the script prints the command to run. `sh uninstall-densepack.sh` removes the tool |
| macOS | Open `DensePack it.workflow` and accept the install when macOS asks. The right-click menu of Finder then has DensePack it. The workflow runs `~/DensePack/tools/densepack.py`. When the download is in another folder, edit the PACKER line of the workflow. GitHub zips unpack to a folder named DensePack-main. Rename that folder to DensePack |

## DensePack it

| Action | What the tool does |
| --- | --- |
| Right-click a file | Writes the image of the file as a PNG beside it |
| `Ctrl + Shift + D` | <strong>Replaces</strong> the selected text with a packed image, on Windows |
| `Ctrl + Shift + C` | Copies the image and keeps the text, on Windows |
| `Ctrl + Right-click` | Opens the DensePack menu in each text box, on Windows |
| Linux Open With, DensePack it | Writes the image of the file as a PNG beside it |

No menu entry or hotkey passes a size, and the packer makes the one image of the plugin for all models, at 17 px unless `DENSEPACK_CODE_PX` names another number. `densepack.py --size N` sets that number for one run from the shell.

## Where the text and the images go

On Windows, each hotkey and each menu item saves the text and all images in a new folder named after the first three words of the text.

| You used | The new folder is in |
| --- | --- |
| `Ctrl + Shift + D` or `Ctrl + Shift + C` | `tools\ctrl-shift-vault` |
| The `Ctrl + Right-click` menu | `tools\ctrl-right_click-vault` |

Each folder holds `text.txt` with the exact text and one PNG for each image, such as `image-1.png` and `image-2.png`. File Explorer shows the time of each pack.

`Ctrl + Shift + D` and the menu item **DensePack it** replace the selected text with its image, and when the text needs more than one image, the tool pastes all images in order. The first time you use one of them, a window explains this. Select "Do not show this message again" to stop that window. The text also stays in the Windows clipboard history (`Win + V`) when clipboard history is on.

Git ignores the two vault folders, `ctrl-shift-vault` and `ctrl-right_click-vault`, and the tool and the uninstall never delete them. Delete a folder by hand when you do not need it.

## The files

| File | What it does |
| --- | --- |
| densepack.py | Packs text into a PNG with the renderer of the plugin, at the one size of the plugin |
| install-densepack.bat, install-densepack.ps1 | The Windows install. It does the downloads and adds the registry entry and the hotkeys |
| uninstall-densepack.bat | Removes the Windows registry entry, the hotkeys and the reading card hook |
| uninstall-densepack.sh | Removes the Linux menu items, the Open With entry and the packer copy |
| DensePack.ahk | The two hotkeys and the Ctrl+Right-click menu |
| densepack-clip.ps1 | Puts the image on the Windows clipboard |
| reading_card.py | The Claude Code hook that explains each mark on the image to the model |
| install-densepack.sh, densepack-file.sh, densepack.desktop | The Linux install, the shell packer and the Open With entry |
| DensePack it.workflow | The macOS Finder Quick Action |

## The registry change

The installer adds one key, `HKCU\Software\Classes\*\shell\DensePack`, to your own user hive and never to the machine hive. The key adds the right-click entry for each file type.

`uninstall-densepack.bat` deletes the key, the Startup shortcut, the hotkeys and the reading card hook in `~/.claude`.

## The image

Text costs about 1 token for each 2.40 characters, and an image costs 1 token for each patch of 28 by 28 pixels. Small dense type puts more characters into each patch, and for most text the image costs fewer tokens than the text.

After a run from the shell, `densepack.py` prints the text cost and the image cost, and it prints WORSE when the image costs more.

This tool and the DensePack plugin use the same renderer, `plugin/scripts/codepack.py`, and make the same image for each model.

| Mark | What it shows |
| --- | --- |
| Black characters | Letters |
| Blue characters | Digits |
| Red characters | Most other characters |
| Green numbers in a box | The line number in the source file |
| Gaps in the green numbers | Blank lines |
| Red numbers after the green number | The exact indent of the line, in spaces |
| Purple marks at the right edge | The line continues on the next row |
| The band color | The nesting depth of the line |
| The key at the top of the first image | The name of each mark |

The image has no line end mark, and the tool writes no legend file. Each menu item and hotkey runs `densepack.py` with no `--size` and makes the image of the plugin.

<!-- DensePack 2.0 -->
# Right-click tool

The DensePack right-click tool packs a file or selected text into a DensePack image. For most text, the image costs fewer input tokens than the text itself. Paste the image in place of the text into models that read images well.

<br>

---

<br>

## Install

| System | Install |
| --- | --- |
| Windows | Run `install-densepack.bat`. It downloads and installs Python, Pillow, freetype-py, NumPy and AutoHotkey when they are missing. Windows can ask for administrator rights for AutoHotkey.<br><br>The installer adds the shell menu entry and starts the hotkeys. It also puts a DensePack shortcut in your Windows Startup folder to start the hotkeys with Windows. `DensePack.ahk` catches Ctrl+Right-click in each application.<br><br>The installer also adds a reading card hook to `~\.claude\settings.json` that runs before each prompt in each Claude Code project.<br><br>To install without the hook, run `powershell -ExecutionPolicy Bypass -File install-densepack.ps1 -NoCard`. To install without the hotkeys, add `-NoHotkey` to the PowerShell command |
| Linux | Run `sh install-densepack.sh`. It checks for Python 3.10 or newer and downloads and installs Pillow, freetype-py and NumPy when they are missing. It then writes the file manager menu items and the Open With entry in your home folder. Newer Debian and Ubuntu releases block pip installs into the system Python. On those systems, the script prints the commands that work and stops. `sh uninstall-densepack.sh` removes the tool |
| macOS | Open `DensePack it.workflow` and accept the install when macOS asks. In Finder, right-click a file, then choose Quick Actions, then DensePack it.<br><br>The workflow runs `tools/densepack.py` from `~/DensePack`, or else from the plugin's download in `~/.claude/plugins/marketplaces/densepack-marketplace`. For a copy in another folder, open `~/Library/Services/DensePack it.workflow` in Automator and put the full path of its `tools/densepack.py` in the PACKER line. GitHub ZIP files unpack to `DensePack-main` in Downloads, so rename that folder to `DensePack` and move it to your home folder.<br><br>The workflow installs nothing. When the DensePack plugin is installed and has run once in Claude Code, the workflow uses the plugin's Python, Pillow, freetype-py and NumPy. Without the plugin, it needs Python 3.10 or newer with those packages. Run `brew install python`, then `python3 -m pip install --user --break-system-packages pillow freetype-py numpy`.<br><br>To remove the tool, delete `~/Library/Services/DensePack it.workflow` |

<br>

---

<br>

## DensePack it

| Action | What the tool does |
| --- | --- |
| Right-click a file | The tool writes the image of the file as a PNG beside the file |
| `Ctrl + Shift + D` | On Windows, the tool <strong>replaces</strong> the selected text with a packed image |
| `Ctrl + Shift + C` | On Windows, the tool copies the image and keeps the text |
| `Ctrl + Right-click` | On Windows, the tool opens the DensePack menu in each text box |
| Linux Open With, DensePack it | The tool writes the image of the file as a PNG beside the file |
| macOS Quick Actions, DensePack it | The tool writes the image of the file as a PNG beside the file |

- The menu entries and hotkeys pass no size.
- The packer makes the same image as the plugin for all models, at 17 px unless `DENSEPACK_CODE_PX` sets another number.
- `densepack.py --size N` sets that number for one run from the shell.

<br>

---

<br>

## Output folders

On Windows, the hotkeys and menu items save the text and the images of each pack in a new folder. The folder takes its name from the first three words of the text, which helps you find a pack later.

| You used | The new folder is in |
| --- | --- |
| `Ctrl + Shift + D` or `Ctrl + Shift + C` | `tools\ctrl-shift-vault` |
| The `Ctrl + Right-click` menu | `tools\ctrl-right_click-vault` |

Pack folders contain `text.txt` with the exact text and one PNG for each image, such as `image-1.png` and `image-2.png`. File Explorer shows the time of each pack.

`Ctrl + Shift + D` and the menu item **DensePack it** replace the selected text with its image.

- When the text needs more than one image, the tool pastes all images in order.
- The first time you use one of them, the tool shows a warning window. The warning contains that the tool replaces the selected text, saves the text in the vault folder, and leaves it in the clipboard history. Select "Do not show this message again" to stop that window in later uses.
- The text also stays in the Windows clipboard history (`Win + V`) when clipboard history is on.

Git ignores the two vault folders, `ctrl-shift-vault` and `ctrl-right_click-vault`. The tool and the uninstall never delete them, so delete a folder manually when you no longer need it.

Removing the plugin folder deletes them when the tool runs from it, so copy out the folders you want to keep first.

<br>

---

<br>

## The files

| File | What it does |
| --- | --- |
| densepack.py | It packs text into a PNG with the renderer of the plugin at the one image size of the plugin |
| install-densepack.bat, install-densepack.ps1 | These files run the Windows install. They download what the install needs and add the registry entry and the hotkeys |
| uninstall-densepack.bat | It removes the Windows registry entry, the hotkeys and the reading card hook |
| uninstall-densepack.sh | It removes the Linux menu items, the Open With entry and the packer copy |
| DensePack.ahk | It contains the two hotkeys and the Ctrl+Right-click menu |
| densepack-clip.ps1 | It puts the image on the Windows clipboard |
| reading_card.py | This Claude Code hook adds an explanation of each mark on the image to your prompt for the model |
| install-densepack.sh, densepack-file.sh, densepack.desktop | These files are the Linux install, the shell packer and the Open With entry |
| DensePack it.workflow | It is the macOS Finder Quick Action |

<br>

---

<br>

## The registry change

The installer adds one key, `HKCU\Software\Classes\*\shell\DensePack`, to your own user hive. When AutoHotkey is missing, its winget install runs for the whole computer and adds AutoHotkey's own entries. The key adds the right-click entry for each file type.

`uninstall-densepack.bat` deletes the key, the Startup shortcut, the hotkeys and the reading card hook in `~/.claude`. When it finds no Python, it keeps the reading card and prints the entry to delete from `~/.claude/settings.json`.

<br>

---

<br>

## The image

For most text, the image costs fewer tokens than the text. The token costs and the meaning of each mark are in [The image](../HOW-IT-WORKS.md#the-image).

After a run from the shell, `densepack.py` prints the text cost and the image cost. It prints WORSE when the image costs more. Send the text instead in that case.

This tool uses the plugin renderer, `plugin/scripts/codepack.py`, so it makes the same image as the plugin for each model.
The tool loads the renderer from `plugin/scripts/` each time it runs. Changes to the renderer reach the tool with no change to the tool.

The image has no line end mark. The tool writes no legend file, because the first image has a key for each mark. The menu items and hotkeys all run `densepack.py` with no `--size` and make the same image as the plugin.

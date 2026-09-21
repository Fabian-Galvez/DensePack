<!-- DensePack 1.1 -->
# Privacy policy

DensePack does all its work on your computer.

DensePack sends no file, no text and no image to an external service. It collects no data.

DensePack uses the network only to install what it needs. On the first run the plugin installs Pillow, freetype-py and NumPy with pip. On Windows it also installs Python with winget when Python is missing. On macOS and Linux the plugin installs no Python. It prints the command for you to run. The installer of the right-click tool installs the same packages. On Windows that installer also installs AutoHotkey with winget.

The plugin contains the Inter font. It downloads no font.

DensePack saves files on your own disk only. The plugin saves the images it draws and copies of the text it converts in the `.claude` folder of each project and in `~/.claude`. The right-click tool saves each image beside the source file. On Windows the hotkeys save the text and the images of each pack in the two vault folders in `tools`.

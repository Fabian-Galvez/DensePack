# DensePack

DensePack is a plugin for Claude Code and Cowork. It packs file Reads and long Bash output into images, so the model reads fewer tokens.

Install steps, commands and benchmarks are in the full README at https://github.com/Fabian-Galvez/DensePack.

Claude Code needs `densepack:` before every command, such as `/densepack:helppack`. Cowork uses the short names, such as `/helppack`.

## What DensePack runs and downloads

DensePack sends no file, text or image to an outside service. It uses the network only to download and install what it needs, once on each computer:

- At session start, if Pillow, freetype-py or NumPy is missing, it downloads and installs them from PyPI with pip. They go into the plugin's own data folder.
- On macOS with no Python 3.10 or newer, it downloads uv 0.13.5 from the uv releases on GitHub and checks its SHA-256. uv downloads and installs Python 3.13 from the python-build-standalone releases on GitHub into the plugin's data folder. Then pip downloads and installs the three packages, and DensePack deletes uv.
- On Windows with no Python 3.10 or newer, it downloads and installs Python 3.13 with winget.
- On Windows with no Git Bash, it downloads and installs Git for Windows with winget.
- On Linux, it installs no Python and shows the command for you to run.

The macOS install needs no password and changes no PATH. The plugin uninstall deletes the data folder and what is in it. PRIVACY-POLICY.md in the repository has the details.

The license is MIT. See LICENSE in this folder.

# BinDbg

## Description:

BinDbg is a Binary Ninja plugin that syncs WinDbg to Binja to create a fusion of dynamic and static analyses. It was primarily written to improve the Windows experience for Binja debugger integrations.

Features include:
 * Start and stop WinDbg directly in Binja
 * Control debugger execution and IP
 * Set and delete breakpoints
 * Set process arguments
 * Branch decision highlighting
 * vtable resolution and (rough) type identification
 * ASLR support
 
Demo video: https://www.youtube.com/watch?v=6xrf4hgog5s

Likely full of bugs and oversights; issues and PR's welcomed :)

## Installation

`git clone https://github.com/kukfa/bindbg.git` within your Binary Ninja plugins folder (`%APPDATA%\Binary Ninja\plugins`), and install WinDbg via the Windows SDK for your version of Windows.

The following pip dependencies are required:
 * python-qt5
 * pywin32
 * pykd (with [bootstrapper](https://githomelab.ru/pykd/pykd/wikis/Pykd-bootstrapper))

I recommend installing these on the system's native Python installation, then adding the `site-packages` folder to the `PYTHONPATH` environment variable instead of trying to install everything in Binja's embedded Python.

In `__init__.py`, modify the `pykd_path` var to reflect the absolute path to `pykd.dll`, and the `dbg_dir` var to the `Debuggers` folder containing the x86 and x64 WinDbg folders.

## Usage

 * Open target binary in Binja
 * Tools or right-click -> Initialize Toolbar for this view
 * Tools or right-click -> Set process arguments (if necessary)
 * Click Go on the toolbar to launch WinDbg
 * Open Memory/Registers windows in WinDbg as desired
 * Control execution (run, break, step out, step in, step over) using the buttons in the toolbar
 * Control IP (run to cursor, set IP) by right-clicking an instruction and selecting a command accordingly
 * Set or delete breakpoints by right-clicking an instruction and selecting a command accordingly
 * vtable calls and references will be automatically resolved as a Binja comment during execution
 * Click Stop on the toolbar to stop debugging

## Acknowledgements

Many ideas (and code) were borrowed from the following projects:

 * snare's [Binjatron](https://github.com/snare/binjatron)
 * Eric Hennenfent's [Binja Dynamics](https://github.com/ehennenfent/binja_dynamics)
 * Eric Hennenfent's [Binja Toolbar](https://github.com/ehennenfent/binja_toolbar) (and thus NOPDev's [BinjaDock](https://github.com/NOPDev/BinjaDock))

## License

This plugin is released under an [MIT](LICENSE) license.
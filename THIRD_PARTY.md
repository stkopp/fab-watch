# Third-party components and notices

Fab Watch application source and original project assets are distributed under
the root MIT license. Fab, Epic Games and Unreal Engine trademarks and third-party
content displayed in examples are not relicensed by this project.

The Windows bundle includes CPython, Tcl/Tk and dependent runtime libraries. Their
original licenses remain in effect. Build tooling includes PyInstaller (GPL with
its bootloader distribution exception), pyinstaller-hooks-contrib and their build
dependencies. The PyInstaller exception permits shipping the frozen application
under the application's own license; it does not relicense PyInstaller itself.

The build copies the Python installation's LICENSE.txt, Tcl/Tk license.terms,
PyInstaller license/copying documents and project notices into the installed
`_internal/licenses/` directory. Python's bundled notice includes notices for
standard-library components. Any licenses collected by PyInstaller are retained.

References:

- https://docs.python.org/3/license.html
- https://www.tcl-lang.org/software/tcltk/license.html
- https://pyinstaller.org/en/stable/license.html

When adding a dependency, review its redistribution requirements and update the
packaged notices. Do not treat this summary as a replacement for those licenses.

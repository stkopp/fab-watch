"""Copy actual runtime/build-tool licenses into a staging directory."""
from importlib.metadata import distribution
from pathlib import Path
import shutil
import sys


def collect(destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[1]
    for source, name in ((root / "LICENSE", "FabWatch-MIT.txt"),
                         (root / "THIRD_PARTY.md", "THIRD_PARTY.md"),
                         (Path(sys.base_prefix) / "LICENSE.txt", "Python-LICENSE.txt")):
        shutil.copyfile(source, destination / name)
    found = list((Path(sys.base_prefix) / "tcl").glob("*/license.terms"))
    if not found:
        raise RuntimeError("Tcl/Tk license files are required for a Windows release")
    for source in found:
        shutil.copyfile(source, destination / (source.parent.name + "-license.txt"))
    for source in (root / "licenses").glob("*.txt"):
        shutil.copyfile(source, destination / source.name)
    for package in ("pyinstaller", "pyinstaller-hooks-contrib", "altgraph", "pefile", "pywin32-ctypes", "packaging"):
        dist = distribution(package)
        copied = 0
        for item in dist.files or []:
            if "dist-info" in str(item) and any(word in item.name.lower() for word in ("license", "copying", "copyright")):
                source = Path(dist.locate_file(item))
                if source.is_file():
                    shutil.copyfile(source, destination / f"{package}-{item.name}.txt")
                    copied += 1
        if not copied:
            raise RuntimeError(f"Missing redistribution notice for {package}")


if __name__ == "__main__":
    collect(sys.argv[1])

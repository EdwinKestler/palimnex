"""Exercise installed distributions outside the source tree (no Redis/network)."""
from importlib.resources import files
from pathlib import Path
import subprocess
import sys
import tempfile

from palimnex import API_VERSION, Palimnex, __version__
from palimnex.tests.support import write_project


def main() -> None:
    assert API_VERSION == 1 and __version__ == "2.7.0"
    package = files("palimnex")
    assert package.joinpath("py.typed").is_file()
    assert any(package.joinpath("schemas").iterdir())
    assert any(package.joinpath("evaluation").iterdir())
    with tempfile.TemporaryDirectory(prefix="palimnex-installed-") as temporary:
        root = Path(temporary)
        write_project(root)
        reader = Palimnex(root)
        assert reader.status()["status"] == "missing"
        version = subprocess.check_output([sys.executable, "-m", "palimnex", "--version"], cwd=root, text=True)
        assert "2.7.0" in version
        commands = () if "--core-only" in sys.argv else ("evaluate-challenges", "evaluate-longitudinal")
        for command in commands:
            subprocess.run([sys.executable, "-m", "palimnex", command], cwd=root, check=True,
                           stdout=subprocess.DEVNULL)
    print("Installed package: resources, CLI and SDK passed" +
          (" (no extras)" if "--core-only" in sys.argv else "; offline evaluations passed"))


if __name__ == "__main__":
    main()

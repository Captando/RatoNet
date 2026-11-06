"""Build the standalone hardware bundle from the canonical field-agent sources."""

from pathlib import Path
import tarfile


def build(output: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    output.parent.mkdir(parents=True, exist_ok=True)
    files = [root / "ratonet/__init__.py", root / "ratonet/config.py"]
    for folder in ("common", "field"):
        files.extend(sorted((root / "ratonet" / folder).glob("*.py")))
    with tarfile.open(output, "w:gz") as archive:
        for path in files:
            archive.add(path, arcname=str(Path("ratonet-field") / path.relative_to(root)))
        for name in ("requirements.txt", ".env.example", "README.md"):
            archive.add(root / "hardware-streamer" / name, arcname=f"ratonet-field/{name}")


if __name__ == "__main__":
    target = Path(__file__).resolve().parents[1] / "dist/ratonet-field.tar.gz"
    build(target)
    print(target)

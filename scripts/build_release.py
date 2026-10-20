#!/usr/bin/python3
"""Build the shareable Ubuntu 24.04 ARM64 package for 芯观.

The build is reproducible from tracked files only:

    python3 scripts/build_release.py

Outputs:
    build/                     staging trees (ignored by git)
    dist/芯观-<version>-Ubuntu24.04-ARM64.zip
    dist/芯观-<version>-Ubuntu24.04-ARM64.sha256
"""
from pathlib import Path
import hashlib
import json
import re
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PACKAGING = ROOT / "packaging"
BUILD = ROOT / "build"
DIST = ROOT / "dist"

VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?", VERSION):
    sys.exit(f"VERSION 文件内容不是有效的版本号：{VERSION!r}")

ARCHIVE = f"xinguan-{VERSION}-ubuntu24.04-arm64"
BUNDLE_NAME = f"芯观-{VERSION}-Ubuntu24.04-ARM64"
DEB = f"xinguan_{VERSION}_arm64.deb"
STAGE = BUILD / "deb-root"
BUNDLE = BUILD / BUNDLE_NAME

APP_FILES = ("app.py", "metrics.py", "check_runtime.py")


def write(root: Path, relative: str, data: str, executable: bool = False) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data, encoding="utf-8")
    path.chmod(0o755 if executable else 0o644)
    return path


def render(relative: str) -> str:
    return (PACKAGING / relative).read_text(encoding="utf-8").replace("@VERSION@", VERSION)


def main() -> None:
    for directory in (BUILD, DIST):
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir(parents=True)

    for path in (STAGE, BUNDLE):
        path.mkdir(parents=True)

    for filename in APP_FILES:
        write(STAGE, f"usr/share/xinguan/{filename}", (ROOT / "src" / filename).read_text(encoding="utf-8"))

    write(STAGE, "usr/bin/xinguan", render("launcher.sh"), executable=True)
    write(STAGE, "usr/share/applications/local.ahua.HardwarePanel.desktop",
          (PACKAGING / "xinguan.desktop").read_text(encoding="utf-8"))
    write(STAGE, "usr/share/icons/hicolor/scalable/apps/local.ahua.HardwarePanel.svg",
          (ROOT / "assets/icon.svg").read_text(encoding="utf-8"))
    write(STAGE, "usr/share/doc/xinguan/README.zh_CN.txt", render("README.txt.in"))

    size = sum(p.stat().st_size for p in STAGE.rglob("*") if p.is_file())
    write(STAGE, "DEBIAN/control", f"""Package: xinguan
Version: {VERSION}
Section: utils
Priority: optional
Architecture: arm64
Maintainer: chengminhua <chengminhua@users.noreply.github.com>
Installed-Size: {(size + 1023) // 1024}
Depends: python3 (>= 3.10), python3-gi, python3-gi-cairo, python3-cairo, python3-psutil, gir1.2-gtk-4.0 (>= 4.14), gir1.2-adw-1 (>= 1.5)
Description: Native hardware dashboard for AIBOOK M1000
 Chinese read-only dashboard for CPU, GPU, memory, temperature, fans,
 battery and separate power rails. Whole-system AC power is unavailable.
 Validated on Ubuntu 24.04 ARM64. Vendor drivers are not bundled.
""")

    hashes = []
    for path in sorted((STAGE / "usr").rglob("*")):
        if path.is_file():
            hashes.append(hashlib.md5(path.read_bytes()).hexdigest()
                          + "  " + str(path.relative_to(STAGE)))
    write(STAGE, "DEBIAN/md5sums", "\n".join(hashes) + "\n")

    for path in STAGE.rglob("*"):
        if path.is_dir():
            path.chmod(0o755)
    STAGE.chmod(0o755)

    subprocess.run(["dpkg-deb", "--root-owner-group", "--build", str(STAGE), str(BUNDLE / DEB)],
                   check=True)

    write(BUNDLE, "安装芯观.sh", render("install.sh.in"), executable=True)
    write(BUNDLE, "使用说明.txt", render("README.txt.in"))

    manifest = "".join(
        hashlib.sha256(path.read_bytes()).hexdigest() + "  " + path.name + "\n"
        for path in sorted(BUNDLE.iterdir()) if path.is_file()
    )
    write(BUNDLE, "SHA256SUMS.txt", manifest)

    desktop_file = STAGE / "usr/share/applications/local.ahua.HardwarePanel.desktop"
    if shutil.which("desktop-file-validate"):
        subprocess.run(["desktop-file-validate", str(desktop_file)], check=True)
    subprocess.run(["bash", "-n", str(BUNDLE / "安装芯观.sh"), str(STAGE / "usr/bin/xinguan")],
                   check=True)

    archive = DIST / f"{ARCHIVE}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in sorted(BUNDLE.iterdir()):
            zf.write(path, str(Path(BUNDLE_NAME) / path.name))

    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    write(DIST, f"{ARCHIVE}.sha256", f"{digest}  {archive.name}\n")

    print(json.dumps({
        "archive": str(archive.relative_to(ROOT)),
        "bytes": archive.stat().st_size,
        "sha256": digest,
        "deb": str((BUNDLE / DEB).relative_to(ROOT)),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

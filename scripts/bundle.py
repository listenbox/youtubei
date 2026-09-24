#!/usr/bin/env python3
"""Reproduce the committed bundle using verified upstream archives (Linux x64).

This maintainer-only tool uses Python 3.12+ and the native esbuild executable.
Cargo consumers need neither this script nor a JavaScript toolchain.
"""

import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import platform
import subprocess
import tarfile
import tempfile
import urllib.request


ROOT = Path(__file__).resolve().parent.parent


def unpack(name, version, integrity, destination):
    url = f"https://registry.npmjs.org/{name}/-/{name.split('/')[-1]}-{version}.tgz"
    with urllib.request.urlopen(url, timeout=30) as response:
        data = response.read()
    digest = "sha512-" + base64.b64encode(hashlib.sha512(data).digest()).decode()
    if digest != integrity:
        raise ValueError(f"Integrity mismatch for {name}@{version}")
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        for member in archive.getmembers():
            if not member.name.startswith("package/"):
                raise ValueError(f"Unexpected archive entry: {member.name}")
            member.name = member.name.removeprefix("package/")
            if member.name:
                archive.extract(member, destination, filter="data")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Compare without changing files")
    args = parser.parse_args()
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        parser.error("Bundle regeneration uses the pinned Linux x64 esbuild build")
    lock = json.loads((ROOT / "upstream.json").read_text())
    with tempfile.TemporaryDirectory(prefix="youtubei-bundle-") as temporary:
        directory = Path(temporary)
        notices = []
        for name, package in lock["packages"].items():
            target = directory / "node_modules" / name
            unpack(name, package["version"], package["integrity"], target)
            licenses = sorted(path for path in target.iterdir() if path.name.lower().startswith("license"))
            if name == "@bufbuild/protobuf":
                # The npm archive omits its declared Apache/BSD license texts.
                licenses = sorted((ROOT / "licenses").glob("protobuf-*.txt"))
            if not licenses:
                raise ValueError(f"Missing license for {name}")
            notices.append(f"{name}@{package['version']}\n" + "\n".join(path.read_text() for path in licenses))
        esbuild = lock["esbuild"]
        unpack("@esbuild/linux-x64", esbuild["version"], esbuild["integrity"], directory / "esbuild")
        binary = directory / "esbuild/bin/esbuild"
        binary.chmod(0o755)
        output = directory / "youtubei.js"
        subprocess.run([
            str(binary), "node_modules/youtubei.js/dist/src/platform/cf-worker.js",
            "--bundle", "--platform=browser", "--format=esm", "--keep-names",
            "--legal-comments=inline", "--outfile=youtubei.js",
        ], cwd=directory, check=True)
        generated = {
            "youtubei.js": output.read_bytes(),
            "THIRD-PARTY-NOTICES.txt": "\n\n".join(notices).encode(),
        }
        (ROOT / "generated").mkdir(exist_ok=True)
        for name, content in generated.items():
            target = ROOT / "generated" / name
            if args.check:
                if target.read_bytes() != content:
                    raise ValueError(f"Generated file differs: {target}")
            else:
                target.write_bytes(content)


if __name__ == "__main__":
    main()

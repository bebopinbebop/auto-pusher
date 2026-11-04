"""Run offline release checks against an already built Docker image."""
import argparse
import shutil
import subprocess
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--image", default="git-progressor:local")
    args = parser.parse_args()
    bundle = args.bundle.resolve(strict=True)
    if not bundle.is_file() or "," in str(bundle):
        parser.error("bundle must be a file whose path contains no commas")
    docker = shutil.which("docker")
    if docker is None:
        parser.error("Docker CLI is not installed")
    common = [docker, "run", "--rm", "--network", "none", "--read-only",
              "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
              "--tmpfs", "/tmp:rw,nosuid,nodev,size=256m"]  # noqa: S108 - isolated container mount

    def run(arguments: list[str]) -> None:
        subprocess.run(arguments, check=True, timeout=120)  # noqa: S603

    run([*common, "--entrypoint", "python", args.image, "-c",
         "import os,pathlib; "
         "assert os.getuid()==10001, 'unexpected runtime user'; "
         "assert not os.environ.get('OPENAI_API_KEY'), 'unexpected credential'; "
         "assert not pathlib.Path('/app/data').exists(), 'host data in image'; "
         "assert not pathlib.Path('/app/.git').exists(), 'Git history in image'; "
         "print('Non-root runtime and isolated image checks passed')"])
    run([*common, args.image, "--help"])
    run([*common, "--mount", f"type=bind,source={bundle},target=/input/bundle.zip,readonly",
         args.image, "bundle-verify", "/input/bundle.zip", "--sha256", args.sha256])
    print("Offline container smoke checks passed.")


if __name__ == "__main__":
    main()

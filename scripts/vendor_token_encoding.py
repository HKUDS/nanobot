"""Reproduce the bundled cl100k_base vocabulary from its pinned upstream bytes."""

import gzip
import hashlib
from pathlib import Path
from urllib.request import urlopen

URL = "https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken"
SHA256 = "223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7"
TARGET = Path(__file__).resolve().parents[1] / "nanobot/utils/cl100k_base.tiktoken.gz"


def main() -> None:
    with urlopen(URL, timeout=30) as response:
        vocabulary = response.read()
    if hashlib.sha256(vocabulary).hexdigest() != SHA256:
        raise ValueError("upstream cl100k_base vocabulary checksum mismatch")
    with TARGET.open("wb") as output:
        with gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0) as compressed:
            compressed.write(vocabulary)
    print(f"{TARGET}: {len(vocabulary)} bytes before compression")


if __name__ == "__main__":
    main()

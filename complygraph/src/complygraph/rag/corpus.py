from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass
class Chunk:
    id: str
    regulation: str
    section: str
    text: str
    score: float = 0.0

    def to_dict(self):
        return asdict(self)


def load_corpus(directory: Path) -> list[Chunk]:
    chunks: list[Chunk] = []
    for path in sorted(Path(directory).glob("*.md")):
        raw = path.read_text()
        lines = raw.splitlines()
        title = next((l[2:].strip() for l in lines if l.startswith("# ")), path.stem)
        title = title.split(" (")[0].split(" - ")[0].strip()
        for i, block in enumerate(raw.split("\n## ")[1:], 1):
            head, _, body = block.partition("\n")
            chunks.append(Chunk(f"{path.stem}#{i}", title, head.strip(), body.strip()))
    return chunks

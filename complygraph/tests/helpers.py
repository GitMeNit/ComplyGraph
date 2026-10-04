import tempfile
from pathlib import Path

from complygraph.config import Settings
from complygraph.copilot import Copilot
from complygraph.llm import OfflineLLM


def make_copilot():
    s = Settings.load(state_dir=Path(tempfile.mkdtemp()))
    return Copilot(s, OfflineLLM()), s

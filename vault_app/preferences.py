import json
import logging
from pathlib import Path


logger = logging.getLogger(__name__)


class AppPreferences:
    def __init__(self, state_file: Path) -> None:
        self.state_file = state_file

    def load(self) -> dict:
        if not self.state_file.exists():
            return {}

        try:
            return json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Could not load app state: %s", exc)
            return {}

    def save(self, data: dict) -> None:
        try:
            self.state_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            logger.warning("Could not save app state: %s", exc)

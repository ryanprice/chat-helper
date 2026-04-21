import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_DEFAULT_PATH = "data/watcher_feedback.jsonl"


class FeedbackLog:
    def __init__(self, path: str = _DEFAULT_PATH):
        self._path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)

    def record(self, action_id: str, chat_id: str, action_type: str, trigger_summary: str) -> None:
        """Append a new unrated entry to the log."""
        entry = {
            "action_id": action_id,
            "chat_id": chat_id,
            "action_type": action_type,
            "trigger_summary": trigger_summary,
            "score": None,
        }
        with open(self._path, "a") as f:
            f.write(json.dumps(entry) + "\n")
        logger.debug("Recorded watcher action %s (type=%s)", action_id, action_type)

    def _read_all(self) -> list[dict]:
        if not os.path.exists(self._path):
            return []
        entries = []
        with open(self._path) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return entries

    def update_score(self, action_id: str, score: int) -> bool:
        """Find action_id and set its score. Rewrites the file. Returns True if found."""
        entries = self._read_all()
        found = False
        for entry in entries:
            if entry.get("action_id") == action_id:
                entry["score"] = score
                found = True
                break
        if found:
            with open(self._path, "w") as f:
                for entry in entries:
                    f.write(json.dumps(entry) + "\n")
            logger.debug("Updated score for action %s → %d", action_id, score)
        return found

    def get_last_unrated(self) -> Optional[dict]:
        """Return the most recent entry with score=None, or None if all are rated."""
        entries = self._read_all()
        for entry in reversed(entries):
            if entry.get("score") is None:
                return entry
        return None

    def summarize(self, n: int = 20) -> str:
        """Return a compact feedback summary suitable for injection into the decision gate prompt."""
        entries = self._read_all()
        scored = [e for e in entries if e.get("score") is not None]
        recent = scored[-n:]

        if not recent:
            return (
                "No feedback yet. Default to conservative action — "
                "only act when there is clear, specific value."
            )

        useful = [e for e in recent if e.get("score") == 1]
        not_useful = [e for e in recent if e.get("score") == 0]

        type_counts: dict[str, dict[str, int]] = {}
        for e in recent:
            at = e.get("action_type", "unknown")
            if at not in type_counts:
                type_counts[at] = {"useful": 0, "total": 0}
            type_counts[at]["total"] += 1
            if e.get("score") == 1:
                type_counts[at]["useful"] += 1

        type_summary = ", ".join(
            f"{at}: {v['useful']}/{v['total']}" for at, v in type_counts.items()
        )

        lines = [f"Last {len(recent)} rated actions: {len(useful)} useful ({type_summary})."]

        useful_triggers = [e.get("trigger_summary", "") for e in useful[-5:] if e.get("trigger_summary")]
        poor_triggers = [e.get("trigger_summary", "") for e in not_useful[-5:] if e.get("trigger_summary")]

        if useful_triggers:
            lines.append(f"Useful triggers: {'; '.join(useful_triggers)}.")
        if poor_triggers:
            lines.append(f"Poor triggers: {'; '.join(poor_triggers)}.")

        return " ".join(lines)

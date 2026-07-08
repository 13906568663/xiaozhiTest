"""In-memory conversation history with per-message marks.

设计要点：
  * ``add_message`` / ``get_memory`` 是同步 API（纯内存操作，不需要 async）。
  * ``state_dict`` / ``load_state_dict`` 的序列化形状：
    ``{"content": [[msg_dict, marks], ...], "compressed_summary": str | None}``。
  * 支持给消息打 mark（如 ``"compressed"``），调用方在压缩时使用，避免被压缩
    过的消息再次进入下一轮 reasoning。
  * 提供 ``compressed_summary``：在前置消息被压缩后，新一轮 reasoning 把
    ``summary`` 当成"上文摘要"塞回 history。
"""

from __future__ import annotations

from typing import Any, Iterable

from app.runtime_core.messages import Msg


class Memory:
    """A simple list-backed memory with marks and a single compression summary."""

    def __init__(self) -> None:
        # 每条 entry = (Msg, marks_set)
        self._entries: list[tuple[Msg, set[str]]] = []
        self._compressed_summary: str | None = None

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def add_message(self, msg: Msg) -> None:
        self._entries.append((msg, set()))

    def add_messages(self, msgs: Iterable[Msg]) -> None:
        for m in msgs:
            self.add_message(m)

    def mark_messages(self, msg_ids: Iterable[str], mark: str) -> int:
        """Add ``mark`` to every message whose ``id`` is in ``msg_ids``."""
        targets = set(msg_ids)
        if not targets or not mark:
            return 0
        count = 0
        for msg, marks in self._entries:
            if msg.id in targets:
                marks.add(mark)
                count += 1
        return count

    def update_compressed_summary(self, summary: str | None) -> None:
        self._compressed_summary = summary or None

    def clear(self) -> None:
        self._entries.clear()
        self._compressed_summary = None

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._entries)

    def get_memory(
        self, *, exclude_mark: str | None = None,
    ) -> list[Msg]:
        """Return messages, optionally skipping any tagged with ``exclude_mark``."""
        if not exclude_mark:
            return [m for m, _ in self._entries]
        return [m for m, marks in self._entries if exclude_mark not in marks]

    def get_entries(self) -> list[tuple[Msg, set[str]]]:
        return [(m, set(marks)) for m, marks in self._entries]

    @property
    def compressed_summary(self) -> str | None:
        return self._compressed_summary

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def state_dict(self) -> dict[str, Any]:
        return {
            "content": [
                [msg.to_dict(), sorted(marks)] for msg, marks in self._entries
            ],
            "compressed_summary": self._compressed_summary,
        }

    def load_state_dict(self, state: dict[str, Any], *, strict: bool = False) -> None:
        if not isinstance(state, dict):
            if strict:
                raise TypeError("Memory state must be a dict")
            return

        self._entries.clear()
        for entry in state.get("content") or []:
            try:
                if isinstance(entry, (list, tuple)) and len(entry) == 2:
                    raw_msg, raw_marks = entry
                else:
                    raw_msg, raw_marks = entry, []
                msg = Msg.from_dict(raw_msg)
                marks = set(raw_marks) if isinstance(raw_marks, (list, tuple, set)) else set()
                self._entries.append((msg, marks))
            except Exception:
                if strict:
                    raise
                continue
        summary = state.get("compressed_summary")
        self._compressed_summary = str(summary) if summary else None


__all__ = ["Memory"]

from pathlib import Path
from unittest.mock import MagicMock

from imbue.mng.primitives import AgentLifecycleState
from imbue.mng.primitives import AgentName
from imbue.mng.primitives import ProviderInstanceName
from imbue.mng_kanpan.data_types import AgentBoardEntry
from imbue.mng_kanpan.data_types import BoardSection
from imbue.mng_kanpan.data_types import BoardSnapshot
from imbue.mng_kanpan.data_types import CheckStatus
from imbue.mng_kanpan.data_types import PendingMark
from imbue.mng_kanpan.data_types import PrInfo
from imbue.mng_kanpan.data_types import PrState
from imbue.mng_kanpan.tui import _KanpanState
from imbue.mng_kanpan.tui import _advance_focus
from imbue.mng_kanpan.tui import _build_board_widgets
from imbue.mng_kanpan.tui import _classify_entry
from imbue.mng_kanpan.tui import _format_agent_line
from imbue.mng_kanpan.tui import _is_safe_to_delete
from imbue.mng_kanpan.tui import _toggle_mark
from imbue.mng_kanpan.tui import _unmark_all
from imbue.mng_kanpan.tui import _unmark_focused


def _make_entry(
    name: str = "agent-1",
    state: AgentLifecycleState = AgentLifecycleState.RUNNING,
    pr_state: PrState | None = None,
    work_dir: Path | None = None,
    is_muted: bool = False,
) -> AgentBoardEntry:
    """Create an AgentBoardEntry for testing."""
    pr = None
    if pr_state is not None:
        pr = PrInfo(
            number=1,
            title="test",
            state=pr_state,
            url="https://github.com/org/repo/pull/1",
            head_branch="mng/test",
            check_status=CheckStatus.PASSING,
            is_draft=False,
        )
    return AgentBoardEntry(
        name=AgentName(name),
        state=state,
        provider_name=ProviderInstanceName("local"),
        work_dir=work_dir,
        pr=pr,
        is_muted=is_muted,
    )


def _make_state(entries: tuple[AgentBoardEntry, ...] = ()) -> _KanpanState:
    """Create a minimal _KanpanState for testing pure functions."""
    snapshot = BoardSnapshot(entries=entries, fetch_time_seconds=0.1) if entries else None
    frame = MagicMock()
    footer_left_text = MagicMock()
    footer_left_attr = MagicMock()
    footer_right = MagicMock()
    # Use model_construct to bypass MngContext validation (we don't need a real one)
    state = _KanpanState.model_construct(
        mng_ctx=MagicMock(),
        frame=frame,
        footer_left_text=footer_left_text,
        footer_left_attr=footer_left_attr,
        footer_right=footer_right,
        snapshot=snapshot,
        spinner_index=0,
        marks={},
        pending_confirm_deletes=(),
        executing=False,
        execute_status="",
        index_to_entry={},
        list_walker=None,
        focused_agent_name=None,
        steady_footer_text="  Loading...",
        commands={},
        loop=None,
        refresh_future=None,
        executor=None,
    )
    if snapshot is not None:
        walker = _build_board_widgets(state)
        state.list_walker = walker
        frame.body = MagicMock()
    return state


# --- _classify_entry ---


def test_classify_entry_no_pr() -> None:
    entry = _make_entry()
    assert _classify_entry(entry) == BoardSection.STILL_COOKING


def test_classify_entry_merged_pr() -> None:
    entry = _make_entry(pr_state=PrState.MERGED)
    assert _classify_entry(entry) == BoardSection.PR_MERGED


def test_classify_entry_closed_pr() -> None:
    entry = _make_entry(pr_state=PrState.CLOSED)
    assert _classify_entry(entry) == BoardSection.PR_CLOSED


def test_classify_entry_open_pr() -> None:
    entry = _make_entry(pr_state=PrState.OPEN)
    assert _classify_entry(entry) == BoardSection.PR_BEING_REVIEWED


def test_classify_entry_muted_overrides_pr_state() -> None:
    entry = _make_entry(pr_state=PrState.OPEN, is_muted=True)
    assert _classify_entry(entry) == BoardSection.MUTED


# --- _is_safe_to_delete ---


def test_is_safe_to_delete_merged_pr() -> None:
    entry = _make_entry(pr_state=PrState.MERGED)
    assert _is_safe_to_delete(entry) is True


def test_is_safe_to_delete_open_pr() -> None:
    entry = _make_entry(pr_state=PrState.OPEN)
    assert _is_safe_to_delete(entry) is False


def test_is_safe_to_delete_no_pr() -> None:
    entry = _make_entry()
    assert _is_safe_to_delete(entry) is False


# --- _format_agent_line with marks ---


def test_format_agent_line_no_mark() -> None:
    entry = _make_entry()
    parts = _format_agent_line(entry, BoardSection.STILL_COOKING)
    text = "".join(seg if isinstance(seg, str) else seg[1] for seg in parts)
    assert text.startswith("  agent-1")


def test_format_agent_line_delete_mark() -> None:
    entry = _make_entry()
    parts = _format_agent_line(entry, BoardSection.STILL_COOKING, mark=PendingMark.DELETE)
    # First part should be the mark indicator tuple
    assert parts[0] == ("mark_delete", "D")
    text = "".join(seg if isinstance(seg, str) else seg[1] for seg in parts)
    assert "agent-1" in text


def test_format_agent_line_push_mark() -> None:
    entry = _make_entry(work_dir=Path("/tmp/work"))
    parts = _format_agent_line(entry, BoardSection.STILL_COOKING, mark=PendingMark.PUSH)
    assert parts[0] == ("mark_push", "P")


def test_format_agent_line_muted_with_mark_flattens_to_gray() -> None:
    entry = _make_entry(is_muted=True)
    parts = _format_agent_line(entry, BoardSection.MUTED, mark=PendingMark.DELETE)
    # Muted section flattens everything to gray
    assert len(parts) == 1
    assert parts[0][0] == "muted"


# --- _toggle_mark ---


def test_toggle_mark_adds_mark() -> None:
    entry = _make_entry()
    state = _make_state(entries=(entry,))
    # Focus the first selectable entry
    first_idx = min(state.index_to_entry.keys())
    state.list_walker.set_focus(first_idx)

    _toggle_mark(state, PendingMark.DELETE)
    assert state.marks == {AgentName("agent-1"): PendingMark.DELETE}


def test_toggle_mark_removes_same_mark() -> None:
    entry = _make_entry()
    state = _make_state(entries=(entry,))
    first_idx = min(state.index_to_entry.keys())
    state.list_walker.set_focus(first_idx)

    state.marks[AgentName("agent-1")] = PendingMark.DELETE
    _toggle_mark(state, PendingMark.DELETE)
    assert AgentName("agent-1") not in state.marks


def test_toggle_mark_replaces_different_mark() -> None:
    entry = _make_entry(work_dir=Path("/tmp/work"))
    state = _make_state(entries=(entry,))
    first_idx = min(state.index_to_entry.keys())
    state.list_walker.set_focus(first_idx)

    state.marks[AgentName("agent-1")] = PendingMark.DELETE
    _toggle_mark(state, PendingMark.PUSH)
    assert state.marks[AgentName("agent-1")] == PendingMark.PUSH


def test_toggle_push_mark_rejected_without_work_dir() -> None:
    entry = _make_entry()  # no work_dir
    state = _make_state(entries=(entry,))
    first_idx = min(state.index_to_entry.keys())
    state.list_walker.set_focus(first_idx)

    _toggle_mark(state, PendingMark.PUSH)
    assert AgentName("agent-1") not in state.marks


# --- _unmark_focused ---


def test_unmark_focused_removes_mark() -> None:
    entry = _make_entry()
    state = _make_state(entries=(entry,))
    first_idx = min(state.index_to_entry.keys())
    state.list_walker.set_focus(first_idx)
    state.marks[AgentName("agent-1")] = PendingMark.DELETE

    _unmark_focused(state)
    assert AgentName("agent-1") not in state.marks


def test_unmark_focused_noop_without_mark() -> None:
    entry = _make_entry()
    state = _make_state(entries=(entry,))
    first_idx = min(state.index_to_entry.keys())
    state.list_walker.set_focus(first_idx)

    _unmark_focused(state)  # should not error
    assert state.marks == {}


# --- _unmark_all ---


def test_unmark_all_clears_all_marks() -> None:
    e1 = _make_entry(name="agent-1")
    e2 = _make_entry(name="agent-2")
    state = _make_state(entries=(e1, e2))
    state.marks[AgentName("agent-1")] = PendingMark.DELETE
    state.marks[AgentName("agent-2")] = PendingMark.PUSH

    _unmark_all(state)
    assert state.marks == {}


def test_unmark_all_noop_when_empty() -> None:
    state = _make_state(entries=(_make_entry(),))
    _unmark_all(state)  # should not error
    assert state.marks == {}


# --- _advance_focus ---


def test_advance_focus_moves_to_next_agent() -> None:
    e1 = _make_entry(name="agent-1")
    e2 = _make_entry(name="agent-2")
    state = _make_state(entries=(e1, e2))

    sorted_indices = sorted(state.index_to_entry.keys())
    state.list_walker.set_focus(sorted_indices[0])

    _advance_focus(state)

    _, new_focus = state.list_walker.get_focus()
    assert new_focus == sorted_indices[1]


def test_advance_focus_stays_at_last_agent() -> None:
    entry = _make_entry()
    state = _make_state(entries=(entry,))
    first_idx = min(state.index_to_entry.keys())
    state.list_walker.set_focus(first_idx)

    _advance_focus(state)

    _, new_focus = state.list_walker.get_focus()
    assert new_focus == first_idx  # didn't move, only one agent


# --- _build_board_widgets with marks ---


def test_build_board_widgets_shows_mark_indicator() -> None:
    entry = _make_entry()
    state = _make_state(entries=(entry,))
    state.marks[AgentName("agent-1")] = PendingMark.DELETE

    walker = _build_board_widgets(state)

    # Find the selectable widget (agent line)
    agent_idx = min(state.index_to_entry.keys())
    widget = walker[agent_idx]
    # The inner widget is a _SelectableText wrapped in AttrMap
    inner_text = widget.original_widget  # type: ignore[union-attr]
    markup = inner_text.text
    # The markup should contain the D mark indicator
    flat = "".join(seg if isinstance(seg, str) else seg[1] for seg in markup)
    assert flat.startswith("D")

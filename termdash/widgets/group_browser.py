"""Favorites and groups sidebar widget."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Label, ListItem, ListView

from ..models import Favorite, Group


class GroupBrowser(Vertical):
    """Sidebar showing saved favorites and groups."""

    _refresh_seq: int = 0  # avoids DOM ID collisions during async clear

    class FavoriteSelected(Message):
        def __init__(self, favorite_id: int) -> None:
            super().__init__()
            self.favorite_id = favorite_id

    class GroupSelected(Message):
        def __init__(self, group_id: int) -> None:
            super().__init__()
            self.group_id = group_id

    class FavoriteDeleteRequested(Message):
        def __init__(self, favorite_id: int) -> None:
            super().__init__()
            self.favorite_id = favorite_id

    def compose(self) -> ComposeResult:
        yield Label("Favorites", classes="section-title")
        yield ListView(id="fav-list")
        yield Label("Groups", classes="section-title")
        yield ListView(id="group-list")

    def refresh_data(self, favorites: list[Favorite], groups: list[Group]):
        """Reload the favorites and groups lists."""
        self._refresh_seq += 1
        seq = self._refresh_seq

        fav_list = self.query_one("#fav-list", ListView)
        fav_list.clear()
        for fav in favorites:
            fav_list.append(ListItem(Label(f"* {fav.label}"), id=f"fav-{fav.id}-{seq}"))

        group_list = self.query_one("#group-list", ListView)
        group_list.clear()
        for group in groups:
            group_list.append(ListItem(Label(f"# {group.name}"), id=f"grp-{group.id}-{seq}"))

    def get_selected_favorite_id(self) -> int | None:
        """Return the favorite ID of the highlighted sidebar item, or None."""
        fav_list = self.query_one("#fav-list", ListView)
        if fav_list.highlighted_child is not None:
            item_id = fav_list.highlighted_child.id or ""
            if item_id.startswith("fav-"):
                return int(item_id.split("-")[1])
        return None

    def request_delete_selected(self):
        """Post a delete request for the currently highlighted favorite."""
        fav_id = self.get_selected_favorite_id()
        if fav_id is not None:
            self.post_message(self.FavoriteDeleteRequested(fav_id))

    def on_list_view_selected(self, event: ListView.Selected):
        item_id = event.item.id or ""
        if item_id.startswith("fav-"):
            # id format: fav-{id}-{seq}
            fav_id = int(item_id.split("-")[1])
            self.post_message(self.FavoriteSelected(fav_id))
        elif item_id.startswith("grp-"):
            group_id = int(item_id.split("-")[1])
            self.post_message(self.GroupSelected(group_id))

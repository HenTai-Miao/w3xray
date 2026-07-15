"""Map and campaign source browser behavior."""

from __future__ import annotations

import glob
import os
from tkinter import filedialog

from .api import quick_map_name
from .gui_worker_registry import GuiWorkerTicket
from .map_directory import scan_battle_maps
from .map_gallery import MapEntry, render_map_gallery


class SourceBrowserMixin:
    """Manage the global left source panel."""

    def on_pick_dir(self) -> None:
        kind = "战役" if self.mode == "campaign" else "对战图"
        directory = filedialog.askdirectory(title=f"选择存放{kind}的目录")
        if not directory:
            return
        self._cur_dir[self.mode] = directory
        self._save_config(**{f"last_dir_{self.mode}": directory})
        self._scan_dir(directory, self.mode)

    def on_refresh_dir(self) -> None:
        directory = self._cur_dir.get(self.mode) or self._load_config().get(
            f"last_dir_{self.mode}"
        )
        if directory and os.path.isdir(directory):
            self._scan_dir(directory, self.mode)
        else:
            self.status.configure(text="还没选过目录，先点「选择地图目录」")

    def _scan_dir(self, directory: str, mode: str) -> None:
        self._cur_dir[mode] = directory
        self.status.configure(text="正在扫描目录 …")
        self.update_idletasks()

        def work(ticket: GuiWorkerTicket) -> None:
            if mode == "campaign":
                files = glob.glob(
                    os.path.join(directory, "**", "*.w3n"), recursive=True
                )
                files = sorted(
                    set(files), key=lambda path: os.path.getmtime(path), reverse=True
                )
                items = [
                    {
                        "path": path,
                        "name": os.path.basename(path),
                        "loaded": False,
                        "views": None,
                    }
                    for path in files
                ]
                _ = self._post_gui_worker(
                    ticket,
                    lambda: self._fill_campaign(items),
                )
            else:
                items = scan_battle_maps(directory)
                _ = self._post_gui_worker(
                    ticket,
                    lambda: self._fill_battle(items),
                )

        _ = self._start_gui_worker("source-scan", work, replace=True)

    def _fill_battle(self, items) -> None:
        self._dir_maps = items
        if self.mode == "battle":
            self._populate_left()
        self.status.configure(text=f"对战图目录：找到 {len(items)} 张")

    def _fill_campaign(self, items) -> None:
        self._dir_campaigns = items
        if self.mode == "campaign":
            self._populate_left()
        self.status.configure(
            text=f"战役目录：找到 {len(items)} 个（点战役展开看子地图）"
        )

    def _populate_left(self) -> None:
        if not self.left_brow.winfo_manager():
            self.left_brow.pack(fill="x", padx=8, pady=(8, 4), before=self.left_title)
        if self.mode == "campaign":
            self.left_title.configure(text="战役列表")
            self._refresh_campaign_tree()
        else:
            self.left_title.configure(text="地图列表")
            self._refresh_left_list()

    def _refresh_left_list(self) -> None:
        query = (
            self.map_search.get().strip().lower() if hasattr(self, "map_search") else ""
        )
        self._node_map = {}
        entries = []
        self.map_list.delete(*self.map_list.get_children())
        for index, (path, name) in enumerate(self._dir_maps):
            if query and query not in name.lower():
                continue
            iid = f"m{index}"
            self.map_list.insert("", "end", iid=iid, text=f" {name}")
            self._node_map[iid] = ("path", path)
            entries.append(
                MapEntry(
                    iid=iid,
                    title=name,
                    subtitle=os.path.basename(path),
                    action="打开地图",
                )
            )
        self._autosize_tree(self.map_list, minw=130)
        self._map_gallery_entries = entries
        self._render_map_gallery()

    def _refresh_campaign_tree(self) -> None:
        query = (
            self.map_search.get().strip().lower() if hasattr(self, "map_search") else ""
        )
        self._node_map = {}
        entries = []
        self.map_list.delete(*self.map_list.get_children())
        for index, campaign in enumerate(self._dir_campaigns):
            if query and query not in campaign["name"].lower():
                continue
            parent_id = f"c{index}"
            self.map_list.insert(
                "",
                "end",
                iid=parent_id,
                text=f" {campaign['name']}",
                open=bool(campaign["loaded"]),
            )
            self._node_map[parent_id] = ("campaign", index)
            action = "查看子图" if campaign["loaded"] else "加载战役"
            entries.append(
                MapEntry(
                    iid=parent_id,
                    title=campaign["name"],
                    subtitle="战役图 · 共享对象与关卡子图",
                    action=action,
                )
            )
            self._append_campaign_children(parent_id, campaign, entries)
        self._autosize_tree(self.map_list, minw=130)
        self._map_gallery_entries = entries
        self._render_map_gallery()

    def _append_campaign_children(self, parent_id: str, campaign, entries) -> None:
        if campaign["loaded"] and campaign["views"]:
            for index, (label, md) in enumerate(campaign["views"]):
                child_id = f"{parent_id}_s{index}"
                self.map_list.insert(parent_id, "end", iid=child_id, text=f" {label}")
                self._node_map[child_id] = ("md", md)
                entries.append(
                    MapEntry(
                        iid=child_id,
                        title=label,
                        subtitle=md.name,
                        action="切换子图",
                        depth=1,
                    )
                )
        else:
            self.map_list.insert(
                parent_id, "end", iid=f"{parent_id}_load", text="  （展开加载…）"
            )

    def _render_map_gallery(self) -> None:
        if not hasattr(self, "map_gallery"):
            return
        render_map_gallery(self.map_gallery, self._map_gallery_entries, self._open_node)

    def _on_mode_change(self, mode: str) -> None:
        self.mode = "campaign" if mode == "战役图" else "battle"
        self.map_search.set("")
        self._populate_left()

    def _on_tree_open(self, _event) -> None:
        selected = self.map_list.focus()
        info = self._node_map.get(selected)
        if info and info[0] == "campaign":
            index = info[1]
            if not self._dir_campaigns[index]["loaded"]:
                self._load_campaign_node(index)

    def _load_campaign_node(self, index: int) -> None:
        self._start_campaign_load(index)

    def _open_node(self, node_id: str) -> None:
        info = self._node_map.get(node_id)
        if not info:
            return
        kind, payload = info
        if kind == "path":
            self._start_path_load(payload)
        elif kind == "md":
            self._campaign_path = next(
                (
                    campaign["path"]
                    for campaign in self._dir_campaigns
                    if campaign["views"]
                    and any(md is payload for _, md in campaign["views"])
                ),
                None,
            )
            self._start_map_switch(payload, self._campaign_path)
        elif kind == "campaign" and not self._dir_campaigns[payload]["loaded"]:
            self._load_campaign_node(payload)

    def _on_map_pick(self, _event) -> None:
        selected = self.map_list.selection()
        if selected:
            self._open_node(selected[0])

    def _set_campaign_views(self, views, path=None) -> None:
        self._campaign_views = views
        self._campaign_path = path
        if views:
            name = quick_map_name(path) if path else "战役"
            entry = next(
                (
                    campaign
                    for campaign in self._dir_campaigns
                    if campaign["path"] == path
                ),
                None,
            )
            if entry:
                entry["loaded"] = True
                entry["views"] = views
            else:
                self._dir_campaigns.insert(
                    0, {"path": path, "name": name, "loaded": True, "views": views}
                )
            self.mode = "campaign"
            self.mode_seg.set("战役图")
        self._populate_left()

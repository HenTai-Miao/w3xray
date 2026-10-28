"""Cancel only timers whose Tcl command belongs to a retiring widget tree."""

from __future__ import annotations

import tkinter as tk


def cancel_widget_callbacks(widget: tk.Misc) -> tuple[str, ...]:
    """Retire owned ``after`` scripts before Tk deletes their commands.

    CTk schedules several titlebar/scaling callbacks without retaining timer
    IDs. Tk removes a destroyed widget's registered Tcl commands but leaves
    those timers queued. Match exact command identities, including child
    widgets, while keeping timers owned by the parent or another window.
    Cancellation uses the command's actual owner so its ``_tclCommands`` list
    stays consistent when Tk subsequently destroys every child.
    """
    owners: dict[str, tk.Misc] = {}
    pending = [widget]
    while pending:
        current = pending.pop()
        commands = getattr(current, "_tclCommands", None)
        if isinstance(commands, (tuple, list)):
            owners.update(
                (command, current) for command in commands if isinstance(command, str)
            )
        try:
            pending.extend(current.winfo_children())
        except tk.TclError:
            continue  # An ancestor teardown may have already removed this child.
    cancelled: list[str] = []
    try:
        queued = widget.tk.splitlist(widget.tk.call("after", "info"))
    except tk.TclError:
        return ()
    for identifier in queued:
        try:
            info = widget.tk.splitlist(widget.tk.call("after", "info", identifier))
            command = widget.tk.splitlist(info[0]) if info else ()
            owner = owners.get(str(command[0])) if command else None
            if owner is not None:
                owner.after_cancel(str(identifier))
                cancelled.append(str(identifier))
        except tk.TclError:
            continue  # A timer may have completed since the queue snapshot.
    return tuple(cancelled)

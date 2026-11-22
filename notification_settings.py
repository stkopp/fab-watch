import tkinter as tk
from tkinter import ttk, messagebox
from notification_policy import policies, LABELS, popout_layout
from appearance import BG, TEXT, MUTED, FONT

MODES = {"Popout": "popout", "Windows notifications": "windows", "None": "none"}
MINUTES = ("5", "10", "15", "30", "60", "120", "240", "720", "1440", "10080")


def open_settings(parent, config, on_save):
    window = tk.Toplevel(parent)
    window.title("Notification settings")
    window.configure(bg=BG)
    window.resizable(False, False)
    window.transient(parent)
    frame = tk.Frame(window, bg=BG, padx=22, pady=18)
    frame.pack(fill="both", expand=True)
    def label(text, row, col, **opts):
        widget = tk.Label(frame, text=text, bg=BG, fg=TEXT, font=(FONT, 10), **opts)
        widget.grid(row=row, column=col, sticky="w", padx=(0, 12), pady=7)
        return widget
    for col, title in enumerate(("Event", "Check every (min)", "Repeat every (min)", "Notification type")):
        label(title, 0, col)
    fields = {}
    for row, (kind, policy) in enumerate(policies(config).items(), 1):
        label(LABELS[kind], row, 0)
        if "check" in policy:
            check = ttk.Combobox(frame, width=17, values=("None", *MINUTES))
            check.set(str(policy["check"]) if policy["check"] else "None")
            check.grid(row=row, column=1, padx=(0, 12))
        else:
            check = None
            label("Seller interval", row, 1)
        repeat = ttk.Combobox(frame, width=18, values=("Once", *MINUTES))
        repeat.set(str(policy["repeat"]) if policy["repeat"] else "Once")
        repeat.grid(row=row, column=2, padx=(0, 12))
        mode = ttk.Combobox(frame, state="readonly", width=23, values=list(MODES))
        mode.set(next(k for k, v in MODES.items() if v == policy["mode"]))
        mode.grid(row=row, column=3)
        fields[kind] = check, repeat, mode
    layouts = {"Show one at a time": "sequential", "Group in one window": "grouped"}
    label("Multiple popouts", 8, 0)
    layout = ttk.Combobox(frame, state="readonly", values=list(layouts), width=25)
    layout.set(next(name for name, value in layouts.items() if value == popout_layout(config)))
    layout.grid(row=8, column=1, columnspan=3, sticky="w")
    text = ("Check intervals control when new items are found. Repeat intervals apply to unread items.\n"
            "Use Mark as read to stop reminders. Once shows the item once.\n"
            "Choose None to mute a channel or stop checking an engine type.\n"
            "Enter an interval of 5–10080 minutes.")
    tk.Label(frame, text=text, bg=BG, fg=MUTED, justify="left", font=(FONT, 9)).grid(
        row=9, column=0, columnspan=4, sticky="w", pady=(16, 12))
    def save():
        try:
            values = {}
            for kind, (check, repeat, mode) in fields.items():
                values[kind] = {"mode": MODES[mode.get()],
                                "repeat": None if repeat.get() == "Once" else int(repeat.get())}
                if check:
                    values[kind]["check"] = None if check.get() == "None" else int(check.get())
            validated = policies({"notifications": values})
        except (ValueError, KeyError) as exc:
            messagebox.showerror("Notification settings", str(exc), parent=window)
            return
        on_save({"notifications": validated, "popout_layout": layouts[layout.get()]})
        window.destroy()
    ttk.Button(frame, text="Save", style="Accent.TButton", command=save).grid(row=10, column=3, sticky="e")
    ttk.Button(frame, text="Cancel", command=window.destroy).grid(row=10, column=2, sticky="e", padx=12)
    window.update_idletasks()
    x = max(0, parent.winfo_rootx() + (parent.winfo_width() - window.winfo_reqwidth()) // 2)
    y = max(0, parent.winfo_rooty() + (parent.winfo_height() - window.winfo_reqheight()) // 2)
    window.geometry(f"+{x}+{y}")
    window.grab_set()
    return window

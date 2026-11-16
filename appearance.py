from pathlib import Path
import ctypes
import tkinter as tk
from tkinter import ttk

ASSETS = Path(__file__).resolve().parent
BG, PANEL, EDGE = "#17171c", "#222228", "#393841"
TEXT, MUTED, ACCENT, SELECT = "#f6f3fd", "#b5b1c1", "#c4aaff", "#4d3569"
RAISED, HOVER, PRESSED = "#2b2932", "#41364f", "#524064"
FONT = "Segoe UI"


def theme(root):
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("FabWatch.Desktop")
    root.configure(bg=BG)
    root.fab_icon = tk.PhotoImage(file=ASSETS / "fab-watch.png", master=root)
    root.iconphoto(True, root.fab_icon)
    root.iconbitmap(default=str(ASSETS / "fab-watch.ico"))
    root.iconbitmap(str(ASSETS / "fab-watch.ico"))
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", background=PANEL, foreground=TEXT, fieldbackground=PANEL, bordercolor=EDGE,
                    lightcolor=EDGE, darkcolor=EDGE, font=(FONT, 10), focuscolor=ACCENT)
    style.configure("TButton", padding=(12, 7), background=RAISED)
    style.map("TButton", background=[("disabled", PANEL), ("pressed", PRESSED), ("active", HOVER)],
              foreground=[("disabled", "#858090"), ("!disabled", TEXT)])
    style.configure("Accent.TButton", background="#a875f6", foreground="#170c26", font=(FONT, 10, "bold"))
    style.map("Accent.TButton", background=[("disabled", PANEL), ("pressed", "#c29afc"), ("active", "#bf9aff")],
              foreground=[("disabled", "#858090"), ("!disabled", "#170c26")])
    style.configure("TEntry", padding=8, insertcolor=TEXT, fieldbackground=BG)
    style.configure("TCheckbutton", background=PANEL, foreground=TEXT, padding=(0, 2))
    style.map("TCheckbutton", background=[("active", PANEL)],
              foreground=[("disabled", MUTED), ("!disabled", TEXT)],
              indicatorbackground=[("selected", ACCENT), ("!selected", BG)],
              indicatorforeground=[("selected", BG)])
    style.map("TEntry", bordercolor=[("focus", ACCENT)])
    style.configure("TCombobox", padding=6, arrowcolor=ACCENT)
    style.map("TCombobox", background=[("active", HOVER), ("readonly", RAISED)],
              fieldbackground=[("readonly", RAISED)], foreground=[("readonly", TEXT)],
              selectbackground=[("readonly", RAISED)], selectforeground=[("readonly", TEXT)])
    style.configure("Treeview", rowheight=33, borderwidth=1, background=PANEL, fieldbackground=PANEL)
    style.configure("Treeview.Heading", padding=8, background=RAISED, foreground=TEXT, relief="flat",
                    font=(FONT, 10, "bold"))
    style.map("Treeview.Heading", background=[("pressed", PRESSED), ("active", HOVER)],
              foreground=[("pressed", TEXT), ("active", TEXT)])
    style.map("Treeview", background=[("selected", SELECT)], foreground=[("selected", TEXT)])
    style.configure("TNotebook", background=BG, bordercolor=EDGE, padding=0)
    style.configure("TNotebook.Tab", background=RAISED, foreground=MUTED, padding=(14, 7))
    style.map("TNotebook.Tab", background=[("selected", SELECT), ("active", HOVER)],
              foreground=[("selected", TEXT), ("active", TEXT)])
    style.configure("Vertical.TScrollbar", background=EDGE, troughcolor=BG, arrowcolor=MUTED)
    style.map("Vertical.TScrollbar", background=[("active", PRESSED)])
    root.option_add("*TCombobox*Listbox.background", RAISED)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", SELECT)
    root.option_add("*TCombobox*Listbox.selectForeground", TEXT)

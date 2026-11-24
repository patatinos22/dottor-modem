import tkinter as tk
from ui.dashboard import DottorModemApp, enable_high_dpi


def main() -> None:
    enable_high_dpi()
    root = tk.Tk()
    DottorModemApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

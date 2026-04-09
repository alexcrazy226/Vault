import tkinter as tk

from vault_app.ui.app import PasswordManagerApp


def main() -> None:
    root = tk.Tk()
    PasswordManagerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

"""Entrada do aplicativo desktop."""
import logging
from pathlib import Path
import tkinter as tk
from tkinter import messagebox


def main():
    base = Path(__file__).resolve().parent
    logs = base / "logs"
    logs.mkdir(exist_ok=True)
    logging.basicConfig(filename=logs / "app.log", level=logging.WARNING, encoding="utf-8", format="%(asctime)s %(levelname)s %(message)s")
    root = tk.Tk()
    root.withdraw()
    try:
        from pontos_autocad.ui import App
        App(root)
    except Exception as exc:
        logging.exception("Falha na inicialização")
        messagebox.showerror("Pontos AutoCAD", f"Não foi possível iniciar o aplicativo.\n\n{exc}\n\nExecute Instalar.bat para preparar as bibliotecas.")
        root.destroy()
        return
    def callback_error(exc_type, exc_value, traceback):
        logging.error("Falha da interface", exc_info=(exc_type, exc_value, traceback))
        messagebox.showerror("Operação não concluída", str(exc_value))
    root.report_callback_exception = callback_error
    root.deiconify()
    root.mainloop()


if __name__ == "__main__":
    main()

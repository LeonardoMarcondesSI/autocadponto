from __future__ import annotations

import json
import math
import queue
import threading
import tkinter as tk
from collections import Counter
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from .core import Check, Point, azimuth, checks_csv, compare, export_files, normal_id, number, parse_memorial, validate
from .reader import Reader
from .geometry import contour_measures
from .conference import verify_documents, contour_issues, order_by_destinations, code_suggestions
from .georef import GeoReference, utm_reference
from .memorial import geographic

BASE = Path(__file__).resolve().parent.parent
BLUE = "#17434a"
BG = "#f3f6f7"


def fmt(value, digits=2):
    return "" if value is None else f"{value:.{digits}f}".replace(".", ",")


def fmt_measure(value, digits=2):
    return f"{value:,.{digits}f}".translate(str.maketrans({",": ".", ".": ","}))


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.points: list[Point] = []
        self.memorial: list[Point] = []
        self.table_warnings: list[str] = []
        self.memorial_warnings: list[str] = []
        self.checks: list[Check] = []
        self.reader = Reader()
        self.events = queue.Queue()
        self.busy = False
        self.dirty = False
        self.memorial_stale = False
        self.preview = None
        self.photo = None
        self.photo_scale = 1.0
        self.source_images = {}
        self.georef = GeoReference()
        self.status = tk.StringVar(value="Abra uma foto, PDF ou lista de coordenadas para começar.")
        self.reviewed = tk.BooleanVar(value=False)
        self.contour = tk.BooleanVar(value=True)
        self.close_contour = tk.BooleanVar(value=True)
        self.rotation = tk.StringVar(value="Automática")
        self.coord_tol = tk.StringVar(value="0,02")
        self.dist_tol = tk.StringVar(value="0,05")
        self.az_tol = tk.StringVar(value="1")
        self.area_tol = tk.StringVar(value="1,00")
        self.perimeter_tol = tk.StringVar(value="0,10")
        self.declared_area = tk.StringVar()
        self.declared_perimeter = tk.StringVar()
        self.measurement_mode = tk.StringVar(value="Não informado")
        self.reference_label = tk.StringVar(value="Latitude/longitude: referência não informada")
        self.totals_summary = tk.StringVar(value="Área e perímetro: carregue a planta e o memorial.")
        self.mem_rotation = tk.StringVar(value="Automática")
        self.point_count = tk.StringVar(value="Nenhum ponto")
        self.area_summary = tk.StringVar(value="Área total: —")
        self.perimeter_summary = tk.StringVar(value="Perímetro: —")
        self.measure_note = tk.StringVar(value="Importe os pontos para calcular as medidas.")
        self.mem_count = tk.StringVar(value="Nenhum vértice interpretado")
        self.report_summary = tk.StringVar(value="A conferência usa as coordenadas E/N em metros e os trechos declarados.")
        self.root.title("Pontos AutoCAD · Leitura e conferência 2D")
        self.root.geometry("1360x850")
        self.root.minsize(1060, 720)
        self.root.configure(bg=BG)
        self.root.protocol("WM_DELETE_WINDOW", self.quit)
        self.style()
        self.build()
        for var in (self.coord_tol, self.dist_tol, self.az_tol, self.area_tol, self.perimeter_tol, self.declared_area, self.declared_perimeter, self.measurement_mode):
            var.trace_add("write", lambda *_: self.changed(table=False))
        self.contour.trace_add("write", lambda *_: self.options_changed())
        self.close_contour.trace_add("write", lambda *_: self.options_changed())
        self.root.after(100, self.poll)

    def style(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", font=("Segoe UI", 10), background=BG)
        style.configure("TButton", padding=(10, 7))
        style.configure("Accent.TButton", background=BLUE, foreground="white")
        style.map("Accent.TButton", background=[("active", "#28646c")])
        style.configure("Treeview", rowheight=28, background="white", fieldbackground="white")
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"), padding=6)
        style.configure("TNotebook.Tab", padding=(16, 9))
        style.configure("Title.TLabel", font=("Segoe UI", 20, "bold"), foreground=BLUE)
        style.configure("Sub.TLabel", foreground="#536c74")

    def build(self):
        header = ttk.Frame(self.root, padding=(22, 16, 22, 10))
        header.pack(fill="x")
        ttk.Label(header, text="Pontos AutoCAD", style="Title.TLabel").pack(side="left")
        ttk.Label(header, text="FOTO → COORDENADAS → DESENHO 2D", style="Sub.TLabel").pack(side="left", padx=20)
        ttk.Button(header, text="Ajuda", command=self.help).pack(side="right")
        ttk.Button(header, text="Salvar projeto", command=self.save_project).pack(side="right", padx=6)
        ttk.Button(header, text="Abrir projeto", command=self.load_project).pack(side="right")
        self.tabs = ttk.Notebook(self.root)
        self.tabs.pack(fill="both", expand=True, padx=18)
        self.tab_table = ttk.Frame(self.tabs, padding=12)
        self.tab_mem = ttk.Frame(self.tabs, padding=12)
        self.tab_report = ttk.Frame(self.tabs, padding=12)
        for tab, label in ((self.tab_table, "1 · Tabela e contorno"), (self.tab_mem, "2 · Memorial"), (self.tab_report, "3 · Conferência")):
            self.tabs.add(tab, text=label)
        self.build_table()
        self.build_memorial()
        self.build_report()
        export = ttk.Frame(self.root, padding=(22, 12, 22, 4))
        export.pack(fill="x")
        ttk.Checkbutton(export, text="Conferi os valores, a quantidade e a ordem dos pontos", variable=self.reviewed).pack(side="left")
        ttk.Checkbutton(export, text="Gerar contorno", variable=self.contour).pack(side="left", padx=12)
        ttk.Checkbutton(export, text="Fechar contorno", variable=self.close_contour).pack(side="left")
        ttk.Button(export, text="Exportar para AutoCAD", style="Accent.TButton", command=self.export).pack(side="right")
        footer = ttk.Frame(self.root, padding=(22, 6, 22, 14))
        footer.pack(fill="x")
        self.progress = ttk.Progressbar(footer, mode="indeterminate", length=100)
        self.progress.pack(side="right", padx=8)
        ttk.Label(footer, textvariable=self.status, style="Sub.TLabel", wraplength=1020).pack(side="left")

    def build_table(self):
        toolbar = ttk.Frame(self.tab_table)
        toolbar.pack(fill="x", pady=(0, 10))
        ttk.Button(toolbar, text="Abrir foto / PDF / lista", style="Accent.TButton", command=self.import_table).pack(side="left")
        ttk.Label(toolbar, text="Orientação:").pack(side="left", padx=(12, 5))
        ttk.Combobox(toolbar, textvariable=self.rotation, values=["Automática", "0°", "90°", "180°", "270°"], state="readonly", width=12).pack(side="left")
        ttk.Label(toolbar, textvariable=self.point_count, style="Sub.TLabel").pack(side="right")
        pane = ttk.Panedwindow(self.tab_table, orient="horizontal")
        pane.pack(fill="both", expand=True)
        left, right = ttk.Frame(pane), ttk.Frame(pane)
        pane.add(left, weight=5)
        pane.add(right, weight=5)
        self.table_tree = self.point_tree(left)
        self.table_tree.bind("<Double-1>", lambda _: self.edit_point(False))
        self.table_tree.bind("<<TreeviewSelect>>", self.show_detail)
        actions = ttk.Frame(left)
        actions.pack(fill="x", pady=8)
        for title, callback in [("Adicionar", lambda: self.edit_point(False, True)), ("Editar", lambda: self.edit_point(False)), ("Remover", lambda: self.remove_point(False)), ("↑", lambda: self.move(-1)), ("↓", lambda: self.move(1)), ("Trocar E/N", self.swap_axes)]:
            ttk.Button(actions, text=title, command=callback).pack(side="left", padx=(0, 4))
        ttk.Button(left, text="Organizar contorno pelos destinos…", command=self.suggest_order).pack(anchor="w", pady=(0,6))
        self.detail = tk.Text(left, height=5, wrap="word", font=("Segoe UI", 9), relief="flat", background="#e8eef0")
        self.detail.pack(fill="x")
        self.detail.configure(state="disabled")
        preview_tabs = ttk.Notebook(right)
        preview_tabs.pack(fill="both", expand=True, padx=(10, 0))
        photo_frame, graph_frame = ttk.Frame(preview_tabs), ttk.Frame(preview_tabs)
        preview_tabs.add(photo_frame, text="Imagem da tabela")
        preview_tabs.add(graph_frame, text="Prévia do desenho")
        photo_bar = ttk.Frame(photo_frame)
        photo_bar.pack(fill="x")
        for label, command in [("Ajustar", lambda: self.zoom(0)), ("+", lambda: self.zoom(1.4)), ("−", lambda: self.zoom(1/1.4))]:
            ttk.Button(photo_bar, text=label, command=command).pack(side="left", padx=2, pady=4)
        ttk.Button(photo_bar, text="Ver linha selecionada", command=self.show_crop).pack(side="left", padx=4)
        area = ttk.Frame(photo_frame)
        area.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(area, background="#e3e9eb", highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        sy, sx = ttk.Scrollbar(area, orient="vertical", command=self.canvas.yview), ttk.Scrollbar(area, orient="horizontal", command=self.canvas.xview)
        sy.grid(row=0, column=1, sticky="ns")
        sx.grid(row=1, column=0, sticky="ew")
        self.canvas.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        area.rowconfigure(0, weight=1)
        area.columnconfigure(0, weight=1)
        self.canvas.bind("<Configure>", lambda _: self.draw_photo())
        self.graph = tk.Canvas(graph_frame, background="white", highlightthickness=0)
        self.graph.pack(fill="both", expand=True)
        self.graph.bind("<Configure>", lambda _: self.draw_graph())
        measures = ttk.Frame(graph_frame, padding=(14, 10))
        measures.pack(fill="x")
        ttk.Label(measures, textvariable=self.area_summary, font=("Segoe UI", 12, "bold"), foreground=BLUE).pack(anchor="w")
        ttk.Label(measures, textvariable=self.perimeter_summary, font=("Segoe UI", 12, "bold"), foreground=BLUE).pack(anchor="w", pady=(4, 0))
        note = ttk.Label(measures, textvariable=self.measure_note, style="Sub.TLabel", wraplength=420)
        note.pack(fill="x", pady=(6, 0))
        measures.bind("<Configure>", lambda event: note.configure(wraplength=max(180, event.width - 28)))
        ttk.Label(graph_frame, text="E/X horizontal · N/Y vertical · Z = 0 · ordem da tabela", style="Sub.TLabel").pack(pady=7)

    def point_tree(self, parent):
        area = ttk.Frame(parent)
        area.pack(fill="both", expand=True)
        tree = ttk.Treeview(area, columns=("id", "x", "y", "dest", "dist", "az", "state"), show="headings", selectmode="browse")
        for key, title, width in [("id", "Ponto", 115), ("x", "E / X (m)", 110), ("y", "N / Y (m)", 120), ("dest", "Destino", 110), ("dist", "Dist. (m)", 80), ("az", "Azimute (°)", 95), ("state", "Leitura", 100)]:
            tree.heading(key, text=title)
            tree.column(key, width=width, minwidth=65, stretch=False)
        tree.tag_configure("warn", background="#fff1d5")
        tree.grid(row=0, column=0, sticky="nsew")
        vs, hs = ttk.Scrollbar(area, orient="vertical", command=tree.yview), ttk.Scrollbar(area, orient="horizontal", command=tree.xview)
        vs.grid(row=0, column=1, sticky="ns")
        hs.grid(row=1, column=0, sticky="ew")
        tree.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        area.rowconfigure(0, weight=1)
        area.columnconfigure(0, weight=1)
        return tree

    def build_memorial(self):
        bar = ttk.Frame(self.tab_mem)
        bar.pack(fill="x", pady=(0, 10))
        ttk.Button(bar, text="Abrir páginas do memorial…", style="Accent.TButton", command=self.import_memorial).pack(side="left")
        ttk.Button(bar, text="Interpretar texto", command=self.interpret_memorial).pack(side="left", padx=8)
        ttk.Combobox(bar, textvariable=self.mem_rotation, values=["Automática", "0°", "90°", "180°", "270°"], state="readonly", width=12).pack(side="left")
        ttk.Label(bar, textvariable=self.mem_count, style="Sub.TLabel").pack(side="right")
        ttk.Label(self.tab_mem, text="Cole ou importe o memorial. Confira os vértices e os destinos encontrados; trechos não interpretados serão sinalizados.", wraplength=1100).pack(anchor="w", pady=(0, 8))
        totals = ttk.Frame(self.tab_mem)
        totals.pack(fill="x", pady=(0,8))
        for label,var in [('Área declarada (m²)',self.declared_area),('Perímetro declarado (m)',self.declared_perimeter)]:
            ttk.Label(totals,text=label).pack(side="left",padx=(0,5))
            ttk.Entry(totals,textvariable=var,width=16).pack(side="left",padx=(0,16))
        ttk.Label(totals,text="Extraídos do texto; podem ser corrigidos aqui.",style="Sub.TLabel").pack(side="left")
        pane = ttk.Panedwindow(self.tab_mem, orient="horizontal")
        pane.pack(fill="both", expand=True)
        text_frame, points_frame = ttk.Frame(pane), ttk.Frame(pane)
        pane.add(text_frame, weight=4)
        pane.add(points_frame, weight=6)
        self.mem_text = tk.Text(text_frame, wrap="word", font=("Segoe UI", 10), padx=10, pady=10, undo=True)
        sb = ttk.Scrollbar(text_frame, command=self.mem_text.yview)
        sb.pack(side="right", fill="y")
        self.mem_text.pack(fill="both", expand=True)
        self.mem_text.configure(yscrollcommand=sb.set)
        self.mem_text.bind("<<Modified>>", self.mem_text_changed)
        self.mem_tree = self.point_tree(points_frame)
        for key,label,width in [('lon','Longitude (°)',125),('lat','Latitude (°)',125)]:
            self.mem_tree.configure(columns=(*self.mem_tree['columns'],key))
            self.mem_tree.heading(key,text=label)
            self.mem_tree.column(key,width=width,stretch=False)
        self.mem_tree.bind("<Double-1>", lambda _: self.edit_point(True))
        actions = ttk.Frame(points_frame)
        actions.pack(fill="x", pady=8)
        for title, callback in [("Adicionar vértice", lambda: self.edit_point(True, True)), ("Editar", lambda: self.edit_point(True)), ("Remover", lambda: self.remove_point(True))]:
            ttk.Button(actions, text=title, command=callback).pack(side="left", padx=3)
        ttk.Button(points_frame,text='Revisar códigos semelhantes aos da planta…',command=self.review_codes).pack(anchor='w',pady=5)
        self.mem_notes = ttk.Label(points_frame, text="", wraplength=650, foreground="#875708")
        self.mem_notes.pack(fill="x", pady=5)

    def build_report(self):
        ttk.Label(self.tab_report,textvariable=self.totals_summary,font=("Segoe UI",12,"bold"),foreground=BLUE,wraplength=1150).pack(anchor="w",pady=(0,10))
        controls = ttk.Frame(self.tab_report)
        controls.pack(fill="x", pady=(0, 12))
        for label, variable in [("Posição (m)", self.coord_tol), ("Distância (m)", self.dist_tol), ("Azimute (minutos)", self.az_tol)]:
            ttk.Label(controls, text=label).pack(side="left", padx=(0, 5))
            ttk.Entry(controls, textvariable=variable, width=8).pack(side="left", padx=(0, 15))
        ttk.Button(controls, text="Conferir documentos", style="Accent.TButton", command=self.run_compare).pack(side="left")
        ttk.Button(controls, text="Salvar relatório CSV", command=self.export_report).pack(side="right")
        more = ttk.Frame(self.tab_report)
        more.pack(fill="x",pady=(0,8))
        for label,var in [('Tolerância de área (m²)',self.area_tol),('Perímetro (m)',self.perimeter_tol)]:
            ttk.Label(more,text=label).pack(side="left",padx=(0,5))
            ttk.Entry(more,textvariable=var,width=9).pack(side="left",padx=(0,14))
        ttk.Label(more,text="Trechos do memorial:").pack(side="left")
        ttk.Combobox(more,textvariable=self.measurement_mode,values=['Não informado','Grade da planta','Geodésico / terreno'],state='readonly',width=21).pack(side='left',padx=5)
        ref = ttk.Frame(self.tab_report)
        ref.pack(fill='x',pady=(0,8))
        ttk.Button(ref,text='Referência de coordenadas…',command=self.configure_reference).pack(side='left')
        ttk.Label(ref,textvariable=self.reference_label,style='Sub.TLabel').pack(side='left',padx=12)
        ttk.Label(self.tab_report, textvariable=self.report_summary, font=("Segoe UI", 11, "bold"), wraplength=1150).pack(anchor="w", pady=(0, 12))
        area = ttk.Frame(self.tab_report)
        area.pack(fill="both", expand=True)
        columns = ("status", "source", "item", "field", "reference", "calculated", "diff", "note")
        self.report_tree = ttk.Treeview(area, columns=columns, show="headings")
        for key, title, width in zip(columns, ["Situação", "Origem", "Ponto / trecho", "Campo", "Documento", "Calculado / tabela", "Diferença", "Observação"], [100, 85, 250, 130, 165, 180, 100, 280]):
            self.report_tree.heading(key, text=title)
            self.report_tree.column(key, width=width, stretch=False)
        for status, bg in [("DIVERGE", "#fde8e5"), ("CONFERE", "#e6f3ed"), ("PENDENTE", "#fff1d5")]:
            self.report_tree.tag_configure(status, background=bg)
        self.report_tree.grid(row=0, column=0, sticky="nsew")
        sy, sx = ttk.Scrollbar(area, command=self.report_tree.yview), ttk.Scrollbar(area, orient="horizontal", command=self.report_tree.xview)
        sy.grid(row=0, column=1, sticky="ns")
        sx.grid(row=1, column=0, sticky="ew")
        self.report_tree.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        area.rowconfigure(0, weight=1)
        area.columnconfigure(0, weight=1)
        ttk.Label(self.tab_report, text="Conferência numérica da planta e do memorial. Área e perímetro são planos, em E/N e metros. A conversão de latitude/longitude é opcional e exige a referência dos documentos. Azimutes e distâncias de terreno/geodésicos não são tratados como medidas de grade. As tolerâncias são definidas por você.", wraplength=1150, style="Sub.TLabel").pack(anchor="w", pady=(12, 0))

    def selected_rotation(self):
        return None if self.rotation.get() == "Automática" else int(self.rotation.get().replace("°", ""))

    def start_task(self, task, done):
        if self.busy:
            messagebox.showinfo("Leitura em andamento", "Aguarde a leitura atual terminar.")
            return
        self.busy = True
        self.progress.start(12)
        self.status.set("Preparando leitura local…")
        def worker():
            try:
                result = task(lambda text: self.events.put(("progress", text)))
                self.events.put(("done", (done, result)))
            except Exception as exc:
                import logging
                logging.exception("Falha de leitura")
                self.events.put(("error", str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "progress":
                    self.status.set(value)
                else:
                    self.busy = False
                    self.progress.stop()
                    if kind == "done":
                        done, result = value
                        done(result)
                    else:
                        self.status.set("A leitura não foi concluída.")
                        messagebox.showerror("Não foi possível ler", value)
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def guard(self):
        if self.busy:
            messagebox.showinfo("Aguarde", "A leitura está em andamento. Aguarde para alterar os dados.")
        return not self.busy

    def import_table(self):
        if not self.guard():
            return
        files = filedialog.askopenfilenames(title="Selecionar tabelas", initialdir=BASE, filetypes=[("Fotos, PDFs e listas", "*.jpg *.jpeg *.png *.bmp *.tif *.tiff *.webp *.pdf *.csv *.txt"), ("Todos os arquivos", "*")])
        if not files:
            return
        append = False
        if self.points:
            append = messagebox.askyesnocancel("Importar tabela", "Adicionar aos pontos existentes?\n\nSim: adicionar. Não: substituir a tabela atual.")
            if append is None:
                return
        rotation = self.selected_rotation()
        self.start_task(lambda progress: [self.reader.read_table(Path(f), rotation, progress) for f in files], lambda results: self.table_loaded(results, append))

    def table_loaded(self, results, append=False):
        if not any(result.parsed.points for result in results):
            messagebox.showwarning('Tabela não reconhecida','A leitura não encontrou pontos. A tabela atual foi mantida.')
            return
        if not append:
            self.points = []
            self.table_warnings = []
            self.source_images = {}
            self.preview = None
        for result in results:
            self.points += result.parsed.points
            self.table_warnings += result.parsed.warnings
            self.source_images.update(getattr(result,'pages',{}))
            if result.preview is not None:
                self.preview = result.preview
        self.photo_scale = 1.0
        self.changed()
        self.refresh()
        self.tabs.select(self.tab_table)
        self.status.set(f"{len(self.points)} pontos encontrados. Confira a foto e dê duplo clique em uma linha para corrigir.")
        if not self.points:
            messagebox.showwarning("Tabela não reconhecida", "\n".join(self.table_warnings[:6]))
        self.set_detail("\n".join(self.table_warnings))

    def import_memorial(self):
        if not self.guard():
            return
        files = filedialog.askopenfilenames(title="Selecionar páginas do memorial", initialdir=BASE, filetypes=[("Memorial", "*.pdf *.jpg *.jpeg *.png *.tif *.tiff *.txt *.csv"), ("Todos", "*")])
        if files:
            self.choose_page_order(list(files))

    def choose_page_order(self, files):
        dialog = tk.Toplevel(self.root)
        dialog.title('Ordem das páginas do memorial')
        dialog.transient(self.root)
        frame = ttk.Frame(dialog,padding=16)
        frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='Organize do início ao fim. Páginas de cada PDF seguem a ordem do arquivo.').pack(anchor='w')
        listing = tk.Listbox(frame,width=80,height=min(10,max(3,len(files))),exportselection=False)
        listing.pack(fill='both',expand=True,pady=10)
        def refresh(index=0):
            listing.delete(0,'end')
            for i,path in enumerate(files): listing.insert('end',f'{i+1}. {Path(path).name}')
            listing.selection_set(index)
        def move(delta):
            chosen=listing.curselection()
            if chosen and 0 <= chosen[0]+delta < len(files):
                i=chosen[0]
                files[i],files[i+delta]=files[i+delta],files[i]
                refresh(i+delta)
        def read():
            rotation=None if self.mem_rotation.get()=='Automática' else int(self.mem_rotation.get().replace('°',''))
            dialog.destroy()
            self.start_task(lambda progress: '\n\n'.join(self.reader.read_document(Path(path),rotation,progress) for path in files),self.memorial_loaded)
        actions=ttk.Frame(frame)
        actions.pack(fill='x')
        ttk.Button(actions,text='↑',command=lambda:move(-1)).pack(side='left')
        ttk.Button(actions,text='↓',command=lambda:move(1)).pack(side='left',padx=6)
        ttk.Button(actions,text='Ler nesta ordem',style='Accent.TButton',command=read).pack(side='right')
        refresh()
        dialog.grab_set()

    def memorial_loaded(self, text):
        self.mem_text.delete("1.0", "end")
        self.mem_text.insert("1.0", text)
        self.mem_text.edit_modified(False)
        self.interpret_memorial()
        self.tabs.select(self.tab_mem)

    def mem_text_changed(self, _=None):
        if self.mem_text.edit_modified():
            self.mem_text.edit_modified(False)
            self.memorial_stale = True
            self.mem_count.set("Texto alterado: clique em Interpretar texto")
            self.dirty = True
            self.invalidate_report()

    def interpret_memorial(self):
        if not self.guard():
            return
        result = parse_memorial(self.mem_text.get("1.0", "end-1c"))
        self.memorial = result.points
        self.memorial_warnings = result.warnings
        self.declared_area.set(fmt(result.area_m2,4))
        self.declared_perimeter.set(fmt(result.perimeter_m,4))
        self.memorial_stale = False
        self.changed(table=False)
        self.refresh()
        self.status.set(f"Memorial: {len(self.memorial)} registros encontrados. Confira identificações e destinos.")

    def changed(self, table=True):
        self.dirty = True
        if table:
            self.reviewed.set(False)
        self.invalidate_report()

    def options_changed(self):
        self.changed()
        self.draw_graph()

    def invalidate_report(self):
        self.checks = []
        if hasattr(self, "report_tree"):
            self.report_tree.delete(*self.report_tree.get_children())
        self.report_summary.set("Clique em Conferir documentos para calcular com os dados e critérios atuais.")
        self.totals_summary.set('Área e perímetro: clique em Conferir documentos para atualizar os resultados.')

    def refresh(self):
        duplicates = {c for c, n in Counter(p.code for p in self.points).items() if n > 1}
        for tree, rows in ((self.table_tree, self.points), (self.mem_tree, self.memorial)):
            tree.delete(*tree.get_children())
            for i, p in enumerate(rows):
                complete = p.x is not None and p.y is not None or tree is self.mem_tree and p.longitude is not None and p.latitude is not None
                warn = bool(p.notes or not complete or (tree is self.table_tree and p.code in duplicates))
                status = "Revisar" if warn else (f"OCR {p.confidence:.0%}" if p.confidence is not None else "Informado")
                values=(p.code, fmt(p.x), fmt(p.y), p.destination, fmt(p.distance), fmt(p.bearing, 5), status)
                if tree is self.mem_tree: values += (fmt(p.longitude,9),fmt(p.latitude,9))
                tree.insert("", "end", iid=str(i), values=values, tags=("warn",) if warn else ())
        self.point_count.set(f"{len(self.points)} pontos · Z = 0")
        geo_count=sum(p.latitude is not None and p.longitude is not None for p in self.memorial)
        self.mem_tree.configure(displaycolumns=('id','lon','lat','dest','dist','az','state','x','y') if geo_count else ('id','x','y','dest','dist','az','state','lon','lat'))
        self.mem_count.set(f"{len(self.memorial)} registros · {geo_count} com lat/lon" if not self.memorial_stale else "Texto alterado: interpretar novamente")
        self.mem_notes.configure(text="\n".join(self.memorial_warnings[:4]))
        self.draw_photo()
        self.draw_graph()

    def edit_point(self, memorial=False, new=False):
        if not self.guard():
            return
        rows, tree = (self.memorial, self.mem_tree) if memorial else (self.points, self.table_tree)
        selection = tree.selection()
        if not new and not selection:
            return
        idx = len(rows) if new else int(selection[0])
        old = Point("", None, None) if new else rows[idx]
        dialog = tk.Toplevel(self.root)
        dialog.title("Editar vértice" if memorial else "Editar ponto")
        dialog.transient(self.root)
        dialog.resizable(False, False)
        frame = ttk.Frame(dialog, padding=20)
        frame.pack(fill="both", expand=True)
        fields = []
        values = [old.code, fmt(old.x, 6), fmt(old.y, 6), old.destination, fmt(old.distance, 6), fmt(old.bearing, 6)]
        labels = ["Identificação", "E / X (m)", "N / Y (m)", "Próximo vértice", "Distância declarada (m)", "Azimute (decimal ou 122°39')"]
        if memorial:
            values += [fmt(old.longitude,9),fmt(old.latitude,9)]
            labels += ['Longitude (decimal ou graus/min/seg)','Latitude (decimal ou graus/min/seg)']
        for i, (label, value) in enumerate(zip(labels, values)):
            ttk.Label(frame, text=label).grid(row=i, column=0, sticky="w", padx=(0, 12), pady=6)
            var = tk.StringVar(value=value)
            entry = ttk.Entry(frame, textvariable=var, width=30)
            entry.grid(row=i, column=1, pady=6)
            fields.append(var)
        ttk.Label(frame, text=old.raw[:260], wraplength=450, style="Sub.TLabel").grid(row=len(fields), column=0, columnspan=2, pady=8)
        reviewed_fields = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame,text='Conferi todos os campos desta linha na fonte',variable=reviewed_fields).grid(row=len(fields)+1,column=0,columnspan=2,sticky='w')
        def save():
            try:
                code = normal_id(fields[0].get())
                import re
                if not re.fullmatch(r"[A-Z0-9][A-Z0-9_-]{0,79}", code):
                    raise ValueError("Use letras, números, hífen ou sublinhado na identificação.")
                x = number(fields[1].get()) if fields[1].get().strip() else None
                y = number(fields[2].get()) if fields[2].get().strip() else None
                if not memorial and (x is None or y is None):
                    raise ValueError("Preencha E/X e N/Y.")
                distance = number(fields[4].get()) if fields[4].get().strip() else None
                bearing = azimuth(fields[5].get()) if fields[5].get().strip() else None
                if distance is not None and distance < 0:
                    raise ValueError("Distância não pode ser negativa.")
                longitude,latitude = old.longitude,old.latitude
                if memorial:
                    geo=[]
                    for pos,is_lat in [(6,False),(7,True)]:
                        raw=fields[pos].get().strip()
                        value=(geographic(raw,is_lat) if '°' in raw or 'º' in raw else number(raw)) if raw else None
                        if value is not None and abs(value)>(90 if is_lat else 180): raise ValueError('Latitude/longitude fora do intervalo permitido.')
                        geo.append(value)
                    longitude,latitude=geo
                    if (x is not None or y is not None) and (longitude is not None or latitude is not None):
                        raise ValueError('Informe E/N ou latitude/longitude nesta linha, usando o par da fonte original.')
                point = replace(old,code=code,x=x,y=y,destination=normal_id(fields[3].get()),distance=distance,bearing=bearing,confidence=None,source=old.source or 'manual',notes=[] if reviewed_fields.get() else list(old.notes),longitude=longitude,latitude=latitude)
                if new:
                    rows.append(point)
                else:
                    rows[idx] = point
                self.changed(table=not memorial)
                self.refresh()
                tree.selection_set(str(idx))
                tree.see(str(idx))
                dialog.destroy()
            except ValueError as exc:
                messagebox.showerror("Confira os campos", str(exc), parent=dialog)
        ttk.Button(frame, text="Salvar correção", style="Accent.TButton", command=save).grid(row=len(fields)+2, column=1, sticky="e", pady=10)
        dialog.grab_set()

    def remove_point(self, memorial=False):
        if not self.guard():
            return
        tree, rows = (self.mem_tree, self.memorial) if memorial else (self.table_tree, self.points)
        selection = tree.selection()
        if selection and messagebox.askyesno("Remover registro", "Remover o registro selecionado?"):
            del rows[int(selection[0])]
            self.changed(table=not memorial)
            self.refresh()

    def move(self, offset):
        if not self.guard() or not self.table_tree.selection():
            return
        index = int(self.table_tree.selection()[0])
        new = index + offset
        if 0 <= new < len(self.points):
            self.points[index], self.points[new] = self.points[new], self.points[index]
            self.changed()
            self.refresh()
            self.table_tree.selection_set(str(new))
            self.table_tree.see(str(new))

    def swap_axes(self):
        if self.guard() and self.points and messagebox.askyesno("Trocar eixos", "Trocar E/X e N/Y em todos os pontos da tabela?"):
            for p in self.points:
                p.x, p.y = p.y, p.x
            self.changed()
            self.refresh()

    def show_detail(self, _=None):
        selected = self.table_tree.selection()
        if selected:
            p = self.points[int(selected[0])]
            self.set_detail(f"{p.code} · {p.source}\n{p.raw}\n" + "\n".join(p.notes))
            if p.source in self.source_images:
                self.preview=self.source_images[p.source]
                self.draw_photo()

    def show_crop(self):
        selection=self.table_tree.selection()
        if not selection: return
        p=self.points[int(selection[0])]
        original=self.source_images.get(p.source)
        if original is None or len(p.box)!=4:
            messagebox.showinfo('Recorte da fonte','Reimporte a imagem para ver o recorte desta linha.')
            return
        dialog=tk.Toplevel(self.root)
        dialog.title(f'Conferir linha · {p.code}')
        dialog.transient(self.root)
        crop=original.crop(tuple(p.box))
        scale=min(5,1200/max(1,crop.width))
        photo=ImageTk.PhotoImage(crop.resize((round(crop.width*scale),max(40,round(crop.height*scale))),Image.Resampling.LANCZOS))
        label=ttk.Label(dialog,image=photo,padding=12)
        label.image=photo
        label.pack()
        ttk.Label(dialog,text=p.raw+'\n'+'\n'.join(p.notes),wraplength=1150,padding=12).pack(fill='x')

    def suggest_order(self):
        if not self.guard(): return
        try:
            proposed=order_by_destinations(self.points)
        except ValueError as exc:
            messagebox.showerror('Não foi possível organizar',str(exc))
            return
        if [p.code for p in proposed]==[p.code for p in self.points]:
            messagebox.showinfo('Ordem do contorno','A ordem já coincide com os destinos.')
            return
        dialog=tk.Toplevel(self.root)
        dialog.title('Revisar ordem sugerida')
        dialog.transient(self.root)
        frame=ttk.Frame(dialog,padding=16)
        frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='A sequência abaixo usa os destinos informados. Confira antes de aplicar.').pack(anchor='w')
        listing=tk.Text(frame,width=85,height=16,wrap='word')
        listing.pack(fill='both',expand=True,pady=8)
        listing.insert('1.0',' → '.join(p.code for p in proposed)+' → '+proposed[0].code)
        listing.configure(state='disabled')
        def apply():
            self.points=proposed
            self.changed()
            self.refresh()
            dialog.destroy()
        ttk.Button(frame,text='Aplicar esta ordem',command=apply,style='Accent.TButton').pack(anchor='e')
        dialog.grab_set()

    def configure_reference(self):
        if not self.guard(): return
        dialog=tk.Toplevel(self.root)
        dialog.title('Referência da planta e do memorial')
        dialog.transient(self.root)
        frame=ttk.Frame(dialog,padding=18)
        frame.pack()
        ttk.Label(frame,text='Preencha conforme os documentos. Área e perímetro podem ser comparados\nsem converter latitude/longitude.',wraplength=600).grid(row=0,column=0,columnspan=2,pady=(0,12))
        source=tk.StringVar(value=self.georef.source_crs)
        target=tk.StringVar(value=self.georef.target_crs)
        for row,label,var in [(1,'Memorial: código EPSG geográfico',source),(2,'Planta: código EPSG projetado (metros)',target)]:
            ttk.Label(frame,text=label).grid(row=row,column=0,sticky='w',pady=5)
            ttk.Entry(frame,textvariable=var,width=25).grid(row=row,column=1,padx=10,pady=5)
        ttk.Label(frame,text='Ou monte os códigos a partir das informações da planta:').grid(row=3,column=0,columnspan=2,sticky='w',pady=(14,5))
        source_datum, target_datum, zone, hemisphere = (tk.StringVar() for _ in range(4))
        for row,label,var,values in [(4,'Datum do memorial',source_datum,['SIRGAS 2000','SAD69','WGS 84']),(5,'Datum da planta',target_datum,['SIRGAS 2000','SAD69','WGS 84']),(6,'Fuso UTM da planta',zone,[str(i) for i in range(1,61)]),(7,'Hemisfério',hemisphere,['Sul','Norte'])]:
            ttk.Label(frame,text=label).grid(row=row,column=0,sticky='w',pady=5)
            ttk.Combobox(frame,textvariable=var,values=values,state='readonly',width=23).grid(row=row,column=1,padx=10,pady=5)
        def fill_codes():
            try:
                target.set(utm_reference(target_datum.get(),zone.get(),hemisphere.get()))
                source.set({'SIRGAS 2000':'EPSG:4674','SAD69':'EPSG:4618','WGS 84':'EPSG:4326'}[source_datum.get()])
            except (ValueError,KeyError) as exc:
                messagebox.showerror('Confira a referência',str(exc) or 'Escolha o datum do memorial.',parent=dialog)
        ttk.Button(frame,text='Preencher códigos',command=fill_codes).grid(row=8,column=1,pady=8)
        def apply():
            try:
                geo=GeoReference(source.get().strip(),target.get().strip())
                if geo.source_crs or geo.target_crs: geo.transformer()
                self.georef=geo
                self.reference_label.set(f'{geo.source_crs} → {geo.target_crs}' if geo.source_crs else 'Latitude/longitude: referência não informada')
                self.changed(table=False)
                dialog.destroy()
            except Exception as exc:
                messagebox.showerror('Confira a referência',str(exc),parent=dialog)
        ttk.Button(frame,text='Aplicar',style='Accent.TButton',command=apply).grid(row=9,column=1,sticky='e',pady=8)
        dialog.grab_set()

    def review_codes(self):
        if not self.guard(): return
        suggestions=code_suggestions(self.points,self.memorial)
        if not suggestions:
            messagebox.showinfo('Códigos do memorial','Não há associações únicas por O/0 ou pontuação para sugerir. Confira os códigos na tabela.')
            return
        dialog=tk.Toplevel(self.root)
        dialog.title('Confirmar códigos do memorial')
        dialog.transient(self.root)
        frame=ttk.Frame(dialog,padding=16)
        frame.pack()
        ttk.Label(frame,text='Confira cada código na foto. Marque somente as associações corretas.',wraplength=650).pack(anchor='w',pady=(0,10))
        selections=[]
        for old,new in sorted(suggestions.items()):
            var=tk.BooleanVar(value=False)
            ttk.Checkbutton(frame,text=f'{old} → {new}',variable=var).pack(anchor='w')
            selections.append((old,new,var))
        def apply():
            mapping={old:new for old,new,var in selections if var.get()}
            for p in self.memorial:
                if p.code in mapping:
                    p.code=mapping[p.code]
                    p.notes=[n for n in p.notes if not n.startswith('Identificador com letra junto de zero')]
                p.destination=mapping.get(p.destination,p.destination)
            self.changed(table=False)
            self.refresh()
            dialog.destroy()
        ttk.Button(frame,text='Aplicar associações marcadas',style='Accent.TButton',command=apply).pack(anchor='e',pady=(12,0))
        dialog.grab_set()

    def set_detail(self, text):
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", text)
        self.detail.configure(state="disabled")

    def zoom(self, factor):
        self.photo_scale = 1.0 if factor == 0 else min(6, max(.5, self.photo_scale * factor))
        self.draw_photo()

    def draw_photo(self):
        if not hasattr(self, "canvas"):
            return
        self.canvas.delete("all")
        if self.preview is None:
            self.canvas.create_text(30, 35, anchor="nw", text="A imagem aparecerá aqui após a leitura.", fill="#536c74", font=("Segoe UI", 11))
            return
        w, h = max(200, self.canvas.winfo_width()), max(200, self.canvas.winfo_height())
        factor = min(w/self.preview.width, h/self.preview.height) * self.photo_scale
        size = (max(1, round(self.preview.width*factor)), max(1, round(self.preview.height*factor)))
        self.photo = ImageTk.PhotoImage(self.preview.resize(size, Image.Resampling.LANCZOS))
        self.canvas.create_image(0, 0, anchor="nw", image=self.photo)
        self.canvas.configure(scrollregion=(0, 0, *size))

    def draw_graph(self):
        if not hasattr(self, "graph"):
            return
        self.update_measures()
        self.graph.delete("all")
        points = [p for p in self.points if p.x is not None and p.y is not None and math.isfinite(p.x) and math.isfinite(p.y)]
        indices = [i+1 for i,p in enumerate(self.points) if p.x is not None and p.y is not None and math.isfinite(p.x) and math.isfinite(p.y)]
        if not points:
            self.graph.create_text(30, 35, anchor="nw", text="A prévia do contorno aparecerá aqui.", fill="#536c74")
            return
        width, height = max(200, self.graph.winfo_width()), max(200, self.graph.winfo_height())
        xmin, xmax = min(p.x for p in points), max(p.x for p in points)
        ymin, ymax = min(p.y for p in points), max(p.y for p in points)
        scale = min((width-100)/max(xmax-xmin, 1), (height-100)/max(ymax-ymin, 1))
        coords = [(50+(p.x-xmin)*scale, height-50-(p.y-ymin)*scale) for p in points]
        if self.contour.get() and len(points) == len(self.points) and len(coords) >= 2:
            path = coords + ([coords[0]] if self.close_contour.get() and len(coords) > 2 else [])
            self.graph.create_line(*[v for xy in path for v in xy], fill="#2a777c", width=2)
        for i, (x, y) in enumerate(coords):
            self.graph.create_oval(x-3, y-3, x+3, y+3, fill=BLUE, outline="white")
            if len(coords) <= 60:
                self.graph.create_text(x+5, y-7, text=str(indices[i]), fill="#607983", font=("Segoe UI", 8), anchor="w")
        self.graph.create_text(16, 16, anchor="nw", text=f"{len(points)} pontos · índices na ordem da tabela", fill="#536c74")

    def update_measures(self):
        self.area_summary.set("Área total: —")
        self.perimeter_summary.set("Perímetro: —")
        if not self.contour.get():
            self.measure_note.set("Ative Gerar contorno para ver a área e o perímetro.")
            return
        measures = contour_measures(self.points, self.close_contour.get())
        if measures.area_m2 is not None:
            self.area_summary.set(f"Área total: {fmt_measure(measures.area_m2)} m² ({fmt_measure(measures.area_m2 / 10000, 4)} ha)")
        if measures.perimeter_m is not None:
            self.perimeter_summary.set(f"Perímetro: {fmt_measure(measures.perimeter_m)} m")
        elif measures.length_m is not None:
            self.perimeter_summary.set(f"Comprimento dos trechos: {fmt_measure(measures.length_m)} m")
        self.measure_note.set(measures.note or "Medidas planas pelas coordenadas E/N em metros, na ordem da tabela. Confira os pontos lidos.")

    def run_compare(self):
        if not self.guard():
            return False
        if not self.points:
            messagebox.showinfo("Carregue a tabela", "Importe a tabela de coordenadas primeiro.")
            return False
        if self.memorial_stale:
            messagebox.showinfo("Memorial alterado", "Clique em Interpretar texto na aba Memorial para usar o texto atualizado.")
            return False
        try:
            tolerances = tuple(number(v.get()) for v in (self.coord_tol, self.dist_tol, self.az_tol))
            area=number(self.declared_area.get()) if self.declared_area.get().strip() else None
            perimeter=number(self.declared_perimeter.get()) if self.declared_perimeter.get().strip() else None
            if area is not None and area<=0 or perimeter is not None and perimeter<=0:
                raise ValueError('Área e perímetro declarados precisam ser positivos.')
            self.checks = verify_documents(self.points,self.memorial,coord_tol=tolerances[0],dist_tol=tolerances[1],az_tol_minutes=tolerances[2],area_m2=area,perimeter_m=perimeter,area_tol=number(self.area_tol.get()),perimeter_tol=number(self.perimeter_tol.get()),georef=self.georef,measurement_mode=self.measurement_mode.get(),close=self.close_contour.get())
        except ValueError as exc:
            messagebox.showerror("Critérios inválidos", str(exc))
            return False
        for origin, warnings in (("Tabela", self.table_warnings), ("Memorial", self.memorial_warnings)):
            for warning in warnings:
                if "Confiança OCR não garante" not in warning:
                    self.checks.append(Check(origin, "Leitura", "Interpretação", "", "", "", "PENDENTE", warning))
        if not self.memorial:
            self.checks.append(Check("Memorial", "Documento", "Cobertura", "", "não carregado ou não interpretado", "", "PENDENTE", "Apenas a consistência interna da tabela pode ser verificada."))
        self.report_tree.delete(*self.report_tree.get_children())
        for c in self.checks:
            self.report_tree.insert("", "end", values=(c.status, c.origin, c.item, c.field, c.reference, c.calculated, c.difference, c.note), tags=(c.status,))
        counts = Counter(c.status for c in self.checks)
        total_checks=[c for c in self.checks if c.item=='Total']
        self.totals_summary.set('\n'.join(f"{c.field}: planta {fmt_measure(float(c.calculated)) if c.calculated else '—'} · memorial {fmt_measure(float(c.reference)) if c.reference else '—'} · {c.status.lower()}" + (f" · diferença {fmt_measure(float(c.difference))}" if c.difference else '') for c in total_checks))
        self.report_summary.set(f"{counts['CONFERE']} verificações conferem · {counts['DIVERGE']} divergências · {counts['PENDENTE']} pendências")
        self.tabs.select(self.tab_report)
        return True

    def export_report(self):
        if not self.run_compare():
            return
        path = filedialog.asksaveasfilename(title="Salvar conferência", initialdir=BASE, initialfile="conferencia.csv", defaultextension=".csv")
        if path:
            settings = f"Posição <= {self.coord_tol.get()} m; distância <= {self.dist_tol.get()} m; azimute <= {self.az_tol.get()} min; área <= {self.area_tol.get()} m²; perímetro <= {self.perimeter_tol.get()} m. Referência: {self.georef.source_crs or 'não informada'} → {self.georef.target_crs or 'não informada'}. Trechos: {self.measurement_mode.get()}. Totais planos; conferência numérica dos documentos."
            try:
                Path(path).write_text(checks_csv(self.checks, settings), encoding="utf-8-sig")
                self.status.set(f"Relatório salvo em {path}")
            except OSError as exc:
                messagebox.showerror("Falha ao salvar", str(exc))

    def export(self):
        if not self.guard():
            return
        errors = validate(self.points)
        if self.contour.get() and not errors:
            errors = contour_issues(self.points,self.close_contour.get())
        if errors:
            messagebox.showerror("Corrija a tabela", "\n".join(errors[:15]))
            return
        if not self.reviewed.get():
            messagebox.showinfo("Conferência dos pontos", "Confira a quantidade, os valores e a ordem. Depois marque a confirmação no rodapé para exportar.")
            return
        folder = filedialog.askdirectory(title="Pasta para os scripts e a lista de pontos", initialdir=BASE)
        if not folder:
            return
        directory = Path(folder)
        names = ["pontos_pontos.scr", "pontos.csv"] + (["pontos_contorno.scr"] if self.contour.get() else [])
        if any((directory/n).exists() for n in names) and not messagebox.askyesno("Arquivos existentes", "Substituir os arquivos de pontos nesta pasta?"):
            return
        try:
            paths = export_files(directory, self.points, self.contour.get(), self.close_contour.get())
            self.status.set(f"Exportados {len(paths)} arquivos em {directory}")
            messagebox.showinfo("Pronto para AutoCAD", "Arquivos gerados:\n" + "\n".join(p.name for p in paths) + "\n\nNo AutoCAD, abra um desenho em metros, execute SCRIPT e escolha o arquivo .scr. Todos os pontos usam Z = 0.")
        except (ValueError, OSError) as exc:
            messagebox.showerror("Falha na exportação", str(exc))

    def save_project(self):
        if not self.guard():
            return False
        path = filedialog.asksaveasfilename(title="Salvar projeto", initialdir=BASE, initialfile="projeto.pontos.json", defaultextension=".json", filetypes=[("Projeto", "*.json")])
        if not path:
            return False
        data = {"version": 1, "saved_at": datetime.now().isoformat(), "points": [asdict(p) for p in self.points], "memorial": [asdict(p) for p in self.memorial], "memorial_text": self.mem_text.get("1.0", "end-1c"), "memorial_stale": self.memorial_stale, "table_warnings": self.table_warnings, "memorial_warnings": self.memorial_warnings, "tolerances": [v.get() for v in (self.coord_tol, self.dist_tol, self.az_tol)], "contour": self.contour.get(), "close": self.close_contour.get()}
        data.update(version=2,georef=asdict(self.georef),declared_totals=[self.declared_area.get(),self.declared_perimeter.get()],total_tolerances=[self.area_tol.get(),self.perimeter_tol.get()],measurement_mode=self.measurement_mode.get())
        try:
            Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            self.dirty = False
            self.status.set(f"Projeto salvo: {Path(path).name}")
            return True
        except OSError as exc:
            messagebox.showerror("Falha ao salvar", str(exc))
            return False

    def load_project(self):
        if not self.guard() or not self.may_discard():
            return
        path = filedialog.askopenfilename(title="Abrir projeto", initialdir=BASE, filetypes=[("Projeto", "*.json")])
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
            if data.get("version") not in (1,2):
                raise ValueError("Versão de projeto não reconhecida.")
            points = [Point.from_dict(p) for p in data["points"]]
            memorial = [Point.from_dict(p) for p in data.get("memorial", [])]
            tolerances = data.get("tolerances", ["0,02", "0,05", "1"])
            if len(tolerances) != 3 or any(number(t) < 0 for t in tolerances):
                raise ValueError("Tolerâncias inválidas.")
            total_tolerances=data.get('total_tolerances',['1,00','0,10'])
            declared=data.get('declared_totals',['',''])
            if len(total_tolerances)!=2 or any(number(t)<0 for t in total_tolerances) or len(declared)!=2 or any(number(t)<=0 for t in declared if str(t).strip()):
                raise ValueError('Totais ou tolerâncias inválidos.')
            georef=GeoReference(**data.get('georef',{}))
            mode=data.get('measurement_mode','Não informado')
            if mode not in ('Não informado','Grade da planta','Geodésico / terreno'):
                raise ValueError('Tipo de medida inválido.')
            self.points, self.memorial = points, memorial
            self.table_warnings = data.get("table_warnings", [])
            self.memorial_warnings = data.get("memorial_warnings", [])
            self.mem_text.delete("1.0", "end")
            self.mem_text.insert("1.0", data.get("memorial_text", ""))
            self.mem_text.edit_modified(False)
            self.memorial_stale = bool(data.get("memorial_stale", False))
            for variable, value in zip((self.coord_tol, self.dist_tol, self.az_tol), tolerances):
                variable.set(value)
            for variable,value in zip((self.declared_area,self.declared_perimeter),declared): variable.set(value)
            for variable,value in zip((self.area_tol,self.perimeter_tol),total_tolerances): variable.set(value)
            self.measurement_mode.set(mode)
            self.georef=georef
            self.reference_label.set(f'{georef.source_crs} → {georef.target_crs}' if georef.source_crs else 'Latitude/longitude: referência não informada')
            self.contour.set(bool(data.get("contour", True)))
            self.close_contour.set(bool(data.get("close", True)))
            self.preview = None
            self.source_images = {}
            self.reviewed.set(False)
            self.invalidate_report()
            self.refresh()
            self.dirty = False
            self.status.set(f"Projeto aberto: {Path(path).name}. A prévia da foto não é armazenada no projeto.")
        except (ValueError, TypeError, KeyError, AttributeError, OSError) as exc:
            messagebox.showerror("Projeto inválido", str(exc))

    def may_discard(self):
        if not self.dirty:
            return True
        answer = messagebox.askyesnocancel("Salvar alterações", "Deseja salvar o projeto antes de continuar?")
        return False if answer is None else self.save_project() if answer else True

    def quit(self):
        if self.guard() and self.may_discard():
            self.root.destroy()

    def help(self):
        messagebox.showinfo("Como usar", "1. Abra uma foto, PDF ou lista. O layout da foto de referência é: código, E, N, altitude, destino, azimute e distância.\n\n2. Confira a imagem e os pontos. Duplo clique permite corrigir valores; as setas alteram a ordem do contorno.\n\n3. Importe ou cole o memorial e confira a interpretação. São lidos vértices identificados, coordenadas E/N explícitas e trechos com distância e azimute.\n\n4. Ajuste as tolerâncias e execute a conferência. Amarelo indica pendência, vermelho indica divergência.\n\n5. Confirme a revisão e exporte os scripts. No AutoCAD, execute SCRIPT. E/X e N/Y devem estar em metros, no mesmo sistema; Z sempre será zero.\n\nArquivos de exemplo fictícios estão na pasta exemplos.\n\nSalve o projeto para continuar depois. A leitura roda localmente; seus documentos não são enviados a serviços externos.")

from __future__ import annotations

import csv
import os
import queue
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import ttk

APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent
VENV_SITE_PACKAGES = PROJECT_ROOT / "entorno" / "lib" / "python3.13" / "site-packages"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
if VENV_SITE_PACKAGES.exists() and str(VENV_SITE_PACKAGES) not in sys.path:
    sys.path.append(str(VENV_SITE_PACKAGES))

import hrcalc
from max30102 import MAX30102

try:
    import requests
except ImportError:
    requests = None

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ImportError:
    plt = None

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
except ImportError:
    colors = None
    letter = None
    getSampleStyleSheet = None
    inch = None
    Image = None
    Paragraph = None
    SimpleDocTemplate = None
    Spacer = None
    Table = None
    TableStyle = None


CSV_FILE = "registro_biomedico.csv"
PDF_FILE = "reporte_biomedico.pdf"
PDF_CHART_FILE = "reporte_biomedico_graficas.png"
PDF_TABLE_ROWS = 24

# Umbrales de alerta: ajusta estos valores si tu protocolo medico lo requiere.
CRITICAL_SPO2_MIN = 92
CRITICAL_BPM_MAX = 120
CRITICAL_BPM_MIN = 50
CRITICAL_TEMP_MAX = 38.0

# Cooldown antispam: despues de una alerta se esperan 120 segundos para otra.
ALERT_COOLDOWN_SECONDS = 120

DEFAULT_TELEGRAM_TOKEN = "8730838095:AAFT6HOSVROjM6CLS1gduWEbEvCm3O6Z_ew"
DEFAULT_TELEGRAM_CHAT_ID = ""


@dataclass
class Reading:
    timestamp: datetime
    bpm: float | None
    spo2: float | None
    temperature: float | None
    raw_ir: int | None
    valid_bpm: bool
    valid_spo2: bool
    finger_detected: bool


class SensorWorker:
    def __init__(self, data_queue, status_queue, bus=1, address=0x57):
        self.data_queue = data_queue
        self.status_queue = status_queue
        self.bus = bus
        self.address = address
        self.stop_event = threading.Event()
        self.thread = None

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()

    def _run(self):
        sensor = None
        ir_data = []
        red_data = []
        bpms = []
        last_temperature = None
        last_temperature_read = 0.0
        last_raw_ir = None
        temperature_warning_sent = False

        try:
            self.status_queue.put(("info", "Inicializando sensor MAX30102..."))
            sensor = MAX30102(channel=self.bus, address=self.address)
            self.status_queue.put(("ok", "Sensor activo. Esperando lectura estable..."))

            while not self.stop_event.is_set():
                num_samples = sensor.get_data_present()

                while num_samples > 0 and not self.stop_event.is_set():
                    red, ir = sensor.read_fifo()
                    red_data.append(red)
                    ir_data.append(ir)
                    last_raw_ir = ir
                    num_samples -= 1

                while len(ir_data) > hrcalc.BUFFER_SIZE:
                    ir_data.pop(0)
                    red_data.pop(0)

                if len(ir_data) == hrcalc.BUFFER_SIZE:
                    bpm, valid_bpm, spo2, valid_spo2 = hrcalc.calc_hr_and_spo2(
                        ir_data, red_data
                    )
                    finger_detected = self._finger_detected(ir_data, red_data)

                    bpm_value = None
                    spo2_value = None

                    if valid_bpm and finger_detected:
                        bpms.append(bpm)
                        while len(bpms) > 4:
                            bpms.pop(0)
                        bpm_value = sum(bpms) / len(bpms)

                    if valid_spo2 and finger_detected:
                        spo2_value = float(spo2)

                    # La temperatura se lee desde el sensor real. Se limita a
                    # una vez por segundo para no bloquear el bucle de muestras.
                    if time.monotonic() - last_temperature_read >= 1.0:
                        try:
                            last_temperature = sensor.read_temperature()
                            temperature_warning_sent = False
                        except Exception as exc:
                            last_temperature = None
                            if not temperature_warning_sent:
                                self.status_queue.put(("warning", f"No se pudo leer temperatura: {exc}"))
                                temperature_warning_sent = True
                        last_temperature_read = time.monotonic()

                    self.data_queue.put(
                        Reading(
                            timestamp=datetime.now(),
                            bpm=bpm_value,
                            spo2=spo2_value,
                            temperature=last_temperature,
                            raw_ir=last_raw_ir,
                            valid_bpm=valid_bpm,
                            valid_spo2=valid_spo2,
                            finger_detected=finger_detected,
                        )
                    )

                time.sleep(0.01)

        except Exception as exc:
            self.status_queue.put(("sensor_error", f"Error del sensor: {exc}"))
        finally:
            if sensor is not None:
                try:
                    sensor.shutdown()
                except Exception as exc:
                    self.status_queue.put(("warning", f"No se pudo apagar el sensor: {exc}"))
            self.status_queue.put(("info", "Monitoreo detenido."))

    @staticmethod
    def _finger_detected(ir_data, red_data):
        ir_mean = sum(ir_data) / len(ir_data)
        red_mean = sum(red_data) / len(red_data)
        return ir_mean >= 50000 or red_mean >= 50000


class AlertManager:
    def __init__(self, status_queue):
        self.status_queue = status_queue
        self.last_alert_time = 0.0
        self.alert_queue = queue.Queue()
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()

    def enqueue_message(self, token, chat_id, message):
        if not token.strip() or not chat_id.strip():
            self.status_queue.put(("warning", "Falta Telegram Token o Chat ID."))
            return

        self.status_queue.put(("info", "Enviando mensaje por Telegram..."))
        self.alert_queue.put(("message", token.strip(), chat_id.strip(), message))

    def enqueue_document(self, token, chat_id, file_path, caption):
        if not token.strip() or not chat_id.strip():
            self.status_queue.put(("warning", "Falta Telegram Token o Chat ID."))
            return

        self.status_queue.put(("info", "Enviando reporte PDF por Telegram..."))
        self.alert_queue.put(("document", token.strip(), chat_id.strip(), file_path, caption))

    def enqueue_if_critical(self, bpm, spo2, temperature, token, chat_id):
        has_vital_data = bpm is not None and spo2 is not None
        has_temperature = temperature is not None
        if not has_vital_data and not has_temperature:
            return

        critical_vitals = (
            has_vital_data
            and (spo2 < CRITICAL_SPO2_MIN or bpm > CRITICAL_BPM_MAX or bpm < CRITICAL_BPM_MIN)
        )
        critical_temperature = has_temperature and temperature > CRITICAL_TEMP_MAX
        critical = critical_vitals or critical_temperature
        if not critical:
            return

        now = time.monotonic()
        if now - self.last_alert_time < ALERT_COOLDOWN_SECONDS:
            remaining = int(ALERT_COOLDOWN_SECONDS - (now - self.last_alert_time))
            self.status_queue.put(("warning", f"Alerta critica en cooldown: {remaining}s restantes."))
            return

        if not token.strip() or not chat_id.strip():
            self.status_queue.put(("warning", "Alerta critica detectada, pero falta Token o Chat ID."))
            return

        self.last_alert_time = now
        bpm_text = "--" if bpm is None else f"{bpm:.1f}"
        spo2_text = "--" if spo2 is None else f"{spo2:.1f}"
        temp_text = "--" if temperature is None else f"{temperature:.1f}"
        message = (
            "¡ALERTA MÉDICA! Paciente con parámetros críticos: "
            f"{bpm_text} BPM, {spo2_text}% SpO2 y {temp_text} °C"
        )
        self.alert_queue.put(("message", token.strip(), chat_id.strip(), message))

    def _worker(self):
        while True:
            item = self.alert_queue.get()
            kind = item[0]
            if kind == "message":
                _, token, chat_id, message = item
                ok, status = send_telegram_alert(token, chat_id, message)
            else:
                _, token, chat_id, file_path, caption = item
                ok, status = send_telegram_document(token, chat_id, file_path, caption)
            level = "ok" if ok else "warning"
            self.status_queue.put((level, status))
            self.alert_queue.task_done()


def send_telegram_alert(token, chat_id, message):
    if requests is None:
        return False, "No se pudo enviar alerta: instala requests."

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message}

    try:
        response = requests.post(url, data=payload, timeout=6)
        response.raise_for_status()
        return True, "Mensaje enviado por Telegram."
    except Exception as exc:
        return False, f"Fallo de red/Telegram: {exc}"


def send_telegram_document(token, chat_id, file_path, caption):
    if requests is None:
        return False, "No se pudo enviar PDF: instala requests."

    path = Path(file_path)
    if not path.exists():
        return False, f"No existe el PDF: {path}"

    url = f"https://api.telegram.org/bot{token}/sendDocument"
    payload = {"chat_id": chat_id, "caption": caption}

    try:
        with path.open("rb") as pdf_file:
            files = {"document": (path.name, pdf_file, "application/pdf")}
            response = requests.post(url, data=payload, files=files, timeout=20)
        response.raise_for_status()
        return True, "Reporte PDF enviado por Telegram."
    except Exception as exc:
        return False, f"Fallo enviando PDF por Telegram: {exc}"


def generate_pdf_report(readings, output_path=PDF_FILE):
    if plt is None or SimpleDocTemplate is None:
        raise RuntimeError("Faltan dependencias: instala matplotlib y reportlab.")

    if not readings:
        raise RuntimeError("No hay lecturas para generar el reporte.")

    output_path = Path(output_path)
    chart_path = output_path.with_name(PDF_CHART_FILE)
    _create_report_chart(readings, chart_path)

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=letter,
        rightMargin=0.55 * inch,
        leftMargin=0.55 * inch,
        topMargin=0.55 * inch,
        bottomMargin=0.55 * inch,
    )
    styles = getSampleStyleSheet()
    story = [
        Paragraph("Reporte Biomédico MAX30102", styles["Title"]),
        Spacer(1, 0.12 * inch),
        Paragraph(
            "Reporte generado automáticamente desde la sesión actual de monitoreo.",
            styles["BodyText"],
        ),
        Spacer(1, 0.18 * inch),
    ]

    story.append(_build_summary_table(readings))
    story.append(Spacer(1, 0.22 * inch))
    story.append(Image(str(chart_path), width=7.1 * inch, height=4.4 * inch))
    story.append(Spacer(1, 0.18 * inch))
    story.append(Paragraph("Últimas lecturas registradas", styles["Heading2"]))
    story.append(_build_readings_table(readings[-PDF_TABLE_ROWS:]))
    story.append(Spacer(1, 0.12 * inch))
    story.append(
        Paragraph(
            "Nota: la temperatura corresponde al sensor/chip MAX30102 y requiere calibración "
            "si se desea interpretar como temperatura corporal clínica.",
            styles["Italic"],
        )
    )

    doc.build(story)
    return output_path


def _create_report_chart(readings, chart_path):
    timestamps = [reading.timestamp for reading in readings]
    series = [
        ("BPM", [reading.bpm for reading in readings], "#ef4444"),
        ("SpO2 (%)", [reading.spo2 for reading in readings], "#38bdf8"),
        ("Temperatura (°C)", [reading.temperature for reading in readings], "#f59e0b"),
    ]

    fig, axes = plt.subplots(3, 1, figsize=(9.2, 5.8), sharex=True)
    fig.suptitle("Tendencias de la sesión", fontsize=14, fontweight="bold")

    for axis, (label, values, color) in zip(axes, series):
        clean_times = [timestamp for timestamp, value in zip(timestamps, values) if value is not None]
        clean_values = [value for value in values if value is not None]
        axis.set_ylabel(label)
        axis.grid(True, alpha=0.28)
        if clean_values:
            axis.plot(clean_times, clean_values, color=color, linewidth=1.8)
            axis.scatter(clean_times[-1:], clean_values[-1:], color=color, s=28)
        else:
            axis.text(0.5, 0.5, "Sin datos", ha="center", va="center", transform=axis.transAxes)

    axes[-1].set_xlabel("Tiempo")
    fig.autofmt_xdate()
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(str(chart_path), dpi=140)
    plt.close(fig)


def _build_summary_table(readings):
    start = readings[0].timestamp.isoformat(timespec="seconds")
    end = readings[-1].timestamp.isoformat(timespec="seconds")
    critical_count = sum(1 for reading in readings if _is_critical_reading(reading))

    data = [
        ["Inicio", start, "Fin", end],
        ["Lecturas", str(len(readings)), "Eventos críticos", str(critical_count)],
        ["BPM", _stats_text([r.bpm for r in readings]), "SpO2", _stats_text([r.spo2 for r in readings])],
        ["Temperatura", _stats_text([r.temperature for r in readings]), "Raw IR", _stats_text([r.raw_ir for r in readings])],
    ]
    table = Table(data, colWidths=[1.15 * inch, 2.3 * inch, 1.3 * inch, 2.35 * inch])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e5e7eb")),
                ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#f8fafc")),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    return table


def _build_readings_table(readings):
    data = [["Fecha_Hora", "BPM", "SpO2", "Temp", "Raw_IR"]]
    for reading in readings:
        data.append(
            [
                reading.timestamp.strftime("%H:%M:%S"),
                _format_value(reading.bpm, 1),
                _format_value(reading.spo2, 1),
                _format_value(reading.temperature, 1),
                "--" if reading.raw_ir is None else str(reading.raw_ir),
            ]
        )

    table = Table(data, colWidths=[1.35 * inch, 0.95 * inch, 0.95 * inch, 0.95 * inch, 1.35 * inch])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#17212f")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#f8fafc")),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#cbd5e1")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
            ]
        )
    )
    return table


def _stats_text(values):
    clean_values = [float(value) for value in values if value is not None]
    if not clean_values:
        return "--"
    avg = sum(clean_values) / len(clean_values)
    return f"prom {avg:.1f} | min {min(clean_values):.1f} | max {max(clean_values):.1f}"


def _format_value(value, decimals):
    if value is None:
        return "--"
    return f"{value:.{decimals}f}"


def _is_critical_reading(reading):
    bpm_critical = reading.bpm is not None and (
        reading.bpm > CRITICAL_BPM_MAX or reading.bpm < CRITICAL_BPM_MIN
    )
    spo2_critical = reading.spo2 is not None and reading.spo2 < CRITICAL_SPO2_MIN
    temp_critical = reading.temperature is not None and reading.temperature > CRITICAL_TEMP_MAX
    return bpm_critical or spo2_critical or temp_critical


class MedicalMonitorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Monitor Biomédico MAX30102")
        self.root.geometry("1120x660")
        self.root.minsize(980, 600)
        self.root.configure(bg="#0f1720")

        self.data_queue = queue.Queue()
        self.status_queue = queue.Queue()
        self.sensor_worker = None
        self.latest_reading = None
        self.session_readings = []
        self.alert_manager = AlertManager(self.status_queue)

        self.bpm_var = tk.StringVar(value="--")
        self.spo2_var = tk.StringVar(value="--")
        self.temperature_var = tk.StringVar(value="--")
        self.raw_ir_var = tk.StringVar(value="--")
        self.status_var = tk.StringVar(value="Sistema listo.")
        self.save_csv_var = tk.BooleanVar(value=False)
        self.token_var = tk.StringVar(value=DEFAULT_TELEGRAM_TOKEN)
        self.chat_id_var = tk.StringVar(value=DEFAULT_TELEGRAM_CHAT_ID)
        self.monitoring_var = tk.BooleanVar(value=False)

        self._configure_style()
        self._build_ui()
        self._poll_queues()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _configure_style(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background="#0f1720")
        style.configure("Card.TFrame", background="#17212f", relief="flat")
        style.configure("TLabel", background="#0f1720", foreground="#e6edf3")
        style.configure("Title.TLabel", font=("Arial", 22, "bold"))
        style.configure("MetricName.TLabel", background="#17212f", foreground="#94a3b8", font=("Arial", 18))
        style.configure("MetricValue.TLabel", background="#17212f", foreground="#f8fafc", font=("Arial", 56, "bold"))
        style.configure("MetricUnit.TLabel", background="#17212f", foreground="#38bdf8", font=("Arial", 20, "bold"))
        style.configure("Raw.TLabel", background="#0f1720", foreground="#cbd5e1", font=("Arial", 12, "bold"))
        style.configure("TCheckbutton", background="#0f1720", foreground="#e6edf3")
        style.map("TCheckbutton", background=[("active", "#0f1720")])
        style.configure("TEntry", fieldbackground="#111827", foreground="#f8fafc")
        style.configure("Accent.TButton", font=("Arial", 14, "bold"), padding=12)

    def _build_ui(self):
        container = ttk.Frame(self.root, padding=24)
        container.pack(fill="both", expand=True)

        title = ttk.Label(container, text="Monitor Biomédico MAX30102", style="Title.TLabel")
        title.pack(anchor="w")

        cards = ttk.Frame(container)
        cards.pack(fill="both", expand=True, pady=(24, 18))
        cards.columnconfigure(0, weight=1)
        cards.columnconfigure(1, weight=1)
        cards.columnconfigure(2, weight=1)
        cards.rowconfigure(0, weight=1)

        self._metric_card(cards, "Frecuencia Cardiaca", self.bpm_var, "BPM").grid(
            row=0, column=0, sticky="nsew", padx=(0, 10)
        )
        self._metric_card(cards, "Oxigenación", self.spo2_var, "SpO2 %").grid(
            row=0, column=1, sticky="nsew", padx=10
        )
        self._metric_card(cards, "Temperatura", self.temperature_var, "°C").grid(
            row=0, column=2, sticky="nsew", padx=(10, 0)
        )

        controls = ttk.Frame(container)
        controls.pack(fill="x", pady=(0, 16))
        controls.columnconfigure(1, weight=1)
        controls.columnconfigure(3, weight=1)

        self.start_button = ttk.Button(
            controls,
            text="Iniciar monitoreo",
            style="Accent.TButton",
            command=self._toggle_monitoring,
        )
        self.start_button.grid(row=0, column=0, sticky="w", padx=(0, 16))

        save_check = ttk.Checkbutton(
            controls,
            text=f"Guardar en {CSV_FILE}",
            variable=self.save_csv_var,
        )
        save_check.grid(row=0, column=1, sticky="w")

        raw_ir_name = ttk.Label(controls, text="Sensor IR (Raw):", style="Raw.TLabel")
        raw_ir_name.grid(row=0, column=2, sticky="e", padx=(12, 8))

        raw_ir_label = ttk.Label(
            controls,
            textvariable=self.raw_ir_var,
            style="Raw.TLabel",
        )
        raw_ir_label.grid(row=0, column=3, sticky="e")

        config = ttk.Frame(container)
        config.pack(fill="x", pady=(0, 16))
        config.columnconfigure(1, weight=1)
        config.columnconfigure(3, weight=1)

        ttk.Label(config, text="Telegram Token").grid(row=0, column=0, sticky="w", padx=(0, 8))
        token_entry = ttk.Entry(config, textvariable=self.token_var, show="*", width=36)
        token_entry.grid(row=0, column=1, sticky="ew", padx=(0, 16))

        ttk.Label(config, text="Chat ID").grid(row=0, column=2, sticky="w", padx=(0, 8))
        chat_entry = ttk.Entry(config, textvariable=self.chat_id_var, width=22)
        chat_entry.grid(row=0, column=3, sticky="ew")

        telegram_actions = ttk.Frame(container)
        telegram_actions.pack(fill="x", pady=(0, 16))

        current_values_button = ttk.Button(
            telegram_actions,
            text="Enviar valores actuales",
            command=self._send_current_values,
        )
        current_values_button.pack(side="left", padx=(0, 12))

        critical_test_button = ttk.Button(
            telegram_actions,
            text="Probar alerta crítica",
            command=self._send_critical_alert_test,
        )
        critical_test_button.pack(side="left", padx=(0, 12))

        pdf_button = ttk.Button(
            telegram_actions,
            text="Enviar reporte PDF",
            command=self._send_pdf_report,
        )
        pdf_button.pack(side="left")

        status_bar = tk.Label(
            container,
            textvariable=self.status_var,
            bg="#111827",
            fg="#cbd5e1",
            anchor="w",
            padx=12,
            pady=10,
            font=("Arial", 11),
        )
        status_bar.pack(fill="x")

    def _metric_card(self, parent, name, value_var, unit):
        frame = ttk.Frame(parent, style="Card.TFrame", padding=28)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)

        ttk.Label(frame, text=name, style="MetricName.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(frame, textvariable=value_var, style="MetricValue.TLabel").grid(
            row=1, column=0, sticky="nsew", pady=(28, 8)
        )
        ttk.Label(frame, text=unit, style="MetricUnit.TLabel").grid(row=2, column=0, sticky="e")
        return frame

    def _toggle_monitoring(self):
        if self.monitoring_var.get():
            self._stop_monitoring()
        else:
            self._start_monitoring()

    def _start_monitoring(self):
        self.sensor_worker = SensorWorker(self.data_queue, self.status_queue)
        self.sensor_worker.start()
        self.monitoring_var.set(True)
        self.start_button.configure(text="Detener monitoreo")
        self.status_var.set("Monitoreo iniciado.")

    def _stop_monitoring(self):
        if self.sensor_worker:
            self.sensor_worker.stop()
        self.monitoring_var.set(False)
        self.start_button.configure(text="Iniciar monitoreo")
        self.status_var.set("Deteniendo monitoreo...")

    def _send_current_values(self):
        if self.latest_reading is None:
            self.status_var.set("Aun no hay lecturas reales para enviar.")
            return

        reading = self.latest_reading
        bpm_text = "--" if reading.bpm is None else f"{reading.bpm:.1f}"
        spo2_text = "--" if reading.spo2 is None else f"{reading.spo2:.1f}"
        temp_text = "--" if reading.temperature is None else f"{reading.temperature:.1f}"
        raw_ir_text = "--" if reading.raw_ir is None else str(reading.raw_ir)
        message = (
            "Lectura actual del Monitor Biomédico MAX30102:\n"
            f"Fecha/Hora: {reading.timestamp.isoformat(timespec='seconds')}\n"
            f"BPM: {bpm_text}\n"
            f"SpO2: {spo2_text}%\n"
            f"Temperatura: {temp_text} °C\n"
            f"Sensor IR (Raw): {raw_ir_text}"
        )
        self.alert_manager.enqueue_message(
            self.token_var.get(),
            self.chat_id_var.get(),
            message,
        )

    def _send_critical_alert_test(self):
        self.status_var.set("Simulando alerta crítica para Telegram...")
        self.alert_manager.enqueue_if_critical(
            bpm=130.0,
            spo2=89.0,
            temperature=38.5,
            token=self.token_var.get(),
            chat_id=self.chat_id_var.get(),
        )

    def _send_pdf_report(self):
        if not self.session_readings:
            self.status_var.set("Aun no hay lecturas para generar el PDF.")
            return

        token = self.token_var.get()
        chat_id = self.chat_id_var.get()
        if not token.strip() or not chat_id.strip():
            self.status_var.set("Falta Telegram Token o Chat ID.")
            return

        readings = list(self.session_readings)
        self.status_var.set("Generando reporte PDF...")
        thread = threading.Thread(
            target=self._generate_and_send_pdf_report,
            args=(readings, token, chat_id),
            daemon=True,
        )
        thread.start()

    def _generate_and_send_pdf_report(self, readings, token, chat_id):
        try:
            output_path = Path(PDF_FILE).resolve()
            generate_pdf_report(readings, output_path)
            self.status_queue.put(("info", f"Reporte generado: {output_path.name}. Enviando..."))
            self.alert_manager.enqueue_document(
                token,
                chat_id,
                str(output_path),
                "Reporte biomédico MAX30102 con gráficas de la sesión.",
            )
        except Exception as exc:
            self.status_queue.put(("warning", f"No se pudo generar/enviar PDF: {exc}"))

    def _poll_queues(self):
        self._drain_status_queue()
        self._drain_data_queue()
        self.root.after(200, self._poll_queues)

    def _drain_status_queue(self):
        while True:
            try:
                level, message = self.status_queue.get_nowait()
            except queue.Empty:
                break
            self.status_var.set(message)
            if level == "sensor_error":
                self.monitoring_var.set(False)
                self.start_button.configure(text="Iniciar monitoreo")

    def _drain_data_queue(self):
        latest = None
        while True:
            try:
                latest = self.data_queue.get_nowait()
            except queue.Empty:
                break

        if latest is None:
            return

        self.latest_reading = latest
        self.session_readings.append(latest)
        self._update_metrics(latest)

        if self.save_csv_var.get():
            self._append_csv(latest)

        self.alert_manager.enqueue_if_critical(
            latest.bpm,
            latest.spo2,
            latest.temperature,
            self.token_var.get(),
            self.chat_id_var.get(),
        )

    def _update_metrics(self, reading):
        if not reading.finger_detected:
            self.bpm_var.set("--")
            self.spo2_var.set("--")
            self.temperature_var.set("--" if reading.temperature is None else f"{reading.temperature:.1f}")
            self.raw_ir_var.set("--" if reading.raw_ir is None else str(reading.raw_ir))
            self.status_var.set("Dedo no detectado o señal insuficiente.")
            return

        self.bpm_var.set("--" if reading.bpm is None else f"{reading.bpm:.1f}")
        self.spo2_var.set("--" if reading.spo2 is None else f"{reading.spo2:.1f}")
        self.temperature_var.set("--" if reading.temperature is None else f"{reading.temperature:.1f}")
        self.raw_ir_var.set("--" if reading.raw_ir is None else str(reading.raw_ir))
        self.status_var.set("Lectura actualizada.")

    def _append_csv(self, reading):
        exists = os.path.exists(CSV_FILE)
        try:
            with open(CSV_FILE, "a", newline="", encoding="utf-8") as csvfile:
                writer = csv.writer(csvfile)
                if not exists:
                    writer.writerow(["Fecha_Hora", "BPM", "SpO2", "Temperatura", "Raw_IR"])
                writer.writerow(
                    [
                        reading.timestamp.isoformat(timespec="seconds"),
                        "" if reading.bpm is None else f"{reading.bpm:.2f}",
                        "" if reading.spo2 is None else f"{reading.spo2:.2f}",
                        "" if reading.temperature is None else f"{reading.temperature:.2f}",
                        "" if reading.raw_ir is None else reading.raw_ir,
                    ]
                )
        except Exception as exc:
            self.status_queue.put(("warning", f"No se pudo guardar CSV: {exc}"))

    def _on_close(self):
        if self.sensor_worker:
            self.sensor_worker.stop()
        self.root.after(200, self.root.destroy)


def main():
    root = tk.Tk()
    app = MedicalMonitorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

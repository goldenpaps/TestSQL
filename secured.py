#!/usr/bin/env python3
import threading
import socket
import time
import math
import os
import hmac
import sqlite3
from datetime import datetime, timezone
import tkinter as tk
from tkinter import ttk


# DNP3 data link / TCP channel
# DNP3 is disabled in this compatibility version; no DNP3 port is opened.

# Plain TCP control channel (master -> outstation)
CTRL_IP = "127.0.0.1"              # Localhost only; change only if remote access is required.
CTRL_PORT = 21000                 # control port
CTRL_AUTH_TOKEN = os.environ.get("SCADA_CONTROL_TOKEN", "")
MAX_COMMAND_BYTES = 128
MAX_COMMANDS_PER_CONNECTION = 20
CLIENT_TIMEOUT_SECONDS = 5

# Original DNP3 point index definitions retained for reference only.
TEMP_INDEX = 0       # Analog 0  (°C)
VOLT_INDEX = 1       # Analog 1  (V)
CURR_INDEX = 2       # Analog 2  (A)
POWER_INDEX = 3      # Analog 3  (kW)

GEN_INDEX = 0        # Binary 0  (Generator ON/OFF)
BREAKER_INDEX = 1    # Binary 1  (Breaker CLOSED/OPEN)

ALARM_OVERTEMP_INDEX   = 2   # Binary 2
ALARM_UNDERVOLT_INDEX  = 3   # Binary 3
ALARM_OVERLOAD_INDEX   = 4   # Binary 4


class OutstationApp:
    def __init__(self, master_window):
        self.root = master_window
        self.root.title("Smart Grid Outstation – Feeder 1")
        self.root.geometry("950x680")

        # --- UI state ---
        self.temp_value = tk.DoubleVar(value=25.0)    # °C
        self.volt_value = tk.DoubleVar(value=230.0)   # V
        self.load_kw    = tk.DoubleVar(value=2.0)     # kW "demand"

        self.gen_is_on = tk.BooleanVar(value=False)
        self.breaker_closed = tk.BooleanVar(value=True)

        # Alarm states
        self.alarm_overtemp = False
        self.alarm_undervolt = False
        self.alarm_overload = False

        # --- animation state ---
        self.gen_angle_deg = 0.0  # rotor angle

        # DNP3 is omitted in this version because pydnp3 could not be built.
        # The GUI, TCP control listener, and SQLite telemetry logging remain available.

        # TCP control socket server thread
        self.ctrl_thread = None

        # --- SQLite telemetry logging ---
        # Uses the same populate.db file as fakepopulate.py, but a separate
        # table so the existing "users" table is not overwritten.
        self.db_conn = sqlite3.connect("populate.db", check_same_thread=False)
        self.db_lock = threading.Lock()
        with self.db_lock:
            self.db_conn.execute("""
                CREATE TABLE IF NOT EXISTS scada_readings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    temperature REAL NOT NULL,
                    voltage REAL NOT NULL,
                    current REAL NOT NULL,
                    power_kw REAL NOT NULL,
                    generator_on INTEGER NOT NULL,
                    breaker_closed INTEGER NOT NULL,
                    alarm_overtemp INTEGER NOT NULL,
                    alarm_undervolt INTEGER NOT NULL,
                    alarm_overload INTEGER NOT NULL
                )
            """)
            self.db_conn.commit()
        print("[DATABASE] SQLite telemetry logging ready: populate.db / scada_readings")

        # Build GUI
        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Sample telemetry into SQLite once per second
        self.root.after(1000, self._database_sample_tick)

        # Start TCP control server in a background thread
        self.ctrl_thread = threading.Thread(target=self._start_ctrl_server, daemon=True)
        self.ctrl_thread.start()

        # Start animation loop
        self._animation_tick()

    def _on_close(self):
        """Close SQLite cleanly when the GUI exits."""
        try:
            with self.db_lock:
                self.db_conn.commit()
                self.db_conn.close()
        finally:
            self.root.destroy()

    # ---------------- GUI ----------------

    def _build_ui(self):
        # --- Color palette ---
        BG = "#f4f7fa"
        CARD_BG = "#ffffff"
        CARD_BORDER = "#d0d7df"
        FG = "#1d242b"
        MUTED = "#5f6b78"
        ACCENT = "#007bff"
        DANGER = "#d9534f" 
        SUCCESS = "#f0ad4e"

        self.root.configure(bg=BG)

        # ttk style
        style = ttk.Style(self.root)
        style.theme_use("clam")

        style.configure(
            ".", 
            background=BG,
            foreground=FG,
            font=("Segoe UI", 10)
        )

        style.configure(
            "Title.TLabel",
            background=BG,
            foreground=ACCENT,
            font=("Segoe UI", 18, "bold")
        )

        style.configure(
            "Card.TLabelframe",
            background=CARD_BG,
            foreground=ACCENT,
            bordercolor=CARD_BORDER,
            relief="solid",
            borderwidth=1
        )
        style.configure(
            "Card.TLabelframe.Label",
            background=CARD_BG,
            foreground=ACCENT,
            font=("Segoe UI", 11, "bold")
        )

        style.configure(
            "Card.TFrame",
            background=CARD_BG
        )

        # Explicit alarm styles make the active state visible consistently
        # across ttk themes on Windows.
        style.configure(
            "AlarmClear.TLabel",
            background=CARD_BG,
            foreground=MUTED,
            font=("Segoe UI", 10, "normal")
        )
        style.configure(
            "AlarmActive.TLabel",
            background=CARD_BG,
            foreground=DANGER,
            font=("Segoe UI", 10, "bold")
        )
        style.configure(
            "AlarmSummaryClear.TLabel",
            background=CARD_BG,
            foreground=SUCCESS,
            font=("Segoe UI", 10, "bold")
        )
        style.configure(
            "AlarmSummaryActive.TLabel",
            background=CARD_BG,
            foreground=DANGER,
            font=("Segoe UI", 10, "bold")
        )

        style.configure(
            "Accent.TButton",
            font=("Segoe UI", 10, "bold"),
            padding=6
        )

        style.map(
            "Accent.TButton",
            background=[("active", "#0ea5e9"), ("!disabled", ACCENT)],
            foreground=[("!disabled", BG)]
        )

        # Title
        title_frame = ttk.Frame(self.root, style="Card.TFrame", padding=(10, 10, 10, 5))
        title_frame.pack(fill="x")

        ttk.Label(
            title_frame,
            text="Smart Grid Outstation – Feeder 1",
            style="Title.TLabel"
        ).pack(side="left")

        # ---- Process values (top, full width) ----
        meas_frame = ttk.LabelFrame(
            self.root, text="Process Values", padding=10, style="Card.TLabelframe"
        )
        meas_frame.pack(fill="x", padx=10, pady=(5, 5))

        # Temperature
        ttk.Label(meas_frame, text="Temperature (°C)").grid(row=0, column=0, sticky="w")
        temp_slider = ttk.Scale(
            meas_frame,
            from_=-20,
            to=120,
            orient="horizontal",
            variable=self.temp_value,
            command=self._on_any_change,
        )
        temp_slider.grid(row=0, column=1, sticky="ew", padx=5)
        self.temp_label = ttk.Label(meas_frame, text="25.0 °C")
        self.temp_label.grid(row=0, column=2, sticky="w")

        # Voltage
        ttk.Label(meas_frame, text="Bus Voltage (V)").grid(row=1, column=0, sticky="w")
        volt_slider = ttk.Scale(
            meas_frame,
            from_=180,
            to=260,
            orient="horizontal",
            variable=self.volt_value,
            command=self._on_any_change,
        )
        volt_slider.grid(row=1, column=1, sticky="ew", padx=5)
        self.volt_label = ttk.Label(meas_frame, text="230.0 V")
        self.volt_label.grid(row=1, column=2, sticky="w")

        # Load
        ttk.Label(meas_frame, text="Load (kW)").grid(row=2, column=0, sticky="w")
        load_slider = ttk.Scale(
            meas_frame,
            from_=0.0,
            to=10.0,
            orient="horizontal",
            variable=self.load_kw,
            command=self._on_any_change,
        )
        load_slider.grid(row=2, column=1, sticky="ew", padx=5)
        self.load_label = ttk.Label(meas_frame, text="2.0 kW")
        self.load_label.grid(row=2, column=2, sticky="w")

        # Derived values
        ttk.Label(meas_frame, text="Line Current:").grid(row=3, column=0, sticky="w", pady=(10, 0))
        self.curr_label = ttk.Label(
            meas_frame, text="0.0 A", font=("Segoe UI", 10, "bold")
        )
        self.curr_label.grid(row=3, column=1, sticky="w", pady=(10, 0))

        ttk.Label(meas_frame, text="Delivered Power:").grid(row=4, column=0, sticky="w")
        self.power_label = ttk.Label(
            meas_frame, text="0.0 kW", font=("Segoe UI", 10, "bold")
        )
        self.power_label.grid(row=4, column=1, sticky="w")

        meas_frame.columnconfigure(1, weight=1)

        # ---- Visual single-line diagram (middle, full width) ----
        diagram_frame = ttk.LabelFrame(
            self.root, text="Single-Line Diagram & Animation",
            padding=10, style="Card.TLabelframe"
        )
        diagram_frame.pack(fill="x", padx=10, pady=(0, 5))

        self.canvas = tk.Canvas(
            diagram_frame,
            height=190,
            bg="#020617",   # deep dark
            highlightthickness=0,
        )
        self.canvas.pack(fill="x")

        # ---- Equipment status & local control (below diagram) ----
        equip_frame = ttk.LabelFrame(
            self.root, text="Equipment Status & Local Control",
            padding=10, style="Card.TLabelframe"
        )
        equip_frame.pack(fill="x", padx=10, pady=(0, 5))

        # Generator
        ttk.Label(equip_frame, text="Generator").grid(row=0, column=0, sticky="w")
        self.gen_label = ttk.Label(
            equip_frame,
            text="OFF",
            font=("Segoe UI", 11, "bold"),
            foreground=DANGER
        )
        self.gen_label.grid(row=0, column=1, sticky="w", padx=(5, 0))

        ttk.Button(
            equip_frame,
            text="Toggle (Local)",
            command=self._on_gen_button,
            width=14,
            style="Accent.TButton",
        ).grid(row=0, column=2, sticky="w", padx=(10, 0))

        # Breaker
        ttk.Label(equip_frame, text="Feeder Breaker").grid(row=1, column=0, sticky="w", pady=(5, 0))
        self.breaker_label = ttk.Label(
            equip_frame,
            text="CLOSED",
            font=("Segoe UI", 11, "bold"),
            foreground=SUCCESS
        )
        self.breaker_label.grid(row=1, column=1, sticky="w", padx=(5, 0), pady=(5, 0))

        ttk.Button(
            equip_frame,
            text="Toggle (Local)",
            command=self._on_breaker_button,
            width=14,
            style="Accent.TButton",
        ).grid(row=1, column=2, sticky="w", padx=(10, 0), pady=(5, 0))

        ttk.Label(
            equip_frame,
            text=(
                "Generator and breaker can also be operated remotely over TCP.\n"
                "Telemetry is logged locally to SQLite; DNP3 is disabled in this version.\n"
                "Alarm thresholds: temperature > 80 °C, voltage < 210 V, requested load > 5 kW."
            ),
            foreground=MUTED,
            justify="left",
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(10, 0))

        equip_frame.columnconfigure(1, weight=1)

        # ---- Alarms (bottom, full width) ----
        alarm_frame = ttk.LabelFrame(
            self.root, text="Local Alarm Indicators",
            padding=10, style="Card.TLabelframe"
        )
        alarm_frame.pack(fill="x", padx=10, pady=(0, 10))

        self.alarm_overtemp_label = ttk.Label(
            alarm_frame,
            text="Overtemperature: CLEAR",
            style="AlarmClear.TLabel"
        )
        self.alarm_overtemp_label.grid(row=0, column=0, sticky="w", pady=2)

        self.alarm_undervolt_label = ttk.Label(
            alarm_frame,
            text="Undervoltage: CLEAR",
            style="AlarmClear.TLabel"
        )
        self.alarm_undervolt_label.grid(row=0, column=1, sticky="w", pady=2, padx=(20, 0))

        self.alarm_overload_label = ttk.Label(
            alarm_frame,
            text="Overload: CLEAR",
            style="AlarmClear.TLabel"
        )
        self.alarm_overload_label.grid(row=0, column=2, sticky="w", pady=2, padx=(20, 0))

        self.alarm_summary_label = ttk.Label(
            alarm_frame,
            text="No active alarms.",
            style="AlarmSummaryClear.TLabel"
        )
        self.alarm_summary_label.grid(row=1, column=0, columnspan=3, sticky="w", pady=(10, 0))

        # store theme colors for later use in other methods
        self._theme = {
            "FG": FG,
            "MUTED": MUTED,
            "ACCENT": ACCENT,
            "DANGER": DANGER,
            "SUCCESS": SUCCESS,
        }

        # initial push
        self._recompute_and_push_telemetry()

    # ---------------- Telemetry / alarms ----------------

    def _on_any_change(self, _event=None):
        self._recompute_and_push_telemetry()

    def _on_gen_button(self):
        new_state = not self.gen_is_on.get()
        self._set_generator_state(new_state)

    def _on_breaker_button(self):
        new_state = not self.breaker_closed.get()
        self._set_breaker_state(new_state)

    def _set_generator_state(self, is_on: bool):
        print(f"[CONTROL] Generator {'ON' if is_on else 'OFF'}")
        self.gen_is_on.set(is_on)
        self.gen_label.config(
            text="ON" if is_on else "OFF",
            foreground=self._theme["SUCCESS"] if is_on else self._theme["DANGER"]
        )
        self._recompute_and_push_telemetry()

    def _set_breaker_state(self, is_closed: bool):
        print(f"[CONTROL] Breaker {'CLOSED' if is_closed else 'OPEN'}")
        self.breaker_closed.set(is_closed)
        self.breaker_label.config(
            text="CLOSED" if is_closed else "OPEN",
            foreground=self._theme["SUCCESS"] if is_closed else self._theme["DANGER"]
        )
        self._recompute_and_push_telemetry()

    def _recompute_and_push_telemetry(self):
        """
        Compute derived quantities and alarms, update labels, and save telemetry.
        """
        temp = float(self.temp_value.get())
        volt = float(self.volt_value.get())
        load_kw = float(self.load_kw.get())
        gen_on = self.gen_is_on.get()
        brk_closed = self.breaker_closed.get()

        # Update local labels
        self.temp_label.config(text=f"{temp:.1f} °C")
        self.volt_label.config(text=f"{volt:.1f} V")
        self.load_label.config(text=f"{load_kw:.1f} kW")

        # Simple model:
        if not brk_closed or not gen_on:
            power_kw = 0.0
        else:
            power_kw = load_kw

        curr_a = (power_kw * 1000.0) / volt if volt > 1.0 else 0.0

        self.curr_label.config(text=f"{curr_a:.1f} A")
        self.power_label.config(text=f"{power_kw:.1f} kW")

        # Alarms: overload is based on requested load, even if the generator/breaker is off.
        self.alarm_overtemp = (temp > 80.0)
        self.alarm_undervolt = (volt < 210.0)
        self.alarm_overload = (load_kw > 5.0)

        self._refresh_alarm_labels()

        # Save the current SCADA telemetry to SQLite.
        # This is called by the periodic sampler and whenever controls change.
        self._save_telemetry(
            temp, volt, curr_a, power_kw, gen_on, brk_closed
        )


    def _database_sample_tick(self):
        """Record a time-series sample every second."""
        try:
            self._recompute_and_push_telemetry()
        except Exception as exc:
            print(f"[DATABASE] Telemetry sample failed: {exc}")
        finally:
            if self.root.winfo_exists():
                self.root.after(1000, self._database_sample_tick)

    def _save_telemetry(self, temp, volt, curr_a, power_kw, gen_on, brk_closed):
        """Insert one snapshot of the current outstation values into SQLite."""
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        values = (
            timestamp,
            temp,
            volt,
            curr_a,
            power_kw,
            int(bool(gen_on)),
            int(bool(brk_closed)),
            int(bool(self.alarm_overtemp)),
            int(bool(self.alarm_undervolt)),
            int(bool(self.alarm_overload)),
        )
        try:
            with self.db_lock:
                self.db_conn.execute("""
                    INSERT INTO scada_readings (
                        timestamp, temperature, voltage, current, power_kw,
                        generator_on, breaker_closed,
                        alarm_overtemp, alarm_undervolt, alarm_overload
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, values)
                self.db_conn.commit()
        except sqlite3.Error as exc:
            print(f"[DATABASE] Could not save telemetry: {exc}")

    def _refresh_alarm_labels(self):
        # Use explicit ttk styles instead of per-widget foreground/font options;
        # this avoids theme-dependent rendering of alarm colors on Windows.
        self.alarm_overtemp_label.config(
            text="Overtemperature: ACTIVE" if self.alarm_overtemp else "Overtemperature: CLEAR",
            style="AlarmActive.TLabel" if self.alarm_overtemp else "AlarmClear.TLabel"
        )
        self.alarm_undervolt_label.config(
            text="Undervoltage: ACTIVE" if self.alarm_undervolt else "Undervoltage: CLEAR",
            style="AlarmActive.TLabel" if self.alarm_undervolt else "AlarmClear.TLabel"
        )
        self.alarm_overload_label.config(
            text="Overload: ACTIVE" if self.alarm_overload else "Overload: CLEAR",
            style="AlarmActive.TLabel" if self.alarm_overload else "AlarmClear.TLabel"
        )

        alarms = []
        if self.alarm_overtemp:
            alarms.append("Overtemperature")
        if self.alarm_undervolt:
            alarms.append("Undervoltage")
        if self.alarm_overload:
            alarms.append("Overload")

        if alarms:
            self.alarm_summary_label.config(
                text="ACTIVE ALARMS: " + ", ".join(alarms),
                style="AlarmSummaryActive.TLabel"
            )
        else:
            self.alarm_summary_label.config(
                text="No active alarms.",
                style="AlarmSummaryClear.TLabel"
            )

    # ---------------- Animation ----------------

    def _animation_tick(self):
        # advance generator rotor angle if ON
        if self.gen_is_on.get():
            self.gen_angle_deg = (self.gen_angle_deg + 15.0) % 360.0

        self._redraw_diagram()
        self.root.after(150, self._animation_tick)

    def _redraw_diagram(self):
        c = self.canvas
        c.delete("all")

        width = c.winfo_width() or 800
        height = c.winfo_height() or 190
        mid_y = height // 2

        ACCENT = self._theme["ACCENT"]
        DANGER = self._theme["DANGER"]
        SUCCESS = self._theme["SUCCESS"]

        # Basic positions
        gen_x = 140
        breaker_x = width // 2
        load_x = width - 100

        # Bus line
        line_color = "#4b5563"
        if self.gen_is_on.get() and self.breaker_closed.get():
            line_color = ACCENT
        c.create_line(gen_x + 40, mid_y, load_x - 20, mid_y, width=4, fill=line_color)

        # Generator body
        gen_radius = 32
        c.create_oval(
            gen_x - gen_radius,
            mid_y - gen_radius,
            gen_x + gen_radius,
            mid_y + gen_radius,
            fill="#020617",
            outline="#1f2937",
            width=3,
        )

        # Rotor blades
        angle_rad = math.radians(self.gen_angle_deg)
        for i in range(3):
            a = angle_rad + i * (2 * math.pi / 3)
            x2 = gen_x + gen_radius * math.cos(a)
            y2 = mid_y + gen_radius * math.sin(a)
            color = SUCCESS if self.gen_is_on.get() else "#4b5563"
            c.create_line(gen_x, mid_y, x2, y2, width=3, fill=color)

        c.create_text(gen_x, mid_y + gen_radius + 16, text="GEN", fill="#e5e7eb",
                      font=("Segoe UI", 9, "bold"))

        # Breaker symbol
        brk_closed = self.breaker_closed.get()
        brk_color = SUCCESS if brk_closed else DANGER

        gap = 18
        c.create_line(breaker_x - 40, mid_y, breaker_x - gap, mid_y, width=4, fill="#4b5563")
        c.create_line(breaker_x + gap, mid_y, breaker_x + 40, mid_y, width=4, fill="#4b5563")

        if brk_closed:
            c.create_line(breaker_x - gap, mid_y, breaker_x + gap, mid_y,
                          width=6, fill=brk_color)
        else:
            c.create_line(breaker_x - gap, mid_y - 13, breaker_x - gap, mid_y + 13,
                          width=4, fill=brk_color)
            c.create_line(breaker_x + gap, mid_y - 13, breaker_x + gap, mid_y + 13,
                          width=4, fill=brk_color)

        c.create_text(breaker_x, mid_y + 26, text="BREAKER", fill="#e5e7eb",
                      font=("Segoe UI", 9, "bold"))

        # Load box
        c.create_rectangle(
            load_x - 30, mid_y - 22, load_x + 30, mid_y + 22,
            fill="#020617", outline="#1f2937", width=3
        )
        c.create_text(load_x, mid_y, text="LOAD", fill="#e5e7eb", font=("Segoe UI", 9, "bold"))

        # Temperature thermometer
        temp = float(self.temp_value.get())
        if temp <= 40:
            t_color = "#38bdf8"
        elif temp <= 80:
            t_color = "#fbbf24"
        else:
            t_color = DANGER

        thermo_x = width - 60
        thermo_top = 20
        thermo_bottom = height - 20

        c.create_rectangle(
            thermo_x - 8, thermo_top, thermo_x + 8, thermo_bottom - 18,
            outline="#475569", width=2
        )
        c.create_oval(
            thermo_x - 14, thermo_bottom - 30,
            thermo_x + 14, thermo_bottom - 2,
            outline="#475569", width=2, fill="#020617"
        )

        min_t, max_t = -20.0, 120.0
        t_clamped = max(min_t, min(max_t, temp))
        frac = (t_clamped - min_t) / (max_t - min_t)
        level = thermo_top + (thermo_bottom - 32 - thermo_top) * (1.0 - frac)

        c.create_rectangle(
            thermo_x - 6, level,
            thermo_x + 6, thermo_bottom - 20,
            outline="", fill=t_color
        )
        c.create_oval(
            thermo_x - 12, thermo_bottom - 28,
            thermo_x + 12, thermo_bottom - 4,
            outline="", fill=t_color
        )

        c.create_text(
            thermo_x - 25, thermo_top + 12,
            text="TEMP",
            font=("Segoe UI", 8, "bold"),
            anchor="w",
            fill="#9ca3af"
        )

    # ---------------- Authenticated TCP control server ----------------

    def _start_ctrl_server(self):
        # Fail closed: do not expose a control listener without a configured secret.
        if not CTRL_AUTH_TOKEN:
            print("[TCP CONTROL] DISABLED: set SCADA_CONTROL_TOKEN before starting.")
            return

        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            server.bind((CTRL_IP, CTRL_PORT))
            server.listen(5)
            print(f"[TCP CONTROL] Listening on {CTRL_IP}:{CTRL_PORT} (authentication required)")
        except OSError as exc:
            print(f"[TCP CONTROL] Could not listen on port {CTRL_PORT}: {exc}")
            server.close()
            return

        while True:
            try:
                conn, addr = server.accept()
                threading.Thread(target=self._handle_ctrl_client, args=(conn, addr), daemon=True).start()
            except OSError as exc:
                print(f"[TCP CONTROL] Accept failed: {exc}")
                break

    def _handle_ctrl_client(self, conn, addr):
        authenticated = False
        command_count = 0
        buf = b""
        try:
            with conn:
                conn.settimeout(CLIENT_TIMEOUT_SECONDS)
                print(f"[TCP CONTROL] Client connected from {addr[0]}:{addr[1]}")
                while True:
                    data = conn.recv(256)
                    if not data:
                        break
                    buf += data
                    if len(buf) > MAX_COMMAND_BYTES and b"\\n" not in buf:
                        conn.sendall(b"ERR command too long\\n")
                        return

                    while b"\\n" in buf:
                        line, buf = buf.split(b"\\n", 1)
                        if len(line) > MAX_COMMAND_BYTES:
                            conn.sendall(b"ERR command too long\\n")
                            return
                        try:
                            cmd = line.decode("ascii").strip()
                        except UnicodeDecodeError:
                            conn.sendall(b"ERR ASCII commands only\\n")
                            return
                        if not cmd:
                            conn.sendall(b"ERR empty command\\n")
                            continue

                        # Every TCP connection must authenticate before issuing controls.
                        if not authenticated:
                            parts = cmd.split()
                            if (len(parts) == 2 and parts[0] == "AUTH"
                                    and hmac.compare_digest(parts[1], CTRL_AUTH_TOKEN)):
                                authenticated = True
                                conn.sendall(b"OK authenticated\\n")
                                continue
                            print(f"[TCP CONTROL] Rejected unauthenticated client {addr[0]}")
                            conn.sendall(b"ERR authentication required\\n")
                            return

                        command_count += 1
                        if command_count > MAX_COMMANDS_PER_CONNECTION:
                            conn.sendall(b"ERR command limit exceeded\\n")
                            return

                        # Exact allowlist blocks malformed commands and extra arguments.
                        parts = cmd.split()
                        if (len(parts) != 2 or parts[0] not in ("GEN", "BRK")
                                or parts[1] not in ("ON", "OFF", "TOGGLE")):
                            print(f"[TCP CONTROL] Rejected invalid command from {addr[0]}")
                            conn.sendall(b"ERR invalid command\\n")
                            continue

                        print(f"[TCP CONTROL] Accepted authenticated command: {parts[0]} {parts[1]}")
                        if parts[0] == "GEN":
                            self._handle_gen_command([parts[1]])
                        else:
                            self._handle_breaker_command([parts[1]])
                        conn.sendall(b"OK command queued\\n")
        except (socket.timeout, OSError) as exc:
            print(f"[TCP CONTROL] Client {addr[0]} disconnected/error: {exc}")
        finally:
            print(f"[TCP CONTROL] Connection closed for {addr[0]}")

    def _handle_gen_command(self, args):
        # Defense in depth: validate again before scheduling a state change.
        if len(args) != 1 or args[0] not in ("ON", "OFF", "TOGGLE"):
            print("[TCP CONTROL] Rejected invalid generator action.")
            return
        action = args[0]
        if action == "ON":
            self.root.after(0, lambda: self._set_generator_state(True))
        elif action == "OFF":
            self.root.after(0, lambda: self._set_generator_state(False))
        elif action == "TOGGLE":
            self.root.after(0, lambda: self._set_generator_state(not self.gen_is_on.get()))

    def _handle_breaker_command(self, args):
        # Defense in depth: validate again before scheduling a state change.
        if len(args) != 1 or args[0] not in ("ON", "OFF", "TOGGLE"):
            print("[TCP CONTROL] Rejected invalid breaker action.")
            return
        action = args[0]
        if action == "ON":
            self.root.after(0, lambda: self._set_breaker_state(True))
        elif action == "OFF":
            self.root.after(0, lambda: self._set_breaker_state(False))
        elif action == "TOGGLE":
            self.root.after(0, lambda: self._set_breaker_state(not self.breaker_closed.get()))


def main():
    root = tk.Tk()
    app = OutstationApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()


#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
# Ai assisted Code by RBolisay
import Tkinter as tk
import ttk
import tkFileDialog
import os
import threading
import time # For simulating pauses if needed
import math # For Lat/Lon formatting
import json # For saving/loading settings
import csv  # For writing CSV files
import errno # For checking directory errors
import tkFont # For setting monospaced font
from collections import OrderedDict # ADDED for preserving order
import re # Import regex for streamer ID parsing

# --- Helper Function for Lat/Lon Formatting (SHARED UTILITY) ---
def format_decimal_degrees_to_deg_min(dec_deg, axis):
    try:
        dec_deg_float = float(dec_deg)
        if axis.lower() == 'lat': hemi = 'N' if dec_deg_float >= 0 else 'S'
        elif axis.lower() == 'lon': hemi = 'E' if dec_deg_float >= 0 else 'W'
        else: return "Invalid Axis"
        dec_deg_float = abs(dec_deg_float)
        degrees = int(math.floor(dec_deg_float))
        minutes = (dec_deg_float - degrees) * 60.0
        return "{} {:.2f} {}".format(degrees, minutes, hemi)
    except (ValueError, TypeError) as e:
        return "Format Error"

# --- Helper for Directory Creation (SHARED UTILITY) ---
def _ensure_dir_exists(path):
    try: os.makedirs(path)
    except OSError as e:
        if e.errno != errno.EEXIST: raise

# --- Feather Calculation Helper Functions (SHARED UTILITY) ---
def calculate_azimuth(x1, y1, x2, y2):
    """Calculates azimuth (degrees clockwise from North) between two points."""
    try:
        dx = float(x2) - float(x1); dy = float(y2) - float(y1)
        if abs(dx) < 1e-6 and abs(dy) < 1e-6 : return None
        rad = math.atan2(dx, dy)
        deg = math.degrees(rad)
        azimuth = (deg + 360.0) % 360.0
        return azimuth
    except (ValueError, TypeError):
        return None

def angle_difference(angle1, angle2):
    """Calculates the smallest difference between two angles (degrees)."""
    if angle1 is None or angle2 is None: return None
    diff = angle1 - angle2
    while diff <= -180: diff += 360
    while diff > 180: diff -= 360
    return diff

# --- MODIFIED Feather Calculation Function (User Requested Formula) ---
def calculate_feather(r1_pos, r_last_pos, line_dir_deg):
    """Calculates feather angle using user formula: (line_dir+180) - streamer_azimuth, normalized."""
    if not all([r1_pos, r_last_pos, line_dir_deg is not None]): return None
    if not (isinstance(r1_pos, (list, tuple)) and len(r1_pos) >= 2 and
            isinstance(r_last_pos, (list, tuple)) and len(r_last_pos) >= 2):
        return None
    try:
        e1, n1 = float(r1_pos[0]), float(r1_pos[1])
        e_last, n_last = float(r_last_pos[0]), float(r_last_pos[1])
        line_dir = float(line_dir_deg)

        streamer_azimuth = calculate_azimuth(e1, n1, e_last, n_last)
        if streamer_azimuth is None: return None

        reciprocal_line_dir = (line_dir + 180.0) % 360.0
        raw_feather = reciprocal_line_dir - streamer_azimuth
        feather = (raw_feather + 180.0) % 360.0 - 180.0

        return "%.1f" % feather if feather is not None else None
    except (ValueError, TypeError, IndexError) as e:
        print "Error during feather calculation:", e
        return None
# --- END MODIFIED Feather Calculation Function ---


# --- Formatting Constants ---
VESSEL_PREVIEW_FORMAT = "{:<16} {:<15} {:<10} {:<16} {:<16} {:<15} {:<12} {:<15} {:<15} {:<12}"
VESSEL_CSV_HEADER = ["Sequence Number", "Line Name", "Subline", "Shotpoint Number", "Preplot Number", "Latitude", "Longitude", "Easting", "Northing", "Water Depth"]
SOURCE_PREVIEW_FORMAT = "{:<16} {:<15} {:<10} {:<16} {:<16} {:<13} {:<15} {:<15} {:<15} {:<15}"
SOURCE_CSV_HEADER = ["Sequence Number", "Line Name", "Subline", "Shotpoint Number", "Preplot Number", "Source Fired", "Latitude", "Longitude", "Easting", "Northing"]
ECHOSOUNDER_PREVIEW_FORMAT = "{:<16} {:<15} {:<10} {:<16} {:<16} {:<15} {:<12} {:<15} {:<15} {:<12}"
ECHOSOUNDER_CSV_HEADER = ["Sequence Number", "Line Name", "Subline", "Shotpoint Number", "Preplot Number", "Latitude", "Longitude", "Easting", "Northing", "Water Depth"]
FEATHER_CSV_HEADER = ["Sequence Number", "Line Name", "Subline", "Shotpoint Number", "Preplot Number", "Vsl Latitude", "Vsl Longitude", "Vsl Easting", "Vsl Northing", "Streamer Feather"]
FEATHER_PREVIEW_FORMAT = "{:<16} {:<15} {:<10} {:<16} {:<16} {:<13} {:<14} {:<13} {:<14} {:<17}"
assert len(FEATHER_CSV_HEADER) == len(FEATHER_PREVIEW_FORMAT.split('{')) - 1

# --- Field Indices ---
P_REC_SPN_IDX=4; P_REC_PREPLOT_IDX=5; P_REC_DEVICE_ID_IDX=9; P_REC_EASTING_IDX=12; P_REC_NORTHING_IDX=13; P_REC_LATITUDE_IDX=15; P_REC_LONGITUDE_IDX=16
S1_REC_SPN_IDX=4; S1_REC_PREPLOT_IDX=5; S1_REC_SOURCE_FIRED_IDX=9; S1_REC_EASTING_IDX=12; S1_REC_NORTHING_IDX=13; S1_REC_LATITUDE_IDX=15; S1_REC_LONGITUDE_IDX=16
R_SPN_IDX=4; R_PREPLOT_IDX=5; R_STREAMER_ID_IDX=9; R_RECEIVER_NUM_IDX=11; R_EASTING_IDX=12; R_NORTHING_IDX=13

# Header Card Prefixes
CC_SEQUENCE_PREFIX = 'CC,1,0,0,LINE SEQUENCE NUMBER ='; CC_LINENAME_PREFIX = 'CC,1,0,0,LINENAME/SUBLINE ='; CC_LINE_DIRECTION_PREFIX = 'CC,1,0,0,LINE-DIRECTION ='; HC_STREAMER_PREFIX = 'HC,2,3,0,Streamer '
HC_DEVICE_PREFIX = 'HC,2,3,'

# --- Robust Sequence Sort Key ---
def robust_sequence_sort_key(seq_name):
    if seq_name == "N/A":
        return (1, "")  # Group "N/A" last by giving it a higher primary sort key
    try:
        # Attempt to convert to int for numeric parts of sequence names if they are purely numeric
        return (0, int(seq_name))
    except ValueError:
        # Fallback to string sort for alphanumeric sequence names
        return (0, seq_name)

# --- Main Application Class ---
class P111ExtractorApp(tk.Tk):

    def __init__(self):
        tk.Tk.__init__(self); self.title("xP111 - Data Extractor (Independent Tabs)"); self.settings_dir = "/usr/local/trinop/dbase/links/qcfiles/Misc/xP111_Extractor"; self.settings_file = os.path.join(self.settings_dir, "settings.json")
        self._apply_custom_styles()
        self._init_vessel_vars()
        self._init_source_vars()
        self._init_echosounder_vars()
        self._init_feather_vars()
        self._init_fonts(); self._load_settings(); self._create_widgets(); self._configure_preview_tags(); self.protocol("WM_DELETE_WINDOW", self._on_closing)

    def _apply_custom_styles(self):
        gui_bg_color = "#B4C8E1"; button_bg_color = "#8DA9CC"; button_text_color = "black"
        style = ttk.Style(self); self.configure(background=gui_bg_color)
        style.configure("TFrame", background=gui_bg_color)
        style.map("TNotebook.Tab", background=[("selected", gui_bg_color), ("!selected", gui_bg_color)], foreground=[("selected", "black"), ("!selected", "gray")])
        style.configure("TNotebook.Tab", padding=[5, 2], font=('TkDefaultFont', 10))
        style.configure("Custom.TButton", background=button_bg_color, foreground=button_text_color, relief="raised")
        style.map("Custom.TButton", background=[('active', button_bg_color), ('pressed', button_bg_color)])
        style.configure("TLabel", background=gui_bg_color, foreground="black")
        style.configure("TCheckbutton", background=gui_bg_color, foreground="black")

    def _init_vessel_vars(self):
        self.vessel_p111_files=[]; self.vessel_output_dir_var=tk.StringVar(); self.vessel_last_p111_dir=None; self.vessel_default_output_dir="/usr/local/trinop/dbase/links/qcfiles/Misc/xP111_Output_Vessel"; self.vessel_individual_csv_var=tk.BooleanVar(value=True); self.vessel_pause_preview_var=tk.BooleanVar(value=False); self.vessel_extraction_running=False; self.vessel_cancel_extraction_flag=False;
        self.vessel_id=None; self.vessel_extraction_thread=None

    def _init_source_vars(self):
        self.source_p111_files=[]; self.source_output_dir_var=tk.StringVar(); self.source_last_p111_dir=None; self.source_default_output_dir="/usr/local/trinop/dbase/links/qcfiles/Misc/xP111_Output_Source"; self.source_individual_csv_var=tk.BooleanVar(value=True); self.source_pause_preview_var=tk.BooleanVar(value=False); self.source_extraction_running=False; self.source_cancel_extraction_flag=False; self.source_extraction_thread=None

    def _init_echosounder_vars(self):
        self.echosounder_p111_files=[]; self.echosounder_output_dir_var=tk.StringVar(); self.echosounder_last_p111_dir=None; self.echosounder_default_output_dir="/usr/local/trinop/dbase/links/qcfiles/Misc/xP111_Output_Echosounder"; self.echosounder_individual_csv_var=tk.BooleanVar(value=True); self.echosounder_pause_preview_var=tk.BooleanVar(value=False); self.echosounder_extraction_running=False; self.echosounder_cancel_extraction_flag=False; self.echosounder_extraction_thread=None

    def _init_feather_vars(self):
        self.feather_p111_files=[]; self.feather_output_dir_var=tk.StringVar(); self.feather_last_p111_dir=None; self.feather_default_output_dir="/usr/local/trinop/dbase/links/qcfiles/Misc/xP111_Output_Feather"; self.feather_individual_csv_var=tk.BooleanVar(value=True); self.feather_pause_preview_var=tk.BooleanVar(value=False); self.feather_extraction_running=False; self.feather_cancel_extraction_flag=False; self.feather_extraction_thread=None; self.feather_streamer_prefix=None; self.feather_first_rx_id=None; self.feather_last_rx_id=None

    def _init_fonts(self):
        try: base_font_family = "Courier"; self.mono_font = tkFont.Font(family=base_font_family, size=10); self.mono_font_bold = tkFont.Font(family=base_font_family, size=10, weight='bold')
        except tk.TclError:
            try: base_font_family = "Consolas"; self.mono_font = tkFont.Font(family=base_font_family, size=10); self.mono_font_bold = tkFont.Font(family=base_font_family, size=10, weight='bold')
            except tk.TclError:
                try: base_font_family = "Monaco"; self.mono_font = tkFont.Font(family=base_font_family, size=10); self.mono_font_bold = tkFont.Font(family=base_font_family, size=10, weight='bold')
                except tk.TclError: base_font_family = "TkFixedFont"; self.mono_font = tkFont.Font(family=base_font_family, size=10); self.mono_font_bold = tkFont.Font(family=base_font_family, size=10, weight='bold')
        print "Using font family:", base_font_family

    def _configure_preview_tags(self):
        if hasattr(self,'vessel_preview_text'): self.vessel_preview_text.tag_configure('bold_header',font=self.mono_font_bold)
        if hasattr(self,'source_preview_text'): self.source_preview_text.tag_configure('bold_header',font=self.mono_font_bold)
        if hasattr(self,'echosounder_preview_text'): self.echosounder_preview_text.tag_configure('bold_header',font=self.mono_font_bold)
        if hasattr(self,'feather_preview_text'): self.feather_preview_text.tag_configure('bold_header',font=self.mono_font_bold)

    def _load_settings(self):
        loaded_geometry=None; settings={}
        try:
            _ensure_dir_exists(self.settings_dir);
            if os.path.exists(self.settings_file):
                with open(self.settings_file,'r') as f: settings=json.load(f)
            loaded_geometry=settings.get('window_geometry')
            self.vessel_last_p111_dir=settings.get('vessel_last_p111_dir'); self.vessel_output_dir_var.set(settings.get('vessel_output_dir',self.vessel_default_output_dir))
            self.source_last_p111_dir=settings.get('source_last_p111_dir'); self.source_output_dir_var.set(settings.get('source_output_dir',self.source_default_output_dir))
            self.echosounder_last_p111_dir=settings.get('echosounder_last_p111_dir'); self.echosounder_output_dir_var.set(settings.get('echosounder_output_dir',self.echosounder_default_output_dir))
            self.feather_last_p111_dir=settings.get('feather_last_p111_dir'); self.feather_output_dir_var.set(settings.get('feather_output_dir',self.feather_default_output_dir))
        except (IOError,ValueError,KeyError,OSError) as e: print("Warning: Could not load/create settings from {}: {}".format(self.settings_file,e)); self.vessel_output_dir_var.set(self.vessel_default_output_dir); self.source_output_dir_var.set(self.source_default_output_dir); self.echosounder_output_dir_var.set(self.echosounder_default_output_dir); self.feather_output_dir_var.set(self.feather_default_output_dir)
        if not self.vessel_output_dir_var.get(): self.vessel_output_dir_var.set(self.vessel_default_output_dir)
        if not self.source_output_dir_var.get(): self.source_output_dir_var.set(self.source_default_output_dir)
        if not self.echosounder_output_dir_var.get(): self.echosounder_output_dir_var.set(self.echosounder_default_output_dir)
        if not self.feather_output_dir_var.get(): self.feather_output_dir_var.set(self.feather_default_output_dir)
        if loaded_geometry:
            try: self.geometry(loaded_geometry)
            except tk.TclError as e: print("Warning: Could not apply saved window geometry '{}': {}".format(loaded_geometry,e))

    def _save_settings(self):
        settings={}
        try:
            settings['window_geometry']=self.winfo_geometry()
            if self.vessel_last_p111_dir: settings['vessel_last_p111_dir']=self.vessel_last_p111_dir; settings['vessel_output_dir']=self.vessel_output_dir_var.get()
            if self.source_last_p111_dir: settings['source_last_p111_dir']=self.source_last_p111_dir; settings['source_output_dir']=self.source_output_dir_var.get()
            if self.echosounder_last_p111_dir: settings['echosounder_last_p111_dir']=self.echosounder_last_p111_dir; settings['echosounder_output_dir']=self.echosounder_output_dir_var.get()
            if self.feather_last_p111_dir: settings['feather_last_p111_dir']=self.feather_last_p111_dir; settings['feather_output_dir']=self.feather_output_dir_var.get()
            _ensure_dir_exists(self.settings_dir);
            with open(self.settings_file,'w') as f: json.dump(settings, f, indent=4)
        except (IOError, tk.TclError, OSError) as e: print("Warning: Could not save settings to {}: {}".format(self.settings_file, e))

    def _on_closing(self):
        if self.vessel_extraction_running: self._cancel_vessel_extraction()
        if self.source_extraction_running: self._cancel_source_extraction()
        if self.echosounder_extraction_running: self._cancel_echosounder_extraction()
        if self.feather_extraction_running: self._cancel_feather_calculation()
        self._save_settings(); self.destroy()

    def _create_widgets(self):
        main_frame = ttk.Frame(self, padding="10", style="TFrame") 
        main_frame.pack(fill=tk.BOTH, expand=True)
        self.notebook = ttk.Notebook(main_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True, pady=(0, 5))
        self.vessel_tab = ttk.Frame(self.notebook, padding="5", style="TFrame") 
        self.source_tab = ttk.Frame(self.notebook, padding="5", style="TFrame") 
        self.echosounder_tab = ttk.Frame(self.notebook, padding="5", style="TFrame") 
        self.feather_tab = ttk.Frame(self.notebook, padding="5", style="TFrame") 
        self.notebook.add(self.vessel_tab, text='Vessel Data'); self.notebook.add(self.source_tab, text='Source Data')
        self.notebook.add(self.echosounder_tab, text='Echosounder Data'); self.notebook.add(self.feather_tab, text='Feather Data')
        self._create_vessel_tab_content(self.vessel_tab)
        self._create_source_tab_content(self.source_tab)
        self._create_echosounder_tab_content(self.echosounder_tab)
        self._create_feather_tab_content(self.feather_tab)

    def _create_vessel_tab_content(self, parent_tab):
        parent_tab.columnconfigure(1, weight=1); parent_tab.rowconfigure(5, weight=1); parent_tab.rowconfigure(7, weight=1)
        desc_label = ttk.Label(parent_tab, text="Extract Vessel Data from P111 to CSV")
        desc_label.grid(row=0, column=0, columnspan=3, sticky="w", padx=5, pady=(0, 10))
        ttk.Label(parent_tab, text="P111 input file(s):").grid(row=1, column=0, sticky="w", padx=5, pady=2)
        vessel_file_list_frame = ttk.Frame(parent_tab, style="TFrame") 
        vessel_file_list_frame.grid(row=1, column=1, sticky="ew", padx=5, pady=2); vessel_file_list_frame.columnconfigure(0, weight=1)
        self.vessel_file_list_text = tk.Text(vessel_file_list_frame, height=4, width=50, wrap=tk.WORD, state=tk.DISABLED, background="white", relief=tk.SUNKEN, borderwidth=1) 
        vessel_file_scroll = ttk.Scrollbar(vessel_file_list_frame, orient=tk.VERTICAL, command=self.vessel_file_list_text.yview); self.vessel_file_list_text['yscrollcommand'] = vessel_file_scroll.set
        self.vessel_file_list_text.grid(row=0, column=0, sticky="ew"); vessel_file_scroll.grid(row=0, column=1, sticky="ns")
        vessel_browse_files_btn = ttk.Button(parent_tab, text="Browse...", command=self._select_vessel_p111_files, style="Custom.TButton") 
        vessel_browse_files_btn.grid(row=1, column=2, sticky="w", padx=5, pady=2)
        ttk.Label(parent_tab, text="Output CSV directory:").grid(row=2, column=0, sticky="w", padx=5, pady=2)
        vessel_output_dir_entry = ttk.Entry(parent_tab, textvariable=self.vessel_output_dir_var, width=60)
        vessel_output_dir_entry.grid(row=2, column=1, sticky="ew", padx=5, pady=2)
        vessel_browse_dir_btn = ttk.Button(parent_tab, text="Browse...", command=self._select_vessel_output_dir, style="Custom.TButton") 
        vessel_browse_dir_btn.grid(row=2, column=2, sticky="w", padx=5, pady=2)
        vessel_individual_csv_check = ttk.Checkbutton(parent_tab, text="Create individual CSV per sequence", variable=self.vessel_individual_csv_var, style="TCheckbutton") 
        vessel_individual_csv_check.grid(row=3, column=1, sticky="w", padx=5, pady=5)
        ttk.Label(parent_tab, text="Results Preview:").grid(row=4, column=0, sticky="nw", padx=5, pady=(10, 2))
        vessel_pause_preview_check = ttk.Checkbutton(parent_tab, text="Pause Preview", variable=self.vessel_pause_preview_var, style="TCheckbutton") 
        vessel_pause_preview_check.grid(row=4, column=1, columnspan=2, sticky="w", padx=5, pady=(10,2))
        vessel_preview_frame = ttk.Frame(parent_tab, style="TFrame") 
        vessel_preview_frame.grid(row=5, column=0, columnspan=3, sticky="nsew", padx=5, pady=2); vessel_preview_frame.rowconfigure(0, weight=1); vessel_preview_frame.columnconfigure(0, weight=1)
        self.vessel_preview_text = tk.Text(vessel_preview_frame, height=10, width=80, wrap=tk.NONE, state=tk.DISABLED, font=self.mono_font, background="white", relief=tk.SUNKEN, borderwidth=1) 
        vessel_preview_scroll_y = ttk.Scrollbar(vessel_preview_frame, orient=tk.VERTICAL, command=self.vessel_preview_text.yview); vessel_preview_scroll_x = ttk.Scrollbar(vessel_preview_frame, orient=tk.HORIZONTAL, command=self.vessel_preview_text.xview)
        self.vessel_preview_text['yscrollcommand'] = vessel_preview_scroll_y.set; self.vessel_preview_text['xscrollcommand'] = vessel_preview_scroll_x.set
        self.vessel_preview_text.grid(row=0, column=0, sticky="nsew"); vessel_preview_scroll_y.grid(row=0, column=1, sticky="ns"); vessel_preview_scroll_x.grid(row=1, column=0, sticky="ew")
        ttk.Label(parent_tab, text="Errors / Status Logs:").grid(row=6, column=0, sticky="w", padx=5, pady=(10, 2))
        vessel_log_frame = ttk.Frame(parent_tab, style="TFrame") 
        vessel_log_frame.grid(row=7, column=0, columnspan=3, sticky="nsew", padx=5, pady=2); vessel_log_frame.rowconfigure(0, weight=1); vessel_log_frame.columnconfigure(0, weight=1)
        self.vessel_log_text = tk.Text(vessel_log_frame, height=6, width=80, wrap=tk.WORD, state=tk.DISABLED, background="white", relief=tk.SUNKEN, borderwidth=1) 
        vessel_log_scroll = ttk.Scrollbar(vessel_log_frame, orient=tk.VERTICAL, command=self.vessel_log_text.yview); self.vessel_log_text['yscrollcommand'] = vessel_log_scroll.set
        self.vessel_log_text.grid(row=0, column=0, sticky="nsew"); vessel_log_scroll.grid(row=0, column=1, sticky="ns")
        vessel_button_frame = ttk.Frame(parent_tab, style="TFrame") 
        vessel_button_frame.grid(row=8, column=0, columnspan=3, pady=(10, 0))
        self.vessel_start_button = ttk.Button(vessel_button_frame, text="Start Extraction", command=self._start_vessel_extraction, style="Custom.TButton") 
        self.vessel_start_button.pack(side=tk.LEFT, padx=5)
        self.vessel_cancel_button = ttk.Button(vessel_button_frame, text="Cancel Extraction", command=self._cancel_vessel_extraction, state=tk.DISABLED, style="Custom.TButton") 
        self.vessel_cancel_button.pack(side=tk.LEFT, padx=5)

    def _create_source_tab_content(self, parent_tab):
        parent_tab.columnconfigure(1, weight=1); parent_tab.rowconfigure(5, weight=1); parent_tab.rowconfigure(7, weight=1)
        desc_label = ttk.Label(parent_tab, text="Extract Source Data from P111 to CSV")
        desc_label.grid(row=0, column=0, columnspan=3, sticky="w", padx=5, pady=(0, 10))
        ttk.Label(parent_tab, text="P111 input file(s):").grid(row=1, column=0, sticky="w", padx=5, pady=2)
        source_file_list_frame = ttk.Frame(parent_tab, style="TFrame") 
        source_file_list_frame.grid(row=1, column=1, sticky="ew", padx=5, pady=2); source_file_list_frame.columnconfigure(0, weight=1)
        self.source_file_list_text = tk.Text(source_file_list_frame, height=4, width=50, wrap=tk.WORD, state=tk.DISABLED, background="white", relief=tk.SUNKEN, borderwidth=1) 
        source_file_scroll = ttk.Scrollbar(source_file_list_frame, orient=tk.VERTICAL, command=self.source_file_list_text.yview); self.source_file_list_text['yscrollcommand'] = source_file_scroll.set
        self.source_file_list_text.grid(row=0, column=0, sticky="ew"); source_file_scroll.grid(row=0, column=1, sticky="ns")
        source_browse_files_btn = ttk.Button(parent_tab, text="Browse...", command=self._select_source_p111_files, style="Custom.TButton") 
        source_browse_files_btn.grid(row=1, column=2, sticky="w", padx=5, pady=2)
        ttk.Label(parent_tab, text="Output CSV directory:").grid(row=2, column=0, sticky="w", padx=5, pady=2)
        source_output_dir_entry = ttk.Entry(parent_tab, textvariable=self.source_output_dir_var, width=60)
        source_output_dir_entry.grid(row=2, column=1, sticky="ew", padx=5, pady=2)
        source_browse_dir_btn = ttk.Button(parent_tab, text="Browse...", command=self._select_source_output_dir, style="Custom.TButton") 
        source_browse_dir_btn.grid(row=2, column=2, sticky="w", padx=5, pady=2)
        source_individual_csv_check = ttk.Checkbutton(parent_tab, text="Create individual CSV per sequence", variable=self.source_individual_csv_var, style="TCheckbutton") 
        source_individual_csv_check.grid(row=3, column=1, sticky="w", padx=5, pady=5)
        ttk.Label(parent_tab, text="Results Preview:").grid(row=4, column=0, sticky="nw", padx=5, pady=(10, 2))
        source_pause_preview_check = ttk.Checkbutton(parent_tab, text="Pause Preview", variable=self.source_pause_preview_var, style="TCheckbutton") 
        source_pause_preview_check.grid(row=4, column=1, columnspan=2, sticky="w", padx=5, pady=(10,2))
        source_preview_frame = ttk.Frame(parent_tab, style="TFrame") 
        source_preview_frame.grid(row=5, column=0, columnspan=3, sticky="nsew", padx=5, pady=2); source_preview_frame.rowconfigure(0, weight=1); source_preview_frame.columnconfigure(0, weight=1)
        self.source_preview_text = tk.Text(source_preview_frame, height=10, width=80, wrap=tk.NONE, state=tk.DISABLED, font=self.mono_font, background="white", relief=tk.SUNKEN, borderwidth=1) 
        source_preview_scroll_y = ttk.Scrollbar(source_preview_frame, orient=tk.VERTICAL, command=self.source_preview_text.yview); source_preview_scroll_x = ttk.Scrollbar(source_preview_frame, orient=tk.HORIZONTAL, command=self.source_preview_text.xview)
        self.source_preview_text['yscrollcommand'] = source_preview_scroll_y.set; self.source_preview_text['xscrollcommand'] = source_preview_scroll_x.set
        self.source_preview_text.grid(row=0, column=0, sticky="nsew"); source_preview_scroll_y.grid(row=0, column=1, sticky="ns"); source_preview_scroll_x.grid(row=1, column=0, sticky="ew")
        ttk.Label(parent_tab, text="Errors / Status Logs:").grid(row=6, column=0, sticky="w", padx=5, pady=(10, 2))
        source_log_frame = ttk.Frame(parent_tab, style="TFrame") 
        source_log_frame.grid(row=7, column=0, columnspan=3, sticky="nsew", padx=5, pady=2); source_log_frame.rowconfigure(0, weight=1); source_log_frame.columnconfigure(0, weight=1)
        self.source_log_text = tk.Text(source_log_frame, height=6, width=80, wrap=tk.WORD, state=tk.DISABLED, background="white", relief=tk.SUNKEN, borderwidth=1) 
        source_log_scroll = ttk.Scrollbar(source_log_frame, orient=tk.VERTICAL, command=self.source_log_text.yview); self.source_log_text['yscrollcommand'] = source_log_scroll.set
        self.source_log_text.grid(row=0, column=0, sticky="nsew"); source_log_scroll.grid(row=0, column=1, sticky="ns")
        source_button_frame = ttk.Frame(parent_tab, style="TFrame") 
        source_button_frame.grid(row=8, column=0, columnspan=3, pady=(10, 0))
        self.source_start_button = ttk.Button(source_button_frame, text="Start Extraction", command=self._start_source_extraction, style="Custom.TButton") 
        self.source_start_button.pack(side=tk.LEFT, padx=5)
        self.source_cancel_button = ttk.Button(source_button_frame, text="Cancel Extraction", command=self._cancel_source_extraction, state=tk.DISABLED, style="Custom.TButton") 
        self.source_cancel_button.pack(side=tk.LEFT, padx=5)

    def _create_echosounder_tab_content(self, parent_tab):
        parent_tab.columnconfigure(1, weight=1); parent_tab.rowconfigure(5, weight=1); parent_tab.rowconfigure(7, weight=1)
        desc_label = ttk.Label(parent_tab, text="Extract Echosounder Data from P111 to CSV")
        desc_label.grid(row=0, column=0, columnspan=3, sticky="w", padx=5, pady=(0, 10))
        ttk.Label(parent_tab, text="P111 input file(s):").grid(row=1, column=0, sticky="w", padx=5, pady=2)
        echosounder_file_list_frame = ttk.Frame(parent_tab, style="TFrame") 
        echosounder_file_list_frame.grid(row=1, column=1, sticky="ew", padx=5, pady=2); echosounder_file_list_frame.columnconfigure(0, weight=1)
        self.echosounder_file_list_text = tk.Text(echosounder_file_list_frame, height=4, width=50, wrap=tk.WORD, state=tk.DISABLED, background="white", relief=tk.SUNKEN, borderwidth=1) 
        echosounder_file_scroll = ttk.Scrollbar(echosounder_file_list_frame, orient=tk.VERTICAL, command=self.echosounder_file_list_text.yview); self.echosounder_file_list_text['yscrollcommand'] = echosounder_file_scroll.set
        self.echosounder_file_list_text.grid(row=0, column=0, sticky="ew"); echosounder_file_scroll.grid(row=0, column=1, sticky="ns")
        echosounder_browse_files_btn = ttk.Button(parent_tab, text="Browse...", command=self._select_echosounder_p111_files, style="Custom.TButton") 
        echosounder_browse_files_btn.grid(row=1, column=2, sticky="w", padx=5, pady=2)
        ttk.Label(parent_tab, text="Output CSV directory:").grid(row=2, column=0, sticky="w", padx=5, pady=2)
        echosounder_output_dir_entry = ttk.Entry(parent_tab, textvariable=self.echosounder_output_dir_var, width=60)
        echosounder_output_dir_entry.grid(row=2, column=1, sticky="ew", padx=5, pady=2)
        echosounder_browse_dir_btn = ttk.Button(parent_tab, text="Browse...", command=self._select_echosounder_output_dir, style="Custom.TButton") 
        echosounder_browse_dir_btn.grid(row=2, column=2, sticky="w", padx=5, pady=2)
        echosounder_individual_csv_check = ttk.Checkbutton(parent_tab, text="Create individual CSV per sequence", variable=self.echosounder_individual_csv_var, style="TCheckbutton") 
        echosounder_individual_csv_check.grid(row=3, column=1, sticky="w", padx=5, pady=5)
        ttk.Label(parent_tab, text="Results Preview:").grid(row=4, column=0, sticky="nw", padx=5, pady=(10, 2))
        echosounder_pause_preview_check = ttk.Checkbutton(parent_tab, text="Pause Preview", variable=self.echosounder_pause_preview_var, style="TCheckbutton") 
        echosounder_pause_preview_check.grid(row=4, column=1, columnspan=2, sticky="w", padx=5, pady=(10,2))
        echosounder_preview_frame = ttk.Frame(parent_tab, style="TFrame") 
        echosounder_preview_frame.grid(row=5, column=0, columnspan=3, sticky="nsew", padx=5, pady=2); echosounder_preview_frame.rowconfigure(0, weight=1); echosounder_preview_frame.columnconfigure(0, weight=1)
        self.echosounder_preview_text = tk.Text(echosounder_preview_frame, height=10, width=80, wrap=tk.NONE, state=tk.DISABLED, font=self.mono_font, background="white", relief=tk.SUNKEN, borderwidth=1) 
        echosounder_preview_scroll_y = ttk.Scrollbar(echosounder_preview_frame, orient=tk.VERTICAL, command=self.echosounder_preview_text.yview); echosounder_preview_scroll_x = ttk.Scrollbar(echosounder_preview_frame, orient=tk.HORIZONTAL, command=self.echosounder_preview_text.xview)
        self.echosounder_preview_text['yscrollcommand'] = echosounder_preview_scroll_y.set; self.echosounder_preview_text['xscrollcommand'] = echosounder_preview_scroll_x.set
        self.echosounder_preview_text.grid(row=0, column=0, sticky="nsew"); echosounder_preview_scroll_y.grid(row=0, column=1, sticky="ns"); echosounder_preview_scroll_x.grid(row=1, column=0, sticky="ew")
        ttk.Label(parent_tab, text="Errors / Status Logs:").grid(row=6, column=0, sticky="w", padx=5, pady=(10, 2))
        echosounder_log_frame = ttk.Frame(parent_tab, style="TFrame") 
        echosounder_log_frame.grid(row=7, column=0, columnspan=3, sticky="nsew", padx=5, pady=2); echosounder_log_frame.rowconfigure(0, weight=1); echosounder_log_frame.columnconfigure(0, weight=1)
        self.echosounder_log_text = tk.Text(echosounder_log_frame, height=6, width=80, wrap=tk.WORD, state=tk.DISABLED, background="white", relief=tk.SUNKEN, borderwidth=1) 
        echosounder_log_scroll = ttk.Scrollbar(echosounder_log_frame, orient=tk.VERTICAL, command=self.echosounder_log_text.yview); self.echosounder_log_text['yscrollcommand'] = echosounder_log_scroll.set
        self.echosounder_log_text.grid(row=0, column=0, sticky="nsew"); echosounder_log_scroll.grid(row=0, column=1, sticky="ns")
        echosounder_button_frame = ttk.Frame(parent_tab, style="TFrame") 
        echosounder_button_frame.grid(row=8, column=0, columnspan=3, pady=(10, 0))
        self.echosounder_start_button = ttk.Button(echosounder_button_frame, text="Start Extraction", command=self._start_echosounder_extraction, style="Custom.TButton") 
        self.echosounder_start_button.pack(side=tk.LEFT, padx=5)
        self.echosounder_cancel_button = ttk.Button(echosounder_button_frame, text="Cancel Extraction", command=self._cancel_echosounder_extraction, state=tk.DISABLED, style="Custom.TButton") 
        self.echosounder_cancel_button.pack(side=tk.LEFT, padx=5)

    def _create_feather_tab_content(self, parent_tab):
        parent_tab.columnconfigure(1, weight=1); parent_tab.rowconfigure(5, weight=1); parent_tab.rowconfigure(7, weight=1)
        desc_label = ttk.Label(parent_tab, text="Calculate Streamer Feather")
        desc_label.grid(row=0, column=0, columnspan=3, sticky="w", padx=5, pady=(0, 10))
        ttk.Label(parent_tab, text="P111 input file(s):").grid(row=1, column=0, sticky="w", padx=5, pady=2)
        feather_file_list_frame = ttk.Frame(parent_tab, style="TFrame") 
        feather_file_list_frame.grid(row=1, column=1, sticky="ew", padx=5, pady=2); feather_file_list_frame.columnconfigure(0, weight=1)
        self.feather_file_list_text = tk.Text(feather_file_list_frame, height=4, width=50, wrap=tk.WORD, state=tk.DISABLED, background="white", relief=tk.SUNKEN, borderwidth=1) 
        feather_file_scroll = ttk.Scrollbar(feather_file_list_frame, orient=tk.VERTICAL, command=self.feather_file_list_text.yview); self.feather_file_list_text['yscrollcommand'] = feather_file_scroll.set
        self.feather_file_list_text.grid(row=0, column=0, sticky="ew"); feather_file_scroll.grid(row=0, column=1, sticky="ns")
        feather_browse_files_btn = ttk.Button(parent_tab, text="Browse...", command=self._select_feather_p111_files, style="Custom.TButton") 
        feather_browse_files_btn.grid(row=1, column=2, sticky="w", padx=5, pady=2)
        ttk.Label(parent_tab, text="Output CSV directory:").grid(row=2, column=0, sticky="w", padx=5, pady=2)
        feather_output_dir_entry = ttk.Entry(parent_tab, textvariable=self.feather_output_dir_var, width=60)
        feather_output_dir_entry.grid(row=2, column=1, sticky="ew", padx=5, pady=2)
        feather_browse_dir_btn = ttk.Button(parent_tab, text="Browse...", command=self._select_feather_output_dir, style="Custom.TButton") 
        feather_browse_dir_btn.grid(row=2, column=2, sticky="w", padx=5, pady=2)
        feather_individual_csv_check = ttk.Checkbutton(parent_tab, text="Create individual CSV per sequence", variable=self.feather_individual_csv_var, style="TCheckbutton") 
        feather_individual_csv_check.grid(row=3, column=1, sticky="w", padx=5, pady=5)
        ttk.Label(parent_tab, text="Results Preview:").grid(row=4, column=0, sticky="nw", padx=5, pady=(10, 2))
        feather_pause_preview_check = ttk.Checkbutton(parent_tab, text="Pause Preview", variable=self.feather_pause_preview_var, style="TCheckbutton") 
        feather_pause_preview_check.grid(row=4, column=1, columnspan=2, sticky="w", padx=5, pady=(10,2))
        feather_preview_frame = ttk.Frame(parent_tab, style="TFrame") 
        feather_preview_frame.grid(row=5, column=0, columnspan=3, sticky="nsew", padx=5, pady=2); feather_preview_frame.rowconfigure(0, weight=1); feather_preview_frame.columnconfigure(0, weight=1)
        self.feather_preview_text = tk.Text(feather_preview_frame, height=10, width=80, wrap=tk.NONE, state=tk.DISABLED, font=self.mono_font, background="white", relief=tk.SUNKEN, borderwidth=1) 
        feather_preview_scroll_y = ttk.Scrollbar(feather_preview_frame, orient=tk.VERTICAL, command=self.feather_preview_text.yview); feather_preview_scroll_x = ttk.Scrollbar(feather_preview_frame, orient=tk.HORIZONTAL, command=self.feather_preview_text.xview)
        self.feather_preview_text['yscrollcommand'] = feather_preview_scroll_y.set; self.feather_preview_text['xscrollcommand'] = feather_preview_scroll_x.set
        self.feather_preview_text.grid(row=0, column=0, sticky="nsew"); feather_preview_scroll_y.grid(row=0, column=1, sticky="ns"); feather_preview_scroll_x.grid(row=1, column=0, sticky="ew")
        ttk.Label(parent_tab, text="Errors / Status Logs:").grid(row=6, column=0, sticky="w", padx=5, pady=(10, 2))
        feather_log_frame = ttk.Frame(parent_tab, style="TFrame") 
        feather_log_frame.grid(row=7, column=0, columnspan=3, sticky="nsew", padx=5, pady=2); feather_log_frame.rowconfigure(0, weight=1); feather_log_frame.columnconfigure(0, weight=1)
        self.feather_log_text = tk.Text(feather_log_frame, height=6, width=80, wrap=tk.WORD, state=tk.DISABLED, background="white", relief=tk.SUNKEN, borderwidth=1) 
        feather_log_scroll = ttk.Scrollbar(feather_log_frame, orient=tk.VERTICAL, command=self.feather_log_text.yview); self.feather_log_text['yscrollcommand'] = feather_log_scroll.set
        self.feather_log_text.grid(row=0, column=0, sticky="nsew"); feather_log_scroll.grid(row=0, column=1, sticky="ns")
        feather_button_frame = ttk.Frame(parent_tab, style="TFrame") 
        feather_button_frame.grid(row=8, column=0, columnspan=3, pady=(10, 0))
        self.feather_start_button = ttk.Button(feather_button_frame, text="Start Calculation", command=self._start_feather_calculation, style="Custom.TButton") 
        self.feather_start_button.pack(side=tk.LEFT, padx=5)
        self.feather_cancel_button = ttk.Button(feather_button_frame, text="Cancel Calculation", command=self._cancel_feather_calculation, state=tk.DISABLED, style="Custom.TButton") 
        self.feather_cancel_button.pack(side=tk.LEFT, padx=5)

    def _scan_header_for_ids(self, file_list, log_func):
        if not file_list:
            log_func("Error: No input file provided for header scan.")
            return None, None
        header_file = file_list[0]
        log_func("Scanning header of {} for device IDs...".format(os.path.basename(header_file)))
        found_vessel_id = None; found_echosounder_id = None; scan_limit = 2000
        try:
            with open(header_file, 'r') as infile:
                for i, line in enumerate(infile):
                    if i >= scan_limit: log_func("Info: Reached header scan limit ({}) for device IDs.".format(scan_limit)); break
                    line = line.strip();
                    if not line: continue
                    if line.startswith(('P1,', 'S1,', 'R1,')): break 
                    if line.startswith(HC_DEVICE_PREFIX): 
                        fields = line.split(',')
                        if len(fields) > 15: 
                            try:
                                device_id = fields[6].strip();
                                if not device_id: continue
                                device_type = fields[8].strip().lower(); description_field = fields[15].strip()
                                if found_vessel_id is None:
                                    is_vessel = False
                                    if device_type == "vessel": is_vessel = True
                                    elif description_field == "Vessel Reference Point": is_vessel = True
                                    if is_vessel: found_vessel_id = device_id
                                if found_echosounder_id is None:
                                    is_echosounder = False
                                    if "echo sounder" in device_type or "echosounder" in device_type: is_echosounder = True
                                    elif description_field == "Transducer Position": is_echosounder = True
                                    if is_echosounder: found_echosounder_id = device_id
                                if found_vessel_id and found_echosounder_id: log_func("Found both potential Vessel and Echosounder IDs in header."); break
                            except IndexError: continue
                        elif len(fields) > 8: 
                            try:
                                device_id = fields[6].strip();
                                if not device_id: continue
                                device_type = fields[8].strip().lower()
                                if found_vessel_id is None:
                                     if device_type == "vessel": found_vessel_id = device_id
                                if found_echosounder_id is None:
                                     if "echo sounder" in device_type or "echosounder" in device_type: found_echosounder_id = device_id
                                if found_vessel_id and found_echosounder_id: break
                            except IndexError: continue
        except IOError as e: log_func("Error reading header file {}: {}".format(header_file, e)); return None, None
        return found_vessel_id, found_echosounder_id

    def _select_vessel_p111_files(self):
        try: import tkFileDialog
        except ImportError: self._log_vessel_message("Error: Could not import tkFileDialog."); return
        filetypes=[('P111 files','*.p111'),('All files','*.*')]; initial_dir=self.vessel_last_p111_dir if self.vessel_last_p111_dir and os.path.isdir(self.vessel_last_p111_dir) else self.vessel_output_dir_var.get() or "/"
        filenames=tkFileDialog.askopenfilenames(title="Select P111 Files (Vessel)",initialdir=initial_dir,filetypes=filetypes); processed_filenames=[]
        if filenames:
            if isinstance(filenames,basestring): 
                 try: processed_filenames=list(self.tk.splitlist(filenames))
                 except tk.TclError: self._log_vessel_message("Error: Could not parse file list string."); processed_filenames=[]
            elif isinstance(filenames,tuple): processed_filenames=list(filenames)
            else: self._log_vessel_message("Error: Unexpected return type from file dialog."); processed_filenames=[]
            if processed_filenames: self.vessel_p111_files=processed_filenames; self.vessel_last_p111_dir=os.path.dirname(self.vessel_p111_files[0]); self._update_vessel_file_list_display(); self._log_vessel_message("Selected {} file(s) for Vessel tab.".format(len(self.vessel_p111_files)))
        else: self._log_vessel_message("No files selected for Vessel tab.")

    def _update_vessel_file_list_display(self):
        if not hasattr(self,'vessel_file_list_text'): return
        self.vessel_file_list_text.config(state=tk.NORMAL); self.vessel_file_list_text.delete(1.0,tk.END);
        if self.vessel_p111_files: self.vessel_file_list_text.insert(tk.END,"\n".join(self.vessel_p111_files))
        self.vessel_file_list_text.config(state=tk.DISABLED)

    def _select_vessel_output_dir(self):
        try: import tkFileDialog
        except ImportError: self._log_vessel_message("Error: Could not import tkFileDialog."); return
        initial_browse_dir=self.vessel_output_dir_var.get() if self.vessel_output_dir_var.get() and os.path.isdir(self.vessel_output_dir_var.get()) else self.vessel_default_output_dir
        directory=tkFileDialog.askdirectory(title="Select Output CSV Directory (Vessel)",initialdir=initial_browse_dir)
        if directory and os.path.isdir(directory): self.vessel_output_dir_var.set(directory); self._log_vessel_message("Vessel output directory set to: {}".format(directory))

    def _select_source_p111_files(self):
        try: import tkFileDialog
        except ImportError: self._log_source_message("Error: Could not import tkFileDialog."); return
        filetypes=[('P111 files','*.p111'),('All files','*.*')]; initial_dir=self.source_last_p111_dir if self.source_last_p111_dir and os.path.isdir(self.source_last_p111_dir) else self.source_output_dir_var.get() or "/"
        filenames=tkFileDialog.askopenfilenames(title="Select P111 Files (Source)",initialdir=initial_dir,filetypes=filetypes); processed_filenames=[]
        if filenames:
            if isinstance(filenames,basestring):
                 try: processed_filenames=list(self.tk.splitlist(filenames))
                 except tk.TclError: self._log_source_message("Error: Could not parse file list string."); processed_filenames=[]
            elif isinstance(filenames,tuple): processed_filenames=list(filenames)
            else: self._log_source_message("Error: Unexpected return type from file dialog."); processed_filenames=[]
            if processed_filenames: self.source_p111_files=processed_filenames; self.source_last_p111_dir=os.path.dirname(self.source_p111_files[0]); self._update_source_file_list_display(); self._log_source_message("Selected {} file(s) for Source tab.".format(len(self.source_p111_files)))
        else: self._log_source_message("No files selected for Source tab.")

    def _update_source_file_list_display(self):
        if not hasattr(self,'source_file_list_text'): return
        self.source_file_list_text.config(state=tk.NORMAL); self.source_file_list_text.delete(1.0,tk.END);
        if self.source_p111_files: self.source_file_list_text.insert(tk.END,"\n".join(self.source_p111_files))
        self.source_file_list_text.config(state=tk.DISABLED)

    def _select_source_output_dir(self):
        try: import tkFileDialog
        except ImportError: self._log_source_message("Error: Could not import tkFileDialog."); return
        initial_browse_dir=self.source_output_dir_var.get() if self.source_output_dir_var.get() and os.path.isdir(self.source_output_dir_var.get()) else self.source_default_output_dir
        directory=tkFileDialog.askdirectory(title="Select Output CSV Directory (Source)",initialdir=initial_browse_dir)
        if directory and os.path.isdir(directory): self.source_output_dir_var.set(directory); self._log_source_message("Source output directory set to: {}".format(directory))

    def _select_echosounder_p111_files(self):
        try: import tkFileDialog
        except ImportError: self._log_echosounder_message("Error: Could not import tkFileDialog."); return
        filetypes=[('P111 files','*.p111'),('All files','*.*')]; initial_dir=self.echosounder_last_p111_dir if self.echosounder_last_p111_dir and os.path.isdir(self.echosounder_last_p111_dir) else self.echosounder_output_dir_var.get() or "/"
        filenames=tkFileDialog.askopenfilenames(title="Select P111 Files (Echosounder)",initialdir=initial_dir,filetypes=filetypes); processed_filenames=[]
        if filenames:
            if isinstance(filenames,basestring):
                 try: processed_filenames=list(self.tk.splitlist(filenames))
                 except tk.TclError: self._log_echosounder_message("Error: Could not parse file list string."); processed_filenames=[]
            elif isinstance(filenames,tuple): processed_filenames=list(filenames)
            else: self._log_echosounder_message("Error: Unexpected return type from file dialog."); processed_filenames=[]
            if processed_filenames: self.echosounder_p111_files=processed_filenames; self.echosounder_last_p111_dir=os.path.dirname(self.echosounder_p111_files[0]); self._update_echosounder_file_list_display(); self._log_echosounder_message("Selected {} file(s) for Echosounder tab.".format(len(self.echosounder_p111_files)))
        else: self._log_echosounder_message("No files selected for Echosounder tab.")

    def _update_echosounder_file_list_display(self):
        if not hasattr(self,'echosounder_file_list_text'): return
        self.echosounder_file_list_text.config(state=tk.NORMAL); self.echosounder_file_list_text.delete(1.0,tk.END);
        if self.echosounder_p111_files: self.echosounder_file_list_text.insert(tk.END,"\n".join(self.echosounder_p111_files))
        self.echosounder_file_list_text.config(state=tk.DISABLED)

    def _select_echosounder_output_dir(self):
        try: import tkFileDialog
        except ImportError: self._log_echosounder_message("Error: Could not import tkFileDialog."); return
        initial_browse_dir=self.echosounder_output_dir_var.get() if self.echosounder_output_dir_var.get() and os.path.isdir(self.echosounder_output_dir_var.get()) else self.echosounder_default_output_dir
        directory=tkFileDialog.askdirectory(title="Select Output CSV Directory (Echosounder)",initialdir=initial_browse_dir)
        if directory and os.path.isdir(directory): self.echosounder_output_dir_var.set(directory); self._log_echosounder_message("Echosounder output directory set to: {}".format(directory))

    def _select_feather_p111_files(self):
        try: import tkFileDialog
        except ImportError: self._log_feather_message("Error: Could not import tkFileDialog."); return
        filetypes=[('P111 files','*.p111'),('All files','*.*')]; initial_dir=self.feather_last_p111_dir if self.feather_last_p111_dir and os.path.isdir(self.feather_last_p111_dir) else self.feather_output_dir_var.get() or "/"
        filenames=tkFileDialog.askopenfilenames(title="Select P111 Files (Feather)",initialdir=initial_dir,filetypes=filetypes); processed_filenames=[]
        if filenames:
            if isinstance(filenames,basestring):
                 try: processed_filenames=list(self.tk.splitlist(filenames))
                 except tk.TclError: self._log_feather_message("Error: Could not parse file list string."); processed_filenames=[]
            elif isinstance(filenames,tuple): processed_filenames=list(filenames)
            else: self._log_feather_message("Error: Unexpected return type from file dialog."); processed_filenames=[]
            if processed_filenames: self.feather_p111_files=processed_filenames; self.feather_last_p111_dir=os.path.dirname(self.feather_p111_files[0]); self._update_feather_file_list_display(); self._log_feather_message("Selected {} file(s) for Feather tab.".format(len(self.feather_p111_files)))
        else: self._log_feather_message("No files selected for Feather tab.")

    def _update_feather_file_list_display(self):
        if not hasattr(self,'feather_file_list_text'): return
        self.feather_file_list_text.config(state=tk.NORMAL); self.feather_file_list_text.delete(1.0,tk.END);
        if self.feather_p111_files: self.feather_file_list_text.insert(tk.END,"\n".join(self.feather_p111_files))
        self.feather_file_list_text.config(state=tk.DISABLED)

    def _select_feather_output_dir(self):
        try: import tkFileDialog
        except ImportError: self._log_feather_message("Error: Could not import tkFileDialog."); return
        initial_browse_dir=self.feather_output_dir_var.get() if self.feather_output_dir_var.get() and os.path.isdir(self.feather_output_dir_var.get()) else self.feather_default_output_dir
        directory=tkFileDialog.askdirectory(title="Select Output CSV Directory (Feather)",initialdir=initial_browse_dir)
        if directory and os.path.isdir(directory): self.feather_output_dir_var.set(directory); self._log_feather_message("Feather output directory set to: {}".format(directory))

    def _log_vessel_message(self, message):
        def task():
            if hasattr(self,'vessel_log_text'): self.vessel_log_text.config(state=tk.NORMAL); self.vessel_log_text.insert(tk.END, message+"\n"); self.vessel_log_text.see(tk.END); self.vessel_log_text.config(state=tk.DISABLED)
            else: print "Log Error (Vessel): vessel_log_text widget not found."
        self.after(0, task)

    def _update_vessel_preview(self, data_list):
        def task():
            if not hasattr(self,'vessel_preview_text'): print "Preview Error (Vessel): vessel_preview_text widget not found."; return
            is_header=(data_list==VESSEL_CSV_HEADER)
            if not self.vessel_pause_preview_var.get() or is_header:
                try: str_data_list=map(str,data_list); preview_line=VESSEL_PREVIEW_FORMAT.format(*str_data_list)
                except (IndexError, ValueError, TypeError) as e: preview_line=" | ".join(map(str,data_list)); print "Vessel Preview format error:", e, "| Data:", data_list
                self.vessel_preview_text.config(state=tk.NORMAL); start_index=self.vessel_preview_text.index(tk.END+"-1c"); self.vessel_preview_text.insert(tk.END,preview_line+"\n"); end_index=self.vessel_preview_text.index(tk.END+"-1c")
                if is_header: self.vessel_preview_text.tag_add('bold_header',start_index,end_index)
                self.vessel_preview_text.see(tk.END); self.vessel_preview_text.config(state=tk.DISABLED)
        self.after(0, task)

    def _log_source_message(self, message):
        def task():
            if hasattr(self,'source_log_text'): self.source_log_text.config(state=tk.NORMAL); self.source_log_text.insert(tk.END, message+"\n"); self.source_log_text.see(tk.END); self.source_log_text.config(state=tk.DISABLED)
            else: print "Log Error (Source): source_log_text widget not found."
        self.after(0, task)

    def _update_source_preview(self, data_list):
        def task():
            if not hasattr(self,'source_preview_text'): print "Preview Error (Source): source_preview_text widget not found."; return
            is_header=(data_list==SOURCE_CSV_HEADER)
            if not self.source_pause_preview_var.get() or is_header:
                try: str_data_list=map(str,data_list); preview_line=SOURCE_PREVIEW_FORMAT.format(*str_data_list)
                except (IndexError, ValueError, TypeError) as e: preview_line=" | ".join(map(str,data_list)); print "Source Preview format error:", e, "| Data:", data_list
                self.source_preview_text.config(state=tk.NORMAL); start_index=self.source_preview_text.index(tk.END+"-1c"); self.source_preview_text.insert(tk.END,preview_line+"\n"); end_index=self.source_preview_text.index(tk.END+"-1c")
                if is_header: self.source_preview_text.tag_add('bold_header',start_index,end_index)
                self.source_preview_text.see(tk.END); self.source_preview_text.config(state=tk.DISABLED)
        self.after(0, task)

    def _log_echosounder_message(self, message):
        def task():
            if hasattr(self,'echosounder_log_text'): self.echosounder_log_text.config(state=tk.NORMAL); self.echosounder_log_text.insert(tk.END, message+"\n"); self.echosounder_log_text.see(tk.END); self.echosounder_log_text.config(state=tk.DISABLED)
            else: print "Log Error (Echosounder): echosounder_log_text widget not found."
        self.after(0, task)

    def _update_echosounder_preview(self, data_list):
        def task():
            if not hasattr(self,'echosounder_preview_text'): print "Preview Error (Echosounder): echosounder_preview_text widget not found."; return
            is_header=(data_list==ECHOSOUNDER_CSV_HEADER)
            if not self.echosounder_pause_preview_var.get() or is_header:
                try: str_data_list=map(str,data_list); preview_line=ECHOSOUNDER_PREVIEW_FORMAT.format(*str_data_list)
                except (IndexError, ValueError, TypeError) as e: preview_line=" | ".join(map(str,data_list)); print "Echosounder Preview format error:", e, "| Data:", data_list
                self.echosounder_preview_text.config(state=tk.NORMAL); start_index=self.echosounder_preview_text.index(tk.END+"-1c"); self.echosounder_preview_text.insert(tk.END,preview_line+"\n"); end_index=self.echosounder_preview_text.index(tk.END+"-1c")
                if is_header: self.echosounder_preview_text.tag_add('bold_header',start_index,end_index)
                self.echosounder_preview_text.see(tk.END); self.echosounder_preview_text.config(state=tk.DISABLED)
        self.after(0, task)

    def _log_feather_message(self, message):
        def task():
            if hasattr(self,'feather_log_text'): self.feather_log_text.config(state=tk.NORMAL); self.feather_log_text.insert(tk.END, message+"\n"); self.feather_log_text.see(tk.END); self.feather_log_text.config(state=tk.DISABLED)
            else: print "Log Error (Feather): feather_log_text widget not found."
        self.after(0, task)

    def _update_feather_preview(self, data_list):
        def task():
            if not hasattr(self,'feather_preview_text'): print "Preview Error (Feather): feather_preview_text widget not found."; return
            is_header = (data_list == FEATHER_CSV_HEADER)
            if not self.feather_pause_preview_var.get() or is_header:
                try: str_data_list = map(str, data_list); preview_line = FEATHER_PREVIEW_FORMAT.format(*str_data_list)
                except (IndexError, ValueError, TypeError) as e: preview_line = " | ".join(map(str, data_list)); print "Feather Preview format error:", e, "| Data:", data_list
                self.feather_preview_text.config(state=tk.NORMAL); start_index = self.feather_preview_text.index(tk.END + "-1c"); self.feather_preview_text.insert(tk.END, preview_line + "\n"); end_index = self.feather_preview_text.index(tk.END + "-1c")
                if is_header: self.feather_preview_text.tag_add('bold_header', start_index, end_index)
                self.feather_preview_text.see(tk.END); self.feather_preview_text.config(state=tk.DISABLED)
        self.after(0, task)

    def _check_other_extractions(self, current_tab_name):
        if current_tab_name!="Vessel" and self.vessel_extraction_running: return "Vessel"
        if current_tab_name!="Source" and self.source_extraction_running: return "Source"
        if current_tab_name!="Echosounder" and self.echosounder_extraction_running: return "Echosounder"
        if current_tab_name!="Feather" and self.feather_extraction_running: return "Feather"
        return None

    def _start_vessel_extraction(self):
        other_running=self._check_other_extractions("Vessel");
        if other_running: self._log_vessel_message("Error: {} extraction is already running.".format(other_running)); return
        if self.vessel_extraction_running: self._log_vessel_message("Vessel extraction already in progress."); return
        if not self.vessel_p111_files: self._log_vessel_message("Error: No P111 input files selected for Vessel tab."); return
        out_dir=self.vessel_output_dir_var.get();
        if not out_dir: self._log_vessel_message("Error: Vessel output directory not set."); return
        if not os.path.isdir(out_dir):
             try: _ensure_dir_exists(out_dir); self._log_vessel_message("Created output directory: {}".format(out_dir))
             except OSError as e: self._log_vessel_message("Error: Vessel output directory is invalid and cannot be created: {}".format(out_dir)); return
        self.vessel_extraction_running=True; self.vessel_cancel_extraction_flag=False; self.vessel_start_button.config(state=tk.DISABLED); self.vessel_cancel_button.config(state=tk.NORMAL); self._log_vessel_message("Starting Vessel data extraction...")
        def clear_preview_and_add_header():
            if hasattr(self,'vessel_preview_text'): self.vessel_preview_text.config(state=tk.NORMAL); self.vessel_preview_text.delete(1.0,tk.END); self.vessel_preview_text.config(state=tk.DISABLED); self._update_vessel_preview(VESSEL_CSV_HEADER)
            else: self._log_vessel_message("Error: Cannot clear preview - widget not found.")
        self.after(0,clear_preview_and_add_header)
        self.vessel_extraction_thread=threading.Thread(target=self._start_vessel_extraction_thread); self.vessel_extraction_thread.daemon=True; self.vessel_extraction_thread.start()

    def _cancel_vessel_extraction(self):
        if self.vessel_extraction_running: self._log_vessel_message("Vessel cancellation requested..."); self.vessel_cancel_extraction_flag=True
        else: self._log_vessel_message("No Vessel extraction running to cancel.")

    def _vessel_extraction_finished(self):
        was_cancelled=self.vessel_cancel_extraction_flag; self.vessel_extraction_running=False; self.vessel_cancel_extraction_flag=False; self.vessel_extraction_thread=None
        if hasattr(self,'vessel_start_button'): self.vessel_start_button.config(state=tk.NORMAL)
        if hasattr(self,'vessel_cancel_button'): self.vessel_cancel_button.config(state=tk.DISABLED)
        if was_cancelled: self._log_vessel_message("Vessel extraction cancelled by user.")
        else: self._log_vessel_message("Vessel extraction finished.")

    def _start_source_extraction(self):
        other_running=self._check_other_extractions("Source");
        if other_running: self._log_source_message("Error: {} extraction is already running.".format(other_running)); return
        if self.source_extraction_running: self._log_source_message("Source extraction already in progress."); return
        if not self.source_p111_files: self._log_source_message("Error: No P111 input files selected for Source tab."); return
        out_dir=self.source_output_dir_var.get();
        if not out_dir: self._log_source_message("Error: Source output directory not set."); return
        if not os.path.isdir(out_dir):
             try: _ensure_dir_exists(out_dir); self._log_source_message("Created output directory: {}".format(out_dir))
             except OSError as e: self._log_source_message("Error: Source output directory is invalid and cannot be created: {}".format(out_dir)); return
        self.source_extraction_running=True; self.source_cancel_extraction_flag=False; self.source_start_button.config(state=tk.DISABLED); self.source_cancel_button.config(state=tk.NORMAL); self._log_source_message("Starting Source data extraction...")
        def clear_preview_and_add_header():
            if hasattr(self,'source_preview_text'): self.source_preview_text.config(state=tk.NORMAL); self.source_preview_text.delete(1.0,tk.END); self.source_preview_text.config(state=tk.DISABLED); self._update_source_preview(SOURCE_CSV_HEADER)
            else: self._log_source_message("Error: Cannot clear preview - widget not found.")
        self.after(0,clear_preview_and_add_header)
        self.source_extraction_thread=threading.Thread(target=self._start_source_extraction_thread); self.source_extraction_thread.daemon=True; self.source_extraction_thread.start()

    def _cancel_source_extraction(self):
        if self.source_extraction_running: self._log_source_message("Source cancellation requested..."); self.source_cancel_extraction_flag=True
        else: self._log_source_message("No Source extraction running to cancel.")

    def _source_extraction_finished(self):
        was_cancelled=self.source_cancel_extraction_flag; self.source_extraction_running=False; self.source_cancel_extraction_flag=False; self.source_extraction_thread=None
        if hasattr(self,'source_start_button'): self.source_start_button.config(state=tk.NORMAL)
        if hasattr(self,'source_cancel_button'): self.source_cancel_button.config(state=tk.DISABLED)
        if was_cancelled: self._log_source_message("Source extraction cancelled by user.")
        else: self._log_source_message("Source extraction finished.")

    def _start_echosounder_extraction(self):
        other_running=self._check_other_extractions("Echosounder");
        if other_running: self._log_echosounder_message("Error: {} extraction is already running.".format(other_running)); return
        if self.echosounder_extraction_running: self._log_echosounder_message("Echosounder extraction already in progress."); return
        if not self.echosounder_p111_files: self._log_echosounder_message("Error: No P111 input files selected for Echosounder tab."); return
        out_dir=self.echosounder_output_dir_var.get();
        if not out_dir: self._log_echosounder_message("Error: Echosounder output directory not set."); return
        if not os.path.isdir(out_dir):
             try: _ensure_dir_exists(out_dir); self._log_echosounder_message("Created output directory: {}".format(out_dir))
             except OSError as e: self._log_echosounder_message("Error: Echosounder output directory is invalid and cannot be created: {}".format(out_dir)); return
        self.echosounder_extraction_running=True; self.echosounder_cancel_extraction_flag=False; self.echosounder_start_button.config(state=tk.DISABLED); self.echosounder_cancel_button.config(state=tk.NORMAL); self._log_echosounder_message("Starting Echosounder data extraction...")
        def clear_preview_and_add_header():
            if hasattr(self,'echosounder_preview_text'): self.echosounder_preview_text.config(state=tk.NORMAL); self.echosounder_preview_text.delete(1.0,tk.END); self.echosounder_preview_text.config(state=tk.DISABLED); self._update_echosounder_preview(ECHOSOUNDER_CSV_HEADER)
            else: self._log_echosounder_message("Error: Cannot clear preview - widget not found.")
        self.after(0,clear_preview_and_add_header)
        self.echosounder_extraction_thread=threading.Thread(target=self._start_echosounder_extraction_thread); self.echosounder_extraction_thread.daemon=True; self.echosounder_extraction_thread.start()

    def _cancel_echosounder_extraction(self):
        if self.echosounder_extraction_running: self._log_echosounder_message("Echosounder cancellation requested..."); self.echosounder_cancel_extraction_flag=True
        else: self._log_echosounder_message("No Echosounder extraction running to cancel.")

    def _echosounder_extraction_finished(self):
        was_cancelled=self.echosounder_cancel_extraction_flag; self.echosounder_extraction_running=False; self.echosounder_cancel_extraction_flag=False; self.echosounder_extraction_thread=None
        if hasattr(self,'echosounder_start_button'): self.echosounder_start_button.config(state=tk.NORMAL)
        if hasattr(self,'echosounder_cancel_button'): self.echosounder_cancel_button.config(state=tk.DISABLED)
        if was_cancelled: self._log_echosounder_message("Echosounder extraction cancelled by user.")
        else: self._log_echosounder_message("Echosounder extraction finished.")

    def _start_feather_calculation(self): 
        other_running=self._check_other_extractions("Feather");
        if other_running: self._log_feather_message("Error: {} extraction is already running.".format(other_running)); return
        if self.feather_extraction_running: self._log_feather_message("Feather calculation already in progress."); return
        if not self.feather_p111_files: self._log_feather_message("Error: No P111 input files selected for Feather tab."); return
        out_dir=self.feather_output_dir_var.get();
        if not out_dir: self._log_feather_message("Error: Feather output directory not set."); return
        if not os.path.isdir(out_dir):
             try: _ensure_dir_exists(out_dir); self._log_feather_message("Created output directory: {}".format(out_dir))
             except OSError as e: self._log_feather_message("Error: Feather output directory is invalid and cannot be created: {}".format(out_dir)); return
        self.feather_extraction_running=True; self.feather_cancel_extraction_flag=False; self.feather_start_button.config(state=tk.DISABLED); self.feather_cancel_button.config(state=tk.NORMAL); self._log_feather_message("Starting Feather data calculation...")
        def clear_preview_and_add_header():
            if hasattr(self,'feather_preview_text'): self.feather_preview_text.config(state=tk.NORMAL); self.feather_preview_text.delete(1.0,tk.END); self.feather_preview_text.config(state=tk.DISABLED); self._update_feather_preview(FEATHER_CSV_HEADER)
            else: self._log_feather_message("Error: Cannot clear preview - widget not found.")
        self.after(0,clear_preview_and_add_header)
        self.feather_extraction_thread=threading.Thread(target=self._start_feather_calculation_thread); self.feather_extraction_thread.daemon=True; self.feather_extraction_thread.start()

    def _cancel_feather_calculation(self):
        if self.feather_extraction_running: self._log_feather_message("Feather calculation cancellation requested..."); self.feather_cancel_extraction_flag=True
        else: self._log_feather_message("No Feather calculation running to cancel.")

    def _feather_calculation_finished(self):
        was_cancelled=self.feather_cancel_extraction_flag; self.feather_extraction_running=False; self.feather_cancel_extraction_flag=False; self.feather_extraction_thread=None
        if hasattr(self,'feather_start_button'): self.feather_start_button.config(state=tk.NORMAL)
        if hasattr(self,'feather_cancel_button'): self.feather_cancel_button.config(state=tk.DISABLED)
        if was_cancelled: self._log_feather_message("Feather calculation cancelled by user.")
        else: self._log_feather_message("Feather calculation finished.")

    # --- Worker Thread Functions ---
    def _start_vessel_extraction_thread(self):
        scanned_vessel_id, scanned_echosounder_id = self._scan_header_for_ids(
            self.vessel_p111_files, self._log_vessel_message
        )
        local_vessel_id = scanned_vessel_id
        local_echosounder_id = scanned_echosounder_id 

        if not local_vessel_id:
            self._log_vessel_message("Error: Vessel ID could not be automatically detected from P111 header. Stopping Vessel extraction.")
            self.after(0, self._vessel_extraction_finished)
            return
        self._log_vessel_message("Using detected Vessel ID: {}".format(local_vessel_id))

        if local_echosounder_id:
            self._log_vessel_message("Using auto-detected Echosounder ID for depth: {}".format(local_echosounder_id))
        else:
            self._log_vessel_message("Warning: Echosounder ID for depth could not be auto-detected. Water depth may not be extracted or will be 'N/A'.")

        all_sequences_data = OrderedDict()
        output_files = {}
        csv_writers = {}
        
        try:
            input_files = list(self.vessel_p111_files)
            output_dir = self.vessel_output_dir_var.get()
            individual_csv = self.vessel_individual_csv_var.get()

            for filename in input_files:
                if self.vessel_cancel_extraction_flag: break
                self._log_vessel_message("Processing (Vessel): {}".format(os.path.basename(filename)))
                
                current_sequence_in_file = "N/A"
                current_line_name_in_file = "N/A"
                current_subline_in_file = ""
                line_count = 0
                
                try:
                    with open(filename, 'r') as infile:
                        for line in infile:
                            line_count += 1
                            if self.vessel_cancel_extraction_flag: break
                            line = line.strip()
                            if not line: continue

                            if line.startswith(CC_SEQUENCE_PREFIX):
                                try:
                                    current_sequence_in_file = line.split('=')[1].strip() or "N/A"
                                except IndexError: 
                                    current_sequence_in_file = current_sequence_in_file # Keep previous if parse fails
                            elif line.startswith(CC_LINENAME_PREFIX):
                                try:
                                    parts = line.split('=')[1].strip()
                                    name_parts = [p for p in parts.split('/') if p]
                                    current_line_name_in_file = name_parts[0] if len(name_parts) > 0 else "N/A"
                                    current_subline_in_file = name_parts[1] if len(name_parts) > 1 else ""
                                except (IndexError, ValueError): 
                                     pass # Keep previous line/subline
                            
                            elif line.startswith('P1,'):
                                try:
                                    fields = line.split(',')
                                    if len(fields) > max(P_REC_SPN_IDX, P_REC_DEVICE_ID_IDX):
                                        spn = fields[P_REC_SPN_IDX].strip()
                                        device_id = fields[P_REC_DEVICE_ID_IDX].strip()

                                        if current_sequence_in_file not in all_sequences_data:
                                            all_sequences_data[current_sequence_in_file] = OrderedDict()
                                        
                                        sequence_specific_spn_data = all_sequences_data[current_sequence_in_file]

                                        if spn not in sequence_specific_spn_data:
                                            sequence_specific_spn_data[spn] = {
                                                "Sequence Number": current_sequence_in_file,
                                                "Line Name": current_line_name_in_file,
                                                "Subline": current_subline_in_file,
                                                "Shotpoint Number": spn,
                                                "Preplot Number": 'N/A', "Latitude": 'N/A', 
                                                "Longitude": 'N/A', "Easting": 'N/A',
                                                "Northing": 'N/A', "Water Depth": 'N/A'
                                            }
                                        else: 
                                            sequence_specific_spn_data[spn]['Line Name'] = current_line_name_in_file
                                            sequence_specific_spn_data[spn]['Subline'] = current_subline_in_file
                                            sequence_specific_spn_data[spn]['Sequence Number'] = current_sequence_in_file


                                        if device_id == local_vessel_id:
                                            if len(fields) > max(P_REC_PREPLOT_IDX, P_REC_NORTHING_IDX, P_REC_LONGITUDE_IDX):
                                                preplot = fields[P_REC_PREPLOT_IDX].strip()
                                                easting = fields[P_REC_EASTING_IDX].strip()
                                                northing = fields[P_REC_NORTHING_IDX].strip()
                                                latitude_dec = fields[P_REC_LATITUDE_IDX].strip()
                                                longitude_dec = fields[P_REC_LONGITUDE_IDX].strip()
                                                lat_str = format_decimal_degrees_to_deg_min(latitude_dec, 'lat')
                                                lon_str = format_decimal_degrees_to_deg_min(longitude_dec, 'lon')
                                                sequence_specific_spn_data[spn].update({
                                                    "Preplot Number": preplot, "Latitude": lat_str,
                                                    "Longitude": lon_str, "Easting": easting, "Northing": northing
                                                })
                                            else:
                                                self._log_vessel_message("Warning: Vessel P1 record at line {} for SPN {} in Seq {} is missing fields.".format(line_count, spn, current_sequence_in_file))
                                        
                                        elif local_echosounder_id and device_id == local_echosounder_id:
                                            if len(fields) > 0:
                                                try:
                                                    raw_depth = fields[-1].strip()
                                                    water_depth = raw_depth.split(';')[0]
                                                    float(water_depth) 
                                                    sequence_specific_spn_data[spn]["Water Depth"] = water_depth
                                                except (IndexError, ValueError, TypeError) as e_depth:
                                                    self._log_vessel_message("Warning: Could not parse water depth for SPN {} in Seq {} at line {}: {} (Value: '{}')".format(spn, current_sequence_in_file, line_count, e_depth, fields[-1]))
                                                    sequence_specific_spn_data[spn]["Water Depth"] = 'Error'
                                            else:
                                                self._log_vessel_message("Warning: Echosounder P1 record at line {} for SPN {} in Seq {} has no fields.".format(line_count, spn, current_sequence_in_file))
                                except (IndexError, ValueError) as e:
                                    self._log_vessel_message("Warning: Error parsing P1 record fields at line {}: {}".format(line_count, e))
                                    continue
                except IOError as e:
                    self._log_vessel_message("Error opening/reading file {}: {}".format(filename, e))
                    continue
                if self.vessel_cancel_extraction_flag: break
            
            if self.vessel_cancel_extraction_flag:
                self.after(0, self._vessel_extraction_finished); return

            if not all_sequences_data:
                self._log_vessel_message("Warning: No relevant P1 records found in any file for Vessel ID '{}' or Echosounder ID '{}'.".format(local_vessel_id, local_echosounder_id or 'N/A'))
                self.after(0, self._vessel_extraction_finished); return

            self._log_vessel_message("Writing Vessel CSV data...")
            
            combined_csv_filename = "combined_VesselData.csv" 
            if not individual_csv:
                valid_seq_names = [s_name for s_name in all_sequences_data.keys() if s_name != "N/A"]
                seq_range_for_filename = "all_sequences"
                if valid_seq_names:
                    sorted_valid_seq_names = sorted(valid_seq_names, key=robust_sequence_sort_key)
                    first_s = sorted_valid_seq_names[0]
                    last_s = sorted_valid_seq_names[-1]
                    seq_range_for_filename = "{}-{}".format(first_s, last_s) if first_s != last_s else first_s
                safe_seq_range = "".join(c if c.isalnum() or c in ('_', '-') else '_' for c in seq_range_for_filename)
                combined_csv_filename = "{}_VesselData.csv".format(safe_seq_range)

            sorted_sequence_names_for_output = sorted(all_sequences_data.keys(), key=robust_sequence_sort_key)

            for seq_name in sorted_sequence_names_for_output:
                if self.vessel_cancel_extraction_flag: break
                spn_data_for_this_sequence = all_sequences_data[seq_name]
                
                current_full_out_path = None
                if individual_csv:
                    safe_seq_name = "".join(c if c.isalnum() or c in ('_', '-') else '_' for c in seq_name)
                    out_filename = "{}_VesselData.csv".format(safe_seq_name)
                    current_full_out_path = os.path.join(output_dir, out_filename)
                else:
                    current_full_out_path = os.path.join(output_dir, combined_csv_filename)

                if current_full_out_path not in csv_writers: 
                    self._log_vessel_message("Creating/Opening CSV: {}".format(current_full_out_path))
                    try:
                        _ensure_dir_exists(output_dir)
                        output_files[current_full_out_path] = open(current_full_out_path, 'wb')
                        csv_writers[current_full_out_path] = csv.writer(output_files[current_full_out_path])
                        csv_writers[current_full_out_path].writerow(VESSEL_CSV_HEADER)
                    except (IOError, OSError) as e_io:
                        self._log_vessel_message("ERROR: Cannot write to {}. Check permissions/disk space. {}".format(current_full_out_path, e_io))
                        self.vessel_cancel_extraction_flag = True; break 
                
                current_csv_writer = csv_writers.get(current_full_out_path)
                if not current_csv_writer: self._log_vessel_message("Error: CSV writer not available for {}".format(current_full_out_path)); continue

                for spn, data_dict in spn_data_for_this_sequence.items():
                    if self.vessel_cancel_extraction_flag: break
                    csv_data = [data_dict.get(h, "N/A") for h in VESSEL_CSV_HEADER]
                    self._update_vessel_preview(csv_data)
                    try: current_csv_writer.writerow(csv_data)
                    except Exception as e_write: self._log_vessel_message("Error writing row to CSV {}: {}".format(current_full_out_path, e_write))
                if self.vessel_cancel_extraction_flag: break
        except Exception as e:
            import traceback
            self._log_vessel_message("FATAL ERROR during Vessel extraction thread: {}".format(e))
            self._log_vessel_message(traceback.format_exc())
        finally:
            for f_path, f_handle in output_files.items():
                try:
                    if f_handle and not f_handle.closed: f_handle.close(); self._log_vessel_message("Closed CSV: {}".format(os.path.basename(f_path)))
                except Exception as e_close: self._log_vessel_message("Warning: Error closing output file {}: {}".format(f_path, e_close))
            self.after(0, self._vessel_extraction_finished)

    def _start_source_extraction_thread(self):
        all_sequences_data = OrderedDict()
        output_files = {}
        csv_writers = {}
        try:
            input_files = list(self.source_p111_files)
            output_dir = self.source_output_dir_var.get()
            individual_csv = self.source_individual_csv_var.get()

            for filename in input_files:
                if self.source_cancel_extraction_flag: break
                self._log_source_message("Processing (Source): {}".format(os.path.basename(filename)))
                current_sequence_in_file = "N/A"
                current_line_name_in_file = "N/A"
                current_subline_in_file = ""
                line_count = 0
                try:
                    with open(filename, 'r') as infile:
                        for line in infile:
                            line_count += 1
                            if self.source_cancel_extraction_flag: break
                            line = line.strip()
                            if not line: continue

                            if line.startswith(CC_SEQUENCE_PREFIX):
                                try: current_sequence_in_file = line.split('=')[1].strip() or "N/A"
                                except IndexError: pass # Keep previous
                            elif line.startswith(CC_LINENAME_PREFIX):
                                try:
                                    parts = line.split('=')[1].strip(); name_parts = [p for p in parts.split('/') if p]
                                    current_line_name_in_file = name_parts[0] if len(name_parts) > 0 else "N/A"
                                    current_subline_in_file = name_parts[1] if len(name_parts) > 1 else ""
                                except (IndexError, ValueError): pass # Keep previous
                            elif line.startswith('S1,'):
                                try:
                                    fields = line.split(',')
                                    min_s1_fields = max(S1_REC_SPN_IDX, S1_REC_PREPLOT_IDX, S1_REC_SOURCE_FIRED_IDX, S1_REC_LATITUDE_IDX, S1_REC_LONGITUDE_IDX, S1_REC_EASTING_IDX, S1_REC_NORTHING_IDX) + 1
                                    if len(fields) >= min_s1_fields:
                                        spn = fields[S1_REC_SPN_IDX].strip()
                                        
                                        if current_sequence_in_file not in all_sequences_data:
                                            all_sequences_data[current_sequence_in_file] = OrderedDict()
                                        sequence_specific_spn_data = all_sequences_data[current_sequence_in_file]

                                        preplot = fields[S1_REC_PREPLOT_IDX].strip()
                                        source_fired_id = fields[S1_REC_SOURCE_FIRED_IDX].strip()
                                        latitude_dec = fields[S1_REC_LATITUDE_IDX].strip()
                                        longitude_dec = fields[S1_REC_LONGITUDE_IDX].strip()
                                        easting = fields[S1_REC_EASTING_IDX].strip()
                                        northing = fields[S1_REC_NORTHING_IDX].strip()
                                        lat_str = format_decimal_degrees_to_deg_min(latitude_dec, 'lat')
                                        lon_str = format_decimal_degrees_to_deg_min(longitude_dec, 'lon')
                                        
                                        sequence_specific_spn_data[spn] = {
                                            "Sequence Number": current_sequence_in_file,
                                            "Line Name": current_line_name_in_file,
                                            "Subline": current_subline_in_file,
                                            "Shotpoint Number": spn,
                                            "Preplot Number": preplot,
                                            "Source Fired": source_fired_id,
                                            "Latitude": lat_str, "Longitude": lon_str,
                                            "Easting": easting, "Northing": northing
                                        }
                                    else:
                                        self._log_source_message("Warning (Source): S1 record at line {} for Seq {} has too few fields. Skipping.".format(line_count, current_sequence_in_file))
                                except (IndexError, ValueError, TypeError) as e:
                                    self._log_source_message("Warning (Source): Error parsing S1 record at line {} for Seq {}: {}".format(line_count, current_sequence_in_file, e))
                except IOError as e:
                    self._log_source_message("Error opening/reading file {}: {}".format(filename, e)); continue
                if self.source_cancel_extraction_flag: break
            
            if self.source_cancel_extraction_flag: self.after(0, self._source_extraction_finished); return
            if not all_sequences_data: self._log_source_message("Warning: No S1 records found in any file."); self.after(0, self._source_extraction_finished); return

            self._log_source_message("Writing Source CSV data...")
            combined_csv_filename = "combined_SourceData.csv"
            if not individual_csv:
                valid_seq_names = [s_name for s_name in all_sequences_data.keys() if s_name != "N/A"]
                seq_range_for_filename = "all_sequences"
                if valid_seq_names:
                    sorted_valid_seq_names = sorted(valid_seq_names, key=robust_sequence_sort_key)
                    first_s, last_s = sorted_valid_seq_names[0], sorted_valid_seq_names[-1]
                    seq_range_for_filename = "{}-{}".format(first_s, last_s) if first_s != last_s else first_s
                safe_seq_range = "".join(c if c.isalnum() or c in ('_', '-') else '_' for c in seq_range_for_filename)
                combined_csv_filename = "{}_SourceData.csv".format(safe_seq_range)

            sorted_sequence_names_for_output = sorted(all_sequences_data.keys(), key=robust_sequence_sort_key)
            for seq_name in sorted_sequence_names_for_output:
                if self.source_cancel_extraction_flag: break
                spn_data_for_this_sequence = all_sequences_data[seq_name]
                current_full_out_path = os.path.join(output_dir, "{}_SourceData.csv".format("".join(c if c.isalnum() or c in ('_', '-') else '_' for c in seq_name))) if individual_csv else os.path.join(output_dir, combined_csv_filename)
                if current_full_out_path not in csv_writers:
                    self._log_source_message("Creating/Opening CSV: {}".format(current_full_out_path))
                    try:
                        _ensure_dir_exists(output_dir); output_files[current_full_out_path] = open(current_full_out_path, 'wb')
                        csv_writers[current_full_out_path] = csv.writer(output_files[current_full_out_path]); csv_writers[current_full_out_path].writerow(SOURCE_CSV_HEADER)
                    except (IOError, OSError) as e_io: self._log_source_message("ERROR: Cannot write to {}. {}".format(current_full_out_path, e_io)); self.source_cancel_extraction_flag = True; break
                current_csv_writer = csv_writers.get(current_full_out_path)
                if not current_csv_writer: continue
                for spn, data_dict in spn_data_for_this_sequence.items():
                    if self.source_cancel_extraction_flag: break
                    csv_data = [data_dict.get(h, "N/A") for h in SOURCE_CSV_HEADER]; self._update_source_preview(csv_data)
                    try: current_csv_writer.writerow(csv_data)
                    except Exception as e_write: self._log_source_message("Error writing row to CSV {}: {}".format(current_full_out_path, e_write))
                if self.source_cancel_extraction_flag: break
        except Exception as e: import traceback; self._log_source_message("FATAL ERROR: {}".format(e)); self._log_source_message(traceback.format_exc())
        finally:
            for f_path, f_handle in output_files.items():
                try:
                    if f_handle and not f_handle.closed: f_handle.close(); self._log_source_message("Closed CSV: {}".format(os.path.basename(f_path)))
                except Exception as e_close: self._log_source_message("Warning: Error closing {}: {}".format(f_path, e_close))
            self.after(0, self._source_extraction_finished)

    def _start_echosounder_extraction_thread(self):
        _, scanned_echosounder_id = self._scan_header_for_ids(self.echosounder_p111_files, self._log_echosounder_message)
        local_echosounder_id = scanned_echosounder_id
        if not local_echosounder_id:
            self._log_echosounder_message("Error: Echosounder ID could not be auto-detected. Stopping extraction.")
            self.after(0, self._echosounder_extraction_finished); return
        self._log_echosounder_message("Using detected Echosounder ID: {}".format(local_echosounder_id))

        all_sequences_data = OrderedDict()
        output_files, csv_writers = {}, {}
        try:
            input_files, output_dir, individual_csv = list(self.echosounder_p111_files), self.echosounder_output_dir_var.get(), self.echosounder_individual_csv_var.get()
            for filename in input_files:
                if self.echosounder_cancel_extraction_flag: break
                self._log_echosounder_message("Processing (Echosounder): {}".format(os.path.basename(filename)))
                current_sequence_in_file, current_line_name_in_file, current_subline_in_file = "N/A", "N/A", ""
                line_count = 0
                try:
                    with open(filename, 'r') as infile:
                        for line in infile:
                            line_count += 1
                            if self.echosounder_cancel_extraction_flag: break
                            line = line.strip()
                            if not line: continue
                            if line.startswith(CC_SEQUENCE_PREFIX): 
                                try: current_sequence_in_file = line.split('=')[1].strip() or "N/A"
                                except IndexError: pass
                            elif line.startswith(CC_LINENAME_PREFIX):
                                try: 
                                    parts = line.split('=')[1].strip(); name_parts = [p for p in parts.split('/') if p]
                                    current_line_name_in_file = name_parts[0] if len(name_parts) > 0 else "N/A"
                                    current_subline_in_file = name_parts[1] if len(name_parts) > 1 else ""
                                except (IndexError, ValueError): pass
                            elif line.startswith('P1,'):
                                try:
                                    fields = line.split(',')
                                    if len(fields) > P_REC_DEVICE_ID_IDX and fields[P_REC_DEVICE_ID_IDX].strip() == local_echosounder_id:
                                        min_p1_fields = max(P_REC_SPN_IDX, P_REC_PREPLOT_IDX, P_REC_LATITUDE_IDX, P_REC_LONGITUDE_IDX, P_REC_EASTING_IDX, P_REC_NORTHING_IDX) + 1
                                        if len(fields) >= min_p1_fields and len(fields) > 0: 
                                            spn = fields[P_REC_SPN_IDX].strip()
                                            if current_sequence_in_file not in all_sequences_data: all_sequences_data[current_sequence_in_file] = OrderedDict()
                                            sequence_specific_spn_data = all_sequences_data[current_sequence_in_file]
                                            
                                            water_depth = 'Error'
                                            try: 
                                                raw_depth = fields[-1].strip(); parsed_depth = raw_depth.split(';')[0]; float(parsed_depth); water_depth = parsed_depth
                                            except (IndexError, ValueError, TypeError): self._log_echosounder_message("Warning: Could not parse depth for SPN {} Seq {} line {}: {}".format(spn, current_sequence_in_file, line_count, fields[-1]))
                                            
                                            sequence_specific_spn_data[spn] = {
                                                "Sequence Number": current_sequence_in_file, "Line Name": current_line_name_in_file, "Subline": current_subline_in_file,
                                                "Shotpoint Number": spn, "Preplot Number": fields[P_REC_PREPLOT_IDX].strip(),
                                                "Latitude": format_decimal_degrees_to_deg_min(fields[P_REC_LATITUDE_IDX].strip(), 'lat'),
                                                "Longitude": format_decimal_degrees_to_deg_min(fields[P_REC_LONGITUDE_IDX].strip(), 'lon'),
                                                "Easting": fields[P_REC_EASTING_IDX].strip(), "Northing": fields[P_REC_NORTHING_IDX].strip(),
                                                "Water Depth": water_depth
                                            }
                                        else: self._log_echosounder_message("Warning (Echosounder): P1 record for ID {} at line {} Seq {} has too few fields.".format(local_echosounder_id, line_count, current_sequence_in_file))
                                except (IndexError, ValueError) as e: self._log_echosounder_message("Warning (Echosounder): Error parsing P1 at line {} Seq {}: {}".format(line_count, current_sequence_in_file, e))
                except IOError as e: self._log_echosounder_message("Error reading {}: {}".format(filename,e)); continue
                if self.echosounder_cancel_extraction_flag: break

            if self.echosounder_cancel_extraction_flag: self.after(0, self._echosounder_extraction_finished); return
            if not all_sequences_data: self._log_echosounder_message("Warning: No P1 records found for Echosounder ID '{}'.".format(local_echosounder_id)); self.after(0, self._echosounder_extraction_finished); return

            self._log_echosounder_message("Writing Echosounder CSV data...")
            combined_csv_filename = "combined_EchosounderData.csv"
            if not individual_csv:
                valid_seq_names = [s for s in all_sequences_data.keys() if s != "N/A"]; seq_range = "all_sequences"
                if valid_seq_names: s_sorted = sorted(valid_seq_names, key=robust_sequence_sort_key); seq_range = "{}-{}".format(s_sorted[0],s_sorted[-1]) if s_sorted[0]!=s_sorted[-1] else s_sorted[0]
                combined_csv_filename = "{}_EchosounderData.csv".format("".join(c if c.isalnum() or c in ('_','-') else '_' for c in seq_range))

            sorted_seq_names = sorted(all_sequences_data.keys(), key=robust_sequence_sort_key)
            for seq_name in sorted_seq_names:
                if self.echosounder_cancel_extraction_flag: break
                spn_data_list = all_sequences_data[seq_name]
                out_f_path = os.path.join(output_dir, "{}_EchosounderData.csv".format("".join(c if c.isalnum() or c in ('_','-') else '_' for c in seq_name))) if individual_csv else os.path.join(output_dir, combined_csv_filename)
                if out_f_path not in csv_writers:
                    self._log_echosounder_message("Creating/Opening CSV: {}".format(out_f_path))
                    try: _ensure_dir_exists(output_dir); output_files[out_f_path] = open(out_f_path, 'wb'); csv_writers[out_f_path] = csv.writer(output_files[out_f_path]); csv_writers[out_f_path].writerow(ECHOSOUNDER_CSV_HEADER)
                    except (IOError,OSError) as e: self._log_echosounder_message("ERROR creating {}: {}".format(out_f_path,e)); self.echosounder_cancel_extraction_flag=True; break
                writer = csv_writers.get(out_f_path)
                if not writer: continue
                for spn, data_dict in spn_data_list.items():
                    if self.echosounder_cancel_extraction_flag: break
                    csv_row = [data_dict.get(h,"N/A") for h in ECHOSOUNDER_CSV_HEADER]; self._update_echosounder_preview(csv_row)
                    try: writer.writerow(csv_row)
                    except Exception as e: self._log_echosounder_message("Error writing to CSV {}: {}".format(out_f_path,e))
                if self.echosounder_cancel_extraction_flag: break
        except Exception as e: import traceback; self._log_echosounder_message("FATAL ERROR: {}".format(e)); self._log_echosounder_message(traceback.format_exc())
        finally:
            for fpath, fhandle in output_files.items():
                try:
                    if fhandle and not fhandle.closed: fhandle.close(); self._log_echosounder_message("Closed CSV: {}".format(os.path.basename(fpath)))
                except Exception as e: self._log_echosounder_message("Warning closing {}: {}".format(fpath,e))
            self.after(0, self._echosounder_extraction_finished)

    def _start_feather_calculation_thread(self):
        output_files, csv_writers = {}, {}
        all_sequences_data_for_feather = OrderedDict() 
        target_streamer_id = None
        try:
            input_files = list(self.feather_p111_files)
            output_dir = self.feather_output_dir_var.get()
            individual_csv = self.feather_individual_csv_var.get()

            if not input_files: 
                self._log_feather_message("Error: No input files selected.")
                self.after(0,self._feather_calculation_finished)
                return

            feather_vessel_id, _ = self._scan_header_for_ids(input_files, self._log_feather_message)
            if not feather_vessel_id: 
                self._log_feather_message("Error: Vessel ID needed for Feather calculation could not be detected from P111 header. Stopping Feather calculation.")
                self.after(0,self._feather_calculation_finished)
                return
            self._log_feather_message("Using detected Vessel ID for Feather calc: {}".format(feather_vessel_id))

            self._log_feather_message("Pass 0: Determining middle streamer from header...")
            streamer_ids_found=[]
            streamer_prefix="S" 
            try:
                with open(input_files[0],'r') as headerfile:
                    for i,line_content in enumerate(headerfile):
                        if i > 2000: break 
                        line_content=line_content.strip()
                        if line_content.startswith(HC_STREAMER_PREFIX):
                            fields=line_content.split(',')
                            if len(fields) > 6:
                                sid=fields[6].strip()
                                if sid and sid not in streamer_ids_found:
                                    streamer_ids_found.append(sid)
                                    if len(streamer_ids_found) == 1: 
                                        match = re.match(r"([a-zA-Z]+)", sid)
                                        if match: streamer_prefix = match.group(1)
                streamer_ids_found.sort(key=lambda x: int(x[len(streamer_prefix):]) if x.startswith(streamer_prefix) and x[len(streamer_prefix):].isdigit() else float('inf'))
                if not streamer_ids_found:
                    self._log_feather_message("Error: No '{}...' defs found in header to determine streamers.".format(HC_STREAMER_PREFIX))
                    self.after(0, self._feather_calculation_finished)
                    return
                num_streamers=len(streamer_ids_found)
                mid_index=int(math.ceil(num_streamers / 2.0)) - 1 
                target_streamer_id=streamer_ids_found[mid_index]
                self._log_feather_message("Found {} streamers (e.g., '{}'-'{}'). Using middle streamer: {}".format(num_streamers, streamer_ids_found[0] if streamer_ids_found else "N/A", streamer_ids_found[-1] if streamer_ids_found else "N/A", target_streamer_id))
            except Exception as e:
                self._log_feather_message("Header scan error for streamers: {}".format(e))
                self.after(0, self._feather_calculation_finished)
                return

            self._log_feather_message("Pass 1: Reading files for target streamer {}...".format(target_streamer_id))
            for filename in input_files:
                if self.feather_cancel_extraction_flag: break
                self._log_feather_message("Pass 1 Processing: {}".format(os.path.basename(filename)))
                current_sequence_in_file = "N/A"
                current_line_name_in_file = "N/A"
                current_subline_in_file = ""
                current_line_direction_in_file = None
                line_count=0
                
                try:
                    with open(filename,'r') as infile:
                        for line_content in infile: # Renamed 'line' to 'line_content' to avoid clash with variable in get_or_init_spn_data if it were a global
                            line_count+=1
                            L=line_content.strip() # Use L for stripped line
                            if self.feather_cancel_extraction_flag or not L: continue

                            if L.startswith(CC_SEQUENCE_PREFIX): 
                                try: current_sequence_in_file=L.split('=')[1].strip() or "N/A"
                                except IndexError: pass
                            elif L.startswith(CC_LINENAME_PREFIX):
                                try: 
                                     parts=L.split('=')[1].strip(); name_parts=[p for p in parts.split('/') if p]
                                     current_line_name_in_file=name_parts[0] if len(name_parts)>0 else "N/A"
                                     current_subline_in_file=name_parts[1] if len(name_parts)>1 else ""
                                except (IndexError,ValueError): pass
                            elif L.startswith(CC_LINE_DIRECTION_PREFIX): 
                                try: current_line_direction_in_file=float(L.split('=')[1].strip())
                                except (IndexError, ValueError, TypeError): current_line_direction_in_file=None # Ensure it's None on error
                            
                            # Helper to manage SPN data within the current sequence
                            def get_or_init_spn_data_feather(seq, spn_val, line_name, subline_val, preplot_val_default, line_dir_val):
                                if seq not in all_sequences_data_for_feather: 
                                    all_sequences_data_for_feather[seq] = OrderedDict()
                                current_seq_dict = all_sequences_data_for_feather[seq]
                                if spn_val not in current_seq_dict:
                                    current_seq_dict[spn_val] = {
                                        'Seq': seq, 'Line': line_name, 'Sub': subline_val, 
                                        'Preplot': preplot_val_default, # Default preplot
                                        'LineDir': line_dir_val,
                                        'VesPos': None, 'R1Pos': None, 'RLastPos': None, 'max_rx_num': 0
                                    }
                                # Always update line/subline/seq from current context
                                current_seq_dict[spn_val]['Seq'] = seq
                                current_seq_dict[spn_val]['Line'] = line_name
                                current_seq_dict[spn_val]['Sub'] = subline_val
                                # Update LineDir only if it's None and new one is available
                                if current_seq_dict[spn_val].get('LineDir') is None and line_dir_val is not None:
                                    current_seq_dict[spn_val]['LineDir'] = line_dir_val
                                return current_seq_dict[spn_val]

                            if L.startswith('P1,'):
                                try:
                                    fields=L.split(',')
                                    if len(fields) > max(P_REC_SPN_IDX,P_REC_DEVICE_ID_IDX,P_REC_LATITUDE_IDX,P_REC_LONGITUDE_IDX,P_REC_EASTING_IDX,P_REC_NORTHING_IDX):
                                        spn=fields[P_REC_SPN_IDX].strip()
                                        device_id=fields[P_REC_DEVICE_ID_IDX].strip()
                                        if device_id==feather_vessel_id:
                                            preplot_p1 = fields[P_REC_PREPLOT_IDX].strip()
                                            spn_entry = get_or_init_spn_data_feather(current_sequence_in_file, spn, current_line_name_in_file, current_subline_in_file, preplot_p1, current_line_direction_in_file)
                                            
                                            lat_s=format_decimal_degrees_to_deg_min(fields[P_REC_LATITUDE_IDX].strip(),'lat')
                                            lon_s=format_decimal_degrees_to_deg_min(fields[P_REC_LONGITUDE_IDX].strip(),'lon')
                                            easting_p1 = fields[P_REC_EASTING_IDX].strip()
                                            northing_p1 = fields[P_REC_NORTHING_IDX].strip()
                                            spn_entry['VesPos']=(lat_s,lon_s,easting_p1,northing_p1)
                                            spn_entry['Preplot'] = preplot_p1 # P1 preplot is preferred
                                except Exception as e_p1_parse:self._log_feather_message("Warning (Feather/P1): Err parsing line {} (Seq {}): {}".format(line_count, current_sequence_in_file, e_p1_parse))
                            
                            elif L.startswith('R1,'):
                                try:
                                    initial_fields=L.split(',')
                                    min_initial_r1_fields = max(R_SPN_IDX, R_PREPLOT_IDX, R_STREAMER_ID_IDX, R_RECEIVER_NUM_IDX) +1 # Simplified, ensure core R1 info is there
                                    if len(initial_fields) >= min_initial_r1_fields and initial_fields[R_STREAMER_ID_IDX].strip()==target_streamer_id:
                                        spn=initial_fields[R_SPN_IDX].strip()
                                        preplot_r1 = initial_fields[R_PREPLOT_IDX].strip()
                                        spn_entry = get_or_init_spn_data_feather(current_sequence_in_file, spn, current_line_name_in_file, current_subline_in_file, preplot_r1, current_line_direction_in_file)
                                        
                                        idx_first_rx_char = 0
                                        if R_RECEIVER_NUM_IDX > 0: 
                                            prefix_str = ','.join(initial_fields[:R_RECEIVER_NUM_IDX])
                                            idx_first_rx_char = len(prefix_str) + 1
                                        
                                        all_rx_str = L[idx_first_rx_char:]
                                        rx_blocks = all_rx_str.split(',,,,')
                                        current_max_rx_for_spn_entry = spn_entry.get('max_rx_num', 0) # Use the one from spn_entry

                                        for block_str in rx_blocks:
                                            block_str=block_str.strip()
                                            if not block_str:continue
                                            rx_fields=block_str.split(',')
                                            if len(rx_fields)>=3: # RxNum, Easting, Northing
                                                try:
                                                    rx_num_val=int(rx_fields[0].strip())
                                                    easting_val=rx_fields[1].strip()
                                                    northing_val=rx_fields[2].strip()
                                                    float(easting_val);float(northing_val) # Validate
                                                    if rx_num_val==1:spn_entry['R1Pos']=(easting_val,northing_val)
                                                    if rx_num_val > current_max_rx_for_spn_entry: 
                                                        current_max_rx_for_spn_entry=rx_num_val # Update local max for this R1 line's blocks
                                                        spn_entry['max_rx_num']=rx_num_val
                                                        spn_entry['RLastPos']=(easting_val,northing_val)
                                                except (ValueError,TypeError,IndexError)as ex_rx_blk:self._log_feather_message("Warning (Feather/R1 Blk): SPN {} Seq {} Line {} - {}: {}".format(spn, current_sequence_in_file, line_count, block_str, ex_rx_blk))
                                except Exception as e_r1_parse:self._log_feather_message("Warning (Feather/R1): Err parsing line {} (Seq {}): {}".format(line_count, current_sequence_in_file, e_r1_parse))
                except IOError as e: self._log_feather_message("IOError reading {}:{}".format(os.path.basename(filename),e)); continue
                if self.feather_cancel_extraction_flag: break
            
            if self.feather_cancel_extraction_flag: self.after(0,self._feather_calculation_finished); return
            if not all_sequences_data_for_feather: self._log_feather_message("Warning: No suitable P1 (vessel) or R1 (target streamer) records found."); self.after(0,self._feather_calculation_finished);return

            self._log_feather_message("Pass 2: Calculating Feather and writing CSV...")
            
            # Log details for the first SPN of the first sequence processed (after sorting)
            if all_sequences_data_for_feather:
                try:
                    # Ensure robust_sequence_sort_key is defined or use simple sort if appropriate for seq names
                    first_seq_key_overall = sorted(all_sequences_data_for_feather.keys(), key=robust_sequence_sort_key)[0]
                    if all_sequences_data_for_feather[first_seq_key_overall]: # Check if sequence has SPNs
                        first_spn_key_in_first_seq = all_sequences_data_for_feather[first_seq_key_overall].keys()[0]
                        first_spn_data_overall = all_sequences_data_for_feather[first_seq_key_overall][first_spn_key_in_first_seq]
                        log_msg_parts = ["Details for first SPN processed ({} in Seq {}):".format(first_spn_key_in_first_seq, first_seq_key_overall)]
                        r1p=first_spn_data_overall.get('R1Pos')
                        rlp=first_spn_data_overall.get('RLastPos')
                        lrx=first_spn_data_overall.get('max_rx_num')
                        log_msg_parts.append("  - R1Pos: {}".format(r1p if r1p else "N/A"))
                        log_msg_parts.append("  - RLastPos (Rx#{}): {}".format(lrx if lrx else "N/A", rlp if rlp else "N/A"))
                        self._log_feather_message("\n".join(log_msg_parts))
                except IndexError: # Handles empty all_sequences_data_for_feather or empty first sequence
                    self._log_feather_message("Info: Not enough data to log first SPN details for Feather.")
                except Exception as e_log: # Catch any other error during this logging
                    self._log_feather_message("Info: Error logging first SPN details for Feather: {}".format(e_log))


            combined_csv_filename = "combined_FeatherData.csv"
            if not individual_csv:
                valid_seqs = [s for s in all_sequences_data_for_feather.keys() if s!="N/A"]; s_range="all_sequences"
                if valid_seqs: 
                    s_sorted=sorted(valid_seqs,key=robust_sequence_sort_key)
                    s_range="{}-{}".format(s_sorted[0],s_sorted[-1]) if s_sorted[0]!=s_sorted[-1] else s_sorted[0]
                combined_csv_filename="{}_FeatherData.csv".format("".join(c if c.isalnum()or c in('_','-')else'_'for c in s_range))

            sorted_seq_names = sorted(all_sequences_data_for_feather.keys(), key=robust_sequence_sort_key)
            processed_count=0
            for seq_name in sorted_seq_names:
                if self.feather_cancel_extraction_flag: break
                spn_data_list = all_sequences_data_for_feather[seq_name]
                out_f_path=os.path.join(output_dir,"{}_FeatherData.csv".format("".join(c if c.isalnum()or c in('_','-')else'_'for c in seq_name)))if individual_csv else os.path.join(output_dir,combined_csv_filename)
                if out_f_path not in csv_writers:
                    self._log_feather_message("Creating/Opening CSV: {}".format(out_f_path))
                    try: 
                        _ensure_dir_exists(output_dir)
                        output_files[out_f_path]=open(out_f_path,'wb')
                        csv_writers[out_f_path]=csv.writer(output_files[out_f_path])
                        csv_writers[out_f_path].writerow(FEATHER_CSV_HEADER)
                    except (IOError,OSError)as e_io:
                        self._log_feather_message("ERROR creating {}: {}".format(out_f_path,e_io))
                        self.feather_cancel_extraction_flag=True;break
                writer=csv_writers.get(out_f_path)
                if not writer:continue # Should not happen if above try succeeded
                for spn,data in spn_data_list.items():
                    if self.feather_cancel_extraction_flag:break
                    f_angle=calculate_feather(data.get('R1Pos'),data.get('RLastPos'),data.get('LineDir'))
                    f_out=f_angle if f_angle is not None else "N/A"
                    if f_out!="N/A":processed_count+=1
                    
                    ves_pos_data=data.get('VesPos')
                    ves_lat,ves_lon,ves_east,ves_north='N/A','N/A','N/A','N/A'
                    if ves_pos_data and len(ves_pos_data)>=4:
                        ves_lat,ves_lon,ves_east,ves_north = ves_pos_data
                    
                    csv_row=[data.get('Seq','N/A'),data.get('Line','N/A'),data.get('Sub',''),spn,data.get('Preplot','N/A'),ves_lat,ves_lon,ves_east,ves_north,f_out]
                    self._update_feather_preview(csv_row)
                    try:writer.writerow(csv_row)
                    except Exception as e_write_csv:self._log_feather_message("Error writing row to CSV {}: {}".format(out_f_path,e_write_csv))
                if self.feather_cancel_extraction_flag:break
            self._log_feather_message("Feather calculation complete. {} valid feather values generated.".format(processed_count))
        except Exception as e_fatal_feather: 
            import traceback
            self._log_feather_message("FATAL ERROR during Feather calculation thread: {}".format(e_fatal_feather))
            self._log_feather_message(traceback.format_exc())
        finally:
            for fp,fh in output_files.items():
                try:
                    if fh and not fh.closed:fh.close();self._log_feather_message("Closed CSV: {}".format(os.path.basename(fp)))
                except Exception as e_close_feather:self._log_feather_message("Warning: Error closing output file {}: {}".format(fp,e_close_feather))
            self.after(0,self._feather_calculation_finished)

# --- Main Execution ---
if __name__ == "__main__":
    app = P111ExtractorApp()
    app.mainloop()
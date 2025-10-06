# --- Standard Library Imports ---
import configparser
import glob
import logging
import os
import sys
import threading
import time

# --- Third-Party Library Imports ---
import cv2
import customtkinter as ctk
import numpy as np
import pyautogui
from tkinter import messagebox
from pynput import keyboard

# --- Platform-Specific Imports (Windows) ---
try:
    import win32con
    import win32gui
except ImportError:
    logging.warning("win32gui and win32con not found. Area selection feature might be limited.")
    win32gui = None
    win32con = None

# --- RESOURCE PATH RESOLUTION ---
# Determines the correct path for resources whether running as a script or a frozen executable.
if getattr(sys, 'frozen', False):
    application_path = os.path.dirname(sys.executable)
else:
    application_path = os.path.dirname(os.path.abspath(__file__))

# --- LOGGING SETUP ---
log_file_path = os.path.join(application_path, 'Image-auto-clicker.log')
logging.basicConfig(filename=log_file_path, level=logging.INFO,
                    format='%(asctime)s - %(levelname)s: %(message)s')

# --- UI APPEARANCE SETUP ---
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class ResettableEntry(ctk.CTkFrame):
    """
    A custom widget that groups a CTkLabel, a CTkEntry, and a reset button.

    The reset button (⟲) appears to the left of the entry field only when the
    current value differs from the specified default value. This provides a clean
    and intuitive way for users to revert individual settings.

    Layout: [Label] ...... [Reset Button][Entry]
    """
    def __init__(self, master, label_text: str, textvariable: ctk.StringVar, default_value, entry_width: int = 80):
        """
        Initializes the ResettableEntry widget.

        Args:
            master: The parent widget.
            label_text (str): The text to display in the label.
            textvariable (ctk.StringVar): The variable linked to the entry field.
            default_value: The default value to which the entry can be reset.
            entry_width (int): The width of the entry field.
        """
        super().__init__(master, fg_color="transparent")

        self.textvariable = textvariable
        self.default_value = str(default_value)

        # --- Widget Grid Configuration ---
        # Column 0: Label
        # Column 1: Stretchy column containing the button + entry group
        self.grid_columnconfigure(1, weight=1)

        # --- Widget Creation ---
        self.label = ctk.CTkLabel(self, text=label_text)
        self.label.grid(row=0, column=0, sticky="w")

        # Create a nested frame to hold the button and entry together on the right side.
        entry_frame = ctk.CTkFrame(self, fg_color="transparent")
        entry_frame.grid(row=0, column=1, sticky="e")

        # Create the reset button and entry inside the nested frame.
        self.reset_button = ctk.CTkButton(entry_frame, text="⟲", width=30, command=self._reset_to_default)
        self.entry = ctk.CTkEntry(entry_frame, textvariable=self.textvariable, width=entry_width)
        self.entry.grid(row=0, column=1) # The entry is always visible in the second column.

        # --- Logic Initialization ---
        # Add a trace to the variable to check its value whenever it changes.
        self.textvariable.trace_add("write", self._check_value)
        # Perform an initial check to set the initial visibility of the reset button.
        self._check_value()

    def _check_value(self, *args):
        """
        Checks the entry's current value and shows or hides the reset button.
        This method is called automatically whenever the textvariable is modified.
        """
        if self.textvariable.get() != self.default_value:
            # If the value is not the default, show the reset button.
            self.reset_button.grid(row=0, column=0, padx=(0, 5))
        else:
            # If the value is the default, hide the reset button.
            self.reset_button.grid_forget()

    def _reset_to_default(self):
        """Resets the textvariable to its configured default value."""
        self.textvariable.set(self.default_value)


class ImageClickerApp(ctk.CTk):
    """
    Main application class for the Image Auto Clicker.
    """
    def __init__(self):
        super().__init__()
        # --- Initialization Steps ---
        self.setup_translations()
        self.config = configparser.ConfigParser()
        self.config_path = os.path.join(application_path, 'config.ini')
        self._initialize_default_attributes()
        self.load_or_create_config()

        # --- Window Setup ---
        self.title(self.translations[self.current_lang]['title'])
        self.geometry("400x390")
        self.resizable(True, True)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.main_frame = ctk.CTkFrame(self)
        self.main_frame.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        self.main_frame.grid_columnconfigure(0, weight=1)

        # --- State Variables ---
        self.is_running = False
        self.search_thread = None
        self.search_region = None
        self.templates = []
        self.general_settings_expanded = False
        self.mouse_settings_expanded = False
        self.listener = None

        # --- UI Control Variables ---
        self.move_mode = ctk.StringVar(value="smooth")
        self.smooth_duration_var = ctk.StringVar(value=self.default_smooth_duration)
        self.instant_delay_var = ctk.StringVar(value=self.default_instant_delay)
        self.image_folder_var = ctk.StringVar(value=self.image_folder)
        self.threshold_var = ctk.StringVar(value=str(self.threshold))
        self.post_click_delay_var = ctk.StringVar(value=str(self.post_click_delay))
        self.idle_delay_var = ctk.StringVar(value=str(self.idle_delay))
        self.stop_key_var = ctk.StringVar(value=self.stop_key)

        # --- UI Initialization ---
        self.create_widgets()
        self.update_ui_text()
        self.toggle_move_settings()
        self.toggle_general_settings_frame(initial_run=True)
        self.toggle_mouse_settings_frame(initial_run=True)
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        # --- Start the global keyboard listener ---
        self.start_keyboard_listener()


    def create_widgets(self):
            """Creates and places all UI widgets in the main window."""
            # --- Header Section ---
            header_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
            header_frame.grid(row=0, column=0, sticky="ew", pady=5, padx=5)
            header_frame.configure(height=40) # Set a minimum height for proper placement
            self.status_label = ctk.CTkLabel(header_frame, text="", font=ctk.CTkFont(size=16, weight="bold"))
            self.status_label.place(relx=0.5, rely=0.5, anchor="center")
            globe_font = ctk.CTkFont(family="Segoe UI Emoji", size=22)
            self.lang_button = ctk.CTkButton(header_frame, text="🌐", command=self.switch_language, width=40, height=30, font=globe_font)
            self.lang_button.place(relx=1.0, rely=0.5, anchor="e", x=-5)

            # --- Info & Region Labels ---
            self.info_label = ctk.CTkLabel(self.main_frame, text="", text_color="gray")
            self.info_label.grid(row=1, column=0, pady=2)
            self.region_label = ctk.CTkLabel(self.main_frame, text="")
            self.region_label.grid(row=2, column=0, pady=2)

            # --- Area Selection Controls ---
            area_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
            area_frame.grid(row=3, column=0, pady=10)
            area_frame.grid_columnconfigure((0, 1), weight=1)
            self.select_area_button = ctk.CTkButton(area_frame, command=self.select_search_area)
            self.select_area_button.grid(row=0, column=0, padx=5)
            self.reset_area_button = ctk.CTkButton(area_frame, command=self.reset_search_area)
            self.reset_area_button.grid(row=0, column=1, padx=5)

            # --- General Settings (Collapsible Frame) ---
            self.general_settings_container = ctk.CTkFrame(self.main_frame)
            self.general_settings_container.grid(row=4, column=0, pady=5, padx=10, sticky="ew")
            self.general_settings_container.grid_columnconfigure(0, weight=1)

            # Create a dedicated header frame for the collapsible section
            general_settings_header = ctk.CTkFrame(self.general_settings_container, fg_color="transparent", cursor="hand2")
            general_settings_header.grid(row=0, column=0, sticky="ew")
            general_settings_header.configure(height=40)

            self.general_settings_label = ctk.CTkLabel(general_settings_header, text="", font=ctk.CTkFont(weight="bold"))
            self.general_settings_label.place(relx=0.5, rely=0.5, anchor="center") # Center the label

            self.toggle_general_settings_button = ctk.CTkButton(general_settings_header, text="v", width=30, command=self.toggle_general_settings_frame)
            self.toggle_general_settings_button.place(relx=1.0, rely=0.5, anchor="e", x=-10) # Place button on the right

            # --- Click & Hover Logic for General Settings Header ---
            # Make the entire header clickable to toggle the frame
            toggle_general_func = lambda event: self.toggle_general_settings_frame()
            general_settings_header.bind("<Button-1>", toggle_general_func)
            self.general_settings_label.bind("<Button-1>", toggle_general_func)

            # Create a proxy hover effect on the collapse button
            gs_button = self.toggle_general_settings_button
            gs_original_color = gs_button.cget("fg_color")
            gs_hover_color = gs_button.cget("hover_color")

            def on_gs_enter(event):
                gs_button.configure(fg_color=gs_hover_color)

            def on_gs_leave(event):
                gs_button.configure(fg_color=gs_original_color)

            # Bind hover events to the header and label
            general_settings_header.bind("<Enter>", on_gs_enter)
            general_settings_header.bind("<Leave>", on_gs_leave)
            self.general_settings_label.bind("<Enter>", on_gs_enter)
            self.general_settings_label.bind("<Leave>", on_gs_leave)

            self.general_settings_content_frame = ctk.CTkFrame(self.general_settings_container, fg_color="transparent")
            self.general_settings_content_frame.grid(row=1, column=0, sticky="ew", padx=5)
            self.general_settings_content_frame.grid_columnconfigure(0, weight=1)

            self.image_folder_widget = ResettableEntry(self.general_settings_content_frame, "", self.image_folder_var, self.default_image_folder)
            self.image_folder_widget.grid(row=0, column=0, sticky="ew", pady=5, padx=5)
            self.threshold_widget = ResettableEntry(self.general_settings_content_frame, "", self.threshold_var, self.default_threshold)
            self.threshold_widget.grid(row=1, column=0, sticky="ew", pady=5, padx=5)
            self.post_click_delay_widget = ResettableEntry(self.general_settings_content_frame, "", self.post_click_delay_var, self.default_post_click_delay)
            self.post_click_delay_widget.grid(row=2, column=0, sticky="ew", pady=5, padx=5)
            self.idle_delay_widget = ResettableEntry(self.general_settings_content_frame, "", self.idle_delay_var, self.default_idle_delay)
            self.idle_delay_widget.grid(row=3, column=0, sticky="ew", pady=5, padx=5) # MODIFIED: Changed row

            # Add the stop key entry field
            self.stop_key_widget = ResettableEntry(self.general_settings_content_frame, "", self.stop_key_var, self.default_stop_key)
            self.stop_key_widget.grid(row=4, column=0, sticky="ew", pady=(5, 10), padx=5)


            # --- Mouse Movement Settings (Collapsible Frame) ---
            self.mouse_settings_container = ctk.CTkFrame(self.main_frame)
            self.mouse_settings_container.grid(row=5, column=0, pady=5, padx=10, sticky="ew")
            self.mouse_settings_container.grid_columnconfigure(0, weight=1)

            # Create a dedicated header frame for the collapsible section
            mouse_settings_header = ctk.CTkFrame(self.mouse_settings_container, fg_color="transparent", cursor="hand2")
            mouse_settings_header.grid(row=0, column=0, sticky="ew")
            mouse_settings_header.configure(height=40)

            self.move_settings_label = ctk.CTkLabel(mouse_settings_header, font=ctk.CTkFont(weight="bold"))
            self.move_settings_label.place(relx=0.5, rely=0.5, anchor="center") # Center the label

            self.toggle_mouse_settings_button = ctk.CTkButton(mouse_settings_header, text="v", width=30, command=self.toggle_mouse_settings_frame)
            self.toggle_mouse_settings_button.place(relx=1.0, rely=0.5, anchor="e", x=-10) # Place button on the right

            # --- Click & Hover Logic for Mouse Settings Header ---
            toggle_mouse_func = lambda event: self.toggle_mouse_settings_frame()
            mouse_settings_header.bind("<Button-1>", toggle_mouse_func)
            self.move_settings_label.bind("<Button-1>", toggle_mouse_func)

            # Create a proxy hover effect on the collapse button
            ms_button = self.toggle_mouse_settings_button
            ms_original_color = ms_button.cget("fg_color")
            ms_hover_color = ms_button.cget("hover_color")

            def on_ms_enter(event):
                ms_button.configure(fg_color=ms_hover_color)

            def on_ms_leave(event):
                ms_button.configure(fg_color=ms_original_color)

            # Bind hover events to the header and label
            mouse_settings_header.bind("<Enter>", on_ms_enter)
            mouse_settings_header.bind("<Leave>", on_ms_leave)
            self.move_settings_label.bind("<Enter>", on_ms_enter)
            self.move_settings_label.bind("<Leave>", on_ms_leave)

            self.mouse_settings_content_frame = ctk.CTkFrame(self.mouse_settings_container, fg_color="transparent")
            self.mouse_settings_content_frame.grid(row=1, column=0, sticky="ew", padx=5)
            self.mouse_settings_content_frame.grid_columnconfigure(1, weight=1)

            self.smooth_radio = ctk.CTkRadioButton(self.mouse_settings_content_frame, variable=self.move_mode, value="smooth", command=self.toggle_move_settings)
            self.smooth_radio.grid(row=0, column=0, sticky="w", padx=10, pady=5)
            self.smooth_duration_widget = ResettableEntry(self.mouse_settings_content_frame, "", self.smooth_duration_var, self.default_smooth_duration)
            self.smooth_duration_widget.grid(row=0, column=1, sticky="ew", pady=5, padx=5)

            self.instant_radio = ctk.CTkRadioButton(self.mouse_settings_content_frame, variable=self.move_mode, value="instant", command=self.toggle_move_settings)
            self.instant_radio.grid(row=1, column=0, sticky="w", padx=10, pady=(5, 10))
            self.instant_delay_widget = ResettableEntry(self.mouse_settings_content_frame, "", self.instant_delay_var, self.default_instant_delay)
            self.instant_delay_widget.grid(row=1, column=1, sticky="ew", pady=(5, 10), padx=5)

            # --- Main Control Buttons ---
            self.start_button = ctk.CTkButton(self.main_frame, command=self.start_script, height=40)
            self.start_button.grid(row=6, column=0, pady=(15, 5), padx=10, sticky="ew")
            self.stop_button = ctk.CTkButton(self.main_frame, command=self.stop_script, height=40, fg_color="#D32F2F", hover_color="#B71C1C")
            self.stop_button.grid(row=7, column=0, pady=(0, 10), padx=10, sticky="ew")

    # --- Language and Translations ---
    def setup_translations(self):
        """Initializes a dictionary with translations for all UI text elements."""
        self.translations = {
            'en': {
                'title': "Image Auto Clicker", 'status_stopped': "Status: Stopped", 'status_running': "Status: Running",
                'info_waiting': "Press Start or your hotkey", 'info_stopped': "Process stopped.", 'info_searching': "Searching for image...",
                'info_found': "Found: {filename} at ({x}, {y})", 'region_full': "Search Area: Full Screen", 'region_selected': "Area: {region}",
                'select_area': "Select Area", 'reset_area': "Reset",
                'general_settings': "General Settings",
                'image_folder': "Image Folder:", 'threshold': "Threshold (0.1-1.0):",
                'post_click_delay': "Post-Click Delay (sec):", 'idle_delay': "Idle Delay (sec):",
                'stop_key': "Stop Key:", # NEW
                'move_settings': "Mouse Movement",
                'smooth': "Smooth", 'instant': "Instant", 'duration': "Duration:", 'delay': "Delay:",
                'start': "Start", 'stop': "Stop", 'lang_switch_btn': "RU", 'error': "Error", 'warning': "Warning",
                'img_folder_not_found': "Image folder not found: {folder}",
                'no_images_found': "No images found in '{folder}' folder. Add images to start.",
                'no_templates_loaded': "Failed to load any image templates.",
                'cancel_start': "Start cancelled because templates were not loaded."
            },
            'ru': {
                'title': "Image Auto Clicker", 'status_stopped': "Статус: Остановлен", 'status_running': "Статус: Работает",
                'info_waiting': "Нажмите Старт", 'info_stopped': "Работа остановлена.", 'info_searching': "Поиск изображения...",
                'info_found': "Найдено: {filename} в ({x}, {y})", 'region_full': "Область поиска: Весь экран", 'region_selected': "Область: {region}",
                'select_area': "Выбрать область", 'reset_area': "Сбросить",
                'general_settings': "Основные настройки",
                'image_folder': "Папка с картинками:", 'threshold': "Порог совпадения (0.1-1.0):",
                'post_click_delay': "Задержка после клика (сек):", 'idle_delay': "Задержка ожидания (сек):",
                'stop_key': "Клавиша стоп:", # NEW
                'move_settings': "Перемещение мыши",
                'smooth': "Плавное", 'instant': "Мгновенное", 'duration': "Длительность:", 'delay': "Задержка:",
                'start': "Старт", 'stop': "Стоп", 'lang_switch_btn': "EN", 'error': "Ошибка", 'warning': "Внимание",
                'img_folder_not_found': "Папка с изображениями не найдена: {folder}",
                'no_images_found': "В папке '{folder}' не найдено изображений. Добавьте изображения для начала работы.",
                'no_templates_loaded': "Не удалось загрузить ни одного изображения-шаблона.",
                'cancel_start': "Запуск отменен, так как шаблоны не были загружены."
            }
        }

    # --- Configuration Management ---
    def _initialize_default_attributes(self):
        """Sets the hardcoded default values for all settings."""
        self.default_image_folder = 'img'
        self.default_threshold = 0.8
        self.default_post_click_delay = 2.6
        self.default_idle_delay = 0.5
        self.default_smooth_duration = "0.5"
        self.default_instant_delay = "0.1"
        self.default_lang = 'en'
        self.default_stop_key = 'esc' # Default stop key

        # Initialize runtime attributes with these defaults
        self.image_folder = self.default_image_folder
        self.threshold = self.default_threshold
        self.post_click_delay = self.default_post_click_delay
        self.idle_delay = self.default_idle_delay
        self.current_lang = self.default_lang
        self.stop_key = self.default_stop_key

        logging.info("Initialized with default attributes.")

    def load_or_create_config(self):
        """Loads settings from config.ini or uses defaults if the file is not found."""
        if os.path.exists(self.config_path):
            logging.info(f"Loading configuration from {self.config_path}")
            self.config.read(self.config_path, encoding='utf-8')
            # Load settings, falling back to the default values if a key is missing
            self.image_folder = self.config.get('Paths', 'image_folder', fallback=self.default_image_folder)
            self.threshold = self.config.getfloat('Settings', 'threshold', fallback=self.default_threshold)
            self.post_click_delay = self.config.getfloat('Settings', 'post_click_delay', fallback=self.default_post_click_delay)
            self.idle_delay = self.config.getfloat('Settings', 'idle_delay', fallback=self.default_idle_delay)
            self.current_lang = self.config.get('Settings', 'language', fallback=self.default_lang)
            self.stop_key = self.config.get('Settings', 'stop_key', fallback=self.default_stop_key)
        else:
             logging.warning("config.ini not found. It will be created on exit.")
        # Ensure the image folder exists.
        image_folder_path = os.path.join(application_path, self.image_folder)
        if not os.path.isdir(image_folder_path):
            logging.warning(f"Image folder '{self.image_folder}' not found. Creating it.")
            os.makedirs(image_folder_path)

    def save_config(self):
        """Saves the current settings to config.ini."""
        logging.info("Saving configuration...")
        self.config['Paths'] = {'image_folder': self.image_folder_var.get()}
        self.config['Settings'] = {
            'threshold': self.threshold_var.get(),
            'post_click_delay': self.post_click_delay_var.get(),
            'idle_delay': self.idle_delay_var.get(),
            'language': self.current_lang,
            'stop_key': self.stop_key_var.get()
        }
        try:
            with open(self.config_path, 'w', encoding='utf-8') as configfile:
                self.config.write(configfile)
            logging.info(f"Configuration saved to {self.config_path}")
        except IOError as e:
            logging.error(f"Failed to save configuration: {e}")

    # --- UI and State Management ---
    def toggle_general_settings_frame(self, initial_run=False):
        """Expands or collapses the general settings frame."""
        if not initial_run: self.general_settings_expanded = not self.general_settings_expanded
        if self.general_settings_expanded:
            self.general_settings_content_frame.grid(row=1, column=0, sticky="ew", padx=5, pady=(0,5))
            self.toggle_general_settings_button.configure(text="ᐱ") # Up arrow
        else:
            self.general_settings_content_frame.grid_forget()
            self.toggle_general_settings_button.configure(text="v") # Down arrow
        if not initial_run: self._update_window_size()

    def toggle_mouse_settings_frame(self, initial_run=False):
        """Expands or collapses the mouse movement settings frame."""
        if not initial_run: self.mouse_settings_expanded = not self.mouse_settings_expanded
        if self.mouse_settings_expanded:
            self.mouse_settings_content_frame.grid(row=1, column=0, sticky="ew", padx=5, pady=(0,5))
            self.toggle_mouse_settings_button.configure(text="ᐱ") # Up arrow
        else:
            self.mouse_settings_content_frame.grid_forget()
            self.toggle_mouse_settings_button.configure(text="v") # Down arrow
        if not initial_run: self._update_window_size()

    def switch_language(self):
        """Toggles the language and updates all UI text."""
        self.current_lang = 'ru' if self.current_lang == 'en' else 'en'
        self.update_ui_text()

    def update_ui_text(self):
        """Updates the text of all UI widgets based on the current language."""
        lang_dict = self.translations[self.current_lang]
        self.title(lang_dict['title'])
        # self.lang_button.configure(text=lang_dict['lang_switch_btn']) # Button text no longer changes.
        self.status_label.configure(text=lang_dict['status_running'] if self.is_running else lang_dict['status_stopped'])
        if not self.is_running: self.info_label.configure(text=lang_dict['info_waiting'])
        self.reset_search_area()
        self.select_area_button.configure(text=lang_dict['select_area'])
        self.reset_area_button.configure(text=lang_dict['reset_area'])

        # Update labels within the custom ResettableEntry widgets
        self.general_settings_label.configure(text=lang_dict['general_settings'])
        self.image_folder_widget.label.configure(text=lang_dict['image_folder'])
        self.threshold_widget.label.configure(text=lang_dict['threshold'])
        self.post_click_delay_widget.label.configure(text=lang_dict['post_click_delay'])
        self.idle_delay_widget.label.configure(text=lang_dict['idle_delay'])
        self.stop_key_widget.label.configure(text=lang_dict['stop_key'])

        self.move_settings_label.configure(text=lang_dict['move_settings'])
        self.smooth_radio.configure(text=lang_dict['smooth'])
        self.instant_radio.configure(text=lang_dict['instant'])
        self.start_button.configure(text=lang_dict['start'])
        self.stop_button.configure(text=lang_dict['stop'])

    def load_templates(self):
        """Loads all image templates from the specified folder."""
        self.templates = []
        self.image_folder = self.image_folder_var.get()
        folder_path = os.path.join(application_path, self.image_folder)
        if not os.path.isdir(folder_path):
            messagebox.showerror(self.translations[self.current_lang]['error'], self.translations[self.current_lang]['img_folder_not_found'].format(folder=self.image_folder))
            return False
        image_paths = []
        for ext in ('*.png', '*.jpg', '*.jpeg'):
            image_paths.extend(glob.glob(os.path.join(folder_path, ext)))
        if not image_paths:
            messagebox.showwarning(self.translations[self.current_lang]['warning'], self.translations[self.current_lang]['no_images_found'].format(folder=self.image_folder))
            return False
        for path in image_paths:
            try:
                template = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
                if template is None:
                    logging.error(f"Failed to read image (corrupted or unsupported format): {path}")
                    continue
                filename = os.path.basename(path)
                self.templates.append((filename, template))
                logging.info(f"Template '{filename}' loaded successfully.")
            except Exception as e:
                logging.error(f"Error loading template {path}: {e}")
        if not self.templates:
            messagebox.showerror(self.translations[self.current_lang]['error'], self.translations[self.current_lang]['no_templates_loaded'])
            return False
        return True

    def start_script(self):
        """Starts the automation thread."""
        if self.is_running: return
        if not self.load_templates():
            logging.warning(self.translations[self.current_lang]['cancel_start'])
            return
        self.is_running = True
        self.update_status(self.translations[self.current_lang]['status_running'], "#4CAF50")
        self.update_info_label(self.translations[self.current_lang]['info_searching'])
        self.start_button.configure(state=ctk.DISABLED)
        self.stop_button.configure(state=ctk.NORMAL)
        self.search_thread = threading.Thread(target=self.search_and_click_worker, daemon=True)
        self.search_thread.start()
        logging.info("Automation script started.")
        self.focus_set()

    def stop_script(self):
        """Stops the automation thread."""
        if not self.is_running: return
        self.is_running = False
        self.update_status(self.translations[self.current_lang]['status_stopped'], "#F44336")
        self.update_info_label(self.translations[self.current_lang]['info_stopped'])
        self.start_button.configure(state=ctk.NORMAL)
        self.stop_button.configure(state=ctk.DISABLED)
        logging.info("Automation script stopped.")
        self.focus_set()

    def toggle_move_settings(self):
        """Enables or disables entry fields based on the selected move mode."""
        is_smooth = self.move_mode.get() == "smooth"
        # Access the 'entry' attribute of the custom widget to change its state
        self.smooth_duration_widget.entry.configure(state=ctk.NORMAL if is_smooth else ctk.DISABLED)
        self.instant_delay_widget.entry.configure(state=ctk.DISABLED if is_smooth else ctk.NORMAL)

    def select_search_area(self):
        """Hides the main window and shows an overlay for selecting a screen region."""
        self.withdraw()
        self.after(200, self._create_selection_window)

    def _create_selection_window(self):
        """Creates a transparent, fullscreen window to draw a selection rectangle."""
        overlay = ctk.CTkToplevel(self)
        overlay.attributes("-fullscreen", True)
        overlay.attributes("-alpha", 0.3)
        overlay.attributes("-topmost", True)
        overlay.overrideredirect(True)
        canvas = ctk.CTkCanvas(overlay, cursor="cross", bg="white")
        canvas.pack(fill="both", expand=True)
        start_x, start_y, rect_id = 0, 0, None
        def on_mouse_press(event):
            nonlocal start_x, start_y
            start_x, start_y = event.x, event.y
        def on_mouse_drag(event):
            nonlocal rect_id
            if rect_id: canvas.delete(rect_id)
            rect_id = canvas.create_rectangle(start_x, start_y, event.x, event.y, outline='red', width=2)
        def on_mouse_release(event):
            end_x, end_y = event.x, event.y
            left, top = min(start_x, end_x), min(start_y, end_y)
            width, height = abs(start_x - end_x), abs(start_y - end_y)
            if width > 10 and height > 10:
                self.search_region = (left, top, width, height)
                self.region_label.configure(text=self.translations[self.current_lang]['region_selected'].format(region=self.search_region))
            overlay.destroy()
            self.deiconify()
        canvas.bind("<ButtonPress-1>", on_mouse_press)
        canvas.bind("<B1-Motion>", on_mouse_drag)
        canvas.bind("<ButtonRelease-1>", on_mouse_release)

    def reset_search_area(self):
        """Resets the search area to the full screen."""
        self.search_region = None
        self.region_label.configure(text=self.translations[self.current_lang]['region_full'])

    def on_closing(self):
        """Handles the window close event."""
        if self.is_running: self.stop_script()
        if self.listener: 
            self.listener.stop()
        self.save_config()
        self.destroy()

    def _update_window_size(self):
        """Adjusts window height to fit all visible widgets."""
        self.update_idletasks()
        required_height = self.main_frame.winfo_reqheight() + 20
        current_width = self.winfo_width()
        self.geometry(f"{current_width}x{required_height}")

    def update_status(self, text, color):
        """Updates the main status label."""
        self.status_label.configure(text=text, text_color=color)

    def update_info_label(self, message):
        """Updates the secondary informational label."""
        self.info_label.configure(text=message)

    # --- Keyboard Listener Methods ---
    def start_keyboard_listener(self):
        """Initializes and starts the global keyboard listener in a separate thread."""
        if self.listener is None:
            self.listener = keyboard.Listener(on_press=self.on_key_press)
            self.listener.start()
            logging.info("Keyboard listener started.")

    def _get_key_name(self, key):
        """Helper to get a consistent string name for a pressed key."""
        if isinstance(key, keyboard.KeyCode):
            return key.char
        else:
            return key.name

    def on_key_press(self, key):
        """Callback function executed by the listener when a key is pressed."""
        if not self.is_running:
            return # Do nothing if the script is not running

        try:
            pressed_key_name = self._get_key_name(key)
            # Compare the pressed key with the configured stop key (case-insensitive)
            if pressed_key_name and pressed_key_name.lower() == self.stop_key_var.get().lower():
                logging.info(f"Stop key '{pressed_key_name}' pressed. Stopping script.")
                # IMPORTANT: UI updates must be done in the main thread.
                # self.after() schedules the function to be called by the main UI loop.
                self.after(0, self.stop_script)
        except Exception as e:
            logging.error(f"Error in on_key_press: {e}")

    # --- Core Automation Worker ---
    def search_and_click_worker(self):
        """The main automation loop that runs in a separate thread."""
        method = cv2.TM_CCOEFF_NORMED
        while self.is_running:
            found_this_cycle = False
            # Get current settings, falling back to defaults if input is invalid
            try: threshold = float(self.threshold_var.get())
            except ValueError: threshold = self.default_threshold
            try: post_click_delay = float(self.post_click_delay_var.get())
            except ValueError: post_click_delay = self.default_post_click_delay
            try: idle_delay = float(self.idle_delay_var.get())
            except ValueError: idle_delay = self.default_idle_delay
            try: smooth_duration = float(self.smooth_duration_var.get())
            except ValueError: smooth_duration = float(self.default_smooth_duration)
            try: instant_delay = float(self.instant_delay_var.get())
            except ValueError: instant_delay = float(self.default_instant_delay)
            mode = self.move_mode.get()

            # --- Image Recognition ---
            screenshot = pyautogui.screenshot(region=self.search_region)
            screen_gray = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2GRAY)
            for filename, template in self.templates:
                if not self.is_running: break
                try:
                    result = cv2.matchTemplate(screen_gray, template, method)
                    _, max_val, _, max_loc = cv2.minMaxLoc(result)
                    if max_val >= threshold:
                        h, w = template.shape[:2]
                        center_x, center_y = max_loc[0] + w // 2, max_loc[1] + h // 2
                        click_x, click_y = (self.search_region[0] + center_x, self.search_region[1] + center_y) if self.search_region else (center_x, center_y)
                        message = self.translations[self.current_lang]['info_found'].format(filename=filename, x=click_x, y=click_y)
                        self.after(0, self.update_info_label, message)

                        # Perform mouse action
                        if mode == "smooth":
                            pyautogui.moveTo(click_x, click_y, duration=smooth_duration)
                            pyautogui.click()
                        else:
                            pyautogui.moveTo(click_x, click_y, duration=0)
                            time.sleep(instant_delay)
                            pyautogui.click()

                        logging.info(f"Clicked on {filename} at ({click_x}, {click_y}) with confidence {max_val:.2f}")
                        found_this_cycle = True
                        time.sleep(post_click_delay)
                        break
                except Exception as e:
                    logging.error(f"Error during image processing for {filename}: {e}")

            # --- Idle State ---
            if not found_this_cycle and self.is_running:
                self.after(0, self.update_info_label, self.translations[self.current_lang]['info_searching'])
                time.sleep(idle_delay)
        logging.info("Automation worker thread has finished.")

if __name__ == "__main__":
    app = ImageClickerApp()
    app.mainloop()
import cv2
import numpy as np
import pyautogui
import threading
import time
import win32gui
import win32con
import os
import logging
import customtkinter as ctk
from tkinter import messagebox
import configparser
import glob
import sys

# --- ROBUST RESOURCE PATH DETECTION ---
# Determines the application's root directory to correctly locate resources
# like config.ini and the image folder, whether running as a script or a
# frozen executable (e.g., created by PyInstaller).
if getattr(sys, 'frozen', False):
    # Running as a bundled executable.
    application_path = os.path.dirname(sys.executable)
else:
    # Running as a standard Python script.
    application_path = os.path.dirname(os.path.abspath(__file__))
# -------------------------------------------------

# --- Logging Setup ---
# Configure logging to write to a file in the application's root directory.
log_file_path = os.path.join(application_path, 'Image-auto-clicker.log')
logging.basicConfig(filename=log_file_path, level=logging.INFO,
                    format='%(asctime)s - %(levelname)s: %(message)s')

# --- UI Appearance Setup ---
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

class ImageClickerApp(ctk.CTk):
    """
    Main application class for the Image Clicker.
    Handles the UI, configuration, image processing, and automation logic.
    """
    def __init__(self):
        super().__init__()

        # --- Language and Translations ---
        self.setup_translations()

        # --- Configuration ---
        self.config = configparser.ConfigParser()
        self.config_path = os.path.join(application_path, 'config.ini')

        # NEW: Initialize all settings with hardcoded default values first.
        self._initialize_default_attributes()
        # Now, load the config file. If it exists, it will override the defaults.
        # If not, it will be created using the current default attributes.
        self.load_or_create_config()

        # --- Window Setup ---
        self.title(self.translations[self.current_lang]['title'])
        self.geometry("420x480")

        # --- Grid Layout Configuration ---
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.main_frame = ctk.CTkFrame(self)
        self.main_frame.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        self.main_frame.grid_columnconfigure((0, 1), weight=1)
        self.main_frame.grid_rowconfigure(6, weight=1)

        # --- State Variables ---
        self.is_running = False
        self.search_thread = None
        self.search_region = None
        self.templates = []

        # --- UI Control Variables ---
        self.move_mode = ctk.StringVar(value="smooth")
        self.smooth_duration_var = ctk.StringVar(value="0.5")
        self.instant_delay_var = ctk.StringVar(value="0.1")

        # --- UI Widget Creation ---
        self.create_widgets()

        # --- Final UI Initialization ---
        self.update_ui_text()
        self.toggle_move_settings()
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def create_widgets(self):
        """Creates and places all the UI widgets in the main frame."""
        # Language Switch Button
        self.lang_button = ctk.CTkButton(self.main_frame, text="", command=self.switch_language, width=40)
        self.lang_button.grid(row=0, column=1, padx=5, pady=(5,0), sticky="e")

        # Status Labels
        self.status_label = ctk.CTkLabel(self.main_frame, text="", font=ctk.CTkFont(size=16, weight="bold"))
        self.status_label.grid(row=1, column=0, columnspan=2, pady=(10, 2))
        self.info_label = ctk.CTkLabel(self.main_frame, text="", text_color="gray")
        self.info_label.grid(row=2, column=0, columnspan=2, pady=2)
        self.region_label = ctk.CTkLabel(self.main_frame, text="")
        self.region_label.grid(row=3, column=0, columnspan=2, pady=2)

        # Area Selection Frame and Buttons
        area_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        area_frame.grid(row=4, column=0, columnspan=2, pady=10)
        area_frame.grid_columnconfigure((0,1), weight=1)
        self.select_area_button = ctk.CTkButton(area_frame, text="", command=self.select_search_area)
        self.select_area_button.grid(row=0, column=0, padx=5)
        self.reset_area_button = ctk.CTkButton(area_frame, text="", command=self.reset_search_area)
        self.reset_area_button.grid(row=0, column=1, padx=5)

        # Mouse Movement Settings Frame
        self.settings_frame = ctk.CTkFrame(self.main_frame)
        self.settings_frame.grid(row=5, column=0, columnspan=2, pady=10, padx=10, sticky="ew")
        self.settings_frame.grid_columnconfigure(1, weight=1)

        # Smooth Movement Option
        self.smooth_radio = ctk.CTkRadioButton(self.settings_frame, text="", variable=self.move_mode, value="smooth", command=self.toggle_move_settings)
        self.smooth_radio.grid(row=1, column=0, sticky="w", padx=10, pady=5)
        self.smooth_label = ctk.CTkLabel(self.settings_frame, text="")
        self.smooth_label.grid(row=1, column=1, sticky="e")
        self.smooth_entry = ctk.CTkEntry(self.settings_frame, textvariable=self.smooth_duration_var, width=60)
        self.smooth_entry.grid(row=1, column=2, sticky="e", padx=10)

        # Instant Movement Option
        self.instant_radio = ctk.CTkRadioButton(self.settings_frame, text="", variable=self.move_mode, value="instant", command=self.toggle_move_settings)
        self.instant_radio.grid(row=2, column=0, sticky="w", padx=10, pady=5)
        self.instant_label = ctk.CTkLabel(self.settings_frame, text="")
        self.instant_label.grid(row=2, column=1, sticky="e")
        self.instant_entry = ctk.CTkEntry(self.settings_frame, textvariable=self.instant_delay_var, width=60)
        self.instant_entry.grid(row=2, column=2, sticky="e", padx=10)

        # Start/Stop Buttons
        self.start_button = ctk.CTkButton(self.main_frame, text="", command=self.start_script, height=40)
        self.start_button.grid(row=7, column=0, columnspan=2, pady=(5,5), padx=10, sticky="ew")
        self.stop_button = ctk.CTkButton(self.main_frame, text="", command=self.stop_script, height=40, fg_color="#D32F2F", hover_color="#B71C1C")
        self.stop_button.grid(row=8, column=0, columnspan=2, pady=(0, 10), padx=10, sticky="ew")

    def setup_translations(self):
        """Initializes a dictionary with translations for UI elements."""
        self.translations = {
            'en': {
                'title': "Image Clicker", 'status_stopped': "Status: Stopped", 'status_running': "Status: Running",
                'info_waiting': "Waiting to start...", 'info_stopped': "Process stopped.", 'info_searching': "Searching for image...",
                'info_found': "Found: {filename} at ({x}, {y})", 'region_full': "Search Area: Full Screen", 'region_selected': "Area: {region}",
                'select_area': "Select Area", 'reset_area': "Reset", 'settings_frame': "Mouse Movement Settings",
                'smooth': "Smooth", 'instant': "Instant", 'duration': "Duration (sec):", 'delay': "Delay (sec):",
                'start': "Start", 'stop': "Stop", 'lang_switch_btn': "RU", 'error': "Error", 'warning': "Warning",
                'img_folder_not_found': "Image folder not found: {folder}",
                'no_images_found': "No images found in '{folder}' folder. Add images to start.",
                'no_templates_loaded': "Failed to load any image templates.",
                'cancel_start': "Start cancelled because templates were not loaded."
            },
            'ru': {
                'title': "Image Clicker", 'status_stopped': "Статус: Остановлен", 'status_running': "Статус: Работает",
                'info_waiting': "Ожидание запуска...", 'info_stopped': "Работа остановлена.", 'info_searching': "Поиск изображения...",
                'info_found': "Найдено: {filename} в ({x}, {y})", 'region_full': "Область поиска: Весь экран", 'region_selected': "Область: {region}",
                'select_area': "Выбрать область", 'reset_area': "Сбросить", 'settings_frame': "Настройки перемещения мыши",
                'smooth': "Плавное", 'instant': "Мгновенное", 'duration': "Длительность (сек):", 'delay': "Задержка (сек):",
                'start': "Старт", 'stop': "Стоп", 'lang_switch_btn': "EN", 'error': "Ошибка", 'warning': "Внимание",
                'img_folder_not_found': "Папка с изображениями не найдена: {folder}",
                'no_images_found': "В папке '{folder}' не найдено изображений. Добавьте изображения для начала работы.",
                'no_templates_loaded': "Не удалось загрузить ни одного изображения-шаблона.",
                'cancel_start': "Запуск отменен, так как шаблоны не были загружены."
            }
        }

    # --- Configuration Management ---

    def _initialize_default_attributes(self):
        """Sets the default fallback values for all configuration-dependent attributes."""
        self.image_folder = 'img'
        self.threshold = 0.8
        self.post_click_delay = 2.6
        self.idle_delay = 0.5
        self.current_lang = 'en'
        logging.info("Initialized with default attributes.")

    def load_or_create_config(self):
        """
        Loads the configuration from config.ini.
        If the file or the image folder doesn't exist, they are created with default values.
        """
        # Ensure the image folder exists, creating it if necessary.
        image_folder_path = os.path.join(application_path, self.image_folder)
        if not os.path.isdir(image_folder_path):
            logging.warning(f"Image folder '{image_folder_path}' not found. Creating it.")
            os.makedirs(image_folder_path)

        # If config.ini does not exist, create it from the current default attributes.
        if not os.path.exists(self.config_path):
            logging.warning("config.ini not found. Creating a default one from attributes.")
            self.save_config()
        # If it exists, load it and override the default attributes.
        else:
            logging.info(f"Loading configuration from {self.config_path}")
            self.config.read(self.config_path, encoding='utf-8')
            # The 'fallback' argument uses the existing self.attribute if a key is not in the file.
            self.image_folder = self.config.get('Paths', 'image_folder', fallback=self.image_folder)
            self.threshold = self.config.getfloat('Settings', 'threshold', fallback=self.threshold)
            self.post_click_delay = self.config.getfloat('Settings', 'post_click_delay', fallback=self.post_click_delay)
            self.idle_delay = self.config.getfloat('Settings', 'idle_delay', fallback=self.idle_delay)
            self.current_lang = self.config.get('Settings', 'language', fallback=self.current_lang)
            logging.info("Configuration loaded successfully.")

    def save_config(self):
        """Saves the current application attributes to the config.ini file."""
        logging.info("Saving configuration...")
        # Populate the config object with current application state.
        self.config['Paths'] = {
            'image_folder': self.image_folder
        }
        self.config['Settings'] = {
            'threshold': str(self.threshold),
            'post_click_delay': str(self.post_click_delay),
            'idle_delay': str(self.idle_delay),
            'language': self.current_lang
        }
        try:
            with open(self.config_path, 'w', encoding='utf-8') as configfile:
                self.config.write(configfile)
            logging.info(f"Configuration saved to {self.config_path}")
        except Exception as e:
            logging.error(f"Failed to save configuration: {e}")

    # --- UI and State Management ---

    def switch_language(self):
        """Toggles the current language and updates the UI text."""
        self.current_lang = 'ru' if self.current_lang == 'en' else 'en'
        self.update_ui_text()

    def update_ui_text(self):
        """Updates the text of all UI widgets based on the current language."""
        lang_dict = self.translations[self.current_lang]
        self.title(lang_dict['title'])
        self.lang_button.configure(text=lang_dict['lang_switch_btn'])

        self.status_label.configure(text=lang_dict['status_running'] if self.is_running else lang_dict['status_stopped'])
        self.info_label.configure(text=lang_dict['info_waiting'])
        self.reset_search_area() # Also updates region label text
        self.select_area_button.configure(text=lang_dict['select_area'])
        self.reset_area_button.configure(text=lang_dict['reset_area'])
        self.smooth_radio.configure(text=lang_dict['smooth'])
        self.instant_radio.configure(text=lang_dict['instant'])
        self.smooth_label.configure(text=lang_dict['duration'])
        self.instant_label.configure(text=lang_dict['delay'])
        self.start_button.configure(text=lang_dict['start'])
        self.stop_button.configure(text=lang_dict['stop'])

    def load_templates(self):
        """
        Loads all image templates from the specified folder into memory.
        Returns True if successful, False otherwise.
        """
        self.templates = []
        folder_path = os.path.join(application_path, self.image_folder)

        if not os.path.isdir(folder_path):
            messagebox.showerror(self.translations[self.current_lang]['error'],
                                 self.translations[self.current_lang]['img_folder_not_found'].format(folder=folder_path))
            return False

        search_patterns = [os.path.join(folder_path, ext) for ext in ('*.png', '*.jpg', '*.jpeg')]
        image_paths = []
        for pattern in search_patterns:
            image_paths.extend(glob.glob(pattern))

        if not image_paths:
            messagebox.showwarning(self.translations[self.current_lang]['warning'],
                                   self.translations[self.current_lang]['no_images_found'].format(folder=self.image_folder))
            return False

        for path in image_paths:
            try:
                template = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
                if template is None:
                    logging.error(f"Failed to read image: {path}")
                    continue
                filename = os.path.basename(path)
                self.templates.append((filename, template))
                logging.info(f"Template '{filename}' loaded successfully.")
            except Exception as e:
                logging.error(f"Error loading template {path}: {e}")

        if not self.templates:
            messagebox.showerror(self.translations[self.current_lang]['error'],
                                 self.translations[self.current_lang]['no_templates_loaded'])
            return False

        return True

    def start_script(self):
        """Starts the image search and click process in a separate thread."""
        if self.is_running:
            return

        if not self.load_templates():
            logging.warning("Start cancelled because templates were not loaded.")
            return

        self.is_running = True
        self.update_status(self.translations[self.current_lang]['status_running'], "#4CAF50") # Green
        self.update_info_label(self.translations[self.current_lang]['info_searching'])
        self.start_button.configure(state=ctk.DISABLED)
        self.stop_button.configure(state=ctk.NORMAL)

        self.search_thread = threading.Thread(target=self.search_and_click_worker, daemon=True)
        self.search_thread.start()
        logging.info("Script started via UI.")
        self.focus_set()

    def stop_script(self):
        """Stops the image search and click process."""
        if not self.is_running:
            return

        self.is_running = False
        self.update_status(self.translations[self.current_lang]['status_stopped'], "#F44336") # Red
        self.update_info_label(self.translations[self.current_lang]['info_stopped'])
        self.start_button.configure(state=ctk.NORMAL)
        self.stop_button.configure(state=ctk.DISABLED)
        logging.info("Script stopped via UI.")
        self.focus_set()

    def toggle_move_settings(self):
        """Enables or disables entry fields based on the selected move mode."""
        if self.move_mode.get() == "smooth":
            self.smooth_entry.configure(state=ctk.NORMAL)
            self.instant_entry.configure(state=ctk.DISABLED)
        else:
            self.smooth_entry.configure(state=ctk.DISABLED)
            self.instant_entry.configure(state=ctk.NORMAL)

    def select_search_area(self):
        """Hides the main window to initiate the screen selection process."""
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
            if rect_id:
                canvas.delete(rect_id)
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
        if self.is_running:
            self.stop_script()
        # Save the latest settings (e.g., language) on exit.
        self.save_config()
        self.destroy()

    def update_status(self, text, color):
        """Helper function to update the status label text and color."""
        self.status_label.configure(text=text, text_color=color)

    def update_info_label(self, message):
        """Helper function to update the info label text."""
        self.info_label.configure(text=message)

    # --- Core Worker Thread ---

    def search_and_click_worker(self):
        """
        The core worker function that runs in a background thread.
        Continuously takes screenshots and searches for the template images.
        """
        method = cv2.TM_CCOEFF_NORMED
        while self.is_running:
            found_this_cycle = False

            # Get settings from UI safely.
            mode = self.move_mode.get()
            try: smooth_duration = float(self.smooth_duration_var.get())
            except ValueError: smooth_duration = 0.5
            try: instant_delay = float(self.instant_delay_var.get())
            except ValueError: instant_delay = 0.1

            screenshot = pyautogui.screenshot(region=self.search_region)
            screen_np = np.array(screenshot)
            screen_gray = cv2.cvtColor(screen_np, cv2.COLOR_RGB2GRAY)

            for filename, template in self.templates:
                if not self.is_running: break
                try:
                    result = cv2.matchTemplate(screen_gray, template, method)
                    _, max_val, _, max_loc = cv2.minMaxLoc(result)

                    if max_val >= self.threshold:
                        h, w = template.shape[:2]
                        center_x = max_loc[0] + w // 2
                        center_y = max_loc[1] + h // 2

                        click_x, click_y = (self.search_region[0] + center_x, self.search_region[1] + center_y) if self.search_region else (center_x, center_y)

                        message = self.translations[self.current_lang]['info_found'].format(filename=filename, x=click_x, y=click_y)
                        self.after(0, self.update_info_label, message)

                        if mode == "smooth":
                            pyautogui.moveTo(click_x, click_y, duration=smooth_duration)
                            pyautogui.click()
                        else: # Instant mode
                            pyautogui.moveTo(click_x, click_y, duration=0)
                            time.sleep(instant_delay)
                            pyautogui.click()

                        logging.info(f"Clicked on {filename} at ({click_x}, {click_y})")
                        found_this_cycle = True
                        time.sleep(self.post_click_delay)
                        break
                except Exception as e:
                    logging.error(f"Error processing {filename}: {e}")

            if not found_this_cycle and self.is_running:
                self.after(0, self.update_info_label, self.translations[self.current_lang]['info_searching'])
                time.sleep(self.idle_delay)

        logging.info("Worker thread finished.")

if __name__ == "__main__":
    app = ImageClickerApp()
    app.mainloop()
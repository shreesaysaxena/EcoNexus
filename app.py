from flask import Flask, render_template, request, jsonify, current_app
from werkzeug.utils import secure_filename
import os
import time
from PIL import Image
import google.generativeai as genai
import re
import serial
from threading import Thread, Event
from queue import Queue, Empty
import logging

# Flask app setup
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'static/uploads'

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Arduino Controller Class
class ArduinoController:
    def __init__(self, port='COM9', baudrate=9600):
        self.port = port
        self.baudrate = baudrate
        self.arduino = None
        self.connect()

    def connect(self):
        try:
            self.arduino = serial.Serial(port=self.port, baudrate=self.baudrate, timeout=1)
            logger.info(f"Connected to Arduino on {self.port}")
        except serial.SerialException as e:
            logger.error(f"Failed to connect to Arduino: {e}")
            self.arduino = None

    def send_command(self, command):
        if not self.arduino:
            logger.error("Arduino not connected")
            return False
        try:
            self.arduino.write(command.encode())
            return True
        except Exception as e:
            logger.error(f"Error sending command to Arduino: {e}")
            return False

    def close(self):
        if self.arduino:
            try:
                self.arduino.close()
                logger.info("Arduino connection closed")
            except Exception as e:
                logger.error(f"Error closing Arduino connection: {e}")

# Image Processor Class
class ImageProcessor:
    def __init__(self):
        self.process_queue = Queue()
        self.stop_event = Event()
        self.processing_thread = None
        self.arduino = ArduinoController()
        self.initialize_gemini()

    def initialize_gemini(self):
        try:
            genai.configure(api_key="AIzaSyB_RFI7WlcUZJLC1eVGjrjZyUH_wX74RVo")
            self.model = genai.GenerativeModel("gemini-1.5-flash")
            logger.info("Gemini API initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Gemini API: {e}")
            raise

    def start(self):
        if self.processing_thread and self.processing_thread.is_alive():
            logger.warning("Processing thread already running")
            return

        self.stop_event.clear()
        self.processing_thread = Thread(target=self._process_queue)
        self.processing_thread.daemon = True
        self.processing_thread.start()
        logger.info("Processing thread started")

    def stop(self):
        if self.processing_thread and self.processing_thread.is_alive():
            logger.info("Stopping processing thread...")
            self.stop_event.set()
            self.processing_thread.join(timeout=5)
            self.arduino.close()
            logger.info("Processing thread stopped")

    def _process_queue(self):
        logger.info("Processing thread is running")
        while not self.stop_event.is_set():
            try:
                img_path = self.process_queue.get(timeout=1)
                logger.info(f"Processing image from path: {img_path}")
                self._process_image(img_path)
                self.process_queue.task_done()
            except Empty:
                continue
            except Exception as e:
                logger.error(f"Error in processing thread: {e}")
                time.sleep(1)

    def _process_image(self, image_path):
        """
        Processes an image by sending it to the Gemini API and rendering a template with the response.

        :param image_path: The path to the image to be processed.
        """
        try:
            with current_app.app_context():
                current_app.logger.info(f"Processing image from path: {image_path}")

                if not os.path.exists(image_path):
                    raise FileNotFoundError(f"Image not found at path: {image_path}")

                current_app.logger.info("Sending image to Gemini API")

                # Replace with actual Gemini API call
                gemini_response = "non-biodegradable"  # Mock response

                current_app.logger.info(f"Gemini API Response: {gemini_response}")

                # Render the response to the HTML template
                rendered_html = render_template('index.html', processed_message=gemini_response)
                current_app.logger.info("Template rendered successfully")
                return rendered_html

        except Exception as e:
            current_app.logger.error(f"Error processing image {image_path}: {e}", exc_info=True)

# Global processor instance
processor = None

def get_processor():
    global processor
    if processor is None:
        processor = ImageProcessor()
        processor.start()
    return processor

# Flask Routes
@app.route('/')
def index():
    return render_template('index.html', processed_message='Waiting for image capture...')

@app.route('/upload', methods=['POST'])
def upload_image():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    try:
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        logger.info(f"File saved to {filepath}")

        # Get the processor instance and queue the image
        processor = get_processor()
        processor.process_queue.put(filepath)
        logger.info(f"Image queued for processing: {filepath}")

        return jsonify({'message': 'Image queued for processing'})
    except Exception as e:
        logger.error(f"Error handling upload: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.teardown_appcontext
def cleanup(exception=None):
    pass

if __name__ == "__main__":
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    processor = get_processor()
    app.run(debug=True, use_reloader=False)

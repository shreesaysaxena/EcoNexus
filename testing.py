from flask import Flask, render_template, request, jsonify
import os
import time
from queue import Queue, Empty
from threading import Thread, Event
from werkzeug.utils import secure_filename
import logging
import serial
from PIL import Image
import google.generativeai as genai
import re

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize the Gemini API client
genai.configure(api_key="AIzaSyB_RFI7WlcUZJLC1eVGjrjZyUH_wX74RVo")  # Replace with your actual API key
model = genai.GenerativeModel("gemini-1.5-flash")

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'static/uploads'

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
# Image Processor Class
class ImageProcessor:
    def __init__(self):
        self.process_queue = Queue()
        self.stop_event = Event()
        self.processing_thread = None
        self.arduino = ArduinoController()

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
                self._process_image(img_path)  # Now this will work
                self.process_queue.task_done()
            except Empty:
                continue
            except Exception as e:
                logger.error(f"Error in processing thread: {e}")
                time.sleep(1)

    def _process_image(self, image_path):  # Moved into the class
        """
        Processes an image by simulating a call to the Gemini API and sends commands to Arduino.
        """
        try:
            logger.info(f"Processing image from path: {image_path}")

            if not os.path.exists(image_path):
                raise FileNotFoundError(f"Image not found at path: {image_path}")

            # Open the image using PIL
            image = Image.open(image_path)

            # Call the Gemini API to determine if the image is biodegradable or non-biodegradable
            try:
                response = model.generate_content(["Reply in one word, is this biodegradable or non-biodegradable, reply only by saying B (for biodegradable) and NL (for Non-biodegradable)", image])
                gemini_response = response.text.strip().lower()
                logger.info(f"Gemini API Response: {gemini_response}")

                # Determine motor action based on response
                if "b" in gemini_response:  # Check for biodegradable (B)
                    command = 'A'  # Clockwise rotation
                elif "nl" in gemini_response:  # Check for non-biodegradable (NL)
                    command = 'B'  # Anti-clockwise rotation
                else:
                    logger.error(f"Unrecognized response from Gemini: {gemini_response}")
                    return

                # Send the command to the Arduino
                if self.arduino.send_command(command):
                    logger.info(f"Command '{command}' sent to Arduino successfully")
                else:
                    logger.error(f"Failed to send command '{command}' to Arduino")

                # Save the response to a file for the frontend to access
                response_file = os.path.join(app.config['UPLOAD_FOLDER'], "response.txt")
                with open(response_file, "w") as f:
                    f.write(gemini_response)

                logger.info(f"Response saved to {response_file}")

            except Exception as e:
                logger.error(f"Error calling Gemini API: {e}")
        except Exception as e:
            logger.error(f"Error processing image {image_path}: {e}", exc_info=True)



# Instantiate the processor
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
    """
    Renders the homepage with a placeholder message.
    """
    return render_template('index.html', processed_message='Waiting for image capture...')

@app.route('/upload', methods=['POST'])
def upload_image():
    """
    Handles the upload of an image file and queues it for processing.
    """
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

        processor = get_processor()
        processor.process_queue.put(filepath)
        logger.info(f"Image queued for processing: {filepath}")

        return jsonify({'message': 'Image queued for processing'}), 200
    except Exception as e:
        logger.error(f"Error handling upload: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/result', methods=['GET'])
def get_result():
    """
    Returns the result of the last processed image.
    """
    try:
        response_file = os.path.join(app.config['UPLOAD_FOLDER'], "response.txt")
        if os.path.exists(response_file):
            with open(response_file, "r") as f:
                response = f.read().strip()
            return jsonify({'result': response}), 200
        else:
            return jsonify({'error': 'No result available yet'}), 404
    except Exception as e:
        logger.error(f"Error fetching result: {e}")
        return jsonify({'error': 'Internal server error'}), 500

# App Cleanup
@app.teardown_appcontext
def cleanup(exception=None):
    pass

if __name__ == "__main__":
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    processor = get_processor()
    app.run(debug=True, use_reloader=False)

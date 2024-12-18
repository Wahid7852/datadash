import json
import platform
import os
import logging


def get_logger_file_path():
    if platform.system() == 'Windows':
        logger_dir = os.path.join(os.getenv('LOCALAPPDATA'), 'Temp' ,  'DataDash')
    elif platform.system() == 'Linux':
        logger_dir = os.path.join(os.path.expanduser('~'), '.cache', 'DataDash')
    elif platform.system() == 'Darwin':  # macOS
        logger_dir = os.path.join(os.path.expanduser('~/Library/Caches'), 'DataDash')
    else:
        return None
    
    # Create the directory if it doesn't exist
    os.makedirs(logger_dir, exist_ok=True)
    return logger_dir


# Create logger directory and set up the log file path
log_dir = get_logger_file_path()
if (log_dir is None):
    raise RuntimeError("Unsupported OS!")
    
log_file_path = os.path.join(log_dir, 'datadashlog.txt')

# Configure the logger
logger = logging.getLogger('FileSharing: ')
logger.setLevel(logging.DEBUG)

# Create a formatter with date and time
formatter = logging.Formatter('%(asctime)s %(levelname)s %(name)s %(message)s')

# Create a FileHandler to write logs to 'datadashlog.txt'
file_handler = logging.FileHandler(log_file_path, mode='a')
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(formatter)

# Create a StreamHandler for console output
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
console_handler.setFormatter(formatter)

# Add handlers to the logger
logger.addHandler(file_handler)
logger.addHandler(console_handler)



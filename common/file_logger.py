import os
import time
import threading


class FileLogger:
    def __init__(self, file_path: str, flush_interval: float = 1.0, buffer_size: int = 1000):
        """
        Initializes the FileLogger with buffering and flushing capabilities.

        :param file_path: Path to the log file.
        :param flush_interval: Time in seconds to flush logs to the file.
        :param buffer_size: Maximum number of log entries to buffer before forcing a flush.
        """
        self.file_path = file_path
        self.flush_interval = flush_interval
        self.buffer_size = buffer_size
        self.buffer = []
        self.lock = threading.Lock()

        # Ensure the file and its parent directories exist
        self.create_file_with_parents(self.file_path)

        # Background thread to flush buffer periodically
        self.flush_thread = threading.Thread(target=self._periodic_flush, daemon=True)
        self.flush_thread.start()

    @staticmethod
    def create_file_with_parents(file_path):
        """
        Creates the parent directories if they don't exist and ensures the file exists.
        """
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        fd = os.open(file_path, os.O_WRONLY | os.O_CREAT, mode=0o666)
        os.close(fd)

    def log(self, message: str):
        """
        Adds a log message to the buffer and checks if a flush is needed.
        """
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        formatted_message = f"[{timestamp}] {message}"

        # Lock to ensure thread-safe appending to the buffer
        with self.lock:
            self.buffer.append(formatted_message)

        # Check if we need to flush the buffer
        if len(self.buffer) >= self.buffer_size:
            self.flush()

    def flush(self):
        """
        Flushes the buffer to the file immediately.
        """
        with self.lock:
            if self.buffer:
                with open(self.file_path, 'a') as file:
                    file.write('\n'.join(self.buffer) + '\n')
                self.buffer.clear()  # Clear the buffer after flushing

    def _periodic_flush(self):
        """
        Periodically flushes the buffer to the file based on the flush_interval.
        """
        while True:
            time.sleep(self.flush_interval)
            self.flush()

    def shutdown(self):
        """
        Stops the background flush thread and ensures all logs are written.
        """
        self.flush_thread.join()
        self.flush()  # Ensure all remaining logs are flushed before shutdown


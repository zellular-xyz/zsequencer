import threading


class SharedState:
    def __init__(self):
        self._lock = threading.Lock()
        self._missed_txs = {}
        self._attempts = 0
        self._pause_node = threading.Event()


    def add_missed_txs(self, txs):
        with self._lock:
            self._missed_txs.update(txs)

    def set_missed_txs(self, txs):
        with self._lock:
            self._missed_txs = txs

    def empty_missed_txs(self):
        with self._lock:
            return self._missed_txs.clear()

    def get_missed_txs(self):
        with self._lock:
            return self._missed_txs
        
    def get_missed_txs_number(self):
        with self._lock:
            return len(self._missed_txs)

    def increase_attempt_count(self):
        with self._lock:
            self._attempts += 1

    def reset_attempts(self):
        with self._lock:
            self._attempts = 0

    def get_attempts(self):
        with self._lock:
            return self._attempts


state = SharedState()

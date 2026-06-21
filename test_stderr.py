import sys, threading, queue, time
_LOG_QUEUE = queue.Queue()
class _QueueWriter:
    def write(self, s):
        if s.strip():
            _LOG_QUEUE.put(s)
            sys.__stdout__.write(s)
            sys.__stdout__.flush()
    def flush(self):
        sys.__stdout__.flush()
sys.stderr = _QueueWriter()
def fail():
    1/0
threading.Thread(target=fail).start()
time.sleep(1)
while not _LOG_QUEUE.empty():
    print("Q:", repr(_LOG_QUEUE.get()))

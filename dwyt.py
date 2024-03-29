from os import mkdir
from threading import Thread, Condition, Event, Lock
from enum import Enum

from pytube import YouTube


class DeferredLogger:
    def __init__(self):
        self._lock = Lock()
        self._lines = []

    def log(self, line):
        with self._lock:
            self._lines.append(line)

    def output_logs(self):
        with self._lock:
            for line in self._lines:
                print(line)
            self._lines.clear()


class ThreadManager:
    def __init__(self, thread_count):
        self._thread_count = thread_count
        self._threads = [None] * thread_count

        self._scheduled_tasks = []
        self._dispatcher = Thread(target=self._dispatcher_routine)
        self._dispatcher_shutdown = Event()
        self._dispatcher_notify = Condition()
        self._dispatcher_tasks_started = 0

    def schedule_task(self, target, *args, **kwargs):
        task = Thread(target=self._wrap_target_function(target), args=args, kwargs=kwargs)
        with self._dispatcher_notify:
            self._scheduled_tasks.append(task)
            self._dispatcher_notify.notify()

    def _dispatcher_routine(self):
        def wait_predicate():
            has_task = len(self._scheduled_tasks) > 0
            has_thread = self._get_available_thread_index() is not None
            return (has_task and has_thread) or (not has_task and self._dispatcher_shutdown.is_set())

        while True:
            with self._dispatcher_notify:
                # wait for notification
                self._dispatcher_notify.wait_for(wait_predicate)

                if len(self._scheduled_tasks) > 0:
                    # Find task and thread to perform it
                    scheduled_task = self._scheduled_tasks.pop(0)
                    index = self._get_available_thread_index()

                    # Ensure thread is really done by joining it
                    if self._threads[index] is not None:
                        self._threads[index].join()

                    # prepare task data
                    task_index = self._dispatcher_tasks_started
                    self._dispatcher_tasks_started += 1
                    task_data = {"thread_index": index, "task_index": task_index}

                    # Start thread
                    self._threads[index] = scheduled_task
                    self._threads[index]._kwargs["task_data"] = task_data
                    self._threads[index].start()

                elif self._dispatcher_shutdown.is_set():
                    return

    def __enter__(self):
        self._dispatcher.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Shut down dispatcher thread
        self._dispatcher_shutdown.set()
        with self._dispatcher_notify:
            self._dispatcher_notify.notify()
        self._dispatcher.join()

        # Join all threads
        for thread in self._threads:
            if thread is not None:
                thread.join()

    def _get_available_thread_index(self):
        for index, thread in enumerate(self._threads):
            if thread is None or not thread.is_alive():
                return index
        return None

    def _wrap_target_function(self, target):
        def wrapped_target(*args, **kwargs):
            target(*args, **kwargs)
            with self._dispatcher_notify:
                self._dispatcher_notify.notify()

        return wrapped_target


def ensure_output_dir_is_present(output_dir):
    try:
        mkdir(output_dir)
    except OSError:
        pass  # directory already exists


class FileType(Enum):
    video = "video"
    audio = "audio"

    @staticmethod
    def from_string(string, default_file_type):
        for enum in FileType:
            if enum.value == string:
                return enum
        return default_file_type


def download_video(url, file_type, output_dir, logger, task_data):
    if file_type is FileType.video:
        filter_attributes = {"progressive": True, "file_extension": "mp4"}
        sort_attribute = "resolution"
    elif file_type is FileType.audio:
        filter_attributes = {"only_audio": True, "file_extension": "mp4"}
        sort_attribute = "abr"
    else:
        raise Exception("Invalid type")

    log_line = f"Downloading url={url}   task_index={task_data['task_index']}   thread_index={task_data['thread_index']}   type={file_type}"
    try:
        video = YouTube(url)
        streams = video.streams
        streams = streams.filter(**filter_attributes)
        streams = streams.order_by(sort_attribute).desc()
        selected_stream = streams.first()
        if selected_stream is None:
            raise Exception
    except Exception:
        logger.log(f"ERROR {log_line}")
    else:
        out_file = selected_stream.default_filename
        logger.log(f'      {log_line}   out_file="{out_file}"')
        selected_stream.download(output_path=output_dir, filename=out_file)


def print_help(**kwargs):
    print("DWYT - download youtube")
    print("Parameters:")
    for parameter_name, parameter_value in kwargs.items():
        print("\t{} = {}".format(parameter_name, parameter_value))
    print("Valid inputs:")
    print("\tUrl (starting with https)")
    print("\tFile name - file with urls in each line")
    print("Line can have options appended after the url. Available options:")
    print("\tvideo")
    print("\taudio")
    print()
    print("Input any number of valid input lines and confirm with <Enter>:")


def query_lines():
    while True:
        print("\t", end="")
        line = input()
        if line == "":
            return

        if line.startswith("https://"):
            # Single url
            yield line
        else:
            # File with urls
            with open(line) as file:
                for line in file.read().splitlines():
                    yield line


def parse_lines(lines, default_file_type):
    for line in lines:
        if line.startswith("#"):
            continue

        tokens = line.split()
        url = tokens[0]
        file_type = FileType.from_string(tokens[1], default_file_type) if len(tokens) > 1 else default_file_type
        yield url, file_type


def main():
    thread_count = 8
    output_dir = "yt"
    default_file_type = FileType.video

    print_help(thread_count=thread_count, output_dir=output_dir, default_file_type=default_file_type)
    ensure_output_dir_is_present(output_dir)
    logger = DeferredLogger()
    with ThreadManager(thread_count) as thread_manager:
        for url, file_extension in parse_lines(query_lines(), default_file_type):
            thread_manager.schedule_task(download_video, url, file_extension, output_dir, logger)
    print("Done")
    logger.output_logs()


if __name__ == "__main__":
    main()

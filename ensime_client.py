import os, sys, stat, time, datetime, re
import sublime_plugin, sublime
from sexp_parser import sexp
import thread
import logging
import subprocess
import functools
import socket
try:
    from cStringIO import StringIO
except ImportError:
    from StringIO import StringIO

def swank_bool(bl):
  bl.lower() == 't'

class ProcessListener(object):
    def on_data(self, proc, data):
        pass

    def on_finished(self, proc):
        pass

class AsyncProcess(object):
    def __init__(self, arg_list, listener, cwd = None):
        self.listener = listener
        self.killed = False

        # Hide the console window on Windows
        startupinfo = None
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        proc_env = os.environ.copy()

        self.proc = subprocess.Popen(arg_list, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, startupinfo=startupinfo, env=proc_env, cwd = cwd)

        if self.proc.stdout:
            thread.start_new_thread(self.read_stdout, ())

        if self.proc.stderr:
            thread.start_new_thread(self.read_stderr, ())

    def kill(self):
        if not self.killed:
            self.killed = True
            self.proc.kill()
            self.listener = None

    def poll(self):
        return self.proc.poll() == None

    def read_stdout(self):
        while True:
            data = os.read(self.proc.stdout.fileno(), 2**15)

            if data != "":
                if self.listener:
                    self.listener.on_data(self, data)
            else:
                self.proc.stdout.close()
                if self.listener:
                    self.listener.on_finished(self)
                break

    def read_stderr(self):
        while True:
            data = os.read(self.proc.stderr.fileno(), 2**15)

            if data != "":
                if self.listener:
                    self.listener.on_data(self, data)
            else:
                self.proc.stderr.close()
                break



class ScalaOnly:
    def is_enabled(self):
        return (bool(self.window and self.window.active_view().file_name() != "" and
        self._is_scala(self.window.active_view().file_name())))

    def _is_scala(self, file_name):
        _, fname = os.path.split(file_name)
        return fname.lower().endswith(".scala")
        # return True

class EnsimeOnly:
    def ensime_project_file(self):
        prj_files = [(f + "/core/.ensime") for f in self.window.folders() if os.path.exists(f + "/core/.ensime")]
        if len(prj_files) > 0:
            return prj_files[0]
        else:
            return None

    def is_enabled(self, kill = False):
        return bool(ensime_env.client) and ensime_env.client.ready and bool(self.ensime_project_file())

class EnsimeServerCommand(sublime_plugin.WindowCommand, ProcessListener, ScalaOnly, EnsimeOnly):


    def ensime_project_root(self):
        prj_dirs = [f for f in self.window.folders() if os.path.exists(f + "/core/.ensime")]
        if len(prj_dirs) > 0:
            return prj_dirs[0] + "/core"
        else:
            return None

    def is_started(self):
        return hasattr(self, 'proc') and self.proc and self.proc.poll()

    def is_enabled(self, **kwargs):
        start, kill, show_output = kwargs.get("start", False), kwargs.get("kill", False), kwargs.get("show_output", False)
        return ((kill or show_output) and self.is_started()) or (start and bool(self.ensime_project_file()))
                    
    def show_output_window(self, show_output = False):
        if show_output:
            self.window.run_command("show_panel", {"panel": "output.ensime_server"})
        

    def run(self, encoding = "utf-8", env = {}, start = False, quiet = False, kill = False, show_output = False):
        self.show_output = False

        if not hasattr(self, 'settings'):
            self.settings = sublime.load_settings("Ensime.sublime-settings")

        server_dir = self.settings.get("ensime_server_path")

        if kill:
            ensime_env.message_counter = 0
            ensime_env.client.ready = False
            if self.proc:
                self.proc.kill()
                self.proc = None
                self.append_data(None, "[Cancelled]")
            return
        else:
            if self.is_started():
                self.show_output_window(show_output)
                if not self.quiet:
                    print "Ensime server is already running!"
                return

        if not hasattr(self, 'output_view'):
            self.output_view = self.window.get_output_panel("ensime_server")

        if not hasattr(self.window, 'message_counter'):
            ensime_env.message_counter = 0

        self.quiet = quiet

        self.proc = None
        if not self.quiet:
            print "Starting Ensime Server."
        
        if show_output:
            self.show_output_window(show_output)

        # Change to the working dir, rather than spawning the process with it,
        # so that emitted working dir relative path names make sense
        if self.ensime_project_root() and self.ensime_project_root() != "":
            os.chdir(self.ensime_project_root())


        err_type = OSError
        if os.name == "nt":
            err_type = WindowsError

        try:
            self.show_output = show_output
            if start:
                ensime_env.client = EnsimeClient(self.window, self.ensime_project_root())
                self.proc = AsyncProcess(['bin/server', self.ensime_project_root() + "/.ensime_port"], self, server_dir)
        except err_type as e:
            self.append_data(None, str(e) + '\n')

    def perform_handshake(self):
        self.window.run_command("ensime_handshake")
        

    def append_data(self, proc, data):
        if proc != self.proc:
            # a second call to exec has been made before the first one
            # finished, ignore it instead of intermingling the output.
            if proc:
                proc.kill()
            return

        str = data.replace("\r\n", "\n").replace("\r", "\n")

        if not ensime_env.client.ready and re.search("Wrote port", str):
            ensime_env.client.ready = True
            self.perform_handshake()

        selection_was_at_end = (len(self.output_view.sel()) == 1
            and self.output_view.sel()[0]
                == sublime.Region(self.output_view.size()))
        self.output_view.set_read_only(False)
        edit = self.output_view.begin_edit()
        self.output_view.insert(edit, self.output_view.size(), str)
        if selection_was_at_end:
            self.output_view.show(self.output_view.size())
        self.output_view.end_edit(edit)
        self.output_view.set_read_only(True)

    def finish(self, proc):
        if proc != self.proc:
            return

        # Set the selection to the start, so that next_result will work as expected
        edit = self.output_view.begin_edit()
        self.output_view.sel().clear()
        self.output_view.sel().add(sublime.Region(0))
        self.output_view.end_edit(edit)

    def on_data(self, proc, data):
        sublime.set_timeout(functools.partial(self.append_data, proc, data), 0)

    def on_finished(self, proc):
        sublime.set_timeout(functools.partial(self.finish, proc), 0)



class EnsimeEnvironment:

    def __init__(self):
        self.settings = sublime.load_settings("Ensime.sublime-settings")

    def set_client(self, client):
        self.client = client

ensime_env = EnsimeEnvironment()

class EnsimeClient:

    def __init__(self, window, project_root):
        self.settings = ensime_env.settings
        self.project_root = project_root
        self.ready = False
        self.window = window
        self.output_view = self.window.get_output_panel("ensime_messages")
        ensime_env.set_client(self)


    def _port(self):
        return int(open(self.project_root + "/.ensime_port").read())

    def _last_message(self):
        return self._current_message()

    def _current_message(self):
        if self.window:
            return ensime_env.message_counter
        else:
            return 0

    def _next_message(self):
        return self._current_message() + 1

    def _update_message_count(self):
        if self.window:
            ensime_env.message_counter = self._next_message()
        
    def _with_length_header(self, data): 
        return "%06x" % len(data) + data

    def _make_message(self, data):
        return str(self._with_length_header(
          "(:swank-rpc " + str(data) + " " + str(self._next_message()) + ")"))

    def project_file(self): 
        if self.ready:
            return self.project_root + "/.ensime"
        else:
            return ""

    def project_config(self):
        return open(self.project_file()).read()

    def connect(self):
        try:
            s = socket.socket()
            s.connect(("127.0.0.1", self._port()))
            self.client = s
            return s
        except socket.error as e:
            # set sublime error status
            self.ready = False
            sublime.error_message("Can't connect to ensime server:  " + e.args[1])

    def send(self, msg):
        self.feedback(msg)
        self.client.send(self._make_message(msg))
        self._update_message_count()


    def feedback(self, msg):
        # self.window.run_command("ensime_update_messages_view", { 'msg': msg })
        print msg


    def close(self):
        if self.client:
            self.client.close()

    def get_response(self, mnr):
        resp = self.client.recv(8192)[6:]
        try:
            mm = sexp.parseString(resp)[0]
            while mnr != mm[-1]:
                resp = self.client.recv(8192)[6:]
                mm = sexp.parseString(resp)[0]
            return mm
        except BaseException as e:
            sublime.error_message("There was an exception: " + e)
            return None

    def req(self, to_send): 
        if self.ready and (not hasattr(self, "client") or not self.client):
            self.connect()
        self.send(to_send)
        resp = self.get_response(self._last_message())
        if resp != None:
            self.feedback(resp)
        return resp

    def handshake(self): 
        return self.req("(swank:connection-info)")

    def initialize_project(self):
        return self.req("(swank:init-project " + self.project_config() + " )")

    def format_source(self, file_path):
        return self.req('(swank:format-source ("'+file_path+'"))')
        
class EnsimeUpdateMessagesView(sublime_plugin.WindowCommand, EnsimeOnly):
    def run(self, msg):
        if msg != None:
            ov = ensime_env.client.output_view
            msg = msg.replace("\r\n", "\n").replace("\r", "\n")

            selection_was_at_end = (len(ov.sel()) == 1
                and ov.sel()[0]
                    == sublime.Region(ov.size()))
            ov.set_read_only(False)
            edit = ov.begin_edit()
            ov.insert(edit, ov.size(), msg + "\n")
            if selection_was_at_end:
                ov.show(ov.size())
            ov.end_edit(edit)
            ov.set_read_only(True)

class CreateEnsimeClientCommand(sublime_plugin.WindowCommand, EnsimeOnly):

    def run(self):
        ensime_env.message_counter = 0
        cl = EnsimeClient(self.window, u"/Users/ivan/projects/mojolly/backchat-library/core")
        cl.ready = True
        self.window.run_command("ensime_handshake")

class EnsimeShowMessageViewCommand(sublime_plugin.WindowCommand, EnsimeOnly):

    def run(self):
        self.window.run_command("show_panel", {"panel": "output.ensime_messages"})

class EnsimeHandshakeCommand(sublime_plugin.WindowCommand, EnsimeOnly):

    def run(self):
        if (ensime_env.client.ready):
            server_info = ensime_env.client.handshake()
            if server_info[1][0] == ":ok" and server_info[2] == 1:
                msg = "Initializing " + server_info[1][1][3][1] + " v." + server_info[1][1][9]
                sublime.status_message(msg)
                init_info = ensime_env.client.initialize_project()
                sublime.status_message("Ensime ready!")
            else:
                sublime.error_message("There was problem initializing ensime, msgno: " + str(server_info[2]) + ".")

def save_view(view):
    if view == None or view.file_name == None:
      return
    content = view.substr(sublime.Region(0, view.size()))
    with open(view.file_name(), 'wb') as f:
      f.write(content.encode("UTF-8"))
                
class EnsimeReformatSourceCommand(sublime_plugin.WindowCommand, EnsimeOnly):

    def run(self):
        vw = self.window.active_view()
        print("reformatting: " + vw.file_name())
        save_view(vw)
        fmt_result = ensime_env.client.format_source(vw.file_name())
        print fmt_result
        sublime.status_message("Formatting done!")









            
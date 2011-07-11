import os, sys, stat, random, getpass
import ensime_environment
from ensime_server import EnsimeOnly
import functools, socket, threading
import sublime_plugin, sublime


def save_view(view):
  if view == None or view.file_name == None:
    return
  content = view.substr(sublime.Region(0, view.size()))
  with open(view.file_name(), 'wb') as f:
    f.write(content.encode("UTF-8"))
                
class EnsimeReformatSourceCommand(sublime_plugin.TextCommand, EnsimeOnly):

  def handle_reply(self, data):
    self.view.run_command('revert')
    self.view.set_status("ensime", "Formatting done!")
    ensime_environment.ensime_env.client().remove_handler(data[-1])

  def run(self, edit):
    #ensure_ensime_environment.ensime_env()
    vw = self.view
    if vw.is_dirty():
      vw.run_command("save")
    fmt_result = ensime_environment.ensime_env.client().format_source(vw.file_name(), self.handle_reply)

class RandomWordsOfEncouragementCommand(sublime_plugin.WindowCommand, EnsimeOnly):

  def run(self):
    if not hasattr(self, "phrases"):
      self.phrases = [
        "Let the hacking commence!",
        "Hacks and glory await!",
        "Hack and be merry!",
        "May the source be with you!",
        "Death to null!",
        "Find closure!",
        "May the _ be with you.",
        "CanBuildFrom[List[Dream], Reality, List[Reality]]"
      ]  
    msgidx = random.randint(0, len(self.phrases) - 1)
    msg = self.phrases[msgidx]
    sublime.status_message(msg + " This could be the start of a beautiful program, " + 
      getpass.getuser().capitalize()  + ".")

class EnsimeTypeCheckAllCommand(sublime_plugin.WindowCommand, EnsimeOnly):

  def handle_reply(self, data):
    
    ensime_environment.ensime_env.client().remove_handler(data[-1])

  def run(self):
    ensime_environment.ensime_env.client().type_check_all(self.handle_reply)

class EnsimeTypeCheckFileCommand(sublime_plugin.WindowCommand, EnsimeOnly):

  def run(self):
    pass

class EnsimeOrganizeImportsCommand(sublime_plugin.TextCommand, EnsimeOnly):

  def handle_reply(self, edit, data):
    if data[1][1][5] == "success":
      ov = self.view.window().new_file()

      ov.set_syntax_file(self.view.settings().get('syntax'))
      ov.set_scratch(True)

      prelude = "/*\n   Confirm that you want to make this change.\n   Hitting enter with a string of yes is to confirm any other string or esc cancels.\n*/\n\n\n"
      start = data[1][1][7][0][5]
      end = data[1][1][7][0][7]
      new_cntnt = data[1][1][7][0][3]

      prev = self.view.substr(sublime.Region(0, start))

      on_done = functools.partial(self.on_done, data[1][1][1], data[-1], ov)
      on_cancel = functools.partial(self.on_cancel, data[-1], ov)

      new_cntnt = new_cntnt.replace('\r\n', '\n').replace('\r', '\n')
      cl = ensime_environment.ensime_env.client()
      cl.window.show_input_panel("Confirm change: ", "yes", on_done, None, on_cancel)
      ov.set_read_only(False)
      edt = ov.begin_edit()
      ov.insert(edt, 0, prelude + prev + new_cntnt)
      ov.end_edit(edt)
      ov.set_read_only(True)

  def on_done(self, procedure_id, msg_id, output, answer):
    if answer.lower() == "yes":
      print "performing refactor"
      self.view.run_command("ensime_accept_imports", { "procedure_id": procedure_id, "msg_id": msg_id })
      self.close_output_view(output)
    else:
      self.on_cancel(msg_id, output)

  def on_cancel(self, msg_id, output):
    ensime_environment.ensime_env.client().remove_handler(msg_id)
    self.close_output_view(output)

  def close_output_view(self, output):
    # ov = self.views[output]
    ov = output
    ensime_environment.ensime_env.client().window.focus_view(ov)
    ensime_environment.ensime_env.client().window.run_command("close")

  def run(self, edit):
    #ensure_ensime_environment.ensime_env()
    fname = self.view.file_name()
    if fname:
      ensime_environment.ensime_env.client().organize_imports(fname, lambda data: self.handle_reply(edit, data))

class EnsimeAcceptImportsCommand(sublime_plugin.TextCommand, EnsimeOnly): 

  def handle_reply(self, edit, data):
    print "Got data for executed imports command"
    print data
    self.view.run_command("revert")
    ensime_environment.ensime_env.client().remove_handler(data[-1])

  def run(self, edit, procedure_id, msg_id):
    ensime_environment.ensime_env.client().perform_organize(
      procedure_id, msg_id, lambda data: self.handle_reply(edit, data))

from binaryninja import *
from binja_toolbar import add_image_button
from multiprocessing.connection import Client
import os
import subprocess
import threading
import time
import win32com.client
import win32con
import win32gui
import win32process

pykd_path = "C:\\path\\to\\pykd.dll"
dbg_dir = "C:\\Program Files (x86)\\Windows Kits\\10\\Debuggers"
poll_time = .25
no_color = HighlightStandardColor.NoHighlightColor
ip_color = HighlightStandardColor.YellowHighlightColor
enabled_bp_color = HighlightStandardColor.RedHighlightColor
hit_bp_color = HighlightStandardColor.OrangeHighlightColor
cond_jump_color = HighlightStandardColor.GreenHighlightColor


class BinDbgSession:
    def __init__(self, bv):
        self.bv = bv
        self.conn = None
        self.windbg_proc = None
        self.regs = None
        self.ip = None
        self.bps = set()
        
        if not 'proc_args' in self.bv.session_data:
            self.bv.session_data['proc_args'] = ''

        if not 'pipe' in self.bv.session_data:
            self.bv.session_data['pipe'] = get_text_line_input(
                "Enter BinDbg pipe name:",
                "Start BinDbg session",
            )

        t = threading.Thread(target=self.event_loop)
        t.setDaemon(True)
        t.start()


    def stop(self, reason):
        if 'bindbg' in self.bv.session_data:
            if self.bv.session_data['bindbg'].windbg_proc:
                # close windbg
                pid = self.bv.session_data['bindbg'].windbg_proc.pid
                for hwnd in get_hwnds_for_pid(pid):
                    win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
            del self.bv.session_data['bindbg']

        if self.conn:
            self.conn.close()

        for bp in self.bps.copy():
            self.delete_bp(bp)

        if self.ip:
            self.highlight(self.ip, no_color)
            self.ip = None

        print(reason)
        
        
    def send(self, command, **params):
        try:
            self.conn.send((command, params))
        except IOError:
            return self.stop("Lost connection to WinDbg")


    def connect(self):
        try:
            self.conn = Client('\\\\.\\pipe\\' + self.bv.session_data['pipe'])
            return True
        except WindowsError:
            return False
    
    
    def start_windbg(self):
        bindbg_dir = os.path.dirname(os.path.abspath(__file__))
        windbg_ext = os.path.join(bindbg_dir, 'windbg.py')
        exe_path = self.bv.file.filename.replace('.bndb', '.exe')
        exe_dir = os.path.dirname(exe_path)
        
        # determine whether we should run x86 or x64 windbg
        if self.bv.arch.name == 'x86':
            windbg_path = os.path.join(dbg_dir, 'x86', 'windbg.exe')
        else:
            windbg_path = os.path.join(dbg_dir, 'x64', 'windbg.exe')
        
        # save command as a script due to nested double quotes
        windbg_cmd = '.load "{}"; !py -2 --global "{}" "{}"'.format(
            pykd_path.replace('\\', '\\\\'),
            windbg_ext.replace('\\', '\\\\'),
            self.bv.session_data['pipe']
        )
        script_path = os.path.join(bindbg_dir, 'cmd.txt')
        with open(script_path, "w") as script:
            script.write(windbg_cmd)

        # open WinDbg without blocking
        self.windbg_proc = subprocess.Popen(
            [windbg_path,
            '-W', exe_path, # create a named workspace for this exe
            '-QY',  # automatically save workspace to preserve BPs & layout
            '-c', '$$<' + script_path,  # run windbg_cmd
            exe_path,
            self.bv.session_data['proc_args']],
            cwd=exe_dir,
        )


    def event_loop(self):
        # attempt to connect to already open windbg session
        if not self.connect():
            # if that fails, start windbg and attempt to connect again
            self.start_windbg()
            while not self.connect():
                # wait while windbg loads
                time.sleep(2)
        print("Connected to WinDbg")
        self.send('sync')

        while True:
            try:
                if self.conn.poll(poll_time):
                    self.process(self.conn.recv())
            except IOError as e:
                if e.errno == 6:   # stop() has already been called
                    return
                return self.stop("Lost connection to WinDbg")


    def process(self, data):
        print(data)
        cmd, params = data

        if 'bp' in cmd:
            addr = params['addr'] + self.bv.start
            if self.bv.is_valid_offset(addr):
                if cmd == 'set_bp':
                    self.set_bp(addr)
                elif cmd == 'delete_bp':
                    self.delete_bp(addr)
                elif cmd == 'bp_hit':
                    self.bp_hit(addr, params['regs'])
        elif cmd == 'set_ip':
            ip = params['ip'] + self.bv.start
            if self.bv.is_valid_offset(ip):
                self.set_ip(ip, params['regs'])
        elif cmd == 'vtable':
            ip = params['ip'] + self.bv.start
            target = params['target'] + self.bv.start
            object = params['object'] + self.bv.start if 'object' in params else None
            instr = params['instr']
            self.vtable(ip, target, object, instr)


    def highlight(self, addr, color):
        func = self.bv.get_functions_containing(addr)[0]
        func.set_auto_instr_highlight(addr, color)


    def set_ip(self, addr, regs=None, came_from_binja=False):
        if came_from_binja:
            self.send('set_ip', ip=addr-self.bv.start)

        if self.ip:
            self.highlight(self.ip, no_color)
        self.highlight(addr, ip_color)
        self.ip = addr
        self.bv.navigate(self.bv.view, addr)    # "go to address" equivalent
        
        # highlight the target of a branch instruction
        func = self.bv.get_functions_containing(addr)[0]
        il_instr = func.get_lifted_il_at(addr)
        if il_instr.operation != LowLevelILOperation.LLIL_IF or not regs:
            return
        instr, jump = self.bv.get_disassembly(addr).split()
        if ((instr in ('jo') and regs['of'] == 1) or
            (instr in ('jno') and regs['of'] == 0) or
            (instr in ('js') and regs['sf'] == 1) or
            (instr in ('jns') and regs['sf'] == 0) or
            (instr in ('je','jz') and regs['zf'] == 1) or
            (instr in ('jne') and regs['zf'] == 0) or
            (instr in ('jb','jnae','jc') and regs['cf'] == 1) or
            (instr in ('jnb','jae','jnc') and regs['cf'] == 0) or
            (instr in ('jbe','jna') and (regs['cf'] == 1 or regs['zf'] == 1)) or
            (instr in ('ja','jnbe') and regs['cf'] == 0 and regs['zf'] == 0) or
            (instr in ('jl','jnge') and regs['sf'] != regs['of']) or
            (instr in ('jge','jnl') and regs['sf'] == regs['of']) or
            (instr in ('jle','jng') and (regs['zf'] == 1 or regs['sf'] != regs['of'])) or
            (instr in ('jg','jnle') and regs['zf'] == 0 and regs['sf'] == 0) or
            (instr in ('jp','jpe') and regs['pf'] == 1) or
            (instr in ('jnp','jpo') and regs['pf'] == 1) or
            (instr in ('jcxz','jecxz') and regs['cx'] == 0)):
            target = int(jump, 16)
        else:
            target = addr + self.bv.get_instruction_length(addr)
        self.highlight(target, cond_jump_color)


    def set_bp(self, addr, came_from_binja=False):
        if came_from_binja:
            self.send('set_bp', addr=addr-self.bv.start)

        self.bps.add(addr)
        self.highlight(addr, enabled_bp_color)
        

    def delete_bp(self, addr, came_from_binja=False):
        if addr not in self.bps:
            return

        if came_from_binja:
            self.send('delete_bp', addr=addr-self.bv.start)

        self.bps.remove(addr)
        self.highlight(addr, no_color)
    
    
    def bp_hit(self, addr, regs=None):
        self.set_ip(addr, regs=regs)
        self.highlight(addr, hit_bp_color)
    
    
    def vtable(self, ip, target, object, instr):
        target_sym = self.bv.get_symbol_at(target)
        target_sym = target_sym.full_name if target_sym else str(target)
        if object:
            object_sym = self.bv.get_symbol_at(object)
            object_sym = object_sym.full_name.split("::")[0] if object_sym else str(object)
            comment = '{} (from {} object)'.format(target_sym, object_sym)
            if instr == 'lea':
                comment = '(ptr)' + comment
        else:
            comment = target_sym
        self.bv.get_functions_containing(ip)[0].set_comment_at(ip, comment)
        

def get_hwnds_for_pid(pid):
    def callback(hwnd, hwnds):
        if win32gui.IsWindowVisible(hwnd) and win32gui.IsWindowEnabled(hwnd):
            _, found_pid = win32process.GetWindowThreadProcessId(hwnd)
            if found_pid == pid:
                hwnds.append (hwnd)
        return True

    hwnds = []
    win32gui.EnumWindows (callback, hwnds)
    return hwnds


def start(bv):
    if 'bindbg' not in bv.session_data:
        bv.session_data['bindbg'] = BinDbgSession(bv)
    else:
        print("This BinaryView is already being debugged")


def stop(bv):
    try:
        bv.session_data['bindbg'].stop("BinDbg session closed by user")
    except KeyError:
        print("This BinaryView is not being debugged")


def set_bp(bv, addr):
    try:
        bv.session_data['bindbg'].set_bp(addr, came_from_binja=True)
    except KeyError:
        print("This BinaryView is not being debugged")


def delete_bp(bv, addr):
    try:
        bv.session_data['bindbg'].delete_bp(addr, came_from_binja=True)
    except KeyError:
        print("This BinaryView is not being debugged")


def set_ip(bv, addr):
    try:
        bv.session_data['bindbg'].set_ip(addr, came_from_binja=True)
    except KeyError:
        print("This BinaryView is not being debugged")


def run_to(bv, addr):
    try:
        bv.session_data['bindbg'].send('run_to', addr=addr-bv.start)
    except KeyError:
        print("This BinaryView is not being debugged")


def go(bv):
    try:
        bv.session_data['bindbg'].send('go')
    except KeyError:
        start(bv)
        

def break_(bv):
    try:
        shell = win32com.client.Dispatch('WScript.Shell')
        # focus on windbg (avoid AppActivate as it leaves windbg in foreground)
        hwnd = get_hwnds_for_pid(bv.session_data['bindbg'].windbg_proc.pid)[0]
        win32gui.SetForegroundWindow(hwnd)
        # send break sequence to transfer control back to debugger
        shell.SendKeys('^{BREAK}')
        # re-focus on Binja
        time.sleep(.3)
        win32gui.SetForegroundWindow(get_hwnds_for_pid(os.getpid())[0])
    except KeyError:
        print("This BinaryView is not being debugged")
        

def step_out(bv):
    try:
        bv.session_data['bindbg'].send('step_out')
    except KeyError:
        print("This BinaryView is not being debugged")
        
        
def step_in(bv):
    try:
        bv.session_data['bindbg'].send('step_in')
    except KeyError:
        print("This BinaryView is not being debugged")
        

def step_over(bv):
    try:
        bv.session_data['bindbg'].send('step_over')
    except KeyError:
        print("This BinaryView is not being debugged")


def set_args(bv):
    bv.session_data['proc_args'] = get_text_line_input(
        "Enter process arguments:",
        "Set process arguments"
    )


def sync(bv):
    try:
        bv.session_data['bindbg'].send('sync')
    except KeyError:
        print("This BinaryView is not being debugged")


PluginCommand.register_for_address("Set breakpoint", "", set_bp)
PluginCommand.register_for_address("Delete breakpoint", "", delete_bp)
PluginCommand.register_for_address("Set instruction ptr", "", set_ip)
PluginCommand.register_for_address("Run to cursor", "", run_to)
PluginCommand.register("Start BinDbg session", "", start)
PluginCommand.register("Stop BinDbg session", "", stop)
PluginCommand.register("Set process arguments", "", set_args)
PluginCommand.register("Sync with debugger", "", sync)

icons_path = os.path.dirname(os.path.abspath(__file__)) + '\\icons'
add_image_button(icons_path + '\\firefox-play.png', (32,32), go, tooltip="Go")
add_image_button(icons_path + '\\firefox-close.png', (32,32), stop, tooltip="Stop")
add_image_button(icons_path + '\\firefox-pause.png', (32,32), break_, tooltip="Break")
add_image_button(icons_path + '\\firefox-step-out.png', (32,32), step_out, tooltip="Step Out")
add_image_button(icons_path + '\\firefox-step-in.png', (32,32), step_in, tooltip="Step In")
add_image_button(icons_path + '\\firefox-step-over.png', (32,32), step_over, tooltip="Step Over")
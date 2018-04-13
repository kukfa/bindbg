from multiprocessing.connection import Listener
from pykd import *
import os
import re
import string
import sys
import threading
import time

poll_time = .25
conn = None
base = module.begin(getModulesList()[0])
bps = { }
ip = None


def start(pipe):
    global conn
    listener = Listener('\\\\.\\pipe\\' + pipe, backlog=0)

    while True:
        conn = listener.accept()
        print("Connected to Binary Ninja")
        event_loop(conn)


def stop(conn, reason):
    conn.close()
    print(reason)


def send(command, **params):
    global conn
    
    try:
        conn.send((command, params))
    except IOError:
        return stop(conn, "Lost connection to Binary Ninja")


def event_loop(conn):
    global bps
    global ip

    while True:
        try:
            if conn.poll(poll_time):
                if (getExecutionStatus() == executionStatus.Go):
                    breakin()   # COM returns before execution is stopped(?)
                    time.sleep(.1)  # quick sleep fixes it
                    continue_executing = process(conn.recv())
                    if continue_executing:
                        go()
                else:
                    process(conn.recv())
            
            if (getExecutionStatus() == executionStatus.Go):
                continue
            
            # check if IP has changed
            current_ip = getIP()
            if (current_ip != ip):
                update_ip(current_ip)
                update_vtable(current_ip)

            # check for breakpoints added or removed through windbg
            if getNumberBreakpoints() != len(bps):
                update_bps()
        except IOError:
            return stop(conn, "Lost connection to Binary Ninja")
        except DbgException as e:
            print(e)
            send('print', message=str(e) + '. Try again - pykd is finicky')


def process(data):
    print(data)
    global bps
    cmd, params = data

    if 'bp' in cmd:
        addr = params['addr'] + base
        if cmd == 'set_bp' and addr not in bps:
            # set unresolved BP (b/c ASLR)
            dbgCommand('bu ' + findSymbol(addr, True))
            # retrieve and save the BP we just created
            bp = get_bp(addr)
            bps[addr] = bp
        elif cmd == 'delete_bp' and addr in bps:
            breakpoint.remove(bps[addr])
            del bps[addr]
    elif cmd == 'set_ip':
        setIP(params['ip'] + base)
    elif cmd == 'sync':
        send('set_ip', ip=getIP()-base, regs=get_regs())
        for bp in bps:
            send('set_bp', addr=bp-base)
    elif cmd == 'go':
        go()
    elif cmd == 'break':
        breakin()
        return False    # pause execution
    elif cmd == 'step_out':
        dbgCommand('pt; p') # stepout() is weird
    elif cmd == 'step_in':
        trace()
    elif cmd == 'step_over':
        step()
    elif cmd == 'run_to':
        addr = params['addr'] + base
        # because 'pa' throws exception and won't run for some reason
        dbgCommand('bu ' + findSymbol(addr, True))
        go()
        breakpoint.remove(get_bp(addr))
    return True         # continue executing


def update_ip(current_ip):
    global bps
    global ip
    ip = current_ip
    if current_ip not in bps:
        send('set_ip', ip=current_ip-base, regs=get_regs())
    else:
        send('bp_hit', addr=current_ip-base, regs=get_regs())


def update_vtable(current_ip):
    # matches symbols, e.g. {Symbol!ExampleSymbol (73b43420)}
    symbol_regex = r"\{([^()]*|\([^()]*\))*\}"
    # matches dereferences, e.g. [eax+30h]
    deref_regex = r"\[[^\[]*\]"
    # matches arithmetic in dereferences
    arith_regex = r"([+-/*])"

    asm = disasm.instruction(disasm(current_ip))
    instr = asm.split()[2]
    ptr_target = None
    find_object_type = False
    ptr_object = None
    object = None

    if instr == 'call' and re.search(symbol_regex, asm):
        # target addr is between parentheses in WinDbg disasm
        addr = asm[asm.find("(")+1:asm.find(")")]
        if asm.find(addr+"={") != -1:
            return  # addr is an import
        target = long(addr, 16)
    elif instr == 'mov' and 'ptr' in asm.split(',')[1]:
        find_object_type = True
        if re.search(symbol_regex, asm):
            # target has already been dereferenced by WinDbg
            target = long(asm[asm.find("(")+1:asm.find(")")], 16)
        else:
            ptr_target = long(asm.split("=")[1], 16)
    elif instr == 'lea' and re.search(deref_regex, asm):
        find_object_type = True
        # target (e.g. esi+30h) is between brackets in WinDbg disasm
        reg_and_arith = asm[asm.find("[")+1:asm.find("]")]
        # although lea doesn't actually deref memory, do it anyway
        # to get a symbol, then can mark it as a pointer in binja
        ptr_target = expr(reg_and_arith, False)
    else:
        # this is not a valid vtable reference
        return

    # attempt to determine type of the object where the vtable's coming from
    # warning: this is not always accurate (e.g. may determine it's an object
    # of type Parent when it's really of type Child)
    if find_object_type:
        reg_and_arith = asm[asm.find("[")+1:asm.find("]")]
        if '!' in reg_and_arith:    # symbol
            if '+' in reg_and_arith:    # symbol with offset
                # remove the offset and evaluate to get object address
                symbol = reg_and_arith.split('+')[0]
                ptr_object = expr(symbol, False)
            else:
                # no offset, so just extract the address provided by WinDbg
                addr = reg_and_arith[reg_and_arith.find("(")+1:reg_and_arith.find(")")]
                ptr_object = long(addr, 16)
        elif re.search(arith_regex, reg_and_arith):
            reg_name = re.split(arith_regex, reg_and_arith)[0]
            ptr_object = reg(reg_name)
        elif all(char in string.hexdigits for char in reg_and_arith):
            ptr_object = long(reg_and_arith.strip('h'), 16)
        elif reg_and_arith.isalpha():
            reg_name = reg_and_arith
            ptr_object = reg(reg_name)

    if ptr_target is not None:
        if not isValid(ptr_target):
            return
        target = ptrPtr(ptr_target)
    if ptr_object is not None and isValid(ptr_object):
        object = ptrPtr(ptr_object)

    if isValid(target):
        if find_object_type and object is not None:
            send('vtable', instr=instr, target=target-base, object=object-base, ip=current_ip-base)
        else:
            send('vtable', instr=instr, target=target-base, ip=current_ip-base)
        

def update_bps():
    global bps
    current_bps = []
    for index in range(0, getNumberBreakpoints()):
        bp = getBp(index)
        addr = breakpoint.getOffset(bp)
        current_bps.append(addr)
        # check for BPs added in WinDbg
        if addr not in bps:
            bps[addr] = bp
            send('set_bp', addr=addr-base)
    # check for BPs removed in WinDbg
    for addr in bps.copy():
        if addr not in current_bps:
            del bps[addr]
            send('delete_bp', addr=addr-base)


def get_bp(addr):
    for index in range(0, getNumberBreakpoints()):
        bp = getBp(index)
        if breakpoint.getOffset(bp) == addr:
            return bp


def get_regs():
    regs = { }
    # TODO limited set of registers due to pykd errors
    reg_names = [getRegisterName(i) for i in range(0, getNumberRegisters())
        if not any(char.isdigit() for char in getRegisterName(i))]
    for name in reg_names:
        regs[name] = reg(name)
    return regs


pipe = sys.argv[1]
t = threading.Thread(target=start, args=[pipe])
t.setDaemon(True)
t.start()
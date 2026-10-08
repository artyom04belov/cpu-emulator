"""Graphical emulator. Run with: python3 main.py  (only the standard library is needed)."""
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, font as tkfont

from assembler import AsmError, assemble
from cpu import CPU, CPUError
from isa import (MEM_SIZE, REG_COUNT, INSTR_CELLS, REG, IMM, DIR, HALT, MOVE, ALU, COMPARE, JUMP,
                 DecodeError, decode, disassemble, fields)

BASE = Path(__file__).resolve().parent
EXAMPLES = [('Maximum', 'maximum'), ('Convolution', 'convolution')]
STEP_LIMIT = 20_000

BG, PANEL, INK, MUTED, LINE = '#f5f5f4', '#ffffff', '#1c1917', '#78716c', '#e7e5e4'
NEXT, CHANGED, ERROR = '#dbeafe', '#fde68a', '#fecaca'
SHORT_MODES = ('register', 'immediate', 'direct', 'indirect')


def describe_fields(word):
    """(title, bits, meaning) for every field of the instruction in IR."""
    f = fields(word)
    try:
        ins = decode(word)
    except DecodeError:
        ins = None
    kind = ins.kind if ins else None
    a3_mode = f['dmode'] if f['dmode'] != REG else f['smode']
    if kind in (None, HALT):
        a1 = a2 = a3 = 'unused'
    else:
        a1 = f"R{f['a1']}" if kind in (MOVE, ALU) else 'unused'
        a2 = f"R{f['a2']}" if kind in (ALU, COMPARE) else 'unused'
        if kind == JUMP:
            a3 = f"addr 0x{f['a3']:03X}"
        elif a3_mode == IMM:
            a3 = f"number {f['a3']}"
        elif a3_mode == DIR:
            a3 = f"addr 0x{f['a3']:03X}"
        else:
            a3 = f"R{f['a3']}"
    return [
        ('Opcode', f"{f['opcode']:08b}", ins.name if ins else 'unknown'),
        ('Dest. mode', f"{f['dmode']:02b}", SHORT_MODES[f['dmode']]),
        ('Src. mode', f"{f['smode']:02b}", SHORT_MODES[f['smode']]),
        ('A1', f"{f['a1']:04b}", a1),
        ('A2', f"{f['a2']:04b}", a2),
        ('A3', f"{f['a3']:012b}", a3),
    ]


class App:
    def __init__(self, root):
        self.root = root
        root.title('CPU Emulator - variant 11: three-address, von Neumann')
        root.geometry('1360x800')
        root.minsize(1180, 660)
        root.configure(bg=BG)
        self.cpu = CPU()
        self.program = None
        self.built_text = None
        self.timer = None
        self.marked = set()                    # memory rows that carry a highlight

        families = set(tkfont.families())
        mono = next((f for f in ('JetBrains Mono', 'JetBrainsMono Nerd Font', 'Menlo', 'Consolas',
                                 'DejaVu Sans Mono') if f in families), 'Courier')
        self.mono = (mono, 10)
        self.mono_big = (mono, 13, 'bold')
        self.ui = tkfont.nametofont('TkDefaultFont').actual('family')

        style = ttk.Style()
        style.theme_use('clam')
        style.configure('.', background=BG, foreground=INK)
        style.configure('TButton', padding=(10, 4))
        style.configure('Treeview', font=self.mono, rowheight=20, background=PANEL,
                        fieldbackground=PANEL, borderwidth=0)
        style.configure('Treeview.Heading', background=BG, foreground=MUTED, relief='flat')

        self.build_toolbar()
        self.build_log()
        body = ttk.Frame(root)
        body.pack(fill='both', expand=True, padx=12)
        body.columnconfigure(0, weight=25, uniform='col')
        body.columnconfigure(1, weight=42, uniform='col')
        body.columnconfigure(2, weight=33, uniform='col')
        body.rowconfigure(0, weight=1)
        self.build_editor(body)
        self.build_cpu(body)
        self.build_memory(body)
        self.load_example('maximum')

    # --- layout ---------------------------------------------------------------------------

    def heading(self, parent, text):
        return tk.Label(parent, text=text.upper(), bg=parent['bg'], fg=MUTED, anchor='w',
                        font=(self.ui, 8, 'bold'))

    def build_toolbar(self):
        bar = ttk.Frame(self.root, padding=(12, 10))
        bar.pack(fill='x')
        ttk.Label(bar, text='Examples:').pack(side='left')
        for title, name in EXAMPLES:
            ttk.Button(bar, text=title, command=lambda n=name: self.load_example(n)).pack(side='left', padx=2)
        for title, command in (('Open...', self.open_file), ('Save...', self.save_file)):
            ttk.Button(bar, text=title, command=command).pack(side='left', padx=2)
        ttk.Separator(bar, orient='vertical').pack(side='left', fill='y', padx=10)
        for title, command in (('Assemble', self.build), ('Step', self.step), ('Run', self.run),
                               ('Pause', self.pause), ('Reset', self.reset)):
            ttk.Button(bar, text=title, command=command).pack(side='left', padx=2)
        ttk.Label(bar, text='Run delay, ms:').pack(side='left', padx=(14, 4))
        self.delay = tk.IntVar(value=150)
        ttk.Spinbox(bar, from_=0, to=2000, increment=50, textvariable=self.delay, width=5).pack(side='left')

    def build_editor(self, body):
        frame = tk.Frame(body, bg=BG)
        frame.grid(row=0, column=0, sticky='nsew', padx=(0, 10))
        self.heading(frame, 'Assembly program').pack(fill='x', pady=(0, 4))
        self.editor = tk.Text(frame, font=self.mono, wrap='none', undo=True, bg=PANEL, fg=INK,
                              relief='flat', highlightthickness=1, highlightbackground=LINE,
                              padx=8, pady=6, width=10)
        self.editor.pack(fill='both', expand=True)
        self.editor.tag_configure('next', background=NEXT)
        self.editor.tag_configure('error', background=ERROR)

    def build_cpu(self, body):
        frame = tk.Frame(body, bg=BG)
        frame.grid(row=0, column=1, sticky='nsew', padx=(0, 10))

        def panel(title, parent=frame, **pack):
            holder = tk.Frame(parent, bg=BG)
            holder.pack(**(pack or dict(fill='x')))
            self.heading(holder, title).pack(fill='x', pady=(0, 4))
            box = tk.Frame(holder, bg=PANEL, highlightthickness=1, highlightbackground=LINE, padx=10, pady=6)
            box.pack(fill='both', expand=True, pady=(0, 8))
            return box

        def value(parent, big=False):
            return tk.Label(parent, bg=PANEL, fg=INK, font=self.mono_big if big else self.mono, anchor='w', pady=0)

        def caption(parent, text):
            return tk.Label(parent, text=text, bg=PANEL, fg=MUTED, anchor='w')

        top = tk.Frame(frame, bg=BG)
        top.pack(fill='x')
        box = panel('Program counter (PC)', top, side='left', fill='both', expand=True, padx=(0, 10))
        caption(box, 'Address of the next instruction').pack(anchor='w')
        self.pc_label = value(box, big=True)
        self.pc_label.pack(anchor='w')

        box = panel('Flags', top, side='left', fill='both', expand=True)
        self.flag_labels = {}
        for col, (key, title) in enumerate((('z', 'Z  zero'), ('c', 'C  carry'), ('s', 'S  sign'))):
            caption(box, title).grid(row=0, column=col, sticky='w', padx=(0, 22))
            self.flag_labels[key] = value(box, big=True)
            self.flag_labels[key].grid(row=1, column=col, sticky='w')

        box = panel('Instruction register (IR) - the last fetched instruction')
        top = tk.Frame(box, bg=PANEL)
        top.pack(fill='x')
        caption(top, 'Machine code').grid(row=0, column=0, sticky='w', padx=(0, 30))
        caption(top, 'Assembly').grid(row=0, column=1, sticky='w')
        self.ir_code = value(top, big=True)
        self.ir_code.grid(row=1, column=0, sticky='w', padx=(0, 30))
        self.ir_asm = value(top, big=True)
        self.ir_asm.grid(row=1, column=1, sticky='w')
        grid = tk.Frame(box, bg=PANEL)
        grid.pack(fill='x', pady=(6, 0))
        caption(grid, 'Field').grid(row=0, column=0, sticky='w', padx=(0, 12))
        caption(grid, 'Bits').grid(row=1, column=0, sticky='w', padx=(0, 12))
        caption(grid, 'Meaning').grid(row=2, column=0, sticky='w', padx=(0, 12))
        self.field_cells = []
        for col in range(6):
            cells = (caption(grid, ''), value(grid), value(grid))
            for row, cell in enumerate(cells):
                cell.grid(row=row, column=col + 1, sticky='w', padx=(0, 8))
            self.field_cells.append(cells)

        box = panel('General-purpose registers (16 bits each)')
        self.reg_labels = []
        half = REG_COUNT // 2
        for block in range(2):
            base = block * 4
            for col, title in enumerate(('Register', 'Hex', 'Unsigned')):
                caption(box, title).grid(row=0, column=base + col, sticky='w', padx=(0, 16))
            box.columnconfigure(base + 3, minsize=30)
        for n in range(REG_COUNT):
            row, base = n % half + 1, n // half * 4
            name = value(box)
            name.configure(text=f'R{n}')
            name.grid(row=row, column=base, sticky='w')
            cells = (value(box), value(box))
            cells[0].grid(row=row, column=base + 1, sticky='w', padx=(0, 16))
            cells[1].grid(row=row, column=base + 2, sticky='w', padx=(0, 16))
            self.reg_labels.append(cells)

    def build_memory(self, body):
        frame = tk.Frame(body, bg=BG)
        frame.grid(row=0, column=2, sticky='nsew')
        self.heading(frame, f'Memory (RAM) - {MEM_SIZE} cells of 16 bits, code and data').pack(fill='x', pady=(0, 4))
        holder = tk.Frame(frame, bg=PANEL, highlightthickness=1, highlightbackground=LINE)
        holder.pack(fill='both', expand=True)
        columns = (('address', 'Address', 62), ('label', 'Label', 62), ('hex', 'Hex', 46),
                   ('value', 'Unsigned', 68), ('meaning', 'Contents', 170))
        self.memory = ttk.Treeview(holder, columns=[c[0] for c in columns], show='headings')
        for key, title, width in columns:
            self.memory.heading(key, text=title, anchor='w')
            self.memory.column(key, width=width, anchor='w', stretch=key == 'meaning')
        scroll = ttk.Scrollbar(holder, orient='vertical', command=self.memory.yview)
        self.memory.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.memory.pack(side='left', fill='both', expand=True)
        self.memory.tag_configure('next', background=NEXT)
        self.memory.tag_configure('changed', background=CHANGED)
        for addr in range(MEM_SIZE):
            self.memory.insert('', 'end', iid=str(addr))

    def build_log(self):
        bar = tk.Frame(self.root, bg=BG)
        bar.pack(side='bottom', fill='x', padx=12, pady=(0, 8))
        self.state_label = tk.Label(bar, bg=BG, fg=MUTED, anchor='w')
        self.state_label.pack(side='left')
        self.status = tk.Label(bar, bg=BG, fg=MUTED, anchor='e')
        self.status.pack(side='right')
        frame = tk.Frame(self.root, bg=BG)
        frame.pack(side='bottom', fill='x', padx=12, pady=(0, 6))
        self.heading(frame, 'Execution trace: address, machine code, instruction, effect').pack(fill='x', pady=(0, 4))
        self.log = tk.Text(frame, height=5, font=self.mono, state='disabled', bg=PANEL, fg=INK,
                           relief='flat', highlightthickness=1, highlightbackground=LINE, padx=8, pady=6)
        self.log.pack(fill='x')

    # --- actions --------------------------------------------------------------------------

    def say(self, text, error=False):
        self.status.configure(text=text, fg='#b91c1c' if error else MUTED)

    def write_log(self, text=None):
        self.log.configure(state='normal')
        if text is None:
            self.log.delete('1.0', 'end')
        else:
            self.log.insert('end', text + '\n')
            self.log.see('end')
        self.log.configure(state='disabled')

    def set_text(self, text):
        self.editor.delete('1.0', 'end')
        self.editor.insert('1.0', text)
        self.build()

    def load_example(self, name):
        self.set_text((BASE / 'examples' / f'{name}.asm').read_text(encoding='utf-8'))

    def open_file(self):
        path = filedialog.askopenfilename(filetypes=[('Assembly', '*.asm'), ('All files', '*')])
        if path:
            try:
                self.set_text(Path(path).read_text(encoding='utf-8'))
            except (OSError, UnicodeError) as exc:
                self.say(str(exc), error=True)

    def save_file(self):
        path = filedialog.asksaveasfilename(defaultextension='.asm')
        if path:
            try:
                Path(path).write_text(self.editor.get('1.0', 'end-1c'), encoding='utf-8')
            except OSError as exc:
                self.say(str(exc), error=True)

    def pause(self):
        if self.timer is not None:
            self.root.after_cancel(self.timer)
            self.timer = None

    def build(self):
        """Assemble the editor text, load it into memory and reset the processor."""
        self.pause()
        text = self.editor.get('1.0', 'end-1c')
        self.editor.tag_remove('error', '1.0', 'end')
        try:
            self.program = assemble(text)
        except AsmError as exc:
            self.program = self.built_text = None
            self.editor.tag_remove('next', '1.0', 'end')
            self.editor.tag_add('error', f'{exc.line}.0', f'{exc.line}.end+1c')
            self.editor.see(f'{exc.line}.0')
            self.say(f'Assembly error: {exc}', error=True)
            return False
        self.built_text = text
        self.say(f'Assembled: {len(self.program.lines)} instructions, '
                 f'{len(self.program.image)} memory cells loaded')
        self.reset()
        return True

    def reset(self):
        """Processor to the initial state, memory back to the assembled program."""
        self.pause()
        if self.program is None:
            return
        self.cpu.reset(self.program.image)
        self.write_log()
        self.refresh(everything=True)

    def ready(self):
        """Reassemble when the text was edited after the last build."""
        if self.program is None or self.editor.get('1.0', 'end-1c') != self.built_text:
            return self.build()
        return True

    def advance(self):
        """Execute one instruction; False when the run has to stop."""
        if self.cpu.halted:
            return False
        try:
            self.write_log(self.cpu.step())
        except CPUError as exc:
            self.cpu.halted = True
            self.say(f'Processor error: {exc}', error=True)
            self.refresh()
            return False
        if self.cpu.executed >= STEP_LIMIT and not self.cpu.halted:
            self.cpu.halted = True
            self.say(f'Stopped after {STEP_LIMIT} instructions: endless loop?', error=True)
        self.refresh()
        return not self.cpu.halted

    def step(self):
        self.pause()
        if self.ready():
            self.advance()

    def run(self):
        self.pause()
        if self.ready():
            self.tick()

    def tick(self):
        self.timer = None
        if self.advance():
            try:
                delay = max(0, min(2000, self.delay.get()))
            except tk.TclError:
                delay = 150
            self.timer = self.root.after(delay, self.tick)

    # --- drawing the state ----------------------------------------------------------------

    def memory_row(self, addr, labels):
        word = self.cpu.mem[addr]
        meaning = ''
        if addr in self.program.lines:
            try:
                meaning = disassemble(decode(word << 16 | self.cpu.mem[addr + 1]))
            except DecodeError:
                meaning = 'not an instruction'
        elif addr - 1 in self.program.lines:
            meaning = '  (second half)'
        elif addr in self.program.image:
            meaning = 'data'
        self.memory.item(str(addr), values=(f'0x{addr:03X}', labels.get(addr, ''), f'{word:04X}', word, meaning))

    def refresh(self, everything=False):
        cpu = self.cpu
        labels = {}
        for name, addr in self.program.labels.items():
            labels[addr] = f'{labels[addr]}, {name}' if addr in labels else name

        self.pc_label.configure(text=f'0x{cpu.pc:03X}  ({cpu.pc})')
        if cpu.ir_addr is None:
            self.ir_code.configure(text='-')
            self.ir_asm.configure(text='nothing executed yet')
            for title, bits, meaning in self.field_cells:
                bits.configure(text='')
                meaning.configure(text='')
            for cells, (title, _, _) in zip(self.field_cells, describe_fields(0)):
                cells[0].configure(text=title)
        else:
            try:
                text = disassemble(decode(cpu.ir))
            except DecodeError:
                text = 'not an instruction'
            self.ir_code.configure(text=f'0x{cpu.ir:08X}')
            self.ir_asm.configure(text=text)
            for cells, (title, bits, meaning) in zip(self.field_cells, describe_fields(cpu.ir)):
                cells[0].configure(text=title)
                cells[1].configure(text=bits)
                cells[2].configure(text=meaning)
        for key, label in self.flag_labels.items():
            label.configure(text=str(getattr(cpu, key)))
        for n, (hexa, dec) in enumerate(self.reg_labels):
            colour = CHANGED if n in cpu.changed_regs else PANEL
            hexa.configure(text=f'0x{cpu.reg[n]:04X}', bg=colour)
            dec.configure(text=str(cpu.reg[n]), bg=colour)
        self.state_label.configure(text=f'Instructions executed: {cpu.executed}      State: '
                                        + ('halted' if cpu.halted else 'ready for the next instruction'))

        # Memory: redraw only what changed, move the highlights.
        for addr in (range(MEM_SIZE) if everything else cpu.changed_mem):
            self.memory_row(addr, labels)
        for addr in self.marked:
            self.memory.item(str(addr), tags=())
        self.marked = set(cpu.changed_mem)
        for addr in cpu.changed_mem:
            self.memory.item(str(addr), tags=('changed',))
        if not cpu.halted:
            for addr in range(cpu.pc, min(cpu.pc + INSTR_CELLS, MEM_SIZE)):
                self.memory.item(str(addr), tags=('next',))
                self.marked.add(addr)
        focus = min(cpu.changed_mem) if cpu.changed_mem else min(cpu.pc, MEM_SIZE - 1)
        self.memory.see(str(focus))

        # Editor: highlight the line of the instruction that runs next.
        self.editor.tag_remove('next', '1.0', 'end')
        line = None if cpu.halted else self.program.lines.get(cpu.pc)
        if line and self.editor.get('1.0', 'end-1c') == self.built_text:
            self.editor.tag_add('next', f'{line}.0', f'{line}.end+1c')
            self.editor.see(f'{line}.0')


if __name__ == '__main__':
    window = tk.Tk()
    App(window)
    window.mainloop()

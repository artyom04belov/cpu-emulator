"""Run with python3 main.py. Only the Python standard library is required."""
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from core import CPU, assemble

BASE = Path(__file__).resolve().parent

class App:
    def __init__(self, root):
        self.root = root
        root.title('Neumann Lab — двухадресный процессор')
        root.geometry('1250x850')
        self.cpu = self.program = None
        self.running = False
        self.timer = None
        bar = ttk.Frame(root, padding=8)
        bar.pack(fill='x')
        for title, command in [('Максимум', lambda: self.example('maximum')), ('Свёртка', lambda: self.example('convolution')), ('Открыть', self.open), ('Сохранить', self.save), ('Собрать / сброс', self.build), ('Этап', self.step), ('Пуск', self.run), ('Пауза', self.pause)]:
            ttk.Button(bar, text=title, command=command).pack(side='left', padx=2)
        ttk.Label(bar, text='мс/этап').pack(side='left', padx=5)
        self.delay = tk.IntVar(value=100)
        ttk.Spinbox(bar, from_=1, to=2000, textvariable=self.delay, width=5).pack(side='left')
        pane = ttk.Panedwindow(root, orient='horizontal')
        pane.pack(fill='both', expand=True, padx=8)
        left, right = ttk.Frame(pane), ttk.Frame(pane)
        pane.add(left, weight=1)
        pane.add(right, weight=2)
        ttk.Label(left, text='Ассемблер · измените массивы в строках .word').pack(anchor='w')
        self.editor = tk.Text(left, width=48, undo=True, font=('Menlo', 12), wrap='none')
        self.editor.pack(fill='both', expand=True)
        self.editor.tag_configure('current', background='#ffe49c', foreground='#111111')
        self.canvas = tk.Canvas(right, height=190, bg='#f1f5f9', highlightthickness=0)
        self.canvas.pack(fill='x')
        self.boxes = {}
        for key, coords, label in [('control', (15, 25, 190, 105), 'Устройство управления\nPC → IR → декодер'), ('alu', (235, 25, 395, 105), 'АЛУ\n+, −, ×, сравнение'), ('memory', (440, 25, 640, 105), 'Общая память\nкоманды + данные')]:
            self.boxes[key] = self.canvas.create_rectangle(*coords, fill='white', outline='#64748b', width=2)
            self.canvas.create_text((coords[0]+coords[2])/2, 65, text=label, fill='#0f172a')
        self.canvas.create_line(100, 105, 100, 145, 540, 145, 540, 105, arrow='both', width=2)
        self.canvas.create_line(315, 105, 315, 145, width=2)
        self.canvas.create_text(315, 168, text='Шина адресов и данных', fill='#334155')
        self.state = tk.StringVar()
        ttk.Label(right, textvariable=self.state, font=('Menlo', 11), justify='left').pack(anchor='w', pady=8)
        memframe = ttk.Frame(right)
        memframe.pack(fill='both', expand=True)
        self.memory = ttk.Treeview(memframe, columns=('address', 'label', 'hex', 'value'), show='headings', height=13)
        for col, title, width in [('address', 'Адрес', 60), ('label', 'Метка', 120), ('hex', 'Слово HEX', 120), ('value', 'Без знака', 120)]:
            self.memory.heading(col, text=title)
            self.memory.column(col, width=width)
        scroll = ttk.Scrollbar(memframe, orient='vertical', command=self.memory.yview)
        self.memory.configure(yscrollcommand=scroll.set)
        self.memory.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')
        self.result = tk.StringVar()
        ttk.Label(root, textvariable=self.result, wraplength=1200, padding=8).pack(fill='x')
        self.log = tk.Text(root, height=7, font=('Menlo', 11), state='disabled')
        self.log.pack(fill='x', padx=8, pady=5)
        self.example('maximum')

    def pause(self):
        self.running = False
        if self.timer is not None:
            self.root.after_cancel(self.timer)
            self.timer = None

    def example(self, name):
        self.pause()
        self.editor.delete('1.0', 'end')
        self.editor.insert('1.0', (BASE / 'examples' / (name + '.asm')).read_text(encoding='utf-8'))
        self.build()

    def open(self):
        self.pause()
        path = filedialog.askopenfilename(filetypes=[('Ассемблер', '*.asm'), ('Все файлы', '*')])
        if path:
            try:
                text = Path(path).read_text(encoding='utf-8')
                self.editor.delete('1.0', 'end')
                self.editor.insert('1.0', text)
                self.build()
            except (OSError, UnicodeError) as exc:
                messagebox.showerror('Ошибка открытия', str(exc))

    def save(self):
        path = filedialog.asksaveasfilename(defaultextension='.asm')
        if path:
            try:
                Path(path).write_text(self.editor.get('1.0', 'end-1c'), encoding='utf-8')
            except OSError as exc:
                messagebox.showerror('Ошибка сохранения', str(exc))

    def build(self):
        self.pause()
        try:
            text = self.editor.get('1.0', 'end-1c')
            program = assemble(text)
        except ValueError as exc:
            self.cpu = None
            messagebox.showerror('Ошибка ассемблера', str(exc))
            return False
        self.program, self.cpu, self.built_text = program, CPU(program), text
        self.log.configure(state='normal')
        self.log.delete('1.0', 'end')
        self.log.configure(state='disabled')
        self.refresh()
        return True

    def step(self):
        self.pause()
        self.advance()

    def advance(self):
        if self.cpu is None or self.editor.get('1.0', 'end-1c') != self.built_text:
            if not self.build():
                return False
        try:
            message = self.cpu.step()
        except ValueError as exc:
            self.pause()
            messagebox.showerror('Ошибка процессора', str(exc))
            return False
        self.log.configure(state='normal')
        self.log.insert('end', message + '\n')
        if int(self.log.index('end-1c').split('.')[0]) > 300:
            self.log.delete('1.0', '2.0')
        self.log.see('end')
        self.log.configure(state='disabled')
        self.refresh()
        return not self.cpu.halted

    def run(self):
        self.pause()
        if self.cpu is None or self.editor.get('1.0', 'end-1c') != self.built_text:
            if not self.build():
                return
        if self.cpu.halted:
            return
        self.running = True
        self.tick()

    def tick(self):
        self.timer = None
        if self.running and self.advance():
            try:
                delay = max(1, min(2000, self.delay.get()))
            except (ValueError, tk.TclError):
                delay = 100
            self.timer = self.root.after(delay, self.tick)
        else:
            self.running = False

    def refresh(self):
        c = self.cpu
        status = 'HALT' if c.halted else c.phase
        self.state.set(f'Следующий этап: {status}     Выполнено команд: {c.instructions}\nPC={c.pc}  IR=0x{c.ir:08X}  MAR={c.mar}  MDR=0x{c.mdr:08X}\nZ={int(c.z)} C={int(c.c)} GT={int(c.gt)} LT={int(c.lt)}\n' + '  '.join(f'R{i}={v}' for i, v in enumerate(c.r[:4])) + '\n' + '  '.join(f'R{i+4}={v}' for i, v in enumerate(c.r[4:])))
        active = {'Выборка': 'memory', 'Декодирование': 'control', 'Выполнение': 'alu'}.get(c.phase)
        for key, item in self.boxes.items():
            self.canvas.itemconfigure(item, fill='#bfdbfe' if key == active and not c.halted else 'white')
        labels = {}
        for name, addr in self.program.labels.items():
            labels[addr] = labels.get(addr, '') + name + ' '
        for addr, value in enumerate(c.memory):
            values = (addr, labels.get(addr, ''), f'{value:08X}', value)
            if self.memory.exists(str(addr)):
                self.memory.item(str(addr), values=values)
            else:
                self.memory.insert('', 'end', iid=str(addr), values=values)
        self.editor.tag_remove('current', '1.0', 'end')
        addr = c.pc if c.phase == 'Выборка' and not c.halted else c.mar
        line = self.program.source.get(addr)
        if line:
            self.editor.tag_add('current', f'{line}.0', f'{line}.end')
            self.editor.see(f'{line}.0')
        if 'result' in self.program.labels:
            start = self.program.labels['result']
            count = 11 if 'a' in self.program.labels and 'b' in self.program.labels else 1
            values = c.memory[start:start+count]
            self.result.set(('Результат: ' if c.halted else 'Промежуточное значение result: ') + ', '.join(map(str, values)))
        else:
            self.result.set('Результаты доступны в памяти и регистрах')

if __name__ == '__main__':
    root = tk.Tk()
    App(root)
    root.mainloop()

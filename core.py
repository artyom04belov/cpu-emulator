"""32-bit educational von Neumann CPU and a two-pass assembler."""
from dataclasses import dataclass
import re

MASK = 0xFFFFFFFF
OPS = {name: i for i, name in enumerate(('HALT', 'MOV', 'ADD', 'SUB', 'MUL', 'CMP', 'JMP', 'JZ', 'JNZ', 'JA', 'JB', 'NOP'))}
NAMES = {v: k for k, v in OPS.items()}
ARITY = {name: (0 if name in ('HALT', 'NOP') else 1 if name.startswith('J') else 2) for name in OPS}

@dataclass
class Program:
    memory: list
    labels: dict
    source: dict


def assemble(text):
    labels, lines, source = {}, [], {}
    pc = 0
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.split(';', 1)[0].strip()
        if not line:
            continue
        if ':' in line:
            label, line = line.split(':', 1)
            label, line = label.strip(), line.strip()
            if not re.fullmatch(r'[A-Za-z_]\w*', label) or label in labels:
                raise ValueError(f'Строка {number}: неверная или повторная метка {label}')
            labels[label] = pc
        if not line:
            continue
        parts = line.split(None, 1)
        op = parts[0].upper()
        args = [a.strip() for a in parts[1].split(',')] if len(parts) > 1 else []
        if op == '.WORD':
            if not args:
                raise ValueError(f'Строка {number}: .word требует данные')
            size = len(args)
        else:
            if op not in OPS or len(args) != ARITY[op]:
                raise ValueError(f'Строка {number}: неизвестная команда или неверное число операндов')
            size = 1
        lines.append((pc, number, op, args))
        source[pc] = number
        pc += size
        if pc > 256:
            raise ValueError('Программа превышает память в 256 слов')
    memory = [0] * 256
    def value(s):
        return labels[s] if s in labels else int(s, 0)
    def operand(s):
        if re.fullmatch(r'R[0-7]', s.upper()):
            return 0x800 | int(s[1])
        if re.fullmatch(r'\[R[0-7]\]', s.upper()):
            return 0xC00 | int(s[2])
        if s.startswith('#'):
            n = value(s[1:])
            if not 0 <= n <= 1023:
                raise ValueError('Непосредственная константа должна быть 0…1023; большие числа храните в .word')
            return 0x400 | n
        n = value(s[1:-1] if s.startswith('[') and s.endswith(']') else s)
        if not 0 <= n < 256:
            raise ValueError('Адрес должен быть 0…255')
        return n
    for addr, number, op, args in lines:
        try:
            if op == '.WORD':
                for i, arg in enumerate(args):
                    n = value(arg)
                    if not 0 <= n <= MASK:
                        raise ValueError('Данные должны быть uint32')
                    memory[addr + i] = n
            else:
                codes = [operand(a) for a in args]
                if op in ('MOV', 'ADD', 'SUB', 'MUL') and codes[0] >> 10 == 1:
                    raise ValueError('Нельзя записать результат в константу')
                if op.startswith('J') and codes[0] >> 10 != 0:
                    raise ValueError('Переход требует прямой адрес или метку')
                codes += [0] * (2 - len(codes))
                memory[addr] = OPS[op] << 24 | codes[0] << 12 | codes[1]
        except (ValueError, KeyError) as exc:
            raise ValueError(f'Строка {number}: {exc}') from exc
    return Program(memory, labels, source)


class CPU:
    def __init__(self, program):
        self.memory = program.memory.copy()
        self.r = [0] * 8
        self.pc = self.ir = self.mar = self.mdr = 0
        self.z = self.c = self.gt = self.lt = False
        self.phase = 'Выборка'
        self.halted = False
        self.instructions = 0
        self.current = None

    def address(self, n):
        if not 0 <= n < 256:
            raise ValueError(f'Адрес вне памяти: {n}')
        return n

    def validate(self, code):
        mode, n = code >> 10, code & 1023
        if mode == 0:
            self.address(n)
        if mode in (2, 3) and n > 7:
            raise ValueError('Неверный номер регистра')

    def read(self, code):
        mode, n = code >> 10, code & 1023
        if mode == 1:
            return n
        if mode == 2:
            return self.r[n]
        return self.memory[self.address(self.r[n] if mode == 3 else n)]

    def write(self, code, value):
        mode, n = code >> 10, code & 1023
        if mode == 1:
            raise ValueError('Запись в константу')
        if mode == 2:
            self.r[n] = value & MASK
        else:
            self.memory[self.address(self.r[n] if mode == 3 else n)] = value & MASK

    def step(self):
        if self.halted:
            return 'Процессор остановлен'
        if self.phase == 'Выборка':
            self.mar = self.address(self.pc)
            self.mdr = self.memory[self.mar]
            self.ir = self.mdr
            self.pc += 1
            self.phase = 'Декодирование'
            return f'Выборка: M[{self.mar}] → IR = 0x{self.ir:08X}; PC = {self.pc}'
        if self.phase == 'Декодирование':
            op = NAMES.get(self.ir >> 24)
            if op is None:
                raise ValueError(f'Неизвестный код команды: {self.ir >> 24}')
            a, b = (self.ir >> 12) & 4095, self.ir & 4095
            for code in (a, b)[:ARITY[op]]:
                self.validate(code)
            if op in ('MOV', 'ADD', 'SUB', 'MUL') and a >> 10 == 1:
                raise ValueError('Недопустимый приёмник')
            if op.startswith('J') and a >> 10:
                raise ValueError('Недопустимый адрес перехода')
            self.current = op, a, b
            self.phase = 'Выполнение'
            return f'Декодирование: {op}; операнды 0x{a:03X}, 0x{b:03X}'
        op, a, b = self.current
        if op == 'HALT':
            self.halted = True
        elif op.startswith('J'):
            condition = {'JMP': True, 'JZ': self.z, 'JNZ': not self.z, 'JA': self.gt, 'JB': self.lt}[op]
            if condition:
                self.pc = self.address(a)
        elif op == 'MOV':
            self.write(a, self.read(b))
        elif op in ('ADD', 'SUB', 'MUL', 'CMP'):
            x, y = self.read(a), self.read(b)
            if op == 'CMP':
                self.z, self.gt, self.lt, self.c = x == y, x > y, x < y, x < y
            else:
                result = {'ADD': lambda: x + y, 'SUB': lambda: x - y, 'MUL': lambda: x * y}[op]()
                self.write(a, result)
                self.z, self.c = (result & MASK) == 0, not 0 <= result <= MASK
                self.gt = self.lt = False
        self.instructions += 1
        self.phase = 'Выборка'
        return f'Выполнение: {op}; завершено команд: {self.instructions}'

    def run(self, limit=100000):
        for _ in range(limit):
            if self.halted:
                return
            self.step()
        raise ValueError('Превышен лимит этапов; возможен бесконечный цикл')

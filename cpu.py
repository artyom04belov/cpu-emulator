"""The emulated processor: memory, registers, flags and the instruction cycle."""
from isa import (WORD_BITS, WORD_MASK, MEM_SIZE, REG_COUNT, INSTR_CELLS, REG, IMM, DIR, IND,
                 HALT, MOVE, COMPARE, JUMP, DecodeError, decode, disassemble)


class CPUError(Exception):
    """The program made the processor do something impossible."""


class CPU:
    def __init__(self):
        self.reset()

    def reset(self, image=None):
        """Clear the whole machine and optionally load a memory image {address: word}."""
        self.mem = [0] * MEM_SIZE          # one memory for code and data (von Neumann)
        self.reg = [0] * REG_COUNT         # general-purpose registers R0..R15
        self.pc = 0                        # program counter: address of the next instruction
        self.ir = 0                        # instruction register: the instruction being executed
        self.z = self.c = self.s = 0       # flags: zero, carry / borrow, sign
        self.halted = False
        self.executed = 0
        self.ir_addr = None                # where the instruction in IR was fetched from
        self.changed_regs = set()          # what the last instruction wrote
        self.changed_mem = set()
        for addr, word in (image or {}).items():
            self.mem[addr] = word

    # --- memory access ------------------------------------------------------------------

    def check(self, addr):
        if not 0 <= addr < MEM_SIZE:
            raise CPUError(f'address 0x{addr:04X} is outside memory (0x000..0x{MEM_SIZE - 1:03X})')
        return addr

    def load(self, addr):
        return self.mem[self.check(addr)]

    def store(self, addr, value):
        self.mem[self.check(addr)] = value & WORD_MASK
        self.changed_mem.add(addr)

    def set_reg(self, n, value):
        self.reg[n] = value & WORD_MASK
        self.changed_regs.add(n)

    # --- arithmetic logic unit ----------------------------------------------------------

    def alu(self, name, x, y):
        """Compute one operation on two 16-bit words; update the flags; return the result."""
        carry = 0
        if name in ('ADD', 'ADC'):
            full = x + y + (self.c if name == 'ADC' else 0)
            carry = full >> WORD_BITS                      # bit that did not fit into 16 bits
        elif name in ('SUB', 'SBB', 'CMP'):
            full = x - y - (self.c if name == 'SBB' else 0)
            carry = int(full < 0)                          # a borrow was needed
        elif name in ('MUL', 'MULH'):
            product = x * y                                # up to 32 bits wide
            carry = int(product > WORD_MASK)
            full = product if name == 'MUL' else product >> WORD_BITS
        elif name == 'AND':
            full = x & y
        elif name == 'OR':
            full = x | y
        elif name == 'XOR':
            full = x ^ y
        else:                                              # SHL, SHR
            count = y & (WORD_BITS - 1)
            if name == 'SHL':
                full = x << count
                carry = (full >> WORD_BITS) & 1            # the last bit pushed out
            else:
                full = x >> count
                carry = (x >> (count - 1)) & 1 if count else 0
        result = full & WORD_MASK
        self.z = int(result == 0)
        self.c = carry
        self.s = result >> (WORD_BITS - 1)
        return result

    # --- instruction cycle --------------------------------------------------------------

    def step(self):
        """Fetch, decode and execute one instruction. Returns a line for the trace log."""
        if self.halted:
            return 'The processor is halted.'
        self.changed_regs, self.changed_mem = set(), set()

        # Fetch: two cells, the high half of the instruction comes first.
        addr = self.pc
        self.check(addr + INSTR_CELLS - 1)
        self.ir = self.mem[addr] << WORD_BITS | self.mem[addr + 1]
        self.ir_addr = addr
        self.pc = addr + INSTR_CELLS

        # Decode.
        try:
            ins = decode(self.ir)
        except DecodeError as exc:
            raise CPUError(f'at 0x{addr:03X}: {exc}') from exc

        # Execute.
        effect = ''
        if ins.kind == HALT:
            self.halted = True
            effect = 'halted'
        elif ins.kind == MOVE:
            effect = self.move(ins)
        elif ins.kind == JUMP:
            taken = {'JMP': True, 'JZ': self.z, 'JNZ': not self.z, 'JC': self.c,
                     'JNC': not self.c, 'JS': self.s, 'JNS': not self.s}[ins.name]
            if taken:
                self.pc = ins.a3
            effect = f'jump taken, PC = 0x{self.pc:03X}' if taken else 'no jump'
        else:                                              # ALU and CMP: registers only
            x = self.reg[ins.a2]
            y = ins.a3 if ins.smode == IMM else self.reg[ins.a3]
            result = self.alu(ins.name, x, y)
            if ins.kind == COMPARE:
                effect = f'compared {x} with {y}'
            else:
                self.set_reg(ins.a1, result)
                effect = f'R{ins.a1} = 0x{result:04X} ({result})'
            effect += f'; Z={self.z} C={self.c} S={self.s}'
        self.executed += 1
        return f'0x{addr:03X}  {self.ir:08X}  {disassemble(ins):<22} {effect}'

    def move(self, ins):
        """MOV is the only instruction that reads or writes memory."""
        if ins.dmode == REG:                               # load into register A1
            if ins.smode == REG:
                value = self.reg[ins.a3]
            elif ins.smode == IMM:
                value = ins.a3
            elif ins.smode == DIR:
                value = self.load(ins.a3)
            else:
                value = self.load(self.reg[ins.a3])
            self.set_reg(ins.a1, value)
            return f'R{ins.a1} = 0x{value:04X} ({value})'
        addr = ins.a3 if ins.dmode == DIR else self.reg[ins.a3]   # store register A1
        self.store(addr, self.reg[ins.a1])
        return f'mem[0x{addr:03X}] = 0x{self.reg[ins.a1]:04X} ({self.reg[ins.a1]})'

    def run(self, limit=100_000):
        """Run until HLT. The limit protects against endless loops."""
        for _ in range(limit):
            if self.halted:
                return
            self.step()
        if not self.halted:
            raise CPUError(f'no HLT after {limit} instructions: endless loop?')

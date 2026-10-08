"""Instruction set of the emulated processor: word sizes, fields, opcodes.

Every instruction is 32 bits long and has the same layout:

    31      24 23  22 21  20 19    16 15    12 11           0
    +---------+------+------+--------+--------+--------------+
    | opcode  | DM   | SM   |   A1   |   A2   |      A3      |
    +---------+------+------+--------+--------+--------------+
       8 bits  2 bits 2 bits  4 bits   4 bits     12 bits

    opcode  what to do
    DM      addressing mode of the destination
    SM      addressing mode of the source (the second operand)
    A1      register that receives the result
    A2      register holding the first operand
    A3      second operand: register number, literal or memory address
"""
from dataclasses import dataclass

WORD_BITS = 16                 # width of a register and of a memory cell
WORD_MASK = 0xFFFF
MEM_SIZE = 4096                # cells; a 12-bit address reaches all of them
REG_COUNT = 16                 # R0..R15, a 4-bit field
INSTR_CELLS = 2                # one instruction occupies two memory cells
A3_MASK = 0xFFF

# Addressing modes (the 2-bit DM / SM fields).
REG, IMM, DIR, IND = 0, 1, 2, 3
MODE_NAMES = {REG: 'register', IMM: 'immediate', DIR: 'direct', IND: 'register-indirect'}

# Instruction kinds: they define which operands an instruction takes.
HALT, MOVE, ALU, COMPARE, JUMP = 'halt', 'move', 'alu', 'compare', 'jump'

# mnemonic: (opcode, kind, description)
INSTRUCTIONS = {
    'HLT':  (0x00, HALT,    'stop the processor'),
    'MOV':  (0x01, MOVE,    'copy: destination <- source'),
    'ADD':  (0x10, ALU,     'A1 <- A2 + A3'),
    'ADC':  (0x11, ALU,     'A1 <- A2 + A3 + C'),
    'SUB':  (0x12, ALU,     'A1 <- A2 - A3'),
    'SBB':  (0x13, ALU,     'A1 <- A2 - A3 - C'),
    'MUL':  (0x14, ALU,     'A1 <- low word of A2 * A3'),
    'MULH': (0x15, ALU,     'A1 <- high word of A2 * A3'),
    'CMP':  (0x16, COMPARE, 'set flags by A2 - A3, result is dropped'),
    'AND':  (0x20, ALU,     'A1 <- A2 AND A3'),
    'OR':   (0x21, ALU,     'A1 <- A2 OR A3'),
    'XOR':  (0x22, ALU,     'A1 <- A2 XOR A3'),
    'SHL':  (0x23, ALU,     'A1 <- A2 shifted left by A3 bits'),
    'SHR':  (0x24, ALU,     'A1 <- A2 shifted right by A3 bits'),
    'JMP':  (0x30, JUMP,    'PC <- A3'),
    'JZ':   (0x31, JUMP,    'PC <- A3 if Z = 1'),
    'JNZ':  (0x32, JUMP,    'PC <- A3 if Z = 0'),
    'JC':   (0x33, JUMP,    'PC <- A3 if C = 1'),
    'JNC':  (0x34, JUMP,    'PC <- A3 if C = 0'),
    'JS':   (0x35, JUMP,    'PC <- A3 if S = 1'),
    'JNS':  (0x36, JUMP,    'PC <- A3 if S = 0'),
}
MNEMONICS = {code: name for name, (code, _, _) in INSTRUCTIONS.items()}

# Allowed (DM, SM) pairs. Only MOV may touch memory (RISC rule).
MOVE_MODES = {(REG, REG), (REG, IMM), (REG, DIR), (REG, IND), (DIR, REG), (IND, REG)}
ALU_MODES = {(REG, REG), (REG, IMM)}
JUMP_MODES = {(REG, IMM)}
HALT_MODES = {(REG, REG)}


class DecodeError(Exception):
    """The word in the instruction register is not a valid instruction."""


@dataclass(frozen=True)
class Instruction:
    name: str
    dmode: int = REG
    smode: int = REG
    a1: int = 0
    a2: int = 0
    a3: int = 0

    @property
    def opcode(self):
        return INSTRUCTIONS[self.name][0]

    @property
    def kind(self):
        return INSTRUCTIONS[self.name][1]


def encode(ins):
    """Pack the fields of an instruction into one 32-bit machine word."""
    return (ins.opcode << 24 | ins.dmode << 22 | ins.smode << 20
            | ins.a1 << 16 | ins.a2 << 12 | ins.a3)


def fields(word):
    """Cut a 32-bit machine word into its raw fields with shifts and masks."""
    return {
        'opcode': (word >> 24) & 0xFF,
        'dmode': (word >> 22) & 0x3,
        'smode': (word >> 20) & 0x3,
        'a1': (word >> 16) & 0xF,
        'a2': (word >> 12) & 0xF,
        'a3': word & A3_MASK,
    }


def decode(word):
    """Turn a machine word into an Instruction, checking that it is legal."""
    f = fields(word)
    name = MNEMONICS.get(f['opcode'])
    if name is None:
        raise DecodeError(f"unknown opcode 0x{f['opcode']:02X}")
    ins = Instruction(name, f['dmode'], f['smode'], f['a1'], f['a2'], f['a3'])
    allowed = {HALT: HALT_MODES, MOVE: MOVE_MODES, ALU: ALU_MODES,
               COMPARE: ALU_MODES, JUMP: JUMP_MODES}[ins.kind]
    if (ins.dmode, ins.smode) not in allowed:
        raise DecodeError(f'{name} does not support addressing '
                          f'{MODE_NAMES[ins.dmode]} <- {MODE_NAMES[ins.smode]}')
    # In MOV the mode that is not "register" describes A3; otherwise SM does.
    a3_mode = ins.dmode if ins.dmode != REG else ins.smode
    if a3_mode in (REG, IND) and ins.a3 >= REG_COUNT:
        raise DecodeError(f'no such register: R{ins.a3}')
    return ins


def operand_text(mode, value):
    """Assembly spelling of the A3 operand in the given addressing mode."""
    return {REG: f'R{value}', IMM: str(value),
            DIR: f'[0x{value:03X}]', IND: f'[R{value}]'}[mode]


def disassemble(ins):
    """Assembly text of a decoded instruction."""
    if ins.kind == HALT:
        return ins.name
    if ins.kind == JUMP:
        return f'{ins.name} 0x{ins.a3:03X}'
    if ins.kind == COMPARE:
        return f'{ins.name} R{ins.a2}, {operand_text(ins.smode, ins.a3)}'
    if ins.kind == ALU:
        return f'{ins.name} R{ins.a1}, R{ins.a2}, {operand_text(ins.smode, ins.a3)}'
    if ins.dmode == REG:                                   # MOV: load
        return f'{ins.name} R{ins.a1}, {operand_text(ins.smode, ins.a3)}'
    return f'{ins.name} {operand_text(ins.dmode, ins.a3)}, R{ins.a1}'   # MOV: store

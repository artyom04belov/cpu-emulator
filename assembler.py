"""Assembler: text of a program -> machine words in memory.

The work is done in three classic steps:
  1. lexical analysis   - a line is cut into tokens (names, numbers, punctuation);
  2. syntax analysis    - tokens become a statement: label, mnemonic, operands;
  3. code generation    - the statement is packed into the fields of a machine word.
Labels are resolved in two passes: the first pass only counts addresses and fills
the label table, the second one already knows every address and generates code.
"""
from dataclasses import dataclass, field
import re

from isa import (WORD_MASK, MEM_SIZE, REG_COUNT, INSTR_CELLS, A3_MASK, REG, IMM, DIR, IND,
                 HALT, MOVE, ALU, COMPARE, JUMP, INSTRUCTIONS, MOVE_MODES, Instruction, encode)

TOKEN = re.compile(r'\s*(?:(?P<number>0[xX][0-9a-fA-F]+|0[bB][01]+|\d+)(?![\w.])'
                   r'|(?P<name>[A-Za-z_.][\w.]*)|(?P<punct>[,\[\]:]))')
REGISTER = re.compile(r'[rR](\d+)$')
OPERAND_COUNT = {HALT: 0, MOVE: 2, ALU: 3, COMPARE: 2, JUMP: 1}


class AsmError(Exception):
    def __init__(self, line, message):
        super().__init__(f'line {line}: {message}')
        self.line = line


@dataclass
class Operand:
    mode: int
    value: object                 # int, or the name of a label until it is resolved


@dataclass
class Program:
    image: dict = field(default_factory=dict)      # address -> 16-bit word
    labels: dict = field(default_factory=dict)     # label -> address
    lines: dict = field(default_factory=dict)      # instruction address -> source line number
    listing: list = field(default_factory=list)    # (address, [words], source text)


def tokenize(text):
    """Lexical analysis: 'MOV R1, [arr]' -> [('name','MOV'), ('reg',1), (',',','), ...]."""
    text = re.split(r';|//', text, maxsplit=1)[0].rstrip()
    tokens, pos = [], 0
    while pos < len(text):
        match = TOKEN.match(text, pos)
        if not match:
            raise ValueError(f'unexpected text "{text[pos:].strip()}"')
        pos = match.end()
        if match['number']:
            tokens.append(('number', int(match['number'], 0)))
        elif match['punct']:
            tokens.append((match['punct'], match['punct']))
        elif REGISTER.match(match['name']):
            number = int(match['name'][1:])
            if number >= REG_COUNT:
                raise ValueError(f'no such register: {match["name"]} (R0..R{REG_COUNT - 1} exist)')
            tokens.append(('reg', number))
        else:
            tokens.append(('name', match['name']))
    return tokens


def parse_operand(tokens):
    """Syntax of one operand; the spelling decides the addressing mode."""
    kinds = [kind for kind, _ in tokens]
    if kinds == ['reg']:
        return Operand(REG, tokens[0][1])                  # R1       register
    if kinds in (['number'], ['name']):
        return Operand(IMM, tokens[0][1])                  # 5, arr   immediate
    if kinds == ['[', 'reg', ']']:
        return Operand(IND, tokens[1][1])                  # [R1]     register-indirect
    if kinds in (['[', 'number', ']'], ['[', 'name', ']']):
        return Operand(DIR, tokens[1][1])                  # [arr]    direct
    raise ValueError('cannot understand operand "' + ' '.join(str(v) for _, v in tokens) + '"')


def parse_line(text):
    """Syntax analysis of a line -> (label or None, mnemonic or None, operands)."""
    tokens = tokenize(text)
    label = None
    if len(tokens) >= 2 and tokens[0][0] == 'name' and tokens[1][0] == ':':
        label, tokens = tokens[0][1], tokens[2:]
    if not tokens:
        return label, None, []
    if tokens[0][0] != 'name':
        raise ValueError('an instruction name is expected')
    groups, current = [], []
    for token in tokens[1:]:                               # split operands by commas
        if token[0] == ',':
            groups.append(current)
            current = []
        else:
            current.append(token)
    if current or groups:
        groups.append(current)
    return label, tokens[0][1].upper(), [parse_operand(group) for group in groups]


def build(name, ops):
    """Code generation: place operands into the fields A1, A2, A3 and the mode bits."""
    kind = INSTRUCTIONS[name][1]
    if len(ops) != OPERAND_COUNT[kind]:
        raise ValueError(f'{name} takes {OPERAND_COUNT[kind]} operand(s), got {len(ops)}')
    if kind == HALT:
        return Instruction(name)
    if kind == JUMP:
        if ops[0].mode != IMM:
            raise ValueError(f'{name} needs a label or an address')
        return Instruction(name, REG, IMM, a3=ops[0].value)
    if kind == MOVE:
        dst, src = ops
        if (dst.mode, src.mode) not in MOVE_MODES:
            raise ValueError('MOV needs a register on one side: MOV Rn, source  or  MOV [..], Rn')
        if dst.mode == REG:                                # load: register <- source
            return Instruction(name, REG, src.mode, a1=dst.value, a3=src.value)
        return Instruction(name, dst.mode, REG, a1=src.value, a3=dst.value)   # store
    regs, last = ops[:-1], ops[-1]                         # ALU and CMP
    if any(op.mode != REG for op in regs) or last.mode not in (REG, IMM):
        raise ValueError(f'{name} works only with registers; the last operand may be a number. '
                         'Use MOV to read or write memory')
    if kind == COMPARE:
        return Instruction(name, REG, last.mode, a2=regs[0].value, a3=last.value)
    return Instruction(name, REG, last.mode, a1=regs[0].value, a2=regs[1].value, a3=last.value)


def assemble(text):
    program = Program()
    statements = []                                        # (line number, address, name, operands)
    source = text.splitlines()

    # Pass 1: give every statement an address and remember the labels.
    addr = 0
    for number, line in enumerate(source, 1):
        try:
            label, name, ops = parse_line(line)
            if label is not None:
                if label in program.labels:
                    raise ValueError(f'label "{label}" is defined twice')
                if label.upper() in INSTRUCTIONS or label.startswith('.'):
                    raise ValueError(f'"{label}" cannot be used as a label')
                program.labels[label] = addr
            if name is None:
                continue
            if name == '.ORG':
                if len(ops) != 1 or ops[0].mode != IMM or not isinstance(ops[0].value, int):
                    raise ValueError('.org needs one number: the new address')
                addr = ops[0].value
                if label is not None:
                    program.labels[label] = addr
                size = 0
            elif name == '.WORD':
                if not ops or any(op.mode != IMM for op in ops):
                    raise ValueError('.word needs a list of numbers')
                size = len(ops)
            elif name in INSTRUCTIONS:
                size = INSTR_CELLS
            else:
                raise ValueError(f'unknown instruction "{name}"')
            if addr + size > MEM_SIZE:
                raise ValueError(f'the program does not fit into memory ({MEM_SIZE} cells)')
            if size:
                statements.append((number, addr, name, ops))
            addr += size
        except ValueError as exc:
            raise AsmError(number, str(exc)) from exc

    # Pass 2: replace labels with addresses and generate machine words.
    for number, addr, name, ops in statements:
        try:
            for op in ops:
                if isinstance(op.value, str):
                    if op.value not in program.labels:
                        raise ValueError(f'unknown label "{op.value}"')
                    op.value = program.labels[op.value]
            if name == '.WORD':
                words = [op.value for op in ops]
                if any(word > WORD_MASK for word in words):
                    raise ValueError(f'a data word must be in 0..{WORD_MASK}')
            else:
                ins = build(name, ops)
                if ins.a3 > A3_MASK:
                    raise ValueError(f'number or address {ins.a3} does not fit into 12 bits '
                                     f'(0..{A3_MASK}); keep bigger constants in .word')
                code = encode(ins)
                words = [code >> 16, code & WORD_MASK]
                program.lines[addr] = number
            for offset, word in enumerate(words):
                if addr + offset in program.image:
                    raise ValueError(f'cell 0x{addr + offset:03X} is already occupied')
                program.image[addr + offset] = word
            program.listing.append((addr, words, source[number - 1].strip()))
        except ValueError as exc:
            raise AsmError(number, str(exc)) from exc
    return program


def format_listing(program):
    """Address, machine code and source text of every statement, for the report."""
    rows = []
    for addr, words, text in program.listing:
        for start in range(0, len(words), 4):              # long .word lists wrap
            code = ' '.join(f'{word:04X}' for word in words[start:start + 4])
            rows.append(f'0x{addr + start:03X}  {code:<21}{text if start == 0 else ""}'.rstrip())
    return '\n'.join(rows)


if __name__ == '__main__':
    import sys
    print(format_listing(assemble(open(sys.argv[1], encoding='utf-8').read())))

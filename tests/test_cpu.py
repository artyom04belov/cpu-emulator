import random
import sys
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from assembler import AsmError, assemble, tokenize
from cpu import CPU, CPUError
from isa import INSTRUCTIONS, Instruction, IMM, REG, decode, disassemble, encode


def execute(text):
    program = assemble(text)
    cpu = CPU()
    cpu.reset(program.image)
    cpu.run()
    return program, cpu


def with_arrays(name, *arrays):
    """Example program with its .word arrays replaced (the size cell is added here)."""
    lines = (BASE / 'examples' / f'{name}.asm').read_text(encoding='utf-8').splitlines()
    arrays = iter(arrays)
    for i, line in enumerate(lines):
        label = line.split(':')[0]
        if label in ('arr', 'a', 'b'):
            data = next(arrays)
            lines[i] = f'{label}: .word ' + ', '.join(map(str, [len(data)] + data))
    return '\n'.join(lines)


class Programs(unittest.TestCase):
    def test_examples_as_shipped(self):
        program, cpu = execute((BASE / 'examples/maximum.asm').read_text(encoding='utf-8'))
        self.assertEqual(cpu.mem[program.labels['max']], 99)
        program, cpu = execute((BASE / 'examples/convolution.asm').read_text(encoding='utf-8'))
        total = [cpu.mem[program.labels[n]] for n in ('s_high', 's_mid', 's_low')]
        self.assertEqual(total[0] << 32 | total[1] << 16 | total[2], 11600168402)

    def test_maximum(self):
        rng = random.Random(1)
        cases = [[], [0], [65535] * 6, [1, 2, 3, 4, 5, 6], [6, 5, 4, 3, 2, 1]]
        cases += [[rng.randrange(65536) for _ in range(rng.randint(1, 15))] for _ in range(60)]
        for data in cases:
            program, cpu = execute(with_arrays('maximum', data))
            self.assertEqual(cpu.mem[program.labels['max']], max(data, default=0), data)

    def test_convolution(self):
        rng = random.Random(2)
        cases = [([65535] * 6, [65535] * 6), ([0] * 6, [7] * 6), ([], [])]
        cases += [([rng.randrange(65536) for _ in range(6)], [rng.randrange(65536) for _ in range(6)])
                  for _ in range(60)]
        for a, b in cases:
            program, cpu = execute(with_arrays('convolution', a, b))
            got = [cpu.mem[program.labels[n]] for n in ('s_high', 's_mid', 's_low')]
            self.assertEqual(got[0] << 32 | got[1] << 16 | got[2], sum(x * y for x, y in zip(a, b)))


class Machine(unittest.TestCase):
    def test_addressing_modes(self):
        _, cpu = execute('''
            MOV R1, 7           ; immediate
            MOV R2, R1          ; register
            MOV R3, [cell]      ; direct
            MOV R4, cell
            MOV R5, [R4]        ; register-indirect
            MOV [out], R2
            ADD R4, R4, 2
            MOV [R4], R3
            HLT
            cell: .word 1234
            out:  .word 0, 0''')
        self.assertEqual(cpu.reg[1:6], [7, 7, 1234, cpu.reg[4], 1234])
        self.assertEqual(cpu.mem[cpu.reg[4] - 1:cpu.reg[4] + 1], [7, 1234])

    def test_flags_and_long_arithmetic(self):
        _, cpu = execute('''
            MOV R1, [big]
            ADD R2, R1, 1       ; 0xFFFF + 1 = 0 with carry
            ADC R3, R3, 0       ; carry goes to the next word
            MUL R4, R1, R1      ; 0xFFFF * 0xFFFF = 0xFFFE0001
            MULH R5, R1, R1
            SUB R6, R3, 2       ; 1 - 2: borrow, sign
            HLT
            big: .word 0xFFFF''')
        self.assertEqual(cpu.reg[2:7], [0, 1, 0x0001, 0xFFFE, 0xFFFF])
        self.assertEqual((cpu.z, cpu.c, cpu.s), (0, 1, 1))

    def test_shifts_and_logic(self):
        _, cpu = execute('MOV R1, 0xF0F\nSHL R2, R1, 4\nSHR R3, R1, 1\nAND R4, R1, 0xFF\n'
                         'OR R5, R1, 0xF0\nXOR R6, R1, R1\nHLT')
        self.assertEqual(cpu.reg[2:7], [0xF0F0, 0x787, 0x0F, 0xFFF, 0])
        self.assertEqual(cpu.z, 1)

    def test_jumps(self):
        _, cpu = execute('MOV R1, 3\nloop: ADD R2, R2, 5\nSUB R1, R1, 1\nJNZ loop\nCMP R2, 20\n'
                         'JC less\nMOV R3, 1\nless: HLT')
        self.assertEqual((cpu.reg[2], cpu.reg[3]), (15, 0))

    def test_code_is_data(self):
        """Von Neumann: an instruction is just a pair of words that MOV can overwrite."""
        _, cpu = execute('MOV R1, 0\nMOV [target], R1\nMOV [target2], R1\n'
                         'target: MOV R5, 9\ntarget2: .word 0\nHLT')
        self.assertEqual(cpu.reg[5], 0)

    def test_encode_decode_round_trip(self):
        for word, text in ((0x10023004, 'ADD R2, R3, R4'), (0x10123004, 'ADD R2, R3, 4'),
                           (0x0181_0107, 'MOV [0x107], R1'), (0x0132_0000, 'MOV R2, [R0]'),
                           (0x3210_000A, 'JNZ 0x00A'), (0x1600_1003, 'CMP R1, R3')):
            self.assertEqual(disassemble(decode(word)), text)
            self.assertEqual(encode(decode(word)), word)
        self.assertEqual(encode(Instruction('ADD', REG, IMM, 1, 2, 5)), 0x10112005)
        self.assertEqual(len({code for code, _, _ in INSTRUCTIONS.values()}), len(INSTRUCTIONS))

    def test_lexer(self):
        self.assertEqual(tokenize('loop: mov r1, [0x10] ; note'),
                         [('name', 'loop'), (':', ':'), ('name', 'mov'), ('reg', 1), (',', ','),
                          ('[', '['), ('number', 16), (']', ']')])

    def test_assembler_errors(self):
        for text in ('ADD R1, R2', 'ADD R1, [R2], R3', 'ADD R1, R2, [5]', 'MOV [1], [2]', 'MOV [1], 5',
                     'MOV 5, R1', 'MOV R16, 1', 'JMP nowhere', 'x: HLT\nx: HLT', 'MOV R1, 4096',
                     '.word 65536', 'FOO R1', 'MOV R1, R2,', 'JMP R1', 'MOV R1, 12abc', 'HLT: HLT',
                     '.org 0\n.word 1\n.org 0\n.word 2', 'MOV R1 R2', 'CMP 1, R2'):
            with self.subTest(text=text), self.assertRaises(AsmError):
                assemble(text)

    def test_runtime_errors(self):
        for text in ('MOV R1, [big]\nMOV R2, [R1]\nHLT\nbig: .word 5000',   # address outside memory
                     'loop: JMP loop',                                       # endless loop
                     '.word 0xAB00, 0',                                      # unknown opcode
                     '.word 0x1020, 0'):                                     # ADD with memory operand
            with self.subTest(text=text), self.assertRaises(CPUError):
                execute(text)


if __name__ == '__main__':
    unittest.main()

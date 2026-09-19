import random
import unittest
from pathlib import Path
from core import CPU, assemble, MASK

BASE = Path(__file__).resolve().parents[1]

class Tests(unittest.TestCase):
    def execute(self, text):
        p = assemble(text)
        c = CPU(p)
        c.run()
        return p, c

    def test_maximum(self):
        source = (BASE / 'examples/maximum.asm').read_text()
        rng = random.Random(12)
        for a in [[0]*6, [MASK]*6, [6,5,4,3,2,1]] + [[rng.randrange(MASK+1) for _ in range(6)] for _ in range(40)]:
            p, c = self.execute(source.replace('12, 7, 99, 4, 31, 18', ', '.join(map(str, a))))
            self.assertEqual(c.memory[p.labels['result']], max(a))

    def test_convolution(self):
        source = (BASE / 'examples/convolution.asm').read_text()
        rng = random.Random(42)
        for _ in range(40):
            a, b = [[rng.randrange(MASK+1) for _ in range(6)] for _ in range(2)]
            text = source.replace('1, 2, 3, 4, 5, 6', ', '.join(map(str, a))).replace('6, 5, 4, 3, 2, 1', ', '.join(map(str, b)))
            p, c = self.execute(text)
            expected = [sum(a[i]*b[k-i] for i in range(6) if 0 <= k-i < 6) & MASK for k in range(11)]
            self.assertEqual(c.memory[p.labels['result']:p.labels['result']+11], expected)

    def test_stages_and_overflow(self):
        p = assemble('MOV R0, n\nADD R0, #1\nHALT\nn: .word 4294967295')
        c = CPU(p)
        c.step()
        self.assertEqual(c.r[0], 0)
        self.assertEqual(c.phase, 'Декодирование')
        c.step()
        self.assertEqual(c.r[0], 0)
        c.step()
        self.assertEqual(c.r[0], MASK)
        c.run()
        self.assertEqual(c.r[0], 0)
        self.assertTrue(c.c)
        self.assertTrue(c.z)

    def test_errors(self):
        for text in ['MOV #1, R0', 'MOV R8, #1', 'JMP missing', 'x: HALT\nx: HALT', '.word -1', 'MOV R0, #1024']:
            with self.subTest(text=text), self.assertRaises(ValueError):
                assemble(text)
        with self.assertRaises(ValueError):
            self.execute('MOV R0, #256\nMOV R1, [R0]\nHALT')

    def test_shared_memory(self):
        p, c = self.execute('MOV target, #0\nJMP target\ntarget: MOV R0, #9\nHALT')
        self.assertEqual(c.r[0], 0)
        self.assertEqual(c.memory[p.labels['target']], 0)

if __name__ == '__main__':
    unittest.main()

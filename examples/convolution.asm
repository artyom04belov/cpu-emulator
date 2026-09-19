; Линейная свёртка: result[i+j] += a[i] * b[j]
; Очистка результата позволяет повторно запустить программу
MOV R0, #result
MOV R1, #11
clear:
MOV [R0], #0
ADD R0, #1
SUB R1, #1
JNZ clear
MOV R0, #a
MOV R2, #0
outer:
MOV R1, #b
MOV R3, #0
inner:
MOV R4, [R0]
MUL R4, [R1]
MOV R5, #result
ADD R5, R2
ADD R5, R3
ADD [R5], R4
ADD R1, #1
ADD R3, #1
CMP R3, #6
JB inner
ADD R0, #1
ADD R2, #1
CMP R2, #6
JB outer
HALT
a: .word 1, 2, 3, 4, 5, 6
b: .word 6, 5, 4, 3, 2, 1
result: .word 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0

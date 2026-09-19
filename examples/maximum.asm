; Максимум массива из 6 беззнаковых чисел
MOV R0, #array
MOV R1, [R0]
MOV R2, #5
ADD R0, #1
loop:
CMP [R0], R1
JA update
JMP next
update:
MOV R1, [R0]
next:
ADD R0, #1
SUB R2, #1
JNZ loop
MOV result, R1
HALT
array: .word 12, 7, 99, 4, 31, 18
result: .word 0

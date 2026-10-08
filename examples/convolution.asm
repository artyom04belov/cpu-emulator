; Task 2. Convolution of two arrays: S = A1*B1 + A2*B2 + ... + AN*BN.
; Unsigned 16-bit numbers. One product needs 32 bits and the sum of six
; products needs up to 35, so S is kept in three words (48 bits) and is
; computed with long arithmetic: MUL/MULH give the two halves of a product,
; ADD/ADC/ADC carry the overflow from word to word.
;   R0, R1 - pointers into A and B      R2 - counter
;   R3, R4 - current elements           R5, R6 - low and high half of the product
;   R7 : R8 : R9 - the sum S (low : middle : high word)

        MOV  R0, a
        MOV  R1, b
        MOV  R2, [R0]       ; size (the first cell of A)
        MOV  R7, 0
        MOV  R8, 0
        MOV  R9, 0
        CMP  R2, 0
        JZ   done
loop:   ADD  R0, R0, 1
        ADD  R1, R1, 1
        MOV  R3, [R0]       ; A[i]
        MOV  R4, [R1]       ; B[i]
        MUL  R5, R3, R4     ; low 16 bits of A[i] * B[i]
        MULH R6, R3, R4     ; high 16 bits
        ADD  R7, R7, R5     ; low words; C = carry out
        ADC  R8, R8, R6     ; middle words + carry
        ADC  R9, R9, 0      ; high word takes the last carry
        SUB  R2, R2, 1
        JNZ  loop
done:   MOV  [s_low], R7
        MOV  [s_mid], R8
        MOV  [s_high], R9
        HLT

        .org 0x100
a:      .word 6, 50000, 60000, 65535, 1234, 7, 40000
b:      .word 6, 50000, 60000, 65535, 4321, 9, 30000
s_low:  .word 0             ; S = s_high : s_mid : s_low
s_mid:  .word 0
s_high: .word 0

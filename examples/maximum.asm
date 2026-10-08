; Task 1. Maximum of an array of unsigned numbers.
; The first cell of the array holds its size.
;   R0 - pointer to the current element
;   R1 - accumulator: the maximum found so far
;   R2 - counter: elements left to check
;   R3 - the current element

        MOV  R0, arr        ; immediate: R0 = address of the array
        MOV  R2, [R0]       ; register-indirect: R2 = size
        MOV  R1, 0          ; unsigned numbers: nothing is smaller than 0
        CMP  R2, 0
        JZ   done           ; empty array
loop:   ADD  R0, R0, 1      ; move to the next element
        MOV  R3, [R0]       ; read it
        CMP  R1, R3         ; max - element; C = 1 means max < element
        JNC  next           ; max >= element: keep the maximum
        MOV  R1, R3         ; register: new maximum
next:   SUB  R2, R2, 1
        JNZ  loop
done:   MOV  [max], R1      ; direct: save the answer
        HLT

        .org 0x100
arr:    .word 6, 12, 7, 99, 4, 31, 18
max:    .word 0

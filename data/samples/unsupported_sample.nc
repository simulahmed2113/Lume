(Unsupported code sample)
G21
G90
G0 X0 Y0
G1 Z-0.5 F150
G999 X10 Y10  ; unsupported G-code should be reported
M3 S1000
M99          ; unsupported M-code should be reported
G0 Z5
M5
M2

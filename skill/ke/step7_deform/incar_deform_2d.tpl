# =====================================================================
# incar_deform_3d.tpl —— 形变势单点（2D）。每个 deform-NN / undeformed 一份。
# 固定结构单点，收紧 EDIFF 取精确带边能量。占位符：{{SYSTEM}} {{ENCUT}} {{GGA}}
# =====================================================================
SYSTEM = {{SYSTEM}}

ISTART = 0
ICHARG = 2
GGA    = {{GGA}}
{{VDW_LINE}}

PREC   = Accurate
ENCUT  = {{ENCUT}}
LREAL  = .FALSE.
LASPH  = .TRUE.

ALGO   = Normal
EDIFF  = 1E-7          # 带边能量差，收紧
NELM   = 200
NELMIN = 6
AMIN   = 0.01          # 2D 长真空层电子步稳定
ISMEAR = 0
SIGMA  = 0.05

IBRION = -1            # 单点，不动离子
NSW    = 0
ISIF   = 2
ISYM   = 2

LWAVE  = .FALSE.
LCHARG = .FALSE.
LORBIT = 0

NCORE  = 6
KPAR   = 2

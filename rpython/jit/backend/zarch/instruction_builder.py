from rpython.jit.backend.zarch.instructions import (all_mnemonic_codes,)
from rpython.rtyper.lltypesystem.rbuilder import always_inline
from rpython.rlib.unroll import unrolling_iterable
from rpython.jit.backend.zarch import locations as loc

def dummy_argument(arg):
    """ NOT_RPYTHON """
    if arg in ('r', 'r/m', 'm', 'f', '-', 'eo'):
        return 0
    if arg.startswith('i') or arg.startswith('u'):
        return 0
    if arg.startswith('h'):
        return 0
    return loc.addr(0)

class builder(object):
    """ NOT_RPYTHON """
    @staticmethod
    def arguments(args_str):
        """ NOT_RPYTHON """
        """
        Available names:
        -      - unused
        f      - floating point register
        r      - register
        m      - mask
        eo     - even odd pair (= the even register)
        r/m    - register or mask
        iX     - immediate X bits (signed)
        uX     - immediate X bits (unsigend)
        bd     - base displacement (unsigned 12 bit)
        bdl    - base displacement long (20 bit)
        bid    - index base displacement (unsigned 12 bit)
        bidl   - index base displacement (20 bit)
        l4bd   - length base displacement (4 bit)
        l8bd   - length base displacement (8 bit)
        h32    - halfwords 32 bit (e.g. LARL, or other relative instr.)

        note that a suffix 'l' means long, and a prefix length
        """
        class Counter(object):
            def __init__(self):
                self.counter = 0
            def writechar(self, char):
                self.counter += 1
            def write_i16(self, _):
                self.counter += 2
            def write_i32(self, _):
                self.counter += 4
        def impl(func):
            func._arguments_ = args_str.split(',')
            if args_str == '':
                func._arguments_ = []
            args = [dummy_argument(a) for a in func._arguments_]
            c = Counter()
            # invoke it once and get the amount of bytes
            func(c, *args)
            func._byte_count = c.counter
            return func
        return impl

BIT_MASK_4 =  0xF
BIT_MASK_12 = 0xFFF
BIT_MASK_16 = 0xFFFF
BIT_MASK_20 = 0xFFFFF
BIT_MASK_32 = 0xFFFFFFFF

@always_inline
def encode_base_displace(mc, base_displace):
    """
        +---------------------------------+
        | ... | base | length[0:11] | ... |
        +---------------------------------+
    """
    displace = base_displace.displace
    base = base_displace.base & 0xf
    byte = (displace >> 8 & 0xf) | base << 4
    mc.writechar(chr(byte))
    mc.writechar(chr(displace & 0xff))

@always_inline
def encode_base_displace_long(mc, basedisp):
    """
        +-------------------------------------------------+
        | ... | base | length[0:11] | length[12:20] | ... |
        +-------------------------------------------------+
    """
    displace = basedisp.displace & BIT_MASK_20
    base = basedisp.base & 0xf
    byte = (displace >> 8) & 0xf | base << 4
    mc.writechar(chr(byte))
    mc.writechar(chr(displace & 0xff))
    byte = displace >> 12 & 0xff
    mc.writechar(chr(byte))

@always_inline
def encode_index_base_displace(mc, reg, idxbasedisp):
    """
        +----------------------------------------------------+
        | opcode | reg & index | base & displace[0:11] | ... |
        +----------------------------------------------------+
    """
    index = idxbasedisp.index
    byte = (reg & 0x0f) << 4 | index & 0xf
    mc.writechar(chr(byte))
    displace = idxbasedisp.displace & BIT_MASK_12
    base = idxbasedisp.base & 0xf
    byte = displace >> 8 & 0xf | base << 4
    mc.writechar(chr(byte))
    mc.writechar(chr(displace & 0xff))

def build_e(mnemonic, (opcode1,opcode2)):
    @builder.arguments('')
    def encode_e(self):
        self.writechar(opcode1)
        self.writechar(opcode2)
    return encode_e

def build_i(mnemonic, (opcode,)):
    @builder.arguments('u8')
    def encode_i(self, imm):
        self.writechar(opcode)
        self.writechar(chr(imm))
    return encode_i

def build_rr(mnemonic, (opcode,), argtypes='r,r'):
    @builder.arguments(argtypes)
    def encode_rr(self, reg1, reg2):
        self.writechar(opcode)
        operands = ((reg1 & 0x0f) << 4) | (reg2 & 0xf)
        self.writechar(chr(operands))
    return encode_rr

def build_rre(mnemonic, (opcode1,opcode2), argtypes='r,r'):
    @builder.arguments(argtypes)
    def encode_rre(self, reg1, reg2):
        self.writechar(opcode1)
        self.writechar(opcode2)
        self.writechar('\x00')
        operands = ((reg1 & 0x0f) << 4) | (reg2 & 0xf)
        self.writechar(chr(operands))
    return encode_rre

def build_rx(mnemonic, (opcode,)):
    @builder.arguments('r/m,bid')
    def encode_rx(self, reg_or_mask, idxbasedisp):
        self.writechar(opcode)
        encode_index_base_displace(self, reg_or_mask, idxbasedisp)
    return encode_rx

def build_rxy(mnemonic, (opcode1,opcode2), arguments='r/m,bidl'):
    @builder.arguments(arguments)
    def encode_rxy(self, reg_or_mask, idxbasedisp):
        self.writechar(opcode1)
        index = idxbasedisp.index
        byte = (reg_or_mask & 0x0f) << 4 | index & 0xf
        self.writechar(chr(byte))
        encode_base_displace_long(self, idxbasedisp)
        self.writechar(opcode2)
    return encode_rxy

def build_ri(mnemonic, (opcode,halfopcode)):
    br = is_branch_relative(mnemonic)
    @builder.arguments('r/m,i16')
    def encode_ri(self, reg_or_mask, imm16):
        self.writechar(opcode)
        byte = (reg_or_mask & 0xf) << 4 | (ord(halfopcode) & 0xf)
        self.writechar(chr(byte))
        if br:
            imm16 = imm16 >> 1
        self.writechar(chr(imm16 >> 8 & 0xff))
        self.writechar(chr(imm16 & 0xff))
    return encode_ri

def build_ri_u(mnemonic, (opcode,halfopcode)):
    # unsigned version of ri
    func = build_ri(mnemonic, (opcode,halfopcode))
    func._arguments_[1] = 'u16'
    return func

def build_ril(mnemonic, (opcode,halfopcode), args='r/m,i32'):
    br = is_branch_relative(mnemonic)
    @builder.arguments(args)
    def encode_ri(self, reg_or_mask, imm32):
        self.writechar(opcode)
        byte = (reg_or_mask & 0xf) << 4 | (ord(halfopcode) & 0xf)
        self.writechar(chr(byte))
        if br:
            imm32 = imm32 >> 1
        # half word boundary, addressing bytes
        self.write_i32(imm32 & BIT_MASK_32)
    return encode_ri

def build_s(mnemonic, (opcode1,opcode2)):
    @builder.arguments('bd')
    def encode_s(self, base_displace):
        self.writechar(opcode1)
        self.writechar(opcode2)
        encode_base_displace(self, base_displace)
    return encode_s

def build_si(mnemonic, (opcode,)):
    @builder.arguments('bd,u8')
    def encode_si(self, base_displace, uimm8):
        self.writechar(opcode)
        self.writechar(chr(uimm8))
        encode_base_displace(self, base_displace)
    return encode_si

def build_siy(mnemonic, (opcode1,opcode2)):
    @builder.arguments('bd,u8')
    def encode_siy(self, base_displace, uimm8):
        self.writechar(opcode1)
        self.writechar(chr(uimm8))
        encode_base_displace(self, base_displace)
        displace = base_displace.displace
        self.writechar(chr(displace >> 12 & 0xff))
        self.writechar(opcode2)
    return encode_siy

def build_ssa(mnemonic, (opcode1,)):
    @builder.arguments('l8bd,bd')
    def encode_ssa(self, len_base_disp, base_displace):
        self.writechar(opcode1)
        self.writechar(chr(len_base_disp.length & 0xff))
        encode_base_displace(self, len_base_disp)
        encode_base_displace(self, base_displace)
    return encode_ssa

def build_ssb(mnemonic, (opcode1,)):
    @builder.arguments('l8bd,l8bd')
    def encode_ssb(self, len_base_disp1, len_base_disp2):
        self.writechar(opcode1)
        byte = (len_base_disp1.length & 0xf) << 4 | len_base_disp2.length & 0xf
        self.writechar(chr(byte))
        encode_base_displace(self, len_base_disp1)
        encode_base_displace(self, len_base_disp2)
    return encode_ssb

def build_ssc(mnemonic, (opcode1,)):
    @builder.arguments('l4bd,bd,u4')
    def encode_ssc(self, len_base_disp, base_disp, uimm4):
        self.writechar(opcode1)
        byte = (len_base_disp.length & 0xf) << 4 | uimm4 & 0xf
        self.writechar(chr(byte))
        encode_base_displace(self, len_base_disp)
        encode_base_displace(self, base_disp)
    return encode_ssc

def build_ssd(mnemonic, (opcode,)):
    @builder.arguments('bid,bd,r')
    def encode_ssd(self, index_base_disp, base_disp, reg):
        self.writechar(opcode)
        byte = (index_base_disp.index & 0xf) << 4 | reg & 0xf
        self.writechar(chr(byte))
        encode_base_displace(self, index_base_disp)
        encode_base_displace(self, base_disp)
    return encode_ssd

def build_sse(mnemonic, (opcode,)):
    @builder.arguments('r,r,bd,bd')
    def encode_sse(self, reg1, reg3, base_disp2, base_disp4):
        self.writechar(opcode)
        byte = (reg1 & BIT_MASK_4) << 4 | reg3 & BIT_MASK_4
        self.writechar(chr(byte))
        encode_base_displace(self, base_disp2)
        encode_base_displace(self, base_disp4)
    return encode_sse

def build_ssf(mnemonic, (opcode,)):
    @builder.arguments('bd,l8bd')
    def encode_ssf(self, base_disp, len_base_disp):
        self.writechar(opcode)
        self.writechar(chr(len_base_disp.length & 0xff))
        encode_base_displace(self, base_disp)
        encode_base_displace(self, len_base_disp)
    return encode_ssf

def build_rs(mnemonic, (opcode,), argtypes='r,r,bd'):
    @builder.arguments(argtypes)
    def encode_rs(self, reg1, reg3, base_displace):
        self.writechar(opcode)
        self.writechar(chr((reg1 & BIT_MASK_4) << 4 | reg3 & BIT_MASK_4))
        encode_base_displace(self, base_displace)
    return encode_rs

@always_inline
def _encode_rsy(self, opcode1, opcode2, reg1, reg3, base_displace):
    self.writechar(opcode1)
    self.writechar(chr((reg1 & BIT_MASK_4) << 4 | reg3 & BIT_MASK_4))
    encode_base_displace_long(self, base_displace)
    self.writechar(opcode2)

def build_rsy_a(mnemonic, (opcode1,opcode2)):
    @builder.arguments('r,r,bdl')
    def encode_rsy(self, reg1, reg3, base_displace):
        _encode_rsy(self, opcode1, opcode2, reg1, reg3, base_displace)
    return encode_rsy

def build_rsy_b(mnemonic, (opcode1,opcode2)):
    @builder.arguments('r,bdl,r')
    def encode_rsy(self, reg1, base_displace, reg3):
        _encode_rsy(self, opcode1, opcode2, reg1, reg3, base_displace)
    return encode_rsy

def build_rsi(mnemonic, (opcode,)):
    br = is_branch_relative(mnemonic)
    @builder.arguments('r,r,i16')
    def encode_ri(self, reg1, reg2, imm16):
        self.writechar(opcode)
        byte = (reg1 & BIT_MASK_4) << 4 | (reg2 & BIT_MASK_4)
        self.writechar(chr(byte))
        if br:
            imm16 = imm16 >> 1
        self.write_i16(imm16 & BIT_MASK_16)
    return encode_ri

def build_rie_d(mnemonic, (opcode1,opcode2)):
    @builder.arguments('r,r,i16')
    def encode_rie_d(self, reg1, reg2, imm16):
        self.writechar(opcode1)
        byte = (reg1 & BIT_MASK_4) << 4 | (reg2 & BIT_MASK_4)
        self.writechar(chr(byte))
        self.write_i16(imm16 & BIT_MASK_16)
        self.writechar(chr(0x0))
        self.writechar(opcode2)
    return encode_rie_d

def build_rie_e(mnemonic, (opcode1,opcode2)):
    br = is_branch_relative(mnemonic)
    @builder.arguments('r,r,i16')
    def encode_rie_e(self, reg1, reg2, imm16):
        self.writechar(opcode1)
        byte = (reg1 & BIT_MASK_4) << 4 | (reg2 & BIT_MASK_4)
        self.writechar(chr(byte))
        if br:
            imm16 = imm16 >> 1
        self.write_i16(imm16 & BIT_MASK_16)
        self.writechar(chr(0x0))
        self.writechar(opcode2)
    return encode_rie_e

def build_rie_f(mnemonic, (opcode1,opcode2)):
    @builder.arguments('r,r,i8,i8,i8')
    def encode_rie_f(self, reg1, reg2, i1, i2, i3):
        self.writechar(opcode1)
        byte = (reg1 & BIT_MASK_4) << 4 | (reg2 & BIT_MASK_4)
        self.writechar(chr(byte))
        self.writechar(chr(i1))
        self.writechar(chr(i2))
        self.writechar(chr(i3))
        self.writechar(opcode2)
    return encode_rie_f

def build_rie_a(mnemonic, (opcode1,opcode2)):
    br = is_branch_relative(mnemonic)
    @builder.arguments('r,i16,r/m')
    def encode_rie_a(self, reg1, imm16, mask):
        self.writechar(opcode1)
        byte = (reg1 & BIT_MASK_4) << 4 | (mask & BIT_MASK_4)
        self.writechar(chr(byte))
        if br:
            imm16 = imm16 >> 1
        self.write_i16(imm16 & BIT_MASK_16)
        self.writechar(chr(0x0))
        self.writechar(opcode2)
    return encode_rie_a

build_rie_g = build_rie_a

def build_rie_b(mnemonic, (opcode1,opcode2)):
    br = is_branch_relative(mnemonic)
    @builder.arguments('r,r,r/m,i16')
    def encode_rie_b(self, reg1, reg2, mask, imm16):
        self.writechar(opcode1)
        byte = (reg1 & BIT_MASK_4) << 4 | (reg2 & BIT_MASK_4)
        self.writechar(chr(byte))
        if br:
            imm16 = imm16 >> 1
        self.write_i16(imm16 & BIT_MASK_16)
        byte = (mask & BIT_MASK_4) << 4
        self.writechar(chr(byte))
        self.writechar(opcode2)
    return encode_rie_b

def build_rie_c(mnemonic, (opcode1,opcode2), argtypes='r,i8,r/m,i16'):
    br = is_branch_relative(mnemonic)
    @builder.arguments(argtypes)
    def encode_rie_c(self, reg1, imm8, mask, imm16):
        self.writechar(opcode1)
        byte = (reg1 & BIT_MASK_4) << 4 | (mask & BIT_MASK_4)
        self.writechar(chr(byte))
        if br:
            imm16 = imm16 >> 1
        self.write_i16(imm16 & BIT_MASK_16)
        self.writechar(chr(imm8 & 0xff))
        self.writechar(opcode2)
    return encode_rie_c

@always_inline
def _encode_rrf(self, opcode1, opcode2, r1, r2, rm3, rm4):
    self.writechar(opcode1)
    self.writechar(opcode2)
    byte = (rm3 & BIT_MASK_4) << 4 | (rm4 & BIT_MASK_4)
    self.writechar(chr(byte))
    byte = (r1 & BIT_MASK_4) << 4 | (r2 & BIT_MASK_4)
    self.writechar(chr(byte))

def build_rrf_a(mnemonic, (opcode1,opcode2), argtypes='r,r,r'):
    @builder.arguments(argtypes)
    def encode_rrf_a(self, r1, r2, r3):
        _encode_rrf(self, opcode1, opcode2, r1, r2, r3, 0)
    return encode_rrf_a

def build_rrf_c(mnemonic, (opcode1,opcode2), argtypes='r,r,r/m,-'):
    @builder.arguments(argtypes)
    def encode_rrf_b(self, r1, r2, rm3, rm4):
        _encode_rrf(self, opcode1, opcode2, r1, r2, rm3, rm4)
    return encode_rrf_b

def build_rrf_e(mnemonic, (opcode1,opcode2), argtypes):
    @builder.arguments(argtypes)
    def encode_rrf_e(self, r1, rm3, r2, rm4):
        _encode_rrf(self, opcode1, opcode2, r1, r2, rm3, rm4)
    return encode_rrf_e
build_rrf_b = build_rrf_e

def build_rxe(mnemonic, (opcode1,opcode2), argtypes):
    @builder.arguments(argtypes)
    def encode_rxe(self, reg, idxbasedisp, mask):
        self.writechar(opcode1)
        encode_index_base_displace(self, reg, idxbasedisp)
        self.writechar(chr((mask & 0xf) << 4))
        self.writechar(opcode2)
    return encode_rxe

def build_rxf(mnemonic, (opcode1,opcode2)):
    @builder.arguments('r,bidl,r/m')
    def encode_rxe(self, reg1, idxbasedisp, reg3):
        self.writechar(opcode1)
        index = idxbasedisp.index
        byte = (reg3 & 0x0f) << 4 | index & 0xf
        self.writechar(chr(byte))
        encode_base_displace_long(self, reg, idxbasedisp)
        self.writechar(chr((reg1 & 0xf) << 4))
        self.writechar(opcode2)
    return encode_rxe

def build_ris(mnemonic, (opcode1,opcode2), argtypes='r,i8,r/m,bd'):
    br = is_branch_relative(mnemonic)
    @builder.arguments(argtypes)
    def encode_rie_c(self, reg1, imm8, mask, basedisp):
        self.writechar(opcode1)
        byte = (reg1 & BIT_MASK_4) << 4 | (mask & BIT_MASK_4)
        self.writechar(chr(byte))
        #
        encode_base_displace(self, basedisp)
        self.writechar(chr(imm8 & 0xff))
        self.writechar(opcode2)
    return encode_rie_c

def build_unpack_func(mnemonic, func):
    @always_inline
    def unpack_arg(arg, argtype):
        if argtype == '-':
            return 0
        elif argtype == 'r' or argtype == 'r/m' or \
             argtype == 'f' or argtype == 'eo':
            return arg.value
        elif argtype.startswith('i') or argtype.startswith('u') or argtype.startswith('h'):
            return arg.value
        else:
            return arg
    unpack_arg._annspecialcase_ = 'specialize:arg(1)'
    argtypes = func._arguments_[:]
    #while len(argtypes) > 0 and argtypes[-1] == '-':
    #    argtypes.pop()
    at = argtypes[0] if len(argtypes) >= 1 else '-'
    bt = argtypes[1] if len(argtypes) >= 2 else '-'
    ct = argtypes[2] if len(argtypes) >= 3 else '-'
    dt = argtypes[3] if len(argtypes) >= 4 else '-'
    def function0(self):
        return func(self)
    def function1(self, a):
        e = unpack_arg(a, at)
        return func(self, e)
    def function2(self, a, b):
        e = unpack_arg(a, at)
        f = unpack_arg(b, bt)
        return func(self, e, f)
    def function2_last_default(self, a):
        e = unpack_arg(a, at)
        return func(self, e, 0)
    def function3(self, a, b, c):
        e = unpack_arg(a, at)
        f = unpack_arg(b, bt)
        g = unpack_arg(c, ct)
        return func(self, e, f, g)
    def function3_last_default(self, a, b):
        e = unpack_arg(a, at)
        f = unpack_arg(b, bt)
        return func(self, e, f, 0)
    def function4(self, a, b, c, d):
        e = unpack_arg(a, at)
        f = unpack_arg(b, bt)
        g = unpack_arg(c, ct)
        h = unpack_arg(d, dt)
        return func(self, e, f, g, h)
    def function4_last_default(self, a, b, c):
        e = unpack_arg(a, at)
        f = unpack_arg(b, bt)
        g = unpack_arg(c, ct)
        return func(self, e, f, g, 0)
    if len(argtypes) == 0:
        function = function0
    elif len(argtypes) == 1:
        function = function1
    elif len(argtypes) == 2:
        function = function2
        if argtypes[1] == '-':
            # e.g. SPM/IPM
            function = function2_last_default
    elif len(argtypes) == 3:
        function = function3
        if argtypes[2] == '-':
            # e.g. FIEBR or CGEBR ignore the last element
            function = function3_last_default
    elif len(argtypes) == 4:
        function = function4
        if argtypes[3] == '-':
            # e.g. FIEBR or CGEBR ignore the last element
            function = function4_last_default
    else:
        assert 0, "implement function for argtypes %s" % (argtypes,)
    function.__name__ = mnemonic
    return function

def is_branch_relative(name):
    return name.startswith('BR') or name.endswith('J')

def build_instr_codes(clazz):
    for mnemonic, params in all_mnemonic_codes.items():
        argtypes = None
        if len(params) == 2:
            (instrtype, args) = params
        else:
            (instrtype, args, argtypes) = params
        builder = globals()['build_' + instrtype]
        if argtypes:
            func = builder(mnemonic, args, argtypes)
        else:
            func = builder(mnemonic, args)
        name = mnemonic + "_" + instrtype
        setattr(clazz, name, func)
        setattr(clazz, mnemonic, build_unpack_func(mnemonic, func))
        setattr(clazz, mnemonic + '_byte_count', func._byte_count)
        del func._byte_count

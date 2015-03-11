import logging

import barf

from barf.arch.translator import Label
from barf.arch.translator import TranslationBuilder

from barf.arch import ARCH_X86_MODE_32
from barf.arch import ARCH_X86_MODE_64
from barf.arch.x86.x86base import X86ArchitectureInformation
from barf.arch.x86.x86base import X86ImmediateOperand
from barf.arch.x86.x86base import X86MemoryOperand
from barf.arch.x86.x86base import X86RegisterOperand
from barf.core.reil import ReilEmptyOperand
from barf.core.reil import ReilImmediateOperand
from barf.core.reil import ReilInstructionBuilder
from barf.core.reil import ReilInstruction
from barf.core.reil import ReilMnemonic
from barf.core.reil import ReilRegisterOperand
from barf.utils.utils import VariableNamer

FULL_TRANSLATION = 0
LITE_TRANSLATION = 1

logger = logging.getLogger(__name__)


class X86TranslationBuilder(TranslationBuilder):

    def __init__(self, ir_name_generator, architecture_mode):
        super(X86TranslationBuilder, self).__init__(ir_name_generator, architecture_mode)

        self._arch_info = X86ArchitectureInformation(architecture_mode)

        self._regs_mapper = self._arch_info.registers_access_mapper()

        self._regs_size = self._arch_info.registers_size

    def read(self, x86_operand):

        if isinstance(x86_operand, barf.arch.x86.x86base.X86ImmediateOperand):

            reil_operand = ReilImmediateOperand(x86_operand.immediate, x86_operand.size)

        elif isinstance(x86_operand, barf.arch.x86.x86base.X86RegisterOperand):

            reil_operand = ReilRegisterOperand(x86_operand.name, x86_operand.size)

        elif isinstance(x86_operand, barf.arch.x86.x86base.X86MemoryOperand):

            addr = self._compute_memory_address(x86_operand)

            reil_operand = self.temporal(x86_operand.size)

            self.add(self._builder.gen_ldm(addr, reil_operand))

        else:
            raise Exception()

        return reil_operand

    def write(self, x86_operand, value):

        if isinstance(x86_operand, barf.arch.x86.x86base.X86RegisterOperand):

            reil_operand = ReilRegisterOperand(x86_operand.name, x86_operand.size)

            if self._arch_info.architecture_mode == ARCH_X86_MODE_64 and \
                x86_operand.size == 32:
                if x86_operand.name in self._regs_mapper:
                    base_reg, offset = self._regs_mapper[x86_operand.name]

                    reil_operand_base = ReilRegisterOperand(base_reg, self._regs_size[base_reg])
                    reil_immediate = ReilImmediateOperand(0x0, self._regs_size[base_reg])

                    self.add(self._builder.gen_str(reil_immediate, reil_operand_base))

            self.add(self._builder.gen_str(value, reil_operand))

        elif isinstance(x86_operand, barf.arch.x86.x86base.X86MemoryOperand):

            addr = self._compute_memory_address(x86_operand)

            if value.size != x86_operand.size:
                tmp = self.temporal(x86_operand.size)

                self.add(self._builder.gen_str(value, tmp))

                self.add(self._builder.gen_stm(tmp, addr))
            else:
                self.add(self._builder.gen_stm(value, addr))

        else:
            raise Exception()

    def _compute_memory_address(self, mem_operand):
        """Return operand memory access translation.
        """
        size = self._arch_info.architecture_size

        addr = None

        if mem_operand.base:
            addr = ReilRegisterOperand(mem_operand.base, size)

        if mem_operand.index and mem_operand.scale != 0x0:
            index = ReilRegisterOperand(mem_operand.index, size)
            scale = ReilImmediateOperand(mem_operand.scale, size)
            scaled_index = self.temporal(size)

            self.add(self._builder.gen_mul(index, scale, scaled_index))

            if addr:
                tmp = self.temporal(size)

                self.add(self._builder.gen_add(addr, scaled_index, tmp))

                addr = tmp
            else:
                addr = scaled_index

        if mem_operand.displacement != 0x0:
            disp = ReilImmediateOperand(mem_operand.displacement, size)

            if addr:
                tmp = self.temporal(size)

                self.add(self._builder.gen_add(addr, disp, tmp))

                addr = tmp
            else:
                addr = disp
        else:
            if not addr:
                disp = ReilImmediateOperand(mem_operand.displacement, size)

                addr = disp

        return addr

def check_operands_size(instr, arch_size):
    if instr.mnemonic in [  ReilMnemonic.ADD, ReilMnemonic.SUB,
                            ReilMnemonic.MUL, ReilMnemonic.DIV,
                            ReilMnemonic.MOD,
                            ReilMnemonic.AND, ReilMnemonic.OR,
                            ReilMnemonic.XOR]:
        # operand0 : Source 1 (Literal or register)
        # operand1 : Source 2 (Literal or register)
        # operand2 : Destination resgister

        # Check that source operands have the same size.
        assert instr.operands[0].size == instr.operands[1].size, \
            "Invalid operands size: %s" % instr

    elif instr.mnemonic in [ReilMnemonic.BSH]:
        # operand0 : Source 1 (Literal or register)
        # operand1 : Source 2 (Literal or register)
        # operand2 : Destination resgister

        pass

    elif instr.mnemonic in [ReilMnemonic.LDM]:
        # operand0 : Source address (Literal or register)
        # operand1 : Empty register
        # operand2 : Destination register

        assert instr.operands[0].size == arch_size, \
            "Invalid operands size: %s" % instr

    elif instr.mnemonic in [ReilMnemonic.STM]:
        # operand0 : Value to store (Literal or register)
        # operand1 : Empty register
        # operand2 : Destination address (Literal or register)

        assert instr.operands[2].size == arch_size, \
            "Invalid operands size: %s" % instr

    elif instr.mnemonic in [ReilMnemonic.STR]:
        # operand0 : Value to store (Literal or register)
        # operand1 : Empty register
        # operand2 : Destination register

        pass

    elif instr.mnemonic in [ReilMnemonic.BISZ]:
        # operand0 : Value to compare (Literal or register)
        # operand1 : Empty register
        # operand2 : Destination register

        pass

    elif instr.mnemonic in [ReilMnemonic.JCC]:
        # operand0 : Condition (Literal or register)
        # operand1 : Empty register
        # operand2 : Destination register

        # FIX: operand2.size should be arch_size + 1 byte

        # assert instr.operands[2].size == arch_size + 8, \
        #     "Invalid operands size: %s" % instr

        pass

    elif instr.mnemonic in [ReilMnemonic.UNKN]:
        # operand0 : Empty register
        # operand1 : Empty register
        # operand2 : Empty register

        pass

    elif instr.mnemonic in [ReilMnemonic.UNDEF]:
        # operand0 : Empty register
        # operand1 : Empty register
        # operand2 : Destination register

        pass

    elif instr.mnemonic in [ReilMnemonic.NOP]:
        # operand0 : Empty register
        # operand1 : Empty register
        # operand2 : Empty register

        pass

class X86Translator(object):

    """x86 to IR Translator."""

    def __init__(self, architecture_mode=ARCH_X86_MODE_32, translation_mode=FULL_TRANSLATION):

        # Set *Architecture Mode*. The translation of each instruction
        # into the REIL language is based on this.
        self._arch_mode = architecture_mode

        # An instance of *ArchitectureInformation*.
        self._arch_info = X86ArchitectureInformation(architecture_mode)

        # Set *Translation Mode*.
        self._translation_mode = translation_mode

        # An instance of a *VariableNamer*. This is used so all the
        # temporary REIL registers are unique.
        self._ir_name_generator = VariableNamer("t", separator="")

        self._builder = ReilInstructionBuilder()

        self._flags = {
            "af" : ReilRegisterOperand("af", 1),
            "cf" : ReilRegisterOperand("cf", 1),
            "df" : ReilRegisterOperand("df", 1),
            "of" : ReilRegisterOperand("of", 1),
            "pf" : ReilRegisterOperand("pf", 1),
            "sf" : ReilRegisterOperand("sf", 1),
            "zf" : ReilRegisterOperand("zf", 1),
        }

        if self._arch_mode == ARCH_X86_MODE_32:
            self._sp = ReilRegisterOperand("esp", 32)
            self._bp = ReilRegisterOperand("ebp", 32)
            self._ip = ReilRegisterOperand("eip", 32)

            self._ws = ReilImmediateOperand(4, 32) # word size
        elif self._arch_mode == ARCH_X86_MODE_64:
            self._sp = ReilRegisterOperand("rsp", 64)
            self._bp = ReilRegisterOperand("rbp", 64)
            self._ip = ReilRegisterOperand("rip", 64)

            self._ws = ReilImmediateOperand(8, 64) # word size

    def translate(self, instruction):
        """Return IR representation of an instruction.
        """
        try:
            trans_instrs = self._translate(instruction)
        except NotImplementedError:
            trans_instrs = [self._builder.gen_unkn()]

            self._log_not_supported_instruction(instruction)
        except:
            self._log_translation_exception(instruction)

            raise

        # Some sanity check....
        for instr in trans_instrs:
            try:
                check_operands_size(instr, self._arch_info.architecture_size)
            except:
                logger.error(
                    "Invalid operand size: %s (%s)",
                    instr,
                    instruction
                )

                raise

        return trans_instrs

    def _translate(self, instruction):
        """Translate a x86 instruction into REIL language.

        :param instruction: a x86 instruction
        :type instruction: X86Instruction
        """
        # Retrieve translation function.
        translator_name = "_translate_" + instruction.mnemonic
        translator_fn = getattr(self, translator_name, self._not_implemented)

        # Translate instruction.
        tb = X86TranslationBuilder(self._ir_name_generator, self._arch_mode)

        translator_fn(tb, instruction)

        return tb.instanciate(instruction.address)

    def reset(self):
        """Restart IR register name generator.
        """
        self._ir_name_generator.reset()

    @property
    def translation_mode(self):
        """Get translation mode.
        """
        return self._translation_mode

    @translation_mode.setter
    def translation_mode(self, value):
        """Set translation mode.
        """
        self._translation_mode = value

    def _log_not_supported_instruction(self, instruction):
        bytes_str = " ".join("%02x" % ord(b) for b in instruction.bytes)

        logger.info(
            "Instruction not supported: %s (%s [%s])",
            instruction.mnemonic,
            instruction,
            bytes_str
        )

    def _log_translation_exception(self, instruction):
        bytes_str = " ".join("%02x" % ord(b) for b in instruction.bytes)

        logger.error(
            "Failed to translate x86 to REIL: %s (%s)",
            instruction,
            bytes_str,
            exc_info=True
        )

# ============================================================================ #

    def _not_implemented(self, tb, instruction):
        raise NotImplementedError("Instruction Not Implemented")

    def _extract_bit(self, tb, reg, bit):
        assert(bit >= 0 and bit < reg.size)

        tmp = tb.temporal(reg.size)
        ret = tb.temporal(1)

        tb.add(self._builder.gen_bsh(reg, tb.immediate(-bit, reg.size), tmp))   # shift to LSB
        tb.add(self._builder.gen_and(tmp, tb.immediate(1, reg.size), ret))      # filter LSB

        return ret

    def _extract_msb(self, tb, reg):
        return self._extract_bit(tb, reg, reg.size - 1)

    def _extract_sign_bit(self, tb, reg):
        return self._extract_msb(tb, reg)

# Translators
# ============================================================================ #
# ============================================================================ #

# "Flags"
# ============================================================================ #
    def _update_af(self, tb, oprnd0, oprnd1, result):
        # TODO: Implement
        pass

    def _update_pf(self, tb, oprnd0, oprnd1, result):
        # TODO: Implement
        pass

    def _update_sf(self, tb, oprnd0, oprnd1, result):
        # Create temporal variables.
        tmp0 = tb.temporal(result.size)

        mask0 = tb.immediate(2**(oprnd0.size-1), result.size)
        shift0 = tb.immediate(-(oprnd0.size-1), result.size)

        sf = self._flags["sf"]

        tb.add(self._builder.gen_and(result, mask0, tmp0))  # filter sign bit
        tb.add(self._builder.gen_bsh(tmp0, shift0, sf))     # extract sign bit

    def _update_of(self, tb, oprnd0, oprnd1, result):
        assert oprnd0.size == oprnd1.size

        of = self._flags["of"]

        imm0 = tb.immediate(1, 1)

        tmp0 = tb.temporal(1)
        tmp1 = tb.temporal(1)
        tmp2 = tb.temporal(1)
        tmp3 = tb.temporal(1)

        # Extract sign bit.
        oprnd0_sign = self._extract_sign_bit(tb, oprnd0)
        oprnd1_sign = self._extract_sign_bit(tb, oprnd1)
        result_sign = self._extract_bit(tb, result, oprnd0.size - 1)

        # Compute OF.
        tb.add(self._builder.gen_xor(oprnd0_sign, oprnd1_sign, tmp0))   # (sign bit oprnd0 ^ sign bit oprnd1)
        tb.add(self._builder.gen_xor(tmp0, imm0, tmp1))                 # (sign bit oprnd0 ^ sign bit oprnd1 ^ 1)
        tb.add(self._builder.gen_xor(oprnd0_sign, result_sign, tmp2))   # (sign bit oprnd0 ^ sign bit result)
        tb.add(self._builder.gen_and(tmp1, tmp2, tmp3))                 # (sign bit oprnd0 ^ sign bit oprnd1 ^ 1) & (sign bit oprnd0 ^ sign bit result)

        # Save result.
        tb.add(self._builder.gen_str(tmp3, of))

    def _update_of_sub(self, tb, oprnd0, oprnd1, result):
        assert oprnd0.size == oprnd1.size

        of = self._flags["of"]

        imm0 = tb.immediate(1, 1)

        tmp0 = tb.temporal(1)
        tmp1 = tb.temporal(1)
        tmp2 = tb.temporal(1)
        tmp3 = tb.temporal(1)

        oprnd1_sign = tb.temporal(1)

        # Extract sign bit.
        oprnd0_sign = self._extract_sign_bit(tb, oprnd0)
        oprnd1_sign_tmp = self._extract_sign_bit(tb, oprnd1)
        result_sign = self._extract_bit(tb, result, oprnd0.size - 1)

        # Invert sign bit of oprnd2.
        tb.add(self._builder.gen_xor(oprnd1_sign_tmp, imm0, oprnd1_sign))

        # Compute OF.
        tb.add(self._builder.gen_xor(oprnd0_sign, oprnd1_sign, tmp0))   # (sign bit oprnd0 ^ sign bit oprnd1)
        tb.add(self._builder.gen_xor(tmp0, imm0, tmp1))                 # (sign bit oprnd0 ^ sign bit oprnd1 ^ 1)
        tb.add(self._builder.gen_xor(oprnd0_sign, result_sign, tmp2))   # (sign bit oprnd0 ^ sign bit result)
        tb.add(self._builder.gen_and(tmp1, tmp2, tmp3))                 # (sign bit oprnd0 ^ sign bit oprnd1 ^ 1) & (sign bit oprnd0 ^ sign bit result)

        # Save result.
        tb.add(self._builder.gen_str(tmp3, of))

    def _update_cf(self, tb, oprnd0, oprnd1, result):
        cf = self._flags["cf"]

        imm0 = tb.immediate(2**oprnd0.size, result.size)
        imm1 = tb.immediate(-oprnd0.size, result.size)

        tmp0 = tb.temporal(result.size)

        tb.add(self._builder.gen_and(result, imm0, tmp0))   # filter carry bit
        tb.add(self._builder.gen_bsh(tmp0, imm1, cf))

    def _update_zf(self, tb, oprnd0, oprnd1, result):
        zf = self._flags["zf"]

        imm0 = tb.immediate((2**oprnd0.size)-1, result.size)

        tmp0 = tb.temporal(oprnd0.size)

        tb.add(self._builder.gen_and(result, imm0, tmp0))  # filter low part of result
        tb.add(self._builder.gen_bisz(tmp0, zf))

    def _undefine_flag(self, tb, flag):
        # NOTE: In every test I've made, each time a flag is leave
        # undefined it is always set to 0.

        imm = tb.immediate(0, flag.size)

        tb.add(self._builder.gen_str(imm, flag))

    def _clear_flag(self, tb, flag):
        imm = tb.immediate(0, flag.size)

        tb.add(self._builder.gen_str(imm, flag))

    def _set_flag(self, tb, flag):
        imm = tb.immediate(1, flag.size)

        tb.add(self._builder.gen_str(imm, flag))

# "Data Transfer Instructions"
# ============================================================================ #
    def _translate_mov(self, tb, instruction):
        # Flags Affected
        # None.

        oprnd1 = tb.read(instruction.operands[1])

        tb.write(instruction.operands[0], oprnd1)

    def _translate_movzx(self, tb, instruction):
        # Flags Affected
        # None.

        oprnd1 = tb.read(instruction.operands[1])

        tb.write(instruction.operands[0], oprnd1)

    def _translate_xchg(self, tb, instruction):
        # Flags Affected
        # None.

        oprnd0 = tb.read(instruction.operands[0])
        oprnd1 = tb.read(instruction.operands[1])

        tmp0 = tb.temporal(oprnd1.size)

        tb.add(self._builder.gen_str(oprnd0, tmp0))

        tb.write(instruction.operands[0], oprnd1)
        tb.write(instruction.operands[1], tmp0)

    def _translate_push(self, tb, instruction):
        # Flags Affected
        # None.

        oprnd0 = tb.read(instruction.operands[0])

        tmp0 = tb.temporal(self._sp.size)

        tb.add(self._builder.gen_sub(self._sp, self._ws, tmp0))
        tb.add(self._builder.gen_str(tmp0, self._sp))
        tb.add(self._builder.gen_stm(oprnd0, self._sp))

    def _translate_pop(self, tb, instruction):
        # Flags Affected
        # None.

        oprnd0 = tb.read(instruction.operands[0])

        tmp0 = tb.temporal(self._sp.size)

        tb.add(self._builder.gen_ldm(self._sp, oprnd0))
        tb.add(self._builder.gen_add(self._sp, self._ws, tmp0))
        tb.add(self._builder.gen_str(tmp0, self._sp))

# "Binary Arithmetic Instructions"
# ============================================================================ #
    def _translate_add(self, tb, instruction):
        # Flags Affected
        # The OF, SF, ZF, AF, CF, and PF flags are set according to the
        # result.

        oprnd0 = tb.read(instruction.operands[0])
        oprnd1 = tb.read(instruction.operands[1])

        tmp0 = tb.temporal(oprnd0.size*2)

        tb.add(self._builder.gen_add(oprnd0, oprnd1, tmp0))

        if self._translation_mode == FULL_TRANSLATION:
            # Flags : OF, SF, ZF, AF, CF, PF
            self._update_of(tb, oprnd0, oprnd1, tmp0)
            self._update_sf(tb, oprnd0, oprnd1, tmp0)
            self._update_zf(tb, oprnd0, oprnd1, tmp0)
            self._update_af(tb, oprnd0, oprnd1, tmp0)
            self._update_cf(tb, oprnd0, oprnd1, tmp0)
            self._update_pf(tb, oprnd0, oprnd1, tmp0)

        tb.write(instruction.operands[0], tmp0)

    def _translate_adc(self, tb, instruction):
        # Flags Affected
        # The OF, SF, ZF, AF, CF, and PF flags are set according to the result.

        oprnd0 = tb.read(instruction.operands[0])
        oprnd1 = tb.read(instruction.operands[1])

        tmp0 = tb.temporal(oprnd1.size*2)
        tmp1 = tb.temporal(oprnd1.size*2)
        tmp2 = tb.temporal(oprnd1.size*2)

        tb.add(self._builder.gen_add(oprnd0, oprnd1, tmp0))
        tb.add(self._builder.gen_str(self._flags["cf"], tmp1))
        tb.add(self._builder.gen_add(tmp0, tmp1, tmp2))

        if self._translation_mode == FULL_TRANSLATION:
            # Flags : OF, SF, ZF, AF, CF, PF
            self._update_of(tb, oprnd0, oprnd1, tmp2)
            self._update_sf(tb, oprnd0, oprnd1, tmp2)
            self._update_zf(tb, oprnd0, oprnd1, tmp2)
            self._update_af(tb, oprnd0, oprnd1, tmp2)
            self._update_cf(tb, oprnd0, oprnd1, tmp2)
            self._update_pf(tb, oprnd0, oprnd1, tmp2)

        tb.write(instruction.operands[0], tmp2)

    def _translate_sub(self, tb, instruction):
        # Flags Affected
        # The OF, SF, ZF, AF, PF, and CF flags are set according to the
        # result.

        oprnd0 = tb.read(instruction.operands[0])
        oprnd1 = tb.read(instruction.operands[1])

        tmp0 = tb.temporal(oprnd0.size*2)

        tb.add(self._builder.gen_sub(oprnd0, oprnd1, tmp0))

        if self._translation_mode == FULL_TRANSLATION:
            # Flags : OF, SF, ZF, AF, PF, CF
            self._update_of_sub(tb, oprnd0, oprnd1, tmp0)
            self._update_sf(tb, oprnd0, oprnd1, tmp0)
            self._update_zf(tb, oprnd0, oprnd1, tmp0)
            self._update_af(tb, oprnd0, oprnd1, tmp0)
            self._update_pf(tb, oprnd0, oprnd1, tmp0)
            self._update_cf(tb, oprnd0, oprnd1, tmp0)

        tb.write(instruction.operands[0], tmp0)

    def _translate_sbb(self, tb, instruction):
        # Flags Affected
        # The OF, SF, ZF, AF, PF, and CF flags are set according to the
        # result.

        oprnd0 = tb.read(instruction.operands[0])
        oprnd1 = tb.read(instruction.operands[1])

        tmp0 = tb.temporal(oprnd0.size*2)
        tmp1 = tb.temporal(oprnd0.size*2)
        tmp2 = tb.temporal(oprnd0.size*2)

        # FIX: This translation generates a wrong result for the OF flag
        # for some inputs.
        tb.add(self._builder.gen_sub(oprnd0, oprnd1, tmp0))
        tb.add(self._builder.gen_str(self._flags["cf"], tmp1))
        tb.add(self._builder.gen_sub(oprnd0, oprnd1, tmp2))

        if self._translation_mode == FULL_TRANSLATION:
            # Flags : OF, SF, ZF, AF, PF, CF
            self._update_of_sub(tb, oprnd0, oprnd1, tmp2)
            self._update_sf(tb, oprnd0, oprnd1, tmp2)
            self._update_zf(tb, oprnd0, oprnd1, tmp2)
            self._update_af(tb, oprnd0, oprnd1, tmp2)
            self._update_pf(tb, oprnd0, oprnd1, tmp2)
            self._update_cf(tb, oprnd0, oprnd1, tmp2)

        tb.write(instruction.operands[0], tmp2)

    def _translate_mul(self, tb, instruction):
        # Flags Affected
        # The OF and CF flags are set to 0 if the upper half of the
        # result is 0; otherwise, they are set to 1. The SF, ZF, AF, and
        # PF flags are undefined.

        # IF (Byte operation)
        #   THEN
        #       AX <- AL * SRC;
        #   ELSE (* Word or doubleword operation *)
        #       IF OperandSize = 16
        #           THEN
        #               DX:AX <- AX * SRC;
        #           ELSE IF OperandSize = 32
        #               THEN EDX:EAX <- EAX * SRC; FI;
        #           ELSE (* OperandSize = 64 *)
        #               RDX:RAX <- RAX * SRC;
        #           FI;
        # FI;

        oprnd0 = tb.read(instruction.operands[0])

        if oprnd0.size == 8:
            oprnd1 = ReilRegisterOperand("al", 8)
            tmp0 = tb.temporal(16)
            result_low = ReilRegisterOperand("al", 8)
            result_high = ReilRegisterOperand("ah", 8)
        elif oprnd0.size == 16:
            oprnd1 = ReilRegisterOperand("ax", 16)
            tmp0 = tb.temporal(32)
            result_low = ReilRegisterOperand("ax", 16)
            result_high = ReilRegisterOperand("dx", 16)
        elif oprnd0.size == 32:
            oprnd1 = ReilRegisterOperand("eax", 32)
            tmp0 = tb.temporal(64)
            result_low = ReilRegisterOperand("eax", 32)
            result_high = ReilRegisterOperand("edx", 32)
        elif oprnd0.size == 64:
            oprnd1 = ReilRegisterOperand("rax", 64)
            tmp0 = tb.temporal(128)
            result_low = ReilRegisterOperand("rax", 64)
            result_high = ReilRegisterOperand("rdx", 64)

        imm0 = tb.immediate(-oprnd0.size, oprnd0.size*2)

        tb.add(self._builder.gen_mul(oprnd0, oprnd1, tmp0))

        # Clean rax and rdx registers.
        if self._arch_info.architecture_mode == ARCH_X86_MODE_64 and \
            oprnd0.size == 32:

            zero = tb.immediate(0, 64)

            tb.add(self._builder.gen_str(zero, ReilRegisterOperand("rdx", 64)))
            tb.add(self._builder.gen_str(zero, ReilRegisterOperand("rax", 64)))

        tb.add(self._builder.gen_bsh(tmp0, imm0, result_high))
        tb.add(self._builder.gen_str(tmp0, result_low))

        if self._translation_mode == FULL_TRANSLATION:
            # Flags : OF, CF
            fimm0 = tb.immediate(1, 1)

            ftmp0 = tb.temporal(oprnd0.size*2)
            ftmp1 = tb.temporal(1)

            tb.add(self._builder.gen_bsh(tmp0, imm0, ftmp0))
            tb.add(self._builder.gen_bisz(ftmp0, ftmp1))
            tb.add(self._builder.gen_xor(ftmp1, fimm0, self._flags["of"]))
            tb.add(self._builder.gen_xor(ftmp1, fimm0, self._flags["cf"]))

            # Flags : SF, ZF, AF, PF
            self._undefine_flag(tb, self._flags["sf"])
            self._undefine_flag(tb, self._flags["zf"])
            self._undefine_flag(tb, self._flags["af"])
            self._undefine_flag(tb, self._flags["pf"])

    def _translate_imul(self, tb, instruction):
        # Flags Affected
        # For the one operand form of the instruction, the CF and OF flags are
        # set when significant bits are carried into the upper half of the
        # result and cleared when the result fits exactly in the lower half of
        # the result. For the two- and three-operand forms of the instruction,
        # the CF and OF flags are set when the result must be truncated to fit
        # in the destination operand size and cleared when the result fits
        # exactly in the destination operand size. The SF, ZF, AF, and PF flags
        # are undefined.

        # TODO: Implement CF and OF flags.
        # FIXME: Make this a signed multiply.

        # IF (NumberOfOperands = 1)
        #   THEN IF (OperandSize = 8)
        #       THEN
        #           AX <- AL * SRC (* Signed multiplication *)
        #           IF AL = AX
        #               THEN CF <- 0; OF <- 0;
        #               ELSE CF <- 1; OF <- 1; FI;
        #   ELSE IF OperandSize = 16
        #       THEN
        #       DX:AX <- AX * SRC (* Signed multiplication *)
        #       IF sign_extend_to_32 (AX) = DX:AX
        #           THEN CF <- 0; OF <- 0;
        #           ELSE CF <- 1; OF <- 1; FI;
        #   ELSE IF OperandSize = 32
        #       THEN
        #       EDX:EAX <- EAX * SRC (* Signed multiplication *)
        #       IF EAX = EDX:EAX
        #           THEN CF <- 0; OF <- 0;
        #           ELSE CF <- 1; OF <- 1; FI;
        #   ELSE (* OperandSize = 64 *)
        #       RDX:RAX <- RAX * SRC (* Signed multiplication *)
        #       IF RAX = RDX:RAX
        #           THEN CF <- 0; OF <- 0;
        #           ELSE CF <- 1; OF <- 1; FI;
        #   FI;
        # ELSE IF (NumberOfOperands = 2)
        #   THEN
        #       temp <- DEST * SRC (* Signed multiplication; temp is double DEST size *)
        #       DEST <- DEST * SRC (* Signed multiplication *)
        #       IF temp != DEST
        #           THEN CF <- 1; OF <- 1;
        #           ELSE CF <- 0; OF <- 0; FI;
        #   ELSE (* NumberOfOperands = 3 *)
        #       DEST <- SRC1 * SRC2 (* Signed multiplication *)
        #       temp <- SRC1 * SRC2 (* Signed multiplication; temp is double SRC1 size *)
        #       IF temp != DEST
        #           THEN CF <- 1; OF <- 1;
        #           ELSE CF <- 0; OF <- 0; FI;
        #   FI;
        # FI;


        if len(instruction.operands) == 1:

            oprnd0 = tb.read(instruction.operands[0])

            if oprnd0.size == 8:
                oprnd1 = ReilRegisterOperand("al", 8)

                tmp0 = tb.temporal(16)
                result_low = ReilRegisterOperand("al", 8)
                result_high = ReilRegisterOperand("ah", 8)
            elif oprnd0.size == 16:
                oprnd1 = ReilRegisterOperand("ax", 16)

                tmp0 = tb.temporal(32)
                result_low = ReilRegisterOperand("dx", 16)
                result_high = ReilRegisterOperand("ax", 16)
            elif oprnd0.size == 32:
                oprnd1 = ReilRegisterOperand("eax", 32)

                tmp0 = tb.temporal(64)
                result_low = ReilRegisterOperand("edx", 32)
                result_high = ReilRegisterOperand("eax", 32)
            elif oprnd0.size == 64:
                oprnd1 = ReilRegisterOperand("rax", 64)

                tmp0 = tb.temporal(64)
                result_low = ReilRegisterOperand("rdx", 64)
                result_high = ReilRegisterOperand("rax", 64)

        elif len(instruction.operands) == 2:

            oprnd0 = tb.read(instruction.operands[0])
            oprnd1 = tb.read(instruction.operands[1])

        elif len(instruction.operands) == 3:

            oprnd0 = tb.read(instruction.operands[1])
            oprnd1 = tb.read(instruction.operands[2])

        imm0 = tb.immediate(-oprnd0.size, 2*oprnd0.size)

        tmp0 = tb.temporal(2*oprnd0.size)

        # Do multiplication.
        tb.add(self._builder.gen_mul(oprnd0, oprnd1, tmp0))

        # Save result.
        if len(instruction.operands) == 1:

            tb.add(self._builder.gen_bsh(tmp0, imm0, result_high))
            tb.add(self._builder.gen_str(tmp0, result_low))

        elif len(instruction.operands) == 2:

            tb.write(instruction.operands[0], tmp0)

        elif len(instruction.operands) == 3:

            tb.write(instruction.operands[0], tmp0)

        if self._translation_mode == FULL_TRANSLATION:
            # Flags : OF, CF
            # TODO: Implement.
            self._undefine_flag(tb, self._flags["sf"])
            self._undefine_flag(tb, self._flags["zf"])
            self._undefine_flag(tb, self._flags["af"])
            self._undefine_flag(tb, self._flags["pf"])

    def _translate_div(self, tb, instruction):
        # Flags Affected
        # The CF, OF, SF, ZF, AF, and PF flags are undefined.

        oprnd0 = tb.read(instruction.operands[0])

        if oprnd0.size == 8:
            oprnd1 = ReilRegisterOperand("ah", 8)
            oprnd2 = ReilRegisterOperand("al", 8)
            result_low = ReilRegisterOperand("al", 8)
            result_high = ReilRegisterOperand("ah", 8)
        elif oprnd0.size == 16:
            oprnd1 = ReilRegisterOperand("dx", 16)
            oprnd2 = ReilRegisterOperand("ax", 16)
            result_low = ReilRegisterOperand("ax", 16)
            result_high = ReilRegisterOperand("dx", 16)
        elif oprnd0.size == 32:
            oprnd1 = ReilRegisterOperand("edx", 32)
            oprnd2 = ReilRegisterOperand("eax", 32)
            result_low = ReilRegisterOperand("eax", 32)
            result_high = ReilRegisterOperand("edx", 32)
        elif oprnd0.size == 64:
            oprnd1 = ReilRegisterOperand("rdx", 64)
            oprnd2 = ReilRegisterOperand("rax", 64)
            result_low = ReilRegisterOperand("rax", 64)
            result_high = ReilRegisterOperand("rdx", 64)

        imm0 = tb.immediate(oprnd0.size, oprnd0.size*2)

        tmp0 = tb.temporal(oprnd0.size*2)
        tmp1 = tb.temporal(oprnd0.size*2)
        tmp2 = tb.temporal(oprnd0.size*2)

        tmp3 = tb.temporal(oprnd0.size*2)
        tmp4 = tb.temporal(oprnd0.size*2)
        tmp5 = tb.temporal(oprnd0.size*2)
        tmp6 = tb.temporal(oprnd0.size*2)

        # Extend operands to match their size.
        tb.add(self._builder.gen_str(oprnd0, tmp0))
        tb.add(self._builder.gen_str(oprnd1, tmp1))
        tb.add(self._builder.gen_str(oprnd2, tmp2))

        # Put dividend together.
        tb.add(self._builder.gen_bsh(tmp1, imm0, tmp3))
        tb.add(self._builder.gen_or(tmp3, tmp2, tmp4))

        # Do division
        tb.add(self._builder.gen_div(tmp4, tmp0, tmp5))
        tb.add(self._builder.gen_mod(tmp4, tmp0, tmp6))
        tb.add(self._builder.gen_str(tmp5, result_low))
        tb.add(self._builder.gen_str(tmp6, result_high))

        if self._translation_mode == FULL_TRANSLATION:
            # Flags : CF, OF, SF, ZF, AF, PF
            self._undefine_flag(tb, self._flags["cf"])
            self._undefine_flag(tb, self._flags["of"])
            self._undefine_flag(tb, self._flags["sf"])
            self._undefine_flag(tb, self._flags["zf"])
            self._undefine_flag(tb, self._flags["af"])
            self._undefine_flag(tb, self._flags["pf"])

    def _translate_inc(self, tb, instruction):
        # Flags Affected
        # The CF flag is not affected. The OF, SF, ZF, AF, and PF flags
        # are set according to the result.

        oprnd0 = tb.read(instruction.operands[0])

        imm0 = tb.immediate(1, oprnd0.size)

        tmp0 = tb.temporal(oprnd0.size*2)

        tb.add(self._builder.gen_add(oprnd0, imm0, tmp0))

        if self._translation_mode == FULL_TRANSLATION:
            # Flags : OF, SF, ZF, AF, PF
            self._update_of(tb, oprnd0, imm0, tmp0)
            self._update_sf(tb, oprnd0, imm0, tmp0)
            self._update_zf(tb, oprnd0, imm0, tmp0)
            self._update_af(tb, oprnd0, imm0, tmp0)
            self._update_pf(tb, oprnd0, imm0, tmp0)

        tb.write(instruction.operands[0], tmp0)

    def _translate_dec(self, tb, instruction):
        # Flags Affected
        # The CF flag is not affected. The OF, SF, ZF, AF, and PF flags
        # are set according to the result.

        oprnd0 = tb.read(instruction.operands[0])

        imm0 = tb.immediate(1, oprnd0.size)

        tmp0 = tb.temporal(oprnd0.size*2)

        tb.add(self._builder.gen_sub(oprnd0, imm0, tmp0))

        if self._translation_mode == FULL_TRANSLATION:
            # Flags : OF, SF, ZF, AF, PF
            self._update_of_sub(tb, oprnd0, imm0, tmp0)
            self._update_sf(tb, oprnd0, imm0, tmp0)
            self._update_zf(tb, oprnd0, imm0, tmp0)
            self._update_af(tb, oprnd0, imm0, tmp0)
            self._update_pf(tb, oprnd0, imm0, tmp0)

        tb.write(instruction.operands[0], tmp0)

    def _translate_neg(self, tb, instruction):
        # Flags Affected
        # The CF flag set to 0 if the source operand is 0; otherwise it
        # is set to 1. The OF, SF, ZF, AF, and PF flags are set
        # according to the result.

        oprnd0 = tb.read(instruction.operands[0])

        imm0 = tb.immediate((2**oprnd0.size)-1, oprnd0.size)
        imm1 = tb.immediate(1, oprnd0.size)
        imm2 = tb.immediate(1, 1)

        tmp0 = tb.temporal(oprnd0.size)
        tmp1 = tb.temporal(oprnd0.size)
        tmp2 = tb.temporal(1)

        tb.add(self._builder.gen_xor(oprnd0, imm0, tmp0))
        tb.add(self._builder.gen_add(tmp0, imm1, tmp1))

        # Flags : CF
        tb.add(self._builder.gen_bisz(oprnd0, tmp2))
        tb.add(self._builder.gen_xor(tmp2, imm2, self._flags["cf"]))

        if self._translation_mode == FULL_TRANSLATION:
            # Flags : OF, SF, ZF, AF, PF
            self._update_of_sub(tb, oprnd0, oprnd0, tmp1)
            self._update_sf(tb, oprnd0, oprnd0, tmp1)
            self._update_zf(tb, oprnd0, oprnd0, tmp1)
            self._update_af(tb, oprnd0, oprnd0, tmp1)
            self._update_pf(tb, oprnd0, oprnd0, tmp1)

        tb.write(instruction.operands[0], tmp1)

    def _translate_cmp(self, tb, instruction):
        # Flags Affected
        # The CF, OF, SF, ZF, AF, and PF flags are set according to the
        # result.

        oprnd0 = tb.read(instruction.operands[0])
        oprnd1 = tb.read(instruction.operands[1])

        tmp0 = tb.temporal(oprnd0.size*2)

        tb.add(self._builder.gen_sub(oprnd0, oprnd1, tmp0))

        # Flags : CF, OF, SF, ZF, AF, PF
        self._update_cf(tb, oprnd0, oprnd1, tmp0)
        self._update_of_sub(tb, oprnd0, oprnd1, tmp0)
        self._update_sf(tb, oprnd0, oprnd1, tmp0)
        self._update_zf(tb, oprnd0, oprnd1, tmp0)
        self._update_af(tb, oprnd0, oprnd1, tmp0)
        self._update_pf(tb, oprnd0, oprnd1, tmp0)

# "Decimal Arithmetic Instructions"
# ============================================================================ #

# "Logical Instructions"
# ============================================================================ #
    def _translate_and(self, tb, instruction):
        # Flags Affected
        # The OF and CF flags are cleared; the SF, ZF, and PF flags are
        # set according to the result. The state of the AF flag is
        # undefined.

        oprnd0 = tb.read(instruction.operands[0])
        oprnd1 = tb.read(instruction.operands[1])

        tmp0 = tb.temporal(oprnd0.size*2)

        tb.add(self._builder.gen_and(oprnd0, oprnd1, tmp0))

        if self._translation_mode == FULL_TRANSLATION:
            # Flags : OF, CF
            self._clear_flag(tb, self._flags["of"])
            self._clear_flag(tb, self._flags["cf"])

            # Flags : SF, ZF, PF
            self._update_sf(tb, oprnd0, oprnd1, tmp0)
            self._update_zf(tb, oprnd0, oprnd1, tmp0)
            self._update_pf(tb, oprnd0, oprnd1, tmp0)

            # Flags : AF
            self._undefine_flag(tb, self._flags["af"])

        tb.write(instruction.operands[0], tmp0)

    def _translate_or(self, tb, instruction):
        # Flags Affected
        # The OF and CF flags are cleared; the SF, ZF, and PF flags are
        # set according to the result. The state of the AF flag is
        # undefined.

        oprnd0 = tb.read(instruction.operands[0])
        oprnd1 = tb.read(instruction.operands[1])

        tmp0 = tb.temporal(oprnd0.size*2)

        tb.add(self._builder.gen_or(oprnd0, oprnd1, tmp0))

        if self._translation_mode == FULL_TRANSLATION:
            # Flags : OF, CF
            self._clear_flag(tb, self._flags["of"])
            self._clear_flag(tb, self._flags["cf"])

            # Flags : SF, ZF, PF
            self._update_sf(tb, oprnd0, oprnd1, tmp0)
            self._update_zf(tb, oprnd0, oprnd1, tmp0)
            self._update_pf(tb, oprnd0, oprnd1, tmp0)

            # Flags : AF
            self._undefine_flag(tb, self._flags["af"])

        tb.write(instruction.operands[0], tmp0)

    def _translate_xor(self, tb, instruction):
        # Flags Affected
        # The OF and CF flags are cleared; the SF, ZF, and PF flags are set
        # according to the result. The state of the AF flag is
        # undefined.

        oprnd0 = tb.read(instruction.operands[0])
        oprnd1 = tb.read(instruction.operands[1])

        tmp0 = tb.temporal(oprnd0.size*2)

        tb.add(self._builder.gen_xor(oprnd0, oprnd1, tmp0))

        if self._translation_mode == FULL_TRANSLATION:
            # Flags : OF, CF
            self._clear_flag(tb, self._flags["of"])
            self._clear_flag(tb, self._flags["cf"])

            # Flags : SF, ZF, PF
            self._update_sf(tb, oprnd0, oprnd1, tmp0)
            self._update_zf(tb, oprnd0, oprnd1, tmp0)
            self._update_pf(tb, oprnd0, oprnd1, tmp0)

            # Flags : AF
            self._undefine_flag(tb, self._flags["af"])

        tb.write(instruction.operands[0], tmp0)

    def _translate_not(self, tb, instruction):
        # Flags Affected
        # None.

        oprnd0 = tb.read(instruction.operands[0])

        tmp0 = tb.temporal(oprnd0.size*2)

        imm0 = tb.immediate((2**oprnd0.size)-1, oprnd0.size)

        tb.add(self._builder.gen_xor(oprnd0, imm0, tmp0))

        tb.write(instruction.operands[0], tmp0)

# "Shift and Rotate Instructions"
# ============================================================================ #
    def _translate_shr(self, tb, instruction):
        # Flags Affected
        # The CF flag contains the value of the last bit shifted out
        # of the destination operand; it is undefined for SHL and SHR
        # instructions where the count is greater than or equal to the
        # size (in bits) of the destination operand. The OF flag is
        # affected only for 1-bit shifts (see "Description" above);
        # otherwise, it is undefined. The SF, ZF, and PF flags are set
        # according to the result. If the count is 0, the flags are
        # not affected. For a non-zero count, the AF flag is
        # undefined.

        # TODO: Fix flag translation

        oprnd0 = tb.read(instruction.operands[0])
        oprnd1 = tb.read(instruction.operands[1])

        imm0 = tb.immediate(1, oprnd0.size)
        imm1 = tb.immediate((2**oprnd0.size)-1, oprnd0.size)
        imm2 = tb.immediate(-1, oprnd0.size)

        tmp0 = tb.temporal(oprnd0.size)
        tmp1 = tb.temporal(oprnd0.size)
        tmp2 = tb.temporal(oprnd0.size)
        tmp3 = tb.temporal(oprnd0.size)
        tmp4 = tb.temporal(oprnd0.size)
        tmp5 = tb.temporal(oprnd0.size)
        tmp6 = tb.temporal(oprnd0.size)

        # Extend 2nd operand to 1st operand size
        tb.add(self._builder.gen_str(oprnd1, tmp0))

        # Decrement in 1 shift amount
        tb.add(self._builder.gen_sub(tmp0, imm0, tmp1))

        # Negate
        tb.add(self._builder.gen_xor(tmp1, imm1, tmp2))
        tb.add(self._builder.gen_add(tmp2, imm0, tmp3))

        # Shift right
        tb.add(self._builder.gen_bsh(oprnd0, tmp3, tmp4))

        # Save LSB in CF
        tb.add(self._builder.gen_and(tmp4, imm0, tmp5))
        tb.add(self._builder.gen_str(tmp5, self._flags["cf"]))

        # Shift one more time
        tb.add(self._builder.gen_bsh(tmp4, imm2, tmp6))

        if self._translation_mode == FULL_TRANSLATION:
            # Flags : OF
            # TODO: Implement translation for OF flag.

            # Flags : SF, ZF, PF
            self._update_sf(tb, oprnd0, oprnd0, tmp6)
            self._update_zf(tb, oprnd0, oprnd0, tmp6)
            self._update_pf(tb, oprnd0, oprnd0, tmp6)

            # Flags : AF
            self._undefine_flag(tb, self._flags["af"])

        tb.write(instruction.operands[0], tmp6)

    def _translate_shl(self, tb, instruction):
        # Flags Affected
        # The CF flag contains the value of the last bit shifted out
        # of the destination operand; it is undefined for SHL and SHR
        # instructions where the count is greater than or equal to the
        # size (in bits) of the destination operand. The OF flag is
        # affected only for 1-bit shifts (see "Description" above);
        # otherwise, it is undefined. The SF, ZF, and PF flags are set
        # according to the result. If the count is 0, the flags are
        # not affected. For a non-zero count, the AF flag is
        # undefined.

        # TODO: Fix flag translation.

        oprnd0 = tb.read(instruction.operands[0])
        oprnd1 = tb.read(instruction.operands[1])

        imm0 = tb.immediate(1, oprnd0.size)

        tmp0 = tb.temporal(oprnd0.size)
        tmp1 = tb.temporal(oprnd0.size)
        tmp2 = tb.temporal(oprnd0.size)
        tmp3 = tb.temporal(oprnd0.size)

        tmp4 = tb.temporal(oprnd0.size)

        # Extend 2nd operand to 1st operand size
        tb.add(self._builder.gen_str(oprnd1, tmp0))

        # Decrement in 1 shift amount
        tb.add(self._builder.gen_sub(tmp0, imm0, tmp1))

        # Shift left
        tb.add(self._builder.gen_bsh(oprnd0, tmp1, tmp2))

        # Save LSB in CF
        tb.add(self._builder.gen_and(tmp2, imm0, tmp3))
        tb.add(self._builder.gen_str(tmp3, self._flags["cf"]))

        # Shift one more time
        tb.add(self._builder.gen_bsh(tmp2, imm0, tmp4))

        if self._translation_mode == FULL_TRANSLATION:
            # Flags : OF
            # TODO: Implement translation for OF flag.

            # Flags : SF, ZF, PF
            self._update_sf(tb, oprnd0, oprnd0, tmp4)
            self._update_zf(tb, oprnd0, oprnd0, tmp4)
            self._update_pf(tb, oprnd0, oprnd0, tmp4)

            # Flags : AF
            self._undefine_flag(tb, self._flags["af"])

        tb.write(instruction.operands[0], tmp4)

    def _translate_sal(self, tb, instruction):
        # Flags Affected
        # The CF flag contains the value of the last bit shifted out
        # of the destination operand; it is undefined for SHL and SHR
        # instructions where the count is greater than or equal to the
        # size (in bits) of the destination operand. The OF flag is
        # affected only for 1-bit shifts (see "Description" above);
        # otherwise, it is undefined. The SF, ZF, and PF flags are set
        # according to the result. If the count is 0, the flags are
        # not affected. For a non-zero count, the AF flag is
        # undefined.

        # TODO: Fix flag translation.

        return self._translate_shl(tb, instruction)

    def _translate_sar(self, tb, instruction):
        # Flags Affected
        # The CF flag contains the value of the last bit shifted out
        # of the destination operand; it is undefined for SHL and SHR
        # instructions where the count is greater than or equal to the
        # size (in bits) of the destination operand. The OF flag is
        # affected only for 1-bit shifts (see "Description" above);
        # otherwise, it is undefined. The SF, ZF, and PF flags are set
        # according to the result. If the count is 0, the flags are
        # not affected. For a non-zero count, the AF flag is
        # undefined.

        # TODO: Fix flag translation.

        oprnd0 = tb.read(instruction.operands[0])
        oprnd1 = tb.read(instruction.operands[1])

        imm0 = tb.immediate(2**(oprnd0.size-1), oprnd0.size)
        imm1 = tb.immediate(1, oprnd0.size)
        imm2 = tb.immediate(-1, oprnd0.size)

        tmp0 = tb.temporal(oprnd0.size)
        tmp1 = tb.temporal(oprnd0.size)
        tmp2 = tb.temporal(oprnd0.size)
        tmp6 = tb.temporal(oprnd0.size)
        tmp3 = tb.temporal(oprnd0.size)
        tmp4 = tb.temporal(oprnd0.size)
        tmp5 = tb.temporal(oprnd0.size)
        tmp6 = tb.temporal(oprnd0.size)

        # Create labels.
        loop_lbl = tb.label('loop')

        # Initialize counter
        tb.add(self._builder.gen_str(oprnd1, tmp0))

        # Copy operand to temporal register
        tb.add(self._builder.gen_str(oprnd0, tmp1))

        # Filter sign bit
        tb.add(self._builder.gen_and(oprnd0, imm0, tmp2))

        tb.add(loop_lbl)

        # Filter lsb bit
        tb.add(self._builder.gen_and(oprnd0, imm1, tmp6))
        tb.add(self._builder.gen_str(tmp6, self._flags["cf"]))

        # Shift right
        tb.add(self._builder.gen_bsh(tmp1, imm2, tmp3))

        # Propagate sign bit
        tb.add(self._builder.gen_or(tmp3, tmp2, tmp1))

        # Decrement counter
        tb.add(self._builder.gen_sub(tmp0, imm1, tmp0))

        # Compare counter to zero
        tb.add(self._builder.gen_bisz(tmp0, tmp4))

        # Invert stop flag
        tb.add(self._builder.gen_xor(tmp4, imm1, tmp5))

        # Iterate
        tb.add(self._builder.gen_jcc(tmp5, loop_lbl))

        # Save result
        tb.add(self._builder.gen_str(tmp1, tmp6))

        if self._translation_mode == FULL_TRANSLATION:
            # Flags : OF
            # TODO: Implement translation for OF flag.

            # Flags : SF, ZF, PF
            self._update_sf(tb, oprnd0, oprnd0, tmp6)
            self._update_zf(tb, oprnd0, oprnd0, tmp6)
            self._update_pf(tb, oprnd0, oprnd0, tmp6)

            # Flags : AF
            self._undefine_flag(tb, self._flags["af"])

        tb.write(instruction.operands[0], tmp6)

    def _translate_rol(self, tb, instruction):
        # Flags Affected
        # The CF flag contains the value of the bit shifted into it.
        # The OF flag is affected only for single-bit rotates (see
        # "Description" above); it is undefined for multi-bit rotates.
        # The SF, ZF, AF, and PF flags are not affected.

        oprnd0 = tb.read(instruction.operands[0])
        oprnd1 = tb.read(instruction.operands[1])

        size = tb.immediate(oprnd0.size, oprnd0.size)

        if self._arch_mode == ARCH_X86_MODE_32:
            count_mask = tb.immediate(0x1f, oprnd0.size)
        elif self._arch_mode == ARCH_X86_MODE_64:
            count_mask = tb.immediate(0x3f, oprnd0.size)

        count_masked = tb.temporal(oprnd0.size)
        count = tb.temporal(oprnd0.size)
        temp_count = tb.temporal(oprnd0.size)

        oprnd_ext = tb.temporal(oprnd0.size * 2)
        oprnd_ext_shifted = tb.temporal(oprnd0.size * 2)
        oprnd_ext_shifted_l = tb.temporal(oprnd0.size)
        oprnd_ext_shifted_h = tb.temporal(oprnd0.size)

        result = tb.temporal(oprnd0.size)
        result_msb = tb.temporal(1)

        tmp0 = tb.temporal(1)
        tmp0_zero = tb.temporal(1)

        imm0 = tb.immediate(1, oprnd0.size)
        imm1 = tb.immediate(-oprnd0.size, oprnd0.size * 2)
        imm2 = tb.immediate(-(oprnd0.size + 1), oprnd0.size)

        # Compute temp count.
        tb.add(self._builder.gen_str(oprnd1, count))
        tb.add(self._builder.gen_and(count, count_mask, count_masked))
        tb.add(self._builder.gen_mod(count_masked, size, temp_count))

        # Rotate register.
        tb.add(self._builder.gen_str(oprnd0, oprnd_ext))
        tb.add(self._builder.gen_bsh(oprnd_ext, temp_count, oprnd_ext_shifted))
        tb.add(self._builder.gen_bsh(oprnd_ext_shifted, imm1, oprnd_ext_shifted_h))
        tb.add(self._builder.gen_str(oprnd_ext_shifted, oprnd_ext_shifted_l))
        tb.add(self._builder.gen_or(oprnd_ext_shifted_l, oprnd_ext_shifted_h, result))

        # Compute CF.
        tb.add(self._builder.gen_str(result, self._flags["cf"]))

        # Compute OF.
        undef_of_lbl = tb.label('undef_of_lbl')

        tb.add(self._builder.gen_sub(count_masked, imm0, tmp0))
        tb.add(self._builder.gen_bisz(tmp0, tmp0_zero))
        tb.add(self._builder.gen_jcc(tmp0_zero, undef_of_lbl))

        # Compute.
        tb.add(self._builder.gen_bsh(result, imm2, result_msb))
        tb.add(self._builder.gen_xor(result_msb, self._flags["cf"], self._flags["of"]))

        # Undef OF.
        tb.add(undef_of_lbl)
        self._undefine_flag(tb, self._flags["of"])

        tb.write(instruction.operands[0], result)

    def _translate_ror(self, tb, instruction):
        # Flags Affected
        # The CF flag contains the value of the bit shifted into it.
        # The OF flag is affected only for single-bit rotates (see
        # "Description" above); it is undefined for multi-bit rotates.
        # The SF, ZF, AF, and PF flags are not affected.

        oprnd0 = tb.read(instruction.operands[0])
        oprnd1 = tb.read(instruction.operands[1])

        size = tb.immediate(oprnd0.size, oprnd0.size)

        if self._arch_mode == ARCH_X86_MODE_32:
            count_mask = tb.immediate(0x1f, oprnd0.size)
        elif self._arch_mode == ARCH_X86_MODE_64:
            count_mask = tb.immediate(0x3f, oprnd0.size)

        count = tb.temporal(oprnd0.size)
        temp_count = tb.temporal(oprnd0.size)

        oprnd_ext = tb.temporal(oprnd0.size * 2)
        oprnd_ext_shifted = tb.temporal(oprnd0.size * 2)
        oprnd_ext_shifted_l = tb.temporal(oprnd0.size)
        oprnd_ext_shifted_h = tb.temporal(oprnd0.size)

        result = tb.temporal(oprnd0.size)
        result_msb = tb.temporal(1)
        result_msb_prev = tb.temporal(1)

        tmp0 = tb.temporal(oprnd0.size)
        tmp1 = tb.temporal(1)
        tmp1_zero = tb.temporal(1)
        tmp2 = tb.temporal(oprnd0.size)

        zero = tb.immediate(0, oprnd0.size)
        imm1 = tb.immediate(1, oprnd0.size)
        imm2 = tb.immediate(-oprnd0.size, oprnd0.size * 2)
        imm3 = tb.immediate(-(oprnd0.size + 1), oprnd0.size)
        imm4 = tb.immediate(oprnd0.size - 1, oprnd0.size)
        imm5 = tb.immediate(oprnd0.size - 2, oprnd0.size)

        # Compute temp count.
        tb.add(self._builder.gen_str(oprnd1, count))
        tb.add(self._builder.gen_and(count, count_mask, tmp0))
        tb.add(self._builder.gen_mod(tmp0, size, tmp2))
        tb.add(self._builder.gen_sub(zero, tmp2, temp_count))

        # Rotate register.
        tb.add(self._builder.gen_bsh(oprnd0, size, oprnd_ext))
        tb.add(self._builder.gen_bsh(oprnd_ext, temp_count, oprnd_ext_shifted))
        tb.add(self._builder.gen_bsh(oprnd_ext_shifted, imm2, oprnd_ext_shifted_h))
        tb.add(self._builder.gen_str(oprnd_ext_shifted, oprnd_ext_shifted_l))
        tb.add(self._builder.gen_or(oprnd_ext_shifted_l, oprnd_ext_shifted_h, result))

        # Compute CF.
        tb.add(self._builder.gen_bsh(result, imm4, self._flags["cf"]))

        # Compute OF.
        undef_of_lbl = tb.label('undef_of_lbl')

        tb.add(self._builder.gen_sub(tmp0, imm1, tmp1))
        tb.add(self._builder.gen_bisz(tmp1, tmp1_zero))
        tb.add(self._builder.gen_jcc(tmp1_zero, undef_of_lbl))

        # Compute.
        tb.add(self._builder.gen_bsh(result, imm3, result_msb))
        tb.add(self._builder.gen_bsh(result, imm5, result_msb_prev))
        tb.add(self._builder.gen_xor(result_msb, result_msb_prev, self._flags["of"]))

        # Undef OF.
        tb.add(undef_of_lbl)
        self._undefine_flag(tb, self._flags["of"])

        tb.write(instruction.operands[0], result)

    def _translate_rcl(self, tb, instruction):
        # Flags Affected
        # The CF flag contains the value of the bit shifted into it.
        # The OF flag is affected only for single-bit rotates (see
        # "Description" above); it is undefined for multi-bit rotates.
        # The SF, ZF, AF, and PF flags are not affected.

        oprnd0 = tb.read(instruction.operands[0])
        oprnd1 = tb.read(instruction.operands[1])

        size = tb.immediate(oprnd0.size, oprnd0.size)

        tmp_cf_ext = tb.temporal(oprnd0.size * 2)
        tmp_cf_ext_1 = tb.temporal(oprnd0.size * 2)

        oprnd_ext = tb.temporal(oprnd0.size * 2)
        oprnd_ext_1 = tb.temporal(oprnd0.size * 2)
        oprnd_ext_shifted = tb.temporal(oprnd0.size * 2)
        oprnd_ext_shifted_l = tb.temporal(oprnd0.size)
        oprnd_ext_shifted_h = tb.temporal(oprnd0.size)

        result = tb.temporal(oprnd0.size)
        result_msb = tb.temporal(1)

        tmp1 = tb.temporal(1)
        tmp1_zero = tb.temporal(1)

        imm1 = tb.immediate(1, oprnd0.size)
        imm2 = tb.immediate(-(oprnd0.size + 1), oprnd0.size * 2)
        imm3 = tb.immediate(-(oprnd0.size + 1), oprnd0.size)
        imm4 = tb.immediate(oprnd0.size, oprnd0.size * 2)

        if oprnd0.size == 8:
            count_mask = tb.immediate(0x1f, oprnd0.size)
            tmp0 = tb.temporal(oprnd0.size)
            count = tb.temporal(oprnd0.size)
            temp_count = tb.temporal(oprnd0.size)
            mod_amount = tb.immediate(9, oprnd0.size)

            tb.add(self._builder.gen_str(oprnd1, count))

            tb.add(self._builder.gen_and(count, count_mask, tmp0))
            tb.add(self._builder.gen_mod(tmp0, mod_amount, temp_count))
        elif oprnd0.size == 16:
            count_mask = tb.immediate(0x1f, oprnd0.size)
            tmp0 = tb.temporal(oprnd0.size)
            count = tb.temporal(oprnd0.size)
            temp_count = tb.temporal(oprnd0.size)
            mod_amount = tb.immediate(17, oprnd0.size)

            tb.add(self._builder.gen_str(oprnd1, count))

            tb.add(self._builder.gen_and(count, count_mask, tmp0))
            tb.add(self._builder.gen_mod(tmp0, mod_amount, temp_count))
        elif oprnd0.size == 32:
            count_mask = tb.immediate(0x1f, oprnd0.size)
            tmp0 = tb.temporal(oprnd0.size)
            count = tb.temporal(oprnd0.size)
            temp_count = tb.temporal(oprnd0.size)

            tb.add(self._builder.gen_str(oprnd1, count))

            tb.add(self._builder.gen_and(count, count_mask, tmp0))
            tb.add(self._builder.gen_str(tmp0, temp_count))
        elif oprnd0.size == 64:
            count_mask = tb.immediate(0x3f, oprnd0.size)
            tmp0 = tb.temporal(oprnd0.size)
            count = tb.temporal(oprnd0.size)
            temp_count = tb.temporal(oprnd0.size)

            tb.add(self._builder.gen_str(oprnd1, count))

            tb.add(self._builder.gen_and(count, count_mask, tmp0))
            tb.add(self._builder.gen_str(tmp0, temp_count))
        else:
            raise Exception("Invalid operand size: %d", oprnd0.size)

        tb.add(self._builder.gen_str(oprnd0, oprnd_ext_1))

        # Insert CF.
        tb.add(self._builder.gen_str(self._flags["cf"], tmp_cf_ext))
        tb.add(self._builder.gen_bsh(tmp_cf_ext, imm4, tmp_cf_ext_1))
        tb.add(self._builder.gen_or(tmp_cf_ext_1, oprnd_ext_1, oprnd_ext))

        tb.add(self._builder.gen_bsh(oprnd_ext, temp_count, oprnd_ext_shifted))
        tb.add(self._builder.gen_bsh(oprnd_ext_shifted, imm2, oprnd_ext_shifted_h))
        tb.add(self._builder.gen_str(oprnd_ext_shifted, oprnd_ext_shifted_l))
        tb.add(self._builder.gen_or(oprnd_ext_shifted_l, oprnd_ext_shifted_h, result))

        # Compute CF.
        tb.add(self._builder.gen_str(result, self._flags["cf"]))

        # Compute OF.
        undef_of_lbl = tb.label('undef_of_lbl')

        tb.add(self._builder.gen_sub(count, imm1, tmp1))
        tb.add(self._builder.gen_bisz(tmp1, tmp1_zero))
        tb.add(self._builder.gen_jcc(tmp1_zero, undef_of_lbl))

        # Compute.
        tb.add(self._builder.gen_bsh(result, imm3, result_msb))
        tb.add(self._builder.gen_xor(result_msb, self._flags["cf"], self._flags["of"]))

        # Undef OF.
        tb.add(undef_of_lbl)
        self._undefine_flag(tb, self._flags["of"])

        tb.write(instruction.operands[0], result)

    def _translate_rcr(self, tb, instruction):
        # Flags Affected
        # The CF flag contains the value of the bit shifted into it.
        # The OF flag is affected only for single-bit rotates (see
        # "Description" above); it is undefined for multi-bit rotates.
        # The SF, ZF, AF, and PF flags are not affected.

        # XXX: Fix OF flag

        oprnd0 = tb.read(instruction.operands[0])
        oprnd1 = tb.read(instruction.operands[1])

        size = tb.immediate(oprnd0.size, oprnd0.size)
        msize = tb.immediate(-oprnd0.size, oprnd0.size)

        tmp0 = tb.temporal(oprnd0.size)
        tmp0_1 = tb.temporal(oprnd0.size)
        count = tb.temporal(oprnd0.size)
        temp_count = tb.temporal(oprnd0.size)
        zero = tb.immediate(0, oprnd0.size)

        # TODO: Improve this translation. It uses unecessary large
        # register...
        tmp_cf_ext = tb.temporal(oprnd0.size * 4)
        tmp_cf_ext_1 = tb.temporal(oprnd0.size * 4)

        oprnd_ext = tb.temporal(oprnd0.size * 4)
        oprnd_ext_1 = tb.temporal(oprnd0.size * 4)
        oprnd_ext_2 = tb.temporal(oprnd0.size * 4)
        oprnd_ext_shifted = tb.temporal(oprnd0.size * 4)
        oprnd_ext_shifted_l = tb.temporal(oprnd0.size)
        oprnd_ext_shifted_h = tb.temporal(oprnd0.size)
        oprnd_ext_shifted_h_1 = tb.temporal(oprnd0.size)

        result = tb.temporal(oprnd0.size)
        result_msb = tb.temporal(1)
        result_msb_prev = tb.temporal(1)

        tmp1 = tb.temporal(1)
        tmp1_zero = tb.temporal(1)

        imm1 = tb.immediate(1, oprnd0.size)
        imm7 = tb.immediate(-(oprnd0.size - 1), oprnd0.size)

        one = tb.immediate(1, oprnd0.size * 2)
        mone = tb.immediate(-1, oprnd0.size * 2)

        cf_old = tb.temporal(1)

        if oprnd0.size == 8:
            count_mask = tb.immediate(0x1f, oprnd0.size)
            tmp0 = tb.temporal(oprnd0.size)
            count = tb.temporal(oprnd0.size)
            temp_count = tb.temporal(oprnd0.size)
            mod_amount = tb.immediate(9, oprnd0.size)

            tb.add(self._builder.gen_str(oprnd1, count))
            tb.add(self._builder.gen_and(count, count_mask, tmp0_1))
            tb.add(self._builder.gen_mod(tmp0_1, mod_amount, tmp0))
        elif oprnd0.size == 16:
            count_mask = tb.immediate(0x1f, oprnd0.size)
            tmp0 = tb.temporal(oprnd0.size)
            count = tb.temporal(oprnd0.size)
            temp_count = tb.temporal(oprnd0.size)
            mod_amount = tb.immediate(17, oprnd0.size)

            tb.add(self._builder.gen_str(oprnd1, count))
            tb.add(self._builder.gen_and(count, count_mask, tmp0_1))
            tb.add(self._builder.gen_mod(tmp0_1, mod_amount, tmp0))
        elif oprnd0.size == 32:
            count_mask = tb.immediate(0x1f, oprnd0.size)
            tmp0 = tb.temporal(oprnd0.size)
            count = tb.temporal(oprnd0.size)
            temp_count = tb.temporal(oprnd0.size)

            tb.add(self._builder.gen_str(oprnd1, count))
            tb.add(self._builder.gen_and(count, count_mask, tmp0))
        elif oprnd0.size == 64:
            count_mask = tb.immediate(0x3f, oprnd0.size)
            tmp0 = tb.temporal(oprnd0.size)
            count = tb.temporal(oprnd0.size)
            temp_count = tb.temporal(oprnd0.size)

            tb.add(self._builder.gen_str(oprnd1, count))
            tb.add(self._builder.gen_and(count, count_mask, tmp0))
        else:
            raise Exception("Invalid operand size: %d", oprnd0.size)

        tb.add(self._builder.gen_sub(zero, tmp0, temp_count))

        # Backup CF.
        tb.add(self._builder.gen_str(self._flags["cf"], cf_old))

        # Insert CF.
        tb.add(self._builder.gen_bsh(oprnd0, one, oprnd_ext_1))
        tb.add(self._builder.gen_str(self._flags["cf"], tmp_cf_ext))
        tb.add(self._builder.gen_or(tmp_cf_ext, oprnd_ext_1, oprnd_ext_2))

        # Rotate register.
        tb.add(self._builder.gen_bsh(oprnd_ext_2, size, oprnd_ext))

        tb.add(self._builder.gen_bsh(oprnd_ext, temp_count, oprnd_ext_shifted))
        tb.add(self._builder.gen_bsh(oprnd_ext_shifted, msize, oprnd_ext_shifted_h_1))
        tb.add(self._builder.gen_bsh(oprnd_ext_shifted_h_1, mone, oprnd_ext_shifted_h))
        tb.add(self._builder.gen_str(oprnd_ext_shifted, oprnd_ext_shifted_l))
        tb.add(self._builder.gen_or(oprnd_ext_shifted_l, oprnd_ext_shifted_h, result))

        # Compute CF.
        tb.add(self._builder.gen_str(oprnd_ext_shifted_h_1, self._flags["cf"]))

        # Compute OF.
        undef_of_lbl = tb.label('undef_of_lbl')

        tb.add(self._builder.gen_sub(count, imm1, tmp1))
        tb.add(self._builder.gen_bisz(tmp1, tmp1_zero))
        tb.add(self._builder.gen_jcc(tmp1_zero, undef_of_lbl))

        # Compute.
        tb.add(self._builder.gen_bsh(oprnd0, imm7, result_msb))
        tb.add(self._builder.gen_xor(result_msb, cf_old, self._flags["of"]))

        # Undef OF.
        tb.add(undef_of_lbl)
        self._undefine_flag(tb, self._flags["of"])

        tb.write(instruction.operands[0], result)

# "Bit and Byte Instructions"
# ============================================================================ #
    def _translate_test(self, tb, instruction):
        # Flags Affected
        # The OF and CF flags are set to 0. The SF, ZF, and PF flags are
        # set according to the result (see the "Operation" section
        # above). The state of the AF flag is undefined.

        oprnd0 = tb.read(instruction.operands[0])
        oprnd1 = tb.read(instruction.operands[1])

        tmp0 = tb.temporal(oprnd0.size)

        tb.add(self._builder.gen_and(oprnd0, oprnd1, tmp0))

        # Flags : OF, CF
        self._clear_flag(tb, self._flags["of"])
        self._clear_flag(tb, self._flags["cf"])

        # Flags : SF, ZF, PF
        self._update_sf(tb, oprnd0, oprnd1, tmp0)
        self._update_zf(tb, oprnd0, oprnd1, tmp0)
        self._update_pf(tb, oprnd0, oprnd1, tmp0)

        # Flags : AF
        self._undefine_flag(tb, self._flags["af"])

    def _translate_setne(self, tb, instruction):
        # Set byte if not equal (ZF=0).

        imm0 = tb.immediate(1, 1)

        tmp0 = tb.temporal(instruction.operands[0].size)

        tb.add(self._builder.gen_xor(self._flags["zf"], imm0, tmp0))

        tb.write(instruction.operands[0], tmp0)

    def _translate_sete(self, tb, instruction):
        # Set byte if equal (ZF=1).

        imm0 = tb.immediate(1, 1)

        tmp0 = tb.temporal(instruction.operands[0].size)

        tb.add(self._builder.gen_and(self._flags["zf"], imm0, tmp0))

        tb.write(instruction.operands[0], tmp0)

    def _translate_setb(self, tb, instruction):
        # Set byte if below (CF=1).

        tb.write(instruction.operands[0], self._flags["cf"])

    def _translate_setbe(self, tb, instruction):
        # Set byte if below or equal (CF=1 or ZF=1).

        tmp0 = tb.temporal(instruction.operands[0].size)

        tb.add(self._builder.gen_or(self._flags["cf"], self._flags["zf"], tmp0))

        tb.write(instruction.operands[0], tmp0)

    def _translate_setae(self, tb, instruction):
        # Set byte if above or equal (CF=0).

        tmp0 = tb.temporal(instruction.operands[0].size)

        tb.add(self._builder.gen_bisz(self._flags["cf"], tmp0))

        tb.write(instruction.operands[0], tmp0)

    def _translate_setg(self, tb, instruction):
        # Set byte if greater (ZF=0 and SF=OF).

        imm0 = tb.immediate(1, 1)

        tmp0 = tb.temporal(8)
        tmp1 = tb.temporal(1)
        tmp2 = tb.temporal(1)
        tmp3 = tb.temporal(instruction.operands[0].size)

        tb.add(self._builder.gen_sub(self._flags["sf"], self._flags["of"], tmp0))
        tb.add(self._builder.gen_bisz(tmp0, tmp1))
        tb.add(self._builder.gen_xor(self._flags["zf"], imm0, tmp2))
        tb.add(self._builder.gen_and(tmp1, tmp2, tmp3))

        tb.write(instruction.operands[0], tmp3)

# "Control Transfer Instructions"
# ============================================================================ #
    def _translate_address(self, tb, oprnd):
        addr_oprnd_size = oprnd.size + 8

        if isinstance(oprnd, ReilRegisterOperand):
            oprnd_tmp = tb.temporal(addr_oprnd_size)
            addr_oprnd = tb.temporal(addr_oprnd_size)
            imm = ReilImmediateOperand(8, addr_oprnd_size)

            tb.add(self._builder.gen_str(oprnd, oprnd_tmp))
            tb.add(self._builder.gen_bsh(oprnd_tmp, imm, addr_oprnd))
        elif isinstance(oprnd, ReilImmediateOperand):
            addr_oprnd = ReilImmediateOperand(oprnd.immediate << 8, addr_oprnd_size)

        return addr_oprnd

    def _translate_jmp(self, tb, instruction):
        # Flags Affected
        # All flags are affected if a task switch occurs; no flags are
        # affected if a task switch does not occur.

        oprnd0 = tb.read(instruction.operands[0])

        addr_oprnd = self._translate_address(tb, oprnd0)

        imm0 = tb.immediate(1, 1)

        tb.add(self._builder.gen_jcc(imm0, addr_oprnd))

    def _translate_ja(self, tb, instruction):
        # Jump near if above (CF=0 and ZF=0).

        oprnd0 = tb.read(instruction.operands[0])

        addr_oprnd = self._translate_address(tb, oprnd0)

        imm0 = tb.immediate(1, 1)

        tmp0 = tb.temporal(1)
        tmp1 = tb.temporal(1)
        tmp2 = tb.temporal(1)

        tb.add(self._builder.gen_xor(self._flags["cf"], imm0, tmp0))
        tb.add(self._builder.gen_xor(self._flags["zf"], imm0, tmp1))
        tb.add(self._builder.gen_and(tmp0, tmp1, tmp2))
        tb.add(self._builder.gen_jcc(tmp2, addr_oprnd))

    def _translate_jo(self, tb, instruction):
        # Jump near if overflow (OF=1).

        oprnd0 = tb.read(instruction.operands[0])

        addr_oprnd = self._translate_address(tb, oprnd0)

        tb.add(self._builder.gen_jcc(self._flags["of"], addr_oprnd))

    def _translate_jbe(self, tb, instruction):
        # Jump near if below or equal (CF=1 or ZF=1).

        oprnd0 = tb.read(instruction.operands[0])

        addr_oprnd = self._translate_address(tb, oprnd0)

        tmp0 = tb.temporal(1)

        tb.add(self._builder.gen_or(self._flags["cf"], self._flags["zf"], tmp0))
        tb.add(self._builder.gen_jcc(tmp0, addr_oprnd))

    def _translate_jl(self, tb, instruction):
        # Jump near if less (SF!=OF).

        oprnd0 = tb.read(instruction.operands[0])

        addr_oprnd = self._translate_address(tb, oprnd0)

        imm0 = tb.immediate(1, 1)

        tmp0 = tb.temporal(8)
        tmp1 = tb.temporal(1)
        tmp2 = tb.temporal(1)

        tb.add(self._builder.gen_sub(self._flags["sf"], self._flags["of"], tmp0))
        tb.add(self._builder.gen_bisz(tmp0, tmp1))
        tb.add(self._builder.gen_xor(tmp1, imm0, tmp2))
        tb.add(self._builder.gen_jcc(tmp2, addr_oprnd))

    def _translate_je(self, tb, instruction):
        # Jump near if equal (ZF=1).

        oprnd0 = tb.read(instruction.operands[0])

        addr_oprnd = self._translate_address(tb, oprnd0)

        tb.add(self._builder.gen_jcc(self._flags["zf"], addr_oprnd))

    def _translate_js(self, tb, instruction):
        # Jump near if sign (SF=1).

        oprnd0 = tb.read(instruction.operands[0])

        addr_oprnd = self._translate_address(tb, oprnd0)

        tb.add(self._builder.gen_jcc(self._flags["sf"], addr_oprnd))

    def _translate_jg(self, tb, instruction):
        # Jump near if greater (ZF=0 and SF=OF).

        oprnd0 = tb.read(instruction.operands[0])

        addr_oprnd = self._translate_address(tb, oprnd0)

        imm0 = tb.immediate(1, 1)

        tmp0 = tb.temporal(8)
        tmp1 = tb.temporal(1)
        tmp2 = tb.temporal(1)
        tmp3 = tb.temporal(1)

        tb.add(self._builder.gen_sub(self._flags["sf"], self._flags["of"], tmp0))
        tb.add(self._builder.gen_bisz(tmp0, tmp1))
        tb.add(self._builder.gen_xor(self._flags["zf"], imm0, tmp2))
        tb.add(self._builder.gen_and(tmp1, tmp2, tmp3))
        tb.add(self._builder.gen_jcc(tmp3, addr_oprnd))

    def _translate_jge(self, tb, instruction):
        # Jump near if greater or equal (SF=OF).

        oprnd0 = tb.read(instruction.operands[0])

        addr_oprnd = self._translate_address(tb, oprnd0)

        tmp0 = tb.temporal(8)
        tmp1 = tb.temporal(1)

        tb.add(self._builder.gen_sub(self._flags["sf"], self._flags["of"], tmp0))
        tb.add(self._builder.gen_bisz(tmp0, tmp1))
        tb.add(self._builder.gen_jcc(tmp1, addr_oprnd))

    def _translate_jae(self, tb, instruction):
        # Jump near if above or equal (CF=0).

        oprnd0 = tb.read(instruction.operands[0])

        addr_oprnd = self._translate_address(tb, oprnd0)

        tmp0 = tb.temporal(1)

        tb.add(self._builder.gen_bisz(self._flags["cf"], tmp0))
        tb.add(self._builder.gen_jcc(tmp0, addr_oprnd))

    def _translate_jno(self, tb, instruction):
        # Jump near if not overflow (OF=0).

        oprnd0 = tb.read(instruction.operands[0])

        addr_oprnd = self._translate_address(tb, oprnd0)

        tmp0 = tb.temporal(1)

        tb.add(self._builder.gen_bisz(self._flags["of"], tmp0))
        tb.add(self._builder.gen_jcc(tmp0, addr_oprnd))

    def _translate_jns(self, tb, instruction):
        # Jump near if not sign (SF=0).

        oprnd0 = tb.read(instruction.operands[0])

        addr_oprnd = self._translate_address(tb, oprnd0)

        tmp0 = tb.temporal(1)

        tb.add(self._builder.gen_bisz(self._flags["sf"], tmp0))
        tb.add(self._builder.gen_jcc(tmp0, addr_oprnd))

    def _translate_jb(self, tb, instruction):
        # Jump near if below (CF=1).

        oprnd0 = tb.read(instruction.operands[0])

        addr_oprnd = self._translate_address(tb, oprnd0)

        tb.add(self._builder.gen_jcc(self._flags["cf"], addr_oprnd))

    def _translate_jle(self, tb, instruction):
        # Jump near if less or equal (ZF=1 or SF!=OF).

        oprnd0 = tb.read(instruction.operands[0])

        addr_oprnd = self._translate_address(tb, oprnd0)

        imm0 = tb.immediate(1, 1)

        tmp0 = tb.temporal(8)
        tmp1 = tb.temporal(1)
        tmp2 = tb.temporal(1)
        tmp3 = tb.temporal(1)

        tb.add(self._builder.gen_sub(self._flags["sf"], self._flags["of"], tmp0))
        tb.add(self._builder.gen_bisz(tmp0, tmp1))
        tb.add(self._builder.gen_xor(tmp1, imm0, tmp2))
        tb.add(self._builder.gen_or(tmp2, self._flags["zf"], tmp3))
        tb.add(self._builder.gen_jcc(tmp3, addr_oprnd))

    def _translate_jz(self, tb, instruction):
        # Jump near if 0 (ZF=1).

        oprnd0 = tb.read(instruction.operands[0])

        addr_oprnd = self._translate_address(tb, oprnd0)

        tb.add(self._builder.gen_jcc(self._flags["zf"], addr_oprnd))

    def _translate_jne(self, tb, instruction):
        # Jump near if not equal (ZF=0).

        oprnd0 = tb.read(instruction.operands[0])

        addr_oprnd = self._translate_address(tb, oprnd0)

        imm0 = tb.immediate(1, 1)

        tmp0 = tb.temporal(1)

        tb.add(self._builder.gen_xor(self._flags["zf"], imm0, tmp0))
        tb.add(self._builder.gen_jcc(tmp0, addr_oprnd))

    def _translate_jnz(self, tb, instruction):
        # Jump near if not zero (ZF=0).

        oprnd0 = tb.read(instruction.operands[0])

        addr_oprnd = self._translate_address(tb, oprnd0)

        imm0 = tb.immediate(1, 1)

        tmp0 = tb.temporal(1)

        tb.add(self._builder.gen_xor(self._flags["zf"], imm0, tmp0))
        tb.add(self._builder.gen_jcc(tmp0, addr_oprnd))

    def _translate_jnbe(self, tb, instruction):
        # Jump near if not below or equal (CF=0 and ZF=0).

        oprnd0 = tb.read(instruction.operands[0])

        addr_oprnd = self._translate_address(tb, oprnd0)

        imm0 = tb.immediate(1, 1)

        tmp0 = tb.temporal(1)
        tmp1 = tb.temporal(1)
        tmp2 = tb.temporal(1)

        tb.add(self._builder.gen_xor(self._flags["cf"], imm0, tmp0))
        tb.add(self._builder.gen_xor(self._flags["zf"], imm0, tmp1))
        tb.add(self._builder.gen_and(tmp0, tmp1, tmp2))
        tb.add(self._builder.gen_jcc(tmp2, addr_oprnd))

    def _translate_jc(self, tb, instruction):
        # Jump near if carry (CF=1).

        oprnd0 = tb.read(instruction.operands[0])

        addr_oprnd = self._translate_address(tb, oprnd0)

        tb.add(self._builder.gen_jcc(self._flags["cf"], addr_oprnd))

    def _translate_jnc(self, tb, instruction):
        # Jump near if not carry (CF=0).

        oprnd0 = tb.read(instruction.operands[0])

        addr_oprnd = self._translate_address(tb, oprnd0)

        imm0 = tb.immediate(1, 1)

        tmp0 = tb.temporal(1)

        tb.add(self._builder.gen_xor(self._flags["cf"], imm0, tmp0))
        tb.add(self._builder.gen_jcc(tmp0, addr_oprnd))

    def _translate_jecxz(self, tb, instruction):
        # Jump short if ECX register is 0.

        oprnd0 = tb.read(instruction.operands[0])

        addr_oprnd = self._translate_address(tb, oprnd0)

        tmp0 = tb.temporal(1)

        ecx = ReilRegisterOperand("ecx", 32)

        tb.add(self._builder.gen_bisz(ecx, tmp0))
        tb.add(self._builder.gen_jcc(tmp0, addr_oprnd))

    def _translate_call(self, tb, instruction):
        # Flags Affected
        # All flags are affected if a task switch occurs; no flags are
        # affected if a task switch does not occur.

        oprnd0 = tb.read(instruction.operands[0])

        addr_oprnd = self._translate_address(tb, oprnd0)

        imm1 = tb.immediate(1, 1)
        size = tb.immediate(instruction.size, self._sp.size)

        tmp0 = tb.temporal(self._sp.size)
        tmp1 = tb.temporal(self._sp.size)

        tb.add(self._builder.gen_sub(self._sp, self._ws, tmp0))
        tb.add(self._builder.gen_str(tmp0, self._sp))
        tb.add(self._builder.gen_add(self._ip, size, tmp1))
        tb.add(self._builder.gen_stm(tmp1, self._sp))
        tb.add(self._builder.gen_jcc(imm1, addr_oprnd))

    def _translate_ret(self, tb, instruction):
        # Flags Affected
        # None.

        tmp0 = tb.temporal(self._sp.size)
        tmp1 = tb.temporal(self._sp.size)

        tb.add(self._builder.gen_ldm(self._sp, tmp1))
        tb.add(self._builder.gen_add(self._sp, self._ws, tmp0))
        tb.add(self._builder.gen_str(tmp0, self._sp))

        # Free stack.
        if len(instruction.operands) > 0:
            oprnd0 = tb.read(instruction.operands[0])

            imm0 = tb.immediate(oprnd0.immediate & (2**self._sp.size -1), self._sp.size)

            tmp2 = tb.temporal(self._sp.size)

            tb.add(self._builder.gen_add(self._sp, imm0, tmp2))
            tb.add(self._builder.gen_str(tmp2, self._sp))

        # TODO: Replace RET instruction with JCC [BYTE 0x1, EMPTY, {D,Q}WORD %0]
        tb.add(self._builder.gen_ret())

    def _translate_loop(self, tb, instruction):
        # Flags Affected
        # None.

        if self._arch_mode == ARCH_X86_MODE_32:
            counter = ReilRegisterOperand("ecx", 32)
        elif self._arch_mode == ARCH_X86_MODE_64:
            counter = ReilRegisterOperand("rcx", 64)

        oprnd0 = tb.read(instruction.operands[0])

        addr_oprnd = self._translate_address(tb, oprnd0)

        end_addr = ReilImmediateOperand((instruction.address + instruction.size) << 8, self._arch_info.address_size + 8)

        tmp0 = tb.temporal(counter.size)
        exit_cond = tb.temporal(1)

        imm0 = tb.immediate(1, counter.size)

        stop_looping_lbl = tb.label('stop_looping')

        tb.add(self._builder.gen_str(counter, tmp0))
        tb.add(self._builder.gen_sub(tmp0, imm0, counter))
        tb.add(self._builder.gen_bisz(counter, exit_cond))
        tb.add(self._builder.gen_jcc(exit_cond, stop_looping_lbl))
        tb.add(self._builder.gen_jcc(imm0, addr_oprnd)) # keep looping
        tb.add(stop_looping_lbl)
        tb.add(self._builder.gen_jcc(imm0, end_addr))

    def _translate_loopne(self, tb, instruction):
        # Flags Affected
        # None.

        if self._arch_mode == ARCH_X86_MODE_32:
            counter = ReilRegisterOperand("ecx", 32)
        elif self._arch_mode == ARCH_X86_MODE_64:
            counter = ReilRegisterOperand("rcx", 64)

        oprnd0 = tb.read(instruction.operands[0])

        addr_oprnd = self._translate_address(tb, oprnd0)

        end_addr = ReilImmediateOperand((instruction.address + instruction.size) << 8, self._arch_info.address_size + 8)

        tmp0 = tb.temporal(counter.size)

        counter_zero = tb.temporal(1)
        counter_not_zero = tb.temporal(1)
        zf_zero = tb.temporal(1)
        branch_cond = tb.temporal(1)

        imm0 = tb.immediate(1, counter.size)
        imm1 = tb.immediate(1, 1)

        keep_looping_lbl = tb.label('keep_looping')

        tb.add(self._builder.gen_str(counter, tmp0))
        tb.add(self._builder.gen_sub(tmp0, imm0, counter))
        tb.add(self._builder.gen_bisz(counter, counter_zero))
        tb.add(self._builder.gen_bisz(self._flags["zf"], zf_zero))
        tb.add(self._builder.gen_xor(counter_zero, imm1, counter_not_zero))
        tb.add(self._builder.gen_and(counter_not_zero, zf_zero, branch_cond))
        tb.add(self._builder.gen_jcc(branch_cond, keep_looping_lbl))
        tb.add(self._builder.gen_jcc(imm0, end_addr)) # exit loop
        tb.add(keep_looping_lbl)
        tb.add(self._builder.gen_jcc(imm0, addr_oprnd))

    def _translate_loopnz(self, tb, instruction):
        return self._translate_loopne(tb, instruction)

    def _translate_loope(self, tb, instruction):
        # Flags Affected
        # None.

        if self._arch_mode == ARCH_X86_MODE_32:
            counter = ReilRegisterOperand("ecx", 32)
        elif self._arch_mode == ARCH_X86_MODE_64:
            counter = ReilRegisterOperand("rcx", 64)

        oprnd0 = tb.read(instruction.operands[0])

        addr_oprnd = self._translate_address(tb, oprnd0)

        end_addr = ReilImmediateOperand((instruction.address + instruction.size) << 8, self._arch_info.address_size + 8)

        tmp0 = tb.temporal(counter.size)

        counter_zero = tb.temporal(1)
        counter_not_zero = tb.temporal(1)
        zf_zero = tb.temporal(1)
        zf_not_zero = tb.temporal(1)
        branch_cond = tb.temporal(1)

        imm0 = tb.immediate(1, counter.size)
        imm1 = tb.immediate(1, 1)

        keep_looping_lbl = tb.label('keep_looping')

        tb.add(self._builder.gen_str(counter, tmp0))
        tb.add(self._builder.gen_sub(tmp0, imm0, counter))
        tb.add(self._builder.gen_bisz(counter, counter_zero))
        tb.add(self._builder.gen_bisz(self._flags["zf"], zf_zero))
        tb.add(self._builder.gen_xor(zf_zero, imm1, zf_not_zero))
        tb.add(self._builder.gen_xor(counter_zero, imm1, counter_not_zero))
        tb.add(self._builder.gen_and(counter_not_zero, zf_not_zero, branch_cond))
        tb.add(self._builder.gen_jcc(branch_cond, keep_looping_lbl))
        tb.add(self._builder.gen_jcc(imm0, end_addr)) # exit loop
        tb.add(keep_looping_lbl)
        tb.add(self._builder.gen_jcc(imm0, addr_oprnd))

    def _translate_loopz(self, tb, instruction):
        return self._translate_loope(tb, instruction)

# "String Instructions"
# ============================================================================ #

# "I/O Instructions"
# ============================================================================ #

# "Enter and Leave Instructions"
# ============================================================================ #
    def _translate_leave(self, tb, instruction):
        # Flags Affected
        # None.

        tmp0 = tb.temporal(self._sp.size)

        tb.add(self._builder.gen_str(self._bp, self._sp))
        tb.add(self._builder.gen_ldm(self._sp, self._bp))
        tb.add(self._builder.gen_add(self._sp, self._ws, tmp0))
        tb.add(self._builder.gen_str(tmp0, self._sp))

# "Flag Control (EFLAG) Instructions"
# ============================================================================ #
    def _translate_cld(self, tb, instruction):
        # Flags Affected
        # The DF flag is set to 0. The CF, OF, ZF, SF, AF, and PF flags
        # are unaffected.

        self._clear_flag(tb, self._flags["df"])

    def _translate_clc(self, tb, instruction):
        # Flags Affected
        # The CF flag is set to 0. The OF, ZF, SF, AF, and PF flags are
        # unaffected.

        self._clear_flag(tb, self._flags["cf"])

    def _translate_stc(self, tb, instruction):
        # Flags Affected
        # The CF flag is set. The OF, ZF, SF, AF, and PF flags are
        # unaffected.

        self._set_flag(tb, self._flags["cf"])

    def _translate_std(self, tb, instruction):
        # Flags Affected
        # The DF flag is set. The CF, OF, ZF, SF, AF, and PF flags are
        # unaffected.

        self._set_flag(tb, self._flags["df"])

# "Segment Register Instructions"
# ============================================================================ #

# "Miscellaneous Instructions"
# ============================================================================ #
    def _translate_lea(self, tb, instruction):
        # Flags Affected
        # None.

        oprnd1 = tb._compute_memory_address(instruction.operands[1])

        tb.write(instruction.operands[0], oprnd1)

    def _translate_nop(self, tb, instruction):
        # Flags Affected
        # None.

        tb.add(self._builder.gen_nop())

# "Random Number Generator Instruction"
# ============================================================================ #

# "Misc"
# ============================================================================ #
    def _translate_hlt(self, tb, instruction):
        # Flags Affected
        # None.

        tb.add(self._builder.gen_unkn())

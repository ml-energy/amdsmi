# Copyright (C) Advanced Micro Devices. All rights reserved.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of
# this software and associated documentation files (the "Software"), to deal in
# the Software without restriction, including without limitation the rights to
# use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of
# the Software, and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS
# FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
# COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER
# IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
# CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

import os
# -*- coding: utf-8 -*-
#
# TARGET arch is: ['-I/usr/lib/llvm-16/lib/clang/16/include', '-DENABLE_ESMI_LIB']
# WORD_SIZE is: 8
# POINTER_SIZE is: 8
# LONGDOUBLE_SIZE is: 16
#
import ctypes


c_int128 = ctypes.c_ubyte*16
c_uint128 = c_int128
void = None
if ctypes.sizeof(ctypes.c_longdouble) == 16:
    c_long_double_t = ctypes.c_longdouble
else:
    c_long_double_t = ctypes.c_ubyte*16

class AsDictMixin:
    @classmethod
    def as_dict(cls, self):
        result = {}
        if not isinstance(self, AsDictMixin):
            # not a structure, assume it's already a python object
            return self
        if not hasattr(cls, "_fields_"):
            return result
        # sys.version_info >= (3, 5)
        # for (field, *_) in cls._fields_:  # noqa
        for field_tuple in cls._fields_:  # noqa
            field = field_tuple[0]
            if field.startswith('PADDING_'):
                continue
            value = getattr(self, field)
            type_ = type(value)
            if hasattr(value, "_length_") and hasattr(value, "_type_"):
                # array
                if not hasattr(type_, "as_dict"):
                    value = [v for v in value]
                else:
                    type_ = type_._type_
                    value = [type_.as_dict(v) for v in value]
            elif hasattr(value, "contents") and hasattr(value, "_type_"):
                # pointer
                try:
                    if not hasattr(type_, "as_dict"):
                        value = value.contents
                    else:
                        type_ = type_._type_
                        value = type_.as_dict(value.contents)
                except ValueError:
                    # nullptr
                    value = None
            elif isinstance(value, AsDictMixin):
                # other structure
                value = type_.as_dict(value)
            result[field] = value
        return result


class Structure(ctypes.Structure, AsDictMixin):

    def __init__(self, *args, **kwds):
        # We don't want to use positional arguments fill PADDING_* fields

        args = dict(zip(self.__class__._field_names_(), args))
        args.update(kwds)
        super(Structure, self).__init__(**args)

    @classmethod
    def _field_names_(cls):
        if hasattr(cls, '_fields_'):
            return (f[0] for f in cls._fields_ if not f[0].startswith('PADDING'))
        else:
            return ()

    @classmethod
    def get_type(cls, field):
        for f in cls._fields_:
            if f[0] == field:
                return f[1]
        return None

    @classmethod
    def bind(cls, bound_fields):
        fields = {}
        for name, type_ in cls._fields_:
            if hasattr(type_, "restype"):
                if name in bound_fields:
                    if bound_fields[name] is None:
                        fields[name] = type_()
                    else:
                        # use a closure to capture the callback from the loop scope
                        fields[name] = (
                            type_((lambda callback: lambda *args: callback(*args))(
                                bound_fields[name]))
                        )
                    del bound_fields[name]
                else:
                    # default callback implementation (does nothing)
                    try:
                        default_ = type_(0).restype().value
                    except TypeError:
                        default_ = None
                    fields[name] = type_((
                        lambda default_: lambda *args: default_)(default_))
            else:
                # not a callback function, use default initialization
                if name in bound_fields:
                    fields[name] = bound_fields[name]
                    del bound_fields[name]
                else:
                    fields[name] = type_()
        if len(bound_fields) != 0:
            raise ValueError(
                "Cannot bind the following unknown callback(s) {}.{}".format(
                    cls.__name__, bound_fields.keys()
            ))
        return cls(**fields)


class Union(ctypes.Union, AsDictMixin):
    pass



def string_cast(char_pointer, encoding='utf-8', errors='strict'):
    value = ctypes.cast(char_pointer, ctypes.c_char_p).value
    if value is not None and encoding is not None:
        value = value.decode(encoding, errors=errors)
    return value


def char_pointer_cast(string, encoding='utf-8'):
    if encoding is not None:
        try:
            string = string.encode(encoding)
        except AttributeError:
            # In Python3, bytes has no encode attribute
            pass
    string = ctypes.c_char_p(string)
    return ctypes.cast(string, ctypes.POINTER(ctypes.c_char))



_libraries = {}
from pathlib import Path
# libamd_smi.so can be located in several different places.
# Look for it with below priority:
# 1. ROCM_HOME/ROCM_PATH environment variables
#    - ROCM_HOME/lib
#    - ROCM_PATH/lib (usually set to /opt/rocm/)
# 2. Decided by the linker
#    - LD_LIBRARY_PATH env var
#    - defined path in /etc/ld.so.conf.d/
# 3. Relative to amdsmi_wrapper.py
#    - parent directory
#    - current directory
def find_smi_library():
    err = OSError("Could not load libamd_smi.so")
    possible_locations = list()
    # 1.
    rocm_path = os.getenv("ROCM_HOME", os.getenv("ROCM_PATH"))
    if rocm_path:
        possible_locations.append(os.path.join(rocm_path, "lib/libamd_smi.so"))
    # 2.
    possible_locations.append("libamd_smi.so")
    # 3.
    libamd_smi_parent_dir = Path(__file__).resolve().parent / "libamd_smi.so"
    libamd_smi_cwd = Path(os.getenv("ROCM_PATH", "/opt/rocm")) / "lib" / "libamd_smi.so"
    possible_locations.append(libamd_smi_parent_dir)
    possible_locations.append(libamd_smi_cwd)

    for location in possible_locations:
        try:
            lib = ctypes.CDLL(location)
            return lib, location
        except OSError as e:
            err = e
            continue
    raise err

try:
    _libraries['libamd_smi.so'], location = find_smi_library()
    #print(f"found smi lib in [", location, "]")
except OSError as e:
    print(e)
    print("Unable to find libamd_smi.so library try installing amd-smi-lib from your package manager")



# values for enumeration 'amdsmi_init_flags_t'
amdsmi_init_flags_t__enumvalues = {
    4294967295: 'AMDSMI_INIT_ALL_PROCESSORS',
    1: 'AMDSMI_INIT_AMD_CPUS',
    2: 'AMDSMI_INIT_AMD_GPUS',
    4: 'AMDSMI_INIT_NON_AMD_CPUS',
    8: 'AMDSMI_INIT_NON_AMD_GPUS',
    3: 'AMDSMI_INIT_AMD_APUS',
}
AMDSMI_INIT_ALL_PROCESSORS = 4294967295
AMDSMI_INIT_AMD_CPUS = 1
AMDSMI_INIT_AMD_GPUS = 2
AMDSMI_INIT_NON_AMD_CPUS = 4
AMDSMI_INIT_NON_AMD_GPUS = 8
AMDSMI_INIT_AMD_APUS = 3
amdsmi_init_flags_t = ctypes.c_uint32 # enum

# values for enumeration 'amdsmi_mm_ip_t'
amdsmi_mm_ip_t__enumvalues = {
    0: 'AMDSMI_MM_UVD',
    1: 'AMDSMI_MM_VCE',
    2: 'AMDSMI_MM_VCN',
    3: 'AMDSMI_MM__MAX',
}
AMDSMI_MM_UVD = 0
AMDSMI_MM_VCE = 1
AMDSMI_MM_VCN = 2
AMDSMI_MM__MAX = 3
amdsmi_mm_ip_t = ctypes.c_uint32 # enum

# values for enumeration 'amdsmi_container_types_t'
amdsmi_container_types_t__enumvalues = {
    0: 'AMDSMI_CONTAINER_LXC',
    1: 'AMDSMI_CONTAINER_DOCKER',
}
AMDSMI_CONTAINER_LXC = 0
AMDSMI_CONTAINER_DOCKER = 1
amdsmi_container_types_t = ctypes.c_uint32 # enum
amdsmi_processor_handle = ctypes.POINTER(None)
amdsmi_socket_handle = ctypes.POINTER(None)
amdsmi_cpusocket_handle = ctypes.POINTER(None)
class struct_amdsmi_hsmp_driver_version_t(Structure):
    pass

struct_amdsmi_hsmp_driver_version_t._pack_ = 1 # source:False
struct_amdsmi_hsmp_driver_version_t._fields_ = [
    ('major', ctypes.c_uint32),
    ('minor', ctypes.c_uint32),
]

amdsmi_hsmp_driver_version_t = struct_amdsmi_hsmp_driver_version_t

# values for enumeration 'processor_type_t'
processor_type_t__enumvalues = {
    0: 'AMDSMI_PROCESSOR_TYPE_UNKNOWN',
    1: 'AMDSMI_PROCESSOR_TYPE_AMD_GPU',
    2: 'AMDSMI_PROCESSOR_TYPE_AMD_CPU',
    3: 'AMDSMI_PROCESSOR_TYPE_NON_AMD_GPU',
    4: 'AMDSMI_PROCESSOR_TYPE_NON_AMD_CPU',
    5: 'AMDSMI_PROCESSOR_TYPE_AMD_CPU_CORE',
    6: 'AMDSMI_PROCESSOR_TYPE_AMD_APU',
}
AMDSMI_PROCESSOR_TYPE_UNKNOWN = 0
AMDSMI_PROCESSOR_TYPE_AMD_GPU = 1
AMDSMI_PROCESSOR_TYPE_AMD_CPU = 2
AMDSMI_PROCESSOR_TYPE_NON_AMD_GPU = 3
AMDSMI_PROCESSOR_TYPE_NON_AMD_CPU = 4
AMDSMI_PROCESSOR_TYPE_AMD_CPU_CORE = 5
AMDSMI_PROCESSOR_TYPE_AMD_APU = 6
processor_type_t = ctypes.c_uint32 # enum

# values for enumeration 'amdsmi_status_t'
amdsmi_status_t__enumvalues = {
    0: 'AMDSMI_STATUS_SUCCESS',
    1: 'AMDSMI_STATUS_INVAL',
    2: 'AMDSMI_STATUS_NOT_SUPPORTED',
    3: 'AMDSMI_STATUS_NOT_YET_IMPLEMENTED',
    4: 'AMDSMI_STATUS_FAIL_LOAD_MODULE',
    5: 'AMDSMI_STATUS_FAIL_LOAD_SYMBOL',
    6: 'AMDSMI_STATUS_DRM_ERROR',
    7: 'AMDSMI_STATUS_API_FAILED',
    8: 'AMDSMI_STATUS_TIMEOUT',
    9: 'AMDSMI_STATUS_RETRY',
    10: 'AMDSMI_STATUS_NO_PERM',
    11: 'AMDSMI_STATUS_INTERRUPT',
    12: 'AMDSMI_STATUS_IO',
    13: 'AMDSMI_STATUS_ADDRESS_FAULT',
    14: 'AMDSMI_STATUS_FILE_ERROR',
    15: 'AMDSMI_STATUS_OUT_OF_RESOURCES',
    16: 'AMDSMI_STATUS_INTERNAL_EXCEPTION',
    17: 'AMDSMI_STATUS_INPUT_OUT_OF_BOUNDS',
    18: 'AMDSMI_STATUS_INIT_ERROR',
    19: 'AMDSMI_STATUS_REFCOUNT_OVERFLOW',
    30: 'AMDSMI_STATUS_BUSY',
    31: 'AMDSMI_STATUS_NOT_FOUND',
    32: 'AMDSMI_STATUS_NOT_INIT',
    33: 'AMDSMI_STATUS_NO_SLOT',
    34: 'AMDSMI_STATUS_DRIVER_NOT_LOADED',
    40: 'AMDSMI_STATUS_NO_DATA',
    41: 'AMDSMI_STATUS_INSUFFICIENT_SIZE',
    42: 'AMDSMI_STATUS_UNEXPECTED_SIZE',
    43: 'AMDSMI_STATUS_UNEXPECTED_DATA',
    44: 'AMDSMI_STATUS_NON_AMD_CPU',
    45: 'AMDSMI_STATUS_NO_ENERGY_DRV',
    46: 'AMDSMI_STATUS_NO_MSR_DRV',
    47: 'AMDSMI_STATUS_NO_HSMP_DRV',
    48: 'AMDSMI_STATUS_NO_HSMP_SUP',
    49: 'AMDSMI_STATUS_NO_HSMP_MSG_SUP',
    50: 'AMDSMI_STATUS_HSMP_TIMEOUT',
    51: 'AMDSMI_STATUS_NO_DRV',
    52: 'AMDSMI_STATUS_FILE_NOT_FOUND',
    53: 'AMDSMI_STATUS_ARG_PTR_NULL',
    54: 'AMDSMI_STATUS_AMDGPU_RESTART_ERR',
    55: 'AMDSMI_STATUS_SETTING_UNAVAILABLE',
    56: 'AMDSMI_STATUS_CORRUPTED_EEPROM',
    57: 'AMDSMI_STATUS_MORE_DATA',
    4294967294: 'AMDSMI_STATUS_MAP_ERROR',
    4294967295: 'AMDSMI_STATUS_UNKNOWN_ERROR',
}
AMDSMI_STATUS_SUCCESS = 0
AMDSMI_STATUS_INVAL = 1
AMDSMI_STATUS_NOT_SUPPORTED = 2
AMDSMI_STATUS_NOT_YET_IMPLEMENTED = 3
AMDSMI_STATUS_FAIL_LOAD_MODULE = 4
AMDSMI_STATUS_FAIL_LOAD_SYMBOL = 5
AMDSMI_STATUS_DRM_ERROR = 6
AMDSMI_STATUS_API_FAILED = 7
AMDSMI_STATUS_TIMEOUT = 8
AMDSMI_STATUS_RETRY = 9
AMDSMI_STATUS_NO_PERM = 10
AMDSMI_STATUS_INTERRUPT = 11
AMDSMI_STATUS_IO = 12
AMDSMI_STATUS_ADDRESS_FAULT = 13
AMDSMI_STATUS_FILE_ERROR = 14
AMDSMI_STATUS_OUT_OF_RESOURCES = 15
AMDSMI_STATUS_INTERNAL_EXCEPTION = 16
AMDSMI_STATUS_INPUT_OUT_OF_BOUNDS = 17
AMDSMI_STATUS_INIT_ERROR = 18
AMDSMI_STATUS_REFCOUNT_OVERFLOW = 19
AMDSMI_STATUS_BUSY = 30
AMDSMI_STATUS_NOT_FOUND = 31
AMDSMI_STATUS_NOT_INIT = 32
AMDSMI_STATUS_NO_SLOT = 33
AMDSMI_STATUS_DRIVER_NOT_LOADED = 34
AMDSMI_STATUS_NO_DATA = 40
AMDSMI_STATUS_INSUFFICIENT_SIZE = 41
AMDSMI_STATUS_UNEXPECTED_SIZE = 42
AMDSMI_STATUS_UNEXPECTED_DATA = 43
AMDSMI_STATUS_NON_AMD_CPU = 44
AMDSMI_STATUS_NO_ENERGY_DRV = 45
AMDSMI_STATUS_NO_MSR_DRV = 46
AMDSMI_STATUS_NO_HSMP_DRV = 47
AMDSMI_STATUS_NO_HSMP_SUP = 48
AMDSMI_STATUS_NO_HSMP_MSG_SUP = 49
AMDSMI_STATUS_HSMP_TIMEOUT = 50
AMDSMI_STATUS_NO_DRV = 51
AMDSMI_STATUS_FILE_NOT_FOUND = 52
AMDSMI_STATUS_ARG_PTR_NULL = 53
AMDSMI_STATUS_AMDGPU_RESTART_ERR = 54
AMDSMI_STATUS_SETTING_UNAVAILABLE = 55
AMDSMI_STATUS_CORRUPTED_EEPROM = 56
AMDSMI_STATUS_MORE_DATA = 57
AMDSMI_STATUS_MAP_ERROR = 4294967294
AMDSMI_STATUS_UNKNOWN_ERROR = 4294967295
amdsmi_status_t = ctypes.c_uint32 # enum

# values for enumeration 'amdsmi_clk_type_t'
amdsmi_clk_type_t__enumvalues = {
    0: 'AMDSMI_CLK_TYPE_SYS',
    0: 'AMDSMI_CLK_TYPE_FIRST',
    0: 'AMDSMI_CLK_TYPE_GFX',
    1: 'AMDSMI_CLK_TYPE_DF',
    2: 'AMDSMI_CLK_TYPE_DCEF',
    3: 'AMDSMI_CLK_TYPE_SOC',
    4: 'AMDSMI_CLK_TYPE_MEM',
    5: 'AMDSMI_CLK_TYPE_PCIE',
    6: 'AMDSMI_CLK_TYPE_VCLK0',
    7: 'AMDSMI_CLK_TYPE_VCLK1',
    8: 'AMDSMI_CLK_TYPE_DCLK0',
    9: 'AMDSMI_CLK_TYPE_DCLK1',
    9: 'AMDSMI_CLK_TYPE__MAX',
}
AMDSMI_CLK_TYPE_SYS = 0
AMDSMI_CLK_TYPE_FIRST = 0
AMDSMI_CLK_TYPE_GFX = 0
AMDSMI_CLK_TYPE_DF = 1
AMDSMI_CLK_TYPE_DCEF = 2
AMDSMI_CLK_TYPE_SOC = 3
AMDSMI_CLK_TYPE_MEM = 4
AMDSMI_CLK_TYPE_PCIE = 5
AMDSMI_CLK_TYPE_VCLK0 = 6
AMDSMI_CLK_TYPE_VCLK1 = 7
AMDSMI_CLK_TYPE_DCLK0 = 8
AMDSMI_CLK_TYPE_DCLK1 = 9
AMDSMI_CLK_TYPE__MAX = 9
amdsmi_clk_type_t = ctypes.c_uint32 # enum

# values for enumeration 'amdsmi_accelerator_partition_type_t'
amdsmi_accelerator_partition_type_t__enumvalues = {
    0: 'AMDSMI_ACCELERATOR_PARTITION_INVALID',
    1: 'AMDSMI_ACCELERATOR_PARTITION_SPX',
    2: 'AMDSMI_ACCELERATOR_PARTITION_DPX',
    3: 'AMDSMI_ACCELERATOR_PARTITION_TPX',
    4: 'AMDSMI_ACCELERATOR_PARTITION_QPX',
    5: 'AMDSMI_ACCELERATOR_PARTITION_CPX',
    6: 'AMDSMI_ACCELERATOR_PARTITION_MAX',
}
AMDSMI_ACCELERATOR_PARTITION_INVALID = 0
AMDSMI_ACCELERATOR_PARTITION_SPX = 1
AMDSMI_ACCELERATOR_PARTITION_DPX = 2
AMDSMI_ACCELERATOR_PARTITION_TPX = 3
AMDSMI_ACCELERATOR_PARTITION_QPX = 4
AMDSMI_ACCELERATOR_PARTITION_CPX = 5
AMDSMI_ACCELERATOR_PARTITION_MAX = 6
amdsmi_accelerator_partition_type_t = ctypes.c_uint32 # enum

# values for enumeration 'amdsmi_accelerator_partition_resource_type_t'
amdsmi_accelerator_partition_resource_type_t__enumvalues = {
    0: 'AMDSMI_ACCELERATOR_XCC',
    1: 'AMDSMI_ACCELERATOR_ENCODER',
    2: 'AMDSMI_ACCELERATOR_DECODER',
    3: 'AMDSMI_ACCELERATOR_DMA',
    4: 'AMDSMI_ACCELERATOR_JPEG',
    5: 'AMDSMI_ACCELERATOR_MAX',
}
AMDSMI_ACCELERATOR_XCC = 0
AMDSMI_ACCELERATOR_ENCODER = 1
AMDSMI_ACCELERATOR_DECODER = 2
AMDSMI_ACCELERATOR_DMA = 3
AMDSMI_ACCELERATOR_JPEG = 4
AMDSMI_ACCELERATOR_MAX = 5
amdsmi_accelerator_partition_resource_type_t = ctypes.c_uint32 # enum

# values for enumeration 'amdsmi_compute_partition_type_t'
amdsmi_compute_partition_type_t__enumvalues = {
    0: 'AMDSMI_COMPUTE_PARTITION_INVALID',
    1: 'AMDSMI_COMPUTE_PARTITION_SPX',
    2: 'AMDSMI_COMPUTE_PARTITION_DPX',
    3: 'AMDSMI_COMPUTE_PARTITION_TPX',
    4: 'AMDSMI_COMPUTE_PARTITION_QPX',
    5: 'AMDSMI_COMPUTE_PARTITION_CPX',
}
AMDSMI_COMPUTE_PARTITION_INVALID = 0
AMDSMI_COMPUTE_PARTITION_SPX = 1
AMDSMI_COMPUTE_PARTITION_DPX = 2
AMDSMI_COMPUTE_PARTITION_TPX = 3
AMDSMI_COMPUTE_PARTITION_QPX = 4
AMDSMI_COMPUTE_PARTITION_CPX = 5
amdsmi_compute_partition_type_t = ctypes.c_uint32 # enum

# values for enumeration 'amdsmi_memory_partition_type_t'
amdsmi_memory_partition_type_t__enumvalues = {
    0: 'AMDSMI_MEMORY_PARTITION_UNKNOWN',
    1: 'AMDSMI_MEMORY_PARTITION_NPS1',
    2: 'AMDSMI_MEMORY_PARTITION_NPS2',
    4: 'AMDSMI_MEMORY_PARTITION_NPS4',
    8: 'AMDSMI_MEMORY_PARTITION_NPS8',
}
AMDSMI_MEMORY_PARTITION_UNKNOWN = 0
AMDSMI_MEMORY_PARTITION_NPS1 = 1
AMDSMI_MEMORY_PARTITION_NPS2 = 2
AMDSMI_MEMORY_PARTITION_NPS4 = 4
AMDSMI_MEMORY_PARTITION_NPS8 = 8
amdsmi_memory_partition_type_t = ctypes.c_uint32 # enum

# values for enumeration 'amdsmi_temperature_type_t'
amdsmi_temperature_type_t__enumvalues = {
    0: 'AMDSMI_TEMPERATURE_TYPE_EDGE',
    0: 'AMDSMI_TEMPERATURE_TYPE_FIRST',
    1: 'AMDSMI_TEMPERATURE_TYPE_HOTSPOT',
    1: 'AMDSMI_TEMPERATURE_TYPE_JUNCTION',
    2: 'AMDSMI_TEMPERATURE_TYPE_VRAM',
    3: 'AMDSMI_TEMPERATURE_TYPE_HBM_0',
    4: 'AMDSMI_TEMPERATURE_TYPE_HBM_1',
    5: 'AMDSMI_TEMPERATURE_TYPE_HBM_2',
    6: 'AMDSMI_TEMPERATURE_TYPE_HBM_3',
    7: 'AMDSMI_TEMPERATURE_TYPE_PLX',
    7: 'AMDSMI_TEMPERATURE_TYPE__MAX',
}
AMDSMI_TEMPERATURE_TYPE_EDGE = 0
AMDSMI_TEMPERATURE_TYPE_FIRST = 0
AMDSMI_TEMPERATURE_TYPE_HOTSPOT = 1
AMDSMI_TEMPERATURE_TYPE_JUNCTION = 1
AMDSMI_TEMPERATURE_TYPE_VRAM = 2
AMDSMI_TEMPERATURE_TYPE_HBM_0 = 3
AMDSMI_TEMPERATURE_TYPE_HBM_1 = 4
AMDSMI_TEMPERATURE_TYPE_HBM_2 = 5
AMDSMI_TEMPERATURE_TYPE_HBM_3 = 6
AMDSMI_TEMPERATURE_TYPE_PLX = 7
AMDSMI_TEMPERATURE_TYPE__MAX = 7
amdsmi_temperature_type_t = ctypes.c_uint32 # enum

# values for enumeration 'amdsmi_fw_block_t'
amdsmi_fw_block_t__enumvalues = {
    1: 'AMDSMI_FW_ID_SMU',
    1: 'AMDSMI_FW_ID_FIRST',
    2: 'AMDSMI_FW_ID_CP_CE',
    3: 'AMDSMI_FW_ID_CP_PFP',
    4: 'AMDSMI_FW_ID_CP_ME',
    5: 'AMDSMI_FW_ID_CP_MEC_JT1',
    6: 'AMDSMI_FW_ID_CP_MEC_JT2',
    7: 'AMDSMI_FW_ID_CP_MEC1',
    8: 'AMDSMI_FW_ID_CP_MEC2',
    9: 'AMDSMI_FW_ID_RLC',
    10: 'AMDSMI_FW_ID_SDMA0',
    11: 'AMDSMI_FW_ID_SDMA1',
    12: 'AMDSMI_FW_ID_SDMA2',
    13: 'AMDSMI_FW_ID_SDMA3',
    14: 'AMDSMI_FW_ID_SDMA4',
    15: 'AMDSMI_FW_ID_SDMA5',
    16: 'AMDSMI_FW_ID_SDMA6',
    17: 'AMDSMI_FW_ID_SDMA7',
    18: 'AMDSMI_FW_ID_VCN',
    19: 'AMDSMI_FW_ID_UVD',
    20: 'AMDSMI_FW_ID_VCE',
    21: 'AMDSMI_FW_ID_ISP',
    22: 'AMDSMI_FW_ID_DMCU_ERAM',
    23: 'AMDSMI_FW_ID_DMCU_ISR',
    24: 'AMDSMI_FW_ID_RLC_RESTORE_LIST_GPM_MEM',
    25: 'AMDSMI_FW_ID_RLC_RESTORE_LIST_SRM_MEM',
    26: 'AMDSMI_FW_ID_RLC_RESTORE_LIST_CNTL',
    27: 'AMDSMI_FW_ID_RLC_V',
    28: 'AMDSMI_FW_ID_MMSCH',
    29: 'AMDSMI_FW_ID_PSP_SYSDRV',
    30: 'AMDSMI_FW_ID_PSP_SOSDRV',
    31: 'AMDSMI_FW_ID_PSP_TOC',
    32: 'AMDSMI_FW_ID_PSP_KEYDB',
    33: 'AMDSMI_FW_ID_DFC',
    34: 'AMDSMI_FW_ID_PSP_SPL',
    35: 'AMDSMI_FW_ID_DRV_CAP',
    36: 'AMDSMI_FW_ID_MC',
    37: 'AMDSMI_FW_ID_PSP_BL',
    38: 'AMDSMI_FW_ID_CP_PM4',
    39: 'AMDSMI_FW_ID_RLC_P',
    40: 'AMDSMI_FW_ID_SEC_POLICY_STAGE2',
    41: 'AMDSMI_FW_ID_REG_ACCESS_WHITELIST',
    42: 'AMDSMI_FW_ID_IMU_DRAM',
    43: 'AMDSMI_FW_ID_IMU_IRAM',
    44: 'AMDSMI_FW_ID_SDMA_TH0',
    45: 'AMDSMI_FW_ID_SDMA_TH1',
    46: 'AMDSMI_FW_ID_CP_MES',
    47: 'AMDSMI_FW_ID_MES_KIQ',
    48: 'AMDSMI_FW_ID_MES_STACK',
    49: 'AMDSMI_FW_ID_MES_THREAD1',
    50: 'AMDSMI_FW_ID_MES_THREAD1_STACK',
    51: 'AMDSMI_FW_ID_RLX6',
    52: 'AMDSMI_FW_ID_RLX6_DRAM_BOOT',
    53: 'AMDSMI_FW_ID_RS64_ME',
    54: 'AMDSMI_FW_ID_RS64_ME_P0_DATA',
    55: 'AMDSMI_FW_ID_RS64_ME_P1_DATA',
    56: 'AMDSMI_FW_ID_RS64_PFP',
    57: 'AMDSMI_FW_ID_RS64_PFP_P0_DATA',
    58: 'AMDSMI_FW_ID_RS64_PFP_P1_DATA',
    59: 'AMDSMI_FW_ID_RS64_MEC',
    60: 'AMDSMI_FW_ID_RS64_MEC_P0_DATA',
    61: 'AMDSMI_FW_ID_RS64_MEC_P1_DATA',
    62: 'AMDSMI_FW_ID_RS64_MEC_P2_DATA',
    63: 'AMDSMI_FW_ID_RS64_MEC_P3_DATA',
    64: 'AMDSMI_FW_ID_PPTABLE',
    65: 'AMDSMI_FW_ID_PSP_SOC',
    66: 'AMDSMI_FW_ID_PSP_DBG',
    67: 'AMDSMI_FW_ID_PSP_INTF',
    68: 'AMDSMI_FW_ID_RLX6_CORE1',
    69: 'AMDSMI_FW_ID_RLX6_DRAM_BOOT_CORE1',
    70: 'AMDSMI_FW_ID_RLCV_LX7',
    71: 'AMDSMI_FW_ID_RLC_SAVE_RESTORE_LIST',
    72: 'AMDSMI_FW_ID_ASD',
    73: 'AMDSMI_FW_ID_TA_RAS',
    74: 'AMDSMI_FW_ID_TA_XGMI',
    75: 'AMDSMI_FW_ID_RLC_SRLG',
    76: 'AMDSMI_FW_ID_RLC_SRLS',
    77: 'AMDSMI_FW_ID_PM',
    78: 'AMDSMI_FW_ID_DMCU',
    79: 'AMDSMI_FW_ID_PLDM_BUNDLE',
    80: 'AMDSMI_FW_ID__MAX',
}
AMDSMI_FW_ID_SMU = 1
AMDSMI_FW_ID_FIRST = 1
AMDSMI_FW_ID_CP_CE = 2
AMDSMI_FW_ID_CP_PFP = 3
AMDSMI_FW_ID_CP_ME = 4
AMDSMI_FW_ID_CP_MEC_JT1 = 5
AMDSMI_FW_ID_CP_MEC_JT2 = 6
AMDSMI_FW_ID_CP_MEC1 = 7
AMDSMI_FW_ID_CP_MEC2 = 8
AMDSMI_FW_ID_RLC = 9
AMDSMI_FW_ID_SDMA0 = 10
AMDSMI_FW_ID_SDMA1 = 11
AMDSMI_FW_ID_SDMA2 = 12
AMDSMI_FW_ID_SDMA3 = 13
AMDSMI_FW_ID_SDMA4 = 14
AMDSMI_FW_ID_SDMA5 = 15
AMDSMI_FW_ID_SDMA6 = 16
AMDSMI_FW_ID_SDMA7 = 17
AMDSMI_FW_ID_VCN = 18
AMDSMI_FW_ID_UVD = 19
AMDSMI_FW_ID_VCE = 20
AMDSMI_FW_ID_ISP = 21
AMDSMI_FW_ID_DMCU_ERAM = 22
AMDSMI_FW_ID_DMCU_ISR = 23
AMDSMI_FW_ID_RLC_RESTORE_LIST_GPM_MEM = 24
AMDSMI_FW_ID_RLC_RESTORE_LIST_SRM_MEM = 25
AMDSMI_FW_ID_RLC_RESTORE_LIST_CNTL = 26
AMDSMI_FW_ID_RLC_V = 27
AMDSMI_FW_ID_MMSCH = 28
AMDSMI_FW_ID_PSP_SYSDRV = 29
AMDSMI_FW_ID_PSP_SOSDRV = 30
AMDSMI_FW_ID_PSP_TOC = 31
AMDSMI_FW_ID_PSP_KEYDB = 32
AMDSMI_FW_ID_DFC = 33
AMDSMI_FW_ID_PSP_SPL = 34
AMDSMI_FW_ID_DRV_CAP = 35
AMDSMI_FW_ID_MC = 36
AMDSMI_FW_ID_PSP_BL = 37
AMDSMI_FW_ID_CP_PM4 = 38
AMDSMI_FW_ID_RLC_P = 39
AMDSMI_FW_ID_SEC_POLICY_STAGE2 = 40
AMDSMI_FW_ID_REG_ACCESS_WHITELIST = 41
AMDSMI_FW_ID_IMU_DRAM = 42
AMDSMI_FW_ID_IMU_IRAM = 43
AMDSMI_FW_ID_SDMA_TH0 = 44
AMDSMI_FW_ID_SDMA_TH1 = 45
AMDSMI_FW_ID_CP_MES = 46
AMDSMI_FW_ID_MES_KIQ = 47
AMDSMI_FW_ID_MES_STACK = 48
AMDSMI_FW_ID_MES_THREAD1 = 49
AMDSMI_FW_ID_MES_THREAD1_STACK = 50
AMDSMI_FW_ID_RLX6 = 51
AMDSMI_FW_ID_RLX6_DRAM_BOOT = 52
AMDSMI_FW_ID_RS64_ME = 53
AMDSMI_FW_ID_RS64_ME_P0_DATA = 54
AMDSMI_FW_ID_RS64_ME_P1_DATA = 55
AMDSMI_FW_ID_RS64_PFP = 56
AMDSMI_FW_ID_RS64_PFP_P0_DATA = 57
AMDSMI_FW_ID_RS64_PFP_P1_DATA = 58
AMDSMI_FW_ID_RS64_MEC = 59
AMDSMI_FW_ID_RS64_MEC_P0_DATA = 60
AMDSMI_FW_ID_RS64_MEC_P1_DATA = 61
AMDSMI_FW_ID_RS64_MEC_P2_DATA = 62
AMDSMI_FW_ID_RS64_MEC_P3_DATA = 63
AMDSMI_FW_ID_PPTABLE = 64
AMDSMI_FW_ID_PSP_SOC = 65
AMDSMI_FW_ID_PSP_DBG = 66
AMDSMI_FW_ID_PSP_INTF = 67
AMDSMI_FW_ID_RLX6_CORE1 = 68
AMDSMI_FW_ID_RLX6_DRAM_BOOT_CORE1 = 69
AMDSMI_FW_ID_RLCV_LX7 = 70
AMDSMI_FW_ID_RLC_SAVE_RESTORE_LIST = 71
AMDSMI_FW_ID_ASD = 72
AMDSMI_FW_ID_TA_RAS = 73
AMDSMI_FW_ID_TA_XGMI = 74
AMDSMI_FW_ID_RLC_SRLG = 75
AMDSMI_FW_ID_RLC_SRLS = 76
AMDSMI_FW_ID_PM = 77
AMDSMI_FW_ID_DMCU = 78
AMDSMI_FW_ID_PLDM_BUNDLE = 79
AMDSMI_FW_ID__MAX = 80
amdsmi_fw_block_t = ctypes.c_uint32 # enum

# values for enumeration 'amdsmi_vram_type_t'
amdsmi_vram_type_t__enumvalues = {
    0: 'AMDSMI_VRAM_TYPE_UNKNOWN',
    1: 'AMDSMI_VRAM_TYPE_HBM',
    2: 'AMDSMI_VRAM_TYPE_HBM2',
    3: 'AMDSMI_VRAM_TYPE_HBM2E',
    4: 'AMDSMI_VRAM_TYPE_HBM3',
    10: 'AMDSMI_VRAM_TYPE_DDR2',
    11: 'AMDSMI_VRAM_TYPE_DDR3',
    12: 'AMDSMI_VRAM_TYPE_DDR4',
    17: 'AMDSMI_VRAM_TYPE_GDDR1',
    18: 'AMDSMI_VRAM_TYPE_GDDR2',
    19: 'AMDSMI_VRAM_TYPE_GDDR3',
    20: 'AMDSMI_VRAM_TYPE_GDDR4',
    21: 'AMDSMI_VRAM_TYPE_GDDR5',
    22: 'AMDSMI_VRAM_TYPE_GDDR6',
    23: 'AMDSMI_VRAM_TYPE_GDDR7',
    23: 'AMDSMI_VRAM_TYPE__MAX',
}
AMDSMI_VRAM_TYPE_UNKNOWN = 0
AMDSMI_VRAM_TYPE_HBM = 1
AMDSMI_VRAM_TYPE_HBM2 = 2
AMDSMI_VRAM_TYPE_HBM2E = 3
AMDSMI_VRAM_TYPE_HBM3 = 4
AMDSMI_VRAM_TYPE_DDR2 = 10
AMDSMI_VRAM_TYPE_DDR3 = 11
AMDSMI_VRAM_TYPE_DDR4 = 12
AMDSMI_VRAM_TYPE_GDDR1 = 17
AMDSMI_VRAM_TYPE_GDDR2 = 18
AMDSMI_VRAM_TYPE_GDDR3 = 19
AMDSMI_VRAM_TYPE_GDDR4 = 20
AMDSMI_VRAM_TYPE_GDDR5 = 21
AMDSMI_VRAM_TYPE_GDDR6 = 22
AMDSMI_VRAM_TYPE_GDDR7 = 23
AMDSMI_VRAM_TYPE__MAX = 23
amdsmi_vram_type_t = ctypes.c_uint32 # enum

# values for enumeration 'amdsmi_vram_vendor_type_t'
amdsmi_vram_vendor_type_t__enumvalues = {
    0: 'AMDSMI_VRAM_VENDOR_SAMSUNG',
    1: 'AMDSMI_VRAM_VENDOR_INFINEON',
    2: 'AMDSMI_VRAM_VENDOR_ELPIDA',
    3: 'AMDSMI_VRAM_VENDOR_ETRON',
    4: 'AMDSMI_VRAM_VENDOR_NANYA',
    5: 'AMDSMI_VRAM_VENDOR_HYNIX',
    6: 'AMDSMI_VRAM_VENDOR_MOSEL',
    7: 'AMDSMI_VRAM_VENDOR_WINBOND',
    8: 'AMDSMI_VRAM_VENDOR_ESMT',
    9: 'AMDSMI_VRAM_VENDOR_MICRON',
    10: 'AMDSMI_VRAM_VENDOR_UNKNOWN',
}
AMDSMI_VRAM_VENDOR_SAMSUNG = 0
AMDSMI_VRAM_VENDOR_INFINEON = 1
AMDSMI_VRAM_VENDOR_ELPIDA = 2
AMDSMI_VRAM_VENDOR_ETRON = 3
AMDSMI_VRAM_VENDOR_NANYA = 4
AMDSMI_VRAM_VENDOR_HYNIX = 5
AMDSMI_VRAM_VENDOR_MOSEL = 6
AMDSMI_VRAM_VENDOR_WINBOND = 7
AMDSMI_VRAM_VENDOR_ESMT = 8
AMDSMI_VRAM_VENDOR_MICRON = 9
AMDSMI_VRAM_VENDOR_UNKNOWN = 10
amdsmi_vram_vendor_type_t = ctypes.c_uint32 # enum
class struct_amdsmi_range_t(Structure):
    pass

struct_amdsmi_range_t._pack_ = 1 # source:False
struct_amdsmi_range_t._fields_ = [
    ('lower_bound', ctypes.c_uint64),
    ('upper_bound', ctypes.c_uint64),
    ('reserved', ctypes.c_uint64 * 2),
]

amdsmi_range_t = struct_amdsmi_range_t
class struct_amdsmi_xgmi_info_t(Structure):
    pass

struct_amdsmi_xgmi_info_t._pack_ = 1 # source:False
struct_amdsmi_xgmi_info_t._fields_ = [
    ('xgmi_lanes', ctypes.c_ubyte),
    ('PADDING_0', ctypes.c_ubyte * 7),
    ('xgmi_hive_id', ctypes.c_uint64),
    ('xgmi_node_id', ctypes.c_uint64),
    ('index', ctypes.c_uint32),
    ('reserved', ctypes.c_uint32 * 9),
]

amdsmi_xgmi_info_t = struct_amdsmi_xgmi_info_t
class struct_amdsmi_vram_usage_t(Structure):
    pass

struct_amdsmi_vram_usage_t._pack_ = 1 # source:False
struct_amdsmi_vram_usage_t._fields_ = [
    ('vram_total', ctypes.c_uint32),
    ('vram_used', ctypes.c_uint32),
    ('reserved', ctypes.c_uint32 * 2),
]

amdsmi_vram_usage_t = struct_amdsmi_vram_usage_t
class struct_amdsmi_violation_status_t(Structure):
    pass

struct_amdsmi_violation_status_t._pack_ = 1 # source:False
struct_amdsmi_violation_status_t._fields_ = [
    ('reference_timestamp', ctypes.c_uint64),
    ('violation_timestamp', ctypes.c_uint64),
    ('acc_counter', ctypes.c_uint64),
    ('acc_prochot_thrm', ctypes.c_uint64),
    ('acc_ppt_pwr', ctypes.c_uint64),
    ('acc_socket_thrm', ctypes.c_uint64),
    ('acc_vr_thrm', ctypes.c_uint64),
    ('acc_hbm_thrm', ctypes.c_uint64),
    ('acc_gfx_clk_below_host_limit', ctypes.c_uint64),
    ('per_prochot_thrm', ctypes.c_uint64),
    ('per_ppt_pwr', ctypes.c_uint64),
    ('per_socket_thrm', ctypes.c_uint64),
    ('per_vr_thrm', ctypes.c_uint64),
    ('per_hbm_thrm', ctypes.c_uint64),
    ('per_gfx_clk_below_host_limit', ctypes.c_uint64),
    ('active_prochot_thrm', ctypes.c_ubyte),
    ('active_ppt_pwr', ctypes.c_ubyte),
    ('active_socket_thrm', ctypes.c_ubyte),
    ('active_vr_thrm', ctypes.c_ubyte),
    ('active_hbm_thrm', ctypes.c_ubyte),
    ('active_gfx_clk_below_host_limit', ctypes.c_ubyte),
    ('PADDING_0', ctypes.c_ubyte * 2),
    ('reserved', ctypes.c_uint64 * 3),
]

amdsmi_violation_status_t = struct_amdsmi_violation_status_t
class struct_amdsmi_frequency_range_t(Structure):
    pass

struct_amdsmi_frequency_range_t._pack_ = 1 # source:False
struct_amdsmi_frequency_range_t._fields_ = [
    ('supported_freq_range', amdsmi_range_t),
    ('current_freq_range', amdsmi_range_t),
    ('reserved', ctypes.c_uint32 * 8),
]

amdsmi_frequency_range_t = struct_amdsmi_frequency_range_t
class union_amdsmi_bdf_t(Union):
    pass

class struct_amdsmi_bdf_t(Structure):
    pass

struct_amdsmi_bdf_t._pack_ = 1 # source:False
struct_amdsmi_bdf_t._fields_ = [
    ('function_number', ctypes.c_uint64, 3),
    ('device_number', ctypes.c_uint64, 5),
    ('bus_number', ctypes.c_uint64, 8),
    ('domain_number', ctypes.c_uint64, 48),
]

union_amdsmi_bdf_t._pack_ = 1 # source:False

union_amdsmi_bdf_t._fields_ = [
    ('struct_amdsmi_bdf_t', struct_amdsmi_bdf_t),
    ('as_uint', ctypes.c_uint64),
]

amdsmi_bdf_t = union_amdsmi_bdf_t
class struct_amdsmi_enumeration_info_t(Structure):
    pass

struct_amdsmi_enumeration_info_t._pack_ = 1 # source:False
struct_amdsmi_enumeration_info_t._fields_ = [
    ('drm_render', ctypes.c_uint32),
    ('drm_card', ctypes.c_uint32),
    ('hsa_id', ctypes.c_uint32),
    ('hip_id', ctypes.c_uint32),
    ('hip_uuid', ctypes.c_char * 256),
]

amdsmi_enumeration_info_t = struct_amdsmi_enumeration_info_t

# values for enumeration 'amdsmi_card_form_factor_t'
amdsmi_card_form_factor_t__enumvalues = {
    0: 'AMDSMI_CARD_FORM_FACTOR_PCIE',
    1: 'AMDSMI_CARD_FORM_FACTOR_OAM',
    2: 'AMDSMI_CARD_FORM_FACTOR_CEM',
    3: 'AMDSMI_CARD_FORM_FACTOR_UNKNOWN',
}
AMDSMI_CARD_FORM_FACTOR_PCIE = 0
AMDSMI_CARD_FORM_FACTOR_OAM = 1
AMDSMI_CARD_FORM_FACTOR_CEM = 2
AMDSMI_CARD_FORM_FACTOR_UNKNOWN = 3
amdsmi_card_form_factor_t = ctypes.c_uint32 # enum
class struct_amdsmi_pcie_info_t(Structure):
    pass

class struct_pcie_metric_(Structure):
    pass

struct_pcie_metric_._pack_ = 1 # source:False
struct_pcie_metric_._fields_ = [
    ('pcie_width', ctypes.c_uint16),
    ('PADDING_0', ctypes.c_ubyte * 2),
    ('pcie_speed', ctypes.c_uint32),
    ('pcie_bandwidth', ctypes.c_uint32),
    ('PADDING_1', ctypes.c_ubyte * 4),
    ('pcie_replay_count', ctypes.c_uint64),
    ('pcie_l0_to_recovery_count', ctypes.c_uint64),
    ('pcie_replay_roll_over_count', ctypes.c_uint64),
    ('pcie_nak_sent_count', ctypes.c_uint64),
    ('pcie_nak_received_count', ctypes.c_uint64),
    ('pcie_lc_perf_other_end_recovery_count', ctypes.c_uint32),
    ('PADDING_2', ctypes.c_ubyte * 4),
    ('reserved', ctypes.c_uint64 * 12),
]

class struct_pcie_static_(Structure):
    pass

struct_pcie_static_._pack_ = 1 # source:False
struct_pcie_static_._fields_ = [
    ('max_pcie_width', ctypes.c_uint16),
    ('PADDING_0', ctypes.c_ubyte * 2),
    ('max_pcie_speed', ctypes.c_uint32),
    ('pcie_interface_version', ctypes.c_uint32),
    ('slot_type', amdsmi_card_form_factor_t),
    ('max_pcie_interface_version', ctypes.c_uint32),
    ('PADDING_1', ctypes.c_ubyte * 4),
    ('reserved', ctypes.c_uint64 * 9),
]

struct_amdsmi_pcie_info_t._pack_ = 1 # source:False
struct_amdsmi_pcie_info_t._fields_ = [
    ('pcie_static', struct_pcie_static_),
    ('pcie_metric', struct_pcie_metric_),
    ('reserved', ctypes.c_uint64 * 32),
]

amdsmi_pcie_info_t = struct_amdsmi_pcie_info_t
class struct_amdsmi_power_cap_info_t(Structure):
    pass

struct_amdsmi_power_cap_info_t._pack_ = 1 # source:False
struct_amdsmi_power_cap_info_t._fields_ = [
    ('power_cap', ctypes.c_uint64),
    ('default_power_cap', ctypes.c_uint64),
    ('dpm_cap', ctypes.c_uint64),
    ('min_power_cap', ctypes.c_uint64),
    ('max_power_cap', ctypes.c_uint64),
    ('reserved', ctypes.c_uint64 * 3),
]

amdsmi_power_cap_info_t = struct_amdsmi_power_cap_info_t
class struct_amdsmi_vbios_info_t(Structure):
    pass

struct_amdsmi_vbios_info_t._pack_ = 1 # source:False
struct_amdsmi_vbios_info_t._fields_ = [
    ('name', ctypes.c_char * 256),
    ('build_date', ctypes.c_char * 32),
    ('part_number', ctypes.c_char * 256),
    ('version', ctypes.c_char * 256),
    ('reserved', ctypes.c_uint64 * 32),
]

amdsmi_vbios_info_t = struct_amdsmi_vbios_info_t

# values for enumeration 'amdsmi_cache_property_type_t'
amdsmi_cache_property_type_t__enumvalues = {
    1: 'AMDSMI_CACHE_PROPERTY_ENABLED',
    2: 'AMDSMI_CACHE_PROPERTY_DATA_CACHE',
    4: 'AMDSMI_CACHE_PROPERTY_INST_CACHE',
    8: 'AMDSMI_CACHE_PROPERTY_CPU_CACHE',
    16: 'AMDSMI_CACHE_PROPERTY_SIMD_CACHE',
}
AMDSMI_CACHE_PROPERTY_ENABLED = 1
AMDSMI_CACHE_PROPERTY_DATA_CACHE = 2
AMDSMI_CACHE_PROPERTY_INST_CACHE = 4
AMDSMI_CACHE_PROPERTY_CPU_CACHE = 8
AMDSMI_CACHE_PROPERTY_SIMD_CACHE = 16
amdsmi_cache_property_type_t = ctypes.c_uint32 # enum
class struct_amdsmi_gpu_cache_info_t(Structure):
    pass

class struct_cache_(Structure):
    pass

struct_cache_._pack_ = 1 # source:False
struct_cache_._fields_ = [
    ('cache_properties', ctypes.c_uint32),
    ('cache_size', ctypes.c_uint32),
    ('cache_level', ctypes.c_uint32),
    ('max_num_cu_shared', ctypes.c_uint32),
    ('num_cache_instance', ctypes.c_uint32),
    ('reserved', ctypes.c_uint32 * 3),
]

struct_amdsmi_gpu_cache_info_t._pack_ = 1 # source:False
struct_amdsmi_gpu_cache_info_t._fields_ = [
    ('num_cache_types', ctypes.c_uint32),
    ('cache', struct_cache_ * 10),
    ('reserved', ctypes.c_uint32 * 15),
]

amdsmi_gpu_cache_info_t = struct_amdsmi_gpu_cache_info_t
class struct_amdsmi_fw_info_t(Structure):
    pass

class struct_fw_info_list_(Structure):
    pass

struct_fw_info_list_._pack_ = 1 # source:False
struct_fw_info_list_._fields_ = [
    ('fw_id', amdsmi_fw_block_t),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('fw_version', ctypes.c_uint64),
    ('reserved', ctypes.c_uint64 * 2),
]

struct_amdsmi_fw_info_t._pack_ = 1 # source:False
struct_amdsmi_fw_info_t._fields_ = [
    ('num_fw_info', ctypes.c_ubyte),
    ('PADDING_0', ctypes.c_ubyte * 7),
    ('fw_info_list', struct_fw_info_list_ * 80),
    ('reserved', ctypes.c_uint32 * 7),
    ('PADDING_1', ctypes.c_ubyte * 4),
]

amdsmi_fw_info_t = struct_amdsmi_fw_info_t
class struct_amdsmi_asic_info_t(Structure):
    pass

struct_amdsmi_asic_info_t._pack_ = 1 # source:False
struct_amdsmi_asic_info_t._fields_ = [
    ('market_name', ctypes.c_char * 256),
    ('vendor_id', ctypes.c_uint32),
    ('vendor_name', ctypes.c_char * 256),
    ('subvendor_id', ctypes.c_uint32),
    ('device_id', ctypes.c_uint64),
    ('rev_id', ctypes.c_uint32),
    ('asic_serial', ctypes.c_char * 256),
    ('oam_id', ctypes.c_uint32),
    ('num_of_compute_units', ctypes.c_uint32),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('target_graphics_version', ctypes.c_uint64),
    ('reserved', ctypes.c_uint32 * 22),
]

amdsmi_asic_info_t = struct_amdsmi_asic_info_t
class struct_amdsmi_kfd_info_t(Structure):
    pass

struct_amdsmi_kfd_info_t._pack_ = 1 # source:False
struct_amdsmi_kfd_info_t._fields_ = [
    ('kfd_id', ctypes.c_uint64),
    ('node_id', ctypes.c_uint32),
    ('current_partition_id', ctypes.c_uint32),
    ('reserved', ctypes.c_uint32 * 12),
]

amdsmi_kfd_info_t = struct_amdsmi_kfd_info_t
class union_amdsmi_nps_caps_t(Union):
    pass

class struct_nps_flags_(Structure):
    pass

struct_nps_flags_._pack_ = 1 # source:False
struct_nps_flags_._fields_ = [
    ('nps1_cap', ctypes.c_uint32, 1),
    ('nps2_cap', ctypes.c_uint32, 1),
    ('nps4_cap', ctypes.c_uint32, 1),
    ('nps8_cap', ctypes.c_uint32, 1),
    ('reserved', ctypes.c_uint32, 28),
]

union_amdsmi_nps_caps_t._pack_ = 1 # source:False
union_amdsmi_nps_caps_t._fields_ = [
    ('nps_flags', struct_nps_flags_),
    ('nps_cap_mask', ctypes.c_uint32),
]

amdsmi_nps_caps_t = union_amdsmi_nps_caps_t
class struct_amdsmi_memory_partition_config_t(Structure):
    pass

class struct_numa_range_(Structure):
    pass

struct_numa_range_._pack_ = 1 # source:False
struct_numa_range_._fields_ = [
    ('memory_type', amdsmi_vram_type_t),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('start', ctypes.c_uint64),
    ('end', ctypes.c_uint64),
]

struct_amdsmi_memory_partition_config_t._pack_ = 1 # source:False
struct_amdsmi_memory_partition_config_t._fields_ = [
    ('partition_caps', amdsmi_nps_caps_t),
    ('mp_mode', amdsmi_memory_partition_type_t),
    ('num_numa_ranges', ctypes.c_uint32),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('numa_range', struct_numa_range_ * 32),
    ('reserved', ctypes.c_uint64 * 11),
]

amdsmi_memory_partition_config_t = struct_amdsmi_memory_partition_config_t
class struct_amdsmi_accelerator_partition_profile_t(Structure):
    pass

struct_amdsmi_accelerator_partition_profile_t._pack_ = 1 # source:False
struct_amdsmi_accelerator_partition_profile_t._fields_ = [
    ('profile_type', amdsmi_accelerator_partition_type_t),
    ('num_partitions', ctypes.c_uint32),
    ('memory_caps', amdsmi_nps_caps_t),
    ('profile_index', ctypes.c_uint32),
    ('num_resources', ctypes.c_uint32),
    ('resources', ctypes.c_uint32 * 32 * 8),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('reserved', ctypes.c_uint64 * 13),
]

amdsmi_accelerator_partition_profile_t = struct_amdsmi_accelerator_partition_profile_t
class struct_amdsmi_accelerator_partition_resource_profile_t(Structure):
    pass

struct_amdsmi_accelerator_partition_resource_profile_t._pack_ = 1 # source:False
struct_amdsmi_accelerator_partition_resource_profile_t._fields_ = [
    ('profile_index', ctypes.c_uint32),
    ('resource_type', amdsmi_accelerator_partition_resource_type_t),
    ('partition_resource', ctypes.c_uint32),
    ('num_partitions_share_resource', ctypes.c_uint32),
    ('reserved', ctypes.c_uint64 * 6),
]

amdsmi_accelerator_partition_resource_profile_t = struct_amdsmi_accelerator_partition_resource_profile_t
class struct_amdsmi_accelerator_partition_profile_config_t(Structure):
    pass

struct_amdsmi_accelerator_partition_profile_config_t._pack_ = 1 # source:False
struct_amdsmi_accelerator_partition_profile_config_t._fields_ = [
    ('num_profiles', ctypes.c_uint32),
    ('num_resource_profiles', ctypes.c_uint32),
    ('resource_profiles', struct_amdsmi_accelerator_partition_resource_profile_t * 32),
    ('default_profile_index', ctypes.c_uint32),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('profiles', struct_amdsmi_accelerator_partition_profile_t * 32),
    ('reserved', ctypes.c_uint64 * 30),
]

amdsmi_accelerator_partition_profile_config_t = struct_amdsmi_accelerator_partition_profile_config_t

# values for enumeration 'amdsmi_link_type_t'
amdsmi_link_type_t__enumvalues = {
    0: 'AMDSMI_LINK_TYPE_INTERNAL',
    1: 'AMDSMI_LINK_TYPE_XGMI',
    2: 'AMDSMI_LINK_TYPE_PCIE',
    3: 'AMDSMI_LINK_TYPE_NOT_APPLICABLE',
    4: 'AMDSMI_LINK_TYPE_UNKNOWN',
}
AMDSMI_LINK_TYPE_INTERNAL = 0
AMDSMI_LINK_TYPE_XGMI = 1
AMDSMI_LINK_TYPE_PCIE = 2
AMDSMI_LINK_TYPE_NOT_APPLICABLE = 3
AMDSMI_LINK_TYPE_UNKNOWN = 4
amdsmi_link_type_t = ctypes.c_uint32 # enum
class struct_amdsmi_link_metrics_t(Structure):
    pass

class struct__links(Structure):
    pass

struct__links._pack_ = 1 # source:False
struct__links._fields_ = [
    ('bdf', amdsmi_bdf_t),
    ('bit_rate', ctypes.c_uint32),
    ('max_bandwidth', ctypes.c_uint32),
    ('link_type', amdsmi_link_type_t),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('read', ctypes.c_uint64),
    ('write', ctypes.c_uint64),
    ('reserved', ctypes.c_uint64 * 2),
]

struct_amdsmi_link_metrics_t._pack_ = 1 # source:False
struct_amdsmi_link_metrics_t._fields_ = [
    ('num_links', ctypes.c_uint32),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('links', struct__links * 64),
    ('reserved', ctypes.c_uint64 * 7),
]

amdsmi_link_metrics_t = struct_amdsmi_link_metrics_t
class struct_amdsmi_vram_info_t(Structure):
    pass

struct_amdsmi_vram_info_t._pack_ = 1 # source:False
struct_amdsmi_vram_info_t._fields_ = [
    ('vram_type', amdsmi_vram_type_t),
    ('vram_vendor', amdsmi_vram_vendor_type_t),
    ('vram_size', ctypes.c_uint64),
    ('vram_bit_width', ctypes.c_uint32),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('vram_max_bandwidth', ctypes.c_uint64),
    ('reserved', ctypes.c_uint64 * 4),
]

amdsmi_vram_info_t = struct_amdsmi_vram_info_t
class struct_amdsmi_driver_info_t(Structure):
    pass

struct_amdsmi_driver_info_t._pack_ = 1 # source:False
struct_amdsmi_driver_info_t._fields_ = [
    ('driver_version', ctypes.c_char * 256),
    ('driver_date', ctypes.c_char * 256),
    ('driver_name', ctypes.c_char * 256),
]

amdsmi_driver_info_t = struct_amdsmi_driver_info_t
class struct_amdsmi_board_info_t(Structure):
    pass

struct_amdsmi_board_info_t._pack_ = 1 # source:False
struct_amdsmi_board_info_t._fields_ = [
    ('model_number', ctypes.c_char * 256),
    ('product_serial', ctypes.c_char * 256),
    ('fru_id', ctypes.c_char * 256),
    ('product_name', ctypes.c_char * 256),
    ('manufacturer_name', ctypes.c_char * 256),
    ('reserved', ctypes.c_uint64 * 32),
]

amdsmi_board_info_t = struct_amdsmi_board_info_t
class struct_amdsmi_power_info_t(Structure):
    pass

struct_amdsmi_power_info_t._pack_ = 1 # source:False
struct_amdsmi_power_info_t._fields_ = [
    ('socket_power', ctypes.c_uint64),
    ('current_socket_power', ctypes.c_uint32),
    ('average_socket_power', ctypes.c_uint32),
    ('gfx_voltage', ctypes.c_uint32),
    ('soc_voltage', ctypes.c_uint32),
    ('mem_voltage', ctypes.c_uint32),
    ('power_limit', ctypes.c_uint32),
    ('reserved', ctypes.c_uint32 * 2),
]

amdsmi_power_info_t = struct_amdsmi_power_info_t
class struct_amdsmi_clk_info_t(Structure):
    pass

struct_amdsmi_clk_info_t._pack_ = 1 # source:False
struct_amdsmi_clk_info_t._fields_ = [
    ('clk', ctypes.c_uint32),
    ('min_clk', ctypes.c_uint32),
    ('max_clk', ctypes.c_uint32),
    ('clk_locked', ctypes.c_ubyte),
    ('clk_deep_sleep', ctypes.c_ubyte),
    ('PADDING_0', ctypes.c_ubyte * 2),
    ('reserved', ctypes.c_uint32 * 4),
]

amdsmi_clk_info_t = struct_amdsmi_clk_info_t
class struct_amdsmi_engine_usage_t(Structure):
    pass

struct_amdsmi_engine_usage_t._pack_ = 1 # source:False
struct_amdsmi_engine_usage_t._fields_ = [
    ('gfx_activity', ctypes.c_uint32),
    ('umc_activity', ctypes.c_uint32),
    ('mm_activity', ctypes.c_uint32),
    ('reserved', ctypes.c_uint32 * 13),
]

amdsmi_engine_usage_t = struct_amdsmi_engine_usage_t
amdsmi_process_handle_t = ctypes.c_uint32
class struct_amdsmi_proc_info_t(Structure):
    pass

class struct_memory_usage_(Structure):
    pass

struct_memory_usage_._pack_ = 1 # source:False
struct_memory_usage_._fields_ = [
    ('gtt_mem', ctypes.c_uint64),
    ('cpu_mem', ctypes.c_uint64),
    ('vram_mem', ctypes.c_uint64),
    ('reserved', ctypes.c_uint32 * 10),
]

class struct_engine_usage_(Structure):
    pass

struct_engine_usage_._pack_ = 1 # source:False
struct_engine_usage_._fields_ = [
    ('gfx', ctypes.c_uint64),
    ('enc', ctypes.c_uint64),
    ('reserved', ctypes.c_uint32 * 12),
]

struct_amdsmi_proc_info_t._pack_ = 1 # source:False
struct_amdsmi_proc_info_t._fields_ = [
    ('name', ctypes.c_char * 256),
    ('pid', ctypes.c_uint32),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('mem', ctypes.c_uint64),
    ('engine_usage', struct_engine_usage_),
    ('memory_usage', struct_memory_usage_),
    ('container_name', ctypes.c_char * 256),
    ('cu_occupancy', ctypes.c_uint32),
    ('reserved', ctypes.c_uint32 * 11),
]

amdsmi_proc_info_t = struct_amdsmi_proc_info_t
class struct_amdsmi_p2p_capability_t(Structure):
    pass

struct_amdsmi_p2p_capability_t._pack_ = 1 # source:False
struct_amdsmi_p2p_capability_t._fields_ = [
    ('is_iolink_coherent', ctypes.c_ubyte),
    ('is_iolink_atomics_32bit', ctypes.c_ubyte),
    ('is_iolink_atomics_64bit', ctypes.c_ubyte),
    ('is_iolink_dma', ctypes.c_ubyte),
    ('is_iolink_bi_directional', ctypes.c_ubyte),
]

amdsmi_p2p_capability_t = struct_amdsmi_p2p_capability_t

# values for enumeration 'amdsmi_dev_perf_level_t'
amdsmi_dev_perf_level_t__enumvalues = {
    0: 'AMDSMI_DEV_PERF_LEVEL_AUTO',
    0: 'AMDSMI_DEV_PERF_LEVEL_FIRST',
    1: 'AMDSMI_DEV_PERF_LEVEL_LOW',
    2: 'AMDSMI_DEV_PERF_LEVEL_HIGH',
    3: 'AMDSMI_DEV_PERF_LEVEL_MANUAL',
    4: 'AMDSMI_DEV_PERF_LEVEL_STABLE_STD',
    5: 'AMDSMI_DEV_PERF_LEVEL_STABLE_PEAK',
    6: 'AMDSMI_DEV_PERF_LEVEL_STABLE_MIN_MCLK',
    7: 'AMDSMI_DEV_PERF_LEVEL_STABLE_MIN_SCLK',
    8: 'AMDSMI_DEV_PERF_LEVEL_DETERMINISM',
    8: 'AMDSMI_DEV_PERF_LEVEL_LAST',
    256: 'AMDSMI_DEV_PERF_LEVEL_UNKNOWN',
}
AMDSMI_DEV_PERF_LEVEL_AUTO = 0
AMDSMI_DEV_PERF_LEVEL_FIRST = 0
AMDSMI_DEV_PERF_LEVEL_LOW = 1
AMDSMI_DEV_PERF_LEVEL_HIGH = 2
AMDSMI_DEV_PERF_LEVEL_MANUAL = 3
AMDSMI_DEV_PERF_LEVEL_STABLE_STD = 4
AMDSMI_DEV_PERF_LEVEL_STABLE_PEAK = 5
AMDSMI_DEV_PERF_LEVEL_STABLE_MIN_MCLK = 6
AMDSMI_DEV_PERF_LEVEL_STABLE_MIN_SCLK = 7
AMDSMI_DEV_PERF_LEVEL_DETERMINISM = 8
AMDSMI_DEV_PERF_LEVEL_LAST = 8
AMDSMI_DEV_PERF_LEVEL_UNKNOWN = 256
amdsmi_dev_perf_level_t = ctypes.c_uint32 # enum
amdsmi_event_handle_t = ctypes.c_uint64

# values for enumeration 'amdsmi_event_group_t'
amdsmi_event_group_t__enumvalues = {
    0: 'AMDSMI_EVNT_GRP_XGMI',
    10: 'AMDSMI_EVNT_GRP_XGMI_DATA_OUT',
    4294967295: 'AMDSMI_EVNT_GRP_INVALID',
}
AMDSMI_EVNT_GRP_XGMI = 0
AMDSMI_EVNT_GRP_XGMI_DATA_OUT = 10
AMDSMI_EVNT_GRP_INVALID = 4294967295
amdsmi_event_group_t = ctypes.c_uint32 # enum

# values for enumeration 'amdsmi_event_type_t'
amdsmi_event_type_t__enumvalues = {
    0: 'AMDSMI_EVNT_FIRST',
    0: 'AMDSMI_EVNT_XGMI_FIRST',
    0: 'AMDSMI_EVNT_XGMI_0_NOP_TX',
    1: 'AMDSMI_EVNT_XGMI_0_REQUEST_TX',
    2: 'AMDSMI_EVNT_XGMI_0_RESPONSE_TX',
    3: 'AMDSMI_EVNT_XGMI_0_BEATS_TX',
    4: 'AMDSMI_EVNT_XGMI_1_NOP_TX',
    5: 'AMDSMI_EVNT_XGMI_1_REQUEST_TX',
    6: 'AMDSMI_EVNT_XGMI_1_RESPONSE_TX',
    7: 'AMDSMI_EVNT_XGMI_1_BEATS_TX',
    7: 'AMDSMI_EVNT_XGMI_LAST',
    10: 'AMDSMI_EVNT_XGMI_DATA_OUT_FIRST',
    10: 'AMDSMI_EVNT_XGMI_DATA_OUT_0',
    11: 'AMDSMI_EVNT_XGMI_DATA_OUT_1',
    12: 'AMDSMI_EVNT_XGMI_DATA_OUT_2',
    13: 'AMDSMI_EVNT_XGMI_DATA_OUT_3',
    14: 'AMDSMI_EVNT_XGMI_DATA_OUT_4',
    15: 'AMDSMI_EVNT_XGMI_DATA_OUT_5',
    15: 'AMDSMI_EVNT_XGMI_DATA_OUT_LAST',
    15: 'AMDSMI_EVNT_LAST',
}
AMDSMI_EVNT_FIRST = 0
AMDSMI_EVNT_XGMI_FIRST = 0
AMDSMI_EVNT_XGMI_0_NOP_TX = 0
AMDSMI_EVNT_XGMI_0_REQUEST_TX = 1
AMDSMI_EVNT_XGMI_0_RESPONSE_TX = 2
AMDSMI_EVNT_XGMI_0_BEATS_TX = 3
AMDSMI_EVNT_XGMI_1_NOP_TX = 4
AMDSMI_EVNT_XGMI_1_REQUEST_TX = 5
AMDSMI_EVNT_XGMI_1_RESPONSE_TX = 6
AMDSMI_EVNT_XGMI_1_BEATS_TX = 7
AMDSMI_EVNT_XGMI_LAST = 7
AMDSMI_EVNT_XGMI_DATA_OUT_FIRST = 10
AMDSMI_EVNT_XGMI_DATA_OUT_0 = 10
AMDSMI_EVNT_XGMI_DATA_OUT_1 = 11
AMDSMI_EVNT_XGMI_DATA_OUT_2 = 12
AMDSMI_EVNT_XGMI_DATA_OUT_3 = 13
AMDSMI_EVNT_XGMI_DATA_OUT_4 = 14
AMDSMI_EVNT_XGMI_DATA_OUT_5 = 15
AMDSMI_EVNT_XGMI_DATA_OUT_LAST = 15
AMDSMI_EVNT_LAST = 15
amdsmi_event_type_t = ctypes.c_uint32 # enum

# values for enumeration 'amdsmi_counter_command_t'
amdsmi_counter_command_t__enumvalues = {
    0: 'AMDSMI_CNTR_CMD_START',
    1: 'AMDSMI_CNTR_CMD_STOP',
}
AMDSMI_CNTR_CMD_START = 0
AMDSMI_CNTR_CMD_STOP = 1
amdsmi_counter_command_t = ctypes.c_uint32 # enum
class struct_amdsmi_counter_value_t(Structure):
    pass

struct_amdsmi_counter_value_t._pack_ = 1 # source:False
struct_amdsmi_counter_value_t._fields_ = [
    ('value', ctypes.c_uint64),
    ('time_enabled', ctypes.c_uint64),
    ('time_running', ctypes.c_uint64),
]

amdsmi_counter_value_t = struct_amdsmi_counter_value_t

# values for enumeration 'amdsmi_evt_notification_type_t'
amdsmi_evt_notification_type_t__enumvalues = {
    0: 'AMDSMI_EVT_NOTIF_NONE',
    1: 'AMDSMI_EVT_NOTIF_VMFAULT',
    1: 'AMDSMI_EVT_NOTIF_FIRST',
    2: 'AMDSMI_EVT_NOTIF_THERMAL_THROTTLE',
    3: 'AMDSMI_EVT_NOTIF_GPU_PRE_RESET',
    4: 'AMDSMI_EVT_NOTIF_GPU_POST_RESET',
    5: 'AMDSMI_EVT_NOTIF_RING_HANG',
    5: 'AMDSMI_EVT_NOTIF_LAST',
}
AMDSMI_EVT_NOTIF_NONE = 0
AMDSMI_EVT_NOTIF_VMFAULT = 1
AMDSMI_EVT_NOTIF_FIRST = 1
AMDSMI_EVT_NOTIF_THERMAL_THROTTLE = 2
AMDSMI_EVT_NOTIF_GPU_PRE_RESET = 3
AMDSMI_EVT_NOTIF_GPU_POST_RESET = 4
AMDSMI_EVT_NOTIF_RING_HANG = 5
AMDSMI_EVT_NOTIF_LAST = 5
amdsmi_evt_notification_type_t = ctypes.c_uint32 # enum
class struct_amdsmi_evt_notification_data_t(Structure):
    pass

struct_amdsmi_evt_notification_data_t._pack_ = 1 # source:False
struct_amdsmi_evt_notification_data_t._fields_ = [
    ('processor_handle', ctypes.POINTER(None)),
    ('event', amdsmi_evt_notification_type_t),
    ('message', ctypes.c_char * 96),
    ('PADDING_0', ctypes.c_ubyte * 4),
]

amdsmi_evt_notification_data_t = struct_amdsmi_evt_notification_data_t

# values for enumeration 'amdsmi_temperature_metric_t'
amdsmi_temperature_metric_t__enumvalues = {
    0: 'AMDSMI_TEMP_CURRENT',
    0: 'AMDSMI_TEMP_FIRST',
    1: 'AMDSMI_TEMP_MAX',
    2: 'AMDSMI_TEMP_MIN',
    3: 'AMDSMI_TEMP_MAX_HYST',
    4: 'AMDSMI_TEMP_MIN_HYST',
    5: 'AMDSMI_TEMP_CRITICAL',
    6: 'AMDSMI_TEMP_CRITICAL_HYST',
    7: 'AMDSMI_TEMP_EMERGENCY',
    8: 'AMDSMI_TEMP_EMERGENCY_HYST',
    9: 'AMDSMI_TEMP_CRIT_MIN',
    10: 'AMDSMI_TEMP_CRIT_MIN_HYST',
    11: 'AMDSMI_TEMP_OFFSET',
    12: 'AMDSMI_TEMP_LOWEST',
    13: 'AMDSMI_TEMP_HIGHEST',
    14: 'AMDSMI_TEMP_SHUTDOWN',
    14: 'AMDSMI_TEMP_LAST',
}
AMDSMI_TEMP_CURRENT = 0
AMDSMI_TEMP_FIRST = 0
AMDSMI_TEMP_MAX = 1
AMDSMI_TEMP_MIN = 2
AMDSMI_TEMP_MAX_HYST = 3
AMDSMI_TEMP_MIN_HYST = 4
AMDSMI_TEMP_CRITICAL = 5
AMDSMI_TEMP_CRITICAL_HYST = 6
AMDSMI_TEMP_EMERGENCY = 7
AMDSMI_TEMP_EMERGENCY_HYST = 8
AMDSMI_TEMP_CRIT_MIN = 9
AMDSMI_TEMP_CRIT_MIN_HYST = 10
AMDSMI_TEMP_OFFSET = 11
AMDSMI_TEMP_LOWEST = 12
AMDSMI_TEMP_HIGHEST = 13
AMDSMI_TEMP_SHUTDOWN = 14
AMDSMI_TEMP_LAST = 14
amdsmi_temperature_metric_t = ctypes.c_uint32 # enum

# values for enumeration 'amdsmi_voltage_metric_t'
amdsmi_voltage_metric_t__enumvalues = {
    0: 'AMDSMI_VOLT_CURRENT',
    0: 'AMDSMI_VOLT_FIRST',
    1: 'AMDSMI_VOLT_MAX',
    2: 'AMDSMI_VOLT_MIN_CRIT',
    3: 'AMDSMI_VOLT_MIN',
    4: 'AMDSMI_VOLT_MAX_CRIT',
    5: 'AMDSMI_VOLT_AVERAGE',
    6: 'AMDSMI_VOLT_LOWEST',
    7: 'AMDSMI_VOLT_HIGHEST',
    7: 'AMDSMI_VOLT_LAST',
}
AMDSMI_VOLT_CURRENT = 0
AMDSMI_VOLT_FIRST = 0
AMDSMI_VOLT_MAX = 1
AMDSMI_VOLT_MIN_CRIT = 2
AMDSMI_VOLT_MIN = 3
AMDSMI_VOLT_MAX_CRIT = 4
AMDSMI_VOLT_AVERAGE = 5
AMDSMI_VOLT_LOWEST = 6
AMDSMI_VOLT_HIGHEST = 7
AMDSMI_VOLT_LAST = 7
amdsmi_voltage_metric_t = ctypes.c_uint32 # enum

# values for enumeration 'amdsmi_voltage_type_t'
amdsmi_voltage_type_t__enumvalues = {
    0: 'AMDSMI_VOLT_TYPE_FIRST',
    0: 'AMDSMI_VOLT_TYPE_VDDGFX',
    1: 'AMDSMI_VOLT_TYPE_VDDBOARD',
    1: 'AMDSMI_VOLT_TYPE_LAST',
    4294967295: 'AMDSMI_VOLT_TYPE_INVALID',
}
AMDSMI_VOLT_TYPE_FIRST = 0
AMDSMI_VOLT_TYPE_VDDGFX = 0
AMDSMI_VOLT_TYPE_VDDBOARD = 1
AMDSMI_VOLT_TYPE_LAST = 1
AMDSMI_VOLT_TYPE_INVALID = 4294967295
amdsmi_voltage_type_t = ctypes.c_uint32 # enum

# values for enumeration 'amdsmi_power_profile_preset_masks_t'
amdsmi_power_profile_preset_masks_t__enumvalues = {
    1: 'AMDSMI_PWR_PROF_PRST_CUSTOM_MASK',
    2: 'AMDSMI_PWR_PROF_PRST_VIDEO_MASK',
    4: 'AMDSMI_PWR_PROF_PRST_POWER_SAVING_MASK',
    8: 'AMDSMI_PWR_PROF_PRST_COMPUTE_MASK',
    16: 'AMDSMI_PWR_PROF_PRST_VR_MASK',
    32: 'AMDSMI_PWR_PROF_PRST_3D_FULL_SCR_MASK',
    64: 'AMDSMI_PWR_PROF_PRST_BOOTUP_DEFAULT',
    64: 'AMDSMI_PWR_PROF_PRST_LAST',
    18446744073709551615: 'AMDSMI_PWR_PROF_PRST_INVALID',
}
AMDSMI_PWR_PROF_PRST_CUSTOM_MASK = 1
AMDSMI_PWR_PROF_PRST_VIDEO_MASK = 2
AMDSMI_PWR_PROF_PRST_POWER_SAVING_MASK = 4
AMDSMI_PWR_PROF_PRST_COMPUTE_MASK = 8
AMDSMI_PWR_PROF_PRST_VR_MASK = 16
AMDSMI_PWR_PROF_PRST_3D_FULL_SCR_MASK = 32
AMDSMI_PWR_PROF_PRST_BOOTUP_DEFAULT = 64
AMDSMI_PWR_PROF_PRST_LAST = 64
AMDSMI_PWR_PROF_PRST_INVALID = 18446744073709551615
amdsmi_power_profile_preset_masks_t = ctypes.c_uint64 # enum

# values for enumeration 'amdsmi_gpu_block_t'
amdsmi_gpu_block_t__enumvalues = {
    0: 'AMDSMI_GPU_BLOCK_INVALID',
    1: 'AMDSMI_GPU_BLOCK_FIRST',
    1: 'AMDSMI_GPU_BLOCK_UMC',
    2: 'AMDSMI_GPU_BLOCK_SDMA',
    4: 'AMDSMI_GPU_BLOCK_GFX',
    8: 'AMDSMI_GPU_BLOCK_MMHUB',
    16: 'AMDSMI_GPU_BLOCK_ATHUB',
    32: 'AMDSMI_GPU_BLOCK_PCIE_BIF',
    64: 'AMDSMI_GPU_BLOCK_HDP',
    128: 'AMDSMI_GPU_BLOCK_XGMI_WAFL',
    256: 'AMDSMI_GPU_BLOCK_DF',
    512: 'AMDSMI_GPU_BLOCK_SMN',
    1024: 'AMDSMI_GPU_BLOCK_SEM',
    2048: 'AMDSMI_GPU_BLOCK_MP0',
    4096: 'AMDSMI_GPU_BLOCK_MP1',
    8192: 'AMDSMI_GPU_BLOCK_FUSE',
    16384: 'AMDSMI_GPU_BLOCK_MCA',
    32768: 'AMDSMI_GPU_BLOCK_VCN',
    65536: 'AMDSMI_GPU_BLOCK_JPEG',
    131072: 'AMDSMI_GPU_BLOCK_IH',
    262144: 'AMDSMI_GPU_BLOCK_MPIO',
    262144: 'AMDSMI_GPU_BLOCK_LAST',
    9223372036854775808: 'AMDSMI_GPU_BLOCK_RESERVED',
}
AMDSMI_GPU_BLOCK_INVALID = 0
AMDSMI_GPU_BLOCK_FIRST = 1
AMDSMI_GPU_BLOCK_UMC = 1
AMDSMI_GPU_BLOCK_SDMA = 2
AMDSMI_GPU_BLOCK_GFX = 4
AMDSMI_GPU_BLOCK_MMHUB = 8
AMDSMI_GPU_BLOCK_ATHUB = 16
AMDSMI_GPU_BLOCK_PCIE_BIF = 32
AMDSMI_GPU_BLOCK_HDP = 64
AMDSMI_GPU_BLOCK_XGMI_WAFL = 128
AMDSMI_GPU_BLOCK_DF = 256
AMDSMI_GPU_BLOCK_SMN = 512
AMDSMI_GPU_BLOCK_SEM = 1024
AMDSMI_GPU_BLOCK_MP0 = 2048
AMDSMI_GPU_BLOCK_MP1 = 4096
AMDSMI_GPU_BLOCK_FUSE = 8192
AMDSMI_GPU_BLOCK_MCA = 16384
AMDSMI_GPU_BLOCK_VCN = 32768
AMDSMI_GPU_BLOCK_JPEG = 65536
AMDSMI_GPU_BLOCK_IH = 131072
AMDSMI_GPU_BLOCK_MPIO = 262144
AMDSMI_GPU_BLOCK_LAST = 262144
AMDSMI_GPU_BLOCK_RESERVED = 9223372036854775808
amdsmi_gpu_block_t = ctypes.c_uint64 # enum

# values for enumeration 'amdsmi_clk_limit_type_t'
amdsmi_clk_limit_type_t__enumvalues = {
    0: 'CLK_LIMIT_MIN',
    1: 'CLK_LIMIT_MAX',
}
CLK_LIMIT_MIN = 0
CLK_LIMIT_MAX = 1
amdsmi_clk_limit_type_t = ctypes.c_uint32 # enum

# values for enumeration 'amdsmi_cper_sev_t'
amdsmi_cper_sev_t__enumvalues = {
    0: 'AMDSMI_CPER_SEV_NON_FATAL_UNCORRECTED',
    1: 'AMDSMI_CPER_SEV_FATAL',
    2: 'AMDSMI_CPER_SEV_NON_FATAL_CORRECTED',
    3: 'AMDSMI_CPER_SEV_NUM',
    10: 'AMDSMI_CPER_SEV_UNUSED',
}
AMDSMI_CPER_SEV_NON_FATAL_UNCORRECTED = 0
AMDSMI_CPER_SEV_FATAL = 1
AMDSMI_CPER_SEV_NON_FATAL_CORRECTED = 2
AMDSMI_CPER_SEV_NUM = 3
AMDSMI_CPER_SEV_UNUSED = 10
amdsmi_cper_sev_t = ctypes.c_uint32 # enum

# values for enumeration 'amdsmi_cper_notify_type_t'
amdsmi_cper_notify_type_t__enumvalues = {
    4976123370175105969: 'AMDSMI_CPER_NOTIFY_TYPE_CMC',
    5356425115412803478: 'AMDSMI_CPER_NOTIFY_TYPE_CPE',
    5531987820403847166: 'AMDSMI_CPER_NOTIFY_TYPE_MCE',
    5619395120325705759: 'AMDSMI_CPER_NOTIFY_TYPE_PCIE',
    4992964802890589160: 'AMDSMI_CPER_NOTIFY_TYPE_INIT',
    4812579876830546431: 'AMDSMI_CPER_NOTIFY_TYPE_NMI',
    4655221457236894822: 'AMDSMI_CPER_NOTIFY_TYPE_BOOT',
    5487573144795207569: 'AMDSMI_CPER_NOTIFY_TYPE_DMAR',
    1289362001033197706: 'AMDSMI_CPER_NOTIFY_TYPE_SEA',
    5658685719731260545: 'AMDSMI_CPER_NOTIFY_TYPE_SEI',
    4761520883332928940: 'AMDSMI_CPER_NOTIFY_TYPE_PEI',
    5306157213770398665: 'AMDSMI_CPER_NOTIFY_TYPE_CXL_COMPONENT',
}
AMDSMI_CPER_NOTIFY_TYPE_CMC = 4976123370175105969
AMDSMI_CPER_NOTIFY_TYPE_CPE = 5356425115412803478
AMDSMI_CPER_NOTIFY_TYPE_MCE = 5531987820403847166
AMDSMI_CPER_NOTIFY_TYPE_PCIE = 5619395120325705759
AMDSMI_CPER_NOTIFY_TYPE_INIT = 4992964802890589160
AMDSMI_CPER_NOTIFY_TYPE_NMI = 4812579876830546431
AMDSMI_CPER_NOTIFY_TYPE_BOOT = 4655221457236894822
AMDSMI_CPER_NOTIFY_TYPE_DMAR = 5487573144795207569
AMDSMI_CPER_NOTIFY_TYPE_SEA = 1289362001033197706
AMDSMI_CPER_NOTIFY_TYPE_SEI = 5658685719731260545
AMDSMI_CPER_NOTIFY_TYPE_PEI = 4761520883332928940
AMDSMI_CPER_NOTIFY_TYPE_CXL_COMPONENT = 5306157213770398665
amdsmi_cper_notify_type_t = ctypes.c_uint64 # enum

# values for enumeration 'amdsmi_ras_err_state_t'
amdsmi_ras_err_state_t__enumvalues = {
    0: 'AMDSMI_RAS_ERR_STATE_NONE',
    1: 'AMDSMI_RAS_ERR_STATE_DISABLED',
    2: 'AMDSMI_RAS_ERR_STATE_PARITY',
    3: 'AMDSMI_RAS_ERR_STATE_SING_C',
    4: 'AMDSMI_RAS_ERR_STATE_MULT_UC',
    5: 'AMDSMI_RAS_ERR_STATE_POISON',
    6: 'AMDSMI_RAS_ERR_STATE_ENABLED',
    6: 'AMDSMI_RAS_ERR_STATE_LAST',
    4294967295: 'AMDSMI_RAS_ERR_STATE_INVALID',
}
AMDSMI_RAS_ERR_STATE_NONE = 0
AMDSMI_RAS_ERR_STATE_DISABLED = 1
AMDSMI_RAS_ERR_STATE_PARITY = 2
AMDSMI_RAS_ERR_STATE_SING_C = 3
AMDSMI_RAS_ERR_STATE_MULT_UC = 4
AMDSMI_RAS_ERR_STATE_POISON = 5
AMDSMI_RAS_ERR_STATE_ENABLED = 6
AMDSMI_RAS_ERR_STATE_LAST = 6
AMDSMI_RAS_ERR_STATE_INVALID = 4294967295
amdsmi_ras_err_state_t = ctypes.c_uint32 # enum

# values for enumeration 'amdsmi_memory_type_t'
amdsmi_memory_type_t__enumvalues = {
    0: 'AMDSMI_MEM_TYPE_FIRST',
    0: 'AMDSMI_MEM_TYPE_VRAM',
    1: 'AMDSMI_MEM_TYPE_VIS_VRAM',
    2: 'AMDSMI_MEM_TYPE_GTT',
    2: 'AMDSMI_MEM_TYPE_LAST',
}
AMDSMI_MEM_TYPE_FIRST = 0
AMDSMI_MEM_TYPE_VRAM = 0
AMDSMI_MEM_TYPE_VIS_VRAM = 1
AMDSMI_MEM_TYPE_GTT = 2
AMDSMI_MEM_TYPE_LAST = 2
amdsmi_memory_type_t = ctypes.c_uint32 # enum

# values for enumeration 'amdsmi_freq_ind_t'
amdsmi_freq_ind_t__enumvalues = {
    0: 'AMDSMI_FREQ_IND_MIN',
    1: 'AMDSMI_FREQ_IND_MAX',
    4294967295: 'AMDSMI_FREQ_IND_INVALID',
}
AMDSMI_FREQ_IND_MIN = 0
AMDSMI_FREQ_IND_MAX = 1
AMDSMI_FREQ_IND_INVALID = 4294967295
amdsmi_freq_ind_t = ctypes.c_uint32 # enum

# values for enumeration 'amdsmi_xgmi_status_t'
amdsmi_xgmi_status_t__enumvalues = {
    0: 'AMDSMI_XGMI_STATUS_NO_ERRORS',
    1: 'AMDSMI_XGMI_STATUS_ERROR',
    2: 'AMDSMI_XGMI_STATUS_MULTIPLE_ERRORS',
}
AMDSMI_XGMI_STATUS_NO_ERRORS = 0
AMDSMI_XGMI_STATUS_ERROR = 1
AMDSMI_XGMI_STATUS_MULTIPLE_ERRORS = 2
amdsmi_xgmi_status_t = ctypes.c_uint32 # enum
amdsmi_bit_field_t = ctypes.c_uint64

# values for enumeration 'amdsmi_memory_page_status_t'
amdsmi_memory_page_status_t__enumvalues = {
    0: 'AMDSMI_MEM_PAGE_STATUS_RESERVED',
    1: 'AMDSMI_MEM_PAGE_STATUS_PENDING',
    2: 'AMDSMI_MEM_PAGE_STATUS_UNRESERVABLE',
}
AMDSMI_MEM_PAGE_STATUS_RESERVED = 0
AMDSMI_MEM_PAGE_STATUS_PENDING = 1
AMDSMI_MEM_PAGE_STATUS_UNRESERVABLE = 2
amdsmi_memory_page_status_t = ctypes.c_uint32 # enum

# values for enumeration 'amdsmi_io_link_type_t'
amdsmi_io_link_type_t__enumvalues = {
    0: 'AMDSMI_IOLINK_TYPE_UNDEFINED',
    1: 'AMDSMI_IOLINK_TYPE_PCIEXPRESS',
    2: 'AMDSMI_IOLINK_TYPE_XGMI',
    3: 'AMDSMI_IOLINK_TYPE_NUMIOLINKTYPES',
    4294967295: 'AMDSMI_IOLINK_TYPE_SIZE',
}
AMDSMI_IOLINK_TYPE_UNDEFINED = 0
AMDSMI_IOLINK_TYPE_PCIEXPRESS = 1
AMDSMI_IOLINK_TYPE_XGMI = 2
AMDSMI_IOLINK_TYPE_NUMIOLINKTYPES = 3
AMDSMI_IOLINK_TYPE_SIZE = 4294967295
amdsmi_io_link_type_t = ctypes.c_uint32 # enum

# values for enumeration 'amdsmi_utilization_counter_type_t'
amdsmi_utilization_counter_type_t__enumvalues = {
    0: 'AMDSMI_UTILIZATION_COUNTER_FIRST',
    0: 'AMDSMI_COARSE_GRAIN_GFX_ACTIVITY',
    1: 'AMDSMI_COARSE_GRAIN_MEM_ACTIVITY',
    2: 'AMDSMI_COARSE_DECODER_ACTIVITY',
    100: 'AMDSMI_FINE_GRAIN_GFX_ACTIVITY',
    101: 'AMDSMI_FINE_GRAIN_MEM_ACTIVITY',
    102: 'AMDSMI_FINE_DECODER_ACTIVITY',
    102: 'AMDSMI_UTILIZATION_COUNTER_LAST',
}
AMDSMI_UTILIZATION_COUNTER_FIRST = 0
AMDSMI_COARSE_GRAIN_GFX_ACTIVITY = 0
AMDSMI_COARSE_GRAIN_MEM_ACTIVITY = 1
AMDSMI_COARSE_DECODER_ACTIVITY = 2
AMDSMI_FINE_GRAIN_GFX_ACTIVITY = 100
AMDSMI_FINE_GRAIN_MEM_ACTIVITY = 101
AMDSMI_FINE_DECODER_ACTIVITY = 102
AMDSMI_UTILIZATION_COUNTER_LAST = 102
amdsmi_utilization_counter_type_t = ctypes.c_uint32 # enum
class struct_amdsmi_utilization_counter_t(Structure):
    pass

struct_amdsmi_utilization_counter_t._pack_ = 1 # source:False
struct_amdsmi_utilization_counter_t._fields_ = [
    ('type', amdsmi_utilization_counter_type_t),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('value', ctypes.c_uint64),
    ('fine_value', ctypes.c_uint64 * 4),
    ('fine_value_count', ctypes.c_uint16),
    ('PADDING_1', ctypes.c_ubyte * 6),
]

amdsmi_utilization_counter_t = struct_amdsmi_utilization_counter_t
class struct_amdsmi_retired_page_record_t(Structure):
    pass

struct_amdsmi_retired_page_record_t._pack_ = 1 # source:False
struct_amdsmi_retired_page_record_t._fields_ = [
    ('page_address', ctypes.c_uint64),
    ('page_size', ctypes.c_uint64),
    ('status', amdsmi_memory_page_status_t),
    ('PADDING_0', ctypes.c_ubyte * 4),
]

amdsmi_retired_page_record_t = struct_amdsmi_retired_page_record_t
class struct_amdsmi_power_profile_status_t(Structure):
    pass

struct_amdsmi_power_profile_status_t._pack_ = 1 # source:False
struct_amdsmi_power_profile_status_t._fields_ = [
    ('available_profiles', ctypes.c_uint64),
    ('current', amdsmi_power_profile_preset_masks_t),
    ('num_profiles', ctypes.c_uint32),
    ('PADDING_0', ctypes.c_ubyte * 4),
]

amdsmi_power_profile_status_t = struct_amdsmi_power_profile_status_t
class struct_amdsmi_frequencies_t(Structure):
    pass

struct_amdsmi_frequencies_t._pack_ = 1 # source:False
struct_amdsmi_frequencies_t._fields_ = [
    ('has_deep_sleep', ctypes.c_bool),
    ('PADDING_0', ctypes.c_ubyte * 3),
    ('num_supported', ctypes.c_uint32),
    ('current', ctypes.c_uint32),
    ('PADDING_1', ctypes.c_ubyte * 4),
    ('frequency', ctypes.c_uint64 * 33),
]

amdsmi_frequencies_t = struct_amdsmi_frequencies_t
class struct_amdsmi_dpm_policy_entry_t(Structure):
    pass

struct_amdsmi_dpm_policy_entry_t._pack_ = 1 # source:False
struct_amdsmi_dpm_policy_entry_t._fields_ = [
    ('policy_id', ctypes.c_uint32),
    ('policy_description', ctypes.c_char * 32),
]

amdsmi_dpm_policy_entry_t = struct_amdsmi_dpm_policy_entry_t
class struct_amdsmi_dpm_policy_t(Structure):
    pass

struct_amdsmi_dpm_policy_t._pack_ = 1 # source:False
struct_amdsmi_dpm_policy_t._fields_ = [
    ('num_supported', ctypes.c_uint32),
    ('current', ctypes.c_uint32),
    ('policies', struct_amdsmi_dpm_policy_entry_t * 32),
]

amdsmi_dpm_policy_t = struct_amdsmi_dpm_policy_t
class struct_amdsmi_pcie_bandwidth_t(Structure):
    pass

struct_amdsmi_pcie_bandwidth_t._pack_ = 1 # source:False
struct_amdsmi_pcie_bandwidth_t._fields_ = [
    ('transfer_rate', amdsmi_frequencies_t),
    ('lanes', ctypes.c_uint32 * 33),
    ('PADDING_0', ctypes.c_ubyte * 4),
]

amdsmi_pcie_bandwidth_t = struct_amdsmi_pcie_bandwidth_t
class struct_amdsmi_version_t(Structure):
    pass

struct_amdsmi_version_t._pack_ = 1 # source:False
struct_amdsmi_version_t._fields_ = [
    ('year', ctypes.c_uint32),
    ('major', ctypes.c_uint32),
    ('minor', ctypes.c_uint32),
    ('release', ctypes.c_uint32),
    ('build', ctypes.POINTER(ctypes.c_char)),
]

amdsmi_version_t = struct_amdsmi_version_t
class struct_amdsmi_od_vddc_point_t(Structure):
    pass

struct_amdsmi_od_vddc_point_t._pack_ = 1 # source:False
struct_amdsmi_od_vddc_point_t._fields_ = [
    ('frequency', ctypes.c_uint64),
    ('voltage', ctypes.c_uint64),
]

amdsmi_od_vddc_point_t = struct_amdsmi_od_vddc_point_t
class struct_amdsmi_freq_volt_region_t(Structure):
    _pack_ = 1 # source:False
    _fields_ = [
    ('freq_range', amdsmi_range_t),
    ('volt_range', amdsmi_range_t),
     ]

amdsmi_freq_volt_region_t = struct_amdsmi_freq_volt_region_t
class struct_amdsmi_od_volt_curve_t(Structure):
    _pack_ = 1 # source:False
    _fields_ = [
    ('vc_points', struct_amdsmi_od_vddc_point_t * 3),
     ]

amdsmi_od_volt_curve_t = struct_amdsmi_od_volt_curve_t
class struct_amdsmi_od_volt_freq_data_t(Structure):
    pass

struct_amdsmi_od_volt_freq_data_t._pack_ = 1 # source:False
struct_amdsmi_od_volt_freq_data_t._fields_ = [
    ('curr_sclk_range', amdsmi_range_t),
    ('curr_mclk_range', amdsmi_range_t),
    ('sclk_freq_limits', amdsmi_range_t),
    ('mclk_freq_limits', amdsmi_range_t),
    ('curve', amdsmi_od_volt_curve_t),
    ('num_regions', ctypes.c_uint32),
    ('PADDING_0', ctypes.c_ubyte * 4),
]

amdsmi_od_volt_freq_data_t = struct_amdsmi_od_volt_freq_data_t
class struct_amd_metrics_table_header_t(Structure):
    pass

struct_amd_metrics_table_header_t._pack_ = 1 # source:False
struct_amd_metrics_table_header_t._fields_ = [
    ('structure_size', ctypes.c_uint16),
    ('format_revision', ctypes.c_ubyte),
    ('content_revision', ctypes.c_ubyte),
]

amd_metrics_table_header_t = struct_amd_metrics_table_header_t
class struct_amdsmi_gpu_xcp_metrics_t(Structure):
    pass

struct_amdsmi_gpu_xcp_metrics_t._pack_ = 1 # source:False
struct_amdsmi_gpu_xcp_metrics_t._fields_ = [
    ('gfx_busy_inst', ctypes.c_uint32 * 8),
    ('jpeg_busy', ctypes.c_uint16 * 32),
    ('vcn_busy', ctypes.c_uint16 * 4),
    ('gfx_busy_acc', ctypes.c_uint64 * 8),
    ('gfx_below_host_limit_acc', ctypes.c_uint64 * 8),
]

amdsmi_gpu_xcp_metrics_t = struct_amdsmi_gpu_xcp_metrics_t
class struct_amdsmi_gpu_metrics_t(Structure):
    pass

struct_amdsmi_gpu_metrics_t._pack_ = 1 # source:False
struct_amdsmi_gpu_metrics_t._fields_ = [
    ('common_header', amd_metrics_table_header_t),
    ('temperature_edge', ctypes.c_uint16),
    ('temperature_hotspot', ctypes.c_uint16),
    ('temperature_mem', ctypes.c_uint16),
    ('temperature_vrgfx', ctypes.c_uint16),
    ('temperature_vrsoc', ctypes.c_uint16),
    ('temperature_vrmem', ctypes.c_uint16),
    ('average_gfx_activity', ctypes.c_uint16),
    ('average_umc_activity', ctypes.c_uint16),
    ('average_mm_activity', ctypes.c_uint16),
    ('average_socket_power', ctypes.c_uint16),
    ('energy_accumulator', ctypes.c_uint64),
    ('system_clock_counter', ctypes.c_uint64),
    ('average_gfxclk_frequency', ctypes.c_uint16),
    ('average_socclk_frequency', ctypes.c_uint16),
    ('average_uclk_frequency', ctypes.c_uint16),
    ('average_vclk0_frequency', ctypes.c_uint16),
    ('average_dclk0_frequency', ctypes.c_uint16),
    ('average_vclk1_frequency', ctypes.c_uint16),
    ('average_dclk1_frequency', ctypes.c_uint16),
    ('current_gfxclk', ctypes.c_uint16),
    ('current_socclk', ctypes.c_uint16),
    ('current_uclk', ctypes.c_uint16),
    ('current_vclk0', ctypes.c_uint16),
    ('current_dclk0', ctypes.c_uint16),
    ('current_vclk1', ctypes.c_uint16),
    ('current_dclk1', ctypes.c_uint16),
    ('throttle_status', ctypes.c_uint32),
    ('current_fan_speed', ctypes.c_uint16),
    ('pcie_link_width', ctypes.c_uint16),
    ('pcie_link_speed', ctypes.c_uint16),
    ('PADDING_0', ctypes.c_ubyte * 2),
    ('gfx_activity_acc', ctypes.c_uint32),
    ('mem_activity_acc', ctypes.c_uint32),
    ('temperature_hbm', ctypes.c_uint16 * 4),
    ('firmware_timestamp', ctypes.c_uint64),
    ('voltage_soc', ctypes.c_uint16),
    ('voltage_gfx', ctypes.c_uint16),
    ('voltage_mem', ctypes.c_uint16),
    ('PADDING_1', ctypes.c_ubyte * 2),
    ('indep_throttle_status', ctypes.c_uint64),
    ('current_socket_power', ctypes.c_uint16),
    ('vcn_activity', ctypes.c_uint16 * 4),
    ('PADDING_2', ctypes.c_ubyte * 2),
    ('gfxclk_lock_status', ctypes.c_uint32),
    ('xgmi_link_width', ctypes.c_uint16),
    ('xgmi_link_speed', ctypes.c_uint16),
    ('PADDING_3', ctypes.c_ubyte * 4),
    ('pcie_bandwidth_acc', ctypes.c_uint64),
    ('pcie_bandwidth_inst', ctypes.c_uint64),
    ('pcie_l0_to_recov_count_acc', ctypes.c_uint64),
    ('pcie_replay_count_acc', ctypes.c_uint64),
    ('pcie_replay_rover_count_acc', ctypes.c_uint64),
    ('xgmi_read_data_acc', ctypes.c_uint64 * 8),
    ('xgmi_write_data_acc', ctypes.c_uint64 * 8),
    ('current_gfxclks', ctypes.c_uint16 * 8),
    ('current_socclks', ctypes.c_uint16 * 4),
    ('current_vclk0s', ctypes.c_uint16 * 4),
    ('current_dclk0s', ctypes.c_uint16 * 4),
    ('jpeg_activity', ctypes.c_uint16 * 32),
    ('pcie_nak_sent_count_acc', ctypes.c_uint32),
    ('pcie_nak_rcvd_count_acc', ctypes.c_uint32),
    ('accumulation_counter', ctypes.c_uint64),
    ('prochot_residency_acc', ctypes.c_uint64),
    ('ppt_residency_acc', ctypes.c_uint64),
    ('socket_thm_residency_acc', ctypes.c_uint64),
    ('vr_thm_residency_acc', ctypes.c_uint64),
    ('hbm_thm_residency_acc', ctypes.c_uint64),
    ('num_partition', ctypes.c_uint16),
    ('PADDING_4', ctypes.c_ubyte * 6),
    ('xcp_stats', struct_amdsmi_gpu_xcp_metrics_t * 8),
    ('pcie_lc_perf_other_end_recovery', ctypes.c_uint32),
    ('PADDING_5', ctypes.c_ubyte * 4),
    ('vram_max_bandwidth', ctypes.c_uint64),
    ('xgmi_link_status', ctypes.c_uint16 * 8),
]

amdsmi_gpu_metrics_t = struct_amdsmi_gpu_metrics_t

# values for enumeration 'amdsmi_xgmi_link_status_type_t'
amdsmi_xgmi_link_status_type_t__enumvalues = {
    0: 'AMDSMI_XGMI_LINK_DOWN',
    1: 'AMDSMI_XGMI_LINK_UP',
    2: 'AMDSMI_XGMI_LINK_DISABLE',
}
AMDSMI_XGMI_LINK_DOWN = 0
AMDSMI_XGMI_LINK_UP = 1
AMDSMI_XGMI_LINK_DISABLE = 2
amdsmi_xgmi_link_status_type_t = ctypes.c_uint32 # enum
class struct_amdsmi_xgmi_link_status_t(Structure):
    pass

struct_amdsmi_xgmi_link_status_t._pack_ = 1 # source:False
struct_amdsmi_xgmi_link_status_t._fields_ = [
    ('total_links', ctypes.c_uint32),
    ('status', amdsmi_xgmi_link_status_type_t * 8),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('reserved', ctypes.c_uint64 * 7),
]

amdsmi_xgmi_link_status_t = struct_amdsmi_xgmi_link_status_t
class struct_amdsmi_name_value_t(Structure):
    pass

struct_amdsmi_name_value_t._pack_ = 1 # source:False
struct_amdsmi_name_value_t._fields_ = [
    ('name', ctypes.c_char * 64),
    ('value', ctypes.c_uint64),
]

amdsmi_name_value_t = struct_amdsmi_name_value_t

# values for enumeration 'amdsmi_reg_type_t'
amdsmi_reg_type_t__enumvalues = {
    0: 'AMDSMI_REG_XGMI',
    1: 'AMDSMI_REG_WAFL',
    2: 'AMDSMI_REG_PCIE',
    3: 'AMDSMI_REG_USR',
    4: 'AMDSMI_REG_USR1',
}
AMDSMI_REG_XGMI = 0
AMDSMI_REG_WAFL = 1
AMDSMI_REG_PCIE = 2
AMDSMI_REG_USR = 3
AMDSMI_REG_USR1 = 4
amdsmi_reg_type_t = ctypes.c_uint32 # enum
class struct_amdsmi_ras_feature_t(Structure):
    pass

struct_amdsmi_ras_feature_t._pack_ = 1 # source:False
struct_amdsmi_ras_feature_t._fields_ = [
    ('ras_eeprom_version', ctypes.c_uint32),
    ('ecc_correction_schema_flag', ctypes.c_uint32),
]

amdsmi_ras_feature_t = struct_amdsmi_ras_feature_t
class struct_amdsmi_error_count_t(Structure):
    pass

struct_amdsmi_error_count_t._pack_ = 1 # source:False
struct_amdsmi_error_count_t._fields_ = [
    ('correctable_count', ctypes.c_uint64),
    ('uncorrectable_count', ctypes.c_uint64),
    ('deferred_count', ctypes.c_uint64),
    ('reserved', ctypes.c_uint64 * 5),
]

amdsmi_error_count_t = struct_amdsmi_error_count_t
class struct_amdsmi_process_info_t(Structure):
    pass

struct_amdsmi_process_info_t._pack_ = 1 # source:False
struct_amdsmi_process_info_t._fields_ = [
    ('process_id', ctypes.c_uint32),
    ('pasid', ctypes.c_uint32),
    ('vram_usage', ctypes.c_uint64),
    ('sdma_usage', ctypes.c_uint64),
    ('cu_occupancy', ctypes.c_uint32),
    ('PADDING_0', ctypes.c_ubyte * 4),
]

amdsmi_process_info_t = struct_amdsmi_process_info_t
class struct_amdsmi_topology_nearest_t(Structure):
    pass

struct_amdsmi_topology_nearest_t._pack_ = 1 # source:False
struct_amdsmi_topology_nearest_t._fields_ = [
    ('count', ctypes.c_uint32),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('processor_list', ctypes.POINTER(None) * 32),
    ('reserved', ctypes.c_uint64 * 15),
]

amdsmi_topology_nearest_t = struct_amdsmi_topology_nearest_t

# values for enumeration 'amdsmi_virtualization_mode_t'
amdsmi_virtualization_mode_t__enumvalues = {
    0: 'AMDSMI_VIRTUALIZATION_MODE_UNKNOWN',
    1: 'AMDSMI_VIRTUALIZATION_MODE_BAREMETAL',
    2: 'AMDSMI_VIRTUALIZATION_MODE_HOST',
    3: 'AMDSMI_VIRTUALIZATION_MODE_GUEST',
    4: 'AMDSMI_VIRTUALIZATION_MODE_PASSTHROUGH',
}
AMDSMI_VIRTUALIZATION_MODE_UNKNOWN = 0
AMDSMI_VIRTUALIZATION_MODE_BAREMETAL = 1
AMDSMI_VIRTUALIZATION_MODE_HOST = 2
AMDSMI_VIRTUALIZATION_MODE_GUEST = 3
AMDSMI_VIRTUALIZATION_MODE_PASSTHROUGH = 4
amdsmi_virtualization_mode_t = ctypes.c_uint32 # enum
class struct_amdsmi_smu_fw_version_t(Structure):
    pass

struct_amdsmi_smu_fw_version_t._pack_ = 1 # source:False
struct_amdsmi_smu_fw_version_t._fields_ = [
    ('debug', ctypes.c_ubyte),
    ('minor', ctypes.c_ubyte),
    ('major', ctypes.c_ubyte),
    ('unused', ctypes.c_ubyte),
]

amdsmi_smu_fw_version_t = struct_amdsmi_smu_fw_version_t
class struct_amdsmi_ddr_bw_metrics_t(Structure):
    pass

struct_amdsmi_ddr_bw_metrics_t._pack_ = 1 # source:False
struct_amdsmi_ddr_bw_metrics_t._fields_ = [
    ('max_bw', ctypes.c_uint32),
    ('utilized_bw', ctypes.c_uint32),
    ('utilized_pct', ctypes.c_uint32),
]

amdsmi_ddr_bw_metrics_t = struct_amdsmi_ddr_bw_metrics_t
class struct_amdsmi_temp_range_refresh_rate_t(Structure):
    pass

struct_amdsmi_temp_range_refresh_rate_t._pack_ = 1 # source:False
struct_amdsmi_temp_range_refresh_rate_t._fields_ = [
    ('range', ctypes.c_ubyte, 3),
    ('ref_rate', ctypes.c_ubyte, 1),
    ('PADDING_0', ctypes.c_uint8, 4),
]

amdsmi_temp_range_refresh_rate_t = struct_amdsmi_temp_range_refresh_rate_t
class struct_amdsmi_dimm_power_t(Structure):
    pass

struct_amdsmi_dimm_power_t._pack_ = 1 # source:False
struct_amdsmi_dimm_power_t._fields_ = [
    ('power', ctypes.c_uint16, 15),
    ('PADDING_0', ctypes.c_uint8, 1),
    ('update_rate', ctypes.c_uint16, 9),
    ('PADDING_1', ctypes.c_uint8, 7),
    ('dimm_addr', ctypes.c_uint16, 8),
    ('PADDING_2', ctypes.c_uint8, 8),
]

amdsmi_dimm_power_t = struct_amdsmi_dimm_power_t
class struct_amdsmi_dimm_thermal_t(Structure):
    pass

struct_amdsmi_dimm_thermal_t._pack_ = 1 # source:False
struct_amdsmi_dimm_thermal_t._fields_ = [
    ('sensor', ctypes.c_uint16, 11),
    ('PADDING_0', ctypes.c_uint8, 5),
    ('update_rate', ctypes.c_uint16, 9),
    ('PADDING_1', ctypes.c_uint8, 7),
    ('dimm_addr', ctypes.c_uint16, 8),
    ('PADDING_2', ctypes.c_uint32, 24),
    ('temp', ctypes.c_float),
]

amdsmi_dimm_thermal_t = struct_amdsmi_dimm_thermal_t

# values for enumeration 'amdsmi_io_bw_encoding_t'
amdsmi_io_bw_encoding_t__enumvalues = {
    1: 'AGG_BW0',
    2: 'RD_BW0',
    4: 'WR_BW0',
}
AGG_BW0 = 1
RD_BW0 = 2
WR_BW0 = 4
amdsmi_io_bw_encoding_t = ctypes.c_uint32 # enum
class struct_amdsmi_link_id_bw_type_t(Structure):
    pass

struct_amdsmi_link_id_bw_type_t._pack_ = 1 # source:False
struct_amdsmi_link_id_bw_type_t._fields_ = [
    ('bw_type', amdsmi_io_bw_encoding_t),
    ('PADDING_0', ctypes.c_ubyte * 4),
    ('link_name', ctypes.POINTER(ctypes.c_char)),
]

amdsmi_link_id_bw_type_t = struct_amdsmi_link_id_bw_type_t
class struct_amdsmi_dpm_level_t(Structure):
    pass

struct_amdsmi_dpm_level_t._pack_ = 1 # source:False
struct_amdsmi_dpm_level_t._fields_ = [
    ('max_dpm_level', ctypes.c_ubyte),
    ('min_dpm_level', ctypes.c_ubyte),
]

amdsmi_dpm_level_t = struct_amdsmi_dpm_level_t
class struct_amdsmi_hsmp_metrics_table_t(Structure):
    pass

struct_amdsmi_hsmp_metrics_table_t._pack_ = 1 # source:True
struct_amdsmi_hsmp_metrics_table_t._fields_ = [
    ('accumulation_counter', ctypes.c_uint32),
    ('max_socket_temperature', ctypes.c_uint32),
    ('max_vr_temperature', ctypes.c_uint32),
    ('max_hbm_temperature', ctypes.c_uint32),
    ('max_socket_temperature_acc', ctypes.c_uint64),
    ('max_vr_temperature_acc', ctypes.c_uint64),
    ('max_hbm_temperature_acc', ctypes.c_uint64),
    ('socket_power_limit', ctypes.c_uint32),
    ('max_socket_power_limit', ctypes.c_uint32),
    ('socket_power', ctypes.c_uint32),
    ('timestamp', ctypes.c_uint64),
    ('socket_energy_acc', ctypes.c_uint64),
    ('ccd_energy_acc', ctypes.c_uint64),
    ('xcd_energy_acc', ctypes.c_uint64),
    ('aid_energy_acc', ctypes.c_uint64),
    ('hbm_energy_acc', ctypes.c_uint64),
    ('cclk_frequency_limit', ctypes.c_uint32),
    ('gfxclk_frequency_limit', ctypes.c_uint32),
    ('fclk_frequency', ctypes.c_uint32),
    ('uclk_frequency', ctypes.c_uint32),
    ('socclk_frequency', ctypes.c_uint32 * 4),
    ('vclk_frequency', ctypes.c_uint32 * 4),
    ('dclk_frequency', ctypes.c_uint32 * 4),
    ('lclk_frequency', ctypes.c_uint32 * 4),
    ('gfxclk_frequency_acc', ctypes.c_uint64 * 8),
    ('cclk_frequency_acc', ctypes.c_uint64 * 96),
    ('max_cclk_frequency', ctypes.c_uint32),
    ('min_cclk_frequency', ctypes.c_uint32),
    ('max_gfxclk_frequency', ctypes.c_uint32),
    ('min_gfxclk_frequency', ctypes.c_uint32),
    ('fclk_frequency_table', ctypes.c_uint32 * 4),
    ('uclk_frequency_table', ctypes.c_uint32 * 4),
    ('socclk_frequency_table', ctypes.c_uint32 * 4),
    ('vclk_frequency_table', ctypes.c_uint32 * 4),
    ('dclk_frequency_table', ctypes.c_uint32 * 4),
    ('lclk_frequency_table', ctypes.c_uint32 * 4),
    ('max_lclk_dpm_range', ctypes.c_uint32),
    ('min_lclk_dpm_range', ctypes.c_uint32),
    ('xgmi_width', ctypes.c_uint32),
    ('xgmi_bitrate', ctypes.c_uint32),
    ('xgmi_read_bandwidth_acc', ctypes.c_uint64 * 8),
    ('xgmi_write_bandwidth_acc', ctypes.c_uint64 * 8),
    ('socket_c0_residency', ctypes.c_uint32),
    ('socket_gfx_busy', ctypes.c_uint32),
    ('dram_bandwidth_utilization', ctypes.c_uint32),
    ('socket_c0_residency_acc', ctypes.c_uint64),
    ('socket_gfx_busy_acc', ctypes.c_uint64),
    ('dram_bandwidth_acc', ctypes.c_uint64),
    ('max_dram_bandwidth', ctypes.c_uint32),
    ('dram_bandwidth_utilization_acc', ctypes.c_uint64),
    ('pcie_bandwidth_acc', ctypes.c_uint64 * 4),
    ('prochot_residency_acc', ctypes.c_uint32),
    ('ppt_residency_acc', ctypes.c_uint32),
    ('socket_thm_residency_acc', ctypes.c_uint32),
    ('vr_thm_residency_acc', ctypes.c_uint32),
    ('hbm_thm_residency_acc', ctypes.c_uint32),
    ('spare', ctypes.c_uint32),
    ('gfxclk_frequency', ctypes.c_uint32 * 8),
]

amdsmi_hsmp_metrics_table_t = struct_amdsmi_hsmp_metrics_table_t
amdsmi_hsmp_freqlimit_src_names = ['cHTC-Active', 'PROCHOT', 'TDC limit', 'PPT Limit', 'OPN Max', 'Reliability Limit', 'APML Agent', 'HSMP Agent'] # Variable ctypes.POINTER(ctypes.c_char) * 8
uint64_t = ctypes.c_uint64
amdsmi_init = _libraries['libamd_smi.so'].amdsmi_init
amdsmi_init.restype = amdsmi_status_t
amdsmi_init.argtypes = [uint64_t]
amdsmi_shut_down = _libraries['libamd_smi.so'].amdsmi_shut_down
amdsmi_shut_down.restype = amdsmi_status_t
amdsmi_shut_down.argtypes = []
amdsmi_get_socket_handles = _libraries['libamd_smi.so'].amdsmi_get_socket_handles
amdsmi_get_socket_handles.restype = amdsmi_status_t
amdsmi_get_socket_handles.argtypes = [ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.POINTER(None))]
amdsmi_get_cpu_handles = _libraries['libamd_smi.so'].amdsmi_get_cpu_handles
amdsmi_get_cpu_handles.restype = amdsmi_status_t
amdsmi_get_cpu_handles.argtypes = [ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.POINTER(None))]
size_t = ctypes.c_uint64
amdsmi_get_socket_info = _libraries['libamd_smi.so'].amdsmi_get_socket_info
amdsmi_get_socket_info.restype = amdsmi_status_t
amdsmi_get_socket_info.argtypes = [amdsmi_socket_handle, size_t, ctypes.POINTER(ctypes.c_char)]
amdsmi_get_processor_info = _libraries['libamd_smi.so'].amdsmi_get_processor_info
amdsmi_get_processor_info.restype = amdsmi_status_t
amdsmi_get_processor_info.argtypes = [amdsmi_processor_handle, size_t, ctypes.POINTER(ctypes.c_char)]
amdsmi_get_processor_count_from_handles = _libraries['libamd_smi.so'].amdsmi_get_processor_count_from_handles
amdsmi_get_processor_count_from_handles.restype = amdsmi_status_t
amdsmi_get_processor_count_from_handles.argtypes = [ctypes.POINTER(ctypes.POINTER(None)), ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_uint32)]
amdsmi_get_processor_handles_by_type = _libraries['libamd_smi.so'].amdsmi_get_processor_handles_by_type
amdsmi_get_processor_handles_by_type.restype = amdsmi_status_t
amdsmi_get_processor_handles_by_type.argtypes = [amdsmi_socket_handle, processor_type_t, ctypes.POINTER(ctypes.POINTER(None)), ctypes.POINTER(ctypes.c_uint32)]
amdsmi_get_processor_handles = _libraries['libamd_smi.so'].amdsmi_get_processor_handles
amdsmi_get_processor_handles.restype = amdsmi_status_t
amdsmi_get_processor_handles.argtypes = [amdsmi_socket_handle, ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.POINTER(None))]
amdsmi_get_cpucore_handles = _libraries['libamd_smi.so'].amdsmi_get_cpucore_handles
amdsmi_get_cpucore_handles.restype = amdsmi_status_t
amdsmi_get_cpucore_handles.argtypes = [ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.POINTER(None))]
amdsmi_get_processor_type = _libraries['libamd_smi.so'].amdsmi_get_processor_type
amdsmi_get_processor_type.restype = amdsmi_status_t
amdsmi_get_processor_type.argtypes = [amdsmi_processor_handle, ctypes.POINTER(processor_type_t)]
amdsmi_get_processor_handle_from_bdf = _libraries['libamd_smi.so'].amdsmi_get_processor_handle_from_bdf
amdsmi_get_processor_handle_from_bdf.restype = amdsmi_status_t
amdsmi_get_processor_handle_from_bdf.argtypes = [amdsmi_bdf_t, ctypes.POINTER(ctypes.POINTER(None))]
amdsmi_get_gpu_device_bdf = _libraries['libamd_smi.so'].amdsmi_get_gpu_device_bdf
amdsmi_get_gpu_device_bdf.restype = amdsmi_status_t
amdsmi_get_gpu_device_bdf.argtypes = [amdsmi_processor_handle, ctypes.POINTER(union_amdsmi_bdf_t)]
amdsmi_get_gpu_device_uuid = _libraries['libamd_smi.so'].amdsmi_get_gpu_device_uuid
amdsmi_get_gpu_device_uuid.restype = amdsmi_status_t
amdsmi_get_gpu_device_uuid.argtypes = [amdsmi_processor_handle, ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_char)]
amdsmi_get_gpu_enumeration_info = _libraries['libamd_smi.so'].amdsmi_get_gpu_enumeration_info
amdsmi_get_gpu_enumeration_info.restype = amdsmi_status_t
amdsmi_get_gpu_enumeration_info.argtypes = [amdsmi_processor_handle, ctypes.POINTER(struct_amdsmi_enumeration_info_t)]
amdsmi_get_gpu_id = _libraries['libamd_smi.so'].amdsmi_get_gpu_id
amdsmi_get_gpu_id.restype = amdsmi_status_t
amdsmi_get_gpu_id.argtypes = [amdsmi_processor_handle, ctypes.POINTER(ctypes.c_uint16)]
amdsmi_get_gpu_revision = _libraries['libamd_smi.so'].amdsmi_get_gpu_revision
amdsmi_get_gpu_revision.restype = amdsmi_status_t
amdsmi_get_gpu_revision.argtypes = [amdsmi_processor_handle, ctypes.POINTER(ctypes.c_uint16)]
amdsmi_get_gpu_vendor_name = _libraries['libamd_smi.so'].amdsmi_get_gpu_vendor_name
amdsmi_get_gpu_vendor_name.restype = amdsmi_status_t
amdsmi_get_gpu_vendor_name.argtypes = [amdsmi_processor_handle, ctypes.POINTER(ctypes.c_char), size_t]
uint32_t = ctypes.c_uint32
amdsmi_get_gpu_vram_vendor = _libraries['libamd_smi.so'].amdsmi_get_gpu_vram_vendor
amdsmi_get_gpu_vram_vendor.restype = amdsmi_status_t
amdsmi_get_gpu_vram_vendor.argtypes = [amdsmi_processor_handle, ctypes.POINTER(ctypes.c_char), uint32_t]
amdsmi_get_gpu_subsystem_id = _libraries['libamd_smi.so'].amdsmi_get_gpu_subsystem_id
amdsmi_get_gpu_subsystem_id.restype = amdsmi_status_t
amdsmi_get_gpu_subsystem_id.argtypes = [amdsmi_processor_handle, ctypes.POINTER(ctypes.c_uint16)]
amdsmi_get_gpu_subsystem_name = _libraries['libamd_smi.so'].amdsmi_get_gpu_subsystem_name
amdsmi_get_gpu_subsystem_name.restype = amdsmi_status_t
amdsmi_get_gpu_subsystem_name.argtypes = [amdsmi_processor_handle, ctypes.POINTER(ctypes.c_char), size_t]
amdsmi_get_gpu_virtualization_mode = _libraries['libamd_smi.so'].amdsmi_get_gpu_virtualization_mode
amdsmi_get_gpu_virtualization_mode.restype = amdsmi_status_t
amdsmi_get_gpu_virtualization_mode.argtypes = [amdsmi_processor_handle, ctypes.POINTER(amdsmi_virtualization_mode_t)]
amdsmi_get_gpu_pci_bandwidth = _libraries['libamd_smi.so'].amdsmi_get_gpu_pci_bandwidth
amdsmi_get_gpu_pci_bandwidth.restype = amdsmi_status_t
amdsmi_get_gpu_pci_bandwidth.argtypes = [amdsmi_processor_handle, ctypes.POINTER(struct_amdsmi_pcie_bandwidth_t)]
amdsmi_get_gpu_bdf_id = _libraries['libamd_smi.so'].amdsmi_get_gpu_bdf_id
amdsmi_get_gpu_bdf_id.restype = amdsmi_status_t
amdsmi_get_gpu_bdf_id.argtypes = [amdsmi_processor_handle, ctypes.POINTER(ctypes.c_uint64)]
amdsmi_get_gpu_topo_numa_affinity = _libraries['libamd_smi.so'].amdsmi_get_gpu_topo_numa_affinity
amdsmi_get_gpu_topo_numa_affinity.restype = amdsmi_status_t
amdsmi_get_gpu_topo_numa_affinity.argtypes = [amdsmi_processor_handle, ctypes.POINTER(ctypes.c_int32)]
amdsmi_get_gpu_pci_throughput = _libraries['libamd_smi.so'].amdsmi_get_gpu_pci_throughput
amdsmi_get_gpu_pci_throughput.restype = amdsmi_status_t
amdsmi_get_gpu_pci_throughput.argtypes = [amdsmi_processor_handle, ctypes.POINTER(ctypes.c_uint64), ctypes.POINTER(ctypes.c_uint64), ctypes.POINTER(ctypes.c_uint64)]
amdsmi_get_gpu_pci_replay_counter = _libraries['libamd_smi.so'].amdsmi_get_gpu_pci_replay_counter
amdsmi_get_gpu_pci_replay_counter.restype = amdsmi_status_t
amdsmi_get_gpu_pci_replay_counter.argtypes = [amdsmi_processor_handle, ctypes.POINTER(ctypes.c_uint64)]
amdsmi_set_gpu_pci_bandwidth = _libraries['libamd_smi.so'].amdsmi_set_gpu_pci_bandwidth
amdsmi_set_gpu_pci_bandwidth.restype = amdsmi_status_t
amdsmi_set_gpu_pci_bandwidth.argtypes = [amdsmi_processor_handle, uint64_t]
amdsmi_get_energy_count = _libraries['libamd_smi.so'].amdsmi_get_energy_count
amdsmi_get_energy_count.restype = amdsmi_status_t
amdsmi_get_energy_count.argtypes = [amdsmi_processor_handle, ctypes.POINTER(ctypes.c_uint64), ctypes.POINTER(ctypes.c_float), ctypes.POINTER(ctypes.c_uint64)]
amdsmi_set_power_cap = _libraries['libamd_smi.so'].amdsmi_set_power_cap
amdsmi_set_power_cap.restype = amdsmi_status_t
amdsmi_set_power_cap.argtypes = [amdsmi_processor_handle, uint32_t, uint64_t]
amdsmi_set_gpu_power_profile = _libraries['libamd_smi.so'].amdsmi_set_gpu_power_profile
amdsmi_set_gpu_power_profile.restype = amdsmi_status_t
amdsmi_set_gpu_power_profile.argtypes = [amdsmi_processor_handle, uint32_t, amdsmi_power_profile_preset_masks_t]
amdsmi_get_cpu_socket_power = _libraries['libamd_smi.so'].amdsmi_get_cpu_socket_power
amdsmi_get_cpu_socket_power.restype = amdsmi_status_t
amdsmi_get_cpu_socket_power.argtypes = [amdsmi_processor_handle, ctypes.POINTER(ctypes.c_uint32)]
amdsmi_get_cpu_socket_power_cap = _libraries['libamd_smi.so'].amdsmi_get_cpu_socket_power_cap
amdsmi_get_cpu_socket_power_cap.restype = amdsmi_status_t
amdsmi_get_cpu_socket_power_cap.argtypes = [amdsmi_processor_handle, ctypes.POINTER(ctypes.c_uint32)]
amdsmi_get_cpu_socket_power_cap_max = _libraries['libamd_smi.so'].amdsmi_get_cpu_socket_power_cap_max
amdsmi_get_cpu_socket_power_cap_max.restype = amdsmi_status_t
amdsmi_get_cpu_socket_power_cap_max.argtypes = [amdsmi_processor_handle, ctypes.POINTER(ctypes.c_uint32)]
amdsmi_get_cpu_pwr_svi_telemetry_all_rails = _libraries['libamd_smi.so'].amdsmi_get_cpu_pwr_svi_telemetry_all_rails
amdsmi_get_cpu_pwr_svi_telemetry_all_rails.restype = amdsmi_status_t
amdsmi_get_cpu_pwr_svi_telemetry_all_rails.argtypes = [amdsmi_processor_handle, ctypes.POINTER(ctypes.c_uint32)]
amdsmi_set_cpu_socket_power_cap = _libraries['libamd_smi.so'].amdsmi_set_cpu_socket_power_cap
amdsmi_set_cpu_socket_power_cap.restype = amdsmi_status_t
amdsmi_set_cpu_socket_power_cap.argtypes = [amdsmi_processor_handle, uint32_t]
uint8_t = ctypes.c_uint8
amdsmi_set_cpu_pwr_efficiency_mode = _libraries['libamd_smi.so'].amdsmi_set_cpu_pwr_efficiency_mode
amdsmi_set_cpu_pwr_efficiency_mode.restype = amdsmi_status_t
amdsmi_set_cpu_pwr_efficiency_mode.argtypes = [amdsmi_processor_handle, uint8_t]
amdsmi_get_gpu_memory_total = _libraries['libamd_smi.so'].amdsmi_get_gpu_memory_total
amdsmi_get_gpu_memory_total.restype = amdsmi_status_t
amdsmi_get_gpu_memory_total.argtypes = [amdsmi_processor_handle, amdsmi_memory_type_t, ctypes.POINTER(ctypes.c_uint64)]
amdsmi_get_gpu_memory_usage = _libraries['libamd_smi.so'].amdsmi_get_gpu_memory_usage
amdsmi_get_gpu_memory_usage.restype = amdsmi_status_t
amdsmi_get_gpu_memory_usage.argtypes = [amdsmi_processor_handle, amdsmi_memory_type_t, ctypes.POINTER(ctypes.c_uint64)]
amdsmi_get_gpu_bad_page_info = _libraries['libamd_smi.so'].amdsmi_get_gpu_bad_page_info
amdsmi_get_gpu_bad_page_info.restype = amdsmi_status_t
amdsmi_get_gpu_bad_page_info.argtypes = [amdsmi_processor_handle, ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(struct_amdsmi_retired_page_record_t)]
amdsmi_get_gpu_bad_page_threshold = _libraries['libamd_smi.so'].amdsmi_get_gpu_bad_page_threshold
amdsmi_get_gpu_bad_page_threshold.restype = amdsmi_status_t
amdsmi_get_gpu_bad_page_threshold.argtypes = [amdsmi_processor_handle, ctypes.POINTER(ctypes.c_uint32)]
amdsmi_gpu_validate_ras_eeprom = _libraries['libamd_smi.so'].amdsmi_gpu_validate_ras_eeprom
amdsmi_gpu_validate_ras_eeprom.restype = amdsmi_status_t
amdsmi_gpu_validate_ras_eeprom.argtypes = [amdsmi_processor_handle]
amdsmi_get_gpu_ras_feature_info = _libraries['libamd_smi.so'].amdsmi_get_gpu_ras_feature_info
amdsmi_get_gpu_ras_feature_info.restype = amdsmi_status_t
amdsmi_get_gpu_ras_feature_info.argtypes = [amdsmi_processor_handle, ctypes.POINTER(struct_amdsmi_ras_feature_t)]
amdsmi_get_gpu_ras_block_features_enabled = _libraries['libamd_smi.so'].amdsmi_get_gpu_ras_block_features_enabled
amdsmi_get_gpu_ras_block_features_enabled.restype = amdsmi_status_t
amdsmi_get_gpu_ras_block_features_enabled.argtypes = [amdsmi_processor_handle, amdsmi_gpu_block_t, ctypes.POINTER(amdsmi_ras_err_state_t)]
amdsmi_get_gpu_memory_reserved_pages = _libraries['libamd_smi.so'].amdsmi_get_gpu_memory_reserved_pages
amdsmi_get_gpu_memory_reserved_pages.restype = amdsmi_status_t
amdsmi_get_gpu_memory_reserved_pages.argtypes = [amdsmi_processor_handle, ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(struct_amdsmi_retired_page_record_t)]
amdsmi_get_gpu_fan_rpms = _libraries['libamd_smi.so'].amdsmi_get_gpu_fan_rpms
amdsmi_get_gpu_fan_rpms.restype = amdsmi_status_t
amdsmi_get_gpu_fan_rpms.argtypes = [amdsmi_processor_handle, uint32_t, ctypes.POINTER(ctypes.c_int64)]
amdsmi_get_gpu_fan_speed = _libraries['libamd_smi.so'].amdsmi_get_gpu_fan_speed
amdsmi_get_gpu_fan_speed.restype = amdsmi_status_t
amdsmi_get_gpu_fan_speed.argtypes = [amdsmi_processor_handle, uint32_t, ctypes.POINTER(ctypes.c_int64)]
amdsmi_get_gpu_fan_speed_max = _libraries['libamd_smi.so'].amdsmi_get_gpu_fan_speed_max
amdsmi_get_gpu_fan_speed_max.restype = amdsmi_status_t
amdsmi_get_gpu_fan_speed_max.argtypes = [amdsmi_processor_handle, uint32_t, ctypes.POINTER(ctypes.c_uint64)]
amdsmi_get_temp_metric = _libraries['libamd_smi.so'].amdsmi_get_temp_metric
amdsmi_get_temp_metric.restype = amdsmi_status_t
amdsmi_get_temp_metric.argtypes = [amdsmi_processor_handle, amdsmi_temperature_type_t, amdsmi_temperature_metric_t, ctypes.POINTER(ctypes.c_int64)]
amdsmi_get_gpu_cache_info = _libraries['libamd_smi.so'].amdsmi_get_gpu_cache_info
amdsmi_get_gpu_cache_info.restype = amdsmi_status_t
amdsmi_get_gpu_cache_info.argtypes = [amdsmi_processor_handle, ctypes.POINTER(struct_amdsmi_gpu_cache_info_t)]
amdsmi_get_gpu_volt_metric = _libraries['libamd_smi.so'].amdsmi_get_gpu_volt_metric
amdsmi_get_gpu_volt_metric.restype = amdsmi_status_t
amdsmi_get_gpu_volt_metric.argtypes = [amdsmi_processor_handle, amdsmi_voltage_type_t, amdsmi_voltage_metric_t, ctypes.POINTER(ctypes.c_int64)]
amdsmi_reset_gpu_fan = _libraries['libamd_smi.so'].amdsmi_reset_gpu_fan
amdsmi_reset_gpu_fan.restype = amdsmi_status_t
amdsmi_reset_gpu_fan.argtypes = [amdsmi_processor_handle, uint32_t]
amdsmi_set_gpu_fan_speed = _libraries['libamd_smi.so'].amdsmi_set_gpu_fan_speed
amdsmi_set_gpu_fan_speed.restype = amdsmi_status_t
amdsmi_set_gpu_fan_speed.argtypes = [amdsmi_processor_handle, uint32_t, uint64_t]
amdsmi_get_gpu_busy_percent = _libraries['libamd_smi.so'].amdsmi_get_gpu_busy_percent
amdsmi_get_gpu_busy_percent.restype = amdsmi_status_t
amdsmi_get_gpu_busy_percent.argtypes = [amdsmi_processor_handle, ctypes.POINTER(ctypes.c_uint32)]
amdsmi_get_utilization_count = _libraries['libamd_smi.so'].amdsmi_get_utilization_count
amdsmi_get_utilization_count.restype = amdsmi_status_t
amdsmi_get_utilization_count.argtypes = [amdsmi_processor_handle, ctypes.POINTER(struct_amdsmi_utilization_counter_t), uint32_t, ctypes.POINTER(ctypes.c_uint64)]
amdsmi_get_gpu_perf_level = _libraries['libamd_smi.so'].amdsmi_get_gpu_perf_level
amdsmi_get_gpu_perf_level.restype = amdsmi_status_t
amdsmi_get_gpu_perf_level.argtypes = [amdsmi_processor_handle, ctypes.POINTER(amdsmi_dev_perf_level_t)]
amdsmi_set_gpu_perf_determinism_mode = _libraries['libamd_smi.so'].amdsmi_set_gpu_perf_determinism_mode
amdsmi_set_gpu_perf_determinism_mode.restype = amdsmi_status_t
amdsmi_set_gpu_perf_determinism_mode.argtypes = [amdsmi_processor_handle, uint64_t]
amdsmi_get_gpu_overdrive_level = _libraries['libamd_smi.so'].amdsmi_get_gpu_overdrive_level
amdsmi_get_gpu_overdrive_level.restype = amdsmi_status_t
amdsmi_get_gpu_overdrive_level.argtypes = [amdsmi_processor_handle, ctypes.POINTER(ctypes.c_uint32)]
amdsmi_get_gpu_mem_overdrive_level = _libraries['libamd_smi.so'].amdsmi_get_gpu_mem_overdrive_level
amdsmi_get_gpu_mem_overdrive_level.restype = amdsmi_status_t
amdsmi_get_gpu_mem_overdrive_level.argtypes = [amdsmi_processor_handle, ctypes.POINTER(ctypes.c_uint32)]
amdsmi_get_clk_freq = _libraries['libamd_smi.so'].amdsmi_get_clk_freq
amdsmi_get_clk_freq.restype = amdsmi_status_t
amdsmi_get_clk_freq.argtypes = [amdsmi_processor_handle, amdsmi_clk_type_t, ctypes.POINTER(struct_amdsmi_frequencies_t)]
amdsmi_reset_gpu = _libraries['libamd_smi.so'].amdsmi_reset_gpu
amdsmi_reset_gpu.restype = amdsmi_status_t
amdsmi_reset_gpu.argtypes = [amdsmi_processor_handle]
amdsmi_get_gpu_od_volt_info = _libraries['libamd_smi.so'].amdsmi_get_gpu_od_volt_info
amdsmi_get_gpu_od_volt_info.restype = amdsmi_status_t
amdsmi_get_gpu_od_volt_info.argtypes = [amdsmi_processor_handle, ctypes.POINTER(struct_amdsmi_od_volt_freq_data_t)]
amdsmi_get_gpu_metrics_header_info = _libraries['libamd_smi.so'].amdsmi_get_gpu_metrics_header_info
amdsmi_get_gpu_metrics_header_info.restype = amdsmi_status_t
amdsmi_get_gpu_metrics_header_info.argtypes = [amdsmi_processor_handle, ctypes.POINTER(struct_amd_metrics_table_header_t)]
amdsmi_get_gpu_metrics_info = _libraries['libamd_smi.so'].amdsmi_get_gpu_metrics_info
amdsmi_get_gpu_metrics_info.restype = amdsmi_status_t
amdsmi_get_gpu_metrics_info.argtypes = [amdsmi_processor_handle, ctypes.POINTER(struct_amdsmi_gpu_metrics_t)]
amdsmi_get_gpu_pm_metrics_info = _libraries['libamd_smi.so'].amdsmi_get_gpu_pm_metrics_info
amdsmi_get_gpu_pm_metrics_info.restype = amdsmi_status_t
amdsmi_get_gpu_pm_metrics_info.argtypes = [amdsmi_processor_handle, ctypes.POINTER(ctypes.POINTER(struct_amdsmi_name_value_t)), ctypes.POINTER(ctypes.c_uint32)]
amdsmi_get_gpu_reg_table_info = _libraries['libamd_smi.so'].amdsmi_get_gpu_reg_table_info
amdsmi_get_gpu_reg_table_info.restype = amdsmi_status_t
amdsmi_get_gpu_reg_table_info.argtypes = [amdsmi_processor_handle, amdsmi_reg_type_t, ctypes.POINTER(ctypes.POINTER(struct_amdsmi_name_value_t)), ctypes.POINTER(ctypes.c_uint32)]
amdsmi_set_gpu_clk_range = _libraries['libamd_smi.so'].amdsmi_set_gpu_clk_range
amdsmi_set_gpu_clk_range.restype = amdsmi_status_t
amdsmi_set_gpu_clk_range.argtypes = [amdsmi_processor_handle, uint64_t, uint64_t, amdsmi_clk_type_t]
amdsmi_set_gpu_clk_limit = _libraries['libamd_smi.so'].amdsmi_set_gpu_clk_limit
amdsmi_set_gpu_clk_limit.restype = amdsmi_status_t
amdsmi_set_gpu_clk_limit.argtypes = [amdsmi_processor_handle, amdsmi_clk_type_t, amdsmi_clk_limit_type_t, uint64_t]
amdsmi_free_name_value_pairs = _libraries['libamd_smi.so'].amdsmi_free_name_value_pairs
amdsmi_free_name_value_pairs.restype = None
amdsmi_free_name_value_pairs.argtypes = [ctypes.POINTER(None)]
amdsmi_set_gpu_od_clk_info = _libraries['libamd_smi.so'].amdsmi_set_gpu_od_clk_info
amdsmi_set_gpu_od_clk_info.restype = amdsmi_status_t
amdsmi_set_gpu_od_clk_info.argtypes = [amdsmi_processor_handle, amdsmi_freq_ind_t, uint64_t, amdsmi_clk_type_t]
amdsmi_set_gpu_od_volt_info = _libraries['libamd_smi.so'].amdsmi_set_gpu_od_volt_info
amdsmi_set_gpu_od_volt_info.restype = amdsmi_status_t
amdsmi_set_gpu_od_volt_info.argtypes = [amdsmi_processor_handle, uint32_t, uint64_t, uint64_t]
amdsmi_get_gpu_od_volt_curve_regions = _libraries['libamd_smi.so'].amdsmi_get_gpu_od_volt_curve_regions
amdsmi_get_gpu_od_volt_curve_regions.restype = amdsmi_status_t
amdsmi_get_gpu_od_volt_curve_regions.argtypes = [amdsmi_processor_handle, ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(struct_amdsmi_freq_volt_region_t)]
amdsmi_get_gpu_power_profile_presets = _libraries['libamd_smi.so'].amdsmi_get_gpu_power_profile_presets
amdsmi_get_gpu_power_profile_presets.restype = amdsmi_status_t
amdsmi_get_gpu_power_profile_presets.argtypes = [amdsmi_processor_handle, uint32_t, ctypes.POINTER(struct_amdsmi_power_profile_status_t)]
amdsmi_set_gpu_perf_level = _libraries['libamd_smi.so'].amdsmi_set_gpu_perf_level
amdsmi_set_gpu_perf_level.restype = amdsmi_status_t
amdsmi_set_gpu_perf_level.argtypes = [amdsmi_processor_handle, amdsmi_dev_perf_level_t]
amdsmi_set_gpu_overdrive_level = _libraries['libamd_smi.so'].amdsmi_set_gpu_overdrive_level
amdsmi_set_gpu_overdrive_level.restype = amdsmi_status_t
amdsmi_set_gpu_overdrive_level.argtypes = [amdsmi_processor_handle, uint32_t]
amdsmi_set_clk_freq = _libraries['libamd_smi.so'].amdsmi_set_clk_freq
amdsmi_set_clk_freq.restype = amdsmi_status_t
amdsmi_set_clk_freq.argtypes = [amdsmi_processor_handle, amdsmi_clk_type_t, uint64_t]
amdsmi_get_soc_pstate = _libraries['libamd_smi.so'].amdsmi_get_soc_pstate
amdsmi_get_soc_pstate.restype = amdsmi_status_t
amdsmi_get_soc_pstate.argtypes = [amdsmi_processor_handle, ctypes.POINTER(struct_amdsmi_dpm_policy_t)]
amdsmi_set_soc_pstate = _libraries['libamd_smi.so'].amdsmi_set_soc_pstate
amdsmi_set_soc_pstate.restype = amdsmi_status_t
amdsmi_set_soc_pstate.argtypes = [amdsmi_processor_handle, uint32_t]
amdsmi_get_xgmi_plpd = _libraries['libamd_smi.so'].amdsmi_get_xgmi_plpd
amdsmi_get_xgmi_plpd.restype = amdsmi_status_t
amdsmi_get_xgmi_plpd.argtypes = [amdsmi_processor_handle, ctypes.POINTER(struct_amdsmi_dpm_policy_t)]
amdsmi_set_xgmi_plpd = _libraries['libamd_smi.so'].amdsmi_set_xgmi_plpd
amdsmi_set_xgmi_plpd.restype = amdsmi_status_t
amdsmi_set_xgmi_plpd.argtypes = [amdsmi_processor_handle, uint32_t]
amdsmi_get_gpu_process_isolation = _libraries['libamd_smi.so'].amdsmi_get_gpu_process_isolation
amdsmi_get_gpu_process_isolation.restype = amdsmi_status_t
amdsmi_get_gpu_process_isolation.argtypes = [amdsmi_processor_handle, ctypes.POINTER(ctypes.c_uint32)]
amdsmi_set_gpu_process_isolation = _libraries['libamd_smi.so'].amdsmi_set_gpu_process_isolation
amdsmi_set_gpu_process_isolation.restype = amdsmi_status_t
amdsmi_set_gpu_process_isolation.argtypes = [amdsmi_processor_handle, uint32_t]
amdsmi_clean_gpu_local_data = _libraries['libamd_smi.so'].amdsmi_clean_gpu_local_data
amdsmi_clean_gpu_local_data.restype = amdsmi_status_t
amdsmi_clean_gpu_local_data.argtypes = [amdsmi_processor_handle]
amdsmi_get_lib_version = _libraries['libamd_smi.so'].amdsmi_get_lib_version
amdsmi_get_lib_version.restype = amdsmi_status_t
amdsmi_get_lib_version.argtypes = [ctypes.POINTER(struct_amdsmi_version_t)]
amdsmi_get_gpu_ecc_count = _libraries['libamd_smi.so'].amdsmi_get_gpu_ecc_count
amdsmi_get_gpu_ecc_count.restype = amdsmi_status_t
amdsmi_get_gpu_ecc_count.argtypes = [amdsmi_processor_handle, amdsmi_gpu_block_t, ctypes.POINTER(struct_amdsmi_error_count_t)]
amdsmi_get_gpu_ecc_enabled = _libraries['libamd_smi.so'].amdsmi_get_gpu_ecc_enabled
amdsmi_get_gpu_ecc_enabled.restype = amdsmi_status_t
amdsmi_get_gpu_ecc_enabled.argtypes = [amdsmi_processor_handle, ctypes.POINTER(ctypes.c_uint64)]
amdsmi_get_gpu_total_ecc_count = _libraries['libamd_smi.so'].amdsmi_get_gpu_total_ecc_count
amdsmi_get_gpu_total_ecc_count.restype = amdsmi_status_t
amdsmi_get_gpu_total_ecc_count.argtypes = [amdsmi_processor_handle, ctypes.POINTER(struct_amdsmi_error_count_t)]
class struct_amdsmi_cper_guid_t(Structure):
    pass

struct_amdsmi_cper_guid_t._pack_ = 1 # source:False
struct_amdsmi_cper_guid_t._fields_ = [
    ('b', ctypes.c_ubyte * 16),
]

amdsmi_cper_guid_t = struct_amdsmi_cper_guid_t
class struct_amdsmi_cper_timestamp_t(Structure):
    pass

struct_amdsmi_cper_timestamp_t._pack_ = 1 # source:False
struct_amdsmi_cper_timestamp_t._fields_ = [
    ('seconds', ctypes.c_ubyte),
    ('minutes', ctypes.c_ubyte),
    ('hours', ctypes.c_ubyte),
    ('flag', ctypes.c_ubyte),
    ('day', ctypes.c_ubyte),
    ('month', ctypes.c_ubyte),
    ('year', ctypes.c_ubyte),
    ('century', ctypes.c_ubyte),
]

amdsmi_cper_timestamp_t = struct_amdsmi_cper_timestamp_t
class union_amdsmi_cper_valid_bits_t(Union):
    pass

class struct_valid_bits_(Structure):
    pass

struct_valid_bits_._pack_ = 1 # source:False
struct_valid_bits_._fields_ = [
    ('platform_id', ctypes.c_uint32, 1),
    ('timestamp', ctypes.c_uint32, 1),
    ('partition_id', ctypes.c_uint32, 1),
    ('reserved', ctypes.c_uint32, 29),
]

union_amdsmi_cper_valid_bits_t._pack_ = 1 # source:False
union_amdsmi_cper_valid_bits_t._fields_ = [
    ('valid_bits', struct_valid_bits_),
    ('valid_mask', ctypes.c_uint32),
]

amdsmi_cper_valid_bits_t = union_amdsmi_cper_valid_bits_t
class struct_amdsmi_cper_hdr_t(Structure):
    pass

struct_amdsmi_cper_hdr_t._pack_ = 1 # source:False
struct_amdsmi_cper_hdr_t._fields_ = [
    ('signature', ctypes.c_char * 4),
    ('revision', ctypes.c_uint16),
    ('signature_end', ctypes.c_uint32),
    ('sec_cnt', ctypes.c_uint16),
    ('error_severity', amdsmi_cper_sev_t),
    ('cper_valid_bits', amdsmi_cper_valid_bits_t),
    ('record_length', ctypes.c_uint32),
    ('timestamp', amdsmi_cper_timestamp_t),
    ('platform_id', ctypes.c_char * 16),
    ('partition_id', amdsmi_cper_guid_t),
    ('creator_id', ctypes.c_char * 16),
    ('notify_type', amdsmi_cper_guid_t),
    ('record_id', ctypes.c_char * 8),
    ('flags', ctypes.c_uint32),
    ('persistence_info', ctypes.c_uint64),
    ('reserved', ctypes.c_ubyte * 12),
]

amdsmi_cper_hdr_t = struct_amdsmi_cper_hdr_t
amdsmi_get_gpu_cper_entries = _libraries['libamd_smi.so'].amdsmi_get_gpu_cper_entries
amdsmi_get_gpu_cper_entries.restype = amdsmi_status_t
amdsmi_get_gpu_cper_entries.argtypes = [amdsmi_processor_handle, uint32_t, ctypes.POINTER(ctypes.c_char), ctypes.POINTER(ctypes.c_uint64), ctypes.POINTER(ctypes.POINTER(struct_amdsmi_cper_hdr_t)), ctypes.POINTER(ctypes.c_uint64), ctypes.POINTER(ctypes.c_uint64)]
amdsmi_get_afids_from_cper = _libraries['libamd_smi.so'].amdsmi_get_afids_from_cper
amdsmi_get_afids_from_cper.restype = amdsmi_status_t
amdsmi_get_afids_from_cper.argtypes = [ctypes.POINTER(ctypes.c_char), uint32_t, ctypes.POINTER(ctypes.c_uint64), ctypes.POINTER(ctypes.c_uint32)]
amdsmi_get_gpu_ecc_status = _libraries['libamd_smi.so'].amdsmi_get_gpu_ecc_status
amdsmi_get_gpu_ecc_status.restype = amdsmi_status_t
amdsmi_get_gpu_ecc_status.argtypes = [amdsmi_processor_handle, amdsmi_gpu_block_t, ctypes.POINTER(amdsmi_ras_err_state_t)]
amdsmi_status_code_to_string = _libraries['libamd_smi.so'].amdsmi_status_code_to_string
amdsmi_status_code_to_string.restype = amdsmi_status_t
amdsmi_status_code_to_string.argtypes = [amdsmi_status_t, ctypes.POINTER(ctypes.POINTER(ctypes.c_char))]
amdsmi_gpu_counter_group_supported = _libraries['libamd_smi.so'].amdsmi_gpu_counter_group_supported
amdsmi_gpu_counter_group_supported.restype = amdsmi_status_t
amdsmi_gpu_counter_group_supported.argtypes = [amdsmi_processor_handle, amdsmi_event_group_t]
amdsmi_gpu_create_counter = _libraries['libamd_smi.so'].amdsmi_gpu_create_counter
amdsmi_gpu_create_counter.restype = amdsmi_status_t
amdsmi_gpu_create_counter.argtypes = [amdsmi_processor_handle, amdsmi_event_type_t, ctypes.POINTER(ctypes.c_uint64)]
amdsmi_gpu_destroy_counter = _libraries['libamd_smi.so'].amdsmi_gpu_destroy_counter
amdsmi_gpu_destroy_counter.restype = amdsmi_status_t
amdsmi_gpu_destroy_counter.argtypes = [amdsmi_event_handle_t]
amdsmi_gpu_control_counter = _libraries['libamd_smi.so'].amdsmi_gpu_control_counter
amdsmi_gpu_control_counter.restype = amdsmi_status_t
amdsmi_gpu_control_counter.argtypes = [amdsmi_event_handle_t, amdsmi_counter_command_t, ctypes.POINTER(None)]
amdsmi_gpu_read_counter = _libraries['libamd_smi.so'].amdsmi_gpu_read_counter
amdsmi_gpu_read_counter.restype = amdsmi_status_t
amdsmi_gpu_read_counter.argtypes = [amdsmi_event_handle_t, ctypes.POINTER(struct_amdsmi_counter_value_t)]
amdsmi_get_gpu_available_counters = _libraries['libamd_smi.so'].amdsmi_get_gpu_available_counters
amdsmi_get_gpu_available_counters.restype = amdsmi_status_t
amdsmi_get_gpu_available_counters.argtypes = [amdsmi_processor_handle, amdsmi_event_group_t, ctypes.POINTER(ctypes.c_uint32)]
amdsmi_get_gpu_compute_process_info = _libraries['libamd_smi.so'].amdsmi_get_gpu_compute_process_info
amdsmi_get_gpu_compute_process_info.restype = amdsmi_status_t
amdsmi_get_gpu_compute_process_info.argtypes = [ctypes.POINTER(struct_amdsmi_process_info_t), ctypes.POINTER(ctypes.c_uint32)]
amdsmi_get_gpu_compute_process_info_by_pid = _libraries['libamd_smi.so'].amdsmi_get_gpu_compute_process_info_by_pid
amdsmi_get_gpu_compute_process_info_by_pid.restype = amdsmi_status_t
amdsmi_get_gpu_compute_process_info_by_pid.argtypes = [uint32_t, ctypes.POINTER(struct_amdsmi_process_info_t)]
amdsmi_get_gpu_compute_process_gpus = _libraries['libamd_smi.so'].amdsmi_get_gpu_compute_process_gpus
amdsmi_get_gpu_compute_process_gpus.restype = amdsmi_status_t
amdsmi_get_gpu_compute_process_gpus.argtypes = [uint32_t, ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_uint32)]
amdsmi_gpu_xgmi_error_status = _libraries['libamd_smi.so'].amdsmi_gpu_xgmi_error_status
amdsmi_gpu_xgmi_error_status.restype = amdsmi_status_t
amdsmi_gpu_xgmi_error_status.argtypes = [amdsmi_processor_handle, ctypes.POINTER(amdsmi_xgmi_status_t)]
amdsmi_reset_gpu_xgmi_error = _libraries['libamd_smi.so'].amdsmi_reset_gpu_xgmi_error
amdsmi_reset_gpu_xgmi_error.restype = amdsmi_status_t
amdsmi_reset_gpu_xgmi_error.argtypes = [amdsmi_processor_handle]
amdsmi_get_xgmi_info = _libraries['libamd_smi.so'].amdsmi_get_xgmi_info
amdsmi_get_xgmi_info.restype = amdsmi_status_t
amdsmi_get_xgmi_info.argtypes = [amdsmi_processor_handle, ctypes.POINTER(struct_amdsmi_xgmi_info_t)]
amdsmi_get_gpu_xgmi_link_status = _libraries['libamd_smi.so'].amdsmi_get_gpu_xgmi_link_status
amdsmi_get_gpu_xgmi_link_status.restype = amdsmi_status_t
amdsmi_get_gpu_xgmi_link_status.argtypes = [amdsmi_processor_handle, ctypes.POINTER(struct_amdsmi_xgmi_link_status_t)]
amdsmi_get_link_metrics = _libraries['libamd_smi.so'].amdsmi_get_link_metrics
amdsmi_get_link_metrics.restype = amdsmi_status_t
amdsmi_get_link_metrics.argtypes = [amdsmi_processor_handle, ctypes.POINTER(struct_amdsmi_link_metrics_t)]
amdsmi_topo_get_numa_node_number = _libraries['libamd_smi.so'].amdsmi_topo_get_numa_node_number
amdsmi_topo_get_numa_node_number.restype = amdsmi_status_t
amdsmi_topo_get_numa_node_number.argtypes = [amdsmi_processor_handle, ctypes.POINTER(ctypes.c_uint32)]
amdsmi_topo_get_link_weight = _libraries['libamd_smi.so'].amdsmi_topo_get_link_weight
amdsmi_topo_get_link_weight.restype = amdsmi_status_t
amdsmi_topo_get_link_weight.argtypes = [amdsmi_processor_handle, amdsmi_processor_handle, ctypes.POINTER(ctypes.c_uint64)]
amdsmi_get_minmax_bandwidth_between_processors = _libraries['libamd_smi.so'].amdsmi_get_minmax_bandwidth_between_processors
amdsmi_get_minmax_bandwidth_between_processors.restype = amdsmi_status_t
amdsmi_get_minmax_bandwidth_between_processors.argtypes = [amdsmi_processor_handle, amdsmi_processor_handle, ctypes.POINTER(ctypes.c_uint64), ctypes.POINTER(ctypes.c_uint64)]
amdsmi_topo_get_link_type = _libraries['libamd_smi.so'].amdsmi_topo_get_link_type
amdsmi_topo_get_link_type.restype = amdsmi_status_t
amdsmi_topo_get_link_type.argtypes = [amdsmi_processor_handle, amdsmi_processor_handle, ctypes.POINTER(ctypes.c_uint64), ctypes.POINTER(amdsmi_io_link_type_t)]
amdsmi_get_link_topology_nearest = _libraries['libamd_smi.so'].amdsmi_get_link_topology_nearest
amdsmi_get_link_topology_nearest.restype = amdsmi_status_t
amdsmi_get_link_topology_nearest.argtypes = [amdsmi_processor_handle, amdsmi_link_type_t, ctypes.POINTER(struct_amdsmi_topology_nearest_t)]
amdsmi_is_P2P_accessible = _libraries['libamd_smi.so'].amdsmi_is_P2P_accessible
amdsmi_is_P2P_accessible.restype = amdsmi_status_t
amdsmi_is_P2P_accessible.argtypes = [amdsmi_processor_handle, amdsmi_processor_handle, ctypes.POINTER(ctypes.c_bool)]
amdsmi_topo_get_p2p_status = _libraries['libamd_smi.so'].amdsmi_topo_get_p2p_status
amdsmi_topo_get_p2p_status.restype = amdsmi_status_t
amdsmi_topo_get_p2p_status.argtypes = [amdsmi_processor_handle, amdsmi_processor_handle, ctypes.POINTER(amdsmi_io_link_type_t), ctypes.POINTER(struct_amdsmi_p2p_capability_t)]
amdsmi_get_gpu_compute_partition = _libraries['libamd_smi.so'].amdsmi_get_gpu_compute_partition
amdsmi_get_gpu_compute_partition.restype = amdsmi_status_t
amdsmi_get_gpu_compute_partition.argtypes = [amdsmi_processor_handle, ctypes.POINTER(ctypes.c_char), uint32_t]
amdsmi_set_gpu_compute_partition = _libraries['libamd_smi.so'].amdsmi_set_gpu_compute_partition
amdsmi_set_gpu_compute_partition.restype = amdsmi_status_t
amdsmi_set_gpu_compute_partition.argtypes = [amdsmi_processor_handle, amdsmi_compute_partition_type_t]
amdsmi_get_gpu_memory_partition = _libraries['libamd_smi.so'].amdsmi_get_gpu_memory_partition
amdsmi_get_gpu_memory_partition.restype = amdsmi_status_t
amdsmi_get_gpu_memory_partition.argtypes = [amdsmi_processor_handle, ctypes.POINTER(ctypes.c_char), uint32_t]
amdsmi_set_gpu_memory_partition = _libraries['libamd_smi.so'].amdsmi_set_gpu_memory_partition
amdsmi_set_gpu_memory_partition.restype = amdsmi_status_t
amdsmi_set_gpu_memory_partition.argtypes = [amdsmi_processor_handle, amdsmi_memory_partition_type_t]
amdsmi_get_gpu_memory_partition_config = _libraries['libamd_smi.so'].amdsmi_get_gpu_memory_partition_config
amdsmi_get_gpu_memory_partition_config.restype = amdsmi_status_t
amdsmi_get_gpu_memory_partition_config.argtypes = [amdsmi_processor_handle, ctypes.POINTER(struct_amdsmi_memory_partition_config_t)]
amdsmi_set_gpu_memory_partition_mode = _libraries['libamd_smi.so'].amdsmi_set_gpu_memory_partition_mode
amdsmi_set_gpu_memory_partition_mode.restype = amdsmi_status_t
amdsmi_set_gpu_memory_partition_mode.argtypes = [amdsmi_processor_handle, amdsmi_memory_partition_type_t]
amdsmi_get_gpu_accelerator_partition_profile_config = _libraries['libamd_smi.so'].amdsmi_get_gpu_accelerator_partition_profile_config
amdsmi_get_gpu_accelerator_partition_profile_config.restype = amdsmi_status_t
amdsmi_get_gpu_accelerator_partition_profile_config.argtypes = [amdsmi_processor_handle, ctypes.POINTER(struct_amdsmi_accelerator_partition_profile_config_t)]
amdsmi_get_gpu_accelerator_partition_profile = _libraries['libamd_smi.so'].amdsmi_get_gpu_accelerator_partition_profile
amdsmi_get_gpu_accelerator_partition_profile.restype = amdsmi_status_t
amdsmi_get_gpu_accelerator_partition_profile.argtypes = [amdsmi_processor_handle, ctypes.POINTER(struct_amdsmi_accelerator_partition_profile_t), ctypes.POINTER(ctypes.c_uint32)]
amdsmi_set_gpu_accelerator_partition_profile = _libraries['libamd_smi.so'].amdsmi_set_gpu_accelerator_partition_profile
amdsmi_set_gpu_accelerator_partition_profile.restype = amdsmi_status_t
amdsmi_set_gpu_accelerator_partition_profile.argtypes = [amdsmi_processor_handle, uint32_t]
amdsmi_init_gpu_event_notification = _libraries['libamd_smi.so'].amdsmi_init_gpu_event_notification
amdsmi_init_gpu_event_notification.restype = amdsmi_status_t
amdsmi_init_gpu_event_notification.argtypes = [amdsmi_processor_handle]
amdsmi_set_gpu_event_notification_mask = _libraries['libamd_smi.so'].amdsmi_set_gpu_event_notification_mask
amdsmi_set_gpu_event_notification_mask.restype = amdsmi_status_t
amdsmi_set_gpu_event_notification_mask.argtypes = [amdsmi_processor_handle, uint64_t]
amdsmi_get_gpu_event_notification = _libraries['libamd_smi.so'].amdsmi_get_gpu_event_notification
amdsmi_get_gpu_event_notification.restype = amdsmi_status_t
amdsmi_get_gpu_event_notification.argtypes = [ctypes.c_int32, ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(struct_amdsmi_evt_notification_data_t)]
amdsmi_stop_gpu_event_notification = _libraries['libamd_smi.so'].amdsmi_stop_gpu_event_notification
amdsmi_stop_gpu_event_notification.restype = amdsmi_status_t
amdsmi_stop_gpu_event_notification.argtypes = [amdsmi_processor_handle]
amdsmi_get_gpu_driver_info = _libraries['libamd_smi.so'].amdsmi_get_gpu_driver_info
amdsmi_get_gpu_driver_info.restype = amdsmi_status_t
amdsmi_get_gpu_driver_info.argtypes = [amdsmi_processor_handle, ctypes.POINTER(struct_amdsmi_driver_info_t)]
amdsmi_get_gpu_asic_info = _libraries['libamd_smi.so'].amdsmi_get_gpu_asic_info
amdsmi_get_gpu_asic_info.restype = amdsmi_status_t
amdsmi_get_gpu_asic_info.argtypes = [amdsmi_processor_handle, ctypes.POINTER(struct_amdsmi_asic_info_t)]
amdsmi_get_gpu_kfd_info = _libraries['libamd_smi.so'].amdsmi_get_gpu_kfd_info
amdsmi_get_gpu_kfd_info.restype = amdsmi_status_t
amdsmi_get_gpu_kfd_info.argtypes = [amdsmi_processor_handle, ctypes.POINTER(struct_amdsmi_kfd_info_t)]
amdsmi_get_gpu_vram_info = _libraries['libamd_smi.so'].amdsmi_get_gpu_vram_info
amdsmi_get_gpu_vram_info.restype = amdsmi_status_t
amdsmi_get_gpu_vram_info.argtypes = [amdsmi_processor_handle, ctypes.POINTER(struct_amdsmi_vram_info_t)]
amdsmi_get_gpu_board_info = _libraries['libamd_smi.so'].amdsmi_get_gpu_board_info
amdsmi_get_gpu_board_info.restype = amdsmi_status_t
amdsmi_get_gpu_board_info.argtypes = [amdsmi_processor_handle, ctypes.POINTER(struct_amdsmi_board_info_t)]
amdsmi_get_power_cap_info = _libraries['libamd_smi.so'].amdsmi_get_power_cap_info
amdsmi_get_power_cap_info.restype = amdsmi_status_t
amdsmi_get_power_cap_info.argtypes = [amdsmi_processor_handle, uint32_t, ctypes.POINTER(struct_amdsmi_power_cap_info_t)]
amdsmi_get_pcie_info = _libraries['libamd_smi.so'].amdsmi_get_pcie_info
amdsmi_get_pcie_info.restype = amdsmi_status_t
amdsmi_get_pcie_info.argtypes = [amdsmi_processor_handle, ctypes.POINTER(struct_amdsmi_pcie_info_t)]
amdsmi_get_gpu_xcd_counter = _libraries['libamd_smi.so'].amdsmi_get_gpu_xcd_counter
amdsmi_get_gpu_xcd_counter.restype = amdsmi_status_t
amdsmi_get_gpu_xcd_counter.argtypes = [amdsmi_processor_handle, ctypes.POINTER(ctypes.c_uint16)]
amdsmi_get_fw_info = _libraries['libamd_smi.so'].amdsmi_get_fw_info
amdsmi_get_fw_info.restype = amdsmi_status_t
amdsmi_get_fw_info.argtypes = [amdsmi_processor_handle, ctypes.POINTER(struct_amdsmi_fw_info_t)]
amdsmi_get_gpu_vbios_info = _libraries['libamd_smi.so'].amdsmi_get_gpu_vbios_info
amdsmi_get_gpu_vbios_info.restype = amdsmi_status_t
amdsmi_get_gpu_vbios_info.argtypes = [amdsmi_processor_handle, ctypes.POINTER(struct_amdsmi_vbios_info_t)]
amdsmi_get_gpu_activity = _libraries['libamd_smi.so'].amdsmi_get_gpu_activity
amdsmi_get_gpu_activity.restype = amdsmi_status_t
amdsmi_get_gpu_activity.argtypes = [amdsmi_processor_handle, ctypes.POINTER(struct_amdsmi_engine_usage_t)]
amdsmi_get_power_info_v2 = _libraries['libamd_smi.so'].amdsmi_get_power_info_v2
amdsmi_get_power_info_v2.restype = amdsmi_status_t
amdsmi_get_power_info_v2.argtypes = [amdsmi_processor_handle, uint32_t, ctypes.POINTER(struct_amdsmi_power_info_t)]
amdsmi_get_power_info = _libraries['libamd_smi.so'].amdsmi_get_power_info
amdsmi_get_power_info.restype = amdsmi_status_t
amdsmi_get_power_info.argtypes = [amdsmi_processor_handle, ctypes.POINTER(struct_amdsmi_power_info_t)]
amdsmi_is_gpu_power_management_enabled = _libraries['libamd_smi.so'].amdsmi_is_gpu_power_management_enabled
amdsmi_is_gpu_power_management_enabled.restype = amdsmi_status_t
amdsmi_is_gpu_power_management_enabled.argtypes = [amdsmi_processor_handle, ctypes.POINTER(ctypes.c_bool)]
amdsmi_get_clock_info = _libraries['libamd_smi.so'].amdsmi_get_clock_info
amdsmi_get_clock_info.restype = amdsmi_status_t
amdsmi_get_clock_info.argtypes = [amdsmi_processor_handle, amdsmi_clk_type_t, ctypes.POINTER(struct_amdsmi_clk_info_t)]
amdsmi_get_gpu_vram_usage = _libraries['libamd_smi.so'].amdsmi_get_gpu_vram_usage
amdsmi_get_gpu_vram_usage.restype = amdsmi_status_t
amdsmi_get_gpu_vram_usage.argtypes = [amdsmi_processor_handle, ctypes.POINTER(struct_amdsmi_vram_usage_t)]
amdsmi_get_violation_status = _libraries['libamd_smi.so'].amdsmi_get_violation_status
amdsmi_get_violation_status.restype = amdsmi_status_t
amdsmi_get_violation_status.argtypes = [amdsmi_processor_handle, ctypes.POINTER(struct_amdsmi_violation_status_t)]
amdsmi_get_gpu_process_list = _libraries['libamd_smi.so'].amdsmi_get_gpu_process_list
amdsmi_get_gpu_process_list.restype = amdsmi_status_t
amdsmi_get_gpu_process_list.argtypes = [amdsmi_processor_handle, ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(struct_amdsmi_proc_info_t)]
amdsmi_get_cpu_core_energy = _libraries['libamd_smi.so'].amdsmi_get_cpu_core_energy
amdsmi_get_cpu_core_energy.restype = amdsmi_status_t
amdsmi_get_cpu_core_energy.argtypes = [amdsmi_processor_handle, ctypes.POINTER(ctypes.c_uint64)]
amdsmi_get_cpu_socket_energy = _libraries['libamd_smi.so'].amdsmi_get_cpu_socket_energy
amdsmi_get_cpu_socket_energy.restype = amdsmi_status_t
amdsmi_get_cpu_socket_energy.argtypes = [amdsmi_processor_handle, ctypes.POINTER(ctypes.c_uint64)]
amdsmi_get_threads_per_core = _libraries['libamd_smi.so'].amdsmi_get_threads_per_core
amdsmi_get_threads_per_core.restype = amdsmi_status_t
amdsmi_get_threads_per_core.argtypes = [ctypes.POINTER(ctypes.c_uint32)]
amdsmi_get_cpu_hsmp_driver_version = _libraries['libamd_smi.so'].amdsmi_get_cpu_hsmp_driver_version
amdsmi_get_cpu_hsmp_driver_version.restype = amdsmi_status_t
amdsmi_get_cpu_hsmp_driver_version.argtypes = [amdsmi_processor_handle, ctypes.POINTER(struct_amdsmi_hsmp_driver_version_t)]
amdsmi_get_cpu_smu_fw_version = _libraries['libamd_smi.so'].amdsmi_get_cpu_smu_fw_version
amdsmi_get_cpu_smu_fw_version.restype = amdsmi_status_t
amdsmi_get_cpu_smu_fw_version.argtypes = [amdsmi_processor_handle, ctypes.POINTER(struct_amdsmi_smu_fw_version_t)]
amdsmi_get_cpu_hsmp_proto_ver = _libraries['libamd_smi.so'].amdsmi_get_cpu_hsmp_proto_ver
amdsmi_get_cpu_hsmp_proto_ver.restype = amdsmi_status_t
amdsmi_get_cpu_hsmp_proto_ver.argtypes = [amdsmi_processor_handle, ctypes.POINTER(ctypes.c_uint32)]
amdsmi_get_cpu_prochot_status = _libraries['libamd_smi.so'].amdsmi_get_cpu_prochot_status
amdsmi_get_cpu_prochot_status.restype = amdsmi_status_t
amdsmi_get_cpu_prochot_status.argtypes = [amdsmi_processor_handle, ctypes.POINTER(ctypes.c_uint32)]
amdsmi_get_cpu_fclk_mclk = _libraries['libamd_smi.so'].amdsmi_get_cpu_fclk_mclk
amdsmi_get_cpu_fclk_mclk.restype = amdsmi_status_t
amdsmi_get_cpu_fclk_mclk.argtypes = [amdsmi_processor_handle, ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_uint32)]
amdsmi_get_cpu_cclk_limit = _libraries['libamd_smi.so'].amdsmi_get_cpu_cclk_limit
amdsmi_get_cpu_cclk_limit.restype = amdsmi_status_t
amdsmi_get_cpu_cclk_limit.argtypes = [amdsmi_processor_handle, ctypes.POINTER(ctypes.c_uint32)]
amdsmi_get_cpu_socket_current_active_freq_limit = _libraries['libamd_smi.so'].amdsmi_get_cpu_socket_current_active_freq_limit
amdsmi_get_cpu_socket_current_active_freq_limit.restype = amdsmi_status_t
amdsmi_get_cpu_socket_current_active_freq_limit.argtypes = [amdsmi_processor_handle, ctypes.POINTER(ctypes.c_uint16), ctypes.POINTER(ctypes.POINTER(ctypes.c_char))]
amdsmi_get_cpu_socket_freq_range = _libraries['libamd_smi.so'].amdsmi_get_cpu_socket_freq_range
amdsmi_get_cpu_socket_freq_range.restype = amdsmi_status_t
amdsmi_get_cpu_socket_freq_range.argtypes = [amdsmi_processor_handle, ctypes.POINTER(ctypes.c_uint16), ctypes.POINTER(ctypes.c_uint16)]
amdsmi_get_cpu_core_current_freq_limit = _libraries['libamd_smi.so'].amdsmi_get_cpu_core_current_freq_limit
amdsmi_get_cpu_core_current_freq_limit.restype = amdsmi_status_t
amdsmi_get_cpu_core_current_freq_limit.argtypes = [amdsmi_processor_handle, ctypes.POINTER(ctypes.c_uint32)]
amdsmi_get_cpu_core_boostlimit = _libraries['libamd_smi.so'].amdsmi_get_cpu_core_boostlimit
amdsmi_get_cpu_core_boostlimit.restype = amdsmi_status_t
amdsmi_get_cpu_core_boostlimit.argtypes = [amdsmi_processor_handle, ctypes.POINTER(ctypes.c_uint32)]
amdsmi_get_cpu_socket_c0_residency = _libraries['libamd_smi.so'].amdsmi_get_cpu_socket_c0_residency
amdsmi_get_cpu_socket_c0_residency.restype = amdsmi_status_t
amdsmi_get_cpu_socket_c0_residency.argtypes = [amdsmi_processor_handle, ctypes.POINTER(ctypes.c_uint32)]
amdsmi_set_cpu_core_boostlimit = _libraries['libamd_smi.so'].amdsmi_set_cpu_core_boostlimit
amdsmi_set_cpu_core_boostlimit.restype = amdsmi_status_t
amdsmi_set_cpu_core_boostlimit.argtypes = [amdsmi_processor_handle, uint32_t]
amdsmi_set_cpu_socket_boostlimit = _libraries['libamd_smi.so'].amdsmi_set_cpu_socket_boostlimit
amdsmi_set_cpu_socket_boostlimit.restype = amdsmi_status_t
amdsmi_set_cpu_socket_boostlimit.argtypes = [amdsmi_processor_handle, uint32_t]
amdsmi_get_cpu_ddr_bw = _libraries['libamd_smi.so'].amdsmi_get_cpu_ddr_bw
amdsmi_get_cpu_ddr_bw.restype = amdsmi_status_t
amdsmi_get_cpu_ddr_bw.argtypes = [amdsmi_processor_handle, ctypes.POINTER(struct_amdsmi_ddr_bw_metrics_t)]
amdsmi_get_cpu_socket_temperature = _libraries['libamd_smi.so'].amdsmi_get_cpu_socket_temperature
amdsmi_get_cpu_socket_temperature.restype = amdsmi_status_t
amdsmi_get_cpu_socket_temperature.argtypes = [amdsmi_processor_handle, ctypes.POINTER(ctypes.c_uint32)]
amdsmi_get_cpu_dimm_temp_range_and_refresh_rate = _libraries['libamd_smi.so'].amdsmi_get_cpu_dimm_temp_range_and_refresh_rate
amdsmi_get_cpu_dimm_temp_range_and_refresh_rate.restype = amdsmi_status_t
amdsmi_get_cpu_dimm_temp_range_and_refresh_rate.argtypes = [amdsmi_processor_handle, uint8_t, ctypes.POINTER(struct_amdsmi_temp_range_refresh_rate_t)]
amdsmi_get_cpu_dimm_power_consumption = _libraries['libamd_smi.so'].amdsmi_get_cpu_dimm_power_consumption
amdsmi_get_cpu_dimm_power_consumption.restype = amdsmi_status_t
amdsmi_get_cpu_dimm_power_consumption.argtypes = [amdsmi_processor_handle, uint8_t, ctypes.POINTER(struct_amdsmi_dimm_power_t)]
amdsmi_get_cpu_dimm_thermal_sensor = _libraries['libamd_smi.so'].amdsmi_get_cpu_dimm_thermal_sensor
amdsmi_get_cpu_dimm_thermal_sensor.restype = amdsmi_status_t
amdsmi_get_cpu_dimm_thermal_sensor.argtypes = [amdsmi_processor_handle, uint8_t, ctypes.POINTER(struct_amdsmi_dimm_thermal_t)]
amdsmi_set_cpu_xgmi_width = _libraries['libamd_smi.so'].amdsmi_set_cpu_xgmi_width
amdsmi_set_cpu_xgmi_width.restype = amdsmi_status_t
amdsmi_set_cpu_xgmi_width.argtypes = [amdsmi_processor_handle, uint8_t, uint8_t]
amdsmi_set_cpu_gmi3_link_width_range = _libraries['libamd_smi.so'].amdsmi_set_cpu_gmi3_link_width_range
amdsmi_set_cpu_gmi3_link_width_range.restype = amdsmi_status_t
amdsmi_set_cpu_gmi3_link_width_range.argtypes = [amdsmi_processor_handle, uint8_t, uint8_t]
amdsmi_cpu_apb_enable = _libraries['libamd_smi.so'].amdsmi_cpu_apb_enable
amdsmi_cpu_apb_enable.restype = amdsmi_status_t
amdsmi_cpu_apb_enable.argtypes = [amdsmi_processor_handle]
amdsmi_cpu_apb_disable = _libraries['libamd_smi.so'].amdsmi_cpu_apb_disable
amdsmi_cpu_apb_disable.restype = amdsmi_status_t
amdsmi_cpu_apb_disable.argtypes = [amdsmi_processor_handle, uint8_t]
amdsmi_set_cpu_socket_lclk_dpm_level = _libraries['libamd_smi.so'].amdsmi_set_cpu_socket_lclk_dpm_level
amdsmi_set_cpu_socket_lclk_dpm_level.restype = amdsmi_status_t
amdsmi_set_cpu_socket_lclk_dpm_level.argtypes = [amdsmi_processor_handle, uint8_t, uint8_t, uint8_t]
amdsmi_get_cpu_socket_lclk_dpm_level = _libraries['libamd_smi.so'].amdsmi_get_cpu_socket_lclk_dpm_level
amdsmi_get_cpu_socket_lclk_dpm_level.restype = amdsmi_status_t
amdsmi_get_cpu_socket_lclk_dpm_level.argtypes = [amdsmi_processor_handle, uint8_t, ctypes.POINTER(struct_amdsmi_dpm_level_t)]
amdsmi_set_cpu_pcie_link_rate = _libraries['libamd_smi.so'].amdsmi_set_cpu_pcie_link_rate
amdsmi_set_cpu_pcie_link_rate.restype = amdsmi_status_t
amdsmi_set_cpu_pcie_link_rate.argtypes = [amdsmi_processor_handle, uint8_t, ctypes.POINTER(ctypes.c_ubyte)]
amdsmi_set_cpu_df_pstate_range = _libraries['libamd_smi.so'].amdsmi_set_cpu_df_pstate_range
amdsmi_set_cpu_df_pstate_range.restype = amdsmi_status_t
amdsmi_set_cpu_df_pstate_range.argtypes = [amdsmi_processor_handle, uint8_t, uint8_t]
amdsmi_get_cpu_current_io_bandwidth = _libraries['libamd_smi.so'].amdsmi_get_cpu_current_io_bandwidth
amdsmi_get_cpu_current_io_bandwidth.restype = amdsmi_status_t
amdsmi_get_cpu_current_io_bandwidth.argtypes = [amdsmi_processor_handle, amdsmi_link_id_bw_type_t, ctypes.POINTER(ctypes.c_uint32)]
amdsmi_get_cpu_current_xgmi_bw = _libraries['libamd_smi.so'].amdsmi_get_cpu_current_xgmi_bw
amdsmi_get_cpu_current_xgmi_bw.restype = amdsmi_status_t
amdsmi_get_cpu_current_xgmi_bw.argtypes = [amdsmi_processor_handle, amdsmi_link_id_bw_type_t, ctypes.POINTER(ctypes.c_uint32)]
amdsmi_get_hsmp_metrics_table_version = _libraries['libamd_smi.so'].amdsmi_get_hsmp_metrics_table_version
amdsmi_get_hsmp_metrics_table_version.restype = amdsmi_status_t
amdsmi_get_hsmp_metrics_table_version.argtypes = [amdsmi_processor_handle, ctypes.POINTER(ctypes.c_uint32)]
amdsmi_get_hsmp_metrics_table = _libraries['libamd_smi.so'].amdsmi_get_hsmp_metrics_table
amdsmi_get_hsmp_metrics_table.restype = amdsmi_status_t
amdsmi_get_hsmp_metrics_table.argtypes = [amdsmi_processor_handle, ctypes.POINTER(struct_amdsmi_hsmp_metrics_table_t)]
amdsmi_first_online_core_on_cpu_socket = _libraries['libamd_smi.so'].amdsmi_first_online_core_on_cpu_socket
amdsmi_first_online_core_on_cpu_socket.restype = amdsmi_status_t
amdsmi_first_online_core_on_cpu_socket.argtypes = [amdsmi_processor_handle, ctypes.POINTER(ctypes.c_uint32)]
amdsmi_get_cpu_family = _libraries['libamd_smi.so'].amdsmi_get_cpu_family
amdsmi_get_cpu_family.restype = amdsmi_status_t
amdsmi_get_cpu_family.argtypes = [ctypes.POINTER(ctypes.c_uint32)]
amdsmi_get_cpu_model = _libraries['libamd_smi.so'].amdsmi_get_cpu_model
amdsmi_get_cpu_model.restype = amdsmi_status_t
amdsmi_get_cpu_model.argtypes = [ctypes.POINTER(ctypes.c_uint32)]
amdsmi_get_esmi_err_msg = _libraries['libamd_smi.so'].amdsmi_get_esmi_err_msg
amdsmi_get_esmi_err_msg.restype = amdsmi_status_t
amdsmi_get_esmi_err_msg.argtypes = [amdsmi_status_t, ctypes.POINTER(ctypes.POINTER(ctypes.c_char))]
__all__ = \
    ['AGG_BW0', 'AMDSMI_ACCELERATOR_DECODER',
    'AMDSMI_ACCELERATOR_DMA', 'AMDSMI_ACCELERATOR_ENCODER',
    'AMDSMI_ACCELERATOR_JPEG', 'AMDSMI_ACCELERATOR_MAX',
    'AMDSMI_ACCELERATOR_PARTITION_CPX',
    'AMDSMI_ACCELERATOR_PARTITION_DPX',
    'AMDSMI_ACCELERATOR_PARTITION_INVALID',
    'AMDSMI_ACCELERATOR_PARTITION_MAX',
    'AMDSMI_ACCELERATOR_PARTITION_QPX',
    'AMDSMI_ACCELERATOR_PARTITION_SPX',
    'AMDSMI_ACCELERATOR_PARTITION_TPX', 'AMDSMI_ACCELERATOR_XCC',
    'AMDSMI_CACHE_PROPERTY_CPU_CACHE',
    'AMDSMI_CACHE_PROPERTY_DATA_CACHE',
    'AMDSMI_CACHE_PROPERTY_ENABLED',
    'AMDSMI_CACHE_PROPERTY_INST_CACHE',
    'AMDSMI_CACHE_PROPERTY_SIMD_CACHE', 'AMDSMI_CARD_FORM_FACTOR_CEM',
    'AMDSMI_CARD_FORM_FACTOR_OAM', 'AMDSMI_CARD_FORM_FACTOR_PCIE',
    'AMDSMI_CARD_FORM_FACTOR_UNKNOWN', 'AMDSMI_CLK_TYPE_DCEF',
    'AMDSMI_CLK_TYPE_DCLK0', 'AMDSMI_CLK_TYPE_DCLK1',
    'AMDSMI_CLK_TYPE_DF', 'AMDSMI_CLK_TYPE_FIRST',
    'AMDSMI_CLK_TYPE_GFX', 'AMDSMI_CLK_TYPE_MEM',
    'AMDSMI_CLK_TYPE_PCIE', 'AMDSMI_CLK_TYPE_SOC',
    'AMDSMI_CLK_TYPE_SYS', 'AMDSMI_CLK_TYPE_VCLK0',
    'AMDSMI_CLK_TYPE_VCLK1', 'AMDSMI_CLK_TYPE__MAX',
    'AMDSMI_CNTR_CMD_START', 'AMDSMI_CNTR_CMD_STOP',
    'AMDSMI_COARSE_DECODER_ACTIVITY',
    'AMDSMI_COARSE_GRAIN_GFX_ACTIVITY',
    'AMDSMI_COARSE_GRAIN_MEM_ACTIVITY',
    'AMDSMI_COMPUTE_PARTITION_CPX', 'AMDSMI_COMPUTE_PARTITION_DPX',
    'AMDSMI_COMPUTE_PARTITION_INVALID',
    'AMDSMI_COMPUTE_PARTITION_QPX', 'AMDSMI_COMPUTE_PARTITION_SPX',
    'AMDSMI_COMPUTE_PARTITION_TPX', 'AMDSMI_CONTAINER_DOCKER',
    'AMDSMI_CONTAINER_LXC', 'AMDSMI_CPER_NOTIFY_TYPE_BOOT',
    'AMDSMI_CPER_NOTIFY_TYPE_CMC', 'AMDSMI_CPER_NOTIFY_TYPE_CPE',
    'AMDSMI_CPER_NOTIFY_TYPE_CXL_COMPONENT',
    'AMDSMI_CPER_NOTIFY_TYPE_DMAR', 'AMDSMI_CPER_NOTIFY_TYPE_INIT',
    'AMDSMI_CPER_NOTIFY_TYPE_MCE', 'AMDSMI_CPER_NOTIFY_TYPE_NMI',
    'AMDSMI_CPER_NOTIFY_TYPE_PCIE', 'AMDSMI_CPER_NOTIFY_TYPE_PEI',
    'AMDSMI_CPER_NOTIFY_TYPE_SEA', 'AMDSMI_CPER_NOTIFY_TYPE_SEI',
    'AMDSMI_CPER_SEV_FATAL', 'AMDSMI_CPER_SEV_NON_FATAL_CORRECTED',
    'AMDSMI_CPER_SEV_NON_FATAL_UNCORRECTED', 'AMDSMI_CPER_SEV_NUM',
    'AMDSMI_CPER_SEV_UNUSED', 'AMDSMI_DEV_PERF_LEVEL_AUTO',
    'AMDSMI_DEV_PERF_LEVEL_DETERMINISM',
    'AMDSMI_DEV_PERF_LEVEL_FIRST', 'AMDSMI_DEV_PERF_LEVEL_HIGH',
    'AMDSMI_DEV_PERF_LEVEL_LAST', 'AMDSMI_DEV_PERF_LEVEL_LOW',
    'AMDSMI_DEV_PERF_LEVEL_MANUAL',
    'AMDSMI_DEV_PERF_LEVEL_STABLE_MIN_MCLK',
    'AMDSMI_DEV_PERF_LEVEL_STABLE_MIN_SCLK',
    'AMDSMI_DEV_PERF_LEVEL_STABLE_PEAK',
    'AMDSMI_DEV_PERF_LEVEL_STABLE_STD',
    'AMDSMI_DEV_PERF_LEVEL_UNKNOWN', 'AMDSMI_EVNT_FIRST',
    'AMDSMI_EVNT_GRP_INVALID', 'AMDSMI_EVNT_GRP_XGMI',
    'AMDSMI_EVNT_GRP_XGMI_DATA_OUT', 'AMDSMI_EVNT_LAST',
    'AMDSMI_EVNT_XGMI_0_BEATS_TX', 'AMDSMI_EVNT_XGMI_0_NOP_TX',
    'AMDSMI_EVNT_XGMI_0_REQUEST_TX', 'AMDSMI_EVNT_XGMI_0_RESPONSE_TX',
    'AMDSMI_EVNT_XGMI_1_BEATS_TX', 'AMDSMI_EVNT_XGMI_1_NOP_TX',
    'AMDSMI_EVNT_XGMI_1_REQUEST_TX', 'AMDSMI_EVNT_XGMI_1_RESPONSE_TX',
    'AMDSMI_EVNT_XGMI_DATA_OUT_0', 'AMDSMI_EVNT_XGMI_DATA_OUT_1',
    'AMDSMI_EVNT_XGMI_DATA_OUT_2', 'AMDSMI_EVNT_XGMI_DATA_OUT_3',
    'AMDSMI_EVNT_XGMI_DATA_OUT_4', 'AMDSMI_EVNT_XGMI_DATA_OUT_5',
    'AMDSMI_EVNT_XGMI_DATA_OUT_FIRST',
    'AMDSMI_EVNT_XGMI_DATA_OUT_LAST', 'AMDSMI_EVNT_XGMI_FIRST',
    'AMDSMI_EVNT_XGMI_LAST', 'AMDSMI_EVT_NOTIF_FIRST',
    'AMDSMI_EVT_NOTIF_GPU_POST_RESET',
    'AMDSMI_EVT_NOTIF_GPU_PRE_RESET', 'AMDSMI_EVT_NOTIF_LAST',
    'AMDSMI_EVT_NOTIF_NONE', 'AMDSMI_EVT_NOTIF_RING_HANG',
    'AMDSMI_EVT_NOTIF_THERMAL_THROTTLE', 'AMDSMI_EVT_NOTIF_VMFAULT',
    'AMDSMI_FINE_DECODER_ACTIVITY', 'AMDSMI_FINE_GRAIN_GFX_ACTIVITY',
    'AMDSMI_FINE_GRAIN_MEM_ACTIVITY', 'AMDSMI_FREQ_IND_INVALID',
    'AMDSMI_FREQ_IND_MAX', 'AMDSMI_FREQ_IND_MIN', 'AMDSMI_FW_ID_ASD',
    'AMDSMI_FW_ID_CP_CE', 'AMDSMI_FW_ID_CP_ME',
    'AMDSMI_FW_ID_CP_MEC1', 'AMDSMI_FW_ID_CP_MEC2',
    'AMDSMI_FW_ID_CP_MEC_JT1', 'AMDSMI_FW_ID_CP_MEC_JT2',
    'AMDSMI_FW_ID_CP_MES', 'AMDSMI_FW_ID_CP_PFP',
    'AMDSMI_FW_ID_CP_PM4', 'AMDSMI_FW_ID_DFC', 'AMDSMI_FW_ID_DMCU',
    'AMDSMI_FW_ID_DMCU_ERAM', 'AMDSMI_FW_ID_DMCU_ISR',
    'AMDSMI_FW_ID_DRV_CAP', 'AMDSMI_FW_ID_FIRST',
    'AMDSMI_FW_ID_IMU_DRAM', 'AMDSMI_FW_ID_IMU_IRAM',
    'AMDSMI_FW_ID_ISP', 'AMDSMI_FW_ID_MC', 'AMDSMI_FW_ID_MES_KIQ',
    'AMDSMI_FW_ID_MES_STACK', 'AMDSMI_FW_ID_MES_THREAD1',
    'AMDSMI_FW_ID_MES_THREAD1_STACK', 'AMDSMI_FW_ID_MMSCH',
    'AMDSMI_FW_ID_PLDM_BUNDLE', 'AMDSMI_FW_ID_PM',
    'AMDSMI_FW_ID_PPTABLE', 'AMDSMI_FW_ID_PSP_BL',
    'AMDSMI_FW_ID_PSP_DBG', 'AMDSMI_FW_ID_PSP_INTF',
    'AMDSMI_FW_ID_PSP_KEYDB', 'AMDSMI_FW_ID_PSP_SOC',
    'AMDSMI_FW_ID_PSP_SOSDRV', 'AMDSMI_FW_ID_PSP_SPL',
    'AMDSMI_FW_ID_PSP_SYSDRV', 'AMDSMI_FW_ID_PSP_TOC',
    'AMDSMI_FW_ID_REG_ACCESS_WHITELIST', 'AMDSMI_FW_ID_RLC',
    'AMDSMI_FW_ID_RLCV_LX7', 'AMDSMI_FW_ID_RLC_P',
    'AMDSMI_FW_ID_RLC_RESTORE_LIST_CNTL',
    'AMDSMI_FW_ID_RLC_RESTORE_LIST_GPM_MEM',
    'AMDSMI_FW_ID_RLC_RESTORE_LIST_SRM_MEM',
    'AMDSMI_FW_ID_RLC_SAVE_RESTORE_LIST', 'AMDSMI_FW_ID_RLC_SRLG',
    'AMDSMI_FW_ID_RLC_SRLS', 'AMDSMI_FW_ID_RLC_V',
    'AMDSMI_FW_ID_RLX6', 'AMDSMI_FW_ID_RLX6_CORE1',
    'AMDSMI_FW_ID_RLX6_DRAM_BOOT',
    'AMDSMI_FW_ID_RLX6_DRAM_BOOT_CORE1', 'AMDSMI_FW_ID_RS64_ME',
    'AMDSMI_FW_ID_RS64_MEC', 'AMDSMI_FW_ID_RS64_MEC_P0_DATA',
    'AMDSMI_FW_ID_RS64_MEC_P1_DATA', 'AMDSMI_FW_ID_RS64_MEC_P2_DATA',
    'AMDSMI_FW_ID_RS64_MEC_P3_DATA', 'AMDSMI_FW_ID_RS64_ME_P0_DATA',
    'AMDSMI_FW_ID_RS64_ME_P1_DATA', 'AMDSMI_FW_ID_RS64_PFP',
    'AMDSMI_FW_ID_RS64_PFP_P0_DATA', 'AMDSMI_FW_ID_RS64_PFP_P1_DATA',
    'AMDSMI_FW_ID_SDMA0', 'AMDSMI_FW_ID_SDMA1', 'AMDSMI_FW_ID_SDMA2',
    'AMDSMI_FW_ID_SDMA3', 'AMDSMI_FW_ID_SDMA4', 'AMDSMI_FW_ID_SDMA5',
    'AMDSMI_FW_ID_SDMA6', 'AMDSMI_FW_ID_SDMA7',
    'AMDSMI_FW_ID_SDMA_TH0', 'AMDSMI_FW_ID_SDMA_TH1',
    'AMDSMI_FW_ID_SEC_POLICY_STAGE2', 'AMDSMI_FW_ID_SMU',
    'AMDSMI_FW_ID_TA_RAS', 'AMDSMI_FW_ID_TA_XGMI', 'AMDSMI_FW_ID_UVD',
    'AMDSMI_FW_ID_VCE', 'AMDSMI_FW_ID_VCN', 'AMDSMI_FW_ID__MAX',
    'AMDSMI_GPU_BLOCK_ATHUB', 'AMDSMI_GPU_BLOCK_DF',
    'AMDSMI_GPU_BLOCK_FIRST', 'AMDSMI_GPU_BLOCK_FUSE',
    'AMDSMI_GPU_BLOCK_GFX', 'AMDSMI_GPU_BLOCK_HDP',
    'AMDSMI_GPU_BLOCK_IH', 'AMDSMI_GPU_BLOCK_INVALID',
    'AMDSMI_GPU_BLOCK_JPEG', 'AMDSMI_GPU_BLOCK_LAST',
    'AMDSMI_GPU_BLOCK_MCA', 'AMDSMI_GPU_BLOCK_MMHUB',
    'AMDSMI_GPU_BLOCK_MP0', 'AMDSMI_GPU_BLOCK_MP1',
    'AMDSMI_GPU_BLOCK_MPIO', 'AMDSMI_GPU_BLOCK_PCIE_BIF',
    'AMDSMI_GPU_BLOCK_RESERVED', 'AMDSMI_GPU_BLOCK_SDMA',
    'AMDSMI_GPU_BLOCK_SEM', 'AMDSMI_GPU_BLOCK_SMN',
    'AMDSMI_GPU_BLOCK_UMC', 'AMDSMI_GPU_BLOCK_VCN',
    'AMDSMI_GPU_BLOCK_XGMI_WAFL', 'AMDSMI_INIT_ALL_PROCESSORS',
    'AMDSMI_INIT_AMD_APUS', 'AMDSMI_INIT_AMD_CPUS',
    'AMDSMI_INIT_AMD_GPUS', 'AMDSMI_INIT_NON_AMD_CPUS',
    'AMDSMI_INIT_NON_AMD_GPUS', 'AMDSMI_IOLINK_TYPE_NUMIOLINKTYPES',
    'AMDSMI_IOLINK_TYPE_PCIEXPRESS', 'AMDSMI_IOLINK_TYPE_SIZE',
    'AMDSMI_IOLINK_TYPE_UNDEFINED', 'AMDSMI_IOLINK_TYPE_XGMI',
    'AMDSMI_LINK_TYPE_INTERNAL', 'AMDSMI_LINK_TYPE_NOT_APPLICABLE',
    'AMDSMI_LINK_TYPE_PCIE', 'AMDSMI_LINK_TYPE_UNKNOWN',
    'AMDSMI_LINK_TYPE_XGMI', 'AMDSMI_MEMORY_PARTITION_NPS1',
    'AMDSMI_MEMORY_PARTITION_NPS2', 'AMDSMI_MEMORY_PARTITION_NPS4',
    'AMDSMI_MEMORY_PARTITION_NPS8', 'AMDSMI_MEMORY_PARTITION_UNKNOWN',
    'AMDSMI_MEM_PAGE_STATUS_PENDING',
    'AMDSMI_MEM_PAGE_STATUS_RESERVED',
    'AMDSMI_MEM_PAGE_STATUS_UNRESERVABLE', 'AMDSMI_MEM_TYPE_FIRST',
    'AMDSMI_MEM_TYPE_GTT', 'AMDSMI_MEM_TYPE_LAST',
    'AMDSMI_MEM_TYPE_VIS_VRAM', 'AMDSMI_MEM_TYPE_VRAM',
    'AMDSMI_MM_UVD', 'AMDSMI_MM_VCE', 'AMDSMI_MM_VCN',
    'AMDSMI_MM__MAX', 'AMDSMI_PROCESSOR_TYPE_AMD_APU',
    'AMDSMI_PROCESSOR_TYPE_AMD_CPU',
    'AMDSMI_PROCESSOR_TYPE_AMD_CPU_CORE',
    'AMDSMI_PROCESSOR_TYPE_AMD_GPU',
    'AMDSMI_PROCESSOR_TYPE_NON_AMD_CPU',
    'AMDSMI_PROCESSOR_TYPE_NON_AMD_GPU',
    'AMDSMI_PROCESSOR_TYPE_UNKNOWN',
    'AMDSMI_PWR_PROF_PRST_3D_FULL_SCR_MASK',
    'AMDSMI_PWR_PROF_PRST_BOOTUP_DEFAULT',
    'AMDSMI_PWR_PROF_PRST_COMPUTE_MASK',
    'AMDSMI_PWR_PROF_PRST_CUSTOM_MASK',
    'AMDSMI_PWR_PROF_PRST_INVALID', 'AMDSMI_PWR_PROF_PRST_LAST',
    'AMDSMI_PWR_PROF_PRST_POWER_SAVING_MASK',
    'AMDSMI_PWR_PROF_PRST_VIDEO_MASK', 'AMDSMI_PWR_PROF_PRST_VR_MASK',
    'AMDSMI_RAS_ERR_STATE_DISABLED', 'AMDSMI_RAS_ERR_STATE_ENABLED',
    'AMDSMI_RAS_ERR_STATE_INVALID', 'AMDSMI_RAS_ERR_STATE_LAST',
    'AMDSMI_RAS_ERR_STATE_MULT_UC', 'AMDSMI_RAS_ERR_STATE_NONE',
    'AMDSMI_RAS_ERR_STATE_PARITY', 'AMDSMI_RAS_ERR_STATE_POISON',
    'AMDSMI_RAS_ERR_STATE_SING_C', 'AMDSMI_REG_PCIE',
    'AMDSMI_REG_USR', 'AMDSMI_REG_USR1', 'AMDSMI_REG_WAFL',
    'AMDSMI_REG_XGMI', 'AMDSMI_STATUS_ADDRESS_FAULT',
    'AMDSMI_STATUS_AMDGPU_RESTART_ERR', 'AMDSMI_STATUS_API_FAILED',
    'AMDSMI_STATUS_ARG_PTR_NULL', 'AMDSMI_STATUS_BUSY',
    'AMDSMI_STATUS_CORRUPTED_EEPROM',
    'AMDSMI_STATUS_DRIVER_NOT_LOADED', 'AMDSMI_STATUS_DRM_ERROR',
    'AMDSMI_STATUS_FAIL_LOAD_MODULE',
    'AMDSMI_STATUS_FAIL_LOAD_SYMBOL', 'AMDSMI_STATUS_FILE_ERROR',
    'AMDSMI_STATUS_FILE_NOT_FOUND', 'AMDSMI_STATUS_HSMP_TIMEOUT',
    'AMDSMI_STATUS_INIT_ERROR', 'AMDSMI_STATUS_INPUT_OUT_OF_BOUNDS',
    'AMDSMI_STATUS_INSUFFICIENT_SIZE',
    'AMDSMI_STATUS_INTERNAL_EXCEPTION', 'AMDSMI_STATUS_INTERRUPT',
    'AMDSMI_STATUS_INVAL', 'AMDSMI_STATUS_IO',
    'AMDSMI_STATUS_MAP_ERROR', 'AMDSMI_STATUS_MORE_DATA',
    'AMDSMI_STATUS_NON_AMD_CPU', 'AMDSMI_STATUS_NOT_FOUND',
    'AMDSMI_STATUS_NOT_INIT', 'AMDSMI_STATUS_NOT_SUPPORTED',
    'AMDSMI_STATUS_NOT_YET_IMPLEMENTED', 'AMDSMI_STATUS_NO_DATA',
    'AMDSMI_STATUS_NO_DRV', 'AMDSMI_STATUS_NO_ENERGY_DRV',
    'AMDSMI_STATUS_NO_HSMP_DRV', 'AMDSMI_STATUS_NO_HSMP_MSG_SUP',
    'AMDSMI_STATUS_NO_HSMP_SUP', 'AMDSMI_STATUS_NO_MSR_DRV',
    'AMDSMI_STATUS_NO_PERM', 'AMDSMI_STATUS_NO_SLOT',
    'AMDSMI_STATUS_OUT_OF_RESOURCES',
    'AMDSMI_STATUS_REFCOUNT_OVERFLOW', 'AMDSMI_STATUS_RETRY',
    'AMDSMI_STATUS_SETTING_UNAVAILABLE', 'AMDSMI_STATUS_SUCCESS',
    'AMDSMI_STATUS_TIMEOUT', 'AMDSMI_STATUS_UNEXPECTED_DATA',
    'AMDSMI_STATUS_UNEXPECTED_SIZE', 'AMDSMI_STATUS_UNKNOWN_ERROR',
    'AMDSMI_TEMPERATURE_TYPE_EDGE', 'AMDSMI_TEMPERATURE_TYPE_FIRST',
    'AMDSMI_TEMPERATURE_TYPE_HBM_0', 'AMDSMI_TEMPERATURE_TYPE_HBM_1',
    'AMDSMI_TEMPERATURE_TYPE_HBM_2', 'AMDSMI_TEMPERATURE_TYPE_HBM_3',
    'AMDSMI_TEMPERATURE_TYPE_HOTSPOT',
    'AMDSMI_TEMPERATURE_TYPE_JUNCTION', 'AMDSMI_TEMPERATURE_TYPE_PLX',
    'AMDSMI_TEMPERATURE_TYPE_VRAM', 'AMDSMI_TEMPERATURE_TYPE__MAX',
    'AMDSMI_TEMP_CRITICAL', 'AMDSMI_TEMP_CRITICAL_HYST',
    'AMDSMI_TEMP_CRIT_MIN', 'AMDSMI_TEMP_CRIT_MIN_HYST',
    'AMDSMI_TEMP_CURRENT', 'AMDSMI_TEMP_EMERGENCY',
    'AMDSMI_TEMP_EMERGENCY_HYST', 'AMDSMI_TEMP_FIRST',
    'AMDSMI_TEMP_HIGHEST', 'AMDSMI_TEMP_LAST', 'AMDSMI_TEMP_LOWEST',
    'AMDSMI_TEMP_MAX', 'AMDSMI_TEMP_MAX_HYST', 'AMDSMI_TEMP_MIN',
    'AMDSMI_TEMP_MIN_HYST', 'AMDSMI_TEMP_OFFSET',
    'AMDSMI_TEMP_SHUTDOWN', 'AMDSMI_UTILIZATION_COUNTER_FIRST',
    'AMDSMI_UTILIZATION_COUNTER_LAST',
    'AMDSMI_VIRTUALIZATION_MODE_BAREMETAL',
    'AMDSMI_VIRTUALIZATION_MODE_GUEST',
    'AMDSMI_VIRTUALIZATION_MODE_HOST',
    'AMDSMI_VIRTUALIZATION_MODE_PASSTHROUGH',
    'AMDSMI_VIRTUALIZATION_MODE_UNKNOWN', 'AMDSMI_VOLT_AVERAGE',
    'AMDSMI_VOLT_CURRENT', 'AMDSMI_VOLT_FIRST', 'AMDSMI_VOLT_HIGHEST',
    'AMDSMI_VOLT_LAST', 'AMDSMI_VOLT_LOWEST', 'AMDSMI_VOLT_MAX',
    'AMDSMI_VOLT_MAX_CRIT', 'AMDSMI_VOLT_MIN', 'AMDSMI_VOLT_MIN_CRIT',
    'AMDSMI_VOLT_TYPE_FIRST', 'AMDSMI_VOLT_TYPE_INVALID',
    'AMDSMI_VOLT_TYPE_LAST', 'AMDSMI_VOLT_TYPE_VDDGFX',
    'AMDSMI_VOLT_TYPE_VDDBOARD',
    'AMDSMI_VRAM_TYPE_DDR2', 'AMDSMI_VRAM_TYPE_DDR3',
    'AMDSMI_VRAM_TYPE_DDR4', 'AMDSMI_VRAM_TYPE_GDDR1',
    'AMDSMI_VRAM_TYPE_GDDR2', 'AMDSMI_VRAM_TYPE_GDDR3',
    'AMDSMI_VRAM_TYPE_GDDR4', 'AMDSMI_VRAM_TYPE_GDDR5',
    'AMDSMI_VRAM_TYPE_GDDR6', 'AMDSMI_VRAM_TYPE_GDDR7',
    'AMDSMI_VRAM_TYPE_HBM', 'AMDSMI_VRAM_TYPE_HBM2',
    'AMDSMI_VRAM_TYPE_HBM2E', 'AMDSMI_VRAM_TYPE_HBM3',
    'AMDSMI_VRAM_TYPE_UNKNOWN', 'AMDSMI_VRAM_TYPE__MAX',
    'AMDSMI_VRAM_VENDOR_ELPIDA', 'AMDSMI_VRAM_VENDOR_ESMT',
    'AMDSMI_VRAM_VENDOR_ETRON', 'AMDSMI_VRAM_VENDOR_HYNIX',
    'AMDSMI_VRAM_VENDOR_INFINEON', 'AMDSMI_VRAM_VENDOR_MICRON',
    'AMDSMI_VRAM_VENDOR_MOSEL', 'AMDSMI_VRAM_VENDOR_NANYA',
    'AMDSMI_VRAM_VENDOR_SAMSUNG', 'AMDSMI_VRAM_VENDOR_UNKNOWN',
    'AMDSMI_VRAM_VENDOR_WINBOND', 'AMDSMI_XGMI_LINK_DISABLE',
    'AMDSMI_XGMI_LINK_DOWN', 'AMDSMI_XGMI_LINK_UP',
    'AMDSMI_XGMI_STATUS_ERROR', 'AMDSMI_XGMI_STATUS_MULTIPLE_ERRORS',
    'AMDSMI_XGMI_STATUS_NO_ERRORS', 'CLK_LIMIT_MAX', 'CLK_LIMIT_MIN',
    'RD_BW0', 'WR_BW0', 'amd_metrics_table_header_t',
    'amdsmi_accelerator_partition_profile_config_t',
    'amdsmi_accelerator_partition_profile_t',
    'amdsmi_accelerator_partition_resource_profile_t',
    'amdsmi_accelerator_partition_resource_type_t',
    'amdsmi_accelerator_partition_type_t', 'amdsmi_asic_info_t',
    'amdsmi_bdf_t', 'amdsmi_bit_field_t', 'amdsmi_board_info_t',
    'amdsmi_cache_property_type_t', 'amdsmi_card_form_factor_t',
    'amdsmi_clean_gpu_local_data', 'amdsmi_clk_info_t',
    'amdsmi_clk_limit_type_t', 'amdsmi_clk_type_t',
    'amdsmi_compute_partition_type_t', 'amdsmi_container_types_t',
    'amdsmi_counter_command_t', 'amdsmi_counter_value_t',
    'amdsmi_cper_guid_t', 'amdsmi_cper_hdr_t',
    'amdsmi_cper_notify_type_t', 'amdsmi_cper_sev_t',
    'amdsmi_cper_timestamp_t', 'amdsmi_cper_valid_bits_t',
    'amdsmi_cpu_apb_disable', 'amdsmi_cpu_apb_enable',
    'amdsmi_cpusocket_handle', 'amdsmi_ddr_bw_metrics_t',
    'amdsmi_dev_perf_level_t', 'amdsmi_dimm_power_t',
    'amdsmi_dimm_thermal_t', 'amdsmi_dpm_level_t',
    'amdsmi_dpm_policy_entry_t', 'amdsmi_dpm_policy_t',
    'amdsmi_driver_info_t', 'amdsmi_engine_usage_t',
    'amdsmi_enumeration_info_t', 'amdsmi_error_count_t',
    'amdsmi_event_group_t', 'amdsmi_event_handle_t',
    'amdsmi_event_type_t', 'amdsmi_evt_notification_data_t',
    'amdsmi_evt_notification_type_t',
    'amdsmi_first_online_core_on_cpu_socket',
    'amdsmi_free_name_value_pairs', 'amdsmi_freq_ind_t',
    'amdsmi_freq_volt_region_t', 'amdsmi_frequencies_t',
    'amdsmi_frequency_range_t', 'amdsmi_fw_block_t',
    'amdsmi_fw_info_t', 'amdsmi_get_afids_from_cper',
    'amdsmi_get_clk_freq', 'amdsmi_get_clock_info',
    'amdsmi_get_cpu_cclk_limit', 'amdsmi_get_cpu_core_boostlimit',
    'amdsmi_get_cpu_core_current_freq_limit',
    'amdsmi_get_cpu_core_energy',
    'amdsmi_get_cpu_current_io_bandwidth',
    'amdsmi_get_cpu_current_xgmi_bw', 'amdsmi_get_cpu_ddr_bw',
    'amdsmi_get_cpu_dimm_power_consumption',
    'amdsmi_get_cpu_dimm_temp_range_and_refresh_rate',
    'amdsmi_get_cpu_dimm_thermal_sensor', 'amdsmi_get_cpu_family',
    'amdsmi_get_cpu_fclk_mclk', 'amdsmi_get_cpu_handles',
    'amdsmi_get_cpu_hsmp_driver_version',
    'amdsmi_get_cpu_hsmp_proto_ver', 'amdsmi_get_cpu_model',
    'amdsmi_get_cpu_prochot_status',
    'amdsmi_get_cpu_pwr_svi_telemetry_all_rails',
    'amdsmi_get_cpu_smu_fw_version',
    'amdsmi_get_cpu_socket_c0_residency',
    'amdsmi_get_cpu_socket_current_active_freq_limit',
    'amdsmi_get_cpu_socket_energy',
    'amdsmi_get_cpu_socket_freq_range',
    'amdsmi_get_cpu_socket_lclk_dpm_level',
    'amdsmi_get_cpu_socket_power', 'amdsmi_get_cpu_socket_power_cap',
    'amdsmi_get_cpu_socket_power_cap_max',
    'amdsmi_get_cpu_socket_temperature', 'amdsmi_get_cpucore_handles',
    'amdsmi_get_energy_count', 'amdsmi_get_esmi_err_msg',
    'amdsmi_get_fw_info',
    'amdsmi_get_gpu_accelerator_partition_profile',
    'amdsmi_get_gpu_accelerator_partition_profile_config',
    'amdsmi_get_gpu_activity', 'amdsmi_get_gpu_asic_info',
    'amdsmi_get_gpu_available_counters',
    'amdsmi_get_gpu_bad_page_info',
    'amdsmi_get_gpu_bad_page_threshold', 'amdsmi_get_gpu_bdf_id',
    'amdsmi_get_gpu_board_info', 'amdsmi_get_gpu_busy_percent',
    'amdsmi_get_gpu_cache_info', 'amdsmi_get_gpu_compute_partition',
    'amdsmi_get_gpu_compute_process_gpus',
    'amdsmi_get_gpu_compute_process_info',
    'amdsmi_get_gpu_compute_process_info_by_pid',
    'amdsmi_get_gpu_cper_entries', 'amdsmi_get_gpu_device_bdf',
    'amdsmi_get_gpu_device_uuid', 'amdsmi_get_gpu_driver_info',
    'amdsmi_get_gpu_ecc_count', 'amdsmi_get_gpu_ecc_enabled',
    'amdsmi_get_gpu_ecc_status', 'amdsmi_get_gpu_enumeration_info',
    'amdsmi_get_gpu_event_notification', 'amdsmi_get_gpu_fan_rpms',
    'amdsmi_get_gpu_fan_speed', 'amdsmi_get_gpu_fan_speed_max',
    'amdsmi_get_gpu_id', 'amdsmi_get_gpu_kfd_info',
    'amdsmi_get_gpu_mem_overdrive_level',
    'amdsmi_get_gpu_memory_partition',
    'amdsmi_get_gpu_memory_partition_config',
    'amdsmi_get_gpu_memory_reserved_pages',
    'amdsmi_get_gpu_memory_total', 'amdsmi_get_gpu_memory_usage',
    'amdsmi_get_gpu_metrics_header_info',
    'amdsmi_get_gpu_metrics_info',
    'amdsmi_get_gpu_od_volt_curve_regions',
    'amdsmi_get_gpu_od_volt_info', 'amdsmi_get_gpu_overdrive_level',
    'amdsmi_get_gpu_pci_bandwidth',
    'amdsmi_get_gpu_pci_replay_counter',
    'amdsmi_get_gpu_pci_throughput', 'amdsmi_get_gpu_perf_level',
    'amdsmi_get_gpu_pm_metrics_info',
    'amdsmi_get_gpu_power_profile_presets',
    'amdsmi_get_gpu_process_isolation', 'amdsmi_get_gpu_process_list',
    'amdsmi_get_gpu_ras_block_features_enabled',
    'amdsmi_get_gpu_ras_feature_info',
    'amdsmi_get_gpu_reg_table_info', 'amdsmi_get_gpu_revision',
    'amdsmi_get_gpu_subsystem_id', 'amdsmi_get_gpu_subsystem_name',
    'amdsmi_get_gpu_topo_numa_affinity',
    'amdsmi_get_gpu_total_ecc_count', 'amdsmi_get_gpu_vbios_info',
    'amdsmi_get_gpu_vendor_name',
    'amdsmi_get_gpu_virtualization_mode',
    'amdsmi_get_gpu_volt_metric', 'amdsmi_get_gpu_vram_info',
    'amdsmi_get_gpu_vram_usage', 'amdsmi_get_gpu_vram_vendor',
    'amdsmi_get_gpu_xcd_counter', 'amdsmi_get_gpu_xgmi_link_status',
    'amdsmi_get_hsmp_metrics_table',
    'amdsmi_get_hsmp_metrics_table_version', 'amdsmi_get_lib_version',
    'amdsmi_get_link_metrics', 'amdsmi_get_link_topology_nearest',
    'amdsmi_get_minmax_bandwidth_between_processors',
    'amdsmi_get_pcie_info', 'amdsmi_get_power_cap_info',
    'amdsmi_get_power_info', 'amdsmi_get_power_info_v2',
    'amdsmi_get_processor_count_from_handles',
    'amdsmi_get_processor_handle_from_bdf',
    'amdsmi_get_processor_handles',
    'amdsmi_get_processor_handles_by_type',
    'amdsmi_get_processor_info', 'amdsmi_get_processor_type',
    'amdsmi_get_soc_pstate', 'amdsmi_get_socket_handles',
    'amdsmi_get_socket_info', 'amdsmi_get_temp_metric',
    'amdsmi_get_threads_per_core', 'amdsmi_get_utilization_count',
    'amdsmi_get_violation_status', 'amdsmi_get_xgmi_info',
    'amdsmi_get_xgmi_plpd', 'amdsmi_gpu_block_t',
    'amdsmi_gpu_cache_info_t', 'amdsmi_gpu_control_counter',
    'amdsmi_gpu_counter_group_supported', 'amdsmi_gpu_create_counter',
    'amdsmi_gpu_destroy_counter', 'amdsmi_gpu_metrics_t',
    'amdsmi_gpu_read_counter', 'amdsmi_gpu_validate_ras_eeprom',
    'amdsmi_gpu_xcp_metrics_t', 'amdsmi_gpu_xgmi_error_status',
    'amdsmi_hsmp_driver_version_t', 'amdsmi_hsmp_freqlimit_src_names',
    'amdsmi_hsmp_metrics_table_t', 'amdsmi_init',
    'amdsmi_init_flags_t', 'amdsmi_init_gpu_event_notification',
    'amdsmi_io_bw_encoding_t', 'amdsmi_io_link_type_t',
    'amdsmi_is_P2P_accessible',
    'amdsmi_is_gpu_power_management_enabled', 'amdsmi_kfd_info_t',
    'amdsmi_link_id_bw_type_t', 'amdsmi_link_metrics_t',
    'amdsmi_link_type_t', 'amdsmi_memory_page_status_t',
    'amdsmi_memory_partition_config_t',
    'amdsmi_memory_partition_type_t', 'amdsmi_memory_type_t',
    'amdsmi_mm_ip_t', 'amdsmi_name_value_t', 'amdsmi_nps_caps_t',
    'amdsmi_od_vddc_point_t', 'amdsmi_od_volt_curve_t',
    'amdsmi_od_volt_freq_data_t', 'amdsmi_p2p_capability_t',
    'amdsmi_pcie_bandwidth_t', 'amdsmi_pcie_info_t',
    'amdsmi_power_cap_info_t', 'amdsmi_power_info_t',
    'amdsmi_power_profile_preset_masks_t',
    'amdsmi_power_profile_status_t', 'amdsmi_proc_info_t',
    'amdsmi_process_handle_t', 'amdsmi_process_info_t',
    'amdsmi_processor_handle', 'amdsmi_range_t',
    'amdsmi_ras_err_state_t', 'amdsmi_ras_feature_t',
    'amdsmi_reg_type_t', 'amdsmi_reset_gpu', 'amdsmi_reset_gpu_fan',
    'amdsmi_reset_gpu_xgmi_error', 'amdsmi_retired_page_record_t',
    'amdsmi_set_clk_freq', 'amdsmi_set_cpu_core_boostlimit',
    'amdsmi_set_cpu_df_pstate_range',
    'amdsmi_set_cpu_gmi3_link_width_range',
    'amdsmi_set_cpu_pcie_link_rate',
    'amdsmi_set_cpu_pwr_efficiency_mode',
    'amdsmi_set_cpu_socket_boostlimit',
    'amdsmi_set_cpu_socket_lclk_dpm_level',
    'amdsmi_set_cpu_socket_power_cap', 'amdsmi_set_cpu_xgmi_width',
    'amdsmi_set_gpu_accelerator_partition_profile',
    'amdsmi_set_gpu_clk_limit', 'amdsmi_set_gpu_clk_range',
    'amdsmi_set_gpu_compute_partition',
    'amdsmi_set_gpu_event_notification_mask',
    'amdsmi_set_gpu_fan_speed', 'amdsmi_set_gpu_memory_partition',
    'amdsmi_set_gpu_memory_partition_mode',
    'amdsmi_set_gpu_od_clk_info', 'amdsmi_set_gpu_od_volt_info',
    'amdsmi_set_gpu_overdrive_level', 'amdsmi_set_gpu_pci_bandwidth',
    'amdsmi_set_gpu_perf_determinism_mode',
    'amdsmi_set_gpu_perf_level', 'amdsmi_set_gpu_power_profile',
    'amdsmi_set_gpu_process_isolation', 'amdsmi_set_power_cap',
    'amdsmi_set_soc_pstate', 'amdsmi_set_xgmi_plpd',
    'amdsmi_shut_down', 'amdsmi_smu_fw_version_t',
    'amdsmi_socket_handle', 'amdsmi_status_code_to_string',
    'amdsmi_status_t', 'amdsmi_stop_gpu_event_notification',
    'amdsmi_temp_range_refresh_rate_t', 'amdsmi_temperature_metric_t',
    'amdsmi_temperature_type_t', 'amdsmi_topo_get_link_type',
    'amdsmi_topo_get_link_weight', 'amdsmi_topo_get_numa_node_number',
    'amdsmi_topo_get_p2p_status', 'amdsmi_topology_nearest_t',
    'amdsmi_utilization_counter_t',
    'amdsmi_utilization_counter_type_t', 'amdsmi_vbios_info_t',
    'amdsmi_version_t', 'amdsmi_violation_status_t',
    'amdsmi_virtualization_mode_t', 'amdsmi_voltage_metric_t',
    'amdsmi_voltage_type_t', 'amdsmi_vram_info_t',
    'amdsmi_vram_type_t', 'amdsmi_vram_usage_t',
    'amdsmi_vram_vendor_type_t', 'amdsmi_xgmi_info_t',
    'amdsmi_xgmi_link_status_t', 'amdsmi_xgmi_link_status_type_t',
    'amdsmi_xgmi_status_t', 'processor_type_t', 'size_t',
    'struct__links', 'struct_amd_metrics_table_header_t',
    'struct_amdsmi_accelerator_partition_profile_config_t',
    'struct_amdsmi_accelerator_partition_profile_t',
    'struct_amdsmi_accelerator_partition_resource_profile_t',
    'struct_amdsmi_asic_info_t', 'struct_amdsmi_board_info_t',
    'struct_amdsmi_clk_info_t', 'struct_amdsmi_counter_value_t',
    'struct_amdsmi_cper_guid_t', 'struct_amdsmi_cper_hdr_t',
    'struct_amdsmi_cper_timestamp_t',
    'struct_amdsmi_ddr_bw_metrics_t', 'struct_amdsmi_dimm_power_t',
    'struct_amdsmi_dimm_thermal_t', 'struct_amdsmi_dpm_level_t',
    'struct_amdsmi_dpm_policy_entry_t', 'struct_amdsmi_dpm_policy_t',
    'struct_amdsmi_driver_info_t', 'struct_amdsmi_engine_usage_t',
    'struct_amdsmi_enumeration_info_t', 'struct_amdsmi_error_count_t',
    'struct_amdsmi_evt_notification_data_t',
    'struct_amdsmi_freq_volt_region_t', 'struct_amdsmi_frequencies_t',
    'struct_amdsmi_frequency_range_t', 'struct_amdsmi_fw_info_t',
    'struct_amdsmi_gpu_cache_info_t', 'struct_amdsmi_gpu_metrics_t',
    'struct_amdsmi_gpu_xcp_metrics_t',
    'struct_amdsmi_hsmp_driver_version_t',
    'struct_amdsmi_hsmp_metrics_table_t', 'struct_amdsmi_kfd_info_t',
    'struct_amdsmi_link_id_bw_type_t', 'struct_amdsmi_link_metrics_t',
    'struct_amdsmi_memory_partition_config_t',
    'struct_amdsmi_name_value_t', 'struct_amdsmi_od_vddc_point_t',
    'struct_amdsmi_od_volt_curve_t',
    'struct_amdsmi_od_volt_freq_data_t',
    'struct_amdsmi_p2p_capability_t',
    'struct_amdsmi_pcie_bandwidth_t', 'struct_amdsmi_pcie_info_t',
    'struct_amdsmi_power_cap_info_t', 'struct_amdsmi_power_info_t',
    'struct_amdsmi_power_profile_status_t',
    'struct_amdsmi_proc_info_t', 'struct_amdsmi_process_info_t',
    'struct_amdsmi_range_t', 'struct_amdsmi_ras_feature_t',
    'struct_amdsmi_retired_page_record_t',
    'struct_amdsmi_smu_fw_version_t',
    'struct_amdsmi_temp_range_refresh_rate_t',
    'struct_amdsmi_topology_nearest_t',
    'struct_amdsmi_utilization_counter_t',
    'struct_amdsmi_vbios_info_t', 'struct_amdsmi_version_t',
    'struct_amdsmi_violation_status_t', 'struct_amdsmi_vram_info_t',
    'struct_amdsmi_vram_usage_t', 'struct_amdsmi_xgmi_info_t',
    'struct_amdsmi_xgmi_link_status_t', 'struct_cache_',
    'struct_engine_usage_', 'struct_fw_info_list_',
    'struct_memory_usage_', 'struct_nps_flags_', 'struct_numa_range_',
    'struct_pcie_metric_', 'struct_pcie_static_',
    'struct_amdsmi_bdf_t', 'struct_valid_bits_', 'uint32_t',
    'uint64_t', 'uint8_t', 'union_amdsmi_bdf_t',
    'union_amdsmi_cper_valid_bits_t', 'union_amdsmi_nps_caps_t']


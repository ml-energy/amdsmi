# 🐍 Python Bindings for AMDSMI

Community-maintained Python bindings for [AMDSMI](https://github.com/ROCm/amdsmi).

Whenever a new [release](https://github.com/ROCm/amdsmi/releases) is published to the official AMDSMI repository, we run a simple script to checkout the `py-interface` directory of the tag and push it to this repository and PyPI.
For the source code and API documentation, please see [`py-interface`](/py-interface).

> [!NOTE]
> At this time, there are no official Python bindings for AMDSMI on PyPI. Rather, bindings are distributed together with ROCm, which complicates dependency management and installation. Thus, we created this community-maintained binding package.
>
> When AMD intends to officially maintain the `amdsmi` package on PyPI, we are happy to transfer ownership. Please contact the current maintainers Parth Raut (<praut@umich.edu>) and Jae-Won Chung (<jwnchung@umich.edu>).

## 🚀 Installation

```
pip install amdsmi
```

> [!IMPORTANT]
> 1. Ensure your ROCm version matches the `amdsmi` package version. For instance, if you are using ROCm 6.2.1, run `pip install amdsmi==6.2.1`. (See [Versioning](#-versioning) for detais.)
> 2. Ensure you have `libamd_smi.so` in your system. It's shipped together with ROCm. Search order:
>    1. `site-packages/amdsmi/libamd_smi.so` (inside the `amdsmi` installation directory; useful for debugging/dev)
>    2. If environment variable `ROCM_PATH` is set, `$ROCM_PATH/lib/libamd_smi.so`
>    3. (Since 6.2.3) If environment variable `ROCM_PATH` is **not** set, `/opt/rocm/lib/libamd_smi.so`

## 📦 Versioning

AMDSMI seems to have two parallel release strategies:  
1. AMDSMI package releases, based on year, month, and revision (e.g., 24.5.0).
2. ROCm-based releases, which is released whenever a new ROCm version is released (e.g., 6.2.2).

At the moment, we adopt the second ROCm-based versioning strategy. So, the `amdsmi` package version is identical to the ROCm version the bindings are released against.

See [here](https://pypi.org/project/amdsmi/#history) for a full list of releases.

## ❗ Bug Reports

Most issues would be better off reported directly to [ROCm/amdsmi](https://github.com/ROCm/amdsmi). If you believe the bug is specific to the bindings package, please file an issue on this repository.
